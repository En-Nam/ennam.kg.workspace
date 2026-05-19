# Lessons Learned: Intent Parse Failure Debugging (2026-04-29 → 2026-05-05)

## Timeline

| Date | Issue | Fix |
|------|-------|-----|
| 04-29 | `json.loads("")` crash — empty AI response | Retry logic + empty check |
| 04-29 | ANTHROPIC_API_KEY empty in .env | Identified as non-issue (Python doesn't call direct) |
| 05-05 | Markdown fences (`\`\`\`json ... \`\`\``) | `_strip_markdown_fences()` |
| 05-05 | Go circuit breaker open (503) | Go fix: remove CB from credential injection path |
| 05-05 | AI returns plain text (314 tables too large) | KG search + tool_use (final fix) |

## Root Cause Chain

The "same error message" (`INTENT_PARSE_FAILED: invalid JSON char 0`) was actually **5 different underlying causes** that appeared over time:

1. **Empty response** → AI provider not configured (Go DB key issue)
2. **Markdown fences** → Model wraps JSON in ` \`\`\`json ` blocks
3. **Circuit breaker** → Previous failures tripped breaker, blocking all requests
4. **Plain text explanation** → 314-table schema too large, model ignores JSON instruction
5. **Prompt too weak** → "Respond with JSON only" is a suggestion, not enforcement

## Key Insights

### 1. Same error message ≠ same root cause
`json.loads()` failure at char 0 can mean: empty string, markdown-wrapped, plain text explanation. Always check the ACTUAL content in logs.

### 2. Large context degrades instruction following
With >50K tokens of schema, model treats "respond with JSON" as optional. Solution: reduce context (KG search) AND enforce output (tool_use).

### 3. tool_use is the ONLY way to guarantee JSON from Anthropic
Unlike OpenAI's `response_format: json_object`, Anthropic has no equivalent. The only guarantee is `tool_choice: {type: "tool", name: "..."}` which forces the model to call the tool with valid schema-conforming input.

### 4. Knowledge Graph as search index
The KG that was built for visualization also serves as a semantic search index for schema filtering. Table nodes have `ai_description` fields that enable meaning-based search ("orders" → finds "Bookings" via description mentioning "booking transactions").

### 5. Header-based credential injection enables circuit breaker bypass
When Go injects `X-AI-API-Key`, Python calls Anthropic directly — completely bypassing Go's circuit breaker. Circuit breaker state on Go side becomes irrelevant for the AI call path.

### 6. Multiple layers of defense
Final solution uses 4 layers:
- Layer 1: KG search → small relevant schema (prevent large context)
- Layer 2: tool_use → forced JSON output (prevent plain text)
- Layer 3: `_extract_json()` → extract JSON from any format (safety net)
- Layer 4: Retry once on failure (handle transient issues)

## Testing Lessons

- **Test through the correct path**: Direct `curl localhost:8081` bypasses Go headers. Must test via Go's `/api/v1/ai-query/stream` (requires user session).
- **Container rebuild ≠ container restart**: `docker compose build` creates new image. `docker compose up -d` recreates containers. Both needed.
- **Check container has code**: Always verify with `docker compose exec indexer python -c "from module import func"` before claiming fix is deployed.
