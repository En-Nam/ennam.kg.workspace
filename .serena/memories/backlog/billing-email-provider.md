# Backlog: email provider for billing and signup (LAAM + Ennam Admin)

**Added:** 2026-11-09. Owner decision: skip this for phase 1 of Stripe billing and track it here.
**Spec:** `docs/superpowers/specs/2026-11-09-stripe-subscription-billing-design.md` (§5.1, §5.3, §5.5, §7).

## Why
Neither LAAM nor Ennam Admin has an email library or provider yet (no dependency in either package.json). Phase 1 of the Stripe billing therefore ships without:
- email verification at public signup (phase 1 uses only these anti-abuse measures: a disposable-domain block, an IP rate limit, and one trial per email);
- trial reminder emails on days 10, 13 and 14 (phase 1 shows the reminders in the app only);
- low-credit alerts to the owner by email at 25% and at zero (in-app only in phase 1).

## To do
- Pick a provider. AWS SES was suggested because the infra is already on AWS; Resend and Postmark are alternatives.
- Pick the sending domain; DevOps adds SPF, DKIM and DMARC records.
- Add email verification to the LAAM register flow without changing the rest of the flow.
- Add the trial-reminder and credit-alert emails.
- Do this before public signup is opened widely, since without verification fake trial accounts are easier.
