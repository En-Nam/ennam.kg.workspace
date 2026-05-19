# BA-009 AI Provider Abstraction Layer — Go API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement AI provider registry, Claude Max + pay-per-token fallback integration, circuit breaker, budget enforcement, and normalized request/response interface in the Go API server.

**Architecture:** New `internal/ai/` package tree encapsulating provider abstraction. Circuit breaker is in-process (not distributed) using atomic counters. Budget tracking is DB-backed with monthly reset. Provider selection uses priority-based failover with availability checks. All external AI communication goes through a single `ai.Client` interface.

**Tech Stack:** Go std lib, `net/http` (for AI API calls), AES-256-GCM (reuse from Task 1), `sync/atomic` (circuit breaker), PostgreSQL (usage/budget tracking)

**BA Reference:** `ennam.kg.requirements/documents/phase2/BA-009-ai-provider-abstraction.md`

---

## File Structure

### New Files

```
internal/ai/
├── client.go                       # Client interface: Send(ctx, Request) (*Response, error)
├── client_test.go
├── provider.go                     # Provider interface + registry
├── provider_test.go
├── anthropic.go                    # Anthropic API adapter (Claude Max + direct API)
├── anthropic_test.go
├── openai.go                       # OpenAI API adapter
├── openai_test.go
├── selector.go                     # Priority-based provider selection with failover
├── selector_test.go
├── circuitbreaker.go               # Circuit breaker (closed/open/half-open)
├── circuitbreaker_test.go
├── budget.go                       # Budget enforcement + tracking
├── budget_test.go
├── normalize.go                    # Request/response normalization
└── normalize_test.go

internal/models/
├── ai_provider.go                  # AIProvider, AIUsageLog, AIBudgetTracking, AIProviderHealth models

internal/store/
├── ai_provider.go                  # AIProviderStore: CRUD
├── ai_provider_test.go
├── ai_usage.go                     # AIUsageStore: log + budget + health
└── ai_usage_test.go

internal/service/
├── ai_provider.go                  # AIProviderService: registration, health check, usage stats
└── ai_provider_test.go

internal/handler/
├── ai_provider.go                  # AIProviderHandler: REST endpoints
└── ai_provider_test.go

db/migrations/
├── 000020_create_ai_providers.up.sql
├── 000020_create_ai_providers.down.sql
├── 000021_create_ai_usage.up.sql
├── 000021_create_ai_usage.down.sql
├── 000022_create_ai_provider_health.up.sql
└── 000022_create_ai_provider_health.down.sql
```

### Modified Files

```
cmd/kg-server/main.go              # Wire AI provider handlers + AI client into buildRouter()
config/config.yaml                  # Add ai.provider_strategy section
```

---

## Task 1: Database Migrations (020-022)

**Files:**
- Create: `db/migrations/000020_create_ai_providers.up.sql` + down
- Create: `db/migrations/000021_create_ai_usage.up.sql` + down
- Create: `db/migrations/000022_create_ai_provider_health.up.sql` + down

- [ ] **Step 1: Write migration 020 — ai_providers table**

```sql
-- 000020_create_ai_providers.up.sql
CREATE TABLE ai_providers (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(255) NOT NULL UNIQUE,
    provider_type   VARCHAR(50) NOT NULL,
    base_url        VARCHAR(500) NOT NULL,
    api_key_encrypted BYTEA,
    model_id        VARCHAR(255) NOT NULL,
    rate_limit_rpm  INTEGER NOT NULL DEFAULT 50,
    rate_limit_tpd  INTEGER NOT NULL DEFAULT 1000000,
    cost_per_input_token  BIGINT NOT NULL DEFAULT 0,
    cost_per_output_token BIGINT NOT NULL DEFAULT 0,
    priority        INTEGER NOT NULL UNIQUE,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    status          VARCHAR(50) NOT NULL DEFAULT 'healthy',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ai_providers_type_check CHECK (provider_type IN ('claude_max', 'anthropic_api', 'openai')),
    CONSTRAINT ai_providers_status_check CHECK (status IN ('healthy', 'degraded', 'circuit_open', 'recovering')),
    CONSTRAINT ai_providers_cost_nonneg CHECK (cost_per_input_token >= 0 AND cost_per_output_token >= 0)
);
```

```sql
-- 000020_create_ai_providers.down.sql
DROP TABLE IF EXISTS ai_providers;
```

- [ ] **Step 2: Write migration 021 — ai_usage_logs + ai_budget_tracking**

```sql
-- 000021_create_ai_usage.up.sql
CREATE TABLE ai_usage_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider_id     UUID NOT NULL REFERENCES ai_providers(id),
    request_type    VARCHAR(100) NOT NULL,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cost_calculated BIGINT NOT NULL DEFAULT 0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    finish_reason   VARCHAR(50),
    error_code      VARCHAR(100),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ai_usage_provider ON ai_usage_logs(provider_id, created_at);
CREATE INDEX idx_ai_usage_created ON ai_usage_logs(created_at);

CREATE TABLE ai_budget_tracking (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider_type   VARCHAR(50) NOT NULL,
    month           DATE NOT NULL,
    budget_monthly_usd BIGINT NOT NULL DEFAULT 50000000,
    spend_current   BIGINT NOT NULL DEFAULT 0,
    alert_80_triggered BOOLEAN NOT NULL DEFAULT false,
    exhausted_at    TIMESTAMPTZ,
    reset_at        TIMESTAMPTZ,

    CONSTRAINT ai_budget_month_unique UNIQUE (provider_type, month),
    CONSTRAINT ai_budget_type_check CHECK (provider_type IN ('claude_max', 'anthropic_api', 'openai'))
);
```

```sql
-- 000021_create_ai_usage.down.sql
DROP TABLE IF EXISTS ai_budget_tracking;
DROP TABLE IF EXISTS ai_usage_logs;
```

- [ ] **Step 3: Write migration 022 — ai_provider_health**

```sql
-- 000022_create_ai_provider_health.up.sql
CREATE TABLE ai_provider_health (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider_id             UUID NOT NULL REFERENCES ai_providers(id) UNIQUE,
    last_checked_at         TIMESTAMPTZ,
    consecutive_failures    INTEGER NOT NULL DEFAULT 0,
    last_failure_at         TIMESTAMPTZ,
    circuit_breaker_state   VARCHAR(50) NOT NULL DEFAULT 'closed',
    circuit_breaker_opened_at TIMESTAMPTZ,

    CONSTRAINT ai_health_cb_check CHECK (circuit_breaker_state IN ('closed', 'open', 'half_open'))
);
```

```sql
-- 000022_create_ai_provider_health.down.sql
DROP TABLE IF EXISTS ai_provider_health;
```

- [ ] **Step 4: Run migrations**

Run: `cd ennam.kg.go && make db-migrate`
Expected: Migrations 020-022 applied

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add db/migrations/000020_* db/migrations/000021_* db/migrations/000022_*
git commit -m "feat(db): add ai_providers, ai_usage_logs, ai_budget_tracking, ai_provider_health tables (BA-009)"
```

---

## Task 2: Domain Models

**Files:**
- Create: `internal/models/ai_provider.go`

- [ ] **Step 1: Define all BA-009 models**

```go
// internal/models/ai_provider.go
package models

import "time"

// AIProvider represents a registered AI service provider.
type AIProvider struct {
	ID                string    `json:"id" db:"id"`
	Name              string    `json:"name" db:"name"`
	ProviderType      string    `json:"provider_type" db:"provider_type"`
	BaseURL           string    `json:"base_url" db:"base_url"`
	APIKeyEncrypted   []byte    `json:"-" db:"api_key_encrypted"`
	ModelID           string    `json:"model_id" db:"model_id"`
	RateLimitRPM      int       `json:"rate_limit_rpm" db:"rate_limit_rpm"`
	RateLimitTPD      int       `json:"rate_limit_tpd" db:"rate_limit_tpd"`
	CostPerInputToken int64     `json:"cost_per_input_token" db:"cost_per_input_token"`
	CostPerOutputToken int64    `json:"cost_per_output_token" db:"cost_per_output_token"`
	Priority          int       `json:"priority" db:"priority"`
	IsActive          bool      `json:"is_active" db:"is_active"`
	Status            string    `json:"status" db:"status"`
	CreatedAt         time.Time `json:"created_at" db:"created_at"`
	UpdatedAt         time.Time `json:"updated_at" db:"updated_at"`
}

// AIUsageLog records a single AI API request for cost and latency tracking.
type AIUsageLog struct {
	ID             string    `json:"id" db:"id"`
	ProviderID     string    `json:"provider_id" db:"provider_id"`
	RequestType    string    `json:"request_type" db:"request_type"`
	InputTokens    int       `json:"input_tokens" db:"input_tokens"`
	OutputTokens   int       `json:"output_tokens" db:"output_tokens"`
	CostCalculated int64     `json:"cost_calculated" db:"cost_calculated"`
	LatencyMs      int       `json:"latency_ms" db:"latency_ms"`
	FinishReason   *string   `json:"finish_reason,omitempty" db:"finish_reason"`
	ErrorCode      *string   `json:"error_code,omitempty" db:"error_code"`
	CreatedAt      time.Time `json:"created_at" db:"created_at"`
}

// AIBudgetTracking tracks monthly spend per provider type.
type AIBudgetTracking struct {
	ID               string     `json:"id" db:"id"`
	ProviderType     string     `json:"provider_type" db:"provider_type"`
	Month            time.Time  `json:"month" db:"month"`
	BudgetMonthlyUSD int64      `json:"budget_monthly_usd" db:"budget_monthly_usd"`
	SpendCurrent     int64      `json:"spend_current" db:"spend_current"`
	Alert80Triggered bool       `json:"alert_80_triggered" db:"alert_80_triggered"`
	ExhaustedAt      *time.Time `json:"exhausted_at,omitempty" db:"exhausted_at"`
	ResetAt          *time.Time `json:"reset_at,omitempty" db:"reset_at"`
}

// AIProviderHealth tracks circuit breaker state and failure history.
type AIProviderHealth struct {
	ID                    string     `json:"id" db:"id"`
	ProviderID            string     `json:"provider_id" db:"provider_id"`
	LastCheckedAt         *time.Time `json:"last_checked_at,omitempty" db:"last_checked_at"`
	ConsecutiveFailures   int        `json:"consecutive_failures" db:"consecutive_failures"`
	LastFailureAt         *time.Time `json:"last_failure_at,omitempty" db:"last_failure_at"`
	CircuitBreakerState   string     `json:"circuit_breaker_state" db:"circuit_breaker_state"`
	CircuitBreakerOpenedAt *time.Time `json:"circuit_breaker_opened_at,omitempty" db:"circuit_breaker_opened_at"`
}

// AIRequest is the normalized request sent to any AI provider.
type AIRequest struct {
	Messages     []AIMessage `json:"messages"`
	MaxTokens    int         `json:"max_tokens"`
	Temperature  float64     `json:"temperature"`
	SystemPrompt string      `json:"system_prompt,omitempty"`
	RequestType  string      `json:"request_type"`
	Metadata     map[string]string `json:"metadata,omitempty"`
}

// AIMessage represents a single message in a conversation.
type AIMessage struct {
	Role    string `json:"role"`    // "user", "assistant"
	Content string `json:"content"`
}

// AIResponse is the normalized response from any AI provider.
type AIResponse struct {
	Content      string `json:"content"`
	InputTokens  int    `json:"input_tokens"`
	OutputTokens int    `json:"output_tokens"`
	FinishReason string `json:"finish_reason"` // completed, truncated, filtered
	ProviderID   string `json:"provider_id"`
	Model        string `json:"model"`
	LatencyMs    int    `json:"latency_ms"`
}

// Provider type constants.
const (
	ProviderTypeClaudeMax    = "claude_max"
	ProviderTypeAnthropicAPI = "anthropic_api"
	ProviderTypeOpenAI       = "openai"
)

// Circuit breaker state constants.
const (
	CircuitClosed   = "closed"
	CircuitOpen     = "open"
	CircuitHalfOpen = "half_open"
)

// Normalized finish reasons.
const (
	FinishCompleted = "completed"
	FinishTruncated = "truncated"
	FinishFiltered  = "filtered"
)

// Normalized error codes.
const (
	AIErrRateLimited     = "RATE_LIMITED"
	AIErrContextTooLong  = "CONTEXT_TOO_LONG"
	AIErrInvalidRequest  = "INVALID_REQUEST"
	AIErrProviderError   = "PROVIDER_ERROR"
	AIErrTimeout         = "TIMEOUT"
	AIErrBudgetExhausted = "BUDGET_EXHAUSTED"
)
```

- [ ] **Step 2: Commit**

```bash
cd ennam.kg.go
git add internal/models/ai_provider.go
git commit -m "feat(models): add AI provider, usage, budget, health models (BA-009)"
```

---

## Task 3: Circuit Breaker

**Files:**
- Create: `internal/ai/circuitbreaker.go`
- Test: `internal/ai/circuitbreaker_test.go`

- [ ] **Step 1: Write failing tests**

```go
// internal/ai/circuitbreaker_test.go
package ai_test

import (
	"testing"
	"time"

	"github.com/ennam/ennam-kg/internal/ai"
)

func TestCircuitBreaker_StartsOpen(t *testing.T) {
	cb := ai.NewCircuitBreaker(3, 5*time.Minute, 30*time.Second)
	if !cb.Allow() {
		t.Fatal("new circuit breaker should allow requests")
	}
}

func TestCircuitBreaker_OpensAfterThreshold(t *testing.T) {
	cb := ai.NewCircuitBreaker(3, 5*time.Minute, 30*time.Second)

	cb.RecordFailure()
	cb.RecordFailure()
	cb.RecordFailure()

	if cb.Allow() {
		t.Fatal("should not allow after 3 failures")
	}
	if cb.State() != "open" {
		t.Fatalf("state: got %q, want %q", cb.State(), "open")
	}
}

func TestCircuitBreaker_ResetsOnSuccess(t *testing.T) {
	cb := ai.NewCircuitBreaker(3, 5*time.Minute, 30*time.Second)

	cb.RecordFailure()
	cb.RecordFailure()
	cb.RecordSuccess()

	if !cb.Allow() {
		t.Fatal("should allow after success resets counter")
	}
	if cb.State() != "closed" {
		t.Fatalf("state: got %q, want %q", cb.State(), "closed")
	}
}

func TestCircuitBreaker_HalfOpenAfterCooldown(t *testing.T) {
	cb := ai.NewCircuitBreaker(3, 5*time.Minute, 1*time.Millisecond) // tiny cooldown for test

	cb.RecordFailure()
	cb.RecordFailure()
	cb.RecordFailure()

	time.Sleep(5 * time.Millisecond)

	if !cb.Allow() {
		t.Fatal("should allow probe request after cooldown")
	}
	if cb.State() != "half_open" {
		t.Fatalf("state: got %q, want %q", cb.State(), "half_open")
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/ai/... -run TestCircuitBreaker -v`

- [ ] **Step 3: Implement CircuitBreaker**

```go
// internal/ai/circuitbreaker.go
package ai

import (
	"sync"
	"time"
)

// CircuitBreaker implements the circuit breaker pattern for AI provider health.
// States: closed (normal) → open (failing) → half_open (probing).
type CircuitBreaker struct {
	mu                sync.Mutex
	failureThreshold  int
	failureWindow     time.Duration
	cooldownDuration  time.Duration
	failures          int
	lastFailureAt     time.Time
	state             string
	openedAt          time.Time
}

func NewCircuitBreaker(threshold int, window, cooldown time.Duration) *CircuitBreaker {
	return &CircuitBreaker{
		failureThreshold: threshold,
		failureWindow:    window,
		cooldownDuration: cooldown,
		state:            "closed",
	}
}

func (cb *CircuitBreaker) Allow() bool {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	switch cb.state {
	case "closed":
		return true
	case "open":
		if time.Since(cb.openedAt) >= cb.cooldownDuration {
			cb.state = "half_open"
			return true
		}
		return false
	case "half_open":
		return true
	default:
		return true
	}
}

func (cb *CircuitBreaker) RecordSuccess() {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	cb.failures = 0
	cb.state = "closed"
}

func (cb *CircuitBreaker) RecordFailure() {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	now := time.Now()

	// Reset counter if outside failure window.
	if !cb.lastFailureAt.IsZero() && now.Sub(cb.lastFailureAt) > cb.failureWindow {
		cb.failures = 0
	}

	cb.failures++
	cb.lastFailureAt = now

	if cb.failures >= cb.failureThreshold {
		cb.state = "open"
		cb.openedAt = now
	}
}

func (cb *CircuitBreaker) State() string {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	if cb.state == "open" && time.Since(cb.openedAt) >= cb.cooldownDuration {
		cb.state = "half_open"
	}
	return cb.state
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/ai/... -run TestCircuitBreaker -v -race`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/ai/circuitbreaker.go internal/ai/circuitbreaker_test.go
git commit -m "feat(ai): add circuit breaker with threshold, window, and cooldown (BA-009)"
```

---

## Task 4: AI Provider Store (CRUD)

**Files:**
- Create: `internal/store/ai_provider.go`
- Test: `internal/store/ai_provider_test.go`

- [ ] **Step 1: Write failing tests**

Tests for: `Create`, `GetByID`, `List` (ordered by priority), `Update`, `Deactivate`, `GetActiveByPriority`

Key test: cannot deactivate if it's the last active provider → error

- [ ] **Step 2: Implement AIProviderStore**

Methods:
- `Create(ctx, provider)` — INSERT with encrypted API key
- `GetByID(ctx, id)` — SELECT single
- `List(ctx)` — SELECT all ORDER BY priority
- `GetActiveByPriority(ctx)` — SELECT WHERE is_active = true ORDER BY priority ASC
- `Update(ctx, provider)` — UPDATE fields
- `Deactivate(ctx, id)` — SET is_active = false (check not last active)
- `CountActive(ctx)` — used by deactivate guard

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.go
git add internal/store/ai_provider.go internal/store/ai_provider_test.go
git commit -m "feat(store): add AIProviderStore with priority-ordered CRUD (BA-009)"
```

---

## Task 5: AI Usage & Budget Store

**Files:**
- Create: `internal/store/ai_usage.go`
- Test: `internal/store/ai_usage_test.go`

- [ ] **Step 1: Write failing tests**

Tests for:
- `LogUsage(ctx, log)` — INSERT usage record
- `GetMonthlyBudget(ctx, providerType, month)` — GET or CREATE budget record
- `IncrementSpend(ctx, providerType, amount)` — atomic INCREMENT + check exhaustion
- `GetUsageStats(ctx, providerID, since)` — aggregated stats (RPM, daily tokens)
- `GetBudgetStats(ctx)` — all budgets with projected spend

- [ ] **Step 2: Implement AIUsageStore**

Key: `IncrementSpend` uses `UPDATE ... SET spend_current = spend_current + $1 ... RETURNING spend_current, budget_monthly_usd` for atomic budget check.

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.go
git add internal/store/ai_usage.go internal/store/ai_usage_test.go
git commit -m "feat(store): add AIUsageStore with atomic budget tracking (BA-009)"
```

---

## Task 6: Provider Adapters (Anthropic + OpenAI)

**Files:**
- Create: `internal/ai/client.go`
- Create: `internal/ai/anthropic.go`
- Create: `internal/ai/openai.go`
- Create: `internal/ai/normalize.go`
- Test: `internal/ai/anthropic_test.go`, `internal/ai/openai_test.go`, `internal/ai/normalize_test.go`

- [ ] **Step 1: Define Provider interface and normalized types**

```go
// internal/ai/client.go
package ai

import (
	"context"

	"github.com/ennam/ennam-kg/internal/models"
)

// Provider sends normalized AI requests to a specific backend.
type Provider interface {
	// Send sends a normalized request and returns a normalized response.
	Send(ctx context.Context, req *models.AIRequest) (*models.AIResponse, error)

	// ProviderID returns the provider's database ID.
	ProviderID() string

	// ProviderType returns "claude_max", "anthropic_api", or "openai".
	ProviderType() string
}
```

- [ ] **Step 2: Write failing tests for Anthropic adapter**

Test request/response mapping:
- `system_prompt` → Anthropic `system` field
- `messages` → `messages` array
- Response: `content[0].text`, `usage.input_tokens`, `usage.output_tokens`
- HTTP 429 → `AIErrRateLimited`
- HTTP 5xx → `AIErrProviderError`

Use `httptest.Server` to mock Anthropic API responses.

- [ ] **Step 3: Implement Anthropic adapter**

```go
// internal/ai/anthropic.go — key structure
type AnthropicProvider struct {
    id         string
    ptype      string // "claude_max" or "anthropic_api"
    baseURL    string
    apiKey     string
    modelID    string
    httpClient *http.Client
}

func (p *AnthropicProvider) Send(ctx context.Context, req *models.AIRequest) (*models.AIResponse, error) {
    // 1. Build Anthropic request body
    // 2. POST to baseURL/v1/messages
    // 3. Parse response, normalize finish_reason
    // 4. Map errors to normalized error codes
}
```

- [ ] **Step 4: Write failing tests for OpenAI adapter + implement**

Similar pattern but maps to OpenAI chat completions API format.

- [ ] **Step 5: Write normalize.go tests + implement**

Finish reason mapping:
- `end_turn`/`stop` → `completed`
- `max_tokens` → `truncated`
- `content_filter` → `filtered`

- [ ] **Step 6: Run all AI package tests**

Run: `cd ennam.kg.go && go test ./internal/ai/... -v -race`

- [ ] **Step 7: Commit**

```bash
cd ennam.kg.go
git add internal/ai/client.go internal/ai/anthropic.go internal/ai/openai.go internal/ai/normalize.go \
        internal/ai/anthropic_test.go internal/ai/openai_test.go internal/ai/normalize_test.go
git commit -m "feat(ai): add Anthropic and OpenAI provider adapters with normalization (BA-009)"
```

---

## Task 7: Provider Selector (Priority + Failover + Budget)

**Files:**
- Create: `internal/ai/selector.go`
- Test: `internal/ai/selector_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- Selects highest-priority active provider
- Skips provider with open circuit breaker
- Skips pay-per-token provider with exhausted budget
- Falls back to next provider on failure
- Returns `503 SERVICE_UNAVAILABLE` when all providers exhausted
- Failover completes within 2 seconds (timeout test)
- Logs usage after successful request
- Increments budget after pay-per-token request

- [ ] **Step 2: Implement Selector**

```go
// internal/ai/selector.go
type Selector struct {
    providers      []ProviderEntry
    usageStore     *store.AIUsageStore
    budgetStore    *store.AIUsageStore
    logger         *slog.Logger
}

type ProviderEntry struct {
    Provider       Provider
    CircuitBreaker *CircuitBreaker
    ProviderModel  *models.AIProvider
}

func (s *Selector) Send(ctx context.Context, req *models.AIRequest) (*models.AIResponse, error) {
    for _, entry := range s.providers {
        // 1. Check is_active
        // 2. Check circuit breaker allows
        // 3. Check RPM not exceeded (sliding window)
        // 4. Check budget not exhausted (if pay-per-token)
        // 5. Send request
        // 6. On success: record success, log usage, increment budget
        // 7. On failure: record failure, try next
    }
    return nil, ErrAllProvidersUnavailable
}
```

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.go
git add internal/ai/selector.go internal/ai/selector_test.go
git commit -m "feat(ai): add priority-based provider selector with failover and budget check (BA-009)"
```

---

## Task 8: AI Provider Handler (REST Endpoints)

**Files:**
- Create: `internal/handler/ai_provider.go`
- Test: `internal/handler/ai_provider_test.go`

- [ ] **Step 1: Write failing tests for all 9 endpoints**

```go
// Endpoints:
// POST   /api/v1/ai-providers                → 201 Created
// GET    /api/v1/ai-providers                → 200 OK (list, API keys masked)
// GET    /api/v1/ai-providers/{id}           → 200 OK (detail)
// PATCH  /api/v1/ai-providers/{id}           → 200 OK (update)
// DELETE /api/v1/ai-providers/{id}           → 204 No Content (deactivate)
// POST   /api/v1/ai-providers/{id}/health-check → 200 OK (connectivity test)
// GET    /api/v1/ai-providers/{id}/usage-stats  → 200 OK (RPM, tokens, utilization)
// GET    /api/v1/ai-budget-stats             → 200 OK (all budgets + projections)
// POST   /api/v1/ai/request                  → 200 OK (normalized AI request)
```

- [ ] **Step 2: Implement AIProviderHandler**

```go
type AIProviderHandler struct {
    providerStore *store.AIProviderStore
    usageStore    *store.AIUsageStore
    selector      *ai.Selector
    encKey        []byte
    logger        *slog.Logger
}

func (h *AIProviderHandler) RegisterRoutes(mux *http.ServeMux) {
    mux.HandleFunc("POST /api/v1/ai-providers", h.Create)
    mux.HandleFunc("GET /api/v1/ai-providers", h.List)
    mux.HandleFunc("GET /api/v1/ai-providers/{id}", h.Get)
    mux.HandleFunc("PATCH /api/v1/ai-providers/{id}", h.Update)
    mux.HandleFunc("DELETE /api/v1/ai-providers/{id}", h.Deactivate)
    mux.HandleFunc("POST /api/v1/ai-providers/{id}/health-check", h.HealthCheck)
    mux.HandleFunc("GET /api/v1/ai-providers/{id}/usage-stats", h.UsageStats)
    mux.HandleFunc("GET /api/v1/ai-budget-stats", h.BudgetStats)
    mux.HandleFunc("POST /api/v1/ai/request", h.SendRequest)
}
```

- [ ] **Step 3: Run tests, verify pass**

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.go
git add internal/handler/ai_provider.go internal/handler/ai_provider_test.go
git commit -m "feat(handler): add AIProviderHandler with 9 REST endpoints (BA-009)"
```

---

## Task 9: AI Config Section

**Files:**
- Modify: `config/config.yaml`

- [ ] **Step 1: Add AI provider strategy config**

```yaml
# Add to config/config.yaml
ai:
  provider_strategy:
    selection: "priority"           # priority-based selection
    max_retries_per_provider: 1     # max retry per fallback provider
    failover_timeout_ms: 2000       # total failover budget: 2 seconds
    request_timeout_ms: 60000       # per-request timeout: 60 seconds
  circuit_breaker:
    failure_threshold: 3            # failures before opening
    failure_window_minutes: 5       # window for counting failures
    cooldown_seconds: 30            # wait before half-open probe
  budget:
    default_monthly_usd: 50000000   # $50 in microdollars
    alert_threshold_pct: 80         # alert at 80% budget
    hard_stop_pct: 100              # hard stop at 100%
  rate_limits:
    claude_max_rpm: 50
    claude_max_tpd: 1000000
```

- [ ] **Step 2: Commit**

```bash
cd ennam.kg.go
git add config/config.yaml
git commit -m "feat(config): add AI provider strategy, circuit breaker, and budget config (BA-009)"
```

---

## Task 10: Wire into Composition Root

**Files:**
- Modify: `cmd/kg-server/main.go`

- [ ] **Step 1: Add AI provider handlers to buildRouter()**

```go
// Register AI provider handlers (BA-009).
aiProviderStore := store.NewAIProviderStore(db)
aiUsageStore := store.NewAIUsageStore(db)

// Build provider selector from DB registry.
aiSelector := buildAISelector(aiProviderStore, aiUsageStore, encKey, appCfg, logger)

aiHandler := handler.NewAIProviderHandler(aiProviderStore, aiUsageStore, aiSelector, encKey, logger)
aiHandler.RegisterRoutes(apiMux)
```

Helper function `buildAISelector`:
1. Load active providers from DB
2. Decrypt API keys
3. Create provider adapters (Anthropic/OpenAI)
4. Create circuit breakers from config
5. Return `ai.Selector`

- [ ] **Step 2: Run full test suite**

Run: `cd ennam.kg.go && make test`

- [ ] **Step 3: Commit**

```bash
cd ennam.kg.go
git add cmd/kg-server/main.go
git commit -m "feat(server): wire AI provider handlers and selector into composition root (BA-009)"
```

---

## Task 11: Integration Test — Full AI Request Flow

**Files:**
- Create: `internal/ai/integration_test.go`

- [ ] **Step 1: Write end-to-end test**

Test flow:
1. POST /ai-providers → register Claude Max provider → 201
2. POST /ai-providers → register Anthropic API fallback → 201
3. GET /ai-providers → list (API keys masked) → 200
4. POST /ai-providers/{id}/health-check → verify connectivity → 200
5. POST /ai/request → send normalized request → 200 (via mock)
6. GET /ai-providers/{id}/usage-stats → verify usage logged → 200
7. GET /ai-budget-stats → verify budget tracking → 200
8. Simulate 3 failures → verify circuit breaker opens
9. Simulate failover to next provider
10. DELETE /ai-providers/{id} → deactivate → 204

- [ ] **Step 2: Run integration test**

Run: `cd ennam.kg.go && go test ./internal/ai/ -run TestAI_Integration -v -race`

- [ ] **Step 3: Commit**

```bash
cd ennam.kg.go
git add internal/ai/integration_test.go
git commit -m "test: add BA-009 AI provider integration test covering full request and failover flow"
```
