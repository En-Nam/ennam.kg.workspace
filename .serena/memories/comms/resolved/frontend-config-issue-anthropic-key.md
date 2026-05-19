# Config Issue: ANTHROPIC_API_KEY Empty — Chat AI Non-functional

**Date**: 2026-04-29
**Found by**: Frontend Team (via Chrome DevTools SSE debug)
**Affects**: ALL teams — Go API, Python Worker, Frontend
**Severity**: P0 — entire AI chat feature blocked

## Problem
`ANTHROPIC_API_KEY=` is empty in root `.env` file. Python AI worker calls Anthropic API with no key → receives empty response → `json.loads("")` fails at char 0 → `INTENT_PARSE_FAILED` error.

## Evidence
```
# .env (line 33)
ANTHROPIC_API_KEY=

# SSE stream response:
event: error
data: {"error_code":"INTENT_PARSE_FAILED","error_message":"AI returned invalid JSON: Expecting value: line 1 column 1 (char 0)","retryable":false}
```

## SSE Pipeline Status (all verified working)
- FE → BFF proxy (text/event-stream pass-through): ✅
- BFF → Go API (POST /ai-query/stream): ✅  
- Go API → Python Worker (SSE proxy): ✅
- Python → Anthropic API: ❌ (empty key)
- Error display in chat UI: ✅ (red bubble shown)

## Fix Required
1. Set valid `ANTHROPIC_API_KEY=sk-ant-...` in `.env`
2. `docker compose restart kg-server indexer worker`
3. Re-test chat

## FE Readiness
Frontend is 100% ready for successful AI responses:
- SSE streaming + progress indicators ✅
- Error display with retry button ✅
- Rich response rendering (ResponseRenderer, charts, tables) ✅
- Insights + Suggested Actions ✅
- Streaming blocks live during stream ✅

Once API key is set, chat should work end-to-end.
