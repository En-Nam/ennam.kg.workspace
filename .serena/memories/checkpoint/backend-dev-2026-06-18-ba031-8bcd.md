# Checkpoint: backend-dev — 2026-06-18 (BA-031 Phase 8b+8c+8d)

## What was done
Implemented BA-031 phases 8b→8c→8d sequentially (subagent-driven, fresh implementer + reviewer per task, real-DB verification).
- **8b** (Python benchmark harness): dataset schema/loader, recall@K metric + T×K grid, sweep harness, report+gate, CLI + shared HttpxRetriever. Final review: READY TO MERGE.
- **8c** (resolution SHADOW): merge_suggestions sidecar (000064), lossless edge re-point, merge tx (chain/cycle/optimistic/stamping), byte-equivalent un-merge, merge/unmerge/suggestion endpoints, Pass2 verifier+resummarise+shadow orchestrator, merge precision/recall eval, un-merge drill. Final review: code correct, READY-with-CI-followup.
- **8d** (auto-merge GA, built but OFF): degree count, cost ceiling (refuse before LLM, 503 fail-closed), run_id telemetry + runs endpoint (000065) + 8a-fix (000066 UUID→TEXT), gleaning breaker, degree-gated apply (hubs never merged), apply endpoint (fail-closed apply_mode=shadow), GA integration gate + tripwire. Final review: READY TO MERGE.

## Files changed
- Go (ennam.kg.go) branch cab4533→b36f2a8: migrations 000064/065/066; internal/store/{merge_suggestion,edge_repoint,degree,run_cost}.go; internal/service/{merge,unmerge,apply_suggestions}.go; internal/handler/{merge,merge_suggestion,apply_suggestions,extraction}.go; internal/ai/cost_ceiling.go; internal/integration/{ba031_resolution,ba031_ga}_test.go; config.
- Python (ennam.kg.python) branch 397c852→e9b9210: src/ennam_kg/benchmark/{dataset,metrics,sweep,report,cli,merge_eval}.py; src/ennam_kg/resolution/{candidates_client,verify,resummarise,pass2}.py; extraction/gleaning.py breaker; ai_client run_id; benchmarks/ba031/ data.
- Test DB: dev DB (docker ennam-kg-postgres :5433) migrated to v66.

## Current state
- All engineering done; final whole-branch reviews passed for all 3 phases. Build+vet clean (Go), full suites green (Go real-DB tests via KG_TEST_DATABASE_URL; Python 477 passed/18 skipped).
- **auto-merge is OFF**: apply_mode="shadow" in config.yaml; GA NOT-DECLARED. Tripwire test (TestBA031GA_Step5_GADecisionGuard) fails loudly if apply_mode flipped.
- **DATA GATES PENDING (owner action)**: 8b blocking-recall + 8c precision/recall both need `ennam.kg.python/benchmarks/ba031/vi_blocking_v1.json` populated (≥30 gold groups/≥50 pairs, Vietnamese hard cases). Owner = TODO-ASSIGN.

## Next steps
- Owner populates vi_blocking_v1.json → run 8b CLI (blocking recall ≥0.90 @K=10 in [0.72,0.75]) and 8c Task 9 (precision ≥0.90 / recall ≥0.80).
- Flip-to-apply checklist (in `.git/sdd/progress.md`): populate data → wire gleamingRounds into cost estimate → shadow-run staging → reversibility on staging → flip config apply_mode:apply + update/remove tripwire in same commit → decide pass1 run_id backfill + merged attribution.
- Optional: wire a Postgres-backed CI job (-tags=integration + KG_TEST_DATABASE_URL) so the resolution byte-equivalence tests run in CI (currently gate-off per repo convention; all ran locally this session).

## Blockers / Risks
- Data gates are owner deliverables (not code). auto-merge cannot GA until both pass on real VI data.
- Pre-existing (not BA-031): test_queue.py unused-import ruff debt; TestFavoriteStore_*/TestShouldSkip fail under forced real-DB (stale created_by seed).
- pass1 extraction run_id not yet threaded (complete_json adapter lacks seam) → runs-endpoint cost half is zero for pass1 spend until that adapter lands.

## 8b DEEP RE-VERIFICATION (later same day)
Closed the DEFERRED 8b live-run: ran kg-server + real e5 model + CLI on sample.json end-to-end. Found & fixed 4 real runtime bugs in the benchmark CLI live path (model short-name; node payload missing created_by + per-type required fields; wrapped {node} response parsing; DB title>=5 vs short abbreviations). Commits 86d6e0d, c047127, d545783, 2799267. Live run #4: 8 nodes+8 embeddings via real endpoints, GATE PASS recall=1.0 @K=10 (synthetic — proves wiring, not real VI gate). 85 benchmark/resolution tests green, ruff clean. Dev DB cleaned, server stopped.
