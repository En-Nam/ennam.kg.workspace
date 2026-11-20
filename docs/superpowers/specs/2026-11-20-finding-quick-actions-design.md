# Finding quick actions, affected items, bulk actions (Trello card #6, Phase 1 + 2)

Date: 2026-11-20 · Branch: `task/improve_by_feedback_19112026` (LAAM, ennam.kg.packs, workspace root)
Card: https://trello.com/c/NFJVFEt3 · Agreed direction: our card comment `6afe76ab50b8c1fae69b0da9`

## 1. Intent

When someone opens a finding in LAAM, they can see what is wrong but cannot act on it beyond "Assign".
The meeting on 2026-11-18 asked for:
- direct actions on the finding;
- a way to see and pick the individual affected records;
- tasks that carry those records, so the owner knows exactly what to look at.

Actions must come from configuration, not from code branching on finding type.

- **Success:** a store manager opens a margin finding, clicks **Review Items** and ticks 12 sales. They pick "Review Pricing" and confirm. The owner gets one task that links to the finding and lists those 12 sales.
- **Phase 2:** an admin attaches a workflow to the same finding type, and the menu shows that workflow's button as well.

## 2. Goals, non-goals, anti-goals

**Goals (Phase 1)**
- Add two compact outlined buttons, **Take Action** and **Review Items**, next to **Assign** in the right "Status and task" panel (`TaskPanel.tsx`).
  - The Assign dropdown stays unchanged.
  - The buttons go in the panel, not in the header.
- **Take Action** opens a menu of the actions configured for the finding's rule.
  - Each action opens one shared form: context, item count, owner, priority, due date, note, approval. The user confirms, and the result is a task linked to the finding (and the selected items).
- **Review Items** opens a full-width page of the finding's evidence rows.
  - The page has search, column filter, pagination, multi-select, and a bulk toolbar showing the actions that allow bulk use.
  - Clicking a row opens the existing receipt drawer for sale/refund rows, or a row-detail panel for other rows.
- The evidence preview on the detail page gets a **View all items** link. The preview IDs are already clickable.
- Action definitions live in the pack, per rule (`actions:`). A project admin can switch individual actions off in Settings.
- Every action is recorded: a `finding_event` and an `audit_log` row.

**Goals (Phase 2)**
- A workflow can be marked as a **Finding action**, with a label (EN/VI), the rules it applies to, single/bulk, and personas.
- Those workflows appear in the same Take Action menu.
  - Clicking one shows a confirm dialog (workflow name, finding, item count), then runs the workflow with the finding and the selected items as input.
  - The run appears in the existing run history.
- Two workflows can show different buttons for the same finding type.

**Non-goals**
- Phase 3, writing into POS, promotion, purchasing or CRM systems, is **on hold**: no write connector exists.
  - Actions that would need such a write are marked `mode: draft_task`. They create a task titled as a draft for a person to carry out by hand.
  - The UI says plainly that nothing is sent to an external system.
- Low Inventory, Slow-Moving Products and Customer Decline templates are not built. RET-INV-003 (stockout risk) exists, but there is no reorder/transfer data or connector, and no slow-moving or customer data at all. RET-INV-003 keeps its single fallback action. "Review Inventory" is also left out of the Sales Decline template for the same reason.
- A drag-and-drop form builder. Phase 1 pack actions use one fixed form (the pack sets defaults). Phase 2 workflow actions get a short list of extra fields (§5.6), not a full builder.
- Changing the existing workflow graph editor, the run engine semantics, or the run history UI beyond adding the input variables.

**Anti-goals (a failure even if it "works")**
- An action that looks executed but did nothing: a fake "Sent to POS".
- Restricted users seeing finding wording or items outside their scope through the new page, task titles or workflow input.
- Hardcoding DAAB names or tool ids in LAAM runtime strings. LAAM stays connector-agnostic.
- Breaking old findings: runs pinned to pack 0.7.3 have no `actions:` and must still show a working menu.

## 3. Constraints (from the code)

- **The pack rule schema is strict.** `ruleSchema` (`LAAM/src/lib/intel/pack/schema.ts:44`) is a `z.strictObject`, so the LAAM change that accepts `actions:` must deploy **before** pack 0.7.4 is published.
- **Pack bumps need pins.** Pharmacy extends retail, so **both** `retail/pack.yaml` and `pharmacy/pack.yaml` go to 0.7.4. That means bumping every `canonical: retail@…` / `pharmacy@…` in `*/daab/crosswalks/*.yaml` and the Go test pins (`ennam.kg.go/internal/intel/pack_070_test.go`, `crosswalk_test.go`). Then run `grep -rn "@0.7.3" ennam.kg.packs ennam.kg.go/internal/intel`, which must return nothing.
- **Affected items are not stored.** They come live from `GET /api/intel/findings/[id]/evidence` (DAAB `kg_get_evidence`), which returns 25 rows per page and is capped at 500 rows in the UI. The columns differ per metric.
- **Some users may see only part of a finding.** Restricted users get 404 unless the finding is fully in their scope. Partial or peer-hidden views keep the wording out of task titles (`finding-actions.ts:55-59`).
- **Task creation is centralised.** It goes through `prepareCreateTask` → `planCreateTask` → `commitPlan` (`finding-actions.ts`, `actions.ts`), shared with the chat tools.
  - That path checks the owner is eligible, refuses an identical open task with a 409, and moves the finding to `assigned`.
- **Workflows take no input today.** A run's context is `emptyContext({source})`, and `RunTrigger` is `manual|schedule|draft|preset_test`.
- **Migrations:** drizzle-kit. Use `npm run db:generate` then `db:migrate`, never `db:push`. The latest migration is `0059`.
- **i18n:** every new string goes in `src/i18n/dictionaries/intel.ts` in vi, en and zh.
- **Route tests:** every new route goes in `src/test/route-inventory.ts` and `src/test/isolation/cases.ts`.

## 4. Approaches considered

- **A. Templates in LAAM code, plus Settings toggles. Not picked.**
  - It needs no pack release.
  - But it puts retail vocabulary in LAAM code, which the pack layer exists to avoid.
- **B. `actions:` per rule in the pack, plus Settings toggles, plus workflow actions. Picked by the user.**
  - Domain wording stays in the pack, next to the rule it belongs to.
  - The cost is a pack release (0.7.4) with pin bumps, and a fixed deploy order.
- **C. Everything defined by workflows. Not picked.**
  - Every simple "create a task" action would need a workflow.
  - That is heavy for Phase 1, and nothing would work out of the box.
- **Bulk selection.** The user picked **one shared task** that links all the selected items, over one task per item.

## 5. Design

### 5.1 Pack: `actions:` on a rule (pack 0.7.4)

The `actions:` list on a rule is optional. Example:

```yaml
actions:
  - key: review_pricing             # lower_snake, unique within the rule
    label: { en: "Review pricing", vi: "Rà soát giá bán" }
    action_type: price_review       # one of RECOMMENDED_ACTIONS (existing enum)
    scope: both                     # single | bulk | both  (bulk = needs selected items)
    mode: task                      # task | draft_task
    approval_required: false        # default for the form
    due_days: 3                     # optional default due date, days from today
    personas: [store_manager, area_manager]  # optional: project personas (pack roles.yaml) allowed to use it; absent = everyone who can act
    reminder_days: [2, 21]          # optional follow-up reminders, days after the task is created
```

- **LAAM schema:** add an `actionSchema` (strict) and `actions: z.array(actionSchema).default([])` on `ruleSchema`, with keys unique per rule.
- **When a rule has no actions:** if the rule has no `actions` (old pinned pack, or a rule we did not configure), LAAM synthesises one action from `recommended_action`, with `key` = the `recommended_action` value (e.g. `review`), the existing localized label for that action type, `scope: both` and `mode: task`. So the fallback can be disabled, stored as `task.action_key`, and deduplicated like any other action.
- **Templates written in 0.7.4:**

  | Template | Rules | Actions |
  |----------|-------|---------|
  | Sales Decline | RET-SALES-001 | Investigate sales; Review pricing; Create promotion (`draft_task`) |
  | Margin Deterioration | RET-MARGIN-001/002, RET-VENDOR-001 | Review vendor costs; Review pricing; Analyze margins; Request vendor review (`draft_task`) |
  | High Returns / Refunds | RET-REF-001/002/004, RET-X-REPRINT-001 | Review transactions; Investigate returns; Flag products (`draft_task`) |

  The other rules (DISC, VOID, CASH, LABOR, INV) keep the single action built from `recommended_action`.

### 5.2 Settings: switch actions off per project

- A new `text[]` column on `business_project`: `disabled_finding_actions` (default empty), holding entries like `"RET-SALES-001:review_pricing"`.
- The project admin page (`settings/business-projects/[id]`) gets a "Finding actions" section: the rules, each with its actions as toggles. Only owners and admins can change it.
- A disabled action is hidden from the menu and refused by the API.
- Entries that no longer match any action (a pack renamed a key) are simply ignored.

### 5.3 Which actions a user sees

A pure function `availableActions(rule, project, viewer, selectionCount)` returns the actions to show. An action is shown only if it is all of:
- defined for the rule, or built from `recommended_action`;
- not disabled in Settings;
- allowed for the viewer: `canMutate`, and, when the action lists `personas`, the viewer's project persona (`user_scope.persona`) is one of them. Personas, not org roles, because almost every store user is an org "member";
- allowed by the selection: with 0 items selected, only `single`/`both` actions; with items selected, only `bulk`/`both` actions.

The function also includes the Phase 2 workflow actions that match the rule. The API applies the same function, so a hidden action cannot be posted.

### 5.4 Take Action → task

- **Form.** A reusable `ActionForm` panel shows:
  - the action label;
  - the finding context: its title, kept out for partial views as today;
  - the selected item count and the first few item labels;
  - owner (the same candidate list as Assign), priority, due date (prefilled from `due_days`), an optional note, and approval (prefilled);
  - for `mode: draft_task`, a banner: "Draft task: nothing is sent to any external system."

  The confirm button submits. The panel then shows the created task, or a localized error.
- **API.** Extend `POST /api/intel/findings/[id]/tasks`:
  - The body gains `actionKey?` (string), `itemIds?` (max 200), and `note?` (max 1000).
  - The server resolves the action through `availableActions` and rejects unknown or hidden actions with 403/422.
  - It sets `actionType` from the action, and builds the title from the action label plus the item count. For `draft_task` the title gets a "Draft:" prefix.
- **Re-checking items.** The server re-checks `itemIds` against the finding's evidence in one scan. `findingEvidenceHas` (`records.ts`) is generalised rather than copied: its pagination and sanitise loop stay, it takes a set of ids and the key columns of §5.5, and returns the matched rows. So a row the caller may not see still cannot vouch for an id. It rejects ids that are not in the finding's evidence, returns which ones failed, and fails closed if the scan errors.
- **Same path as Assign.** Task creation still goes through `prepareCreateTask`, so owner checks, wording hiding, the finding moving to `assigned`, `finding_event` and `audit_log` all stay as they are.
  - The `task_created` event payload adds `actionKey`, `itemCount` and `mode`.
- **New task columns.** `task.action_key` (nullable text) and `task.note` (nullable text) are added in the same migration. The title is stored in the creator's language; readers in other languages still see the action label through `action_key`.
- **Duplicates.**
  - When `actionKey` is set, the existing owner+title+actionType check (`finding-actions.ts:62-64`) is **skipped** (titles are "label + count", so two different 12-item selections would wrongly collide). Without `actionKey` (Assign, chat) it stays as today.
  - With items: if any selected item is already in an **open** task with the same `action_key` (any owner) → 409 `items_in_open_task`, listing those items so the UI can offer to deselect them. This also covers re-submitting the same selection.
  - With no items: an open task with the same `action_key` (any owner) → 409 `duplicate_task`.
  - These checks run in `prepare`. The race is already closed by `commitPlan`, which locks the finding with a guarded UPDATE and re-counts open tasks (`actions.ts:382-399`) and returns `ConflictError`; `WritePlan` is extended with `taskItems` so the items are inserted in that same transaction. No extra `SELECT … FOR UPDATE`.
- **Reminders.** One simple rule for both pack and workflow actions: if the action has reminder days, one `finding_reminder` row (findingId, taskId?, userId, remindAt, sentAt) is written per day, for the task owner (pack action) or the clicking user (workflow action). A due-reminder sweep on the existing workflow scheduler tick sends an in-app notification (existing `src/lib/notifications`) if the task is still open, or for workflow actions, if the finding is still open; otherwise the row is marked skipped. Optional: no reminder days, no rows.
- **Linking items.** A new table `task_item` (`taskId` FK cascade, `projectId`, `itemKind` sale|refund|row, `itemId`, `label`, `row` jsonb snapshot, `createdAt`) is written in the same transaction as the task.
  - The snapshot is kept because evidence is read live and can change later.
- **Showing items on the task.** The task card in `TaskPanel` shows "N items". Clicking it lists them, and sale/refund items open the receipt drawer.
- **Scope on read.** `task_item.row` and `label` are snapshots made under the creator's view, and `sanitizeEvidencePage` cannot re-scope them (it only filters on `location_id`, which these evidence SQLs do not return). So item details (rows, labels, receipt drawer) are shown only to readers who pass the evidence route's own gate: unrestricted, or `scopeFinding(...).mode === "full"` and `evidenceReadable` (`evidence/route.ts:29-44`). Everyone else sees the item count only.
- **Chat.** The chat task tool keeps working without `actionKey`/`itemIds`.

### 5.5 Review Items page

- **Route.** `/home/findings/[id]/items`, a full-width page (no right aside), using the same access check as the detail page.
- **Data.** It uses the existing evidence API, paging through up to 500 rows.
  - Search is a client-side text match over the loaded rows.
  - The column filter is a select on the known dims: category, employee and location, when those columns are present.
  - Pagination is 25 per page.
- **Selection.** Checkbox per row, select-all on the page, and a "select all N loaded" option. The bulk toolbar shows the count and the bulk-eligible actions; choosing one opens `ActionForm` with the selection.
- **One item = one record, not one evidence row.** Evidence for sales/margin is one row per sale line, so the same `sale_id` repeats. The list groups rows by key: one line per record, showing the line count and summed amounts; the detail panel shows all its lines. Selection, item count, the duplicate check and `task_item` all use the record key (`task_item.row` holds the record's lines).
- **Item key.** The key column is the first one present of `refund_id`, `sale_id`, `original_sale_id` (as `keyCell` does today), then `product_id`, then `employee_id`. Rows with none of these cannot be selected.
- **Selection cap.** At most 200 records per action (same as the API limit); "select all loaded" stops at 200 and says so.
- **Row click.** A sale/refund row opens `ReceiptDrawer`. Any other row opens a side panel with all of the row's columns, using the same cell formatting as `EvidencePanel`.
- **States.** The page has empty, loading and error states that reuse the evidence error keys. It is responsive: on phone and tablet the table scrolls horizontally inside its card, and the toolbar sticks to the bottom.
- **Links.** The detail page's `EvidencePanel` gets a "View all items" link, and **Review Items** in `TaskPanel` links to the same page.

### 5.5a Which records come first (pack evidence convention)

Today evidence is every record in the finding's window, in time order, cut at 500, so the records that caused the problem may not be in the list. The fix is a **convention in the pack's evidence SQL**, so any new metric gets it by following the same rule, with no LAAM or DAAB code change:

- **`_impact` column.** An evidence query may return a numeric column named `_impact`: how much this row moved the metric in the bad direction (bigger = worse). The query orders by `_impact DESC NULLS LAST`, then by time, so the 500-row cut keeps the worst rows.
  - `gross_margin_pct`: margin lost on the line, `discount_amount - quantity * (unit_price - unit_cost)` (positive = loss).
  - `refund_rate`, `no_receipt_refund_pct`, `duplicate_refund_groups`, `reprint_before_refund_count`: refund amount, with no-receipt refunds first where that column exists.
- **Metrics with no per-row impact** (e.g. `net_sales`: a sales drop is missing sales, not bad rows) return no `_impact` and keep time order.
- **Factor pre-filter (server-side).** The Review Items page opens pre-filtered to the top contributing factor from `contributingFactors` (e.g. category = Drinks, 70% of the change). The filter is passed to the evidence API as one extra dim, applied in the SQL (`:dim_category` etc.), so the 500-row cut is taken **after** filtering; a client-side filter would only see the first hours of a time-ordered window. The route accepts an extra dim only if (a) it is the dim of one of the finding's own `contributingFactors` entries and (b) the metric's evidence SQL declares that `:dim_` parameter; anything else is 400. This is a deliberate, narrow loosening of the route's "the request cannot name dims" rule (`evidence/route.ts:18-20`). A chip shows the filter and can be removed. Rules whose evidence SQL lacks the dim fall back to no pre-filter.
- **Lines of one sale.** Worst-first ordering is by line, so a sale's lines can be split across the 500-row cut. Grouped records (§5.5) show "partial: more lines outside the list" when the record's line count could be cut, and the record detail fetches its full lines through the receipt drawer.
- **Display.** `_impact` is a meta column: LAAM shows it as an "Impact" column (formatted like the other money cells) and sorts by it by default; it is not stored as an item id.
- **Who else sees it.** The detail page evidence panel, the receipt drawer check and the chat tools read the same SQL, so they all switch to worst-first order. That is intended.
- **Go tests.** Adding `_impact` changes evidence column lists asserted in Go (`pack_070_test.go`, `golden_070_return_test.go`, `engine/query_test.go`); update them in the same change.
- **Checks.** Each changed SQL is tested on all three source modes (live, file, landed) and timed on the landed demo data; if the sort makes the landed query noticeably slower (more than ~2x), add a supporting index or keep time order for that metric and note it.
- **Later, not now.** Per-product comparison against the baseline period for Sales Decline (a different query shape). The convention above leaves room for it: a future `net_sales` evidence query can return `_impact` = lost sales per product.

### 5.6 Phase 2: workflows as finding actions

- **Storage.** A new nullable jsonb column on `workflow`, `finding_action`:
  `{ enabled, label:{en,vi}, ruleIds:string[], scope: single|bulk|both, personas:string[] | null, fields:[{key, label:{en,vi}, type: text|number|select|date, options?, required}], reminderDays:number[] | null }`. It applies to every project of the workflow's org whose findings match `ruleIds`.
- **Validation on save.** `ruleIds` must exist in at least one of the org's projects' installed packs; `fields` max 10; and **writes must be terminal**: the save is refused if any node's args or any condition references the output of a write step (in a preview that output is a mock, so replaying args built from it would send mock-derived content).
- **Which workflows.** Only **org** workflows can be finding actions; personal workflows cannot. The viewer must also pass the existing `canUse` grant (`lib/workflow/access.ts`).
- **Editing.** It is edited in a new "Finding action" card in the workflow's settings, next to `ScheduleCard`. The rule list comes from the project's installed pack rules. Owners and admins only.
- **Menu.** `availableActions` adds the matching enabled workflows, with a "workflow" icon, after the pack actions.
- **Running.** A new route `POST /api/intel/findings/[id]/workflow-actions` takes `{ workflowId, itemIds? }`.
  1. It checks finding access, the workflow's `finding_action` (enabled, project and rule match, persona, scope), the `fields` values, and the items (same re-check as §5.4).
  2. It applies the same gates as `POST /api/workflows/[id]/run`: `requireMutator`, `assertOrgActive`, `assertCanConsume`, and member consent.
  3. It runs `executeRun` with the new `RunTrigger` value `"finding_action"` (also added to `viaOfTrigger`'s exhaustive switch, the run-history labels and i18n).
- **Run input.** Stored durably in a new `workflow_run.trigger_input` jsonb column written **at insert** (not only at finalize; the finalize `context` is capped and is `undefined` when the engine throws), threaded through `RunRow` and `rebuildContext` so a resumed run still has it (`resume.ts:128` rebuilds `{source}` only today). The trigger carries `{ source:"finding_action", finding:{ id, ruleId, metricKey, dims, severity, variancePct, title? }, items:[{kind,id,label,row}], params:{…field values}, actionConfig:{…snapshot of finding_action at run time} }`.
  - `title` is left out when the viewer's view is partial, as in §5.4.
  - Items are bounded: kind, id, label and up to 8 key columns per record, never full line lists (max 200 records).
  - `trigger_input` keeps the exact input and the action config snapshot each run used. That is the versioning the card asks for.
- **Channel (`via`).** `viaOfTrigger("finding_action")` returns the existing `"workflow_manual"`. Adding a new `Via` value would touch the data-source delegation contract, so we reuse the existing one.
- **Editor.** The variable hints add `{{trigger.finding.*}}`, `{{trigger.items}}` and `{{trigger.params.*}}`.
- **Confirmation.** The first dialog shows the workflow name, the finding, the item count and the fields; the user must click to start the preview run. Nothing is sent until the second click ("Confirm & send", below).
  - Afterwards it shows the run status with a link to the run in run history.
  - A `finding_event` of type `workflow_action_run` (runId, workflowId, itemCount) is written.
- **Finding link.** A new nullable, indexed `workflow_run.finding_id` column, used for the finding's history and for the send claim below. No duplicate check on preview runs: a preview sends nothing.
- **Retry.** A failed preview or send shows its error and "Preview again", which starts a new preview with the same input. There is no retry of a single failed write: a write that threw may have committed, and the WAL deliberately refuses to re-claim it.
- **Reminders.** As in §5.4.
- **Ready-made templates (required).** Two finding-action presets ship: "Draft a promotion proposal" (Sales Decline) and "Vendor cost review request" (Margin). Each analyses the items and drafts a proposal; sending follows the preview rule below.
- **Preview before anything is sent.** The engine cannot pause mid-run (node kinds are agent/connector/condition/foreach/mcp), so a finding action runs in two steps (user's choice, option b):
  1. **Preview run.** The workflow runs with `dryRun: true`. Reads and AI steps run for real; every write step is already mocked by the runtime and returns `{ dryRun:true, wouldHaveCalled, args, recipientCheck? }` (`LAAM/src/lib/workflow/runtime.ts:133-150`), saved in that run's steps. The dialog shows each pending write: destination (connector action), recipient, and the exact content (`args`), plus any recipient-allowlist refusal.
  2. **Send.** "Confirm & send" calls `POST /api/intel/findings/[id]/workflow-actions/[runId]/send`. The server checks, in order:
     - access to the finding, and that the preview run belongs to this finding and this user, is a `finding_action` dry run, succeeded, and is under 24 h old;
     - `requireConsent` on the **current** workflow row (dry runs skip it, `workflows/[id]/run/route.ts:126-133`), surfacing its 409 reactivation flow in the dialog; plus `requireMutator`, `assertOrgActive`, `assertCanConsume`;
     - the preview's `authoredHash` equals the workflow's current stored hash; otherwise "the workflow changed, preview again";
     - **single-use claim**: `UPDATE workflow_run SET sent_run_id = $new WHERE id = $preview AND sent_run_id IS NULL RETURNING`. No row → 409 `already_sent`. This, not the WAL, is what stops a double click or two tabs.
  
     It then creates the send run and executes **only the recorded write calls, with the stored `args`, for real**, through a new `sendRecordedCall(action, args)` that **skips `interpolateArgs`** (AI text containing `{{…}}` must be sent verbatim; `executors.ts:87,100` would re-interpolate) and applies the real-run gates explicitly: `assertConnectorAllowed` / `assertMcpAllowed` against a fresh `mcpReadAllow`, the recipient allow-list, and `withWriteIdempotency` **keyed on the send run's id** (the preview's own WAL rows already hold the mocked output as `done`, `run.ts:205`, `idempotency.ts:97-110`, so keying on the preview would "replay" the mock and send nothing). The WAL is extended to cover MCP-node writes too (today `isWrite` is connector-only). No AI step runs again, so what is sent is exactly what was previewed.
  - Credentials are the clicking member's own (`connectorExecute(userId)`); a user with no Slack/Jira connection gets a clear "connect X first" error before anything is sent.
  - The send is its own `workflow_run` (trigger `finding_action`, `previewRunId` in `trigger_input`) with one step per write, so run history shows the preview and the send with per-write success/failure.
  - If the preview has no write steps, step 2 is skipped: the run is the result.
  - Builder to verify first: dry-run step output keeps the full `args` (each step capped at 256 KB by `capForPersist`; a preview whose write args were capped cannot be sent and says so).

### 5.7 Deploy order (goes into the deploy checklist)

1. Deploy LAAM with the migrations (`task_item`, `task.action_key`, `task.note`, `finding_reminder`, `business_project.disabled_finding_actions`, `workflow.finding_action`, `workflow_run.finding_id`, `workflow_run.trigger_input`, `workflow_run.sent_run_id`) and the schema that accepts `actions:`.
2. Bump retail **and** pharmacy to 0.7.4, along with every crosswalk `canonical:` and the Go pins. Pharmacy inherits the retail rules' actions; PH-MARGIN-001 gets the Margin template. Run the Go and pack tests after the bump. `grep @0.7.3` must return nothing.
3. Tag packs v0.7.4 so they publish.
4. New runs pick up 0.7.4. Findings pinned to 0.7.3 use the fallback action.

**Which pack version is read:** `availableActions` and the task API read the rule from the finding's **pinned** pack version (the same `runPackDirs` path the detail page uses), so an action always matches the rule that produced the finding. The Settings rule list and the workflow `ruleIds` picker read the project's **currently installed** pack.

## 6. Tests (intent)

- **`availableActions`:**
  - the fallback for rules without `actions`;
  - actions disabled in Settings are hidden;
  - `personas` is enforced;
  - the single/bulk split follows the selection count;
  - workflow actions are included only for matching rules.
- **Tasks API:**
  - a hidden or disabled action is refused;
  - item ids outside the evidence are refused;
  - an overlapping selection returns 409 `items_in_open_task`; a disjoint selection for the same owner and same count creates a new task;
  - item details are hidden from a partial-scope reader of the task;
  - a `draft_task` gets the "Draft:" title;
  - partial views get no wording;
  - the task and `task_item` rows are written in one transaction.
- **Workflow action route:**
  - wrong rule, role or scope is refused;
  - the context carries the finding and items;
  - the trigger is `finding_action`;
  - the consent and consume gates still apply;
  - send: second send → 409 `already_sent`; changed workflow → refused; `{{…}}` in drafted text is sent verbatim; a graph with a non-terminal write cannot be saved as a finding action.
- **Isolation:** another org's or project's finding, task or workflow returns 404.
- **Pack schema:**
  - an unknown key inside `actions` fails validation;
  - duplicate keys fail;
  - `rules.yaml` 0.7.4 loads;
  - the Go crosswalk tests pass at 0.7.4.
- **Evidence route:** an extra dim not from the finding's factors, or not declared by the SQL, returns 400.
- **E2E on :3900, in EN and VI:**
  - a margin finding → Take Action → Review pricing → task created;
  - Review Items → select 3 → bulk action → one task with 3 items;
  - a draft action shows its banner;
  - a workflow action previews, then sends, and both runs show up in run history.

## 7. Left to the builder

- Icons, exact spacing, and the menu component: use the existing UI kit.
- The exact Vietnamese labels for actions in the pack. Keep them short and use the glossary terms.
- Bulk evidence verification: one evidence scan per request. Fail closed if the scan errors.
- The exact `_impact` expression per metric, within §5.5a's meaning (bigger = worse), checked against the real columns of each evidence SQL.
