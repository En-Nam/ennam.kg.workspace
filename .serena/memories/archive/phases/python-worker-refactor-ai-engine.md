# Refactor Python Worker: From Middleman Proxy to AI Engine

**Created**: 2026-04-29
**Updated**: 2026-05-05
**Status**: ALL PHASES COMPLETE — Phase 1 + Phase 2 both merged to main, pushed.
**Commits**: Phase 1 (5) + Phase 2 (4) + Bug fixes (3) + KG search + tool_use (1) = 13 total
**Final architecture doc**: `project/python-worker-architecture-final`
**Go Review**: comms/go-team-review-python-refactor-ai-engine (all recommendations accepted)
**Priority**: HIGH — eliminates 8 unnecessary network round-trips per chat stream

## Context

Python worker trong chat flow hiện tại là **proxy of proxy** — nhận request từ Go rồi gọi ngược Go cho mọi AI call (4 lần/stream) và query execution. Go lại gọi Anthropic. Tổng cộng 8 extra network round-trips per stream, Python gần như không thêm value nào ngoài `generate_sql()`.

Refactor để Python trở thành **AI engine thực sự**: gọi Anthropic trực tiếp, execute SQL trên source DB trực tiếp. Go trở thành API gateway thuần túy (auth, persistence, credential injection).

## Target Architecture

```
FE → Go (API gateway: auth, thread persistence, credential injection via headers)
     → Python (AI engine: direct Anthropic calls, direct source DB queries, SSE streaming)
     → FE
```

## Approach: Incremental (2 phases)

### Phase 1: Python Calls Anthropic Directly

Go injects headers: `X-AI-API-Key`, `X-AI-Base-URL`, `X-AI-Model-ID`, `X-AI-Provider-ID`
Python reads → creates Anthropic SDK client → gọi trực tiếp.
If headers absent → fallback về Go proxy (backward compatible).

**Tasks:**
1. Create `AnthropicDirectClient` (same interface as AIClient: `complete(AIRequest) → AIResponse`)
2. Create client factory (route by header presence, read `X-AI-Max-Tokens`)
3. Wire factory into streaming endpoint (~3 line change)
4. Update SSEDone: add `provider_id`, `model_id`, `error_code` fields
5. Error classification: map Anthropic HTTP errors → error_code enum (auth_error|rate_limit|timeout|server_error)
6. Tests (mock Anthropic SDK, error scenarios)
7. Go team: inject headers in `sse_stream.go:proxyFromPython()` ← Go confirmed ready

**Additional headers from Go (confirmed):**
- `X-AI-API-Key` — decrypted provider key
- `X-AI-Base-URL` — provider endpoint
- `X-AI-Model-ID` — model to use
- `X-AI-Provider-ID` — for usage attribution
- `X-AI-Max-Tokens` — budget cap per request

**New files:**
- `src/ennam_kg/ai_client/direct_client.py`
- `src/ennam_kg/ai_client/factory.py`
- `tests/test_ai_client/test_direct_client.py`
- `tests/test_ai_client/test_factory.py`

### Phase 2: Python Executes SQL on Source DBs

Go injects header: `X-DB-DSN` (base64-encoded encrypted connection string)
Python decrypts (AES-256-GCM, compatible with Go's crypto) → connects → executes SQL.
If header absent → fallback về `kg_client.submit_nl_query()`.

**Tasks:**
1. Add deps: `asyncpg>=0.30`, `pymssql>=2.3`, `cryptography>=44`
2. Create AES-256-GCM decryption (compatible with Go's `internal/crypto/aes.go`)
   - BLOCKED: waiting for Go's `tests/fixtures/crypto_vectors.json`
3. Create `SourceDBClient` (asyncpg for PG, pymssql for MSSQL)
   - Read `X-DB-Dialect` header for driver selection (no DSN parsing needed)
   - Read `X-DB-Row-Limit` header (default 1000, per-project configurable)
4. Engine integration (db_client param, direct execution when present)
5. Endpoint wiring (read X-DB-DSN + X-DB-Dialect + X-DB-Row-Limit headers)
6. Tests (mock drivers, cross-language crypto test vectors from Go)
7. Go team: inject X-DB-DSN + X-DB-Dialect + X-DB-Row-Limit ← Go confirmed ready

**Additional Phase 2 headers from Go (confirmed):**
- `X-DB-DSN` — base64(raw encrypted connection string from DB)
- `X-DB-Dialect` — "postgresql" | "mssql"
- `X-DB-Row-Limit` — integer (default 1000)

**New files:**
- `src/ennam_kg/crypto.py`
- `src/ennam_kg/db_client/__init__.py`
- `src/ennam_kg/db_client/client.py`
- `tests/test_crypto.py`
- `tests/test_db_client/test_client.py`

## Key Design Decisions

1. **Same interface, different impl**: `AnthropicDirectClient` duck-types `AIClient.complete()` — zero changes needed in intent_parser, format_detector, insight_generator, streaming engine
2. **Header-based routing**: backward compatible — if Go hasn't deployed headers yet, Python falls back automatically
3. **Per-request clients**: Anthropic client + DB connection created per stream request, closed after. No pooling needed for ad-hoc user queries
4. **Go manages credentials**: Python never stores keys. Go injects decrypted key (AI) or encrypted DSN (DB) per-request via internal network headers
5. **Usage reporting via SSEDone**: Go reads `provider_id` + `tokens_input/output` from done event → logs to `ai_usage_logs`

## Dependencies Between Teams

| Phase | Python Team | Go Team |
|-------|------------|---------|
| 1 | Implement direct_client + factory | Inject X-AI-* headers in sse_stream.go |
| 2 | Implement crypto + db_client | Inject X-DB-DSN header |

Both sides backward compatible — can be deployed independently in any order.

## Verification

- Phase 1: `uv run pytest tests/test_ai_client/ tests/test_streaming/ -v` + manual test with/without headers
- Phase 2: `uv run pytest tests/test_crypto.py tests/test_db_client/ tests/test_streaming/ -v` + manual test with/without DSN header
