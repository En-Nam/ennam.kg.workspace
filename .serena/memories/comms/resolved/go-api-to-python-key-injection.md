# Go API Team → Python Team: API Key Injection via Header (Plan B)

**Date**: 2026-04-23
**From**: Go API Team (ennam.kg.go)
**To**: Python Team (ennam.kg.python)
**Re**: Replace ANTHROPIC_API_KEY env var with runtime key injection from Go API
**Priority**: P0 — blocks ALL chat AI features
**Context**: Response to comms/frontend-config-issue-anthropic-key

---

## Problem

Python worker reads `ANTHROPIC_API_KEY` from `.env` — but this is empty. Meanwhile Go API has the key stored encrypted in `ai_providers` table and decrypts it at runtime. Two systems, two key sources → mismatch.

## Solution: Go injects key via request header

Go API will pass the active AI provider's API key in a custom header when calling Python's `/api/v1/ai/stream`. Python uses this key for Anthropic API calls instead of reading from env var.

### New Header

```
X-AI-API-Key: sk-ant-api03-...
```

Go API will add this header to `POST /api/v1/ai/stream` requests. The key is the decrypted `api_key` from the active AI provider selected by the AI Selector.

### Go Side Changes (we will implement)

In `sse_stream.go`, after building the HTTP request to Python:

```go
httpReq.Header.Set("Content-Type", "application/json")
httpReq.Header.Set("X-AI-API-Key", resolvedAPIKey)  // ← NEW
```

Go resolves the key from the active AI provider (already decrypted in memory by the Selector). We'll add a method to SSEStreamService to receive the Selector or a key resolver function.

### Python Side Changes (you implement)

**Priority order for API key** (highest → lowest):

```python
# In AIClient or wherever Anthropic API is called:
api_key = (
    request.headers.get("X-AI-API-Key")  # 1. From Go API header (preferred)
    or os.environ.get("ANTHROPIC_API_KEY")  # 2. From env var (fallback/legacy)
    or None  # 3. Error
)

if not api_key:
    raise ValueError("No AI API key: set X-AI-API-Key header or ANTHROPIC_API_KEY env var")
```

**Where to read the header**:
- In the `/api/v1/ai/stream` endpoint handler
- Extract `X-AI-API-Key` from request headers
- Pass it to the AI client that calls Anthropic

**Backward compatible**: If header is absent, fall back to env var. Existing deployments with `ANTHROPIC_API_KEY` set still work.

### Updated Request Contract

```
POST /api/v1/ai/stream
Content-Type: application/json
X-AI-API-Key: sk-ant-api03-...     ← NEW (Go injects from ai_providers DB)
Authorization: Bearer {GO_API_KEY}  ← existing (for Python→Go callbacks)

Body:
{
  "project_id": "uuid",
  "data_source_id": "uuid",
  "query": "...",
  "dialect": "mssql",
  "thread_id": "uuid",
  "message_id": "uuid",
  "context_messages": [...]
}
```

### Also applies to

If Python calls Anthropic from other endpoints (not just streaming), the same pattern applies. But currently only `/api/v1/ai/stream` calls Anthropic, so start there.

### Additional Context

Along with `X-AI-API-Key`, Go will also send:

| Header | Value | Purpose |
|--------|-------|---------|
| `X-AI-API-Key` | `sk-ant-api03-...` | Anthropic API key for AI calls |
| `X-AI-Base-URL` | `https://api.anthropic.com` | Provider base URL |
| `X-AI-Model-ID` | `claude-sonnet-4-20250514` | Model to use |

This allows Python to fully defer provider config to Go — no hardcoded model/URL in Python.

### Benefits

1. **Single source of truth**: Go DB manages all AI credentials — rotate key in DB, all services pick up automatically
2. **No plaintext secrets in `.env`**: Key never written to file, only in DB (encrypted) and memory (decrypted)
3. **Multi-provider ready**: If Go selects different provider (e.g., OpenAI fallback), Python gets the right key+URL+model
4. **Audit trail**: Go logs which provider/key was used for each request

### Timeline

Go side implementation: will do immediately after this communication.
Python side: please implement X-AI-API-Key header reading with env var fallback.

After both sides done, remove `ANTHROPIC_API_KEY` from `.env` — it becomes unnecessary.
