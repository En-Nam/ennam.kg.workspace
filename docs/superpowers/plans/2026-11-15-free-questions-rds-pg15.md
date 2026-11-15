# Free questions on RDS PostgreSQL 15 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Free questions on landed T-log data work on AWS RDS PostgreSQL 15.17 without weakening customer/store isolation.

**Architecture:** Typed AI views use portable guarded casts instead of `pg_input_is_valid`; an always-on SQL guard in
the landed executor replaces the catalog revokes RDS cannot apply; readiness stops blocking on those revokes.

**Tech Stack:** Go (ennam.kg.go), PostgreSQL 15/16, lib/pq.

**Spec:** `docs/superpowers/specs/2026-11-14-landed-free-questions-store-scope-design.md` §7 (D-11..D-13).

## Global Constraints
- Branch `task/pos-data-model` in ennam.kg.go and workspace root; commit, never push.
- Every DB test must pass on BOTH `pgvector/pgvector:pg15` and `pg16`.
- No new DB functions, no edits to landed migrations 000001–000006 contents beyond comments.
- Flags stay default-OFF (`LANDED_NL_QUERY`, `LANDED_FREE_QUESTIONS`).
- Error messages never name the landed host or echo the SQL.

## Review Focus
1. A JSON value like `"2026-02-30"`, `"99999999999"`, `"1e999999"`, `" 12 "` in a typed column → NULL, never a query error (cross-tenant view must not fail).
2. Quoted / unicode-escaped identifiers (`"PG_STAT_ACTIVITY"`, `U&"\0070g_sleep"(1)`) and `query_to_xml('...')` are refused by the guard.
3. On a cluster where catalog revokes were NOT applied, readiness is true AND an AI query reading `pg_stat_activity` is refused before reaching the DB.
4. Legit analytics SQL (date_trunc, extract, sum/count/avg, CTEs, window functions, `::numeric`) passes the guard.
5. LANDED_PERF 3M-row overhead stays in the same range as the PG16 `pg_input_is_valid` baseline (~20%).

---

### Task 1: Portable guarded casts in the AI views (D-11)

**Files:** Modify `internal/landed/aiviews.go` (`fieldExpr`); tests in `internal/landed/aiviews_test.go` (unit) and `aiviews_integration_test.go`.

- [ ] Unit test `TestFieldExprHasNoPG16Functions`: for every intel type, the expression does not contain `pg_input_is_valid`.
- [ ] Integration test `TestTypedCastsNeverFail` (runs on whatever PG the test DSN points at): one landed record per bad value in Review Focus 1 plus valid ones (`"12"`, `"-3"`, `"12.50"`, `"1.5E+3"`, `"TRUE"`, `"off"`, `"2026-11-15"`, `"2026-11-15T09:05:07.123456"`, `"2026-11-15 09:05"`, `"2026-11-15T09:05:07Z"`); selecting every typed column through the view returns no error, valid values cast exactly, bad ones NULL.
- [ ] Implement `fieldExpr` per spec D-11 (nested CASE; integer range via numeric compare; date day-of-month check; timestamp builds on the date check).
- [ ] Run `go test ./internal/landed/...` on pg15 and pg16; then `LANDED_PERF=1` benchmark on pg15, record numbers in the report.
- [ ] Commit `fix(landed): portable typed casts in AI views (PostgreSQL 15)`.

### Task 2: SQL guard + readiness on RDS (D-12, D-13)

**Files:** Create `internal/landed/sqlguard.go` (+ `_test.go`); modify `internal/landed/hardening.go`, `freequestions.go` (readiness), `internal/service/source_executor_landed.go` / the landed query path; `scripts/landed/ai-role.sql`; runbook section in `docs/ws0-delegation-runbook.md`.

**Interfaces:** Produces `landed.CheckAISQL(sql string) error` (returns `landed.ErrSQLRefused`); `CheckAIRoleHardening` returns `(blocking []string, covered []string, err error)`.

- [ ] Unit tests for `CheckAISQL`: refuses every case in Review Focus 2 plus `pg_sleep(5)`, `set_config('statement_timeout','0',true)`, `pg_advisory_lock(1)`, `select * from pg_catalog.pg_stat_activity`; accepts the Review Focus 4 queries.
- [ ] Executor test: a guarded landed query never reaches the DB (no audit "free question executed"), returns a model-readable refusal without the SQL.
- [ ] Hardening test: on a DB where `GRANT EXECUTE ON FUNCTION pg_catalog.pg_stat_get_activity(integer) TO PUBLIC` (and SELECT on pg_stat_activity) is in place, `FreeQuestionsReady` is true and the item appears in `covered`, logged once as a warning; a non-covered item (e.g. TEMP on the database) still blocks.
- [ ] `ai-role.sql`: `temp_file_limit` in a DO block that turns insufficient_privilege into a WARNING; tests no longer require it.
- [ ] Simulated-RDS run (document commands in report): pg15 container, role `rds_master LOGIN CREATEDB CREATEROLE` (not superuser) runs init.sql, landed migrations 1–6, ai-role.sql; DAAB readiness reaches "ready".
- [ ] Full `go test ./...` on pg15 and pg16 green.
- [ ] Commit `feat(landed): SQL guard and RDS-compatible readiness for free questions`.
