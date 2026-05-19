# AI Chat E2E Retest — 2026-05-05 (Round 2, after Python rebuild)

**Trigger**: Python team reported docker rebuild complete, requested retest
**Result**: SAME FAILURE — `INTENT_PARSE_FAILED` persists

## SSE Trace (identical to Round 1)
```
POST /api/kg/ai-query/stream → 200 (text/event-stream)
  event: progress {"stage":"parsing_intent","label":"Understanding your question..."}  ✅
  event: progress {"stage":"generating_sql","label":"Generating SQL query..."}  ✅
  event: error {"error_code":"INTENT_PARSE_FAILED","error_message":"AI returned invalid JSON: Expecting value: line 1 column 1 (char 0)","retryable":false}  ❌
```

## Analysis
- Python containers rebuilt and running (Up 3 minutes at test time)
- Python worker healthy (GET /healthz → 200)
- **Same root cause**: AI model returns empty response because no API key injected
- Python retry logic (commit `baca818`) fires → retries once → same empty response → fails

## Root Cause (unchanged)
Go API does not inject `X-AI-API-Key` header into requests to Python.
Python falls back to `ANTHROPIC_API_KEY` env var → empty in `.env` → empty API key → Anthropic returns empty response.

## Action Required
**Go API team** must implement `X-AI-API-Key` header injection per `comms/go-api-to-python-key-injection`.
OR: Set `ANTHROPIC_API_KEY=sk-ant-...` in `.env` and restart all containers.

## FE Status
All FE components verified working:
- SSE pipeline ✅, error display ✅, thread CRUD ✅, retry button ✅, rich rendering (ready) ✅
- No FE changes needed. Waiting on backend config.
