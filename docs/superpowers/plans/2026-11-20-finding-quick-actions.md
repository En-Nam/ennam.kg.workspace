# Finding Quick Actions, Affected Items, Bulk Actions — Implementation Plan (card #6, Phase 1 + 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users act on a LAAM finding from its detail page: create tasks from pack-configured actions, review the affected records, bulk-select them into one task, and (Phase 2) run org workflows as previewed-then-sent finding actions.

**Architecture:**
- **Pack.** Action definitions live in the pack, per rule (`actions:`, pack 0.7.4). One pure function `availableActions` decides what a viewer sees; the UI and the API both use it.
- **Tasks.** Tasks still go through the shared `prepareCreateTask` → `commitPlan` path, which is extended with `actionKey`, item ids and a `task_item` link table.
- **Workflows.** Phase 2 adds a `finding_action` config on org workflows. A preview is a dry run. "Send" replays only the recorded write calls, verbatim, in a new run, guarded by a single-use claim.

**Tech Stack:** Next 16 App Router, React 19, TypeScript strict, Drizzle (drizzle-kit migrations), Postgres 15, zod, vitest (+ jsdom), Playwright. Packs are YAML + SQL (`ennam.kg.packs`). DAAB pack tests are Go (`ennam.kg.go`).

**Spec:** `docs/superpowers/specs/2026-11-20-finding-quick-actions-design.md` (workspace root). Read it before any task: section numbers below (§5.4 etc.) refer to it.

Paths are relative to `LAAM/` unless they start with `ennam.kg.packs/`, `ennam.kg.go/` or `docs/`.

## Global Constraints

**Git and deploy**
- Branch `task/improve_by_feedback_19112026` in every repo (LAAM, ennam.kg.packs, ennam.kg.go, workspace root).
- No branch switching, merging, pushing or deploying. Commit on the branch only.
- `ennam.kg.go` and the other sub-projects are nested git repos: commit with `git -C <repo>`.
- Never `git add` a file that was already dirty before your task. Check `git status` first.

**Database**
- Migrations: `npm run db:generate` then `npm run db:migrate`. Never `db:push`.
- One migration for the whole feature, `drizzle/0060_*.sql` (Task 3). Later tasks must not add migrations unless the plan says so.

**i18n**
- Every user-visible string goes in `src/i18n/dictionaries/intel.ts`, with `vi`, `en` and `zh`. zh may repeat the English.
- Components use `useT(intelDict)`; server code uses `intelT(locale)`.

**Routes and isolation**
- Every new route is added to `src/test/route-inventory.ts` and gets isolation cases in `src/test/isolation/cases.ts`.
- Another org's or project's id returns 404, with the same body as "not found".

**Connector-agnostic**
- No DAAB or connector-specific identifiers in LAAM runtime strings (UI text, task titles, errors).

**Restricted views**
- Partial or peer-hidden views never get finding wording: reuse the `wordingVisible` logic in `finding-actions.ts:55-59`.
- Item rows and labels go only to readers who pass the evidence gate:
  - unrestricted, or
  - `scopeFinding(f, view)?.mode === "full"` and `evidenceReadable(...)`.

**Phase 3**
- Never send anything to POS, promotion, purchasing or CRM systems.
- `mode: draft_task` actions create a task titled `Draft: …` and show the banner "Draft task: nothing is sent to any external system."

**Limits**
- At most 200 items per action, `note` at most 1000 characters.
- At most 10 workflow `fields`.
- A preview can be sent only while it is under 24 h old.
- Evidence UI cap: 500 rows (`EVIDENCE_MAX_ROWS`).

**Pack version**
- Retail and pharmacy both go to `0.7.4`.
- `grep -rn "@0.7.3" ennam.kg.packs ennam.kg.go/internal/intel` must return nothing.

**Before changing a shared function** (`prepareCreateTask`, `commitPlan`, `findingEvidenceHas`, `executeRun`, `rebuildContext`, `withWriteIdempotency`):
- list its callers (grep, or `spectex_get_blast_radius`);
- keep every existing caller's behaviour.

**Per-task tests**
- Run only that task's tests plus `npx tsc --noEmit`.
- The full suite runs once at the end (Task 18).

## Review Focus

1. **A store-scoped user** opens a task a chain-wide colleague created with 12 sales. They must see "12 items" and nothing else: no labels, rows or drawer. Task 6 test `items API hides details from partial reader`.
2. **A double click or two tabs on "Confirm & send"** must send exactly once and say "already sent" the second time. Task 15 test `second send returns already_sent`.
3. **AI-drafted text containing `{{price}}`** is sent verbatim, not interpolated or rejected. Task 15 test `sends braces verbatim`.
4. **An old finding pinned to pack 0.7.3** (no `actions:`) still shows one working action, and creating its task succeeds. Task 4 test `fallback action for rule without actions`, and Task 6 test `fallback action creates task`.
5. **Two different selections of the same size**, for the same owner and action, both create tasks. Re-selecting an item already in an open task returns 409 with that item listed. Task 6 tests `disjoint same-size selections both succeed` and `overlap returns items_in_open_task`.

---

## Phase 1

### Task 1: Pack schema accepts `actions:` + fallback resolver

**Files:**
- Modify: `src/lib/intel/pack/schema.ts` (add `actionSchema`, `actions` on `ruleSchema`)
- Create: `src/lib/intel/actions/rule-actions.ts`
- Test: `src/lib/intel/pack/schema.test.ts` (extend), `src/lib/intel/actions/rule-actions.test.ts`

**Interfaces:**
- Produces:
  - `type RuleAction = { key: string; label: { en: string; vi: string }; actionType: RecommendedAction; scope: "single"|"bulk"|"both"; mode: "task"|"draft_task"; approvalRequired: boolean; dueDays: number|null; personas: string[]|null; reminderDays: number[] }`
  - `resolveRuleActions(rule: Rule, fallbackLabel: (actionType: RecommendedAction) => { en: string; vi: string }): RuleAction[]`

**Steps:**
- [ ] **Step 1: Write the failing tests.** In `schema.test.ts`:
  - a rule with
    ```yaml
    actions: [{ key: review_pricing, label: { en: "Review pricing", vi: "Rà soát giá bán" }, action_type: price_review, scope: both, mode: task }]
    ```
    parses, with defaults `approval_required: false`, `due_days` null, `personas` null and `reminder_days: []`;
  - an unknown key inside an action fails;
  - duplicate `key` within a rule fails with path `["actions", 1, "key"]`;
  - `key` must match `/^[a-z][a-z0-9_]*$/`;
  - `reminder_days` items are integers from 1 to 90, at most 3 of them.

  In `rule-actions.test.ts`: `fallback action for rule without actions`. A rule with `recommended_action: review` and no actions gives exactly `[{ key: "review", actionType: "review", scope: "both", mode: "task", approvalRequired: false, dueDays: null, personas: null, reminderDays: [] , label: fallbackLabel("review") }]`. A rule with actions returns them mapped to camelCase, in order.
- [ ] **Step 2: Run the tests and see them fail.** `npx vitest run src/lib/intel/pack/schema.test.ts src/lib/intel/actions/rule-actions.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `actionSchema`: a `z.strictObject` with snake_case keys: `key`, `label {en, vi}` (both required, min 1), `action_type` (enum `RECOMMENDED_ACTIONS`), `scope` (default `both`), `mode` (default `task`), `approval_required` (default false), `due_days` (int 0–90, optional), `personas` (`ident[]`, optional), `reminder_days` (default `[]`).
  - `ruleSchema` gains `actions: z.array(actionSchema).default([])`, with the duplicate-key check in the existing `superRefine`.
  - `resolveRuleActions` maps the rule's actions to camelCase, or builds the single fallback action when the rule has none.
- [ ] **Step 4: Run the tests and see them pass**, plus `npx tsc --noEmit`. Also run `npx vitest run src/lib/intel/pack` so the existing real-pack loader tests still pass against pack 0.7.3, which has no `actions`.
- [ ] **Step 5: Commit.** `git -C LAAM commit -m "feat(intel): pack rule actions schema and fallback resolver"`

### Task 2: Pack 0.7.4 — rule actions, evidence `_impact`, version pins

**Files:**
- Modify: `ennam.kg.packs/retail/laam/rules.yaml`, `ennam.kg.packs/retail/pack.yaml`, `ennam.kg.packs/pharmacy/pack.yaml`, `ennam.kg.packs/pharmacy/laam/rules.yaml` (PH-MARGIN-001), and every `ennam.kg.packs/*/daab/crosswalks/*.yaml` (`canonical:` pins)
- Modify evidence SQL: `ennam.kg.packs/retail/daab/evidence/{gross_margin_pct,refund_rate,no_receipt_refund_pct,duplicate_refund_groups,reprint_before_refund_count}.sql`
- Modify Go pins and goldens: `ennam.kg.go/internal/intel/pack_070_test.go`, `crosswalk_test.go`, `golden_070_return_test.go`, `engine/query_test.go` (only where they assert versions or evidence columns)

**Interfaces:**
- Consumes: Task 1's `actionSchema` (snake_case YAML shape).
- Produces: pack 0.7.4, in which evidence rows of the listed metrics carry a numeric `_impact` column (bigger = worse), ordered `_impact DESC NULLS LAST` then the old order.

**Steps:**
- [ ] **Step 1: Add `actions:` to the rules** (spec §5.1 table).
  - **Labels:** EN as in the spec. VI is short and uses glossary terms.
  - **RET-SALES-001:**
    - `investigate_sales` (investigate)
    - `review_pricing` (price_review)
    - `create_promotion` (review, `mode: draft_task`)
  - **RET-MARGIN-001, RET-MARGIN-002, RET-VENDOR-001:**
    - `review_vendor_costs` (vendor_review)
    - `review_pricing` (price_review)
    - `analyze_margins` (investigate)
    - `request_vendor_review` (vendor_review, `mode: draft_task`)
  - **RET-REF-001, RET-REF-002, RET-REF-004, RET-X-REPRINT-001:**
    - `review_transactions` (review)
    - `investigate_returns` (investigate)
    - `flag_products` (review, `mode: draft_task`)
  - **Pharmacy PH-MARGIN-001:** the same four margin actions.
  - **Defaults:** set `due_days: 3` on every action. Set `reminder_days: [2, 21]` on `create_promotion` and `request_vendor_review` only.
  - **All other rules:** no actions (they use the fallback).
- [ ] **Step 2: Add `_impact` to the evidence SQL.** For each listed SQL, add the column `_impact`.
  - `gross_margin_pct`: `(COALESCE(l.discount_amount,0) - l.quantity * (l.unit_price - l.unit_cost)) AS _impact`.
  - Refund SQLs: the refund amount column. Where `has_receipt` exists, order `has_receipt ASC` first.
  - Then `ORDER BY _impact DESC NULLS LAST, <old order>`.
  - Do not change `net_sales.sql`.
- [ ] **Step 3: Bump versions to `0.7.4`.**
  - Set `0.7.4` in both `pack.yaml` files and in every crosswalk `canonical: retail@…` / `pharmacy@…`.
  - Update the Go version pins and any golden column lists that now include `_impact`.
- [ ] **Step 4: Verify.**
  - `grep -rn "@0.7.3" ennam.kg.packs ennam.kg.go/internal/intel` → no output.
  - `cd ennam.kg.go && PACKS_DIR=../ennam.kg.packs go test ./internal/intel/...` → PASS.
  - In LAAM: `PACKS_DIR=../ennam.kg.packs npx vitest run src/lib/intel/pack` → PASS (the real 0.7.4 pack parses with `actions`).
- [ ] **Step 5: Time the change on landed data.** Run the changed `gross_margin_pct` and `refund_rate` evidence queries on the local landed demo DB (DAAB dev DB on :5433), as role `landed_engine`, with `EXPLAIN ANALYZE`, before and after.
  - Record both timings in the commit message.
  - If "after" is more than 2× "before", keep the old ORDER BY for that metric (still return `_impact`) and say so in the commit message.
- [ ] **Step 6: Commit** in each repo:
  - `git -C ennam.kg.packs commit -m "feat(packs): 0.7.4 — finding actions per rule, evidence _impact ordering"`
  - `git -C ennam.kg.go commit -m "test(intel): pin packs 0.7.4"`

### Task 3: Migration 0060 — all new columns and tables

**Files:**
- Modify: `src/db/schema.ts`
- Create: `drizzle/0060_*.sql` (generated)
- Test: `src/db/schema.int.test.ts` (extend if it exists, otherwise create `src/lib/intel/actions/schema-0060.int.test.ts`)

**Interfaces:**
- Produces, in Drizzle:
  - **`task`:** `task.actionKey` (text, null), `task.note` (text, null).
  - **`taskItems`** (`task_item`): `id` uuid pk, `projectId`, `taskId` (FK `task.id` on delete cascade), `itemKind` (`"sale"|"refund"|"row"`), `itemId` (text), `label` (text), `row` (jsonb), `createdAt`. Unique `(taskId, itemKind, itemId)`; index `(projectId, itemKind, itemId)`.
  - **`findingReminders`** (`finding_reminder`): `id`, `projectId`, `findingId`, `taskId` (null, FK cascade), `userId`, `remindAt` (timestamptz), `sentAt` (null), `status` (`pending|sent|skipped`). Index `(status, remindAt)`.
  - **`businessProjects.disabledFindingActions`:** `text[]`, not null, default `{}`.
  - **`workflows.findingAction`:** jsonb, null.
  - **`workflowRuns`:** `findingId` (text, null, indexed), `triggerInput` (jsonb, null), `sentRunId` (uuid/text matching the run id type, null).

**Steps:**
- [ ] **Step 1: Write the failing int test** `schema 0060 round-trip`. Insert a task with `actionKey`/`note` and two `task_item` rows. Delete the task; the items are gone (cascade). A duplicate `(taskId, itemKind, itemId)` throws.
- [ ] **Step 2: Run it and see it fail.** `npm run test:int -- src/lib/intel/actions/schema-0060.int.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement.** Edit `schema.ts`, then run `npm run db:generate`, then `npm run db:migrate`. Check that the generated SQL contains only these changes.
- [ ] **Step 4: Run it and see it pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit** the schema, the migration SQL and the drizzle meta: `feat(db): 0060 finding actions, task items, reminders, workflow finding action`.

### Task 4: `availableActions` — what a viewer may use

**Files:**
- Create: `src/lib/intel/actions/available.ts`
- Test: `src/lib/intel/actions/available.test.ts`

**Interfaces:**
- Consumes: `RuleAction` and `resolveRuleActions` (Task 1).
- Produces:
  - `type WorkflowActionDef = { workflowId: string; label: { en: string; vi: string }; ruleIds: string[]; scope: "single"|"bulk"|"both"; personas: string[]|null; fields: FindingActionField[]; reminderDays: number[]|null }`, where `FindingActionField` is defined in Task 12. Import its type from `src/lib/workflow/finding-action.ts`; until Task 12 lands, declare it here and have Task 12 move it.
  - `type MenuAction = { kind: "pack"; action: RuleAction } | { kind: "workflow"; action: WorkflowActionDef }`
  - `availableActions(input: { ruleId: string; ruleActions: RuleAction[]; disabled: readonly string[]; viewer: { canMutate: boolean; persona: string }; selectionCount: number; workflows: readonly WorkflowActionDef[] }): MenuAction[]` — a pure function.
  - `findAction(menu: MenuAction[], ref: { actionKey: string } | { workflowId: string }): MenuAction | null`

**Steps:**
- [ ] **Step 1: Write the failing tests:**
  - `fallback action for rule without actions` (through `resolveRuleActions`);
  - an action in `disabled` (format `"<RULE>:<key>"`) is hidden;
  - `canMutate: false` gives `[]`;
  - an action with `personas: ["store_manager"]` is hidden for `persona: "analyst"`;
  - `selectionCount 0` shows only single/both, `> 0` shows only bulk/both;
  - a workflow shows only when its `ruleIds` include `ruleId`;
  - pack actions come first, then workflows, in input order;
  - stale disabled entries are ignored.
- [ ] **Step 2: Run them and see them fail.** `npx vitest run src/lib/intel/actions/available.test.ts`
- [ ] **Step 3: Implement** the pure filter. No IO.
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(intel): availableActions menu resolver`

### Task 5: Item keys + set-based evidence check

**Files:**
- Create: `src/lib/intel/actions/items.ts` (shared client/server, no server imports)
- Modify: `src/lib/intel/records.ts` (generalise `findingEvidenceHas`)
- Test: `src/lib/intel/actions/items.test.ts`, `src/lib/intel/records.test.ts` (extend)

**Interfaces:**
- Produces:
  - `type ItemKind = "sale"|"refund"|"row"`
  - `type ItemRef = { kind: ItemKind; id: string }`
  - `ITEM_KEY_COLUMNS: readonly { column: string; kind: ItemKind }[]` = `refund_id→refund`, `sale_id→sale`, `original_sale_id→sale`, `product_id→row`, `employee_id→row`
  - `itemKeyOf(columns: string[], row: unknown[]): ItemRef | null`
  - `type ItemRecord = { ref: ItemRef; label: string; lines: unknown[][]; lineCount: number; impact: number|null; partial: boolean }`
  - `groupRecords(columns: string[], rows: unknown[][], idLabels: Record<string,string>, cutReached: boolean): ItemRecord[]` — rows grouped by key, keeping the order of first appearance. `impact` is the sum of `_impact`. `partial` is true when `cutReached` and the record is among the last group(s) whose lines could continue past the cut. Simplest correct rule: the record of the last row is marked partial when `cutReached`.
  - `itemSetKey(refs: ItemRef[]): string` — sorted `kind:id`, joined by `|`.
  - In `records.ts`: `findingEvidenceItems(provider: MetricsProvider, refs: EvidenceRefs, wanted: readonly ItemRef[], view: ScopeView): Promise<{ found: Map<string, { label: string; row: unknown[]; columns: string[] }>; missing: ItemRef[] }>`. It reuses the same pagination and sanitise loop as `findingEvidenceHas`, scans up to `EVIDENCE_MAX_ROWS`, and throws when the provider errors (fail closed).
  - `findingEvidenceHas` becomes a thin wrapper over it, with unchanged behaviour for its existing callers.

**Steps:**
- [ ] **Step 1: Write the failing tests:**
  - `itemKeyOf` follows the priority order;
  - `groupRecords` folds three lines of the same `sale_id` into one record with `lineCount 3` and summed impact;
  - the last record is `partial` when `cutReached`;
  - `findingEvidenceItems` (fake provider) returns found and missing;
  - a row removed by sanitising cannot vouch for an id;
  - a provider error rejects;
  - the existing `findingEvidenceHas` tests stay green.
- [ ] **Step 2: Run them and see them fail.** `npx vitest run src/lib/intel/actions/items.test.ts src/lib/intel/records.test.ts`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(intel): item keys and set-based evidence check`

### Task 6: Tasks API — actions, items, dedup, reminders, item read

**Files:**
- Modify: `src/lib/intel/actions.ts` (`CreateTaskInput`, `WritePlan.taskItems`, `WritePlan.reminders`, `planCreateTask`, `commitPlan`)
- Modify: `src/lib/intel/finding-actions.ts` (`prepareCreateTask`, `ActionDenial`)
- Modify: `src/app/api/intel/findings/[id]/tasks/route.ts`
- Create: `src/lib/intel/actions/finding-menu.ts` (server loader for the menu)
- Create: `src/app/api/intel/findings/[id]/tasks/[taskId]/items/route.ts`
- Modify: `src/lib/intel/home/load.ts` (`FindingDetailModel` gains `menu`, plus `itemCount` per task)
- Modify: `src/test/route-inventory.ts`, `src/test/isolation/cases.ts`
- Test: `src/lib/intel/finding-actions.int.test.ts` (extend or create), `src/app/api/intel/findings/[id]/tasks/route.test.ts`, `.../items/route.test.ts`

**Interfaces:**
- Consumes: Tasks 1, 3, 4 and 5.
- Produces:
  - `loadFindingMenu(ctx: ScopedCtx, finding: Finding, selectionCount: number): Promise<MenuAction[]>`. It loads the rule from the finding's **pinned** pack (`runPackDirs`, as `load.ts` does), the project's `disabledFindingActions`, the viewer's `persona` and `canMutate`, and — from Task 14 on — the matching workflows. Until then it passes `workflows: []`.
  - The `CreateTaskInput` additions: `actionKey?: string; itemIds?: ItemRef[]; note?: string`.
  - `ActionDenial` adds `"action_unavailable" | "items_not_in_evidence" | "items_in_open_task"`.
  - `ActionOutcome` denial payloads: `{ denial: "items_not_in_evidence"; items: ItemRef[] }` and `{ denial: "items_in_open_task"; items: ItemRef[] }`.
  - The tasks route body adds `actionKey: z.string().regex(/^[a-z][a-z0-9_]*$/).optional()`, `itemIds: z.array(z.strictObject({kind, id: z.string().min(1).max(128)})).max(200).optional()` and `note: z.string().max(1000).optional()`.
  - Status mapping:
    - `action_unavailable` → 403 `{code}`;
    - `items_not_in_evidence` → 422 `{code, items}`;
    - `items_in_open_task` → 409 `{code, items}`;
    - `duplicate_task` → 409, as today.
  - `GET /api/intel/findings/[id]/tasks/[taskId]/items`:
    - when the reader passes the evidence gate: `{ count, items: [{kind,id,label,row,columns}] | null }`;
    - otherwise: `{ count, items: null }`.

**Behaviour, from spec §5.4:**
- **When `actionKey` is set:**
  - Resolve it through `loadFindingMenu(selectionCount = itemIds.length)`. If missing → `action_unavailable`.
  - `actionType` = `action.actionType`.
  - Title = `"<label in the creator's locale> (N items)"`, or just the label when there are 0 items, prefixed with `"Draft: "` when the mode is `draft_task`. The neutral-title fallback for hidden wording still applies when there is no label.
  - **Skip** the owner+title+actionType duplicate check.
  - Check the items with `findingEvidenceItems` → `items_not_in_evidence`.
  - An open task with the same `actionKey` that contains any of the items (join `task_item`) → `items_in_open_task`.
  - No items and an open task with the same `actionKey` → `duplicate_task`.
  - `plan.taskItems` = the rows to insert, with `row` = the record's lines.
  - `plan.reminders` = one row per `reminderDays` entry, for the task owner.
  - The `task_created` event payload adds `actionKey`, `itemCount` and `mode`.
- **When `actionKey` is absent** (Assign, chat): the behaviour is unchanged.
- **`commitPlan`** inserts `taskItems` and `reminders` in the same transaction, after the task insert.

**Steps:**
- [ ] **Step 1: Write the failing tests:**
  - `fallback action creates task`;
  - `disjoint same-size selections both succeed`;
  - `overlap returns items_in_open_task` (items listed);
  - an id not in the evidence → 422 with that id;
  - a disabled action → 403;
  - a `draft_task` title starts with `Draft: `;
  - a partial-view creator's title has no wording;
  - the task, `task_item` and `finding_reminder` rows are written together;
  - forcing an insert failure leaves none of them (rollback);
  - `items API hides details from partial reader`: `items: null`, count present;
  - a full reader gets the rows;
  - the old body without `actionKey` behaves exactly as before (existing tests green);
  - isolation: a foreign task id gives 404.
- [ ] **Step 2: Run them and see them fail.** `npx vitest run src/app/api/intel/findings` and `npm run test:int -- src/lib/intel/finding-actions.int.test.ts`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit` and `npm run test:int -- src/test/isolation`. The known pre-existing failure `org-connection.int.test.ts:131` is not yours.
- [ ] **Step 5: Commit.** `feat(intel): action tasks with linked items, dedup and reminders`

### Task 7: Evidence route — top-factor filter + `_impact` display

**Files:**
- Modify: `src/app/api/intel/findings/[id]/evidence/route.ts`
- Modify: `src/components/intel/detail/receipt-format.ts` (`_impact` is shown, not hidden)
- Create: `src/lib/intel/actions/factor-filter.ts`
- Test: `src/app/api/intel/findings/[id]/evidence/route.test.ts` (extend), `src/lib/intel/actions/factor-filter.test.ts`

**Interfaces:**
- Produces:
  - `topFactor(contributingFactors: unknown): { dim: string; key: string; share: number } | null` — the factor with the largest `share` across all breakdowns; null if none.
  - `allowedFactorFilter(contributingFactors: unknown, dim: string, key: string): boolean` — true only when `(dim, key)` is one of the finding's own factors.
  - Evidence route: the optional query param `factor=<dim>:<key>`.
    - When it is allowed, pass `dimsFilter: { [dim]: [key] }` to `provider.getEvidence`. DAAB already supports `dims_filter` and rejects dims the metric does not have, so map that rejection to 400.
    - When it is not allowed, return 400 `"invalid factor"`.
  - `receipt-format.ts`: `isHiddenColumn` keeps hiding `_*` columns **except** `_impact`. `columnLabel("_impact")` is the i18n key `intel.items.col.impact`, formatted as money.

**Steps:**
- [ ] **Step 1: Write the failing tests:**
  - a factor not in the finding → 400;
  - an allowed factor passes `dimsFilter`;
  - a provider "not a dim" error → 400;
  - no factor → the call is unchanged;
  - `topFactor` picks the highest share;
  - `_impact` is visible while `_source_ref` stays hidden.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(intel): evidence top-factor filter and impact column`

### Task 8: Settings — per-project action on/off

**Files:**
- Create: `src/components/intel/admin/FindingActionsSection.tsx`
- Modify: `src/components/intel/admin/ProjectDetail.tsx` (add the section after `ScheduleSection`)
- Create: `src/app/api/intel/admin/projects/[id]/finding-actions/route.ts` (GET and PUT). Match the existing admin API path pattern in `adminApi.ts`; if it differs, use the existing pattern and keep this name.
- Modify: `src/components/intel/admin/adminApi.ts`
- Modify: `src/test/route-inventory.ts`, `src/test/isolation/cases.ts`
- Test: the route test and `FindingActionsSection.test.tsx`

**Interfaces:**
- GET returns `{ rules: [{ ruleId, name, actions: [{ key, label, enabled }] }] }`, built from the project's **installed** pack plus `resolveRuleActions`.
- PUT takes `{ disabled: string[] }`:
  - each entry must be `"<RULE>:<key>"` and exist in the installed pack, otherwise 400;
  - owner and admin only, otherwise 403;
  - it writes `audit_log` `intel.finding_actions.update`.

**Steps:**
- [ ] **Step 1: Write the failing tests:**
  - a member gets 403;
  - an unknown key gets 400;
  - a toggle round-trips;
  - the UI lists the rules with their toggles and saves.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(intel): project settings to switch finding actions off`

### Task 9: Detail page — Take Action menu, ActionForm, task items

**Files:**
- Modify: `src/components/intel/detail/TaskPanel.tsx` (buttons next to Assign, `:183-185`)
- Create: `src/components/intel/detail/TakeActionMenu.tsx`, `src/components/intel/detail/ActionForm.tsx`, `src/components/intel/detail/TaskItemsList.tsx`
- Modify: `src/components/intel/detail/EvidencePanel.tsx` (add a "View all items" link to `/home/findings/[id]/items`)
- Modify: `src/i18n/dictionaries/intel.ts`
- Test: a co-located `*.test.tsx` for each new component, and `TaskPanel.test.tsx`

**Interfaces:**
- Consumes: `FindingDetailModel.menu` (Task 6) and the tasks API (Task 6).
- Produces:
  - `<ActionForm findingId action={MenuAction & {kind:"pack"}} items={ItemRecord[]} owners currency onDone(task) onCancel />`, reused by Task 10.
  - Workflow menu entries call `onWorkflow(def)`, a no-op until Task 16.

**UI rules:**
- **Buttons.** Two compact outlined buttons, `Take Action` and `Review Items`, sit to the right of Assign. Assign is unchanged. They are hidden when `!canMutate`, except Review Items, which needs only read access to the evidence.
- **Form.** Prefill the owner with the default owner candidate, `due` = today + `dueDays`, and `approval` = `approvalRequired`.
  - The banner shows for `draft_task`.
  - 409 `items_in_open_task` shows the listed items with "Deselect these".
  - 422 shows "Some items are no longer in this finding's records".
- **Task card.** It shows "N items" when the task has items. Clicking it opens `TaskItemsList`, which fetches the items API. With `items: null` it shows the count only.
- **Strings.** Add every string in vi/en/zh.

**Steps:**
- [ ] **Step 1: Write the failing tests:**
  - the buttons render next to Assign, and Assign is still there;
  - the menu lists `menu` entries in order;
  - the draft banner shows only for `draft_task`;
  - the 409 overlap view lists the items;
  - `TaskItemsList` with `items: null` shows the count and no rows.
- [ ] **Step 2: Run them and see them fail.** `npx vitest run src/components/intel/detail`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(intel): take action menu and action form on finding detail`

### Task 10: Review Items page

**Files:**
- Create: `src/app/(app)/home/findings/[id]/items/page.tsx`
- Create: `src/components/intel/items/ReviewItemsView.tsx`, `ItemsTable.tsx`, `BulkToolbar.tsx`, `RecordDetailPanel.tsx`, `FactorChip.tsx`
- Modify: `src/i18n/dictionaries/intel.ts`
- Test: a co-located `*.test.tsx` for each component; `e2e/` gets a spec in Task 18

**Interfaces:**
- Consumes: `groupRecords`, `itemKeyOf` and `ItemRecord` (Task 5); `topFactor` and the evidence `factor` param (Task 7); `ActionForm` (Task 9); the menu with `selectionCount` (Task 6 — call `GET` on the detail model or extend the page loader; the page server component loads the menu with `loadFindingMenu(ctx, finding, 1)` for bulk actions).

**Behaviour (spec §5.5, §5.5a):**
- **Access.** Same as the detail page. Full width.
- **Loading.** Pages through the evidence API (`limit=200`) up to 500 rows, with the `factor=` from `topFactor` by default. The chip shows `"<dim>: <key> (NN%)"`; removing it reloads without the factor.
- **Rows.** Rows are grouped into records. The columns are the key label, the impact (when present), the line count, then the evidence columns.
  - Search is a case-insensitive substring match over the visible cells.
  - Pagination is 25 per page.
- **Selection.**
  - Checkbox per record, and select-all on the page.
  - "Select all loaded" caps at 200, with a note.
  - Records with no key are not selectable.
- **Bulk toolbar.** Shows the count and the bulk actions. Choosing an action opens `ActionForm` with the selected `ItemRecord`s. It sticks to the bottom on narrow screens.
- **Row click.** A sale/refund record opens `ReceiptDrawer`; any other record opens `RecordDetailPanel` (all its lines, `cellText` formatting). Partial records show "More lines outside this list".
- **States.** Empty, loading and error states reuse the `intel.evidence.err.*` keys. The table scrolls horizontally inside its card under 768px.

**Steps:**
- [ ] **Step 1: Write the failing tests:**
  - grouping shows one row per sale;
  - the factor chip is present by default and removing it refetches without `factor`;
  - "select all loaded" stops at 200;
  - the toolbar shows only bulk/both actions;
  - a sale row opens the drawer, a product row opens the detail panel;
  - the error state uses the evidence error key.
- [ ] **Step 2: Run them and see them fail.** `npx vitest run src/components/intel/items`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(intel): review items page with grouping, factor filter and bulk actions`

### Task 11: Reminder sweep

**Files:**
- Create: `src/lib/intel/actions/reminders.ts`
- Modify: the workflow scheduler tick in `src/lib/workflow/schedule.ts` (call the sweep once per tick, inside a try/catch that logs and continues)
- Modify: `src/lib/notifications/index.ts` (add `notifyFindingReminder`)
- Test: `src/lib/intel/actions/reminders.int.test.ts`

**Interfaces:**
- `sweepFindingReminders(db: Db, now: Date, limit = 100): Promise<{ sent: number; skipped: number }>`. It takes due `pending` rows (`remindAt <= now`), using `FOR UPDATE SKIP LOCKED`.
  - If the row has a task and that task is still open, or it has no task and the finding is still open: call `notifyFindingReminder` with `createOnce`, `dedupeKey = "finding_reminder:" + id`, and mark the row `sent`.
  - Otherwise mark it `skipped`.
- `notifyFindingReminder(n: { userId; findingId; taskId?: string; title: string })` links to `/home/findings/<id>`. The title must not contain finding wording for users with hidden wording: use the task title, which is already safe, or the neutral label.

**Steps:**
- [ ] **Step 1: Write the failing tests:**
  - a due reminder for an open task → sent, one notification;
  - a closed task → skipped;
  - running the sweep twice → still one notification;
  - a reminder not yet due is untouched.
- [ ] **Step 2: Run them and see them fail.** `npm run test:int -- src/lib/intel/actions/reminders.int.test.ts`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(intel): finding action follow-up reminders`

---

## Phase 2

### Task 12: Workflow `finding_action` config — schema, validation, API, card

**Files:**
- Create: `src/lib/workflow/finding-action.ts`
- Create: `src/app/api/workflows/[id]/finding-action/route.ts` (PUT; GET is covered by the workflow detail payload)
- Create: `src/components/workflows/FindingActionCard.tsx`, wired into `WorkflowDetailClient.tsx` next to `ScheduleCard`
- Modify: `src/test/route-inventory.ts`, `src/test/isolation/cases.ts`, the i18n dictionary used by the workflow components
- Test: `src/lib/workflow/finding-action.test.ts`, the route test, `FindingActionCard.test.tsx`

**Interfaces:**
- Produces:
  - `type FindingActionField = { key: string; label: { en: string; vi: string }; type: "text"|"number"|"select"|"date"; options?: string[]; required: boolean }`. Move the type here from Task 4.
  - `findingActionSchema`: a strict zod schema for `{ enabled, label, ruleIds (min 1), scope, personas (nullable), fields (max 10, unique keys), reminderDays (nullable, ints 1–90, max 3) }`.
  - `nonTerminalWrites(graph: WorkflowGraph): string[]` — returns the ids of write nodes (connector writes per `isWrite`, plus MCP nodes whose action is not in the read allow-list) whose output is referenced by another node's args (`{{steps.<id>…}}`) or by a condition.
  - `validateFindingParams(fields: FindingActionField[], params: unknown): { ok: true; value: Record<string,string|number> } | { ok: false; field: string }`
- **PUT rules:**
  - The workflow must be an **org** workflow managed by the caller: use `loadManagedOrgWorkflow`, which means owner or admin. Otherwise 404/403 as that helper does.
  - Validate the body with `findingActionSchema`.
  - Every `ruleId` must exist in at least one of the org's projects' installed packs → otherwise 400.
  - `nonTerminalWrites(graph)` must be empty → otherwise 422 `{code:"write_not_terminal", nodes}`.
  - Writes an `audit_log` row.
- **Card.** Enable toggle, label EN/VI, a rule multi-select (rules from the org's installed packs), scope, a persona multi-select (pack `roles.yaml` personas), a fields editor (add/remove, max 10) and reminder days.

**Steps:**
- [ ] **Step 1: Write the failing tests:**
  - a personal workflow is refused;
  - a member is refused;
  - an unknown rule → 400;
  - a graph where a Slack post's args use `{{steps.jira1.output.key}}`, with `jira1` a write → 422 listing `jira1`;
  - a valid config round-trips;
  - `validateFindingParams` rejects a missing required field and a wrong type.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(workflows): finding action configuration`

### Task 13: Run plumbing — trigger `finding_action`, durable `trigger_input`

**Files:**
- Modify: `src/lib/workflow/run.ts` (`RunTrigger`, `viaOfTrigger`, the run insert at `:306` and `executeRunRow` at `:219`, both of which use `triggerInput`)
- Modify: `src/lib/workflow/resume.ts:128` and `src/lib/workflow/resume-context.ts` (`rebuildContext` uses `triggerInput`)
- Modify: `src/components/workflows/editor/variableHints.ts`, `src/components/workflows/runDisplay.ts` (label), workflow i18n
- Test: `src/lib/workflow/run.test.ts` / `resume.test.ts` (extend), `variableHints` test

**Interfaces:**
- `RunTrigger` adds `"finding_action"`. `viaOfTrigger("finding_action")` returns `"workflow_manual"`.
- The run-creation function (whatever `executeRun` uses to insert) accepts `triggerInput?: Record<string, unknown>` and `findingId?: string` and stores them at insert time.
- The initial context is `emptyContext({ source: trigger, ...triggerInput })`. `rebuildContext` uses `{ source: run.trigger, ...(run.triggerInput ?? {}) }`.
- Variable hints add `trigger.finding.id|ruleId|metricKey|dims|severity|variancePct|title`, `trigger.items`, and `trigger.params.<key>` for each configured field.

**Steps:**
- [ ] **Step 1: Write the failing tests:**
  - a run started with `triggerInput {finding, items, params}` exposes `{{trigger.items}}` to the first node;
  - after a simulated crash and resume, the rebuilt context still has `trigger.finding.id`;
  - `viaOfTrigger("finding_action") === "workflow_manual"`;
  - the run history label for the new trigger is translated.
- [ ] **Step 2: Run them and see them fail.** `npx vitest run src/lib/workflow src/components/workflows`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(workflows): finding_action trigger with durable trigger input`

### Task 14: Preview route + workflows in the menu

**Files:**
- Create: `src/app/api/intel/findings/[id]/workflow-actions/route.ts` (POST = start a preview)
- Create: `src/lib/intel/actions/workflow-actions.ts`
- Modify: `src/lib/intel/actions/finding-menu.ts` (load the matching workflows)
- Modify: `src/test/route-inventory.ts`, `src/test/isolation/cases.ts`
- Test: the route test and `workflow-actions.int.test.ts`

**Interfaces:**
- `listFindingWorkflows(orgId: string, userId: string, ruleId: string): Promise<WorkflowActionDef[]>`. It returns org workflows with `finding_action.enabled` whose `ruleIds` include the rule and that the user can use (`listUsableWorkflows` / `canUse`). `loadFindingMenu` passes these in.
- `buildTriggerInput(finding, viewerScope, records: ItemRecord[], params, actionConfig): Record<string, unknown>`:
  - `finding: { id, ruleId, metricKey, dims, severity, variancePct, title? }`, where `title` is present only when the wording is visible to the viewer;
  - `items: [{ kind, id, label, cols }]`, where `cols` holds at most 8 key columns;
  - `params`;
  - `actionConfig` (a snapshot of `finding_action`).
- `POST` body: `{ workflowId: string; itemIds?: ItemRef[] (max 200); params?: Record<string, unknown> }`. In order:
  1. finding guard (mutator);
  2. menu check through `findAction`, otherwise 403 `action_unavailable`;
  3. `validateFindingParams`, otherwise 422 `{code:"invalid_field", field}`;
  4. `findingEvidenceItems`, otherwise 422 with the items;
  5. `assertOrgActive` and `assertCanConsume(orgId, "workflow_run")`, mapped as the workflow run route maps them;
  6. `executeRun` with `{ dryRun: true, trigger: "finding_action", findingId, triggerInput }`;
  7. return `{ runId }`;
  8. write a `finding_event` of type `workflow_action_run` `{runId, workflowId, itemCount, phase:"preview"}`.
- `pendingWrites(runId: string): Promise<{ nodeId: string; action: string; args: unknown; recipientCheck?: unknown; capped: boolean }[]>` reads the preview run's steps whose output has `dryRun: true`. `capped` is true when the step output hit the `capForPersist` cap. The UI uses it through the GET in Task 15.

**Steps:**
- [ ] **Step 1: Write the failing tests:**
  - a workflow whose rule doesn't match → 403;
  - a persona not allowed → 403;
  - a missing required field → 422;
  - a valid call starts a dry-run run with trigger `finding_action`, `finding_id` set and `trigger_input.items` populated;
  - partial-view `title` is absent;
  - `pendingWrites` returns the mocked write with its full args;
  - the consume gate refuses when the org is out of tokens;
  - isolation: a foreign `workflowId` → 404/403 with no leak.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(intel): finding workflow action preview runs`

### Task 15: Send route — single-use claim, verbatim replay

**Files:**
- Create: `src/app/api/intel/findings/[id]/workflow-actions/[runId]/route.ts` (GET = preview status plus `pendingWrites`)
- Create: `src/app/api/intel/findings/[id]/workflow-actions/[runId]/send/route.ts` (POST)
- Create: `src/lib/workflow/send-recorded.ts`
- Modify: `src/lib/workflow/idempotency.ts` (extend the write WAL to MCP-node writes)
- Modify: `src/test/route-inventory.ts`, `src/test/isolation/cases.ts`
- Test: `send-recorded.test.ts` and `send/route.int.test.ts`

**Interfaces:**
- `sendRecordedCall(deps: { execute: (action: string, args: unknown) => Promise<unknown>; mcpReadAllow: ReadonlySet<string>; checkRecipient: (action: string, args: unknown) => Promise<{ allowed: boolean; reason?: string }>; db: Db }, call: { sendRunId: string; nodeId: string; action: string; args: unknown }): Promise<unknown>`.
  - It never calls `interpolateArgs`.
  - It calls `assertConnectorAllowed` for connector actions, or `assertMcpAllowed` for `mcp__*`.
  - If the recipient is not allowed, it throws with the reason.
  - It wraps the call in `claimNode` / `recordNodeOutput` keyed on `{ runId: sendRunId, nodeId, iterIndex: 0 }`.
- **`POST …/send`, in order:**
  1. Finding guard (mutator).
  2. The preview run: `trigger = "finding_action"`, `dryRun`, `findingId` = this finding, `userId` = the caller, `status = "succeeded"`, `createdAt` > now − 24 h. Otherwise 404/409 `preview_invalid`.
  3. `requireConsent` on the current workflow row. Return its 409 body as-is, so the dialog can run reactivation.
  4. `requireMutator`, `assertOrgActive`, `assertCanConsume`.
  5. The preview's `authoredHash` equals the current hash (`computeAuthoredHash`). Otherwise 409 `workflow_changed`.
  6. If any pending write is `capped` → 422 `preview_capped`.
  7. **Claim:** create the send run row first (trigger `finding_action`, `dryRun: false`, `findingId`, `triggerInput: { previewRunId }`). Then run `UPDATE workflow_run SET sent_run_id = <send> WHERE id = <preview> AND sent_run_id IS NULL RETURNING id`. If no row comes back, mark the send run `cancelled` and return 409 `already_sent`.
  8. Run each pending write in node order with `sendRecordedCall`, using the clicking user's connectors (`connectorExecute(userId)` via `buildRunNode`'s deps). Record one `workflow_run_step` per write. Stop at the first failure.
  9. Finalize the send run as `succeeded` or `failed`.
  10. Write a `finding_event` of type `workflow_action_run` `{runId: send, previewRunId, phase:"send", status}`.
  11. Return `{ sendRunId, status, results: [{nodeId, ok, error?}] }`.
- A missing connector connection becomes a typed error, `connector_not_connected` `{action}`, raised before the first write: check every pending action's connector first.

**Steps:**
- [ ] **Step 1: Write the failing tests:**
  - `second send returns already_sent`: two concurrent POSTs give exactly one execute call per write;
  - `sends braces verbatim`: args `{text:"Giá {{price}}"}` reach `execute` unchanged;
  - a changed workflow hash → 409 `workflow_changed`;
  - a preview older than 24 h, or another user's preview → refused;
  - a recipient not allow-listed → nothing sent and an error;
  - a missing connector → `connector_not_connected` and nothing sent;
  - the WAL key is the send run's id, not the preview's: the preview's own `done` WAL rows must not short-circuit the send;
  - an MCP write is WAL-covered.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(intel): send previewed workflow writes verbatim, once`

### Task 16: Workflow action dialog

**Files:**
- Create: `src/components/intel/detail/WorkflowActionDialog.tsx`
- Modify: `TakeActionMenu.tsx` and `BulkToolbar.tsx`, so that `onWorkflow` opens the dialog
- Modify: the i18n dictionary
- Test: `WorkflowActionDialog.test.tsx`

**Flow:**
1. **Step 1, form.** Shows the workflow label, the finding, the item count and the configured `fields`. The button is "Preview".
2. **Polling.** Once the preview starts, poll GET `…/[runId]` until it is terminal, with a spinner.
3. **Step 2, preview.** Lists each pending write: destination (action), recipient, and content (`args`, rendered as text, never HTML), plus any allow-list refusal or "too large to send". The buttons are "Confirm & send" and "Cancel". With no pending writes, it shows "Done — nothing to send" and a link to the run.
4. **Result.** Per-write ok or error, and links to both runs in run history.
5. **Errors.**
   - `already_sent` → "Already sent".
   - `workflow_changed` → "Workflow changed — preview again".
   - Consent 409 → the existing reactivation prompt.
   - `connector_not_connected` → "Connect <app> first".
   - Any failure shows "Preview again".

**Steps:**
- [ ] **Step 1: Write the failing tests:**
  - the fields render and a required field blocks Preview;
  - the preview lists the writes as plain text, so content containing `<b>` is not rendered as HTML;
  - `already_sent` shows its message;
  - the no-writes path shows "Done".
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(intel): workflow action preview and send dialog`

### Task 17: Two finding-action presets

**Files:**
- Modify or create: under `src/lib/presets/templates/`, following `schema.ts` / `load.ts` there. Put them in `sales.yaml` (promotion) and in `sales.yaml` or a new `retail-actions.yaml` (vendor cost) if the loader picks up new files. Check `catalog.test.ts`.
- Test: `src/lib/presets/templates/catalog.test.ts` (extend)

**Content:**
- **"Draft a promotion proposal"**
  - `finding_action`: rules RET-SALES-001; scope both; field `discount_pct` (number, required); reminders `[2, 21]`.
  - Graph: agent node (summarise `{{trigger.items}}` and draft the proposal with `{{trigger.params.discount_pct}}`) → one connector **write** (a notify/post action the preset system already uses; the write is terminal).
- **"Vendor cost review request"**
  - `finding_action`: rules RET-MARGIN-001, RET-MARGIN-002, RET-VENDOR-001; scope both.
  - Graph: agent drafts the request from the items → one terminal write.
- Both must pass `nonTerminalWrites(graph).length === 0` and `findingActionSchema`. If the preset schema cannot carry `finding_action`, extend it minimally and say so in the commit.

**Steps:**
- [ ] **Step 1: Write the failing test:** the catalog contains both presets, and each passes `findingActionSchema` and `nonTerminalWrites` is empty.
- [ ] **Step 2: Run it and see it fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run it and see it pass**, plus `npx tsc --noEmit`.
- [ ] **Step 5: Commit.** `feat(presets): finding action workflow templates`

### Task 18: Full verification, E2E, deploy notes (controller)

- [ ] **Step 1: Run the full LAAM suite.**
  - `npm test`, `npx tsc --noEmit`, `npm run test:int -- src/test/isolation` → all green except the known `org-connection.int.test.ts:131`.
  - The Go and pack tests from Task 2 → green.
- [ ] **Step 2: Whole-branch review** (Opus). Fix what it finds.
- [ ] **Step 3: E2E on :3900.**
  - Rebuild: `cd LAAM && docker build -t laam-app:latest . && docker compose up -d app`.
  - Use chrome-devtools MCP. Ask the user to log in when needed.
  - Run each in EN and VI:
    1. A margin finding → Take Action → Review pricing → task created.
    2. Review Items → factor chip → select 3 → bulk "Review transactions" on a refund finding → one task with 3 items.
    3. A draft action shows its banner.
    4. A workflow action → preview → send → both runs are in run history.
    5. A second send says "Already sent".
  - Add `e2e/finding-actions.spec.ts` covering flows 1 and 2.
- [ ] **Step 4: Deploy checklist.** Write `docs/deploy/2026-11-20-card6-finding-actions-checklist.md` with the spec §5.7 order: LAAM with migration 0060 first, then the packs 0.7.4 tag, plus the `grep @0.7.3` check. Then the Serena checkpoint `checkpoint/claude-2026-11-20-card6`.

## Task dependencies (for parallel dispatch)

- Task 1 → Tasks 2, 4.
- Task 3 → Tasks 6, 8, 11, 12, 13.
- Task 5 → Tasks 6, 10, 14.
- Task 6 → Tasks 9, 10, 14.
- Task 7 → Task 10.
- Task 9 → Tasks 10, 16.
- Tasks 12 + 13 → Task 14 → Task 15 → Task 16.
- Task 12 → Task 17.
- These groups can run in parallel:
  - after Tasks 1 and 3: {2, 4, 5, 7, 8, 12, 13};
  - after Task 6: {9, 11};
  - Task 17 at any point after Task 12.
