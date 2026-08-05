# Checkpoint: claude — 2026-08-05 (demo-readiness pass, follow-up to tool-name-sanitize)

## What was done (continuation of `mem:checkpoint/claude-2026-08-05-tool-name-sanitize`)
User asked to fix LAAM "triệt để" (thoroughly) so the same 12 QA questions demo smoothly, and specifically for Q11 to decompose into precursor questions before the final synthesis ask.

1. `src/lib/agent/context.ts` — 2 new evidence-based guards in the tool-instruction block (generic, not DAAB-specific in wording, but validated against DAAB's `ai_queries` log):
   - **M1**: forces decomposing multi-metric/multi-table compare questions into one tool call per metric, then synthesize — evidence: `ai_queries.error_message` for every "compare sales+refunds+variance+claims in one query" attempt showed hard SQL-gen failures (`missing FROM-clause entry`, `table name "st" specified more than once`, bad date-interval syntax). Verified fix: Q11 now works end-to-end as a 4-sub-question + 1-synthesis flow, all 4 sub-totals exact-matched DB ground truth, synthesis correct.
   - **P1**: pushes the model to phrase `natural_language_query` precisely (exact table/column/filter, from a prior `kg_describe_table`) instead of vague phrasing — correlated with success in the same log.
   - **R1**: explicit routing rule — `laam_query_audit` (LAAM's own action log) must never be used for business/customer questions; business questions must go through the data-source query tool. Added because tightening the tool's own `description` (previous session) was insufficient — verified via retest that R1 stopped the model from calling `laam_query_audit` at all for Q12 in the latest runs.
   - 3 new tests in `context.test.ts` (M1, P1, R1). `npx vitest run src/lib/agent src/app/api/chat` → 283 passed. `npx tsc --noEmit` clean.

## Real API retest results (round2/round3, gpt-oss-120b via BytePlus, both /chat and /constellation voice mode)
- Q1, Q3, Q7, Q8: reliably correct both modes.
- Q2, Q4, Q5: correct in voice mode (Q4's "9 duplicate transaction groups" exact-matched DB).
- Q6: verified end-to-end with the requested 2-step flow (list-5-transactions → use returned `TXN-0004917` → ask full receipt) — voice mode reconstructed all 6 line items exactly matching `transaction_items` join `products`, plus employee/register/customer/tax/discount breakdown not even asked for.
- Q9, Q10: voice mode now reliably exact-matches DB (Robert Reed/EMP-0100/9 shortages; PH-004/UnityCare Frisco/265 claims/41 rejected/15.47%) across repeated retests. Chat/text mode remains flakier on these two specifically — recommend voice/Larvis for the demo of Q9/Q10 if choosing one surface.
- Q11: SOLVED via the user's requested decompose pattern — demo script is 4 precursor questions (sales/store, refunds/store, inventory variance/store, claims/store — each independently exact-matched DB) + 1 synthesis question in the same conversation ("compare all 5 stores across the 4 metrics... healthiest/most concerning") — synthesis was accurate (correctly named PH-002 healthiest, PH-005 most concerning, right reasons).
- Q12: R1 fixed the LAAM-side wrong-tool bug (no more `laam_query_audit` calls). BUT traced the remaining failure to a **DAAB-side bug** (`ennam.kg.go`'s NL→SQL pipeline), confirmed via `ai_queries.generated_sql` in `daab-postgres`/`ennam_kg` DB:
  - Compound "before X OR after Y" time-range conditions generate malformed SQL (`WHERE override_datetime EXTRACT_HOUR $1`, `HOUR_LT_9_OR_GE_18 $1`, `NOT BETWEEN $1` missing 2nd bound) or wrong boolean logic (AND instead of OR → impossible condition → false "0 rows").
  - Workaround (same decompose pattern as Q11) DOES work when it lands cleanly: a SINGLE simple condition "before 09:00 (i.e., hour < 9)" on `discount_overrides` returned **18**, exact-matching direct DB count. The "after/at 18:00" half + the `refunds.manager_override OR flagged` half weren't gotten cleanly this session (mix of the same DAAB compound-OR bug for the refunds half, and ordinary BytePlus transient flakiness — one run returned a stray narration-only token mangle `pharmacy_chain` vs `pharmacy-chain` that didn't break the actual dispatched call, i.e. cosmetic not functional).
  - Ground truth for the demo script: `discount_overrides` before-9am = 18, at/after-18:00 = 144 (total after-hours = 162 — NOT 0, contradicting the model's earlier confident-wrong "no after-hours overrides" answer from before R1); `refunds` with `manager_override=true OR flagged=true` = 232.

## Files changed this pass
- `src/lib/agent/context.ts`, `src/lib/agent/context.test.ts`

## Next steps / open item flagged to user, not yet actioned
- Q12's residual DAAB-side bug lives in `ennam.kg.go` (NL→SQL intent-parser/query-plan generator), a different service/repo than LAAM. Did not touch it this session — user was only asked about LAAM; flagged the finding (with exact reproducing NL phrasings + malformed SQL) for a separate decision on whether to fix there.
- For the demo, Q12 should be run as: (1) "count discount_overrides before 09:00", (2) "count discount_overrides at/after 18:00", (3) "count refunds with manager_override=true or flagged=true", (4) synthesis — mirroring the Q11 script. Only sub-question (1) was cleanly verified working this session; (2) and (3) should be spot-checked once more before a live demo.
- Changes still uncommitted on `task/implement_docs_sync` (user has not asked for a commit).

## Blockers / Risks
- BytePlus/gpt-oss-120b has genuine transient flakiness independent of any of these fixes (occasional empty completions, occasional cosmetic token-narration glitches that no longer break gating/dispatch after the sanitizer fix). A demo run should budget for an occasional retry.
