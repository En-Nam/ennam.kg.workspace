# Ennam Knowledge Graph Platform — Project Overview

## Purpose
A centralized Knowledge Graph platform hosted on AWS that serves as the single source of truth for all Ennam engineering projects. Combines:
1. **Project Knowledge** (human-driven) — decisions, concepts, requirements, tasks, architecture, discoveries
2. **Code Knowledge** (auto-extracted) — functions, classes, modules, dependencies, API endpoints with AI-generated descriptions
3. **Data Knowledge** (Phase 2) — database schemas, table relationships (FK + AI-detected), NL query interface

All accessible via MCP protocol for Claude Code agents and via web dashboard for human developers.

## Problem Solved
Replaces current `.serena/memories/ouroboros/` flat markdown files that break down with 9 agents running in parallel across multiple sessions. Provides structured storage, schema validation, cross-project querying, and enforcement mechanisms.

## Repository Structure
Monorepo root with 4 independent sub-projects (polyrepo style):
```
ennam.kg/                          # Root (this project)
├── ennam.kg.go/                   # Go backend — REST API + MCP bridge (~99% Phase 1)
├── ennam.kg.next/                 # NextJS web dashboard (14 routes, all Phase 1 sprints done)
├── ennam.kg.python/               # Python AI compute engine (Phase 1 + Phase 2 CODE COMPLETE)
├── ennam.kg.requirements/         # Formal BA documentation (24 BA documents)
│   ├── documents/                 # Phase 1: BA-001 through BA-006
│   ├── documents/phase2/          # Phase 2: BA-007 through BA-013
│   ├── documents/phase3/          # Phase 3: BA-014 through BA-016
│   └── designs/DES-007-phase2/    # Phase 2 UI designs (design system done, 6 screens pending)
├── docs/superpowers/plans/        # Implementation plans
└── CLAUDE.md                      # Ouroboros framework
```

## Tech Stack
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Core API Server | Go 1.23 | REST API, MCP bridge, auth, graph engine |
| AI Compute Workers | Python 3.12+ (FastAPI, tree-sitter, httpx) | Code indexing, KG generation, NL→SQL, benchmark |
| Web Dashboard | NextJS 15 (TypeScript, Tailwind, shadcn/ui, Cytoscape.js) | Graph viz, AI query UI, admin portal |
| Database | PostgreSQL 16 + Apache AGE (graph ext.) | Relational + graph queries, FTS via pg_trgm |
| Queue | Redis (dev) / SQS (prod) | Go API → Python workers async jobs |
| AI Provider | Claude Max ($200/mo primary) + pay-per-token fallback | Via Go API abstraction layer (BA-009) |
| Hosting | AWS (ECS/EKS, RDS, ElastiCache, SQS) | Production infrastructure |

## Status (updated 2026-04-08)

### Phase 1 — Platform Foundation
- **Go backend**: ~99% complete (25 MCP tools, 40+ REST endpoints, 14 DB migrations)
- **NextJS**: All sprints done (N1-N4), 14 routes, build passes
- **Python**: All sprints done (P1-P4), 89 Phase 1 tests
- **Requirements**: 6 BA documents (4,726 lines, 208 acceptance criteria)

### Phase 2 — Knowledge Graph AI Pipeline
- **Requirements**: 7 BA documents complete (BA-007→BA-013, 42 FRs, 47 NFRs, ~245 ACs)
- **UI Design**: Design system library DONE (38 components), 6 screen designs pending
- **Python**: CODE COMPLETE + ALL BUGS FIXED (53 Phase 2 tests, indexer E2E: 173 nodes, 85 edges)
- **Go backend**: Wave 1+3+4 DONE (55+ endpoints, 24 migrations). Wave 2 not started.
- **NextJS**: NOT STARTED — waiting on screen designs + Go API
- **Docker**: Dev stack running (postgres:5433, redis:6380, kg-server:8080, indexer:8081, worker)
- **Only remaining**: register AI provider with real API key (`scripts/register-ai-provider.sh`)

### Phase 3 — Projects, Users & Platform Administration
- **Requirements**: 3 BA documents complete (BA-014→BA-016, 17 FRs, 19 NFRs, ~100 ACs)
- **Go backend**: NOT STARTED
- **NextJS**: NOT STARTED
- **Python**: No changes needed
- **Scope**: User accounts (bcrypt auth, login/session, lockout), project CRUD + membership + roles, API key REST, activity feed, system settings + feature flags
- **Migrations**: 032-035 (users, project_members, system_settings, audit_trail extension)
- **Development order**: BA-014 → BA-015 → BA-016 (sequential, not parallel — auth dependency chain)

### Phase 4 — AI Query UI/UX Enhancement
- **Requirements**: 3 BA documents complete (BA-017→BA-019, 19 FRs, 22 NFRs, ~120 ACs)
- **Seed**: `seed_fb4151930647` (Cursor-style AI query experience)
- **Go backend**: NOT STARTED
- **NextJS**: NOT STARTED
- **Python**: NOT STARTED (insight generation, action suggestions, format detection)
- **Scope**: Conversation threads, SSE streaming, Recharts charts, markdown/code blocks, 9-tool menu, AI insights with confidence labels, favorites, smart aggregation
- **Prerequisites**: Phase 3 (user accounts) must be complete for launch
- **Development order**: BA-017 → BA-018 + BA-019 (parallel)

## Formal Documentation
All formal BA requirements live in `ennam.kg.requirements/documents/`. Serena memories are operational notes for agent sessions — the BA documents are the single source of truth.
- Phase 1: `documents/phase1/BA-001` → `BA-006` (45 FRs, NFR-001→052)
- Phase 2: `documents/phase2/BA-007` → `BA-013` (42 FRs, NFR-053→099)
- Phase 3: `documents/phase3/BA-014` → `BA-016` (17 FRs, NFR-100→125)
- Phase 4: `documents/phase4/BA-017` → `BA-019` (19 FRs, NFR-130→157)
- Phase 5: `documents/phase5/BA-020` + `BA-021` (13 FRs, NFR-160→181)
- Phase 6: `documents/phase6/BA-022` → `BA-024` (21 FRs, NFR-185→198)
