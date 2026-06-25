# BA-033 Slice 1 — Cross-Document Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. TDD: failing test → run-fail → implement → run-pass → commit.

**Goal:** Build cross-document chunk-similarity links (`similar_to` edges) and a `kg_graph_retrieve` tool that expands a hybrid-search seed one hop over those links to surface cross-document evidence a flat search misses.

**Architecture:** Three isolated units. (1) **ChunkLinker** — an admin-triggered batch job that, per embedded `document_chunk`, runs an hnsw ANN query for cross-document similar chunks and upserts `similar_to` edges. (2) **GraphRetriever** — query-time: hybrid-search seed → 1-hop `similar_to` JOIN → multiplicative rank with per-document cap. (3) **`kg_graph_retrieve`** — read-only HTTP endpoint + MCP tool over GraphRetriever. No recursion, no LLM, no entity bridge (deferred).

**Tech Stack:** Go (stdlib `net/http`, `database/sql`, no ORM), PostgreSQL + pgvector (hnsw cosine), existing `NodeEmbeddingStore.SemanticSearch` / `EdgeStore` / `SearchHandler`, kg-bridge MCP (stdio).

**Spec:** `docs/superpowers/specs/2026-06-24-ba033-slice1-cross-document-retrieval-design.md`

## Global Constraints

- **Distinct edge type `similar_to`** for chunk↔chunk similarity (NOT `related_to(origin=…)`). Overrides BA-033 OQ-033-3.
- **No DB migration for the edge type** — `knowledge_edges.edge_type` has no DB CHECK (migration 000052); `similar_to` is added via a **config.yaml Gate-1 whitelist rule only**.
- **Cross-document only** — never link two chunks with the same `properties.document_id`.
- **Embedded chunks only** — only `document_chunk` nodes with a row in `knowledge_node_embeddings` are linkable (currently ~60/131 — log coverage every run).
- **Read tools never mutate.** Linking is internal/admin-class; retrieval is read-class.
- **Project-scoped** — all queries filter `project_id`; never cross projects.
- **Edge constraints (existing):** `UNIQUE(source_id, target_id, edge_type)`, `CHECK(source_id != target_id)` — canonical-order each pair (lexicographically smaller UUID as `source_id`).
- **Go conventions:** `fmt.Errorf("ctx: %w", err)`, `log/slog`, table-driven tests, `make -C ennam.kg.go test lint build` green per task.

---

## File Structure

**Go (`ennam.kg.go/`):**
- `config/config.yaml` (modify) — add Gate-1 rule `document_chunk → similar_to → document_chunk`.
- `internal/store/chunk_link.go` (new, +`_test.go`) — `SimilarChunksCrossDoc` (ANN) + `UpsertSimilarToEdge`.
- `internal/service/chunk_linker.go` (new, +`_test.go`) — per-chunk linking loop, canonical ordering, coverage + histogram logging.
- `internal/handler/graphrag_link.go` (new, +`_test.go`) — `POST /api/v1/internal/graphrag/link`.
- `internal/store/graph_retrieve.go` (new, +`_test.go`) — `ExpandSimilarTo` (1-hop JOIN surfacing `similarity`).
- `internal/service/graph_retriever.go` (new, +`_test.go`) — seed + expand + rank (blend, dedup, tie-break, per-doc cap).
- `internal/handler/graph_retrieve.go` (new, +`_test.go`) — `POST /api/v1/retrieve/graph`.
- `cmd/kg-server/main.go` (modify) — wire the two new handlers.
- `internal/bridge/` (modify, + test) — register `kg_graph_retrieve` routed MCP tool.

**Eval (`ennam.kg.python/` or a Go integration test):**
- `internal/integration/ba033_marginal_eval_test.go` (new, `//go:build integration`) — the `G \ B` ship-gate harness.

---

## Task 1: Gate-1 whitelist rule for `similar_to`

**Files:**
- Modify: `config/config.yaml` (edge_whitelist section, near the `related_to` rules ~line 1022)
- Test: `internal/validation/` existing Gate-1 test (add a case) or `internal/service/link_test.go`

**Interfaces:**
- Produces: a Gate-1 rule permitting `document_chunk --similar_to--> document_chunk` (same-project).

- [ ] **Step 1: Write the failing test** — assert the edge whitelist admits `similar_to` between two `document_chunk` and rejects it to a non-chunk target. Add to the existing Gate-1/edge-whitelist test (mirror how `related_to` rules are tested).

```go
func TestEdgeWhitelist_SimilarToChunkPair(t *testing.T) {
    wl := loadEdgeWhitelistFromConfig(t) // existing helper / load config.yaml
    if !wl.Allows("document_chunk", "similar_to", "document_chunk") {
        t.Fatal("similar_to chunk->chunk must be whitelisted")
    }
    if wl.Allows("document_chunk", "similar_to", "person") {
        t.Fatal("similar_to must not target non-chunk types")
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `make -C ennam.kg.go test ARGS="-run TestEdgeWhitelist_SimilarToChunkPair"` (or `go test ./internal/validation/ -run TestEdgeWhitelist_SimilarToChunkPair -v`)
Expected: FAIL (rule absent).

- [ ] **Step 3: Add the rule to `config/config.yaml`** (mirror the `related_to` block format at ~line 1022):

```yaml
  - source: document_chunk
    relationship: similar_to
    targets: [document_chunk]
    allow_cross_project: false
```

- [ ] **Step 4: Run to verify it passes** — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add config/config.yaml internal/validation
git -C ennam.kg.go commit -m "feat(ba033-s1): Gate-1 whitelist rule for similar_to chunk pairs"
```

---

## Task 2: Store — cross-document similar-chunk ANN query

**Files:**
- Create: `internal/store/chunk_link.go`, `internal/store/chunk_link_test.go`

**Interfaces:**
- Consumes: `NodeEmbeddingStore` pattern (`internal/store/node_embedding.go:101` `SemanticSearch`) — mirror its hnsw query but with `node_type='document_chunk'`, **`document_id <> $`** (exclude), and return the source chunk's neighbours by cosine.
- Produces:
  ```go
  type ChunkNeighbor struct { NodeID string; Similarity float64 }
  // SimilarChunksCrossDoc returns up to `limit` chunks in OTHER documents than docID,
  // ordered by cosine desc, for the embedded chunk chunkID in project projectID.
  func (s *ChunkLinkStore) SimilarChunksCrossDoc(ctx context.Context, projectID, chunkID, docID string, limit int) ([]ChunkNeighbor, error)
  ```

- [ ] **Step 1: Write the failing test** (test DB; mirror existing embedding-store test setup):

```go
func TestSimilarChunksCrossDoc(t *testing.T) {
    db := testDB(t) // existing helper
    st := NewChunkLinkStore(db)
    // seed: chunk A in doc1, chunk B in doc2 (near A), chunk C in doc1 (near A)
    seedChunkWithEmbedding(t, db, proj, "A", "doc1", vecNear)
    seedChunkWithEmbedding(t, db, proj, "B", "doc2", vecNear)
    seedChunkWithEmbedding(t, db, proj, "C", "doc1", vecNear)
    got, err := st.SimilarChunksCrossDoc(ctx, proj, "A", "doc1", 10)
    if err != nil { t.Fatal(err) }
    // B (other doc) returned; C (same doc) excluded; A (self) excluded
    if !containsID(got, "B") || containsID(got, "C") || containsID(got, "A") {
        t.Fatalf("cross-doc only failed: %+v", got)
    }
}
```

- [ ] **Step 2: Run to verify it fails** — `go test ./internal/store/ -run TestSimilarChunksCrossDoc -v` → FAIL (undefined).

- [ ] **Step 3: Implement** `chunk_link.go` mirroring `SemanticSearch` (node_embedding.go:101–140), changing the doc filter from `= $` to `<> $` and pinning `node_type='document_chunk'`:

```go
package store

import ("context"; "database/sql"; "fmt")

type ChunkLinkStore struct{ db *sql.DB }
func NewChunkLinkStore(db *sql.DB) *ChunkLinkStore { return &ChunkLinkStore{db: db} }

type ChunkNeighbor struct { NodeID string; Similarity float64 }

func (s *ChunkLinkStore) SimilarChunksCrossDoc(ctx context.Context, projectID, chunkID, docID string, limit int) ([]ChunkNeighbor, error) {
    // embedding of the source chunk is read by sub-select to keep one round-trip
    const q = `
      SELECT n.id, (1 - (e.embedding <=> src.embedding))::float8 AS sim
      FROM knowledge_node_embeddings e
      JOIN knowledge_nodes n ON n.id = e.node_id AND n.node_type = 'document_chunk' AND n.status='active'
      JOIN knowledge_node_embeddings src ON src.node_id = $2
      WHERE e.project_id = $1
        AND n.id <> $2
        AND n.properties->>'document_id' <> $3
      ORDER BY e.embedding <=> src.embedding
      LIMIT $4`
    rows, err := s.db.QueryContext(ctx, q, projectID, chunkID, docID, limit)
    if err != nil { return nil, fmt.Errorf("similar chunks cross-doc: %w", err) }
    defer rows.Close()
    var out []ChunkNeighbor
    for rows.Next() {
        var c ChunkNeighbor
        if err := rows.Scan(&c.NodeID, &c.Similarity); err != nil { return nil, fmt.Errorf("scan: %w", err) }
        out = append(out, c)
    }
    return out, rows.Err()
}
```

- [ ] **Step 4: Run to verify it passes** — `go test ./internal/store/ -run TestSimilarChunksCrossDoc -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/store/chunk_link.go internal/store/chunk_link_test.go
git -C ennam.kg.go commit -m "feat(ba033-s1): cross-document similar-chunk ANN store query"
```

---

## Task 3: Store — upsert `similar_to` edge (idempotent)

**Files:**
- Modify: `internal/store/chunk_link.go`, `internal/store/chunk_link_test.go`

**Interfaces:**
- Consumes: `knowledge_edges` schema (UNIQUE(source_id,target_id,edge_type)).
- Produces:
  ```go
  // UpsertSimilarToEdge inserts or refreshes a similar_to edge with {similarity} in properties.
  // Caller MUST pass canonical-ordered ids (sourceID < targetID lexicographically).
  func (s *ChunkLinkStore) UpsertSimilarToEdge(ctx context.Context, projectID, sourceID, targetID string, similarity float64) error
  ```

- [ ] **Step 1: Write the failing test** — upsert twice with different similarity; assert one row, similarity refreshed:

```go
func TestUpsertSimilarToEdge_Idempotent(t *testing.T) {
    db := testDB(t); st := NewChunkLinkStore(db)
    a, b := canonical("A-uuid", "B-uuid") // smaller first
    if err := st.UpsertSimilarToEdge(ctx, proj, a, b, 0.84); err != nil { t.Fatal(err) }
    if err := st.UpsertSimilarToEdge(ctx, proj, a, b, 0.91); err != nil { t.Fatal(err) }
    n, sim := countSimilarTo(t, db, a, b)
    if n != 1 { t.Fatalf("want 1 edge, got %d", n) }
    if sim != 0.91 { t.Fatalf("want refreshed 0.91, got %v", sim) }
}
```

- [ ] **Step 2: Run to verify it fails** → FAIL (undefined).

- [ ] **Step 3: Implement** the upsert:

```go
func (s *ChunkLinkStore) UpsertSimilarToEdge(ctx context.Context, projectID, sourceID, targetID string, similarity float64) error {
    // id is OMITTED — knowledge_edges.id has DEFAULT uuid_generate_v4() (migration 000006:5).
    // ON CONFLICT (source_id, target_id, edge_type) targets the table's UNIQUE column list (000006:16) — verified.
    const q = `
      INSERT INTO knowledge_edges (project_id, source_id, target_id, edge_type, properties, created_by, created_at)
      VALUES ($1, $2, $3, 'similar_to',
              jsonb_build_object('similarity', $4::float8), 'ba033-chunk-linker', now())
      ON CONFLICT (source_id, target_id, edge_type)
      DO UPDATE SET properties = jsonb_build_object('similarity', $4::float8)`
    if _, err := s.db.ExecContext(ctx, q, projectID, sourceID, targetID, similarity); err != nil {
        return fmt.Errorf("upsert similar_to: %w", err)
    }
    return nil
}
```

> Verified: `knowledge_edges` has `id UUID PRIMARY KEY DEFAULT uuid_generate_v4()` and `UNIQUE (source_id, target_id, edge_type)` (migration 000006). No `gen_random_uuid()` — omit `id` and let the DEFAULT fill it. Confirm `knowledge_edges` has no other NOT-NULL column without a default before running (the INSERT covers project_id/source_id/target_id/edge_type/properties/created_by/created_at; `session_id` is nullable).

- [ ] **Step 4: Run to verify it passes** → PASS.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/store/chunk_link.go internal/store/chunk_link_test.go
git -C ennam.kg.go commit -m "feat(ba033-s1): idempotent upsert of similar_to edges"
```

---

## Task 4: ChunkLinker service (loop, canonical order, top_k, coverage)

**Files:**
- Create: `internal/service/chunk_linker.go`, `internal/service/chunk_linker_test.go`

**Interfaces:**
- Consumes: `ChunkLinkStore.SimilarChunksCrossDoc`, `ChunkLinkStore.UpsertSimilarToEdge`; a chunk-lister (`SELECT id, properties->>'document_id' FROM knowledge_nodes JOIN knowledge_node_embeddings ... WHERE node_type='document_chunk'`).
- Produces:
  ```go
  type LinkConfig struct { SimThreshold float64; TopK int; Overfetch int } // defaults 0.83 / 5 / 20
  type LinkResult struct { ChunksTotal, ChunksEmbedded, EdgesUpserted int; Histogram map[string]int }
  func (l *ChunkLinker) Run(ctx context.Context, projectID string, cfg LinkConfig) (LinkResult, error)
  ```

- [ ] **Step 1: Write the failing test** — fixture: 1 doc-pair with a cross-doc near pair above threshold + a same-doc pair; assert exactly one `similar_to` edge, canonical order, coverage counts, and histogram populated:

```go
func TestChunkLinker_Run(t *testing.T) {
    db := testDB(t)
    l := NewChunkLinker(NewChunkLinkStore(db), slog.Default())
    seedCrossDocSimilarPair(t, db, proj)       // A(doc1) ~ B(doc2), sim 0.88
    seedSameDocSimilarPair(t, db, proj)        // C(doc1) ~ D(doc1), sim 0.95
    res, err := l.Run(ctx, proj, LinkConfig{SimThreshold: 0.83, TopK: 5, Overfetch: 20})
    if err != nil { t.Fatal(err) }
    if res.EdgesUpserted != 1 { t.Fatalf("want 1 cross-doc edge, got %d", res.EdgesUpserted) }
    if res.ChunksEmbedded == 0 || res.ChunksEmbedded > res.ChunksTotal { t.Fatal("coverage counts wrong") }
    assertOneEdgeCanonical(t, db, "A","B")     // smaller uuid is source, no duplicate
}
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Implement** the loop:
  - List embedded chunks for the project (id + document_id); record `ChunksTotal` (all active chunks) vs `ChunksEmbedded`.
  - For each: `SimilarChunksCrossDoc(limit = TopK + Overfetch)`; keep `sim >= SimThreshold`; take first `TopK`; for each neighbour, canonical-order the pair and `UpsertSimilarToEdge`.
  - Bucket every candidate's `sim` into the `Histogram` (0.78–0.90 buckets) BEFORE the threshold cut (BR-L6 calibration data).
  - If a chunk's cross-doc candidate pool is exhausted before `TopK`, `logger.Info("link pool exhausted", "chunk", id)` (BR-L2).
  - `logger.Info("chunk-link coverage", "embedded", e, "total", t)` (BR-L3).

```go
func (l *ChunkLinker) Run(ctx context.Context, projectID string, cfg LinkConfig) (LinkResult, error) {
    chunks, total, err := l.store.ListEmbeddedChunks(ctx, projectID) // returns []{id,docID}, totalActive
    if err != nil { return LinkResult{}, fmt.Errorf("list chunks: %w", err) }
    res := LinkResult{ChunksTotal: total, ChunksEmbedded: len(chunks), Histogram: map[string]int{}}
    for _, c := range chunks {
        nbrs, err := l.store.SimilarChunksCrossDoc(ctx, projectID, c.ID, c.DocID, cfg.TopK+cfg.Overfetch)
        if err != nil { return res, fmt.Errorf("neighbors %s: %w", c.ID, err) }
        kept := 0
        for _, nb := range nbrs {
            bucket(res.Histogram, nb.Similarity)
            if nb.Similarity < cfg.SimThreshold { continue }
            if kept >= cfg.TopK { break }
            src, tgt := canonical(c.ID, nb.NodeID)
            if err := l.store.UpsertSimilarToEdge(ctx, projectID, src, tgt, nb.Similarity); err != nil {
                return res, fmt.Errorf("upsert %s-%s: %w", src, tgt, err)
            }
            res.EdgesUpserted++; kept++
        }
        if kept < cfg.TopK { l.log.Info("link pool exhausted", "chunk", c.ID, "kept", kept) }
    }
    l.log.Info("chunk-link coverage", "embedded", res.ChunksEmbedded, "total", res.ChunksTotal, "edges", res.EdgesUpserted)
    return res, nil
}
```
(Add `ListEmbeddedChunks` to `ChunkLinkStore`; `canonical(a,b)` returns the two ids with the lexicographically smaller first; `bucket()` increments the 0.78–0.90 histogram.)

- [ ] **Step 4: Run to verify it passes** → PASS.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/service/chunk_linker.go internal/service/chunk_linker_test.go internal/store/chunk_link.go
git -C ennam.kg.go commit -m "feat(ba033-s1): ChunkLinker service — cross-doc top-k linking with coverage+histogram"
```

---

## Task 5: Linker endpoint + wiring

**Files:**
- Create: `internal/handler/graphrag_link.go`, `internal/handler/graphrag_link_test.go`
- Modify: `cmd/kg-server/main.go` (~line 382, beside `resolutionCandidatesHandler`)

**Interfaces:**
- Consumes: `ChunkLinker.Run`.
- Produces: `POST /api/v1/internal/graphrag/link` body `{project_id}` → `200 {chunks_total, chunks_embedded, edges_upserted, histogram}`.

- [ ] **Step 1: Write the failing handler test** — POST with a project that has a seeded cross-doc pair returns 200 with `edges_upserted >= 1`; missing `project_id` → 400.

```go
func TestGraphRAGLinkHandler(t *testing.T) {
    h := NewGraphRAGLinkHandler(linkerWithSeed(t), slog.Default())
    rr := doPOST(t, h.HandleLink, "/api/v1/internal/graphrag/link", `{"project_id":"`+proj+`"}`)
    if rr.Code != 200 { t.Fatalf("want 200, got %d", rr.Code) }
    var resp struct{ EdgesUpserted int `json:"edges_upserted"` }
    json.Unmarshal(rr.Body.Bytes(), &resp)
    if resp.EdgesUpserted < 1 { t.Fatal("expected >=1 edge") }
    rr2 := doPOST(t, h.HandleLink, "/api/v1/internal/graphrag/link", `{}`)
    if rr2.Code != 400 { t.Fatalf("missing project_id want 400, got %d", rr2.Code) }
}
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Implement** the handler (mirror `resolution_candidates.go` handler shape) + `RegisterRoutes(mux)` registering `POST /api/v1/internal/graphrag/link`. Decode body, validate `project_id`, call `linker.Run` with default `LinkConfig`, encode `LinkResult` as JSON.

- [ ] **Step 4: Wire in `main.go`** (after line 383):

```go
chunkLinker := service.NewChunkLinker(store.NewChunkLinkStore(db), logger)
handler.NewGraphRAGLinkHandler(chunkLinker, logger).RegisterRoutes(apiMux)
```

- [ ] **Step 5: Run + build** — `go test ./internal/handler/ -run TestGraphRAGLinkHandler -v` → PASS; `make -C ennam.kg.go build` → ok.

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.go add internal/handler/graphrag_link.go internal/handler/graphrag_link_test.go cmd/kg-server/main.go
git -C ennam.kg.go commit -m "feat(ba033-s1): POST /internal/graphrag/link endpoint + wiring"
```

---

## Task 6: Store — 1-hop `similar_to` expansion (surfaces similarity)

**Files:**
- Create: `internal/store/graph_retrieve.go`, `internal/store/graph_retrieve_test.go`

**Interfaces:**
- Produces:
  ```go
  type Expanded struct { ChunkID, DocumentID string; EdgeSimilarity float64; ViaSeed string }
  // ExpandSimilarTo returns, for each seed chunk id, the chunks reachable by one similar_to hop
  // (either direction), carrying the edge's similarity and which seed reached it.
  func (s *GraphRetrieveStore) ExpandSimilarTo(ctx context.Context, projectID string, seedIDs []string) ([]Expanded, error)
  ```

- [ ] **Step 1: Write the failing test** — seed A linked to B(doc2) sim 0.9; expanding [A] returns B with EdgeSimilarity 0.9, ViaSeed A; expanding [] returns empty.

```go
func TestExpandSimilarTo(t *testing.T) {
    db := testDB(t); st := NewGraphRetrieveStore(db)
    seedSimilarToEdge(t, db, proj, "A", "B", "doc2", 0.9)
    got, err := st.ExpandSimilarTo(ctx, proj, []string{"A"})
    if err != nil { t.Fatal(err) }
    if len(got) != 1 || got[0].ChunkID != "B" || got[0].EdgeSimilarity != 0.9 || got[0].ViaSeed != "A" {
        t.Fatalf("bad expansion: %+v", got)
    }
}
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Implement** — query both directions, surface `e.properties->>'similarity'`:

```go
func (s *GraphRetrieveStore) ExpandSimilarTo(ctx context.Context, projectID string, seedIDs []string) ([]Expanded, error) {
    if len(seedIDs) == 0 { return nil, nil }
    const q = `
      SELECT c.id, c.properties->>'document_id',
             (e.properties->>'similarity')::float8,
             CASE WHEN e.source_id = ANY($2) THEN e.source_id ELSE e.target_id END AS via_seed
      FROM knowledge_edges e
      JOIN knowledge_nodes c ON c.status='active' AND c.node_type='document_chunk'
        AND c.id = CASE WHEN e.source_id = ANY($2) THEN e.target_id ELSE e.source_id END
      WHERE e.edge_type = 'similar_to' AND e.project_id = $1
        AND (e.source_id = ANY($2) OR e.target_id = ANY($2))`
    rows, err := s.db.QueryContext(ctx, q, projectID, pq.Array(seedIDs))
    if err != nil { return nil, fmt.Errorf("expand similar_to: %w", err) }
    defer rows.Close()
    var out []Expanded
    for rows.Next() {
        var x Expanded
        if err := rows.Scan(&x.ChunkID, &x.DocumentID, &x.EdgeSimilarity, &x.ViaSeed); err != nil { return nil, fmt.Errorf("scan: %w", err) }
        out = append(out, x)
    }
    return out, rows.Err()
}
```
(Use the project's existing array-binding helper if `pq.Array` isn't the convention — mirror how other multi-id queries bind.)

- [ ] **Step 4: Run to verify it passes** → PASS.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/store/graph_retrieve.go internal/store/graph_retrieve_test.go
git -C ennam.kg.go commit -m "feat(ba033-s1): 1-hop similar_to expansion store query"
```

---

## Task 7: GraphRetriever service (seed + rank + dedup + per-doc cap)

**Files:**
- Create: `internal/service/graph_retriever.go`, `internal/service/graph_retriever_test.go`

**Interfaces:**
- Consumes (VERIFIED — the seed is a TWO-step path, not one call):
  - `QueryEmbedder.EmbedQuery(ctx, query) ([]float32, error)` — the **Python embedding service** turns the TEXT query into a 384-dim vector (interface defined at `internal/handler/search.go:22`; `SemanticSearch` does NOT accept text). The retriever depends on this same interface SearchHandler uses.
  - `NodeEmbeddingStore.SemanticSearch(ctx, projectID, queryEmbedding []float32, topK int, nodeTypes []string, documentID string) ([]SearchResult, error)` (node_embedding.go:101) — call with `nodeTypes=["document_chunk"]`, `documentID=""`, `topK=SeedK`. `SearchResult` carries the node `id` + `rank` (cosine).
  - `GraphRetrieveStore.ExpandSimilarTo`.
- Produces:
  ```go
  type RetrieveConfig struct { SeedK, ResultK, PerDocCap int } // 10 / 5 / 2
  type Result struct { ChunkID, DocumentID string; Score, SeedRelevance, EdgeSimilarity float64; ViaSeed string; HopCount int }
  type Bundle struct { Results []Result; SeedCount, ExpandedCount, DroppedCount int; Truncated bool }
  // QueryEmbedder mirrors handler.QueryEmbedder (search.go:22).
  type QueryEmbedder interface { EmbedQuery(ctx context.Context, query string) ([]float32, error) }
  type SeedSearcher interface { SemanticSearch(ctx context.Context, projectID string, queryEmbedding []float32, topK int, nodeTypes []string, documentID string) ([]store.SearchResult, error) }
  func NewGraphRetriever(embedder QueryEmbedder, seeder SeedSearcher, expander Expander) *GraphRetriever
  func (r *GraphRetriever) Retrieve(ctx context.Context, projectID, query string, cfg RetrieveConfig) (Bundle, error)
  ```
- **Error path:** if `EmbedQuery` fails, return a typed error the handler maps to **502** (mirror `search.go:163-164` "embedding service error"). Retrieval depends on the embedding service being up — same dependency as `/search`.

- [ ] **Step 1: Write the failing test** — inject a fake seed (`A`:0.8) and a fake expander (`A→B@0.9`, `A→C@0.5`); assert: B scores 0.72 (0.8×0.9), dedup keeps max, per-doc cap + round-robin diversifies, deterministic tie-break, provenance fields set.

```go
func TestGraphRetriever_RankAndDedup(t *testing.T) {
    emb := fakeEmbedder{vec: make([]float32, 384)}                 // text→vector stub
    seed := fakeSeeder{results: []store.SearchResult{{ID: "A", Rank: 0.8}}} // SemanticSearch stub
    exp := fakeExpander{ {ChunkID:"B",DocumentID:"d2",EdgeSimilarity:0.9,ViaSeed:"A"},
                         {ChunkID:"B",DocumentID:"d2",EdgeSimilarity:0.7,ViaSeed:"A2"}, // dup → keep max
                         {ChunkID:"C",DocumentID:"d3",EdgeSimilarity:0.5,ViaSeed:"A"} }
    r := NewGraphRetriever(emb, seed, exp)
    b, _ := r.Retrieve(ctx, proj, "q", RetrieveConfig{SeedK:10, ResultK:5, PerDocCap:2})
    // B kept once with score 0.8*0.9=0.72; C with 0.8*0.5=0.40; order B then C
    if len(b.Results)!=2 || b.Results[0].ChunkID!="B" || b.Results[0].Score != 0.72 {
        t.Fatalf("rank/dedup wrong: %+v", b.Results)
    }
}
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Implement** (pure functions, easily testable):
  - Seed (two steps): `vec, err := embedder.EmbedQuery(ctx, query)` (on err → typed embed-error for 502); then `seeds := seeder.SemanticSearch(ctx, projectID, vec, SeedK, []string{"document_chunk"}, "")` → map `seedID → rank`.
  - Expand: `ExpandSimilarTo(seedIDs)`.
  - For each expanded item: `score = seedRelevance[ViaSeed] * EdgeSimilarity`, `HopCount=1`.
  - **Dedup** by `ChunkID`: keep max score (record its ViaSeed).
  - **Sort:** score desc, then `ChunkID` asc (deterministic tie-break).
  - **Per-doc cap + round-robin:** group by `DocumentID`; emit round-robin, ≤ `PerDocCap` per doc, until `ResultK`. Set `DroppedCount`/`Truncated`.
  - Empty seed → empty bundle (not error). No edges → results empty, `ExpandedCount=0`.

- [ ] **Step 4: Run to verify it passes** → PASS.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/service/graph_retriever.go internal/service/graph_retriever_test.go
git -C ennam.kg.go commit -m "feat(ba033-s1): GraphRetriever — blend score, dedup, per-doc round-robin"
```

---

## Task 8: `kg_graph_retrieve` endpoint + wiring

**Files:**
- Create: `internal/handler/graph_retrieve.go`, `internal/handler/graph_retrieve_test.go`
- Modify: `cmd/kg-server/main.go`

**Interfaces:**
- Produces: `POST /api/v1/retrieve/graph` body `{query, project_id, result_k?, seed_k?, per_document_cap?}` → `Bundle` JSON (read-only).

- [ ] **Step 1: Write the failing handler test** — valid body returns 200 with `results` + counts; missing `query` → 400; handler performs no writes (assert edge count unchanged before/after).

```go
func TestGraphRetrieveHandler(t *testing.T) {
    h := NewGraphRetrieveHandler(retrieverWithSeededEdges(t), slog.Default())
    rr := doPOST(t, h.HandleRetrieve, "/api/v1/retrieve/graph",
        `{"query":"referral","project_id":"`+proj+`"}`)
    if rr.Code != 200 { t.Fatalf("want 200, got %d", rr.Code) }
    rr2 := doPOST(t, h.HandleRetrieve, "/api/v1/retrieve/graph", `{"project_id":"`+proj+`"}`)
    if rr2.Code != 400 { t.Fatalf("missing query want 400, got %d", rr2.Code) }
}
```

- [ ] **Step 2: Run to verify it fails** → FAIL.

- [ ] **Step 3: Implement** the handler + `RegisterRoutes` (`POST /api/v1/retrieve/graph`), decode/validate, apply defaults (SeedK 10, ResultK 5, PerDocCap 2), call `retriever.Retrieve`, encode `Bundle`.

- [ ] **Step 4: Wire in `main.go`:**

```go
// queryEmbedder is the SAME QueryEmbedder instance SearchHandler uses (Python embedding
// service client). Locate where SearchHandler is constructed (NewSearchHandler(..., embedder, ...))
// — it is wired via a query-handlers registrar, not directly in main.go's top scope — and
// reuse that embedder here. Do NOT construct a second embedder.
graphRetriever := service.NewGraphRetriever(queryEmbedder, nodeEmbStore, store.NewGraphRetrieveStore(db))
handler.NewGraphRetrieveHandler(graphRetriever, logger).RegisterRoutes(apiMux)
```

> ⚠️ **Wiring prerequisite (verified gap):** `main.go` does not reference the embedder at top scope — `SearchHandler` gets its `QueryEmbedder` inside a sub-registrar. Before this task, surface that embedder instance (or its constructor) so the GraphRetriever can share it. The handler maps an `EmbedQuery` failure to **502** (mirror `search.go:163-164`).

- [ ] **Step 5: Run + build** → PASS; `make -C ennam.kg.go build` ok.

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.go add internal/handler/graph_retrieve.go internal/handler/graph_retrieve_test.go cmd/kg-server/main.go
git -C ennam.kg.go commit -m "feat(ba033-s1): POST /retrieve/graph endpoint + wiring"
```

---

## Task 9: `kg_graph_retrieve` MCP tool (routed read tool)

**Files:**
- Modify: `internal/bridge/` (schema list, route map, handler) + the corresponding bridge tests (mirror an existing routed read tool, e.g. `kg_get_backlinks` / `kg_search`).

**Interfaces:**
- Consumes: `POST /api/v1/retrieve/graph`.
- Produces: MCP tool `kg_graph_retrieve` (read-class, HTTP-proxy), params `{query (required), result_k?, project_id?}` (≤3 required for Qwen portability).

- [ ] **Step 1: Write the failing tests** — per the bridge tool-count invariant (memory `bridge-tool-count-drift`): adding a ROUTED tool bumps client_test(ListToolNames), handler_test(ListTools), schema_test, and the integration_test enum. Add `kg_graph_retrieve` to each expected set; assert the invariant `schemas == routes + localToolNames` still holds.

- [ ] **Step 2: Run to verify it fails** → FAIL (counts off / tool absent).

- [ ] **Step 3: Implement** — add the JSON schema entry, the route mapping `kg_graph_retrieve → POST /api/v1/retrieve/graph`, and ensure it's in ListToolNames/ListTools. Mirror an existing routed read tool exactly.

- [ ] **Step 4: Run to verify it passes** → PASS; `make -C ennam.kg.go test` green.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/bridge
git -C ennam.kg.go commit -m "feat(ba033-s1): kg_graph_retrieve routed MCP read tool"
```

---

## Task 10: Marginal-set eval harness (ship gate)

**Files:**
- Create: `internal/integration/ba033_marginal_eval_test.go` (`//go:build integration`)

**Interfaces:**
- Consumes: `/api/v1/search` (baseline `B`) and `/api/v1/retrieve/graph` (slice `G`) over a query set.

- [ ] **Step 1: Write the eval** — for a fixture query set on a seeded 2-doc-shared-topic corpus:
  - `B` = `/search @ result_k=20` chunk ids.
  - `G` = `/retrieve/graph` chunk ids.
  - Compute `G \ B` (the marginal set) per query; assert it is **non-empty for ≥1 query** and the marginal chunks are the seeded cross-doc bridges (relevance proxy in the fixture).

```go
//go:build integration
func TestBA033_MarginalSet(t *testing.T) {
    // seed doc1 + doc2 sharing a topic; run linker; then:
    B := searchChunkIDs(t, "topic query", 20)
    G := graphRetrieveChunkIDs(t, "topic query")
    marg := difference(G, B)
    if len(marg) == 0 { t.Fatal("graph retrieve added nothing over /search@20 — ship gate FAIL") }
    if !containsExpectedBridge(marg) { t.Fatal("marginal set is not the seeded cross-doc bridge") }
}
```

- [ ] **Step 2: Run** — `KG_TEST_DB_URL=... go test -tags=integration ./internal/integration/ -run TestBA033_MarginalSet -v`. Expected: PASS on the fixture (or DEFERRED with reason if the live stack/embeddings aren't available — fail loud, never skip silently).

- [ ] **Step 3: Commit**

```bash
git -C ennam.kg.go add internal/integration/ba033_marginal_eval_test.go
git -C ennam.kg.go commit -m "test(ba033-s1): marginal-set ship-gate eval (G\\B vs /search@20)"
```

> **Operational ship gate (post-merge, on real data, not just the fixture):** run the linker on a real project, then compare `G \ B` relevance on a human-judged query set. Ship the feature ON only if the marginal set is materially non-empty and relevant (spec §7). If it's empty, do NOT ship — expose a higher `result_k` on `/search` instead.

---

## Definition of Done

- [ ] Gate-1 admits `document_chunk → similar_to → document_chunk` (Task 1).
- [ ] ChunkLinker builds cross-doc-only, top-k, canonical, idempotent `similar_to` edges; logs coverage + histogram (Tasks 2–5).
- [ ] `kg_graph_retrieve` returns a ranked, deduped, per-doc-capped, provenance-tagged bundle from a 1-hop expansion (Tasks 6–8).
- [ ] `kg_graph_retrieve` exposed as a routed MCP read tool; bridge invariant holds (Task 9).
- [ ] Marginal-set eval passes on the fixture; operational ship gate documented (Task 10).
- [ ] `make -C ennam.kg.go test lint build` green; no entity-bridge / community / recursion code introduced (scope held).

## Self-review notes (verified against spec)
- Spec coverage: FR-001 → Tasks 1–5; FR-004 → Tasks 6–8; tool surface → Task 9; ship gate §7 → Task 10. Linker BR-L1..L7 mapped (cross-doc T2/T4, over-fetch T4, embedded-only/coverage T4, idempotent T3, Gate-1 T1, calibration histogram T4). Ranking BR-R1..R5 → Task 7. Deferrals (entity bridge, community, incremental) carry no tasks by design.
- Type consistency: `ChunkLinkStore`, `ChunkNeighbor`, `Expanded`, `RetrieveConfig`/`Result`/`Bundle`, `LinkConfig`/`LinkResult` used identically across tasks.
- **Corrections from deep code verification (2026-06-24):**
  - T7 seed: `SemanticSearch` takes a **vector, not text** — the retriever must depend on `QueryEmbedder` (Python embedding service, search.go:22) to embed the query first, then `SemanticSearch(vec, ["document_chunk"], SeedK)`. Embedding-service failure → 502. (Fixed in T7/T8.)
  - T3 upsert: use the table `DEFAULT uuid_generate_v4()` (omit `id`); `gen_random_uuid()` is NOT the convention. `ON CONFLICT (source_id,target_id,edge_type)` confirmed valid (000006 column-list UNIQUE). (Fixed in T3.)
  - T2 confirmed: `knowledge_node_embeddings` has `node_id UNIQUE` + cols `node_id/project_id/embedding` — the self-join is valid.
- Open items still to confirm at implement time: array-binding driver (`pq.Array` vs pgx) in T6; exact bridge routed-tool registration files in T9; the exact location of the shared `QueryEmbedder` instance for T8 wiring; any other NOT-NULL-without-default column on `knowledge_edges` (T3).
- **New dependency surfaced:** retrieval (not just linking) requires the Python embedding service to be up, and only embedded chunks (~60/131) are reachable — both noted as Slice-1 preconditions (spec §2, S1-OQ1).
