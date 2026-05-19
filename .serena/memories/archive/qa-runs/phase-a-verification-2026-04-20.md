# Phase A Verification — 2026-04-20

## Summary: 17 PASS, 10 FAIL out of 27 tests

## Verified FIXED
- P0#3: Admin self-disable → 400 "cannot disable your own account"
- P1#7: Same password → 400 "must be different"
- P1#9: Duplicate project → 409 Conflict
- P1 Benchmark enum: validates 'moderate' (not 'medium')
- NextJS: All 8 fixes verified via Chrome DevTools MCP

## Still FAILING
- **P1#8: Archive write protection** — node 201 in archived project. Fix NOT effective.
- **P1: Thread archive filter** — archived threads in default list. NOT fixed.
- **P1: Thread search** — search param ignored. NOT fixed.

## NEW BUGS FOUND
1. **P0: API keys from POST /api-keys don't authenticate** — plaintext_key returned but 401 on use. Blocks ALL RBAC testing.
2. **P2: Login revokes ALL previous API keys** — disrupts external integrations.
3. **P2: SSE route returns 500** — handler error "streaming not supported".

## RBAC: BLOCKED
All 6 RBAC tests fail with 401 because created API keys don't work (NEW P0 bug).

## Report
`ennam.kg.requirements/QA/reports/phase-a-verification-2026-04-20.md`
