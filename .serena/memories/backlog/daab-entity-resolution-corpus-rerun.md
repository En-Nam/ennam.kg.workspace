# Backlog — Step 1a DONE · 1b + Step 2 pending

**Filed:** 2026-06-29 · **1a completed:** 2026-06-30 · **Branch:** `task/implement_docs_sync` · **Parent direction:** cross-document entity linking. Related: `mem:ba031-resolution-thresholds-gates`, `mem:backlog/ba033-slice2-readiness-path`, `mem:decisions/ba033-slice2-deferred`.
> ⚠️ DB state: stack is the **daab-* docker compose** (host ports: Go API :8082, postgres via `docker exec daab-postgres`, redis `daab-redis`). NOT :5433.

## Why this (not Slice 2) — settled 2026-06-29
User's two REAL needs: (1) "which docs does this figure come from" = **provenance → ALREADY BUILT**; (2) "how are these 2 documents related" = **cross-document linking via shared entities → was BLOCKED, 1a unblocks it**. Global synthesis = AAA's role, not DAAB. DAAB builds the connected graph; consumer does synthesis. BA-033 Slice 2 = DROPPED.

## ✅ 1a — DONE (2026-06-30): resolution re-run on big corpus `592c7ff7-9f6f-4cc5-9094-d9b3b685277e`
**Root cause:** corpus ingested via `extract_upload` → `ingestion_engine.run_batch()` (creates nodes, NO BA-031 resolution chain). `chunk_extraction_state` had 0 rows → `resolve_document` never fired. The `extract_document`→chunk-complete→`resolve_document` chain is a SEPARATE path.

**Re-trigger path:** `POST /api/v1/ingestion/documents/{docId}/extract` on Go (`daab-server` :8082) with `X-Project-ID: 592c7ff7…` + `Authorization: Bearer ennam_kg_dev_0000…`. Returns `{dispatched, run_id, skipped}`. Batch-triggered 113 docs / 626 chunks. apply-exact-name auto-fires per `resolve_document` (worker.py:282) — gated by `resolution.auto_apply_exact_name=true` (NOT apply_mode); can also call manually: `POST /api/v1/internal/resolution/apply-exact-name {"project_id":…}`.

**Results (success criteria all met):**
- 626/626 chunks `resolved`.
- `merge_suggestions` = 10,381 (5,686 `applied` + 4,695 `suggested`); 2,936 entities `superseded`, 4,297 active canonicals.
- Duplicate-node count **876 → 523** (237 name-groups). Remainder is HUBS + generic terms → that's 1b.
- Cross-doc verified: "Chính phủ" → 1 active canonical (24 edges re-pointed, has `provenance`/`merge_undo`/`resolution_audit`/`aliases_merge_provenance`).
- Of the 4,695 `suggested`: **661 exact-name** (1b candidates) + 4,034 semantic.

**Tail gotcha:** rebuilding the worker mid-run KILLS in-flight jobs → chunks stuck in `extracting`/`extracted` (doc never hits "all extracted" → no resolve). Fix: re-trigger just the affected docs (skip-guard re-dispatches; `skipped=0` because non-`resolved` chunks aren't skipped — re-extract is wasteful but self-heals via merge). **Don't rebuild worker while a backfill is draining.**

**Perf fixes made this session (code, UNCOMMITTED on `task/implement_docs_sync`):**
1. `worker.py` — extraction consumer was singular despite `worker_concurrency`; now spawns N consumers (`extraction_consumers` list). Set `WORKER_CONCURRENCY=4` in `docker-compose.yml`. ~×4 throughput (I/O-bound, RAM flat, CPU bursts ~8 cores only during pass2 cross-encoder).
2. `pass1.py` + `config.py` + `deps_factory.py` — gleaning was UNCONDITIONAL (always +1–2 LLM calls/chunk). Now gated: skip when `chunk_len < extraction_glean_min_chunk_len` (400) OR entity density ≥ `extraction_glean_density_threshold` (2.0/1k). On this VI legal corpus density is 5–51/1k → gleaning 0% triggered → 2–3 calls/chunk → **1 call/chunk**.
3. Tests updated: `test_ba031a_worker_extraction_consumer.py` dispatch assert `==1`→`>=1`. 7/7 pass.
NOTE: model cache volume `hf_cache:/tmp/huggingface` already in compose (survives rebuild). First load downloads `bge-reranker-v2-m3` ~30s.

## 1b — FOLLOW-ON (next): hub exact-name merge
Hubs (degree≥10) never auto-merge (leaf-only safety). 661 `suggested` rows are exact-name (incl. hubs like "khu bến tổng hợp định an" ×6, "định an" ×5, "duyên hải" ×4). Exact-name merge is SAFE even for hubs (degree gate exists to block *fuzzy* hub merges). Design: relax degree gate ONLY for exact-name (post honorific-strip); reversible; no-LLM. Needs own spec/plan (mutating shipped resolution system). Beware generic terms ("thành viên", "dự án", "doanh nghiệp", "chủ đầu tư") — these are boilerplate, NOT real entities; exact-name merge on them is harmless but consider a stoplist.

## Step 2 (later): thin "related documents / shared entities" retrieval
Given 2 docs → shared canonical entities; given 1 doc → related docs via shared entities. Reuses `ennam.kg.go/internal/store/{neighbors,graph_retrieve}.go`. No LLM. Answers user need #2.

## Cloud note (raised, deferred): cross-encoder is the CPU cost driver
`bge-reranker-v2-m3` runs on CPU in-process; pass2 burst hit ~8 cores at concurrency=4. For cloud: size by steady-state (4 vCPU start), set `WORKER_CONCURRENCY`=vCPU, consider splitting ML inference into its own (optionally GPU) service — `embedding_service_url` already hints this pattern for embeddings. Not urgent (YAGNI).

## Pointers
- `mem:ba031-resolution-thresholds-gates` — pipeline, thresholds, GA state.
- `docs/superpowers/plans/2026-06-22-ba-031-resolution-turn-on-runbook.md`
- Code: `ennam.kg.python` worker.py + `resolution/`, `extraction/pass1.py` ; `ennam.kg.go` chunk-complete + apply_suggestions service.
