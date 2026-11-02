# Checkpoint: claude (DAAB user mgmt + Supabase provisioning) — 2026-11-02

## What was done
- Fixed "can't create user" in DAAB dashboard: FE sent no password and expected `temporary_password`; Go API required `password` → 400. Server now generates a policy-compliant temp password (create + admin reset; reset accepts empty body).
- Admin-created users are mirrored into Supabase Auth (login page is email-only via Supabase): new `internal/supabaseadmin` client (create/update-password/delete). Enabled when `KG_SUPABASE_URL` + `KG_SUPABASE_SERVICE_ROLE_KEY` are set; email becomes required. Supabase-first ordering; DAAB failure rolls back Supabase user; provider errors → 502 (`service.ErrIdentityProvider`).
- Reset + self-service change-password sync Supabase first. Supabase login returns `requires_password_change` → dashboard forces `/change-password?forced=1`. Added "Change Password" to UserMenu.
- Security review follow-up: Supabase login paths (regular + consumer) now reject `locked` users (403 "account locked").
- Compose passes `SUPABASE_SERVICE_ROLE_KEY` (.env) → `KG_SUPABASE_SERVICE_ROLE_KEY`; added the key to gitignored `envfiles/kg-server.env`.
- Deleted test user `john.smith` (and its keys); E2E verified create → Supabase login → linked DAAB user → forced change → old pw rejected; test data cleaned in both systems.

## Files changed
- ennam.kg.go: internal/supabaseadmin/{client,client_test}.go, internal/models/temp_password.go, internal/service/user.go (+tests, user_supabase_provision_test.go), internal/handler/{user,auth}.go (+tests), cmd/kg-server/main.go — commits 0943b51, 7221212
- ennam.kg.next: CreateUserDialog.tsx, types/user.ts, login/actions.ts, layout/UserMenu.tsx — commits 29e7c86, 445a6b1
- workspace: docker-compose.yml — f784e82

## Current state
- All on task/DAAB/improve, merged to main (fast-forward). Containers rebuilt and healthy; Supabase project `woxykpthpoabxtwbfroe`.

## Next steps / gaps
- JIT Supabase users have no DAAB password → change-password says "ask an admin to reset it".
- DAAB lock does not ban the Supabase user (DAAB login already rejects locked; optional `ban_duration` sync).
- No DAAB "delete user" API; deleting a user leaves its Supabase account.

## Blockers / Risks
- Missing `KG_SUPABASE_SERVICE_ROLE_KEY` in any env → provisioning silently off (WARN log), admin-created users can't use email login.
- Local dev: port 8080 is Adminer; DAAB server is on 8082.
