# Unified login P1 + P2 (DAAB org foundation, provisioning and linking) - deploy checklist

## Migration 000101 (organizations)

kg-server auto-migrates on start. If the migration aborts on duplicate e-mails
(differing only by case), version 101 is left dirty and the server will not start.

**Precondition (run on prod BEFORE deploying):**

```sql
SELECT lower(email), count(*) FROM users WHERE email IS NOT NULL GROUP BY 1 HAVING count(*) > 1;
```

Fix every returned row (rename/merge/clear the duplicate e-mail) until it returns nothing.

**Recovery if it still aborts:** fix the data, `make db-migrate-force V=100`, restart kg-server.

## Task 8: Supabase removal (migration 000104, password login only)

**Precondition (ops, BEFORE merging to main; not needed before coding):**

1. Run the user report (`ennam.kg.go/cmd/kg-report-users`, Task 9) on prod. Every
   user with `supabase_user_id` set and NULL `password_hash` (column `has_password`
   = false, `supabase_linked` = true) must get a DAAB password through an admin
   password reset, or they cannot sign in once Supabase login is gone.
2. Confirm with the AAAA owner that `POST /api/v1/auth/supabase?session=consumer`
   is unused in prod. After this release it returns 401 to callers without a DAAB key (404 with a key), and migration 000104
   revokes every active `consumer-session-%` key.
3. Record both results here (who confirmed, date, count of users reset):
   - [ ] report run, users reset: ____
   - [ ] AAAA owner confirmation: ____

**Temporary passwords for Supabase-only users (step 1).** These users may be the
only admins, so nobody can reset them through the UI. List them, then give each a
temporary password with `kg-set-temp-password` (forces a change at first login):

```sql
SELECT username, email, role, status FROM users
 WHERE password_hash IS NULL AND laam_user_id IS NULL AND status <> 'disabled';
```

```bash
cd ennam.kg.go && go build -o /tmp/kg-set-temp-password ./cmd/kg-set-temp-password
/tmp/kg-set-temp-password -dsn "$KG_DATABASE_URL" -user alice -user bob@example.com          # dry run
/tmp/kg-set-temp-password -dsn "$KG_DATABASE_URL" -user alice -user bob@example.com -apply -out ./temp-passwords.txt   # writes
```

The dry run changes nothing. `-apply` writes `username → temporary password` once,
to the `-out` file (created mode 0600; it must not exist) or, without `-out`, to
stdout; nothing else logs it. Run it interactively or with `-out`, never in a
container whose stdout is shipped to log storage. It also sets status
`pending_password_change`, clears lockout and revokes the user's web sessions.
Hand each password over out-of-band (not chat or email with the username), never
paste it into a ticket, and delete the `-out` file (and clear scrollback) after.
Users who already have a password are refused (a mistyped `-user` must not reset a
working account); add `-force` only when you really mean to reset one. Disabled
and LAAM-linked (SSO) users are always refused; a refused or ambiguous name aborts
the whole run before anything is written.

**What the deploy changes:** kg-server auto-migrates 000104, which (a) revokes
every active `consumer-session-%` key and (b) sets `expires_at = now() + 15 days`
on active `web-session-%` keys whose `expires_at` is NULL (keys minted by the
removed Supabase login). Down is a no-op (revocation cannot be undone).

**Env cleanup:** `KG_SUPABASE_URL`, `KG_SUPABASE_ADMIN_EMAILS`,
`KG_SUPABASE_SERVICE_ROLE_KEY`, `NEXT_PUBLIC_SUPABASE_URL` and
`NEXT_PUBLIC_SUPABASE_ANON_KEY` are no longer read; remove them from the prod
env files (already removed from the local `envfiles/envfiles/*.env`, compose
files and `.env.release.example`). The `supabase_user_id` column stays for now.

## Network guard for customer data sources (Task 7)

Customer-org data sources are dialled through a fail-closed guard that refuses
loopback, private, link-local and other internal addresses. Internal-org sources
are trusted and unaffected.

- [ ] If any customer source lives on a private network, set
  `KG_DATASOURCE_ALLOW_CIDRS` (comma-separated, e.g. `10.1.0.0/16, 192.168.5.0/24`)
  on BOTH kg-server AND the Python indexer/worker, with the same value. They
  parse it independently; setting only one leaves the other side refusing the
  source. Leave it unset when every customer source is public.
- [ ] Confirm the Python service (port 8081) is reachable only from kg-server in
  prod. It trusts the `X-DB-Trusted-Internal` header to skip the guard, so anyone
  who can reach 8081 directly can bypass it. Do NOT publish 8081 publicly (no
  public load-balancer listener, no security-group ingress from outside the
  kg-server network).

## Migration 000105 (organizations.kind immutable)

kg-server auto-migrates it on start. It adds a trigger that rejects any
`UPDATE organizations SET kind = ...` that changes the kind (the
`users_org_guard` trigger only runs on user writes, so a flipped kind would
bypass its invariants). Nothing to prepare; down drops the trigger.

## Plan 2: DAAB provisioning and account linking

Adds a server-to-server (S2S) channel between kg-server (DAAB) and LAAM, plus two
feature flags that stay OFF until the owner turns them on.

## Keys

- [ ] Generate two 48-char random keys (`openssl rand -hex 24`), never reuse them:
  - **A** (LAAM to Go)
  - **B** (Go to LAAM)

| Service | Variable | Value |
|---|---|---|
| kg-server | `KG_S2S_INBOUND_KEYS` | A (comma list, each >= 32 chars) |
| kg-server | `KG_LAAM_OUTBOUND_KEY` | B |
| kg-server | `KG_LAAM_API_URL` | LAAM base URL (https in prod) |
| LAAM | `LAAM_S2S_INBOUND_KEYS` | B |
| LAAM | `DAAB_OUTBOUND_KEY` | A |
| LAAM | `DAAB_API_URL` | kg-server base URL |

Rotation: list old and new keys together in the inbound variable, switch the
outbound side, then drop the old key.

## Feature flags (default OFF)

- [ ] `KG_ORG_LINKING_ENABLED` (kg-server): gates the org linking routes, the admin
  laam-members list and the 15-minute reconcile job.
- [ ] `DAAB_ORG_PROVISIONING=1` (Ennam Admin): org creation also provisions the LAAM owner.

Leave both unset until the owner says go (last step below).

## Env files

- [ ] The real deploy env files under `envfiles/envfiles/` are gitignored (`kg-server.env`,
  `kg-admin.env`, LAAM's env file). Update them by hand with the new variables above;
  the `.env.example` files and `docker-compose.yml` do not reach them.

## Network

- [ ] LAAM can reach kg-server, and kg-server can reach LAAM `/api/s2s/*`.
- [ ] `/api/s2s/*` is never exposed publicly without the key: keep it on the private
  network or behind an allow-list. Both sides answer 503 when no key is configured.
- [ ] `KG_DATASOURCE_ALLOW_CIDRS` is unchanged (set on kg-server AND the Python service).

## Run order

1. [ ] Migrate Go: 000106 (laam link, key org binding, laam disable scope). kg-server auto-migrates on start.
   A failed auto-migrate only logs a WARN ("auto-migration failed, continuing with current schema") and the server
   keeps serving the old schema: after every Go deploy check `SELECT version, dirty FROM schema_migrations`
   (expect the newest version, `dirty = f`).
2. [ ] Deploy Go (kg-server) with the S2S env above and the flag off.
3. [ ] Deploy LAAM with its S2S env.
4. [ ] Deploy Ennam Admin (flag off).
5. [ ] Report users: `go run ./cmd/kg-report-users -dsn <dsn> > users.csv` (the report goes to stdout).
6. [ ] Owner classifies each user in the CSV.
7. [ ] Apply classification: `go run ./cmd/kg-apply-classification -dsn <dsn> -csv users.csv` (dry-run), review, then add `-apply`.
8. [ ] Backfill, run from Ennam Admin with the flag set on the command only: `DAAB_ORG_PROVISIONING=1 npm run daab:backfill` (dry-run). Check the private-host warnings, then `DAAB_ORG_PROVISIONING=1 npm run daab:backfill -- --apply`. The backfill refuses to run without the flag, but the DEPLOYED Admin service keeps `DAAB_ORG_PROVISIONING` unset until step 10.
   The backfill (spec D-13) moves every project that exactly one org points at: a project the org created
   (`org.daab_project_created`) or one it attached (`org.daab_project_attached`) with no other org's connection or state on
   it. The dry-run line says `would provision (created)` or `would provision (attached, sole owner)`; an attached one is
   recorded as `project_origin = attached`. A project several orgs point at stays internal and shows `skip (shared)`.
   If Go refuses a move (the project is held by another customer) the line is `conflict: ...`, the run goes on and exits
   non-zero: resolve it by hand. Runtime Connect/attach is unchanged: an org that attaches an existing project later gets
   no customer org (D-10). Count the attached ones before the deploy
   (Admin DB: `select target_id, action from audit_log where action in ('org.daab_project_created','org.daab_project_attached')`).
   Run the backfill in a quiet window (no connects, attaches or suspends meanwhile). Check every
   `would provision (attached, sole owner)` line by hand: Admin only sees its own connections, so Ennam staff's direct use
   of that project in DAAB is invisible to it. A failed attached provision has no Retry button: re-run the backfill.
9. [ ] Resolve every `conflict` owner with "Link to LAAM member".
10. [ ] Turn the flags on: `KG_ORG_LINKING_ENABLED=1` (kg-server) and `DAAB_ORG_PROVISIONING=1` (Admin), then restart.

## Plan 3: SSO hand-off, sign-out both ways, deep links

Adds one-time-code SSO from LAAM to DAAB, sign-out in either app ending both, and deep links
surviving sign-in. Three feature flags stay OFF until the owner turns them on.

### Migrations

- [ ] Go `000107_sso_codes` (kg-server auto-migrates on start).
- [ ] LAAM `0057` (`drizzle/0057_far_fantastic_four.sql`, adds `revoked_session`). Legacy LAAM sessions without a
  `sid` get a deterministic one on refresh, so nobody is forced to sign in again.

### Prerequisite

- [ ] The Plan 2 S2S keys are already set both ways (see "Keys" above). Plan 3 adds traffic:
  Go to LAAM `POST /api/s2s/sessions/revoke` (DAAB sign-out), and LAAM to Go `POST /api/v1/s2s/sso/codes` and
  `/sso/revoke` (LAAM sign-out and password change revoke DAAB SSO sessions). kg-server must reach LAAM and LAAM
  must reach kg-server.

### New env

| Service | Variable | Value |
|---|---|---|
| kg-server | `KG_SSO_ENABLED` | `false` |
| LAAM | `SSO_DAAB_ENABLED` | `false` |
| LAAM | `DAAB_DASHBOARD_URL` | `https://<dashboard host>` |
| LAAM | `AUTH_URL` | `https://<laam host>` (public origin; used by `safeCallbackPath` and `readLaamToken` behind TLS termination) |
| dashboard | `SSO_ENABLED` | `false` |
| dashboard | `LAAM_URL` | `https://<laam host>` (no trailing slash, server-only) |

- [ ] Both public hosts are HTTPS in prod so the Secure cookies work.
- [ ] The real env files under `envfiles/envfiles/` are gitignored; the dashboard has no `.env.example`.
  Add the vars by hand (`docker-compose.yml` passes `KG_SSO_ENABLED`, `SSO_ENABLED`, `LAAM_URL` from the shell
  for local runs only; LAAM is not in compose).

### Run order

1. [ ] Migrate Go (000107) and deploy Go (kg-server); set the env values from the table (`KG_SSO_ENABLED=false`).
2. [ ] Migrate LAAM (0057) and deploy LAAM; set the env values from the table (`SSO_DAAB_ENABLED=false`).
3. [ ] Deploy the dashboard; set the env values from the table (`SSO_ENABLED=false`).
4. [ ] Smoke test with flags off: password logins unchanged; LAAM `callbackUrl` and DAAB `/login?next=` deep
   links work; sign-out still works in both apps.
5. [ ] Turn flags on, in this order, restarting each service: `KG_SSO_ENABLED=true`, then `SSO_DAAB_ENABLED=true`,
   then `SSO_ENABLED=true`.
6. [ ] QA per spec section 8:
   - [ ] linked user: LAAM to DAAB with no second sign-in
   - [ ] unlinked user: clear access message (`/sso/no-access`)
   - [ ] user of another org (org mismatch): access message
   - [ ] internal user via direct `/sso/start`: access message
   - [ ] expired LAAM session: lands on LAAM login, then back to DAAB
   - [ ] expired DAAB key: silent re-run through `/sso/start`
   - [ ] signed out of LAAM, then DAAB "Sign in with AIO Analytics": LAAM login, then back to DAAB at `next`
   - [ ] sign-out in LAAM ends the DAAB session; sign-out in DAAB ends the LAAM session

### Rollback

Turn the three flags off in this order, restarting each service: dashboard `SSO_ENABLED`, then LAAM
`SSO_DAAB_ENABLED`, then Go `KG_SSO_ENABLED`. The order matters: with the dashboard flag still on after Go is off,
expired SSO sessions are sent through `/sso/start` and end on LAAM `/sso/error`. Existing SSO keys expire within
4 hours; `/s2s/sso/revoke` stays on, so sign-out and password-change revocation keep working. Migrations stay.

## Plan 4: Portal home, right navigation, password recovery

Adds the Portal home page, the right-hand navigation rail (LAAM and DAAB) and LAAM password recovery by e-mail
(Resend). Three LAAM flags plus the dashboard's `RIGHT_NAV_ENABLED` stay OFF until the owner turns them on.

### Migrations

- [ ] No Go migration (`org_name` is a subselect on `organizations`). Go adds `POST /api/v1/s2s/sso/status`.
- [ ] LAAM `0058` (`drizzle/0058_cloudy_puma.sql`, adds `password_reset_token`). It can stay on rollback.

### Mail (Resend)

- [ ] DevOps: verify the sending domain in Resend (SPF and DKIM TXT records plus the return-path record on DNS).
- [ ] Create a Resend API key with "sending access" only.
- [ ] Free tier is 100 mails/day; LAAM caps reset mails at 80 per 24 h globally.

### New env

| Service | Variable | Value |
|---|---|---|
| LAAM | `RESEND_API_KEY` | key from Resend (secret) |
| LAAM | `MAIL_FROM` | `AIO Analytics <no-reply@<verified domain>>` |
| LAAM | `PASSWORD_RECOVERY_ENABLED` | `false` |
| LAAM | `PORTAL_HOME_ENABLED` | `false` |
| LAAM | `RIGHT_NAV_ENABLED` | `false` |
| LAAM | `AUTH_URL` | already required; its origin is the origin of the reset link |
| LAAM | `TRUSTED_PROXY_HEADER` | REQUIRED in prod, e.g. `x-forwarded-for` or `x-real-ip` (the header your proxy sets with the client IP) |
| dashboard | `RIGHT_NAV_ENABLED` | `false` |

- [ ] Flags accept `true` or `1`; anything else is off.
- [ ] `TRUSTED_PROXY_HEADER` must be set in production. Without it `clientIpFrom` returns `unknown` for every
  request, so all clients share one rate-limit bucket: one client can trigger the forgot/reset 429 for everyone,
  and the 80/day global mail cap is easy to exhaust. The proxy must overwrite the header (LAAM uses the last
  entry of the list).
- [ ] Plan 3 settings must be on for the Portal/DAAB items: LAAM `SSO_DAAB_ENABLED=true` and `DAAB_DASHBOARD_URL`,
  Go `KG_SSO_ENABLED=true`, dashboard `SSO_ENABLED=true` (and `LAAM_URL`). The Plan 2/3 S2S keys must be set both
  ways: LAAM calls Go `POST /api/v1/s2s/sso/status` to check the link.
- [ ] The real env files under `envfiles/` are gitignored: add the vars by hand. `docker-compose.yml` passes the
  dashboard `RIGHT_NAV_ENABLED` from the shell for local runs only; LAAM is not in compose.

### Run order

1. [ ] Set the env values from the table (all flags `false`, `TRUSTED_PROXY_HEADER` set).
2. [ ] Deploy Go (kg-server).
3. [ ] Migrate LAAM (0058) and deploy LAAM.
4. [ ] Deploy the dashboard.
5. [ ] Smoke test with flags off: landing, login and sign-out unchanged; org name visible in the header; a
   customer owner shows "Owner".
6. [ ] Turn on LAAM `PORTAL_HOME_ENABLED` (restart LAAM). This goes BEFORE the dashboard rail.
7. [ ] Turn on `RIGHT_NAV_ENABLED` in LAAM (restart LAAM), then in the dashboard (restart it).
8. [ ] Turn on LAAM `PASSWORD_RECOVERY_ENABLED` (restart LAAM; the APIs and pages return 404 while it is off), then
   send a test reset to an internal mailbox. If delivery fails, turn the flag back off (restart LAAM).
9. [ ] QA (Task 10 list).

QA note: the DAAB rail shows its Portal item for SSO sessions regardless of LAAM's `PORTAL_HOME_ENABLED`, so the
Portal home must be live before the dashboard rail is turned on.

QA note: DAAB password sessions from before this deploy show no org name until the next login.

### Rollback

Turn the dashboard `RIGHT_NAV_ENABLED` off FIRST (restart the dashboard; its rail links to the Portal even when LAAM's
flag is off), then LAAM `PORTAL_HOME_ENABLED` (restart LAAM; users stop landing on the Portal), then LAAM
`RIGHT_NAV_ENABLED` (restart LAAM), then `PASSWORD_RECOVERY_ENABLED` (restart LAAM; reset tokens expire in 30 min).
Migration 0058 can stay.
