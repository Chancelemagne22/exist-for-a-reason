"""
EFAR (exist-for-a-reason) - Modal backend
A self-hosted, Roblox-focused AI coding assistant.
Serves Qwen2.5-Coder-7B-Instruct via vLLM on an OpenAI-compatible endpoint.

Setup:
  pip install modal
  modal setup                 # authenticate your account
  modal deploy modal_app.py   # deploy

After deploy, Modal prints a URL like:
  https://<your-workspace>--efar-serve.modal.run

That URL is OpenAI-API compatible: POST /v1/chat/completions
"""

import modal

MINUTES = 60  # seconds

# ---- Model config ----
# Qwen2.5-Coder-7B-Instruct is a strong pick for Lua/Luau-family code.
# AWQ quantized version keeps VRAM usage low so it fits comfortably on an A10G.
MODEL_NAME = "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ"
MODEL_REVISION = None  # pin a commit hash later if you want reproducibility

app = modal.App("efar")

# ---- Container image ----
# Pulls vLLM's official image and installs what's needed on top.
vllm_image = (
    modal.Image.from_registry(
        "vllm/vllm-openai:v0.15.1",
        add_python="3.11",  # Modal can't auto-detect Python in this image; specify it explicitly
    )
    .entrypoint([])  # override the base image's default entrypoint
    .env(
        {
            "HF_HUB_CACHE": "/root/.cache/huggingface",
            "VLLM_SERVER_DEV_MODE": "1",
        }
    )
)

# ---- Persistent volumes ----
# Cache model weights across cold starts so you're not re-downloading
# ~7-15GB from Hugging Face every time the container spins up.
hf_cache_vol = modal.Volume.from_name("efar-hf-cache", create_if_missing=True)
vllm_cache_vol = modal.Volume.from_name("efar-vllm-cache", create_if_missing=True)


@app.function(
    image=vllm_image,
    gpu="A10G",
    scaledown_window=300,       # sleep fast after idle - you said cold starts are fine
    timeout=10 * MINUTES,      # max time to wait for container start + first response
    min_containers=0,          # never keep it warm = never pay when you're not using it
    volumes={
        "/root/.cache/huggingface": hf_cache_vol,
        "/root/.cache/vllm": vllm_cache_vol,
    },
)
@modal.concurrent(max_inputs=4)  # you're the only user, so this is plenty
@modal.web_server(port=8000, startup_timeout=10 * MINUTES)
def serve():
    import subprocess

    cmd = [
        "vllm", "serve",
        MODEL_NAME,
        "--served-model-name", "roblox-coder",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--max-model-len", "8192",       # plenty for chat + TDD context, keeps memory light
        "--gpu-memory-utilization", "0.90",
        "--quantization", "awq",
        "--dtype", "auto",
        "--enable-prefix-caching",       # speeds up repeated system-prompt reuse
    ]
    subprocess.Popen(cmd)