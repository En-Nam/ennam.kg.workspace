# SSE Block-Ordered Streaming Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix SSE event ordering so content tokens stream within block boundaries, and short-circuit empty results to avoid unnecessary LLM calls.

**Architecture:** Python streaming engine emits `block_start` before content tokens (not after). Go BlockAccumulator handles `content` events within active block context. Empty query results skip format detection and insight generation LLM calls.

**Tech Stack:** Python 3.12 (Pydantic, FastAPI), Go 1.22 (stdlib HTTP, `encoding/json`)

---

## Task 1: Python — Add `block_id` to SSEContent model

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/streaming/models.py:44-46`

- [ ] **Step 1: Add block_id field to SSEContent**

In `ennam.kg.python/src/ennam_kg/streaming/models.py`, change the `SSEContent` class:

```python
class SSEContent(BaseModel):
    token: str
    index: int
    block_id: str | None = None
```

- [ ] **Step 2: Verify no existing tests break**

Run: `cd d:/Projects/EnNam/ennam.kg/ennam.kg.python && uv run pytest tests/test_streaming_api.py -v`
Expected: All existing tests PASS (field is optional, backward compatible)

- [ ] **Step 3: Commit**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.python
git add src/ennam_kg/streaming/models.py
git commit -m "feat(streaming): add block_id field to SSEContent model

Allows content tokens to be associated with their containing block.
Field is optional (None) for backward compatibility."
```

---

## Task 2: Python — Reorder engine.py to emit blocks before content tokens

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/streaming/engine.py:281-320`

- [ ] **Step 1: Write failing test for new event ordering**

Create `ennam.kg.python/tests/test_streaming_block_order.py`:

```python
"""Tests for block-ordered streaming — block_start must precede content tokens."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from ennam_kg.ai_client.models import AIResponse, AIUsage
from ennam_kg.streaming.engine import StreamRequest, StreamingQueryEngine
from ennam_kg.streaming.models import SSEEvent


async def _collect_events(engine: StreamingQueryEngine, req: StreamRequest) -> list[dict]:
    """Collect all SSE events from engine.stream() as dicts."""
    events = []
    async for event in engine.stream(req):
        events.append({"event": event.event, "data": event.data.model_dump(mode="json", exclude_none=True)})
    return events


def _make_request() -> StreamRequest:
    return StreamRequest(
        project_id="proj-1",
        data_source_id="ds-1",
        query="show me all orders",
        thread_id="t-1",
        message_id="msg-1",
        dialect="mssql",
    )


def _mock_kg_client():
    client = AsyncMock()
    client.search.return_value = AsyncMock(nodes=[])
    client.get_schema_metadata.return_value = {
        "tables": {
            "orders": {
                "columns": {"id": "integer", "total": "numeric", "created_at": "datetime"},
                "primary_key": "id",
                "foreign_keys": [],
            }
        }
    }
    return client


def _mock_ai_client_with_results():
    """AI client that returns intent + summary + format + insights."""
    client = AsyncMock()
    call_count = 0

    async def fake_complete(request):
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            # Intent parsing
            return AIResponse(
                content=json.dumps({
                    "tables": ["orders"],
                    "joins": [],
                    "filters": [],
                    "aggregations": [],
                    "group_by": [],
                    "order_by": [{"column": "created_at", "direction": "DESC"}],
                    "limit": 10,
                }),
                usage=AIUsage(input_tokens=300, output_tokens=100),
                provider_id="test",
                provider_type="test",
            )
        elif call_count == 2:
            # Summary generation
            return AIResponse(
                content="Found 2 orders totaling $250.",
                usage=AIUsage(input_tokens=200, output_tokens=30),
                provider_id="test",
                provider_type="test",
            )
        elif call_count == 3:
            # Format detection
            return AIResponse(
                content=json.dumps({
                    "format": "table",
                    "blocks": [
                        {"type": "markdown", "purpose": "summary"},
                        {"type": "table", "purpose": "data"},
                    ],
                    "aggregation_applied": False,
                    "aggregation_metadata": None,
                }),
                usage=AIUsage(input_tokens=150, output_tokens=50),
                provider_id="test",
                provider_type="test",
            )
        else:
            # Insights
            return AIResponse(
                content=json.dumps({
                    "insights": [],
                    "suggested_actions": [
                        {"label": "Export", "description": "Download CSV", "action_type": "export"},
                    ],
                }),
                usage=AIUsage(input_tokens=100, output_tokens=40),
                provider_id="test",
                provider_type="test",
            )

    client.complete = fake_complete
    client.complete_with_tools = AsyncMock(side_effect=fake_complete)
    client.provider_id = "test-provider"
    client.model_id = "test-model"
    return client


def _mock_db_client_with_rows():
    """DB client that returns 2 rows."""
    from ennam_kg.db_client.client import QueryResult

    client = AsyncMock()
    client.execute.return_value = QueryResult(
        columns=["id", "total", "created_at"],
        rows=[[1, 100.0, "2026-01-01"], [2, 150.0, "2026-01-02"]],
    )
    return client


@pytest.mark.asyncio
async def test_block_start_precedes_content_tokens():
    """block_start must appear BEFORE any content tokens for that block."""
    kg = _mock_kg_client()
    ai = _mock_ai_client_with_results()
    db = _mock_db_client_with_rows()
    engine = StreamingQueryEngine(kg, ai, db)

    events = await _collect_events(engine, _make_request())
    event_types = [e["event"] for e in events]

    # Find first content token
    first_content_idx = next(i for i, e in enumerate(events) if e["event"] == "content")
    # Find first block_start
    first_block_start_idx = next(i for i, e in enumerate(events) if e["event"] == "block_start")

    # block_start MUST come before first content token
    assert first_block_start_idx < first_content_idx, (
        f"block_start at index {first_block_start_idx} should precede "
        f"content at index {first_content_idx}"
    )


@pytest.mark.asyncio
async def test_content_tokens_have_block_id():
    """All content tokens must carry block_id matching their enclosing block."""
    kg = _mock_kg_client()
    ai = _mock_ai_client_with_results()
    db = _mock_db_client_with_rows()
    engine = StreamingQueryEngine(kg, ai, db)

    events = await _collect_events(engine, _make_request())

    content_events = [e for e in events if e["event"] == "content"]
    assert len(content_events) > 0, "Expected content tokens"

    for ce in content_events:
        assert "block_id" in ce["data"], f"Content token missing block_id: {ce['data']}"
        assert ce["data"]["block_id"] is not None, f"Content token has null block_id"


@pytest.mark.asyncio
async def test_block_content_follows_content_tokens():
    """block_content (reconciliation) must come after content tokens, before block_end."""
    kg = _mock_kg_client()
    ai = _mock_ai_client_with_results()
    db = _mock_db_client_with_rows()
    engine = StreamingQueryEngine(kg, ai, db)

    events = await _collect_events(engine, _make_request())

    # For the first block (markdown), verify ordering:
    # block_start → content* → block_content → block_end
    block_starts = [i for i, e in enumerate(events) if e["event"] == "block_start"]
    assert len(block_starts) >= 1

    first_block_id = events[block_starts[0]]["data"]["block_id"]

    # Get indices for this block's events
    block_content_idx = next(
        i for i, e in enumerate(events)
        if e["event"] == "block_content" and e["data"]["block_id"] == first_block_id
    )
    block_end_idx = next(
        i for i, e in enumerate(events)
        if e["event"] == "block_end" and e["data"]["block_id"] == first_block_id
    )
    last_token_for_block = max(
        (i for i, e in enumerate(events)
         if e["event"] == "content" and e["data"].get("block_id") == first_block_id),
        default=-1,
    )

    # content tokens < block_content < block_end
    assert last_token_for_block < block_content_idx < block_end_idx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd d:/Projects/EnNam/ennam.kg/ennam.kg.python && uv run pytest tests/test_streaming_block_order.py -v`
Expected: FAIL — `block_start` currently comes after content tokens

- [ ] **Step 3: Rewrite engine.py lines 281-320**

Replace the content streaming + block emission section in `ennam.kg.python/src/ennam_kg/streaming/engine.py`. The section currently at lines 281-320 (from `# Emit format_metadata event` to after the block loop) should become:

```python
        # Emit format_metadata event
        yield SSEEvent(
            event="format_metadata",
            data=SSEFormatMetadata(
                format=fmt.format,
                total_blocks=len(blocks),
                aggregation_applied=fmt.aggregation_applied,
            ),
        )

        # Stream blocks — content tokens live INSIDE block boundaries
        token_index = 0
        for block in blocks:
            yield SSEEvent(
                event="block_start",
                data=SSEBlockStart(
                    block_id=block.block_id,
                    block_type=block.block_type,
                    config=block.config,
                ),
            )

            if block.block_type == "markdown":
                # Text blocks: stream token-by-token for progressive rendering
                words = (block.content or "").split(" ")
                for i, word in enumerate(words):
                    token = word if i == 0 else f" {word}"
                    content_parts.append(token)
                    yield SSEEvent(
                        event="content",
                        data=SSEContent(token=token, index=token_index, block_id=block.block_id),
                    )
                    token_index += 1
                # Reconciliation: full content for clients that missed tokens
                yield SSEEvent(
                    event="block_content",
                    data=SSEBlockContent(
                        block_id=block.block_id,
                        content=block.content,
                        is_complete=True,
                    ),
                )
            else:
                # Data blocks (table, chart, code): single payload, no token streaming
                yield SSEEvent(
                    event="block_content",
                    data=SSEBlockContent(
                        block_id=block.block_id,
                        content=block.content,
                        data=block.data,
                        is_complete=True,
                    ),
                )

            yield SSEEvent(
                event="block_end",
                data=SSEBlockEnd(block_id=block.block_id),
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd d:/Projects/EnNam/ennam.kg/ennam.kg.python && uv run pytest tests/test_streaming_block_order.py tests/test_streaming_api.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.python
git add src/ennam_kg/streaming/engine.py tests/test_streaming_block_order.py
git commit -m "fix(streaming): emit block_start before content tokens

Content tokens now stream within block boundaries. Each token carries
block_id so frontend can route it to the correct container.
block_content serves as reconciliation fallback after tokens."
```

---

## Task 3: Python — Empty result short circuit

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/streaming/engine.py` (insert after line 242, before Stage 5)

- [ ] **Step 1: Write failing test for empty result fast path**

Add to `ennam.kg.python/tests/test_streaming_block_order.py`:

```python
def _mock_ai_client_intent_only():
    """AI client that only handles intent parsing (no summary/format/insight calls)."""
    client = AsyncMock()

    async def fake_complete(request):
        return AIResponse(
            content=json.dumps({
                "tables": ["orders"],
                "joins": [],
                "filters": [],
                "aggregations": [],
                "group_by": [],
                "order_by": [],
                "limit": 10,
            }),
            usage=AIUsage(input_tokens=300, output_tokens=100),
            provider_id="test",
            provider_type="test",
        )

    client.complete = fake_complete
    client.complete_with_tools = AsyncMock(side_effect=fake_complete)
    client.provider_id = "test-provider"
    client.model_id = "test-model"
    return client


def _mock_db_client_empty():
    """DB client that returns 0 rows."""
    from ennam_kg.db_client.client import QueryResult

    client = AsyncMock()
    client.execute.return_value = QueryResult(columns=["id", "total"], rows=[])
    return client


@pytest.mark.asyncio
async def test_empty_result_short_circuits_llm_calls():
    """When query returns 0 rows, skip summary/format/insight LLM calls."""
    kg = _mock_kg_client()
    ai = _mock_ai_client_intent_only()
    db = _mock_db_client_empty()
    engine = StreamingQueryEngine(kg, ai, db)

    events = await _collect_events(engine, _make_request())
    event_types = [e["event"] for e in events]

    # Should still have progress, format_metadata, block events, suggested_actions, done
    assert "format_metadata" in event_types
    assert "block_start" in event_types
    assert "done" in event_types
    assert "suggested_actions" in event_types

    # Verify format is "text" not "table" (no format detection LLM call)
    fmt_event = next(e for e in events if e["event"] == "format_metadata")
    assert fmt_event["data"]["format"] == "text"

    # Verify AI was only called once (intent parsing), not 3-4 times
    # The mock only handles 1 call — if engine tried more calls, it would fail
    done_event = next(e for e in events if e["event"] == "done")
    assert done_event["data"]["tokens_input"] == 300  # Only intent parsing tokens
    assert done_event["data"]["tokens_output"] == 100


@pytest.mark.asyncio
async def test_empty_result_suggested_actions_are_contextual():
    """Empty results should suggest helpful actions, not export/chart."""
    kg = _mock_kg_client()
    ai = _mock_ai_client_intent_only()
    db = _mock_db_client_empty()
    engine = StreamingQueryEngine(kg, ai, db)

    events = await _collect_events(engine, _make_request())

    actions_event = next(e for e in events if e["event"] == "suggested_actions")
    labels = [a["label"] for a in actions_event["data"]["actions"]]

    # Should NOT contain export/chart for empty results
    assert "Export CSV" not in labels
    assert "View as chart" not in labels
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd d:/Projects/EnNam/ennam.kg/ennam.kg.python && uv run pytest tests/test_streaming_block_order.py::test_empty_result_short_circuits_llm_calls -v`
Expected: FAIL — engine currently calls all LLM stages regardless of row count

- [ ] **Step 3: Add empty-result short circuit to engine.py**

Insert the following after the query execution `except` blocks (after line 242, before the `# --- Stage 5` comment):

```python
        # --- Empty result fast path: skip LLM calls when no rows ---
        rows = results_data.get("rows", [])
        if not rows:
            table_name = plan.tables[0] if plan.tables else "table"
            summary_text = (
                f"The query returned no results. "
                f"The {table_name} table may be empty or no records match the criteria."
            )
            # Emit format_metadata
            yield SSEEvent(
                event="format_metadata",
                data=SSEFormatMetadata(format="text", total_blocks=1, aggregation_applied=False),
            )
            # Emit block with template response
            from uuid import uuid4

            block_id = f"blk-{uuid4().hex[:8]}"
            yield SSEEvent(
                event="block_start",
                data=SSEBlockStart(block_id=block_id, block_type="markdown"),
            )
            token_index = 0
            words = summary_text.split(" ")
            for i, word in enumerate(words):
                token = word if i == 0 else f" {word}"
                content_parts.append(token)
                yield SSEEvent(
                    event="content",
                    data=SSEContent(token=token, index=token_index, block_id=block_id),
                )
                token_index += 1
            yield SSEEvent(
                event="block_content",
                data=SSEBlockContent(block_id=block_id, content=summary_text, is_complete=True),
            )
            yield SSEEvent(
                event="block_end",
                data=SSEBlockEnd(block_id=block_id),
            )
            # Context-aware suggested actions for empty results
            yield SSEEvent(
                event="suggested_actions",
                data=SSESuggestedActions(
                    actions=[
                        SuggestedAction(
                            label="Check data source",
                            description="Verify the table has data",
                            action_type="query",
                        ),
                        SuggestedAction(
                            label="Try broader query",
                            description="Remove filters or constraints",
                            action_type="query",
                        ),
                        SuggestedAction(
                            label="View schema",
                            description="Inspect table structure",
                            action_type="drill_down",
                        ),
                    ]
                ),
            )
            # Done
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            yield SSEEvent(
                event="done",
                data=SSEDone(
                    message_id=req.message_id,
                    tokens_input=total_input_tokens,
                    tokens_output=total_output_tokens,
                    latency_ms=elapsed_ms,
                    generated_sql=generated_sql,
                    full_content="".join(content_parts),
                    provider_id=self._provider_id,
                    model_id=self._model_id,
                ),
            )
            return
```

Also add `from uuid import uuid4` at the top of the file (imports section).

- [ ] **Step 4: Run tests**

Run: `cd d:/Projects/EnNam/ennam.kg/ennam.kg.python && uv run pytest tests/test_streaming_block_order.py tests/test_streaming_api.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.python
git add src/ennam_kg/streaming/engine.py tests/test_streaming_block_order.py
git commit -m "perf(streaming): short-circuit empty results, skip LLM calls

When query returns 0 rows, emit template response directly instead of
calling Claude for summary/format/insights. Saves ~11s latency.
Suggested actions are now context-aware for empty results."
```

---

## Task 4: Go — Add BlockID to SSEContent struct

**Files:**
- Modify: `ennam.kg.go/internal/models/sse.go:26-29`

- [ ] **Step 1: Add BlockID field**

In `ennam.kg.go/internal/models/sse.go`, update the `SSEContent` struct:

```go
// SSEContent represents a single content token streamed from the AI.
type SSEContent struct {
	Token   string `json:"token"`
	Index   int    `json:"index"`
	BlockID string `json:"block_id,omitempty"`
}
```

- [ ] **Step 2: Run existing tests**

Run: `cd d:/Projects/EnNam/ennam.kg/ennam.kg.go && go test ./internal/models/... ./internal/service/... -v -count=1`
Expected: All PASS (new field is omitempty, backward compatible)

- [ ] **Step 3: Commit**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.go
git add internal/models/sse.go
git commit -m "feat(models): add BlockID to SSEContent struct

Allows content tokens to carry their parent block_id for
block-ordered streaming. Field is omitempty for backward compat."
```

---

## Task 5: Go — Update BlockAccumulator to handle content tokens within blocks

**Files:**
- Modify: `ennam.kg.go/internal/service/sse_stream.go:258-370`
- Modify: `ennam.kg.go/internal/service/sse_stream_test.go`

- [ ] **Step 1: Write failing test for content-within-block accumulation**

Add to `ennam.kg.go/internal/service/sse_stream_test.go`:

```go
func TestBlockAccumulator_ContentWithinBlock(t *testing.T) {
	acc := NewBlockAccumulator()

	// Simulate new ordering: block_start → content tokens → block_content → block_end
	err := acc.HandleBlockStart(&models.SSEBlockStart{
		BlockID: "blk-1",
		Type:    "markdown",
	})
	require.NoError(t, err)

	// Content tokens arrive within block context
	err = acc.HandleContentToken(&models.SSEContent{
		Token:   "Hello",
		Index:   0,
		BlockID: "blk-1",
	})
	require.NoError(t, err)

	err = acc.HandleContentToken(&models.SSEContent{
		Token:   " world",
		Index:   1,
		BlockID: "blk-1",
	})
	require.NoError(t, err)

	// block_content arrives as reconciliation (should NOT double-append)
	err = acc.HandleBlockContent(&models.SSEBlockContent{
		BlockID: "blk-1",
		Content: "Hello world",
	})
	require.NoError(t, err)

	err = acc.HandleBlockEnd(&models.SSEBlockEnd{BlockID: "blk-1"})
	require.NoError(t, err)

	// ContentText should be "Hello world", not "Hello worldHello world"
	assert.Equal(t, "Hello world", acc.ContentText())

	blocksJSON, err := acc.Blocks()
	require.NoError(t, err)
	assert.Contains(t, string(blocksJSON), `"content":"Hello world"`)
}

func TestBlockAccumulator_ContentTokenWithoutBlock_Ignored(t *testing.T) {
	acc := NewBlockAccumulator()

	// Legacy: content token without active block should not error (backward compat)
	err := acc.HandleContentToken(&models.SSEContent{
		Token: "orphan",
		Index: 0,
	})
	// Should not error — just accumulate for legacy ContentText fallback
	require.NoError(t, err)
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd d:/Projects/EnNam/ennam.kg/ennam.kg.go && go test ./internal/service/ -run TestBlockAccumulator_ContentWithinBlock -v -count=1`
Expected: FAIL — `HandleContentToken` method does not exist yet

- [ ] **Step 3: Add HandleContentToken to BlockAccumulator**

In `ennam.kg.go/internal/service/sse_stream.go`, add after `HandleBlockEnd`:

```go
// HandleContentToken processes a content token event.
// If a block is active and the token's BlockID matches, appends to the content buffer.
// If no block is active (legacy ordering), accumulates for fallback ContentText.
func (a *BlockAccumulator) HandleContentToken(content *models.SSEContent) error {
	if a.activeBlock != nil && content.BlockID == a.activeBlock.BlockID {
		a.contentBuffer.WriteString(content.Token)
		a.tokenReceived = true
	} else if a.activeBlock == nil {
		// Legacy fallback: accumulate orphan tokens
		a.legacyContent.WriteString(content.Token)
	}
	return nil
}
```

Also update the `BlockAccumulator` struct to add new fields:

```go
type BlockAccumulator struct {
	blocks         []models.ResponseBlock
	activeBlock    *models.ResponseBlock
	contentBuffer  strings.Builder
	formatMetadata *models.SSEFormatMetadata
	aggregation    *models.AggregationMetadata
	tokenReceived  bool            // true if content tokens were received for active block
	legacyContent  strings.Builder // accumulates orphan tokens (legacy ordering)
}
```

Update `HandleBlockContent` to skip appending content if tokens already provided it:

```go
func (a *BlockAccumulator) HandleBlockContent(content *models.SSEBlockContent) error {
	if a.activeBlock == nil {
		return fmt.Errorf("block_content received without active block")
	}
	if a.activeBlock.BlockID != content.BlockID {
		return fmt.Errorf("block_content block_id mismatch: active=%q, received=%q", a.activeBlock.BlockID, content.BlockID)
	}

	// If tokens already streamed content, block_content is reconciliation — use it only
	// if the token buffer is empty (fallback for missed tokens).
	if content.Content != "" {
		if a.tokenReceived {
			// Tokens already populated contentBuffer — skip to avoid duplication.
			// But validate: if contentBuffer is empty despite tokenReceived, use block_content.
			if a.contentBuffer.Len() == 0 {
				a.contentBuffer.WriteString(content.Content)
			}
		} else {
			a.contentBuffer.WriteString(content.Content)
		}
	}
	if content.Data != nil {
		a.activeBlock.Data = content.Data
	}
	return nil
}
```

Update `HandleBlockStart` to reset `tokenReceived`:

```go
func (a *BlockAccumulator) HandleBlockStart(start *models.SSEBlockStart) error {
	if len(a.blocks) >= models.MaxResponseBlocks {
		return fmt.Errorf("block limit exceeded: maximum %d blocks per response", models.MaxResponseBlocks)
	}
	if !models.IsValidBlockType(start.Type) {
		return fmt.Errorf("invalid block type: %q", start.Type)
	}
	if a.activeBlock != nil {
		return fmt.Errorf("block_start received while block %q is still active", a.activeBlock.BlockID)
	}

	a.activeBlock = &models.ResponseBlock{
		BlockID: start.BlockID,
		Type:    start.Type,
		Config:  start.Config,
	}
	a.contentBuffer.Reset()
	a.tokenReceived = false
	return nil
}
```

Update `ContentText` to include legacy content:

```go
func (a *BlockAccumulator) ContentText() string {
	var sb strings.Builder
	// Include legacy orphan tokens (from old Python that sends tokens before blocks)
	if a.legacyContent.Len() > 0 {
		sb.WriteString(a.legacyContent.String())
	}
	for _, block := range a.blocks {
		if block.Content != "" {
			if sb.Len() > 0 {
				sb.WriteString("\n\n")
			}
			sb.WriteString(block.Content)
		}
	}
	return sb.String()
}
```

- [ ] **Step 4: Wire HandleContentToken into the streaming proxy**

In `sse_stream.go`, inside the `switch` block (around line 278), add a case for content events:

```go
case models.SSEEventContent:
	var content models.SSEContent
	if jsonErr := json.Unmarshal(eventData, &content); jsonErr != nil {
		s.logger.ErrorContext(ctx, "parse content", "error", jsonErr)
	} else {
		_ = accumulator.HandleContentToken(&content)
	}
```

- [ ] **Step 5: Run all accumulator tests**

Run: `cd d:/Projects/EnNam/ennam.kg/ennam.kg.go && go test ./internal/service/ -run TestBlockAccumulator -v -count=1`
Expected: All PASS (including new and existing tests)

- [ ] **Step 6: Run full test suite**

Run: `cd d:/Projects/EnNam/ennam.kg/ennam.kg.go && go test ./internal/service/... ./internal/models/... -v -count=1`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.go
git add internal/service/sse_stream.go internal/service/sse_stream_test.go internal/models/sse.go
git commit -m "fix(streaming): handle content tokens within block context

BlockAccumulator now processes content tokens that arrive between
block_start and block_end. Tokens with matching block_id append to
the block's content buffer. block_content serves as reconciliation
(skipped if tokens already provided the content).

Maintains backward compat: orphan tokens (no active block) still
accumulate in legacy buffer for old Python versions."
```

---

## Task 6: Integration verification

**Files:** None (verification only)

- [ ] **Step 1: Run full Python test suite**

Run: `cd d:/Projects/EnNam/ennam.kg/ennam.kg.python && uv run pytest -v`
Expected: All tests PASS

- [ ] **Step 2: Run full Go test suite**

Run: `cd d:/Projects/EnNam/ennam.kg/ennam.kg.go && make test`
Expected: All tests PASS

- [ ] **Step 3: Verify event ordering end-to-end**

Manually verify with the existing test helper: in `test_streaming_api.py`, the `test_stream_endpoint_returns_sse` test should still pass and events should show `block_start` before `content`.

Run: `cd d:/Projects/EnNam/ennam.kg/ennam.kg.python && uv run pytest tests/test_streaming_api.py -v -s`
Expected: PASS, event ordering visible in output
