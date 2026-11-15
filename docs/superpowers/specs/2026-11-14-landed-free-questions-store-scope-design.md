# Free questions on POS T-log data, filtered by customer and store (D1/D2 v2)

Date: 2026-11-14. Status: approved direction (owner, in session). Replaces Tasks D1/D2 of
`docs/superpowers/plans/2026-11-11-pos-data-model-tlog-landed.md` (per-project role + per-project view schema).
Builds on WS0 (`2026-11-13-ws0-store-scope-authorization-design.md`).

## 1. Why

A store manager (member with assigned stores) and the chain owner must be able to ask questions that no
standard metric answers ("top 10 products sold by EMP-0006 between 14:00 and 16:00"), on the POS T-log data
DAAB has ingested (`ennam_landed`). Today:
- the landed store is not a data source, so DAAB's natural-language query cannot reach it;
- WS0 deliberately denies natural-language queries to store-limited tickets, because AI-written SQL cannot
  be trusted to filter by store.

## 2. Decisions

D-1 **Two lanes.** Lane 1 (primary, later plan): extend the pack-driven semantic layer (metrics engine) so
the model composes measures/dimensions/filters; server compiles SQL and applies scope. Lane 2 (this design):
AI-written SQL for the long tail, over views the database itself filters. Evidence: semantic layers raise
accuracy 20-31 points (AtScale) but answer 0% of out-of-model questions (dbt 2026); hence both lanes.

D-2 **Isolation is enforced by the database, never by the model or by SQL text checks.** The AI login role
has no privilege on base tables; it can read only the shared views.

D-3 **Signed context ticket verified inside Postgres.** Per query, DAAB mints a short-lived DB ticket
`{pid, loc: "*" | [stores], exp}` (HMAC-SHA256, a DB-only key — never the LAAM/DAAB delegation key), sets it
in the same transaction as the AI SQL (`set_config('landed.ctx', <ticket>, true)`), and the views call a
`SECURITY DEFINER` function that verifies signature and expiry (pgcrypto). Invalid / missing / expired ⇒ the
function returns NULL ⇒ views return no rows (fail closed). The model may call `set_config` itself but cannot
forge a signature. The ticket's `pid`/`loc` come from the caller's WS0 delegation ticket (DAAB side), so
store grants have one source of truth (LAAM People / `storeGrantFor`).
Rejected: plain RLS on a session variable (forgeable by the model's SQL); per-project roles and view
schemas (no store filtering; ops cost per customer); per-store roles (combinatorial).

D-4 **One set of shared typed views** (one per canonical entity, schema `pos`), `security_barrier = true`,
filter `project_id = <ctx pid>` AND (`loc = "*"` OR row store ∈ ctx stores OR entity has no store),
context read through scalar subqueries so it is evaluated once per statement (InitPlan).
Measured (3M rows, 20 projects × 25 stores): ~20 % overhead vs direct SQL when written this way; 2-4× when
the context function runs per row.

D-5 **Store id as a real column** on `landed_record`: `location_id text GENERATED ALWAYS AS
(data->>'location_id') STORED` (no writer change, no drift, no deploy-order risk), indexed with
`(project_id, entity, location_id, business_date)`.

D-8 **Entities without a store field are hidden from store-limited callers by default.** Only entities a pack
marks `scope: shared` (initially `product`, `location`) are visible to them. Reason: `labor_rate` (wages of every
employee in the chain) and similar have no store; the free-question lane must not be more permissive than the
metrics lane. (Owner approved 2026-11-14.)

D-9 **The AI role can change no setting and see no other session.** `set_config`, `pg_stat_activity`,
`pg_terminate_backend` / `pg_cancel_backend` and advisory-lock functions are revoked from PUBLIC in
`ennam_landed` and granted back to the existing roles; the executor sets the ticket and timeout with
`SET LOCAL`. Every tenant's questions share one role, so these would otherwise be cross-tenant side channels.

D-10 **Fail loud.** A rejected ticket is an error (`ticket_rejected`), never "0 rows"; a system-source query
without a caller scope is an error.

D-6 **Bridge-ready connections.** All new code obtains landed connections through one function
`landedFor(projectID)` (initially: the shared store from env). Moving a customer to its own database later
touches that function, not callers.

D-7 **Default OFF.** Shipping with the Monday 2026-11-16 deploy, every user-visible path is behind
`LANDED_NL_QUERY` (DAAB, exact value `1` enables) and LAAM `LANDED_FREE_QUESTIONS=1`. Off ⇒ no system data
source is created, no allow-list change, no LAAM tool change. Migrations (column, functions, views, role)
are additive and safe to apply with the flag off.

## 3. Scope

In: landed DB objects (column + index, pgcrypto, key table, ctx functions, views, AI role, resource limits);
DB-ticket minting + executor hook; system data source "Landed (system)" (created on enable, rotated, removed
on disable/purge; not editable/deletable); schema sync over the views; WS0 allow-list: store-limited
tickets may run natural-language queries ONLY on that system source; LAAM offers the direct-query tool to
restricted users only for that source and updates the system note; audit log line per free question.
Out: lane 1 semantic layer; customer live databases (store filtering impossible there — stays denied for
store-limited users); per-customer databases (D-6 only prepares); AST validation of SQL (later, defence in
depth).

## 4. Security requirements (each must have a test)

1. AI role: `SELECT` on schema `pos` views only; no access to `landed_record`, partitions, history, key table,
   other schemas; cannot create objects; `default_transaction_read_only = on`; `statement_timeout = 30s`;
   `idle_in_transaction_session_timeout`, `temp_file_limit`, `work_mem` capped; connection limit.
2. Ticket: tampered body, wrong key, expired, missing, malformed, model-issued `set_config` ⇒ 0 rows.
3. Cross-project and cross-store reads impossible, including via error messages (casts on hidden rows),
   `COPY ... TO PROGRAM`, `COMMIT; SET ... READ WRITE`, multi-statement input.
4. No dangerous extensions in `ennam_landed` (dblink, postgres_fdw, file_fdw, adminpack); role not in
   `pg_read_server_files` / `pg_write_server_files` / `pg_execute_server_program`.
5. With the flag off, behaviour is byte-identical to today for every existing path (including
   `GET /data-sources` and bridge instructions).
7. No cross-tenant side channel through the shared role: other sessions' SQL text, terminating/cancelling
   them, advisory locks, raising memory settings.
8. A store-limited caller cannot read another caller's query result via the status route.
9. Shared caches (value hints, plan cache) never carry values across scopes for the system source.
6. Store-limited users can never run natural-language queries on a non-landed data source (unchanged WS0).

## 5. Performance requirements

Monthly aggregation for one project of ~150k lines/month: < 500 ms p50 on the dev DB. Context verified once
per statement (EXPLAIN shows InitPlan). Test with `EXPLAIN (ANALYZE)` in an integration test fixture of
≥ 100k rows.

## 6. Rollout

Deploy Monday with flags off. Enable per environment after: security review of this diff, attack tests
green, a scripted free-question run as owner and as a store manager on the e2e stack.

## 7. Addendum 2026-11-15 — production is AWS RDS PostgreSQL 15.17

Facts: DAAB, LAAM and pharmacy DBs share one RDS instance (PG 15.17); devops will create `ennam_landed` there too.
RDS has no real superuser, so the pg_catalog revokes of D-9 (set_config, pg_terminate/cancel_backend,
pg_stat_get_activity, pg_stat_get_backend_*, advisory locks, SELECT on pg_stat_activity) cannot be applied, and
`pg_input_is_valid` (used by the typed views) does not exist before PG 16. Owner decision: free questions must work
on RDS; no self-managed Postgres.

- **D-11 Portable typed casts.** `fieldExpr` emits pure-SQL guarded casts (regex + range checks, nested CASE so the
  cast only runs on a value that will not fail). No new DB functions, no migration change. Accepted inputs:
  integer `[+-]digits` within int4; numeric decimal/exponent notation; boolean `true/false/t/f/yes/no/y/n/on/off/1/0`
  (case-insensitive); date ISO `YYYY-MM-DD` with a real day-of-month; timestamp ISO date + `[T ]HH:MM[:SS[.ffffff]]`
  with an optional ignored zone. Anything else is NULL (as an invalid value is today). Same SQL on PG 15 and 16.
- **D-12 SQL guard (always on).** Before a free question runs on the landed system source, DAAB refuses SQL whose
  lower-cased text, with double quotes removed, contains `pg_`, `set_config`, `u&`, `xml`, `ts_stat` or `ts_rewrite` (covers the catalog side
  channels, quoted/unicode-escaped identifiers, and the two built-in families that run a text argument as SQL:
  `query_to_xml`/`cursor_to_xml` and `ts_stat`/`ts_rewrite` — without them a name built with `||` or `chr()`
  could reach `pg_stat_activity`, found in review 2026-11-15). Bound parameters never carry SQL: the guard
  checks the SQL text, and the function names are refused wherever they appear. A false positive
  only costs the model a retry. The DB-enforced ticket + views (D-1..D-8) stay the primary protection.
- **D-13 Readiness on RDS.** The D-9 catalog items (function EXECUTE + pg_stat_activity SELECT) are reported as
  warnings "covered by the SQL guard" and no longer block readiness; every other hardening item still blocks.
  `ai-role.sql` tolerates a refused `temp_file_limit` (warning, not failure); readiness does not require it.
- Verification: full Go suite on PG 15; a PG 15 cluster where migrations and scripts run as a NON-superuser
  (CREATEDB, CREATEROLE — the RDS master shape) reaches "ready"; LANDED_PERF re-run; browser E2E.
