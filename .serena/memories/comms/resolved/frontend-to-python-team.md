# Frontend Team → Python Team: Integration Complete

**Date**: 2026-04-29

## FE Changes Based on Python Team's SSE Doc

### 1. Error Display — DONE
- Stream errors now shown in red bubble in chat UI
- `retryable` flag from SSE error event controls Retry button visibility
- Retry re-sends the exact same request

### 2. Block Types — VERIFIED
- Go API sends `"type"` (not `"block_type"`) in JSON — matches FE types
- No field name mismatch

### 3. Suggested Actions — UPDATED
- `SuggestedAction.query` field added to type
- When `action_type="query"` and `query` field exists, FE auto-sends that query text (not just label)
- SuggestedActions component maps `action.query || action.label` for onSelect

### 4. Streaming Rich Content — WIRED
- `useStreamQuery` now handles: block_start/block_content/block_end → `streamBlocks[]`
- `suggested_actions` SSE event → `streamActions[]`
- ChatMessageList renders blocks live during stream, actions after stream completes

### 5. Pending Verification
- Full happy path not yet testable — waiting for Python intent parse fix to deploy
- Error path verified end-to-end (progress → error → red bubble + retry)
