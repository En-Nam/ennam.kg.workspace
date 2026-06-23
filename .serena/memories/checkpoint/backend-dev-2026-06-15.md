# Checkpoint: backend-dev — 2026-06-15

## What was done

### IMP-006 P1 Implementation (all 8 tasks complete + Task 9 live test)
- Migration 000057: `ai_models` table (one-to-many under `ai_providers`)
- `internal/models/ai_model.go`: `AIModel` struct
- `internal/store/ai_model.go`: `AIModelStore` (Create, GetByID, ListByProvider)
- `internal/models/ai_provider.go`: `AIRequest.Model` field (`json:"-"`)
- `internal/ai/openai.go`: model override + `openAICompletionsURL` (handles versioned paths like `/v3`)
- `internal/ai/anthropic.go`: `pickModel` helper for override
- `internal/ai/resolver.go`: `ModelResolver` interface + `ModelResolved` type
- `internal/service/model_resolver.go`: `SettingsModelResolver` (reads `ai.model.<requestType>` setting)
- `internal/ai/selector.go`: resolve-before-priority dispatch with `IsActive`, circuit breaker, usage logging
- `internal/ai/selector_resolve_test.go`: stub-based routing test
- `cmd/kg-server/main.go`: wires `SettingsModelResolver` to `aiSelector` at startup
- `ennam.kg.python/src/ennam_kg/ai_client/models.py`: `request_type` field + corrected `to_go_payload`
- `ennam.kg.python/src/ennam_kg/ingestion/pipeline/extract.py`: `request_type="extraction"` added

### Task 9 — Live acceptance test with BytePlus Ark
- Registered BytePlus provider (`provider_type=openai`, base_url with `/v3` path)
- Inserted `ai_models` row manually (P1 gap: new providers don't auto-seed)
- Set `ai.model.extraction = <ai_models_id>`
- Confirmed routing: `"ai: routed by assignment" request_type=extraction provider=c336ca5c... model=gpt-oss-120b`
- Confirmed negative: with `"auto"`, no routing — falls back to priority loop

## Files changed
All IMP-006 P1 files listed above + Docker images rebuilt

## Current state
- IMP-006 P1: COMPLETE and live-verified
- Docker stack running with rebuilt images (kg-server + worker)
- BytePlus provider active: `c336ca5c-f845-4b5c-8dad-3e18562ff6f4`
- `ai.model.extraction` → `68aeaf40-b7a0-4c70-9b45-6e1509dc7258` (restored after negative test)

## Next steps
- IMP-006 P2: Admin UI for ai_models registry (model list per provider)
- IMP-006 P2: Auto-seed ai_models on new provider creation (P1 gap)
- IMP-006 P2: Route other function types (e.g., `nl_query`, `summarization`)
- Commit IMP-006 P1 code changes to git

## Blockers / Risks (P1)
- Anthropic credit exhausted — BytePlus is the only working AI provider currently
- P1 gap: manually inserted ai_models row; new providers created via API won't auto-seed

---

## IMP-006 P2 Implementation (all 8 tasks + review fix)

### What was done
- Task 1: AIFunction registry (`internal/models/ai_function.go`) — 7 real Path-A functions with capability flags
- Task 2: AIModelStore.Update + Delete — nil-DB guards + RETURNING scan
- Task 3: Auto-seed `ai_models` row on provider create — non-fatal warn on failure
- Task 4: ai_models CRUD endpoints (ListModels, AddModel, UpdateModel, DeleteModel) + 4 new routes
- Task 5: Assignment/capability guard (`validateAIModelAssignment`) — rejects unknown function, missing model, capability mismatch; "auto" always valid
- Task 6: Wired SetModelStore + SetAIModelStore in main.go
- Task 7: Migration 000058 — reconciled legacy free-text ai.model.* (sql_generation orphan removed)
- Task 8: Live acceptance — all checks passed (auto-seed, CRUD, 400/400/200 guard, 204 delete)
- Fix: 409 on duplicate ai_models unique constraint (pq.Error code 23505)

### P2 commits (ennam.kg.go)
- 91ca084 fix(ai): return 409 on duplicate ai_models unique constraint violation
- d2a2cff feat(ai): reconcile legacy free-text ai.model.* settings to the registry (IMP-006 P2)
- 769e054 feat(ai): wire ai_models store into provider + settings handlers (IMP-006 P2)
- efcdd41 feat(settings): guard ai.model.<function> assignments (IMP-006 P2)
- 8d38b7c feat(ai): ai_models CRUD endpoints under provider connections (IMP-006 P2)
- 7f917c5 feat(ai): auto-seed ai_models row when a provider is registered (IMP-006 P2)
- 18af8ba feat(ai): AIModelStore Update + Delete (IMP-006 P2)
- 81fa52e feat(ai): AIFunction registry of real request-type functions (IMP-006 P2)

### P2 current state
- All 20 Go packages pass, build clean
- Migration 000058 applied: ai.model.extraction=UUID, others=auto
- ai.model.extraction → 68aeaf40... (BytePlus gpt-oss-120b)

### P2 final verification (2026-06-15 end-of-session)
- `go test -race ./... -count=1`: 20/20 packages PASS, no race conditions
- `go vet ./...`: exit 0, no issues
- `git status`: 1 unrelated whitespace diff in `internal/bridge/handler.go` (gofmt alignment, NOT committed to P2)
- All 8 P2 commits clean, no uncommitted P2 changes
- Live re-checks: guard 400/400/200/200, PATCH model 200, capability mismatch 400, DB migration version=58 dirty=false

### Next steps
- P3: Dashboard UI (provider/model management + per-function dropdowns)
- P4: Agentic Path B OpenAI-compatible client (RequiresTools=true)
- Minor: commit bridge/handler.go whitespace fix separately if desired

---

## IMP-006 P3 Implementation (Tasks 1–8 complete, Task 9 pending manual test)

### What was done

**Go:**
- `internal/models/ai_function.go`: thêm JSON tags cho `AIFunction` struct (`key`, `display_name`, `requires_tools`, `requires_json`)
- `internal/handler/ai_provider.go`: thêm `ListFunctions` handler + route `GET /api/v1/ai-functions`
- `internal/handler/ai_functions_test.go` (mới): `TestListFunctions` — PASS

**Frontend (ennam.kg.next):**
- `src/types/ai-providers.ts` (mới): AIProvider, AIModel, AIFunction, ProviderWithModels, CreateProviderRequest, AddModelRequest, UpdateModelRequest
- `src/types/settings.ts`: thêm `category?: SettingCategory` vào `UpdateSettingRequest`
- `src/hooks/use-ai-functions.ts` (mới): `useAIFunctions()` query (staleTime 5 phút)
- `src/hooks/use-ai-providers.ts` (mới): `useAICatalog()` + useCreateProvider, useAddModel, useUpdateModel, useDeleteModel
- `src/components/settings/AIModelAssignments.tsx` (mới): per-function model dropdown với guard incompatible + toast
- `src/components/settings/ai-providers/CreateProviderDialog.tsx` (mới): dialog tạo provider
- `src/components/settings/ai-providers/AddModelDialog.tsx` (mới): dialog thêm model (named export)
- `src/components/settings/ai-providers/ProvidersManager.tsx` (mới): list providers + models, toggle/delete
- `src/app/(dashboard)/admin/settings/ai-providers/page.tsx` (mới): Server Component page admin
- `src/components/layout/Sidebar.tsx`: thêm "AI Providers" nav (Sparkles) trước Settings

### P3 verification
- Go: 20/20 packages PASS (full `./...` suite), `go build ./...` clean
- Frontend: `npx tsc --noEmit` exit 0 (strict), lint 10 files mới exit 0, `npm run build` ✓ — route `/admin/settings/ai-providers` trong build output

### P3 current state
- Task 9 (manual acceptance) chưa thực hiện — cần Docker stack running
- `AddModelDialog` dùng named export (không phải default) — import trong ProvidersManager đã đúng

### Next steps
- Task 9: manual acceptance test (login admin → AI Providers page)
- P4: IMP-006 P4 — Agentic Path B (`requires_tools=true`, `ai.model.agentic`)
