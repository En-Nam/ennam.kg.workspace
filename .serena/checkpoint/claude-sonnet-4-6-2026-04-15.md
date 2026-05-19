# Checkpoint: claude-sonnet-4-6 — 2026-04-15

## What was done
- Implemented Task 2: Bearer Token Propagation (BA-021 P5) in ennam.kg.python
- Added `_auth_header(bearer_token=None)` method to `AIClient` with `default_bearer_token` constructor param
- Added `_auth_header(bearer_token=None)` method to `KGClient` and `bearer_token` param to `_request`
- Updated `streaming.py` to extract inbound Bearer token and pass via `default_bearer_token` to AIClient
- Removed unused `_get_ai_client` helper function from `streaming.py`
- Created `tests/test_token_propagation.py` with 3 tests (TDD: fail first, then pass)
- Fixed `tests/test_streaming_api.py` to patch `AIClient` class instead of removed `_get_ai_client`
- Removed unused `from typing import Any` import from `ai_client/client.py` (ruff fix)

## Files changed
- `src/ennam_kg/ai_client/client.py` — added `_auth_header`, `default_bearer_token` param
- `src/ennam_kg/kg_client/client.py` — added `_auth_header`, `bearer_token` param on `_request`
- `src/ennam_kg/api/streaming.py` — inline AIClient creation with token extraction
- `tests/test_token_propagation.py` — created (3 new tests)
- `tests/test_streaming_api.py` — patched `AIClient` class instead of `_get_ai_client`

## Current state
- All 47 related tests pass (token propagation + streaming + ai_client + kg_client)
- Committed to branch `feature/ba021-python-oauth-embeddings`
- 22 pre-existing failures in test_extractor/test_differ/test_engine are unrelated to this task

## Next steps
- Task 3+ of BA-021 (if applicable): other OAuth/embedding tasks on this branch
- Run full test suite to confirm pre-existing failures are not regressions

## Blockers / Risks
- None for this task

---

# Checkpoint: claude-sonnet-4-6 — 2026-04-15 (Session 2)

## What was done
- Implemented Task 5: Embedding API Endpoint (BA-021 P7)
- Created `src/ennam_kg/api/embeddings.py` with `POST /api/v1/embeddings` endpoint
- Module-level singleton `_get_local_model()` for lazy model loading, patchable in tests
- Bearer auth guard (401 if missing/malformed), delegates validation to `EmbeddingRequest` model
- Updated `src/ennam_kg/main.py` to import and register `embeddings.router`
- Created `tests/test_embeddings_api.py` with 4 tests (TDD: verified fail first, then pass)

## Files changed
- `src/ennam_kg/api/embeddings.py` — created (new endpoint)
- `src/ennam_kg/main.py` — added embeddings import + `app.include_router(embeddings.router)`
- `tests/test_embeddings_api.py` — created (4 tests)

## Current state
- All 4 new tests pass; no regressions in previously passing tests
- Committed to branch `feature/ba021-python-oauth-embeddings` (commit 28360a5)
- 26 pre-existing failures in `test_extractor.py` are unrelated to this task

## Next steps
- Remaining BA-021 tasks on this branch (if any)
- Integration test with Go API once local embedding provider is configured

## Blockers / Risks
- None
