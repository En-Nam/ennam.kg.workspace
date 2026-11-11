# Checkpoint: billing-controller — 2026-11-11

## What was done
- Stripe sandbox acceptance (spec §4, 12 steps) — TWO full runs, ALL 12 PASS both times.
  - Run 1: manual-ish Playwright over CDP. Run 2: scripted (tag r2gvnx, fresh orgs), 218 API calls logged, 10 webhooks all 200.
  - Script now in repo: LAAM `e2e/billing-acceptance/` (run.mjs, browser.mjs, helpers.mjs, README.md) — commit d6937ed4. Usage: `node e2e/billing-acceptance/browser.mjs` (log in to Admin w/ TOTP in that window) then `E2E_PASSWORD=... node e2e/billing-acceptance/run.mjs --fresh`; resumable (`run.mjs <step>`), `E2E_TO=<n>` stops early; output in .out/ (gitignored).
- Bugs found only by real Stripe / prod build / live flows, fixed + committed (not pushed):
  - LAAM: b34ebf8f (client bundle imported pg), 6457ef04 (contract: credits one decimal), 94e115ec + 8f96d390 (Haiku credited label = Admin debit rule; zero allowance / unlimited).
  - Admin: 3822983 (payment_method_types rejected by API 2026-10-28.endive → allowed_payment_method_types), 4419bf3 (adaptive_pricing off → USD only), a4fadff (contract decimal credits), 06090ae (ApprovalCard defaulted currency to VND → approving switched USD orgs to VND; now org's currency).
- Owner-approved UX: Admin bb6eb40 (branches "4 (period start: 3)", credit-pack charges in invoices table) + 4fbd47a (invoices survive charges.list failure); Admin 7fec012 Sonnet estimate 10→2; LAAM 445d0684 ("~1–3 credits"), 7d6b2c9c (hide Trial ends unless trial), 41e7c91a (downgrade notice as toast), 9148ef50 comment.
- Opus reviews: acceptance fixes = approve w/ notes (I1 fixed); UX batch = APPROVE. Reviews in each repo's .superpowers/sdd/<plan>/.
- Anthropic list prices (platform.claude.com pricing) match price_book (Sonnet 5.5 $2/$10; Haiku 5.5 ≤100K $0.10/$0.50). Real Sonnet answers cost 0.3–1 credit.
- Recheck: LAAM tsc/lint(0 err)/unit 8455; Admin tsc/unit 570/int 546; Admin prod build OK; LAAM docker image at 9148ef50 healthy.

## Current state
- LAAM dev DB `laam` migrated 0053–0056 (backup in session scratchpad). AUTH_URL=http://localhost:3900. Old image tag laam-app:pre-billing.
- Admin .env has STRIPE_DEV_TOOLS=true + STRIPE_DEV_TEST_CLOCK=auto (both needed for test clocks). Admin dev server + stripe listen were running in the Claude session background — rerun both in a terminal after the session.
- Test orgs: Acceptance/Clock/Trial Bakery 1111 (run 1), E2E… r2gvnx orgs (run 2). Shared test password is owner-chosen (not stored in memory).

## Next steps
- LAAM `npm run test:int` GREEN at HEAD: 108 files / 1451 tests (owner added TEST_DATABASE_URL → laam_test to LAAM/.env, so it now runs directly).
- Owner: decide push/PR for both branches.
- Open: one unexplained POST /api/chat 400 on the first message right after Checkout return (run 2; not reproduced, likely script typed before hydration).
- Parked Minors in review files (partial refunds show Paid; 100-charge scan; toast hover-pause; extra Stripe call per org page).

## Blockers / Risks
- Stripe CLI OAuth token expires ~daily → `stripe listen` dies; owner re-runs `stripe login`.
- Admin job list is fixed at server start: new jobs need a dev-server restart.
