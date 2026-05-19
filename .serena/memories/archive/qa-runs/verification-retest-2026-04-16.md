# QA Verification Results — 2026-04-16

## Re-test Summary
- 13 bugs re-tested: **11 PASS (85%), 2 FAIL**
- Smoke test: All PASS, no regressions

## PASS (11 bugs fixed)
1. P0: UserIdentity middleware — threads, favorites, AI stream all work
2. P1: Session creation enum — returns 200 with active session
3. P1: Project members list/change/remove — 200 with correct data
4. P1: Settings update — 200 with correct updated_by UUID
5. P1: AI query favorites — both endpoints return 200
6. P1: Benchmark subsystem — create 201, list 200
7. P1: Create Project CTA — opens CreateProjectDialog
8. P1: Edit Project CTA — opens EditProjectDialog pre-filled
9. P2: Stat cards "undefined" — shows "0" or valid numbers
10. P2: Admin Sync tooltips — title attributes added
11. P2: /settings/users placeholder — redirects to /admin/users

## STILL FAILING (2 bugs)
1. **P1: Add Project Member** — `resolveUserID()` in `project.go:32-38` returns DeveloperName (string) not UserIdentity.UserID (UUID). Fix: use GetUserIdentity().UserID.
2. **P2: Chat Demo tooltip** — disabledReason added to data but Radix Tooltip doesn't fire on disabled buttons (pointer-events: none). Fix: add native `title` attribute fallback.

## Not Yet Addressed
- Node history route still 404 (not registered)
- New finding: login can revoke existing API keys (design decision needed)

## Full Report
`ennam.kg.requirements/QA/reports/verification-retest-2026-04-16.md`
