# Unified login P1 (DAAB org foundation) - deploy checklist

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
   is unused in prod. After this release it returns 404, and migration 000104
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
