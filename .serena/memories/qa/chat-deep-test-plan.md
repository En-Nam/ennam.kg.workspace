# /chat Deep Test Plan — 70 Test Cases

**File**: ennam.kg.requirements/QA/testcases/chat-deep-test-plan.md

## 9 Test Groups
- A: Thread Management (12 tests) — CRUD, rename, archive, search, ordering
- B: Query Input & Validation (8 tests) — DS selector, char limits, Enter/Shift+Enter
- C: SSE Streaming (10 tests) — progress events, indicators, done/error, persistence
- D: Message Display & History (8 tests) — rendering, scroll, pagination, reload
- E: Multi-Turn Context (5 tests) — follow-up, independent threads, context window
- F: Response Rendering (6 tests) — plain text, SQL, partial, empty
- G: Tool Menu (8 tests) — NOT wired in /chat (only /chat-demo)
- H: Error Handling (8 tests) — network, invalid ID, special chars, double-click
- I: Data Source Integration (5 tests) — selector, switch, status

## Key Finding from Code Review
ResponseRenderer, ToolMenu, SuggestedActions, InsightCards — wired into production /chat since 2026-04-23 fixes.

## E2E Verification (2026-05-11)
- Full pipeline verified: User query → SSE → markdown block + table block + suggested actions → Browser display
- Two blockers found and fixed: missing ENCRYPTION_KEY env, pymssql charset encoding
- See `archive/qa-runs/chat-e2e-verification-2026-05-11.md` for full report

## Execution Order
1. Phase 1: Non-AI tests (A, B, D partial, H, I) — ~35 tests, no budget
2. Phase 2: AI tests (C, E, F) — ~21 tests, ~$0.15 budget
3. Phase 3: /chat-demo integration (G) — ~8 tests
