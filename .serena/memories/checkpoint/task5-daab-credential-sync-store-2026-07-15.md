# Checkpoint: Task 5 (DAAB doc-sync plan) — 2026-07-15

## What was done
- Wired `credential_encrypted` into `internal/store/source_connection.go` (Create/GetByID/ListByProject/GetByWebhookSecret/Update/scanSourceConnection).
- Added `internal/store/aaaa_synced_document.go`: `AAAASyncedDocumentStore` with `UpsertSyncedDoc` (ON CONFLICT upsert), `GetSyncedDoc`, `ListFailed`.
- Added `SourceConnectionService.CreateWithCredential` / `.DecryptCredential` (AES-256-GCM via `internal/crypto`, mirrors `DataSourceService.encKey` pattern exactly). Extended `NewSourceConnectionService(store, logger, encKey)` — 3rd arg added.
- TDD: RED confirmed via `git stash` (compile errors), GREEN after restore. All new tests pass, incl. `-race`.
- Live-verified against `ennam-kg-postgres:5432` (migration 000076 applied) with a throwaway `cmd/verifytmp` — round-tripped credential_encrypted through Create/Update, verified ON CONFLICT upsert on aaaa_synced_document, deleted the temp dir afterward.

## Files changed
- `ennam.kg.go/internal/store/source_connection.go` (modified)
- `ennam.kg.go/internal/store/aaaa_synced_document.go` (new)
- `ennam.kg.go/internal/store/aaaa_synced_document_test.go` (new)
- `ennam.kg.go/internal/service/source_connection.go` (modified)
- `ennam.kg.go/internal/service/source_connection_test.go` (new)
- Commit: `cc2a73c` in `ennam.kg.go` (nested git repo) on branch `task/implement_docs_sync`.
- Full report: `docs-workspace/.superpowers/sdd/task-5-report.md` (overwrote a stale unrelated report that had reused this filename from an old task-numbering scheme).

## Current state
- `go build ./internal/...` passes clean; `go vet` clean; `gofmt` clean.
- `go build ./...` fails ONLY at `cmd/kg-server/main.go`'s `NewSourceConnectionService` call site (2-arg → 3-arg mismatch) — expected, explicitly Task 7's scope (main.go composition-root wiring). No other call sites exist repo-wide.

## Next steps
- Task 6/7 will wire `encKey` through `cmd/kg-server/main.go` and build the AAAA connect/sync handler flow on top of `CreateWithCredential`/`DecryptCredential` and the `aaaa_synced_document` store.
- Design note for later tasks: `SourceConnectionStore.Update`'s `credential_encrypted` SET is unconditional (not the CASE-WHEN-preserve-if-null pattern `DataSourceStore.Update` uses) — safe today only because all current callers fetch-then-update. Flag if a bare-struct `Update` call path is ever added.

## Blockers / Risks
- None. Task complete and self-reviewed.
