# Free Questions on T-log Data, Filtered by Customer and Store — Implementation Plan (rev 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Owners and store managers can ask DAAB natural-language questions on ingested POS T-log data, and the landed database itself returns only the caller's customer and stores — shipped default-OFF.

**Architecture:** DAAB mints a short-lived HMAC "DB ticket" per query and sets it with `SET LOCAL` in the same read-only transaction as the generated SQL; shared typed views in schema `pos` (one per canonical entity) read the ticket through `SECURITY DEFINER` helpers that verify it with pgcrypto and filter by project and store; a single login role `landed_ai` can read only those views and can change no setting or see other sessions. A system data source "Landed (system)" per enabled project exposes the views to the existing NL-query pipeline; WS0 lets store-limited tickets query only that source; LAAM offers the direct-query tool to restricted users for the org data-source connection only, when its flag is on.

**Tech Stack:** Go (ennam.kg.go: database/sql, lib/pq, golang-migrate), PostgreSQL 16 + pgcrypto, packs YAML (ennam.kg.packs), Next.js/TypeScript (LAAM, vitest).

**Spec:** `docs/superpowers/specs/2026-11-14-landed-free-questions-store-scope-design.md` (D-1…D-10). Code facts: `.superpowers/sdd/2026-11-13-ws0-store-scope-authorization/d12-facts.md`. Plan review (rev 1 → rev 2): `.superpowers/sdd/2026-11-13-ws0-store-scope-authorization/d12-plan-review.md` (C1, I1–I12, M1–M10 addressed below).

## Global Constraints

- Branch `task/pos-data-model` in every repo (ships Mon 2026-11-16). Payment-owned files may be edited.
- Flags: DAAB `LANDED_NL_QUERY` — on only when exactly `1`; LAAM `LANDED_FREE_QUESTIONS` — on only when exactly `1`. Flag off ⇒ every existing path behaves exactly as today, including `GET /api/v1/data-sources` and bridge instructions.
- New DAAB env: `LANDED_AI_URL` (DSN of `landed_ai`), `LANDED_CTX_KEYS` (`kid:base64secret[,…]`, secrets ≥ 32 bytes, first entry signs). Role script env: `LANDED_AI_PASSWORD`.
- DB ticket: body JSON `{"kid","pid","loc","exp","bp"}` (no canonicalisation needed — the MAC covers the exact bytes); wire = `base64url(body) + "." + hex(hmac_sha256(key, base64url(body)))`, charset `[A-Za-z0-9_.-]` (validate by regex before inlining in `SET LOCAL`); `pid` lower-case UUID = the data source's project; `loc` = `"*"` or non-empty array; `exp` = now + 60 s; `bp` = the executor's `pg_backend_pid()` read right after connecting. Never the LAAM/DAAB delegation key.
- DB objects (ennam_landed): schema `pos` (views), schema `pos_secret` (table `pos_secret.ctx_key(kid text PRIMARY KEY, k bytea NOT NULL)`, no USAGE for anyone but owner); helpers `pos.ctx_ok() boolean`, `pos.ctx_pid() uuid`, `pos.ctx_all() boolean`, `pos.ctx_stores() text[]` — all `SECURITY DEFINER`, `STABLE`, `SET search_path = pg_catalog, pg_temp`, every reference schema-qualified, owned by `landed_maintenance`, verifying from one internal `pos_secret.verify()`; NULL/false on: no setting, malformed, unknown kid, bad MAC, expired (`clock_timestamp()`), `bp <> pg_backend_pid()`.
- Role `landed_ai`: created NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT by migration with `default_transaction_read_only=on`, `statement_timeout='30s'`, `idle_in_transaction_session_timeout='60s'`, `work_mem='32MB'`, `TimeZone='UTC'`, `search_path=pos`, `CONNECTION LIMIT 20`; `GRANT CONNECT` on the database (no TEMP); LOGIN + password + `temp_file_limit='256MB'` set by idempotent `scripts/landed/ai-role.sql` (run by the runbook on existing clusters; included by `init.sql` for fresh ones).
- Side-channel revokes in ennam_landed (D-9): `REVOKE EXECUTE` FROM PUBLIC on `set_config(text,text,boolean)`, `pg_terminate_backend`, `pg_cancel_backend`, `pg_stat_get_activity`, every `pg_advisory_*`/`pg_try_advisory_*` overload; `REVOKE SELECT ON pg_stat_activity FROM PUBLIC`; grant each back to `landed_writer`, `landed_engine`, `landed_maintenance` where they use it (writer: set_config + advisory xact lock; maintenance: advisory lock; engine: set_config).
- View rules: `WITH (security_barrier = true)`; filter `r.entity='<e>' AND r.project_id = (SELECT pos.ctx_pid())`; entities with field `location_id`: `AND ((SELECT pos.ctx_all()) OR r.location_id = ANY ((SELECT pos.ctx_stores())))`; entities without it: visible only when `(SELECT pos.ctx_all())` unless the pack marks the entity `scope: shared` (D-8; initially `product`, `location`). Column types: text/integer/boolean/date as is; numeric via `CASE WHEN pg_input_is_valid(x,'numeric') THEN x::numeric END`; catalog `timestamp` → `timestamp` (without time zone); add `COMMENT ON VIEW` telling the planner to bound date filters with `business_date`.
- New code obtains landed connections only via `landed.For(projectID uuid.UUID) (Stores, error)` (D-6). The system source row stores no real DSN; executor and schema extractor resolve it through `landed.For(ds.ProjectID)` (M7).
- `scripts/check-core-words.sh` must pass. Conventional commits ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; stage explicit paths. Go DB tests use `.superpowers/sdd/2026-11-11-pos-data-model-tlog-landed/test.env` (unset `PHARMACY_DEMO_URL`); never run Go and Python/LAAM DB suites concurrently.

## Review Focus

1. **Status poll across users:** store-limited caller polling another caller's (or an owner's) query id ⇒ 404 — Task 5 `TestStoreLimitedCannotReadOthersQuery`.
2. **Shared caches:** value hints / plan cache never used for the system source — Task 4 `TestLandedSystemSourceSkipsValueHintsAndPlanCache`.
3. **Ticket drift / clock skew:** wrong key or expired ticket ⇒ error `ticket_rejected`, never an empty answer — Task 4 `TestRejectedTicketFailsLoud`.
4. **Hidden entities:** `labor_rate` invisible to `loc:["S1"]`, `product` visible — Task 1 `TestEntityWithoutStoreHiddenUnlessShared`.
5. **Flag off after enable:** store-limited refused even on the system source; LAAM hides the tool; owners unchanged — Task 5 `TestFlagOffRefusesStoreLimitedEvenOnLandedSource`, Task 6 `flag off keeps direct-query tools hidden`.

---

### Task 1: Landed DB layer — generated store column, ticket helpers, shared views, AI role, side-channel revokes

**Files:**
- Create: `ennam.kg.go/db/landed_migrations/000006_free_questions.up.sql` / `.down.sql` (down drops views, helpers, `pos`, `pos_secret`, column, index; leaves the cluster role like 000001.down)
- Create: `scripts/landed/ai-role.sql` (idempotent: `ALTER ROLE landed_ai LOGIN PASSWORD :'pw'`, `ALTER ROLE landed_ai SET temp_file_limit='256MB'`); Modify `scripts/landed/init.sql`, `init.sh`, `docker-compose.yml`, `.env.example`
- Create: `ennam.kg.go/internal/landed/aiviews.go` (`SyncAIViews`), `ennam.kg.go/internal/landed/ctxkeys.go` (`ParseCtxKeys`, `SyncCtxKeys`)
- Modify: `ennam.kg.packs/retail/daab/canonical.yaml` (`scope: shared` on `product`, `location`), `ennam.kg.go/internal/intel/types.go` (+ loader) `Entity.Shared bool`
- Test: `ennam.kg.go/internal/landed/aiviews_integration_test.go`, `ai_attack_integration_test.go`; extend `schema_integration_test.go` (`TestRolesHaveNoBypassRLS` to 4 roles; RLS invariant ignores schema `pos_secret` only if it uses FORCE RLS — choose: `pos_secret.ctx_key` ENABLE+FORCE RLS with `maintenance_all`)

**Interfaces — Produces:**
- Migration: `CREATE EXTENSION IF NOT EXISTS pgcrypto`; `landed_record.location_id` GENERATED ALWAYS AS (`data->>'location_id'`) STORED + index `(project_id, entity, location_id, business_date)`; schemas/helpers/role/revokes per Global Constraints.
- `type CtxKey struct{ Kid string; Secret []byte }`; `landed.ParseCtxKeys(s string) ([]CtxKey, error)`; `landed.SyncCtxKeys(ctx, maint *sql.DB, keys []CtxKey) error` — insert/update only, never deletes (M5).
- `landed.SyncAIViews(ctx, maint *sql.DB, entities []intel.Entity) (changed bool, err error)` — under `pg_advisory_xact_lock`, `SET LOCAL lock_timeout='5s'`, applies DDL only when `pg_get_viewdef` differs, drops `pos` views not in the list, re-grants SELECT to `landed_ai`.

- [ ] **Step 1: Failing integration tests** (`KG_TEST_LANDED_URL`; fixture 2 projects × 3 stores; entities `sale` (location_id), `product` (shared), `labor_rate` (no store, not shared); helper mints tickets in Go):
  - `TestAIViewsTypedColumns` — columns/types match catalog; a timestamp column is `timestamp without time zone`; `extract(hour from sold_at)` equals the raw wall-clock hour.
  - `TestTicketFiltersProjectAndStores` — `loc:["S1"]` ⇒ P1/S1 only; `"*"` ⇒ all P1; never P2.
  - `TestEntityWithoutStoreHiddenUnlessShared` — under `loc:["S1"]`: `pos.product` = all P1 products, `pos.labor_rate` = 0 rows; under `"*"`: both visible (P1 only).
  - `TestTicketRejected` (table): tampered, wrong key, unknown kid, expired, wrong `bp`, empty, malformed ⇒ `pos.ctx_ok()` false and 0 rows.
  - `TestAIRoleCannotForgeOrEscape` (as `landed_ai`): `SELECT set_config('landed.ctx', …, true)` and `SELECT set_config('work_mem','4GB',true)` ⇒ permission denied, and `current_setting('work_mem')` stays `32MB` (model SQL only ever runs as one prepared SELECT/WITH statement, so a `SET` command cannot be issued; `set_config` is the only route and it is revoked); `SELECT` on `landed_record`, a partition, `landed_record_history`, `pos_secret.ctx_key` ⇒ denied; `CREATE TABLE pos.x` / `CREATE TEMP TABLE` ⇒ denied; `SET default_transaction_read_only=off; BEGIN READ WRITE; INSERT INTO pos.sale …` ⇒ permission denied (not read-only error); `COPY (SELECT 1) TO PROGRAM 'true'` ⇒ denied.
  - `TestNoCrossSessionSideChannels` — two `landed_ai` sessions A, B: B cannot see A's `query` in `pg_stat_activity`, `pg_terminate_backend(A)` / `pg_cancel_backend(A)` denied, `pg_advisory_lock(1)` denied.
  - `TestNoLeakThroughCastErrors` — P2 row `amount='abc'` never errors a P1 query; own-project `amount=''` yields NULL, not an error.
  - `TestDangerousExtensionsAbsent` — no dblink/postgres_fdw/file_fdw/adminpack; `landed_ai` not in `pg_read_server_files`/`pg_write_server_files`/`pg_execute_server_program`; no TEMP on the DB.
  - `TestCtxHelpersOwnedByMaintenance` — `pg_proc.proowner` = `landed_maintenance`, `prosecdef`, `proconfig` contains `search_path=pg_catalog, pg_temp`.
  - `TestContextEvaluatedOncePerStatement` — EXPLAIN has `InitPlan` and no `Filter:` line containing `ctx_`.
  - `TestExistingRolesStillWork` — writer path (set_config + advisory xact lock) and maintenance partition creation still succeed after the revokes.
  - `TestAIViewsPerformance` (runs when `LANDED_PERF=1`; Task 7 runs it): 150k sale_line rows/month for one of 20 projects; monthly aggregate bounded by `business_date` < 500 ms; same bounded only by `sold_at` — record the time (no assertion).
- [ ] **Step 2:** `go test ./internal/landed/ -count=1 -run 'AIViews|Ticket|Entity|AIRole|SideChannel|NoLeak|Dangerous|CtxHelpers|ContextEvaluated|ExistingRoles'` → FAIL.
- [ ] **Step 3:** implement migration, `ai-role.sql`, Go sync funcs, pack flag + loader field.
- [ ] **Step 4:** PASS; landed-migrate down/up clean on the test DB; existing `internal/landed` suite green; `check-core-words.sh` passes.
- [ ] **Step 5:** commit `feat(landed): ticket-checked shared views and AI role for free questions` (go + packs commits).

### Task 2: Tickets, `landed.For`, wiring, reconcile of views and keys

**Files:** Create `ennam.kg.go/internal/landed/ctxticket.go`, `ennam.kg.go/internal/landed/stores.go`; Modify `ennam.kg.go/cmd/kg-server/landed_wiring.go` (sync at `buildLanded`, where the maintenance DB exists), the pack-reload path (`internal/handler/intel_packs_admin.go` `ReloadUnderLock` → callback); Test `ctxticket_test.go`, `stores_test.go`, `reload_views_integration_test.go`.
**Interfaces — Produces:**
- `landed.MintCtx(keys []CtxKey, pid uuid.UUID, loc []string /* nil = "*" */, backendPID int, now time.Time) (string, error)` — refuses empty non-nil `loc`.
- `type Stores struct{ AIDSN string; CtxKeys []CtxKey }`; `landed.For(projectID uuid.UUID) (Stores, error)` (env-backed shared store); `landed.FreeQuestionsEnabled() bool`.
- `type ViewsChanged func(ctx context.Context)` — callback invoked when `SyncAIViews` reports a change (Task 3 uses it to re-extract system source schemas).
- [ ] Step 1: tests `TestMintCtxVerifiedByHelpers` (integration, incl. `bp` match), `TestMintCtxRefusesEmptyStores`, `TestMintCtxLowercasesPid`, `TestForReturnsSharedStore`, `TestFreeQuestionsEnabledExactValue`, `TestPackReloadResyncsViews` → FAIL.
- [ ] Step 2: implement; PASS; `go build ./... && go vet ./...`.
- [ ] Step 3: commit `feat(landed): DB context tickets, store lookup and view sync wiring`.

### Task 3: System data source "Landed (system)"

**Files:** Create `ennam.kg.go/db/migrations/000099_data_source_kind.up.sql`/`.down.sql`; Modify `internal/models/datasource.go`, `internal/store/datasource.go`, `internal/handler/datasource.go` (Update/Delete/List/Get output), `internal/service/datasource.go`, schema extractor (resolve DSN for the system kind via `landed.For`), `internal/landedapi/handler.go` (enable/disable/purge hooks), `cmd/kg-server/landed_wiring.go` (deps: dsStore, encKey, extractor; startup reconcile); Test `internal/landedapi/system_source_integration_test.go`, `internal/handler/datasource_system_test.go`.
**Interfaces — Produces:** `data_sources.kind text NOT NULL DEFAULT 'user' CHECK (kind IN ('user','landed_system'))`; `models.DataSource.Kind`; `models.DataSourceKindLandedSystem = "landed_system"`; `ensureSystemSource(ctx, projectID) (dsID uuid.UUID, err error)` (flag on): one per project, name `Landed (system)`, `db_type='postgresql'`, `allow_writes=false`, host/port/database stored as `landed (system)` placeholders, no real DSN stored; then `StartExtractSchema`. Disable/purge soft-delete it. Startup reconcile (flag on): every landed-enabled project has its system source; re-extract schemas when the `ViewsChanged` callback fires. PATCH/DELETE on it ⇒ 409 `{"error":"system_data_source"}`.
- [ ] Step 1: tests `TestSystemSourceCreatedOnEnableAndSchemaExtracted` (lists `pos` views + columns), `TestSystemSourceNotCreatedWhenFlagOff`, `TestStartupReconcileCreatesMissingSystemSources`, `TestSystemSourceRemovedOnDisableAndPurge`, `TestSystemSourceNotEditable`, `TestSystemSourceHidesHostAndForbidsWrites` → FAIL.
- [ ] Step 2: implement; PASS.
- [ ] Step 3: commit `feat(datasource): landed system source per enabled project`.

### Task 4: Execute under the caller's scope

**Files:** Migration `000100_ai_query_scope` (`ai_queries.requester_scope jsonb NULL`); Modify `internal/handler/ai_query.go` (SubmitQuery stores scope), `internal/service/nl_query.go` (ProcessQuery loads scope from the row into ctx), `internal/service/source_executor.go`, `internal/service/value_hints.go`, plan-cache lookup, `internal/livesource/live.go`, source-write and playbook entry points, `internal/handler/sse_stream.go` (`X-DB-DSN`), `cmd/kg-server/main.go`; Test `internal/service/source_executor_landed_test.go`, `nl_query_landed_test.go`.
**Interfaces — Produces:**
- `type QueryScope struct{ ProjectID uuid.UUID; Stores []string /* nil = all */; Sub, Via string }`; `service.WithQueryScope(ctx, QueryScope) context.Context`; `service.QueryScopeFrom(ctx) (QueryScope, bool)`.
- `SubmitQuery`: scope from `delegation.FromContext` (store-limited ⇒ ticket stores; `*` or no ticket ⇒ nil; `Sub` = ticket sub or the authenticated user/key id) → `requester_scope`.
- Executor for `Kind == landed_system`: requires a scope in ctx (else error `landed_system requires a caller scope`); asserts `scope.ProjectID == ds.ProjectID`; connects via `landed.For(ds.ProjectID).AIDSN`; reads `pg_backend_pid()`; `SET LOCAL statement_timeout = '30000'`; `SET LOCAL landed.ctx = '<ticket>'` (regex-validated); `SELECT pos.ctx_ok()` must be true else error `ticket_rejected` (log kid + skew, never the ticket); then the statement. Kind `user`: unchanged.
- Value hints and plan cache skipped for `landed_system`; livesource bindings, source writes, playbooks and the SSE DSN path refuse a `landed_system` source with a clear error.
- Audit: INFO `free question executed` (sub, via, project_id, stores, data_source_id, query_id, row_count; never SQL text or values).
- [ ] Step 1: tests `TestLandedSourceQueryOnlySeesCallerStores` (two scopes, same source, different rows), `TestLandedSourceWithoutScopeReturnsError`, `TestRejectedTicketFailsLoud`, `TestScopeSurvivesRetryAndRankingPaths`, `TestUserSourceUnchanged`, `TestLandedSystemSourceSkipsValueHintsAndPlanCache`, `TestOtherPathsRefuseSystemSource`, `TestFreeQuestionAuditLine` → FAIL.
- [ ] Step 2: implement; PASS; `go test ./internal/service/... ./internal/handler/... ./internal/livesource/...`.
- [ ] Step 3: commit `feat(nlquery): run landed questions under the caller's store scope`.

### Task 5: WS0 — store-limited tickets on the system source only

**Files:** Modify `internal/delegation/routes.go`, the `LimitStores` file, `internal/handler/ai_query.go`; Test `internal/delegation/routes_test.go`, `internal/handler/ai_query_scope_test.go`.
**Interfaces — Produces:** `RouteClass` `ScopedQuery` for `POST /api/v1/ai-queries` and `GET /api/v1/ai-queries/{id}`; `LimitStores` passes it for store-limited tickets only when `landed.FreeQuestionsEnabled()` (else 403 as today). `SubmitQuery` with a store-limited ticket on a non-system source ⇒ 403 `{"error":"scope_denied","use_data_source_id":"<system id>"}` (field omitted when none). `GetQuery` for a delegated request ⇒ 404 unless `requester_scope.sub == ticket.sub` and the stores are equal as sorted sets; `requester_scope IS NULL` ⇒ 404 for delegated callers. No change to `GET /data-sources` or bridge instructions.
- [ ] Step 1: tests `TestStoreLimitedCanQueryLandedSource`, `TestStoreLimitedRefusedOnUserSourceWithHint`, `TestFlagOffRefusesStoreLimitedEvenOnLandedSource`, `TestStoreLimitedCannotReadOthersQuery` (other sub; same sub other stores; legacy NULL scope), `TestUnscopedCallersUnchanged`, `TestDataSourcesListUnchanged`, update `TestEveryRegisteredRouteIsClassified` → FAIL.
- [ ] Step 2: implement; PASS; `go test ./internal/delegation/... ./internal/handler/...`.
- [ ] Step 3: commit `feat(ws0): store managers query the landed source only`.

### Task 6: LAAM — direct-query tool for restricted users on the org data-source connection (flag)

**Files:** Modify `LAAM/src/lib/intel/chat/guard.ts`, `hook.ts`, `note.ts`, `LAAM/.env.example`; Test `guard.test.ts`, `note.test.ts`, `hook.test.ts`.
**Interfaces — Produces:** `freeQuestionsEnabled(): boolean` (`process.env.LANDED_FREE_QUESTIONS === "1"`). When on and restricted: only `mcp__<slug>__<tool>` where `<slug>` is an org server with `delegation` config (the list `deniedDataSources` walks, minus denied ones) and `<tool>` ∈ `directQueryTools()` is allowed; every other `mcp__*` (incl. personal servers' `kg_query_datasource`) stays blocked. Restricted note when on: "Direct source queries are limited to this user's stores; the data source refuses other data. External connector tools are not available for this user." Off: unchanged.
- [ ] Step 1: tests `flag on: restricted user keeps org direct-query tools only`, `flag on: personal server direct-query tool stays blocked`, `flag off keeps direct-query tools hidden`, `note text per flag`, `unrestricted users unchanged` → FAIL.
- [ ] Step 2: implement; `npx tsc --noEmit` + touched vitest PASS.
- [ ] Step 3: commit `feat(intel): free questions for restricted users behind a flag`.

### Task 7: Deploy safety, end-to-end, runbook (controller)

- [ ] Dry-run landed migration 000006 and main 000099/000100 on a copy with the production runner identity (record whether `CREATE EXTENSION pgcrypto`, `ALTER ROLE … SET`, revokes succeed); production `landed_record` row count for the generated-column rewrite time.
- [ ] e2e: rebuild kg-server; migrate e2e DBs; run `ai-role.sql`; set `LANDED_AI_URL`, `LANDED_CTX_KEYS`, `LANDED_NL_QUERY=1`; LAAM `LANDED_FREE_QUESTIONS=1`, `INTEL_DIRECT_QUERY_TOOLS=kg_query_datasource,kg_query_datasource_status`; restart (startup reconcile creates the system source and extracts its schema).
- [ ] Run `TestAIViewsPerformance` with `LANDED_PERF=1`; record numbers.
- [ ] Browser: member.demo (PH-001) asks 5 free questions (top products for an employee 14–16h; transactions with > 3 price overrides; refunds without receipt by hour; wages question ⇒ refused/empty; another store ⇒ refused) — only PH-001 in answers; owner sees all stores; DAAB log `free question executed` with the right stores.
- [ ] Flags off ⇒ member loses the tool and gets 403 on the source; owner unchanged.
- [ ] Runbook: `ennam.kg.go/docs/ws0-delegation-runbook.md` + `LAAM/docs/DEPLOYMENT.md`: env vars, `ai-role.sql` on existing clusters, migration order (landed 000006 before kg-server), flags stay off until security review.
