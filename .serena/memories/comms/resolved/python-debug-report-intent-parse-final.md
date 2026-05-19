# Python Team: Debug Report — Intent Parse Failure Root Cause Analysis

**Date**: 2026-05-05
**From**: Python Team
**To**: Go Team + FE Team
**Status**: Python fix deployed, Go circuit breaker blocking

---

## Two Root Causes Found (layered)

### Issue 1: Markdown Code Fences (Python — FIXED)

**Root cause**: Anthropic model wraps JSON response in ` ```json ... ``` ` markdown fences.
**Evidence**: Go `/api/v1/ai/request` returns `{"content": "```json\n{...}\n```"}` — valid AI response, but wrapped.
**Fix**: `_strip_markdown_fences()` in `intent_parser.py` extracts JSON from fences before `json.loads()`.
**Status**: Merged (`bd2df99`), container rebuilt and deployed.

### Issue 2: Go Circuit Breaker Open (Go — NEEDS ACTION)

**Root cause**: Previous failed AI attempts (from Issue 1) tripped the circuit breaker on provider `ennam-kg` (ID: `584aa35d-8f7e-44d1-805a-58174513cbca`). Now ALL AI requests get 503 immediately without reaching Anthropic.
**Evidence**: 
- `POST /api/v1/ai/request` → `{"error": "Service Unavailable", "message": "ai: all providers unavailable: [...ennam-kg request_failed]"}`
- Health check passes: `POST /ai-providers/{id}/health-check` → `{"healthy": true}`
- But circuit breaker remains open for actual requests
- Server restart does NOT reset it
**Impact**: Python's markdown fix can't be verified because Go won't forward AI requests.

---

## Current Data Flow

```
FE → Go (POST /ai-query/stream) 
  → Go calls Python (POST /ai/stream) [NO X-AI-* headers — Go falls through to proxy path]
    → Python receives request
    → Python calls Go (POST /ai/request) for AI [using GO_API_KEY auth — works]
      → Go circuit breaker BLOCKS → returns 503
    → Python gets 503 → emits AI_PROVIDER_ERROR SSE event
```

---

## Go Team Actions Required

1. **Reset circuit breaker** — the `request_failed` state needs clearing. Options:
   - Reset in DB if persisted (check `ai_provider_health` table)
   - Increase circuit breaker timeout/threshold
   - Manually reset via code/endpoint

2. **Confirm X-AI-* header injection** — Go startup shows "AI credential injection enabled for streaming" but headers don't appear to reach Python. If headers were present, Python would use direct Anthropic path (bypassing Go's circuit breaker entirely).

3. **Test direct AI call from Go** — after circuit breaker reset:
   ```bash
   curl -X POST http://localhost:8080/api/v1/ai/request \
     -H "Authorization: Bearer ennam_kg_dev_000000000000000000000000" \
     -H "Content-Type: application/json" \
     -d '{"messages":[{"role":"user","content":"say hello"}],"max_tokens":10}'
   ```

---

## Python Team Status

| Item | Status |
|------|--------|
| Markdown fence stripping | FIXED + deployed |
| Retry on empty/invalid JSON | FIXED (from earlier) |
| Direct Anthropic client (Phase 1) | READY — waiting for X-AI-* headers |
| Direct DB execution (Phase 2) | READY — waiting for X-DB-* headers |
| Container image | LATEST (all fixes included) |

**Python side is complete.** Awaiting Go circuit breaker reset to verify E2E.
