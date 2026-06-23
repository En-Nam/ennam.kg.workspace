# Checkpoint: claude-sonnet — 2026-04-20

## What was done
- Fixed 4 QA Phase A bugs in ennam.kg.go (4 commits on main)

## Files changed
- `internal/service/user.go` — extended UserAPIKeyService interface with GetKey; login now only revokes keys with "web-session-" label prefix
- `internal/service/apikey.go` — confirmed existing GetKey method (no duplicate added)
- `scripts/reset-and-seed.sql` — added separate web-session key (b0000002) for user account; Platform Admin Key (b0000001) stays permanent
- `internal/middleware/project.go` — added ProjectStatusCheckerFunc type; ProjectID middleware optionally blocks write ops on archived projects (403)
- `cmd/kg-server/main.go` — wired ProjectStatusCheckerFunc in buildRouter using projectStore.GetByID
- `internal/store/thread.go` — added ListThreadsOptions; List() default excludes archived threads; supports ILIKE search
- `internal/service/thread.go` — updated ListThreads signature to accept includeArchived + search params
- `internal/handler/thread.go` — passes include_archived and search query params to service
- `internal/ws/handler.go` — added Unwrapper interface + findFlusher() to walk ResponseWriter chain; fixes SSE 500 error

## Current state
- `go build ./...` passes cleanly (0 errors)
- All 4 bugs fixed and committed

## Next steps
- Run QA Phase A test suite to verify fixes
- Proceed to QA Phase B if Phase A passes

## Blockers / Risks
- None
