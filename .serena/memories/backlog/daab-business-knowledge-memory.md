# DAAB: turn memory into project-scoped "business knowledge" (deferred) — 2026-10-22

Context: `mem:decisions/memory-allocation-2026-10-22`. Personal memory moved to LAAM; DAAB keeps only knowledge that belongs to a business/project.

## Target
Definitions & conventions ("doanh thu = chưa gồm VAT"), corrections ("PH-004 là chi nhánh Thủ Đức"), business decisions. Curated by org admins in the DAAB dashboard; **consumed by DAAB's own NL query path** (`kg_query_datasource`) so answers improve for every client (LAAM, AAAA, dashboard).

## Start condition
Only once a consumer is built: today the query engine does NOT read `agent_context` (Python side only embeds it, `ennam.kg.python/.../worker.py:878`). Building storage without the reader repeats "built ≠ used".

## Design notes from the 2026-10-22 adversarial review (do not skip)
1. **Do not reuse `agent_context` as-is for curated knowledge.** Its retention sweep dedups/growth-caps rows with `mem_key IS NULL` per (project,user,scope) (`internal/store/agent_context.go:325-360`) and recall is half-life decayed (`internal/handler/agent_context.go:191-204`) — curated definitions would be archived or ranked down. Prefer existing KG node types (decision/concept) or pack `project_mapping` overrides.
2. **Writes from clients land as "proposed"**, approved by an org admin before the query engine trusts them. Any LAAM member clicking a confirm card must not be able to change org-wide knowledge directly.
3. **Attribution:** writes via a shared org key carry the key's user/DeveloperName (`agent_context.go:256`); record the real author (or keep proposals anonymous-but-reviewed).
4. Check whether the org key Ennam Admin provisions is read-only: `agent_context.go:247` rejects writes from viewer keys.

## Drop dev-era scopes `user` / `agent` (no code consumer: none in LAAM, am-ai-agents, ~/.claude/hooks)
- `validScopes` (`internal/handler/agent_context.go:93`), bridge enums (`internal/bridge/schema.go:1717,1730`), recall filter (`internal/store/agent_context.go:202-214`), migration for the CHECK in `000068_agent_context.up.sql:9`.
- Tests: `agent_context_userscope_test.go`, `recall_isolation_test.go`, `agent_context_isolation_integration_test.go`, `schema_test.go`.
- Clean the 3 dev rows in agent_context.
- AAAA docs planned a per-user `kg_recall` path — tell AAAA before dropping (`mem:comms/active/claude-to-orchestrator-memory-allocation`).

## ⚠️ Separate, existing issue found during review
`kg_search_sessions` has its own `user|monitoring` scope enum — **do not touch it with the change above**. But under a SHARED org key its "user" scope already lets every member of an org read each other's sessions (user_id comes from the key). Needs its own fix/threat-model before any multi-user client relies on it.


## 2026-10-23 — spec drafted; owner: DEFERRED ("note vào backlog, làm sau")
- Status: parked. Not approved yet; resume by asking the owner the 4 open questions in spec §8 (project admin may flip switch? keep `value_alias`? auto-suggest from clarifications? project-only scope?), then start at P0 (fix benchmark runner + seed ~30 real Pharmacy POS questions + baseline).
- Spec committed on workspace branch `task/DAAB/improve`.
- Spec: workspace `docs/superpowers/specs/2026-10-23-daab-business-knowledge-design.md` (dedicated `business_knowledge` table, `project_ai_settings.knowledge_enabled` default off, inject approved items into `ParseWithTier` schemaContext BEFORE the plan-cache fingerprint).
- Survey facts: NL→SQL planner is Go `internal/service/query_intent.go` (Python `nl_query/` is legacy). `user_description` on tables/columns is read but has no write API.
- **Benchmark never ran:** `BenchmarkRunner.executeQuestion` creates `ai_queries` with `ProjectID: ""` (NOT NULL FK → Create fails) and then only polls a pending row nothing processes (`ProcessQuery` is only called from the HTTP handler). 0 benchmark questions/runs in DB. Fix is phase P0 of the spec.