# Checkpoint: backend-dev — 2026-06-18 — BA-031 Phase 8a Foundation

## What was done

All 9 tasks of BA-031 Phase 8a implemented, reviewed, and merged via subagent-driven development:

1. **Task 1 (Go):** Closed vocabulary registered at 3 surfaces — `ValidNodeTypes` map, DB CHECK constraint (migration 000061), `config.yaml` node_types + edge_whitelist. 8 new types + concept reused. 7 edge types enumerated.
2. **Task 2 (Go):** `chunk_extraction_state` table (migration 000062) + store (`ShouldSkip`, `FindStale`, `Upsert`).
3. **Task 3 (Go):** Internal resolution-candidates endpoint `POST /api/v1/internal/resolution/candidates` — semantic search filtered by min_similarity (default 0.82), top_k default 5.
4. **Task 4 (Go+Python):** `ExtractionMessage` struct + `ExtractionPublisher` interface + Redis impl. `POST /api/v1/ingestion/documents/{docId}/extract` trigger. Python queue message models + parse_message dispatcher + worker stubs.
5. **Task 5 (Python):** Closed-vocab Pass 1 extraction parser — drop-don't-coerce, span validation, orphan relation pruning.
6. **Task 6 (Python):** Bounded gleaning loop — early-stop, alias-union dedup, max_rounds cap.
7. **Task 7 (Python):** Pass 1 orchestrator — LLM → parse → glean → provenance attach → create nodes → embed + upsert. `embed_entity` uses `encode_query` (symmetric prefix), SHA256 hash.
8. **Task 8 (Go):** Recovery sweep `RunRecoverySweep` — FindStale → publish per status. `doc_id` column added (migration 000063) so recovery messages carry document ID (not chunk ID).
9. **Task 9 (Go):** 3 exit gate tests (closed-schema acceptance, idempotent skip-guard, crash-recovery with DocID assertion). `extraction.go` updated to call `Upsert("extracting")` before PublishExtractDocument (closes doc_id population gap).

**Final review Critical fix:** `provenance` field type changed from `string_array` → `json` in config.yaml (9 node type blocks). Python writes nested object; `string_array` validation would reject it → 400 on every Pass 1 create.

## Files changed

**Go (`ennam.kg.go`):**
- `config/config.yaml` — 8 new node_type blocks, edge_whitelist enumerated, 8 search blocks, provenance type → json
- `db/migrations/000061_ba031_closed_vocab.{up,down}.sql`
- `db/migrations/000062_chunk_extraction_state.{up,down}.sql`
- `db/migrations/000063_chunk_extraction_state_doc_id.{up,down}.sql`
- `internal/config/types.go` — NodeTypePerson/Org/Event/DocumentRef/Location/Artifact/MasterRecord/Project + ValidNodeTypes + ValidEdgeTypes
- `internal/config/types_test.go`
- `internal/handler/extraction.go` — trigger endpoint + ShouldSkip + Upsert("extracting") + publish
- `internal/handler/resolution_candidates.go` + `_test.go`
- `internal/jobengine/extraction_recovery.go` + `_test.go`
- `internal/queue/extraction_messages.go` + `_test.go`
- `internal/store/chunk_extraction_state.go` + `_test.go`
- `internal/store/ba031_gate_test.go`
- `internal/service/node_test.go` (provenance regression test)
- `internal/store/node.go` (minor additions)
- `cmd/kg-server/main.go` (wiring)

**Python (`ennam.kg.python`):**
- `src/ennam_kg/extraction/__init__.py`
- `src/ennam_kg/extraction/schema.py` — EXTRACTABLE_NODE_TYPES, CLOSED_EDGE_TYPES, ExtractedEntity, ExtractedRelation, ParseResult
- `src/ennam_kg/extraction/parser.py` — parse_extraction()
- `src/ennam_kg/extraction/gleaning.py` — merge_gleaned(), run_gleaning()
- `src/ennam_kg/extraction/embed.py` — embed_entity() with encode_query (symmetric prefix)
- `src/ennam_kg/extraction/pass1.py` — run_pass1() async orchestrator, Pass1Summary, Pass1Deps
- `src/ennam_kg/queue/messages.py` — ExtractDocumentMessage, ResolveDocumentMessage, parse_message()
- `src/ennam_kg/worker.py` — dispatch stubs for extract/resolve
- `tests/extraction/test_parser.py`, `test_gleaning.py`, `test_pass1.py`
- `tests/queue/test_messages.py`

## Current state

- All tasks complete, final review clean after Critical fix
- Go branch: cab4533..9ea1a23 (11 commits)
- Python branch: 397c852..b2a50a2 (6 commits)
- Both on `task/implement_mcp`
- `go build ./...` + `go vet ./...` + `make test` green
- `uv run pytest` → 390 passed / 17 skipped
- 3 BA-031 gate tests skip gracefully without `KG_TEST_DATABASE_URL` (real-DB CI convention)

## Next steps

- Create PR for `task/implement_mcp` → `main`
- **8b:** Labelled Vietnamese benchmark + threshold×K sweep (needs candidates endpoint from Task 3)
- **8b prerequisite:** Add `chunk_id` to `ExtractionMessage` before wiring 8b worker — per-chunk fan-out currently publishes N identical DocID messages per document (Important finding, deferred)
- **8c:** Pass 2 resolution in shadow mode

## Blockers / Risks

- Per-chunk message fan-out (Important, non-blocking for 8a): N chunks → N identical `extract_document` messages with same DocID. Fix: add `ChunkID string` to `ExtractionMessage` so Python processes one chunk per message. Must fix before 8b worker is wired.
- Cost-idempotency (zero LLM calls on 2nd run) verified only in Python unit tests, not Go integration test. Comment in Gate 2 test notes this.
