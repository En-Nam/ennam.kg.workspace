# Architecture Assessment: Organization Layer Feasibility

**Date**: 2026-04-22
**Status**: ASSESSED — NOT PLANNED for development yet

## Current Multi-tenancy Model: Flat Project-Scoped

Platform is single-tenant with project-level isolation. No Organization concept.

### Resource Scope Distribution
- **Global (no isolation)**: ai_providers, oauth_tokens, system_settings, users, rate_limit_state, usage_metrics, ai_provider_health
- **Project-scoped (16 tables)**: knowledge_nodes, knowledge_edges, data_sources, sessions, audit_trail, ai_queries, conversation_threads, query_favorites, sync_jobs, source_schemas/tables/columns, kg_generation_jobs, table_embeddings, benchmark_runs
- **Array-scoped (app logic)**: api_keys.project_ids — no FK enforcement

### Strengths
- Project isolation consistent across 16+ tables with WHERE project_id filter
- User model flexible: global users + per-project roles via project_members
- Cross-project edge support designed (config flag + per-rule control)
- Middleware has project validation (ProjectID + DeveloperIdentity.HasProjectAccess)

### Weaknesses for Org Layer
- No boundary between "groups of projects" — admin sees everything
- Settings/Providers/OAuth global — can't configure per team
- Billing global (ai.monthly_budget_usd = single number)
- API key scoping by array (no FK enforcement)
- 30+ handlers self-parse project_id from query params instead of using middleware

## Two Strategies Evaluated

### Strategy A: "Org Validates Project" (RECOMMENDED)
- Middleware validates: user ∈ org → org contains project → pass
- Store layer UNCHANGED — still filters by project_id only
- Org is a "gate" at middleware level, not added to every table
- **Effort: ~80-120 hours (2-3 sprints)**
- Changes: 3-4 migrations, 2 middleware files, 5-8 handlers, 2-3 stores

### Strategy B: "Org Permeates Everything"
- Add org_id FK to all 26 tables, every query adds WHERE org_id
- DB-level enforcement, full SaaS isolation
- **Effort: ~200-300 hours (5-7 sprints)**
- Changes: 10+ migrations, 30+ handlers, 30 stores

## Required DB Changes (Strategy A)
1. CREATE organizations (id, name, slug, status, billing_plan, created_at)
2. CREATE organization_members (org_id, user_id, role, invited_by)
3. ALTER projects ADD organization_id FK (required, backfill existing → "Default Org")
4. CREATE org_settings (3-tier: global → org → project override)

## What Stays Global (both strategies)
- ai_providers — shared provider fleet
- oauth_tokens — platform-level (unless per-org billing needed)
- Rate limiting, health monitoring

## Decision
Strategy A is sufficient for current internal platform use case. If Ennam KG becomes SaaS product serving multiple independent customers, migrate to Strategy B incrementally.
