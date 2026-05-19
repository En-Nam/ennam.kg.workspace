# Phase C — Go Backend Fixes Applied (2026-04-21)

## Context
QA Phase C reported 20 PASS, 3+2 FAIL related to AI/OAuth. Go backend team applied fixes across 3 commits.

## Commits Applied

### 1. `e5b83fe` — Capture API error bodies + ErrCodeAuth (latest)
- **Problem**: Anthropic/OpenAI error response bodies were discarded (`io.Copy(io.Discard, resp.Body)`), making 401 diagnosis impossible
- **Fix**: Read up to 1KB of error body, include in error message. Map HTTP 401/403 → `ErrCodeAuth` (new constant)
- **Files**: `internal/ai/anthropic.go`, `internal/ai/openai.go`, `internal/models/ai_provider.go`
- **Impact**: Health check and all AI calls now show Anthropic's actual error message (e.g., `"authentication_error: invalid x-api-key"`)

### 2. `30a1af7` — Python worker service key + OAuth health check injection
- **Problem**: Python worker's API key (`ennam_kg_dev_...`) wasn't in seed script; health checks didn't inject OAuth token
- **Fix**: Added stable service key (role=agent, not linked to user account). Added `OAuthAccessor` interface to `AIProviderHandler` for health check OAuth injection
- **Files**: `scripts/reset-and-seed.sql`, `internal/handler/ai_provider.go`, `cmd/kg-server/main.go`

### 3. `bd984bd` — base_url persistence + stream project resolution
- **Problem**: PATCH /ai-providers didn't persist base_url; stream endpoint couldn't resolve project_id for admin keys
- **Fix**: Added `base_url` to updateProviderRequest; 3-tier project resolution (body → identity → middleware)
- **Files**: `internal/handler/ai_provider.go`, `internal/handler/ai_stream.go`

## QA Note: OAuth Header Format Already Correct
QA diagnosed "OAuth token header format mismatch" as root cause. **Code analysis shows the header logic was already correct**:
```go
if p.oauthToken != "" {
    httpReq.Header.Set("Authorization", "Bearer "+p.oauthToken)  // OAuth
} else if p.apiKey != "" {
    httpReq.Header.Set("x-api-key", p.apiKey)  // Standard API key
}
```
The real issue was inability to see Anthropic's actual error response. With error body capture (commit e5b83fe), the next health check will reveal the actual root cause.

## Verification Needed
After rebuild + re-seed:
1. Health check on Claude provider — should now show detailed error or pass
2. AI request via selector — should work if OAuth token is valid
3. Stream endpoint — should resolve project_id correctly
4. Check Docker logs for Anthropic error body details

## Status
- All non-AI features: **PASS** (20/20)
- AI features: **pending re-verification** after container rebuild
- All Go code changes committed and pushed to main
