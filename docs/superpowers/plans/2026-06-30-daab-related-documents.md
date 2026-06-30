# DAAB Related Documents / Shared Entities (Step 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose document-level relatedness via shared canonical entities (IDF-ranked, blob-resistant, raw/no-LLM) as REST + an MCP tool, reusing the existing graph.

**Architecture:** Two pure-SQL, project-scoped store methods on `GraphRetrieveStore` (document-grained IDF over `document→concept` mentions); a thin REST handler with a mandatory path-project access check; an MCP tool `kg_related_documents`. No migration (read-only), no service pipeline, no LLM.

**Tech Stack:** Go (`ennam.kg.go`, `database/sql`, `lib/pq`). Tests: `go test` (`-tags=integration` for DB) + bridge unit tests.

**Design spec:** `docs/superpowers/specs/2026-06-30-daab-related-documents-design.md`

## Global Constraints

- Run from `ennam.kg.go`. Integration tests: store reads `KG_TEST_DATABASE_URL`, handler reads `KG_TEST_DSN`; dev DB is **:5433** — export BOTH to `postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable`.
- Run with `-race`; `gofmt`/`goimports` after edits. **No migration** (read-only over existing graph).
- **IDF universe = `mentions` edges with source `node_type='document'`** (NOT the unscoped `SharedEntityNeighbors` universe). `N`=distinct documents in project, `df`=distinct documents mentioning the concept, `weight=ln(N/df)`. Only non-superseded concepts (`properties->>'merged_into' = ''`).
- **Ranking = max-IDF per doc-pair** (tiebreak shared_count, then doc id) — blob-resistant (empirically validated).
- **Security:** the path `{projectId}` is NOT checked by middleware (`mem:be-path-project-access-gap`); the handler MUST call `requireProjectAccess(w, r, h.roleResolver, projectID)`.
- Output is raw + provenance (canonical entity IDs + names + IDF); NO LLM.
- Bridge counts (current): routes **42**, schemas **45**, `RouteRead` **19**. Adding a read tool → 43 / 46 / 20.

---

## Task 1: Store methods — `SharedDocumentEntities` + `RelatedDocuments`

**Files:**
- Modify: `internal/store/graph_retrieve.go`
- Test: `internal/store/related_documents_test.go` (create, integration)

**Interfaces:**
- Produces:
  - `type SharedEntity struct { EntityID, Name string; IDF float64 }`
  - `type RelatedDoc struct { RelatedDocumentID, TopSharedEntity, TopSharedEntityID string; MaxIDF float64; SharedCount int }`
  - `(*GraphRetrieveStore).SharedDocumentEntities(ctx, projectID, docA, docB string) ([]SharedEntity, error)` — shared canonical entities of two docs, rarest IDF first.
  - `(*GraphRetrieveStore).RelatedDocuments(ctx, projectID, docID string, limit int) ([]RelatedDoc, error)` — docs sharing ≥1 canonical entity, ranked by max-IDF.

- [ ] **Step 1: Write the failing integration test**

Create `internal/store/related_documents_test.go`:
```go
//go:build integration

package store_test

import (
	"context"
	"database/sql"
	"testing"

	"github.com/ennam/ennam-kg/internal/store"
)

const rdProj = "eeeeeeee-0000-0000-0000-000000000001"

// rdSeed builds a tiny graph: 3 documents, 3 concepts (1 specific/rare, 1 ubiquitous),
// with document→concept 'mentions' edges, in project rdProj. Returns the store.
func rdSeed(t *testing.T, db *sql.DB) *store.GraphRetrieveStore {
	t.Helper()
	ctx := context.Background()
	ex := func(q string, args ...interface{}) {
		if _, err := db.ExecContext(ctx, q, args...); err != nil {
			t.Fatalf("seed: %v\n%s", err, q)
		}
	}
	db.ExecContext(ctx, `DELETE FROM knowledge_edges WHERE project_id=$1`, rdProj)  //nolint:errcheck
	db.ExecContext(ctx, `DELETE FROM knowledge_nodes WHERE project_id=$1`, rdProj)  //nolint:errcheck
	db.ExecContext(ctx, `DELETE FROM projects WHERE id=$1`, rdProj)                 //nolint:errcheck
	ex(`INSERT INTO projects (id,name) VALUES ($1,'rd-test')`, rdProj)
	t.Cleanup(func() {
		db.ExecContext(ctx, `DELETE FROM knowledge_edges WHERE project_id=$1`, rdProj) //nolint:errcheck
		db.ExecContext(ctx, `DELETE FROM knowledge_nodes WHERE project_id=$1`, rdProj) //nolint:errcheck
		db.ExecContext(ctx, `DELETE FROM projects WHERE id=$1`, rdProj)                //nolint:errcheck
	})
	node := func(id, typ, title string) {
		// created_by is NOT NULL (no default) on knowledge_nodes.
		ex(`INSERT INTO knowledge_nodes (id, project_id, node_type, title, properties, status, created_by)
		    VALUES ($1,$2,$3,$4,'{}'::jsonb,'active','test')`, id, rdProj, typ, title)
	}
	const dA, dB, dC = "eeee0001-0000-0000-0000-000000000001", "eeee0002-0000-0000-0000-000000000002", "eeee0003-0000-0000-0000-000000000003"
	const cSpecific, cUbiq = "eeeeccc1-0000-0000-0000-000000000001", "eeeeccc2-0000-0000-0000-000000000002"
	node(dA, "document", "Doc A")
	node(dB, "document", "Doc B")
	node(dC, "document", "Doc C")
	node(cSpecific, "concept", "Công ty Hàm Giang") // rare: A,B only
	node(cUbiq, "concept", "Tỉnh Trà Vinh")          // ubiquitous: A,B,C
	mention := func(doc, concept string) {
		// created_by is NOT NULL (no default) on knowledge_edges.
		ex(`INSERT INTO knowledge_edges (id, project_id, source_id, target_id, edge_type, created_by)
		    VALUES (uuid_generate_v4(),$1,$2,$3,'mentions','test')`, rdProj, doc, concept)
	}
	mention(dA, cSpecific); mention(dB, cSpecific)              // specific shared by A,B (df=2)
	mention(dA, cUbiq); mention(dB, cUbiq); mention(dC, cUbiq)  // ubiquitous in A,B,C (df=3)
	return store.NewGraphRetrieveStore(db)
}

func TestSharedDocumentEntities(t *testing.T) {
	db := setupTestDB(t)
	s := rdSeed(t, db)
	const dA, dB = "eeee0001-0000-0000-0000-000000000001", "eeee0002-0000-0000-0000-000000000002"
	got, err := s.SharedDocumentEntities(context.Background(), rdProj, dA, dB)
	if err != nil {
		t.Fatalf("shared: %v", err)
	}
	if len(got) != 2 {
		t.Fatalf("want 2 shared entities, got %d: %+v", len(got), got)
	}
	// rarest first: "Công ty Hàm Giang" (df=2) before "Tỉnh Trà Vinh" (df=3)
	if got[0].Name != "Công ty Hàm Giang" || got[0].IDF <= got[1].IDF {
		t.Errorf("expected specific entity first with higher IDF, got %+v", got)
	}
}

func TestRelatedDocuments_BlobResistant(t *testing.T) {
	db := setupTestDB(t)
	s := rdSeed(t, db)
	const dA, dB, dC = "eeee0001-0000-0000-0000-000000000001", "eeee0002-0000-0000-0000-000000000002", "eeee0003-0000-0000-0000-000000000003"
	got, err := s.RelatedDocuments(context.Background(), rdProj, dA, 10)
	if err != nil {
		t.Fatalf("related: %v", err)
	}
	// A relates to B (shares specific + ubiquitous → max-IDF = specific) and C (shares only ubiquitous).
	if len(got) != 2 {
		t.Fatalf("want 2 related docs, got %d: %+v", len(got), got)
	}
	if got[0].RelatedDocumentID != dB {
		t.Errorf("B (specific shared entity) must rank first, got %+v", got)
	}
	if got[0].TopSharedEntity != "Công ty Hàm Giang" {
		t.Errorf("top shared entity must be the specific one, got %q", got[0].TopSharedEntity)
	}
	if got[0].MaxIDF <= got[1].MaxIDF {
		t.Errorf("B's max-IDF (specific) must exceed C's (ubiquitous): %+v", got)
	}
}
```

- [ ] **Step 2: Run → fail**

Run: `export KG_TEST_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable"; go test -tags=integration ./internal/store/ -run 'TestSharedDocumentEntities|TestRelatedDocuments' -v`
Expected: FAIL (undefined).

- [ ] **Step 3: Implement the methods**

In `internal/store/graph_retrieve.go` (ensure `"github.com/lib/pq"` is imported — it is), add:
```go
// SharedEntity is one canonical entity two documents both mention.
type SharedEntity struct {
	EntityID string  `json:"entity_id"`
	Name     string  `json:"name"`
	IDF      float64 `json:"idf"`
}

// RelatedDoc is one document related to a seed document by shared canonical entities.
type RelatedDoc struct {
	RelatedDocumentID string  `json:"related_document_id"`
	MaxIDF            float64 `json:"max_idf"`
	SharedCount       int     `json:"shared_count"`
	TopSharedEntity   string  `json:"top_shared_entity"`
	TopSharedEntityID string  `json:"top_shared_entity_id"`
}

// docMentionsIDF is the shared CTE: document→non-superseded-concept mentions, with
// document-grained IDF (N=distinct docs, df=distinct docs per concept). $1=projectID.
const docMentionsIDF = `
	WITH dm AS (
		SELECT e.source_id AS doc, e.target_id AS concept
		FROM knowledge_edges e
		JOIN knowledge_nodes sn ON sn.id = e.source_id AND sn.node_type = 'document' AND sn.status = 'active'
		JOIN knowledge_nodes cn ON cn.id = e.target_id AND cn.node_type = 'concept' AND cn.status = 'active'
		                        AND COALESCE(cn.properties->>'merged_into','') = ''
		WHERE e.edge_type = 'mentions' AND e.project_id = $1),
	nn AS (SELECT GREATEST(count(DISTINCT id),1)::float8 AS n FROM knowledge_nodes
	       WHERE node_type='document' AND status='active' AND project_id = $1),
	idf AS (SELECT concept, ln((SELECT n FROM nn) / count(DISTINCT doc)) AS idf FROM dm GROUP BY concept)`

// SharedDocumentEntities returns the canonical entities both documents mention,
// rarest (highest IDF) first. Empty = the documents share no entity.
func (s *GraphRetrieveStore) SharedDocumentEntities(ctx context.Context, projectID, docA, docB string) ([]SharedEntity, error) {
	q := docMentionsIDF + `
		SELECT a.concept AS entity_id, cn.title AS name, i.idf
		FROM dm a JOIN dm b ON a.concept = b.concept
		JOIN idf i ON i.concept = a.concept
		JOIN knowledge_nodes cn ON cn.id = a.concept
		WHERE a.doc = $2 AND b.doc = $3
		ORDER BY i.idf DESC, cn.title`
	rows, err := s.db.QueryContext(ctx, q, projectID, docA, docB)
	if err != nil {
		return nil, fmt.Errorf("shared document entities: %w", err)
	}
	defer rows.Close()
	var out []SharedEntity
	for rows.Next() {
		var e SharedEntity
		if err := rows.Scan(&e.EntityID, &e.Name, &e.IDF); err != nil {
			return nil, fmt.Errorf("scan shared entity: %w", err)
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

// RelatedDocuments returns documents sharing ≥1 canonical entity with docID,
// ranked by the rarest shared entity (max-IDF) — blob-resistant.
func (s *GraphRetrieveStore) RelatedDocuments(ctx context.Context, projectID, docID string, limit int) ([]RelatedDoc, error) {
	if limit <= 0 {
		limit = 10
	}
	q := docMentionsIDF + `
		SELECT b.doc AS related_document_id,
		       max(i.idf) AS max_idf,
		       count(*)   AS shared_count,
		       (array_agg(cn.title    ORDER BY i.idf DESC))[1] AS top_shared_entity,
		       (array_agg(a.concept::text ORDER BY i.idf DESC))[1] AS top_shared_entity_id
		FROM dm a JOIN dm b ON a.concept = b.concept AND a.doc <> b.doc
		JOIN idf i ON i.concept = a.concept
		JOIN knowledge_nodes cn ON cn.id = a.concept
		WHERE a.doc = $2
		GROUP BY b.doc
		ORDER BY max_idf DESC, shared_count DESC, b.doc
		LIMIT $3`
	rows, err := s.db.QueryContext(ctx, q, projectID, docID, limit)
	if err != nil {
		return nil, fmt.Errorf("related documents: %w", err)
	}
	defer rows.Close()
	var out []RelatedDoc
	for rows.Next() {
		var d RelatedDoc
		if err := rows.Scan(&d.RelatedDocumentID, &d.MaxIDF, &d.SharedCount, &d.TopSharedEntity, &d.TopSharedEntityID); err != nil {
			return nil, fmt.Errorf("scan related doc: %w", err)
		}
		out = append(out, d)
	}
	return out, rows.Err()
}
```

- [ ] **Step 4: Run → pass**

Run: `go test -tags=integration ./internal/store/ -run 'TestSharedDocumentEntities|TestRelatedDocuments' -v`
Expected: PASS (blob-resistance test proves the specific entity ranks B above C).

- [ ] **Step 5: Commit**

```bash
git add internal/store/graph_retrieve.go internal/store/related_documents_test.go
git commit -m "feat(daab): document-grained shared-entity retrieval (SharedDocumentEntities, RelatedDocuments)"
```

---

## Task 2: REST handler + path-project access check

**Files:**
- Create: `internal/handler/related_documents.go`
- Test: `internal/handler/related_documents_test.go`
- Modify: `cmd/kg-server/main.go` (construct, register, `SetRoleResolver`)

**Interfaces:**
- Consumes: `GraphRetrieveStore.SharedDocumentEntities`/`RelatedDocuments`, `requireProjectAccess` (`authz.go:35`), `ProjectRoleResolverFunc`.
- Produces:
  - `GET /api/v1/projects/{projectId}/documents/{documentId}/related?limit=` → `{results:[RelatedDoc]}`
  - `GET /api/v1/projects/{projectId}/documents/{documentId}/shared-entities?with_document_id={otherDocId}` → `{shared_entities:[SharedEntity]}`
  - constructor `NewRelatedDocumentsHandler(store relatedStore, logger)` + `SetRoleResolver(ProjectRoleResolverFunc)`.

- [ ] **Step 1: Write the failing unit test (fake store, fake resolver)**

Create `internal/handler/related_documents_test.go`:
```go
package handler

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"log/slog"

	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/store"
)

type fakeRelatedStore struct {
	related []store.RelatedDoc
	shared  []store.SharedEntity
}

func (f *fakeRelatedStore) RelatedDocuments(_ context.Context, _ string, _ string, _ int) ([]store.RelatedDoc, error) {
	return f.related, nil
}
func (f *fakeRelatedStore) SharedDocumentEntities(_ context.Context, _ string, _ string, _ string) ([]store.SharedEntity, error) {
	return f.shared, nil
}

func allowAll(_ context.Context, _ string, _ string) (models.ProjectMemberRole, bool) {
	return models.ProjectMemberRoleDeveloper, true
}
func denyAll(_ context.Context, _ string, _ string) (models.ProjectMemberRole, bool) {
	return "", false
}

func newRD(store relatedStore, resolver ProjectRoleResolverFunc) *RelatedDocumentsHandler {
	h := NewRelatedDocumentsHandler(store, slog.Default())
	h.SetRoleResolver(resolver)
	return h
}

func TestRelatedDocuments_Ranked(t *testing.T) {
	fs := &fakeRelatedStore{related: []store.RelatedDoc{{RelatedDocumentID: "d2", MaxIDF: 3.5, SharedCount: 2, TopSharedEntity: "Hàm Giang"}}}
	h := newRD(fs, allowAll)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/projects/p1/documents/d1/related?limit=5", nil)
	req.SetPathValue("projectId", "p1")
	req.SetPathValue("documentId", "d1")
	req = reqWithIdentityUser(req, "p1", "u1") // sets identity (see agent-context tests)
	w := httptest.NewRecorder()
	h.HandleRelated(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d: %s", w.Code, w.Body.String())
	}
	var resp struct{ Results []map[string]interface{} `json:"results"` }
	json.Unmarshal(w.Body.Bytes(), &resp)
	if len(resp.Results) != 1 {
		t.Errorf("expected 1 result, got %+v", resp)
	}
}

func TestRelatedDocuments_DeniesForeignProject(t *testing.T) {
	fs := &fakeRelatedStore{}
	h := newRD(fs, denyAll) // caller is not a member of the path project
	req := httptest.NewRequest(http.MethodGet, "/api/v1/projects/pX/documents/d1/related", nil)
	req.SetPathValue("projectId", "pX")
	req.SetPathValue("documentId", "d1")
	req = reqWithIdentityUser(req, "p1", "u1")
	w := httptest.NewRecorder()
	h.HandleRelated(w, req)
	if w.Code == http.StatusOK {
		t.Errorf("must deny access to a non-member project, got 200")
	}
}
```
(If `reqWithIdentityUser` doesn't exist yet in the handler test package, add it — mirror `reqWithIdentity` in `agent_context_test.go`, setting `UserID` — see the kg_search_sessions plan. If the codebase already added it for session search, reuse it.)

- [ ] **Step 2: Run → fail**

Run: `go test ./internal/handler/ -run TestRelatedDocuments -v` → FAIL (undefined).

- [ ] **Step 3: Implement the handler**

Create `internal/handler/related_documents.go`:
```go
package handler

import (
	"context"
	"log/slog"
	"net/http"
	"strconv"

	"github.com/ennam/ennam-kg/internal/store"
)

type relatedStore interface {
	RelatedDocuments(ctx context.Context, projectID, docID string, limit int) ([]store.RelatedDoc, error)
	SharedDocumentEntities(ctx context.Context, projectID, docA, docB string) ([]store.SharedEntity, error)
}

// RelatedDocumentsHandler serves document relatedness via shared canonical entities.
type RelatedDocumentsHandler struct {
	store        relatedStore
	roleResolver ProjectRoleResolverFunc
	logger       *slog.Logger
}

func NewRelatedDocumentsHandler(s relatedStore, logger *slog.Logger) *RelatedDocumentsHandler {
	return &RelatedDocumentsHandler{store: s, logger: logger}
}

// SetRoleResolver injects the project-role resolver (matches the other handlers).
func (h *RelatedDocumentsHandler) SetRoleResolver(r ProjectRoleResolverFunc) { h.roleResolver = r }

func (h *RelatedDocumentsHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/projects/{projectId}/documents/{documentId}/related", h.HandleRelated)
	mux.HandleFunc("GET /api/v1/projects/{projectId}/documents/{documentId}/shared-entities", h.HandleShared)
}

// HandleRelated returns documents related to {documentId} ranked by max-IDF shared entity.
func (h *RelatedDocumentsHandler) HandleRelated(w http.ResponseWriter, r *http.Request) {
	projectID := r.PathValue("projectId")
	docID := r.PathValue("documentId")
	if projectID == "" || docID == "" {
		errorResponse(w, http.StatusBadRequest, "projectId and documentId are required")
		return
	}
	// Close the path-project gap: middleware does NOT check the path project.
	if !requireProjectAccess(w, r, h.roleResolver, projectID) {
		return
	}
	limit := 10
	if v := r.URL.Query().Get("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			limit = n
		}
	}
	res, err := h.store.RelatedDocuments(r.Context(), projectID, docID, limit)
	if err != nil {
		h.logger.ErrorContext(r.Context(), "related documents failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "related documents query failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"results": res})
}

// HandleShared returns the canonical entities {documentId} and ?with={otherDocId} share.
func (h *RelatedDocumentsHandler) HandleShared(w http.ResponseWriter, r *http.Request) {
	projectID := r.PathValue("projectId")
	docID := r.PathValue("documentId")
	other := r.URL.Query().Get("with_document_id")
	if projectID == "" || docID == "" || other == "" {
		errorResponse(w, http.StatusBadRequest, "projectId, documentId and ?with_document_id are required")
		return
	}
	if !requireProjectAccess(w, r, h.roleResolver, projectID) {
		return
	}
	res, err := h.store.SharedDocumentEntities(r.Context(), projectID, docID, other)
	if err != nil {
		h.logger.ErrorContext(r.Context(), "shared entities failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "shared entities query failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"shared_entities": res})
}
```
(Confirm `requireProjectAccess(w, r, resolver, projectIDs...) bool` returns true on allow / writes the error + returns false on deny — `authz.go:35`. Confirm `ProjectRoleResolverFunc` signature `func(ctx, projectID, userID) (models.ProjectMemberRole, bool)`.)

- [ ] **Step 4: Run → pass; wire main.go**

Run: `go test ./internal/handler/ -run TestRelatedDocuments -v` → PASS.
In `cmd/kg-server/main.go`, after `roleResolver` is defined (~L669) and near the other handler registrations:
```go
	relatedDocsHandler := handler.NewRelatedDocumentsHandler(store.NewGraphRetrieveStore(db), logger)
	relatedDocsHandler.SetRoleResolver(roleResolver)
	relatedDocsHandler.RegisterRoutes(apiMux)
```

- [ ] **Step 5: Build + integration test (cross-project deny)**

Run:
```bash
go build ./...
export KG_TEST_DSN="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable"
go test -race ./internal/handler/ -run TestRelatedDocuments
```
Expected: PASS (incl. the foreign-project deny).

- [ ] **Step 6: Commit**

```bash
git add internal/handler/related_documents.go internal/handler/related_documents_test.go cmd/kg-server/main.go
git commit -m "feat(daab): related-documents REST handler with path-project access gate"
```

---

## Task 3: MCP tool `kg_related_documents`

**Files:**
- Modify: `internal/bridge/schema.go` (schema in `buildToolSchemas`)
- Modify: `internal/bridge/client.go` (route)
- Modify: `internal/bridge/client_test.go` (42→43; `RouteRead` 19→20; total)
- Modify: `internal/bridge/handler_test.go` (45→46)

**Interfaces:**
- Produces **TWO** RouteRead MCP tools (the bridge PathTemplate is fixed and cannot switch on an arg; verified `ToolRoute` has `QueryParams []string` and serve.go:346-351 auto-fills `projectId`/`project_id` from `cfg.DefaultProjectID`, and existing routes already use `/projects/{projectId}/...`):
  - `kg_related_documents` → `/projects/{projectId}/documents/{document_id}/related`, QueryParams `["limit"]`.
  - `kg_document_shared_entities` → `/projects/{projectId}/documents/{document_id}/shared-entities`, QueryParams `["with_document_id"]`.
  `{projectId}` is filled from the key/config; `{document_id}` from the tool arg.

- [ ] **Step 1: Baseline the counts**

Run: `go test ./internal/bridge/ -run 'TestListToolNames|TestRouteClassCounts|TestListTools' -v` (current: `client_test.go:216`=42, `handler_test.go:276`=45, `RouteRead`=19). Expected: PASS.

- [ ] **Step 2: Add the two schemas (mirror `kg_recall`/`kg_search_sessions`)**

In `internal/bridge/schema.go` `buildToolSchemas()`:
```go
	schemas["kg_related_documents"] = &ToolSchema{
		ToolName:    "kg_related_documents",
		Description: "Find documents related to a document by shared canonical entities, ranked by entity specificity (rare = stronger). Raw provenance (the driving shared entity per result), no summarization. Project resolved from the API key.",
		Properties: map[string]ParamSchema{
			"document_id": {Type: TypeString, Required: true, Description: "The document to find relations for", MinLength: intPtr(1)},
			"limit":       {Type: TypeInteger, Required: false, Description: "Max related documents (default 10)"},
		},
	}
	schemas["kg_document_shared_entities"] = &ToolSchema{
		ToolName:    "kg_document_shared_entities",
		Description: "Return the canonical entities that two documents both mention (rarest/most-specific first) — the literal answer to 'how are these two documents related?'. Raw, no summarization.",
		Properties: map[string]ParamSchema{
			"document_id":      {Type: TypeString, Required: true, Description: "First document", MinLength: intPtr(1)},
			"with_document_id": {Type: TypeString, Required: true, Description: "Second document", MinLength: intPtr(1)},
		},
	}
```

- [ ] **Step 3: Add the two routes**

In `internal/bridge/client.go` routes map (the `{projectId}` placeholder is auto-filled from `cfg.DefaultProjectID`, like the existing `/projects/{projectId}/...` routes):
```go
	"kg_related_documents": {
		Method:       http.MethodGet,
		PathTemplate: apiPrefix + "/projects/{projectId}/documents/{document_id}/related",
		Class:        RouteRead,
		QueryParams:  []string{"limit"},
	},
	"kg_document_shared_entities": {
		Method:       http.MethodGet,
		PathTemplate: apiPrefix + "/projects/{projectId}/documents/{document_id}/shared-entities",
		Class:        RouteRead,
		QueryParams:  []string{"with_document_id"},
	},
```

- [ ] **Step 4: Bump the count assertions (+2 tools)**

- `internal/bridge/client_test.go:216-217`: `42` → `44`.
- `internal/bridge/client_test.go` `TestRouteClassCounts` (~:1060): `RouteRead: 19` → `21`; total `42` → `44`.
- `internal/bridge/handler_test.go:276-277`: `45` → `47`.
- (Optional cosmetic) `buildToolSchemas` `make(map, 45)` hint → `47`.

- [ ] **Step 5: Run → pass**

Run: `go test -race ./internal/bridge/`
Expected: PASS. Invariant `schemas(46) == routes(43) + local(3)` holds.

- [ ] **Step 6: Commit**

```bash
git add internal/bridge/schema.go internal/bridge/client.go internal/bridge/client_test.go internal/bridge/handler_test.go
git commit -m "feat(daab): expose kg_related_documents + kg_document_shared_entities MCP tools"
```

---

## Task 4: Full verification + ranked-mode quality gate

**Files:** none (verification).

- [ ] **Step 1: Build, vet, unit**

Run: `go build ./... && go vet ./internal/store/... ./internal/handler/... ./internal/bridge/... && go test -race ./internal/store/ ./internal/handler/ ./internal/bridge/`
Expected: build/vet OK; unit packages PASS.

- [ ] **Step 2: Integration (both DSN vars → :5433)**

Run:
```bash
export KG_TEST_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable"
export KG_TEST_DSN="$KG_TEST_DATABASE_URL"
go test -tags=integration ./internal/store/ -run 'TestSharedDocumentEntities|TestRelatedDocuments'
go test -tags=integration ./internal/handler/ -run TestRelatedDocuments
```
Expected: PASS.

- [ ] **Step 3: Falsifiable quality gate for the RANKED mode (spec §8)**

On the real corpus (`592c7ff7…`), run `RelatedDocuments` for ~10 seed documents (via the endpoint or a SQL harness using the same query). For the top related pair of each, inspect `top_shared_entity`. **Pass = ≥80% of seeds have a *specific* connector (NOT "Tỉnh Trà Vinh"/"UBND tỉnh Trà Vinh"/"Ban Quản lý…"/province-blob).** Record the result. If it fails (blob dominates), do NOT bless the ranked mode as a default — note it and revisit ranking; the **pairwise mode ships regardless** (deterministic raw evidence). (The §4 spot-check already passed; this formalizes it.)

- [ ] **Step 4: Smoke test the MCP tool**

`docker compose up -d --build kg-server`; call `kg_related_documents` (or the REST endpoint) with a user-bound key for a known document; confirm a `results` array with a `top_shared_entity`, and that a foreign-project path is denied.

- [ ] **Step 5: Checkpoint + backlog**

Serena checkpoint; mark Step 2 done; note the deferred follow-ups (fuzzy alias merge; ranked-mode consumer = AAA; min-IDF floor if calibration shows pollution; materialized per-project IDF at scale).

---

## Self-Review notes (author)

- **Spec coverage:** store methods §6 → T1; handler + RBAC §7/§9 → T2; MCP §7 → T3; quality gate §8 → T4 Step 3; no migration (read-only) — confirmed. Ranking (max-IDF, document-grained) §6.2/D4 → T1 (validated by `TestRelatedDocuments_BlobResistant`).
- **Type consistency:** `SharedEntity{EntityID,Name,IDF}` / `RelatedDoc{RelatedDocumentID,MaxIDF,SharedCount,TopSharedEntity,TopSharedEntityID}` used identically in T1 (store) and T2 (handler fake + view). SQL column order matches the `Scan` order.
- **Security:** T2 mandates `requireProjectAccess` on the path project (closes `mem:be-path-project-access-gap`); `TestRelatedDocuments_DeniesForeignProject` regresses it.
- **Bridge counts (TWO tools):** routes 42→44, schemas 45→47, `RouteRead` 19→21 — pinned from `client_test.go:216`/`handler_test.go:276`/`TestRouteClassCounts`. Two tools because the bridge PathTemplate is fixed (can't switch `/related`↔`/shared-entities` on an arg); verified `ToolRoute.QueryParams` exists and serve.go:346-351 auto-fills `{projectId}` from `cfg.DefaultProjectID`, matching the existing `/projects/{projectId}/...` routes.
- **Verified:** `requireProjectAccess(w,r,resolver,projectIDs...) bool` (authz.go:35) writes 403 + returns false on deny, returns true on `identity==nil` (dev); `ProjectRoleResolverFunc(ctx,projectID,userID)→(models.ProjectMemberRole,bool)`; bridge path/query substitution (client.go:563 `{param}` replace + QueryParams).
- **Verified (corrected here):** `created_by` is NOT NULL (no default) on `knowledge_nodes` AND `knowledge_edges` → the T1 seed sets it; superseded concepts carry `status='superseded'` (1266) while active carry `status='active'` (1929) → the IDF CTE filters `status='active'` on both document and concept (plus `merged_into=''` belt-and-suspenders) — matches `SharedEntityNeighbors`'s convention and the empirical validation; `reqWithIdentityUser` already exists (`session_search_test.go:194`, same `handler` package) → T2 reuses it.
