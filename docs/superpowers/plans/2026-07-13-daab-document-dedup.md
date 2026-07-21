# DAAB Document Deduplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop identical re-uploaded PDFs from creating duplicate document nodes (global per-project content-hash reuse at ingest), and clean up the existing ~70 duplicates in Cảng Định An by soft-delete + re-ingest.

**Architecture:** Add a third dedup tier — *global content-hash reuse* — to the ingest pipeline, after the existing source-id-scoped exact-hash (tier 1) and source-only/regenerate (tier 2) checks, before `create_node`. Backed by a new Go store method `FindByContentHash(project, hash)` exposed through a content-hash-only mode of the existing `/canonical-documents/lookup` endpoint, called from a new Python client method inside `engine.run_batch`. Cleanup is a one-shot script (delete substrate → verify empty → re-ingest clean folder → verify invariants).

**Tech Stack:** Go (`database/sql`, stdlib `net/http`, table-driven tests), Python 3.12 (httpx async client, pytest + `unittest.mock`), PostgreSQL 16, Docker Compose stack.

## Global Constraints

- **Dedup key is `content_hash`** (SHA-256 of normalized content), scoped **per-project**, ignoring `source_id`. Never cross-project.
- **`source_type` for uploads is `local_upload`** (verified in DB) — but tier-3 lookup ignores `source_type` entirely.
- **Tier-3 lookup MUST filter `deleted_at IS NULL`** so soft-deleted / cleaned-up rows are never reused.
- **Fail loud (AGENTS.md Rule 12 / NFR-243 ingest-once):** a non-404 error in the dedup lookup fails the draft (`result.failed += 1`, `_safe_complete(..., False)`) — it MUST NOT fall through to `create_node`. 404 = miss = proceed.
- **Tier ordering is fixed:** exact-hash (1) → source-only/regenerate (2) → global-hash reuse (3) → create (miss). Tier 3 is consulted only when tier 2 misses (`prior is None`).
- **Cleanup ordering (two hard gates):** (a) prevention shipped & verified before cleanup; (b) deletion verified complete (0 live document hubs AND 0 live `canonical_document` rows for the project) before the first re-ingest upload — else tier 3 reuses stale duplicate nodes.
- Go: `gofmt`/`goimports`, `fmt.Errorf("ctx: %w", err)`, `go test -race`. Python: `ruff`, type hints, `pytest`.

**Key files & symbols (verified):**
- `ennam.kg.go/internal/store/canonical_document.go` — `CanonicalDocumentStore`, existing `FindBySourceHash`/`FindBySource`/`SoftDeleteBySource`.
- `ennam.kg.go/internal/handler/canonical_document.go` — `Lookup` (line ~100), `canonicalDocStorer` interface (line ~24), `validCanonicalSourceTypes` (line ~15).
- `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py` — `KGClient`, existing `get_canonical_document_by_source` (line ~397), `find_canonical_document_by_source` (line ~444).
- `ennam.kg.python/src/ennam_kg/ingestion/pipeline/engine.py` — `IngestionPipelineEngine.run_batch`; tier-2 block ends at the `continue` on line ~233, `create_node` block starts on line ~235.

---

### Task 1: Go store — `FindByContentHash`

**Files:**
- Modify: `ennam.kg.go/internal/store/canonical_document.go` (add method after `FindBySource`, ~line 130)
- Test: `ennam.kg.go/internal/store/canonical_document_test.go` (append)

**Interfaces:**
- Produces: `func (s *CanonicalDocumentStore) FindByContentHash(ctx context.Context, projectID, contentHash string) (*models.CanonicalDocument, error)` — returns latest non-deleted canonical doc for `(project_id, content_hash)` regardless of `source_id`; `(nil, nil)` on miss.

- [ ] **Step 1: Write the failing integration test**

Append to `canonical_document_test.go`. Mirrors `TestCanonicalDocumentStore_FindBySource_ReturnsRow`. Intent (Rule 9): a canonical row created under one upload's `source_id` must be found by hash alone — proving a *different* re-upload (new `source_id`, same hash) will dedup.

```go
// TestCanonicalDocumentStore_FindByContentHash_ReturnsRowIgnoringSource verifies
// that a row is found by (project, content_hash) alone — the cross-upload dedup
// case where a re-uploaded identical file has a NEW source_id but the SAME hash.
func TestCanonicalDocumentStore_FindByContentHash_ReturnsRow(t *testing.T) {
	db := setupTestDB(t)
	prereqs := seedCanonicalDocPrereqs(t, db, "findbyhash")

	ctx := context.Background()
	s := store.NewCanonicalDocumentStore(db)

	doc := models.CanonicalDocument{
		ProjectID:        prereqs.projID,
		DraftNodeID:      prereqs.draftID,
		KnowledgeNodeID:  prereqs.nodeID,
		SourceType:       "local_upload",
		SourceID:         "upload:" + prereqs.runSuffix,
		ContentHash:      "hash-global-1",
		ExtractionMethod: "native",
		Metadata:         map[string]any{},
		ExtractedAt:      time.Now().UTC().Truncate(time.Millisecond),
	}
	inserted, err := s.UpsertByDraft(ctx, doc)
	if err != nil {
		t.Fatalf("upsert: %v", err)
	}

	// Look up by hash only — no source_id passed.
	found, err := s.FindByContentHash(ctx, prereqs.projID, "hash-global-1")
	if err != nil {
		t.Fatalf("FindByContentHash: %v", err)
	}
	if found == nil {
		t.Fatal("expected non-nil result")
	}
	if found.ID != inserted.ID {
		t.Errorf("ID mismatch: got %q, want %q", found.ID, inserted.ID)
	}
}

// TestCanonicalDocumentStore_FindByContentHash_MissAndSoftDelete verifies a miss
// returns nil, and a soft-deleted row is not matched (deleted_at IS NULL).
func TestCanonicalDocumentStore_FindByContentHash_MissAndSoftDelete(t *testing.T) {
	db := setupTestDB(t)
	prereqs := seedCanonicalDocPrereqs(t, db, "findbyhashdel")

	ctx := context.Background()
	s := store.NewCanonicalDocumentStore(db)

	doc := models.CanonicalDocument{
		ProjectID:        prereqs.projID,
		DraftNodeID:      prereqs.draftID,
		KnowledgeNodeID:  prereqs.nodeID,
		SourceType:       "local_upload",
		SourceID:         "upload:" + prereqs.runSuffix,
		ContentHash:      "hash-del-1",
		ExtractionMethod: "native",
		Metadata:         map[string]any{},
		ExtractedAt:      time.Now().UTC().Truncate(time.Millisecond),
	}
	inserted, err := s.UpsertByDraft(ctx, doc)
	if err != nil {
		t.Fatalf("upsert: %v", err)
	}

	// Wrong hash → nil.
	miss, err := s.FindByContentHash(ctx, prereqs.projID, "no-such-hash")
	if err != nil {
		t.Fatalf("FindByContentHash miss: %v", err)
	}
	if miss != nil {
		t.Errorf("expected nil for unknown hash, got %+v", miss)
	}

	// Soft-delete, then the same hash must return nil.
	if _, err := db.ExecContext(ctx,
		`UPDATE canonical_document SET deleted_at = NOW() WHERE id = $1`, inserted.ID); err != nil {
		t.Fatalf("soft-delete: %v", err)
	}
	afterDel, err := s.FindByContentHash(ctx, prereqs.projID, "hash-del-1")
	if err != nil {
		t.Fatalf("FindByContentHash after delete: %v", err)
	}
	if afterDel != nil {
		t.Errorf("expected nil after soft-delete, got %+v", afterDel)
	}
}

// TestCanonicalDocumentStore_FindByContentHash_NilDB verifies the nil-DB guard.
func TestCanonicalDocumentStore_FindByContentHash_NilDB(t *testing.T) {
	s := store.NewCanonicalDocumentStore(nil)
	if _, err := s.FindByContentHash(context.Background(), "p", "h"); err == nil {
		t.Fatal("expected error for nil db")
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestCanonicalDocumentStore_FindByContentHash -v`
Expected: compile failure — `s.FindByContentHash undefined`.

- [ ] **Step 3: Implement `FindByContentHash`**

Add to `canonical_document.go` after `FindBySource` (before `SoftDeleteBySource`):

```go
// FindByContentHash returns the latest non-deleted canonical document matching
// (project_id, content_hash) regardless of source_id — the cross-upload dedup
// lookup. A re-uploaded identical file gets a new source_id but the same content
// hash, so source-scoped lookups miss; this catches it. Returns (nil, nil) on miss.
func (s *CanonicalDocumentStore) FindByContentHash(
	ctx context.Context,
	projectID, contentHash string,
) (*models.CanonicalDocument, error) {
	if s.db == nil {
		return nil, fmt.Errorf("find canonical document by content hash: db is nil")
	}
	const q = `
		SELECT id, project_id, draft_node_id, knowledge_node_id,
		       source_type, source_id, content_hash,
		       extraction_method, metadata, extracted_at,
		       created_at, updated_at
		FROM canonical_document
		WHERE project_id  = $1
		  AND content_hash = $2
		  AND deleted_at IS NULL
		ORDER BY updated_at DESC
		LIMIT 1`

	doc, err := scanCanonicalDocument(s.db.QueryRowContext(ctx, q, projectID, contentHash))
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("find canonical document by content hash: %w", err)
	}
	return &doc, nil
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestCanonicalDocumentStore_FindByContentHash -race -v`
Expected: PASS (all three). Note: integration tests need the test DB — if `setupTestDB` skips without `KG_TEST_DATABASE_URL`, run with that env var pointed at the dev DB (`:5433`).

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/store/canonical_document.go internal/store/canonical_document_test.go
git commit -m "feat(dedup): FindByContentHash store method for cross-upload dedup"
```

---

### Task 2: Go handler — content-hash-only lookup mode

**Files:**
- Modify: `ennam.kg.go/internal/handler/canonical_document.go` (interface ~line 24, `Lookup` ~line 100)
- Test: `ennam.kg.go/internal/handler/canonical_document_test.go` (fake store ~line 17, append tests)

**Interfaces:**
- Consumes: `CanonicalDocumentStore.FindByContentHash` (Task 1).
- Produces: `GET /api/v1/projects/{projectId}/canonical-documents/lookup?content_hash=H` (no `source_id`) → `FindByContentHash`; returns 200 on hit, 404 on miss. Existing modes (with `source_id`) unchanged.

- [ ] **Step 1: Write the failing handler tests**

Append to `canonical_document_test.go`. First, extend the fake store with the new method (add near the other fake methods, ~line 78):

```go
func (f *fakeCanonicalDocStore) FindByContentHash(_ context.Context, projectID, contentHash string) (*models.CanonicalDocument, error) {
	if f.findByHashErr != nil {
		return nil, f.findByHashErr
	}
	for _, doc := range f.rows {
		if doc.ProjectID == projectID && doc.ContentHash == contentHash {
			d := doc
			return &d, nil
		}
	}
	return nil, nil
}
```

Then the tests:

```go
// TestCanonicalDocumentLookup_ContentHashOnly_Hit verifies that a lookup with
// content_hash but NO source_id uses the global content-hash dedup path.
func TestCanonicalDocumentLookup_ContentHashOnly_Hit(t *testing.T) {
	st := newFakeCanonicalDocStore()
	_, _ = st.UpsertByDraft(context.Background(), models.CanonicalDocument{
		ID:              "cd-h1",
		ProjectID:       "proj-1",
		DraftNodeID:     "draft-1",
		KnowledgeNodeID: "node-1",
		SourceType:      "local_upload",
		SourceID:        "upload:aaa",
		ContentHash:     "H1",
	})
	mux := newCanonicalMux(st)

	req := httptest.NewRequest("GET",
		"/api/v1/projects/proj-1/canonical-documents/lookup?content_hash=H1", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}
	var got models.CanonicalDocument
	if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got.KnowledgeNodeID != "node-1" {
		t.Errorf("expected node-1, got %q", got.KnowledgeNodeID)
	}
}

// TestCanonicalDocumentLookup_ContentHashOnly_Miss verifies 404 on no match.
func TestCanonicalDocumentLookup_ContentHashOnly_Miss(t *testing.T) {
	st := newFakeCanonicalDocStore()
	mux := newCanonicalMux(st)

	req := httptest.NewRequest("GET",
		"/api/v1/projects/proj-1/canonical-documents/lookup?content_hash=NOPE", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("expected 404, got %d", rec.Code)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestCanonicalDocumentLookup_ContentHashOnly -v`
Expected: compile failure (fake missing `FindByContentHash` in interface) then, once interface updated, 404-instead-of-200 / current handler rejects missing `source_id` with 400.

- [ ] **Step 3: Add the method to the store interface**

In `canonical_document.go`, add to `canonicalDocStorer` (after `FindBySource`, ~line 27):

```go
	FindByContentHash(ctx context.Context, projectID, contentHash string) (*models.CanonicalDocument, error)
```

- [ ] **Step 4: Add the content-hash-only branch to `Lookup`**

Replace the validation + dispatch block in `Lookup` (currently lines ~107-129) with:

```go
	sourceType := strings.TrimSpace(r.URL.Query().Get("source_type"))
	sourceID := strings.TrimSpace(r.URL.Query().Get("source_id"))
	contentHash := strings.TrimSpace(r.URL.Query().Get("content_hash"))

	var (
		doc *models.CanonicalDocument
		err error
	)

	// Content-hash-only mode: content_hash present, source_id absent → global
	// per-project dedup lookup (cross-upload duplicate detection). source_type
	// is not required in this mode.
	if contentHash != "" && sourceID == "" {
		doc, err = h.store.FindByContentHash(r.Context(), projectID, contentHash)
	} else {
		if sourceType == "" || sourceID == "" {
			errorResponse(w, http.StatusBadRequest, "source_type and source_id query params are required")
			return
		}
		if !validCanonicalSourceTypes[sourceType] {
			errorResponse(w, http.StatusBadRequest, "unknown source_type: "+sourceType)
			return
		}
		if contentHash != "" {
			doc, err = h.store.FindBySourceHash(r.Context(), projectID, sourceType, sourceID, contentHash)
		} else {
			doc, err = h.store.FindBySource(r.Context(), projectID, sourceType, sourceID)
		}
	}
	if err != nil {
		h.logger.Error("canonical document lookup failed", "project_id", projectID, "error", err)
		errorResponse(w, http.StatusInternalServerError, "canonical document lookup failed")
		return
	}
	if doc == nil {
		errorResponse(w, http.StatusNotFound, "canonical document not found")
		return
	}
```

Update the `Lookup` doc-comment (lines ~94-99) to note the three modes: content-hash-only, source+hash, source-only.

- [ ] **Step 5: Run the full handler package to verify pass + no regression**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestCanonicalDocumentLookup -race -v`
Expected: PASS — new ContentHashOnly tests + all existing `TestCanonicalDocumentLookup_*` (SourceOnly, WithHash regression, MissingParams, etc.).

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.go
git add internal/handler/canonical_document.go internal/handler/canonical_document_test.go
git commit -m "feat(dedup): content-hash-only mode on canonical-documents lookup"
```

---

### Task 3: Python client — `find_canonical_document_by_content_hash`

**Files:**
- Modify: `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py` (after `find_canonical_document_by_source`, ~line 470)
- Test: `ennam.kg.python/tests/ingestion/test_kgclient_canonical.py` (append)

**Interfaces:**
- Produces: `async def find_canonical_document_by_content_hash(self, project_id: str, content_hash: str) -> dict[str, Any] | None` — GETs `/canonical-documents/lookup?content_hash=…` (no source params); `None` on 404, raises `KGClientError` otherwise.

- [ ] **Step 1: Write the failing test**

Append to `test_kgclient_canonical.py` (mirror the existing `find_canonical_document_by_source` test in that file — inspect it first for the exact `respx`/`httpx` mock style and reuse it verbatim). Test body:

```python
@pytest.mark.asyncio
async def test_find_canonical_document_by_content_hash_hit(kg_client, httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url__regex=r".*/canonical-documents/lookup\?content_hash=H1$",
        json={"knowledge_node_id": "node-1", "content_hash": "H1"},
    )
    got = await kg_client.find_canonical_document_by_content_hash("proj-1", "H1")
    assert got is not None
    assert got["knowledge_node_id"] == "node-1"


@pytest.mark.asyncio
async def test_find_canonical_document_by_content_hash_miss_returns_none(kg_client, httpx_mock):
    httpx_mock.add_response(status_code=404, json={"error": "not found"})
    got = await kg_client.find_canonical_document_by_content_hash("proj-1", "NOPE")
    assert got is None
```

> If the existing tests in this file use a different mocking fixture than `httpx_mock`, copy that file's exact fixture/style instead — do not introduce a new mocking approach.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_kgclient_canonical.py -k content_hash -v`
Expected: FAIL — `AttributeError: 'KGClient' object has no attribute 'find_canonical_document_by_content_hash'`.

- [ ] **Step 3: Implement the client method**

Add to `client.py` after `find_canonical_document_by_source`:

```python
    async def find_canonical_document_by_content_hash(
        self,
        project_id: str,
        content_hash: str,
    ) -> dict[str, Any] | None:
        """GET …/canonical-documents/lookup with content_hash only (no source_id).

        Global per-project content-hash dedup — catches an identical file re-uploaded
        under a new source_id (same content → same hash, but source-scoped lookups miss).

        Returns None on 404 (no duplicate); raises KGClientError for other errors.
        """
        try:
            return await self._request(
                "GET",
                f"/api/v1/projects/{project_id}/canonical-documents/lookup",
                params={"content_hash": content_hash},
            )
        except KGClientError as exc:
            if exc.status_code == 404:
                return None
            raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_kgclient_canonical.py -k content_hash -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py tests/ingestion/test_kgclient_canonical.py
git commit -m "feat(dedup): KGClient.find_canonical_document_by_content_hash"
```

---

### Task 4: Python engine — tier-3 global-hash dedup

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/pipeline/engine.py` (insert between the tier-2 `continue` on ~line 233 and the `create_node` `try:` on ~line 235)
- Test: `ennam.kg.python/tests/ingestion/test_dedup.py` (append)

**Interfaces:**
- Consumes: `self._kg.find_canonical_document_by_content_hash(project_id, content_hash)` (Task 3); existing `complete_draft_node`, `_safe_complete`.
- Produces: on tier-3 hit → draft completed with existing `knowledge_node_id`, `result.reused += 1`, `result.processed += 1`, no `create_node`.

- [ ] **Step 1a: Update the shared `_make_mock_kg` helper (REQUIRED — prevents breaking existing tests)**

`_make_mock_kg` returns a bare `MagicMock`, so any test that reaches tier-3 (e.g. the existing `test_cache_miss_falls_through_to_create_node`, which misses tier-1 and tier-2) would `await` an auto-created non-awaitable MagicMock and raise `TypeError`. Add a default stub for the new method inside `_make_mock_kg` (near the other `AsyncMock` assignments, ~line 133):

```python
    kg.find_canonical_document_by_content_hash = AsyncMock(return_value=None)
```

This defaults tier 3 to "no duplicate" so unrelated tests fall through unchanged; per-test overrides set it explicitly.

- [ ] **Step 1b: Write the failing tests**

Append to `test_dedup.py`. Reuse the file's existing helpers (`_make_mock_kg`, `_make_mock_ai`, `_make_existing_canonical_doc`, constants `PROJECT_ID`/`DRAFT_ID`/`EXISTING_NODE_ID`, and the `patch(...)` block from `test_dedup_reuse_skips_create_node_and_embeddings`). Each test overrides the tier-1/tier-2/tier-3 mocks it needs.

```python
# ---------------------------------------------------------------------------
# Tier 3: global content-hash dedup — identical file re-uploaded, new source_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_hash_dedup_reuses_node_no_create():
    """A re-uploaded identical file (tier1 miss: new source_id; tier2 miss: no prior
    for that source_id) whose content_hash already exists under ANOTHER upload must
    REUSE the existing node — no create_node — and increment `reused`."""
    content_hash = _sha256_of_normalized(MARKDOWN_CONTENT)
    dup = _make_existing_canonical_doc(content_hash)  # knowledge_node_id == EXISTING_NODE_ID

    kg = _make_mock_kg(existing_doc=None)            # tier 1 miss
    kg.find_canonical_document_by_source = AsyncMock(return_value=None)          # tier 2 miss
    kg.find_canonical_document_by_content_hash = AsyncMock(return_value=dup)     # tier 3 HIT
    ai = _make_mock_ai()

    with patch(
        "ennam_kg.ingestion.pipeline.engine.extract_draft",
        new=AsyncMock(return_value=MagicMock(topic="test", to_dict=lambda: {})),
    ), patch(
        "ennam_kg.ingestion.pipeline.engine.decompose_document",
        new=AsyncMock(return_value=MagicMock(sections=0, edges=0, embeddings=0)),
    ) as mock_decompose, patch(
        "ennam_kg.ingestion.pipeline.engine.create_upload_batch_edges",
        new=AsyncMock(return_value=0),
    ), patch(
        "ennam_kg.ingestion.pipeline.engine.propose_ai_cross_edges",
        new=AsyncMock(return_value=[]),
    ), patch(
        "ennam_kg.ingestion.pipeline.engine.apply_cross_edge_proposals",
        new=AsyncMock(return_value=0),
    ):
        engine = IngestionPipelineEngine(kg_client=kg, ai_client=ai)
        result = await engine.run_batch(project_id=PROJECT_ID, draft_ids=[DRAFT_ID])

    kg.create_node.assert_not_called()
    mock_decompose.assert_not_called()
    call_kwargs = kg.complete_draft_node.call_args.kwargs
    assert call_kwargs.get("success") is True
    assert call_kwargs.get("knowledge_node_id") == EXISTING_NODE_ID
    assert result.reused == 1, f"reused should be 1, got {result.reused}"
    assert result.nodes_created == 0


@pytest.mark.asyncio
async def test_global_hash_dedup_lookup_error_fails_draft_no_create():
    """NFR-243: a non-404 error in the tier-3 lookup fails the draft loudly — it must
    NOT fall through to create_node."""
    kg = _make_mock_kg(existing_doc=None)
    kg.find_canonical_document_by_source = AsyncMock(return_value=None)
    kg.find_canonical_document_by_content_hash = AsyncMock(
        side_effect=KGClientError(500, "boom")  # constructor is (status_code, detail)
    )
    ai = _make_mock_ai()

    with patch(
        "ennam_kg.ingestion.pipeline.engine.extract_draft",
        new=AsyncMock(return_value=MagicMock(topic="test", to_dict=lambda: {})),
    ), patch(
        "ennam_kg.ingestion.pipeline.engine.decompose_document",
        new=AsyncMock(return_value=MagicMock(sections=0, edges=0, embeddings=0)),
    ), patch(
        "ennam_kg.ingestion.pipeline.engine.create_upload_batch_edges",
        new=AsyncMock(return_value=0),
    ), patch(
        "ennam_kg.ingestion.pipeline.engine.propose_ai_cross_edges",
        new=AsyncMock(return_value=[]),
    ), patch(
        "ennam_kg.ingestion.pipeline.engine.apply_cross_edge_proposals",
        new=AsyncMock(return_value=0),
    ):
        engine = IngestionPipelineEngine(kg_client=kg, ai_client=ai)
        result = await engine.run_batch(project_id=PROJECT_ID, draft_ids=[DRAFT_ID])

    kg.create_node.assert_not_called()
    assert result.failed == 1
    assert result.reused == 0
    assert result.nodes_created == 0
```

Match the file's convention: import `KGClientError` **locally inside** the error test function (`from ennam_kg_indexer.kg_client.client import KGClientError`), exactly as the existing `test_dedup_lookup_kg_error_fails_draft_no_create_node` does — not at module top.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_dedup.py -k global_hash -v`
Expected: FAIL — `create_node` IS called (no tier-3 branch yet), so `assert_not_called` fails / `reused == 0`.

- [ ] **Step 3: Insert the tier-3 block in `engine.py`**

Between the tier-2 block's closing `continue` (~line 233) and the `try:` that begins the `create_node` path (~line 235), insert (match surrounding indentation — same level as the `for` loop body):

```python
            # --- Tier 3: global content-hash dedup (FR-004) ---
            # tier-1 (exact source+hash) and tier-2 (same source, any hash) both missed,
            # so this source_id is new. But the identical file may already exist under a
            # DIFFERENT upload (same content → same hash). Reuse that node instead of
            # creating a duplicate. Fail loud on non-404 errors (NFR-243 ingest-once).
            try:
                dup = await self._kg.find_canonical_document_by_content_hash(
                    project_id, canonical.content_hash
                )
            except KGClientError as exc:
                result.failed += 1
                result.errors.append(f"{draft_id}: content-hash dedup lookup: {exc}")
                logger.warning("content-hash dedup lookup failed draft=%s: %s", draft_id, exc)
                await self._safe_complete(project_id, draft_id, False, "")
                continue

            if dup is not None:
                dup_node_id = str(dup.get("knowledge_node_id") or "")
                await self._kg.complete_draft_node(
                    project_id, draft_id, success=True, knowledge_node_id=dup_node_id
                )
                result.processed += 1
                result.reused += 1
                logger.info(
                    "content-hash dedup hit draft=%s existing_node=%s", draft_id, dup_node_id
                )
                continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_dedup.py -v`
Expected: PASS — new `global_hash` tests + all existing dedup tests (tier-1 reuse, cache-miss create, regenerate, error-fails-draft) still green.

- [ ] **Step 5: Lint + commit**

```bash
cd ennam.kg.python
uv run ruff check src/ennam_kg/ingestion/pipeline/engine.py tests/ingestion/test_dedup.py
git add src/ennam_kg/ingestion/pipeline/engine.py tests/ingestion/test_dedup.py
git commit -m "feat(dedup): tier-3 global content-hash reuse in ingest pipeline"
```

---

### Task 5: Rebuild stack + prove prevention end-to-end

**Files:**
- Create: `docs/superpowers/plans/scratch/verify_dedup_prevention.py` (throwaway verification script; may live in the session scratchpad instead)

**Interfaces:**
- Consumes: the deployed kg-server + Python worker with Tasks 1-4 built in.
- Produces: evidence that uploading the same PDF twice yields exactly one `document` node.

- [ ] **Step 1: Rebuild the Go + Python images and restart**

```bash
cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace
docker compose up -d --build kg-server indexer worker
docker compose ps
```
Expected: `kg-server`, `indexer`, `worker` healthy/running.

- [ ] **Step 2: Write the throwaway verification script**

Adapt the existing `ingest_sala.py` scratchpad upload helper (multipart POST to `/api/v1/projects/{project}/ingest/upload` with `file`/`title`/`auto_approve=true`, then poll `GET /draft-nodes/{id}` until `processed|approved|failed`). Script logic:
1. Pick one PDF from `doc_pdf_test/project_1`.
2. Create a fresh throwaway project (or use a dedicated dedup-test project id) via the API, and an API key scoped to it — OR reuse an existing empty test project. Record the project id.
3. Upload the SAME PDF **twice** (two separate upload calls → two drafts → two `source_id`s).
4. Wait for both drafts to reach a terminal state.
5. Query the DB for the document count:
   `SELECT count(*) FROM knowledge_nodes WHERE project_id=$P AND node_type='document';`

- [ ] **Step 3: Run it and assert one document**

Run the script. Expected:
- Both drafts terminal (`approved`).
- **`count(document) == 1`** — the second upload hit tier 3 and reused the first node.
- Worker logs show `content-hash dedup hit` for the second draft:
  `docker compose logs worker | grep "content-hash dedup hit"` → at least one line.

If count == 2, prevention failed — stop and debug (check the worker actually rebuilt, and the lookup endpoint returns 200 for the content-hash-only call).

- [ ] **Step 4: Commit the evidence note**

Record the result (counts + log line) in the cleanup checkpoint (Task 6 writes the Serena checkpoint). No production code commit here.

---

### Task 6: Clean up Cảng Định An (delete + re-ingest)

**Files:**
- Create: throwaway cleanup script (session scratchpad) — no production code.

**Interfaces:**
- Consumes: prevention verified (Task 5); existing `DELETE …/documents/{docId}/subtree` endpoint and `POST …/soft-delete-by-source`, plus direct SQL for hub deletion.
- Produces: Cảng Định An with duplicate-free document set matching the dedup invariant.

**Project:** Cảng Định An = `592c7ff7-9f6f-4cc5-9094-d9b3b685277e`. Clean source folder = `doc_pdf_test/project_1` (79 files).

- [ ] **Step 1: Snapshot before-state**

```sql
-- run via: docker exec daab-postgres psql -U ennam_kg -d ennam_kg -c "..."
SELECT
  count(*) FILTER (WHERE node_type='document')         AS docs,
  count(*) FILTER (WHERE node_type='document_section') AS sections,
  count(*) FILTER (WHERE node_type='document_chunk')   AS chunks
FROM knowledge_nodes WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e';
SELECT count(*) AS similar_edges FROM knowledge_edges
  WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e' AND edge_type='similar_to';
SELECT count(*) live_canon, count(DISTINCT content_hash) distinct_hash
FROM canonical_document
  WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e' AND deleted_at IS NULL;
```
Record the numbers (expect ~145 docs, 74 distinct hashes).

- [ ] **Step 2: Delete the document substrate**

For each `document` hub, delete its subtree via the existing endpoint (removes sections, chunks, embeddings, and chunk `similar_to` edges), then delete the hub node; finally soft-delete canonical rows. A single transactional SQL block is acceptable for this one-shot (the subtree-delete endpoint and SQL are equivalent — SQL is simpler here):

```sql
BEGIN;
-- 1. edges touching any section/chunk (and hub) of this project's documents
DELETE FROM knowledge_edges
 WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e'
   AND (source_id IN (SELECT id FROM knowledge_nodes
          WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e'
            AND node_type IN ('document','document_section','document_chunk'))
     OR target_id IN (SELECT id FROM knowledge_nodes
          WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e'
            AND node_type IN ('document','document_section','document_chunk')));
-- 2. node versions for those nodes
DELETE FROM knowledge_node_versions WHERE node_id IN (
  SELECT id FROM knowledge_nodes
   WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e'
     AND node_type IN ('document','document_section','document_chunk'));
-- 3. the nodes themselves (embeddings cascade via FK ON DELETE CASCADE)
DELETE FROM knowledge_nodes
 WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e'
   AND node_type IN ('document','document_section','document_chunk');
-- 4. soft-delete canonical rows so tier-3 cannot reuse stale rows on re-ingest
UPDATE canonical_document SET deleted_at=NOW(), updated_at=NOW()
 WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e' AND deleted_at IS NULL;
COMMIT;
```
> Confirm the embeddings FK is `ON DELETE CASCADE` (per `DeleteDocumentSubtree` doc-comment). If not, add an explicit `DELETE FROM knowledge_node_embeddings WHERE project_id=…` before step 3.

- [ ] **Step 3: Verify deletion complete (HARD GATE before re-ingest)**

```sql
SELECT
  (SELECT count(*) FROM knowledge_nodes
     WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e'
       AND node_type IN ('document','document_section','document_chunk')) AS live_nodes,
  (SELECT count(*) FROM canonical_document
     WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e' AND deleted_at IS NULL) AS live_canon;
```
Expected: **both 0**. If either is non-zero, DO NOT re-ingest (tier 3 would reuse stale rows) — fix deletion first.

- [ ] **Step 4: Re-ingest the clean folder**

Adapt `ingest_sala.py` (change `PDF_DIR` → `doc_pdf_test/project_1`, `PROJECT_ID` → Cảng, and use a valid Cảng-scoped API key). Upload all 79 files, wait for all drafts terminal. Then wait for the chunk-link worker to rebuild `similar_to` edges (runs every 5 min; or trigger the link endpoint if available).

- [ ] **Step 5: Verify success criteria**

```sql
-- docs == distinct content_hash (the dedup invariant)
SELECT
  (SELECT count(*) FROM knowledge_nodes
     WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e' AND node_type='document') AS docs,
  (SELECT count(DISTINCT content_hash) FROM canonical_document
     WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e' AND deleted_at IS NULL) AS distinct_hash;
-- zero similar_to edges between chunks whose parent docs share a content_hash
-- (after cleanup there are no such duplicate docs, so this must be 0):
SELECT count(*) AS dup_doc_similar_edges
FROM knowledge_edges e
JOIN knowledge_nodes cs ON cs.id=e.source_id AND cs.node_type='document_chunk'
JOIN knowledge_nodes ct ON ct.id=e.target_id AND ct.node_type='document_chunk'
JOIN canonical_document cds ON cds.knowledge_node_id=(cs.properties->>'document_id')::uuid AND cds.deleted_at IS NULL
JOIN canonical_document cdt ON cdt.knowledge_node_id=(ct.properties->>'document_id')::uuid AND cdt.deleted_at IS NULL
WHERE e.project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e'
  AND e.edge_type='similar_to'
  AND cds.content_hash=cdt.content_hash;
```
Expected: **`docs == distinct_hash`** (≈75), **`dup_doc_similar_edges == 0`**.

> If the `document_id` property is not a UUID cast-able string, adjust the join to match how chunk→document is stored (`properties->>'document_id'` compared to the hub node id as text). Verify the exact shape against one chunk row first.

- [ ] **Step 6: Write the Serena checkpoint**

Via `mcp__serena__write_memory("checkpoint/<agent>-2026-07-13", …)`: record before/after counts, the prevention E2E result (Task 5), and any deviations. Update `mem:backlog/daab-retrieval-quality-gaps-postfix` to mark the dedup gap resolved.

---

## Self-Review

**Spec coverage:**
- Prevention §3.2 (Go store) → Task 1. §3.2 (Go handler) → Task 2. §3.3 (Python client) → Task 3. §3.3 (Python engine) + tier ordering §3.1 → Task 4. Prevention E2E (success criterion 1) → Task 5.
- Cleanup §4 (delete + re-ingest) → Task 6. Cleanup ordering gates §4.3 → Task 6 Steps 3 (hard gate) + Task 5 precedes Task 6.
- Success criteria §7: (1) Task 5; (2) Task 6 Step 5; (3) manual graph-retrieve check — folded into Task 6 checkpoint note; (4) regression — Tasks 2/4 run full existing suites; (5) Sala untouched — cleanup is project-scoped to Cảng only.

**Placeholder scan:** No TBDs. Two explicit "verify the exact shape" notes (embeddings FK cascade; chunk→document property) are guarded conditionals with a concrete fallback, not deferrals.

**Type consistency:** `FindByContentHash(ctx, projectID, contentHash)` identical across store impl (Task 1), interface + handler (Task 2). `find_canonical_document_by_content_hash(project_id, content_hash)` identical across client (Task 3) and engine call + tests (Task 4). `result.reused` / `result.failed` / `result.processed` match existing `PipelineBatchResult` fields.

**Out-of-scope confirmed absent:** no near-dup/MinHash, no OCR-variant handling, no cross-project lookup.
