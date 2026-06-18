# Checkpoint: backend-dev — 2026-06-16 (RAG Citation Surface)

## What was done
- Implemented Phase 1 of the RAG citation surface (spec/plan dated 2026-06-16).
- **FR-1 (works, verified E2E):** `kg_get_document` MCP tool + new Go endpoint `GET /nodes/{id}/document-meta`
  returning `{node_id, title(filename), source_url, section_count}` (no document_tree, no stored_path).
- **Security fix (from commit review):** added path-level project-access check (404 on deny) and dropped
  internal `stored_path` from the response.
- **FR-2 (BLOCKED — see below):** wired `stored_path` from upload → draft.metadata (Go) → `build_node_payload`
  (Python param + metadata fallback). Backfilled the existing Cảng Định An hub via one-off SQL (that one persisted).
- Docs: BA-002 updated with `kg_get_document` + LAAM citation pattern.

## Files changed (all committed)
- `ennam.kg.go/internal/handler/document.go` (GetDocumentMeta + access check)
- `ennam.kg.go/internal/bridge/{schema,client}.go` + 4 test count fixes (33→34 / 31→32)
- `ennam.kg.go/internal/service/file_upload.go` (stored_path into draft.metadata)
- `ennam.kg.python/.../pipeline/{nodes,engine}.py`, `worker.py`, `tests/ingestion/test_nodes.py`
- `ennam.kg.go/db/backfill/2026-06-16-hub-stored-path.sql`
- `ennam.kg.requirements/.../BA-002-mcp-bridge.md`

## Current state
- **FR-1 fully working** — citation goal (filename + section + lines) is MET by FR-1 alone: `kg_get_document`
  returns `title`=filename (a top-level column, never wiped), `kg_search` gives section title + lines.
- **FR-2 stored_path does NOT persist on new-upload hubs.** Root cause is a **pre-existing global bug**, not FR-2:
  - `cmd/kg-server/main.go:369` builds `NewUpdateService(versionStore)` WITHOUT `WithNodeReader(...)`.
  - So `UpdateService.nodeReader == nil` → `UpdateNode` can't fetch `existing` → `MergeProperties(nil, update)`
    → every `PUT/PATCH /nodes/{id}` **REPLACES** properties instead of merging.
  - decompose's hub update (`{document_tree, section_count}`) therefore wipes `summary/draft_id/source_type/stored_path`.
  - Verified empirically: create persists `{summary, stored_path}` to DB; a decompose-style PUT leaves only
    `{document_tree, section_count}`.
- Impact of the bug is broad: ALL partial node updates silently drop unspecified properties (document hubs
  have only `{document_tree, section_count}` — true for the original Cảng hub too).

## Next steps (decision needed from user)
- Recommended: **ship FR-1** (citation works), **defer FR-2** (stored_path is future-proofing for D2-B, not
  returned by the API, not needed for citation), and **file the UpdateService nodeReader bug separately** —
  it's a 1-line wiring fix (`WithNodeReader(nodeStore)`) but turns on merge + Gate-2-on-update globally, so it
  needs its own change + regression review (blast radius).
- Alternative: fix the wiring now (makes FR-2 work) — but treat as a separate, reviewed change.

## Blockers / Risks
- The nodeReader-nil bug means partial updates are lossy platform-wide. Fixing it may surface Gate-2
  validation on updates that currently bypass it. Needs deliberate testing.

## UPDATE — bug fixed, FR-2 now works (same day)
- Fixed the UpdateService nodeReader bug: `cmd/kg-server/main.go` now wires
  `service.WithNodeReader(nodeStore)` → partial updates MERGE properties (Gate 2 stays off, no cfg wired).
- Full internal Go suite green (20 packages, no regressions). E2E: PUT preserves properties; a fresh upload
  hub now carries both `stored_path` and `document_tree`. FR-2 is no longer deferred.
- Removed the backlog item (resolved). Both FR-1 and FR-2 verified.
