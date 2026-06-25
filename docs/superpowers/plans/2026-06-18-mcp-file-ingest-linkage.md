# MCP File Ingest & Linkage (IMP-009) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an MCP-only satellite drive DAAB's existing file pipeline — agent signals ingest-intent, host streams the binary over a bridge HTTP route, polls status, then cites and downloads the original.

**Architecture:** Binary over HTTP (new **raw streaming** bridge routes proxying the Go `/upload`+`/download`), coordination over MCP tools. No new ingest/RAG/storage. Status is resolved **read-side** from the existing `canonical_document` + `draft_nodes` tables (no worker change, no migration). Security is enforced **in the routes** (in-route `readonly` reject + size cap + project-scoped resolution), not via a token.

**Tech Stack:** Go (`net/http`, `database/sql`), the MCP bridge (`internal/bridge`), the Go REST API (`internal/handler`, `internal/store`). Tests: `go test` (table tests + `httptest`).

**Spec:** `docs/superpowers/specs/2026-06-18-mcp-file-ingest-linkage-design.md` · **Requirement:** `ennam.kg.requirements/documents/improvements/IMP-009-mcp-file-ingest-linkage.md`

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `internal/store/uploaded_file.go` | `FindByDraftNodeID` + `GetIngestStatusRow` queries | Modify |
| `internal/handler/ingest_status.go` | `deriveIngestStatus` (pure) + `GET …/uploads/{uploadId}/ingest-status` handler | Create |
| `internal/handler/ingest_upload.go` | Register the new status route | Modify |
| `internal/bridge/schema.go` | Schemas for `kg_ingest_status`, `kg_request_file_upload`; add `kg_request_file_upload` to `localToolNames`; bump count | Modify |
| `internal/bridge/client.go` | `toolRoutes["kg_ingest_status"]` (RouteRead) | Modify |
| `internal/bridge/serve.go` | `makeToolHandler` case for `kg_request_file_upload`; mount `POST /files` + `GET /files/{document_id}` raw proxies | Modify |
| `internal/bridge/files_proxy.go` | Raw streaming proxy handlers (`POST /files`, `GET /files/{document_id}`) | Create |
| `internal/handler/document.go` | `download_url` on document-meta | Modify |
| `internal/bridge/schema_test.go`, `e2e_tools_test.go` | Count 38→40 + invariant | Modify |

**Verified facts this plan relies on** (do not re-derive):
- `UploadedFileStore.GetByID(ctx, projectID, id)` exists (`uploaded_file.go:52`); model `UploadedFile` has `ID, ProjectID, DraftNodeID *string, OriginalFilename, StoredPath, …, CreatedAt` (`models/uploaded_file.go:6`).
- `canonical_document(draft_node_id UNIQUE → knowledge_node_id, deleted_at)` (migration 060); written by the worker **only on success**.
- `draft_nodes.id, status` (status lifecycle, indexed migration 047); `uploaded_files.draft_node_id → draft_nodes ON DELETE SET NULL` (migration 054).
- `completeDraftRequest` carries only `{status, knowledge_node_id}` (no failure reason) → status `failed` is **bare** (BR-006).
- Go routes: upload `POST /api/v1/projects/{projectId}/upload` (returns `{draft_id, upload_id}`, `service/file_upload.go:34`), download `GET /api/v1/projects/{projectId}/uploads/{uploadId}/download` (`ingest_upload.go`).
- Bridge: `apiPrefix = "/api/v1"`; `toolRoutes` map with `ToolRoute{Method, PathTemplate, PathParams, QueryParams, Class}` and `RouteRead|RouteWrite|RouteLocal` (`client.go:32-44,118`). `makeToolHandler` has a `switch toolName` returning early for special tools; readonly gate blocks `toolRoutes[name].Class != RouteRead` and `localToolNames[name]` (`serve.go:262-281`). Schemas declared as `schemas["x"] = &ToolSchema{ToolName, Description, Properties: map[string]ParamSchema{...}}` (`schema.go:1196`). Bearer middleware injects `ctxKeyScope` ("full"/"readonly") (`middleware_auth.go:51`); the bridge reaches Go via `cfg.ServerURL` + `cfg.APIKey`.
- Count: `schema_test.go:51` asserts `len(schemas)==38`; invariant `len(schemas)==len(ListToolNames)+len(localToolNames)` (`e2e_tools_test.go:805`); `localToolNames` currently has 2 entries.

---

## Task 1: `UploadedFileStore.FindByDraftNodeID`

**Files:**
- Modify: `internal/store/uploaded_file.go`
- Test: `internal/store/uploaded_file_test.go`

- [ ] **Step 1: Write the failing test**

Add to `internal/store/uploaded_file_test.go` (mirror the existing store-test setup in that file for DB/seed; if none exists, mirror `internal/store/canonical_document_test.go`):

```go
func TestUploadedFileStore_FindByDraftNodeID(t *testing.T) {
	db := newTestDB(t) // existing helper in store tests
	store := NewUploadedFileStore(db)
	ctx := context.Background()
	projectID := seedProject(t, db)
	draftID := seedDraftNode(t, db, projectID)

	// Arrange: an upload row linked to draftID.
	up := &models.UploadedFile{
		ProjectID: projectID, OriginalFilename: "c.pdf",
		StoredPath: "uploads/c.pdf", FileSizeBytes: 10, UploadedBy: "tester",
	}
	if err := store.Create(ctx, up); err != nil {
		t.Fatalf("create: %v", err)
	}
	if err := store.SetDraftNodeID(ctx, projectID, up.ID, draftID); err != nil {
		t.Fatalf("set draft: %v", err)
	}

	// Act
	got, err := store.FindByDraftNodeID(ctx, projectID, draftID)

	// Assert
	if err != nil {
		t.Fatalf("FindByDraftNodeID: %v", err)
	}
	if got.ID != up.ID {
		t.Errorf("got upload %q, want %q", got.ID, up.ID)
	}

	// Unknown draft id → not found error.
	if _, err := store.FindByDraftNodeID(ctx, projectID, "00000000-0000-0000-0000-000000000000"); err == nil {
		t.Error("expected error for unknown draft_node_id")
	}
}
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestUploadedFileStore_FindByDraftNodeID -v`
Expected: FAIL — `store.FindByDraftNodeID undefined`.

- [ ] **Step 3: Implement the query**

Add after `GetByID` in `internal/store/uploaded_file.go` (reuses `scanUploadedFile`):

```go
// FindByDraftNodeID returns the active upload linked to a draft node.
func (s *UploadedFileStore) FindByDraftNodeID(ctx context.Context, projectID, draftNodeID string) (*models.UploadedFile, error) {
	query := `
		SELECT id, project_id, draft_node_id, original_filename, stored_path, mime_type,
		       file_size_bytes, content_extracted, uploaded_by, created_at, deleted_at
		FROM uploaded_files
		WHERE project_id = $1 AND draft_node_id = $2 AND deleted_at IS NULL`
	file, err := scanUploadedFile(s.db.QueryRowContext(ctx, query, projectID, draftNodeID))
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("upload for draft %q not found", draftNodeID)
		}
		return nil, fmt.Errorf("find uploaded file by draft: %w", err)
	}
	return file, nil
}
```

- [ ] **Step 4: Run it — verify it passes**

Run: `go test ./internal/store/ -run TestUploadedFileStore_FindByDraftNodeID -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/store/uploaded_file.go internal/store/uploaded_file_test.go
git commit -m "feat(store): add UploadedFileStore.FindByDraftNodeID for ingest status/download lookup"
```

---

## Task 2: Ingest-status resolution (pure derivation + store row query)

The status decision is a **pure function** over `(draft_node_id, draft status, canonical knowledge_node_id, upload age)` — test it in isolation (Rule 9).

**Files:**
- Modify: `internal/store/uploaded_file.go` (add `GetIngestStatusRow`)
- Create: `internal/handler/ingest_status.go` (`deriveIngestStatus` + handler)
- Test: `internal/handler/ingest_status_test.go`

- [ ] **Step 1: Write the failing test for the pure derivation**

`internal/handler/ingest_status_test.go`:

```go
package handler

import (
	"testing"
	"time"
)

func TestDeriveIngestStatus(t *testing.T) {
	now := time.Date(2026, 6, 18, 12, 0, 0, 0, time.UTC)
	timeout := 30 * time.Minute
	hub := "11111111-1111-1111-1111-111111111111"

	cases := []struct {
		name        string
		row         ingestStatusRow
		wantStatus  string
		wantDocID   string
	}{
		{"done when canonical row present",
			ingestStatusRow{DraftNodeID: ptr("d"), DraftStatus: ptr("processing"), KnowledgeNodeID: ptr(hub), CreatedAt: now.Add(-time.Minute)},
			"done", hub},
		{"pending link window (no draft yet)",
			ingestStatusRow{DraftNodeID: nil, DraftStatus: nil, KnowledgeNodeID: nil, CreatedAt: now.Add(-time.Minute)},
			"processing", ""},
		{"failed when draft failed",
			ingestStatusRow{DraftNodeID: ptr("d"), DraftStatus: ptr("failed"), KnowledgeNodeID: nil, CreatedAt: now.Add(-time.Minute)},
			"failed", ""},
		{"processing while in flight",
			ingestStatusRow{DraftNodeID: ptr("d"), DraftStatus: ptr("processing"), KnowledgeNodeID: nil, CreatedAt: now.Add(-time.Minute)},
			"processing", ""},
		{"timeout → failed when stuck past threshold",
			ingestStatusRow{DraftNodeID: ptr("d"), DraftStatus: ptr("processing"), KnowledgeNodeID: nil, CreatedAt: now.Add(-31 * time.Minute)},
			"failed", ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			gotStatus, gotDoc := deriveIngestStatus(tc.row, now, timeout)
			if gotStatus != tc.wantStatus || gotDoc != tc.wantDocID {
				t.Errorf("got (%q,%q), want (%q,%q)", gotStatus, gotDoc, tc.wantStatus, tc.wantDocID)
			}
		})
	}
}

func ptr(s string) *string { return &s }
```

- [ ] **Step 2: Run it — verify it fails**

Run: `go test ./internal/handler/ -run TestDeriveIngestStatus -v`
Expected: FAIL — `deriveIngestStatus` / `ingestStatusRow` undefined.

- [ ] **Step 3: Implement the pure derivation + row type**

Create `internal/handler/ingest_status.go`:

```go
package handler

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/ennam/ennam-kg/internal/store"
)

// ingestStatusRow is the raw correlation read for an upload (Task 2 store query).
type ingestStatusRow struct {
	DraftNodeID     *string
	DraftStatus     *string
	KnowledgeNodeID *string
	CreatedAt       time.Time
}

// deriveIngestStatus maps the correlation row to the MCP-facing status.
// Authoritative success = a canonical_document row exists (carries knowledge_node_id).
// A stuck "processing" past `timeout` is reported as "failed" — a dead worker
// writes nothing, so terminal state is a read-time judgment (BR-005).
func deriveIngestStatus(row ingestStatusRow, now time.Time, timeout time.Duration) (status string, documentID string) {
	if row.KnowledgeNodeID != nil && *row.KnowledgeNodeID != "" {
		return "done", *row.KnowledgeNodeID
	}
	if row.DraftStatus != nil && *row.DraftStatus == "failed" {
		return "failed", ""
	}
	if now.Sub(row.CreatedAt) > timeout {
		return "failed", ""
	}
	return "processing", ""
}
```

- [ ] **Step 4: Run it — verify it passes**

Run: `go test ./internal/handler/ -run TestDeriveIngestStatus -v`
Expected: PASS (all 5 cases).

- [ ] **Step 5: Add the store row query**

Add to `internal/store/uploaded_file.go`:

```go
// IngestStatusRow is the correlation read backing kg_ingest_status.
type IngestStatusRow struct {
	DraftNodeID     *string
	DraftStatus     *string
	KnowledgeNodeID *string
	CreatedAt       time.Time
}

// GetIngestStatusRow joins uploaded_files → draft_nodes → canonical_document
// for one upload. Returns sql.ErrNoRows if the upload does not exist.
func (s *UploadedFileStore) GetIngestStatusRow(ctx context.Context, projectID, uploadID string) (*IngestStatusRow, error) {
	query := `
		SELECT uf.draft_node_id, dn.status, cd.knowledge_node_id, uf.created_at
		FROM uploaded_files uf
		LEFT JOIN draft_nodes dn ON dn.id = uf.draft_node_id
		LEFT JOIN canonical_document cd
		       ON cd.draft_node_id = uf.draft_node_id AND cd.deleted_at IS NULL
		WHERE uf.project_id = $1 AND uf.id = $2 AND uf.deleted_at IS NULL`
	var r IngestStatusRow
	var draftID, draftStatus, knID sql.NullString
	err := s.db.QueryRowContext(ctx, query, projectID, uploadID).
		Scan(&draftID, &draftStatus, &knID, &r.CreatedAt)
	if err != nil {
		return nil, err
	}
	if draftID.Valid {
		r.DraftNodeID = &draftID.String
	}
	if draftStatus.Valid {
		r.DraftStatus = &draftStatus.String
	}
	if knID.Valid {
		r.KnowledgeNodeID = &knID.String
	}
	return &r, nil
}
```

- [ ] **Step 6: Write the HTTP handler + register the route**

Append to `internal/handler/ingest_status.go`:

```go
// IngestStatusHandler serves GET /api/v1/projects/{projectId}/uploads/{uploadId}/ingest-status.
type IngestStatusHandler struct {
	store   *store.UploadedFileStore
	timeout time.Duration
}

func NewIngestStatusHandler(s *store.UploadedFileStore) *IngestStatusHandler {
	return &IngestStatusHandler{store: s, timeout: 30 * time.Minute}
}

func (h *IngestStatusHandler) Status(w http.ResponseWriter, r *http.Request) {
	projectID := r.PathValue("projectId")
	uploadID := r.PathValue("uploadId")

	row, err := h.store.GetIngestStatusRow(r.Context(), projectID, uploadID)
	if err != nil {
		http.Error(w, "upload not found", http.StatusNotFound)
		return
	}
	status, docID := deriveIngestStatus(
		ingestStatusRow{
			DraftNodeID: row.DraftNodeID, DraftStatus: row.DraftStatus,
			KnowledgeNodeID: row.KnowledgeNodeID, CreatedAt: row.CreatedAt,
		},
		time.Now().UTC(), h.timeout,
	)
	resp := map[string]any{"status": status}
	if docID != "" {
		resp["document_id"] = docID
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}
```

Register it on the **Go API mux `apiMux`** (the var in `cmd/kg-server/main.go:340`, where `nodeHandler.RegisterRoutes(apiMux)` etc. are called — NOT the bridge mux). Give the handler a `RegisterRoutes` method mirroring `ingest_upload.go:31`:

```go
// internal/handler/ingest_status.go
func (h *IngestStatusHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/projects/{projectId}/uploads/{uploadId}/ingest-status", h.Status)
}
```

Then in `cmd/kg-server/main.go`, alongside the other `RegisterRoutes(apiMux)` calls (~line 371):

```go
	ingestStatusHandler := handler.NewIngestStatusHandler(uploadedFileStore) // reuse the existing UploadedFileStore instance
	ingestStatusHandler.RegisterRoutes(apiMux)
```

- [ ] **Step 7: Run handler + store tests**

Run: `go test ./internal/handler/ -run TestDeriveIngestStatus -v && go test ./internal/store/ -run TestUploadedFileStore -v`
Expected: PASS. (The DB-backed `GetIngestStatusRow` is exercised end-to-end in Task 8's integration smoke; the derivation logic — the part with branches — is fully unit-covered here.)

- [ ] **Step 8: Verify build**

Run: `go build ./... && go vet ./internal/handler/ ./internal/store/`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add internal/store/uploaded_file.go internal/handler/ingest_status.go internal/handler/ingest_status_test.go cmd/kg-server/main.go
git commit -m "feat(handler): add read-side ingest-status endpoint (canonical_document + draft_nodes)"
```

---

## Task 3: `kg_ingest_status` MCP tool (routed, read-class)

**Files:**
- Modify: `internal/bridge/client.go` (`toolRoutes`)
- Modify: `internal/bridge/schema.go` (schema)
- Test: `internal/bridge/schema_test.go`

- [ ] **Step 1: Bump the count assertion + add a schema-presence test**

In `internal/bridge/schema_test.go`, the count assertion lives inside `TestAllToolSchemasRegistered` (line 9) as `if len(schemas) != 38` — change it to `!= 39`. Then add:

```go
func TestSchema_HasIngestStatus(t *testing.T) {
	schemas := ListToolSchemas() // the real builder entry point (schema.go:216)
	s, ok := schemas["kg_ingest_status"]
	if !ok {
		t.Fatal("kg_ingest_status schema missing")
	}
	if _, ok := s.Properties["upload_id"]; !ok {
		t.Error("kg_ingest_status must accept upload_id")
	}
}
```

- [ ] **Step 2: Run it — verify it fails**

Run: `go test ./internal/bridge/ -run 'TestSchema_HasIngestStatus|TestAllToolSchemasRegistered' -v`
Expected: FAIL — schema missing + count is 38 not 39.

- [ ] **Step 3: Add the route + schema**

In `internal/bridge/client.go` `toolRoutes`, add (read-class, GET, path params):

```go
	"kg_ingest_status": {
		Method:       http.MethodGet,
		PathTemplate: apiPrefix + "/projects/{projectId}/uploads/{uploadId}/ingest-status",
		PathParams:   []string{"projectId", "uploadId"},
		Class:        RouteRead,
	},
```

In `internal/bridge/schema.go`, add to the schema map (mirror `kg_get_document`):

```go
	// === kg_ingest_status (IMP-009 — routed HTTP-proxy read tool) ===
	schemas["kg_ingest_status"] = &ToolSchema{
		ToolName:    "kg_ingest_status",
		Description: "Poll a file ingest by upload_id. Returns status (processing|done|failed) and, once done, the document_id to cite or download.",
		Properties: map[string]ParamSchema{
			"upload_id": {
				Type:        TypeString,
				Required:    true,
				Description: "The upload_id returned when the file was POSTed to the upload_url",
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

> Note: the route uses path param `uploadId`; the bridge's default-project fill injects `projectId`. Ensure the tool maps `upload_id` (snake) → the `uploadId` path param. If `toolRoutes` path substitution is case/name-exact, add `upload_id` handling: either name the param `uploadId` in the schema, or map it in the route's `PathParams`. Verify against how `kg_end_session` maps `session_id` → `{session_id}` and follow the same convention (use `upload_id` in both schema and `PathParams`/template).

- [ ] **Step 4: Run it — verify it passes**

Run: `go test ./internal/bridge/ -run 'TestSchema_HasIngestStatus|TestAllToolSchemasRegistered' -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/bridge/client.go internal/bridge/schema.go internal/bridge/schema_test.go
git commit -m "feat(bridge): add kg_ingest_status routed read tool"
```

---

## Task 4: `kg_request_file_upload` MCP tool (bridge-internal, confirm-gated)

This tool does **not** proxy to Go. It returns the `/files` upload URL and exists to give the agent a discoverable, confirm-gated intent signal. It is dispatched in-bridge and counted on the non-routed side (`localToolNames`) so the readonly gate blocks it and the count invariant balances.

**Files:**
- Modify: `internal/bridge/schema.go` (schema + `localToolNames`)
- Modify: `internal/bridge/serve.go` (`makeToolHandler` case)
- Test: `internal/bridge/schema_test.go`

- [ ] **Step 1: Bump count + add presence test**

In `schema_test.go`, `TestAllToolSchemasRegistered` change `!= 39` → `!= 40`, and add:

```go
func TestSchema_HasRequestFileUpload(t *testing.T) {
	schemas := ListToolSchemas()
	if _, ok := schemas["kg_request_file_upload"]; !ok {
		t.Fatal("kg_request_file_upload schema missing")
	}
	if !localToolNames["kg_request_file_upload"] {
		t.Error("kg_request_file_upload must be registered in localToolNames (non-routed)")
	}
}
```

- [ ] **Step 2: Run it — verify it fails**

Run: `go test ./internal/bridge/ -run 'TestSchema_HasRequestFileUpload|TestAllToolSchemasRegistered' -v`
Expected: FAIL — schema missing, not in localToolNames, count 39≠40.

- [ ] **Step 3: Add schema + register in localToolNames**

In `internal/bridge/schema.go`:

```go
	// === kg_request_file_upload (IMP-009 — bridge-internal write/confirm tool) ===
	schemas["kg_request_file_upload"] = &ToolSchema{
		ToolName:    "kg_request_file_upload",
		Description: "Signal intent to ingest a file. Returns upload_url; the host then POSTs the file bytes there (binary travels over HTTP, never over MCP). Confirm-gated.",
		Properties: map[string]ParamSchema{
			"filename": {
				Type:        TypeString,
				Required:    true,
				Description: "The file's name (e.g. contract.pdf)",
			},
			"project_id": {
				Type:        TypeString,
				Required:    false,
				Description: "Optional project id (falls back to the default project)",
			},
			"content_format": {
				Type:        TypeString,
				Required:    false,
				Description: "Optional hint: pdf | markdown | text",
			},
		},
	}
```

In the `localToolNames` map (`schema.go:180`), add:

```go
	"kg_request_file_upload": true,
```

- [ ] **Step 4: Dispatch it in `makeToolHandler`**

In `internal/bridge/serve.go`, add a case to the `switch toolName` (next to `kg_index_source`/`kg_index_status`). The upload URL is the bridge's own `/files` route; the bridge is reached by the satellite at its public base, so return a relative path the host resolves against the same origin:

```go
		case "kg_request_file_upload":
			// Bridge-internal: no HTTP proxy. Return the upload route; the host
			// POSTs the bytes there. Confirm/readonly handled above + client-side.
			payload, _ := json.Marshal(map[string]any{
				"upload_url": "/files",
				"filename":   params["filename"],
			})
			return &mcp.CallToolResult{
				Content: []mcp.Content{&mcp.TextContent{Text: string(payload)}},
			}, nil
```

(Add `"encoding/json"` to `serve.go` imports if not present.)

> The readonly gate at `serve.go:273` already blocks `localToolNames` tools under a `readonly` scope — so a read-only satellite cannot request an upload. Client-side write/confirm classification (IMP-008) is the satellite's concern; note for the LAAM integration: treat `kg_request_file_upload` as write/confirm even though the bridge dispatches it locally.

- [ ] **Step 5: Run it — verify it passes**

Run: `go test ./internal/bridge/ -run 'TestSchema_HasRequestFileUpload|TestAllToolSchemasRegistered' -v && go build ./...`
Expected: PASS + build clean.

- [ ] **Step 6: Commit**

```bash
git add internal/bridge/schema.go internal/bridge/serve.go internal/bridge/schema_test.go
git commit -m "feat(bridge): add kg_request_file_upload intent/confirm tool (bridge-internal)"
```

---

## Task 5: `POST /files` raw streaming proxy

**Files:**
- Create: `internal/bridge/files_proxy.go`
- Modify: `internal/bridge/serve.go` (mount route in the bearer chain)
- Test: `internal/bridge/files_proxy_test.go`

- [ ] **Step 1: Write failing tests (readonly reject + size cap + stream-through)**

`internal/bridge/files_proxy_test.go`:

```go
package bridge

import (
	"bytes"
	"context"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"testing"
)

func multipartBody(t *testing.T, field, name string, data []byte) (*bytes.Buffer, string) {
	t.Helper()
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	fw, _ := w.CreateFormFile(field, name)
	fw.Write(data)
	w.Close()
	return &buf, w.FormDataContentType()
}

func TestPostFiles_RejectsReadonly(t *testing.T) {
	h := newFilesProxy("http://example.invalid", "key", "proj", 1<<20)
	body, ct := multipartBody(t, "file", "c.pdf", []byte("x"))
	req := httptest.NewRequest(http.MethodPost, "/files", body)
	req.Header.Set("Content-Type", ct)
	req = req.WithContext(context.WithValue(req.Context(), ctxKeyScope, "readonly"))
	rec := httptest.NewRecorder()

	h.PostFiles(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Errorf("readonly POST /files: got %d, want 403", rec.Code)
	}
}

func TestPostFiles_RejectsOversize(t *testing.T) {
	h := newFilesProxy("http://example.invalid", "key", "proj", 4) // 4-byte cap
	body, ct := multipartBody(t, "file", "c.pdf", []byte("way too big"))
	req := httptest.NewRequest(http.MethodPost, "/files", body)
	req.Header.Set("Content-Type", ct)
	req = req.WithContext(context.WithValue(req.Context(), ctxKeyScope, "full"))
	rec := httptest.NewRecorder()

	h.PostFiles(rec, req)

	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Errorf("oversize POST /files: got %d, want 413", rec.Code)
	}
}

func TestPostFiles_StreamsToUpstream(t *testing.T) {
	var got []byte
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got, _ = io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"upload_id":"u1","draft_id":"d1"}`))
	}))
	defer upstream.Close()

	h := newFilesProxy(upstream.URL, "key", "proj", 1<<20)
	body, ct := multipartBody(t, "file", "c.pdf", []byte("hello"))
	req := httptest.NewRequest(http.MethodPost, "/files", body)
	req.Header.Set("Content-Type", ct)
	req = req.WithContext(context.WithValue(req.Context(), ctxKeyScope, "full"))
	rec := httptest.NewRecorder()

	h.PostFiles(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("got %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	if len(got) == 0 {
		t.Error("upstream received no body — not streamed")
	}
}
```

- [ ] **Step 2: Run — verify it fails**

Run: `go test ./internal/bridge/ -run TestPostFiles -v`
Expected: FAIL — `newFilesProxy`/`PostFiles` undefined.

- [ ] **Step 3: Implement the proxy**

`internal/bridge/files_proxy.go`:

```go
package bridge

import (
	"io"
	"net/http"
	"time"
)

// filesProxy streams binary between MCP-only satellites and the Go file API.
// The bridge's JSON Client cannot carry multipart, so this is a raw proxy.
type filesProxy struct {
	serverURL        string
	apiKey           string
	defaultProjectID string
	maxBytes         int64
	client           *http.Client
}

func newFilesProxy(serverURL, apiKey, defaultProjectID string, maxBytes int64) *filesProxy {
	return &filesProxy{
		serverURL: serverURL, apiKey: apiKey, defaultProjectID: defaultProjectID, maxBytes: maxBytes,
		client: &http.Client{Timeout: 10 * time.Minute}, // longer than the JSON client (large uploads)
	}
}

// projectID resolves the target project: per-request header override, else the
// bridge's configured default (the raw routes do not pass through makeToolHandler's
// default-project injection, so the proxy resolves it itself).
func (p *filesProxy) projectID(r *http.Request) string {
	if h := r.Header.Get("X-KG-Project-Id"); h != "" {
		return h
	}
	return p.defaultProjectID
}

// PostFiles streams an uploaded file to Go POST /api/v1/projects/{projectId}/upload.
func (p *filesProxy) PostFiles(w http.ResponseWriter, r *http.Request) {
	if scope, _ := r.Context().Value(ctxKeyScope).(string); scope == "readonly" {
		http.Error(w, "forbidden: readonly credential cannot upload", http.StatusForbidden)
		return
	}
	// Hard cap at the edge — Go's maxMultipartMemory is only a parse buffer.
	r.Body = http.MaxBytesReader(w, r.Body, p.maxBytes)

	upstreamURL := p.serverURL + "/api/v1/projects/" + p.projectID(r) + "/upload"

	req, err := http.NewRequestWithContext(r.Context(), http.MethodPost, upstreamURL, r.Body)
	if err != nil {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	req.Header.Set("Content-Type", r.Header.Get("Content-Type")) // preserve multipart boundary
	req.Header.Set("Authorization", "Bearer "+p.apiKey)

	resp, err := p.client.Do(req)
	if err != nil {
		// MaxBytesReader trips here as a read error → 413.
		http.Error(w, "upload failed: "+err.Error(), http.StatusRequestEntityTooLarge)
		return
	}
	defer resp.Body.Close()

	w.Header().Set("Content-Type", resp.Header.Get("Content-Type"))
	w.WriteHeader(resp.StatusCode) // pass through 200/400/413/5xx verbatim
	_, _ = io.Copy(w, resp.Body)
}
```

> If `MaxBytesReader` returning 413 specifically (vs a generic 500) needs to be exact, assert the cap **before** streaming by checking `r.ContentLength > p.maxBytes` and returning 413 early; keep the `MaxBytesReader` as the hard backstop for chunked/unknown-length bodies. Add that early check to satisfy `TestPostFiles_RejectsOversize` deterministically:
>
> ```go
> if r.ContentLength > 0 && r.ContentLength > p.maxBytes {
> 	http.Error(w, "file too large", http.StatusRequestEntityTooLarge)
> 	return
> }
> ```
> (place it right after the readonly check)

- [ ] **Step 4: Mount the route in the bearer chain**

In `internal/bridge/serve.go`, after the `client` is built (`serve.go:56`) and before the catch-all `mux.Handle("/", …)` (`serve.go:143`), construct the proxy and mount it wrapped in `requireBearerV2` so `ctxKeyScope` is populated. **`chainMiddleware(h http.Handler, ms ...func(http.Handler) http.Handler) http.Handler` takes the handler FIRST** (`middleware.go:25`):

```go
	fproxy := newFilesProxy(cfg.ServerURL, cfg.APIKey, cfg.DefaultProjectID, maxUploadBytes)
	mux.Handle("POST /files", chainMiddleware(
		http.HandlerFunc(fproxy.PostFiles),
		requireBearerV2(token, readonlyToken, metrics.incAuthFailure),
	))
```

Define `const maxUploadBytes = 64 << 20` near the top of `serve.go` (≥ Go's per-file 50 MiB cap so legitimate files pass; the Go side still enforces its own 50 MiB/quota). This mounts on the **bridge serve mux** (`mux` in `serve.go`), separate from the Go API's `apiMux`. Go 1.22 method patterns (`"POST /files"`) work on `http.ServeMux`; the more-specific pattern wins over the `/` catch-all.

- [ ] **Step 5: Run — verify it passes**

Run: `go test ./internal/bridge/ -run TestPostFiles -v && go build ./...`
Expected: PASS + build clean.

- [ ] **Step 6: Commit**

```bash
git add internal/bridge/files_proxy.go internal/bridge/files_proxy_test.go internal/bridge/serve.go
git commit -m "feat(bridge): POST /files raw streaming upload proxy (readonly reject + size cap)"
```

---

## Task 6: `GET /files/{document_id}` raw download proxy

Resolve `document_id` → upload within the bridge's default project (the single-project bridge model = the project-access boundary), then proxy the Go download. Unknown/cross-project id → 404 (no `stored_path` leak).

**Files:**
- Modify: `internal/bridge/files_proxy.go` (add `GetFile` + a Go lookup)
- Modify: `internal/bridge/serve.go` (mount route)
- Test: `internal/bridge/files_proxy_test.go`

- [ ] **Step 1: Decide the resolution path (no new bridge DB access)**

The bridge has no DB handle — it reaches Go over HTTP. Resolve `document_id → uploadId` by calling a Go endpoint. Add a tiny Go endpoint that returns the `uploadId` for a `document_id` (knowledge_node_id), reusing `FindByDraftNodeID` + the canonical_document reverse lookup. Add to `internal/handler/ingest_status.go`:

```go
// ResolveUploadByDocument: GET /api/v1/projects/{projectId}/documents/{documentId}/upload
// → {"upload_id": "..."}; 404 if no file-backed upload for that document.
func (h *IngestStatusHandler) ResolveUploadByDocument(w http.ResponseWriter, r *http.Request) {
	projectID := r.PathValue("projectId")
	docID := r.PathValue("documentId")
	draftID, err := h.store.FindDraftByKnowledgeNode(r.Context(), projectID, docID) // Step 2
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	up, err := h.store.FindByDraftNodeID(r.Context(), projectID, draftID)
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"upload_id": up.ID})
}
```

- [ ] **Step 2: Add `FindDraftByKnowledgeNode` store query + test**

Add to `internal/store/uploaded_file.go`. (A `canonical_document.go` store exists, but keeping this read here gives the status handler a **single** store dependency — `h.store` already serves `FindByDraftNodeID`. The query targets the `canonical_document` table regardless.)

```go
// FindDraftByKnowledgeNode returns the draft_node_id whose canonical document
// produced the given knowledge node (document hub). ErrNoRows if none.
func (s *UploadedFileStore) FindDraftByKnowledgeNode(ctx context.Context, projectID, knowledgeNodeID string) (string, error) {
	const q = `SELECT draft_node_id FROM canonical_document
	           WHERE project_id = $1 AND knowledge_node_id = $2 AND deleted_at IS NULL`
	var draftID string
	if err := s.db.QueryRowContext(ctx, q, projectID, knowledgeNodeID).Scan(&draftID); err != nil {
		if err == sql.ErrNoRows {
			return "", fmt.Errorf("no canonical document for node %q", knowledgeNodeID)
		}
		return "", fmt.Errorf("find draft by knowledge node: %w", err)
	}
	return draftID, nil
}
```

Test in `internal/store/uploaded_file_test.go`:

```go
func TestUploadedFileStore_FindDraftByKnowledgeNode(t *testing.T) {
	db := newTestDB(t)
	store := NewUploadedFileStore(db)
	ctx := context.Background()
	projectID := seedProject(t, db)
	draftID := seedDraftNode(t, db, projectID)
	hubID := seedKnowledgeNode(t, db, projectID)
	seedCanonicalDocument(t, db, projectID, draftID, hubID) // existing helper / inline INSERT

	got, err := store.FindDraftByKnowledgeNode(ctx, projectID, hubID)
	if err != nil || got != draftID {
		t.Fatalf("got (%q,%v), want %q", got, err, draftID)
	}
}
```

Run: `go test ./internal/store/ -run TestUploadedFileStore_FindDraftByKnowledgeNode -v` → PASS after implementing.

- [ ] **Step 3: Register the resolve route + write the bridge `GetFile` failing test**

Add to the handler's `RegisterRoutes` (Task 2) so it lands on `apiMux`:

```go
	mux.HandleFunc("GET /api/v1/projects/{projectId}/documents/{documentId}/upload", h.ResolveUploadByDocument)
```

Bridge test (`files_proxy_test.go`): an upstream that serves the resolve endpoint then the download; assert bytes flow and unknown → 404.

```go
func TestGetFile_StreamsOriginal(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case bytes.HasSuffix([]byte(r.URL.Path), []byte("/upload")):
			w.Write([]byte(`{"upload_id":"u1"}`))
		case bytes.Contains([]byte(r.URL.Path), []byte("/uploads/u1/download")):
			w.Write([]byte("FILEBYTES"))
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer upstream.Close()

	h := newFilesProxy(upstream.URL, "key", "proj", 1<<20)
	req := httptest.NewRequest(http.MethodGet, "/files/doc-1", nil)
	req.SetPathValue("document_id", "doc-1")
	req = req.WithContext(context.WithValue(req.Context(), ctxKeyScope, "full"))
	rec := httptest.NewRecorder()

	h.GetFile(rec, req)

	if rec.Code != http.StatusOK || rec.Body.String() != "FILEBYTES" {
		t.Fatalf("got %d %q, want 200 FILEBYTES", rec.Code, rec.Body.String())
	}
}
```

- [ ] **Step 4: Implement `GetFile` (resolve then proxy download)**

Add to `internal/bridge/files_proxy.go`:

```go
// GetFile resolves document_id → upload_id (Go), then streams the original file.
func (p *filesProxy) GetFile(w http.ResponseWriter, r *http.Request) {
	docID := r.PathValue("document_id")
	projectID := p.projectID(r)

	// 1. Resolve document → upload via Go. 404 here = unknown/cross-project (no leak).
	resolveURL := p.serverURL + "/api/v1/projects/" + projectID + "/documents/" + docID + "/upload"
	uploadID, err := p.resolveUploadID(r.Context(), resolveURL)
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}

	// 2. Stream the download.
	dlURL := p.serverURL + "/api/v1/projects/" + projectID + "/uploads/" + uploadID + "/download"
	req, _ := http.NewRequestWithContext(r.Context(), http.MethodGet, dlURL, nil)
	req.Header.Set("Authorization", "Bearer "+p.apiKey)
	resp, err := p.client.Do(req)
	if err != nil {
		http.Error(w, "download failed", http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	for _, h := range []string{"Content-Type", "Content-Disposition", "Content-Length"} {
		if v := resp.Header.Get(h); v != "" {
			w.Header().Set(h, v)
		}
	}
	w.WriteHeader(resp.StatusCode)
	_, _ = io.Copy(w, resp.Body)
}

func (p *filesProxy) resolveUploadID(ctx context.Context, url string) (string, error) {
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	req.Header.Set("Authorization", "Bearer "+p.apiKey)
	resp, err := p.client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("resolve status %d", resp.StatusCode)
	}
	var out struct{ UploadID string `json:"upload_id"` }
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil || out.UploadID == "" {
		return "", fmt.Errorf("resolve decode")
	}
	return out.UploadID, nil
}
```

(Add `"context"`, `"encoding/json"`, `"fmt"` imports to `files_proxy.go`.)

- [ ] **Step 5: Mount the bridge route**

In `serve.go` next to `POST /files` (same `chainMiddleware(handler, mw)` shape, bridge mux):

```go
	mux.Handle("GET /files/{document_id}", chainMiddleware(
		http.HandlerFunc(fproxy.GetFile),
		requireBearerV2(token, readonlyToken, metrics.incAuthFailure),
	))
```

- [ ] **Step 6: Run — verify it passes**

Run: `go test ./internal/bridge/ -run 'TestGetFile|TestPostFiles' -v && go test ./internal/store/ -run TestUploadedFileStore -v && go build ./...`
Expected: PASS + build clean.

- [ ] **Step 7: Commit**

```bash
git add internal/bridge/files_proxy.go internal/bridge/files_proxy_test.go internal/bridge/serve.go internal/handler/ingest_status.go internal/store/uploaded_file.go internal/store/uploaded_file_test.go cmd/kg-server/main.go
git commit -m "feat(bridge): GET /files/{document_id} download proxy + document→upload resolution"
```

---

## Task 7: `download_url` on `kg_get_document`

**Files:**
- Modify: `internal/handler/document.go` (document-meta response)
- Test: `internal/handler/document_test.go`

- [ ] **Step 1: Write the failing test**

In `internal/handler/document_test.go`, add a case asserting that a document-meta response for a node WITH a non-empty `stored_path` includes `download_url = "/files/{id}"`, and a node WITHOUT one omits it. Mirror the existing document-meta test setup in that file:

```go
func TestGetDocumentMeta_DownloadURL(t *testing.T) {
	// Arrange: a document hub node whose properties include a non-empty stored_path.
	// (mirror the existing meta test's node seeding)
	respWithFile := getMetaForNodeWithStoredPath(t, "uploads/c.pdf", "node-1")
	if respWithFile["download_url"] != "/files/node-1" {
		t.Errorf("download_url: got %v, want /files/node-1", respWithFile["download_url"])
	}
	respNoFile := getMetaForNodeWithStoredPath(t, "", "node-2")
	if _, present := respNoFile["download_url"]; present {
		t.Error("download_url must be omitted when stored_path is empty")
	}
}
```

(Replace `getMetaForNodeWithStoredPath` with the actual call path used by the existing meta tests; the assertion is the contract.)

- [ ] **Step 2: Run — verify it fails**

Run: `go test ./internal/handler/ -run TestGetDocumentMeta_DownloadURL -v`
Expected: FAIL — `download_url` not present.

- [ ] **Step 3: Add `download_url` to the meta builder**

In `internal/handler/document.go` `GetDocumentMeta`, the response is currently built **inline** in the final `writeJSON` call (`document.go:~138`):

```go
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"node_id":       nodeID,
		"title":         node.Title,
		"source_url":    strOrEmpty(props["source_url"]),
		"section_count": props["section_count"],
	})
```

Refactor it to a named map so `download_url` can be added conditionally — **without** exposing the raw `stored_path` (the existing `strOrEmpty` helper + `props`/`nodeID` vars are already in scope):

```go
	meta := map[string]interface{}{
		"node_id":       nodeID,
		"title":         node.Title,
		"source_url":    strOrEmpty(props["source_url"]),
		"section_count": props["section_count"],
	}
	// IMP-009 FR-4: opaque download route when a stored file exists.
	// stored_path itself stays unexposed (D2-A); only the bridge route is emitted.
	if strOrEmpty(props["stored_path"]) != "" {
		meta["download_url"] = "/files/" + nodeID
	}
	writeJSON(w, http.StatusOK, meta)
```

- [ ] **Step 4: Run — verify it passes**

Run: `go test ./internal/handler/ -run TestGetDocumentMeta_DownloadURL -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/handler/document.go internal/handler/document_test.go
git commit -m "feat(handler): add opaque download_url to kg_get_document (no stored_path leak)"
```

---

## Task 8: Tool-count invariant + full verification

**Files:**
- Modify: `internal/bridge/e2e_tools_test.go` (if it hardcodes a count)
- Test: full suite

- [ ] **Step 1: Verify the invariant test still balances**

Run: `go test ./internal/bridge/ -run 'TestAllToolSchemasMatchRoutes|TestAllToolSchemasRegistered' -v`
Expected: PASS. Count math: before = **36 routed** (`ListToolNames`, `client.go` toolRoutes) **+ 2 local** = 38. After = **37 routed** (+`kg_ingest_status`) **+ 3 local** (+`kg_request_file_upload`) = **40**, and `len(schemas)==len(ListToolNames())+len(localToolNames)` holds (`e2e_tools_test.go:805`). If it fails, the cause is a tool registered on zero or two dispatch sides — fix registration (each new tool on exactly one side: `kg_ingest_status`→`toolRoutes`, `kg_request_file_upload`→`localToolNames`), do **not** weaken the assertion.

- [ ] **Step 2: Run the full bridge + handler + store suites**

Run: `go test ./internal/bridge/... ./internal/handler/... ./internal/store/... -count=1`
Expected: PASS.

- [ ] **Step 3: Lint + vet + build**

Run: `make lint && go vet ./... && go build ./...`
Expected: clean.

- [ ] **Step 4: Integration smoke (DB-backed, the feature's intent)**

With the dockerized deps up (`docker compose up -d postgres redis`), run an end-to-end check that exercises the real correlation read:
1. `POST /api/v1/projects/{p}/upload` a small markdown file → capture `upload_id`.
2. Poll `GET …/uploads/{upload_id}/ingest-status` until `done` → capture `document_id`.
3. `GET …/documents/{document_id}/upload` → returns the same `upload_id`.
4. `kg_get_document(document_id)` → response has `download_url`.

Document the commands + observed output in the PR description (verification-before-completion).

- [ ] **Step 5: Final commit**

```bash
git add internal/bridge/e2e_tools_test.go
git commit -m "test(bridge): assert tool-count invariant holds at 40 after IMP-009 tools"
```

---

## Self-Review notes (done by author)

- **Spec coverage:** FR-1 (Task 4), FR-2 (Task 5), FR-3 (Tasks 2+3), FR-4 (Task 7), FR-5 (Task 6), FR-6 (Task 7 via download_url + reused stored_path), §3.5 security controls (readonly reject Task 5, size cap Task 5, project-scoped 404 Task 6). BR-006 bare `failed` (Task 2 derivation). Count invariant (Tasks 3/4/8).
- **Known mirror-points** (engineer must read the referenced file to copy exact local helpers): store-test DB helpers (`newTestDB`, `seed*`), the document-meta test harness, `chainMiddleware` wrapping signature, and `toolRoutes` path-param substitution for `upload_id`→`{uploadId}`. These are existing patterns, not new design.
- **Residual (carry to PR):** client-side IMP-008 confirm classification for `kg_request_file_upload` is a LAAM concern (the bridge models it as local-dispatch + readonly-blocked); typed failure reason for `kg_ingest_status` is deferred (BR-006).
