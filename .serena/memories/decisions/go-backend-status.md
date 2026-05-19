# Go Backend Status (ennam.kg.go)

**Updated**: 2026-04-21 (ALL 5 PHASES COMPLETE)

## Summary
- **Phase 1**: Core KG — nodes, edges, sessions, validation gates, MCP bridge
- **Phase 2**: Data Pipeline — data sources, KG generation, AI providers, NL query, sync, benchmarks
- **Phase 3**: Platform Admin — users, auth, projects, members, API keys, activity feed, settings
- **Phase 4**: AI Query UX — conversational threads, SSE streaming, rich response, favorites, insights

## Metrics
- ~130+ REST endpoints + 1 SSE + 2 real-time (WebSocket + SSE)
- 41 migrations (001-041)
- 21 internal packages
- 6 Docker services running

## Phase 5 BA-021 — COMPLETE (2026-04-21)
Claude OAuth integration fully implemented:
- OAuth token store (AES-256-GCM encrypted), refresh worker (60s cycle, 5min proactive)
- POST /auth/claude/import-token (credentials JSON + authorization code methods)
- GET /auth/claude/status, POST /auth/claude/disconnect
- Anthropic provider: OAuth Bearer header + API key fallback
- Selector: auto-injects OAuth token before each AI request
- Health check: OAuth injection for claude_max providers
- Error diagnostics: API error bodies captured (up to 1KB), 401/403 → ErrCodeAuth

## QA Status (2026-04-21)
- 20/20 non-AI features PASS
- AI features: verified working (health check, direct request, SSE stream, schema extraction 39/39)

## MSSQL Support (2026-04-22)
- Strategy Pattern: SchemaQuerier interface with PostgresQuerier + MSSQLQuerier
- 6 new files, 4 modified files, migration 043
- MSSQL queries use sys.* catalog views, @p1/@p2 params, sys.extended_properties for comments
- FE integration doc: Serena memory `project/fe-action-required-mssql-datasource`

## Phase 4 Key Architecture
- Go = SSE proxy, Python = AI brain
- 9 SSE event types (progress, content, error, done, format_metadata, block_start/content/end, suggested_actions)
- Heartbeat 15s, timeout 5min, concurrent limit 3
- BlockAccumulator for rich response persistence
- Insight/action capture from stream
