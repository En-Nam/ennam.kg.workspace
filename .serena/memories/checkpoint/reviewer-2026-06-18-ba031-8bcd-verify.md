# Checkpoint: reviewer — 2026-06-18 (BA-031 8b/8c/8d verification + fixes)

## What was done
- Verified plans 8b/8c/8d against actual code via 3 parallel agents (incl. live-DB run for 8c).
- **8b PASS**: 31/31 benchmark tests; self-match correction, EXTRACTABLE_NODE_TYPES import, meets_gate band, HttpxRetriever under resolution/ all correct. vi_blocking_v1.json still skeleton = PENDING-DATA (by design).
- **8c PASS** (DB-verified): migration 000064, uuid_generate_v4, lossless edge re-point, mergeOpID stamping, byte-equivalent un-merge, optimistic lock+cycle guard, shadow no-mutation. Gate PENDING-DATA (no VI data).
- **8d PASS, auto-merge OFF confirmed**: config ships apply_mode=shadow, GA not declared, hubs→needs_review, cost ceiling enforced pre-dispatch with real stores.
- Fixed 2 MEDIUM findings (user-approved):
  1. **gleaningRounds hardcoded 0** in cost estimate → now wired from config `gleaning.max_rounds` (default 2, mirrors Python pass1 max_rounds). New test `TestTriggerExtract_CostCeilingIncludesGleaningRounds` (0 rounds→202, 2 rounds→422).
  2. **runbook** `ba031-unmerge-drill.md`: fixed gate table to real 8c thresholds (precision≥0.90 / recall≥0.80), rewrote "Clearing PENDING-DATA" (correct dataset path/shape, real 8b CLI `ennam_kg.benchmark.cli`, real 8c evaluator `ennam_kg.benchmark.merge_eval` — removed nonexistent `blocking_eval` module ref), migration req 000061→000064.

## Files changed
- ennam.kg.go/internal/config/types.go (GleaningConfig.MaxRounds)
- ennam.kg.go/config/config.yaml (gleaning.max_rounds: 2)
- ennam.kg.go/internal/handler/extraction.go (gleaningRounds field/param, resolveGleaningRounds, constant, estimate call)
- ennam.kg.go/internal/handler/extraction_test.go (call sites + new test)
- ennam.kg.go/internal/integration/ba031_ga_test.go (call sites)
- ennam.kg.go/cmd/kg-server/main.go (pass appCfg.Gleaning)
- docs/superpowers/runbooks/ba031-unmerge-drill.md

## Current state
- `go build ./...` OK; gofmt clean; handler/config/ai tests green; integration tag compiles.
- DB-gated + integration tests still SKIP without KG_TEST_DB_URL (env-dependent, unchanged).

## Next steps
- LOW (not done): add a standalone CLI to `benchmark/merge_eval.py` so the 8c gate has a runnable command (runbook currently points at the functions + test shape).
- lint not verified (golangci-lint absent locally).
- Human deliverable: populate vi_blocking_v1.json to clear the 8c/8b data gates.

## Blockers / Risks
- None for engineering. Auto-merge remains OFF until human runs 8c precision/recall gate to real PASS.
