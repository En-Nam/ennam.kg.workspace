# Phase 2 Go API — Change Request from Frontend Team

**Date:** 2026-04-09
**Requester:** Frontend (ennam.kg.next Phase 2)
**Priority:** Blocking — frontend pages render empty without these endpoints

---

## Issue: Frontend pages hitting 404 on unimplemented Go API endpoints

The NextJS dashboard (Phase 2) has been built with 7 new pages. All frontend hooks, types, and components are complete. However, several Go API endpoints return 404 because they haven't been implemented yet.

Frontend currently handles 404 gracefully (returns empty data, no polling flood), but pages will remain non-functional until Go API delivers these endpoints.

---

## Endpoints Needed — Ordered by Priority

### P0: Admin Sync Portal (`/admin/sync`)

#### `GET /api/v1/admin/sync/jobs`
- **Purpose:** List sync jobs for history table + active syncs display
- **Query params:** `status` (string, opt), `data_source_id` (uuid, opt), `limit` (int, default 20), `offset` (int, default 0)
- **Response:** `{ "jobs": [SyncJob], "total_count": N }`
- SyncJob: `{ id, data_source_id, job_type (full|incremental), status (queued|preparing|extracting_schema|generating_kg|completing|completed|failed|cancelled), progress_percentage, current_phase, tables_total, tables_processed, current_table_name, warnings[], errors[], retry_count, estimated_duration_s, triggered_by, cancelled_by, cancel_reason, started_at, completed_at, created_at }`

#### `GET /api/v1/admin/queue/status`
- **Purpose:** Queue metrics (4 stat cards + RPM gauge)
- **Response:** `{ normal: int, high: int, processing: int, dead_letter: int, rate_rpm: int, rate_max_rpm: int }`

#### `POST /api/v1/admin/sync/trigger`
- **Request:** `{ data_source_id, sync_type (full|incremental), confirm: true }`
- **Response (201):** `{ id, status: "queued", estimated_duration_s }`

#### `POST /api/v1/admin/sync/{job_id}/cancel`
- **Request:** `{ reason? }`
- **Response:** `{ status: "cancelled" }`

#### `GET /api/v1/admin/sync/jobs/{job_id}/progress`
- **Response:** `{ progress_percentage, current_phase, tables_processed, warnings[], errors[] }`

### P1: Schema KG Visualization

#### `GET /api/v1/schema-graph?project_id={id}`
- **Response:** `{ tables: [{ id, table_name, schema_name, columns: [{ name, data_type, is_primary_key, is_foreign_key, is_nullable, is_unique, default_value, foreign_key_target }], ai_description, row_count_estimate, metadata }], relationships: [{ id, source_table_id, target_table_id, relationship_type (fk|ai_naming|ai_semantic|ai_join|ai_other), label, confidence (0-1), source_column, target_column }], metadata: { total_tables, total_relationships, total_fk_edges, total_ai_edges, generated_at, project_id } }`

### P2: Usage Dashboard

- `GET /api/v1/admin/usage/summary?period=7d` → `{ total_queries, total_queries_trend, ai_tokens_used, ai_tokens_percentage, avg_response_ms, avg_response_trend, error_rate, error_rate_trend }`
- `GET /api/v1/admin/usage/budget` → `{ current_usage, budget_ceiling, percentage, warning_thresholds[] }`
- `GET /api/v1/admin/usage/metrics?period_type=daily&start=&end=` → `{ metrics: [{ period_start, query_count, input_tokens, output_tokens, total_cost, avg_latency_ms }] }`
- `GET /api/v1/admin/queue/rate-limit` → `{ current_rpm, max_rpm, is_limited, limited_until }`

### P3: AI NL Query

- `POST /api/v1/ai-query/submit` → `{ query_id, status }`
- `GET /api/v1/ai-query/{id}` (polled 2s) → full AIQuery object
- `GET /api/v1/ai-query/{id}/results?page=&page_size=` → `{ columns[], rows[], total_rows, page, page_size }`
- `GET /api/v1/ai-query/history?data_source_id=` → `{ queries[], total_count }`

### P4: Benchmarks

- `GET /api/v1/benchmarks/runs?data_source_id=` → `{ runs[], total_count }`
- `POST /api/v1/benchmarks/runs` → `{ id, status: "queued" }`
- `GET /api/v1/benchmarks/runs/{id}/results` → BenchmarkResult[]

### P5: KG Generation

- `POST /api/v1/kg-generation/trigger` → `{ id, status: "pending" }`
- `GET /api/v1/kg-generation/{id}` (polled 2s) → KGGenerationJob object

---

## Already Working

- `GET /api/v1/data-sources?project_id=` ✅ (returns plain array, not wrapped)
- `POST /api/v1/data-sources` ✅ (needs host, port, database_name, ssl_mode, created_by AND connection_string)
- `DELETE /api/v1/data-sources/{id}` ✅

## Known API Contract Issues

1. `GET /api/v1/data-sources` returns plain array, not `{ data_sources: [], total_count }` — frontend normalizes
2. `POST /api/v1/data-sources` requires both individual fields AND connection_string — BA-007 only mentions connection_string
3. Empty collections return `null` not `[]` — frontend BFF proxy handles this
