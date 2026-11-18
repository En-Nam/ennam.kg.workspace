# Unified login — Plan 4: Home, right navigation, password recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A LAAM user with an active DAAB link lands on a two-card Home (`/portal`); both apps get the same right navigation (Portal, LAAM, DAAB, Settings, profile, Sign out) with the org name in the header; LAAM gets self-service forgot/reset password by e-mail (Resend) that ends every LAAM session and the user's DAAB SSO sessions; Plan 1–3 leftovers (role label "Editor", Users-page minors) are fixed; spec §8 QA runs end to end.

**Architecture:** LAAM asks Go over S2S whether the user is SSO-eligible (`POST /api/v1/s2s/sso/status`, same R5 check as `/sso/codes`) and caches the answer for 60 s; `/` sends eligible users to `/portal`, and `/?to=laam` runs today's landing logic unchanged. Each app renders its own fixed right rail from a pure, unit-tested item builder; DAAB computes LAAM hrefs server-side from `ssoConfig()`. Password reset uses a hashed single-use token table in LAAM; replacing `passwordHash` ends all other LAAM sessions through the existing D11 fingerprint check, and the route then calls `revokeDaabSso({ userId })`.

**Tech Stack:** Go (net/http, database/sql), Next.js 16.3 + Auth.js v5 + Drizzle + Vitest (LAAM), Next.js 16 + iron-session + Tailwind 4/shadcn (dashboard `ennam.kg.next`), Resend HTTP API via `fetch` (no SDK), PostgreSQL 15/16.

**Spec:** `docs/superpowers/specs/2026-11-17-unified-login-design.md` — rollout steps 6–7: D-7, D-17, D-15 (+ H-6 for reset), D-8 copy check, §8 QA. Plans 1–3 are done (`docs/superpowers/plans/2026-11-17-unified-login-p1-daab-org-foundation.md`, `…-p2-provisioning-linking.md`, `…-p3-sso-signout-deeplinks.md`, ledger `.superpowers/sdd/2026-11-18-unified-login-p3-sso-signout-deeplinks/progress.md` incl. the R7/R9 amendments).

**Design rulings (spec §9 leaves names, flags, nav structure and Resend details to the builder):**
- R1. Link check: Go `POST /api/v1/s2s/sso/status` body `{"laam_user_id":uuid,"laam_org_id":uuid}` (POST so the ids stay out of access logs; S2S mux, service key) → 200 `{"eligible":true|false}` from the SAME `SSOService.eligible` used by `IssueCode` (ids lowercased first); `KG_SSO_ENABLED` off → 200 `{"eligible":false}`; missing/invalid uuid (either id, incl. empty `laam_org_id` — `eligible` skips the org match when it is empty) → 400 `{"message":"invalid sso request"}`. No reason is ever returned.
- R2. LAAM `hasDaabLink(u: { id: string; orgId: string; orgStatus?: string })` (one name everywhere) = `SSO_DAAB_ENABLED` on AND `DAAB_DASHBOARD_URL` parses AND `!(await isInternalOrg(u.orgId))` AND `u.orgStatus === "active"` AND Go says eligible. Callers skip it entirely when both `PORTAL_HOME_ENABLED` and `RIGHT_NAV_ENABLED` are off. Internal/non-active orgs never call Go. In-memory cache keyed `userId:orgId`, max 5 000 entries (oldest evicted), 60 s for both answers, single-flight; error/timeout (3 s) → `false`, cached 15 s; `evictDaabLink(userId, orgId)` drops one entry. Fail closed = no portal, no DAAB item, `/` as today.
- R3. LAAM routes: `/portal` (Home; not `/home`, which is the intel brief); `/?to=laam` is the one portal bypass, used by the portal's "Open LAAM" card, LAAM's own "LAAM" nav item, DAAB's "LAAM" item and the Back button of `/sso/no-access` and `/sso/error` (no-access also calls `evictDaabLink`). In `src/app/page.tsx` the portal check runs FIRST (before onboarding); with `to=laam` it is skipped and the existing order (onboarding → `/home` → `/chat`) runs unchanged. `/portal` for a user without a link → redirect `/?to=laam`. The LAAM logo keeps linking to `/` (→ portal for linked users; intended). `/portal` reads runtime flags: `export const dynamic = "force-dynamic"`.
- R4. Recovery routes: pages `/forgot-password`, `/reset-password`; APIs `POST /api/password/forgot`, `POST /api/password/reset` (never under `/api/auth*`: `isPublic` matches `startsWith("/api/auth")`, and that segment is Auth.js's). All four are exact matches in `isPublic` and are auth pages in `safeCallbackPath` (→ `/`).
- R5. Token: 32 random bytes, base64url (43 chars, `^[A-Za-z0-9_-]{43}$`), stored as `hashToken()` (sha256 hex, `src/lib/machine-token.ts`) in `password_reset_token`; TTL 30 min; a new request marks the user's earlier unused tokens used. The token travels in the URL FRAGMENT (`/reset-password#token=…`): never sent to the server, never in access logs or `Referer`; the client page reads `location.hash`, clears it (`history.replaceState`) and POSTs it. Opening the page burns nothing (mail scanners prefetch links) — only the POST consumes, with one atomic `UPDATE … SET "usedAt" = now() WHERE "tokenHash" = $1 AND "usedAt" IS NULL AND "expiresAt" > now() RETURNING "userId"`. Invalid/used/expired → 400 `{ "code": "invalid_token" }`. `/reset-password` still sends `Referrer-Policy: no-referrer` (in `next.config.ts` `headers()`; it must be on the response before any third-party resource loads — nothing sensitive is in the query anyway).
- R6. Reset effect: `bcrypt.hash(newPassword, 12)` BEFORE the transaction; in one transaction consume the token (R5), read the user (email, `disabledAt`) from the consumed `userId`, refuse disabled → `invalid_token`, set `passwordHash`, `passwordChangedAt = now`, `mustChangePassword = false`, burn all the user's tokens, audit `password_reset` (`orgId` = user's org, `userId` = subject). Other LAAM sessions end via D11 (`pwdFp` mismatch) — no sid enumeration, no `unstable_update` (the requester has no session). After commit: `loginLockout.recordSuccess(normalizeEmail(row.email))` and `void revokeDaabSso({ userId })` (P4-1). Disabled users (`disabledAt` set) get no mail.
- R7. No enumeration: `POST /api/password/forgot {email}` always returns 200 `{ "ok": true }` for any syntactically valid e-mail (invalid shape → 400 `{code:"invalid"}`); the lookup + mail run in `after()` (`next/server`) so timing does not depend on the account. Limits (`createFixedWindowLimiter`, `clientIpFrom`), each handler calling `limiter.consume(...)` directly (the route-inventory signup marker is `/\.consume\(/`): per IP 10 / 15 min → 429; per `normalizeEmail(email)` 3 / hour → same 200, nothing sent; global 80 reset mails / 24 h (Resend free tier is 100/day) → same 200, nothing sent, `console.error` once per window. Reset POST: per IP 20 / 15 min → 429. The mail goes to the stored `users.email`, never the typed string.
- R8. Mail: `sendMail({ to, subject, text, html }): Promise<boolean>` in `src/lib/mail/resend.ts` → `POST https://api.resend.com/emails` `{from: MAIL_FROM, to:[to], subject, text, html}`, `Authorization: Bearer ${RESEND_API_KEY}`, 10 s timeout, never throws, never logs the token/link. Unset key/from: `NODE_ENV !== "production"` → `console.info` the reset link (dev only); production → `console.error("[mail] not configured")` without the link. Link = `` `${new URL(AUTH_URL).origin}/reset-password#token=${token}` `` (never Host/X-Forwarded-Host); AUTH_URL unset/invalid → no mail, error log. One bilingual mail (vi first, then en).
- R9. Flags (runtime env, accepted `true`/`1`, default off): LAAM `PORTAL_HOME_ENABLED` (the `/` → `/portal` redirect, `/portal` itself and the rail's Portal item), `RIGHT_NAV_ENABLED` (the rail; its DAAB item is gated by `hasDaabLink` only, not by `PORTAL_HOME_ENABLED`), `PASSWORD_RECOVERY_ENABLED` (login link, pages and APIs 404 when off); dashboard `RIGHT_NAV_ENABLED`. Pages/wrappers that read a flag are dynamic (`export const dynamic = "force-dynamic"`). Org name in the header and the role-label fix are not flagged.
- R10. Look (both apps, exact): rail bg navy `#0B1F3A`, hover `#132B4F`, border `#1E3A5F`, text `#E2E8F0`, muted `#94A3B8`, active item = teal `#14B8A6` 3 px left bar + teal icon + bg `#14B8A61A`, focus ring blue `#3B82F6`, org name in teal. Fixed `right-0 top-0 h-dvh`; expanded 224 px at ≥1280 px (no collapse toggle), icon rail 64 px at 768–1279 px (this is the collapsed nav; labels as `title`/`aria-label`), <768 px hidden and opened as a right drawer from a header button (LAAM BottomNav and DAAB's left mobile drawer stay). Content gets matching right padding (`md:pr-16 xl:pr-56`) in BOTH LAAM `AppShellFrame` branches and in DAAB's shell, only when the rail renders, so fill-viewport/full-bleed pages keep their height. Order: Portal, LAAM, DAAB, Settings — spacer — Profile, Sign out. Org name: header (both apps) and rail top (expanded).
- R11. LAAM items: Portal → `/portal` (only with a link and `PORTAL_HOME_ENABLED`), LAAM → `/?to=laam`, DAAB → `new URL("/sso/start?next=%2F", DAAB_DASHBOARD_URL)` (only with a link), Settings → `/settings`, Profile → `/settings/account`, Sign out → `signOut({ callbackUrl: "/login" })` from `next-auth/react` (so `events.signOut` → `onSignOut` fires). Hidden in AppHeader's restricted branch (mustChangePassword / pending / rejected). Right-nav labels via `rightNavDict` (vi/en/zh): Portal "Cổng" / "Portal" / "门户" (R16).
- R12. DAAB items: Portal (English constant, like the rest of the dashboard) → `${LAAM_URL}/portal` and LAAM → `${LAAM_URL}/?to=laam` only when `authSource === 'sso'` and `ssoConfig().enabled`; DAAB → `/`; Settings → `/settings` only for `orgKind !== 'customer'` (D-3: Settings is internal-only); Profile → popover (name, @username, org name, role label; "Change password" only for password sessions — the header `UserMenu` follows the same rule); Sign out → `useLogout()` (returns `redirectTo` = LAAM `/sso/logout` for SSO sessions). Hrefs are computed in the server layout and passed as props; `LAAM_URL` never becomes `NEXT_PUBLIC_*`.
- R13. Org name: Go adds `(SELECT o.name FROM organizations o WHERE o.id = users.org_id)` to `userColumns` as `User.OrgName *string json:"org_name,omitempty" db:"-"` → `/auth/login`, `/auth/sso` and user lists carry it (no migration). Dashboard session gains `orgName?: string` (absent on old sessions → header shows nothing until the next login). LAAM: `refreshSessionFromDb` selects `organizations.name` in its existing join → `token.orgName` → `session.user.orgName` (old tokens gain it on refresh).
- R14. Role label: dashboard `userRoleLabel({ role, orgKind, orgRole })` → customer with `orgRole` → `Owner|Admin|Member|Viewer`; otherwise `roleLabel(role)`. Cause of "Editor": `Header` passes only the global `role` (`developer` for customer owners per D-2) to `UserMenu`.
- R16. Owner decision 2026-11-18: existing intel Home tab unchanged; the 2-portal item is named Portal (spec/card say Home).

## Global Constraints

- Branch `task/portal_login` in every repo; commit only there; no checkouts of other branches/commits, no worktrees; no merge/push until this plan is done AND the owner says so. No `--no-verify`. Stage by explicit path only; never `git add -A` / `git add .` (the workspace root has unrelated dirty files).
- Repos (each its own git, use `git -C <repo>`): `ennam.kg.go` (head `80b209a`, highest migration `000107`, none added here), `LAAM` (head `fe09af71`, next drizzle `0058_*` via `npm run db:generate`), `ennam.kg.next` (head `4bef3ef`), workspace root (head `09144fa`) for docs.
- New Go S2S routes are registered only on the S2S mux; they are not in `main.go`'s route list or `internal/delegation`; the key-guard inventory in `cmd/kg-server/s2s_wiring_test.go` iterates `reg.Patterns()`. Go error bodies use `errorResponse`; quote messages exactly.
- Dashboard `node --test` modules use relative `./x.ts` imports only (no `@/` alias, no `next/*`).
- S2S per Plan 2 R2: LAAM → Go `DAAB_OUTBOUND_KEY` + `DAAB_API_URL`; never log keys, tokens, links or ids in refusals.
- i18n: every LAAM `Dict` entry has `vi`, `en`, `zh`.
- Per-task tests only (task tests + typecheck/build); full suites, final review and Chrome DevTools E2E once at the end (Task 10). Go DB tests: `KG_TEST_DATABASE_URL` and `KG_TEST_DSN` = `postgres://ennam_kg:<pw>@localhost:5433/ennam_kg_test?sslmode=disable` (check `-v` for SKIP). LAAM: `npm test -- <pattern>`, `npm run test:int -- <pattern> </dev/null` (`TEST_DATABASE_URL` :5500 `laam_test`), `npx tsc --noEmit`. Dashboard: `node --test <file>.test.ts` for dependency-free helpers (`.ts` imports, `allowImportingTsExtensions` is on; no `next/*` imports in tested modules), `npm run build`, `npx eslint <changed files>` (58 pre-existing problems; add none).

## Review Focus

1. Account enumeration on forgot: unknown, disabled and over-limit e-mails return the identical 200 body and send nothing; the response does not wait for the lookup or the mail (Task 5).
2. Token misuse: a used token, a token 31 min old, an older token after a newer request, opening the reset page (must not burn) and two concurrent POSTs (one winner) (Task 5).
3. Reset leaves sessions alive: a JWT minted before the reset must refresh to `valid:false`, and `revokeDaabSso({ userId })` is called after commit even when DAAB is down (Task 5).
4. Poisoned reset link: a forged `Host` / `X-Forwarded-Host` never changes the mailed link; AUTH_URL unset in production sends nothing and logs no link (Task 5).
5. Wrong Home: DAAB down/slow, `KG_SSO_ENABLED` off, internal or suspended org, or flag off → `/` behaves exactly as today and no DAAB item; `/?to=laam` never bounces back to `/portal` (Task 3).
6. Sign-out bypass: the LAAM rail's Sign out must call Auth.js `signOut` (not a link or cookie delete), the DAAB rail's must call `useLogout` (Tasks 4, 7).
7. Wrong items for the session type: a DAAB password session (internal or DAAB-only customer) shows no Portal/LAAM; a customer session shows no Settings; a LAAM-only user shows no DAAB/Portal (Tasks 4, 7).

Lanes (parallel, serial within a lane): Go T1 → T2 | LAAM T3 → T4 → T5 → T6 | Dashboard T7 → T8 | T9 last; T10 is a controller step, not dispatched. Cross-repo contracts are the Interfaces blocks; use fakes with these exact shapes.

---

### Task 1: Go — `POST /api/v1/s2s/sso/status`

**Files:**
- Modify: `ennam.kg.go/internal/service/sso.go` (`Status`), `internal/handler/sso.go` (route in `RegisterS2SRoutes`)
- Test: `internal/service/sso_test.go`, `internal/handler/sso_test.go`, `cmd/kg-server/s2s_wiring_test.go` (key-guard inventory over `reg.Patterns()`)

**Interfaces:**
- Produces: `func (s *SSOService) Status(ctx context.Context, laamUserID, laamOrgID string) (bool, error)` — lowercases ids; empty either id → `ErrSSOInvalidRequest` (never calls `eligible` with an empty org id); `GetByLAAMUserID`, `eligible(…, laamOrgID)`; `ErrSSONotAvailable` → `(false, nil)`; DB error → error (handler 500).
- Produces (HTTP, consumed by Task 3): `POST /api/v1/s2s/sso/status` body `{"laam_user_id","laam_org_id"}` → R1.

- [ ] **Step 1: Failing tests**: `TestSSOService_Status_LinkedCustomerUser_True`, `TestSSOService_Status_InternalOrGlobalAdmin_False`, `TestSSOService_Status_DisabledUserOrOrg_False`, `TestSSOService_Status_OrgMismatch_False`, `TestSSOService_Status_EmptyOrgID_Invalid`, `TestSSOService_Status_UppercaseIDs_Match`; handler `TestSSOStatusRoute_FlagOff_EligibleFalse` (200 `{"eligible":false}`, service not called), `TestSSOStatusRoute_BadUUID_400`, `TestSSOStatusRoute_EmptyOrgID_400`; the `s2s_wiring_test.go` inventory covers the new pattern (401 without the service key).
- [ ] **Step 2: Run** `cd ennam.kg.go && go test ./internal/service/ ./internal/handler/ ./cmd/kg-server/ -run 'SSOService_Status|SSOStatusRoute|S2S' -v` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** same + `go build ./...` → PASS (no SKIP).
- [ ] **Step 5: Commit** `feat(sso): S2S eligibility status for the LAAM Home`

---

### Task 2: Go — `org_name` on users (header, Users Org column)

**Files:**
- Modify: `internal/models/user.go` (`OrgName`), `internal/store/user.go` (`userColumns` + both scan sites ~L603/L702)
- Test: `internal/store/user_test.go`, `internal/handler/auth_test.go` (or the existing login-shape test), `internal/handler/sso_test.go`

**Interfaces:** Produces JSON `user.org_name` (string, omitted when null) on `/api/v1/auth/login`, `/api/v1/auth/sso`, `GET /api/v1/users`, `GET /api/v1/org/users` (consumed by Tasks 7, 8).

- [ ] **Step 1: Failing tests**: `TestUserStore_GetByUsername_HasOrgName`, `TestUserStore_List_HasOrgName`, `TestUserStore_CreateReturning_HasOrgName`, `TestLogin_ResponseHasOrgName`, `TestAuthSSO_ResponseHasOrgName`.
- [ ] **Step 2–4**: `go test ./internal/store/ ./internal/handler/ -run 'OrgName' -v` → FAIL → implement → PASS; `go build ./...`. (Self-disable is already refused: `OrgUserService.SetStatus` returns `ErrOrgForbidden` when actor == target — no Go change.)
- [ ] **Step 5: Commit** `feat(users): expose org_name on user payloads`

---

### Task 3: LAAM — link check, `/portal` Home, `/` routing

**Files:**
- Create: `LAAM/src/lib/sso/daab-link.ts` (+ `.test.ts`), `src/app/(app)/portal/page.tsx`, `src/components/portal/ModuleCard.tsx`, `src/i18n/dictionaries/portal.ts` (+ `.test.ts`), `src/lib/flags/unified-login.ts` (+ `.test.ts`)
- Modify: `src/lib/s2s/daab-client.ts` (`fetchDaabSsoStatus`), `src/app/page.tsx`, `src/app/page.test.tsx`, `src/app/sso/no-access/page.tsx` and `src/app/sso/error/page.tsx` (Back → `/?to=laam`; no-access calls `evictDaabLink`)

**Interfaces:**
- Consumes: Task 1 HTTP; session `user.orgStatus`; `isInternalOrg(orgId)` from `@/lib/org/context` (cached 60 s).
- Produces:
  - `function unifiedLoginFlags(env?: NodeJS.ProcessEnv): { portalHome: boolean; rightNav: boolean; passwordRecovery: boolean; ssoDaab: boolean; daabDashboardUrl: string | null }` (R9; URL parsed with `new URL`, origin kept, invalid → null).
  - `async function fetchDaabSsoStatus(laamUserId: string, laamOrgId: string, timeoutMs = 3000): Promise<boolean | null>` (POST per R1; `null` = error/unconfigured).
  - `async function hasDaabLink(u: { id: string; orgId: string; orgStatus?: string }): Promise<boolean>` (R2); `function evictDaabLink(userId: string, orgId: string): void`; `resetDaabLinkCacheForTest()`.
  - `function daabStartUrl(base: string): string` → `new URL("/sso/start?next=%2F", base).toString()`.
- `/portal` page (`dynamic = "force-dynamic"`): two cards — LAAM "AI Insights & Analysis" / "Thông tin chi tiết & phân tích AI" → "Open LAAM" href `/?to=laam`; DAAB "Data & Connections" / "Dữ liệu & Kết nối" → "Open DAAB" href `daabStartUrl(...)` (plain `<a>`, full navigation). No link or `portalHome` off → `redirect("/?to=laam")`.

- [ ] **Step 1: Failing tests**: `hasDaabLink`: `SSO flag off → false, no fetch`, `internal org → false, no fetch`, `suspended org → false, no fetch`, `eligible true → true and second call within 60 s does not fetch`, `Go 500/timeout → false, retried after 15 s`, `two concurrent calls → one fetch`, `ids sent lowercase in the POST body`, `cache never exceeds 5000 entries`, `evictDaabLink forces a refetch`; `unifiedLoginFlags`: `"1"`/`"true"` on, `"yes"` off, bad URL → null; `page.test.tsx`: `linked user → /portal`, `linked user with ?to=laam → existing order (onboarding → /home → /chat)`, `link check throws → existing order`, `unlinked → existing order`, `PORTAL_HOME_ENABLED off → hasDaabLink not called`; portal dict has vi/en/zh for every key.
- [ ] **Step 2–4**: `cd LAAM && npm test -- daab-link unified-login page portal` → FAIL → implement → PASS; `npx tsc --noEmit`.
- [ ] **Step 5: Commit** in LAAM `feat(portal): Home with LAAM/DAAB cards for users with DAAB access`

---

### Task 4: LAAM — right navigation, org name in header

**Files:**
- Create: `LAAM/src/lib/nav/right-nav.ts` (+ `.test.ts`), `src/components/right-nav/RightNav.tsx`, `src/components/right-nav/RightNavDrawerButton.tsx`, `src/components/right-nav/RightNavSignOut.tsx` (+ `.test.tsx`), `src/i18n/dictionaries/rightNav.ts`
- Modify: `src/lib/auth/session-refresh.ts` (select `organizations.name` → `orgName`), `src/auth.config.ts` (copy `orgName` token → session), `src/types/next-auth.d.ts` (`orgName?: string` on Session.user and JWT), `src/app/(app)/layout.tsx` (reads `RIGHT_NAV_ENABLED`, passes `rightNav` to `AppShellFrame`), `src/components/app-header.tsx` (org name; rail + drawer button; not in the restricted branch), `src/components/app-shell-frame.tsx` (`rightNav: boolean` prop → right padding in both branches), `src/lib/auth/session-refresh.test.ts`

**Interfaces:**
- Consumes: Task 3 `unifiedLoginFlags`, `hasDaabLink`, `daabStartUrl` (`hasDaabLink` skipped when both `portalHome` and `rightNav` are off).
- Produces: `type RightNavItem = { key: "portal" | "laam" | "daab" | "settings" | "profile" | "signout"; href: string | null; external: boolean }`; `function laamRightNavItems(input: { hasLink: boolean; portalHome: boolean; daabUrl: string | null }): RightNavItem[]` (R10 order, R11 rules; Portal needs `hasLink && portalHome`, DAAB needs `hasLink && daabUrl` only; `signout.href = null`); `function activeLaamItem(pathname: string): RightNavItem["key"]` (`/portal` → portal, `/settings/account` → profile, `/settings*` → settings, else laam).
- `RightNavSignOut` calls `signOut({ callbackUrl: "/login" })` from `next-auth/react`.

- [ ] **Step 1: Failing tests**: `laamRightNavItems`: `linked + portalHome → portal,laam,daab,settings,profile,signout`, `unlinked → no portal, no daab`, `linked but portalHome off → no portal, daab kept`, `portal item label is "Portal"`, `daab href = <origin>/sso/start?next=%2F`, `laam href = /?to=laam`; `activeLaamItem` table (`/portal`, `/chat`, `/settings`, `/settings/account`, `/home`); `RightNavSignOut click calls next-auth signOut with callbackUrl /login` (mock `next-auth/react`); `refresh returns orgName`; `session callback copies orgName`.
- [ ] **Step 2–4**: `npm test -- right-nav session-refresh auth.config` → FAIL → implement (R10 look, R11 items, `rightNav` off → no rail, no padding) → PASS; `npx tsc --noEmit`.
- [ ] **Step 5: Commit** in LAAM `feat(nav): AIO right navigation and org name in the header`

---

### Task 5: LAAM — reset tokens, mailer, forgot/reset APIs

**Files:**
- Create: `LAAM/src/lib/mail/resend.ts` (+ `.test.ts`), `src/lib/auth/password-reset.ts` (+ `.test.ts`, `.int.test.ts`), `src/app/api/password/forgot/route.ts`, `src/app/api/password/reset/route.ts` (+ `route.int.test.ts` each), `drizzle/0058_*.sql`
- Modify: `src/db/schema.ts` (`passwordResetTokens`), `src/lib/auth/route-limits.ts` (four limiters, R7), `src/auth.config.ts` (`isPublic` exact matches, R4), `src/test/route-inventory.ts` (both APIs mirror `/api/register`: `POST: { auth: "signup", isolation: exempt("public", "<anonymous; acts only on the account the e-mail/token names>") }`)

**Interfaces:**
- Produces (DB): `password_reset_token(id uuid pk default gen_random_uuid(), "userId" text not null references "user"(id) on delete cascade, "tokenHash" text not null unique, "expiresAt" timestamp not null, "usedAt" timestamp null, "createdAt" timestamp not null default now())`, index on `"userId"`.
- `async function sendMail(m: { to: string; subject: string; text: string; html: string }): Promise<boolean>` (R8).
- `function resetLink(token: string, env?: NodeJS.ProcessEnv): string | null` (R8, fragment link from `AUTH_URL` only).
- `async function requestPasswordReset(email: string, now?: Date): Promise<void>` (lookup, skip disabled, per-email + daily cap, burn earlier tokens, insert, mail to stored `users.email`).
- `after()` testability: the forgot route imports `after` from `next/server`; tests `vi.mock("next/server", …)` with an `after` that pushes callbacks into an array. Int tests `await Promise.all(collected.map((f) => f()))` before asserting DB/mail; the timing test asserts the 200 response exists while `collected` is still un-run and `sendMail` not called.
- `async function resetPassword(token: string, newPassword: string): Promise<{ ok: true } | { ok: false; code: "invalid_token" }>` (R5, R6).
- `POST /api/password/forgot {email}` → R7; `POST /api/password/reset {token, newPassword}` (`newPassword` 8–200 chars, token R5 regex) → 200 `{ok:true}` | 400 `{code:"invalid"|"invalid_token"}` | 429. `PASSWORD_RECOVERY_ENABLED` off → 404 for both.

- [ ] **Step 1: Failing tests**:
  - unit: `sendMail posts to api.resend.com with bearer and from`, `sendMail never throws on 500/timeout`, `unset key in development logs the link; in production logs no link and returns false`, `resetLink ignores request headers and uses AUTH_URL origin`, `resetLink puts the token in the fragment`, `resetLink null when AUTH_URL unset`.
  - int: `forgot: unknown, disabled and known e-mail → identical 200 body`, `forgot: responds before the after() work runs`, `forgot: mail goes to the stored address even when typed with other case/spaces`, `forgot: 81st mail in 24 h sends nothing, still 200`, `forgot: known e-mail inserts one hashed token (no raw token in DB) with expiresAt = now+30 min`, `forgot: second request burns the first token`, `forgot: 4th request in an hour sends nothing, still 200`, `forgot: 11th from one IP → 429`, `reset: valid token changes the password and clears mustChangePassword`, `reset: token reused → invalid_token`, `reset: token 31 min old → invalid_token`, `reset: concurrent POSTs → exactly one ok`, `reset: older token after a newer request → invalid_token`, `reset: a JWT minted before the reset → refreshSessionFromDb valid:false`, `reset: calls revokeDaabSso({ userId }) after commit; DAAB down → still 200`, `reset: disabled user → invalid_token`, `reset writes audit password_reset`, `flag off → 404`.
- [ ] **Step 2–4**: `npm test -- resend password-reset route-inventory` and `npm run test:int -- password </dev/null` → FAIL → implement (+ `npm run db:generate` → `0058_*`) → PASS; `npx tsc --noEmit`.
- [ ] **Step 5: Commit** in LAAM `feat(auth): self-service password reset by e-mail (Resend)`

---

### Task 6: LAAM — forgot/reset pages, login link

**Files:**
- Create: `LAAM/src/app/forgot-password/page.tsx`, `src/app/reset-password/page.tsx` (+ `page.test.tsx`), `src/i18n/dictionaries/recovery.ts` (+ `.test.ts`)
- Create: `src/app/login/LoginForm.tsx` (today's client page body moved as is, plus a `showForgot: boolean` prop)
- Modify: `src/app/login/page.tsx` (becomes a server wrapper, `dynamic = "force-dynamic"`, reads `PASSWORD_RECOVERY_ENABLED`, renders `<LoginForm showForgot />`; the form stays a client component and keeps Plan 3's `window.location` callbackUrl logic), `src/lib/auth/safe-callback.ts` (+ test), `next.config.ts` `headers()` (`Referrer-Policy: no-referrer` on `/reset-password`)

**Interfaces:** Consumes Task 5 APIs. `/forgot-password` and `/reset-password` are server wrappers (`dynamic = "force-dynamic"`; flag off → `notFound()`) around client forms; the reset form reads the token from `location.hash` (R5). Copy (en; vi/zh in the dictionary): forgot sent "If an account exists for that e-mail, we've sent a link to reset your password. It expires in 30 minutes."; invalid "This reset link is invalid or has expired. Request a new one."; done "Your password has been changed. Sign in with your new password." (→ `/login`).

- [ ] **Step 1: Failing tests**: `safeCallbackPath('/forgot-password') → /`, `('/reset-password') → /`; reset form: `render does not call the reset API`, `token read from #token= and removed from the address bar after mount`, `no fragment → invalid copy`, `submit posts {token,newPassword}`, `invalid_token shows the invalid copy with a link to /forgot-password`; dictionary has vi/en/zh for every key.
- [ ] **Step 2–4**: `npm test -- safe-callback reset-password recovery` → FAIL → implement → PASS; `npx tsc --noEmit`.
- [ ] **Step 5: Commit** in LAAM `feat(auth): forgot / reset password pages`

---

### Task 7: Dashboard — right navigation, org name, role label

**Files:**
- Create: `ennam.kg.next/src/lib/nav/right-nav.ts` (+ `right-nav.test.ts`), `src/lib/role-label.ts` (+ `role-label.test.ts`), `src/components/layout/RightNav.tsx`, `src/components/layout/ProfilePopover.tsx`
- Modify: `src/lib/auth/session.ts` (`orgName?: string`), `src/lib/auth/apply-login.ts` (`orgName` from `data.user.org_name`), `src/types/user.ts` (`org_name?: string | null`), `src/app/(dashboard)/layout.tsx` (compute items server-side, pass `orgName`, `authSource`, flag), `src/components/layout/DashboardShell.tsx` (rail + right padding), `Header.tsx` (org name; drawer button <768 px; pass `orgKind`/`orgRole`/`authSource` to `UserMenu`), `UserMenu.tsx` (`userRoleLabel`; "Change Password" hidden for SSO sessions, same as the rail profile)

**Interfaces:**
- Consumes: Task 2 `user.org_name`; `ssoConfig()`; `useLogout()`.
- Produces: `type DaabNavItem = { key: "portal" | "laam" | "daab" | "settings" | "profile" | "signout"; href: string | null; external: boolean }`; `function daabRightNavItems(input: { authSource: 'password' | 'sso' | undefined; ssoEnabled: boolean; laamUrl: string | null; orgKind: 'internal' | 'customer' | undefined }): DaabNavItem[]` (R12); `function activeDaabItem(pathname: string): DaabNavItem["key"]`; `function userRoleLabel(input: { role?: string; orgKind?: string; orgRole?: string }): string` (R14); `function rightNavEnabled(env?: NodeJS.ProcessEnv): boolean`.

- [ ] **Step 1: Failing tests** (`node --test`): `sso session + enabled → portal(<laam>/portal), laam(<laam>/?to=laam), daab, profile, signout; no settings for customer`, `password session (internal) → daab, settings, profile, signout`, `password session (DAAB-only customer) → daab, profile, signout`, `sso session but SSO off → no portal/laam`, `legacy session (authSource undefined) → treated as password`; `activeDaabItem('/settings/api-keys') → settings`, `('/projects/x') → daab`; `userRoleLabel({role:'developer',orgKind:'customer',orgRole:'owner'}) → Owner`, `({role:'developer'}) → Editor`, `({role:'admin',orgKind:'internal'}) → Admin`, `customer without orgRole → roleLabel(role)`; `rightNavEnabled` `true`/`1` only.
- [ ] **Step 2–4**: `cd ennam.kg.next && node --test src/lib/nav/right-nav.test.ts src/lib/role-label.test.ts` → FAIL → implement (R10 look; Sign out via `useLogout`; flag off → no rail, no padding) → PASS; `npm run build`; `npx eslint <changed files>`.
- [ ] **Step 5: Commit** in ennam.kg.next `feat(nav): AIO right navigation, org name, org role label`

---

### Task 8: Dashboard — Users page minors, D-8 check

**Files:**
- Create: `ennam.kg.next/src/lib/users/row-actions.ts` (+ `row-actions.test.ts`)
- Modify: `src/components/users/UserTable.tsx` (Org column when `!orgMode`; no Disable on own row, comparing `username` from the existing user context `src/lib/context/user.tsx` — no new session plumbing), `src/components/users/CreateUserDialog.tsx` (copy)

**Interfaces:** `function canDisableRow(row: { username: string; status: string }, currentUsername: string | undefined): boolean` (false for own row — case-insensitive — and already-disabled; the backend already refuses self-disable with 403); `function orgColumnText(u: { org_name?: string | null }): string` (`—` when absent).
Copy: orgMode description "Create an account that signs in on DAAB's own login page. Set a temporary password; the user must change it at first sign-in." (confirm in Go `CreateInOrg` that status is `pending_password_change`; if not, drop the last sentence); internal mode keeps today's text.

- [ ] **Step 1: Failing tests** (`node --test`): `own row → cannot disable`, `own row with different username case → cannot disable`, `other active row → can`, `disabled row → cannot`, `orgColumnText missing → —`.
- [ ] **Step 2–4**: `node --test src/lib/users/row-actions.test.ts` → FAIL → implement → PASS; `npm run build`; `npx eslint <changed files>`. Verify (read-only) that `LinkLaamMemberDialog` renders `DAAB_ACCESS_WARNING` (D-8) — no change expected.
- [ ] **Step 5: Commit** in ennam.kg.next `fix(users): org column, own-row disable hidden, create dialog copy`

---

### Task 9: Deploy checklist + env examples

**Files:**
- Modify: `docs/deploy/2026-11-17-unified-login-p1-checklist.md` (add `## Plan 4` with `### Migrations`, `### Mail (Resend)`, `### New env`, `### Run order`, `### Rollback`), `LAAM/.env.example`, `docker-compose.yml` (dashboard `RIGHT_NAV_ENABLED`), note in the checklist that `envfiles/` needs the vars by hand.

**Content (exact items):** No Go migration (`org_name` is a subselect); LAAM migration `0058`. Resend/DevOps: verify the sending domain in Resend (SPF/DKIM TXT + return-path records on DNS), create an API key with "sending access" only; free tier 100 mails/day. New env — LAAM `RESEND_API_KEY`, `MAIL_FROM="AIO Analytics <no-reply@<verified domain>>"`, `PASSWORD_RECOVERY_ENABLED=false`, `PORTAL_HOME_ENABLED=false`, `RIGHT_NAV_ENABLED=false`, `AUTH_URL` (already required; the reset link's origin); dashboard `RIGHT_NAV_ENABLED=false`; Plan 3 `SSO_DAAB_ENABLED` / `KG_SSO_ENABLED` / `SSO_ENABLED` must be on for the Portal/DAAB items. Run order: set env values → deploy Go → migrate + deploy LAAM → deploy dashboard → smoke with flags off (landing, login, sign-out unchanged; org name visible; customer owner shows "Owner") → `RIGHT_NAV_ENABLED` both apps → `PORTAL_HOME_ENABLED` → send a test reset to an internal mailbox, then `PASSWORD_RECOVERY_ENABLED` → QA (Task 10 list). Rollback: turn `PORTAL_HOME_ENABLED` off first (users stop landing on the Portal), then `RIGHT_NAV_ENABLED` in both apps, then `PASSWORD_RECOVERY_ENABLED` (tokens expire in 30 min; migration 0058 can stay). QA note: DAAB password sessions from before this deploy show no org name until the next login.
- [ ] Commit in each repo touched (workspace root for the checklist): `docs(deploy): unified login plan 4 rollout checklist`.

---

### Task 10: Full suites, final review, E2E QA (spec §8) — controller step, not dispatched

- [ ] **Step 1:** Go `go test -race ./...` (DB env set, no SKIP), LAAM `npm test`, `npm run test:int </dev/null`, `npx tsc --noEmit`, `npm run build`; dashboard all `node --test` files, `npm run build`, `npx eslint .` (≤ 58 problems).
- [ ] **Step 2:** Final whole-branch review (all three repos, diffs from the plan heads); fix Critical/Important.
- [ ] **Step 3: Chrome DevTools E2E** (all flags on locally; ask the user to log in when a login is needed): full-access linked owner (lands on `/portal`, both cards, DAAB without second login, rail Portal/LAAM back to LAAM, role label "Owner", org name in both headers); LAAM-only user (no Portal, no DAAB item, `/` as before; intel "Home" tab unchanged); DAAB-only user (DAAB password login, no Portal/LAAM, no Settings); internal user (no portal in LAAM, DAAB Settings visible, no Portal/LAAM in DAAB); sign out from each rail ends both; forgot → `#token=` link from the dev console → reset → old session in a second browser context is signed out → DAAB SSO session of that user gets 401; DAAB-only reset by org owner and internal reset by global admin (existing flows, verify only); desktop (1440 px), rail (1024 px) and drawer (390 px) in both apps; Users page Org column / own-row / dialog copy.
- [ ] **Step 4:** Save screenshots to the scratchpad and list them with pass/fail per §8 item in the ledger; posting results to the Trello card is the owner's step. Stop servers, delete seed data.

---

## Self-review notes

- Spec coverage: D-7 (T1, T3), D-17 (T4, T7; org name T2/T4/T7), D-15 + H-6 reset (T5, T6; DAAB-side resets verified T10), D-8 (T8 check), §8 QA (T10), P4-1 (T5 R6), Plan 3 sign-out carry (T4 `RightNavSignOut`, T7 `useLogout`), "Editor" (R14, T7), P1 minors (T8).
- Type consistency: `POST /s2s/sso/status` → `{"eligible":bool}` (T1) = `fetchDaabSsoStatus` (T3); `user.org_name` (T2) = `orgColumnText` / `applyLoginResponse` (T7, T8); `/?to=laam` used in T3, T4, T7; `daabStartUrl` (T3) used by T4.
- Execution: lanes in parallel; T9 then T10 last; full suites, review and E2E only in T10.
