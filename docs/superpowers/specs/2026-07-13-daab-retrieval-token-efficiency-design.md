# DAAB Retrieval Token-Efficiency — Design Spec

**Date:** 2026-07-13
**Status:** Draft (pending user review)
**Branch:** task/implement_docs_sync
**Related:** Gap #3 in `mem:backlog/daab-retrieval-quality-gaps-postfix`; evidence `other_projects/daab-sim-consumer/findings-rerun.md`; FR-001 GraphRAG.
**Provenance:** Synthesized from a 2-round adversarial review (CTO/platform-owner ⇄ RAG consultant). Two debate premises were corrected against source (see §6).

---

## 1. Problem

A simulated MCP consumer (M&A analyst over the Cảng Định An deal) hit two token-efficiency defects in DAAB's retrieval tools:

1. **`kg_graph_retrieve` returns bare ids.** Each result is `chunk_id` + `document_id` + scores, no chunk text → every grounded citation forces a follow-up `kg_search_chunks` call (N citations = N round-trips).
2. **`kg_get_neighbors` is heavy.** Full node properties per neighbor → measured **118 KB for 30 neighbors** (~4 KB/row), almost entirely the `properties` JSON blob.

Both tools are exposed over the MCP bridge (`kg_graph_retrieve`, `kg_get_neighbors`), so any new parameter must plumb through `bridge/schema.go` as well as the HTTP handler.

---

## 2. Scope

**In scope**
- **Part A** — inline chunk snippets on `kg_graph_retrieve` (opt-in).
- **Part B** — a `slim` response view on `kg_get_neighbors` (plus a small sort tie-break for coherent paging). Pagination itself (`limit`/`offset`) is already fully implemented and bridge-exposed — no work there.

**Out of scope (YAGNI — explicitly rejected in review)**
- `snippet_chars` consumer-tunable truncation (chunks are fixed ~1 KB; truncating a 1 KB blob is pointless).
- Highlight/query-relevant snippet windows (offset math + OCR-boundary bugs to save a few hundred bytes).
- Any scoring/ranking change; any new MCP tool.
- A graded verbosity enum or a general sparse-fieldset selector (`view` is a two-value knob; a real `fields=[…]` selector is a future feature the naming leaves room for).

One spec, **two independently-shippable parts** (shared driver, shared blast radius: both touch `bridge/schema.go` + an HTTP request struct + the `schemas == routes + localToolNames` invariant, adding **zero** tools). Acceptance criteria are per-part so Part A can merge if Part B needs another round.

---

## 3. Part A — `kg_graph_retrieve` inline snippets

### 3.1 Contract

**Request (added):**
- `include_snippet: bool` — optional, **default `false`**. Idiomatic with the existing `include_headline` / `include_cross_project` / `include_archived` boolean family. "Inline the full chunk content for each result, eliminating a follow-up `kg_search_chunks`."

**Response — each `Result`, only when `include_snippet=true`:**
- `snippet: string | null` — the chunk's full `properties->>'content'`.
  - **Null-discrimination (load-bearing):** when `content` is absent/empty, `snippet` is JSON **`null`** — never `""`, never omitted. The corpus is OCR'd Vietnamese and the `text` column is NULL (canonical text lives in `content`), so legitimately-retrieved chunks *can* have empty content. `""` is indistinguishable from a real empty chunk → silent ungrounded citation; omission forces the consumer to branch on key-presence. Null is the explicit signal.
  - **Defensive byte cap (should-have):** truncate at an internal `maxSnippetBytes` constant (~4 KB, well above the ~1175-char norm) and set `snippet_truncated: true` on that result (default/absent = `false`). Guards against a pathological oversized `content`; **not** a consumer-tunable knob.

**Projection-only invariant (load-bearing):** `include_snippet` MUST NOT change result-set membership, count, or ordering. A null-content chunk keeps its ranked slot with `snippet: null`. Retrieve with the flag on vs off returns an identical `chunk_id` sequence.

**Also surfaced (cheap, already computed):**
- `section_id` — `Result.SectionID` is already serialized (`omitempty`) in parent-child mode; it is the parent-context handle a consumer uses to escalate to section-level context without us inlining parent text. Keep it; do **not** add a query to populate it in flat mode (the always-present parent handle there is `document_id`). This is the cheap half of parent-child grounding for OCR-split chunks.
- `EntityResult.title` — add `title` to every `entity_neighbors` element **unconditionally**. `EntityResult` currently carries only `NodeID/NodeType/SharedEntityCount/Score`; in entity/hybrid mode the consumer cannot label or decide on an entity without a round-trip — the exact anti-pattern Gap #3 exists to kill. Entities get `title` always; they get **no** `snippet` (they are not chunks; a "content" field would be meaningless).

### 3.2 Implementation

- **After** the result set is built, deduped, sorted, and **capped** (`result_k`, `per_document_cap`), batch-fetch content for the ≤`result_k` surviving chunk ids via a new store method:
  ```
  ChunkContentByIDs(ctx, projectID, ids []string) (map[string]string, error)
  ```
  Fetch **all** surviving result ids uniformly (both hop-0 seeds and hop-1 expanded) in this one batch — do **not** special-case seeds from their in-memory `Properties`. Uniform fetch is simpler (KISS, one code path) and avoids depending on whether the seed's `Properties` projection includes `content`. Fetching after the cap bounds it to ≤`result_k` lookups (one query, not N+1, not fetch-before-cap).
- **SECURITY (CRITICAL — hard blocker, §5).** The SQL is project- and type-scoped:
  ```sql
  SELECT id, properties->>'content'
  FROM knowledge_nodes
  WHERE project_id = $1 AND id = ANY($2) AND node_type = 'document_chunk'
  ```
  The upstream ids are already project-scoped, but this codebase has a documented IDOR history (IMP-009 `/files` pinning, BA-015 GenerateKG escalation); a new by-id content read path re-scopes defensively. The `node_type` predicate additionally prevents a caller-supplied id from pulling a non-chunk node's content.
- Bridge: add `include_snippet` to the `kg_graph_retrieve` tool schema + the HTTP request struct.

### 3.3 Total-payload bound

Max snippet payload = `result_k × maxSnippetBytes` cap (≤ result_k × ~1.2 KB in practice; e.g. result_k=20 → ≤ ~24 KB). Bounded by construction because the fetch runs after the `≤result_k` cap.

---

## 4. Part B — `kg_get_neighbors` slim view (+ paging tie-break)

### 4.1 Contract

**Request (added):**
- `view: "full" | "slim"` — optional, **default `full`** (current behavior byte-identical). Idiomatic with the existing `mode` string-enum. Invalid value → **400** (fail loud, no silent fallback). **This is the only new parameter in Part B.**

**Pagination is already complete — no work.** `limit` (default 50, max 200) + `offset` are already implemented in the store (`ORDER BY edge_created_at DESC LIMIT/OFFSET`), the HTTP handler, **and the MCP bridge schema** (`schema.go` lines ~1365/1372). The consumer's 30-neighbor / 118 KB case was pure per-row size (the `properties` blob), not row count — so `slim` is the actual fix. The only paging-related change here is a **sort tie-break** (§4.2) for correctness under tied timestamps; it is optional-but-recommended, not required for the token win.

**Response — `slim` view, frozen field set (9 fields):**
```
id, project_id, node_type, title, status, scope, edge_id, edge_type, direction
```
- **Dropped in slim:** `properties`, `edge_properties`, `version`, `created_by`, `created_at`, `updated_at`, `session_id`.
- `project_id` and `scope` are **retained** (contra the consultant's first-round drop): `include_cross_project=true` is a shipped capability, so cross-project neighbors are a real returned case; without their disambiguators slim mode would be *incorrect*, not just lossy. A UUID + short enum are negligible against the 118 KB (which is the `properties` blob).
- **`edge_weight` is NOT added** (contra the consultant's round-2 hoist). That hoist assumed `kg_get_neighbors` traverses the chunk `similar_to` graph; it does not. Its edge whitelist is `relates_to/impacts/supersedes/fulfilled_by/depends_on/blocked_by/implements/about`, and those edges carry no weight scalar in `edge_properties` (verified empty; only `similar_to` — outside this tool's scope — carries `{"similarity":…}`). An always-null `edge_weight` is speculative generality. If these edges ever carry a weight, add it then.
- `full` view = current behavior, unchanged.

The 9-field list is **frozen in this spec** so future additions to `NeighborNode` do not silently leak into slim.

### 4.2 Implementation

- Handler maps each `store.NeighborNode` → a slim DTO before marshalling (the 118 KB is MCP-serialization tokens; DB transfer is local/negligible, so a handler-level projection is the low-risk fix — no SQL change needed for slimming).
- **Stable paging:** the store currently sorts `ORDER BY edge_created_at DESC` with no tie-break, so `offset` paging can repeat/skip rows across calls when timestamps tie. Add a deterministic tie-break (`edge_created_at DESC, edge_id`). This is the only store-SQL change in Part B.
- Bridge: add `view`, `limit`, `offset` to the `kg_get_neighbors` tool schema + ensure the HTTP request struct fields are wired (limit/offset already exist on the struct).

---

## 5. Error handling & security

- **`ChunkContentByIDs` project+type scoping is a CRITICAL acceptance gate**, with a cross-project isolation test (seed a chunk in project B, assert its content is absent from a project-A `include_snippet=true` retrieve even when its id is supplied). Ships with the control or does not ship.
- **`view` invalid value → 400**, never a silent fallback to `full`.
- **`snippet` null-discrimination** is a correctness contract, not cosmetics — tested explicitly.
- **Projection-only invariant** for `include_snippet` — tested by comparing result ordering flag-on vs flag-off.
- No new auth surface on Part B (reuses the existing neighbor RBAC scope resolution).

---

## 6. Corrections to the review (verified against source)

Both reviewers were sharp but assumed `kg_get_neighbors` behaves like the chunk retrieval path. Source/DB checks corrected two premises, which this spec reflects:

1. **Pagination is fully done — including the bridge.** The CTO claimed the bridge doesn't expose `limit`/`offset`; source shows it does (`schema.go` ~1365/1372), alongside the handler and store (`store/neighbors.go:77,122`). So the entire O3 "add pagination" thread is **moot** — nothing to add. The 118 KB was per-row size, not row count. Part B's only new parameter is `view`; the sole paging-adjacent change is an optional sort tie-break for correctness. The "default-50 breaks consumers" concern is doubly moot (50 is already the shipped default).
2. **No `edge_weight` to preserve.** The consultant's slim `edge_weight` hoist assumed `similar_to` traversal; `kg_get_neighbors` traverses KG semantic edges that carry no weight scalar. `edge_weight` is dropped as always-null.

Everything else is the reviewers' converged consensus.

---

## 7. Testing

**Part A — Go (service/store/handler):**
1. **Snippet fidelity:** flag on → `snippet` byte-equals `properties->>'content'` for a seed (hop-0) result AND an expanded (hop-1) result (proves the after-cap batch fetch joins the right ids).
2. **Null discrimination:** a retrieved chunk with NULL/empty `content` → `snippet` is JSON `null`, result still present, **rank/position unchanged** vs a flag-off run.
3. **Default parity (regression lock):** flag off → response byte-identical to pre-change (no `snippet` key).
4. **Batch, not N+1:** with `result_k=10` over a large expansion, `ChunkContentByIDs` is called **once** with ≤10 ids.
5. **dedup/per_document_cap interaction:** a chunk reached via two seeds yields one result with one correct snippet.
6. **CRITICAL cross-project isolation:** chunk in project B is absent from a project-A `include_snippet=true` retrieve when its id is passed.
7. **Oversized-content guard:** synthetic >4 KB `content` → snippet truncated at cap, `snippet_truncated=true`.
8. **Entity mode:** `include_snippet=true` in entity/hybrid → `entity_neighbors` carry `title`, no `snippet`; no crash, no silent no-op.

**Part B — Go (handler/store):**
9. **Slim field-set exactness:** `view=slim` response has **exactly** the 9 whitelisted keys — assert presence of `project_id`/`scope`/`title` and absence of `properties`/`edge_properties`/timestamps. Table-driven over both directions.
10. **Full parity (regression):** `view=full` (and default) byte-identical to current.
11. **Invalid `view`:** `view=garbage` → 400.
12. **Payload delta:** slim over the 30-neighbor fixture that produced 118 KB → response size drops below a threshold (e.g. < 15 KB).
13. **Stable paging:** two overlapping `limit`/`offset` windows over tied `edge_created_at` return no duplicated/skipped `edge_id` (proves the tie-break).

**Bridge (both):**
14. `include_snippet` (A) and `view` (B) added to `bridge/schema.go` and round-trip through the stdio bridge; `limit`/`offset` remain present on `kg_get_neighbors` (regression — already exposed); unknown params rejected; `schemas == routes + localToolNames` invariant preserved (no tool added).

---

## 8. Success criteria

1. A consumer can retrieve grounded chunk text in **one** `kg_graph_retrieve` call (no follow-up `kg_search_chunks`) via `include_snippet=true`.
2. `snippet` is unambiguous: real text, or explicit `null` — never a misleading `""`.
3. `include_snippet` never alters which/what-order results come back.
4. `ChunkContentByIDs` cannot return another project's chunk content (isolation test passes).
5. `view=slim` on `kg_get_neighbors` cuts the 30-neighbor payload from ~118 KB to < 15 KB while keeping cross-project disambiguation.
6. Neighbor paging (already exposed via `limit`/`offset`) returns coherent, non-overlapping pages under tied timestamps (tie-break fix).
7. All existing `kg_graph_retrieve` / `kg_get_neighbors` behavior is unchanged when the new params are absent (regression locks pass).
