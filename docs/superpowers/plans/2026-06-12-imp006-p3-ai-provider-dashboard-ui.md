# IMP-006 P3 — AI Provider/Model Dashboard UI + Per-Function Model Dropdowns (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give admins a dashboard UI to (A) register OpenAI-compatible AI providers and manage the models under each, and (B) assign a specific model to each AI function via dropdowns (replacing the free-text `ai.model.*` cards), backed by the P2 REST API.

**Architecture:** A NextJS App-Router admin page (`/admin/settings/ai-providers`) + a per-function "AI Model Assignments" panel. All data goes through the existing BFF proxy (`/api/kg/...` → Go `/api/v1/...`) using TanStack Query hooks (fetch fn + `useQuery`/`useMutation` + invalidate), matching the repo's existing `use-settings`/`use-projects` pattern. One small Go endpoint (`GET /api/v1/ai-functions`) exposes the P2 function registry so the dropdowns are driven by the backend (single source of truth). UI uses the repo's `@base-ui/react` wrappers (`Select`, `Dialog`, `Switch`, `Button`, `Card`, `Input`) — **not Radix**.

**Tech Stack:** Next.js 16 (App Router) + React 19 + TypeScript (strict) + Tailwind v4 + `@base-ui/react` + TanStack Query; Go (stdlib `net/http`) for the one registry endpoint.

**Builds on P2** (merged). API contract consumed:
- `GET /api/v1/ai-providers` → list providers (ordered by priority).
- `POST /api/v1/ai-providers` → create `{name, provider_type, base_url, api_key, model_id, priority}`.
- `GET /api/v1/ai-providers/{id}/models` → `{models: AIModel[]}`.
- `POST /api/v1/ai-providers/{id}/models` → add `{model_id, display_name, supports_tools, supports_json}`.
- `PATCH /api/v1/ai-models/{id}` → `{display_name?, supports_tools?, supports_json?, is_active?}`.
- `DELETE /api/v1/ai-models/{id}` → 204.
- `GET /api/v1/settings` + `PUT /api/v1/settings/{key}` → `ai.model.<fn>` assignments (P2 guard validates; a capability/unknown-function/missing-model violation returns 400 — surface its message).
- **NEW (Task 1):** `GET /api/v1/ai-functions` → the `models.AIFunctions` registry.

**Verification note (important):** `ennam.kg.next` has **no test runner** (no Jest/Vitest/Playwright/RTL). Per Rule 11 (match the codebase) this plan does **not** add one. Each frontend task is verified by `npm run lint` + `npm run build` (type-checks) + an explicit manual browser check. Only Task 1 (Go) uses `go test`/`go build`.

**Scope:** Admin UI only. Agentic Path B (`ai.model.agentic`) is P4 — it is not in `AIFunctions` yet, so it won't appear in the dropdowns until P4 registers it.

---

## File Structure

**Go (create/modify):**
- `ennam.kg.go/internal/handler/ai_provider.go` — add `ListFunctions` handler + route.
- `ennam.kg.go/internal/handler/ai_functions_test.go` — handler test.

**Frontend (create):**
- `ennam.kg.next/src/types/ai-providers.ts` — `AIProvider`, `AIModel`, `AIFunction`, request types.
- `ennam.kg.next/src/hooks/use-ai-providers.ts` — catalog query + provider/model mutations.
- `ennam.kg.next/src/hooks/use-ai-functions.ts` — function registry query.
- `ennam.kg.next/src/components/settings/AIModelAssignments.tsx` — per-function dropdown panel.
- `ennam.kg.next/src/components/settings/ai-providers/ProvidersManager.tsx` — providers + models management.
- `ennam.kg.next/src/components/settings/ai-providers/CreateProviderDialog.tsx`
- `ennam.kg.next/src/components/settings/ai-providers/AddModelDialog.tsx`
- `ennam.kg.next/src/app/(dashboard)/admin/settings/ai-providers/page.tsx` — the page.

**Frontend (modify):**
- `ennam.kg.next/src/components/layout/Sidebar.tsx` — ADMIN nav item.

---

## Task 1: Go — expose the function registry (`GET /api/v1/ai-functions`)

**Files:**
- Modify: `ennam.kg.go/internal/handler/ai_provider.go`
- Test: `ennam.kg.go/internal/handler/ai_functions_test.go`

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/handler/ai_functions_test.go`:

```go
package handler

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestListFunctions(t *testing.T) {
	h := &AIProviderHandler{}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/ai-functions", nil)
	rec := httptest.NewRecorder()
	h.ListFunctions(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var body struct {
		Functions []struct {
			Key           string `json:"key"`
			DisplayName   string `json:"display_name"`
			RequiresTools bool   `json:"requires_tools"`
			RequiresJSON  bool   `json:"requires_json"`
		} `json:"functions"`
	}
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(body.Functions) < 7 {
		t.Fatalf("expected >= 7 functions, got %d", len(body.Functions))
	}
	var found bool
	for _, f := range body.Functions {
		if f.Key == "nl_query_intent" {
			found = true
			if !f.RequiresJSON {
				t.Error("nl_query_intent should require JSON")
			}
		}
	}
	if !found {
		t.Error("nl_query_intent missing from functions")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestListFunctions -v`
Expected: FAIL — `ListFunctions` undefined.

- [ ] **Step 3: Add JSON tags to the registry + the handler**

In `ennam.kg.go/internal/models/ai_function.go`, add JSON tags to `AIFunction` (it currently has none — the API needs stable field names):

```go
type AIFunction struct {
	Key           string `json:"key"`
	DisplayName   string `json:"display_name"`
	RequiresTools bool   `json:"requires_tools"`
	RequiresJSON  bool   `json:"requires_json"`
}
```

In `ennam.kg.go/internal/handler/ai_provider.go`, add the handler (near `ListModels`):

```go
// ListFunctions handles GET /api/v1/ai-functions — the routable AI-function
// registry (IMP-006), so the dashboard can render per-function model selectors.
func (h *AIProviderHandler) ListFunctions(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]interface{}{"functions": models.AIFunctions})
}
```

Register the route in `RegisterRoutes` (next to the ai-models routes):

```go
	mux.HandleFunc("GET /api/v1/ai-functions", h.ListFunctions)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestListFunctions -v && go build ./...`
Expected: PASS + clean build.

- [ ] **Step 5: Commit**

```bash
git add internal/handler/ai_provider.go internal/handler/ai_functions_test.go internal/models/ai_function.go
git commit -m "feat(ai): GET /api/v1/ai-functions exposes the function registry (IMP-006 P3)"
```

---

## Task 2: Frontend types

**Files:**
- Create: `ennam.kg.next/src/types/ai-providers.ts`

- [ ] **Step 1: Write the types**

Create `ennam.kg.next/src/types/ai-providers.ts`:

```typescript
export interface AIProvider {
  id: string;
  name: string;
  provider_type: 'openai' | 'anthropic_api' | 'claude_max';
  base_url: string;
  model_id: string;
  priority: number;
  is_active: boolean;
  status: string;
}

export interface AIModel {
  id: string;
  provider_id: string;
  model_id: string;
  display_name: string;
  supports_tools: boolean;
  supports_json: boolean;
  is_active: boolean;
}

export interface AIFunction {
  key: string;
  display_name: string;
  requires_tools: boolean;
  requires_json: boolean;
}

export interface ProviderWithModels extends AIProvider {
  models: AIModel[];
}

export interface CreateProviderRequest {
  name: string;
  provider_type: 'openai';
  base_url: string;
  api_key: string;
  model_id: string;
  priority: number;
}

export interface AddModelRequest {
  model_id: string;
  display_name: string;
  supports_tools: boolean;
  supports_json: boolean;
}

export interface UpdateModelRequest {
  display_name?: string;
  supports_tools?: boolean;
  supports_json?: boolean;
  is_active?: boolean;
}
```

- [ ] **Step 2: Verify it type-checks**

Run: `cd ennam.kg.next && npx tsc --noEmit`
Expected: no errors from this file.

- [ ] **Step 3: Commit**

```bash
git add src/types/ai-providers.ts
git commit -m "feat(ui): AI provider/model/function types (IMP-006 P3)"
```

---

## Task 3: Data hooks

**Files:**
- Create: `ennam.kg.next/src/hooks/use-ai-providers.ts`
- Create: `ennam.kg.next/src/hooks/use-ai-functions.ts`

- [ ] **Step 1: Write the function-registry hook**

Create `ennam.kg.next/src/hooks/use-ai-functions.ts`:

```typescript
'use client';

import { useQuery } from '@tanstack/react-query';
import type { AIFunction } from '@/types/ai-providers';

async function fetchFunctions(): Promise<AIFunction[]> {
  const res = await fetch('/api/kg/ai-functions');
  if (!res.ok) throw new Error(`Failed to fetch AI functions: ${res.statusText}`);
  const data = await res.json();
  return data.functions ?? [];
}

export function useAIFunctions() {
  return useQuery({ queryKey: ['ai-functions'], queryFn: fetchFunctions, staleTime: 300_000 });
}
```

- [ ] **Step 2: Write the providers + models hook**

Create `ennam.kg.next/src/hooks/use-ai-providers.ts`:

```typescript
'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type {
  AIProvider,
  AIModel,
  ProviderWithModels,
  CreateProviderRequest,
  AddModelRequest,
  UpdateModelRequest,
} from '@/types/ai-providers';

async function fetchProviders(): Promise<AIProvider[]> {
  const res = await fetch('/api/kg/ai-providers');
  if (!res.ok) throw new Error(`Failed to fetch providers: ${res.statusText}`);
  const data = await res.json();
  // List may return a bare array or { providers: [...] } / { items: [...] }.
  if (Array.isArray(data)) return data;
  return data.providers ?? data.items ?? [];
}

async function fetchModels(providerId: string): Promise<AIModel[]> {
  const res = await fetch(`/api/kg/ai-providers/${providerId}/models`);
  if (!res.ok) throw new Error(`Failed to fetch models: ${res.statusText}`);
  const data = await res.json();
  return data.models ?? [];
}

// Catalog = every provider with its models, for the management table + the
// per-function dropdowns. One query so loading/refetch is unified.
async function fetchCatalog(): Promise<ProviderWithModels[]> {
  const providers = await fetchProviders();
  return Promise.all(
    providers.map(async (p) => ({ ...p, models: await fetchModels(p.id) })),
  );
}

export function useAICatalog() {
  return useQuery({ queryKey: ['ai-catalog'], queryFn: fetchCatalog, staleTime: 30_000 });
}

async function postProvider(input: CreateProviderRequest): Promise<AIProvider> {
  const res = await fetch('/api/kg/ai-providers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error((await res.text()) || `Failed to create provider`);
  return res.json();
}

async function postModel(args: { providerId: string; input: AddModelRequest }): Promise<AIModel> {
  const res = await fetch(`/api/kg/ai-providers/${args.providerId}/models`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args.input),
  });
  if (!res.ok) throw new Error((await res.text()) || `Failed to add model`);
  return res.json();
}

async function patchModel(args: { id: string; input: UpdateModelRequest }): Promise<AIModel> {
  const res = await fetch(`/api/kg/ai-models/${args.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args.input),
  });
  if (!res.ok) throw new Error((await res.text()) || `Failed to update model`);
  return res.json();
}

async function deleteModel(id: string): Promise<void> {
  const res = await fetch(`/api/kg/ai-models/${id}`, { method: 'DELETE' });
  if (!res.ok && res.status !== 204) throw new Error((await res.text()) || `Failed to delete model`);
}

function useInvalidateCatalog() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ['ai-catalog'] });
}

export function useCreateProvider() {
  const invalidate = useInvalidateCatalog();
  return useMutation({ mutationFn: postProvider, onSuccess: invalidate, retry: false });
}

export function useAddModel() {
  const invalidate = useInvalidateCatalog();
  return useMutation({ mutationFn: postModel, onSuccess: invalidate, retry: false });
}

export function useUpdateModel() {
  const invalidate = useInvalidateCatalog();
  return useMutation({ mutationFn: patchModel, onSuccess: invalidate, retry: false });
}

export function useDeleteModel() {
  const invalidate = useInvalidateCatalog();
  return useMutation({ mutationFn: deleteModel, onSuccess: invalidate, retry: false });
}
```

- [ ] **Step 3: Verify type-check**

Run: `cd ennam.kg.next && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/hooks/use-ai-providers.ts src/hooks/use-ai-functions.ts
git commit -m "feat(ui): hooks for AI provider/model catalog + function registry (IMP-006 P3)"
```

---

## Task 4: Per-function model assignment panel

**Files:**
- Create: `ennam.kg.next/src/components/settings/AIModelAssignments.tsx`

- [ ] **Step 1: Write the component**

Create `ennam.kg.next/src/components/settings/AIModelAssignments.tsx`:

```typescript
'use client';

import { useState, useEffect } from 'react';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useAICatalog } from '@/hooks/use-ai-providers';
import { useAIFunctions } from '@/hooks/use-ai-functions';
import { useSettings, useUpdateSetting } from '@/hooks/use-settings';
import type { AIFunction, AIModel } from '@/types/ai-providers';

const AUTO = 'auto';

function modelDisabled(fn: AIFunction, m: AIModel): boolean {
  if (!m.is_active) return true;
  if (fn.requires_tools && !m.supports_tools) return true;
  if (fn.requires_json && !m.supports_json) return true;
  return false;
}

export default function AIModelAssignments() {
  const catalog = useAICatalog();
  const functions = useAIFunctions();
  const settings = useSettings();
  const updateSetting = useUpdateSetting();
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(t);
  }, [toast]);

  const settingValue = (fnKey: string): string => {
    const s = settings.data?.settings.find((x) => x.key === `ai.model.${fnKey}`);
    const v = s?.value;
    return typeof v === 'string' && v.trim() !== '' ? v : AUTO;
  };

  const onChange = (fnKey: string, value: string) => {
    updateSetting.mutate(
      { key: `ai.model.${fnKey}`, input: { value } },
      {
        onSuccess: () => setToast({ message: `Saved ai.model.${fnKey}`, type: 'success' }),
        onError: (e) => setToast({ message: (e as Error).message, type: 'error' }),
      },
    );
  };

  if (catalog.isLoading || functions.isLoading || settings.isLoading) {
    return <div className="text-sm text-[#5C6080]">Loading AI functions…</div>;
  }

  const allModels = (catalog.data ?? []).flatMap((p) =>
    p.models.map((m) => ({ provider: p.name, model: m })),
  );

  return (
    <div className="space-y-4">
      {toast && (
        <div
          className={`rounded-lg px-4 py-3 text-sm ${
            toast.type === 'success' ? 'bg-green/10 text-green' : 'bg-red/10 text-red'
          }`}
        >
          {toast.message}
        </div>
      )}
      {(functions.data ?? []).map((fn) => {
        const current = settingValue(fn.key);
        return (
          <div
            key={fn.key}
            className="rounded-lg border border-[#2A2E45] bg-[#1A1D2E] p-4"
          >
            <div className="mb-1 flex items-center justify-between">
              <label className="text-sm font-medium text-[#F0F0F8]">{fn.display_name}</label>
              <code className="text-xs text-[#5C6080]">ai.model.{fn.key}</code>
            </div>
            <Select value={current} onValueChange={(v) => v && onChange(fn.key, v as string)}>
              <SelectTrigger className="w-full max-w-md border-[#2A2E45] bg-[#1A1D2E] text-[#F0F0F8]">
                <SelectValue placeholder="Auto (priority)" />
              </SelectTrigger>
              <SelectContent className="bg-[#1A1D2E] border-[#2A2E45]">
                <SelectItem value={AUTO} className="text-[#F0F0F8] focus:bg-[#2A2E45]">
                  Auto (priority)
                </SelectItem>
                {allModels.map(({ provider, model }) => {
                  const disabled = modelDisabled(fn, model);
                  return (
                    <SelectItem
                      key={model.id}
                      value={model.id}
                      disabled={disabled}
                      className="text-[#F0F0F8] focus:bg-[#2A2E45]"
                    >
                      {model.display_name} · {provider}
                      {disabled && <span className="ml-2 text-xs text-[#5C6080]">(incompatible)</span>}
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Verify type-check + lint**

Run: `cd ennam.kg.next && npx tsc --noEmit && npm run lint`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/components/settings/AIModelAssignments.tsx
git commit -m "feat(ui): per-function AI model assignment dropdowns (IMP-006 P3)"
```

---

## Task 5: Create-provider dialog

**Files:**
- Create: `ennam.kg.next/src/components/settings/ai-providers/CreateProviderDialog.tsx`

- [ ] **Step 1: Write the dialog**

Create `ennam.kg.next/src/components/settings/ai-providers/CreateProviderDialog.tsx`:

```typescript
'use client';

import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCreateProvider } from '@/hooks/use-ai-providers';

export default function CreateProviderDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [modelId, setModelId] = useState('');
  const [priority, setPriority] = useState('50');
  const create = useCreateProvider();

  const reset = () => {
    setName(''); setBaseUrl(''); setApiKey(''); setModelId(''); setPriority('50');
  };
  const valid = name.trim() && baseUrl.trim() && apiKey.trim() && modelId.trim();

  const submit = () => {
    if (!valid) return;
    create.mutate(
      {
        name: name.trim(),
        provider_type: 'openai',
        base_url: baseUrl.trim(),
        api_key: apiKey.trim(),
        model_id: modelId.trim(),
        priority: Number(priority) || 50,
      },
      { onSuccess: () => { reset(); onOpenChange(false); } },
    );
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) reset(); onOpenChange(v); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add OpenAI-compatible provider</DialogTitle>
          <DialogDescription>
            Register a connection (e.g. BytePlus Ark). Its default model is auto-seeded.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Input placeholder="Name (e.g. BytePlus Ark)" value={name} onChange={(e) => setName(e.target.value)} />
          <Input placeholder="Base URL (https://ark.../api/coding/v3)" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          <Input placeholder="API key" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          <Input placeholder="Default model id (e.g. gpt-oss-120b)" value={modelId} onChange={(e) => setModelId(e.target.value)} />
          <Input placeholder="Priority (lower = preferred)" value={priority} onChange={(e) => setPriority(e.target.value)} />
          {create.isError && <p className="text-sm text-red">{(create.error as Error).message}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} disabled={!valid || create.isPending}>
            {create.isPending ? 'Adding…' : 'Add provider'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Verify type-check**

Run: `cd ennam.kg.next && npx tsc --noEmit`
Expected: no errors. (If `Input`/`Button`/`Dialog` named exports differ, fix imports to match `src/components/ui/*`.)

- [ ] **Step 3: Commit**

```bash
git add src/components/settings/ai-providers/CreateProviderDialog.tsx
git commit -m "feat(ui): create OpenAI-compatible provider dialog (IMP-006 P3)"
```

---

## Task 6: Add-model dialog

**Files:**
- Create: `ennam.kg.next/src/components/settings/ai-providers/AddModelDialog.tsx`

- [ ] **Step 1: Write the dialog**

Create `ennam.kg.next/src/components/settings/ai-providers/AddModelDialog.tsx`:

```typescript
'use client';

import { useState } from 'react';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { useAddModel } from '@/hooks/use-ai-providers';

export default function AddModelDialog({
  providerId,
  open,
  onOpenChange,
}: {
  providerId: string;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [modelId, setModelId] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [supportsJson, setSupportsJson] = useState(true);
  const [supportsTools, setSupportsTools] = useState(false);
  const add = useAddModel();

  const reset = () => { setModelId(''); setDisplayName(''); setSupportsJson(true); setSupportsTools(false); };

  const submit = () => {
    if (!modelId.trim()) return;
    add.mutate(
      {
        providerId,
        input: {
          model_id: modelId.trim(),
          display_name: displayName.trim() || modelId.trim(),
          supports_json: supportsJson,
          supports_tools: supportsTools,
        },
      },
      { onSuccess: () => { reset(); onOpenChange(false); } },
    );
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) reset(); onOpenChange(v); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add model</DialogTitle>
          <DialogDescription>A model id served by this connection.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Input placeholder="Model id (e.g. glm-4.7)" value={modelId} onChange={(e) => setModelId(e.target.value)} />
          <Input placeholder="Display name (optional)" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          <label className="flex items-center justify-between text-sm text-[#F0F0F8]">
            Supports JSON output
            <Switch checked={supportsJson} onCheckedChange={setSupportsJson} />
          </label>
          <label className="flex items-center justify-between text-sm text-[#F0F0F8]">
            Supports tool-calling
            <Switch checked={supportsTools} onCheckedChange={setSupportsTools} />
          </label>
          {add.isError && <p className="text-sm text-red">{(add.error as Error).message}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} disabled={!modelId.trim() || add.isPending}>
            {add.isPending ? 'Adding…' : 'Add model'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

> Base UI `Switch` uses `checked` + `onCheckedChange(checked: boolean)`. Confirm against `src/components/ui/switch.tsx`; if it forwards a different handler name, adjust.

- [ ] **Step 2: Verify type-check**

Run: `cd ennam.kg.next && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/components/settings/ai-providers/AddModelDialog.tsx
git commit -m "feat(ui): add-model dialog with capability toggles (IMP-006 P3)"
```

---

## Task 7: Providers manager (list providers + their models)

**Files:**
- Create: `ennam.kg.next/src/components/settings/ai-providers/ProvidersManager.tsx`

- [ ] **Step 1: Write the manager component**

Create `ennam.kg.next/src/components/settings/ai-providers/ProvidersManager.tsx`:

```typescript
'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { useAICatalog, useUpdateModel, useDeleteModel } from '@/hooks/use-ai-providers';
import CreateProviderDialog from './CreateProviderDialog';
import AddModelDialog from './AddModelDialog';

export default function ProvidersManager() {
  const catalog = useAICatalog();
  const updateModel = useUpdateModel();
  const deleteModel = useDeleteModel();
  const [createOpen, setCreateOpen] = useState(false);
  const [addModelFor, setAddModelFor] = useState<string | null>(null);

  if (catalog.isLoading) return <div className="text-sm text-[#5C6080]">Loading providers…</div>;
  if (catalog.isError) return <div className="text-sm text-red">{(catalog.error as Error).message}</div>;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setCreateOpen(true)}>Add provider</Button>
      </div>

      {(catalog.data ?? []).map((p) => (
        <div key={p.id} className="rounded-lg border border-[#2A2E45] bg-[#1A1D2E] p-4">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <div className="text-sm font-medium text-[#F0F0F8]">{p.name}</div>
              <div className="text-xs text-[#5C6080]">
                {p.provider_type} · {p.base_url} · priority {p.priority}
              </div>
            </div>
            <Button variant="outline" onClick={() => setAddModelFor(p.id)}>Add model</Button>
          </div>

          <div className="space-y-1">
            {p.models.length === 0 && (
              <div className="text-xs text-[#5C6080]">No models — add one.</div>
            )}
            {p.models.map((m) => (
              <div
                key={m.id}
                className="flex items-center justify-between rounded border border-[#2A2E45] px-3 py-2"
              >
                <div className="text-sm text-[#F0F0F8]">
                  {m.display_name}{' '}
                  <code className="text-xs text-[#5C6080]">{m.model_id}</code>
                  {!m.supports_json && <span className="ml-2 text-xs text-[#5C6080]">no-json</span>}
                  {m.supports_tools && <span className="ml-2 text-xs text-[#00D4FF]">tools</span>}
                </div>
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-2 text-xs text-[#5C6080]">
                    Active
                    <Switch
                      checked={m.is_active}
                      onCheckedChange={(v) => updateModel.mutate({ id: m.id, input: { is_active: v } })}
                    />
                  </label>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => {
                      if (confirm(`Delete model ${m.model_id}?`)) deleteModel.mutate(m.id);
                    }}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

      <CreateProviderDialog open={createOpen} onOpenChange={setCreateOpen} />
      {addModelFor && (
        <AddModelDialog
          providerId={addModelFor}
          open={!!addModelFor}
          onOpenChange={(v) => { if (!v) setAddModelFor(null); }}
        />
      )}
    </div>
  );
}
```

> `Button` has a `size` prop (`sm`, `icon-sm`) and variants (`outline`, `destructive`) per `src/components/ui/button.tsx` — confirm the exact variant names. `confirm()` is the repo's existing destructive-confirm idiom (see `KeyTable.tsx`); if it uses a dialog instead, mirror that.

- [ ] **Step 2: Verify type-check + lint**

Run: `cd ennam.kg.next && npx tsc --noEmit && npm run lint`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/components/settings/ai-providers/ProvidersManager.tsx
git commit -m "feat(ui): providers manager — list providers + models, toggle active, delete (IMP-006 P3)"
```

---

## Task 8: Page + sidebar nav

**Files:**
- Create: `ennam.kg.next/src/app/(dashboard)/admin/settings/ai-providers/page.tsx`
- Modify: `ennam.kg.next/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Write the page**

Create `ennam.kg.next/src/app/(dashboard)/admin/settings/ai-providers/page.tsx`:

```typescript
import ProvidersManager from '@/components/settings/ai-providers/ProvidersManager';
import AIModelAssignments from '@/components/settings/AIModelAssignments';

export default function AIProvidersPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-8 p-6">
      <div>
        <h1 className="text-xl font-semibold text-[#F0F0F8]">AI Providers & Models</h1>
        <p className="text-sm text-[#5C6080]">
          Register OpenAI-compatible providers and assign a model to each AI function.
        </p>
      </div>

      <section>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-[#5C6080]">Providers</h2>
        <ProvidersManager />
      </section>

      <section>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-[#5C6080]">
          Per-function model
        </h2>
        <AIModelAssignments />
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Add the sidebar nav item**

In `ennam.kg.next/src/components/layout/Sidebar.tsx`, in the `ADMIN` section's `items` array (where `Claude AI` and `Settings` are), add an entry. Reuse an already-imported icon (e.g. `Sparkles` or `Database`) to avoid a new import; if none fits, import one from `lucide-react`:

```typescript
      { href: '/admin/settings/ai-providers', label: 'AI Providers', icon: Sparkles },
```
> Verify `Sparkles` is imported at the top of `Sidebar.tsx`; it is used by the `Chat Demo` nav item, so it is already in scope. Place this entry right before `{ href: '/admin/settings', label: 'Settings', icon: Settings }`.

- [ ] **Step 3: Verify build**

Run: `cd ennam.kg.next && npx tsc --noEmit && npm run build`
Expected: builds clean; `/admin/settings/ai-providers` appears in the route list.

- [ ] **Step 4: Commit**

```bash
git add "src/app/(dashboard)/admin/settings/ai-providers/page.tsx" src/components/layout/Sidebar.tsx
git commit -m "feat(ui): AI Providers admin page + sidebar nav (IMP-006 P3)"
```

---

## Task 9: Live acceptance (manual, against the running stack)

Start the dashboard (`cd ennam.kg.next && npm run dev`, default :3500) with the Docker stack up, log in as admin, open **Admin → AI Providers**.

- [ ] **Step 1: Providers + auto-seed** — the existing **BytePlus Ark** provider shows with its `gpt-oss-120b` model. Click **Add provider**, fill a throwaway OpenAI-compatible connection (BytePlus base_url + key + `model_id=glm-4.7`), submit → it appears with `glm-4.7` auto-seeded.
- [ ] **Step 2: Model management** — under the new provider, **Add model** (`kimi-k2.5`, JSON on, tools off) → appears; toggle **Active** off/on; **Delete** the throwaway model and provider.
- [ ] **Step 3: Per-function dropdown** — in **Per-function model**, the `Ingestion extraction` row shows the current assignment (`gpt-oss-120b · BytePlus Ark`). Change another function (e.g. `Smart-context table filter`) to a model → a success toast; reload and confirm it persisted.
- [ ] **Step 4: Guard surfaced** — try assigning a model whose capability is missing (e.g. a `supports_json=false` model to a JSON function): the option is **disabled** in the dropdown; if forced via API it returns 400 — confirm the panel shows the error toast (set a model to `supports_json=false`, then attempt assignment).
- [ ] **Step 5: Auto (priority)** — set a function back to `Auto (priority)` → persists as `"auto"`; routing falls back to priority (no `routed by assignment` log for that function).

---

## Done criteria (P3)

- `GET /api/v1/ai-functions` returns the 7-function registry; `go test ./internal/handler/ -run TestListFunctions` green.
- `/admin/settings/ai-providers` lists providers + models, creates OpenAI-compatible providers, adds/toggles/deletes models, and assigns a model per function via dropdowns (with incompatible models disabled + server-guard errors surfaced).
- `npx tsc --noEmit`, `npm run lint`, `npm run build` all clean.
- Sidebar links to the new page.

**Not in P3:** agentic Path B model selection (P4 — registers `agentic` in `AIFunctions` with `requires_tools=true`, after which it appears in the dropdowns automatically). Test infrastructure for the frontend (the repo has none; out of scope).
```
