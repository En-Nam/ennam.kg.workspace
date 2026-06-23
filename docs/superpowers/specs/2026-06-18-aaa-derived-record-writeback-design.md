# Design Spec — AAA Derived-Record Write-Back (IMP-010)

**Date:** 2026-06-18
**Status:** Approved (design — node model R2) — pending implementation plan
**Requirement:** `ennam.kg.requirements/documents/improvements/IMP-010-aaa-masterrecord-writeback-tools.md`
**Ecosystem:** `thiet-ke-ecosystem-laam-daab-aaa.md` §3.1 (write-back diagram), §3.2 Luồng 3/4, §4.2.2 (MasterRecord = node type), §4.4 (Phase C), §5 (MasterRecord Schema contract)
**Builds on:** BA-031 (closed-vocab graph), IMP-008 (write-class gating), BA-029 (transport/auth)

---

## 1. Problem

AAA (the Master Record pipeline) is an **MCP satellite** of DAAB. In **Phase C** it must write its generated Master Record back into the KG so the ecosystem loop closes:
- **Forward (Luồng 4):** from a Master Record, trace the documents it was built from.
- **Reverse (the PO's ask, *"tài liệu này được tính toán vào MC nào"*):** from a document/chunk, find which records consumed it.

The ecosystem doc is explicit (4 places): the Master Record is written back as **its own graph node** with `derived_from` edges to what it was built from — not as properties on an existing node.

### Naming conflict (resolved: R2)
BA-031 already shipped a node type literally named **`master_record`**, but it means something **different** from the ecosystem's MasterRecord:

| | BA-031 `master_record` (shipped) | Ecosystem MasterRecord (AAA Phase C) |
|---|---|---|
| Meaning | "A resolved, de-duplicated **entity** record merging multiple extractions" (`config.yaml:637`) | A per-Project deal record AAA computes |
| Required | `canonical_name`, `subtype` ∈ {person, organization} | a record about a Project, built from documents |
| Origin | BA-031 Pass-2 entity resolution | AAA pipeline |

They collide on one name. **R2** (chosen; R1 = rename BA-031's node was rejected as a higher-risk migration on shipped code): introduce a **new, generic `derived_record` node type** for AAA's Master Record (and future satellite-computed records), leaving BA-031's `master_record` untouched. This honors the ecosystem doc's *structure* (record-as-node + `derived_from`→evidence) while avoiding a rename.

### Why generic (`derived_record`, not a name pinned to AAA)
The PO requires the write-back surface to be reusable by future satellites (valuation, legal study, matching). Modeling **each computed record as its own node** makes records from different systems **naturally distinguishable** (one node per build, attributed by `source_system`/`subtype`) — strictly better than collapsing onto a shared anchor and disambiguating via edge metadata. AAA is simply the first consumer (`subtype = master_record`, `source_system = aaa`).

## 2. Principles honored

- **DAAB is the graph/index, not a document store (§2.2):** the **full record content stays in AAA** (`EntityProfile.masterRecord`). KG holds only the anchor node + a lightweight `summary` + `record_ref` (back-pointer) + provenance edges.
- **Reuse over new mechanism:** edges are written with the **existing `kg_link`** tool; the node uses the **existing** node create/update store path + the UpdateService merge fix. No new edge tool, no new relation types.
- **Provenance throughout (§2.4):** `derived_record → derived_from → {project, entities}` and `derived_record → evidence → {document_chunk, …}` make both the forward and reverse traversals graph-native.
- **Idempotent writes (ecosystem §7):** AAA/LLM may retry — the upsert is keyed and the edge write is 409-idempotent.
- **Simplicity (AGENTS Rule 2):** one new node type + one write tool + config whitelist. No speculative columns; content duplication avoided.

## 3. Architecture

```
AAA Phase C: built MasterRecord for Project P from docs/chunks
        │
        ▼
 kg_upsert_derived_record(title, subtype="master_record",          ── MCP tool, WRITE-class → client confirm
                          source_system="aaa", record_ref=<EntityProfile.id>, summary?, project_id?)
        │  upsert keyed on (project, source_system, record_ref)        idempotent — retry-safe
        ▼
 [Go upsert endpoint] find derived_record by (source_system, record_ref)
        │  found → UpdateNode (merge props, UpdateService node-reader fix)
        │  none  → CreateNode (node_type=derived_record)
        ▼  returns document_id (the derived_record node id)
 AAA writes provenance with the EXISTING kg_link tool (write-class):
        kg_link(derived_record → derived_from → project P)
        kg_link(derived_record → evidence → document_chunk c1, c2, …)   ← Gate-1 whitelist must allow these
        │
        ▼
 Reverse-usage (the PO's view) — NO new read tool:
        kg_get_neighbors(chunk c1, direction=inbound)  → [derived_record(s)]
        each attributed by node.properties.source_system / subtype
```

### 3.1 The `derived_record` node
- **Fields:** `title` (req), `subtype` (req — record kind, e.g. `master_record`), `source_system` (req — e.g. `aaa`), `record_ref` (req — external id, the AAA `EntityProfile.id`; idempotency key), `summary?`, `provenance?`.
- **Content boundary:** the rich MasterRecord JSON lives in AAA; `record_ref` is the back-pointer. KG never duplicates it.

### 3.2 Provenance edges (ecosystem chain, made self-contained)
- `derived_record → derived_from → [project, person, organization, event, location, artifact, concept, document_ref]` — what the record was built from.
- `derived_record → evidence → [document_chunk, document_ref, artifact]` — **direct** chunk-level citations.

> **Verified provenance-model note:** in BA-031 only three node types are `evidence`-edge sources (`document_ref`, `artifact`, `master_record`), all targeting `[document_ref, artifact]`; `document_chunk` is **not** an `evidence` target anywhere. The ecosystem doc's `entities → evidence → chunks` leg is realized in BA-031 as the mandatory node **`provenance[]` field**, not as edges. So IMP-010's reverse query relies on the **direct `derived_record → evidence → document_chunk` edge** added here — self-contained, not dependent on a non-existent entity→chunk edge leg. (Adding `document_chunk` to the three existing entity-`evidence` rules is optional cleanup, out of scope.)

## 4. Node-type registration — ALL gates (the load-bearing risk)

Registering a closed-vocab node type touches multiple gates; missing any one breaks at **runtime**, not build (lesson: IMP-007 `document_chunk` missing the `search:` block → `/query` 500). Verified gate checklist:

| Gate | File (verified) | Change |
|------|-----------------|--------|
| Migration `node_type` CHECK | `db/migrations/000067_add_derived_record.up.sql` (next free number) | Extend `knowledge_nodes_node_type_check` to include `'derived_record'` (mirror 000061) |
| Node schema | `config/config.yaml` → `node_types:` | `derived_record` block: `required: [title, subtype, source_system, record_ref]`, fields incl. `summary`, `provenance` |
| **Search block** | `config/config.yaml` → `search:` | `derived_record: { text_search: [title, summary], filterable: [subtype, source_system], sort_fields: [title, subtype] }` — **without this `/query` 500s** |
| Edge whitelist | `config/config.yaml` → `edge_whitelist:` | `derived_record` source rules (§3.2) + `document_chunk` as an `evidence` target |
| Type const + valid set | `internal/config/types.go` | `NodeTypeDerivedRecord` const + `ValidNodeTypes[...] = true` (drives `/query` filter at `query.go:113`, `resolution_candidates.go:101`) |
| Handler filter allowlists (**3 hardcoded, verified present**) | `query.go:237`, `neighbors.go:151`, `search.go:187` | Add `"derived_record": true` where AAA filters — **required for `neighbors.go`** (reverse-usage may filter `node_types=[derived_record]`) |
| Regression test | `internal/filter/validate_test.go` | New `TestNewValidationContext_DerivedRecord_HasSearchConfig` (mirror the `document_chunk` test) |

> config.yaml is read at **startup** (not hot-reloaded by `air`) — restart kg-server after editing.
>
> **Pre-existing inconsistency (verified, flag don't fix):** the three filter allowlists are hardcoded and out of sync with `config.ValidNodeTypes` — `query.go`/`neighbors.go` list only the original 6 types; `search.go` lists 11. BA-031's own entity types already can't be used as `node_types` filters there. IMP-010 adds `derived_record` only where FR-5 needs it; consolidating the three maps onto `config.ValidNodeTypes` is a separate backlog cleanup, out of scope.

## 5. The write tool — `kg_upsert_derived_record`

- **Surface:** routed write tool (`internal/bridge/schema.go` schema + `client.go` `toolRoutes` entry, `RouteWrite`) → a Go upsert endpoint. Params (lean): `title`, `subtype`, `source_system`, `record_ref` (req); `summary?`, `project_id?`.
- **Backing endpoint (new):** `POST /api/v1/projects/{projectId}/derived-records` — an **upsert keyed on `(project_id, source_system, record_ref)`**, distinct from the create-only `POST /api/v1/nodes` (`node.go:23`, the `node_type`-discriminated path the `kg_store_*` tools share). Logic:
  1. `SELECT` a `derived_record` node where `properties->>'source_system' = $ AND properties->>'record_ref' = $` (project-scoped).
  2. found → `UpdateNode` (merge — **UpdateService node-reader fix** so prior `summary`/provenance are not wiped).
  3. none → `CreateNode` (`CreateNodeParams{NodeType:"derived_record", …}`, `node.go`/`store/node.go:33`).
  - Returns the node id (the `derived_record`'s `document_id`) for AAA to attach edges to.
- **Idempotency (race-safe):** a **partial unique index** (NOT a table `UNIQUE` constraint — Postgres requires `CREATE UNIQUE INDEX` for JSONB-expression + partial predicates; mirrors the existing pattern, e.g. migration 000016 `(project_id, lower(name)) WHERE deleted_at IS NULL`) in the same migration:
  ```sql
  CREATE UNIQUE INDEX idx_derived_record_key
    ON knowledge_nodes (project_id, (properties->>'source_system'), (properties->>'record_ref'))
    WHERE node_type = 'derived_record';
  ```
  (`knowledge_nodes` has no `deleted_at` — it uses a `status` enum; the partial predicate is `node_type` only.)
  so concurrent retries cannot create duplicates even under a TOCTOU race; the endpoint treats a unique-violation as "update the existing".
- **Confirm + auth (IMP-008):** classified **write** → client confirm-gated; AAA uses a **write-scoped** credential, not the read-only Qwen profile.

### 5.1 Edges via the existing `kg_link`
Provenance edges are written with the **existing `kg_link` tool** — this IMP only adds the §3.2 whitelist rules (config + Gate-1 validation). `kg_link` is already 409-idempotent on a duplicate edge (AAA treats 409 as success), and its edge `metadata` is persisted (`knowledge_edges.properties JSONB`), available if a future need wants per-edge attribution beyond the node's own `source_system`.

## 6. Tool-count impact (corrected)

The IMP-010 requirement doc says "invariant `schemas == routes + 2`" — that framing is outdated. The **real** invariant (verified, `e2e_tools_test.go`) is `len(schemas) == len(ListToolNames) + len(localToolNames)`. Current count is **40** (`schema_test.go:53`, post-IMP-009). `kg_upsert_derived_record` is a **routed** write tool → +1 schema, +1 routed name → **41**; the invariant stays balanced. Bump the `40` literal to `41` and add a presence test.

## 7. Reverse-usage query (FR-5) — no new read tool

Once the `derived_record → evidence → document_chunk` and `→ derived_from → project` edges exist, existing read tools answer the reverse view:
- `kg_get_neighbors(chunk_id, direction=inbound)` → the `derived_record`(s) citing that chunk; each attributed by `properties.source_system` / `subtype`.
- With `node_types=["derived_record"]` filter → requires the `neighbors.go` allowlist entry (§4) or it is rejected as invalid.
- `kg_traverse` for multi-hop (record → project → other records).

## 8. Error handling

- Upsert with a missing required field (`title`/`subtype`/`source_system`/`record_ref`) → Gate-1 schema validation 400.
- `kg_link` to a non-whitelisted target (e.g. `derived_record → evidence → person`) → Gate-1 reject (the whitelist intentionally excludes entities from `evidence`; they belong under `derived_from`).
- Duplicate edge → 409, idempotent (no duplicate written).
- `/query?node_type=derived_record` before the `search:` block exists → 500 (the gate this spec is built to prevent; AC live-tests it).

## 9. Testing strategy

- **Gate regression:** `TestNewValidationContext_DerivedRecord_HasSearchConfig` (the search-block gate) + a live `/query?node_type=derived_record` → 200 (not 500).
- **Upsert idempotency (the core invariant, Rule 9):** create then re-`upsert` same `(source_system, record_ref)` → one node, merged properties (prior `summary`/edges intact); concurrent double-upsert → one node (partial unique index).
- **Whitelist:** `kg_link(derived_record → evidence → document_chunk)` and `→ derived_from → project` accepted; `→ evidence → person` rejected.
- **Reverse query:** inbound `kg_get_neighbors` on a cited chunk returns the record, attributed; with `node_types=[derived_record]` filter accepted (allowlist).
- **Write-class:** Qwen read-only profile does not auto-approve `kg_upsert_derived_record`.
- **Count:** `schema_test.go` 40→41 + the e2e invariant holds.

## 10. Scope boundaries (recorded, not dropped)

- **AAA-side logic** — generating MC content, the `generate_master_record` trigger AAA exposes for LAAM — AAA-owned (ecosystem §4.4), out of scope.
- **Renaming BA-031's `master_record`** (entity-merge) — deliberately untouched (R2).
- **Enriching the `project` node in place** (option a) — rejected; records are their own nodes.
- **MasterRecord field-schema / templating per project type** — ecosystem §8.3, AAA concern (content stays in AAA).
- **Edge-materializing the entity→chunk `evidence` leg** — broader BA-031 provenance-modeling change, out of scope (the direct `derived_record → evidence → chunk` edge suffices).

## 11. Open questions

- **OQ-1:** idempotency key storage — `properties.(source_system, record_ref)` + partial unique expression index (chosen above, no extra column) vs a dedicated column. *Recommended: the expression index (no schema column churn) for v1.*
- **OQ-2:** does `derived_record` need a `project_id` scoping column beyond the `derived_from → project` edge? *Recommended: the column already exists on every `knowledge_nodes` row (project-scoped); the edge is the semantic link, the column is the tenancy filter — both present, no new work.*
- **OQ-3 (CTO Office):** confirm R2 against ecosystem §5 "MasterRecord Schema" contract ("AAA đề xuất, DAAB phê duyệt") — `derived_record(subtype=master_record)` is DAAB's approved shape; sign-off so the literal `MasterRecord` name divergence is intentional.
- **OQ-4:** should the upsert endpoint live under `/projects/{projectId}/derived-records` (REST-resource style, matches uploads) or be folded into the `node_type`-discriminated `POST /nodes` with upsert semantics? *Recommended: a dedicated `/derived-records` endpoint — the keyed-upsert behavior differs from the create-only `/nodes` path, and conflating them risks changing `kg_store_*` semantics.*
