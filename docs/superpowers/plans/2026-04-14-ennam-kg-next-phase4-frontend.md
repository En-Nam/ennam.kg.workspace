# Phase 4 Frontend — AI Query UI/UX Enhancement

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the simple AI query page into a Cursor-style conversational interface with SSE streaming, rich response blocks (charts, markdown, code), 9-tool menu, AI insights, and favorites.

**Architecture:** Complete rewrite of `/query` page. Thread-based conversations with SSE streaming through BFF proxy. Multi-block responses rendered progressively. Recharts for interactive charts, react-markdown for text, Prism.js for syntax highlighting. 9-tool toolbar with keyboard shortcuts. Feature-flaggable via BA-016 settings.

**Tech Stack:** Next.js 16, React 19, TypeScript strict, TanStack Query 5, Recharts 2, react-markdown 9, Prism.js, iron-session 8, shadcn/ui, Tailwind CSS 4

**Backend status:** Go API Phase 4 NOT STARTED. Frontend hooks use 404 graceful handling. SSE streaming requires backend — will show "Connecting..." state until available.

---

## New Dependencies to Install

```bash
npm install recharts react-markdown remark-gfm rehype-highlight
```

---

## File Structure

### New Files (~35)

```
src/types/
├── thread.ts                       # Thread, ThreadMessage, ThreadPreview, StreamRequest
├── response-block.ts               # MarkdownBlock, CodeBlock, ChartBlock, TableBlock, InteractiveVizBlock
├── insight.ts                      # Insight, SuggestedAction, ComparisonResult
└── favorite.ts                     # Favorite, FavoriteList

src/hooks/
├── use-threads.ts                  # useThreads, useThread, useCreateThread, useArchiveThread
├── use-thread-messages.ts          # useMessages (cursor pagination), useStreamQuery (SSE)
├── use-favorites.ts                # useFavorites, useCreateFavorite, useDeleteFavorite
└── use-insights.ts                 # useInsights, useCompare

src/lib/
└── streaming/
    └── sse-handler.ts              # SSE event parser for 9 event types

src/app/(dashboard)/
├── chat/                           # NEW — replaces /query
│   └── page.tsx                    # Main chat page (thread sidebar + chat area)
├── chat/[threadId]/
│   └── page.tsx                    # Thread-specific chat view
└── favorites/
    └── page.tsx                    # Favorites management page

src/components/chat/
├── ThreadSidebar.tsx               # Thread list + search + favorites section
├── ThreadListItem.tsx              # Single thread entry in sidebar
├── ChatMessageList.tsx             # Scrollable message container with lazy-load
├── ChatMessage.tsx                 # Message bubble (user/assistant) with blocks
├── StreamingIndicator.tsx          # Progress stages + typewriter cursor
├── QueryInputBar.tsx               # Input with data source selector + send
├── ThreadHeader.tsx                # Thread name (editable) + metadata
├── ToolMenu.tsx                    # 9-tool horizontal toolbar
├── InsightCards.tsx                # Insight cards with confidence badges
├── SuggestedActions.tsx            # 3 action buttons + custom input
└── CompareView.tsx                 # Side-by-side comparison display

src/components/response/
├── ResponseRenderer.tsx            # Dispatches block type → renderer
├── MarkdownBlock.tsx               # react-markdown with remark-gfm
├── CodeBlock.tsx                   # Syntax-highlighted code with copy button
├── ChartBlock.tsx                  # Recharts bar/line/pie/scatter
├── TableBlock.tsx                  # Paginated data table with sort/filter
└── AggregationRationale.tsx        # "Data was aggregated..." notice
```

### Files to Modify

```
src/components/layout/Sidebar.tsx   # Replace "AI Query" link with "Chat" + add "Favorites"
src/app/(dashboard)/query/page.tsx  # Redirect to /chat (or remove)
```

---

## Step 1: BA-017 — Conversational AI Interface (Foundation)

### Task 1: Thread + Message Types

**Files:**
- Create: `src/types/thread.ts`

```typescript
export interface Thread {
  id: string;
  user_id: string;
  project_id: string;
  name: string;
  is_archived: boolean;
  total_tokens_used: number;
  created_at: string;
  updated_at: string;
  last_message_at: string;
  message_count: number;
}

export interface ThreadMessage {
  id: string;
  thread_id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  ai_query_id?: string;
  response_blocks?: ResponseBlock[];  // BA-018
  insights?: Insight[];               // BA-019
  suggested_actions?: SuggestedAction[]; // BA-019
}

export interface StreamRequest {
  thread_id?: string;
  data_source_id: string;
  query: string;
}

export interface MessagePage {
  messages: ThreadMessage[];
  has_more: boolean;
  total_count: number;
}

// SSE event payloads
export interface ProgressEvent {
  stage_name: string;
  stage_label: string;
  timestamp: string;
}

export interface ContentEvent {
  token: string;
}

export interface DoneEvent {
  message_id: string;
  tokens_input: number;
  tokens_output: number;
  latency_ms: number;
  generated_sql: string;
  result_summary: string;
  thread_id: string;
}

export interface ErrorEvent {
  error_code: string;
  error_message: string;
  partial_content: string;
}
```

- [ ] **Step 1:** Write types file
- [ ] **Step 2:** Verify: `npx tsc --noEmit`
- [ ] **Step 3:** Commit: `feat(types): add thread and message types for BA-017`

### Task 2: Response Block Types

**Files:**
- Create: `src/types/response-block.ts`
- Create: `src/types/insight.ts`
- Create: `src/types/favorite.ts`

Define all block types (markdown, code, chart, table, interactive_viz), Insight, SuggestedAction, Favorite, ComparisonResult.

- [ ] **Step 1:** Write all 3 type files
- [ ] **Step 2:** Verify + commit: `feat(types): add response block, insight, and favorite types for BA-018/019`

### Task 3: SSE Event Handler

**Files:**
- Create: `src/lib/streaming/sse-handler.ts`

A reusable SSE parser that:
1. Opens EventSource or fetch + ReadableStream to `/api/kg/ai-query/stream`
2. Parses 9 event types: progress, content, error, done, format_metadata, block_start, block_content, block_end, suggested_actions
3. Calls typed callbacks for each event
4. Handles heartbeat, reconnect on 30s timeout, max 5min connection
5. Returns abort controller for cancellation

- [ ] **Step 1:** Write SSE handler
- [ ] **Step 2:** Verify + commit: `feat(streaming): add SSE event handler with 9 event types`

### Task 4: Thread Hooks

**Files:**
- Create: `src/hooks/use-threads.ts`
- Create: `src/hooks/use-thread-messages.ts`

Thread CRUD hooks + cursor-based message pagination + stream mutation.

- [ ] **Step 1:** Write hooks
- [ ] **Step 2:** Verify + commit: `feat(hooks): add thread and message hooks with SSE streaming`

### Task 5: Install Dependencies + Chat Page Layout

**Files:**
- Create: `src/app/(dashboard)/chat/page.tsx`
- Create: `src/components/chat/ThreadSidebar.tsx`
- Create: `src/components/chat/ThreadListItem.tsx`
- Create: `src/components/chat/ThreadHeader.tsx`
- Create: `src/components/chat/QueryInputBar.tsx`
- Modify: `src/components/layout/Sidebar.tsx`

Install recharts, react-markdown. Build the main layout: sidebar (threads) + chat area + input bar. Wire thread CRUD.

- [ ] **Step 1:** Install deps: `npm install recharts react-markdown remark-gfm rehype-highlight`
- [ ] **Step 2:** Build ThreadSidebar, ThreadListItem, ThreadHeader, QueryInputBar
- [ ] **Step 3:** Build chat page layout
- [ ] **Step 4:** Update sidebar: replace "AI Query" → "Chat" link
- [ ] **Step 5:** Verify + commit: `feat(chat): add conversational chat page with thread sidebar`

### Task 6: Streaming Message Display

**Files:**
- Create: `src/components/chat/ChatMessageList.tsx`
- Create: `src/components/chat/ChatMessage.tsx`
- Create: `src/components/chat/StreamingIndicator.tsx`

Message list with lazy-load scroll-up, message bubbles, streaming progress indicator with typewriter effect.

- [ ] **Step 1:** Build components
- [ ] **Step 2:** Wire SSE handler into chat page
- [ ] **Step 3:** Verify + commit: `feat(chat): add streaming message display with progress indicator`

---

## Step 2: BA-018 — Rich Response Rendering (Parallel with Step 3)

### Task 7: Response Block Renderers

**Files:**
- Create: `src/components/response/ResponseRenderer.tsx`
- Create: `src/components/response/MarkdownBlock.tsx`
- Create: `src/components/response/CodeBlock.tsx`
- Create: `src/components/response/ChartBlock.tsx`
- Create: `src/components/response/TableBlock.tsx`
- Create: `src/components/response/AggregationRationale.tsx`

ResponseRenderer dispatches block type → specific renderer. Charts use Recharts with hover/legend/responsive. Code uses syntax highlighting with copy button. Tables are paginated + sortable.

- [ ] **Step 1:** Build MarkdownBlock (react-markdown + remark-gfm)
- [ ] **Step 2:** Build CodeBlock (syntax highlight + copy)
- [ ] **Step 3:** Build ChartBlock (Recharts bar/line/pie/scatter)
- [ ] **Step 4:** Build TableBlock (paginated + sortable)
- [ ] **Step 5:** Build ResponseRenderer (dispatcher)
- [ ] **Step 6:** Integrate into ChatMessage component
- [ ] **Step 7:** Verify + commit: `feat(response): add rich response renderers (charts, markdown, code, tables)`

---

## Step 3: BA-019 — Tools, Actions & Insights (Parallel with Step 2)

### Task 8: Favorites Hooks + Types

**Files:**
- Create: `src/hooks/use-favorites.ts`
- Create: `src/hooks/use-insights.ts`

Favorite CRUD hooks + insight/compare hooks.

- [ ] **Step 1:** Write hooks
- [ ] **Step 2:** Verify + commit: `feat(hooks): add favorites and insights hooks for BA-019`

### Task 9: Tool Menu + Keyboard Shortcuts

**Files:**
- Create: `src/components/chat/ToolMenu.tsx`

9-tool horizontal toolbar with icons, labels, keyboard shortcuts, disabled state logic.

- [ ] **Step 1:** Build ToolMenu with all 9 tools
- [ ] **Step 2:** Wire keyboard shortcuts (useEffect + keydown listener)
- [ ] **Step 3:** Verify + commit: `feat(chat): add 9-tool menu with keyboard shortcuts`

### Task 10: Insight Cards + Suggested Actions

**Files:**
- Create: `src/components/chat/InsightCards.tsx`
- Create: `src/components/chat/SuggestedActions.tsx`

Insight cards with confidence badges (high/medium/low), sorted by confidence. 3 suggested action buttons + custom input.

- [ ] **Step 1:** Build InsightCards
- [ ] **Step 2:** Build SuggestedActions
- [ ] **Step 3:** Integrate into ChatMessage (below tool menu)
- [ ] **Step 4:** Verify + commit: `feat(chat): add AI insight cards and suggested actions`

### Task 11: Favorites Page + Sidebar Section

**Files:**
- Create: `src/app/(dashboard)/favorites/page.tsx`
- Modify: `src/components/chat/ThreadSidebar.tsx` (add favorites section)

Favorites list page with search/sort/filter. Sidebar favorites section below threads.

- [ ] **Step 1:** Build favorites page
- [ ] **Step 2:** Add favorites section to ThreadSidebar
- [ ] **Step 3:** Verify + commit: `feat(favorites): add favorites page and sidebar section`

### Task 12: Compare View

**Files:**
- Create: `src/components/chat/CompareView.tsx`

Side-by-side comparison display: added rows (green), removed rows (red), changed cells (yellow), AI narrative.

- [ ] **Step 1:** Build CompareView
- [ ] **Step 2:** Wire into tool menu "Compare" action
- [ ] **Step 3:** Verify + commit: `feat(chat): add compare view for result differences`

### Task 13: Final Build Verification

- [ ] **Step 1:** `npx tsc --noEmit` — 0 errors
- [ ] **Step 2:** `npm run build` — all routes in output
- [ ] **Step 3:** Update CLAUDE.md with Phase 4 routes
- [ ] **Step 4:** Commit: `docs: update CLAUDE.md with Phase 4 chat routes and streaming architecture`

---

## Task Count Summary

| Step | BA | Tasks | New Files | Modified Files |
|------|-----|-------|-----------|----------------|
| Step 1 | BA-017 Threads + Streaming | 6 | 14 | 1 |
| Step 2 | BA-018 Rich Responses | 1 (multi-file) | 6 | 1 |
| Step 3 | BA-019 Tools + Insights | 5 | 7 | 1 |
| Final | — | 1 | 0 | 1 |
| **Total** | | **13** | **27** | **4** |
