# LAAM Markdown Memory Ingestion & Recall — Design Spec

**Date**: 2026-06-07
**Status**: Approved (design)
**Goal**: Define the end-to-end flow for **LAAM (a satellite runtime) to persist "things to remember" as `.md` files into the central Ennam KG, and recall them semantically** — using the existing Phase 6 ingestion + decomposition + embedding pipeline. This is an **integration / convention spec**, not a new parser: the markdown parsing and embedding mechanisms already exist (see "Already Built").

**Depends on (all DONE):** BA-022 (Unified Ingestion / draft nodes), BA-023 (file adapters), BA-024 (public ingest API + MCP), BA-025 (document decomposition + section embeddings, Phase 6.2).

> **Critical scoping decision (confirmed during brainstorming):** a markdown parser does **not** belong in the code indexer (`ennam-kg-indexer`). Code parsers emit `node_type="architecture"`; LAAM memory is **knowledge** (`document` / `document_section`), goes through the **ingestion** pipeline (AI-optional, deterministic section split, draft review, embeddings, cross-source links), and must not be duplicated in the indexer.

---

## Already Built (verified 2026-06-07 against the codebase)

The full parse → node → embed → recall chain exists. This spec **wires LAAM into it**, it does not rebuild it.

| Stage | Component | Notes |
|-------|-----------|-------|
| Markdown parse | `ennam.kg.python/.../ingestion/pipeline/document_tree.py::parse_markdown_sections` | Deterministic, PageIndex-style section split by heading boundaries |
| File extraction | `ingestion/adapters/files.py::extract_file_text` | `.md` → `("…", "markdown")`; also pdf/docx/xlsx/csv |
| Decompose → nodes | `ingestion/pipeline/decompose.py::decompose_document` | A `document` hub → `document_section` child nodes (Phase 6.2 / BA-025) |
| Embedding | `decompose.py` → `LocalEmbeddingModel` (sentence-transformers, **384-dim**) → `kg.upsert_node_embeddings` | Stored in `knowledge_node_embeddings (embedding vector(384))`, HNSW cosine index (migration 000055) |
| Ingest entry (MCP) | bridge tool `kg_ingest_node` (`title`, `content_raw`, `source_id`, `content_format`, `auto_approve`) + `kg_ingest_batch` | Forwards to public ingest API |
| Ingest entry (HTTP) | `POST /api/v1/projects/{id}/ingest/upload` (multipart) | What `scripts/ingest-md-via-api.sh` uses |
| Dedup on re-send | `draft_nodes` `ON CONFLICT (project_id, source_type, source_id) DO UPDATE` | Re-sending the same `source_id` **updates in place** (status `created`→`updated`), never duplicates |
| Processing trigger | `kg_process_drafts` MCP tool / `ingestion.auto_queue_processing` setting | Runs decompose + embed |
| Semantic recall | `internal/handler/search.go` → `NodeEmbeddingStore.SemanticSearch(QueryEmbedding, …)` (HNSW cosine) | `kg_search` returns semantically-near nodes |

---

## The LAAM memory flow (this spec)

```
LAAM (satellite, MCP client)
  │  kg_ingest_node(
  │     title       = "<memory title>",
  │     content_raw = "<full .md content>",
  │     content_format = "markdown",
  │     source_id   = "laam:memory:<stable-key>",   # dedup key
  │     auto_approve = true)
  ▼
Go public ingest API → draft_nodes UPSERT (ON CONFLICT source_id → update)
  ▼  (processing trigger — see Decisions)
Python decompose_document(draft):
     parse_markdown_sections → document hub + document_section nodes
     LocalEmbeddingModel(384) → knowledge_node_embeddings (per section)
  ▼
Recall: any agent → kg_search(query, semantic) → SemanticSearch over the 384-dim
        section embeddings → returns the remembered sections.
```

### Conventions (defined here)

- **`source_id` scheme:** `laam:memory:<stable-key>` where `<stable-key>` is LAAM's own stable id for that memory (e.g. a note id or content slug). Re-sending an updated memory with the **same** `source_id` updates the draft in place (verified `ON CONFLICT` upsert), so LAAM memory does not accumulate duplicates — the knowledge analog of the indexer's "re-index = latest state".
- **`source_type`:** `satellite_api` (`DraftSourceTypeSatelliteAPI`) — already what the public ingest path tags MCP/satellite submissions.
- **`content_format`:** `"markdown"` — drives `extract_file_text`/section parsing.
- **Node types produced:** one `document` hub + N `document_section` nodes (one per heading section). Memory is recalled at **section** granularity (each section independently embedded), so LAAM should structure a memory file with meaningful `##` headings.
- **`project_id`:** LAAM targets a dedicated memory project (e.g. a per-tenant or per-LAAM project UUID), passed by LAAM. Not hard-coded here.

### Decisions

| # | Decision | Choice |
|---|----------|--------|
| Q1 | Where does markdown parsing live? | **Ingestion pipeline (existing)** — never the code indexer. |
| Q2 | AI extraction vs deterministic? | **Deterministic section decomposition** (`document_tree` + `decompose_document`) is the memory path — cheap, no token cost, structured. (The AI `extract.py` step remains available for richer cross-source intelligence but is not required for plain memory recall.) |
| Q3 | Draft review vs auto-approve? | **`auto_approve=true`** for LAAM memory (trusted satellite; no human gate per note). Memory is meant to be immediately recallable. |
| Q4 | Processing trigger | **LAAM submits then triggers processing in the same interaction.** Two viable mechanisms — pick one in the plan: (a) enable `ingestion.auto_queue_processing` so ingest auto-enqueues decompose+embed; or (b) LAAM calls `kg_process_drafts` after `kg_ingest_node`. **(a) is preferred** so a single `kg_ingest_node` call yields a recallable memory without a second round-trip. |
| Q5 | Embedding model parity | The **recall query must be embedded with the same 384-dim model** (`sentence-transformers`, `settings.embedding_model_name`) that `decompose.py` uses, or cosine search is meaningless. `kg_search`'s `QueryEmbedding` must come from that same model. This parity is a **hard requirement** the plan must verify end-to-end. |

---

## Likely gap to build (to be confirmed in the plan)

Everything above is built **except** possibly a smooth single-call path. Today LAAM may need two MCP calls (`kg_ingest_node` → `kg_process_drafts`) unless `auto_queue_processing` is enabled. **Candidate (optional, decide in plan):** a thin convenience MCP tool `kg_remember(title, content, source_id, project_id)` that wraps ingest(markdown, auto_approve) + process in one call — the knowledge analog of `kg_index_source` for code. If `auto_queue_processing=true` makes a single `kg_ingest_node` sufficient, **no new tool is needed** (YAGNI) and this spec reduces to enabling that setting + documenting the convention.

**The plan's first task is to determine empirically which is true** (does `kg_ingest_node` + `auto_queue_processing` already produce recallable embedded sections in one call?), then either (a) document the existing one-call flow, or (b) add the thin `kg_remember` wrapper.

---

## Out of Scope

- A markdown parser in the code indexer (`ennam-kg-indexer`) — wrong layer (would emit `architecture` nodes and duplicate this pipeline).
- New embedding infrastructure — `knowledge_node_embeddings` (384-dim, HNSW) and `LocalEmbeddingModel` already exist.
- Re-specifying decomposition — BA-025 / `decompose.py` already define section decomposition + embeddings.
- AI cross-source linking tuning (`cross_edges.py`) — available but not required for basic memory recall.
- Changing the embedding model/dimension (stays 384-dim local; changing it is a separate migration).

---

## Verification (end-to-end, requires running stack)

1. `kg_ingest_node` a small markdown memory (`content_format=markdown`, `source_id=laam:memory:test-1`, `auto_approve=true`) → returns a draft, status `created`.
2. Ensure processing ran (auto-queue or `kg_process_drafts`) → assert `document` hub + ≥1 `document_section` nodes exist, and `knowledge_node_embeddings` has rows for them.
3. `kg_search` with a query semantically related to a section → the section is returned (semantic recall works; confirms model parity).
4. Re-`kg_ingest_node` the **same** `source_id` with edited content → draft status `updated`, sections refreshed, **no duplicate** document hub (dedup holds).
5. A query unrelated to any memory → does not spuriously return the memory (sanity).
