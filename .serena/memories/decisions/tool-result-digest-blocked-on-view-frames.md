# Tool-result digest is BLOCKED — the display channel it assumes does not exist (2026-08-06)

## The premise that was wrong
The plan was: large tabular tool results go into the model's context as a digest (counts,
columns, code-computed aggregates, a few sample rows) while `view.ts`'s `deriveFromToolResult`
keeps carrying the full rows to the UI, so nothing the user sees is lost.

**`onView` is never passed.** `runToolRounds` is called in exactly two places, both in
`src/app/api/chat/route.ts` (~line 639 and ~869), and neither passes `onView`. So
`deriveFromToolResult` never runs in production, no `t:"view"` frame is ever emitted, and
`DisplayPanel` in `components/constellation` never receives anything. Separately, `DisplayPanel`
only exists under `constellation` (Larvis) — the text `/chat` page has no table surface at all.

Consequence: **the rows reach the user only through the text the model writes.** Any reduction
of the conversation copy is straight data loss, in BOTH modes.

## Measured, then reverted
12-question sweep with the digest wired (threshold: >6000 chars AND >=10 rows; aggregates
computed in code; 5 sample rows):

| | control | digest |
|---|---|---|
| total | 332.5s | 276.7s |
| Q2 "show every refund by Sarah Miller" | listed them (8041 chars) | **"cannot provide the full list"** — 614 chars, refused |
| Q4 | found all 9 | asked for clarification, no data |
| Q11 | full table | full table (used avg variance instead of sum) |
| Q12 | 11 tool calls | **24 tool calls** (cap is 25), 72.6s |

Faster, but Q2 — a question that literally asks for a listing — became a refusal, and Q12
nearly hit the round backstop re-querying for the rows it no longer had. Code removed.

## What has to happen first
Wire the view channel end to end before re-attempting: pass `onView` from the chat route, emit
the `t:"view"` frame, and give the TEXT chat a table surface (today only Larvis has one). Until
a result's rows can reach the user without passing through model tokens, digesting the context
copy cannot be safe.

Note also `pickTurnView` shows only ONE table per turn (the last descriptor), so even once
wired, a turn running several queries still has un-displayed results — a digest note must
never claim "the full table is already displayed".

Related: `mem:decisions/nl-query-pinning-rejected`, `mem:checkpoint/perf-latency-2026-08-06`.
