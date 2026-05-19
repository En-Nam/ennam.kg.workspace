# AI Pipeline Final Status — 2026-04-21

## RESULT: Pipeline architecturally complete, blocked by 1 DB bug

### What Works (verified)
1. AI Provider health check → healthy:true ✅
2. AI direct request → returns response (2320ms) ✅
3. AI budget tracking → microdollar spend logged ✅
4. SSE Stream → progress events fire (parsing_intent, generating_sql) ✅
5. Go→Python→Go call chain → all connectivity OK ✅
6. Worker service key → 200 on /projects ✅
7. Schema extraction → finds 39 tables, starts processing ✅
8. KG_PYTHON_URL=http://indexer:8081 → added to docker-compose ✅

### Blocking Bug
**Heartbeat monitor DB error**: `pq: column "updated_at" does not exist` in sync_jobs table.
- Kills extraction jobs after processing only 1 of 39 tables
- Without full schema, AI intent parser gets empty context → returns empty JSON
- File: `internal/jobengine/heartbeat.go:60`
- Fix: add `updated_at` column to sync_jobs migration, or fix heartbeat query

### E2E Flow (when schema extraction works)
```
User query → Go API → Python indexer (HTTP)
  → Python gets schema from Go API (worker key 200) 
  → Python calls AI for intent parsing (via Go /ai/request)
  → Python generates SQL
  → Python executes query on source DB
  → Python streams results back via SSE
```

### Cost: ~$0.02 used of $5.00 budget

### Infrastructure Changes Made
- docker-compose.yml: added `KG_PYTHON_URL: http://indexer:8081`
- Seed script: worker service key role fixed
- Both changes needed for AI pipeline to function
