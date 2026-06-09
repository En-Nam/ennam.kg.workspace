# Hybrid Search (RRF) + Multilingual Embedding — Design Spec

**Date**: 2026-06-09
**Status**: Approved
**Source requirement**: `ennam.kg.requirements/documents/improvements/IMP-005-hybrid-search-rrf-multilingual-embedding.md`
**Affects**: BA-011 (AI NL Query), BA-025 (Document Decomposition & Retrieval), BA-028 (Satellite Memory Semantic Recall)
**Goal**: Add a `hybrid` search mode that fuses the existing full-text (`ts_rank`) and semantic (pgvector cosine) result lists via Reciprocal Rank Fusion, and swap the embedding model to a multilingual one (`intfloat/multilingual-e5-small`, still 384-dim) so Vietnamese recall stops failing — all on managed AWS RDS, with **no new Postgres extension and no `vector(384)` column migration**.

---

## Context

`kg_search` today has two **mutually exclusive** modes:

- **Full-text** (default): Postgres FTS `search_vector @@ plainto_tsquery` ranked by `ts_rank(..., 32)` in [`internal/store/search.go`](../../../ennam.kg.go/internal/store/search.go), with an `ILIKE` substring fallback when FTS returns nothing.
- **Semantic** (`semantic=true`, BA-028): the query text is embedded server-side at 384-dim ([`SearchHandler.ensureQueryEmbedding`](../../../ennam.kg.go/internal/handler/search.go) → Python `POST /api/v1/embeddings`) and run through [`NodeEmbeddingStore.SemanticSearch`](../../../ennam.kg.go/internal/store/node_embedding.go) (pgvector cosine).

Two weaknesses motivate this work:

1. **No fusion.** A lexical-only hit (rare keyword) and a semantic-only hit (paraphrase) can never appear in the same ranked list — the caller must pick one mode.
2. **English-centric embeddings.** `all-MiniLM-L6-v2` is English-centric, so Vietnamese recall is poor (observed: query "rủi ro pháp lý" returned the "Điểm mạnh" section). The real corpus (e.g. the Cảng Định An report) is predominantly Vietnamese.

True BM25 (`pg_search`/ParadeDB) is **not on the RDS allowlist** and is out of scope (see Appendix). This spec takes the two RDS-compatible wins: **Hybrid RRF** + a **multilingual embedding swap that keeps 384-dim**.

The `knowledge_node_embeddings` table already has an **HNSW cosine index** (`idx_knowledge_node_embeddings_vector`, migration `000055`), so semantic search is already index-accelerated — no index work is needed for this IMP.

---

## Approved Decisions

| # | Decision | Choice |
|---|----------|--------|
| D1 | **Hybrid candidate scope** | Both arms run over the **embedded node types only** (today: `document_section`). Same universe in, clean RRF out. Caller may override `node_types`; if so, both arms use the override. |
| D2 | **RRF compute location** | **Go app-layer merge.** Run the two existing queries (FTS + `SemanticSearch`), then fuse by rank in Go. Reuses both code paths untouched, trivial to unit-test, clean fail-soft. |
| D3 | **Re-embed trigger** | **Admin REST endpoint on the Python service** (`POST /api/v1/admin/reembed`), paginating over `knowledge_node_embeddings`, re-encoding with e5, upserting back. |
| D4 | **Embedding model** | `intfloat/multilingual-e5-small` (384-dim). `embedding_dimensions` stays **384** → no column/index migration. |
| D5 | **Speed** | The two hybrid arms run **concurrently** (two goroutines + `sync.WaitGroup`, matching the codebase convention — `golang.org/x/sync/errgroup` is **not** a dependency); query embedding is computed once and shared. |

---

## Scope

### In scope
- **FR-1** — Hybrid RRF: a new `hybrid` branch in the Go search handler that fuses FTS + semantic via RRF.
- **FR-2** — Multilingual embedding: change `embedding_model_name` to `intfloat/multilingual-e5-small`; route all embedding through prefix-aware helpers (e5 needs `query:`/`passage:` prefixes).
- **FR-3** — Re-embed/backfill: an admin endpoint that re-encodes every existing embedding row with the new model.
- **FR-4** — MCP schema: add a `mode` property to `kg_search`.
- **FR-5** — Retrieval eval: a small (~20–30 pair) VI+EN `query → expected-section` harness measuring recall@5 / MRR before vs after, used to confirm quality and tune RRF `k`.

### Out of scope
- BM25 / `pg_search` / ParadeDB (blocked on RDS — Appendix).
- Any dimension ≠ 384 (would force a `vector(...)` column + index migration).
- Changing the decomposition/ingest pipeline shape (BA-022/024/025) — only the embedding *model* changes, not *how* sections are produced.
- Embedding-version columns / dual-write / zero-downtime cutover (recorded as a future upgrade path, not built now).
- **The BA-020 table-schema embedding system is explicitly untouched.** There are two unrelated embedding systems in the codebase; this IMP affects only the first:
  - **Node section embeddings** — `knowledge_node_embeddings` table, **384-dim**, local sentence-transformers, written by [`decompose.py`](../../../ennam.kg.python/src/ennam_kg/ingestion/pipeline/decompose.py) → [`NodeEmbeddingStore`](../../../ennam.kg.go/internal/store/node_embedding.go). **This is what `kg_search semantic`/`hybrid` queries — and the only thing this IMP changes.**
  - **Table-schema embeddings (BA-020)** — a separate `EmbeddingStore` populated by [`internal/service/embedding_generator.go`](../../../ennam.kg.go/internal/service/embedding_generator.go) at **1536-dim** via OpenAI `text-embedding-3-small`, used for NL→SQL table retrieval. Different table, dimension, model, and purpose. The re-embed job (FR-3) **must not** touch it; the model swap (FR-2) does **not** apply to it.

---

## FR-1 — Hybrid RRF (Go)

### Request shape

Extend `searchRequest` in [`internal/handler/search.go`](../../../ennam.kg.go/internal/handler/search.go) with a `mode` field:

```go
type searchRequest struct {
    // ... existing fields ...
    Mode     string `json:"mode,omitempty"`     // "fulltext" (default) | "semantic" | "hybrid"
    Semantic bool   `json:"semantic,omitempty"` // legacy; semantic=true ⇒ mode=semantic
}
```

**Mode normalization (one place, early in `HandleSearch`):**

```
effectiveMode =
    "hybrid"   if mode == "hybrid"
    "semantic" if mode == "semantic" OR semantic == true   // BR-002 back-compat
    "fulltext" otherwise (default; unknown/empty mode)
```

`mode=fulltext` and the legacy `semantic=true` paths are **byte-for-byte unchanged** (BR-001/BR-002). Only `mode=hybrid` (and `mode=semantic` as an alias) is new wiring.

### Candidate scope (D1)

In hybrid mode, the candidate node-type set is the **embedded set**. Define a single source of truth:

```go
// hybridEmbeddedNodeTypes is the set both hybrid arms run over.
// Matches what the ingest worker actually embeds (today: document_section).
var hybridEmbeddedNodeTypes = []string{"document_section"}
```

- If the caller passes `node_types`, both arms use that (caller override).
- If not, both arms use `hybridEmbeddedNodeTypes`.
- The FTS arm therefore receives the **same** `NodeTypes` filter as the semantic arm — no universe mismatch.

> Rationale: the IMP flags that FTS covers all node types while only `document_section` is embedded. Restricting FTS to the embedded set guarantees RRF fuses two views of the *same* candidate pool. When the embedded set later grows (e.g. the worker starts embedding `document`/`concept`), this one slice is the only thing to update — keep it aligned with the worker.
>
> BA-028 coverage: satellite memory ingested via `kg_ingest_node` flows through the ingest pipeline and is decomposed into `document_section` nodes (verified: [`decompose.py`](../../../ennam.kg.python/src/ennam_kg/ingestion/pipeline/decompose.py) runs for `document`/`external` hubs and emits `document_section`). So LAAM memory is embedded as `document_section` and is fully covered by both `semantic` and `hybrid` with this scope.

### Fusion algorithm (D2 — app layer)

New function in the store or a small `internal/search` helper:

```
RRF(lists [][]SearchResult, k int, limit int) []SearchResult:
    scores := map[nodeID]float64
    keep   := map[nodeID]SearchResult   // first-seen full row
    for each list in lists:
        for rank, row in enumerate(list, start=1):   // 1-based
            scores[row.ID] += 1.0 / float64(k + rank)
            keep.setdefault(row.ID, row)
    merged := values(keep) sorted by scores desc, tie-break updated_at desc
    return merged[:limit], with row.Rank = scores[row.ID]   // RRF score replaces per-arm rank
```

- `k` is configurable, **default 60** (BR-003), read from config (see Config below).
- RRF uses **ranks, not raw scores** — `ts_rank` (0–1, normalized) and cosine (`1 - distance`) are never compared directly, so no score normalization is needed.
- Dedup is by node `id`; the first arm to surface a node supplies the returned row (both arms `SELECT` the same columns, so the row is identical regardless).
- Each arm is fetched at **top-K = max(limit, defaultArmK)** (arm depth ≥ final limit; start `defaultArmK = limit`, tune via eval) so RRF has enough candidates to fuse before truncating to `limit`.

### Concurrency + fail-soft (D5, BR-004)

```
HandleSearch (mode=hybrid):
    1. ensureQueryEmbedding(req)        // embed query once (e5 "query:" prefix, server-side)
       └─ on embedding-service error → log, FALL BACK to plain fulltext (BR-004): see "fallback scope" below
    2. two goroutines + sync.WaitGroup (each writes its result/err to its own var):
         g1: lexical  = store.Search(FTS, nodeTypes=scope, topK)
         g2: semantic = nodeEmb.SemanticSearch(queryEmbedding, nodeTypes=scope, topK)
       └─ if the semantic arm errors but lexical succeeds → log, return lexical-only (degrade, don't 502)
       └─ if the lexical arm errors but semantic succeeds → log, return semantic-only
       └─ if both error → 500
    3. fused = RRF([lexical, semantic], k, limit)
    4. respond 200 with fused (optional debug: per-arm rank when ?debug=true)
```

- **Concurrency uses stdlib `sync.WaitGroup`** (two goroutines, each writing to its own result/error variable — no shared map, so no lock needed). `errgroup` is deliberately avoided because it is not a project dependency.
- **Fallback scope (resolves the ambiguity):** when the embedding hop fails and we fall back to fulltext, the fallback is a **plain full-text search honoring only the caller's explicit `node_types`** (no injected `document_section` restriction). It does **not** apply the hybrid embedded-set scope — the embedded-set restriction exists only so the two arms fuse over the same universe, which is irrelevant once there is a single (lexical) arm. This gives the most useful degradation: a normal full-text search.
- Fail-soft is the headline behavior: **a dead embedding service must never 502 a hybrid query** — it silently becomes full-text (acceptance criterion). This mirrors the existing handler, which today returns `502` on embedding error for `semantic` mode; for `hybrid` we instead degrade.
- Running the two arms in parallel keeps hybrid latency ≈ `max(FTS, semantic)`, not their sum (D5 — "speed at best").

### Response

Reuse the existing `store.SearchResponse`. `Rank` carries the **RRF score** in hybrid mode. When `?debug=true` (or a `debug` body flag), attach an optional per-node breakdown `{lexical_rank, semantic_rank, rrf_score}` to aid `k`-tuning — omitted by default to keep the payload stable.

---

## FR-2 — Multilingual embedding (Python)

### Model swap

In [`config.py`](../../../ennam.kg.python/src/ennam_kg/config.py):

```python
embedding_model_name: str = "intfloat/multilingual-e5-small"   # was: all-MiniLM-L6-v2
embedding_dimensions: int = 384                                 # UNCHANGED (BR-006)
```

`intfloat/multilingual-e5-small`: 384-dim, ~118M params (~470MB on disk, ≈5× `all-MiniLM`), purpose-built for retrieval, strong on Vietnamese.

### Prefix parity (BR-005) — the footgun this section exists to prevent

e5 is **asymmetric**: queries must be prefixed `"query: "` and passages `"passage: "`. A mismatch silently degrades cosine. The prefix must live in **one shared helper**, never hand-built at call sites.

Add prefix-aware methods to [`LocalEmbeddingModel`](../../../ennam.kg.python/src/ennam_kg/embeddings/local_model.py):

```python
# e5 family requires asymmetric prefixes; non-e5 models (e.g. all-MiniLM) must NOT be prefixed.
def _needs_e5_prefix(self) -> bool:
    return "e5" in self._model_name.lower()

def encode_query(self, texts: list[str]) -> list[list[float]]:
    return self.encode([f"query: {t}" for t in texts] if self._needs_e5_prefix() else texts)

def encode_passage(self, texts: list[str]) -> list[list[float]]:
    return self.encode([f"passage: {t}" for t in texts] if self._needs_e5_prefix() else texts)
```

- Raw `encode()` stays (still L2-normalizes — required for cosine), but **call sites must use `encode_query` / `encode_passage`**, never raw `encode` for retrieval text.
- Model-aware prefixing means the same code is correct before and after the swap, and during the maintenance window.

### Two call sites, two helpers

| Site | File | Was | Becomes |
|------|------|-----|---------|
| Query embedding (search) | [`api/embeddings.py`](../../../ennam.kg.python/src/ennam_kg/api/embeddings.py) | `model.encode(body.texts)` | `model.encode_query(body.texts)` (default) — add optional `input_type: "query" \| "passage"` to `EmbeddingRequest`, defaulting to `"query"`, routing to the matching helper |
| Passage embedding (ingest) | [`ingestion/pipeline/decompose.py`](../../../ennam.kg.python/src/ennam_kg/ingestion/pipeline/decompose.py) | `model.encode(batch_texts)` | `model.encode_passage(batch_texts)` |

- The Go side ([`SearchHandler`](../../../ennam.kg.go/internal/handler/search.go)) already calls `POST /api/v1/embeddings` for queries; with the endpoint defaulting to `input_type="query"`, **no Go change is needed for prefixing** — the prefix is applied entirely server-side in Python.
- **Single config source** (BR-005): both sites read the same `settings.embedding_model_name`, preserving model parity required by BA-028. The endpoint already echoes `model`/`dimensions` in `EmbeddingResponse` for verification.

---

## FR-3 — Re-embed / backfill (D3)

Old (`all-MiniLM`) and new (e5) vectors live in **different spaces** — cosine between them is meaningless. We re-embed everything, **then** cut over the query model (BR-007).

### Endpoint

`POST /api/v1/admin/reembed` on the Python service (auth: same bearer as `/api/v1/embeddings`).

```
reembed():
    model = LocalEmbeddingModel(settings.embedding_model_name)   # e5
    cursor = 0
    loop:
        rows = KG API: list embeddings page (project_id, node_id, chunk_text) LIMIT N OFFSET cursor
        if empty: break
        vectors = model.encode_passage([r.chunk_text for r in rows])   # passages
        upsert each (node_id, chunk_text, content_hash, vector) via KGClient.upsert_node_embeddings
        cursor += len(rows)
    return {reembedded: total}
```

- **Node-type-agnostic**: it re-encodes **whatever is currently in `knowledge_node_embeddings`** (today `document_section`), so it stays correct if the embedded set changes later.
- **Idempotent + batched**: upsert is `ON CONFLICT (node_id) DO UPDATE` (existing `NodeEmbeddingStore.Upsert`); batch size reuses the worker's `_EMBED_BATCH = 32`. Safe to re-run.
- **`chunk_text` is reused as-is** — it is the stored passage text; the `passage:` prefix is applied transiently inside `encode_passage` and is **not** persisted (consistent with ingest).

A read endpoint is needed to page the rows: add a Go endpoint `GET /api/v1/embeddings/rows?limit=&offset=` (admin-scoped) returning `{node_id, project_id, chunk_text}` so the Python job can iterate without direct DB access. (Python has no DB connection — it only talks to the Go API.)

### Operational cutover (maintenance window)

1. **Pause ingest** — operationally don't ingest during the window, or set `ingestion.auto_queue_processing=false`. (No section is created in the old space mid-flight.)
2. **Run `POST /api/v1/admin/reembed`** with the e5 model until it reports done.
3. **Only then** cut over the query model (it already reads the same `embedding_model_name`) and resume ingest.

Cutover *after* backfill avoids any "new-query vs old-section" window. The model is **pre-baked into the Python image** (avoid first-request download latency; measure image size + encode latency at PoC — Risks).

---

## FR-4 — MCP bridge schema

In [`internal/bridge/schema.go`](../../../ennam.kg.go/internal/bridge/schema.go), `kg_search`:

- Add a `mode` property: `enum ["fulltext", "semantic", "hybrid"]`, optional, default `fulltext`, with a description of fusion behavior.
- Keep `semantic` (boolean) for back-compat; document that `mode` takes precedence and `semantic=true` ⇒ `semantic` mode.
- The bridge proxies the request body verbatim, so **no routing change** — it's a property add, not a tool. **Tool count is unchanged.**
- Update the `node_types` enum description to note that `document_section` is the embedded type used by `hybrid`/`semantic` (the enum currently lists only the six core types — extend it to include the embedded types so callers can target them).

---

## FR-5 — Retrieval eval

A small standalone harness (script + fixture), **separate from BA-013** (BA-013 measures NL→SQL accuracy, not vector recall):

- **Dataset**: ~20–30 `query → expected-section-id` pairs, **VI + EN mixed**, drawn from real ingested content (e.g. the Cảng Định An report) plus a few synthetic paraphrase/rare-keyword pairs that specifically exercise lexical-only vs semantic-only hits.
- **Metrics**: `recall@5` and `MRR`, computed per mode (`fulltext`, `semantic`, `hybrid`) and per language.
- **Gates** (relative, not absolute):
  - **recall@5 (VI) > the `all-MiniLM` baseline**, AND
  - **no regression (EN)**.
- **Secondary use**: sweep RRF `k` (and arm depth) over the eval set to pick the production default; record the chosen `k`.
- Runs before (baseline, current model) and after (e5 + hybrid) so the improvement is evidence-backed.

---

## Configuration

Go side — add to search config (env `KG_`-prefixed, following existing convention), with safe defaults so nothing breaks if unset:

| Key | Default | Purpose |
|-----|---------|---------|
| `search.rrf_k` | `60` | RRF constant `k` (BR-003) |
| `search.hybrid_arm_k` | `= limit` | per-arm top-K fetched before fusion |

Python side — no new config beyond the `embedding_model_name` value change (`embedding_dimensions` unchanged).

---

## Business Rules (from IMP, locked)

| Rule | Detail |
|------|--------|
| BR-001 | `mode=fulltext` is the default; current FTS behavior is **unchanged**. |
| BR-002 | Legacy `semantic=true` ≡ `mode=semantic`. |
| BR-003 | `mode=hybrid` fuses lexical + semantic via RRF, configurable `k` (default 60). |
| BR-004 | Hybrid needs the query embedding; if the embedding service fails → **fall back to fulltext** (fail-soft), never a blanket 502. |
| BR-005 | Embedding model is a **single config source**; embed-query/embed-passage go through a **shared prefix-aware helper** (e5 prefixes never hand-built per site). |
| BR-006 | `embedding_dimensions` locked at **384** — no pgvector column/index migration. |
| BR-007 | Model change = **re-embed everything first, cut over the query model after** (maintenance window). |
| BR-008 | **No new Postgres extension** (managed-RDS compatible). |
| BR-009 | Quality accepted via the retrieval eval (recall@5 / MRR), VI + EN, before/after. |

---

## Acceptance Criteria

1. **Given** a document with section A matched only lexically (rare keyword) and section B matched only semantically (paraphrase), **when** `kg_search(mode=hybrid)`, **then** both A and B appear, ranked by RRF score.
2. **Given** a Vietnamese query FTS misses but semantic catches, **when** `mode=hybrid`, **then** the correct result is within top-N.
3. **Given** `mode=fulltext` (or no mode), **when** searching, **then** behavior is identical to before this IMP (no regression).
4. **Given** the embedding service is down, **when** `mode=hybrid`, **then** search still returns full-text results (fail-soft), not a 502.
5. **Given** `embedding_model_name` changed to e5-small (384-dim), **when** running the backfill, **then** there is **no** `vector(384)` schema migration, and **every existing row** in `knowledge_node_embeddings` is re-embedded before the query model is cut over.
6. **Given** the dedicated retrieval eval (~20–30 VI+EN pairs), **when** measuring recall@5 / MRR before/after, **then** **recall@5 (VI) > the `all-MiniLM` baseline** AND **no EN regression**. This eval also fixes the RRF `k`.
7. **Given** any query, **when** inspected, **then** query and section vectors are produced by the **same** model (parity), confirmable via `model`/`dimensions` from `/api/v1/embeddings`.

---

## Components & Files

| Component | Effort | Files |
|-----------|--------|-------|
| Go: hybrid handler branch + mode normalization + fail-soft | Medium | `internal/handler/search.go` (+ test) |
| Go: RRF fusion helper | Small | `internal/store/search.go` or new `internal/search/rrf.go` (+ table-driven test) |
| Go: concurrent arms (`sync.WaitGroup`) | Small | `internal/handler/search.go` |
| Go: embedding-rows read endpoint (for backfill paging) | Small | `internal/handler/` + `internal/store/node_embedding.go` (+ test) |
| Go: `mode` param on `kg_search` schema | Small | `internal/bridge/schema.go` (+ schema test) |
| Go: search config (`rrf_k`, `hybrid_arm_k`) | Small | `internal/config/` |
| Python: model config change | Trivial | `config.py` |
| Python: prefix-aware `encode_query`/`encode_passage` | Small | `embeddings/local_model.py` (+ test) |
| Python: route both embed sites through helpers + `input_type` | Small | `api/embeddings.py`, `embeddings/models.py`, `ingestion/pipeline/decompose.py` |
| Python: `POST /api/v1/admin/reembed` | Medium | new `api/admin.py` (+ test) |
| Eval harness (VI/EN, before/after) | Small | `tests/` fixture + a runner script |
| **Total** | **~3–4 days** | + re-embed compute (one-time, depends on row count) |

---

## Testing Strategy

- **Go unit (table-driven)**: RRF fusion (rank math, dedup, tie-break, empty arm, k variation); mode normalization (`""`/`fulltext`/`semantic`/`semantic=true`/`hybrid`/unknown); fail-soft (embedding error → fulltext; one arm errors → other returned; both error → 500).
- **Go schema test**: `kg_search` exposes `mode` with the right enum; tool count unchanged (guards the [bridge tool-count drift](../../../.serena/memories/) noted in memory).
- **Python unit**: `encode_query`/`encode_passage` apply e5 prefixes for e5 models and **no** prefix for non-e5 (regression guard for the parity footgun); `decompose.py` uses `encode_passage`; `/api/v1/embeddings` defaults to query prefix; reembed pagination idempotency (mocked KG client, no real model/Redis — per existing test convention).
- **Eval (FR-5)**: recall@5 / MRR per mode per language, asserted against the relative gates.
- All Go tests under `make test` (`-race`); Python under `uv run pytest` (mocked).

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Old/new vectors mixed during transition → garbage cosine | Medium | High | Re-embed-all then cut over the query model (FR-3, BR-007); no dual-space queries |
| e5-small ~5× larger (~470MB) → image bloat + slower encode | Medium | Med | Pre-bake model into the image; batch encode; measure latency + image size at PoC |
| RRF `k`/arm-depth needs tuning | Medium | Med | Tune via the eval; start at `k=60`, arm depth = limit |
| Large re-embed compute if many nodes | Low–Med | Med | Batched, idempotent, paginated; estimate up front; run inside the window |
| Hybrid scope drift (worker starts embedding new types but `hybridEmbeddedNodeTypes` not updated) | Low | Med | Single source-of-truth slice; comment ties it to the worker's embedded set; eval would catch missing recall |
| Users expect "BM25" but get RRF | Low | Low | Document: RRF captures most lexical+semantic benefit while staying RDS-compatible; true BM25 needs leaving RDS (out of scope) |

---

## Appendix — Why not BM25 / `pg_search`

Production runs **AWS RDS PostgreSQL 16.4 managed** (`deploy/terraform/modules/rds`, ECS Fargate). RDS only allows allowlisted extensions (`vector`, `pg_trgm`, `uuid-ossp` are all allowed). **`pg_search`/ParadeDB (Tantivy BM25) is not on the RDS allowlist** and Aurora does not support it either → true BM25 would require self-managed Postgres (EC2/ECS + ParadeDB image) or ParadeDB Cloud, i.e. **abandoning managed RDS** (high cost/ops, low ROI). This spec deliberately takes the RDS-compatible path: RRF over the two arms we already have.
