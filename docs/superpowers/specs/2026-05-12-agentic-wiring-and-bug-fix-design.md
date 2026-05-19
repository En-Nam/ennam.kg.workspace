# Design: Agentic Engine Wiring + Bug Fixes
**Date:** 2026-05-12
**Status:** Approved
**Scope:** P0 (UI wiring) + P1 (SQL engine bugs) + P2 (error UX)
**Approach:** Wave 1 — 2 parallel agents → Wave 2 — 1 verification agent

---

## Context

Browser E2E testing (2026-05-12) revealed that the new agentic streaming engine is fully implemented but not wired into the chat page. All queries fall back to the old non-agentic Python handler (`/api/v1/ai/stream`) because the `tier` field is never sent. This cascades into all agentic UI components never rendering.

Two additional bugs exist in the old non-agentic SQL engine (P1a, P1b) and one UX issue in error display (P2).

---

## P0 — Wire `useAgenticStream` into Chat Page

**File:** `ennam.kg.next/src/app/(dashboard)/chat/[threadId]/page.tsx`
**New file:** `ennam.kg.next/src/components/chat/AgenticStreamPanel.tsx`

### Changes to `ThreadChatPage`

1. **Remove** `useStreamQuery` import and call
2. **Add** `useAgenticStream` from `@/hooks/use-agentic-stream`
3. **Add** `useQueryClient` from `@tanstack/react-query`
4. **Add** tier state: `const [tier, setTier] = useState<AgentTier>('quick')`
5. **Update** `handleSubmit` to call `agenticStream.start()` with:
   - All existing fields (`thread_id`, `project_id`, `data_source_id`, `query`)
   - `tier` from state
   - `message_id: crypto.randomUUID()`
6. **Add** `useEffect` for query invalidation after stream completion:
   ```tsx
   useEffect(() => {
     if (!agenticState.isStreaming && agenticState.done) {
       queryClient.invalidateQueries({ queryKey: ['messages', threadId] });
       queryClient.invalidateQueries({ queryKey: ['threads'] });
     }
   }, [agenticState.isStreaming, agenticState.done, threadId, queryClient]);
   ```
7. **Update** `QueryInputBar` to receive: `threadId`, `tier`, `onTierChange={setTier}`
8. **Pass neutral values** to `ChatMessageList` for old streaming props — do NOT modify `ChatMessageList.tsx` itself:
   `isStreaming={false}`, `currentStage={null}`, `partialContent=""`, `streamBlocks={[]}`, `streamInsights={[]}`, `streamActions={[]}`.
   Streaming display is fully delegated to `AgenticStreamPanel`.
9. **Add** `AgenticStreamPanel` between `ChatMessageList` and `QueryInputBar`

### New `AgenticStreamPanel` component

Renders during streaming only (`agenticState.isStreaming === true`):
- `AgenticProgress` (steps, phase, isStreaming, iterations from done data)
- Live text from `agenticState.content` (rendered as `<p>`)
- `ClarificationPrompt` when `agenticState.clarification` is non-null, wired to `agenticStream.resumeFromClarification()`

Props:
```tsx
interface AgenticStreamPanelProps {
  state: AgenticStreamState;
  threadId: string;
  tier: AgentTier;
  onResume: (sessionId: string, response: string) => void;
}
```

### Layout after fix

```
┌─────────────────────────────────┐
│ ChatMessageList (history only)  │
├─────────────────────────────────┤
│ AgenticStreamPanel (streaming)  │  ← visible only while isStreaming
│  · AgenticProgress (steps)      │
│  · partialContent text          │
│  · ClarificationPrompt (cond.)  │
├─────────────────────────────────┤
│ QueryInputBar (tier + submit)   │  ← TierSelector now renders
└─────────────────────────────────┘
```

---

## P1a — SQL SELECT Clause Bug

**File:** `ennam.kg.python/src/ennam_kg/nl_query/sql_generator.py`
**Line:** 31

**Before:**
```python
select_clause = ", ".join(f"{t}.*" for t in plan.tables)
```

**After:**
```python
joined_tables = {j.to_col.split('.')[0] for j in plan.joins}
valid_select_tables = [plan.tables[0]] + [
    t for t in plan.tables[1:] if t in joined_tables
]
select_clause = ", ".join(f"{t}.*" for t in valid_select_tables)
```

**Why:** `plan.tables` contains all tables the LLM planned to use, but only `plan.tables[0]` is placed in the FROM clause. Additional tables are only valid in SELECT if they have a corresponding JOIN definition. MSSQL raises error 107 (column prefix mismatch) when a table is referenced in SELECT but not in FROM/JOIN.

---

## P1b — INFORMATION_SCHEMA Hallucination

**Files:**
- `ennam.kg.python/src/ennam_kg/nl_query/prompts.py` (prompt rule)
- `ennam.kg.python/src/ennam_kg/nl_query/intent_parser.py` (_validate_plan guard)

### Fix 1 — Prompt rule (`prompts.py:111`)

Add to the Rules section of `get_intent_parsing_prompt()`:
```
- Do not use INFORMATION_SCHEMA, sys, or any database system views.
  Only use tables from the schema listed above.
```

### Fix 2 — Validate guard (`intent_parser.py:_validate_plan`)

Before the existing `known_tables` check, intercept system view references:
```python
if "INFORMATION_SCHEMA" in table.upper() or table.lower().startswith("sys."):
    raise IntentParseError(
        "System views are not accessible. Use the provided schema to answer this question."
    )
```

**Why:** C4K Staging MSSQL blocks `INFORMATION_SCHEMA.TABLES` access. The prompt lacked an explicit prohibition, so Claude sometimes suggests it for "list tables" queries. The guard provides a clearer error message than the generic "unknown table" message.

---

## P2 — Error Display UX

**File:** `ennam.kg.next/src/components/chat/ChatMessage.tsx`

Add a `formatErrorContent()` utility before the content render at line 64:

```typescript
function formatErrorContent(content: string): string {
  if (!content.includes('DB-Lib error message')) return content;
  // Strip repeated DB-Lib noise; keep only the first meaningful line
  const firstLine = content.split('\n')[0];
  return firstLine.replace(/\s*DB-Lib error.*$/s, '').trim();
}
```

Use in the content render:
```tsx
<p className="text-sm text-[#F0F0F8] whitespace-pre-wrap">
  {formatErrorContent(message.content)}
</p>
```

**Why:** Raw MSSQL errors include 22 repetitions of "General SQL Server error: Check messages from the SQL Server" which provides no value to end users and floods the chat bubble.

---

## Wave 1 — Parallel Agents

| Agent | Branch | Files | Verification |
|-------|--------|-------|-------------|
| `web-dev` | `fix/p0-agentic-wiring` | `page.tsx`, `AgenticStreamPanel.tsx`, `ChatMessage.tsx` | `npm run build` passes |
| `backend-dev` | `fix/p1-sql-engine` | `sql_generator.py`, `prompts.py`, `intent_parser.py` | `uv run pytest` passes |

No shared files. Agents work independently. Each writes a checkpoint on completion.

---

## Wave 2 — Verification Agent

**Trigger:** After both Wave 1 branches are merged.
**Agent:** `test-worker`
**Tools:** Chrome DevTools MCP + pytest

### Browser E2E (UI-01 through UI-08)
Re-run against fixed code. Expected outcomes:
- UI-01: PASS (TierSelector visible)
- UI-02: PASS (Quick/Deep toggle works, persists to localStorage)
- UI-03: PASS (agent_start → tool_call_start/end → content → agent_done → done)
- UI-04: PASS (Deep tier, ≥2 tool calls)
- UI-05: PASS (KgNodeChip renders for KG node references)
- UI-06: PASS (truncated error, UI not frozen)
- UI-07: PASS (history persists — already passing)
- UI-08: PASS (tier field in request body)

### Layer 1 — API Smoke Tests
```bash
cd ennam.kg && pytest tests/e2e/test_api_smoke.py -v
```

### Layer 3 — Accuracy Evaluation
```bash
cd ennam.kg && pytest tests/e2e/test_accuracy.py -v
```

### Success Gate
- All 8 UI tests pass (or explicitly skipped with justification)
- Layer 1: all 5 runnable tests pass
- Layer 3: avg accuracy score ≥ 2.0/3.0 across 12 cases

---

## What Is NOT Changed

- `ChatMessageList` props for persisted messages (unchanged)
- `useMessages` / `useThread` hooks (unchanged)
- Go API routing logic (unchanged — already routes correctly when tier is set)
- Agentic Python engine (`agentic/engine.py`, `agentic/tools.py`) — already working
- Any files not listed above

---

## Success Criteria

1. Submitting a query in the chat page sends `tier: "quick"` in the request body
2. SSE events received are `agent_start → tool_call_start/end → content → agent_done → done`
3. `AgenticProgress` and `TierSelector` are visible in the browser DOM
4. Old SQL engine errors display as single-line truncated messages
5. All Wave 2 success gate criteria met
