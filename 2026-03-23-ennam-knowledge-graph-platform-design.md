# Ennam Knowledge Graph Platform — Design Specification

**Date**: 2026-03-23
**Status**: Draft — Approved for development
**Owner**: Project Owner (Ennam Engineering)
**Scope**: Standalone internal platform for Ennam engineering teams

---

## 1. Problem Statement

### 7 Pain Points Identified

| # | Problem | Impact |
|---|---------|--------|
| 1 | **Context loss** across sessions | Agents re-read many files on new sessions, still miss big picture |
| 2 | **Knowledge silos** between agents | Discoveries buried in per-agent files, don't propagate to other agents |
| 3 | **No query interface** | Manual grep across markdown files — slow and imprecise |
| 4 | **No knowledge evolution tracking** | Can't see how concepts change over time across sprints |
| 5 | **Flat markdown is inefficient** | No database, data passed manually between agents |
| 6 | **No rules enforcement** | Agents don't create memory files at the right time or place — soft rules in prompts are ignored under cognitive load |
| 7 | **Memory grows unbounded** | No archival or garbage collection policy |

### Root Cause

The current memory protocol (`.serena/memories/ouroboros/`) uses flat markdown files with soft rules embedded in agent prompts. This works for 1-2 sessions but breaks down when 9 agents run in parallel across multiple sessions and projects. There is no structured storage, no schema validation, no cross-project querying, and no enforcement mechanism.

---

## 2. Vision

A **centralized Knowledge Graph platform** hosted on AWS that serves as the single source of truth for all Ennam engineering projects. It combines:

1. **Project Knowledge** (human-driven) — decisions, concepts, requirements, tasks, architecture, discoveries
2. **Code Knowledge** (auto-extracted) — functions, classes, modules, dependencies, API endpoints with descriptions and relationships

All accessible via MCP protocol for Claude Code agents and via web dashboard for human developers.

---

## 3. Architecture Overview

### 3.1 System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        AWS Infrastructure                        │
│                                                                  │
│  ┌──────────────┐   ┌──────────────────┐   ┌─────────────────┐  │
│  │  Go API       │   │  Python Workers   │   │  NextJS Web     │  │
│  │  Server       │   │                   │   │  Dashboard      │  │
│  │              │   │  • Code Indexer    │   │                 │  │
│  │  • REST API  │   │  • AST Parser     │   │  • Graph Viz    │  │
│  │  • MCP Bridge│   │  • AI Summarizer  │   │  • Metrics      │  │
│  │  • Auth      │   │  • Diff Analyzer  │   │  • User Mgmt    │  │
│  │  • Graph     │   │                   │   │  • Project Mgmt │  │
│  │    Engine    │   │                   │   │                 │  │
│  └──────┬───────┘   └────────┬──────────┘   └────────┬────────┘  │
│         │                    │                       │           │
│         └────────────┬───────┘───────────────────────┘           │
│                      │                                           │
│              ┌───────▼────────┐                                  │
│              │  PostgreSQL     │                                  │
│              │  + Apache AGE   │                                  │
│              │  (Graph ext.)   │                                  │
│              └────────────────┘                                  │
└─────────────────────────────────────────────────────────────────┘

         ▲ MCP Protocol                    ▲ HTTPS
         │                                 │
┌────────┴─────────┐              ┌────────┴──────────┐
│  Claude Code      │              │  Web Browser       │
│  (Agent Team)     │              │  (Dev Dashboard)   │
│  via MCP tools    │              │                    │
└──────────────────┘              └───────────────────┘
```

### 3.2 Tech Stack Decision

| Component | Technology | Rationale |
|-----------|------------|-----------|
| **Core API Server** | Go | High performance for graph queries, concurrent indexing, strong typing |
| **Code Analysis Workers** | Python | Best ecosystem for AST parsing (tree-sitter), code analysis, AI summarization |
| **Web Dashboard** | NextJS (TypeScript) | Interactive graph visualization, SSR for metrics, React ecosystem |
| **Database** | PostgreSQL + Apache AGE | Relational + native graph queries, FTS via pg_trgm, JSON columns for flexible schema, battle-tested on AWS |
| **Message Queue** | Redis / SQS | Go API → Python workers async communication for indexing jobs |
| **Hosting** | AWS | Company infrastructure standard |

### 3.3 Why Hybrid Stack

- **Go** for the hot path: API requests, graph traversals, MCP bridge — needs to be fast and concurrent
- **Python** for the smart path: code parsing (tree-sitter supports 40+ languages), AST analysis, AI-powered function summarization — Python has the best libraries
- **NextJS** for the human path: dashboard, visualization, project management — best DX for interactive web apps

---

## 4. Knowledge Model (Graph Schema)

### 4.1 Node Types — Project Knowledge (Human-driven)

| Node Type | Key Fields | Created By | Example |
|-----------|------------|------------|---------|
| **Project** | name, description, repo_url, stack, status | Admin/PO | "SalonBookly POS App" |
| **Decision** | title, context, rationale, alternatives[], impact, status | project-owner, BA, team-lead | "Use integer cents for all prices" |
| **Concept** | name, definition, domain, aliases[] | BA, project-owner | "Authentication", "Pricing Model" |
| **Requirement** | req_id, title, description, acceptance_criteria[], priority | BA | REQ-001, User Story |
| **Task** | task_id, title, status, assignee, blockers[], branch | team-lead, workers | TASK-042 |
| **Architecture** | type (api_contract/data_model/pattern), content, version | team-lead, backend-dev | API contract for /api/auth/login |
| **AgentDiscovery** | description, category, severity, resolved | Any worker | "Edge case: empty titles pass validation" |
| **DesignArtifact** | design_id, screens[], pen_file_path, node_id_mapping | ui-designer | DES-001, screen → node ID |
| **Session** | agent, started_at, ended_at, summary, phase | Any agent | "backend-dev session 2026-03-23" |

### 4.2 Node Types — Code Knowledge (Auto-extracted)

| Node Type | Key Fields | Source | Example |
|-----------|------------|--------|---------|
| **Module** | path, language, description, loc | Auto-scan | `src/services/auth/` |
| **Function** | name, file_path, line_start, line_end, signature, description, complexity | AST + AI summary | `validateToken()` — "Validates JWT, returns user claims" |
| **Class** | name, file_path, methods[], properties[], description | AST + AI summary | `ProductCard` — "Displays product with price/rating" |
| **Component** | name, file_path, props[], description, framework | AST + AI summary | `<StarRating>` — React component |
| **APIEndpoint** | method, path, handler_function, request_schema, response_schema | AST + route analysis | `POST /api/auth/login` |
| **DataModel** | name, fields[], relations[], source_file | Schema parser | Prisma model `User` |

### 4.3 Edge Types (Relationships)

```
# Project Knowledge edges
Decision    --impacts-->        Function | Module | Component
Decision    --relates_to-->     Concept
Concept     --implemented_by--> Module | Class | Component
Requirement --fulfilled_by-->   Task
Task        --modifies-->       Function | Class | Module
Task        --blocked_by-->     Task
Task        --assigned_to-->    Agent (via Session)
AgentDiscovery --about-->       Function | Class | Module | Concept

# Code Knowledge edges
Function    --calls-->          Function
Function    --belongs_to-->     Class | Module
Class       --inherits-->       Class
Class       --belongs_to-->     Module
Component   --uses-->           Component | Function | APIEndpoint
APIEndpoint --handled_by-->     Function
APIEndpoint --uses_model-->     DataModel
DataModel   --has_relation-->   DataModel
Module      --imports-->        Module

# Cross-layer edges (Project ↔ Code)
Decision    --impacts-->        Function | Module
Requirement --fulfilled_by-->   Function | Component | APIEndpoint
DesignArtifact --maps_to-->     Component
```

### 4.4 All Nodes Share

```
id:          UUID
project_id:  UUID (namespace isolation)
created_by:  user_id | agent_name
created_at:  timestamp
updated_at:  timestamp
version:     integer (auto-increment on update)
metadata:    JSONB (extensible fields)
is_archived: boolean (soft delete for GC)
```

---

## 5. MCP Interface (Agent-facing API)

### 5.1 Knowledge Write Tools

```
kg_store_decision(project_id, title, context, rationale, alternatives[], impact, related_concepts[])
kg_store_concept(project_id, name, definition, domain, aliases[])
kg_store_discovery(project_id, description, category, related_to[])
kg_store_task(project_id, task_id, title, status, assignee, blockers[])
kg_store_architecture(project_id, type, content, version, related_to[])
kg_store_session(project_id, agent, summary, phase, decisions_made[], discoveries[])
kg_link(source_id, target_id, relationship_type, metadata?)
```

### 5.2 Knowledge Read Tools

```
kg_query(project_id, query_string)
  — Natural language or structured query
  — Example: "all decisions related to authentication"
  — Returns: nodes + edges + context

kg_get_context(project_id, scope)
  — Returns: relevant knowledge for current agent/phase
  — Scope: "full" | "phase" | "task" | "domain"

kg_get_function_context(project_id, function_name_or_path)
  — Returns: function description, callers, callees, related decisions, recent changes
  — Solves: "agent doesn't need to re-read entire files"

kg_get_impact_analysis(project_id, node_id)
  — Returns: all nodes affected by a change to this node
  — Example: "what breaks if I change validateToken()?"

kg_search(project_id?, text, node_types[], limit)
  — Full-text search across all knowledge
  — Optional cross-project (omit project_id)

kg_get_graph(project_id, center_node_id, depth)
  — Returns: subgraph around a node for visualization
```

### 5.3 Code Indexing Tools

```
kg_index_project(project_id, repo_path)
  — Full scan: parse all source files, extract AST, generate AI summaries
  — Called once on project onboarding

kg_index_changed(project_id, changed_files[])
  — Incremental: re-index only changed files
  — Called by hooks after commits

kg_get_code_map(project_id, path?)
  — Returns: module tree with function/class summaries
  — Optional: filter to specific path
```

### 5.4 Validation Rules (Gate 1 — MCP Layer)

Every write tool enforces schema validation:

```yaml
kg_store_decision:
  required: [project_id, title, context, rationale]
  validation:
    - title: min 10 chars
    - context: min 20 chars (must explain WHY)
    - rationale: min 20 chars (must explain decision reasoning)
    - alternatives: array (can be empty, but field must exist)
  on_fail: return error with specific missing/invalid fields

kg_store_session:
  required: [project_id, agent, summary, phase]
  validation:
    - summary: min 30 chars
    - phase: enum [0-7]
    - decisions_made: array of existing decision IDs (validated against DB)
  on_fail: return error
```

---

## 6. Enforcement Architecture (Double Safety Net)

### 6.1 Gate 1 — MCP Layer (Schema Validation)

```
Agent calls kg_store_decision({title: "auth", context: "", ...})
                    ↓
         MCP Server validates:
         ✗ context is empty (min 20 chars)
         ✗ rationale is missing
                    ↓
         Returns ERROR:
         {
           "error": "validation_failed",
           "fields": {
             "context": "minimum 20 characters, got 0",
             "rationale": "required field missing"
           }
         }
                    ↓
         Agent MUST fix and retry
```

**What it catches**: Malformed data, missing fields, invalid references, type mismatches.

### 6.2 Gate 2 — Hook Layer (Completeness Checks)

Runs as Claude Code hooks (post-task, pre-commit, session-end):

```javascript
// Hook: check-knowledge-completeness.js
// Triggered: before task marked complete / before commit

async function checkCompleteness(context) {
  const { agent, task_id, project_id, changed_files } = context;

  const checks = [];

  // 1. Did agent store a session summary?
  checks.push(await kg_check("session", { agent, project_id, recent: true }));

  // 2. If code changed, were changes indexed?
  if (changed_files.length > 0) {
    checks.push(await kg_check("code_indexed", { files: changed_files }));
  }

  // 3. If architectural decision was made, is it recorded?
  // (Heuristic: new files created, schema changes, new endpoints)
  if (hasArchitecturalChanges(changed_files)) {
    checks.push(await kg_check("decision_exists", { task_id, recent: true }));
  }

  // 4. If task completed, is task status updated in KG?
  checks.push(await kg_check("task_status", { task_id, expected: "completed" }));

  const failures = checks.filter(c => !c.passed);
  if (failures.length > 0) {
    return {
      blocked: true,
      exit_code: 2,  // Same pattern as quality-gates
      message: `Knowledge completeness check failed:\n${failures.map(f => `  ✗ ${f.reason}`).join('\n')}`
    };
  }

  return { blocked: false };
}
```

**What it catches**: Agent "forgot" to record knowledge, code changes not indexed, decisions not logged.

### 6.3 Enforcement Flow

```
Agent works on task
        ↓
Makes code changes → Post-commit hook → kg_index_changed()    (auto)
        ↓
Makes decisions    → Must call kg_store_decision()             (MCP validates)
        ↓
Completes task     → Pre-completion hook                       (Gate 2)
        │
        ├─ ✗ Missing session summary    → BLOCKED, must write
        ├─ ✗ Code not indexed           → BLOCKED, auto-trigger index
        ├─ ✗ Decision not recorded      → BLOCKED, must record
        │
        └─ ✓ All checks passed          → Task complete ✓
```

---

## 7. Code Indexing Engine (Python Workers)

### 7.1 Indexing Strategy: Hybrid (Option C)

```
Project Onboarding (First time):
  1. Clone/access repo
  2. Full AST scan (tree-sitter) → extract all functions, classes, modules
  3. AI summarization (Claude API) → generate descriptions for each symbol
  4. Store all nodes + relationships in PostgreSQL
  5. Mark project as "indexed"

Incremental Updates (Ongoing):
  Trigger: post-commit hook OR session-end hook
  1. Detect changed files (git diff)
  2. Re-parse only changed files
  3. Diff against existing nodes → update/create/archive
  4. Re-run AI summary only for significantly changed functions
  5. Update relationship edges
```

### 7.2 Supported Languages (Phase 1)

| Language | Parser | Frameworks |
|----------|--------|------------|
| TypeScript/JavaScript | tree-sitter-typescript | NextJS, React, NestJS, Express |
| Dart | tree-sitter-dart | Flutter |
| Python | tree-sitter-python | FastAPI, Django |

### 7.3 AI Summarization

```python
# For each extracted function/class, generate a concise description
prompt = f"""
Given this {language} {symbol_type}:
```
{symbol_source_code}
```

Write a one-line description (max 100 chars) of what this {symbol_type} does.
Focus on WHAT it does, not HOW.
"""

# Uses Claude API (company MAX subscription)
# Batch processing: summarize up to 50 symbols per API call
# Cache: only re-summarize if function body changed (hash comparison)
```

---

## 8. Authentication & Authorization

### 8.1 Two Auth Modes

| Mode | For | Method | Example |
|------|-----|--------|---------|
| **API Key** | AI Agents (MCP) | Bearer token in header | `Authorization: Bearer ennam_kg_abc123` |
| **JWT** | Human devs (Dashboard) | OAuth2 / email-password | Company SSO integration |

### 8.2 Permission Model

```
Roles:
  - admin:     full access, user management, project creation
  - developer: read/write to assigned projects, view dashboard
  - agent:     read/write via MCP tools only, scoped to project_id
  - viewer:    read-only dashboard access

Scoping:
  - Every API key is scoped to specific project_id(s)
  - Agents can only write to their assigned project
  - Cross-project queries require explicit permission
  - Admin can grant cross-project read access
```

---

## 9. Web Dashboard (NextJS)

### 9.1 Key Views

| View | Purpose | Key Features |
|------|---------|--------------|
| **Project Overview** | High-level project status | Phase indicator, node counts, recent activity |
| **Knowledge Graph** | Interactive graph visualization | Zoom, filter by node type, click to inspect, search |
| **Decision Log** | All decisions across projects | Timeline view, filterable, cross-referenced |
| **Code Map** | Module/function tree with descriptions | Expandable tree, click to see relationships |
| **Agent Activity** | What each agent did per session | Timeline, decisions made, discoveries, code changes |
| **Metrics** | Platform health & usage | Nodes created/day, query latency, coverage, agent compliance |
| **Impact Analysis** | "What if I change X?" | Visual graph of affected nodes |
| **User Management** | Roles, permissions, API keys | Admin-only |

### 9.2 Graph Visualization

- Library: D3.js or Cytoscape.js (interactive, handles 10K+ nodes)
- Features: zoom, pan, filter by node type, highlight paths, search-to-center
- Color coding by node type (decisions = blue, functions = green, concepts = purple, etc.)

---

## 10. Phased Delivery Plan

### Phase 1 — Core Foundation (MVP)

**Goal**: Agents can store and query knowledge via MCP

| Component | Deliverables |
|-----------|-------------|
| **Go API Server** | REST API, MCP bridge (stdio + HTTP), project CRUD, knowledge CRUD |
| **PostgreSQL Schema** | All node types, edge types, versioning, project namespacing |
| **MCP Tools** | `kg_store_*`, `kg_query`, `kg_search`, `kg_get_function_context` |
| **Python Code Indexer** | Full scan + incremental, tree-sitter parsing, AI summarization |
| **Basic Auth** | API keys for agents, JWT for admin |
| **Integration** | Claude Code MCP config, ennam-dev-agent-team agent updates |

### Phase 2 — Intelligence

**Goal**: Automated enforcement and smart querying

| Component | Deliverables |
|-----------|-------------|
| **Graph Query Engine** | Apache AGE integration, path queries, impact analysis |
| **Auto-index Hooks** | Post-commit, session-end, phase-transition triggers |
| **Enforcement Gates** | MCP schema validation (Gate 1), hook completeness checks (Gate 2) |
| **Cross-project Search** | Query across all projects with permission checks |
| **Knowledge Evolution** | Version history per node, diff view, timeline |

### Phase 3 — Dashboard & Visualization

**Goal**: Human-readable view of all knowledge

| Component | Deliverables |
|-----------|-------------|
| **NextJS Dashboard** | All views from section 9.1 |
| **Graph Visualization** | Interactive graph with D3.js/Cytoscape.js |
| **Metrics & Analytics** | Agent compliance, knowledge coverage, query patterns |
| **User Management UI** | Roles, permissions, API key management |
| **SSO Integration** | Company OAuth2 provider |

---

## 11. Integration with ennam-dev-agent-team

### 11.1 Agent Updates Required

All 9 agents need updates to use KG MCP tools:

| Agent | New Responsibilities |
|-------|---------------------|
| **project-owner** | `kg_store_decision` for all decisions, `kg_get_context("full")` on session start |
| **business-analyst** | `kg_store_concept` for domain concepts, `kg_store_requirement` |
| **team-lead** | `kg_store_task` for all tasks, `kg_store_architecture` for contracts |
| **backend-dev** | `kg_get_function_context` before coding, `kg_store_discovery` for findings |
| **web-dev** | Same as backend-dev, scoped to frontend domain |
| **mobile-dev** | Same as backend-dev, scoped to mobile domain |
| **test-worker** | `kg_get_function_context` for test target analysis |
| **reviewer** | `kg_query` to check decisions are followed, `kg_get_impact_analysis` |
| **ui-designer** | `kg_store_design_artifact` with screen → node ID mapping |

### 11.2 MCP Registration

```json
// User-level: ~/.claude/settings.json
{
  "mcpServers": {
    "ennam-knowledge-graph": {
      "type": "http",
      "url": "https://kg.ennam.internal/mcp",
      "headers": {
        "Authorization": "Bearer ${ENNAM_KG_API_KEY}"
      }
    }
  }
}
```

### 11.3 Replaces Current Memory Protocol

| Current (markdown) | New (Knowledge Graph) |
|--------------------|----------------------|
| `.serena/memories/ouroboros/project/state.md` | `kg_get_context(project_id, "phase")` |
| `.serena/memories/ouroboros/project/decisions.md` | `kg_query(project_id, "recent decisions")` |
| `.serena/memories/ouroboros/tasks/registry.md` | `kg_search(project_id, node_types: ["Task"])` |
| `.serena/memories/ouroboros/architecture/*` | `kg_search(project_id, node_types: ["Architecture"])` |
| `.serena/memories/ouroboros/agents/*/handoff.md` | `kg_store_session` + `kg_get_context("agent")` |
| Manual grep across files | `kg_query` / `kg_search` / `kg_get_function_context` |

---

## 12. AWS Deployment Architecture (Preliminary)

```
┌─ AWS ──────────────────────────────────────────────┐
│                                                     │
│  ┌─ ECS/EKS ─────────────────────────────────┐     │
│  │  ┌─────────┐  ┌──────────┐  ┌───────────┐ │     │
│  │  │ Go API  │  │ Python   │  │ NextJS    │ │     │
│  │  │ (x2-3)  │  │ Workers  │  │ Dashboard │ │     │
│  │  │         │  │ (x1-2)   │  │ (x1)      │ │     │
│  │  └────┬────┘  └────┬─────┘  └─────┬─────┘ │     │
│  └───────┼─────────────┼──────────────┼───────┘     │
│          │             │              │              │
│  ┌───────▼─────────────▼──────────────▼───────┐     │
│  │  ALB (Application Load Balancer)           │     │
│  └────────────────────┬───────────────────────┘     │
│                       │                              │
│  ┌────────────────────▼───────────────────────┐     │
│  │  RDS PostgreSQL (+ Apache AGE extension)   │     │
│  │  Multi-AZ for reliability                  │     │
│  └────────────────────────────────────────────┘     │
│                                                     │
│  ┌─────────────┐  ┌──────────────┐                  │
│  │ ElastiCache │  │ SQS          │                  │
│  │ (Redis)     │  │ (Job Queue)  │                  │
│  └─────────────┘  └──────────────┘                  │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 13. Open Questions for Development Phase

1. **Apache AGE on RDS**: AWS RDS may not support Apache AGE extension natively — need to evaluate alternatives (self-managed PostgreSQL on EC2, or use recursive CTEs instead of graph extension)
2. **AI Summarization cost**: How many Claude API calls per full project scan? Budget implications for MAX subscription
3. **Real-time vs batch indexing**: Should code changes be indexed synchronously (blocking commit) or asynchronously (eventual consistency)?
4. **SSO provider**: Which OAuth2 provider does Ennam use? (Google Workspace, Azure AD, etc.)
5. **Data retention policy**: How long to keep archived nodes? Permanent or TTL-based?

---

## Appendix A: Discussion Timeline

### Session: 2026-03-23

**Participants**: User (Product Owner) + Claude (acting as Project Owner)

1. **Initial request**: User wants Knowledge Graph feature for ennam-dev-agent-team
2. **Pain points identified** (7 total):
   - Context loss, knowledge silos, no query interface, no evolution tracking
   - Flat markdown inefficient, no enforcement rules, unbounded memory growth
   - User added: markdown files have no DB, manual passing, agents don't follow rules
3. **Storage backend decision**: Evaluated 3 options (Custom MCP, Structured files, Serena extension)
   - User narrowed to A vs C
   - After analysis: Option C (Serena) eliminated due to per-project limitation
   - **Decision: Option A — Custom MCP Server**
4. **Indexing strategy**: Hybrid (Option C) — full scan on onboarding + hook-based incremental
   - User emphasized: "absolute accuracy", agents must know project info from start
5. **Enforcement**: Double safety net (Option C) — MCP schema validation + hook completeness checks
   - User: "absolute accuracy is priority"
6. **Multi-project architecture**: Discussion revealed user wants hosted AWS platform, not local SQLite
   - **Scope expanded**: From MCP plugin → full internal platform with dashboard
7. **Tech stack**: Hybrid (Option D) + PostgreSQL
   - Go (core API + graph engine) + Python (code analysis workers) + NextJS (dashboard)
   - PostgreSQL with Apache AGE for graph queries
8. **Phasing approved**: Phase 1 (Core) → Phase 2 (Intelligence) → Phase 3 (Dashboard)
9. **Decision**: Develop as standalone platform in separate repo
