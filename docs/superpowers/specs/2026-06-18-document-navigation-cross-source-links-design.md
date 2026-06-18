# Design Spec — Document Navigation & Cross-source Links (BA-032)

**Date**: 2026-06-18
**Status**: Approved design (brainstorming → ready for writing-plans)
**Source BA**: `ennam.kg.requirements/documents/phase8/BA-032-document-navigation-cross-source-links.md` (rev. 2)
**Method**: Tech-Consultant ↔ CTO debate (2 perspectives) reconciled against ground-truth code
**Owner**: backend-dev (Go), with a one-line decompose.py follow-up (Python)

---

## 1. Decision summary

| Decision | Resolution | Driver |
|---|---|---|
| Core architecture | **Read-derived on each request** — no new table, no migration, no stored snapshot | Both roles; `document_tree` snapshot is the bug (synthetic `sec-NNNN` ids, stale on re-decompose) |
| Scope split | **BA-032a** (FR-001 outline + FR-002 neighbors + 2 MCP tools) ships **now**; **BA-032b** (FR-003 backlinks + `kg_get_backlinks`) ships **after BA-031** lands edges | FR-001/002 read `contains_section` (exists today via BA-025/IMP-007); FR-003 reads `references_document`/`mentions` (BA-031 produces). Shipping an always-empty backlinks tool is negative value |
| OQ-6 `chunk_count` | **Include** per outline entry | Near-free in the single aggregating CTE; serves UC-002.2 "pick a passage" |
| Outline traversal | **Single recursive CTE** seeded at hub, with parent-linkage projection + SQL `LIMIT` | N+1 (per-section `GetNeighbors`) would blow NFR-268 at 2000 sections |

### Code-grounded corrections to BA-032 (must be applied to the BA text and the implementation)

| # | Severity | Correction |
|---|---|---|
| **D1** | CRITICAL | An `external` node's `referenced_by` is **NOT** structurally empty. `config.yaml:877-881` whitelists `document → references_document → [document, external]`; `external` is a valid **target**, so inbound backlinks populate the moment such an edge exists. Only `references_out` for an external node is empty (no source rule). Rewrite BR-NAV-18, FR-003 AC-187, §4 line 257, glossary line 541, OQ-7. |
| **D2** | INFO (corrected) | Earlier draft claimed re-decomposition soft-deletes old sections, requiring a `status='active'` filter to avoid superposition. **Verified false.** Re-decomposition cleanup is a **hard delete**: `DeleteDocumentSubtree` (node.go:210) physically removes old `document_section`/`document_chunk` nodes + their edges + versions (FKs lack ON DELETE CASCADE), invoked from canonical_document.go:161 on the canonical re-ingest path. There is **no stale-version superposition**, so **no `status` filter is required for correctness**. The existing read path (`GetChunksByDocument`, node.go:296) does **not** filter status — the outline MUST match that convention (no status filter) rather than introduce a deviating one. *Implementation note: confirm the canonical re-ingest flow calls `DeleteDocumentSubtree` before re-decompose; if a future path soft-deletes instead, revisit.* |
| **D3** | HIGH | BR-NAV-26 / NFR-275 ("tool count is downstream, not a criterion") conflicts with R-004. The live assertions `schema_test.go:48` (`len(schemas) != 35`) and `client_test.go:1060` (`RouteRead:12` / `total==33`) are **hardcoded** and go red on +tools. Pick R-004's reading: **the live test update ships in the same PR**; only the cross-doc number reconciliation (BA-002/BA-027/CLAUDE.md) is decoupled cleanup. |
| **D4** | MEDIUM | `document → references_component → [architecture, external]` (config.yaml:871-873) is a second reference-style edge FR-003 silently ignores. Acceptable to scope out, but state the omission explicitly so reviewers aren't surprised. |
| **D5** | MEDIUM | IDOR template = **`GetDocumentMeta`** (document.go:119-124): not-found→404, then `HasProjectAccess(node.ProjectID)`→404, **then** type→400. Do **not** copy the neighbors handler, which trusts caller-supplied `project_id` and scopes only in SQL. |

---

## 2. Architecture

All navigation surfaces are **stateless reads** derived from live `knowledge_nodes` + `knowledge_edges`. No persisted entity, no cache, no migration. Re-decomposing a document changes the next read with no invalidation step (NFR-272).

Every returned `node_id` is a real `knowledge_nodes.id` (UUID) — the same namespace as `kg_search_chunks`, `/traverse`, and citation. The synthetic `sec-NNNN` namespace is never produced (NFR-271 contract test: no JSON string value matches `sec-\d+`).

### Shared building blocks (used by both 032a and 032b)
- **IDOR check** — copy `GetDocumentMeta` order exactly (D5): existence→404, project-access→404, node-type→400.
- **No `status` filter** (D2 corrected) — match the existing `GetChunksByDocument` convention (no status predicate). Re-decompose hard-deletes the old subtree, so there are no stale rows to exclude.
- **Lightweight serialization** (NFR-273) — entries carry identity + structure only (`node_id`, `title`, `node_type`, `line_start`, `line_end`, `level`/`ordinal`); never `summary`/`content`. Body is fetched on demand via `section-content` / chunk content.
- **JSONB casts** — `line_start`/`line_end`/`level`/`ordinal` live in `properties`; the CTE must cast `(properties->>'ordinal')::int`, `(properties->>'line_start')::int`, etc. for `ORDER BY`. Half-open `[line_start, line_end)` is passed through verbatim (config.yaml:288,332 confirm `line_end` exclusive) — never "corrected."

---

## 3. BA-032a — Outline + Neighbors (ship now)

### FR-001 — Document Outline (`GET /api/v1/nodes/{id}/outline`)

**Single recursive CTE** seeded at the hub, reusing the `traversal.go:297-439` pattern:
- Relationship filter `contains_section`; `node_type IN ('document_section')` for the recursive tree (chunks excluded — BR-NAV-06).
- Cycle guard via `path || n.id::text` ARRAY (reuse — do **not** hand-roll a Go visited-set; R-003).
- Parent linkage projected (penultimate `path` element or add `source_id` to projection) so the tree assembles in **one pass**.
- No `status` predicate (D2 — match `GetChunksByDocument` convention; re-decompose hard-deletes stale rows).
- Soft cap as SQL `LIMIT MAX_OUTLINE_SECTIONS` (default 2000); set `truncated:true` when hit (BR-NAV-08).
- **`chunk_count`** per section via `COUNT(*) FILTER (WHERE node_type='document_chunk')` aggregated in the same traversal pass (OQ-6 — include).

Each entry: `{ node_id, title, line_start, line_end, level, chunk_count, children[] }`. Hierarchy shape is **edge-authoritative** (BR-NAV-28); `level` is reported verbatim, `null` when absent. Sibling order: `line_start` ASC, tie-break `node_id` ASC; missing `line_start` sorts last (BR-NAV-05). Hub-type guard: non-hub → `400 NOT_A_DOCUMENT_HUB`.

> **Pre-lock check (OQ-2):** before locking `MAX_OUTLINE_SECTIONS`, verify the largest real document's section count is comfortably below 2000. `truncated` must be surfaced loudly. Trigger for cursor pagination: first real doc within ~50% of cap, or any production truncation.

### FR-002 — Section Neighborhood (`GET /api/v1/nodes/{id}/section-neighbors`)

Input strictly `document_section` (OQ-3) → else `400 NOT_A_SECTION`.
- `parent` = source of the single incoming `contains_section` edge (section or hub). Single-parent is well-founded (decompose.py:118 sets exactly one `source_id`); for the degenerate multi-parent anomaly, **deterministic tie-break (lowest source `node_id`)** rather than 500.
- `children.subsections` = outgoing `contains_section` targets where `node_type='document_section'`, order `line_start` ASC.
- `children.chunks` = targets where `node_type='document_chunk'`, order `(properties->>'ordinal')::int` ASC (BR-NAV-13).
- `siblings` = parent's other `document_section` children, current excluded; same ordering as outline. "Next"/"previous" = adjacent entries in this total order.
- No `status` predicate (D2 — same convention as FR-001).

### FR-004a — Two MCP tools
Register in `schema.go` with routes (`GetToolRoute`) and required-param validation (`ValidateToolParams`); thin `GET` proxies (BR-NAV-24/29, no pagination params):
- `kg_get_document_outline(document_id)` → `/outline`
- `kg_get_section_neighbors(section_id)` → `/section-neighbors`

**Tool-count gate (D3, in this PR):** baseline 35 schemas / 33 routes / 12 read → **37 / 35 / 14**. Update `schema_test.go:48` and `client_test.go:1060` in the same PR. (Cross-doc reconciliation of BA-002/BA-027/CLAUDE.md numbers is the decoupled follow-up.)

### decompose.py follow-up (OQ-1 trigger, ships with 032a)
Once `/outline` is live, **stop writing `document_tree`** in `decompose.py` (new docs carry no synthetic tree). Keep `/document-structure` read path for back-compat until a consumer audit shows zero dependents, then remove (separate change). Log this stop-writing decision now.

---

## 4. BA-032b — Backlinks (ship after BA-031)

### FR-003 — Cross-source Backlinks (`GET /api/v1/nodes/{id}/backlinks`)
Accepts `document`, `external`, `document_section`; `document_chunk` → `400 UNSUPPORTED_NODE_TYPE`.
- `references_out` = outgoing `references_document` (only `document` nodes have these today).
- `referenced_by` = **inbound** `references_document` — populated for `document` **and `external`** targets (D1 — config.yaml:877-881 whitelists `document→external`). This is whitelist-agnostic on the inbound side; populates the instant BA-031 creates any such edge.
- `mentions` = outgoing `mentions → concept` (sources: `document`, `document_section`).
- Whitelisted relationships only; cross-project excluded (`allow_cross_project:false`); empty-but-`200` when no edges (BR-NAV-19). No `status` predicate (D2 convention).
- Must **not** write tests asserting an `external → references_document` source rule exists (OQ-7 / M10) — that tests a non-existent edge and passes falsely.

### FR-004b — `kg_get_backlinks(node_id)` → `/backlinks`. Tool-count gate: 37/35/14 → **38/36/15** (update assertions again in this PR).

---

## 5. Open-question dispositions (final)

| OQ | Disposition |
|---|---|
| OQ-1 | Keep read path; **stop writing `document_tree` now** (032a follow-up); remove `/document-structure` later after zero-dependent audit |
| OQ-2 | Soft cap + `truncated` for v1; **verify largest real doc < cap before locking**; cursor pagination on trigger |
| OQ-3 | Strict `document_section`; hubs use `/outline` |
| OQ-4 | Defer — no score data; optional sort key only if BA-031 emits confidence |
| OQ-5 | Live test update in-PR (D3); cross-doc number reconciliation decoupled |
| OQ-6 | **Include `chunk_count`** (near-free in CTE) |
| OQ-7 | Owned by BA-031; BA-032 stays whitelist-agnostic; no test asserting the rule |

---

## 6. NFR notes
- **NFR-268** (outline <400ms@500 / <1200ms@2000): met **only** via single CTE; per-section loop fails it.
- **NFR-271** (identifier integrity): contract test — every `node_id` parses as UUID + exists; no `sec-\d+` value anywhere in serialized JSON.
- **NFR-274** (IDOR): `GetDocumentMeta` order (D5), 404 not 403.
- **NFR-275**: tools register with required-param validation + route; per D3, the live count assertion is updated in-PR.

## 7. Day-one risks (carry into the plan)
1. N+1 outline traversal → single CTE (highest risk).
2. ~~Stale-version superposition~~ — not a risk (D2 corrected): re-decompose hard-deletes the old subtree, so no stale rows accumulate. Do **not** add a `status` filter.
3. Cycle/orphan → reuse CTE path-array guard; orphan sections reachable via `section-neighbors` but absent from `/outline` (note in docs).
4. Multi-parent anomaly → deterministic tie-break, no 500.
5. `line_start`/`level` nulls are legacy-only (current pipeline always sets them) — keep the deterministic null-sort but don't let the edge case dominate.

## 8. Out of scope / deferred
Creating the edges (BA-031); pagination (OQ-2); backlink ranking (OQ-4); `references_component` navigation (D4); cross-project nav; full removal of `document_tree`/`/document-structure` (later cleanup after audit).
