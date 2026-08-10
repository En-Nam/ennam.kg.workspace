# Pinning the user's question for NL-query tools — TRIED AND REJECTED (2026-08-06)

Do not re-attempt this without reading the numbers below. Two variants were measured; both lost.

## The problem it tried to solve
One user question, "Show duplicate refunds across stores.", reached DAAB in six different
rewrites (see DAAB's `ai_queries` log). The rewrite decided the answer: 0, 9 and 18 rows for
the same question. Rewrites naming `refund_id` (the primary key) or listing display columns
are empty by construction, and the turn then answers "there are no duplicate refunds" — a
confident all-clear on a fraud question. `context.ts` rules P1/P2/P3 already forbid exactly
this rewriting and the measured runs violated all three, so a code fix was attempted.

## Variant A — APPEND the user's question to the model's text. Dead.
Tested straight against DAAB (no LAAM), 12 runs over the three real rewrites from the log:
verdicts were **identical** with and without the appended original. Once the text names a
column the planner locks onto it; extra context does not undo it.

## Variant B — REPLACE the model's text with the user's, first query call of a turn only.
Rationale for "first call only": `context.ts` rule M1 tells the model to SPLIT a multi-metric
question into one call per metric, and pinning every call would destroy that.

12-question sweep, pin OFF vs ON (same build, same session):

| | OFF | ON |
|---|---|---|
| total | 332.5s | 229.9s |
| Q4 duplicate refunds | **found all 9** | "no duplicates" (WRONG) |
| Q8 negative inventory | correct ("none") | lists variance<0 products (WRONG) |
| Q11 compare 5 stores | **full table** | clarifying questions only, no data |

Faster and worse on every discriminating question. Two independent causes, and they pull in
opposite directions so no small patch fixes both:
- Q4 leaked through the hole deliberately left for M1 — the turn made 7 tool calls, so the
  model simply issued a second, unpinned query in its own words and answered from that.
  Closing the hole (pin every call) is what M1 exists to prevent.
- Q11 broke exactly as predicted: its first call got pinned back to the whole compound
  question, so the split never happened.

Code was removed rather than left behind an off-by-default flag (Rule 2/3 — no dead code).

## What this tells the next attempt
The lever is NOT "which text reaches the connector". Note that the OFF arm above produced the
best Q4 and Q11 results of the whole session, on a build that already had
`mem:checkpoint/perf-latency-2026-08-06`'s empty-result note plus
`CHAT_REASONING_EFFORT_FINAL=low`. Look there, and at the tool-result digest, before
re-litigating question text.
