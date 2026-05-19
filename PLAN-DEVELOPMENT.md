# Plan: Development — Phase 2 Knowledge Graph AI Pipeline

**Team**: team-lead, backend-dev, web-dev, test-worker, reviewer
**Prerequisites**: All 7 BA docs approved + UI designs handed off
**Stack**: Go + Python + NextJS on AWS (inherit Phase 1)

---

## 1. Sprint Structure (6 sprints)

### Sprint 1: Foundation Layer
**BAs**: BA-007 (Data Source) + BA-009 (AI Provider)

| Task | Agent | Domain | Dependencies |
|---|---|---|---|
| DB migrations 016-022 (data_sources, source_schemas, source_tables, source_columns, source_foreign_keys, ai_providers, ai_usage_log) | backend-dev | `ennam.kg.go/db/migrations/` | none |
| Go models + stores for data source CRUD | backend-dev | `internal/datasource/` | migrations |
| Go service: connection testing (SSL validation) | backend-dev | `internal/datasource/` | models |
| Go service: schema extraction (information_schema queries) | backend-dev | `internal/datasource/` | models |
| Go handlers: data source REST endpoints | backend-dev | `internal/handler/` | services |
| Go AI provider interface + Claude Max adapter | backend-dev | `internal/ai/` | none |
| Go AI provider fallback adapter (pay-per-token) | backend-dev | `internal/ai/` | interface |
| Go rate limit tracking service | backend-dev | `internal/ratelimit/` | none |
| Config.yaml: new node types + edge whitelist entries | backend-dev | `config/` | none |
| NextJS: Data source management page (list, add, edit, test) | web-dev | `src/app/(dashboard)/data-sources/` | Pencil designs |
| NextJS: Schema browser component | web-dev | `src/components/` | API endpoints |
| Unit tests for connection, schema extraction, AI provider | test-worker | tests | implementation |
| Code review Sprint 1 | reviewer | all | all above |

**Parallelization**: backend-dev on datasource + AI provider can be 2 separate worktrees

---

### Sprint 2: Knowledge Graph Engine
**BA**: BA-008 (KG Generation)

| Task | Agent | Domain | Dependencies |
|---|---|---|---|
| Go service: explicit FK relationship mapper | backend-dev | `internal/kggen/` | Sprint 1 schema data |
| Go service: implicit relationship detector (AI-powered) | backend-dev | `internal/kggen/` | Sprint 1 AI provider |
| Go service: KG node/edge generation | backend-dev | `internal/kggen/` | FK + implicit detectors |
| Go service: confidence scoring system | backend-dev | `internal/kggen/` | edge generation |
| Extend knowledge_edges: `confidence` column + `detection_method` enum | backend-dev | migrations | none |
| Go handlers: KG generation trigger + status endpoints | backend-dev | `internal/handler/` | services |
| NextJS: KG generation progress indicator | web-dev | `src/components/` | API endpoints |
| Unit tests for relationship detection, KG generation | test-worker | tests | implementation |
| Code review Sprint 2 | reviewer | all | all above |

---

### Sprint 3: Visualization + Admin Portal
**BAs**: BA-010 (KG Viz) + BA-012 (Admin Sync)

| Task | Agent | Domain | Dependencies |
|---|---|---|---|
| Go service: sync job engine (background jobs) | backend-dev | `internal/jobs/` | Sprint 1 datasource |
| Go handler: WebSocket/SSE for progress streaming | backend-dev | `internal/handler/` | job engine |
| Go service: rate limit enforcement (token bucket, concurrency) | backend-dev | `internal/ratelimit/` | Sprint 1 rate limit |
| Go handlers: sync trigger, progress, usage endpoints | backend-dev | `internal/handler/` | services |
| NextJS: Interactive KG viz (zoom, drag, filter, search, edge types) | web-dev | `src/app/(dashboard)/knowledge-graph/` | Pencil designs + KG API |
| NextJS: Node detail panel (sidebar) | web-dev | `src/components/` | KG API |
| NextJS: Admin sync portal (trigger, progress, history) | web-dev | `src/app/(dashboard)/admin/sync/` | Pencil designs + sync API |
| Frontend component tests + backend job engine tests | test-worker | tests | implementation |
| Code review Sprint 3 | reviewer | all | all above |

**Parallelization**: web-dev on KG viz + backend-dev on admin/sync can work in parallel

---

### Sprint 4: NLP Query Core
**BA**: BA-011 (AI Natural Language Query)

| Task | Agent | Domain | Dependencies |
|---|---|---|---|
| Go service: query intent parsing (NL -> query plan via KG context) | backend-dev | `internal/nlquery/` | Sprint 2 KG + Sprint 1 AI |
| Go service: SQL generation (query plan -> SQL) | backend-dev | `internal/nlquery/` | intent parser |
| Go service: MCP connector for live source DB query (read-only) | backend-dev | `internal/mcp_connector/` | Sprint 1 datasource |
| Security: read-only enforcement, query timeout (5s), row limit (1000), DDL/DML block | backend-dev | `internal/mcp_connector/` | connector |
| Go service: response formatting (tabular + NL summary) | backend-dev | `internal/nlquery/` | SQL gen + connector |
| Go service: query queue with rate limiting integration | backend-dev | `internal/nlquery/` | Sprint 3 rate limiter |
| Go handlers: query submission, results, history endpoints | backend-dev | `internal/handler/` | services |
| NextJS: Query input page (chat-style, input, results, table) | web-dev | `src/app/(dashboard)/query/` | Pencil designs |
| Query accuracy tests against sample datasets | test-worker | tests | implementation |
| Code review Sprint 4 | reviewer | all | all above |

---

### Sprint 5: Query Refinement + Monitoring
**BAs**: BA-011 (continued) + BA-012 (queue management)

| Task | Agent | Domain | Dependencies |
|---|---|---|---|
| Go service: query clarification flow (ambiguous -> suggest) | backend-dev | `internal/nlquery/` | Sprint 4 query pipeline |
| Go service: query explanation (KG path used) | backend-dev | `internal/nlquery/` | Sprint 4 query pipeline |
| Go service: query history + favorites persistence | backend-dev | `internal/nlquery/` | Sprint 4 |
| Go service: full rate limiting for Claude Max (2-5 concurrent) | backend-dev | `internal/ratelimit/` | Sprint 3 |
| Go handlers: usage metrics endpoints | backend-dev | `internal/handler/` | rate limiter |
| NextJS: Query explanation UI toggle | web-dev | `src/components/` | explanation API |
| NextJS: Query history + favorites | web-dev | `src/components/` | history API |
| NextJS: Usage dashboard (charts, gauges) | web-dev | `src/app/(dashboard)/admin/usage/` | Pencil designs |
| Rate limiting + concurrent user tests | test-worker | tests | implementation |
| Code review Sprint 5 | reviewer | all | all above |

---

### Sprint 6: Benchmark + E2E Integration
**BA**: BA-013 (Benchmark Suite)

| Task | Agent | Domain | Dependencies |
|---|---|---|---|
| Go service: benchmark question bank management | backend-dev | `internal/benchmark/` | none |
| Go service: automated test runner (execute + compare) | backend-dev | `internal/benchmark/` | Sprint 4 query pipeline |
| Go service: accuracy scoring (exact, semantic, partial) | backend-dev | `internal/benchmark/` | test runner |
| Go service: regression detection (baseline comparison) | backend-dev | `internal/benchmark/` | scoring |
| Go handlers: benchmark CRUD + run endpoints | backend-dev | `internal/handler/` | services |
| NextJS: Benchmark dashboard (run, results, trends) | web-dev | `src/app/(dashboard)/benchmarks/` | Pencil designs |
| E2E integration tests: full pipeline (connect -> extract -> KG -> query -> verify) | test-worker | tests | all sprints |
| Full code review of Phase 2 | reviewer | all | all above |

---

## 2. New Go Packages

```
internal/datasource/       — connection management, schema extraction
  ├── models.go            — DataSource, SourceSchema, SourceTable structs
  ├── store.go             — SQL queries (CRUD + information_schema)
  ├── service.go           — business logic (connect, test, extract)
  └── handler.go           — HTTP handlers

internal/ai/               — provider abstraction layer
  ├── provider.go          — Provider interface + CompletionOpts/Result
  ├── claude_max.go        — Claude Max adapter (rate-limit aware)
  ├── anthropic_api.go     — Pay-per-token fallback adapter
  └── selector.go          — Provider selection strategy

internal/kggen/            — knowledge graph generation
  ├── explicit.go          — FK relationship mapper
  ├── implicit.go          — AI-powered implicit relationship detector
  ├── generator.go         — KG node/edge generation orchestrator
  └── confidence.go        — Confidence scoring

internal/nlquery/          — natural language query pipeline
  ├── parser.go            — Query intent parsing (NL -> plan)
  ├── sqlgen.go            — SQL generation (plan -> SQL via KG context)
  ├── formatter.go         — Response formatting (table + NL summary)
  ├── clarifier.go         — Ambiguous query handling
  ├── explainer.go         — Query explanation (KG path)
  └── history.go           — Query history + favorites

internal/mcp_connector/    — source DB live query
  ├── connector.go         — Connection pool + read-only enforcement
  └── security.go          — Timeout, row limit, DDL/DML block

internal/ratelimit/        — rate limiting
  ├── token_bucket.go      — Per-user token bucket
  └── concurrency.go       — Global concurrency limiter (Claude Max)

internal/benchmark/        — benchmark suite
  ├── models.go            — Question, Run, Result structs
  ├── runner.go            — Test execution engine
  ├── scorer.go            — Accuracy scoring
  └── regression.go        — Regression detection

internal/jobs/             — background job engine
  ├── engine.go            — Job runner with status tracking
  └── progress.go          — WebSocket/SSE progress streaming
```

---

## 3. New NextJS Routes

```
src/app/(dashboard)/
├── data-sources/
│   ├── page.tsx           — List all connected sources
│   └── [id]/
│       └── page.tsx       — Source detail + schema browser
├── knowledge-graph/
│   └── page.tsx           — Interactive KG visualization
├── query/
│   └── page.tsx           — AI NL query interface
├── admin/
│   ├── sync/
│   │   └── page.tsx       — Sync trigger + progress
│   └── usage/
│       └── page.tsx       — Usage + rate limit dashboard
└── benchmarks/
    └── page.tsx           — Benchmark runs + results
```

---

## 4. Database Migrations (estimated)

```
016_create_data_sources.sql
017_create_source_schemas.sql
018_create_source_tables_and_columns.sql
019_create_source_foreign_keys.sql
020_create_ai_providers.sql
021_create_ai_usage_log.sql
022_extend_knowledge_edges_confidence.sql
023_create_sync_jobs.sql
024_create_query_queue.sql
025_create_query_history.sql
026_create_benchmark_tables.sql
027_create_usage_metrics.sql
```

---

## 5. Dependency Graph

```
Sprint 1 (Foundation)
├── Data Source CRUD + Schema Extraction
└── AI Provider Abstraction + Rate Limiter
         │
Sprint 2 (KG Engine)
├── Explicit FK Mapper
├── Implicit AI Detector
└── KG Node/Edge Generator
         │
Sprint 3 (Viz + Admin) ──────────────────┐
├── Interactive KG Visualization          │
├── Sync Job Engine + Progress           │
└── Rate Limit Enforcement                │
         │                                │
Sprint 4 (NLP Query) ←───────────────────┘
├── Intent Parser → SQL Gen → MCP Connector
├── Response Formatter
└── Query Queue Integration
         │
Sprint 5 (Refinement)
├── Clarification + Explanation
├── History + Favorites
└── Usage Dashboard
         │
Sprint 6 (Benchmark + E2E)
├── Question Bank + Test Runner
├── Accuracy Scoring + Regression
└── Full E2E Integration Tests
```

---

## 6. Quality Gates per Sprint

### Per-Sprint (test-worker + reviewer)

- [ ] All Gherkin ACs from BA docs → automated test cases
- [ ] State machine transitions: valid pass, invalid return correct error
- [ ] API endpoints match BA API Mapping (method, path, response format)
- [ ] NFR targets met (latency, error rates)
- [ ] Code review: no critical findings
- [ ] Domain boundaries respected (no cross-domain file modifications)
- [ ] API contracts match Apidog specs

### Final Acceptance (Sprint 6 complete)

- [ ] All 7 BA docs implemented with passing tests
- [ ] Benchmark: >= 95% accuracy on 50-100 questions
- [ ] NLP query p95 response time < 5 seconds
- [ ] Rate limiting: 5 concurrent users without errors
- [ ] Full code review: no critical findings
- [ ] docker-compose.yml updated, all services start
- [ ] CLAUDE.md updated in: ennam.kg.go, ennam.kg.next, ennam.kg.python, ennam.kg.requirements
- [ ] `.serena/memories/` updated with Phase 2 state

---

## 7. Agent Coordination

| Agent | Responsibilities |
|---|---|
| **team-lead** | Decompose each BA → task list, define API contracts via Apidog MCP, spawn workers, manage dependencies, resolve cross-domain issues |
| **backend-dev** | Go: handlers, services, stores, migrations. Owns `internal/` and `db/migrations/` |
| **web-dev** | NextJS: pages, components, hooks. References Pencil node IDs via `batch_get()`. Owns `src/app/`, `src/components/`, `src/hooks/` |
| **test-worker** | Unit, integration, E2E tests. Owns `tests/`, `__tests__/`, `*.test.*` |
| **reviewer** | Code review per sprint. Gates next sprint. Uses `code-review-checklist` skill |

### Branch Naming Convention
```
backend/task-001-data-source-crud
backend/task-002-schema-extraction
backend/task-003-ai-provider-interface
frontend/task-004-data-source-page
frontend/task-005-kg-visualization
tests/task-006-s1-unit-tests
```

### Commit Convention
```
feat(datasource): add POST /api/v1/data-sources endpoint

Task: TASK-001
```

---

## 8. Key Files to Modify/Extend

| File | Changes |
|---|---|
| `ennam.kg.go/config/config.yaml` | New node types (table_node, etc.), edge whitelist entries |
| `ennam.kg.go/internal/handler/routes.go` | Register new endpoint groups |
| `ennam.kg.go/db/migrations/` | 12 new migration files |
| `ennam.kg.next/src/app/(dashboard)/` | 7 new route directories |
| `ennam.kg.next/src/components/` | Graph viz, query UI, admin components |
| `ennam.kg.next/src/hooks/` | New TanStack Query hooks for Phase 2 APIs |
| `ennam.kg.next/src/types/` | TypeScript types mirroring Go models |
| `docker-compose.yml` | If new services needed (likely extend kg-server) |
| All CLAUDE.md files | Document Phase 2 additions |
