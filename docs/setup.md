# EFAR Setup Guide

This walks you through deploying your own copy of **EFAR** (exist-for-a-reason) — a self-hosted, Roblox-focused AI coding assistant — using your own Modal account for GPU inference.

By the end, you'll have a private AI chat that understands Luau/Roblox development and (optionally) your own game's technical design docs.

---

## What you'll need

- A [Modal](https://modal.com) account — new accounts get $30 in free credits, which is enough to develop and test comfortably.
- Python 3.10+
- Node.js 18+ (only needed once we get to the frontend)
- Basic comfort with the terminal

No GPU of your own required — Modal provides that.

---

## Step 1: Clone the repo

```bash
git clone https://github.com/<your-username>/exist-for-a-reason.git
cd efar
```

## Step 2: Install Modal and authenticate

```bash
pip install modal
modal setup
```

This opens a browser window to link your Modal account to the CLI. Once it says "authenticated," you're good.

## Step 3: Deploy the backend

```bash
modal deploy modal_app.py
```

First deploy will take a few minutes — Modal is building the container image and downloading the model weights (~5GB) from Hugging Face. Subsequent deploys are much faster since weights are cached in a Modal Volume.

When it finishes, Modal prints a URL that looks like:

```
https://<your-workspace>--efar-serve.modal.run
```

**Save this URL** — it's your private AI endpoint.

## Step 4: Test it

```bash
curl https://<your-workspace>--efar-serve.modal.run/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "roblox-coder",
    "messages": [
      {"role": "user", "content": "Write a Luau function using PathfindingService to move an NPC to a target part."}
    ]
  }'
```

If you get a JSON response with Luau code in it, the backend is working.

> **First request will be slow** (15–40 seconds) — this is the "cold start," Modal spinning up a GPU container from nothing. This is expected and by design: it means you pay **$0** while you're not using it. Subsequent requests within the idle window are fast.

## Step 5: Add your own game context (optional but recommended)

Open `system_prompt.md` and replace the placeholder with details about your own Roblox project — naming conventions, architecture, key systems. This is what makes the assistant actually useful instead of generic.

Example structure:

```markdown
# Project Context

You are a coding assistant for [Your Game Name], a Roblox [genre] game.

## Key systems
- [System name]: [what it does, key APIs used]

## Naming conventions
- [convention]: [explanation]

## Architecture notes
- [anything the assistant should always keep in mind]
```

Redeploy after editing:

```bash
modal deploy modal_app.py
```

## Step 6: (Coming soon) Set up the frontend

The web chat UI setup will live in `frontend/README.md` once that piece is built. For now, you can talk to your model directly via curl or any OpenAI-API-compatible client pointed at your Modal URL.

---

## Cost expectations

Modal bills per-second and this setup scales to zero when idle — you pay only while a request is actively being processed.

Rough numbers (verify current pricing at [modal.com/pricing](https://modal.com/pricing), as this can change):
- A10G GPU: roughly $1/hr **while active**
- A typical dev session (a handful of questions) costs a few cents, not dollars
- Your $30 free credit should comfortably cover weeks of casual use

If you want zero cold starts (instant responses every time), you can set `min_containers=1` in `modal_app.py`, but this keeps a GPU warm 24/7 and will burn through credits fast. Not recommended unless you're demoing this to someone live.

---

## Troubleshooting

**Deploy fails with a CUDA/image error**
Try pinning to the exact vLLM image version in `modal_app.py` (already pinned by default) — floating `latest` tags can break unexpectedly.

**Cold starts feel slower than expected**
Check that your Modal Volumes are being created correctly (`modal volume list`) — if weights aren't caching, every start re-downloads from Hugging Face.

**Model gives generic (non-Roblox) answers**
Make sure `system_prompt.md` is actually being loaded into your requests — check your API route or curl payload includes it as a system message.

---

## Next steps

- Swap in a different model by changing `MODEL_NAME` in `modal_app.py` (any vLLM-supported model works)
- Add RAG over a larger doc set if your project context grows beyond a single system prompt
- Open an issue or PR if you hit something this guide doesn't cover
