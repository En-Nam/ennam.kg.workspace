# Checkpoint: claude — 2026-11-18 (unified login deployed to prod)

## What was done
- Dev rehearsal on localhost (Go 107, LAAM 0058, rebuilt images, keys, flags; temp passwords; backfill fixed per spec D-13 + --org). Then PROD deploy on owner's go after DevOps updated envfiles/envfiles.
- Prod: backups → pre-checks → merged task/portal_login into main and deploy-* (go x3, python x2, next, LAAM, admin) → Go migrated 100→107, LAAM 57→59 → temp passwords for dragoon@exnodes.vn + admin@ennam.vn → classification (4 staff, 0 moved) → backfill --org Pharmacy T-log Demo Co → provisioned, owner linked, SSO eligible.

## Files changed
- Code: go 31d9f77/1a742f6 (kg-set-temp-password), admin 79f35cd/40cb21c/2385063/bf838e8 (backfill D-13, sync, --org); spec D-10/D-13 cb05294; checklist f622f22/0b80503/91ca7ae/fa5a1fd/c680612.
- Env (not in git): envfiles/envfiles/{kg-server,laam-app,kg-dashboard,kg-admin,kg-worker,kg-indexer}.env (+ .bak-2026-11-18); dev .env, LAAM/.env.

## Current state
- Prod live: SSO, Portal, bottom bar on; password recovery OFF (no Resend). KG_DATASOURCE_ALLOW_CIDRS=10.100.0.0/16.
- Backups: .superpowers/backups/2026-11-18-prod-pre-unified-login/ (dumps, temp passwords, users csv; 0600).
- Runbook/log: .superpowers/sdd/2026-11-18-unified-login-p4-home-nav-recovery/dev-rollout-log.md.

## Next steps
- Owner hands temp passwords to dragoon/admin@ennam out of band; owner.tlog tries LAAM → Portal → Open DAAB.
- Rotate the two prod DB passwords pasted in chat. Set up Resend then enable PASSWORD_RECOVERY_ENABLED.
- Uncommitted dev-only docker-compose.yml extra_hosts; CRLF in kg-admin.env/kg-bridge.env/pack-registry.env.
- Tell Huy/team the card deviations (spec §6, Portal naming, bottom bar).

## Blockers / Risks
- None blocking.
