# DAAB Related Documents / Shared Entities (Step 2) — Design

**Date:** 2026-06-30
**Status:** APPROVED (design) — ready for implementation plan
**Scope:** DAAB (`ennam.kg.go`) — document-level relatedness via shared canonical entities, IDF-ranked, raw (no LLM).
**Parent direction:** the user's validated need — *"how are these 2 documents related?"* / *"which documents relate to doc X?"* — answerable now that entity resolution (1a + 1b) connected the graph cross-document.
**Related:** `mem:backlog/daab-entity-resolution-corpus-rerun`, the 1b spec `2026-06-30-daab-exact-name-hub-merge-design.md`.

---

## 1. Problem

After 1a + 1b, documents are connected through shared canonical entities (measured: 131 documents link to another document via a shared entity; 8647 document-pairs share an entity — up from **0** before resolution). But there is no way to **query** that relatedness: "which documents relate to this one, and *why*?" The graph holds the answer; DAAB must expose it as a raw, provenance-tagged primitive. Synthesis ("what are the themes across these related docs") stays AAA's job — DAAB does **no LLM**.

The trap (from the data): 8647 doc-pairs share *some* entity, and ubiquitous entities ("Tỉnh Trà Vinh" df=29, "UBND tỉnh Trà Vinh" df=62) connect nearly everything. A naive "shares an entity ⇒ related" returns "every document relates to every document" — the entity-blob at document level. Relatedness MUST be weighted by entity rarity (IDF).

## 2. Goals / Non-goals

**Goals**
- A raw, provenance-tagged primitive answering: (a) **2 docs → their shared canonical entities** (+ IDF), and (b) **1 doc → ranked related docs** (by the specificity of shared entities).
- Blob-resistant ranking (a pair sharing one *specific* entity beats a pair sharing only ubiquitous ones).
- A stable MCP/REST contract that survives a future fuzzy-merge (alias collapse) without breaking consumers.

**Non-goals (deferred — see §11)**
- LLM synthesis / "explain the relationship in prose" — that is AAA's job; DAAB returns raw evidence.
- Cross-project relatedness (entities are project-scoped).
- Vector/embedding fusion, RRF, multi-arm retrieval (over-built for shared-entity relatedness).
- Reusing the BA-033 `GraphRetriever.Retrieve` query→chunk path (concluded NO-GO; this is a separate, simpler surface).
- Blessing the ranked doc→docs mode as a production default before the falsifiable quality gate passes and a real consumer exists.

## 3. Established decisions (from 2-agent review + empirical validation)

| # | Decision | Basis |
|---|----------|-------|
| D1 | **New, document-grained store methods** — do NOT reuse `SharedEntityNeighbors` as-is. | Its `df`/`N` count `DISTINCT source_id` over ALL `mentions` source types (document + section + org/event/person entity→entity), so its IDF universe is not "documents" and its output mixes node types. Both reviewers flagged this independently. |
| D2 | **Document-grained IDF, computed directly from `document→concept` mentions** (filter source `node_type='document'`). **No section rollup.** | Verified: `document→concept` mentions are populated (1793 edges / 158 documents). Direct is simpler than the rollup both reviewers assumed. |
| D3 | **Two modes:** pairwise (PRIMARY) `2 docs → shared entities + IDF`; ranked (SECONDARY) `doc → related docs`. | Pairwise is the literal answer to the #1 validated need; ranked is the weaker mode on a single-domain corpus. |
| D4 | **Ranking = max-IDF of shared entities per doc-pair** (tiebreak: count of shared, then sum-IDF). Return the full shared-entity list sorted by IDF. | Max-IDF is blob-resistant (sum accumulates ubiquitous-entity mass on a single-domain corpus). **Empirically validated** (§4). |
| D5 | **Raw, provenance-tagged output; canonical entity IDs as data.** | A future fuzzy-merge changes entity-ID values/scores, never the schema → consumers don't break. No LLM. |
| D6 | **Falsifiable quality gate on the RANKED mode only** before it is blessed as a default. | Don't repeat BA-033 (shipped on an unchecked assumption). Pairwise mode ships raw (deterministic; the caller judges). |
| D7 | **No df-cap / hub-drop / normalization / magic threshold in v1.** | max-IDF + top-K already beats the blob on the data; a min-IDF floor is a *named escalation*, built only if calibration shows pollution. |

## 4. Current-state facts (verified on :5433, 2026-06-30)

- **`mentions` edge source grain:** `document→concept` 1793 edges / **158 distinct documents**; `document_section→concept` 1484 / 125; plus entity→entity (`organization`/`event`/`person`/`concept`/`artifact`→concept, ~163). ⟹ the IDF universe MUST filter source `node_type='document'`; otherwise `N`/`df` are polluted by sections + entity→entity edges.
- **Document-grained df sample:** "CÔNG TY TNHH XÂY DỰNG HÀM GIANG" df=85, "UBND tỉnh Trà Vinh" df=62, a rare entity df=2 → with N≈158, IDF(85)=0.62, IDF(62)=0.94, IDF(2)=4.36. Rare entities dominate.
- **★ Empirical validation of the ranked query** (seed document → top related docs by max-IDF shared entity):

  | related_doc | max_idf | top_shared_entity |
  |---|---:|---|
  | …c44 | 3.88 | UBND tỉnh Sóc Trăng |
  | …e40 | 3.88 | UBND tỉnh Sóc Trăng |
  | …51b | 3.03 | Ban quản lý KKT tỉnh Trà Vinh |

  Top related docs are connected by **specific** entities (IDF 3.88, 3.03), NOT the ubiquitous province (~0.6) — max-IDF ranking is blob-resistant as designed. The falsifiable gate would pass on this sample.
- **Existing infra (reuse the IDEA, not the query):** `service/graph_retriever.go` documents the IDF semantics (`Score = Σ IDF of shared concepts`, L82-88) and a sort/dedup/cap idiom (L259-291); `store/graph_retrieve.go` holds `GraphRetrieveStore` (where the new methods land) + the (universe-unscoped) `SharedEntityNeighbors` CTE pattern (L88-122) to mirror but re-scope. `config.yaml`: `mentions` whitelist (L935-960), `document_section.document_id` (L279-282, the rollup key — not needed given D2 but available).
- **Note on residual aliases:** "UBND tỉnh Trà Vinh" (62) and "Ủy ban Nhân dân Tỉnh Trà Vinh" (32) are still separate (abbreviation alias — fuzzy merge deferred). The entity-ID-as-data contract (D5) means a future fuzzy-merge improves results without a contract change.

## 5. Architecture

```
kg_related_documents (MCP) / REST
  ├─ pairwise mode: (project, doc_a, doc_b) → SharedDocumentEntities
  │     intersect doc_a's & doc_b's mentioned canonical concepts → [{entity_id, name, idf}] sorted IDF desc
  └─ ranked mode:   (project, doc_id, k)     → RelatedDocuments
        find docs sharing ≥1 canonical concept with doc_id → score = max-IDF shared → top-K
        each result carries its top shared entity (+ optionally the shared list)

store.GraphRetrieveStore  (new methods, pure SQL, project-scoped)
  - SharedDocumentEntities(ctx, projectID, docA, docB) ([]SharedEntity, error)
  - RelatedDocuments(ctx, projectID, docID string, limit int) ([]RelatedDoc, error)

IDF universe (both): mentions where source node_type='document' AND target is a non-superseded concept;
  N = COUNT(DISTINCT document) in project ; df = COUNT(DISTINCT document) mentioning the concept ; weight = ln(N/df)
```

Two single-query store methods + a thin handler + an MCP tool. No service-layer pipeline, no embed/expand, no LLM.

## 6. Store methods (`internal/store/graph_retrieve.go`)

Shared IDF CTE (both methods), parameterized by project:
```sql
WITH dm AS (   -- document → non-superseded canonical concept
  SELECT e.source_id AS doc, e.target_id AS concept
  FROM knowledge_edges e
  JOIN knowledge_nodes sn ON sn.id = e.source_id AND sn.node_type = 'document'
  JOIN knowledge_nodes cn ON cn.id = e.target_id AND cn.node_type = 'concept'
                          AND COALESCE(cn.properties->>'merged_into','') = ''
  WHERE e.edge_type = 'mentions' AND e.project_id = $project),
nn AS (SELECT count(DISTINCT id)::float8 AS n FROM knowledge_nodes
       WHERE node_type='document' AND project_id = $project),
idf AS (SELECT concept, ln((SELECT n FROM nn) / count(DISTINCT doc)) AS idf FROM dm GROUP BY concept)
```

### 6.1 `SharedDocumentEntities(projectID, docA, docB)` — PRIMARY
```sql
SELECT a.concept AS entity_id, cn.title AS name, i.idf
FROM dm a JOIN dm b ON a.concept = b.concept
JOIN idf i  ON i.concept = a.concept
JOIN knowledge_nodes cn ON cn.id = a.concept
WHERE a.doc = $docA AND b.doc = $docB
ORDER BY i.idf DESC
```
Returns the canonical entities both documents mention, rarest-first (the literal "how are these 2 related"). Empty list = unrelated.

### 6.2 `RelatedDocuments(projectID, docID, limit)` — SECONDARY (gated)
```sql
SELECT b.doc AS related_document_id,
       max(i.idf) AS max_idf,
       count(*)   AS shared_count,
       (array_agg(cn.title ORDER BY i.idf DESC))[1] AS top_shared_entity,
       (array_agg(a.concept::text ORDER BY i.idf DESC))[1] AS top_shared_entity_id
FROM dm a JOIN dm b ON a.concept = b.concept AND a.doc <> b.doc
JOIN idf i  ON i.concept = a.concept
JOIN knowledge_nodes cn ON cn.id = a.concept
WHERE a.doc = $docID
GROUP BY b.doc
ORDER BY max_idf DESC, shared_count DESC, b.doc
LIMIT $limit
```
`max(idf)` is the blob-resistant ranking key (D4). `top_shared_entity` gives the provenance "why." (A richer variant can return the full shared-entity list per related doc; v1 returns the top one + count.)

Result structs:
```go
type SharedEntity struct { EntityID, Name string; IDF float64 }
type RelatedDoc struct { RelatedDocumentID, TopSharedEntity, TopSharedEntityID string; MaxIDF float64; SharedCount int }
```

## 7. Surface — handler + MCP tool

- **REST** (new `internal/handler/related_documents.go`): `GET /api/v1/projects/{projectId}/documents/{documentId}/related?limit=` (ranked) and `GET /api/v1/projects/{projectId}/documents/{documentId}/shared-entities?with={otherDocId}` (pairwise). Project + document resolved/validated server-side; project-scoped RBAC mirrors existing document handlers.
- **MCP tool `kg_related_documents`** (`internal/bridge/schema.go` + `client.go`, +1 schema/route + the count-drift test bumps per `mem:bridge-tool-count-drift`): input `{document_id (required), with_document_id?, limit?}`; if `with_document_id` set → pairwise shared entities, else → ranked related docs. Output raw + provenance:
  ```
  ranked:   {results:[{related_document_id, max_idf, shared_count, top_shared_entity, top_shared_entity_id}]}
  pairwise: {shared_entities:[{entity_id, name, idf}]}
  ```
  Description states: returns documents related by shared canonical entities, ranked by entity specificity (rare = stronger), raw with provenance, no summarization (synthesis is the caller's job).

## 8. Quality gate (ranked mode only)

Before the ranked `doc → related docs` mode is blessed as a trusted default, run a **pre-registered falsifiable check**: sample top-N ranked pairs across several seed docs; for each, surface the driving `top_shared_entity`. **Pass = the connector is a *specific* entity (not one of the ubiquitous "Tỉnh Trà Vinh"/"UBND tỉnh Trà Vinh"/"Ban Quản lý…"/"Hàm Giang"-as-province-blob) for ≥ a pre-registered X% (e.g. 80%) of sampled pairs.** A blob-dominated top = NO-GO (revisit ranking) — exactly the BA-033 discipline. (The §4 sample already passes; this gate formalizes it on a larger sample.) The **pairwise mode ships without a gate** (deterministic raw evidence).

## 9. RBAC

Project-scoped: both methods take `projectID` and filter `mentions.project_id`/node `project_id`. The handler resolves project + validates the caller's access to it (mirror existing document handlers / the path-project gate). No cross-project surface. Documents are not user-scoped, so no per-user filter (unlike agent_context).

## 10. Performance

The IDF CTE recomputes per query. At current scale (158 docs, ~1500 concept mentions) this is trivial. If a project grows large, the IDF can be materialized (a per-project concept→idf view refreshed on a schedule) — a noted optimization, not v1.

## 11. Deferred — follow-ups

1. **Fuzzy alias merge** (e.g. "UBND tỉnh Trà Vinh" ≈ "Ủy ban Nhân dân Tỉnh Trà Vinh") — improves relatedness; the entity-ID-as-data contract absorbs it without a schema change.
2. **Ranked-mode consumer** — the plausible caller is AAA M&A synthesis (find related deal docs). Build the pairwise primitive now; the ranked mode is built-but-gated until a consumer + the §8 gate.
3. **Min-IDF floor / df-cap** — only if calibration shows blob pollution (named escalation, not v1).
4. **Full shared-entity list per related doc** in the ranked mode (v1 returns the top one + count).
5. **Cross-domain corpus** — document relatedness is low-signal on the single-domain (Trà Vinh) corpus; the feature gains value as the corpus diversifies. The high-signal query here is entity-anchored ("which docs share THIS specific company/permit").
6. **Materialized per-project IDF** (§10) for scale.

## 12. Test plan

**Store (integration, `KG_TEST_DATABASE_URL`/`KG_TEST_DSN` → :5433):**
- `SharedDocumentEntities`: two docs sharing a known specific entity return it with a high IDF; sorted rarest-first; two unrelated docs return empty.
- `RelatedDocuments`: ranks a doc connected by a *specific* entity above one connected only by a ubiquitous entity (blob-resistance — the core test); `top_shared_entity` is the rarest shared one; respects `limit`; superseded (merged) concept nodes are excluded (only canonical participate); IDF universe excludes section/entity→entity mentions (filter `node_type='document'`).
- Determinism: stable order via `(max_idf desc, shared_count desc, id)`.

**Handler (integration + unit):**
- Project-scope: a caller can't get related docs across projects.
- `with_document_id` switches to pairwise; absent → ranked.

**MCP:** schema present + routed; tool-count drift tests updated.

## 13. Files touched (anticipated)

- `internal/store/graph_retrieve.go` — `SharedDocumentEntities` + `RelatedDocuments` + `SharedEntity`/`RelatedDoc` structs (+ integration tests).
- `internal/handler/related_documents.go` (new) — REST handlers + route registration (+ tests); wire in `cmd/kg-server/main.go`.
- `internal/bridge/schema.go` + `client.go` — `kg_related_documents` tool + route (+ count-drift test bumps).
- No migration (read-only over existing graph). No service-layer pipeline. No LLM.
