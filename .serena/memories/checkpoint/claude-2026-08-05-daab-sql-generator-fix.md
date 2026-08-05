# Checkpoint: claude — 2026-08-05 (DAAB `ennam.kg.go` fix: NL2SQL operator whitelist + OR support)

## Context
Follow-up to `mem:checkpoint/claude-2026-08-05-demo-ready-fixes`. That session traced LAAM Q12's remaining failure to a bug in a DIFFERENT repo — `ennam.kg.go`'s NL→SQL pipeline — via `ai_queries.generated_sql`/`error_message` in the `ennam_kg` Postgres DB. User asked to fix it there, then retest via LAAM.

## Root cause (2 compounding bugs in `ennam.kg.go`)
1. **No operator whitelist.** `internal/service/sql_generator.go`'s `buildFilterClause` `default` case interpolated whatever `Operator` string the AI-generated `QueryPlan` contained directly into SQL with no validation. The AI (`internal/service/query_intent.go`'s `QueryIntentParser`, prompted via `userPromptTemplate`) was never told a fixed operator set, so it sometimes invented non-SQL tokens (`EXTRACT_HOUR`, `HOUR_LT_9_OR_GE_18`) → cryptic Postgres syntax errors.
2. **No OR support at all.** `SQLGenerator.Generate()` always joined `plan.Filters` with `" AND "` — `models.QueryFilter` had no field to express OR. A compound "before 9am OR after 6pm" question always became an impossible AND'd condition → silently wrong "0 rows" (not even an error).

## Fix
- `internal/models/ai_query.go` — added `QueryFilter.Logic string` (`"AND"`/`"OR"`, joins to the PREVIOUS filter; first filter's Logic ignored; default AND for back-compat).
- `internal/service/sql_generator.go` — `allowedComparisonOperators` whitelist; `buildFilterClause` now returns `error` and rejects unknown operators with a clear message instead of interpolating them; added `IS NULL`/`IS NOT NULL` case; `Generate()` now interleaves each filter's `Logic` (AND/OR) instead of always-AND, using normal SQL AND-before-OR precedence (no explicit parens/grouping — flat list only, no evidence anything needs nested grouping yet, kept minimal per Rule 2).
- `internal/service/query_intent.go` — `userPromptTemplate` now: enumerates the exact valid operator set; explicitly teaches "column" MAY be a SQL expression (`EXTRACT(HOUR FROM col)`, `col::time`) for date/time-part filters instead of inventing a fake operator; documents `"logic"` and the "two filters, second one `logic: OR`" pattern for before-X-or-after-Y questions.
- 7 new table-driven tests in `internal/service/sql_generator_test.go` (unknown-operator fails loud, expression-as-column, OR logic, first-filter-Logic-ignored, mixed AND/OR precedence, IS NULL). `go build ./...`, `gofmt -l`, `go vet`, `go test ./internal/service/... ./internal/models/...` all clean.

## Deployment + live verification
- `daab-server` (docker project `daab-dev`, container built from `./ennam.kg.go` via `docker-compose.yml`) runs `air` hot-reload on a bind mount — picked up the fix automatically (confirmed via `docker logs daab-server` showing a `building...` cycle finishing at 06:15:48 UTC, after the edits).
- Retested via LAAM's real `/api/chat` (voice mode, model `gpt-oss-120b`) against DAAB project "Michael Pharmacy Chain":
  - "discount_overrides before 09:00 or on/after 18:00" → **162** (exact DB match). `ai_queries.generated_sql` confirmed: `... WHERE override_datetime::time < $1 OR override_datetime::time >= $2 ...` — proper OR, not AND.
  - "refunds where manager_override=true or flagged=true" → **232** (exact DB match), same OR pattern confirmed in generated SQL.
  - This was LAAM Q12's exact original failure mode — now resolved at the root (DAAB), no LAAM-side workaround/decompose needed for this specific case anymore.
- Regression pass on Q1/Q2/Q5/Q7/Q8/Q10 (voice mode): no new failures introduced by this change — spot-checked `ai_queries` for every query run after the fix landed (06:17 UTC onward) and none hit the new operator-whitelist error path; failures seen in this pass are pre-existing, DIFFERENT bugs (see below), or ordinary AI-generation nondeterminism (JSON-parse hiccups, exploration-heavy rounds) that predate this change.

## New (separate, NOT fixed this session) bug found during regression
`internal/service/sql_generator.go` generates a WHERE clause containing a bare aggregate (`COUNT(*) > $1`, `COUNT(DISTINCT store_id) > $2`) instead of `HAVING` — Postgres rejects this (`aggregate functions are not allowed in WHERE`). Observed on: "duplicate refunds across stores" and "employees with >1 cash drawer shortage" style questions (both need a GROUP BY + a post-aggregation count filter). Same class of root cause as the fixed bug (`query_intent.go`'s prompt doesn't teach the AI when to use `group_by`+implicit HAVING vs `filters`/WHERE) — not fixed this session, flagged to user, awaiting a decision on whether to fix it too.

## Files changed
- `ennam.kg.go/internal/models/ai_query.go`
- `ennam.kg.go/internal/service/sql_generator.go`, `sql_generator_test.go`
- `ennam.kg.go/internal/service/query_intent.go`
- (LAAM side unchanged this session — this was a DAAB-only fix, LAAM already fixed in the prior 2 checkpoints)

## Next steps / open item
- Same HAVING-vs-WHERE class of bug for aggregate post-filters — not yet fixed, needs a similar prompt teaching + possibly a `plan.Having []string` field (mirroring how `GroupBy`/`OrderBy` are already plain SQL-fragment lists) if the user wants it addressed.
- Both `ennam.kg.go` and LAAM changes across this whole thread remain **uncommitted** — user has not asked for a commit.

## Blockers / Risks
- None blocking. `ennam.kg.go`'s own Serena memory store (`.serena/` in that sub-repo) was not reachable this session (no `activate_project` tool available) — this checkpoint is written to whichever store was already active; if that turns out to be the LAAM store rather than `ennam.kg.go`'s own, the note should be copied over in a future session per that repo's own CLAUDE.md protocol.
