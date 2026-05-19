# Development Plan — Ennam KG Platform

> **Full deployment specs**: See `ennam.kg.requirements/documents/phase1/BA-006-deployment-ops.md`
> **Per-subsystem specs**: See BA-001 through BA-006 (Phase 1), BA-007 through BA-013 (Phase 2)

## Current Status (2026-04-08)

| Platform | Phase 1 | Phase 2 | Key Metric |
|----------|---------|---------|------------|
| Go API | ~99% complete | Wave 1+3+4 DONE, Wave 2 not started | 55+ endpoints, 24 migrations |
| Python | All sprints done | CODE COMPLETE + ALL BUGS FIXED | 53 Phase 2 tests, indexer working E2E |
| NextJS | All sprints done | NOT STARTED (waiting designs) | 14 routes, build passes |
| Requirements | Complete | Complete (7 BA docs) | 87 FRs, 455+ ACs, 47 NFRs |
| Requirements | — | Phase 3: Complete (3 BA docs) | 17 FRs, ~100 ACs, 19 NFRs |
| UI Design | N/A | Design system DONE, 6 screens pending | 38 components |

## Phase 2 — Knowledge Graph AI Pipeline

### Dependency Waves & Status

```text
Wave 1: BA-007 Data Source    +  BA-009 AI Provider
         [Go: DONE]              [Go: DONE]
         [Py: DONE + ALIGNED]    [Py: DONE + ALIGNED]
         [Docker: RUNNING]       [Need: register provider API key]
                ↓                        ↓
Wave 2: BA-008 KG Generation  +  BA-012 Admin Sync
         [Go: NOT STARTED]       [Go: NOT STARTED]
         [Py: DONE — kg_generator]  [Py: N/A]
                ↓                        ↓
Wave 3: BA-010 Visualization  +  BA-011 AI Query
         [Next: NOT STARTED]      [Go: DONE]
         [Design: pending]        [Py: DONE — nl_query]
                                  [Next: NOT STARTED]
                                         ↓
Wave 4: BA-013 Benchmark Suite
         [Go: DONE]
         [Py: DONE — benchmark]
```

### What's Working Now (E2E tested)

- **Indexer**: auto-scans Python code → 173 architecture nodes, 85 edges (parent-child)
- **Search**: full-text search on node titles
- **Traversal**: graph neighbors query
- **AI queries**: submit + retrieve (pending execution — needs AI provider)
- **Benchmarks**: questions listing + result submission
- **Data sources**: registration, connection test, schema extraction

### What's Left

1. **Register AI provider** — run `scripts/register-ai-provider.sh <API_KEY>` to enable AI features
2. **Wave 2 Go code** — BA-008 KG Generation + BA-012 Admin Sync
3. **NextJS Phase 2** — waiting on 6 screen designs
4. **22 Phase 1 test fixes** — old tests use wrong field names (`type` vs `node_type`)

### Frontend blocks

- 6 screen designs (DES-007-phase2) not started
- Design system library is ready (38 components)

## Phase 3 — Projects, Users & Platform Administration

### BA Documents (complete, 2026-04-13)
| BA | Title | FRs | NFRs | Endpoints | Migration |
|----|-------|-----|------|-----------|-----------|
| BA-014 | User Accounts & Auth | 6 | NFR-100→106 | 12 Go + 4 BFF | 032 |
| BA-015 | Project Management & Access | 6 | NFR-110→115 | 11 | 033 |
| BA-016 | Platform Administration | 5 | NFR-120→125 | 12 | 034, 035 |

### Development Order (sequential — NOT parallel)
```
Step 1: BA-014 → users table, auth endpoints, login, bcrypt, middleware
Step 2: BA-015 → project_members, CRUD, roles, middleware wire (depends on BA-014)
Step 3: BA-016 → API keys REST, activity feed, settings, feature flags (depends on both)
```

### Key Design Decisions
- `project_members` table = authoritative source for access control
- `api_keys.project_ids` = derived/cache for backward compat with MCP agents
- Existing API keys → auto-create "system" users (migration 032)
- Session: 15-day hard timeout, iron-session encrypted cookie
- Account lockout: configurable via `auth.max_login_attempts` setting (default 5)
- Password: bcrypt cost 12, min 8 chars + uppercase + number + special char
- Python workers: NO CHANGES needed for Phase 3

### Service Scope
| Service | BA-014 | BA-015 | BA-016 |
|---------|--------|--------|--------|
| Go API | Auth, users, middleware | Projects, members, middleware | Keys, feed, settings |
| NextJS | Login, change-pwd, BFF | Project UI, member mgmt | Admin pages |
| Python | — | — | — |

## Phase 4 — AI Query UI/UX Enhancement

### BA Documents (complete, 2026-04-14)
Seed: `seed_fb4151930647` (interview `interview_20260414_050641`, ambiguity 0.168)

| BA | Title | FRs | NFRs | Key Entities |
|----|-------|-----|------|--------------|
| BA-017 | Conversational AI Interface | 6 | NFR-130→136 | `conversation_threads`, `thread_messages` |
| BA-018 | Rich Response Rendering | 6 | NFR-140→146 | Extends `thread_messages` (+response_blocks, +aggregation_metadata) |
| BA-019 | AI Tools, Actions & Insights | 7 | NFR-150→157 | `query_favorites`, extends `thread_messages` (+insights, +suggested_actions) |

### Development Order
```
Step 1: BA-017 (foundation — threads, SSE streaming, messages)
Step 2: BA-018 + BA-019 (parallel — both depend on BA-017)
```
Prerequisite: Phase 3 (BA-014 user accounts) must be complete for launch

### Key Design Decisions
- SSE streaming with 9 event types (4 base + 4 format + 1 suggested_actions)
- Recharts for interactive charts (hover, zoom, legend toggle — visual-only, no re-query)
- Smart aggregation: AI auto-GROUP BY for >500 rows
- 9-tool fixed menu + 3 AI-suggested quick-action buttons + custom text input
- 80% insight accuracy benchmark target (always-on, confidence-labeled)
- Model configurable per pipeline step via BA-009/BA-016 settings
- Thread context window: last 10 messages, max 8000 tokens
- BA-011 `query_favorites` renamed to `ai_query_favorites` in Phase 4 migration
- No Share/collaboration features in Phase 4 scope

### Service Scope
| Service | BA-017 | BA-018 | BA-019 |
|---------|--------|--------|--------|
| Go API | Thread CRUD, SSE streaming | Format metadata | Favorites, compare, insights, PDF |
| NextJS | Thread sidebar, streaming renderer | Recharts, markdown, code blocks | Tool menu, insight cards, favorites |
| Python | Thread context in prompts | Format detection, aggregation SQL | Insight generation, action suggestions |

## Phase 1 Remaining Gaps

- Dart parser (needs tree-sitter-dart on PyPI)
- E2E integration tests (Go + Python + NextJS together)
- Playwright E2E tests for NextJS
- Real deployment configs (ECS, staging/production)
- SQS publisher implementation
- Users/API keys management in dashboard (→ NOW COVERED BY Phase 3 BA-014/BA-016)
