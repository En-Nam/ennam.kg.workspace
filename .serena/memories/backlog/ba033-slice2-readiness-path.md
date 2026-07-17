# Backlog — BA-033 Slice 2 readiness path

**UPDATE 2026-07-16 — `concept`-type exact/case/legal-form duplication is FIXED** (was a contributor to the dup-entity top-hub problem described below). See `mem:backlog/ingestion-ocr-content-loss-bugs` and `mem:checkpoint/concept-dedup-fix-2026-07-16`. `decompose.py` now reuses project-scoped `concept` nodes via a `fold_name`-based key instead of minting one per mention; measured on Dasin: concepts 41→26, 0 exact dupes, cross-document bridge query went from 0 rows to 11 shared concepts. This does NOT resolve semantic near-duplicates (only deterministic case/whitespace/legal-form folding) — the 95 `needs_review` dup-entity hubs described below are a distinct, still-open problem for the 6 resolution-pipeline types (`concept` is explicitly outside that pipeline's scope).

**UPDATED 2026-07-10: OQ-033-8 SETTLED by direct measurement → Gate A GREEN on the CORRECT (concept-excluded) graph.** Supersedes the 2026-07-03 "green" which measured the wrong graph. **Branch:** `task/implement_docs_sync`.

## ⚡ OQ-033-8 SPIKE 2026-07-10 (project 592c7ff7 "Cảng Định An M&A", :5433, Louvain seed 42)
Script: scratchpad `modularity_spike.py` (+ `edges_noconcept.tsv` / `edges_withconcept.tsv`).

BA-033 doc (2026-06-24) recorded the concept-EXCLUDED graph as **35 edges / 109 nodes / 36% connected → "collapses, DEFER"**. **That is STALE — refuted by measurement today:**

| Variant | edges | nodes-in-edges | modularity | non-trivial comms (≥3) | largest component |
|---|---|---|---|---|---|
| **A. concept-EXCLUDED** (BR-002.9 v1 scope: 6 resolved types) | **1493** | **1209** | **0.836** | **73** | 68% |
| B. A minus top-15 generic hubs | 983 | 1008 | 0.955 | 91 | 35% |
| C. concept-INCLUDED (what 2026-07-03 measured) | 2583 | 1957 | 0.832 | 72 | 78% |

**Verdict: OQ-033-8 resolved.** Excluding `concept` does NOT collapse the graph (1493 edges, not 35 — 42×), and modularity is ESSENTIALLY UNCHANGED vs concept-included (0.836 vs 0.832). So BR-002.9's exclusion of `concept` is coherence-FREE — the original OQ-033-8 fear is empirically dead. **Gate A is genuinely GREEN, measured on the right graph.**

**Two real, quantified caveats (do not overclaim):**
1. **Coverage 28%** — only 1209/4300 six-type entities participate in any edge; 117 components, 32% of edge-nodes off the giant component. Community summaries would describe ~28% of entities.
2. **Entity resolution incomplete, and it shows as the TOP HUBS** — top-degree nodes are dup/OCR-mangled entities: `Công ty` (96), `Công ty TNHII Xây dựng Flàm Giang`=TNHH/Hàm Giang (70), `UBND TÍNH TRÀ VINH…` OCR (68), `Cục llàng hải`=Hàng hải (27), `Trị Vinh`=Trà Vinh (22). **These ARE the 95 `needs_review` items.** They distort communities. Pruning them spikes modularity to 0.955 but shatters the graph (largest comp 35%) — a symptom, not a fix.

## Corpus reality (measured 2026-07-10 — corrects "mixed-domain" claim)
DAAB KG is dominated by ONE real single-domain M&A corpus: project 592c7ff7 "Cảng Định An M&A", **8383 nodes / 145 documents** (hợp đồng hợp tác, FS 2022, ĐTM, CV Sở Xây dựng, kho xăng dầu). **The old "recipe/phở theme" is GONE** (query for phở/nguyên liệu/nước dùng = 0 rows). Other projects (dev-project 687, C4K Staging 317) are separate `project_id`s; BA-033 clusters per-project so they never mix. ⟹ The "no coherent single-domain corpus" re-entry blocker is SATISFIED.

## Gate B — Product (named consumer): RESOLVED in principle
**Consumer = AAAA agent via MCP** (architecture CONFIRMED in AAAA's own docs: `am-ai-agents/docs/ecosystem/2026-06-23-aaaa-feedback-on-hermes-allocation.md:43` "Consume DAAB qua MCP — CONFIRMED arch"; `2026-06-04-...md:14,34` KG exposed via MCP, 25 tools). The three old "no valid consumer" reasons are ALL refuted (see `mem:decisions/ba033-slice2-deferred` retraction 2026-07-08):
- AAAA is NOT multi-tenant (per-userId; cross-deal = within-user = not a leak).
- LAAM "no-summary-on-read" does not exist; LAAM has no document corpus anyway.
- "client data never enters KG" = only the INTERNAL (engineering) KG; a separate per-project namespace with hard RBAC isolation is the SANCTIONED mitigation — exactly DAAB's project-scoped g2 isolation. Cảng Định An as its own project is compliant.
- Also doc-specified: DAAB's own dashboard (`GET /api/v1/communities` "(dashboard)", "Community explorer" on Cytoscape BA-010).

## Remaining gates (the honest ones)
1. **Consumer not wired.** AAAA `.mcp.json` = supabase+inngest only; no DAAB. LAAM daab appears only in test fixtures. Architecture agreed, integration NOT built.
2. **Falsifiability gate undefined** — need a runnable criterion ("community-global beats hybrid+entity-neighborhood on corpus-level questions") before building FR-002/003/005.
3. **Coverage 28% + dup-entity hubs** — the 95 `needs_review` items are top hubs distorting clusters; resolving them raises coverage AND coherence for ALL retrieval. **⚡ RESOLVED 2026-07-17 — FR-001-at-scale verdict is now in hand: MARGINAL, not a settled retrieval floor.** Full detail: `mem:checkpoint/fr001-at-scale-2026-07-17`, deliverable `.superpowers/sdd/fr001atscale-task-4-report.md`. Measured live on the real 77-doc Cảng Định An corpus (21 judgement-selected queries, deterministic script, zero LLM in the counting path, human relevance read with a k-cap confound check on every Yes — the same discipline that caught two prior fabricated-measurement runs). Result: `hop1_only_rate` rose sharply vs Dasin (1.0 vs 0.40 — the mechanism fires on literally every query at this density), but `answer_rate` fell sharply (≈0.048 vs Dasin's 0.25, confound-verified) — the mechanism fires constantly but almost never delivers a genuine novel answer (1 confirmed instance out of 88 judged hop-1-only snippets; 2 other plausible Yes candidates were tested and DISQUALIFIED by the confound check, confirming the check works as designed, not a formality). **Implication for gates 1/2 above: FR-002/003/005 (community summarization / global retrieval) must NOT assume `kg_graph_retrieve`'s 1-hop `similar_to` expansion as a settled retrieval floor — it is real but marginal, keep it, do not build on it as load-bearing infrastructure.** Also surfaced: the Task-2 `homogeneous`-class prediction ("expansion adds nothing") failed across all 8 predicted-homogeneous queries at this scale — reported as a finding, not buried.

## ⚡ HARNESS RUN 2026-07-13 + triage — FR-001 is BUILT but UNPOPULATED (operational gap, not build)
Simulated M&A-consumer run (`other_projects/daab-sim-consumer/findings.md`, 15 DD questions on Cảng Định An via DAAB MCP). Scores: Tier-1 single-doc **2.25**, Tier-2 entity **2.5** (existing kg_search + kg_get_neighbors + entity resolution already good), Tier-3 cross-doc **0.5**, Tier-4 corpus **0.33**. Clearest cross-doc win the tools MISSED: Q10 found a real phase-2 area contradiction (14.71ha planning-decision vs 33.6ha 2019 Sở Xây dựng letter) only by manual cross-reading.

**`kg_graph_retrieve` returned `seed_count:0`/`expanded_count:0` on every query. Triaged from DB+source (the consumer couldn't): NOT a bug, NOT a missing feature — the DATA SUBSTRATE was never generated for this project:**
- `document_chunk` nodes: **626 exist, 0 embedded** (`knowledge_node_embeddings` has only entity types here). Seeding = `SemanticSearch over document_chunk` (`graph_retriever.go:133`) → no chunk embeddings → 0 seeds even for verbatim text.
- **`similar_to` edges: 0** in the project. Even with seeds, `ExpandSimilarTo` returns nothing. The FR-001 linker (`POST /api/v1/internal/graphrag/link`, `service/chunk_linker.go`) EXISTS but has never run on this corpus.
- BA-033 **Slice 1 is fully BUILT** (handler `graph_retrieve.go`, service, store, linker, MCP tool). The gap is purely **operational**: the chunk-embed + chunk-link pipeline never ran on 592c7ff7.

**Corrections to the harness (agent couldn't see internals):** `kg_related_documents` + `kg_document_shared_entities` DO exist in the running build (commit `9fe8bdc` 2026-06-30 < server build 2026-07-07) — agent's ToolSearch missed them; Q12 "most central docs" IS answerable with an existing tool.

**⟹ Next action for FR-001 retrieval is CHEAP and is NOT a build:** (1) embed the 626 `document_chunk` nodes for 592c7ff7, (2) run `POST /api/v1/internal/graphrag/link` to populate `similar_to`, (3) re-run harness Q9–Q12 + try `kg_related_documents`. If cross-doc answers land → FR-001 is DONE, just needed data. Only if it still falls short → consider building more.

### ⚡ EXECUTED 2026-07-13 — populate DONE; FR-001 VALIDATED + latent index bug found (see `mem:checkpoint/daab-fr001-populate-2026-07-13`, deliverable `other_projects/daab-sim-consumer/fr001-retest.md`)
Steps 1–3 run. **626/626 chunks embedded** (reembed/backfill are no-ops on already-ingested chunks — used clean script reusing LocalEmbeddingModel+batch endpoint), **1864 `similar_to` edges** (linker edges_upserted=2762). FR-001 core hypothesis **CONFIRMED**: Q9 returns full chủ-trương→quy-hoạch→3×ĐTM approval chain in one call; Q10 co-retrieves BOTH 14.71ha & 33.6ha contradiction docs; `kg_related_documents`+`kg_document_shared_entities` EXIST & work (harness wrongly said missing). **REFINES the prediction — "just needed data" is ~90% true but not clean-DONE:** populating exposed a latent **HNSW post-filter starvation** bug. Seeding = `ORDER BY <=> LIMIT k WHERE node_type='document_chunk'` on a table-wide HNSW index where chunks are only 626/6219 (~10%); at default `hnsw.ef_search=40` entities crowd the seed window → `seed_count:0` for ~2/3 of queries (clean 200, no error). **Fix is ONE LINE, still not a build: `SET LOCAL hnsw.ef_search=400` in the seed query** (ef40→4/12, ef100→8/12, ef400→12/12 incl. all English; ef1600 regresses→tune ~400). Optional filtered chunk index = latency follow-up + needs schema change (`knowledge_node_embeddings` has no node_type col). Cross-lingual = relevance nuance, collapses into same fix. Also: (4) neighbors/traverse return full node props (230K chars/30 neighbors) — a titles/ids-only mode is a cheap high-value ergonomics fix; (5) document duplication (same PDF ingested 2–5× with divergent OCR) inflates counts — dedup pass, separate from 95 needs_review.

## Recommended order (evidence-led)
1. **Wire AAAA to the 25 EXISTING MCP tools** (zero build) — observe whether corpus-level questions actually arise. Consumer contract: `docs/daab-memory-consumer-contract.md`.
2. **Finish 95 `needs_review`** — NOW critical path (spike proved dup entities are top hubs), not polish. DAAB-solo, measurable.
3. **FR-001 + FR-004** (`kg_graph_retrieve`, local graph retrieval) — NOT blocked by OQ-033-8, highest value for an M&A agent.
4. **FR-002/003/005** (community + summaries + global) — Gate A now green; needs the falsifiability gate + coverage lift first.

## Build path (if FR-002/003/005 committed)
`community` node type + `member_of`/`summarised_as` edges (OQ-033-1 migration + config edge rule) + batch Leiden/Louvain jobengine job (prune generic hubs first) + one summary/cluster via BA-009 + `kg_global_retrieve` REST+MCP.

## ⚡ UPDATE 2026-07-16 — harness-findings-fixes plan complete; FR-001's "kg_graph_retrieve is broken" claim RETRACTED, ingest-quality gate closed

Full detail: `mem:checkpoint/harness-findings-fixes-2026-07-16`. Summary for this backlog:

- **The 2026-07-16 sim-consumer run's finding #1 ("`kg_graph_retrieve` broken — no passage text, `limit` ignored, hop-1 discarded") was a false diagnosis** from analyst parameter misuse (there is no `limit` field; real params are `result_k`/`seed_k`/`include_snippet`). Measured with correct params both before and after this fix: 9 rows, 9/9 snippets, `hop_count [0,1]`, multi-document. **`kg_graph_retrieve` was never broken.**
- **Closed the real defect that caused the false diagnosis:** `graph_retrieve.go` now rejects unknown JSON fields with 400 (`DisallowUnknownFields`) — verified live: `limit:60` → 400 naming the field + valid list; valid request → 200.
- **Closed the Dasin ingest-quality gaps this backlog's Gate-B/C section flags as blocking an honest verdict:** `BCTC KIEM TOAN 2023` was silently orphaned (0 concept edges) from a swallowed LLM JSON-parse failure in `extract.py` — now retries once then fails loud; re-ingested and measured at 3 concept edges (was 0), 9/9 docs processed with 0 failures, zero silent errors in the worker log.
- **Place/authority concept duplication (a distinct issue from the already-fixed company-legal-form dedup) is now closed too:** `decompose.py`'s `_LEGAL_FORMS` extended to place/authority abbreviations; measured live — Tân Thuận EPZ, Phú An Thạnh IP, and the HEPZA authority each collapsed to exactly one node (was 2+ each), total Dasin concepts 26→22.
- **This is Dasin-scale evidence (9 docs), not Cảng Định An-scale** — it closes the *ingest-quality* prerequisite this doc's Gate-B/C section names, but does not itself settle OQ-033-8/coverage/95-needs_review on the M&A corpus.

## ⚡ UPDATE (same day) — honest FR-001 verdict now in hand at Dasin scale, PLUS a second real bug found+fixed live

The harness re-run above (`findings-dasin-run2.md`) surfaced a NEW real bug, distinct from the retracted "graph_retrieve is broken" claim: DAAB's MCP bridge (`ennam.kg.go/internal/bridge/serve.go`) unconditionally injected an extra unrequested `projectId` field into every default-project `kg_graph_retrieve` call — harmless until this same plan's `DisallowUnknownFields()` fix started rejecting it. **Invisible to two independent whole-branch code reviews** because they checked the bridge's declared schema, not its runtime request-building logic. Fixed live (`ennam.kg.go` commit `467fd91`, TDD, independently reviewed Approved 0 Critical/Important), `kg-bridge` rebuilt.

**`findings-dasin-run3.md` (run 3, bridge now genuinely fixed) is the first trustworthy FR-001 measurement in 3 attempts:** score 33/42 (2.36 avg, up from 32/42 both prior runs). **`kg_graph_retrieve` CONFIRMED genuinely working** — 5/5 calls succeeded through the real MCP bridge path a real consumer (AAAA) would use, including real `hop_count:1` cross-document expansion in 3/5 calls.

**New backlog item surfaced (not retrieval, not covered by any FR-00x above):** even with retrieval genuinely working, Q9 (equity delta), Q11 (contradictions), Q12/Q13 (corpus synthesis) still score ≤2 — because the gap is a **comparison/arithmetic/synthesis layer**, not missing retrieval. Worth its own brainstorm + plan; do not fold into FR-001/FR-004 scope.

Full detail: `mem:checkpoint/harness-findings-fixes-2026-07-16`. Dasin-scale still cannot settle OQ-033-8/coverage/95-needs_review on the M&A corpus — that needs the 145-doc Cảng Định An corpus, unchanged from before.

## ⚡ UPDATE 2026-07-17 — first deterministic FR-001 verdict (code-measured, not LLM-narrated)

`findings-dasin-run2.md` and `findings-dasin.md` (referenced throughout the 2026-07-16 updates above) are **both banner-flagged compromised**: an LLM narrated its own tool-call outputs as measurements and fabricated numbers, twice. Task 3 of the doc-sync/DAAB-fix plan replaced that process with a deterministic Python script (`other_projects/daab-sim-consumer/fr001_measure.py`, gitignored local artefact) that computes every metric by code — set differences, row counts — and only dumps raw snippets for a human to separately judge relevance. Full detail: `mem:checkpoint/fr001-measurement-2026-07-17`.

**Verdict: INCONCLUSIVE AT N=10 — not the clean 0 (`ADDS NOTHING`) the prior narrated runs implied, and not a clean win either.** On the Dasin project (9 docs, `similar_to` edges=399), 10 queries (5 homogeneous financial-statement / 5 heterogeneous licence-narrative, predicted class stated before running):
- `hop1_only_docs` (documents reached ONLY via a `similar_to` edge, not by `kg_search_chunks`, not by graph_retrieve's own seeds) = **8 total**, non-zero on 4/10 queries (H1, X2, X4, X5) — spans **both** predicted classes, not just heterogeneous as hypothesized.
- `true_cross_doc_hop1` (edge-verified via `kg_get_node`) = 25 — the graph-traversal mechanism itself is confirmed real and working; it just often lands on documents already reachable another way, which is why `hop1_only_docs` (8) is much smaller than `true_cross_doc_hop1` (25).
- Heterogeneous queries lean on hop-1 expansion ~3x more than homogeneous ones by row fraction (0.332 vs 0.103 mean) — directionally consistent with the FR-001 thesis even though the binary class split didn't cleanly separate `hop1_only_docs` to zero on the homogeneous side.
- **This still cannot settle OQ-033-8/coverage/the 145-doc scale question** — Dasin's 9 docs test the mechanism, not whether it matters in aggregate. A repeat of this same deterministic script against Cảng Định An (592c7ff7) is the next concrete step if the Slice 2 scale decision is revisited.
- Bonus: one specific numeric claim from `findings-dasin-run3.md` (dropped_count/expanded_count/seed_count/hop1-doc-IDs for the `"doanh thu thuần 2023 2024 2025"` query) was spot-checked against the real script output and matched exactly — a genuine (if narrow) point of agreement, not grounds to trust that report's other unverified claims.

## See also
- `mem:decisions/ba033-slice2-deferred` (retraction 2026-07-08) · `mem:docs` `docs/daab-memory-consumer-contract.md`
- `mem:backlog/daab-kg-search-sessions-followups` · `mem:backlog/agent-context-retention-followups`
