# Checkpoint: DAAB sync-key management — 2026-07-20

## What was done
- Full spec → plan → implement → verify cycle for replacing AAAA's hardcoded
  `DAAB_SYNC_TOKEN` env var with DB-backed, revocable sync keys.
- Spec: `docs/superpowers/specs/2026-07-17-daab-sync-key-management-design.md` (commit `7162e8d`).
- Plan: `docs/superpowers/plans/2026-07-17-daab-sync-key-management.md` (`8e784fd`, fixed in `ffcc9be`).
- Implementation: 9 commits in `am-ai-agents`, `f55e4a6` → `69189a8`.
- Cutover completed: seed → verify → `DAAB_SYNC_TOKEN` removed from `.env` (user did this manually).
- Closes `backlog/aaaa-daab-sync-token-settings-ui` (deleted).

## Files changed (am-ai-agents)
- `prisma/schema.prisma` + migration — new `DaabSyncKey` table (`daab_sync_keys`).
- `src/services/daab-key.service.ts` (+test) — generate/list/revoke/verify, SHA-256 hashed storage, throttled `lastUsedAt`.
- `src/lib/integrations/daab-auth.ts` — `daabTokenOk` now async, DB lookup, fails closed.
- `src/app/api/integrations/daab/documents/{route,signed-urls/route}.ts` (+tests) — `await` the guard.
- `src/proxy.ts` (+`src/proxy.public-paths.test.ts`) — **security fix**, see below.
- `src/app/api/integrations/daab/keys/{route.ts,[id]/route.ts}` (+tests) — list/generate/revoke behind `requireAuth`.
- `src/components/settings/daab-sync-card.tsx` + `src/app/(protected)/settings/page.tsx` — UI.
- `scripts/seed-daab-sync-key.ts` (+test), `.env.example`.

## Current state
- Verified working: 173 tests pass across the feature surface; build green.
- DB has 2 active keys (`daab_fe3bcca3`, `daab_6b1f7ea3`), both with non-null
  `lastUsedAt` → DAAB is authenticating against the DB, not env. Mechanism proven live.
- No code reads `process.env.DAAB_SYNC_TOKEN` anymore except the one-time seed script.

## Key decisions (see spec for rationale)
- Keys stored as **SHA-256 hash**; plaintext shown exactly once at creation. `timingSafeEqual` intentionally dropped — indexed hash lookup has no timing channel.
- **Multiple active keys** allowed → zero-downtime rotation (generate → paste into DAAB → revoke old).
- Keys stay **global** (not project-scoped) — unchanged DAAB contract, YAGNI.
- Seed script guards `main()` with `require.main === module` (matches `scripts/reap-stale-gen-jobs.ts`); an earlier plan draft used an unverified `process.env.VITEST` check — corrected before implementation.

## Security note — proxy fix was load-bearing
`src/proxy.ts` listed `/api/integrations/daab` in `publicApiPaths` matched with
`startsWith`, so the new `/api/integrations/daab/keys` route would have been
reachable **unauthenticated** — an anonymous key-mint granting all-project
document reads. Narrowed to `/api/integrations/daab/documents` (still covers
`documents/signed-urls`), plus `requireAuth()` in the keys routes and a
regression test. Any future `/api/integrations/daab/*` route must re-check this.

## Accepted risk (explicit, not inherited silently)
**No RBAC on key minting.** `User` has no role field, so any authenticated user
can create a key that reads documents of every project. Follows AAAA's existing
convention (provider/Google keys are likewise un-gated). Revisit if AAAA adds roles.

## Next steps
- Optional hygiene: revoke the older key `daab_fe3bcca3` if the rotation round is finished; both current keys have `label: null` — set labels on future keys.
- Unrelated pre-existing test debt still red on this branch: 18 failures / 11 files (OCR/tesseract, live-API, `formatUsd` rounding). Confirmed present before the `origin/main` merge too — not regressions from this work.
