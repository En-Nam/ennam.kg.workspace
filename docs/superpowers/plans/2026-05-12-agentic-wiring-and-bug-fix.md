# Agentic Engine Wiring + Bug Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing `useAgenticStream` hook into the chat page, fix 2 SQL engine bugs in the Python NL query pipeline, and clean up raw MSSQL error display.

**Architecture:** Wave 1 — two agents work in parallel (web-dev on NextJS, backend-dev on Python). Wave 2 — one test-worker verifies with Chrome DevTools MCP + pytest after both are merged.

**Tech Stack:** Next.js 16 App Router · TypeScript strict · React hooks · Python 3.12 · pytest · uv · Chrome DevTools MCP

---

## ⚡ Wave 1 Dispatch

Dispatch these two agent sections **simultaneously**. They share no files.

| Agent | Section | Repos touched |
|-------|---------|--------------|
| `web-dev` | [Agent A — NextJS](#agent-a--nextjs-p0--p2) | `ennam.kg.next/` |
| `backend-dev` | [Agent B — Python](#agent-b--python-p1a--p1b) | `ennam.kg.python/` |

Wave 2 starts only after both agents are done.

---

## Agent A — NextJS (P0 + P2)

**Spec:** `docs/superpowers/specs/2026-05-12-agentic-wiring-and-bug-fix-design.md` §P0 + §P2

**Files:**
- Create: `ennam.kg.next/src/components/chat/AgenticStreamPanel.tsx`
- Modify: `ennam.kg.next/src/app/(dashboard)/chat/[threadId]/page.tsx`
- Modify: `ennam.kg.next/src/components/chat/ChatMessage.tsx`

**Verification:** `npm run build` (no TypeScript errors)

---

### Task A1: Create `AgenticStreamPanel`

**File:** `ennam.kg.next/src/components/chat/AgenticStreamPanel.tsx` (new)

Read these files first (understand the props each component expects):
- `ennam.kg.next/src/components/chat/AgenticProgress.tsx`
- `ennam.kg.next/src/components/chat/ClarificationPrompt.tsx`
- `ennam.kg.next/src/types/agentic.ts` (understand `AgenticStreamState`, `AgentTier`, `AgentPhase`)

- [ ] **Step 1: Create the component**

```tsx
'use client';

import { AgenticProgress } from './AgenticProgress';
import { ClarificationPrompt } from './ClarificationPrompt';
import type { AgenticStreamState, AgentTier } from '@/types/agentic';

interface AgenticStreamPanelProps {
  state: AgenticStreamState;
  threadId: string;
  tier: AgentTier;
  onResume: (sessionId: string, response: string) => void;
}

export function AgenticStreamPanel({
  state,
  onResume,
}: AgenticStreamPanelProps) {
  const visible = state.isStreaming || state.clarification !== null || state.error !== null;
  if (!visible) return null;

  return (
    <div className="border-t border-[#2A2E45] px-4 py-2 flex flex-col gap-2">
      {state.steps.length > 0 && (
        <AgenticProgress
          steps={state.steps}
          phase={state.phase}
          isStreaming={state.isStreaming}
          iterations={state.done?.iterations}
        />
      )}
      {state.content && !state.clarification && (
        <p className="text-sm text-[#F0F0F8] whitespace-pre-wrap">{state.content}</p>
      )}
      {state.clarification && (
        <ClarificationPrompt
          question={state.clarification.question}
          options={state.clarification.options}
          timeoutSeconds={state.clarification.timeoutSeconds}
          startedAt={state.clarification.startedAt}
          onSubmit={(response) => onResume(state.clarification!.sessionId, response)}
        />
      )}
      {state.error && !state.isStreaming && (
        <p className="text-sm text-[#FF6B6B]">Error: {state.error}</p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify file saved — check it compiles in isolation**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.next
npx tsc --noEmit --skipLibCheck 2>&1 | head -30
```

Expected: no errors referencing `AgenticStreamPanel.tsx`

---

### Task A2: Wire `useAgenticStream` into Chat Page

**File:** `ennam.kg.next/src/app/(dashboard)/chat/[threadId]/page.tsx`

Read first: `ennam.kg.next/src/hooks/use-agentic-stream.ts` (understand `start()`, `resumeFromClarification()`, `AgenticStreamRequest`)

- [ ] **Step 1: Replace the entire file content**

```tsx
'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { MessageSquare } from 'lucide-react';
import ThreadSidebar from '@/components/chat/ThreadSidebar';
import ThreadHeader from '@/components/chat/ThreadHeader';
import ChatMessageList from '@/components/chat/ChatMessageList';
import QueryInputBar from '@/components/chat/QueryInputBar';
import { AgenticStreamPanel } from '@/components/chat/AgenticStreamPanel';
import { useThread } from '@/hooks/use-threads';
import { useMessages } from '@/hooks/use-thread-messages';
import { useAgenticStream } from '@/hooks/use-agentic-stream';
import { useProject } from '@/lib/context/project';
import type { Thread, ThreadMessage } from '@/types/thread';
import type { AgentTier } from '@/types/agentic';

// ── Page ─────────────────────────────────────────────────────────────────────

export default function ThreadChatPage() {
  const params = useParams<{ threadId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { projectId } = useProject();
  const threadId = params.threadId;

  const [olderBefore, setOlderBefore] = useState<string | undefined>(undefined);
  const [tier, setTier] = useState<AgentTier>('quick');

  const { data: activeThread, isLoading: isLoadingThread } = useThread(threadId);
  const { data: messagePage, isLoading: isLoadingMessages } = useMessages(
    threadId,
    50,
    olderBefore,
  );
  const { state: agenticState, start, resumeFromClarification } = useAgenticStream();

  const messages: ThreadMessage[] = messagePage ?? [];
  const hasMore = messages.length > 0 && messages.length % 50 === 0;

  // Invalidate message + thread lists when stream finishes
  useEffect(() => {
    if (!agenticState.isStreaming && agenticState.done) {
      queryClient.invalidateQueries({ queryKey: ['messages', threadId] });
      queryClient.invalidateQueries({ queryKey: ['threads'] });
    }
  }, [agenticState.isStreaming, agenticState.done, threadId, queryClient]);

  const handleSelectThread = useCallback(
    (thread: Thread) => {
      setOlderBefore(undefined);
      router.push(`/chat/${thread.id}`);
    },
    [router],
  );

  const handleLoadMore = useCallback(() => {
    if (messages.length > 0) {
      setOlderBefore(messages[0].id);
    }
  }, [messages]);

  const lastDataSourceRef = useRef<string>('');

  const handleSubmit = useCallback(
    (query: string, dataSourceId: string) => {
      lastDataSourceRef.current = dataSourceId;
      start({
        thread_id: threadId,
        project_id: projectId,
        data_source_id: dataSourceId,
        query,
        tier,
        message_id: crypto.randomUUID(),
      });
    },
    [threadId, projectId, tier, start],
  );

  const handleResume = useCallback(
    (sessionId: string, response: string) => {
      resumeFromClarification(sessionId, threadId, response, tier);
    },
    [resumeFromClarification, threadId, tier],
  );

  const handleDeleted = useCallback(() => {
    router.push('/chat');
  }, [router]);

  return (
    <div className="flex h-full">
      {/* Left sidebar */}
      <ThreadSidebar
        projectId={projectId}
        activeThreadId={threadId}
        onSelectThread={handleSelectThread}
      />

      {/* Main area */}
      <div className="flex flex-1 flex-col min-w-0">
        {isLoadingThread ? (
          <div className="flex flex-1 items-center justify-center">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-[#00D4FF] border-t-transparent" />
          </div>
        ) : activeThread ? (
          <>
            <ThreadHeader thread={activeThread} onDeleted={handleDeleted} />
            <ChatMessageList
              messages={messages}
              hasMore={hasMore}
              onLoadMore={handleLoadMore}
              isLoadingMore={isLoadingMessages && !!olderBefore}
              isStreaming={false}
              currentStage={null}
              partialContent=""
            />
            <AgenticStreamPanel
              state={agenticState}
              threadId={threadId}
              tier={tier}
              onResume={handleResume}
            />
            <QueryInputBar
              projectId={projectId}
              threadId={threadId}
              tier={tier}
              onTierChange={setTier}
              isStreaming={agenticState.isStreaming}
              onSubmit={handleSubmit}
            />
          </>
        ) : (
          /* Thread not found */
          <div className="flex flex-1 flex-col items-center justify-center gap-4">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[#FF6B6B1A] border border-[#2A2E45]">
              <MessageSquare className="h-8 w-8 text-[#FF6B6B]" />
            </div>
            <h2 className="text-lg font-semibold text-[#F0F0F8]">Thread not found</h2>
            <p className="text-sm text-[#5C6080]">
              This thread may have been deleted or archived.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Run TypeScript check**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.next
npx tsc --noEmit --skipLibCheck 2>&1 | head -40
```

Expected: zero errors. If TypeScript reports an error about `AgenticStreamState` missing a field (e.g. `done.iterations`), open `src/types/agentic.ts` and align the field name with what's defined there.

- [ ] **Step 3: Commit A1 + A2**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.next
git add src/components/chat/AgenticStreamPanel.tsx
git add src/app/\(dashboard\)/chat/\[threadId\]/page.tsx
git commit -m "feat: wire useAgenticStream into chat page, add AgenticStreamPanel"
```

---

### Task A3: Fix Error Display in `ChatMessage`

**File:** `ennam.kg.next/src/components/chat/ChatMessage.tsx`

Read the file first — find the `<p>` that renders `message.content` for assistant messages (around line 64).

- [ ] **Step 1: Add `formatErrorContent` utility and use it**

Find this exact block in `ChatMessage.tsx`:
```tsx
        {/* Text content */}
        {message.content && (
          <div className="rounded-xl rounded-bl-sm border border-[#2A2E45] bg-[#1E2235] px-4 py-3">
            <p className="text-sm text-[#F0F0F8] whitespace-pre-wrap">{message.content}</p>
          </div>
        )}
```

Replace it with:
```tsx
        {/* Text content */}
        {message.content && (
          <div className="rounded-xl rounded-bl-sm border border-[#2A2E45] bg-[#1E2235] px-4 py-3">
            <p className="text-sm text-[#F0F0F8] whitespace-pre-wrap">
              {formatErrorContent(message.content)}
            </p>
          </div>
        )}
```

Then add the utility function **before** the `export default function ChatMessage` line:

```typescript
/** Strip repeated DB-Lib noise from MSSQL error messages stored in message.content. */
function formatErrorContent(content: string): string {
  if (!content.includes('DB-Lib error message')) return content;
  const firstLine = content.split('\n')[0];
  return firstLine.replace(/\s*DB-Lib error.*$/s, '').trim();
}
```

- [ ] **Step 2: Verify build**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.next
npm run build 2>&1 | tail -20
```

Expected: `✓ Compiled successfully` (or similar). Zero TypeScript errors.

- [ ] **Step 3: Commit**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.next
git add src/components/chat/ChatMessage.tsx
git commit -m "fix: truncate raw MSSQL DB-Lib error noise in chat message display"
```

---

### Task A4: Agent A Checkpoint

- [ ] **Write checkpoint file**

Create `.serena/checkpoint/web-dev-2026-05-12.md` (append if exists):

```markdown
## Wave 1 — web-dev session (append)

### Done
- Created AgenticStreamPanel.tsx
- Replaced useStreamQuery with useAgenticStream in [threadId]/page.tsx
- Added tier state, query invalidation useEffect, AgenticStreamPanel wiring
- QueryInputBar now receives threadId + tier + onTierChange
- formatErrorContent() added to ChatMessage.tsx

### Verification
- npx tsc --noEmit: 0 errors
- npm run build: passes

### Next
- Wave 2 test-worker to verify with Chrome DevTools MCP
```

---

## Agent B — Python (P1a + P1b)

**Spec:** `docs/superpowers/specs/2026-05-12-agentic-wiring-and-bug-fix-design.md` §P1a + §P1b

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/nl_query/sql_generator.py`
- Modify: `ennam.kg.python/src/ennam_kg/nl_query/prompts.py`
- Modify: `ennam.kg.python/src/ennam_kg/nl_query/intent_parser.py`

**Verification:** `uv run pytest tests/ -v` — all existing tests must still pass

---

### Task B1: Fix SQL SELECT Clause (P1a)

**File:** `ennam.kg.python/src/ennam_kg/nl_query/sql_generator.py`

Read the file first. The bug is on line 31: `select_clause = ", ".join(f"{t}.*" for t in plan.tables)` — this generates `t1.*, t2.*, t3.*` for ALL plan tables, but only `plan.tables[0]` is in the FROM clause. Tables without JOINs cause MSSQL error 107.

- [ ] **Step 1: Write failing tests first**

Check for an existing test file for `sql_generator`. If none exists, create `ennam.kg.python/tests/test_sql_generator.py`:

```python
"""Tests for sql_generator.generate_sql (BA-011 FR-003)."""
import pytest
from ennam_kg.nl_query.sql_generator import generate_sql, SQLGenerationError
from ennam_kg.nl_query.intent_parser import QueryPlan, JoinSpec


def test_mssql_single_table_select():
    """Single table: SELECT TOP N table.* FROM table."""
    plan = QueryPlan(tables=["Articles"], joins=[], limit=100)
    sql, params = generate_sql(plan, dialect="mssql")
    assert "SELECT TOP 100 Articles.*" in sql
    assert "FROM Articles" in sql
    assert params == []


def test_mssql_multi_table_no_join_only_primary_in_select():
    """Multi-table plan with no JOINs: only primary table appears in SELECT."""
    plan = QueryPlan(
        tables=["Articles", "BlogArticleWidgetMappingV2", "BlogAuthorV2"],
        joins=[],
        limit=1000,
    )
    sql, params = generate_sql(plan, dialect="mssql")
    assert "Articles.*" in sql
    assert "BlogArticleWidgetMappingV2" not in sql
    assert "BlogAuthorV2" not in sql
    assert "FROM Articles" in sql


def test_mssql_multi_table_with_join_includes_joined_table():
    """Multi-table plan with explicit JOIN: joined table appears in SELECT."""
    plan = QueryPlan(
        tables=["Articles", "Users"],
        joins=[JoinSpec(from_col="Articles.user_id", to_col="Users.id", type="inner")],
        limit=50,
    )
    sql, params = generate_sql(plan, dialect="mssql")
    assert "Articles.*" in sql
    assert "Users.*" in sql
    assert "INNER JOIN Users ON Articles.user_id = Users.id" in sql


def test_raises_on_empty_tables():
    """No tables raises SQLGenerationError."""
    plan = QueryPlan(tables=[], joins=[])
    with pytest.raises(SQLGenerationError, match="No tables"):
        generate_sql(plan)
```

- [ ] **Step 2: Run tests — confirm they fail on the right assertions**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.python
uv run pytest tests/test_sql_generator.py -v 2>&1
```

Expected: `test_mssql_multi_table_no_join_only_primary_in_select` FAILS (because the bug still exists). Others may pass.

- [ ] **Step 3: Apply the fix**

In `sql_generator.py`, find the `else` branch of the `if plan.aggregations:` block (line ~31) and replace:

```python
    else:
        select_clause = ", ".join(f"{t}.*" for t in plan.tables)
```

With:

```python
    else:
        joined_tables = {j.to_col.split(".")[0] for j in plan.joins}
        valid_select_tables = [plan.tables[0]] + [
            t for t in plan.tables[1:] if t in joined_tables
        ]
        select_clause = ", ".join(f"{t}.*" for t in valid_select_tables)
```

- [ ] **Step 4: Run tests — confirm all pass**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.python
uv run pytest tests/test_sql_generator.py -v 2>&1
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Run full test suite — confirm no regressions**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.python
uv run pytest tests/ -v 2>&1 | tail -20
```

Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.python
git add tests/test_sql_generator.py src/ennam_kg/nl_query/sql_generator.py
git commit -m "fix: sql_generator SELECT clause only includes tables present in FROM/JOIN"
```

---

### Task B2: Fix INFORMATION_SCHEMA Hallucination (P1b)

**Files:**
- `ennam.kg.python/src/ennam_kg/nl_query/prompts.py`
- `ennam.kg.python/src/ennam_kg/nl_query/intent_parser.py`

Read both files first.

- [ ] **Step 1: Write failing tests**

Check for existing tests for `intent_parser`. If none exist, create `ennam.kg.python/tests/test_intent_parser.py`:

```python
"""Tests for intent_parser validation (BA-011 FR-002)."""
import pytest
from ennam_kg.nl_query.intent_parser import QueryPlan, _validate_plan, IntentParseError
from ennam_kg.nl_query.prompts import get_intent_parsing_prompt

SCHEMA = {"tables": {"Articles": {"columns": {"id": "int", "title": "varchar"}, "foreign_keys": []}}}


def test_validate_rejects_information_schema():
    """INFORMATION_SCHEMA.TABLES raises IntentParseError with helpful message."""
    plan = QueryPlan(tables=["INFORMATION_SCHEMA.TABLES"])
    with pytest.raises(IntentParseError, match="System views are not accessible"):
        _validate_plan(plan, SCHEMA)


def test_validate_rejects_sys_prefix():
    """sys.tables raises IntentParseError."""
    plan = QueryPlan(tables=["sys.tables"])
    with pytest.raises(IntentParseError, match="System views are not accessible"):
        _validate_plan(plan, SCHEMA)


def test_validate_accepts_known_table():
    """Known table passes validation."""
    plan = QueryPlan(tables=["Articles"])
    _validate_plan(plan, SCHEMA)  # no exception
    assert plan.tables == ["Articles"]


def test_validate_rejects_unknown_table():
    """Unknown table raises IntentParseError with 'unknown table'."""
    plan = QueryPlan(tables=["NonExistentTable"])
    with pytest.raises(IntentParseError, match="unknown table"):
        _validate_plan(plan, SCHEMA)


def test_prompt_includes_no_system_views_rule():
    """Prompt explicitly forbids INFORMATION_SCHEMA."""
    prompt = get_intent_parsing_prompt("list all tables", SCHEMA)
    assert "INFORMATION_SCHEMA" in prompt
    assert "Do not use" in prompt or "not use" in prompt.lower()
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.python
uv run pytest tests/test_intent_parser.py -v 2>&1
```

Expected: `test_validate_rejects_information_schema`, `test_validate_rejects_sys_prefix`, `test_prompt_includes_no_system_views_rule` FAIL.

- [ ] **Step 3: Fix `prompts.py`**

In `get_intent_parsing_prompt()`, find the Rules section (the last multi-line f-string, around line 106):

```python
Rules:
- Output raw JSON only. No explanation. No markdown fences.
- Pick the best matching tables from the schema for the query.
- Only reference tables and columns that exist in the schema.
- Use foreign key relationships for JOINs.
- If no LIMIT is implied, set limit to null."""
```

Replace with:

```python
Rules:
- Output raw JSON only. No explanation. No markdown fences.
- Pick the best matching tables from the schema for the query.
- Only reference tables and columns that exist in the schema.
- Do not use INFORMATION_SCHEMA, sys, or any database system views. Only use tables from the schema listed above.
- Use foreign key relationships for JOINs.
- If no LIMIT is implied, set limit to null."""
```

- [ ] **Step 4: Fix `intent_parser.py` — add system view guard to `_validate_plan`**

In `_validate_plan`, find the `for table in plan.tables:` loop. Add a system-view guard **before** the existing `if table in known_tables:` check:

```python
def _validate_plan(plan: QueryPlan, schema: dict) -> None:
    known_tables = set(schema.get("tables", {}).keys())
    lower_to_actual = {t.lower(): t for t in known_tables}

    corrected_tables: list[str] = []
    for table in plan.tables:
        # Guard: reject system views before checking known tables
        if "INFORMATION_SCHEMA" in table.upper() or table.lower().startswith("sys."):
            raise IntentParseError(
                "System views are not accessible. Use the provided schema to answer this question."
            )
        if table in known_tables:
            corrected_tables.append(table)
        elif table.lower() in lower_to_actual:
            corrected_tables.append(lower_to_actual[table.lower()])
        else:
            raise IntentParseError(
                f"Query plan references unknown table '{table}'. Available: {sorted(known_tables)}"
            )
    plan.tables = corrected_tables
```

- [ ] **Step 5: Run tests — confirm all pass**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.python
uv run pytest tests/test_intent_parser.py -v 2>&1
```

Expected: all 5 tests PASS.

- [ ] **Step 6: Run full suite — no regressions**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.python
uv run pytest tests/ -v 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
cd d:/Projects/EnNam/ennam.kg/ennam.kg.python
git add tests/test_intent_parser.py \
        src/ennam_kg/nl_query/prompts.py \
        src/ennam_kg/nl_query/intent_parser.py
git commit -m "fix: block INFORMATION_SCHEMA in nl_query prompt and validate guard"
```

---

### Task B3: Agent B Checkpoint

- [ ] **Write checkpoint**

Create `.serena/checkpoint/backend-dev-2026-05-12.md` (append if exists):

```markdown
## Wave 1 — backend-dev session (append)

### Done
- sql_generator.py: SELECT clause now only includes tables present in FROM or JOINed
- prompts.py: added explicit rule against INFORMATION_SCHEMA/sys views
- intent_parser._validate_plan: system view guard raises helpful error
- 9 new tests added (test_sql_generator.py + test_intent_parser.py)

### Verification
- uv run pytest: all tests pass, no regressions

### Next
- Wave 2 test-worker to verify via API smoke tests and accuracy eval
```

---

## Agent C — Test Worker (Wave 2 Verification)

**Trigger:** Run AFTER both Agent A and Agent B are merged and Docker services are rebuilt.

**Prerequisite:** `docker compose up -d --build` completed successfully.

**Tools:** Chrome DevTools MCP + pytest

---

### Task C1: Browser E2E — UI-01 through UI-08

Use Chrome DevTools MCP tools. Follow this sequence:

- [ ] **UI-01: Login and navigate to chat**

```
navigate_page → http://localhost:3500/login
fill_form → { username: "admin", password: "Admin123!@#" }
click → Sign In button
wait_for → ["Dashboard", "Chat"]
navigate_page → http://localhost:3500/chat
click → New Thread
wait_for → ["/chat/"]  (URL changes to thread URL)
take_snapshot
```

**Pass criteria:** Thread URL contains `/chat/<uuid>`, QueryInputBar visible with C4K Staging dropdown.

- [ ] **UI-02: TierSelector renders and toggles**

```
take_snapshot
```

**Pass criteria:** Snapshot contains buttons with text "Quick" AND "Deep". If absent → FAIL, record finding.

```
click → "Deep" button
evaluate_script → () => localStorage.getItem('agentic-tier')
```

**Pass criteria:** `localStorage` returns `"deep"`.

- [ ] **UI-03: Quick tier — verify agentic SSE events**

```
fill → textarea with "How many users are in the system?"
press_key → Enter
wait_for → ["agent_start", "tool_call", "steps", "EXPLORE", "PLAN"]  -- any agentic indicator
take_screenshot
list_network_requests → filter fetch/xhr
get_network_request → the /api/kg/ai-query/stream request
```

**Pass criteria:**
- Request body includes `"tier":"quick"`
- Response SSE contains `event: agent_start` (not `event: progress`)
- `AgenticProgress` steps appear in DOM snapshot

- [ ] **UI-04: Deep tier — extended exploration**

```
click → "Deep" tier button
fill → textarea with "List all tables and their row counts in C4K Staging"
press_key → Enter
wait_for → ["agent_done", "complete", "iterations"] -- wait up to 120s
take_screenshot
```

**Pass criteria:** Request body has `"tier":"deep"`, ≥2 tool call steps visible in AgenticProgress.

- [ ] **UI-05: KgNodeChip**

```
evaluate_script → () => document.querySelectorAll('[data-testid="kg-node-chip"]').length
```

**Pass criteria:** Count > 0. If 0, check if the response referenced any KG nodes. Document result.

- [ ] **UI-06: Error resilience**

```
fill → textarea with "DROP TABLE Users"
press_key → Enter
wait_for → ["error", "rejected", "DDL"] -- error message about DDL rejection
evaluate_script → () => ({
  inputDisabled: document.querySelector('textarea')?.disabled,
  pageTitle: document.title
})
```

**Pass criteria:** Input remains enabled (not `true`), page title unchanged. Error message is single-line (no 22x DB-Lib repetitions).

- [ ] **UI-07: Chat history persistence**

```
navigate_page → http://localhost:3500/graph
navigate_page → back to the thread URL
wait_for → ["message", "New Thread"]
take_snapshot
```

**Pass criteria:** Previous messages still visible in ChatMessageList.

- [ ] **UI-08: Network inspection — tier in payload**

```
list_network_requests → filter fetch
```

**Pass criteria:** All `/api/kg/ai-query/stream` requests include `"tier"` in request body. No requests missing the tier field.

- [ ] **Record results**

Write results to `docs/superpowers/test-results/browser-e2e-wave2-results.md`:

```markdown
# Wave 2 Browser E2E Results
Date: 2026-05-12 (Wave 2)

| Test | Status | Notes |
|------|--------|-------|
| UI-01 | PASS/FAIL | ... |
...
```

---

### Task C2: Layer 1 API Smoke Tests

- [ ] **Run smoke tests**

```bash
cd d:/Projects/EnNam/ennam.kg
pip install -r tests/e2e/requirements.txt  # if not already installed
pytest tests/e2e/test_api_smoke.py -v --timeout=300 2>&1
```

Expected: API-01, API-02, API-03, API-04, API-06 all PASS. (API-05 may skip if no clarification triggered.)

- [ ] **If any test fails: capture output and check logs**

```bash
docker compose logs kg-server --tail=50
docker compose logs indexer --tail=50
```

Document failures in `docs/superpowers/test-results/api-smoke-wave2.txt`.

---

### Task C3: Layer 3 Accuracy Evaluation

- [ ] **Run accuracy tests**

```bash
cd d:/Projects/EnNam/ennam.kg
pytest tests/e2e/test_accuracy.py -v --timeout=600 -s 2>&1 | tee docs/superpowers/test-results/accuracy-wave2.txt
```

Expected: avg score ≥ 2.0/3.0 across ACC-01 to ACC-12.

- [ ] **Check summary at end of output**

The `print_accuracy_summary` fixture prints a table at session end. Verify the "Average" row shows ≥ 2.0.

---

### Task C4: Wave 2 Final Report + Checkpoint

- [ ] **Write final report**

Append to `docs/superpowers/test-results/browser-e2e-wave2-results.md`:

```markdown
## API Smoke Tests
- Passed: N/5
- Failed: [list]

## Accuracy Evaluation
- Average: X.X/3.0
- Cases ≥ 2.0: N/12

## Overall: PASS / FAIL
```

- [ ] **Write checkpoint**

Create `.serena/checkpoint/test-worker-2026-05-12.md`:

```markdown
# Checkpoint: test-worker — 2026-05-12 Wave 2

## Done
- UI-01 to UI-08 browser E2E re-run (Chrome DevTools MCP)
- Layer 1 API smoke tests
- Layer 3 accuracy evaluation

## Results
- Browser: N/8 pass
- API Smoke: N/5 pass
- Accuracy: avg X.X/3.0

## Blockers
- [any failures that need follow-up]
```

---

## Self-Review Checklist (completed inline)

- ✅ **Spec coverage:** P0 (Tasks A1+A2), P2 (Task A3), P1a (Task B1), P1b (Task B2), Wave 2 (Tasks C1–C4)
- ✅ **No placeholders:** All steps contain actual code or exact commands
- ✅ **Type consistency:** `AgentTier` used consistently; `AgenticStreamState` fields (`state.steps`, `state.phase`, `state.content`, `state.clarification`, `state.done`, `state.error`) match what `use-agentic-stream.ts` actually sets
- ✅ **Test-before-implement:** B1 and B2 write failing tests first; A tasks verified via `tsc --noEmit` + `npm run build`
- ✅ **No regressions:** Both B tasks run full `uv run pytest` suite after changes
