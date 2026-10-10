import streamlit as st
import requests
import os
import re
import threading
import time
import uuid
import json
from pathlib import Path
from dotenv import load_dotenv
from retrieve import retrieve, build_context_block, is_killbrick_query
from validation import validate_answer, post_validate_and_clean as _shared_clean

# Load .env from repo root even if Streamlit is started from rag/ or elsewhere.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

st.set_page_config(page_title="EFAR Assistant", page_icon=":material/smart_toy:", layout="wide")
st.title("EFAR — Roblox Coding Assistant")

MODAL_ENDPOINT_RAW = os.environ.get("MODAL_ENDPOINT_URL", "").strip()
if not MODAL_ENDPOINT_RAW:
    st.error("MODAL_ENDPOINT_URL not set. Add it to your .env (see .env.example) and restart Streamlit.")
    st.stop()
ENDPOINT_BASE = MODAL_ENDPOINT_RAW.rstrip("/")
# Guard against double-suffix if .env already contains the full path (ask.py already guards; keep in sync).
ENDPOINT = ENDPOINT_BASE if ENDPOINT_BASE.endswith("/v1/chat/completions") else ENDPOINT_BASE + "/v1/chat/completions"
# Dedicated Endpoint auth + model (M2 migration from DIY modal_app.py).
# MODAL_PROXY_TOKEN is `wk-<id>.ws-<secret>` from `modal workspace proxy-tokens create`.
# Source of truth for model is dashboard Endpoints -> Quickstart request example
# (currently "Qwen/Qwen3.5-4B" for efar-coder). Use `roblox-coder` only for DIY rollback.
MODAL_MODEL = os.environ.get("MODAL_MODEL", "Qwen/Qwen3.5-4B").strip() or "Qwen/Qwen3.5-4B"
MODAL_PROXY_TOKEN = os.environ.get("MODAL_PROXY_TOKEN", "").strip()


def get_affinity_key():
    """One affinity key per browser session = one conversation, keeps prefix cache warm."""
    if "affinity_key" not in st.session_state:
        st.session_state.affinity_key = uuid.uuid4().hex
    return st.session_state.affinity_key


def modal_headers():
    """Bearer headers for Dedicated Endpoint + affinity routing. Empty dict for legacy DIY."""
    headers = {}
    if MODAL_PROXY_TOKEN:
        headers["Authorization"] = f"Bearer {MODAL_PROXY_TOKEN}"
    try:
        headers["Modal-Routing-Affinity-Key"] = get_affinity_key()
    except Exception:
        pass
    return headers


MODAL_RETRY_DELAYS = [15, 30, 60]
RETRYABLE_STATUSES = {502, 503, 504}


def post_with_coldstart_retry(payload, stream=True):
    """POST to Dedicated endpoint with retry on 502/503/504 (scale-from-zero).

    Returns the successful Response, or raises the last error. Shows Streamlit
    status updates between attempts so the UI never looks hung.
    """
    last_exc = None
    for attempt, delay in enumerate([0] + MODAL_RETRY_DELAYS):
        if attempt:
            st.info(
                f"Modal container still starting (attempt {attempt + 1}/"
                f"{len(MODAL_RETRY_DELAYS) + 1}) — retrying in {delay}s..."
            )
            time.sleep(delay)
        try:
            resp = requests.post(
                ENDPOINT, headers=modal_headers(), json=payload,
                stream=stream, timeout=(10, 300),
            )
        except requests.exceptions.ConnectionError as e:
            st.warning(f"Connection error (attempt {attempt + 1}): {e}")
            last_exc = e
            continue
        if resp.status_code in RETRYABLE_STATUSES:
            st.warning(
                f"Modal returned {resp.status_code} — container likely still "
                f"starting. Will retry automatically."
            )
            last_exc = requests.exceptions.HTTPError(
                f"{resp.status_code} Server Error for url: {ENDPOINT}", response=resp
            )
            continue
        return resp
    if last_exc:
        raise last_exc
    raise RuntimeError("Modal retry loop exhausted without response")

# --- CONTEXT / TOKEN BUDGET CONFIG ---
# Keep this in sync with --max-model-len in modal_app.py (both read the same
# MAX_MODEL_LEN env var, so a friend deploying with a bigger GPU just needs
# to set one value in their .env, not edit code in two places).
MAX_MODEL_LEN = int(os.environ.get("MAX_MODEL_LEN", "16384"))
RESERVED_FOR_OUTPUT = 2048   # max tokens we'd ever want the model to generate in one reply
SAFETY_MARGIN = 200          # buffer against our own token estimate being approximate

# --- SIDEBAR WARM UP UTILITY ---
st.sidebar.title("System Controls")

def ping_modal():
    """Sends a minimal fast request to trigger container startup."""
    try:
        # Cold start is 15-60s, so a 5s timeout always fails — use 65s in background thread.
        # enable_thinking=False: Qwen3.5 reasoning would eat max_tokens even on ping.
        requests.post(ENDPOINT, headers=modal_headers(), json={"model": MODAL_MODEL, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1, "chat_template_kwargs": {"enable_thinking": False}}, timeout=(10, 65))
    except Exception:
        pass

if "warmed_up" not in st.session_state:
    st.session_state.warmed_up = False

if st.sidebar.button("Pre-Warm Modal Backend", icon=":material/whatshot:"):
    st.sidebar.info("Waking up Modal container in the background... (Takes ~30s)")
    threading.Thread(target=ping_modal, daemon=True).start()
    st.session_state.warmed_up = True

if st.session_state.warmed_up:
    st.sidebar.success("Container requested! Your first prompt should be fast.")

st.sidebar.markdown("""
---
**Note:** The container automatically completely shuts down after **3 minutes (180s)** of total inactivity to protect your credits (see `scaledown_window=180` in `modal_app.py`).
""")

if st.sidebar.button("Clear retrieved-docs cache", icon=":material/cleaning_services:"):
    st.session_state.covered = set()
    st.sidebar.success("Cleared — next question will fetch fresh docs.")

# --- TOKEN ESTIMATION + HISTORY TRIMMING ---

def estimate_tokens(messages):
    """Crude token estimate: ~4 chars per token is a reasonable rule of thumb for English/code."""
    total_chars = sum(len(m["content"]) for m in messages)
    return total_chars // 4


def trim_history_to_fit(system_prompt, history, budget):
    """
    Drops oldest user/assistant PAIRS (not single messages) from history
    until the combined token estimate fits inside budget.
    Returns (trimmed_history, dropped_pairs_count).
    """
    history = history[:]  # work on a copy - don't mutate session_state mid-loop
    dropped_pairs = 0

    def total_tokens():
        all_msgs = [{"role": "system", "content": system_prompt}] + history
        return estimate_tokens(all_msgs)

    while total_tokens() > budget and len(history) >= 2:
        # Drop the oldest pair (oldest user message + its assistant reply)
        # so every remaining message stays correctly paired.
        history = history[2:]
        dropped_pairs += 1

    return history, dropped_pairs


# --- EFAR PIPELINE VALIDATION ENGINE ---
# Single source of truth lives in rag/validation.py (imported above).
# Do NOT add local checks here — add them there so CLI and Streamlit stay in sync.

def post_validate_and_clean(response_text: str) -> tuple[str, list[str]]:
    """Streamlit wrapper around validation.post_validate_and_clean (adds :material: icons)."""
    cleaned_text, plain_logs = _shared_clean(response_text)
    icon_map = {
        "Auto-corrected legacy `.magnitude`": ":material/check_circle: Auto-corrected legacy `.magnitude` to PascalCase `.Magnitude`",
        "Auto-corrected legacy `.unit`": ":material/check_circle: Auto-corrected legacy `.unit` to PascalCase `.Unit`",
        "Upgraded deprecated global": ":material/rocket_launch: Upgraded deprecated global `wait()` to performance-optimized `task.wait()`",
        "LINT WARNING": ":material/warning: LINT WARNING: Detected server-side `CharacterAdded:Wait()`. If a player leaves right as this fires, the thread hangs.",
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

# --- CHAT UI RENDER HELPERS (Option A: native per-block copy, zero deps) ---
# st.code blocks render with Streamlit's native copy toolbar (hover on desktop,
# tap-to-focus on mobile). Splitting fences out of one big markdown blob gives
# each Luau block its own isolated copy target. No new deps, no custom JS.
CODE_FENCE_RE = re.compile(r"```(?:luau|lua)\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def render_assistant_message(content: str):
    """Render prose via markdown and each Luau fence via st.code (own copy button).

    Falls back to plain markdown for unclosed fences (streaming remnants).
    """
    parts = CODE_FENCE_RE.split(content)
    # split() yields [prose, code, prose, code, ...]; even indices are prose.
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part.strip():
                st.markdown(part)
        else:
            st.code(part.strip(), language="lua")


# --- CHAT UI ENGINE ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "covered" not in st.session_state:
    st.session_state.covered = set()
if "extra_logs" not in st.session_state:
    st.session_state.extra_logs = {}

# Render conversation timeline
for idx, message in enumerate(st.session_state.messages):
    if message["role"] == "assistant":
        avatar = ":material/smart_toy:"
    else:
        avatar = ":material/person:"
    with st.chat_message(message["role"], avatar=avatar):
        if message["role"] == "assistant":
            render_assistant_message(message["content"])
        else:
            st.markdown(message["content"])
        # If this response has stored linter warnings or corrections, render them right underneath
        if message["role"] == "assistant" and str(idx) in st.session_state.extra_logs:
            logs = st.session_state.extra_logs[str(idx)]
            if logs.get("corrections"):
                with st.expander("EFAR Pipeline Auto-Corrections", expanded=False, icon=":material/auto_fix_high:"):
                    for c in logs["corrections"]:
                        st.write(c)
            if logs.get("warnings"):
                st.warning("**Validation Warnings:**\n" + "\n".join([f"- {w}" for w in logs["warnings"]]))

if user_input := st.chat_input("Ask a Roblox development question..."):
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})

    with st.spinner("Processing RAG pipeline..."):
        results = retrieve(user_input, top_k=3)
        new_results = [r for r in results if (r["title"], r["section"]) not in st.session_state.covered]

        context_block = build_context_block(new_results)
        for r in results:
            st.session_state.covered.add((r["title"], r["section"]))

        # Task router (keep in sync with rag/ask.py:build_messages): kill-brick
        # builds get kill-brick laws, everything else keeps Pathfinding laws.
        if is_killbrick_query(user_input):
            task_laws = (
                "4. KILL-BRICK PLACEMENT: The server Script MUST be a CHILD of the kill Part "
                "(Workspace > DeathTile > Script) so `script.Parent` is the part. NEVER place it in "
                "ServerScriptService while doing `local part = script.Parent`. Parts have NO 'Script field' in Properties.\n"
                "5. CHARACTER RESOLUTION: `Touched` gives a LIMB (e.g. LowerLeg), NOT the character. Use "
                "`hit:FindFirstAncestorOfClass(\"Model\")` + `FindFirstChildOfClass(\"Humanoid\")`.\n"
                "6. PLAYER-ONLY FILTER: Use `Players:GetPlayerFromCharacter(character); if not player then return end`. "
                "NEVER use FindFirstChildWhichIsA(\"HumanoidRootPart\") — name, not class, always nil.\n"
                "7. DEBOUNCE: Per-player table (`debounce[player]`) + `task.delay` + `PlayerRemoving` cleanup. "
                "NEVER a single shared boolean/attribute.\n"
            )
        else:
            task_laws = (
                "4. ENUMS: Use exact enum names from the documentation (e.g., Enum.PathStatus.Success).\n"
                "5. PATHFINDING MOVEMENT: Move NPCs waypoint-by-waypoint using Humanoid:MoveTo() and MoveToFinished:Wait().\n"
            )
        system_prompt = (
            "You are EFAR, a coding assistant specialized in Roblox development (Luau, Studio APIs).\n"
            f"### Reference Documentation:\n{context_block}\n\n"
            "### CRITICAL LAWS:\n"
            "1. DEPRECATION: Never use properties or methods marked DEPRECATED.\n"
            "2. STRICT API: Only use properties and methods that explicitly appear in the reference documentation above. Do not invent Studio UI or API details.\n"
            "3. MODELS: Roblox Models do not have a .Position property. Use model:GetPivot().Position.\n"
            f"{task_laws}"
        )

        # Token-budget-aware history trim: drops oldest Q&A pairs (never the
        # system prompt or the freshly retrieved context) until what's left
        # fits comfortably under MAX_MODEL_LEN, reserving room for the reply.
        token_budget = MAX_MODEL_LEN - RESERVED_FOR_OUTPUT - SAFETY_MARGIN

        recent_messages, dropped_pairs = trim_history_to_fit(
            system_prompt,
            st.session_state.messages,
            token_budget
        )

        if dropped_pairs > 0:
            st.sidebar.warning(f"Trimmed {dropped_pairs} oldest exchange(s) to stay within context limit.")
            print(f"[EFAR] Dropped {dropped_pairs} oldest Q&A pair(s) — history was over token budget.")

        modal_messages = [{"role": "system", "content": system_prompt}] + [
            {"role": m["role"], "content": m["content"]} for m in recent_messages
        ]

        # Dynamically size max_tokens so we never ask vLLM for more output
        # room than the remaining budget actually has - prevents the
        # "prompt + max_tokens > max_model_len" hard rejection outright.
        prompt_tokens_est = estimate_tokens(modal_messages)
        safe_max_tokens = min(RESERVED_FOR_OUTPUT, MAX_MODEL_LEN - prompt_tokens_est - SAFETY_MARGIN)
        safe_max_tokens = max(safe_max_tokens, 256)  # floor so it never goes negative/degenerate

        try:
            response = post_with_coldstart_retry(
                {
                    "model": MODAL_MODEL,
                    "messages": modal_messages,
                    "max_tokens": safe_max_tokens,
                    "temperature": 0.3,
                    "repetition_penalty": 1.15,
                    "stream": True,
                    "chat_template_kwargs": {"enable_thinking": False}
                },
                stream=True,
            )
            if response.status_code == 401:
                st.error("Modal returned 401 Unauthorized. Check MODAL_PROXY_TOKEN in your .env (`modal workspace proxy-tokens create`).")
                st.stop()

            with st.chat_message("assistant", avatar=":material/smart_toy:"):
                response_placeholder = st.empty()
                raw_response = ""

                for line in response.iter_lines():
                    if line:
                        decoded_line = line.decode('utf-8').strip()
                        if decoded_line.startswith("data: "):
                            content = decoded_line[6:]
                            if content != "[DONE]":
                                try:
                                    chunk_data = json.loads(content)
                                    token = chunk_data['choices'][0]['delta'].get('content', '')
                                    raw_response += token
                                    response_placeholder.markdown(raw_response + "▌")
                                except Exception:
                                    # Skip malformed SSE chunk, keep streaming.
                                    continue

                # Run the post-generation validation and auto-cleaning layer.
                # Final render uses split code blocks so each gets a native
                # copy button; mid-stream stays single-markdown to avoid
                # flicker on partial fences. st.rerun() below re-renders via
                # the timeline helper anyway.
                clean_response, corrections = post_validate_and_clean(raw_response)
                with response_placeholder.container():
                    render_assistant_message(clean_response)

                # Track warning conditions
                warnings = validate_answer(clean_response)

                # Save assistant message to timeline
                st.session_state.messages.append({"role": "assistant", "content": clean_response})
                new_msg_idx = str(len(st.session_state.messages) - 1)

                # Store the custom linter diagnostics attached to this specific turn index
                if corrections or warnings:
                    st.session_state.extra_logs[new_msg_idx] = {
                        "corrections": corrections,
                        "warnings": warnings
                    }

                # Force an instant re-render to display the freshly injected linter layouts
                st.rerun()

        except Exception as e:
            st.error(f"Error connecting to your Modal backend: {e}")