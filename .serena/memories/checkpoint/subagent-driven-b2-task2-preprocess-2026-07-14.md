# Checkpoint: subagent-driven (Plan B2 Task 2) — 2026-07-14

## What was done
- Implemented `preprocess_for_ocr` (grayscale -> median denoise -> Otsu binarize -> +/-8deg deskew) in `ennam.kg.python/src/ennam_kg/ingestion/ocr/preprocess.py`, TDD (3 failing tests -> pass).
- Wired `TesseractEngine(preprocess: bool)` ctor param, `ocr_preprocess_enabled: bool = False` in config.py, call site in `files.py::_extract_pdf` reads `settings.ocr_preprocess_enabled`.
- Ran real A/B on Task 1's golden-set harness (`scripts/b2_figure_metrics.py`), BEFORE run byte-matched Task 1's captured baseline (sanity check passed).

## Files changed
- ennam.kg.python: `src/ennam_kg/ingestion/ocr/preprocess.py` (new), `tesseract_engine.py`, `config.py`, `ingestion/adapters/files.py`, `tests/ingestion/test_ocr_preprocess.py` (new) — commit `7af5e5c`.
- workspace-root: `docs/superpowers/plans/b2-golden-set.md` (AFTER A/B section appended) — commit `0bbce23`.

## Current state
- 86/86 tests pass in `tests/ingestion/`; ruff clean.
- **Gate decision: `ocr_preprocess_enabled` stays `False`** (default unchanged). Evidence: retrievability (found/miss) flat 2/5->2/5 (no items crossed MISS->FOUND); CER halved on items #2/#3 (digit-confusable class, both now 1 char from FOUND: `I`/`1`, `.`/`,`); CER *regressed* on item #5 (best-effort, decorative-font page, 0.471->0.706) — a real degradation on a real scanned page, not a synthetic-test artifact. No regression on the two currently-correct control items (#1/#4, both stayed FOUND/CER=0.000). Determinism re-verified (two runs, byte-identical output).
- Feature ships wired end-to-end and opt-in only, per plan's explicit "if it doesn't help, keep it OFF (no harm)" fallback.

## Next steps
- If Task 3 (RapidOCR + digit-confusable regex fixes) lands, re-run the A/B combining both — items #2/#3 are now only 1 char from FOUND, plausible the combination clears the gate where preprocessing alone did not.
- Item #5 regression hypothesis (unverified): Otsu's single global threshold likely clips/fuses thin decorative-font strokes; deskew's horizontal-projection-variance search may misfire on non-paragraph page structure. Worth investigating only if item #5 becomes a live gate target.

## Blockers / Risks
- None. Task complete, decision is evidence-based and documented in b2-golden-set.md.
