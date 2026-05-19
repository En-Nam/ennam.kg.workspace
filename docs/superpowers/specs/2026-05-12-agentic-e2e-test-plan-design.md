# Agentic AI Chat Engine — E2E Test Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Validate the Agentic AI Chat Engine end-to-end across API, browser UI, and response accuracy.

**Approach:** 3-layer testing — API smoke tests (httpx/curl), browser E2E (Chrome DevTools MCP), accuracy evaluation (rubric-scored AI responses).

**Tech Stack:** Python (pytest + httpx), Chrome DevTools MCP, Docker Compose, MSSQL (C4K Staging)

---

## 1. Prerequisites

### 1.1 Docker Environment

Rebuild all services with latest code:

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

Wait for healthy state:
- `kg-server` (Go API) — `:8080/healthz` returns 200
- `worker` (Python) — `:8081/healthz` returns 200
- `dashboard` (NextJS) — `:3500` returns 200
- `postgres` — accepts connections on `:5432`
- `redis` — responds to PING on `:6379`

### 1.2 Database Migration

Verify migration 000044 (agentic AI support) is applied:

```sql
SELECT EXISTS (
  SELECT FROM information_schema.tables
  WHERE table_name = 'agent_tool_calls'
);
-- Must return true
```

If not applied, run:
```bash
docker compose exec kg-server ./migrate up
```

### 1.3 Test Data

| Item | Detail |
|------|--------|
| **User account** | `admin` / `Admin123!@#` |
| **Data source** | MSSQL "C4K Staging" — already loaded in system |
| **AI provider** | Anthropic API key stored in DB, encrypted with AES-GCM |
| **Project** | Default project (created during initial setup) |

### 1.4 Verify Baseline

Before running tests, confirm:
1. Login as admin via dashboard — should reach `/graph` page
2. Navigate to `/chat` — should render QueryInputBar
3. Send a simple non-agentic message — should get SSE response
4. Navigate to `/data-sources` — "C4K Staging" should appear with status "connected"

---

## 2. Layer 1 — API Smoke Tests

Direct HTTP requests to the Go API (`:8080`) and Python worker (`:8081`). No browser needed. Validates SSE event contracts, tier routing, and error handling.

### API-01: Quick Tier SSE Event Sequence

**Endpoint:** `POST /api/v1/agentic/stream` (via Go BFF proxy)

**Request:**
```json
{
  "thread_id": "<test-thread>",
  "query": "What tables exist in C4K Staging?",
  "tier": "quick",
  "data_source_id": "<c4k-staging-id>"
}
```

**Expected SSE events (in order):**
1. `agent_start` — contains `tier: "quick"`, `max_iterations: 3`
2. One or more `tool_call_start` / `tool_call_end` pairs
3. `content` — final answer text
4. `agent_done` — contains `iterations_used`, `tools_used`, `total_tokens`
5. `done` — terminal event

**Pass criteria:**
- All 5 event types received in correct order
- `iterations_used ≤ 3`
- `total_tokens ≤ 30000`
- Response completes within 5 minutes

### API-02: Deep Tier Extended Exploration

**Request:** Same as API-01 but with `"tier": "deep"` and a more complex query:
```json
{
  "query": "Analyze the relationships between Customer, Order, and Product tables in C4K Staging. What are the foreign keys and how do they connect?",
  "tier": "deep"
}
```

**Expected:**
- `agent_start` with `max_iterations: 12`
- More tool calls than Quick (typically 4-8)
- Uses `get_table_schema` and `get_neighbors` tools
- `iterations_used > 3` (exercises Deep tier capacity)
- Response completes within 10 minutes

**Pass criteria:**
- Deep tier uses more iterations than Quick for equivalent complexity
- All SSE events well-formed

### API-03: SQL Security — DDL Rejection

**Request:**
```json
{
  "query": "Drop the Users table",
  "tier": "quick"
}
```

**Expected:**
- Agent should NOT execute any DROP statement
- If the LLM generates DDL, the SQL validator blocks it
- Response should explain it cannot perform destructive operations
- No `tool_call_end` with SQL containing DROP/ALTER/INSERT/UPDATE/DELETE

**Pass criteria:**
- No DDL/DML SQL executed
- Graceful error or refusal in content

### API-04: SQL Security — SELECT Enforcement

**Request:**
```json
{
  "query": "Show me the first 5 customers from C4K Staging",
  "tier": "quick"
}
```

**Expected:**
- `tool_call_start` with tool `execute_sql`
- `tool_call_end` showing the SQL used — must be SELECT or WITH
- SQL length ≤ 5000 characters
- Results contain customer data

**Pass criteria:**
- Only SELECT/WITH statements executed
- Results returned successfully

### API-05: Clarification Pause/Resume

**Request:** A deliberately ambiguous query:
```json
{
  "query": "Show me the data",
  "tier": "deep"
}
```

**Expected:**
- Agent emits `clarification_request` event with a question
- Stream pauses (no more events until resume)
- Resume via `POST /api/v1/ai/clarification`:
  ```json
  {
    "session_id": "<from clarification_request>",
    "thread_id": "<test-thread>",
    "response": "Show me the top 10 customers by order count from C4K Staging"
  }
  ```
- Agent resumes with new SSE stream containing the answer

**Pass criteria:**
- Clarification event received with valid `session_id`
- Resume produces new stream with relevant answer
- Total flow completes within 10 minutes

**Note:** This test may not trigger clarification every time (LLM-dependent). If the agent proceeds without clarification, mark as SKIP with note "LLM did not request clarification" — this is acceptable behavior.

### API-06: Error Handling — Invalid Data Source

**Request:**
```json
{
  "query": "Show me all tables",
  "tier": "quick",
  "data_source_id": "nonexistent-uuid"
}
```

**Expected:**
- Error response (HTTP 4xx or SSE error event)
- No crash or hanging connection
- Error message indicates data source not found

**Pass criteria:**
- Clean error, no server crash
- Connection properly closed

---

## 3. Layer 2 — Browser E2E Tests (Chrome DevTools MCP)

Uses Chrome DevTools MCP to drive the NextJS dashboard at `:3500`. Tests UI components, SSE streaming visualization, and user interactions.

### UI-01: Login & Navigation to Chat

**Steps:**
1. Navigate to `http://localhost:3500`
2. Login with `admin` / `Admin123!@#`
3. Navigate to `/chat`
4. Take screenshot

**Pass criteria:**
- Chat page renders with QueryInputBar visible
- TierSelector component visible (Quick/Deep toggle)
- No console errors

### UI-02: TierSelector Toggle + Persistence

**Steps:**
1. On `/chat`, click "Deep" in TierSelector
2. Take screenshot — Deep should be visually selected
3. Reload the page
4. Take screenshot — Deep should still be selected (localStorage)
5. Click "Quick" — should switch back

**Pass criteria:**
- Visual toggle works
- Selection persists across page reload
- localStorage key `agentic-tier` contains correct value

### UI-03: Quick Tier — Streaming Response

**Steps:**
1. Ensure TierSelector is set to "Quick"
2. Type "What tables are in C4K Staging?" in QueryInputBar
3. Submit the query
4. Observe streaming response — take screenshot during streaming
5. Wait for completion — take final screenshot

**Pass criteria:**
- AgenticProgress component appears during streaming
- PhaseIndicator shows current phase
- ToolCallStepRow entries appear for each tool call
- Final answer renders in ChatMessage
- AgenticProgress collapses after completion

### UI-04: Deep Tier — Extended Streaming

**Steps:**
1. Set TierSelector to "Deep"
2. Submit: "Analyze the Customer table schema and show me the top 5 customers by order count"
3. Observe streaming — take screenshots at intervals
4. Wait for completion

**Pass criteria:**
- More tool call steps visible than Quick tier
- AgenticProgress shows multiple iterations
- KgNodeChip badges appear if KG nodes are referenced
- MultiSourceResults tabs appear if multiple sources queried
- Response completes within 10 minutes

### UI-05: KgNodeChip Display

**Steps:**
1. Submit a query that references KG nodes: "What architecture nodes exist in the knowledge graph?"
2. Wait for response
3. Inspect the rendered message

**Pass criteria:**
- KgNodeChip components render as colored pill badges
- Each chip shows node label
- Chips are visually distinct by node type (different colors)

### UI-06: Error Resilience — Network Interruption

**Steps:**
1. Start a Deep tier query
2. During streaming (after first tool_call_start), simulate network interruption:
   - Use Chrome DevTools to go offline briefly, then reconnect
3. Observe UI behavior

**Pass criteria:**
- UI shows error state (not blank screen or infinite spinner)
- User can submit a new query after error
- No unhandled exceptions in console

### UI-07: Chat History Persistence

**Steps:**
1. Submit a Quick tier query and wait for completion
2. Note the thread URL (should be `/chat/<threadId>`)
3. Navigate away to `/graph`
4. Navigate back to the thread URL
5. Take screenshot

**Pass criteria:**
- Previous messages render correctly
- Agentic metadata (tool calls, iterations) visible in historical messages
- QueryInputBar ready for new input

### UI-08: Network Request Inspection

**Steps:**
1. Start monitoring network requests via Chrome DevTools
2. Submit a Quick tier query
3. Inspect the SSE request

**Pass criteria:**
- Request goes to `/api/kg/ai/agentic/stream` (BFF proxy path)
- Request includes `tier` field in body
- Response content-type is `text/event-stream`
- SSE events match expected format (data: JSON lines)
- No failed requests (all 2xx except the streaming SSE)

---

## 4. Layer 3 — Accuracy Evaluation

12 test cases across 4 categories, scored on a 0–3 rubric. Uses Quick tier for simple queries, Deep tier for complex analysis.

### Scoring Rubric

| Score | Label | Criteria |
|-------|-------|----------|
| 0 | Wrong | Factually incorrect, hallucinates data, or fails to execute |
| 1 | Partial | Partially correct but missing key information or contains errors |
| 2 | Correct | Accurate answer that addresses the question |
| 3 | Excellent | Accurate, well-structured, cites sources, provides context |

### Category A: KG Search (3 cases)

**ACC-01: Basic Node Search**
- Query: "What architecture nodes exist in the knowledge graph?" (Quick)
- Expected: Lists schema_table nodes from C4K Staging
- Score 2+ if: returns real node names from KG
- Score 3 if: also shows node types, relationships, or metadata

**ACC-02: Neighbor Traversal**
- Query: "What nodes are connected to the Customer table?" (Quick)
- Expected: Shows edges to related tables (Orders, Products, etc.)
- Score 2+ if: lists actual neighbors with relationship types
- Score 3 if: explains the relationships and their meaning

**ACC-03: Cross-Reference Search**
- Query: "Find all tables related to order processing in C4K Staging" (Deep)
- Expected: Identifies Orders, OrderItems, Products, Customers, and their connections
- Score 2+ if: finds relevant tables with evidence from KG
- Score 3 if: maps the full order processing data flow

### Category B: SQL Generation (3 cases)

**ACC-04: Simple SELECT**
- Query: "Show me the first 10 customers from C4K Staging" (Quick)
- Expected: Valid SELECT with TOP 10 (MSSQL syntax)
- Score 2+ if: returns actual customer data
- Score 3 if: uses correct MSSQL dialect (TOP not LIMIT), clean formatting

**ACC-05: Aggregation Query**
- Query: "How many orders does each customer have? Show top 5 by order count" (Quick)
- Expected: JOIN + GROUP BY + ORDER BY + TOP 5
- Score 2+ if: correct SQL, correct results
- Score 3 if: includes customer name, well-formatted output

**ACC-06: Multi-Table JOIN**
- Query: "What are the most popular products by total quantity ordered?" (Deep)
- Expected: JOIN Products → OrderItems, aggregate quantities
- Score 2+ if: correct JOIN, meaningful results
- Score 3 if: handles NULL cases, shows product names, proper ordering

### Category C: Multi-Step Reasoning (3 cases)

**ACC-07: Schema-Then-Query**
- Query: "What columns does the Customer table have, and show me 3 example rows" (Quick)
- Expected: First calls `get_table_schema`, then `execute_sql`
- Score 2+ if: both schema and data returned
- Score 3 if: schema shown first, then example rows, with column descriptions

**ACC-08: KG-Guided Analysis**
- Query: "Using the knowledge graph, find all tables in C4K Staging and tell me which ones have the most columns" (Deep)
- Expected: Searches KG for schema_table nodes, then gets schema for each
- Score 2+ if: lists tables with column counts
- Score 3 if: sorted by column count, uses KG evidence, comprehensive coverage

**ACC-09: Data Discovery Pipeline**
- Query: "I'm new to this database. Give me an overview of what data is available and suggest 3 interesting analyses I could do" (Deep)
- Expected: Uses list_datasources → search_kg → get_table_schema → synthesize
- Score 2+ if: meaningful overview with real table names
- Score 3 if: coherent narrative, practical suggestions tied to actual data

### Category D: Edge Cases (3 cases)

**ACC-10: Empty Result Handling**
- Query: "Show me all customers named 'ZZZZNONEXISTENT'" (Quick)
- Expected: Reports no results found (not an error)
- Score 2+ if: clearly states no results
- Score 3 if: suggests alternative approaches (e.g., "try a different search term")

**ACC-11: Ambiguous Query**
- Query: "Show me the data" (Quick)
- Expected: Asks for clarification OR makes a reasonable assumption and explains it
- Score 2+ if: either clarifies or makes explicit assumption
- Score 3 if: offers multiple interpretations

**ACC-12: Complex Analysis**
- Query: "Analyze the C4K Staging database schema and identify potential data quality issues or missing foreign key relationships" (Deep)
- Expected: Deep exploration of schema, cross-referencing relationships
- Score 2+ if: identifies real structural observations
- Score 3 if: actionable insights, references actual column names and types

### Scoring Aggregation

| Metric | Threshold |
|--------|-----------|
| **Minimum average** | ≥ 1.5 (all 12 cases) |
| **Target average** | ≥ 2.0 |
| **Critical failures** | No score-0 cases in Categories A or B |
| **Category minimums** | Each category average ≥ 1.0 |

### Results Template

```markdown
| Case | Category | Tier | Score | Notes |
|------|----------|------|-------|-------|
| ACC-01 | KG Search | Quick | ?/3 | |
| ACC-02 | KG Search | Quick | ?/3 | |
| ACC-03 | KG Search | Deep | ?/3 | |
| ACC-04 | SQL Gen | Quick | ?/3 | |
| ACC-05 | SQL Gen | Quick | ?/3 | |
| ACC-06 | SQL Gen | Deep | ?/3 | |
| ACC-07 | Multi-step | Quick | ?/3 | |
| ACC-08 | Multi-step | Deep | ?/3 | |
| ACC-09 | Multi-step | Deep | ?/3 | |
| ACC-10 | Edge Case | Quick | ?/3 | |
| ACC-11 | Edge Case | Quick | ?/3 | |
| ACC-12 | Edge Case | Deep | ?/3 | |
| **Average** | | | **?/3** | |
```

---

## 5. Execution Order

1. **Prerequisites** (Section 1) — rebuild Docker, verify migration, confirm baseline
2. **API Smoke Tests** (Section 2) — run API-01 through API-06
3. **Browser E2E** (Section 3) — run UI-01 through UI-08
4. **Accuracy Evaluation** (Section 4) — run ACC-01 through ACC-12, score each

Tests in Layers 1 and 2 must pass before proceeding to Layer 3. Accuracy evaluation requires a working API and UI.

## 6. Test Environment Cleanup

After all tests complete:
- Delete test threads created during testing
- Capture final screenshots and save to `docs/superpowers/test-results/`
- Generate accuracy report from results template
- No need to tear down Docker — leave running for further development
