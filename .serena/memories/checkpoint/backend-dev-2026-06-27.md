# Checkpoint: backend-dev — 2026-06-27

## What was done
- Implemented BA-033 in full across 5 tasks (subagent-driven development)
- Task 1: Added `ParentSections` + `SharedEntityNeighbors` to `GraphRetrieveStore` (`internal/store/graph_retrieve.go`)
- Task 2: Added `SectionExpander` interface + variadic `Option`/`WithSections` + parent-child mode to `GraphRetriever`
- Task 3: Added `EntityExpander` interface + `WithEntities` + entity-anchored mode; `Bundle.EntityNeighbors` field
- Task 4: Wired `mode` param in handler; wired `WithSections(graphRetrieveStore)` + `WithEntities(graphRetrieveStore)` in `main.go`
- Task 5: Wrote eval script `ennam.kg.python/eval/eval_ba033_retrieval.py` (live eval deferred — no document_chunk nodes in docker DB)
- Final review fix: Added `status='active'` filter to both new store queries (H1); DB tests verified on port 5433 (H2)
- Final whole-branch review: **READY** — all constraints pass, 3 Notes only (none blocking)

## Files changed
- `ennam.kg.go/internal/store/graph_retrieve.go`
- `ennam.kg.go/internal/store/graph_retrieve_test.go`
- `ennam.kg.go/internal/service/graph_retriever.go`
- `ennam.kg.go/internal/service/graph_retriever_test.go`
- `ennam.kg.go/internal/handler/graph_retrieve.go`
- `ennam.kg.go/internal/handler/graph_retrieve_test.go`
- `ennam.kg.go/cmd/kg-server/main.go`
- `ennam.kg.python/eval/eval_ba033_retrieval.py`

## Current state
- All 6 commits merged to branch `task/implement_docs_sync`: `465ac70` → `4931928` → `d55c662` → `a50f4cc` → `54980ef` → `3237743` → `aab1f22`
- Build clean, `go vet` clean, full test suite + `-race` passes
- DB-backed store tests pass on port 5433
- Final review: READY

## Next steps
- Create PR for `task/implement_docs_sync` → `main`
- Seed 10-doc corpus in docker: rebuild docker binary with new code, seed `document_chunk` nodes
- Run `eval/eval_ba033_retrieval.py` against live server to measure marginal improvement per mode
- Resolve 3 Notes if desired: (1) reject unknown mode with 400, (2) document same-doc section limitation, (3) add secondary ORDER BY `node_id` in SharedEntityNeighbors for determinism

## Blockers / Risks
- Live eval still blocked: docker DB has 0 `document_chunk` nodes; docker container runs old binary (needs rebuild)
- `dragoon@exnodes.vn` login fails — empty `password_hash` in docker DB; dev API key still works
