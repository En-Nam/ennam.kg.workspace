# BA-032a Document Navigation (Outline + Neighbors) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add read-only document-navigation surfaces — an edge-derived outline and a section neighborhood — exposed over HTTP and as two MCP tools, all keyed by real `document_section` UUIDs.

**Architecture:** Stateless reads derived on each request from the live `knowledge_nodes` + `knowledge_edges` (`contains_section` edges). No new table, no migration, no stored snapshot. The outline is one recursive CTE seeded at the hub; section-neighbors is a small set of single-hop edge queries. Two thin HTTP-proxy MCP tools wrap the endpoints.

**Tech Stack:** Go (stdlib `net/http`, `database/sql`, `log/slog`), PostgreSQL 16, MCP bridge (`internal/bridge`). One Python edit in `ennam.kg.python` (decompose pipeline).

**Source spec:** `docs/superpowers/specs/2026-06-18-document-navigation-cross-source-links-design.md` (BA-032a slice). FR-003 backlinks (BA-032b) are **out of scope** — they depend on BA-031 edges and get their own plan.

## Global Constraints

- **No new migration, no new table.** Reads only existing nodes/edges.
- **No `status` predicate** on any query — match the existing `GetChunksByDocument` convention (node.go:296). Re-decompose hard-deletes stale rows (`DeleteDocumentSubtree`, node.go:210), so there is nothing to filter.
- **Real UUIDs only.** No synthetic `sec-NNNN` value may appear in any response (NFR-271). No `summary`/`content`/body text in any list entry (NFR-273).
- **IDOR order = `GetDocumentMeta` exactly** (document.go:107-124): id-missing→400, not-found→404, `HasProjectAccess(node.ProjectID)` fail→404, wrong-type→400. Return **404 not 403** on cross-tenant.
- **Edge type is literally `contains_section`** (config.yaml:903-912); `document_chunk` excluded from the outline tree (BR-NAV-06), included only as FR-002 children.
- **Half-open line ranges** — `line_start`/`line_end`/`level`/`ordinal` are read from JSONB `properties` via `(properties->>'key')::int` and passed through verbatim; never "corrected."
- **Soft cap** `MAX_OUTLINE_SECTIONS = 2000` as a SQL `LIMIT`; `truncated:true` when the cap is hit.
- Go style: `fmt.Errorf("context: %w", err)`, `log/slog`, table-driven tests, `go test -race`.

---

## File Structure

| File | Responsibility |
|---|---|
| `internal/store/document_nav.go` (create) | `OutlineByHub` (recursive CTE) + `SectionNeighbors` (single-hop queries). Pure SQL. |
| `internal/store/document_nav_test.go` (create) | Integration tests against a live DB (build tag matches existing store tests). |
| `internal/handler/document_nav.go` (create) | `DocumentNavHandler`: `/outline` + `/section-neighbors`, IDOR, tree assembly, caps. |
| `internal/handler/document_nav_test.go` (create) | Handler tests (IDOR order, type guards, payload discipline, no `sec-` value). |
| `cmd/kg-server/main.go` (modify) | Construct + register `DocumentNavHandler` at the composition root. |
| `internal/bridge/schema.go` (modify) | Add `kg_get_document_outline` + `kg_get_section_neighbors` schemas; bump count comment. |
| `internal/bridge/client.go` (modify) | Add two `RouteRead` GET routes to the route map. |
| `internal/bridge/schema_test.go` (modify) | Count assertion 35 → 37. |
| `internal/bridge/client_test.go` (modify) | `RouteRead` 12 → 14, total 33 → 35. |
| `../ennam.kg.python/src/ennam_kg/ingestion/pipeline/decompose.py` (modify) | Stop writing `document_tree` (OQ-1 trigger). |

---

## Task 1: Outline store method (recursive CTE)

**Files:**
- Create: `ennam.kg.go/internal/store/document_nav.go`
- Test: `ennam.kg.go/internal/store/document_nav_test.go`

**Interfaces:**
- Consumes: `*sql.DB` (the `NodeStore` already holds `s.db`; this file adds methods to a new `DocumentNavStore` constructed the same way). Tests reuse the package's existing `store_test` helpers: `setupTestDB(t)` (skips unless `KG_TEST_DATABASE_URL` is set), `seedNodeReturning(ctx, db, projectID, nodeType, title, props []byte) (string, error)`, `seedEdge(ctx, db, projectID, sourceID, targetID, edgeType string) error` (all in `node_subtree_test.go`).
- Produces:
  - `type OutlineRow struct { ID, Title, ParentID string; LineStart, LineEnd, Level *int; ChunkCount int }`
  - `func NewDocumentNavStore(db *sql.DB) *DocumentNavStore`
  - `func (s *DocumentNavStore) OutlineByHub(ctx context.Context, hubID, projectID string, limit int) ([]OutlineRow, error)` — flat rows in arbitrary order; `ParentID == hubID` marks a top-level section; caller assembles the tree.

> **Test pattern (match the package exactly):** store tests are in `package store_test`, have **no** build tag, and skip at runtime when `KG_TEST_DATABASE_URL` is unset (see `favorite_test.go:17`, `node_subtree_test.go`). Do **not** use `//go:build integration`. Reuse `setupTestDB`/`seedNodeReturning`/`seedEdge` (already defined in the package — do not redefine them). Seed a unique project + FK-safe `t.Cleanup` exactly as `node_subtree_test.go:25-54` does; the helper `seedNavProject` below wraps that.

- [ ] **Step 1: Write the failing test**

Create `document_nav_test.go` in `package store_test`:

```go
package store_test

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"time"

	_ "github.com/lib/pq"
	"github.com/ennam/ennam-kg/internal/store"
)

// seedNavProject creates a unique project with FK-safe cleanup, mirroring
// node_subtree_test.go:25-54. Unique name avoids collision with leftover rows.
func seedNavProject(t *testing.T, db *sql.DB) (context.Context, string) {
	t.Helper()
	ctx := context.Background()
	name := fmt.Sprintf("test-nav-%d", time.Now().UnixNano())
	var projectID string
	if err := db.QueryRowContext(ctx,
		`INSERT INTO projects (name, description) VALUES ($1, 'nav integration test') RETURNING id`,
		name,
	).Scan(&projectID); err != nil {
		t.Fatalf("seed project: %v", err)
	}
	t.Cleanup(func() {
		c := context.Background()
		_, _ = db.ExecContext(c, `DELETE FROM knowledge_edges WHERE project_id = $1`, projectID)
		_, _ = db.ExecContext(c, `DELETE FROM knowledge_node_versions WHERE project_id = $1`, projectID)
		_, _ = db.ExecContext(c, `DELETE FROM knowledge_nodes WHERE project_id = $1`, projectID)
		_, _ = db.ExecContext(c, `DELETE FROM projects WHERE id = $1`, projectID)
	})
	return ctx, projectID
}

func mustSeedNode(t *testing.T, ctx context.Context, db *sql.DB, proj, nodeType, title, propsJSON string) string {
	t.Helper()
	id, err := seedNodeReturning(ctx, db, proj, nodeType, title, json.RawMessage(propsJSON))
	if err != nil {
		t.Fatalf("seed %s %q: %v", nodeType, title, err)
	}
	return id
}

func TestOutlineByHub_ReturnsRealSectionsWithParentAndChunkCount(t *testing.T) {
	db := setupTestDB(t)
	ctx, proj := seedNavProject(t, db)

	hub := mustSeedNode(t, ctx, db, proj, "document", "Doc", `{}`)
	secA := mustSeedNode(t, ctx, db, proj, "document_section", "A", `{"line_start":1,"line_end":10,"level":1}`)
	secB := mustSeedNode(t, ctx, db, proj, "document_section", "B", `{"line_start":10,"line_end":20,"level":1}`)
	subD := mustSeedNode(t, ctx, db, proj, "document_section", "D", `{"line_start":11,"line_end":15,"level":2}`)
	chunk := mustSeedNode(t, ctx, db, proj, "document_chunk", "c0", `{"ordinal":0}`)
	for _, e := range [][2]string{{hub, secA}, {hub, secB}, {secB, subD}, {secB, chunk}} {
		if err := seedEdge(ctx, db, proj, e[0], e[1], "contains_section"); err != nil {
			t.Fatalf("seed edge %s->%s: %v", e[0], e[1], err)
		}
	}

	rows, err := store.NewDocumentNavStore(db).OutlineByHub(ctx, hub, proj, 2000)
	if err != nil {
		t.Fatalf("OutlineByHub: %v", err)
	}
	if len(rows) != 3 {
		t.Fatalf("want 3 section rows (A,B,D), got %d", len(rows))
	}
	byID := map[string]store.OutlineRow{}
	for _, r := range rows {
		byID[r.ID] = r
	}
	if byID[secA].ParentID != hub || byID[subD].ParentID != secB {
		t.Errorf("parent linkage wrong: A.parent=%s D.parent=%s", byID[secA].ParentID, byID[subD].ParentID)
	}
	if byID[secB].ChunkCount != 1 {
		t.Errorf("B.chunk_count want 1, got %d", byID[secB].ChunkCount)
	}
	if _, ok := byID[chunk]; ok {
		t.Errorf("document_chunk must not appear as an outline row")
	}
}
```

> Add `"database/sql"` to the import block (used by the helper signatures). If `seedNodeReturning`'s param is already `[]byte`, `json.RawMessage` satisfies it; otherwise pass `[]byte(propsJSON)`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && KG_TEST_DATABASE_URL="$KG_TEST_DATABASE_URL" go test ./internal/store/ -run TestOutlineByHub -v`
Expected: FAIL — `store.NewDocumentNavStore` / `OutlineByHub` undefined (compile error). (If `KG_TEST_DATABASE_URL` is unset the test SKIPs — set it to your test DB per `make db-up` first.)

- [ ] **Step 3: Write minimal implementation**

```go
package store

import (
	"context"
	"database/sql"
	"fmt"
)

// DocumentNavStore derives document navigation (outline, section neighborhood)
// from live contains_section edges. It stores nothing; every call reads the
// current graph (BA-032a).
type DocumentNavStore struct {
	db *sql.DB
}

// NewDocumentNavStore constructs a DocumentNavStore.
func NewDocumentNavStore(db *sql.DB) *DocumentNavStore {
	return &DocumentNavStore{db: db}
}

// OutlineRow is one document_section in the flat outline result. ParentID equals
// the hub id for a top-level section, or the parent section id when nested.
// LineStart/LineEnd/Level are nil when the stored property is absent (legacy).
type OutlineRow struct {
	ID         string
	Title      string
	ParentID   string
	LineStart  *int
	LineEnd    *int
	Level      *int
	ChunkCount int
}

// OutlineByHub returns the document_section subtree under hubID as flat rows
// (caller assembles the tree from ParentID). Hierarchy is edge-authoritative:
// it follows contains_section edges only, excludes document_chunk from the tree
// (BR-NAV-06), counts chunk children per section (chunk_count), bounds depth via
// a path-array cycle guard, and caps rows at limit. No status predicate (D2).
func (s *DocumentNavStore) OutlineByHub(ctx context.Context, hubID, projectID string, limit int) ([]OutlineRow, error) {
	if s.db == nil {
		return nil, fmt.Errorf("OutlineByHub: nil database")
	}
	const q = `
WITH RECURSIVE outline AS (
    SELECT n.id, n.title, n.properties,
           $1::text AS parent_id,
           ARRAY[n.id::text] AS path
    FROM knowledge_edges e
    JOIN knowledge_nodes n
      ON n.id = e.target_id AND n.project_id = $2
    WHERE e.source_id = $1 AND e.project_id = $2
      AND e.edge_type = 'contains_section'
      AND n.node_type = 'document_section'
  UNION ALL
    SELECT n.id, n.title, n.properties,
           o.id::text AS parent_id,
           o.path || n.id::text
    FROM outline o
    JOIN knowledge_edges e
      ON e.source_id = o.id AND e.project_id = $2
     AND e.edge_type = 'contains_section'
    JOIN knowledge_nodes n
      ON n.id = e.target_id AND n.project_id = $2
     AND n.node_type = 'document_section'
    WHERE NOT (n.id::text = ANY(o.path))
)
SELECT o.id, o.title, o.parent_id,
       (o.properties->>'line_start')::int,
       (o.properties->>'line_end')::int,
       (o.properties->>'level')::int,
       COALESCE((
         SELECT COUNT(*)
         FROM knowledge_edges ce
         JOIN knowledge_nodes cn
           ON cn.id = ce.target_id AND cn.project_id = $2
         WHERE ce.source_id = o.id AND ce.project_id = $2
           AND ce.edge_type = 'contains_section'
           AND cn.node_type = 'document_chunk'
       ), 0) AS chunk_count
FROM outline o
LIMIT $3`
	rows, err := s.db.QueryContext(ctx, q, hubID, projectID, limit)
	if err != nil {
		return nil, fmt.Errorf("OutlineByHub query: %w", err)
	}
	defer rows.Close()

	var out []OutlineRow
	for rows.Next() {
		var r OutlineRow
		if err := rows.Scan(&r.ID, &r.Title, &r.ParentID, &r.LineStart, &r.LineEnd, &r.Level, &r.ChunkCount); err != nil {
			return nil, fmt.Errorf("OutlineByHub scan: %w", err)
		}
		out = append(out, r)
	}
	return out, rows.Err()
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestOutlineByHub -v` (with `KG_TEST_DATABASE_URL` set)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/store/document_nav.go internal/store/document_nav_test.go
git commit -m "feat(nav): outline store method (recursive contains_section CTE)"
```

---

## Task 2: Section-neighbors store method

**Files:**
- Modify: `ennam.kg.go/internal/store/document_nav.go`
- Modify: `ennam.kg.go/internal/store/document_nav_test.go`

**Interfaces:**
- Consumes: `OutlineRow` types from Task 1; the same `DocumentNavStore`.
- Produces:
  - `type NavNode struct { ID, Title, NodeType string; LineStart, LineEnd, Level, Ordinal *int }`
  - `type SectionNeighborhood struct { Parent *NavNode; Subsections, Chunks, Siblings []NavNode }`
  - `func (s *DocumentNavStore) SectionNeighbors(ctx context.Context, sectionID, projectID string) (*SectionNeighborhood, error)` — returns `nil` neighborhood with no error only if the section has no rows; the handler decides 400/404 from the node lookup, not from this method.

- [ ] **Step 1: Write the failing test** (append to `document_nav_test.go`, `package store_test`)

```go
func TestSectionNeighbors_ParentChildrenSiblings(t *testing.T) {
	db := setupTestDB(t)
	ctx, proj := seedNavProject(t, db)

	hub := mustSeedNode(t, ctx, db, proj, "document", "Doc", `{}`)
	secB := mustSeedNode(t, ctx, db, proj, "document_section", "B", `{"line_start":10,"line_end":20,"level":1}`)
	secE := mustSeedNode(t, ctx, db, proj, "document_section", "E", `{"line_start":20,"line_end":30,"level":1}`)
	subD := mustSeedNode(t, ctx, db, proj, "document_section", "D", `{"line_start":11,"line_end":15,"level":2}`)
	c0 := mustSeedNode(t, ctx, db, proj, "document_chunk", "c0", `{"ordinal":0}`)
	c1 := mustSeedNode(t, ctx, db, proj, "document_chunk", "c1", `{"ordinal":1}`)
	for _, e := range [][2]string{{hub, secB}, {hub, secE}, {secB, subD}, {secB, c0}, {secB, c1}} {
		if err := seedEdge(ctx, db, proj, e[0], e[1], "contains_section"); err != nil {
			t.Fatalf("seed edge %s->%s: %v", e[0], e[1], err)
		}
	}

	got, err := store.NewDocumentNavStore(db).SectionNeighbors(ctx, secB, proj)
	if err != nil {
		t.Fatalf("SectionNeighbors: %v", err)
	}
	if got.Parent == nil || got.Parent.ID != hub {
		t.Fatalf("parent want hub, got %+v", got.Parent)
	}
	if len(got.Subsections) != 1 || got.Subsections[0].ID != subD {
		t.Errorf("subsections want [D], got %+v", got.Subsections)
	}
	if len(got.Chunks) != 2 || got.Chunks[0].ID != c0 || got.Chunks[1].ID != c1 {
		t.Errorf("chunks want [c0,c1] by ordinal, got %+v", got.Chunks)
	}
	if len(got.Siblings) != 1 || got.Siblings[0].ID != secE {
		t.Errorf("siblings want [E] (B excluded), got %+v", got.Siblings)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestSectionNeighbors -v` (with `KG_TEST_DATABASE_URL` set)
Expected: FAIL — `SectionNeighbors`/`NavNode`/`SectionNeighborhood` undefined.

- [ ] **Step 3: Write minimal implementation** (append to `document_nav.go`)

```go
// NavNode is a lightweight neighbor entry: identity + line range only (NFR-273).
type NavNode struct {
	ID        string
	Title     string
	NodeType  string
	LineStart *int
	LineEnd   *int
	Level     *int // sections only
	Ordinal   *int // chunks only
}

// SectionNeighborhood is the parent / ordered children / siblings of a section.
type SectionNeighborhood struct {
	Parent      *NavNode
	Subsections []NavNode
	Chunks      []NavNode
	Siblings    []NavNode
}

const navNodeCols = `n.id, n.title, n.node_type,
       (n.properties->>'line_start')::int,
       (n.properties->>'line_end')::int,
       (n.properties->>'level')::int,
       (n.properties->>'ordinal')::int`

func scanNavNodes(rows *sql.Rows) ([]NavNode, error) {
	var out []NavNode
	for rows.Next() {
		var n NavNode
		if err := rows.Scan(&n.ID, &n.Title, &n.NodeType, &n.LineStart, &n.LineEnd, &n.Level, &n.Ordinal); err != nil {
			return nil, fmt.Errorf("scan nav node: %w", err)
		}
		out = append(out, n)
	}
	return out, rows.Err()
}

// SectionNeighbors returns the parent (source of the incoming contains_section
// edge), ordered children (subsections by line_start, chunks by ordinal), and
// siblings (parent's other document_section children, current excluded). No
// status predicate (D2). Multi-parent anomalies tie-break to the lowest source id.
func (s *DocumentNavStore) SectionNeighbors(ctx context.Context, sectionID, projectID string) (*SectionNeighborhood, error) {
	if s.db == nil {
		return nil, fmt.Errorf("SectionNeighbors: nil database")
	}
	nh := &SectionNeighborhood{}

	// Parent: source of the single incoming contains_section edge.
	parentRow := s.db.QueryRowContext(ctx, `
SELECT `+navNodeCols+`
FROM knowledge_edges e
JOIN knowledge_nodes n ON n.id = e.source_id AND n.project_id = $2
WHERE e.target_id = $1 AND e.project_id = $2 AND e.edge_type = 'contains_section'
ORDER BY n.id
LIMIT 1`, sectionID, projectID)
	var p NavNode
	switch err := parentRow.Scan(&p.ID, &p.Title, &p.NodeType, &p.LineStart, &p.LineEnd, &p.Level, &p.Ordinal); err {
	case nil:
		nh.Parent = &p
	case sql.ErrNoRows:
		// orphan section: no parent edge — leave Parent nil
	default:
		return nil, fmt.Errorf("SectionNeighbors parent: %w", err)
	}

	// Children: outgoing contains_section, split by type, ordered.
	childRows, err := s.db.QueryContext(ctx, `
SELECT `+navNodeCols+`
FROM knowledge_edges e
JOIN knowledge_nodes n ON n.id = e.target_id AND n.project_id = $2
WHERE e.source_id = $1 AND e.project_id = $2 AND e.edge_type = 'contains_section'
ORDER BY (n.properties->>'line_start')::int NULLS LAST,
         (n.properties->>'ordinal')::int NULLS LAST, n.id`, sectionID, projectID)
	if err != nil {
		return nil, fmt.Errorf("SectionNeighbors children: %w", err)
	}
	children, err := scanNavNodes(childRows)
	childRows.Close()
	if err != nil {
		return nil, err
	}
	for _, c := range children {
		switch c.NodeType {
		case "document_section":
			nh.Subsections = append(nh.Subsections, c)
		case "document_chunk":
			nh.Chunks = append(nh.Chunks, c)
		}
	}

	// Siblings: parent's other document_section children, current excluded.
	if nh.Parent != nil {
		sibRows, err := s.db.QueryContext(ctx, `
SELECT `+navNodeCols+`
FROM knowledge_edges e
JOIN knowledge_nodes n ON n.id = e.target_id AND n.project_id = $2
WHERE e.source_id = $1 AND e.project_id = $2 AND e.edge_type = 'contains_section'
  AND n.node_type = 'document_section' AND n.id <> $3
ORDER BY (n.properties->>'line_start')::int NULLS LAST, n.id`, nh.Parent.ID, projectID, sectionID)
		if err != nil {
			return nil, fmt.Errorf("SectionNeighbors siblings: %w", err)
		}
		nh.Siblings, err = scanNavNodes(sibRows)
		sibRows.Close()
		if err != nil {
			return nil, err
		}
	}
	return nh, nil
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestSectionNeighbors -v` (with `KG_TEST_DATABASE_URL` set)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/store/document_nav.go internal/store/document_nav_test.go
git commit -m "feat(nav): section-neighbors store method (parent/children/siblings)"
```

---

## Task 3: Outline handler + route

**Files:**
- Create: `ennam.kg.go/internal/handler/document_nav.go`
- Test: `ennam.kg.go/internal/handler/document_nav_test.go`

**Interfaces:**
- Consumes: `store.DocumentNavStore` (Task 1/2), `store.NodeStore.GetNode` (existence + type + ProjectID), `middleware.GetDeveloperIdentity` (IDOR), `errorResponse`/`writeJSON` (existing handler helpers).
- Produces:
  - `type DocumentNavHandler struct {...}`, `func NewDocumentNavHandler(nodeStore *store.NodeStore, navStore *store.DocumentNavStore, logger *slog.Logger) *DocumentNavHandler`
  - `func (h *DocumentNavHandler) RegisterRoutes(mux *http.ServeMux)`
  - `GET /api/v1/nodes/{id}/outline` → `GetOutline`
  - JSON: `{ node_id, title, truncated, sections: [ {node_id,title,line_start,line_end,level,chunk_count,children[]} ] }`

> **Test convention (match the package):** handler tests are `package handler`, use `httptest`, and test the **validation branches reachable with a `nil` store** (see `neighbors_test.go:43` — `NewNeighborHandler(nil, logger)`). The data path (real GetNode) is proven at the store layer (Tasks 1-2). The non-trivial handler logic here — `assembleOutline`/`sortEntries` — is **pure** and is unit-tested directly (no DB), which is also where NFR-271 (no `sec-` ids) and sibling ordering live.

- [ ] **Step 1: Write the failing tests**

Create `document_nav_test.go` in `package handler`:

```go
package handler

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/store"
)

func ip(n int) *int { return &n }

// Missing id fires before any store call — safe with nil stores.
func TestGetOutline_MissingIDReturns400(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	h := NewDocumentNavHandler(nil, nil, logger)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/nodes//outline", nil)
	req.SetPathValue("id", "")
	w := httptest.NewRecorder()
	h.GetOutline(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("want 400 for missing id, got %d", w.Code)
	}
}

// assembleOutline is the core FR-001 logic: edge-derived nesting, sibling order
// (line_start asc, nulls last, id tiebreak), null level passthrough, orphan
// dropped, real UUIDs only (no sec- ids), chunk_count preserved.
func TestAssembleOutline_NestingOrderingAndNoSyntheticIDs(t *testing.T) {
	hub := "11111111-1111-1111-1111-111111111111"
	a := "aaaaaaaa-0000-0000-0000-000000000001"
	b := "bbbbbbbb-0000-0000-0000-000000000002"
	d := "dddddddd-0000-0000-0000-000000000003"
	orphan := "ffffffff-0000-0000-0000-000000000009"
	rows := []store.OutlineRow{
		{ID: b, Title: "B", ParentID: hub, LineStart: ip(10), LineEnd: ip(20), Level: ip(1), ChunkCount: 2},
		{ID: a, Title: "A", ParentID: hub, LineStart: ip(1), LineEnd: ip(10), Level: ip(1), ChunkCount: 0},
		{ID: d, Title: "D", ParentID: b, LineStart: nil, LineEnd: nil, Level: nil, ChunkCount: 0},
		{ID: orphan, Title: "Orphan", ParentID: "no-such-parent", LineStart: ip(5)},
	}

	roots := assembleOutline(rows, hub)

	if len(roots) != 2 || roots[0].NodeID != a || roots[1].NodeID != b {
		t.Fatalf("want roots [A,B] by line_start, got %+v", roots)
	}
	if len(roots[1].Children) != 1 || roots[1].Children[0].NodeID != d {
		t.Fatalf("want B.children=[D] (edge-derived nesting), got %+v", roots[1].Children)
	}
	if roots[1].Children[0].Level != nil {
		t.Errorf("D.level should pass through as nil, got %v", *roots[1].Children[0].Level)
	}
	if roots[1].ChunkCount != 2 {
		t.Errorf("B.chunk_count want 2, got %d", roots[1].ChunkCount)
	}

	out, _ := json.Marshal(map[string]interface{}{"sections": roots})
	if strings.Contains(string(out), "sec-") {
		t.Errorf("NFR-271: response must contain no synthetic sec- ids: %s", out)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run 'TestGetOutline_MissingIDReturns400|TestAssembleOutline' -v`
Expected: FAIL — `NewDocumentNavHandler`/`GetOutline`/`assembleOutline`/`store.OutlineRow` undefined.

- [ ] **Step 3: Write minimal implementation**

```go
package handler

import (
	"log/slog"
	"net/http"
	"sort"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/store"
)

// maxOutlineSections bounds the outline (BR-NAV-08); a fuller outline sets truncated=true.
const maxOutlineSections = 2000

// DocumentNavHandler serves edge-derived document navigation (BA-032a):
// outline and section neighborhood, keyed by real document_section UUIDs.
type DocumentNavHandler struct {
	nodeStore *store.NodeStore
	navStore  *store.DocumentNavStore
	logger    *slog.Logger
}

// NewDocumentNavHandler constructs a DocumentNavHandler.
func NewDocumentNavHandler(nodeStore *store.NodeStore, navStore *store.DocumentNavStore, logger *slog.Logger) *DocumentNavHandler {
	return &DocumentNavHandler{nodeStore: nodeStore, navStore: navStore, logger: logger}
}

// RegisterRoutes registers BA-032a navigation routes.
func (h *DocumentNavHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/nodes/{id}/outline", h.GetOutline)
	mux.HandleFunc("GET /api/v1/nodes/{id}/section-neighbors", h.GetSectionNeighbors)
}

type outlineEntry struct {
	NodeID     string         `json:"node_id"`
	Title      string         `json:"title"`
	LineStart  *int           `json:"line_start"`
	LineEnd    *int           `json:"line_end"`
	Level      *int           `json:"level"`
	ChunkCount int            `json:"chunk_count"`
	Children   []*outlineEntry `json:"children"`
}

// GetOutline returns the edge-derived outline of a document/external hub.
func (h *DocumentNavHandler) GetOutline(w http.ResponseWriter, r *http.Request) {
	nodeID := r.PathValue("id")
	if nodeID == "" {
		errorResponse(w, http.StatusBadRequest, "node id is required")
		return
	}
	node, err := h.nodeStore.GetNode(r.Context(), nodeID)
	if err != nil {
		errorResponse(w, http.StatusNotFound, "node not found")
		return
	}
	if identity := middleware.GetDeveloperIdentity(r.Context()); identity != nil && !identity.HasProjectAccess(node.ProjectID) {
		errorResponse(w, http.StatusNotFound, "node not found")
		return
	}
	if node.NodeType != "document" && node.NodeType != "external" {
		errorResponse(w, http.StatusBadRequest, "node is not a document hub")
		return
	}

	rows, err := h.navStore.OutlineByHub(r.Context(), nodeID, node.ProjectID, maxOutlineSections)
	if err != nil {
		h.logger.Error("outline query failed", "node_id", nodeID, "err", err)
		errorResponse(w, http.StatusInternalServerError, "failed to build outline")
		return
	}

	sections := assembleOutline(rows, nodeID)
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"node_id":   nodeID,
		"title":     node.Title,
		"truncated": len(rows) >= maxOutlineSections,
		"sections":  sections,
	})
}

// assembleOutline turns flat rows into a tree rooted at hubID, ordering siblings
// by line_start (nulls last) then node_id.
func assembleOutline(rows []store.OutlineRow, hubID string) []*outlineEntry {
	byID := make(map[string]*outlineEntry, len(rows))
	for _, r := range rows {
		byID[r.ID] = &outlineEntry{
			NodeID: r.ID, Title: r.Title,
			LineStart: r.LineStart, LineEnd: r.LineEnd, Level: r.Level,
			ChunkCount: r.ChunkCount, Children: []*outlineEntry{},
		}
	}
	var roots []*outlineEntry
	for _, r := range rows {
		e := byID[r.ID]
		if r.ParentID == hubID {
			roots = append(roots, e)
		} else if parent, ok := byID[r.ParentID]; ok {
			parent.Children = append(parent.Children, e)
		}
		// rows whose parent is absent (orphan) are dropped from the tree.
	}
	sortEntries(roots)
	for _, e := range byID {
		sortEntries(e.Children)
	}
	return roots
}

func sortEntries(es []*outlineEntry) {
	sort.SliceStable(es, func(i, j int) bool {
		li, lj := es[i].LineStart, es[j].LineStart
		switch {
		case li == nil && lj != nil:
			return false
		case li != nil && lj == nil:
			return true
		case li != nil && lj != nil && *li != *lj:
			return *li < *lj
		default:
			return es[i].NodeID < es[j].NodeID
		}
	})
}
```

> `GetSectionNeighbors` is added in Task 4; this task compiles because `RegisterRoutes` references it — add a temporary stub `func (h *DocumentNavHandler) GetSectionNeighbors(w http.ResponseWriter, r *http.Request) { errorResponse(w, http.StatusNotImplemented, "not implemented") }` at the bottom of this file and replace it in Task 4.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run 'TestGetOutline_MissingIDReturns400|TestAssembleOutline' -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/handler/document_nav.go internal/handler/document_nav_test.go
git commit -m "feat(nav): GET /outline handler (IDOR, tree assembly, soft cap)"
```

---

## Task 4: Section-neighbors handler

**Files:**
- Modify: `ennam.kg.go/internal/handler/document_nav.go` (replace the `GetSectionNeighbors` stub)
- Modify: `ennam.kg.go/internal/handler/document_nav_test.go`

**Interfaces:**
- Consumes: `store.DocumentNavStore.SectionNeighbors`, `NavNode`/`SectionNeighborhood`.
- Produces: `GET /api/v1/nodes/{id}/section-neighbors` → JSON `{ node_id, parent, children:{subsections,chunks}, siblings }`. Non-section node → `400 NOT_A_SECTION` (message `"node is not a document_section"`).

> The non-section `400 NOT_A_SECTION` guard requires a real `GetNode` and is proven by the store-layer `SectionNeighbors` data path (Task 2); here we test the nil-store-safe missing-id branch and that the stub is gone. (An optional real-DB handler test for the non-section guard may mirror the merge-handler real-DB pattern in `merge_test.go`, gated on `KG_TEST_DATABASE_URL`.)

- [ ] **Step 1: Write the failing test** (append to `internal/handler/document_nav_test.go`)

```go
func TestGetSectionNeighbors_MissingIDReturns400(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	h := NewDocumentNavHandler(nil, nil, logger)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/nodes//section-neighbors", nil)
	req.SetPathValue("id", "")
	w := httptest.NewRecorder()
	h.GetSectionNeighbors(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("want 400 for missing id, got %d", w.Code)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestGetSectionNeighbors_MissingIDReturns400 -v`
Expected: FAIL — the Task 3 stub returns 501 (not 400) for the missing-id path, or `GetSectionNeighbors` not yet replaced.

- [ ] **Step 3: Write minimal implementation** (replace the stub)

```go
type navNodeJSON struct {
	NodeID    string `json:"node_id"`
	Title     string `json:"title"`
	NodeType  string `json:"node_type"`
	LineStart *int   `json:"line_start"`
	LineEnd   *int   `json:"line_end"`
	Level     *int   `json:"level,omitempty"`
	Ordinal   *int   `json:"ordinal,omitempty"`
}

func toNavJSON(n store.NavNode) navNodeJSON {
	return navNodeJSON{
		NodeID: n.ID, Title: n.Title, NodeType: n.NodeType,
		LineStart: n.LineStart, LineEnd: n.LineEnd, Level: n.Level, Ordinal: n.Ordinal,
	}
}

func toNavJSONList(ns []store.NavNode) []navNodeJSON {
	out := make([]navNodeJSON, 0, len(ns))
	for _, n := range ns {
		out = append(out, toNavJSON(n))
	}
	return out
}

// GetSectionNeighbors returns parent/children/siblings for a document_section.
func (h *DocumentNavHandler) GetSectionNeighbors(w http.ResponseWriter, r *http.Request) {
	nodeID := r.PathValue("id")
	if nodeID == "" {
		errorResponse(w, http.StatusBadRequest, "node id is required")
		return
	}
	node, err := h.nodeStore.GetNode(r.Context(), nodeID)
	if err != nil {
		errorResponse(w, http.StatusNotFound, "node not found")
		return
	}
	if identity := middleware.GetDeveloperIdentity(r.Context()); identity != nil && !identity.HasProjectAccess(node.ProjectID) {
		errorResponse(w, http.StatusNotFound, "node not found")
		return
	}
	if node.NodeType != "document_section" {
		errorResponse(w, http.StatusBadRequest, "node is not a document_section")
		return
	}

	nh, err := h.navStore.SectionNeighbors(r.Context(), nodeID, node.ProjectID)
	if err != nil {
		h.logger.Error("section-neighbors query failed", "node_id", nodeID, "err", err)
		errorResponse(w, http.StatusInternalServerError, "failed to fetch section neighbors")
		return
	}

	var parent interface{}
	if nh.Parent != nil {
		parent = toNavJSON(*nh.Parent)
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"node_id": nodeID,
		"parent":  parent,
		"children": map[string]interface{}{
			"subsections": toNavJSONList(nh.Subsections),
			"chunks":      toNavJSONList(nh.Chunks),
		},
		"siblings": toNavJSONList(nh.Siblings),
	})
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestGetSectionNeighbors_MissingIDReturns400 -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/handler/document_nav.go internal/handler/document_nav_test.go
git commit -m "feat(nav): GET /section-neighbors handler (strict section input)"
```

---

## Task 5: Wire handler at the composition root

**Files:**
- Modify: `ennam.kg.go/cmd/kg-server/main.go`

**Interfaces:**
- Consumes: existing `cmd/kg-server/main.go` locals — `db` (`*sql.DB`), `logger` (`*slog.Logger`), `nodeStore` (`store.NewNodeStore(db)`, main.go:365), `apiMux` (the protected sub-mux); `store.NewDocumentNavStore`; `handler.NewDocumentNavHandler`.

- [ ] **Step 1: Confirm the wiring site**

Run: `cd ennam.kg.go && grep -n "docHandler := handler.NewDocumentHandler\|docHandler.RegisterRoutes\|nodeStore :=\|apiMux" cmd/kg-server/main.go | head`
Expected: shows `nodeStore := store.NewNodeStore(db)` (~365), `docHandler := handler.NewDocumentHandler(nodeStore, nodeEmbStore, logger)` (~374), `docHandler.RegisterRoutes(apiMux)` (~375).

- [ ] **Step 2: Add the nav store + handler right after `docHandler.RegisterRoutes(apiMux)`**

```go
	navStore := store.NewDocumentNavStore(db)
	docNavHandler := handler.NewDocumentNavHandler(nodeStore, navStore, logger)
	docNavHandler.RegisterRoutes(apiMux)
```

(Reuse the existing `nodeStore`, `db`, `logger`, `apiMux` — do not re-declare them.)

- [ ] **Step 3: Build to verify it compiles**

Run: `cd ennam.kg.go && go build ./...`
Expected: builds with no errors.

- [ ] **Step 4: Smoke-test the route is mounted**

Run: `cd ennam.kg.go && go vet ./cmd/kg-server/...`
Expected: no vet errors. (Full route smoke is covered by handler tests in Tasks 3-4.)

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add cmd/kg-server/main.go
git commit -m "feat(nav): register document navigation routes at composition root"
```

---

## Task 6: MCP tools `kg_get_document_outline` + `kg_get_section_neighbors`

**Files:**
- Modify: `ennam.kg.go/internal/bridge/schema.go` (add two schemas; bump count comment)
- Modify: `ennam.kg.go/internal/bridge/client.go` (add two `RouteRead` GET routes)
- Modify: `ennam.kg.go/internal/bridge/schema_test.go` (35 → 37)
- Modify: `ennam.kg.go/internal/bridge/client_test.go` (RouteRead 12 → 14, total 33 → 35)

**Interfaces:**
- Consumes: existing `ToolSchema`, `ParamSchema`, `TypeString`, `uuidPattern`, `apiPrefix`, `RouteRead`, and the route map `toolRoutes map[string]ToolRoute` (struct `ToolRoute{Method, PathTemplate, PathParams, Class}`, client.go:100-114).
- Produces: two registered tools that proxy `GET /outline` and `GET /section-neighbors`.

- [ ] **Step 1: Update the count assertions first (RED)**

In `internal/bridge/schema_test.go` change the assertion and its comment:

```go
// TestAllToolSchemasRegistered verifies that all 37 MCP tools (35 HTTP-proxy + 2 local-exec) have schemas.
```
```go
	if len(schemas) != 37 {
		t.Errorf("expected 37 tool schemas, got %d", len(schemas))
```

In `internal/bridge/client_test.go` — update the count comment (~line 1058) and both assertions:

```go
	// IMP-008 corrected counts + BA-032a (+2 read): 14 read, 21 write, 0 local (local tools are not in toolRoutes)
```
```go
		RouteRead:  14,
```
```go
	if total != 35 {
		t.Errorf("total routed routes: got %d, want 35", total)
```

- [ ] **Step 2: Run the bridge tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/bridge/ -run 'TestAllToolSchemasRegistered|Route' -v`
Expected: FAIL — got 35 schemas want 37; RouteRead/total mismatch.

- [ ] **Step 3: Add the two tool schemas** (in `buildToolSchemas`, after the `kg_search_chunks` block ~line 1262)

```go
	// === kg_get_document_outline (BA-032a — routed HTTP-proxy read tool) ===
	schemas["kg_get_document_outline"] = &ToolSchema{
		ToolName:    "kg_get_document_outline",
		Description: "Get a document's outline: the real section UUIDs, titles, line ranges, levels, chunk counts, and nesting. Pass a document hub UUID (a section's properties.document_id). Use to navigate to an exact passage.",
		Properties: map[string]ParamSchema{
			"document_id": {
				Type:        TypeString,
				Required:    true,
				Description: "UUID of the document/external hub node",
				Format:      "uuid",
				Pattern:     uuidPattern,
			},
			"project_id": {
				Type:        TypeString,
				Required:    false,
				Description: "Optional project id (falls back to the default project)",
			},
		},
	}

	// === kg_get_section_neighbors (BA-032a — routed HTTP-proxy read tool) ===
	schemas["kg_get_section_neighbors"] = &ToolSchema{
		ToolName:    "kg_get_section_neighbors",
		Description: "Get a document_section's parent, child subsections and chunks, and sibling sections (prev/next) by real UUID. Pass a section UUID (e.g. a kg_search_chunks hit's section_id) to place it in its document.",
		Properties: map[string]ParamSchema{
			"section_id": {
				Type:        TypeString,
				Required:    true,
				Description: "UUID of the document_section node",
				Format:      "uuid",
				Pattern:     uuidPattern,
			},
			"project_id": {
				Type:        TypeString,
				Required:    false,
				Description: "Optional project id (falls back to the default project)",
			},
		},
	}
```

- [ ] **Step 4: Add the two routes** (in `client.go` route map, after the `kg_get_document` entry ~line 241)

```go
	"kg_get_document_outline": {
		Method:       http.MethodGet,
		PathTemplate: apiPrefix + "/nodes/{document_id}/outline",
		PathParams:   []string{"document_id"},
		Class:        RouteRead,
	},
	"kg_get_section_neighbors": {
		Method:       http.MethodGet,
		PathTemplate: apiPrefix + "/nodes/{section_id}/section-neighbors",
		PathParams:   []string{"section_id"},
		Class:        RouteRead,
	},
```

- [ ] **Step 5: Run the bridge tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/bridge/ -v`
Expected: PASS — 37 schemas, RouteRead 14, total 35. (If a separate test enumerates that every schema has a route, both new tools satisfy it.)

- [ ] **Step 6: Verify required-param validation works**

Run: `cd ennam.kg.go && go test ./internal/bridge/ -run 'ValidateToolParams|Validate' -v`
Expected: PASS — calling `kg_get_document_outline` without `document_id` fails validation (driven by `Required: true`). If no such test exists for the new tools, add one mirroring an existing `ValidateToolParams` test for `kg_get_document`.

- [ ] **Step 7: Commit**

```bash
cd ennam.kg.go
git add internal/bridge/schema.go internal/bridge/client.go internal/bridge/schema_test.go internal/bridge/client_test.go
git commit -m "feat(nav): register kg_get_document_outline + kg_get_section_neighbors MCP tools"
```

---

## Task 7: Stop writing legacy `document_tree` (OQ-1 trigger)

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/pipeline/decompose.py:60-74`
- Test: `ennam.kg.python/tests/ingestion/test_decompose.py` (or the existing decompose test module)

**Rationale:** With `/outline` shipping, new documents no longer need the synthetic `document_tree` JSONB on the hub (R-001, OQ-1). Keep `section_count` (used by `kg_get_document`). The `/document-structure` read path stays for back-compat (separate later removal).

- [ ] **Step 1: Write the failing test**

```python
import pytest

@pytest.mark.asyncio
async def test_decompose_does_not_write_document_tree(fake_kg, sample_draft):
    # fake_kg records update_node payloads; mirror the existing decompose test harness
    await decompose(fake_kg, hub_node_id="hub-1", draft=sample_draft, node_type="document")
    hub_update = fake_kg.updated_nodes["hub-1"]
    assert "document_tree" not in hub_update["properties"]
    assert hub_update["properties"]["section_count"] >= 0
```

> Match the actual decompose entrypoint signature and test fixtures already in the repo (`test_nodes.py`/`test_decompose.py`). If the existing harness uses a different fake-KG shape, reuse it rather than introducing a new one.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion -k document_tree -v`
Expected: FAIL — `document_tree` is still written.

- [ ] **Step 3: Edit `decompose.py`** — drop `document_tree` from the hub update (keep `section_count`)

Change the `update_node` properties block (lines ~67-71) from:

```python
                "properties": {
                    "document_tree": canonical.tree,
                    "section_count": len(sections),
                },
```

to:

```python
                "properties": {
                    # document_tree removed (BA-032a OQ-1): /outline is now the
                    # canonical, edge-derived outline. section_count is retained
                    # for kg_get_document citation metadata.
                    "section_count": len(sections),
                },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion -k document_tree -v`
Expected: PASS.

- [ ] **Step 5: Run the full decompose test module + lint**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion -q && uv run ruff check src/ennam_kg/ingestion/pipeline/decompose.py`
Expected: all pass; no new lint errors. (No existing test should assert `document_tree` is present; if one does, update it — it is now intentionally absent.)

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/ingestion/pipeline/decompose.py tests/ingestion
git commit -m "feat(nav): stop writing legacy document_tree on hub (BA-032a OQ-1)"
```

---

## Final verification

- [ ] **Go race + full suite:**

Run: `cd ennam.kg.go && KG_TEST_DATABASE_URL=<test-db-url> go test -race -count=1 ./internal/store/... ./internal/handler/... ./internal/bridge/...`
Expected: PASS. Store/handler DB-backed tests skip automatically when `KG_TEST_DATABASE_URL` is unset (no build tag); set it to a live PostgreSQL per `make db-up` to run them. `make test` runs the same without tags.

- [ ] **Lint:** `cd ennam.kg.go && make lint` → no new findings.

- [ ] **NFR-271 contract check:** confirm no test fixture or response contains a `sec-` value (covered by `TestGetOutline_NoSyntheticIdsInResponse`).

- [ ] **Manual smoke (optional):** with `make dev` running and a decomposed document hub `H`:
  `curl -s localhost:8080/api/v1/nodes/H/outline | jq '.sections[0]'` → real UUID, `chunk_count`, no `summary`.

---

## Out of scope (BA-032b — separate plan after BA-031)

FR-003 backlinks (`/api/v1/nodes/{id}/backlinks`) + `kg_get_backlinks`. Depends on BA-031 producing `references_document`/`mentions` edges. Will bump tool count 37 → 38 (RouteRead 14 → 15, total 35 → 36). Remember the D1 correction: an `external` node's `referenced_by` is **not** structurally empty (inbound `document → references_document → external` is whitelisted).
