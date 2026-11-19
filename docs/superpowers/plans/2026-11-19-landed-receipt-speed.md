# Landed receipt / evidence speed — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut landed evidence / receipt / free-question join latency (~950 ms → <100 ms locally) by reading join keys from indexed generated columns instead of JSON, and stop LAAM's receipt route from serialising its membership check.

**Architecture:** Landed migration 000007 adds `sale_id_key` / `product_id_key` generated STORED columns + indexes on `landed_record`. Under RLS (`landed_engine`, `landed_ai`) Postgres cannot use expression indexes on `data->>…` (not leakproof), but plain columns compared with `=` are fine. `landedsource.Table.ColumnSQL` and the AI view DDL read the key columns when the DB has them (detected at runtime, so code deployed before the migration keeps working). LAAM checks finding membership in parallel with the record read, first page 25 rows.

**Tech Stack:** Go (stdlib, database/sql, golang-migrate), PostgreSQL 15/16, Next.js 16 + Vitest (LAAM).

**Spec:** `docs/superpowers/specs/2026-11-19-landed-receipt-speed-design.md` (workspace root).

**Branch:** `task/improve_by_feedback_19112026` in `ennam.kg.go` and `LAAM` (nested git repos — commit with `git -C <repo>`).

## Global Constraints

- Column names exactly `sale_id_key`, `product_id_key`; generated as `NULLIF(data->>'sale_id','')` / `NULLIF(data->>'product_id','')`, type `text`, `STORED`.
- Index columns exactly `(project_id, entity, sale_id_key)` and `(project_id, entity, product_id_key)`, created on the partitioned parent.
- Key-column use applies only to canonical fields named `sale_id` / `product_id` whose field type is text; every other field keeps today's SQL byte-for-byte.
- Detection: "present" cached for the process lifetime; "absent" or a detection error cached for 2 minutes, then re-checked. A detection error never fails a query — it falls back to the JSON expression.
- No change to RLS policies, roles, grants, or the `location_id` column.
- Results must be identical (same rows, same order) with and without the key columns.
- LAAM: a failed membership check returns 404 regardless of the `getRecord` outcome (never a 500 for a non-member). `EVIDENCE_MAX_ROWS` stays 500.
- Code comments and commit messages in English; CHANGELOG/README/docs in Vietnamese.
- DB tests: source `<sdd-workspace>/test.env` (`KG_TEST_LANDED_URL`, port 5433, `ennam_landed_test` — never `ennam_landed`); run with `-v` and confirm the named tests RAN (they `t.Fatalf` without env, never skip).

## Review Focus

1. Migration applied after DAAB started → within ~2 min the engine uses the key columns without a restart.
2. Project whose landed data has a `sale_id` stored as `""` → still NULL in compiler output (NULLIF semantics kept).
3. Non-member receipt id whose `getRecord` throws → 404, not 500.
4. Pack whose `sale_id` field is not text (or an entity with no `sale_id`) → untouched SQL.
5. AI views on a DB without the columns → views still build (startup must not break before the migration).

---

### Task 1: Landed migration 000007

**Files:**
- Create: `ennam.kg.go/db/landed_migrations/000007_join_key_columns.up.sql`, `…down.sql`
- Modify: `ennam.kg.go/internal/landed/schema_integration_test.go` (or a new `join_keys_integration_test.go` in `internal/landed`)
- Modify: `ennam.kg.go/README.md`, `ennam.kg.go/CLAUDE.md` — migration range "000001-000005" → "000001-000007"

**Interfaces:** Produces columns/indexes named in Global Constraints.

- [ ] Step 1: Failing integration test `TestJoinKeyColumns`: after migrate up, inserting a `sale_line` record with `data = {"sale_id":"S1","product_id":"P1"}` reads back `sale_id_key='S1'`, `product_id_key='P1'`; `{"sale_id":""}` → `sale_id_key IS NULL`; both indexes exist on the parent (`pg_indexes`); down migration removes columns and indexes; `landed_engine` can SELECT the columns under RLS for its own project only.
- [ ] Step 2: Run it (`go test -v -run TestJoinKeyColumns ./internal/landed/`) → FAIL.
- [ ] Step 3: Write up/down SQL. Header comment: rewrites the whole table (STORED), run in a quiet window, before deploying the DAAB that reads it; no grants needed (same as 000002/000006).
- [ ] Step 4: Re-run → PASS; also run the existing `internal/landed` integration tests that cover migrations (`-run 'Migration|Schema|Partition'`) → PASS.
- [ ] Step 5: Commit `feat(landed): generated join-key columns for sale_id/product_id (000007)`.

### Task 2: Engine reads key columns (landedsource)

**Files:**
- Modify: `ennam.kg.go/internal/intel/landedsource/table.go`, `resolver.go`
- Create: `ennam.kg.go/internal/intel/landedsource/keycols.go` (detector)
- Test: `table_test.go`, new `keycols_integration_test.go`, extend `parity_integration_test.go`

**Interfaces:**
- Consumes: Task 1 columns.
- Produces: `type KeyColumns struct{...}` with `func (k *KeyColumns) Present(ctx context.Context) bool` (query `pg_attribute` of `landed_record` for both column names; TTLs per Global Constraints; concurrency-safe); `NewTable(projectID, entity string, fields []intel.Field, keyCols bool) (*Table, error)` — `keyCols` true makes `ColumnSQL("sale_id")` → `src.sale_id_key`, `ColumnSQL("product_id")` → `src.product_id_key` when the field type is text. Resolver owns one `KeyColumns` over the engine pool and passes `Present(ctx)` to `NewTable` in `Bind`.

- [ ] Step 1: Unit tests in `table_test.go`: keyCols=false → existing expressions unchanged; keyCols=true → `src.sale_id_key` / `src.product_id_key` for text fields, unchanged for a non-text `sale_id` and for other fields.
- [ ] Step 2: Detector tests (unit with an injectable clock/query func): present cached forever; absent re-queried after 2 min, not before; query error → false, re-queried after 2 min.
- [ ] Step 3: Implement; run unit tests → PASS.
- [ ] Step 4: Integration: extend parity test — the finding-evidence query of `retail.net_sales` (sale ⨝ sale_line ⨝ product, store filter) returns identical rows in identical order with keyCols true vs false on the same fixture. Integration `TestKeyColumnsUsedUnderRLS`: as `landed_engine` with `app.project_id` set, `EXPLAIN` of a `sale ⨝ sale_line` join built by the compiler contains `sale_id_key =` in an `Index Cond`.
- [ ] Step 5: Run `go test -v ./internal/intel/landedsource/` with test.env → PASS (named tests ran). Run `go build ./... && go vet ./internal/intel/...`.
- [ ] Step 6: Commit `perf(landed): engine joins on indexed key columns when present`.

### Task 3: AI views read key columns

**Files:**
- Modify: `ennam.kg.go/internal/landed/aiviews.go` (`viewDDL`, `SyncAIViews` gets presence from the maint connection inside its tx)
- Test: `aiviews_test.go`, `aiviews_integration_test.go`

**Interfaces:** Consumes Task 1 columns. `viewDDL(viewName string, e intel.Entity, keyCols bool)`; text fields `sale_id` / `product_id` → `r.sale_id_key` / `r.product_id_key` when keyCols.

- [ ] Step 1: Unit tests: keyCols=false → DDL byte-identical to today; keyCols=true → the two columns read the key columns, all else identical.
- [ ] Step 2: Integration: on a DB with the columns, `pos.sale_line.sale_id` reads the key column and a ticketed `landed_ai` join `pos.sale s JOIN pos.sale_line l ON l.sale_id = s.sale_id` EXPLAIN uses the key index; on a DB without them (drop columns in the test DB or detect false via injection) views still build.
- [ ] Step 3: Implement (detection: one `pg_attribute` query inside the sync tx; no caching needed — sync runs at startup and on pack change).
- [ ] Step 4: `go test -v -run 'AIViews|FreeQuestions' ./internal/landed/` → PASS.
- [ ] Step 5: Commit `perf(landed): AI views expose indexed join-key columns`.

### Task 4: LAAM receipt route — parallel membership check

**Files:**
- Modify: `LAAM/src/lib/intel/records.ts` (`findingEvidenceHas`), `LAAM/src/app/api/intel/findings/[id]/records/[entity]/[recordId]/route.ts`
- Test: the existing tests of both (find with `ls` next to them), isolation cases for this route stay green.

**Interfaces:** `findingEvidenceHas` signature unchanged. Page sizes: first page `FIRST_PAGE_SIZE = 25`, then `PAGE_SIZE = 200`, total ≤ `EVIDENCE_MAX_ROWS` (500).

- [ ] Step 1: Failing tests: (a) `findingEvidenceHas` requests limit 25 at offset 0 first, then 200 at offset 25, … never beyond 500 rows total; (b) route calls membership and `getRecord` concurrently (getRecord starts before membership resolves); (c) membership false + getRecord rejects → 404; (d) membership false + getRecord ok → 404 and no record data in body; (e) membership true + getRecord rejects with `scope_denied` → 404, other errors → existing errorResponse.
- [ ] Step 2: Run → FAIL. Step 3: implement (`Promise.allSettled`, membership decides first). Step 4: `npx vitest run <those files>` → PASS; `npm run test:int -- src/test/isolation` for this route's cases (`TEST_DATABASE_URL` from LAAM `.env`) → PASS.
- [ ] Step 5: Commit `perf(intel): check receipt membership in parallel, small first page`.

### Task 5: Docs, changelog, deploy notes

**Files:** `ennam.kg.go/CHANGELOG.md` (Unreleased), `LAAM/CHANGELOG.md` (Unreleased), new `docs/deploy/2026-11-19-landed-speed-checklist.md` (workspace root).

- [ ] Deploy checklist (Vietnamese): order 000007 on RDS (quiet window; 000006 rewrote the same table — use its runtime as the estimate; `make landed-migrate` as `landed_maintenance`) → deploy DAAB (deploy-dev) → deploy LAAM; verification: EXPLAIN check under `landed_engine`, re-measure prod receipt / evidence 25 & 100 / one chat question joining lines; rollback = down migration (code falls back automatically within 2 min).
- [ ] Commit in each repo `docs: …`.

## Execution notes

- Task 4 is independent of Tasks 1–3 (can run in parallel with Task 1). Tasks 2 and 3 both need Task 1; they touch different packages and can run in parallel.
- Final: full `go test ./...` (with test.env) in ennam.kg.go, full LAAM unit suite once; landed integration packages re-run on a throwaway `postgres:15` container; then E2E on local :3900 (receipt open time before/after, numbers identical).
