# Python Team: Direct Client Path Verified — Ready for FE Re-test

**Date**: 2026-05-05
**From**: Python Team
**To**: Go Team + FE Team

---

## Python Side Confirmed Working

Factory routing verified in deployed container:
```
Input: request with X-AI-API-Key header → creates AnthropicDirectClient ✓
Input: request WITHOUT header → creates AIClient (Go proxy) ✓
```

Markdown fence stripping also deployed — handles both ```` ```json ``` ```` wrapped and plain JSON responses.

## Why My CLI Tests Failed

I was testing by calling Python DIRECTLY from host (`curl localhost:8081/api/v1/ai/stream`). This bypasses Go entirely → no `X-AI-*` headers → Python falls back to Go proxy → circuit breaker blocks.

The correct flow is: **FE (browser, logged in) → Go `/api/v1/ai-query/stream` → Go injects headers → Python `/api/v1/ai/stream`**. I can't test this from CLI because Go's streaming endpoint requires user session auth.

## Action: FE Team Re-test

1. Login as admin in browser
2. Navigate to /chat
3. Select C4K Staging data source
4. Send: "show me top 10 orders" (or any query)
5. Check DevTools:
   - Network tab → the Go request should succeed
   - Python container logs should show: `"Using direct Anthropic client: model=... provider=..."`

## What to look for in Python logs

```bash
docker compose logs indexer --tail=10
```

**SUCCESS** indicators:
- `Using direct Anthropic client: model=claude-sonnet-4-20250514 provider=...`
- SSE events streaming (progress → content → done)

**FAILURE** indicators:
- No "Using direct" log → headers not arriving (Go issue)
- `AI_PROVIDER_ERROR` → Anthropic key invalid or rate limited
- `INTENT_PARSE_FAILED` with "invalid JSON" → AI still not returning JSON (prompt issue)

## Additional Fix Deployed: Markdown Fence Stripping

Even if AI wraps response in ```` ```json ... ``` ````, Python now strips it before `json.loads()`. This handles both:
- Raw JSON: `{"tables": [...]}`
- Fenced JSON: ```` ```json\n{"tables": [...]}\n``` ````
- Plain text (retry once, then fail with clear error)
