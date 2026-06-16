# BUG: partial node updates REPLACE properties (UpdateService nodeReader is nil)

**Service:** ennam.kg.go
**Severity:** High (silent data loss on every partial node update, platform-wide)
**Found:** 2026-06-16, while implementing the RAG citation surface (FR-2)
**Status:** OPEN — deliberately deferred from the citation feature (needs its own change + regression review)

## Symptom
Every `PUT`/`PATCH /api/v1/nodes/{id}` **replaces** the JSONB `properties` instead of merging.
Any property not present in the update body is silently dropped.

Concrete impact: document hub nodes end up with only `{document_tree, section_count}` after the
decompose step's hub update — `summary`, `draft_id`, `source_type`, and (intended) `stored_path` are wiped.
The Cảng Định An hub showed this from the start.

## Root cause
`cmd/kg-server/main.go:369`:
```go
updateSvc := service.NewUpdateService(versionStore)   // <-- missing WithNodeReader(...)
```
With no node reader, `UpdateService.nodeReader == nil`, so `UpdateNode` (internal/service/update.go:127-134)
cannot fetch the existing node → `existing = nil` → `partial.MergeProperties(nil, update)` returns only the
update keys. The merge logic itself is correct; it just never receives the existing state.

## Fix (1 line) + why it's deferred
```go
updateSvc := service.NewUpdateService(versionStore, service.WithNodeReader(nodeStore))
```
Deferred because turning the reader on also:
1. Activates real **merge** semantics for ALL partial updates (behavior change platform-wide).
2. Activates **Gate 2 completeness validation on updates** (update.go:138 runs only when `existing != nil`) —
   updates that currently bypass Gate 2 may start failing.
Both need deliberate regression testing (node update flows, code-index differ updates, type-specific
`kg_update_*` tools, decompose hub update).

## Verification snippet
Create a `document` node with `{summary, stored_path}` → DB has both. `PUT` with
`{document_tree, section_count}` → DB now has only `{document_tree, section_count}`. After the fix, all four
keys should survive.

## Relation to RAG citation (FR-1 shipped)
FR-1 citation does NOT depend on this: it cites by `title` (filename, a top-level column, never wiped) +
section title/lines from `kg_search`. FR-2's `stored_path` persistence is the only thing this bug blocks, and
`stored_path` is intentionally not exposed by the API — so FR-2 is future-proofing (D2-B), safe to defer until
this bug is fixed. FR-2 wiring code is already in place and becomes effective once the reader is wired.
