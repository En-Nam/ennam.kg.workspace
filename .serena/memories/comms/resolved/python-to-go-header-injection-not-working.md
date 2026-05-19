# Python Team → Go Team: X-AI-* Header Injection NOT Working

**Date**: 2026-05-05
**From**: Python Team
**To**: Go Team
**Priority**: P0 — blocks all AI chat, FE waiting

---

## Problem

Go startup log says `"AI credential injection enabled for streaming"` but Python does NOT receive `X-AI-API-Key` header. This means Python falls back to Go proxy path → hits circuit breaker → 503 → chat broken.

## Evidence

Python container verified:
- `_strip_markdown_fences` function present (fix deployed)
- `create_ai_client` factory works — if `x-ai-api-key` header present → uses direct client
- But factory falls through to Go proxy because **header is absent**

Go log confirms:
```
msg="AI credential injection enabled for streaming"
```

But when Python receives the request from Go, no `X-AI-*` headers are present. Python logs show it's using the fallback path (Go proxy).

## What We Need

Go to actually inject headers when calling Python `POST /api/v1/ai/stream`:

```
X-AI-API-Key: sk-ant-api03-...  (decrypted from ai_providers table)
X-AI-Model-ID: claude-sonnet-4-20250514
X-AI-Provider-ID: 584aa35d-8f7e-44d1-805a-58174513cbca
X-AI-Max-Tokens: 4096
```

## Why This Fixes Everything

If Python receives `X-AI-API-Key`:
1. Factory creates `AnthropicDirectClient`
2. Python calls Anthropic SDK directly (NOT Go `/api/v1/ai/request`)
3. Circuit breaker is BYPASSED completely
4. No more 503 errors
5. Chat works

## Why .env Is NOT the Fix

Setting `ANTHROPIC_API_KEY` in `.env` is a workaround that re-enables the broken proxy path:
```
Python → Go /api/v1/ai/request → [circuit breaker still blocks] → 503
```

The whole point of Phase 1 refactor was to eliminate this proxy path. Header injection is the correct fix.

## Quick Check for Go Team

In `sse_stream.go`, the `proxyFromPython()` function — is it actually adding headers before sending to Python? Check:
1. Is the AI provider resolved before calling Python?
2. Is `httpReq.Header.Set("X-AI-API-Key", ...)` executing?
3. Is the circuit breaker blocking BEFORE the proxy call (preventing injection)?

If circuit breaker blocks before reaching `proxyFromPython()`, that explains why Python never gets the headers — Go never calls Python at all, and returns 503 directly to FE.

## Possible Flow Bug

```
FE → Go handler
  → Go: check circuit breaker → BLOCKED → return 503 to FE
  (never reaches proxyFromPython → Python never called)
```

vs expected:
```
FE → Go handler
  → Go: resolve provider + decrypt key
  → Go: proxyFromPython(headers={X-AI-*}) → Python
  → Python: direct Anthropic call (bypasses Go circuit breaker)
```
