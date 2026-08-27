# Checkpoint: grok — 2026-08-26 (DAAB scalar-subquery filter fallback)

Investigation only-then-fix of the remaining LAAM-visible DAAB `failed` rows. Did **not** commit or rebuild `daab-server` (shared infra; user said be careful, did not ask to commit).

## Root cause (confirmed from live SQL)

`ai_queries` 99fb9408 / 0123a5ab (2026-08-26 07:04/07:06 UTC):
```
WHERE t1.transaction_datetime = $1
param = (SELECT transaction_datetime FROM transactions ORDER BY transaction_datetime ASC LIMIT 1)
pq: invalid input syntax for type timestamp
```
Same class as 2026-08-05 `ValueIsExpression` (subquery in filter value) and 2026-08-17 interval fallback: planner omits `value_is_expression`, generator binds SQL text as `$N`.

Interval already had a **closed grammar** fallback. Scalar SELECT subquery did not.

## Fix (TDD, RED then GREEN)

`internal/service/sql_generator.go` — two closed patterns, FROM table gated on `planColumnRefPrefixes`:
- `(SELECT ident FROM table ORDER BY ident ASC|DESC LIMIT n)` — live 08-26 shape
- `(SELECT MIN|MAX(ident) FROM table)` — live 08-21 shape

Look-alikes (other table, `; DROP TABLE`, `pg_sleep(1)`) stay `$N`. Did not widen `ValueIsExpression` trust, did not touch planner prompt.

Tests in `sql_generator_test.go` (3 new). `go test ./internal/service/ -count=1` ok. Full `go test ./... -race -count=1` with `KG_TEST_DATABASE_URL` on localhost:5432 — all packages ok.

## clarification_needed (not this fix)

Recent 48h: 1497 completed / 21 clarification / 3 failed. Remaining clarification includes markdown/` ```sql ` wrappers, leftover `[verify]` from before LAAM transitive fix, and NL	o SQL planner ambiguity. hardenPlan retry (df9e6c6) already covers hallucinated columns. Do not fold those into this generator change.

## Next

- Commit + rebuild `daab-server` only if the user asks.
- Serena `gopls` is not installed; symbolic tools failed on Go files this session.
