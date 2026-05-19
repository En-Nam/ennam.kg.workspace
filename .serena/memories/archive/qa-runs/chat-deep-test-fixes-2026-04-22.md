# /chat Deep Test — Go API Fixes Applied (2026-04-22)

## Commit: `0835d6f`

### Fix 1: Thread search returns [] not null (P1)
- `scanRows` used `var threads []*T` which stays `nil` when no results
- Changed to `make([]*T, 0)` → JSON serializes to `[]` instead of `null`
- File: `internal/store/thread.go`

### Fix 2: Thread name max length 100 chars (P2)
- `MaxThreadNameLength` changed from 255 → 100 per BA spec
- Both `CreateThread` and `RenameThread` already validate against this constant
- File: `internal/models/thread.go`

### Fix 3: Invalid UUID returns 400 not 500 (P2)
- Added `requireThreadID()` helper that validates UUID format before hitting DB
- Applied to all 6 thread handler methods (GetThread, RenameThread, ArchiveThread, UnarchiveThread, DeleteThread, ListMessages)
- File: `internal/handler/thread.go`

## Remaining (NextJS team — not Go):
1. P0: Replace `const projectId = 'default'` with `useProject()` in 2 chat page files
2. P1: BFF SSE proxy for streaming
3. P2: Wire ResponseRenderer + ToolMenu + SuggestedActions + InsightCards into /chat production
