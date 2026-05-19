# Go Team: Circuit Breaker Reset — All Blockers Resolved

**Date**: 2026-05-05
**From**: Go Team
**To**: Python Team + FE Team
**Status**: RESOLVED — E2E ready for retest

---

## What Happened

1. **Python Issue 1** (markdown fences): Fixed by Python team (`_strip_markdown_fences()`)
2. **Go Issue 2** (circuit breaker open): Auto-resolved by container rebuild

Circuit breaker is **in-memory only** (not persisted in `ai_provider_health` table). When `kg-server` was rebuilt with new header injection code, fresh circuit breakers were created in closed state.

## Verified Working

```
POST /api/v1/ai/request → 200 OK
{
  "content": "Hello",
  "input_tokens": 12,
  "output_tokens": 4,
  "finish_reason": "completed",
  "provider_id": "584aa35d-8f7e-44d1-805a-58174513cbca",
  "provider_type": "anthropic_api",
  "latency_ms": 1948
}
```

Provider `ennam-kg` (anthropic_api, claude-sonnet-4-20250514) is active and responding normally.

## Action for FE Team

Re-run the 6 blocked E2E tests (TC1-7, TC10). All should pass now:
- Go AI endpoint: working
- Python markdown parsing: fixed
- Circuit breaker: closed (healthy)

## Knowledge: Circuit Breaker Behavior

- **State**: In-memory only, NOT persisted to DB
- **Reset method**: Restart kg-server container (or wait 30s cooldown → half-open → 1 success → closed)
- **Threshold**: 3 consecutive failures within 5-minute window → open
- **Cooldown**: 30 seconds in open state → transitions to half-open (allows 1 probe)
- **Recovery**: 1 successful probe in half-open → closed (fully operational)
- **Health check endpoint** (`POST /ai-providers/{id}/health-check`) uses a **separate code path** — does NOT go through selector/circuit breaker, so it can show "healthy" even when circuit is open

## Prevention

With the new `X-AI-*` header injection deployed, once Python implements Phase 1 (direct Anthropic client), the circuit breaker issue becomes irrelevant for streaming — Python calls Anthropic directly, bypassing Go's selector entirely. Circuit breaker only affects Go's own AI calls (KG generation, NL query pipeline).
