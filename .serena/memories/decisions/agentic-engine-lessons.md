# Agentic Engine — Lessons Learned & Pitfalls

**Created**: 2026-05-13
**Context**: Smoke test debugging session — tracing 30k TPM token explosion and Haiku behavior

---

## 1. Schema Truncation is Critical

**Problem**: C4K Staging MSSQL has 297 tables in `dbo` schema.
Raw `get_schema_metadata` → `_transform_schema_tree` → 1.1MB dict ≈ **276,259 tokens**.
This is 9× the entire 30k TPM budget — a SINGLE tool call causes immediate 429 on the next Anthropic call.

**Fix**: `_compact_schema()` in `tools.py`:
- Returns ALL table names (so agent knows what exists to write SQL)
- Column details ONLY for first `_MAX_SCHEMA_TABLES = 60` tables
- Result: ~5.8k tokens (96% reduction)

**Lesson**: Always cap tool result size before returning to LLM. Token explosions don't happen at the tool call — they happen as INPUT tokens on the NEXT API call (full conversation history is sent every turn).

---

## 2. Conversation History Compounds Token Usage

**How Anthropic billing works in agentic loops**:
```
Iteration 1: system_prompt + user_message                     → N tokens
Iteration 2: system_prompt + user_message + tool_result_1    → N + R1 tokens
Iteration 3: system_prompt + user_message + tool_results 1+2 → N + R1 + R2 tokens
```
Each iteration resends the ENTIRE conversation history as input. A single large tool result (e.g., 276k tokens) causes every subsequent call to cost 276k+ input tokens.

**Lesson**: Token budgets must be enforced at the tool level (truncate before returning), not at the prompt level.

---

## 3. Haiku vs Sonnet Prompt Style

**Sonnet**: Can follow conditional/implicit instructions reliably.
```
"If KG search returns 0 results, do not repeat with similar queries — instead inspect the schema."
```

**Haiku**: Requires explicit numbered step-by-step rules. Conditional "if X then Y" chains are NOT reliably followed.
```
1. Call search_kg AT MOST ONCE. If it returns 0 results, do NOT call search_kg again.
2. After search_kg returns 0 results, call get_table_schema immediately.
3. After seeing the schema, write a SELECT query and call execute_sql.
```

**Lesson**: When switching models, revalidate that the system prompt style matches the model's instruction-following capability. Haiku is cheaper/faster but needs more explicit rules.

---

## 4. Agent Passes Human Labels Instead of UUIDs

**Problem**: LLM sometimes passes "C4K Staging" (human-readable name) as `data_source_id` instead of the UUID.
This causes the schema fetch to fail silently (wrong data source looked up).

**Fix**: `_resolve_ds_id()` in `tools.py`:
```python
def _resolve_ds_id(self, value: str) -> str:
    try:
        _uuid_mod.UUID(value)
        return value
    except (ValueError, AttributeError):
        return self._data_source_id  # fallback to request context
```

**Lesson**: Never trust LLM-provided IDs to be in the correct format. Always validate and fall back to the authoritative source from the request context.

---

## 5. Session Key vs API Key in E2E Tests

**Problem**: Attempted to use permanent developer API keys (`POST /api/v1/api-keys`) to avoid session revocation in tests.
Go's `/api/v1/conversations` returns: `"user account required for conversation threads"` — developer keys cannot create threads.

**Fix**: Keep session keys (from `POST /api/v1/auth/login`). Run both test files in a SINGLE pytest command so `scope="session"` fixture calls `login()` only once → no concurrent revocation.

**Lesson**: In this project, AI conversation threads require user-scoped sessions, not API keys. Don't try to bypass this.

---

## 6. Live Monitoring During Agentic Tests

Set `SSE_VERBOSE=1` to see real-time tool events without changing test code:
```bash
SSE_VERBOSE=1 python -m pytest test_api_smoke.py -v -s 2>&1
```
Output format:
```
  ── SSE stream  tier=quick  query='What tables exist in C4K Staging?'
  ▶ [  0.1s] agent_start  tier=quick  max_iter=3
  → [  1.2s] search_kg            'C4K Staging'
  ✓ [  2.1s] search_kg            OK  nodes found  (891ms)
  → [  2.1s] get_table_schema     <ds-id>
  ✓ [  4.3s] get_table_schema     OK  297 tables returned  (2147ms)
  💬 [  5.0s] content      'The C4K Staging database...'
  ■ [  5.1s] agent_done   iter=2  tokens=19569  tools=['search_kg', 'get_table_schema']
  □ [  5.1s] done  status=complete
```

**Lesson**: `SSE_VERBOSE=1` is the key debugging tool for agentic test runs — shows tool name, timing, success, and running token count per event. Use `-s` flag to prevent pytest from capturing stderr.

---

## 7. Rate Limit Retry Pattern

Adding `anthropic.RateLimitError` retry at the engine level (not tool level):
```python
for _attempt in range(2):
    try:
        response = await self._ai._client.messages.create(...)
        break
    except anthropic.RateLimitError as exc:
        if _attempt == 0:
            await asyncio.sleep(60)
        else:
            raise
```
After schema truncation fixed the root cause, this retry is rarely triggered. But it's a safety net for transient 429s.

**Lesson**: Rate limit retries should be secondary mitigation. If hitting 429 frequently, investigate token usage first (likely a tool returning massive data).
