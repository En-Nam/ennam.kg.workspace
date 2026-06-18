# Checkpoint: backend-dev — 2026-06-07 (Dart parser complete)

## What was done

- Implemented Dart parser (`dart.py`) from stub → full production parser using tree-sitter-dart (language-pack)
- Wrote 19 tests in `test_dart.py` covering all spec cases (TDD: tests first, then implementation)
- Fixed `_leading_doc` bug: `lstrip("/* ")` was a character-set strip that corrupted Dart markdown in doc comments — replaced with explicit prefix detection for `///`, `/**`, and ` * ` line patterns (commit `5fc96bb`)
- All 10 plan tasks completed and verified

## Files changed

- `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/dart.py` — full implementation
- `ennam.kg.python/packages/ennam-kg-indexer/tests/test_parsers/test_dart.py` — 19 tests

## Current state

- 19/19 Dart-specific tests PASSED
- 138/138 full indexer suite PASSED
- ruff check + format: clean
- `__init__.py`: DartParser imported + registered via `_register(DartParser)`
- `scanner.py`: auto-discovers `.dart` via `get_parser()`
- `extractor.py`: CLASS parents → `relates_to` edges (pre-existing)

## Known limitations (not bugs)

- **Getter/setter natural key collision**: getter `val` and setter `val` both map to `file:val:method`. The differ uses last-writer-wins dict (`new_by_key[key] = payload`), so one collapses. Pre-existing differ design issue — not Dart-specific. Fix belongs in `differ.py` if needed.
- **CLAUDE.md stale doc**: `ennam.kg.python/CLAUDE.md` still says "Dart | Stub | Awaiting tree-sitter-dart on PyPI" — out of scope per plan (plan restricted changes to 2 files only).

## Next steps

- Update `ennam.kg.python/CLAUDE.md` supported languages table (Dart row: Stub → DartParser)
- Fix `differ.py` getter/setter key collision if symbol loss becomes a real concern
- Implement Go parser per `docs/superpowers/plans/2026-06-07-go-parser-implementation.md`

## Blockers / Risks

- None for Dart parser — implementation complete
