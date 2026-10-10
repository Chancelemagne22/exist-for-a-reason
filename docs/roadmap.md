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

## Migration — DIY `modal_app.py` → Modal Dedicated Endpoint (free $30/mo, experimental)

> Decision 2026-10-03: migrate. Project is purely experimental for Roblox AI. Must stay inside $30/mo free credits.
> Key billing rule: `Shared Endpoints` (per-token) CANNOT use free credits (out-of-pocket only). `Dedicated Endpoints` (per-second compute, scale-to-zero) DO use credits. → Use Dedicated only.

### Cost baseline (Sept 2026 pricing)
- `A100-40GB $2.10/hr`, `A10G $1.10/hr`, `L4 $0.799/hr` (cheapest 24GB), `H100 $3.95/hr` — avoid.
- 20 queries/day x 30s active: A100 ~$10.50/mo, A10G ~$5.50/mo, L4 ~$4.00/mo. All fit $30 if scale-to-zero holds.
- Avoid screenshot traps for free tier: `Kimi K3 (2.8T)`, `Qwen3.6-35B-A3B` need large GPUs — burns $30 in days.

### Target
- `Dedicated Endpoint`, `us-west` default (no `--colocate-compute` multiplier), scale-to-zero, proxy-token auth.
- Model: `Qwen2.5-Coder-7B-Instruct-AWQ` if in catalog (safest, same quality), fallback `Qwen3.5-4B` or `Gemma 4 E4B IT` compact. No 35B/Kimi on free tier.
- Keep RAG/UI untouched (`rag/retrieve.py`, validators, `TOP_K=3`); only inference URL + auth + model name change.

### M0 — Baseline (30 min, no changes)
- [ ] Record dashboard Usage $/day, `modal volume list` (`efar-hf-cache` size), cold-start p50 (15-40s now)
- [ ] Confirm workspace spend limit = $30, Starter plan credits active

### M1 — Create Dedicated Endpoint (30 min, dashboard + CLI)
- [ ] Dashboard Endpoints tab → Browse catalog → confirm 7B-AWQ or 4B availability + compute rate shown
- [ ] `modal endpoint create --name efar-coder --model Qwen/Qwen2.5-Coder-7B-Instruct-AWQ` (fallback `--model Qwen/Qwen3.5-4B`)
- [ ] `modal workspace proxy-tokens create` → save `wk-<id>.ws-<secret>` to password manager (never commit)
- [ ] `curl` smoke test with `Authorization: Bearer wk-...ws-...` to `/v1/chat/completions`

### M2 — Code swap (1-2 hrs, reversible)
- [ ] `.env.example` + `.env`: add `MODAL_ENDPOINT_URL=<dedicated-url>`, `MODAL_PROXY_TOKEN=wk-...`, `MODAL_MODEL=<catalog-name>`
- [ ] `rag/app.py:15,211`: read new env, add `Authorization` header, use `MODAL_MODEL` instead of hardcoded `roblox-coder`
- [ ] `rag/ask.py:216-257`: same header + model change, keep `MAX_MODEL_LEN=16384`, `SAFETY_MARGIN=500`
- [ ] Keep `modal_app.py` as rollback for 1 week (do not delete volumes yet)

### M3 — Verify + guardrails (1 day soak)
- [ ] 3-query check: cold + warm + follow-up → TTFT, citations, validation warnings OK
- [ ] 429/expiry handling: proxy-token 401 shows friendly `st.error`, no crash
- [ ] Cost check: dashboard <$0.50/day, `modal endpoint list` shows idle scale-to-zero
- [ ] Guardrails: no `min_containers=1`, no pre-warm loop, keep `RESERVED_FOR_OUTPUT=2048`, dynamic `max_tokens`

### M4 — Decommission DIY (after 1 week green)
- [ ] `modal endpoint stop` old test deploys if any; keep `efar-hf-cache` volume 1 week, then delete
- [ ] Append Endpoint ID + model + $/day to `docs/audit.md` + check P2 sign-off gate
- [ ] Rollback: revert `.env` to old `--efar-serve.modal.run` URL + `modal deploy modal_app.py` — RAG unchanged

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
