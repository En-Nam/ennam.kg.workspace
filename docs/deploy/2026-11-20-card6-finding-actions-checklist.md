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

## Follow-ups (branch `task/improve_by_feedback_19112026`, LAAM up to `edc0d17a`)

Covers the 18 follow-up tasks (spec `docs/superpowers/specs/2026-11-20-card6-followups-design.md`). **No DB migration.**

### Env

- `RESEND_API_KEY`, `MAIL_FROM`: optional. When unset, task notices are bell-only and the app logs `[mail] not configured; task notices are bell-only` once. When set, assignment / due-soon / overdue / pack-reminder emails are sent.
- `AUTH_URL`: must be the public origin. Email links are built from it only.

### Owner confirmations before deploy

- **First tick after deploy:** every open task that went overdue in the last 14 days (`OVERDUE_LOOKBACK_DAYS`) gets one overdue notice to its owner and creator (bell, plus email if Resend is set). Confirm this is acceptable.
- **Due-soon timing (owner decision 2026-11-20):** sent 39h before the due instant, about 09:00 local time the day before.
  - Tasks saved before this deploy store UTC 23:59:59. Their notice still lands on the day before, at an odd hour: about 16:00 in Vietnam, about 04:00 in New York.
  - In UTC-9 and further west (Hawaii, Alaska), legacy rows get it two days early.

### Steps

1. Merge, then `docker build -t laam-app:latest .` and `docker compose up -d app`.
2. Check that the tick is running: `docker logs --tail 5 laam-v2-tick`. `Could not resolve host: app` or `Failed to connect` are expected only while the app container is being recreated, and should stop after it is up. Locally the tick resumed by itself; restart `laam-v2-tick` only if the errors continue.
3. **Refresh installed Sales finding-action presets.** Changing the template does not update copies already installed in orgs; an old copy keeps the email subject `… - {{trigger.finding.ruleId}}`, so the rule code shows in the email. Run from `LAAM/` with the prod `.env`:
   - Dry run first: `npx tsx scripts/refresh-sales-finding-presets.ts`. Read each line, especially the `re-consent=` count per workflow.
   - Then `npx tsx scripts/refresh-sales-finding-presets.ts --apply`.
   - It only replaces a prompt or subject that still exactly matches a shipped template version. A user edit is reported and left alone, and a row saved during the run is skipped (`skipped: changed during run`). Running it again is a no-op.
   - Like an admin save, a changed email subject makes members with an activated copy consent again, and pauses their schedules until they do.
   - Locally it updated "Draft a promotion proposal" and "Vendor cost review request"; the second run reported `unchanged=2`.

### Behaviour to know (support)

- A reader who can't see a finding's wording (for example, a store manager on a chain-wide finding) sees a neutral task title everywhere: bell, email, task card and API. A store-scoped creator also sees the neutral title on tasks they named themselves.
- Sharing a workflow now runs the same check as Save. A workflow with an empty AI step or a mail step with no recipient can't be shared until it is fixed. The message is generic and doesn't name the step.
- The task card shows the due day in the project time zone, "Quá hạn" (red) when overdue, and "Sẽ nhắc: 1 ngày trước hạn".

### Verified before handover (2026-11-20, follow-ups)

- **Tests:**
  - Unit: 9676 pass.
  - Int: all pass except the pre-existing `org-connection.int.test.ts:131`.
  - `tsc` is clean and `npm run build` passes.
- **Browser E2E on :3900, VI and EN**, with Resend unset (bell-only), so no real email was sent:
  - Grouped menu.
  - Create notice and its "Xem task" link.
  - Due day and reminder line on the card.
  - Bulk task with 3-item preview and the "Xem tất cả" dialog.
  - Readable save error.
  - AI finding mode, which adds `{{trigger.items}}` once.
  - Preview dialog: labels, "Chưa gửi gì…", Confirm disabled for a refused recipient.
  - Store manager: assignment bell, 404 outside scope, no wording or task title on a partial-view finding.
  - Overdue tick: neutral title to the store manager, real title to the creator, once each.
- **E2E findings fixed and re-verified on :3900 (LAAM `8138ecff`):**
  - The preview subject no longer shows the rule code after the refresh script runs.
  - The AI builder chat no longer shows raw tool-call text, and the old "Save failed" banner clears after an AI rebuild.
  - `{{trigger.finding.*}}` is refused on Save with a readable message.
  - New bell notices format the due date in the reader's language. Notices created before the deploy keep the date as it was stored.
  - Tests: unit 9710 pass, `tsc` is clean and `npm run build` passes. The integration tests for the touched areas pass.
- **E2E re-run 2026-11-25 and small fixes (LAAM up to `d2dc344e`):**
  - The full browser E2E re-ran on `8138ecff` and passed. The tick sent the due-soon and overdue notices once each, over real days.
  - `a31ccd03`: "Deselect these" in an overlap now also unticks those rows in the items table and the toolbar count. The form closes when nothing is left.
  - `ad5988b4`: overdue tasks under "Earlier tasks" show the "Overdue" chip.
  - `d2dc344e`: the workflow dialog on the finding page is titled with the rule name in the reader's language, the same as on the items page.
  - These are UI-only: no migration and no API change.
  - Tests: unit 9715 pass, `tsc` is clean and `npm run build` passes. Re-verified in the browser on :3900, in EN and VI.
  - Known and not blocking: the workflow email subject `{{trigger.finding.title}}` is still the English pack wording. A localized variable and VI presets are a follow-up.
- **Mail and UI, 2026-11-25 (LAAM up to `43d1dda7`):**
  - `d73c907e`: task notices and the password-reset mail now use one product layout, in one language per mail. Spec: `docs/superpowers/specs/2026-11-25-mail-layout-design.md`.
    - **Behaviour change:** a recipient with no profile "Reply language" used to get Vietnamese mail. Now they get the finding project's `localeDefault`, else English. The reset mail is no longer bilingual: it uses the profile language, else English.
    - Subjects of task mails and the bell rows are unchanged.
  - `43d1dda7`: spacing fixes on the workflow pages (the Schedule and Finding-action sections; "Use this template" on its own line).
  - **Mail sending is set up:**
    - Resend domain `mail.exnodes.vn` is Verified. Its DNS (DKIM, `send.mail`/`rsend.mail` CNAMEs, `_dmarc` p=none) is on Mắt Bão, and Google Workspace mail is untouched.
    - Prod env `laam-app.env` now has `RESEND_API_KEY` and `MAIL_FROM="AIO Analytics <no-reply@mail.exnodes.vn>"`. The closing `>` was missing at first and has been fixed.
    - Samples of all 5 mail kinds reached Gmail, but under All Mail rather than the Primary tab (new domain).
  - Tests: unit 9729 pass; mail int tests (password forgot/reset, task-assign notice, deadline sweep, reminders) 52 pass; `tsc` and build pass.
