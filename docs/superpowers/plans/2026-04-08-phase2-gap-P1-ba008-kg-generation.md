# P1: BA-008 KG Generation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Priority: P1 (CRITICAL PATH)** — Blocks BA-011 expansion (NL queries need KG context) and BA-013 expansion (benchmarks need KG data). Do this first.

**Goal:** Transform extracted schema metadata (from BA-007) into Knowledge Graph nodes and edges — explicit FK mapping with cardinality, AI-powered implicit relationship detection with confidence scoring, and admin override capabilities.

**Architecture:** New service layer that reads from `source_*` tables (BA-007), creates `knowledge_nodes` (type=architecture, subtype=schema_table) and `knowledge_edges` (types: schema_fk, schema_implicit, schema_many_to_many). Uses BA-009 AI selector for implicit detection. All operations are idempotent (re-run updates, doesn't duplicate).

**Tech Stack:** Go std lib, `internal/ai/` Selector (BA-009), `internal/store/schema_metadata.go` (BA-007), PostgreSQL JSONB properties

**BA Reference:** `ennam.kg.requirements/documents/phase2/BA-008-knowledge-graph-generation.md`

**Prerequisites:** BA-007 (schema metadata) + BA-009 (AI provider) — both complete on `main`.

---

## What Already Exists (from team's work)

- `config.yaml` already has `schema_fk`, `schema_implicit`, `schema_many_to_many` edge types ✅
- Migrations 023-024 are TAKEN (ai_queries, benchmarks) → new migrations start at **025**

## File Structure

### New Files

```
db/migrations/
├── 000025_extend_kg_properties.up.sql      # Add JSONB property fields for schema nodes/edges
├── 000025_extend_kg_properties.down.sql
├── 000026_create_kg_generation_jobs.up.sql  # KG generation job tracking table
├── 000026_create_kg_generation_jobs.down.sql

internal/models/
├── kg_generation.go                        # KGGenerationJob model

internal/store/
├── kg_generation.go                        # KGGenerationStore: job tracking + KG node/edge queries by data source
├── kg_generation_test.go

internal/service/
├── kg_generator.go                         # Orchestrator: nodes → explicit → implicit → persist
├── kg_generator_test.go
├── kg_explicit.go                          # FK → directed edge mapping (1:1, 1:N, M:N)
├── kg_explicit_test.go
├── kg_implicit.go                          # AI-powered implicit relationship detection
├── kg_implicit_test.go

internal/handler/
├── kg_generation.go                        # 9 REST endpoints
├── kg_generation_test.go
```

### Modified Files

```
cmd/kg-server/main.go                      # Wire KGGeneration handler
```

---

## Task 1: Migrations 025-026

**Files:**
- Create: `db/migrations/000025_extend_kg_properties.up.sql`
- Create: `db/migrations/000025_extend_kg_properties.down.sql`
- Create: `db/migrations/000026_create_kg_generation_jobs.up.sql`
- Create: `db/migrations/000026_create_kg_generation_jobs.down.sql`

- [ ] **Step 1: Write migration 025 — extend properties + relax self-ref**

```sql
-- 000025_extend_kg_properties.up.sql

-- Relax self-reference CHECK on knowledge_edges for schema_fk edges
-- (self-referential FKs like employee.manager_id → employee.id)
ALTER TABLE knowledge_edges DROP CONSTRAINT IF EXISTS knowledge_edges_no_self_ref;
ALTER TABLE knowledge_edges ADD CONSTRAINT knowledge_edges_no_self_ref
    CHECK (source_id != target_id OR edge_type IN ('schema_fk', 'schema_implicit'));

-- Add index for querying schema-generated nodes by data source
CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_properties_source
    ON knowledge_nodes USING gin ((properties->'source_data_source_id'));
```

```sql
-- 000025_extend_kg_properties.down.sql
DROP INDEX IF EXISTS idx_knowledge_nodes_properties_source;
ALTER TABLE knowledge_edges DROP CONSTRAINT IF EXISTS knowledge_edges_no_self_ref;
ALTER TABLE knowledge_edges ADD CONSTRAINT knowledge_edges_no_self_ref
    CHECK (source_id != target_id);
```

- [ ] **Step 2: Write migration 026 — kg_generation_jobs**

```sql
-- 000026_create_kg_generation_jobs.up.sql
CREATE TABLE kg_generation_jobs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    data_source_id  UUID NOT NULL REFERENCES data_sources(id),
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',
    nodes_created   INTEGER DEFAULT 0,
    edges_explicit  INTEGER DEFAULT 0,
    edges_implicit  INTEGER DEFAULT 0,
    edges_rejected  INTEGER DEFAULT 0,
    error_message   TEXT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT kg_gen_jobs_status_check CHECK (status IN ('pending','running','completed','failed'))
);

CREATE INDEX idx_kg_gen_jobs_ds ON kg_generation_jobs(data_source_id);
CREATE INDEX idx_kg_gen_jobs_status ON kg_generation_jobs(status) WHERE status IN ('pending','running');
```

```sql
-- 000026_create_kg_generation_jobs.down.sql
DROP TABLE IF EXISTS kg_generation_jobs;
```

- [ ] **Step 3: Commit**

```bash
git add db/migrations/000025_* db/migrations/000026_*
git commit -m "feat(db): extend KG properties and add kg_generation_jobs table (BA-008)"
```

---

## Task 2: KG Generation Model + Store

**Files:**
- Create: `internal/models/kg_generation.go`
- Create: `internal/store/kg_generation.go`
- Create: `internal/store/kg_generation_test.go`

- [ ] **Step 1: Write KGGenerationJob model**

```go
// internal/models/kg_generation.go
package models

import "time"

// KGGenerationJob tracks a KG generation pipeline run.
type KGGenerationJob struct {
	ID             string     `json:"id" db:"id"`
	DataSourceID   string     `json:"data_source_id" db:"data_source_id"`
	Status         string     `json:"status" db:"status"`
	NodesCreated   int        `json:"nodes_created" db:"nodes_created"`
	EdgesExplicit  int        `json:"edges_explicit" db:"edges_explicit"`
	EdgesImplicit  int        `json:"edges_implicit" db:"edges_implicit"`
	EdgesRejected  int        `json:"edges_rejected" db:"edges_rejected"`
	ErrorMessage   *string    `json:"error_message,omitempty" db:"error_message"`
	StartedAt      *time.Time `json:"started_at,omitempty" db:"started_at"`
	CompletedAt    *time.Time `json:"completed_at,omitempty" db:"completed_at"`
	CreatedAt      time.Time  `json:"created_at" db:"created_at"`
}

// SchemaNodeProperties holds JSONB properties for schema-generated knowledge_nodes.
type SchemaNodeProperties struct {
	NodeSubtype       string `json:"node_subtype"`        // "schema_table"
	SourceDataSourceID string `json:"source_data_source_id"`
	SourceTableName   string `json:"source_table_name"`
	SchemaGroup       string `json:"schema_group"`
	ColumnCount       int    `json:"column_count"`
	RowCountEstimate  int64  `json:"row_count_estimate"`
	AIDescription     string `json:"ai_description,omitempty"`
	AIDescriptionEdited bool `json:"ai_description_edited,omitempty"`
}

// SchemaEdgeProperties holds JSONB properties for schema-generated knowledge_edges.
type SchemaEdgeProperties struct {
	ConfidenceScore    float64 `json:"confidence_score"`
	DetectionMethod    string  `json:"detection_method"`    // explicit_fk, ai_detected, admin_confirmed
	Cardinality        string  `json:"cardinality"`         // one_to_one, one_to_many, many_to_many
	SourceColumn       string  `json:"source_column,omitempty"`
	TargetColumn       string  `json:"target_column,omitempty"`
	FKConstraintName   string  `json:"fk_constraint_name,omitempty"`
	AdminScoreOverride bool    `json:"admin_score_override,omitempty"`
	Status             string  `json:"status,omitempty"`    // active, rejected
}
```

- [ ] **Step 2: Write KGGenerationStore**

```go
// internal/store/kg_generation.go
package store

// Methods needed:
// CreateJob(ctx, job) error
// GetJob(ctx, id) (*KGGenerationJob, error)
// UpdateJob(ctx, job) error
// GetNodesByDataSource(ctx, dataSourceID) ([]*KnowledgeNode, error)
// GetEdgesByDataSource(ctx, dataSourceID, filters) ([]*KnowledgeEdge, error)
// UpdateEdgeConfidence(ctx, edgeID, confidence float64) error
// ConfirmEdge(ctx, edgeID) error
// RejectEdge(ctx, edgeID) error
// UnrejectEdge(ctx, edgeID) error
```

Key queries:
- `GetNodesByDataSource`: `SELECT * FROM knowledge_nodes WHERE properties->>'source_data_source_id' = $1 AND properties->>'node_subtype' = 'schema_table'`
- `GetEdgesByDataSource`: JOIN on source/target nodes that belong to the data source, filter by detection_method and confidence threshold
- `ConfirmEdge`: `UPDATE properties SET detection_method='admin_confirmed', confidence_score=1.0`
- `RejectEdge`: `UPDATE properties SET status='rejected'`

- [ ] **Step 3: Write tests, verify compilation**

- [ ] **Step 4: Commit**

```bash
git add internal/models/kg_generation.go internal/store/kg_generation.go internal/store/kg_generation_test.go
git commit -m "feat(store): add KGGenerationStore with job tracking and edge management (BA-008)"
```

---

## Task 3: Explicit FK → Edge Mapper

**Files:**
- Create: `internal/service/kg_explicit.go`
- Create: `internal/service/kg_explicit_test.go`

- [ ] **Step 1: Write failing tests for FK mapping**

Test cases:
- Simple FK: `orders.customer_id → customers.id` → one edge, cardinality=one_to_many
- Unique FK: FK column has UNIQUE → cardinality=one_to_one
- Junction table: exactly 2 FKs + composite PK → 3 edges (source→junction, target→junction, source→target M:N)
- Self-referential: `employees.manager_id → employees.id` → same source/target node
- Composite FK: multiple columns → single edge with all columns listed
- Idempotent: calling twice doesn't duplicate edges

- [ ] **Step 2: Implement ExplicitEdgeMapper**

```go
// internal/service/kg_explicit.go
type ExplicitEdgeMapper struct {
    metaStore *store.SchemaMetadataStore
    nodeStore *store.NodeStore
    edgeStore *store.EdgeStore
    logger    *slog.Logger
}

// MapForeignKeys reads all FKs from schema metadata and creates knowledge_edges.
// Returns count of edges created.
func (m *ExplicitEdgeMapper) MapForeignKeys(ctx context.Context, dataSourceID, projectID string) (int, error)
```

Cardinality determination:
1. Get FK constraint
2. Check if FK column has UNIQUE index → one_to_one
3. Check junction table pattern (exactly 2 FKs + composite PK covering both) → many_to_many
4. Default → one_to_many

Edge properties: `confidence_score=1.0`, `detection_method="explicit_fk"`, `cardinality`, `source_column`, `target_column`, `fk_constraint_name`

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Commit**

```bash
git add internal/service/kg_explicit.go internal/service/kg_explicit_test.go
git commit -m "feat(service): add ExplicitEdgeMapper for FK→edge with cardinality (BA-008)"
```

---

## Task 4: KG Node Generator

**Files:**
- Create: `internal/service/kg_generator.go` (partial — node generation part)
- Create: `internal/service/kg_generator_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- One node per table with `node_type=architecture`, `node_subtype=schema_table`
- Title format: `public.orders` (schema.table_name)
- Properties include: column_count, row_count_estimate, source_data_source_id
- AI description generation via Selector.Send() (mock)
- Graceful degradation: if AI unavailable, create node without description
- Idempotent: re-run updates existing nodes

- [ ] **Step 2: Implement KGGenerator (node creation)**

```go
type KGGenerator struct {
    metaStore     *store.SchemaMetadataStore
    kgStore       *store.KGGenerationStore
    nodeStore     *store.NodeStore
    edgeStore     *store.EdgeStore
    aiSelector    *ai.Selector  // may be nil
    explicitMapper *ExplicitEdgeMapper
    implicitDetector *ImplicitDetector
    logger        *slog.Logger
}

func (g *KGGenerator) Generate(ctx context.Context, dataSourceID, projectID string) (*models.KGGenerationJob, error)
func (g *KGGenerator) generateNodes(ctx context.Context, dataSourceID, projectID string, job *models.KGGenerationJob) error
```

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Commit**

```bash
git add internal/service/kg_generator.go internal/service/kg_generator_test.go
git commit -m "feat(service): add KGGenerator with node creation and AI description (BA-008)"
```

---

## Task 5: Implicit Relationship Detector

**Files:**
- Create: `internal/service/kg_implicit.go`
- Create: `internal/service/kg_implicit_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- Naming convention: `orders.customer_id` matches `customers.id` → candidate
- Type compatibility: both INTEGER or both UUID → candidate; mismatched types → skip
- Skip columns with existing FK constraints
- Minimum 2 forms of evidence (naming + type) before AI scoring
- AI confidence scoring returns 0.0-1.0
- Default threshold 0.5: below → excluded from default queries
- Graceful degradation: if AI unavailable, skip implicit detection entirely

- [ ] **Step 2: Implement ImplicitDetector**

```go
type ImplicitDetector struct {
    metaStore  *store.SchemaMetadataStore
    aiSelector *ai.Selector
    logger     *slog.Logger
}

// DetectImplicit finds non-FK relationships using naming conventions and AI scoring.
func (d *ImplicitDetector) DetectImplicit(ctx context.Context, dataSourceID, projectID string) ([]ImplicitCandidate, error)

type ImplicitCandidate struct {
    SourceTable  string
    SourceColumn string
    TargetTable  string
    TargetColumn string
    Evidence     []string  // ["naming_match", "type_compatible", "value_overlap"]
    Confidence   float64
}
```

Naming patterns to check:
- `<table_name>_id` (e.g., `customer_id` → `customers`)
- `<singular_table_name>_id` (e.g., `customer_id` → `customer`)
- `<table_name>Id` (camelCase)
- `fk_<table_name>`

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Commit**

```bash
git add internal/service/kg_implicit.go internal/service/kg_implicit_test.go
git commit -m "feat(service): add ImplicitDetector for AI-powered relationship discovery (BA-008)"
```

---

## Task 6: KG Generation Handler (9 endpoints)

**Files:**
- Create: `internal/handler/kg_generation.go`
- Create: `internal/handler/kg_generation_test.go`

- [ ] **Step 1: Define handler + routes**

```go
type KGGenerationHandler struct {
    generator *service.KGGenerator
    kgStore   *store.KGGenerationStore
    logger    *slog.Logger
}

func (h *KGGenerationHandler) RegisterRoutes(mux *http.ServeMux) {
    mux.HandleFunc("POST /api/v1/data-sources/{id}/generate-kg", h.GenerateKG)
    mux.HandleFunc("GET /api/v1/data-sources/{id}/kg-nodes", h.ListKGNodes)
    mux.HandleFunc("PATCH /api/v1/kg-nodes/{id}", h.UpdateNodeDescription)
    mux.HandleFunc("GET /api/v1/data-sources/{id}/kg-edges", h.ListKGEdges)
    mux.HandleFunc("PATCH /api/v1/kg-edges/{id}/confidence", h.UpdateConfidence)
    mux.HandleFunc("POST /api/v1/kg-edges/{id}/confirm", h.ConfirmEdge)
    mux.HandleFunc("POST /api/v1/kg-edges/{id}/reject", h.RejectEdge)
    mux.HandleFunc("POST /api/v1/kg-edges/{id}/unreject", h.UnrejectEdge)
    mux.HandleFunc("GET /api/v1/data-sources/{id}/kg-status", h.GetKGStatus)
}
```

Endpoint details:
- `POST generate-kg` → 202 Accepted, returns KGGenerationJob
- `GET kg-nodes` → 200, filter by data source
- `PATCH kg-nodes/{id}` → 200, update ai_description (sets ai_description_edited=true)
- `GET kg-edges` → 200, filter by detection_method, min confidence
- `PATCH kg-edges/{id}/confidence` → 200, body: `{"confidence": 0.8}`
- `POST confirm` → 200, sets confidence=1.0, detection_method=admin_confirmed
- `POST reject` → 200, sets status=rejected
- `POST unreject` → 200, sets status=active
- `GET kg-status` → 200, latest KGGenerationJob for data source

- [ ] **Step 2: Implement all endpoints**

- [ ] **Step 3: Write tests, verify compilation**

- [ ] **Step 4: Commit**

```bash
git add internal/handler/kg_generation.go internal/handler/kg_generation_test.go
git commit -m "feat(handler): add KGGenerationHandler with 9 endpoints (BA-008)"
```

---

## Task 7: Wire into Composition Root

**Files:**
- Modify: `cmd/kg-server/main.go`

- [ ] **Step 1: Wire KG generation handler after DataSource handler**

```go
// Register KG generation handlers (BA-008).
kgGenStore := store.NewKGGenerationStore(db)
explicitMapper := service.NewExplicitEdgeMapper(metaStore, nodeStore, edgeStore, logger)
implicitDetector := service.NewImplicitDetector(metaStore, aiSelector, logger)
kgGenerator := service.NewKGGenerator(metaStore, kgGenStore, nodeStore, edgeStore, aiSelector, explicitMapper, implicitDetector, logger)
kgGenHandler := handler.NewKGGenerationHandler(kgGenerator, kgGenStore, logger)
kgGenHandler.RegisterRoutes(apiMux)
logger.Info("KG generation endpoints enabled")
```

- [ ] **Step 2: Verify compilation + commit**

```bash
go build ./cmd/kg-server/...
git add cmd/kg-server/main.go
git commit -m "feat(server): wire KG generation handler into composition root (BA-008)"
```

---

## Task Summary

| # | Task | Files | Effort |
|---|------|-------|--------|
| 1 | Migrations 025-026 | 4 SQL files | Small |
| 2 | Model + Store | 3 Go files | Medium |
| 3 | Explicit FK Mapper | 2 Go files | Large — cardinality + junction tables |
| 4 | KG Node Generator | 2 Go files | Large — AI description integration |
| 5 | Implicit Detector | 2 Go files | Large — naming patterns + AI scoring |
| 6 | Handler (9 endpoints) | 2 Go files | Medium |
| 7 | Wire composition root | 1 file modify | Small |
| **Total** | **7 tasks** | **~16 files** | |
