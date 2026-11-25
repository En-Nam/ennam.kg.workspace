# LAAM mail layout: professional task and password-reset emails

Owner-approved 2026-11-25 (option A: "ok A"; "ok làm đi, mà viết tiếng Anh hoặc theo ngôn ngữ system").

## Why

Today the first real Resend send (from `no-reply@mail.exnodes.vn`) arrived as one line of text and a bare link. The owner wants these emails to look like they come from a real product. Gmail also filed that mail outside the Primary tab.

## Goals

- One shared layout for every mail LAAM sends:
  - the 4 task notice kinds (assigned, due soon, overdue, pack reminder);
  - the password-reset mail.
- What the layout shows:
  - the "AIO Analytics" wordmark as text, in the accent colour #1f6f96;
  - a heading per kind;
  - the task title in bold;
  - the due line, in red when the task is overdue;
  - a "View task" button with a plain-link fallback;
  - a small grey footer saying why the reader got the mail and that it is automatic.
  - a hidden preheader line.
- One language per mail. The task mail is in the recipient's profile "Reply language" (vi | en | zh). When that is unset (Auto), it uses the finding project's `localeDefault`, else English. The reset mail uses the profile language, else English. The reset mail is no longer bilingual.
- A plain-text part with the same content.

## Non-goals and anti-goals

- No new information in the mail (option B was declined). The neutral-title privacy rule stays exactly as it is.
- No image logo (it can't load from localhost) and no heavy styling: mostly-text mails are less likely to land in Promotions.
- No new dependency. React Email and MJML were rejected: two mail kinds don't justify one.
- No change to subjects. Task subjects stay the bell line; the reset subject becomes single-language.
- No change to the bell rows.

## Approach

- Hand-written table layout with inline styles, in `src/lib/mail/layout.ts`. It is a pure function: `renderMailLayout({ lang, preheader, heading, lines, cta, footer }) → { html, text }`. Every value is HTML-escaped. With no link there is no button.
- Copy lives in `src/i18n/dictionaries/mail.ts` (vi/en/zh): headings, button labels, due line, fallback text, footers, and the reset copy.
- `taskMail` (src/lib/intel/task-mail.ts) builds the mail through the layout. `sendTaskNotice` and `mailTaskReminder` resolve the language as profile → project → en. That costs one extra lookup from the finding to its project.
- `requestPasswordReset` reads the profile reply language and renders the reset mail in it, through the layout.

## Verification

- Unit tests:
  - each kind renders its heading, button and fallback;
  - escaping;
  - no button without a link;
  - the language fallback order;
  - a neutral reminder still shows only the neutral label.
- `tsc`, the full `npm test` and `npm run build`.
- One real sample of each kind sent to the owner's Gmail, for a visual check.
