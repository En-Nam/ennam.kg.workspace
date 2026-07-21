# Checkpoint: subagent-driven (B2 review fixes) — 2026-07-14

## What was done
- Fixed Task 1 review Finding 1 (Important): `is_found` in `b2_figure_metrics.py`
  previously stripped all whitespace across the whole OCR page before
  containment check, risking cross-line false positives. Now normalizes and
  checks containment per-line (`ocr_text.split("\n")`), keeping `_unaccent_lower`
  unchanged for accent/case + within-line whitespace stripping.
- Fixed Task 1 review Finding 2 (Important): `docs/superpowers/plans/b2-golden-set.md`
  `Số 09` exclusion note rewritten as an explicit controller-ratified decision
  (was citing Task 3's fix-scope note to justify a measurement-scope omission —
  reviewer flagged as silent unilateral scope-narrowing). Exclusion itself stands;
  no new source page was sought (per controller instruction).
- Addressed Finding 3 (Minor, trivial): added `used_text_layer: bool` to
  `run_item`'s result dict + a `[TEXT-LAYER, NOT OCR]` print flag in `main()`,
  so a future born-digital golden-set item won't silently skip OCR.

## Files changed
- `ennam.kg.python/scripts/b2_figure_metrics.py` (is_found per-line scoping,
  used_text_layer field/flag) — commit `15d06ce` in ennam.kg.python nested repo.
- `docs/superpowers/plans/b2-golden-set.md` (Số 09 exclusion rationale) —
  commit `8e90d35` in workspace-root repo.

## Current state
- Re-ran `uv run python scripts/b2_figure_metrics.py`: all 5 golden-set
  FOUND/MISS verdicts and CER values are byte-identical to the recorded
  BEFORE baseline in the doc (2 FOUND: #1, #4; 3 MISS: #2, #3, #5). Fix
  confirmed to close a latent risk without altering current real results.
- No existing unit tests for `b2_figure_metrics.py` found; none added
  (harness's own golden-set run is the verification per the Task 1 brief).

## Next steps
- None outstanding from this review round. Tasks 2/3 (preprocessing,
  RapidOCR) will re-run this harness for the AFTER baseline — the per-line
  `is_found` fix specifically de-risks that re-run.

## Blockers / Risks
- None.
