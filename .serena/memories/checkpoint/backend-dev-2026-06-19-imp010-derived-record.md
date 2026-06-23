# Checkpoint: backend-dev — 2026-06-19 (IMP-010)

## What was done
- Registered `derived_record` node type across all 5 KG gates
- TDD: wrote failing test first, confirmed RED, then implemented, confirmed GREEN
- `go build ./...` clean, all tests pass

## Files changed
- `db/migrations/000067_add_derived_record.up.sql` — CHECK constraint + idempotency index
- `db/migrations/000067_add_derived_record.down.sql` — reversal
- `config/config.yaml` — `node_types.derived_record` + `search.derived_record` blocks
- `internal/config/types.go` — `NodeTypeDerivedRecord` const + `ValidNodeTypes` entry
- `internal/handler/neighbors.go` — `"derived_record": true` in `validNodeTypes` map
- `internal/filter/validate_test.go` — `TestNewValidationContext_DerivedRecord_HasSearchConfig` regression test

## Current state
- All code gates wired and verified (build clean, tests green)
- Migration 000067 created and staged; NOT yet applied to DB (Step 9 deferred to controller)
- Committed: `4981f07 feat(kg): register derived_record node type (all gates + idempotency index)`

## Next steps
- Controller to run `make db-migrate` + live `/query` smoke (Step 9)
- Follow-on tasks (Task 2+) in IMP-010 as directed

## Blockers / Risks
- None. Step 9 smoke requires Docker deps up — controller owns that.

---

## Session 2 (Task 5: Bridge tool `kg_upsert_derived_record`)

## What was done
- TDD RED: bumped schema count 40→41 + added `TestSchema_HasUpsertDerivedRecord` — confirmed FAIL
- Added `kg_upsert_derived_record` route in `client.go` (POST, RouteWrite, `{projectId}` path param)
- Added schema in `schema.go` (4 required: title, subtype, source_system, record_ref; optional: summary, projectIDParam)
- Bumped 5 test files (brief specified 4; `TestRouteClassCounts` in client_test.go also needed updating — caught by full suite)
- Full bridge suite: `ok github.com/ennam/ennam-kg/internal/bridge` — all pass; `go build ./...` clean
- Committed: `b9d1a37 feat(bridge): add kg_upsert_derived_record routed write tool`

## Files changed (Task 5)
- `internal/bridge/client.go` — new route entry
- `internal/bridge/schema.go` — new schema
- `internal/bridge/schema_test.go` — count bump + presence test
- `internal/bridge/client_test.go` — ListToolNames 37→38; RouteClassCounts write 21→22 total 37→38
- `internal/bridge/handler_test.go` — ListTools count 40→41
- `internal/bridge/integration_test.go` — imp010Tools group added

## Next steps (Task 5 complete)
- Task 6 (full bridge suite) should just run; no additional changes needed from this task
