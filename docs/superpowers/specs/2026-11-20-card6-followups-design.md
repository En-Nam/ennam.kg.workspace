# Card #6 follow-ups: walkthrough fixes, task reminders, AI builder for finding actions

Date: 2026-11-20
Branch: `task/improve_by_feedback_19112026`. No merge, push or deploy until the owner says so.
Parent spec: `2026-11-20-finding-quick-actions-design.md`. Trello card #6: https://trello.com/c/NFJVFEt3

## 1. Why

The owner walked through card #6 in the browser, as a store user and then as an admin building a workflow. The features work, but:

- An admin cannot build a finding-action workflow without help:
  - the save error is unreadable;
  - the org copy is read-only for the owner;
  - re-sharing creates a duplicate copy;
  - an empty AI prompt can be saved.
- Non-technical users meet raw codes, English text and unrendered markdown.
- People who are given a task are never told about it. Reminders exist only in the in-app bell, only for 5 pack actions, and nothing in the UI shows that a reminder is scheduled.
- The "Dựng bằng AI" builder does not know a workflow will run from a finding with the user's selected records. It probes data itself, hardcodes ids, and leaves hidden settings that break the save.

**Success means:**
- An admin can build, enable and later edit a finding-action workflow using only the UI.
- An assignee hears about a task when it is given, the day before it is due, and when it is late.
- A store manager can use every screen from card #6 without seeing a code, an English sentence or a raw field name.

## 2. Goals and non-goals

**Goals.** Tracks A–D below, in this order:
- A: admin blockers.
- B: reminders.
- C: AI builder mode.
- D: UI polish.

**Non-goals:**
- Slack or Zalo reminders. The owner chose bell + email.
- Phase 3 external writes (card #7).
- Changing how findings are produced.
- A task reassignment feature (none exists today).

**Anti-goals:**
- Any change that sends a real email or external write during tests or E2E.
- Restricted finding wording leaking into an email.
- An email failure that rolls back a task or stops the reminder sweep.

## 3. Owner decisions (2026-11-20)

- **Channel:** in-app bell + system email (the existing Resend path in `src/lib/mail/resend.ts`, used today for password reset).
- **When to remind:**
  - when a task is assigned;
  - 1 day before the due date;
  - when overdue.
- **AI builder:** an explicit toggle in the "Dựng bằng AI" panel, "Workflow này chạy từ một phát hiện". No guessing from the prompt.
- **Menu and bulk toolbar:** grouped into sections (Tạo việc / Việc nháp / Chạy workflow). Decided earlier in the walkthrough.
- **Long item lists on a task card:** option A. Show the first 3 items, then "Xem tất cả N mục" opens a dialog with search, 20 rows per page, and each row opens its receipt.

- **Pack reminders (`reminder_days: [2, 21]`): kept**, additive to the new ones (owner, 2026-11-20). The due date is optional and only prefilled from `due_days`, so a task with no due date relies on these. The design was approved the same day.

## 4. Approaches considered

### Admin authoring of org workflows

Today, the owner opens the org copy through `loadUsableWorkflow`, which is read-only whenever the owner is also assigned the preset. Re-sharing always inserts a new copy.

- **(a) Owner/admin always gets the managed (editable) view of an org workflow, whether or not they are assigned.**
  - Smallest change: in `GET /api/workflows/[id]`, try `loadManagedOrgWorkflow` first for owner/admin.
  - Edits save through `PATCH /api/org-items/workflow/{id}`, which the editor already uses for managed workflows.
- **(b) Re-share updates the linked copy.**
  - Needs a source link column, a migration, and merge rules for the finding-action config.
- **Chosen: (a).** After (a), editing the org copy in place is the normal path, so (b) is not needed.
  - The share dialog gets a note: "Đã có bản trong bộ công cụ — mở bản đó để sửa", linking to the existing copy if one with the same source name exists in that preset.
  - It stays a note only; no new link column.

### Reminder scheduling

- **Pre-insert rows** in `finding_reminder` at task creation, as today. These go stale when the due date changes, or when the task closes and reopens.
- **Derive at sweep time** from open `task` rows. Use `createOnce` with a dedupe key per (task, owner, dueAt, kind), so a changed due date re-arms the reminder.
- **Chosen:** derive at sweep time for due-soon and overdue. Assignment is sent right after the create transaction commits. Pack fixed-day reminders keep their existing rows (if kept).

### AI builder

- **Toggle (chosen)** vs. inferring from the prompt (rejected by the owner).

## 5. Design

### Track A — admin blockers

**A1. Editable org copy.**
- `GET /api/workflows/[id]`: for owner/admin, a managed org workflow is returned with `readOnly: false, managed: true` even when the caller is assigned its preset. Members keep the read-only view.
- Isolation and route-inventory entries are updated.

**A2. Empty required fields cannot be saved.**
- `assertRunnable` rejects:
  - an agent node with an empty or whitespace prompt;
  - a connector node with a missing required arg.
- The editor shows the problem on the node.

**A3. Friendly save errors.**
- `assertRunnable` / validate errors map to i18n messages that name the step, for example "Bước AI 'Tóm tắt' đang trỏ tới một bước đã bị xoá".
- The problems list highlights the node.

**A4. Dangling references on delete.**
- Deleting a node in the editor removes `extract.from` settings that point at it.
- Args containing `{{steps.<deleted>…}}` are flagged on the node.
- This was the root cause of the first save error in the demo.

**A5. Friendly preview errors.**
- A failed preview shows a readable reason, for example "Bước AI chưa có nội dung yêu cầu" or "Không kết nối được Gmail".
- The raw provider text is logged server-side only.

**A6. Share dialog.**
- Steps are listed in graph (topological) order. Today the order is reversed.
- The note from §4 explains how to edit an existing copy.

**A7. Personal workflow hint.**
- The personal workflow detail page shows a short line under the finding-action area: "Muốn dùng làm nút trên trang phát hiện? Thêm vào bộ công cụ của tổ chức trước." Shown to owner/admin only.

**A8. Sticky footer.**
- The FindingActionCard "Lưu" button and any bottom-of-page action respect `--intel-footer-h` / page bottom padding, so the footer never covers them.

### Track B — task reminders (bell + email)

**B1. Assignment notice.**
- After the create-task transaction commits, notify the owner unless the owner is the creator. A bulk selection is one task, so one notice.
- **Bell:** "Bạn được giao việc: <task title>, hạn <date>".
- **Email:** same text plus a link to the finding.

**B2. Due tomorrow.**
- The workflow tick sweep finds open tasks with `dueAt` within the next 24h whose due-soon notice has not been sent for this (task, owner, dueAt).
- It notifies the owner by bell + email.

**B3. Overdue.**
- The sweep finds open tasks with `dueAt < now`.
- It notifies the owner, and also `createdBy` when different, once per (task, owner, dueAt). It does not repeat daily.

**B4. Email rules:**
- Sent through `src/lib/mail/resend.ts`. If the key is unset or sending fails, log and continue: the bell notice still goes out and the sweep never fails.
- The recipient must still be enabled and able to see the finding (the existing `recipientCanSee`). Otherwise skip.
- Email text never contains the finding's wording. It uses the task title, which is the user's own text, or the neutral title, plus a link. The same rule applies today in the bell.
- Language is the recipient's language preference (vi/en/zh), defaulting to vi.

**B5. Visible on the task card.**
- The card shows the due date, and when late, an "Quá hạn" badge.
- It shows the next scheduled reminder, e.g. "Sẽ nhắc: 1 ngày trước hạn".

**B6. Time zone (builder's call).**
- Today `dueAt` is end of the due day in UTC (`endOfDayUtc`, `src/lib/intel/actions.ts:250`). For a US project that makes a task "overdue" on the afternoon of its own due day.
- New tasks store `dueAt` as the end of the due day in the project's time zone (`business_project.timezone`). Due-soon and overdue compare against that instant.
- Existing rows are left as they are.

**B7. Pack fixed-day reminders.**
- Kept as today (owner decision). They now also send email under the B4 rules, and appear in the B5 "Sẽ nhắc" line.

### Track C — "Dựng bằng AI" finding-action mode

**C1. Toggle.**
- The panel gets "Workflow này chạy từ một phát hiện".
- When the workflow already has finding-action config, the toggle is on by default.

**C2. When the toggle is on:**
- The data probe is skipped.
- The prompt gets the catalogue of `trigger.finding.*`, `trigger.items` and `me.email`, and the rules: read the selected records from `trigger.items`, never query data again, writes are terminal, no foreach around writes.
- `findingActionGraphProblems` runs as a planGuard check, so the generated graph passes on the first save.

**C3. Readable node ids.**
- Ids are derived in code from kind plus purpose (e.g. `tom-tat`, `gui-email`), unique per graph.
- The model's ids are never trusted (Rule 13).

**C4. Variable hints.**
- `trigger.finding.*` / `trigger.items` hints show while the toggle is on, or when finding-action config exists. Today they show only after the action is enabled, which is backwards.

### Track D — UI polish (walkthrough list)

1. Take Action menu and bulk toolbar grouped into sections (Tạo việc / Việc nháp / Chạy workflow). The menu flips upward near the bottom of the screen.
2. Review Items:
   - hide columns that are empty in every row;
   - remove the duplicated product info;
   - fix quantity aggregation.
3. After a task is created:
   - show a success notice with a "Xem task" link;
   - use the same default priority on the detail page and the bulk path (Bình thường).
4. Task card:
   - "N mục" shown once;
   - option A dialog from §3;
   - "Việc trước đó" expandable.
5. Workflow dialog:
   - open/close animation (`confirm-dialog` / `useAnimatedClose`);
   - Vietnamese subtitle;
   - an "Chưa gửi gì cho tới khi bạn bấm Xác nhận" line;
   - friendly field labels (Người nhận / Tiêu đề / Nội dung) instead of `gmail_send` / `body` / `subject`;
   - markdown rendered (react-markdown + sanitize);
   - a "how to fix" line for a disallowed recipient (who can add it to the allow-list);
   - long content collapsed.
6. Preset prompts: no metric or rule codes and no "unknown" in generated emails.
7. Workflow page:
   - Vietnamese rule names, with codes hidden or shown small;
   - "Phạm vi: Cả hai" relabelled (Một mục / Nhiều mục / Cả hai → "Dùng cho: một phiếu / nhiều phiếu / cả hai");
   - "Thử" → "Xem trước";
   - section renamed to "Hiện thành nút trên trang phát hiện".

## 6. Constraints

- LAAM rules:
  - i18n in vi/en/zh for every new string;
  - English code comments and commits;
  - Drizzle migrations only;
  - route inventory and isolation cases for changed routes.
- `npm run build` is part of verification (client bundle must not pull `pg`).
- No real email in tests. Email is tested with a fake transport and reported as "not verified end to end" unless a real key is configured.
- No push, merge or deploy without the owner.

## 7. Verification

- Unit + integration suites, `tsc`, and `npm run build` all green.
- Browser E2E on :3900, VI and EN:
  - an admin builds a finding-action workflow with "Dựng bằng AI" (toggle on), saves on the first try, edits the org copy, and previews from a refund finding without sending;
  - assigning a task produces a bell notice;
  - a task due tomorrow and an overdue task produce one notice each after a tick;
  - every item in Track D is checked on screen.

## 8. Builder-check answers and calls (2026-11-20)

**Facts from the code:**
- **A1.**
  - `GET /api/workflows/[id]` (route.ts:13-38) tries `loadUsableWorkflow` first, and falls back to `loadManagedOrgWorkflow` only when that returns null. `withSource` forces `readOnly` for presets (access.ts:25-28).
  - Fix: for owner/admin, check managed first.
  - Saves already go to `/api/org-items/workflow/{id}` (WorkflowEditor.tsx:773). Keep that path's existing version and notify behaviour; add no new re-notify.
- **A2–A4.**
  - `assertRunnable` lives in `src/lib/workflow/validate.ts`, also runs client-side as a preflight, and throws raw English text.
  - A3 first needs structured issue codes (`{code, nodeId, params}`), mapped to i18n in the editor.
  - Empty-prompt and dangling `extract.from` checks are new validators.
  - `stepRefsOf` / `STEP_REF` already find `{{steps.X}}` references.
- **A5.** Two paths need mapping:
  - the start failure (`run_failed_to_start` + `error`);
  - a run that fails later (run row `status` / `error`).
- **A8.** `--intel-footer-h` exists (`intel.module.css:33`). The workflow detail page may need its own bottom padding.
- **B.**
  - The sweep lives in `sweepFindingReminders`, called from `tick/route.ts` inside an isolated try/catch.
  - `recipientCanSee` is private; export it.
  - `createOnce` (notifications/index.ts:83) is keyed on (userId, dedupeKey).
  - `sendMail` (`mail/resend.ts`) returns false and never throws.
- **C.**
  - `generate/route.ts` always calls `probe` (~line 180). The toggle is a new request-body field `findingAction: boolean`, threaded through `generate`, `generate/chat`, `generate/compile` and `append-write`.
  - `findingActionGraphProblems` (`workflow/finding-action.ts`) needs an `mcpReadAllow` set. The generate route must load it (`mcpReadAllow(userId)`) and run the check after `planToGraph`. On failure, do one repair round with the problems listed; if it still fails, return them as editor problems. This is new wiring, not a flag.

**Builder's calls:**
- **Notification kinds** `task_assigned`, `task_due_soon`, `task_overdue`:
  - `createOnce` key `task_<kind>:<taskId>:<userId>:<dueAt ISO or "none">`;
  - text through i18n key + params, like `findingReminder`.
- **Recipient language:** `userProfiles.replyLanguage`, else vi.
- **Email sending:** a helper beside the notify functions, called after commit and never inside a transaction. The B4 rules (enabled user, `recipientCanSee`, no finding wording) apply to B1–B3 and to pack reminders.
- **Due soon:** `now < dueAt <= now + 24h`.
- **Overdue:** one notice to the owner, plus `createdBy` when different, deduped per person. Admins are not notified.
- **Tasks with no due date** get only the assignment notice and any pack reminders. Accepted by the owner (pack reminders kept).
- **Bulk and workflow-created tasks** follow the same rules: one task, one assignment notice, bell + email.
- **A6:** steps are sorted with the topological order already in `validate.ts`.
- **C3:** slug = kind or purpose label folded to ASCII (Vietnamese diacritics removed), plus `-2`, `-3` on a collision.
- **Deploy:** `MAIL_FROM` and the Resend key must be set in prod, or email silently never sends. Add this to the deploy checklist.

## 9. Left to the builder

- Exact Vietnamese wording, matching existing tone.
- Node-id slug rules.
- Which existing notification component renders the new kinds.
- Email HTML layout (reuse the password-reset template style).
