# Backlog: BA-031 Phase 8c — end-to-end merge precision/recall gate harness (Python)

**Status:** NOT built. Blocked on the VI dataset (PENDING-DATA), build together with it.

## Gap
`ennam_kg.benchmark.merge_eval` has the scoring functions (`evaluate_merge`,
`sweep_confidence` → `MergeScore{precision, recall, tp, fp, fn}`) but they consume
**pre-computed** `blocked_pairs` + per-pair `verdicts`. There is **no runner** that
produces those verdicts, so the 8c exit gate (precision ≥ 0.90 AND recall ≥ 0.80)
cannot actually be executed end-to-end. Today `merge_eval` is only exercised by
`tests/benchmark/test_merge_eval.py` with synthetic verdicts.

## What to build (when `benchmarks/ba031/vi_blocking_v1.json` is populated)
A CLI harness, modelled on `benchmark/cli.py` + `benchmark/sweep.py`:
1. load benchmark → embed + insert entities (reuse 8b `sweep` wiring / `KGClientWriter`)
2. block candidates via `/internal/resolution/candidates` (shared `HttpxRetriever`)
3. for each blocked pair run `resolution.verify.verify_pair` with the real AIClient model → build `verdicts`
4. `evaluate_merge` / `sweep_confidence` at the chosen `merge_confidence_threshold`
5. report + gate verdict (precision ≥ 0.90 / recall ≥ 0.80)

Needs live model + KG writer + candidates endpoint — only validatable once the
labelled dataset exists. Do NOT build against the empty skeleton.

## Why deferred (not done 2026-06-18)
Building a harness whose only real test is data that doesn't exist yet = YAGNI +
can't verify. The VI labelling is a human deliverable; the harness ships with it.
Runbook `docs/superpowers/runbooks/ba031-unmerge-drill.md` Step 3 documents this.
