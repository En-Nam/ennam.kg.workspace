# Python Worker Architecture — Final State (2026-05-05)

## Role

Python worker là **AI Engine** của hệ thống. Go API là **API Gateway** thuần túy.

```
FE → Go (auth, thread persistence, credential injection via headers)
     → Python (AI calls, DB queries, SSE streaming)
     → FE
```

## Key Architecture Decisions

### 1. Header-Based Credential Injection

Go inject credentials qua HTTP headers khi gọi Python:

| Header | Purpose |
|--------|---------|
| `X-AI-API-Key` | Anthropic API key (decrypted from DB) |
| `X-AI-Model-ID` | Model to use (e.g. claude-sonnet-4-20250514) |
| `X-AI-Provider-ID` | Provider UUID for usage attribution |
| `X-AI-Max-Tokens` | Budget cap per request |
| `X-AI-Base-URL` | Provider endpoint URL |
| `X-DB-DSN` | Base64(AES-256-GCM encrypted connection string) |
| `X-DB-Dialect` | "postgresql" or "mssql" |
| `X-DB-Row-Limit` | Max rows to return (default 1000) |

Python reads headers → creates per-request clients → calls Anthropic/DB directly.
If headers absent → falls back to Go proxy (backward compatible).

### 2. Client Factory Pattern

`create_ai_client(request)` in `ai_client/factory.py`:
- If `X-AI-API-Key` present → `AnthropicDirectClient` (calls Anthropic SDK)
- If absent → `AIClient` (calls Go `/api/v1/ai/request`)

Both implement same interface: `complete(AIRequest) → AIResponse`

### 3. KG-Based Schema Filtering

Instead of dumping all 314 tables into prompt:
1. Search Knowledge Graph: `POST /api/v1/search {query, node_types: ["architecture"]}`
2. KG returns relevant table nodes (matched by title + ai_description)
3. Filter metadata to only those tables (~10-15 instead of 314)
4. Fallback: top 20 tables if KG search fails

### 4. Anthropic tool_use for Structured Output

Intent parsing uses `tool_choice: {type: "tool", name: "output_query_plan"}` to FORCE model to output structured JSON matching the QueryPlan schema. Model cannot return plain text.

Tool schema defined in `nl_query/prompts.py:QUERY_PLAN_TOOL`.

### 5. AES-256-GCM Crypto Interop

Python decrypts connection strings encrypted by Go using same `KG_ENCRYPTION_KEY`.
Format: `nonce(12 bytes) || ciphertext || GCM tag(16 bytes)`.
Verified with shared test vectors from Go.

### 6. Error Feedback Loop

SSEDone event includes `provider_id`, `model_id`, `error_code` for Go's circuit breaker:
- `null` = success
- `auth_error` = 401 from Anthropic
- `rate_limit` = 429
- `timeout` = request exceeded deadline
- `server_error` = 500+ or connection failed

Go updates circuit breaker state based on this feedback.

## Module Map

```
src/ennam_kg/
├── ai_client/
│   ├── client.py           # AIClient — Go proxy (fallback)
│   ├── direct_client.py    # AnthropicDirectClient — calls SDK directly
│   ├── factory.py          # create_ai_client() — header-based routing
│   └── models.py           # AIRequest, AIResponse, AIUsage
├── api/
│   ├── streaming.py        # POST /api/v1/ai/stream — SSE endpoint
│   └── embeddings.py       # POST /api/v1/embeddings — local model
├── streaming/
│   ├── engine.py           # StreamingQueryEngine — 6-stage pipeline
│   ├── models.py           # 9 SSE event types
│   ├── format_detector.py  # AI-driven format selection
│   ├── block_composer.py   # Response block composition
│   ├── insight_generator.py # AI insights + suggested actions
│   └── prompts.py          # AI prompts + QUERY_PLAN_TOOL schema
├── nl_query/
│   ├── intent_parser.py    # parse_intent_with_usage() — tool_use
│   ├── sql_generator.py    # generate_sql(plan, dialect) — postgres/mssql
│   └── prompts.py          # get_intent_parsing_prompt()
├── db_client/
│   └── client.py           # SourceDBClient — asyncpg + pymssql
├── embeddings/
│   ├── local_model.py      # sentence-transformers all-MiniLM-L6-v2
│   └── models.py           # EmbeddingRequest/Response
├── crypto.py               # AES-256-GCM decryption (Go-compatible)
├── kg_client/              # Go API REST client
├── indexer/                # Code indexing pipeline (tree-sitter)
├── config.py               # Settings from env vars
├── main.py                 # FastAPI app
└── worker.py               # Redis queue consumer
```

## Streaming Pipeline (6 stages)

```
POST /api/v1/ai/stream
  Stage 1: KG search → find relevant tables → fetch filtered schema
  Stage 2: Intent parsing (tool_use forced JSON) → QueryPlan
  Stage 3: SQL generation (deterministic, postgres/mssql dialect)
  Stage 4: Query execution (direct DB or Go proxy fallback)
  Stage 5: Summary + format detection + block composition
  Stage 6: Insights + suggested actions
  → SSE events streamed progressively to Go → FE
```

## Common Debugging

| Symptom | Likely cause |
|---------|-------------|
| `INTENT_PARSE_FAILED` | AI not returning JSON → check tool_use response, verify headers |
| `AI_PROVIDER_ERROR` 503 | Go circuit breaker open → health-check provider, restart Go |
| `AI_PROVIDER_ERROR` 401 | API key invalid → check ai_providers table in Go DB |
| `SCHEMA_FETCH_FAILED` | Can't reach Go API → check GO_API_URL, network |
| `QUERY_EXECUTION_FAILED` | DB connection issue → check X-DB-DSN decryption, dialect |
| Empty KG search results | KG generation not run for this data source → trigger generate-kg |
