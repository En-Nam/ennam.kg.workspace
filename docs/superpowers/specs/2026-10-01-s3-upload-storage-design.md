# DAAB: S3 storage for uploaded files — Design

Date: 2026-10-01 · Status: draft for review · Path: architectural

## 1. Problem and goal

Uploaded files (the "analyse this file" flow) are written to the local filesystem of the
kg-server container under `KG_UPLOAD_DIR` (`/app/data/uploads`). The Python worker reads the
same path from a shared Docker volume. On prod (separate containers, ephemeral disk) this breaks:

- the worker cannot see files the server received unless a shared volume (EFS) is mounted,
- files are lost on redeploy.

**Goal:** store new uploads in S3, keep kg-server as the only component that talks to S3, and
leave local-disk storage as the default for dev.

**Success criteria**

1. With `USE_S3=1`, an upload lands at `s3://<bucket>/<AWS_MAIN_FOLDER>/<project>/<upload>/<file>` and
   is analysed by the worker without any shared volume.
2. Download via the existing API returns the file; unknown file → 404.
3. Deleting an upload removes the object.
4. With `USE_S3` unset, behaviour is unchanged.
5. The worker and indexer need no AWS credentials.

## 2. Out of scope

- Migrating existing files (≈780 MB local) or the 267 `uploaded_files` rows already synced to prod.
  Those rows have no object on prod; downloading them returns 404. Accepted by the owner.
- Presigned URLs (downloads keep going through the API so project authorisation is enforced).
- S3 access from the worker/indexer, or reading both S3 and disk side by side.
- Any change to the `uploaded_files` schema or to the format of `stored_path`.

## 3. Current state (verified in code)

| Concern | Where |
|---|---|
| Write | `ennam.kg.go/internal/service/file_upload.go` `handleOneFile` (`MkdirAll`/`OpenFile`/`io.Copy`, size capped by `LimitReader`) |
| Cleanup on failure | same function, `os.Remove(absPath)` on DB/ingest errors |
| Delete | `FileUploadService.DeleteUpload` → `os.Remove` |
| Download | `handler/ingest_upload.go` `Download` → `http.ServeFile(ResolveStoredPath)`; bridge `files_proxy.go` reaches it via the Go API |
| Worker read | `ennam.kg.python/src/ennam_kg/worker.py` `handle_extract_upload`: `Path(settings.kg_upload_dir) / stored_path` |
| Composition | `cmd/kg-server/main.go` reads `KG_UPLOAD_DIR`, builds `NewFileUploadService` |

`stored_path` in DB and in the queue message is a **relative** path `<project>/<upload>/<file>`.
`go.mod` already depends on `aws-sdk-go-v2` (CloudWatch only); no S3 module and no boto in Python.

## 4. Design

### 4.1 Storage abstraction (Go, new package `internal/storage`)

```go
type ObjectStorage interface {
    Put(ctx context.Context, key string, r io.Reader, contentType string) error
    Open(ctx context.Context, key string) (io.ReadCloser, error) // ErrNotFound when absent
    Delete(ctx context.Context, key string) error               // absent key is not an error
}
```

- **`LocalStorage`** — current behaviour rooted at `KG_UPLOAD_DIR`. Rejects keys that escape the root.
- **`S3Storage`** — `aws-sdk-go-v2/service/s3`, uploads through `manager.Uploader` (multipart for
  large files). Real key = `AWS_MAIN_FOLDER + "/" + key`. No ACL is set; objects stay private.
  The S3 calls sit behind a small client interface so tests use a fake. `NoSuchKey` maps to `ErrNotFound`.
- Credentials: if `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are both set, use them; if both
  are empty use the default credential chain (IAM role on ECS). Exactly one set is a startup error.

### 4.2 Selection and configuration (`main.go`)

`USE_S3` of `1`/`true` (case-insensitive) selects `S3Storage`; `""`/`0`/`false` select `LocalStorage`; any other value is a startup error (a typo must not silently keep uploads on disk). With S3 on, a missing
`AWS_STORAGE_BUCKET_NAME` or `AWS_S3_REGION_NAME` is a fatal startup error (fail loud, never fall
back to disk silently).

| Variable | Value | Notes |
|---|---|---|
| `USE_S3` | `1` | unset/`0` = local disk |
| `AWS_STORAGE_BUCKET_NAME` | `devshared-ap-southeast-1-public-storage` | required with `USE_S3=1` |
| `AWS_MAIN_FOLDER` | `media/daab` | key prefix; trailing slash trimmed |
| `AWS_S3_REGION_NAME` | `ap-southeast-1` | required with `USE_S3=1` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | secrets | empty → IAM role |

These are needed on **kg-server only**. `KG_UPLOAD_DIR` stays (local mode on the server; legacy
fallback on the worker). Documented in `.env.release.example` and `docker-compose.release.yml`
(kg-server); added to the owner's `envfiles/kg-server.env` with the secrets left blank.

### 4.3 `FileUploadService`

Takes an `ObjectStorage` instead of `storageRoot`.

- Save: `Put(key = relPath, …)` replaces mkdir/open/copy. The size cap (`LimitReader`, per-file limit)
  is kept; oversize → `Delete` and `ErrUploadTooLarge`, as today.
- Order is unchanged: store the object first, then create the DB record. Any later failure calls `Delete`.
- Delete: soft-delete the record, then `Delete(key)`; a storage error is logged, not returned (as today).
- `ResolveStoredPath` is removed; callers use `Open`.
- `stored_path` stays `<project>/<upload>/<file>` — the S3 prefix is added only inside `S3Storage`,
  so changing `AWS_MAIN_FOLDER` later never touches the DB.

### 4.4 Download handler

`Download` calls `GetUpload` then `Open(StoredPath)`, sets `Content-Type` (stored mime type, else `application/octet-stream`) and streams; it does not set `Content-Disposition`, matching the previous `http.ServeFile` behaviour. `ErrNotFound` → 404. Other errors → 500 with a generic body (S3 detail goes to the log, never to the client). Range requests (previously via `http.ServeFile`) are not supported; no current client relies on them.

### 4.5 Python worker

- `KGClient.download_upload(project_id, upload_id, dest_path)`: `GET /api/v1/projects/{id}/uploads/{uploadId}/download`
  with the existing `GO_API_KEY`, streamed in chunks to `dest_path`; non-2xx raises `KGClientError`.
- `handle_extract_upload`: when `upload_id` is present, download into a temp directory, run the
  existing extraction on that `Path`, and remove the temp file in `finally`. When `upload_id` is
  missing (messages already queued before deploy) fall back to the old `KG_UPLOAD_DIR` read.
- Extraction functions are untouched.

### 4.6 Error handling

| Failure | Result |
|---|---|
| `Put` fails | upload fails, no DB record |
| DB create/ingest fails after `Put` | object deleted, error returned |
| object missing on download | 404 |
| bad credentials / missing permission | 500, logged with the S3 error code (no key material); first upload surfaces it |
| S3 on but bucket/region unset, or only one credential set | server refuses to start |

### 4.7 IAM and bucket (owner action)

Role/user for kg-server needs `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` on
`arn:aws:s3:::devshared-ap-southeast-1-public-storage/media/daab/*`. The bucket name contains
"public": confirm Block Public Access (or a deny policy) covers the `media/daab/` prefix so uploaded
documents cannot be read without going through DAAB.

## 5. Testing (TDD, no real AWS in automated tests)

- `LocalStorage`: round trip; missing → `ErrNotFound`; delete of absent key ok; `..` traversal rejected.
- `S3Storage` with a fake client: prefix applied, no ACL sent, `NoSuchKey` → `ErrNotFound`, other errors propagated.
- Config: `USE_S3=1` without bucket/region fails; unset selects local; `1`/`true` accepted; half-set credentials fail.
- `FileUploadService`/handler with a fake storage: `Put` failure creates no record; record failure triggers `Delete`;
  delete upload calls `Delete`; download streams content and maps `ErrNotFound` to 404.
- Python: `download_upload` streams and raises on 404; worker uses and removes the temp file (also on
  extraction error); worker falls back to disk when `upload_id` is absent.
- Manual, once, only if the owner supplies keys in a local env: upload → object appears under
  `media/daab/…` → download → delete.

## 6. Rollout

1. Merge and release images (server and worker).
2. Add the variables to the kg-server config and attach the IAM permission.
3. Redeploy kg-server, then the worker (the worker works against old or new server, thanks to the fallback).
4. Smoke test: upload a small PDF, confirm extraction completes and the file downloads.

Rollback: unset `USE_S3` (new uploads go back to disk). Objects already in S3 are not read in that mode.

## 7. Risks

- kg-server is the single S3 client; a wrong role breaks all uploads and downloads until fixed. Permission
  errors only appear on first use, not at startup.
- Files now make one extra hop (S3 → server → worker). Acceptable for the current per-file size cap.
- Pre-existing prod rows (267) point at files that do not exist in S3 (404), by decision.
