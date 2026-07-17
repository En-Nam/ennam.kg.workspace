# Checkpoint: harness-findings-fixes — 2026-07-16

**Plan:** `docs/superpowers/plans/2026-07-16-harness-findings-fixes.md`. Executed via superpowers:subagent-driven-development (fresh implementer + task reviewer per task, fix rounds on findings, 2 independent whole-branch review passes).

## What was done
- **Task 1** (`ennam.kg.python`): `extract.py` (`extract_draft`) now retries once then raises `ExtractionParseError` (not silently returns empty) on unparseable extraction JSON — root cause of `BCTC KIEM TOAN 2023`'s silent entity loss. Also raises on valid-but-non-dict JSON (self-flagged extension, later given its own test per review finding). Commits `33c5154`, `36525bc` (test fix).
- **Task 2** (`ennam.kg.go`): `graph_retrieve.go` — `DisallowUnknownFields()` on the request decoder → 400 naming the offending field + valid field list. Closes the exact gap that produced a **false** "kg_graph_retrieve is broken" bug report (analyst used a nonexistent `limit` param). Commit `86640ca`.
- **Task 3** (`ennam.kg.python`): `decompose.py`'s `_LEGAL_FORMS` extended with 4 place/authority abbreviation entries (khu che xuat→kcx, khu cong nghiep→kcn, thanh pho ho chi minh→tphcm, tp hcm→tphcm), measured against real `fold_name` output, ordering longer-before-shorter. Commit `73db0c3`.
- **Whole-branch review:** 2 independent Opus passes, both converged **Ready to merge: Yes**, 0 Critical/Important. Verified from source: Task 1's raise is caught per-document in `engine.py` (does not crash the batch); Task 2 touches only the decode path, no callers outside kg-bridge's schema (which only sends valid fields) exist; Task 3 converges correctly with no substring-collision risk.
- **Task 4 (operational, live-measured):** Docker images (`worker`, `kg-server`) rebuilt with all 3 fixes. Old Dasin project (`c47988fa-cb77-4367-94dc-36158956082b`) deleted (FK-safe SQL transaction — 678 edges/219 nodes/9 docs/184 embeddings/etc, confirmed 0 remaining) at user's request. User re-created + re-synced via dashboard → new project `Dasin` id **`6115fa4b-d6d4-46d6-9617-2cae644d8a0f`**. Measured:
  - Worker log: `processed=9 failed=0`, zero ERROR/Traceback.
  - FR-001 linker: `edges_upserted: 607` on 147 chunks.
  - **BCTC KIEM TOAN 2023: 0→3 concept edges** (was the orphaned document; now every doc has ≥1).
  - **Place/authority collapse confirmed**: Tân Thuận EPZ, Phú An Thạnh IP, HEPZA authority each now exactly 1 node (were 2+). Total concepts 26→22.
  - **graph_retrieve contract confirmed live**: `limit:60` → 400 (names field + valid list); valid request → 200, `hop_count [0,1]`, 6/6 snippets, 3 distinct docs.

## Files changed
- `ennam.kg.python`: `src/ennam_kg/ingestion/pipeline/extract.py`, `tests/ingestion/test_extract_failure.py` (new), `src/ennam_kg/ingestion/pipeline/decompose.py`, `tests/ingestion/test_decompose_concepts.py`.
- `ennam.kg.go`: `internal/handler/graph_retrieve.go`, `internal/handler/graph_retrieve_test.go`.
- Ledger: `.superpowers/sdd/progress-harness-findings-fixes.md` (workspace root, git-ignored scratch — full task-by-task + review detail).

## Current state
- All 3 code tasks committed on `task/implement_docs_sync` in their respective nested repos (`ennam.kg.python`, `ennam.kg.go`), not yet merged/PR'd to those repos' `main`.
- All Task 4 measurements pass with clear margin. Corrected `mem:checkpoint/daab-mcp-harness-dasin-2026-07-16`'s finding #1 was already retracted in an earlier pass this session (verified still correct, no further edit needed). Updated `mem:backlog/ba033-slice2-readiness-path` with today's verdict.
- **Not done:** plan's Task 4 Step 7 — a full harness re-run (`other_projects/daab-sim-consumer/questions-dasin.md` against the new project, correct parameter names) producing `findings-dasin-run2.md` and a formal FR-001 verdict at Dasin scale. This is a separate, larger analyst-simulation exercise, not part of the core fix-verification loop.

## UPDATE — harness re-run completed, PLUS a real bridge regression found + fixed live

Re-ran the sim-consumer harness twice more after the checkpoint above:

- **Run 2** (`findings-dasin-run2.md`, correct parameters this time): surfaced a NEW real bug — `kg_graph_retrieve` failed 100% of calls through the MCP bridge with "Validation error... check required fields", even the tool's own minimal valid call. Root cause: `ennam.kg.go/internal/bridge/serve.go`'s `makeToolHandler` unconditionally injected BOTH `project_id` and `projectId` into every default-project tool call, regardless of which key the tool's route actually consumes. Harmless until Task 2's `DisallowUnknownFields()` fix (this same plan) started rejecting the unrequested `projectId` key on every `kg_graph_retrieve` call. **Invisible to both whole-branch reviews of the original Task 2 commit** because they checked the bridge's *declared* schema (`schema.go`), not its *runtime request-building* logic (`serve.go`) — lesson for future caller-impact reviews: check what a client actually sends at runtime, not just what its schema declares.
- **Fix:** `ennam.kg.go` commit `467fd91` — new `defaultProjectKey(toolName)` helper fills only the ONE key a tool's registered route actually uses. TDD (4 new tests, including an httptest-backed integration test proving the pre-fix code would have failed it), independently reviewed (Opus): **Approved, 0 Critical/Important** — reviewer verified against the full `toolRoutes` table that no handler anywhere expects `projectId` in a JSON body, so no tool is starved by this change. `kg-bridge` rebuilt, live-reverified.
- **Run 3** (`findings-dasin-run3.md`, bridge now fixed): **33/42 (2.36 avg)**, one point above runs 1 and 2 (32/42 each), entirely from Q8 (revenue-trend) moving 2→3. **`kg_graph_retrieve` CONFIRMED genuinely working end-to-end** — 5/5 calls succeeded including the exact minimal call that failed 100% in run 2, real `hop_count:1` cross-document expansions in 3/5 calls. This is the first of 3 total runs where FR-001 was actually testable (run 1: analyst parameter misuse; run 2: bridge bug; run 3: clean). **New honest finding for the backlog:** even with retrieval genuinely working, most Tier-3/4 gaps (Q9 equity delta, Q11 contradictions, Q12/13 synthesis) are NOT retrieval problems — they need a comparison/arithmetic/synthesis layer, which is a separate, larger question from anything in this plan's scope.

## Next steps
- Decide whether/when to merge `task/implement_docs_sync` → each repo's `main` (not requested this session).
- The comparison/arithmetic/synthesis-layer gap surfaced by run 3 (Q9/Q11/Q12/Q13) is a genuine new backlog item, separate from FR-001/FR-002/003/005 — worth its own brainstorm before committing to a build.

## Blockers / Risks
- None outstanding. Accepted risks from the plan (temp-0 retry has narrow value against deterministic LLM failures; `_LEGAL_FORMS` is a blunt string-rewrite map, kept intentionally small/corpus-driven) were re-confirmed by both whole-branch reviewers as acceptable, not defects.
