# Deploy checklist: Card #6 (finding Take Action / Review Items / bulk actions, workflow finding actions)

Trello: https://trello.com/c/NFJVFEt3. This covers Phase 1 + Phase 2 only. Phase 3 is on hold on card #7: https://trello.com/c/US1doFEP.

- Ships on branch `task/improve_by_feedback_19112026`, together with landed-speed and card #5.
- Deploy only when the owner gives the go. Deploys go main → `deploy-*` branches.
- Spec: `docs/superpowers/specs/2026-11-20-finding-quick-actions-design.md` (§5.7 is the deploy order).

## Order (it matters)

LAAM's pack rule schema is strict. A LAAM that has not been upgraded rejects `actions:`, so **LAAM must go live before the packs v0.7.4 tag**.

### 1. LAAM

- **Migration** `drizzle/0060_fresh_northstar.sql` runs through the migration image (`npm run db:migrate`, never `db:push`). It:
  - adds `task.actionKey` and `task.note`;
  - adds the `task_item` and `finding_reminder` tables;
  - adds `business_project.disabledFindingActions` (`text[]`, NOT NULL, default `{}`; metadata-only on PG15);
  - adds `workflow.findingAction`;
  - adds `workflow_run.findingId`, `triggerInput` and `sentRunId`;
  - adds 3 indexes, created without CONCURRENTLY. Fine at current table sizes.
- **Checks after deploy:**
  - A finding pinned to pack 0.7.3 still opens.
  - Take Action shows the fallback action, e.g. "Review", and creating a task from it works.
  - Settings → project → "Finding actions" section loads.
  - The production build includes the client-safe split `src/lib/workflow/finding-action-schema.ts`. Commit 9bf26dec fixed a build break here, so the deploy build must succeed.

### 2. Packs 0.7.4 (retail + pharmacy)

- Merge `ennam.kg.packs` and `ennam.kg.go` (test pins only) to main.
- Before tagging, `grep -rn "@0.7.3" ennam.kg.packs ennam.kg.go/internal/intel` must return nothing. A published tag cannot be reused; 0.7.1 failed this way.
- Tag `v0.7.4`. That publishes the packs.
- **DAAB:** reload the packs (`POST /api/v1/admin/packs/reload`, or restart). Confirm the projects run packs 0.7.4.
- **What changes:**
  - `actions:` per rule.
  - Evidence SQL now returns `_impact` with worst-first ordering, for `gross_margin_pct`, `refund_rate`, `no_receipt_refund_pct`, `duplicate_refund_groups` and `reprint_before_refund_count`.
  - Duplicate refund pairs stay together.
  - `net_sales`, `avg_unit_cost` and `rx_margin_pct` are unchanged.
- **Timing:**
  - Locally on landed data, `gross_margin_pct` evidence went from 42.9 to 75.5 ms (1.76x, under the 2x limit).
  - **Re-measure on prod** with `EXPLAIN ANALYZE` as `landed_engine` on a 30-day window. If it is above 2x, keep the old ORDER BY for that metric in a 0.7.5.
- **Live-source orgs:** check the evidence page of one margin finding and one refund finding on a live-source project. The `_impact` column must show and the order must be worst-first. This was not verified locally because no live source was configured.

### 3. After both are live

- New analysis runs pin 0.7.4, and their findings show the per-rule actions:
  - Sales Decline: Investigate sales, Review pricing, Create promotion (draft).
  - Margin: Review vendor costs, Review pricing, Analyze margins, Request vendor review (draft).
  - Refunds: Review transactions, Investigate returns, Flag products (draft).
- **Optional, Phase 2 demo:** create the "Sales" preset from its template, then publish and assign it.
  - "Draft a promotion proposal" and "Vendor cost review request" then appear in Take Action.
  - Sending needs the recipient on the org's allow-list and a connected Gmail. Each send goes only to the clicking user's own email, and only after preview → Confirm & send.

## Behaviour to know (support)

- **Actions are configured per rule in the pack.** A project admin can switch individual actions off in Settings → project → Finding actions.
- **Bulk selection.** One shared task is created per selection, max 200 records. Records already in an open task for the same action are refused, and the UI offers to deselect them.
- **Reminders.** `reminder_days` (e.g. 2 and 21 days) create in-app reminders while the task or finding is still open. The workflow tick sends them.
- **Workflow finding actions:**
  - A preview is a dry run. Send replays exactly the previewed writes, once.
  - The preview expires after 24h.
  - If the workflow changes after the preview, the user must preview again.
  - A finding action run that a restart interrupts is failed, never resumed.
  - Closed findings show no actions.
- **No external system writes.** POS, promotion and CRM writes are Phase 3, on hold. Draft actions only create a task with a "Draft:" title and a notice.

## Verified before handover (2026-11-20)

- **Tests:**
  - LAAM: unit 9436 pass, int 1645 pass. The 1 int failure is the pre-existing `org-connection.int.test.ts:131`, which needs the DAAB MCP.
  - `tsc` is clean and `npm run build` passes.
  - Go `internal/intel/...` passes, and the LAAM pack loader passes at 0.7.4.
- **Browser E2E on :3900, EN and VI:**
  - Take Action, then a task with a note.
  - Review Items: impact column, select 3 → 1 task, overlap refused → deselect → task with its item list.
  - Draft notice shown.
  - Sales preset → workflow in the menu → preview lists the write. Send was blocked by the allow-list as designed, and no real email was sent.
