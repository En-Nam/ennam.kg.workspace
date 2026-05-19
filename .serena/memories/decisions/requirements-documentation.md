# Requirements Documentation — BA Analysis Suite

Created: 2026-04-08, Phase 2 added: 2026-04-08
Commit: `89f248c` on `ennam.kg.requirements/main`

## Location
- Phase 1: `ennam.kg.requirements/documents/phase1/`
- Phase 2: `ennam.kg.requirements/documents/phase2/`

## Phase 1 — Platform Foundation (complete)

| Document | FRs | ACs | Domain |
|----------|-----|-----|--------|
| BA-001-platform-foundation.md | 7 | 39 | Go API: nodes, edges, search, traversal, auth, sessions |
| BA-002-mcp-bridge.md | 6 | 26 | MCP stdio bridge: 25 tools, auto-injection |
| BA-003-code-indexing.md | 7 | 33 | Python: tree-sitter, AI summary, queue |
| BA-004-dashboard.md | 12 | 48 | NextJS: 14 routes, graph viz, BFF proxy |
| BA-005-enforcement.md | 6 | 24 | Gate 1 + Gate 2, edge whitelist, hooks |
| BA-006-deployment-ops.md | 7 | 38 | Docker, AWS, CI/CD, migrations |
| **Phase 1 Total** | **45** | **208** | |

## Phase 2 — Knowledge Graph AI Pipeline (draft, 2026-04-08)

Seed: `seed_129664ad5ef8` (ambiguity 0.168)

| Document | FRs | NFR Range | Domain |
|----------|-----|-----------|--------|
| BA-007-data-source-connection.md | 6 | NFR-053→058 | PostgreSQL source, schema extraction, incremental sync |
| BA-008-knowledge-graph-generation.md | 5 | NFR-059→066 | FK→edge mapping, AI implicit detection, confidence |
| BA-009-ai-provider-abstraction.md | 5 | NFR-067→073 | Claude Max + fallback, circuit breaker, budget |
| BA-010-interactive-kg-visualization.md | 7 | NFR-074→079 | Cytoscape.js schema graph, 4 layouts, export |
| BA-011-ai-natural-language-query.md | 8 | NFR-080→087 | NL→SQL, MCP source DB query, history |
| BA-012-admin-sync-portal.md | 6 | NFR-088→094 | Sync trigger, jobs, WebSocket, rate limiting |
| BA-013-benchmark-suite.md | 5 | NFR-095→099 | Test questions, accuracy scoring, regression |
| **Phase 2 Total** | **42** | **47 NFRs** | **~245 ACs, ~104 APIs, 24 entities** |

### Development Waves
Wave 1: BA-007 + BA-009 (parallel) → Wave 2: BA-008 + BA-012 → Wave 3: BA-010 + BA-011 → Wave 4: BA-013

## Phase 3 — Projects, Users & Platform Administration (draft, 2026-04-13)

Design spec: `documents/phase3/projects-users-platform-admin-spec.md`

| Document | FRs | NFR Range | Domain |
|----------|-----|-----------|--------|
| BA-014-user-accounts-authentication.md | 6 | NFR-100→106 | User CRUD, bcrypt auth, login/session, lockout |
| BA-015-project-management-access-control.md | 6 | NFR-110→115 | Project CRUD, membership, roles, archive |
| BA-016-platform-administration.md | 5 | NFR-120→125 | API keys, activity feed, settings, feature flags |
| **Phase 3 Total** | **17** | **19 NFRs** | **~35 endpoints, 3 new tables, 2 extensions** |

### Development Order
Step 1: BA-014 → Step 2: BA-015 (depends on users table) → Step 3: BA-016 (depends on both)

### Migrations: 032 (users), 033 (project_members + projects ext), 034 (system_settings), 035 (audit_trail ext)

## Phase 4 — AI Query UI/UX Enhancement (draft, 2026-04-14)

Seed: `seed_fb4151930647` (ambiguity 0.168)

| Document | FRs | NFR Range | Domain |
|----------|-----|-----------|--------|
| BA-017-conversational-ai-interface.md | 6 | NFR-130→136 | Threads, SSE streaming, multi-turn context, history |
| BA-018-rich-response-rendering.md | 6 | NFR-140→146 | Charts (Recharts), markdown, code blocks, smart aggregation |
| BA-019-ai-tools-actions-insights.md | 7 | NFR-150→157 | 9-tool menu, AI suggestions, insights, confidence, favorites |
| **Phase 4 Total** | **19** | **22 NFRs** | **~120 ACs, 2 new tables, 4 JSONB extensions** |

### Development Order
Step 1: BA-017 (foundation) → Step 2: BA-018 + BA-019 (parallel, both depend on BA-017)
Prerequisite: Phase 3 (BA-014 user accounts) must be complete for launch

## Format
Each BA follows the exampleBA.md template:
1. Overview → 2. Business Context → 3. Functional Requirements (Gherkin) → 4. Business Rules →
5. State Machines (Mermaid) → 6. Data Requirements (full schema) → 7. NFRs → 8. API Mapping →
9. UI/UX References → 10. Open Questions

## NFR ID Ranges

### Phase 1 (NFR-001→052)
- BA-001: NFR-001→007 | BA-002: NFR-011→015 | BA-003: NFR-016→022
- BA-004: NFR-026→035 | BA-005: NFR-036→041 | BA-006: NFR-046→052

### Phase 2 (NFR-053→099, contiguous)
- BA-007: NFR-053→058 | BA-008: NFR-059→066 | BA-009: NFR-067→073
- BA-010: NFR-074→079 | BA-011: NFR-080→087 | BA-012: NFR-088→094
- BA-013: NFR-095→099

### Phase 3 (NFR-100→125, pre-allocated 10-slot ranges)
- BA-014: NFR-100→106 | BA-015: NFR-110→115 | BA-016: NFR-120→125

### Phase 4 (NFR-130→157, pre-allocated 10-slot ranges)
- BA-017: NFR-130→136 | BA-018: NFR-140→146 | BA-019: NFR-150→157

### Phase 5 (NFR-160→181)
- BA-020: NFR-160→170 (Smart Context Building for NL→SQL Accuracy)
- BA-021: NFR-175→181 (Claude OAuth Integration)

### Phase 6 (NFR-185→198, pre-allocated 10-slot ranges)
- BA-022: NFR-185→190 (Unified Ingestion Framework & Draft Nodes)
- BA-023: NFR-191→195 (Source Adapters & File Processing)
- BA-024: NFR-196→198 (Public Ingestion API & Cross-Source Intelligence)

## How to Use
- **Agent teams**: Read relevant BA doc before implementing features — acceptance criteria define "done"
- **Code reviewers**: Verify implementation against FR acceptance criteria
- **Test workers**: Derive test cases from Gherkin acceptance criteria
- **Serena memories**: Operational notes stay here; BA docs are the formal specification
