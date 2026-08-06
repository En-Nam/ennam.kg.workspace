# Checkpoint: claude — 2026-08-05 (DAAB fixes #5-#7: retry-on-malformed-JSON, JOIN-fan-out prompt guidance, derived-table validation)

Follow-up to `mem:checkpoint/claude-2026-08-05-daab-flexint-fix`. User asked to investigate and fix all remaining known issues for max demo reliability.

## Fix #5 — retry once when the AI's JSON response is malformed
Second-most-frequent `ai_queries` failure class after the (already-fixed) limit-as-array bug: outright broken JSON (`invalid character ':' after object key:value pair`, `invalid character 'i' after object key`, etc — truncation or stray tokens, NOT the array-instead-of-scalar shape FlexInt/FlexStrings already handle). `ProcessQuery` (nl_query.go) already had a "retry once with a simplified plan" pattern for SQL EXECUTION failures, but ZERO retry existed at the earlier intent-PARSING stage — one malformed JSON response killed the whole query outright.
- `internal/service/query_intent.go` — extracted `sendAndParse` (method, calls the real `ai.Selector`) delegating to `sendAndParseWithRetry` (standalone function taking a `send func() (*models.AIResponse, error)` closure — testable without a real Selector/HTTP round trip). Retries the AI call ONCE if `parseAIResponse` fails; a second consecutive malformed response is a real failure, not retried further (same "max 1 retry" idiom as `retryWithSimplification`).
- 4 new tests in `query_intent_test.go` (succeeds first try = 1 call, malformed-then-valid recovers = 2 calls, malformed-twice fails after exactly 2 calls, a transport/Send error is NOT retried here since that's a different failure class already owned by ai.Selector's own retry/failover).

## Fix #6 — JOIN-fan-out-before-aggregate prompt guidance
Noticed in `mem:checkpoint/claude-2026-08-05-daab-value-expression-fix`'s verification: AI sometimes LEFT JOINs a one-to-many table to another one-to-many table BEFORE summing, multiplying rows across the join and inflating totals by orders of magnitude (numbers in the tens of millions instead of thousands).
- `internal/service/query_intent.go` prompt — new rule: "tables" must hold EXACTLY ONE entry (only `Tables[0]` is ever used by the generator — anything else there is silently dropped, a related footgun now also documented); combining an aggregate from two different one-to-many tables for the same key REQUIRES pre-aggregating the many-side as a derived-table subquery in `joins` FIRST (worked example given), never joining the raw many-rows tables directly before aggregating.

## Fix #7 — validator rejected the derived-table subqueries fix #6 asks the AI to use
Once the AI followed fix #6's guidance and produced a derived-table subquery as a "tables"/join "table" entry (`"(SELECT store_id, SUM(...) ... GROUP BY store_id) agg_alias"`), `validatePlanTables` rejected it outright — "unknown tables in plan" — since it only recognized real schema table names, never a subquery string.
- `internal/service/query_intent.go` — new `isDerivedTable(entry string) bool` (true iff the trimmed entry starts with `"("`). `validatePlanTables` now skips validation entirely for derived-table entries in both `plan.Tables` and `plan.Joins[].Table` — same trust boundary already used for Having/GroupBy/OrderBy/a join's "on" (all raw AI-generated SQL, never validated against the schema whitelist). A genuinely unknown REAL table alongside a derived one is still caught (regression-tested).
- 3 new tests in `query_intent_test.go` (derived table accepted as base table, accepted as a join table, unknown real table still rejected even when a derived table is also present).

## Deployment + verification
`go build ./...`, `gofmt -l`, `go vet ./...`, **full repo `go test ./...`** (21 packages) all clean after each fix. `docker restart daab-server` after all three landed together; healthy immediately.

Re-ran the EXACT question that previously failed derived-table validation (`mem:checkpoint/claude-2026-08-05-daab-value-expression-fix`'s flagged-but-unfixed JOIN-fan-out case): now **completes cleanly** via LAAM `/api/chat` (voice, gpt-oss-120b). Confirmed in `ai_queries.generated_sql`: a proper two-level pre-aggregated derived-table plan —
`FROM (SELECT ... GROUP BY store_id) snap_agg LEFT JOIN (SELECT ... GROUP BY store_id) mov_agg ON snap_agg.store_id = mov_agg.store_id` — status completed, plausible-scale numbers (system_quantity ~14-15k/store, movement ~5-6k/store — three orders of magnitude smaller than the pre-fix run's tens-of-millions fan-out artifact).

## Files changed
- `ennam.kg.go/internal/service/query_intent.go`, `query_intent_test.go`

## Cumulative DAAB fixes across this whole thread (7 total, all verified via LAAM)
1. Operator whitelist + OR logic
2. HAVING (aggregate post-filter) support
3. Subquery-as-filter-value (`ValueIsExpression`)
4. FlexInt for `Limit` (array-instead-of-scalar)
5. Retry-once-on-malformed-JSON (this session)
6. JOIN-fan-out-before-aggregate prompt guidance (this session)
7. Derived-table (subquery-as-table) validation support (this session)

## Remaining, NOT fixed — genuine model nondeterminism, not a single deterministic bug
- Q10 (insurance claim rejection rate) still occasionally returns a wrong/different SQL plan each ask (sometimes correct — PH-004/15.47% — sometimes claims all-zero). No crash, no error — the AI just picks a different (sometimes incorrect) query shape run to run. No further code lever identified; would need either a fixed canonical SQL template for this specific metric (defeats the point of NL2SQL) or accepting the demo re-asks it if wrong.
- Occasional question-framing confusion unrelated to SQL correctness (e.g. one Q2 retest brought up "prescription ID", a concept not in the schema, out of nowhere) — LLM reasoning noise, not a code bug.
- Q11/Q12 single-shot multi-metric asks still benefit from the decompose-into-sub-questions demo script (established in `mem:checkpoint/claude-2026-08-05-demo-ready-fixes`) even after all 7 fixes — each INDIVIDUAL sub-metric is now reliably correct, but asking for all 4 (or all 2, for Q12) in one natural-language question still has room to under-deliver depending on how many tool rounds the LAAM-side model spends before running out of budget. Recommended demo path unchanged: ask precursor questions, then synthesize.

## Blockers / Risks
- None blocking. All `ennam.kg.go` AND `LAAM` changes across this entire multi-turn thread remain **uncommitted** on both repos — user has not asked for a commit at any point across the whole session.
