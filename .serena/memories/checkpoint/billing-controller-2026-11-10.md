# Checkpoint: billing-controller — 2026-11-10

## What was done
- Stripe sandbox wired: owner created "LAAM Sandbox" (AIO Solutions LLC); sk_test + whsec in ennam.kg.admin/.env; `npm run stripe:setup` ran; price/product/portal ids saved in Admin /settings/billing; webhook smoke 200.
- Dev DB ennam_admin migrated 0008/0009 with owner consent (pg_dump backup in session scratchpad: ennam_admin-before-stripe-20261110-1339.dump).
- Admin final whole-branch review (opus) + fix wave: plan by product id (`stripe.products`), sweep/reject vs open checkout, card-only, live-sub predicate, fixture. Later: `billing.credits.included_granted` (11c1a37, ba01a08). Admin HEAD ba01a08 (34 commits on task/payment-subscription, not pushed).
- LAAM plan T1–T6 done via SDD (sonnet impl, opus review), final review "Ready", fix wave + changelog. LAAM HEAD f25a5e7f (20 commits on task/payment-subscription, not pushed). Full int 1451/1451, unit green.
- Owner decisions today: managed orgs also Claude-only; per-answer badge = only deducted credit + "Your usage" panel on /settings/billing; extra fix rounds approved (T3 round 4).

## Current state
- Ledgers: LAAM/.superpowers/sdd/2026-11-09-laam-stripe-subscription/progress.md, ennam.kg.admin/.superpowers/sdd/2026-11-09-admin-1h-stripe-subscription/progress.md (parked minors listed there).
- `stripe listen` stopped: CLI OAuth token expired — owner must `stripe login` again.

## Next steps
- Sandbox acceptance (spec §4, 12 steps) with owner: Admin T11 Step 2 + LAAM T7 Step 2. Env: REGISTER_MODE=open, BILLING_SIGNUP_ENABLED=true, USAGE_ENFORCE=true (step 12), ANTHROPIC_API_KEY, stripe listen with --events list. Run step 5 before step 8 (test clock vs real-time spend). New members default strong AI off.
- LAAM dev DB `laam` needs migrations 0053–0056 (ask owner before touching).
- Pending owner answer: send Stripe CLI feedback (`stripe listen` now requires --events)?

## Blockers / Risks
- Parked before real sale: T5 M2/M6, T3 warn log on cap overflow, Admin N1–N4, M3 duplicate customer.
