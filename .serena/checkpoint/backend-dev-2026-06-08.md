# Checkpoint: backend-dev — 2026-06-08

## What was done
Cleaned up the 16 pre-existing `internal/service` test failures on `task/sines-enhancement`
(ennam.kg.go). Used systematic-debugging: root-caused each group before fixing. Four distinct
root causes — two production bugs, two stale tests.

- **Group A (13 tests, PRODUCTION)** `a4b9210` — `validateStoreRequest` ran the `schema.Required`
  check before `StoreNode` applied config defaults, so omitting a required-with-default field
  (decision/task `status`, default `accepted`) failed wrongly. Fix: skip the required error when the
  field's schema defines a non-nil `Default` (value applied downstream before persistence).
- **Group B (1, STALE test)** `616bc24` — CrossProjectEdge test concept had empty properties; Gate 2
  falls back to `DefaultEntityCompletenessRules()` (no profile in test cfg) requiring name/definition/
  domain. Added those fields to isolate the test's real intent.
- **Group C (1, STALE test)** `616bc24` — `InvalidSSLMode` used `"disable"` which is VALID; changed to
  `"bogus-mode"`.
- **Group D (1, PRODUCTION gap)** `bbd83f8` — `matchNamingConvention` lacked consonant+y→ies plural;
  added the case (category_id → categories).

## Files changed
- `internal/service/node.go` (Group A, production)
- `internal/service/kg_implicit.go` (Group D, production)
- `internal/service/cross_project_test.go` (Group B, test)
- `internal/service/datasource_test.go` (Group C, test)
- `.serena/memories/backlog/be-pre-existing-test-debt-sines-branch.md` (updated: resolved + remaining)

## Current state
- `internal/service`: **fully green with `-race`** (was 16 failing).
- Regression check: reverting node.go reproduces the 13 → fix confirmed; the Gate1 *handler* failures
  reproduce with node.go reverted → NOT caused by this work.
- `go build ./...` passes.

## Next steps (branch-wide debt beyond the 16 — surfaced once service compiled; NOT started)
- `internal/store`: **build failed** (test pkg) — missing `json` import in search_test.go; `containsStr`
  + `TestIsUniqueViolation` redeclared. Mechanical compile fixes.
- `internal/handler`: 5 failures (Gate1 EdgeWhitelist x2, ConceptEndpoint message-format,
  ExtractSchemaMissingCreatedBy, HistoryHandler_RegisterRoutes).
- `internal/middleware`: 2 (Metrics_RecordsLatency, ExtractProjectID).
- `internal/models`: 1 (AuditEntityType_IsValid).
- Goal if continued: `make test` / `go test ./...` fully green.

## Blockers / Risks
- None for the 16. Remaining items are a separate cleanup awaiting go-ahead (different packages/root causes).
