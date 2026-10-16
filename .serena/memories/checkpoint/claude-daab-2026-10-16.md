# Checkpoint: claude (DAAB + Python + packs + Admin) — 2026-10-16

## What was done
- DAAB (ennam.kg.go, task/demo_pharmacy, pushed 1f9e25f): full suite on a throwaway pgvector/pg16 (removed afterwards). All 93 migrations apply from scratch; down 6 / up OK. Default tags 4942 pass/0 fail; `-tags=integration` 4980 pass/0 fail (17–20 legit skips).
- Fixed 3 test problems: embedding-isolation seed SQL casts (cross-project embedding isolation tests now actually run and PASS); pack-version pin 0.3.0 → ">= 0.3.0"; integration package compile error (`MarkDocResolved` on gaFakeStateChecker).
- Python (ennam.kg.python, pushed 74ff37f): ruff clean; parser test/docstring aligned with commit 63a2b63 (bad span → entity kept with whole-chunk span); pytest 925 pass, 0 fail.
- Packs (ennam.kg.packs, pushed 0d27ffd, v0.5.0 retail+pharmacy): scenario text (0.4.0), glossary (0.4.1), Vietnamese rule names (0.5.0). 199 pack tests + release_test 40 pass. NOT published to registry (workflow triggers on tag vX.Y.Z on main).
- Admin (ennam.kg.admin, main, untouched): integration 330/330 on ennam_admin_test; unit 419, tsc, build OK; contracts identical to LAAM's.

## Current state
- Nothing uncommitted/unpushed in go/python/packs. 3 pre-existing unformatted Go files (ai_provider.go, datasource.go, datasource_integration_test.go) not touched.
- Dashboard (ennam.kg.next): NOT fixed. `session.apiKey || process.env.KG_API_KEY` fallback in src/app/api/kg/[...path]/route.ts:18, auth/claude/import-token/route.ts:9, projects/[id]/ingest/upload/route.ts:15, src/lib/api/client.ts:11. Teammate branch fix/part0-no-fallback-key not on remote. Also 27 lint errors (likely React-Compiler preset).

## Next steps
- Decide dashboard fix (wait for teammate vs. implement) and lint policy.
- Deploy side (deferred by user): DAAB prod migration path broken (deploy-production.yml:187 runs `/app/kg-server migrate`, which main.go ignores; auto_migrate false; no kg-migrate binary; step ends with `|| echo ::warning`) → migrations 88–93 would never apply; KG_INTERNAL_TOKEN missing from terraform/workflows; scoped-key allowlist includes write routes; confirm ENVIRONMENT can't be unset (KG_AUTH_NOOP). Admin: no Dockerfile/CI/lint/CHANGELOG, manual migrations (0005 deletes billing data — pg_dump first), TRUSTED_PROXY_HEADER, CHANGE_ME in .env.example.
- Deploy order: DAAB → Admin → LAAM → publish packs. Rotate dev secrets pasted earlier.

## Blockers / Risks
- All feature branches ahead of main (go 98, next 15, python 5, packs 5, workspace 45); last tag v2.5.0; version number deliberately not chosen yet.
