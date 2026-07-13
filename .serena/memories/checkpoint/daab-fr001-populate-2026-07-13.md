# Checkpoint: daab-fr001-populate — 2026-07-13

## What was done
Populated + re-tested FR-001 (`kg_graph_retrieve`) for project 592c7ff7 "Cảng Định An M&A". Deliverable: `other_projects/daab-sim-consumer/fr001-retest.md`.
- **Step 1** — embedded 626/626 `document_chunk` nodes (was 0). Path: `admin/reembed` and `admin/backfill-chunks` both no-op on already-ingested chunks (reembed lists existing embeddings; backfill skips matching content_hash), so used a clean script (scratchpad `embed_chunks.py`) reusing `LocalEmbeddingModel.encode_passage` + `KGClient.get_nodes`/`upsert_node_embeddings` → `POST /projects/{id}/node-embeddings/batch` (64/batch).
- **Step 2** — ran linker `POST /api/v1/internal/graphrag/link` → edges_upserted=2762, **similar_to=1864** in DB (was 0). Default sim_threshold 0.90, not lowered.
- **Step 3** — re-tested via `POST /api/v1/retrieve/graph` (admin key `ennam_kg_dev_0000…`, blank project_ids → CanOverrideProject). Q9 approval chain: seeds=8/expanded=81, surfaces chủ-trương→quy-hoạch→3 ĐTM decisions in ONE call. Q10 area contradiction: co-retrieves BOTH 14.71ha and 33.6ha docs. Q12: `kg_related_documents` + `kg_document_shared_entities` EXIST and work (harness wrongly said missing).

## Key finding (NEW — corrects prior triage)
Populating the substrate was necessary but NOT sufficient. `kg_graph_retrieve` still returns `seed_count:0` for ~2/3 of realistic queries — **HNSW post-filter starvation**: seeding = `ORDER BY embedding <=> q LIMIT k WHERE node_type='document_chunk'` on a single table-wide HNSW index where document_chunk is only 626/6219 (~10%) of vectors; entities dominate the top sim band (0.83–0.90), chunk band ~0.82. At default `hnsw.ef_search=40` the node_type post-filter starves → 0 seeds (clean 200, no error). Proven: seq-scan returns rows; **ef_search=400 recovers 100% of tested queries incl. all pure-English ones** (ef=40→4/12, ef=100→8/12, ef=400→12/12; ef=1600 regresses to 0 — tune to ~400, don't max). Cross-lingual is a relevance nuance that collapses into the same fix.

## Verdict
FR-001 design is VALIDATED — delivers Tier-3 cross-doc retrieval once populated; no new feature needed. Remaining gap is a ONE-LINE config fix: `SET LOCAL hnsw.ef_search=400` in the seed query (`graph_retriever.go`/`NodeEmbeddingStore.SemanticSearch`). Filtered/dedicated chunk index is an OPTIONAL latency follow-up and needs a schema change (`knowledge_node_embeddings` has no node_type column).

## Files changed
- NEW `other_projects/daab-sim-consumer/fr001-retest.md` (deliverable)
- scratchpad `embed_chunks.py` (one-off; not committed)
- DB mutated: 626 chunk embeddings + 1864 similar_to edges for project 592c7ff7

## Current state
Substrate populated & persistent in daab-postgres. FR-001 works for well-phrased/Vietnamese queries today; English/many queries need the ef_search bump. No code changed in the server.

## Next steps
1. DAAB: add `SET LOCAL hnsw.ef_search=400` to the seed query (the fix). 2. Optional filtered chunk index (schema change). 3. Wire chunk-embed+link into ingestion pipeline. 4. Provisioning fix for single-project dev-key 403 (`backlog/daab-agent-context-project-resolution-bug`) so a real AAAA key can call graph_retrieve.

## Blockers / Risks
- ef=1600 anomaly (regresses to 0) — don't set ef arbitrarily high; ~400 tuned.
- Doc duplication (same PDF as 2–5 document_ids) inflates related/shared-entities centrality — dedup pass pending.
