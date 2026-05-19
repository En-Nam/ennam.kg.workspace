# FE Action Required: Phase 4 API — Conversational AI, Rich Response, Tools & Insights

**Date**: 2026-04-14
**Status**: BE DEPLOYED — all endpoints live on Docker

---

## Overview

Phase 4 transforms the basic query-response into a conversational AI interface with:
- Multi-turn conversation threads
- SSE streaming responses (9 event types)
- Rich rendering (charts, markdown, code blocks)
- AI-generated insights + suggested actions
- Query favorites

---

## 1. Thread Management (8 endpoints)

### POST /api/v1/threads — Create thread
```json
Request: {"project_id": "uuid", "name": "Revenue Analysis"}
Response 201: ConversationThread object
```

### GET /api/v1/threads?project_id={uuid}&limit=20&before={cursor}
List user's threads (scoped by user identity). Supports cursor pagination via `before` param (ISO timestamp). Optional `include_archived=true`.
```json
Response 200: [
  {
    "id": "uuid",
    "user_id": "uuid",
    "project_id": "uuid",
    "name": "Revenue Analysis",
    "message_count": 12,
    "total_tokens_used": 15000,
    "last_message_at": "2026-04-14T10:00:00Z",
    "is_archived": false,
    "created_at": "2026-04-14T09:00:00Z",
    "updated_at": "2026-04-14T10:00:00Z"
  }
]
```

### GET /api/v1/threads/{id} — Get thread detail
### PUT /api/v1/threads/{id} — Rename thread
```json
Request: {"name": "New Name"}
```
### POST /api/v1/threads/{id}/archive
### POST /api/v1/threads/{id}/unarchive
### DELETE /api/v1/threads/{id} — Soft delete

### GET /api/v1/threads/{id}/messages?limit=20&before={uuid}
Lazy-load messages with cursor pagination. `before` = message UUID for offset.
```json
Response 200: [
  {
    "id": "uuid",
    "thread_id": "uuid",
    "role": "user",
    "content": "How many orders last month?",
    "query_text": "How many orders last month?",
    "created_at": "2026-04-14T10:00:00Z"
  },
  {
    "id": "uuid",
    "thread_id": "uuid",
    "role": "assistant",
    "content": "Based on your query, there were 1,234 orders...",
    "generated_sql": "SELECT COUNT(*) FROM orders WHERE...",
    "result_summary": {"row_count": 1, "columns": ["count"], "sample_rows": [{"count": 1234}]},
    "model_used": "claude-sonnet-4",
    "tokens_input": 1500,
    "tokens_output": 800,
    "latency_ms": 4200,
    "response_blocks": [...],
    "insights": [...],
    "suggested_actions": [...],
    "created_at": "2026-04-14T10:00:05Z"
  }
]
```

---

## 2. SSE Streaming (1 endpoint, 9 event types)

### POST /api/v1/ai-query/stream
**Content-Type request**: `application/json`
**Content-Type response**: `text/event-stream`

```json
Request: {
  "thread_id": "uuid",          // optional — auto-creates thread if omitted
  "data_source_id": "uuid",     // required
  "query": "How many orders last month?"  // 3-2000 chars
}
```

**Response**: SSE stream with these event types:

### Event 1: progress
```
event: progress
data: {"stage":"parsing_intent","label":"Parsing intent...","timestamp":"2026-04-14T10:00:00Z"}
```
Stages: `parsing_intent` → `generating_sql` → `executing_query` → `analyzing_results` → `formatting_response`

### Event 2: content (token streaming)
```
event: content
data: {"token":"Based on ","index":0}
```

### Event 3: format_metadata (BA-018)
```
event: format_metadata
data: {"format":"bar_chart","reasoning":"Aggregation by region with 5 categories","block_count":3,"aggregation_applied":false}
```
Formats: `bar_chart` | `line_chart` | `pie_chart` | `markdown` | `code_block` | `table` | `interactive_viz`

### Event 4: block_start (BA-018)
```
event: block_start
data: {"block_id":"b1","type":"markdown","config":{}}
```

### Event 5: block_content (BA-018)
```
event: block_content
data: {"block_id":"b1","content":"## Revenue Summary\n\nTotal revenue increased by 15%..."}
```
OR for charts/tables:
```
event: block_content
data: {"block_id":"b2","data":[{"region":"NA","revenue":1500000},{"region":"EU","revenue":1200000}]}
```

### Event 6: block_end (BA-018)
```
event: block_end
data: {"block_id":"b1"}
```

### Event 7: suggested_actions (BA-019)
```
event: suggested_actions
data: {"actions":["Show monthly trend chart","Break down by product category","Compare with previous year"]}
```

### Event 8: error
```
event: error
data: {"error_code":"AI_PROVIDER_TIMEOUT","error_message":"Provider timed out","retryable":true}
```

### Event 9: done
```
event: done
data: {"message_id":"uuid","tokens_input":1500,"tokens_output":800,"latency_ms":4200,"generated_sql":"SELECT ...","result_summary":{"row_count":150,"columns":["id","name"]}}
```

### Heartbeat (comment, not event)
```
: heartbeat 2026-04-14T10:30:15Z
```
Sent every 15 seconds. Client should reconnect if no data for 30 seconds.

### Error Codes
- `429` — Concurrent stream limit exceeded. `Retry-After` header included.
- `400` — Invalid request (missing data_source_id, query too short/long)
- `401` — Not authenticated

### Connection Limits
- Max 5 minutes per stream
- Max 3 concurrent streams per user (configurable)
- Heartbeat every 15 seconds

---

## 3. Favorites (6 endpoints)

### POST /api/v1/favorites — Create favorite
```json
Request: {
  "label": "Monthly revenue query",       // optional, defaults to first 100 chars of query
  "query_text": "How many orders last month?",
  "generated_sql": "SELECT COUNT(*)...",   // optional
  "result_snapshot": {"rows": [...], "columns": [...]},  // first 100 rows
  "chart_config": {"type": "bar_chart", ...},  // optional
  "thread_id": "uuid",                    // optional
  "project_id": "uuid"                    // required
}
Response 201: ThreadFavorite object
```

### GET /api/v1/favorites?project_id={uuid}&search={text}&page=1&page_size=20
List favorites. `search` filters by label + query content (ILIKE).

### GET /api/v1/favorites/{id}
### PUT /api/v1/favorites/{id} — Update label
```json
Request: {"label": "New label"}
```
### DELETE /api/v1/favorites/{id} — Hard delete
### POST /api/v1/favorites/{id}/run — Re-run favorite query

---

## 4. Tools (2 endpoints)

### GET /api/v1/threads/{thread_id}/messages/{message_id}/export-csv
Download result data as CSV. Max 10,000 rows.
```
Content-Type: text/csv
Content-Disposition: attachment; filename="thread-name_20260414_100000.csv"
```

### POST /api/v1/threads/{thread_id}/compare
Compare last two query results in thread.
```json
Request: {
  "message_id_a": "uuid",   // optional, defaults to second-to-last
  "message_id_b": "uuid"    // optional, defaults to last
}
Response 200: {
  "message_a": ThreadMessage,
  "message_b": ThreadMessage,
  "diff": { "added_rows": [...], "removed_rows": [...], "changed_rows": [...] }
}
```

---

## 5. TypeScript Types

```typescript
// ─── Threads ──────────────────────────────────────────────
interface ConversationThread {
  id: string;
  user_id: string;
  project_id: string;
  name: string;
  message_count: number;
  total_tokens_used: number;
  last_message_at: string | null;
  is_archived: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

interface ThreadMessage {
  id: string;
  thread_id: string;
  role: 'user' | 'assistant';
  content: string;
  query_text: string | null;
  generated_sql: string | null;
  result_summary: ResultSummary | null;
  ai_query_id: string | null;
  model_used: string | null;
  tokens_input: number | null;
  tokens_output: number | null;
  latency_ms: number | null;
  is_partial: boolean;
  response_blocks: ResponseBlock[] | null;     // BA-018
  aggregation_metadata: AggregationMetadata | null; // BA-018
  insights: Insight[] | null;                  // BA-019
  suggested_actions: string[] | null;          // BA-019
  created_at: string;
}

interface ResultSummary {
  row_count: number;
  columns: string[];
  sample_rows: Record<string, unknown>[];
}

// ─── Rich Response (BA-018) ───────────────────────────────
interface ResponseBlock {
  block_id: string;
  type: 'markdown' | 'code_block' | 'bar_chart' | 'line_chart' | 'pie_chart' | 'table' | 'interactive_viz';
  content?: string;           // for markdown/code
  data?: Record<string, unknown>[]; // for charts/tables
  config?: Record<string, unknown>; // format-specific
}

interface AggregationMetadata {
  original_row_count: number;
  aggregated_row_count: number;
  strategy: string;
  group_by_columns: string[];
  aggregate_functions: string[];
  time_bucket_size?: string;
  rationale: string;
}

// ─── Insights (BA-019) ───────────────────────────────────
interface Insight {
  observation: string;
  category: 'anomaly' | 'trend' | 'pattern' | 'data_quality';
  confidence: 'high' | 'medium' | 'low';
}

// ─── Favorites (BA-019) ──────────────────────────────────
interface ThreadFavorite {
  id: string;
  user_id: string;
  project_id: string;
  label: string;
  query_text: string;
  generated_sql: string | null;
  result_snapshot: Record<string, unknown> | null;
  chart_config: Record<string, unknown> | null;
  thread_id: string | null;
  created_at: string;
  updated_at: string;
}

// ─── SSE Events ──────────────────────────────────────────
interface SSEProgress {
  stage: 'parsing_intent' | 'generating_sql' | 'executing_query' | 'analyzing_results' | 'formatting_response';
  label: string;
  timestamp: string;
}

interface SSEContent {
  token: string;
  index: number;
}

interface SSEFormatMetadata {
  format: string;
  reasoning: string;
  block_count: number;
  aggregation_applied: boolean;
}

interface SSEBlockStart {
  block_id: string;
  type: string;
  config: Record<string, unknown>;
}

interface SSEBlockContent {
  block_id: string;
  content?: string;
  data?: Record<string, unknown>[];
}

interface SSEBlockEnd {
  block_id: string;
}

interface SSESuggestedActions {
  actions: string[];
}

interface SSEError {
  error_code: string;
  error_message: string;
  partial_content?: string;
  retryable: boolean;
}

interface SSEDone {
  message_id: string;
  tokens_input: number;
  tokens_output: number;
  latency_ms: number;
  generated_sql: string;
  result_summary: ResultSummary;
}
```

---

## 6. SSE Client Implementation Guide

```typescript
// src/lib/api/stream.ts
export async function streamQuery(
  threadId: string | null,
  dataSourceId: string,
  query: string,
  onEvent: (event: string, data: unknown) => void,
): Promise<void> {
  const res = await fetch('/api/kg/ai-query/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      thread_id: threadId,
      data_source_id: dataSourceId,
      query,
    }),
  });

  if (!res.ok) throw new Error(`Stream failed: ${res.status}`);
  if (!res.body) throw new Error('No response body');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = 'message';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7);
      } else if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6));
        onEvent(currentEvent, data);
      }
      // Ignore heartbeat comments (lines starting with ':')
    }
  }
}
```

### TanStack Query Hook for Threads
```typescript
// src/hooks/use-threads.ts
export function useThreads(projectId: string) {
  return useQuery({
    queryKey: ['threads', projectId],
    queryFn: () => fetchThreads(projectId),
    staleTime: 30_000,
  });
}

export function useThreadMessages(threadId: string) {
  return useQuery({
    queryKey: ['thread-messages', threadId],
    queryFn: () => fetchMessages(threadId),
    enabled: !!threadId,
  });
}
```

---

## 7. Suggested FE Pages

| Route | Purpose |
|-------|---------|
| `/ai-query` | Main conversational AI page: thread sidebar + message area + streaming |
| `/ai-query?thread={id}` | Open specific thread |
| `/favorites` | List/manage saved queries |

---

## 8. BFF Proxy Notes

The SSE streaming endpoint needs special handling in the BFF proxy — it must NOT buffer the response:

```typescript
// src/app/api/kg/ai-query/stream/route.ts
export async function POST(request: Request) {
  const body = await request.json();
  const session = await getSession();
  
  const res = await fetch(`${GO_API_URL}/api/v1/ai-query/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${session.apiKey}`,
    },
    body: JSON.stringify(body),
  });

  // IMPORTANT: Stream through without buffering
  return new Response(res.body, {
    status: res.status,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    },
  });
}
```
