# Admin Pages (DAAB Packs tab + LAAM Business Projects) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give non-technical admins screens to (a) switch industry packs on/off per project in DAAB and (b) create and manage LAAM business projects, who can see them (user scope) and their daily analysis schedule — replacing today's CLI/seed-script-only workflow. Also fix three small issues found on the way.

**Architecture:** DAAB gets two admin HTTP endpoints over the existing `pack_install` table plus a fixed project stat; the DAAB dashboard gets a "Packs" tab. LAAM gets admin API routes (`/api/intel/admin/*`) over the existing `business_project`, `user_scope`, `analysis_job` tables and a `/settings/business-projects` UI section. No DB schema changes anywhere.

**Tech Stack:** Go (net/http mux, pgx via existing stores), Next.js (DAAB dashboard: Tailwind + shadcn-style `@/components/ui`, TanStack Query; LAAM: Next.js 16 App Router, Drizzle, zod, vitest), i18n dictionaries (vi/en/zh) in LAAM.

**Spec:** `docs/superpowers/specs/2026-09-25-industry-pack-proactive-intelligence-design.md` (§5 pack ownership by the metrics source, §7.1 jobs run as the project owner) plus the decisions in this plan's "Decisions" section (made in conversation 2026-10-05).

## Global Constraints

- **No DB schema changes** (no migrations, no new tables/columns) in DAAB or LAAM. LAAM `user` table untouched (a permissions branch is in progress elsewhere).
- **Non-technical users must be able to use every new screen.** Rules: plain everyday words (never show rule ids like `RET-INV-003`, metric keys, cron expressions, UUIDs as the primary label); pick from lists (projects, people, stores, time zones) instead of typing ids; schedules shown as a sentence, e.g. "Runs every day at 6:00 AM (Chicago time)"; statuses and errors in plain words with the next step; helpful empty states; a confirmation dialog before anything hard to undo; keyboard-accessible, 16px side gutters, no horizontal page scroll at 320px.
- **LAAM strings** go through the i18n dictionaries in all three languages (vi/en/zh), new dictionary `src/i18n/dictionaries/intelAdmin.ts` with keys `intelAdmin.*`, plus a test pinning every key has all three languages. The DAAB dashboard has no i18n: inline English like the rest of that app.
- **Roles:** DAAB admin endpoints require project role Admin (`requireProjectRole(..., models.ProjectMemberRoleAdmin, resolver)`). LAAM admin routes require session role `owner` or `admin` (`requireRole`), JSON bodies only via `readJson`, zod `strictObject` validation, `audit_log` row per write, same per-user rate limit as `sessionUser`.
- **Code comments and commit messages in English.** Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Commit per repo (nested git repos: `ennam.kg.go`, `ennam.kg.next`, `LAAM`, workspace root for docs).
- **TDD** where a test harness exists (Go and LAAM). `ennam.kg.next` has no test infra: do not add any; verify with `npm run lint` and `npm run build` instead.
- Surgical changes only; match existing style; do not refactor adjacent code.
- Never print or store secrets. Do not edit any `.env`.

## Decisions (made 2026-10-05)

1. Pack list/enable use the registry the server loaded at startup. A pack folder added to disk later appears only after a server restart (the registry is immutable; hot reload is out of scope). The UI says nothing about this; ops notes go in the runbook.
2. The Packs tab only lists, enables and disables packs (plus read-only data status). No "refresh data now" button in this plan: metric runs stay on the scheduler/CLI. Follow-up, not in scope.
3. LAAM project creation picks the DAAB connection and DAAB project from lists built from the owner's MCP connection introduction text (`connectors.mcpInstructions(ownerUserId)` returns `{slug, text}[]`; the text names projects as `- <Name> (project_id: <uuid>)`). When no project can be parsed (connection sees more than 3 projects) the form falls back to a plain "DAAB project ID" field with an explanation.
4. Locations for a restricted user are chosen from the store codes already seen in that project's findings/forecasts; if none exist yet, a text field is offered.
5. Rule-override (threshold) editing is NOT in this plan.
6. "Remember my last project" on Home is a cookie (`laam_home_project`), no DB.

## Review Focus

- Admin screens opened by a non-admin (member/viewer): must get 403 on API and redirect on page, never partial data.
- Enabling a pack whose parent pack is not enabled (pharmacy needs retail): clear refusal in plain words, nothing written.
- Disabling the last enabled pack of a project that has a running LAAM business project: allowed but confirmed with a warning that analysis will stop until a pack is enabled again.
- Creating a business project with a DAAB project ID the chosen connection does not name: refused with a plain message (mirrors the pin check in `providerForProject`).
- Removing the only executive/owner scope, or a user scope for a user with open tasks: warn; never silently orphan the owner.
- Schedule edits with an invalid time/time zone, and "run now" while a run is already running: friendly error, no duplicate run.
- A scope with `locationIds` for a persona that is not chain-wide must be required to be non-empty; for chain-wide personas it must be empty (existing invariant).

---

## File Structure

**ennam.kg.go**
- Modify `internal/models/project.go`, `internal/store/project.go`: `DataSourceCount` in project stats.
- Create `internal/intel/admin/packs.go` (+ `packs_test.go`): `ListPacks`, `SetPackEnabled` extracted from `cmd/kg-packs/main.go` logic, importable.
- Create `internal/handler/intel_packs.go` (+ `intel_packs_test.go`): `GET /api/v1/projects/{id}/packs`, `PUT /api/v1/projects/{id}/packs/{key}`.
- Modify `cmd/kg-server/intel_wiring.go`, `cmd/kg-server/main.go`: construct and register the handler.
- Modify `cmd/kg-packs/main.go`: `installPacks` delegates to the new package (behavior unchanged).

**ennam.kg.next**
- Modify `src/app/(dashboard)/projects/[id]/layout.tsx`: add the "Packs" tab.
- Create `src/app/(dashboard)/projects/[id]/packs/page.tsx`, `src/hooks/use-project-packs.ts`, `src/types/project-pack.ts`.

**LAAM**
- Create `src/lib/intel/admin/` : `schemas.ts` (zod), `schedule.ts` (cron <-> plain schedule), `connection-projects.ts` (parse introduction text), `repo.ts` (reads/writes), `guard.ts` (admin route guard); each with a `*.test.ts`.
- Create `src/app/api/intel/admin/projects/route.ts`, `projects/[id]/route.ts`, `projects/[id]/scopes/route.ts`, `projects/[id]/schedule/route.ts`, `options/route.ts` (+ tests).
- Create `src/app/(app)/settings/business-projects/page.tsx`, `.../[id]/page.tsx`, components under `src/components/intel/admin/`, dictionary `src/i18n/dictionaries/intelAdmin.ts` (+ test); modify `src/components/settings/SettingsMenu.tsx` (admin-only row).
- Modify `src/lib/intel/home/load.ts`, `src/app/(app)/home/page.tsx`, `src/components/intel/intel.module.css`, new `src/components/intel/home/RememberProject.tsx` (Home fixes).
- Modify `e2e/` : new read-only `e2e/intel-admin.spec.ts`.

---

### Task 1: DAAB — project stats count data sources

**Files:** Modify `ennam.kg.go/internal/models/project.go` (around line 25), `ennam.kg.go/internal/store/project.go` (`ProjectStore.GetStats`); test next to the store's existing tests.

**Interfaces:** Produces JSON field `data_source_count` (int) on `GET /api/v1/projects/{id}/stats`, consumed unchanged by the dashboard (`stats.data_source_count`).

- [ ] **Step 1:** Find the existing GetStats test (grep `GetStats` in `internal/store/*_test.go`, `internal/service/*_test.go`, `internal/handler/project*_test.go`). Add a failing assertion: a project with 2 non-deleted data sources and 1 soft-deleted data source returns `DataSourceCount == 2`.
- [ ] **Step 2:** Run it: `cd ennam.kg.go && go test ./internal/store/... -run GetStats -v` (use the repo's DB-test conventions; the DB tests read `KG_TEST_DATABASE_URL`, dev DB is on :5433, never :5432). Expected FAIL (field missing).
- [ ] **Step 3:** Add `DataSourceCount int \`json:"data_source_count"\`` to `models.ProjectStats` and add `(SELECT COUNT(*) FROM data_sources WHERE project_id = $1 AND deleted_at IS NULL)` to the stats query, scanning into the new field.
- [ ] **Step 4:** Run `go test ./internal/store/... ./internal/handler/... ./internal/service/...`; all green. `gofmt -l` clean, `go vet ./...` clean.
- [ ] **Step 5:** Commit in `ennam.kg.go`: `fix(projects): count data sources in project stats`.

### Task 2: DAAB — pack admin logic + HTTP endpoints

**Files:** Create `internal/intel/admin/packs.go`, `packs_test.go`; create `internal/handler/intel_packs.go`, `intel_packs_test.go`; modify `cmd/kg-server/intel_wiring.go`, `cmd/kg-server/main.go` (next to `intelHandler.RegisterRoutes(apiMux)`), `cmd/kg-packs/main.go`.

**Interfaces:**
- Consumes: `intel.Registry` (`Packs map[string]*intel.Pack` with `Key, Version, DisplayName, Extends`), `intelstore.Store` (`ListInstalls`, `UpsertInstall`), `requireProjectRole`, `models.ProjectMemberRoleAdmin`, `ProjectRoleResolverFunc`.
- Produces in package `admin` (import path `.../internal/intel/admin`):
```go
type PackInfo struct {
    Key         string   `json:"key"`
    DisplayName string   `json:"display_name"`
    Version     string   `json:"version"`
    Extends     []string `json:"extends"`      // parent pack keys
    Installed   bool     `json:"installed"`
    Enabled     bool     `json:"enabled"`
    InstalledVersion string `json:"installed_version,omitempty"`
}
func ListPacks(ctx context.Context, st *intelstore.Store, reg *intel.Registry, projectID string) ([]PackInfo, error) // sorted by Key
type EnableError struct{ Code, Message string } // Code: "unknown_pack" | "parent_not_enabled" | "child_still_enabled"
func SetPackEnabled(ctx context.Context, st *intelstore.Store, reg *intel.Registry, projectID, key string, enable bool) error
```
  Rules: unknown key -> `unknown_pack`; enabling requires every parent in `Extends` currently enabled for the project -> else `parent_not_enabled`; disabling refuses while another enabled pack extends it -> `child_still_enabled`.
- HTTP: `GET /api/v1/projects/{id}/packs` -> `{"packs":[PackInfo...]}` (any project member via `requireProjectAccess`); `PUT /api/v1/projects/{id}/packs/{key}` body `{"enabled":true|false}` (project Admin) -> 200 with the updated `{"packs":[...]}`; `EnableError` -> 409 `{"error":{"code","message"}}` using `writeIntelError`; unavailable registry (q nil) -> 503 `packs_unavailable` like the existing handler.

- [ ] **Step 1:** Write `packs_test.go` with a fake store (small interface `installStore{ListInstalls; UpsertInstall}` defined in the new package so tests need no DB) and a registry built from a temp dir containing packs `retail` and `pharmacy` (`extends: [retail]`; mirror `internal/intel` test helpers/fixtures). Tests: list marks installed/enabled correctly; enabling pharmacy without retail -> `parent_not_enabled`; enabling retail then pharmacy works; disabling retail while pharmacy enabled -> `child_still_enabled`; unknown key -> `unknown_pack`; enabling an already-enabled pack is idempotent (no error).
- [ ] **Step 2:** Run `go test ./internal/intel/admin/ -v`; expected FAIL (package missing).
- [ ] **Step 3:** Implement `packs.go`. `Store` parameter type is the small `installStore` interface (satisfied by `*intelstore.Store`). Move the parent-enabled check logic out of `installPacks` in `cmd/kg-packs/main.go` into `SetPackEnabled`, and make `installPacks` call it so CLI behavior and its existing tests stay identical.
- [ ] **Step 4:** Run `go test ./internal/intel/... ./cmd/kg-packs/...`; green.
- [ ] **Step 5:** Write `intel_packs_test.go` (style of `intel_metrics_test.go` and `datasource_role_test.go`): GET returns the list for a project member; PUT as Viewer -> 403; PUT as Admin enabling pharmacy without retail -> 409 with code `parent_not_enabled`; PUT body not JSON -> 400; registry nil -> 503.
- [ ] **Step 6:** Implement `intel_packs.go` (`NewIntelPacksHandler(st packsAdmin, reg *intel.Registry, roleResolver ProjectRoleResolverFunc, logger)` + `RegisterRoutes(mux)`), wire it in `intel_wiring.go`/`main.go` beside the metrics handler, passing the same `db`-backed store and the registry `buildIntel` already loads.
- [ ] **Step 7:** Run `go test ./internal/handler/... ./cmd/... ./internal/intel/...`, `go vet ./...`, `gofmt -l .`; all clean.
- [ ] **Step 8:** Commit in `ennam.kg.go`: `feat(intel): admin endpoints to list and switch industry packs per project`.

### Task 3: DAAB dashboard — "Packs" tab

**Files:** Modify `ennam.kg.next/src/app/(dashboard)/projects/[id]/layout.tsx` (`projectTabs`); create `src/app/(dashboard)/projects/[id]/packs/page.tsx`, `src/hooks/use-project-packs.ts`, `src/types/project-pack.ts`.

**Interfaces:** Consumes the Task 2 endpoints through the existing proxy (`/api/kg/projects/${id}/packs`, `PUT /api/kg/projects/${id}/packs/${key}`), `useMyProjectRole(projectId)`, `ConfirmDialog`, `Switch`, `Badge`, `Card` from `@/components/ui`.

Page behavior (non-technical wording):
- Tab label **"Industry Templates"** (route `/projects/{id}/packs`). Page title "Industry templates"; subtitle "Templates teach this project the rules of an industry, such as retail or pharmacy. Turn on the ones that fit your data."
- One card per pack: display name, version in small text, plain description line derived from `extends` ("Builds on Retail" when it has parents), a switch labelled "On"/"Off".
- Turning a switch **off** opens a ConfirmDialog: "Turn off {name}? Reports and alerts that use it will stop being updated for this project. You can turn it back on at any time." Turning **on** applies directly. Non-admins see the switches disabled with the note "Only project admins can change this."
- Error mapping to plain words: `parent_not_enabled` -> "Turn on {parent name} first — {name} builds on it."; `child_still_enabled` -> "Turn off {child name} first — it builds on {name}."; other failures -> "We couldn't save that change. Please try again."
- Empty state (no packs available): "No industry templates are installed on the server yet. Ask your administrator to add one."
- Loading skeleton and error state with a Retry button.

- [ ] **Step 1:** Add `ProjectPack` type matching the Task 2 JSON (`key, display_name, version, extends, installed, enabled, installed_version?`).
- [ ] **Step 2:** Add hook `useProjectPacks(projectId)` (`useQuery` key `['project-packs', id]`) and `useSetPackEnabled(projectId)` (`useMutation`, invalidates the query; surfaces the Go error code so the page can map it).
- [ ] **Step 3:** Add the tab item `{ href: \`/projects/${id}/packs\`, label: 'Industry Templates' }` after Knowledge Sources in `projectTabs`, and build the page per the behavior above, following `[id]/members/page.tsx` for structure and the dark hex palette.
- [ ] **Step 4:** `cd ennam.kg.next && npm run lint && npm run build`; both pass. Start the dashboard against the local server and take a screenshot (Playwright MCP or Chrome) of the tab at 1440 and 375 widths; confirm no horizontal scroll.
- [ ] **Step 5:** Commit in `ennam.kg.next`: `feat(projects): Industry Templates tab to switch packs on and off`.

### Task 4: LAAM — admin library and API routes

**Files:** Create `src/lib/intel/admin/{schemas.ts,schedule.ts,connection-projects.ts,repo.ts,guard.ts}` + tests; create routes `src/app/api/intel/admin/options/route.ts`, `projects/route.ts`, `projects/[id]/route.ts`, `projects/[id]/scopes/route.ts`, `projects/[id]/schedule/route.ts` + route tests (harness: `src/lib/intel/testing/route-harness.ts`, style of `src/app/api/intel/findings/[id]/open/route.test.ts` and `src/app/api/users/route.test.ts`).

**Interfaces (exact):**
```ts
// schedule.ts
export interface DailySchedule { hour: number; minute: number; timeZone: string }
export function cronOf(s: DailySchedule): string            // "30 6 * * *"; throws ScheduleError on bad input
export function scheduleOf(cron: string, timeZone: string): DailySchedule | null // null when the cron is not a simple daily one
export function isValidTimeZone(tz: string): boolean        // Intl.DateTimeFormat try/catch
export class ScheduleError extends Error { code: "bad_time" | "bad_time_zone" }

// connection-projects.ts
export interface DaabProjectChoice { id: string; name: string }
export function parseProjectChoices(instructionsText: string): DaabProjectChoice[] // from "- Name (project_id: uuid)" lines; dedupe by id; ignores non-uuid ids

// schemas.ts (zod strictObject)
export const createProjectBody:  { name:string(1..80), connectorSlug:string, daabProjectId:string(uuid), timeZone:string, locale:"vi"|"en"|"zh", ownerUserId?:string }
export const updateProjectBody:  { name?:..., timeZone?:..., locale?:..., asOf?: string|null (YYYY-MM-DD) }
export const scopeBody:          { userId:string, persona:string, locationIds:string[] }   // upsert
export const scopeDeleteBody:    { userId:string }
export const scheduleBody:       { hour:int 0..23, minute:int 0..59, timeZone:string, enabled:boolean }

// guard.ts
export async function adminSession(): Promise<Guarded<{ userId: string }>> // reuses sessionUser(true) + requireRole owner/admin

// repo.ts (all take `db` as first param for testability)
listProjects(db): Promise<AdminProjectRow[]>           // id,name,daabProjectId,connectorSlug,timeZone,locale,asOf, ownerName, peopleCount, packs: never (not read here), schedule: {enabled,hour,minute,timeZone,lastRunAt,lastError}|null, lastRun: {status,finishedAt}|null
getProject(db, id): Promise<AdminProjectDetail|null>   // + scopes: {userId,name,email,persona,locationIds}[]
createProject(db, input, actorId): Promise<string>     // inserts business_project + owner user_scope(executive,[]) + daily job (06:00, same tz, enabled) + audit_log, one transaction; id = "bp-" + slug(name) + "-" + 4 random chars
updateProject(db, id, patch, actorId): Promise<void>
upsertScope(db, id, input, actorId): Promise<void>     // enforces invariant: persona chain-wide (executive) => locationIds [] ; other persona => locationIds non-empty; user must exist
removeScope(db, id, userId, actorId): Promise<{ removed: boolean }> // refuses to remove the project owner's scope -> throws AdminError("owner_scope")
setSchedule(db, id, s, actorId): Promise<void>        // updates analysis_job (kind 'daily'): cron, timezone, enabled, nextRunAt = nextRunInTimeZone(cron, now, tz) (from ../time)
optionsFor(userId): Promise<{ connections: {slug:string; projects: DaabProjectChoice[]}[]; users:{id,name,email}[]; personas:{key:string;chainWide:boolean}[]; timeZones:string[]; locations: (id:string)=> Promise<string[]> }>
export class AdminError extends Error { code: "owner_scope"|"not_found"|"bad_scope"|"unknown_connection"|"unknown_daab_project"|"duplicate_project" }
```
Routes: `GET /api/intel/admin/options` (query `projectId?` for locations); `GET/POST /api/intel/admin/projects`; `GET/PATCH /api/intel/admin/projects/[id]`; `PUT/DELETE /api/intel/admin/projects/[id]/scopes`; `PUT /api/intel/admin/projects/[id]/schedule`. "Run now" reuses the existing `POST /api/intel/analysis/run`. Create validates: connector slug is in `connectors.mcpInstructions(owner)`; the DAAB project id is among `parseProjectChoices(text)` when the text names any, otherwise (text names none) any well-formed uuid is accepted and a warning flag `unverified:true` is returned; duplicate = same `daabProjectId` + `connectorSlug` already used -> `duplicate_project`. Personas come from the pack roles (`chainWidePersonasOf`, existing `roles.yaml` personas) — read through the existing pack loader; never hardcode.

- [ ] **Step 1 (schedule):** Write `schedule.test.ts`: `cronOf({hour:6,minute:0,timeZone:"America/Chicago"})==="0 6 * * *"`; `scheduleOf("30 6 * * *","America/Chicago")` -> `{hour:6,minute:30,...}`; `scheduleOf("*/5 * * * *", tz)` -> `null`; hour 24 / minute 60 / "Mars/Base" throw/return false. Run -> FAIL; implement `schedule.ts`; run -> PASS.
- [ ] **Step 2 (connection parsing):** Write `connection-projects.test.ts` using the exact bridge sentence format ("This DAAB (Ennam Knowledge Graph) connection is scoped to the following project(s):\n- Pharmacy Chain (project_id: 4ad7a5fa-a036-4f6a-8229-39a20af23e38)\n  ..."): single project, three projects, duplicate id, non-uuid id ignored, the "many projects" sentence (no ids) -> `[]`. FAIL -> implement -> PASS.
- [ ] **Step 3 (schemas + guard):** Tests: each schema rejects unknown keys, out-of-range values and bad uuids; `adminSession` returns 403 for role `member`/`viewer` and 401 without session (harness). Implement.
- [ ] **Step 4 (repo):** Tests with the repo test conventions in `store/repo.contract.ts` / `repo.db.test.ts` style (in-memory fake `db` object if that is how the neighbors do it; otherwise vi-mocked chained stubs as in `users/route.test.ts`): createProject writes project + owner scope + daily job + audit row in one transaction and rolls back on failure; upsertScope enforces the persona/location invariant (Review Focus); removeScope refuses the owner; setSchedule recomputes `nextRunAt`; updateProject only touches provided fields. Implement `repo.ts`.
- [ ] **Step 5 (routes):** Route tests for each handler: 401/403 for non-admin; 400 on bad body; 415 on non-JSON; 404 unknown project; happy paths record the expected ops (`insert:business_project`, `insert:user_scope`, `insert:audit_log` ...); `create` with a DAAB project id the connection does not name -> 422-style error `unknown_daab_project` mapped to a plain message key. Implement routes using `adminSession`, `readJson`, `errorResponse` patterns from `src/lib/intel/http.ts`.
- [ ] **Step 6:** `cd LAAM && PACKS_DIR=../packs npx vitest run src/lib/intel src/app/api/intel && npx tsc --noEmit` (only the known pre-existing `executors.test.ts` error may remain). All green.
- [ ] **Step 7:** Commit in `LAAM`: `feat(intel): admin API for business projects, people and schedule`.

### Task 5: LAAM — admin UI (settings section) with i18n

**Files:** Create `src/app/(app)/settings/business-projects/page.tsx`, `src/app/(app)/settings/business-projects/[id]/page.tsx`, `src/components/intel/admin/{ProjectList.tsx,CreateProjectDialog.tsx,PeopleSection.tsx,ScheduleSection.tsx,ProjectBasics.tsx,adminApi.ts}` (+ component tests), `src/i18n/dictionaries/intelAdmin.ts` + `intelAdmin.test.ts`; modify `src/components/settings/SettingsMenu.tsx` (admin-only row "Business projects" with a Briefcase/Building icon, sub-label "Which companies LAAM watches, who sees what, and when it runs").

**Interfaces:** Consumes Task 4 routes through `adminApi.ts` (thin `fetch` helpers sending `Content-Type: application/json`, returning typed results and mapping `{error, code}` to dictionary keys). Pages gate with `if (role !== "owner" && role !== "admin") redirect("/settings")` after `auth()`.

Screens (all plain language; vi/en/zh):
1. **List** ("Business projects"): a card per project — name, "Data from: {DAAB project name or id short}", "{n} people can see this", schedule sentence ("Runs every day at 6:00 AM, Chicago time" / "Paused"), last result in words ("Last checked today at 6:02 AM — all good" / "Last check failed: {plain reason}"), button "Open". Empty state: "No business projects yet. Create the first one to start getting daily briefings." Primary button "New business project".
2. **Create dialog** (3 steps in one dialog, no jargon): ① "Where is the data?" choose a connection (dropdown, shows friendly name) and then a DAAB project (dropdown of names; if none can be listed, a text field "Project ID" with help text and an "unverified" note); ② "About this project": name, language, time zone (searchable select from `Intl.supportedValuesOf("timeZone")`, default = browser time zone); ③ "Who is in charge": owner (people dropdown, default me). Final button "Create business project". Success -> go to the detail page.
3. **Detail page** with four sections: **Basics** (edit name, language, time zone, "Use data up to" date — labelled "Pretend today is" with help "Only for demos"); **People** (table: person, role in words, stores; "Add person" dialog: person dropdown, role dropdown whose labels come from persona names with a one-line explanation each, store checkboxes shown only for roles that need stores, with "All stores" implied for chain-wide roles; remove with confirm; owner row has no remove); **Daily check** (time picker hour/minute, time zone select, On/Off switch, sentence preview "Runs every day at {time} ({zone})", button "Run it now" calling the existing run route with progress text and the plain result/err); **Data & templates** (read-only: "These industry templates are on in DAAB: Retail, Pharmacy" via the existing provider listMetrics through a small server action, with "Change them in DAAB → Project → Industry Templates").
4. Errors use dictionary messages, e.g. `owner_scope` -> "The person in charge can't be removed. Pick a new owner first."; `unknown_daab_project` -> "That project isn't part of the selected connection. Choose one from the list."; `bad_scope` -> "Pick at least one store for this role."

- [ ] **Step 1:** Write `intelAdmin.test.ts` (every key has vi/en/zh non-empty; no key's English contains `cron`, `uuid`, `slug`, `metric`, `pack_` as visible words) -> FAIL; create the dictionary with every string used below -> PASS.
- [ ] **Step 2:** Component tests (Testing Library, style of `UsersManager.test.tsx`): ProjectList renders cards, empty state and the schedule sentence; CreateProjectDialog walks the three steps, disables "Create" until required fields are valid, shows the fallback text field when a connection lists no projects, maps `unknown_daab_project`; PeopleSection hides store checkboxes for the chain-wide role and requires one store otherwise, owner row has no remove button, removal asks for confirmation; ScheduleSection shows the sentence preview live and rejects an invalid time. Run -> FAIL.
- [ ] **Step 3:** Implement components and pages; add the SettingsMenu row (visible only when `canManageUsers`-style check passes) and update `SettingsMenu.test.tsx` for admin vs member.
- [ ] **Step 4:** `npx vitest run src/components src/app src/i18n` green except the known unrelated `ConstellationClient` failures; `npx tsc --noEmit` clean for new files; `npx eslint` on touched files.
- [ ] **Step 5:** Visual check: run the dev server (`PACKS_DIR=../packs npx next dev -p 3100`), log in as an owner/admin account, screenshot list, create dialog, detail at 1440/768/375, in vi and en; confirm no horizontal overflow and that a reader with no technical background can follow each screen (read every visible string).
- [ ] **Step 6:** Commit in `LAAM`: `feat(intel): settings screens to manage business projects, people and schedule`.

### Task 6: LAAM — Home: remember last project and mark the active chip

**Files:** Modify `src/lib/intel/home/load.ts` (`loadHome` option `preferredProjectId`), `src/app/(app)/home/page.tsx` (read cookie `laam_home_project`), `src/components/intel/intel.module.css`; create `src/components/intel/home/RememberProject.tsx` (client component writing the cookie); tests `load.test.ts` (existing file or new), `page.test.tsx`, `RememberProject.test.tsx`.

**Interfaces:** `loadHome(viewer, { projectId, preferredProjectId?, cookieLang, ... })`: selection order is `projectId` (URL) -> `preferredProjectId` if the viewer still has access -> `scopes[0]`. Cookie: name `laam_home_project`, value = business project id, `Path=/; Max-Age=31536000; SameSite=Lax`.

- [ ] **Step 1:** Failing tests: with two accessible projects and `preferredProjectId` = the second, `loadHome` returns the second; a stale/inaccessible preferred id falls back to `scopes[0]` without error; an explicit `projectId` wins over the preference; `RememberProject` writes the cookie for the shown project; the active chip has `aria-current="page"` and a visible style (test via class on the element).
- [ ] **Step 2:** Run -> FAIL. Implement. CSS: `.chip[aria-current="page"]` — solid accent background, readable contrast in light and dark (reuse tokens; check contrast >= 4.5:1).
- [ ] **Step 3:** `npx vitest run src/lib/intel/home src/app/\(app\)/home src/components/intel` green.
- [ ] **Step 4:** Commit in `LAAM`: `feat(home): open the last viewed project and highlight the active one`.

### Task 7: End-to-end check, docs and report

**Files:** Create `LAAM/e2e/intel-admin.spec.ts`; modify `docs/superpowers/runbooks/2026-10-05-test-and-usage-guide.md` (new section), `docs/superpowers/test-results/2026-10-05-beta-completion-report.md` (move the "no admin screens" items to done), LAAM `CHANGELOG.md` (Vietnamese, under `[Unreleased]`).

- [ ] **Step 1:** Playwright spec, read-only: log in as an owner/admin (env `E2E_ADMIN_EMAIL/PASSWORD`; skip with a clear message when unset), open `/settings/business-projects`, expect the Pharmacy project card with a schedule sentence, open its detail page, expect People and Daily check sections, and that a non-admin (`E2E_EXEC_EMAIL`) gets redirected away. No writes.
- [ ] **Step 2:** Run the stack end to end by hand: restart `daab-server` (new endpoints), build and recreate the LAAM image only if the user asks (production deploy needs the user's explicit go-ahead; do not run `docker compose up` for `app`). Verify the DAAB Packs tab against Pharmacy Chain (both packs On; try turning pharmacy Off then On again on the dev project only with the user's approval), and the stats card now shows the real data source count.
- [ ] **Step 3:** Update runbook and report; mention the pack-folder-needs-restart note and the follow-ups (refresh-data button, rule-override editor).
- [ ] **Step 4:** Commit docs in the workspace repo and the E2E/CHANGELOG in `LAAM`.

---

## Self-Review

- **Spec coverage:** DAAB pack management (Task 2, 3); stats bug (Task 1); LAAM project/people/schedule management (Task 4, 5); Home default-project and chip highlight (Task 6); non-technical UI (Global Constraints + Tasks 3, 5 behavior and visual check); no schema changes (Global Constraints, repo functions only use existing tables).
- **Placeholders:** none; each task names files, interfaces and tests. The two pieces left to the implementer's reading of neighboring code are the DB test style in Task 4 step 4 and the locations source (distinct `locationIds` of the project's findings), both bounded by stated behavior.
- **Type consistency:** `PackInfo` JSON (Task 2) = `ProjectPack` (Task 3); `DailySchedule` / `cronOf` / `scheduleOf` (Task 4) used by schedule route and `ScheduleSection` (Task 5); `AdminError` codes map to dictionary keys in Task 5; `preferredProjectId` / `laam_home_project` consistent across Task 6.
