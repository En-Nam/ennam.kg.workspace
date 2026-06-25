# Checkpoint: backend-dev (SDD controller) — 2026-06-19

## What was done
- Implemented IMP-009 (MCP File Ingest & Linkage) plan end-to-end via subagent-driven development: 8 tasks, fresh implementer + reviewer per task, opus final whole-feature review.
- Feature: MCP-only satellites drive the existing file pipeline. kg_request_file_upload (local intent tool) → POST /files raw streaming proxy → kg_ingest_status (read-side status from canonical_document+draft_nodes) → kg_get_document download_url → GET /files/{document_id} download proxy.
- Security hardening beyond the plan (from reviews): 404-vs-500 split on ingest-status; project-id/doc-id/resolved-upload-id path-segment validation; upstream-header test asserts; and (per user decision) in-route HasProjectAccess IDOR guard on the two new Go handlers (spec §5).

## Files changed (in nested repo ennam.kg.go)
- internal/store/uploaded_file.go (+FindByDraftNodeID, GetIngestStatusRow, FindDraftByKnowledgeNode) + test
- internal/handler/ingest_status.go (new: deriveIngestStatus, Status, ResolveUploadByDocument, HasProjectAccess guard) + test
- internal/handler/document.go (buildDocumentMeta + download_url) + document_test.go
- internal/bridge/{client,schema,serve,files_proxy}.go (kg_ingest_status route, kg_request_file_upload local tool, POST/GET /files proxies) + tests
- cmd/kg-server/main.go (register ingest-status handler)
- Tool count: 40 schemas = 37 routed + 3 local (invariant holds)

## Current state
- All committed on branch task/implement_mcp in nested repo ennam.kg.go (commits f85223f..b4edbe8, 11 commits).
- go build ./... + go vet ./... clean; all 22 packages' tests pass; 2 new SQL correlation queries validated against real Postgres.
- Final review verdict: READY TO MERGE.

## Next steps
- Optional: run `make lint` in CI (golangci-lint absent on dev host; go vet was the substitute).
- Optional: full HTTP end-to-end smoke (bridge --http mode: upload→poll→resolve→download) in a live env — deferred per plan Task 8.
- Deferred per spec: IMP-008 client-side confirm classification for kg_request_file_upload; typed BR-006 failure reason for kg_ingest_status.
- Not merged/PR'd — awaiting user direction.

## Blockers / Risks
- None. Bridge is single-project (cfg.DefaultProjectID); X-KG-Project-Id override now access-checked in-route on the Go side.

## Deep-verification addendum (same day)
Adversarial opus audit + fixes:
- 896421e: POST /files now returns 502 (upstream down/timeout) vs 413 (real oversize via *http.MaxBytesError).
- f91d24c: /files routes pinned to cfg.DefaultProjectID, X-KG-Project-Id ignored (bridge = per-project satellite; closes IDOR regardless of key scope).
All IMP-009 tests pass with real Postgres (KG_TEST_DATABASE_URL). Whole-repo build+vet clean. Final HEAD=f91d24c (13 commits 3fefe16..HEAD).
Pre-existing unrelated DB-test failures (favorite, section_neighbors) are NOT IMP-009.
