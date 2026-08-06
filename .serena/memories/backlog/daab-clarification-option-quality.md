# DAAB clarification OPTION quality — bundling FIXED, misdescription still open

Status after commit `d7cfc16` on `ennam.kg.go` (branch `task/implement_docs_sync`).
The ask-back mechanism itself is healthy; these are about WHAT the options say.

## FIXED — bundling (was Defect 1)
An option used to read "the system-recorded quantity **or** the counted quantity" — two columns
in one choice, so picking it decides nothing. Same shape had bundled `counted_quantity` with
`variance_quantity`: **0 rows vs 471 products**, i.e. a coin flip.
Rule added: each option maps to exactly ONE column + ONE aggregation; two candidate columns are
two options. **Measured after: 3/3 runs clean, every option single-column.**

## MOSTLY FIXED — off-target readings (was Defect 2)
A follow-up used to offer "the variance" *inside* the user's already-chosen "latest recorded
count is negative". A variance is not a stock level and is the reading that caused the original
wrong answer. Rule added: an option must measure what the question asks (a LEVEL question is not
answered by a DIFFERENCE column, and vice versa); when the wording or an earlier answer narrowed
the reading, options must stay inside that narrowing.
**Measured after: 2/3 runs no longer offer variance at all.** Where it still appears it is an
explicitly labelled choice among several, not a silent pick — a different order of risk.

No over-asking introduced: "Which store has the most employees?" and "Show duplicate refunds
across stores." both still `completed` directly.

## STILL OPEN — the model MISDESCRIBES a column's meaning (new, and the worst of the three)
One run explained option 3 as:
> "inventory variance is negative, meaning **the counted amount is higher than the system amount**"

Backwards. Verified in `pharmacy_demo`: `variance_quantity = counted_quantity - system_quantity`
(18−21=−3, 69−71=−2, 8−10=−2), so a negative variance means counted is **LOWER**. A
non-technical user picks based on exactly that sentence, so a wrong explanation is worse than an
extra option.

**This is an information gap, not an instruction gap — do not try to fix it with another prompt
rule.** The model receives only `name (data_type)`: `buildSchemaContext`
(`internal/service/query_intent.go`) renders NONE of the three description fields that
`source_columns` already has (`description`, `user_description`, `column_comment`), and all
three are empty for the Pharmacy POS DB anyway (the source DB has no `COMMENT ON COLUMN`
either). So it guesses from the name.

Two separable pieces:
- (a) **Rendering** — include a column description when one exists
  (`user_description` > `description` > `column_comment`). Pure formatting, unit-testable in Go
  with no LLM call, benefits every data source. Does not fix this dataset on its own.
- (b) **Curation** — fill `user_description` for the ambiguous columns. Writes to the user's
  data; their call.

## Minor, unchanged
One sampled clarifying question just echoed the user's question back as the stem
("Which products have negative inventory?"). Harmless, low priority.

## Probe harness
`scratchpad/laam_test/ask.sh` (+ `daab.env`, scratchpad only, never committed) — hits
`POST /api/v1/ai-queries` directly, ~10s per sample, bypasses LAAM so the planner is the only
variable. Use this, not the LAAM chat path, for planner-prompt work.
