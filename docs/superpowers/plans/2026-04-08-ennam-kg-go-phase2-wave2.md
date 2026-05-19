# Wave 2: BA-008 KG Generation + BA-012 Admin Sync — Go API Plan Outline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement KG generation from schema metadata (explicit FK mapping + AI implicit detection) and admin sync portal with background job engine, WebSocket progress, and rate limiting.

**Architecture:** Extends knowledge_nodes/knowledge_edges with schema-generated content. New background job engine (`internal/jobengine/`) shared across BA-008, BA-012, BA-013. WebSocket support via gorilla/websocket for live progress.

**Tech Stack:** Go std lib, gorilla/websocket, `internal/ai/` (from BA-009), PostgreSQL

**Prerequisites:** Wave 1 complete (BA-007 stores + BA-009 AI client)

---

## BA-008: Knowledge Graph Generation

### Migrations

| # | Content |
|---|---------|
| 023 | ALTER `knowledge_nodes` — add `node_subtype`, `source_data_source_id`, `source_table_name`, `schema_group`, `column_count`, `row_count_estimate`, `ai_description`, `column_details` to properties JSONB. ALTER `knowledge_edges` — add `confidence_score`, `detection_method`, `cardinality`, `source_column`, `target_column`, `fk_constraint_name` to properties JSONB. Relax self-reference CHECK for `schema_fk` edges. Add new edge types to whitelist: `schema_fk`, `schema_implicit`, `schema_many_to_many`. |
| 024 | CREATE `kg_generation_jobs` — tracks generation pipeline status per data source |

### New Files

```
internal/service/
├── kg_generator.go              # Orchestrates: nodes → explicit edges → implicit detection → persist
├── kg_generator_test.go
├── kg_explicit.go               # FK → directed edge mapping (1:1, 1:N, M:N, junction tables)
├── kg_explicit_test.go
├── kg_implicit.go               # AI-powered implicit relationship detection
└── kg_implicit_test.go

internal/store/
├── kg_generation.go             # KGGenerationStore: job tracking + node/edge queries by data source
└── kg_generation_test.go

internal/handler/
├── kg_generation.go             # 9 endpoints: generate, list nodes/edges, confirm/reject, status
└── kg_generation_test.go
```

### Key Tasks (High-Level)

- [ ] **Task 1**: Migration 023 — extend knowledge_nodes/edges properties, relax self-ref CHECK
- [ ] **Task 2**: Migration 024 — kg_generation_jobs table
- [ ] **Task 3**: KG Explicit Edge Mapper — FK → edge with cardinality detection (1:1/1:N/M:N)
  - Junction table detection: exactly 2 FKs + composite PK → synthetic M:N edge
  - Self-referential FK support
  - Idempotent: re-run updates existing, doesn't duplicate
- [ ] **Task 4**: KG Node Generator — one `knowledge_node` per source table
  - `node_type = 'architecture'`, `node_subtype = 'schema_table'`
  - Title format: `<schema>.<table_name>`
  - AI description generation via BA-009 AI client (graceful degradation if unavailable)
- [ ] **Task 5**: KG Implicit Relationship Detector
  - Naming convention patterns: `<table>_id`, `<singular_table>_id`, camelCase
  - Type compatibility check (both INTEGER, both UUID, etc.)
  - Minimum 2 forms of evidence before AI scoring
  - AI confidence scoring (0.0-1.0) via BA-009
  - Skip columns with existing FK constraints
- [ ] **Task 6**: Confidence Scoring Service
  - Explicit FK → 1.0 (immutable)
  - AI-detected → 0.0-1.0
  - Admin confirm → 1.0 (irreversible)
  - Admin reject → status = 'rejected'
  - Default threshold: 0.5 (configurable)
- [ ] **Task 7**: KG Generation Handler — 9 endpoints
  - `POST /api/v1/data-sources/{id}/generate-kg`
  - `GET /api/v1/data-sources/{id}/kg-nodes`
  - `PATCH /api/v1/kg-nodes/{id}`
  - `GET /api/v1/data-sources/{id}/kg-edges`
  - `PATCH /api/v1/kg-edges/{id}/confidence`
  - `POST /api/v1/kg-edges/{id}/confirm`
  - `POST /api/v1/kg-edges/{id}/reject`
  - `GET /api/v1/kg-edges/{id}/unconfirm`
  - `GET /api/v1/data-sources/{id}/kg-status`
- [ ] **Task 8**: Config updates — add `schema_fk`, `schema_implicit`, `schema_many_to_many` edge types
- [ ] **Task 9**: Wire into composition root + integration test

---

## BA-012: Admin Sync Portal & Queue Management

### Migrations

| # | Content |
|---|---------|
| 025 | CREATE `query_queue`, `dead_letter_queue`, `rate_limit_state`, `usage_metrics` |

### New Files

```
internal/jobengine/
├── engine.go                    # Background job runner: FIFO, configurable concurrency
├── engine_test.go
├── heartbeat.go                 # Heartbeat monitor: detect stale jobs
└── heartbeat_test.go

internal/service/
├── sync_trigger.go              # Sync orchestration: concurrency guards, duration estimates
├── sync_trigger_test.go
├── query_queue.go               # Query queue: FIFO with priority, dead-letter
├── query_queue_test.go
├── rate_limiter.go              # Sliding-window rate limiting with fair-share allocation
└── rate_limiter_test.go

internal/handler/
├── sync_portal.go               # Sync endpoints + WebSocket progress
├── sync_portal_test.go
├── query_queue.go               # Queue management endpoints
├── query_queue_test.go
├── usage_dashboard.go           # Usage metrics + health dashboard
└── usage_dashboard_test.go

internal/ws/
├── handler.go                   # WebSocket upgrade + message broadcasting
└── handler_test.go
```

### Key Tasks (High-Level)

- [ ] **Task 1**: Background Job Engine (`internal/jobengine/`)
  - FIFO queue with configurable concurrency (default 3)
  - Auto-retry with exponential backoff: 30s × 2^attempt
  - Heartbeat every 60s; 3 missed = stale → failed
  - Status tracking: pending → running → completed/failed/cancelled
- [ ] **Task 2**: Migration 025 — query_queue, dead_letter_queue, rate_limit_state, usage_metrics
- [ ] **Task 3**: Sync Trigger Service
  - Full vs incremental sync
  - Concurrency guards: max 3 global (`KG_SYNC_MAX_CONCURRENT`), 1 per source
  - Duration estimation: `avg_duration × table_count × multiplier`
- [ ] **Task 4**: WebSocket Progress Handler (`internal/ws/`)
  - `WS /ws/sync/{job_id}/progress` — per-job progress
  - `GET /stream/sync/progress` — SSE for all running jobs
  - 2-second update interval
  - Payload: `{job_id, status, current_phase, progress_pct, tables_total, tables_processed, errors_count}`
- [ ] **Task 5**: Query Queue Service
  - FIFO with priority levels (high > normal)
  - Auto-scale: >50% capacity → 5 concurrent; <20% → 1 concurrent
  - Dead-letter: after 3 retries → dead_letter_queue
  - Replay: POST /queue/dead-letter/{id}/replay
- [ ] **Task 6**: Rate Limiter Service
  - Sliding-window algorithm (60-second window)
  - Dual tracking: request count AND token count
  - Fair-share: `floor(capacity / N_active_users)` (min 1)
- [ ] **Task 7**: Usage Dashboard Handler
  - Hourly/daily/monthly aggregations
  - Token budget vs spend
  - Response time percentiles (p50/p95/p99)
  - Provider health: healthy (<1%), degraded (1-10%), down (>10%)
- [ ] **Task 8**: Sync Portal Handler — 8 endpoints
  - `POST /api/sync/{data_source_id}/trigger`
  - `GET /api/sync/{job_id}/status`
  - `WS /ws/sync/{job_id}/progress`
  - `GET /stream/sync/progress`
  - `GET /api/queue/query?priority=high`
  - `GET /api/queue/dead-letter`
  - `POST /api/queue/dead-letter/{id}/replay`
  - `GET /api/usage/dashboard`
- [ ] **Task 9**: Wire into composition root + integration test

---

## Estimated Task Count

| BA | Tasks | Tests | Migrations |
|----|-------|-------|------------|
| BA-008 | 9 | ~6 test files | 2 |
| BA-012 | 9 | ~7 test files | 1 |
| **Total** | **18** | **~13 test files** | **3** |

> **Note:** Detailed step-by-step plans (with code in every step) will be written when Wave 1 is complete and we're ready to start Wave 2. The patterns established in Wave 1 (BA-007/BA-009) will carry forward.
