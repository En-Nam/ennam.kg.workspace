# Checkpoint: backend-dev — 2026-06-16

## What was done

- Implemented IMP-006 P4a: "Wire `ai.model.agentic` into the Agentic Chat Path" — all 6 automated tasks complete.
- Task 1: Added `agentic` (RequiresTools: true) to `models.AIFunctions` registry + unit test.
- Task 2: Added `Selector.ResolveEntry(ctx, requestType)` to `internal/ai/selector.go` + test file.
- Task 3: Rewrote `CredentialProvider` interface — new signature `SelectCredentials(ctx, requestType string)`, added `ProviderType` to `CredentialInjection`, resolve-then-fallback logic + test.
- Task 4: Updated `sse_stream.go` — derive `credRequestType="agentic"` when routing to `/api/v1/agentic/stream`, propagate `X-AI-Provider-Type` and `X-AI-Base-URL` headers.
- Task 5: Updated `ennam.kg.python/src/ennam_kg/api/agentic.py` — new headers (`x_ai_provider_type`, `x_ai_base_url`), 501 guard for non-Anthropic providers, `base_url` forwarded to `AnthropicDirectClient`.
- Task 6: Deleted `_CHAT_MODEL_OVERRIDE` constant from `engine.py`; `_resolve_chat_model` now defaults to `ai_client._model` with optional `CHAT_MODEL_OVERRIDE` env var fallback + 2 new tests.
- Deep verification (2 rounds): found and fixed 2 coverage gaps — `RequiresTools` branch in `validateAIModelAssignment` untested, `agentic` absent from `TestListFunctions` assertions. Fixed in commit `3293f93`.

## Files changed

- `ennam.kg.go/internal/models/ai_function.go` — agentic entry added (commit `66520e3`)
- `ennam.kg.go/internal/models/ai_function_test.go` — TestAgenticFunctionRegistered
- `ennam.kg.go/internal/ai/selector.go` — ResolveEntry method (commit `96db6e7`)
- `ennam.kg.go/internal/ai/selector_resolve_entry_test.go` — new test file
- `ennam.kg.go/internal/service/credential_provider.go` — full rewrite (commit `4a985e6`)
- `ennam.kg.go/internal/service/credential_provider_test.go` — new test file
- `ennam.kg.go/internal/service/sse_stream.go` — credential injection block (commit `a69552d`)
- `ennam.kg.go/internal/handler/ai_model_guard_test.go` — 2 agentic test cases (commit `3293f93`)
- `ennam.kg.go/internal/handler/ai_functions_test.go` — agentic assertion + count bump (commit `3293f93`)
- `ennam.kg.python/src/ennam_kg/api/agentic.py` — new headers + 501 guard (commit `de461b2`)
- `ennam.kg.python/src/ennam_kg/agentic/engine.py` — _CHAT_MODEL_OVERRIDE deleted (commit `59556ca`)
- `ennam.kg.python/tests/test_agentic/test_chat_model_resolution.py` — new test file

## Current state

- All automated Go tests: 20/20 packages `ok` (`-race -count=1`)
- All Python agentic tests: 91/91 passed
- Branch: `task/implement_mcp`
- IMP-006 P4a fully implemented and verified

## Next steps

- Task 7 (live acceptance): run Docker stack, assign an Anthropic model to `ai.model.agentic` via P3 UI, verify SSE stream picks it up in logs. This requires manual testing.
- IMP-006 P4b: OpenAI-compatible provider support for agentic chat (currently returns 501).
- PR creation for `task/implement_mcp` when P4b or other planned tasks are also done.

## Blockers / Risks

- Task 7 cannot be automated; requires Docker stack running + P3 dashboard access.
- P4b (OpenAI provider) not yet planned/scoped.
