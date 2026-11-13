# WS0 — Store-scoped access from LAAM to DAAB (design)

Date: 2026-11-13 · Status: draft for review · Branch: `task/pos-data-model` (all repos)
Related: `2026-11-11-tlog-landed-ingestion-design.md` (WS0 gate, §"Gate"), `2026-09-25-industry-pack-proactive-intelligence-design.md` §7.11 (LAAM `user_scope`, "DAAB still trusts LAAM"), Serena `decisions/pos-tlog-landed-store`.

## 1. Intent (why)

Real customer t-logs may not land in DAAB until a LAAM user can only pull data for the stores they are allowed to see.
Today LAAM already narrows by store (`user_scope.locationIds`), but DAAB only sees **one shared org key**: whoever holds that key
reads every store, and several LAAM paths (scheduled workflows, authoring, preset test runs, users without a scope row) bypass
LAAM's own filter. WS0 makes the guarantee hold at the data owner (DAAB) and closes the LAAM gaps — simply, without
infrastructure we don't need yet, and in a way that can be upgraded later without rewriting the enforcement.

Success = for a LAAM `member`/`viewer` assigned PH-001, every path (chat, intel pages, manual/scheduled workflow, preset test,
authoring) returns only PH-001 data from DAAB; a stolen org key alone cannot read store data of an enforced project; scheduled
runs follow the owner's *current* stores and pause when access is lost.

## 2. Decisions (user, 2026-11-13)

- D1 **Scope = which stores a LAAM user may pull from DAAB.** Nothing else is in scope for store-level access.
- D2 **Roles:** LAAM `owner` and `admin` ⇒ all stores. `member`/`viewer` ⇒ only stores assigned in Intel Admin → People
  (`user_scope.locationIds`); **no assignment ⇒ sees nothing**; a chain-wide persona (pack `roles.yaml` `chain_wide`) ⇒ all stores.
- D3 **Who receives results is the user's responsibility.** No recipient/egress gate, no destination registry. The rule that keeps
  this safe: *a run can never read more than the person it runs as may see*.
- D4 **Rollout = per project (option c):** a project flag "delegation required". ON by default for new projects and for every
  project with POS (landed) data enabled; existing demo projects keep current behaviour until switched on.
- D5 Ennam Admin is not touched (it only holds a billing branch count and issues the per-org key).
- D6 Keep it simple: no OAuth server, no policy engine (OPA/OpenFGA), no per-user DAAB keys now. Use a compact, standard-shaped
  delegation token (RFC 8693 shape) so we can later swap the issuer/keys without changing DAAB enforcement.

## 3. Design

### 3.1 Delegation ticket (LAAM → DAAB)
- A JWT signed by LAAM, sent on every DAAB call in header **`X-KG-Delegation`**, next to the unchanged org key (`Authorization: Bearer`).
- Claims: `iss` = "laam"; `aud` = "daab"; `sub` = LAAM user id; `act` = {"sub": "laam", "via": "chat|intel|workflow_manual|workflow_schedule|preset_test|authoring"};
  `pid` = DAAB project id; `loc` = list of DAAB `location_id` values **or** `"*"` (all stores); `iat`, `exp` (≤ 5 minutes), `jti`.
- Signing: HS256 with a shared secret per environment, `kid` header for rotation (two keys accepted during rotation).
  Env: LAAM `DAAB_DELEGATION_KEYS` / DAAB `KG_DELEGATION_KEYS` (kid → secret). Upgrade path (out of scope): asymmetric keys
  (DAAB only verifies), then IdP-issued tokens.
- LAAM mints the ticket **at call time** from the user's current role + `user_scope` (never stored).

### 3.2 DAAB enforcement
- Middleware (after `Auth`): if `X-KG-Delegation` present ⇒ verify signature, `kid`, `aud`, `exp` (small clock skew), and that
  `pid` is the project the org key may access; attach `Delegation{UserID, Via, Locations|All}` to the request context. Invalid
  ticket ⇒ 401 (never fall back to key-only).
- Project flag `delegation_required` (main DB, project setting; default per D4). When ON, **every data read** by a key without a
  user (org/agent keys) requires a valid ticket; missing ⇒ 403 `delegation_required`. Non-data calls (health, list metrics
  catalogue, list projects/datasources metadata) stay allowed. Human dashboard sessions (user-bound keys) and global admins are
  unaffected.
- Store filtering in the **metrics service layer** (`engine.QueryService` GetMetrics / GetEvidence / GetRecord / data status):
  intersect the caller's `dims_filter.location_id` with the ticket's locations; inject it when omitted; metrics without a
  `location_id` dimension ⇒ denied for a store-limited ticket; record/evidence re-check per row (existing `query.go`/`record.go`
  rules make an injected filter unwidenable).
- Tools that cannot be filtered by store are **denied** for a store-limited ticket: NL→SQL (`kg_query_datasource` /
  `POST /ai-queries`), datasource describe / insert-row / playbooks, graph search over raw rows. (Allowed for `loc="*"`.)
- MCP bridge: forward `X-KG-Delegation` from the incoming MCP HTTP request to kg-server (additive change in
  `internal/bridge/middleware_auth.go` + `client.go`; payment touched only `billing.go`, `mcpresponse.go`, `serve.go`).
- Audit: log delegation `sub`, `via`, project, decision on denied calls (no data values).

### 3.3 DAAB hygiene (same WS0)
- `requireProjectAccess` and sibling checks: **fail closed** when no identity is on the context (`authz.go:36-39`,
  `project_role.go` `isUnauthenticated`, `intel_metrics.go:113`, `landed_guards.go`). Not reachable over HTTP today, but the
  default must be deny.
- GenerateKG IDOR (`kg_generation.go:133-172`): verify the path data source belongs to the body project before starting the job
  (same pattern as `ai_query.go:122-129`); 404 on mismatch.

### 3.4 LAAM
- One helper `delegationFor(user, businessProject, via)` ⇒ `{loc, sub}` from D2 rules (owner/admin ⇒ `*`; chain-wide persona ⇒ `*`;
  member/viewer ⇒ assigned stores; none ⇒ **no ticket and no DAAB data**).
- Every DAAB call path mints and sends a ticket: intel provider (today it calls as project owner — must use the *acting* user),
  chat MCP tools, manual workflow runs, **scheduled runs as the schedule owner** (`workflow_schedule.userId`), resume, preset
  test runs, workflow/custom-agent authoring (generate/generateChat), media/evidence routes.
- **Default deny:** a member/viewer without a `user_scope` row is treated as "no stores" (fix `intel/chat/hook.ts:92` +
  `chat/route.ts:737` pattern) on all paths, not only intel chat.
- **Scheduled workflows:** scope is recomputed at every run (not frozen at scheduling); if the owner is disabled/removed or has no
  stores ⇒ the schedule pauses with a new `pausedReason = data_access_lost` (existing lifecycle mechanism); never fall back to the
  org key. Org (shared) workflows run with the scheduling member's own scope.
- MCP transport: the ticket is per acting user and per call; the LAAM MCP client must attach the header per request (or per
  short-lived session keyed by acting user). Keep connector-agnostic: DAAB-specific header name lives only in the DAAB provider /
  connector config, not in runtime strings elsewhere (rule `laam-must-stay-connector-agnostic`).
- UI: Intel Admin → People already assigns stores; add a clear line for members without stores ("No stores assigned — this person
  sees no store data"). No new tables.

### 3.5 Resolved after builder check (controller's calls unless marked)
- **One source of truth for a user's stores:** the ticket is computed by the same LAAM access function that LAAM's own pages use
  (`src/lib/intel/access.ts`), extended per D2: `owner` and `admin` ⇒ all stores and cannot be narrowed (today only owner);
  owner/admin without a `user_scope` row ⇒ all stores (today "no row = no access"); chain-wide persona **with an empty store list**
  ⇒ all stores, **with listed stores** ⇒ those stores (keeps current code, `access.ts:50-56`); member/viewer without a row ⇒ nothing.
- **LAAM default-deny is unconditional** (all projects, flag or not): LAAM's policy must not depend on a DAAB flag. Demo projects
  keep working for owner/admin; members need stores assigned (one-line note in People).
- **DAAB project ↔ business projects:** a DAAB call is resolved to the business projects whose `daabProjectId` matches; zero ⇒
  owner/admin all stores, others nothing; several ⇒ union of the user's stores across them (same underlying data).
- **Background analysis** (`intel/run-project.ts` and other system reads: templates, packs uninstall): ticket `via = "system"`,
  `sub` = business-project owner, `loc = "*"`. Findings written from it stay protected by LAAM's existing per-user filtering
  (`visibility.ts`). This is the only all-stores ticket not tied to an acting human; it is minted server-side only.
- **Flag ↔ POS data:** enabling POS data on a project forces `delegation_required = ON`; landed uploads are refused while the flag is
  OFF; only a global admin can switch it OFF (and not while POS data is enabled). One-time backfill: ON for projects with landed
  enabled.
- **Paused schedules (`data_access_lost`):** re-evaluated at each tick; resume automatically when the owner regains stores; same
  30-day purge as other paused reasons; owner notified once (existing notify path).
- **MCP bridge:** per-call headers reach tool handlers only via the request (`serve.go:492`, `req.Extra.Header`), so the forward
  is added in `serve.go` + `client.go` (small, additive; payment branch is already merged into this branch in `ennam.kg.go`).
- **Admin service keys** (global admin API keys without a user, e.g. the worker key) are not subject to tickets — they must never be
  given to LAAM; stated explicitly as an operational rule.
- **GenerateKG mismatch ⇒ 404** (do not reveal that the data source exists in another project).
- **Store-limited ticket = allow-list:** only store-filterable data reads (metrics, evidence, record, data status) plus
  non-data catalogue calls are allowed; everything else is denied by default.
- **Knowledge & AI memory (user decision 2026-11-13, on controller's recommendation):** for a store-limited ticket, the shared
  project knowledge (documents, chunks, notes/decisions/graph nodes, derived/master records, sessions) and AI memory
  (`kg_recall`/`kg_remember` and similar) are **denied** in WS0 — they are not partitioned by store and may mention other stores.
  Future (non-goal now): admin can mark documents "shared with all staff" to open them to members; AI memory becomes per-user.

## 4. Constraints
- Branch `task/pos-data-model`; must merge after `task/payment-subscription`. Payment-owned files: go `internal/service/source_executor.go`,
  `nl_query.go`, `internal/models/ai_query.go`, `internal/bridge/*` (only additive edits in non-billing bridge files, coordinated);
  LAAM `src/db/schema.ts` + drizzle migrations (no new migration in WS0), billing/settings, `contracts/admin-api.ts`; LAAM
  `src/app/api/chat/route.ts` and `src/app/api/workflows/generate/chat/route.ts` are shared — keep edits small and localized.
- D10: DAAB core stays industry-neutral (`location_id` is the generic dimension name already used).
- No real customer data until WS0 is merged and the flag is ON for that project.
- Tests: DAAB integration tests (ticket valid/expired/wrong aud/kid/pid; flag on/off; filtering incl. injected filter, metric
  without location denied, NL→SQL denied for limited; fail-closed; IDOR); LAAM tests per path (member PH-001 sees only PH-001; no
  scope ⇒ nothing; owner/admin ⇒ all; scheduled run uses owner's current scope and pauses on loss).
- E2E (Chrome DevTools) on the e2e stack: a member assigned one store sees only that store in intel pages and chat; a scheduled
  workflow run returns only that store.

## 5. Non-goals / anti-goals
- Not: recipient/egress control, destination registry, data labels (D3).
- Not: per-user DAAB keys, OAuth/IdP, policy engine, landed-DB RLS by location (possible later defence in depth).
- Anti-goal: any path where a failed/absent ticket silently falls back to org-wide access on an enforced project.

## 6. Left to the builder
- JWT library choice in Go and TS (standard, maintained); exact clock-skew value (≤ 60 s).
- Where the `delegation_required` flag lives (project settings table vs projects column) — follow existing settings conventions.
- How the LAAM MCP client attaches per-call headers (per-request header vs per-user session cache).
