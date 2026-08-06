# Checkpoint: claude — 2026-08-05 (DAAB fix #9: metric-level ambiguity → ask the user back)

Follow-up to `mem:checkpoint/claude-2026-08-05-daab-value-hints-fix`. User raised the design point: when the LLM isn't sure, it should ASK THE USER rather than pick silently. Correct — and investigation showed the mechanism already existed but was scoped too narrowly.

## What already worked
DAAB has a full clarification round-trip, proven end-to-end this session: AI returns `{"ambiguous": true, "clarification": {...}}` → `parseAIResponse` → `models.QueryClarification` → `query_clarifications` table → query status `clarification_needed` → `ai_query.go` handler returns it → MCP → LAAM surfaces the question + options to the user, who answers and the conversation continues. Real examples pulled from `query_clarifications`:
- "Do you want store_id or store_name in the results?"
- "The refunds table does not have a 'status' column. Which status would you like?"
- "'refund_date' is not a column. Did you mean 'refund_datetime'?"

## The gap
Every clarification ever raised was about **COLUMNS** (missing column / which column). The prompt defined ambiguity as *"multiple tables could match"* + *"references concepts with no matching column"*. So the Q5/Q7 class never triggered it: there, **all candidate columns exist** — the ambiguity is in the METRIC, i.e. which valid computation the user meant. The planner just picked one at random per run.

Measured proof of why that matters:
- **Q7** "highest inventory variance": by `sum(abs(variance_quantity))` → PH-005 first (1015); by `sum(variance_value)` → PH-005 **last** (−9,886.23), PH-001 first (+488.38). **Opposite rankings**, both defensible.
- **Q5** "most frequently refunded": count of refund_items rows vs sum of quantity → completely disjoint top-5 lists (School SuppliesValue Pack 6 vs Vitamin C50 Count 9).

## Fix
`internal/service/query_intent.go` — broadened the ambiguity contract in BOTH `systemPrompt` and `userPromptTemplate`:
- Ambiguity now explicitly includes "the metric itself could be computed in two valid ways from columns that ALL exist, and those ways give materially different answers (different top result or different ranking)" — must return the ambiguous form, must NOT silently pick, with the reasoning made explicit ("both answers look equally confident to the user, so a silent choice is indistinguishable from a wrong answer").
- Named the recurring shapes: count-of-rows vs sum-of-quantity for "most/top X"; a variance/difference/total that exists as BOTH a quantity column and a value/amount column (noted these often rank in opposite order); "highest rate" with no denominator floor; ranking over multi-period data with no time window.
- Requires the concrete column/aggregation inside each option (not vague prose).
- **Over-asking guard** (important — an over-eager clarifier ruins a demo as much as a guesser): do NOT raise ambiguity when the readings would rank the same, when one is the obvious common-sense default, or merely because the question is short.
- `go build`, `gofmt`, `go vet ./...`, `go test ./internal/service/...` clean; deployed via `docker restart daab-server`.

## Verification + a THIRD ambiguity dimension found
Retesting Q5 twice post-deploy: both runs now chose the SAME metric (count of `refund_items` rows) — but still returned different answers, which exposed a further gotcha in the dataset itself:
- run A grouped by `product_name` → "School SuppliesValue Pack" = 6
- run B grouped by `product_id` → "PRD-00069 (Iced TeaValue Pack)" = 4

Root cause: `products` has **800 rows but only 360 distinct product_name values** — names are heavily duplicated (up to 8 distinct product_ids share "Nasal SprayLarge"). Grouping by name silently merges distinct SKUs. So Q5 is ambiguous in TWO dimensions at once (what to measure × what to group by), not one.

Did NOT observe the new metric-clarification firing live in these runs (the model answered rather than asked). Whether the broadened prompt actually raises metric-level clarifications in practice is **not yet empirically confirmed** — the prompt change is landed and safe (fully backward compatible: it can only add clarifications, never break a plan), but its real-world hit rate is unmeasured. Worth a dedicated probe run later.

## Files changed
- `ennam.kg.go/internal/service/query_intent.go`
- `docs/demo-script-michael-pharmacy-12-questions.md` (Q5 section rewritten for the 3 readings + new section documenting the clarification mechanism)

## Blockers / Risks
- Everything across this whole thread (both repos) still **uncommitted**.
- Demo advice unchanged: use the pre-pinned phrasings in the demo doc for Q5/Q7 rather than relying on the clarification path, so the demo stays on rails.
