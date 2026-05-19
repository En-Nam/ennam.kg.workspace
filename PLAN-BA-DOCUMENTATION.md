# Plan: BA Documentation — Phase 2 Knowledge Graph AI Pipeline

**Team**: business-analyst + reviewer
**Seed Source**: `seed_129664ad5ef8` (interview `interview_20260408_033800`, ambiguity 0.168)
**Output Location**: `ennam.kg.requirements/documents/`
**Template**: `ennam.kg.requirements/documents/exampleBA.md`

---

## 1. Document Map (7 new BA docs)

| BA ID | Title | Seed Components | Est. FRs |
|---|---|---|---|
| **BA-007** | Data Source Connection & Schema Migration | data_source, schema_metadata | 6-8 |
| **BA-008** | Knowledge Graph Generation | knowledge_graph, implicit_relationship, graph_node, graph_edge | 5-7 |
| **BA-009** | AI Provider Abstraction Layer | ai_provider, query_queue | 4-5 |
| **BA-010** | Interactive KG Visualization | visualization_state | 6-8 |
| **BA-011** | AI Natural Language Query | ai_query, mcp_connector | 7-9 |
| **BA-012** | Admin Sync Portal & Queue Management | sync_job, sync_progress | 6-8 |
| **BA-013** | Benchmark Suite | benchmark_test | 4-5 |

**Totals**: ~38-50 FRs, ~120-160 ACs, NFRs starting from NFR-053

---

## 2. Writing Order (Dependency Waves)

### Wave 1 — No Phase 2 dependencies (parallel)

**BA-007: Data Source Connection & Schema Migration**
- FR-001: Data Source Registration (connection string, SSL cert, name, description)
- FR-002: Connection Testing (validate connectivity, verify SSL, check permissions)
- FR-003: Schema Extraction (tables, columns, data types, constraints, indexes)
- FR-004: Foreign Key & Index Discovery
- FR-005: Metadata Storage (persist in internal PostgreSQL)
- FR-006: Incremental Schema Sync (detect schema drift on re-sync)
- State machines: DataSource lifecycle, SyncJob lifecycle
- Entities: `data_sources`, `source_schemas`, `source_tables`, `source_columns`, `source_foreign_keys`, `sync_jobs`

**BA-009: AI Provider Abstraction Layer**
- FR-001: Provider Registry (capabilities, rate limits, costs)
- FR-002: Claude Max Integration (subscription-based, rate-limited)
- FR-003: Pay-Per-Token Fallback (Anthropic API, OpenAI, etc.)
- FR-004: Provider Selection Strategy (prefer Claude Max, fallback on rate limit/error)
- FR-005: Request/Response Normalization (unified interface)
- Entities: `ai_providers`, `ai_usage_log`
- Critical NFR: rate limit tracking, circuit breaker pattern

### Wave 2 — Depends on Wave 1 (parallel)

**BA-008: Knowledge Graph Generation** (needs BA-007 data entities)
- FR-001: Explicit Relationship Mapping (FK -> graph edges with cardinality)
- FR-002: Implicit Relationship Detection (AI-powered: naming conventions, data patterns)
- FR-003: KG Node Generation (one node per table, enriched metadata)
- FR-004: KG Edge Generation (FK edges + AI-detected edges with confidence)
- FR-005: Relationship Confidence Scoring (explicit=1.0, AI-detected=0.0-1.0)
- State machines: KGGeneration lifecycle
- Entities: extends `knowledge_nodes` + `knowledge_edges` with new types

**BA-012: Admin Sync Portal & Queue Management** (needs BA-007 sync + BA-009 rate limits)
- FR-001: Sync Trigger (super admin manual trigger)
- FR-002: Background Job Engine (async execution + status tracking)
- FR-003: Real-Time Progress Monitoring (WebSocket/SSE)
- FR-004: Query Queue Management (FIFO with priority)
- FR-005: Rate Limit Enforcement (Claude Max: 2-5 concurrent users)
- FR-006: Usage Dashboard (query counts, token usage, response times)
- State machines: SyncJob, QueryJob lifecycles
- Entities: `sync_jobs`, `query_queue`, `rate_limit_state`, `usage_metrics`

### Wave 3 — Depends on Wave 2 (parallel)

**BA-010: Interactive KG Visualization** (needs BA-008 KG structure)
- FR-001: Graph Rendering (force-directed layout)
- FR-002: Interactive Controls (zoom, pan, drag, select, hover tooltips)
- FR-003: Edge Type Differentiation (FK=solid, AI-detected=dashed, confidence opacity)
- FR-004: Filter & Search (by schema, table, relationship type, name)
- FR-005: Node Detail Panel (click -> columns, types, constraints, relations)
- FR-006: Layout Modes (force-directed, hierarchical, radial, schema-grouped)
- FR-007: Export (PNG/SVG)
- Extends BA-004 patterns (Cytoscape.js or alternative for Neo4j Browser-style)

**BA-011: AI Natural Language Query** (needs BA-008 KG + BA-009 AI)
- FR-001: Query Input Interface (NL text input + query history)
- FR-002: Query Intent Parsing (NLP -> structured query plan via KG context)
- FR-003: SQL Generation (query plan -> SQL using KG metadata)
- FR-004: MCP Connector — Live Source DB Query (read-only, parameterized)
- FR-005: Response Formatting (tabular, chart suggestions, NL summary)
- FR-006: Query Explanation (which KG metadata informed the query)
- FR-007: Error Handling & Clarification (ambiguous -> ask, SQL error -> retry)
- FR-008: Query History & Favorites
- Critical NFRs: 95% accuracy, <5s response, read-only source access

### Wave 4 — Depends on Wave 3

**BA-013: Benchmark Suite** (needs BA-011 query interface)
- FR-001: Test Question Bank (50-100 per data source)
- FR-002: Verified Answer Set (expected SQL + result sets)
- FR-003: Automated Test Runner (execute, compare)
- FR-004: Accuracy Scoring (exact match, semantic match, partial credit)
- FR-005: Regression Detection (baseline comparison)
- Entities: `benchmark_questions`, `benchmark_runs`, `benchmark_results`

---

## 3. Input Requirements per BA Doc

**Mandatory for all**:
- Seed `seed_129664ad5ef8` (relevant sections)
- Template: `ennam.kg.requirements/documents/exampleBA.md`
- Style references: BA-001 (backend), BA-004 (frontend)
- Current DB schema: `ennam.kg.go/db/migrations/` (15 migrations)
- Config: `ennam.kg.go/config/config.yaml` (node types, edge whitelist)
- Architecture: `ennam.kg.go/CLAUDE.md`, `ennam.kg.next/CLAUDE.md`, `ennam.kg.python/CLAUDE.md`
- Docker topology: `docker-compose.yml`

**Per-document context**:
| BA | Additional Context |
|---|---|
| BA-007 | PostgreSQL `information_schema` patterns, SSL connection |
| BA-008 | Existing edge whitelist, `knowledge_nodes` table schema |
| BA-009 | Claude Max rate limits, Anthropic API model |
| BA-010 | BA-004 as predecessor (existing graph viz FRs/NFRs) |
| BA-011 | MCP protocol spec, BA-002 (existing MCP bridge patterns) |
| BA-012 | BA-006 (monitoring), existing Redis queue from BA-003 |
| BA-013 | NLP-to-SQL benchmarks (Spider, WikiSQL for reference) |

---

## 4. Quality Checklist (per doc, reviewer validates)

- [ ] All 10 sections present (Overview → Open Questions)
- [ ] Every FR has: Description, Use Cases table, Business Rules table, Gherkin ACs
- [ ] Every NFR has measurable target (specific numbers)
- [ ] State machines use Mermaid `stateDiagram-v2`
- [ ] Data entities: Attribute, Type, Constraints, Description columns
- [ ] API Mapping: Method, Path, FR ref, Description, Access columns
- [ ] NFR IDs globally unique, sequential from NFR-053
- [ ] FR IDs scoped per document (BA-007/FR-001, etc.)
- [ ] No entity name collisions with Phase 1 tables
- [ ] No API path collisions with existing 40+ endpoints
- [ ] New edge/node types follow existing naming conventions

---

## 5. Post-Completion Deliverables

- [ ] 7 BA docs at `ennam.kg.requirements/documents/`
- [ ] Updated `ennam.kg.requirements/CLAUDE.md` — add BA-007 → BA-013 to document table + reading paths
- [ ] Updated `ennam.kg.requirements/README.md` if exists
- [ ] Cross-document consistency verified (entity names, NFR numbering, API paths)

---

## 6. Seed Summary (for BA reference)

**Goal**: End-to-end pipeline: PostgreSQL datawarehouse → Knowledge Graph → AI natural language query

**Key constraints**:
- Stack: Go + Python + NextJS on AWS (inherit Phase 1)
- AI: Claude Max $200/mo primary, pay-per-token fallback, provider abstraction layer
- Data: Hybrid approach — KG from schema+metadata (internal), live query source DB via MCP (external)
- Source DBs: up to 60-70 tables, largest ~60GB
- Sync: Manual trigger by super admin, background job, realtime progress
- Users: 2-5 concurrent AI query users (MVP)
- Accuracy: >= 95% on benchmark, <5s response
- Security: SSL-only connections (MVP)
- Dev: AI-driven, ASAP timeline

**14 Ontology Entities**: data_source, schema_metadata, knowledge_graph, implicit_relationship, graph_node, graph_edge, ai_query, ai_provider, query_queue, sync_job, sync_progress, benchmark_test, mcp_connector, visualization_state

**7 Exit Conditions**: pipeline operational, accuracy >= 95%, p95 < 5s, KG explicit+implicit, viz functional, admin sync works, benchmark delivered
