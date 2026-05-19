# Full Regression Test — 2026-04-20

## Summary
- 631 TCs executed across 14 agents, 3 waves, 21 BAs
- **195 PASS (31%), 98 FAIL (16%), 331 SKIP (52%), 7 PARTIAL (1%)**
- 37 unique bugs found: 5 P0, 11 P1, 18 P2, 3 P3
- 33 bugs assigned Go API, 4 assigned NextJS, 0 Python

## Top P0 Blockers
1. BFF Proxy broken — Next.js 16 catch-all route not resolving (NextJS)
2. Non-admin user creation broken — empty ProjectIDs (Go API service/user.go:99)
3. Admin self-disable not blocked (Go API handler/user.go)
4. Auto-create thread crashes — 500 on stream without thread_id (Go API)
5. Ctrl+K crashes page — cmdk incompatibility (NextJS)

## Cascade Impact
- BFF Proxy blocks ~25 dashboard tests
- User creation blocks ~30 RBAC tests
- No AI provider blocks ~90 tests
- No Playwright in API agents blocks ~120 browser tests

## Not Implemented
- BA-005: Gate 2 completeness, hooks, compliance scoring
- BA-010: 16 visualization features (tooltips, search, layouts, exports)
- BA-013: 6 benchmark endpoints (delete, versions, cancel, breakdown, regressions, trends)
- BA-020: Smart context pipeline (search, filter, assemble, query) — only settings exist

## Full Report
`ennam.kg.requirements/QA/reports/full-regression-2026-04-20.md`
