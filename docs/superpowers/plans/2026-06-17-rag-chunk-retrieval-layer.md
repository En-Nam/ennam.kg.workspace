# RAG Chunk Retrieval Layer (IMP-007) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a passage-level `document_chunk` retrieval unit below `document_section`, embedded with the existing e5-small/384-dim stack, served by a new Qwen-friendly MCP tool `kg_search_chunks` that returns the passage text + a precise citation — without changing `kg_search` or the embedding model.

**Architecture:** Each chunk is its own `document_chunk` knowledge node (server-assigned UUID = citation `chunk_id`), embedded into the existing `knowledge_node_embeddings(384)` table (one row per node, `UNIQUE(node_id)`), with a `document_section --contains_section--> document_chunk` edge for graph provenance. A deterministic natural key `chunk_key = "{section_id}:{ordinal}"` in properties drives idempotency via the codebase's existing differ pattern (create/update/delete by natural key + `content_hash`). A new `POST /api/v1/search-chunks` handler forces `scope=["document_chunk"]`, supports an optional `document_id` filter, and reuses the shipped hybrid RRF + fail-soft ladder.

**Tech Stack:** Go (stdlib `net/http`, `database/sql`, golang-migrate) for the API/bridge; Python 3.12 (httpx, sentence-transformers e5-small) for the ingest pipeline; PostgreSQL 16 + pgvector; pytest + `go test -race`.

**Spec:** `docs/superpowers/specs/2026-06-17-rag-chunk-retrieval-layer-design.md`
**Requirement:** `ennam.kg.requirements/documents/improvements/IMP-007-rag-chunk-retrieval-layer.md`

---

## ⚠️ Build gate (read before starting)

Per the spec §2 (PO-locked): **Phase 0 runs first and is a STOP/GO point.** Implement Phase 1+ **only if** the FR-4 baseline eval, on a representative long-document corpus with real extracted text, shows section-level truncation measurably hurts tail-of-section recall. If it does not, stop after Phase 0 and record the finding — the layer stays committed-in-direction but unbuilt.

`CHUNK_SIZE`/`CHUNK_THRESHOLD`/`CHUNK_OVERLAP` are **outputs of Phase 0**, not inputs. The seed values below (1200/1800/150 chars) make the chunker runnable for the eval; Phase 0 sets the shipped values, **bounded above by the e5 ~512-token window** (a chunk must never exceed it or embedding silently re-truncates).

---

## File Structure

**Python (`ennam.kg.python/`)**
- Create `src/ennam_kg/ingestion/pipeline/chunker.py` — pure chunking logic: paragraph-first packing, offsets, `chunk_key`, `content_hash`, token-budget guard. No I/O. Unit-testable in isolation.
- Modify `src/ennam_kg/ingestion/pipeline/decompose.py` — after each section is created, call the chunker and create `document_chunk` nodes + embeddings + `contains_section` edges.
- Create `src/ennam_kg/api/admin.py` addition (or new router function) — `POST /api/v1/admin/backfill-chunks`.
- Create `tests/ingestion/test_chunker.py`, extend `tests/ingestion/test_nodes.py`/decompose tests.
- Modify `tests/eval/retrieval_eval.py` — add a `/search-chunks` target + chunk-id scoring.

**Go (`ennam.kg.go/`)**
- Create `db/migrations/000059_document_chunk_node_type.up.sql` + `.down.sql`.
- Modify `config/config.yaml` — `node_types.document_chunk` block + `edge_whitelist` target.
- Modify `internal/config/types.go` — `NodeTypeDocumentChunk` const + `ValidNodeTypes`.
- Modify `internal/store/search.go` — add `DocumentID` to `SearchParams` + FTS predicate.
- Modify `internal/store/node_embedding.go` — add `documentID` arg to `SemanticSearch`.
- Modify `internal/handler/search.go` — `validNodeTypes` entry; new `HandleSearchChunks` + route.
- Modify `internal/bridge/schema.go` (+ `schema_test.go`, `handler_test.go`) — `kg_search_chunks` schema, 34→35.
- Modify `internal/bridge/client.go` (+ `integration_test.go`, `client_test.go`) — route, 32→33.

---

## Phase 0 — Build gate (FR-4): extractor + eval + STOP/GO

### Task 0.1: Minimal text extractor for the eval corpus

**Files:**
- Create: `ennam.kg.python/scripts/extract_eval_corpus.py`
- Test: manual (one-off script)

- [ ] **Step 1: Write the extractor**

The headline target (`C_ng_nh_An-master-record.pdf`) yields only 1706 chars via pypdf. Use `pypdf` first; if a page yields < 50 chars of text, fall back to `pdfplumber` (better layout extraction). This is a one-off eval aid, NOT bucket-C OCR.

```python
# ennam.kg.python/scripts/extract_eval_corpus.py
"""One-off: extract text from the eval corpus (PDF + markdown) for FR-4.
NOT production OCR — just enough real text to evaluate IMP-007 on long docs."""
import sys
from pathlib import Path

def extract_pdf(path: Path) -> str:
    from pypdf import PdfReader
    text = "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    if len(text.strip()) >= 50 * max(1, len(PdfReader(str(path)).pages)):
        return text
    # fall back to pdfplumber for layout-heavy / scanned-ish PDFs
    import pdfplumber
    with pdfplumber.open(str(path)) as pdf:
        return "\n".join((pg.extract_text() or "") for pg in pdf.pages)

def main() -> None:
    out = Path("tests/eval/corpus")
    out.mkdir(parents=True, exist_ok=True)
    for src in sys.argv[1:]:
        p = Path(src)
        text = extract_pdf(p) if p.suffix == ".pdf" else p.read_text(encoding="utf-8")
        (out / (p.stem + ".txt")).write_text(text, encoding="utf-8")
        print(f"{p.name}: {len(text)} chars -> {out / (p.stem + '.txt')}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add `pdfplumber` to dev deps and run**

Run:
```bash
cd ennam.kg.python && uv add --dev pdfplumber
uv run python scripts/extract_eval_corpus.py \
  ../C_ng_nh_An-master-record.pdf \
  ../2026-05-28-cang-dinh-an-deal-report.md \
  ../2026-05-29-cang-dinh-an-deal-report.md
```
Expected: prints char counts; the PDF `.txt` should be **materially larger than 1706 chars** (if not, the PDF is image-only → note that bucket-C OCR is a hard prerequisite and flag to the user).

- [ ] **Step 3: Commit**

```bash
git add ennam.kg.python/scripts/extract_eval_corpus.py ennam.kg.python/pyproject.toml ennam.kg.python/uv.lock
git commit -m "chore(eval): minimal text extractor for IMP-007 FR-4 corpus"
```

### Task 0.2: Build the labeled eval dataset

**Files:**
- Modify: `ennam.kg.python/tests/eval/dataset.json` (currently a template)

- [ ] **Step 1: Author 25-30 query pairs — MATCH the existing dataset.json schema**

The harness (`retrieval_eval.py`) reads `{project_id, pairs:[{lang, query, expected_node_id, kind}]}` and scores the **section** run by `expected_node_id ∈ returned ids` (`retrieval_eval.py:_score`). So keep that exact schema and **add two fields** for IMP-007: `past_cutoff` (bool — for the tail subset) and `expected_snippet` (a ~1-sentence passage string — used by the chunk run, where chunk ids aren't known until ingest). ~80% VI / ~20% EN, **biased toward answers PAST the first ~512 tokens of a long section**.

```json
{
  "project_id": "<eval-project-id>",
  "pairs": [
    {
      "lang": "vi",
      "query": "Rủi ro pháp lý về giấy phép môi trường của dự án là gì?",
      "expected_node_id": "FILL_AFTER_INGEST",
      "kind": "semantic_only",
      "past_cutoff": true,
      "expected_snippet": "<~1 sentence of the exact passage that answers it>"
    }
  ]
}
```

> `expected_node_id` = the **section** UUID that answers the query; it is **server-generated**, so it can only be filled **after** Task 0.3 Step 1 (ingest). Author the `query`/`kind`/`past_cutoff`/`expected_snippet` now; fill `expected_node_id` after ingest by inspecting which section answers each query. Note (Rule 12): labels are judgment; N≈30 is a smoke-gate, not a benchmark.

- [ ] **Step 2: Commit**

```bash
git add ennam.kg.python/tests/eval/dataset.json
git commit -m "test(eval): IMP-007 labeled retrieval pairs (VI-weighted, tail-biased)"
```

### Task 0.3: Baseline section-level eval + GATE decision

**Files:**
- Use: existing `ennam.kg.python/tests/eval/retrieval_eval.py` (section path, unchanged)

- [ ] **Step 1: Ingest the corpus into a dev project**

Bring up the stack (`docker compose up -d`), upload the three corpus docs through the normal ingest path so they become `document`/`document_section` nodes with embeddings.

- [ ] **Step 2: Run the section-level baseline**

Run:
```bash
cd ennam.kg.python && uv run python tests/eval/retrieval_eval.py
```
Record `recall@5`/`MRR` per mode (fulltext/semantic/hybrid) × lang, AND compute recall on the `past_cutoff: true` subset specifically.

- [ ] **Step 3: GATE DECISION (STOP/GO)**

- **GO** if section-level recall on the `past_cutoff` subset is materially below the full-set recall (truncation demonstrably misses tail answers). Record the baseline numbers; proceed to Phase 1.
- **STOP** if recall is saturated even on the tail subset → the current sections already retrieve fine. Write the finding into the spec §9 and **halt the build**. The layer stays committed-in-direction, unbuilt.

This decision is a human/PO checkpoint — surface the numbers and the recommendation, do not auto-proceed.

---

## Phase 1 — Go: register `document_chunk` node type + edge

> Unblocks Python chunk creation: Gate 1 (`validateStoreRequest`, `node.go:519`) rejects unknown node types, so the node type must exist in BOTH the DB CHECK and `config.yaml` before any chunk can be created.

### Task 1.1: Migration — extend the node_type CHECK

**Files:**
- Create: `ennam.kg.go/db/migrations/000059_document_chunk_node_type.up.sql`
- Create: `ennam.kg.go/db/migrations/000059_document_chunk_node_type.down.sql`

- [ ] **Step 1: Write the up migration**

(Mirror `000055`'s list, appending `document_chunk`.)

```sql
-- IMP-007: add document_chunk node type (passage-level retrieval unit below document_section).
ALTER TABLE knowledge_nodes DROP CONSTRAINT IF EXISTS knowledge_nodes_node_type_check;

ALTER TABLE knowledge_nodes ADD CONSTRAINT knowledge_nodes_node_type_check
    CHECK (node_type IN (
        'decision', 'concept', 'requirement', 'task',
        'architecture', 'discovery', 'session',
        'initiative', 'document', 'document_section', 'document_chunk', 'dataset', 'external'
    ));
```

- [ ] **Step 2: Write the down migration**

Dropping the value fails if `document_chunk` rows exist, so delete them first.

```sql
-- Revert IMP-007 document_chunk node type.
DELETE FROM knowledge_nodes WHERE node_type = 'document_chunk';

ALTER TABLE knowledge_nodes DROP CONSTRAINT IF EXISTS knowledge_nodes_node_type_check;

ALTER TABLE knowledge_nodes ADD CONSTRAINT knowledge_nodes_node_type_check
    CHECK (node_type IN (
        'decision', 'concept', 'requirement', 'task',
        'architecture', 'discovery', 'session',
        'initiative', 'document', 'document_section', 'dataset', 'external'
    ));
```

- [ ] **Step 3: Apply and verify up+down**

Run:
```bash
cd ennam.kg.go && make db-migrate && make db-migrate-version
make db-migrate-down && make db-migrate-version && make db-migrate
```
Expected: version goes 58→59, down to 58, back to 59 with no error. (Highest existing migration is 000058 — verified; 056-058 are unrelated repo-path/ai-model migrations that do NOT touch the node_type CHECK, so the base CHECK list above, taken from 000055, is still current.)

- [ ] **Step 4: Commit**

```bash
git add db/migrations/000059_document_chunk_node_type.*.sql
git commit -m "feat(db): add document_chunk node type (IMP-007 migration 000059)"
```

### Task 1.2: config.yaml — node_types block + edge_whitelist target

**Files:**
- Modify: `ennam.kg.go/config/config.yaml` (node_types after the `document_section` block ~line 280; edge_whitelist ~line 592)

- [ ] **Step 1: Add the `document_chunk` node_types block**

Insert directly after the `document_section` block (before `external:`):

```yaml
  document_chunk:
    display_name: "Document Chunk"
    description: "A passage-level chunk within a document section (IMP-007 RAG retrieval unit)"
    required:
      - title
    fields:
      title:
        type: string
        min_length: 1
        max_length: 500
        description: "Chunk label (section title + ordinal)"
      content:
        type: text
        max_length: 50000
        description: "Full passage text (embedded + FTS-indexed)"
      document_id:
        type: string
        max_length: 64
        description: "Parent document hub UUID"
      section_id:
        type: string
        max_length: 64
        description: "Parent document_section UUID"
      chunk_key:
        type: string
        max_length: 128
        description: "Deterministic natural key: {section_id}:{ordinal}"
      content_hash:
        type: string
        max_length: 64
        description: "sha256 of the passage text (idempotency change signal)"
      ordinal:
        type: integer
        description: "0-based chunk index within the section"
      line_start:
        type: integer
        description: "Document-absolute start line (1-based)"
      line_end:
        type: integer
        description: "Document-absolute end line (exclusive)"
      char_start:
        type: integer
        description: "Section-relative start char offset"
      char_end:
        type: integer
        description: "Section-relative end char offset"
```

Note: `title` `min_length` is 1 (not 3 like sections) because a chunk label may be short.

- [ ] **Step 2: Add the edge_whitelist target**

Append `document_chunk` to the **existing** `document_section --contains_section--> targets` rule (config.yaml ~line 592):

```yaml
  - source: document_section
    relationship: contains_section
    targets: [document_section, document_chunk]
    description: "Nested section hierarchy and passage-level chunks"
    constraints:
      allow_cross_project: false
```

- [ ] **Step 3: Verify config loads**

Run:
```bash
cd ennam.kg.go && go run ./cmd/kg-server/ 2>&1 | head -5
```
Expected: server boots without a config validation error (`validateEdgeRule` would reject an edge target not in `node_types`). Ctrl-C after it logs "listening".

- [ ] **Step 4: Commit**

```bash
git add config/config.yaml
git commit -m "feat(config): register document_chunk node type + contains_section edge (IMP-007)"
```

### Task 1.3: Go config constants

**Files:**
- Modify: `ennam.kg.go/internal/config/types.go` (after `NodeTypeDocumentSection` ~line 50; `ValidNodeTypes` map ~line 66)

- [ ] **Step 1: Write the failing test**

Add to `ennam.kg.go/internal/config/types_test.go` (create if absent):

```go
func TestValidNodeTypes_IncludesDocumentChunk(t *testing.T) {
	if !ValidNodeTypes[string(NodeTypeDocumentChunk)] {
		t.Fatal("document_chunk must be a valid node type")
	}
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/config/ -run TestValidNodeTypes_IncludesDocumentChunk`
Expected: FAIL — `NodeTypeDocumentChunk` undefined.

- [ ] **Step 3: Add the const + map entry**

```go
// in the NodeTypeName const block, after NodeTypeDocumentSection:
NodeTypeDocumentChunk NodeTypeName = "document_chunk"
```
```go
// in the ValidNodeTypes map literal, add:
string(NodeTypeDocumentChunk): true,
```

- [ ] **Step 4: Run to verify it passes**

Run: `go test ./internal/config/ -run TestValidNodeTypes_IncludesDocumentChunk`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/config/types.go internal/config/types_test.go
git commit -m "feat(config): NodeTypeDocumentChunk const + ValidNodeTypes (IMP-007)"
```

### Task 1.4: search.go validNodeTypes allowlist

**Files:**
- Modify: `ennam.kg.go/internal/handler/search.go:187-191`

- [ ] **Step 1: Add the entry**

In the `validNodeTypes` map literal in `HandleSearch`, add `document_chunk`:

```go
validNodeTypes := map[string]bool{
	"decision": true, "concept": true, "requirement": true,
	"task": true, "architecture": true, "discovery": true,
	"document": true, "document_section": true, "document_chunk": true, "dataset": true, "external": true,
}
```

- [ ] **Step 2: Build**

Run: `cd ennam.kg.go && go build ./...`
Expected: builds clean.

- [ ] **Step 3: Commit**

```bash
git add internal/handler/search.go
git commit -m "feat(search): accept document_chunk in kg_search node_type filter (IMP-007)"
```

### Task 1.5: Integration check — create a chunk node + edge end-to-end

**Files:**
- Test: `ennam.kg.go/internal/handler/document_chunk_smoke_test.go` (or reuse an existing integration test harness)

- [ ] **Step 1: Write a smoke test that creates a document_chunk node and a contains_section edge**

Use the existing node/edge create test helpers (follow the pattern in the handler tests that create `document_section`). Assert: node create returns 200/201 with a server id; edge `document_section --contains_section--> document_chunk` create returns success.

- [ ] **Step 2: Run**

Run: `go test ./internal/handler/ -run DocumentChunkSmoke -race`
Expected: PASS (proves Gate 1 + edge whitelist accept the new type).

- [ ] **Step 3: Commit**

```bash
git add internal/handler/document_chunk_smoke_test.go
git commit -m "test(handler): document_chunk node + edge create smoke (IMP-007)"
```

---

## Phase 2 — Go: `/search-chunks` handler + store filters

### Task 2.1: Add `DocumentID` filter to FTS store

**Files:**
- Modify: `ennam.kg.go/internal/store/search.go` (`SearchParams` struct ~line 33; both query builders ~line 195 and ~line 301)
- Test: `ennam.kg.go/internal/store/search_test.go`

- [ ] **Step 1: Write the failing test**

```go
func TestSearch_DocumentIDFilter(t *testing.T) {
	// Arrange: two document_chunk rows under different document_id values.
	// Act: Search with DocumentID = docA.
	// Assert: only docA chunks returned.
	store := newTestSearchStore(t)
	seedChunk(t, store, "docA", "alpha keyword")
	seedChunk(t, store, "docB", "alpha keyword")
	resp, err := store.Search(ctx, SearchParams{
		Query: "alpha", ProjectID: testProject, NodeTypes: []string{"document_chunk"},
		DocumentID: "docA", Limit: 10,
	})
	if err != nil { t.Fatal(err) }
	for _, r := range resp.Results {
		if r.Properties["document_id"] != "docA" {
			t.Fatalf("leaked doc: %v", r.Properties["document_id"])
		}
	}
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestSearch_DocumentIDFilter`
Expected: FAIL — `DocumentID` field undefined.

- [ ] **Step 3: Add the field + predicate**

In `SearchParams` (after `NodeTypes`):
```go
// DocumentID optionally restricts results to one document hub (IMP-007 chunk search).
DocumentID string `json:"document_id,omitempty"`
```

The two builders use **different** local idioms (both use `n.properties`, both use the `argIdx` counter). Add the predicate immediately **after the Status block** in each.

Builder 1 — the ILIKE fallback (~after `search.go:207`, the `if params.Status != ""` block that does `where += ...`):
```go
if params.DocumentID != "" {
	where += fmt.Sprintf(" AND n.properties->>'document_id' = $%d", argIdx)
	args = append(args, params.DocumentID)
	argIdx++
}
```

Builder 2 — the FTS path (~after `search.go:314`, the `if params.Status != ""` block that does `conditions = append(...)`). **This builder maintains BOTH `args` and `countArgs` — append to both or the count query breaks:**
```go
if params.DocumentID != "" {
	conditions = append(conditions, fmt.Sprintf("n.properties->>'document_id' = $%d", argIdx))
	args = append(args, params.DocumentID)
	countArgs = append(countArgs, params.DocumentID)
	argIdx++
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `go test ./internal/store/ -run TestSearch_DocumentIDFilter -race`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/store/search.go internal/store/search_test.go
git commit -m "feat(store): optional document_id filter on FTS search (IMP-007)"
```

### Task 2.2: Add `documentID` to SemanticSearch

**Files:**
- Modify: `ennam.kg.go/internal/store/node_embedding.go` (`SemanticSearch` ~line 100-132)
- Test: `ennam.kg.go/internal/store/node_embedding_test.go`

- [ ] **Step 1: Write the failing test**

```go
func TestSemanticSearch_DocumentIDFilter(t *testing.T) {
	// Seed two embedded chunks with different document_id; query vector matches both.
	// Assert SemanticSearch(..., documentID="docA") returns only docA.
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `go test ./internal/store/ -run TestSemanticSearch_DocumentIDFilter`
Expected: FAIL — signature mismatch (extra arg).

- [ ] **Step 3: Add the param + predicate**

Change the signature to add `documentID string` (after `nodeTypes []string`):
```go
func (s *NodeEmbeddingStore) SemanticSearch(
	ctx context.Context,
	projectID string,
	queryVec []float32,
	limit int,
	nodeTypes []string,
	documentID string,
) ([]SearchResult, error) {
```
After the `nodeTypes` clause (~line 124-132), append:
```go
if documentID != "" {
	args = append(args, documentID)
	conditions = append(conditions, fmt.Sprintf("n.properties->>'document_id' = $%d", len(args)))
}
```
> Match the exact JOIN alias used in the query (`n` per `node_embedding.go:119 JOIN knowledge_nodes n`). Update the two existing callers in `handler/search.go` (lines 226 and 317) to pass `""` for now — they'll be revisited.

- [ ] **Step 4: Update existing callers to compile**

In `internal/handler/search.go`, the two `SemanticSearch(...)` calls (semantic-only path ~line 226, hybrid arm ~line 317) get a trailing `, ""` argument.

- [ ] **Step 5: Run to verify it passes**

Run: `go test ./internal/store/ ./internal/handler/ -race`
Expected: PASS / compiles.

- [ ] **Step 6: Commit**

```bash
git add internal/store/node_embedding.go internal/store/node_embedding_test.go internal/handler/search.go
git commit -m "feat(store): optional document_id filter on SemanticSearch (IMP-007)"
```

### Task 2.3: `HandleSearchChunks` handler + route

**Files:**
- Modify: `ennam.kg.go/internal/handler/search.go` (new method + `RegisterRoutes` ~line 402)
- Test: `ennam.kg.go/internal/handler/search_chunks_test.go`

- [ ] **Step 1: Write the failing test**

```go
func TestHandleSearchChunks_ForcesChunkScope(t *testing.T) {
	// POST /search-chunks {query, project_id}; assert the handler searches
	// only document_chunk (mock store records the NodeTypes it received).
}
func TestHandleSearchChunks_FailSoftToFulltext(t *testing.T) {
	// embedder errors → still returns chunk fulltext results, not 502.
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestHandleSearchChunks`
Expected: FAIL — handler undefined.

- [ ] **Step 3: Implement the handler**

Reuse the hybrid machinery; force the chunk scope and thread `document_id`. Add near `HandleSearch`:

```go
const chunkSearchLimitMax = 10 // Qwen: passages are heavy (ecosystem §3.2)

var chunkScope = []string{"document_chunk"}

type searchChunksRequest struct {
	Query      string `json:"query"`
	ProjectID  string `json:"project_id"`
	DocumentID string `json:"document_id"`
	Mode       string `json:"mode"`
	Limit      int    `json:"limit"`
	Offset     int    `json:"offset"`
}

// HandleSearchChunks searches passage-level document_chunk nodes and returns the
// passage text + citation. Reuses the IMP-005 hybrid RRF + fail-soft ladder, but
// forces scope=document_chunk and supports a document_id filter. kg_search is untouched.
func (h *SearchHandler) HandleSearchChunks(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	var req searchChunksRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid JSON request body: "+err.Error())
		return
	}
	if req.Query == "" {
		errorResponse(w, http.StatusBadRequest, "query field is required")
		return
	}
	if req.ProjectID == "" {
		errorResponse(w, http.StatusBadRequest, "project_id field is required")
		return
	}
	if req.Mode == "" {
		req.Mode = "hybrid"
	}
	switch req.Mode {
	case "fulltext", "semantic", "hybrid":
	default:
		errorResponse(w, http.StatusBadRequest, "invalid mode: must be fulltext, semantic, or hybrid")
		return
	}
	limit := req.Limit
	if limit <= 0 {
		limit = 5
	}
	if limit > chunkSearchLimitMax {
		limit = chunkSearchLimitMax
	}

	h.logger.InfoContext(ctx, "kg_search_chunks",
		"query", req.Query, "project_id", req.ProjectID,
		"document_id", req.DocumentID, "mode", req.Mode, "limit", limit)

	// FULLTEXT-only or fail-soft path.
	runFulltext := func() {
		resp, err := h.store.Search(ctx, store.SearchParams{
			Query:      req.Query,
			ProjectID:  req.ProjectID,
			NodeTypes:  chunkScope,
			DocumentID: req.DocumentID,
			Limit:      limit,
			Offset:     req.Offset,
		})
		if err != nil {
			h.logger.ErrorContext(ctx, "chunk fulltext failed", "error", err)
			errorResponse(w, http.StatusInternalServerError, "search failed")
			return
		}
		writeJSON(w, http.StatusOK, resp)
	}

	if req.Mode == "fulltext" || h.nodeEmb == nil {
		runFulltext()
		return
	}

	// Embed the query for semantic/hybrid; fail-soft to fulltext.
	sr := &searchRequest{Query: req.Query, ProjectID: req.ProjectID}
	if err := h.ensureQueryEmbeddingForHybrid(ctx, sr); err != nil || len(sr.QueryEmbedding) == 0 {
		h.logger.WarnContext(ctx, "chunk search: embedding unavailable, fulltext fallback", "error", err)
		runFulltext()
		return
	}

	var (
		wg              sync.WaitGroup
		lexResp         *store.SearchResponse
		lexErr, semErr  error
		semRows         []store.SearchResult
	)
	wg.Add(2)
	go func() {
		defer wg.Done()
		if req.Mode == "semantic" {
			return
		}
		lexResp, lexErr = h.store.Search(ctx, store.SearchParams{
			Query: req.Query, ProjectID: req.ProjectID, NodeTypes: chunkScope,
			DocumentID: req.DocumentID, Limit: limit, Offset: 0,
		})
	}()
	go func() {
		defer wg.Done()
		semRows, semErr = h.nodeEmb.SemanticSearch(ctx, req.ProjectID, sr.QueryEmbedding, limit, chunkScope, req.DocumentID)
	}()
	wg.Wait()

	lists := make([][]store.SearchResult, 0, 2)
	if req.Mode != "semantic" && lexErr == nil && lexResp != nil {
		lists = append(lists, lexResp.Results)
	}
	if semErr == nil {
		lists = append(lists, semRows)
	}
	if len(lists) == 0 {
		h.logger.ErrorContext(ctx, "chunk search: all arms failed", "lex", lexErr, "sem", semErr)
		errorResponse(w, http.StatusInternalServerError, "search failed")
		return
	}
	fused := store.ReciprocalRankFusion(lists, h.rrfK, limit)
	writeJSON(w, http.StatusOK, &store.SearchResponse{
		Results: fused, TotalCount: len(fused), Limit: limit, Offset: 0, Query: req.Query,
	})
}
```

- [ ] **Step 4: Register the route**

In `RegisterRoutes` (~line 402), add:
```go
mux.HandleFunc("POST /api/v1/search-chunks", h.HandleSearchChunks)
```
> Match the existing route-registration style in that method (it may use a different mux pattern — mirror the `/search` registration exactly).

- [ ] **Step 5: Run to verify it passes**

Run: `go test ./internal/handler/ -run TestHandleSearchChunks -race`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add internal/handler/search.go internal/handler/search_chunks_test.go
git commit -m "feat(handler): POST /search-chunks (chunk-scoped hybrid RRF, document_id filter) (IMP-007)"
```

---

## Phase 3 — Go: bridge tool `kg_search_chunks`

### Task 3.1: Schema (34→35)

**Files:**
- Modify: `ennam.kg.go/internal/bridge/schema.go` (add schema near `kg_get_document` ~line 1181)
- Modify: `ennam.kg.go/internal/bridge/schema_test.go:50` (34→35), `internal/bridge/handler_test.go:276` (34→35)

- [ ] **Step 1: Update the count assertions to the new expected value (failing first)**

In `schema_test.go:50` change `!= 34` → `!= 35`; in `handler_test.go:276` change `!= 34` → `!= 35`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/bridge/ -run TestAllToolSchemasRegistered`
Expected: FAIL — got 34, expected 35.

- [ ] **Step 3: Add the schema**

After the `kg_get_document` block (~line 1200):
```go
// === kg_search_chunks (passage retrieval — routed HTTP-proxy tool, IMP-007) ===
schemas["kg_search_chunks"] = &ToolSchema{
	ToolName: "kg_search_chunks",
	Description: "Search document passages (fine-grained chunks) and return the matching passage text " +
		"with a precise citation (document, section, lines). Use to ground a cited answer in the exact source passage.",
	Properties: map[string]ParamSchema{
		"query": {
			Type:        TypeString,
			Required:    true,
			Description: "The search text",
		},
		"document_id": {
			Type:        TypeString,
			Required:    false,
			Description: "Optional: restrict to one document (hub UUID from a kg_search result)",
			Format:      "uuid",
			Pattern:     uuidPattern,
		},
		"project_id": {
			Type:        TypeString,
			Required:    false,
			Description: "Optional project id (falls back to the default project)",
		},
		"mode": {
			Type:        TypeString,
			Required:    false,
			Description: "Retrieval mode: fulltext | semantic | hybrid (default hybrid)",
			Enum:        []string{"fulltext", "semantic", "hybrid"},
		},
		"limit": {
			Type:        TypeInteger,
			Required:    false,
			Description: "Max results (default 5, max 10)",
		},
		"offset": {
			Type:        TypeInteger,
			Required:    false,
			Description: "Pagination offset (default 0)",
		},
	},
}
```
> If `ParamSchema` has no `Enum` field, match how other enum params are expressed in this file (grep for an existing `Enum` or `mode` param, e.g. `kg_search`'s `mode`); mirror it exactly.

- [ ] **Step 4: Run to verify it passes**

Run: `go test ./internal/bridge/ -run 'TestAllToolSchemasRegistered|Test.*34|Test.*Schema'`
Expected: PASS (35 schemas).

- [ ] **Step 5: Commit**

```bash
git add internal/bridge/schema.go internal/bridge/schema_test.go internal/bridge/handler_test.go
git commit -m "feat(bridge): kg_search_chunks tool schema (34->35) (IMP-007)"
```

### Task 3.2: Route (32→33)

**Files:**
- Modify: `ennam.kg.go/internal/bridge/client.go` (`toolRoutes` ~line 196)
- Modify: `ennam.kg.go/internal/bridge/client_test.go:216` (32→33), `internal/bridge/integration_test.go` (`TestIntegration_AllToolsRegistered` route list)

- [ ] **Step 1: Update the route-count assertion (failing first)**

In `client_test.go:216` change `!= 32` → `!= 33`. Add `kg_search_chunks` to the expected tool-name list in `integration_test.go`'s `TestIntegration_AllToolsRegistered`.

- [ ] **Step 2: Run to verify it fails**

Run: `go test ./internal/bridge/ -run 'TestIntegration_AllToolsRegistered|Test.*Route'`
Expected: FAIL — got 32, expected 33 / missing route.

- [ ] **Step 3: Add the route**

In `toolRoutes` (after `kg_search` ~line 199):
```go
"kg_search_chunks": {
	Method:       http.MethodPost,
	PathTemplate: apiPrefix + "/search-chunks",
},
```

- [ ] **Step 4: Run to verify it passes**

Run: `go test ./internal/bridge/ -race`
Expected: PASS (33 routes; `e2e_tools_test.go:805` relational assertion holds automatically — 35 = 33 + 2).

- [ ] **Step 5: Commit**

```bash
git add internal/bridge/client.go internal/bridge/client_test.go internal/bridge/integration_test.go
git commit -m "feat(bridge): route kg_search_chunks -> POST /search-chunks (32->33) (IMP-007)"
```

---

## Phase 4 — Python: chunker module (pure logic)

### Task 4.1: Paragraph-first chunker with offsets, key, hash, token guard

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/ingestion/pipeline/chunker.py`
- Test: `ennam.kg.python/tests/ingestion/test_chunker.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/ingestion/test_chunker.py
from ennam_kg.ingestion.pipeline.chunker import chunk_section, Chunk

def test_short_section_yields_single_chunk():
    text = "Một đoạn ngắn." * 3
    chunks = chunk_section(section_id="sec1", document_id="doc1",
                           section_title="T", text=text, section_line_start=10)
    assert len(chunks) == 1
    assert chunks[0].chunk_key == "sec1:0"
    assert chunks[0].ordinal == 0
    assert chunks[0].line_start == 10

def test_long_section_splits_into_multiple_chunks():
    para = "Đây là một đoạn văn dài về rủi ro pháp lý. " * 40  # ~1700 chars
    text = para + "\n\n" + ("Đoạn thứ hai về giấy phép môi trường. " * 40)
    chunks = chunk_section("sec2", "doc1", "T", text, 1)
    assert len(chunks) >= 2
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert all(c.chunk_key == f"sec2:{c.ordinal}" for c in chunks)

def test_no_chunk_exceeds_token_budget():
    text = "từ " * 5000  # very long
    chunks = chunk_section("sec3", "doc1", "T", text, 1)
    for c in chunks:
        assert c.token_estimate <= 512  # e5 window — never re-truncate

def test_offsets_map_to_document_lines():
    text = "Dòng một.\n\nDòng hai dài hơn để tách đoạn." * 50
    chunks = chunk_section("sec4", "doc1", "T", text, section_line_start=100)
    assert chunks[0].line_start == 100
    assert all(c.line_end >= c.line_start for c in chunks)

def test_content_hash_changes_with_content():
    a = chunk_section("s", "d", "T", "alpha", 1)[0]
    b = chunk_section("s", "d", "T", "beta", 1)[0]
    assert a.content_hash != b.content_hash
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_chunker.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the chunker**

```python
# src/ennam_kg/ingestion/pipeline/chunker.py
"""IMP-007: split a document_section's text into passage-level chunks.

Pure logic, no I/O. Paragraph-first greedy packing with a sentence/hard-cut
fallback; every chunk stays within the e5-small ~512-token window.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# Seed values — FR-4 (Phase 0) tunes these. CHUNK_SIZE must stay below the
# e5-small ~512-token window (≈1500-1800 chars VI) or embeddings re-truncate.
CHUNK_THRESHOLD = 1800  # sections <= this become a single 1:1 chunk
CHUNK_SIZE = 1200       # target chars per chunk
CHUNK_OVERLAP = 150     # char overlap between adjacent chunks
TOKEN_BUDGET = 512      # e5-small max_seq_length (hard ceiling)
_CHARS_PER_TOKEN = 3.0  # conservative VI estimate; keep CHUNK_SIZE/3 < TOKEN_BUDGET

_SENT_SPLIT = re.compile(r"(?<=[.!?。…])\s+")


@dataclass(frozen=True)
class Chunk:
    chunk_key: str
    ordinal: int
    section_id: str
    document_id: str
    title: str
    content: str
    content_hash: str
    line_start: int
    line_end: int
    char_start: int
    char_end: int
    token_estimate: int


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _token_estimate(text: str) -> int:
    return int(len(text) / _CHARS_PER_TOKEN) + 1


def _hard_cap() -> int:
    # never let a chunk exceed the token budget; cap chars accordingly
    return min(CHUNK_SIZE, int(TOKEN_BUDGET * _CHARS_PER_TOKEN))


def _split_oversized(block: str, cap: int) -> list[str]:
    """A paragraph bigger than cap: split on sentences, then hard-cut."""
    out: list[str] = []
    buf = ""
    for sent in _SENT_SPLIT.split(block):
        if len(buf) + len(sent) + 1 <= cap:
            buf = f"{buf} {sent}".strip()
        else:
            if buf:
                out.append(buf)
            while len(sent) > cap:
                out.append(sent[:cap])
                sent = sent[cap:]
            buf = sent
    if buf:
        out.append(buf)
    return out


def chunk_section(
    section_id: str,
    document_id: str,
    section_title: str,
    text: str,
    section_line_start: int,
) -> list[Chunk]:
    cap = _hard_cap()
    # Short section → single 1:1 chunk (BR-005). Still token-capped.
    if len(text) <= CHUNK_THRESHOLD and _token_estimate(text) <= TOKEN_BUDGET:
        pieces = [text]
    else:
        pieces = []
        cur = ""
        cur_start = 0
        cursor = 0
        for para in re.split(r"\n\s*\n", text):
            seg = para
            if len(seg) > cap:
                # flush current, then split the oversized paragraph
                if cur:
                    pieces.append(cur)
                    cur = ""
                pieces.extend(_split_oversized(seg, cap))
                continue
            if len(cur) + len(seg) + 2 <= CHUNK_SIZE:
                cur = f"{cur}\n\n{seg}".strip() if cur else seg
            else:
                if cur:
                    pieces.append(cur)
                cur = seg
        if cur:
            pieces.append(cur)

    chunks: list[Chunk] = []
    search_from = 0
    for ordinal, piece in enumerate(pieces):
        piece = piece.strip()
        if not piece:
            continue
        char_start = text.find(piece, search_from)
        if char_start < 0:
            char_start = search_from
        char_end = char_start + len(piece)
        search_from = max(char_start + 1, char_end - CHUNK_OVERLAP)
        line_start = section_line_start + text[:char_start].count("\n")
        line_end = section_line_start + text[:char_end].count("\n")
        chunks.append(
            Chunk(
                chunk_key=f"{section_id}:{ordinal}",
                ordinal=ordinal,
                section_id=section_id,
                document_id=document_id,
                title=f"{section_title} [{ordinal}]"[:500],
                content=piece[:50000],
                content_hash=_content_hash(piece),
                line_start=line_start,
                line_end=max(line_end, line_start),
                char_start=char_start,
                char_end=char_end,
                token_estimate=_token_estimate(piece),
            )
        )
    return chunks
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/ingestion/test_chunker.py -v`
Expected: PASS (all 5).

- [ ] **Step 5: Commit**

```bash
git add src/ennam_kg/ingestion/pipeline/chunker.py tests/ingestion/test_chunker.py
git commit -m "feat(ingest): passage chunker — paragraph-first, token-capped, deterministic key (IMP-007)"
```

---

## Phase 5 — Python: wire chunker into decompose

### Task 5.1: Create chunk nodes + embeddings + edges per section

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/pipeline/decompose.py` (inside the per-section loop, after `embed_node_ids.append(sec_id)` ~line 131)
- Test: `ennam.kg.python/tests/ingestion/test_nodes.py` (or the decompose test) with a mocked `KGClient`

- [ ] **Step 1: Write the failing test**

```python
async def test_decompose_creates_chunks_for_long_section(monkeypatch):
    # Arrange a mocked KGClient capturing create_node/create_edge/upsert calls.
    # Feed a draft whose section text exceeds CHUNK_THRESHOLD.
    # Assert: >=1 document_chunk node created with node_type document_chunk,
    #         properties carry chunk_key/section_id/document_id/content_hash,
    #         a contains_section edge document_section -> document_chunk is created,
    #         an embedding is upserted for each chunk node.
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_nodes.py -k chunk -v`
Expected: FAIL — no chunk nodes created.

- [ ] **Step 3: Implement chunk creation**

In `decompose.py`, after the section node + its embedding bookkeeping (after line 131), add a chunk pass. Mirror the existing `create_node`/`create_edge`/embedding idioms exactly:

```python
        # IMP-007: passage-level chunks below this section.
        from ennam_kg.ingestion.pipeline.chunker import chunk_section

        for ch in chunk_section(
            section_id=sec_id,
            document_id=hub_node_id,
            section_title=sec.title,
            text=sec.text,
            section_line_start=sec.line_start,
        ):
            try:
                ch_resp = await kg.create_node(
                    {
                        "project_id": project_id,
                        "node_type": "document_chunk",
                        "title": ch.title,
                        "status": "active",
                        "created_by": _CREATED_BY,
                        "properties": {
                            "content": ch.content,
                            "document_id": ch.document_id,
                            "section_id": ch.section_id,
                            "chunk_key": ch.chunk_key,
                            "content_hash": ch.content_hash,
                            "ordinal": ch.ordinal,
                            "line_start": ch.line_start,
                            "line_end": ch.line_end,
                            "char_start": ch.char_start,
                            "char_end": ch.char_end,
                        },
                    }
                )
                ch_obj = ch_resp.get("node") if isinstance(ch_resp.get("node"), dict) else ch_resp
                ch_id = str((ch_obj or {}).get("id") or "")
            except Exception as exc:
                logger.debug("create chunk skip %s: %s", ch.chunk_key, exc)
                continue
            if not ch_id:
                continue
            try:
                await kg.create_edge(
                    {
                        "project_id": project_id,
                        "source_id": sec_id,
                        "target_id": ch_id,
                        "relationship": "contains_section",
                        "created_by": _CREATED_BY,
                    }
                )
            except Exception as exc:
                logger.debug("chunk edge skip %s: %s", ch.chunk_key, exc)
            # queue the chunk embedding alongside section embeddings
            embed_texts.append(ch.content)
            embed_node_ids.append(ch_id)
```

> The existing embedding batch loop at lines 185-205 already encodes every `(embed_node_ids[i], embed_texts[i])` via `encode_passage` and `upsert_node_embeddings` — appending chunk ids/texts to those lists means chunks are embedded by the **same** path with the e5 `passage:` prefix. No new embedding code.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/ingestion/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ennam_kg/ingestion/pipeline/decompose.py tests/ingestion/test_nodes.py
git commit -m "feat(ingest): create document_chunk nodes + embeddings + edges in decompose (IMP-007)"
```

---

## Phase 6 — Python: backfill existing sections

### Task 6.1: `POST /admin/backfill-chunks` (differ-pattern idempotency)

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/api/admin.py`
- Test: `ennam.kg.python/tests/api/test_admin_backfill.py`

- [ ] **Step 1: Write the failing test**

```python
async def test_backfill_chunks_is_idempotent(monkeypatch):
    # Mock KGClient: existing document_section nodes for a project, no chunks yet.
    # First call: creates N chunks.
    # Second call (same content): creates 0 new chunks (matched by chunk_key + content_hash).
    # A section whose content changed: updates the affected chunk (same node id).
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/api/test_admin_backfill.py -v`
Expected: FAIL — endpoint missing.

- [ ] **Step 3: Implement the backfill endpoint (create/update/skip — NO delete; see limitation note)**

**Verified API facts (do not deviate):** the real client is `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py`. To **enumerate** all nodes of a type, use `get_nodes(project_id, node_type=...)` (POSTs `/api/v1/query`, limit 5000) — **NOT** `search_nodes`, which requires a `query` and is FTS. There is **no hard-delete endpoint** for knowledge nodes (only soft-archive), and `SemanticSearch` does not filter status, so a soft-archived chunk would still be returned and its embedding row would linger. Therefore backfill is **create/update/skip only** — orphan deletion is out of reach with the current API (see limitation).

Enumerate sections and existing chunks **once per project** (corpus is tiny), group chunks by `section_id` in memory, diff by `chunk_key`:

Match the existing `admin.py` conventions exactly (verified `admin.py:1-75`): `router = APIRouter()` is module-level; the client factory is **`_build_kg_client()`** (returns `KGClient(settings.go_api_url, settings.go_api_key)` — NOT a context manager); endpoints take an `authorization` Header and check the Bearer prefix; the route path is the **full** `/api/v1/admin/...`.

```python
# admin.py already imports: APIRouter, Header, HTTPException, BaseModel.
class BackfillChunksRequest(BaseModel):
    project_ids: list[str]


@router.post("/api/v1/admin/backfill-chunks")
async def backfill_chunks(body: BackfillChunksRequest, authorization: str | None = Header(default=None)) -> dict:
    """IMP-007: chunk already-ingested document_section nodes (idempotent: create/update/skip)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization header required")
    from ennam_kg.ingestion.pipeline.chunker import chunk_section
    kg = _build_kg_client()
    created = updated = skipped = 0
    for project_id in body.project_ids:
        sections = await kg.get_nodes(project_id, node_type="document_section")
        all_chunks = await kg.get_nodes(project_id, node_type="document_chunk")
        by_section: dict[str, dict[str, dict]] = {}
        for ch in all_chunks:
            p = ch.get("properties", {})
            by_section.setdefault(p.get("section_id", ""), {})[p.get("chunk_key", "")] = ch
        for sec in sections:
            sec_id = sec["id"]
            props = sec.get("properties", {})
            desired = chunk_section(
                section_id=sec_id,
                document_id=props.get("document_id", ""),
                section_title=sec.get("title", ""),
                text=props.get("content", ""),
                section_line_start=int(props.get("line_start", 1)),
            )
            existing_by_key = by_section.get(sec_id, {})
            for c in desired:
                cur = existing_by_key.get(c.chunk_key)
                if cur is None:
                    await _create_chunk(kg, project_id, sec_id, c)
                    created += 1
                elif cur.get("properties", {}).get("content_hash") != c.content_hash:
                    await _update_chunk(kg, project_id, cur["id"], c)  # change_reason="re-chunk"
                    updated += 1
                else:
                    skipped += 1
    return {"created": created, "updated": updated, "skipped": skipped}
```

> `_create_chunk` builds the same payload + edge + embedding as Phase 5 Task 5.1. `_update_chunk` calls `kg.update_node(node_id, {"properties": {...}, "change_reason": "re-chunk", "expected_version": ...})` — **`update_node` requires `change_reason`** (Gate); read `update_node` (`client.py:201`) for the exact body it sends and match it — then re-embeds via `upsert_node_embeddings` (the embedding row is keyed by node_id, so update is in-place).

> **LIMITATION (document in the endpoint docstring + spec):** because there is no node hard-delete, this backfill **cannot remove orphan chunks** (ordinals that disappear when `CHUNK_SIZE` shrinks). Re-running with the **same** `CHUNK_SIZE` is fully idempotent (no orphans). **Changing `CHUNK_SIZE` requires a full re-ingest of the affected documents**, not a backfill-diff. True orphan deletion needs a `DELETE /api/v1/nodes/{id}` endpoint (none today) — a separate follow-up, out of IMP-007 scope.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/api/test_admin_backfill.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ennam_kg/api/admin.py tests/api/test_admin_backfill.py
git commit -m "feat(admin): POST /admin/backfill-chunks (idempotent differ backfill) (IMP-007)"
```

---

## Phase 7 — Eval: extend harness + post-build proof

### Task 7.1: Extend `retrieval_eval.py` to the chunk path

**Files:**
- Modify: `ennam.kg.python/tests/eval/retrieval_eval.py`

- [ ] **Step 1: Add a chunk target + chunk-id scoring**

The current `_search` calls `/api/v1/search` (sections) and `_score` matches `expected_node_id`. Chunk ids are unknown at labeling time, so the chunk run matches the labeled `expected_snippet` against returned passage text. Add (mirroring the existing `_search`/`_score` auth + shape exactly — inline `Authorization: Bearer {TOKEN}`, **not** a `HEADERS` global, which does not exist):

```python
def _search_chunks(query: str, project_id: str, mode: str) -> list[str]:
    r = httpx.post(
        f"{API}/api/v1/search-chunks",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"query": query, "project_id": project_id, "mode": mode, "limit": TOP_K},
        timeout=30.0,
    )
    r.raise_for_status()
    return [hit.get("properties", {}).get("content", "") for hit in r.json().get("results", [])]


def _score_chunks(pairs, project_id, mode):
    """recall@5 / MRR for chunks: a hit is correct when expected_snippet is a substring."""
    hits = 0
    rr_sum = 0.0
    for p in pairs:
        passages = _search_chunks(p["query"], project_id, mode)
        rank = next((i for i, t in enumerate(passages) if p["expected_snippet"] in t), -1)
        if rank >= 0:
            hits += 1
            rr_sum += 1.0 / (rank + 1)
    n = len(pairs) or 1
    return hits / n, rr_sum / n
```
Gate the target via an arg (e.g. `--target chunks` → use `_score_chunks`/`_search_chunks`; default → the existing section `_search`/`_score`). Keep the section path byte-for-byte for the no-regression run.

- [ ] **Step 2: Populate chunks for the eval corpus FIRST (sequencing — required)**

The Phase 0 eval corpus was ingested **before** chunking existed (Phase 5 only chunks *new* ingests), so it currently has **zero** `document_chunk` nodes — a chunk eval would return nothing. Run the Phase 6 backfill on the eval project to chunk the already-ingested sections:

Run:
```bash
cd ennam.kg.python
curl -s -X POST localhost:8081/api/v1/admin/backfill-chunks \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $KG_TOKEN" \
  -d '{"project_ids": ["<eval-project-id>"]}'
```
Expected: `{"created": N, ...}` with N > 0. (Alternatively, re-ingest the three corpus docs so the steady-state path chunks them.)

- [ ] **Step 3: Run the section no-regression + chunk eval**

Run:
```bash
uv run python tests/eval/retrieval_eval.py                 # sections (regression guard)
uv run python tests/eval/retrieval_eval.py --target chunks # chunks (improvement)
```
Expected: section numbers == Phase 0 baseline (no regression); chunk recall@5/MRR on the full set **> section baseline**, with the `past_cutoff` subset showing the largest gain.

- [ ] **Step 4: Record results + commit**

Write the before/after table into the spec §9 / a results note.
```bash
git add tests/eval/retrieval_eval.py
git commit -m "test(eval): chunk-target retrieval eval + post-build proof (IMP-007)"
```

### Task 7.2: Full-suite verification

- [ ] **Step 1: Run both suites**

Run:
```bash
cd ennam.kg.go && make test
cd ../ennam.kg.python && uv run pytest
```
Expected: all green; bridge counts 35 schemas / 33 routes; `kg_search` regression tests unchanged.

- [ ] **Step 2: E2E sanity**

Ingest a long doc → `kg_search_chunks(query)` returns a passage past the section cutoff with citation `{document_id, section_id, chunk_id, line_start, line_end}` → chain `document_id` to `kg_get_document` for the filename.

---

## Self-Review (completed during authoring)

**Spec coverage:** FR-1 → Phase 4+5; FR-2 (`kg_search_chunks`) → Phase 2+3; FR-3 (provenance + edge) → Phase 1 (edge) + Phase 4 (offsets) + Phase 5 (wiring); FR-4 (eval gate) → Phase 0 + Phase 7; D6 change-sites → Phase 1 + Phase 3; D7 backfill → Phase 6; Qwen caps (limit max 10) → Phase 2 Task 2.3 + Phase 3 Task 3.1; chunk_id contract note → carried as `chunk_key` (Phase 4). All covered.

**Corrections folded in vs. the consultant proposal:** chunk_id is the **server UUID** (the API has no client-id field — verified `node.go:70-71`); idempotency uses the **differ natural-key pattern** (`chunk_key` + `content_hash`), not a deterministic node id; `CHUNK_SIZE` is **token-capped** to the e5 ~512 window; the eval harness is **extended**, not reused as-is.

**Verified during review (resolved, not open):** `ParamSchema` HAS an `Enum []string` field (`schema.go:37`) — schema code is correct. `RegisterRoutes` uses Go-1.22 `mux.HandleFunc("POST /api/v1/...", ...)` (`search.go:402`) — route code is correct. The real client is `packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py`; it has `create_node`/`update_node`/`create_edge`/`get_nodes`/`upsert_node_embeddings` but **no `delete_node`** — Phase 6 is create/update/skip only (limitation documented). Enumeration uses `get_nodes(project_id, node_type=...)`, not `search_nodes`.

**Open verification items the executor must confirm (1-line reads):** (1) the exact body `update_node` sends (`change_reason`, `expected_version`) for `_update_chunk` (`client.py:201`); (2) `get_nodes` returns each node's `properties` dict (assumed — confirm against a live `/query` response). The `store/search.go` predicate code is now given precisely for both builders (incl. `countArgs`).

---

## Execution

**Plan complete and saved to `docs/superpowers/plans/2026-06-17-rag-chunk-retrieval-layer.md`.**

Phase 0 is a hard STOP/GO gate — do not start Phase 1 until the baseline eval justifies the build (or the PO overrides).
