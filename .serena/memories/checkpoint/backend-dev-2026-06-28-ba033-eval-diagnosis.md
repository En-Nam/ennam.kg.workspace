# Checkpoint: backend-dev — 2026-06-28 — BA-033 retrieval eval diagnosis

## What was done
- Verified the BA-033 retrieval plan (`docs/superpowers/plans/2026-06-27-ba033-retrieval-parent-child-entity.md`) against real code; fixed 2 plan gaps (NewGraphRetriever variadic-Option wiring; RRF needs []SearchResult convert).
- Other chat executed the plan: parent-child + entity-anchored + hybrid modes, 38/38 checklist, build green. NOTE: hybrid uses `Score = SeedRelevance*EdgeSimilarity`, NOT RRF.
- Eval gate (`ennam.kg.python/eval/eval_ba033_retrieval.py`) reported NO-GO, all 4 modes avg marginal r@k = -0.10; other chat recommended "keep flat + seed 216 docs".
- DIAGNOSED the NO-GO. Found it was largely an eval-harness artifact, then a deeper corpus/algorithm truth.

## Key findings (the important part)
1. **3 eval bugs** (now FIXED in eval_ba033_retrieval.py):
   - B1: `entity_neighbors[:max(0, top_k-len(ids))]` → sliced to empty whenever chunk results fill top_k → entity mode never measured (its -0.10 was a copy of flat).
   - B2: GT is mixed-granularity (8 document_section + 3 document_chunk of 11 sampled) but flat/parent_child return only `chunk_id`; baseline `/search` returns `document_section`. → graph chunk-modes structurally can't hit section GT; baseline wins by construction. Fixed by collapsing every id to canonical SECTION (chunk→parent section via `contains_section`, map in `eval/chunk_section_map.json`).
   - B3 (real, kept): 0 `similar_to` edges in corpus (only contains_section:83, mentions:140) → flat similar_to expansion is a no-op.
2. **After fix**, fair recall@10 (section-level): baseline 0.89 vs all-4-graph-modes 0.70 (identical); entity adds **0** GT hits beyond flat across 10 q.
3. **LLM relevance pass** on entity neighbors resolved the ambiguity:
   - Neighbors are NOT junk — real ecosystem docs (Kho xăng dầu Định An `d39914d2`, Hàm Giang `ac6ea64d`, land-lease `7031686b`). → GT is genuinely incomplete (eyeballed boilerplate: "Điều 3 hiệu lực", "Document").
   - BUT entity expansion is **query-INDEPENDENT**: Jaccard 0.87, 8/12 sections common to ALL 10 queries. Returns the same ecosystem "blob" regardless of query.
   - **Root cause (code):** `store.SharedEntityNeighbors` uses ALL concepts the origin sections `mentions` (origin = top-semantic seed sections, which all mention the common entities Định An/Trà Vinh/Hàm Giang/UBND), ranked by raw shared-COUNT, query ignored after seeding. On a single-project corpus → pulls ~whole corpus.

## Verdict
- Graph feature works as designed (surfaces real cross-doc ecosystem sections) but has NO per-query discriminative value on this dense single-project 10-doc corpus. Baseline `/search` (query-sensitive, section-grain) genuinely wins.
- `keep mode=flat` recommendation = correct; "seed 216" reasoning = wrong. 216 alone won't help unless entity expansion is made query-aware.

## Current state
- Eval harness fixed + chunk_section_map.json added (UNCOMMITTED in ennam.kg.python).
- Graph code (ennam.kg.go) committed by other chat (commits 4931928..aab1f22) + uncommitted tweak to internal/service/graph_retriever.go.
- Baseline `/search` is the shippable retrieval path now.

## Next steps
- IMPLEMENT 2a: make entity expansion **query-aware** — anchor on query-relevant entities, not all seed-mentioned entities (target: Jaccard drops, neighbors vary by query). Cheap, testable on same 10 docs.
- Then: rebuild a PROPERLY-labeled GT set (current GT is boilerplate/incomplete) before any trustworthy Go/No-Go.
- Only after 2a + good GT: decide whether to seed 216 multi-deal docs (entity diversity is the other prerequisite).

## Blockers / Risks
- GT quality is the real blocker to a trustworthy eval, not corpus size.
- Even query-aware entity expansion may stay blobby on a single-project corpus (all docs share entities) → 2a verification on 10 docs may be only partially conclusive.
