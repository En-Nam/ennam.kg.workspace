# Backlog: AAAA needs a Settings UI to manage DAAB_SYNC_TOKEN

**Raised:** 2026-07-16, during Task 11 (E2E) manual setup of `mem:checkpoint/subagent-driven-doc-sync-planA-2026-07-15` (DAAB↔AAAA doc-sync plan).

## Problem
`DAAB_SYNC_TOKEN` (the shared-secret Bearer token DAAB uses to authenticate to AAAA's `/api/integrations/daab/*` endpoints, added in Task 2 via `src/lib/integrations/daab-auth.ts`) is a plain environment variable (`process.env.DAAB_SYNC_TOKEN`). To set or rotate it today, an operator must:
1. Manually run `openssl rand -hex 32` (or similar) to generate a value
2. Hand-edit AAAA's `.env` file
3. Restart the AAAA app
4. Manually copy the same value into DAAB's "connect AAAA" dialog (Task 10 UI)

There is no UI in AAAA to view, generate, or rotate this token. No rotation-without-downtime support (old token stops working the instant the env var changes + app restarts).

## Proposed fix (future work, out of scope for the doc-sync plan itself)
A Settings page in AAAA with:
- Display current token status (e.g. masked preview, last-rotated timestamp) — never show full plaintext after initial generation, mirroring how DAAB never returns `credential_encrypted` plaintext (Task 5/6 pattern).
- "Regenerate" button that creates a new token.
- Consider supporting multiple valid tokens simultaneously (old + new) for a grace period, so rotating doesn't require synchronized changes on both DAAB and AAAA at the exact same instant.

## Architectural note (why this isn't a trivial UI addition)
The token is currently a `process.env` value — Next.js apps can't have a UI action rewrite environment variables and have them take effect live. Implementing a real "Generate" button requires moving the token from `.env` into the database (encrypted at rest, similar to how DAAB encrypts `credential_encrypted` — see `mem:checkpoint/subagent-driven-doc-sync-planA-2026-07-15`), with `daabTokenOk()` (`src/lib/integrations/daab-auth.ts`) reading from DB instead of `process.env`. This is a real architecture change, not just a settings-page addition.

## Status
Not started. Flagged by the user as worth doing, explicitly deferred until after Task 11 (E2E verification) of the current doc-sync plan is complete.
