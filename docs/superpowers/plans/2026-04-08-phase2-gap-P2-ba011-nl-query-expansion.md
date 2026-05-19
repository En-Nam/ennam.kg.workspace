# P2: BA-011 AI Query Pipeline Expansion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Priority: P2 (HIGH)** — Core user-facing feature. Needs BA-008 KG data for context. Blocks BA-013 benchmark expansion.

**Goal:** Expand the basic AI query endpoints (submit + get) into a full NL→SQL pipeline with intent parsing, SQL generation, source DB execution, query history, and favorites.

**Architecture:** Multi-stage pipeline: NL input → AI intent parsing (via BA-009 Selector) → SQL generation (using KG metadata from BA-008 as context) → source DB execution (via BA-007 encrypted connections) → response formatting. Extends existing `ai_query.go` handler/store rather than replacing them.

**Tech Stack:** Go std lib, `internal/ai/` Selector, `internal/store/schema_metadata.go`, `internal/crypto/`, PostgreSQL

**BA Reference:** `ennam.kg.requirements/documents/phase2/BA-011-ai-natural-language-query.md`

**Prerequisites:** BA-008 (KG nodes/edges provide query context)

---

## What Already Exists

- `internal/models/ai_query.go` — AIQuery model ✅
- `internal/store/ai_query.go` — Create, GetByID, UpdateCompleted, UpdateFailed ✅
- `internal/handler/ai_query.go` — POST /ai-queries, GET /ai-queries/{id} ✅
- Migration 023 — ai_queries table ✅

## What's Missing

- **Service layer**: No NL→SQL pipeline (intent parser, SQL generator, source executor)
- **Store methods**: No List, History, Favorites, Search
- **Handler endpoints**: No history, favorites, clarification
- **Migration**: No query_clarifications, query_favorites tables

---

## File Structure

### New Files

```
db/migrations/
├── 000027_create_query_extras.up.sql       # query_clarifications + query_favorites
├── 000027_create_query_extras.down.sql

internal/service/
├── nl_query.go                             # Pipeline orchestrator
├── nl_query_test.go
├── query_intent.go                         # AI intent parsing: NL → query plan JSON
├── query_intent_test.go
├── sql_generator.go                        # Query plan → parameterized SQL
├── sql_generator_test.go
├── source_executor.go                      # Execute SQL on source DB (read-only)
├── source_executor_test.go
```

### Modified Files

```
internal/models/ai_query.go                # Add QueryClarification, QueryFavorite models
internal/store/ai_query.go                 # Add List, ListHistory, Favorites CRUD, UpdateRunning
internal/handler/ai_query.go               # Add 4 endpoints (history, star, clarification)
cmd/kg-server/main.go                      # Wire NL query service into handler
```

---

## Task 1: Migration 027 — query extras tables

**Files:**
- Create: `db/migrations/000027_create_query_extras.up.sql`
- Create: `db/migrations/000027_create_query_extras.down.sql`

- [ ] **Step 1: Write migration**

```sql
-- 000027_create_query_extras.up.sql
CREATE TABLE query_clarifications (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query_id        UUID NOT NULL REFERENCES ai_queries(id),
    clarifying_question TEXT NOT NULL,
    options         JSONB NOT NULL DEFAULT '[]',
    selected_option TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_query_clarifications_query ON query_clarifications(query_id);

CREATE TABLE query_favorites (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query_id        UUID NOT NULL REFERENCES ai_queries(id),
    user_id         VARCHAR(255) NOT NULL,
    label           VARCHAR(255),
    is_shared       BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT query_favorites_unique UNIQUE (query_id, user_id)
);

CREATE INDEX idx_query_favorites_user ON query_favorites(user_id);

-- Add created_by column to ai_queries if missing (team's migration may not have it)
-- Also add index for history queries
CREATE INDEX IF NOT EXISTS idx_ai_queries_project_ds ON ai_queries(project_id, data_source_id, created_at DESC);
```

```sql
-- 000027_create_query_extras.down.sql
DROP INDEX IF EXISTS idx_ai_queries_project_ds;
DROP TABLE IF EXISTS query_favorites;
DROP TABLE IF EXISTS query_clarifications;
```

- [ ] **Step 2: Commit**

```bash
git add db/migrations/000027_*
git commit -m "feat(db): add query_clarifications and query_favorites tables (BA-011)"
```

---

## Task 2: Extend Models

**Files:**
- Modify: `internal/models/ai_query.go`

- [ ] **Step 1: Add QueryClarification and QueryFavorite models**

```go
// Add to internal/models/ai_query.go

// QueryClarification represents an ambiguity resolution step.
type QueryClarification struct {
	ID                 string    `json:"id" db:"id"`
	QueryID            string    `json:"query_id" db:"query_id"`
	ClarifyingQuestion string    `json:"clarifying_question" db:"clarifying_question"`
	Options            json.RawMessage `json:"options" db:"options"`
	SelectedOption     *string   `json:"selected_option,omitempty" db:"selected_option"`
	CreatedAt          time.Time `json:"created_at" db:"created_at"`
}

// QueryFavorite represents a starred query.
type QueryFavorite struct {
	ID        string    `json:"id" db:"id"`
	QueryID   string    `json:"query_id" db:"query_id"`
	UserID    string    `json:"user_id" db:"user_id"`
	Label     *string   `json:"label,omitempty" db:"label"`
	IsShared  bool      `json:"is_shared" db:"is_shared"`
	CreatedAt time.Time `json:"created_at" db:"created_at"`
}

// QueryPlan represents the structured plan produced by AI intent parsing.
type QueryPlan struct {
	Tables       []string       `json:"tables"`
	Joins        []QueryJoin    `json:"joins"`
	Filters      []QueryFilter  `json:"filters"`
	Aggregations []string       `json:"aggregations,omitempty"`
	GroupBy      []string       `json:"group_by,omitempty"`
	OrderBy      []string       `json:"order_by,omitempty"`
	Limit        int            `json:"limit,omitempty"`
}

type QueryJoin struct {
	Table      string `json:"table"`
	On         string `json:"on"`
	Type       string `json:"type"` // INNER, LEFT, etc.
}

type QueryFilter struct {
	Column   string      `json:"column"`
	Operator string      `json:"operator"`
	Value    interface{} `json:"value"`
}
```

- [ ] **Step 2: Commit**

```bash
git add internal/models/ai_query.go
git commit -m "feat(models): add QueryClarification, QueryFavorite, QueryPlan (BA-011)"
```

---

## Task 3: Extend AI Query Store

**Files:**
- Modify: `internal/store/ai_query.go`

- [ ] **Step 1: Add new store methods**

```go
// New methods to add:
func (s *AIQueryStore) UpdateRunning(ctx, id, generatedSQL string) error
func (s *AIQueryStore) ListByDataSource(ctx, projectID, dataSourceID string, limit int) ([]*models.AIQuery, error)
func (s *AIQueryStore) ListHistory(ctx, projectID string, limit int) ([]*models.AIQuery, error)
func (s *AIQueryStore) CreateFavorite(ctx, queryID, userID string, label *string) (*models.QueryFavorite, error)
func (s *AIQueryStore) DeleteFavorite(ctx, queryID, userID string) error
func (s *AIQueryStore) ListFavorites(ctx, userID string) ([]*models.QueryFavorite, error)
func (s *AIQueryStore) CreateClarification(ctx, *models.QueryClarification) error
func (s *AIQueryStore) ResolveClarification(ctx, id, selectedOption string) error
```

- ListHistory: `SELECT FROM ai_queries WHERE project_id = $1 ORDER BY created_at DESC LIMIT $2`
- ListByDataSource: same + filter on data_source_id
- Default limit: 20, max 100

- [ ] **Step 2: Write tests, commit**

```bash
git add internal/store/ai_query.go internal/store/ai_query_test.go
git commit -m "feat(store): extend AIQueryStore with history, favorites, clarification (BA-011)"
```

---

## Task 4: Query Intent Parser (AI)

**Files:**
- Create: `internal/service/query_intent.go`
- Create: `internal/service/query_intent_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- Parses NL into QueryPlan with correct tables, joins, filters
- Builds KG metadata context from schema tree (tables, columns, FKs)
- Trims context to fit token budget (max ~4000 tokens)
- Validates plan against KG metadata (rejects unknown tables/columns)
- Detects ambiguity (multi-table name matches) → returns clarification

- [ ] **Step 2: Implement QueryIntentParser**

```go
type QueryIntentParser struct {
    metaStore  *store.SchemaMetadataStore
    kgStore    *store.KGGenerationStore
    aiSelector *ai.Selector
    logger     *slog.Logger
}

// Parse sends NL query + KG context to AI, returns structured QueryPlan.
func (p *QueryIntentParser) Parse(ctx context.Context, dataSourceID, nlQuery string) (*models.QueryPlan, *models.QueryClarification, error)
```

AI prompt structure:
```
System: You are a SQL query planner. Given a database schema and a natural language question, produce a JSON query plan.

User:
Schema context: {tables, columns, FK relationships from KG}
Question: {nlQuery}

Respond with JSON: {"tables":[], "joins":[], "filters":[], "aggregations":[], "group_by":[], "order_by":[], "limit": N}
```

- [ ] **Step 3: Run tests, commit**

```bash
git add internal/service/query_intent.go internal/service/query_intent_test.go
git commit -m "feat(service): add QueryIntentParser with AI-powered NL→plan conversion (BA-011)"
```

---

## Task 5: SQL Generator

**Files:**
- Create: `internal/service/sql_generator.go`
- Create: `internal/service/sql_generator_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- Simple SELECT: `{tables:["orders"], filters:[{column:"status",operator:"=",value:"shipped"}]}` → `SELECT * FROM orders WHERE status = $1`
- JOIN from KG edges: uses FK relationships, not guessed
- Aggregation: COUNT, SUM, AVG with GROUP BY
- Default LIMIT 1000, max 10000
- All values parameterized ($1, $2, ...)
- Rejects unknown tables/columns

- [ ] **Step 2: Implement SQLGenerator**

```go
type SQLGenerator struct {
    kgStore *store.KGGenerationStore
    logger  *slog.Logger
}

// Generate transforms a QueryPlan into parameterized SQL.
func (g *SQLGenerator) Generate(ctx context.Context, dataSourceID string, plan *models.QueryPlan) (string, []interface{}, error)
```

- [ ] **Step 3: Run tests, commit**

```bash
git add internal/service/sql_generator.go internal/service/sql_generator_test.go
git commit -m "feat(service): add SQLGenerator transforming query plans to parameterized SQL (BA-011)"
```

---

## Task 6: Source DB Executor

**Files:**
- Create: `internal/service/source_executor.go`
- Create: `internal/service/source_executor_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- Executes parameterized SQL against source DB
- 30-second query timeout
- Max 10,000 rows, truncation warning
- Read-only enforcement (connection string uses read-only user)
- Returns rows as JSON array

- [ ] **Step 2: Implement SourceExecutor**

```go
type SourceExecutor struct {
    dsStore *store.DataSourceStore
    encKey  []byte
    logger  *slog.Logger
}

type QueryResult struct {
    Columns  []string                 `json:"columns"`
    Rows     []map[string]interface{} `json:"rows"`
    RowCount int                      `json:"row_count"`
    Truncated bool                    `json:"truncated"`
}

// Execute runs parameterized SQL against the source database.
func (e *SourceExecutor) Execute(ctx context.Context, dataSourceID, sql string, params []interface{}) (*QueryResult, error)
```

Key: decrypt connection string → sql.Open → set 30s timeout → execute → scan rows → close

- [ ] **Step 3: Run tests, commit**

```bash
git add internal/service/source_executor.go internal/service/source_executor_test.go
git commit -m "feat(service): add SourceExecutor for read-only source DB queries (BA-011)"
```

---

## Task 7: NL Query Pipeline Orchestrator

**Files:**
- Create: `internal/service/nl_query.go`
- Create: `internal/service/nl_query_test.go`

- [ ] **Step 1: Implement NLQueryService**

```go
type NLQueryService struct {
    queryStore   *store.AIQueryStore
    intentParser *QueryIntentParser
    sqlGenerator *SQLGenerator
    executor     *SourceExecutor
    logger       *slog.Logger
}

// ProcessQuery runs the full NL→SQL→Execute pipeline.
func (s *NLQueryService) ProcessQuery(ctx context.Context, queryID string) error {
    // 1. Get query from store
    // 2. Update status to "running"
    // 3. Parse intent → QueryPlan (or clarification needed)
    // 4. Generate SQL from plan
    // 5. Execute SQL on source DB
    // 6. Update query with results (completed) or error (failed)
    // Auto-retry on SQL error: max 2 attempts
}
```

- [ ] **Step 2: Write tests covering full pipeline with mocks**

- [ ] **Step 3: Commit**

```bash
git add internal/service/nl_query.go internal/service/nl_query_test.go
git commit -m "feat(service): add NLQueryService orchestrating full NL→SQL→Execute pipeline (BA-011)"
```

---

## Task 8: Expand Handler with New Endpoints

**Files:**
- Modify: `internal/handler/ai_query.go`

- [ ] **Step 1: Add 4 new endpoints to existing handler**

```go
// Add to RegisterRoutes:
mux.HandleFunc("GET /api/v1/ai-queries", h.ListHistory)           // query history
mux.HandleFunc("POST /api/v1/ai-queries/{id}/star", h.StarQuery)  // add to favorites
mux.HandleFunc("DELETE /api/v1/ai-queries/{id}/star", h.UnstarQuery)
mux.HandleFunc("GET /api/v1/ai-queries/favorites", h.ListFavorites)
```

Also modify `SubmitQuery` to trigger the NL pipeline (either sync or async via goroutine).

- [ ] **Step 2: Wire NLQueryService into handler constructor**

```go
// Modify handler struct to include service:
type AIQueryHandler struct {
    queryStore *store.AIQueryStore
    nlService  *service.NLQueryService  // NEW
    logger     *slog.Logger
}
```

- [ ] **Step 3: Update composition root wiring**

- [ ] **Step 4: Commit**

```bash
git add internal/handler/ai_query.go cmd/kg-server/main.go
git commit -m "feat(handler): expand AIQueryHandler with history, favorites, and NL pipeline (BA-011)"
```

---

## Task Summary

| # | Task | Type | Effort |
|---|------|------|--------|
| 1 | Migration 027 | New tables | Small |
| 2 | Extend models | Modify | Small |
| 3 | Extend store | Modify | Medium |
| 4 | Query Intent Parser | New service — AI integration | Large |
| 5 | SQL Generator | New service — plan→SQL | Large |
| 6 | Source Executor | New service — DB execution | Medium |
| 7 | Pipeline Orchestrator | New service — glue | Medium |
| 8 | Expand handler + wire | Modify handler + main | Medium |
| **Total** | **8 tasks** | **~14 files** | |
