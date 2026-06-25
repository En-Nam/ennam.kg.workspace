# BA-032b Cross-source Backlinks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only cross-source backlinks surface — outbound `references_document`, inbound `references_document` (backlinks), and outbound `mentions → concept` — exposed over HTTP and as one MCP tool, keyed by real node UUIDs.

**Architecture:** Extends the BA-032a `DocumentNavStore`/`DocumentNavHandler` (already landed). One new store method (`BacklinksByNode`, three single-hop edge queries), one new handler method (`GetBacklinks`) + route, one new bridge tool (`kg_get_backlinks`). No new table, no migration. Reuses the existing `NavNode`/`scanNavNodes`/`navNodeCols` helpers and the `GetDocumentMeta` IDOR pattern.

**Tech Stack:** Go (stdlib `net/http`, `database/sql`, `log/slog`), PostgreSQL 16, MCP bridge.

**Source spec:** `docs/superpowers/specs/2026-06-18-document-navigation-cross-source-links-design.md` §4 (FR-003 + FR-004b).

**Depends on BA-032a:** shipped (handler `internal/handler/document_nav.go`, store `internal/store/document_nav.go`, bridge tools registered; tool baseline **37 schemas / RouteRead 14 / total 35**).

**Depends on BA-031 for *data*, not for *code*:** the `references_document`/`mentions` edges this surface reads are produced by BA-031. Until BA-031 runs, all arrays are empty and the endpoint returns `200` (BR-NAV-19). **Tests seed these edges directly into the test DB** (raw `seedEdge` INSERT bypasses the creation-time whitelist), so this plan is fully implementable and testable now.

## Global Constraints

- **No new migration, no new table.** Reads only existing nodes/edges.
- **No `status` predicate** on any query — match the BA-032a convention (D2). Cross-project links are naturally excluded because every JOIN requires the linked node's `project_id = $2`.
- **Real UUIDs only**, no `summary`/`content` body text (NFR-273). Each backlink entry carries `node_id`, `title`, `node_type` only (BR-NAV-20).
- **IDOR order = `GetDocumentMeta` exactly** (document.go): id-missing→400, not-found→404, `HasProjectAccess(node.ProjectID)` fail→404, wrong-type→400. Return **404 not 403** cross-tenant.
- **Accepted node types:** `document`, `external`, `document_section` (BR-NAV-18). `document_chunk` → `400 UNSUPPORTED_NODE_TYPE` (message `"node type does not support backlinks"`).
- **Whitelisted edges only:** `references_document` (config.yaml:877-882, source `document` → targets `document`/`external`) and `mentions` (config.yaml:917-928, source `document`/`document_section` → `concept`). No other relationship is read.
- **D1 (CRITICAL — do not regress):** `referenced_by` (inbound `references_document`) is populated for **both `document` and `external`** target nodes, because `document → references_document → external` is whitelisted. An `external` node's `referenced_by` is **not** structurally empty. Only `references_out` for an `external` node is empty today (no `external` *source* rule).
- **OQ-7 / M10:** do **not** write any test asserting an `external → references_document` *source* rule exists. The D1 test seeds an inbound edge from a `document` source — a legal whitelisted edge.
- Go style: `fmt.Errorf("context: %w", err)`, `log/slog`, table-driven tests, `go test -race`.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `internal/store/document_nav.go` | modify (append) | Add `Backlinks` type + `BacklinksByNode` method. |
| `internal/store/document_nav_test.go` | modify (append) | Store tests incl. the D1 external-`referenced_by` case + empty-but-present. |
| `internal/handler/document_nav.go` | modify | Add `GetBacklinks` + register `/backlinks` route. |
| `internal/handler/document_nav_test.go` | modify (append) | Nil-store missing-id 400 + unsupported-type guard test. |
| `internal/bridge/schema.go` | modify | Add `kg_get_backlinks` schema. |
| `internal/bridge/client.go` | modify | Add `kg_get_backlinks` `RouteRead` GET route. |
| `internal/bridge/schema_test.go` | modify | Count 37 → 38. |
| `internal/bridge/client_test.go` | modify | `RouteRead` 14 → 15, total 35 → 36, comment. |

No change to `cmd/kg-server/main.go` — the `DocumentNavHandler` is already constructed and registered there; adding a route inside its existing `RegisterRoutes` is enough.

---

## Task 1: `BacklinksByNode` store method

**Files:**
- Modify: `ennam.kg.go/internal/store/document_nav.go`
- Modify: `ennam.kg.go/internal/store/document_nav_test.go`

**Interfaces:**
- Consumes: existing `DocumentNavStore`, `NavNode`, `navNodeCols`, `scanNavNodes` (already in `document_nav.go`); test helpers `setupTestDB`, `seedNavProject`, `mustSeedNode`, `seedEdge` (already in `document_nav_test.go` / `node_subtree_test.go`).
- Produces:
  - `type Backlinks struct { ReferencesOut, ReferencedBy, Mentions []NavNode }`
  - `func (s *DocumentNavStore) BacklinksByNode(ctx context.Context, nodeID, projectID string) (*Backlinks, error)` — slices are non-nil but may be empty (BR-NAV-19).

- [ ] **Step 1: Write the failing test** (append to `document_nav_test.go`, `package store_test`)

```go
func TestBacklinksByNode_OutInboundAndMentions(t *testing.T) {
	db := setupTestDB(t)
	ctx, proj := seedNavProject(t, db)

	x := mustSeedNode(t, ctx, db, proj, "document", "X", `{}`)
	y := mustSeedNode(t, ctx, db, proj, "document", "Y", `{}`)
	z := mustSeedNode(t, ctx, db, proj, "document", "Z", `{}`)
	c := mustSeedNode(t, ctx, db, proj, "concept", "C", `{}`)
	// X -> Y (references_out), Z -> X (referenced_by), X -> C (mentions)
	if err := seedEdge(ctx, db, proj, x, y, "references_document"); err != nil {
		t.Fatalf("seed x->y: %v", err)
	}
	if err := seedEdge(ctx, db, proj, z, x, "references_document"); err != nil {
		t.Fatalf("seed z->x: %v", err)
	}
	if err := seedEdge(ctx, db, proj, x, c, "mentions"); err != nil {
		t.Fatalf("seed x->c: %v", err)
	}

	bl, err := store.NewDocumentNavStore(db).BacklinksByNode(ctx, x, proj)
	if err != nil {
		t.Fatalf("BacklinksByNode: %v", err)
	}
	if len(bl.ReferencesOut) != 1 || bl.ReferencesOut[0].ID != y {
		t.Errorf("references_out want [Y], got %+v", bl.ReferencesOut)
	}
	if len(bl.ReferencedBy) != 1 || bl.ReferencedBy[0].ID != z {
		t.Errorf("referenced_by want [Z], got %+v", bl.ReferencedBy)
	}
	if len(bl.Mentions) != 1 || bl.Mentions[0].ID != c || bl.Mentions[0].NodeType != "concept" {
		t.Errorf("mentions want [C concept], got %+v", bl.Mentions)
	}
}

// D1: an external node's referenced_by is NOT empty — document -> references_document -> external
// is whitelisted, so an inbound edge from a document source populates it. This seeds the
// inbound edge from a *document* source (legal); it does NOT assume an external source rule (OQ-7).
func TestBacklinksByNode_ExternalReferencedByIsPopulated(t *testing.T) {
	db := setupTestDB(t)
	ctx, proj := seedNavProject(t, db)

	ext := mustSeedNode(t, ctx, db, proj, "external", "E", `{}`)
	w := mustSeedNode(t, ctx, db, proj, "document", "W", `{}`)
	if err := seedEdge(ctx, db, proj, w, ext, "references_document"); err != nil {
		t.Fatalf("seed w->ext: %v", err)
	}

	bl, err := store.NewDocumentNavStore(db).BacklinksByNode(ctx, ext, proj)
	if err != nil {
		t.Fatalf("BacklinksByNode: %v", err)
	}
	if len(bl.ReferencedBy) != 1 || bl.ReferencedBy[0].ID != w {
		t.Errorf("D1: external referenced_by want [W], got %+v", bl.ReferencedBy)
	}
	if len(bl.ReferencesOut) != 0 {
		t.Errorf("external references_out should be empty today (no external source rule), got %+v", bl.ReferencesOut)
	}
}

// BR-NAV-19: no edges => all slices empty (non-nil), no error.
func TestBacklinksByNode_EmptyWhenNoEdges(t *testing.T) {
	db := setupTestDB(t)
	ctx, proj := seedNavProject(t, db)
	lonely := mustSeedNode(t, ctx, db, proj, "document", "Lonely", `{}`)

	bl, err := store.NewDocumentNavStore(db).BacklinksByNode(ctx, lonely, proj)
	if err != nil {
		t.Fatalf("BacklinksByNode: %v", err)
	}
	if bl.ReferencesOut == nil || bl.ReferencedBy == nil || bl.Mentions == nil {
		t.Errorf("slices must be non-nil (empty), got %+v", bl)
	}
	if len(bl.ReferencesOut)+len(bl.ReferencedBy)+len(bl.Mentions) != 0 {
		t.Errorf("want all empty, got %+v", bl)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestBacklinksByNode -v` (with `KG_TEST_DATABASE_URL` set)
Expected: FAIL — `BacklinksByNode` / `store.Backlinks` undefined.

- [ ] **Step 3: Write minimal implementation** (append to `document_nav.go`)

```go
// Backlinks is the cross-source navigation neighborhood of a node (FR-003):
// outbound references_document, inbound references_document (backlinks), and
// outbound mentions to concepts. Slices are non-nil; empty when no edges exist
// (BR-NAV-19). No status predicate (D2); cross-project links excluded via the
// project_id JOIN.
type Backlinks struct {
	ReferencesOut []NavNode
	ReferencedBy  []NavNode
	Mentions      []NavNode
}

// BacklinksByNode reads whitelisted cross-source edges for nodeID. references_out
// = outgoing references_document; referenced_by = inbound references_document
// (populated for document AND external targets — D1); mentions = outgoing
// mentions to concept.
func (s *DocumentNavStore) BacklinksByNode(ctx context.Context, nodeID, projectID string) (*Backlinks, error) {
	if s.db == nil {
		return nil, fmt.Errorf("BacklinksByNode: nil database")
	}
	bl := &Backlinks{
		ReferencesOut: []NavNode{},
		ReferencedBy:  []NavNode{},
		Mentions:      []NavNode{},
	}

	// references_out: outgoing references_document (linked node is the target).
	outRows, err := s.db.QueryContext(ctx, `
SELECT `+navNodeCols+`
FROM knowledge_edges e
JOIN knowledge_nodes n ON n.id = e.target_id AND n.project_id = $2
WHERE e.source_id = $1 AND e.project_id = $2 AND e.edge_type = 'references_document'
ORDER BY n.title, n.id`, nodeID, projectID)
	if err != nil {
		return nil, fmt.Errorf("BacklinksByNode references_out: %w", err)
	}
	bl.ReferencesOut, err = scanNavNodes(outRows)
	outRows.Close()
	if err != nil {
		return nil, err
	}

	// referenced_by: inbound references_document (linked node is the source).
	inRows, err := s.db.QueryContext(ctx, `
SELECT `+navNodeCols+`
FROM knowledge_edges e
JOIN knowledge_nodes n ON n.id = e.source_id AND n.project_id = $2
WHERE e.target_id = $1 AND e.project_id = $2 AND e.edge_type = 'references_document'
ORDER BY n.title, n.id`, nodeID, projectID)
	if err != nil {
		return nil, fmt.Errorf("BacklinksByNode referenced_by: %w", err)
	}
	bl.ReferencedBy, err = scanNavNodes(inRows)
	inRows.Close()
	if err != nil {
		return nil, err
	}

	// mentions: outgoing mentions to concept.
	mRows, err := s.db.QueryContext(ctx, `
SELECT `+navNodeCols+`
FROM knowledge_edges e
JOIN knowledge_nodes n ON n.id = e.target_id AND n.project_id = $2
WHERE e.source_id = $1 AND e.project_id = $2 AND e.edge_type = 'mentions'
  AND n.node_type = 'concept'
ORDER BY n.title, n.id`, nodeID, projectID)
	if err != nil {
		return nil, fmt.Errorf("BacklinksByNode mentions: %w", err)
	}
	bl.Mentions, err = scanNavNodes(mRows)
	mRows.Close()
	if err != nil {
		return nil, err
	}

	// scanNavNodes returns nil for an empty result; keep non-nil empty slices.
	if bl.ReferencesOut == nil {
		bl.ReferencesOut = []NavNode{}
	}
	if bl.ReferencedBy == nil {
		bl.ReferencedBy = []NavNode{}
	}
	if bl.Mentions == nil {
		bl.Mentions = []NavNode{}
	}
	return bl, nil
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestBacklinksByNode -v` (with `KG_TEST_DATABASE_URL` set)
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/store/document_nav.go internal/store/document_nav_test.go
git commit -m "feat(nav): BacklinksByNode store method (references_document + mentions)"
```

---

## Task 2: `GetBacklinks` handler + route

**Files:**
- Modify: `ennam.kg.go/internal/handler/document_nav.go`
- Modify: `ennam.kg.go/internal/handler/document_nav_test.go`

**Interfaces:**
- Consumes: `store.DocumentNavStore.BacklinksByNode`, `store.NavNode`, existing `errorResponse`/`writeJSON`, `middleware.GetDeveloperIdentity`.
- Produces: `GET /api/v1/nodes/{id}/backlinks` → JSON `{ node_id, references_out, referenced_by, mentions }` where each array element is `{ node_id, title, node_type }`.

- [ ] **Step 1: Register the route** — add to the existing `RegisterRoutes` in `document_nav.go`:

```go
	mux.HandleFunc("GET /api/v1/nodes/{id}/backlinks", h.GetBacklinks)
```

- [ ] **Step 2: Write the failing tests** (append to `internal/handler/document_nav_test.go`, `package handler`)

```go
func TestGetBacklinks_MissingIDReturns400(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	h := NewDocumentNavHandler(nil, nil, logger)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/nodes//backlinks", nil)
	req.SetPathValue("id", "")
	w := httptest.NewRecorder()
	h.GetBacklinks(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("want 400 for missing id, got %d", w.Code)
	}
}

// backlinkEntry projection carries identity only (BR-NAV-20) and never body text.
func TestToBacklinkJSON_IdentityOnly(t *testing.T) {
	out := toBacklinkJSONList([]store.NavNode{
		{ID: "n1", Title: "Doc One", NodeType: "document", LineStart: ip(5)},
	})
	if len(out) != 1 || out[0].NodeID != "n1" || out[0].Title != "Doc One" || out[0].NodeType != "document" {
		t.Fatalf("unexpected projection: %+v", out)
	}
	b, _ := json.Marshal(out[0])
	if strings.Contains(string(b), "line_start") || strings.Contains(string(b), "summary") || strings.Contains(string(b), "content") {
		t.Errorf("backlink entry must be identity-only, got %s", b)
	}
}
```

> `ip` is defined in `document_nav_test.go` by BA-032a. Reuse it.

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run 'TestGetBacklinks_MissingIDReturns400|TestToBacklinkJSON' -v`
Expected: FAIL — `GetBacklinks` / `toBacklinkJSONList` undefined.

- [ ] **Step 4: Write minimal implementation** (append to `document_nav.go`)

```go
type backlinkEntry struct {
	NodeID   string `json:"node_id"`
	Title    string `json:"title"`
	NodeType string `json:"node_type"`
}

func toBacklinkJSONList(ns []store.NavNode) []backlinkEntry {
	out := make([]backlinkEntry, 0, len(ns))
	for _, n := range ns {
		out = append(out, backlinkEntry{NodeID: n.ID, Title: n.Title, NodeType: n.NodeType})
	}
	return out
}

// GetBacklinks returns cross-source links for a document/external/document_section
// node: references_out, referenced_by, mentions (BR-NAV-16/17/18). Empty arrays
// when no edges (BR-NAV-19). document_chunk is unsupported.
func (h *DocumentNavHandler) GetBacklinks(w http.ResponseWriter, r *http.Request) {
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
	switch node.NodeType {
	case "document", "external", "document_section":
		// supported
	default:
		errorResponse(w, http.StatusBadRequest, "node type does not support backlinks")
		return
	}

	bl, err := h.navStore.BacklinksByNode(r.Context(), nodeID, node.ProjectID)
	if err != nil {
		h.logger.Error("backlinks query failed", "node_id", nodeID, "err", err)
		errorResponse(w, http.StatusInternalServerError, "failed to fetch backlinks")
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"node_id":        nodeID,
		"references_out": toBacklinkJSONList(bl.ReferencesOut),
		"referenced_by":  toBacklinkJSONList(bl.ReferencedBy),
		"mentions":       toBacklinkJSONList(bl.Mentions),
	})
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run 'TestGetBacklinks_MissingIDReturns400|TestToBacklinkJSON' -v`
Expected: PASS. Then `go build ./...` to confirm the route wiring compiles.

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.go
git add internal/handler/document_nav.go internal/handler/document_nav_test.go
git commit -m "feat(nav): GET /backlinks handler (references + mentions, FR-003)"
```

---

## Task 3: MCP tool `kg_get_backlinks`

**Files:**
- Modify: `ennam.kg.go/internal/bridge/schema.go`
- Modify: `ennam.kg.go/internal/bridge/client.go`
- Modify: `ennam.kg.go/internal/bridge/schema_test.go` (37 → 38)
- Modify: `ennam.kg.go/internal/bridge/client_test.go` (RouteRead 14 → 15, total 35 → 36)

**Interfaces:**
- Consumes: existing `ToolSchema`, `ParamSchema`, `TypeString`, `uuidPattern`, `apiPrefix`, `RouteRead`, `toolRoutes map[string]ToolRoute`.
- Produces: a registered tool proxying `GET /backlinks`.

- [ ] **Step 1: Update the count assertions first (RED)**

In `internal/bridge/schema_test.go` (~line 8 comment + 50-51):

```go
// TestAllToolSchemasRegistered verifies that all 38 MCP tools (36 HTTP-proxy + 2 local-exec) have schemas.
```
```go
	if len(schemas) != 38 {
		t.Errorf("expected 38 tool schemas, got %d", len(schemas))
```

In `internal/bridge/client_test.go` (~line 1058 comment + 1060 + 1070):

```go
	// IMP-008 + BA-032a (+2) + BA-032b (+1): 15 read, 21 write, 0 local (local tools are not in toolRoutes)
```
```go
		RouteRead:  15,
```
```go
	if total != 36 {
		t.Errorf("total routed routes: got %d, want 36", total)
```

- [ ] **Step 2: Run the bridge tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/bridge/ -run 'TestAllToolSchemasRegistered|Route' -v`
Expected: FAIL — got 37 schemas want 38; RouteRead/total mismatch.

- [ ] **Step 3: Add the tool schema** (in `buildToolSchemas`, after the `kg_get_section_neighbors` block ~line 1254)

```go
	// === kg_get_backlinks (BA-032b — routed HTTP-proxy read tool) ===
	schemas["kg_get_backlinks"] = &ToolSchema{
		ToolName:    "kg_get_backlinks",
		Description: "Get cross-source links for a document, external, or section node: documents it references (references_out), documents that reference it (referenced_by / backlinks), and concepts it mentions. Use to navigate between linked documents and concepts. Pass a node UUID.",
		Properties: map[string]ParamSchema{
			"node_id": {
				Type:        TypeString,
				Required:    true,
				Description: "UUID of the document/external/document_section node",
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

- [ ] **Step 4: Add the route** (in `client.go` `toolRoutes`, after the `kg_get_section_neighbors` entry ~line 258)

```go
	"kg_get_backlinks": {
		Method:       http.MethodGet,
		PathTemplate: apiPrefix + "/nodes/{node_id}/backlinks",
		PathParams:   []string{"node_id"},
		Class:        RouteRead,
	},
```

- [ ] **Step 5: Run the bridge tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/bridge/ -v`
Expected: PASS — 38 schemas, RouteRead 15, total 36. (`TestAllRoutesTagged` and the local-tools-not-in-routes test both still hold; the new tool is `RouteRead`, not local.)

- [ ] **Step 6: Verify required-param validation**

Run: `cd ennam.kg.go && go test ./internal/bridge/ -run 'ValidateToolParams|Validate' -v`
Expected: PASS — `kg_get_backlinks` without `node_id` fails validation (`Required: true`). If no test covers the new tool, add one mirroring the existing `kg_get_document` validation test.

- [ ] **Step 7: Commit**

```bash
cd ennam.kg.go
git add internal/bridge/schema.go internal/bridge/client.go internal/bridge/schema_test.go internal/bridge/client_test.go
git commit -m "feat(nav): register kg_get_backlinks MCP tool (FR-004b)"
```

---

## Final verification

- [ ] **Go race + full suite:**

Run: `cd ennam.kg.go && KG_TEST_DATABASE_URL=<test-db-url> go test -race -count=1 ./internal/store/... ./internal/handler/... ./internal/bridge/...`
Expected: PASS. DB-backed store/handler tests skip when `KG_TEST_DATABASE_URL` is unset.

- [ ] **Lint:** `cd ennam.kg.go && make lint` → no new findings.

- [ ] **D1 regression guard present:** confirm `TestBacklinksByNode_ExternalReferencedByIsPopulated` passes (external `referenced_by` is non-empty).

- [ ] **Empty-but-200 (BR-NAV-19):** confirm a node with no cross-source edges returns `200` with three empty arrays — the expected state until BA-031 produces edges.

- [ ] **Manual smoke (optional):** with `make dev` running, after BA-031 (or a manually seeded `references_document` edge):
  `curl -s localhost:8080/api/v1/nodes/X/backlinks | jq '{out:.references_out|length, in:.referenced_by|length, mentions:.mentions|length}'`

---

## Notes for the implementer
- This completes BA-032 (FR-001/002/004a shipped in 032a; FR-003/004b here). Total nav tools: 3.
- Do not add an `external → references_document` source rule or any test that assumes it (OQ-7). If BA-031 later adds it, `references_out` for `external` nodes populates with **zero code change** here (the query already runs both directions).
- The dashboard "Linked references / Backlinks" panel (spec §9) consumes this endpoint; empty states are expected pre-BA-031.
