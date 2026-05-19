# P4: BA-012 Admin Sync Portal & Queue Management — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Priority: P4 (LOW)** — Operational tooling. Does not block user-facing features. Can be deferred if time-constrained.

**Goal:** Implement admin sync triggering with concurrency guards, background job engine with retry/heartbeat, WebSocket live progress, AI query queue with priority/dead-letter, sliding-window rate limiting, and usage dashboard.

**Architecture:** New `internal/jobengine/` package for background jobs (shared by BA-008 generation and BA-012 sync). New `internal/ws/` for WebSocket support. Rate limiter uses in-memory sliding window backed by DB state for persistence across restarts.

**Tech Stack:** Go std lib, `gorilla/websocket`, `sync`, PostgreSQL

**BA Reference:** `ennam.kg.requirements/documents/phase2/BA-012-admin-sync-portal.md`

**Prerequisites:** BA-007 (data sources), BA-008 (KG generation), BA-009 (AI providers)

---

## What Already Exists

- `sync_jobs` table (migration 019) ✅
- `SyncJobStore` with Create, GetByID, UpdateStatus, UpdateProgress, etc. ✅
- Data source extraction/sync endpoints in DataSourceHandler ✅

## What's Missing

- **Job engine**: No background runner, no retry, no heartbeat
- **WebSocket**: No live progress streaming
- **Query queue**: No FIFO queue for AI queries
- **Rate limiter**: No sliding window for Claude Max
- **Usage dashboard**: No aggregated metrics endpoint
- **Migration**: No query_queue, dead_letter_queue, rate_limit_state, usage_metrics tables

---

## File Structure

### New Files

```
db/migrations/
├── 000029_create_queue_tables.up.sql       # query_queue, dead_letter, rate_limit_state, usage_metrics
├── 000029_create_queue_tables.down.sql

internal/jobengine/
├── engine.go                               # Background job runner: FIFO, configurable concurrency
├── engine_test.go
├── heartbeat.go                            # Stale job detection
├── heartbeat_test.go

internal/ws/
├── handler.go                              # WebSocket upgrade + broadcast
├── handler_test.go

internal/service/
├── sync_trigger.go                         # Sync orchestration with concurrency guards
├── sync_trigger_test.go
├── query_queue.go                          # FIFO queue with priority + dead-letter
├── query_queue_test.go
├── rate_limiter.go                         # Sliding-window rate limiting
├── rate_limiter_test.go

internal/store/
├── queue.go                                # QueueStore: query queue, dead letter, rate limit state
├── queue_test.go
├── usage_metrics.go                        # UsageMetricsStore: hourly/daily/monthly aggregation
├── usage_metrics_test.go

internal/handler/
├── sync_portal.go                          # Sync trigger + WebSocket progress
├── sync_portal_test.go
├── admin_dashboard.go                      # Queue management + usage dashboard
├── admin_dashboard_test.go
```

### Modified Files

```
go.mod                                      # Add gorilla/websocket dependency
cmd/kg-server/main.go                      # Wire all new handlers
```

---

## Task 1: Add gorilla/websocket dependency

- [ ] **Step 1: Add dependency**

```bash
cd ennam.kg.go && go get github.com/gorilla/websocket@v1.5.3
```

- [ ] **Step 2: Commit**

```bash
git add go.mod go.sum
git commit -m "deps: add gorilla/websocket for admin sync portal (BA-012)"
```

---

## Task 2: Migration 029 — queue + metrics tables

- [ ] **Step 1: Write migration**

```sql
-- 000029_create_queue_tables.up.sql
CREATE TABLE query_queue (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ai_query_id UUID NOT NULL REFERENCES ai_queries(id),
    priority    VARCHAR(20) NOT NULL DEFAULT 'normal',
    status      VARCHAR(50) NOT NULL DEFAULT 'queued',
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dequeued_at TIMESTAMPTZ,
    retry_count INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT query_queue_priority_check CHECK (priority IN ('high', 'normal')),
    CONSTRAINT query_queue_status_check CHECK (status IN ('queued', 'processing', 'completed', 'dead_letter'))
);

CREATE INDEX idx_query_queue_status ON query_queue(status, priority DESC, enqueued_at);

CREATE TABLE dead_letter_queue (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ai_query_id     UUID NOT NULL REFERENCES ai_queries(id),
    error_messages  JSONB NOT NULL DEFAULT '[]',
    retry_timestamps JSONB NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE rate_limit_state (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider_id         UUID NOT NULL REFERENCES ai_providers(id),
    requests_this_window INTEGER NOT NULL DEFAULT 0,
    tokens_this_window   BIGINT NOT NULL DEFAULT 0,
    window_reset_at      TIMESTAMPTZ NOT NULL,

    CONSTRAINT rate_limit_provider_unique UNIQUE (provider_id)
);

CREATE TABLE usage_metrics (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    period      VARCHAR(20) NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    query_count INTEGER NOT NULL DEFAULT 0,
    input_tokens BIGINT NOT NULL DEFAULT 0,
    output_tokens BIGINT NOT NULL DEFAULT 0,
    latency_p50 INTEGER DEFAULT 0,
    latency_p95 INTEGER DEFAULT 0,
    latency_p99 INTEGER DEFAULT 0,
    error_rate  REAL DEFAULT 0,

    CONSTRAINT usage_metrics_period_check CHECK (period IN ('hourly', 'daily', 'monthly')),
    CONSTRAINT usage_metrics_unique UNIQUE (period, period_start)
);
```

- [ ] **Step 2: Commit**

```bash
git add db/migrations/000029_*
git commit -m "feat(db): add queue, dead letter, rate limit, usage metrics tables (BA-012)"
```

---

## Task 3: Background Job Engine

**Files:**
- Create: `internal/jobengine/engine.go`
- Create: `internal/jobengine/engine_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- Submits job, executes in background
- Concurrency limited (default 3)
- Retry with exponential backoff: 30s × 2^attempt (max 3 retries)
- Job timeout detection
- Graceful shutdown (drain in-progress jobs)

- [ ] **Step 2: Implement Engine**

```go
type JobFunc func(ctx context.Context) error

type Engine struct {
    concurrency int
    sem         chan struct{}
    wg          sync.WaitGroup
    logger      *slog.Logger
}

func NewEngine(concurrency int, logger *slog.Logger) *Engine
func (e *Engine) Submit(ctx context.Context, name string, fn JobFunc)
func (e *Engine) Shutdown(ctx context.Context) error
```

- [ ] **Step 3: Commit**

```bash
git add internal/jobengine/
git commit -m "feat(jobengine): add background job engine with concurrency control and retry (BA-012)"
```

---

## Task 4: Heartbeat Monitor

**Files:**
- Create: `internal/jobengine/heartbeat.go`
- Create: `internal/jobengine/heartbeat_test.go`

- [ ] **Step 1: Implement heartbeat**

```go
type HeartbeatMonitor struct {
    syncStore *store.SyncJobStore
    interval  time.Duration // 60s
    maxMissed int           // 3 missed = stale
    logger    *slog.Logger
}

// Start begins periodic heartbeat checks in a goroutine.
func (h *HeartbeatMonitor) Start(ctx context.Context)
```

Logic: every 60s, query running jobs where `updated_at < NOW() - interval * maxMissed`, mark as failed.

- [ ] **Step 2: Commit**

```bash
git add internal/jobengine/heartbeat.go internal/jobengine/heartbeat_test.go
git commit -m "feat(jobengine): add heartbeat monitor for stale job detection (BA-012)"
```

---

## Task 5: WebSocket Progress Handler

**Files:**
- Create: `internal/ws/handler.go`
- Create: `internal/ws/handler_test.go`

- [ ] **Step 1: Implement WebSocket handler**

```go
type ProgressHub struct {
    mu          sync.RWMutex
    subscribers map[string]map[*websocket.Conn]struct{} // jobID → connections
    logger      *slog.Logger
}

func NewProgressHub(logger *slog.Logger) *ProgressHub
func (h *ProgressHub) HandleWebSocket(w http.ResponseWriter, r *http.Request)  // WS upgrade
func (h *ProgressHub) Broadcast(jobID string, msg ProgressMessage)             // send to all subscribers

type ProgressMessage struct {
    JobID           string `json:"job_id"`
    Status          string `json:"status"`
    CurrentPhase    string `json:"current_phase"`
    ProgressPct     int    `json:"progress_pct"`
    TablesTotal     int    `json:"tables_total"`
    TablesProcessed int    `json:"tables_processed"`
    ErrorsCount     int    `json:"errors_count"`
}
```

Routes:
- `WS /ws/sync/{job_id}/progress` — per-job WebSocket
- `GET /stream/sync/progress` — SSE for all running jobs (fallback)

- [ ] **Step 2: Commit**

```bash
git add internal/ws/
git commit -m "feat(ws): add WebSocket progress hub for live sync monitoring (BA-012)"
```

---

## Task 6: Queue + Rate Limiter Services

**Files:**
- Create: `internal/store/queue.go`, `internal/store/usage_metrics.go`
- Create: `internal/service/query_queue.go`, `internal/service/rate_limiter.go`

- [ ] **Step 1: Implement QueueStore + UsageMetricsStore**

QueueStore methods: Enqueue, Dequeue (by priority), MoveToDeadLetter, Replay, ListQueue, ListDeadLetter
UsageMetricsStore methods: Increment, GetByPeriod, GetDashboard

- [ ] **Step 2: Implement QueryQueueService**

```go
type QueryQueueService struct {
    queueStore *store.QueueStore
    logger     *slog.Logger
}

func (s *QueryQueueService) Enqueue(ctx, queryID string, priority string) error
func (s *QueryQueueService) DequeueNext(ctx) (*models.QueueEntry, error)
func (s *QueryQueueService) MoveToDeadLetter(ctx, entryID string, err error) error
func (s *QueryQueueService) Replay(ctx, deadLetterID string) error
```

- [ ] **Step 3: Implement RateLimiterService**

```go
type RateLimiterService struct {
    store  *store.QueueStore
    logger *slog.Logger
    window time.Duration // 60s
}

func (s *RateLimiterService) Allow(ctx, providerID string, rpm, tpd int) (bool, error)
func (s *RateLimiterService) RecordUsage(ctx, providerID string, tokens int) error
func (s *RateLimiterService) GetFairShare(ctx, providerID string, activeUsers int) int
```

- [ ] **Step 4: Commit**

```bash
git add internal/store/queue.go internal/store/usage_metrics.go \
        internal/service/query_queue.go internal/service/rate_limiter.go
git commit -m "feat(service): add query queue with priority/dead-letter and rate limiter (BA-012)"
```

---

## Task 7: Sync Portal + Admin Dashboard Handlers

**Files:**
- Create: `internal/handler/sync_portal.go`
- Create: `internal/handler/admin_dashboard.go`

- [ ] **Step 1: Implement SyncPortalHandler**

```go
func (h *SyncPortalHandler) RegisterRoutes(mux *http.ServeMux) {
    mux.HandleFunc("POST /api/v1/sync/{data_source_id}/trigger", h.TriggerSync)
    mux.HandleFunc("GET /api/v1/sync/{job_id}/status", h.GetSyncStatus)
    mux.HandleFunc("/ws/sync/{job_id}/progress", h.progressHub.HandleWebSocket)
    mux.HandleFunc("GET /stream/sync/progress", h.SSEProgress)
}
```

- [ ] **Step 2: Implement AdminDashboardHandler**

```go
func (h *AdminDashboardHandler) RegisterRoutes(mux *http.ServeMux) {
    mux.HandleFunc("GET /api/v1/queue/query", h.ListQueue)
    mux.HandleFunc("GET /api/v1/queue/dead-letter", h.ListDeadLetter)
    mux.HandleFunc("POST /api/v1/queue/dead-letter/{id}/replay", h.ReplayDeadLetter)
    mux.HandleFunc("GET /api/v1/usage/dashboard", h.GetUsageDashboard)
}
```

- [ ] **Step 3: Wire into composition root, commit**

```bash
git add internal/handler/sync_portal.go internal/handler/admin_dashboard.go cmd/kg-server/main.go
git commit -m "feat(handler): add SyncPortal and AdminDashboard handlers (BA-012)"
```

---

## Task Summary

| # | Task | Type | Effort |
|---|------|------|--------|
| 1 | Add gorilla/websocket dep | Config | Tiny |
| 2 | Migration 029 | New tables | Small |
| 3 | Background Job Engine | New package | Large |
| 4 | Heartbeat Monitor | New service | Small |
| 5 | WebSocket Progress | New package | Medium |
| 6 | Queue + Rate Limiter | New stores + services | Large |
| 7 | Handlers (8 endpoints) | New handlers + wire | Medium |
| **Total** | **7 tasks** | **~18 files** | |
