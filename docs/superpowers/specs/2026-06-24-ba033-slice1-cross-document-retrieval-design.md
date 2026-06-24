# BA-033 Slice 1 — Cross-Document Retrieval (Design Spec)

**Created:** 2026-06-24
**Status:** Draft (design approved in brainstorming; pending user review before plan)
**Parent BA:** `ennam.kg.requirements/documents/phase8/BA-033-cross-document-graphrag-retrieval.md`
**Author:** business-analyst (synthesised from a CTO ⇄ Staff-Engineer design debate, 2026-06-24)
**Method note:** scope decided via brainstorming Q1–Q5, then refined by a two-role debate (CTO + technical consultant) that converged on the decisions below. Load-bearing claims verified against live code + DB (2026-06-24).

---

## 1. Goal & scope

Deliver the **first usable increment** of BA-033: cross-document retrieval that surfaces evidence a flat semantic search misses, via **chunk-to-chunk similarity links** and a new **graph-aware retrieval tool**. This is BA-033 FR-001 + FR-004, chunk-similarity path only.

### In scope (Slice 1)
- **FR-001** — cross-document chunk-similarity links (`similar_to` edges), built by an admin-triggered batch job.
- **FR-004** — `kg_graph_retrieve`: seed via existing hybrid search → 1-hop `similar_to` expansion → ranked, provenance-tagged bundle. REST endpoint + read-class MCP tool.

### Out of scope (deferred, with re-entry triggers)
| Deferred | Reason | Re-entry trigger |
|---|---|---|
| Entity-mediated bridge (chunk→mentions→entity→…→chunk) | Live entity edges too sparse (`mentions=42, part_of=4`) → near-zero reachable chunk-pairs; the 3-hop path can't complete at sane hop budgets and serves an empty set | entity-edge density ~10× current (low-hundreds of `mentions` across docs sharing entities) |
| Community detection + summaries (FR-002/003) | Graph not yet resolved enough; needs readiness gate (BA-033 OQ-033-2) | corpus resolved (dup-cluster count below threshold) |
| Global / community retrieval (FR-005) | Depends on communities | after FR-002/003 |
| Incremental on-ingest linking (FR-006) | Batch suffices for v1; avoids per-chunk fan-in coordination | after retrieval value proven |
| Community tools (`kg_global_retrieve`, `kg_get_community`) | Depend on communities | with FR-002/003/005 |

### Overrides of the parent BA (flagged)
- **OQ-033-3 → OVERRIDDEN.** Chunk similarity uses a **distinct `similar_to` edge type**, NOT `related_to(origin="similarity")`. Separation-by-construction beats an `origin` filter that every future cluster loader must remember; it also keeps the retrieval query a simple type-filtered JOIN.
- **OQ-033-1 scope reduced.** No DB migration is needed for the edge type: `knowledge_edges.edge_type` has **no DB CHECK** (verified, migration 000052). Adding `similar_to` is a **config.yaml Gate-1 whitelist rule only**. (The `community` node type — which DOES need schema work — stays deferred with FR-002.)
- **Slice 1 is NOT gated by BA-031 resolution readiness.** Chunk-similarity retrieval operates on chunk embeddings, independent of entity resolution. OQ-033-2's readiness gate applies only to the deferred community work, not here.

---

## 2. Verified facts (live code + DB, 2026-06-24)

| Fact | Value | Implication |
|---|---|---|
| `document_chunk` active nodes | 131 | corpus is small |
| …carrying `properties.document_id` | **131/131** | same-doc filter via `properties->>'document_id'` is reliable |
| chunk embeddings in `knowledge_node_embeddings` | **60** | ⚠️ only ~60/131 chunks are embedded → linker/retrieval cover **embedded chunks only**; the rest are invisible to this slice (must be logged, not silently dropped) |
| `knowledge_edges.edge_type` CHECK/enum | **none** | `similar_to` needs only a Gate-1 config rule, no DB migration |
| edge uniqueness | `UNIQUE(source_id, target_id, edge_type)` + `CHECK(source_id != target_id)` | one edge per chunk pair; canonical ordering required |
| existing ANN | `SemanticSearch` over hnsw cosine (`embedding <=> $1::vector`) | linker reuses this; ANN-bounded ~O(n·log n), zero LLM calls |
| existing search | `POST /api/v1/search` hybrid lexical+semantic RRF | provides retrieval seed |

> ⚠️ **Embedding-coverage gap (60/131)** is a real precondition risk. Before/with this slice, confirm why ~71 chunks lack embeddings (likely older open-schema ingest path vs the decompose path). The linker MUST log embedded-vs-total coverage per run; low coverage caps the slice's value and the eval must be read in that light.

---

## 3. Architecture

```
COMPONENT 1 — ChunkLinker (batch, admin-triggered, write)
  for each embedded document_chunk c in project:
    ANN top-(K+slack) over hnsw, node_type='document_chunk', same project,
       exclude c, exclude same document_id            ← cross-doc only
    keep sim >= threshold, take top_k, canonical-order pair (min UUID = source)
    UPSERT similar_to edge {similarity} (ON CONFLICT DO UPDATE)
  → cross-doc similar_to edges in knowledge_edges

COMPONENT 2 — GraphRetriever (query-time, read)
  seed = POST /api/v1/search(query)  → top seed_k chunks + relevance scores
  expand = 1-hop JOIN: seed.chunk --similar_to--> target chunk, surface edge similarity
  rank = score(seed_relevance, edge_similarity); dedup; per-doc cap + round-robin; cap result_k
  → ranked bundle with provenance (which seed bridged to each result)

COMPONENT 3 — kg_graph_retrieve (HTTP + MCP read tool)
  thin surface over GraphRetriever
```

Three units, each independently testable: ChunkLinker (writes edges, no retrieval), GraphRetriever (reads, no writes), the handler/tool (thin I/O).

---

## 4. Component 1 — ChunkLinker (FR-001)

**Trigger:** internal endpoint `POST /api/v1/internal/graphrag/link` `{project_id}` (admin/internal-class; not an agent tool). Runs as a `jobengine` background job.

**Algorithm (per embedded chunk, ANN-bounded):**
1. ANN query over `knowledge_node_embeddings` joined to `knowledge_nodes` where `node_type='document_chunk'`, same `project_id`, `id <> c`, `properties->>'document_id' <> c.document_id` (cross-doc), ordered by cosine, `LIMIT top_k + slack`.
2. Keep candidates with cosine `>= chunk_link_sim_threshold`; take top `chunk_link_top_k`.
3. Canonical-order each pair (lower UUID = `source_id`) to respect the unique constraint.
4. `INSERT ... ON CONFLICT (source_id,target_id,edge_type) DO UPDATE SET properties = {similarity}` — re-runs refresh the score.

**Business rules:**
- BR-L1 — **Cross-document only.** Same-`document_id` pairs are never linked (the `contains_section` hierarchy already relates them).
- BR-L2 — **Over-fetch to survive the same-doc filter.** Fetch `top_k + slack` before filtering; if the candidate pool is exhausted before `top_k` cross-doc hits, log it (under-linking is surfaced, not silent).
- BR-L3 — **Embedded chunks only.** Chunks without an embedding are skipped; the run logs `embedded/total` coverage.
- BR-L4 — **Idempotent re-run.** `ON CONFLICT DO UPDATE` refreshes `similarity`. Orphan policy: a re-run for a project first clears that project's `similar_to` edges whose endpoints no longer clear the threshold (or rebuilds the project's `similar_to` set wholesale) — no stale edges left after re-ingest.
- BR-L5 — **Gate 1.** Edge creation goes through the whitelist; `document_chunk → similar_to → document_chunk` must exist in config.yaml or creation is rejected loud.
- BR-L6 — **Threshold calibration.** `chunk_link_sim_threshold` (0.83) and `chunk_link_top_k` (5) are **starting points**; the first run emits a link-count histogram across candidate thresholds (e.g. 0.78–0.90) and the values are calibrated from that distribution, not hardcoded blind.
- BR-L7 — **No LLM, no graph mutation beyond `similar_to` edges.**

**Config:** `chunk_link_sim_threshold` (default 0.83), `chunk_link_top_k` (default 5), `chunk_link_overfetch_slack` (default e.g. 15).

---

## 5. Component 2 — GraphRetriever (FR-004)

**Seed:** call existing `POST /api/v1/search` (hybrid RRF) for the query → top `seed_k` `document_chunk` hits with relevance scores.

**Expand (1 hop, plain JOIN — no recursive CTE):**
```sql
-- seeds(chunk_id, relevance) from hybrid search
SELECT c.id AS chunk_id, c.properties->>'document_id' AS document_id,
       s.relevance AS seed_relevance,
       (e.properties->>'similarity')::float AS edge_similarity,
       s.chunk_id AS via_seed
FROM seeds s
JOIN knowledge_edges e
  ON e.edge_type = 'similar_to'
 AND e.source_id = s.chunk_id          -- plus the mirror: e.target_id = s.chunk_id
JOIN knowledge_nodes c ON c.id = e.target_id AND c.status='active';
```
(Run both directions of the undirected pair, or query `source_id = ANY(seeds) OR target_id = ANY(seeds)` and normalise.)

**Rank — deterministic, fully specified:**
- BR-R1 — **Blend (multiplicative):** `score = seed_relevance × edge_similarity`. Multiplicative so a weak seed OR a weak edge both drag the result down (an additive blend lets a strong edge off a marginal seed rank too high).
- BR-R2 — **Dedup:** a target reachable from multiple seeds → keep the **max** `score`, record the winning `via_seed`.
- BR-R3 — **Tie-break:** equal score → ascending `chunk_id` (deterministic, test-reproducible).
- BR-R4 — **Per-document cap + round-robin:** group survivors by `document_id`; emit in score order but round-robin across documents, ≤ `per_document_cap` each, until `result_k` filled. This protects cross-document diversity (NFR-276) — one verbose document must not flood the bundle.
- BR-R5 — **Provenance:** every result carries `chunk_id`, `document_id`, `via_seed` (which seed bridged to it), `edge_similarity`, `hop_count=1`. `dropped_count`/`truncated` reported (no silent truncation).

**Config:** `retrieval_seed_k` (10), `retrieval_result_k` (5), `retrieval_per_document_cap` (2), `retrieval_min_similarity` (mirror linker threshold).

---

## 6. Component 3 — `kg_graph_retrieve` surface (FR-007 subset)

`POST /api/v1/retrieve/graph` (read-class) + MCP read tool `kg_graph_retrieve` (HTTP-proxy, ≤3 required params for Qwen portability).

**Request:**
```jsonc
{ "query": "string",           // required
  "project_id": "uuid",        // required (or X-KG-Project-Id header)
  "result_k": 5,               // optional
  "seed_k": 10,                // optional
  "per_document_cap": 2 }      // optional
```
**Response:**
```jsonc
{ "results": [
    { "chunk_id":"…", "document_id":"…", "content":"…",
      "score":0.71, "seed_relevance":0.74, "edge_similarity":0.96,
      "via_seed_chunk_id":"…", "hop_count":1 } ],
  "seed_count":10, "expanded_count":23, "dropped_count":18, "truncated":true }
```
- BR-T1 — read-only; never mutates the graph.
- BR-T2 — `hop_count` is a constant `1` in v1 (free forward-compat: the deferred entity bridge adds 2/3 without a response-shape break).
- BR-T3 — bridge tool-count invariant: adding `kg_graph_retrieve` updates schema/route counts + tests (`schemas == routes + localToolNames`; it is a routed read tool).

---

## 7. Ship gate (the falsifiability requirement)

Semantic search **already** returns cross-document similar chunks; the only defensible added value of this slice is the **marginal "friend-of-a-friend" set** — chunks reached via a `similar_to` hop that a flat query misses. Therefore the gate measures the **marginal set, not aggregate recall**:

- Baseline `B` = `POST /api/v1/search @ result_k=20` for a query set.
- Slice `G` = `kg_graph_retrieve` for the same queries.
- Judge relevance on **`G \ B`** (what graph expansion adds beyond the baseline).
- **SHIP only if:** relevance of `G \ B` ≥ threshold (to be set with the eval) **AND** `|G \ B|` is materially > 0 across the query set.
- If the delta is empty/low-relevance, the slice adds nothing real → **do not ship**; expose a higher `result_k` on `/search` instead.

This gate also replaces the now-cut "Referral→Contact Request via shared entity" acceptance criterion (that AC required the deferred entity bridge).

### Ship-gate execution result (2026-06-24) — VERDICT: NO-GO on current data

The slice was implemented, the linker run, and the gate executed on the live corpus (project `6f5f1680…`, "LAAM Project Test", 60 embedded chunks):

- **Threshold calibration (BR-L6) was done from real data.** At the placeholder `0.83`, the linker produced 66 edges but they were **cross-topic false links** — a query about a port project (*"lợi thế… cảng Định An"*) expanded to **cooking-recipe chunks** at edge-sim ~0.83. Reading the edges across bands showed `multilingual-e5-small`'s noise floor sits ~0.78–0.87 for same-language text; genuine topical similarity only separates at **≥0.90** (top edges 0.94–0.95 correctly linked recipe↔recipe). The default was recalibrated to **0.90** (handler default + `sim_threshold` override).
- **At the calibrated 0.90, the marginal set `G \ B` = 0** on both a topic-covered query (recipe) and the port query: graph-retrieve returned only chunks `/search@20` already returned (1-hop chunk-sim from semantic seeds overlaps semantic search by transitivity), or returned nothing (no cross-doc bridge at 0.90).
- **Verdict: NO-GO** to activate chunk-sim as a default value-add **on this corpus**. This is the spec's own gate working as designed (the CTO-mandated falsifiability check), not a code failure — the implementation is correct, tested, and the response/ranking behave per spec.

**Caveats (why this is not a permanent verdict):** the test corpus is small (60 chunks) and **contaminated** (two unrelated domains — a port project and cooking recipes — in one project), so it cannot fairly evaluate cross-document retrieval. The genuine cross-document value was always expected from the **entity-mediated bridge (deferred)** and from a **coherent multi-document corpus**. The eval is therefore **inconclusive for a real corpus**, with **no evidence yet** that chunk-sim alone beats `/search`.

**Disposition: built-but-gated.** The code ships (committed `38df8b7`, branch `task/implement_mcp`) but `kg_graph_retrieve` is **not adopted as a default retrieval path**. Re-evaluate when (a) a coherent multi-document corpus is available, or (b) the entity-mediated bridge lands. Re-entry = re-run this gate on real data.

### Known gap surfaced during validation
- **BR-L4 edge-prune is NOT implemented.** The linker only upserts; it does not delete edges that fall below the threshold on re-run. Recalibrating from 0.83→0.90 required a manual `DELETE FROM knowledge_edges WHERE edge_type='similar_to'` before re-linking. A wholesale-rebuild (or below-threshold prune) per project must be added before the linker is run repeatedly in any real workflow (S1-OQ3).

---

## 8. Error handling

- Linker: ANN/DB failure on one chunk → log, continue (per-chunk isolation); job summary reports processed/linked/skipped/coverage. Gate-1 rejection → fail loud (config error), do not silently skip.
- Retriever: empty seed (no search hits) → empty bundle, `seed_count=0` (not an error). No `similar_to` edges yet → bundle = seed-only fallback, clearly labelled (so a missing linker run is visible, not a silent empty).
- Tool: validation at boundary (missing query/project → 400).

---

## 9. Testing

- **ChunkLinker (unit, seeded vectors):** cross-doc-only (same-doc pair never linked); top_k cap; canonical ordering (one edge per pair); over-fetch survives same-doc filter; `ON CONFLICT DO UPDATE` refreshes similarity; Gate-1 reject is loud; coverage logged.
- **GraphRetriever (unit, fixture graph):** multiplicative score; dedup keeps max + records via_seed; deterministic tie-break; per-doc cap + round-robin actually diversifies; provenance fields present; seed-only fallback when no edges.
- **Tool (handler):** request validation; read-only (no writes); bridge tool-count invariant.
- **Eval (integration):** the §7 marginal-set gate on a real query set.

---

## 10. NFR mapping (Slice-1 subset)

| NFR | This slice |
|---|---|
| NFR-276 cross-doc retrieval recall | served by per-doc cap + round-robin + the §7 marginal-set gate |
| NFR-277 chunk-link precision | linker threshold calibration (BR-L6) + reviewer check on a `similar_to` sample |
| NFR-281 retrieval latency | 1-hop JOIN + app-side rank; no recursion → well within p95 budget |
| NFR-283 provenance completeness | BR-R5 (every result carries via_seed/document_id) |
| NFR-285 Gate-1 / project scope | BR-L5, project-scoped linker + retriever |

---

## 11. Open questions (Slice-1)

| ID | Question | Default |
|---|---|---|
| S1-OQ1 | Why are only 60/131 chunks embedded? Does the slice need a backfill of embeddings first? | Investigate during plan; if backfill is cheap, do it so the slice has real coverage to evaluate |
| S1-OQ2 | Exact `chunk_link_sim_threshold` / `top_k` | Calibrate from the first run's histogram (BR-L6); 0.83/5 are placeholders |
| S1-OQ3 | Orphan-edge policy on re-run: wholesale rebuild vs targeted delete | Wholesale rebuild of a project's `similar_to` set (simplest correct; cheap at this corpus size) |
| S1-OQ4 | `result_k` default (5) vs (20) | 5 for precision-first bundle; revisit with eval |

---

## 12. Relationship to BA-033

This spec implements **FR-001 + FR-004 (chunk-similarity path)** of BA-033. It **overrides OQ-033-3** (distinct `similar_to` edge type) and **narrows OQ-033-1** (no DB migration; config-only Gate-1 rule). Everything else in BA-033 (community detection, summaries, global retrieval, incremental, entity-mediated bridge) remains deferred per §1. The parent BA-033 doc should have OQ-033-3 annotated as overridden by this slice.
