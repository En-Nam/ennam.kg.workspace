# AI Pipeline Fixes — Final Round (2026-04-21)

## All blocking bugs fixed

### 1. `20f511f` — sync_jobs.updated_at for heartbeat monitor
- **Bug**: `pq: column "updated_at" does not exist` killed extraction jobs after 1 table
- **Fix**: Migration 042 adds `updated_at` column; `UpdateProgress` touches it on every update
- Heartbeat now correctly uses `updated_at` for stale detection (30-min window)

### 2. `9e4e055` — Agent keys can list projects
- **Bug**: Python worker key (role=agent, developer_name="python-worker") caused `ListForUser` to fail (non-UUID in UUID column)
- **Fix**: Handler detects non-UUID identities, falls back to listing by `project_ids` array
- Added `ProjectStore.ListByIDs()`

### 3. `f47568d` — OAuth injection scoped to claude_max only
- **Bug**: OAuth token overrode valid API keys on `anthropic_api` providers
- **Fix**: Only inject OAuth for `claude_max` provider type

### 4. `e5b83fe` — Error body capture + ErrCodeAuth
- **Bug**: API error bodies discarded, 401s showed only "HTTP 401"
- **Fix**: Capture up to 1KB of error body; map 401/403 → `ErrCodeAuth`

### 5. Provider key was in wrong workspace
- Old key `sk-ant-api03-...8nAAA` belonged to workspace without credits
- New key `sk-ant-api03-...sgAA` works (health check: healthy:true)

## Current Status
- AI provider health check: PASS
- Schema extraction: should now complete all 39 tables (heartbeat won't kill)
- Intent parsing: should work (worker can list projects + get schema context)
- Full NL→SQL pipeline: ready for E2E verification
