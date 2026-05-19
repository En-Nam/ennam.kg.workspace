# Full Regression Wave 1 — Phase 1 + Phase 3

**Date**: 2026-04-20 | **5 parallel agents** | **216 TCs executed**

## Summary
| Metric | Count |
|--------|-------|
| Total TCs | 216 |
| PASS | 110 (51%) |
| FAIL | 48 (22%) |
| SKIP | 56 (26%) |
| Partial | 2 (1%) |

## Results by BA

| BA | Scope | Pass | Fail | Skip |
|----|-------|------|------|------|
| BA-001 Platform Foundation | 38 TCs | 23 | 10 | 3 |
| BA-004 Dashboard | 48 TCs | 14 | 24 | 10 |
| BA-005+006 Enforcement+Deploy | 32 TCs | 18 | 6 | 8 |
| BA-014 User Auth | 40 TCs | 28 | 3 | 9 |
| BA-015+016 Projects+Admin | 58 TCs | 27 | 5 | 26 |

## BLOCKER Bugs (P0)

1. **BFF Proxy broken** — All `/api/kg/*` return 404. Next.js 16 route resolution issue. Cascades to 20+ dashboard failures. **NextJS team**.
2. **Non-admin user creation broken** — `CreateUser()` passes empty `ProjectIDs` to `CreateKey()`, but API key validation rejects non-admin without project_ids. Cannot create developer/viewer users. **Go API team** (`service/user.go:99`).
3. **Admin self-disable not blocked** — Admin can disable own account, locking themselves out. BA-014/AC-006 requires 400 error. **Go API team** (`handler/user.go`).

## CRITICAL Bugs (P1)

4. **Ctrl+K crashes page** — RuntimeTypeError in CommandPrimitive.Input. Entire page unrecoverable. **NextJS team** (`components/ui/command.tsx:76`).
5. **No auth guard on protected routes** — Unauthenticated users see full dashboard (no redirect to /login). **NextJS team** (`layout.tsx`).
6. **Viewer role can create nodes** — No RBAC enforcement on write operations. Security issue. **Go API team**.
7. **Same password accepted** — Password change doesn't check new != old. **Go API team** (`service/user.go`).
8. **Archive write protection missing** — Writes to archived projects not blocked. **Go API team**.
9. **Duplicate project name → 500** — Should be 409 Conflict. **Go API team**.
10. **Impact analysis + Context scope endpoints missing** — 404, not implemented. **Go API team**.

## MEDIUM Bugs (P2)

11. **History ordering ASC not DESC** — BA spec says newest first.
12. **Inline edges not supported** — Returns 400 "not configured".
13. **Structured filter without query rejected** — Should work standalone.
14. **Regex pattern validation not enforced** — req_id accepts any format.
15. **Immutable field update → 500** — Should be 400.
16. **max_per_source constraint not enforced** — Multiple supersedes edges allowed.
17. **Cross-project config restriction not enforced**.
18. **include_archived query param not implemented**.
19. **DELETE /settings/{key} returns 405** — Not implemented.
20. **Node with invalid edge type → 422 not 400** — Minor status code diff.

## SKIPs (56 total)
- 26 due to single admin API key (no developer/viewer keys — blocked by Bug #2)
- 10 due to BFF proxy broken (blocked by Bug #1)
- 8 due to enforcement endpoints not implemented (Gate 2, hooks)
- 12 due to environment constraints (can't stop DB, need MCP client, etc.)

## Key Insight
Bugs #1 (BFF proxy) and #2 (non-admin user creation) are **cascade blockers** — fixing them would unblock ~36 additional test cases that are currently SKIP.
