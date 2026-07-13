# Checkpoint: daab-ingestion + FR-001 full auto-population — 2026-07-13 (session c)

## Arc: made FR-001 (cross-document graph retrieval) work end-to-end on a real deal
Started from the FR-001 harness result, ended with FR-001 auto-populating on ingest. All on branch `task/implement_docs_sync` (NOT merged to main).

## Commits this session
- `fc9afa6` (go) feat: raise HNSW ef_search=400 on graph-retrieve chunk seeds (seed-scoped `WithEfSearch`, fixes post-filter starvation → seed_count:0).
- `9f7f5b7` (go) fix: **Fix 1** — node field length validator counts runes not bytes (`utf8.RuneCountInString`). Vietnamese multi-byte text was rejected ("8000 characters (got 9365)"), silently emptying document_section/chunk creation. THE root cause of empty FR-001 substrate.
- `7edd9dd` (python) fix: **Fix 2** — fail-loud ingestion. `decompose.py` counts substrate failures (`DecomposeResult.failures`) + logs at WARNING (was debug); engine aggregates `PipelineBatchResult.substrate_failures`; worker logs pipeline-done at WARNING when substrate_failures>0 or sections_created==0.
- `0b4d507` (go) feat: **Fix 4** — `ChunkLinkWorker` background job (every 5m) auto-builds similar_to edges for freshly-ingested projects (>=2 embedded chunks, 0 similar_to). Server-trusted, no API key.

## Deployed + verified (all LIVE on :8082)
- **daab-server** rebuilt (image 2026-07-13 06:31) → ef_search + validator + auto-link worker.
- **daab-worker** rebuilt (image 05:01) → fail-loud.
- (daab-indexer + daab-bridge still on 2026-07-01 images — NOT in the fix path: indexer=code-indexing, bridge=MCP proxy to the current server. Rebuild only for version consistency.)

## E2E proof (real deal: Sala Food `b9a4d353-2bd9-458f-a78a-eb3b54998706`, 15 M&A PDFs)
- Diagnosed: pipeline reported `status=approved errors=0` but produced 0 sections/chunks/embeddings (silent).
- After Fix 1+2 + clean re-ingest: chunk 143/143 + section 68/68 embedded, `substrate_failures=0` in log.
- After Fix 4: deleted Sala's similar_to → one worker tick rebuilt them (Sala 771, dev-project a0000000 87) with NO manual call.
- `kg_graph_retrieve` returns real cross-document results (score 0.87–0.92).
⟹ **FR-001 now auto-populates: ingest → chunk+embed (Fix 1) + loud failures (Fix 2) → auto-link (Fix 4) → retrieve.**

## Not done — follow-ups
- **Fix 3** (worker `GO_API_KEY` is scoped admin `{a0000000, 592c7ff7}` → 403 on new-project reads like "load architecture nodes"): NON-FATAL for doc deals (architecture is code-KG only; substrate writes succeed). Proper fix = give the worker a GLOBAL-ADMIN key (config/ops: create persistent global-admin service key + set worker env + restart). User action. See `mem:backlog/daab-ingestion-pipeline-silent-failures`.
- **Auto-link v1 limitation:** links FRESH deals churn-free; incremental relink when NEW docs are added to an already-linked deal needs a per-chunk link-state / watermark (follow-up).
- 4 XLSX in `doc_pdf_test/project_2` not ingested (upload path is PDF-only).

## Blockers / Risks — CLEANUP DEBT (overdue several sessions)
- ⚠️ **Revoke test API keys**: global-admin `ennam_kg_e953…` (used for Sala ingest + linker), plus older `ennam_kg_e09c…`, `ennam_kg_c622…`, `ennam_kg_009c…`.
- ⚠️ **Rotate** leaked daab-postgres dev password.
- Sala Food project left populated (clean corpus, 15 docs); dev-project a0000000 got auto-linked (87 similar_to) as a side effect.
- **Branch `task/implement_docs_sync` is large and UNMERGED** — accumulates keystone + decay + several bug fixes + this session's 4 commits. Merge risk grows.

## Next steps (recommended order)
1. Security cleanup (revoke keys, rotate password) — overdue.
2. Decide merge of `task/implement_docs_sync` → main (big unmerged branch).
3. Fix 3 (worker global-admin key) — config action.
4. Strategic: FR-001 + memory keystone now both REAL + validated; the open question is still consumer enablement (wire AAAA) vs. hold. No new DAAB-solo feature is demand-justified without a consumer.
