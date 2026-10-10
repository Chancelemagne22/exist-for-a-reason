"""
EFAR - Ask (full RAG pipeline, end to end)

Question -> retrieve relevant Roblox doc chunks from Supabase -> build a
grounded prompt -> send to your Modal endpoint -> print the answer.

This is the same logic that will eventually live in the Next.js API route -
this script just lets us test and tune it before wiring up a frontend.

Requires:
  pip install fastembed psycopg2-binary python-dotenv pgvector requests

Requires in .env:
  SUPABASE_DB_URL=...
  MODAL_ENDPOINT_URL=...   (e.g. https://your-workspace--efar-serve.modal.run)
"""

import os
import sys
import re
import json
import time
import uuid
from pathlib import Path
import requests
from dotenv import load_dotenv

from retrieve import retrieve, build_context_block, is_killbrick_query
from validation import validate_answer, post_validate_and_clean as _shared_clean

# Windows consoles default to cp1252, which crashes on emoji/model unicode
# (e.g. ✅ in audit logs). Force UTF-8 with replacement so a print can never
# lose an already-paid-for answer (see Oct 2026 killbrick retest).
if sys.stdout is not None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Load .env from repo root even when run as `python rag/ask.py` from root
# (load_dotenv without args only checks cwd, so `cd rag` runs missed it).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Resolve relative to this file so `python rag/ask.py` works from repo root and from rag/.
SYSTEM_PROMPT_FILE = str(Path(__file__).resolve().parent.parent / "system_prompt.md")
TOP_K = 3               # default; retrieve() auto-bumps to TUTORIAL_TOP_K=8
                        # for multi-concept builds (see retrieve.is_tutorial_query).
                        # Old note: vector matches beyond ~3 were noise for
                        # single-concept Pathfinding queries — still true there.
MAX_TOKENS = 2048  # match app.py RESERVED_FOR_OUTPUT: Qwen3.5 reasoning (~900 toks on big
               # RAG prompts) + answer must fit; 900 starved content to empty
SAFETY_MARGIN = 500          # increased from 300
MIN_RESPONSE_TOKENS = 400    # increased from 200       # preferred/ceiling response length, used when budget allows
# Must match --max-model-len in modal_app.py (default 16384) and MAX_MODEL_LEN in rag/app.py.
# Reads env with fallback so .env is single source of truth.
MAX_MODEL_LEN = int(os.environ.get("MAX_MODEL_LEN", "16384"))
TEMPERATURE = 0.3
REPETITION_PENALTY = 1.15
# Cold-start retry: Dedicated scales to zero, first request wakes 1 container
# (15-60s+) and proxy may 503 while starting. Retry instead of hard-failing.
MODAL_RETRY_DELAYS = [15, 30, 60]
RETRYABLE_STATUSES = {502, 503, 504}
# One affinity key per CLI run = one conversation, keeps prefix cache warm.
_AFFINITY_KEY = uuid.uuid4().hex


def _modal_headers_with_affinity(base_headers, affinity_key):
    """Copy auth headers + add Modal affinity routing so follow-ups land warm."""
    headers = dict(base_headers or {})
    if affinity_key:
        headers["Modal-Routing-Affinity-Key"] = affinity_key
    return headers


def _post_with_coldstart_retry(url, headers, payload, stream=False):
    """POST with retry on 502/503/504 (scale-from-zero). Raises last error."""
    last_exc = None
    for attempt, delay in enumerate([0] + MODAL_RETRY_DELAYS):
        if attempt:
            print(
                f"Modal cold start (attempt {attempt + 1}/{len(MODAL_RETRY_DELAYS) + 1}): "
                f"container still starting, retrying in {delay}s...",
                flush=True,
            )
            time.sleep(delay)
        try:
            resp = requests.post(url, headers=headers, json=payload, stream=stream, timeout=(10, 300))
        except requests.exceptions.ConnectionError as e:
            print(f"Connection error (attempt {attempt + 1}): {e}", flush=True)
            last_exc = e
            continue
        if resp.status_code in RETRYABLE_STATUSES:
            print(
                f"Modal returned {resp.status_code} (attempt {attempt + 1}): "
                f"{resp.text[:300]}",
                flush=True,
            )
            last_exc = requests.exceptions.HTTPError(
                f"{resp.status_code} Server Error for url: {url}", response=resp
            )
            continue
        return resp
    if last_exc:
        raise last_exc
    raise RuntimeError("Modal retry loop exhausted without response")

# --- Post-generation validation ---
# Single source of truth lives in rag/validation.py (imported above).
# Do NOT add local checks here — add them there so CLI and Streamlit stay in sync.


def load_game_context():
    try:
        with open(SYSTEM_PROMPT_FILE, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""  # fine to run without it, just less personalized


def build_messages(question, context_block, game_context):
    # 1. Base persona and general instruction
    system_parts = [
        "You are EFAR, a coding assistant specialized in Roblox development (Luau, Studio APIs, game architecture).",
        "Answer using the reference documentation provided below whenever it's relevant. "
        "If the documentation doesn't cover something, say so rather than guessing or inventing API details."
    ]
    
    # 2. Append bulk project context early
    if game_context.strip():
        system_parts.append(f"### Project Context:\n{game_context.strip()}")
        
    # 3. Append the heavy reference documentation block in the middle
    if context_block.strip():
        system_parts.append(f"### Reference Documentation:\n{context_block.strip()}")
        
    # 4. CRITICAL RULES - Placed at the absolute end so they stay highly activated in attention.
    # Task router: kill-brick builds get kill-brick laws (placement, character
    # resolution, player filter, per-player debounce). Everything else keeps
    # the original Pathfinding laws. Sending Pathfinding waypoint laws on a
    # Touched kill-brick wastes attention and caused the Oct 2026 deathtile
    # failures (see evals/killbrick/).
    base_rules = [
        "### CRITICAL LAWS YOU MUST FOLLOW STRICTLY:",
        "1. DEPRECATION: Never use properties or methods marked DEPRECATED. Use the recommended replacements instead.",
        "2. STRICT API: Only use properties and methods that explicitly appear in the reference documentation above. Do not invent parameters, Studio UI, or API details.",
        "3. MODELS: Roblox Models do not have a .Position property. Use model:GetPivot().Position or model.PrimaryPart.Position.",
    ]
    if is_killbrick_query(question):
        base_rules += [
            "4. KILL-BRICK PLACEMENT: The server Script MUST be a CHILD of the kill Part "
            "(Workspace > DeathTile > Script) so `script.Parent` is the part. NEVER place it in "
            "ServerScriptService while doing `local part = script.Parent` — that service has no Touched event. "
            "Parts have NO 'Script field' in the Properties window; parenting in Explorer IS the connection.",
            "5. CHARACTER RESOLUTION: `Touched:Connect(function(hit)` gives you a LIMB part (e.g. LowerLeg), "
            "NOT the character. Resolve with `local character = hit:FindFirstAncestorOfClass(\"Model\")` "
            "and `local humanoid = character:FindFirstChildOfClass(\"Humanoid\")`. NEVER treat `hit` itself as the player.",
            "6. PLAYER-ONLY FILTER: NPCs and dummies also have Humanoids AND HumanoidRootParts. The ONLY reliable "
            "real-player check is `local player = Players:GetPlayerFromCharacter(character); if not player then return end`. "
            "NEVER use FindFirstChildWhichIsA(\"HumanoidRootPart\") — that is an instance NAME, not a class, and always returns nil.",
            "7. DEBOUNCE: Touched fires once per limb. Use a PER-PLAYER table: `local debounce = {}` + "
            "`if debounce[player] then return end` + `task.delay(COOLDOWN, function() debounce[player] = nil end)` "
            "+ `Players.PlayerRemoving` cleanup. NEVER use a single shared boolean/attribute — it blocks all players.",
            "8. VERIFICATION: Before outputting, cross-verify every single method call against the provided documentation to ensure it exists.",
        ]
    else:
        base_rules += [
            "4. ENUMS: Use exact enum names from the documentation (e.g., Enum.PathStatus.Success). Never substitute terms like 'Complete'.",
            "5. PATHFINDING MOVEMENT: To move an NPC along a path, you MUST fetch waypoints and iterate through them using Humanoid:MoveTo() and MoveToFinished:Wait(). Never teleport characters via CFrame loops. Use this exact pattern:\n"
            "   local waypoints = path:GetWaypoints()\n"
            "   for _, waypoint in ipairs(waypoints) do\n"
            "       humanoid:MoveTo(waypoint.Position)\n"
            "       humanoid.MoveToFinished:Wait()\n"
            "   end",
            "6. STATUS CHECK: Always check if Path.Status == Enum.PathStatus.Success after ComputeAsync before iterating over waypoints. Handle non-Success states with warnings.",
            "7. VERIFICATION: Before outputting, cross-verify every single method call against the provided documentation to ensure it exists.",
        ]
    system_parts.append("\n".join(base_rules))

    # Assemble the final system block
    system_message = "\n\n".join(system_parts)

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": question},
    ]


def build_followup_message(question, context_block):
    """
    Build a follow-up user turn. Keeps the original system message and full
    conversation history intact, just adds fresh retrieved docs relevant to
    THIS follow-up (e.g. if the correction mentions a different class/method
    than the original question did) inline with the message itself.
    """
    parts = [question]
    if context_block.strip():
        parts.append(
            "\n\n(Additional reference documentation relevant to this "
            "follow-up:\n" + context_block + ")"
        )
    return {"role": "user", "content": "".join(parts)}


def trim_conversation_to_fit(messages, budget):
    """
    Hard safety net: if messages are still too large for the context window
    even after context dedup, drop the OLDEST completed (user, assistant)
    turn-pairs - keeping the system message and the newest, not-yet-answered
    user message always - until the estimate fits. This is a blunt fallback,
    not the primary fix (context dedup in run_turn is); it exists in case a
    follow-up genuinely needs a lot of fresh, non-overlapping context.
    """
    if not messages:
        return messages, 0

    has_system = messages[0]["role"] == "system"
    system_msg = [messages[0]] if has_system else []
    body = messages[1:] if has_system else list(messages)

    # The last message is the newest user turn (not yet answered) - always keep it.
    trailing = [body[-1]] if body and body[-1]["role"] == "user" else []
    middle = body[:-1] if trailing else body

    dropped_pairs = 0
    while middle and estimate_tokens(system_msg + middle + trailing) > budget:
        # Drop oldest complete pair (user, assistant) together, so the
        # conversation structure stays valid.
        middle = middle[2:] if len(middle) >= 2 else middle[1:]
        dropped_pairs += 1

    return system_msg + middle + trailing, dropped_pairs


def estimate_tokens(messages):
    # Use 4 chars per token – more realistic for code + markup.
    return sum(len(m["content"]) for m in messages) // 4


def ask_modal(messages):
    endpoint = os.environ.get("MODAL_ENDPOINT_URL")
    if not endpoint:
        raise SystemExit("MODAL_ENDPOINT_URL not found in .env")

    url = endpoint.rstrip("/")
    if not url.endswith("/v1/chat/completions"):
        url += "/v1/chat/completions"

    # Dedicated Endpoint auth + model (M2). Empty token = legacy DIY unauthenticated.
    # Source of truth for model is dashboard Endpoints -> Quickstart request
    # example (currently "Qwen/Qwen3.5-4B" for efar-coder). `roblox-coder` only for DIY rollback.
    modal_model = os.environ.get("MODAL_MODEL", "Qwen/Qwen3.5-4B").strip() or "Qwen/Qwen3.5-4B"
    proxy_token = os.environ.get("MODAL_PROXY_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {proxy_token}"} if proxy_token else {}

    safety_margin = SAFETY_MARGIN      # buffer for estimation error + special/role tokens
    min_response_reserve = MIN_RESPONSE_TOKENS # don't trim history so hard the response has no room

    # Safety net: if even after context dedup (see run_turn) the conversation
    # is too large, drop the oldest turns rather than erroring outright.
    prompt_budget = MAX_MODEL_LEN - min_response_reserve - safety_margin
    messages, dropped_pairs = trim_conversation_to_fit(messages, prompt_budget)
    if dropped_pairs:
        print(
            f"(Note: dropped the oldest {dropped_pairs} turn(s) from conversation "
            f"history to fit within the {MAX_MODEL_LEN}-token context window.)"
        )

    approx_prompt_tokens = estimate_tokens(messages)
    available = MAX_MODEL_LEN - approx_prompt_tokens - safety_margin
    max_tokens = max(200, min(MAX_TOKENS, available))

    if max_tokens < MAX_TOKENS:
        print(
            f"(Note: trimming max_tokens to {max_tokens} to fit within the "
            f"{MAX_MODEL_LEN}-token context window - conversation history is "
            f"getting long.)",
            flush=True,
        )

    payload = {
        "model": modal_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": TEMPERATURE,
        "repetition_penalty": REPETITION_PENALTY,
        # Qwen3.5 is a reasoning model: without this, ~900-2000 thinking tokens
        # eat max_tokens and content comes back empty. Proven 259->0 in probe.
        "chat_template_kwargs": {"enable_thinking": False},
    }

    print("Sending to Modal (cold start may take 15-60s if idle, auto-retries on 503)...", flush=True)
    print(f"Endpoint: {url} | model: {modal_model} | auth: {'proxy-token' if headers else 'none'}", flush=True)
    headers = _modal_headers_with_affinity(headers, _AFFINITY_KEY)
    # (connect=10s so DNS/TLS hangs fail fast, read=300s for cold start + generation)
    resp = _post_with_coldstart_retry(url, headers, payload, stream=False)
    if resp.status_code == 401:
        print("\nModal returned 401 Unauthorized. Check MODAL_PROXY_TOKEN in your .env.", flush=True)
        resp.raise_for_status()
    if not resp.ok:
        print(f"\nModal returned {resp.status_code}. Response body:", flush=True)
        print(resp.text)
        resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"], data.get("usage", {}), messages


def ask_modal_stream(messages):
    """Streaming variant mirroring rag/app.py - prints tokens live so the
    terminal never looks hung on Dedicated cold starts."""
    endpoint = os.environ.get("MODAL_ENDPOINT_URL")
    if not endpoint:
        raise SystemExit("MODAL_ENDPOINT_URL not found in .env")

    url = endpoint.rstrip("/")
    if not url.endswith("/v1/chat/completions"):
        url += "/v1/chat/completions"

    modal_model = os.environ.get("MODAL_MODEL", "Qwen/Qwen3.5-4B").strip() or "Qwen/Qwen3.5-4B"
    proxy_token = os.environ.get("MODAL_PROXY_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {proxy_token}"} if proxy_token else {}

    safety_margin = SAFETY_MARGIN
    min_response_reserve = MIN_RESPONSE_TOKENS

    prompt_budget = MAX_MODEL_LEN - min_response_reserve - safety_margin
    messages, dropped_pairs = trim_conversation_to_fit(messages, prompt_budget)
    if dropped_pairs:
        print(
            f"(Note: dropped the oldest {dropped_pairs} turn(s) to fit "
            f"within the {MAX_MODEL_LEN}-token window.)",
            flush=True,
        )

    approx_prompt_tokens = estimate_tokens(messages)
    available = MAX_MODEL_LEN - approx_prompt_tokens - safety_margin
    max_tokens = max(200, min(MAX_TOKENS, available))

    payload = {
        "model": modal_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": TEMPERATURE,
        "repetition_penalty": REPETITION_PENALTY,
        "stream": True,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    print("Sending to Modal (streaming, cold start may take 15-60s, auto-retries on 503)...", flush=True)
    print(f"Endpoint: {url} | model: {modal_model} | auth: {'proxy-token' if headers else 'none'}", flush=True)
    headers = _modal_headers_with_affinity(headers, _AFFINITY_KEY)
    resp = _post_with_coldstart_retry(url, headers, payload, stream=True)
    if resp.status_code == 401:
        print("\nModal returned 401 Unauthorized. Check MODAL_PROXY_TOKEN in your .env.", flush=True)
        resp.raise_for_status()
    resp.raise_for_status()

    print("\n--- streaming ---\n", flush=True)
    raw_parts = []
    for line in resp.iter_lines():
        if not line:
            continue
        decoded = line.decode("utf-8").strip()
        if not decoded.startswith("data: "):
            continue
        content = decoded[6:]
        if content == "[DONE]":
            break
        try:
            chunk = json.loads(content)
            token = chunk["choices"][0]["delta"].get("content", "")
        except Exception:
            continue
        if token:
            raw_parts.append(token)
            print(token, end="", flush=True)
    print("\n\n--- end stream ---\n", flush=True)
    return "".join(raw_parts), {}, messages


def run_turn(question, messages, game_context, covered, use_retrieval=True, stream=False):
    """
    Runs one turn: retrieves docs for `question`, skips any chunk already
    sent in an earlier turn (tracked via `covered`, a set of (title, section)
    tuples) so the same class docs aren't sent twice as history grows, builds
    the appropriate message, sends the conversation to Modal, prints the
    answer + validation warnings, and returns (updated messages, updated
    covered set) for use in the next turn.

    use_retrieval=False skips Supabase/FastEmbed entirely (fast Modal-only
    smoke test, e.g. `print hello`). stream=True mirrors app.py live tokens.
    """
    if use_retrieval:
        print("\nRetrieving relevant docs...", flush=True)
        results = retrieve(question, top_k=TOP_K)

        new_results = [r for r in results if (r["title"], r["section"]) not in covered]
        skipped = len(results) - len(new_results)
        if skipped and messages:
            print(
                f"Retrieved {len(results)} chunks, {skipped} already sent earlier "
                f"in this conversation (skipping to save context space).",
                flush=True,
            )
        else:
            print(f"Retrieved {len(results)} chunks: {[r['title'] for r in results]}", flush=True)

        context_block = build_context_block(new_results)
        covered = covered | {(r["title"], r["section"]) for r in results}
    else:
        print("\n(Skipping retrieval: --no-retrieval Modal-only test.)", flush=True)
        context_block = ""

    if not messages:
        messages = build_messages(question, context_block, game_context)
    else:
        messages = messages + [build_followup_message(question, context_block)]

    # 1. Fetch the raw response string from your Dedicated endpoint
    if stream:
        raw_answer, usage, messages = ask_modal_stream(messages)
    else:
        raw_answer, usage, messages = ask_modal(messages)

    # 2. Intercept and auto-correct 7B micro-quirks (magnitude, unit, wait)
    clean_answer, corrections = post_validate_and_clean(raw_answer)

    # 3. Print the cleaned code/response
    print("\n" + "=" * 60)
    print("ANSWER:")
    print("=" * 60)
    print(clean_answer)

    # 4. Print the micro-linter logs right below the answer
    if corrections:
        print("\n------------------------------------------------------------")
        print("EFAR PIPELINE AUTO-CORRECTIONS:")
        print("------------------------------------------------------------")
        for log in corrections:
            print(f"  {log}")

    # 5. Run structural checks (like missing waypoints) on the cleaned code
    warnings = validate_answer(clean_answer)
    if warnings:
        print("\n" + "=" * 60)
        print("⚠️  VALIDATION WARNINGS (review before using this code):")
        print("=" * 60)
        for w in warnings:
            print(f"- {w}")

    print("\n" + "=" * 60)
    print(f"Tokens used: {usage}")

    # 6. Save the sanitized text into memory so the model stays clean next turn
    messages = messages + [{"role": "assistant", "content": clean_answer}]
    return messages, covered


def post_validate_and_clean(response_text: str) -> tuple[str, list[str]]:
    """CLI wrapper around validation.post_validate_and_clean (adds CLI icons)."""
    cleaned_text, plain_logs = _shared_clean(response_text)
    icon_map = {
        "Auto-corrected legacy `.magnitude`": "✅ Auto-corrected legacy `.magnitude` to PascalCase `.Magnitude`",
        "Auto-corrected legacy `.unit`": "✅ Auto-corrected legacy `.unit` to PascalCase `.Unit`",
        "Upgraded deprecated global": "🚀 Upgraded deprecated global `wait()` to performance-optimized `task.wait()`",
        "LINT WARNING": "⚠️ LINT WARNING: Detected server-side `CharacterAdded:Wait()`. "
                        "If a player leaves right as this fires, the server thread will hang indefinitely.",
    }
    icon_logs = []
    for log in plain_logs:
        for key, icon_msg in icon_map.items():
            if key in log:
                icon_logs.append(icon_msg)
                break
        else:
            icon_logs.append(log)
    return cleaned_text, icon_logs


def parse_cli_args(argv):
    """Split `python rag/ask.py <question> [--no-retrieval] [--stream] [--once]`."""
    use_retrieval = True
    stream = False
    once = False
    parts = []
    for a in argv:
        if a == "--no-retrieval":
            use_retrieval = False
        elif a == "--stream":
            stream = True
        elif a in ("--once", "--no-followup"):
            once = True
        else:
            parts.append(a)
    question = " ".join(parts) or "How do I use PathfindingService to move an NPC?"
    return question, use_retrieval, stream, once


def main():
    question, use_retrieval, stream, once = parse_cli_args(sys.argv[1:])
    print(f"Question: {question}", flush=True)
    print(f"Mode: retrieval={'on' if use_retrieval else 'OFF'} | stream={'on' if stream else 'off'} | endpoint=Dedicated efar-coder", flush=True)

    game_context = load_game_context()
    covered = set()

    messages = []
    current_input = question
    first_turn = True

    while True:
        # Executes the full turn pipeline linearly
        messages, covered = run_turn(current_input, messages, game_context, covered,
                                     use_retrieval=use_retrieval, stream=stream)

        if once:
            break

        if first_turn:
            print("\n" + "-" * 60)
            print("Enter a follow-up (e.g. paste an error or a correction), or ")
            print("press Enter/type 'exit' to quit.")
            print("-" * 60)
            first_turn = False

        try:
            followup = input("\nFollow-up> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not followup or followup.lower() in ("exit", "quit"):
            break
            
        current_input = followup


if __name__ == "__main__":
    main()