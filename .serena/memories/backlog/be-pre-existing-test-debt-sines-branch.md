# Backlog: Pre-existing test debt on `task/sines-enhancement` (Go)

**Discovered:** 2026-06-08 during LAAM Markdown Memory implementation.
**Owner:** Go backend (branch `task/sines-enhancement`).
**Not LAAM:** these failures are unrelated to LAAM memory work — surfaced as a side effect.

## Why it was hidden
At commit `e19df16` the `internal/service` and `internal/handler` **test packages did not compile**
(e.g. `apikey_test.go` mismatched types, duplicate `testDecisionConfig`, `mockAPIKeyRepo` missing `Delete`).
The LAAM session fixed the compile errors so the new tests could run. Once the packages compiled,
two goroutine panics (`oauth_refresh.go`, `datasource.go`) crashed the test binaries early and masked
everything behind them. Fixing those panics revealed the real backlog below.

## Already fixed (had standalone value — committed on this branch)
- `oauth_refresh_test.go`: lifecycle tests ticked a 10ms timer into `checkAndRefresh` with a nil token
  store → goroutine panic. Switched to a long interval (verifies Start/Stop + ctx-cancel only). `cde693c`
- `datasource.go`: background `ExtractSchema` goroutine had **no panic recovery** → a panic there would
  crash the whole server process. Added recover→job-error. Real production hardening. `efd90a9`

## Remaining — NOT fixed (deliberately out of LAAM scope; needs per-feature judgment)

### `internal/service` — 16 failures (stale tests vs evolved validation/config)
These are **logic mismatches**, not panics. Files were NOT touched by LAAM work (decision_test.go,
task_test.go, datasource_test.go are original). Root cause looks like Gate1/validation evolved past the
test fixtures (e.g. `status: status is required for Decision nodes`).
- `TestNodeService_StoreDecision_*` (7): DefaultStatus, VersionIsOne, WithAlternatives, WithSessionID,
  RepoError, AppendOnlyVersioning, ScopeNormalization
- `TestNodeService_StoreTask_*` (6): DefaultStatus, VersionIsOne, WithSessionID, RepoError,
  NodeTypeAlwaysTask, OptionalFieldsOmitted
- `TestStoreNode_CrossProjectEdge_AllowedByConfigAndAccess`
- `TestDataSourceService_ValidateRegister_InvalidSSLMode`
- `TestMatchNamingConvention_SingularID`
> Likely a shared root cause in `testDecisionConfig`/`testTaskConfig` not setting a default-status rule.
> Fix once at the helper level and re-check — but confirm INTENDED behavior first (do decisions/tasks
> require an explicit status now, or should they default?). Do NOT blindly edit tests to pass.

### `internal/handler` — nil-store synchronous panics in tests (test-debt, NOT production bugs)
Tests construct handlers with `nil` stores/DB and call them directly, expecting a graceful 500, but the
store derefs the nil DB and panics. (LAAM's own search tests had this and were fixed with a recovery
HTTP-server wrapper — same pattern applies.) Confirmed so far:
- `history.go:103` (`h.store.GetFullHistory` on nil store) via `history_test.go:114`
- (more likely behind it — each panic masks the next; enumerate by running `go test ./internal/handler/`
  repeatedly and wrapping each offending test, or give handlers a shared test recovery helper)

## RESOLVED 2026-06-08 — `internal/service` package now fully green (`-race`)

The 16 service failures were fixed (4 commits on `task/sines-enhancement`). Root causes were
NOT a single shared helper — they were four distinct issues, two production bugs + two stale tests:

- **A (13 tests, PRODUCTION bug)** `a4b9210` — `validateStoreRequest` checked `schema.Required`
  BEFORE `StoreNode` applied config defaults, so omitting a required-with-default field (decision/task
  `status`, default `accepted`) failed with "X is required". The REST/MCP contract treats such fields
  as optional. Fix: required-check now skips a missing field when its schema defines a non-nil Default.
- **B (1, STALE test)** `616bc24` — CrossProjectEdge test built a concept with empty properties; Gate 2
  falls back to `DefaultEntityCompletenessRules()` when no profile is configured, requiring
  name/definition/domain. Added those fields so the test isolates cross-project edge authorization.
- **C (1, STALE test)** `616bc24` — `InvalidSSLMode` used `"disable"`, which is a VALID pg mode
  (in `pgSSLModes`). Changed to `"bogus-mode"`.
- **D (1, PRODUCTION gap)** `bbd83f8` — `matchNamingConvention` lacked consonant+y→ies plural
  (`category_id`→`categories`). Added the y→ies case to `findTable`.

Verified: `go test ./internal/service/ -race` PASS; reverting node.go reproduces all 13 → confirms the
fix; the Gate1 *handler* failures below reproduce with node.go reverted → NOT caused by this work.

## STILL OPEN — branch-wide debt beyond the 16 (surfaced once service compiled, 2026-06-08)
Running the FULL suite (`go test ./...`) now reaches packages previously masked:
- **`internal/store` — BUILD FAILED** (test pkg won't compile): `search_test.go` missing `json` import;
  `containsStr` redeclared (edge_test.go:96 vs search_test.go:352); `TestIsUniqueViolation` redeclared
  (apikey_test.go:22 vs session_test.go:256). Mechanical compile fixes.
- **`internal/handler` — 5 failures** (pre-existing, NOT from this work — verified): `TestGate1_EdgeWhitelist_UnknownSourceType`,
  `TestGate1_EdgeWhitelist_UnknownTargetType`, `TestGate1_ConceptEndpoint_MissingDefinition_ActionableError`
  (expects error to mention "Concept", gets a MinLength message — message-format debt),
  `TestExtractSchemaMissingCreatedBy`, `TestHistoryHandler_RegisterRoutes` (nil-store panic pattern).
- **`internal/middleware` — 2**: `TestMetrics_RecordsLatency`, `TestExtractProjectID`.
- **`internal/models` — 1**: `TestAuditEntityType_IsValid`.

These are a SEPARATE cleanup (different packages, different root causes). Not started — awaiting go-ahead.

## LAAM status (for contrast)
LAAM feature code is complete and verified via **targeted** tests (embed, bridge, service ingest,
handler search/embedding) — all green with `-race`. `go build ./...` passes.
