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
