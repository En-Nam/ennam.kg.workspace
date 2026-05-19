# Checkpoint: Go API Gaps Fixed — 2026-03-25

## What was done
All 3 Go API gaps have been closed:

### 1. Database Connection Wired ✓
- **File**: `cmd/kg-server/main.go`
- Added `connectDatabase()` helper using `database.ConnectDB()` + pool config
- `*sql.DB` now passed to `buildRouter()` → all handlers, stores, services
- Auto-migration in development (`serverCfg.Database.AutoMigrate`)
- `/readyz` now checks `db.PingContext()` for real health status

### 2. API Key Authenticator Integrated ✓
- **File**: `cmd/kg-server/main.go`
- Default: `store.NewAPIKeyStore(db)` — real hash-based authentication
- Dev fallback: `KG_AUTH_NOOP=true` env var → noop authenticator
- `noopAuthenticator` preserved for development without seeded API keys

### 3. Redis Queue Infrastructure Added ✓
- **New files**:
  - `internal/queue/publisher.go` — Publisher interface + IndexMessage types + noopPublisher
  - `internal/queue/redis.go` — Redis publisher using raw RESP protocol (no external dependency)
- **Modified files**:
  - `internal/config/server.go` — Added `QueueConfig`, `RedisQueueConfig`, `SQSQueueConfig` structs + env overrides
  - `config/environments/development.yaml` — Added queue config (redis, localhost:6379)
  - `docker-compose.yml` — Added Redis 7-alpine service with healthcheck

## Files Changed
```
cmd/kg-server/main.go                        # DB wiring, auth, imports
internal/config/server.go                     # QueueConfig struct + env overrides
internal/queue/publisher.go                   # NEW: Publisher interface + message types
internal/queue/redis.go                       # NEW: Redis RESP publisher
config/environments/development.yaml          # Queue config section
docker-compose.yml                            # Redis service
```

## New imports in main.go
- `database/sql`
- `github.com/ennam/ennam-kg/internal/database`
- `github.com/ennam/ennam-kg/internal/store`

## Status
Go backend now **~99% feature complete** for Phase 1. Remaining:
- AWS Secrets Manager integration (stubs only — needed for staging/production)
- SQS publisher implementation (for production queue)
- Wire queue publisher into kg-server main.go (publish on project creation)

## Next Steps
- Scaffold Python Service (`ennam.kg.python`) — Sprint P1
- Scaffold NextJS Dashboard (`ennam.kg.next`) — Sprint N1
