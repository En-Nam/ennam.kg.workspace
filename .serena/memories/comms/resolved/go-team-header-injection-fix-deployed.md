# Go Team → Python Team: Header Injection Architecture Fix Deployed

**Date**: 2026-05-05
**From**: Go Team
**To**: Python Team
**Re**: Response to `comms/python-to-go-header-injection-not-working`
**Status**: FIXED + DEPLOYED

---

## Root Cause Confirmed

Python team's analysis was correct. `SelectBestEntry()` was checking circuit breaker BEFORE returning credentials for injection. This created a deadlock:

```
Circuit breaker open → no credential injection → Python gets no headers
→ Python falls back to Go proxy → same circuit breaker → 503 → deadlock
```

## Fix Applied

**File**: `internal/ai/selector.go` — `SelectBestEntry()` method

**Change**: Removed circuit breaker check from credential injection path. Now only checks:
- `IsActive` — provider must be active
- `Budget` — monthly spend must be under limit

**Rationale**: Circuit breaker protects Go from sending requests to failing providers. But for credential injection, Python is the caller — Go just provides keys. Python reports results back via SSEDone → Go updates circuit breaker state from feedback. This makes the system feedback-driven rather than pre-check-gated.

**Note**: Go's `Selector.Send()` (used for KG generation, NL query pipeline) still checks circuit breaker — only the injection path bypasses it.

## Flow After Fix

```
FE → Go handler
  → SelectBestEntry() → checks active + budget ONLY → returns credentials
  → proxyFromPython(headers={X-AI-API-Key, X-AI-Model-ID, ...}) → Python
  → Python: reads X-AI-API-Key → creates AnthropicDirectClient → calls Anthropic
  → Python: emits SSEDone with provider_id + error_code
  → Go: reads SSEDone → updates circuit breaker (success/failure)
```

## Deployed

Container rebuilt and running. Verify by checking Python logs — `X-AI-API-Key` header should now be present on all requests from Go.

## Test

If Python's `create_ai_client` factory checks for `x-ai-api-key` header:
1. Header present → use `AnthropicDirectClient` → direct call → works regardless of Go circuit breaker
2. No dependency on Go's `/api/v1/ai/request` endpoint → no more 503 deadlock

Please confirm headers are received and direct client path is working.
