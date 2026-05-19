# Python Team → Go API Team: Anthropic Direct Usage — ZERO

**Date**: 2026-04-29
**From**: Python Team (ennam.kg.python)
**To**: Go API Team (ennam.kg.go)
**Re**: Answer to "Does Python call Anthropic directly in any flow?"

---

## Answer: NO — Python calls Anthropic directly in ZERO flows

### Background indexing worker (summarizer/claude.py)

`ClaudeSummarizer` **does NOT** use the Anthropic SDK. It was refactored in Phase 2 to route through Go API:

```python
# summarizer/claude.py — line 22-23
class ClaudeSummarizer:
    def __init__(self, ai_client: AIClient, ...):  # ← uses AIClient, not anthropic SDK
        self._ai = ai_client

    async def _summarize_single(self, symbol):
        response = await self._ai.complete(AIRequest(...))  # ← goes to Go /api/v1/ai/request
```

Worker creates it with Go API client:
```python
# worker.py — line 32, 37
ai_client = AIClient(settings.go_api_url, settings.go_api_key)
summarizer = ClaudeSummarizer(ai_client=ai_client, cache=cache)
```

### Full grep verification

```
$ grep -r "import anthropic\|from anthropic" src/
(no results)
```

`anthropic` appears only once in source code: `config.py:11` as an unused config field (`anthropic_api_key: str | None = None`).

The `anthropic>=0.49` dependency in `pyproject.toml` is a legacy leftover — it was used before Phase 2 refactored all AI calls to go through Go API. It can be safely removed.

### Conclusion

| Flow | Calls Anthropic directly? | Uses what? |
|------|--------------------------|------------|
| Streaming (chat) | NO | AIClient → Go `/api/v1/ai/request` |
| Background indexing (summarizer) | NO | AIClient → Go `/api/v1/ai/request` |
| KG generation (descriptions) | NO | AIClient → Go `/api/v1/ai/request` |
| NL query (non-streaming) | NO | AIClient → Go `/api/v1/ai/request` |
| Benchmarking | NO | AIClient → Go `/api/v1/ai/request` |

**100% of AI calls go through Go API.** `ANTHROPIC_API_KEY` is completely unused. The field in config and the dependency in pyproject.toml are dead code from pre-Phase 2.

### Implication

Bài toán "cung cấp key cho 2 flows" **không tồn tại**. Chỉ có 1 flow: Python → Go API → Anthropic. Key chỉ cần tồn tại ở Go side (trong `ai_providers` DB table).

`ANTHROPIC_API_KEY` trong Python `.env` có thể xóa hoàn toàn.
