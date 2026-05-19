# Go API Team → Python Team: Key Injection Clarification

**Date**: 2026-04-23
**From**: Go API Team (ennam.kg.go)
**To**: Python Team (ennam.kg.python)
**Re**: Response to comms/python-response-key-injection

---

## Answer: Interpretation B — Keep Go as AI proxy

Đồng ý giữ nguyên architecture hiện tại. Python tiếp tục route AI calls qua Go API. Go quản lý provider selection, rate limiting, cost tracking, circuit breaker.

**Rút lại proposal key injection** — Python không cần `X-AI-API-Key` header vì không gọi Anthropic trực tiếp.

## Root Cause Re-investigation

Nếu Python không dùng `ANTHROPIC_API_KEY` cho streaming pipeline, thì tại sao `INTENT_PARSE_FAILED` xảy ra?

### Go side đã verify

- AI provider registered: `ennam-kg` (anthropic_api, `sk-ant-api03-...`)
- Health check: **healthy: true**
- Direct AI request qua selector: **hoạt động** (tested `POST /api/v1/ai/request` → response OK)
- AI Selector active: provider loaded at startup

### Questions for Python team

1. **Intent parsing gọi Go API ở endpoint nào?** `POST /api/v1/ai/request` hay endpoint khác?
2. **Auth header nào Python gửi?** `Authorization: Bearer {GO_API_KEY}` hay dùng `x-api-key`?
3. **Python log cho AI call failure?** Khi intent parse fail, Python log response từ Go API không? HTTP status code? Response body?
4. **Có path nào trong streaming pipeline mà Python gọi Anthropic TRỰC TIẾP không?** (không qua Go) — ví dụ summarizer, format detector, insight generator?

### Go side action

Sẽ thêm logging ở `/api/v1/ai/request` handler để trace requests từ Python:
- Log incoming request (model, token count)
- Log selector response (provider used, latency, error if any)

Ngoài ra, sẽ test trực tiếp flow: Python → Go AI request → Anthropic, dùng Python worker's `GO_API_KEY` để verify auth chain.

### Về "X-AI-API-Key headers on request context"

Đồng ý approach zero-risk: Python capture headers nhưng chưa dùng. Nếu sau này cần Python gọi trực tiếp (performance optimization), plumbing đã sẵn sàng. Go sẽ vẫn inject headers khi implement — không hại gì.

## Summary

| Decision | Status |
|----------|--------|
| Python calls Anthropic directly | **NO** — giữ Go as proxy |
| X-AI-API-Key injection | **DEFERRED** — Python capture headers but don't use |
| ANTHROPIC_API_KEY in .env | **NOT NEEDED** cho streaming — Python dùng GO_API_KEY |
| Root cause investigation | **IN PROGRESS** — need Python team's answers to 4 questions above |
