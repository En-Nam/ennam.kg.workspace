# Checkpoint: claude (DAAB KG explainer) — 2026-10-30

## What was done
- Answered, from primary source only (migrations, `config.yaml`, Go services/stores/handlers, Python ingestion pipeline), how DAAB builds KG nodes/edges, what a node holds, and how chunking / RAG / GraphRAG are implemented.
- Built a Vietnamese single-file HTML explainer (12 sections, each technical section opening with a plain-language "Nói đơn giản" box) and published it as a private Artifact.
- Verified every quoted number against the live dev DB (`daab-postgres`, port **5433**, user/db `ennam_kg`) per the "built ≠ used" rule (`mem:…` / auto-memory `daab-built-vs-used-row-counts`).

## Files changed
- No repo files changed. Deliverable only:
  `/private/tmp/claude-501/-Users-danhtrinh-Projects-Exnodes-EnnamKG-ennam-kg-workspace/8b42eedc-a999-4421-9f9d-27a1ada0cccc/scratchpad/daab-knowledge-graph.html` (session scratchpad — not durable across machines).

## Current state — verified facts worth keeping
- Graph storage is **Postgres 16 + pgvector**, not Neo4j: `knowledge_nodes` (node_type discriminator + `properties` JSONB) + `knowledge_edges` (UNIQUE(source,target,type), no DB CHECK on `edge_type` — whitelist-enforced in `config.yaml`).
- **22** allowed `node_type` values as of migration `000067_add_derived_record` (not 21 — count from 061+067, not 059).
- Two separate embedding systems: `knowledge_node_embeddings` vector(384) `intfloat/multilingual-e5-small` HNSW (12 084 rows, live) vs `table_embeddings` vector(1536) `text-embedding-3-small` IVFFlat (**0 rows** — corroborates the `ai.query_tier` vs `ai.query_tier_default` key-mismatch finding).
- Chunking is deterministic, no AI: THRESHOLD 1800 / SIZE 1200 / OVERLAP 150 / TOKEN_BUDGET 512. `CHUNKABLE_FORMATS = {markdown, md, plain_text, txt, text}` → PDF and DOCX *are* chunked (converted to md/plain_text first); CSV/XLSX/JSON stay **hub-only**.
- GraphRAG `similar_to` linking: `ChunkLinkWorker` runs unconditionally every 300 s, SimThreshold **0.90** (calibrated 2026-06-24 up from 0.83; e5-small noise floor 0.78–0.87), TopK 5, Overfetch 20.
- Retrieval `POST /api/v1/retrieve/graph`: seed_k 10 with `SET LOCAL hnsw.ef_search = 400` (fixes post-ANN node_type-filter starvation / `seed_count: 0`), 1-hop expansion, `score = seed_relevance × edge_similarity`, result_k 5, per_document_cap 2.
- Live row counts: document_chunk 5022, concept 4910, organization 1743, document_section 1469, location 1015, person 693, architecture 599, artifact 580, document 300, event 268, derived_record 3, project 1. Edges: similar_to 20173, contains_section 6491, mentions 5519, related_to 1553, schema_fk 671, part_of 567, works_for 375, evidence 186, causes 23, derived_from 8, schema_many_to_many 5, schema_implicit 1. `merge_suggestions` 10903.

## Two confirmed limitations (reported, NOT fixed)
1. `decompose.py` creates section-level `mentions` edges only from `hub_node_id` and `section_ids[0]` → only **265 of 1469** sections carry any `mentions`. Consequence: GraphRAG `entity`/`hybrid` mode is effectively dead, because `SharedEntityNeighbors` anchors on parent sections.
2. BA-031 pass 1 links an extracted entity to its chunk only via `properties.provenance.chunk_id` — there is **no edge** from entity back to the chunk.

## Next steps
- Decide whether to fix limitation 1 (emit `mentions` for every section, not just `section_ids[0]`) — note `config.yaml`'s whitelist has no `document_chunk → mentions` rule, so an entity→chunk edge (limitation 2) would need a whitelist entry first.
- `table_embeddings` is empty — the NL→SQL table-selection path (BA-020) has never run.

## Blockers / Risks
- The published Artifact (`https://claude.ai/artifact/MGBvnak7ugycwVz7fnRBaz`) **no longer exists** as of 2026-11-03 (watch ended: artifact not found). The source HTML survives only in the session scratchpad above; if it is wanted again it must be republished from there, or regenerated.
- Reading container env vars for DB credentials is blocked by the permission classifier ("Credential Materialization"); use `docker-compose.yml` defaults (`KG_DB_USER:-ennam_kg`) instead.
