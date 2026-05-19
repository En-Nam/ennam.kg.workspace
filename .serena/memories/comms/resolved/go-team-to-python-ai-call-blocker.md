# Go Team → Python Team: AI Call Blocker — Action Required

**Date**: 2026-05-05
**From**: Go Team
**To**: Python Team
**Priority**: HIGH — blocks 6/10 FE E2E tests

---

## Problem

FE E2E tests show Python worker returns `INTENT_PARSE_FAILED: AI returned invalid JSON: Expecting value: line 1 column 1 (char 0)`.

This means Python's AI call returns **empty response** — no content from Anthropic.

## Go Side Status: READY

- AI provider active in DB: `ennam-kg` (anthropic_api, claude-sonnet-4-20250514, is_active=true, status=healthy)
- `X-AI-API-Key` header injection: **deployed and working** (confirmed in startup logs)
- Go `/api/v1/ai/request` endpoint: available for fallback proxy calls
- Budget: available ($5 remaining)

## What Python Should Check

### If using fallback (Go proxy — current state):
1. Is `KG_GO_API_URL` env var set correctly in Python container? (should be `http://kg-server:8080`)
2. Is Python calling `POST /api/v1/ai/request` with correct auth header?
3. Check Python logs: what error does it get when calling Go for AI?

### If testing new direct client (Phase 1):
1. Are `X-AI-*` headers being read? (Go is sending them now)
2. Is `AnthropicDirectClient` creating SDK client correctly from `X-AI-API-Key` header?

## Quick Diagnostic

Run from Python container:
```bash
curl -X POST http://kg-server:8080/api/v1/ai/request \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <python-worker-api-key>" \
  -d '{"request_type":"intent_parse","messages":[{"role":"user","content":"show all tables"}],"max_tokens":1000}'
```

If this returns a valid AI response → problem is in Python's client code.
If this returns auth error → Python's API key is wrong/revoked.

## Expected Resolution

Once Python can successfully call Anthropic (either via Go proxy or direct), all 6 blocked FE tests should pass automatically — FE code is confirmed working.
