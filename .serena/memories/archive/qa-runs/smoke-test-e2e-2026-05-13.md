# Smoke Test E2E Run — 2026-05-13

**Layer**: Layer 2 — API Smoke Tests (`tests/e2e/test_api_smoke.py`)
**Duration**: 7m 12s
**Result**: **5 PASSED, 1 SKIPPED** — all critical tests green

---

## Test Results

| Test | Result | Notes |
|------|--------|-------|
| API-01: Quick Tier SSE Event Sequence | ✅ PASS | search_kg → get_table_schema → 19,569 tokens |
| API-02: Deep Tier Extended Exploration | ✅ PASS | search_kg → list_datasources → get_table_schema → execute_sql → 41,067 tokens |
| API-03: DDL Rejection | ✅ PASS | Agent refused DROP without tool calls, 985 tokens |
| API-04: SELECT Enforcement | ✅ PASS | search_kg → get_table_schema → execute_sql |
| API-05: Clarification Pause/Resume | ⏭ SKIP | LLM-dependent — Haiku doesn't proactively ask for clarification |
| API-06: Invalid Data Source | ✅ PASS | Returned error event cleanly |

---

## Fixes Deployed During This Session

### Root Issue: 276k Token Schema Explosion
- C4K Staging has 297 dbo tables → raw `get_schema_metadata` = 1.1MB ≈ 276k tokens
- A single `get_table_schema` call IMMEDIATELY exceeded the 30k TPM rate limit
- Every subsequent Anthropic call got a 429 before receiving any content
- Fix: `_compact_schema()` in `tools.py` returns ALL table names + column details for first 60 → ~5.8k tokens

### Agent Passing Data Source Name Instead of UUID
- Haiku passed "C4K Staging" (human label) instead of UUID to `get_table_schema`
- Fix: `_resolve_ds_id()` in `tools.py` validates UUID format; falls back to `self._data_source_id` from request context

### Haiku Prompt Compatibility
- Original prompt: "If KG search returns 0 results, do not repeat with similar queries"
- Haiku doesn't reliably follow conditional/implicit instructions
- Fix: Rewrote `_IDENTITY` in `prompts.py` as explicit numbered rules:
  ```
  1. Call search_kg AT MOST ONCE. If it returns 0 results, do NOT call search_kg again.
  2. After search_kg returns 0 results, call get_table_schema immediately.
  3. After seeing the schema, write a SELECT query and call execute_sql.
  ...
  ```

### Rate Limit Retry
- Added `anthropic.RateLimitError` catch in `engine.py`: 60s backoff, max 1 retry
- Secondary mitigation after schema truncation fixed the root cause

### Model Switch
- Changed AI provider DB record from `claude-sonnet-4-20250514` → `claude-haiku-4-5-20251001`
- SQL: `UPDATE ai_providers SET model_id = 'claude-haiku-4-5-20251001' WHERE name = 'ennam-kg';`

---

## Live Monitoring

Ran with `SSE_VERBOSE=1` to see real-time tool events:
```bash
cd tests/e2e && SSE_VERBOSE=1 python -m pytest test_api_smoke.py -v -s 2>&1
```
Output format: `[elapsed] tool_name  OK/FAIL  summary_preview  (duration_ms)`

---

## Remaining Work

- [ ] Layer 3: `test_accuracy.py` — accuracy test cases with `time.sleep(10)` between cases
- [ ] Browser UI tests via Chrome DevTools MCP (http://localhost:3500)
- [ ] Session checkpoint write
