# Checkpoint: backend-dev — 2026-06-18 (BA-031 Phase 8d Task 2)

## What was done
- Implemented pre-batch cost ceiling estimator + enforcement (BA-031 Phase 8d Task 2)
- TDD: wrote 8 unit tests RED first, then implemented to GREEN
- Created `internal/ai/cost_ceiling.go`: CostEstimate, EstimateExtractionCost,
  ErrCostCeilingExceeded, EnforceCeiling, AvgChunkTokensDefault (exported)
- Created `internal/ai/cost_ceiling_test.go`: 8 tests covering formula, gleaning,
  zero chunks, disabled ceiling (<= 0), per-run / per-doc ceiling, nil provider
- Added `CostConfig` to `internal/config/types.go` and `config/config.yaml`
  (per_run_ceiling_usd: 5.0, per_doc_ceiling_usd: 1.0)
- Updated `internal/handler/extraction.go`: added providerReader interface + costCfg
  field, updated constructors, wired EnforceCeiling gate before dispatch loop
- Created `internal/handler/extraction_test.go`: 3 tests including primary safety
  test asserting zero dispatch on ceiling refusal (422 response)
- Updated `cmd/kg-server/main.go` line 602 to pass aiProviderStore + appCfg.Cost
- Committed: `feat(ba031-8d): pre-batch cost ceiling estimator + enforcement`

## Files changed
- `internal/ai/cost_ceiling.go` (new)
- `internal/ai/cost_ceiling_test.go` (new)
- `internal/handler/extraction_test.go` (new)
- `internal/handler/extraction.go` (modified — constructors + gate)
- `internal/config/types.go` (modified — CostConfig added)
- `config/config.yaml` (modified — cost: block appended)
- `cmd/kg-server/main.go` (modified — wiring at line 602)

## Current state
- All tests pass: `go test ./internal/ai/... ./internal/handler/... ./internal/config/... -race`
- Build clean: `go build ./... && go vet ./...`
- Commit: 497489b on branch task/implement_mcp

## Next steps
- Task 6: wire gleaningRounds and avgChunkTokens from config (currently hardcoded 0 / 500)
- Task 6: add KG_COST_PER_RUN_CEILING_USD / KG_COST_PER_DOC_CEILING_USD env overrides
  in ServerConfig.applyEnvOverrides() if per-environment override is needed
- Consider caching the provider lookup result to reduce DB calls under high throughput

## Blockers / Risks
- None. Implementation is clean, independent of BA-009.
- `cmd/kg-server/` is in .gitignore but `cmd/kg-server/main.go` staged and committed
  correctly (gitignore warning was about adding the directory path, not the file).
