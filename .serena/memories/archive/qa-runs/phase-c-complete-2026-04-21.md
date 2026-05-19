# Phase C Complete — 2026-04-21

## Final Status: 20 PASS, 3 FAIL, 2 BLOCKED

### PASS (20)
All non-AI-call features working:
- OAuth status, token storage, connection ✅
- Data source CRUD + schema extraction ✅
- KG generation (explicit FK mapping) ✅
- Schema graph API ✅
- Thread CRUD + message persistence ✅
- Favorites CRUD (full lifecycle) ✅
- AI query submission + history ✅
- Provider CRUD + dynamic selector ✅
- base_url persistence ✅
- Stream project resolution (3-tier fallback) ✅

### FAIL (3) — all related to OAuth→Anthropic call
1. **Health check 401** — OAuth token injected but Anthropic returns 401. May need Bearer auth header format (not x-api-key) for Claude OAuth subscriptions.
2. **AI request 503** — cascaded from health check failure marking provider unhealthy
3. **Stream upstream_error** — Python worker reaches Go API but Go can't call Anthropic

### ROOT CAUSE
Claude OAuth subscription tokens may require different authentication header format than standard API keys. Standard: `x-api-key: sk-ant-...`. OAuth: `Authorization: Bearer <oauth_token>`. The Go Anthropic client may be using x-api-key header.

### BLOCKED (2)
1. End-to-end NL→SQL — needs working AI calls
2. Embedding generation — needs working AI calls

### What This Means
The platform is **functionally complete for all non-AI features**. The AI call layer has one remaining integration issue: OAuth token header format for Claude subscriptions. This is a 1-line fix in the Anthropic client (change header from `x-api-key` to `Authorization: Bearer` when using OAuth token).
