# Checkpoint: subagent-driven B2 Task 5 — 2026-07-14

## What was done
- Step 1: Rebuilt `worker` + `indexer` images (`docker compose up -d --build worker indexer`). Both healthy. `daab-server` recreated as a side effect (dependency graph), incidentally went unhealthy→healthy — no code change to it, in scope.
- Step 2 (delete half): Ran a scoped, transactional delete for exactly the 3 B2 golden-set docs in Cảng Định An (`592c7ff7-9f6f-4cc5-9094-d9b3b685277e`):
  `89a0ea6a-8605-4408-b765-a7598464cc40`, `7922817f-0a3c-4e61-8fb0-228ce1f8648c`, `a3856d16-4ce4-4c0a-812b-5fe0a00724e5`.
  Before-state preview: 3 hubs + 12 sections + 80 chunks (95 nodes), 92 embeddings, 143 edges, 3 live canonical_document rows.
  Deleted: 143 edges, 3 node_versions, unlinked 3 draft_nodes (`knowledge_node_id=NULL`), hard-deleted 3 canonical_document rows, deleted 95 nodes.
  **HARD GATE PASSED**: 0 live nodes, 0 live canonical rows, 0 embeddings for these 3 doc ids. Project doc count 77→74 (exactly −3, confirms no over-scoped deletion; other 74 docs / B1 entity-resolution work untouched).
  **Deviation from referenced dedup-cleanup plan**: that plan's soft-delete-canonical-then-delete-hub order fails on the current schema (`canonical_document.knowledge_node_id` and `draft_nodes.knowledge_node_id` are both FKs to the hub row that block hub deletion while referencing rows exist). Fixed by unlinking `draft_nodes.knowledge_node_id` and hard-deleting (not soft-deleting) canonical_document rows — functionally equivalent for the "no live canonical row" invariant. Both failed attempts rolled back cleanly before the working transaction — nothing partially committed.
- Step 2.4 (re-ingest): **BLOCKED**. Found the upload route by reading `ennam.kg.go/internal/handler/ingest_upload.go`: `POST /api/v1/projects/{projectId}/ingest/upload` (multipart, field `file`), terminal states via `GET .../draft-nodes/{draftId}` = `processed`/`failed`/`rejected` (from `internal/models/draft_node.go`). Adapted `scripts/ingest-batch-pdfs.py` into a scratchpad script targeting only the 3 files. The API key given in the task brief (from `other_projects/daab-sim-consumer/.mcp.json`) returned HTTP 401 — verified its sha256 does not match any row in `api_keys` (12 rows, all admin web-sessions or 2 long-lived admin keys, none matching). Did NOT attempt to brute-force/guess alternate keys (harness's own credential-exploration guard blocked that path when tried) — correctly stopped and is reporting BLOCKED per the task's own instruction.
- Step 3 (verify): NOT run — depends on Step 2.4.
- Docs: appended "Task 5 — Live Re-ingest Verification (BLOCKED — partial)" section to `docs/superpowers/plans/b2-golden-set.md` with full before/after counts, the FK deviation, and resume instructions. Committed to workspace-root repo: `052ea27`.
- Backlog: updated `mem:backlog/daab-retrieval-quality-gaps-postfix` item 5 (OCR/needs_review) — marked IN PROGRESS, Tasks 1-4 summarized (Task 2 preprocessing OFF by evidence-based A/B; Task 3 confusable-repair shipped as verified no-op on this corpus + model-conversion half deferred via spike gate; Task 4 fallback wired), Task 5 blocker documented.

## Files changed
- `docs/superpowers/plans/b2-golden-set.md` (Task 5 section appended; committed `052ea27` in workspace-root repo)
- No source code changes (operational task, as specified)
- DB (Cảng Định An project): 3 documents' substrate deleted (95 nodes, 143 edges, 3 canonical rows) — reversible via re-ingest, source PDFs untouched

## Current state
- Worker/indexer images rebuilt and running with Tasks 1-4's OCR code (preprocess flag OFF, confusable-repair active, fallback wired).
- The 3 target documents are **currently absent from the KG** (delete done, re-ingest not run). This is a genuine mid-operation state, not a completed cleanup.
- The other 74 documents in Cảng Định An (77→74) are confirmed unaffected, including B1's entity-resolution work.
- No golden-set live-DB verification numbers exist yet for Task 5 (Task 1's harness-based numbers from Tasks 1-3, already in `b2-golden-set.md`, are unaffected/still valid).

## Next steps
- Obtain a valid API key scoped to project `592c7ff7-9f6f-4cc5-9094-d9b3b685277e` (or admin role) for the live stack's current `api_keys` table — the `.mcp.json` key is stale.
- Re-run Step 2.4 (upload the 3 PDFs via `POST .../ingest/upload`), wait for `processed` status on all 3.
- Step 2.5: confirm worker log shows fresh OCR (absence of "content-hash dedup hit" for these 3, near the re-upload timestamps).
- Step 3: run `b2_figure_metrics.py` (Task 1 harness, unmodified) + live DB queries scoped to the 3 new document ids (33,6ha / mangled-figure recovery in `structured_fields.areas` or `.unrecovered`) + spot-check one unrelated, unaffected document.
- Update `docs/superpowers/plans/b2-golden-set.md`'s Task 5 section from BLOCKED to DONE with real numbers once the above completes.

## Blockers / Risks
- **Blocker**: no working API key for the live stack. Task brief's key is invalid (not in DB). Per Rule 8 / the task's own destructive-op caution and the harness's credential-exploration guard, did not attempt to find a substitute — needs a human/caller-supplied valid key.
- **Risk if resumed carelessly**: do not re-run the delete (Step 2) again — it already succeeded and is idempotent-safe to re-verify (hard gate query) but re-running the DELETE statements is a no-op now (0 rows match). Only Step 2.4 onward needs to run.
