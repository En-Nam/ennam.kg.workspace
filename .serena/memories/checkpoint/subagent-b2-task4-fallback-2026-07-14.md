# Checkpoint: subagent (DAAB B2 Task 4) — 2026-07-14

## What was done
- Implemented Plan B2 Task 4: residual-figure fallback (CPU second detector + fail-loud `unrecovered` marker).
- TDD: wrote 4 tests in `tests/ingestion/test_ocr_fallback.py` (brief's 2 illustrative tests + 2 extra: bounded-cost "second detector not called when nothing missing", "only still-missing fields flagged"). Verified RED (`ModuleNotFoundError: fallback`) before implementing.
- New `ennam.kg.python/src/ennam_kg/ingestion/ocr/fallback.py`: `recover_or_flag(primary, second_detector, expected)` — matches brief's illustrative logic verbatim (verified correct by hand for both test cases); `DEFAULT_EXPECTED_FIELDS = {"areas"}` module constant (simple global default, no doc-type classifier — YAGNI).
- Refactored `rapidocr_fields.py`: extracted `extract_fields_from_text(text)` (normalize + confusable-repair + regex extraction) out of `extract_structured_fields(img)`, so it's reusable against any OCR engine's raw text output.
- Wired into `extract_structured_fields_for_file` (`ingestion/adapters/files.py`): primary RapidOCR pass aggregates fields across all pages (unchanged) → `recover_or_flag` called once at document level → if `expected` fields still missing, a lazy `second_detector()` closure re-renders pages (fresh `page_texts_and_renders(path)` call) and runs `TesseractEngine().ocr_image()` + `extract_fields_from_text()` per page, merging results. Second detector only invoked when something is missing (bounded cost, no speculative OCR). WARNING logged when `unrecovered` is non-empty.

## Key decision — "the other detector" interpretation
Brief's literal text said "RapidOCR (vi/latin if available, else default)" as the second detector. Read `rapidocr_fields.py` and found there is only ONE RapidOCR config (ch+en) — a vi/latin variant was explicitly evaluated and deferred in Task 3 (comment in `_get_engine()`: no VN-diacritic ONNX rec model readily available without conversion). Running RapidOCR against itself on the same image is deterministic and would recover nothing — not a real second detector. Deviated to use Tesseract (already in the codebase for body-text OCR, genuinely fails differently) as the second detector. Documented in commit message per Rule 7 (surface conflict, don't average).

## Files changed
- `ennam.kg.python/src/ennam_kg/ingestion/ocr/fallback.py` (new)
- `ennam.kg.python/tests/ingestion/test_ocr_fallback.py` (new)
- `ennam.kg.python/src/ennam_kg/ingestion/ocr/rapidocr_fields.py` (refactor: extracted `extract_fields_from_text`)
- `ennam.kg.python/src/ennam_kg/ingestion/adapters/files.py` (wired fallback into `extract_structured_fields_for_file`)

## Current state
- Commit `39e16e7` on branch `task/implement_docs_sync` in `ennam.kg.python` (nested repo).
- `uv run pytest tests/ingestion/ tests/test_worker_extract_gate.py` → 98 passed (includes real-fixture integration test `test_structured_fields_for_scanned_pdf`, exercises the actual Tesseract fallback wiring, no errors).
- Full `uv run pytest` → 659 passed, 1 pre-existing unrelated failure (`tests/extraction/test_parser.py::test_drops_out_of_range_span_and_orphan_relation`, confirmed pre-existing via `git stash` before this change), 17 e2e errors (no live Docker stack, expected), 2 skipped.
- `uv run ruff check` on all touched files: clean.

## Next steps
- Task 5 of Plan B2 (if any) — not investigated, out of scope for this task.
- Optional: note golden-set fallback performance in `docs/superpowers/plans/b2-golden-set.md` (brief said optional, not done).

## Blockers / Risks
- None. Task complete, reviewed against self-review checklist, committed.
