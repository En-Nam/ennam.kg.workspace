# Checkpoint: backend-dev — 2026-06-07 (Markdown Task 5)

## What was done

Implemented **Task 5: Resilience** for the `ennam-kg-indexer` markdown parser.
- Added 2 resilience tests to lock the parser's error-handling contract
- Verified existing error-handling code in `markdown.py` passes both tests without any production code changes

### Tests Added

Two new test cases appended to `packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py`:

1. **`test_malformed_markdown_does_not_raise`** — Parser never raises on malformed markdown
   - Tests: unclosed links, unterminated code fences, empty headings
   - Expected: Parse succeeds, returns list with DOCUMENT hub present
   - Contract: `has_error` flag → log warning but continue extracting

2. **`test_unreadable_file_returns_empty`** — Parser handles missing files gracefully
   - Tests: Parsing non-existent file path
   - Expected: Return empty list
   - Contract: `OSError` → log warning, return `[]`

## Files changed

- **Modified**: `packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py`
  - Lines 98–108: Added 2 test functions

## Current state

- **11/11 tests pass** (9 pre-existing + 2 new)
  - `test_malformed_markdown_does_not_raise` — PASS
  - `test_unreadable_file_returns_empty` — PASS
- Production code unchanged — no errors found
- Commit: `f9f09d1` on branch `task/sines-enhancement`

## Verification

```
$ uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py -v
... 11 passed in 0.06s
```

## Next steps

Task 5 complete. Markdown parser resilience is locked via tests.
Ready for next task (Task 6: Containment edge integration tests, or Task 7/8 full suite).

## Blockers / Risks

None. Task completed on first run with all tests passing.
