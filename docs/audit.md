# EFAR Audit — Current State (2026-10-02)

> Frozen pre-upgrade snapshot. Do not upgrade until P0 docs/fixes in `roadmap.md` are acknowledged.
> Scope: `README.md`, `modal_app.py`, `rag/*.py` (8 files), `system_prompt.md`, `.env.example`, `docs/setup.md`, `requirements.txt`

## Architecture as-built

```
creator-docs sparse checkout → rag/chunk_docs.py → chunks.jsonl
  → rag/embed_chunks.py (FastEmbed bge-small-en-v1.5 CPU) → chunks_embedded.jsonl
  → rag/upload_chunks.py → Supabase pgvector (doc_chunks)
  → rag/retrieve.py (keyword + vector + expansion) → rag/app.py (Streamlit) / rag/ask.py (CLI)
  → Modal vLLM Qwen2.5-Coder-7B-AWQ (/v1/chat/completions, streaming) → regex validation
```

Corpus (local): `3933 chunks`, avg 865 chars, max 19577 chars. Breakdown heavily `class:2001, enum:1354`.

## 1. What is lacking

### Tests — zero coverage
- No `tests/`, no pytest, no RAG evals (RAGAS / deepeval / promptfoo).
- `rag/app.py:92-136` and `rag/ask.py:58-110` duplicated validators have no unit tests.
- `TOP_K=3` change (`rag/retrieve.py:26`) has no eval to prove improvement.

### Docs divergence (must fix before upgrade)
- GPU/context: `README.md:62-65` says A10G/8192 ctx, `modal_app.py:52,67` is A100-40GB/16384, `rag/ask.py:35` hardcodes 8192, sidebar `rag/app.py:47-49` says 10min vs `scaledown_window=180` (3min).
- `README.md:526` promises `rag/custom-docs/` auto-ingest; `rag/chunk_docs.py:193-199` only globs `luau/**/`, `scripting/**/`, `characters/**/`.
- `rag/upload_chunks.py:33` points to `docs_supabase_setup.md` which does not exist.
- `docs/setup.md:96-98` says frontend “Coming soon”, `README.md:76-81,393-403` already documents Streamlit.
- Missing: CONTRIBUTING, SECURITY, CHANGELOG, API reference, cost runbook.

### CI/CD / packaging
- No `.github/workflows`, no ruff/black/mypy, no pre-commit.
- `requirements.txt:1-16` all unpinned, no `pyproject.toml` / `uv.lock`.
- `rag/chunks.jsonl` (4.3MB) tracked in git; `chunks_embedded.jsonl` (37MB) gitignored — clone requires 5-15min re-embed. No DVC / HF Dataset versioning.
- `rag/creator-docs` is untracked content, not a submodule — broken sparse-checkout story.

### Observability
- `print()` only in `rag/ask.py:286,323`, `rag/retrieve.py:191,194`, `rag/app.py:197`. No structlog, no request IDs.
- `usage` from vLLM printed then discarded (`rag/ask.py:326`); ignored in UI (`rag/app.py:224-250`).
- No p50/p95, TTFT, tokens/s, cost/query tracking. No health probe on Modal (`modal_app.py:63-81` opaque Popen).
- `MODEL_REVISION=None` (`modal_app.py:24`), no corpus_version / embedding-model tag in DB.

### Security (P0)
- Modal `@modal.web_server` open internet, no auth, no rate limit — anyone with URL burns GPU.
- `SUPABASE_DB_URL` superuser URI shipped to Streamlit client env (`rag/retrieve.py:187-198`). No pooled 6543, no read-only role, no RLS.
- `.env` exists locally but `.env.example:6-10` omits `MAX_MODEL_LEN` drift.
- `system_prompt.md:1-27` blank template — no guardrails. No prompt-injection guard.

## 2. Issues — confirmed bugs

| ID | Location | Bug |
|----|----------|-----|
| B1 | `rag/app.py:15` | `ENDPOINT = os.environ.get(...) + "/v1/..."` → `"/v1/chat/completions"` when unset, no `st.stop()` |
| B2 | `rag/app.py:239` | bare `except: pass` drops malformed SSE chunks silently |
| B3 | `rag/app.py:38-41` | `ping_modal(timeout=5)` always times out on cold start (15-40s) but sets `warmed_up=True` — false positive |
| B4 | `rag/app.py:167-171` | `covered:set()` never cleared → after ~20 turns `context_block=""` ungrounded with no warning |
| B5 | `rag/app.py:47-49` vs `modal_app.py:53` | sidebar 10min vs code 180s |
| B6 | `rag/retrieve.py:192` | `TextEmbedding()` reloaded per query (1-3s + 200MB) — needs `@st.cache_resource` |
| B7 | `rag/retrieve.py:197-212` | `psycopg2.connect` no try/finally/pool, leaks on exception |
| B8 | `rag/retrieve.py:169-183` | `embedding <=> %s::vector` defaults L2; README SQL creates IVFFLAT without opclass match → seq-scan risk |
| B9 | `rag/chunk_docs.py:62-99` | `GROUP_SIZE=5` blows `MAX_CHARS=2000` — measured max 19577 chars (~5k tokens) |
| B10 | `rag/chunk_docs.py:208-210` | global `idx` in IDs shifts all downstream IDs on ingest → `ON CONFLICT DO UPDATE` churn |
| B12 | `modal_app.py:63-81` | `Popen(vllm serve)` no supervise/healthcheck, `VLLM_SERVER_DEV_MODE=1` left on |
| B14 | `rag/app.py:134` vs `rag/ask.py:369` | `\r\n` missed in UI regex, works in CLI — silent divergence |
| B15 | `rag/ask.py:28,114` + `rag/app.py:173-182` | CLI CWD-relative `system_prompt.md` fails silently; UI hardcodes prompt — CLI/UI diverge |

Tech debt: duplicated `validate_answer` (~45 lines) + `post_validate_and_clean`, config sprawl (`TOP_K`, `MAX_MODEL_LEN`, `SAFETY_MARGIN 200 vs 500`), `chars//4` token estimate undercounts 30-50%, blocking I/O in Streamlit, no types.

Perf: 4 sequential SQL per turn, prefix-cache defeated by changing `context_block`, A100 ~1.9x cost vs A10G for 7B-AWQ with no bench, TOP_K expansion can yield 6-12k prompt tokens.

## 3. What can be improved / changed (no upgrade yet)

- Extract `rag/efar_core/{config.py,retrieval.py,validation.py,prompting.py}` + `pydantic-settings`.
- Add `ruff + black + mypy`, `pytest --cov-fail-under=70`, `structlog`, `tenacity` + `httpx` timeouts.
- Fix chunking: `MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter(800, overlap 120)`, stable `content_hash` IDs.
- DB: `HNSW + halfvec + cosine`, `pg_trgm` title index, `ef_search` tuning, `tsvector` hybrid + RRF.
- UX: clearable `covered` cache, token-budget bar, citations with distance, 👍/👎 to eval set, persist history to Supabase.
- DX: `uv sync && modal deploy && streamlit run`, `justfile`, `.env.example` CI check.
- Simplifications: fold `check_embeddings.py` into `embed_chunks --verify`, merge `docs/setup.md` into README, use or delete `fastapi/uvicorn`, unify `build_messages()` loading `system_prompt.md`.

## 4. What can be updated (deferred — see roadmap P2)

| Now | Target 2026 |
|-----|-------------|
| Python 3.10/3.11/3.12 mix | 3.12 everywhere, `add_python="3.12"` |
| `vllm-openai:v0.15.1` | `v0.17.0+ cu130`, V1 engine, FP8 KV, xgrammar |
| Qwen2.5-Coder-7B-AWQ (2024) | Eval `Qwen3-Coder-30B-A3B-FP8` (A100) or `Qwen3-8B-AWQ` (A10G) |
| bge-small-en-v1.5 384d/512tok | `Qwen3-Embedding-0.6B` or `bge-m3` 1024d + `Qwen3-Reranker-0.6B-ONNX` top-20→5 |
| IVFFLAT lists=100, VECTOR(384) | HNSW + halfvec(1024) + cosine, pgvector>=0.8 |
| psycopg2-binary | psycopg3[binary,pool] |
| unpinned deps | `uv.lock` + `pip-audit` + dependabot |
| chars//4, threading, print | tiktoken, httpx.Async, structlog, pg_trgm |

## 5. Latest tech to consider (post-docs)

- **RAG 2.0:** hybrid + RRF, rerank, contextual retrieval (Anthropic), HyDE/multi-query, LangGraph `retrieve→grade→rewrite→generate→validate`.
- **Serving:** Modal Inference batching, Memory Snapshots (5-10x cold-start cut), `modal.Sandbox` for Luau-lsp/Selene validation, `modal.Cron` warmer, `modal.Dict/Queue` semantic cache.
- **vLLM V1:** chunked prefill, prefix-cache (after stabilizing prompt), FP8 KV (2x ctx on A10G), speculative decoding, structured JSON.
- **Evals/cache/UX:** RAGAS 2.0 + deepeval + promptfoo nightly on Modal, Langfuse tracing, GPTCache/Redis (30-60% $/query cut), Vercel AI SDK streaming + citations.
