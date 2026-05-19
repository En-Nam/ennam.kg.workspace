# /chat Deep Test Results — 2026-04-22

## Summary: 20 PASS, 10 FAIL, 8 BLOCKED out of 38 executed

## Fixes Applied (2026-04-23)

### P0 — FIXED
**project_id hardcoded "default"** → Replaced with `useProject()` in 4 files:
- `chat/page.tsx`, `chat/[threadId]/page.tsx`, `query/page.tsx`, `favorites/page.tsx`

### P1 — FIXED
1. **BFF SSE proxy** — Added `text/event-stream` detection in `/api/kg/[...path]/route.ts`. Now passes through SSE responses without buffering.
2. **StreamRequest missing project_id** — Added `project_id` field to `StreamRequest` type, passed from `useProject()` in both chat pages' `stream.mutate()` calls.

### P2 — FIXED
3. **ResponseRenderer/InsightCards/SuggestedActions NOT WIRED** → Integrated into `ChatMessage.tsx`. Production `/chat` now renders rich response blocks (charts, tables, code), insight cards, and suggested actions — same as `/chat-demo`.

## Remaining (Go API team)
- Thread search returns null instead of [] for no matches
- Thread name max length validation (100 chars, currently accepts 150)
- Invalid UUID returns 500 (should 400)

## Report: ennam.kg.requirements/QA/reports/chat-deep-test-2026-04-22.md
