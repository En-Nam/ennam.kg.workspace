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
2. [ ] Deploy Go (kg-server) with the S2S env above and the flag off.
3. [ ] Deploy LAAM with its S2S env.
4. [ ] Deploy Ennam Admin (flag off).
5. [ ] Report users: `go run ./cmd/kg-report-users -dsn <dsn> > users.csv` (the report goes to stdout).
6. [ ] Owner classifies each user in the CSV.
7. [ ] Apply classification: `go run ./cmd/kg-apply-classification -dsn <dsn> -csv users.csv` (dry-run), review, then add `-apply`.
8. [ ] Backfill, run from Ennam Admin with the flag set on the command only: `DAAB_ORG_PROVISIONING=1 npm run daab:backfill` (dry-run). Check the private-host warnings, then `DAAB_ORG_PROVISIONING=1 npm run daab:backfill -- --apply`. The backfill refuses to run without the flag, but the DEPLOYED Admin service keeps `DAAB_ORG_PROVISIONING` unset until step 10.
9. [ ] Resolve every `conflict` owner with "Link to LAAM member".
10. [ ] Turn the flags on: `KG_ORG_LINKING_ENABLED=1` (kg-server) and `DAAB_ORG_PROVISIONING=1` (Admin), then restart.
