# Card #6 Follow-ups — Admin Blockers, Task Reminders, AI Builder Finding Mode, UI Polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An admin can build, save and edit a finding-action workflow using only the UI; assignees hear about tasks (bell + email) at assignment, the day before the due date, and when overdue; and every card #6 screen speaks plain Vietnamese/English with no codes.

**Architecture:**
- **Validation.** `assertRunnable` keeps its role as the runtime gate. Its throws become a typed `GraphValidationError` that carries `WfIssue[]` (code, node, params). The message text does not change.
- **Save-time gate.** A new save-time gate, `assertSavable`, adds three checks: empty prompt, dangling `{{steps.X}}` reference, and missing required connector argument. The required-argument lookup is injected, so `validate.ts` stays client-safe.
- **Reminders.**
  - Due-soon and overdue reminders are derived at sweep time from open `task` rows. They are deduped by `createOnce` keys that include `dueAt`.
  - The assignment notice fires after the create transaction commits.
  - Email always goes out after any transaction, and only when the bell row was newly created.
- **AI builder.**
  - Finding mode is an explicit request flag, `findingAction: true`.
  - It skips the probe. The chat route builds with its existing agent-only path (`deriveNodeTasks` → `agentWorkGraph`) plus the trigger catalogue; the one-shot generate route authors an agent-only Plan from an empty facts sheet plus the catalogue.
  - It gets the terminal write from the existing append-write card.
  - `findingActionGraphProblems` gates the result: with one repair round on the Plan path, and as a returned-problems guard in chat.
  - Readable ids come from the builder's `idOf`, shared with `provenanceOf`, so chat provenance keeps working (Task 12).

**Tech Stack:** Next 16 App Router, React 19, TypeScript strict, Drizzle + Postgres 15, zod, vitest (jsdom unit / `laam_test` integration), react-markdown 10 + remark-gfm + rehype-sanitize (already dependencies), Resend via `src/lib/mail/resend.ts`.

**Spec:** `docs/superpowers/specs/2026-11-20-card6-followups-design.md` (workspace root). Section refs (§5 A1, §8 …) point into it. Read it before any task.

Paths are relative to `LAAM/` unless they start with `docs/`. Run commands from `LAAM/` (`cd LAAM && …`). Commit from the workspace root with `git -C LAAM …`.

## Global Constraints

**Git and deploy**
- Branch `task/improve_by_feedback_19112026` (LAAM nested repo). Commit only. No branch switching, merge, push or deploy (spec header).
- Stage explicit files: `git -C LAAM add <files>`. Never stage a file that was dirty before your task (`git -C LAAM status` first).
- Commit messages and code comments in English. Conventional prefix (`feat:`, `fix:`).

**Email and external writes**
- No real email and no external write in any test or E2E.
- Every test that reaches mail mocks the transport: `vi.mock("@/lib/mail/resend", () => ({ sendMail: vi.fn(async () => true) }))`, then asserts call count and arguments.
- Email is reported as "not verified end to end" unless a real `RESEND_API_KEY` + `MAIL_FROM` is configured.
- Email never runs inside a DB transaction.
- An email failure never rolls back a task, never fails a request, and never stops a sweep (§2 anti-goals, §5 B4).
- Email text never contains finding wording. It carries the task title or the neutral title, chosen per recipient (Task 8).

**Database**
- No migration is expected in this plan. If a task finds one is needed, stop and report. Never use `db:push`.

**i18n**
- Every new user-visible string gets `vi`, `en` and `zh` (zh may repeat en).
- Dictionaries:
  - `src/i18n/dictionaries/workflows.ts` (wf.*);
  - `intel.ts` (intel.*);
  - `notifications.ts` (notif.msg.*);
  - `presets-dialogs.ts` (share.*).
- Vietnamese wording follows the existing tone. Use the exact copy the spec quotes.

**Routes and isolation**
- A changed route keeps or extends its `src/test/route-inventory.ts` entry and its `src/test/isolation/cases.ts` cases.
- Another org's id answers 404 with the "not found" body.

**Restricted views**
- Partial or peer-hidden readers never get finding wording, item rows or labels.
- Reuse `scopeFinding` / `wordingVisible` (`src/lib/intel/finding-actions.ts`), and the items route's `items: null` rule.

**Shared functions**
- Before changing a shared function, list its callers (grep or `spectex_get_blast_radius`) and keep their behaviour.
- Shared functions here: `assertRunnable`, `collectIssues`, `planCreateTask`, `executeCreateTask`, `sweepFindingReminders`, `synthesizePlan`, `taskDto`, `summarizeWorkflow`, `agentWorkGraph`, `provenanceOf`, `deriveNodeTasks`.

**Tests**
- Unit: `npm test -- <path>`. Integration: `npm run test:int -- <path>` (files `*.int.test.ts`; DB `laam_test`; see memory: dev DB is on :5433).
- Per task, run that task's tests plus `npx tsc --noEmit`. The full suite runs once, in Task 18.

## Review Focus

1. **The first deadline sweep after deploy must not mass-mail.**
   - Existing open tasks that went overdue weeks ago must not all mail on the first tick.
   - The sweep only considers `dueAt > now − 14 days` (`OVERDUE_LOOKBACK_DAYS`).
   - Task 9 test `overdue beyond lookback gets nothing`.
2. **A chain-wide creator assigns a default-titled task to a store-scoped user.**
   - The task title equals the finding wording, which the assignee's view hides. After a pack upgrade edits the rule wording, the stored title no longer equals the current wording, so title equality cannot detect it.
   - Rule (controller, I0): whenever the recipient has `wordingVisible === false`, the bell and the email show the neutral title, whatever the task title is.
   - Task 8 test `default-titled task is neutral for a recipient without wording, even after the wording changed`.
3. **Every per-minute tick must send each notice at most once.**
   - It must not re-mail a notice already sent.
   - Mail goes only when `createOnce` returns a row.
   - Task 8 test `no mail when createOnce returns null`, and Task 9 test `second sweep sends none`.
4. **An AI-authored finding graph is incomplete until append-write fills `to`.**
   - `gmail_send` requires `to, subject, body` (`gmail.ts:174`).
   - This must not break AI authoring or the runtime gate. The required-argument check lives only in `assertSavable`, never in `assertRunnable`.
   - Task 1 test `assertRunnable accepts a gmail_send with empty to`.
5. **A US project task due 2026-11-20 must not show as due on 11/21 or be overdue on the afternoon of 11/20.**
   - The task card's due day, the home card's due day, the email day, and the overdue badge all read the project zone through one helper, `dueDayOf` (Task 10).
   - Rows stored before Task 7 (UTC `23:59:59.000`) keep their UTC date, so a Vietnam project's legacy row does not move to the next day.
   - Task 7 test `endOfLocalDay New York`, and Task 10 tests `dueDay is the project-zone day`, `legacy UTC row keeps its day in Ho Chi Minh` and `home card due day is the project-zone day`.

---

## Track A — Admin blockers

### Task 1: Structured validation errors + save-time checks (A2, A3 core)

**Files:**
- Modify: `src/lib/workflow/validate.ts`
- Create: `src/lib/connectors/required-args.ts`
- Modify: `src/app/api/workflows/[id]/route.ts` (PATCH), `src/lib/presets/service.ts:567-575` (`checkGraph`)
- Modify: `src/i18n/dictionaries/workflows.ts` (`wf.validate.<code>` for every new code, with `{node}` and code params)
- Test: `src/lib/workflow/validate.test.ts`, `src/lib/connectors/required-args.test.ts`, `src/app/api/workflows/[id]/route.test.ts`, `src/lib/presets/service.int.test.ts`

**Interfaces:**
- Produces (all in `validate.ts`, client-safe):
  - `WfIssueCode` gains these codes:
    - `"trigger_misuse"`, `"mcp_output_field"`, `"agent_output_field"`, `"bare_formatted_output"`, `"agent_field_unknown"`;
    - `"opaque_id_from_mcp_text"`, `"object_field_as_arg"`;
    - `"extract_from_unknown"`, `"extract_from_not_before"`;
    - `"fanout_cap"`;
    - `"agent_prompt_empty"`, `"step_ref_unknown"`, `"connector_arg_missing"`.
  - `WfIssue` gains `params?: Record<string, string>`, e.g. `{ ref }`, `{ target }`, `{ arg }`.
  - `export class GraphValidationError extends Error { readonly issues: WfIssue[] }`. The message is unchanged from today's text.
  - `export function issuesOf(e: unknown): WfIssue[] | null`
  - `export type RequiredArgsOf = (connectorId: string, action: string) => readonly string[] | undefined`
  - `export function savabilityIssues(graph: WorkflowGraph, requiredOf?: RequiredArgsOf, idPrefix?: string): WfIssue[]`
  - `export function assertSavable(graph: WorkflowGraph, requiredOf?: RequiredArgsOf): void`. It runs `assertRunnable` first, then throws `GraphValidationError` with all savability issues.
  - `collectIssues(graph, idPrefix = "", requiredOf?: RequiredArgsOf)` now also returns `savabilityIssues`.
- Produces (`required-args.ts`, server-only):
  - `export const serverRequiredArgsOf: RequiredArgsOf`. It reads `CONNECTORS[].tools[].function.parameters.required`.
- Wire shape of a 400:
  - **Personal PATCH:** `{ error: <message>, code: "invalid_graph", issues: WfIssue[] }`.
  - **Org-items PATCH:** `{ error: "invalid_graph", message, issues }`, via `new ServiceError(400, "invalid_graph", msg, { issues })`, which `failure()` spreads into the body.
  - The editor reads `issues` from either shape.
- `collectIssues` callers: `WorkflowEditor.tsx` only (advisory). No server gate reads it, so the new codes do not affect authoring.

**Rules:**
- **`agent_prompt_empty`:** an agent node without `extract` whose `prompt.trim() === ""`. Extract nodes are exempt, because their prompt is documentation (`types.ts:18-31`).
- **`step_ref_unknown`:** a `stepRefsOf(node)` id that is no node id anywhere in the graph, foreach bodies included. `params: { ref }`.
- **`connector_arg_missing`:** a connector node whose `requiredOf(connectorId, action)` lists a key whose arg is `undefined`, `null` or a whitespace-only string. `params: { arg }`.
- **What gates what:**
  - `assertRunnable` gets no new rule. Its runtime callers (engine, generate, compile, templates, share) are unchanged.
  - Only the editor preflight (Task 2), the personal PATCH and org-items `checkGraph` call `assertSavable(graph, serverRequiredArgsOf)`.

- [ ] **Step 1: Write the failing tests** in `validate.test.ts`:
  - `assertRunnable throws GraphValidationError with code extract_from_unknown`: `issuesOf(err)` equals `[{ code: "extract_from_unknown", nodeId: "a2", params: { target: "gone" }, severity: "error" }]`, and `err.message` still starts with `validate: agent "a2" — extract.from points at an unknown node`.
  - `every assertRunnable failure class maps to a code`: a table with one minimal bad graph per throw site (linear and `parallel: true`); each throw has a non-null `issuesOf`, and its code is in a fixed expected list.
  - `savabilityIssues flags empty agent prompt but not an extract node`.
  - `step_ref_unknown flags {{steps.gone.output}}; a foreach body ref to an outer node is fine`.
  - `connector_arg_missing for gmail_send without to` (inject `requiredOf = () => ["to","subject","body"]`); `params.arg === "to"`.
  - `assertRunnable accepts a gmail_send with empty to` (Review Focus 4).

  In `required-args.test.ts`: `serverRequiredArgsOf("gmail","gmail_send")` contains `"to"`; an unknown action gives `undefined`.

  In `route.test.ts`: `PATCH with an empty agent prompt returns 400 with issues[0].code agent_prompt_empty`.

  In `service.int.test.ts`: `org workflow update with an empty prompt fails with code invalid_graph and issues`.
- [ ] **Step 2: Run them and see them fail.** `npm test -- src/lib/workflow/validate.test.ts src/lib/connectors/required-args.test.ts "src/app/api/workflows/[id]/route.test.ts"` → FAIL (no export `GraphValidationError`).
- [ ] **Step 3: Implement.**
  - Replace each `throw new Error(...)` in `assertRunnable`, `assertRunnableDag`, `assertLinear`, `assertExtractsReachable` and the `assertNo*` helpers with `throw new GraphValidationError(<same message>, [issue])`.
  - Then add the savability rules and the two route wirings.
  - Add the `wf.validate.*` keys. Example VI: `agent_prompt_empty` → "Bước AI '{node}' chưa có nội dung yêu cầu"; `extract_from_unknown` → "Bước AI '{node}' đang trỏ tới một bước đã bị xoá".
- [ ] **Step 4: Run them and see them pass.** Same command, plus `npm run test:int -- src/lib/presets/service.int.test.ts` and `npx tsc --noEmit` → PASS, no type errors.
- [ ] **Step 5: Commit.** `git -C LAAM add <files> && git -C LAAM commit -m "feat(workflow): structured validation issues and save-time checks"`

### Task 2: Editor — friendly save errors, problems list, dangling cleanup on delete (A2, A3, A4)

**Files:**
- Create: `src/components/workflows/editor/graph-edit.ts`, `src/components/workflows/editor/issue-text.ts`, `src/components/workflows/editor/useRequiredArgs.ts`
- Modify: `src/components/workflows/editor/WorkflowEditor.tsx` (lines 241-256 issue mapping, 640-649 `handleDeleteNode`, 771-807 `persistGraph`/`handleSave`, 1179-1214 save banner + problems list)
- Test: `src/components/workflows/editor/graph-edit.test.ts`, `src/components/workflows/editor/WorkflowEditor.test.tsx`

**Interfaces:**
- Consumes: Task 1 `GraphValidationError`, `issuesOf`, `assertSavable`, `collectIssues(..., requiredOf)`, `WfIssue`, `RequiredArgsOf`.
- Produces:
  - `detachDeletedNode(nodes: readonly WfNode[], deletedId: string): WfNode[]`. Returns new nodes in which any agent `extract` with `from === deletedId` is removed (prompt kept). Nothing is mutated.
  - `issueText(issue: WfIssue, t: (k: string, p?: Record<string, string>) => string): string`. Equals `t("wf.validate." + code, { node: <top-level node id>, ...params })`.
  - `useRequiredArgs(): RequiredArgsOf | undefined`. Fetches `/api/connectors` once and reads `tools[].parameters.required` (the `ConnectorListItem.tools` shape, `connectors/types.ts:84,111`).

**Behaviour:**
- **Save:** the preflight calls `assertSavable(graph, requiredOf)`. A `GraphValidationError` or a server 400 with `issues` sets the banner to `issueText(issues[0])`, never the raw message, and fills the problems list.
  - `persistGraph` is shared by Save and Test (dry run) (`WorkflowEditor.tsx:771-789`), so the preflight also blocks Test of an incomplete graph. This is intended: Test shows the same localized message.
  - `useRequiredArgs` loads asynchronously. A save before the fetch resolves runs the preflight without `requiredOf`, so `connector_arg_missing` is then caught by the server 400 path. The server-issue mapping test below covers it.
- **Problems list:** clicking a row selects the node, as today (`:1196-1201`), and now also centres it (new behaviour). The badge on the node shows the same text.
- **Delete:** the editor holds `RFNode<{ node: WfNode }>`, not `WfNode[]`. `handleDeleteNode` maps the remaining nodes' `data.node` through `detachDeletedNode` and rebuilds the RF nodes from the result. Args still containing `{{steps.<deleted>…}}` then show as `step_ref_unknown` through `collectIssues`.

- [ ] **Step 1: Write the failing tests.**
  - `graph-edit.test.ts`:
    - `deleting a node removes extract.from pointing at it and keeps the prompt`;
    - `input array is not mutated`.
  - `WorkflowEditor.test.tsx`:
    - `save with an empty agent prompt shows the localized message and sends no PATCH`: the banner text contains "chưa có nội dung yêu cầu" and the fetch mock was not called with PATCH;
    - `server 400 issues are shown localized, not raw`: the mock PATCH returns `{ error: "validate: …", issues: [{ code: "extract_from_unknown", nodeId: "n2", params: { target: "x" } }] }`, the banner does not contain "validate:", and it contains "n2";
    - `deleting the source node of an extract leaves a savable graph`;
    - `managed org workflow save with an empty prompt shows the localized message`: the editor is loaded with `managed: true`, and the org-items 400 body `{ error: "invalid_graph", message, issues }` is mapped;
    - `Test with an empty agent prompt shows the same localized message and starts no run`.
- [ ] **Step 2: Run them and see them fail.** `npm test -- src/components/workflows/editor/graph-edit.test.ts src/components/workflows/editor/WorkflowEditor.test.tsx` → FAIL.
- [ ] **Step 3: Implement** as described. Keep `readOnlyRef` guards.
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `fix(workflow-editor): readable save errors and dangling extract cleanup on delete`

### Task 3: Owner/admin gets the editable org copy (A1)

**Files:**
- Modify: `src/app/api/workflows/[id]/route.ts:12-38` (GET)
- Modify: `src/test/route-inventory.ts:617-621`, `src/test/isolation/cases.ts`
- Modify: `src/components/workflows/WorkflowDetailClient.tsx` (Danger zone at `:650-651`, rendered on `!readOnly`)
- Test: `src/app/api/workflows/[id]/route.test.ts`, `src/components/workflows/WorkflowDetailClient.test.tsx`, isolation suite

**Interfaces:**
- Consumes: `loadManagedOrgWorkflow(orgId, id)` and `withSource` (`src/lib/workflow/access.ts`).
- Produces: for owner/admin, GET returns `{ ...withSource(managed), readOnly: false, managed: true }` whenever `loadManagedOrgWorkflow` finds the row. This happens before `loadUsableWorkflow`, so it holds even when the caller is assigned the preset. Members keep the read-only view.
- Saves keep going to `PATCH /api/org-items/workflow/{id}` (`WorkflowEditor.tsx:778`). That path's version and notify behaviour is unchanged, and no new re-notify is added (§8 A1).
- **Delete (controller, I1):** the detail page hides the Danger zone when `workflow.scope === "org"`, whatever `readOnly` says. Its Delete calls `DELETE /api/workflows/[id]` (`:292`), which only loads `scope: "user"` rows and would 404. Org copies are deleted from the preset editor, which uses `DELETE /api/org-items/[kind]/[id]`.

- [ ] **Step 1: Write the failing tests.**
  - `route.test.ts`:
    - `owner assigned to the preset gets managed editable view`: `readOnly` is false and `managed` is true;
    - `member assigned to the preset still gets readOnly`.
  - `WorkflowDetailClient.test.tsx`: `managed org workflow detail shows Edit but no Delete`. GET returns `{ scope: "org", readOnly: false, managed: true }`; the edit control is present, and the `wf.detail.dangerZone` heading and delete button are absent.
  - New isolation case `workflow.get-managed-foreign`: the owner of org B GETs org A's org workflow id → 404 with the not-found body. Add it to the GET `proven(...)` list.
- [ ] **Step 2: Run them and see them fail.** `npm test -- "src/app/api/workflows/[id]/route.test.ts" src/components/workflows/WorkflowDetailClient.test.tsx` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass.** Also `npm run test:int -- src/test/isolation` → PASS. `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `fix(workflows): owner/admin opens the org copy editable even when assigned`

### Task 4: Friendly preview errors (A5)

**Files:**
- Create: `src/lib/intel/preview-failure.ts`
- Modify: `src/lib/intel/workflow-preview.ts:63-118`, `src/app/api/intel/findings/[id]/workflow-actions/route.ts:25-35`, `src/app/api/intel/findings/[id]/workflow-actions/[runId]/route.ts` (reload path)
- Modify: `src/components/intel/detail/WorkflowActionDialog.tsx:52-59,115-135`, `src/i18n/dictionaries/intel.ts`
- Test: `src/lib/intel/preview-failure.test.ts`, `src/components/intel/detail/WorkflowActionDialog.test.tsx`, `src/lib/intel/actions/workflow-actions.int.test.ts`

**Interfaces:**
- Produces:
  - `export type PreviewFailureReason = "agent_prompt_empty" | "connector_not_connected" | "provider_error" | "unknown"`
  - `export function previewFailureOf(rawError: string | null | undefined, graph: WorkflowGraph): { reason: PreviewFailureReason; app?: string }`
    - `connector_not_connected` when `notConnectedName(rawError)` (`src/components/workflows/workflowError.ts:6`, reused, Rule 11) returns a name. `app` is that name exactly as the error carries it (`not_connected:Gmail` → "Gmail"); there is no lookup.
    - `agent_prompt_empty` when `savabilityIssues(graph)` has that code.
    - `provider_error` when the text matches a provider HTTP failure (`/\b(4\d\d|5\d\d)\b|anthropic|openai|byteplus/i`).
    - Otherwise `unknown`.
- Wire changes:
  - **Preview success with `status: "failed"`:** `{ runId, status, reason, app?, pendingWrites }`. The raw `error` field is removed from the response.
  - **Start failure:** `{ error: "Run failed to start", code: "run_failed", reason, app? }` with the same status as today.
  - **Logging:** `console.error("[intel] preview failed", runId ?? "-", rawError)` on the server. The raw text appears only there.
  - **Pre-check:** before starting the run, a graph whose `savabilityIssues` include `agent_prompt_empty` returns 422 `{ code: "run_failed", reason: "agent_prompt_empty" }` and makes no model call. It runs after the `unavailable` and `graph_not_allowed` gates, so it never reveals anything about a workflow the caller cannot use.
- Dialog: shows `t("intel.wf.fail." + reason, { app })`.
  - Reuse what exists: the dialog's `intel.wf.err.connect` mapping for `connector_not_connected` (`WorkflowActionDialog.tsx:57`) and `ownerStepError` for step errors. Add only the missing reasons.
  - VI `agent_prompt_empty` = "Bước AI chưa có nội dung yêu cầu".
  - VI `connector_not_connected` = "Không kết nối được {app}".
  - VI `provider_error` = "Dịch vụ AI đang lỗi, thử lại sau ít phút".
  - VI `unknown` = "Chưa chuẩn bị được bản xem trước".

- [ ] **Step 1: Write the failing tests.**
  - `preview-failure.test.ts`: one case per reason, including `"not_connected:Gmail"` → `{ reason: "connector_not_connected", app: "Gmail" }`, and `"messages: at least one message is required (400)"` → `provider_error`.
  - Dialog:
    - `failed preview shows the reason text, never the raw error`: the mock returns `{ status: "failed", reason: "connector_not_connected", app: "Gmail" }`, the dialog shows "Không kết nối được Gmail", and the text "not_connected" is absent;
    - `run_failed start error shows the reason`.
  - Int:
    - `empty-prompt workflow preview returns 422 agent_prompt_empty and creates no run`;
    - `empty-prompt workflow the caller cannot use answers the unavailable/not-allowed error, not agent_prompt_empty`.
- [ ] **Step 2: Run them and see them fail.** `npm test -- src/lib/intel/preview-failure.test.ts src/components/intel/detail/WorkflowActionDialog.test.tsx` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npm run test:int -- src/lib/intel/actions/workflow-actions.int.test.ts` and `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `fix(intel): readable workflow preview failures; raw provider text logged only`

### Task 5: Share dialog — graph order + "existing copy" note (A6)

**Files:**
- Modify: `src/lib/workflow/validate.ts` (add `topoOrder`), `src/lib/presets/graph-insight.ts:107-135` (`walkSteps`)
- Create: `src/lib/presets/existing-copies.ts`
- Modify: `src/app/api/workflows/[id]/insight/route.ts`, `src/components/presets/ShareToPresetDialog.tsx`, `src/i18n/dictionaries/presets-dialogs.ts`
- Test: `src/lib/workflow/validate.test.ts`, `src/lib/presets/graph-insight.pure.test.ts`, `src/lib/presets/existing-copies.int.test.ts`, `src/components/presets/ShareToPresetDialog.test.tsx`

**Interfaces:**
- Produces:
  - `export function topoOrder(graph: WorkflowGraph): WfNode[]` (validate.ts):
    - Kahn order; ties keep `graph.nodes` order;
    - nodes left in a cycle are appended in array order;
    - never throws.
  - `export async function existingOrgCopies(db: Db, orgId: string, name: string): Promise<{ workflowId: string; presetId: string; presetName: string }[]>`. Returns org-scope workflows of `orgId` with exactly `name` that appear in a `preset_item` (`itemType = "workflow"`).
  - Insight response gains `existingCopies` (that array).
- Dialog: when the selected target preset has an entry in `existingCopies`, it shows `share.existingCopy` ("Đã có bản trong bộ công cụ — mở bản đó để sửa") linking to `/workflows/<workflowId>`. It is a note only, and Confirm stays enabled (§4).

- [ ] **Step 1: Write the failing tests.**
  - `topoOrder follows edges when nodes array is reversed`, and `topoOrder never throws on a cycle`.
  - `graph-insight.pure.test`: `steps follow edge order: AI step before email step` (the graph lists the gmail node first).
  - `existing-copies.int.test`:
    - `lists the org copy with the same name in its preset`;
    - `another org's copy with the same name is not listed`.
  - Dialog: `shows existing copy note with link for the chosen preset`.
- [ ] **Step 2: Run them and see them fail.** `npm test -- src/lib/workflow/validate.test.ts src/lib/presets/graph-insight.pure.test.ts src/components/presets/ShareToPresetDialog.test.tsx` → FAIL.
- [ ] **Step 3: Implement.** `walkSteps` iterates `topoOrder(graph)` instead of `graph.nodes`. `summarizeWorkflow`'s other callers (`builder.ts`, `duplicate.ts`, `test-run.ts`) only gain correct order.
- [ ] **Step 4: Run them and see them pass**, plus `npm run test:int -- src/lib/presets/existing-copies.int.test.ts src/lib/presets/graph-insight.test.ts` and `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `fix(presets): share dialog lists steps in graph order and points at an existing copy`

### Task 6: Workflow detail page — personal hint, footer clearance, plain labels (A7, A8, D7)

**Files:**
- Modify: `src/components/workflows/WorkflowDetailClient.tsx` (`<main>` at line 488; the section at 643-648; a hint for personal workflows)
- Modify: `src/components/workflows/FindingActionCard.tsx:131-151`, `src/lib/workflow/finding-action-options.ts:16-33`, `src/i18n/dictionaries/workflows.ts`
- Test: `src/components/workflows/FindingActionCard.test.tsx`, `src/lib/workflow/finding-action-options.test.ts`, `src/components/workflows/WorkflowDetailClient.test.tsx`

**Interfaces:**
- Produces: `FindingActionOptions.rules: { ruleId: string; name: string; nameVi: string | null }[]`. `nameVi` comes from `rule.text?.vi?.name`. The GET finding-action route passes it through unchanged.

**Changes:**
- **A7:** for `workflow.scope === "user"` and `canManagePresets`, show `wf.fa.personalHint` under the graph: "Muốn dùng làm nút trên trang phát hiện? Thêm vào bộ công cụ của tổ chức trước."
- **A8:** `<main>` bottom padding goes from `md:pb-8` to `md:pb-16`. The RightNav is `h-11` = 2.75rem (`RightNav.tsx:110`), so the "Lưu" button is no longer covered.
- **D7:**
  - Rule rows show `lang === "vi" ? nameVi ?? name : name`, with `ruleId` small and muted.
  - `wf.fa.scope` VI → "Dùng cho"; options become "một phiếu" / "nhiều phiếu" / "cả hai".
  - `wf.run.dryRun` VI → "Xem trước".
  - `wf.fa.title` VI → "Hiện thành nút trên trang phát hiện".
  - Update en/zh equivalents.

- [ ] **Step 1: Write the failing tests.**
  - `options return nameVi from rule text`.
  - Card (vi):
    - `rule row shows Vietnamese name with code small`;
    - `scope select reads Dùng cho with một phiếu / nhiều phiếu / cả hai`.
  - `WorkflowDetailClient.test.tsx`: `main has md:pb-16 so the footer does not cover Lưu` (a class assertion; E2E row 4 checks the real clearance).
- [ ] **Step 2: Run them and see them fail.** `npm test -- src/components/workflows/FindingActionCard.test.tsx src/lib/workflow/finding-action-options.test.ts src/components/workflows/WorkflowDetailClient.test.tsx` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `fix(workflows): finding-action card wording, personal hint, footer clearance`

## Track B — Task reminders (bell + email)

### Task 7: Due dates at end of day in the project time zone (B6)

**Files:**
- Modify: `src/lib/intel/time.ts` (export `endOfLocalDay`, built on the private `zonedInstant` + `addDays` + `dayMs`)
- Modify: `src/lib/intel/actions.ts:38-47` (`Actor`), `:250-256` (`endOfDayUtc` → `dueAtOf`), `:311`
- Modify: `src/lib/intel/scoped.ts:77` (`actorOf` sets `timeZone: ctx.bp.timezone`)
- Test: `src/lib/intel/time.test.ts`, `src/lib/intel/actions.test.ts`

**Interfaces:**
- Existing tz helpers (named in the spec request): `src/lib/intel/time.ts` exports `localDate(now, timeZone)` (YYYY-MM-DD in zone) and `nextRunInTimeZone`. It keeps `wallClock` / `zonedInstant` private. There is no exported end-of-day helper, so this task adds one.
- Produces:
  - `export function endOfLocalDay(day: string, timeZone: string): Date`. Equals the instant of local midnight of `addDays(day, 1)` minus 1 ms. It throws `RangeError` on a bad day or zone.
  - `Actor.timeZone?: string` (default `"UTC"` when absent, so existing fixtures keep today's behaviour).
  - `planCreateTask` stores `dueAt = dueAtOf(input.dueDate, a.timeZone ?? "UTC")`. This keeps today's `InputError` messages for a malformed or unreal date.
- Existing rows are not rewritten (§5 B6).

- [ ] **Step 1: Write the failing tests.**
  - `endOfLocalDay New York`: `("2026-11-20","America/New_York")` → `2026-11-21T04:59:59.999Z`.
  - `endOfLocalDay Ho Chi Minh`: → `2026-11-20T16:59:59.999Z`.
  - `endOfLocalDay across spring-forward`: `("2026-03-08","America/New_York")` → `2026-03-09T03:59:59.999Z`.
  - `planCreateTask stores dueAt at end of the due day in the project zone`: actor `timeZone: "America/New_York"`; and `no zone keeps UTC end of day`.
- [ ] **Step 2: Run them and see them fail.** `npm test -- src/lib/intel/time.test.ts src/lib/intel/actions.test.ts` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npm test -- src/lib/intel` (callers of `planCreateTask`) and `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(intel): task due date ends at the project's local midnight`

### Task 8: Task notices (bell + email) and the assignment notice (B1, B4)

**Files:**
- Modify: `src/lib/intel/actions/reminders.ts` (export `recipientAccess`; `recipientCanSee` is built on it)
- Create: `src/lib/intel/task-notices.ts`, `src/lib/intel/task-mail.ts`
- Modify: `src/lib/intel/finding-actions.ts:130-138` (`executeCreateTask`)
- Modify: `src/i18n/dictionaries/notifications.ts` (`notif.msg.task.assigned|dueSoon|overdue.title`, with params `{title}` and `{day}`)
  - VI assigned = "Bạn được giao việc: {title}, hạn {day}" (§5 B1); a variant without "hạn" when there is no due date.
  - VI dueSoon = "Việc sắp đến hạn ngày mai: {title}".
  - VI overdue = "Việc đã quá hạn: {title}".
  - The email uses the same text, plus the finding link.
- Test: `src/lib/intel/task-mail.test.ts`, `src/lib/intel/task-notices.test.ts`, `src/lib/intel/task-assign-notice.int.test.ts`

**Interfaces:**
- Consumes: Task 10 `dueDayOf` (`src/lib/intel/time.ts`). Run Task 10 first.
- Produces:
  - `export async function recipientAccess(db: Db, userId: string, findingId: string): Promise<{ wordingVisible: boolean } | null>`. Returns null when the user is disabled or cannot see the finding; `wordingVisible` uses the same rule as `finding-actions.ts` (`scopeFinding(...).mode === "full" && !comparisonHidden`).
  - `export type TaskNoticeKind = "task_assigned" | "task_due_soon" | "task_overdue"`
  - `export function taskNoticeKey(kind: TaskNoticeKind, taskId: string, userId: string, dueAt: Date | null): string` = `` `${kind}:${taskId}:${userId}:${dueAt?.toISOString() ?? "none"}` `` (§8).
  - `export type TaskNotice = { kind: TaskNoticeKind; userId: string; taskId: string; findingId: string; taskTitle: string; dueAt: Date | null; timeZone: string }`. There is no `findingWording` field: the title rule below does not compare against it.
  - `export async function sendTaskNotice(db: Db, n: TaskNotice): Promise<{ bell: boolean; mailed: boolean }>`. It never throws (logs instead). Its order:
    1. If a notification with the key already exists, return.
    2. Check `recipientAccess`.
    3. Choose the title (controller, I0): `NEUTRAL_REMINDER_TITLE` whenever `wordingVisible === false`, whatever `taskTitle` is; otherwise `taskTitle`. A default-titled task stores the finding wording verbatim, and every analysis run can rewrite `findings.wording` (`store/repo.ts:181-183`), so title equality would miss a stale wording after a pack upgrade. Hiding a hand-typed title from a restricted reader is accepted (the spec allows the neutral title).
    4. Call `createOnce` with i18n `{ key: "task.<assigned|dueSoon|overdue>", params: { title, day } }` and link `/home/findings/<id>`.
    5. Only when `createOnce` returned a row: read the recipient's email + `userProfiles.replyLanguage` (default vi), then `sendMail(taskMail(...))`.
  - `export async function mailTaskReminder(db: Db, n: { userId: string; findingId: string; title: string; neutral: boolean }): Promise<boolean>`. This is the email-only path for pack reminders (used in Task 9).
  - `export function taskMail(kind: TaskNoticeKind | "task_reminder", lang: "vi" | "en" | "zh", v: { title: string; day: string | null; link: string | null }): Mail`. HTML-escapes the title. Same style as the password-reset mail.
  - `export function findingLink(findingId: string, env?: NodeJS.ProcessEnv): string | null`. Built from the `AUTH_URL` origin, never from a request (`resetLink` pattern); null when unset.
  - `day` = `formatDay(dueDayOf(dueAt, timeZone), locale)` in the recipient's locale, or null when `dueAt` is null. `dueDayOf` comes from Task 10 (I2), so the email day equals the card day, legacy rows included. Never format the instant with `Intl` in the zone: a legacy `23:59:59.000Z` row would show the next day in Ho Chi Minh.
  - **Open tasks include `pending_approval`** (`TASK_OPEN_STATUSES`, `lifecycle.ts:8`). Following the spec literally, such tasks get the assignment notice and the deadline notices like `assigned` ones. This is flagged as an owner question in the task report; no exclusion is invented here.
  - Mail not configured (Resend is not set up yet; owner, 2026-11-20). Before calling `sendMail`, task mail checks `RESEND_API_KEY` and `MAIL_FROM`.
    - When either is unset, it skips the call and returns `mailed: false`.
    - It logs `[mail] not configured; task notices are bell-only` once per process (a module-level flag), not once per mail.
    - `sendMail` itself is unchanged, so password reset behaves as before.
- **B1 hook:** after `commitPlan` in `executeCreateTask`, when `ownerUserId !== creator`, call `void sendTaskNotice(db, …).catch(log)`. This is fire-and-forget: the HTTP and chat responses never wait on Resend. It covers the detail, bulk and chat paths (the only create path, §8 "bulk and workflow-created tasks").

- [ ] **Step 1: Write the failing tests.**
  - Mail tests (here and in `task-assign-notice.int.test.ts`): set `RESEND_API_KEY` and `MAIL_FROM` with `vi.stubEnv`, otherwise task mail stops before `sendMail` and a "one mail" assertion fails for the wrong reason. Call `vi.resetModules()` per test so the "logged once" flag starts clean.
  - `task-notices.test.ts` (mocks: `@/lib/mail/resend`, `@/lib/notifications` `createOnce`, `./actions/reminders` `recipientAccess`, and a db stub for email/lang):
    - `assigned notice creates bell and one mail in recipient language`: `sendMail` is called once; `to` is the user's email; the subject is in en when `replyLanguage = "en"`.
    - `no mail when createOnce returns null`.
    - `mail failure still reports bell and does not throw`: `sendMail` rejects, and the result is `{ bell: true, mailed: false }`.
    - `recipient who cannot see the finding gets nothing`: neither `createOnce` nor `sendMail` is called.
    - `default-titled task is neutral for a recipient without wording, even after the wording changed`: the task title is the old wording "A" and the finding's current wording is "B"; with `wordingVisible: false`, the mail text and the bell title contain `NEUTRAL_REMINDER_TITLE`, and neither "A" nor "B".
    - `hand-typed title is neutral for a recipient without wording`: a title unrelated to any wording, `wordingVisible: false` → `NEUTRAL_REMINDER_TITLE`.
    - `task title is shown when wording is visible`.
    - `email day equals the card day for a legacy Vietnam row`: `dueAt = 2026-11-20T23:59:59.000Z`, `timeZone = "Asia/Ho_Chi_Minh"` → the mail and bell `day` is 20/11, not 21/11.
    - `unconfigured mail is bell-only and logs once`. With `RESEND_API_KEY` unset, two notices both return `{ bell: true, mailed: false }`, `sendMail` is never called, and the "not configured" log line appears exactly once.
    - `dedupe key includes dueAt`: `taskNoticeKey("task_due_soon", "t1", "u1", new Date("2026-11-21T04:59:59.999Z"))` equals `"task_due_soon:t1:u1:2026-11-21T04:59:59.999Z"`, and with `dueAt` null it ends in `":none"`.
  - `task-mail.test.ts`:
    - `link uses AUTH_URL origin`;
    - `no link when AUTH_URL unset`;
    - `title is HTML-escaped`;
    - `vi is the default language`.
  - `task-assign-notice.int.test.ts`:
    - `creating a task for another user writes one task_assigned notification and calls sendMail once` (wait with `vi.waitFor`);
    - `self-assigned task writes none`.
- [ ] **Step 2: Run them and see them fail.** `npm test -- src/lib/intel/task-notices.test.ts src/lib/intel/task-mail.test.ts` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npm run test:int -- src/lib/intel/task-assign-notice.int.test.ts src/lib/intel/actions/reminders.int.test.ts src/lib/intel/finding-actions.int.test.ts` and `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(intel): task assignment notice by bell and email`

### Task 9: Deadline sweep (due soon, overdue) + email for pack reminders (B2, B3, B7)

**Files:**
- Create: `src/lib/intel/actions/deadline-sweep.ts`
- Modify: `src/lib/intel/actions/reminders.ts` (`sweepFindingReminders`: collect the newly notified rows and mail them after the transaction returns)
- Modify: `src/app/api/workflows/tick/route.ts:60-68` (its own isolated try/catch; response gains `deadlines`)
- Test: `src/lib/intel/actions/deadline-sweep.int.test.ts`, `src/lib/intel/actions/reminders.int.test.ts`, `src/app/api/workflows/tick/route.test.ts`

**Interfaces:**
- Consumes: Task 8 `sendTaskNotice`, `mailTaskReminder`; Task 7 zone-aware `dueAt`.
- Produces:
  - `export const OVERDUE_LOOKBACK_DAYS = 14`
  - `export async function sweepTaskDeadlines(db: Db, now: Date): Promise<{ dueSoon: number; overdue: number }>`
- Candidates (one SQL query, `LIMIT 100` per kind, like `sweepFindingReminders`):
  - tasks with status in `TASK_OPEN_STATUSES` (includes `pending_approval`, see Task 8);
  - `dueAt` not null and `findingId` not null (`tasks.findingId` is nullable, `schema.ts:1431`, and `recipientAccess` needs it);
  - `now − 14d < dueAt <= now + 24h`;
  - an anti-join on `notifications.dedupeKey` drops tasks whose notice key for this (kind, person, dueAt) already exists, so a task already notified is not re-read every minute;
  - selects `createdAt`, and joins `business_project.timezone`. No `findings.wording` join: the title rule (Task 8, I0) does not need it.
- Notices:
  - **Due soon** when `now < dueAt <= now + 24h` **and** `createdAt < dueAt − 24h`: the owner gets `task_due_soon`. A task created inside the 24h window gets none, because its assignment notice already named the day (controller, I7).
  - **Overdue** when `dueAt <= now`: the owner and `createdBy` (when different and non-null) each get `task_overdue`, once per (task, person, dueAt). Admins are not notified (§8).
  - A task with no owner sends to `createdBy` only, for overdue.
  - Each send is awaited one by one. A failure is logged and the loop continues.
- Pack reminders: email only for rows whose `notifyFindingReminder` returned a row, sent after the transaction. The bell behaviour is unchanged.
  - Accepted loss (documented next to B4 in a code comment): `createOnce` writes the bell row with the global `db` (`notifications/index.ts:83-104`), outside the sweep transaction. If the transaction throws after a notify, the collected mail list is discarded, and the next sweep's `createOnce` returns null, so that one email is never sent. The bell still shows it.
- **First tick after deploy:** every open task that went overdue in the last 14 days gets its overdue notice once. This is bounded by `OVERDUE_LOOKBACK_DAYS`; confirm with the owner before deploy (Task 18 checklist).

- [ ] **Step 1: Write the failing tests** (`vi.mock("@/lib/mail/resend")`, plus `vi.stubEnv` for `RESEND_API_KEY` / `MAIL_FROM` as in Task 8). Fixtures backdate `createdAt` (e.g. `now − 2d`) unless a test says otherwise, so the I7 rule does not hide the due-soon notice.
  - `task due in 23h gets one due-soon notice to owner; second sweep sends none`. Assert one notification row and `sendMail` called once across two sweeps.
  - `task created inside the 24h window gets no due-soon notice`: `createdAt = now − 1h`, `dueAt = now + 20h` → no `task_due_soon` row and no mail.
  - `task due in 25h gets nothing`.
  - `overdue task notifies owner and creator once each; not again next tick`.
  - `changed dueAt re-arms the due-soon notice` (`createdAt` backdated before both due dates).
  - `task without a finding is skipped`.
  - `closed task gets nothing`.
  - `overdue beyond lookback gets nothing` (Review Focus 1).
  - `mail failure does not stop the sweep`: `sendMail` rejects for the first task, and the second task is still notified.
  - In `reminders.int.test`: `pack reminder sends one email after commit and none on the next sweep`.
  - In `tick/route.test`: `deadline sweep failure does not fail the tick`. The mocked sweep throws, the response is 200, and `deadlines.error` is set.
- [ ] **Step 2: Run them and see them fail.** `npm run test:int -- src/lib/intel/actions/deadline-sweep.int.test.ts` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npm run test:int -- src/lib/intel/actions/reminders.int.test.ts`, `npm test -- src/app/api/workflows/tick/route.test.ts` and `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(intel): due-soon and overdue task notices; email for pack reminders`

### Task 10: Task card shows due day, "Quá hạn" and "Sẽ nhắc" (B5)

**Priority: run next.** Task 7 has landed (`ff8687b0`), so on this branch the home card (`home/derive.ts:163`) and the task card (`TaskPanel.tsx:159`) already show the UTC date of a zone-aware `dueAt`: a New York task due 2026-11-20 shows 11/21. Those are live regressions until this task lands. Task 8 also consumes `dueDayOf` from here.

**Files:**
- Create: `src/lib/intel/actions/next-reminder.ts`
- Modify: `src/lib/intel/time.ts` (add `dueDayOf`)
- Modify: `src/lib/intel/http.ts:170-189` (`taskDto`), `src/lib/intel/home/load.ts:~435` (load pending pack reminders per task in one query; pass `bp.timezone` to the `CardTask` builder), the task create/decision/complete routes (pass `timeZone`)
- Modify: `src/components/intel/detail/TaskPanel.tsx:156-160` (line 159 reads `newest.dueAt.slice(0, 10)`; it reads `newest.dueDay` instead), `src/i18n/dictionaries/intel.ts`
- Modify (added after the Task 7 review): `src/lib/intel/home/derive.ts:162-163`.
  - Today the home card's `dueDay` is the UTC date of `dueAt` (`task.dueAt.toISOString().slice(0, 10)`). Make it `dueDayOf(task.dueAt, projectTimeZone)`, passing the zone in from `load.ts`. Replace the stale comment "stored as the end of the chosen day in UTC".
  - These two are the only `dueAt…slice(0, 10)` sites in `src` (grep, 2026-11-20). Re-grep before closing the task.
- Test: `src/lib/intel/time.test.ts`, `src/lib/intel/actions/next-reminder.test.ts`, `src/lib/intel/http.test.ts`, `src/components/intel/detail/TaskPanel.test.tsx`, `src/lib/intel/home/derive.test.ts`.

**Interfaces:**
- Produces:
  - `export function dueDayOf(dueAt: Date, timeZone: string): string` (time.ts, YYYY-MM-DD; controller, I2):
    - a legacy row, stored before Task 7 as UTC `23:59:59.000` (the old `endOfDayUtc`), returns its UTC date;
    - any other value returns `localDate(dueAt, timeZone)`;
    - new rows end in `.999`, so they never match the legacy rule.
    - Used by `taskDto`, the home card (`derive.ts`), and Task 8's email/bell `day`.
  - `export type NextReminder = { kind: "pack" | "due_soon" | "overdue"; at: string }`
  - `export function nextReminderOf(task: { status: string; dueAt: Date | null }, pendingPackAt: readonly Date[], now: Date): NextReminder | null`. Rules:
    - a closed task → null;
    - candidates:
      - each pending pack date (a past one counts as `now`);
      - `due_soon` at `dueAt − 24h` when `now < dueAt − 24h`;
      - `overdue` at `dueAt` when `now < dueAt`;
    - the earliest wins.
    - The I7 rule (Task 9: no due-soon for a task created inside the 24h window) needs no extra input: such a task has `now >= createdAt >= dueAt − 24h`, so the `due_soon` candidate never appears. A test pins it.
  - `taskDto(t, ownerName, itemCount?, opts?: { timeZone?: string; nextReminder?: NextReminder | null; now?: Date })` adds `dueDay: string | null` (= `dueDayOf(dueAt, timeZone ?? "UTC")`), `overdue: boolean` and `nextReminder`.
- Card:
  - shows the due day from `dueDay`;
  - shows an "Quá hạn" chip when `overdue`;
  - shows a "Sẽ nhắc: …" line. `due_soon` → "1 ngày trước hạn", `overdue` → "khi quá hạn", `pack` → "ngày {day}".

- [ ] **Step 1: Write the failing tests.**
  - `time.test`:
    - `legacy UTC row keeps its day in Ho Chi Minh`: `dueDayOf(new Date("2026-11-20T23:59:59.000Z"), "Asia/Ho_Chi_Minh") === "2026-11-20"` (plain `localDate` would give `2026-11-21`);
    - `new row uses the project-zone day`: `dueDayOf(new Date("2026-11-20T16:59:59.999Z"), "Asia/Ho_Chi_Minh") === "2026-11-20"`.
  - `next-reminder.test`: closed → null; due in 3 days → `due_soon` at dueAt−24h; due in 10h → `overdue`; a pack date earlier than due-soon wins; past due → null; `task created 1h ago and due in 20h promises overdue, not due_soon`.
  - `http.test`: `dueDay is the project-zone day` (a New York `dueAt` of `2026-11-21T04:59:59.999Z` gives `"2026-11-20"`).
  - `derive.test`: `home card due day is the project-zone day` (a New York task due 2026-11-20 shows 20/11, not 21/11) and `home card keeps a legacy Vietnam row's day`.
  - `TaskPanel.test`: `overdue task shows Quá hạn`; `shows Sẽ nhắc: 1 ngày trước hạn`; `due day comes from dueDay, not the UTC date of dueAt`.
- [ ] **Step 2: Run them and see them fail.** `npm test -- src/lib/intel/time.test.ts src/lib/intel/actions/next-reminder.test.ts src/lib/intel/http.test.ts src/components/intel/detail/TaskPanel.test.tsx src/lib/intel/home/derive.test.ts` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npm run test:int -- src/lib/intel/home` and `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(intel): task card shows due day, overdue and next reminder`

## Track C — "Dựng bằng AI" finding-action mode

The "Dựng bằng AI" sidebar tab (`wf.sidebar.tabAi`) renders `AiChatPanel` → `POST /api/workflows/generate/chat`. The one-shot `AiGeneratePanel` → `POST /api/workflows/generate` takes the same flag.

### Task 11: Toggle and variable hints (C1, C4)

**Files:**
- Create: `src/lib/workflow/finding-vars.ts` (client-safe; moves `FINDING_KEYS` out of `variableHints.ts:3`)
- Modify: `src/components/workflows/editor/variableHints.ts`, `AiChatPanel.tsx` (bodies at lines 232 and 336), `AiGeneratePanel.tsx:42`, `WorkflowEditor.tsx` (state, the props at 1257 and 1332, and the `findingAction` passed to `NodeConfigPanel`), `src/i18n/dictionaries/workflows.ts`
- Test: `src/components/workflows/editor/AiChatPanel.test.tsx`, `AiGeneratePanel.test.tsx`, `variableHints.test.ts`, `WorkflowEditor.test.tsx`

**Interfaces:**
- Produces:
  - `export const FINDING_KEYS = ["id","ruleId","metricKey","dims","severity","variancePct","title"] as const`
  - `export function findingVarCatalogue(fields: readonly { key: string }[]): string[]`. Returns `{{trigger.finding.<k>}}` for each key, then `{{trigger.items}}`, `{{trigger.params.<key>}}` per field, and `{{me.email}}`.
  - `AiChatPanel` / `AiGeneratePanel` props: `findingMode: boolean; onFindingModeChange: (v: boolean) => void`. Every authoring request body the client sends carries `findingAction: findingMode` (generate, generate/chat, append-write). `generate/compile` has no client caller (only `route-inventory.ts:665`), so its flag is server-side only (Task 13).
  - Editor state `aiFindingMode`. It starts `true` when the loaded workflow has finding-action config (`wf.findingAction != null`), else `false`.
  - Hints get `findingAction ?? (aiFindingMode ? { fields: [] } : null)` (C4).
- Checkbox label `wf.ai.findingMode`: "Workflow này chạy từ một phát hiện".

- [ ] **Step 1: Write the failing tests.**
  - `toggle on sends findingAction true to generate/chat`.
  - `WorkflowEditor.test.tsx`: `AI panel finding toggle starts checked when the workflow has findingAction` (GET returns `findingAction` → the checkbox is checked), and `starts unchecked without findingAction`. This tests the editor's own rule, not a controlled prop.
  - `append-write body carries findingAction`.
  - The `variableHints` test still passes, importing `FINDING_KEYS` from `finding-vars`.
  - New: `findingVarCatalogue lists me.email and trigger.items`.
- [ ] **Step 2: Run them and see them fail.** `npm test -- src/components/workflows/editor/AiChatPanel.test.tsx src/components/workflows/editor/AiGeneratePanel.test.tsx src/components/workflows/editor/variableHints.test.ts src/components/workflows/editor/WorkflowEditor.test.tsx` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(workflow-editor): "runs from a finding" toggle and trigger hints`

### Task 12: Readable node ids (C3)

**Choice (controller, I5).** Readable ids must not break chat provenance. `provenanceOf` (`provenance.ts:46-59`) treats the canvas as the assistant's own work only when its agent-node ids equal the ids of `agentWorkGraph(prevSteps)`. Those ids come from `stepId` → `n1…` (`authorAppend.ts:224`). A rename pass after the build would make provenance `"unknown"` on every later turn, and `canBuild` (`chat/route.ts:761`) would turn false: no rebuild from the conversation, and human edits no longer tracked.
- **Chosen:** the chat path builds readable ids directly. `agentWorkGraph` takes an `idOf` parameter (it already holds `const idOf = stepId` locally), and `provenanceOf` takes the same `idOf`, so the build and the provenance check always agree. The ids are positional and kind-based (`tom-tat`, `tom-tat-2`, …), so they stay stable across rebuilds with no rename pass and no `keep` set.
- **Not chosen:** readable ids only where provenance is unused. The "Dựng bằng AI" tab is the chat route, and E2E row 1 expects readable ids there.
- `renameNodeIds` is used only where provenance does not look: the one-shot `generate` route, and the new non-agent nodes that append-write adds (Task 13).
- Never rename `report`: `workNodes` excludes it by id (`provenance.ts:31-35`).
- Switching the toggle mid-conversation changes `idOf`. A canvas built under the other mode then reads as `"unknown"` and is left as it is, unless it is empty or the user asks for a redraw. This is accepted.

**Files:**
- Create: `src/lib/workflow/node-ids.ts`
- Modify: `src/lib/workflow/authorAppend.ts` (`agentWorkGraph` at :217 gains `idOf`; `appendBranch` at :290 and the new `nodeAtStep`)
- Modify: `src/lib/workflow/provenance.ts` (`provenanceOf` at :46 gains `idOf`)
- Modify: `src/app/api/workflows/generate/append-write/route.ts:26` (`validatedBranch` uses `nodeAtStep`)
- Test: `src/lib/workflow/node-ids.test.ts`, `src/lib/workflow/authorAppend.test.ts`, `src/lib/workflow/provenance.test.ts`, `src/app/api/workflows/generate/append-write/route.test.ts`

**Interfaces:**
- Consumes: Task 5 `topoOrder` (numbering order in `readableIdMap`); `stepRefsOf`/`STEP_REF` (validate.ts).
- Produces:
  - `export function slugify(label: string): string`:
    - NFD, then strip `\p{M}`, `đ/Đ → d`, lowercase;
    - runs of non-`[a-z0-9]` become `-`;
    - trim dashes; empty → `"buoc"`.
  - `export function findingStepId(i: number): string` = `i === 0 ? "tom-tat" : "tom-tat-" + (i + 1)`. The finding-mode `idOf` for `agentWorkGraph` (every node it builds is a non-extract agent).
  - `export function readableIdOf(node: WfNode): string`. Base ids (spec §8 C3 allows "kind or purpose label"; ids are kind-based):

    | Node | Base id |
    |------|---------|
    | agent with `extract` | `trich-xuat` |
    | other agent | `tom-tat` |
    | connector `gmail_send` | `gui-email` |
    | other connector write | `ghi-<slug(connectorId)>` |
    | connector read | `doc-<slug(connectorId)>` |
    | mcp | `mcp-<slug(tool)>` |
    | condition | `kiem-tra` |
    | foreach | `lap` |
  - `export function readableIdMap(graph: WorkflowGraph, keep: ReadonlySet<string>): Map<string, string>`:
    - old → new for every node not in `keep`, foreach bodies included;
    - unique against kept ids and each other by suffix `-2`, `-3`.
  - `export function renameNodeIds(graph: WorkflowGraph, map: ReadonlyMap<string, string>): WorkflowGraph`. Returns a new graph that rewrites:
    - node ids and edges;
    - `extract.from`;
    - `{{steps.<id>` in every string sink (agent `prompt`/`system`, connector/mcp `args` deep, condition `when` left/right, foreach `items`);
    - `positions` keys;
    - foreach bodies, recursively.
  - `agentWorkGraph(steps, lang?, idOf: (i: number) => string = stepId)`. Default behaviour is unchanged.
  - `provenanceOf(current, prevSteps, idOf: (i: number) => string = stepId)`. Passes `idOf` to `agentWorkGraph`.
  - `export function nodeAtStep(graph: WorkflowGraph, onStep: number): WfNode | undefined` (in `authorAppend.ts`) = the node whose id is `stepId(onStep - 1)`, else the node whose id is `findingStepId(onStep - 1)`. Both schemes are positional, so the append-write route, which has no steps, can still find the decider. Not `topoOrder`: independent steps (no `needsPrevious`) would be reordered. `validatedBranch` and `appendBranch` both use it.
- Where each is applied (wiring in Task 13):
  - chat: `agentWorkGraph(tasks.steps, lang, findingStepId)` and `provenanceOf(current, prevSteps, findingStepId)` when `findingAction` is on. After the rebuild re-attaches the write (`appendWrite` / `appendBranch` in `chat/route.ts:~800-815`), rename its non-agent nodes with `readableIdMap(graph, keep)`, `keep` = the agent ids plus `"report"`, so a confirmed write keeps `gui-email` across turns (provenance only reads agent ids);
  - one-shot generate: `renameNodeIds(graph, readableIdMap(graph, new Set()))`;
  - append-write: `readableIdMap(graph, keep)` with `keep` = the ids in `current` plus `"report"`, so only the new write and condition nodes are renamed (`gui-email`, `kiem-tra`).
  - Always before any verify, and before the response.

- [ ] **Step 1: Write the failing tests.**
  - `node-ids.test`:
    - `renames refs in prompt, args, extract.from, edges, positions and foreach body`;
    - `collision gets -2 and -3`;
    - `kept ids are untouched`;
    - `slugify("Gửi email") === "gui-email"` and `slugify("Đơn hàng") === "don-hang"`;
    - `renamed graph passes assertRunnable when the input did`;
    - `input graph is not mutated`.
  - `authorAppend.test`:
    - `agentWorkGraph with findingStepId names steps tom-tat, tom-tat-2 and wires {{steps.tom-tat.output}}`;
    - `agentWorkGraph without idOf still names n1, n2`;
    - `nodeAtStep finds n2 and tom-tat-2 for onStep 2`.
  - `provenance.test`: `finding-mode turn 2 still sees the canvas as assistant-authored`: a canvas built by `agentWorkGraph(steps, "vi", findingStepId)` → `provenanceOf(canvas, steps, findingStepId)` is `{ kind: "assistant" }`; with one prompt changed it is `edited`.
  - append-write: `branch target found with finding-mode ids` (both the route's validation and `appendBranch` attach to `tom-tat-2`).
- [ ] **Step 2: Run them and see them fail.** `npm test -- src/lib/workflow/node-ids.test.ts src/lib/workflow/authorAppend.test.ts src/lib/workflow/provenance.test.ts src/app/api/workflows/generate/append-write/route.test.ts` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npm test -- src/lib/workflow src/app/api/workflows/generate` (non-finding callers keep `n1…`) and `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(workflow): readable node ids for AI-built finding workflows`

### Task 13: Finding-mode authoring path (C2)

**One builder per route (controller, I5; Rule 7).**
- **generate/chat** keeps its "observed read" gate (`chat/route.ts:663`). With no tools offered, no read is observed, so the turn falls through to the chat route's existing probe-free, agent-only builder: `deriveNodeTasks` → `agentWorkGraph` (`chat/route.ts:718-800`). Finding mode only injects `findingModeSystem` into the `deriveNodeTasks` messages, builds with Task 12's `findingStepId`, and runs `findingActionGraphProblems` on the result. `synthesizePlan` is not run in chat finding mode.
- **generate** (one-shot) has no agent-work path, so `synthesizePlan`'s finding mode is used there only.

**Files:**
- Create: `src/lib/workflow/finding-mode.ts`
- Modify: `src/lib/workflow/synthesizePlan.ts` (`SynthResult` at :21, `planSystem` at :144, `synthesizePlan` at :235, the `compileTrace` fallback at :280-352)
- Modify: `src/lib/workflow/nodeTask.ts` (`deriveNodeTasks` at :318 gains an opt; `taskSystem` at :221 appends it)
- Modify: `src/app/api/workflows/generate/route.ts:174-223`, `src/app/api/workflows/generate/chat/route.ts` (tool list ~line 359, agent-work path ~718-800, verify ~830), `generate/compile/route.ts`, `generate/append-write/route.ts`
- Modify: `src/components/workflows/editor/AiChatPanel.tsx` / `AiGeneratePanel.tsx` (show returned `problems` with the `wf.fa.problem.*` texts FindingActionCard already uses)
- Test: `src/lib/workflow/finding-mode.test.ts`, `src/lib/workflow/synthesizePlan.test.ts`, `src/lib/workflow/nodeTask.test.ts`, `src/app/api/workflows/generate/route.test.ts`, `generate/chat/route.test.ts`, `generate/compile/route.test.ts`, `generate/append-write/route.test.ts`

**Interfaces:**
- Consumes:
  - Task 11 `FINDING_KEYS` / `findingVarCatalogue`;
  - Task 12 `findingStepId`, `agentWorkGraph(…, idOf)`, `provenanceOf(…, idOf)`, `readableIdMap` / `renameNodeIds`;
  - `findingActionGraphProblems(graph, readAllow)` and `GraphProblem` (`finding-action.ts:14,58`);
  - `mcpReadAllow(userId): Promise<ReadonlySet<string>>` (`connectors/index.ts:429`).
- Produces:
  - `export function findingModeSystem(fields: readonly { key: string }[]): string`. The routes receive only `findingAction: boolean`, so they pass `fields: []` (the catalogue then lists no `trigger.params.*`). Contains:
    - the catalogue;
    - the four rules: read the selected records from `{{trigger.items}}`; never query data again; writes are terminal; no foreach around a write.
  - `deriveNodeTasks(jobPrompt, generate, opts?: { prev?; edits?; lang?; extraSystem?: string })`. `extraSystem` is appended to `taskSystem`'s output. Absent → the messages are byte-identical to today.
  - `synthesizePlan` input gains:
    - `findingMode?: { fields: readonly { key: string }[] }`. When set, `planSystem` uses `findingModeSystem` in place of the observed-data instructions; facts may be empty. A `use` node is already rejected by `assertTraceGrounded` with empty facts; in finding mode the repair message also says "read the selected records from `{{trigger.items}}`; do not query data".
    - `check?: (graph: WorkflowGraph) => GraphProblem[]`. A non-empty result counts the attempt as failed, and the problems, rendered as text, are pushed back as the repair message. `DEFAULT_MAX_ATTEMPTS = 2` already gives exactly one repair round.
  - `SynthResult` gains `problems?: GraphProblem[]`.
  - **No `compileTrace` fallback in finding mode (controller, I4).** Today, after the last failed attempt, `synthesizePlan` builds `compileTrace(closedRecords)` from `facts.calls` (`:280-352`). With empty facts that is an empty graph plus the "linear version" note, and the problems are lost. In finding mode instead:
    - when the last attempt built a graph that failed only `check`, return `{ graph: lastCheckedGraph, source: "plan", problems }`;
    - when no attempt produced a graph at all, throw a `FindingModeError` (or return an error result); the route answers 422.
    - Without `findingMode`, the fallback is unchanged.
  - **When problems remain:**
    - generate and generate/chat answer 200 `{ graph, problems: GraphProblem[] }`. The draft is still handed over and the editor badges the nodes (§8 "return them as editor problems"; the same reasoning as the generate route's existing "return the graph even when verify failed").
    - compile and append-write reject the step with 422 `{ error: "finding_action_graph", problems }`.
- **Route behaviour when `body.findingAction === true`:**
  - **generate (one-shot):**
    - no `probe` and no 422 "No tool was observed";
    - `facts = buildFacts([])`, `readAllow = await mcpReadAllow(userId)`;
    - `synthesizePlan({ findingMode, check })`, where `check = (g) => findingActionGraphProblems(g, readAllow)`;
    - rename ids with `renameNodeIds(graph, readableIdMap(graph, new Set()))` (no provenance on this route);
    - no `verifyGraph`, because there are no reads to verify and the real check is the preview from a finding;
    - returns `{ graph, problems? }`; a thrown `FindingModeError` → 422.
    - `AiGeneratePanel` has no append-write card: in finding mode it yields an agent-only graph, and the admin adds the email node by hand.
  - **generate/chat:**
    - the model is given no tools (no probe), so no read is observed and the plan-path gate stays closed;
    - the agent-work path builds: `deriveNodeTasks(…, { …, extraSystem: findingModeSystem(fields) })` → `agentWorkGraph(tasks.steps, lang, findingStepId)`; `provenanceOf(current, prevSteps, findingStepId)` decides `canBuild`, so turn 2 still sees the canvas as assistant-authored;
    - after the rebuild re-attaches a confirmed write, its non-agent nodes are renamed (`gui-email`, `kiem-tra`) with `keep` = the agent ids plus `"report"`, as in Task 12;
    - then `findingActionGraphProblems` runs and any problems are returned as `problems` in the turn;
    - no repair round in chat: this path emits only agent nodes plus at most one terminal append-write, so `findingActionGraphProblems` effectively cannot trip. The check stays as a guard and its problems are still returned (spec C2 is met by the check; the repair round lives on the one path that can fail it);
    - verify is skipped;
    - the write-offer card path is unchanged. It is derived from the conversation (`mailIntent` / `emailPrefill` / `nodeTask`, `authorAppend.ts`), not from a tool call, so it survives offering no tools. Step 1 pins this with a test.
  - **append-write:** after building, rename only the new nodes with `readableIdMap(graph, keep)`, `keep` = the ids in `current` plus `"report"` (→ `gui-email`, `kiem-tra`); then run `findingActionGraphProblems`; problems → the 422 above.
  - **compile:** after building, run `findingActionGraphProblems`; problems → the 422 above. No client sends the flag today (Task 11).
  - `assertTraceGrounded` with empty facts already rejects any `use` node ("never query data again", `planGuard.ts:262`).

- [ ] **Step 1: Write the failing tests.**
  - `finding-mode.test`: `system lists every FINDING_KEYS var, trigger.items, me.email and the four rules`.
  - `nodeTask.test`: `extraSystem is appended to the task system message`; `no extraSystem leaves the messages unchanged`.
  - `synthesizePlan.test`:
    - `finding mode with empty facts builds an agent-only graph` (mocked `generate` returns a Plan whose agent prompt uses `{{trigger.items}}`);
    - `a use node in finding mode gets a repair message naming trigger.items` (assert the second `generate` call's messages, not only the rejection, which already happens today);
    - `check failure triggers exactly one repair round`: `generate` is called twice, and the second messages contain the problem text;
    - `problems after the repair round return the last graph with problems, not compileTrace`: `source === "plan"`, `problems` has the check's codes, and no fallback note;
    - `finding mode with no buildable attempt throws, not falls back`.
  - `generate/route.test`:
    - `findingAction skips the probe`: the probe mock is not called and the response is 200 with ids like `tom-tat`;
    - `problems after repair → 200 with graph and problems`;
    - `no buildable plan in finding mode → 422`.
  - `chat/route.test`:
    - `findingAction: the model is offered no tools, synthesizePlan and verify are not run, and node ids are tom-tat…`;
    - `findingAction turn 2 rebuilds the assistant's own canvas` (provenance stays `assistant`);
    - `findingAction turn after the email is confirmed keeps gui-email`;
    - `findingAction: "…rồi gửi email cho tôi" still returns the email offer card`.
  - `compile/route.test`: `findingAction with a write inside foreach → 422 write_in_foreach`.
  - `append-write/route.test`:
    - `findingAction rejects a second write after the first (write_not_terminal)`;
    - `findingAction names the new write gui-email and keeps report`.
- [ ] **Step 2: Run them and see them fail.** `npm test -- src/lib/workflow/finding-mode.test.ts src/lib/workflow/synthesizePlan.test.ts src/lib/workflow/nodeTask.test.ts src/app/api/workflows/generate` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npm test -- src/lib/workflow src/components/workflows/editor` (non-finding authoring is unchanged) and `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(workflow): AI builder finding-action mode (no probe, trigger catalogue, graph check)`

## Track D — UI polish (walkthrough list)

### Task 14: Take Action menu + bulk toolbar sections; create success notice; one default priority (D1, D3)

**Files:**
- Modify: `src/components/intel/detail/TakeActionMenu.tsx`, `src/components/intel/items/BulkToolbar.tsx`, `src/components/intel/detail/TaskPanel.tsx:222`, `src/components/intel/detail/FindingWorkspace.tsx:190`, `src/components/intel/detail/ActionForm.tsx`, `src/components/intel/items/ReviewItemsView.tsx` (bulk success), `src/i18n/dictionaries/intel.ts`
- Test: `src/components/intel/detail/TakeAction.test.tsx`, `src/components/intel/items/ReviewItemsView.test.tsx`

**Interfaces:**
- Produces (exported from `TakeActionMenu.tsx`):
  - `export type MenuGroupKey = "task" | "draft" | "workflow"`
  - `export function groupMenu(menu: MenuAction[]): { key: MenuGroupKey; items: MenuAction[] }[]`. Groups are pack `mode: "task"` → task, pack `mode: "draft_task"` → draft, `kind: "workflow"` → workflow. They come in that order; empty groups are omitted; server order is kept within a group.
- Headings: `intel.take.group.task|draft|workflow` = "Tạo việc" / "Việc nháp" / "Chạy workflow".
- The menu opens upward when the space below the button (`innerHeight − rect.bottom − footer height`) is under 320px and the space above is larger.
- **D3:**
  - After a create, show a clear `role="status"` notice "Đã tạo việc." with a "Xem task" link: `#task-<id>` on the detail page, and `/home/findings/<findingId>#task-<id>` from Review Items.
  - The detail `ActionForm` gets `defaultPriority="normal"`, the same as the bulk path.
  - The legacy assign form also defaults to `normal`: `FindingWorkspace.tsx:190` passes `defaultPriority="normal"` instead of `defaultPriority(p.severity)`, which `TaskPanel.tsx:87` seeds the form with. §5 D3 says "the same default priority on the detail page" with no exception (review M13).

- [ ] **Step 1: Write the failing tests.**
  - `groupMenu orders task, draft, workflow and drops empty groups`.
  - `menu renders section headings Tạo việc / Việc nháp / Chạy workflow`.
  - `menu opens upward near the bottom` (mock `getBoundingClientRect`).
  - `detail action form defaults to Bình thường`.
  - `legacy assign form defaults to Bình thường for a critical finding`.
  - `success notice links to the new task`.
  - `bulk toolbar shows the same sections`.
- [ ] **Step 2: Run them and see them fail.** `npm test -- src/components/intel/detail/TakeAction.test.tsx src/components/intel/items/ReviewItemsView.test.tsx` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `fix(intel): grouped action menu, clear create notice, one default priority`

### Task 15: Review Items table — empty columns, product duplication, quantity (D2)

**Files:**
- Modify: `src/components/intel/items/table-model.ts`, `src/components/intel/items/ItemsTable.tsx`
- Test: `src/components/intel/items/table-model.test.ts` (create)

**Interfaces:**
- Produces:
  - `evidenceColumns(columns: string[], rows?: unknown[][]): string[]`. With `rows`, it also drops columns that are null or empty in every row.
  - `columnFlags` returns `showLines: false` when any `PRODUCT_COLUMNS` column is visible. That column already says "N sản phẩm".
  - `entryCell` sums `SUMMED_COUNTS` (`quantity`, `units`) whenever a record has more than one line, even when every line has the same value. Money is unchanged.

- [ ] **Step 1: Write the failing tests.**
  - `unit cost column hidden when empty for every row`.
  - `two lines of quantity 1 show 2`. This is the TXN-1015842 case.
  - `lines column hidden when a product column is visible`.
  - `single-line record still shows its product id`.
- [ ] **Step 2: Run them and see them fail.** `npm test -- src/components/intel/items/table-model.test.ts` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npm test -- src/components/intel/items` and `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `fix(intel): review items hides empty columns and sums quantities`

### Task 16: Task card items — first 3 + "Xem tất cả" dialog; expandable earlier tasks (D4)

**Files:**
- Modify: `src/lib/intel/actions/items.ts` (add `itemSummary`), `src/app/api/intel/findings/[id]/tasks/[taskId]/items/route.ts` (each item gains `date`, `amount`)
- Modify: `src/components/intel/detail/TaskItemsList.tsx`, `src/components/intel/detail/TaskPanel.tsx:163-200`, `src/i18n/dictionaries/intel.ts`
- Create: `src/components/intel/detail/TaskItemsDialog.tsx`
- Test: `src/app/api/intel/findings/[id]/tasks/[taskId]/items/route.test.ts`, `src/components/intel/detail/TaskItemsDialog.test.tsx`, `src/components/intel/detail/TaskPanel.test.tsx`

**Interfaces:**
- Produces:
  - `export function itemSummary(row: unknown): { date: string | null; amount: number | null }`. Reads the snapshot `{ columns, lines }` (first line's date column; sum of `amount`).
  - Items response: each item adds `date: string | null` and `amount: number | null`; the response keeps `row` and `columns` as today (`items/route.ts:22-27`). A partial reader still gets `items: null`.
  - `TaskItemsDialog({ findingId, items, currency, onClose })`:
    - search over id + label;
    - 20 rows per page;
    - a row opens `ReceiptDrawer`;
    - animated close via `useAnimatedClose`.
- Card:
  - "N mục" appears once, on the toggle only; the duplicate line inside the list is removed;
  - the first 3 items are shown as `id · date · amount`;
  - "Xem tất cả N mục" opens the dialog when N > 3.
- "Việc trước đó": each older task is a `<details>` showing owner, priority, due day, item count and note.

- [ ] **Step 1: Write the failing tests.**
  - Route: `items carry date and amount for a full reader`; `partial reader still gets items null`.
  - Dialog:
    - `search filters by id`;
    - `page 2 shows rows 21-25 of 25`;
    - `row click opens the receipt`.
  - Panel:
    - `shows first 3 items and Xem tất cả 5 mục`;
    - `count shown once`;
    - `earlier task expands to show its details`.
- [ ] **Step 2: Run them and see them fail.** `npm test -- "src/app/api/intel/findings/[id]/tasks/[taskId]/items/route.test.ts" src/components/intel/detail` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `fix(intel): task card item preview, all-items dialog, expandable earlier tasks`

### Task 17: Workflow action dialog polish + preset prompts (D5, D6)

**Files:**
- Modify: `src/components/intel/detail/WorkflowActionDialog.tsx`, `src/i18n/dictionaries/intel.ts`
- Create: `src/components/intel/detail/PreviewMarkdown.tsx`
- Modify: `src/lib/presets/templates/sales.yaml` (the two finding-action presets: prompts at :138 and :171, email subjects at :147 and :180)
- Test: `src/components/intel/detail/WorkflowActionDialog.test.tsx`, `src/lib/presets/templates/catalog.test.ts`

**Interfaces:**
- Produces: `PreviewMarkdown({ text }: { text: string })`. Uses react-markdown + remark-gfm + rehype-sanitize, with no `rehype-raw`, so raw HTML such as `<b>` stays text. It renders long content collapsed after 600 characters, with a "Xem thêm" / "Thu gọn" toggle.

**Dialog changes:**
- open/close animation via `useAnimatedClose` (`src/components/ui/use-animated-close.ts`) and the `confirm-dialog` classes;
- VI subtitle `intel.wf.subtitle`;
- the line `intel.wf.notSentYet` = "Chưa gửi gì cho tới khi bạn bấm Xác nhận";
- field labels `intel.wf.arg.to|subject|body|text|message` = "Người nhận" / "Tiêu đề" / "Nội dung" (…) replace raw keys, and an unknown key falls back to the key;
- the destination `intel.wf.dest.gmail_send` = "Gửi email (Gmail)", falling back to the action name;
- when a recipient is refused, `intel.wf.refusedHow`: "Quản trị viên tổ chức có thể thêm người nhận này ở Cài đặt → Đích gửi của workflow" (settings page `/settings/workflow-destinations`).

**D6:**
- Preset agent prompts reference `{{trigger.finding.title}}` and `{{trigger.items}}` only, never `ruleId` / `metricKey`. Today both prompts include `metric {{trigger.finding.metricKey}}` (`:138`, `:171`).
- They also tell the model: "Không ghi mã quy tắc, mã chỉ số hay chữ 'unknown'; thiếu thông tin thì bỏ qua."
- **Email subjects (controller, I6):** `sales.yaml:147` and `:180` end in `- {{trigger.finding.ruleId}}`, which puts the rule code in the generated email (§5 D6 forbids it). Change both to `- {{trigger.finding.title}}`.
- Org copies already installed from the old template are not updated by this change. Note it in the Task 18 deploy checklist.

- [ ] **Step 1: Write the failing tests.**
  - Dialog:
    - `labels body as Nội dung, not body`;
    - `markdown table renders as a table`;
    - `<b> stays text` (keep the existing test);
    - `long body is collapsed with Xem thêm`;
    - `refused recipient shows how to fix with the settings link`;
    - `shows Chưa gửi gì cho tới khi bạn bấm Xác nhận`.
  - Catalog:
    - `finding-action presets reference no trigger.finding.ruleId or metricKey in any prompt or connector arg, and forbid 'unknown'`: walk every string in `graph.nodes[*].prompt` and `args` (subjects included, foreach bodies included);
    - follow-up from Task 1 (done, review M1): `every template graph passes assertSavable(serverRequiredArgsOf)` after `resolveTemplateRefs`. Templates reach `checkGraph` through `from-template.ts:47` → `createOrgItem`, which now runs `assertSavable`; this pins that they still pass.
- [ ] **Step 2: Run them and see them fail.** `npm test -- src/components/intel/detail/WorkflowActionDialog.test.tsx src/lib/presets/templates/catalog.test.ts` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npm run build` (the new client import must not pull server code) and `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `fix(intel): plain-language workflow preview dialog and preset prompts`

## Task 18: Whole-branch verification (controller)

- [ ] **Step 1: Run the full suite** in `LAAM/`. Expected:
  - `npx tsc --noEmit` → no errors.
  - `npm test` → all pass (skips are reported, not hidden).
  - `npm run test:int` → all pass except the known `org-connection.int.test.ts:131`. Any other failure blocks.
  - `npm run build` → succeeds. The client bundle must not pull `pg`.
- [ ] **Step 2: Whole-branch review** (most capable model) on `git -C LAAM diff <base>..HEAD`. Fix CRITICAL/HIGH findings, then re-run Step 1.
- [ ] **Step 3: Browser E2E on :3900** (controller only, not a subagent).
  - Rebuild: `cd LAAM && docker build -t laam-app:latest . && docker compose up -d app`.
  - Use chrome-devtools MCP; ask the user to log in when a login appears.
  - No real email: leave `RESEND_API_KEY` unset in the container, and check the `[mail] not configured` log line instead.
  - Do not confirm any external send.

  | # | VI | EN |
  |---|----|----|
  | 1 | Admin: tạo workflow cá nhân, bật "Workflow này chạy từ một phát hiện" trong "Dựng bằng AI", dựng xong, Lưu được ngay lần đầu; id bước dễ đọc (`tom-tat`, `gui-email`) | Admin: build a personal workflow with "Runs from a finding" on in "Build with AI"; first save succeeds; readable step ids |
  | 2 | Xoá một bước AI nguồn → không còn lỗi "extract.from"; prompt trống → thông báo tiếng Việt ở bước đó | Delete a source step → no raw extract error; empty prompt → localized message on that node |
  | 3 | "Thêm vào bộ công cụ": các bước theo đúng thứ tự (AI trước email); có ghi chú "Đã có bản…" khi bộ công cụ đã có bản | Share dialog lists steps in graph order; "existing copy" note shows |
  | 4 | Mở bản của tổ chức (đang được gán) → sửa và lưu được; nút Lưu không bị chân trang che | Open the org copy while assigned → editable and saves; Save not under the footer |
  | 5 | Phát hiện hoàn tiền → chạy workflow → Xem trước: nhãn "Người nhận/Tiêu đề/Nội dung", markdown hiển thị, dòng "Chưa gửi gì…"; KHÔNG bấm Xác nhận | Refund finding → run workflow → preview: friendly labels, markdown rendered, "nothing sent yet" line; do NOT confirm |
  | 6 | Giao việc cho người khác → người đó có thông báo chuông "Bạn được giao việc…" | Assign a task to someone else → they get the bell notice |
  | 7 | Việc hạn ngày mai (tạo từ trước, `createdAt` lùi ≥ 2 ngày) và việc quá hạn → gọi tick → mỗi việc đúng một thông báo; tick lần hai không thêm | Task due tomorrow (created earlier: backdate `createdAt` ≥ 2 days, or the I7 rule hides due-soon) and an overdue task → one notice each after a tick; none on a second tick |
  | 8 | Thẻ việc: ngày hạn đúng, "Quá hạn", "Sẽ nhắc: …", 3 mục đầu + "Xem tất cả N mục" (tìm, 20/trang, mở phiếu), "Việc trước đó" mở được | Task card: due day, overdue badge, next reminder, first 3 items + all-items dialog, earlier tasks expand |
  | 9 | Menu Take Action và thanh chọn nhiều: nhóm Tạo việc / Việc nháp / Chạy workflow; menu mở lên khi gần đáy; thông báo "Đã tạo việc. Xem task"; mức ưu tiên mặc định Bình thường ở cả hai đường | Grouped menu + toolbar, flips up near the bottom, create notice with link, default priority Normal on both paths |
  | 10 | Xem mục: không có cột rỗng, không lặp thông tin sản phẩm, số lượng cộng đúng | Review Items: no empty columns, no duplicate product info, quantities summed |
  | 11 | Trang workflow: tên quy tắc tiếng Việt, "Dùng cho: một phiếu / nhiều phiếu / cả hai", "Xem trước", mục "Hiện thành nút trên trang phát hiện"; gợi ý trên workflow cá nhân | Workflow page: localized rule names, "Use for" labels, "Preview" label, renamed section; personal-workflow hint |

- [ ] **Step 4: Deploy checklist.** Append a "Card #6 follow-ups" section to `docs/deploy/2026-11-20-card6-finding-actions-checklist.md` (workspace root, commit dd856b5):
  - `MAIL_FROM` and `RESEND_API_KEY` must be set in prod, or email silently never sends (§8);
  - `AUTH_URL` must be set for email links;
  - no migration in this change;
  - the first tick after deploy sends one overdue notice for every open task overdue in the last 14 days (Task 9); confirm with the owner;
  - `pending_approval` tasks receive task notices like `assigned` ones (Task 8); owner question;
  - org copies already installed from the old `sales.yaml` finding-action templates keep the rule code in their email subject (Task 17).
- [ ] **Step 5: Checkpoint.** `mcp__serena__write_memory("checkpoint/claude-2026-11-20-card6-followups", …)`. Record that email was "not verified end to end".

## Task dependencies

Done and committed: Tasks 1 (`797df26c`), 7 (`ff8687b0`) and 15 (`2684939d`). Findings about them are follow-up steps in later tasks (Task 2 for M2, Task 10 for I3, Task 17 for M1).

- **Task 10 runs next (priority).** Task 7 made `dueAt` zone-aware, so the home card and the task card show the wrong day for projects west of UTC until Task 10 lands (I3).
- Task 10 → Task 8 (`dueDayOf`). Task 8 → Task 9.
- Task 1 → Tasks 2, 4, 5 (`topoOrder` lives in validate.ts).
- Task 5 → Task 12 (`topoOrder`). Tasks 11 and 12 → Task 13.
- **Shared-file rule:** these files are each edited by several tasks:
  - `WorkflowEditor.tsx` and its test (2, 11);
  - `WorkflowDetailClient.tsx` and its test (3, 6);
  - `WorkflowActionDialog.tsx` and its test (4, 17);
  - `AiChatPanel.tsx` / `AiGeneratePanel.tsx` (11, 13);
  - `append-write/route.ts` and its test (12, 13);
  - `authorAppend.ts`, `provenance.ts` (12, 13);
  - `time.ts` (10; Task 8 reads it);
  - `intel.ts` dictionary (4, 10, 14, 16, 17);
  - `workflows.ts` dictionary (6, 11);
  - `TaskPanel.tsx` and its test (10, 14, 16).

  Tasks sharing any of these files never run at the same time.
- Safe parallel groups:
  - {3, 10} now; Tasks 2 and 5 may join them (no shared file);
  - Task 4 after Task 10 (both edit `intel.ts`);
  - Task 6 after Tasks 3 and 11;
  - {11, 12} after Task 5.
