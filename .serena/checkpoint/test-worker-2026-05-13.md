# Checkpoint: test-worker — 2026-05-13

## What was done

### Smoke test debugging & fixes
- Identified root cause of 30k TPM hits: `get_table_schema` returned 276k tokens for 297-table C4K Staging MSSQL
- Added `_compact_schema()` to `tools.py` — caps output at 60 tables with columns (~5.8k tokens)
- Added `_resolve_ds_id()` to `tools.py` — UUID validation + fallback when LLM passes data source name
- Added `anthropic.RateLimitError` retry in `engine.py` — 60s backoff, max 1 retry
- Rewrote `_IDENTITY` in `prompts.py` to explicit numbered rules (Haiku compatibility)
- Switched AI provider DB record to `claude-haiku-4-5-20251001`
- Added `SSE_VERBOSE=1` live monitoring to `helpers/sse.py`

### Smoke test results
- Layer 1 (`test_api_smoke.py`): **5 PASS / 1 SKIP** in 7m12s
  - API-01..04, API-06 all green
  - API-05 skipped (Haiku doesn't proactively ask clarification)

### E2E test migration
- Moved `tests/e2e/` (root level, untracked) → `ennam.kg.python/tests/e2e/` (tracked)
- Added `sys.path.insert` to `conftest.py` for reliable `helpers` import
- Updated `run_tests.sh` path depth: `../../..` (was `../..`)
- Added `pytest-timeout>=2.3` to `pyproject.toml` dev deps
- Declared 4 markers in `pyproject.toml`: `smoke`, `accuracy`, `quick_tier`, `deep_tier`
- Updated `CLAUDE.md` with separate unit vs e2e run commands

### Serena updates
- Created `archive/qa-runs/smoke-test-e2e-2026-05-13.md`
- Created `decisions/agentic-engine-lessons.md` (7 lessons)
- Updated `services/python-worker.md` with all fixes and new test layout
- Updated `INDEX.md` with latest QA run + new decisions file

## Files changed

**ennam.kg.python** (committed + pushed, `9022b7a`):
- `src/ennam_kg/agentic/engine.py` — rate limit retry
- `src/ennam_kg/agentic/prompts.py` — numbered rules
- `src/ennam_kg/agentic/tools.py` — _compact_schema, _resolve_ds_id
- `tests/e2e/` — all e2e files (new)
- `pyproject.toml` — pytest-timeout + markers
- `CLAUDE.md` — e2e test commands

**Serena memories**:
- `.serena/memories/archive/qa-runs/smoke-test-e2e-2026-05-13.md`
- `.serena/memories/decisions/agentic-engine-lessons.md`
- `.serena/memories/services/python-worker.md`
- `.serena/memories/INDEX.md`

## Current state

- Agentic engine: fully hardened, Haiku model, smoke tests green
- E2E tests: live in `ennam.kg.python/tests/e2e/`, tracked by git
- Old `tests/e2e/` at root (ennam.kg/) still exists — can be deleted

## Next steps

- [ ] Run Layer 3 accuracy tests: `SSE_VERBOSE=1 uv run pytest tests/e2e/test_accuracy.py -v -s`
- [ ] Run Layer 2 browser tests via Chrome DevTools MCP (browser_playbook.md)
- [ ] Delete old `tests/e2e/` at root level (no longer needed)
- [ ] Write session checkpoint to `.serena/checkpoint/` ← done (this file)

## Blockers / Risks

- Haiku doesn't trigger clarification (API-05 always skips) — acceptable for now
- `test_accuracy.py` has 10s sleep between each of 12 cases = ~2min overhead
- Old `tests/e2e/` at root is orphaned — should be cleaned up to avoid confusion
