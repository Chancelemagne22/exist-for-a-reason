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
from pathlib import Path
import requests
from dotenv import load_dotenv

from retrieve import retrieve, build_context_block

load_dotenv()

# Resolve relative to this file so `python rag/ask.py` works from repo root and from rag/.
SYSTEM_PROMPT_FILE = str(Path(__file__).resolve().parent.parent / "system_prompt.md")
TOP_K = 3               # lowered from 5 - vector matches beyond ~3 were mostly
                        # noise (e.g. ServerScriptService, Luau globals) that
                        # ate context budget without adding relevant grounding
MAX_TOKENS = 900
SAFETY_MARGIN = 500          # increased from 300
MIN_RESPONSE_TOKENS = 400    # increased from 200       # preferred/ceiling response length, used when budget allows
# Must match --max-model-len in modal_app.py (default 16384) and MAX_MODEL_LEN in rag/app.py.
# Reads env with fallback so .env is single source of truth.
MAX_MODEL_LEN = int(os.environ.get("MAX_MODEL_LEN", "16384"))
TEMPERATURE = 0.3
REPETITION_PENALTY = 1.15

# --- Post-generation validation ---
# This is a fallback safety net, not a replacement for good retrieval/prompting.
# It catches known hallucination patterns for the classes we've actually tested
# (PathfindingService/Path so far) by pattern-matching the generated Lua code
# against a small hardcoded list of what's real. It will NOT catch novel
# hallucinations on classes not covered here - expand these sets as new
# failure patterns turn up on new test questions.

VALID_PATHSTATUS_VALUES = {
    "Success", "NoPath", "ClosestNoPath", "ClosestOutOfRange",
    "FailStartNotEmpty", "FailFinishNotEmpty", "Unknown",
}
VALID_PATH_EVENTS = {"Blocked"}
DEPRECATED_PATHFINDING_METHODS = {
    "FindPathAsync", "ComputeRawPathAsync", "ComputeSmoothPathAsync",
    "CheckOcclusionAsync", "GetPointCoordinates",
}


def validate_answer(answer):
    """
    Scan generated Lua code for known hallucination/deprecation patterns.
    Returns a list of warning strings (empty if nothing suspicious found).
    """
    warnings = []

    # Deprecated methods used despite being told not to
    for method in DEPRECATED_PATHFINDING_METHODS:
        if re.search(rf"\b{re.escape(method)}\s*\(", answer):
            warnings.append(
                f"Uses '{method}', which is DEPRECATED. Check the reference docs "
                f"for the recommended replacement."
            )

    # Invented Enum.PathStatus values
    for match in re.finditer(r"Enum\.PathStatus\.(\w+)", answer):
        value = match.group(1)
        if value not in VALID_PATHSTATUS_VALUES:
            warnings.append(
                f"Uses 'Enum.PathStatus.{value}', which is not a real PathStatus value. "
                f"Valid values: {', '.join(sorted(VALID_PATHSTATUS_VALUES))}."
            )

    # Invented Path events (path.X:Connect(...) where X isn't a real event)
    for match in re.finditer(r"\bpath\.(\w+):Connect\s*\(", answer, re.IGNORECASE):
        event = match.group(1)
        if event not in VALID_PATH_EVENTS:
            warnings.append(
                f"Connects to 'path.{event}', which is not a documented Path event. "
                f"Valid events: {', '.join(sorted(VALID_PATH_EVENTS))}."
            )

    # ComputeAsync is void - flag if the code tries to capture a return value
    if re.search(r"local\s+\w+(?:\s*,\s*\w+)*\s*=\s*[\w.]*:ComputeAsync\s*\(", answer):
        warnings.append(
            "Captures a return value from ':ComputeAsync()', but this method returns "
            "nothing (void). Check Path.Status after calling it instead."
        )

    # CreatePath/ComputeAsync present but waypoints never retrieved or followed -
    # usually means the answer silently skipped pathfinding and just did a
    # single MoveTo() straight to the destination.
    creates_path = re.search(r":CreatePath\s*\(", answer) or re.search(r":ComputeAsync\s*\(", answer)
    uses_waypoints = re.search(r":GetWaypoints\s*\(", answer)
    if creates_path and not uses_waypoints:
        warnings.append(
            "Calls CreatePath/ComputeAsync but never calls GetWaypoints() - the path "
            "may not actually be followed (check for a single MoveTo() straight to "
            "the target instead of waypoint-by-waypoint movement)."
        )

    return warnings


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
        
    # 4. CRITICAL RULES - Placed at the absolute end so they stay highly activated in attention
    rules = [
        "### CRITICAL LAWS YOU MUST FOLLOW STRICTLY:",
        "1. DEPRECATION: Never use properties or methods marked DEPRECATED. Use the recommended replacements instead.",
        "2. STRICT API: Only use properties and methods that explicitly appear in the reference documentation above. Do not invent parameters or API details.",
        "3. MODELS: Roblox Models do not have a .Position property. Use model:GetPivot().Position or model.PrimaryPart.Position.",
        "4. ENUMS: Use exact enum names from the documentation (e.g., Enum.PathStatus.Success). Never substitute terms like 'Complete'.",
        "5. PATHFINDING MOVEMENT: To move an NPC along a path, you MUST fetch waypoints and iterate through them using Humanoid:MoveTo() and MoveToFinished:Wait(). Never teleport characters via CFrame loops. Use this exact pattern:\n"
        "   local waypoints = path:GetWaypoints()\n"
        "   for _, waypoint in ipairs(waypoints) do\n"
        "       humanoid:MoveTo(waypoint.Position)\n"
        "       humanoid.MoveToFinished:Wait()\n"
        "   end",
        "6. STATUS CHECK: Always check if Path.Status == Enum.PathStatus.Success after ComputeAsync before iterating over waypoints. Handle non-Success states with warnings.",
        "7. VERIFICATION: Before outputting, cross-verify every single method call against the provided documentation to ensure it exists."
    ]
    system_parts.append("\n".join(rules))

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
            f"getting long.)"
        )

    payload = {
        "model": "roblox-coder",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": TEMPERATURE,
        "repetition_penalty": REPETITION_PENALTY,
    }

    print("Sending to Modal (cold start may take 15-40s if idle)...")
    resp = requests.post(url, json=payload, timeout=300)
    if not resp.ok:
        print(f"\nModal returned {resp.status_code}. Response body:")
        print(resp.text)
        resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"], data.get("usage", {}), messages


def run_turn(question, messages, game_context, covered):
    """
    Runs one turn: retrieves docs for `question`, skips any chunk already
    sent in an earlier turn (tracked via `covered`, a set of (title, section)
    tuples) so the same class docs aren't sent twice as history grows, builds
    the appropriate message, sends the conversation to Modal, prints the
    answer + validation warnings, and returns (updated messages, updated
    covered set) for use in the next turn.
    """
    print("\nRetrieving relevant docs...")
    results = retrieve(question, top_k=TOP_K)

    new_results = [r for r in results if (r["title"], r["section"]) not in covered]
    skipped = len(results) - len(new_results)
    if skipped and messages:
        print(
            f"Retrieved {len(results)} chunks, {skipped} already sent earlier "
            f"in this conversation (skipping to save context space)."
        )
    else:
        print(f"Retrieved {len(results)} chunks: {[r['title'] for r in results]}")

    context_block = build_context_block(new_results)
    covered = covered | {(r["title"], r["section"]) for r in results}

    if not messages:
        messages = build_messages(question, context_block, game_context)
    else:
        messages = messages + [build_followup_message(question, context_block)]

    # 1. Fetch the raw response string from your Modal container endpoint
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
    """
    Scans the LLM response, extracts Luau code blocks, auto-corrects 
    7B micro-quirks, and returns the cleaned text along with an audit log.
    """
    audit_log = []
    
    def process_code_block(match):
        prefix = match.group(1)  # e.g., "```lua\n" or "```luau\n" (captures optional \r)
        code = match.group(2)
        suffix = match.group(3)  # "```"
        
        # 1. Fix legacy casing for Vector3 properties
        if re.search(r'\.magnitude\b', code):
            code = re.sub(r'\.magnitude\b', '.Magnitude', code)
            audit_log.append("✅ Auto-corrected legacy `.magnitude` to PascalCase `.Magnitude`")
            
        if re.search(r'\.unit\b', code):
            code = re.sub(r'\.unit\b', '.Unit', code)
            audit_log.append("✅ Auto-corrected legacy `.unit` to PascalCase `.Unit`")
            
        # 2. Catch accidental leaks of deprecated global wait()
        if re.search(r'(?<!task\.)\bwait\(', code):
            code = re.sub(r'(?<!task\.)\bwait\(', 'task.wait(', code)
            audit_log.append("🚀 Upgraded deprecated global `wait()` to performance-optimized `task.wait()`")
            
        # 3. Detect and insert a defensive programming warning for server yields
        if "CharacterAdded:Wait()" in code:
            audit_log.append(
                "⚠️ LINT WARNING: Detected server-side `CharacterAdded:Wait()`. "
                "If a player leaves right as this fires, the server thread will hang indefinitely."
            )
            
        return f"{prefix}{code}{suffix}"

    # FIXED: Added \r? to match Windows text stream line breaks properly
    code_block_pattern = r'(```lu[au]a\r?\n)(.*?)(```)'
    
    cleaned_text = re.sub(
        code_block_pattern, 
        process_code_block, 
        response_text, 
        flags=re.DOTALL | re.IGNORECASE
    )
    
    return cleaned_text, audit_log


def main():
    question = " ".join(sys.argv[1:]) or "How do I use PathfindingService to move an NPC?"
    print(f"Question: {question}")

    game_context = load_game_context()
    covered = set()
    
    messages = []
    current_input = question
    first_turn = True

    while True:
        # Executes the full turn pipeline linearly
        messages, covered = run_turn(current_input, messages, game_context, covered)

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