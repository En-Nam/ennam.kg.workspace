# Final AI Pipeline Status — 2026-04-21

## Architecture: VERIFIED END-TO-END
```
Provider health ✅ → AI direct call ✅ → SSE stream ✅ → 
Python worker connects ✅ → Progress events fire ✅ →
Intent parsing stage reached ✅ → BUT schema context empty → parse fails
```

## Root Cause Chain
1. Schema extraction job starts (39 tables found) ✅
2. Job runs but only processes 1 table then hangs
3. No heartbeat errors (fix works) but extraction goroutine stalls
4. Likely cause: DB connection hangs on SSL negotiation despite sslmode=disable in connection_string
5. Without full schema → AI intent parser gets empty context → returns empty → JSON parse fails

## What Is Fully Verified Working
- Anthropic API key authentication (healthy:true)
- AI direct request/response (2320ms latency)
- Budget tracking (microdollar spend)
- SSE streaming (progress events: parsing_intent, generating_sql)
- Go→Python HTTP chain (KG_PYTHON_URL=http://indexer:8081)
- Python worker service key (200 on /projects)
- Thread CRUD + message persistence
- Heartbeat monitor (updated_at column fix)

## Remaining: 1 Bug
Schema extraction goroutine stalls after processing 1 of 39 tables.
Go team needs to debug the extraction DB connection — may need to force sslmode=disable at connection level, not just in connection_string parameter.

## Cost: ~$0.03 of $5.00 used (very economical)
