# Checkpoint: backend-dev — 2026-06-17 Task 4.2a

## What was done
- Implemented BA-030 FR-004 document subtree hard-delete across two repos
- Verified document_section nodes DO carry `properties->>'document_id'` (decompose.py:96)
- Discovered knowledge_edges FKs have NO ON DELETE CASCADE (migration 000006) — store method deletes edges → node_versions → nodes in that order
- knowledge_node_embeddings DOES have ON DELETE CASCADE (migration 000055) — handled automatically
- All tests pass; Go real-DB integration test skips (KG_TEST_DATABASE_URL not set)

## Files changed

### ennam.kg.go (commit b4f653a)
- internal/store/node.go — DeleteDocumentSubtree(ctx, projectID, hubNodeID) (int, error)
- internal/store/node_test.go — 3 nil-DB guard tests
- internal/store/node_subtree_test.go — NEW, real-DB integration test with edge seeding
- internal/handler/canonical_document.go — nodeSubtreeDeleter interface, DeleteSubtree handler, constructor updated
- internal/handler/canonical_document_test.go — fakeNodeSubtreeDeleter, 3 handler tests
- cmd/kg-server/main.go — pass nodeStore to NewCanonicalDocumentHandler

### ennam.kg.python (commit 561d4c1)
- packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py — delete_document_subtree
- tests/ingestion/test_kgclient_canonical.py — 4 new tests

## Current state
- Task 4.2a: COMPLETE
- Go build: clean
- Go tests (handler + store): all pass
- Python tests (test_kgclient_canonical.py): 11/11 pass
- Real-DB integration test: written and skipped (needs KG_TEST_DATABASE_URL)

## Next steps
- Task 4.2b: regenerate path — calls delete_document_subtree then re-runs the ingestion
  pipeline for the document to produce fresh section+chunk nodes
- The real-DB integration test should be validated with a live DB before Task 4.2b ships

## Blockers / Risks
- None blocking 4.2b
- knowledge_edges ON DELETE CASCADE missing is a known schema gap (flagged in report);
  the store method works around it but a future migration to add CASCADE would simplify
