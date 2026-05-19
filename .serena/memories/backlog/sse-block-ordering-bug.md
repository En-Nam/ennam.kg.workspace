# Issue: SSE Block Events Emitted in Wrong Order

## Severity: P1 — UX/Architecture

## Description
In `ennam.kg.python/src/ennam_kg/streaming/engine.py` (lines 291-320), the SSE event ordering is incorrect:

**Current (wrong):**
```
format_metadata → content tokens (0..N) → block_start → block_content → block_end
```

**Expected (correct):**
```
format_metadata → block_start → content tokens (within block context) → block_content (confirmation) → block_end
```

## Root Cause
Code was written in 2 phases:
1. Original: `content` token streaming (simple word-by-word)
2. BA-018: Block system added AFTER content tokens instead of wrapping them

Result: content tokens are "orphaned" (no block context), and `block_content` duplicates the full text that was already streamed via tokens.

## Impact
- FE cannot progressively render text into the correct block container
- FE receives duplicate data (tokens + block_content with same text)
- FE has no way to know which block a token belongs to (no block_id on content events)
- Suggested actions are context-unaware (export/chart offered on empty results)

## Fix Required
1. Move `block_start` BEFORE content token streaming
2. Add `block_id` field to `SSEContent` model so tokens are associated with their block
3. Stream tokens only for text-based blocks (markdown); non-text blocks (table, chart) use single `block_content`
4. `block_content` at end serves as reconciliation fallback, not primary delivery
5. Add early-return path when query result has 0 rows (skip LLM calls for summary/format/insights)
6. Update Go BlockAccumulator to handle new event ordering

## Files to Change
- `ennam.kg.python/src/ennam_kg/streaming/engine.py` — reorder yield sequence (lines 281-320)
- `ennam.kg.python/src/ennam_kg/streaming/models.py` — add `block_id` to `SSEContent`
- `ennam.kg.go/internal/service/sse_stream.go` — update BlockAccumulator for new ordering
- `ennam.kg.go/internal/models/sse.go` — add BlockID to content event model
- Tests in both services

## Related
- BA-018 (Format Detection and Block Composition)
- BA-019 (Insights and Suggested Actions)
- Discovered: 2026-05-05
