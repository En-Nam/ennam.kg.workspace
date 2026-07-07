# Checkpoint: danger-stratum R5 OCR cleanup — 2026-07-03

## What was done
- BA-033 slice 2: re-measured Gate A → GREEN (see `mem:backlog/ba033-slice2-readiness-path`); ran a one-off community report (falsifiability probe) = PASS (~12/15 coherent themes: provincial govt, Định An port, corporate governance, ministries, logistics). Debate concluded DEFER the slice build (consumer=admin dashboard is speculative; report delivers the value reversibly). Gate B (consumer) still open.
- Report surfaced residual OCR-duplicate entities → chose to clean L3 instead of productizing.
- **Built R5 OCR rule classes** (danger_rules.py, committed+pushed ennam.kg.python 34b8ece):
  - R5a = de-diacritic space-removed equality (missing-space/OCR-concat), construction-safe.
  - R5b = Levenshtein≤2 on de-diac base + length floor 15 (blocks short false-merge) + guards + Wilson≥0.97 (WILSON_GATED={R4,R5b}).
  - 21/21 danger tests pass, ruff clean.
- **Drained R5** on project 592c7ff7…: R5a 44 (inspected all = 100% same-entity) + R5b 279 (labeled evidence, Wilson lcb=0.986) + R1 straggler 1 → 324 flipped → applied 323, 1 hub deferred (via existing ApplyReviewClearedMerges; temp KG_AUTH_NOOP toggle, restored).

## Current state (verified)
- decision breakdown 592c: applied=7860, needs_review=2521 (danger stratum: was 3148 → 627 auto-drained by R1-R5, rest genuine human review).
- Auth restored KG_AUTH_NOOP=false (401 no-header). review_cleared=0.
- Community report re-run: modularity 0.843, 56 non-trivial communities (themes intact/sharper).
- All reversible via merge_undo.

## Next steps
- Remaining ~2520 needs_review = genuine human review (danger_review_cli) OR accept as-is. Diminishing returns on further rules.
- BA-033 slice 2: revisit only if the community report generates repeated demand (Gate B). Build path in `mem:backlog/ba033-slice2-readiness-path`.
- Unblocked keystone alternative: LAAM monitoring-scope for kg_search_sessions.
- Branch task/implement_docs_sync NOT merged to main (per user).

## Blockers / Risks
- None. R5b (fuzzy) is the riskiest class but triple-gated (length floor + guards + Wilson) + reversible.
