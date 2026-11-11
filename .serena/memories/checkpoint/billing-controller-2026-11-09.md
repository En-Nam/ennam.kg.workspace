# Checkpoint: billing-controller — 2026-11-09

## What was done
- Ran the Admin plan "1H — Stripe subscription billing" T1–T10 via subagent-driven development: sonnet implemented, opus reviewed, sonnet fixed. T7 got a 4th fix round, approved by the owner, for a critical renewal bug.
- T11 Step 1: typecheck clean; 554 unit and 527 int tests pass at HEAD 18f44b4.

## Files changed
- ennam.kg.admin, branch task/payment-subscription: 26 commits after 4195f8d (not pushed).
- Plan doc `ennam.kg.admin/docs/superpowers/plans/2026-11-09-admin-1h-stripe-subscription.md` is uncommitted. It was updated for these rulings: onboarding route `/orgs/{id}/onboarding`, `balance.low_tokens` kept for managed orgs.
- Ledger with every ruling and parked minor: `ennam.kg.admin/.superpowers/sdd/2026-11-09-admin-1h-stripe-subscription/progress.md`.

## Current state
- Admin T1–T10 complete and reviewed.
- T11 Step 2 (12-step sandbox acceptance, spec §4) is BLOCKED on:
  - the owner's Stripe sandbox keys plus `npm run stripe:setup`;
  - the LAAM plan (most acceptance steps go through the LAAM UI).
- The LAAM plan has not started.

## Next steps
1. Final whole-branch Admin review (opus) covering the FINAL-REVIEW items and parked minors from the ledger; then one fix wave.
   - Key item: there is only one price ID per plan. A subscription on an old or replaced price fails every webhook and every upgrade.
   - Key item: if a new subscription's `invoice.paid` arrives before the old subscription is deleted, the new one is flagged as a duplicate and gets no credit.
2. Write a Vietnamese guide for the owner on getting the Stripe sandbox keys (secret + webhook), setting env, running `stripe:setup`, pasting the IDs into /settings/billing, `stripe listen`, and the two Dashboard settings. The owner asked for this.
3. LAAM plan T1–T6. LAAM T1: fix the contract fixture `entitlement.billing.json` before copying; port the `priceUsage` DAAB change into `chargeOf`; `not_an_increase` returns 422 and the onboarding route is `/orgs/{id}/onboarding`.
4. Acceptance with the owner.

## Blockers / Risks
- Stripe keys are the owner's action. Never paste keys in chat.
- The dev DB `ennam_admin` was not touched; the T2 rehearsal is still awaiting owner consent.
- Unit flake seen once: `ActionForm.test.tsx`.
