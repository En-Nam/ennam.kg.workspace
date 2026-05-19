# ✅ FIXED: useAgenticStream isStreaming not reset on error events

**Priority**: P3 (UX degraded, not blocking)
**Found**: 2026-05-12, Wave 2 E2E testing session

## Bug description

When the agentic stream ends with an `error` SSE event (without a subsequent `done` event), the `useAgenticStream` hook does not reset `isStreaming` to `false`.

Result: The chat input field stays disabled after a stream error. User must refresh the page to regain input.

## Expected behavior

`isStreaming` should be set to `false` (and any loading UI cleared) whenever the stream ends — whether by `done`, `error`, or connection close.

## File to fix

`ennam.kg.next/` — look for `useAgenticStream` hook (likely `src/hooks/useAgenticStream.ts` or similar)

Fix: Add `setIsStreaming(false)` on the `error` event handler and on the EventSource `onerror` callback (connection closed).

## How to verify fix

1. Send a query with an invalid data source ID
2. Stream should show error in AgenticStreamPanel
3. After error, chat input should be enabled (not disabled)
4. No page refresh needed
