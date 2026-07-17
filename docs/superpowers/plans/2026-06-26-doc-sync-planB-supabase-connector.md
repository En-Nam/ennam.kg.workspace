# Doc-Sync Plan B — Supabase Storage Connector (reuse source_connections) Implementation Plan

> **⚠️ SUPERSEDED — 2026-07-15.** Never started. Replaced by `docs/superpowers/plans/2026-07-15-daab-doc-sync-planA.md` (spec `…/specs/2026-07-15-daab-doc-sync-planA-aaaa-endpoint-design.md`). Reason: verified AAAA's document **metadata** lives in AAAA's own Postgres (`am_ai_db`), NOT on Supabase (only the Storage bucket is) — so DAAB pulls metadata via an **AAAA integrations endpoint** (Option A), not a Supabase VIEW/connector. Migration number here (000071) is also stale (latest is 000075 → new is 000076). Future shared-Supabase path: Serena `backlog/daab-doc-sync-planB-future`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Thêm `source_type='supabase'` vào hệ **`source_connections` SẴN CÓ**: admin connect (nhập scoped read-only key, lưu mã hoá) → nút **Sync** (implement route 501 sẵn có) → worker kéo PDF `documents/` từ Supabase Storage → OCR (Plan A) → draft-node → graph + back-link. Idempotent (etag), no-persist, vào corpus-project khoá admin.

**Architecture:** **TÁI DÙNG `source_connections`** (migration 000048: model/store/handler CRUD + routes `/connections` + `/connections/{id}/sync` hiện **501**). Lưu config (url/bucket/prefix) trong `config JSONB` + key ở cột mới `credential_encrypted`. Implement Sync 501 cho supabase → decrypt + enqueue `ennam:kg_generation` (queue ingestion sẵn có; `handle_message` đã dispatch theo `type`). Worker pull qua **`StorageClient` interface** (mock được → unit-test ngay; E2E gated khi có key). KGClient ở package `ennam_kg_indexer` → call Go MỚI bằng **httpx-to-Go** trong worker. OQ-1=Cách B scoped key; broker = thêm 1 impl interface sau.

**Tech Stack:** Go (crypto AES-256-GCM `internal/crypto/aes.go`, redis publisher, net/http), Python worker (httpx → Supabase Storage REST + Go REST), Next.js (ConnectionBar + dialog + TanStack Query). PostgreSQL.

## Global Constraints
- Spec: `docs/superpowers/specs/2026-06-26-daab-doc-sync-design.md`. **Phụ thuộc Plan A** (`extract_file_text -> (str,str)` GIỮ 2-tuple + `extract_structured_fields_for_file -> dict`).
- **Reuse, KHÔNG dựng song song:** source_connections (ALTER), Sync route 501 (implement), UI hook `useSourceConnections` + `ConnectionBar`.
- **Credential:** scoped read-only key (KHÔNG service_role), mã hoá `crypto.Encrypt`, lưu `source_connections.credential_encrypted`, admin-only. RLS hardening = follow-up.
- **No-persist:** temp `/tmp` → OCR → **xoá (try/finally)** + orphan-sweep; KHÔNG `KG_UPLOAD_DIR`.
- **Idempotency:** `supabase_synced_objects` key `(connection_id, object_id)` + **etag**; etag đổi → re-sync; row lúc draft-creation.
- **Tenancy:** corpus-project khoá admin (project của connection); `aaaa_user_id` (path) = metadata. KHÔNG general-rollout (gated D3 RBAC).
- **Scope:** chỉ prefix `documents/`; loại `users/`,`matches/`,edge.
- **Queue:** `ennam:kg_generation` (Go `queue.KGGenerationQueueName`; Python `redis_kg_generation_queue`; cả 4 consumer chạy `handle_message` → dispatch theo `type`).
- **KGClient ở `ennam_kg_indexer.kg_client.client`** (worker.py:15) — call mới bằng httpx-to-Go, KHÔNG sửa package indexer.
- Migration `.up`+`.down`; latest=000070 → **000071**. Nested git `git -C`. Test: Go `make test`, Python `uv run pytest` (mock StorageClient + httpx). E2E gated.

---

## File Structure
**Go (`ennam.kg.go`) — extend source_connections:**
- `db/migrations/000071_supabase_source_connection.{up,down}.sql` — ALTER source_type CHECK +`supabase`; ADD `source_connections.credential_encrypted BYTEA`; CREATE `supabase_synced_objects`.
- `internal/models/source_connection.go` (modify) — `CredentialEncrypted []byte`; new `SupabaseSyncedObject`.
- `internal/store/source_connection.go` (modify) — read/write credential_encrypted; registry CRUD.
- `internal/service/source_connection.go` (modify) — encrypt/decrypt credential; validate supabase config.
- `internal/handler/source_connection.go` (modify) — implement `Sync` (501→supabase); internal worker endpoints (get-conn-with-key, create draft-node, registry upsert).
- `internal/handler/draft_node.go` (modify) — add `POST .../draft-nodes` (create draft for worker; reuse draft service).
- `internal/queue/supabase_sync.go` (create) — `SupabaseSyncMessage` + publish to `ennam:kg_generation`.
- `cmd/kg-server/main.go` (modify) — wire publisher + encKey into source_connection handler.

**Python (`ennam.kg.python`):**
- `src/ennam_kg/ingestion/storage/__init__.py`, `client.py` (create) — `StorageClient` Protocol + `SupabaseRestStorageClient` + `StorageObject`.
- `src/ennam_kg/ingestion/supabase_sync_client.py` (create) — httpx helpers to new Go endpoints.
- `src/ennam_kg/worker.py` (modify) — `handle_supabase_sync` + dispatch + orphan-sweep.

**Next (`ennam.kg.next`):**
- `src/components/sources/connection-bar.tsx` (modify) — Supabase card (reuse connections data).
- `src/components/sources/supabase-connect-dialog.tsx` (create) — connect + sync.
- `src/hooks/use-supabase-connection.ts` (create) — connect/sync mutations (reuse `useSourceConnections` for status).

---

## Task 1: Migration + model (extend source_connections)

**Files:** Create migration up/down; modify `internal/models/source_connection.go`. Test: migration applies + model scans.

- [ ] **Step 1: Migration up** (`db/migrations/000071_supabase_source_connection.up.sql`)
```sql
-- Add 'supabase' to source_connections.source_type (verified CHECK in migration 000048)
ALTER TABLE source_connections DROP CONSTRAINT IF EXISTS source_connections_source_type_check;
ALTER TABLE source_connections ADD CONSTRAINT source_connections_source_type_check
    CHECK (source_type IN ('jira','google_drive','local_upload','satellite_api','supabase'));
-- Encrypted scoped read key (nullable — only supabase uses it)
ALTER TABLE source_connections ADD COLUMN credential_encrypted BYTEA;
-- (existing config JSONB holds supabase_url / bucket / prefix)

CREATE TABLE supabase_synced_objects (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    connection_id UUID NOT NULL REFERENCES source_connections(id) ON DELETE CASCADE,
    object_id     VARCHAR(255) NOT NULL,            -- storage.objects.id
    object_path   VARCHAR(1024) NOT NULL,
    etag          VARCHAR(255),                     -- change-key (NOT size)
    state         VARCHAR(50) NOT NULL DEFAULT 'processing',
    node_id       UUID REFERENCES knowledge_nodes(id) ON DELETE SET NULL,
    aaaa_user_id  UUID,
    failure_reason TEXT,
    synced_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_supa_obj_state CHECK (state IN ('processing','drafted','synced','failed'))
);
CREATE UNIQUE INDEX idx_supa_obj_unique ON supabase_synced_objects(connection_id, object_id);
CREATE INDEX idx_supa_obj_state ON supabase_synced_objects(state);
```
`.down.sql`:
```sql
DROP TABLE IF EXISTS supabase_synced_objects;
ALTER TABLE source_connections DROP COLUMN IF EXISTS credential_encrypted;
ALTER TABLE source_connections DROP CONSTRAINT IF EXISTS source_connections_source_type_check;
ALTER TABLE source_connections ADD CONSTRAINT source_connections_source_type_check
    CHECK (source_type IN ('jira','google_drive','local_upload','satellite_api'));
```
> Verify `DraftSourceType` enum (Go) cũng cho 'supabase' — đọc `models/source_connection.go` (`SourceType DraftSourceType`); thêm hằng `DraftSourceTypeSupabase = "supabase"` nếu enum được validate ở app layer.

- [ ] **Step 2: Model** — `internal/models/source_connection.go`: thêm vào struct `SourceConnection` (sau `WebhookSecret`):
```go
	CredentialEncrypted []byte `json:"-" db:"credential_encrypted"`  // AES-256-GCM(scoped key), supabase only
```
Thêm struct registry:
```go
type SupabaseSyncedObject struct {
	ID, ConnectionID, ObjectID, ObjectPath, Etag, State string
	NodeID, AAAAUserID, FailureReason *string
}
```
+ hằng `DraftSourceTypeSupabase DraftSourceType = "supabase"`.

- [ ] **Step 3: Apply + verify**
```bash
cd ennam.kg.go && make db-migrate && make db-migrate-version   # → 000071
go build ./...
```
Expected: version 000071, build clean.

- [ ] **Step 4: Commit**
```bash
git -C ennam.kg.go add db/migrations/000071_* internal/models/source_connection.go
git -C ennam.kg.go commit -m "feat(doc-sync): add 'supabase' source_type + credential column + synced_objects"
```

---

## Task 2: Go — credential encrypt/decrypt + registry store

**Files:** Modify `internal/store/source_connection.go` (scan/insert credential_encrypted; registry CRUD), `internal/service/source_connection.go` (encrypt on create, decrypt accessor). Test: `internal/service/source_connection_test.go`.

**Interfaces:**
- Produces: `(*SourceConnectionService) DecryptCredential(conn *models.SourceConnection) (string, error)`; on `Create`, nếu `SourceType=="supabase"` và req có `Credential` → `crypto.Encrypt` vào `conn.CredentialEncrypted`. Store: `UpsertSyncedObject(ctx, SupabaseSyncedObject) error`, `ListSyncedObjectEtags(ctx, connID) (map[string]string, error)` (object_id→etag), `GetWithCredential(ctx, connID) (*models.SourceConnection, error)`.

- [ ] **Step 1: Store** — thêm `credential_encrypted` vào INSERT/UPDATE + scan của source_connection store (đọc cột list hiện tại; append `credential_encrypted`). Thêm registry CRUD (`supabase_synced_objects`): `UpsertSyncedObject` (ON CONFLICT (connection_id,object_id) DO UPDATE etag/state/node_id), `ListSyncedObjectEtags`.

- [ ] **Step 2: Write failing test** (`service/source_connection_test.go`):
```go
func TestSourceConnection_SupabaseCredentialEncrypted(t *testing.T) {
    key := make([]byte, 32)
    svc := NewSourceConnectionService(fakeStore(), key)
    conn := &models.SourceConnection{ProjectID: "p1", SourceType: "supabase",
        DisplayName: "M&A corpus", Config: []byte(`{"supabase_url":"https://x.supabase.co","bucket":"documents","prefix":"documents/"}`)}
    if err := svc.CreateWithCredential(context.Background(), conn, "sb_secret_abc"); err != nil { t.Fatal(err) }
    if string(conn.CredentialEncrypted) == "sb_secret_abc" { t.Fatal("plaintext stored!") }
    got, _ := svc.DecryptCredential(conn)
    if got != "sb_secret_abc" { t.Errorf("decrypt mismatch: %q", got) }
}
```

- [ ] **Step 3: Run → fail.** `cd ennam.kg.go && go test ./internal/service/ -run SupabaseCredential -v`

- [ ] **Step 4: Implement service** (mirror `service/datasource.go:64-94` crypto usage):
```go
func (s *SourceConnectionService) CreateWithCredential(ctx context.Context, conn *models.SourceConnection, credential string) error {
    if conn.SourceType == models.DraftSourceTypeSupabase && credential != "" {
        enc, err := crypto.Encrypt([]byte(credential), s.encKey)
        if err != nil { return fmt.Errorf("encrypt supabase credential: %w", err) }
        conn.CredentialEncrypted = enc
    }
    return s.Create(ctx, conn)
}
func (s *SourceConnectionService) DecryptCredential(conn *models.SourceConnection) (string, error) {
    if len(conn.CredentialEncrypted) == 0 { return "", fmt.Errorf("no credential") }
    pt, err := crypto.Decrypt(conn.CredentialEncrypted, s.encKey)
    return string(pt), err
}
```
> Service cần `encKey []byte` (inject từ `KG_ENCRYPTION_KEY` ở main.go — mirror DataSourceService). Nếu `SourceConnectionService` chưa có encKey → thêm vào constructor.

- [ ] **Step 5: Run → pass.** Commit:
```bash
git -C ennam.kg.go add internal/store/source_connection.go internal/service/source_connection.go internal/service/source_connection_test.go
git -C ennam.kg.go commit -m "feat(doc-sync): encrypt supabase credential + synced-object registry store"
```

---

## Task 3: Go — implement Sync (501→), queue, create-draft endpoint, wiring

**Files:** Modify `internal/handler/source_connection.go` (Sync + Create wire credential), `internal/handler/draft_node.go` (POST create), `internal/queue/supabase_sync.go` (create), `cmd/kg-server/main.go`. Test: handler test.

**Interfaces:**
- `SupabaseSyncMessage{Type:"supabase_sync", ConnectionID, ProjectID, CreatedAt}` published to `ennam:kg_generation` (reuse `queue.KGGenerationQueueName`).
- `POST /api/v1/projects/{projectId}/draft-nodes` → create pending draft `{title, source_type, content_raw, content_format, properties}` → `{id}`.
- Internal: `GET /api/v1/projects/{projectId}/connections/{connId}/credential` (returns config + `credential_encrypted_b64`; admin/internal-key only) for worker; `POST .../connections/{connId}/synced-objects` (registry upsert).

- [ ] **Step 1: Queue message** (`internal/queue/supabase_sync.go`) — reuse redis publisher to `KGGenerationQueueName`:
```go
type SupabaseSyncMessage struct {
    Type string `json:"type"`; ConnectionID string `json:"connection_id"`
    ProjectID string `json:"project_id"`; CreatedAt time.Time `json:"created_at"`
}
// Add PublishSupabaseSync(ctx, msg) to the ingestion publisher: json.Marshal → lpush to KGGenerationQueueName.
```

- [ ] **Step 2: Implement Sync** — `source_connection.go` `Sync` (đang `errorResponse(501)`): chỉ supabase, admin role, enqueue.
```go
func (h *SourceConnectionHandler) Sync(w http.ResponseWriter, r *http.Request) {
    pid := r.PathValue("projectId"); connID := r.PathValue("connId")
    if !requireProjectRole(w, r, pid, models.ProjectMemberRoleAdmin, h.roleResolver) { return }
    conn, err := h.svc.Get(r.Context(), connID)
    if err != nil || conn == nil { errorResponse(w, http.StatusNotFound, "connection not found"); return }
    if conn.SourceType != models.DraftSourceTypeSupabase {
        errorResponse(w, http.StatusNotImplemented, "sync only implemented for supabase"); return
    }
    if err := h.publisher.PublishSupabaseSync(r.Context(), queue.SupabaseSyncMessage{
        Type: "supabase_sync", ConnectionID: connID, ProjectID: pid, CreatedAt: time.Now(),
    }); err != nil { errorResponse(w, http.StatusInternalServerError, "enqueue failed"); return }
    writeJSON(w, http.StatusAccepted, map[string]string{"status": "enqueued"})
}
```
+ `Create`: đọc `credential` từ request body (supabase) → `svc.CreateWithCredential`. + internal endpoints (credential fetch + synced-objects upsert) — admin/internal-key guard.

- [ ] **Step 3: Create draft-node endpoint** — `draft_node.go`: `POST /api/v1/projects/{projectId}/draft-nodes` → tạo pending draft với content (reuse draft-create service mà upload dùng; đọc service để gọi đúng). Trả `{id}`.

- [ ] **Step 4: Wire main.go** — inject `publisher` + `encKey` vào `SourceConnectionHandler`/service (đọc chỗ construct hiện tại).

- [ ] **Step 5: Test** (handler): Sync non-supabase → 501; supabase + non-admin → 403; supabase admin → 202 + enqueued; Create supabase lưu credential mã hoá. `go test ./internal/handler/ -run "SourceConnection|Supabase|DraftNodeCreate" -v && go build ./...`

- [ ] **Step 6: Commit**
```bash
git -C ennam.kg.go add internal/handler/source_connection.go internal/handler/draft_node.go internal/queue/supabase_sync.go cmd/kg-server/main.go internal/handler/source_connection_test.go
git -C ennam.kg.go commit -m "feat(doc-sync): implement supabase Sync (501→) + queue + create-draft endpoint"
```

---

## Task 4: Python — StorageClient interface + Supabase REST impl

**Files:** Create `ingestion/storage/__init__.py`, `client.py`. Test: `tests/ingestion/test_storage_client.py`.

**Interfaces:**
- `StorageObject(id:str, path:str, etag:str, size:int)`; `StorageClient` Protocol: `list_objects(prefix)->list[StorageObject]`, `download(path, dest: Path)->None`; `SupabaseRestStorageClient(base_url, key, bucket)`.

- [ ] **Step 1: Write failing test** (mock httpx via respx — no real Supabase):
```python
import respx, httpx
from pathlib import Path
from ennam_kg.ingestion.storage.client import SupabaseRestStorageClient, StorageObject

@respx.mock
def test_list_objects_recursive():
    base="https://x.supabase.co"
    respx.post(f"{base}/storage/v1/object/list/documents").mock(side_effect=[
        httpx.Response(200, json=[{"name":"u1","id":None,"metadata":None}]),       # folder
        httpx.Response(200, json=[{"name":"f.pdf","id":"oid1","metadata":{"eTag":'"e1"',"size":10}}]),
    ])
    objs=SupabaseRestStorageClient(base,"k","documents").list_objects("documents/")
    assert objs==[StorageObject(id="oid1", path="documents/u1/f.pdf", etag="e1", size=10)]
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** (`ingestion/storage/client.py`) — recursive list (fix C3) + pagination + download:
```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import httpx

@dataclass(frozen=True)
class StorageObject:
    id: str; path: str; etag: str; size: int

class StorageClient(Protocol):
    def list_objects(self, prefix: str) -> list[StorageObject]: ...
    def download(self, path: str, dest: Path) -> None: ...

class SupabaseRestStorageClient:
    def __init__(self, base_url: str, key: str, bucket: str) -> None:
        self._b = base_url.rstrip("/"); self._bucket = bucket
        self._h = {"apikey": key, "Authorization": f"Bearer {key}"}

    def _list_folder(self, prefix: str) -> list[dict]:
        out, offset = [], 0
        while True:
            r = httpx.post(f"{self._b}/storage/v1/object/list/{self._bucket}",
                headers=self._h, json={"prefix": prefix, "limit": 1000, "offset": offset}, timeout=30)
            r.raise_for_status(); page = r.json(); out.extend(page)
            if len(page) < 1000: break
            offset += 1000
        return out

    def list_objects(self, prefix: str) -> list[StorageObject]:
        results: list[StorageObject] = []
        stack = [prefix if prefix.endswith("/") else prefix + "/"]
        while stack:
            cur = stack.pop()
            for it in self._list_folder(cur):
                meta, name = it.get("metadata"), it["name"]
                full = cur + name
                if meta is None and it.get("id") is None:        # folder
                    stack.append(full + "/")
                elif name.lower().endswith(".pdf"):              # PDF file only
                    results.append(StorageObject(id=it["id"], path=full,
                        etag=str(meta.get("eTag", "")).strip('"'), size=int(meta.get("size", 0))))
        return results

    def download(self, path: str, dest: Path) -> None:
        r = httpx.get(f"{self._b}/storage/v1/object/{self._bucket}/{path}", headers=self._h, timeout=120)
        r.raise_for_status(); dest.write_bytes(r.content)
```
> Supabase Storage `list` response shape (folder = `id:null, metadata:null`; file = `id`,`metadata.eTag/size`) — theo doc; verify khi có key thật (Task 7), điều chỉnh nếu khác.

- [ ] **Step 4: Run → pass.** Commit:
```bash
git -C ennam.kg.python add src/ennam_kg/ingestion/storage/ tests/ingestion/test_storage_client.py
git -C ennam.kg.python commit -m "feat(doc-sync): Supabase storage client (recursive list + download)"
```

---

## Task 5: Python — `handle_supabase_sync` worker handler

**Files:** Create `ingestion/supabase_sync_client.py` (httpx-to-Go); modify `worker.py` (dispatch + handler + orphan-sweep). Test: `tests/test_supabase_sync.py`.

**Interfaces:**
- Consumes: `StorageClient` (Task 4), `extract_file_text` + `extract_structured_fields_for_file` (Plan A), `crypto.decrypt_aes_gcm` (`crypto.py:15`), `ingestion_engine.run_batch` (worker local).
- httpx-to-Go (`supabase_sync_client.py`): `get_connection_credential(conn_id) -> {supabase_url,bucket,prefix,credential_encrypted_b64,project_id}`; `list_synced_etags(conn_id) -> {obj_id: etag}`; `create_draft(project_id, title, content_raw, content_format, properties) -> node_id`; `upsert_synced(conn_id, obj, state, node_id, aaaa_user_id, err)`.
- Dispatch: `worker.py handle_message` add `elif msg_type == "supabase_sync": await handle_supabase_sync(msg)`.

- [ ] **Step 1: httpx-to-Go helpers** (`ingestion/supabase_sync_client.py`) — async httpx calls tới Go endpoints (Task 3). Bearer = `settings.go_api_key`, base = `settings.go_api_url`.

- [ ] **Step 2: Write failing test** (`tests/test_supabase_sync.py` — mock StorageClient + httpx-to-Go + extract):
```python
async def test_handle_supabase_sync_drafts_only_new(monkeypatch, tmp_path):
    # fake go client: get_connection_credential, list_synced_etags={"oid_old":"e_old"}, create_draft→"n1", upsert_synced spy
    # fake StorageClient.list_objects → [obj_old(etag e_old), obj_new(etag e_new)]; download writes a pdf
    # fake extract_file_text→("text vi","plain_text"); extract_structured_fields_for_file→{"doc_numbers":["1/QD"]}
    # assert: only obj_new processed (1 create_draft); structured_fields in properties; temp file deleted; upsert state drafted
    ...
```

- [ ] **Step 3: Run → fail.**

- [ ] **Step 4: Implement** `handle_supabase_sync`:
```python
async def handle_supabase_sync(msg: dict[str, Any]) -> None:
    from ennam_kg.ingestion.storage.client import SupabaseRestStorageClient
    from ennam_kg.ingestion.adapters.files import extract_file_text, extract_structured_fields_for_file
    from ennam_kg.crypto import decrypt_aes_gcm
    import base64, tempfile
    conn = await supa_go.get_connection_credential(msg["connection_id"])
    key = decrypt_aes_gcm(base64.b64decode(conn["credential_encrypted_b64"]),
                          base64.b64decode(settings.encryption_key)).decode()
    client = SupabaseRestStorageClient(conn["supabase_url"], key, conn["bucket"])
    seen = await supa_go.list_synced_etags(msg["connection_id"])     # {object_id: etag}
    for obj in client.list_objects(conn["prefix"]):
        if seen.get(obj.id) == obj.etag:
            continue                                                 # idempotent skip
        tmp = Path(tempfile.gettempdir()) / f"supa_{obj.id}.pdf"
        aaaa_uid = obj.path.split("/")[1] if obj.path.count("/") >= 2 else None
        try:
            client.download(obj.path, tmp)
            content_raw, content_format = extract_file_text(tmp)            # Plan A OCR
            fields = extract_structured_fields_for_file(tmp)
            node_id = await supa_go.create_draft(
                project_id=msg["project_id"], title=Path(obj.path).name,
                content_raw=content_raw, content_format=content_format,
                properties={"structured_fields": fields, "source_url": obj.path,
                            "source_platform": "supabase", "aaaa_user_id": aaaa_uid})
            await supa_go.upsert_synced(msg["connection_id"], obj, "drafted", node_id, aaaa_uid, None)
            await ingestion_engine.run_batch(project_id=msg["project_id"], draft_ids=[node_id],
                                             batch_id=f"supa:{obj.id}")
        except Exception as exc:                                     # per-doc isolation
            logger.warning("supabase sync object failed", extra={"object": obj.path, "error": str(exc)})
            await supa_go.upsert_synced(msg["connection_id"], obj, "failed", None, aaaa_uid, str(exc))
        finally:
            tmp.unlink(missing_ok=True)                              # no-persist
```
+ dispatch line trong `handle_message`. + **orphan-sweep** lúc worker start: `for f in Path(tempfile.gettempdir()).glob("supa_*.pdf"): f.unlink(missing_ok=True)`.

- [ ] **Step 5: Run → pass.** `uv run pytest tests/test_supabase_sync.py -v`

- [ ] **Step 6: Commit**
```bash
git -C ennam.kg.python add src/ennam_kg/ingestion/supabase_sync_client.py src/ennam_kg/worker.py tests/test_supabase_sync.py
git -C ennam.kg.python commit -m "feat(doc-sync): worker handle_supabase_sync (idempotent, no-persist, per-doc isolation)"
```

---

## Task 6: Next.js — Supabase card + connect dialog + sync

**Files:** Modify `components/sources/connection-bar.tsx`; Create `components/sources/supabase-connect-dialog.tsx`, `hooks/use-supabase-connection.ts`. Test: build + manual.

- [ ] **Step 1: Hook** (`hooks/use-supabase-connection.ts`) — `useConnectSupabase()` (POST `/api/kg/projects/{id}/connections` body `{source_type:'supabase', display_name, config:{supabase_url,bucket,prefix}, credential}`), `useSupabaseSync(connId)` (POST `/api/kg/projects/{id}/connections/{connId}/sync`). Status từ `useSourceConnections` sẵn có (tìm `c.source_type==='supabase'`).

- [ ] **Step 2: Card** — `connection-bar.tsx`: thêm Supabase `ConnectionCard` (icon `Database`); status Connected/Not connected từ connections data; click (admin) → mở dialog. (Mirror cách render local_upload + placeholder.)

- [ ] **Step 3: Dialog** (`supabase-connect-dialog.tsx`) — admin form: Supabase URL (prefill `https://nicrcubktflnwdkhotut.supabase.co`), bucket (`documents`), prefix (`documents/`), **Storage key** (password) → `useConnectSupabase`. Khi Connected → nút **Sync** (`useSupabaseSync`) + hiện `last_synced_at`.

- [ ] **Step 4: Build** `cd ennam.kg.next && npm run build` → OK, no type errors.

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.next add src/components/sources/connection-bar.tsx src/components/sources/supabase-connect-dialog.tsx src/hooks/use-supabase-connection.ts
git -C ennam.kg.next commit -m "feat(doc-sync): Supabase source-connection card + connect/sync UI"
```

---

## Task 7: E2E (GATED on real credential) + full-216 run

**Files:** none. Requires AAAA cấp **scoped read-only key** + corpus-project khoá admin.

- [ ] **Step 1:** Tạo project "M&A corpus" (khoá admin). Connect Supabase (nhập key) → Connected.
- [ ] **Step 2:** Sync → enumerate (216 `documents/`, loại users//matches/); idempotent (sync lần 2 = 0 mới); per-doc isolation (1 file hỏng không chặn).
- [ ] **Step 3:** Verify: draft nodes có content VN + `properties.structured_fields` + `source_url`; **temp /tmp sạch** (no-persist); re-sync chỉ khi etag đổi.
- [ ] **Step 4:** Bounded conc 1-2, off-hours (worker chung box kg-server → tránh 502). Resume nếu gián đoạn.
- [ ] **Step 5:** Verify shape `storage.objects` list response thật khớp parser (Task 4); chỉnh nếu khác. Checkpoint kết quả (Serena).

> **Trước Task 7:** chốt OQ-1 với AAAA. Nếu chọn **broker signed-URL** thay scoped-key → thêm `BrokerStorageClient(StorageClient)` (list+download qua endpoint AAAA), swap ở Task 5 — phần khác không đổi (interface giữ).

---

## Self-Review (đã chạy)
- **Spec coverage:** credential mã hoá (§0/§4.2) → Task 1/2; enumerate documents/ recursive (§4.3, fix C3) → Task 4; idempotency etag mark-at-draft (§4.5) → Task 5; no-persist+orphan-sweep (§4.6) → Task 5; per-doc isolation (§3.1) → Task 5; tenancy corpus-project (§3.0) → Task 3(project)+Task 7; UI card+sync (§4.1) → Task 6; gate full-216 (§6) → Task 7. ✓ OCR = Plan A.
- **Reuse verified:** source_connections (migration 000048) ALTER không tạo bảng song song; Sync 501 implement; UI hook/ConnectionBar reuse; queue `ennam:kg_generation` (4 consumer chạy handle_message — verified worker.py); KGClient ở `ennam_kg_indexer` → httpx-to-Go.
- **Type consistency:** `StorageObject(id,path,etag,size)` Task4→5; `SupabaseSyncMessage{Type,ConnectionID,ProjectID}` Task3→5; registry `(connection_id,object_id)+etag` Task1/5; `extract_file_text->(str,str)` + `extract_structured_fields_for_file->dict` khớp Plan A (đã fix). ✓
- **No-placeholder:** code novel (StorageClient, handle_supabase_sync, migration, queue, Sync handler) đầy đủ; "đọc trước" chỉ ở integration points (source_connection store cột-list, draft-create service, main.go wiring) — mirroring existing patterns trong codebase.

## Open dependencies (execute-time)
- **Plan A xong trước** (`extract_file_text` 2-tuple + `extract_structured_fields_for_file`).
- `POST /draft-nodes` create endpoint (Task 3 Step 3) — đọc draft-create service mà upload dùng để gọi đúng.
- `SourceConnectionService` có `encKey` chưa (Task 2) — thêm vào constructor + wire main.go (mirror DataSourceService).
- source_connection store cột-list (Task 2 Step 1) — append `credential_encrypted` vào mọi SELECT/INSERT/scan.
- Supabase Storage `list` response shape (Task 4/7) — verify với key thật.
- **OQ-1** scoped-key vs broker (Task 7 gated); interface swap.
- Worker chung box kg-server → Task 7 throttle/off-hours.
