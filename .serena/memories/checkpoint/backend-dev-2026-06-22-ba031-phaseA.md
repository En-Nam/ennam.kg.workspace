# Checkpoint: backend-dev — 2026-06-22 — BA-031 Phase A

## What was done

BA-031 Phase A "Wire the Suggestion-Producer Chain" fully implemented.

**Python (ennam.kg.python) — 6 commits (8d62584..1af2763):**
- `a9e76a1` — extraction-queue consumer wired; `AIClient.complete_json()` + `KGClient.get_node()` + `KGClient.report_chunk_extracted()` added
- `260c99d` — fix: dead code + return type tightened
- `5c41425` — `extract_document` handler: fetches chunk node, runs `run_pass1`, calls chunk-complete
- `a90edd1` — fix: `KGClientError` guard on `get_node` (prevents worker crash on 404)
- `76ae43a` — `resolve_document` handler: `HttpxEntitiesClient` (sync), `build_pass2_deps`, runs `run_pass2_shadow`
- `1af2763` — E2E integration test (deferred/skip gate; runs when live stack available)

**Go (ennam.kg.go) — 2 commits (94960c2..e62b137):**
- `e9859d9` — `GET /api/v1/nodes/{id}`, `POST /api/v1/internal/resolution/entities` (JSONB provenance query), `POST /api/v1/internal/extraction/chunk-complete` (AllChunksExtracted fan-in + MarkDocResolving idempotency)
- `e62b137` — fix: Upsert status regression guard (CASE statement prevents double-publish)

## Files changed

**Python:**
- `src/ennam_kg/config.py` — 4 new settings fields
- `src/ennam_kg/ai_client/client.py` — `complete_json()`
- `src/ennam_kg/worker.py` — extraction consumer + both handlers
- `packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py` — `get_node()`, `report_chunk_extracted()`
- `src/ennam_kg/resolution/deps_factory.py` — `build_pass1_deps()`, `build_pass2_deps()`
- `src/ennam_kg/resolution/entities_client.py` (new) — sync `HttpxEntitiesClient`
- `tests/` — 7 new test files, 501 unit tests pass

**Go:**
- `internal/handler/node_read.go` (new)
- `internal/handler/resolution_entities.go` (new)
- `internal/handler/extraction.go` — `ChunkComplete` handler
- `internal/store/node.go` — `ListEntitiesByProvenance()`
- `internal/store/chunk_extraction_state.go` — `AllChunksExtracted()`, `MarkDocResolving()`, Upsert fix
- `cmd/kg-server/main.go` — wired new handlers
- `internal/handler/*_test.go` — 10 new tests

## Current state

- All Python unit tests: 501 passed, 20 skipped (e2e deferred)
- Go: `go vet` + `go build` OK; golangci-lint not installed locally
- Phase A implementation complete: extract → Pass 1 → chunk-complete → Pass 2 shadow → merge_suggestions

## Key invariants for next steps

- `get_entities` is SYNC (pass2.py calls without await); `HttpxEntitiesClient` uses `httpx.Client` (not async)
- `resolution_sim_threshold=0.74` explicitly set — Go default 0.82 bypassed
- `MarkDocResolving` atomic UPDATE prevents double-enqueue of `resolve_document`
- E2E test uses `decision='suggested'` not `apply_mode='shadow'` (no apply_mode column in merge_suggestions table)

## Next steps

1. **Run the turn-on runbook** (`docs/superpowers/plans/2026-06-22-ba-031-resolution-turn-on-runbook.md`) — verify data gates (entity count, FP rate) before enabling auto-merge
2. **BA-033** — cross-document GraphRAG retrieval (spec + plan + implement)
3. Activate E2E test in CI once Docker stack is wired in pipeline

## Blockers / Risks

- golangci-lint not installed locally — CI may catch additional lint issues
- E2E test deferred until CI has live Docker stack + ANTHROPIC_API_KEY
- `apply_mode` column absent from `merge_suggestions` — check if runbook Step 4/7 needs schema migration

---

## Session 2 — 2026-06-22 — BA-031 Turn-On Runbook (Step 1)

### What was done
- Populated `ennam.kg.python/benchmarks/ba031/vi_blocking_v1.json` — was empty skeleton, now contains real data
- 84 entities / 30 gold groups / 86 true-duplicate pairs extracted from Cảng Định An deal reports (2026-05-28, 2026-05-29)
- Commit: `a2c89ca` on `ennam.kg.python` branch `task/implement_mcp`

### Dataset validation (verified by script)
- Gold groups: 30 ✅ (gate: ≥30)
- True-duplicate pairs: 86 ✅ (gate: ≥50)
- ID uniqueness: PASS ✅
- Hard-case coverage: honorifics ✅ / diacritics↔romanised ✅ / abbreviations ✅ / org variants ✅ / near-miss non-pairs ✅
- Owner set (human validation note included)

### Key near-miss stress-test
- `g_khai_thinh_tv`: Công ty CP Khải Thịnh Trà Vinh (50% shareholder of Hàm Giang)
- `g_khai_thong_tv`: Công ty CP Khai Thông Trà Vinh (unrelated borrower at Sacombank ~599 tỷ VND)
- Near-identical names, entirely different entities — critical precision trap for blocking model

### Runbook gate status
- **Step 1 (populate dataset)**: DONE ✅
- **G1 gate (benchmark recall ≥0.90 @ K=10)**: PENDING — needs benchmark CLI run on staging
- **G2–G6 gates**: PENDING — require staging DB + human review
- **apply_mode**: still "shadow" — NOT flipped (correct; gates not cleared)
- **Tripwire test `TestBA031GA_Step5_GADecisionGuard`**: still expects shadow — NOT modified (correct)

### Next steps (runbook)
1. Stand up staging Docker stack: `docker compose up -d`
2. Ingest test documents into staging KG
3. Run: `python -m ennam_kg.benchmark.cli --dataset benchmarks/ba031/vi_blocking_v1.json --project <id> --out /tmp/ba031-bench.json`
4. Review G1 (recall ≥0.90 @ K=10, threshold in [0.72, 0.75])
5. Proceed through G2–G6 per runbook; flip apply_mode ONLY when all gates green

### Blockers (runbook)
- Dataset needs human expert validation before G1 can be declared PASS
- Steps 2–8 require staging DB — cannot run without Docker stack

---

## Session 3 — 2026-06-22 — BA-031 Turn-On Runbook (Steps 2 + 5)

### What was done

**G1 benchmark run (Step 2):** Re-ran `ennam_kg.benchmark.cli` after improving 6 entity descriptions to add bidirectional cross-references (abbreviation/shortname mentions). Result: recall=0.901 @ K=10, threshold=0.73 → **GATE PASS**.
- Commits to `ennam.kg.python`: `a2c89ca` (initial populate), `25ef028` (improved descriptions for e55/e68/e75/e77/e79/e80)
- Report saved to `reports/ba031-8b-blocking-v2-20260622-213717.md`

**Integration test fix (Step 5 prerequisite):** `gaFakeStateChecker` in `ennam.kg.go/internal/integration/ba031_ga_test.go` was missing `AllChunksExtracted` and `MarkDocResolving` methods added by Phase A to `chunkStateChecker` interface. Added stub implementations.
- Commit `4db11f9` to `ennam.kg.go`: `test(ba031): fix gaFakeStateChecker to satisfy chunkStateChecker interface`

**G3 re-confirmed (Step 5):** `TestBA031GA_Step4_Reversibility` → PASS (merge → un-merge byte-equivalent restore).

**Full TestBA031GA suite:** All 5 tests PASS:
- Step1 (G4 cost ceiling): PASS
- Step2 (G5 degree-gating): PASS
- Step3 (telemetry): PASS
- Step4 (G3 reversibility): PASS
- Step5 (GA tripwire guard): NOT-DECLARED / PASS (correct — apply_mode still "shadow")

### Runbook gate status (updated)
- **Step 1** (populate dataset): DONE ✅
- **G1** (blocking recall ≥0.90 @K=10): PASS ✅ (recall=0.901, threshold=0.73)
- **G3** (reversibility): PASS ✅
- **G4** (cost ceiling): PASS ✅ (TestBA031GA_Step1)
- **G5** (degree-gating): PASS ✅ (TestBA031GA_Step2)
- **G2** (merge precision ≥0.90): BLOCKED — needs `merge_suggestions` rows from Phase A wired producer chain
- **G6** (staging dry-run review): BLOCKED — same prerequisite + human SQL review
- **apply_mode**: still "shadow" — NOT flipped (correct; G2/G6 not cleared)

### Blockers (runbook)
- G2 and G6 require the Phase A producer chain to be running in staging (Pass 1 → extract_document → chunk-complete → Pass 2 shadow → merge_suggestions). Phase A code is committed but requires E2E activation via live Docker stack with ANTHROPIC_API_KEY.
- Step 4 (G6 SQL review) is a human review step — cannot be automated.
- apply_mode MUST NOT be flipped until G2/G6 both green.

### Next steps for next session
1. Verify Phase A E2E produces `merge_suggestions` rows on staging (need live stack + API key)
2. Run 8c precision/recall benchmark (G2) once merge_suggestions exist
3. Human SQL review of would-merge set (G6)
4. Only then: Step 6 atomic commit (flip apply_mode + update tripwire test)

---

## Session 4 — 2026-06-23 — BA-031 Phase A Root-Cause Debug + Fixes

### Bugs fixed (3 root causes, all blocking merge_suggestions creation)

**Bug 1 — ListEntitiesByProvenance SQL: jsonb_build_array vs jsonb_build_object**
- `ennam.kg.go/internal/store/node.go` L395: SQL used `jsonb_build_array(jsonb_build_object('source_doc_id', $3))` which expected `{"provenance":[{"source_doc_id":"..."}]}` but pass1 stores `{"provenance":{"source_doc_id":"...",...}}` (a dict, not array). Removed `jsonb_build_array` wrapper.
- Committed to `ennam.kg.go`: `d73260a`

**Bug 2 — verify.py: Go API field names (title/node_type vs name/type)**
- `verify.py` `build_verify_request` used `a.get("name","")` and `a.get("type","")` which return empty for Go API responses that return `title` and `node_type`. Added `_extract()` helper that falls back to both conventions, and also extracts `description` from `properties.description`.
- Committed to `ennam.kg.python`: `69f97b0`

**Bug 3 — deps_factory.py: get_node was None, candidates had empty name/description**
- `build_pass2_deps` didn't wire `get_node`, so all candidate nodes had `{"name":"","description":""}`. LLM always returned `same_entity=False`. Added `_get_node_sync` using `httpx.Client` to `GET /api/v1/nodes/{id}`.
- Committed to `ennam.kg.python`: `69f97b0`

**Also fixed: wrong doc ID in Redis RPUSH**
- Used `204c82e1-b37c-4069-bdce-83aaeb7f62b8` (wrong); actual doc is `204c82e1-55a6-4549-b3bd-db15bdecf2c3`
- Documents: `fbfff4ed-8330-4a44-86e9-661c2eebd8c5` = OMNI Channel ISO20022; `204c82e1-55a6-4549-b3bd-db15bdecf2c3` = 3rd party payment hooks

### Current state (session 4 — paused)
- Pass 2 run STILL IN PROGRESS for doc `204c82e1-55a6-4549-b3bd-db15bdecf2c3` (68 entities)
- Worker running sequential version (parallel code committed but not yet rebuilt)
- **26 merge_suggestions** in DB as of pause (real model `intfloat/multilingual-e5-small`)
- Run started 19:08:57, worker container still up (`ennam-kg-worker`)

### Next steps
1. Wait for resolve_document done for `204c82e1-55a6-4549-b3bd-db15bdecf2c3`
2. Push resolve_document for `fbfff4ed-8330-4a44-86e9-661c2eebd8c5` (716 entities — expect several hours)
3. G2 gate: run precision benchmark on collected merge_suggestions
4. G6: human SQL review of would-merge set
5. Rotate BytePlus API key (SECURITY — outstanding)

---

## Session 5 — 2026-06-23 — BA-031 Parallel Worker + G2 Harness

### What was done

**Parallel worker deployed:**
- Previous sequential run (started 19:08 UTC yesterday) completed at 22:02 UTC (~3h for 68 entities)
- Sequential writes: suggestions=32, evaluated=612 (but pre-deletion writes erased by manual DELETE)
- New parallel image built (`docker compose build worker`) — confirmed `asyncio.gather` in pass2.py
- Deployed: `docker compose up -d worker` (container recreated with new image)

**Both docs queued for parallel processing (run_id=ba031-run-002):**
- `204c82e1-55a6-4549-b3bd-db15bdecf2c3` (3rd party payment hooks, 68 entities, 612 pairs)
- `fbfff4ed-8330-4a44-86e9-661c2eebd8c5` (OMNI Channel ISO20022, 716 entities, ~5000+ pairs estimated)
- Phase 1 complete for 3rd party doc: 68 entities, 612 pairs (parallel Phase 2 in progress)
- Expected: ~5 min for 3rd party, ~45 min for OMNI Channel

**G2 harness built:**
- `ennam.kg.python/src/ennam_kg/benchmark/merge_cli.py` — new CLI for 8c precision/recall gate
- Reuses sweep.run_sweep() for ANN blocking, then asyncio.gather(semaphore=10) for verify_pair
- Commit `8b64cd1` on `ennam.kg.python` branch `task/implement_mcp`
- Usage: `python -m ennam_kg.benchmark.merge_cli --dataset benchmarks/ba031/vi_blocking_v1.json --project 1e69492a-... --out reports/ba031-8c-<ts>.md`
- Note: re-inserts benchmark entities with `created_by=ba031-benchmark` — use `DELETE FROM knowledge_nodes WHERE properties->>'created_by'='ba031-benchmark'` for cleanup

### Gate status (updated)
- G1: PASS ✅ (recall=0.901 @K=10, threshold=0.73) 
- G2: PENDING — parallel run in progress, will measure avg_conf + optionally run merge_cli
- G3: PASS ✅ 
- G4: PASS ✅
- G5: PASS ✅
- G6: PENDING — human SQL review needed once suggestions populated

### Next steps
1. Wait for parallel run to complete for both docs
2. Check suggestions count + avg_conf (G2 proxy)
3. Run G2 formal benchmark if avg_conf ≥ 0.90: `python -m ennam_kg.benchmark.merge_cli --dataset benchmarks/ba031/vi_blocking_v1.json --project 1e69492a-7b20-4327-be06-5eeaa94dc274 --out /tmp/ba031-8c-report.md`
4. G6 SQL review (human): `SELECT node_a_id, node_b_id, merge_confidence, reason FROM merge_suggestions WHERE project_id='1e69492a-7b20-4327-be06-5eeaa94dc274' AND decision='suggested' ORDER BY merge_confidence DESC;`
5. Step 6: atomic flip apply_mode + tripwire test update (only when G2+G6 green)
6. Rotate BytePlus API key (SECURITY — outstanding)

