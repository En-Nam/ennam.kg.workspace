# Backlog: staff billing actions in Ennam Admin (Stripe), deferred to the pre-live gate

**Added:** 2026-11-09. Owner decision: these are not in phase 1, which is the sandbox acceptance. They must be done before switching to Stripe live.
**Spec:** `docs/superpowers/specs/2026-11-09-stripe-subscription-billing-design.md`, §3 and §13.2.

Staff must never use the Stripe Dashboard. The single exception is dispute evidence, which only the admin role may submit. Every action below is an Ennam Admin button that calls the Stripe API, with requireStaff + TOTP + audit.

1. **Add or stop billing an extra data source ($29/month each, 2nd source onward).**
   - Create it as a separate subscription with `metadata.kind=addon` and `org_id`, on the same customer and card.
   - Set `billing_cycle_anchor` to the main plan subscription's current period end, with prorations.
   - Cancel the add-on whenever the main subscription is deleted.
   - If the customer cancels the add-on in the Portal, alert staff and pause that data source.
   - Customers get 2 invoices/month as a result.
   - Add-on events must never touch the org's plan or status, never grant credit, and must be excluded from the duplicate-subscription check.
2. **Change plan or quantity, including decreases and Pro→Essentials.**
   - Increase: `proration_behavior=always_invoice`, `payment_behavior=pending_if_incomplete`.
   - Decrease or downgrade: takes effect at period end through an Admin job, not a subscription schedule. No mid-period refund.
3. **Cancel the subscription, immediately or at period end.** This is also how staff resolve duplicate subscriptions.
4. **Refund.**
   - Subscription invoice: offer "refund + cancel"; no credit clawback.
   - Credit pack: claw back only the remaining purchased credit, never below 0.
   - Correlate refunds by Stripe refund id so the `charge.refunded` webhook does not write duplicate rows.

Also at the pre-live gate (spec §3):
- nightly reconciliation, iterating per stored customer or subscription id because unfiltered Stripe lists omit test-clock objects;
- dispute auto-handling (`pause_collection` plus `dispute.closed`);
- a mid-turn credit ceiling;
- per-plan workflow frequency limits;
- sample pharmacy data;
- DAAB part 0;
- org-scoped LAAM→Admin keys;
- email (see `mem:backlog/billing-email-provider`).
