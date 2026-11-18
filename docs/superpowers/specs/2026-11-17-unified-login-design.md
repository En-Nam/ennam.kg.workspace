# Unified AIO Analytics login, Home and right navigation (LAAM + DAAB)

Date: 2026-11-17. Status: direction approved by the owner in session; reviewed (adversarial review + builder
check + spec review); approved by the owner for planning 2026-11-17.
Card: https://trello.com/c/lanoZRrq (#3 [Portal & Login]). Branch: `task/portal_login` (workspace + all sub-repos).
The card's mockup lives in Huy's ChatGPT and is not accessible; the card text is the requirement.

## 1. Why

LAAM (AI insights) and DAAB (data hub) have separate logins, separate user stores and separate sessions. A
customer owner who uses both must sign in twice, and DAAB has no notion of "company": its users are global,
its admins see every project. The card asks for one AIO Analytics sign-in, a shared Home to pick a module,
a persistent right navigation, one sign-out, and backend-enforced company and module permissions.

The owner also wants DAAB to manage users the way LAAM does (internal org + customer orgs), so that a
customer's DAAB access is created and governed per company, and so that linking a LAAM and a DAAB account is
simple and safe.

## 2. Goals, non-goals, anti-goals

Goals
- Sign in once in LAAM; a user who also has DAAB access lands on a Home with two cards and switches modules
  from a right navigation without signing in again.
- DAAB gets organizations: one internal Ennam org and one org per customer; customer users only ever see
  their own org's projects and users.
- Sign-out in either app ends both; DAAB sessions opened from LAAM never outlive the LAAM session.
- Deep links survive sign-in in both apps. Self-service password recovery in LAAM.
- Supabase login is removed from DAAB.

Non-goals (this card)
- Making LAAM an OIDC provider or moving both apps under one domain (see §4).
- Store (location) filtering inside DAAB's own UI (D-8).
- "Recent activity" on Home (card item 7 is optional).
- A third app joining the SSO.

Anti-goals (would be a failure even if it "works")
- A customer user can see another customer's projects, users or data in DAAB.
- A customer org owner/admin ends up with DAAB's global `admin` key role (that role sees every project).
- Accounts get linked by guessing from an unverified e-mail.
- MCP / programmatic API keys (Settings → API Keys, incl. `laam-org-connection`) start expiring or get
  revoked by sign-out.
- An existing internal user loses access to a project they have today.

## 3. Current state (verified in code)

- LAAM: Auth.js v5 Credentials, stateless JWT (default 30 days, refreshed daily; `LAAM/src/auth.ts:26`); the
  JWT callback re-reads the user from the DB on each request. One org per user, roles owner/admin/member/viewer,
  store scope per business project. E-mail unique, lower-cased; registration does not verify e-mail. No
  `events.signOut`. Login ignores `callbackUrl` and goes to `/` → `/onboarding` | `/home` (intel) | `/chat`.
  `/home` is taken.
- DAAB Go: users have a global role (admin/developer/viewer) + `project_members` roles. Every login mints a
  `web-session-<username>` API key with `ProjectIDs: []` and revokes the user's previous one
  (`ennam.kg.go/internal/service/user.go:504-520`). An admin key with empty `ProjectIDs` sees all projects
  (`internal/middleware/auth.go:67-101`). `api_keys` has no expiry; `/auth/logout` revokes nothing. No org or
  tenant concept. ~24 `APIKeyRoleAdmin` checks in 16 files + `requireAdmin` ×9 (`handler/user.go:65`) +
  `requireAdminRole` ×8 (`handler/oauth.go:49`). `users.email` unique but case-sensitive (migration 000032).
- DAAB Supabase login auto-links an existing DAAB user by e-mail (`service/user.go:575`); Supabase signup is
  open. Also used by `?session=consumer` (built for AAAA) and the user-creation dialog / identity provisioner.
- DAAB dashboard: iron-session cookie 15 days holding the key; unauthenticated → bare `redirect('/login')`;
  after login → `/`. ADMIN menu gated by `session.role === 'admin'` (`ennam.kg.next/src/app/(dashboard)/admin/layout.tsx:12`).
- Store scope reaches DAAB only through LAAM delegation tickets on AI queries
  (`ennam.kg.go/internal/handler/ai_query_scope.go:33-45`); a web session has no store filter.
- Ennam Admin `connectDaab` creates a DAAB project + an agent key and stores it as LAAM org connection slug
  `daab`; `attachDaabProject` attaches an existing project that other orgs may share
  (`ennam.kg.admin/src/lib/daab/service.ts`). Admin creates no DAAB users; refuses internal orgs.
- No self-service password reset in either app; no e-mail sender anywhere.

## 4. Approaches

- **A. One-time code via redirect (chosen).** LAAM's server asks Go for a short-lived single-use code bound to
  the linked DAAB user; the browser carries it to the DAAB dashboard, which exchanges it for a session. This is
  the OAuth authorization-code pattern (RFC 6749 §4.1.2: single use, ≤10 min). Reuses Go's existing
  "verify identity → mint web-session key" path; no domain change.
- B. LAAM as a full OIDC provider, DAAB as client. Standard and future-proof, but Auth.js is client-only; it
  needs a provider library, signing-key management, discovery, consent. Too heavy for two apps; revisit if a
  third app joins.
- C. Shared parent domain + shared cookie. Requires moving production domains and makes DAAB trust LAAM's JWT
  secret, coupling the services the card wants kept separate.

## 5. Decisions

### Organizations and roles in DAAB

D-1 **Orgs.** New `organizations` table in DAAB: `id`, `name`, `kind` (`internal` | `customer`),
`laam_org_id` (unique, null for internal), `status` (active | disabled). `users.org_id` and
`projects.org_id` are required after migration. Exactly one internal org.

D-1a **Org lifecycle follows Admin** (calls from Admin's existing operations in
`ennam.kg.admin/src/lib/daab/service.ts`, decided by Claude):
- Disconnect DAAB, org suspended or rejected → DAAB org `disabled`; Go revokes all its web-session keys;
  SSO and DAAB password login are refused for its users; data and projects are kept.
- Reconnect / org re-activated → DAAB org `active` again.
- Connect with a new project on an org that already has a DAAB org → the project joins the same DAAB org.
- Org switches to an attached (shared) project and has no own project left → DAAB org `disabled`.

D-2 **Roles.** Customer-org users get an org role mirroring LAAM: owner, admin, member, viewer. A customer
user may use every project of their org; project role derives from the org role: owner/admin → project
admin, member → developer, viewer → viewer. "Org admin" (owner/admin) is a separate check; it must never
produce an API key with role `admin` — customer keys are always project-scoped to the org's projects.
Internal-org users keep today's model (global role + `project_members`), and internal global admins keep
seeing every org's data for support.

D-3 **Backend enforcement.** Every `role == admin` gate is classified as either internal-only (stays global
admin) or org-admin-capable (Users, Sync Portal). Customer-org sessions get only:
- ADMIN → **Users** (list/create/disable/reset users of their own org) and **Sync Portal** (jobs of their
  org's projects; the global queue endpoint gets an org-scoped variant);
- Dashboard, Projects, Activity, Graph, Schema Graph, Chat, Data Sources — limited to their org's projects.
Usage, Template Library, API Keys, AI Providers, Settings are internal-only, hidden in the dashboard and
refused by the API. A direct URL to a hidden page shows a clear "not available for your account" page.

D-4 **E-mail.** DAAB e-mails become case-insensitively unique (`lower(email)` index, duplicate pre-check in
the migration). A "duplicate e-mail" error to a customer owner must not reveal that the e-mail exists in
another org.

### Provisioning and linking

D-5 **Provisioning on Connect.** Only Ennam Admin's "Connect DAAB (create new project)" provisions DAAB for a
customer: Admin calls Go to create the DAAB org (`laam_org_id`), assign the new project to it, and create the
owner's DAAB account (no password) linked to the LAAM owner's user id. If that e-mail already exists in DAAB,
nothing is auto-linked; Admin shows the conflict for manual resolution. "Attach existing project" creates
nothing in DAAB (D-10).
The owner's LAAM user id comes from LAAM, not from Admin's `ownerEmail`: Admin asks LAAM server-to-server for
the org's owner by LAAM org id (new endpoint). If the org has no owner user yet, the DAAB org is created
without an owner and Admin shows "owner pending"; the owner account is provisioned (retry/button) once LAAM
reports one.

D-6 **Linking is explicit, by id.** `users.laam_user_id` (unique, nullable). A link is made only:
- at provisioning (D-5), or
- when an org owner/admin, in DAAB → Users, picks **"Give DAAB access to a LAAM member"** from the list of
  members of the linked LAAM org (e-mail prefilled, link by LAAM user id; DAAB fetches that list from LAAM
  server-to-server).
"Create a DAAB-only account" creates an unlinked user who signs in only on DAAB's login page. No code path
links accounts by matching e-mail. Internal-org users are never linkable to a customer LAAM user.

D-6a **DAAB roles are managed in DAAB** (decided by Claude). The DAAB org role is stored in Go and chosen by
the org owner/admin in "Give DAAB access" (prefilled from the member's LAAM role); later LAAM role changes do
not change it. The provisioned owner is DAAB owner. Deprovisioning: when a LAAM member is removed from the org
or disabled, LAAM calls Go (service credential) to disable the linked DAAB user and revoke its web sessions;
independently, `POST /sso/codes` is only ever called for LAAM's current, active session user, so a removed
member cannot start SSO.

### Who sees what after LAAM sign-in

D-7 **Home.** A LAAM user with an active link (their DAAB user active, their DAAB org active) lands on a new
LAAM route (not `/home`; builder picks, e.g. `/portal`) with two cards: LAAM "AI Insights & Analysis" →
Open LAAM (the existing LAAM landing logic), DAAB "Data & Connections" → Open DAAB. Everyone else goes
straight into LAAM exactly as today; their right navigation has no DAAB item; a direct DAAB SSO link for
them ends on a clear access message. Orgs not connected to DAAB are unchanged.

D-7a **SSO is for customer orgs only** (owner decision). Ennam staff (LAAM internal org, DAAB internal org) do
not get Home or SSO; they keep signing in to DAAB on its own login page. Go refuses `POST /sso/codes` and
`POST /auth/sso` for any user not in an active customer org, so an SSO code can never carry an internal or
global-admin role.

D-8 **Store scope.** Having a DAAB account means seeing all stores of the org's projects. LAAM store limits
are not carried into DAAB's UI. The "Give DAAB access" dialog warns the owner of this.

### Session hand-off (approach A)

D-9 **Flow** (also covers DAAB deep links for linked users):
1. Browser → DAAB `/sso/start?next=<relative path>`. Dashboard sets a short-lived `sso_state` cookie
   (random) and redirects to LAAM `/sso/authorize?state=<state>&next=…`.
2. LAAM: if not signed in → LAAM login, then back (callbackUrl). If the user has no active link → access page.
   Otherwise LAAM's server calls Go `POST /api/v1/sso/codes` with a dedicated LAAM service credential (new
   secret, not the org agent keys, not the delegation key), sending `laam_user_id`, `laam_org_id`,
   `laam_session_id`, `laam_session_exp`, `sha256(state)`.
3. Go checks: a DAAB user with that `laam_user_id` exists, is active, belongs to an active customer org whose
   `laam_org_id` matches. It returns an opaque random code (≥32 bytes), stored hashed with TTL ≤ 60 s and a
   `used_at`. LAAM redirects to DAAB `/sso/callback?code=…&state=…`.
4. Dashboard verifies `state` equals its cookie, then exchanges `code` + `state` at Go
   `POST /api/v1/auth/sso` (public). Go checks hash, TTL, unused, `sha256(state)`; marks used; reuse of a used
   code is refused. Go mints a web-session key (D-11) and the dashboard sets iron-session, then redirects to
   `next` (relative paths only; anything else → `/`).

### Shared projects

D-10 **Shared projects (option b).** A project attached to more than one customer org belongs to the internal
org: those customers keep using it through LAAM (MCP key) but do not see it in DAAB. Admin refuses to attach
a customer-owned project to another org. An org that attaches a project at runtime gets no DAAB org and no Home
(exception: the one-off migration backfill, D-13, owner decision 2026-11-18).

### Sessions, expiry, sign-out

D-11 **Per-session web keys with expiry.** Login and SSO each mint their own `web-session-*` key; stop revoking
the previous one. New `api_keys.expires_at` (nullable) and `api_keys.laam_session_id` (nullable), used only by
`web-session-*` keys; auth rejects expired keys. SSO keys expire at `laam_session_exp`; DAAB password-login
keys at the cookie lifetime (15 days). Keys without `expires_at` (MCP / manual / org-connection keys) are
unchanged and never touched by sign-out. When an SSO session expires while LAAM is still valid, the dashboard
silently re-runs D-9.

D-12 **Sign-out.**
- LAAM gets server-side session ids: `sid` in the JWT + a `user_sessions` table (or revocation list) checked
  in the existing per-request DB refresh. Sign-out marks the sid revoked, then LAAM's server calls Go
  `POST /api/v1/sso/revoke {laam_session_id}` (service credential) → Go revokes all web-session keys with that
  `laam_session_id`.
- DAAB sign-out: Go `/auth/logout` now revokes the calling web-session key; if the session came from SSO, the
  dashboard then redirects to LAAM `/sso/logout`, which ends the LAAM session (same path as above).
- DAAB password-login sessions (DAAB-only and internal users) sign out of DAAB only.

### Accounts, recovery, cleanup

D-13 **Migration.** Create the internal org; every existing DAAB user and project goes into it. Then, for
each customer org Admin connected via "Connect DAAB" whose project no other org points at: create the
customer DAAB org, move that project, provision the owner (D-5). Projects pointed at by several orgs stay
internal (D-10). Owner decision 2026-11-18 (dev rollout rehearsal): this covers projects the org CREATED and
projects it ATTACHED, as long as no other org points at the project now or ever did (audit log, name suffix);
the same strict test decides "shared" for both. Backfilled attached orgs are then managed like created ones
(Admin suspend/reactivate/disconnect sync, Retry owner). Before migrating, count on prod how many projects are shared and how many users have
`supabase_user_id` without a password.
Ownership: the Go migration creates the internal org and assigns everything to it. The customer part is an
Admin backfill job (Admin knows created vs attached projects from its own state/audit and already holds the
DAAB admin key) that calls the new Go org/provisioning endpoints and the LAAM owner lookup (D-5). It is
idempotent and re-runnable.

D-14 **Remove Supabase before customer user creation ships.** Remove the Supabase login button, `/auth/supabase`
(both web and `?session=consumer`), the Supabase wiring in user creation and the identity provisioner, and the
`KG_SUPABASE_*` / `NEXT_PUBLIC_SUPABASE_*` env. Preconditions: confirm AAAA does not use the consumer path in
prod; give Supabase-only users a password (admin reset) first.

D-15 **Password recovery.** LAAM gets self-service "forgot password": single-use token (hashed, ~30 min TTL),
e-mail sent via **Resend** (free tier: 100/day, 1 sending domain; needs DNS records on the sending domain —
DevOps). Reset revokes the user's other LAAM sessions. DAAB-only users are reset by their org owner/admin
(the existing admin reset, scoped to the org); internal users by a global admin.

D-16 **Deep links.** LAAM login honours `callbackUrl` (relative paths only). DAAB: unauthenticated →
`/login?next=…`; the DAAB login page offers "Sign in with AIO Analytics" (→ D-9 with `next`) next to the
password form.

### UI

D-17 Right navigation (Home, LAAM, DAAB, Settings, profile, Sign out) in both apps, same look (navy/teal/blue),
built separately per app; active item highlighted; collapses to an icon rail / drawer on small screens. The
existing in-app left sidebars stay for in-module navigation. Header shows the company (org) name. In DAAB,
Home and LAAM items appear only for SSO sessions; DAAB-only users see DAAB-only items. Settings opens the
current module's settings; profile and Sign out follow D-12.

## 5b. Security invariants and amendments (from the spec review, verified in code)

These amend the decisions above; where they conflict, this section wins.

H-1 **Authorization lives on the user row, not the key** (amends D-2, D-7a). Web sessions are authorized from
`users.role` and `project_members` (`ennam.kg.go/internal/handler/project.go:57-60`,
`internal/handler/project_role.go:104-109`), so constraining the key is not enough:
- DB CHECK: a user in a customer org can never have `users.role = 'admin'`.
- `isGlobalAdmin` (and every global-admin gate) also requires the caller's org to be the internal org.
- Customer project access is materialised as `project_members` rows for every project of the org (role per
  D-2), written on user create/role change/project join; this keeps `ListProjects` and activity filters
  working unchanged.

H-2 **Org-scoped Users endpoints** (amends D-3): separate handlers that ignore any requested global `Role`,
force `org_id` to the caller's org, and return 404 for user ids outside it (update, reset, disable, delete).
QA: an org admin cannot create `role=admin`, cannot reset/disable an internal user or another org's user.

H-3 **User resolution per key, fail closed** (amends D-11). Today the user is found via `users.api_key_id`
(one key per user, `internal/store/user.go:84`) and resolution failure is ignored
(`internal/middleware/auth.go:217-224`). In the same step as per-session keys: resolve by
`api_keys.user_id`; if a key has a `user_id` and resolution fails, reject the request; on every request check
user status and org status (same DB read), so disabling a user or org takes effect immediately, not only via
revocation.

H-4 **SSRF guard before customers get Data Sources** (amends D-3). Customers may create data sources (the card:
"Connect sources. Import data."), but Go dials any host (`internal/service/datasource.go:526-641`) and test
steps leak dial errors. Before customer Data Sources ships: a dialer guard refusing private, loopback,
link-local and metadata addresses (resolved IP checked at dial time, not the hostname), with an explicit
allowlist for internal use; customer-facing errors are generic.

H-5 **SSO service credential** (D-9, D-12): a dedicated shared secret (env, rotatable via key id) accepted only
by the `/sso/*` server-to-server routes, never an `api_keys` row; every other gate ignores it.

H-6 **Revocation beyond sign-out** (amends D-11, D-12): SSO keys expire at `min(laam_session_exp, now + 4h)`;
when expired, the dashboard re-runs D-9, which re-checks LAAM. LAAM calls Go `POST /sso/revoke` by
`laam_user_id` (all that user's SSO keys) on password change, password reset, user disable/removal, and when
the JWT refresh drops the session. A failed revoke call is logged and bounded by the 4 h cap. With the cap,
LAAM's session store may be a revoked-sid list rather than a full sessions table (builder's choice).

H-7 **Migration classifies existing users** (amends D-13). Step 1 of the rollout lists every existing DAAB user
with e-mail, role, projects and Supabase link; the owner marks each as Ennam staff or customer (customer users
are moved to their customer org with D-2 roles, or disabled). No customer person lands in the internal org.

H-8 **Link check** (amends D-6): before storing `laam_user_id`, Go asks LAAM server-to-server whether that user
belongs to the org's `laam_org_id`; otherwise refuse.

H-9 **Fail closed on the LAAM side**: `/sso/authorize` reads the session and sid from the DB and refuses on any
error (today the JWT refresh keeps the session on DB errors, `LAAM/src/lib/auth/session-refresh.ts:132-138`).

H-10 **Redirect hygiene** (D-9, D-12, D-16): `next` must start with a single `/` and reject `//`, `/\`, and
encoded variants; the DAAB callback URL in LAAM comes from config, never from a parameter; `sso_state` cookie
is HttpOnly, Secure, SameSite=Lax, ~5 min; `/sso/logout` is POST (or a confirm page).

H-11 **Expired session during API calls** (D-11): when a BFF/TanStack call gets 401 for an SSO session, the
dashboard performs a top-level navigation to `/sso/start?next=<current path>` instead of showing an error.

H-12 **E-mail uniqueness stays global** (amends D-4, decided by Claude): DAAB login is global, so uniqueness
cannot be per org. Create-user failure shows one generic message ("this e-mail can't be used") and the
endpoint is rate-limited; LAAM registration already has the same property.

H-13 **Untouched keys, stated explicitly**: MCP org-connection agent keys and delegation tickets authenticate
through the key path with no linked user (`internal/handler/project_role.go:110-114`,
`internal/handler/ai_query_scope.go:33-49`). They have no `expires_at`, no `laam_session_id`, and are not
affected by sign-out, revocation by user, or H-3.

## 6. Deviations from the card (to tell the team / Huy)

- The card describes one sign-in for everyone. DAAB keeps a password login for internal staff and DAAB-only
  accounts.
- The card sends everyone to Home. Here only users with DAAB access see Home; LAAM-only users go straight into
  LAAM.
- "Existing account recovery flow" does not exist; it is built (LAAM only).
- DAAB does not apply LAAM store limits (D-8).

## 7. Rollout order

Each step ships behind default-OFF flags where user-visible.
1. Prod pre-checks (D-13 counts, AAAA consumer usage).
2. DAAB orgs + migration to internal org + authorization split (invisible to users).
3. Per-session keys + expiry + case-insensitive e-mail; Supabase removal (D-14).
4. Admin provisioning (D-5), org-scoped Users/Sync, linking UI (D-6), customer menus (D-3).
5. SSO hand-off, LAAM session ids, sign-out both ways, deep links (D-9, D-11, D-12, D-16).
6. Home + right navigation in both apps (D-7, D-17).
7. Password recovery (D-15).

## 8. QA (from the card)

Full-access user (linked owner), LAAM-only user, DAAB-only user, internal user; both Home cards; LAAM ↔ DAAB
without second login; direct links to DAAB for linked / unlinked / other-org users; refresh; expired LAAM
session and expired DAAB key; sign-out from each side ends both; customer cannot reach another org's project
by id or URL; internal users keep all current access; desktop + collapsed nav; screenshots + QA results on the
card.

## 9. Left to the builder

Route names, table/column names beyond those fixed above, code TTLs within the stated bounds, how LAAM lists
org members to DAAB (server-to-server endpoint shape), right-nav component structure, Resend integration
details, exact classification list of each admin gate (must follow D-3), feature-flag names.
