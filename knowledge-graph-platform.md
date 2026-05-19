---
name: knowledge-graph-platform
description: Design decisions for Ennam Knowledge Graph Platform — standalone AWS-hosted platform with Go+Python+NextJS, PostgreSQL+AGE, MCP bridge for Claude Code agents
type: project
---

## Ennam Knowledge Graph Platform

**Status**: Design spec approved (2026-03-23), pending repo setup
**Spec**: `docs/superpowers/specs/2026-03-23-ennam-knowledge-graph-platform-design.md`
**Scope**: Standalone platform (separate repo), NOT a plugin in ennam-dev-agent-team

### Key Decisions

1. **Hybrid tech stack**: Go (API server + MCP bridge) + Python (code indexer workers) + NextJS (dashboard)
2. **Database**: PostgreSQL + Apache AGE (graph extension)
3. **Hosting**: AWS (ECS/EKS + RDS + ElastiCache + SQS)
4. **Indexing**: Hybrid — full scan on project onboarding + hook-based incremental auto-index
5. **Enforcement**: Double safety net — MCP schema validation (Gate 1) + hook completeness checks (Gate 2)
6. **Auth**: API keys for agents, JWT for human devs, role-based (admin/developer/agent/viewer)
7. **Multi-project**: Single DB with project_id namespacing, cross-project queries with permission
8. **Replaces**: Current `.serena/memories/ouroboros/` markdown-based memory protocol

### Phasing

- **Phase 1 (Core)**: Go API + PostgreSQL schema + MCP tools + Python code indexer + basic auth
- **Phase 2 (Intelligence)**: Graph queries (AGE) + auto-index hooks + enforcement gates + cross-project search + knowledge evolution
- **Phase 3 (Dashboard)**: NextJS web dashboard + graph viz + metrics + user mgmt + SSO

### Two Knowledge Layers

1. **Project Knowledge** (human-driven): decisions, concepts, requirements, tasks, architecture, discoveries, design artifacts, sessions
2. **Code Knowledge** (auto-extracted): modules, functions, classes, components, API endpoints, data models — with AI-generated descriptions

### Integration with ennam-dev-agent-team

- All 9 agents will use KG MCP tools (`kg_store_*`, `kg_query`, `kg_get_function_context`, etc.)
- Registered at user-level `~/.claude/settings.json` — works across all projects
- Will replace current memory-protocol skill (markdown → KG API calls)

### Open Questions

- Apache AGE on AWS RDS compatibility (may need self-managed PostgreSQL)
- AI summarization cost per full project scan
- Real-time vs batch indexing for code changes
- SSO provider selection
- Data retention policy
