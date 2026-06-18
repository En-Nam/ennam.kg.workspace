# Checkpoint: backend-dev — 2026-06-17 — BA-030 Canonical Ingest Core

## What was done
Implemented the full BA-030 plan (canonical ingest core) via subagent-driven development — 17 plan tasks + 1 plan-gap fix + 1 final-review bug fix. Every task gated by spec+quality review; fixes re-reviewed.

- P0: migration 000060 `canonical_document` table; characterization golden (md/txt/pdf chunk path).
- P1: `normalize_canonical_text`, `build_canonical_document` (single producer, fail-loud, chunkable-format gate), Go model/store/REST endpoints, KGClient methods, persist canonical in `run_batch`.
- P2: config gate `ingestion.require_upload_approval` (default OFF = index immediately), worker honors flag, Go ceases synchronous text extraction.
- P3: pinned AAA chunk-level read contract + NFR-247 golden.
- P4: dedup reuse + document-subtree hard-delete (cascade verified on live DB) + content-change regenerate. **Plan gap found+fixed (4.1.5):** added source-only canonical lookup (`FindBySource` + optional-hash endpoint + KGClient) — user chose additive Hướng 1.
- P5: `decompose_document` consumes canonical chunks (NFR-248, no re-parse); full verification + lint.
- **Final whole-branch review (opus): bug fixed** — regenerate didn't soft-delete prior live canonical row → A→B→A revert on stable source_id (satellite_api/jira/google_drive) served stale chunks. Added `SoftDeleteBySource` + revive `deleted_at` on upsert + regenerate supersede + A→B→A regression test.

## Files changed
Go (ennam.kg.go): db/migrations/000060_*, internal/models/canonical_document.go, internal/store/canonical_document.go (+test), internal/store/node.go + node_subtree_test.go, internal/handler/canonical_document.go (+test), internal/service/ingestion_settings.go (+test), internal/service/file_upload.go (+test), internal/queue (IngestionMessage), cmd/kg-server/main.go.
Python (ennam.kg.python): ingestion/pipeline/{normalize,canonical,engine,decompose}.py, kg_client/client.py, worker.py; tests/ingestion/{test_normalize,test_canonical,test_dedup,test_decompose_canonical,test_characterization,test_aaa_non_regression,test_kgclient_canonical,test_engine_canonical_persist}.py, tests/test_worker_extract_gate.py.
Workspace: docs/superpowers/specs/2026-06-17-canonical-ingest-core-design.md (chunk-level contract pin).

## Current state — DONE, verified green
- Go: `go build`/`go vet` clean; `go test ./...` (gate-off / CI) exit 0, 20 pkgs ok; gofmt clean; real-DB canonical/subtree/FindBySource/soft-delete tests pass & re-runnable.
- Python: full suite 373 passed / 17 skipped; ruff clean on our files.
- All NFRs (239/240/241/243/244/247/248/249) have green tests.
- Branch ranges: Go efae831..cab4533 ; Python 04b6048..397c852 (branch task/implement_mcp, both nested repos).

## Next steps
- Open PRs for both nested repos (not yet pushed). Branch is task/implement_mcp.
- Optionally write back BA-030 decisions to KG MCP (was not queried this session).

## Blockers / Risks
- BACKLOG: hub node's own title/summary not refreshed on content-change regenerate (stale hub summary for high-churn docs) — scoped out of v1; needs follow-up `update_node(hub)`.
- Pre-existing (NOT BA-030): `favorite_test.go` fails under forced real-DB (invalid UUID "test-user-id"); ruff debt in test_queue/test_summarizer/test_worker/benchmark; `golangci-lint` binary not installed locally (used `go vet`+`gofmt` as proxy).
