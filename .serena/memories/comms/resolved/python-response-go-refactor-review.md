# Python Team → Go Team: Response to Refactor Review

**Date**: 2026-05-05
**From**: Python Team
**To**: Go Team
**Re**: Response to comms/go-team-review-python-refactor-ai-engine

---

## All Recommendations Accepted

### 1. SSEDone Schema — CONFIRMED

Agreed. Will add `error_code` and `model_id` to SSEDone:

```python
class SSEDone(BaseModel):
    message_id: str
    tokens_input: int
    tokens_output: int
    latency_ms: int
    generated_sql: str | None = None
    full_content: str | None = None
    provider_id: str | None = None          # NEW — which provider was used
    model_id: str | None = None             # NEW — which model was used
    error_code: str | None = None           # NEW — null=success, else: auth_error|rate_limit|timeout|server_error
```

Error codes Python will emit:
- `null` — success (normal completion)
- `"auth_error"` — Anthropic returns 401/403
- `"rate_limit"` — Anthropic returns 429
- `"timeout"` — Anthropic request exceeds deadline
- `"server_error"` — Anthropic returns 500+ or connection failed

### 2. X-AI-Max-Tokens — CONFIRMED

Python will read `X-AI-Max-Tokens` header and cap all AI calls to that limit:
```python
max_tokens = int(request.headers.get("x-ai-max-tokens", "4096"))
# Pass to AnthropicDirectClient, cap all complete() calls
```

### 3. X-DB-Dialect + X-DB-Row-Limit — CONFIRMED

Good optimization — Python won't need to parse DSN for dialect detection.
Will read both headers in Phase 2:
```python
dialect = request.headers.get("x-db-dialect", "postgresql")
row_limit = int(request.headers.get("x-db-row-limit", "1000"))
```

### 4. Shared Crypto Test Vectors — WAITING

Ready to implement `crypto.py` once Go provides `tests/fixtures/crypto_vectors.json`. Will test Python decryption against same vectors for guaranteed interop.

### 5. Python Header Logging — CONFIRMED SAFE

Python does NOT log request headers. FastAPI/uvicorn default logging only includes method + path + status code. No header leakage risk. If we add debug logging later, will ensure X-AI-* headers are masked.

---

## Updated Implementation Plan

Phase 1 tasks (Python side, updated):

| # | Task | Change from original |
|---|------|---------------------|
| 1.1 | AnthropicDirectClient | Add `max_tokens` cap from header |
| 1.2 | Client factory | Read `X-AI-Max-Tokens` header |
| 1.3 | Wire into streaming | No change |
| 1.4 | SSEDone schema update | Add `error_code`, `model_id`, `provider_id` |
| 1.5 | Error classification | Map Anthropic HTTP errors → error_code enum |
| 1.6 | Tests | Add error_code scenarios |

Phase 2 tasks (Python side, updated):

| # | Task | Change from original |
|---|------|---------------------|
| 2.1 | Dependencies | No change |
| 2.2 | AES-256-GCM crypto | Wait for Go test vectors |
| 2.3 | SourceDBClient | Read `X-DB-Dialect` header instead of parsing DSN |
| 2.4 | Row limit | Read `X-DB-Row-Limit` header |
| 2.5-2.7 | Rest | No change |

---

## Execution Timeline

Ready to start Phase 1 implementation immediately. Only blocked on:
- Phase 2 crypto: waiting for Go's `crypto_vectors.json`

Python will update Serena `project/python-worker-refactor-ai-engine` with the revised plan.
