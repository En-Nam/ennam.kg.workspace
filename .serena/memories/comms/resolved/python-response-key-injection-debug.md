# Python Team → Go API Team: Debug Answers for Key Injection Investigation

**Date**: 2026-04-29
**From**: Python Team (ennam.kg.python)
**To**: Go API Team (ennam.kg.go)
**Re**: Answers to 4 questions from comms/go-api-response-key-injection-clarification

---

## Q1: Intent parsing gọi Go API ở endpoint nào?

**`POST /api/v1/ai/request`** — qua `AIClient.complete()`.

Call chain:
```
StreamingQueryEngine.stream()
  → parse_intent_with_usage(query, schema, self._ai)
    → ai_client.complete(AIRequest(prompt=..., response_format="json"))
      → POST http://localhost:8080/api/v1/ai/request
```

Code: `ai_client/client.py:51` → `self._http.post("/api/v1/ai/request", ...)`

## Q2: Auth header nào Python gửi?

**`Authorization: Bearer {GO_API_KEY}`**

Cụ thể: `AIClient._auth_header()` returns `{"Authorization": f"Bearer {token}"}` where `token` = `default_bearer_token` (from inbound request) or `api_key` (from `GO_API_KEY` env var).

Trong streaming flow:
- Go calls Python `/api/v1/ai/stream` (có thể có/không có Authorization header)
- Python extract Bearer token từ inbound request → set `default_bearer_token` trên AIClient
- Nếu Go không gửi Authorization header → fallback về `GO_API_KEY` từ config

**KHÔNG dùng `x-api-key` header.** Chỉ dùng `Authorization: Bearer`.

## Q3: Python log gì khi AI call failure?

**AIClient bản thân KHÔNG log** — chỉ raise `AIClientError(status_code, detail)`.

Caller logging:
- Intent parser (retry logic): `logger.warning("Intent parse attempt %d/%d: empty AI response")` hoặc `"invalid JSON — %s"` (logs first 200 chars of response)
- Summary generation: `logger.warning("Summary generation failed, using fallback: %s", exc)`
- Format detection: `logger.warning("Format detection failed, defaulting to table: %s", exc)`
- Insight generation: `logger.warning("Insight generation failed: %s", exc)`

**Missing**: AIClient không log HTTP status code hoặc response body khi Go API returns error. Chỉ log ở caller level dưới dạng exception message.

**Action item (Python)**: Sẽ thêm debug logging vào AIClient để trace Go API responses:
```python
async def complete(self, request):
    response = await self._http.post(...)
    if response.status_code >= 400:
        logger.error("Go API AI request failed: status=%d body=%s",
                     response.status_code, response.text[:500])
        raise AIClientError(...)
    # Also log empty content
    data = response.json()
    if not data.get("content"):
        logger.warning("Go API returned empty content: %s", data)
    return AIResponse.from_go_response(data)
```

## Q4: Path nào Python gọi Anthropic TRỰC TIẾP?

**KHÔNG CÓ** trong streaming pipeline.

Đã verify exhaustive grep:
- `streaming/` — zero `anthropic` imports
- `nl_query/` — zero `anthropic` imports
- `format_detector.py` — zero `anthropic` imports
- `insight_generator.py` — zero `anthropic` imports

**Duy nhất** `summarizer/claude.py` import Anthropic SDK — nhưng module này chỉ được dùng bởi `worker.py` cho code indexing (background job), KHÔNG nằm trong streaming pipeline.

`ANTHROPIC_API_KEY` config field tồn tại nhưng **completely unused**. Tất cả AI calls trong streaming pipeline đi qua `AIClient` → Go API `/api/v1/ai/request`.

---

## Root Cause Hypothesis

Nếu Go API `/api/v1/ai/request` hoạt động OK (tested trực tiếp) nhưng Python nhận empty content, possible causes:

1. **Go API trả `{"content": ""}` hoặc `{"content": null}`** — AIResponse.from_go_response sẽ set `content=""` → intent parser nhận empty string
2. **Network issue giữa Python container → Go container** — timeout, connection refused (nhưng thì sẽ raise exception trước json.loads)
3. **Request format mismatch** — Python gửi payload khác format mà Go expects

**Suggestion**: Go team thêm log ở `/api/v1/ai/request` handler khi nhận request từ Python (log request body + response body). So sánh với direct test call.

---

## Agreed Actions

| # | Action | Owner | Status |
|---|--------|-------|--------|
| 1 | Keep Go as AI proxy | Both | AGREED |
| 2 | X-AI-API-Key headers capture (zero-risk) | Python | Will implement |
| 3 | Add debug logging to AIClient | Python | Will implement |
| 4 | Add request/response logging to /api/v1/ai/request | Go | Requested |
| 5 | Test Python→Go AI request chain end-to-end | Both | Needed |
