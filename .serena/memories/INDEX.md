# Serena Memory Index

Agents: read this file FIRST at session start.
See CLAUDE.md "Serena Memory Protocol" for read/write rules.

## Quick Reference

| Directory | Purpose | When to use |
|-----------|---------|-------------|
| `conventions/` | Code style, commands, task completion rules | Before writing code |
| `decisions/` | Active technical decisions, architecture | Before design decisions |
| `services/` | Current state per service (1 file each) | Session start |
| `backlog/` | Pending action items for agents | Check your domain |
| `comms/active/` | Open inter-agent questions | Check for messages to you |
| `comms/resolved/` | Closed threads | Reference only |
| `qa/` | QA strategy, playbooks, latest results | Before/after testing |
| `archive/` | Historical data (phases, old QA runs) | Only when investigating history |

## Latest QA Run
- `archive/qa-runs/smoke-test-e2e-2026-05-13.md` — Layer 2 Smoke Tests: **5 PASS, 1 SKIP** — Haiku model, schema truncation fix
- `archive/qa-runs/chat-e2e-verification-2026-05-11.md` — AI Chat E2E: PASS after 2 fixes (ENCRYPTION_KEY env + pymssql charset)

## Service State Files

| File | Service | Key Info |
|------|---------|----------|
| `services/go-api.md` | Go API (:8080) | Phase 1-4 complete, SSE streaming, credential vault |
| `services/nextjs-dashboard.md` | NextJS (:3500) | 15+ pages, 3D graph, chat, BFF proxy |
| `services/python-worker.md` | Python (:8081) | Stateless AI engine, streaming, NL query |

## Active Decisions (15 files)

| File | Topic |
|------|-------|
| `decisions/ecosystem-hermes-allocation.md` | ⭐ ENNAM ECOSYSTEM (AAAA/DAAB/LAAM): **DAAB OWNS** shared memory (`kg_remember`/`kg_recall`, RRF) + session search; AAAA/LAAM consume; gates = confirm internals + cross-platform RBAC isolation. CTO decision 2026-06-23 |
| `decisions/daab-hermes-keystone-verification.md` | 🔴 DAAB verdict on the above: retrieval engine EXISTS (384-dim node search/RRF/FTS confirmed), but **cross-platform RBAC isolation DOES-NOT-HOLD** (body-override + cross_project_ids + by-UUID IDOR) → consumers BLOCKED until gate test passes. 2026-06-23 |
| `decisions/technical-decisions.md` | Master decision log (tech stack, auth, hosting) |
| `decisions/overview.md` | Project roadmap — all 6 phases |
| `decisions/knowledge-model.md` | Graph schema design |
| `decisions/mcp-api-spec.md` | MCP tools + REST API contract |
| `decisions/python-worker-architecture-final.md` | Go=gateway, Python=AI engine |
| `decisions/go-backend-status.md` | Go API implementation baseline |
| `decisions/architecture-assessment-organization-layer.md` | Org layer feasibility (not planned) |
| `decisions/requirements-documentation.md` | BA document structure |
| `decisions/phase3-design-spec.md` | Phase 3 spec (awaiting implementation) |
| `decisions/phase5-smart-context-design.md` | Embedding + smart search architecture |
| `decisions/phase6-multi-source-ingestion.md` | Future phase spec (not started) |
| `decisions/agentic-engine-lessons.md` | Agentic engine pitfalls: schema truncation, Haiku prompt style, UUID fallback, rate limit |
| `decisions/workspace-meta-repo.md` | root is a shared git repo; sub-repos cloned via bootstrap manifest, not submodules |

## Backlog (15 items)

| File | Domain | Priority |
|------|--------|----------|
| `backlog/sse-block-ordering-bug.md` | Python+Go | P1 |
| `backlog/bug-kg-nodes-missing-ai-description.md` | Go | Medium |
| `backlog/fix-kg-generation-progress-visibility.md` | Go | Medium |
| `backlog/development-plan.md` | All | Roadmap |
| `backlog/phase5-ba021-work-plan.md` | NextJS | 7 tasks remaining |
| `backlog/fe-action-required-phase3-api.md` | NextJS | Phase 3 |
| `backlog/fe-action-required-phase4-api.md` | NextJS | Phase 4 |
| `backlog/fe-action-required-*.md` (7 more) | NextJS | Various |
| `backlog/be-change-request-datasource-sync-status.md` | NextJS | FE integration |

## Conventions (3 files)

- `conventions/code-style.md` — Go, Python, NextJS coding standards
- `conventions/task-completion.md` — Per-service completion checklist
- `conventions/suggested_commands.md` — Build/test/run commands per service
