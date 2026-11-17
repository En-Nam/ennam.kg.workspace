# Checkpoint: claude — 2026-11-17 (unified login, card #3, Plan 1)

## What was done
- Brainstormed + approved design: docs/superpowers/specs/2026-11-17-unified-login-design.md (approach A one-time-code SSO; DAAB orgs; explicit linking; SSO customer-only; §5b security invariants H-1..H-13).
- Plan 1 (DAAB org foundation) written, reviewed, executed via SDD (sonnet implementers, opus reviewers, ≤3 fix rounds): docs/superpowers/plans/2026-11-17-unified-login-p1-daab-org-foundation.md. All 12 tasks + final review + one fix wave: clean.

## Files changed (branch task/portal_login in every repo)
- ennam.kg.go 2ffe0d8..f324a82: migrations 000101–000105 (orgs, key expiry, disabled_scope, legacy session revoke, org kind immutable), per-key fail-closed auth, org authz, /api/v1/org/users + /org/queue, netguard SSRF guard, Supabase removed, cmd/kg-report-users.
- ennam.kg.python 58b6243..c42d236: db_client netguard + TLS pinned hostname (fail closed unless X-DB-Trusted-Internal: 1).
- ennam.kg.next 5b44303..cdac745: org-aware session/admin gate/menus, /not-available, Supabase removed, /settings gated for customers.
- workspace: spec, plan, docs/deploy/2026-11-17-unified-login-p1-checklist.md, compose/env Supabase removal.

## Current state
- Go full suite green except 2 pre-existing (landedapi TestMarginMetricEnabledAfterProductUpload, service TestSemanticsMatchMetrics). Python db_client green; landed_ingest needs another plan's env. Dashboard builds; lint 58 pre-existing.
- SDD ledger: .superpowers/sdd/2026-11-17-unified-login-p1-daab-org-foundation/progress.md (rulings + deferred minors).

## Next steps
- Owner reviews rulings; then write Plan 2 (Admin provisioning + linking, SyncOrgProjects caller, customer backfill using kg-report-users CSV classification), Plan 3 (SSO + sign-out + deep links), Plan 4 (Home + right nav + password recovery via Resend).
- Tell Huy/team the card deviations (spec §6).

## Blockers / Risks
- Owner rule: NO merge/push until all 4 plans done. Only branch task/portal_login; no worktrees/checkouts.
- Before any deploy: checklist preconditions (duplicate-email check, Supabase-only users get passwords, AAAA consumer path unused, KG_DATASOURCE_ALLOW_CIDRS on Go+Python, 8081 private).
- KG MCP not queried this session (session boot skipped; handoff file used instead) — no KG backfill done.
