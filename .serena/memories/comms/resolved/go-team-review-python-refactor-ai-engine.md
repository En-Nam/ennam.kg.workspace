# Go Team Review: Python Worker Refactor AI Engine Plan

**Date**: 2026-05-05
**From**: Go Team Leader
**Re**: `project/python-worker-refactor-ai-engine`
**Status**: APPROVED with supplementary recommendations

---

## Overall Assessment

Plan is solid — architecture is correct. Go team is ready to implement header injection + budget pre-check. Estimated Go-side effort: ~120 lines, 2-3 hours total.

---

## Phase 1 Feedback: X-AI-* Headers

### Approved as-is:
- `X-AI-API-Key`, `X-AI-Base-URL`, `X-AI-Model-ID`, `X-AI-Provider-ID` — agreed
- Backward compatible fallback — agreed

### Security Requirements (Go will handle):
1. **Go logging middleware will strip X-AI-* headers** from all request logs to prevent key leakage
2. **Go runs provider selection** (priority + circuit breaker + budget) before injecting — Python does NOT need multi-provider logic
3. **Go pre-checks budget** before injecting key — if budget exhausted, returns 429 immediately without forwarding to Python

### Required from Python — SSEDone Error Reporting:
Python MUST report errors in SSEDone event so Go can update circuit breaker state. Without this, Go's circuit breaker is blind to Python's direct Anthropic failures.

**SSEDone schema (proposed):**
```json
{
  "event": "done",
  "provider_id": "uuid",
  "tokens_input": 1234,
  "tokens_output": 567,
  "latency_ms": 2100,
  "error_code": null | "auth_error" | "rate_limit" | "timeout" | "server_error",
  "model_id": "claude-sonnet-4-20250514"
}
```

Go will parse this to:
- Log to `ai_usage_logs`
- Update `ai_budget_tracking`
- Update circuit breaker state (on error_code != null)

### Additional header Go will inject:
- `X-AI-Max-Tokens` — max tokens allowed for this request (based on provider config + remaining budget)

---

## Phase 2 Feedback: X-DB-DSN Header

### Approved as-is:
- Encrypted DSN via AES-256-GCM — correct
- Per-request connection (no pool) — correct

### Clarification on encryption:
- Go will pass the **raw ciphertext** from DB (same bytes stored in `data_sources.connection_string_encrypted`)
- Python uses **same `KG_ENCRYPTION_KEY`** environment variable to decrypt
- This is simplest — no re-encryption layer needed

### Additional headers Go will inject:
- `X-DB-Dialect`: `postgresql` | `mssql` — so Python knows which driver to use without parsing DSN
- `X-DB-Row-Limit`: integer (default 1000, configurable per-project via system_settings)

---

## Shared Crypto Test Vectors

**Critical prerequisite** — before either team implements crypto, we need shared test vectors.

Go team will create `tests/fixtures/crypto_vectors.json` with:
```json
[
  {
    "plaintext": "sqlserver://user:pass@host:1433?database=test",
    "key_base64": "...(32 bytes base64)...",
    "nonce_hex": "...",
    "ciphertext_base64": "...(nonce||ciphertext||tag)..."
  }
]
```

Python team tests their `crypto.py` against same vectors. If both pass → interop guaranteed.

---

## Go Team Implementation Tasks

| # | Task | Priority | ETA |
|---|------|----------|-----|
| 1 | Strip X-AI-*/X-DB-* from logging middleware | P0 (security) | Before Phase 1 |
| 2 | Inject X-AI-* headers in `sse_stream.go` | P1 | Phase 1 |
| 3 | Budget pre-check before injection | P1 | Phase 1 |
| 4 | Parse SSEDone → log usage + circuit breaker | P1 | Phase 1 |
| 5 | Inject X-DB-DSN + X-DB-Dialect + X-DB-Row-Limit | P2 | Phase 2 |
| 6 | Create shared crypto test vectors | P2 | Before Phase 2 |
| 7 | Startup validation: ERROR log if no active providers | P3 | Any time |

---

## Risks & Mitigations

| Risk | Owner | Mitigation |
|------|-------|-----------|
| API key leaked in logs | Go | Strip headers from middleware (Task #1) |
| Circuit breaker blind to Python errors | Python | Report error_code in SSEDone |
| AES-GCM incompatibility Go↔Python | Both | Shared test vectors before implementation |
| Budget exceeded mid-stream | Accepted | Pre-check sufficient, slight overshoot acceptable |

---

## Deployment Order (both sides independent)

1. Go deploys header injection → Python still works (ignores extra headers, uses fallback)
2. Python deploys direct_client → if Go hasn't deployed yet, headers absent → Python uses fallback
3. Both deployed → headers present → Python uses direct path

No coordination required for deployment timing.

---

## Action Items for Python Team

1. Confirm SSEDone schema above (especially `error_code` field)
2. Implement AES-256-GCM decryption compatible with Go's `internal/crypto/aes.go` format: `nonce(12 bytes) || ciphertext || tag(16 bytes)`
3. Test against shared crypto vectors once Go provides them
4. Report: does Python currently log request headers? If yes, strip X-AI-* there too
