# Backlog: replace the free-question keyword guard with a real Postgres parser

**Owner:** DAAB (ennam.kg.go). **Requested by:** project owner, 2026-11-15. **Priority:** after the semantic layer; it does not block enabling free questions.

## Now
`internal/landed/sqlguard.go` `CheckAISQL` refuses AI SQL whose lower-cased text, with double quotes removed, contains `pg_`, `set_config`, `u&`, `xml`, `ts_stat` or `ts_rewrite`. It replaces the pg_catalog revokes that RDS cannot apply (spec D-12/D-13 in docs/superpowers/specs/2026-11-14-landed-free-questions-store-scope-design.md §7).

It works from a known list. The 2026-11-15 review found the ts_stat/ts_rewrite bypass, which was fixed in go 57ff9da.

## Target
Parse the AI SQL with Postgres' own parser via `pg_query_go`. Allow it only when all of these hold:
- one SELECT/WITH statement;
- every relation is in schema `pos`;
- every function is on an allow-list (aggregates, date/time, math, string, casts);
- nothing in it runs SQL dynamically.

Fail closed on anything the parser does not support.

## Cost and risks
- `pg_query_go` uses cgo, so the kg-server Docker build needs a C toolchain (CGO_ENABLED=1) and gets slower.
- The function allow-list has to be maintained.
- Known false positives (`pg_`, `xml` inside identifiers) go away.

## Done when
- Guard tests from `sqlguard_test.go` still refuse every bypass payload.
- The legitimate analytics queries (CTEs, window functions, date_trunc, extract, casts) still pass.
- The release image builds.
