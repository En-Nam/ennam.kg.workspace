# Checkpoint: daab-fr001-efsearch — 2026-07-13

## What was done
- **Ran the FR-001 simulated-consumer harness** (`other_projects/daab-sim-consumer/`, M&A analyst on Cảng Định An via DAAB MCP, 15 DD questions). Result: existing tools good at Tier-1 single-doc (2.25) + Tier-2 entity (2.5); Tier-3 cross-doc collapsed (0.5), Tier-4 corpus (0.33). Evidence in `other_projects/daab-sim-consumer/findings.md`.
- **Triaged `kg_graph_retrieve` seed_count:0** (harness couldn't tell bug vs unpopulated): it was UNPOPULATED — 626 document_chunk nodes with 0 embeddings + 0 similar_to edges. BA-033 Slice 1 fully BUILT; pipeline never ran on this corpus.
- **A separate session populated it** (verified from DB by me): 626/626 chunk embeddings, 1864 similar_to edges (all chunk↔chunk). After populate, kg_graph_retrieve answered Q9 (approval chain, 1 call), Q10 (14.71 vs 33.6 ha contradiction, auto co-retrieved), Q12 (kg_related_documents works — harness wrongly said it was missing).
- **Found + FIXED the remaining reliability bug (A):** kg_graph_retrieve still returned seed_count:0 for ~2/3 real queries — HNSW post-filter starvation (document_chunk ~10% of the shared table-wide HNSW index; at default ef_search the node_type post-filter starves). Fix commit **`fc9afa6`** on `task/implement_docs_sync`: seed-scoped store option `WithEfSearch(n)` runs the seed query in a read-only tx with `SET LOCAL hnsw.ef_search` (tx-scoped, no pool leak); graph-retrieve seeds default to 400. Other SemanticSearch callers (search, resolution) unchanged (variadic). Verified: build + 3 pkgs unit `-race` green; recall A/B effect proven end-to-end by the other session (ef40 4/12 → ef400 12/12); my local SQL spot-check was inconclusive (chunk-self-embedding doesn't reproduce cross-type starvation — noted, not overclaimed). Variadic ripple to 2 interfaces + 5 fakes handled.

## Key conclusions (evidence-led, corrects earlier memos)
- FR-001 (cross-document local graph retrieval) is **BUILT + now VALIDATED** — closes the Tier-3 gap once populated + ef_search fix. **No new feature to build.**
- The GraphRAG deferral reasons about AAAA/LAAM were all refuted earlier (see `mem:decisions/ba033-slice2-deferred` retraction, `mem:backlog/ba033-slice2-readiness-path`). FR-002/003/005 (community/global) still deferred — Tier-4 weakest, local retrieval now covers most corpus questions.

## Current state
- `fc9afa6` on branch (NOT deployed). daab-server :8082 is a pre-fix 2026-07-07 build → live kg_graph_retrieve won't use ef=400 until rebuilt. Substrate IS populated for project 592c7ff7, so a rebuilt server works immediately.
- Working tree clean.

## Next steps
- **B (IN PROGRESS next): wire chunk-embed + similar_to link into the ingestion pipeline** so FR-001 auto-populates for EVERY project, not just this hand-populated one. Root question: why were 626 chunks ingested with 0 embeddings (Python `api/admin.py:_create_chunk` embeds on backfill, but the normal ingest path apparently didn't), and similar_to linking (`POST /api/v1/internal/graphrag/link`) is a manual step never auto-triggered.
- Deploy: rebuild daab-server from branch to make ef_search fix + populated substrate live.

## Blockers / Risks
- ⚠️ Still-open read-path project-resolution bug (single-project key → 403 on query/search); fix = key-creation auto-default (`mem:backlog/daab-agent-context-project-resolution-bug`). Deferred (provisioning-gated).
- ⚠️ Cleanup debt: revoke test API keys, rotate leaked daab-postgres dev password.
