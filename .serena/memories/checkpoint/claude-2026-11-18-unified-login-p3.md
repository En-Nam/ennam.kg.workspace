# Checkpoint: claude — 2026-11-18 (unified login, card #3, Plan 3)

## What was done
- Plan 3 (SSO hand-off LAAM→DAAB, sign-out both ways, deep links) written by opus, reviewed, owner-approved, executed via SDD in 3 parallel lanes: docs/superpowers/plans/2026-11-18-unified-login-p3-sso-signout-deeplinks.md. 8/8 tasks, final whole-branch review + one fix wave clean, E2E (Chrome DevTools) S1–S10 PASS.
- Rulings during execution: R7 amended (legacy LAAM tokens get deterministic sid = uuid(HMAC(AUTH_SECRET, sub+pwdAt)); sidRetry removed); R9 amended (refresh drop reason password|sid revokes own sid only; by-user only for deleted/disabled/no-org); revoke also burns outstanding sso_codes.
- Security scan caught a real open redirect ('/.//evil.com' after URL normalisation) in the dashboard sanitiser — fixed; LAAM twin built with the fix.

## Files changed (branch task/portal_login; no merge/push until all 4 plans)
- ennam.kg.go 1e6c61c..80b209a: migration 000107 sso_codes, SSO service, /api/v1/s2s/sso/{codes,revoke}, public /api/v1/auth/sso, SSO-aware logout, LAAMClient.RevokeSession.
- LAAM 6e35b91e..fe09af71: sid in JWT + revoked_session (drizzle 0057), events.signOut, /api/s2s/sessions/revoke, /sso/{authorize,no-access,error,logout}, callbackUrl.
- ennam.kg.next b8cb23e..4bef3ef: src/proxy.ts, /sso/{start,callback}, "Sign in with AIO Analytics", silent re-run on 401, sign-out to LAAM.
- workspace d356ea2, 09144fa: deploy checklist Plan 3 section; compose flags.

## Current state
- Flags default off: KG_SSO_ENABLED, SSO_DAAB_ENABLED (+DAAB_DASHBOARD_URL, AUTH_URL), SSO_ENABLED (+LAAM_URL).
- Full suites: only pre-existing failures (Go TestMarginMetric…, TestSemanticsMatchMetrics; packdist timing flake; LAAM org-connection int).
- Ledger: .superpowers/sdd/2026-11-18-unified-login-p3-sso-signout-deeplinks/progress.md.

## Next steps
- Plan 4: Home (2 portals) + right nav both apps + LAAM password recovery (Resend). MUST: password reset calls revokeDaabSso({userId}) + ends other LAAM sessions; right-nav sign-out via Auth.js signOut (events.signOut).
- Check: linked customer owner sees role label "Editor" in DAAB user menu (E2E observation).
- Tell Huy/team card deviations.

## Blockers / Risks
- No merge/push until all 4 plans. golangci-lint not installed (go vet used).
