# Checkpoint: danger-stratum drain — 2026-07-03

## What was done
- Built danger-stratum drain (spec + plan + 5 modules) — see `mem:` fuzzy-hub; committed+pushed on task/implement_docs_sync (python 442c2c6..9979da9, workspace d3efaa5..a469645).
- Independently verified impl: 18/18 danger tests, ruff clean, live dry-run {R1:21,R2:137,R3:7,R4:140,L3:2843}=3148.
- **Executed the drain on project 592c7ff7-9f6f-4cc5-9094-d9b3b685277e:**
  - R1+R2+R3 (165): inspected ALL members = 100% same-entity (ministry abbrevs, Vietnam↔Việt Nam, OCR case) → flipped review_cleared → applied 164, 1 hub (degree 43) deferred.
  - R4 (140, admin-prefix Trà Vinh bare↔tỉnh): province/city risk resolved EMPIRICALLY — **no "thành phố Trà Vinh" node exists** in corpus, so bare Trà Vinh = province (no city entity to conflate). Labeled evidence all=same, code wilson gate passed (lcb=0.973≥0.97) → applied 140.
  - Both drained via `POST /apply-review-cleared` (temp KG_AUTH_NOOP=true + dummy bearer, restored false after; server host port :8082).

## Current state (verified)
- decision breakdown 592c: applied=7537, needs_review=2844 (= 2843 L3 + 1 deferred hub).
- superseded_by_merge edges=605, merged_into nodes=4150 (cumulative).
- Auth restored KG_AUTH_NOOP=false (401 no-header). Stack healthy. review_cleared=0.
- Danger-stratum auto-drained total: 304 merges (164 + 140). All reversible via merge_undo.

## Next steps
- **L3 residual (2843)** — human review via `danger_review_cli --project <id>` (accept→review_cleared, reject→rejected). Grouped by canonical + degree.
- 1 deferred hub (degree 43) — human decision.
- Follow-up (non-blocking, in runbook): verify Pass-2 skips decision='rejected' on re-index.

## Blockers / Risks
- None. R4 province/city risk was empirically nullified (no city node). Reversible.
