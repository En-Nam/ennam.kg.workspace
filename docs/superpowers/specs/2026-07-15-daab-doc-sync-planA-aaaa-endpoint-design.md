# DAAB ↔ AAAA Doc-Sync — Design Spec (Option A: AAAA integrations endpoint)

> **Status:** DRAFT — approved direction (Option A), pending plan. Written 2026-07-15.
> **Supersedes:** the *connector* half of `2026-06-26-daab-doc-sync-design.md` (Plan B / Supabase-Storage broker + locked-corpus-project). Plan A **OCR pipeline is DONE** and is reused as-is.
> **Goal:** A per-project **Sync** button on the DAAB project Sources page pulls AAAA's *analyzed* documents (metadata via an AAAA integrations endpoint, binaries via Supabase Storage signed URLs) → OCR (done) → chunk → graph + back-link. One DAAB project ↔ one AAAA project.
> **Decision provenance:** 2-round CTO⇄consultant debate (both independent → A) + 2-agent source grounding. Grounded in `decisions/ecosystem-direction-cto-approved-2026-06-24` (DAAB = knowledge layer; syncs text + back-links, does NOT store documents) and CTO chat 2026-06-24 (shared Supabase for auth; DAAB sync button pulling unprocessed docs + back-link).

---

## 0. Why A (and the load-bearing fact that ruled out B)

**Verified against live source (2-agent grounding, 2026-07-15):**

| Thing | Location (verified) |
|---|---|
| Auth / identity | Supabase (DAAB already verifies Supabase JWTs — `internal/supabaseauth/verifier.go`) |
| Binary PDFs | Supabase **Storage** bucket `documents` (RLS on, role `authenticated`, path `documents/<uid>/…`) |
| Document **metadata** (`project_id`, `status`, `file_name`, …) | **AAAA's OWN Postgres** (`am_ai_db`, Prisma) — **NOT on Supabase** |

The CTO's premise "Supabase đã có document table" conflates the Storage **bucket** with a metadata **table**. Live Supabase `public` schema has **zero tables**; AAAA's `supabase/migrations/README.md` documents a deliberate `local-postgres-vs-supabase-split`; `.env.example` shows `DATABASE_URL=…@localhost:5500/am_ai_db`.

**Consequence:** a VIEW on the shared Supabase Postgres (Option B) has nothing to select from — not buildable without relocating/mirroring AAAA's business DB. The document metadata lives behind AAAA's Prisma layer, so the clean, low-regret way to expose it is a **read endpoint on AAAA** (Option A). Binaries still come from Supabase Storage (signed URL), so "shared Supabase" is used for what actually lives there (auth + storage).

**Reversibility:** Option A is chosen adapter-first so a future switch to B (shared Supabase registry table) is a one-adapter change on DAAB — see §5 and `backlog/daab-doc-sync-planB-future`.

## 1. Architecture & flow

```
DAAB dashboard: /projects/{daab_project_id}/sources
  [Card "AAAA"] → (admin) Connect → nhập aaaa_project_id + AAAA service token (mã hoá) → [Connected] → [Sync]
        │ POST /api/v1/projects/{pid}/connections/{connId}/sync  (implement 501→202)
        ▼  enqueue "aaaa_sync" {connection_id, daab_project_id, aaaa_project_id, cursor}
  DAAB worker (Python): handle_aaaa_sync
        │ 1. DocSourceClient.list_documents(aaaa_project_id, cursor)  ── httpx → AAAA endpoint
        │      GET /api/integrations/daab/documents?projectId=&status=analyzed&cursor=
        │      → [{document_id, project_id, file_name, doc_type, mime_type, size_bytes, content_hash, status, updated_at}], nextCursor
        │ 2. PER doc (try/except isolation):
        │      a. dedup (document_id, content_hash) → skip if get_canonical_document_by_source hit
        │      b. DocSourceClient.get_signed_urls([document_id]) ── AAAA mints (createSignedUrl, TTL 15m)
        │      c. download → tmp /tmp (try/finally delete; orphan-sweep on worker start)
        │      d. OCR (Plan A): extract_file_text(path) + extract_structured_fields_for_file(path)
        │      e. create draft-node: content_raw + content_format + source_url(back-link to AAAA) + properties
        │      f. run_batch → graph node + back-link ; registry state
        │      g. delete tmp
        │ 3. advance cursor (source_connections.last_synced_at / config cursor)
```

**DAAB never holds a Supabase credential** (only an AAAA service token). **DAAB never stores the binary** (temp → delete). AAAA is the only party that touches Supabase Storage.

## 2. Boundary contract (fixed — must match on both sides; = future registry columns)

**List endpoint** — `GET /api/integrations/daab/documents`
- Query: `projectId` (AAAA project uuid), `status=analyzed`, `cursor` (opaque keyset), `limit` (default 100, max 500).
- Auth: shared secret in `Authorization: Bearer <daab-service-token>` header, validated with **`timingSafeEqual`** against an env secret. ⚠️ This is a **NEW check** modeled on AAAA's existing path-`[secret]` + `timingSafeEqual` pattern (`apollo/phone-webhook/[secret]`) — AAAA has **no** Bearer middleware to reuse. Scope: DAAB read-only.
- Response:
```json
{ "documents": [{
    "document_id": "uuid",
    "project_id": "uuid",
    "file_name": "string",
    "doc_type": "string|null",
    "mime_type": "string",
    "size_bytes": 12345,
    "content_hash": "sha256-hex",
    "status": "analyzed",
    "updated_at": "ISO-8601 UTC"
  }],
  "next_cursor": "string|null" }
```
- **No signed URL inline** — keeps the list credential-free, cacheable, idempotent.
- Ordered by `(updated_at, document_id)` keyset (stable under concurrent inserts). `next_cursor` encodes the last `(updated_at, document_id)`.

**Signed-URL endpoint** — `POST /api/integrations/daab/documents/signed-urls`
- Auth: same header secret (`timingSafeEqual`).
- Body: `{ "document_ids": ["uuid", …] }` (batch; DAAB requests only for docs it will download this cycle).
- Response: `{ "<document_id>": { "url": "https://…", "expires_at": "ISO-8601" } }`
- TTL **15 minutes** (large-PDF download headroom). AAAA mints via `supabaseAdmin.storage.from('documents').createSignedUrl(file_path, 900)`. A `document_id` not `analyzed`/not owned → omitted (logged), does not fail the batch.

**Idempotency key = `(document_id, content_hash)`.** `content_hash` = sha256 of the file bytes (a true content signal; metadata-only edits do NOT re-trigger OCR). See §3 for how AAAA supplies it.

## 3. AAAA components (repo `am-ai-agents`)

1. **`content_hash` on documents** *(effectively REQUIRED — see OQ-1)* — add column `content_hash TEXT` to the `documents` model, compute sha256 at upload in `ingestDocument` (bytes already in hand, `document-ingest.service.ts`), one-time backfill for existing analyzed docs. Rationale: without a content signal in the **list** response, DAAB cannot dedup **before** download → it must download every doc every sync (wasted signed URLs + bandwidth, breaks no-persist efficiency). Also forward-compatible with Option B. **Fallback if deferred:** endpoint returns Storage object `eTag` (from `storage.objects.metadata`, fetched per-doc — extra calls) as `content_hash`, or accept download-all + hash-on-DAAB (state the cost). Decide in plan.
2. **List endpoint** `src/app/api/integrations/daab/documents/route.ts` — header-secret auth (`timingSafeEqual`, §2 — NOT an existing Bearer middleware; new check). Reads AAAA's own Postgres via **Prisma**: `db.document.findMany({ where: { projectId, status: 'analyzed', analysis: { isNot: null } }, orderBy: [{ updatedAt: 'asc' }, { id: 'asc' }], take: limit, cursor })` — `analysis` is a **relation**, filtered via `isNot: null` (NOT a raw-SQL `IS NOT NULL` column check). Returns the §2 contract. **Cross-tenant guard:** the machine token is trusted; scope reads to the requested `projectId` only.
3. **Signed-URL endpoint** `src/app/api/integrations/daab/documents/signed-urls/route.ts` — Bearer auth; for each requested `document_id`, look up `file_path` (validate `status='analyzed'`), `supabaseAdmin.storage.createSignedUrl('documents', file_path, 900)`. Reuse `src/lib/supabase/admin.ts`.
4. **Service token** — issue a DAAB-scoped token (env secret, e.g. `DAAB_SYNC_TOKEN`), validate in both routes with `timingSafeEqual` (a small shared helper, modeled on `secretOk` in `apollo/phone-webhook/[secret]/route.ts`). Rotatable. Not `service_role`.

> **No Supabase migration, no VIEW, no RLS role, no data movement** for Option A. AAAA reads its own DB and mints signed URLs from its own service-role storage access.

## 4. DAAB components

### 4.1 Go (`ennam.kg.go`)
- **Migration `000076`** (latest is 000075 — the old plan's 000071 is stale). `.up`+`.down`:
  - extend `source_connections.source_type` CHECK to include `'aaaa'` (currently `jira|google_drive|local_upload|satellite_api`);
  - add `source_connections.credential_encrypted BYTEA` (AES-256-GCM AAAA service token);
  - create **sync-state table** `aaaa_synced_document`: `connection_id uuid FK→source_connections ON DELETE CASCADE, document_id text, content_hash text, state text CHECK(state IN ('pending','ingested','failed')), draft_node_id uuid NULL, failure_reason text NULL, last_attempt_at timestamptz, UNIQUE(connection_id, document_id)`. This is the **source of truth for sync progress** (dedup + retry), NOT the AAAA cursor. (Reintroduced — dropping it in the first draft broke the incremental/retry story; see §6.)
- **`DraftSourceType`** — add const `aaaa` (`internal/models/draft_node.go`).
- **`source_connections.config` JSONB** carries `{ aaaa_base_url, aaaa_project_id }`; service token → `credential_encrypted` (encrypt via `internal/crypto` `Encrypt`, `KG_ENCRYPTION_KEY`).
- **Draft-create endpoint** — the worker currently only has `update_draft_content` (updates an EXISTING draft; upload pre-creates the draft in Go). AAAA-sync has no pre-created draft, so add `POST /api/v1/projects/{projectId}/draft-nodes` → create a pending draft `{title, source_type:'aaaa', content_raw, content_format, source_url, properties}` → `{id}`, reusing `internal/store/draft_node.go` Create. (This is the piece the old planB called out and the first draft dropped.)
- **Implement `Sync`** (`internal/handler/source_connection.go:208` — currently 501): require admin role, load connection, publish `aaaa_sync` message `{connection_id, daab_project_id, aaaa_project_id}` to the ingestion queue, return `202 {status:"enqueued"}`. `last_synced_at` advanced on completion (store `Update`).
- **Sync-state store** — CRUD for `aaaa_synced_document` (`UpsertSyncedDoc`, `GetSyncedDoc(connection_id, document_id)`, `ListFailed(connection_id)`) used by the worker via the Go API (httpx) or directly.
- **Wiring** (`cmd/kg-server/main.go`) — inject publisher + encKey into the source-connection handler (mirror existing credential-handling services).

### 4.2 Python worker (`ennam.kg.python`)
- **`DocSourceClient` Protocol** (`ingestion/adapters/doc_source.py`) — transport-agnostic (see §5):
```python
class DocRef:  # dataclass from a contract row
    document_id: str; project_id: str; file_name: str; doc_type: str | None
    mime_type: str; size_bytes: int; content_hash: str; updated_at: str

class DocSourceClient(Protocol):
    def list_documents(self, project_id: str, cursor: str | None) -> tuple[list[DocRef], str | None]: ...
    def get_signed_urls(self, document_ids: list[str]) -> dict[str, str]: ...
    def download(self, signed_url: str, dest: Path) -> None: ...
```
- **`AaaaHttpDocSource`** impl — httpx (already a dep; no Supabase client) to the two AAAA endpoints, `Authorization: Bearer <token>` (token fetched from Go, decrypted).
- **`handle_aaaa_sync(msg)`** dispatched in `worker.py` `handle_message` on `msg["type"]=="aaaa_sync"`:
  - `list_documents` (loop cursor — cursor is an **optimization only**; correctness comes from the sync-state table) → per-doc try/except:
    1. **dedup via sync-state:** `GetSyncedDoc(connection_id, document_id)` → if `state='ingested'` AND `content_hash` matches → **skip**. Else (new / hash changed / `state='failed'`) → process. (This is what makes failed docs retry-able and re-list safe — see §6. `get_canonical_document_by_source` in `run_batch` remains a second, ingest-time safety net.)
    2. mark `aaaa_synced_document` row `state='pending'`.
    3. `get_signed_urls([document_id])` (small batch, minted just-in-time vs 15-min TTL) → `download` to `tempfile`.
    4. `extract_file_text(tmp)` + `extract_structured_fields_for_file(tmp)` (Plan A).
    5. **create draft** via the new `POST /draft-nodes` (content_raw + content_format + `source_url` back-link + `properties.structured_fields` + `properties.aaaa_document_id`) → `draft_id`.
    6. `run_batch(daab_project_id, [draft_id], batch_id=f"aaaa:{document_id}")` → graph node + back-link.
    7. `UpsertSyncedDoc(state='ingested', content_hash, draft_node_id)`; on exception → `state='failed', failure_reason=…` (does NOT stop the batch).
    8. **delete tmp (try/finally).**
  - **No-persist:** use `tempfile`, do NOT route through `handle_extract_upload`/`KG_UPLOAD_DIR`. **Orphan-sweep** on worker start.
  - **Back-link `source_url`** = canonical AAAA document link (e.g. `https://aaaa.ennam.vn/projects/{project_id}?tab=documents`, or a doc-deep-link if available) — decide exact URL in plan (OQ-2).

### 4.3 Next.js (`ennam.kg.next`)
- **AAAA card** in `src/components/sources/connection-bar.tsx` (beside `local_upload`), status from `useSourceConnections`.
- **Connect dialog** — admin-only: `aaaa_project_id` + AAAA service token (+ base URL, prefill) → `POST /api/kg/projects/{id}/connections {source_type:'aaaa', config, credential}`.
- **Sync button** when Connected → `POST …/connections/{connId}/sync`; show `last_synced_at`.

## 5. Adapter-first = reversibility to B (the whole point)

The ingest/OCR/chunk/graph pipeline depends only on `DocSourceClient`. Switching to Option B later = write one new impl `SupabaseViewDocSource` (reads a shared Supabase registry table) + point config at it; **the pipeline is untouched**. Guarantees:
1. All source symbols stay behind the adapter (no Supabase/httpx symbol leaks into ingest).
2. The endpoint contract columns (§2) are **exactly** the future registry table columns.
3. The idempotency key `(document_id, content_hash)` is identical for A and B → no re-ingest churn on switch.
System #3 onboards the same way: implement `DocSourceClient` against its own source.

## 6. Idempotency · no-persist · isolation
- **Sync-state table `aaaa_synced_document` is the source of truth** for what's ingested — NOT the AAAA cursor. Key `(connection_id, document_id)` + `content_hash`. Dedup = "row `state='ingested'` and `content_hash` matches → skip". Re-sync when `content_hash` changes.
- **Cursor is an optimization, not correctness.** The list is (re)scanned each sync (metadata is cheap); the sync-state table decides skip / ingest / retry. This resolves the earlier contradiction: a keyset cursor alone would move past a **failed** doc and never retry it — the sync-state table retries every row not in `state='ingested'` regardless of cursor position. (A watermark/cursor may still be kept to shrink the scan, but failed rows are always reconsidered.)
- **No-persist:** temp download → delete (try/finally) + orphan-sweep; graph node keeps `source_url` only (view original via a fresh signed URL on demand). Never `KG_UPLOAD_DIR`.
- **Per-doc isolation:** one doc's failure (404/expired/OCR error) → log + `state='failed'` + continue; retried next cycle (state≠ingested); never fails the batch.
- **Retry:** endpoint 5xx/timeout → backoff, retry the page (list is idempotent).

## 7. Tenancy (per-project — supersedes the old locked-corpus model)
1 DAAB project ↔ 1 AAAA project via the `source_connections` row (`UNIQUE(project_id, source_type)` ⇒ one `aaaa` connection per DAAB project). `aaaa_project_id` in `config` is the routing key; docs land in the DAAB project whose sources page created the connection. (Old spec's single admin "corpus-project" is dropped; per-project fidelity is now a first-class requirement.)

## 8. Security
- **Scoped Bearer service token**, not `service_role`; rotatable; encrypted at rest in DAAB (`credential_encrypted`, AES-256-GCM). Token leak = read to analyzed docs of the queried project(s) only — **state the blast radius in the plan; do not assume zero.**
- **Signed URLs** short-lived (15 min), minted on demand — the list response never carries live credentials.
- **Endpoint = versioned coupling** (path `/daab/`), not zero coupling — AAAA can refactor its DB behind it, but the JSON contract is a published interface.

## 9. Non-goals (this iteration)
- ❌ Option B (shared Supabase registry/VIEW) — deferred, `backlog/daab-doc-sync-planB-future`.
- ❌ DAAB reading Supabase Postgres or Storage directly; DAAB holding any Supabase credential.
- ❌ Storing binaries on DAAB; token-level OCR changes (Plan A is done, reused as-is).
- ❌ Auto-sync / webhook (pull-on-trigger only — CTO: "chạy sau / khi trigger").
- ❌ Multiple AAAA projects → one DAAB project (UNIQUE constraint; 1:1 only).

## 10. Success criteria
- Admin connects AAAA on a DAAB project's Sources page, clicks Sync → analyzed docs of the mapped AAAA project ingest into **that** DAAB project.
- Idempotent (no re-OCR on unchanged `content_hash`); incremental (cursor); per-doc isolation (one bad doc doesn't stop the batch).
- Temp files gone after each doc (orphan-sweep verified); no binary persisted on DAAB.
- DAAB holds no Supabase credential; only an encrypted AAAA service token.
- Back-link `source_url` resolves to the AAAA document.
- Switching to a `SupabaseViewDocSource` later requires no change to the ingest pipeline (adapter boundary holds).

## 11. Open questions
- **OQ-1 (content_hash — near-required):** the list response NEEDS a content signal for pre-download dedup. Preferred: AAAA adds a `content_hash` column (sha256 at upload). Alternatives (both worse): endpoint fetches Storage `eTag` per doc (extra calls), or DAAB downloads-all-then-hashes (wastes signed URLs + bandwidth, weakens no-persist). Pick in plan; default to the column.
- **OQ-2 (back-link URL):** exact AAAA document deep-link vs project-tab URL vs Supabase storage path.
- **OQ-3 (service token issuance):** where AAAA stores/validates the DAAB token (env vs a small tokens table) + rotation procedure.
- **OQ-4 (which docs):** confirm filter = `status='analyzed' AND analysis IS NOT NULL` matches "files AAAA selected to analyze" (user Q1).

## 12. Future — Option B migration (backlog)
Tracked in `backlog/daab-doc-sync-planB-future`. Trigger to revisit: org **deliberately commits** to Supabase-as-shared-data-plane AND ≥2 consumers (LAAM + #3) need cross-platform doc metadata. Then: create a purpose-built **shared registry table** on Supabase (projection populated by AAAA on analyze-complete, reliable dual-write/outbox + backfill), grant DAAB a scoped read role (`security_invoker` VIEW) + a Storage RLS policy for self-served signed URLs; DAAB adds `SupabaseViewDocSource` (adapter swap only). Do NOT relocate AAAA's internal `documents` table (FK cluster) — use a registry projection.

---

## Appendix — verified facts (2026-07-15, file:line)

**AAAA (`am-ai-agents`):** `documents` in `am_ai_db` (Prisma), NOT Supabase (README `local-postgres-vs-supabase-split`; `.env.example` `@localhost:5500/am_ai_db`; live Supabase public schema empty). Model `prisma/schema.prisma:91-129` (`@@map("documents")`); `DocStatus{uploaded,processing,analyzed,failed}` schema:36-41; `analysis Analysis?` optional 1:1. Storage bucket `documents` private/50MB/[pdf,docx,xlsx,zip], RLS on, role `authenticated`, path `documents/<uid>/`. No `content_hash` on documents. `/api/integrations/*` convention + `[secret]` machine-auth exist; `supabaseAdmin` + `createSignedUrl` (`src/lib/supabase/admin.ts`, `documents/[id]/signed-url/route.ts`). Two-phase upload (`ingestDocument`, `/api/documents/process`). Supabase URL `https://nicrcubktflnwdkhotut.supabase.co`.

**DAAB:** `source_connections` model `ennam.kg.go/internal/models/source_connection.go:20-34`; store CRUD `internal/store/source_connection.go` (Create:23, GetByID:68, ListByProject:86, Update:115); `UNIQUE(project_id, source_type)` (mig 000048:17); CHECK allows `jira|google_drive|local_upload|satellite_api` (000048:5, 000049:56). **Sync 501** `internal/handler/source_connection.go:208-210`, route `:52` `POST /api/v1/projects/{projectId}/connections/{connId}/sync`, wired `cmd/kg-server/main.go:634/649/654/660`. **Latest migration 000075** → new = **000076**. UI `sources/page.tsx:20` `useSourceConnections`; `connection-bar.tsx:73/94`. Worker `worker.py:184` `handle_message` on `msg["type"]`; httpx `KGClient(settings.go_api_url, go_api_key):77`; **no Supabase client in Python**. OCR (done) `ingestion/adapters/files.py`: `extract_file_text(path:Path)->tuple[str,str]:18`, `extract_structured_fields_for_file(path)->dict:117`. Ingest: `run_batch` `engine.py:87`; dedup `get_canonical_document_by_source(project_id, source_type, source_id, content_hash)` `engine.py:123`; back-link `source_url` `pipeline/nodes.py:42,63-64`; bypass `KG_UPLOAD_DIR` for no-persist. Crypto `internal/crypto/aes.go` Encrypt:14/Decrypt:35, `KG_ENCRYPTION_KEY`.
