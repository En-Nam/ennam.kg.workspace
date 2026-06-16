# IMP-006 P4a — Wire `ai.model.agentic` into the Agentic Chat Path (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the conversational **agentic** chat engine honor the `ai.model.agentic` setting — register `agentic` as a routable function, resolve its assigned model (instead of priority-only), pass the provider's `base_url` + `provider_type` + resolved model to the Python engine, and stop hard-coding Haiku — so an admin can point agentic chat at any **Anthropic-compatible** model. (Non-Anthropic / OpenAI-compatible agentic is the separate, larger **P4b**.)

**Architecture:** P1–P3 added the `ai_models` registry, the per-function resolver, and the dashboard. The agentic chat request flows Go `SSEStreamService` → Python `/api/v1/agentic/stream`, with Go injecting `X-AI-*` credential headers chosen by `CredentialProvider`. Today `SelectCredentials` uses **priority** (ignoring `ai.model.agentic`) and Python **hard-codes** the chat model to Haiku and ignores `X-AI-Base-URL`/`X-AI-Provider-Type`. P4a: resolve the agentic model via the P1 resolver, add `ProviderType` to the injected credentials, and make Python respect the injected `base_url` + `model_id`. The Anthropic wire format is unchanged (the engine still uses the Anthropic SDK); only **which Anthropic-compatible connection + model** is selectable changes.

**Tech Stack:** Go (stdlib `net/http`, `database/sql`, `log/slog`) + `go test -race`; Python 3.12 (FastAPI, `anthropic` SDK) + pytest.

**Builds on:** P1 (`ai.ModelResolver`/`SettingsModelResolver` wired into the selector via `SetModelResolver`), P2 (`ai_models`, capability guard, `models.AIFunctions`), P3 (dashboard dropdowns — `agentic` will appear automatically once registered).

**Scope / interim limitation:** P4a enables agentic on **Anthropic-type** connections (`anthropic_api`, `claude_max`) — e.g. assigning Sonnet/Opus to agentic instead of the hard-coded Haiku. If `ai.model.agentic` resolves to a non-Anthropic (`openai`) connection, the Python endpoint returns a clear **501** ("agentic on OpenAI-compatible providers arrives in P4b") rather than mis-using the Anthropic SDK. **P4b** adds the OpenAI-compatible streaming + tool-calling client and the engine wire-format abstraction that lifts this limitation.

---

## File Structure

**Go (modify):**
- `ennam.kg.go/internal/models/ai_function.go` — register `agentic`.
- `ennam.kg.go/internal/ai/selector.go` — add public `ResolveEntry`.
- `ennam.kg.go/internal/service/credential_provider.go` — add `ProviderType`; resolve by request type.
- `ennam.kg.go/internal/service/sse_stream.go` — pass the request type + send `X-AI-Provider-Type`.

**Go (test):**
- `ennam.kg.go/internal/ai/selector_resolve_entry_test.go`
- `ennam.kg.go/internal/service/credential_provider_test.go` (extend if present, else create)

**Python (modify):**
- `ennam.kg.python/src/ennam_kg/api/agentic.py` — read `X-AI-Provider-Type` + `X-AI-Base-URL`; build client accordingly (501 for openai).
- `ennam.kg.python/src/ennam_kg/agentic/engine.py` — `_resolve_chat_model` respects the client's model.

**Python (test):**
- `ennam.kg.python/tests/test_agentic/test_chat_model_resolution.py`

---

## Task 1: Register the `agentic` function

**Files:**
- Modify: `ennam.kg.go/internal/models/ai_function.go`
- Test: `ennam.kg.go/internal/models/ai_function_test.go` (extend)

- [ ] **Step 1: Write the failing test**

Add to `ennam.kg.go/internal/models/ai_function_test.go`:

```go
func TestAgenticFunctionRegistered(t *testing.T) {
	f, ok := LookupAIFunction("agentic")
	if !ok {
		t.Fatal("agentic must be a known function")
	}
	if !f.RequiresTools {
		t.Error("agentic requires tool-calling")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/models/ -run TestAgenticFunctionRegistered -v`
Expected: FAIL — `agentic` not found.

- [ ] **Step 3: Add `agentic` to the registry**

In `ennam.kg.go/internal/models/ai_function.go`, append to the `AIFunctions` slice (after `embedding_description`):

```go
	{Key: "agentic", DisplayName: "Conversational agent (chat)", RequiresTools: true, RequiresJSON: true},
}
```
> `RequiresTools: true` makes the P2 guard reject assigning a non-tool model. `RequiresJSON: true` is harmless (tool-capable chat models also do JSON). This is the only Path-B entry.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/models/ -run "TestAgenticFunctionRegistered|TestLookupAIFunction" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/models/ai_function.go internal/models/ai_function_test.go
git commit -m "feat(ai): register 'agentic' routable function (IMP-006 P4a)"
```

---

## Task 2: `Selector.ResolveEntry` — public per-request-type resolution

**Files:**
- Modify: `ennam.kg.go/internal/ai/selector.go`
- Test: `ennam.kg.go/internal/ai/selector_resolve_entry_test.go`

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/ai/selector_resolve_entry_test.go`. It reuses the `stubProvider`/`stubResolver`/`newTestEntry` helpers from the existing `selector_resolve_test.go` (same package), so define only the test:

```go
package ai

import (
	"context"
	"testing"
	"time"
)

func TestSelector_ResolveEntry(t *testing.T) {
	prio := &stubProvider{id: "prio"}
	target := &stubProvider{id: "target"}
	sel := NewSelector(
		[]ProviderEntry{newTestEntry("prio", 1, prio), newTestEntry("target", 9, target)},
		nil, nil, time.Second, time.Second,
	)

	// No resolver set → no resolution.
	if _, _, ok := sel.ResolveEntry(context.Background(), "agentic"); ok {
		t.Fatal("expected ok=false with no resolver")
	}

	sel.SetModelResolver(stubResolver{out: ModelResolved{ProviderID: "target", ModelID: "claude-opus-4-8"}, ok: true})

	entry, modelID, ok := sel.ResolveEntry(context.Background(), "agentic")
	if !ok {
		t.Fatal("expected resolution to succeed")
	}
	if entry.Model.ID != "target" {
		t.Errorf("entry = %q, want target", entry.Model.ID)
	}
	if modelID != "claude-opus-4-8" {
		t.Errorf("modelID = %q, want claude-opus-4-8", modelID)
	}

	// Empty request type → no resolution.
	if _, _, ok := sel.ResolveEntry(context.Background(), ""); ok {
		t.Fatal("expected ok=false for empty request type")
	}
}
```

> `stubProvider`, `stubResolver`, and `newTestEntry` are already defined in `internal/ai/selector_resolve_test.go` (same package, verified) — reuse them; do NOT redefine (duplicate declarations won't compile). `stubProvider` has fields `id` + `respText`; `stubResolver` has `out ModelResolved` + `ok bool`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/ai/ -run TestSelector_ResolveEntry -v`
Expected: FAIL — `ResolveEntry` undefined.

- [ ] **Step 3: Add `ResolveEntry`**

In `ennam.kg.go/internal/ai/selector.go`, add (near `SelectBestEntry`):

```go
// ResolveEntry returns the provider entry + resolved model id assigned to a
// request type via the model resolver (IMP-006), or ok=false to fall back to
// priority selection. The returned entry is a snapshot copy.
func (s *Selector) ResolveEntry(ctx context.Context, requestType string) (*ProviderEntry, string, bool) {
	s.mu.RLock()
	entries := make([]ProviderEntry, len(s.entries))
	copy(entries, s.entries)
	resolver := s.modelResolver
	s.mu.RUnlock()

	if resolver == nil || requestType == "" {
		return nil, "", false
	}
	resolved, ok := resolver.Resolve(ctx, requestType)
	if !ok {
		return nil, "", false
	}
	for i := range entries {
		if entries[i].Model != nil && entries[i].Model.ID == resolved.ProviderID && entries[i].Model.IsActive {
			e := entries[i]
			return &e, resolved.ModelID, true
		}
	}
	return nil, "", false
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/ai/ -run TestSelector_ResolveEntry -race -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/ai/selector.go internal/ai/selector_resolve_entry_test.go
git commit -m "feat(ai): Selector.ResolveEntry — public per-request-type resolution (IMP-006 P4a)"
```

---

## Task 3: Credential provider — provider type + resolve by request type

**Files:**
- Modify: `ennam.kg.go/internal/service/credential_provider.go`
- Test: `ennam.kg.go/internal/service/credential_provider_test.go` (create)

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/service/credential_provider_test.go`. This locks the contract that the injection carries `ProviderType` and the signature takes a request type (compile-level + behavior with an empty selector):

```go
package service

import (
	"context"
	"testing"
)

func TestCredentialInjection_HasProviderType(t *testing.T) {
	ci := CredentialInjection{ProviderType: "anthropic_api"}
	if ci.ProviderType != "anthropic_api" {
		t.Fatalf("ProviderType = %q", ci.ProviderType)
	}
}

func TestSelectCredentials_NilSelectorErrors(t *testing.T) {
	p := &AICredentialProvider{} // nil selector
	defer func() {
		if r := recover(); r == nil {
			// either an error return or a panic-free nil is acceptable; just must not succeed
		}
	}()
	_, err := p.SelectCredentials(context.Background(), "agentic")
	if err == nil {
		t.Fatal("expected error with nil selector")
	}
}
```

> If a nil selector panics rather than errors, wrap the body or adjust; the point is the new `SelectCredentials(ctx, requestType)` signature compiles and does not succeed without a selector.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/service/ -run "TestCredentialInjection_HasProviderType|TestSelectCredentials_NilSelectorErrors" -v`
Expected: FAIL — `ProviderType` field missing / `SelectCredentials` takes no `requestType`.

- [ ] **Step 3: Update `credential_provider.go`**

Add `ProviderType` to the struct:

```go
type CredentialInjection struct {
	APIKey       string
	BaseURL      string
	ModelID      string
	ProviderID   string
	ProviderType string // IMP-006: anthropic_api | claude_max | openai — lets Python pick the wire format
	MaxTokens    int
}
```

Update the interface:

```go
type CredentialProvider interface {
	SelectCredentials(ctx context.Context, requestType string) (*CredentialInjection, error)
}
```

Replace `SelectCredentials` with a resolve-then-fallback implementation:

```go
// SelectCredentials returns credentials for a request type. If ai.model.<requestType>
// resolves to an active connection it is used; otherwise it falls back to the
// priority-best provider (BA-009).
func (p *AICredentialProvider) SelectCredentials(ctx context.Context, requestType string) (*CredentialInjection, error) {
	if p.selector == nil {
		return nil, fmt.Errorf("no AI selector configured")
	}
	if entry, modelID, ok := p.selector.ResolveEntry(ctx, requestType); ok {
		return p.injectionFromEntry(entry, modelID)
	}
	entry, err := p.selector.SelectBestEntry(ctx)
	if err != nil {
		return nil, fmt.Errorf("select provider: %w", err)
	}
	return p.injectionFromEntry(entry, entry.Model.ModelID)
}

func (p *AICredentialProvider) injectionFromEntry(entry *ai.ProviderEntry, modelID string) (*CredentialInjection, error) {
	if len(entry.Model.APIKeyEncrypted) == 0 {
		return nil, fmt.Errorf("provider %s has no encrypted API key", entry.Model.ID)
	}
	apiKeyBytes, err := crypto.Decrypt(entry.Model.APIKeyEncrypted, p.encKey)
	if err != nil {
		return nil, fmt.Errorf("decrypt api key for provider %s: %w", entry.Model.ID, err)
	}
	return &CredentialInjection{
		APIKey:       string(apiKeyBytes),
		BaseURL:      entry.Model.BaseURL,
		ModelID:      modelID,
		ProviderID:   entry.Model.ID,
		ProviderType: entry.Model.ProviderType,
		MaxTokens:    p.maxTokens,
	}, nil
}
```

> `ai.ProviderEntry.Model` is `*models.AIProvider` with `BaseURL`, `ProviderType`, `APIKeyEncrypted`, `ID`, `ModelID` (verified). `ai` + `crypto` + `models` are already imported in this file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/service/ -run "TestCredentialInjection_HasProviderType|TestSelectCredentials_NilSelectorErrors" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/service/credential_provider.go internal/service/credential_provider_test.go
git commit -m "feat(ai): credential provider resolves by request type + carries provider_type (IMP-006 P4a)"
```

---

## Task 4: `sse_stream.go` — pass the request type + send provider-type header

**Files:**
- Modify: `ennam.kg.go/internal/service/sse_stream.go`

- [ ] **Step 1: Update the credential-injection call site**

In `ennam.kg.go/internal/service/sse_stream.go`, the credential block currently calls `s.credentialProvider.SelectCredentials(ctx)`. Replace it to (a) derive the request type from the resolved Python endpoint, (b) send the provider-type header:

```go
	// Inject AI credentials for direct provider access from Python.
	if s.credentialProvider != nil {
		// The agentic chat endpoint honors ai.model.agentic; other streams fall back to priority.
		credRequestType := ""
		if pythonEndpoint(req) == "/api/v1/agentic/stream" {
			credRequestType = "agentic"
		}
		creds, credErr := s.credentialProvider.SelectCredentials(ctx, credRequestType)
		if credErr != nil {
			s.logger.Warn("credential selection failed, streaming without AI headers", "error", credErr)
		} else if creds != nil {
			httpReq.Header.Set("X-AI-API-Key", creds.APIKey)
			httpReq.Header.Set("X-AI-Base-URL", creds.BaseURL)
			httpReq.Header.Set("X-AI-Model-ID", creds.ModelID)
			httpReq.Header.Set("X-AI-Provider-ID", creds.ProviderID)
			httpReq.Header.Set("X-AI-Provider-Type", creds.ProviderType)
			httpReq.Header.Set("X-AI-Max-Tokens", strconv.Itoa(creds.MaxTokens))
		}
	}
```

> `pythonEndpoint(req)` already exists (returns `/api/v1/agentic/stream` vs `/api/v1/ai/stream`). If any **other** `CredentialProvider` implementation or test mock exists, update its `SelectCredentials` signature to `(ctx, requestType string)` — grep `SelectCredentials` across the repo.

- [ ] **Step 2: Build + test the service package**

Run: `cd ennam.kg.go && go build ./... && go test ./internal/service/ ./internal/ai/ 2>&1 | grep -E "FAIL|ok" | tail`
Expected: builds clean (any mock implementing `CredentialProvider` updated); no `FAIL`.

- [ ] **Step 3: Commit**

```bash
git add internal/service/sse_stream.go
git commit -m "feat(ai): agentic stream resolves ai.model.agentic + sends X-AI-Provider-Type (IMP-006 P4a)"
```

---

## Task 5: Python agentic endpoint — respect base_url + model; guard non-Anthropic

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/api/agentic.py`

- [ ] **Step 1: Read the provider-type + base-url headers and branch**

In `ennam.kg.python/src/ennam_kg/api/agentic.py`:

First add `HTTPException` to the FastAPI import (the file currently imports `from fastapi import APIRouter, Header, Request`):

```python
from fastapi import APIRouter, Header, HTTPException, Request
```

Add the two headers to the route signature (next to `x_ai_model_id`):

```python
    x_ai_provider_type: str = Header("anthropic_api"),
    x_ai_base_url: str | None = Header(None),
```

In `_create_engine(...)`, accept + use them. Change the signature to take `provider_type` + `base_url`, and build the client with a guard:

```python
async def _create_engine(
    request: Request,
    body: AgenticStreamRequest,
    api_key: str,
    model_id: str,
    provider_type: str,
    base_url: str | None,
    db_dsn: str | None,
) -> tuple[AgenticEngine, list]:
    cleanups = []

    if provider_type not in ("anthropic_api", "claude_max", ""):
        # IMP-006 P4b adds OpenAI-compatible streaming + tool-calling for agentic.
        raise HTTPException(
            status_code=501,
            detail=f"agentic chat is not yet supported on provider_type={provider_type!r} (IMP-006 P4b)",
        )

    ai_client = AnthropicDirectClient(api_key=api_key, model_id=model_id, base_url=base_url)
    cleanups.append(ai_client.close)
    # ... (unchanged: KGClient, SourceDBClient, AgentStateStore, AgenticEngine) ...
    return engine, cleanups
```

Update the route to pass the new args:

```python
    engine, cleanups = await _create_engine(
        request, body, x_ai_api_key, x_ai_model_id, x_ai_provider_type, x_ai_base_url, x_db_dsn,
    )
```
> `AnthropicDirectClient.__init__(api_key, model_id, provider_id="", base_url=None, ...)` already accepts `base_url` (verified) — passing `None` keeps the default Anthropic endpoint; a real base_url targets an Anthropic-compatible gateway. `ai_client.close` exists (async) and is already appended to `cleanups` today — keep that line.

- [ ] **Step 2: Verify import + lint**

Run: `cd ennam.kg.python && uv run ruff check src/ennam_kg/api/agentic.py`
Expected: clean (fix any unused/import issues ruff flags).

- [ ] **Step 3: Commit**

```bash
git add src/ennam_kg/api/agentic.py
git commit -m "feat(agentic): respect X-AI-Base-URL/Model + 501 on non-Anthropic provider (IMP-006 P4a)"
```

---

## Task 6: Stop hard-coding the chat model

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/agentic/engine.py`
- Test: `ennam.kg.python/tests/test_agentic/test_chat_model_resolution.py`

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.python/tests/test_agentic/test_chat_model_resolution.py`:

```python
from unittest.mock import MagicMock

from ennam_kg.agentic.engine import _resolve_chat_model


def test_resolve_chat_model_uses_client_model_by_default(monkeypatch):
    monkeypatch.delenv("CHAT_MODEL_OVERRIDE", raising=False)
    client = MagicMock()
    client._model = "claude-opus-4-8"
    assert _resolve_chat_model(client) == "claude-opus-4-8"


def test_resolve_chat_model_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("CHAT_MODEL_OVERRIDE", "claude-haiku-4-5-20251001")
    client = MagicMock()
    client._model = "claude-opus-4-8"
    assert _resolve_chat_model(client) == "claude-haiku-4-5-20251001"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_chat_model_resolution.py -q`
Expected: FAIL — current `_resolve_chat_model` returns the hard-coded `_CHAT_MODEL_OVERRIDE` constant by default, not `client._model`.

- [ ] **Step 3: Make `_resolve_chat_model` respect the client model**

In `ennam.kg.python/src/ennam_kg/agentic/engine.py`, replace `_resolve_chat_model`:

```python
def _resolve_chat_model(ai_client: Any) -> str:
    """Return the model id to use for chat streaming.

    Default: the model the client was built with (resolved from ai.model.agentic
    or the priority-best provider — IMP-006). An explicit CHAT_MODEL_OVERRIDE env
    var (a model id) still forces that model, e.g. for local debugging.
    """
    import os

    override = os.environ.get("CHAT_MODEL_OVERRIDE", "").strip()
    if override and override not in ("0", "1"):
        return override
    return ai_client._model
```
> This flips the default from "force `_CHAT_MODEL_OVERRIDE`" to "use the injected/resolved model". The `_CHAT_MODEL_OVERRIDE` constant can be removed if now unused (check with `grep _CHAT_MODEL_OVERRIDE src/ennam_kg/agentic/engine.py`; if referenced only here, delete the constant; otherwise leave it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_chat_model_resolution.py tests/test_agentic/test_engine.py -q`
Expected: PASS (new tests + the existing engine tests still green — they mock `client._model`, which is now honored).

- [ ] **Step 5: Commit**

```bash
git add src/ennam_kg/agentic/engine.py tests/test_agentic/test_chat_model_resolution.py
git commit -m "feat(agentic): chat model = resolved/injected model, not hard-coded Haiku (IMP-006 P4a)"
```

---

## Task 7: Live acceptance (against the running stack)

Stack up + an Anthropic provider registered with `ai_models` rows for ≥2 Anthropic models (e.g. `claude-haiku-4-5` and `claude-sonnet-4-…`). If only one model exists, add a second via the P3 UI / `POST /api/v1/ai-providers/{id}/models`.

- [ ] **Step 1: `agentic` appears + is assignable** — In **Admin → AI Providers → Per-function model**, the `Conversational agent (chat)` row is present. Assign it a tool-capable Anthropic model (e.g. Sonnet). Setting `ai.model.agentic` saves (200).
- [ ] **Step 2: Capability guard** — try assigning a model with `supports_tools=false` → 400 (`requires tool-calling`). Toggle a model's tools off via the UI to test.
- [ ] **Step 3: Resolved model is used** — start a chat (agentic tier). In the Go server log, confirm the credential request resolved the assigned provider; the Python request carries `X-AI-Model-ID: <sonnet>` and the chat runs on that model (not Haiku).
  ```bash
  docker compose logs --tail 60 kg-server | grep -iE "agentic|X-AI-Model|routed"
  ```
- [ ] **Step 4: Non-Anthropic guard (interim)** — assign `ai.model.agentic` to a BytePlus (`openai`) model (capability guard allows it if `supports_tools=true`), start a chat → the stream surfaces a **501** "not yet supported … P4b". (Confirms P4a does not mis-route to the Anthropic SDK; P4b removes this.)
- [ ] **Step 5: Fallback** — set `ai.model.agentic` to `Auto (priority)` → chat uses the priority-best Anthropic provider/model (no resolution), still works.

---

## Done criteria (P4a)

- `agentic` is a registered function (`go test ./internal/models/`), assignable via the guarded settings PUT, and visible in the P3 dropdown.
- `Selector.ResolveEntry` + `CredentialProvider.SelectCredentials(ctx, requestType)` resolve `ai.model.agentic` to its connection (with `ProviderType`), falling back to priority; `go test ./internal/ai ./internal/service` green; `go build ./...` clean.
- The agentic stream sends `X-AI-Provider-Type` + the resolved `X-AI-Model-ID`/`X-AI-Base-URL`; Python builds the Anthropic client against them and **no longer hard-codes Haiku**; `_resolve_chat_model` honors the client model (`pytest tests/test_agentic` green).
- A non-Anthropic agentic assignment fails fast with 501 (interim), not a silent mis-route.

**Not in P4a → P4b:** OpenAI-compatible streaming + tool-calling Python client; wire-format abstraction in `engine.py` (normalize `content_block_delta`/`tool_use`/`stop_reason` vs OpenAI `delta`/`tool_calls`/`finish_reason`); Anthropic→OpenAI tool-definition translation. After P4b, the Task-5 501 branch becomes the OpenAI client path.
```
