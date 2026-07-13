# DAAB Retrieval Token-Efficiency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an MCP consumer retrieve grounded chunk text in one `kg_graph_retrieve` call (opt-in inline snippets) and pull `kg_get_neighbors` at ~1/10th the tokens (a `slim` view), without changing any existing behavior when the new params are absent.

**Architecture:** Two independent, opt-in additions. Part A adds `include_snippet` to `kg_graph_retrieve`: the service fetches chunk `content` for the ≤`result_k` capped results via a new project-scoped store method and inlines it (null-discriminated, rune-safe byte-capped); entity neighbors gain an unconditional `title`. Part B adds a `view=slim` projection to `kg_get_neighbors` (9 frozen fields) plus a sort tie-break for coherent paging. Both plumb one new param through `bridge/schema.go`.

**Tech Stack:** Go (`database/sql`, stdlib `net/http`, functional-option services, table-driven `go test -race`), PostgreSQL 16, MCP stdio bridge.

## Global Constraints

- **Opt-in, default = current behavior.** `include_snippet` default false; `view` default `full`. Absent params → byte-identical current responses (regression-locked).
- **Snippet null-discrimination:** when the flag is on, each result's `snippet` is present as a JSON string OR JSON `null` (content absent/empty) — NEVER `""`, NEVER omitted. When the flag is off, the key is absent. This requires `json.RawMessage` (a `*string` cannot express all three states) — see Task 2.
- **Projection-only invariant:** `include_snippet` MUST NOT change result-set membership, count, or ordering.
- **SECURITY (CRITICAL):** `ChunkContentByIDs` SQL is `WHERE project_id=$1 AND id=ANY($2) AND node_type='document_chunk'`. A cross-project isolation test is a required acceptance gate (this codebase has IDOR history: IMP-009 /files, BA-015).
- **Rune-safe truncation:** the corpus is OCR'd Vietnamese (multi-byte UTF-8). The snippet byte-cap must cut on a rune boundary, never mid-rune (same byte-vs-rune trap as the dedup validator fix).
- **Slim frozen field set (9, exact):** `id, project_id, node_type, title, status, scope, edge_id, edge_type, direction`. No `edge_weight` (neighbors edges carry no weight scalar — verified). Invalid `view` → 400 (fail loud).
- **Bridge invariant:** adding `include_snippet` and `view` extends existing tool schemas; adds **zero** tools. `schemas == routes + localToolNames` preserved. `limit`/`offset` are already bridge-exposed on `kg_get_neighbors` — do not re-add.
- Go: `gofmt`/`goimports`, `fmt.Errorf("ctx: %w", err)`, `go test -race`, table-driven tests.

**Key files & symbols (verified):**
- `internal/store/graph_retrieve.go` — `GraphRetrieveStore`, `EntityNeighbor{NodeID,NodeType,SharedEntityCount,Score}`, `SharedEntityNeighbors` (SQL SELECTs `e.source_id, n.node_type, count, score`).
- `internal/service/graph_retriever.go` — `Result{ChunkID,DocumentID,Score,SeedRelevance,EdgeSimilarity,ViaSeed,HopCount,SectionID}`; `EntityResult{NodeID,NodeType,SharedEntityCount,Score}`; `Bundle{Results,EntityNeighbors,SeedCount,ExpandedCount,DroppedCount,Truncated}`; `RetrieveConfig{SeedK,ResultK,PerDocCap,Mode,SeedEfSearch}`; `GraphRetriever{embedder,seeder,expander,sections,entities}` + `Option`/`WithSections`/`WithEntities`; `Retrieve` builds `results` at step 7 (line ~283–294) then returns `Bundle`; entity map at line ~250–258.
- `internal/handler/graph_retrieve.go` — `HandleRetrieve` request struct (Query/ProjectID/ResultK/SeedK/PerDocumentCap/Mode) → `RetrieveConfig` → `Retrieve` → encode `Bundle`.
- `internal/store/neighbors.go` — `NeighborNode{ID,ProjectID,NodeType,Title,Status,Properties,Scope,Version,CreatedBy,CreatedAt,UpdatedAt,SessionID,EdgeID,EdgeType,Direction,EdgeProperties,EdgeCreatedAt}`; `NeighborResponse{NodeID,Neighbors,TotalCount,Limit,Offset}`; store `ORDER BY edge_created_at DESC LIMIT/OFFSET` (default 50/max 200).
- `internal/handler/neighbors.go` — `HandleGetNeighbors` (parses query+body params, RBAC scope, calls `store.GetNeighbors`, encodes `NeighborResponse`).
- `internal/bridge/schema.go` — `kg_graph_retrieve` schema ~line 1668 (params: query/result_k/project_id); `kg_get_neighbors` schema ~line 1319 (already has limit/offset/include_cross_project). `include_headline`/`mode` precedents exist.
- `cmd/kg-server/main.go:975-979` — `graphRetrieveStore := store.NewGraphRetrieveStore(db)`; `NewGraphRetriever(embedClient, nodeEmbStore, graphRetrieveStore, WithSections(...), WithEntities(...))`.

---

## PART A — `kg_graph_retrieve` inline snippets + entity title

### Task 1: Store — `ChunkContentByIDs` (project+type scoped)

**Files:**
- Modify: `internal/store/graph_retrieve.go` (add method + a `ContentReader`-shaped method)
- Test: `internal/store/graph_retrieve_test.go` (append)

**Interfaces:**
- Produces: `func (s *GraphRetrieveStore) ChunkContentByIDs(ctx context.Context, projectID string, ids []string) (map[string]string, error)` — returns `chunkID → content` for the given ids in `projectID`; ids not found (wrong project, non-chunk, or absent) are simply absent from the map.

- [ ] **Step 1: Write the failing tests (incl. CRITICAL cross-project isolation)**

Append to `graph_retrieve_test.go` (mirror the setup helpers already used by that file's integration tests — inspect the top of the file for the `setupTestDB`/seed helper it uses and reuse it verbatim):

```go
func TestGraphRetrieveStore_ChunkContentByIDs_ReturnsScopedContent(t *testing.T) {
	db := setupTestDB(t)
	ctx := context.Background()
	s := store.NewGraphRetrieveStore(db)

	// Seed a document_chunk with content in project A, and one in project B.
	projA := seedProject(t, db)                 // helper: returns a project id
	projB := seedProject(t, db)
	chunkA := seedChunk(t, db, projA, "alpha content")   // helper: inserts a document_chunk node with properties.content
	chunkB := seedChunk(t, db, projB, "bravo content")

	got, err := s.ChunkContentByIDs(ctx, projA, []string{chunkA, chunkB})
	if err != nil {
		t.Fatalf("ChunkContentByIDs: %v", err)
	}
	// project A id resolves; project B id is filtered out (cross-project isolation).
	if got[chunkA] != "alpha content" {
		t.Errorf("chunkA content: got %q want %q", got[chunkA], "alpha content")
	}
	if _, present := got[chunkB]; present {
		t.Errorf("SECURITY: project B chunk %s leaked into project A result", chunkB)
	}
}

func TestGraphRetrieveStore_ChunkContentByIDs_EmptyIDs(t *testing.T) {
	db := setupTestDB(t)
	s := store.NewGraphRetrieveStore(db)
	got, err := s.ChunkContentByIDs(context.Background(), "p", nil)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if len(got) != 0 {
		t.Errorf("expected empty map for no ids, got %v", got)
	}
}

func TestGraphRetrieveStore_ChunkContentByIDs_NonChunkExcluded(t *testing.T) {
	db := setupTestDB(t)
	ctx := context.Background()
	s := store.NewGraphRetrieveStore(db)
	proj := seedProject(t, db)
	// A non-chunk node (e.g. a document hub) with the same id shape must not resolve.
	hubID := seedDocumentHub(t, db, proj) // helper: inserts a node_type='document'
	got, err := s.ChunkContentByIDs(ctx, proj, []string{hubID})
	if err != nil {
		t.Fatalf("ChunkContentByIDs: %v", err)
	}
	if _, present := got[hubID]; present {
		t.Errorf("non-chunk node %s must not resolve content", hubID)
	}
}
```

> If `graph_retrieve_test.go` has no `seedChunk`/`seedProject`/`seedDocumentHub` helpers, add minimal ones in the test file that INSERT rows directly via `db.ExecContext` (a `document_chunk` node needs `project_id`, `node_type='document_chunk'`, `properties` with a `content` key, `status='active'`). Keep them local to the test file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestGraphRetrieveStore_ChunkContentByIDs -v`
Expected: compile failure — `s.ChunkContentByIDs undefined`.

- [ ] **Step 3: Implement `ChunkContentByIDs`**

Add to `graph_retrieve.go`:

```go
// ChunkContentByIDs returns chunkID → content for the given document_chunk ids
// within projectID. Ids that are absent, belong to another project, or are not
// document_chunk nodes are simply omitted from the result map. The project_id and
// node_type predicates are a defense-in-depth IDOR control on this by-id read path.
func (s *GraphRetrieveStore) ChunkContentByIDs(ctx context.Context, projectID string, ids []string) (map[string]string, error) {
	if len(ids) == 0 {
		return map[string]string{}, nil
	}
	const q = `
		SELECT id, properties->>'content'
		FROM knowledge_nodes
		WHERE project_id = $1
		  AND id = ANY($2)
		  AND node_type = 'document_chunk'`
	rows, err := s.db.QueryContext(ctx, q, projectID, pq.Array(ids))
	if err != nil {
		return nil, fmt.Errorf("chunk content by ids: %w", err)
	}
	defer rows.Close()

	out := make(map[string]string, len(ids))
	for rows.Next() {
		var id string
		var content sql.NullString
		if err := rows.Scan(&id, &content); err != nil {
			return nil, fmt.Errorf("scan chunk content: %w", err)
		}
		if content.Valid {
			out[id] = content.String
		}
	}
	return out, rows.Err()
}
```

> Confirm `sql` and `pq` are already imported in this file (they are — `pq.Array` is used by `SharedEntityNeighbors`; add `database/sql` if not present).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestGraphRetrieveStore_ChunkContentByIDs -race -v`
Expected: PASS (all three, including the cross-project isolation assertion). Needs the test DB (`KG_TEST_DATABASE_URL`).

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/store/graph_retrieve.go internal/store/graph_retrieve_test.go
git commit -m "feat(retrieve): project-scoped ChunkContentByIDs for inline snippets"
```

---

### Task 2: Service — inline snippets on `Retrieve` (null-discriminated, rune-safe cap)

**Files:**
- Modify: `internal/service/graph_retriever.go`
- Modify: `cmd/kg-server/main.go` (wire the content reader)
- Test: `internal/service/graph_retriever_test.go` (append; reuse existing fakes)

**Interfaces:**
- Consumes: `ChunkContentByIDs` (Task 1) via a new `ContentReader` interface.
- Produces: `RetrieveConfig.IncludeSnippet bool`; `Result.Snippet json.RawMessage` (`json:"snippet,omitempty"`) + `Result.SnippetTruncated bool` (`json:"snippet_truncated,omitempty"`); `Option` `WithChunkContent(ContentReader)`.

- [ ] **Step 1: Write the failing service tests**

Append to `graph_retriever_test.go`. Reuse the file's existing fake embedder/seeder/expander (inspect the top of the file). Add a fake content reader:

```go
type fakeContentReader struct {
	byID  map[string]string
	calls int
	ids   [][]string
}

func (f *fakeContentReader) ChunkContentByIDs(_ context.Context, _ string, ids []string) (map[string]string, error) {
	f.calls++
	f.ids = append(f.ids, ids)
	out := map[string]string{}
	for _, id := range ids {
		if c, ok := f.byID[id]; ok {
			out[id] = c
		}
	}
	return out, nil
}
```

Tests (construct the retriever with the existing fakes + `WithChunkContent`; set up seeds so the result set has a known chunk with content and one with missing content):

```go
func TestRetrieve_IncludeSnippet_PopulatesContent(t *testing.T) {
	// ... build embedder/seeder/expander fakes so Retrieve returns >=1 result whose ChunkID = "c1"
	content := &fakeContentReader{byID: map[string]string{"c1": "hello world"}}
	gr := service.NewGraphRetriever(embedder, seeder, expander, service.WithChunkContent(content))

	b, err := gr.Retrieve(ctx, "proj", "q", service.RetrieveConfig{ResultK: 5, PerDocCap: 2, IncludeSnippet: true})
	if err != nil { t.Fatal(err) }
	// snippet for c1 is the JSON string "hello world"
	var found bool
	for _, r := range b.Results {
		if r.ChunkID == "c1" {
			found = true
			if string(r.Snippet) != `"hello world"` {
				t.Errorf("snippet: got %s want %q", r.Snippet, `"hello world"`)
			}
		}
	}
	if !found { t.Fatal("c1 not in results") }
}

func TestRetrieve_IncludeSnippet_NullWhenContentMissing(t *testing.T) {
	// result set includes chunk "c2" with NO entry in the content reader
	content := &fakeContentReader{byID: map[string]string{}} // c2 absent
	gr := service.NewGraphRetriever(embedder, seeder, expander, service.WithChunkContent(content))
	b, _ := gr.Retrieve(ctx, "proj", "q", service.RetrieveConfig{ResultK: 5, PerDocCap: 2, IncludeSnippet: true})
	for _, r := range b.Results {
		if r.ChunkID == "c2" && string(r.Snippet) != "null" {
			t.Errorf("missing content must yield JSON null, got %s", r.Snippet)
		}
	}
}

func TestRetrieve_SnippetFlagOff_NoSnippetKeyAndSameOrder(t *testing.T) {
	content := &fakeContentReader{byID: map[string]string{"c1": "x"}}
	gr := service.NewGraphRetriever(embedder, seeder, expander, service.WithChunkContent(content))
	off, _ := gr.Retrieve(ctx, "proj", "q", service.RetrieveConfig{ResultK: 5, PerDocCap: 2})
	on, _ := gr.Retrieve(ctx, "proj", "q", service.RetrieveConfig{ResultK: 5, PerDocCap: 2, IncludeSnippet: true})
	// projection-only: identical chunk order
	if len(off.Results) != len(on.Results) { t.Fatal("membership changed") }
	for i := range off.Results {
		if off.Results[i].ChunkID != on.Results[i].ChunkID {
			t.Errorf("order changed at %d: %s vs %s", i, off.Results[i].ChunkID, on.Results[i].ChunkID)
		}
		if off.Results[i].Snippet != nil {
			t.Errorf("flag off must not set snippet")
		}
	}
	// batch-once: content reader called exactly once for the on-run
	if content.calls != 1 {
		t.Errorf("expected 1 batch content call, got %d", content.calls)
	}
}

func TestRetrieve_SnippetOversizedIsRuneSafeTruncated(t *testing.T) {
	big := strings.Repeat("á", 5000) // multi-byte runes, > maxSnippetBytes
	content := &fakeContentReader{byID: map[string]string{"c1": big}}
	gr := service.NewGraphRetriever(embedder, seeder, expander, service.WithChunkContent(content))
	b, _ := gr.Retrieve(ctx, "proj", "q", service.RetrieveConfig{ResultK: 5, PerDocCap: 2, IncludeSnippet: true})
	for _, r := range b.Results {
		if r.ChunkID == "c1" {
			if !r.SnippetTruncated { t.Error("expected snippet_truncated=true") }
			// snippet must be valid JSON (rune-safe cut → valid UTF-8 → valid JSON string)
			var s string
			if err := json.Unmarshal(r.Snippet, &s); err != nil {
				t.Errorf("truncated snippet is not valid JSON/UTF-8: %v", err)
			}
			if len(r.Snippet) > maxSnippetJSONBudget { t.Error("snippet exceeds cap") }
		}
	}
}
```

> `maxSnippetJSONBudget` in the last assertion is illustrative; assert `len([]byte(s)) <= maxSnippetBytes` against the decoded string instead if simpler. The load-bearing assertion is that `json.Unmarshal` succeeds (proves rune-safe).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/service/ -run TestRetrieve_IncludeSnippet -v` (and the other two names)
Expected: compile failure — `WithChunkContent`, `RetrieveConfig.IncludeSnippet`, `Result.Snippet` undefined.

- [ ] **Step 3: Implement the service change**

In `graph_retriever.go`:

a. Add to `RetrieveConfig`:
```go
	IncludeSnippet bool // when true, inline each result's chunk content as `snippet`
```

b. Add to `Result` (after `SectionID`):
```go
	Snippet          json.RawMessage `json:"snippet,omitempty"`           // present only when IncludeSnippet; JSON string or null
	SnippetTruncated bool            `json:"snippet_truncated,omitempty"` // true only when the snippet was byte-capped
```

c. Add the interface, option, field, and constant:
```go
const maxSnippetBytes = 4096 // defensive cap against a pathological oversized chunk content

// ContentReader fetches chunk content by id for snippet inlining.
type ContentReader interface {
	ChunkContentByIDs(ctx context.Context, projectID string, ids []string) (map[string]string, error)
}

// WithChunkContent enables include_snippet by wiring a content reader.
func WithChunkContent(cr ContentReader) Option {
	return func(g *GraphRetriever) { g.content = cr }
}
```
Add `content ContentReader` to the `GraphRetriever` struct.

d. A rune-safe truncation helper:
```go
// truncateRunes returns s truncated to at most max bytes without splitting a rune.
func truncateRunes(s string, max int) string {
	if len(s) <= max {
		return s
	}
	// back up to a rune boundary at or below max.
	cut := max
	for cut > 0 && !utf8.RuneStart(s[cut]) {
		cut--
	}
	return s[:cut]
}
```
(add `"unicode/utf8"` and `"encoding/json"` imports if not present — `encoding/json` is already used.)

e. After step 7 builds `results`, before `return Bundle{...}`:
```go
	// Snippet inlining (projection-only): fetch content for the ≤ResultK capped
	// results in one batch, after the cap, so it never alters membership/order.
	if cfg.IncludeSnippet && gr.content != nil && len(results) > 0 {
		ids := make([]string, len(results))
		for i := range results {
			ids[i] = results[i].ChunkID
		}
		contentByID, cerr := gr.content.ChunkContentByIDs(ctx, projectID, ids)
		if cerr != nil {
			return Bundle{}, fmt.Errorf("snippet content: %w", cerr)
		}
		for i := range results {
			c, ok := contentByID[results[i].ChunkID]
			if !ok || c == "" {
				results[i].Snippet = json.RawMessage("null")
				continue
			}
			if len(c) > maxSnippetBytes {
				c = truncateRunes(c, maxSnippetBytes)
				results[i].SnippetTruncated = true
			}
			enc, err := json.Marshal(c)
			if err != nil {
				return Bundle{}, fmt.Errorf("marshal snippet: %w", err)
			}
			results[i].Snippet = enc
		}
	}
```

- [ ] **Step 4: Wire the content reader in main.go**

At `cmd/kg-server/main.go:976`, add the option:
```go
	graphRetriever := service.NewGraphRetriever(embedClient, nodeEmbStore, graphRetrieveStore,
		service.WithSections(graphRetrieveStore),
		service.WithEntities(graphRetrieveStore),
		service.WithChunkContent(graphRetrieveStore))
```
(`graphRetrieveStore` now also satisfies `ContentReader` via Task 1.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/service/ -run TestRetrieve -race -v`
Expected: PASS (fidelity, null, flag-off-parity+batch-once, oversized rune-safe).

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.go
git add internal/service/graph_retriever.go cmd/kg-server/main.go internal/service/graph_retriever_test.go
git commit -m "feat(retrieve): include_snippet inlines chunk content (null-discriminated, rune-safe cap)"
```

---

### Task 3: Entity neighbors gain `title`

**Files:**
- Modify: `internal/store/graph_retrieve.go` (`EntityNeighbor` + `SharedEntityNeighbors` SQL)
- Modify: `internal/service/graph_retriever.go` (`EntityResult` + map)
- Test: `internal/store/graph_retrieve_test.go` and/or `internal/service/graph_retriever_test.go`

**Interfaces:**
- Produces: `EntityNeighbor.Title string`; `EntityResult.Title string` (`json:"title"`).

- [ ] **Step 1: Write the failing test**

Add a service-level assertion (entity/hybrid mode) that each `EntityResult` carries a non-empty `Title`. Reuse the entity fake if the service test file has one; otherwise assert at the store level that `SharedEntityNeighbors` returns `Title`:

```go
func TestSharedEntityNeighbors_ReturnsTitle(t *testing.T) {
	db := setupTestDB(t)
	ctx := context.Background()
	s := store.NewGraphRetrieveStore(db)
	// seed: two sections mentioning a shared concept; a neighbor node with a known title.
	proj, origin, neighborTitle := seedSharedEntityFixture(t, db) // helper returns ids + expected title
	out, err := s.SharedEntityNeighbors(ctx, proj, []string{origin})
	if err != nil { t.Fatal(err) }
	if len(out) == 0 { t.Fatal("expected >=1 neighbor") }
	if out[0].Title != neighborTitle {
		t.Errorf("title: got %q want %q", out[0].Title, neighborTitle)
	}
}
```

> If seeding a full mentions-graph fixture is heavy, prefer the service-level test with a fake `EntityExpander` returning an `EntityNeighbor` with `Title` set, and assert the mapping copies it to `EntityResult.Title`. Pick whichever the existing test file already supports.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestSharedEntityNeighbors_ReturnsTitle -v`
Expected: FAIL — `out[0].Title undefined` / empty.

- [ ] **Step 3: Implement**

a. `EntityNeighbor` — add `Title string`.

b. `SharedEntityNeighbors` SQL: add `n.title` to the SELECT and GROUP BY:
```sql
		SELECT e.source_id AS node_id,
		       n.node_type,
		       n.title,
		       count(DISTINCT e.target_id) AS shared,
		       COALESCE(sum(ln((SELECT n FROM total) / df.df)), 0) AS score
		...
		GROUP BY e.source_id, n.node_type, n.title
		ORDER BY score DESC, shared DESC
		LIMIT 50
```
and update the scan: `rows.Scan(&n.NodeID, &n.NodeType, &n.Title, &n.SharedEntityCount, &n.Score)`.

c. `EntityResult` — add `Title string `json:"title"``.

d. Service map (line ~252):
```go
			entityNeighbors[i] = EntityResult{
				NodeID:            n.NodeID,
				NodeType:          n.NodeType,
				Title:             n.Title,
				SharedEntityCount: n.SharedEntityCount,
				Score:             n.Score,
			}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/store/ ./internal/service/ -run "SharedEntityNeighbors|Retrieve" -race -v`
Expected: PASS; existing entity/hybrid tests still green.

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/store/graph_retrieve.go internal/service/graph_retriever.go internal/store/graph_retrieve_test.go internal/service/graph_retriever_test.go
git commit -m "feat(retrieve): entity_neighbors carry title (kills entity-mode round-trip)"
```

---

### Task 4: Handler + bridge — expose `include_snippet`

**Files:**
- Modify: `internal/handler/graph_retrieve.go`
- Modify: `internal/bridge/schema.go` (`kg_graph_retrieve` schema ~line 1668)
- Test: `internal/handler/graph_retrieve_test.go` (append); `internal/bridge/schema_test.go` (extend)

**Interfaces:**
- Consumes: `RetrieveConfig.IncludeSnippet` (Task 2).
- Produces: request field `include_snippet` on `POST /api/v1/retrieve/graph` and MCP tool `kg_graph_retrieve`.

- [ ] **Step 1: Write the failing handler test**

**Note (verified):** `GraphRetrieveHandler` holds a **concrete** `*service.GraphRetriever` — there is NO fake-retriever seam. `graph_retrieve_test.go` already builds a *real* retriever from fakes (`fakeQueryEmbedder`, `fakeSeedSearcher`, `fakeExpander`, `fakeSectionExpander`, `fakeEntityExpander`) via a `newGraphRetrieveMux`-style helper (line ~89) and posts JSON via `postGraphRetrieve` (line ~95). Test through the response, not a captured cfg.

Append to `graph_retrieve_test.go`. Add the `fakeContentReader` from Task 2 (or a local copy) and build a retriever whose seeder returns a known chunk id that the content fake maps:

```go
func TestGraphRetrieve_IncludeSnippet_InlinesContent(t *testing.T) {
	// Reuse the file's existing fakes. Configure fakeSeedSearcher to return one
	// SearchResult whose ID is "c1" (match the fake's actual field names), and a
	// content fake mapping c1 -> "hello". Then POST include_snippet:true.
	embedder := &fakeQueryEmbedder{ /* vec as the existing helper sets it */ }
	seeder := &fakeSeedSearcher{ /* results: []store.SearchResult{{ID:"c1", Rank:0.9, Properties: []byte(`{"document_id":"d1"}`)}} */ }
	expander := &fakeExpander{}
	content := &fakeContentReader{byID: map[string]string{"c1": "hello"}}

	retriever := service.NewGraphRetriever(embedder, seeder, expander, service.WithChunkContent(content))
	h := NewGraphRetrieveHandler(retriever, logger())
	mux := http.NewServeMux()
	h.RegisterRoutes(mux)

	rec := postGraphRetrieve(mux, `{"query":"q","project_id":"p","include_snippet":true}`)
	if rec.Code != http.StatusOK {
		t.Fatalf("code %d: %s", rec.Code, rec.Body.String())
	}
	var got service.Bundle
	if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	var seen bool
	for _, r := range got.Results {
		if r.ChunkID == "c1" {
			seen = true
			if string(r.Snippet) != `"hello"` {
				t.Errorf("snippet: got %s want %q", r.Snippet, `"hello"`)
			}
		}
	}
	if !seen {
		t.Fatal("c1 not in results")
	}
}

func TestGraphRetrieve_DefaultNoSnippetKey(t *testing.T) {
	// Same setup, body WITHOUT include_snippet → response results carry no snippet key.
	// Assert the raw JSON body does not contain "snippet".
	// (build retriever+mux as above; content fake may be nil-safe since flag is off)
	// ... post `{"query":"q","project_id":"p"}` ...
	// if strings.Contains(rec.Body.String(), "\"snippet\"") { t.Error("default must omit snippet") }
}
```

> Match the exact fake field names by copying how the existing `newGraphRetrieveMux` helper constructs `fakeSeedSearcher`/`fakeQueryEmbedder` (open the file). The load-bearing assertions: `snippet == "hello"` when on, and no `snippet` key when off.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestHandleRetrieve_IncludeSnippet -v`
Expected: FAIL — flag not read.

- [ ] **Step 3: Add the request field + config mapping**

In `HandleRetrieve`, add to the anonymous request struct:
```go
		IncludeSnippet bool `json:"include_snippet"`
```
and after building `cfg`:
```go
	cfg.IncludeSnippet = req.IncludeSnippet
```

- [ ] **Step 4: Add the bridge schema param + test**

In `bridge/schema.go`, inside the `kg_graph_retrieve` `Properties` map (~line 1690), add:
```go
			"include_snippet": {
				Type:        TypeBoolean,
				Required:    false,
				Description: "Inline the full chunk content as `snippet` on each result, eliminating a follow-up kg_search_chunks call.",
			},
```
Extend `schema_test.go` (or the bridge integration test) to assert `kg_graph_retrieve` schema now contains `include_snippet` and that the tool count / `schemas == routes + localToolNames` invariant is unchanged (no new tool). Follow the existing schema-count test pattern.

- [ ] **Step 5: Run tests + build**

Run: `cd ennam.kg.go && go test ./internal/handler/ ./internal/bridge/ -run "Retrieve|Schema|GraphRetrieve" -race -v && go build ./...`
Expected: PASS + clean build.

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.go
git add internal/handler/graph_retrieve.go internal/bridge/schema.go internal/handler/graph_retrieve_test.go internal/bridge/schema_test.go
git commit -m "feat(retrieve): expose include_snippet on handler + kg_graph_retrieve bridge tool"
```

---

## PART B — `kg_get_neighbors` slim view + paging tie-break

### Task 5: Store — stable paging tie-break

**Files:**
- Modify: `internal/store/neighbors.go` (the `ORDER BY`)
- Test: `internal/store/neighbors_test.go` (append)

**Interfaces:**
- Produces: deterministic neighbor ordering `edge_created_at DESC, edge_id ASC` so `limit`/`offset` pages don't repeat/skip under tied timestamps.

- [ ] **Step 1: Write the failing test**

Append an integration test that seeds ≥3 neighbors with the SAME `edge_created_at`, pages with `limit=2 offset=0` then `limit=2 offset=2`, and asserts the union has no duplicate `edge_id` and covers all rows:

```go
func TestGetNeighbors_StablePagingUnderTiedTimestamps(t *testing.T) {
	db := setupTestDB(t)
	ctx := context.Background()
	s := store.NewNeighborStore(db)
	hub, _ := seedNeighborsSameTimestamp(t, db, 3) // 3 edges, identical edge_created_at
	p1, _ := s.GetNeighbors(ctx, store.NeighborParams{NodeID: hub, ProjectID: proj, Limit: 2, Offset: 0})
	p2, _ := s.GetNeighbors(ctx, store.NeighborParams{NodeID: hub, ProjectID: proj, Limit: 2, Offset: 2})
	seen := map[string]bool{}
	for _, n := range append(p1.Neighbors, p2.Neighbors...) {
		if seen[n.EdgeID] { t.Errorf("edge %s appeared twice across pages", n.EdgeID) }
		seen[n.EdgeID] = true
	}
	if len(seen) != 3 { t.Errorf("expected 3 distinct edges across pages, got %d", len(seen)) }
}
```

- [ ] **Step 2: Run to verify it fails (flaky/ordering)**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestGetNeighbors_StablePaging -count=5 -v`
Expected: fails or flakes — without a tie-break, tied timestamps make offset paging non-deterministic.

- [ ] **Step 3: Add the tie-break**

In `neighbors.go`, change the ORDER BY (line ~334) from `ORDER BY edge_created_at DESC` to:
```sql
ORDER BY edge_created_at DESC, edge_id ASC
```
> Verify the exact selected alias for the edge id in the query (it exposes `EdgeID`; the column is likely `e.id AS edge_id`). Use that alias/column in the ORDER BY so it references the edge, not a node.

- [ ] **Step 4: Run to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestGetNeighbors -race -count=5 -v`
Expected: PASS consistently across all 5 runs.

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/store/neighbors.go internal/store/neighbors_test.go
git commit -m "fix(neighbors): deterministic paging tie-break (edge_id) under tied timestamps"
```

---

### Task 6: Handler + bridge — `view=slim`

**Files:**
- Modify: `internal/handler/neighbors.go`
- Modify: `internal/bridge/schema.go` (`kg_get_neighbors` schema ~line 1319)
- Test: `internal/handler/neighbors_test.go` (append); `internal/bridge/schema_test.go`

**Interfaces:**
- Produces: request param `view` (`full`|`slim`, default `full`) on `GET/POST /api/v1/nodes/{id}/neighbors` and `kg_get_neighbors`; slim response = 9 frozen fields per neighbor.

**Note (verified):** `NeighborHandler.store` is a **concrete** `*store.NeighborStore` — there is NO fake-store seam, and the existing `neighbors_test.go` tests pass `NewNeighborHandler(nil, logger)` and only exercise **validation paths** (they return before the store call). So the slim happy-path cannot be handler-unit-tested with a fake. Instead: **extract the slim projection as a pure function** and unit-test it directly; test `view` validation via the existing nil-store validation style; cover the live full-vs-slim response in Task 7 smoke.

- [ ] **Step 1: Write the failing tests**

Append to `neighbors_test.go`:

```go
// Pure-function test — the slim projection, independent of handler/store wiring.
func TestToSlimNeighborResponse_ExactFields(t *testing.T) {
	full := store.NeighborResponse{
		NodeID: "n1", TotalCount: 1, Limit: 50, Offset: 0,
		Neighbors: []store.NeighborNode{{
			ID: "x", ProjectID: "p", NodeType: "concept", Title: "T", Status: "active",
			Scope: "project", Version: 3, CreatedBy: "u", EdgeID: "e1", EdgeType: "about",
			Direction: "outgoing", Properties: json.RawMessage(`{"big":"blob"}`),
			EdgeProperties: json.RawMessage(`{"w":1}`),
		}},
	}
	slim := toSlimNeighborResponse(full)

	// Round-trip to JSON and assert EXACT key set on the neighbor.
	b, _ := json.Marshal(slim.Neighbors[0])
	var m map[string]json.RawMessage
	_ = json.Unmarshal(b, &m)
	want := map[string]bool{
		"id": true, "project_id": true, "node_type": true, "title": true, "status": true,
		"scope": true, "edge_id": true, "edge_type": true, "direction": true,
	}
	for k := range m {
		if !want[k] { t.Errorf("slim neighbor has unexpected key %q", k) }
	}
	for k := range want {
		if _, ok := m[k]; !ok { t.Errorf("slim neighbor missing key %q", k) }
	}
	// heavy fields must be gone
	if _, ok := m["properties"]; ok { t.Error("slim must drop properties") }
	if _, ok := m["edge_properties"]; ok { t.Error("slim must drop edge_properties") }
	if _, ok := m["created_at"]; ok { t.Error("slim must drop timestamps") }
	// envelope fields preserved
	if slim.NodeID != "n1" || slim.TotalCount != 1 || slim.Limit != 50 {
		t.Errorf("envelope not preserved: %+v", slim)
	}
}

// Validation test — invalid view returns 400 BEFORE any store call (nil store is safe).
func TestHandleGetNeighbors_InvalidView_400(t *testing.T) {
	logger := slog.Default()
	h := NewNeighborHandler(nil, logger)
	mux := http.NewServeMux()
	h.RegisterRoutes(mux)
	req := httptest.NewRequest("GET", "/api/v1/nodes/n1/neighbors?project_id=p&view=garbage", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Errorf("invalid view must 400, got %d: %s", rec.Code, rec.Body.String())
	}
}
```

> Copy the exact request/router setup from an existing `neighbors_test.go` validation test (e.g. `TestHandleGetNeighbors_ValidEdgeTypes`) so the node-id path value is wired the same way. The invalid-view check MUST run before `h.store.GetNeighbors`, so nil store never panics.

- [ ] **Step 2: Run to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestHandleGetNeighbors_View -v`
Expected: FAIL — `view` ignored; slim keys present in full form; invalid view returns 200.

- [ ] **Step 3: Implement the slim projection**

In `neighbors.go`:

a. Parse `view` for **both** transports, matching how the handler already dual-sources params (GET → `r.URL.Query()`, POST → decoded JSON body). Add a `View string \`json:"view,omitempty"\`` field to the request struct the POST branch decodes into, and in the GET branch read `r.URL.Query().Get("view")`. Then normalize + validate once, before the store call:
```go
	view := strings.TrimSpace(req.View) // req.View populated from body (POST) or query (GET)
	if view == "" { view = "full" }
	if view != "full" && view != "slim" {
		errorResponse(w, http.StatusBadRequest, "invalid view: must be 'full' or 'slim'")
		return
	}
```
Place the validation among the existing early validations (status/edge_types/node_types), so an invalid `view` returns 400 before `h.store.GetNeighbors` (nil-store-safe, matching the existing validation tests).

b. Define the slim DTO + **pure projection function** (in `neighbors.go`; the function is what the Step-1 unit test targets):
```go
type slimNeighbor struct {
	ID        string `json:"id"`
	ProjectID string `json:"project_id"`
	NodeType  string `json:"node_type"`
	Title     string `json:"title"`
	Status    string `json:"status"`
	Scope     string `json:"scope"`
	EdgeID    string `json:"edge_id"`
	EdgeType  string `json:"edge_type"`
	Direction string `json:"direction"`
}

type slimNeighborResponse struct {
	NodeID     string         `json:"node_id"`
	Neighbors  []slimNeighbor `json:"neighbors"`
	TotalCount int            `json:"total_count"`
	Limit      int            `json:"limit"`
	Offset     int            `json:"offset"`
}

// toSlimNeighborResponse projects a full NeighborResponse to the frozen 9-field
// slim shape, dropping properties/edge_properties/timestamps/version/created_by/session_id.
func toSlimNeighborResponse(resp store.NeighborResponse) slimNeighborResponse {
	out := slimNeighborResponse{
		NodeID: resp.NodeID, TotalCount: resp.TotalCount, Limit: resp.Limit, Offset: resp.Offset,
		Neighbors: make([]slimNeighbor, len(resp.Neighbors)),
	}
	for i, n := range resp.Neighbors {
		out.Neighbors[i] = slimNeighbor{
			ID: n.ID, ProjectID: n.ProjectID, NodeType: n.NodeType, Title: n.Title,
			Status: n.Status, Scope: n.Scope, EdgeID: n.EdgeID, EdgeType: n.EdgeType, Direction: n.Direction,
		}
	}
	return out
}
```

c. After `resp, err := h.store.GetNeighbors(...)` succeeds, branch on `view`:
```go
	if view == "slim" {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(toSlimNeighborResponse(resp))
		return
	}
	// existing full-response encode unchanged
```

- [ ] **Step 4: Add the bridge schema param + test**

In `bridge/schema.go`, inside the `kg_get_neighbors` `Properties` map (~line 1377, after `offset`), add:
```go
			"view": {
				Type:        TypeString,
				Required:    false,
				Description: "Response verbosity: 'full' (default, all fields) or 'slim' (id, project_id, node_type, title, status, scope, edge_id, edge_type, direction).",
				Enum:        []string{"full", "slim"},
			},
```
Extend `schema_test.go` to assert `kg_get_neighbors` now has `view` and the tool-count invariant is unchanged.

- [ ] **Step 5: Run tests + payload-delta check + build**

Run: `cd ennam.kg.go && go test ./internal/handler/ ./internal/bridge/ -run "Neighbors|Schema" -race -v && go build ./...`
Expected: PASS (slim exactness, full regression, invalid-400, bridge schema) + clean build.

Optional payload-delta assertion (add to the slim test or a separate one): marshal a 30-heavy-neighbor fake in both views and assert `len(slimBody) < len(fullBody)/5`.

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.go
git add internal/handler/neighbors.go internal/bridge/schema.go internal/handler/neighbors_test.go internal/bridge/schema_test.go
git commit -m "feat(neighbors): view=slim projection on handler + kg_get_neighbors bridge tool"
```

---

### Task 7: Rebuild + live smoke (both parts)

**Files:** none (verification only; throwaway script in scratchpad).

- [ ] **Step 1: Rebuild + restart the affected services**

```bash
cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace
docker compose up -d --build kg-server kg-bridge
docker compose ps
```

- [ ] **Step 2: Smoke `include_snippet`**

`POST /api/v1/retrieve/graph` with `{"query":"...","project_id":"592c7ff7-...","include_snippet":true}` against a Cảng key. Assert: each result has a `snippet` (string or explicit null), same result ids/order as the same call with the flag off, and entity mode results carry `title`.

- [ ] **Step 3: Smoke `view=slim`**

`GET /api/v1/nodes/{some-concept-id}/neighbors?project_id=592c7ff7-...&view=slim` → assert only the 9 fields, and measure the byte size vs `view=full` on the same node (expect a large drop).

- [ ] **Step 4: Checkpoint**

`mcp__serena__write_memory("checkpoint/<agent>-2026-07-13", …)` recording smoke results; update `mem:backlog/daab-retrieval-quality-gaps-postfix` to mark gap #3 resolved.

---

## Self-Review

**Spec coverage:** Part A §3 (include_snippet) → Tasks 1 (store), 2 (service), 4 (handler+bridge); `section_id` already surfaced (no task needed — verified `omitempty` serialization); `EntityResult.title` §3.1 → Task 3; byte-cap + `snippet_truncated` → Task 2. Part B §4 (slim) → Task 6; tie-break §4.2 → Task 5; pagination already done (no task, per §6). Bridge invariant §2 → Tasks 4 & 6 schema tests. Security §5 → Task 1 cross-project isolation test. Success criteria 1-7 → Tasks 2/4 (1-3), 1 (4), 6 (5), 5 (6), 2/4/6 regression locks (7).

**Placeholder scan:** No TBDs. Test helper names (`seedChunk`, `newNeighborHarness`, `fakeRetriever`, etc.) are flagged as "reuse the file's existing harness or add a minimal local one" — deliberate adaptation points, not deferrals, because the exact fixtures live in files the implementer will open.

**Type consistency:** `ChunkContentByIDs(ctx, projectID, ids) (map[string]string, error)` identical across store (T1), `ContentReader` iface + service call (T2), fake (T2). `RetrieveConfig.IncludeSnippet` set in handler (T4), read in service (T2). `Result.Snippet json.RawMessage` / `SnippetTruncated bool` consistent (T2). `EntityNeighbor.Title`→`EntityResult.Title` (T3). Slim 9-field set identical in DTO (T6), test (T6), and bridge description (T6) — matches spec's frozen list exactly. `view` enum `full|slim` consistent across handler (T6), bridge (T6).

**Backward-compat locks:** flag-off snippet parity (T2 Step 1), full-view regression (T6 Step 1), bridge tool-count invariant (T4, T6). Rune-safe truncation explicitly tested (T2) — guards the Vietnamese UTF-8 trap.
