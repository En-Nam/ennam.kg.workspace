# Q4 "Show duplicate refunds across stores." — resisted FOUR prompt attempts. Needs code, not words.

Only unresolved wrong answer after the 2026-08-05 session (`499146a`, `16e861c`, `396e19f`,
`f614523`, `2e329b2`). Ground truth: **9 groups / 18 refunds** sharing an
`original_transaction_id` across two different stores.

## Why this one matters more than its size
It is the canonical case in `docs/demo-script-michael-pharmacy-12-questions.md` for the
answer-shaped-like-success failure. Recommend dropping Q4 from any demo until fixed, or using
a rephrasing that works (below).

## The mechanism, confirmed repeatedly
LAAM rewrites the question before it reaches DAAB, inventing a criterion the user never gave.
Sent VERBATIM to `POST /api/v1/ai-queries`, DAAB gets it right **2/2**:
`GROUP BY original_transaction_id HAVING COUNT(DISTINCT store_id) > 1` -> real rows. DAAB does
not even flag it ambiguous — it picks the sensible reading. **The whole defect is LAAM's
rewrite.**

What LAAM actually sent, across runs:
- `Find refunds that have identical amount, original transaction ID, timestamp, method, and reason`
- `list refunds that have the same refund amount, refund date and employee but different store`
- `list refunds that have the same refund amount, customer id, and refund date appearing in m…`
- `list duplicate refunds across stores, showing refund id, store id, amount, date, and employee`

## Four prompt attempts, four misses — stop adding words
`f614523` (P3) explicitly names **'duplicate'** as a word that must not be redefined, AND
forbids listing display columns. The very next run violated both halves on this question. That
is strong evidence prompt instruction will not hold here.

**Next step should be STRUCTURAL, not another rule.** Sketch: before dispatching an NL
data-query tool call, compare the query string against the user's message; if it introduces
concrete criteria (field names, "same X and Y and Z", explicit column lists) that have no
counterpart in the user's words, reject it and re-ask the model — the same shape as the
existing `sanitizeToolCallName` guard, i.e. code fixing what the prompt cannot. Design it to be
connector-agnostic (see `mem:decisions/laam-forward-user-question-verbatim`).

## Secondary, intermittent: DAAB emitted `IN (NULL)` once
```
SQL: SELECT * FROM refunds r WHERE r.original_transaction_id IN (NULL) LIMIT 1000
```
Empty by construction — a silent wrong answer, not an error. Did NOT reproduce in 3 further
attempts with identical input (all three produced correct `INNER JOIN (SELECT … HAVING …)`).
Regardless of frequency, a generated `IN (NULL)` / `IN ()` should fail loudly rather than
return an empty set. Go side, `internal/service/query_intent.go` (`value_is_expression` area).

## Verified working rephrasings (for the demo, and for users)
Both plain language, no schema terms — they just say WHAT is duplicated:
- `Are there any purchases that were refunded at more than one store?` -> **9 IDs, exact match**
- `Did the same original purchase get refunded at two different stores? Show me those cases.`
- Vietnamese: `Có lần mua nào bị hoàn tiền ở hai cửa hàng khác nhau không?`
The original wording still fails.

## Good news from the same run
Across all 24 turns of the final regression there were **ZERO answers containing a false "there
is none"** — the dangerous class is gone even though Q4 is still wrong (it now returns a
wrong-but-non-empty result rather than a false negative).
