# RAG Citation & Document Navigation Surface — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let LAAM cite the source document of any `kg_search` hit by adding a `kg_get_document` MCP tool (hub id → filename/source/section_count) and persisting the file reference on ingest — without touching the shipped hybrid/e5 retrieval.

> **EXECUTION OUTCOME (2026-06-16):** All tasks done + FR-1 and FR-2 verified E2E. Plus a security fix
> (project-access check + no `stored_path` in the response) and a **platform bug fix**: `UpdateService` was
> built without a node reader (`main.go:369`), so partial node updates REPLACED properties (the decompose step
> wiped `stored_path`). Fixed by wiring `service.WithNodeReader(nodeStore)` — merge semantics restored, Gate 2
> stays off (no update config wired), full internal Go suite green (20 packages, no regressions).

**Architecture:** Three small slices. (1) Go: a new lightweight `GET /nodes/{id}/document-meta` endpoint + an MCP routed-proxy tool `kg_get_document`. (2) Python: thread the already-available `stored_path` from the `extract_upload` worker through `run_batch` into `build_node_payload` so the hub node stores it. (3) A one-off SQL backfill for the existing hub. The bloated synthetic-id `document_tree` is deliberately NOT used (see spec §3/§6).

**Tech Stack:** Go (stdlib `net/http`, `database/sql`), the bridge's `toolRoutes`/`buildToolSchemas` registry, Python 3.12 (pytest), Postgres (pgvector). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-16-rag-citation-navigation-surface-design.md` (CTO-approved, D1-A + D2-A).

> **Security deviation (applied during execution, after a commit security review flagged HIGH IDOR):**
> `GetDocumentMeta` (Task 1) **adds a path-level project-access check** (`middleware.GetDeveloperIdentity` →
> `HasProjectAccess(node.ProjectID)`, 404 on deny) and **does NOT return `stored_path`** in the response
> (internal file path — disclosure risk; citation uses filename per D2-A). `stored_path` is still persisted
> on the hub (Task 3 FR-2) for server-side provenance. The Task 1 code block + Task 6 checks below reflect
> the pre-fix design; the committed code and the spec (§6) carry the secured version.

**Working dirs:** `$GO = ennam.kg.go`, `$PY = ennam.kg.python`, `$WS = repo root`.

---

## File map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `$GO/internal/handler/document.go` | add `GetDocumentMeta` handler + route registration |
| Modify | `$GO/internal/bridge/schema.go` | register `kg_get_document` schema |
| Modify | `$GO/internal/bridge/client.go` | add `kg_get_document` → `/nodes/{document_id}/document-meta` route |
| Modify | `$GO/internal/bridge/schema_test.go` | new schema test + count `33→34` (line 49) |
| Modify | `$GO/internal/bridge/handler_test.go` | `ListTools` count `33→34` (line 276) |
| Modify | `$PY/src/ennam_kg/ingestion/pipeline/nodes.py` | `build_node_payload` persists `stored_path` |
| Modify | `$PY/src/ennam_kg/ingestion/pipeline/engine.py` | `run_batch` forwards `source_stored_path` |
| Modify | `$PY/src/ennam_kg/worker.py` | `handle_extract_upload` passes `stored_path` to `run_batch` |
| Modify | `$PY/tests/test_ingestion/test_nodes.py` (or nearest existing) | unit tests for `build_node_payload` |
| Create | `$GO/db/backfill/2026-06-16-hub-stored-path.sql` | one-off backfill of existing hubs |
| Modify | `$WS/ennam.kg.requirements/documents/phase1/BA-002-mcp-bridge.md` | document `kg_get_document` + LAAM citation pattern |

> **No Go code change to `ingest_upload.go` / `file_upload.go`** — the `extract_upload` message already carries
> `stored_path` (`file_upload.go:290`) and the worker already reads it (`worker.py:49`). FR-2 is Python-only.
> This corrects the spec's §7 "pass stored_path into the draft on upload" bullet (unnecessary).

> **Testing note (honest):** `DocumentHandler` has **no existing unit tests** and holds a concrete
> `*store.NodeStore` (needs a DB), so Task 1 is verified by a live-stack E2E curl (matching how
> `GetSectionContent`/`GetDocumentStructure` are verified today), not a handler unit test. The bridge
> registry (Task 2) and the pure `build_node_payload` (Task 3) are proper TDD units.

---

## Task 1: Go — `GET /nodes/{id}/document-meta` endpoint

**Files:**
- Modify: `$GO/internal/handler/document.go`

- [ ] **Step 1: Add the route**

In `RegisterRoutes` (currently registers `document-structure`, `section-content`, `node-embeddings`), add:

```go
	mux.HandleFunc("GET /api/v1/nodes/{id}/document-meta", h.GetDocumentMeta)
```

- [ ] **Step 2: Implement `GetDocumentMeta`**

Add this method to `document.go` (mirror `GetDocumentStructure`, but return only citation metadata — no tree):

```go
// GetDocumentMeta returns lightweight citation metadata for a document hub node
// (filename, source reference, section count) — NOT the bloated document_tree.
// Backs the kg_get_document MCP tool.
func (h *DocumentHandler) GetDocumentMeta(w http.ResponseWriter, r *http.Request) {
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
	if node.NodeType != "document" && node.NodeType != "external" {
		errorResponse(w, http.StatusBadRequest, "node is not a document hub")
		return
	}
	var props map[string]interface{}
	if len(node.Properties) > 0 {
		_ = json.Unmarshal(node.Properties, &props)
	}
	strOrEmpty := func(v interface{}) string {
		if s, ok := v.(string); ok {
			return s
		}
		return ""
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"node_id":       nodeID,
		"title":         node.Title,
		"source_url":    strOrEmpty(props["source_url"]),
		"stored_path":   strOrEmpty(props["stored_path"]),
		"section_count": props["section_count"],
	})
}
```

(`json`, `errorResponse`, `writeJSON`, `h.nodeStore.GetNode` are all already used by `GetSectionContent` in the same file — no new imports.)

- [ ] **Step 3: Build to verify it compiles**

Run: `cd $GO && go build ./...`
Expected: clean build.

- [ ] **Step 4: Commit**

```bash
cd $GO
git add internal/handler/document.go
git commit -m "feat(handler): add GET /nodes/{id}/document-meta citation endpoint"
```

> E2E verification of this endpoint is Task 6 (needs the live stack).

---

## Task 2: Bridge — register `kg_get_document` MCP tool

**Files:**
- Modify: `$GO/internal/bridge/client.go` (route)
- Modify: `$GO/internal/bridge/schema.go` (schema)
- Modify: `$GO/internal/bridge/schema_test.go` (new test + count)
- Modify: `$GO/internal/bridge/handler_test.go` (count)

- [ ] **Step 1: Write the failing schema test**

Add to `$GO/internal/bridge/schema_test.go`:

```go
func TestBuildToolSchemas_RegistersGetDocument(t *testing.T) {
	schemas := ListToolSchemas()

	s := schemas["kg_get_document"]
	if s == nil {
		t.Fatal("kg_get_document not registered")
	}
	if !s.Properties["document_id"].Required {
		t.Error("kg_get_document.document_id must be required")
	}

	// It is a routed tool — it MUST have an HTTP route (unlike local-execution tools).
	if _, err := GetToolRoute("kg_get_document"); err != nil {
		t.Errorf("kg_get_document must have a route: %v", err)
	}

	// Validation rejects a call with no document_id, accepts a well-formed one.
	if vr := ValidateToolParams("kg_get_document", map[string]interface{}{}); vr.Valid {
		t.Error("expected validation failure when document_id is missing")
	}
	if vr := ValidateToolParams("kg_get_document", map[string]interface{}{
		"document_id": "11111111-1111-4111-8111-111111111111",
	}); !vr.Valid {
		t.Errorf("expected valid call, got: %s", vr.Error())
	}
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd $GO && go test ./internal/bridge/ -run TestBuildToolSchemas_RegistersGetDocument -count=1`
Expected: FAIL — `kg_get_document not registered`.

- [ ] **Step 3: Register the schema**

In `$GO/internal/bridge/schema.go`, inside `buildToolSchemas()` (before the final `return schemas`), add:

```go
	// === kg_get_document (citation metadata — routed HTTP-proxy tool) ===
	schemas["kg_get_document"] = &ToolSchema{
		ToolName: "kg_get_document",
		Description: "Resolve a document's hub id to its citation metadata (filename, source reference, " +
			"section count). Pass the document_id found in a kg_search result's section properties to cite the source.",
		Properties: map[string]ParamSchema{
			"document_id": {
				Type:        TypeString,
				Required:    true,
				Description: "UUID of the document hub node (a section's properties.document_id from kg_search)",
				Format:      "uuid",
				Pattern:     uuidPattern,
			},
			"project_id": projectIDParam,
		},
	}
```

- [ ] **Step 4: Add the route**

In `$GO/internal/bridge/client.go`, inside the `toolRoutes` map, add:

```go
	"kg_get_document": {
		Method:       http.MethodGet,
		PathTemplate: apiPrefix + "/nodes/{document_id}/document-meta",
		PathParams:   []string{"document_id"},
	},
```

(The server route is `/nodes/{id}/document-meta`; the bridge substitutes `{document_id}` → the UUID, producing `/api/v1/nodes/<uuid>/document-meta`, which the server's `{id}` captures. `project_id`, if passed, rides along as a harmless query param.)

- [ ] **Step 5: Fix the two count assertions (33 → 34)**

In `$GO/internal/bridge/schema_test.go` line ~49:
```go
	if len(schemas) != 34 {
		t.Errorf("expected 34 tool schemas, got %d", len(schemas))
	}
```

In `$GO/internal/bridge/handler_test.go` line ~276:
```go
	if len(tools) != 34 {
		t.Errorf("expected 34 tools, got %d", len(tools))
	}
```

> These are the **only** count assertions that move. `TestAllToolSchemasMatchRoutes` passes (the tool has a
> route), `e2e_tools_test.go:805`'s relational check holds automatically (34 == 32 routes + 2 local), and
> `TestIntegration_AllToolsRegistered` only checks its hardcoded subset (no total count) — none need edits.

- [ ] **Step 6: Run the full bridge suite to verify green**

Run: `cd $GO && go test ./internal/bridge/ -count=1 -race`
Expected: PASS — the new schema test, the two updated counts, and all existing tests.

- [ ] **Step 7: Commit**

```bash
cd $GO
git add internal/bridge/schema.go internal/bridge/client.go internal/bridge/schema_test.go internal/bridge/handler_test.go
git commit -m "feat(bridge): add kg_get_document routed tool (citation metadata)"
```

---

## Task 3: Python — persist `stored_path` on the hub (FR-2)

**Files:**
- Modify: `$PY/src/ennam_kg/ingestion/pipeline/nodes.py`
- Modify: `$PY/src/ennam_kg/ingestion/pipeline/engine.py`
- Modify: `$PY/src/ennam_kg/worker.py`
- Test: `$PY/tests/test_ingestion/test_nodes.py` (create if absent; else nearest existing pipeline test module)

- [ ] **Step 1: Write the failing unit test for `build_node_payload`**

Create/append `$PY/tests/test_ingestion/test_nodes.py`:

```python
from ennam_kg.ingestion.pipeline.nodes import build_node_payload
from ennam_kg.ingestion.pipeline.extract import ExtractionResult


def _draft():
    return {"id": "d1", "title": "Report.md", "content_raw": "hello",
            "source_type": "local_upload", "content_format": "md"}


def test_build_node_payload_persists_stored_path():
    payload = build_node_payload(
        project_id="p1", draft=_draft(), extraction=ExtractionResult(),
        node_type="document", stored_path="p1/up1/Report.md",
    )
    assert payload["properties"]["stored_path"] == "p1/up1/Report.md"


def test_build_node_payload_omits_empty_stored_path():
    payload = build_node_payload(
        project_id="p1", draft=_draft(), extraction=ExtractionResult(),
        node_type="document",  # stored_path defaults to ""
    )
    assert "stored_path" not in payload["properties"]
```

> If `ExtractionResult()` needs required args, mirror the construction used by an existing test in
> `tests/test_ingestion/` (e.g. `test_pipeline.py`); the two assertions above are what matter.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd $PY && uv run pytest tests/test_ingestion/test_nodes.py -q`
Expected: FAIL — `build_node_payload() got an unexpected keyword argument 'stored_path'`.

- [ ] **Step 3: Add the `stored_path` param to `build_node_payload`**

In `$PY/src/ennam_kg/ingestion/pipeline/nodes.py`, change the signature and add the property:

```python
def build_node_payload(
    *,
    project_id: str,
    draft: dict[str, Any],
    extraction: ExtractionResult,
    node_type: str,
    stored_path: str = "",
) -> dict[str, Any]:
```

Then, after the existing `if source_url:` block, add:

```python
    if stored_path:
        properties["stored_path"] = stored_path
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd $PY && uv run pytest tests/test_ingestion/test_nodes.py -q`
Expected: PASS (both cases).

- [ ] **Step 5: Forward `stored_path` through `run_batch`**

In `$PY/src/ennam_kg/ingestion/pipeline/engine.py`, add a parameter to `run_batch`:

```python
    async def run_batch(
        self,
        *,
        project_id: str,
        draft_ids: list[str],
        batch_id: str | None = None,
        source_stored_path: str = "",
    ) -> PipelineBatchResult:
```

and pass it into the `build_node_payload(...)` call in the same method:

```python
                payload = build_node_payload(
                    project_id=project_id,
                    draft=draft,
                    extraction=extraction,
                    node_type=node_type,
                    stored_path=source_stored_path,
                )
```

- [ ] **Step 6: Pass `stored_path` from the worker**

In `$PY/src/ennam_kg/worker.py`, in `handle_extract_upload`, update the `run_batch` call (it already has `stored_path` in scope from line 49):

```python
        pipe_result = await ingestion_engine.run_batch(
            project_id=project_id,
            draft_ids=[draft_id],
            batch_id=f"extract:{upload_id or draft_id}",
            source_stored_path=stored_path,
        )
```

- [ ] **Step 7: Run the ingestion test module + lint**

Run: `cd $PY && uv run pytest tests/test_ingestion/ -q && uv run ruff check src/ennam_kg/ingestion src/ennam_kg/worker.py`
Expected: PASS, no lint errors.

- [ ] **Step 8: Commit**

```bash
cd $PY
git add src/ennam_kg/ingestion/pipeline/nodes.py src/ennam_kg/ingestion/pipeline/engine.py src/ennam_kg/worker.py tests/test_ingestion/test_nodes.py
git commit -m "feat(ingestion): persist stored_path on document hub for citation (FR-2)"
```

---

## Task 4: One-off backfill of existing hubs

**Files:**
- Create: `$GO/db/backfill/2026-06-16-hub-stored-path.sql`

- [ ] **Step 1: Write the backfill SQL**

Create `$GO/db/backfill/2026-06-16-hub-stored-path.sql`:

```sql
-- One-off: backfill properties.stored_path on document hub nodes that were
-- ingested before FR-2. Matches the upload by project + original filename
-- (hub.title == uploaded_files.original_filename). Idempotent: only fills empties.
UPDATE knowledge_nodes kn
SET properties = kn.properties || jsonb_build_object('stored_path', uf.stored_path)
FROM uploaded_files uf
WHERE kn.node_type = 'document'
  AND kn.project_id = uf.project_id
  AND kn.title = uf.original_filename
  AND COALESCE(kn.properties->>'stored_path', '') = '';
```

- [ ] **Step 2: Run it against the dev DB and verify**

Run:
```bash
docker exec -i -e PGPASSWORD=ennam_kg_dev ennam-kg-postgres \
  psql -U ennam_kg -d ennam_kg < $GO/db/backfill/2026-06-16-hub-stored-path.sql
docker exec -e PGPASSWORD=ennam_kg_dev ennam-kg-postgres \
  psql -U ennam_kg -d ennam_kg -tA -c \
  "SELECT title, properties->>'stored_path' FROM knowledge_nodes WHERE node_type='document';"
```
Expected: the Cảng Định An hub now shows a non-empty `stored_path` (e.g. `<project>/<upload>/2026-05-29-cang-dinh-an-deal-report.md`). If it is still empty, the upload row's `original_filename` differs from the hub title — inspect `SELECT original_filename FROM uploaded_files;` and adjust the match, then re-run (idempotent).

- [ ] **Step 3: Commit the script**

```bash
cd $GO
git add db/backfill/2026-06-16-hub-stored-path.sql
git commit -m "chore(db): one-off backfill of hub stored_path for citation (FR-2)"
```

---

## Task 5: Docs — LAAM citation pattern (FR-4)

**Files:**
- Modify: `$WS/ennam.kg.requirements/documents/phase1/BA-002-mcp-bridge.md`

- [ ] **Step 1: Document the tool + the citation pattern**

Append to `BA-002-mcp-bridge.md` (and bump any tool-count phrasing from 33 to **34**):

```markdown
### `kg_get_document` — document citation metadata

Resolves a document hub id → `{ node_id, title (filename), source_url, stored_path, section_count }`.
It does NOT return `document_tree` (synthetic ids + bloat).

**LAAM citation pattern:**
1. `kg_search(query, mode=hybrid)` → each result has the section `title`, `line_start/end`, and
   `properties.document_id` (the hub id), plus `properties.content` (answer text).
2. For each unique `document_id`, call `kg_get_document(document_id)` once.
3. Cite as `[<title>, section '<section title>', lines <start>-<end>]`.

**Graceful-empty rule:** file-less sources (e.g. `kg_ingest_node` memory) return `stored_path`/`source_url`
as empty strings. LAAM MUST cite by filename + section + lines in that case and MUST NOT render an empty
value as a link. `stored_path` is an internal server-side path — never surface it as a clickable link.
```

- [ ] **Step 2: Commit (separate repo)**

```bash
cd $WS/ennam.kg.requirements
git add documents/phase1/BA-002-mcp-bridge.md
git commit -m "docs(BA-002): document kg_get_document + LAAM citation pattern"
```

---

## Task 6: E2E verification (live stack)

**Files:** none (verification only). Requires the Docker stack running (`docker compose ps` healthy).

- [ ] **Step 1: Rebuild + restart the Go server and Python worker with the new code**

Run: `cd $WS && docker compose up -d --build kg-server worker indexer`
Expected: services healthy (`docker compose ps`).

- [ ] **Step 2: Verify the endpoint + tool end-to-end**

Run (dev bootstrap key + the known hub id):
```bash
KEY=ennam_kg_dev_000000000000000000000000
# 2a. New endpoint returns trimmed metadata (no document_tree), stored_path now populated:
curl -s http://localhost:8080/api/v1/nodes/11187b28-2109-4b84-a87e-7a6fe5ee47fe/document-meta \
  -H "Authorization: Bearer $KEY" | python3 -m json.tool
# 2b. A non-hub (section) id is rejected with 400:
curl -s -o /dev/null -w "%{http_code}\n" \
  http://localhost:8080/api/v1/nodes/b2e49833-caa1-49ae-bfea-8aab3f2b702b/document-meta \
  -H "Authorization: Bearer $KEY"
```
Expected: 2a → JSON with `title`, non-empty `stored_path`, `section_count`, and **no** `document_tree`;
2b → `400`.

- [ ] **Step 3: Verify a fresh upload persists stored_path (FR-2 path)**

Upload any small `.md`, then check its hub:
```bash
PID=1a1d1936-1c76-4460-b398-6742a30d0c58
KEY=ennam_kg_dev_000000000000000000000000
curl -s -X POST "http://localhost:8080/api/v1/projects/$PID/upload" \
  -H "Authorization: Bearer $KEY" -F "file=@/tmp/smoke.md" -F "auto_approve=true" >/dev/null
# wait for the worker, then:
docker exec -e PGPASSWORD=ennam_kg_dev ennam-kg-postgres psql -U ennam_kg -d ennam_kg -tA -c \
  "SELECT title, properties->>'stored_path' FROM knowledge_nodes WHERE node_type='document' ORDER BY created_at DESC LIMIT 1;"
```
Expected: the newest hub shows a non-empty `stored_path` (proves the worker→run_batch→build_node_payload wiring).

- [ ] **Step 4: Record results**

Note the observed outputs under this task (or in a checkpoint). If any step fails, debug with
`superpowers:systematic-debugging` before marking the plan complete.

---

## Self-Review

**Spec coverage:**
- FR-1 (kg_get_document, no tree) → Task 1 (endpoint) + Task 2 (tool). ✅
- FR-2 (persist source_url/stored_path on hub) → Task 3 (Python wiring) + Task 4 (backfill old data). ✅
- FR-3 → dropped in spec (D1-A locked); not a task. ✅
- FR-4 (docs + graceful-empty) → Task 5. ✅
- Acceptance #1 (metadata payload, no tree) → Task 6 Step 2a. #2 (new ingest has stored_path) → Task 6 Step 3. #3 (cite without kg_get_node) → Task 5 pattern. #4 (no retrieval regression) → nothing touches search.go (`go test ./internal/...` stays green). #5 (tool count) → Task 2. #6 (file-less empty strings) → `strOrEmpty` in Task 1 + Task 5 rule. ✅

**Type consistency:** `build_node_payload(..., stored_path="")` defined in Task 3 Step 3, called in Task 3 Step 5 (`run_batch`) with `stored_path=source_stored_path`; `run_batch(..., source_stored_path="")` defined Step 5, called Step 6 (worker). `GetDocumentMeta` defined Task 1, routed in Task 2 (`/document-meta`), verified Task 6. Tool name `kg_get_document` identical across Tasks 2, 5, 6. Counts 33→34 consistent.

**Placeholder scan:** none — every code/command step shows concrete content. The one runtime value (`/tmp/smoke.md`) is an operator-supplied test file.

**No-regression guard:** before final commit, run `cd $GO && make test` and `cd $PY && uv run pytest` — both green; `kg_search`/`search.go` untouched.
