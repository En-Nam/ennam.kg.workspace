# Backlog — BA-033 Slice 2 readiness path

**UPDATED 2026-07-03: Gate A RE-MEASURED → GREEN.** (Supersedes the 2026-06-29 RED below — that measurement is stale.) **Branch:** `task/implement_docs_sync`.

## ⚡ Gate A — RE-MEASURED 2026-07-03 (:5433, project 592c7ff7…) → GREEN
Since the 2026-06-29 RED, **BA-031 relation extraction created entity↔entity edges** — the old "concept↔concept=0, entity↔entity=0" blocker is GONE.
- Live edge types now include `related_to` (concept↔concept 182, org↔org 175, org↔concept 163, org↔location 64…), `part_of` (org↔org 139, concept↔concept 125, artifact↔concept 102…), `works_for` (person↔org 188).
- **entity↔entity subgraph: 2081 edges over 1462 nodes** (of 3083 entity nodes; 1621=53% isolated).
- **Community spike (networkx louvain, seed 42):** RAW modularity **0.833** (120 comms, 49 non-trivial≥3); PRUNED-generics modularity **0.849** (140 comms, 61 non-trivial, top sizes 135/94/86/82…). Hairball manageable: pruning ~15 generic titles (Công ty, Dự án, Pháp luật, …) breaks the 193→135 blob. Script: scratchpad `gate_a_spike.py`.
- ⟹ **Strong, well-separated community structure. Gate A no longer blocks slice 2.** Caveat: coverage ~47% (53% entity nodes isolated) → global themes cover ~half the entities.

## Gate B — Product (named consumer). STILL the binding blocker (product decision, not empirical).
`kg_global_retrieve`/community-summary need a valid caller: LAAM (Qwen 8B) forbids LLM-summary-on-read; AAAA multi-tenant forbids cross-deal global. Candidate that fits: **DAAB-internal admin "global themes" dashboard** (human-facing, not 8B, not cross-deal). With 61 coherent communities measured, this now has real content. **Decide the consumer + a runnable falsifiability gate before building.**

## Build path (if Gate B committed)
`community` node type + `member_of`/`summarised_as` edges (OQ-033-1 migration + config edge rule) + batch Leiden/Louvain jobengine job (prune generic hubs first) + one summary/cluster via BA-009 + `kg_global_retrieve` REST+MCP (FR-002/003/005). OQ-033-8 (concept include/exclude) now measurable — concepts DO have inter-concept edges.

## Prior context (2026-06-29, superseded on Gate A)
Corpus was bipartite doc↔concept then; entity resolution (fuzzy-hub + danger-stratum drains, 2026-07-01/03) merged ~1200 dup entities improving edge density. Local upload feeds OCR directly (AAAA-independent seeding). planB Supabase connector deprioritized.

## See also (unblocked, independent of Slice 2)
- `mem:backlog/daab-kg-search-sessions-followups` — `monitoring` scope for LAAM cross-user `kg_search_sessions`. Highest-value unblocked keystone, no gates.
- `mem:backlog/agent-context-retention-followups` · `mem:backlog/sse-block-ordering-bug`.
