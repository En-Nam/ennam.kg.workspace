# Python Team → Go API Team: Integration Handoff

**Date**: 2026-04-29
**From**: Python Team (ennam.kg.python)
**To**: Go API Team (ennam.kg.go)
**Re**: Phase 4 SSE Streaming + BA-021 OAuth/Embeddings — Python side DONE

---

## 1. Phase 4: SSE Streaming Endpoint — READY

Python worker now exposes `POST http://localhost:8081/api/v1/ai/stream` for Go to proxy.

### Request Contract

```
POST /api/v1/ai/stream
Content-Type: application/json
Authorization: Bearer <token>   ← Go passes the resolved auth token

Body:
{
  "project_id": "uuid",
  "data_source_id": "uuid",
  "query": "natural language question",
  "thread_id": "uuid",
  "message_id": "uuid",
  "context_messages": [                    ← optional, for multi-turn
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

### Response: SSE Event Stream

```
Content-Type: text/event-stream

Event order:
  progress(parsing_intent)
  progress(generating_sql)
  progress(executing_query)
  progress(generating_response)
  format_metadata(format, total_blocks, aggregation_applied)
  content(token, index) × N          ← word-by-word summary
  block_start → block_content → block_end  × per block
  suggested_actions(actions[3])
  done(message_id, tokens_input, tokens_output, latency_ms, generated_sql, full_content)
```

### SSE Event Payloads (9 types)

| Event | Key Fields | BA |
|-------|-----------|-----|
| `progress` | `stage`, `label`, `timestamp` | BA-017 |
| `content` | `token`, `index` | BA-017 |
| `error` | `error_code`, `error_message`, `retryable` | BA-017 |
| `done` | `message_id`, `tokens_input`, `tokens_output`, `latency_ms`, `generated_sql`, `full_content` | BA-017 |
| `format_metadata` | `format`, `total_blocks`, `aggregation_applied` | BA-018 |
| `block_start` | `block_id`, `block_type`, `config` | BA-018 |
| `block_content` | `block_id`, `content`, `data`, `is_complete` | BA-018 |
| `block_end` | `block_id` | BA-018 |
| `suggested_actions` | `actions[]` (label, description, action_type, query) | BA-019 |

### Notes for Go ProxyPythonSSE

- **`full_content`** field on `done` event: Python-side extension — Go can use this instead of accumulating content tokens. Field is optional (exclude_none in JSON), so Go's existing SSEDone struct will silently ignore it unless you add the field.
- **Heartbeat**: Python does NOT send heartbeats — Go manages heartbeat independently (15s ticker in Go handler).
- **Timeout**: Python enforces `stream_timeout=300s` internally and emits `error(STREAM_TIMEOUT)` if exceeded. Go should also have its own 5min timeout.
- **Error codes**: `SCHEMA_FETCH_FAILED` (retryable), `INTENT_PARSE_FAILED` (not retryable), `SQL_GENERATION_FAILED` (not retryable), `QUERY_EXECUTION_FAILED` (retryable), `STREAM_TIMEOUT` (retryable), `INTERNAL_ERROR` (retryable).

---

## 2. BA-021: OAuth Token Propagation — READY

### What Python does

Go API sends `Authorization: Bearer <resolved_token>` in requests to Python. Python extracts the token from inbound requests and forwards it when calling back to Go API (`/api/v1/ai/request`, `/api/v1/ai-queries`, etc.).

**Token priority in Python's AIClient**: `bearer_token` param > `default_bearer_token` (from inbound request) > `api_key` (from config).

### What Go needs to do

When calling Python's `/api/v1/ai/stream`, include the resolved auth token:
```go
req.Header.Set("Authorization", "Bearer " + resolvedToken)
```

Python will use that same token for all callbacks to Go API during the stream. This means Go's audit trail will correctly attribute AI calls to the OAuth token or API key that was active.

---

## 3. BA-021: Embedding Endpoint — READY

Python exposes `POST http://localhost:8081/api/v1/embeddings` for local embedding generation.

### Request Contract

```
POST /api/v1/embeddings
Content-Type: application/json
Authorization: Bearer <token>   ← required, returns 401 without it

Body:
{
  "texts": ["text to embed", "another text"],   ← 1-64 items, 422 if empty or >64
  "model": "all-MiniLM-L6-v2"                   ← optional, defaults to config
}
```

### Response

```json
{
  "embeddings": [[0.012, -0.034, ...], [0.056, ...]],   // 384-dim vectors
  "model": "all-MiniLM-L6-v2",
  "dimensions": 384
}
```

### Notes for Go EmbeddingGenerator (G15)

- Call this endpoint when `ai.embedding_provider = "local"`.
- Vectors are **L2-normalized** (unit length) — suitable for cosine similarity.
- **384 dimensions** — must match pgvector column config in BA-020.
- First request is slow (~5s) due to lazy model loading. Subsequent requests are fast (~50ms per batch).
- Max batch size: 64 texts per request.
- Fallback chain (`claude_oauth → openai → local → error`) should be managed in Go's selector, NOT in Python.

---

## 4. Bug Fix: Intent Parse Empty Response

**Deployed**: 2026-04-29 (commit `baca818`)

Intent parser now retries once on empty/invalid AI response. Previously, empty AI response caused `json.loads("")` crash → `INTENT_PARSE_FAILED` for all chat messages.

**Go team action**: If AI provider consistently returns empty responses, investigate provider config (API key validity, rate limits, model availability). Python is now resilient to transient failures but can't fix a permanently broken provider.

---

## 5. Docker

Python images need rebuild to include new dependencies (sentence-transformers ~500MB). Run:
```bash
docker compose build indexer worker
```
