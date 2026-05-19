# SSE Block-Ordered Streaming Protocol Fix

**Date:** 2026-05-05
**Severity:** P1 — UX/Architecture
**Affects:** `ennam.kg.python` (streaming engine), `ennam.kg.go` (SSE proxy + accumulator)

## Problem

In `ennam.kg.python/src/ennam_kg/streaming/engine.py` (lines 291-320), SSE events are emitted in wrong order:

```
format_metadata → content[0..N] → block_start → block_content → block_end
```

Content tokens stream **before** their containing block is opened. Frontend cannot:
- Route tokens to the correct block container (no `block_id` on tokens)
- Progressively render into typed containers (block type unknown until too late)
- Avoid processing duplicate data (`block_content` repeats what tokens already delivered)

## Root Cause

Code written in two phases:
1. **Original:** Simple `content` token streaming (word-by-word split of summary)
2. **BA-018:** Block system appended after tokens instead of wrapping them

## Solution

### New Event Ordering

```
format_metadata
  block_start {id, type, config}
    content {token, index, block_id}    ← tokens inside block
    content {token, index, block_id}
    ...
    block_content {id, content, is_complete: true}  ← reconciliation fallback
  block_end {id}
  block_start {id, type, config}        ← next block (if multi-block)
    block_content {id, data, is_complete: true}     ← non-text blocks: single payload
  block_end {id}
suggested_actions
done
```

### Changes Required

#### 1. Python: `streaming/models.py` — Add `block_id` to SSEContent

```python
class SSEContent(BaseModel):
    token: str
    index: int
    block_id: str | None = None  # NEW: associates token with containing block
```

#### 2. Python: `streaming/engine.py` — Reorder yield sequence

Replace lines 291-320 with block-first streaming:

```python
# Emit format_metadata (unchanged)
yield SSEEvent(event="format_metadata", data=SSEFormatMetadata(...))

# Stream blocks — tokens live INSIDE block boundaries
token_index = 0
for block in blocks:
    yield SSEEvent(event="block_start", data=SSEBlockStart(
        block_id=block.block_id, block_type=block.block_type, config=block.config,
    ))

    if block.block_type == "markdown":
        # Text blocks: stream token-by-token for progressive rendering
        words = (block.content or "").split(" ")
        for i, word in enumerate(words):
            token = word if i == 0 else f" {word}"
            content_parts.append(token)
            yield SSEEvent(event="content", data=SSEContent(
                token=token, index=token_index, block_id=block.block_id,
            ))
            token_index += 1
        # Reconciliation: full content for clients that missed tokens
        yield SSEEvent(event="block_content", data=SSEBlockContent(
            block_id=block.block_id, content=block.content, is_complete=True,
        ))
    else:
        # Data blocks (table, chart, code): single payload, no token streaming
        yield SSEEvent(event="block_content", data=SSEBlockContent(
            block_id=block.block_id, content=block.content,
            data=block.data, is_complete=True,
        ))

    yield SSEEvent(event="block_end", data=SSEBlockEnd(block_id=block.block_id))
```

#### 3. Python: `streaming/engine.py` — Empty result short circuit

After Stage 4 (execute query), before Stage 5:

```python
rows = results_data.get("rows", [])
if not rows:
    # Skip LLM calls — emit template response directly
    summary_text = f"The query returned no results. The {plan.tables[0]} table may be empty."
    yield SSEEvent(event="format_metadata", data=SSEFormatMetadata(
        format="text", total_blocks=1, aggregation_applied=False,
    ))
    block_id = f"blk-{uuid4().hex[:8]}"
    yield SSEEvent(event="block_start", data=SSEBlockStart(
        block_id=block_id, block_type="markdown",
    ))
    # Stream tokens
    for i, word in enumerate(summary_text.split(" ")):
        token = word if i == 0 else f" {word}"
        content_parts.append(token)
        yield SSEEvent(event="content", data=SSEContent(
            token=token, index=i, block_id=block_id,
        ))
    yield SSEEvent(event="block_content", data=SSEBlockContent(
        block_id=block_id, content=summary_text, is_complete=True,
    ))
    yield SSEEvent(event="block_end", data=SSEBlockEnd(block_id=block_id))
    # Emit default suggested actions (no LLM call)
    yield SSEEvent(event="suggested_actions", data=SSESuggestedActions(actions=[
        SuggestedAction(label="Check data source", description="Verify the table has data", action_type="query"),
        SuggestedAction(label="Try broader query", description="Remove filters or constraints", action_type="query"),
        SuggestedAction(label="View schema", description="Inspect table structure", action_type="drill_down"),
    ]))
    # Emit done
    elapsed_ms = int((time.monotonic() - start_time) * 1000)
    yield SSEEvent(event="done", data=SSEDone(
        message_id=req.message_id, tokens_input=total_input_tokens,
        tokens_output=total_output_tokens, latency_ms=elapsed_ms,
        generated_sql=generated_sql, full_content="".join(content_parts),
        provider_id=self._provider_id, model_id=self._model_id,
    ))
    return
```

#### 4. Go: `internal/models/sse.go` — Add BlockID to content event

```go
type SSEContentEvent struct {
    Token   string `json:"token"`
    Index   int    `json:"index"`
    BlockID string `json:"block_id,omitempty"` // NEW
}
```

#### 5. Go: `internal/service/sse_stream.go` — Update BlockAccumulator

Current accumulator expects tokens before blocks. Update to:
- Track "current open block" state
- When `block_start` arrives: open new block context
- When `content` arrives with `block_id`: append to that block's text
- When `block_end` arrives: finalize block
- Final `full_content` built from all blocks' accumulated text

### Backward Compatibility

| Concern | Mitigation |
|---------|------------|
| Old FE clients | `block_id` on content is optional field — ignored by old parsers |
| Old Python (if rollback) | Go accumulator handles both orderings: tokens-before-blocks (legacy) and tokens-within-blocks (new) |
| DB persistence | `full_content` still assembled from all content tokens regardless of ordering |

### Performance Improvement

| Scenario | Before | After |
|----------|--------|-------|
| Empty result (0 rows) | ~14s (3-4 LLM calls) | ~3s (1 LLM call for intent + SQL only) |
| Normal result | ~14s | ~14s (no change — same LLM calls needed) |
| Bandwidth | 2x text (tokens + block_content) | 1x streaming + 1x reconciliation (same bytes but semantically correct) |

### Testing

- **Python unit tests:** Verify event ordering from `engine.stream()` — `block_start` before any `content` with matching `block_id`
- **Python unit tests:** Verify empty-result short circuit skips format/insight LLM calls
- **Go unit tests:** Verify `BlockAccumulator` handles new ordering
- **Integration:** Full SSE stream e2e — confirm FE receives correct order

## Files Changed

| File | Change |
|------|--------|
| `ennam.kg.python/src/ennam_kg/streaming/models.py` | Add `block_id` to `SSEContent` |
| `ennam.kg.python/src/ennam_kg/streaming/engine.py` | Reorder yields + empty-result short circuit |
| `ennam.kg.go/internal/models/sse.go` | Add `BlockID` to content event struct |
| `ennam.kg.go/internal/service/sse_stream.go` | Update `BlockAccumulator` for new ordering |
| `ennam.kg.python/tests/test_streaming_engine.py` | Update/add tests for new ordering |
| `ennam.kg.go/internal/service/sse_stream_test.go` | Update/add tests for accumulator |
