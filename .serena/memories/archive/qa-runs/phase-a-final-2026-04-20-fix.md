# QA Phase A Final Fix — Archive Write-Block for Node/Edge

**Date**: 2026-04-20
**Commit**: 79457ac on main
**Bug**: Node created (201) in archived project — archive write protection not effective

## Root Cause
ProjectID middleware checks archive status for URL-based routes (`/projects/{id}/*`). But `POST /api/v1/nodes` and `POST /api/v1/edges` receive `project_id` in the REQUEST BODY, not the URL. Middleware never sees the project_id → archive check never runs.

## Fix
Added `ProjectArchiveCheckerFunc` to `NodeHandler` and `LinkHandler`:
- Function type: `func(ctx, projectID) bool` — returns true if archived
- Called AFTER body decode, BEFORE service call
- Wired in main.go via `projectStore.GetByID() + p.IsArchived()`

## Files Changed
- `internal/handler/node.go` — added archiveChecker field + SetArchiveChecker + check in HandleStoreNode
- `internal/handler/link.go` — same pattern for HandleCreateLink
- `cmd/kg-server/main.go` — wired checker after projectStore creation

## Pattern
For routes where project context comes from request BODY (not URL), archive enforcement must be at the HANDLER level, not middleware level. This is a known limitation of URL-based middleware.
