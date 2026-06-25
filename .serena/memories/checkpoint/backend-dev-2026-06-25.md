# Checkpoint: backend-dev — 2026-06-25

## What was done (all on branch task/implement_mcp; NOT pushed)
**Authorization unification — "act as the caller, KG enforces" (BA-014/015):**
- `f12fa8e` read-path `requireProjectAccess` honors project_members (graph/query/search/neighbors/traverse) for web-login users.
- `722057e` ProjectID middleware honors project_members (threads/messages/stats…); members may override+access their projects (lazy/memoized lookup; MCP/admin keys unaffected).
- `b63d710`(Go)+`44a89a9`(Py) chat hand B: agentic chat forwards caller's session key (`X-KG-API-Key`) → KG tool calls run as the user (scoped). Files: ai_stream.go, sse_stream.go(StreamRequest.UserAPIKey), api/agentic.py, api/streaming.py.
- `e9b5b85` seed: python-worker service key = unscoped admin (role=admin, project_ids={}) — KEPT (indexer/worker need cross-project; matches "system admin → all" model). Revert was REJECTED (would break indexing).
- `7e046d2` fix create-API-key: default developer_name to caller (admin couldn't create keys → 400).
- `4a…`(next) fix api-keys UI: read backend envelopes `{api_keys:[]}` (list) + flatten `{...api_key,key:plaintext_key}` (create); dialog showed undefined + empty list.
- `0b3b323` **kg-bridge multi-tenant passthrough** (`KG_MCP_AUTH_PASSTHROUGH=true`): each request's Bearer = caller's own KG key, forwarded per-request; no static KG_MCP_TOKEN/KG_API_KEY needed. Files: middleware_auth.go(passthroughBearer), middleware.go(ctxKeyConsumerKey), config_load.go, serve.go(newSessionServerFactory), files_proxy.go(keyFor). TDD + real HTTP→SDK→KG integration test pass.

## Current state (working/live)
- kg-server host port = **8082** (8080 stale/occupied). Internal docker = kg-server:8080.
- kg-bridge rebuilt (`bin/kg-bridge`), OLD bridge killed; **NEW bridge PID 93474** running PASSTHROUGH, bind `0.0.0.0:8765`, KG_SERVER_URL=localhost:8082, log `/tmp/kg-bridge.log`. Verified live: initialize 200 + kg_list_projects returns real data with a consumer KG key.
- Docker rebuilt: kg-server, indexer (Py hand B), dashboard (api-keys fix).
- **DB PURGE done**: deleted 39 projects + 5955 nodes/1260 edges/etc in one txn; **only C4K (a0000000-…-0001) kept** (664 nodes/426 edges/1 ds intact, 0 orphans). Backup: `ennam.kg.workspace/db-backup-before-project-purge-20260625-134359.sql` (18M). python-worker default_project_id repointed C4K.

## Next steps
- Push branch / open PR when ready (Go + Python + Next all uncommitted-pushed).
- For external MCP consumers: issue SCOPED KG_API_KEY per consumer (dashboard) → put in their .mcp.json Bearer; bridge passthrough enforces via project_members. Bind bridge to tailnet IP 100.113.149.106 for remote.
- Optional: launchd service so bridge persists across reboot; delete DB backup after user verifies.

## Blockers/Risks
- All commits LOCAL only (not pushed). Bridge runs via nohup (not persistent across reboot).
- Pre-existing gofmt-dirty files (main.go import order from supabase commit, etc.) — untouched, not ours.
- See `mem:ba015-resolution` style notes; related: kg_remember consumer-key default_project_id requirement still applies.
