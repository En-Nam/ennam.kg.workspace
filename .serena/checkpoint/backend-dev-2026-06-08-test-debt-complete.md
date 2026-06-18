# Checkpoint: backend-dev — 2026-06-08 (branch test-debt cleanup complete)

## Result
`go test -race -count=1 ./...` is **ALL GREEN** on `task/sines-enhancement` (was: many
packages failing/panicking/non-compiling). `go build ./...` clean, `go vet ./...` clean.

## Scope journey
Started from "16 service failures", which — once fixed — unmasked a branch-wide pattern
(packages that never compiled/ran, hiding panics + stale tests). Fixed iteratively with
systematic-debugging (root-cause each before fixing; fix tests when stale, fix production
when a real bug).

## Fixed (by package)
- **service (16)** — earlier commits: required-with-default validation order (prod), Gate2
  completeness test, SSL-mode test, naming-convention y→ies (prod).
- **store** — `c276b11` nil-DB guards across ~15 store files (45 `_NilDB` tests, via
  subagent); `72c1b1e` test-pkg compile errors (json import, dup `containsStr`/
  `TestIsUniqueViolation`, missing `setupTestDB`); 9 logic/test mismatches: limit-clamp test
  inputs (caps don't inflate), node_type optional at store, audit "project" now valid,
  `prepareSearchQuery` keeps capitalized Vietnamese proper nouns (PROD fix), neighbor
  cross-project tests set Direction:"both".
- **middleware** — `d788fe6` ExtractProjectID URL-encode whitespace (test built a malformed
  request); Metrics_RecordsLatency flaky (sleep 1ms; latency is µs-quantized).
- **models** — audit `IsValid` "project" is valid (AuditEntityProject); use a real-invalid type.
- **handler** — EdgeWhitelist used now-valid "document" → use unknown type; History/Neighbor/
  RegisterAll/Query/Traverse nil-store invocations wrapped with existing `recoveringHandler`
  (codebase pattern); created_by + node_type are intentionally optional/defaulted (stale
  required-tests updated); ConceptEndpoint: a required-empty field no longer also emits a
  redundant MinLength error, so the remaining error names the node type ("…for Concept nodes");
  sync_portal: `/stream/sync/progress` is registered separately (outer mux), not by
  RegisterRoutes.
- **jobengine** — `TestHeartbeatMonitor_StartStop` data race (callCount) → `atomic.Int32`.

## Production code changed (not just tests) — all behavior-preserving in prod
- `internal/service/node.go` — required-field-with-default passes Gate1; dedup empty-required
  vs MinLength error.
- `internal/store/*.go` — nil-DB guards (inert in prod; stores always get a real DB).
- `internal/store/search_query.go` — preserve capitalized tokens in query preprocessing.
- `internal/store/kg_generation.go` (gofmt), `internal/handler/datasource.go` (earlier: recover
  in background goroutine).

## Known pre-existing, OUT OF SCOPE (not touched)
- **Repo-wide gofmt debt**: `gofmt -l internal/ cmd/` flags ~60 files — confirmed present at
  e19df16 (predates this work), spans files not edited here. `go vet` is clean. Would only
  affect `make lint` (golangci-lint gofmt check), not `go test`. Recommend a separate
  `gofmt -w ./...` formatting-only commit if lint-green is required.

## Verification
- `go build ./...` ✅  · `go vet ./...` ✅  · `go test -race -count=1 ./...` ✅ ALL GREEN

## Blockers / Risks
- None for tests. Only the pre-existing repo-wide gofmt debt remains (separate concern).
