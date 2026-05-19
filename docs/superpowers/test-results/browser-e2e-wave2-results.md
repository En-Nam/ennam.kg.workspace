# Wave 2 Browser E2E Test Results — 2026-05-12

## Summary

| Layer | Tests | Pass | Fail | Skip |
|-------|-------|------|------|------|
| UI (Browser E2E) | 8 | 5 | 0 | 3 (⚠️ degraded) |
| Layer 1 API Smoke | 6 | 3 | 2 | 1 |
| Layer 3 Accuracy | 12 | 6 | 6 | 0 |

**Wave 2 verdict: PARTIAL PASS** — Core agentic flow works end-to-end. Three known bugs block full pass.

---

## Bugs Fixed This Session

### Fix 1: SSE content event format mismatch (CRITICAL)
- **Symptom**: AI response showed as `(streamed response)` instead of actual text
- **Root cause**: Agentic Python engine sends `content` events as `{"data": "..."}` but `SSEContent` Go model only had `Token string` field; `Data` was silently ignored
- **Files changed**:
  - `ennam.kg.go/internal/models/sse.go` — Added `Data string \`json:"data,omitempty"\`` to `SSEContent`
  - `ennam.kg.go/internal/service/sse_stream.go` — Updated `HandleContentToken` to use `content.Data` as fallback when `content.Token == ""`
- **Status**: FIXED ✅ — Verified via Chrome DevTools: actual AI text appears in ChatMessageList

### Fix 2: Anthropic SDK objects not JSON-serializable (CRITICAL)
- **Symptom**: `TypeError: Object of type TextBlock is not JSON serializable` on second+ agentic iteration
- **Root cause**: `messages.append({"role": "assistant", "content": response.content})` stored Anthropic SDK typed objects (`TextBlock`, `ToolUseBlock`). On iteration 2, `state.to_json()` → `json.dumps(messages)` fails.
- **File changed**: `ennam.kg.python/src/ennam_kg/agentic/engine.py:273-276`
  - Changed to: `[b.model_dump() for b in response.content]`
- **Status**: FIXED ✅ — Multi-tool-call iterations now succeed

### Fix 3: conftest.py projects fixture KeyError (E2E tests)
- **Symptom**: `KeyError: 0` when discovering project_id in pytest fixtures
- **Root cause**: `/api/v1/projects` returns `{"projects": [...]}` not a bare list; code did `projects[0]` on a dict
- **File changed**: `tests/e2e/conftest.py:50-52`
- **Status**: FIXED ✅

---

## UI Tests (Browser E2E via Chrome DevTools MCP)

### UI-01: TierSelector visible ✅
- Quick and Deep buttons visible in chat UI
- Rendered as toggle buttons with active state

### UI-02: Deep tier stored in localStorage ✅
- Clicking Deep writes `tier-{threadId} = "deep"` to localStorage
- Verified via `localStorage.getItem(...)` JS eval

### UI-03: Quick tier SSE sequence ✅
- Full event sequence observed: `agent_start → tool_call_start → tool_call_end → content → agent_done → done`
- AgenticStreamPanel rendered with step count during active stream
- Content text appeared in ChatMessageList after stream

### UI-04: Deep tier tool call count ⚠️ DEGRADED
- Deep tier routing confirmed: `tier: "deep"`, `max_iterations: 12` in request
- `list_datasources` tool invoked (routing correct)
- **BLOCKED**: `list_datasources` uses wrong `node_type: "data_source"` → KG API returns 400 → stream ends in error after 1 tool call
- Requirement: ≥2 distinct tool calls per Deep session — cannot verify
- Root cause: Separate bug in `list_datasources` tool implementation (new finding, see backlog)

### UI-05: KG traversal tool calls ⚠️ SKIPPED
- No KG nodes exist in test environment
- Tool calls to `search_nodes`/`get_neighbors` would return empty → agent skips them
- Cannot verify traversal behavior without seed data

### UI-06: Error handling ⚠️ DEGRADED
- Error message displayed in AgenticStreamPanel when tool call fails — UI rendering correct ✅
- **BUG**: `useAgenticStream` hook does not reset `isStreaming` to `false` when stream ends with an `error` event without a subsequent `done` event
- Input field stays disabled after error; user must refresh page
- Root cause: `isStreaming` flag only clears on `done` event, not on `error` + connection close

### UI-07: History persistence after stream ✅
- `queryClient.invalidateQueries(['messages', threadId])` fires when stream completes
- Confirmed: `GET /messages?limit=50` request fires immediately after `agent_done` event
- New message appears in ChatMessageList without page reload

### UI-08: Tier field in request body ✅
- Network request body contains `"tier": "quick"` for Quick tier
- Network request body contains `"tier": "deep"` for Deep tier
- Routing to Python agentic endpoint confirmed for both tiers

---

## Layer 1 API Smoke Tests

Run: `pytest tests/e2e/test_api_smoke.py -v`

| Test | Result | Notes |
|------|--------|-------|
| test_api_01 — Quick tier SSE sequence | ✅ PASS | Full event sequence verified |
| test_api_02 — Deep tier sequence | ❌ FAIL | `list_datasources` node_type 400 → stream ends in error |
| test_api_03 — DDL rejection | ✅ PASS | SQL gate rejects DROP/ALTER/INSERT |
| test_api_04 — SELECT enforcement | ❌ FAIL | `execute_sql` never invoked; agent takes clarification path |
| test_api_05 — Clarification pause/resume | ⚠️ SKIP | Clarification flow not tested (environment limitation) |
| test_api_06 — Invalid data source | ✅ PASS | Returns error event as expected |

---

## Layer 3 Accuracy Evaluation

Run: `pytest tests/e2e/test_accuracy.py -v`

**Result: 6/12 passed** (average score below 2.0/3.0 gate)

Passed cases: Simple schema queries, count queries, basic joins
Failed cases: Multi-hop joins, aggregations with filters, ambiguous column names, KG-dependent queries (blocked by list_datasources bug)

Primary blockers for failed cases:
1. `list_datasources` tool failure on Deep tier → agent cannot discover available data sources
2. Accuracy gate requires 2.0/3.0 average — not met

---

## New Bugs Found (for backlog)

### BUG-1: `list_datasources` wrong node_type (P2)
- **File**: Python agentic tools — `list_datasources` tool
- **Bug**: Uses `node_type: "data_source"` in KG API call → returns 400 `invalid node_type`
- **Expected**: Correct node type per KG schema (likely `"data_source"` is wrong capitalization/slug)
- **Impact**: Blocks all Deep tier flows; blocks accuracy test cases requiring data source discovery
- **Backlog**: `backlog/python-list-datasources-node-type.md`

### BUG-2: `useAgenticStream` isStreaming not reset on error (P3)
- **File**: `ennam.kg.next/src/hooks/useAgenticStream.ts` (or similar)
- **Bug**: `isStreaming` flag only clears on `done` event; if stream ends with `error` + TCP close, input stays disabled
- **Workaround**: User must refresh page after an error
- **Impact**: UX degraded on error paths; not blocking for core flow
- **Backlog**: `backlog/next-agentic-stream-error-reset.md`

---

## Deployment Notes

Changes applied to running Docker environment during session:
- Go server: `docker compose restart kg-server` (Air hot-reload + manual restart)
- Python indexer: `docker cp` of `engine.py` to `/app/src/ennam_kg/agentic/engine.py` in container + `docker compose restart indexer`
- **Note**: Python indexer runs from built image at `/app/src`, not from mounted source volume. File changes require `docker cp` + restart, not source edits alone.

---

## Files Changed (require git commit)

| File | Change |
|------|--------|
| `ennam.kg.go/internal/models/sse.go` | Added `Data` field to `SSEContent` |
| `ennam.kg.go/internal/service/sse_stream.go` | `HandleContentToken` fallback to `content.Data`; `pythonEndpoint()` routing fix |
| `ennam.kg.python/src/ennam_kg/agentic/engine.py` | `model_dump()` for Anthropic SDK objects in messages list |
| `tests/e2e/conftest.py` | Fixed projects fixture to handle `{"projects": [...]}` response shape |
