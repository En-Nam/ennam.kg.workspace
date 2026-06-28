# BA-033 Retrieval — Parent-Child + Entity-Anchored Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).
> Spec: `docs/superpowers/specs/2026-06-26-ba033-retrieval-realcorpus-design.md`.

**Goal:** Mở rộng retrieval của DAAB với 2 mode trên corpus + entity ĐÃ SẠCH: **parent-child** (chunk chính xác → trả section cha) + **entity-anchored** (cross-doc qua entity chung) → semantic search chính xác/ổn định + đạt mục tiêu cross-doc BA-033. Đo bằng eval gate trên 10-doc corpus thật.

**Architecture:** Mở rộng `GraphRetriever` (Slice 1, `internal/service/graph_retriever.go`) — vốn: embed → seed top-K `document_chunk` → expand `similar_to`. Thêm 2 expander mới (interface, mirror `Expander`): **SectionExpander** (chunk→section cha qua `contains_section` reverse) + **EntityExpander** (chunk→section/doc→`mentions`→concept→reverse `mentions`→doc/section khác = cross-doc). Fuse RRF. Reuse seed search + handler `POST /api/v1/retrieve/graph` (thêm `mode`).

**Tech Stack:** Go (`internal/service/graph_retriever.go`, `internal/store`, `internal/handler/graph_retrieve.go`), PostgreSQL. Eval: script gọi /retrieve/graph + /search trên corpus.

## Verified facts (2026-06-27, từ graph thật 10-doc)
- Edges: `document_section --contains_section--> document_chunk` (chunk có **1 section cha**); `document --contains_section--> document_section`; `document|document_section --mentions--> concept` (entity).
- `knowledge_edges` cột: `id, project_id, source_id, target_id, edge_type, properties, ...` (edge_type, KHÔNG phải relationship).
- `GraphRetriever{embedder, seeder, expander}`, `Retrieve(ctx, projectID, query, cfg RetrieveConfig) (Bundle, error)`; seed = `seeder.SemanticSearch(ctx, projectID, vec, k, []string{"document_chunk"}, "")`; `Result{ChunkID, DocumentID, SeedRelevance, ViaSeed, HopCount}` (json snake_case); handler `POST /api/v1/retrieve/graph` (`graph_retrieve.go:27`).
- Entity đã dedup (exact-name applied) → cross-doc qua `mentions` giờ hợp nhất (Hàm Giang refs 11, Trà Vinh 5…).

## Global Constraints
- Reuse seed search + RRF (`store.ReciprocalRankFusion`) + GraphRetriever skeleton — KHÔNG viết retrieval mới từ đầu.
- Traversal qua `knowledge_edges` (edge_type), scoped `project_id`.
- **Falsifiability gate:** mỗi mode chỉ "ship" nếu **marginal > baseline `/search` flat** trên eval (spec §6).
- Mode chọn qua config/param; default giữ baseline (không đổi hành vi cũ).
- Test: Go `make test` (mock expander + DB-backed traversal test). Nested git `git -C ennam.kg.go`.

---

## Task 1: Store — parent-section + shared-entity traversal

**Files:** Modify `internal/store/` (graph_retrieve store, nơi `ExpandSimilarTo`/`Expanded` định nghĩa). Test: `internal/store/graph_retrieve_test.go` (DB-backed, `setupTestDB`).

**Interfaces:**
- `ParentSections(ctx, projectID string, chunkIDs []string) (map[string]string, error)` — chunk_id → parent section_id (reverse `contains_section`).
- `SharedEntityNeighbors(ctx, projectID string, originNodeIDs []string) ([]EntityNeighbor, error)` — từ origin (section/doc) → `mentions` concept → reverse `mentions` → node khác; trả `{NodeID, NodeType, SharedEntityCount}` (rank by shared count), loại origin.

- [ ] **Step 1: Write failing test** (`package store_test`, `setupTestDB`; seed 2 docs cùng 1 concept + 1 section→chunk):
```go
func TestParentSections(t *testing.T) {
    db := setupTestDB(t); s := store.NewGraphRetrieveStore(db); ctx := context.Background()
    // seed: section S contains_section chunk C
    // assert ParentSections(ctx, proj, []{C}) == {C: S}
}
func TestSharedEntityNeighbors_CrossDoc(t *testing.T) {
    // seed: docA section SA mentions concept E; docB section SB mentions E
    // ParentSections + SharedEntityNeighbors([SA]) → contains SB with SharedEntityCount>=1, excludes SA
}
```

- [ ] **Step 2: Run → fail.** `cd ennam.kg.go && KG_TEST_DATABASE_URL=... go test ./internal/store/ -run "ParentSections|SharedEntity" -v`

- [ ] **Step 3: Implement** — SQL trên `knowledge_edges`:
```go
// chunk → parent section (reverse contains_section)
func (s *GraphRetrieveStore) ParentSections(ctx context.Context, projectID string, chunkIDs []string) (map[string]string, error) {
    rows, err := s.db.QueryContext(ctx, `
        SELECT target_id AS chunk_id, source_id AS section_id
        FROM knowledge_edges
        WHERE project_id=$1 AND edge_type='contains_section' AND target_id = ANY($2)`,
        projectID, pq.Array(chunkIDs))
    // ... scan into map[chunk]section
}

// origin (section/doc) → mentions concept → reverse mentions → other nodes (cross-doc), ranked by shared-entity count
func (s *GraphRetrieveStore) SharedEntityNeighbors(ctx context.Context, projectID string, originIDs []string) ([]EntityNeighbor, error) {
    rows, err := s.db.QueryContext(ctx, `
        WITH ent AS (
            SELECT DISTINCT target_id AS concept_id
            FROM knowledge_edges
            WHERE project_id=$1 AND edge_type='mentions' AND source_id = ANY($2)
        )
        SELECT e.source_id AS node_id, count(DISTINCT e.target_id) AS shared
        FROM knowledge_edges e JOIN ent ON ent.concept_id = e.target_id
        WHERE e.project_id=$1 AND e.edge_type='mentions' AND e.source_id <> ALL($2)
        GROUP BY e.source_id
        ORDER BY shared DESC
        LIMIT 50`,
        projectID, pq.Array(originIDs))
    // ... scan EntityNeighbor{NodeID, SharedEntityCount}; NodeType via a join or separate lookup if needed
}
```
> `EntityNeighbor{NodeID string; NodeType string; SharedEntityCount int}`. Nếu cần NodeType → join `knowledge_nodes`. Đọc store hiện tại để khớp struct/scan pattern + `pq.Array`.

- [ ] **Step 4: Run → pass + commit**
```bash
git -C ennam.kg.go add internal/store/ internal/store/graph_retrieve_test.go
git -C ennam.kg.go commit -m "feat(ba033): store traversal — parent sections + shared-entity neighbors"
```

---

## Task 2: GraphRetriever — parent-child mode

**Files:** Modify `internal/service/graph_retriever.go`. Test: `internal/service/graph_retriever_test.go`.

**Interfaces:**
- `SectionExpander interface { ParentSections(ctx, projectID string, chunkIDs []string) (map[string]string, error) }`.
- `RetrieveConfig.Mode string` ("flat"|"parent_child"|"entity"|"hybrid"; default "flat" = hành vi cũ).
- **Constructor (verified):** `NewGraphRetriever(embedder, seeder, expander)` cố định 3 param, gọi 8 chỗ (main.go:933 + 7 test). → **Thêm variadic options, KHÔNG đổi 3 param cũ** (backward-compat):
  ```go
  type Option func(*GraphRetriever)
  func WithSections(s SectionExpander) Option { return func(g *GraphRetriever){ g.sections = s } }
  func WithEntities(e EntityExpander) Option  { return func(g *GraphRetriever){ g.entities = e } }
  func NewGraphRetriever(embedder QueryEmbedder, seeder SeedSearcher, expander Expander, opts ...Option) *GraphRetriever {
      g := &GraphRetriever{embedder: embedder, seeder: seeder, expander: expander}
      for _, o := range opts { o(g) }
      return g
  }
  ```
  Struct thêm field `sections SectionExpander` + `entities EntityExpander` (nil → mode đó fallback flat). **8 caller cũ KHÔNG đổi.**
- Parent-child: sau seed → map chunk→section → trả thêm `Result.SectionID` (omitempty). Giữ Result cũ backward-compat (thêm field, không xoá).

- [ ] **Step 1: Write failing test** (mock SectionExpander):
```go
func TestRetrieve_ParentChild_ReturnsSection(t *testing.T) {
    gr := NewGraphRetriever(fakeEmbedder, fakeSeeder /*returns chunk C1*/, fakeExpander, withSections(map[string]string{"C1":"S1"}))
    b, _ := gr.Retrieve(ctx, "p1", "q", RetrieveConfig{Mode: "parent_child", SeedK: 5})
    // assert b.Results[0].SectionID == "S1"
}
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — thêm `sections SectionExpander` vào GraphRetriever (optional dep); trong `Retrieve`, nếu Mode=="parent_child"|"hybrid": `parents := gr.sections.ParentSections(ctx, projectID, seedIDs)`; stamp `Result.SectionID = parents[chunkID]`. Giữ similar_to expand cho mode khác.
```go
type Result struct {
    ChunkID string `json:"chunk_id"`; DocumentID string `json:"document_id"`
    SectionID string `json:"section_id,omitempty"`   // parent-child mode
    SeedRelevance float64 `json:"seed_relevance"`; ViaSeed string `json:"via_seed_chunk_id"`; HopCount int `json:"hop_count"`
}
```

- [ ] **Step 4: Run → pass + commit**
```bash
git -C ennam.kg.go add internal/service/graph_retriever.go internal/service/graph_retriever_test.go
git -C ennam.kg.go commit -m "feat(ba033): parent-child retrieval mode (chunk → parent section)"
```

---

## Task 3: GraphRetriever — entity-anchored mode

**Files:** Modify `internal/service/graph_retriever.go`. Test: `internal/service/graph_retriever_test.go`.

**Interfaces:**
- `EntityExpander interface { SharedEntityNeighbors(ctx, projectID string, originIDs []string) ([]store.EntityNeighbor, error) }`.
- Entity mode: seed chunks → parent sections (origin) → `SharedEntityNeighbors` → cross-doc neighbor nodes → add to Bundle (ranked by shared-entity count, `HopCount=1`, `ViaSeed`).

- [ ] **Step 1: Write failing test** (mock EntityExpander returns SB for origin SA):
```go
func TestRetrieve_Entity_AddsCrossDocNeighbors(t *testing.T) {
    gr := NewGraphRetriever(fakeEmbedder, fakeSeeder, fakeExpander, withSections(...), withEntities([]store.EntityNeighbor{{NodeID:"SB", SharedEntityCount:2}}))
    b, _ := gr.Retrieve(ctx, "p1", "q", RetrieveConfig{Mode: "entity", SeedK: 5})
    // assert any(r.NodeID=="SB") in b.Results/Neighbors with shared count
}
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — Mode=="entity"|"hybrid": từ seed chunks → parent sections (origin) → `SharedEntityNeighbors(origin)` → add neighbors vào Bundle (new field `Bundle.EntityNeighbors []EntityResult{NodeID, NodeType, SharedEntityCount}` hoặc gộp Results). Rank by SharedEntityCount.

- [ ] **Step 4: Run → pass + commit**
```bash
git -C ennam.kg.go add internal/service/graph_retriever.go internal/service/graph_retriever_test.go
git -C ennam.kg.go commit -m "feat(ba033): entity-anchored cross-doc retrieval mode (shared entities)"
```

---

## Task 4: Handler — mode param + hybrid RRF fuse

**Files:** Modify `internal/handler/graph_retrieve.go`. Test: `internal/handler/graph_retrieve_test.go`.

**Interfaces:** `POST /api/v1/retrieve/graph` body thêm `"mode": "flat|parent_child|entity|hybrid"` (default "flat"). Hybrid: fuse flat-seed + parent-child + entity qua `store.ReciprocalRankFusion`.

- [ ] **Step 1: Write failing test** — POST với mode="entity" → response có entity neighbors; mode="hybrid" → fused; mode rỗng → flat (backward-compat).

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — parse `mode` → `RetrieveConfig.Mode`.
  - **RRF convert (verified):** `store.ReciprocalRankFusion(lists [][]store.SearchResult, k, limit)` chỉ nhận `[]store.SearchResult`. Các nguồn mới (`Result` parent-child có `SectionID`, `EntityNeighbor{NodeID,NodeType,SharedEntityCount}`) **phải map sang `store.SearchResult`** (set `ID` = ChunkID/NodeID; rank theo thứ tự nguồn) trước khi đưa vào `lists`. Fuse k=60.
  - **Wiring (verified, main.go:933):** hiện `NewGraphRetriever(embedClient, nodeEmbStore, graphRetrieveStore)`. `graphRetrieveStore` CHÍNH là object sẽ có `ParentSections`+`SharedEntityNeighbors` → đổi thành `NewGraphRetriever(embedClient, nodeEmbStore, graphRetrieveStore, service.WithSections(graphRetrieveStore), service.WithEntities(graphRetrieveStore))`. **Không cần đổi 8 caller test** (variadic opts). Handler không đổi signature (đã giữ `retriever`).

- [ ] **Step 4: Run + build + commit**
```bash
cd ennam.kg.go && go test ./internal/handler/ -run GraphRetrieve -race -v && go build ./...
git -C ennam.kg.go add internal/handler/graph_retrieve.go internal/handler/graph_retrieve_test.go cmd/kg-server/main.go
git -C ennam.kg.go commit -m "feat(ba033): retrieve mode param + hybrid RRF fuse"
```

---

## Task 5: Eval gate — đo 4 mode trên 10-doc corpus

**Files:** Create `ennam.kg.python/scripts/eval_ba033_retrieval.py` (hoặc reuse benchmark harness). Stack live + corpus đã seed.

- [ ] **Step 1: Câu hỏi eval** — soạn ~8-12 câu cross-doc M&A thật trên corpus 10-doc (vd "các văn bản liên quan Công ty Hàm Giang", "dự án Khu bến tổng hợp Định An gồm quyết định nào", "vai trò UBND tỉnh Trà Vinh"). Ground-truth = doc/section đúng (gán tay, nhỏ).

- [ ] **Step 2: Chạy 4 mode** — mỗi câu gọi `/search` (baseline flat) + `/retrieve/graph` mode=parent_child|entity|hybrid. Ghi top-k results.

- [ ] **Step 3: Metric (falsifiability gate)** — cross-doc recall@k + precision@k mỗi mode; **marginal vs baseline flat** (set G\B); stability (variance câu tương tự). In bảng so sánh.

- [ ] **Step 4: Go/No-Go** — mode nào **marginal>0** → ship (default mode = mode thắng). entity-anchored kỳ vọng thắng (entity đã sạch); parent-child kỳ vọng tăng độ đầy đủ. Nếu hybrid tốt nhất → default hybrid.
  - Nếu giá trị rõ → **seed full 216** (Danh export → Local Upload, không cần key) → eval lại đầy đủ.
  - Ghi kết quả → Serena checkpoint + cập nhật spec §6.

---

## Self-Review (đã chạy)
- **Spec coverage:** §4.2 parent-child → Task 2; §4.3 entity-anchored → Task 1/3; §4.4 hybrid RRF → Task 4; §6 eval gate → Task 5; §4.1 baseline flat = giữ nguyên `/search`. ✓
- **Edges verified thật:** `contains_section` (parent-child) + `mentions` (entity) tồn tại trên graph 10-doc. ✓
- **Reuse:** GraphRetriever skeleton + seeder + RRF + handler — chỉ thêm 2 expander + mode. Backward-compat (Mode default flat). ✓
- **Type consistency:** `ParentSections->map[chunk]section`, `SharedEntityNeighbors->[]EntityNeighbor{NodeID,NodeType,SharedEntityCount}` (Task1) = SectionExpander/EntityExpander interface (Task2/3) = handler mode (Task4). `Result.SectionID` thêm (omitempty, không vỡ json cũ). ✓

## Open dependencies (execute-time)
- `GraphRetrieveStore` struct/scan pattern + `Expanded`/`store` package (Task 1) — đọc graph_retrieve store hiện tại.
- ✅ VERIFIED: `NewGraphRetriever(embedder, seeder, expander)` — 3 param, gọi main.go:933 + 7 test. Wire qua variadic opts (Task 4 step 3) → 8 caller cũ không đổi.
- ✅ VERIFIED: `store.ReciprocalRankFusion(lists [][]store.SearchResult, k int, limit int) []store.SearchResult` — phải convert nguồn mới → `store.SearchResult` (Task 4 step 3).
- DB-backed store test cần `KG_TEST_DATABASE_URL` (skip nếu thiếu).
- Eval ground-truth gán tay (Task 5) — nhỏ, ~10 câu.
- Entity-anchored granularity = **section/document** (mentions ở mức section/doc, KHÔNG phải chunk) — đúng cho cross-doc; nếu muốn chunk-level cần thêm chunk→entity edges (ngoài scope).
