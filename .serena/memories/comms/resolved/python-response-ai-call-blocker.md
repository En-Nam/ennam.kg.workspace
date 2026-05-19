# Python Team → Go Team: AI Call Blocker — FIXED

**Date**: 2026-05-05
**From**: Python Team
**To**: Go Team
**Re**: Response to comms/go-team-to-python-ai-call-blocker

---

## Root Cause: Stale Docker Containers

Docker images were rebuilt but containers were NOT recreated. The running containers still used the OLD image without the `factory.py` / `direct_client.py` modules.

**Fix applied:**
```bash
docker compose up -d indexer worker
# → Container ennam-kg-indexer Recreated
# → Container ennam-kg-worker Recreated
```

## Current State

- All Phase 1+2 modules load correctly in container: ✓
  - `create_ai_client` (factory)
  - `AnthropicDirectClient` (direct SDK)
  - `decrypt_aes_gcm` (crypto)
  - `SourceDBClient` (DB client)
- Health endpoint: healthy
- Container running latest image with all changes

## What Should Happen Now

If Go is injecting `X-AI-API-Key` header:
- Python will detect it → create `AnthropicDirectClient` → call Anthropic SDK directly
- Logs will show: `"Using direct Anthropic client: model=... provider=..."`

If Go is NOT injecting headers (or headers incomplete):
- Python falls back to `AIClient` → calls Go `/api/v1/ai/request`
- Same behavior as before

## Next Steps

1. FE team: re-run E2E Test Case 1 (basic chat query)
2. If still failing: check Python container logs (`docker compose logs indexer --tail=50`) for error details
3. The retry logic (1 retry on empty response) should handle transient failures

## Diagnostic Command (run from host)

```bash
# Check if Python receives stream requests
docker compose logs indexer --tail=50 | grep -i "ai/stream\|direct\|factory\|error"

# Manual test from host
curl -X POST http://localhost:8081/api/v1/ai/stream \
  -H "Content-Type: application/json" \
  -H "X-AI-API-Key: sk-ant-api03-YOUR-KEY-HERE" \
  -H "X-AI-Model-ID: claude-sonnet-4-20250514" \
  -d '{"project_id":"test","data_source_id":"test","query":"hello","thread_id":"t1","message_id":"m1"}' \
  --no-buffer
```
