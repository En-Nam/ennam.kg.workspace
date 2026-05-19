# Checkpoint: Phase 2 Frontend Complete + API Contract Alignment — 2026-04-09

## Summary
ennam.kg.next Phase 2 frontend is COMPLETE with full API contract alignment against `docs/api-reference.md` (definitive Go handler reference).

## Latest Audit + Fix Pass (2026-04-09)
Source of truth: `ennam.kg.next/docs/api-reference.md` (1474 lines covering all 87 endpoints)

**22 critical + 11 medium + 7 low mismatches found and fixed** across 3 parallel fix tracks:

### Track 1: datasource + schema-graph (commits `20f22fe`, `184129d`)
- `DataSource`: `last_error` → `last_test_status`, removed `last_synced_at`
- `ConnectionTest`: `steps` array (not `test_results`), `'passed'|'failed'|'skipped'` enum
- `SourceTable/Column/FK`: added missing fields (`table_type`, `column_default`, `character_maximum_length`, `numeric_precision`, `user_description`, `referenced_schema`, `extracted_at`)
- `DataSourceListResponse` removed (API returns bare array)
- `updateDataSource`: PUT → PATCH
- `testConnection` path: `/test` → `/test-connection`
- Nested `/schemas/{id}/tables/{id}/columns` → single `/metadata` tree endpoint
- Added `MetadataSchema`, `MetadataTable` types for the tree response
- Added `useMetadata(dataSourceId)` hook
- Removed duplicate `SyncJobType`/`SyncJobStatus` from datasource.ts
- `SchemaGraph`: `data_source_id` query param (not `project_id`), `schema_fk|schema_implicit|schema_many_to_many` enum, removed embedded `columns`/`SchemaColumn`, added `column_count`
- `/knowledge-graph` page now selects first data source to fetch schema graph

### Track 2: ai-query + sync + usage (commit `20f22fe`)
- `QueryStatus`: `'running'` → `'processing'`
- `AIQuery.results`: bare row array `Record<string, unknown>[]` (not wrapped `{columns, rows, row_count, truncated}`)
- `QueryFavorite`: `ai_query_id` → `query_id`, added `is_shared`
- `ResultsTable` derives columns from `Object.keys(rows[0])`, count from `.length`
- `cancelSync`: removed "not implemented" guard — endpoint IS implemented
- `BudgetStats`: completely replaced with `{provider_type, month, budget_monthly_usd, spend_current, utilization_pct, projected_monthly_spend, alert_80_triggered}`
- `RateLimitStatus`: completely replaced with `{provider_id, requests_this_window, tokens_this_window, window_reset_at?, is_limited}`
- `useRateLimitStatus(providerId)` now takes required providerId param

### Track 3: benchmarks (commit `20f22fe`)
- `BenchmarkRunStatus`: added `'created'`
- `BenchmarkRun`: replaced all fields to match actual response (`accuracy` 0-1, `exact_matches`, `semantic_matches`, `partial_matches`, `failures`, `is_baseline`, `alert_triggered`)
- `BenchmarkQuestion`: added `expected_results`, `is_active`, `result_hash`, `verified_at`, `needs_reverification`, `created_at`
- `BenchmarkResult`: added `created_at`
- `fetchBenchmarkResults`: unwrap `{results, total_count}` response (was expecting bare array)
- Polling includes `'created'` status as active

## Commit History (Phase 2 — 40+ commits)
Most recent Phase 2 commits:
- `184129d` fix(types): align datasource + schema-graph with Go API contract
- `20f22fe` fix(types): align benchmark/ai-query/usage types with Go API contract
- `cb2d6c1` docs: add comprehensive API reference (87 endpoints)
- `5bf414d` feat(data-sources): wire sync button to useTriggerSync
- `f5e014e` docs: add Phase 2 API contract
- `3e9cdf6` fix(hooks): align kg-gen, usage, benchmark paths with Go
- `8ae6053` fix(ai-query): align paths and types
- `7dcc26c` fix(sync): align paths and types

## Final State
- **TypeScript:** 0 errors
- **Docker:** Deployed on :3500 (ennamkg-dashboard healthy)
- **7 new routes:** all functional, empty states for endpoints still pending
- **Source of truth:** `ennam.kg.next/docs/api-reference.md` (Go handler derived)

## Key Learning
**Do not trust BA docs for API contracts.** The api-reference.md (extracted from Go handler code) was the only reliable source. BA docs had significantly different field names and response shapes.

Updated 2026-04-09
