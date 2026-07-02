# 🎮 EFAR: Exist For A Reason

> **A self-hosted, Roblox-focused AI coding assistant powered by GPU inference and semantic search.**
>
> *Because I'm too poor to avail Claude.*

![Status](https://img.shields.io/badge/status-Alpha-yellow)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
[![Modal](https://img.shields.io/badge/Powered%20by-Modal-blueviolet)](https://modal.com)
[![Supabase](https://img.shields.io/badge/Backed%20by-Supabase-3ECF8E)](https://supabase.com)

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

- 🎯 **Knows Roblox** — trained on Qwen2.5-Coder with Roblox API documentation embedded via RAG
- 💰 **Pays only when used** — runs on Modal serverless GPUs, scales to $0 when idle (180s inactivity)
- 🔍 **Semantically searches your docs** — embeds Roblox creator-docs in Supabase vector database for retrieval
- ✅ **Validates Roblox code** — post-generation linting catches hallucinations (wrong enum values, deprecated methods, etc.)
- 🚀 **Fast after cold start** — first request ~15-40s, then cached for snappy responses
- 🔒 **Completely private** — runs on your own infrastructure, no telemetry

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
Runs **Qwen2.5-Coder-7B-Instruct (AWQ quantized)** on Modal A10G GPUs:
- ~5GB model (quantized to fit A10G VRAM)
- vLLM serving (OpenAI-compatible `/v1/chat/completions` endpoint)
- Idle scaledown (180s) → $0 when not in use

### 4. **Prefix Caching**
Your system prompt (game context) is cached on the GPU, so repeated queries reuse it without recomputation—faster responses, lower costs.

### 5. **Multi-Source RAG Pipeline**
- Chunks Roblox creator-docs from GitHub sparse checkout
- Embeds with FastEmbed (BAAI/bge-small-en-v1.5)
- Stores in Supabase + pgvector for semantic search
- Optional: add your own game design docs

### 6. **Streamlit Chat Interface**
Interactive UI with:
- Pre-warm button (trigger cold start while you set up)
- Message history
- Code syntax highlighting
- Real-time streaming responses

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
│  Model:                   Qwen2.5-Coder-7B-AWQ                 │
│  Serving:                 OpenAI-compatible endpoint            │
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
| **LLM Model** | Qwen2.5-Coder-7B-Instruct-AWQ | 7B-parameter code model, quantized for A10G |
| **Inference Runtime** | vLLM | LLM serving with prefix caching, OpenAI-compatible API |
| **GPU Hosting** | Modal | Serverless GPU compute (A10G, pay-per-use) |
| **Vector Database** | Supabase PostgreSQL + pgvector | Embedding storage & semantic search |
| **Embeddings Model** | FastEmbed (BAAI/bge-small-en-v1.5) | Document chunking & query embedding |
| **Frontend** | Streamlit | Interactive chat UI (Next.js planned) |
| **Language** | Python 3.10+ | All backend logic |
| **Docs Source** | Roblox creator-docs (GitHub) | Official Roblox API reference & guides |

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

Create `.env` in the project root:

```bash
# .env
MODAL_ENDPOINT_URL=https://your-workspace--efar-serve.modal.run
SUPABASE_DB_URL=postgresql://postgres:your-password@your-project.supabase.co:5432/postgres
NEXT_PUBLIC_API_URL=http://localhost:8501  # Streamlit default
```

Do NOT commit `.env` to version control. Use `.env.example` as a template:

```bash
# .env.example
MODAL_ENDPOINT_URL=https://your-workspace--efar-serve.modal.run
SUPABASE_DB_URL=postgresql://postgres:YOUR_PASSWORD@YOUR_PROJECT.supabase.co:5432/postgres
NEXT_PUBLIC_API_URL=http://localhost:8501
```

### Step 7: Populate Roblox Docs in Supabase

Run the RAG pipeline to chunk, embed, and upload the Roblox creator-docs:

```bash
cd rag

# Step 1: Chunk the Markdown docs
python chunk_docs.py
# Output: chunks.jsonl (~10k-50k chunks depending on docs)

# Step 2: Embed chunks
python embed_chunks.py
# Output: chunks_embedded.jsonl
# ⏱️ This may take 5-15 minutes depending on number of chunks

# Step 3: Upload to Supabase
python upload_chunks.py
# Inserts embeddings into doc_chunks table

cd ..
```

### Step 8: Deploy the Backend to Modal

Deploy the Qwen model to Modal:

```bash
modal deploy modal_app.py
```

**What happens:**
1. Modal builds a container with Python, vLLM, and all dependencies
2. Downloads Qwen2.5-Coder-7B-Instruct-AWQ model (~5GB) from Hugging Face
3. Deploys to Modal infrastructure
4. Caches the model in a Modal Volume (no re-download on future deploys)

**First deploy takes ~5-10 minutes.** Subsequent deploys are much faster.

When complete, Modal prints:
```
https://<your-workspace>--efar-serve.modal.run
```

**Copy this URL** and add it to your `.env`:
```
MODAL_ENDPOINT_URL=https://<your-workspace>--efar-serve.modal.run
```

### Step 9: Test the Backend Endpoint

```bash
curl https://<your-workspace>--efar-serve.modal.run/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "roblox-coder",
    "messages": [
      {"role": "user", "content": "How do I create an NPC using PathfindingService in Roblox Luau?"}
    ]
  }'
```

Expected response: JSON with a Luau code example.

> ⏱️ **First request will take 15-40 seconds** (cold start—Modal spinning up GPU). This is expected and by design. Subsequent requests within the idle window are fast. After 180 seconds of inactivity, the container scales down to $0.

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

Then **redeploy** to pick up the new context:

```bash
modal deploy modal_app.py
```

### Step 11: Run the Streamlit UI

```bash
streamlit run rag/app.py
```

Streamlit opens at `http://localhost:8501`. You'll see:
- Chat interface
- Pre-warm button (optional, triggers cold start in background)
- Message history
- Response streaming

You're ready to go! 🎉

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

Click the **Pre-warm Modal backend** button to trigger a cold start while you're setting up. This avoids the first 15-40 second delay on your first real query.

### Code Validation

EFAR automatically checks generated code for:
- ✅ Correct casing (`.Magnitude` not `.magnitude`)
- ✅ Modern API usage (`task.wait()` not `wait()`)
- ✅ Enum validity (e.g., `Enum.HumanoidStateType.Running` exists)
- ✅ Known Roblox services exist
- ⚠️ Deprecation warnings (e.g., `Humanoid.Health` is deprecated on R15)

Invalid code is highlighted with explanations.

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
| **modal_app.py** | Configures Qwen + vLLM on Modal. Defines GPU (A10G), model params, volumes, and the `/v1/chat/completions` endpoint. Deploy this to Modal with `modal deploy modal_app.py`. |
| **rag/app.py** | Streamlit chat UI. Handles message history, pre-warming, streaming responses, and code validation. Run with `streamlit run rag/app.py`. |
| **rag/chunk_docs.py** | Parses Markdown + YAML from Roblox creator-docs. Splits into semantic chunks (~500-1000 tokens each). Outputs `chunks.jsonl`. |
| **rag/embed_chunks.py** | Uses FastEmbed to create 384-dim embeddings for each chunk. Outputs `chunks_embedded.jsonl`. |
| **rag/upload_chunks.py** | Bulk-inserts embeddings + metadata into Supabase `doc_chunks` table. |
| **rag/retrieve.py** | Core retrieval logic: embed query, search Supabase, keyword-match class names, return top-K results. |
| **rag/ask.py** | CLI tool to test the full pipeline: question → retrieval → inference → answer (useful for debugging). |
| **system_prompt.md** | Game context injected into the system prompt. Customize this with your game's architecture, naming conventions, and systems. |

---

## Customization

### 1. Update Game Context

Edit `system_prompt.md` with your game's:
- **Architecture** — Folder structure, key systems, tech choices
- **Naming conventions** — How you name services, events, modules
- **Known patterns** — Specific RemoteEvent patterns, DataStore design
- **Things to avoid** — Anti-patterns, deprecated APIs you've opted out of

After editing, **redeploy**:
```bash
modal deploy modal_app.py
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

Edit `modal_app.py` to modify:
- **GPU type** — Change from `A10G` to `A100` for larger models (higher cost)
- **Max model length** — Increase from `8192` to allow longer contexts (uses more VRAM)
- **GPU memory utilization** — Tune from `90%` for stability vs. cost
- **Scaledown timeout** — Change from `180s` to scale down faster/slower
- **Quantization** — Use full-precision model instead of AWQ (requires more VRAM/GPU)

Then redeploy:
```bash
modal deploy modal_app.py
```

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

### Cold Start is Too Long (15-40s)

**Expected behavior.** This is by design: the first request spins up a GPU container from scratch. This is the trade-off for paying $0 when idle. Subsequent requests within the 180s idle window are fast.

**Solution:** Click the "Pre-warm Modal backend" button before you start chatting, so the cold start happens in the background.

### "ModuleNotFoundError: No module named 'modal'"

```bash
pip install modal
modal setup
```

Then authenticate in the browser window that opens.

### "Connection refused: localhost:8501"

Streamlit isn't running. Start it:

```bash
cd rag
streamlit run app.py
```

Then open `http://localhost:8501`.

### "SUPABASE_DB_URL not set"

Check `.env` file exists in the project root with:
```
SUPABASE_DB_URL=postgresql://postgres:...@....supabase.co:5432/postgres
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

### "MODAL_ENDPOINT_URL not set"

The Modal endpoint URL isn't in `.env`. After deploying `modal_app.py`, you'll see:

```
https://<your-workspace>--efar-serve.modal.run
```

Add to `.env`:
```
MODAL_ENDPOINT_URL=https://<your-workspace>--efar-serve.modal.run
```

Then restart Streamlit.

### Model generates gibberish / poor code quality

Possible causes:
1. **Poor system prompt** — Fill in `system_prompt.md` with game context (generic prompts → generic answers)
2. **Cold start quirk** — First request after idle may have lower quality. Subsequent requests are better (due to caching).
3. **Insufficient context** — Increase `TOP_K` in `rag/retrieve.py` to retrieve more docs (trade-off: longer inference time)
4. **Model size** — 7B Qwen is smaller than 70B alternatives. Consider upgrading GPU & model if budget allows.

### Supabase query fails / "pgvector not installed"

Ensure pgvector extension is enabled:
1. Supabase Dashboard → Settings → Extensions
2. Search "pgvector" and enable it
3. Restart your Python process

### "Modal deploy hangs"

Modal may be waiting for user input (rare). Check terminal for prompts. If stuck >5 min:
```bash
# Cancel (Ctrl+C) and retry
modal deploy modal_app.py
```

---

## Known Limitations

### Model Size
- **7B parameters** — Smaller than Claude (70B+) or GPT-4 (1T+), but good for code
- **Trade-off**: Faster inference, lower VRAM, but sometimes less accurate on complex tasks
- **Workaround**: Use detailed system prompt + rich context to compensate

### Quantization
- **AWQ quantization** — Reduces model size from ~14GB to ~5GB to fit A10G VRAM
- **Trade-off**: Slight accuracy loss vs. fitting on affordable GPU
- **Workaround**: Use full-precision model on larger GPU (A100, H100) if accuracy critical

### Context Window
- **Max tokens**: 8192
- **Limitation**: Can't process very long code files or design docs
- **Workaround**: Split long prompts into multiple questions; use system prompt for static context

### Vector Search Limitations
- **Top-K retrieval**: Returns 3 closest docs by default
- **Limitation**: May miss relevant docs if they're far in embedding space
- **Workaround**: Use keyword matching (handled by `retrieve.py`) + adjust `TOP_K` parameter

### No Fine-Tuning (Yet)
- **Current**: Uses pre-trained Qwen2.5-Coder, no custom fine-tuning on your game
- **Planned**: Add fine-tuning pipeline on your game-specific docs
- **Workaround**: Use detailed `system_prompt.md` to guide the model

### Frontend
- **Current**: Streamlit-based UI (functional but basic)
- **Planned**: Next.js frontend with prettier UI, markdown rendering, code highlighting
- **Status**: Not yet implemented

### Cold Starts
- **Unavoidable**: GPU containers spin up on first request after 180s idle
- **Duration**: 15-40 seconds
- **Workaround**: Use pre-warm button or keep-alive logic (not yet implemented)

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

- 🎨 **Frontend** — Build a Next.js UI to replace Streamlit
- 📚 **Docs** — Improve setup guides, add troubleshooting, examples
- ✅ **Validation** — Better Luau linting, more hallucination detection patterns
- 🧠 **Fine-tuning** — Create dataset + scripts for game-specific model tuning
- 🔧 **Dev experience** — Docker setup, one-click deploy scripts, CI/CD
- 🌐 **Internationalization** — Support non-English Roblox docs / game contexts

### Code Style

- **Python**: Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- **Commits**: Use clear, descriptive messages (not "fix stuff")
- **Documentation**: Add docstrings to new functions

---

## Roadmap

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
You pay out-of-pocket (typically $0.50-$5/day for active development). Set up billing alerts in Modal dashboard.

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

- 💬 **GitHub Issues** — Bug reports, feature requests
- 💭 **GitHub Discussions** — Questions, ideas, show-and-tell

---

## Acknowledgments

Built with:
- [Qwen2.5-Coder](https://github.com/QwenLM/Qwen2.5-Coder) — The LLM powering inference
- [Modal](https://modal.com) — Serverless GPU hosting
- [Supabase](https://supabase.com) — Vector database (pgvector)
- [vLLM](https://vllm.ai/) — Fast LLM serving
- [FastEmbed](https://github.com/qdrant/fastembed) — Lightweight embeddings
- [Streamlit](https://streamlit.io/) — Chat UI framework
- [Roblox Creator Docs](https://github.com/Roblox/creator-docs) — Official API reference

---

**Happy coding! 🚀**

> made with 💜 by someone too poor to afford Claude