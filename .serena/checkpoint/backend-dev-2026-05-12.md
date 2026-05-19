# Checkpoint: backend-dev — 2026-05-12

## What was done
- **B1 (P1a)**: Fixed `sql_generator.py` SELECT clause bug — multi-table plans with no JOINs
  incorrectly included all tables in SELECT, causing MSSQL error 107 (column prefix not bound).
  Fixed: only primary table and explicitly JOINed tables appear in SELECT.
- **B2 (P1b)**: Added INFORMATION_SCHEMA/sys view blocking in two places:
  - `prompts.py`: Added explicit rule in `get_intent_parsing_prompt()` forbidding system views
  - `intent_parser.py`: Added system view guard in `_validate_plan()` that raises `IntentParseError`
    with "System views are not accessible" before the generic unknown-table check
- **Tests**: Added 4 tests to `tests/test_nl_query/test_sql_generator.py` and 5 tests to
  `tests/test_nl_query/test_intent_parser.py`. All written as failing-first (TDD).

## Files changed
- `src/ennam_kg/nl_query/sql_generator.py` — SELECT clause fix (3 lines replaced with 5)
- `src/ennam_kg/nl_query/prompts.py` — added INFORMATION_SCHEMA rule in prompt
- `src/ennam_kg/nl_query/intent_parser.py` — system view guard in `_validate_plan`
- `tests/test_nl_query/test_sql_generator.py` — 4 new tests appended
- `tests/test_nl_query/test_intent_parser.py` — 5 new tests appended (+ import of `_validate_plan`)

## Current state
- 28 nl_query tests pass (19 existing + 9 new)
- 2 commits created on `main` branch
- 24 pre-existing failures in other test files (test_differ, test_extractor, test_engine, etc.)
  are unrelated to this work and were present before this session

## Next steps
- Wave 2 test-worker: verify via API smoke tests and accuracy eval against C4K Staging MSSQL
- Pre-existing test failures in test_differ/test_extractor warrant investigation

## Blockers / Risks
- None for this task. Pre-existing failures in unrelated modules should be investigated separately.
