# Phase C Final Results — 2026-04-21

## Summary: 18 PASS, 5 FAIL, 3 BLOCKED

## PASS (18)
1. Claude OAuth status → connected=true, active, scopes include user:inference ✅
2. Data source register with ssl_mode=disable → 201 pending ✅
3. Schema extraction (empty body) → 202 accepted, job created ✅
4. Schema metadata → 2 tables extracted from public schema ✅
5. KG generation → completed, nodes_created=2 ✅
6. KG nodes list → 2 nodes ✅
7. KG edges list → 0 edges (no FKs between extracted tables) ✅
8. Schema graph → total_tables:2 ✅
9. AI query submit → 202 pending ✅
10. AI query history → 2 queries stored ✅
11. Thread create → 201 ✅
12. Favorites create → 201 ✅
13. Favorites list → total_count:1 ✅
14. Provider register → 201 ✅
15. AI provider list → shows registered provider ✅
16. AI budget stats → 200 ✅
17. Connection test TCP step → passed ✅
18. Data source status tracking → pending → error (extraction ran but partial) ✅

## FAIL (5)
1. **Provider health check** → "unsupported protocol scheme" — base_url PATCH not persisted (returns empty)
2. **AI request (POST /ai/request)** → 503 all providers unavailable — provider base_url empty breaks HTTP client
3. **AI stream** → 400 "project_id could not be resolved" — admin key is unscoped
4. **Connection test SSL step** → fails even with ssl_mode=disable (test handler always tries SSL)
5. **Provider base_url update** → PATCH accepts but doesn't persist base_url

## BLOCKED (3)
1. End-to-end NL→SQL pipeline — requires working AI provider (base_url fix needed)
2. SSE streaming events — requires working AI + project-scoped key
3. Embedding generation — requires KG_EMBEDDING_API_KEY or working OAuth provider

## Key Finding
**KG Generation pipeline works end-to-end**: register → extract-schema → generate-kg → kg-nodes/edges → schema-graph. This is the explicit FK mapping path (BA-008 FR-001). Only the AI-dependent implicit detection (FR-002) is blocked.

## Remaining Fixes Needed
1. PATCH /ai-providers/{id} should persist base_url field
2. Connection test should respect ssl_mode=disable (skip SSL step)
3. AI stream should resolve project_id from user's project memberships (not just API key)
