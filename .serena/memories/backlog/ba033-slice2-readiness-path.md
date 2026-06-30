# Backlog — BA-033 Slice 2 readiness path (AAAA-independent, post local-upload)

**Filed:** 2026-06-29 · **Gate A empirically measured 2026-06-29 → RED (structural).** Supersedes the blocking framing in `mem:decisions/ba033-slice2-deferred` (analysis still valid; this is the actionable re-entry path). **Branch:** `task/implement_docs_sync`.

## Key change: corpus seeding no longer needs AAAA
- **Local upload feeds the OCR pipeline directly** → seeding no longer depends on AAAA/Supabase. Path: `POST /api/v1/projects/{projectId}/upload` (`ennam.kg.go/internal/handler/ingest_upload.go`) → `ennam.kg.python/.../ingestion/adapters/files.py` (tiered pypdf→Tesseract `vie`+RapidOCR, VN-normalize — shipped).
- ⟹ **planB Supabase connector = DEPRIORITIZED**, off critical path (only needed for automated pull of the 216 Supabase docs).

## ⚡ Gate A — EMPIRICALLY MEASURED (2026-06-29, :5433) → RED, structural
Corpus grew since the deferral: now **~176 documents across ~5 projects** (big new project `592c7ff7…` = 145 docs / 2681 nodes; old Định An `a0000000…` = 687 nodes). Nodes: 1793 concept, 840 chunk, 533 section, 176 document, 28 architecture. **4648 edges total.**

**The ONLY edge types in the whole DB:**
- `mentions`: document→concept (1793) + document_section→concept (1484) — a **bipartite** doc↔concept graph.
- `contains_section`: document hierarchy (1371).
- **concept↔concept = 0 · `related_to` (FR-001 chunk-similarity) = 0 · entity↔entity = 0.**

⟹ **Community detection has NOTHING to cluster** (concept subgraph = 1793 singletons). The bigger corpus did NOT help — the gap is **edge TYPE (entity↔entity), not node count**. This is more fundamental than OQ-033-8 (concept include/exclude is moot when concepts have no inter-concept edges).

**A path EXISTS but is a NEW prerequisite (not in code):** derive a **co-occurrence projection** (concept↔concept edge when co-mentioned in a section). Measured potential: **~11,523 co-occurrence edges over 1774 concepts** (avg ~13 degree → dense/clusterable); **82.9% of concepts span >1 section**.
⚠️ Risk: avg **11.87 concepts/section** + 82.9% ubiquity ⟹ likely an **"entity-blob hairball"** (ubiquitous concepts connect everything → poor community separation — same root cause as Slice 1 NO-GO). The projection MUST be weighted/pruned (TF-IDF-style weights or drop ubiquitous concepts), then community quality re-measured before trusting it.

## Slice 2 gates — BOTH must pass before building
### Gate A — Empirical (corpus/graph). Currently RED (no entity↔entity edges).
Prerequisite to even make it measurable: build an entity↔entity edge layer — cheapest = deterministic **co-occurrence projection** from existing `mentions`; alternatives = BA-031 relation extraction, or BA-033 FR-001 chunk-similarity links (`document_chunk related_to document_chunk`, 0 today). THEN measure density/clustering + community quality (watch the hairball).
### Gate B — Product (named consumer). RED, NOT unblocked by local upload — deepest blocker.
`kg_global_retrieve`/community-summary have **no valid caller**: LAAM (Qwen 8B) forbids LLM-summary-on-read; AAAA multi-tenant forbids cross-deal global. Candidate that fits constraints: a **DAAB-internal admin "global themes" dashboard** (human-facing, not 8B, not cross-deal). Also need a **runnable falsifiability gate**.

## Steps (ordered)
1. **NEW prerequisite (build):** entity↔entity edge layer — start with deterministic co-occurrence projection (concept↔concept from shared-section mentions), weighted/pruned to avoid the hairball.
2. **Gate A re-measure:** density/connectivity + community-formation quality on the projected graph (+ cross-doc retrieval sanity). Empirical go/no-go.
3. **(parallel) Gate B:** decide a real consumer (e.g. admin global-themes dashboard) + write the falsifiability gate. No consumer ⟹ STOP.
4. Only if **A and B both green** → build Slice 2: `community` node type + `member_of`/`summarised_as` edges (OQ-033-1 migration + config edge rule) + batch Leiden/Louvain jobengine job + one summary/cluster via BA-009 + `kg_global_retrieve` REST+MCP (FR-002/003/005).

## Re-entry conditions (deferral decision — all 4)
coherent corpus + **entity↔entity edges (NEW — currently absent)** + resolve OQ-033-8 + named consumer + runnable falsifiability gate.

## See also (other unblocked DAAB work, not Slice 2)
- `mem:backlog/daab-kg-search-sessions-followups` — **`monitoring` scope decision** to let LAAM consume `kg_search_sessions` cross-user. Highest-value unblocked keystone item, independent of Slice 2.
- `mem:backlog/agent-context-retention-followups` · `mem:backlog/sse-block-ordering-bug` (P1).
- DAAB Phase-1 keystone (RBAC + retention/ranking + kg_search_sessions) = COMPLETE; branch not merged to main.
