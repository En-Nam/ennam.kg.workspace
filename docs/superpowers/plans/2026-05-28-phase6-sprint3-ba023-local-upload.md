# Phase 6 Sprint 3: BA-023 Local Upload + File Processing — Implementation Plan

> **Parent:** [`2026-05-28-phase6-master.md`](2026-05-28-phase6-master.md) · **Requires:** Sprint 1 merged (Sprint 2 UI optional for CLI demo)

**Goal:** Upload markdown/PDF/DOCX/XLSX/CSV → stored file → draft node → enables `scripts/ingest-md-via-api.sh`.

---

## Migration 049 — uploaded_files

**File:** `db/migrations/000049_create_uploaded_files.up.sql`

Columns per BA-022/023: id, project_id, draft_node_id, original_filename, stored_path, mime_type, file_size_bytes, content_extracted, uploaded_by, created_at, deleted_at (soft delete).

Index on `(project_id)` for quota SUM.

---

## Go — Upload endpoints (FR-005)

**Files:**
- Create: `internal/handler/ingest_upload.go`
- Create: `internal/service/file_upload.go`
- Create: `internal/store/uploaded_file.go`

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/v1/projects/{id}/upload` | multipart, max 10 files, 50MB each |
| POST | `/api/v1/projects/{id}/ingest/upload` | **alias** — same handler (fixes existing script) |
| GET | `/api/v1/projects/{id}/uploads` | paginated list |
| GET | `/api/v1/projects/{id}/uploads/{uploadId}/download` | local: `http.ServeFile`; prod: pre-signed S3 |
| DELETE | `/api/v1/projects/{id}/uploads/{uploadId}` | soft-delete + remove file |

**Storage:** Dev = `./data/uploads/{project_id}/{uuid}/{filename}`. Docker volume mount in compose.

**Flow:**
1. Validate size vs `ingestion.max_upload_size_bytes`
2. Check quota 10GB (NFR-194) → 413 if exceeded
3. Store file, create draft (source_type=`local_upload`, source_id=upload UUID)
4. Extract text synchronously for md/txt/json/csv; defer pdf/docx/xlsx to Python queue message `extract_upload`

**Response:** `{ "draft_id": "...", "upload_id": "...", "status": "pending" }`

---

## Python — File adapter

**Files:** `src/ennam_kg/ingestion/adapters/files.py`

| Format | Library | Output content_format |
|--------|---------|----------------------|
| .md, .txt | plain read | markdown / plain_text |
| .json | json.loads + pretty | json |
| .csv | csv module | csv |
| .pdf | pypdf or pdfplumber | plain_text |
| .docx | python-docx | plain_text |
| .xlsx | openpyxl | json (sheet rows) |

Update draft via Go API PATCH or internal upsert endpoint (add `PUT /draft-nodes/{id}/content` if needed for worker).

---

## NextJS — Upload dropzone

**File:** `src/components/sources/upload-dropzone.tsx`

Drag-and-drop → `POST /api/bff/projects/{id}/ingest/upload` with progress bar.

---

## Fix existing script

**File:** `scripts/ingest-md-via-api.sh` — no path change needed once alias exists. Verify:

```bash
./scripts/ingest-md-via-api.sh 2026-05-28-cang-dinh-an-deal-report.md --process
```

---

## Sprint 3 Done Checklist

- [ ] Upload .md creates draft visible in GET draft-nodes
- [ ] Quota + size limits enforced
- [ ] PDF/DOCX extraction tested with sample files
- [ ] Script E2E passes against local Docker stack

**Next:** Sprint 4 — Jira + GDrive
