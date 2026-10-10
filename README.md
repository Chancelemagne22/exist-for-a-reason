# 🎮 EFAR: Exist For A Reason

> **A self-hosted, Roblox-focused AI coding assistant.**
>
> *Because I'm too poor to avail Claude.*

![Status](https://img.shields.io/badge/status-Alpha-yellow)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
[![Modal](https://img.shields.io/badge/Powered%20by-Modal-blueviolet)](https://modal.com)
[![Supabase](https://img.shields.io/badge/Backed%20by-Supabase-3ECF8E)](https://supabase.com)

**TL;DR** — RAG assistant for Roblox Luau: ~4K doc chunks (FastEmbed +
Supabase pgvector, hybrid keyword/vector retrieval) grounding `Qwen3.5-4B`
on a Modal Dedicated scale-to-zero endpoint, with a Streamlit chat UI and
eval-gated accuracy loop (kill-brick benchmark: 0/5 → 6/6, zero warnings).

---

## What it is

- **Knows Roblox** — answers grounded in official creator-docs via RAG, plus
  a task router (kill-brick vs. Pathfinding laws) and shared hallucination validators.
- **Costs ~$0 idle** — Modal Dedicated endpoint scales to zero; first request
  cold-starts (15–60s, auto-retried), warm requests are fast.
- **Private** — your own Modal + Supabase projects, no telemetry.
- **Eval-driven** — failing vs. working transcripts frozen as goldens in
  `evals/`; `rag/check_killbrick.py` gates changes offline.

---

## Architecture

```
USER QUERY
    ↓
RETRIEVAL (rag/retrieve.py)
  embed query (FastEmbed bge-small-en-v1.5) → slang→API expansion
  → Supabase pgvector top-K + CamelCase keyword match + companion expansion
    ↓
INFERENCE (Modal Dedicated endpoint efar-coder, OpenAI-compatible)
  system prompt (task-routed laws) + retrieved docs + question
  → Qwen3.5-4B, thinking disabled, proxy-token auth
    ↓
VALIDATION (rag/validation.py, shared by CLI + UI)
  Luau linting, case fixes, deprecation + hallucination warnings
    ↓
UI (rag/app.py Streamlit, or rag/ask.py CLI)
```

---

## Prerequisites

- **Modal account** — free tier ($30 credits) at [modal.com](https://modal.com)
- **Supabase account** — free tier at [supabase.com](https://supabase.com)
- **Python 3.10+** and **Git**

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/<your-username>/exist-for-a-reason.git
cd exist-for-a-reason
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
pip install modal
modal setup
```

`modal setup` opens a browser to link your Modal account.

### 3. Get the Roblox creator-docs (sparse checkout)

```bash
git clone --depth 1 --sparse https://github.com/Roblox/creator-docs.git rag/creator-docs
cd rag/creator-docs
git sparse-checkout set content/en-us
cd ../..
```

### 4. Set up Supabase

1. Create a project at [supabase.com](https://supabase.com), any region.
2. Dashboard → Settings → Extensions → enable `pgvector`.
3. SQL editor → run:

```sql
CREATE TABLE doc_chunks (
    id SERIAL PRIMARY KEY,
    chunk_id VARCHAR UNIQUE NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(384),
    source VARCHAR,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ON doc_chunks USING IVFFLAT (embedding) WITH (lists = 100);
```

4. Settings → Database → copy the **pooler** connection string
   (`:6543`, not `:5432`).

### 5. Configure `.env`

```bash
cp .env.example .env
```

Fill in (see `.env.example` for exact formats):

```
MODAL_ENDPOINT_URL=https://<workspace>--ep-efar-coder-server.us-west.modal.direct
MODAL_PROXY_TOKEN=wk-<id>.ws-<secret>
MODAL_MODEL=Qwen/Qwen3.5-4B
MAX_MODEL_LEN=16384
SUPABASE_DB_URL=postgresql://postgres.<ref>@aws-1-<region>.pooler.supabase.com:6543/postgres
```

Never commit `.env`.

### 6. Create the Modal Dedicated endpoint

```bash
modal endpoint create --name efar-coder --model Qwen/Qwen3.5-4B
modal workspace proxy-tokens create
```

Paste the endpoint URL and proxy token into `.env` (step 5).
Dedicated per-second billing scales to $0 when idle — this is what keeps
you inside free credits. Do NOT set `min_containers=1`.

### 7. Ingest the docs (chunk → embed → upload)

```bash
cd rag
python chunk_docs.py      # → chunks.jsonl (~4K chunks, incl. custom-docs/)
python embed_chunks.py    # → chunks_embedded.jsonl (CPU, ~40-90 min, resumable)
python upload_chunks.py   # → Supabase doc_chunks table
cd ..
```

Add your own pattern docs to `rag/custom-docs/*.md` before chunking to
include them in grounding.

### 8. Smoke-test the endpoint

```bash
curl https://<workspace>--ep-efar-coder-server.us-west.modal.direct/v1/chat/completions \
  -H "Authorization: Bearer $MODAL_PROXY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3.5-4B",
    "messages": [{"role": "user", "content": "Write a Luau print hello"}],
    "max_tokens": 512,
    "chat_template_kwargs": {"enable_thinking": false}
  }'
```

First request takes 15–60s (cold start). A JSON reply with Luau code = working.

### 9. Add your game context

Edit `system_prompt.md`: game name, genre, key systems, naming conventions,
architecture notes, things to avoid. Restart the UI/CLI after editing
(no redeploy needed).

### 10. Run it

```bash
streamlit run rag/app.py
# → http://localhost:8501 (run from repo root so .env loads)
```

Click **Pre-warm Modal backend** while you get set up. Or use the CLI:

```bash
python -u rag/ask.py "Write a Luau print hello" --no-retrieval --once --stream  # endpoint only
python -u rag/ask.py "How do I use PathfindingService to move an NPC?" --once --stream  # full RAG
```

---

## Usage

Ask Roblox questions in the UI or CLI:

```
"How do I use PathfindingService to move an NPC?"
"How do I make a kill-brick that only kills real players?"
"Show me a secure RemoteEvent pattern for a spell system"
"What's the correct way to handle player loading with DataStore?"
"Explain the difference between LocalScripts and ModuleScripts"
```

Each answer renders per-code-block copy buttons plus auto-corrections and
validation warnings underneath. Score new mechanics with
`python rag/check_killbrick.py <answer.txt>` (see `evals/killbrick/`).

---

## Project structure

```
exist-for-a-reason/
├── README.md                 # This file
├── requirements.txt          # Pinned Python deps
├── system_prompt.md          # Your game context (edit this!)
├── modal_app.py              # Legacy DIY backend (rollback only)
├── evals/killbrick/          # Golden/anti-golden evals + checklist
└── rag/
    ├── app.py                # Streamlit chat UI
    ├── ask.py                # CLI: question → retrieval → answer
    ├── retrieve.py           # Hybrid retrieval + task router
    ├── validation.py         # Shared validators (single source of truth)
    ├── check_killbrick.py    # Offline eval gate
    ├── chunk_docs.py         # Creator-docs + custom-docs → chunks.jsonl
    ├── embed_chunks.py       # Chunks → embeddings (resumable)
    ├── upload_chunks.py      # Embeddings → Supabase
    └── custom-docs/          # Your pattern docs (ingested at chunk time)
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| 503 `no upstreams available`, retries exhaust | Container still provisioning after long idle (>2 min). Wait, pre-warm, retry. Check dashboard Endpoints → `efar-coder` → Containers. |
| 401 Unauthorized | Bad `MODAL_PROXY_TOKEN`. `modal workspace proxy-tokens create`, update `.env`, restart. |
| 404 `invalid function call` | Guessed endpoint URL. Copy exactly from dashboard Endpoints → `efar-coder` → copy icon; code appends `/v1/chat/completions`. |
| Supabase `tenant/user not found` | Pooler host must use `:6543`, direct `db.*` host uses `:5432`. Don't mix. |
| Retrieval returns nothing / `SUPABASE_DB_URL not set` | `.env` missing or not loaded (run from repo root). Table empty → run step 7. |
| Empty / gibberish answers | Keep `chat_template_kwargs: {enable_thinking: False}` unless you raise output budgets; fill in `system_prompt.md`; generic prompts → generic answers. |
| `UnicodeEncodeError` on Windows CLI | Fixed via UTF-8 stdout (`ask.py`); update if you see it elsewhere. |

---

## Known Limitations

- **4B-parameter model** — fast and free-tier-friendly, weaker than flagships
  on complex tasks. Mitigation: rich retrieved context + task-routed prompts.
- **16K context window** (`MAX_MODEL_LEN=16384`) — split long code/questions;
  history trimmer drops oldest pairs first.
- **No fine-tuning** — game context comes from `system_prompt.md` + RAG only.
- **Cold starts** — 15–60s+ after ~180s idle; pre-warm button + auto-retry cover it.
- **Alpha UI** — Streamlit is functional, not pretty; edge-case validator gaps exist.

---

## License

MIT — see [LICENSE](LICENSE). Use freely, including commercially, with attribution.
