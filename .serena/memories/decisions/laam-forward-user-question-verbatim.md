# Do not pre-resolve columns when calling an NL data-query tool (LAAM prompt rule P1)

Decision for `buildSystemPrompt` in `src/lib/agent/context.ts`. Measured 2026-08-05 on DAAB's
`ai_queries` log. Related: `mem:backlog/daab-q8-column-semantics-and-row-fabrication`.

## The conflict (AGENTS.md Rule 7)
Rule **P1** (added earlier, measured against DAAB) told the model:

> "hãy nêu CỤ THỂ tên bảng/cột và điều kiện lọc/gộp nhóm bạn đã biết … câu hỏi càng cụ thể
> càng ít bị hiểu sai"

Its premise was real: a vague NL question made the lower layer drop filter conditions and pick
wrong grouping thresholds. But P1 predates DAAB's ambiguity detection, and it **disables that
feature outright**. Same question, two phrasings, measured:

| sent to DAAB | status |
|---|---|
| `Which products have negative inventory?` (verbatim) | `clarification_needed` — 4/4 runs |
| `...where variance_quantity is less than 0` (P1 style) | `completed` — executes LAAM's pick |

Consequence: Q8 answered "471 products" when the correct answer is **none**. LAAM had chosen
the discrepancy column (`variance_quantity`) over the stock columns
(`counted_quantity`/`system_quantity`), and because the choice was already baked into the
question, DAAB had nothing to ask about. A wrong choice rendered as a confident answer.

The `ai_queries` log also showed LAAM sending literal `SELECT ... JOIN ...` in the
natural-language field — the model had generalized "be specific" into "write the SQL".

Two contradicting patterns, so pick one and say why (Rule 7): the newer, measured behaviour
(the lower layer asks when genuinely ambiguous) wins. P1 is rewritten, not layered over.

## The replacement rule — deliberately NARROW
Blanket "forward the user's words exactly" would have broken two things that were working:
- **M1 decomposition** — a 4-metric question must still split into per-metric calls
  (verified: Q11 still issues 4 separate queries and now returns the full 4-metric table).
- **Context resolution** — when the user supplies a transaction ID, sending
  `"...for transaction TXN-0003476"` is correct (verified: still forwarded).

So the rule keeps P1's valid half and drops only the harmful half:
- KEEP the user's own wording of **the metric**; do not substitute a guessed column name.
- STILL pass conditions **the user stated** (time window, threshold, specific IDs) and the
  table when certain.
- Do NOT choose a column when several are plausible — the lower layer asks; pre-committing
  silences it.
- Never put SQL in the natural-language field.

## Generalizable lesson
A prompt rule that makes THIS layer more precise can disable a capability in the layer BELOW.
"Be specific" and "let the callee ask when ambiguous" are in direct tension: specificity
removes exactly the ambiguity the callee is watching for. When adding a be-specific rule to an
agent that calls another reasoning layer, name what it must NOT resolve on that layer's behalf.

## Verification
`context.test.ts` pins the new wording AND asserts the old phrase is gone (so the two cannot
coexist). End-to-end: disambiguated Q8 -> `SELECT COUNT(*) ... WHERE counted_quantity < $1` ->
`{"count": 0}`, matching the demo doc. 462 tests green, `tsc` clean.
