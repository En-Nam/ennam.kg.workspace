# RAG Citation & Document Navigation Surface (Phase 1) — Design Spec

**Date:** 2026-06-16
**Status:** IMPLEMENTED + VERIFIED (2026-06-16). FR-1 (`kg_get_document` + `document-meta` endpoint) shipped
with a security fix (project-access check + no `stored_path` in response). FR-2 (`stored_path` on hub) now also
works after fixing the underlying platform bug (`UpdateService` was built without a node reader → partial
updates replaced properties; fixed by wiring `WithNodeReader`). Both verified E2E.
**Affects:** BA-002 (MCP bridge), BA-025 (Document Decomposition & Retrieval), LAAM (consumer)
**Untouched (shipped):** hybrid RRF + `multilingual-e5-small` 384-dim (IMP-005)

---

## 1. Goal

Let LAAM/AAA produce **detailed, source-cited answers** from the KG, over the already-shipped
retrieval stack — by adding a **document-citation lookup** (`document_id` → filename + source) and
**persisting the file reference** on ingest — WITHOUT changing the embedding/retrieval system.
(A browsable navigation outline is deferred — see §13 — because the existing `document_tree` is unusable for it.)

## 2. Background — Why embedding is NOT in scope (decision record)

The investigation started as "build a RAG layer / swap the embedding model." Evidence redirected it.
This section records the decision so it is not re-litigated later.

### Embedding model: keep `multilingual-e5-small` (384-dim)

| Evidence | Result | Implication |
|----------|--------|-------------|
| Length of all 79 `document_section` rows (corpus-wide; 63 of them in the Cảng Định An doc) | 91% < 2000 chars; median 561; max 3744 | Long-context advantage (BGE-M3/Jina) barely applies to the real corpus |
| Retrieval eval recall@5 VI (e5-small, N=3) | **3/3 in top-5** | e5-small is **good enough for Vietnamese** |
| Eval EN→VI cross-lingual (N=3) | recall 0 | The only weak spot — **not a current requirement** (user confirmed) |
| Production compute | **CPU Fargate, no GPU** (`python:3.12-slim`, no GPU in terraform) | A 570M model (BGE-M3/Jina) ≈ 200-500ms/query → degrades UX |
| DB constraint | pgvector `vector(384)`, AWS RDS managed | BGE-M3 1024-dim would force a column migration |

**Caveat (fail loud):** the eval is N=3 per language — a smoke test, not a benchmark; ground-truth
labels are judgment; EN recall=0 assumes cross-lingual retrieval is wanted, which it currently is not.

### Model comparison (parked for the future)

| Model | Dim / Migration | Weight (CPU latency) | License | Note |
|-------|-----------------|----------------------|---------|------|
| **e5-small** (current) | 384 / none | 118M (~30-80ms) | MIT | Baseline, sufficient for VI |
| **gte-multilingual-base** | 768 but MRL→384 / **none** | 305M (~100-250ms) | **Apache-2.0** | ⭐ Future option #1 if an upgrade is ever justified |
| Cohere embed-multilingual-light-v3 | 384 native / none | API (fast) | Commercial API | Privacy concern (data leaves the network) |
| Jina v3 | MRL→384 / none | 570M (~200-500ms) | CC-BY-NC ⚠️ | Heavy + commercial self-host license |
| BGE-M3 | 1024 / **migration** | 570M (~200-500ms) | MIT | Heaviest, needs migration — last resort |

→ **Decision: keep e5-small.** Embedding is not the bottleneck; see §3 for what actually is.

## 3. Current state (AS-IS — verified on the live stack)

| Fact | Evidence | Implication |
|------|----------|-------------|
| `kg_search` (hybrid) returns `properties.content` inline | live probe: keys `content, summary, line_start, line_end, document_id` | **Content is NOT missing** — no content tool needed |
| Sections are short (median 561, 91% < 2000 chars) | DB query on `knowledge_nodes` | Returning content inline does not bloat context (except ~9% long sections) |
| `kg_search` returns `document_id` = hub UUID, **not** the document name | live probe | Citing the source needs an **N+1 call** (search → get hub → read title) |
| Hub `document` node: `title` = filename; `source_url`/`stored_path`/`source_id` are **empty** | DB: properties only hold `document_tree`, `section_count` | **No link to the physical file**; only the filename via title |
| REST `GetDocumentStructure` returns `properties.document_tree` **verbatim** | `internal/handler/document.go:37` + live probe of the tree | ⚠️ The tree is a **nested outline with synthetic ids** (`node_id: "sec-0001"`, **not** the real section UUID), each entry **embeds the full section `summary`**, and uses `line_num` (single). It does **NOT** correlate with `kg_search` (which returns real UUIDs) and is **bloated**. → Do **NOT** wrap it for citation; return trimmed hub metadata instead. |
| `kg_search` already returns, per section: real UUID, title, `line_start`/`line_end`, `document_id` | live probe (§3 row 1) | For citation, LAAM is missing **only the document filename/source** — not a section list |
| 33 MCP tools (31 HTTP-proxy + 2 local-execution), none for document navigation | `internal/bridge/schema.go` (`schema_test.go:49` asserts 33), routes in `client.go` `toolRoutes` | No way to navigate a document |

→ **The real gap:** (1) no way to resolve a section's `document_id` (hub UUID) → **filename + source** for citation
(today needs an N+1 `kg_get_node` on the hub), and (2) the hub has **no persisted file reference**
(`source_url`/`stored_path` empty). **Not** missing content, **not** embedding quality, **not** a navigation
outline (the existing `document_tree` is unusable for that — see the row above; deferred to Future).

## 4. Decisions (CTO-approved: D1-A + D2-A)

> Both decisions are **locked** to the recommended options (CTO approval, 2026-06-16). The tables are kept
> as a record of the alternatives considered and why they were rejected.

### D1 — How to package citation
| Option | Description | Assessment |
|--------|-------------|------------|
| **D1-A (recommended)** | Add one MCP tool `kg_get_document` (backed by a new trimmed `document-meta` endpoint — §6); LAAM calls it once per document to get the citation, **leaving `kg_search` untouched** | Lowest risk; does not edit shipped `search.go`; citation metadata only |
| D1-B | Enrich `kg_search` directly: join `document_title` into each result | Convenient for LAAM (1 call) but **edits the live `search.go`** → regression risk on hybrid |

### D2 — What "link to the real file" means
| Option | Description | Assessment |
|--------|-------------|------------|
| **D2-A (recommended)** | Citation = logical reference: `{document_title (filename), section_title, line_start/end}`. Backfill `source_url`/`stored_path` onto the hub at ingest so the source is citable | Sufficient for "cite the source"; lightweight |
| D2-B | Also store + serve the **downloadable physical file** (S3/disk) via a new endpoint | Much larger; only if downloading the original file is actually needed |

> The spec implements **D1-A + D2-A** (locked).

### Field semantics — `stored_path` vs `source_url` (resolves CTO condition 2)

Verified from `internal/service/file_upload.go:179` — `StoredPath = <project_id>/<upload_id>/<filename>`,
a **relative internal filesystem path** under `storageRoot` (resolved by `ResolveStoredPath`). It is **NOT**
a public URL and **NOT** a clickable link.

| Field | What it is | LAAM/end-user use |
|-------|-----------|-------------------|
| `stored_path` | Internal relative storage path (server-side) | **Audit / server-side retrieval only — never rendered as a clickable link to end users** |
| `source_url` | External URL, only when the source provided one (e.g. `satellite_api`, or a user-supplied URL) | May be shown as a clickable link **when present**; often empty |
| `document_title` (hub `title`) | The original filename | **The human-readable citation anchor** — always present |

→ End-user citation is built from **filename + section + line range** (D2-A). `stored_path` rides along for
audit/backend use; LAAM must not surface it as a link. This is exactly why D2-A (logical reference) is the
recommended option — no clickable-file expectation is created.

## 5. Scope

### In scope (D1-A + D2-A)
- **FR-1** — MCP tool `kg_get_document`: resolves a hub `document_id` → citation metadata `{node_id, title (filename), source_url, stored_path, section_count}`. **No `document_tree`** (see §6).
- **FR-2** — Provenance: the ingest pipeline persists `stored_path` onto the hub (via draft metadata →
  `build_node_payload`). This required fixing a pre-existing platform bug — `UpdateService` was built without
  a node reader (`main.go:369`), so partial node updates REPLACED properties and the decompose step wiped
  `stored_path`. Fixed by wiring `service.WithNodeReader(nodeStore)` (merge semantics; Gate 2 stays off as no
  update config is wired). Verified E2E: a fresh upload's hub now carries both `stored_path` and `document_tree`.
  Note: `stored_path` is persisted for server-side provenance / future D2-B but is **not** exposed by the API.
- ~~**FR-3** — add `document_title` to `kg_search`~~ — **dropped** (belonged to D1-B; D1-A is locked, so `kg_search` stays untouched).
- **FR-4** — Docs: the LAAM "search → get_document → answer with citation" pattern, **including the graceful-empty citation fallback** (filename + section + lines when `stored_path`/`source_url` are empty).

### Out of scope
- Changing/touching embedding, hybrid RRF, e5-small (shipped).
- A content-returning tool (content is already in `kg_search`).
- Serving the downloadable physical file (D2-B) unless chosen.
- Re-chunking / entity resolution Pass 2 / splitting out an Ingest Core.
- EN→VI cross-lingual query (not a requirement yet — see §13 Future phases).
- **Document navigation outline** (browsing a doc's real sections) — the existing `document_tree` is unusable
  (synthetic ids + bloat) and there is no "sections by `document_id`" endpoint yet; deferred to §13.

## 6. FR-1 — MCP tool `kg_get_document` (citation metadata, NOT the tree)

**Nature:** resolve a hub `document_id` → **lightweight citation metadata**. It must **NOT** return the raw
`document_tree` (synthetic ids + embedded summaries + bloat — see §3). A new trimmed endpoint backs it so the
existing `GetDocumentStructure` contract (BA-025 consumers) is untouched.

**New endpoint:** `GET /api/v1/nodes/{id}/document-meta` → returns hub metadata only (no tree):
```json
{ "node_id": "...", "title": "2026-05-29-cang-dinh-an-deal-report.md",
  "source_url": "", "section_count": 63 }
```

**Security (resolved from a commit security review):**
- **Path-level project-access check.** The ProjectID middleware only validates the header/query project,
  not the node's project — so the handler resolves `middleware.GetDeveloperIdentity` and returns **404**
  (not 403, to avoid a cross-tenant existence oracle) if the caller lacks access to `node.ProjectID`.
- **`stored_path` is NOT returned** by this endpoint. It is an internal server-side file path (IDOR/layout
  disclosure risk) and citation does not need it (D2-A uses filename + section + lines). It is still
  *persisted* on the hub (FR-2) for server-side provenance / future D2-B, just never exposed over the API.

**Tool-count impact (precise — differs from the local-tool case in memory `bridge-tool-count-drift`):**
`kg_get_document` is a **routed HTTP-proxy tool** (it has a `toolRoutes` entry), NOT a local-execution tool.
So both counters move together:
- schemas: **33 → 34** (update `schema_test.go:49` and `handler_test.go:276`, currently `!= 33`)
- routes (`ListToolNames`): **31 → 32** (add to `toolRoutes` in `client.go`; update any hardcoded route-name
  list, e.g. `integration_test.go`'s `TestIntegration_AllToolsRegistered`)
- It is **NOT** added to `localToolNames`, and the `len(schemas) == len(toolNames) + len(localToolNames)`
  assertion (`e2e_tools_test.go:805`) holds automatically since both sides increment.

**Schema (`internal/bridge/schema.go`):**
```
kg_get_document:
  description: "Resolve a document's hub id to its citation metadata: filename, source reference, and
                section count. Use the document_id from a kg_search result's properties to cite the source."
  params:
    document_id: string, required   # node_id of the 'document'/'external' hub (from a section's properties.document_id in kg_search)
    project_id:  string, optional   # falls back to the default project
```

**MCP tool response** = the `document-meta` payload above (small, fixed size — no tree, no per-section summaries).

**Dispatch:** HTTP-proxy tool (like the existing routed tools) — add a route `kg_get_document → /nodes/{id}/document-meta` to `toolRoutes`, NOT a local-exec tool.

> **Why a new endpoint, not wrapping `GetDocumentStructure`:** that endpoint returns `document_tree` verbatim —
> a nested, synthetic-id (`sec-0001`), summary-embedding, potentially huge structure (see §3). Returning it over
> MCP would bloat context and give LAAM ids that don't match `kg_search` results. The new `document-meta`
> endpoint returns only the fixed citation fields. `GetDocumentStructure` is left unchanged (BA-025 still uses it).

> **No `document_tree` size risk in Phase 1:** because the tool does not return the tree, there is no large-outline
> concern. A clean **navigation outline** (real section UUIDs + line ranges) is a separate Future item (§13) —
> it needs a "list section nodes WHERE `document_id` = hub" query, which has **no endpoint today** (verified: 404/405).

## 7. FR-2 — Provenance backfill (persist the file reference)

**Problem:** the hub `document` node currently stores only `document_tree` + `section_count`;
`source_url`/`stored_path` are empty → citation cannot point back to the file.

**Fix in the ingest pipeline:**
- `ennam.kg.python/.../ingestion/pipeline/nodes.py` (`build_node_payload`): when building the hub, also write
  `properties.stored_path` (from the `extract_upload.stored_path` message) and keep `source_url` if present.
- Upload handler `ennam.kg.go/internal/handler/ingest_upload.go` (`ResolveStoredPath`): ensure `stored_path`
  flows into the draft → to Python via the message so it can be persisted on the hub.

**Backfill of old data (DECIDED — resolves CTO condition 1):** a **one-off backfill script runs once before
launch** to set `stored_path`/`source_url` on existing upload-originated hubs (today: the Cảng Định An hub).
This is cheap (corpus is tiny) and gives clean citation UX from day one — no `stored_path: ""` reaching LAAM
for already-ingested documents.

**Graceful-empty rule (mandatory regardless of backfill):** some sources legitimately have **no file**
(e.g. `kg_ingest_node` / satellite memory, `satellite_api` external sources). For these, `stored_path` is
correctly empty and `source_url` may be empty too. The contract is:
- `kg_get_document` always returns the keys, with empty string when absent (never null/missing).
- LAAM **must** fall back to **filename + section + line range** for citation when `stored_path`/`source_url`
  are empty — and must never render an empty value as a link. This is stated in FR-4 (LAAM pattern) and
  tested in §9.

## 8. Citation flow (NotebookLM-style) — after Phase 1

```
1. LAAM: kg_search(query, mode=hybrid)
   → results[]: { id (section), title, properties.{content, document_id, line_start/end} }
   → already has ENOUGH text to answer (content inline)
2. LAAM: for each unique document_id → kg_get_document(document_id)   # dedup, cheap, small payload
   → { title (filename), source_url, section_count }   # stored_path NOT exposed (internal)
3. LAAM answers, citing: "[<document title>, section '<section title>', lines <line_start>-<line_end>]"
   (section title + lines come from the kg_search result; the document title comes from kg_get_document)
```
No retrieval changes; every piece exists after FR-1 + FR-2.

## 9. Testing Strategy

- **Go bridge schema test:** `kg_get_document` registered correctly (param `document_id` required) **and present in `toolRoutes`**; update the count assertions (`schema_test.go:49` + `handler_test.go:276`: 33→34) and the hardcoded route list (`integration_test.go`). The relational assertion in `e2e_tools_test.go:805` needs no change. See §6 for the precise count impact.
- **Go handler test:** new `document-meta` endpoint returns `{title, source_url, section_count}` (no `document_tree`, no `stored_path`); rejects non-hub nodes; empty `source_url` comes back as `""` not null; cross-project caller gets 404.
- **Python unit:** `build_node_payload` persists `stored_path`/`source_url` on the hub (mocked KG client).
- **E2E (live stack):** ingest a file → `kg_search` (gives section title + lines + document_id) → `kg_get_document(document_id)` → assert filename + `stored_path` + `section_count` returned, enabling a full `[filename, section, lines]` citation.
- Go: `make test` (`-race`); Python: `uv run pytest` (mocked).

## 10. Components & Files

| Component | Effort | Files |
|-----------|--------|-------|
| Go: schema `kg_get_document` + count-assertion fixes (33→34) | Small | `internal/bridge/schema.go`, `schema_test.go`, `handler_test.go`, `integration_test.go` |
| Go: route `kg_get_document` → `/nodes/{id}/document-meta` | Small | `internal/bridge/client.go` (toolRoutes) |
| Go: new `GET /nodes/{id}/document-meta` endpoint (hub metadata, no tree; incl. `source_url`/`stored_path`) | Small | `internal/handler/document.go` (+ test) |
| Python: persist `stored_path`/`source_url` on the hub | Small | `ingestion/pipeline/nodes.py` (+ test) |
| Go: pass `stored_path` into the draft on upload | Small | `internal/handler/ingest_upload.go` |
| One-off backfill script for existing hubs (DECIDED §7) | Trivial | one-off admin script |
| Docs: LAAM citation pattern (incl. graceful-empty rule) | Trivial | `BA-002` / README |
| **Total** | **~2-3 days** (with real TDD — tests first) | |

## 11. Acceptance Criteria

1. **Given** a `document_id` from `kg_search`, **when** calling `kg_get_document`, **then** it returns `{node_id, title (filename), source_url, section_count}` — a small fixed payload, **not** `document_tree` and **not** `stored_path` (internal path).
1b. **Given** a caller without access to the node's project, **when** calling `kg_get_document`, **then** it returns **404** (no cross-tenant disclosure).
2. **Given** a **newly** ingested document, **when** inspecting the hub node, **then** `properties.stored_path` is stored (no longer wiped by the decompose update). ✅ Verified E2E.
3. **Given** LAAM answers from `kg_search` + `kg_get_document`, **then** it can cite `[filename, section, lines]` **without** manually calling `kg_get_node` for the hub.
4. **Given** the shipped hybrid/e5 system, **when** Phase 1 is complete, **then** `kg_search`/retrieval behavior is **unchanged** (no regression).
5. **Given** the bridge adds `kg_get_document`, **then** the tool count rises correctly and all cross-check tests are green.
6. **Given** a source with no file (e.g. `kg_ingest_node` memory), **when** calling `kg_get_document`, **then** `source_url` is returned as an empty string (not null/missing), and the documented LAAM pattern cites by filename + section + lines without rendering an empty link.

## 12. Risks

| Risk | Level | Mitigation |
|------|-------|------------|
| New tool breaks count-assertion tests (tool-count drift) | Medium | Routed tool → update count assertions (33→34) + route list per §6; relational e2e assertion holds |
| Old-hub backfill missed → empty citation for old data | Low | One-off backfill script (DECIDED §7) run before launch; graceful-empty rule covers file-less sources |
| Long sections (~9%) return large content inline via `kg_search` | Low | Accepted; if it becomes a problem → handled in Phase 2/3 (re-chunk), not Phase 1 |
| `document.go` change affects BA-025 | Low | Add a **new** `document-meta` endpoint; leave `GetDocumentStructure` untouched |
| `kg_get_document` returns `document_tree` ids that don't match `kg_search` (the original design trap) | — (avoided) | Fixed in design: tool returns trimmed metadata, never the synthetic-id tree |

## 13. Future phases (gated by evidence — not built now)

These are recorded so the roadmap is explicit; each is gated on measured need, not assumption.

- **Phase 2 — Measure, don't guess.** When long / sparsely-headed documents are ingested (contracts,
  100-page specs), run the existing recall@5/MRR eval harness to test whether the 2000-char embedding
  truncation actually hurts recall.
- **Phase 3 — Fix only if Phase 2 proves it.** Prefer **smaller re-chunking while keeping e5-small**
  (no migration) first. A model swap is the last resort; if ever needed, prefer **gte-multilingual-base**
  (Apache-2.0, MRL→384, no migration) over BGE-M3/Jina.
- **EN→VI cross-lingual retrieval** — only if it becomes a real requirement; then label a proper eval set
  before considering a stronger multilingual model.
- **Embedding code source** — code is already well served by graph tools (`kg_traverse`, `kg_get_neighbors`);
  RAG is for prose, so this stays separate.
- **Document navigation outline** — a clean section browser needs (a) a "list `document_section` WHERE
  `document_id` = hub" endpoint (none today), or (b) rebuilding `document_tree` with **real** section UUIDs
  and without embedded summaries. Add when there is a concrete navigation use case.

---

**Next step:** spec approved (CTO, conditions resolved) → `superpowers:writing-plans` to create the implementation plan.
