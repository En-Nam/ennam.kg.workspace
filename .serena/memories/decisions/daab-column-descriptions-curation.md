# Column descriptions in `source_columns` — what they fix, and what was written

Decision + record of the first curation, 2026-08-06. Code side: `1dee4a0` on `ennam.kg.go`
(`columnDescription()` + rendering in BOTH context paths). Related:
`mem:backlog/daab-clarification-option-quality`.

## Where this data lives — NOT the customer database
`source_columns` is in **`ennam_kg`** (DAAB's own metadata store), not in the connected source
DB. Verified: `to_regclass('public.source_columns')` is non-null in `ennam_kg`, NULL in
`pharmacy_demo`. They merely share a Postgres container. DAAB also cannot write to a source DB
at all — `source_executor.go` opens read-only single-use connections and additionally issues
`SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` on Postgres.

## Why curate at all
The planner used to see only `name (data_type)`, so for similarly-named numeric columns it
guessed — and guessed WRONG in ways that reached the user as confident answers. Descriptions
are the only channel that carries column MEANING to the planner.

## What was written (6 columns, all with MEASURED prior confusion)
Semantics were verified against real rows BEFORE writing — a wrong description would be worse
than none.

`inventory_snapshots`
- `system_quantity` — book quantity.
- `counted_quantity` — physically counted; the column to use for "how much stock / below zero".
- `variance_quantity` — `counted - system`; NEGATIVE = shelf LOWER than books. Marked explicitly
  as a DIFFERENCE, not a stock level. (Verified: 18−21=−3, 69−71=−2, 8−10=−2.)
- `variance_value` — `variance_quantity x unit price`; notes that ranking by money can come out
  in the OPPOSITE order to ranking by quantity.

`cash_drawers`
- `cash_variance` — `counted_cash - expected_cash`; NEGATIVE = shortage; the column that decides
  whether a session had one. (Verified against expected/counted pairs.)
- `flagged` — **the important one.** A narrow fraud-review marker on only **7 of 568** sessions
  (reason "Repeated shortage with elevated no-sale opens"), while **263 other sessions with a
  cash shortage are NOT flagged**. The description says outright: this is not a shortage
  indicator, use `cash_variance < 0`.

## Measured effect
- **Q9 "repeated cash drawer shortages": 3/3 direct probes now generate SQL on `cash_variance`
  (previously `flagged`, which returned the wrong employee), and they no longer ask a
  clarification at all — the description removed the ambiguity.** Result: Robert Reed, EMP-0100,
  9 — correct. End-to-end through LAAM: same answer, 4 tool calls, no clarification round.
- **Q8: the backwards explanation is gone.** It used to describe a negative variance as "the
  counted amount is higher than the system amount"; both probes now say counted is LOWER.
  Variance is still OFFERED as one option, but it is now correctly labelled, so a user can tell
  it apart — which is the point of asking.

## Revert
All six were NULL before. `UPDATE source_columns SET user_description = NULL WHERE …` restores
the previous state exactly; nothing else was touched.

## Note for whoever curates next
Write descriptions only after verifying the semantics against real rows. State the FORMULA where
one exists, the SIGN convention, and — most valuable of all — what the column is NOT
(`flagged` is the model case: saying "this is not a shortage indicator, use cash_variance" is
what actually changed the planner's behaviour).
