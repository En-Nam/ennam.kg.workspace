# A self-join that returns half of every pair must say so — DAAB `ec949ac`, 2026-08-07

## The failure it was built for

"Show duplicate refunds across stores." planned a self-join and projected one side:

```sql
SELECT r1.refund_id, r1.customer_id, r1.store_id, ...
FROM refunds r1 JOIN refunds r2 ON r1.customer_id = r2.customer_id
                               AND r1.store_id != r2.store_id
```

Every row is one HALF of a pair; the partner lives in `r2` and is never selected. What reached
the demo UI was a table whose rows all carried `PH-004` under prose asserting they spanned
different stores — and nothing on the page could contradict it, because the SELECT had dropped
the evidence for the claim.

`SELECT *` over a self-join is the same defect in different clothing: both sides come back
under identical column names and a row is scanned into `map[string]interface{}`, so one side
silently overwrites the other. Both shapes were measured live the same day.

## What it does

Detects at PLAN level — same base table twice across `Tables`+`Joins` (schema and alias
stripped), and the select list (`GroupBy`+`Aggregations`, empty meaning `SELECT *`) mentioning
at most one alias. Attaches a note; appended to any ranking note, never replacing it. Reuses
`plan_normalize.go`'s `parseTableEntry` rather than parsing FROM/JOIN a second time.

It deliberately does NOT rewrite the query. Widening the projection or choosing a side means
deciding what the user meant by "duplicate", and this layer has no basis for that. Same
contract as `mem:` rank_direction's note: never guess, never be silent.

## Measured, Q4 × 5 fresh conversations through LAAM

Ground truth: 9 pairs / 18 records (`REF-000003,4,5,6,8,9,10,11,12` + `REF-000223,224,225,226,
228,229,230,231,232`).

| | before any fix | note only (`ce8b51f`) | + self-join note (`ec949ac`) |
|---|---|---|---|
| correct set returned | 0/5 | 1/5 | **3/5** |
| false all-clear | 3/5 | 0/5 | 1/5 |
| asked the user | 1/5 | 3/5 | 1/5 |

Runs 2, 3 and 5 each returned exactly one half of the correct 18 and **said so in the prose** —
"truy vấn trả về chỉ một phía của mỗi cặp" — which is the note reaching the reader, not a
paraphrase of the data.

## What is still broken (and was left alone on purpose)

Run 4 planned the join on `customer_id` again, got 2 rows, correctly distrusted them because of
the note — and then concluded "no duplicate refunds exist across stores". The note changed the
failure from "these two rows are duplicates of each other" to "there are none", which is still
a false all-clear on a fraud question.

The remaining defect is the planner's KEY CHOICE (`customer_id` instead of
`original_transaction_id`). DAAB has the FK metadata to know better — `source_foreign_keys`
carries `original_transaction_id → transactions.transaction_id` — but `customer_id` is an FK
too, so FK-ness alone does not disambiguate. Deciding between them needs either domain meaning
or a cardinality heuristic ("the grouping whose repetition is anomalous"), and the latter is
tuned to this dataset. Rejected for now as demo-fitting in code rather than in the DB.
