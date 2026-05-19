# /chat Final Verification — 2026-04-23

## ALL P0/P1 FIXES VERIFIED

### P0: project_id = 'default' → useProject()  **PASS**
- Sidebar loads 5 threads with real data ✅
- Thread creation works (201) ✅
- Data source "C4K" loads in selector ✅
- Favorites section loads ✅

### P1: BFF SSE Proxy  **PASS**
- Content-Type: text/event-stream ✅
- SSE events stream through: progress(parsing_intent) → progress(generating_sql) → error(INTENT_PARSE_FAILED) ✅
- No more null/400 response ✅

### P1: StreamRequest project_id  **PASS**
- Request body includes project_id: "a0000000-..." ✅
- No more 400 "project_id is required" ✅

### P2: ResponseRenderer wired in /chat
- NOT TESTABLE YET — AI pipeline returns error before generating response content
- Components exist in ChatMessage.tsx per Serena memory — will verify when AI returns actual response

## NEW BUG FOUND

### P2: Message cache not invalidated on stream error
- User message IS persisted server-side (verified via API)
- But UI shows "0 messages" because onError callback in useStreamQuery doesn't invalidate ['messages'] React Query cache
- After page reload: user message appears correctly with "1 message" count
- Fix: add `queryClient.invalidateQueries(['messages', threadId])` in onError handler

## AI Pipeline Status
- SSE streaming end-to-end: Go → Python → AI → SSE → BFF → Browser ✅
- Intent parsing fails: "AI returned invalid JSON" — Python worker needs schema context
- This is a Go/Python pipeline issue (schema extraction), not a frontend bug

## Summary
| Fix | Verdict |
|-----|---------|
| P0: project_id | **PASS** |
| P1: BFF SSE proxy | **PASS** |
| P1: StreamRequest project_id | **PASS** |
| P2: ResponseRenderer wired | **PENDING** (needs successful AI response) |
| NEW: message cache on error | **FAIL** (P2 — messages invisible until reload) |
