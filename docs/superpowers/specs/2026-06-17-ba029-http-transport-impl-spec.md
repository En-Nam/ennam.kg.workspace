# BA-029 Implementation Spec: Streamable HTTP + Auth Transport for Ennam KG MCP Bridge

**Document**: `docs/superpowers/specs/BA-029-http-transport-impl-spec.md`
**Status**: Final — approved for implementation
**Date**: 2026-06-17
**Prepared by**: Council synthesis (Tech Consultant + CTO cross-review)
**Target service**: `ennam.kg.go/internal/bridge/` — `serve.go`, new middleware, new migration

---

## 1. Executive Summary

### What Ships in v1

BA-029 v1 promotes the DAAB MCP bridge from stdio-only to supporting MCP Streamable HTTP transport for remote satellite clients (LAAM, AAA). v1 delivers a hardened, observable HTTP transport layer. It does **not** deliver per-satellite identity, DB-backed audit logging, or Redis-backed rate limiting — those ship together in v2 as a cohesive multi-tenant satellite drop.

**v1 scope:**

| Item | FR | Notes |
|------|----|----|
| Transport selection (`--http` flag, stdio default) | FR-001 | Two paths mutually exclusive at startup |
| Shared-token auth (constant-time compare) | FR-002 partial | Already uses `subtle.ConstantTimeCompare`; remaining gaps addressed (see §5) |
| Health/readiness endpoints | FR-003 | `/healthz`, `/readyz` |
| Per-request timeout (60s, startup-validated) | FR-004 | |
| Simple in-process rate limiter | FR-005 partial | `x/time/rate` token bucket, single-replica, documented as throwaway |
| Structured `slog` call log line (not DB) | FR-006 partial | Baseline observability; DB table is v2 |
| `mcp_auth_failures_total` Prometheus counter via `--metrics-addr` | OQ-011 | Closes OQ-011 |
| Startup guards: token presence, entropy floor, TLS binding assertion | Security | Non-negotiable |
| `Authorization` header stripped after auth middleware | Security | Structural fix for token-in-logs |
| Graceful shutdown drain (65s) | NFR | Longer than per-request timeout |
| CORS deny-all | Security | Unless browser clients are a use case |

**v1 does NOT include:**

- FR-002 API-key mode (per-satellite `DeveloperIdentity`, `api_keys` table lookup)
- FR-005 Redis-backed rate limiting (deferred until multi-replica)
- FR-006 `mcp_tool_call_log` DB table (deferred; delivery semantics must be defined first)
- FR-007 Idempotency reservation — **cut entirely**. No reserved columns in any schema.

### Key Decisions (Council-resolved)

| Decision | Resolution | Rationale |
|----------|-----------|-----------|
| Rate limiting in v1? | **Yes — simple in-process** | An uncapped authenticated HTTP endpoint is a worse risk than bounded throwaway debt. CTO objection (Redis later) is valid; this is explicitly documented as single-replica only. |
| OQ-010: partitioning vs purge | **Scheduled purge** (overrides BA-029 "month-partitioned" language) | pg_partman operational overhead not justified at satellite scale. Daily `DELETE WHERE created_at < NOW() - INTERVAL '90 days'` is simpler and testable. This applies to v2 schema design. |
| OQ-011: 401 counter | **Prometheus counter via `--metrics-addr`** | Periodic log line is noise. Counter must be queryable in alerting stack. |
| OQ-005: Redis rate limiting | **Deferred to v2** | Bundle with API-key mode and Redis infrastructure decision. |
| FR-007: Idempotency | **Cut entirely** | No implementation, no reserved columns. New BA when use case is concrete. |
| TLS requirement | **Hard deployment constraint** | `--http` without TLS-terminating reverse proxy is explicitly unsupported. Startup guard asserts binding to non-public interface or warns loudly. |
| `requireBearer` timing bug | **Already fixed** — `serve.go` already uses `subtle.ConstantTimeCompare`. Verify no `!=` path exists as a fallback. | See §5.1 for the one remaining gap (header not stripped). |

---

## 2. Architecture Overview

### HTTP Pipeline — Middleware Chain Order (locked)

```
[client]
  │
  ▼
recover                  ← top-level panic catch; logs panic, returns 500
  │
  ▼
timeout (60s)            ← context.WithTimeout; fires 503 if exceeded
  │
  ▼
auth                     ← requireBearer; strips Authorization header on success
  │                         sets tokenHash on context; rejects → 401 + counter increment
  ▼
rate-limit               ← x/time/rate token bucket keyed on tokenHash
  │                         exceeds → 429
  ▼
log-start                ← records start time, tool name (from path/body), caller hash
  │
  ▼
mcp-dispatch             ← mcp.StreamableHTTPHandler (existing)
  │
  ▼
log-end                  ← emits slog.Info("mcp_tool_call", ...) with duration + status
  │
  ▼
[response flushed]
```

**Why this order matters:**
- `recover` outermost: panics anywhere in the chain are caught and logged without corrupting state
- `timeout` before `auth`: a timed-out request is rejected before consuming auth computation. **Note: this differs from BA-029 §4's specified order (`auth → rate-limit → timeout`)**. The change is intentional — starting the 60s clock before auth gives an accurate total-request latency measurement, and auth is fast enough (< 10ms) that the deviation is immaterial.
- `auth` before `rate-limit`: rate limiting is keyed on authenticated identity, not IP
- `log-start`/`log-end` bracket the dispatch: captures actual call duration

### Transport Selection (serve.go)

```
RunServe(args)
  │
  ├── parseHTTPAddr(args) == "" ──→ stdio path (unchanged, NFR-229)
  │
  └── parseHTTPAddr(args) != "" ──→ validateHTTPStartup() → serveHTTP()
                                       (startup guards fire before listener opens)
```

The two paths are **mutually exclusive** — `RunServe` branches on `httpAddr != ""` and never re-enters the other path. No mid-process toggling.

### New Files

```
internal/bridge/
  serve.go               ← modify (add middleware chain, startup guards, graceful shutdown)
  middleware_auth.go     ← new: requireBearer v2 (header strip, tokenHash context, counter)
  middleware_timeout.go  ← new: per-request timeout handler
  middleware_ratelimit.go ← new: in-process token-bucket rate limiter
  middleware_recover.go  ← new: top-level panic recovery
  middleware_log.go      ← new: slog call log start/end
  metrics.go             ← new: Prometheus counter registration, metrics HTTP handler
  health.go              ← new: /healthz, /readyz handlers
  startup.go             ← new: validateHTTPStartup() with all guards
```

---

## 3. Implementation Plan

### Phase A — Transport Hardening (blockers for everything else)

**Estimate: 1–2 days**

All of Phase A must land before any other phase can be tested in HTTP mode.

**A.1 — Graceful shutdown drain (30 min)**

Current shutdown timeout is 5s. Per-request timeout will be 60s. A 5s drain window silently kills in-flight requests on deploy.

Change in `serveHTTP`:
```go
// Before (current):
shutdownCtx, cancel := context.WithTimeout(context.Background(), 5e9) // 5s

// After:
shutdownCtx, cancel := context.WithTimeout(context.Background(), 65*time.Second) // drain > per-request timeout
```

**A.2 — Startup validation (2h)**

New file `internal/bridge/startup.go`:

```go
// validateHTTPStartup checks all preconditions before the HTTP listener opens.
// Returns an error if any guard fails; the process must not start serving.
func validateHTTPStartup(addr string) error {
    // Guard 1: Token presence
    token := os.Getenv("KG_MCP_TOKEN")
    if token == "" {
        return errors.New("KG_MCP_TOKEN is required for HTTP mode; set it or use stdio mode")
    }

    // Guard 2: Token entropy floor (>= 32 bytes, base64url or hex encoded)
    if err := validateTokenEntropy(token); err != nil {
        return fmt.Errorf("KG_MCP_TOKEN: %w", err)
    }

    // Guard 3: TLS binding assertion
    // Warn if addr binds to 0.0.0.0 or a public interface without a loopback indicator.
    // We cannot enforce TLS in-process without certs, but we must fail loudly
    // if the deployment looks like plain HTTP on a public interface.
    if err := assertTLSDeployment(addr); err != nil {
        return fmt.Errorf("TLS deployment constraint: %w", err)
    }

    // Guard 4: Client timeout validation (client.go uses 30s; server must be >= 30s)
    // This is a static check — the 60s default is hard-coded in the timeout middleware.
    // If someone passes --request-timeout, validate here.

    return nil
}

// validateTokenEntropy rejects tokens below the entropy floor.
// Accepts base64url (RFC 4648 §5) or hex-encoded tokens of >= 32 bytes decoded length.
// A 32-char human-readable password fails; a 32-byte random token passes.
func validateTokenEntropy(token string) error {
    // Try base64url decode
    decoded, err := base64.RawURLEncoding.DecodeString(token)
    if err == nil {
        if len(decoded) >= 32 {
            return nil
        }
        return fmt.Errorf("decoded length %d bytes is below the 32-byte minimum", len(decoded))
    }
    // Try hex decode
    decoded, err = hex.DecodeString(token)
    if err == nil {
        if len(decoded) >= 32 {
            return nil
        }
        return fmt.Errorf("decoded length %d bytes is below the 32-byte minimum", len(decoded))
    }
    // Neither — treat as opaque string, check raw byte count as fallback
    if len(token) >= 43 { // ceil(32*8/6) — base64 expansion of 32 bytes
        return nil
    }
    return fmt.Errorf("token does not appear to be base64url or hex encoded and is shorter than 43 characters; minimum entropy is 32 random bytes")
}
```

**A.3 — Auth middleware hardening (2h)**

New file `internal/bridge/middleware_auth.go`:

The current `requireBearer` in `serve.go` already uses `subtle.ConstantTimeCompare`. The remaining gaps:
1. The `Authorization` header is **not stripped** after validation — the token travels to the MCP SDK where it can appear in error logs
2. No Prometheus counter increment on 401
3. No `tokenHash` set on context for downstream rate-limit keying

```go
type contextKey string

const contextKeyTokenHash contextKey = "tokenHash"

// requireBearerV2 replaces requireBearer in serve.go.
// Changes from v1: strips Authorization header after validation,
// sets tokenHash on context, increments Prometheus counter on 401.
func requireBearerV2(token string, counter prometheus.Counter, next http.Handler) http.Handler {
    want := []byte("Bearer " + token)
    tokenHash := sha256sum([]byte(token)) // pre-compute; never log the token value
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        got := []byte(r.Header.Get("Authorization"))
        if subtle.ConstantTimeCompare(got, want) != 1 {
            counter.Inc()
            http.Error(w, "unauthorized", http.StatusUnauthorized)
            return
        }
        // Strip the header so it cannot leak into SDK error logs or downstream logging.
        r = r.Clone(r.Context())
        r.Header.Del("Authorization")
        // Set identity on context for rate-limit and log middleware.
        ctx := context.WithValue(r.Context(), contextKeyTokenHash, tokenHash)
        next.ServeHTTP(w, r.WithContext(ctx))
    })
}
```

**A.4 — Top-level panic recovery middleware (1h)**

New file `internal/bridge/middleware_recover.go`:

```go
func recoveryMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        defer func() {
            if rv := recover(); rv != nil {
                slog.Error("mcp_bridge: handler panic",
                    "recover_value", fmt.Sprintf("%v", rv),
                    "stack", string(debug.Stack()),
                )
                http.Error(w, "internal server error", http.StatusInternalServerError)
            }
        }()
        next.ServeHTTP(w, r)
    })
}
```

**A.5 — Per-request timeout middleware (2h)**

New file `internal/bridge/middleware_timeout.go`:

```go
const defaultRequestTimeout = 60 * time.Second

func timeoutMiddleware(timeout time.Duration) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            ctx, cancel := context.WithTimeout(r.Context(), timeout)
            defer cancel()
            next.ServeHTTP(w, r.WithContext(ctx))
        })
    }
}
```

Critical: the context created here is passed into `r.WithContext` before the MCP SDK sees the request. The SDK call must receive this context — verify with the test in §6 (T-002).

**A.6 — Wire the middleware chain in serveHTTP (1h)**

```go
func serveHTTP(ctx context.Context, client *Client, cfg BridgeConfig, addr string) error {
    if err := validateHTTPStartup(addr); err != nil {
        return err
    }

    // Metrics (prometheus)
    metrics := newBridgeMetrics()

    // MCP core handler
    mcpHandler := buildStreamableHandler(client, cfg)

    // Health handlers (FR-003)
    mux := http.NewServeMux()
    mux.Handle("/healthz", healthzHandler())
    mux.Handle("/readyz", readyzHandler(client))
    mux.Handle("/", chainMiddleware(
        mcpHandler,
        recoveryMiddleware,
        timeoutMiddleware(defaultRequestTimeout),
        requireBearerV2(os.Getenv("KG_MCP_TOKEN"), metrics.authFailures),
        rateLimitMiddleware(metrics.rateLimiter),
        callLogMiddleware(),
    ))

    srv := &http.Server{
        Addr:    addr,
        Handler: mux,
    }

    go func() {
        <-ctx.Done()
        drainCtx, cancel := context.WithTimeout(context.Background(), 65*time.Second)
        defer cancel()
        _ = srv.Shutdown(drainCtx)
    }()

    slog.Info("kg-bridge: MCP Streamable HTTP listening", "addr", addr)
    if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
        return err
    }
    return nil
}
```

Note: `chainMiddleware` applies wrappers in reverse order so the first argument in the variadic is the outermost. Implement as a simple fold.

---

### Phase B — API-Key Mode + Per-Satellite Identity

**Estimate: 3–5 days** — **DEFERRED to v2**

See §8 (Deferred Items) for rationale and v2 contract.

---

### Phase C — Rate Limiter + Timeout Enforcement

**Estimate: 1 day** (timeout is Phase A; rate limiter is the remaining Phase C work)

**C.1 — In-process token-bucket rate limiter (3h)**

New file `internal/bridge/middleware_ratelimit.go`:

```go
import "golang.org/x/time/rate"

const (
    defaultRateLimit  = 120           // calls per window
    defaultRateWindow = 60 * time.Second
    // Token bucket: burst = limit, refill = limit/window per second
)

type rateLimiterStore struct {
    mu       sync.Mutex
    limiters map[string]*rate.Limiter
}

func newRateLimiterStore() *rateLimiterStore {
    return &rateLimiterStore{limiters: make(map[string]*rate.Limiter)}
}

func (s *rateLimiterStore) get(key string) *rate.Limiter {
    s.mu.Lock()
    defer s.mu.Unlock()
    if lim, ok := s.limiters[key]; ok {
        return lim
    }
    // r = 120/60 = 2 tokens/s, burst = 120
    lim := rate.NewLimiter(rate.Every(defaultRateWindow/defaultRateLimit), defaultRateLimit)
    s.limiters[key] = lim
    return lim
}

func rateLimitMiddleware(store *rateLimiterStore) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            hash, _ := r.Context().Value(contextKeyTokenHash).(string)
            if hash == "" {
                // Auth middleware must set this; if not set, deny conservatively.
                http.Error(w, "identity not established", http.StatusUnauthorized)
                return
            }
            lim := store.get(hash)
            if !lim.Allow() {
                http.Error(w, "rate limit exceeded", http.StatusTooManyRequests)
                return
            }
            next.ServeHTTP(w, r)
        })
    }
}
```

**Implementation notes:**
- `x/time/rate` token bucket deducts on entry. A panic in `mcp-dispatch` leaves the token consumed — this is the **safer behavior** (penalizes the caller, consistent with the `recover` middleware catching the panic).
- State is per-process. On replica addition, replace with Redis-backed sliding window. Document this explicitly with a `// SINGLE-REPLICA-ONLY` comment in the source.
- Limiter map grows unbounded in a long-running process with many distinct token hashes. In v1 with a small number of satellites this is acceptable. Add an LRU eviction or periodic cleanup in v2.

**C.2 — Timeout validation at startup** (already covered in A.2)

The startup guard asserts `KG_MCP_TOKEN` entropy. The per-request timeout (60s) is hard-coded; if a `--request-timeout` flag is added later, validate `>= 30s` at startup (client.go uses a 30s timeout).

---

### Phase D — Audit Log (mcp_tool_call_log)

**Estimate: 3–4 days** — **DEFERRED to v2**

**D.1 — v1 structured call log (in-scope)**

This is not FR-006. It is baseline observability — a synchronous `slog.Info` line emitted before the response is flushed.

New file `internal/bridge/middleware_log.go`:

```go
type callLogKey struct{}

type callLogEntry struct {
    startTime time.Time
    toolName  string
    callerHash string
}

func callLogMiddleware() func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            start := time.Now()
            callerHash, _ := r.Context().Value(contextKeyTokenHash).(string)
            // Tool name extraction: MCP Streamable HTTP embeds tool name in JSON body.
            // Extract non-destructively using a peek reader; fall back to "unknown".
            toolName := extractToolName(r) // see implementation note

            rw := newResponseWriter(w) // wrapper to capture status code
            next.ServeHTTP(rw, r)

            duration := time.Since(start)
            status := "ok"
            if rw.status >= 400 {
                status = "error"
            }
            if r.Context().Err() == context.DeadlineExceeded {
                status = "timeout"
            }

            slog.Info("mcp_tool_call",
                "tool", toolName,
                "caller_hash", callerHash,
                "duration_ms", duration.Milliseconds(),
                "status", status,
                "http_status", rw.status,
            )
        })
    }
}
```

Note: `extractToolName` must peek at the request body without consuming it (use `io.TeeReader` or read-and-replace pattern). If extraction fails, log `"unknown"` — never fail the request for a logging failure.

See §8 for the full FR-006 DB audit log specification (v2).

---

### Phase E — Health/Readiness Endpoints

**Estimate: 2h**

New file `internal/bridge/health.go`:

```go
// healthzHandler returns 200 OK immediately — liveness check.
// Does not check downstream dependencies.
func healthzHandler() http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.Header().Set("Content-Type", "application/json")
        w.WriteHeader(http.StatusOK)
        _, _ = w.Write([]byte(`{"status":"ok"}`))
    })
}

// readyzHandler returns 200 if the bridge can reach the KG API.
// Returns 503 if the upstream check fails.
func readyzHandler(client *Client) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
        defer cancel()
        if err := client.Ping(ctx); err != nil {
            slog.Warn("kg-bridge: readyz upstream check failed", "error", err)
            http.Error(w, `{"status":"not_ready","reason":"upstream_unavailable"}`, http.StatusServiceUnavailable)
            return
        }
        w.Header().Set("Content-Type", "application/json")
        w.WriteHeader(http.StatusOK)
        _, _ = w.Write([]byte(`{"status":"ready"}`))
    })
}
```

`client.HealthCheck(ctx)` already exists in `client.go:517` — use it directly. No new method needed.

Health endpoints are registered **outside** the auth/rate-limit middleware chain. They are intentionally unauthenticated — load balancers and k8s probes must be able to reach them without a Bearer token.

---

### Phase F — Metrics

**Estimate: 3h**

> **New dependency**: `github.com/prometheus/client_golang` is NOT in `go.mod`. Run before implementing:
> ```
> go get github.com/prometheus/client_golang/prometheus
> go get github.com/prometheus/client_golang/prometheus/promhttp
> go get github.com/prometheus/client_golang/prometheus/promauto
> ```
> Alternative for v1: replace `prometheus.Counter` with `sync/atomic` int64 to avoid adding the dependency. Prometheus metrics become a v2 concern when the full metrics package is wired. Decide at implementation.

New file `internal/bridge/metrics.go`:

```go
import (
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promauto"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

type bridgeMetrics struct {
    authFailures prometheus.Counter
    rateLimiter  *rateLimiterStore
}

func newBridgeMetrics() *bridgeMetrics {
    return &bridgeMetrics{
        authFailures: promauto.NewCounter(prometheus.CounterOpts{
            Name: "mcp_auth_failures_total",
            Help: "Total number of MCP Bearer token authentication failures.",
        }),
        rateLimiter: newRateLimiterStore(),
    }
}

// metricsHandler returns an HTTP handler for the Prometheus metrics endpoint.
func metricsHandler() http.Handler {
    return promhttp.Handler()
}
```

Wire `--metrics-addr` flag in `cmd/kg-bridge/main.go`:

```go
// If --metrics-addr is provided, start a separate HTTP listener for Prometheus scraping.
// Example: --metrics-addr :9090
if metricsAddr := parseMetricsAddr(args); metricsAddr != "" {
    metricsMux := http.NewServeMux()
    metricsMux.Handle("/metrics", metricsHandler())
    go http.ListenAndServe(metricsAddr, metricsMux)
}
```

The metrics server is intentionally unauthenticated on the assumption it binds to a private/internal network interface. Document this in the deployment runbook.

---

## 4. DB Migration Spec

### v1 — No migration required

v1 does not introduce any DB schema changes. The `mcp_tool_call_log` table is v2.

### v2 — Migration 000060

**File**: `db/migrations/000060_create_mcp_tool_call_log.up.sql`

```sql
-- mcp_tool_call_log: append-only audit trail for MCP tool calls over HTTP transport.
-- Retention: 90 days. Purge via scheduled job (see below).
-- Partitioning: NOT used in v1 of this table. Revisit if row count exceeds 10M.
-- OQ-010 resolution: scheduled DELETE purge preferred over range partitioning
--   at expected satellite call volumes. Re-evaluate at scale.

CREATE TABLE mcp_tool_call_log (
    id            UUID        NOT NULL DEFAULT gen_random_uuid(),
    -- Server-generated UUID. NOT the MCP protocol-level request ID (which is client-controlled
    -- and cannot be trusted as a unique key).
    request_id    UUID        NOT NULL DEFAULT gen_random_uuid(),
    -- Nullable: shared-token calls have no api_key_id; API-key mode sets this.
    api_key_id    UUID        NULL REFERENCES api_keys(id) ON DELETE SET NULL,
    tool_name     TEXT        NOT NULL,
    -- Status values: 'ok', 'error', 'timeout'. No other values permitted.
    status        TEXT        NOT NULL CHECK (status IN ('ok', 'error', 'timeout')),
    duration_ms   INTEGER     NOT NULL CHECK (duration_ms >= 0),
    -- Error message, truncated to 1024 chars. NULL when status = 'ok'.
    error_msg     TEXT        NULL,
    -- created_at is the index key for the 90-day purge job.
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- NO idempotency_key column. FR-007 is cut. Add when the use case is concrete.
    PRIMARY KEY (id)
);

CREATE INDEX mcp_tool_call_log_created_at_idx ON mcp_tool_call_log (created_at);
CREATE INDEX mcp_tool_call_log_api_key_id_idx ON mcp_tool_call_log (api_key_id)
    WHERE api_key_id IS NOT NULL;
CREATE INDEX mcp_tool_call_log_tool_name_idx ON mcp_tool_call_log (tool_name);

-- Purge job (run daily via pg_cron or external scheduler):
-- DELETE FROM mcp_tool_call_log WHERE created_at < NOW() - INTERVAL '90 days';
```

**Corresponding down migration** (`000060_create_mcp_tool_call_log.down.sql`):

```sql
DROP TABLE IF EXISTS mcp_tool_call_log;
```

### v2 Audit Write Path Contract

When FR-006 is implemented, the write path must follow this contract (decided now to avoid rediscovery):

1. **Bounded channel buffer**: `make(chan auditEvent, 512)`
2. **Dedicated drain goroutine**: single writer to DB, runs for the lifetime of the HTTP server
3. **Non-blocking send**: `select { case ch <- ev: default: auditDroppedTotal.Inc() }` — never blocks the response path
4. **Separate write context**: the DB write uses `context.Background()` with a 5s timeout, NOT the request context (which will be cancelled on timeout/disconnect)
5. **Shutdown drain**: `http.Server.RegisterOnShutdown` or a `sync.WaitGroup` ensures the drain goroutine flushes before the DB connection closes
6. **Dropped-record counter**: `mcp_audit_dropped_total` Prometheus counter incremented on channel overflow

---

## 5. Go Implementation Details

### 5.1 serve.go Changes Summary

| Location | Change |
|----------|--------|
| `serveHTTP` | Add `validateHTTPStartup(addr)` call before listener opens |
| `serveHTTP` | Replace 5s shutdown timeout with 65s drain window |
| `serveHTTP` | Replace `requireBearer(token, mcpHandler)` with full middleware chain |
| `serveHTTP` | Register health handlers on separate mux paths outside auth chain |
| `requireBearer` | Replace with `requireBearerV2` (header strip, context key, counter) — or delete and move to `middleware_auth.go` |

The existing `requireBearer` function can be deleted from `serve.go` once `requireBearerV2` is in `middleware_auth.go`. Do not leave it as a dead function.

### 5.2 New Types and Interfaces

```go
// contextKey is the private type for context keys in the bridge package.
// Prevents collisions with other packages setting values on context.
type contextKey string

const (
    contextKeyTokenHash contextKey = "tokenHash"
    // v2: contextKeyAPIKeyID contextKey = "apiKeyID"
    // v2: contextKeyDeveloperIdentity contextKey = "developerIdentity"
)

// BridgeMetrics holds all Prometheus metrics for the HTTP bridge.
// Created once at serveHTTP startup and passed into middleware constructors.
type bridgeMetrics struct {
    authFailures prometheus.Counter
    rateLimiter  *rateLimiterStore
    // v2: callsTotal   *prometheus.CounterVec (labels: tool_name, status)
    // v2: callDuration *prometheus.HistogramVec
}

// responseWriter wraps http.ResponseWriter to capture the status code.
// Required for the call log middleware to record the HTTP response status.
type responseWriter struct {
    http.ResponseWriter
    status int
}

func newResponseWriter(w http.ResponseWriter) *responseWriter {
    return &responseWriter{ResponseWriter: w, status: http.StatusOK}
}

func (rw *responseWriter) WriteHeader(code int) {
    rw.status = code
    rw.ResponseWriter.WriteHeader(code)
}
```

### 5.3 Key Function Signatures

```go
// startup.go
func validateHTTPStartup(addr string) error
func validateTokenEntropy(token string) error
func assertTLSDeployment(addr string) error

// middleware_auth.go
func requireBearerV2(token string, counter prometheus.Counter, next http.Handler) http.Handler
func sha256sum(b []byte) string  // hex-encoded SHA-256, used for tokenHash

// middleware_timeout.go
func timeoutMiddleware(timeout time.Duration) func(http.Handler) http.Handler

// middleware_ratelimit.go
func rateLimitMiddleware(store *rateLimiterStore) func(http.Handler) http.Handler
func newRateLimiterStore() *rateLimiterStore
func (s *rateLimiterStore) get(key string) *rate.Limiter

// middleware_recover.go
func recoveryMiddleware(next http.Handler) http.Handler

// middleware_log.go
func callLogMiddleware() func(http.Handler) http.Handler
func extractToolName(r *http.Request) string  // peek-reads JSON body; returns "unknown" on failure

// health.go
func healthzHandler() http.Handler
func readyzHandler(client *Client) http.Handler

// metrics.go
func newBridgeMetrics() *bridgeMetrics
func metricsHandler() http.Handler

// serve.go (helpers)
func chainMiddleware(h http.Handler, middlewares ...func(http.Handler) http.Handler) http.Handler
func parseMetricsAddr(args []string) string
```

### 5.4 `chainMiddleware` Implementation

```go
// chainMiddleware applies middlewares in order: first argument is outermost (first to execute).
// Example: chainMiddleware(handler, recover, timeout, auth) produces recover(timeout(auth(handler))).
func chainMiddleware(h http.Handler, middlewares ...func(http.Handler) http.Handler) http.Handler {
    for i := len(middlewares) - 1; i >= 0; i-- {
        h = middlewares[i](h)
    }
    return h
}
```

### 5.5 `assertTLSDeployment` Logic

```go
// assertTLSDeployment warns/errors if the binding address looks like plain HTTP
// on a public network interface. The bridge does not terminate TLS itself;
// it relies on a TLS-terminating reverse proxy. Binding to 0.0.0.0 on a
// non-loopback address is allowed but emits a loud startup warning.
// Returns an error (hard fail) only if KG_MCP_REQUIRE_TLS=true and the
// address is not loopback.
func assertTLSDeployment(addr string) error {
    host, _, err := net.SplitHostPort(addr)
    if err != nil {
        return fmt.Errorf("invalid --http address %q: %w", addr, err)
    }
    isLoopback := host == "127.0.0.1" || host == "::1" || host == "localhost"
    requireTLS := os.Getenv("KG_MCP_REQUIRE_TLS") == "true"
    if !isLoopback && requireTLS {
        return errors.New("KG_MCP_REQUIRE_TLS=true but --http addr is not loopback; " +
            "ensure a TLS-terminating reverse proxy is in front of this listener")
    }
    if !isLoopback {
        slog.Warn("kg-bridge: HTTP mode binding to non-loopback address without KG_MCP_REQUIRE_TLS=true; " +
            "ensure TLS is terminated at the reverse proxy — plain HTTP with Bearer tokens is insecure")
    }
    return nil
}
```

---

## 6. Testing Plan

The following tests are non-obvious or carry high regression risk. Standard happy-path and error-path tests are expected; these are the tests that are easy to omit and painful to be missing in production.

### T-001 — Constant-time compare cannot be verified by boolean equality alone

**What**: A regression guard asserting that no plain string comparison (`!=` or `==`) of the token appears in `serve.go` or `middleware_auth.go`.

**How**: `TestNoPlainTokenCompare` reads the source file bytes and asserts the string `"!= "` does not appear adjacent to `"token"` or `"bearer"` (case-insensitive). Also write a test that passes a token that is a prefix of the real token and asserts 401.

```go
func TestRequireBearerRejectsPrefixMatch(t *testing.T) {
    realToken := "abcdefghij_this_is_32_bytes_long"
    prefix := realToken[:16]
    h := requireBearerV2(realToken, prometheus.NewCounter(prometheus.CounterOpts{}), okHandler)
    req := httptest.NewRequest("POST", "/", nil)
    req.Header.Set("Authorization", "Bearer "+prefix)
    rr := httptest.NewRecorder()
    h.ServeHTTP(rr, req)
    if rr.Code != http.StatusUnauthorized {
        t.Errorf("expected 401, got %d", rr.Code)
    }
}
```

### T-002 — Timeout context propagates into MCP SDK call

**What**: The per-request timeout context must be the context the MCP SDK tool handler receives, not a discarded wrapper.

**How**: Create a tool handler in test that calls `time.Sleep(2s)` while the timeout is set to `100ms`. Assert the HTTP response arrives within `200ms` (not after 2s). A test that passes but takes 2s is a false pass — the timeout middleware created a context but it was not threaded through.

```go
func TestTimeoutPropagatesIntoDispatch(t *testing.T) {
    // Register a slow tool handler
    // Set timeout to 100ms
    // Issue request
    // Assert response arrives in < 200ms
    // Assert response status is 503 or 499 (timeout)
}
```

### T-003 — Audit log line does not delay response

**What**: The `slog.Info("mcp_tool_call", ...)` line must execute **after** the response is flushed, or at minimum must not block the response path.

**How**: Inject a `slog.Handler` that records call timing. Assert `response_flushed_at < slog_called_at + 10ms`. With the current synchronous log approach the log fires after `next.ServeHTTP` returns but before the handler returns — which means it is synchronous but post-response. Verify this is not blocking by asserting response time is not correlated with an artificially slow slog handler.

### T-004 — Rate limit fires on (N+1)th call

**What**: 120 calls succeed, the 121st returns 429. After the window expires, calls succeed again.

**How**: Use `x/time/rate` directly in the test — do not go through HTTP for the rate-limit unit test (keeps it deterministic). For integration: issue 121 requests to a test HTTP server with `time.Sleep(0)` between calls and assert the last one is 429.

```go
func TestRateLimitFires(t *testing.T) {
    store := newRateLimiterStore()
    for i := 0; i < 120; i++ {
        if !store.get("key1").Allow() {
            t.Fatalf("call %d should have been allowed", i+1)
        }
    }
    if store.get("key1").Allow() {
        t.Error("call 121 should have been rate-limited")
    }
}
```

### T-005 — Stdio transport not affected

**What**: No HTTP listener starts when `--http` flag is absent. NFR-229 guard.

**How**: Spin up the bridge in stdio mode after all changes. Assert no port is bound. Issue a tool call over stdin/stdout. Assert it succeeds.

```go
func TestStdioModeNoHTTPListener(t *testing.T) {
    // RunServe with no --http flag
    // Assert no net.Listen on any port occurred
    // Issue tool call over stdin/stdout pipe
    // Assert response received
}
```

### T-006 — Authorization header stripped

**What**: The `Authorization` header must not be visible to the MCP SDK handler after auth middleware.

**How**: Register a test tool that reads `r.Header.Get("Authorization")` from the request context and returns it in the response. Assert the returned value is empty after auth middleware processes a valid Bearer token.

### T-007 — Startup guard rejects empty token

**What**: `validateHTTPStartup` must return a non-nil error when `KG_MCP_TOKEN=""`.

```go
func TestStartupGuardRejectsEmptyToken(t *testing.T) {
    t.Setenv("KG_MCP_TOKEN", "")
    err := validateHTTPStartup(":8082")
    if err == nil {
        t.Error("expected error for empty KG_MCP_TOKEN")
    }
}
```

### T-008 — Startup guard rejects low-entropy tokens

**What**: Short or human-readable tokens below the entropy floor are rejected.

```go
func TestValidateTokenEntropyRejectsShortToken(t *testing.T) {
    cases := []struct {
        token   string
        wantErr bool
    }{
        {"abc123", true},
        {"password1", true},
        {base64.RawURLEncoding.EncodeToString(make([]byte, 31)), true},  // 31 bytes — below floor
        {base64.RawURLEncoding.EncodeToString(make([]byte, 32)), false}, // 32 bytes — passes
        {hex.EncodeToString(make([]byte, 32)), false},                   // hex 32 bytes
    }
    // ...
}
```

### T-009 — Health endpoints bypass auth

**What**: `/healthz` and `/readyz` return 200 without an `Authorization` header.

```go
func TestHealthzNoAuth(t *testing.T) {
    // Start test server with full middleware chain
    req := httptest.NewRequest("GET", "/healthz", nil)
    // No Authorization header
    rr := httptest.NewRecorder()
    // Assert 200
}
```

### T-010 — Prometheus counter increments on 401

**What**: Sending a bad token increments `mcp_auth_failures_total`.

```go
func TestAuthFailureCounterIncrements(t *testing.T) {
    counter := prometheus.NewCounter(prometheus.CounterOpts{Name: "test_auth_failures"})
    h := requireBearerV2("correct-token", counter, okHandler)
    // Send bad token
    // Assert counter.Value() == 1
}
```

---

## 7. Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `KG_MCP_TOKEN` | Required in HTTP mode | — | Shared Bearer token. Must be base64url or hex, >= 32 decoded bytes. Empty → startup failure in HTTP mode. |
| `KG_MCP_REQUIRE_TLS` | Optional | `false` | Set to `true` to hard-fail startup if `--http` binds to non-loopback. Recommended for production deployments. |
| `KG_MCP_RATE_LIMIT` | Optional | `120` | Max calls per 60s window per caller identity. In-process, single-replica only. |
| `KG_MCP_RATE_WINDOW` | Optional | `60s` | Rate limit window duration (Go duration string). |
| `KG_MCP_REQUEST_TIMEOUT` | Optional | `60s` | Per-request server-side timeout. Must be >= 30s (client.go timeout). Startup guard validates. |

### CLI Flags (parsed in `cmd/kg-bridge/main.go`)

| Flag | Description |
|------|-------------|
| `--http <addr>` | Enable HTTP mode, listen on `addr` (e.g. `:8082`, `127.0.0.1:8082`) |
| `--metrics-addr <addr>` | Start Prometheus metrics server on `addr` (e.g. `:9090`) |

### Startup Validation Summary

On `--http` mode entry (before listener opens), `validateHTTPStartup` checks:

1. `KG_MCP_TOKEN` is non-empty → fail if absent
2. Token entropy: base64url or hex decoded length >= 32 bytes → fail if below floor
3. TLS binding: if `KG_MCP_REQUIRE_TLS=true` and addr is not loopback → fail; otherwise warn
4. Request timeout >= client timeout (30s) → fail if `KG_MCP_REQUEST_TIMEOUT` is set below 30s

---

## 8. Deferred Items (v2)

### v2 Bundle: Multi-Tenant Satellite Drop

Ship FR-002 API-key mode, FR-005 Redis rate limiting, and FR-006 audit log DB together. They form a cohesive set: you need per-satellite identity before per-satellite rate limiting and per-satellite audit logging are meaningful.

**FR-002 API-key mode:**

- DB migration 000061: `api_keys` table already exists (migration 000003). Verify `key_hash`, `revoked_at`, `project_ids` columns are present. Add `satellite_name` label if needed.
- `internal/store/apikey.go`: `LookupByHash(ctx, hash string) (*APIKey, error)` — SHA-256 indexed lookup
- `DeveloperIdentity` extraction: verify `internal/middleware/auth.go` has no REST-specific assumptions (path patterns, JSON body parsing) before reuse. Extract identity getter into shared package if needed.
- Context key `contextKeyAPIKeyID` and `contextKeyDeveloperIdentity` (already reserved in §5.2 comment)
- Startup rule: if `api_keys` table is non-empty, API-key mode wins; `KG_MCP_TOKEN` ignored with startup warning

**FR-005 Redis-backed rate limiting:**

- Replace `x/time/rate` in-process limiter with Redis sliding window (e.g. `go-redis/redis/v9` + Lua script)
- Keyed on `api_key_id` (not token hash) for per-satellite attribution
- OQ-005 resolution: bundle with multi-replica deployment decision

**FR-006 mcp_tool_call_log DB table:**

- Migration 000060 DDL is specified in §4 — ready to run when v2 ships
- Async write path contract specified in §4.4 — must be implemented exactly as specified (bounded channel, background context, shutdown drain)
- `tool_name`, `api_key_id`, `status`, `duration_ms`, `error_msg`, `created_at`
- Retention: daily `DELETE WHERE created_at < NOW() - INTERVAL '90 days'` (scheduled job)
- Dropped-record counter: `mcp_audit_dropped_total`

**FR-007 Idempotency:**

- Cut entirely from BA-029. No reserved columns. Open a new BA when the use case is concrete.
- The `mcp_tool_call_log` schema has **no** `idempotency_key` column.

### Ecosystem Onboarding (before v1 ships to LAAM/AAA)

A one-page integration guide must be written (not part of this spec, but blocking for satellite adoption):

1. **Token distribution**: How does a satellite get its `KG_MCP_TOKEN`? Manual env var in the DAAB deployment for v1. Document this explicitly.
2. **SDK/client contract**: endpoint URL format, `Authorization: Bearer <token>` header, Content-Type for MCP Streamable HTTP, client timeout budget (<= 30s)
3. **Error response contract**: what does a 401 look like in the MCP response envelope? Satellites must handle this gracefully
4. **Local dev story**: `--http localhost:8082` invocation and env var setup for developers testing HTTP mode against a local DAAB

---

## 9. Open Questions Resolved

| OQ | Decision | Rationale |
|----|----------|-----------|
| **OQ-010**: Monthly range-partitioning vs scheduled purge | **Scheduled purge** — `DELETE WHERE created_at < NOW() - INTERVAL '90 days'` with a `created_at` index. No partitioning. | At satellite call volume (120 calls/60s per identity, small number of satellites), range partitioning adds operational burden (partition pre-creation, pg_partman or manual) with no throughput benefit. Revisit if table exceeds 10M rows. pg_cron or an external scheduler runs the purge daily. **Overrides BA-029's "month-partitioned" language.** |
| **OQ-011**: Export 401 counter as Prometheus metric? | **Yes — `mcp_auth_failures_total` via `--metrics-addr`**. | Periodic log line is operationally invisible in alerting stacks. Counter must be queryable to alert on misconfigured satellites and token rotation failures. `--metrics-addr` added to CLI flags to avoid depending on an existing `/metrics` endpoint (the bridge has none). |
| **OQ-005**: Rate limit state in-process; when to Redis? | **Deferred to v2, bundled with multi-replica decision**. In-process `x/time/rate` ships in v1 as a single-replica ceiling, documented as throwaway. Redis migration happens when the multi-replica decision is made. | CTO correctly identified the technical debt risk; the counter-argument (no ceiling on an authenticated endpoint is worse than bounded throwaway debt) is accepted for v1. Rate limiting is server-side protection, not a client contract. |

---

## 10. Acceptance Criteria for v1

A v1 implementation is complete when all of the following are verifiable:

- [ ] `go run ./cmd/kg-bridge/` with no `--http` flag starts in stdio mode; no TCP port is bound; tool calls succeed over stdin/stdout
- [ ] `KG_MCP_TOKEN="" go run ./cmd/kg-bridge/ --http :8082` fails at startup with a clear error message before the listener opens
- [ ] A token shorter than 32 decoded bytes causes startup failure with a descriptive error
- [ ] `KG_MCP_TOKEN=<valid> go run ./cmd/kg-bridge/ --http :8082` starts and serves MCP tool calls
- [ ] `curl -H "Authorization: Bearer wrong" http://localhost:8082/` returns 401
- [ ] `mcp_auth_failures_total` increments in Prometheus after a 401
- [ ] `curl http://localhost:8082/healthz` returns 200 without an Authorization header
- [ ] `curl http://localhost:8082/readyz` returns 200 when KG API is reachable, 503 when not
- [ ] 121 rapid calls from one identity: first 120 succeed, 121st returns 429
- [ ] A request that takes longer than 60s returns a timeout response; response arrives within 65s
- [ ] The `Authorization` header value is absent from all log output (including panic logs)
- [ ] SIGTERM with an in-flight 60s request: request completes (not killed), audit log line emitted
- [ ] All tests in `T-001` through `T-010` pass
- [ ] `go test -race ./internal/bridge/...` passes with no data race reports