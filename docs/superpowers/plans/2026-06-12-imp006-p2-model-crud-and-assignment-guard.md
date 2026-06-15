# IMP-006 P2 — AI-Model CRUD, Auto-Seed & Assignment Guard (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make per-function model assignment safe and manageable: a registry of the real AI functions, full CRUD for the models under a provider connection, auto-seeding an `ai_models` row when a provider is registered, and a guard that rejects assigning a non-existent/incapable model (or an unknown function) to an `ai.model.<function>` setting.

**Architecture:** P1 already routes every function through the Go selector via `ai.model.<RequestType>` (all call sites already set `RequestType`). P2 adds the management + safety layer on top of P1's `ai_models` table: a static `models.AIFunction` registry keyed by the real RequestType strings; `AIModelStore.Update`/`Delete`; `ai_models` REST endpoints + auto-seed on provider create (both on `AIProviderHandler` via an optional `modelStore`); and a capability/assignment guard in the settings `PUT` handler (via an optional `aiModelStore`). All new dependencies are wired with optional setters (matching the existing `SetRebuildSelector`/`SetOAuthService` pattern) so constructors are unchanged.

**Tech Stack:** Go (stdlib `database/sql`, `net/http`, `log/slog`), PostgreSQL 16, `go test -race`.

**Builds on P1** (`docs/superpowers/plans/2026-06-12-imp006-p1-extraction-model-routing.md`, merged): `ai_models` table (migration 000057), `models.AIModel`, `store.AIModelStore{Create,GetByID,ListByProvider}`, `ai.ModelResolver`/`SettingsModelResolver`, `AIRequest.Model`. **Scope:** Path-A functions only. Agentic (Path B / `ai.model.agentic`) is **P4**; its `RequiresTools` guard is encoded in the registry now but no agentic function is registered yet. Dashboard UI is **P3**.

**Real function set (verified in code):** `extraction`, `nl_query_intent`, `sql_verification`, `table_filter`, `kg_implicit_scoring` (JSON output); `kg_description`, `embedding_description` (plain-text output).

---

## File Structure

**Create:**
- `ennam.kg.go/internal/models/ai_function.go` — `AIFunction` registry + `LookupAIFunction`.

**Modify:**
- `ennam.kg.go/internal/store/ai_model.go` — add `Update`, `Delete`.
- `ennam.kg.go/internal/handler/ai_provider.go` — add `modelStore` + `SetModelStore`; auto-seed in `Create`; add `ListModels`/`AddModel`/`UpdateModel`/`DeleteModel` + routes.
- `ennam.kg.go/internal/handler/settings.go` — add `aiModelStore` + `SetAIModelStore`; validate `ai.model.*` assignments in `HandleUpdateSetting`.
- `ennam.kg.go/cmd/kg-server/main.go` — wire `SetModelStore` + `SetAIModelStore`.

**Test:**
- `ennam.kg.go/internal/models/ai_function_test.go`
- `ennam.kg.go/internal/store/ai_model_update_delete_test.go` (nil-DB guards)
- `ennam.kg.go/internal/handler/ai_model_guard_test.go` (settings guard, httptest)

---

## Task 1: AI-function registry

**Files:**
- Create: `ennam.kg.go/internal/models/ai_function.go`
- Test: `ennam.kg.go/internal/models/ai_function_test.go`

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/models/ai_function_test.go`:

```go
package models

import "testing"

func TestLookupAIFunction(t *testing.T) {
	f, ok := LookupAIFunction("nl_query_intent")
	if !ok {
		t.Fatal("nl_query_intent should be a known function")
	}
	if !f.RequiresJSON {
		t.Error("nl_query_intent should require JSON")
	}
	if f.RequiresTools {
		t.Error("Path-A function must not require tools")
	}
	if d, ok := LookupAIFunction("kg_description"); !ok || d.RequiresJSON {
		t.Errorf("kg_description should be known and text-only (RequiresJSON=false), got ok=%v json=%v", ok, d.RequiresJSON)
	}
	if _, ok := LookupAIFunction("not_a_function"); ok {
		t.Error("unknown key must not resolve")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/models/ -run TestLookupAIFunction -v`
Expected: FAIL — `LookupAIFunction` undefined.

- [ ] **Step 3: Write the registry**

Create `ennam.kg.go/internal/models/ai_function.go`:

```go
package models

// AIFunction is a routable AI function (IMP-006). Its Key equals both the
// AIRequest.RequestType the call site sends and the suffix of its
// ai.model.<Key> system setting. Capability flags drive the assignment guard.
type AIFunction struct {
	Key           string
	DisplayName   string
	RequiresTools bool // assigned model must support tool-calling (agentic / Path B)
	RequiresJSON  bool // assigned model must support JSON output
}

// AIFunctions is the registry of admin-routable functions. These are the real
// RequestType strings sent by the Go call sites (Path A); agentic (Path B) is P4.
var AIFunctions = []AIFunction{
	{Key: "extraction", DisplayName: "Ingestion extraction", RequiresJSON: true},
	{Key: "nl_query_intent", DisplayName: "NL→SQL intent", RequiresJSON: true},
	{Key: "sql_verification", DisplayName: "SQL self-verification", RequiresJSON: true},
	{Key: "table_filter", DisplayName: "Smart-context table filter", RequiresJSON: true},
	{Key: "kg_implicit_scoring", DisplayName: "Implicit edge scoring", RequiresJSON: true},
	{Key: "kg_description", DisplayName: "KG node description"},
	{Key: "embedding_description", DisplayName: "Embedding description"},
}

// LookupAIFunction returns the function definition for a key, or ok=false.
func LookupAIFunction(key string) (AIFunction, bool) {
	for _, f := range AIFunctions {
		if f.Key == key {
			return f, true
		}
	}
	return AIFunction{}, false
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/models/ -run TestLookupAIFunction -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/models/ai_function.go internal/models/ai_function_test.go
git commit -m "feat(ai): AIFunction registry of real request-type functions (IMP-006 P2)"
```

---

## Task 2: `AIModelStore.Update` + `Delete`

**Files:**
- Modify: `ennam.kg.go/internal/store/ai_model.go`
- Test: `ennam.kg.go/internal/store/ai_model_update_delete_test.go`

- [ ] **Step 1: Write the failing nil-DB guard tests**

Create `ennam.kg.go/internal/store/ai_model_update_delete_test.go`:

```go
package store

import (
	"context"
	"testing"

	"github.com/ennam/ennam-kg/internal/models"
)

func TestAIModelStore_Update_NilDB(t *testing.T) {
	s := NewAIModelStore(nil)
	if err := s.Update(context.Background(), &models.AIModel{ID: "x"}); err == nil {
		t.Fatal("expected error on nil DB")
	}
}

func TestAIModelStore_Delete_NilDB(t *testing.T) {
	s := NewAIModelStore(nil)
	if err := s.Delete(context.Background(), "x"); err == nil {
		t.Fatal("expected error on nil DB")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/store/ -run "TestAIModelStore_(Update|Delete)_NilDB" -v`
Expected: FAIL — `Update`/`Delete` undefined.

- [ ] **Step 3: Add `Update` and `Delete` to `ai_model.go`**

Append to `ennam.kg.go/internal/store/ai_model.go`:

```go
// Update modifies a model's editable fields (display name, capabilities, active).
func (s *AIModelStore) Update(ctx context.Context, m *models.AIModel) error {
	if s.db == nil {
		return fmt.Errorf("Update: nil database")
	}
	query := `
		UPDATE ai_models
		SET display_name = $1, supports_tools = $2, supports_json = $3, is_active = $4, updated_at = now()
		WHERE id = $5
		RETURNING updated_at`
	err := s.db.QueryRowContext(ctx, query,
		m.DisplayName, m.SupportsTools, m.SupportsJSON, m.IsActive, m.ID,
	).Scan(&m.UpdatedAt)
	if err != nil {
		if err == sql.ErrNoRows {
			return fmt.Errorf("ai model %q not found", m.ID)
		}
		return fmt.Errorf("update ai model: %w", err)
	}
	return nil
}

// Delete removes a model by id.
func (s *AIModelStore) Delete(ctx context.Context, id string) error {
	if s.db == nil {
		return fmt.Errorf("Delete: nil database")
	}
	res, err := s.db.ExecContext(ctx, `DELETE FROM ai_models WHERE id = $1`, id)
	if err != nil {
		return fmt.Errorf("delete ai model: %w", err)
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return fmt.Errorf("ai model %q not found", id)
	}
	return nil
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/store/ -run "TestAIModelStore" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/store/ai_model.go internal/store/ai_model_update_delete_test.go
git commit -m "feat(ai): AIModelStore Update + Delete (IMP-006 P2)"
```

---

## Task 3: Auto-seed `ai_models` on provider create

**Files:**
- Modify: `ennam.kg.go/internal/handler/ai_provider.go` (struct + `SetModelStore` + `Create`)

- [ ] **Step 1: Add the `modelStore` field + setter**

In `ennam.kg.go/internal/handler/ai_provider.go`, add a field to the `AIProviderHandler` struct (next to `oauthService`):

```go
	modelStore      *store.AIModelStore // optional — IMP-006 ai_models registry
```

Add a setter near `SetOAuthService`:

```go
// SetModelStore enables ai_models CRUD + auto-seed on provider create (IMP-006).
func (h *AIProviderHandler) SetModelStore(s *store.AIModelStore) {
	h.modelStore = s
}
```

- [ ] **Step 2: Auto-seed in `Create`**

In `Create`, after the provider is persisted and **before** `if h.rebuildSelector != nil`, add the seed (uses the just-assigned `p.ID` / `p.ModelID`):

```go
	if h.modelStore != nil && strings.TrimSpace(p.ModelID) != "" {
		seed := &models.AIModel{
			ProviderID:    p.ID,
			ModelID:       p.ModelID,
			DisplayName:   p.Name,
			SupportsTools: p.ProviderType == models.ProviderTypeAnthropicAPI || p.ProviderType == models.ProviderTypeClaudeMax,
			SupportsJSON:  true,
			IsActive:      true,
		}
		if err := h.modelStore.Create(ctx, seed); err != nil {
			h.logger.WarnContext(ctx, "auto-seed ai_model failed", "error", err, "provider", p.ID)
		}
	}
```
> `strings` and `models` are already imported in this file. The seed mirrors migration 000057's defaults (anthropic ⇒ tools+json; others ⇒ json only). A failed seed is logged, not fatal — the provider still exists and an admin can add the model via the CRUD endpoint (Task 4).

- [ ] **Step 3: Build**

Run: `cd ennam.kg.go && go build ./...`
Expected: builds clean.

- [ ] **Step 4: Commit**

```bash
git add internal/handler/ai_provider.go
git commit -m "feat(ai): auto-seed ai_models row when a provider is registered (IMP-006 P2)"
```

---

## Task 4: `ai_models` CRUD endpoints

**Files:**
- Modify: `ennam.kg.go/internal/handler/ai_provider.go` (handlers + routes)

- [ ] **Step 1: Add the request bodies + handlers**

Append to `ennam.kg.go/internal/handler/ai_provider.go`:

```go
// addModelRequest is the body for POST /api/v1/ai-providers/{id}/models.
type addModelRequest struct {
	ModelID       string `json:"model_id"`
	DisplayName   string `json:"display_name"`
	SupportsTools bool   `json:"supports_tools"`
	SupportsJSON  bool   `json:"supports_json"`
}

// updateModelRequest is the body for PATCH /api/v1/ai-models/{id}.
type updateModelRequest struct {
	DisplayName   *string `json:"display_name,omitempty"`
	SupportsTools *bool   `json:"supports_tools,omitempty"`
	SupportsJSON  *bool   `json:"supports_json,omitempty"`
	IsActive      *bool   `json:"is_active,omitempty"`
}

// ListModels handles GET /api/v1/ai-providers/{id}/models — admin only.
func (h *AIProviderHandler) ListModels(w http.ResponseWriter, r *http.Request) {
	if h.modelStore == nil {
		errorResponse(w, http.StatusServiceUnavailable, "ai models not configured")
		return
	}
	providerID := r.PathValue("id")
	list, err := h.modelStore.ListByProvider(r.Context(), providerID)
	if err != nil {
		errorResponse(w, http.StatusInternalServerError, "failed to list models")
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"models": list})
}

// AddModel handles POST /api/v1/ai-providers/{id}/models — admin only.
func (h *AIProviderHandler) AddModel(w http.ResponseWriter, r *http.Request) {
	if h.modelStore == nil {
		errorResponse(w, http.StatusServiceUnavailable, "ai models not configured")
		return
	}
	providerID := r.PathValue("id")
	if _, err := h.providerStore.GetByID(r.Context(), providerID); err != nil {
		errorResponse(w, http.StatusNotFound, "provider not found")
		return
	}
	var req addModelRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if strings.TrimSpace(req.ModelID) == "" {
		errorResponse(w, http.StatusBadRequest, "model_id is required")
		return
	}
	m := &models.AIModel{
		ProviderID:    providerID,
		ModelID:       req.ModelID,
		DisplayName:   firstNonEmpty(req.DisplayName, req.ModelID),
		SupportsTools: req.SupportsTools,
		SupportsJSON:  req.SupportsJSON,
		IsActive:      true,
	}
	if err := h.modelStore.Create(r.Context(), m); err != nil {
		h.handleStoreError(w, err, "add ai model")
		return
	}
	writeJSON(w, http.StatusCreated, m)
}

// UpdateModel handles PATCH /api/v1/ai-models/{id} — admin only.
func (h *AIProviderHandler) UpdateModel(w http.ResponseWriter, r *http.Request) {
	if h.modelStore == nil {
		errorResponse(w, http.StatusServiceUnavailable, "ai models not configured")
		return
	}
	id := r.PathValue("id")
	m, err := h.modelStore.GetByID(r.Context(), id)
	if err != nil {
		errorResponse(w, http.StatusNotFound, "ai model not found")
		return
	}
	var req updateModelRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if req.DisplayName != nil {
		m.DisplayName = *req.DisplayName
	}
	if req.SupportsTools != nil {
		m.SupportsTools = *req.SupportsTools
	}
	if req.SupportsJSON != nil {
		m.SupportsJSON = *req.SupportsJSON
	}
	if req.IsActive != nil {
		m.IsActive = *req.IsActive
	}
	if err := h.modelStore.Update(r.Context(), m); err != nil {
		h.handleStoreError(w, err, "update ai model")
		return
	}
	writeJSON(w, http.StatusOK, m)
}

// DeleteModel handles DELETE /api/v1/ai-models/{id} — admin only.
func (h *AIProviderHandler) DeleteModel(w http.ResponseWriter, r *http.Request) {
	if h.modelStore == nil {
		errorResponse(w, http.StatusServiceUnavailable, "ai models not configured")
		return
	}
	if err := h.modelStore.Delete(r.Context(), r.PathValue("id")); err != nil {
		h.handleStoreError(w, err, "delete ai model")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func firstNonEmpty(a, b string) string {
	if strings.TrimSpace(a) != "" {
		return a
	}
	return b
}
```
> Reuses the package-level `writeJSON(w, status, v)` (already defined in `internal/handler/document.go:191`), `errorResponse` (`search.go:88`), and `handleStoreError` (method on `AIProviderHandler`, used by `Create`) — do **not** add new copies of these.

- [ ] **Step 2: Register the routes**

In `RegisterRoutes`, add after the existing AI-provider routes:

```go
	mux.HandleFunc("GET /api/v1/ai-providers/{id}/models", h.ListModels)
	mux.HandleFunc("POST /api/v1/ai-providers/{id}/models", h.AddModel)
	mux.HandleFunc("PATCH /api/v1/ai-models/{id}", h.UpdateModel)
	mux.HandleFunc("DELETE /api/v1/ai-models/{id}", h.DeleteModel)
```

- [ ] **Step 3: Build + vet**

Run: `cd ennam.kg.go && go build ./... && go vet ./internal/handler/`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add internal/handler/ai_provider.go
git commit -m "feat(ai): ai_models CRUD endpoints under provider connections (IMP-006 P2)"
```

---

## Task 5: Assignment / capability guard in settings update

**Files:**
- Modify: `ennam.kg.go/internal/handler/settings.go` (struct + setter + validation in `HandleUpdateSetting`)
- Test: `ennam.kg.go/internal/handler/ai_model_guard_test.go`

- [ ] **Step 1: Write the failing guard test**

Create `ennam.kg.go/internal/handler/ai_model_guard_test.go`. It exercises `validateAIModelAssignment` directly with a fake model lookup so it needs no DB or HTTP:

```go
package handler

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/ennam/ennam-kg/internal/models"
)

type fakeModelLookup struct{ m map[string]*models.AIModel }

func (f fakeModelLookup) GetByID(_ context.Context, id string) (*models.AIModel, error) {
	if mm, ok := f.m[id]; ok {
		return mm, nil
	}
	return nil, errModelNotFound
}

func raw(s string) json.RawMessage { b, _ := json.Marshal(s); return b }

func TestValidateAIModelAssignment(t *testing.T) {
	jsonModel := &models.AIModel{ID: "ok", ModelID: "gpt-oss-120b", SupportsJSON: true}
	noJSON := &models.AIModel{ID: "nojson", ModelID: "weird", SupportsJSON: false}
	lookup := fakeModelLookup{m: map[string]*models.AIModel{"ok": jsonModel, "nojson": noJSON}}

	tests := []struct {
		name    string
		key     string
		value   json.RawMessage
		wantErr bool
	}{
		{"valid json model for json function", "ai.model.nl_query_intent", raw("ok"), false},
		{"auto is always valid", "ai.model.nl_query_intent", raw("auto"), false},
		{"unknown function rejected", "ai.model.not_a_function", raw("ok"), true},
		{"missing model rejected", "ai.model.extraction", raw("ghost"), true},
		{"json function + non-json model rejected", "ai.model.extraction", raw("nojson"), true},
		{"text function accepts non-json model", "ai.model.kg_description", raw("nojson"), false},
		{"non ai.model key skipped", "ingestion.auto_queue", raw("ok"), false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := validateAIModelAssignment(context.Background(), lookup, tt.key, tt.value)
			if (err != nil) != tt.wantErr {
				t.Fatalf("err = %v, wantErr = %v", err, tt.wantErr)
			}
		})
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestValidateAIModelAssignment -v`
Expected: FAIL — `validateAIModelAssignment`, `errModelNotFound` undefined.

- [ ] **Step 3: Implement the guard**

In `ennam.kg.go/internal/handler/settings.go`:

Add imports `"context"`, `"errors"`, `"fmt"` (keep existing). Add a field to `SettingsHandler`:
```go
type SettingsHandler struct {
	svc          *service.SettingsService
	logger       *slog.Logger
	aiModelStore aiModelLookup // optional — IMP-006 assignment guard
}
```

Add the lookup interface + sentinel + setter + the standalone validator:
```go
// aiModelLookup loads an ai_models row by id (satisfied by *store.AIModelStore).
type aiModelLookup interface {
	GetByID(ctx context.Context, id string) (*models.AIModel, error)
}

var errModelNotFound = errors.New("ai model not found")

// SetAIModelStore enables the IMP-006 ai.model.<function> assignment guard.
func (h *SettingsHandler) SetAIModelStore(s aiModelLookup) {
	h.aiModelStore = s
}

// validateAIModelAssignment rejects an invalid ai.model.<function> setting:
// unknown function, missing model, or a model lacking the function's required
// capability. Non-"ai.model." keys and "auto" pass. A nil lookup disables the
// model-existence/capability checks (function-name check still applies).
func validateAIModelAssignment(ctx context.Context, lookup aiModelLookup, key string, rawVal json.RawMessage) error {
	const prefix = "ai.model."
	if !strings.HasPrefix(key, prefix) {
		return nil
	}
	fnKey := strings.TrimPrefix(key, prefix)
	fn, ok := models.LookupAIFunction(fnKey)
	if !ok {
		return fmt.Errorf("unknown AI function %q", fnKey)
	}
	var val string
	if err := json.Unmarshal(rawVal, &val); err != nil {
		return fmt.Errorf("value must be an ai_models id (string) or \"auto\"")
	}
	val = strings.TrimSpace(val)
	if val == "" || val == "auto" {
		return nil
	}
	if lookup == nil {
		return nil
	}
	m, err := lookup.GetByID(ctx, val)
	if err != nil {
		return fmt.Errorf("ai model %q not found", val)
	}
	if fn.RequiresTools && !m.SupportsTools {
		return fmt.Errorf("model %q does not support tool-calling, required by %q", m.ModelID, fnKey)
	}
	if fn.RequiresJSON && !m.SupportsJSON {
		return fmt.Errorf("model %q does not support JSON output, required by %q", m.ModelID, fnKey)
	}
	return nil
}
```

Then call it inside `HandleUpdateSetting`, **after** the `req.Value` emptiness check and **before** `h.svc.Set(...)`:
```go
	if err := validateAIModelAssignment(ctx, h.aiModelStore, key, req.Value); err != nil {
		errorResponse(w, http.StatusBadRequest, err.Error())
		return
	}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestValidateAIModelAssignment -v`
Expected: PASS (all sub-cases).

- [ ] **Step 5: Commit**

```bash
git add internal/handler/settings.go internal/handler/ai_model_guard_test.go
git commit -m "feat(settings): guard ai.model.<function> assignments (known function + capable, existing model) (IMP-006 P2)"
```

---

## Task 6: Wire the stores in `main.go`

**Files:**
- Modify: `ennam.kg.go/cmd/kg-server/main.go`

- [ ] **Step 1: Reuse the P1 `aiModelStore` for the new setters (mind the ordering)**

P1 already declares `aiModelStore := store.NewAIModelStore(db)` (~line 465, right after `settingsSvc`, where the resolver is wired). Both new setters must be called **after that line** (so `aiModelStore` is in scope):

- The provider handler `aiHandler` is constructed **earlier** (~line 430), but the setter call can still go after line 465. Right after the P1 `aiModelStore` declaration, add:
```go
	aiHandler.SetModelStore(aiModelStore)
```
- The settings handler `settingsHandler` is constructed ~line 639 — after `aiModelStore` exists — so right after it is created, add:
```go
	settingsHandler.SetAIModelStore(aiModelStore)
```
> Do not re-declare `aiModelStore`; reuse the single P1 instance (so the resolver, provider handler, and settings handler share it). `SetModelStore` takes `*store.AIModelStore`; `SetAIModelStore` takes the `aiModelLookup` interface — `*store.AIModelStore` satisfies both.

- [ ] **Step 2: Build + full test**

Run: `cd ennam.kg.go && go build ./... && go test ./... 2>&1 | grep -E "FAIL|ok" | tail -20`
Expected: builds clean; no `FAIL` lines.

- [ ] **Step 3: Commit**

```bash
git add cmd/kg-server/main.go
git commit -m "feat(ai): wire ai_models store into provider + settings handlers (IMP-006 P2)"
```

---

## Task 7: Live acceptance (against the running stack)

- [ ] **Step 1: Register a provider → auto-seed**

```bash
curl -s -X POST http://localhost:8080/api/v1/ai-providers \
  -H "Authorization: Bearer ennam_kg_dev_000000000000000000000000" -H "Content-Type: application/json" \
  -d '{"name":"byteplus-ark","provider_type":"openai","base_url":"https://ark.ap-southeast.bytepluses.com/api/coding/v3","api_key":"<KEY>","model_id":"gpt-oss-120b","priority":50}'
# The provider id is in the response; list its models (should already contain gpt-oss-120b via auto-seed):
PID=<provider-id>
curl -s "http://localhost:8080/api/v1/ai-providers/$PID/models" -H "Authorization: Bearer ennam_kg_dev_000000000000000000000000"
```
Expected: the `models` array contains the auto-seeded `gpt-oss-120b` row.

- [ ] **Step 2: Add a second model + edit capability**

```bash
curl -s -X POST "http://localhost:8080/api/v1/ai-providers/$PID/models" \
  -H "Authorization: Bearer ennam_kg_dev_000000000000000000000000" -H "Content-Type: application/json" \
  -d '{"model_id":"glm-4.7","display_name":"GLM 4.7","supports_json":true,"supports_tools":false}'
```
Expected: `201` with the new `ai_models` row (note its `id`).

- [ ] **Step 3: Guard rejects bad assignments**

```bash
# Unknown function -> 400
curl -s -o /dev/null -w "%{http_code}\n" -X PUT "http://localhost:8080/api/v1/settings/ai.model.bogus_fn" \
  -H "Authorization: Bearer ennam_kg_dev_000000000000000000000000" -H "Content-Type: application/json" \
  -d '{"value":"<glm-model-id>","category":"ai"}'
# Non-existent model -> 400
curl -s -o /dev/null -w "%{http_code}\n" -X PUT "http://localhost:8080/api/v1/settings/ai.model.extraction" \
  -H "Authorization: Bearer ennam_kg_dev_000000000000000000000000" -H "Content-Type: application/json" \
  -d '{"value":"00000000-0000-0000-0000-000000000000","category":"ai"}'
# Valid assignment -> 200
curl -s -o /dev/null -w "%{http_code}\n" -X PUT "http://localhost:8080/api/v1/settings/ai.model.extraction" \
  -H "Authorization: Bearer ennam_kg_dev_000000000000000000000000" -H "Content-Type: application/json" \
  -d '{"value":"<glm-model-id>","category":"ai"}'
```
Expected: `400`, `400`, `200`.

- [ ] **Step 4: Delete a model**

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE "http://localhost:8080/api/v1/ai-models/<glm-model-id>" \
  -H "Authorization: Bearer ennam_kg_dev_000000000000000000000000"
```
Expected: `204`. (Per BR-006.6, any setting pointing at it should then resolve to `auto`/fallback — verify `ai.model.extraction` falls back on the next request.)

---

## Done criteria (P2)

- `models.AIFunction` registry with the seven real functions; `go test ./...` green; `go build ./...` clean.
- Registering a provider auto-creates an `ai_models` row; `ai_models` CRUD endpoints work (list/add/update/delete).
- `PUT /api/v1/settings/ai.model.<fn>` rejects unknown function, non-existent model, and capability mismatch (400); accepts `auto` and a valid capable model id (200).
- All wiring via optional setters; existing tests unaffected.

**Not in P2 (later plans):** dashboard provider/model UI + per-function dropdowns (P3, uses `AIFunctions` + the CRUD endpoints); agentic Path B OpenAI-compatible client (P4, registers an `agentic` function with `RequiresTools=true`).
```
