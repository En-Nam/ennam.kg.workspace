# Python Worker — Service State

**Last updated**: 2026-05-13
**Latest commit**: `9022b7a` on `main` — e2e tests merged into repo

## Role

Python is the **stateless AI compute engine**. All credentials (AI API key, DB DSN)
injected via headers per-request by Go. Python never stores secrets.

## Package Structure

```
src/ennam_kg/
├── streaming/       # SSE streaming engine (Phase 4)
├── ai_client/       # Go API AI abstraction adapter
├── kg_generator/    # KG generation from schema metadata
├── nl_query/        # NL-to-SQL pipeline
├── benchmark/       # Accuracy testing
├── db_client/       # Direct query on source databases
├── embeddings/      # Vector embedding generation
├── indexer/         # Code symbol extraction
├── kg_client/       # HTTP client to Go API
├── parsers/         # Multi-language code parsers
├── summarizer/      # Code summarization
├── queue/           # Redis consumer
├── agentic/         # Agentic AI engine (iterative tool-calling)
├── api/             # FastAPI routers
├── config.py        # pydantic-settings
├── worker.py        # Queue message dispatcher
└── main.py          # FastAPI app entry
```

## Key Modules

### Streaming Engine (`streaming/`)
- Block-ordered SSE: `block_start → content tokens (with block_id) → block_content → block_end → done`
- Empty result short-circuit: skips 3 LLM calls (~11s saved) when 0 rows
- All error paths emit `done` event for Go-side persistence

### NL Query (`nl_query/`)
- Intent parsing with LLM tool_use, case-insensitive table validation
- SQL generation: PostgreSQL and MSSQL dialects (TOP vs LIMIT)

### Agentic Engine (`agentic/`) — NEW 2026-05-12, hardened 2026-05-13
- FSM-based agent loop: EXPLORE → PLAN → EXECUTE → SYNTHESIZE
- 7 tools: search_kg, get_neighbors, get_table_schema, execute_sql, list_datasources, ask_clarification, traverse_path
- Tiered execution: Quick (3 iterations, 30K tokens) vs Deep (12 iterations, 100K tokens)
- LoopGuard: blocks duplicate calls, node saturation (3+), budget exceeded
- Clarification pause/resume via Redis state store (600s TTL, one-time getdel)
- SQL security: DDL/DML blocking, SELECT/WITH enforcement, 5000 char limit
- Endpoint: POST /api/v1/agentic/stream (SSE)
- 63 tests, all passing
- **Schema truncation**: `_compact_schema()` caps `get_table_schema` output at 60 tables with columns (~5.8k tokens vs 276k raw)
- **UUID fallback**: `_resolve_ds_id()` validates agent-provided data_source_id; falls back to request context if not a valid UUID
- **Rate limit retry**: `anthropic.RateLimitError` → 60s backoff, max 1 retry in engine loop
- **Model**: `claude-haiku-4-5-20251001` (switched from Sonnet for test env — faster + cheaper)
- **Prompt style**: Numbered explicit rules in `_IDENTITY` (Haiku requires step-by-step; Sonnet could handle conditional)

### KG Client (`kg_client/`)
- Critical fix: `search()` transforms Go's `{"results": [...]}` to FlatResponse

## Architecture Notes
- **AIClient adapter**: Python calls `POST /api/v1/ai/request` on Go — never calls AI providers directly
- **Worker dispatch**: Single process handles ALL message types via `msg_type` switch
- **SQL generation**: Pure Python, no ORM. Supports `$N` (postgres) and `?` (mysql) placeholders
- **Scorer**: Deterministic, no AI. Exact=1.0, semantic=0.95, partial=overlap, failure=0.0

## Known Issues
- Pre-existing test failures in `test_differ.py`, `test_extractor.py`, `test_benchmark/`
- `test_streaming_api.py` has AsyncMock coroutine issue (pre-existing)
- 22 Phase 1 test failures: old tests use `type` vs `node_type`, `edge_type` vs `relationship`
- Dart parser is a stub — needs `tree-sitter-dart` on PyPI

## Recent Fixes (2026-05-13)
- **Schema truncation**: `_compact_schema()` in `tools.py` — 276k → 5.8k tokens for 297-table C4K Staging MSSQL
- **UUID fallback**: `_resolve_ds_id()` in `tools.py` — handles LLM passing data source name instead of UUID
- **Rate limit retry**: `engine.py` — 60s backoff on `anthropic.RateLimitError`, max 1 retry
- **Haiku prompt**: `prompts.py` `_IDENTITY` rewritten as numbered rules (conditional rules not reliable on Haiku)
- **Model switch**: DB record changed to `claude-haiku-4-5-20251001` (test env)

## Fixes (2026-05-11)
- **MSSQL charset**: Added `charset="UTF-8"` to `pymssql.connect()` in `db_client/client.py` — prevents cp1252 bytes in query results
- **Bytes decode**: Added defensive `decode("utf-8", errors="replace")` in `_execute_mssql()` after fetchmany — catches any remaining raw bytes
- **SSE encoder fallback**: Added `_sse_default_encoder` in `streaming/models.py` — prevents crash if bytes leak to JSON serialization
- **Docker env**: `docker-compose.yml` now passes `ENCRYPTION_KEY` to indexer+worker — required for X-DB-DSN decryption (direct DB execution)

## Test Layout (2026-05-13)

```
tests/
├── conftest.py            # Unit test fixtures (mocked — no server needed)
├── test_agentic/          # Agentic engine unit tests (63 tests)
├── test_*.py              # Other unit tests (parsers, indexer, streaming…)
└── e2e/                   # E2E tests (require live Docker stack)
    ├── conftest.py        # E2E fixtures: real httpx client + login session
    ├── test_api_smoke.py  # Layer 1: API-01..06 smoke tests
    ├── test_accuracy.py   # Layer 3: ACC-01..12 accuracy evaluation
    ├── helpers/           # auth.py, health.py, sse.py (SSE_VERBOSE)
    ├── browser_playbook.md  # Layer 2: Chrome DevTools MCP playbook
    └── run_tests.sh       # Full test runner
```

**Run unit tests** (no server needed):
```bash
uv run pytest                      # all unit tests
```

**Run e2e tests** (needs `docker compose up -d`):
```bash
SSE_VERBOSE=1 uv run pytest tests/e2e/test_api_smoke.py -v -s
uv run pytest tests/e2e/test_accuracy.py -v -s
tests/e2e/run_tests.sh --smoke-only
```

`pyproject.toml` dev deps include `pytest-timeout>=2.3`.
Markers declared: `smoke`, `accuracy`, `quick_tier`, `deep_tier`.

## Remaining Items
- Register AI provider: `scripts/register-ai-provider.sh <KEY>`
- Fix 22 pre-existing Phase 1 test failures (field name mismatch)
- Run Layer 3 accuracy tests (`test_accuracy.py`) — not yet executed
- Run Layer 2 browser tests via Chrome DevTools MCP
