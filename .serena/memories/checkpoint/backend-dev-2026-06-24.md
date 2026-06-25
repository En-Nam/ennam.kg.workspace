# Checkpoint: backend-dev — 2026-06-24

## What was done

### BA-033 Slice 1 (from prior session)
- Implemented cross-document GraphRAG retrieval (11 commits, all tests pass)
- Bridge invariant: 42 schemas = 39 routed + 3 local

### Graph unblock (this session)
- **Track B — extraction prompts fixed** (commit `dac6982`, pushed):
  - Fixed `_extraction_prompt` with multi-type examples + comprehensive relation instruction
  - Fixed `_gleaning_prompt` to request relations via `source_name`/`target_name` (canonical names, avoids temp_id collision)
  - Added `canonical_name_to_node_id` reverse map in Step 5 for gleaning edge resolution (Step 6b)
  - Added test `test_run_pass1_gleaning_relations_persisted` — passes
  - Fixed pre-existing FakeKG.create_node return shape (`{"node": node}`)

- **Track A — resolution gates run & cleanup**:
  - G1 gate (8b blocking-recall): `recall=0.901 @ K=10` ✅ (threshold 0.90)
  - G2 gate (8c merge precision): `precision=1.000, recall=0.915` ✅ (thresholds 0.90/0.80)
  - `apply_mode` was already set to `apply` on 2026-06-23 with 34 merges applied
  - 65 stale suggestions in `ba031-pdf-test-verifone` bulk-rejected via DB (all superseded or self-merge cascades)
  - LAAM project (`6f5f1680-6b7e-4c93-bcf7-be3e78b4bb3d`): 425 nodes, 129 edges (up from 303/117)

## Files changed
- `ennam.kg.python/src/ennam_kg/extraction/pass1.py` — gleaning prompt + relations pipeline
- `ennam.kg.python/tests/extraction/test_pass1.py` — new gleaning test + FakeKG fix
- `.serena/memories/checkpoint/backend-dev-2026-06-24.md` — written manually (Serena unavailable earlier)

## Current state
- Branch: `task/implement_mcp`
- All Pass 1 tests passing (5/5 relevant; 1 pre-existing parser test failure unrelated)
- Docker stack running: Go API on `localhost:8082`, indexer on `localhost:8081`
- API URL note: dev env uses port **8082** (container maps 8082→8080)

## Next steps
- Fix pre-existing `TestApplyHandler_ConfigDefaultLoading` in `ennam.kg.go` (BA-031 issue)
- Run re-extraction on Cảng Định An docs with improved prompts to validate edge density improvement
- Plan 2 (community detection) now unblocked — can proceed when graph is dense enough

## Blockers / Risks
- `TestApplyHandler_ConfigDefaultLoading` is a pre-existing test failure — separate from graph unblock work
- Serena MCP was unavailable in earlier session context; checkpoint written manually then via Serena now
