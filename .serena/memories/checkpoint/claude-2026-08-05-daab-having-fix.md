# Checkpoint: claude — 2026-08-05 (DAAB `ennam.kg.go` fix #2: HAVING support)

Follow-up to `mem:checkpoint/claude-2026-08-05-daab-sql-generator-fix`. User asked to also fix the "aggregate functions are not allowed in WHERE" bug found during that fix's regression pass.

## Root cause
Same shape as the OR bug: `models.QueryPlan` had no `Having` field, and `query_intent.go`'s prompt never taught the AI that post-aggregation filters ("more than N occurrences") need HAVING, not a `filters` (WHERE) entry — so it tried `{"column": "COUNT(refund_id)", "operator": ">", "value": 1}` as a filter, which `sql_generator.go` correctly turned into `WHERE COUNT(refund_id) > $1` — syntactically fine on this layer, but Postgres rejects aggregates in WHERE outright.

## Fix
- `internal/models/ai_query.go` — added `QueryPlan.Having FlexStrings` (same plain-SQL-fragment idiom as `Aggregations`/`GroupBy`/`OrderBy`).
- `internal/service/sql_generator.go` — `Generate()` emits `HAVING <having-fragments joined by AND>` right after GROUP BY (before ORDER BY) when `plan.Having` is non-empty. Emitted even without GroupBy (malformed-plan case) — Postgres, not this layer, is the authority that rejects it; silently dropping would produce a query that runs but answers the wrong question.
- `internal/service/query_intent.go` — prompt now includes `"having"` in the JSON shape, and an explicit "WHERE vs HAVING" rule: aggregates NEVER go in `filters`, always in `having` + require `group_by`, with a worked example.
- 4 new tests in `sql_generator_test.go` (basic HAVING, multiple HAVING conditions AND'd, HAVING-without-GroupBy still emitted). `go build`, `gofmt -l`, `go vet`, `go test ./internal/service/... ./internal/models/...` all clean.

## Deployment + live verification
- `air` hot-reload picked it up (rebuild finished 2026-08-05 06:26:08 UTC).
- Retested via LAAM `/api/chat` (voice, gpt-oss-120b) against the same Michael Pharmacy Chain project:
  - "employees with more than one cash drawer shortage" → **58 employees**, top-ranked Robert Reed=9, then a cluster of 8s — exact match to direct-DB ground truth from earlier in this thread. `ai_queries.generated_sql` confirmed: `... GROUP BY e.employee_id, e.first_name, e.last_name HAVING COUNT(*) > 1 ...` — valid SQL, no Postgres error.
  - "duplicate refunds across stores" with the model's own (ambiguous) phrasing produced VALID SQL this time (`GROUP BY refund_id, refund_amount HAVING COUNT(DISTINCT store_id) > 1` — no more WHERE-aggregate crash) but 0 rows, because it grouped by `refund_id` (a PK, always count=1 stores) instead of `original_transaction_id` — a QUESTION-WORDING ambiguity, not a SQL bug. Re-asked with `original_transaction_id` named explicitly → **9 duplicate groups**, exact match to DB ground truth (confirmed independently via direct SQL earlier this thread).

## Regression check
Spot-checked `ai_queries` for every query since the fix landed — **zero** occurrences of the old "aggregate functions are not allowed in WHERE" error. Q1/Q3 clean. Some other questions (Q5, Q7, Q8, Q10 in this round) still failed/gave up, but for causes clearly unrelated to this fix:
- Q10: one BytePlus transient API error (ordinary flakiness, seen throughout this whole multi-session thread).
- Q7 (asked with a much more complex correlated-subquery-style phrasing than earlier in this thread): a NEW, THIRD class of DAAB bug — the AI tried to put a correlated subquery `(SELECT MAX(...) FROM ... WHERE ...)` as a filter's `value` (parameterized as `$1`), which Postgres can't bind a subquery into. Not fixed — flagging only, not asked about yet. The ORIGINAL simple phrasing for this same question ("highest inventory variance", plain `SUM(variance_quantity) GROUP BY store_id`) still works fine and was verified earlier in this thread — this is a different, harder question shape, not a regression.

## Files changed
- `ennam.kg.go/internal/models/ai_query.go`
- `ennam.kg.go/internal/service/sql_generator.go`, `sql_generator_test.go`
- `ennam.kg.go/internal/service/query_intent.go`

## Next steps / open items (not fixed, flagged only)
- Subquery-as-filter-value bug (see above) — a third, deeper class of the same underlying gap (QueryPlan's Filter.Value is always a bound parameter, never inline SQL) — would need a design decision (e.g. an `IsExpression` flag on QueryFilter, or documenting that subqueries aren't supported and steering the AI away from them) — not actioned, awaiting user direction.
- `ennam.kg.go` and LAAM changes across this whole multi-turn thread remain **uncommitted**.

## Blockers / Risks
- None blocking for what was asked. The DAAB NL→SQL pipeline (`query_intent.go` + `sql_generator.go`) is clearly a "long tail" of AI-generated-plan shapes it can't yet express — each fix this thread narrowed the gap for one concrete, evidenced failure mode without attempting to solve the class in general (consistent with Rule 2 — fix what's evidenced, not speculative future cases).
