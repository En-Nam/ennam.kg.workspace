# Python Team → Frontend Team: Integration Status

**Date**: 2026-04-29
**From**: Python Team (ennam.kg.python)
**To**: Frontend Team (ennam.kg.next)
**Re**: Phase 4 SSE Streaming + Bug Fix — What FE needs to know

---

## 1. Bug Fix: Intent Parse Failure — DEPLOYED

**Issue**: `project/be-bug-python-intent-parse-failure` — all chat messages failed with `INTENT_PARSE_FAILED`.

**Root cause**: AI model returned empty string → `json.loads("")` crashed at char 0.

**Fix deployed** (commit `baca818` on main):
- Empty response now detected before JSON parse → clear error message: `"AI returned empty response"`
- **Retry logic added**: Python retries once on empty/invalid AI response before giving up
- Error code remains `INTENT_PARSE_FAILED` but message is now more descriptive

**FE action**: Re-test chat flow. If it still fails, the problem is upstream (Go API → AI provider config), not Python.

---

## 2. SSE Event Stream — Complete Reference

FE receives these events through the BFF proxy (`/api/kg/ai-query/stream` → Go → Python).

### Event Timeline (happy path)

```
1. progress  {"stage":"parsing_intent",    "label":"Understanding your question..."}
2. progress  {"stage":"generating_sql",     "label":"Generating SQL query..."}
3. progress  {"stage":"executing_query",    "label":"Running query..."}
4. progress  {"stage":"generating_response","label":"Analyzing results..."}
5. format_metadata  {"format":"table|chart|markdown|mixed", "total_blocks":2, "aggregation_applied":false}
6. content × N      {"token":"word", "index":0}  ← stream these into the chat bubble
7. block_start      {"block_id":"blk-abc123", "block_type":"markdown|table|chart|code", "config":{...}}
8. block_content    {"block_id":"blk-abc123", "content":"...", "data":{...}, "is_complete":true}
9. block_end        {"block_id":"blk-abc123"}
   (repeat 7-9 for each block)
10. suggested_actions  {"actions":[{"label":"...", "action_type":"query|export|compare|drill_down", "query":"..."}]}
11. done  {"message_id":"uuid", "tokens_input":500, "tokens_output":200, "latency_ms":1234, "generated_sql":"SELECT ..."}
```

### Error Events

```
error  {"error_code":"INTENT_PARSE_FAILED",     "error_message":"...", "retryable":false}
error  {"error_code":"SCHEMA_FETCH_FAILED",      "error_message":"...", "retryable":true}
error  {"error_code":"SQL_GENERATION_FAILED",    "error_message":"...", "retryable":false}
error  {"error_code":"QUERY_EXECUTION_FAILED",   "error_message":"...", "retryable":true}
error  {"error_code":"STREAM_TIMEOUT",           "error_message":"...", "retryable":true}
error  {"error_code":"INTERNAL_ERROR",           "error_message":"...", "retryable":true}
```

**FE handling**: If `retryable=true`, show retry button. If `retryable=false`, show error message only.

### Wire Format

Each event is two lines + blank line:
```
event: progress
data: {"stage":"parsing_intent","label":"Understanding your question...","timestamp":"2026-04-29T05:07:10.122Z"}

event: content
data: {"token":"Found","index":0}

```

Parse with standard `EventSource` or manual line splitting. Heartbeat comments (`: heartbeat ...`) come from Go, not Python.

---

## 3. Rendering Guide per Block Type

| `block_type` | `content` field | `data` field | `config` field | How to render |
|-------------|----------------|-------------|---------------|---------------|
| `markdown` | Markdown text | null | null | Render as markdown (summary) |
| `table` | null | `{columns:[], rows:[[]]}` | `{total_rows: N}` | Render as data table, paginate if rows > config.total_rows |
| `chart` | null | `{columns:[], rows:[[]]}` | `{chart_type: "bar"|"line"}` | Render chart using config.chart_type |
| `code` | SQL string | null | `{language: "sql"}` | Render as syntax-highlighted code block |

### Suggested Actions

```json
{
  "actions": [
    {"label": "Drill into EU", "action_type": "query", "query": "show EU sales by month"},
    {"label": "Export CSV", "action_type": "export"},
    {"label": "Compare YoY", "action_type": "compare"}
  ]
}
```

- `action_type: "query"` → Pre-fill chat input with `action.query` and auto-send
- `action_type: "export"` → Trigger CSV export of current results
- `action_type: "compare"` → Open compare view (if implemented)
- `action_type: "drill_down"` → Navigate to detail view

Always exactly 3 actions per response.

---

## 4. `format_metadata` Usage

Arrives BEFORE content tokens. Use it to:
1. Set up the rendering layout before content starts streaming
2. Know how many blocks to expect (`total_blocks`)
3. Show aggregation indicator if `aggregation_applied=true`

### Format Values

| `format` | Meaning | Typical blocks |
|----------|---------|----------------|
| `table` | Raw tabular data | markdown (summary) + table |
| `chart` | Visualization-friendly data | markdown + chart |
| `markdown` | Text-heavy response | markdown only |
| `code` | SQL or code output | markdown + code |
| `mixed` | Multiple block types | markdown + chart + table |

---

## 5. Known Limitations

- **`context_messages` not yet used**: Python accepts the field but doesn't inject prior messages into the AI prompt yet. Multi-turn context improvement is TODO.
- **`full_content` on done event**: Contains the complete accumulated text from all content tokens. FE can use this for copy-to-clipboard or if content tokens were missed.
- **First embedding request is slow**: ~5s model load time on first call. Not visible to FE unless FE triggers embeddings directly (unlikely — Go manages this).
