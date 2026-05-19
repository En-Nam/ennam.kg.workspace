# /chat Verification After Fixes — 2026-04-22

## Summary: 14 PASS, 1 FAIL (new bug), 1 remaining P1

## VERIFIED FIXED (14)
1. P0: project_id='default' → useProject() hook — sidebar loads threads ✅
2. P0: Thread creation via UI → 201 ✅
3. P0: Data source selector loads "C4K" ✅
4. P1: Thread search returns [] (not null) ✅
5. P2: Thread name max 100 chars → 400 validation ✅
6. P2: Invalid UUID → 400 (not 500) ✅
7. Thread list sorted by last activity ✅
8. Thread inline rename works (click → edit → Enter/Escape) ✅
9. Character counter 38/2000 visible ✅
10. Send button disabled when <3 chars ✅
11. Archive/Delete buttons present in header ✅
12. Show Archived toggle present ✅
13. Favorites section (empty state) ✅
14. Empty state "Select or create a thread" ✅

## NEW BUG FOUND (1)
**P1: StreamRequest missing project_id** — `stream.mutate()` sends `{thread_id, data_source_id, query}` but Go API requires `project_id` in body. Returns 400.
- File: `src/types/thread.ts:57` — `StreamRequest` interface lacks `project_id`
- File: `src/app/(dashboard)/chat/page.tsx:53` — `stream.mutate()` doesn't include `project_id`
- File: `src/app/(dashboard)/chat/[threadId]/page.tsx:52` — same

## REMAINING (1)
**P1: BFF SSE proxy** — even after project_id fix, the BFF catch-all route may not properly stream SSE events to the client. Needs verification after StreamRequest fix.

## Feature Gap (unchanged)
ResponseRenderer, ToolMenu, SuggestedActions, InsightCards still only in /chat-demo, not /chat.
