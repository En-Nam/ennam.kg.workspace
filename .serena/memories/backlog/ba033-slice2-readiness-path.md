# Backlog — BA-033 Slice 2 readiness path (AAAA-independent, post local-upload)

**Filed:** 2026-06-29 · **Supersedes the blocking framing in** `mem:decisions/ba033-slice2-deferred` (that analysis still valid; this is the actionable re-entry path now that corpus seeding no longer needs AAAA). **Branch:** `task/implement_docs_sync`.

## Key change that unblocks the corpus gate
- **Local upload feeds the OCR pipeline directly** → corpus seeding NO LONGER depends on AAAA wiring Supabase. Path: `POST /api/v1/projects/{projectId}/upload` (`ennam.kg.go/internal/handler/ingest_upload.go`) → `ennam.kg.python/.../ingestion/adapters/files.py` (tiered pypdf→Tesseract `vie`+RapidOCR, VN NFC-normalize — already shipped).
- ⟹ **planB Supabase connector = DEPRIORITIZED** (only needed for automated pull of the 216 Supabase docs; manual/script local upload is enough to seed any corpus). Off the critical path.

## Current corpus reality (verified on :5433, 2026-06-29)
- `knowledge_nodes`: 31 `document`, 155 `document_section`, 214 `document_chunk`, **1 project** = the **Cảng Định An** corpus.
- This is the SAME corpus that made **Slice 1 NO-GO** (entity-blob: every doc shares entities) and **Slice 2 defer** (concept-EXCLUDED subgraph = 35 edges / 109 nodes / 36% connected / 70 singletons; ~81% of relations run through `concept`).
- ⟹ "can seed via upload" (✅ mechanism) ≠ "have a corpus that passes readiness" (❌ current one already failed twice).

## Slice 2 has TWO independent gates — BOTH must pass before building

### Gate A — Empirical (corpus/graph). Now testable locally, cheap, decisive.
The gate that killed Slice 1 + Slice 2 twice. Two ways to make the graph dense enough to cluster:
1. **(cheapest, do FIRST) Resolve OQ-033-8 toward "include concept" and re-measure on the existing 31 docs.** Concept-excluded gave 35 edges; since ~81% of relations run through `concept`, the concept-INCLUDED graph may already be dense enough to form meaningful communities. This is analysis only, NO build. Run a density/connectivity + community-formation measure (concept-included) + a small cross-doc retrieval sanity.
2. If still too sparse → **upload more same-domain docs** (more Định An, or another coherent single-domain set) via local upload → re-measure.

### Gate B — Product (named consumer). NOT unblocked by local upload — the DEEPEST blocker.
- `kg_global_retrieve` / community-summary currently have **NO valid caller**: LAAM (Qwen 8B) forbids LLM-summary-on-read; AAAA multi-tenant forbids cross-deal global retrieval (leak by construction).
- Must **define one valid consumer** or do NOT build (YAGNI — twice corpus-failed + no caller).
- Candidate that does NOT violate LAAM/AAAA constraints: a **DAAB-internal admin "global themes" dashboard** (human-facing community summaries, not an 8B agent, not cross-deal).
- Also need a **runnable falsifiability gate** (community-global beats hybrid + entity-neighborhood on corpus-level queries).

## Steps (ordered)
1. **(do first, cheap)** Gate A re-measure: resolve OQ-033-8 = include-concept → measure graph density/clustering + cross-doc retrieval sanity on the current 31 docs. Empirical go/no-go.
2. **(parallel)** Gate B: decide a real consumer (e.g. admin global-themes dashboard) + write the falsifiability gate. No consumer ⟹ STOP.
3. If A weak on current corpus → upload more same-domain docs locally → re-measure A.
4. Only if **A and B both green** → build Slice 2: `community` node type + `member_of`/`summarised_as` edges (OQ-033-1 migration + config edge rule) + batch Leiden/Louvain jobengine job + one community summary per cluster via BA-009 + `kg_global_retrieve` REST+MCP. Per BA-033 doc FR-002/003/005.

## Re-entry conditions (from the deferral decision — all 4)
coherent single-domain multi-doc corpus · resolve OQ-033-8 · named consumer · runnable falsifiability gate.

## See also (other unblocked DAAB work, not Slice 2)
- `mem:backlog/daab-kg-search-sessions-followups` — incl. **`monitoring` scope decision** (decision record + threat model) to let LAAM consume `kg_search_sessions` cross-user. Highest-value unblocked keystone item; independent of Slice 2.
- `mem:backlog/agent-context-retention-followups`. · `mem:backlog/sse-block-ordering-bug` (P1).
- DAAB Phase-1 keystone (RBAC + retention/ranking + kg_search_sessions) = COMPLETE; branch not yet merged to main.
