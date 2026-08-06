# Checkpoint: claude — 2026-08-05 (LAAM: G5 guard redesigned — reactive-only was structurally broken)

Follow-up to `mem:checkpoint/claude-2026-08-05-laam-g5-datafetch-guard`. While running the user-requested "current status of all 12 questions" sweep, found G5 (as shipped) failed on Q8 exactly the way it failed before the fix — investigated instead of assuming the fix was working.

## Root cause of G5 v1's failure
G5 v1 only checked its condition in the branch where `calls.length` is falsy — i.e. the branch that runs when the MODEL VOLUNTARILY stops calling tools. But Q8's actual failure mode is different: the model NEVER stopped — it called `kg_describe_table` on every single round (7 rounds straight) until hitting `i === maxRounds - 1` (`CHAT_MAX_ROUNDS=8` in `.env`), where the loop **force-sets `tools=[]`** (`orchestrator.ts:213`, `isLastRound ? [] : tools`) regardless of what the model wants. At that forced round, `calls` is empty too, but G4/G5 both explicitly require `!isLastRound`, so NEITHER fires. The model is simply handed an empty tool list and must answer from nothing — same "no real data" text as before G5 existed. G5 v1 never got a chance to run.

## Fix — proactive check, not just reactive
Added a SECOND check site, evaluated right after processing every round that DID have tool calls (previously there was only the reactive one, in the no-calls branch — kept, still useful for a model that gives up early with room to spare):
- `roundsLeft = maxRounds - 1 - i` (tool-capable rounds remaining after round `i`).
- Fires (latched, same as before) when `roundsLeft <= DATA_FETCH_NUDGE_LEAD_ROUNDS (3) && roundsLeft >= 2` — the `>= 2` floor is not arbitrary: nudging needs round `i+1` (tool-capable) to actually call the data tool AND round `i+2` (can be the forced-last round) to synthesize the answer; `roundsLeft < 2` means round `i+1` IS ALREADY the forced round, so nudging then is provably useless — skipped rather than wasting a message for no effect (same reasoning applied to the reactive branch's own `roundsAfterNudge >= 2` guard, added in the same pass).
- 2 new regression tests: (a) model calls `kg_describe_table` on every round with no natural pause, `maxRounds: 8` (the exact `CHAT_MAX_ROUNDS` value that exposed this) — asserts the nudge still fires and the model successfully calls the data tool afterward; (b) `maxRounds: 2` (next round would already be forced) — asserts NO nudge fires, proving the floor guard actually suppresses a useless nudge rather than firing blindly.
- `npx vitest run src/lib/agent src/app/api/chat src/lib/chat` → 450 passed. `npx tsc --noEmit` clean.

## Live verification
Retested Q8 ("Which products have negative inventory?", voice mode) **3 times** post-fix: **0/3 give-ups** (previously 2/3 in the same sweep before this fix). Outcomes: 1 run reached and executed `kg_query_datasource` (confirmed in the tool-call trace — text got cut short synthesizing the final answer, a separate minor issue, not the give-up bug), 2 runs correctly asked a clarification (`system_quantity` vs `counted_quantity` — the metric-ambiguity mechanism from fix #9 firing appropriately once the model actually reached the query-planning stage instead of giving up beforehand).

## A related, NOT-yet-actioned observation
`CHAT_MAX_ROUNDS=8` (`.env`) is tight for this connector's typical explore-then-query depth (list_datasources → list_projects → list_datasources again → describe_table ×4 → query = 7 calls before ever querying once, observed multiple times this session). The env's own comment says the intended runaway-guard is `BYTEPLUS_TOOL_BUDGET_CHARS` (char budget), not round count — round count was previously raised from 3 (too aggressive) to 8. G5 v2 now copes with 8 via proactive nudging, but a wider round budget would give the model more room to explore correctly on its own, with less reliance on being nudged. Not changed — this is a cost/latency tradeoff decision for the user, not something to change unilaterally.

## Files changed
- `LAAM/src/lib/agent/orchestrator.ts`, `orchestrator.test.ts`

## Blockers / Risks
- None. Everything across this whole thread (both repos) remains **uncommitted**.
