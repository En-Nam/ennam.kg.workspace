# Layer 2 — Browser E2E Results
**Date:** 2026-05-12
**Tester:** Claude Code (Chrome DevTools MCP)
**Environment:** Docker Compose — Dashboard http://localhost:3500
**Credentials:** admin / Admin123!@#

---

## Executive Summary

**Critical Gap Found:** The chat page (`/chat/[threadId]`) is **not wired to the new agentic streaming engine**. It uses the old non-agentic AI endpoint without a `tier` field. As a result, none of the agentic UI components (TierSelector, AgenticProgress, PhaseIndicator, ToolCallStepRow, KgNodeChip) render or function. This single root cause cascades into failures for UI-02 through UI-06.

---

## Results

| Test | Status | Notes |
|------|--------|-------|
| UI-01 | PARTIAL | Login works; QueryInputBar renders; TierSelector absent |
| UI-02 | FAIL | TierSelector never renders — `onTierChange` prop not passed by parent |
| UI-03 | FAIL | Query uses old engine (no `tier`); wrong SSE format; SQL error returned |
| UI-04 | FAIL | Cannot set Deep tier — TierSelector not rendered |
| UI-05 | FAIL | 0 KgNodeChips; old engine produces no KG node references |
| UI-06 | PARTIAL | UI not frozen after errors; input stays usable; offline scenario not testable |
| UI-07 | PASS | History persists and loads correctly after navigation |
| UI-08 | PARTIAL | BFF proxy works, SSE confirmed; no `tier` field in request body |

---

## Detailed Findings

### UI-01: Login & Navigation to Chat — PARTIAL ✅/❌

**Steps completed:**
- ✅ Login at `/login` with admin/Admin123!@# — succeeded
- ✅ Redirected to dashboard (314 nodes, C4K project)
- ✅ Navigated to `/chat`, created new thread
- ✅ Thread URL: `/chat/c8f3dac8-fee3-4cb6-9d3d-522804702739`
- ✅ QueryInputBar visible: C4K Staging selector + textarea
- ❌ TierSelector NOT visible — no Quick/Deep buttons exist in DOM

**Root cause:** `QueryInputBar.tsx:138-144` renders TierSelector conditionally:
```tsx
{threadId && onTierChange && (
  <TierSelector threadId={threadId} disabled={isStreaming} onChange={onTierChange} />
)}
```
The parent chat page does not pass `onTierChange`, so the component is never mounted.

---

### UI-02: TierSelector Toggle + Persistence — FAIL ❌

- ❌ DOM query for `[data-tier]` returns 0 elements
- ❌ Cannot click Quick/Deep buttons (don't exist)
- ❌ `localStorage.getItem('agentic-tier')` not set
- **Blocked by:** Missing `onTierChange` prop wiring

---

### UI-03: Quick Tier — Streaming Response — FAIL ❌

**Query sent:** "What tables are in C4K Staging?"
**Endpoint called:** `POST /api/kg/ai-query/stream` (correct BFF path)

**Request body (actual):**
```json
{
  "thread_id": "c8f3dac8-fee3-4cb6-9d3d-522804702739",
  "project_id": "a0000000-0000-0000-0000-000000000001",
  "data_source_id": "bde7aa64-97da-4e71-ae8a-2fdc10173c85",
  "query": "What tables are in C4K Staging?"
}
```
**Missing:** `"tier"` field → Go API routes to old non-agentic handler

**SSE events received (old format):**
```
event: progress  { stage: "parsing_intent" }
event: progress  { stage: "generating_sql" }
event: progress  { stage: "executing_query" }
event: error     { error_code: "QUERY_EXECUTION_FAILED", ... }
event: done      { generated_sql: "SELECT TOP 1000 Articles.*, BlogArticleWidgetMappingV2.*, ..." }
```

**Expected SSE format (new agentic):**
```
event: agent_start   { tier: "quick", max_iterations: 3 }
event: tool_call_start / tool_call_end
event: content
event: agent_done    { iterations, total_tokens }
event: done          { status: "complete" }
```

**SQL bug in old engine:** Generated `SELECT TOP 1000 Articles.*, BlogArticleWidgetMappingV2.*, BlogAuthorFollowV2.*, ...` — wildcard columns from tables not present in the FROM clause. MSSQL returns column prefix error.

**Agentic UI components:** 0 AgenticProgress, 0 PhaseIndicator, 0 ToolCallStepRow, 0 KgNodeChip

---

### UI-04: Deep Tier — Extended Streaming — FAIL ❌

- Cannot select Deep tier (TierSelector not rendered)
- Cannot test extended streaming, multiple iterations, or KgNodeChip badges

---

### UI-05: KgNodeChip Display — FAIL ❌

- `document.querySelectorAll('[data-testid="kg-node-chip"]').length` → **0**
- Old engine does not query the KG or return node references
- No agentic pipeline = no KG context = no chips

---

### UI-06: Error Resilience — PARTIAL ⚠️

**Tested:**
- ✅ Submitted 2 queries that returned errors
- ✅ After both errors: `textarea.disabled = false`, page not frozen, UI interactive
- ✅ No unhandled JS exceptions in console (only 1 minor a11y warning)
- ❌ Offline interruption test not performed — old engine responds in <5s, no window to interrupt

**Error display issue:** Raw MSSQL error text (with 22 repetitions of "General SQL Server error") is dumped directly into the chat bubble. No graceful error message formatting.

**Second query error:** "Query plan references unknown table 'INFORMATION_SCHEMA.TABLES'" — the old engine attempted to use `INFORMATION_SCHEMA.TABLES` which is blocked in this MSSQL instance.

---

### UI-07: Chat History Persistence — PASS ✅

- ✅ Navigated away to `/graph`, then returned to thread URL
- ✅ Previous messages (user + assistant error) loaded correctly
- ✅ Thread shows "2 messages | 2.6k tokens" in header
- ✅ Sidebar shows correct message count
- ✅ QueryInputBar ready for new input
- Note: "Retry" button absent on reload (expected — streaming-only UI state)

---

### UI-08: Network Request Inspection — PARTIAL ⚠️

**Confirmed:**
- ✅ SSE request visible in network log: `POST /api/kg/ai-query/stream` → 200
- ✅ Request URL contains `/api/kg/` (BFF proxy path)
- ✅ Response `Content-Type: text/event-stream`
- ✅ No failed HTTP requests (all 200)
- ❌ Request body does NOT include `"tier"` field
- ❌ SSE event names are old format (`progress/error/done`), not agentic (`agent_start/tool_call_start/agent_done/done`)

---

## Root Cause Analysis

### Primary Gap: `useAgenticStream` not wired into chat page

The agentic streaming hook and all its UI components were implemented, but the chat page (`src/app/(dashboard)/chat/[threadId]/page.tsx` or equivalent) does not:
1. Import or call `useAgenticStream`
2. Pass `onTierChange` to `QueryInputBar`
3. Include `tier` in the query payload

**Impact cascade:**
```
No onTierChange prop
  → TierSelector not rendered (UI-02 FAIL)
  → No tier in request body
  → Go API routes to old non-agentic handler
  → Old SSE format (progress/error/done)
  → AgenticProgress/PhaseIndicator/ToolCallStepRow never mount (UI-03/04 FAIL)
  → No KG node references → No KgNodeChips (UI-05 FAIL)
```

### Secondary Bug: Old engine SQL generation

The old non-agentic engine generates `SELECT TOP 1000 [table1].*, [table2.*, ...]` joining many tables without FROM clause for all of them → MSSQL column prefix error for every query about tables.

### Secondary Bug: Error display

Raw MSSQL error text with 22 repeated DB-Lib messages is shown directly to users.

---

## What Works

- ✅ Login / session management (iron-session cookie)
- ✅ Thread creation and listing
- ✅ Chat history persistence across navigation
- ✅ BFF proxy routing (`/api/kg/...` → Go API)
- ✅ SSE streaming infrastructure (old format)
- ✅ UI resilience (no frozen state after errors)
- ✅ Token counting and thread metadata stored correctly
- ✅ Data source selector (C4K Staging)

---

## What Needs Fixing

### P0 — Required for agentic engine to function
1. **Wire `useAgenticStream` into chat page** — pass `onTierChange` to `QueryInputBar`, send `tier` field in request, render `AgenticProgress`/`PhaseIndicator`/`ToolCallStepRow`

### P1 — Bugs discovered
2. **Old engine SQL generation** — `SELECT TOP 1000 t1.*, t2.*, ...` without proper JOINs causes MSSQL column prefix error
3. **INFORMATION_SCHEMA.TABLES blocked** — old engine assumes this view is available; it is not in C4K Staging

### P2 — UX issues
4. **Error message formatting** — raw MSSQL error with 22 repeated lines shown to user; needs graceful wrapping/truncation
