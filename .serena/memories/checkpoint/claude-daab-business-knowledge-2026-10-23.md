# Checkpoint: claude (DAAB business knowledge survey) — 2026-10-23

## What was done
- Confirmed DAAB memory (`agent_context`, kg_remember/kg_recall) is unused in product: 3 dev rows (2026-07-08), not read by the NL→SQL planner, LAAM does not call it.
- Surveyed the query engine: planner prompt is built in Go `ennam.kg.go/internal/service/query_intent.go` `ParseWithTier` (schemaContext from ContextBuilder/legacy + value hints; plan cache `nl_plan_cache` keyed by fingerprint of schemaContext+prompts). Python `nl_query/` is legacy. Table/column `user_description` is read but has no write API (6/10275 columns set).
- Found: benchmark has never run — `BenchmarkRunner.executeQuestion` creates `ai_queries` with `ProjectID: ""` (NOT NULL FK → Create fails), and nothing processes pending rows (`ProcessQuery` only from the HTTP handler). 0 benchmark questions/runs.
- Wrote spec `docs/superpowers/specs/2026-10-23-daab-business-knowledge-design.md` (workspace, commit b5a7665 on `task/DAAB/improve`): `business_knowledge` table, `project_ai_settings.knowledge_enabled` default off, approved items injected into schemaContext before the fingerprint, phases P0 (fix benchmark + seed ~30 real questions + baseline) → P3.

## Current state
- Owner DEFERRED it ("note vào backlog, làm sau"). Tracked in `mem:backlog/daab-business-knowledge-memory`. No code changed in ennam.kg.go.

## Next steps
- When resumed: ask the 4 open questions in spec §8, then start P0.

## Blockers / Risks
- `kg_search_sessions` "user" scope leaks between members under a shared org key (pre-existing, separate fix).
