# Checkpoint: backend-dev — 2026-06-17 (canonical soft-delete fix)

## What was done
- Implemented the A→B→A stale-reuse correctness fix spanning both repos
- Go: added `CanonicalDocumentStore.SoftDeleteBySource`, hardened `UpsertByDraft` ON CONFLICT with `deleted_at=NULL`, added handler+route `POST .../soft-delete-by-source`, widened `canonicalDocStorer` interface, updated fake in handler test, added nil-DB + real-DB tests
- Python: added `KGClient.soft_delete_canonical_documents_by_source`, wired call into `engine.py` regenerate branch (between delete_document_subtree and upsert_canonical_document), added AsyncMock to `_make_mock_kg`, added stateful A→B→A regression test

## Files changed
- `ennam.kg.go/internal/store/canonical_document.go` — SoftDeleteBySource method + deleted_at=NULL in UpsertByDraft
- `ennam.kg.go/internal/store/canonical_document_test.go` — nil-DB test + 2 real-DB integration tests
- `ennam.kg.go/internal/handler/canonical_document.go` — interface widened, handler method, route registered
- `ennam.kg.go/internal/handler/canonical_document_test.go` — fake updated, 6 new handler tests
- `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py` — new method
- `ennam.kg.python/src/ennam_kg/ingestion/pipeline/engine.py` — soft-delete call in regenerate branch
- `ennam.kg.python/tests/ingestion/test_dedup.py` — mock updated + A→B→A regression test

## Current state
- Go: `go build ./...` clean, `go vet ./...` clean, gofmt clean; real-DB tests pass twice
- Python: 373 passed, 17 skipped, 0 failures; dedup suite 8/8 pass
- Commits: Go `cab4533`, Python `a7a3b89` on branch `task/implement_mcp`
- Report: `.git/sdd/final-fix-report.md`

## Next steps
- No known blockers from this fix
- main.go required no changes (handler already wired via RegisterRoutes)

## Blockers / Risks
- None
