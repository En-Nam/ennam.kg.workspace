# Checkpoint: backend-dev — 2026-06-18 (BA-031 Phase 8c Task 10)

## What was done
- Implemented `internal/integration/ba031_resolution_test.go` — HTTP-level un-merge drill
- Test `TestBA031_UnmergeDrillByteEquivalent` passes against real DB (localhost:5433)
- Created `docs/superpowers/runbooks/ba031-unmerge-drill.md` in workspace repo
- Committed both: go subrepo SHA `9c91dfe`, workspace SHA `a09dfa9`
- Wrote report to `.git/sdd/8c-task-10-report.md`

## Files changed
- NEW: `ennam.kg.go/internal/integration/ba031_resolution_test.go`
- NEW: `docs/superpowers/runbooks/ba031-unmerge-drill.md`

## Current state
- Un-merge drill (HTTP level): PASS
- Shadow no-mutation: covered by Task 8 (Python)
- Precision/recall: PENDING-DATA (vi_blocking_v1.json empty skeleton)
- Overall Phase 8c gate: PENDING-DATA

## Next steps
- Populate `vi_blocking_v1.json` with real blocking candidate pairs
- Re-run Task 9 precision/recall benchmark script
- If thresholds pass: update gate decision + commit Phase 8c complete

## Blockers / Risks
- Phase 8c overall PASS is blocked on vi_blocking_v1.json data population (not a code blocker)
