# Card #5 — Chat UI bugs & clickable results (BUG-01/02/03)

Trello: https://trello.com/c/iOc1wW5w · Repo: LAAM · Branch: `task/improve_by_feedback_19112026` (no merge/deploy; ships with card #4-speed).

## Intent
Beta users read 50-row refund tables in chat. In English the table controls are Vietnamese (BUG-01), the ids
in the table are dead text (BUG-02), and the model asserted "no original receipt" from a refund *reason* while
the source flag said the receipt was present (BUG-03). Fix all three without changing chat layout/colours.

## Goals
- BUG-01: every app-controlled label in chat result tables (and other chat states found while there) goes
  through i18n vi/en/zh. Source data stays as-is.
- BUG-02: record ids in chat result tables open the existing right-side `ReceiptDrawer`; chat and its scroll
  position stay; keyboard accessible; not-found/no-permission = same not-found state.
- BUG-03: a system rule + regression test: source fields are reported separately (receipt flag ≠ refund
  reason → review flag, not a cause); future-dated records are flagged without an invented cause; missing
  currency → "currency not specified".

## Non-goals
- Drawers for store / employee / customer / register (no detail view exists; they stay plain text).
- Whole-row click (only id cells are clickable — one obvious target per record, no ambiguity on rows with
  both a refund id and a sale id).
- Client-side caching of the project lookup (add only if measured slow).
- Any DAAB change.

## Anti-goals
- A chat click must never read a project the user cannot see; the client never chooses the project.
- No DAAB/connector-specific identifiers in runtime prompt strings (LAAM stays connector-agnostic).

## Approaches (BUG-02 project resolution)
- **A — resolve from the table's source (chosen by owner).** The view's `toolName` is `mcp__<slug>__<tool>`.
  Server maps slug → the org connection's DAAB project id → the user's visible intel project (`scopesOf`)
  with the same `daabProjectId` (case-insensitive). Correct with several projects.
- B — Home's preferred-project cookie / first scope. Simpler, wrong project when a user has several.
  Rejected.

Performance (owner asked): rendering adds nothing (clickability is a pure column-name + tool-name check in the
browser). Each click is **one** request: the new route resolves the project (a few small DB reads, the same
`scopesOf` lookup every intel page does) and reads the record (`kg_get_record`, the same cost as the
transactions page drawer). No cache now.

## Design
### BUG-01
`ResultTables.tsx`: `+{n} cột`, `{shown}/{total} dòng` / `{n} dòng`, `Xem thêm {n} dòng`, truncation notice →
new keys in `src/i18n/dictionaries/chat.ts` (vi/en/zh). Sweep the rest of the chat components for hardcoded
Vietnamese in loading/error/expanded states and move what is found.

### BUG-02
- Column → entity (pure function, unit-tested): `refund_id` → refund; `sale_id`, `transaction_id`,
  `original_transaction_id`, `original_sale_id` → sale. Everything else (incl. `refund_transaction_id`) plain.
- Clickable only when the view came from an org/personal MCP tool (`mcp__<slug>__…`), the cell is a non-empty
  string ≤ 128 chars. Rendered as a `<button>` styled like a link inside the cell.
- New route `GET /api/chat/records/[server]/[entity]/[recordId]`: session user → resolve project per approach A
  (no match → 404) → same body as the project records route (reuse its logic by extracting a shared helper,
  not by copy). `Cache-Control: no-store`. Unknown / foreign / other store / no project → identical 404.
  Registered in `src/test/route-inventory.ts` with isolation cases (foreign org record, other-store record,
  server slug of another org).
- `ReceiptDrawer` opened with `src=/api/chat/records/<slug>`; it already handles loading / not-found / error,
  focus trap and Escape. Drawer state lives in the chat component, outside the scroll container, so closing it
  does not move the transcript. Focus returns to the clicked id.
- Both surfaces that render `ResultTables` (MessageItem, Constellation ConversationLog) get it.

### BUG-03
Add a sentence block to the chat system rules in `src/lib/agent/context.ts` (generic wording: "trường nguồn",
no connector names) covering the three cases. Regression test in `context.test.ts` asserting the rule is present
in every chat prompt variant and names the three cases (and contains no connector identifiers). The model's
actual answer is non-deterministic, so the REF-000137 case (receipt flag true + reason "No Receipt", date after
today, no currency) is checked end-to-end in the E2E step, not in a unit test.

## Left to the builder
Exact i18n key names; helper extraction shape for the record route; button styling within existing tokens.

## Acceptance (from card QA)
EN + VI labels; click refund id / sale id opens the right record; field mapping shown by the drawer; scroll kept
on close; missing record / permission / loading states; keyboard + narrow layout; discrepancy/future-date
answer. Verified by unit + isolation tests and a chrome-devtools E2E on local :3900 in EN and VI.
