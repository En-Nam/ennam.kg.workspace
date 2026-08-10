# Notes attached to tool results do not change what the model says — measured 2026-08-10

Do not build another "append a sentence to the tool result" guard without reading this.

## What was tried, in order, all against the same probe
Probe: "Which employee refunds the most?" in a FRESH LAAM conversation, gpt-oss-120b.
The question is genuinely ambiguous (most refund TRANSACTIONS vs largest refund AMOUNT) and
the model resolves it to "the highest total refund amount" about half the time, deciding a
measure the user never named.

### Step 1 — remove the tool-description clause that INVITES the rewrite
`kg_query_datasource` said "Prefer questions with aggregates or limits". That tells the caller
to restate the question WITH a metric while context.ts P1/P3 tell it to keep the user's
wording — a real self-contradiction. Replaced with wording that keeps the truncation warning
but forbids adding an aggregate the user did not name.

| | runs | verbatim | rewritten |
|---|---|---|---|
| before | 8 | 4 (50%) | 4 |
| after | 13 | 6 (46%) | 7 |

**No effect.** Deploy verified by grepping the running binary (new string present, old absent),
so this is not a stale-build result. Matches the R1 note already in `context.ts`: fixing a tool
description is not enough, the model still chooses wrong.

### Step 2 — annotate the tool RESULT when the sent query ≠ the user's words
New `LAAM/src/lib/agent/rewrite-notice.ts`: disclose-only (never orders a re-ask, because
`mem:decisions/nl-query-pinning-rejected` already measured re-asking as faster AND wrong).

**Also no effect: 0 of 4 rewritten runs disclosed anything.** The answers named the measure
they had chosen ("tổng số tiền hoàn trả là 3.689,32 USD") but never that a choice existed.

Critically, this is NOT a wiring bug. `rewrite-notice.wiring.test.ts` feeds the EXACT args and
`{text:"<json>"}` envelope pulled from `chat_tool_call` and proves the note attaches on both
the submit call and the id-only poll call, and `digestToolMessageContent` spreads siblings so
it survives to the model. The note reaches the model and the model does not act on it.

The same run also showed DAAB's own `ranking_note` (measure_ambiguity.go, working correctly,
fired on every verbatim run) going unrelayed in the answer.

## The generalisation
Every remaining idea in this family — including a `user_question` side channel so DAAB can
detect ambiguity despite the rewrite — still ends with a note the MODEL must choose to relay.
That step is the one measured to fail. The lever is exhausted.

## What to try instead
Surface it in the UI without the model's cooperation. LAAM already renders code-derived frames
beside answers (`onView` / `annotatePanelShown` / the proactive alert card), and a note DAAB
emits about how it read the question belongs in that channel: the reader sees it whether or not
the model mentions it. That is Rule 5 — if code can decide it, code decides it — and it is the
only shape here that does not depend on the model obeying an instruction it has now ignored
in five separate mechanisms (P1, P2, P3, R1, and both notes above).

Related: `mem:decisions/nl-query-pinning-rejected`, `mem:checkpoint/claude-code-2026-08-10`.
