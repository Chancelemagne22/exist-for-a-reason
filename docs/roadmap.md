# EFAR Roadmap — Pre-upgrade Checklist + Upgrade Path

> Rule: document first, upgrade second. P0 must be signed off before any model/embedding bump.

## P0 — Docs / safety / correctness (<2 days, do first)

- [ ] Pin deps (`modal==1.5.*`, `fastembed==0.8.*`, `streamlit==1.58.*`), add `MAX_MODEL_LEN` to `.env.example`, sync check in CI
- [ ] Gitignore `chunks.jsonl`, publish corpus v1.0 to HF Dataset or Supabase dump; fix `creator-docs` as submodule or `--rev` ingest script
- [ ] Auth Modal endpoint (`modal.Secret` bearer) + move `SUPABASE_DB_URL` to pooled `6543` read-only role + rate limit
- [ ] Fix `rag/app.py:15` endpoint guard (`st.stop()` if unset), `\r\n` regex, `bare except`, clearable `covered`, sidebar `180s (3min)` correction
- [ ] Cache embedder (`@st.cache_resource`), pool DB (`psycopg_pool`), `try/finally` close
- [ ] Decide A100→A10G revert or bench justification; set `MAX_MODEL_LEN=16384` everywhere (`ask.py:35`, README:676)
- [ ] Delete dead `docs_supabase_setup.md` ref, merge `docs/setup.md` vs README divergence

## P1 — Quality foundation (3 days – 2 weeks)

- [ ] Dedupe `validation/prompting` into `efar_core`, add `pytest` + CI (`ruff/mypy/audit`), target 70% cov
- [ ] Fix chunking (800/120 overlap, semantic headers), stable IDs (`content_hash`), re-embed + backfill
- [ ] `HNSW + halfvec + cosine` + `pg_trgm` title index + `ef_search` tuning
- [ ] Reranker (`Qwen3-Reranker-0.6B-ONNX`, top-20→5) + hybrid RRF — biggest retrieval gain
- [ ] FastAPI `/ask|/health|/feedback` + persist conversations + citations + 👍/👎

## P2 — Upgrades (1–3 weeks, after P0/P1 sign-off)

- [ ] `vllm v0.15.1 → v0.17+/cu130` + eval `Qwen3-Coder-30B-A3B-FP8` branch (keep 7B fallback)
- [ ] Migrate embeddings `bge-small-384 → Qwen3-0.6B/bge-m3-1024` + `VECTOR(1024)` backfill, store `embedding_model` per row
- [ ] `LangGraph` retrieve-grade-rewrite loop + `RAGAS/promptfoo` nightly + `Langfuse` tracing
- [ ] Semantic cache (Redis/GPTCache) + `Cron` warmer + cost dashboard

## P3 — Strategic (1–2 mo)

- [ ] Next.js 15 + Vercel AI SDK + `modal.Sandbox` Luau-lsp validation + fine-tune pipeline (README:759-772)

## Quick wins (<1 day)

Pin versions, `.env.example` fix, gitignore chunks, endpoint guard, regex fix, sidebar text, `st.cache_resource`.

## Sign-off gate for upgrades

Upgrades start only when: P0 boxes checked, `audit.md` acknowledged, cost baseline ($/query, cold-start p50/p95) recorded, eval set of 50 Luau Q&A goldens created.
