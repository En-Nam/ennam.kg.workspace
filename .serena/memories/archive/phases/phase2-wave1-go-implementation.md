# Phase 2 Wave 1 — Go API Implementation Checkpoint

**Date**: 2026-04-08
**Branch**: `feature/phase2-wave1` (pushed to origin)
**Commits**: 22 commits, +9,445 lines, 53 files changed
**Status**: Wave 1 complete, ready for Wave 2

## What Was Built

### BA-007: Data Source Connection & Schema Migration (12 commits)

**New packages/files:**
- `internal/crypto/` — AES-256-GCM encryption (shared by BA-007 + BA-009)
- `internal/models/datasource.go` — 9 types (DataSource, SourceSchema, SourceTable, SourceColumn, SourceForeignKey, SourceIndex, SyncJob, ConnectionTestResult, ConnectionTestStep)
- `internal/store/datasource.go` — CRUD + soft delete
- `internal/store/schema_metadata.go` — Bulk upsert, schema tree queries
- `internal/store/sync_job.go` — Job tracking with progress
- `internal/service/datasource.go` — Registration with AES encryption, 5-step connection test (TCP/SSL/Auth/information_schema/test_query)
- `internal/service/schema_extractor.go` — Reads information_schema + pg_catalog from external PostgreSQL
- `internal/service/schema_sync.go` — Incremental diff detection (9 change types), preserves user annotations
- `internal/handler/datasource.go` — 10 REST endpoints under `/api/v1/data-sources/`

**Migrations**: 016-019 (data_sources, source_schemas, source_tables, source_columns, source_foreign_keys, source_indexes, sync_jobs)

**API Endpoints (10)**:
- POST/GET /api/v1/data-sources
- GET/PATCH/DELETE /api/v1/data-sources/{id}
- POST /api/v1/data-sources/{id}/test-connection
- POST /api/v1/data-sources/{id}/extract-schema
- POST /api/v1/data-sources/{id}/sync-schema
- GET /api/v1/data-sources/{id}/sync-jobs
- GET /api/v1/data-sources/{id}/metadata

### BA-009: AI Provider Abstraction Layer (11 commits)

**New packages/files:**
- `internal/ai/` — 7 files: provider interface, circuit breaker, Anthropic adapter, OpenAI adapter, normalize, selector
- `internal/models/ai_provider.go` — 7 types (AIProvider, AIUsageLog, AIBudgetTracking, AIProviderHealth, AIRequest, AIResponse, AIMessage)
- `internal/store/ai_provider.go` — CRUD with priority ordering, last-provider guard
- `internal/store/ai_usage.go` — Atomic budget tracking (microdollars), usage stats aggregation
- `internal/handler/ai_provider.go` — 9 REST endpoints

**Migrations**: 020-022 (ai_providers, ai_usage_logs, ai_budget_tracking, ai_provider_health)

**Key patterns:**
- Circuit breaker: 3-state (closed/open/half_open), mutex-protected, configurable threshold/window/cooldown
- Provider selector: priority-based failover, 2s failover budget, budget enforcement for pay-per-token
- Claude Max: zero marginal cost (cost_per_*_token = 0), always passes budget check
- Normalized request/response across Anthropic + OpenAI APIs

**API Endpoints (9)**:
- POST/GET /api/v1/ai-providers
- GET/PATCH/DELETE /api/v1/ai-providers/{id}
- POST /api/v1/ai-providers/{id}/health-check
- GET /api/v1/ai-providers/{id}/usage-stats
- GET /api/v1/ai-budget-stats
- POST /api/v1/ai/request

## Config Changes
- `config/config.yaml`: Added `ai:` section (provider_strategy, circuit_breaker, budget, rate_limits)

## Composition Root
- `cmd/kg-server/main.go`: Both BA-007 and BA-009 handlers wired. Gated by `KG_ENCRYPTION_KEY` env var.
- `buildAISelector()` helper: loads providers from DB, decrypts API keys, creates adapters + circuit breakers

## Tests
- 24 AI package tests (circuit breaker + adapters + selector) — all pass
- 5 crypto tests — all pass
- Handler/store compilation tests
- 2 integration test skeletons (//go:build integration)

## Pre-existing Issues (not introduced by Phase 2)
- Some test files in `internal/store/` and `internal/service/` have compilation errors (redeclared symbols, undefined config types) predating this branch

## Development Plan Files
- `docs/superpowers/plans/2026-04-08-ennam-kg-go-phase2-master.md`
- `docs/superpowers/plans/2026-04-08-ennam-kg-go-phase2-wave1-ba007.md`
- `docs/superpowers/plans/2026-04-08-ennam-kg-go-phase2-wave1-ba009.md`
- `docs/superpowers/plans/2026-04-08-ennam-kg-go-phase2-wave2.md`
- `docs/superpowers/plans/2026-04-08-ennam-kg-go-phase2-wave3-4.md`

## Wave 3 — AI Queries (2026-04-08)
- Migration 023: `ai_queries` table (project_id, data_source_id, natural_language_query, generated_sql, status, results JSONB)
- `internal/models/ai_query.go` — `AIQuery` model
- `internal/store/ai_query.go` — Create, GetByID, UpdateCompleted, UpdateFailed
- `internal/handler/ai_query.go` — `POST /api/v1/ai-queries`, `GET /api/v1/ai-queries/{id}`
- Wired in `cmd/kg-server/main.go`

## Wave 4 — Benchmarks (2026-04-08)
- Migration 024: `benchmark_questions`, `benchmark_runs`, `benchmark_results` tables
- `internal/models/benchmark.go` — BenchmarkQuestion, BenchmarkRun, BenchmarkResult
- `internal/store/benchmark.go` — GetQuestionsByDataSource, CreateResult, GetRunByID
- `internal/handler/benchmark.go` — `GET /api/v1/benchmarks/{ds_id}/questions`, `POST /api/v1/benchmarks/runs/{run_id}/results`
- Wired in `cmd/kg-server/main.go`

## Edge Whitelist Update (2026-04-08)
- Added `schema_fk`, `schema_implicit`, `schema_many_to_many` to `config/config.yaml`
- Added corresponding constants + `ValidEdgeTypes` entries in `internal/config/types.go`

## Docker Dev Stack (2026-04-08)
- Ports: postgres:5433, redis:6380 (avoid conflict with existing containers)
- `KG_ENCRYPTION_KEY` set in `.env` — unlocks data source + AI endpoints
- `docker-compose.yml` paths fixed (`./` → `../` for sibling repos)
- All 5 services running and healthy

## Additional Fixes (2026-04-08)

- Edge whitelist: `architecture → relates_to → architecture` enabled (was missing, caused 422 on code-to-code edges)
- AI provider handler: nil check on `selector` returns 503 instead of panic
- JSONB null fix in `ai_query` store: nil `results` no longer causes `pq: invalid input syntax for type json`
- Registration script: `scripts/register-ai-provider.sh <API_KEY>`

## Next: Wave 2

- BA-008 KG Generation (extends knowledge_nodes/edges, FK→edge mapping, AI implicit detection)
- BA-012 Admin Sync Portal (background job engine, WebSocket progress, rate limiting)
- Depends on Wave 1 stores (schema metadata) and AI client (selector)
