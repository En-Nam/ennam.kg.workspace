# Wave 3-4: BA-010/011/013 — Go API Plan Outline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement schema graph API for visualization, NL-to-SQL query pipeline, and benchmark suite for accuracy validation.

**Architecture:** BA-010 is minimal Go work (1 endpoint). BA-011 is the most complex feature — a multi-stage AI pipeline. BA-013 builds on BA-011's query pipeline for automated testing.

**Prerequisites:** Wave 2 complete (BA-008 KG data + BA-012 job engine)

---

## BA-010: Interactive KG Visualization (Go Scope: Minimal)

### API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/kg/schema-graph?project_id={id}&data_source_id={id}` | Fetch full schema KG data for Cytoscape.js visualization |

### Tasks

- [ ] **Task 1**: Schema Graph Handler
  - Query knowledge_nodes WHERE `node_subtype = 'schema_table'` AND data_source_id
  - Query knowledge_edges WHERE source/target in those nodes
  - Return `{nodes: [...], edges: [...]}` with Cytoscape.js-compatible format
  - Include: confidence_score, detection_method, cardinality on edges
  - Include: column_count, row_count_estimate, ai_description on nodes

- [ ] **Task 2**: Wire into composition root

> **Note:** BA-010 is primarily a frontend feature (Cytoscape.js in NextJS). The Go API just serves the data.

---

## BA-011: AI Natural Language Query

### Migrations

| # | Content |
|---|---------|
| 026 | CREATE `ai_queries`, `query_clarifications`, `query_favorites` |

### New Files

```
internal/service/
├── nl_query.go                  # NL→SQL pipeline orchestrator
├── nl_query_test.go
├── query_intent.go              # AI intent parsing: NL → structured query plan
├── query_intent_test.go
├── sql_generator.go             # Query plan → parameterized SQL
├── sql_generator_test.go
├── source_executor.go           # Execute SQL on source DB via read-only connection
└── source_executor_test.go

internal/store/
├── ai_query.go                  # AIQueryStore: CRUD + history + favorites
└── ai_query_test.go

internal/handler/
├── nl_query.go                  # 4 endpoints
└── nl_query_test.go
```

### Pipeline Architecture

```
User NL Input
    ↓
1. Query Intent Parsing (AI via BA-009)
   - Input: NL text + KG metadata context (tables, columns, relationships)
   - Output: Structured query plan JSON
     { tables[], joins[], filters[], aggregations[], group_by[], order_by[], limit }
    ↓
2. SQL Generation
   - Input: Query plan + FK relationships from KG
   - Output: Parameterized SQL with JOIN paths derived from KG edges
   - Validation: all tables/columns exist in KG metadata
    ↓
3. Source DB Execution (via MCP or direct read-only connection)
   - Read-only enforcement
   - 30-second timeout
   - Max 10,000 rows
   - Parameterized queries only
    ↓
4. Response Formatting
   - Paginated data table
   - NL summary of results
   - Query explanation (which tables/relationships used)
   - Generated SQL (for transparency)
```

### Key Tasks (High-Level)

- [ ] **Task 1**: Migration 026 — ai_queries, query_clarifications, query_favorites
- [ ] **Task 2**: AI Query Store — CRUD, history (90-day retention), favorites, sharing
- [ ] **Task 3**: Query Intent Parser
  - Build KG metadata context (tables, columns, relationships, business rules)
  - Trim context to fit AI token budget
  - AI request via BA-009 selector
  - Parse structured query plan JSON from AI response
  - Validate plan against KG metadata
- [ ] **Task 4**: SQL Generator
  - Transform query plan → parameterized SQL
  - FK-based JOINs from KG edges (not guessed)
  - Default LIMIT = 1,000 (max 10,000)
  - All values parameterized ($1, $2, ...)
- [ ] **Task 5**: Source DB Executor
  - Read-only connection to source DB (reuse BA-007 encrypted credentials)
  - 30-second query timeout
  - Result set limit: 10,000 rows + truncation warning
  - Never use read-write connection
- [ ] **Task 6**: Ambiguity Detection & Clarification
  - Detect: multi-table name matches, unclear column mappings, ambiguous intent
  - Return 2-4 clarification options
  - Store clarification in `query_clarifications` table
- [ ] **Task 7**: NL Query Handler — 4 endpoints
  - `POST /api/v1/queries/submit` — full pipeline
  - `GET /api/v1/queries/history?data_source_id={id}` — max 20 recent
  - `POST /api/v1/queries/{id}/star` — favorite
  - `GET /api/v1/queries/{id}` — detail with explanation
- [ ] **Task 8**: Wire into composition root + integration test

### Business Rules

- Query length: 3-2,000 characters
- History retention: 90 days (favorited exempt from purge)
- Re-run creates new record (AI re-parses against current KG)
- Auto-retry on SQL error: max 2 attempts with modified SQL

---

## BA-013: Benchmark Suite

### Migrations

| # | Content |
|---|---------|
| 027 | CREATE `benchmark_questions`, `benchmark_question_versions`, `benchmark_runs`, `benchmark_question_results` |

### New Files

```
internal/service/
├── benchmark.go                 # Benchmark orchestrator: run, score, compare
├── benchmark_test.go
├── benchmark_scorer.go          # Multi-level accuracy scoring
└── benchmark_scorer_test.go

internal/store/
├── benchmark.go                 # BenchmarkStore: questions, runs, results
└── benchmark_test.go

internal/handler/
├── benchmark.go                 # 8 endpoints
└── benchmark_test.go
```

### Key Tasks (High-Level)

- [ ] **Task 1**: Migration 027 — all benchmark tables
- [ ] **Task 2**: Benchmark Store — questions CRUD, runs tracking, results persistence
- [ ] **Task 3**: Test Question Management
  - Create/update questions with difficulty (simple/medium/complex) and query type
  - Expected SQL verification: execute against source DB, store result hash
  - Schema drift detection: flag for re-verification on schema change
  - Minimum 50 active questions per data source before run
  - Recommended distribution: 30% simple, 40% medium, 30% complex
- [ ] **Task 4**: Automated Test Runner
  - Pre-flight: source connected, ≥50 verified questions, no active run
  - Parallel execution: concurrency 5 (default, max 20)
  - Timeout: 60 seconds per question
  - Each question: submit to BA-011 NL query pipeline, capture generated SQL + results
- [ ] **Task 5**: Accuracy Scorer
  - **Exact match**: result hash identical (SHA-256 of sorted, normalized rows)
  - **Semantic match**: logically equivalent (column reorder, row order when no ORDER BY)
  - **Partial credit**: correct tables/joins but wrong results
  - **Failure**: incorrect or error
  - Formula: `accuracy = (exact + semantic) / total × 100`
  - Sub-scores by difficulty AND by query type
- [ ] **Task 6**: Regression Detection
  - Compare current run vs baseline
  - Regression: baseline (exact|semantic) but current (partial|failure)
  - Alert threshold: 2% accuracy drop (configurable)
  - **95% EXIT CONDITION**: Phase 2 exit requires accuracy ≥ 95%
- [ ] **Task 7**: Benchmark Handler — 8 endpoints
  - `POST /api/v1/benchmark/questions`
  - `GET /api/v1/benchmark/questions?data_source_id={id}`
  - `PUT /api/v1/benchmark/questions/{id}`
  - `POST /api/v1/benchmark/questions/{id}/verify-answer`
  - `POST /api/v1/benchmark/runs`
  - `GET /api/v1/benchmark/runs/{id}`
  - `GET /api/v1/benchmark/runs/{id}/comparison?baseline_id={baseline}`
  - `POST /api/v1/benchmark/runs/{id}/set-baseline`
- [ ] **Task 8**: Wire into composition root + integration test

### Result Hash Algorithm

```go
// Normalize results for hash comparison:
// 1. Sort rows by all columns (left to right)
// 2. NULL → sentinel string "__NULL__"
// 3. Numeric: round to 4 decimal places
// 4. String: trim whitespace, lowercase
// 5. SHA-256 of JSON-encoded sorted rows
```

---

## Estimated Task Count

| BA | Tasks | Tests | Migrations |
|----|-------|-------|------------|
| BA-010 | 2 | ~1 test file | 0 |
| BA-011 | 8 | ~5 test files | 1 |
| BA-013 | 8 | ~3 test files | 1 |
| **Total** | **18** | **~9 test files** | **2** |

---

## Cross-Wave Summary

| Wave | BAs | Tasks | Migrations | New Tables |
|------|-----|-------|------------|------------|
| 1 | BA-007 + BA-009 | 23 | 7 (016-022) | 11 |
| 2 | BA-008 + BA-012 | 18 | 3 (023-025) | ~6 |
| 3-4 | BA-010 + BA-011 + BA-013 | 18 | 2 (026-027) | ~7 |
| **Total** | **7 BAs** | **59 tasks** | **12 migrations** | **~24 tables** |

> **Note:** Detailed step-by-step plans (with code in every step) will be written when the preceding wave is complete. Each wave builds on the infrastructure and patterns established by previous waves.
