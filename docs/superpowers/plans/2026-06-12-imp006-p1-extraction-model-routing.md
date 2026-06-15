# IMP-006 P1 — Per-Function Model Routing for Ingestion Extraction (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin route the ingestion `extract_draft` AI call to a chosen model (incl. an OpenAI-compatible provider like BytePlus Ark) via the `ai.model.extraction` setting, so ingestion no longer hard-fails when the default Anthropic provider is out of credits.

**Architecture:** Add an `ai_models` registry table (one connection → many models). The Go AI selector gains an optional `ModelResolver`: when a request carries `RequestType` (e.g. `"extraction"`) and `ai.model.<RequestType>` points at an `ai_models` row, the selector dispatches to that row's owning `ai_providers` connection with the row's `model_id` (via a new optional `AIRequest.Model` override honored by the adapters), bypassing priority ranking; otherwise it falls back to the existing BA-009 priority selection. The Python ingestion client is updated to send `request_type = "extraction"`.

**Tech Stack:** Go (stdlib `database/sql`, `log/slog`, `net/http`), golang-migrate, PostgreSQL 16, Python 3.12 (pydantic, httpx), pytest, `go test -race`.

**Scope note:** This is **P1 only** of IMP-006 (`../../../ennam.kg.requirements/documents/improvements/IMP-006-multi-provider-per-function-model-selection.md`). It delivers extraction routing end-to-end. P2 (remaining Path-A functions + capability guard + `ai_models` CRUD API), P3 (dashboard UI), and P4 (agentic Path B) are separate plans. The `ai_models` capability flags (`supports_tools`/`supports_json`) are created here but the **capability guard is NOT enforced in P1** (extraction needs only JSON; guard lands in P2).

---

## File Structure

**ennam.kg.go (new):**
- `db/migrations/000057_create_ai_models.up.sql` / `.down.sql` — registry table + seed.
- `internal/models/ai_model.go` — `AIModel` struct.
- `internal/store/ai_model.go` — `AIModelStore` (Create, GetByID, ListByProvider).
- `internal/ai/resolver.go` — `ModelResolver` interface + `SettingsModelResolver` impl.
- `internal/service/model_resolver.go` — wiring of settings + stores into the resolver.

**ennam.kg.go (modify):**
- `internal/models/ai_provider.go` — add `Model string` field to `AIRequest`.
- `internal/ai/openai.go` — honor `req.Model`; fix completions URL for non-root `base_url`.
- `internal/ai/anthropic.go` — honor `req.Model`.
- `internal/ai/selector.go` — add `SetModelResolver` + resolve-before-priority dispatch in `Send`.
- `cmd/kg-server/main.go` — construct the resolver and call `selector.SetModelResolver(...)`.

**ennam.kg.python (modify):**
- `src/ennam_kg/ai_client/models.py` — add `request_type: str | None` to `AIRequest`, send it.
- `src/ennam_kg/ingestion/pipeline/extract.py` — pass `request_type="extraction"`.

---

## Task 1: `ai_models` migration

**Files:**
- Create: `ennam.kg.go/db/migrations/000057_create_ai_models.up.sql`
- Create: `ennam.kg.go/db/migrations/000057_create_ai_models.down.sql`

- [ ] **Step 1: Write the up migration**

Create `ennam.kg.go/db/migrations/000057_create_ai_models.up.sql`:

```sql
-- IMP-006 P1: selectable models under an ai_providers connection.
CREATE TABLE ai_models (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider_id     UUID NOT NULL REFERENCES ai_providers(id) ON DELETE CASCADE,
    model_id        TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    supports_tools  BOOLEAN NOT NULL DEFAULT false,
    supports_json   BOOLEAN NOT NULL DEFAULT true,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider_id, model_id)
);

CREATE INDEX idx_ai_models_provider ON ai_models(provider_id);

-- Seed: one ai_models row per existing connection's default model.
-- anthropic_api / claude_max support tools + json; others default conservatively.
INSERT INTO ai_models (provider_id, model_id, display_name, supports_tools, supports_json)
SELECT id, model_id, name,
       (provider_type IN ('anthropic_api', 'claude_max')),
       true
FROM ai_providers
WHERE model_id <> '';
```

- [ ] **Step 2: Write the down migration**

Create `ennam.kg.go/db/migrations/000057_create_ai_models.down.sql`:

```sql
DROP TABLE IF EXISTS ai_models;
```

- [ ] **Step 3: Apply + verify the migration**

Run (Docker stack must be up):
```bash
cd ennam.kg.go && go run ./cmd/kg-migrate/ up
docker exec ennam-kg-postgres psql -U ennam_kg -d ennam_kg -c "\d ai_models"
docker exec ennam-kg-postgres psql -U ennam_kg -d ennam_kg -c "SELECT model_id, display_name, supports_tools FROM ai_models;"
```
Expected: table exists; one seeded row per existing provider (e.g. `claude-haiku-4-5 | anthropic-haiku-default | t`).

- [ ] **Step 4: Commit**

```bash
git add db/migrations/000057_create_ai_models.up.sql db/migrations/000057_create_ai_models.down.sql
git commit -m "feat(ai): ai_models registry table + seed from ai_providers (IMP-006 P1)"
```

---

## Task 2: `AIModel` model + store

**Files:**
- Create: `ennam.kg.go/internal/models/ai_model.go`
- Create: `ennam.kg.go/internal/store/ai_model.go`
- Test: `ennam.kg.go/internal/store/ai_model_test.go`

- [ ] **Step 1: Write the model struct**

Create `ennam.kg.go/internal/models/ai_model.go`:

```go
package models

import "time"

// AIModel is one selectable model under an ai_providers connection (IMP-006).
type AIModel struct {
	ID            string    `json:"id" db:"id"`
	ProviderID    string    `json:"provider_id" db:"provider_id"`
	ModelID       string    `json:"model_id" db:"model_id"`
	DisplayName   string    `json:"display_name" db:"display_name"`
	SupportsTools bool      `json:"supports_tools" db:"supports_tools"`
	SupportsJSON  bool      `json:"supports_json" db:"supports_json"`
	IsActive      bool      `json:"is_active" db:"is_active"`
	CreatedAt     time.Time `json:"created_at" db:"created_at"`
	UpdatedAt     time.Time `json:"updated_at" db:"updated_at"`
}
```

- [ ] **Step 2: Write the failing store test**

Create `ennam.kg.go/internal/store/ai_model_test.go`. This mirrors the nil-DB guard style used elsewhere in the package; it asserts the constructor wires the DB and `GetByID` errors cleanly on a nil DB (no panic):

```go
package store

import (
	"context"
	"testing"
)

func TestNewAIModelStore_NotNil(t *testing.T) {
	if NewAIModelStore(nil) == nil {
		t.Fatal("NewAIModelStore returned nil")
	}
}

func TestAIModelStore_GetByID_NilDB(t *testing.T) {
	s := NewAIModelStore(nil)
	if _, err := s.GetByID(context.Background(), "00000000-0000-0000-0000-000000000000"); err == nil {
		t.Fatal("expected error on nil DB, got nil")
	}
}
```

- [ ] **Step 2b: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestAIModelStore_GetByID_NilDB -v`
Expected: FAIL — `NewAIModelStore`/`GetByID` undefined (does not compile).

- [ ] **Step 3: Write the store**

Create `ennam.kg.go/internal/store/ai_model.go` (mirrors `ai_provider.go` patterns):

```go
package store

import (
	"context"
	"database/sql"
	"fmt"

	"github.com/ennam/ennam-kg/internal/models"
)

// AIModelStore manages selectable models registered under ai_providers (IMP-006).
type AIModelStore struct {
	db *sql.DB
}

// NewAIModelStore creates an AIModelStore.
func NewAIModelStore(db *sql.DB) *AIModelStore {
	return &AIModelStore{db: db}
}

const aiModelColumns = `id, provider_id, model_id, display_name,
	supports_tools, supports_json, is_active, created_at, updated_at`

func scanAIModel(row interface{ Scan(...any) error }) (*models.AIModel, error) {
	m := &models.AIModel{}
	if err := row.Scan(
		&m.ID, &m.ProviderID, &m.ModelID, &m.DisplayName,
		&m.SupportsTools, &m.SupportsJSON, &m.IsActive, &m.CreatedAt, &m.UpdatedAt,
	); err != nil {
		return nil, err
	}
	return m, nil
}

// Create inserts a new model and fills generated fields.
func (s *AIModelStore) Create(ctx context.Context, m *models.AIModel) error {
	if s.db == nil {
		return fmt.Errorf("Create: nil database")
	}
	query := `
		INSERT INTO ai_models (provider_id, model_id, display_name, supports_tools, supports_json, is_active)
		VALUES ($1, $2, $3, $4, $5, $6)
		RETURNING id, created_at, updated_at`
	return s.db.QueryRowContext(ctx, query,
		m.ProviderID, m.ModelID, m.DisplayName, m.SupportsTools, m.SupportsJSON, m.IsActive,
	).Scan(&m.ID, &m.CreatedAt, &m.UpdatedAt)
}

// GetByID returns a model by its UUID.
func (s *AIModelStore) GetByID(ctx context.Context, id string) (*models.AIModel, error) {
	if s.db == nil {
		return nil, fmt.Errorf("GetByID: nil database")
	}
	query := `SELECT ` + aiModelColumns + ` FROM ai_models WHERE id = $1`
	m, err := scanAIModel(s.db.QueryRowContext(ctx, query, id))
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("ai model %q not found", id)
		}
		return nil, fmt.Errorf("get ai model: %w", err)
	}
	return m, nil
}

// ListByProvider returns all models for a connection, active first.
func (s *AIModelStore) ListByProvider(ctx context.Context, providerID string) ([]*models.AIModel, error) {
	if s.db == nil {
		return nil, fmt.Errorf("ListByProvider: nil database")
	}
	query := `SELECT ` + aiModelColumns + ` FROM ai_models WHERE provider_id = $1 ORDER BY is_active DESC, model_id`
	rows, err := s.db.QueryContext(ctx, query, providerID)
	if err != nil {
		return nil, fmt.Errorf("list ai models: %w", err)
	}
	defer rows.Close()
	out := make([]*models.AIModel, 0)
	for rows.Next() {
		m, err := scanAIModel(rows)
		if err != nil {
			return nil, fmt.Errorf("scan ai model: %w", err)
		}
		out = append(out, m)
	}
	return out, rows.Err()
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestAIModel -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add internal/models/ai_model.go internal/store/ai_model.go internal/store/ai_model_test.go
git commit -m "feat(ai): AIModel model + AIModelStore (IMP-006 P1)"
```

---

## Task 3: `AIRequest.Model` override + OpenAI adapter (honor model + URL fix)

**Files:**
- Modify: `ennam.kg.go/internal/models/ai_provider.go` (AIRequest struct, ~line 120)
- Modify: `ennam.kg.go/internal/ai/openai.go` (Send: model + URL)
- Test: `ennam.kg.go/internal/ai/openai_test.go` (add cases)

- [ ] **Step 1: Add the `Model` field to `AIRequest`**

In `ennam.kg.go/internal/models/ai_provider.go`, the `AIRequest` struct (line ~120) currently is:

```go
type AIRequest struct {
	Messages    []AIMessage `json:"messages"`
	MaxTokens   int         `json:"max_tokens"`
	Temperature *float64    `json:"temperature,omitempty"`
	System      string      `json:"system,omitempty"`
	RequestType string      `json:"request_type"`
}
```

Add a `Model` field (optional per-request model override; empty = use the provider's default):

```go
type AIRequest struct {
	Messages    []AIMessage `json:"messages"`
	MaxTokens   int         `json:"max_tokens"`
	Temperature *float64    `json:"temperature,omitempty"`
	System      string      `json:"system,omitempty"`
	RequestType string      `json:"request_type"`
	// Model, when non-empty, overrides the provider's configured model for this
	// request (IMP-006 per-function routing). Set by the selector after resolving
	// ai.model.<RequestType>; not part of the public proxy contract.
	Model string `json:"-"`
}
```

- [ ] **Step 2: Write a failing test for the OpenAI URL + model override**

Add to `ennam.kg.go/internal/ai/openai_test.go` (a roundtrip test against an `httptest` server that captures the request path + body model):

```go
func TestOpenAIProvider_HonorsModelOverride_AndBaseURLPath(t *testing.T) {
	var gotPath, gotModel string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		var body struct {
			Model string `json:"model"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		gotModel = body.Model
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":1}}`))
	}))
	defer srv.Close()

	// base_url already includes an /api/v3 segment (BytePlus-style) — must NOT get /v1 appended.
	p := NewOpenAIProvider("p1", srv.URL+"/api/v3", "key", "default-model", 5*time.Second)
	req := &models.AIRequest{
		Messages: []models.AIMessage{{Role: "user", Content: "hi"}},
		Model:    "glm-4.7",
	}
	if _, err := p.Send(context.Background(), req); err != nil {
		t.Fatalf("Send: %v", err)
	}
	if gotPath != "/api/v3/chat/completions" {
		t.Errorf("path = %q, want /api/v3/chat/completions", gotPath)
	}
	if gotModel != "glm-4.7" {
		t.Errorf("model = %q, want glm-4.7 (req.Model override)", gotModel)
	}
}
```

Ensure the test file imports `context`, `encoding/json`, `net/http`, `net/http/httptest`, `testing`, `time`, and `github.com/ennam/ennam-kg/internal/models`.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/ai/ -run TestOpenAIProvider_HonorsModelOverride_AndBaseURLPath -v`
Expected: FAIL — path is `/api/v3/v1/chat/completions` and model is `default-model`.

- [ ] **Step 4: Fix the OpenAI adapter**

In `ennam.kg.go/internal/ai/openai.go` `Send`, change the model selection and the URL build.

Replace the model line:
```go
	or := openaiRequest{
		Model:       p.modelID,
		MaxTokens:   req.MaxTokens,
		Temperature: req.Temperature,
	}
```
with:
```go
	model := p.modelID
	if req.Model != "" {
		model = req.Model
	}
	or := openaiRequest{
		Model:       model,
		MaxTokens:   req.MaxTokens,
		Temperature: req.Temperature,
	}
```

Replace the URL line:
```go
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, p.baseURL+"/v1/chat/completions", bytes.NewReader(body))
```
with:
```go
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, openAICompletionsURL(p.baseURL), bytes.NewReader(body))
```

Add this helper at the bottom of `openai.go` (above or below `Send`):
```go
// openAICompletionsURL builds the chat-completions URL. If base_url already ends
// in a version segment (e.g. ".../v1", ".../v3", ".../coding/v3"), only append
// "/chat/completions"; otherwise assume a host root and append "/v1/chat/completions".
func openAICompletionsURL(baseURL string) string {
	trimmed := strings.TrimRight(baseURL, "/")
	last := trimmed[strings.LastIndex(trimmed, "/")+1:]
	if len(last) >= 2 && last[0] == 'v' && last[1] >= '0' && last[1] <= '9' {
		return trimmed + "/chat/completions"
	}
	return trimmed + "/v1/chat/completions"
}
```
Add `"strings"` to the `openai.go` imports.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/ai/ -run TestOpenAIProvider_HonorsModelOverride_AndBaseURLPath -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add internal/models/ai_provider.go internal/ai/openai.go internal/ai/openai_test.go
git commit -m "feat(ai): AIRequest.Model override + OpenAI adapter honors it and fixes completions URL (IMP-006 P1)"
```

---

## Task 4: Anthropic adapter honors `req.Model`

**Files:**
- Modify: `ennam.kg.go/internal/ai/anthropic.go` (Send body build, ~line 103)
- Test: `ennam.kg.go/internal/ai/anthropic_test.go`

- [ ] **Step 1: Write the failing test**

Add to `ennam.kg.go/internal/ai/anthropic_test.go`:

```go
func TestAnthropicProvider_HonorsModelOverride(t *testing.T) {
	var gotModel string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Model string `json:"model"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		gotModel = body.Model
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"content":[{"type":"text","text":"ok"}],"stop_reason":"end_turn","usage":{"input_tokens":1,"output_tokens":1}}`))
	}))
	defer srv.Close()

	p := NewAnthropicProvider("a1", models.ProviderTypeAnthropicAPI, srv.URL, "key", "default-model", 5*time.Second)
	req := &models.AIRequest{Messages: []models.AIMessage{{Role: "user", Content: "hi"}}, Model: "claude-haiku-4-5"}
	if _, err := p.Send(context.Background(), req); err != nil {
		t.Fatalf("Send: %v", err)
	}
	if gotModel != "claude-haiku-4-5" {
		t.Errorf("model = %q, want claude-haiku-4-5", gotModel)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/ai/ -run TestAnthropicProvider_HonorsModelOverride -v`
Expected: FAIL — model is `default-model`.

- [ ] **Step 3: Fix the Anthropic adapter**

In `ennam.kg.go/internal/ai/anthropic.go` `Send`, the request body currently sets `Model: p.modelID` (~line 103). Replace:
```go
		Model:       p.modelID,
```
with:
```go
		Model:       pickModel(p.modelID, req.Model),
```
and add this helper at the bottom of `anthropic.go`:
```go
// pickModel returns override when non-empty, else the provider default.
func pickModel(def, override string) string {
	if override != "" {
		return override
	}
	return def
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/ai/ -run TestAnthropicProvider_HonorsModelOverride -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/ai/anthropic.go internal/ai/anthropic_test.go
git commit -m "feat(ai): Anthropic adapter honors AIRequest.Model override (IMP-006 P1)"
```

---

## Task 5: `ModelResolver` interface + settings-backed implementation

**Files:**
- Create: `ennam.kg.go/internal/ai/resolver.go`
- Create: `ennam.kg.go/internal/service/model_resolver.go`
- Test: `ennam.kg.go/internal/service/model_resolver_test.go`

- [ ] **Step 1: Define the resolver interface (in the `ai` package, used by the selector)**

Create `ennam.kg.go/internal/ai/resolver.go`:

```go
package ai

import "context"

// ModelResolved is the outcome of resolving ai.model.<requestType>.
type ModelResolved struct {
	ProviderID string // ai_providers.id that owns the model
	ModelID    string // wire model id to send (ai_models.model_id)
}

// ModelResolver maps a request type (e.g. "extraction") to a specific
// connection + model, per IMP-006 ai.model.<requestType> settings. It returns
// ok=false when there is no usable assignment (unset, "auto", dangling, or
// inactive), in which case the selector falls back to priority selection.
type ModelResolver interface {
	Resolve(ctx context.Context, requestType string) (ModelResolved, bool)
}
```

- [ ] **Step 2: Write the failing test for the settings-backed resolver**

Create `ennam.kg.go/internal/service/model_resolver_test.go`. It uses small fakes for the settings reader and the model lookup so it has no DB dependency:

```go
package service

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/ennam/ennam-kg/internal/models"
)

type fakeSettingGetter struct{ vals map[string]string }

func (f fakeSettingGetter) Get(_ context.Context, key string) (*models.SystemSetting, error) {
	v, ok := f.vals[key]
	if !ok {
		return nil, errNoSetting
	}
	raw, _ := json.Marshal(v)
	return &models.SystemSetting{Key: key, Value: raw}, nil
}

type fakeModelGetter struct{ m map[string]*models.AIModel }

func (f fakeModelGetter) GetByID(_ context.Context, id string) (*models.AIModel, error) {
	if mm, ok := f.m[id]; ok {
		return mm, nil
	}
	return nil, errNoSetting
}

func TestSettingsModelResolver(t *testing.T) {
	active := &models.AIModel{ID: "m1", ProviderID: "p1", ModelID: "gpt-oss-120b", IsActive: true}
	inactive := &models.AIModel{ID: "m2", ProviderID: "p1", ModelID: "old", IsActive: false}
	r := NewSettingsModelResolver(
		fakeSettingGetter{vals: map[string]string{
			"ai.model.extraction": "m1",
			"ai.model.table_filter": "auto",
			"ai.model.sql_generation": "m2",
		}},
		fakeModelGetter{m: map[string]*models.AIModel{"m1": active, "m2": inactive}},
	)

	tests := []struct {
		name        string
		requestType string
		wantOK      bool
		wantModel   string
	}{
		{"assigned active model", "extraction", true, "gpt-oss-120b"},
		{"explicit auto", "table_filter", false, ""},
		{"unset setting", "sql_verification", false, ""},
		{"empty request type", "", false, ""},
		{"inactive model -> fallback", "sql_generation", false, ""},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, ok := r.Resolve(context.Background(), tt.requestType)
			if ok != tt.wantOK {
				t.Fatalf("ok = %v, want %v", ok, tt.wantOK)
			}
			if ok && got.ModelID != tt.wantModel {
				t.Errorf("model = %q, want %q", got.ModelID, tt.wantModel)
			}
		})
	}
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/service/ -run TestSettingsModelResolver -v`
Expected: FAIL — `NewSettingsModelResolver`, `errNoSetting` undefined.

- [ ] **Step 4: Write the resolver implementation**

Create `ennam.kg.go/internal/service/model_resolver.go`:

```go
package service

import (
	"context"
	"encoding/json"
	"errors"
	"strings"

	"github.com/ennam/ennam-kg/internal/ai"
	"github.com/ennam/ennam-kg/internal/models"
)

// errNoSetting is a sentinel for "no such setting / model" in tests and lookups.
var errNoSetting = errors.New("not found")

// settingGetter reads a single system setting by key (satisfied by *SettingsService).
type settingGetter interface {
	Get(ctx context.Context, key string) (*models.SystemSetting, error)
}

// modelGetter loads an ai_models row by id (satisfied by *store.AIModelStore).
type modelGetter interface {
	GetByID(ctx context.Context, id string) (*models.AIModel, error)
}

// SettingsModelResolver resolves ai.model.<requestType> -> (provider, model)
// using system settings + the ai_models registry. Implements ai.ModelResolver.
type SettingsModelResolver struct {
	settings settingGetter
	modelsDB modelGetter
}

// NewSettingsModelResolver constructs the resolver.
func NewSettingsModelResolver(settings settingGetter, modelsDB modelGetter) *SettingsModelResolver {
	return &SettingsModelResolver{settings: settings, modelsDB: modelsDB}
}

// Resolve returns the assigned (provider, model) for a request type, or ok=false
// to defer to priority selection.
func (r *SettingsModelResolver) Resolve(ctx context.Context, requestType string) (ai.ModelResolved, bool) {
	if requestType == "" {
		return ai.ModelResolved{}, false
	}
	setting, err := r.settings.Get(ctx, "ai.model."+requestType)
	if err != nil || setting == nil {
		return ai.ModelResolved{}, false
	}
	var modelUUID string
	if err := json.Unmarshal(setting.Value, &modelUUID); err != nil {
		return ai.ModelResolved{}, false
	}
	modelUUID = strings.TrimSpace(modelUUID)
	if modelUUID == "" || modelUUID == "auto" {
		return ai.ModelResolved{}, false
	}
	m, err := r.modelsDB.GetByID(ctx, modelUUID)
	if err != nil || m == nil || !m.IsActive {
		return ai.ModelResolved{}, false
	}
	return ai.ModelResolved{ProviderID: m.ProviderID, ModelID: m.ModelID}, true
}
```

> Note: the `request_type` strings the platform sends (e.g. legacy `"json"` from `response_format`) that have no `ai.model.<rt>` setting simply resolve to `ok=false` and fall back to priority — safe.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/service/ -run TestSettingsModelResolver -v`
Expected: PASS (all sub-cases).

- [ ] **Step 6: Commit**

```bash
git add internal/ai/resolver.go internal/service/model_resolver.go internal/service/model_resolver_test.go
git commit -m "feat(ai): ModelResolver + settings-backed resolver for ai.model.<requestType> (IMP-006 P1)"
```

---

## Task 6: Selector resolves model before priority selection

**Files:**
- Modify: `ennam.kg.go/internal/ai/selector.go` (add field + setter + dispatch branch in `Send`)
- Test: `ennam.kg.go/internal/ai/selector_resolve_test.go`

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/ai/selector_resolve_test.go`. It builds a selector with two entries and a stub resolver, and asserts the resolved provider handles the request (not the priority-first one), with `req.Model` set:

```go
package ai

import (
	"context"
	"testing"
	"time"

	"github.com/ennam/ennam-kg/internal/models"
)

type stubProvider struct {
	id        string
	gotModel  string
	respText  string
}

func (s *stubProvider) ProviderID() string   { return s.id }
func (s *stubProvider) ProviderType() string { return "openai" }
func (s *stubProvider) Send(_ context.Context, req *models.AIRequest) (*models.AIResponse, error) {
	s.gotModel = req.Model
	return &models.AIResponse{Content: s.respText, ProviderID: s.id}, nil
}

type stubResolver struct {
	out ModelResolved
	ok  bool
}

func (r stubResolver) Resolve(_ context.Context, _ string) (ModelResolved, bool) { return r.out, r.ok }

func newTestEntry(id string, priority int, p Provider) ProviderEntry {
	return ProviderEntry{
		Provider:       p,
		CircuitBreaker: NewCircuitBreaker(3, 5*time.Minute, 30*time.Second), // (threshold, window, cooldown)
		Model:          &models.AIProvider{ID: id, ProviderType: "openai", Priority: priority, IsActive: true, Status: "healthy"},
	}
}

func TestSelector_ResolvesToAssignedProvider(t *testing.T) {
	prio := &stubProvider{id: "prio", respText: "from-priority"}
	target := &stubProvider{id: "target", respText: "from-target"}
	sel := NewSelector(
		[]ProviderEntry{newTestEntry("prio", 1, prio), newTestEntry("target", 9, target)},
		nil, nil, time.Second, time.Second,
	)
	sel.SetModelResolver(stubResolver{out: ModelResolved{ProviderID: "target", ModelID: "glm-4.7"}, ok: true})

	resp, err := sel.Send(context.Background(), &models.AIRequest{
		Messages:    []models.AIMessage{{Role: "user", Content: "hi"}},
		RequestType: "extraction",
	})
	if err != nil {
		t.Fatalf("Send: %v", err)
	}
	if resp.Content != "from-target" {
		t.Errorf("served by %q, want target", resp.Content)
	}
	if target.gotModel != "glm-4.7" {
		t.Errorf("target got model %q, want glm-4.7", target.gotModel)
	}
}
```

> Confirm against `selector.go` the exact field name on `ProviderEntry` for the circuit breaker and the `NewCircuitBreaker` signature (`internal/ai/circuitbreaker.go`); adjust `newTestEntry` to match. The `Model.Status`/`IsActive` fields must satisfy the availability checks in `Send` so the priority path would otherwise pick `prio` first.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/ai/ -run TestSelector_ResolvesToAssignedProvider -v`
Expected: FAIL — `SetModelResolver` undefined.

- [ ] **Step 3: Add the resolver field + setter + dispatch branch**

In `ennam.kg.go/internal/ai/selector.go`:

**(a)** Add a field to the `Selector` struct (next to `oauthProvider`):
```go
	modelResolver   ModelResolver // optional — IMP-006 per-function model routing
```

**(b)** Add a setter (mirrors `SetOAuthProvider`, which uses `s.mu.Lock()`):
```go
// SetModelResolver sets an optional per-request model resolver (IMP-006). When
// set and a request's RequestType maps to an active assigned model, the selector
// dispatches to that model's connection instead of priority ranking.
func (s *Selector) SetModelResolver(r ModelResolver) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.modelResolver = r
}
```

**(c)** `Send` already snapshots state under `s.mu.RLock()` into a local `entries := make(...; copy(...))` block (around lines 101–105, where it also reads `oauthProvider := s.oauthProvider`). **Inside that same RLock block**, also capture the resolver:
```go
	resolver := s.modelResolver
```

**(d)** Immediately **after** that snapshot block (before the priority loop), insert the resolve branch — it iterates the local `entries` snapshot (no extra locking), so it is race-free:
```go
	// IMP-006: if a per-function model is assigned and its connection is usable,
	// dispatch there directly (skipping priority). On any failure, fall through
	// to the priority loop below.
	if resolver != nil && req.RequestType != "" {
		if resolved, ok := resolver.Resolve(ctx, req.RequestType); ok {
			for i := range entries {
				e := &entries[i]
				if e.Model == nil || e.Model.ID != resolved.ProviderID {
					continue
				}
				if !e.CircuitBreaker.Allow() {
					break
				}
				routed := *req
				routed.Model = resolved.ModelID
				reqCtx, cancel := context.WithTimeout(ctx, s.requestTimeout)
				resp, err := e.Provider.Send(reqCtx, &routed)
				cancel()
				if err == nil {
					e.CircuitBreaker.RecordSuccess()
					s.logger.InfoContext(ctx, "ai: routed by assignment",
						"request_type", req.RequestType, "provider", resolved.ProviderID, "model", resolved.ModelID)
					return resp, nil
				}
				e.CircuitBreaker.RecordFailure()
				s.logger.WarnContext(ctx, "ai: assigned model failed, falling back to priority",
					"request_type", req.RequestType, "provider", resolved.ProviderID, "error", err)
				break
			}
		}
	}
```
> `CircuitBreaker.Allow()/RecordSuccess()/RecordFailure()` are the real method names (`internal/ai/circuitbreaker.go`); the priority loop below uses the same calls — keep them identical. No new helper functions are needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/ai/ -run TestSelector_ResolvesToAssignedProvider -race -v`
Expected: PASS.

- [ ] **Step 5: Run the whole ai package to catch regressions**

Run: `cd ennam.kg.go && go test ./internal/ai/ -race`
Expected: PASS (all existing selector/provider tests still green).

- [ ] **Step 6: Commit**

```bash
git add internal/ai/selector.go internal/ai/selector_resolve_test.go
git commit -m "feat(ai): selector routes to assigned model before priority (IMP-006 P1)"
```

---

## Task 7: Wire the resolver into the server

**Files:**
- Modify: `ennam.kg.go/cmd/kg-server/main.go` (where the selector is constructed)

- [ ] **Step 1: Construct the resolver and attach it**

In `ennam.kg.go/cmd/kg-server/main.go`, after the `*ai.Selector` is constructed (search for `ai.NewSelector(`) and after the `SettingsService` and stores are available, add:

```go
	aiModelStore := store.NewAIModelStore(db)
	modelResolver := service.NewSettingsModelResolver(settingsService, aiModelStore)
	selector.SetModelResolver(modelResolver)
```
> Use the existing variable names for the DB handle (`db`), the settings service, and the selector as they appear in `main.go`. Place this after both are initialized. `*service.SettingsService` already has `Get(ctx, key)`; `*store.AIModelStore` already has `GetByID` — both satisfy the resolver's interfaces.

- [ ] **Step 2: Build the server**

Run: `cd ennam.kg.go && go build ./...`
Expected: builds with no errors.

- [ ] **Step 3: Run the full Go test suite**

Run: `cd ennam.kg.go && go test ./... 2>&1 | grep -E "FAIL|ok" | tail -20`
Expected: no `FAIL` lines.

- [ ] **Step 4: Commit**

```bash
git add cmd/kg-server/main.go
git commit -m "feat(ai): wire SettingsModelResolver into the selector at startup (IMP-006 P1)"
```

---

## Task 8: Python ingestion sends `request_type="extraction"`

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ai_client/models.py` (AIRequest)
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/pipeline/extract.py` (extract_draft call)
- Test: `ennam.kg.python/tests/test_ai_client_request_type.py`

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.python/tests/test_ai_client_request_type.py`:

```python
from ennam_kg.ai_client.models import AIRequest


def test_request_type_is_sent_when_set():
    req = AIRequest(prompt="x", request_type="extraction", response_format="json")
    payload = req.to_go_payload()
    assert payload["request_type"] == "extraction"


def test_request_type_absent_keeps_payload_clean():
    req = AIRequest(prompt="x")
    payload = req.to_go_payload()
    assert "request_type" not in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_ai_client_request_type.py -q`
Expected: FAIL — `AIRequest` has no `request_type`; and currently `to_go_payload` sets `request_type` to `response_format` ("json"), so the first assertion fails.

- [ ] **Step 3: Update the `AIRequest` model**

In `ennam.kg.python/src/ennam_kg/ai_client/models.py`, add a `request_type` field and stop conflating it with `response_format`:

```python
    prompt: str
    max_tokens: int = 1000
    system_prompt: str | None = None
    temperature: float = 0.0
    response_format: str | None = None  # "json" or None for plain text
    request_type: str | None = None  # IMP-006 function tag, e.g. "extraction"

    def to_go_payload(self) -> dict:
        """Convert to Go API /api/v1/ai/request JSON body."""
        payload: dict = {
            "messages": [{"role": "user", "content": self.prompt}],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if self.system_prompt:
            payload["system"] = self.system_prompt
        if self.request_type:
            payload["request_type"] = self.request_type
        return payload
```

> Note: `response_format` is no longer mapped to `request_type` (it was a conflation). The Go proxy ignores unknown fields, and JSON-mode behavior for extraction is driven by the prompt + `_EXTRACT_SYSTEM`, not this field — so dropping it from the payload is safe.

- [ ] **Step 4: Set `request_type="extraction"` at the extract call site**

In `ennam.kg.python/src/ennam_kg/ingestion/pipeline/extract.py`, the `extract_draft` function builds an `AIRequest` (~line 110). Add `request_type="extraction"`:

```python
    response = await ai_client.complete(
        AIRequest(
            prompt=prompt,
            system_prompt=_EXTRACT_SYSTEM,
            max_tokens=1500,
            temperature=0.0,
            response_format="json",
            request_type="extraction",
        )
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ennam.kg.python && uv run pytest tests/test_ai_client_request_type.py -q`
Expected: PASS.

- [ ] **Step 6: Run the ingestion + ai_client tests for regressions**

Run: `cd ennam.kg.python && uv run pytest tests/ -k "extract or ai_client or ingestion" -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/ennam_kg/ai_client/models.py src/ennam_kg/ingestion/pipeline/extract.py tests/test_ai_client_request_type.py
git commit -m "feat(ingestion): send request_type=extraction so Go routes ai.model.extraction (IMP-006 P1)"
```

---

## Task 9: Live acceptance (manual — needs a real OpenAI-compatible key)

**Goal:** Prove extraction routes to a non-Anthropic model end-to-end. Requires a real key for an OpenAI-compatible endpoint (e.g. BytePlus Ark). Do this against the running Docker stack.

- [ ] **Step 1: Register the OpenAI-compatible connection + its model**

```bash
# Register the connection (provider_type=openai, base_url already includes /api/coding/v3).
curl -s -X POST http://localhost:8080/api/v1/ai-providers \
  -H "Authorization: Bearer ennam_kg_dev_000000000000000000000000" -H "Content-Type: application/json" \
  -d '{"name":"byteplus-ark","provider_type":"openai","base_url":"https://ark.ap-southeast.bytepluses.com/api/coding/v3","api_key":"<BYTEPLUS_KEY>","model_id":"gpt-oss-120b","priority":50}'
```
Then find the new provider id and its seeded `ai_models.id`:
```bash
docker exec ennam-kg-postgres psql -U ennam_kg -d ennam_kg -tAc \
  "SELECT m.id, m.model_id, p.name FROM ai_models m JOIN ai_providers p ON p.id=m.provider_id WHERE p.name='byteplus-ark';"
```
> The provider create path seeds an `ai_models` row only if Task 1's migration trigger logic also runs on insert. Migration 000057 seeds existing rows once; **for newly-created providers, insert the `ai_models` row** (P2 adds this to the create endpoint). For P1 acceptance, insert it manually if absent:
> ```bash
> docker exec ennam-kg-postgres psql -U ennam_kg -d ennam_kg -c \
>   "INSERT INTO ai_models (provider_id, model_id, display_name) SELECT id, model_id, name FROM ai_providers WHERE name='byteplus-ark' ON CONFLICT DO NOTHING;"
> ```

- [ ] **Step 2: Assign the model to extraction**

```bash
curl -s -X PUT "http://localhost:8080/api/v1/settings/ai.model.extraction" \
  -H "Authorization: Bearer ennam_kg_dev_000000000000000000000000" -H "Content-Type: application/json" \
  -d '{"value":"<AI_MODELS_ID>","category":"ai"}'
```
> Confirm the exact settings update endpoint + body shape against `internal/handler` (the `SettingsService.Set` signature is `Set(ctx, key, value json.RawMessage, category, description, updatedBy)`). Adjust the path/body to the real route.

- [ ] **Step 3: Ingest a draft and confirm it processes via BytePlus**

Use the HTTP MCP (or REST) to ingest a node into a project, then verify the draft reaches `processed` (not `failed`) and the server log shows the routed provider:
```bash
docker compose logs --tail 40 kg-server | grep "routed by assignment"
docker exec ennam-kg-postgres psql -U ennam_kg -d ennam_kg -tAc \
  "SELECT status FROM draft_nodes ORDER BY created_at DESC LIMIT 1;"
```
Expected: log line `ai: routed by assignment ... provider=<byteplus> model=gpt-oss-120b`; draft status `processed`. (This satisfies IMP-006 Acceptance Criterion 2.)

- [ ] **Step 4: Negative check — `auto` falls back**

Set the setting back to `auto` and confirm extraction uses priority selection again:
```bash
curl -s -X PUT "http://localhost:8080/api/v1/settings/ai.model.extraction" \
  -H "Authorization: Bearer ennam_kg_dev_000000000000000000000000" -H "Content-Type: application/json" \
  -d '{"value":"auto","category":"ai"}'
```
Expected: next extraction does NOT log "routed by assignment" and uses the priority-ranked provider.

---

## Done criteria (P1)

- `ai_models` table exists + seeded; `go test ./...` green; `go build ./...` clean.
- Setting `ai.model.extraction` → an active `ai_models.id` routes the extraction request to that connection+model; `auto`/unset/inactive/unknown falls back to priority (logged).
- OpenAI adapter targets the correct completions URL for both host-root and versioned base_urls, and honors `req.Model`.
- Python ingestion sends `request_type="extraction"`.
- Live: ingestion completes on a non-Anthropic model with the Anthropic provider unusable (Acceptance Criterion 2).

**Not in P1 (later plans):** `ai_models` CRUD API + auto-seed on provider create (P2), capability guard (P2), other Path-A functions (P2), dashboard UI (P3), agentic Path B (P4).
```
