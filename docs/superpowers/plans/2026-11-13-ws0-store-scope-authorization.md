# WS0 Store-Scoped Access (LAAM → DAAB) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A LAAM user can only pull from DAAB the stores they may see (owner/admin all; member/viewer only assigned stores), on every LAAM path, enforced by DAAB.

**Architecture:** LAAM mints a short-lived HS256 delegation JWT per DAAB call (user, project, stores, via); DAAB verifies it in middleware, filters the metrics service by `location_id`, allow-lists what a store-limited ticket may call, and requires a ticket per project (`delegation_required`). LAAM's default-deny and scheduled-workflow lifecycle close the remaining gaps.

**Tech Stack:** Go 1.x stdlib + `github.com/golang-jwt/jwt/v5` (DAAB verify); Node `crypto` HMAC (LAAM sign, no new npm dependency); Postgres migration 000098; Next.js (LAAM).

**Spec:** `docs/superpowers/specs/2026-11-13-ws0-store-scope-authorization-design.md` (read §2, §3, §3.5 first — §3.5 overrides earlier bullets where they differ).

## Global Constraints
- Branch `task/pos-data-model` in every repo; verify `git branch --show-current` before each commit; stage explicit paths only.
- Do not edit: go `internal/service/source_executor.go`, `internal/service/nl_query.go`, `internal/models/ai_query.go`, `internal/bridge/billing.go`, `internal/bridge/mcpresponse.go`; LAAM `src/db/schema.ts`, `drizzle/*`, `contracts/admin-api.ts`, `src/lib/billing/*`, settings/billing pages, `package.json`/lockfile (no new LAAM dependency). `internal/bridge/serve.go`, `internal/bridge/client.go`, LAAM `src/app/api/chat/route.ts`, `src/app/api/workflows/generate/chat/route.ts` are shared with payment: small, localized edits only.
- Header name `X-KG-Delegation`; claims `iss="laam"`, `aud="daab"`, `sub`, `act{sub:"laam",via}`, `pid`, `loc` (array of location_id or the string `"*"`), `iat`, `exp` (≤ 300 s after iat), `jti`; JWS header `alg=HS256`, `kid`.
- Env: DAAB `KG_DELEGATION_KEYS`, LAAM `DAAB_DELEGATION_KEYS` — format `kid1:base64secret,kid2:base64secret`; LAAM signs with the FIRST entry; DAAB accepts any listed kid. Clock skew ≤ 60 s.
- `via` ∈ `chat|intel|workflow_manual|workflow_schedule|workflow_resume|preset_test|authoring|system`.
- D10: DAAB core stays industry-neutral (`location_id` is the generic dimension). LAAM connector-agnostic: the header name lives only in the DAAB connector/provider config, not in generic runtime strings.
- Never write to `ennam_kg`, `ennam_landed`, `pharmacy_demo`; Go tests use `KG_TEST_DATABASE_URL`/`KG_TEST_DSN`/`KG_TEST_LANDED_URL` from `.superpowers/sdd/2026-11-11-pos-data-model-tlog-landed/test.env`; DB tests fail (not skip) without env. Run Go and Python/LAAM DB suites sequentially.
- Commit messages conventional, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus
1. A present-but-invalid ticket (expired, wrong aud/kid/pid, tampered) must be 401 — never fall back to key-only access → Task W1.
2. A store-limited ticket that omits `dims_filter` or asks for another store must get only its stores (injected filter), and a metric without a `location_id` dimension must be denied → Task W3.
3. A store-limited ticket on any non-allow-listed route/tool (NL→SQL, docs, memory, graph, records, sessions, describe/insert, playbooks) is denied → Task W4.
4. A scheduled workflow whose owner lost all stores pauses with `data_access_lost` and never calls DAAB key-only → Task L3.
5. A LAAM member with no `user_scope` row gets no DAAB data on any path (chat tools, workflows, intel pages) → Tasks L1, L2.

---

### Task W1: Delegation ticket verification (DAAB)

**Files:** Create `ennam.kg.go/internal/delegation/{ticket.go,keys.go,middleware.go}` + `_test.go`; Modify `cmd/kg-server/main.go` (wire middleware after `Auth`, minimal insertion); `go.mod`/`go.sum` (`github.com/golang-jwt/jwt/v5`).

**Interfaces — Produces:**
- `type Ticket struct { UserID, ProjectID, Via, JTI string; AllStores bool; Locations []string; ExpiresAt time.Time }`
- `func ParseKeys(env string) (map[string][]byte, error)`
- `func Verify(token string, keys map[string][]byte, now time.Time) (*Ticket, error)` — checks alg=HS256 only, kid known, aud="daab", iss="laam", exp/iat with 60 s skew, exp−iat ≤ 300 s, non-empty sub/pid, loc is `"*"` or non-empty string array.
- `func Middleware(keys map[string][]byte, logger *slog.Logger) func(http.Handler) http.Handler` — header absent ⇒ pass; present ⇒ Verify; error ⇒ 401 `{"error":"invalid_delegation"}`; ok ⇒ also require `ticket.ProjectID` ∈ caller key's projects (or caller is global admin) else 403; store `*Ticket` in ctx.
- `func FromContext(ctx context.Context) *Ticket`

- [ ] Step 1: Tests `TestVerifyValid`, `TestVerifyExpired`, `TestVerifyWrongAud`, `TestVerifyUnknownKid`, `TestVerifyAlgNone`, `TestVerifyTampered`, `TestVerifyLifetimeOver300s`, `TestVerifyLocStar`, `TestMiddlewareInvalidIs401NoFallback`, `TestMiddlewareProjectNotInKey403`, `TestMiddlewareAbsentPasses` → FAIL.
- [ ] Step 2: Implement; keys from `KG_DELEGATION_KEYS` (unset ⇒ any ticket 401, absent header passes).
- [ ] Step 3: `go test -race ./internal/delegation/...` PASS; commit.

### Task W2: `delegation_required` flag + POS coupling (DAAB)

**Files:** Create `db/migrations/000098_delegation_required.{up,down}.sql`; Modify project store/model for the flag; `internal/landedapi` settings PUT; ingest upload handlers; new middleware enforcement in `internal/delegation/require.go`.

**Interfaces — Produces:** `projects.delegation_required boolean NOT NULL DEFAULT true`; migration backfill: `false` for existing projects, then `true` where `project_landed_settings.enabled`; `func (s *ProjectStore) DelegationRequired(ctx, projectID string) (bool, error)` (cached ≤ 60 s); `func RequireForData(...) func(http.Handler) http.Handler` — for API keys WITHOUT a user on routes classified as data reads (Task W4 table), project flag ON and no ticket ⇒ 403 `{"error":"delegation_required"}`. User-bound keys and global-admin keys are unaffected (spec §3.5 "Admin service keys").

- [ ] Step 1: Tests `TestNewProjectDefaultsRequired`, `TestMigrationBackfillExistingFalseLandedTrue`, `TestOrgKeyNoTicketOnRequiredProject403`, `TestOrgKeyNoTicketOnLegacyProjectPasses`, `TestUserSessionUnaffected`, `TestEnablingLandedForcesFlagOn`, `TestLandedUploadRefusedWhenFlagOff`, `TestOnlyGlobalAdminTurnsFlagOff`, `TestCannotTurnOffWhileLandedEnabled` → FAIL.
- [ ] Step 2: Implement (flag PUT on the existing project settings/admin route used by global admins; 409 when landed enabled).
- [ ] Step 3: Go tests for touched packages PASS; commit.

### Task W3: Store filtering in the metrics service (DAAB)

**Files:** Modify `internal/intel/engine/query.go` (`GetMetrics`, `GetEvidence`, `GetDataStatus`), `record.go` (record lookup), `internal/handler/intel_metrics.go` (pass ticket scope); tests in `internal/intel/engine/*_test.go`.

**Interfaces — Consumes:** `delegation.FromContext`. **Produces:** `type StoreScope struct { All bool; Locations []string }`; request structs gain `Scope *StoreScope` (nil ⇒ unrestricted, legacy).

- [ ] Step 1: Tests `TestScopedMetricsInjectsFilterWhenOmitted`, `TestScopedMetricsIntersectsRequestedStores` (ask PH-001,PH-002 with scope PH-001 ⇒ only PH-001), `TestScopedMetricsOtherStoreOnlyIsEmpty`, `TestScopedMetricWithoutLocationDimDenied` (403 `scope_denied`), `TestScopedEvidenceAndRecordRowsFiltered`, `TestScopedDataStatusHidesOtherStores`, `TestAllStoresTicketUnchangedResults`, `TestNilScopeLegacyUnchanged` → FAIL.
- [ ] Step 2: Implement intersection/injection before existing `checkFilterDims`.
- [ ] Step 3: `go test -race ./internal/intel/...` PASS; commit.

### Task W4: Allow-list for store-limited tickets (DAAB)

**Files:** Create `internal/delegation/routes.go`; Modify `cmd/kg-server/main.go` (wire with W2's middleware); tests.

**Interfaces — Produces:** `func ClassOf(r *http.Request, mux *http.ServeMux) RouteClass` with `RouteClass` ∈ `StoreData` (metrics, evidence, record, data status), `Catalogue` (health, list metrics, list projects/datasources metadata), `Other`; `func LimitStores(...) func(http.Handler) http.Handler` — ticket with `!AllStores` on `Other` ⇒ 403 `{"error":"scope_denied"}`; every denial (W1–W4) logs `sub`, `via`, project, route class and reason — never data values. Use the pattern of `middleware/scoped_routes.go` `allowedOn` (mux pattern matching), not URL string prefixes.

- [ ] Step 1: Table test `TestLimitedTicketRouteClasses` covering at least: ai-queries/NL→SQL, datasource describe/insert-row, playbooks, query/search/neighbors/traverse/graph retrieve, documents/chunks, memory recall/remember, derived/master records, sessions ⇒ 403; metrics/evidence/record/data-status/list-metrics ⇒ allowed; `loc="*"` ⇒ everything allowed as before → FAIL.
- [ ] Step 2: Implement; Step 3: PASS; commit.

### Task W5: MCP bridge forwards the ticket (DAAB)

**Files:** Modify `internal/bridge/serve.go` (`makeToolHandler`: read `req.Extra.Header.Get("X-KG-Delegation")` into ctx), `internal/bridge/client.go` (set header on outgoing request when ctx has it); tests in `internal/bridge/*_test.go`.

- [ ] Step 1: Tests `TestBridgeForwardsDelegationPerCall` (two calls in one session with different tickets reach kg-server with their own header), `TestBridgeNoDelegationNoHeader` → FAIL.
- [ ] Step 2: Implement (context key in a new small file, e.g. `internal/bridge/delegation_ctx.go`); Step 3: PASS; commit.

### Task W6: Fail-closed authz + GenerateKG IDOR (DAAB)

**Files:** Modify `internal/handler/authz.go:35-39`, `project_role.go` (`isUnauthenticated` callers), `intel_metrics.go:106-122`, `landedapi/landed_guards.go`, `internal/handler/kg_generation.go:133-172`.

- [ ] Step 1: Tests `TestRequireProjectAccessNoIdentityDenied` (and siblings), `TestGenerateKGDataSourceOtherProject404` → FAIL.
- [ ] Step 2: Implement (no identity ⇒ 401; data source must belong to body project ⇒ else 404). Update tests that relied on the pass-through to inject an identity.
- [ ] Step 3: `go test -race ./...` (full) PASS; `bash scripts/check-core-words.sh` ok; commit.

### Task L1: Delegation helper + access rules (LAAM)

**Files:** Create `LAAM/src/lib/connectors/mcp/delegation.ts` (+ test); Modify `src/lib/intel/access.ts` (D2 per spec §3.5), `src/lib/intel/admin/repo.ts` (admin not narrowable like owner).

**Interfaces — Produces:**
- `type Delegation = { sub: string; pid: string; loc: string[] | "*"; via: Via }`
- `async function delegationFor(userId: string, daabProjectId: string, via: Via): Promise<Delegation | null>` — resolves business projects by `daabProjectId` (union of the user's stores; zero ⇒ owner/admin `*`, others null); org role owner/admin ⇒ `*`; chain-wide persona with empty list ⇒ `*`, with stores ⇒ those; member/viewer without row ⇒ null.
- `function signDelegation(d: Delegation, now = Date.now()): string` — HS256 via Node `crypto.createHmac`, base64url, header `{alg:"HS256",typ:"JWT",kid}`, `exp = iat + 300`, random `jti`; keys from `DAAB_DELEGATION_KEYS` (first entry signs).
- `function systemDelegation(daabProjectId: string, ownerUserId: string): Delegation` (`via:"system"`, `loc:"*"`).

- [ ] Step 1: Tests: owner ⇒ `*`; admin with a PH-001 row ⇒ `*`; member PH-001 ⇒ `["PH-001"]`; member no row ⇒ null; chain-wide empty ⇒ `*`; chain-wide [PH-002] ⇒ `["PH-002"]`; two business projects same DAAB project ⇒ union; signed token verifies with a reference HS256 verifier (decode + recompute) and has exp−iat = 300 → FAIL.
- [ ] Step 2: Implement; Step 3: `npm test -- delegation access` PASS; commit.

### Task L2: Send the ticket on every DAAB path + default deny (LAAM)

**Files:** Modify `src/lib/connectors/mcp/client.ts` (per-call extra headers), `org-store.ts`, `src/lib/intel/provider/factory.ts` (acting user, not project owner; `system` for background analysis `src/lib/intel/run-project.ts`, templates, packs uninstall), `src/lib/intel/chat/hook.ts:92` + `src/app/api/chat/route.ts` (~737, minimal), workflow executors/run/resume/preset test-run/authoring (`src/lib/workflow/{executors,run,resume}.ts`, `src/lib/presets/test-run.ts`, `src/app/api/workflows/generate/*`, `src/app/api/custom-agents/generate/route.ts`).

**Interfaces — Consumes:** L1 `delegationFor`, `signDelegation`, `systemDelegation`.

- [ ] Step 1: Tests: chat turn for member PH-001 sends a ticket with `loc:["PH-001"]` on every DAAB tool call; member without row ⇒ DAAB tools removed and no DAAB call; manual workflow node sends `via:"workflow_manual"`; scheduled run sends `via:"workflow_schedule"` with `sub` = schedule owner and the owner's CURRENT stores; preset test and authoring send tickets; background analysis sends `via:"system"`, `loc:"*"`; non-DAAB MCP servers never receive the header → FAIL.
- [ ] Step 2: Implement (one `withDelegation(...)` path in the MCP client so call sites only pass the acting user + via).
- [ ] Step 3: LAAM tests PASS (`npm test`), `npx tsc --noEmit`, eslint on changed files; commit.

### Task L3: Scheduled workflow lifecycle + People note (LAAM)

**Files:** Modify `src/lib/workflow/schedule.ts` (tick), `owner-active.ts`, `src/lib/presets/lifecycle.ts`/`purge.ts` (new reason), notify path; `src/components/intel/admin/PeopleSection.tsx` (note).

- [ ] Step 1: Tests: owner with no stores at tick ⇒ schedule paused `pausedReason="data_access_lost"`, no DAAB call; stores re-assigned ⇒ next tick resumes; purge after 30 days like other reasons; owner notified once; People shows "No stores assigned — this person sees no store data" for members without stores → FAIL.
- [ ] Step 2: Implement; Step 3: PASS; commit.

### Task E1: End-to-end (controller, Chrome DevTools)
On the e2e stack (`.superpowers/sdd/2026-11-11-pos-data-model-tlog-landed/e2e-run.md`; set `KG_DELEGATION_KEYS`/`DAAB_DELEGATION_KEYS` in e2e env; LAAM dev against kg-server :18080): user logs in (ask the user). Create member A assigned PH-001: intel pages, chat question about all stores, a manual workflow and a scheduled workflow each return only PH-001; remove A's stores ⇒ schedule pauses `data_access_lost`; owner sees all; a raw call with the org key and no ticket on the enforced project ⇒ 403. Screenshots to the SDD folder.
