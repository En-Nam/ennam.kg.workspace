# Design Spec — MCP File Ingest & Linkage (IMP-009)

**Date:** 2026-06-18
**Status:** Approved (design) — pending implementation plan
**Requirement:** `ennam.kg.requirements/documents/improvements/IMP-009-mcp-file-ingest-linkage.md`
**Ecosystem:** `thiet-ke-ecosystem-laam-daab-aaa.md` §3.1 (Luồng 1 ingest), §4.2.3 (MCP conventions, security/ops), §2 (principles)
**Provenance:** Converged from a two-role design debate (Senior Technical Consultant ↔ CTO), both positions re-verified against `ennam.kg.go` / `ennam.kg.python` code. This spec records the converged outcome.

---

## 1. Problem

Satellites (LAAM, AAA) integrate DAAB (Ennam KG) **MCP-only**: an MCP server URL + bearer token, seeing only the **bridge** JSON-RPC surface — never the Go REST API. Today MCP can push **text** (`kg_ingest_node`) but **cannot push a binary file**. The existing file pipeline (`POST /upload` → disk store → async RAG → `stored_path` on a hub node → `GET …/download`) is reachable **only** over the Go REST API a satellite cannot reach.

**Driving scenario (agent-driven):** a user hands a file to the agent in a LAAM conversation and says *"ingest this."* The file bytes are already in the LAAM host (user attachment); the **agent** must be able to express ingest-intent through the MCP tool surface, and the host must be able to move the bytes to DAAB and get back a `document_id` to cite. No model carries bytes (no base64 over MCP).

This is the last gap in the agent-driven RAG vision: **agent asks to ingest a user-provided file → KG RAGs it → index linked to the stored file → original downloadable later.**

## 2. Principles honored

- **Ingest once / single source of truth (§2.2):** drive the *existing* Go pipeline; build no second ingest/RAG/storage. The satellite pushes bytes through to DAAB and gets a `document_id` — it keeps no copy.
- **Loosely-coupled, MCP-only contract (§2.1):** binary travels over **HTTP on the bridge host** (not JSON-RPC); coordination travels over **MCP tools**. The satellite still integrates by one host + one bearer — but the §5 contract must state the new consumer requirement: the *host* (not the model) performs a multipart HTTP POST out-of-band.
- **Design-for-Qwen (§2.3):** tools are ≤3 required params, snake_case, no nested objects. The model only calls tools (intent + poll); it never constructs the multipart request.
- **Provenance throughout (§2.4):** the index ↔ stored-file link (FR-6) makes Luồng 4 traceability reach the original binary.
- **Simplicity (AGENTS Rule 2):** no speculative infrastructure. The debate cut a one-time-token mechanism that closed no real threat (see §6).

## 3. Architecture

```
User gives file F in LAAM chat + "ingest"
        │
        ▼
 [Model] kg_request_file_upload(F.name, project?)   ── MCP tool, WRITE-class → client confirm gate
        │  returns { upload_url }                       (the ONLY confirm checkpoint for uploads)
        ▼
 [LAAM host, holds bytes] POST {upload_url} (multipart + bearer)
        │
        ▼
 [Bridge POST /files]  raw streaming proxy
        │  • reject if scope=readonly  (in-route — MCP write-gate does NOT cover raw routes)
        │  • MaxBytesReader + 413      (bridge-edge DoS cap)
        │  • io.Copy → Go POST /api/v1/projects/{projectId}/upload
        ▼
 [Go pipeline UNCHANGED] store → uploaded_files(draft_node_id) → publish extract_upload → async RAG worker
        │  returns { upload_id, draft_id }
        ▼
 [Model] kg_ingest_status(upload_id)  ── MCP tool, READ-class, poll
        │  processing | done(+document_id) | failed
        ▼
 [Model] kg_get_document / kg_search_chunks → cite; kg_get_document.download_url → open original
        │
        ▼
 [Bridge GET /files/{document_id}] raw streaming proxy
           • HasProjectAccess → 404 cross-tenant
           • resolve document_id → upload → io.Copy ← Go …/uploads/{uploadId}/download
```

### 3.1 Components

| # | Component | Class | Responsibility |
|---|-----------|-------|----------------|
| C1 | `kg_request_file_upload(filename, project_id?, content_format?)` | MCP tool, **write** | Agent's ingest-intent signal + **client-side confirm gate**. Returns `{ upload_url }` (the bridge `POST /files` route). No token, no bridge state. |
| C2 | `POST /files` | Bridge raw HTTP route | Receive multipart, **reject `readonly` scope in-route**, **`MaxBytesReader` cap + 413**, `io.Copy` to Go `/upload`, pass Go's `{upload_id, draft_id}` + error statuses (413/400) back verbatim. |
| C3 | `kg_ingest_status(upload_id)` | MCP tool, **read** | Poll → `{ status: processing\|done\|failed, document_id? }`. Resolved read-side (see §4). New HTTP-proxy tool against a small Go status endpoint. |
| C4 | `GET /files/{document_id}` | Bridge raw HTTP route | **`HasProjectAccess`→404**, resolve `document_id → upload`, `io.Copy` from Go `…/download`. Opaque route; never exposes `stored_path`. |
| C5 | `download_url` on `kg_get_document` | Field on existing tool | Present only when `stored_path` non-empty (BR-007); value = C4 route. Additive, backward-compatible. |

The whole Go upload→store→RAG→download pipeline + the `canonical_document` correlation table are **reused unchanged**.

**Dispatch / tool-count note (verified):** the bridge has two existing dispatch categories — `toolRoutes` (HTTP-proxy → Go, surfaced by `ListToolNames`) and `localToolNames` (handled in-bridge by `LocalIndexHandler`). The count invariant is `len(schemas) == len(ListToolNames) + len(localToolNames)` (`e2e_tools_test.go:805`).
- **`kg_ingest_status`** → routed: add a `toolRoutes` entry hitting a new Go status endpoint. (+1 schema, +1 routed name.)
- **`kg_request_file_upload`** → **bridge-internal** (returns the static `/files` URL + acts as the write-class confirm gate; it does **not** call Go). It fits neither existing category cleanly, so the plan must register it so the invariant still balances — simplest: a small in-bridge handler analogous to `localToolNames` (give it a schema and count it on the non-routed side). (+1 schema, +1 non-routed name.)
Net: 38→40 schemas; both the `schema_test.go:51` literal and the e2e invariant stay green only if each new tool is registered on exactly one side with a schema.

## 4. Data flow — status correlation (OQ-2, converged)

**Read-side resolution using the already-materialized `canonical_document` table — no worker change, no migration.**

Schema (verified):
- `uploaded_files.draft_node_id → draft_nodes` (migration 054); `draft_nodes.status` carries the full lifecycle (indexed, 047).
- `canonical_document.draft_node_id (UNIQUE) → knowledge_node_id` (migration 060), upserted by the worker at RAG completion.

`kg_ingest_status(upload_id)` resolves:
1. `uploaded_files` by `upload_id` → `draft_node_id` (existing `GetByID`).
2. **`done` iff a `canonical_document` row exists for that `draft_node_id`** — it carries `knowledge_node_id` = the `document_id`. (Authoritative success signal; `canonical_document` is written only on success.)
3. Else `draft_nodes.status` → `processing` (or pending-link window where `draft_node_id IS NULL`) / `failed`.
4. **Timeout** (stuck `processing`, dead worker): derived **read-side** from row age (`now() − created_at` vs threshold) — a dead worker cannot write anything, so this is a query-time judgment under any design; worker write-back would NOT buy it.

`GET /files/{document_id}`: reverse via `canonical_document` (`knowledge_node_id → draft_node_id`) → `uploaded_files` → `uploadId`.

**Only new query needed:** `UploadedFileStore.FindByDraftNodeID` (today the store keys on `(source_type, source_id[, content_hash])` only). No worker change, no new columns, no migration.

**Known edge (accept, revisit if it bites):** `uploaded_files.draft_node_id ON DELETE SET NULL` vs `canonical_document` RESTRICT — deleting a draft loses the upload's `failed` linkage. A status column on `uploaded_files` would preserve it; deferred (YAGNI) per debate.

## 5. Security model (converged — server-enforced only)

The confirm-flow (IMP-008) is **client-side only**; a raw HTTP route **bypasses** the MCP scope gate (`makeToolHandler`, `serve.go:262`). Therefore the load-bearing controls are **in the routes**, not the tools:

| Control | Where | Why |
|---------|-------|-----|
| **Reject `readonly` scope** | inside `POST /files` (read the scope `requireBearerV2` resolved) | The route bypasses the MCP write-class gate; this is the real write-gate. **Without it BR-002 silently does not hold.** |
| **`MaxBytesReader` + 413** | bridge edge, before streaming | The bridge is a DoS amplification point. Go's `maxMultipartMemory` is a form-parse buffer, **not** a total-bytes cap. |
| **`HasProjectAccess` → 404** | inside `GET /files/{document_id}` | Without it this is a fresh IDOR bypassing the fix already shipped on `document-meta` (D2-A). |
| **`download_url` opaque; never emit `stored_path`** | C5 | Preserves the D2-A path-leak fix; only a bridge route URL is exposed. |

**No one-time upload token (cut).** With the mandatory in-route `readonly` reject, the upload principal-set is already "anyone with the `full` bearer" — identical to every write tool. The mint tool would be callable by the same principal (a round-trip, not a capability bound); replay/dedup is already handled by `content_hash` + `idx_canonical_document_hash` (060); the `upload_id` audit anchor exists regardless. The token only adds stateful infra + a multi-instance problem. **Cut → OQ-1, OQ-3, BR-003 all evaporate.**

**Confirm boundary:** lives on `kg_request_file_upload` (write-class → client confirm) — the only place a confirm checkpoint can enter the agent loop, since the byte POST bypasses MCP. The model asks to ingest; the host transfers bytes after approval. Qwen read-only profile must not auto-approve it (AC-8).

## 6. What changed vs the IMP-009 requirement doc (corrections, code-verified)

| Item | Doc said | Corrected |
|------|----------|-----------|
| One-time upload token (FR-1 token, BR-003, OQ-1, OQ-3) | keep, scoped token | **Cut** — no residual threat over the in-route readonly check |
| `kg_request_file_upload` | mints scoped token + upload_url | **Kept** as thin write-class **confirm/intent hook**, returns `upload_url` only, **no token/state** |
| BR-006 `reason: extraction_empty` | status `failed` + typed reason | **Not buildable today** — no reason column, worker passes `""`, complete endpoint takes only `{status, knowledge_node_id}`. v1 returns **`failed` (bare)**; typed reason needs an explicitly-scoped worker+schema change |
| `kg_index_source`/`kg_index_status` "async mirror" | the pattern this mirrors | **False analogy** — those are local-subprocess tools (no `toolRoutes` entry). `kg_ingest_status` is a genuinely new HTTP-poll tool |
| Tool count | 33 / 35 / 31+2 | **Base = 38** (`schema_test.go:51` asserts `len(schemas)==38`); +2 tools → **40** (bump the assert). The real invariant (`e2e_tools_test.go:805`) is `len(schemas) == len(ListToolNames) + len(localToolNames)` — **not** a literal "+2". See dispatch note below. |
| OQ-2 correlation | new JSONB `properties->>'draft_id'` lookup OR worker write-back | **Neither** — `canonical_document` already materializes the join; only `FindByDraftNodeID` is new |
| Write-class enforcement | "reused" (assumed) | The MCP scope gate is **structurally MCP-only**; raw routes must enforce in-route (§5) |

## 7. Error handling

- `POST /files`: `readonly` → 403; over cap → 413; Go 400 (unsupported type) / 413 / 5xx → **passed through verbatim** (don't swallow). Stream errors → 502.
- `kg_ingest_status`: `failed` (bare) on RAG failure incl. empty/scanned extraction (fail-loud, BA-030 floor — file stored, no near-empty doc indexed; OCR deferred). Bounded `failed` on timeout — **never infinite `processing`**.
- `GET /files/{document_id}`: unknown/cross-tenant id → 404 (not 403 — don't leak existence); no stored file → 404.
- `kg_get_document`: no `stored_path` → `download_url` omitted (BR-007).

## 8. Testing strategy

- **Unit:** `FindByDraftNodeID`; status resolution (processing/done/failed/timeout) over the `canonical_document` + `draft_nodes.status` matrix incl. the `draft_node_id IS NULL` pending window.
- **Bridge route tests:** `readonly` → 403 on `POST /files`; over-cap → 413; multipart streamed (not buffered); error pass-through; `GET /files` cross-tenant → 404.
- **Tool-count guards:** update `schema_test.go` (38→40) + e2e invariant.
- **Integration (the intent of the feature):** agent-driven flow — `kg_request_file_upload` (confirm-gated) → host `POST /files` → poll `kg_ingest_status` → `done` + `document_id` → `kg_get_document` returns `download_url` → `GET /files/{id}` returns original bytes. Assert the MCP channel carried **no** file bytes.
- **Security regression:** Qwen read-only profile does not auto-approve `kg_request_file_upload` (AC-8); `download_url` never contains `stored_path`.

## 9. Scope boundaries (recorded, not dropped)

- **OCR** for scanned PDFs → own BA (BA-030 OQ-005); fail-loud floor until then.
- **S3 / object store** → `stored_path` contract unchanged, localized swap behind `FileUploadService`; later.
- **Ingest-Core split** → kept in-KG deliberately (ecosystem §4.1); the `stored_path` seam keeps the future split cheap.
- **Typed failure reason** for `kg_ingest_status` → needs a scoped worker+schema change; out of v1.

## 10. Open questions (residual)

- **OQ-A:** does `POST /files` correlate to the agent's prior `kg_request_file_upload` intent (e.g. an `upload_id` echoed as a header), or is the intent tool purely a confirm gate with no data binding? *Recommended: pure confirm gate for v1 (no bridge state); `upload_id` comes from Go's `/upload` response, fed back by the host for polling.*
- **OQ-B:** bridge-specific request timeout for `/files` (large uploads on slow links) vs the existing 60s middleware — confirm the upload route gets a longer/no timeout. *Recommended: dedicated longer timeout on `/files`.*
