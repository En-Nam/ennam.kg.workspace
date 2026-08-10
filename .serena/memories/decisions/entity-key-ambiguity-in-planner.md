# Planner asks which column defines "the same thing" — 2026-08-10

## The gap
`query_intent.go`'s prompt handled three ambiguity classes: multiple tables, missing column, and
the METRIC ("most" = COUNT or SUM, quantity vs value column…). It had nothing for a fourth,
structurally different one: **which column decides that two rows are the same thing**.

Measured on pharmacy_demo, "Show duplicate refunds across stores." self-joined on the CUSTOMER
three runs in a row — 8, 8 and 2 rows — where the asker meant the originating transaction (9).
The planner was not short of information: `original_transaction_id -> transactions.transaction_id`
is a declared FK and DAAB syncs FKs. It was short of a rule saying that choice is not its to make.

## The fix — generic, no project or connector specifics
One clause in `systemPrompt` and one paragraph in `userPromptTemplate`, phrased entirely in terms
of "the event a row came from, the person involved, the place, the moment". No table names, no
column names, no mention of refunds/stores/DAAB. It also covers the trap in the word "across":
"across stores" names WHERE duplicates are compared, never WHAT makes them duplicates.

Chosen over the alternatives on purpose:
- a playbook with hand-written SQL — rejected by the user, and it is exactly the hardcoded,
  per-project shape this codebase avoids;
- a deterministic post-plan repair (the `rank_direction.go` shape) — code has no principled way
  to know which column is an entity's identity, so it would guess and break working queries;
- a tool-result note — measured the same day as ignored by the model
  (`mem:decisions/tool-result-notes-ignored-by-model`).

The clarification channel was chosen because it is the one channel measured to REACH THE USER:
on 2026-08-10 questions 7, 11 and 12 all asked back and the model relayed every one of them
("Công cụ yêu cầu làm rõ…"), while `ranking_note` on the same runs was never relayed.

## Measured after
| | before | after |
|---|---|---|
| Q4 answers silently with the wrong key | 3/3 | **0/3** |
| Q4 asks back | 0/3 | **3/3** |
| Q3 / Q9 / Q10 still answer directly (no over-asking) | yes | yes, 2 tool calls, same answers |

Q9's wording contains "repeated" and still answered directly — the rule does not fire merely on a
duplicate-ish word, only when the key is genuinely under-determined.

## Known limits — do not oversell this
- The OPTIONS vary run to run. Across three runs the offered readings were: identical
  attributes / same employee; same customer / same original transaction; and the `flagged` +
  `flag_reason` column. The ideal reading (`original_transaction_id`) appeared in some runs and
  not others. It reliably stops the silent wrong answer; it does not reliably surface the best
  reading.
- Q5 ("most frequently refunded products") began asking back where it had answered directly
  earlier the same session. That is METRIC ambiguity, already covered by the old prompt, and the
  demo script itself flags Q5 as ⚠️ — so asking is defensible, but n=1 each way and it cannot be
  confidently attributed to this change.
- Net effect on a demo: more clarification round-trips. That is the deliberate trade the codebase
  already made in `rank_direction.go` — "a clarification is survivable, the reader sees it; an
  inverted table is not."
