# ennam.kg.go Phase 2 — Master Development Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Go API server to support the Phase 2 Knowledge Graph AI Pipeline — covering external data source management, AI provider abstraction, KG generation orchestration, NL-to-SQL query, admin sync portal, and benchmark suite.

**Architecture:** Phase 2 builds on Phase 1's proven 3-layer architecture (Handler → Service → Store) with standard library HTTP, config-driven validation, and pure SQL stores. New domains (data sources, AI providers, sync jobs, benchmarks) each get their own model/store/service/handler packages following identical patterns. Two new cross-cutting concerns are introduced: AES-256 credential encryption (shared by BA-007 and BA-009) and a background job engine (shared by BA-008, BA-012).

**Tech Stack:** Go 1.22+ (std lib HTTP), PostgreSQL 14+, Redis (queue), AES-256-GCM encryption, golang-migrate, gorilla/websocket (BA-012 only), `log/slog`

---

## Wave Structure (from BA README)

```
Wave 1 (parallel):  BA-007 Data Source    +  BA-009 AI Provider
                        ↓                        ↓
Wave 2 (parallel):  BA-008 KG Generation  +  BA-012 Admin Sync
                        ↓                        ↓
Wave 3 (parallel):  BA-010 Visualization  +  BA-011 AI Query
                                                 ↓
Wave 4:             BA-013 Benchmark Suite
```

### Wave Dependencies

| Wave | BA | Hard Dependencies | Go-Relevant Scope |
|------|----|-------------------|--------------------|
| 1 | BA-007 | BA-001 (done) | 10 endpoints, 7 tables, encryption, external DB connector |
| 1 | BA-009 | BA-001 (done) | 9 endpoints, 4 tables, provider registry, circuit breaker, budget |
| 2 | BA-008 | BA-007, BA-009 (soft) | 9 endpoints, extends knowledge_nodes/edges, FK→edge mapping, AI implicit detection |
| 2 | BA-012 | BA-007, BA-008, BA-009 | 8 endpoints, 5 tables, job engine, WebSocket, rate limiting |
| 3 | BA-010 | BA-008 | 1 endpoint (schema-graph), mostly frontend — Go just serves data |
| 3 | BA-011 | BA-007, BA-008, BA-009 | 4 endpoints, 3 tables, NL→SQL pipeline, MCP source DB query |
| 4 | BA-013 | BA-011 | 8 endpoints, 4 tables, benchmark runner, accuracy scoring |

### Go API Scope Summary

| Metric | Count |
|--------|-------|
| New API endpoints | ~49 (Go-relevant, excludes frontend-only) |
| New database tables | ~23 |
| New migrations | ~10-12 (starting at 016) |
| New model files | ~8-10 |
| New store files | ~8-10 |
| New service files | ~8-10 |
| New handler files | ~8-10 |
| Shared infrastructure | encryption pkg, job engine, circuit breaker |

---

## Plan Documents

Each wave has its own detailed plan document:

| Plan | File | Status |
|------|------|--------|
| Wave 1: BA-007 Data Source Connection | [`2026-04-08-ennam-kg-go-phase2-wave1-ba007.md`](2026-04-08-ennam-kg-go-phase2-wave1-ba007.md) | ✅ Written |
| Wave 1: BA-009 AI Provider Abstraction | [`2026-04-08-ennam-kg-go-phase2-wave1-ba009.md`](2026-04-08-ennam-kg-go-phase2-wave1-ba009.md) | ✅ Written |
| Wave 2: BA-008 + BA-012 | [`2026-04-08-ennam-kg-go-phase2-wave2.md`](2026-04-08-ennam-kg-go-phase2-wave2.md) | 📋 Outlined |
| Wave 3-4: BA-010/011/013 | [`2026-04-08-ennam-kg-go-phase2-wave3-4.md`](2026-04-08-ennam-kg-go-phase2-wave3-4.md) | 📋 Outlined |

---

## Shared Infrastructure (Built in Wave 1, Reused Across Waves)

### 1. Encryption Package (`internal/crypto/`)

Both BA-007 (connection strings) and BA-009 (API keys) require AES-256-GCM encryption at rest. Build once in Wave 1.

```
internal/crypto/
├── aes.go          # Encrypt(plaintext, key) / Decrypt(ciphertext, key)
└── aes_test.go     # Round-trip, wrong key, tampered ciphertext
```

- Key source: `KG_ENCRYPTION_KEY` env var (32 bytes, base64-encoded)
- Algorithm: AES-256-GCM (authenticated encryption)
- Format: `nonce || ciphertext || tag` (single []byte blob)

### 2. Background Job Engine (`internal/jobengine/`)

BA-008 (KG generation), BA-012 (sync jobs), and BA-013 (benchmark runs) all need background job execution with status tracking. Build in Wave 2, but the DB schema (sync_jobs table) is created in Wave 1.

### 3. Circuit Breaker (`internal/circuitbreaker/`)

BA-009 defines circuit breaker for AI providers. This is self-contained within BA-009's service layer.

---

## Migration Numbering Plan

| Migration | Wave | Tables/Changes |
|-----------|------|----------------|
| 016 | W1 | `data_sources` |
| 017 | W1 | `source_schemas`, `source_tables`, `source_columns` |
| 018 | W1 | `source_foreign_keys`, `source_indexes` |
| 019 | W1 | `sync_jobs` |
| 020 | W1 | `ai_providers` |
| 021 | W1 | `ai_usage_logs`, `ai_budget_tracking` |
| 022 | W1 | `ai_provider_health` |
| 023 | W2 | Extend `knowledge_nodes` + `knowledge_edges` properties, new edge types |
| 024 | W2 | `kg_generation_jobs` |
| 025 | W2 | `query_queue`, `dead_letter_queue`, `rate_limit_state`, `usage_metrics` |
| 026 | W3 | `ai_queries`, `query_clarifications`, `query_favorites` |
| 027 | W4 | `benchmark_questions`, `benchmark_question_versions`, `benchmark_runs`, `benchmark_question_results` |

---

## Conventions (Inherited from Phase 1)

All Phase 2 code follows Phase 1 patterns exactly:

- **3-layer**: Handler → Service → Store (no shortcuts)
- **Standard library HTTP**: `net/http`, `http.ServeMux`, no framework
- **Pure SQL stores**: `database/sql` with `$1` params, no ORM
- **Config-driven**: New edge types, validation rules added to `config/config.yaml`
- **Error mapping**: validation → 400, not found → 404, conflict → 409, auth → 401/403, service unavailable → 503
- **Response envelope**: `{data: {...}, metadata: {...}}` for single entities, `{items: [...], metadata: {...}}` for lists
- **Table-driven tests**: Every handler, service, and store file has a `_test.go` companion
- **Composition root**: All new handlers wired in `buildRouter()` in `cmd/kg-server/main.go`
- **Logging**: `log/slog` with structured key-value pairs
- **Transactions**: `store.TxBeginner` interface for multi-table atomic operations

---

## Development Order Within Each Wave

### Wave 1 (BA-007 + BA-009 in parallel)

**BA-007 order:**
1. Encryption package (shared)
2. Migrations (016-019)
3. Models → Store → Service → Handler (bottom-up)
4. Config updates (new edge types if needed)
5. Composition root wiring
6. Integration tests

**BA-009 order:**
1. Migrations (020-022)
2. Models → Store → Service (circuit breaker, provider selection) → Handler
3. Config updates (`ai.provider_strategy`)
4. Composition root wiring
5. Integration tests

### Wave 2 (BA-008 + BA-012, after Wave 1)

Depends on BA-007 stores (schema metadata) and BA-009 services (AI requests).

### Wave 3 (BA-010 + BA-011, after Wave 2)

BA-010 Go scope is minimal (1 endpoint serving graph data).
BA-011 is the most complex — NL→SQL pipeline with AI + MCP.

### Wave 4 (BA-013, after Wave 3)

Depends on BA-011's query pipeline for benchmark execution.
