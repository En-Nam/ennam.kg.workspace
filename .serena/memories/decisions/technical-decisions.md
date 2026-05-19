# Technical Decisions — Ennam KG Platform

> **Full specification**: See `ennam.kg.requirements/documents/phase1/BA-001-platform-foundation.md` §4 Business Rules
> and `BA-006-deployment-ops.md` §3 FR-003 for configuration management decisions.

## Approved Decisions (2026-03-23 Design Spec)
1. **Hybrid tech stack**: Go (API + MCP bridge) + Python (code indexer) + NextJS (dashboard)
2. **Database**: PostgreSQL + Apache AGE — but use **recursive CTEs first** (RDS doesn't support AGE natively)
3. **Hosting**: AWS (ECS/EKS + RDS + ElastiCache + SQS)
4. **Indexing**: Hybrid — full scan on project onboarding + hook-based incremental auto-index
5. **Enforcement**: Double safety net — MCP schema validation (Gate 1) + hook completeness checks (Gate 2)
6. **Auth**: API keys for agents, JWT for human devs, role-based (admin/developer/agent/viewer)
7. **Multi-project**: Single DB with project_id namespacing, cross-project queries with permission
8. **Repo structure**: Polyrepo (4 independent sub-repos under ennam.kg/)

## Development Phase Decisions (2026-03-25)
1. **Python package manager**: `uv` (10-100x faster than poetry, PEP 621 standard)
2. **Python worker model**: FastAPI + background worker (HTTP for manual triggers + ECS health, async worker for queue)
3. **Tree-sitter binding**: `py-tree-sitter` official C binding (control grammar versions, 3 languages only)
4. **AI summarization model**: Haiku 4.5 (~10x cheaper than Sonnet, sufficient for one-line descriptions)
5. **Graph visualization**: Cytoscape.js (purpose-built for graph viz, handles 10K+ nodes)
6. **NextJS → Go API**: Thin BFF proxy via NextJS API routes (hides API key, handles CORS)
7. **Auth flow**: API key server-side (Go API auth already complete, no need for NextAuth.js)
8. **Design approach**: Code-first with shadcn/ui, Pencil for later UX refinement
9. **Queue**: Redis (dev) / SQS (prod) — needs to be added to Go API

## Requirements Phase Decisions (2026-04-08)
1. **Documentation structure**: Single-document-per-subsystem BA format (6 BA docs, ~800-1200 lines each)
2. **Requirements repo**: Separate git repo `ennam.kg.requirements/` — docs-only, no source code
3. **BA template**: Follows exampleBA.md from AIO Core Rental project (Gherkin acceptance criteria, Mermaid state machines)
4. **Serena parallel**: .serena/memories/ kept for operational agent notes, BA docs are formal specs

## Open Questions
- Apache AGE on AWS RDS (deferred — using recursive CTEs)
- AI summarization cost per full project scan
- Real-time vs batch indexing (decided: async via queue)
- SSO provider selection (deferred to Phase 3)
- Data retention policy (TBD)
