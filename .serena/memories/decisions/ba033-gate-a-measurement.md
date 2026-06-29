# BA-033 Slice 2 — Gate A Measurement (concept-included)
**Date:** 2026-06-29 · **Branch:** `task/implement_docs_sync`

---
## ⚠️ RE-MEASURE 2026-06-29 (later, Opus) — MECHANISM REFINED, usefulness concern STILL STANDS

The original NO-GO below blamed **topic homogeneity** ("need ≥3 domains; upload won't help"). A fresh live-DB re-measure (daab-postgres :5433) **refines the mechanism but does NOT clear Gate A** — the original's retrieval-usefulness concern is *confirmed*, not refuted. Two separate claims:
- **Refuted — the diversity prescription.** "Need ≥3 domains / upload more won't help" is wrong for this data. The proximate *structural* blocker is non-deduped concept nodes, and per-project clustering (what AAAA tenancy permits) does not need cross-domain diversity.
- **CONFIRMED — the original's usefulness concern.** The would-be bridges are dominantly administrative/geographic co-occurrence (see top-20 below: Hàm Giang 80 docs, UBND Trà Vinh 53, BQL KKT 50…). Clustering on these groups docs by "which authority is named" — the useless-for-retrieval pattern the original flagged. Verdict stays **pending**, not GO.

**Corpus grew:** now 176 documents / 533 sections / 840 chunks / 1793 concepts across 2 substantive projects:
- `592c7ff7-9f6f-4cc5-9094-d9b3b685277e` = **145 docs / 1532 concepts** (NEW — but still Định An/Trà Vinh domain: Hợp đồng hợp tác, Điều lệ, GCN đăng ký DN, Quyết định chủ trương đầu tư; entities Hàm Giang / Trà Vinh / Định An)
- `a0000000-...-0001` = 31 docs / 261 concepts (original Định An)
- 3 other projects = empty (0–2 nodes)

**Decisive finding — concepts are NOT deduplicated (entity resolution in shadow mode, `mem:ba031-resolution-thresholds-gates`):**
- In project 592c7ff7, **cross-doc concept bridges = 0** (max_docs_per_concept = 1) — every concept node belongs to exactly 1 doc.
- BUT 1532 concept nodes collapse to only **656 distinct titles**; 231 titles have ≥2 node copies. E.g. "công ty tnhh xây dựng hàm giang" = **80 separate concept nodes** (one per doc), "ubnd tỉnh trà vinh" = 53, "ban quản lý khu kinh tế trà vinh" = 50.
- **Simulated dedup-by-normalized-title** ⇒ 656 concepts, **231 bridging ≥2 docs = 35.2%**, 40 bridge ≥5 docs, 21 bridge ≥10 docs, max 80 docs.

**BA-031 lever — VERIFIED (not assumed):** `ennam.kg.python/src/ennam_kg/resolution/pass2.py` groups resolution by `node_type` and the retriever filters candidates by `node_type`; `concept` is in `EXTRACTABLE_NODE_TYPES` and resolves against `concept`. So enabling BA-031 merge IS the correct lever to materialize these bridges. (Note: extraction taxonomy also has person/organization/location/event, but in this corpus ALL extracted entities are stored as `node_type='concept'` — which is exactly why the bridges read as administrative: orgs/locations mislabeled as concepts.)

**Bridge QUALITY (the deciding factor, sampled):**
- Top-20 bridges: 100% administrative/geographic (govt bodies, province/commune names, the contractor company).
- Ranks 21–60: still administration-dominant, BUT a real thematic-legal-regulatory substructure exists — `luật hàng hải việt nam`, `luật quy hoạch`, `QCVN 27:2010/BTNMT` + `QCVN 26:2010/BTNMT` (env standards), `nghị định 38/2015/NĐ-CP`, `hội đồng thẩm định báo cáo ĐTM`, comparator ports (Hải Phòng/Quảng Ninh/Nam Định). Latent "regulatory framework" / "environmental impact" / "maritime" communities are plausible but dominated by administrative hubs.
- Exact-title dedup UNDERCOUNTS: `ham giang` (no diacritic) is a separate entry from the 80-copy `hàm giang`; `sở xây dựng tỉnh trà vinh` vs `sở xây dựng trà vinh`. Real BA-031 fuzzy resolution would merge these → bridges denser than the 35.2% simulated floor.

**Refined verdict:** latent cross-doc connectivity (≥35.2% bridging) is already in the data but unmaterialized because duplicate concept nodes are never merged. Gate A is therefore **NOT GO-after-dedup and NOT NO-GO-forever** — it is pending a community-QUALITY trial. Mega-hub risk (Hàm Giang 80, UBND 53) is real and is the *same* phenomenon as the administrative-bridge concern, not a separate footnote.

**Next actionable steps for Slice 2 Gate A (ordered):**
1. Run real BA-031 merge on project 592c7ff7 (fuzzy, not exact-title) → re-run the bridging measure on the *merged* graph.
2. Community-quality trial: run Leiden/Louvain with hub-downweighting / resolution tuning → check whether **thematic** communities form (regulatory / environmental / maritime), not just one administrative mega-cluster. THIS is the real Gate A pass/fail, not the bridge count.
3. Gate B (named consumer) still independent and unresolved ⟹ Slice 2 stays deferred regardless of Gate A.

**Reproduce:** queries in this session's transcript — `knowledge_nodes`/`knowledge_edges` on daab-postgres, group concept mentions up to owning document via `contains_section`, count distinct docs per (concept node) vs per (lower(btrim(title))); BA-031 target verified in `resolution/pass2.py` + `extraction/schema.py`.

--- (original measurement below, root-cause framing superseded) ---


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
