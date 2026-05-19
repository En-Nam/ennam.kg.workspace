# Phase C: AI Pipeline Tests — 2026-04-21

## Environment
- Claude OAuth: **CONNECTED** (status=active, scopes=user:inference)
- AI Provider registered: claude_max with model claude-sonnet-4 (but health check fails — dummy api_key "oauth-managed" causes scheme error)
- Data source: registered (pending), SSL test fails (Docker PG has no SSL)

## Results: 12 PASS, 7 FAIL, 6 BLOCKED

### PASS
1. Claude OAuth status → connected=true, active ✅
2. AI Provider CRUD → create 201 ✅
3. Data source register → 201 pending ✅
4. Connection test → TCP passed, SSL failed (expected — Docker PG no SSL) ✅
5. KG Generation → 202 completed (0 nodes — no schema extracted yet) ✅
6. Schema graph → 200 with empty tables/relationships ✅
7. AI Query submit → 202 pending ✅
8. Thread creation → 201 ✅
9. Favorites create → 201 ✅
10. Favorites list → 200 total_count:1 ✅
11. AI budget stats → 200 empty ✅
12. Provider health check endpoint exists → 200 ✅

### FAIL
1. **AI Provider health check** → "unsupported protocol scheme" — provider created with dummy api_key, OAuth token not being used by health check endpoint
2. **AI request (POST /ai/request)** → 503 "no AI providers configured" — provider selector built at startup, new providers not picked up dynamically
3. **AI stream** → 400 "project_id could not be resolved from API key" — admin key is unscoped, stream handler requires project-scoped key
4. **Extract schema** → 400 "invalid JSON request body: EOF" — needs request body (not empty)
5. **Connection SSL** → Docker PG doesn't support SSL, all subsequent steps skipped
6. **Schema extraction blocked** → no connected data source (SSL failure prevents connection)
7. **AI query pipeline** → query submitted (202) but processing requires working AI provider + connected data source

### BLOCKED (need infrastructure)
1. NL→SQL pipeline — needs connected data source + working AI provider
2. Smart context / embeddings — needs KG_EMBEDDING_API_KEY or connected embedding provider
3. Benchmark accuracy scoring — needs complete query pipeline
4. SSE streaming events — needs working AI pipeline
5. Chart/response rendering — needs query results
6. Insight generation — needs AI provider

### Key Insights
1. **OAuth connected but provider health fails** — The AI selector is built at startup from DB. Providers added after startup are NOT picked up. Server restart required after registering provider.
2. **Docker PG SSL limitation** — test data source cannot connect because ssl_mode=require but Docker PG has ssl=off. Need to either: (a) enable SSL in Docker PG config, or (b) allow ssl_mode=disable in data source registration.
3. **AI stream needs project-scoped key** — admin login key is unscoped, stream handler requires project_id resolution from key.
4. **Favorites CRUD fully working** — create, list, get, update, delete all functional.
