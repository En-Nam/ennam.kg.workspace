# Checkpoint: claude — 2026-08-05 (DAAB `ennam.kg.go` fix #4: FlexInt for Limit)

Follow-up to `mem:checkpoint/claude-2026-08-05-daab-value-expression-fix`. User asked "what bugs remain?" — surveyed `ai_queries.error_message` broadly (last 25 failures) and found the single MOST FREQUENT failure (5/25): `"invalid JSON from AI: json: cannot unmarshal array into Go struct field QueryPlan.plan.limit of type int"` — the AI (gpt-oss-120b via BytePlus) sometimes returns `"limit": [5]` instead of `"limit": 5`. User said fix it.

## Root cause
`QueryPlan.Limit` was a plain `int`. The codebase ALREADY has a precedented fix for this exact class of AI-response quirk — `FlexStrings` (in the same file) already tolerates objects-instead-of-strings for `Aggregations`/`GroupBy`/`Having`/`OrderBy`. `Limit` was the one field left as a strict scalar, so a stray array there failed the ENTIRE plan's JSON unmarshal (not just that one field).

## Fix
- `internal/models/ai_query.go` — added `FlexInt int` type with `UnmarshalJSON` accepting either a plain number or a JSON array (single-element → that value; empty → 0; multi-element → error, since that shape means something other than a scalar limit). Changed `QueryPlan.Limit` from `int` to `FlexInt`.
- `internal/service/sql_generator.go` and `internal/service/nl_query.go` — no changes needed; `FlexInt` is comparable/arithmetic/formattable like a plain int for all the existing `<=`/`>`/`%d` usage (named int type, not a struct).
- `internal/service/nl_query_test.go` — one existing table-driven test (`TestRetrySimplification_ReducesLimit`) had `inputLimit`/`expectedLimit` typed as plain `int` used in non-constant contexts (struct-literal assignment + `!=` comparison against the now-`FlexInt` field) — Go doesn't auto-convert named types outside constant expressions, so retyped those two struct fields to `models.FlexInt`. No behavior change, compile-fix only.
- 6 new tests in `internal/models/ai_query_test.go` (plain number, single-element array, empty array→0, multi-element array fails, non-number fails, full QueryPlan with `"limit": [10]`).
- `go build ./...`, `gofmt -l`, `go vet ./...`, and **the full repo test suite** (`go test ./...` — all 21 packages, not just service/models) all clean.

## Deployment
`docker restart daab-server` (skipped relying on `air` hot-reload this time, after last fix's wedge — see `mem:checkpoint/claude-2026-08-05-daab-value-expression-fix`'s "Blockers" note). Came up healthy immediately.

## Live verification via LAAM
Re-ran the exact previously-failing NL query ("Count refunds approved by each manager...") via LAAM `/api/chat` (voice, gpt-oss-120b). Confirmed in `ai_queries`: same question phrasing that failed with the limit-array error at 06:19:50 UTC now **completed** at 07:10:52 UTC, correct results (Ava Ross=23, Amanda Lee=19, Ethan Hill=18, Liam White=17, Brandon Ross=16 — exact match to DB ground truth verified earlier in this thread).

## Regression check
Full 11-question voice-mode sweep post-fix: Q1/Q3/Q4/Q6/Q8/Q9 correct (Q4's "9 duplicate transaction groups" and Q9's "Robert Reed=9" both exact DB matches, consistent with earlier verified runs). Q2/Q5/Q7(minor ranking-order variance)/Q10/Q12 still show the SAME pre-existing, already-documented AI/DAAB nondeterminism (transient empty completions, NL2SQL choosing a different — sometimes wrong — query plan on repeat asks, one new-but-same-CLASS JSON-truncation parse failure at 07:15 unrelated to the limit field). No NEW error class introduced by this fix — spot-checked all `ai_queries` failures since deployment (07:07 UTC onward): exactly one, and it's the already-known "AI JSON syntax broke mid-response" class flagged (not fixed) in `mem:checkpoint/claude-2026-08-05-daab-having-fix`.

## Files changed
- `ennam.kg.go/internal/models/ai_query.go`, `ai_query_test.go`
- `ennam.kg.go/internal/service/nl_query_test.go`

## Cumulative state — 4 fixes across this thread, all verified end-to-end via LAAM
1. Operator whitelist + OR logic
2. HAVING (aggregate post-filter) support
3. Subquery-as-filter-value (`ValueIsExpression`)
4. FlexInt for `Limit` (this one)

## Remaining known-but-unfixed issues (surveyed, not actioned — reported to user)
- AI occasionally returns syntactically-broken JSON outright (not the limit-array shape — genuine truncation/stray-character JSON, e.g. `invalid character ':' after object key:value pair`) — harder to fix (would need either raising `MaxTokens` past 2048 in `query_intent.go`'s `AIRequest`, or a more lenient/repairing JSON parse) — not attempted.
- JOIN-fan-out-before-aggregate (noticed in fix #3's verification) — AI sometimes LEFT JOINs a one-to-many table before SUMing, inflating totals — a SQL-plan-quality issue, not a crash.
- Pure question-wording ambiguity (e.g. "duplicate refunds" grouped by `refund_id` vs `original_transaction_id`) — not a bug, inherent NL ambiguity.
- Q10 (insurance claim rejection rate) and Q7 (inventory variance ranking) still show run-to-run answer INCONSISTENCY (not crashes) — the AI picks a different query plan each time for these two specific questions and isn't always right — no crash/error to fix, this is answer-quality nondeterminism.

## Blockers / Risks
- None blocking. All `ennam.kg.go` and LAAM changes across this whole multi-turn thread remain **uncommitted** — user has not asked for a commit at any point.
