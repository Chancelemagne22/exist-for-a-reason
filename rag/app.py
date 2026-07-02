import streamlit as st
import requests
import os
import re
import threading
import json
from dotenv import load_dotenv
from retrieve import retrieve, build_context_block

load_dotenv()

st.set_page_config(page_title="EFAR Assistant", page_icon="🤖", layout="wide")
st.title("🤖 EFAR — Roblox Coding Assistant")

ENDPOINT = os.environ.get("MODAL_ENDPOINT_URL", "").rstrip("/") + "/v1/chat/completions"

# --- SIDEBAR WARM UP UTILITY ---
st.sidebar.title("System Controls")

def ping_modal():
    """Sends a minimal fast request to trigger container startup."""
    try:
        requests.post(ENDPOINT, json={"model": "roblox-coder", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}, timeout=5)
    except Exception:
        pass

if "warmed_up" not in st.session_state:
    st.session_state.warmed_up = False

if st.sidebar.button("🔥 Pre-Warm Modal Backend"):
    st.sidebar.info("Waking up Modal container in the background... (Takes ~30s)")
    threading.Thread(target=ping_modal, daemon=True).start()
    st.session_state.warmed_up = True

if st.session_state.warmed_up:
    st.sidebar.success("Container requested! Your first prompt should be fast.")

st.sidebar.markdown("""
---
**Note:** The container automatically completely shuts down after **10 minutes** of total inactivity to protect your credits.
""")

# --- EFAR PIPELINE VALIDATION ENGINE ---
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
    """Scan generated Lua code for known hallucination/deprecation patterns."""
    warnings = []
    for method in DEPRECATED_PATHFINDING_METHODS:
        if re.search(rf"\b{re.escape(method)}\s*\(", answer):
            warnings.append(f"Uses '{method}', which is DEPRECATED. Check the reference docs for the recommended replacement.")
    for match in re.finditer(r"Enum\.PathStatus\.(\w+)", answer):
        value = match.group(1)
        if value not in VALID_PATHSTATUS_VALUES:
            warnings.append(f"Uses 'Enum.PathStatus.{value}', which is not a real PathStatus value.")
    for match in re.finditer(r"\bpath\.(\w+):Connect\s*\(", answer, re.IGNORECASE):
        event = match.group(1)
        if event not in VALID_PATH_EVENTS:
            warnings.append(f"Connects to 'path.{event}', which is not a documented Path event.")
    if re.search(r"local\s+\w+(?:\s*,\s*\w+)*\s*=\s*[\w.]*:ComputeAsync\s*\(", answer):
        warnings.append("Captures a return value from ':ComputeAsync()', but this method returns nothing (void). Check Path.Status after calling it instead.")
    creates_path = re.search(r":CreatePath\s*\(", answer) or re.search(r":ComputeAsync\s*\(", answer)
    uses_waypoints = re.search(r":GetWaypoints\s*\(", answer)
    if creates_path and not uses_waypoints:
        warnings.append("Calls CreatePath/ComputeAsync but never calls GetWaypoints() - the path may not actually be followed.")
    return warnings

def post_validate_and_clean(response_text: str) -> tuple[str, list[str]]:
    """Scans the LLM response, extracts Luau code blocks, and auto-corrects 7B micro-quirks."""
    audit_log = []
    def process_code_block(match):
        prefix = match.group(1)
        code = match.group(2)
        suffix = match.group(3)
        if re.search(r'\.magnitude\b', code):
            code = re.sub(r'\.magnitude\b', '.Magnitude', code)
            audit_log.append("✅ Auto-corrected legacy `.magnitude` to PascalCase `.Magnitude`")
        if re.search(r'\.unit\b', code):
            code = re.sub(r'\.unit\b', '.Unit', code)
            audit_log.append("✅ Auto-corrected legacy `.unit` to PascalCase `.Unit`")
        if re.search(r'(?<!task\.)\bwait\(', code):
            code = re.sub(r'(?<!task\.)\bwait\(', 'task.wait(', code)
            audit_log.append("🚀 Upgraded deprecated global `wait()` to performance-optimized `task.wait()`")
        if "CharacterAdded:Wait()" in code:
            audit_log.append("⚠️ LINT WARNING: Detected server-side `CharacterAdded:Wait()`. If a player leaves right as this fires, the thread hangs.")
        return f"{prefix}{code}{suffix}"

    code_block_pattern = r'(```lu[au]a\n)(.*?)(```)'
    cleaned_text = re.sub(code_block_pattern, process_code_block, response_text, flags=re.DOTALL | re.IGNORECASE)
    return cleaned_text, audit_log

# --- CHAT UI ENGINE ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "covered" not in st.session_state:
    st.session_state.covered = set()
if "extra_logs" not in st.session_state:
    st.session_state.extra_logs = {}

# Render conversation timeline
for idx, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        # If this response has stored linter warnings or corrections, render them right underneath
        if message["role"] == "assistant" and str(idx) in st.session_state.extra_logs:
            logs = st.session_state.extra_logs[str(idx)]
            if logs.get("corrections"):
                with st.expander("🛠️ EFAR Pipeline Auto-Corrections", expanded=False):
                    for c in logs["corrections"]:
                        st.write(c)
            if logs.get("warnings"):
                st.warning("⚠️ **Validation Warnings:**\n" + "\n".join([f"- {w}" for w in logs["warnings"]]))

if user_input := st.chat_input("Ask a Roblox development question..."):
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})

    with st.spinner("Processing RAG pipeline..."):
        results = retrieve(user_input, top_k=3)
        new_results = [r for r in results if (r["title"], r["section"]) not in st.session_state.covered]
        
        context_block = build_context_block(new_results)
        for r in results:
            st.session_state.covered.add((r["title"], r["section"]))

        system_prompt = (
            "You are EFAR, a coding assistant specialized in Roblox development (Luau, Studio APIs).\n"
            f"### Reference Documentation:\n{context_block}\n\n"
            "### CRITICAL LAWS:\n"
            "1. DEPRECATION: Never use properties or methods marked DEPRECATED.\n"
            "2. STRICT API: Only use properties and methods that explicitly appear in the reference documentation above.\n"
            "3. MODELS: Roblox Models do not have a .Position property. Use model:GetPivot().Position.\n"
            "4. ENUMS: Use exact enum names from the documentation (e.g., Enum.PathStatus.Success).\n"
            "5. PATHFINDING MOVEMENT: Move NPCs waypoint-by-waypoint using Humanoid:MoveTo() and MoveToFinished:Wait()."
        )

        modal_messages = [{"role": "system", "content": system_prompt}] + [
            {"role": m["role"], "content": m["content"]} for m in st.session_state.messages
        ]

        try:
            response = requests.post(
                ENDPOINT,
                json={
                    "model": "roblox-coder",
                    "messages": modal_messages,
                    "max_tokens": 900,
                    "temperature": 0.3,
                    "repetition_penalty": 1.15,
                    "stream": True
                },
                stream=True
            )
            
            with st.chat_message("assistant"):
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
                                except:
                                    pass
                
                # Run the post-generation validation and auto-cleaning layer
                clean_response, corrections = post_validate_and_clean(raw_response)
                response_placeholder.markdown(clean_response)
                
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