# AIO Analytics — Release v2.9.0 · Unified login (Trello card #3)

**Date:** 2026-11-18 (deployed to prod the same day)
**Previous workspace tag:** v2.6.1
**Source tags:**

| Repo | Tag | Commit |
|---|---|---|
| `ennam.kg.go` | `v2.9.0` | `0c8098d` |
| `ennam.kg.python` | `v2.9.0` | `2cfc7f4` |
| `ennam.kg.next` | `v2.9.0` | `531b08e` |
| `LAAM` | `v2.9.0` | `02c0612` |
| `ennam.kg.admin` | `v0.4.0` | `1caeae3` |
| `ennam.kg.workspace` (docs, compose) | `v2.9.0` | this commit |

Each repo's `CHANGELOG.md` has the details. Design: `docs/superpowers/specs/2026-11-17-unified-login-design.md`.
Plans: `docs/superpowers/plans/2026-11-1{7,8}-unified-login-p{1,2,3,4}-*.md`.

## What it does

- One AIO Analytics sign-in (LAAM). Users with DAAB access land on the **Portal** (`/portal`, two cards) and open
  DAAB through SSO (one-time code) without a second login. LAAM-only users go straight into LAAM.
- AIO navigation bar (bottom bar) in both apps: Portal, LAAM, DAAB, Settings, Profile, Sign out.
- DAAB organizations: internal Ennam org + customer orgs, org roles enforced on the backend, customers see only their
  own projects and the Users / Sync Portal menus.
- Ennam Admin "Connect DAAB" provisions the customer org and an owner linked to the LAAM owner; owners give DAAB access
  to LAAM members; LAAM disable/enable follows into DAAB.
- Sign-out ends both sessions; SSO sessions expire with LAAM (max 4 h) and renew silently; deep links survive sign-in.
- LAAM forgot/reset password by e-mail (Resend) — built, switched off until Resend is set up.
- Supabase login removed from DAAB. Data sources refuse private destinations unless `KG_DATASOURCE_ALLOW_CIDRS` allows them.

## Deploy

- Checklist (env, run order, rollback): `docs/deploy/2026-11-17-unified-login-p1-checklist.md`.
- Migrations: Go `000101`–`000107` (auto on start; check `schema_migrations` afterwards), LAAM drizzle `0057`, `0058`.
- New env — kg-server: `KG_S2S_INBOUND_KEYS`, `KG_LAAM_OUTBOUND_KEY`, `KG_LAAM_API_URL`, `KG_ORG_LINKING_ENABLED`,
  `KG_SSO_ENABLED`, `KG_DATASOURCE_ALLOW_CIDRS` (same on worker + indexer); LAAM: `LAAM_S2S_INBOUND_KEYS`,
  `DAAB_OUTBOUND_KEY`, `DAAB_API_URL`, `DAAB_DASHBOARD_URL`, `SSO_DAAB_ENABLED`, `PORTAL_HOME_ENABLED`,
  `RIGHT_NAV_ENABLED`, `PASSWORD_RECOVERY_ENABLED` + `RESEND_API_KEY` + `MAIL_FROM` (pending Resend); dashboard:
  `SSO_ENABLED`, `LAAM_URL`, `RIGHT_NAV_ENABLED`; Admin: `DAAB_ORG_PROVISIONING=1`.
- After deploy: `kg-set-temp-password` for Supabase-only users, `kg-report-users` + `kg-apply-classification`,
  `npm run daab:backfill [-- --org <id> --apply]` (dry run first, check each line by hand).

## Prod rollout (2026-11-18)

Go 100 → 107, LAAM 57 → 59. Two Supabase-only Ennam admins got temporary passwords (change at first sign-in); all four
DAAB users classified as staff (none moved); backfill provisioned Pharmacy T-log Demo Co (project "Pharmacy Demo
(T-log)", owner linked, SSO eligible); "Pharmacy Chain" stays internal.

## Follow-ups

- Set up Resend (verified sending domain + key), then enable `PASSWORD_RECOVERY_ENABLED`.
- Rotate the two prod DB passwords that were shared in chat.
- `kg-admin.env`, `kg-bridge.env`, `pack-registry.env` use CRLF line endings.
