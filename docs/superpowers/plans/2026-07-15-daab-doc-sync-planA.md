# DAAB ↔ AAAA Doc-Sync (Option A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** A per-project **Sync** button on DAAB pulls AAAA's *analyzed* documents (metadata via a new AAAA integrations endpoint, binaries via Supabase Storage signed URLs) → OCR (Plan A, done) → chunk → graph + back-link, mapped 1:1 DAAB-project ↔ AAAA-project, idempotent + resumable.

**Architecture:** Option A (spoke). AAAA exposes two read endpoints reading its OWN Postgres (`am_ai_db`) + minting Supabase Storage signed URLs. DAAB consumes over httpx behind a `DocSourceClient` adapter (so a future Option B / system #3 is an adapter swap). DAAB holds NO Supabase credential — only an AAAA service token (encrypted). A DAAB sync-state table `aaaa_synced_document` is the source of truth for progress (dedup + retry); the AAAA cursor is only an optimization.

**Tech Stack:** AAAA = Next.js 16 App Router + Prisma v7 + `@supabase/supabase-js` (`createSignedUrl`). DAAB Go = stdlib net/http, `database/sql`, golang-migrate, AES-256-GCM, redis publisher. DAAB Python = httpx worker. DAAB Next = React 19 + TanStack Query.

**Spec:** `docs/superpowers/specs/2026-07-15-daab-doc-sync-planA-aaaa-endpoint-design.md`.

## Global Constraints
- **Channel = Option A.** DAAB never holds a Supabase credential; only an AAAA Bearer service token, stored **AES-256-GCM** (`KG_ENCRYPTION_KEY`). Reversibility to B lives behind the `DocSourceClient` adapter — no source symbol may leak into the ingest pipeline.
- **Contract (fixed, both sides identical, = future registry columns):** `document_id, project_id, file_name, doc_type, mime_type, size_bytes, content_hash, status='analyzed', updated_at, file_path`. Idempotency key = `(document_id, content_hash)`.
- **No-persist:** temp download → OCR → **delete (try/finally)** + orphan-sweep; never `KG_UPLOAD_DIR`; graph node keeps only `source_url` back-link.
- **Per-doc isolation:** one doc failing (404 / expired URL / OCR error) → mark `state='failed'`, continue; retried next cycle. Never fails the batch.
- **Auth (AAAA endpoints):** shared secret in `Authorization: Bearer` header, validated with **`timingSafeEqual`** (NEW check, modeled on `secretOk` in `apollo/phone-webhook/[secret]/route.ts` — AAAA has no Bearer middleware). Not `service_role`. Signed-URL TTL **900s**.
- **Migrations:** AAAA schema via Prisma migration; AAAA storage/auth via `supabase/migrations`. DAAB Go via golang-migrate — **latest is 000075 → new = 000076** (NOT 000071). `.up`+`.down`. Nested git: `git -C <repo>`.
- **Tenancy:** `source_connections` `UNIQUE(project_id, source_type)` ⇒ one `aaaa` connection per DAAB project (1:1). `aaaa_project_id` in `config` is the routing key.
- **Tests:** AAAA `npm run test` (Vitest — mock `db` (`@/lib/db`) + `supabaseAdmin` (`@/lib/supabase/admin`) via `vi.mock`; mirror `documents/[id]/signed-url/route.test.ts`). DAAB Go `make test`. DAAB Python `uv run pytest` — httpx mocked with **`pytest-httpx`** (`httpx_mock` fixture); **`respx` is NOT a dependency** — do not use it. E2E (Task 11) gated on a real token + Supabase Storage access.

---

## File Structure

**AAAA (`other_projects/am-ai-agents`):**
- `prisma/schema.prisma` (modify) — `Document.content_hash String?`.
- `prisma/migrations/<ts>_document_content_hash/migration.sql` (create).
- `src/services/document-ingest.service.ts` (modify) — compute sha256 at upload.
- `scripts/backfill-document-content-hash.ts` (create) — one-time backfill.
- `src/lib/integrations/daab-auth.ts` (create) — `assertDaabToken(req)` via `timingSafeEqual`.
- `src/app/api/integrations/daab/documents/route.ts` (create) — list endpoint.
- `src/app/api/integrations/daab/documents/signed-urls/route.ts` (create) — signed-URL endpoint.

**DAAB Go (`ennam.kg.go`):**
- `db/migrations/000076_aaaa_doc_sync.{up,down}.sql` (create).
- `internal/models/source_connection.go` (modify) — `CredentialEncrypted []byte`; `AAAASyncedDocument` struct.
- `internal/models/draft_node.go` (modify) — `DraftSourceTypeAAAA`.
- `internal/store/source_connection.go` (modify) — read/write `credential_encrypted`.
- `internal/store/aaaa_synced_document.go` (create) — sync-state CRUD.
- `internal/service/source_connection.go` (modify) — encrypt/decrypt credential; needs `encKey`.
- `internal/handler/source_connection.go` (modify) — implement `Sync`; read credential on Create.
- `internal/handler/draft_node.go` (modify) — `POST /draft-nodes` create handler.
- `internal/handler/aaaa_synced_document.go` (create) — worker-facing sync-state endpoints.
- `internal/queue/ingestion.go` (modify) — `AAAASyncMessage` / reuse `IngestionMessage` + `PublishAAAASync`.
- `cmd/kg-server/main.go` (modify) — wire publisher + encKey.

**DAAB Python (`ennam.kg.python`):**
- `src/ennam_kg/ingestion/adapters/doc_source.py` (create) — `DocRef`, `DocSourceClient` Protocol, `AaaaHttpDocSource`.
- `src/ennam_kg/ingestion/aaaa_sync_client.py` (create) — httpx helpers to DAAB Go sync-state endpoints.
- `src/ennam_kg/worker.py` (modify) — `handle_aaaa_sync` + dispatch + orphan-sweep.
- `src/ennam_kg/<kg_client module>` (modify) — `create_draft(...)` calling `POST /draft-nodes`.

**DAAB Next (`ennam.kg.next`):**
- `src/components/sources/connection-bar.tsx` (modify) — AAAA card.
- `src/components/sources/aaaa-connect-dialog.tsx` (create).
- `src/hooks/use-aaaa-connection.ts` (create).

---

## Task 1: AAAA — `content_hash` column + compute at upload + backfill

**Files:** modify `prisma/schema.prisma`, `src/services/document-ingest.service.ts`; create migration + `scripts/backfill-document-content-hash.ts`. Test: `src/services/document-ingest.service.test.ts`.

**Interfaces:**
- Produces: `Document.content_hash` (sha256 hex of file bytes, set at upload). Consumed by Task 2 (list endpoint) and DAAB idempotency.

- [ ] **Step 1: Write failing test** — `document-ingest.service.test.ts`: mock `supabaseAdmin.storage.upload` + `createDocument`; assert `ingestDocument` passes a 64-char lowercase hex `contentHash` equal to `sha256(bytes)` into `createDocument`.
```ts
import { createHash } from "node:crypto";
it("computes sha256 content_hash at upload", async () => {
  const bytes = Buffer.from("hello-pdf");
  const expected = createHash("sha256").update(bytes).digest("hex");
  // arrange mocks so createDocument spy captures its input
  await ingestDocument({ userId:"u1", fileName:"a.pdf", bytes, contentType:"application/pdf" });
  expect(createDocumentSpy.mock.calls[0][0].contentHash).toBe(expected);
});
```
- [ ] **Step 2: Run → fail.** `cd other_projects/am-ai-agents && npm run test -- document-ingest`
- [ ] **Step 3: Schema + migration.** Add to `model Document`: `contentHash String? @map("content_hash")`. Create `prisma/migrations/<ts>_document_content_hash/migration.sql`:
```sql
ALTER TABLE "documents" ADD COLUMN "content_hash" TEXT;
CREATE INDEX "documents_content_hash_idx" ON "documents"("content_hash");
```
- [ ] **Step 4: Implement.** In `ingestDocument` (`document-ingest.service.ts`), after obtaining `input.bytes`, compute `const contentHash = createHash("sha256").update(input.bytes).digest("hex");` and pass `contentHash` into `createDocument({...})`. Add `contentHash?: string` to `CreateDocumentInput` + persist it in `document.service.ts createDocument`.
- [ ] **Step 5: Backfill script.** `scripts/backfill-document-content-hash.ts`: for each `documents WHERE content_hash IS NULL AND status='analyzed'`, download bytes from Storage (`supabaseAdmin.storage.from('documents').download(file_path)`), sha256, `UPDATE`. Idempotent, batched, logs count.
- [ ] **Step 6: Run migration + test → pass.** `npx prisma migrate dev --name document_content_hash && npm run test -- document-ingest`
- [ ] **Step 7: Commit.** `git -C other_projects/am-ai-agents add -A && git -C other_projects/am-ai-agents commit -m "feat(daab-sync): add documents.content_hash + compute at upload + backfill"`

---

## Task 2: AAAA — service-token auth helper + list endpoint

**Files:** create `src/lib/integrations/daab-auth.ts`, `src/app/api/integrations/daab/documents/route.ts`. Test: `route.test.ts` next to the route.

**Interfaces:**
- Produces: `GET /api/integrations/daab/documents?projectId=&status=analyzed&cursor=&limit=` → `{ documents: DocContract[], next_cursor: string|null }`; `assertDaabToken(req): void | throws 401`.
- `DocContract = { document_id, project_id, file_name, doc_type, mime_type, size_bytes, content_hash, status, updated_at }` (all snake_case, `updated_at` ISO-8601 UTC).

- [ ] **Step 1: Auth helper** — `src/lib/integrations/daab-auth.ts`:
```ts
import { timingSafeEqual } from "node:crypto";
export function daabTokenOk(header: string | null): boolean {
  const expected = process.env.DAAB_SYNC_TOKEN ?? "";
  if (!expected) return false;
  const provided = (header ?? "").replace(/^Bearer\s+/i, "");
  const a = Buffer.from(provided), b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}
```
- [ ] **Step 2: Write failing test** — `documents/route.test.ts`: (a) missing/wrong token → 401; (b) valid token + `projectId` → 200 with only `status='analyzed'` docs, snake_case contract fields, `next_cursor`. Mock `db.document.findMany`.
- [ ] **Step 3: Run → fail.** `npm run test -- integrations/daab/documents`
- [ ] **Step 4: Implement list route** — `src/app/api/integrations/daab/documents/route.ts`:
```ts
import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { daabTokenOk } from "@/lib/integrations/daab-auth";

export async function GET(req: NextRequest) {
  if (!daabTokenOk(req.headers.get("authorization")))
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const sp = req.nextUrl.searchParams;
  const projectId = sp.get("projectId");
  if (!projectId) return NextResponse.json({ error: "projectId required" }, { status: 400 });
  const limit = Math.min(Number(sp.get("limit") ?? 100), 500);
  const cursor = sp.get("cursor"); // "<updated_at ISO>|<id>" or null
  const where: any = { projectId, status: "analyzed", analysis: { isNot: null } };
  if (cursor) {
    const [ts, id] = cursor.split("|");
    where.OR = [{ updatedAt: { gt: new Date(ts) } },
               { updatedAt: new Date(ts), id: { gt: id } }];
  }
  const rows = await db.document.findMany({
    where, orderBy: [{ updatedAt: "asc" }, { id: "asc" }], take: limit + 1,
    select: { id:true, projectId:true, fileName:true, docType:true, mimeType:true,
              fileSize:true, contentHash:true, status:true, updatedAt:true },
  });
  const page = rows.slice(0, limit);
  const next = rows.length > limit
    ? `${page[page.length-1].updatedAt.toISOString()}|${page[page.length-1].id}` : null;
  return NextResponse.json({
    documents: page.map(d => ({
      document_id: d.id, project_id: d.projectId, file_name: d.fileName,
      doc_type: d.docType, mime_type: d.mimeType, size_bytes: Number(d.fileSize),
      content_hash: d.contentHash, status: d.status, updated_at: d.updatedAt.toISOString(),
    })),
    next_cursor: next,
  });
}
```
- [ ] **Step 5: Run → pass.** `npm run test -- integrations/daab/documents`
- [ ] **Step 6: Commit.** `git -C other_projects/am-ai-agents add -A && git -C other_projects/am-ai-agents commit -m "feat(daab-sync): AAAA list endpoint + service-token auth"`

---

## Task 3: AAAA — batch signed-URL endpoint

**Files:** create `src/app/api/integrations/daab/documents/signed-urls/route.ts`. Test: `route.test.ts`.

**Interfaces:**
- Produces: `POST /api/integrations/daab/documents/signed-urls` body `{ document_ids: string[] }` → `{ "<document_id>": { url, expires_at } }`. TTL 900s. Unknown/not-analyzed id omitted.

- [ ] **Step 1: Write failing test** — 401 on bad token; valid → for each analyzed id returns `{url, expires_at}`; a non-analyzed id is omitted (not an error). Mock `db.document.findMany` (id→file_path,status) + `supabaseAdmin.storage.from().createSignedUrl`.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement:**
```ts
import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { supabaseAdmin } from "@/lib/supabase/admin";
import { daabTokenOk } from "@/lib/integrations/daab-auth";
const TTL = 900;
export async function POST(req: NextRequest) {
  if (!daabTokenOk(req.headers.get("authorization")))
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  const { document_ids } = await req.json().catch(() => ({ document_ids: [] }));
  const ids: string[] = Array.isArray(document_ids) ? document_ids.filter((x)=>typeof x==="string") : [];
  const docs = await db.document.findMany({
    where: { id: { in: ids }, status: "analyzed" }, select: { id:true, filePath:true } });
  const out: Record<string, { url: string; expires_at: string }> = {};
  const expiresAt = new Date(Date.now() + TTL*1000).toISOString(); // NOTE: fine in Next runtime
  for (const d of docs) {
    const { data } = await supabaseAdmin.storage.from("documents").createSignedUrl(d.filePath, TTL);
    if (data?.signedUrl) out[d.id] = { url: data.signedUrl, expires_at: expiresAt };
  }
  return NextResponse.json(out);
}
```
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit.** `git -C other_projects/am-ai-agents commit -am "feat(daab-sync): AAAA batch signed-url endpoint"`

---

## Task 4: DAAB Go — migration 000076 + models

**Files:** create `db/migrations/000076_aaaa_doc_sync.{up,down}.sql`; modify `internal/models/source_connection.go`, `internal/models/draft_node.go`. Test: migration applies + `go build`.

**Interfaces:**
- Produces: `source_type='aaaa'` allowed; `source_connections.credential_encrypted BYTEA`; table `aaaa_synced_document`; `models.AAAASyncedDocument`; `models.DraftSourceTypeAAAA`.

- [ ] **Step 1: Migration up** — `000076_aaaa_doc_sync.up.sql`:
```sql
ALTER TABLE source_connections DROP CONSTRAINT IF EXISTS source_connections_source_type_check;
ALTER TABLE source_connections ADD CONSTRAINT source_connections_source_type_check
  CHECK (source_type IN ('jira','google_drive','local_upload','satellite_api','aaaa'));
ALTER TABLE source_connections ADD COLUMN IF NOT EXISTS credential_encrypted BYTEA;

CREATE TABLE aaaa_synced_document (
  id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  connection_id  UUID NOT NULL REFERENCES source_connections(id) ON DELETE CASCADE,
  document_id    TEXT NOT NULL,
  content_hash   TEXT,
  state          TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','ingested','failed')),
  draft_node_id  UUID,
  failure_reason TEXT,
  last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_aaaa_synced UNIQUE (connection_id, document_id)
);
CREATE INDEX idx_aaaa_synced_state ON aaaa_synced_document(connection_id, state);
```
- [ ] **Step 2: Migration down** — `000076_aaaa_doc_sync.down.sql`:
```sql
DROP TABLE IF EXISTS aaaa_synced_document;
ALTER TABLE source_connections DROP COLUMN IF EXISTS credential_encrypted;
ALTER TABLE source_connections DROP CONSTRAINT IF EXISTS source_connections_source_type_check;
ALTER TABLE source_connections ADD CONSTRAINT source_connections_source_type_check
  CHECK (source_type IN ('jira','google_drive','local_upload','satellite_api'));
```
- [ ] **Step 3: Models.** In `models/source_connection.go` add to `SourceConnection` struct: `CredentialEncrypted []byte `json:"-" db:"credential_encrypted"``. Add:
```go
type AAAASyncedDocument struct {
	ID, ConnectionID, DocumentID, State string
	ContentHash, DraftNodeID, FailureReason *string
}
```
In `models/draft_node.go` add const `DraftSourceTypeAAAA DraftSourceType = "aaaa"`.
- [ ] **Step 4: Apply + build.** `cd ennam.kg.go && make db-migrate && make db-migrate-version` (expect 000076) `&& go build ./...`
- [ ] **Step 5: Commit.** `git -C ennam.kg.go add db/migrations/000076_* internal/models/ && git -C ennam.kg.go commit -m "feat(daab-sync): migration 000076 aaaa source_type + credential + sync-state table"`

---

## Task 5: DAAB Go — credential encrypt/decrypt + sync-state store

**Files:** modify `internal/store/source_connection.go`, `internal/service/source_connection.go`; create `internal/store/aaaa_synced_document.go`. Test: `internal/service/source_connection_test.go`, `internal/store/aaaa_synced_document_test.go`.

**Interfaces:**
- Produces: `(*SourceConnectionService).CreateWithCredential(ctx, conn, credential)`, `.DecryptCredential(conn) (string, error)`. Store: `UpsertSyncedDoc(ctx, AAAASyncedDocument)`, `GetSyncedDoc(ctx, connID, documentID) (*AAAASyncedDocument, error)`, `ListFailed(ctx, connID) ([]AAAASyncedDocument, error)`. `source_connection` store SELECT/INSERT/UPDATE include `credential_encrypted`.

- [ ] **Step 1: Store — credential column.** Read the current SELECT/INSERT/scan column list in `store/source_connection.go`; append `credential_encrypted` to every query + scan target.
- [ ] **Step 2: Sync-state store.** Create `store/aaaa_synced_document.go` with `UpsertSyncedDoc` (`INSERT … ON CONFLICT (connection_id, document_id) DO UPDATE SET content_hash=…, state=…, draft_node_id=…, failure_reason=…, last_attempt_at=NOW()`), `GetSyncedDoc`, `ListFailed`.
- [ ] **Step 3: Failing service test** — `service/source_connection_test.go`:
```go
func TestSourceConnection_AAAACredentialEncrypted(t *testing.T) {
	key := make([]byte, 32)
	svc := NewSourceConnectionService(fakeStore(), logger, key) // real ctor is (store, logger); this plan extends it to (store, logger, encKey)
	conn := &models.SourceConnection{ProjectID:"p1", SourceType:"aaaa", DisplayName:"AAAA",
		Config: []byte(`{"aaaa_base_url":"https://aaaa","aaaa_project_id":"ap1"}`)}
	if err := svc.CreateWithCredential(context.Background(), conn, "tok_abc"); err != nil { t.Fatal(err) }
	if string(conn.CredentialEncrypted) == "tok_abc" { t.Fatal("plaintext stored") }
	got, _ := svc.DecryptCredential(conn)
	if got != "tok_abc" { t.Errorf("decrypt mismatch: %q", got) }
}
```
- [ ] **Step 4: Run → fail.** `cd ennam.kg.go && go test ./internal/service/ -run AAAACredential -v`
- [ ] **Step 5: Implement service.** Add `encKey []byte` to `SourceConnectionService` (constructor + wire in main.go — Task 7). Mirror the existing DataSource crypto usage:
```go
func (s *SourceConnectionService) CreateWithCredential(ctx context.Context, conn *models.SourceConnection, credential string) error {
	if conn.SourceType == models.DraftSourceTypeAAAA && credential != "" {
		enc, err := crypto.Encrypt([]byte(credential), s.encKey)
		if err != nil { return fmt.Errorf("encrypt aaaa credential: %w", err) }
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
- [ ] **Step 6: Run → pass** (both store + service tests). Commit. `git -C ennam.kg.go commit -am "feat(daab-sync): encrypt aaaa credential + sync-state store"`

---

## Task 6: DAAB Go — draft-create + sync-state + credential-fetch endpoints

**Files:** modify `internal/handler/draft_node.go`; create `internal/handler/aaaa_synced_document.go`. Test: handler tests.

**Interfaces:**
- Produces:
  - `POST /api/v1/projects/{projectId}/draft-nodes` body `{title, source_type, source_id, content_raw, content_format, source_url, properties}` → `{id}` (reuses store `Upsert` — the store method is named **`Upsert`**, ON CONFLICT `(project_id, source_type, source_id)`; requires `project_id, source_type, source_id, title, created_by`).
  - `GET /…/connections/{connId}/synced-docs/{documentId}` → AAAASyncedDocument|404; `PUT …/synced-docs` upsert.
  - **`GET /…/connections/{connId}/credential`** → `{aaaa_base_url, aaaa_project_id, token}` — decrypts `credential_encrypted` server-side (`svc.DecryptCredential`) + reads `config`. **This is the endpoint the worker (Task 9) calls to obtain the AAAA base URL + decrypted token** — without it Task 9 cannot authenticate to AAAA.
  - All three internal-key/admin guarded (mirror the guard on the existing draft `content`/`process` worker-facing routes).

- [ ] **Step 1: Failing test** — `draft_node_test.go`: `POST /draft-nodes` with `source_type:"aaaa", source_id:"doc1", title:"a.pdf"` → 201 `{id}`; missing `source_id`/`title` → 400. Plus a test that `GET …/credential` returns the decrypted token + config for an `aaaa` connection.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement draft-create handler** — in `draft_node.go`, register `mux.HandleFunc("POST /api/v1/projects/{projectId}/draft-nodes", h.Create)` and implement `Create`: decode body → build `models.DraftNode{ProjectID, SourceType, SourceID, Title, ContentRaw, ContentFormat, SourceURL, Metadata(properties), CreatedBy:"worker"}` → `store.Upsert` → return `{id}`. (`CreatedBy` must be non-empty; `SourceID`/`Title` required per store validation. Upsert-by-source means re-sync of the same doc returns the same draft — idempotent.) **In `properties`/`Metadata`, include whatever marker the pipeline's `_is_pdf(meta)` / `build_canonical_document` expects** (verify in `engine.py` — the OCR'd content is already text, so set `content_format` correctly and any `is_pdf`/mime marker so canonical-doc building treats it right).
- [ ] **Step 4: Sync-state + credential handlers** — `aaaa_synced_document.go`: `GET`/`PUT` synced-docs → store `GetSyncedDoc`/`UpsertSyncedDoc`; **`GET …/credential`** → `svc.GetByID` + `svc.DecryptCredential` + parse `config` → `{aaaa_base_url, aaaa_project_id, token}`. Register routes; guard with the existing internal/admin auth used by worker-facing endpoints (read how the draft `content`/`process` routes are guarded, mirror it).
- [ ] **Step 5: Run → pass** + `go build ./...`. Commit. `git -C ennam.kg.go commit -am "feat(daab-sync): draft-create + sync-state + credential-fetch worker endpoints"`

---

## Task 7: DAAB Go — implement Sync (501→) + queue + wiring

**Files:** modify `internal/handler/source_connection.go`, `internal/queue/ingestion.go`, `cmd/kg-server/main.go`. Test: handler test.

**Interfaces:**
- Produces: `POST /…/connections/{connId}/sync` (admin) → 202 `{status:"enqueued"}`, publishes `IngestionMessage{Type:"aaaa_sync", ConnectionID, ProjectID, AAAAProjectID}` to `KGGenerationQueueName`.

- [ ] **Step 1: Queue message.** In `internal/queue/ingestion.go`, `IngestionMessage` already has `Type string json:"type"` (verified `ingestion.go:26`) + `ProjectID`; **add fields `ConnectionID` + `AAAAProjectID`** (absent today). Add `PublishAAAASync(ctx, IngestionMessage)` to the **`IngestionPublisher` interface** (`ingestion.go:43`) + the redis impl (reuse the private `publish` to `KGGenerationQueueName`). The Python worker dispatches on `msg.get("type")` (`worker.py:185`) — `Type:"aaaa_sync"` slots in.
- [ ] **Step 2: Failing handler test** — `source_connection_test.go`: `Sync` non-`aaaa` conn → 501; `aaaa` + non-admin → 403; `aaaa` + admin → 202 + publisher called once with `Type=="aaaa_sync"`. Inject a fake publisher.
- [ ] **Step 3: Run → fail.**
- [ ] **Step 4: Implement Sync** (`source_connection.go:208` replace the 501 body):
```go
func (h *SourceConnectionHandler) Sync(w http.ResponseWriter, r *http.Request) {
	pid := strings.TrimSpace(r.PathValue("projectId"))
	connID := strings.TrimSpace(r.PathValue("connId"))
	if !requireProjectRole(w, r, pid, models.ProjectMemberRoleAdmin, h.roleResolver) { return } // helper EXISTS (project_role.go:91); add roleResolver to the handler struct/ctor. NOTE: requireProjectRole returns true for legacy API-key callers with no UserIdentity — admin gating only bites session users; document this.
	conn, err := h.svc.GetByID(r.Context(), pid, connID) // real method is GetByID (there is NO svc.Get)
	if err != nil || conn == nil { errorResponse(w, http.StatusNotFound, "connection not found"); return }
	if conn.SourceType != models.DraftSourceTypeAAAA {
		errorResponse(w, http.StatusNotImplemented, "sync only implemented for aaaa"); return
	}
	var cfg struct{ AAAAProjectID string `json:"aaaa_project_id"` }
	_ = json.Unmarshal(conn.Config, &cfg)
	if err := h.publisher.PublishAAAASync(r.Context(), queue.IngestionMessage{
		Type: "aaaa_sync", ConnectionID: connID, ProjectID: pid, AAAAProjectID: cfg.AAAAProjectID,
	}); err != nil { errorResponse(w, http.StatusInternalServerError, "enqueue failed"); return }
	writeJSON(w, http.StatusAccepted, map[string]string{"status": "enqueued"})
}
```
(Add `publisher` + `roleResolver` to the handler struct/constructor; `Create` must call `svc.CreateWithCredential` reading a `credential` body field for `aaaa`.)
- [ ] **Step 5: Wire main.go.** Inject the ingestion publisher + encKey (`KG_ENCRYPTION_KEY` via `crypto.KeyFromBase64`) into `NewSourceConnectionService`/`NewSourceConnectionHandler` (read the current construction at `main.go:634/649/654`).
- [ ] **Step 6: Run → pass** + `go build ./...`. Commit. `git -C ennam.kg.go commit -am "feat(daab-sync): implement aaaa Sync (501→) + queue + wiring"`

---

## Task 8: DAAB Python — `DocSourceClient` adapter + AaaaHttpDocSource

**Files:** create `src/ennam_kg/ingestion/adapters/doc_source.py`, `src/ennam_kg/ingestion/aaaa_sync_client.py`. Test: `tests/ingestion/test_doc_source.py`.

**Interfaces:**
- Produces: `DocRef` dataclass; `DocSourceClient` Protocol `list_documents(project_id, cursor)->tuple[list[DocRef],str|None]`, `get_signed_urls(ids)->dict[str,str]`, `download(url, dest)`; `AaaaHttpDocSource(base_url, token)`.

- [ ] **Step 1: Failing test** (mock httpx via **`pytest-httpx`** `httpx_mock` — NOT respx): `list_documents` maps snake_case JSON → `DocRef`; passes cursor; `get_signed_urls` returns `{id:url}`; `download` writes bytes to dest.
```python
def test_list_documents_maps_contract(httpx_mock):
    base="https://aaaa"
    httpx_mock.add_response(url=f"{base}/api/integrations/daab/documents?projectId=ap1&status=analyzed&limit=100",
      json={"documents":[{"document_id":"d1","project_id":"ap1","file_name":"a.pdf","doc_type":"legal",
        "mime_type":"application/pdf","size_bytes":10,"content_hash":"h1","status":"analyzed",
        "updated_at":"2026-07-15T00:00:00Z"}], "next_cursor":None})
    src = AaaaHttpDocSource(base, "tok")
    rows, nxt = src.list_documents("ap1", None)
    assert rows[0].document_id=="d1" and rows[0].content_hash=="h1" and nxt is None
```
- [ ] **Step 2: Run → fail.** `cd ennam.kg.python && uv run pytest tests/ingestion/test_doc_source.py -v`
- [ ] **Step 3: Implement** `doc_source.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import httpx

@dataclass(frozen=True)
class DocRef:
    document_id: str; project_id: str; file_name: str; doc_type: str | None
    mime_type: str; size_bytes: int; content_hash: str | None; updated_at: str

class DocSourceClient(Protocol):
    def list_documents(self, project_id: str, cursor: str | None) -> tuple[list[DocRef], str | None]: ...
    def get_signed_urls(self, document_ids: list[str]) -> dict[str, str]: ...
    def download(self, signed_url: str, dest: Path) -> None: ...

class AaaaHttpDocSource:
    def __init__(self, base_url: str, token: str) -> None:
        self._b = base_url.rstrip("/"); self._h = {"Authorization": f"Bearer {token}"}
    def list_documents(self, project_id, cursor=None):
        p = {"projectId": project_id, "status": "analyzed", "limit": 100}
        if cursor: p["cursor"] = cursor
        r = httpx.get(f"{self._b}/api/integrations/daab/documents", params=p, headers=self._h, timeout=30)
        r.raise_for_status(); j = r.json()
        rows = [DocRef(document_id=d["document_id"], project_id=d["project_id"], file_name=d["file_name"],
                       doc_type=d.get("doc_type"), mime_type=d["mime_type"], size_bytes=int(d["size_bytes"]),
                       content_hash=d.get("content_hash"), updated_at=d["updated_at"]) for d in j["documents"]]
        return rows, j.get("next_cursor")
    def get_signed_urls(self, document_ids):
        r = httpx.post(f"{self._b}/api/integrations/daab/documents/signed-urls",
                       json={"document_ids": document_ids}, headers=self._h, timeout=30)
        r.raise_for_status(); return {k: v["url"] for k, v in r.json().items()}
    def download(self, signed_url, dest):
        r = httpx.get(signed_url, timeout=120); r.raise_for_status(); dest.write_bytes(r.content)
```
- [ ] **Step 4: `aaaa_sync_client.py`** — async httpx helpers to DAAB Go endpoints (Task 6): **`get_connection_credential(conn_id)`** → `{aaaa_base_url, aaaa_project_id, token}` (the credential-fetch endpoint — required by Task 9), `get_synced(conn_id, doc_id)`, `upsert_synced(conn_id, doc_id, state, content_hash, draft_node_id, failure_reason)`, `create_draft(project_id, title, content_raw, content_format, source_url, properties, source_id)`. Base = `settings.go_api_url`, Bearer = `settings.go_api_key`. Test these with `httpx_mock` too.
- [ ] **Step 5: Run → pass.** Commit. `git -C ennam.kg.python add -A && git -C ennam.kg.python commit -m "feat(daab-sync): DocSourceClient adapter + AaaaHttpDocSource + go sync-client"`

---

## Task 9: DAAB Python — `handle_aaaa_sync` worker

**Files:** modify `src/ennam_kg/worker.py`. Test: `tests/test_aaaa_sync.py`.

**Interfaces:**
- Consumes: `DocSourceClient`, `aaaa_sync_client`, `extract_file_text`/`extract_structured_fields_for_file` (Plan A), `ingestion_engine.run_batch`. Dispatch: `handle_message` add `elif msg_type == "aaaa_sync": await handle_aaaa_sync(msg)`.

- [ ] **Step 1: Failing test** (mock `DocSourceClient` + `aaaa_sync_client` + `extract_*`): given 2 docs (one already `state='ingested'` same hash, one new) → only the new one drafts (1 `create_draft`); temp file deleted; `upsert_synced(state='ingested')` called with content_hash; a download raising → `state='failed'`, batch continues.
- [ ] **Step 2: Run → fail.** `uv run pytest tests/test_aaaa_sync.py -v`
- [ ] **Step 3: Implement** `handle_aaaa_sync`:
```python
async def handle_aaaa_sync(msg: dict[str, Any]) -> None:
    import tempfile
    from ennam_kg.ingestion.adapters.doc_source import AaaaHttpDocSource
    from ennam_kg.ingestion.adapters.files import extract_file_text, extract_structured_fields_for_file
    conn_id = msg["connection_id"]; daab_project = msg["project_id"]; aaaa_project = msg["aaaa_project_id"]
    conn = await aaaa_go.get_connection_credential(conn_id)   # base_url + decrypted token (Go endpoint)
    src = AaaaHttpDocSource(conn["aaaa_base_url"], conn["token"])
    cursor = None
    while True:
        rows, cursor = await asyncio.to_thread(src.list_documents, aaaa_project, cursor)
        for d in rows:
            prior = await aaaa_go.get_synced(conn_id, d.document_id)
            if prior and prior.get("state") == "ingested" and prior.get("content_hash") == d.content_hash:
                continue
            await aaaa_go.upsert_synced(conn_id, d.document_id, "pending", d.content_hash, None, None)
            tmp = Path(tempfile.gettempdir()) / f"aaaa_{d.document_id}.bin"
            try:
                urls = await asyncio.to_thread(src.get_signed_urls, [d.document_id])
                await asyncio.to_thread(src.download, urls[d.document_id], tmp)
                content_raw, content_format = await asyncio.to_thread(extract_file_text, tmp)
                fields = await asyncio.to_thread(extract_structured_fields_for_file, tmp)
                recovered = _build_recovered_fields_section(fields)
                if recovered: content_raw = f"{content_raw}{recovered}"
                draft_id = await aaaa_go.create_draft(
                    project_id=daab_project, title=d.file_name, source_id=d.document_id,
                    content_raw=content_raw, content_format=content_format,
                    source_url=_aaaa_backlink(aaaa_project, d.document_id),
                    properties={"structured_fields": fields, "source_platform": "aaaa",
                                "aaaa_document_id": d.document_id})
                await ingestion_engine.run_batch(project_id=daab_project, draft_ids=[draft_id],
                                                 batch_id=f"aaaa:{d.document_id}")
                await aaaa_go.upsert_synced(conn_id, d.document_id, "ingested", d.content_hash, draft_id, None)
            except Exception as exc:
                logger.warning("aaaa sync doc failed", extra={"doc": d.document_id, "err": str(exc)})
                await aaaa_go.upsert_synced(conn_id, d.document_id, "failed", d.content_hash, None, str(exc))
            finally:
                tmp.unlink(missing_ok=True)
        if not cursor: break
```
Add dispatch line in `handle_message`. Add **orphan-sweep** on worker start: `for f in Path(tempfile.gettempdir()).glob("aaaa_*.bin"): f.unlink(missing_ok=True)`. Add `_aaaa_backlink()` helper (OQ-2 URL).
- [ ] **Step 4: Run → pass.** `uv run pytest tests/test_aaaa_sync.py -v`
- [ ] **Step 5: Commit.** `git -C ennam.kg.python commit -am "feat(daab-sync): handle_aaaa_sync worker (idempotent, no-persist, per-doc isolation)"`

---

## Task 10: DAAB Next — AAAA card + connect dialog + sync

**Files:** modify `src/components/sources/connection-bar.tsx`; create `src/components/sources/aaaa-connect-dialog.tsx`, `src/hooks/use-aaaa-connection.ts`. Test: build + manual.

- [ ] **Step 1: Hook** `use-aaaa-connection.ts` — `useConnectAaaa()` (POST `/api/kg/projects/{id}/connections` body `{source_type:'aaaa', display_name, config:{aaaa_base_url, aaaa_project_id}, credential}`), `useAaaaSync(connId)` (POST `/api/kg/projects/{id}/connections/{connId}/sync`). Status from `useSourceConnections` (`c.source_type==='aaaa'`).
- [ ] **Step 2: Card** — `connection-bar.tsx`: add AAAA `ConnectionCard` (icon `Database`), status Connected/Not from connections; admin click → dialog. Mirror the `local_upload` card render at `connection-bar.tsx:73-94`.
- [ ] **Step 3: Dialog** `aaaa-connect-dialog.tsx` — admin form: AAAA base URL (prefill `https://aaaa.ennam.vn`), `aaaa_project_id`, service token (password) → `useConnectAaaa`. When Connected → **Sync** button + show `last_synced_at`.
- [ ] **Step 4: Build.** `cd ennam.kg.next && npm run build` → no type errors.
- [ ] **Step 5: Commit.** `git -C ennam.kg.next add -A && git -C ennam.kg.next commit -m "feat(daab-sync): AAAA source-connection card + connect/sync UI"`

---

## Task 11: E2E (GATED on real token + Supabase Storage access)

**Files:** none. Requires: `DAAB_SYNC_TOKEN` set in AAAA + DAAB connection; both stacks up; AAAA `documents` with ≥1 analyzed doc.

- [ ] **Step 1:** Create a DAAB project, connect AAAA (base URL + `aaaa_project_id` + token) → Connected.
- [ ] **Step 2:** Sync → verify: only `analyzed` docs of that AAAA project ingest into THIS DAAB project; draft nodes carry VN OCR text + `properties.structured_fields` + `source_url` back-link.
- [ ] **Step 3:** Idempotency: Sync again → 0 new (all `state='ingested'`, unchanged `content_hash`). Change a doc in AAAA (re-analyze) → next Sync re-ingests only that one.
- [ ] **Step 4:** Isolation: one unreadable/expired doc → `state='failed'`, batch completes; retried next Sync.
- [ ] **Step 5:** No-persist: `/tmp` has no `aaaa_*.bin` after a run (orphan-sweep + try/finally). Checkpoint results (Serena).

---

## Self-Review

- **Spec coverage:** content_hash (§3.1)→T1; list endpoint+auth (§2/§3.2)→T2; signed-urls (§2/§3.3)→T3; migration+models incl. sync-state table (§4.1)→T4; credential crypto + sync-state store (§4.1)→T5; draft-create + sync-state endpoints (§4.1)→T6; Sync 501→ + queue + wiring (§4.1)→T7; DocSourceClient adapter (§4.2/§5)→T8; handle_aaaa_sync incl. dedup-via-sync-state + no-persist + isolation (§4.2/§6)→T9; UI card+sync (§4.3)→T10; per-project 1:1 tenancy (§7)→config in T7/T10; gated E2E (§10)→T11. ✓ OCR = Plan A (reused, not re-built).
- **Reversibility (§5):** ingest depends only on `DocSourceClient` (T8); no Supabase symbol in the pipeline; contract fields + idempotency key `(document_id, content_hash)` match a future `SupabaseViewDocSource`. ✓
- **Type consistency:** contract snake_case identical across T2 (emit) → T8 `DocRef` (consume); `IngestionMessage{Type,ConnectionID,ProjectID,AAAAProjectID}` T7→T9; sync-state `(connection_id, document_id)`+`content_hash`+`state` T4/T5/T6/T9; `create_draft` fields (source_id, title, content_raw/format, source_url, properties) T6→T8→T9; `extract_file_text->(str,str)` + `extract_structured_fields_for_file->dict` verified Plan A. ✓
- **Read-before-write integration points (mirror existing, not placeholders):** `IngestionMessage` struct shape (T7), `source_connection` store column-list (T5 Step 1), the admin/internal auth guard used by worker-facing routes (T6 Step 4), `main.go` construction of the source-connection service/handler (T7 Step 5), `DraftNode` struct fields + `CreatedBy` requirement (T6), KGClient module path for `create_draft` (T8 Step 4). Each says which existing pattern to mirror.
- **Open questions to resolve at execution:** OQ-1 content_hash (default: the column, T1); OQ-2 back-link URL (`_aaaa_backlink`, T9); OQ-3 token issuance/rotation (env `DAAB_SYNC_TOKEN`, T2); OQ-4 filter = `status='analyzed' AND analysis isNot null` (T2).

### Review corrections applied (2-agent source verification, 2026-07-15)
- **AAAA (T1-3):** all concrete TS verified against source — `ingestDocument`/`createDocument` shapes, Prisma field names, `analysis` relation, `supabaseAdmin.createSignedUrl` return shape, `db` import, Prisma migration layout. Tests mock `@/lib/db` + `@/lib/supabase/admin` (mirror `documents/[id]/signed-url/route.test.ts`).
- **DAAB blockers fixed:** (1) added the **credential-fetch endpoint** `GET …/connections/{connId}/credential` (T6) — worker (T9) needs the decrypted token + base URL; it was missing. (2) `svc.Get` → **`svc.GetByID`** (real method; T7). (3) tests use **`pytest-httpx`** (`httpx_mock`), **not `respx`** (not a dep) — T8/T9 + Global Constraints.
- **DAAB wording/facts:** draft store method is **`Upsert`** (ON CONFLICT project/source_type/source_id), not `Create` (T6); `NewSourceConnectionService` real ctor is `(store, logger)` → extended to `(store, logger, encKey)` (T5); `IngestionMessage.Type` exists, add `ConnectionID`+`AAAAProjectID` + `PublishAAAASync` to the interface (T7); `run_batch` params are keyword-only, `source_stored_path` optional (T9); canonical dedup `content_hash` = hash of **extracted text** (differs from AAAA's file-byte sha256 → **sync-state table is the true dedup key**, canonical is only a secondary net); migration `uuid_generate_v4()` consistent, latest 000075→**000076**.
- **Security note:** `requireProjectRole` passes legacy API-key callers with no UserIdentity — the Sync admin guard only bites session users; documented in T7.
- **Verify-at-execution nuance:** the AAAA-sync draft's `Metadata` must carry whatever `_is_pdf`/mime marker `build_canonical_document` expects (T6 Step 3) — the content is already OCR'd text, so set `content_format` + marker correctly.
