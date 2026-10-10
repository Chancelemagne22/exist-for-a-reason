# 🎮 EFAR: Exist For A Reason

> **A self-hosted, Roblox-focused AI coding assistant powered by GPU inference and semantic search.**
>
> *Because I'm too poor to avail Claude.*

![Status](https://img.shields.io/badge/status-Alpha-yellow)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
[![Modal](https://img.shields.io/badge/Powered%20by-Modal-blueviolet)](https://modal.com)
[![Supabase](https://img.shields.io/badge/Backed%20by-Supabase-3ECF8E)](https://supabase.com)

> **Portfolio TL;DR** — Solo-built RAG coding assistant for Roblox Luau: 3,933 doc chunks
> (FastEmbed + Supabase pgvector, hybrid keyword + vector retrieval) grounding
> `Qwen/Qwen3.5-4B` on a Modal Dedicated scale-to-zero endpoint, with a Streamlit
> chat UI (live streaming, per-block copy buttons, Material icons). Shipped fixes:
> cold-start 503 auto-retry, reasoning-token budget fix (259 → 0 thinking tokens on
> trivial prompts), and DB connects that fail fast instead of hanging.
> Copy-paste CV bullets at the bottom ([jump](#cv-bullets)).

---

## Table of Contents

1. [Overview](#overview)
2. [Key Features](#key-features)
3. [How It Works](#how-it-works)
4. [Tech Stack](#tech-stack)
5. [Prerequisites](#prerequisites)
6. [Installation & Deployment](#installation--deployment)
7. [Usage](#usage)
8. [Project Structure](#project-structure)
9. [Customization](#customization)
10. [Troubleshooting](#troubleshooting)
11. [Known Limitations](#known-limitations)
12. [Contributing](#contributing)
13. [Roadmap](#roadmap)
14. [License](#license)

---

## Overview

EFAR is a **self-hosted AI assistant** specifically designed for **Roblox Luau development**. Unlike generic coding assistants, EFAR:

- **Knows Roblox** — Qwen3.5-4B grounded in Roblox API documentation via RAG
- **Pays only when used** — runs on a Modal Dedicated endpoint that scales to $0 compute when idle
- **Semantically searches your docs** — embeds Roblox creator-docs in Supabase vector database for retrieval
- **Validates Roblox code** — post-generation linting catches hallucinations (wrong enum values, deprecated methods, etc.)
- **Fast after cold start** — first request ~15-60s, then cached for snappy responses
- **Completely private** — runs on your own infrastructure, no telemetry

Perfect for indie Roblox developers, game studios, and anyone building games without enterprise AI subscription budgets.

---

## Key Features

### 1. **Semantic Search over Roblox Docs**
Your prompts are embedded and semantically matched against the official Roblox creator documentation (Luau, API reference, character systems, scripting guides, security best practices, etc.).

### 2. **Roblox-Specific Code Validation**
EFAR catches common mistakes:
- **Case corrections**: `.magnitude` → `.Magnitude`, `wait()` → `task.wait()`
- **Deprecation warnings**: alerts you if code uses outdated APIs
- **Hallucination detection**: recognizes when the model invents class names or methods
- **Enum validation**: checks that enum values exist in the Roblox API

### 3. **Cost-Controlled GPU Inference**
Runs **`Qwen/Qwen3.5-4B`** on a Modal **Dedicated** endpoint (`efar-coder`, scale-to-zero):
- OpenAI-compatible `POST /v1/chat/completions` with proxy-token Bearer auth
- Reasoning disabled (`chat_template_kwargs: {enable_thinking: False}`) so thinking
  tokens can't eat the completion budget (measured 259 → 0 on trivial prompts)
- Cold-start 503 auto-retry (15/30/60s) with affinity routing; idle → $0 compute

### 4. **Prefix Caching**
Your system prompt (game context) is cached on the GPU, so repeated queries reuse it without recomputation—faster responses, lower costs.

### 5. **Multi-Source RAG Pipeline**
- Chunks Roblox creator-docs into 3,933 chunks (1,302 titles: API reference + guides)
- Embeds with FastEmbed (BAAI/bge-small-en-v1.5, 384-dim)
- Stores in Supabase + pgvector for semantic search
- Hybrid retrieval: CamelCase keyword match + vector top-K + return-type/companion expansion
- Optional: add your own game design docs

### 6. **Streamlit Chat Interface**
Interactive UI with:
- Pre-warm button (trigger cold start while you set up)
- Message history with per-code-block copy buttons (`st.code`, one copy target per Luau fence)
- Material icons throughout (zero emoji)
- Real-time streaming responses with cold-start retry status

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                    EFAR Architecture                            │
└─────────────────────────────────────────────────────────────────┘

USER QUERY
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ RETRIEVAL AUGMENTED GENERATION (RAG)                            │
│                                                                 │
│  1. Embed query with FastEmbed                                 │
│  2. Search Supabase pgvector for top-K similar chunks          │
│  3. Keyword match for CamelCase class names in query           │
│  4. Build context block with relevant docs                     │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ LLM INFERENCE (Modal + vLLM)                                    │
│                                                                 │
│  System Prompt (cached):  Your game context from system_prompt.md
│  Context Window:          Top-K Roblox docs from Supabase      │
│  User Query:              Your question                         │
│  Model:                   Qwen/Qwen3.5-4B (thinking disabled)  │
│  Serving:                 Modal Dedicated, OpenAI-compatible    │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ POST-GENERATION VALIDATION                                      │
│                                                                 │
│  - Luau syntax linting                                          │
│  - Case corrections (.magnitude → .Magnitude)                   │
│  - Deprecation warnings                                         │
│  - Hallucination detection (bogus APIs)                         │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ STREAMLIT UI                                                    │
│                                                                 │
│  Display validated response with warnings & suggestions        │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow on First Setup

```
Roblox creator-docs (GitHub)
    ↓ (sparse checkout)
rag/creator-docs/
    ↓ (chunk_docs.py)
chunks.jsonl
    ↓ (embed_chunks.py)
chunks_embedded.jsonl
    ↓ (upload_chunks.py)
Supabase PostgreSQL (pgvector extension)
    ↓ (at query time: retrieve.py)
Top-K relevant docs
    ↓ (concatenated into system prompt)
Modal vLLM Endpoint
    ↓
Response + validation
```

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **LLM Model** | Qwen/Qwen3.5-4B (thinking disabled) | 4B-parameter chat model via Modal catalog |
| **Inference Runtime** | Modal Dedicated endpoint (`efar-coder`) | Managed serving, OpenAI-compatible API, scale-to-zero |
| **GPU Hosting** | Modal | Serverless GPU compute (per-second billing, $0 when idle) |
| **Vector Database** | Supabase PostgreSQL + pgvector | Embedding storage & semantic search |
| **Embeddings Model** | FastEmbed (BAAI/bge-small-en-v1.5) | 384-dim document + query embeddings |
| **Frontend** | Streamlit 1.58 | Chat UI: streaming, per-block copy, Material icons |
| **Language** | Python 3.10+ | All backend logic |
| **Docs Source** | Roblox creator-docs (GitHub) | 3,933 chunks across 1,302 titles |

Legacy DIY path (`modal_app.py`: Qwen2.5-Coder-7B-AWQ on vLLM, `roblox-coder`) is kept
only as a rollback; the live setup is Dedicated above.

---

## Prerequisites

Before you start, make sure you have:

- **[Modal Account](https://modal.com)** — Free tier includes $30 credits (sufficient for development & testing)
- **Python 3.10+** — Installed and in your PATH
- **Git** — For cloning the repo and sparse checkout of Roblox docs
- **Node.js 18+** *(optional, for future Next.js frontend)*
- **A Supabase Account** — Free tier available at [supabase.com](https://supabase.com)
- **Text editor or IDE** — VS Code, PyCharm, etc.

### API Keys & Credentials

You'll need:
- **Modal API Token** — Created during `modal setup`
- **Supabase connection string** — From your Supabase project settings
- **GitHub account** *(optional)* — To fork/contribute this repo

---

## Installation & Deployment

### Step 1: Clone the Repository

```bash
git clone https://github.com/<your-username>/exist-for-a-reason.git
cd exist-for-a-reason
```

### Step 2: Install Python Dependencies

```bash
pip install -r requirements.txt
```

This installs everything needed to run EFAR, including the RAG pipeline (`fastembed`, `psycopg2-binary`, `pgvector`, etc.). `fastapi` and `uvicorn` are also included but currently optional/unused — they're there for a planned future API layer.

### Step 3: Set Up Modal

Install Modal CLI and authenticate:

```bash
pip install modal
modal setup
```

This opens a browser window to link your Modal account. Once authenticated, you'll see:
```
✓ Authenticated as @your-username
```

### Step 4: Set Up GitHub Docs (Roblox Creator Documentation)

Clone or sparse-checkout the Roblox creator-docs:

```bash
# Option A: Sparse checkout (faster, ~2GB instead of ~8GB full repo)
git clone --depth 1 --sparse https://github.com/Roblox/creator-docs.git rag/creator-docs
cd rag/creator-docs
git sparse-checkout set content/en-us
cd ../..

# Option B: Full clone (comprehensive, but slower)
git clone https://github.com/Roblox/creator-docs.git rag/creator-docs
```

### Step 5: Create & Populate Supabase Project

1. **Create a new Supabase project** at [supabase.com](https://supabase.com):
   - Choose a region close to you
   - Note your project URL and database connection string

2. **Enable pgvector extension**:
   - Go to your Supabase dashboard → Settings → Extensions
   - Search for and enable `pgvector`

3. **Create the `doc_chunks` table**:
   - Open the SQL editor in Supabase
   - Run:
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

4. **Get your connection string**:
   - Supabase Dashboard → Settings → Database → Connection string (URI format)
   - Copy and save for `.env` file

### Step 6: Create Environment Configuration

Create `.env` in the project root (see `.env.example` — copy, don't guess the endpoint URL):

```bash
# .env
# Copy MODAL_ENDPOINT_URL exactly: dashboard Endpoints tab → efar-coder → copy icon
# (bare host; code appends /v1/chat/completions). The old --efar-serve URL pattern 404s.
MODAL_ENDPOINT_URL=https://<workspace>--ep-efar-coder-server.us-west.modal.direct
MODAL_PROXY_TOKEN=wk-<id>.ws-<secret>
# Copy "model" exactly from the endpoint Quickstart example (currently Qwen/Qwen3.5-4B)
MODAL_MODEL=Qwen/Qwen3.5-4B
MAX_MODEL_LEN=16384
# Pooler host MUST use :6543 (not :5432), or Supabase returns "tenant/user not found"
SUPABASE_DB_URL=postgresql://postgres.<ref>@aws-1-<region>.pooler.supabase.com:6543/postgres
```

Do NOT commit `.env` to version control.

### Step 7: Populate Roblox Docs in Supabase

Run the RAG pipeline to chunk, embed, and upload the Roblox creator-docs:

```bash
cd rag

# Step 1: Chunk the Markdown docs
python chunk_docs.py
# Output: chunks.jsonl (current corpus: 3,933 chunks / 1,302 titles)

# Step 2: Embed chunks
python embed_chunks.py
# Output: chunks_embedded.jsonl
# This may take 5-15 minutes depending on number of chunks

# Step 3: Upload to Supabase
python upload_chunks.py
# Inserts embeddings into doc_chunks table

cd ..
```

### Step 8: Create the Backend on Modal (Dedicated endpoint)

Live setup uses a Modal **Dedicated** endpoint, not `modal deploy`:

```bash
# From the CLI (or dashboard Endpoints tab → Browse catalog → Create)
modal endpoint create --name efar-coder --model Qwen/Qwen3.5-4B
modal workspace proxy-tokens create   # save wk-<id>.ws-<secret> to .env, never commit
```

When it turns `live`, copy the endpoint URL **exactly** (dashboard copy icon) into `.env`
as `MODAL_ENDPOINT_URL`, and copy the `"model"` value from the Quickstart request
example into `MODAL_MODEL` (currently `Qwen/Qwen3.5-4B`).

Rollback only: the legacy DIY path (`modal deploy modal_app.py`, `roblox-coder`,
`--efar-serve.modal.run`) is kept in the repo but not used live.

### Step 9: Test the Backend Endpoint

```bash
curl https://<workspace>--ep-efar-coder-server.us-west.modal.direct/v1/chat/completions \
  -H "Authorization: Bearer $MODAL_PROXY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3.5-4B",
    "messages": [
      {"role": "user", "content": "How do I create an NPC using PathfindingService in Roblox Luau?"}
    ],
    "max_tokens": 512,
    "chat_template_kwargs": {"enable_thinking": false}
  }'
```

Expected response: JSON with a Luau code example.

> **First request will take 15-60 seconds** (cold start — Modal spinning up GPU from
> scale-to-zero). This is expected and by design; the CLI/Streamlit retry
> automatically on 503s while the container starts. Warm requests are fast.
> After ~180 seconds of inactivity the endpoint scales to $0 compute.

### Step 10: Customize System Prompt for Your Game

Open `system_prompt.md` and replace the template with your game's context:

```markdown
# Project Context

You are a coding assistant for [Your Game Name], a Roblox [genre] game.

## Project Overview
- Game name: [e.g., "Sword Fighting Simulator"]
- Genre: [e.g., "Action/Multiplayer"]
- One-line pitch: [e.g., "A competitive multiplayer sword fighting game with cosmetics progression"]

## Key Systems
- **Damage System**: Uses a RemoteEvent to sync damage between client/server, with client-side prediction disabled for security
- **Economy**: DataStore-backed currency with caching layer; avoid float types (use integers only)
- **Matchmaking**: Custom ELO-based system using a custom matchmaking service

## Naming Conventions
- All services: `SomethingService` (Pascal case, "Service" suffix)
- All modules: `SomethingModule` (not "Util", not "Helper")
- All RemoteEvents: `Ask_SomethingHappened` (underscore-separated verbs)
- All RemoteProperties: avoid these; use RemoteEvents instead

## Architecture Notes
- Player load sequence: (1) DataStore load, (2) initialize systems, (3) listen for matchmaking
- All RemoteEvents are server-authoritative; client sends requests only
- Avoid yielding in module initialization (use `task.spawn` for deferred setup)

## Things to Avoid
- DO NOT use deprecated `FindFirstChild` without type checking the result
- DO NOT use `game:FindFirstChild("Player")` — use `Players:FindFirstChild()` instead
- DO NOT expose server RemoteEvents to client code directly
- DO NOT assume `Instance:FindFirstChild()` returns a table; always nil-check
```

Then restart Streamlit to pick up the new context (no redeploy needed — the prompt
loads at runtime):

```bash
streamlit run rag/app.py
```

### Step 11: Run the Streamlit UI (from repo root, so `.env` loads)

```bash
streamlit run rag/app.py
```

Streamlit opens at `http://localhost:8501`. You'll see:
- Chat interface with live streaming
- Pre-warm button (optional, triggers cold start in background)
- Message history with per-code-block copy buttons
- Validation warnings + auto-correction details under each answer

You're ready to go!

### Step 12 (optional): Try the CLI

```bash
# Modal-only smoke test (skips retrieval — fastest way to verify the endpoint)
python -u rag/ask.py "Write a Luau print hello" --no-retrieval --once --stream

# Full RAG pipeline (retrieval + grounded answer + validation)
python -u rag/ask.py "Write a Luau print hello" --once --stream
```

---

## Usage

### Basic Chat

1. Open `http://localhost:8501`
2. Type a question about Roblox development:
   - "How do I use PathfindingService to move an NPC?"
   - "Show me an example of a RemoteEvent security issue"
   - "Explain the difference between task.wait() and wait()"
3. Press Enter to send
4. EFAR retrieves relevant docs, generates code, and validates it

### Example Prompts

```
"Write a Luau function that uses UserInputService to detect WASD key presses"

"What's the correct way to handle player loading with DataStore?"

"Show me a secure RemoteEvent pattern for a spell system"

"How do I check if a player's character is humanoid?"

"Explain the difference between LocalScripts and ModuleScripts in Roblox"
```

### Pre-warming (Optional)

Click the **Pre-warm Modal backend** button to trigger a cold start while you're setting up. This avoids the first 15-60 second delay on your first real query. Both CLI and UI retry automatically if the container is still starting.

### Code Validation

EFAR automatically checks generated code for:
- Correct casing (`.Magnitude` not `.magnitude`)
- Modern API usage (`task.wait()` not `wait()`)
- Enum validity (e.g., `Enum.HumanoidStateType.Running` exists)
- Known Roblox services exist
- Deprecation warnings

Invalid code is highlighted with explanations. Each Luau block renders with its own copy button.

---

## Project Structure

```
exist-for-a-reason/
├── README.md                      # This file
├── LICENSE                        # MIT License
├── requirements.txt               # Python dependencies
├── system_prompt.md               # Game context template (customize this!)
├── modal_app.py                   # Backend: Qwen model deployment to Modal
├── .env.example                   # Environment variables template
│
├── docs/
│   └── setup.md                   # Original setup guide (reference)
│
└── rag/                           # Retrieval-Augmented Generation pipeline
    ├── app.py                     # Streamlit chat UI
    ├── chunk_docs.py              # Parse Roblox docs → chunks.jsonl
    ├── embed_chunks.py            # Embed chunks → chunks_embedded.jsonl
    ├── upload_chunks.py           # Upload embeddings → Supabase
    ├── retrieve.py                # Query embedding + Supabase search
    ├── ask.py                     # Full pipeline: question → answer (CLI)
    ├── check_embeddings.py        # Debug/validate embeddings
    ├── chunks.jsonl               # Raw chunked docs
    ├── chunks_embedded.jsonl      # Chunks + embedding vectors
    │
    └── creator-docs/              # Roblox creator-docs (sparse checkout)
        └── content/en-us/
            ├── luau/              # Luau language reference
            ├── scripting/         # Scripting guides (events, security, etc.)
            ├── characters/        # Character/NPC documentation
            └── reference/engine/  # Roblox API reference
```

### Key Files Explained

| File | Purpose |
|------|---------|
| **modal_app.py** | Legacy DIY backend (Qwen + vLLM on Modal). Kept for rollback only; live setup is the Dedicated `efar-coder` endpoint. |
| **rag/app.py** | Streamlit chat UI. Message history, pre-warming, live streaming with 503 retry, per-block copy buttons, Material icons, code validation. Run with `streamlit run rag/app.py` from repo root. |
| **rag/chunk_docs.py** | Parses Markdown + YAML from Roblox creator-docs. Splits into semantic chunks. Outputs `chunks.jsonl` (3,933 chunks / 1,302 titles). |
| **rag/embed_chunks.py** | Uses FastEmbed (`BAAI/bge-small-en-v1.5`) to create 384-dim embeddings. Outputs `chunks_embedded.jsonl`. |
| **rag/upload_chunks.py** | Bulk-inserts embeddings + metadata into Supabase `doc_chunks` table. |
| **rag/retrieve.py** | Core retrieval logic: embed query, search Supabase (10s connect timeout), CamelCase keyword-match, return-type/companion expansion, top-K results. |
| **rag/ask.py** | CLI for the full pipeline: question → retrieval → inference → answer. Flags: `--no-retrieval` (endpoint smoke test), `--stream` (live tokens), `--once` (no follow-up loop). |
| **system_prompt.md** | Game context injected into the system prompt. Customize this with your game's architecture, naming conventions, and systems. |

---

## Customization

### 1. Update Game Context

Edit `system_prompt.md` with your game's:
- **Architecture** — Folder structure, key systems, tech choices
- **Naming conventions** — How you name services, events, modules
- **Known patterns** — Specific RemoteEvent patterns, DataStore design
- **Things to avoid** — Anti-patterns, deprecated APIs you've opted out of

After editing, restart Streamlit/CLI (no redeploy — the prompt loads at runtime):
```bash
streamlit run rag/app.py
```

### 2. Add Custom Documentation

To include your own game design docs in the RAG pipeline:

1. Add Markdown files to `rag/custom-docs/` (create the folder)
2. Re-run the chunking pipeline:
   ```bash
   cd rag
   python chunk_docs.py  # Now includes both creator-docs and custom-docs
   python embed_chunks.py
   python upload_chunks.py
   cd ..
   ```
3. Restart Streamlit to pick up new docs

### 3. Adjust Model Parameters

Live model settings live in the dashboard endpoint (`efar-coder`) plus `.env`:
- **Model** — Copy `"model"` from the endpoint Quickstart example into `MODAL_MODEL`
- **Max model length** — `MAX_MODEL_LEN=16384` in `.env` (keep in sync across CLI/UI trimmers)
- **Output budget** — CLI `MAX_TOKENS=2048` in `rag/ask.py`, UI `RESERVED_FOR_OUTPUT=2048` in `rag/app.py`
- **Thinking** — Keep `chat_template_kwargs: {enable_thinking: False}` unless you raise
  budgets: with thinking on, ~900–2,000 reasoning tokens can starve the answer

DIY rollback only: `modal_app.py` holds the legacy GPU/model/volume settings
(`modal deploy modal_app.py`).

### 4. Modify Embedding Model

Edit `rag/embed_chunks.py` to use a different FastEmbed model:

```python
# Current (default)
embedding_model = FastEmbed(model_name="BAAI/bge-small-en-v1.5")

# Alternative: larger but slower
embedding_model = FastEmbed(model_name="BAAI/bge-base-en-v1.5")

# Alternative: multilingual
embedding_model = FastEmbed(model_name="BAAI/bge-m3")
```

Then re-embed and re-upload:
```bash
cd rag
python embed_chunks.py
python upload_chunks.py
```

---

## Troubleshooting

### Cold Start is Too Long (15-60s) / 503 errors

**Expected behavior.** This is by design: the first request spins up a GPU container
from scale-to-zero, and the proxy may return 503 while it starts. This is the
trade-off for paying $0 compute when idle. Subsequent warm requests are fast.

**Solution:** Click the "Pre-warm Modal backend" button before you start chatting, so the cold start happens in the background. The CLI (`ask.py`) and UI both retry 503s automatically (15/30/60s) with status updates.

### "ModuleNotFoundError: No module named 'modal'"

```bash
pip install modal
modal setup
```

Then authenticate in the browser window that opens.

### "Connection refused: localhost:8501"

Streamlit isn't running. Start it:

```bash
streamlit run rag/app.py
```

Then open `http://localhost:8501`. (Run from repo root so `.env` loads.)

### "SUPABASE_DB_URL not set"

Check `.env` file exists in the project root with (pooler `:6543`, not `:5432`):
```
SUPABASE_DB_URL=postgresql://postgres.<ref>@aws-1-<region>.pooler.supabase.com:6543/postgres
```

If not set, Streamlit will error. Restart after fixing `.env`.

### "No chunks in Supabase" / Retrieval returns nothing

The `doc_chunks` table is empty. Run the pipeline:

```bash
cd rag
python chunk_docs.py
python embed_chunks.py
python upload_chunks.py
```

Check that `creator-docs/` folder exists with Roblox docs.

### "Invalid embedding dimension" / pgvector errors

The embedding dimension must match. BAAI/bge-small-en-v1.5 produces **384-dimensional** vectors.

Check the `embedding VECTOR(384)` line in the Supabase table schema.

### "MODAL_ENDPOINT_URL not set" / 404 "invalid function call"

The endpoint URL isn't in `.env`, or it was guessed. Copy it **exactly** (dashboard
Endpoints tab → `efar-coder` → copy icon) — the old `--efar-serve.modal.run`
pattern 404s on Dedicated:

```
MODAL_ENDPOINT_URL=https://<workspace>--ep-efar-coder-server.us-west.modal.direct
MODAL_MODEL=Qwen/Qwen3.5-4B
MODAL_PROXY_TOKEN=wk-<id>.ws-<secret>
```

Then restart Streamlit.

| Status | Meaning | Fix |
|--------|---------|-----|
| 401 | Bad/missing proxy token | `modal workspace proxy-tokens create`, update `.env` |
| 404 `invalid function call` | Wrong URL (guessed DIY pattern) | Re-copy from dashboard |
| 503 | Container still starting | Wait — CLI/UI retry automatically |

### Model generates gibberish / poor code quality / empty answers

Possible causes:
1. **Poor system prompt** — Fill in `system_prompt.md` with game context (generic prompts → generic answers)
2. **Cold start quirk** — First request after idle may have lower quality. Subsequent requests are better (due to caching).
3. **Insufficient context** — Increase `TOP_K` in `rag/retrieve.py` to retrieve more docs (trade-off: longer inference time)
4. **Thinking budget** — `enable_thinking: False` is set so reasoning can't eat the
   answer budget. If you re-enable thinking, raise `MAX_TOKENS`/`RESERVED_FOR_OUTPUT` well above 2048.

### Supabase query fails / "pgvector not installed"

Ensure pgvector extension is enabled:
1. Supabase Dashboard → Settings → Extensions
2. Search "pgvector" and enable it
3. Restart your Python process

### "Endpoint stuck Starting" / repeated 503s

The Dedicated container can take several minutes on first provisioning. Check the
dashboard Endpoints tab → `efar-coder` → Containers. The CLI and UI retry
automatically; if it stays `Starting` > 5 min, check container logs in the dashboard.
(`modal deploy modal_app.py` applies to the legacy DIY rollback path only.)

---

## Known Limitations

### Model Size
- **4B parameters** (Qwen3.5-4B via Modal catalog) — smaller than Claude/GPT flagships, but fast and cheap
- **Trade-off**: Faster inference, lower cost, but sometimes less accurate on complex tasks
- **Workaround**: Detailed system prompt + rich retrieved context + thinking disabled for direct answers

### Context Window
- **Max tokens**: 16384 (`MAX_MODEL_LEN`, shared by CLI trimmers and UI budget)
- **Limitation**: Can't process very long code files or design docs
- **Workaround**: Split long prompts into multiple questions; history trimmer drops oldest pairs first

### Vector Search Limitations
- **Top-K retrieval**: Returns 3 closest docs by default (hybrid keyword + vector + expansion)
- **Limitation**: May miss relevant docs if they're far in embedding space
- **Workaround**: CamelCase keyword matching (handled by `retrieve.py`) + adjust `TOP_K` parameter

### No Fine-Tuning (Yet)
- **Current**: Uses pre-trained Qwen3.5-4B, no custom fine-tuning on your game
- **Planned**: Add fine-tuning pipeline on your game-specific docs
- **Workaround**: Use detailed `system_prompt.md` to guide the model

### Frontend
- **Current**: Streamlit chat UI with streaming, per-code-block copy buttons, Material icons, validation callouts
- **Planned**: Next.js frontend with prettier UI (optional; Streamlit is fully functional)

### Cold Starts
- **Unavoidable**: GPU containers spin up on first request after ~180s idle
- **Duration**: 15-60 seconds, with automatic 503 retry in CLI and UI
- **Workaround**: Use pre-warm button; affinity routing keeps follow-ups on the warm container

---

## Contributing

We welcome contributions! Here's how to get involved:

### Reporting Issues
- Found a bug? [Open a GitHub Issue](https://github.com/Chancelmagne22/exist-for-a-reason/issues)
- Include:
  - Python version & OS
  - Steps to reproduce
  - Error message / logs
  - Expected vs. actual behavior

### Contributing Code

1. **Fork the repo** and create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes:**
   - Bug fixes, Luau validation improvements, new embeddings models, etc.
   - Keep changes focused and well-tested

3. **Test locally:**
   ```bash
   streamlit run rag/app.py
   ```

4. **Commit with clear messages:**
   ```bash
   git commit -m "Add better error messages for hallucination detection"
   ```

5. **Push and create a Pull Request:**
   ```bash
   git push origin feature/your-feature-name
   ```

### Areas We're Looking For Help

- **Frontend** — Build a Next.js UI to complement Streamlit
- **Docs** — Improve setup guides, add troubleshooting, examples
- **Validation** — Better Luau linting, more hallucination detection patterns
- **Fine-tuning** — Create dataset + scripts for game-specific model tuning
- **Dev experience** — Docker setup, one-click deploy scripts, CI/CD
- **Internationalization** — Support non-English Roblox docs / game contexts

### Code Style

- **Python**: Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- **Commits**: Use clear, descriptive messages (not "fix stuff")
- **Documentation**: Add docstrings to new functions

---

## Roadmap

### Shipped (Oct 2026)
- [x] Modal DIY → Dedicated endpoint migration (`efar-coder`, scale-to-zero, proxy-token auth)
- [x] Reasoning-budget fix (`enable_thinking: False` — thinking 259 → 0 tokens on trivial prompts)
- [x] Cold-start 503 auto-retry + affinity routing in CLI and Streamlit
- [x] Fail-fast Supabase connects (`connect_timeout=10`) with stage logging
- [x] Streamlit per-code-block copy buttons + zero-emoji Material icon pass
- [x] CLI smoke-test flags (`--no-retrieval`, `--stream`, `--once`)

### Q3 2026
- [ ] Next.js frontend (prettier UI, better code display)
- [ ] Fine-tuning pipeline (train on game-specific docs)
- [ ] Support for additional LLMs (Llama 3, CodeLlama)

### Q4 2026
- [ ] IDE plugins (VS Code extension for Roblox)
- [ ] Batch processing (analyze multiple scripts at once)
- [ ] Analytics dashboard (usage, cost, performance tracking)

### 2027+
- [ ] Multimodal support (analyze screenshots, .rbxl files)
- [ ] Collaborative features (share contexts, feedback loops)
- [ ] Marketplace (community-contributed contexts, linters, validators)

---

## Frequently Asked Questions

### Why Roblox-specific?
Roblox has unique APIs, patterns, and best practices. A Roblox-focused assistant beats generic code models for game development.

### Why Modal instead of my own GPU?
- **Cost**: Modal charges only for active GPU time. Idle = $0. Your own GPU means fixed costs + electricity + maintenance.
- **Simplicity**: No GPU setup, driver management, or infrastructure overhead.
- **Scaling**: Modal auto-scales; your GPU doesn't.

### Why not just use Claude / ChatGPT?
- **Cost**: Subscriptions ($20/month) or per-token API costs add up.
- **Privacy**: Your code stays on your infrastructure (Modal is still third-party, but you control it).
- **Speed**: No API rate limits or queue waits.

### Can I fine-tune EFAR for my specific game?
**Future goal!** Currently, we use system prompt for game context. A fine-tuning pipeline is planned for Q3 2026.

### What if I run out of Modal credits?
Dedicated endpoints bill per-second compute and scale to $0 when idle, so typical
experimental use stays inside the $30/mo free tier. Set up billing alerts in the Modal dashboard regardless.

### Can I use EFAR without Supabase?
Currently, no—the RAG pipeline requires vector search. Future versions may support other vector DBs (Pinecone, Weaviate, Milvus).

### Is EFAR production-ready?
**Alpha status.** It works, but:
- Frontend is basic (Streamlit)
- Edge cases in code validation may exist
- Performance under high load not yet tested

Use at your own risk in production. Community testing + feedback welcome!

---

## License

EFAR is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

**In plain English**: You can use, modify, and distribute EFAR freely, including for commercial projects, as long as you include the license and attribute the original work.

---

## Support

- **GitHub Issues** — Bug reports, feature requests
- **GitHub Discussions** — Questions, ideas, show-and-tell

---

## Acknowledgments

Built with:
- [Qwen3.5-4B](https://huggingface.co/Qwen) — The LLM powering inference (via Modal catalog)
- [Modal](https://modal.com) — Serverless GPU hosting (Dedicated endpoint)
- [Supabase](https://supabase.com) — Vector database (pgvector)
- [FastEmbed](https://github.com/qdrant/fastembed) — Lightweight embeddings
- [Streamlit](https://streamlit.io/) — Chat UI framework
- [Roblox Creator Docs](https://github.com/Roblox/creator-docs) — Official API reference (3,933 chunks)

---

## CV Bullets

Copy-paste ready (trim to fit):

- Built solo RAG coding assistant for Roblox Luau: 3,933 doc chunks (FastEmbed `bge-small-en-v1.5` + Supabase pgvector, hybrid keyword/vector retrieval) grounding `Qwen3.5-4B` on a Modal Dedicated scale-to-zero endpoint.
- Shipped OpenAI-compatible inference path with proxy-token auth, cold-start 503 auto-retry, affinity routing, and reasoning-budget fix (259 → 0 thinking tokens on trivial prompts).
- Built Streamlit chat UI (live SSE streaming, per-code-block copy buttons, Material icons) plus a matching CLI with `--no-retrieval`/`--stream` smoke-test flags.
- Hardened data path: Supabase connects fail fast (`connect_timeout=10`), stage-level logging, token-budget trimmers shared across CLI/UI (`MAX_MODEL_LEN=16384`).
- Operated inside Modal's $30/mo free tier (per-second Dedicated billing, $0 when idle).

---

**Happy coding!**