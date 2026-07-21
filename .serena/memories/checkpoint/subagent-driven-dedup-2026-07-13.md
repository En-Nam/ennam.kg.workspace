# Checkpoint: subagent-driven-development (document dedup) — 2026-07-13

## What was done
Executed `docs/superpowers/plans/2026-07-13-daab-document-dedup.md` in full, all 6 tasks, via superpowers:subagent-driven-development.

- Task 1: Go store `CanonicalDocumentStore.FindByContentHash(ctx, projectID, contentHash)` — global per-project content-hash lookup, `deleted_at IS NULL` filtered. TDD, real-DB tests, review clean.
- Task 2: Go handler — `GET .../canonical-documents/lookup?content_hash=H` (no `source_id`) → content-hash-only dedup mode, 200/404. Existing modes unchanged (12/12 lookup tests pass). Review clean.
- Task 3: Python `KGClient.find_canonical_document_by_content_hash(project_id, content_hash)` — mirrors `find_canonical_document_by_source`, 404→None, non-404→raise. Review clean.
- Task 4: Python `engine.py` tier-3 block inserted between tier-2's `continue` and `create_node`'s `try:` — reuses node on global-hash hit, fails loud (NFR-243) on non-404 lookup errors. Also fixed a second independent `_make_mock_kg` copy in `test_engine_canonical_persist.py` (not in plan scope, verified no-op safety net). Review clean.
- Task 5: Rebuilt kg-server/indexer/worker with Tasks 1-4. Proved prevention E2E in dev-project (a0000000-...-001, using the documented dev API key from `.env.example`): uploaded a unique-content file twice, doc count delta was exactly 1 (not 2), both drafts resolved to the same knowledge_node_id, worker log shows `content-hash dedup hit`. Also observed 3 more real dedup hits against pre-existing dev-project content during ad-hoc testing.
- Task 6 (DESTRUCTIVE — explicit user confirmation obtained via AskUserQuestion before running): cleaned up Cảng Định An (592c7ff7-9f6f-4cc5-9094-d9b3b685277e). Before: 145 docs / 378 sections / 626 chunks / 1864 similar_to edges / 145 live canonical rows (74 distinct hashes). Deleted edges → node_versions → nulled `draft_nodes.knowledge_node_id` (FK, not anticipated by plan) → hard-deleted `canonical_document` rows (plan said soft-delete, but `knowledge_node_id` is NOT NULL+FK'd so soft-delete alone can't unblock node deletion — hard-delete approved via a second AskUserQuestion, achieves identical no-stale-reuse goal) → deleted nodes. Verified hard gate (0 live nodes, 0 live canonical rows) before re-ingest. Re-ingested 79 real files (82 minus 3 `.DS_Store`) via the dev API key. Result: **77 documents, 77 distinct content_hash** (docs==distinct_hash invariant holds), 0 failed drafts, 0 dup_doc_similar_edges (148 similar_to edges total, none between duplicate-hash docs).

## Files changed
- `ennam.kg.go/internal/store/canonical_document.go`, `canonical_document_test.go` (Task 1, commit eeba198)
- `ennam.kg.go/internal/handler/canonical_document.go`, `canonical_document_test.go` (Task 2, commit d1d24ce)
- `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py`, `tests/ingestion/test_kgclient_canonical.py` (Task 3, commit 74ce55b)
- `ennam.kg.python/src/ennam_kg/ingestion/pipeline/engine.py`, `tests/ingestion/test_dedup.py`, `tests/ingestion/test_engine_canonical_persist.py` (Task 4, commit 0aee823)
- No production-code commits for Tasks 5-6 (operational only). Data changes are in the shared dev Postgres, not git.
- Ledger: `.superpowers/sdd/dedup-progress.md` (full detail, all task diffs/base-heads).

## Current state
- All 4 code tasks (Go store, Go handler, Python client, Python engine) implemented, TDD'd, task-reviewed clean (0 Critical/Important across all 4).
- Prevention proven live E2E on the rebuilt stack.
- Cảng Định An cleaned and re-ingested; duplicate-free (77 docs = 77 distinct hashes).
- Sala Food / other projects untouched (cleanup was scoped to Cảng Định An's project_id only).
- Final whole-branch code review NOT yet run — next step.

## Next steps
- Dispatch the final whole-branch code-reviewer (most capable model) over the full diff across both nested repos (Go base 0b4d507..HEAD, Python base 7edd9dd..HEAD) before calling this done. Then superpowers:finishing-a-development-branch to decide push/PR.
- No push has happened yet — commits are local to `task/implement_docs_sync` in both nested repos.

## Blockers / Risks
- None outstanding. The two plan deviations (hard-delete instead of soft-delete on canonical_document; nulling draft_nodes.knowledge_node_id) were both explicitly user-approved mid-execution via AskUserQuestion and are documented in `.superpowers/sdd/dedup-progress.md`.
- Backlog memory `backlog/daab-retrieval-quality-gaps-postfix` should be updated to mark the dedup gap resolved (not yet done — do this alongside/after final review).
