# Go API Server State — 2026-05-12

## Latest Commit
`7ee1f3d` on `main` — feat(streaming): credential injection + circuit breaker feedback for AI chat

## Key Features Implemented (Phase 1 + Streaming)

### Core API
- Full CRUD for projects, nodes, edges, search, traversal
- API key auth with role-based access (admin, developer, agent)
- PostgreSQL with trigram + tsvector full-text search
- AES-GCM encryption for sensitive credentials (AI keys, DSN)

### AI Chat Streaming (Phase 4)
- SSE proxy: Go → Python worker → Anthropic API
- **Credential vault pattern**: Go injects AI API key + model via `X-Ai-*` headers per-request
- **DB credential injection**: Go resolves data source DSN and injects via `X-Db-*` headers
- `AICredentialProvider` (`internal/service/credential_provider.go`): selects best provider, decrypts key, builds headers
- `DataSourceResolver` (`internal/service/ds_resolver.go`): resolves DSN from data_source_id
- `BlockAccumulator` (`internal/service/sse_stream.go`): tracks response blocks, handles content tokens within block boundaries
- Circuit breaker feedback: Python reports success/failure in SSEDone → Go updates `ai.Selector`
- AI usage logging from streaming to `ai_usage_logs` table
- Full assistant message persistence: content text + response blocks + aggregation metadata
- `IsSensitiveHeader` guard prevents credential leakage in logs

### Search
- POST `/api/v1/search` returns `{"results": [...], "total_count": N}`
- Node types: decision, concept, requirement, task, architecture, discovery
- Architecture nodes with `node_subtype=schema_table` store indexed DB schema
- Relevance scoring returned as float `rank` field

## Known Issues
- `node_test.go` and `apikey_test.go` have pre-existing duplicate declaration compile errors (not related to streaming work)
- CloudWatch metrics publishing fails in local Docker (no IMDS role) — harmless
- `cmd/kg-server/` is in `.gitignore` (binary output dir) but `main.go` was force-added

## Architecture Notes
- Python is **stateless** — receives all credentials via request headers, never stores them
- Go is the **credential vault** — only Go has access to encryption key and DB stores
- SSE event flow: Python emits `block_start → content (with block_id) → block_content → block_end → done`
- Go accumulates blocks via `BlockAccumulator` and persists on `done` event
- If Python errors, it must still emit `done` event for Go to persist the error message

## Agentic AI Support (uncommitted, 2026-05-12)
- Migration 000044: `agent_tool_calls` + `clarification_sessions` tables, 6 columns on `thread_messages`
- ThreadMessage: 6 agentic fields (agent_tier, agent_iterations, agent_tools_used, agent_total_tokens, clarification_session_id, clarification_status)
- SSE: `agentTimeout()` (5/10min), `pythonEndpoint()` routes to `/api/v1/agentic/stream` when tier set
- Handler: `HandleClarification()` POST endpoint at `/api/v1/ai/clarification`
- Store: `UpdateAgentMetadata()` persists agentic fields after agent completion

## Files of Interest
| File | Purpose |
|------|---------|
| `cmd/kg-server/main.go` | Server bootstrap, wiring |
| `internal/handler/ai_stream.go` | SSE streaming endpoint + usage logging + HandleClarification |
| `internal/service/sse_stream.go` | SSE proxy + BlockAccumulator + agentic routing |
| `internal/service/credential_provider.go` | AI key injection |
| `internal/service/ds_resolver.go` | DB DSN injection |
| `internal/ai/selector.go` | Provider selection + circuit breaker |
| `internal/handler/search.go` | KG search endpoint |
| `internal/models/sse.go` | SSE event structs (BlockID field on SSEContent) |
| `internal/store/thread_message.go` | ThreadMessage CRUD + UpdateAgentMetadata |
