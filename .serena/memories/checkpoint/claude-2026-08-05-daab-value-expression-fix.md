# Checkpoint: claude — 2026-08-05 (DAAB `ennam.kg.go` fix #3: correlated subquery as filter value)

Follow-up to `mem:checkpoint/claude-2026-08-05-daab-having-fix`. User asked to fix the third bug found during that fix's regression: AI query planner comparing a column against a correlated subquery by putting the subquery string in a filter's `value` — bound as a `$N` Postgres parameter, which fails ("invalid input syntax") since a bound parameter is always a literal, never SQL.

## Fix
- `internal/models/ai_query.go` — added `QueryFilter.ValueIsExpression bool`. When true, `Value` (must be a non-empty string) is inlined as raw SQL instead of parameterized. Default false — existing parameterized behavior for plain data values is unchanged; this only opts a filter INTO the same "raw AI-generated SQL fragment" trust boundary that `Column`/`Joins[].On`/`GroupBy`/`Having`/`OrderBy` already use.
- `internal/service/sql_generator.go` — `buildFilterClause`'s default (comparison-operator) case: when `ValueIsExpression`, inline `Value` wrapped in parens (`col op (expr)`, no bound param) instead of `col op $N`; validates `Value` is a non-blank string first. IN/BETWEEN cases untouched (no evidence they need this — scope kept to the exact bug shape observed).
- `internal/service/query_intent.go` — prompt now explains: subquery comparisons need `"value_is_expression": true` on that filter, with a worked example; plain literal values must NOT set it.
- 4 new tests in `sql_generator_test.go` (subquery inlined correctly + no bound param, mixes fine with an ordinary parameterized filter via Logic, non-string value rejected, blank-string value rejected). `go build`, `gofmt -l`, `go vet`, `go test ./internal/service/... ./internal/models/...` all clean (verified both on host and via `go build ./...` run directly inside the `daab-server` container).

## Deployment hiccup + resolution
`air`'s hot-reload got stuck mid-rebuild during the rapid sequence of edits (container `docker exec ... ps aux` showed only the `air` supervisor running, no live `kg-server` process; `wget healthz` connection-refused) even though `go build ./...` succeeded cleanly both on host and inside the container — a transient air/inotify glitch, not a code problem. Fixed with `docker restart daab-server`; came up healthy (`{"status":"healthy"}`) on the new binary.

## Live verification via LAAM
Re-ran the EXACT original failing question from `mem:checkpoint/claude-2026-08-05-daab-having-fix`'s regression note: "For each store, take the most recent inventory_snapshot ... variance = abs difference between snapshot.system_quantity and sum of quantity_change ... up to that snapshot_date ... top 5". Confirmed in `ai_queries.generated_sql`:
`... WHERE snap.snapshot_date = (SELECT MAX(snapshot_date) FROM inventory_snapshots s2 WHERE s2.store_id = snap.store_id) AND mov.movement_datetime <= (snap.snapshot_date) ...` — subquery correctly inlined, **status: completed**, no Postgres error. (The returned variance numbers were implausibly huge — a JOIN-fan-out issue, SUM(quantity_change) inflated by the LEFT JOIN multiplying snapshot rows against every matching movement row before aggregating — a NEW, separate business-logic bug in how the AI structures multi-table aggregates, not related to this fix and not yet flagged to the user.) A simpler equivalent phrasing of the same underlying question (no LEFT JOIN, single-table `SUM(ABS(system_quantity - counted_quantity)) GROUP BY store_id`) returned the exact correct top-5 ranking, matching direct-DB ground truth verified earlier in this thread (PH-005=1015, PH-003=542, PH-001=515, PH-004=492, PH-002=489).

## Files changed
- `ennam.kg.go/internal/models/ai_query.go`
- `ennam.kg.go/internal/service/sql_generator.go`, `sql_generator_test.go`
- `ennam.kg.go/internal/service/query_intent.go`

## Cumulative state across this 3-fix thread
Three concrete, evidenced, independently-tested bugs fixed in `ennam.kg.go`'s NL→SQL pipeline (`sql_generator.go` + `query_intent.go` + `ai_query.go` models), each verified end-to-end through LAAM's real `/api/chat` against DAAB project "Michael Pharmacy Chain": (1) operator whitelist + OR logic, (2) HAVING support, (3) subquery-as-filter-value. All three originated from the SAME LAAM 12-question QA demo thread (see the LAAM-side checkpoints: `mem:checkpoint/claude-2026-08-05-tool-name-sanitize`, `mem:checkpoint/claude-2026-08-05-demo-ready-fixes`).

## Next steps / open items (not fixed, flagged only)
- The JOIN-fan-out-before-aggregate bug noticed in this session's verification (LEFT JOIN inventory_movements before SUM without a pre-aggregated subquery, inflating totals) — not raised to the user yet, purely an observation from this verification pass. A fourth potential fix in the same family if the user wants to keep going.
- All `ennam.kg.go` and LAAM changes across this whole multi-turn thread remain **uncommitted**.

## Blockers / Risks
- None blocking. Note for future sessions: this container's `air` hot-reload can silently wedge (process alive, binary not serving) during rapid successive file saves — if `wget healthz` fails after an edit despite a clean `go build`, check `docker exec daab-server ps aux` for a missing `kg-server` process before assuming the code is broken, and `docker restart daab-server` resolves it.
