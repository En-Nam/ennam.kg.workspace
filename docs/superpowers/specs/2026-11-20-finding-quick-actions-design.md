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
- A workflow can be marked as a **Finding action**, with a label (EN/VI), the rules it applies to, single/bulk, and minimum role.
- Those workflows appear in the same Take Action menu.
  - Clicking one shows a confirm dialog (workflow name, finding, item count), then runs the workflow with the finding and the selected items as input.
  - The run appears in the existing run history.
- Two workflows can show different buttons for the same finding type.

**Non-goals**
- Phase 3, writing into POS, promotion, purchasing or CRM systems, is **on hold**: no write connector exists.
  - Actions that would need such a write are marked `mode: draft_task`. They create a task titled as a draft for a person to carry out by hand.
  - The UI says plainly that nothing is sent to an external system.
- Low Inventory, Slow-Moving Products and Customer Decline templates: there are no rules or data for them, so they are not built.
- A per-action custom form schema builder. Phase 1 uses one fixed form; the pack can only set defaults.
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
    min_role: member                # optional: owner | admin | member (default member)
```

- **LAAM schema:** add an `actionSchema` (strict) and `actions: z.array(actionSchema).default([])` on `ruleSchema`, with keys unique per rule.
- **When a rule has no actions:** if the rule has no `actions` (old pinned pack, or a rule we did not configure), LAAM synthesises one action from `recommended_action`, using the existing localized label for that action type, with `scope: single` and `mode: task`.
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

### 5.3 Which actions a user sees

A pure function `availableActions(rule, project, viewer, selectionCount)` returns the actions to show. An action is shown only if it is all of:
- defined for the rule, or built from `recommended_action`;
- not disabled in Settings;
- allowed for the viewer: `canMutate`, and `min_role` satisfied;
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
- **Re-checking items.** The server re-checks `itemIds` against the finding's evidence in one scan. This is new logic: `findingEvidenceHas` only knows `refund_id`/`sale_id`/`original_sale_id`, so a new set-based check (`findingEvidenceItems`) matches every key column in §5.5. It rejects ids that are not in the finding's evidence, returns which ones failed, and fails closed if the scan errors.
- **Same path as Assign.** Task creation still goes through `prepareCreateTask`, so owner checks, wording hiding, the finding moving to `assigned`, `finding_event` and `audit_log` all stay as they are.
  - The `task_created` event payload adds `actionKey`, `itemCount` and `mode`.
- **New task columns.** `task.action_key` (nullable text) and `task.note` (nullable text) are added in the same migration. The title is stored in the creator's language; readers in other languages still see the action label through `action_key`.
- **Duplicates.** "Identical open task" now also compares `action_key` and the sorted set of item ids. Re-submitting the same selection returns 409; a different selection is a new task.
- **Linking items.** A new table `task_item` (`taskId` FK cascade, `projectId`, `itemKind` sale|refund|row, `itemId`, `label`, `row` jsonb snapshot, `createdAt`) is written in the same transaction as the task.
  - The snapshot is kept because evidence is read live and can change later.
- **Showing items on the task.** The task card in `TaskPanel` shows "N items". Clicking it lists them, and sale/refund items open the receipt drawer.
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
  - `avg_unit_cost`: cost above the line's previous cost, where the data has it; otherwise no `_impact`.
  - `refund_rate`, `no_receipt_refund_pct`, `duplicate_refund_groups`, `reprint_before_refund_count`: refund amount, with no-receipt refunds first where that column exists.
- **Metrics with no per-row impact** (e.g. `net_sales`: a sales drop is missing sales, not bad rows) return no `_impact` and keep time order.
- **Factor pre-filter (generic, in LAAM).** For every finding, the Review Items page opens pre-filtered to the top contributing factor from `contributingFactors` (e.g. category = Drinks, 70% of the change), when the evidence has that column. A chip shows the filter and can be removed. This covers `net_sales` and helps every other metric too.
- **Display.** `_impact` is a meta column: LAAM shows it as an "Impact" column (formatted like the other money cells) and sorts by it by default; it is not stored as an item id.
- **Who else sees it.** The detail page evidence panel, the receipt drawer check and the chat tools read the same SQL, so they all switch to worst-first order. That is intended.
- **Checks.** Each changed SQL is tested on all three source modes (live, file, landed) and timed on the landed demo data; if the sort makes the landed query noticeably slower (more than ~2x), add a supporting index or keep time order for that metric and note it.
- **Later, not now.** Per-product comparison against the baseline period for Sales Decline (a different query shape). The convention above leaves room for it: a future `net_sales` evidence query can return `_impact` = lost sales per product.

### 5.6 Phase 2: workflows as finding actions

- **Storage.** A new nullable jsonb column on `workflow`, `finding_action`:
  `{ enabled, label:{en,vi}, ruleIds:string[], projectIds:string[] | null, scope: single|bulk|both, minRole }` (`projectIds: null` = every project).
- **Which workflows.** Only **org** workflows can be finding actions; personal workflows cannot. The viewer must also pass the existing `canUse` grant (`lib/workflow/access.ts`).
- **Editing.** It is edited in a new "Finding action" card in the workflow's settings, next to `ScheduleCard`. The rule list comes from the project's installed pack rules. Owners and admins only.
- **Menu.** `availableActions` adds the matching enabled workflows, with a "workflow" icon, after the pack actions.
- **Running.** A new route `POST /api/intel/findings/[id]/workflow-actions` takes `{ workflowId, itemIds? }`.
  1. It checks finding access, the workflow's `finding_action` (enabled, rule matches, role, scope) and the items (same re-check as §5.4).
  2. It applies the same gates as `POST /api/workflows/[id]/run`: `requireMutator`, `assertOrgActive`, `assertCanConsume`, and member consent.
  3. It runs `executeRun` with the new `RunTrigger` value `"finding_action"`.
- **Run input.** The run context's trigger carries `{ source:"finding_action", finding:{ id, ruleId, metricKey, dims, severity, variancePct, title? }, items:[{kind,id,label,row}] }`.
  - `title` is left out when the viewer's view is partial, as in §5.4.
  - The context is already persisted on `workflow_run.context`, so every run keeps the exact input and the action config it ran with. That is the versioning the card asks for.
- **Channel (`via`).** `viaOfTrigger("finding_action")` returns the existing `"workflow_manual"`. Adding a new `Via` value would touch the data-source delegation contract, so we reuse the existing one.
- **Editor.** The variable hints add `{{trigger.finding.*}}` and `{{trigger.items}}`.
- **Confirmation.** The dialog shows the workflow name, the finding and the item count, and the user must confirm. Nothing runs without that click.
  - Afterwards it shows the run status with a link to the run in run history.
  - A `finding_event` of type `workflow_action_run` (runId, workflowId, itemCount) is written.
- **Duplicates.** If a run of the same workflow for the same finding is already `running`, the route returns 409.
- **Ready-made templates.** One example finding-action workflow ships as a preset: "Draft a promotion proposal and post it for review".
  - It analyses the items, drafts the proposal, and sends it through whatever notify or write node the org already has.
  - It is optional; whether to add it is left to the builder (§7).

### 5.7 Deploy order (goes into the deploy checklist)

1. Deploy LAAM with the migrations (`task_item`, `task.action_key`, `task.note`, `business_project.disabled_finding_actions`, `workflow.finding_action`) and the schema that accepts `actions:`.
2. Bump retail **and** pharmacy to 0.7.4, along with every crosswalk `canonical:` and the Go pins. Pharmacy inherits the retail rules' actions; PH-MARGIN-001 gets the Margin template. Run the Go and pack tests after the bump. `grep @0.7.3` must return nothing.
3. Tag packs v0.7.4 so they publish.
4. New runs pick up 0.7.4. Findings pinned to 0.7.3 use the fallback action.

## 6. Tests (intent)

- **`availableActions`:**
  - the fallback for rules without `actions`;
  - actions disabled in Settings are hidden;
  - `min_role` is enforced;
  - the single/bulk split follows the selection count;
  - workflow actions are included only for matching rules.
- **Tasks API:**
  - a hidden or disabled action is refused;
  - item ids outside the evidence are refused;
  - the same selection returns 409, a different selection creates a new task;
  - a `draft_task` gets the "Draft:" title;
  - partial views get no wording;
  - the task and `task_item` rows are written in one transaction.
- **Workflow action route:**
  - wrong rule, role or scope is refused;
  - the context carries the finding and items;
  - the trigger is `finding_action`;
  - the consent and consume gates still apply.
- **Isolation:** another org's or project's finding, task or workflow returns 404.
- **Pack schema:**
  - an unknown key inside `actions` fails validation;
  - duplicate keys fail;
  - `rules.yaml` 0.7.4 loads;
  - the Go crosswalk tests pass at 0.7.4.
- **E2E on :3900, in EN and VI:**
  - a margin finding → Take Action → Review pricing → task created;
  - Review Items → select 3 → bulk action → one task with 3 items;
  - a draft action shows its banner;
  - a workflow action runs and shows up in run history.

## 7. Left to the builder

- Icons, exact spacing, and the menu component: use the existing UI kit.
- Whether the example workflow preset (§5.6) ships in this round or later.
- The exact Vietnamese labels for actions in the pack. Keep them short and use the glossary terms.
- Bulk evidence verification: one evidence scan per request. Fail closed if the scan errors.
- The exact `_impact` expression per metric, within §5.5a's meaning (bigger = worse), checked against the real columns of each evidence SQL.
