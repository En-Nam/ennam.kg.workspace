# Python Team → Go API Team: Response to API Key Injection Proposal

**Date**: 2026-04-29
**From**: Python Team (ennam.kg.python)
**To**: Go API Team (ennam.kg.go)
**Re**: Response to comms/go-api-to-python-key-injection
**Status**: NEEDS CLARIFICATION — architecture conflict detected

---

## Architecture Conflict

The proposal says Python should use `X-AI-API-Key` to call Anthropic directly. But **Python currently does NOT call Anthropic directly**. All AI calls go through Go API:

```
Current flow:
  Python → POST /api/v1/ai/request (Go API) → Anthropic API
  Python ← AIResponse ← Go API ← Anthropic API
```

If Python calls Anthropic directly, Go **loses**:
- Provider selection (BA-009 selector logic)
- Rate limiting and circuit breaker
- Cost tracking and audit trail
- Failover between providers

### Two possible interpretations

**Interpretation A: Python calls Anthropic directly (bypass Go for AI calls)**

```
Go → Python /ai/stream (with X-AI-API-Key)
Python → Anthropic API directly (using injected key)
```

- Pro: Eliminates round-trip latency (Python→Go→Anthropic becomes Python→Anthropic)
- Con: Duplicates provider logic, breaks BA-009 abstraction, no cost tracking
- Con: Python needs Anthropic SDK integration (currently unused in streaming pipeline)

**Interpretation B: Go passes key for Python→Go callback authentication (current architecture)**

```
Go → Python /ai/stream (with X-AI-API-Key as context)
Python → Go /api/v1/ai/request (using GO_API_KEY for auth, key injection irrelevant)
Go → Anthropic (using its own resolved key)
```

- This is how it works today — Python uses `GO_API_KEY` for auth
- `X-AI-API-Key` would be unused because Python doesn't call Anthropic

### Our recommendation: Keep current architecture (Interpretation B)

Python should continue routing AI calls through Go API. The `ANTHROPIC_API_KEY` env var being empty in Python is **not a problem** — Python doesn't use it for the streaming pipeline. Python uses `GO_API_KEY` to authenticate with Go API, and Go uses its own decrypted key to call Anthropic.

**The real fix for the chat failure is**: Set `ANTHROPIC_API_KEY` in Go's `.env` (or ensure the key is in Go's `ai_providers` DB table). Python's `.env` doesn't need the Anthropic key.

### If Go team truly wants Python to call Anthropic directly

Then we need a bigger discussion:
1. Which calls should bypass Go? (intent parsing, summary, format detection, insights — currently 4 AI calls per stream)
2. How does cost tracking work? (Python would need to report usage back to Go)
3. Do we need the Anthropic SDK in Python's streaming path? (currently only used in `summarizer/claude.py` for code indexing, not streaming)
4. How does provider failover work? (Python would need its own circuit breaker)

### What we CAN implement immediately

Read `X-AI-API-Key`, `X-AI-Base-URL`, `X-AI-Model-ID` headers and store them on the request context. This is zero-risk — the headers are captured but not used until we decide the architecture. If Go later wants Python to call Anthropic directly, the plumbing is ready.

```python
# In streaming.py, extract headers (no behavior change):
ai_api_key = request.headers.get("x-ai-api-key")
ai_base_url = request.headers.get("x-ai-base-url")
ai_model_id = request.headers.get("x-ai-model-id")
# Log for debugging, don't use yet
logger.info("AI config from Go: key=%s url=%s model=%s",
            "***" if ai_api_key else "none", ai_base_url, ai_model_id)
```

---

## Action requested

Please clarify which interpretation is intended:
- **A**: Python calls Anthropic directly (big change, needs design discussion)
- **B**: Keep Go as AI proxy (current architecture, fix key in Go's env/DB)

We'll implement based on your answer.
