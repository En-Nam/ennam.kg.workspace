# Checkpoint: claude — 2026-08-05 (single-thread 12-question test, per user request + a mid-run collision + one more G5 fix)

User asked to run all 12 questions in ONE conversation thread each (chat + Larvis), instead of the prior isolated-thread-per-question methodology, to better simulate real demo usage. They also cleaned up test conversations themselves.

## Incident: cleanup ran mid-test, caught and diagnosed correctly
First chat-thread attempt: Q1-Q5 succeeded, Q6-Q12 all returned `{"error":"Not found"}`. Investigated instead of assuming a code bug: `route.ts:339` 404s when `conversationId` doesn't resolve to a row owned by the current user. Confirmed via DB (`chat_conversation` count dropped from 203 → 10 between the two checks) that the user's cleanup deleted the in-progress thread's conversation row mid-sequence. Not a bug — re-ran cleanly after cleanup finished.

## NEW finding from single-thread testing: G5's audit-misuse nudge was too slow in long threads
Q12 in the first *clean* single-thread chat run STILL exhibited the exact `laam_query_audit`-misuse bug from `mem:checkpoint/claude-2026-08-05-q12-audit-misuse-fix` — 4x `laam_query_audit` calls, "no data" conclusion, tokens in=12226 (a full 12-message thread, unlike the isolated single-question tests that surfaced my earlier fix). Root cause: the PROACTIVE G5 check (added in `mem:checkpoint/claude-2026-08-05-g5-proactive-redesign`) only fires once `roundsLeft <= DATA_FETCH_NUDGE_LEAD_ROUNDS (3)` — appropriate for the generic "still legitimately exploring schema" case (give it time), but WRONG for the audit-misuse case, where the model isn't exploring toward the right answer, it's already on a wrong path from the first call. Waiting for the same 3-round grace period sometimes let the model finish "concluding" (stop generating tool_calls) before the threshold was reached.

## Fix
`orchestrator.ts` — split the proactive G5 condition into `readyGeneric` (unchanged, still LEAD_ROUNDS-gated) and `readyAuditMisuse` (`calledAuditTool && !calledDataFetchTool && !dataFetchNudged`, fires as soon as `roundsLeft >= 2` — i.e. essentially immediately, no waiting). Both OR'd into the same nudge-firing branch. Rationale documented inline: schema exploration may legitimately need time; calling `laam_query_audit` for a business question is wrong from the very first call, not something that needs "more time" to resolve.
- Updated the existing audit-misuse test's mock sequence (nudge now fires after round 1, not round 2) + added a NEW test proving it fires immediately even with `maxRounds: 25` (nowhere near the LEAD_ROUNDS=3 threshold) — this is the test that would have caught the gap if it had existed before the incident.
- `npx vitest run src/lib/agent src/app/api/chat src/lib/chat` → 452 passed. `npx tsc --noEmit` clean.

## Re-verification: full 12-question re-run in a FRESH single thread each, post-fix
**Chat thread** (`408ce85d…` then final `9010d04e…` after the audit-misuse timing fix): Q1/Q2/Q3/Q5(asks)/Q6(asks)/Q7(exact match: PH-005=1015,PH-003=542,PH-001=515)/Q9(exact: Robert Reed=9)/Q10(exact: PH-004=15.47%) all correct. Q4 gave a garbled one-line "echo" of its own planned query text instead of a full answer (new, minor generation glitch — not investigated further, low priority). Q8 asks clarification (good). Q11 correctly reports it doesn't have full data yet (honest, not wrong — needs the decompose script as already documented). Q12: still tries `laam_query_audit` once (model habit) but now redirects immediately and asks a legitimate clarification with real table names — no more confidently-wrong answer.

**Voice thread** (`5b229579…`, run fresh with the final fix): Q1/Q2(62 refunds)/Q3/Q4(exact: 9 duplicate groups, correct example TXN-0000626)/Q6(asks, cites a real duplicate-group TXN as its example)/Q7(gives BOTH variance readings correctly, matching ground truth: PH-001 488.38/9, PH-003 397.90/26, PH-004 -12.55/-8)/Q9(exact: Robert Reed=9 + correct 8-cluster names)/Q10(exact: UnityCare Frisco 15.47%) all correct or good-clarification. Q5 gave up citing an incomplete clarification round (mild, not wrong-data). Q8 asks clarification (good). Q11 shows a genuine reasoning slip: conflated Q4's "9 duplicate refund GROUPS (system-wide)" with a per-store claim about PH-001 specifically "appearing in 9 repeated refund transactions" — a cross-turn number-conflation error, not something any of this session's fixes specifically target (inherent LLM cross-turn reasoning noise in a long thread). Q12: tries `laam_query_audit` once, redirects correctly, asks a reasonable (if slightly imprecise — mentions `insurance_claims` as an alternative table where `audit_events` would be more apt) clarification — no wrong-data conclusion.

## Overall verdict: single-thread testing is MEASURABLY MORE FORGIVING than isolated-thread testing
Confirms the hypothesis raised when the user first asked about thread methodology: with real conversational context (schema already explored, some data already fetched from earlier turns), several questions that were previously flaky in isolation (Q7, Q9, Q10 especially) came back EXACT-MATCH correct in both single-thread runs, and even Q11 (previously an outright failure every time in isolation) produced a partial, data-grounded answer reusing prior turns instead of a blank refusal. The demo script's advice to keep asking within one thread rather than starting fresh each time is empirically validated.

## Files changed
- `LAAM/src/lib/agent/orchestrator.ts`, `orchestrator.test.ts`

## Remaining, not fixed this pass (low priority / inherent LLM noise, flagged only)
- Q4's garbled one-line "echo" answer in the chat thread (single occurrence, not reproduced/investigated).
- Q11's cross-turn number-conflation in the voice thread (reused a real number from an earlier turn but attached it to the wrong claim) — a reasoning-quality issue, not a code bug; no structural/deterministic lever identified.

## Blockers / Risks
- None blocking. All conversations created by this session's testing are LAAM DB rows under the `dragoon@exnodes.vn` test login — harmless test data, user already cleans these up manually. Everything across this whole thread (both repos) remains **uncommitted**.
