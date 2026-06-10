# Checkpoint: backend-dev — 2026-06-10

## What was done
- Implemented IMP-005 (Hybrid Search RRF + Multilingual Embedding) — all 11 tasks complete
- Task 1: e5 prefix methods (`encode_query`, `encode_passage`, `_needs_e5_prefix`) in `local_model.py`
- Task 2: `input_type` field on `EmbeddingRequest`; `/api/v1/embed` routes to correct prefix method
- Task 3: Ingestion pipeline `decompose.py` calls `encode_passage` instead of raw `encode`
- Task 4: Default embedding model changed to `intfloat/multilingual-e5-small` (384-dim) in `config.py`
- Task 5: `POST /api/v1/admin/reembed` endpoint in `src/ennam_kg/api/admin.py`; registered in `main.py`
- Task 6: `list_node_embeddings` method added to `KGClient` in `packages/ennam-kg-indexer`
- Task 7: `ReciprocalRankFusion` function in `internal/store/rrf.go`
- Task 8: Hybrid search mode in `internal/handler/search.go` — `effectiveSearchMode`, `handleHybrid`, `ensureQueryEmbeddingForHybrid`, `respondFulltext`; interfaces `lexicalSearcher`/`semanticSearcher`
- Task 9: `ListByProject` on `NodeEmbeddingStore` + `GET /api/v1/projects/{id}/node-embeddings` in `document.go`
- Task 10: `mode` param (`fulltext|semantic|hybrid`) added to `kg_search` MCP tool in `bridge/schema.go`; `document_section` added to `node_types` enum
- Task 11: Eval harness — `tests/eval/dataset.json` (6 query pairs) + `tests/eval/retrieval_eval.py` (recall@5, MRR, 3 modes)

## Files changed

**Python (ennam.kg.python):**
- `src/ennam_kg/embeddings/local_model.py` — e5 prefix methods
- `src/ennam_kg/embeddings/models.py` — `input_type` field
- `src/ennam_kg/api/embeddings.py` — routes to encode_query/encode_passage
- `src/ennam_kg/ingestion/pipeline/decompose.py` — encode_passage at ingestion
- `src/ennam_kg/config.py` — default model = multilingual-e5-small
- `src/ennam_kg/api/admin.py` — NEW: reembed endpoint
- `src/ennam_kg/main.py` — admin router registered
- `packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py` — list_node_embeddings
- `tests/test_embeddings/test_prefix.py` — NEW
- `tests/test_embeddings/test_endpoint_input_type.py` — NEW
- `tests/ingestion/test_decompose_passage.py` — NEW
- `tests/test_config_model.py` — NEW
- `tests/test_admin_api.py` — NEW
- `tests/eval/dataset.json` — NEW
- `tests/eval/retrieval_eval.py` — NEW

**Go (ennam.kg.go):**
- `internal/store/rrf.go` — NEW: ReciprocalRankFusion
- `internal/store/rrf_test.go` — NEW
- `internal/handler/search.go` — hybrid mode, interfaces, rrfK
- `internal/handler/search_mode_test.go` — NEW
- `internal/handler/search_hybrid_test.go` — NEW
- `internal/store/node_embedding.go` — NodeEmbeddingRow, ListByProject
- `internal/store/node_embedding_list_test.go` — NEW
- `internal/handler/document.go` — ListNodeEmbeddings handler
- `internal/bridge/schema.go` — mode param, document_section in node_types
- `internal/bridge/schema_mode_test.go` — NEW

## Current state
- All 20 Go packages pass `go test ./... -race`
- All 20 IMP-005 Python tests pass
- Ruff clean on all IMP-005 Python files
- No new migrations (migration count still 110)
- BA-020 (1536-dim) not touched
- Branch: `task/implement_mcp`

## Next steps
Before production go-live (BR-007 backfill):
1. Fill real `project_id` + `expected_node_id` in `tests/eval/dataset.json`
2. Run `POST /api/v1/admin/reembed {"project_ids": [...]}` to backfill all rows to e5 embeddings
3. Run `tests/eval/retrieval_eval.py` to verify recall@5 improvement vs all-MiniLM baseline

## Blockers / Risks
- None for code. Operational backfill (step 2 above) must run before hybrid search returns meaningful vector results on existing data.

---

# Session 2 (2026-06-10) — Verify live + finish

## What was done
Verified IMP-005 end-to-end on the running stack; the "Next steps" above are now DONE.

### Verify found + fixed
- **Python unit regression (IMP-005)**: `test_embeddings_api` still mocked old `encode`; endpoint now
  routes by `input_type` → `encode_query`/`encode_passage`. Fixed mock. → committed.
- **Container blocker (BA-026, not IMP-005)**: rebuilt image crash-looped — Dart parser
  `get_language("dart")` at import + e5 HF cache both need a writable home, but `USER ennam` had none →
  "Permission denied (os error 13)". Fixed `ENV HOME=/tmp` + `HF_HOME` in `ennam.kg.python/Dockerfile`. → committed.

### Live verification (project Cảng Định An, 14 sections)
- Cutover OK: `/api/v1/embeddings` → `intfloat/multilingual-e5-small`, 384-dim.
- Re-embed OK: `POST /api/v1/admin/reembed` → 14 rows all-MiniLM → e5.
- **Regression fixed**: "rủi ro pháp lý / giấy phép môi trường" — all-MiniLM returned wrong "8. Điểm mạnh";
  e5 returns legal/risk sections (all 3 modes).
- Eval (recall@5/MRR): VI recall 1.0 all modes, MRR **hybrid 0.833 > 0.667**; EN fulltext/semantic 0@top-5,
  **hybrid recovers 1.0**. Corpus 14 sections → too small for a hard gate (recall saturates).

## Files changed (session 2)
- `ennam.kg.python/tests/test_embeddings_api.py`, `ennam.kg.python/Dockerfile` (committed)
- `ennam.kg.requirements/.../IMP-005-*.md` — Status Draft → **Implemented (verified live)** + results (committed)
- dataset.json kept as template (real ids used to run eval, then reverted)

## Current state
- IMP-005 FR-1..5 implemented + **verified live**; stack healthy on e5. All source committed on `task/implement_mcp`.

## Next steps (updated)
- Optional `/code-review` of the IMP-005 diff. Expand eval to 20–30 pairs / larger corpus. Persistent HF
  cache volume. Consider `mode=hybrid` default after tuning `k`.
- Separate debt: ~9 Python fails in agentic/streaming/benchmark (pre-existing) + earlier Go handler/middleware/models debt.
