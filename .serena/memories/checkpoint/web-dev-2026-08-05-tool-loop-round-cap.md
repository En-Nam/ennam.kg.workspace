# Checkpoint: web-dev — 2026-08-05 (tool-loop round cap + topic drift)

## What was done
Retested the 12-question Michael Pharmacy Chain set (2 threads × 12 via `/api/chat`, model
`gpt-oss-120b`/BytePlus), found the root cause of the widespread "incomplete answer" symptom,
fixed it, re-measured, then fixed a second defect the re-measurement exposed.

**Root cause: `CHAT_MAX_ROUNDS=8` was far too low.** DAAB's `kg_query_datasource` is ASYNC
(returns `query_id`, must poll `kg_query_datasource_status`) ⇒ every data question costs 2-4
rounds minimum. Plus `kg_list_datasources` + `kg_describe_table`, a simple question eats 5-7
rounds; a 4-metric question (Q11) needs 11-16. At cap 8 nearly EVERY question hit the backstop
and was force-answered from partial data. Raised to 25 (= orchestrator `DEFAULT_MAX_ROUNDS`).

## Files changed (all UNCOMMITTED, branch `task/improve-mcp-tool-call-voice`)
- `.env` — `CHAT_MAX_ROUNDS` 8 → 25, with the async-round-math rationale
- `src/lib/chat/backstop-notice.ts` (NEW) — `synthNudge`, `restateQuestion`, `loopTruncatedNotice`
- `src/lib/chat/backstop-notice.test.ts` (NEW) — 15 tests
- `src/app/api/chat/route.ts` — use the helpers; thread `mode` into `streamMainTurn`; log backstop reason
- `src/lib/agent/orchestrator.ts` — `onBackstop(reason)`; audit-misuse guard rewrite + own latch
- `src/lib/agent/orchestrator.test.ts` — +3 tests

## CAP TUNING — settled at 25, do NOT lower (measured)
Tool calls per question across all 24 questions of the re-run: median ~7, **average 8.2**,
max 24. `maxRounds` is a CEILING, not a budget — a turn that finishes in 6 rounds costs the
same as before. So the real cost increase is ≈35%, NOT the 3× first estimated (that figure
was wrong and was corrected to the user).
- **Q11-Larvis used 23 calls and produced the BEST answer of the run** (full 4-metric table,
  matching the doc's expected "PH-002 healthiest / PH-005 most worrying").
- Any cap below ~24 truncates exactly that question. 25 = 23 + headroom.

**Where the waste actually is (follow-up, deliberately NOT built):** `history` at
route.ts:358 selects only `chatMessages` — `chatToolCalls` are never replayed — so every turn
in a thread starts blind and re-discovers. Measured: 24 `kg_list_datasources` (exactly 1 per
question) + 39 `kg_describe_table` = **63 of 196 tool calls (32%) are re-discovery of things
that do not change within a thread**. A discovery memo would cut that, but: it needs new
persistence + prompt injection, and pinning a `data_source_id` fights the codebase rule that
LAAM must not know connector-specific names (stated for TOOL_DRILLDOWN_PAIRS / TOOL_DATA_FETCH).
Also it would NOT have fixed either wrong answer — Q8-Larvis burned 24 calls and still read the
wrong column. Recorded as an optimization, not a correctness fix.

## Second defect found by the re-run, then fixed
**Topic drift is NOT only a backstop problem.** Larvis Q12 answered a previous question's topic
(cash-drawer shortages instead of after-hours overrides) with **zero backstops** that turn — so
`synthNudge` never ran. Added `restateQuestion(lang, question)`, appended before the final
completion on turns that ran tools and finished naturally (BytePlus path). Gated on
`toolTurns.length > 0` so a plain chitchat turn does not grow an extra turn (that would move
the `bareTurnFetch` call-count assertions in route.test.ts).

**Audit-misuse guard could not fire.** `readyAuditMisuse` required `!calledDataFetchTool`, but
in Larvis Q12 the model called a DAAB query FIRST and `laam_query_audit` after — so the guard
was silently disabled exactly when the misuse happened. Dropped that condition and gave the
guard its OWN latch (`auditMisuseNudged`); added `!auditMisuseNudged` to the second G5 site to
preserve the "at most one G5 nudge per turn" invariant (the new latch would otherwise have
allowed a double nudge — a regression introduced and caught in the same pass).

## Known drift, deliberate
The Ollama tool-loop path has NO `synthNudge` and now no `restateQuestion` either (pre-existing
asymmetry). Ollama is not running in this deployment (no server; BytePlus is the cloud-first
default), so the change was kept to the measured, verifiable path rather than shipped blind.

## Still broken — for a separate pass
1. **Q8 "negative inventory": wrong column, both threads.** Ground truth in `pharmacy_demo`:
   `counted_quantity < 0` = 0, `system_quantity < 0` = 0, `variance_quantity < 0` = 666 rows /
   471 products. "Negative inventory" = stock below zero ⇒ **the demo doc's "không có sản phẩm
   nào" is CORRECT; do NOT update the doc to match the AI.** Frame it as wrong-column, NOT as
   ambiguity. Lives in DAAB's NL→SQL generator (Go, needs a `daab-server` rebuild) — more LAAM
   rounds cannot fix it.
2. **FABRICATED DISPLAY DATA (its own item, worse than #1).** Q8-text padded its output table
   with a hallucinated row repeated ~20× (`Elastic WrapTravel (trùng)`) to fill 100 rows. The
   model is inventing rows to satisfy a row count. Not investigated yet.
3. Consistent ID→name resolution (Q9 still bare IDs while Q1/Q3 resolve). Improved as a side
   effect of the cap raise but still run-to-run inconsistent. Low priority: not a wrong answer.

## Verification
- 100 tests green across `orchestrator.test.ts`, `route.test.ts`, `backstop-notice.test.ts`;
  `tsc --noEmit` clean.
- Full re-run before → after: force-stop footer **6 → 0** in BOTH threads, transient API
  errors 1 → 0 per thread, **zero backstops**. Fixed: Q2, Q5, Q10 (now correct PH-004 15.47%),
  Q12-text (was answering Q9's topic), Q11-Larvis.
- 7 pre-existing failures in `src/lib/search.test.ts` and
  `src/components/constellation/ConstellationClient.test.tsx` — verified red BEFORE any of
  these changes via `git stash`. Unrelated.
- A targeted 5-question × 2-mode re-run (`scratchpad/laam_test/run_targeted.py`) was used for
  the drift fix instead of a full 24-question sweep — same signal, a fraction of the cost.
