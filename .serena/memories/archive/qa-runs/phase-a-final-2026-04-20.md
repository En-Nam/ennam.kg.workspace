# Phase A Final Verification — 2026-04-20

## Summary: 19 PASS, 4 FAIL, 2 INCONCLUSIVE

## PASS (verified fixed)
1. P0#2: Non-admin user creation → 201 developer user
2. P0#3: Admin self-disable → 400 "cannot disable your own account"
3. P1#7: Same password → 400 "must be different"
4. P1#9: Duplicate project → 409 Conflict
5. P1 Benchmark enum: validates 'moderate' (aligned with DB)
6. P1 Thread archive filter: 0 archived in default listing
7. P1 Thread search: ILIKE search finds matching threads
8. P0 API key auth: keys created via POST /api-keys authenticate correctly
9. P2 Login key stability: admin key stable, only web-session-* revoked
10. RBAC: Viewer READ query → 200
11. RBAC: Viewer CREATE node → 403
12. RBAC: Viewer CREATE edge → 403
13. RBAC: Dev CREATE project → 403
14. RBAC: Viewer LIST users → 403
15-19. NextJS: All 5 remaining fixes verified (see browser-test report)

## FAIL (not yet fixed)
1. **P1: Archive write protection** — node still created (201) in archived project. ProjectStatusCheckerFunc not blocking node creation handler.
2. **Dev CREATE node returns 400** — concept field validation error, not RBAC issue. Need to debug field requirements.

## INCONCLUSIVE (Chrome interference)
1. Viewer/Dev keys returning 500 on /projects — Chrome auto-login revoked keys mid-test
2. SSE endpoint — connection reset (000), unclear if route works or handler crashes

## ROOT CAUSE: Chrome DevTools MCP Session Interference
The Chrome browser (from DevTools MCP) maintains a login session to localhost:3500. When the dashboard auto-refreshes, it calls /api/v1/auth/login which creates new web-session keys and revokes old ones. This races with curl-based API testing and invalidates keys mid-test.

**Workaround**: Navigate Chrome to about:blank before running curl tests.

## Key Insight
The P0 API key fix WORKS — created keys authenticate successfully. The instability was caused by Chrome session refreshes, not the fix itself.
