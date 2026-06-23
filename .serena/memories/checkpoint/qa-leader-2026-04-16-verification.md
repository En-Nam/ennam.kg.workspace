# Checkpoint: qa-leader — 2026-04-16 (Verification Re-test)

## What was done
- Read Serena memories from Go API team (6 fixes) and NextJS team (8 fixes)
- Rebuilt Docker images with latest code (kg-server + dashboard)
- Dispatched 2 parallel verification agents
- Go API agent: re-tested 6 bugs + smoke test via curl
- NextJS agent: re-tested 7 bugs via Chrome DevTools MCP
- Compiled verification report

## Test Results
- 13 bugs re-tested: 11 PASS (85%), 2 FAIL
- Smoke test: All PASS, no regressions
- FAIL 1: Add project member — resolveUserID() returns string not UUID (Go API)
- FAIL 2: Chat demo tooltip — Radix Tooltip can't fire on disabled buttons (NextJS)

## Files changed
- Created: ennam.kg.requirements/QA/reports/verification-retest-2026-04-16.md
- Serena: qa/verification-retest-2026-04-16 memory written

## Current state
- 11/13 bugs fixed and verified
- 2 remaining bugs have clear root cause documented
- No regressions detected in smoke test
- Docker stack running with all services healthy

## Next steps
- Go API: Fix resolveUserID() in project.go:32-38
- Go API: Register nodes/{id}/history route
- NextJS: Add title fallback for disabled button tooltips
- QA: Final re-test after 2 remaining bugs fixed

## Blockers / Risks
- Add project member still broken — blocks full project membership management via UI
