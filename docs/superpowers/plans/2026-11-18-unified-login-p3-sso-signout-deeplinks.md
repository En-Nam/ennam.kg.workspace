# Unified login — Plan 3: SSO hand-off, sign-out both ways, deep links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A linked customer user signed in to LAAM opens DAAB without a second sign-in (one-time code, approach A); DAAB SSO sessions never outlive the LAAM session (≤ 4 h keys, silent re-run); sign-out in either app ends both; deep links survive sign-in in both apps; a user without DAAB access who follows a DAAB SSO link gets a clear access message.

**Architecture:** DAAB dashboard `/sso/start` → LAAM `/sso/authorize` → LAAM server asks Go over S2S (`POST /api/v1/s2s/sso/codes`) for a 60 s single-use code bound to the linked DAAB user, the LAAM session id and `sha256(state)` → browser to DAAB `/sso/callback` → dashboard exchanges `code + state` at public `POST /api/v1/auth/sso` for a `web-session-*` key with `laam_session_id` and `expires_at = min(laam_session_exp, now+4h)`. LAAM gets a session id (`sid`) in its JWT and a revoked-sid list checked in the existing per-request DB refresh. Revocation flows over S2S both ways (Go → LAAM `POST /api/s2s/sessions/revoke`, LAAM → Go `POST /api/v1/s2s/sso/revoke`).

**Tech Stack:** Go (net/http, database/sql, golang-migrate), Next.js 16 + Auth.js v5 (LAAM, Drizzle, Vitest), Next.js 16 + iron-session (DAAB dashboard `ennam.kg.next`), PostgreSQL 15/16.

**Spec:** `docs/superpowers/specs/2026-11-17-unified-login-design.md` — rollout step 5: D-9, D-7a, D-11 (SSO keys, expiry, silent re-run), D-12, D-16, H-5 (as amended by Plan 2 R2), H-6, H-9, H-10, H-11, and D-7's "direct DAAB SSO link without access ends on a clear access message". Plans 1 and 2 are done (`docs/superpowers/plans/2026-11-17-unified-login-p1-daab-org-foundation.md`, `docs/superpowers/plans/2026-11-18-unified-login-p2-provisioning-linking.md`; Plan 2 must-fixes landed in go `1e6c61c`). Home/right nav (D-7 Home, D-17) and password recovery (D-15) are Plan 4.

**Design rulings in this plan (spec §9 leaves names/TTLs to the builder):**
- R1. Routes: Go S2S `POST /api/v1/s2s/sso/codes`, `POST /api/v1/s2s/sso/revoke` (Plan 2 R2: the service credential is accepted only under `/api/v1/s2s/`); Go public `POST /api/v1/auth/sso`; LAAM pages `/sso/authorize`, `/sso/no-access`, `/sso/error`, `/sso/logout`; LAAM S2S `POST /api/s2s/sessions/revoke`; dashboard `/sso/start`, `/sso/callback`.
- R2. Code = 32 random bytes, base64url without padding (43 chars); stored as lowercase hex SHA-256 in `sso_codes.code_hash`; TTL 60 s. Any non-empty presented code is burned FIRST, before any other validation (single atomic `UPDATE … SET used_at = now() WHERE code_hash = $1 AND used_at IS NULL RETURNING …`), then TTL, state and user/org are checked.
- R3. `state` = 32 random bytes base64url (43 chars, `^[A-Za-z0-9_-]{43}$`); `state_hash` = lowercase hex SHA-256 of the UTF-8 state string (same in Node and Go); Go compares hashes in constant time.
- R4. SSO key: label `web-session-<username>`, role `user.Role.ToAPIKeyRole()`, `ProjectIDs: []`, `Internal: true`, `UserID`, `LAAMSessionID`, `ExpiresAt = min(laam_session_exp, code_issued_at + 4h)` (H-6 wins over D-11's plain `laam_session_exp`). Exchange sets only `last_login_at`, BEFORE minting the key (new narrow store method — `UpdateLoginSuccess` also resets `failed_login_count`); the `DeleteNeverUsedUser` guard depends on it. Response `requires_password_change` is always `false`.
- R5. Eligibility (D-7a), checked at code issue AND again at exchange: a DAAB user with `laam_user_id` exists, `status <> 'disabled'`, `laam_disabled = false`, org `kind = 'customer'`, org `status = 'active'`, org `laam_org_id` = request `laam_org_id`; the DAAB `org_id` is stored on the code at issue and must still equal `users.org_id` at exchange. `locked` (DAAB password lockout) does not block SSO. Every refusal → 404 `{"message":"sso not available"}` (no reason leaked). LAAM also refuses internal-org (`organizations.internal`) and non-`active` LAAM orgs before calling Go.
- R6. DAAB sign-out is server-side (deviates from D-12's browser redirect — a cross-site POST to LAAM carries no `SameSite=Lax` session cookie): Go `/auth/logout` on a key with `laam_session_id` revokes every key of that LAAM session and calls LAAM `POST /api/s2s/sessions/revoke {sid}`. The dashboard then navigates to LAAM `GET /sso/logout`: no session → redirect `/login`; session still alive (S2S call failed) → same-origin confirm page with a "Sign out" button (H-10 "or a confirm page").
- R7. LAAM session ids: `token.sid = crypto.randomUUID()` in the jwt sign-in branch; assigned lazily on refresh when missing (pre-Plan-3 tokens). Revoked-sid list (H-6 permits it) table `revoked_session(sid text pk, "userId" text null, "revokedAt" timestamp default now(), "expiresAt" timestamp not null = now()+31 days)`, checked with a LEFT JOIN in the same `refreshSessionFromDb` query. `sid` never enters the session JSON. Expired rows are deleted opportunistically on insert.
- R8. LAAM sign-out uses `events.signOut({ token })` in `src/auth.ts` (not the four button call sites): handler `onSignOut(token)` in `src/lib/auth/revoke-session.ts`: insert the revoked sid (awaited, critical), then in `finally` Go revoke by `laam_session_id` (best effort, 5 s timeout, logged) — the Go call runs even if the insert throws.
- R9. H-6 triggers: password change (`/api/users/me/password`) → Go revoke by `laam_user_id`; JWT refresh drop → revoke by `laam_user_id` (user deleted/disabled/no org/password changed) or by `laam_session_id` (sid revoked), fire-and-forget. User disable is already covered by Plan 2 (S2S disable revokes web sessions). Password reset does not exist yet → carried to Plan 4 (see the end of this plan).
- R10. H-9: `/sso/authorize` reads the raw JWT (`getToken`), then runs `refreshSessionFromDb` with `{ sid, failClosed: true }`: any DB error → `/sso/error`; missing `sid` (pre-Plan-3 cookie) → redirect once back to `/sso/authorize?state=…&sidRetry=1` (the proxy's refresh assigns a sid on that request); still missing with `sidRetry=1` → `/sso/error`; no token → `/login?callbackUrl=<this URL>`.
- R11. `next` stays in DAAB (deviates from D-9 step 1): the dashboard sets one sealed cookie per state, `daab_sso_state_<state>` holding `{next, exp}` (iron-session `sealData` with `SESSION_SECRET`; HttpOnly, `secure` = the exact expression `sessionOptions.cookieOptions.secure` uses (`NODE_ENV==='production' && COOKIE_SECURE !== 'false'`, reused from `sessionOptions`, never re-derived), SameSite=Lax, Path=`/sso`, Max-Age 300) — tabs never collide; the callback reads and deletes only its own cookie. LAAM receives only `state`.
- R12. Redirect hygiene (H-10): LAAM `callbackUrl` accepts a relative path or a same-origin absolute URL (Auth.js puts the full href there), normalised to path+search; dashboard `next` accepts relative only. Both parse with `new URL(raw, base)` and match auth pages on the normalised `pathname` (not only a string blacklist); same-origin in LAAM compares the HOST only (or the `AUTH_URL` origin), because behind TLS termination the request scheme is `http`. Both also reject raw input not starting with exactly one `/` (after same-origin normalisation), `//`, `/\`, encoded `%2f`/`%5c` after the first slash, control chars (tab/CR/LF), and send auth pages (`/login`, `/register`, `/api/auth/*`, `/sso/logout`, `/sso/no-access`, `/sso/error` in LAAM; `/login`, `/sso/*` in DAAB) to `/`. DAAB callback base comes from LAAM env `DAAB_DASHBOARD_URL`, never a parameter.
- R13. LAAM error mapping for `/sso/codes`: 404 with message exactly `sso not available` → `/sso/no-access`; any other 404 (e.g. `not found` when `KG_SSO_ENABLED` is off), any other status, timeout, missing S2S config → `/sso/error`. A DAAB outage never says "no access". Copy (en; vi in the dictionary): no-access "Your account doesn't have access to DAAB (Data & Connections). Ask your company owner or admin." / error "AIO Analytics couldn't open DAAB right now. Please try again in a minute."
- R14. Flags (runtime env, default off): Go `KG_SSO_ENABLED` (`/s2s/sso/codes` and `/auth/sso` → 404 when off; `/s2s/sso/revoke` always on); LAAM `SSO_DAAB_ENABLED` (+ `DAAB_DASHBOARD_URL`; `/sso/authorize` → `/sso/error` when off or URL unset); dashboard `SSO_ENABLED` (+ `LAAM_URL`, server-only, not `NEXT_PUBLIC_*`; button hidden and `/sso/*` 404 when off; an expired SSO session with SSO off or `LAAM_URL` unset is destroyed and sent to `/login?next=…`, never to `/sso/start`). Deep links, LAAM sids and revocation are not flagged (behaviour-preserving).
- R15. H-11 / silent re-run: iron-session gains `authSource?: 'password' | 'sso'` and `ssoExpiresAt?: number` (epoch ms). The dashboard proxy sends page navigations of an expired SSO session to `/sso/start?next=<path+search>`; the BFF on a Go 401 for an SSO session does NOT destroy it: it sets `ssoExpiresAt = 0` (other tabs keep `authSource: 'sso'`) and adds `X-Auth-Source: sso`; password sessions are destroyed as today. The client then navigates to `/sso/start?next=…`. Loop guard: a failed callback destroys the dashboard session only when `!isSessionUsable(session)` and lands on `/login?error=sso_failed` (never auto-restarts); with a usable session it redirects to `/` (a third-party `/sso/callback` link cannot sign users out); the login page and the proxy use one helper `isSessionUsable(session, now)` (false for an expired SSO session), so `/login` never bounces an expired SSO session back to `/`; and the client skips the auto re-run if one started < 60 s ago (`sessionStorage['daab-sso-rerun-at']`).

## Global Constraints

- Branch `task/portal_login` in every repo; commit only there; never check out other commits/branches or create worktrees; no merge/push (owner rule until all 4 plans are done). No `--no-verify`.
- Repos: `ennam.kg.go`, `LAAM`, `ennam.kg.next` (each its own git repo: `git -C <repo>`); workspace root for docs. Heads at plan time: go `1e6c61c`, LAAM `6e35b91e`, next `b8cb23e`.
- Go migration: next number `000107` (highest is `000106`). Must run on PostgreSQL 15.
- New Go store methods go behind NEW narrow interfaces; do not add them to existing repository interfaces (mocks in `internal/handler/user_test.go`, `internal/service/user_test.go`, `internal/service/apikey_test.go` would break). New Go routes are added to the route list at `cmd/kg-server/main.go:~1419` and classified in `internal/delegation/routes_other_test.go`.
- Error bodies use Go's `errorResponse` shape (`{"error":<status text>,"message":<text>}`); quote messages exactly as written here.
- S2S calls: bearer keys per Plan 2 R2 (Go inbound `KG_S2S_INBOUND_KEYS`, Go → LAAM `KG_LAAM_OUTBOUND_KEY` + `KG_LAAM_API_URL`; LAAM inbound `LAAM_S2S_INBOUND_KEYS`, LAAM → Go `DAAB_OUTBOUND_KEY` + `DAAB_API_URL`), 10 s timeout unless stated; never log keys, codes or states.
- Per-task tests (owner rule): run only the task's tests + build/typecheck; full suites once at the end of the plan. Go test DB: `KG_TEST_DATABASE_URL` and `KG_TEST_DSN` = `postgres://ennam_kg:<pw>@localhost:5433/ennam_kg_test?sslmode=disable` (check `-v` output for SKIP). LAAM: `TEST_DATABASE_URL` on :5500 `laam_test`; `npm test`, `npm run test:int` (run with stdin closed: `</dev/null`), type-check `npx tsc --noEmit`; migrations via `npm run db:generate` (next file `0057_*`). Dashboard has no test runner: pure helpers are dependency-free TS tested with `node --test <file>.test.ts` (Node 24 strips types; relative imports with explicit `.ts` extensions — Task 6 adds `"allowImportingTsExtensions": true` to `ennam.kg.next/tsconfig.json` (`noEmit` is already set) so `node --test` and `next build` both accept them); otherwise `npm run build` + `npx eslint <changed files>`.

## Review Focus

1. Open redirect: `next` / `callbackUrl` values like `//evil.com`, `/\evil.com`, `/%2F%2Fevil.com`, `/%5Cevil`, `https://evil.com`, a path with a tab/newline, or `/sso/start` must all end on `/` (Task 5 LAAM, Task 6 dashboard).
2. Code replay and state mismatch: a code used twice (also concurrently), a code with the wrong state, or an expired code never yields a key, and a wrong-state attempt or a callback with no matching state cookie still burns the code (Tasks 2, 6).
3. An internal-org user, a global admin, a `laam_disabled`/disabled user, a user of a disabled org, or a `laam_org_id` mismatch never gets a code or a key — also when the state changes between issue and exchange (Task 2).
4. A LAAM DB error, a revoked sid or a missing sid during `/sso/authorize` never reaches Go (Task 5); a DAAB outage shows the error page, not "no access" (Task 5).
5. Server-side redirect loop: a failing `/sso/callback` with an expired SSO session still in the cookie must stop on `/login?error=sso_failed`, not cycle `/login` → `/` → `/sso/start` (Task 6).
6. Sign-out on one side leaves the other alive: DAAB sign-out of an SSO session must end the LAAM sid (Task 3), LAAM sign-out must revoke the SSO keys of that sid (Task 4), and password-login/MCP keys are untouched by either (Task 1).
7. Expired SSO key mid-session with several tabs open: each tab re-runs SSO without a state-cookie collision and without a redirect loop when the callback fails (Tasks 6, 7).

Lanes (parallel, serial within a repo): Go T1 → T2 → T3 | LAAM T4 → T5 | Dashboard T6 → T7 | T8 last. Cross-repo contracts are the Interfaces blocks below; use fakes with these exact shapes.

---

### Task 1: Go — `sso_codes` table, code store, SSO key revocation, last-login setter

**Files:**
- Create: `ennam.kg.go/db/migrations/000107_sso_codes.{up,down}.sql`, `internal/models/sso_code.go`, `internal/store/sso_code.go`, test `internal/store/sso_code_test.go`
- Modify: `internal/store/apikey.go` (two revoke methods), `internal/store/user.go` (`SetLastLogin`)

**Interfaces:**
- Produces (DB): `sso_codes(code_hash text PRIMARY KEY, user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, org_id uuid NOT NULL REFERENCES organizations(id), laam_session_id text NOT NULL, state_hash text NOT NULL, session_expires_at timestamptz NOT NULL, expires_at timestamptz NOT NULL, used_at timestamptz NULL, created_at timestamptz NOT NULL DEFAULT now())`, index on `expires_at`.
- Produces (Go):
  - `type models.SSOCode struct { CodeHash, UserID, OrgID, LAAMSessionID, StateHash string; SessionExpiresAt, ExpiresAt time.Time; UsedAt *time.Time }`
  - `func (s *SSOCodeStore) Create(ctx context.Context, c *models.SSOCode) error` — also deletes rows with `expires_at < now() - interval '1 hour'`
  - `func (s *SSOCodeStore) Consume(ctx context.Context, codeHash string) (*models.SSOCode, error)` — atomic burn (R2); 0 rows → `store.ErrSSOCodeInvalid`
  - `func (s *APIKeyStore) RevokeByLAAMSession(ctx context.Context, laamSessionID string) (int64, error)`
  - `func (s *APIKeyStore) RevokeSSOForLAAMUser(ctx context.Context, laamUserID string) (int64, error)` — keys joined to `users.laam_user_id`
  - Both revoke only `label LIKE 'web-session-%' AND expires_at IS NOT NULL AND laam_session_id IS NOT NULL AND revoked_at IS NULL` (H-13).
  - `func (s *UserStore) SetLastLogin(ctx context.Context, userID string) error` — sets only `last_login_at = now()`.

- [ ] **Step 1: Failing tests**: `TestSSOCodeStore_ConsumeOnce` (second `Consume` → `ErrSSOCodeInvalid`), `TestSSOCodeStore_ConcurrentConsume_OneWinner` (two goroutines → exactly one non-nil result), `TestSSOCodeStore_CreatePrunesOldRows`, `TestRevokeByLAAMSession_OnlySSOKeys` (password-login web-session key, MCP key without expiry and a key of another sid stay active), `TestRevokeSSOForLAAMUser_OnlyThatUser`, `TestSetLastLogin_KeepsFailedCount`, `TestMigration107_UpDown`.
- [ ] **Step 2: Run** `cd ennam.kg.go && go test ./internal/store/ -run 'SSOCode|RevokeByLAAMSession|RevokeSSOForLAAMUser|SetLastLogin|Migration107' -v` → FAIL.
- [ ] **Step 3: Implement**; migrate the test DB to 107 and prove `down 1` / `up`.
- [ ] **Step 4: Run** the same tests + `go build ./...` → PASS (no SKIP).
- [ ] **Step 5: Commit** `feat(sso): one-time code store and SSO key revocation`

---

### Task 2: Go — SSO service, `POST /api/v1/s2s/sso/codes`, `POST /api/v1/auth/sso`

**Files:**
- Create: `internal/service/sso.go`, `internal/handler/sso.go`, tests `internal/service/sso_test.go`, `internal/handler/sso_test.go`
- Modify: `cmd/kg-server/s2s_wiring.go` (register S2S route; `ssoEnabled()` reads `KG_SSO_ENABLED` like `orgLinkingEnabled`), `cmd/kg-server/main.go` (wire service, public route, route list), `internal/middleware/auth.go` `isExemptPath` (add exact `/api/v1/auth/sso`), `internal/delegation/routes_other_test.go`

**Interfaces:**
- Consumes: Task 1 stores; `UserStore.GetByLAAMUserID`; `OrganizationStore.GetByID`; `APIKeyService.CreateKey` (`CreateKeyRequest.LAAMSessionID`, `ExpiresAt`); Plan 1 login response types (`loginResponse`, `loginUser`).
- `type IssueCodeRequest struct { LAAMUserID, LAAMOrgID, LAAMSessionID string; LAAMSessionExp time.Time; StateHash string }`
- `func (s *SSOService) IssueCode(ctx context.Context, req IssueCodeRequest) (code string, err error)` — R5 checks; `ErrSSONotAvailable`; `session_expires_at = min(LAAMSessionExp, now+4h)`; code TTL 60 s.
- `func (s *SSOService) Exchange(ctx context.Context, code, state string) (*SSOLoginResult, error)` — `Consume(sha256hex(code))`; expired or `ConstantTimeCompare(sha256hex(state), StateHash) != 1` → `ErrSSOCodeInvalid`; re-run R5 on the user incl. `users.org_id == code.OrgID` (→ `ErrSSOCodeInvalid`); `SetLastLogin`; then mint key (R4). Any non-empty code is `Consume`d before any other validation (empty code/state → 401 without a DB call). `type SSOLoginResult struct { User *models.User; OrgKind string; APIKey string; ExpiresAt time.Time }`.
- `POST /api/v1/s2s/sso/codes` (S2S mux) body `{"laam_user_id":uuid,"laam_org_id":uuid,"laam_session_id":uuid,"laam_session_exp":<unix seconds>,"state_hash":<64 lowercase hex>}` → 200 `{"code":"<43 chars>","expires_in":60}`; invalid body/ids/hash or `laam_session_exp <= now` → 400 `{"message":"invalid sso request"}`; ineligible → 404 `{"message":"sso not available"}`; flag off → 404 `{"message":"not found"}`.
- `POST /api/v1/auth/sso` (public) body `{"code","state"}` → 200 `{"user":{…same as /auth/login incl. org_kind, org_role},"api_key":"…","requires_password_change":false,"expires_at":"<RFC3339>"}`; every failure → 401 `{"message":"invalid or expired sso code"}`; flag off → 404.

- [ ] **Step 1: Failing tests**:
  - service: `TestIssueCode_LinkedCustomerUser_OK`, `TestIssueCode_InternalOrgUser_NotAvailable` (internal user with `laam_user_id` forced in DB), `TestIssueCode_GlobalAdmin_NotAvailable`, `TestIssueCode_DisabledOrLAAMDisabled_NotAvailable`, `TestIssueCode_DisabledOrg_NotAvailable`, `TestIssueCode_OrgMismatch_NotAvailable`, `TestIssueCode_LockedUser_Allowed`, `TestIssueCode_ExpiryCappedAt4h` (laam exp now+30d → key expires ≤ now+4h), `TestIssueCode_ExpiryUsesLAAMExpWhenSooner`
  - `TestExchange_ReplayRefused`, `TestExchange_ConcurrentRedeem_OneKey`, `TestExchange_WrongState_BurnsCode` (then right state → invalid), `TestExchange_Expired_Refused` (clock +61 s), `TestExchange_UserDisabledAfterIssue_Refused`, `TestExchange_UserMovedOrgAfterIssue_Refused`, `TestExchange_EmptyStateStillBurnsCode`, `TestExchange_KeyShape` (label `web-session-<username>`, `laam_session_id` set, non-nil `expires_at`, role not admin), `TestExchange_SetsLastLoginOnly` (`last_login_at` set, `failed_login_count` unchanged)
  - handler: `TestSSOCodesRoute_BadBody_400`, `TestSSOCodesRoute_NoServiceKey_401`, `TestSSOCodesRoute_FlagOff_404`, `TestAuthSSO_Public_NoAPIKeyNeeded`, `TestAuthSSO_AnyFailure_401SameMessage`, `TestAuthSSO_ResponseMatchesLoginShape`
- [ ] **Step 2: Run** `go test ./internal/service/ ./internal/handler/ ./internal/delegation/ ./cmd/kg-server/ -run 'IssueCode|Exchange|SSOCodesRoute|AuthSSO|EveryRegisteredRoute|S2SRoutes' -v` → FAIL.
- [ ] **Step 3: Implement.** Hashes: `hex.EncodeToString(sha256.Sum256([]byte(s)))`. Code: `crypto/rand` 32 bytes, `base64.RawURLEncoding`.
- [ ] **Step 4: Run** same + `go build ./...` → PASS.
- [ ] **Step 5: Commit** `feat(sso): issue one-time codes for LAAM and exchange them for DAAB sessions`

---

### Task 3: Go — `POST /api/v1/s2s/sso/revoke`, SSO-aware logout, LAAM session revoke client

**Files:**
- Modify: `internal/middleware/auth.go` (`DeveloperIdentity.LAAMSessionID string`, set in `developerIdentityFromKey` from `key.LAAMSessionID`), `internal/handler/sso.go` (revoke route), `internal/handler/auth.go` (`Logout` + `WithSSO`), `internal/s2s/laamclient.go` (`RevokeSession`), `cmd/kg-server/s2s_wiring.go`, `cmd/kg-server/main.go`
- Test: `internal/handler/sso_revoke_test.go`, `internal/handler/auth_logout_sso_test.go`, `internal/s2s/laamclient_test.go`

**Interfaces:**
- `POST /api/v1/s2s/sso/revoke` body exactly one of `{"laam_session_id":"…"}` or `{"laam_user_id":"…"}` → 200 `{"revoked":<n>}`; both/neither → 400 `{"message":"invalid sso request"}`. Not flag-gated.
- `func (c *LAAMClient) RevokeSession(ctx context.Context, sid string) error` → `POST {KG_LAAM_API_URL}/api/s2s/sessions/revoke` body `{"sid":"…"}`; expects 204; per-call timeout 5 s (context deadline, not the client's 10 s); unconfigured → `ErrNotConfigured`.
- `func (h *AuthHandler) WithSSO(revoker interface{ RevokeByLAAMSession(ctx context.Context, sid string) (int64, error) }, laam interface{ RevokeSession(ctx context.Context, sid string) error }) *AuthHandler`
- Logout: after revoking the calling key (unchanged), if `identity.LAAMSessionID != ""` → `RevokeByLAAMSession(sid)` + `laam.RevokeSession(sid)` (error → log `warn` with key id, still 200). Response adds `"sso": true|false`.

- [ ] **Step 1: Failing tests**: `TestSSORevoke_BySession`, `TestSSORevoke_ByUser`, `TestSSORevoke_BothOrNeither_400`, `TestSSORevoke_LeavesPasswordAndMCPKeys`, `TestSSORevoke_NoServiceKey_401`, `TestLogout_SSOKey_RevokesSiblingsAndCallsLAAM` (fake LAAM records sid), `TestLogout_SSOKey_LAAMDown_Still200`, `TestLogout_PasswordKey_NoLAAMCall`, `TestDeveloperIdentity_CarriesLAAMSessionID`, `TestLAAMClient_RevokeSession_SendsBearerAndBody`.
- [ ] **Step 2–4**: `go test ./internal/handler/ ./internal/s2s/ -run 'SSORevoke|Logout_|RevokeSession' -v` → FAIL → implement → PASS; `go build ./...`.
- [ ] **Step 5: Commit** `feat(sso): revoke SSO sessions from LAAM; DAAB sign-out ends the LAAM session`

---

### Task 4: LAAM — session ids, revoked-sid list, sign-out and H-6 revocation to DAAB

**Files:**
- Modify: `LAAM/src/db/schema.ts` (`revokedSessions` → table `revoked_session`), generated `drizzle/0057_*.sql`, `src/auth.config.ts` (jwt: mint/lazy `sid`; on `valid:false` fire the revoke; `isPublic` gains `p === "/sso/logout"` so a server-side-ended session is not bounced through login), `src/auth.ts` (`events.signOut`), `src/lib/auth/session-refresh.ts` (LEFT JOIN sid; `reason`; `failClosed`), `src/types/next-auth.d.ts` (`JWT.sid?: string`), `src/lib/s2s/daab-client.ts` (`revokeDaabSso`), `src/app/api/users/me/password/route.ts`, `src/test/route-inventory.ts`
- Create: `src/lib/auth/revoke-session.ts`, `src/app/api/s2s/sessions/revoke/route.ts`, tests `src/lib/auth/revoke-session.test.ts` (`onSignOut`, mocked deps), `src/lib/auth/revoke-session.int.test.ts`, `src/app/api/s2s/sessions/revoke/route.int.test.ts`, extend `session-refresh.test.ts` / `.int.test.ts`, `daab-client.test.ts`

**Interfaces:**
- `refreshSessionFromDb(userId, pwd, now?, opts?: { sid?: string; failClosed?: boolean })` → adds `{ valid: false; reason: "user" | "sid" }`; `sid` revoked → `{valid:false, reason:"sid"}`; `failClosed` → rethrows DB errors instead of fail-open (existing callers unchanged); the valid result gains `orgInternal: boolean` (read by Task 5).
- `async function revokeLaamSession(sid: string, userId: string | null): Promise<void>` — upsert into `revoked_session` (idempotent), prune expired rows.
- `async function revokeDaabSso(target: { sessionId: string } | { userId: string }, timeoutMs?: number): Promise<void>` → `POST {DAAB_API_URL}/api/v1/s2s/sso/revoke` body `{"laam_session_id"}` or `{"laam_user_id"}`; never throws; failure → `console.error` (no audit row; bounded by the 4 h cap); unconfigured → warn once.
- `POST /api/s2s/sessions/revoke` (service key, `s2sGuard`) body `{"sid":"<uuid>"}` → 204; bad body → 400 `{error:"invalid request"}`; `userId` stored as null.
- `async function onSignOut(token: JWT | null): Promise<void>` in `revoke-session.ts`, wired as `events.signOut: ({ token }) => onSignOut(token)`: `try { await revokeLaamSession(sid, sub) } finally { await revokeDaabSso({ sessionId: sid }, 5000) }`; no sid → nothing.
- Password change: after commit, `revokeDaabSso({ userId })` (not awaited for the response).

- [ ] **Step 1: Failing tests**: `refresh: revoked sid → valid:false reason sid`, `refresh: failClosed rethrows on DB error`, `refresh: default still fail-open on DB error`, `refresh returns orgInternal`, `jwt: sign-in mints a uuid sid`, `jwt: token without sid gains one on refresh`, `session callback never copies sid`, `signOut event inserts revoked sid and calls DAAB revoke by session`, `signOut event: DAAB down → sid still revoked`, `onSignOut: insert throws → DAAB revoke still called`, `s2s sessions/revoke: wrong key 401, bad body 400, ok 204 then refresh of that sid is invalid`, `password change calls revokeDaabSso by user`, `refresh drop (disabled user) calls revokeDaabSso by user`; route inventory entry for `/api/s2s/sessions/revoke` (`auth: "service-key"`, isolation exemption kind `system` — it is keyed by sid, not org).
- [ ] **Step 2–4**: `cd LAAM && npm test -- session-refresh auth.config daab-client route-inventory` and `npm run test:int -- revoke session-refresh </dev/null` → FAIL → implement (+ `npm run db:generate`) → PASS; `npx tsc --noEmit`.
- [ ] **Step 5: Commit** in LAAM `feat(auth): server-side session ids; sign-out and password change revoke DAAB SSO sessions`

---

### Task 5: LAAM — `callbackUrl`, `/sso/authorize`, access/error pages, `/sso/logout`

**Files:**
- Create: `LAAM/src/lib/auth/safe-callback.ts` (+ `.test.ts`), `src/lib/sso/token.ts` (+ `.test.ts`), `src/lib/sso/authorize.ts` (+ `.test.ts`, `.int.test.ts`), `src/app/sso/authorize/route.ts`, `src/app/sso/no-access/page.tsx`, `src/app/sso/error/page.tsx`, `src/app/sso/logout/page.tsx`, `src/i18n/dictionaries/sso.ts`
- Modify: `src/app/login/page.tsx` (honour `callbackUrl`), `src/lib/s2s/daab-client.ts` (`issueDaabSsoCode`)

**Interfaces:**
- `function safeCallbackPath(raw: string | null | undefined, origin: string): string` — R12; fallback `/`.
- `async function issueDaabSsoCode(req: { laamUserId: string; laamOrgId: string; sid: string; exp: number; stateHash: string }): Promise<{ ok: true; code: string } | { ok: false; reason: "no_access" | "error" }>` → Task 2's `POST /api/v1/s2s/sso/codes` with body `{"laam_user_id":laamUserId,"laam_org_id":laamOrgId,"laam_session_id":sid,"laam_session_exp":exp,"state_hash":stateHash}`; 404 + message `sso not available` → `no_access`; anything else → `error` (R13).
- `async function authorizeSso(input: { state: string | null; token: JWT | null; now: number }): Promise<{ redirect: string }>` — order: flag `SSO_DAAB_ENABLED` + `DAAB_DASHBOARD_URL` set, else `/sso/error`; state must match R3 regex, else `/sso/error`; no token → `/login?callbackUrl=<encoded /sso/authorize?state=…>`; token without sid → R10 single retry; `refreshSessionFromDb(sub, pwd, now, { sid, failClosed: true })` throws → `/sso/error`, invalid → `/login?callbackUrl=…`; `orgInternal` or `orgStatus !== "active"` → `/sso/no-access`; `issueDaabSsoCode({… stateHash: sha256hex(state), exp: token.exp})` → `${DAAB_DASHBOARD_URL}/sso/callback?code=…&state=…` | `/sso/no-access` | `/sso/error`.
- `GET /sso/authorize?state=…` route: `readLaamToken(req)` → `authorizeSso` → 302 with `Cache-Control: no-store` and `Referrer-Policy: no-referrer`. `async function readLaamToken(req: Request): Promise<JWT | null>` in `src/lib/sso/token.ts` wraps `getToken({ req, secret: process.env.AUTH_SECRET, secureCookie, salt })` with `secureCookie`/`salt` pinned to what Auth.js itself uses (`__Secure-authjs.session-token` when `AUTH_URL` is https or `x-forwarded-proto: https`, else `authjs.session-token`; salt = that cookie name) — behind TLS termination `req.url` is http. The proxy's existing login redirect covers unauthenticated users.
- `/sso/logout` page (GET, server component): no session → `redirect("/login")`; session → confirm card with the existing `SignOutButton` (`callbackUrl: "/login"`).
- Login page (static client page — no `useSearchParams`): in `onSubmit` read `new URLSearchParams(window.location.search).get("callbackUrl")` and `window.location.assign(safeCallbackPath(raw, window.location.origin))` (full navigation, so `/sso/authorize` route handler runs; `/` stays the default landing logic).

- [ ] **Step 1: Failing tests**:
  - `readLaamToken`: a cookie produced by Auth.js's own `encode` (secure and non-secure names, incl. `x-forwarded-proto: https`) is read back with its `sid` and `exp`.
  - `safeCallbackPath`: `/sso/logout` → `/`, `//evil.com`, `/\evil.com`, `/%2F%2Fevil.com`, `/%5Cevil`, `https://evil.com/x`, `/a\tb`, `javascript:alert(1)`, `/login`, `/api/auth/signin` → `/`; `/chat?x=1` → `/chat?x=1`; `<origin>/sso/authorize?state=abc` → `/sso/authorize?state=abc`; `http://<same host>/sso/authorize?state=abc` with origin `https://<same host>` (TLS termination) → kept; `https://other.host/x` → `/`; `/%73so/logout` → `/` (pathname match). Route test: response has `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.
  - `authorizeSso`: `flag off → /sso/error`, `bad state → /sso/error`, `no token → login with callbackUrl back to authorize`, `token without sid → once back to /sso/authorize with sidRetry=1, then /sso/error`, `Go 404 with message "not found" → /sso/error`, `DB error (failClosed) → /sso/error and Go never called`, `revoked sid → login`, `internal org → /sso/no-access and Go never called`, `Go 404 → /sso/no-access`, `Go 500/timeout → /sso/error`, `success → DAAB_DASHBOARD_URL/sso/callback with code and same state`, `stateHash is lowercase hex sha256 of state`, `exp passed from token.exp`.
  - int: `authorizeSso with a real DB: disabled user → login`, `suspended org → /sso/no-access`.
- [ ] **Step 2–4**: `npm test -- safe-callback sso` and `npm run test:int -- sso </dev/null` → FAIL → implement → PASS; `npx tsc --noEmit`.
- [ ] **Step 5: Commit** in LAAM `feat(sso): authorize DAAB hand-off; honour callbackUrl`

---

### Task 6: Dashboard — deep links, "Sign in with AIO Analytics", `/sso/start`, `/sso/callback`

**Files:**
- Create: `ennam.kg.next/src/lib/auth/safe-next.ts` (+ `safe-next.test.ts`), `src/lib/auth/session-usable.ts`, `src/lib/auth/sso-state.ts` (+ `sso-state.test.ts` for `stateCookieName`/`readStateEntry`), `src/proxy.ts`, `src/app/sso/start/route.ts`, `src/app/sso/callback/route.ts`, `src/lib/auth/apply-login.ts`
- Modify: `tsconfig.json` (`allowImportingTsExtensions: true`), `src/lib/auth/session.ts` (export `sessionOptions`; `authSource`, `ssoExpiresAt`), `src/app/(auth)/login/page.tsx`, `LoginForm.tsx`, `actions.ts` (`next` hidden input; `authSource:'password'`; redirect to `safeNextPath`)

**Interfaces:**
- `function safeNextPath(raw: string | null | undefined): string` — R12 (relative only; `/login`, `/sso/*` → `/`).
- `function isSessionUsable(s: Pick<SessionData, 'isLoggedIn' | 'authSource' | 'ssoExpiresAt'>, now: number): boolean` — false when not logged in or an SSO session with `ssoExpiresAt <= now`; used by the proxy and the login page.
- `function stateCookieName(state: string): string` → `daab_sso_state_<state>` (state must match R3 regex, else throws); `function readStateEntry(sealed: { next: string; exp: number } | null, now: number): { next: string } | null` (expired → null; `next` re-sanitised with `safeNextPath`). Cookie I/O (`sealData`/`unsealData`, R11) wraps them.
- `function applyLoginResponse(session: SessionData, data: GoLoginResponse, source: 'password' | 'sso'): void` — shared by password login and SSO callback (same fields as today + `authSource`; SSO sets `ssoExpiresAt = Date.parse(data.expires_at)`, password login clears `ssoExpiresAt`).
- `GET /sso/start?next=…`: `SSO_ENABLED` off or `LAAM_URL` unset → 404; new state (R3), set `daab_sso_state_<state>` = sealed `{next: safeNextPath(next), exp: now+300 s}`, 302 `${LAAM_URL}/sso/authorize?state=<state>`.
- `GET /sso/callback?code&state` (all responses `Cache-Control: no-store`, `Referrer-Policy: no-referrer`; always delete its own state cookie): cookie missing/expired → still POST the code to Go `/api/v1/auth/sso` and discard the result (burns it), then fail; POST `${GO_API_URL}/api/v1/auth/sso {code,state}`; non-200 → fail; fail = `!isSessionUsable(session)` ? destroy + `/login?error=sso_failed` : 302 `/`; 200 → `applyLoginResponse(…,'sso')`, save, 302 `safeNextPath(entry.next)`.
- `src/proxy.ts` (page requests only; matcher excludes `/api`, `/_next`, static, `/login`, `/sso`, `/change-password`; reads the session with `unsealData`/`getIronSession` on `req.cookies` using the exported `sessionOptions`, not `next/headers` `cookies()`): not logged in → `/login?next=<encoded path+search>`; expired SSO session → `/sso/start?next=…` when SSO is on and `LAAM_URL` set, else clear the session cookie and `/login?next=…` (R14).
- Login page: `isSessionUsable(session, Date.now())` → `redirect(safeNextPath(next))` (an expired SSO session stays on `/login`); shows "Sign in with AIO Analytics" (link `/sso/start?next=<next>`) only when `SSO_ENABLED` is on and `LAAM_URL` is set (server-read prop); `?error=sso_failed` banner "Sign-in with AIO Analytics failed. Please try again or use your DAAB password."

- [ ] **Step 1: Failing tests** (`node --test`): `safeNextPath` with the same hostile list as Task 5 plus `/sso/start`, `/login?next=/x` → `/`; `/projects/abc?tab=graph` kept. `stateCookieName` rejects a non-R3 state; `readStateEntry` → null when expired, `next` `//evil` → `/`; `expiredSsoTarget({ssoOn:false, path})` → `/login?next=…` and `({ssoOn:true})` → `/sso/start?next=…` (pure helper used by the proxy). `isSessionUsable`: expired SSO session → false, live SSO → true, password session without `ssoExpiresAt` → true, logged out → false.
- [ ] **Step 2: Run** `cd ennam.kg.next && node --test src/lib/auth/safe-next.test.ts src/lib/auth/sso-state.test.ts` → FAIL. (`isSessionUsable` and `expiredSsoTarget` live in `src/lib/auth/session-usable.ts`, tested in `safe-next.test.ts`; no `next/*` imports in tested modules; first add `allowImportingTsExtensions: true` to `tsconfig.json`.)
- [ ] **Step 3: Implement** all files above.
- [ ] **Step 4: Run** the node tests → PASS; `npm run build`; `npx eslint <changed files>` (no new problems).
- [ ] **Step 5: Commit** in ennam.kg.next `feat(sso): sign in with AIO Analytics; deep links survive sign-in`

---

### Task 7: Dashboard — expired SSO key mid-session (H-11), sign-out to LAAM

**Files:**
- Create: `ennam.kg.next/src/lib/auth/session-ended.ts` (+ `session-ended.test.ts`)
- Modify: `src/app/api/kg/[...path]/route.ts` (~L60), `src/lib/landed-proxy.ts` (~L57), `src/components/providers/QueryProvider.tsx`, `src/app/api/kg/auth/logout/route.ts`, `src/hooks/use-auth.ts` (`useLogout`)

**Interfaces:**
- BFF (both proxies): on Go 401 with `session.isLoggedIn`: SSO session with SSO on and `LAAM_URL` set → set `ssoExpiresAt = 0`, save (no destroy), headers `X-Session-Revoked: 1` + `X-Auth-Source: sso`; password session, or SSO off → destroy as today.
- `function sessionEndedTarget(input: { authSource: string | null; ssoOn: boolean; path: string; lastRerunAt: number | null; now: number }): string` (`ssoOn` from the `X-Auth-Source` header being present — the BFF sends it only when SSO is on and `LAAM_URL` set; otherwise it destroys the session) — `sso` and no re-run in the last 60 s → `/sso/start?next=<encoded safeNextPath(path)>`; otherwise `/login?reason=session_revoked`. QueryProvider stores `sessionStorage['daab-sso-rerun-at']` before navigating (top-level `window.location.assign`).
- Logout route: read `authSource` first, then Go logout, then `session.destroy()`; returns `{ "message":"Logged out", "redirectTo": "<LAAM_URL>/sso/logout" }` for an SSO session (and `LAAM_URL` set), else `{ …, "redirectTo": "/login" }`; `useLogout` navigates to `redirectTo`.

- [ ] **Step 1: Failing tests** (`node --test`): `sso session → /sso/start with next`, `password session → /login?reason=session_revoked`, `sso re-run 10 s ago → /login` (loop guard), `hostile path → next=/`, `sso session but SSO off/LAAM_URL unset → /login?reason=session_revoked`.
- [ ] **Step 2–4**: `node --test src/lib/auth/session-ended.test.ts` → FAIL → implement → PASS; `npm run build`; `npx eslint <changed files>`.
- [ ] **Step 5** (browser, if a local stack is available): linked user in LAAM → DAAB button/deep link → no second sign-in; force `expires_at` past in DB → next click re-runs silently; two tabs expire together → both recover; sign out in DAAB → LAAM session gone (an already-expired SSO key gets 401 on `/auth/logout`, so LAAM is not revoked server-side → the `/sso/logout` confirm page covers it); sign out in LAAM → DAAB call 401 → `/sso/start` → LAAM login → back to DAAB; a third-party `/sso/callback?code=x&state=y` link while signed in → `/`, session kept. Record what was verified; stop servers, delete seed data.
- [ ] **Step 6: Commit** in ennam.kg.next `feat(sso): silent re-run on expired SSO key; sign-out ends LAAM too`

---

### Task 8: Deploy checklist + env examples

**Files:**
- Modify: `docs/deploy/2026-11-17-unified-login-p1-checklist.md` (add `## Plan 3` with `###` subsections), env examples (`ennam.kg.go/.env.example`, `LAAM/.env.example`; the dashboard has no `.env.example` — its env lives in the `dashboard` service of `docker-compose.yml` and in gitignored `envfiles/`, which need the vars by hand), `docker-compose.yml` (pass `KG_SSO_ENABLED` to kg-server, `SSO_ENABLED`/`LAAM_URL` to dashboard; LAAM if in compose)

**Content (exact items):** migrate Go `000107`; LAAM migration `0057`; new env — kg-server `KG_SSO_ENABLED=false`; LAAM `SSO_DAAB_ENABLED=false`, `DAAB_DASHBOARD_URL=https://<dashboard host>`, `AUTH_URL=https://<laam host>` (public origin; used by `safeCallbackPath` and `readLaamToken` behind TLS termination); dashboard `SSO_ENABLED=false`, `LAAM_URL=https://<laam host>` (no trailing slash; both HTTPS in prod so the Secure cookies work); Plan 2 S2S keys must already be set both ways (Go → LAAM `/api/s2s/sessions/revoke` is new traffic). Run order: migrate Go → deploy Go → migrate + deploy LAAM → deploy dashboard → smoke test with flags off (password logins unchanged, LAAM `callbackUrl` and DAAB `/login?next=` work, sign-out still works) → turn on `KG_SSO_ENABLED`, then `SSO_DAAB_ENABLED`, then `SSO_ENABLED` → QA per spec §8 (linked / unlinked / other-org / internal user via direct `/sso/start`; expired LAAM session; expired DAAB key; logged out of LAAM, then DAAB "Sign in with AIO Analytics" (LAAM login → back to DAAB at `next`); sign-out each side). Rollback: turn the three flags off (existing SSO keys expire within 4 h; `/s2s/sso/revoke` stays on).
- [ ] Commit in each repo touched (workspace root for the checklist).

---

## Self-review notes

- Spec coverage: D-9 (T2, T5, T6), D-7a (T2 R5, T5 internal-org check), D-11 SSO keys/expiry/silent re-run (T1, T2 R4, T6 proxy, T7), D-12 (T3 Go logout → LAAM, T4 LAAM sign-out → Go, T5 `/sso/logout`, T7 dashboard), D-16 (T5 callbackUrl, T6 `/login?next=` + button), H-5 (R1, S2S mux), H-6 (T2 cap, T4 triggers; disable via Plan 2; reset → Plan 4), H-9 (T4 `failClosed`, T5), H-10 (R11, R12, T5, T6), H-11 (T7), D-7 access message (T5 `/sso/no-access`, R13).
- Type consistency: `laam_session_exp` unix seconds (T2) = `token.exp` (T5); `state_hash` hex (T2) = `sha256hex(state)` (T5); `/auth/sso` response = `/auth/login` shape + `expires_at` (T2) consumed by `applyLoginResponse` (T6); revoke bodies (T3) = `revokeDaabSso` (T4); `RevokeSession` path/body (T3) = LAAM route (T4).
- Execution: lanes run in parallel; T8 last; full suites (Go `-race`, LAAM unit + int, dashboard build/lint) once at the end.

## Carried to Plan 4

- P4-1. Password reset (D-15) must call `revokeDaabSso({ userId })` (Task 4) after the reset commits and revoke the user's other LAAM sessions (H-6). Track as a Plan 4 task requirement with its own test.
