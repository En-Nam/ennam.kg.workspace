# BA-031 Phase 8a (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the closed-schema, provenanced, crash-recoverable **Pass 1 extraction** foundation for BA-031 — a single-pass closed-vocabulary graph with mandatory provenance and idempotent re-ingest — with the durable substrate and the resolution-candidates endpoint that Phase 8c will consume. No entity merging happens in 8a.

**Architecture:** Go owns vocabulary enforcement (config + DB CHECK + edge whitelist), the durable `chunk_extraction_state` table, the internal resolution-candidates endpoint (wraps existing `SemanticSearch`), and node/embedding persistence. Python owns Pass 1 LLM extraction + gleaning over canonical `document_chunk` nodes, computing embeddings locally and persisting via existing clients. Dispatch is Redis `LPUSH→BRPOP`; durability/idempotency/recovery come from `chunk_extraction_state`.

**Tech Stack:** Go (stdlib `net/http`, `database/sql`, golang-migrate), PostgreSQL 16 + pgvector, Redis 7, Python 3.12 (FastAPI worker, httpx, pytest), `multilingual-e5-small` (384-dim).

## Global Constraints

- **Closed graph vocabulary (9 lowercase types, OQ-NEW-1):** `person, organization, concept, event, document_ref, location, artifact, project, master_record`. Reuse existing `concept` + `project`; net-new: `person, organization, event, document_ref, location, artifact, master_record`. `document_ref` is distinct from the existing `document` (BA-025 container).
- **Extractable set = 8** (all except `master_record`, which is schema-reserved, BR-001.8).
- **Closed relation vocabulary (7):** `works_for, part_of, mentions, causes, related_to, derived_from, evidence`.
- **Drop, don't coerce** (BR-001.3): out-of-vocabulary entities/relations are discarded and counted, never remapped.
- **Mandatory provenance** (FR-003/NFR-254): every persisted node/edge carries non-empty `provenance[]` of `{source_doc_id, chunk_id, sentence_span:{start,end}}`. No provenance → reject before persist.
- **Qwen-portable prompts** (NFR-265): single-turn, JSON-in/JSON-out, no chat/multi-turn state.
- **Persist-then-resolve:** Pass 1 persists entities as `status=active`; `staged/extracting/.../resolved` are run-progress in `chunk_extraction_state`, never `node.status`.
- **Provider routing via BA-009** (`ai_client/client.py`); never call providers directly.
- **Go conventions:** `make -C ennam.kg.go test`, `make -C ennam.kg.go lint`, `make -C ennam.kg.go build`. Migrations are numbered files in `ennam.kg.go/db/migrations/` (next free numbers: **000061**, **000062**). `database/sql`, no ORM.
- **Python conventions:** `cd ennam.kg.python && uv run pytest`; ruff for lint. New code under `src/ennam_kg/extraction/`, tests under `tests/extraction/`.
- **Embedding text uses a symmetric e5 prefix** — the *same* prefix on both stored and query entity (OQ-003); default `query:` on both, confirmed in 8b.

---

## File Structure

**Go (`ennam.kg.go/`):**
- `db/migrations/000061_ba031_closed_vocab.up.sql` / `.down.sql` — extend `node_type` CHECK with the 7 net-new types; new `edge_whitelist`-backing data is config, not migration.
- `db/migrations/000062_chunk_extraction_state.up.sql` / `.down.sql` — new durable state table.
- `config/config.yaml` — add 7 `node_types` blocks + entity-resolution fields on `concept`/`project`; add 7 `edge_whitelist` rules.
- `internal/config/types.go` — add the 7 new `NodeTypeName` consts + register in `ValidNodeTypes`; add the 7 `EdgeTypeName` consts if not present.
- `internal/store/chunk_extraction_state.go` (+ `_test.go`) — CRUD/claim/skip-guard/recovery queries.
- `internal/handler/resolution_candidates.go` (+ `_test.go`) — `POST /api/v1/internal/resolution/candidates`.
- `internal/queue/messages.go` — add `extract_document` / `resolve_document` message types.

**Python (`ennam.kg.python/`):**
- `src/ennam_kg/extraction/__init__.py`
- `src/ennam_kg/extraction/schema.py` — closed-vocab constants + dataclasses for the extraction contract.
- `src/ennam_kg/extraction/parser.py` — parse + validate + drop-don't-coerce + span validation.
- `src/ennam_kg/extraction/gleaning.py` — bounded gleaning merge logic.
- `src/ennam_kg/extraction/pass1.py` — orchestrates: skip-guard → LLM → parse → gleaning → provenance → persist.
- `src/ennam_kg/extraction/embed.py` — symmetric-prefix embedding + upsert via existing client.
- `tests/extraction/` — mirrors the above.

---

## Task 1: Register the BA-031 closed vocabulary (config + types + DB CHECK + edge whitelist)

Implements OQ-001 (all 3 enforcement surfaces) + OQ-NEW-1 naming. This is the hard prerequisite — nothing persists until it lands.

**Files:**
- Create: `ennam.kg.go/db/migrations/000061_ba031_closed_vocab.up.sql`, `...down.sql`
- Modify: `ennam.kg.go/internal/config/types.go` (add consts + `ValidNodeTypes` entries)
- Modify: `ennam.kg.go/config/config.yaml` (`node_types` blocks + `edge_whitelist` rules)
- Test: `ennam.kg.go/internal/config/types_test.go`, `ennam.kg.go/internal/service/node_test.go`

**Interfaces:**
- Produces: `config.NodeTypePerson … NodeTypeMasterRecord` (`NodeTypeName` consts); `config.ValidNodeTypes` returns `true` for all 9; edge whitelist accepts the 7 relations between the allowed type pairs.

- [ ] **Step 1: Write the failing test for the new node-type consts**

In `ennam.kg.go/internal/config/types_test.go`, append:

```go
func TestValidNodeTypes_IncludesBA031ClosedVocab(t *testing.T) {
	want := []NodeTypeName{
		NodeTypePerson, NodeTypeOrganization, NodeTypeEvent,
		NodeTypeDocumentRef, NodeTypeLocation, NodeTypeArtifact,
		NodeTypeMasterRecord, NodeTypeConcept, NodeTypeProject,
	}
	for _, nt := range want {
		if !ValidNodeTypes[nt] {
			t.Errorf("ValidNodeTypes missing closed-vocab type %q", nt)
		}
	}
}
```

- [ ] **Step 2: Run it to confirm it fails to compile**

Run: `cd ennam.kg.go && go test ./internal/config/ -run TestValidNodeTypes_IncludesBA031ClosedVocab`
Expected: FAIL — `undefined: NodeTypePerson` (consts not declared yet).

- [ ] **Step 3: Add the consts + register in `ValidNodeTypes`**

In `internal/config/types.go`, add to the `NodeTypeName` const block:

```go
	NodeTypePerson       NodeTypeName = "person"
	NodeTypeOrganization NodeTypeName = "organization"
	NodeTypeEvent        NodeTypeName = "event"
	NodeTypeDocumentRef  NodeTypeName = "document_ref"
	NodeTypeLocation     NodeTypeName = "location"
	NodeTypeArtifact     NodeTypeName = "artifact"
	NodeTypeMasterRecord NodeTypeName = "master_record"
```

And add each to the `ValidNodeTypes` map literal (`concept`/`project` are already present):

```go
	NodeTypePerson:       true,
	NodeTypeOrganization: true,
	NodeTypeEvent:        true,
	NodeTypeDocumentRef:  true,
	NodeTypeLocation:     true,
	NodeTypeArtifact:     true,
	NodeTypeMasterRecord: true,
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `cd ennam.kg.go && go test ./internal/config/ -run TestValidNodeTypes_IncludesBA031ClosedVocab`
Expected: PASS.

- [ ] **Step 5: Write the DB migration**

`db/migrations/000061_ba031_closed_vocab.up.sql` — copy the current CHECK from `000059` and add the 7 net-new types (concept/document/project already present from earlier migrations; document_ref/person/etc are new):

```sql
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

> Note: `project` may already be a permitted type via an earlier migration; including it in the `IN (...)` list is idempotent. Verify against the most recent `*_node_type*.up.sql` before finalizing and keep the union of all currently-allowed values plus the 7 new ones.

`db/migrations/000061_ba031_closed_vocab.down.sql` — restore the exact `000059` CHECK list (without the 7 new types), and `DELETE FROM knowledge_nodes WHERE node_type IN ('person','organization','event','document_ref','location','artifact','master_record');` before re-adding the constraint.

- [ ] **Step 6: Add the 7 `node_types` schema blocks + 2 field extensions in `config.yaml`**

Under `node_types:` in `ennam.kg.go/config/config.yaml`, add one block per net-new type, following the existing block shape (`display_name`, `description`, `required`, `fields`). Required fields for every BA-031 entity type: `title` (= canonical_name), plus the JSONB-backed `canonical_name`, `aliases`, `subtype`, `description`, `provenance` declared as fields. Example for `person`:

```yaml
  person:
    display_name: "Person"
    description: "A real-world person extracted from document text (BA-031)"
    required:
      - title
      - canonical_name
    fields:
      title:
        type: string
        min_length: 1
        max_length: 200
        description: "Canonical name (mirrors canonical_name)"
      canonical_name:
        type: string
        min_length: 1
        max_length: 200
        description: "Authoritative entity name"
      aliases:
        type: array
        description: "Alternate names; unioned on merge"
      subtype:
        type: string
        max_length: 100
        description: "Free-text refinement (e.g. engineer)"
      description:
        type: text
        max_length: 2000
        description: "Short description; re-summarised on merge"
      provenance:
        type: array
        description: "Source references {source_doc_id, chunk_id, sentence_span}"
```

Repeat for `organization, event, document_ref, location, artifact, master_record` (same field set; adjust `display_name`/`description`). For `concept` and `project` (already defined), **add** `canonical_name`, `aliases`, `subtype`, `provenance` to their `fields` **without** adding them to `required` (so existing producers don't break) — only `canonical_name` may be required if no existing producer omits it; default to NOT requiring to stay backward-compatible.

- [ ] **Step 7: Add the 7 edge-whitelist rules in `config.yaml`**

Under `edge_whitelist:` add rules expressing the closed relations (illustrative target from spec §6 — confirm the exact allowed pairs are what the team wants):

```yaml
  - source: person
    relationship: works_for
    targets: [organization, project]
  - source: organization
    relationship: part_of
    targets: [organization]
  - source: "*"
    relationship: mentions
    targets: ["*"]
  - source: event
    relationship: causes
    targets: [event, concept]
  - source: "*"
    relationship: related_to
    targets: ["*"]
  - source: document_ref
    relationship: derived_from
    targets: [document_ref, artifact]
  - source: "*"
    relationship: evidence
    targets: [document_ref, artifact]
```

> If `edge_whitelist` does not support `"*"` wildcards, enumerate the concrete pairs instead. Check `internal/validation/edge_whitelist.go` for wildcard handling before writing these.

- [ ] **Step 8: Write a service-layer acceptance test that a `person` node is accepted and a bogus type rejected**

In `ennam.kg.go/internal/service/node_test.go`, add a test that `StoreNode` with `NodeType: "person"` (and a `canonical_name`) succeeds, and with `NodeType: "vehicle"` returns a `ValidationError` whose message contains `unknown node_type`.

```go
func TestStoreNode_AcceptsBA031Person_RejectsUnknown(t *testing.T) {
	// Arrange: NodeService wired with the loaded config (see existing node_test.go setup).
	// Act + Assert (person accepted)
	_, err := svc.StoreNode(ctx, StoreNodeRequest{
		ProjectID: projID, NodeType: "person", Title: "Nguyễn Văn A",
		Properties: map[string]any{"canonical_name": "Nguyễn Văn A"},
	})
	if err != nil {
		t.Fatalf("expected person accepted, got %v", err)
	}
	// Act + Assert (unknown rejected)
	_, err = svc.StoreNode(ctx, StoreNodeRequest{
		ProjectID: projID, NodeType: "vehicle", Title: "Truck",
	})
	if err == nil || !strings.Contains(err.Error(), "unknown node_type") {
		t.Fatalf("expected unknown node_type error, got %v", err)
	}
}
```

> Match the existing `node_test.go` harness (it constructs `NodeService` with a mock repo + loaded config). Reuse that setup verbatim rather than inventing a new one.

- [ ] **Step 9: Run config + service tests, lint, build**

Run: `cd ennam.kg.go && go test ./internal/config/ ./internal/service/ && make lint && make build`
Expected: PASS / clean.

- [ ] **Step 10: Apply migration locally and verify the CHECK accepts a `person` row**

Run: `cd ennam.kg.go && make migrate` (or the project's migrate-up target), then a psql probe inserting a `person` node and asserting success; insert a `vehicle` node and assert the CHECK rejects it.

- [ ] **Step 11: Commit**

```bash
git add ennam.kg.go/db/migrations/000061_ba031_closed_vocab.up.sql \
        ennam.kg.go/db/migrations/000061_ba031_closed_vocab.down.sql \
        ennam.kg.go/internal/config/types.go ennam.kg.go/internal/config/types_test.go \
        ennam.kg.go/config/config.yaml ennam.kg.go/internal/service/node_test.go
git commit -m "feat(ba031): register closed vocab at 3 surfaces (config node_types + ValidNodeTypes + DB CHECK + edge whitelist)"
```

---

## Task 2: `chunk_extraction_state` table + Go store (durability, idempotency, recovery)

Implements FR-NEW-3 / BR-007.5 / BR-007.6 / NFR-263. The skip-guard's storage home and the recovery substrate.

**Files:**
- Create: `ennam.kg.go/db/migrations/000062_chunk_extraction_state.up.sql`, `...down.sql`
- Create: `ennam.kg.go/internal/store/chunk_extraction_state.go`, `...chunk_extraction_state_test.go`

**Interfaces:**
- Produces:
  - `type ChunkExtractionState struct { ChunkID, ProjectID, ContentHash, Status, RunID string; GleaningRoundsUsed, DroppedCount int; UpdatedAt time.Time }`
  - `func (s *ChunkExtractionStateStore) Get(ctx, chunkID string) (*ChunkExtractionState, bool, error)`
  - `func (s *ChunkExtractionStateStore) ShouldSkip(ctx, chunkID, contentHash string) (bool, error)` — true iff a row exists with the same `content_hash` and `status` in (`extracted`,`resolved`).
  - `func (s *ChunkExtractionStateStore) Upsert(ctx, st ChunkExtractionState) error`
  - `func (s *ChunkExtractionStateStore) FindStale(ctx, olderThan time.Duration, statuses []string) ([]ChunkExtractionState, error)` — for the recovery sweep.

- [ ] **Step 1: Write the migration**

`000062_chunk_extraction_state.up.sql`:

```sql
CREATE TABLE IF NOT EXISTS chunk_extraction_state (
    chunk_id             UUID NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    project_id           UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content_hash         TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN (
                            'pending','extracting','extracted','resolving','resolved','extract_failed')),
    run_id               UUID NOT NULL,
    gleaning_rounds_used INTEGER NOT NULL DEFAULT 0,
    dropped_count        INTEGER NOT NULL DEFAULT 0,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (chunk_id)
);
CREATE INDEX IF NOT EXISTS idx_chunk_extraction_state_status ON chunk_extraction_state (status, updated_at);
CREATE INDEX IF NOT EXISTS idx_chunk_extraction_state_run ON chunk_extraction_state (run_id);
```

`...down.sql`: `DROP TABLE IF EXISTS chunk_extraction_state;`

- [ ] **Step 2: Write the failing store test for `ShouldSkip`**

In `chunk_extraction_state_test.go` (use the existing store test harness — a real test DB via the project's test helper, mirroring `node_embedding_test.go`):

```go
func TestShouldSkip_TrueOnUnchangedExtracted(t *testing.T) {
	s := NewChunkExtractionStateStore(testDB)
	st := ChunkExtractionState{ChunkID: chunkID, ProjectID: projID,
		ContentHash: "h1", Status: "extracted", RunID: runID}
	if err := s.Upsert(ctx, st); err != nil { t.Fatal(err) }

	skip, err := s.ShouldSkip(ctx, chunkID, "h1")
	if err != nil { t.Fatal(err) }
	if !skip { t.Fatal("expected skip=true for unchanged extracted chunk") }

	skip, _ = s.ShouldSkip(ctx, chunkID, "h2-changed")
	if skip { t.Fatal("expected skip=false when content_hash changed") }
}
```

- [ ] **Step 3: Run to confirm failure**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestShouldSkip_TrueOnUnchangedExtracted`
Expected: FAIL — `undefined: NewChunkExtractionStateStore`.

- [ ] **Step 4: Implement the store**

Create `chunk_extraction_state.go` with the struct, `NewChunkExtractionStateStore(db *sql.DB)`, and the 5 methods. `ShouldSkip`:

```go
func (s *ChunkExtractionStateStore) ShouldSkip(ctx context.Context, chunkID, contentHash string) (bool, error) {
	var n int
	err := s.db.QueryRowContext(ctx, `
		SELECT COUNT(1) FROM chunk_extraction_state
		WHERE chunk_id = $1 AND content_hash = $2 AND status IN ('extracted','resolved')`,
		chunkID, contentHash).Scan(&n)
	if err != nil {
		return false, fmt.Errorf("should-skip %s: %w", chunkID, err)
	}
	return n > 0, nil
}
```

`Upsert` uses `INSERT ... ON CONFLICT (chunk_id) DO UPDATE SET content_hash=EXCLUDED.content_hash, status=EXCLUDED.status, run_id=EXCLUDED.run_id, gleaning_rounds_used=EXCLUDED.gleaning_rounds_used, dropped_count=EXCLUDED.dropped_count, updated_at=NOW()`. `FindStale` selects rows where `status = ANY($1)` and `updated_at < NOW() - $2::interval`.

- [ ] **Step 5: Run to confirm pass + add a `FindStale` test**

Add `TestFindStale_ReturnsStuckRows` (insert a row with status `extracting` and `updated_at` 1 hour ago via a direct UPDATE, assert it is returned for `statuses=['extracting','resolving']`, `olderThan=10*time.Minute`).
Run: `cd ennam.kg.go && go test ./internal/store/ -run 'TestShouldSkip_TrueOnUnchangedExtracted|TestFindStale_ReturnsStuckRows'`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ennam.kg.go/db/migrations/000062_chunk_extraction_state.up.sql \
        ennam.kg.go/db/migrations/000062_chunk_extraction_state.down.sql \
        ennam.kg.go/internal/store/chunk_extraction_state.go \
        ennam.kg.go/internal/store/chunk_extraction_state_test.go
git commit -m "feat(ba031): chunk_extraction_state table + store (skip-guard + recovery)"
```

---

## Task 3: Internal resolution-candidates endpoint (Go)

Implements FR-NEW-4 / FR-004. Wraps the existing `SemanticSearch` (which already returns a cosine `rank`) and applies the `min_similarity` floor + same-type + project scope. Consumed by Phase 8c; built now because it's pure Go and independently testable.

**Files:**
- Create: `ennam.kg.go/internal/handler/resolution_candidates.go`, `...resolution_candidates_test.go`
- Modify: `ennam.kg.go/internal/handler/routes.go` (register route)

**Interfaces:**
- Consumes: `store.NodeEmbeddingStore.SemanticSearch(ctx, projectID, queryEmbedding []float32, topK int, nodeTypes []string, documentID string) ([]store.SearchResult, error)` (`SearchResult` carries `Rank float64`).
- Produces: `POST /api/v1/internal/resolution/candidates` accepting JSON `{project_id, node_type, embedding:[]float32, top_k, min_similarity}` and returning `{candidates:[{node_id, title, rank}]}` filtered to `rank >= min_similarity`.

- [ ] **Step 1: Write the failing handler test**

`resolution_candidates_test.go` — use a fake embedding store returning two results with ranks 0.88 and 0.70:

```go
func TestResolutionCandidates_FiltersBelowThreshold(t *testing.T) {
	fake := &fakeSemanticSearcher{results: []store.SearchResult{
		{NodeID: "a", Title: "Nguyễn Văn A", Rank: 0.88},
		{NodeID: "b", Title: "Someone Else", Rank: 0.70},
	}}
	h := NewResolutionCandidatesHandler(fake, testLogger)
	body := `{"project_id":"p1","node_type":"person","embedding":[0.1,0.2],"top_k":5,"min_similarity":0.82}`
	rr := doPOST(t, h.Handle, "/api/v1/internal/resolution/candidates", body)
	if rr.Code != 200 { t.Fatalf("want 200, got %d", rr.Code) }
	var resp struct{ Candidates []struct{ NodeID string `json:"node_id"` } `json:"candidates"` }
	json.Unmarshal(rr.Body.Bytes(), &resp)
	if len(resp.Candidates) != 1 || resp.Candidates[0].NodeID != "a" {
		t.Fatalf("expected only node a above threshold, got %+v", resp.Candidates)
	}
}
```

Define a minimal `SemanticSearcher` interface in the handler file (`SemanticSearch(...) ([]store.SearchResult, error)`) so the fake satisfies it.

- [ ] **Step 2: Run to confirm failure**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestResolutionCandidates_FiltersBelowThreshold`
Expected: FAIL — `undefined: NewResolutionCandidatesHandler`.

- [ ] **Step 3: Implement the handler**

`resolution_candidates.go`: decode the request; default `top_k=5`, `min_similarity=0.82`; call `SemanticSearch(ctx, req.ProjectID, req.Embedding, req.TopK, []string{req.NodeType}, "")`; filter results to `Rank >= req.MinSimilarity`; return the candidate JSON. Validate `project_id`, `node_type` (must be in `config.ValidNodeTypes`), and non-empty `embedding`; 400 on invalid input (fail loud).

- [ ] **Step 4: Run to confirm pass**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestResolutionCandidates_FiltersBelowThreshold`
Expected: PASS.

- [ ] **Step 5: Register the route**

In `routes.go` (or the relevant mux registration alongside other internal/admin routes), wire `mux.HandleFunc("POST /api/v1/internal/resolution/candidates", h.Handle)`. Add an auth/role guard consistent with other `/internal/` or admin routes.

- [ ] **Step 6: Run handler tests + lint + build, commit**

Run: `cd ennam.kg.go && go test ./internal/handler/ && make lint && make build`

```bash
git add ennam.kg.go/internal/handler/resolution_candidates.go \
        ennam.kg.go/internal/handler/resolution_candidates_test.go \
        ennam.kg.go/internal/handler/routes.go
git commit -m "feat(ba031): internal resolution-candidates endpoint (min_similarity over SemanticSearch)"
```

---

## Task 4: Queue message types for extract/resolve dispatch

Implements the Redis dispatch leg (Go publisher side + Python consumer dispatch). Durability/recovery come from Task 2; this is transport only.

**Files:**
- Modify: `ennam.kg.go/internal/queue/messages.go` (add message structs + type constants)
- Modify: `ennam.kg.python/src/ennam_kg/queue/messages.py` (mirror) and `consumer.py` (dispatch on type)
- Test: `ennam.kg.go/internal/queue/messages_test.go`, `ennam.kg.python/tests/queue/test_messages.py`

**Interfaces:**
- Produces: Go `QueueMessage{Type:"extract_document", DocID, RunID, ProjectID}` and `{Type:"resolve_document", ...}`, JSON-serialised identically on both sides; Python `parse_message(raw) -> Message` dispatching by `type`.

- [ ] **Step 1: Write the Go failing test for round-trip serialization**

```go
func TestExtractDocumentMessage_RoundTrip(t *testing.T) {
	m := ExtractDocumentMessage{DocID: "d1", RunID: "r1", ProjectID: "p1"}
	b, _ := json.Marshal(m.Envelope())
	var env Envelope
	json.Unmarshal(b, &env)
	if env.Type != "extract_document" || env.DocID != "d1" {
		t.Fatalf("round-trip mismatch: %+v", env)
	}
}
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd ennam.kg.go && go test ./internal/queue/ -run TestExtractDocumentMessage_RoundTrip`
Expected: FAIL — undefined types.

- [ ] **Step 3: Implement the message types in Go**

Add `extract_document` / `resolve_document` constants + structs + an `Envelope()` method to `messages.go`, matching the existing message-envelope convention already in that file (read the existing indexing message for the exact shape and field names — mirror it; do not invent a new envelope format).

- [ ] **Step 4: Run to confirm pass**

Run: `cd ennam.kg.go && go test ./internal/queue/ -run TestExtractDocumentMessage_RoundTrip`
Expected: PASS.

- [ ] **Step 5: Mirror in Python + dispatch**

In `queue/messages.py` add the two message dataclasses + a `parse_message(raw: dict)` that returns the right type by `raw["type"]`. In `consumer.py`, extend the existing BRPOP dispatch loop to route `extract_document` → Pass 1 entrypoint (Task 5's `run_pass1`) and `resolve_document` → a stub that logs "resolution deferred to 8c" (8a does not resolve).

- [ ] **Step 6: Write + run the Python test**

`tests/queue/test_messages.py`:

```python
def test_parse_extract_document():
    m = parse_message({"type": "extract_document", "doc_id": "d1", "run_id": "r1", "project_id": "p1"})
    assert m.doc_id == "d1" and m.type == "extract_document"
```

Run: `cd ennam.kg.python && uv run pytest tests/queue/test_messages.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ennam.kg.go/internal/queue/messages.go ennam.kg.go/internal/queue/messages_test.go \
        ennam.kg.python/src/ennam_kg/queue/messages.py ennam.kg.python/src/ennam_kg/queue/consumer.py \
        ennam.kg.python/tests/queue/test_messages.py
git commit -m "feat(ba031): extract/resolve queue message types (Go + Python dispatch)"
```

---

## Task 5: Pass 1 extraction parser — closed vocab, drop-don't-coerce, span validation (Python)

Implements FR-001 + FR-003 (provenance shaping) deterministically. The LLM call itself is mocked; this task tests the **parse/validate/drop** logic that must be correct regardless of model.

**Files:**
- Create: `src/ennam_kg/extraction/__init__.py`, `schema.py`, `parser.py`
- Test: `tests/extraction/test_parser.py`

**Interfaces:**
- Produces:
  - `EXTRACTABLE_NODE_TYPES = {"person","organization","concept","event","document_ref","location","artifact","project"}` and `CLOSED_EDGE_TYPES = {"works_for","part_of","mentions","causes","related_to","derived_from","evidence"}` in `schema.py`.
  - `@dataclass ExtractedEntity{temp_id, type, canonical_name, subtype, aliases, description, sentence_span:(int,int)}`
  - `@dataclass ExtractedRelation{type, source, target, sentence_span, confidence}`
  - `@dataclass ParseResult{entities, relations, dropped_count}`
  - `parse_extraction(raw: dict, chunk_len: int) -> ParseResult` — drops out-of-vocab types (incl. `master_record`), drops entities with `canonical_name` empty or `sentence_span` out of `[0, chunk_len]`, drops relations whose `source`/`target` `temp_id` is not among kept entities; increments `dropped_count` for each drop.

- [ ] **Step 1: Write the failing parser tests**

`tests/extraction/test_parser.py`:

```python
from ennam_kg.extraction.parser import parse_extraction

def test_keeps_valid_drops_out_of_vocab():
    raw = {"entities": [
        {"temp_id":"e1","type":"person","canonical_name":"Nguyễn Văn A","subtype":"engineer",
         "aliases":["Mr. A"],"description":"d","sentence_span":{"start":0,"end":10}},
        {"temp_id":"e2","type":"vehicle","canonical_name":"Truck","sentence_span":{"start":0,"end":5}},
        {"temp_id":"e3","type":"master_record","canonical_name":"MR","sentence_span":{"start":0,"end":2}},
    ], "relations": []}
    res = parse_extraction(raw, chunk_len=100)
    assert [e.type for e in res.entities] == ["person"]
    assert res.dropped_count == 2  # vehicle + master_record

def test_drops_out_of_range_span_and_orphan_relation():
    raw = {"entities": [
        {"temp_id":"e1","type":"person","canonical_name":"A","sentence_span":{"start":0,"end":9999}},
    ], "relations": [
        {"type":"works_for","source":"e1","target":"eX","sentence_span":{"start":0,"end":5}},
    ]}
    res = parse_extraction(raw, chunk_len=100)
    assert res.entities == []            # span out of range
    assert res.relations == []           # orphan (e1 dropped, eX never existed)
    assert res.dropped_count >= 2
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd ennam.kg.python && uv run pytest tests/extraction/test_parser.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `schema.py` + `parser.py`**

`schema.py` declares the constant sets + dataclasses. `parser.py` implements `parse_extraction` with explicit, early-return drop logic (no coercion): validate type ∈ `EXTRACTABLE_NODE_TYPES`; `canonical_name` non-empty; `0 <= start <= end <= chunk_len`; collect kept `temp_id`s; keep a relation only if its `type ∈ CLOSED_EDGE_TYPES` and both endpoints are kept. Count every drop into `dropped_count`.

- [ ] **Step 4: Run to confirm pass**

Run: `cd ennam.kg.python && uv run pytest tests/extraction/test_parser.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/extraction/__init__.py \
        ennam.kg.python/src/ennam_kg/extraction/schema.py \
        ennam.kg.python/src/ennam_kg/extraction/parser.py \
        ennam.kg.python/tests/extraction/test_parser.py
git commit -m "feat(ba031): Pass1 extraction parser (closed vocab, drop-don't-coerce, span validation)"
```

---

## Task 6: Gleaning loop (Python)

Implements FR-002 deterministically: bounded rounds, early-stop, intra-chunk de-dup by case-insensitive `canonical_name` (alias union). LLM mocked.

**Files:**
- Create: `src/ennam_kg/extraction/gleaning.py`
- Test: `tests/extraction/test_gleaning.py`

**Interfaces:**
- Produces: `merge_gleaned(existing: list[ExtractedEntity], gleaned: list[ExtractedEntity]) -> tuple[list[ExtractedEntity], int]` — returns (merged_entities, new_count); a gleaned entity whose lowercased `canonical_name` matches an existing one has its `aliases` unioned in (no duplicate entity) and does not count as new.
- `run_gleaning(extract_round_fn, initial: ParseResult, max_rounds: int) -> ParseResult` — calls `extract_round_fn()` up to `max_rounds` times; stops when a round yields 0 new entities/relations; records rounds used (returned via a field or tuple).

- [ ] **Step 1: Write the failing tests**

```python
from ennam_kg.extraction.gleaning import merge_gleaned, run_gleaning
from ennam_kg.extraction.schema import ExtractedEntity

def _p(name, aliases=()):
    return ExtractedEntity(temp_id=name, type="person", canonical_name=name,
                           subtype="", aliases=list(aliases), description="", sentence_span=(0,1))

def test_merge_unions_alias_no_duplicate():
    existing = [_p("Nguyễn Văn A")]
    gleaned = [_p("nguyễn văn a", aliases=["Mr. A"])]
    merged, new = merge_gleaned(existing, gleaned)
    assert len(merged) == 1
    assert "Mr. A" in merged[0].aliases
    assert new == 0

def test_run_gleaning_early_stops_on_no_new():
    rounds = {"n": 0}
    def round_fn():
        rounds["n"] += 1
        return []  # nothing new
    res, used = run_gleaning(round_fn, initial_entities=[_p("A")], max_rounds=2)
    assert used == 1            # one gleaning round ran, found nothing, stopped
    assert rounds["n"] == 1
```

> Adjust the `run_gleaning` signature/return to whatever you implement; keep the test asserting (a) early-stop and (b) round-count.

- [ ] **Step 2: Run to confirm failure**

Run: `cd ennam.kg.python && uv run pytest tests/extraction/test_gleaning.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `gleaning.py`**

`merge_gleaned`: build a case-insensitive index of existing `canonical_name`; for each gleaned entity, if matched, union aliases (case-insensitive de-dup) into the existing entity; else append and count new. `run_gleaning`: loop up to `max_rounds`, call `round_fn`, merge; break when new count == 0; return merged result + rounds used.

- [ ] **Step 4: Run to confirm pass**

Run: `cd ennam.kg.python && uv run pytest tests/extraction/test_gleaning.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/extraction/gleaning.py \
        ennam.kg.python/tests/extraction/test_gleaning.py
git commit -m "feat(ba031): gleaning loop (bounded rounds, early-stop, alias-union dedup)"
```

---

## Task 7: Pass 1 orchestrator + embedding (Python)

Ties Tasks 2/4/5/6 together: skip-guard → LLM extract (via BA-009 client) → parse → gleaning → attach provenance → persist nodes/edges to Go → compute embedding (symmetric prefix) → upsert → mark state. LLM + HTTP clients mocked in tests.

**Files:**
- Create: `src/ennam_kg/extraction/pass1.py`, `src/ennam_kg/extraction/embed.py`
- Test: `tests/extraction/test_pass1.py`

**Interfaces:**
- Consumes: `parse_extraction`, `run_gleaning`, the BA-009 `ai_client`, the existing KG HTTP client (node create + `upsert_node_embeddings`), `embeddings/local_model.py` (`encode_query`), and the Go `chunk_extraction_state` (via an HTTP/RPC method `should_skip`/`mark_state` — add a thin client method if not present).
- Produces: `async def run_pass1(doc_id, run_id, project_id, deps) -> Pass1Summary{extracted, dropped, gleaning_rounds, skipped}` where `deps` bundles the injected clients (for testability).

- [ ] **Step 1: Write the failing orchestrator test (all deps mocked)**

`tests/extraction/test_pass1.py` — provide a fake chunk source (2 chunks), a fake LLM returning a fixed JSON per chunk, fake KG client recording created nodes, and a fake state client. Assert:

```python
async def test_run_pass1_persists_and_skips(monkeypatch):
    deps = make_fake_deps(
        chunks=[("c1","h1","Ennam hired Nguyễn Văn A"), ("c2","h2","...")],
        llm_json={"c1": {...person+org...}, "c2": {...}},
        already_extracted={"c2": "h2"},   # skip-guard hits c2
    )
    summary = await run_pass1("d1","r1","p1", deps)
    assert summary.skipped == 1                      # c2 skipped (BR-007.5)
    assert summary.extracted >= 2                    # person + org from c1
    assert deps.kg.created_nodes_have_provenance()   # NFR-254
    assert deps.llm.call_count == 1                  # only c1 hit the model (cost-idempotency)
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd ennam.kg.python && uv run pytest tests/extraction/test_pass1.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `embed.py`**

`embed.py`: `embed_entity(model, name, description) -> (vector, content_hash)` — builds the embedded text (`canonical_name + " " + description` per OQ-003), applies the **symmetric prefix** by calling `model.encode_query([...])` (same prefix both sides — document the choice; confirmed in 8b), computes `content_hash` over the prefixed text.

- [ ] **Step 4: Implement `pass1.py`**

Per chunk: call `deps.state.should_skip(chunk_id, content_hash)`; if skip → increment `skipped`, continue (no LLM). Else: mark `extracting`; call the LLM (single-turn JSON) via `deps.ai_client`; `parse_extraction`; `run_gleaning` (fresh single-turn `round_fn` closure); attach provenance `{source_doc_id, chunk_id, sentence_span}` to every entity/relation; **reject + count any item with empty provenance**; persist each entity as a `status=active` node via `deps.kg` (Go enforces Gate 1); persist relations as edges; embed + `upsert_node_embeddings`; mark state `extracted` with `gleaning_rounds_used`/`dropped_count`. On unparseable LLM output after the retry limit → mark `extract_failed`, continue the batch (BR-001.7, fail loud per-chunk).

- [ ] **Step 5: Run to confirm pass**

Run: `cd ennam.kg.python && uv run pytest tests/extraction/test_pass1.py -v`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

Run: `cd ennam.kg.python && uv run ruff check src/ennam_kg/extraction/`

```bash
git add ennam.kg.python/src/ennam_kg/extraction/pass1.py \
        ennam.kg.python/src/ennam_kg/extraction/embed.py \
        ennam.kg.python/tests/extraction/test_pass1.py
git commit -m "feat(ba031): Pass1 orchestrator + symmetric-prefix embedding (skip-guard, provenance, persist)"
```

---

## Task 8: Recovery sweep (re-enqueue dead-run chunks)

Implements the durability half of FR-NEW-3 / R6. A periodic sweep finds chunks stuck in `extracting`/`resolving` past a staleness window and re-enqueues them (Redis `LPUSH`). Makes Redis dispatch crash-safe.

**Files:**
- Create: `ennam.kg.go/internal/jobengine/extraction_recovery.go` (or the existing periodic-task home — check where other background sweeps live), `...extraction_recovery_test.go`

**Interfaces:**
- Consumes: `store.ChunkExtractionStateStore.FindStale`, the Redis publisher.
- Produces: `func RunRecoverySweep(ctx, states ChunkStaleFinder, pub Publisher, olderThan time.Duration) (reenqueued int, err error)` — for each stale row, LPUSH an `extract_document`/`resolve_document` message keyed by its `run_id`/chunk and return the count.

- [ ] **Step 1: Write the failing test**

```go
func TestRunRecoverySweep_ReenqueuesStale(t *testing.T) {
	finder := &fakeFinder{stale: []store.ChunkExtractionState{
		{ChunkID: "c1", ProjectID: "p1", RunID: "r1", Status: "extracting"},
	}}
	pub := &fakePublisher{}
	n, err := RunRecoverySweep(ctx, finder, pub, 10*time.Minute)
	if err != nil { t.Fatal(err) }
	if n != 1 || len(pub.published) != 1 {
		t.Fatalf("expected 1 re-enqueue, got n=%d published=%d", n, len(pub.published))
	}
}
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd ennam.kg.go && go test ./internal/jobengine/ -run TestRunRecoverySweep_ReenqueuesStale`
Expected: FAIL — undefined.

- [ ] **Step 3: Implement the sweep**

`RunRecoverySweep`: call `finder.FindStale(ctx, olderThan, []string{"extracting","resolving"})`; for each, publish the matching message via `pub`; return count. Wire it into the server's periodic-task scheduler at a config interval (find how existing periodic jobs are scheduled and follow that pattern; do not invent a new scheduler).

- [ ] **Step 4: Run to confirm pass + lint + build**

Run: `cd ennam.kg.go && go test ./internal/jobengine/ && make lint && make build`
Expected: PASS / clean.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.go/internal/jobengine/extraction_recovery.go \
        ennam.kg.go/internal/jobengine/extraction_recovery_test.go
git commit -m "feat(ba031): extraction recovery sweep (re-enqueue dead-run chunks)"
```

---

## Task 9: Integration — crash-recovery + NFR-253/254/263 gates

The Phase 8a exit gate. Proves the foundation end-to-end against a real test DB + Redis.

**Files:**
- Create: `ennam.kg.go/internal/integration/ba031_foundation_test.go` (or the project's integration-test home — check existing integration tests for the harness/build-tag convention)

**Interfaces:**
- Consumes: the full stack from Tasks 1–8.

- [ ] **Step 1: Write the closed-schema + provenance audit test (NFR-253/254)**

Drive Pass 1 over a seeded document with 2 chunks (one mentioning a `person` + `organization`, one with an out-of-vocab `vehicle`). Assert: (a) zero persisted nodes/edges outside the closed vocab; (b) `dropped_count >= 1`; (c) **every** persisted BA-031 node and edge has a non-empty `provenance[]` with `source_doc_id`, `chunk_id`, `sentence_span` (audit query returns zero empty-provenance rows).

- [ ] **Step 2: Write the idempotent re-ingest test (NFR-263)**

Run Pass 1 twice on the same unchanged document (identical chunk content hashes). Assert: (a) node/edge counts identical after the 2nd run (count-idempotency); (b) the 2nd run issued **zero** extraction LLM calls (cost-idempotency — assert via the mock/stub LLM call counter or a metrics probe).

- [ ] **Step 3: Write the crash-recovery test (R6)**

Mark a chunk's state `extracting` with a stale `updated_at` (simulating a worker death mid-pipeline), run `RunRecoverySweep`, assert the chunk is re-enqueued and a subsequent Pass 1 run completes it to `extracted` with no duplicate `active` nodes (BR-007.6 collapses any half-written duplicates).

- [ ] **Step 4: Run the integration suite**

Run: `cd ennam.kg.go && make test` (ensure the integration build tag / test DB + Redis are up via `make dev-up` or the documented integration harness).
Expected: PASS — all three gate tests green.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.go/internal/integration/ba031_foundation_test.go
git commit -m "test(ba031): phase 8a exit gates — closed-schema, provenance, idempotency, crash-recovery"
```

---

## Phase 8a Done — Definition of Done

- [ ] Closed vocab registered at all 3 surfaces; `person` accepted, `vehicle` rejected (Task 1).
- [ ] `chunk_extraction_state` durable; skip-guard + recovery proven (Tasks 2, 8).
- [ ] Resolution-candidates endpoint filters by `min_similarity` (Task 3) — ready for 8c.
- [ ] Pass 1 extracts closed-vocab entities + relations with mandatory provenance, drops out-of-vocab, gleans (Tasks 5–7).
- [ ] NFR-253 (100% closed-schema), NFR-254 (100% provenance), NFR-263 (count + cost idempotency), crash-recovery — all green (Task 9).
- [ ] `make -C ennam.kg.go test lint build` clean; `cd ennam.kg.python && uv run pytest` green.

## Next Plans (separate documents, after 8a ships + is reviewed)

- **8b** — funded labelled Vietnamese benchmark + threshold×K sweep (gate: blocking recall ≥90% @K=10). Depends on 8a's candidates endpoint.
- **8c** — Pass 2 resolution in shadow mode (`merge_suggestions` sidecar), un-merge built + drilled, lossless edge dedup (BR-005.11 rewrite). Gate: precision ≥0.90 / recall ≥0.80 measured.
- **8d** — degree-gated auto-merge GA + cost ceiling (FR-NEW-2). Gate: cost ceiling enforced, un-merge drilled.

---

## Self-Review

- **Spec coverage (8a slice):** OQ-001 + OQ-NEW-1 → Task 1; FR-NEW-3 / BR-007.5/.6 / NFR-263 → Tasks 2, 7, 9; FR-NEW-4 / FR-004 → Task 3; durable dispatch + R6 → Tasks 4, 8; FR-001 / BR-001.* → Task 5; FR-002 → Task 6; FR-003 / NFR-254 → Tasks 7, 9; NFR-253 → Tasks 1, 9; OQ-003 symmetric prefix → Task 7. FR-005/006 (merge/re-summary), FR-NEW-1/2/6/7, BR-005.11 → deferred to 8c/8d plans (correct — out of 8a scope). FR-008 routing is used via the BA-009 client in Task 7; budget *ceiling* (FR-NEW-2) is 8d.
- **Placeholder scan:** no TBD/TODO; each code step shows code; mocked-LLM tests carry real assertions.
- **Type consistency:** `ChunkExtractionState`, `ShouldSkip`, `FindStale`, `SemanticSearch` signature, `parse_extraction`, `merge_gleaned`/`run_gleaning`, `run_pass1`, `RunRecoverySweep` are named identically wherever cross-referenced. Where a signature is illustrative (Python gleaning return), the step says to keep the test asserting the behavior, not the exact shape.
- **Known soft spots to confirm during execution (flagged, not hidden):** (a) exact current `node_type` CHECK list to union against in Task 1 Step 5; (b) whether `edge_whitelist` supports `"*"` wildcards (Task 1 Step 7); (c) the existing queue-envelope field names to mirror (Task 4 Step 3); (d) the integration-test harness/build-tag + where periodic sweeps are scheduled (Tasks 8–9). Each step says to read the existing pattern before writing.
