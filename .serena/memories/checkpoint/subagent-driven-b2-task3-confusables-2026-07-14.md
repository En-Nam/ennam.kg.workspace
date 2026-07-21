# Checkpoint: subagent (Task 3 executor) — 2026-07-14

## What was done
- Plan B2 Task 3 ("Fix RapidOCR fields language + unit tolerance", #4): implemented
  `_repair_confusables_near_units` (span-scoped digit/letter confusable repair
  I/l->1, §->5, O/o->0, `S` deliberately excluded) in
  `ennam.kg.python/src/ennam_kg/ingestion/ocr/rapidocr_fields.py`, wired into
  `extract_structured_fields` after `_normalize_ocr_text`.
- TDD: wrote `tests/ingestion/test_rapidocr_fields.py` first (2 tests from the
  plan's illustrative examples), confirmed RED (ImportError), implemented, GREEN.
  Full `ingestion/` suite: 89 passed, no regressions. Ruff-clean.
- Step 1 spike (~30 min): researched vi/latin PP-OCR rec ONNX model availability.
  Official RapidAI hub (huggingface.co/SWHL/RapidOCR) ships only ch/en models.
  An unofficial "latin" ONNX + dict mirror exists (monkt/paddleocr-onnx) but its
  dict.txt was fetched and verified to lack Vietnamese diacritics — not fit for
  purpose. **Decision: DEFER the model swap.** `_get_engine()` unchanged
  (still `RapidOCR()`, ch+en), documented via NOTE comment at the call site.
- Step 5 A/B: wrote a one-off scratch script (NOT checked in, NOT touching
  Task 1's `scripts/b2_figure_metrics.py`) reusing `GOLDEN_SET`/`render_page`/
  `_unaccent_lower`, scored the *fields* path (`extract_structured_fields(...)
  ["areas"]`) before/after the repair. Real finding: **no MISS->FOUND flip** —
  RapidOCR's ch+en engine does not reproduce on this corpus the `98,1 §ha` /
  `4.3§ ha` digit-confusable mangling that Tesseract produced for the same
  pages (items #2/#3 already parse correctly via RapidOCR without the fix).
  Documented honestly in `docs/superpowers/plans/b2-golden-set.md` (new
  "## Task 3" section) rather than silently declared a win.
- Edge case found during self-review: `_NUM_UNIT` (copied faithfully from the
  plan's illustrative code) has no trailing `\b` after the unit alternation,
  unlike `_AREA` which does. Analyzed and confirmed harmless in practice
  (translation is length-preserving; downstream `_AREA` still has its own
  `\b` guard so no bad field is ever extracted) — documented, not silently
  "improved" past the plan's spec.

## Files changed
- `ennam.kg.python/src/ennam_kg/ingestion/ocr/rapidocr_fields.py` (modified)
- `ennam.kg.python/tests/ingestion/test_rapidocr_fields.py` (new)
- `docs/superpowers/plans/b2-golden-set.md` (workspace-root repo; new "## Task 3" section)

## Current state
- `ennam.kg.python` commit `277e273` (branch `task/implement_docs_sync`):
  `feat(ocr): repair digit/letter confusables in RapidOCR field extraction`
- workspace-root commit `8574f12` (branch `task/implement_docs_sync`):
  `docs(daab): B2 Task 3 record — vi ONNX model spike (deferred) + fields-path A/B`
- Both repos clean working trees after these commits (other pre-existing
  untracked files from earlier sessions, e.g. `.serena/memories/backlog/...`,
  `.codex/`, were NOT touched/staged by this task).

## Next steps
- Task 4/5 of Plan B2 remain (see `docs/superpowers/plans/2026-07-14-daab-ocr-figure-fidelity.md`).
- If a real digit-confusable-mangled RapidOCR fields-path instance ever
  surfaces in a broader corpus, re-run the A/B script pattern used here to
  get a genuine MISS->FOUND validation of `_repair_confusables_near_units`.
- The vi/latin ONNX model spike could be revisited if an official,
  diacritic-complete artifact becomes available, or if paddle2onnx
  conversion effort is later judged worthwhile.

## Blockers / Risks
- None blocking. The regex fix is a real no-op on the current golden set
  (verified, not estimated) — flagged clearly in both the commit message and
  `b2-golden-set.md` so this isn't mistaken for a demonstrated fix.
