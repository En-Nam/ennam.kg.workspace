# Unified login — Plan 2: DAAB provisioning and account linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When Ennam Admin connects DAAB to a customer org, DAAB gets a matching customer org with the project and an owner linked to the LAAM owner; the DAAB org follows Admin's lifecycle; a customer org owner/admin can give DAAB access to LAAM members (linked by id); a LAAM disable disables the linked DAAB user; existing DAAB users/projects can be moved into customer orgs from the classification CSV.

**Architecture:** Go is the hub. Admin calls new admin-key Go endpoints (`/api/v1/admin/orgs/...`). Go talks to LAAM over a new server-to-server (S2S) channel in both directions with a shared service key (bearer, constant-time compare, two keys for rotation): Go → LAAM to look up the org owner and members; LAAM → Go to deprovision/re-enable a linked user. Admin never calls LAAM. Links are by LAAM user id (`users.laam_user_id`); e-mail is only copied, never matched.

**Tech Stack:** Go (net/http, database/sql, golang-migrate), Next.js 16 (LAAM, Admin, DAAB dashboard), Drizzle + Vitest (Admin, LAAM), PostgreSQL 15/16.

**Spec:** `docs/superpowers/specs/2026-11-17-unified-login-design.md` — this plan covers D-1a, D-5, D-6, D-6a, D-10, D-13, H-7 (apply), H-8, and the Plan-1 pointer "bind org-connection keys to their customer org". Plan 1 is done (`docs/superpowers/plans/2026-11-17-unified-login-p1-daab-org-foundation.md`).

**Design rulings in this plan (spec §9 left the S2S shape to the builder):**
- R1. Go, not Admin, asks LAAM for the owner (spec D-5 said "Admin asks LAAM"). Reason: Admin has no LAAM client and Go needs a LAAM channel anyway for member lists (D-6) — one new channel instead of two.
- R2. Directional S2S keys (a leak on one side does not let the other side be impersonated): Go accepts inbound keys `KG_S2S_INBOUND_KEYS` (comma list, rotation) and calls LAAM with `KG_LAAM_OUTBOUND_KEY` to `KG_LAAM_API_URL`; LAAM accepts `LAAM_S2S_INBOUND_KEYS` and calls Go with `DAAB_OUTBOUND_KEY` to `DAAB_API_URL`. Go's inbound keys = LAAM's outbound key and vice versa. Header `Authorization: Bearer <key>`. Spec H-5 is amended accordingly: the service credential is accepted only by routes under `/api/v1/s2s/` (Plan 3 mounts its SSO server-to-server routes there).
- R3. LAAM has no member removal, only disable; "removed" = disabled. A separate flag `users.laam_disabled` records LAAM's state, so it never overwrites who else disabled the user. LAAM disable → `laam_disabled=true`, and if the user is active → disabled with scope `laam`. LAAM enable → `laam_disabled=false`, and only a `laam`-scoped user is re-enabled (after a fresh LAAM check). A platform (Ennam staff) or org disable is never undone by LAAM; org admins cannot re-enable `laam`/`platform` users, nor an `org`-disabled user while `laam_disabled=true`. Go also reconciles every 15 min from LAAM's member list (eventual consistency if a push is lost).
- R4. A linked user created from a LAAM member has no DAAB password (SSO-only until Plan 3). An org admin may set one for members/viewers/admins (existing reset-password); owners cannot be reset by org admins (existing rule) — an owner gets a DAAB password only from Ennam staff or Plan 4's recovery.
- R5. Rollout safety (spec §7): Go `KG_ORG_LINKING_ENABLED` (default off) gates `/api/v1/org/laam-members` and `/api/v1/org/users/link` (404 when off); Admin `DAAB_ORG_PROVISIONING=1` (default off) gates provisioning/lifecycle calls (when off, Connect/attach/disconnect behave exactly as today). The dashboard shows the link button only when `GET /org/laam-members` succeeds.
- R6. D-1a "rejected → disabled" is unreachable (Connect requires an active org), so it has no task.

## Global Constraints

- Branch `task/portal_login` in every repo; commit only there; never check out other commits/branches or create worktrees; no merge/push (owner rule until all 4 plans are done). No `--no-verify`.
- Repos: `ennam.kg.go`, `ennam.kg.admin`, `LAAM`, `ennam.kg.next` (each its own git repo); workspace root for docs.
- Go migrations: next numbers `000106`, `000107` (current highest `000105`). Must run on PostgreSQL 15.
- Go internal org id `00000000-0000-0000-0000-0000000000a1`; org kinds `internal|customer`; Go org status `active|disabled`.
- `users.disabled_scope` values after this plan: `org | platform | laam`.
- Admin's DAAB developer name for org keys: `ennam-org-<orgId>` (existing). LAAM org id == Admin org id == Go `organizations.laam_org_id`.
- Error bodies use the existing Go `errorResponse` shape (`{"error":<status text>,"message":<text>}`); quote messages exactly as written below.
- Per-task tests (owner rule): run only the tests related to the task + build/typecheck; the full suites run once at the end of the plan. Go test DB: `KG_TEST_DATABASE_URL`/`KG_TEST_DSN` = `postgres://ennam_kg:<pw>@localhost:5433/ennam_kg_test?sslmode=disable`. Admin int tests: `TEST_DATABASE_URL` on :5500 `ennam_admin_test` (`npm run test:unit`, `npm run test:int`, `npm run typecheck`). LAAM int tests: `TEST_DATABASE_URL` on :5500 `laam_test` (`npm test`, `npm run test:int`, type-check with `npx tsc --noEmit` — LAAM has no `typecheck` script).
- S2S keys are compared as SHA-256 digests in constant time (equal length); S2S calls: 10 s timeout; never log keys; failures are logged with context and surfaced to the caller as a typed error (no silent fallback).

## Review Focus

1. A LAAM user id from a different LAAM org (or a disabled LAAM user) submitted to the DAAB link endpoint must be refused — the check is a fresh S2S lookup, not the request body (Task 4).
2. Provisioning twice for the same LAAM org (Admin retry, reconnect, second "new project") must not create a second DAAB org, a second owner, or move a project that already belongs to another customer org (Task 3).
3. A wrong or missing S2S key on any S2S route returns 401 and touches nothing; S2S routes are not reachable with a normal user session/API key (Tasks 2, 6).
4. An org-connection agent key (developer `ennam-org-<orgId>`) for a customer org must stop being treated as an internal caller once the org exists (Task 1).
5. Admin suspend/disconnect must take effect in DAAB even if the Go call fails transiently (Admin records `org_sync_pending` and a job retries — Task 8); a LAAM disable must reach DAAB even if the push fails (Go reconcile job — Task 4).
6. A rotated or reconnected org-connection key stays bound to the customer org (Task 1).

---

### Task 1: Go schema — LAAM user link, key org binding, `laam` disable scope

**Files:**
- Create: `ennam.kg.go/db/migrations/000106_laam_link_and_key_org.{up,down}.sql`
- Modify: `internal/models/user.go` (`LAAMUserID *string`, `DisabledScopeLAAM`), `internal/models/apikey.go` (`OrgID *string`), `internal/store/user.go` (columns/scans; `GetByLAAMUserID`, `SetLAAMUserID`), `internal/store/apikey.go` (column/scans; `SetOrgForDeveloper`), `internal/store/project.go` (`SetOrg`), `internal/middleware/auth.go` (key-only identity gets `OrgID`/`OrgKind` from `api_keys.org_id`), `internal/handler/authz_org.go` (`isInternalCtx`: a key-only identity whose key has a customer org is NOT internal)
- Test: `internal/store/laam_link_test.go`, `internal/handler/authz_org_keyorg_test.go`

**Interfaces:**
- Produces (DB): `users.laam_user_id text NULL UNIQUE`; `api_keys.org_id uuid NULL REFERENCES organizations(id)`; `users.disabled_scope` CHECK widened to `('org','platform','laam')`.
- Produces (Go):
  - `models.DisabledScopeLAAM = "laam"`
  - `func (s *UserStore) GetByLAAMUserID(ctx context.Context, laamUserID string) (*models.User, error)` — `(nil, nil)` when none
  - `func (s *UserStore) SetLAAMUserID(ctx context.Context, userID, laamUserID string) error` — unique violation → `store.ErrLAAMUserLinked`
  - `func (s *ProjectStore) SetOrg(ctx context.Context, projectID, orgID string) error`
  - `func (s *APIKeyStore) SetOrgForDeveloper(ctx context.Context, developerName, orgID string) (int64, error)` — sets `org_id` on non-revoked keys with that `developer_name`
  - `middleware.DeveloperIdentity` gains `OrgID, OrgKind string` (empty when the key has no org)
- Rule: org admins still may re-enable only `org`-scoped users (existing `EnableIfOrgDisabled`); `laam` behaves like `platform` for them.

**Amendments (plan review 2026-11-18 — these override the text above where they differ):**
- Bind at insert time: `APIKeyStore.Create` sets `api_keys.org_id` = the customer org whose `laam_org_id` = X when `developer_name` = `ennam-org-<X>` (keys minted later by Admin rotate/reconnect stay bound). Keep `SetOrgForDeveloper` for existing keys. Test `TestRotatedOrgKey_StaysBound` (create org, then create a new `ennam-org-<id>` key → org_id set, `isInternalCaller` false).
- Key-only `OrgID/OrgKind`: resolve with a join in `Authenticate` (or right after it); on lookup error fail closed (401).
- Add `users.laam_disabled boolean NOT NULL DEFAULT false` (R3) in 000106.
- Migration 103 added the CHECK inline: drop the auto-named `users_disabled_scope_check` and recreate it with `('org','platform','laam')`; down restores the 2-value check (and fails loudly if `laam` rows exist).
- Add new store methods behind NEW narrow interfaces; do not add them to the existing repository interfaces (mocks in `internal/handler/user_test.go:36`, `internal/service/user_test.go:32`, `internal/service/apikey_test.go:33` would break).

- [ ] **Step 1: Failing tests**: `TestUserStore_LAAMLink_UniqueAndLookup` (set, get, second user same laam id → `ErrLAAMUserLinked`), `TestProjectStore_SetOrg`, `TestAPIKeyStore_SetOrgForDeveloper_OnlyActiveKeys`, `TestMigration106_DisabledScopeAcceptsLAAM`, `TestIsInternal_KeyOnlyCustomerOrgKey_False` (key with org_id of a customer org → `isInternalCaller` false, `isGlobalAdmin` false), `TestIsInternal_KeyOnlyNoOrg_True` (unchanged for Admin's admin key / MCP keys without org).
- [ ] **Step 2: Run** `cd ennam.kg.go && go test ./internal/store/ ./internal/handler/ -run 'LAAMLink|SetOrg|Migration106|IsInternal_KeyOnly' -v` → FAIL.
- [ ] **Step 3: Implement**; migrate the test DB to 106 and prove `down 1`/`up`.
- [ ] **Step 4: Run** the same tests + `go build ./...` → PASS (no SKIP).
- [ ] **Step 5: Commit** `feat(org): laam user link, org-bound keys, laam disable scope`

---

### Task 2: Go S2S channel — inbound auth + LAAM client

**Files:**
- Create: `ennam.kg.go/internal/s2s/auth.go`, `internal/s2s/laamclient.go`, tests `internal/s2s/auth_test.go`, `internal/s2s/laamclient_test.go`
- Modify: `cmd/kg-server/main.go` (config + wiring), top-level mux (S2S routes on their own mux wrapped in `s2s.Auth`, see Amendments)

**Interfaces:**
- Env: `KG_LAAM_API_URL`, `KG_LAAM_OUTBOUND_KEY` (Go → LAAM), `KG_S2S_INBOUND_KEYS` (comma-separated, LAAM → Go; each ≥ 32 chars). Missing/short keys → S2S routes return 503 `{"message":"s2s not configured"}` and the LAAM client returns `s2s.ErrNotConfigured`; kg-server still starts.
- `func s2s.Auth(keys []string, next http.Handler) http.Handler` — `Authorization: Bearer <k>`, constant-time compare against every key; mismatch/missing → 401 `{"message":"invalid service credential"}`.
- `type LAAMClient struct` with `NewLAAMClient(baseURL string, key string, hc *http.Client) *LAAMClient` (10 s timeout) and:
  - `GetOrgOwner(ctx, laamOrgID string) (*LAAMMember, error)` → `GET {base}/api/s2s/orgs/{orgId}/owner`; 404 → `ErrNoOwner`
  - `ListOrgMembers(ctx, laamOrgID string) ([]LAAMMember, error)` → `GET {base}/api/s2s/orgs/{orgId}/members`
  - `GetOrgMember(ctx, laamOrgID, laamUserID string) (*LAAMMember, error)` → `GET {base}/api/s2s/orgs/{orgId}/members/{userId}`; 404 → `ErrMemberNotFound`
  - `type LAAMMember struct { ID, Email, Name, Role string; Disabled bool }` (JSON `id,email,name,role,disabled`)
**Amendments (plan review 2026-11-18 — these override the text above where they differ):**
- Directional keys (R2): inbound `KG_S2S_INBOUND_KEYS`, outbound `KG_LAAM_OUTBOUND_KEY` + `KG_LAAM_API_URL`. `s2s.Auth` compares SHA-256 digests in constant time.
- Do NOT add a prefix to the user-auth exempt list (`internal/middleware/auth.go:379-391` matches exact paths). Mount every `/api/v1/s2s/` route on its own mux wrapped in `s2s.Auth`, registered on the top-level mux ahead of the user-auth handler. Add a route-inventory test: every registered `/api/v1/s2s/` route answers 401 with no key and with a valid user web-session key.

- [ ] **Step 1: Failing tests** (httptest LAAM fake): `TestS2SAuth_RejectsMissingAndWrongKey`, `TestS2SAuth_AcceptsSecondKey` (rotation), `TestLAAMClient_SendsBearerAndParses`, `TestLAAMClient_404Mapping`, `TestLAAMClient_TimeoutIsError`, `TestS2SRoutes_NotReachableWithUserSessionKey` (a valid web-session key on `/api/v1/s2s/...` → 401).
- [ ] **Step 2–4**: run `go test ./internal/s2s/ ./internal/middleware/ -v` → FAIL → implement → PASS; `go build ./...`.
- [ ] **Step 5: Commit** `feat(s2s): service-key channel between DAAB and LAAM`

---

### Task 3: Go provisioning service + Admin-facing endpoints (D-5, D-1a, D-10)

**Files:**
- Create: `internal/service/org_provisioning.go`, `internal/handler/admin_orgs.go`, tests `internal/service/org_provisioning_test.go`, `internal/handler/admin_orgs_test.go`
- Modify: `cmd/kg-server/main.go` (wire), `internal/delegation/routes_other_test.go` (classify new routes)

**Interfaces:**
- Consumes: Task 1 stores, Task 2 `LAAMClient`, Plan 1 `OrganizationStore`, `OrgAccessService.SyncOrgProjects`, `UserService.DisableUser`, `APIKeyStore.RevokeWebSessionsForUser`.
- `type ProvisionRequest struct { LAAMOrgID, Name, ProjectID string }` → `ProvisionResult { OrgID string; OwnerStatus string /* linked|pending|conflict */; OwnerUserID *string }`
- `func (s *OrgProvisioningService) Provision(ctx, req ProvisionRequest) (*ProvisionResult, error)` — idempotent, in one DB transaction where possible:
  1. get-or-create the customer org by `laam_org_id` (name from request; existing org: status → `active`);
  2. project: if its org is the internal org → `SetOrg` to this org; if it already belongs to THIS org → no-op; if it belongs to ANOTHER customer org → `ErrProjectOwnedByOtherOrg` (409 `{"message":"project belongs to another customer"}`);
  3. `APIKeyStore.SetOrgForDeveloper("ennam-org-"+laamOrgID, orgID)`;
  4. owner: if a user with `org_role=owner` already exists in the org → `linked`; else `LAAMClient.GetOrgOwner` → `ErrNoOwner` → `pending`; owner e-mail already used by any DAAB user → `conflict` (no change); else create user (username = LAAM e-mail local part made unique with a numeric suffix, email, display name, `role=developer`, `org_role=owner`, no password, `laam_user_id`) → `linked`;
  5. `SyncOrgProjects(orgID)`.
- `func (s *OrgProvisioningService) SetStatus(ctx, laamOrgID string, active bool) error` — unknown org → `ErrOrgNotFound` (404); disabled → `OrganizationStore.SetStatus(disabled)` + revoke all web sessions of the org's users; active → `SetStatus(active)`.
- `func (s *OrgProvisioningService) RetryOwner(ctx, laamOrgID string) (*ProvisionResult, error)` — step 4 only.
- `func (s *OrgProvisioningService) ProjectOrg(ctx, projectID string) (orgKind, laamOrgID string, err error)`.
- Routes (all require `isGlobalAdmin` — Admin's `DAAB_ADMIN_KEY`; customer/org-bound keys → 403):
  - `POST /api/v1/admin/orgs/provision` body `{laam_org_id,name,project_id}` → 200 `ProvisionResult` JSON (`org_id, owner_status, owner_user_id`)
  - `POST /api/v1/admin/orgs/{laam_org_id}/status` body `{status:"active"|"disabled"}` → 204
  - `POST /api/v1/admin/orgs/{laam_org_id}/owner/retry` → 200 `ProvisionResult`
  - `GET /api/v1/admin/projects/{id}/org` → 200 `{org_kind, laam_org_id}` (`laam_org_id` null for internal)
**Amendments (plan review 2026-11-18 — these override the text above where they differ):**
- `/status` returns 200 `{}` (Admin's client always parses JSON).
- D-10 in Go: refuse (409 `{"message":"project belongs to another customer"}`) to move a project that appears in `project_ids` of any non-revoked key whose `developer_name` is `ennam-org-<Y>` with Y ≠ this laam_org_id, besides the existing other-customer-org check. Test it.
- Concurrency: take `pg_advisory_xact_lock(hashtext('org-provision:'||laam_org_id))` for the DB part; the LAAM S2S call happens outside any transaction (before it, then re-check inside); a unique violation from a racing request (org `laam_org_id`, `laam_user_id`) maps to the idempotent result. Test two concurrent `Provision` calls → one org, one owner.
- Step 4: `linked` only when an `org_role=owner` user in the org has `laam_user_id` set. An owner without a link → `conflict` with `owner_user_id` set (resolved by Task 4's staff link endpoint).
- Passwordless creation: new store method `CreateLinkedInOrg(ctx, *models.User)` (no password, status `active`, `laam_user_id` set); do not reuse `OrgUserService.Create` (it requires a password and sets `pending_password_change`). Generated usernames must also pass `DeveloperNameInUse` (usernames double as developer names). Global role via `globalRoleFor(orgRole)`.

- [ ] **Step 1: Failing tests** (LAAM fake via an interface):
  - `TestProvision_CreatesOrgMovesProjectLinksOwner`
  - `TestProvision_Idempotent` (call twice → one org, one owner, same result)
  - `TestProvision_SecondProjectJoinsSameOrg`
  - `TestProvision_ProjectOfOtherCustomer_409`
  - `TestProvision_NoLAAMOwner_Pending_ThenRetryLinks`
  - `TestProvision_OwnerEmailConflict_NoUserCreated`
  - `TestProvision_BindsOrgConnectionKeys` (key `ennam-org-<id>` gets org_id; then `isInternalCaller` false for it — through the handler)
  - `TestSetStatus_DisabledRevokesSessionsAndRefusesLogin`
  - `TestAdminOrgRoutes_CustomerOrOrgKey_403`
- [ ] **Step 2–4**: `go test ./internal/service/ ./internal/handler/ ./internal/delegation/ -run 'Provision|SetStatus|AdminOrgRoutes|EveryRegisteredRoute' -v` → FAIL → implement → PASS; `go build ./...`.
- [ ] **Step 5: Commit** `feat(org): provisioning, lifecycle and project-org endpoints for Ennam Admin`

---

### Task 4: Go linking (D-6, H-8) + LAAM deprovision S2S routes (D-6a, R3)

**Files:**
- Create: `internal/service/org_linking.go`, `internal/handler/org_link.go`, `internal/handler/s2s_laam.go`, tests `internal/service/org_linking_test.go`, `internal/handler/org_link_test.go`, `internal/handler/s2s_laam_test.go`
- Modify: `cmd/kg-server/main.go`, `internal/delegation/routes_other_test.go`

**Interfaces:**
- Org-admin routes (`orgAdminCaller`, same authority rules as `/api/v1/org/users`):
  - `GET /api/v1/org/laam-members` → `{"members":[{id,email,name,role,disabled,linked:bool}]}` — LAAM members of the caller org's `laam_org_id` (fresh S2S call), `linked` = a DAAB user with that `laam_user_id` exists in this org.
  - `POST /api/v1/org/users/link` body `{laam_user_id, org_role}` (`org_role` ∈ admin/member/viewer; only owner may pick admin) →
    fresh `GetOrgMember(org.laam_org_id, laam_user_id)`; not found → 404 `{"message":"member not found"}`; `Disabled` → 409 `{"message":"member is disabled in LAAM"}`; already linked anywhere → 409 `{"message":"member is already linked"}`; e-mail used by another DAAB user → 409 `{"message":"this e-mail can't be used"}`; else create user (as in Task 3 step 4, role from request) + `SyncUserProjects` → 201 user JSON. Never trusts e-mail/name from the request body.
- S2S routes (Task 2 `s2s.Auth`):
  - `POST /api/v1/s2s/laam/users/{laam_user_id}/disable` → linked user: if not disabled → disable with scope `laam` + revoke web sessions; if disabled with `org` scope → upgrade scope to `laam`; `platform` stays. Not linked → 204 (no-op).
  - `POST /api/v1/s2s/laam/users/{laam_user_id}/enable` → re-enable only when scope is `laam` (status back as in org enable); otherwise 204 no-op.
**Amendments (plan review 2026-11-18 — these override the text above where they differ):**
- Link: use `CreateLinkedInOrg` + `globalRoleFor(org_role)` + `DeveloperNameInUse` (as Task 3).
- Feature flag `KG_ORG_LINKING_ENABLED` (R5): when off, the two org routes return 404.
- R3 writes (new conditional store methods, never touching `platform`): `MarkLAAMDisabled(ctx, userID)` sets `laam_disabled=true` and, only if status is active, disables with scope `laam` (+ revoke web sessions); `MarkLAAMEnabled(ctx, userID)` sets `laam_disabled=false` and re-enables only if scope is `laam`. S2S enable first re-checks `GetOrgMember` (member exists in the org and not disabled); otherwise it only clears nothing and returns 204. Org enable of an `org`-disabled user with `laam_disabled=true` → 409 `{"message":"member is disabled in LAAM"}`. Pin with tests incl. the existing laam→platform upgrade by `UserService.DisableUser`.
- Reconcile job (every 15 min, lock key in the existing Go job framework or a ticker with a pg advisory lock): for each active customer org, `ListOrgMembers`; linked users whose member is missing or disabled → `MarkLAAMDisabled`; linked users with `laam_disabled=true` whose member is active → `MarkLAAMEnabled`. LAAM unreachable → log and skip that org. Test with the fake.
- Staff link-existing (resolves Task 3 `conflict` and migrated owners): `POST /api/v1/admin/users/{id}/link-laam` body `{laam_user_id}` — `isGlobalAdmin` only; the DAAB user must be in a customer org (internal → 409 `{"message":"internal users cannot be linked"}`); fresh `GetOrgMember(org.laam_org_id, laam_user_id)` (H-8); not already linked; sets `laam_user_id`; if the LAAM member is the owner, also sets `org_role=owner`. Tests for each refusal.

- [ ] **Step 1: Failing tests**:
  - `TestLink_MemberOfOtherLAAMOrg_404` (fake returns 404 for that org)
  - `TestLink_DisabledMember_409`, `TestLink_AlreadyLinked_409`, `TestLink_IgnoresBodyEmail` (body extra fields ignored; e-mail comes from LAAM)
  - `TestLink_AdminCannotGrantAdmin`, `TestLink_CreatesUserWithoutPasswordAndSyncsProjects`
  - `TestLAAMMembers_MarksLinked`
  - `TestS2SDisable_DisablesAndRevokes`, `TestS2SDisable_UpgradesOrgScope_KeepsPlatform`, `TestS2SEnable_OnlyLAAMScope`, `TestS2SRoutes_WrongKey_401`
  - `TestOrgEnable_LAAMScoped_409` (org admin cannot re-enable)
- [ ] **Step 2–4**: run those tests → FAIL → implement → PASS; `go build ./...`.
- [ ] **Step 5: Commit** `feat(org): link LAAM members by id; LAAM-driven disable/enable`

---

### Task 5: Go classification apply CLI (D-13, H-7 apply step)

**Files:**
- Create: `ennam.kg.go/cmd/kg-apply-classification/main.go`, `main_test.go`

**Interfaces:**
- `go run ./cmd/kg-apply-classification -dsn "$KG_DATABASE_URL" -csv users.csv [-apply]` — reads the CSV written by `cmd/kg-report-users` (header exactly as that tool writes; match columns by name). `classification` values: empty → skip; `staff` → no change; `customer:<laam_org_id>` or `customer:<laam_org_id>:<org_role>` (role admin|member|viewer, default member) → move the user into that customer org (org must already exist — else report `org not provisioned`), set `org_role`, set `role=developer` (viewer → viewer), clear `api_key_id`, revoke the user's web sessions, then `SyncUserProjects`. A user with global `role=admin` classified as customer is refused (`admin cannot be moved`) — the owner must demote first.
- Default is dry-run: print one line per row `id username → action` and a summary; `-apply` performs it in one transaction per user.
- Users whose CSV cells were sanitised by the report (leading `'`) are matched by `id` only (column 0).
**Amendments (plan review 2026-11-18 — these override the text above where they differ):**
- Allow `customer:<laam_org_id>:owner` (at most one owner per org; a second → reported and skipped).
- `SyncUserProjects` runs after the user's transaction commits; a re-run is idempotent — state it in the output.
- Dry-run also lists, per moved user's org, nothing more; project moves happen in Admin backfill (Task 9).

- [ ] **Step 1: Failing tests**: `TestApply_DryRunChangesNothing`, `TestApply_MovesCustomerUserAndSyncs`, `TestApply_MissingOrg_Reported`, `TestApply_AdminRefused`, `TestApply_StaffUnchanged`.
- [ ] **Step 2–4**: `go test ./cmd/kg-apply-classification/ -v` → FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(ops): apply user classification into customer orgs (dry-run default)`

---

### Task 6: LAAM S2S inbound routes (owner, members, member)

**Files:**
- Create: `LAAM/src/lib/s2s/auth.ts`, `LAAM/src/app/api/s2s/orgs/[orgId]/owner/route.ts`, `.../members/route.ts`, `.../members/[userId]/route.ts`, tests next to them (`*.test.ts` unit; `*.int.test.ts` with the DB)
- Modify: LAAM request proxy/middleware so `/api/s2s/*` skips the session gate (find the proxy that redirects unauthenticated requests), env docs

**Interfaces:**
- Env `LAAM_S2S_INBOUND_KEYS` (comma list; = Go's `KG_LAAM_OUTBOUND_KEY`), `DAAB_OUTBOUND_KEY` (= one of Go's `KG_S2S_INBOUND_KEYS`) and `DAAB_API_URL` (both used in Task 7).
- `function verifyServiceKey(req: Request): boolean` — constant-time (`crypto.timingSafeEqual`) against every key; missing config → routes 503 `{error:"s2s not configured"}`; bad key → 401 `{error:"invalid service credential"}`.
- `GET /api/s2s/orgs/:orgId/owner` → 200 `{id,email,name,role:"owner",disabled}` (first non-disabled `role='owner'` user of that org) or 404.
- `GET /api/s2s/orgs/:orgId/members` → 200 `{members:[{id,email,name,role,disabled}]}` (all users of that org, incl. disabled, never other orgs; internal orgs → 404).
- `GET /api/s2s/orgs/:orgId/members/:userId` → 200 member or 404 when the user is not in that org.
**Amendments (plan review 2026-11-18 — these override the text above where they differ):**
- Directional keys: inbound `LAAM_S2S_INBOUND_KEYS`; compare SHA-256 digests with `crypto.timingSafeEqual` (equal length; never call it on raw keys of different lengths).
- The session exemption lives in `LAAM/src/auth.config.ts:34-38` (not a proxy file): add the `/api/s2s/` prefix there.
- Add every new route to `LAAM/src/test/route-inventory.ts` with isolation cases (another org's member → 404).
- Internal orgs → 404 on all three endpoints (owner, members, member).
- Type-check with `npx tsc --noEmit`.

- [ ] **Step 1: Failing tests**: `verifyServiceKey` (missing/wrong/rotated key); int: owner lookup, members only of that org, member of another org → 404, internal org → 404, session cookie alone → 401.
- [ ] **Step 2–4**: `cd LAAM && npm test -- s2s` and `npm run test:int -- s2s` → FAIL → implement → PASS; `npm run typecheck`.
- [ ] **Step 5: Commit** in LAAM `feat(s2s): owner and member lookup for DAAB`

---

### Task 7: LAAM → Go deprovision on member disable / enable

**Files:**
- Create: `LAAM/src/lib/s2s/daab-client.ts`, test `daab-client.test.ts`
- Modify: `LAAM/src/app/api/users/[id]/route.ts` (PATCH disable ~L142-169, enable ~L174-182)

**Interfaces:**
- `async function notifyDaabUserDisabled(laamUserId: string): Promise<void>` → `POST {DAAB_API_URL}/api/v1/s2s/laam/users/{id}/disable`; `notifyDaabUserEnabled` → `/enable`. Bearer = `DAAB_OUTBOUND_KEY`; 10 s timeout.
- Called AFTER the LAAM transaction commits. Failure must not undo the LAAM change: log `error` with user id + status, and write a LAAM audit row `daab_sync_failed` (action name added wherever LAAM lists audit actions) so it is visible; no S2S config → log once at `warn` and skip.
**Amendments (plan review 2026-11-18 — these override the text above where they differ):**
- Outbound key `DAAB_OUTBOUND_KEY`, base `DAAB_API_URL`.
- A lost push is repaired by Go's reconcile job (Task 4); LAAM still logs + audits `daab_sync_failed`. No LAAM outbox in this plan.
- Type-check with `npx tsc --noEmit`.

- [ ] **Step 1: Failing tests**: client sends bearer + path; PATCH disable calls `notifyDaabUserDisabled` once after commit; DAAB 500 → LAAM still returns 200 and an audit `daab_sync_failed` row exists; enable calls the enable notifier.
- [ ] **Step 2–4**: run the targeted tests → FAIL → implement → PASS; `npm run typecheck`.
- [ ] **Step 5: Commit** in LAAM `feat(s2s): tell DAAB when a member is disabled or re-enabled`

---

### Task 8: Admin — provisioning on connect, D-10 refusal, lifecycle sync

**Files:**
- Modify: `ennam.kg.admin/src/lib/daab/client.ts` (+ `DaabClient` interface L37-62, `test/daab-fake.ts`), `src/lib/daab/service.ts` (`runConnect` L246, `attachDaabProject` L273, `disconnectDaab` L392), `src/lib/billing/orgs.ts` (`transition()` L298 for suspend/reactivate), `src/lib/audit.ts` (`AUDIT_ACTIONS`), `src/lib/daab/state.ts` (state gains `owner_status?: "linked"|"pending"|"conflict"`, `org_sync_pending?: "active"|"disabled"`)
- Create: `drizzle/0010_*.sql` only if a column is needed (prefer the existing `setup_state` jsonb — no migration), a job `daab-org-sync` next to `daab-key-revoke` (lockKey 6)
- Test: `src/lib/daab/provision.int.test.ts`, `lifecycle.int.test.ts`, extend `connect.int.test.ts`, `attach.int.test.ts`

**Interfaces:**
- Client methods: `provisionOrg({laamOrgId,name,projectId}) → {orgId, ownerStatus, ownerUserId|null}`; `setOrgStatus(laamOrgId, "active"|"disabled")`; `retryOwner(laamOrgId) → same as provision`; `projectOrg(projectId) → {orgKind, laamOrgId|null}`.
- `runConnect`: after the connection is saved (existing step 3), when the project came from step 1 (created or recovered for this org, i.e. `connectDaab` path) call `provisionOrg` and store `owner_status`; audit `org.daab_org_provisioned {org_id, owner_status}`. Provision failure → step `org` failure via existing `failed()` (audit `org.daab_step_failed`), connection stays; the card offers "Retry".
- `attachDaabProject`: before anything, `projectOrg(projectId)`; `orgKind==="customer" && laamOrgId!==org.id` → `{ok:false,error:"customer_owned"}` (new `DaabOpError`, message in `src/i18n/dictionaries/daab.ts`: "This project belongs to another customer."). Attach never provisions. If the org has a DAAB org (state has `owner_status`) and no own project remains after the attach → `setOrgStatus(disabled)`.
- `disconnectDaab` → `setOrgStatus(org.id,"disabled")`; reconnect (`connectDaab` on a disconnected org) → provisioning re-activates.
- `transition()` suspend → `setOrgStatus(disabled)`; reactivate → `setOrgStatus(active)`; only when the org has `owner_status` in its DAAB state; Go 404 → ignore.
- Failure of `setOrgStatus` never blocks the Admin action: store `org_sync_pending` in state and audit `org.daab_org_sync_failed`; job `daab-org-sync` (every 5 min) retries pending statuses and clears them on success.
**Amendments (plan review 2026-11-18 — these override the text above where they differ):**
- Feature flag `DAAB_ORG_PROVISIONING=1` (R5): when off, no Go provisioning/status calls and no `customer_owned` check.
- Do NOT add fields to the `daab` state (`saveDaabState` rebuilds it and zod strips unknown keys at `service.ts:336/420/296`). Store new data under a sibling key `setup_state.daab_org = { project_origin: "created"|"attached", owner_status?, org_sync_pending?: "active"|"disabled", provisioned_at? }` (the merge at `service.ts:94` keeps sibling keys). Set `project_origin` when the project is created (step 1) or attached, and keep it across disconnect.
- Provision whenever `runConnect` completes AND `daab_org.project_origin === "created"` (covers reconnect, which reuses the stored project; never provisions an attached project, also on attach resume).
- Suspend/reactivate: call Go AFTER the transaction commits inside `suspendOrg`/`reactivateOrg` (`orgs.ts`, like `rejectOrg` at ~:342; `transition()` is at ~:309). Reactivate sends `active` only when the DAAB step is `connected` and `project_origin === "created"`.
- The retry job uses lock key **7** (keys 1, 3, 4, 5, 6 are taken — 6 by `plans.ts:161`).
- Also run `npm run test:unit -- guard-inventory audit`.

- [ ] **Step 1: Failing tests**: connect (new project) provisions and stores owner_status; second connect after disconnect re-provisions same org; attach of a customer-owned project → `customer_owned`; attach of an internal shared project → no provision; disconnect/suspend/reactivate send the right status; Go failure → `org_sync_pending` + audit, job retries and clears.
- [ ] **Step 2–4**: `cd ennam.kg.admin && npm run test:int -- daab` → FAIL → implement → PASS; `npm run typecheck`; `npm run test:unit -- guard-inventory audit` (keeps the audit/guard inventory tests green).
- [ ] **Step 5: Commit** in Admin `feat(daab): provision DAAB org on connect; lifecycle sync; refuse customer-owned attach`

---

### Task 9: Admin — owner status on the DAAB card + backfill command (D-13)

**Files:**
- Modify: `ennam.kg.admin/src/app/(staff)/orgs/[id]/DaabCard.tsx`, `daab-actions.ts` (new `retryDaabOwnerAction`), `src/lib/daab/service.ts` (`retryDaabOwner(db, actor, {orgId, now})` under `withOrgLock`), `src/i18n/dictionaries/daab.ts`
- Create: `ennam.kg.admin/src/cli/daab-backfill.ts` (+ `package.json` script `daab:backfill`), test `src/cli/daab-backfill.int.test.ts`

**Interfaces:**
- Card shows owner status: linked → "Owner linked"; pending → "Owner not found in LAAM yet" + Retry; conflict → "Owner e-mail already used in DAAB — resolve manually" + Retry. Retry calls `retryOwner`, audits `org.daab_owner_retried`.
- `npm run daab:backfill [-- --apply]`: for every non-internal org whose DAAB state is `connected` and whose audit log has `org.daab_project_created` for the current `project_id` and no other org's connection uses that project → `provisionOrg`. Default dry-run prints `orgId name project → would provision` (+ shared/attached orgs as `skip (shared)`); `--apply` provisions and records owner_status like `runConnect`. Idempotent.
**Amendments (plan review 2026-11-18 — these override the text above where they differ):**
- The backfill is a tsx script in `ennam.kg.admin/scripts/` (not `src/cli/`), takes `tryDaabOrgLock` per org, and sets `daab_org.project_origin` from the audit log before provisioning.
- Dry-run also prints, per project to be moved, its DAAB data sources' hosts (from Go `GET /api/v1/data-sources?project_id=` with the admin key) and warns when a host is private/internal — after the move those sources become SSRF-guarded unless covered by `KG_DATASOURCE_ALLOW_CIDRS` (on Go and Python).
- The card's `conflict` text points staff to the DAAB internal admin action "Link to LAAM member" (Task 10).
- Run `npm run test:unit -- guard-inventory audit`.

- [ ] **Step 1: Failing tests**: retry action updates state + audit; backfill dry-run touches nothing; backfill apply provisions only created-and-unshared projects and is idempotent.
- [ ] **Step 2–4**: run the targeted int tests → FAIL → implement → PASS; `npm run typecheck`.
- [ ] **Step 5: Commit** in Admin `feat(daab): owner status, retry and provisioning backfill`

---

### Task 10: DAAB dashboard — "Give DAAB access to a LAAM member"

**Files:**
- Create: `ennam.kg.next/src/components/users/LinkLaamMemberDialog.tsx`, `src/hooks/use-laam-members.ts`
- Modify: `src/app/(dashboard)/admin/users/page.tsx` (button next to "New User" for customer owner/admin), `src/types/user.ts` (`laam_user_id?: string | null`), users table (badge "Linked to LAAM" when `laam_user_id` is set)

**Interfaces:**
- `useLaamMembers()` → `GET /api/kg/org/laam-members`; `useLinkLaamMember()` → `POST /api/kg/org/users/link {laam_user_id, org_role}`.
- Dialog lists members with `linked:false` and `disabled:false` (others shown greyed with the reason), picks one + org role (admin only for owner), shows Go's error message verbatim on 4xx, and the warning text from the spec D-8: "A DAAB account can see all stores of your company's data."
- The create dialog label for the existing flow becomes "Create a DAAB-only account".
**Amendments (plan review 2026-11-18 — these override the text above where they differ):**
- Internal admins: on the global Users page, a "Link to LAAM member" action for customer-org users without `laam_user_id` (calls Task 4's `POST /api/kg/admin/users/{id}/link-laam`; the member list comes from a global-admin variant `GET /api/v1/admin/orgs/{laam_org_id}/laam-members` — add it to Task 4's routes if not present, `isGlobalAdmin` only).
- The customer link button is shown only when `GET /api/kg/org/laam-members` succeeds (flag off → 404 → hidden).

- [ ] **Step 1**: implement; **Step 2**: `npm run build` + `npx eslint <changed files>` (no new problems); **Step 3** (if possible): browser check with seeded data and a stub LAAM S2S server or a real local LAAM; record what was verified; stop servers and delete seed data.
- [ ] **Step 4: Commit** in ennam.kg.next `feat(org): give DAAB access to a LAAM member`

---

### Task 11: Deploy checklist + env examples

**Files:**
- Modify: `docs/deploy/2026-11-17-unified-login-p1-checklist.md` (add a "Plan 2" section), env examples in each repo (`.env.example` / envfiles templates where they exist), `docker-compose.yml` (pass the new env to kg-server and LAAM if LAAM is in compose)

**Content (exact items):** generate two 48-char random keys (A: LAAM→Go, B: Go→LAAM); kg-server: `KG_S2S_INBOUND_KEYS=A`, `KG_LAAM_OUTBOUND_KEY=B`, `KG_LAAM_API_URL`; LAAM: `LAAM_S2S_INBOUND_KEYS=B`, `DAAB_OUTBOUND_KEY=A`, `DAAB_API_URL`; flags `KG_ORG_LINKING_ENABLED` and `DAAB_ORG_PROVISIONING` stay off until the owner turns them on; network: LAAM must reach kg-server and kg-server must reach LAAM `/api/s2s/*`; never expose `/api/s2s/*` publicly without the key; run order on deploy: migrate Go (000106) → deploy Go → deploy LAAM → deploy Admin → `kg-report-users` → owner classifies → `kg-apply-classification` (dry-run, then `-apply`) → `npm run daab:backfill` (dry-run, check the private-host warnings, then `--apply`) → resolve any `conflict` owners with "Link to LAAM member" → turn the flags on.
- [ ] Commit in each repo touched (workspace root for the checklist).

---

## Self-review notes

- Spec coverage: D-5 (T3, T8), D-1a (T3 SetStatus, T8), D-6/H-8 (T4, T10), D-6a/R3 (T1 scope, T4 S2S, T7), D-10 (T3 409, T8 customer_owned), D-13/H-7 (T5, T9 backfill), Plan-1 pointer key org binding (T1, T3 step 3), S2S credential (T2, T6, T11). SSO hand-off (D-9), sign-out (D-12), Home/nav (D-7/D-17), password recovery (D-15) → Plans 3–4.
- Execution order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 (Go first so LAAM/Admin integration tests can use a fake with the final contract).
