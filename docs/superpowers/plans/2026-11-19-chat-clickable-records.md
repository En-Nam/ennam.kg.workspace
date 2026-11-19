# Chat UI bugs & clickable results (card #5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** English chat shows English table controls, record ids in chat result tables open the existing receipt drawer, and the model reports source fields without inventing causes.

**Architecture:** All work is in `LAAM/` (Next.js 16, React 19, Vitest). A pure function decides which cells are record links; `ResultTables` renders them as buttons and owns a `ReceiptDrawer` (fixed overlay, so the transcript never moves). A new session route resolves the chat table's MCP server slug → org connection → the caller's visible intel project, then serves the record through a helper extracted from the existing project records route.

**Tech Stack:** Next.js 16 App Router, TypeScript strict, Drizzle, Vitest + Testing Library, in-house i18n (vi/en/zh).

**Spec:** `docs/superpowers/specs/2026-11-19-chat-clickable-records-design.md` (workspace root)

## Global Constraints

- Repo `LAAM/`, branch `task/improve_by_feedback_19112026`. Do not switch branches, merge, push or deploy. Commit per task.
- Code comments and commit messages in English; user-facing strings via i18n in vi, en AND zh.
- No DAAB/connector identifiers ("DAAB", "kg_", "landed") in runtime prompt strings.
- Entities: only `sale` and `refund` (`RecordEntity`). Record id length 1..128.
- Column → entity: `refund_id` → `refund`; `sale_id`, `transaction_id`, `original_transaction_id`, `original_sale_id` → `sale`. Everything else (incl. `refund_transaction_id`) is plain text.
- Every not-found / foreign / other-store / unknown-server / no-matching-project outcome of the new route is the SAME `404` (`notFound()` from `src/lib/intel/http.ts`). Response `Cache-Control: no-store` (`noStore`).
- The client never names a project; the server derives it.
- Task-scoped verification only (the task's own test files + `npx tsc --noEmit`); the full suite runs once after all tasks.
- Avoid the known pre-existing failure `src/test/isolation/org-connection.int.test.ts:131` (needs live DAAB MCP) — not ours.

## Review Focus

1. A cell value that is not a string (number, null, object) in an id column → plain text, never a button (Task 3 test).
2. A view whose source is `model` or a non-MCP tool (`laam_*`) → no links even with a `refund_id` column (Task 3 test).
3. Server slug that belongs to a personal MCP server (not an org connection) → 404, never resolved to an intel project (Task 4 integration test).
4. Org connection with `projectId` in different case from `business_project.daabProjectId` → still resolves (Task 4 test).
5. Closing the drawer returns focus to the clicked id button and does not scroll the transcript (Task 5 test asserts focus return).

---

### Task 1: BUG-01 — chat table labels through i18n

**Files:**
- Modify: `src/components/chat/ResultTables.tsx` (the 4 hardcoded strings: `+{hiddenCols} cột`, `{shown}/{total} dòng` / `{n} dòng`, `Xem thêm {hidden} dòng`, truncation notice)
- Modify: `src/i18n/dictionaries/chat.ts` (new keys next to `chat.showResultTables`)
- Modify: any other `src/components/chat/*.tsx` / `src/components/constellation/ConversationLog.tsx` with hardcoded Vietnamese user-facing text found by the sweep in Step 1
- Test: `src/components/chat/ResultTables.test.tsx`

**Interfaces:**
- Produces keys: `chat.tableMoreCols` (`{n}`), `chat.tableRows` (`{n}`), `chat.tableRowsOf` (`{shown}`, `{total}`), `chat.tableShowMoreRows` (`{n}`), `chat.tableTruncated` (`{shown}`, `{total}`). vi values reproduce today's text exactly (`+{n} cột`, `{n} dòng`, `{shown}/{total} dòng`, `Xem thêm {n} dòng`, `Bảng đã bị cắt bớt — chỉ hiển thị {shown} trên {total} dòng.`); en: `+{n} columns`, `{n} rows`, `{shown}/{total} rows`, `Show {n} more rows`, `Table truncated — showing {shown} of {total} rows.`; zh: `+{n} 列`, `{n} 行`, `{shown}/{total} 行`, `再显示 {n} 行`, `表格已截断 — 仅显示 {total} 行中的 {shown} 行。`

- [ ] **Step 1: Sweep.** Run `grep -nP "[ăâđêôơưáàảãạéèẻẽẹíìỉĩịóòỏõọúùủũụýỳỷỹỵ]" src/components/chat/*.tsx src/components/constellation/ConversationLog.tsx | grep -v "\.test\." ` and list every hit that is user-facing JSX text/attribute (not a comment). Move each to `chat.ts` keys in all three languages in this task.
- [ ] **Step 2: Write failing tests** in `ResultTables.test.tsx`: render with `I18nProvider lang="en"` a view with 12 columns, 20 rows and `truncated: {shown: 20, total: 50}`; assert `+4 columns`, `20/50 rows`, `Show 12 more rows`, `Table truncated — showing 20 of 50 rows.` are present and the text `dòng` / `cột` is absent. Same render with `lang="vi"` asserts the Vietnamese strings.
- [ ] **Step 3: Run** `npx vitest run src/components/chat/ResultTables.test.tsx` → FAIL on the en assertions.
- [ ] **Step 4: Implement** — `ResultTable` calls `useT(chat)` and uses the keys.
- [ ] **Step 5: Run** the test file + `npx tsc --noEmit` → PASS.
- [ ] **Step 6: Commit** `fix(chat): localize result table controls (BUG-01)`.

### Task 2: BUG-03 — source-field reporting rule

**Files:**
- Modify: `src/lib/agent/context.ts` (new const `SOURCE_FIELDS_RULE`, appended to the `buildSystemPrompt` join after `guide`, all modes)
- Test: `src/lib/agent/context.test.ts`

**Interfaces:**
- Produces: `export const SOURCE_FIELDS_RULE: string` (exported for the test).

Rule text (Vietnamese, like the rest of the prompt; exact wording is the builder's, content is fixed): report each source field as its own fact; when two fields disagree (e.g. a boolean flag saying a receipt was present vs a free-text reason saying "no receipt") state both values and mark it as a discrepancy to review — never conclude one from the other; a record dated after today is flagged as "dated in the future, needs review" without guessing a cause; when the data has no currency field/unit, write that the currency is not specified (no guessed unit).

- [ ] **Step 1: Write failing tests:** (a) `buildSystemPrompt` output for text mode with tools, text mode without tools, and voice mode each contains `SOURCE_FIELDS_RULE`; (b) `SOURCE_FIELDS_RULE` mentions the three cases: matches `/mâu thuẫn/`, `/tương lai/` and `/tiền tệ/`; (c) it does not match `/daab|kg_|landed/i`; (d) the existing no-tools wording test still passes (rule must not contain `công cụ` / `tool`).
- [ ] **Step 2: Run** `npx vitest run src/lib/agent/context.test.ts` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** test + `npx tsc --noEmit` → PASS.
- [ ] **Step 5: Commit** `fix(chat): report source fields separately, flag future dates and missing currency (BUG-03)`.

### Task 3: record link rule (pure)

**Files:**
- Create: `src/lib/chat/record-links.ts`
- Test: `src/lib/chat/record-links.test.ts`

**Interfaces:**
- Consumes: `ViewDescriptor` (`src/lib/agent/view.ts`), `RecordEntity` (`src/lib/intel/provider/types.ts`).
- Produces:
  - `export type RecordLink = { server: string; entity: RecordEntity; id: string }`
  - `export function serverOfView(v: ViewDescriptor): string | null` — `mcp__<slug>__<tool>` → `<slug>`; anything else (model source, `laam_*`, malformed, empty slug) → null.
  - `export function entityOfColumn(key: string): RecordEntity | null` — mapping from Global Constraints, exact key match.
  - `export function recordLinkOf(server: string | null, columnKey: string, value: unknown): RecordLink | null` — null unless server non-null, entity non-null, value is a string with trimmed length 1..128.

- [ ] **Step 1: Write failing tests:** `serverOfView` for `mcp__daab__kg_query_datasource` → `daab`, `mcp__daab-personal__x` → `daab-personal`, `laam_query_stats` → null, `{type:"model"}` → null, `mcp____x` → null. `entityOfColumn`: each mapped key; `refund_transaction_id`, `store_id`, `REFUND_ID` → null. `recordLinkOf`: `("daab","refund_id","REF-000137")` → `{server:"daab",entity:"refund",id:"REF-000137"}`; namespaced landed id `add94069:["PH-005","REG-05","2026-11-01","TXN-1015749"]` with `transaction_id` → sale link with the id unchanged; value `137`, `null`, `""`, 129-char string → null; server null → null.
- [ ] **Step 2: Run** `npx vitest run src/lib/chat/record-links.test.ts` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS; `npx tsc --noEmit`.
- [ ] **Step 5: Commit** `feat(chat): record link rule for result table cells`.

### Task 4: chat records route (server)

**Files:**
- Create: `src/lib/intel/record-response.ts` — extracted body of the project records route.
- Modify: `src/app/api/intel/projects/[projectId]/records/[entity]/[recordId]/route.ts` — call the helper (behaviour unchanged; its `route.test.ts` must still pass untouched).
- Modify: `src/lib/intel/scoped.ts` — add `locateProjectByDaab`.
- Create: `src/app/api/chat/records/[server]/[entity]/[recordId]/route.ts`
- Test: `src/app/api/chat/records/[server]/[entity]/[recordId]/route.test.ts` (unit, mocked like the project route's `route.test.ts`)
- Modify: `src/test/route-inventory.ts`, `src/test/isolation/cases.ts`

**Interfaces:**
- Produces:
  - `export async function recordResponse(sc: Scoped, entity: string, recordId: string, path: string): Promise<Response>` in `record-response.ts` — does entity/length validation (400 `invalid record`), provider read, sanitise, media, `scope_denied` → 404; exactly today's project-route logic. `path` is the provider log path (`"project record"` / `"chat record"`).
  - `export async function locateProjectByDaab(userId: string, daabProjectId: string): Promise<Scoped | null>` — first of the user's scopes whose `ctx.bp.daabProjectId?.toLowerCase() === daabProjectId.toLowerCase()`.
  - Route `GET /api/chat/records/[server]/[entity]/[recordId]` exported as `noStore(handle)`. Flow: `sessionUser(false)` → server param 1..64 chars else 400 → the caller's `user.orgId` → `org_connection` row `(orgId, slug=server)` with non-null `projectId`, else 404 → `locateProjectByDaab` else 404 → `recordResponse(sc, entity, recordId, "chat record")`.
- Client URL base used by Task 5: `/api/chat/records/${encodeURIComponent(server)}`.

- [ ] **Step 1: Write failing unit tests** (mock `auth`, db lookups and provider as the project route test does): 200 with sections for own org connection + matching project (case-different projectId); 404 when no org connection for slug; 404 when connection has null projectId; 404 when no visible project matches; 400 for unknown entity; 404 when provider returns `found:false`; response header `Cache-Control` contains `no-store`; 401 without session.
- [ ] **Step 2: Run** `npx vitest run "src/app/api/chat/records" "src/app/api/intel/projects"` → new tests FAIL, existing project tests PASS.
- [ ] **Step 3: Implement** helper extraction, `locateProjectByDaab`, new route.
- [ ] **Step 4: Run** the same command → all PASS.
- [ ] **Step 5: Isolation.** Add to `route-inventory.ts`: `"/api/chat/records/[server]/[entity]/[recordId]": { GET: { auth: "session", isolation: proven("chat-record.foreign-slug", "chat-record.foreign-project", "chat-record.other-store") } }`. Add three cases in `cases.ts` modelled on `intel-project.record-foreign` / `record-other-store` (use `seedOrgConnection` from `test/helpers/org-connection.ts`; `t.atk.daabProjectId` / `t.vic.daabProjectId` from `world.ts`):
  - `chat-record.foreign-slug`: slug seeded only on the victim org (projectId = victim daabProjectId) → attacker gets 404; positive control: same slug seeded on attacker org with attacker daabProjectId → 200 with the record id.
  - `chat-record.foreign-project`: attacker org connection whose projectId = victim's daabProjectId → 404.
  - `chat-record.other-store`: member with `user_scope` `["PH-MINE"]`, stub record at `PH-OTHER` → 404; positive control at `PH-MINE` → 200.
  Clean up seeded connections in `finally` so other cases see the world unchanged.
- [ ] **Step 6: Run** `npm run test:int -- src/test/isolation` → new cases PASS (ignore only the known `org-connection.int.test.ts:131`).
- [ ] **Step 7: Commit** `feat(chat): session route reading a record from a chat table's source project`.

### Task 5: clickable ids + drawer in ResultTables (depends on 1, 3, 4)

**Files:**
- Modify: `src/components/chat/ResultTables.tsx`
- Modify: `src/i18n/dictionaries/chat.ts` (key `chat.openRecord` `{id}` for the button's `aria-label`: vi `Mở bản ghi {id}`, en `Open record {id}`, zh `打开记录 {id}`)
- Test: `src/components/chat/ResultTables.test.tsx`

**Interfaces:**
- Consumes: `serverOfView`, `recordLinkOf`, `RecordLink` (Task 3); `ReceiptDrawer` (`src/components/intel/detail/ReceiptDrawer.tsx`, props `src`, `entity`, `id`, `onClose`); URL base from Task 4.

Behaviour: in `ResultTable`, a cell whose `recordLinkOf(serverOfView(v), c.key, r[c.key])` is non-null renders a `<button type="button">` with the cell text, link styling with existing tokens (`text-[var(--color-accent)] hover:underline`, visible focus ring), `aria-label` from `chat.openRecord`. Click sets state `{link, trigger: HTMLButtonElement}` in `ResultTables` (one drawer per message); render `<ReceiptDrawer src={`/api/chat/records/${encodeURIComponent(link.server)}`} entity id onClose>` when set. `onClose` clears state and calls `trigger.focus({ preventScroll: true })`. No other caller changes (MessageItem and ConversationLog get it for free).

- [ ] **Step 1: Write failing tests** (mock `fetch`): view with `source.toolName = "mcp__daab__kg_query_datasource"` and columns `refund_id`, `refund_transaction_id`, `original_transaction_id`: `REF-000137` and `TXN-0001111` are buttons, `RTX-000137` is not; clicking `REF-000137` fetches `/api/chat/records/daab/refund/REF-000137` and a dialog appears; Escape / close button closes it and `document.activeElement` is the `REF-000137` button; Enter on the focused button opens it; a `laam_*` view renders no buttons.
- [ ] **Step 2: Run** `npx vitest run src/components/chat/ResultTables.test.tsx` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** test file + `npx tsc --noEmit` → PASS.
- [ ] **Step 5: Commit** `feat(chat): open record ids from result tables in the receipt drawer (BUG-02)`.

## After all tasks

- Full suite once: `npm test`, `npx tsc --noEmit`, `npm run test:int -- src/test/isolation`; fix regressions; whole-branch review.
- E2E (chrome-devtools, local :3900 after `docker build -t laam-app:latest .` + `docker compose up -d app`; ask the user to log in): EN and VI labels; click `REF-…` and `TXN-…` → correct drawer; close keeps scroll; unknown id → not-found; keyboard Tab/Enter/Escape; narrow width; ask the REF-000137 question and check the answer reports the flag/reason discrepancy, future date and unspecified currency.
- `CHANGELOG.md` `[Unreleased]` entry (Vietnamese).

---

## Plan review amendments (binding — they override the tasks above where they differ)

From the Opus plan review (2026-11-19):

**Task 2 (BUG-03)**
- Do NOT add a second currency rule. Rewrite the existing RENDER_GUIDE currency sentence (`src/lib/agent/context.ts` ~L80-81) so that it says: read the unit from the data; when the data has no currency field/unit, write that the currency is not specified — never guess one. Keep its comment's reasoning.
- `SOURCE_FIELDS_RULE` then covers only (a) disagreeing source fields → state both, mark "cần xem xét", never derive one from the other; (b) a record dated after today → "cần xem xét", "nguyên nhân chưa được xác định" (reuse NEUTRAL_WORDING's phrasing). It must not contain "flagged" (test at context.test.ts ~153-155) nor tool wording.
- Tests also cover the "custom base" prompt variant (as the neutral-wording `describe.each` at context.test.ts ~309-325), and assert the rewritten currency sentence says the currency is not specified when absent (`/không (được )?nêu|chưa rõ/`).

**Task 4 (route)**
- Org lookup: new mockable function `export async function projectOfChatServer(userId: string, server: string): Promise<string | null>` in `src/lib/chat/record-source.ts`, implemented with `loadOrgMcp(userId)` (`src/lib/connectors/mcp/org-store.ts`): only an org server of an ACTIVE org for a NON-disabled user; returns that server's `delegation.projectId` (already lower-cased) or null. Personal servers never resolve. The route mocks it in unit tests (the route-harness db fake cannot serve `org_connection` rows).
- Provider call uses `via: "chat"` (as `src/lib/intel/chat/hook.ts:153`); `recordResponse` takes an options object `{ path, via }`.
- Isolation cases: both world orgs already hold slug `"daab"` (projectId `proj-<marker>`, unique `(orgId, slug)`), so seed a FRESH slug (`"chatsrc"`) with `projectId` = the relevant `daabProjectId`. The other-store case seeds its own attacker connection. Add the route to `ROUTE_MODULES` (cases.ts ~213). World is reseeded per test; only delete victim-side rows a case inserted if the snapshot comparison needs it.

**Task 5 (UI)**
- Render the drawer via `createPortal(…, document.body)` (pattern: `RightNavDrawerButton.tsx`) — inside Constellation's animated, transformed, `z-20`, `.dark` log column a fixed overlay is otherwise clipped.
- Drawer styling outside intel pages: the CSS variables live only under `.page` in `src/components/intel/intel.module.css` (~L8-38). Move them into a new `.intelTokens` class (composed by `.page`, so intel pages are unchanged) and put `styles.intelTokens` on the drawer root in `ReceiptDrawer.tsx`. Do not reuse `.page` (it has padding). Intel tests touching ReceiptDrawer/TransactionsView must still pass.
- Focus: in the id button's click handler call `e.currentTarget.focus({ preventScroll: true })` before opening, so `useFocusTrap` captures the right opener; its cleanup restores focus (no extra `focus()` in onClose).
- Drawer close is timer-based (`useAnimatedClose`): tests use `waitFor` or fake timers.
- One Escape must close only the drawer: check whether the Constellation DisplayPanel window Escape handler (`DisplayPanel.tsx:45`) also fires; if it does, ignore Escape there while a dialog with `aria-modal` is open (or stop propagation at the drawer) — test it.
- Known limitation (accepted in spec): users without an intel scope see clickable ids that open "not found".

**Execution**
- Tasks 1–4 touch disjoint files and run in parallel in the same tree: each implementer commits ONLY its own files with explicit `git add <paths>` and judges `npx tsc --noEmit` only on errors in its own files. Task 5 runs after 1, 3, 4.
