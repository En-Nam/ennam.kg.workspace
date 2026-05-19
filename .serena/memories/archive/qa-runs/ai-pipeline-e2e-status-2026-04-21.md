# AI Pipeline E2E Status — 2026-04-21

## BREAKTHROUGH: Full pipeline runs end-to-end

### What Works
1. Health check → healthy:true (Anthropic API key works) ✅
2. AI request → "Hi! How are you" response ✅
3. Budget tracking → spend logged in microdollars ✅
4. SSE Stream → progress events (parsing_intent, generating_sql) ✅
5. Go API → Python indexer HTTP → AI call chain works ✅

### What Fails
1. Intent parsing → AI returns empty JSON (Python worker can't call Go API for schema context)
2. Root cause: Python worker service key (agent role) gets 500 on /projects (needs project_ids)

### Infrastructure Fixes Needed
1. `KG_PYTHON_URL=http://indexer:8081` — ADDED to docker-compose.yml ✅
2. Python worker service key needs project access — seed should grant project_ids or use admin role
3. OR Python worker should call Go API differently (internal endpoint without project scoping)

### Cost So Far
- 1 health check: ~$0.003
- 1 AI request (5 tokens): ~$0.003
- 1 stream attempt (parsing only): ~$0.01
- Total: ~$0.02 of $5 budget used
