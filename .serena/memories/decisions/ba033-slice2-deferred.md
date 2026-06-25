# Decision: BA-033 Slice 2 (community detection) — DEFERRED

**Date:** 2026-06-24 · **Basis:** 2-agent debate (Ecosystem CTO ⇄ DAAB Staff Engineer), both converged independently. **Related:** `mem:checkpoint/ba033-slice1-ba031-cleanup-2026-06-24`, BA-033 doc FR-002/003/005, `mem:decisions/ecosystem-hermes-allocation`.

## Verdict: do NOT build Slice 2 (FR-002 community detection + FR-003 summaries + FR-005 global retrieval) now.

### Three evidence-backed reasons
1. **Graph too sparse for clustering — readiness was mis-measured.** The "69% connected" milestone was on the concept-INCLUDED graph. FR-002/OQ-033-8 EXCLUDES concept. Live query: concept-excluded subgraph = **35 edges / 109 nodes / 36% connected / 70 singletons** — because ~81% of relations run through `concept`, and the recipe theme's hubs (Nguyên liệu/nước dùng/Phở Gà) ARE concept-typed. Excluding concept deletes one theme's connective tissue. OQ-033-8 contradicts the readiness gate it was approved against. **Blocking design ambiguity.**
2. **No permitted ecosystem consumer.** LAAM (Qwen 8B) principle "no LLM-summary-on-read" forbids consuming community summaries; AAAA multi-tenant confidentiality forbids cross-deal "global retrieval" (leak by construction). `kg_global_retrieve` has no valid caller.
3. **Wrong priority + unfalsifiable on current corpus.** Ecosystem P0 is memory-of-record (`kg_remember`/`kg_recall`), not community detection. The falsifiability gate (community-global beats hybrid+entity-neighborhood on corpus-level queries) CANNOT be run on the tiny mixed-domain test corpus — same root cause that made Slice 1 NO-GO.

### Recommendation (accepted direction)
- **Next substantive work = memory-of-record P0** (b): ecosystem's stated highest-leverage, 3 real consumers, DAAB is keystone owner, and its value does NOT depend on a coherent corpus (unlike all BA-033 retrieval).
- **Hold ALL BA-033 retrieval** (Slice 2 community AND the smaller entity-neighborhood option) until a coherent single-domain multi-document corpus exists — both Slice 1 and Slice 2 died on the same corpus problem.
- If a BA-033 increment must ship before then, prefer **entity-neighborhood retrieval** (1-2 hop, raw entities+edges) over community summaries — Qwen-safe + tenant-safe.

### Re-entry condition for Slice 2
Coherent single-domain multi-doc corpus + resolve OQ-033-8 (include concept in clustering scope, or re-validate density on a graph where the 6 resolved types are self-connected) + a named consumer + a runnable falsifiability gate.
