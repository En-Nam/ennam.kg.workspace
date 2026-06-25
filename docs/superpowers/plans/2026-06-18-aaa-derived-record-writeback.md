# AAA Derived-Record Write-Back (IMP-010) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give AAA (and future satellites) a KG-side write surface to record a computed Master Record as its own `derived_record` graph node with provenance edges, so the ecosystem loop closes (trace a record → its source docs, and a doc → which records used it).

**Architecture:** A new generic closed-vocab node type `derived_record` (R2 — distinct from BA-031's entity `master_record`), an idempotent upsert endpoint keyed on `(project, source_system, record_ref)`, one routed write MCP tool `kg_upsert_derived_record`, and edge-whitelist rules so provenance is written with the existing `kg_link`. Reverse-usage reuses existing read tools.

**Tech Stack:** Go (`net/http`, `database/sql`), `golang-migrate`, the closed-vocab config (`config/config.yaml`), the MCP bridge (`internal/bridge`).

**Spec:** `docs/superpowers/specs/2026-06-18-aaa-derived-record-writeback-design.md` · **Requirement:** `ennam.kg.requirements/documents/improvements/IMP-010-aaa-masterrecord-writeback-tools.md`

## Global Constraints

- **Closed vocabulary:** every node type must pass ALL gates (migration CHECK, `config.yaml` `node_types` + `search` blocks, `config.ValidNodeTypes`, the 3 hardcoded handler filter allowlists, `validate_test`). Missing the `search:` block makes `/query` return **500** at runtime, not build time.
- **`config.yaml` is read at startup** (not hot-reloaded by `air`) — restart kg-server after editing it.
- **Do NOT touch BA-031's `master_record`** node type (entity-merge) — `derived_record` is a separate, new type (R2).
- **Tool design (Qwen LCD):** snake_case, ≤4 required params, no nested objects.
- **`kg_upsert_derived_record` is write-class** (IMP-008); AAA uses a write-scoped credential.
- **Provenance edges use the existing `kg_link`** — this plan only adds whitelist rules, never a new edge tool.
- All `cd` into `ennam.kg.go` for Go commands. Migration next free number is **000067** (verified).

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `db/migrations/000067_add_derived_record.{up,down}.sql` | node_type CHECK + idempotency partial unique index | Create |
| `config/config.yaml` | `derived_record` node schema, `search:` block, edge whitelist rules | Modify |
| `internal/config/types.go` | `NodeTypeDerivedRecord` const + `ValidNodeTypes` entry | Modify |
| `internal/handler/neighbors.go:151` | add `derived_record` to the filter allowlist (FR-5) | Modify |
| `internal/filter/validate_test.go` | `derived_record` search-block regression test | Modify |
| `internal/store/node.go` | `FindDerivedRecordByKey` JSONB lookup | Modify |
| `internal/handler/derived_record.go` | upsert handler + route registration | Create |
| `cmd/kg-server/main.go` | wire the handler onto `apiMux` | Modify |
| `internal/bridge/schema.go`, `client.go` | `kg_upsert_derived_record` schema + route (RouteWrite) | Modify |
| `internal/bridge/schema_test.go` | count 40→41 + presence test | Modify |

---

## Task 1: Register the `derived_record` node type (all gates)

**Files:**
- Create: `db/migrations/000067_add_derived_record.up.sql`, `db/migrations/000067_add_derived_record.down.sql`
- Modify: `config/config.yaml` (`node_types:`, `search:`), `internal/config/types.go`, `internal/handler/neighbors.go`
- Test: `internal/filter/validate_test.go`

**Interfaces:**
- Produces: `config.NodeTypeDerivedRecord` (`NodeTypeName = "derived_record"`), present in `config.ValidNodeTypes`; a valid `node_types:`+`search:` config entry; the idempotency index `idx_derived_record_key`.

- [ ] **Step 1: Write the failing search-block regression test**

In `internal/filter/validate_test.go`, add (mirrors `TestNewValidationContext_DocumentChunk_HasSearchConfig` at line 331):

```go
func TestNewValidationContext_DerivedRecord_HasSearchConfig(t *testing.T) {
	cfg, err := config.Load("../../config/config.yaml")
	if err != nil {
		t.Fatalf("failed to load real config.yaml: %v", err)
	}
	ctx, err := NewValidationContext(cfg, config.NodeTypeDerivedRecord)
	if err != nil {
		t.Fatalf("NewValidationContext for derived_record failed — search block missing? error: %v", err)
	}
	if ctx.NodeType != config.NodeTypeDerivedRecord {
		t.Errorf("node type = %q, want %q", ctx.NodeType, config.NodeTypeDerivedRecord)
	}
}
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd ennam.kg.go && go test ./internal/filter/ -run TestNewValidationContext_DerivedRecord -v`
Expected: FAIL — `config.NodeTypeDerivedRecord` undefined (and, once defined, missing search block).

- [ ] **Step 3: Add the type const + ValidNodeTypes entry**

In `internal/config/types.go`, after `NodeTypeProject` (line ~62):

```go
	NodeTypeDerivedRecord NodeTypeName = "derived_record"
```

And in the `ValidNodeTypes` map, after `NodeTypeProject: true,`:

```go
	// IMP-010: satellite-computed records (AAA Master Record first)
	NodeTypeDerivedRecord: true,
```

- [ ] **Step 4: Add the migration (CHECK + idempotency index)**

`db/migrations/000067_add_derived_record.up.sql`:

```sql
-- IMP-010: register the generic derived_record node type (AAA Master Record first).
-- Distinct from BA-031 master_record (entity merge). Extends the node_type CHECK
-- and adds the idempotency index for keyed upsert.
ALTER TABLE knowledge_nodes DROP CONSTRAINT IF EXISTS knowledge_nodes_node_type_check;

ALTER TABLE knowledge_nodes ADD CONSTRAINT knowledge_nodes_node_type_check
    CHECK (node_type IN (
        'decision', 'concept', 'requirement', 'task',
        'architecture', 'discovery', 'session',
        'initiative', 'document', 'document_section', 'document_chunk', 'dataset', 'external',
        'person', 'organization', 'event', 'document_ref',
        'location', 'artifact', 'master_record', 'project',
        'derived_record'
    ));

-- Race-safe idempotency for kg_upsert_derived_record (project, source_system, record_ref).
-- Partial unique INDEX (not a table constraint — JSONB expressions + predicate require an index).
-- knowledge_nodes has no deleted_at; predicate is node_type only.
CREATE UNIQUE INDEX idx_derived_record_key
    ON knowledge_nodes (project_id, (properties->>'source_system'), (properties->>'record_ref'))
    WHERE node_type = 'derived_record';
```

`db/migrations/000067_add_derived_record.down.sql`:

```sql
DROP INDEX IF EXISTS idx_derived_record_key;

ALTER TABLE knowledge_nodes DROP CONSTRAINT IF EXISTS knowledge_nodes_node_type_check;
ALTER TABLE knowledge_nodes ADD CONSTRAINT knowledge_nodes_node_type_check
    CHECK (node_type IN (
        'decision', 'concept', 'requirement', 'task',
        'architecture', 'discovery', 'session',
        'initiative', 'document', 'document_section', 'document_chunk', 'dataset', 'external',
        'person', 'organization', 'event', 'document_ref',
        'location', 'artifact', 'master_record', 'project'
    ));
```

- [ ] **Step 5: Add the `node_types:` schema block in `config/config.yaml`**

Under `node_types:`, after the `master_record:` block (mirror its shape):

```yaml
  derived_record:
    display_name: "Derived Record"
    description: "A satellite-computed record about a Project/entity (e.g. AAA Master Record). Content lives in the source system; KG holds anchor + summary + provenance (IMP-010)."
    required:
      - title
      - subtype
      - source_system
      - record_ref
    fields:
      title:
        type: string
        min_length: 1
        max_length: 200
        description: "Human-readable record title"
      subtype:
        type: string
        max_length: 100
        description: "Record kind, e.g. master_record, valuation, legal_study"
      source_system:
        type: string
        max_length: 100
        description: "Producing system, e.g. aaa"
      record_ref:
        type: string
        max_length: 200
        description: "External id in the source system (idempotency key), e.g. AAA EntityProfile.id"
      summary:
        type: text
        max_length: 2000
        description: "Short human-readable summary; full content stays in the source system"
      provenance:
        type: json
        description: "Source references {source_doc_id, chunk_id, sentence_span}"
```

- [ ] **Step 6: Add the `search:` block (without this `/query` 500s)**

Under `search:`, after the `master_record:` entry:

```yaml
  derived_record:
    text_search: [title, summary]
    filterable: [subtype, source_system]
    sort_fields: [title, subtype]
```

- [ ] **Step 7: Add `derived_record` to the `neighbors.go` filter allowlist**

In `internal/handler/neighbors.go:151`, add to the `validNodeTypes` map so reverse-usage can filter `node_types=[derived_record]` (FR-5):

```go
		"derived_record": true,
```

(query.go:237 and search.go:187 are the same hardcoded pattern; adding there is optional — only `neighbors.go` is exercised by FR-5's inbound query. Leave the broader consolidation as a backlog note.)

- [ ] **Step 8: Run the gate test + config load**

Run: `go test ./internal/filter/ -run TestNewValidationContext_DerivedRecord -v && go test ./internal/config/ -run TestConfig -v`
Expected: PASS (config loads with the new blocks; validation context builds).

- [ ] **Step 9: Apply the migration + live `/query` smoke (the runtime gate)**

Run (dockerized deps up):
```bash
make db-migrate              # verified target: go run ./cmd/kg-migrate/ up
go run ./cmd/kg-server/ &    # restart so config.yaml reloads
curl -s -X POST localhost:8080/api/v1/query -H 'Content-Type: application/json' \
  -d '{"node_type":"derived_record","limit":1}' -H "Authorization: Bearer $KG_TOKEN" | head
```
Expected: HTTP 200 with an (empty) result set — **not** 500. (Confirms the `search:` block gate.)

- [ ] **Step 10: Commit**

```bash
git add db/migrations/000067_add_derived_record.up.sql db/migrations/000067_add_derived_record.down.sql config/config.yaml internal/config/types.go internal/handler/neighbors.go internal/filter/validate_test.go
git commit -m "feat(kg): register derived_record node type (all gates + idempotency index)"
```

---

## Task 2: Edge whitelist for `derived_record` provenance

**Files:**
- Modify: `config/config.yaml` (`edge_whitelist:`)
- Test: `internal/validation/edge_whitelist_test.go`

**Interfaces:**
- Consumes: `config.NodeTypeDerivedRecord` (Task 1), `config.EdgeTypeDerivedFrom`, `config.EdgeTypeEvidence` (existing).
- Produces: Gate-1 acceptance of `derived_record → derived_from → {project, entities}` and `derived_record → evidence → {document_chunk, document_ref, artifact}`.

- [ ] **Step 1: Write the failing whitelist test**

In `internal/validation/edge_whitelist_test.go` (mirror existing tests in that file for how `cfg` is loaded):

```go
func TestValidateEdge_DerivedRecordProvenance(t *testing.T) {
	cfg, err := config.Load("../../config/config.yaml")
	if err != nil {
		t.Fatalf("load config: %v", err)
	}
	v := NewEdgeWhitelistValidator(cfg)

	// Allowed: record evidenced by a chunk; record derived from its project.
	if err := v.ValidateEdge(config.NodeTypeDerivedRecord, config.EdgeTypeEvidence, config.NodeTypeDocumentChunk); err != nil {
		t.Errorf("derived_record→evidence→document_chunk should be allowed: %v", err)
	}
	if err := v.ValidateEdge(config.NodeTypeDerivedRecord, config.EdgeTypeDerivedFrom, config.NodeTypeProject); err != nil {
		t.Errorf("derived_record→derived_from→project should be allowed: %v", err)
	}
	// Rejected: an entity is not a valid evidence target (belongs under derived_from).
	if err := v.ValidateEdge(config.NodeTypeDerivedRecord, config.EdgeTypeEvidence, config.NodeTypePerson); err == nil {
		t.Error("derived_record→evidence→person should be rejected")
	}
}
```

- [ ] **Step 2: Run it — verify it fails**

Run: `go test ./internal/validation/ -run TestValidateEdge_DerivedRecordProvenance -v`
Expected: FAIL — the rules do not exist yet (the allowed edges return an error).

- [ ] **Step 3: Add the whitelist rules in `config/config.yaml`**

Under `edge_whitelist:`, add:

```yaml
  - source: derived_record
    relationship: derived_from
    targets: [project, person, organization, event, location, artifact, concept, document_ref]
    description: "A satellite-computed record was derived from these entities/project"
    constraints:
      allow_cross_project: false

  - source: derived_record
    relationship: evidence
    targets: [document_chunk, document_ref, artifact]
    description: "A derived record is directly evidenced by these chunks/references"
    constraints:
      allow_cross_project: false
```

- [ ] **Step 4: Run it — verify it passes**

Run: `go test ./internal/validation/ -run TestValidateEdge_DerivedRecordProvenance -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config/config.yaml internal/validation/edge_whitelist_test.go
git commit -m "feat(kg): whitelist derived_record provenance edges (derived_from + evidence→chunk)"
```

---

## Task 3: Store lookup `FindDerivedRecordByKey`

**Files:**
- Modify: `internal/store/node.go`
- Test: `internal/store/node_test.go` (or `node_derived_record_test.go`)

**Interfaces:**
- Produces: `func (s *NodeStore) FindDerivedRecordByKey(ctx context.Context, projectID, sourceSystem, recordRef string) (*models.KnowledgeNode, error)` — returns the node, or an error wrapping `sql.ErrNoRows` when absent.

- [ ] **Step 1: Write the failing test**

In the store tests (mirror the DB/seed helpers already used in `internal/store/*_test.go`):

```go
func TestNodeStore_FindDerivedRecordByKey(t *testing.T) {
	db := newTestDB(t)
	store := NewNodeStore(db)
	ctx := context.Background()
	projectID := seedProject(t, db)

	// Arrange: a derived_record node with source_system+record_ref in properties.
	props := []byte(`{"subtype":"master_record","source_system":"aaa","record_ref":"ep-1","summary":"s"}`)
	created, err := store.CreateNode(ctx, CreateNodeParams{
		ProjectID: projectID, NodeType: "derived_record", Title: "MR for P", Properties: props,
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	// Act
	got, err := store.FindDerivedRecordByKey(ctx, projectID, "aaa", "ep-1")
	if err != nil {
		t.Fatalf("FindDerivedRecordByKey: %v", err)
	}
	if got.ID != created.ID {
		t.Errorf("got %q, want %q", got.ID, created.ID)
	}

	// Unknown key → error.
	if _, err := store.FindDerivedRecordByKey(ctx, projectID, "aaa", "nope"); err == nil {
		t.Error("expected error for unknown key")
	}
}
```

- [ ] **Step 2: Run it — verify it fails**

Run: `go test ./internal/store/ -run TestNodeStore_FindDerivedRecordByKey -v`
Expected: FAIL — `FindDerivedRecordByKey` undefined.

- [ ] **Step 3: Implement the query**

Add to `internal/store/node.go`. `GetNode` (`node.go:334`) inlines its scan (there is **no** shared `scanNode` helper), so inline the identical column list + scan here:

```go
// FindDerivedRecordByKey returns the derived_record node matching the idempotency
// key (project, source_system, record_ref), or an error wrapping sql.ErrNoRows.
func (s *NodeStore) FindDerivedRecordByKey(ctx context.Context, projectID, sourceSystem, recordRef string) (*models.KnowledgeNode, error) {
	query := `
		SELECT id, project_id, node_type, title, status, properties, scope, version,
		       change_reason, created_by, created_at, updated_at, session_id
		FROM knowledge_nodes
		WHERE project_id = $1
		  AND node_type = 'derived_record'
		  AND properties->>'source_system' = $2
		  AND properties->>'record_ref' = $3
		LIMIT 1`
	var node models.KnowledgeNode
	err := s.db.QueryRowContext(ctx, query, projectID, sourceSystem, recordRef).Scan(
		&node.ID, &node.ProjectID, &node.NodeType, &node.Title, &node.Status,
		&node.Properties, &node.Scope, &node.Version, &node.ChangeReason,
		&node.CreatedBy, &node.CreatedAt, &node.UpdatedAt, &node.SessionID,
	)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("derived_record (%s/%s) not found: %w", sourceSystem, recordRef, err)
		}
		return nil, fmt.Errorf("find derived_record by key: %w", err)
	}
	return &node, nil
}
```

- [ ] **Step 4: Run it — verify it passes**

Run: `go test ./internal/store/ -run TestNodeStore_FindDerivedRecordByKey -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/store/node.go internal/store/node_test.go
git commit -m "feat(store): FindDerivedRecordByKey for idempotent derived_record upsert"
```

---

## Task 4: Upsert endpoint + handler

**Files:**
- Create: `internal/handler/derived_record.go`
- Modify: `cmd/kg-server/main.go` (wire handler)
- Test: `internal/handler/derived_record_test.go`

**Interfaces:**
- Consumes: `store.FindDerivedRecordByKey` (Task 3); `service.NodeService.StoreNode(ctx, service.StoreNodeRequest) (*service.StoreNodeResponse, error)` (`node.go:201`); `service.UpdateService.UpdateNode(ctx, service.UpdateNodeRequest) (*service.UpdateNodeResponse, error)` (`update.go:117`).
- Produces: `POST /api/v1/projects/{projectId}/derived-records` → `{"node_id": "<uuid>"}`; handler `DerivedRecordHandler` with `RegisterRoutes(mux *http.ServeMux)`.

- [ ] **Step 1: Write the failing idempotency test**

`internal/handler/derived_record_test.go` (mirror `internal/handler/node_test.go` for the mock repo + httptest setup):

```go
func TestDerivedRecord_UpsertIsIdempotent(t *testing.T) {
	h, projectID := newTestDerivedRecordHandler(t) // wires real-ish store + services over a test DB

	body := `{"title":"MR for P","subtype":"master_record","source_system":"aaa","record_ref":"ep-1","summary":"v1"}`
	id1 := doUpsert(t, h, projectID, body)

	// Re-submit same key with an updated summary → same node, merged.
	body2 := `{"title":"MR for P","subtype":"master_record","source_system":"aaa","record_ref":"ep-1","summary":"v2"}`
	id2 := doUpsert(t, h, projectID, body2)

	if id1 != id2 {
		t.Errorf("re-upsert created a new node: %q != %q", id1, id2)
	}
	// And exactly one derived_record exists for that key.
	if got, _ := h.store.FindDerivedRecordByKey(context.Background(), projectID, "aaa", "ep-1"); got.ID != id1 {
		t.Errorf("key resolves to %q, want %q", got.ID, id1)
	}
}
```

(`doUpsert` posts the body to the handler via `httptest` and returns the `node_id`; `newTestDerivedRecordHandler` builds the handler against the same test DB Task 3 uses.)

> **Harness note (load-bearing):** the `UpdateService` in the test MUST be built with `service.WithNodeReader(nodeStore)` (mirror `main.go:409`) — without it `UpdateNode` cannot fetch the existing node and silently **REPLACES** properties instead of merging, so the merge assertion would pass for the wrong reason. Build `nodeSvc` and `updateSvc` exactly as `main.go` does.

- [ ] **Step 2: Run it — verify it fails**

Run: `go test ./internal/handler/ -run TestDerivedRecord_UpsertIsIdempotent -v`
Expected: FAIL — handler/constructor undefined.

- [ ] **Step 3: Implement the handler**

`internal/handler/derived_record.go`:

```go
package handler

import (
	"encoding/json"
	"net/http"

	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/service"
	"github.com/ennam/ennam-kg/internal/store"
)

type DerivedRecordHandler struct {
	store     *store.NodeStore
	nodeSvc   *service.NodeService
	updateSvc *service.UpdateService
}

func NewDerivedRecordHandler(s *store.NodeStore, nodeSvc *service.NodeService, updateSvc *service.UpdateService) *DerivedRecordHandler {
	return &DerivedRecordHandler{store: s, nodeSvc: nodeSvc, updateSvc: updateSvc}
}

func (h *DerivedRecordHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/projects/{projectId}/derived-records", h.Upsert)
}

type upsertDerivedRecordRequest struct {
	Title        string `json:"title"`
	Subtype      string `json:"subtype"`
	SourceSystem string `json:"source_system"`
	RecordRef    string `json:"record_ref"`
	Summary      string `json:"summary,omitempty"`
}

func (h *DerivedRecordHandler) Upsert(w http.ResponseWriter, r *http.Request) {
	projectID := r.PathValue("projectId")
	var req upsertDerivedRecordRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid body")
		return
	}
	if req.Title == "" || req.Subtype == "" || req.SourceSystem == "" || req.RecordRef == "" {
		errorResponse(w, http.StatusBadRequest, "title, subtype, source_system, record_ref are required")
		return
	}
	// Service-layer Properties is a map (validated against the config schema), NOT raw JSON.
	props := map[string]interface{}{
		"subtype":       req.Subtype,
		"source_system": req.SourceSystem,
		"record_ref":    req.RecordRef,
		"summary":       req.Summary,
	}

	if existing, err := h.store.FindDerivedRecordByKey(r.Context(), projectID, req.SourceSystem, req.RecordRef); err == nil && existing != nil {
		h.update(w, r, existing, req.Title, props)
		return
	}

	// Create path. A concurrent create trips idx_derived_record_key → re-find + update.
	resp, serr := h.nodeSvc.StoreNode(r.Context(), service.StoreNodeRequest{
		ProjectID:  projectID,
		NodeType:   "derived_record",
		Title:      req.Title,
		Properties: props,
		CreatedBy:  req.SourceSystem,
	})
	if serr != nil {
		if again, ferr := h.store.FindDerivedRecordByKey(r.Context(), projectID, req.SourceSystem, req.RecordRef); ferr == nil && again != nil {
			h.update(w, r, again, req.Title, props)
			return
		}
		errorResponse(w, http.StatusInternalServerError, "create derived_record: "+serr.Error())
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"node_id": resp.Node.ID})
}

// update merges into an existing derived_record. Properties is a partial update
// (only provided keys change); UpdateNode requires ExpectedVersion + ChangeReason + ChangedBy.
func (h *DerivedRecordHandler) update(w http.ResponseWriter, r *http.Request, existing *models.KnowledgeNode, title string, props map[string]interface{}) {
	t := title
	if _, err := h.updateSvc.UpdateNode(r.Context(), service.UpdateNodeRequest{
		ID:              existing.ID,
		ExpectedVersion: existing.Version,
		Title:           &t,
		Properties:      props,
		ChangeReason:    "derived_record upsert",
		ChangedBy:       existing.CreatedBy,
	}); err != nil {
		// version mismatch (concurrent edit) → 409; AAA may retry
		errorResponse(w, http.StatusConflict, "update derived_record: "+err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"node_id": existing.ID})
}
```

> `errorResponse` (`search.go:88`) and `writeJSON` (`document.go:247`) are package-level helpers in `internal/handler` — usable directly (do **not** use `h.handleServiceError`, which is a method on other handlers, not this one). Confirm `StoreNodeRequest` field names against `node.go:66` (verified: `ProjectID`, `NodeType`, `Title`, `Properties map[string]interface{}`, `CreatedBy`).

- [ ] **Step 4: Wire the handler onto `apiMux`**

In `cmd/kg-server/main.go`, next to the other `RegisterRoutes(apiMux)` calls (~line 371), construct with the existing instances (verified names: `nodeStore` `main.go:365`, `nodeSvc` `main.go:367`, `updateSvc` `main.go:409`):

```go
	derivedRecordHandler := handler.NewDerivedRecordHandler(nodeStore, nodeSvc, updateSvc)
	derivedRecordHandler.RegisterRoutes(apiMux)
```

- [ ] **Step 5: Run it — verify it passes**

Run: `go test ./internal/handler/ -run TestDerivedRecord_UpsertIsIdempotent -v && go build ./...`
Expected: PASS + build clean.

- [ ] **Step 6: Commit**

```bash
git add internal/handler/derived_record.go internal/handler/derived_record_test.go cmd/kg-server/main.go
git commit -m "feat(handler): idempotent derived_record upsert endpoint"
```

---

## Task 5: Bridge tool `kg_upsert_derived_record`

**Files:**
- Modify: `internal/bridge/client.go` (`toolRoutes`), `internal/bridge/schema.go` (schema)
- Test: `internal/bridge/schema_test.go`

**Interfaces:**
- Consumes: the `POST /api/v1/projects/{projectId}/derived-records` route (Task 4).
- Produces: routed write tool `kg_upsert_derived_record` (schema count 40→41).

- [ ] **Step 1: Bump count + presence test**

In `internal/bridge/schema_test.go`, the count assertion in `TestAllToolSchemasRegistered` is `if len(schemas) != 40` (line 53) — change to `!= 41`. Add:

```go
func TestSchema_HasUpsertDerivedRecord(t *testing.T) {
	schemas := ListToolSchemas()
	s, ok := schemas["kg_upsert_derived_record"]
	if !ok {
		t.Fatal("kg_upsert_derived_record schema missing")
	}
	for _, p := range []string{"title", "subtype", "source_system", "record_ref"} {
		if _, ok := s.Properties[p]; !ok {
			t.Errorf("kg_upsert_derived_record must accept %q", p)
		}
	}
}
```

- [ ] **Step 2: Run it — verify it fails**

Run: `go test ./internal/bridge/ -run 'TestSchema_HasUpsertDerivedRecord|TestAllToolSchemasRegistered' -v`
Expected: FAIL — schema missing + count 40≠41.

- [ ] **Step 3: Add the route + schema**

In `internal/bridge/client.go` `toolRoutes` (write-class, POST, project path param):

```go
	"kg_upsert_derived_record": {
		Method:       http.MethodPost,
		PathTemplate: apiPrefix + "/projects/{projectId}/derived-records",
		PathParams:   []string{"projectId"},
		Class:        RouteWrite,
	},
```

In `internal/bridge/schema.go` (mirror an existing write schema, e.g. `kg_store_decision`):

```go
	// === kg_upsert_derived_record (IMP-010 — routed write tool) ===
	schemas["kg_upsert_derived_record"] = &ToolSchema{
		ToolName:    "kg_upsert_derived_record",
		Description: "Upsert a satellite-computed record (e.g. AAA Master Record) as a derived_record node. Idempotent by (source_system, record_ref). Returns node_id; attach provenance with kg_link.",
		Properties: map[string]ParamSchema{
			"title":         {Type: TypeString, Required: true, Description: "Record title"},
			"subtype":       {Type: TypeString, Required: true, Description: "Record kind, e.g. master_record"},
			"source_system": {Type: TypeString, Required: true, Description: "Producing system, e.g. aaa"},
			"record_ref":    {Type: TypeString, Required: true, Description: "External id (idempotency key), e.g. AAA EntityProfile.id"},
			"summary":       {Type: TypeString, Required: false, Description: "Short summary; full content stays in the source system"},
			"project_id":    {Type: TypeString, Required: false, Description: "Optional project id (falls back to the default project)"},
		},
	}
```

> Confirm the route maps `project_id` → the `{projectId}` path param via the bridge's default-project injection (same as the IMP-009 upload routes); the tool exposes `project_id` (snake), the path uses `projectId`.

- [ ] **Step 4: Run it — verify it passes**

Run: `go test ./internal/bridge/ -run 'TestSchema_HasUpsertDerivedRecord|TestAllToolSchemasRegistered|TestAllToolSchemasMatchRoutes' -v`
Expected: PASS — count 41, invariant `len(schemas)==len(ListToolNames)+len(localToolNames)` holds (this tool is routed → +1 schema +1 routed name).

- [ ] **Step 5: Commit**

```bash
git add internal/bridge/client.go internal/bridge/schema.go internal/bridge/schema_test.go
git commit -m "feat(bridge): add kg_upsert_derived_record routed write tool"
```

---

## Task 6: Full verification + reverse-usage smoke

**Files:**
- Test: full suite + a DB-backed integration check

- [ ] **Step 1: Run the affected suites**

Run: `go test ./internal/config/... ./internal/filter/... ./internal/validation/... ./internal/store/... ./internal/handler/... ./internal/bridge/... -count=1`
Expected: PASS.

- [ ] **Step 2: Lint + vet + build**

Run: `make lint && go vet ./... && go build ./...`
Expected: clean.

- [ ] **Step 3: Reverse-usage integration smoke (the feature's intent — FR-5)**

With dockerized deps + a migrated DB + a running server, exercise the loop end-to-end:
1. `kg_upsert_derived_record(title, subtype="master_record", source_system="aaa", record_ref="ep-1")` → capture `node_id` (the `derived_record`).
2. Seed/locate a `document_chunk` UUID. `kg_link(source=node_id, relationship=evidence, target=<chunk>)` → 200; re-run → 409 (idempotent).
3. `kg_link(source=node_id, relationship=derived_from, target=<project node>)` → 200.
4. `kg_get_neighbors(<chunk>, direction=inbound)` → returns the `derived_record`, attributed by `properties.source_system="aaa"` / `subtype="master_record"` (the PO's "which MC used this doc").
5. `kg_get_neighbors(<chunk>, direction=inbound, node_types=["derived_record"])` → 200 (allowlist accepts the filter), not 400.

Document the commands + observed output in the PR (verification-before-completion).

- [ ] **Step 4: Final commit (if any test fixtures were added)**

```bash
git add -A && git commit -m "test(kg): verify derived_record reverse-usage loop (FR-5)"
```

---

## Self-Review notes (author)

- **Spec coverage:** FR-1 node type (Task 1), FR-2 upsert tool+endpoint (Tasks 3–5), FR-3 edge whitelist (Task 2), FR-4 confirm+idempotency (Task 4 race-safe upsert + Task 5 RouteWrite; `kg_link` 409 is existing), FR-5 reverse-usage (Task 1 neighbors allowlist + Task 6 smoke). §4 gate checklist fully in Task 1. Count correction (40→41) in Task 5.
- **Known mirror-points** (engineer reads the referenced file to copy exact locals): `GetNode` SELECT columns + scan (`node.go:334`) for Task 3; `StoreNodeRequest`/`UpdateNodeRequest` full fields (`node.go:66`, `update.go:24`) for Task 4; the store/handler test harness (`newTestDB`, `seed*`, `node_test.go` mock setup). These are existing patterns, not new design.
- **Dependency order:** Task 1 (types + ValidNodeTypes) must precede Task 2 (edge rules reference the node type) and Task 4/5. Tasks within run sequentially.
- **Residual (carry to PR):** OQ-3 (CTO sign-off on the R2 name divergence); the broader 3-allowlist consolidation is out of scope (only `neighbors.go` touched).
