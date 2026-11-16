# Checkpoint: controller-pos-data-model — 2026-11-16

## What was done
- T-log demo thickened: poslog-12m (1905 files, 2025-10-31..2026-11-15) + master/target.csv; planted anomalies (PH-003 voids, PH-004 discounts, PH-005 duplicate refunds) via plant-anomalies.sql on scratch DB pharmacy_demo_ext. Local customer org shows 8 findings across 5 stores.
- Local customer org "Pharmacy T-log Demo Co" (Pro, 5 branches, Stripe test) with owner/admin/member.tlog; org DAAB connection from Ennam Admin -> T-log project; delegation_required ON; member scoped to PH-001.
- Internal-org DAAB Demo (Pharmacy Chain) restored from backup after it was deleted.
- Free questions verified locally: owner gets all stores (numbers match landed counts), member gets PH-001 only, other store refused; DAAB log stores=* / stores=PH-001.
- LAAM fixes: home collapses many unavailable metrics; entity:* subjects humanised; store picker reads stores from the source; discovery no longer caches a listing that missed a failed server (429). LAAM branch pushed.
- envfiles/ replaced by prod copy (laam-app.env, pack-registry.env names); today's vars added (delegation keys, LANDED_*, free questions, Stripe test + prod webhook secret, TRUSTED_PROXY_HEADER).
- RDS ennam_landed bootstrapped by DevOps; found quoted search_path bug (fixed by DevOps: RESET) and missing CREATEROLE for v6 (DevOps granted temporarily). See docs/deploy/2026-11-16-landed-devops-requests.md.

## Current state
- Landed migration on RDS NOT run yet (user said hold). landed_maintenance still has temporary CREATEROLE -> must be revoked (NOCREATEROLE) after migrating.
- DevOps item A (revoke CONNECT from PUBLIC on other DBs) still open: required before free questions on prod.
- Prod S3 bucket is named *-public-storage: DevOps to confirm media/daab/* is not publicly readable.
- Deploy (main -> deploy-*) not done; only on owner's go.

## Next steps
- Run `make landed-migrate` as landed_maintenance against RDS when told; tell DevOps to NOCREATEROLE.
- Deploy order DAAB -> next -> LAAM -> Admin -> packs tag v0.7.0; enter Stripe IDs in prod Admin billing settings (2FA, user).
- Prod demo: create T-log project, enable POS data (UI), run scripts/landed/load-demo-data.py --poslog-dir poslog-12m, customer org + Admin DAAB connect (user 2FA).

## Blockers / Risks
- Local .env still has the old ANTHROPIC_API_KEY (prod rotated).
- Pre-existing failing LAAM unit test: chat/route.test.ts 90k Haiku cap.
