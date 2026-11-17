# Unified login — Plan 1: DAAB org foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give DAAB organizations, an authorization model that keeps customer users inside their org, per-session expiring web keys, org-scoped Users/Sync for customer org admins, an SSRF guard for customer data sources, and remove Supabase — with no visible change for today's (all-internal) users.

**Architecture:** One fixed-UUID internal org; every existing user/project defaults into it. Customer orgs (created by Plan 2) carry `laam_org_id`; customer users get an `org_role` and `project_members` rows for all org projects, never `users.role='admin'` (DB trigger). Global-admin gates additionally require the internal org. Auth resolves the user per key (`api_keys.user_id`), fails closed, and checks user + org status on every request.

**Tech Stack:** Go (stdlib net/http, database/sql, golang-migrate, lib/pq), Next.js 16 dashboard (iron-session), PostgreSQL 16 (dev) / RDS PG15 (prod).

**Spec:** `docs/superpowers/specs/2026-11-17-unified-login-design.md` (D-1..D-4, D-11, D-14, §5b H-1..H-4, H-7, H-12, H-13). Plans 2–4 (Admin provisioning + linking; SSO + sign-out + deep links; Home + right nav + password recovery) follow and depend on this one.

## Global Constraints

- Branch `task/portal_login` in `ennam.kg.go`, `ennam.kg.next` (and workspace for docs). `ennam.kg.go` is a nested git repo: commit with `git -C ennam.kg.go`.
- Migrations: `ennam.kg.go/db/migrations/NNNNNN_name.{up,down}.sql`; current highest is `000100`. This plan adds `000101`, `000102`, `000103`.
- Internal org id is the fixed UUID `00000000-0000-0000-0000-0000000000a1`, name `Ennam`, kind `internal`.
- Org kinds: `internal` | `customer`. Org status: `active` | `disabled`. Org roles: `owner` | `admin` | `member` | `viewer`.
- Org role → project role: owner/admin → `admin`, member → `developer`, viewer → `viewer` (spec D-2).
- A customer-org user can never have `users.role = 'admin'` (H-1).
- Web-session keys: label prefix `web-session-`; password-login keys expire after 15 days (`webSessionTTL = 15 * 24 * time.Hour`). Keys with `expires_at IS NULL` (MCP, manual, org-connection, consumer) are never expired, never revoked by logout, unaffected by user resolution changes (H-13).
- Customer-facing errors for duplicate e-mail: exactly `this e-mail can't be used` (H-12).
- Must run on PostgreSQL 15 (prod RDS): no PG16-only syntax.
- Go tests: store/handler DB tests read `KG_TEST_DATABASE_URL` (dev DB is on port **5433**, e.g. `postgres://...@localhost:5433/ennam_kg_test?sslmode=disable`); a test that SKIPs still reports PASS — check the `-v` output for `SKIP`.
- Dashboard has no test runner: verify with `npm run lint` and `npm run build` plus a browser check.
- No `--no-verify` on commits.

## Review Focus

1. A web key whose user lookup errors (DB blip) must be rejected, not downgraded to "key-only" access — tested in Task 4.
2. An internal global admin must keep seeing every project after the migration (no regression for staff) — tested in Task 5.
3. Two dashboard tabs/devices logged in as the same user both keep working after a second login — tested in Task 4.
4. An org admin calling `PATCH /api/v1/org/users/{id}` with an id from another org or the internal org gets 404, not 403 (no existence leak) — tested in Task 6.
5. A customer data source whose hostname resolves to `10.x`, `127.x`, `169.254.169.254` or `::1` is refused at dial time, while internal-org data sources on the private RDS keep working — tested in Task 7.

---

### Task 1: Organizations schema, internal org, org columns, guards, case-insensitive e-mail

**Files:**
- Create: `ennam.kg.go/db/migrations/000101_organizations.up.sql`, `000101_organizations.down.sql`
- Test: `ennam.kg.go/internal/store/organization_migration_test.go`

**Interfaces:**
- Produces (DB): table `organizations(id uuid pk, name text not null, kind text check in ('internal','customer'), laam_org_id text unique null, status text check in ('active','disabled') default 'active', created_at, updated_at)`; row for the internal org; `users.org_id uuid not null default '…a1' references organizations`, `users.org_role text null check in ('owner','admin','member','viewer')`; `projects.org_id uuid not null default '…a1' references organizations`; trigger `trg_users_org_guard`; unique index `idx_users_email_lower` on `lower(email) where email is not null` replacing `idx_users_email`.

- [ ] **Step 1: Write the failing tests** (package `store_test`, use `setupTestDB(t)` from `internal/store/favorite_test.go:19`)

```go
func TestOrgMigration_ExistingRowsLandInInternalOrg(t *testing.T) {
    // every users.org_id and projects.org_id = '00000000-0000-0000-0000-0000000000a1'
}
func TestOrgMigration_CustomerUserCannotBeGlobalAdmin(t *testing.T) {
    // insert customer org; insert user with org_id=customer, role='admin', org_role='owner'
    // → error contains "customer org user cannot have global role admin"
}
func TestOrgMigration_CustomerUserNeedsOrgRole(t *testing.T) {
    // customer user with org_role NULL → error contains "customer org user requires org_role"
}
func TestOrgMigration_EmailUniqueIgnoresCase(t *testing.T) {
    // insert "A@x.com" then "a@x.com" → unique violation on idx_users_email_lower
}
```

- [ ] **Step 2: Run to verify they fail**
Run: `cd ennam.kg.go && KG_TEST_DATABASE_URL=... go test ./internal/store/ -run TestOrgMigration -v`
Expected: FAIL (relation "organizations" does not exist).

- [ ] **Step 3: Write `000101_organizations.up.sql`**
  - Before creating `idx_users_email_lower`, the migration aborts with `RAISE EXCEPTION 'duplicate e-mails differing only by case: %', <list>` if `SELECT lower(email) … GROUP BY 1 HAVING count(*)>1` returns rows (an operator fixes data, then reruns).
  - Trigger function `users_org_guard()` (BEFORE INSERT OR UPDATE OF org_id, role, org_role ON users): if the org's kind is `customer` then `role='admin'` → `RAISE EXCEPTION 'customer org user cannot have global role admin'`, `org_role IS NULL` → `RAISE EXCEPTION 'customer org user requires org_role'`; if kind is `internal`, force `org_role := NULL`.
  - `.down.sql` drops trigger, function, columns, table, and restores `idx_users_email` (case-sensitive, partial).

- [ ] **Step 4: Apply and run tests**
Run: `make db-migrate` against the test DB (`KG_DATABASE_URL` pointing at :5433 test DB), then the test command above. Expected: PASS (4 tests, none SKIP). Also run `go run ./cmd/kg-migrate/ down 1` then `up` once to prove the down migration works.

- [ ] **Step 5: Commit**
`git -C ennam.kg.go add db/migrations/000101_* internal/store/organization_migration_test.go && git -C ennam.kg.go commit -m "feat(org): organizations table, internal org, org columns and guards"`

---

### Task 2: Organization model and store; org fields on User and Project

**Files:**
- Create: `ennam.kg.go/internal/models/organization.go`, `ennam.kg.go/internal/store/organization.go`
- Modify: `internal/models/user.go:78-94` (add `OrgID string`, `OrgRole *OrgRole`), `internal/models/project.go:6` (add `OrgID string`), `internal/store/user.go:23-25,305` (columns + scan), `internal/store/user.go:143` (`GetByEmail` uses `lower(email) = lower($1)`), `internal/store/project.go` (select/scan `org_id`; `Create` leaves it to the DB default unless set)
- Test: `ennam.kg.go/internal/store/organization_test.go`

**Interfaces:**
- Produces:
  - `models.InternalOrgID = "00000000-0000-0000-0000-0000000000a1"`
  - `type OrgKind string` (`OrgKindInternal`, `OrgKindCustomer`); `type OrgStatus string` (`OrgStatusActive`, `OrgStatusDisabled`); `type OrgRole string` (`OrgRoleOwner`, `OrgRoleAdmin`, `OrgRoleMember`, `OrgRoleViewer`)
  - `func (r OrgRole) ProjectRole() ProjectMemberRole` (owner/admin→admin, member→developer, viewer→viewer)
  - `func (r OrgRole) CanManageUsers() bool` (owner, admin)
  - `type Organization struct { ID, Name string; Kind OrgKind; LAAMOrgID *string; Status OrgStatus; CreatedAt, UpdatedAt time.Time }`
  - `store.OrganizationStore` with `NewOrganizationStore(db *sql.DB)`, `Create(ctx, *models.Organization) (*models.Organization, error)`, `GetByID(ctx, id string) (*models.Organization, error)` (nil,nil if none), `GetByLAAMOrgID(ctx, laamOrgID string) (*models.Organization, error)`, `SetStatus(ctx, id string, status models.OrgStatus) error`, `ListProjectIDs(ctx, orgID string) ([]string, error)`

- [ ] **Step 1: Write failing tests**: `TestOrganizationStore_CreateAndGetByLAAMOrgID`, `TestOrganizationStore_SetStatus`, `TestOrganizationStore_ListProjectIDs_OnlyOrgProjects`, `TestUserStore_GetByEmail_CaseInsensitive` (create `Bob@X.com`, `GetByEmail("bob@x.com")` returns it), `TestOrgRole_ProjectRole` (table test of the 4 mappings — pure unit, no DB).
- [ ] **Step 2: Run** `go test ./internal/store/ ./internal/models/ -run 'Organization|GetByEmail_CaseInsensitive|OrgRole' -v` → FAIL (undefined).
- [ ] **Step 3: Implement** the model and store per Interfaces; extend `userColumns`/`scanOneRow` and project scans in the same column order.
- [ ] **Step 4: Run** the same command plus `go test ./internal/store/... ./internal/service/... -count=1` → PASS, no new failures in existing user/project tests.
- [ ] **Step 5: Commit** `feat(org): organization model/store, org fields on user and project`

---

### Task 3: Expiring web-session keys (schema + Authenticate)

**Files:**
- Create: `ennam.kg.go/db/migrations/000102_api_key_session_expiry.{up,down}.sql`
- Modify: `internal/models/apikey.go:47-95` (add `ExpiresAt *time.Time`, `LAAMSessionID *string`; `IsActive()` also false when `ExpiresAt != nil && !ExpiresAt.After(time.Now())`), `internal/store/apikey.go:26,98,114,352` (insert/select the two columns; `Authenticate` returns error `"api key has expired"` for expired keys), `internal/service/apikey.go` (`CreateKeyRequest` gains `ExpiresAt *time.Time`, `LAAMSessionID *string`, passed through)
- Test: `ennam.kg.go/internal/store/apikey_expiry_test.go`

**Interfaces:**
- Produces (DB): `api_keys.expires_at timestamptz null`, `api_keys.laam_session_id text null`, index `idx_api_keys_laam_session_id` (partial, not null). Used by Plan 3 for SSO keys.
- Produces (Go): `CreateKeyRequest.ExpiresAt`, `CreateKeyRequest.LAAMSessionID`, `models.APIKey.ExpiresAt`, `models.APIKey.LAAMSessionID`.

- [ ] **Step 1: Failing tests**: `TestAuthenticate_RejectsExpiredKey` (expires_at = now−1m → error "api key has expired"), `TestAuthenticate_AcceptsUnexpiredKey` (now+1h → ok), `TestAuthenticate_NullExpiryNeverExpires` (expires_at NULL, created 400 days ago → ok).
- [ ] **Step 2: Run** `go test ./internal/store/ -run TestAuthenticate_ -v` → FAIL.
- [ ] **Step 3: Implement** migration + model/store/service changes.
- [ ] **Step 4: Run** the tests + `go test ./internal/middleware/ ./internal/service/ -count=1` → PASS.
- [ ] **Step 5: Commit** `feat(auth): optional expiry and LAAM session id on api keys`

---

### Task 4: Per-key user resolution, fail closed, org/user status on every request; one key per login; logout revokes

**Files:**
- Modify: `internal/middleware/auth.go:24-30` (`UserIdentity` gains `OrgID, OrgKind, OrgRole string`), `:124` (resolver signature unchanged), `:217-224` (fail closed), `cmd/kg-server/main.go:250-266` (resolver uses the new store method), `internal/store/user.go` (new method), `internal/service/user.go:465-551` (Login: stop revoking; set `ExpiresAt`), `:610-652` is deleted in Task 8 (do not touch here), `internal/handler/auth.go:278` (Logout revokes)
- Test: `internal/middleware/auth_test.go`, `internal/store/user_identity_test.go`, `internal/service/user_login_session_test.go`, `internal/handler/auth_logout_test.go`

**Interfaces:**
- Consumes: Task 2 `models.Organization`, Task 3 `CreateKeyRequest.ExpiresAt`.
- Produces:
  - `func (s *UserStore) GetIdentityByAPIKeyID(ctx context.Context, apiKeyID string) (*models.User, *models.Organization, error)` — joins `api_keys.user_id → users → organizations`; returns `(nil, nil, nil)` when the key has no `user_id`.
  - Resolver contract: returns `ErrIdentityRejected` (new, in `middleware`) when the user is not active or the org is disabled.
  - Middleware: if `key.UserID != nil` and the resolver returns any error or a nil identity → 401 `{"error":"session no longer valid"}`; if `key.UserID == nil` → key-only identity as today.
  - `func (s *UserService) Logout(ctx context.Context, keyID string) error` — revokes the key only if its label starts with `web-session-`; otherwise no-op.
  - `webSessionTTL = 15 * 24 * time.Hour` in `internal/service/user.go`.

- [ ] **Step 1: Failing tests**
  - `TestAuth_UserKey_ResolverError_Returns401` (mock resolver returns `errors.New("db down")`, key has UserID → 401)
  - `TestAuth_UserKey_DisabledOrg_Returns401` (resolver returns `ErrIdentityRejected` → 401)
  - `TestAuth_KeyWithoutUser_ResolverNotRequired` (agent key, UserID nil → 200, no UserIdentity in ctx)
  - `TestGetIdentityByAPIKeyID_ResolvesNonLatestKey` (two keys for one user; the older one still resolves to the user — this is the bug fixed by H-3)
  - `TestLogin_SecondLoginKeepsFirstKeyValid` (login twice; `Authenticate(firstKey)` succeeds)
  - `TestLogin_WebSessionKeyExpiresIn15Days` (`ExpiresAt` within 1 min of now+15d)
  - `TestLogout_RevokesOnlyWebSessionKeys` (web-session key revoked; a manual key passed to Logout stays active)
- [ ] **Step 2: Run** `go test ./internal/middleware/ ./internal/store/ ./internal/service/ ./internal/handler/ -run 'Auth_|GetIdentityByAPIKeyID|Login_|Logout_' -v` → FAIL.
- [ ] **Step 3: Implement** per Interfaces. Login still calls `UpdateAPIKeyID` (column now means "last session"). Logout handler takes the key id from `DeveloperIdentity.KeyID`.
- [ ] **Step 4: Run** the tests above, then the whole module: `cd ennam.kg.go && KG_TEST_DATABASE_URL=... go test ./... -race -count=1` → PASS.
- [ ] **Step 5: Commit** `fix(auth): resolve user per key and fail closed; one web key per login; logout revokes`

---

### Task 5: Global admin requires the internal org; customer project access via project_members

**Files:**
- Modify: `internal/handler/project.go:57-66` (`isGlobalAdmin`), `internal/handler/user.go:65` (`requireAdmin` takes `r *http.Request` and also requires internal org when a UserIdentity is present), `internal/handler/oauth.go:49-59` (`requireAdminRole` same rule), `internal/handler/landed_guards.go:46` (same), every inline `APIKeyRoleAdmin` gate in `settings.go:129,174,208`, `activity.go:59,186`, `neighbors.go:304`, `session_search.go:163` → route through one helper
- Create: `internal/handler/authz_org.go`, `internal/service/org_access.go`
- Test: `internal/handler/authz_org_test.go`, `internal/service/org_access_test.go`

**Interfaces:**
- Consumes: Task 4 `UserIdentity.OrgKind/OrgID/OrgRole`.
- Produces:
  - `func isInternalCaller(r *http.Request) bool` — true for key-only callers (no UserIdentity) and for users whose `OrgKind == "internal"`.
  - `isGlobalAdmin(r)` = previous rule `&& isInternalCaller(r)`; all listed gates call `isGlobalAdmin` (or `requireAdmin(w, r)`), so there is one rule.
  - `func orgAdminCaller(r *http.Request) (orgID string, ok bool)` — UserIdentity with `OrgKind=="customer"` and `OrgRole` in owner/admin.
  - `service.OrgAccessService` with `NewOrgAccessService(orgs OrgRepository, members MemberRepository, users UserRepository)` and `SyncUserProjects(ctx, userID string) error` (upsert one `project_members` row per org project with `OrgRole.ProjectRole()`; remove rows for projects outside the org) and `SyncOrgProjects(ctx, orgID string) error` (calls `SyncUserProjects` for every user of the org). Plan 2 calls `SyncOrgProjects` when a project joins an org.

- [ ] **Step 1: Failing tests**
  - `TestIsGlobalAdmin_CustomerUserWithAdminKeyRole_False` (UserIdentity Role "admin", OrgKind "customer" → false; defence in depth even though the DB forbids it)
  - `TestIsGlobalAdmin_InternalAdmin_True` and `TestIsGlobalAdmin_AdminKeyNoUser_True` (no regression for staff and MCP admin keys)
  - `TestSettingsGet_CustomerOrgAdmin_403` (GET `/api/v1/settings` as customer owner → 403)
  - `TestSyncUserProjects_MemberGetsDeveloperOnAllOrgProjects` (2 org projects + 1 other → exactly 2 rows, role developer)
  - `TestSyncUserProjects_RemovesForeignMembership` (pre-existing row on a project outside the org is removed)
- [ ] **Step 2: Run** `go test ./internal/handler/ ./internal/service/ -run 'IsGlobalAdmin|SettingsGet_Customer|SyncUserProjects' -v` → FAIL.
- [ ] **Step 3: Implement**. Grep after implementing: `grep -rn "APIKeyRoleAdmin" internal/handler | grep -v _test` must show only `isGlobalAdmin`, `projectRoleForKeyRole`, `apikey_mgmt.go:92` (create-key refusal) and `landed_guards.go:66` (WorkerGuard, key-only).
- [ ] **Step 4: Run** full `go test ./... -race -count=1` → PASS.
- [ ] **Step 5: Commit** `feat(authz): global admin requires internal org; org project access via project_members`

---

### Task 6: Org-scoped Users and Sync endpoints for customer org admins

**Files:**
- Create: `internal/handler/org_users.go`, `internal/handler/org_queue.go`, `internal/service/org_users.go`
- Modify: `cmd/kg-server/main.go` (register routes), `internal/handler/admin_dashboard.go:52-56` (reuse its queue query with a project filter)
- Test: `internal/handler/org_users_test.go`, `internal/handler/org_queue_test.go`

**Interfaces:**
- Consumes: Task 5 `orgAdminCaller`, `OrgAccessService.SyncUserProjects`.
- Produces routes (all require `orgAdminCaller`; otherwise 403):
  - `GET /api/v1/org/users` — users of the caller's org only.
  - `POST /api/v1/org/users` body `{username, email, display_name, org_role, password}`; `org_role` ∈ admin/member/viewer (only an owner may create `admin`; nobody may create `owner` here); `users.role` is forced to `developer` (viewer for org_role viewer); `org_id` forced to caller's org; then `SyncUserProjects`. Duplicate e-mail/username → 409 `{"error":"this e-mail can't be used"}`.
  - `PATCH /api/v1/org/users/{id}` (display_name, org_role), `POST /api/v1/org/users/{id}/disable|enable|reset-password` — any id not in the caller's org → **404**.
  - `GET /api/v1/org/queue/query` — same response shape as `GET /api/v1/queue/query`, restricted to jobs of the org's projects.
  - Create rate limit: 20 creates per org per hour, in-memory (`golang.org/x/time/rate` if already a dependency, else a small mutex-guarded counter), → 429.
- `service.OrgUserService` with `Create(ctx, orgID string, actorRole models.OrgRole, req OrgCreateUserRequest) (*models.User, error)`, `Update`, `SetStatus`, `ResetPassword(ctx, orgID, userID, newPassword string) error`; returns `ErrNotInOrg` (→404) and `ErrEmailUnavailable` (→409).

- [ ] **Step 1: Failing tests**
  - `TestOrgUsers_Create_IgnoresGlobalRoleField` (body includes `"role":"admin"` → created user has role developer)
  - `TestOrgUsers_AdminCannotCreateAdmin` (actor org_role admin, org_role admin requested → 403)
  - `TestOrgUsers_PatchOtherOrgUser_404` and `TestOrgUsers_ResetInternalAdmin_404`
  - `TestOrgUsers_DuplicateEmail_GenericMessage` (409, body exactly `this e-mail can't be used`)
  - `TestOrgUsers_MemberCaller_403`
  - `TestOrgQueue_OnlyOrgProjects`
- [ ] **Step 2: Run** `go test ./internal/handler/ -run 'OrgUsers|OrgQueue' -v` → FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** the tests + `go test ./... -race -count=1` → PASS.
- [ ] **Step 5: Commit** `feat(org): org-scoped users and sync queue endpoints for customer org admins`

---

### Task 7: SSRF guard for customer-org data sources

**Files:**
- Create: `ennam.kg.go/internal/netguard/netguard.go`, `netguard_test.go`
- Modify: dialers in `internal/service/datasource.go:501-641`, `schema_extractor.go:291`, `source_executor.go:160-173`, `source_write.go:178`, `playbook.go:600`; `cmd/kg-server/main.go` (config)
- Test: `internal/netguard/netguard_test.go`, `internal/service/datasource_guard_test.go`

**Interfaces:**
- Produces:
  - `func netguard.CheckIP(ip net.IP, allow []*net.IPNet) error` — refuses loopback, private (RFC1918, fc00::/7), link-local (169.254/16, fe80::/10, incl. 169.254.169.254), unspecified, multicast, CGNAT 100.64/10, unless inside `allow`. Error text `destination not allowed`.
  - `func netguard.Control(allow []*net.IPNet) func(network, address string, c syscall.RawConn) error` — for `net.Dialer.Control`, checks the resolved IP at dial time (defeats DNS rebinding).
  - `func netguard.DialerFor(guarded bool, allow []*net.IPNet) *net.Dialer`.
  - Env `KG_DATASOURCE_ALLOW_CIDRS` (comma-separated, default empty).
  - Rule: the guard applies when the data source's project belongs to a **customer** org; internal-org data sources are unguarded (internal demo sources live on the private RDS). Every dialer above gets its `net.Dialer` (and the driver's dialer hook, e.g. lib/pq `Connector.Dialer`) from `DialerFor`.
  - `TestConnection` step errors for guarded sources are replaced by `connection failed` (no raw dial error).

- [ ] **Step 1: Failing tests**: `TestCheckIP` (table: 10.0.0.1, 127.0.0.1, 169.254.169.254, ::1, 100.64.0.1 refused; 8.8.8.8 allowed; 10.1.2.3 allowed when `10.1.0.0/16` in allow), `TestControl_RefusesResolvedPrivateIP` (dial `localhost:1` via guarded dialer → error contains `destination not allowed`), `TestTestConnection_CustomerSource_GenericError`, `TestTestConnection_InternalSource_Unguarded`.
- [ ] **Step 2: Run** `go test ./internal/netguard/ ./internal/service/ -run 'CheckIP|Control_|TestConnection_' -v` → FAIL.
- [ ] **Step 3: Implement** per Interfaces; find any other `sql.Open`/`net.Dial` on data-source hosts with `grep -rn "sql.Open\|net.Dial\|tls.Dial" internal/service` and route them through `DialerFor`.
- [ ] **Step 4: Run** the tests + full `go test ./... -race -count=1` → PASS.
- [ ] **Step 5: Commit** `feat(security): SSRF guard for customer-org data source connections`

---

### Task 8: Remove Supabase (Go + dashboard), password login back as the only DAAB login

**Precondition (ops, before merging to main — not before coding):** run the report from Task 9 on prod; every user with `supabase_user_id` and NULL `password_hash` gets a password via admin reset; confirm with the AAAA owner that `POST /api/v1/auth/supabase?session=consumer` is unused in prod. Record both in `docs/deploy/2026-11-17-unified-login-p1-checklist.md`.

**Files:**
- Delete: `ennam.kg.go/internal/supabaseauth/`, `ennam.kg.go/internal/supabaseadmin/`, `internal/handler/auth_supabase_test.go`, `internal/service/user_supabase*_test.go`, `internal/store/user_supabase_test.go`, `ennam.kg.next/src/lib/supabase/`
- Modify: `internal/handler/auth.go` (drop `SupabaseVerifier`, `SupabaseLogin`, route `/auth/supabase`, `adminEmails`), `internal/middleware/auth.go:311` (drop exempt path), `internal/service/user.go` (drop `IdentityProvisioner`, `SetIdentityProvisioner`, `provisionIdentity`, `rollbackIdentity`, `syncIdentityPassword`, `resolveSupabaseUser`, `LoginWithSupabase`, `LoginWithSupabaseConsumer`; `CreateUser` no longer requires e-mail), `internal/store/user.go:97-140` (drop Supabase methods; keep the `supabase_user_id` column in the scan for now), `cmd/kg-server/main.go:48-49,994-1022`, `docker-compose.yml:107-111,301-312`, `docker-compose.release.yml:88-92,232-236`, `envfiles/envfiles/kg-server.env`, `kg-dashboard.env`, `ennam.kg.next/src/app/(auth)/login/LoginForm.tsx` (password form only), `.../login/actions.ts` (drop `supabaseLoginAction`), `src/components/users/CreateUserDialog.tsx:133` (e-mail optional), `ennam.kg.next/Dockerfile:19-22`, `ennam.kg.next/package.json:23` (+ lockfile)
- Test: `internal/handler/auth_test.go`

**Interfaces:**
- Produces: `NewAuthHandler(userService *service.UserService, logger *slog.Logger)`; `POST /api/v1/auth/supabase` → 404.

- [ ] **Step 1: Failing test**: `TestAuthRoutes_SupabaseRouteGone` (POST `/api/v1/auth/supabase` → 404).
- [ ] **Step 2: Run** `go test ./internal/handler/ -run TestAuthRoutes_SupabaseRouteGone -v` → FAIL (route returns 503/400).
- [ ] **Step 3: Remove** everything listed. Then `grep -rni supabase ennam.kg.go --include=*.go | grep -v migrations` and `grep -rni supabase ennam.kg.next/src ennam.kg.next/package.json` must return nothing except the `supabase_user_id` column in `store/user.go`/`models/user.go`.
- [ ] **Step 4: Verify**: `cd ennam.kg.go && go build ./... && go test ./... -race -count=1` → PASS; `cd ennam.kg.next && npm install && npm run lint && npm run build` → success; browser: `http://localhost:3500/login` shows only username/password and logs in an internal admin.
- [ ] **Step 5: Commit** in both repos: `refactor(auth): remove Supabase login and identity provisioning`

---

### Task 9: User classification report (H-7)

**Files:**
- Create: `ennam.kg.go/cmd/kg-report-users/main.go`, `ennam.kg.go/cmd/kg-report-users/main_test.go`

**Interfaces:**
- Produces: CLI `go run ./cmd/kg-report-users -dsn "$KG_DATABASE_URL" > users.csv` writing CSV header exactly
  `id,username,email,global_role,status,has_password,supabase_linked,last_login_at,projects,classification`
  — `projects` is `;`-joined project names from `project_members`; `classification` is left empty for the owner to fill with `staff` or `customer:<laam_org_id>` (consumed by Plan 2's backfill). Read-only: the command opens a transaction with `SET TRANSACTION READ ONLY`.

- [ ] **Step 1: Failing test**: `TestWriteUserReport_HeaderAndRow` (seed one user with 2 projects; output line 1 equals the header above; row has `projects` = `a;b`, `has_password` = `true`).
- [ ] **Step 2: Run** `go test ./cmd/kg-report-users/ -v` → FAIL.
- [ ] **Step 3: Implement** `func writeUserReport(ctx context.Context, db *sql.DB, w io.Writer) error` + `main`.
- [ ] **Step 4: Run** the test → PASS; run it against the dev DB and eyeball the CSV.
- [ ] **Step 5: Commit** `feat(ops): read-only user classification report`

---

### Task 10: Dashboard — org-aware session, admin gate and menus

**Files:**
- Modify: `ennam.kg.next/src/lib/auth/session.ts:4-16` (add `orgKind?: 'internal' | 'customer'`, `orgRole?: 'owner' | 'admin' | 'member' | 'viewer'`), `src/app/(auth)/login/actions.ts:44` (store them from the login response), `src/app/(dashboard)/admin/layout.tsx:12`, `src/components/layout/Sidebar.tsx:70-82,142-143`, `src/components/layout/DashboardShell.tsx:37-38`, admin Users page and Sync page (call `/api/kg/org/users` and `/api/kg/org/queue/query` when `orgKind === 'customer'`)
- Create: `src/app/(dashboard)/not-available/page.tsx`, `src/lib/auth/org-access.ts`
- Modify (Go): `internal/handler/auth.go` login response includes `user.org_kind` and `user.org_role` (from Task 2 fields) — add a Go test `TestLogin_ResponseIncludesOrg`.

**Interfaces:**
- Produces: `canSeeAdminItem(session: SessionData, href: string): boolean` in `org-access.ts` — internal + role admin → all items; customer + orgRole owner/admin → only `/admin/users`, `/admin/sync`; else none. Admin layout uses it with the current path; denied → `redirect('/not-available')`, which renders "This page is not available for your account." with a link to `/`.

- [ ] **Step 1: Failing Go test** `TestLogin_ResponseIncludesOrg` → run `go test ./internal/handler/ -run TestLogin_ResponseIncludesOrg -v` → FAIL; implement; → PASS. Commit in `ennam.kg.go`.
- [ ] **Step 2: Implement** the dashboard changes per Interfaces.
- [ ] **Step 3: Verify**: `npm run lint && npm run build` → success. Browser with two local users: internal admin sees all 7 ADMIN items; a customer owner (create one with SQL: customer org + user with `org_role='owner'`, role developer) sees only Users and Sync Portal, gets the not-available page on `/admin/usage`, and the Users page lists only their org.
- [ ] **Step 4: Commit** in `ennam.kg.next`: `feat(org): org-aware admin gate and menus for customer org admins`

---

## Self-review notes

- Spec coverage for this plan: D-1 (T1–2), D-2/H-1 (T1, T5), D-3/H-2 (T5, T6, T10), D-4/H-12 (T1, T2, T6), D-11/H-3 (T3, T4), H-4 (T7), D-14 (T8), H-7 (T9), H-13 (T3 null-expiry test, T4 key-only test). D-1a lifecycle, D-5/6/6a/H-8, D-13 customer backfill → Plan 2. D-9/D-12/H-5/H-6/H-9/H-10/H-11/D-16 → Plan 3. D-7/D-17/D-15 → Plan 4.
- Not user-visible except Task 8 (login page loses the Supabase tab) — no feature flag needed; Task 8's precondition gates the merge.
