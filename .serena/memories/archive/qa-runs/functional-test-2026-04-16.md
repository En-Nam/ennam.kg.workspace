# QA Functional Test Results — 2026-04-16

## Summary
- 105 API endpoints tested, 73 working (70%), 32 with errors (30%)
- 30 Dashboard pages tested, 28 working, 1 placeholder, 1 missing
- 9 dead CTAs found, 13 bugs total (2 P0, 5 P1, 4 P2, 3 P3)

## P0 Critical Bugs
1. **UserIdentity never injected** — `internal/middleware/auth.go` only sets DeveloperIdentity, never UserIdentity. Blocks 15 endpoints: threads, favorites, AI streaming, export. **Go API team**.

## P1 High Bugs
2. **Session creation enum mismatch** — `pq: column "status" is of type session_status but expression is of type text`. **Go API team**.
3. **Project members all 500** — project_members table schema mismatch. Archive, list, add, change role, remove all fail. **Go API team**.
4. **Settings update always 500** — PUT /settings/{key} fails for all keys. **Go API team**.
5. **Benchmark subsystem entirely broken** — All benchmark endpoints return 500. **Go API team**.
6. **Create Project CTA dead** — navigates to `/projects/new` which has no page file. **NextJS team**.
7. **Edit Project CTA dead** — onClick handler produces no visible result. **NextJS team**.

## Dead CTAs
1. /projects "Create Project" → navigates to dead route
2. /projects/[id] "Edit" → does nothing
3. /settings "Archive Project" → disabled no tooltip
4. /admin/sync "Trigger Sync" → disabled no tooltip
5. /admin/sync "Export CSV" → disabled no tooltip
6. /chat-demo "Explain" → disabled no tooltip
7. /chat-demo 2 ghost buttons → empty, disabled, no label
8. /query send icon → disabled no aria-label
9. /projects/[id] stat cards → shows "undefined"

## Unimplemented Pages
1. `/settings/users` → "Coming Soon" placeholder
2. `/projects/new` → no page.tsx exists (orphan route)

## API Errors by Status Code
- **500**: 27 endpoints (DB/migration bugs + missing 404 handling)
- **401**: 15 endpoints (UserIdentity systemic bug)
- **404**: 1 endpoint (nodes/{id}/history route not registered)
- **503**: 1 endpoint (embeddings — config-dependent, expected)

## Full Report
`ennam.kg.requirements/QA/reports/functional-test-2026-04-16.md`
