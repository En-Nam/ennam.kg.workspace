# BA-033 Slice 2 — Gate A Measurement (concept-included)
**Date:** 2026-06-29 · **Branch:** `task/implement_docs_sync`

## OQ-033-8 Resolution: INCLUDE concepts

Resolved: concept nodes and `mentions` edges should be INCLUDED in the Slice 2 graph.
Rationale: the concept-excluded subgraph had only `contains_section` (hierarchical) edges with zero cross-document paths → no clustering possible. Concept inclusion is necessary for any cross-doc connectivity.

## Empirical measurement on current corpus (31 docs, Cảng Định An)

**Graph structure (knowledge_edges table):**
- `mentions: document → concept` = 261 edges
- `mentions: document_section → concept` = 216 edges
- `contains_section` (hierarchy) = 214+77+76 = 367 edges
- Total edges = 844, Total nodes = 691

**Concept node count:** 261 (of which 242 have ≥1 mention edge; 19 isolated)

**Architecture nodes:** 28 nodes, 0 edges → completely isolated singletons

## Critical finding: cross-document concept bridges

| Metric | Value |
|--------|-------|
| Concepts bridging ≥2 docs | **8** out of 261 (3.1%) |
| Doc-pairs sharing ≥1 concept | **19** out of 465 possible (4.1%) |
| Total cross-doc edges via concepts | **39** |
| Single-doc concepts | **234** (96.7%) |

**The 8 bridging concepts:**
- Công ty TNHH Xây dựng Hàm Giang (6 docs)
- Ban Quản lý Khu kinh tế Trà Vinh (5 docs)
- Xã Dân Thành, Tỉnh Trà Vinh, Ủy ban nhân dân tỉnh Trà Vinh, Thị xã Duyên Hải (3 docs each)
- Bộ Tài Nguyên và Môi Trường, Sở Tài nguyên và Môi trường tỉnh Trà Vinh (2 docs each)

**Nature of bridges:** ALL 8 are administrative/geographic entities (company name, government boards, province/commune names). NOT thematic knowledge concepts.

## Verdict: Gate A = NO-GO on current corpus

**Why concept-included fails:**
1. Only 8 concepts bridge docs (3.1%) — all administrative boilerplate, not thematic
2. 234/242 mentioned concepts are single-document → no cross-doc contribution
3. Concept degree distribution: 195 concepts have exactly 2 mentions (likely same doc at document + section level, NOT two different docs)
4. Architecture nodes (28) are completely unconnected — isolated singletons
5. Leiden/Louvain on this graph would produce: 1 trivial mega-cluster (all docs linked via company/province names) + many singletons. Not useful for retrieval.

**Root cause:** 31 documents are all from the SAME single project (Cảng Định An construction, Trà Vinh province). Shared concepts are organizational references, not thematic diversity.

## What would pass Gate A

- Multi-domain corpus: docs from DIFFERENT projects/domains → thematic concepts would appear across docs meaningfully
- "Upload more same-domain docs" (backlog option 2) would NOT help — the problem is lack of topic diversity, not volume
- Minimum viable corpus for clustering: docs from ≥3 different projects/topics

## Impact on next steps

- Option 2 from backlog ("upload more same-domain docs → re-measure") is NOT the right path
- Gate B (named consumer) is still independent and can be decided in parallel
- Gate A requires corpus diversification, which depends on real usage of the platform (more projects ingested)
- Slice 2 build remains deferred until corpus naturally diversifies through platform adoption

See `mem:backlog/ba033-slice2-readiness-path` for full context.
