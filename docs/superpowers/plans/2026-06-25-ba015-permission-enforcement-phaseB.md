# BA-015 FR-005 Role-Based Permission Enforcement — Phase B

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend FR-005 enforcement to the **entity-id** write endpoints — node update/deprecate, KG-gen node/edge edits, and data-source update/sync — that identify the target by `r.PathValue("id")` and therefore need the entity's own project resolved before the role check.

**Prerequisite:** Phase A is implemented and merged — `requireProjectRole`, `writeInsufficientRole`, `roleAtLeast`, `ProjectRoleResolverFunc` exist in `internal/handler/project_role.go`, and `DataSourceHandler` + `KGGenerationHandler` already have a `roleResolver` field + `SetRoleResolver` wired in `main.go` (`roleResolver` closure over `projectSvc.GetMembership`).

**Architecture:** Resolve the entity's owning `project_id` via an injected `EntityProjectFunc` (a closure over an existing store getter), then reuse Phase A's `requireProjectRole`. A new shared helper `requireProjectRoleForEntity` does the bypass checks (global admin / legacy API key) **before** any lookup, then resolves the project and delegates. Enforcement stays at the handler layer (consistent with Phase A and FR-004); no role logic enters the service layer.

**Tech Stack:** Go stdlib `net/http`, `internal/handler` (`requireProjectRole`, `isGlobalAdmin`, `resolveUserID`, `errorResponse`), `internal/store` (`NodeStore.GetNode`, new `EdgeStore.GetProjectID`), `internal/service.DataSourceService.Get`, `internal/middleware.GetUserIdentity`.

## Global Constraints

- **Reuse Phase A primitives** — do NOT re-define `requireProjectRole`/`writeInsufficientRole`/`roleAtLeast`/`ProjectRoleResolverFunc`. They live in `internal/handler/project_role.go`.
- **The "kg-nodes/kg-edges" are rows in `knowledge_nodes`/`knowledge_edges`** — `KGGenerationStore.ConfirmEdge` does `UPDATE knowledge_edges WHERE id=$1`; `UpdateNodeDescription` targets `knowledge_nodes`. Both tables have a `project_id` column (verified: `models.KnowledgeNode.ProjectID`, `models.KnowledgeEdge.ProjectID`). So every entity-id maps to a single row carrying `project_id` — no multi-hop.
- **Lookup availability (verified):** node→project via `NodeStore.GetNode(ctx, id) (*models.KnowledgeNode, error)`; data-source→project via `DataSourceService.Get(ctx, id) (*models.DataSource, error)`. **No edge getter exists** — Task 1 adds `EdgeStore.GetProjectID`.
- **Bypass rules (same as Phase A):** `isGlobalAdmin(r)` → allow; `middleware.GetUserIdentity(r.Context()) == nil` (legacy API-key caller) → allow. Both checks run BEFORE the entity lookup so MCP/CLI never trigger a DB read and never 403.
- **BR-005.6 403 body** (`{"error":"insufficient project role","required":"<min>","actual":"<role|none>"}`) is emitted by the reused `writeInsufficientRole`. A failed/empty entity lookup returns **404** (`errorResponse(w, 404, ...)`), not 403 — the entity is absent.
- **Min role:** all Phase B write operations are min `developer` (matrix: create/update nodes, create edges, run sync/extract, manage data sources, KG generation are all developer-level).
- **Guard placement (IMPORTANT):** insert the guard **immediately after the path-id validation block** (`id := r.PathValue("id")` + the `if id == ""` check) and **BEFORE the request body is decoded**. The guard needs only `entityID` (from the path), not the body. Placing it before decode means: (1) zero-value-handler unit tests (nil logger/svc) return 403 without panic — nothing touches `h.logger`/`h.svc`/the body first; (2) tests don't need a valid request body; (3) an empty/invalid body never produces a 400 that masks the 403. Authorize-before-input-validation is intentional here. The injected lookup + resolver are set on the handler in the test.
- **main.go scope:** `nodeStore` and `edgeStore` are in scope at the existing `roleResolver` wiring point (~line 649); `projectSvc` at line 599. Wire all Phase B injections there, after `projectSvc` is defined.
- **Tests:** Go table-driven, `package handler`, inject identity via `context.WithValue(ctx, middleware.UserIdentityKey, …)`. `go test -race ./internal/handler/... ./internal/store/...`.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `ennam.kg.go/internal/store/edge.go` | Modify | Add `GetProjectID(ctx, id) (string, error)` |
| `ennam.kg.go/internal/store/edge_test.go` | Modify | Test for `GetProjectID` (DB-backed, mirrors existing edge store tests) |
| `ennam.kg.go/internal/handler/project_role.go` | Modify | Add `EntityProjectFunc` type + `requireProjectRoleForEntity` helper |
| `ennam.kg.go/internal/handler/project_role_test.go` | Modify | Unit tests for `requireProjectRoleForEntity` (viewer 403, lookup-miss 404, bypasses) |
| `ennam.kg.go/internal/handler/update.go` | Modify | `roleResolver` + `nodeProject EntityProjectFunc` fields + setters; guard `HandleUpdateNode` + 6 per-type |
| `ennam.kg.go/internal/handler/deprecate.go` | Modify | `roleResolver` + `nodeProject` fields + setters; guard `HandleDeprecateNode` |
| `ennam.kg.go/internal/handler/datasource.go` | Modify | Guard `Update`/`Delete`/`TestConnection`/`ExtractSchema`/`SyncSchema` via `h.svc.Get` |
| `ennam.kg.go/internal/handler/kg_generation.go` | Modify | `nodeProject` + `edgeProject` fields + setters; guard `UpdateNodeDescription` (node) + `UpdateConfidence`/`ConfirmEdge`/`RejectEdge`/`UnrejectEdge` (edge) |
| `ennam.kg.go/cmd/kg-server/main.go` | Modify | Build node/edge `EntityProjectFunc` closures; inject into the handlers above |

---

## Task 1: `EdgeStore.GetProjectID` + `requireProjectRoleForEntity` helper

**Files:**
- Modify: `ennam.kg.go/internal/store/edge.go`
- Modify: `ennam.kg.go/internal/store/edge_test.go`
- Modify: `ennam.kg.go/internal/handler/project_role.go`
- Modify: `ennam.kg.go/internal/handler/project_role_test.go`

**Interfaces:**
- Produces: `func (s *EdgeStore) GetProjectID(ctx context.Context, id string) (string, error)`
- Produces: `type EntityProjectFunc func(ctx context.Context, entityID string) (string, error)`
- Produces: `func requireProjectRoleForEntity(w http.ResponseWriter, r *http.Request, entityID string, minRole models.ProjectMemberRole, lookup EntityProjectFunc, resolver ProjectRoleResolverFunc) bool`
- Consumes: Phase A `requireProjectRole`, `isGlobalAdmin`, `errorResponse`, `middleware.GetUserIdentity`.

- [ ] **Step 1: Write the failing store test**

In `ennam.kg.go/internal/store/edge_test.go`, add a test mirroring the existing edge-store DB test setup (use the same test DB helper / fixtures the file already uses — read the file first to match its `setupTestDB`/seed pattern). The test creates an edge with a known `project_id`, then asserts `GetProjectID` returns it, and returns an error (or empty) for an unknown id.

```go
func TestEdgeStore_GetProjectID(t *testing.T) {
	// Arrange: use the file's existing DB setup + an inserted edge with project_id.
	// (Match the helper this file already uses to create edges/nodes.)
	store, projectID, edgeID := setupEdgeWithProject(t) // adapt to existing helpers

	// Act
	got, err := store.GetProjectID(context.Background(), edgeID)

	// Assert
	if err != nil {
		t.Fatalf("GetProjectID: unexpected error: %v", err)
	}
	if got != projectID {
		t.Fatalf("GetProjectID = %q, want %q", got, projectID)
	}

	// Unknown id → error.
	if _, err := store.GetProjectID(context.Background(), "00000000-0000-0000-0000-000000000000"); err == nil {
		t.Fatal("expected error for unknown edge id")
	}
}
```

> Read `edge_test.go` and `edge.go` first: reuse the exact test-DB bootstrap and edge-creation helper already present so the test compiles and runs in the existing suite. If the suite skips when no DB is available, follow that same skip guard.

- [ ] **Step 2: Run the store test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestEdgeStore_GetProjectID -v`
Expected: FAIL — `GetProjectID` undefined.

- [ ] **Step 3: Implement `GetProjectID` in `edge.go`**

```go
// GetProjectID returns the project_id of a single edge by its ID.
// Returns sql.ErrNoRows (wrapped) if the edge does not exist.
func (s *EdgeStore) GetProjectID(ctx context.Context, id string) (string, error) {
	var projectID string
	err := s.db.QueryRowContext(ctx,
		`SELECT project_id FROM knowledge_edges WHERE id = $1`, id).Scan(&projectID)
	if err != nil {
		return "", fmt.Errorf("get edge project id: %w", err)
	}
	return projectID, nil
}
```

Confirm `EdgeStore` holds its DB handle as `s.db` (read the struct in `edge.go`); match the field name and the existing query style (`QueryRowContext`). Ensure `fmt` is imported.

- [ ] **Step 4: Run the store test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestEdgeStore_GetProjectID -v`
Expected: PASS

- [ ] **Step 5: Write the failing helper tests**

Append to `ennam.kg.go/internal/handler/project_role_test.go`:

```go
func okLookup(projectID string) EntityProjectFunc {
	return func(_ context.Context, _ string) (string, error) { return projectID, nil }
}

func failLookup() EntityProjectFunc {
	return func(_ context.Context, _ string) (string, error) { return "", errors.New("not found") }
}

func TestRequireProjectRoleForEntity_ViewerForbidden(t *testing.T) {
	w := httptest.NewRecorder()
	r := userReq("u-viewer", "developer") // helper from Phase A test file
	if requireProjectRoleForEntity(w, r, "edge-1", models.ProjectMemberRoleDeveloper,
		okLookup("proj-1"), fixedResolver(models.ProjectMemberRoleViewer, true)) {
		t.Fatal("project viewer must be denied")
	}
	if w.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d", w.Code)
	}
	var body map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &body)
	if body["error"] != "insufficient project role" || body["required"] != "developer" || body["actual"] != "viewer" {
		t.Fatalf("BR-005.6 body mismatch: %v", body)
	}
}

func TestRequireProjectRoleForEntity_LookupMiss404(t *testing.T) {
	w := httptest.NewRecorder()
	r := userReq("u-dev", "developer")
	if requireProjectRoleForEntity(w, r, "edge-x", models.ProjectMemberRoleDeveloper,
		failLookup(), fixedResolver(models.ProjectMemberRoleDeveloper, true)) {
		t.Fatal("missing entity must not pass")
	}
	if w.Code != http.StatusNotFound {
		t.Fatalf("expected 404 on lookup miss, got %d", w.Code)
	}
}

func TestRequireProjectRoleForEntity_GlobalAdminSkipsLookup(t *testing.T) {
	w := httptest.NewRecorder()
	r := userReq("u-admin", "admin")
	calledLookup := false
	spy := func(_ context.Context, _ string) (string, error) { calledLookup = true; return "", nil }
	if !requireProjectRoleForEntity(w, r, "edge-1", models.ProjectMemberRoleDeveloper,
		spy, fixedResolver("", false)) {
		t.Fatalf("global admin must bypass; got %d", w.Code)
	}
	if calledLookup {
		t.Fatal("global admin must bypass BEFORE the entity lookup")
	}
}

func TestRequireProjectRoleForEntity_LegacyKeyBypass(t *testing.T) {
	w := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodPatch, "/api/v1/nodes/n-1", nil) // no UserIdentity
	if !requireProjectRoleForEntity(w, r, "n-1", models.ProjectMemberRoleDeveloper,
		failLookup(), fixedResolver("", false)) {
		t.Fatalf("legacy API-key caller must bypass; got %d", w.Code)
	}
}
```

Add `"errors"` to the test file imports.

- [ ] **Step 6: Run the helper tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestRequireProjectRoleForEntity -v`
Expected: FAIL — `requireProjectRoleForEntity` / `EntityProjectFunc` undefined.

- [ ] **Step 7: Add the helper to `project_role.go`**

```go
// EntityProjectFunc resolves the owning project id for an entity id
// (a node, edge, or data source). Returns an error if the entity does not exist.
type EntityProjectFunc func(ctx context.Context, entityID string) (string, error)

// requireProjectRoleForEntity enforces a minimum project role on an operation
// targeting an entity identified by entityID. It resolves the entity's project
// via lookup, then delegates to requireProjectRole. Bypass checks (global admin,
// legacy API-key caller) run BEFORE the lookup, so privileged/legacy callers
// never trigger a DB read. A failed lookup yields 404.
func requireProjectRoleForEntity(
	w http.ResponseWriter,
	r *http.Request,
	entityID string,
	minRole models.ProjectMemberRole,
	lookup EntityProjectFunc,
	resolver ProjectRoleResolverFunc,
) bool {
	if isGlobalAdmin(r) {
		return true
	}
	if middleware.GetUserIdentity(r.Context()) == nil {
		return true // legacy API-key caller — backward compatibility
	}
	if lookup == nil {
		// Misconfiguration: fail closed for Phase 3 users rather than panic.
		writeInsufficientRole(w, minRole, "")
		return false
	}
	projectID, err := lookup(r.Context(), entityID)
	if err != nil || projectID == "" {
		errorResponse(w, http.StatusNotFound, "resource not found")
		return false
	}
	return requireProjectRole(w, r, projectID, minRole, resolver)
}
```

- [ ] **Step 8: Run helper tests + build**

Run: `cd ennam.kg.go && go test -race ./internal/handler/ -run 'TestRequireProjectRole' -v && go build ./...`
Expected: PASS, no errors

- [ ] **Step 9: Commit**

```bash
git -C ennam.kg.go add internal/store/edge.go internal/store/edge_test.go internal/handler/project_role.go internal/handler/project_role_test.go
git -C ennam.kg.go commit -m "feat(ba015): add EdgeStore.GetProjectID + requireProjectRoleForEntity helper"
```

---

## Task 2: Enforce on node updates (`UpdateHandler`)

**Files:**
- Modify: `ennam.kg.go/internal/handler/update.go`
- Modify: `ennam.kg.go/cmd/kg-server/main.go`

**Interfaces:**
- Produces: `(*UpdateHandler).SetRoleResolver(ProjectRoleResolverFunc)` and `(*UpdateHandler).SetNodeProjectResolver(EntityProjectFunc)`.
- Guarded (min `developer`): `HandleUpdateNode` + `HandleUpdateDecision`, `HandleUpdateConcept`, `HandleUpdateRequirement`, `HandleUpdateTask`, `HandleUpdateArchitecture`, `HandleUpdateDiscovery`. All identify the node via `r.PathValue("id")`.

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/handler/update_role_test.go`:

```go
package handler

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
)

func TestHandleUpdateNode_ProjectViewerForbidden(t *testing.T) {
	h := &UpdateHandler{} // svc/logger nil — guard must fire first
	h.SetRoleResolver(func(_ context.Context, _, _ string) (models.ProjectMemberRole, bool) {
		return models.ProjectMemberRoleViewer, true
	})
	h.SetNodeProjectResolver(func(_ context.Context, _ string) (string, error) {
		return "proj-1", nil
	})

	r := httptest.NewRequest(http.MethodPatch, "/api/v1/nodes/n-1", strings.NewReader(`{"title":"x"}`))
	r.SetPathValue("id", "n-1")
	ctx := context.WithValue(r.Context(), middleware.UserIdentityKey,
		&middleware.UserIdentity{UserID: "u-viewer", Role: "developer"})
	r = r.WithContext(ctx)
	w := httptest.NewRecorder()

	h.HandleUpdateNode(w, r)

	if w.Code != http.StatusForbidden {
		t.Fatalf("project viewer updating a node must get 403, got %d: %s", w.Code, w.Body.String())
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestHandleUpdateNode_ProjectViewerForbidden -v`
Expected: FAIL — setters undefined / no 403.

- [ ] **Step 3: Add fields + setters to `UpdateHandler`**

```go
	roleResolver ProjectRoleResolverFunc
	nodeProject  EntityProjectFunc
```

```go
// SetRoleResolver wires the project-role resolver for FR-005 enforcement.
func (h *UpdateHandler) SetRoleResolver(fn ProjectRoleResolverFunc) { h.roleResolver = fn }

// SetNodeProjectResolver wires the node→project lookup used to resolve the target's project.
func (h *UpdateHandler) SetNodeProjectResolver(fn EntityProjectFunc) { h.nodeProject = fn }
```

- [ ] **Step 4: Add the guard to each of the 7 update handlers**

In `HandleUpdateNode`, immediately after the `nodeID := r.PathValue("id")` validation block and **before** the `json.NewDecoder(r.Body).Decode(...)` line:

```go
	if !requireProjectRoleForEntity(w, r, nodeID, models.ProjectMemberRoleDeveloper, h.nodeProject, h.roleResolver) {
		return
	}
```

Add the identical guard (using each handler's path-id variable name) in `HandleUpdateDecision`, `HandleUpdateConcept`, `HandleUpdateRequirement`, `HandleUpdateTask`, `HandleUpdateArchitecture`, `HandleUpdateDiscovery` (in update.go / update_*.go). Each follows the same shape (`id := r.PathValue("id")` → validate → decode → log → service); place the guard right after the id-validation block, before the decode.

- [ ] **Step 5: Wire in `main.go`**

Find where `UpdateHandler` is constructed (`grep -n "NewUpdateHandler" cmd/kg-server/main.go`; note its variable name, e.g. `updateHandler`). Beside the existing `roleResolver` wiring (~line 649), add:

```go
	nodeProjectResolver := handler.EntityProjectFunc(func(ctx context.Context, nodeID string) (string, error) {
		n, err := nodeStore.GetNode(ctx, nodeID)
		if err != nil {
			return "", err
		}
		return n.ProjectID, nil
	})
	updateHandler.SetRoleResolver(roleResolver)
	updateHandler.SetNodeProjectResolver(nodeProjectResolver)
```

(`roleResolver` and `nodeStore` are already in scope from Phase A / earlier wiring; confirm the `UpdateHandler` variable name.)

- [ ] **Step 6: Run test + build**

Run: `cd ennam.kg.go && go test -race ./internal/handler/ -run TestHandleUpdateNode_ProjectViewerForbidden -v && go build ./...`
Expected: PASS, no errors

- [ ] **Step 7: Commit**

```bash
git -C ennam.kg.go add internal/handler/update.go cmd/kg-server/main.go internal/handler/update_role_test.go
git -C ennam.kg.go commit -m "feat(ba015): enforce developer-min role on node updates"
```

---

## Task 3: Enforce on node deprecate (`DeprecateHandler`)

**Files:**
- Modify: `ennam.kg.go/internal/handler/deprecate.go`
- Modify: `ennam.kg.go/cmd/kg-server/main.go`

**Interfaces:**
- Produces: `(*DeprecateHandler).SetRoleResolver` + `(*DeprecateHandler).SetNodeProjectResolver`.
- Guarded (min `developer`): `HandleDeprecateNode` (target via `r.PathValue("id")`).

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/handler/deprecate_role_test.go`:

```go
package handler

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
)

func TestHandleDeprecateNode_ProjectViewerForbidden(t *testing.T) {
	h := &DeprecateHandler{}
	h.SetRoleResolver(func(_ context.Context, _, _ string) (models.ProjectMemberRole, bool) {
		return models.ProjectMemberRoleViewer, true
	})
	h.SetNodeProjectResolver(func(_ context.Context, _ string) (string, error) { return "proj-1", nil })

	r := httptest.NewRequest(http.MethodPost, "/api/v1/nodes/n-1/deprecate", strings.NewReader(`{"change_reason":"x"}`))
	r.SetPathValue("id", "n-1")
	ctx := context.WithValue(r.Context(), middleware.UserIdentityKey,
		&middleware.UserIdentity{UserID: "u-viewer", Role: "developer"})
	r = r.WithContext(ctx)
	w := httptest.NewRecorder()

	h.HandleDeprecateNode(w, r)

	if w.Code != http.StatusForbidden {
		t.Fatalf("project viewer deprecating a node must get 403, got %d", w.Code)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestHandleDeprecateNode_ProjectViewerForbidden -v`
Expected: FAIL

- [ ] **Step 3: Add fields + setters to `DeprecateHandler`** (mirror Task 2 Step 3: `roleResolver` + `nodeProject`, with `SetRoleResolver`/`SetNodeProjectResolver`).

- [ ] **Step 4: Add the guard in `HandleDeprecateNode`**

Immediately after the `nodeID := r.PathValue("id")` validation block (`deprecate.go:27`), before the body decode:

```go
	if !requireProjectRoleForEntity(w, r, nodeID, models.ProjectMemberRoleDeveloper, h.nodeProject, h.roleResolver) {
		return
	}
```

(Use the actual path-id variable name in the handler.)

- [ ] **Step 5: Wire in `main.go`**

Find the `DeprecateHandler` variable (`grep -n "NewDeprecateHandler" cmd/kg-server/main.go`) and add beside Task 2's wiring:

```go
	deprecateHandler.SetRoleResolver(roleResolver)
	deprecateHandler.SetNodeProjectResolver(nodeProjectResolver)
```

(`nodeProjectResolver` from Task 2 is reused.)

- [ ] **Step 6: Run test + build**

Run: `cd ennam.kg.go && go test -race ./internal/handler/ -run TestHandleDeprecateNode_ProjectViewerForbidden -v && go build ./...`
Expected: PASS, no errors

- [ ] **Step 7: Commit**

```bash
git -C ennam.kg.go add internal/handler/deprecate.go cmd/kg-server/main.go internal/handler/deprecate_role_test.go
git -C ennam.kg.go commit -m "feat(ba015): enforce developer-min role on node deprecate"
```

---

## Task 4: Enforce on data-source mutations (`DataSourceHandler`)

**Files:**
- Modify: `ennam.kg.go/internal/handler/datasource.go`

**Interfaces:**
- Consumes: `DataSourceHandler.roleResolver` (already injected in Phase A) and `h.svc.Get(ctx, id)` (`*service.DataSourceService.Get` returns `*models.DataSource` with `ProjectID`).
- Guarded (min `developer`): `Update`, `Delete`, `TestConnection`, `ExtractSchema`, `SyncSchema` (target via `r.PathValue("id")`).

> No new injection needed: `DataSourceHandler` already holds its service (`h.svc`), so the entity lookup is an inline closure over `h.svc.Get`. The `Create` handler was already guarded in Phase A.

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/handler/datasource_role_test.go`:

```go
package handler

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
)

func TestDataSourceUpdate_ProjectViewerForbidden(t *testing.T) {
	h := &DataSourceHandler{}
	h.SetRoleResolver(func(_ context.Context, _, _ string) (models.ProjectMemberRole, bool) {
		return models.ProjectMemberRoleViewer, true
	})
	h.SetDataSourceProjectResolver(func(_ context.Context, _ string) (string, error) { return "proj-1", nil })

	r := httptest.NewRequest(http.MethodPatch, "/api/v1/data-sources/ds-1", strings.NewReader(`{"name":"x"}`))
	r.SetPathValue("id", "ds-1")
	ctx := context.WithValue(r.Context(), middleware.UserIdentityKey,
		&middleware.UserIdentity{UserID: "u-viewer", Role: "developer"})
	r = r.WithContext(ctx)
	w := httptest.NewRecorder()

	h.Update(w, r)

	if w.Code != http.StatusForbidden {
		t.Fatalf("project viewer updating a data source must get 403, got %d", w.Code)
	}
}
```

> Use an injected `dsProject EntityProjectFunc` (set via `SetDataSourceProjectResolver`) rather than calling `h.svc.Get` directly in the guard — this keeps the handler unit-testable with a nil service. The production closure (wired in main.go) uses `h.svc.Get`. (See Step 5.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestDataSourceUpdate_ProjectViewerForbidden -v`
Expected: FAIL — `SetDataSourceProjectResolver` undefined.

- [ ] **Step 3: Add field + setter to `DataSourceHandler`**

```go
	dsProject EntityProjectFunc
```

```go
// SetDataSourceProjectResolver wires the data-source→project lookup.
func (h *DataSourceHandler) SetDataSourceProjectResolver(fn EntityProjectFunc) { h.dsProject = fn }
```

(`roleResolver` + `SetRoleResolver` already exist from Phase A.)

- [ ] **Step 4: Add the guard to the 5 mutation handlers**

In each of `Update`, `Delete`, `TestConnection`, `ExtractSchema`, `SyncSchema`, immediately after the path-id validation block and before the body decode / first `h.svc`/`h.logger` use:

```go
	if !requireProjectRoleForEntity(w, r, id, models.ProjectMemberRoleDeveloper, h.dsProject, h.roleResolver) {
		return
	}
```

(`id` = each handler's existing `r.PathValue("id")` variable. `Delete` may have no body to decode — place the guard right after the id-validation block regardless.)

- [ ] **Step 5: Wire in `main.go`**

Where `dsHandler` is built (main.go:473, conditional), add inside that block (or guarded by `if dsHandler != nil`):

```go
	dsHandler.SetDataSourceProjectResolver(func(ctx context.Context, dsID string) (string, error) {
		ds, err := dsSvc.Get(ctx, dsID)
		if err != nil {
			return "", err
		}
		return ds.ProjectID, nil
	})
```

(`dsSvc` is the data-source service used to build `dsHandler` at line 473 — confirm the variable name. `dsHandler.SetRoleResolver(roleResolver)` was added in Phase A.)

- [ ] **Step 6: Run test + build**

Run: `cd ennam.kg.go && go test -race ./internal/handler/ -run TestDataSourceUpdate_ProjectViewerForbidden -v && go build ./...`
Expected: PASS, no errors

- [ ] **Step 7: Commit**

```bash
git -C ennam.kg.go add internal/handler/datasource.go cmd/kg-server/main.go internal/handler/datasource_role_test.go
git -C ennam.kg.go commit -m "feat(ba015): enforce developer-min role on data-source update/delete/sync"
```

---

## Task 5: Enforce on KG-generation node/edge edits (`KGGenerationHandler`)

**Files:**
- Modify: `ennam.kg.go/internal/handler/kg_generation.go`
- Modify: `ennam.kg.go/cmd/kg-server/main.go`

**Interfaces:**
- Consumes: `KGGenerationHandler.roleResolver` (Phase A); new `nodeProject` + `edgeProject EntityProjectFunc` fields.
- Guarded (min `developer`):
  - `UpdateNodeDescription` (PATCH `/kg-nodes/{id}`) — node lookup (`knowledge_nodes`).
  - `UpdateConfidence` (PATCH `/kg-edges/{id}/confidence`), `ConfirmEdge`, `RejectEdge`, `UnrejectEdge` (`/kg-edges/{id}/...`) — edge lookup (`knowledge_edges`).

- [ ] **Step 1: Write the failing tests**

Create `ennam.kg.go/internal/handler/kg_generation_role_test.go` with two tests (one node-based, one edge-based):

```go
package handler

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
)

func kgViewerCtx(r *http.Request) *http.Request {
	ctx := context.WithValue(r.Context(), middleware.UserIdentityKey,
		&middleware.UserIdentity{UserID: "u-viewer", Role: "developer"})
	return r.WithContext(ctx)
}

func viewerRoleResolver() ProjectRoleResolverFunc {
	return func(_ context.Context, _, _ string) (models.ProjectMemberRole, bool) {
		return models.ProjectMemberRoleViewer, true
	}
}

func TestConfirmEdge_ProjectViewerForbidden(t *testing.T) {
	h := &KGGenerationHandler{}
	h.SetRoleResolver(viewerRoleResolver())
	h.SetEdgeProjectResolver(func(_ context.Context, _ string) (string, error) { return "proj-1", nil })

	r := httptest.NewRequest(http.MethodPost, "/api/v1/kg-edges/e-1/confirm", nil)
	r.SetPathValue("id", "e-1")
	w := httptest.NewRecorder()
	h.ConfirmEdge(w, kgViewerCtx(r))

	if w.Code != http.StatusForbidden {
		t.Fatalf("project viewer confirming an edge must get 403, got %d", w.Code)
	}
}

func TestUpdateNodeDescription_ProjectViewerForbidden(t *testing.T) {
	h := &KGGenerationHandler{}
	h.SetRoleResolver(viewerRoleResolver())
	h.SetNodeProjectResolver(func(_ context.Context, _ string) (string, error) { return "proj-1", nil })

	r := httptest.NewRequest(http.MethodPatch, "/api/v1/kg-nodes/n-1", nil)
	r.SetPathValue("id", "n-1")
	w := httptest.NewRecorder()
	h.UpdateNodeDescription(w, kgViewerCtx(r))

	if w.Code != http.StatusForbidden {
		t.Fatalf("project viewer editing a kg node must get 403, got %d", w.Code)
	}
}
```

> Because the guard is placed before any body decode (see Guard placement constraint), these tests can pass a `nil` body — `UpdateNodeDescription` would otherwise decode a body, but the guard returns 403 first. Verified: `ConfirmEdge` has no body decode; `UpdateNodeDescription` decodes `req.AIDescription` after the id check, so the guard precedes it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run 'TestConfirmEdge_ProjectViewerForbidden|TestUpdateNodeDescription_ProjectViewerForbidden' -v`
Expected: FAIL

- [ ] **Step 3: Add fields + setters to `KGGenerationHandler`**

```go
	nodeProject EntityProjectFunc
	edgeProject EntityProjectFunc
```

```go
// SetNodeProjectResolver wires the kg-node→project lookup.
func (h *KGGenerationHandler) SetNodeProjectResolver(fn EntityProjectFunc) { h.nodeProject = fn }

// SetEdgeProjectResolver wires the kg-edge→project lookup.
func (h *KGGenerationHandler) SetEdgeProjectResolver(fn EntityProjectFunc) { h.edgeProject = fn }
```

(`roleResolver` + `SetRoleResolver` already exist from Phase A.)

- [ ] **Step 4: Add guards**

In `UpdateNodeDescription`, immediately after the `id := r.PathValue("id")` validation block and **before** the body decode / first `h.logger`/`h.kgStore` use:

```go
	if !requireProjectRoleForEntity(w, r, id, models.ProjectMemberRoleDeveloper, h.nodeProject, h.roleResolver) {
		return
	}
```

In `UpdateConfidence`, `ConfirmEdge`, `RejectEdge`, `UnrejectEdge`, the same placement with the edge lookup (`ConfirmEdge`/`RejectEdge`/`UnrejectEdge` have no body decode; place the guard right after id validation):

```go
	if !requireProjectRoleForEntity(w, r, id, models.ProjectMemberRoleDeveloper, h.edgeProject, h.roleResolver) {
		return
	}
```

- [ ] **Step 5: Wire in `main.go`**

Beside the Phase A `kgGenHandler.SetRoleResolver(roleResolver)` line, add (reusing `nodeProjectResolver` from Task 2 and a new edge resolver over `edgeStore.GetProjectID`):

```go
	edgeProjectResolver := handler.EntityProjectFunc(func(ctx context.Context, edgeID string) (string, error) {
		return edgeStore.GetProjectID(ctx, edgeID)
	})
	kgGenHandler.SetNodeProjectResolver(nodeProjectResolver)
	kgGenHandler.SetEdgeProjectResolver(edgeProjectResolver)
```

(`nodeProjectResolver` from Task 2, `edgeStore` in scope from earlier wiring.)

- [ ] **Step 6: Run tests + build**

Run: `cd ennam.kg.go && go test -race ./internal/handler/ -run 'ProjectViewerForbidden' -v && go build ./...`
Expected: PASS, no errors

- [ ] **Step 7: Commit**

```bash
git -C ennam.kg.go add internal/handler/kg_generation.go cmd/kg-server/main.go internal/handler/kg_generation_role_test.go
git -C ennam.kg.go commit -m "feat(ba015): enforce developer-min role on KG-generation node/edge edits"
```

---

## Self-Review

### Spec coverage (FR-005 matrix) — after Phase A + B

| Matrix row | Min role | Status |
|---|---|---|
| Create / **update** nodes | developer | Phase A (create) + **Phase B Task 2** (update) ✅ |
| Deprecate nodes | developer | **Phase B Task 3** ✅ |
| Create edges | developer | Phase A ✅ |
| Manage data sources (create + **update/delete/sync**) | developer | Phase A (create) + **Phase B Task 4** ✅ |
| Run sync/extract | developer | **Phase B Task 4** (`SyncSchema`/`ExtractSchema`/`TestConnection`) ✅ |
| Trigger KG generation | developer | Phase A ✅ |
| **KG-gen node/edge confirm/reject/edit** | developer | **Phase B Task 5** ✅ |
| Submit AI queries | developer | Phase A ✅ |
| Update project details | project admin | Phase A ✅ |
| Manage members / archive | admin / global | Already implemented (FR-004 / project.go) |
| View data / list members / stats | viewer | Read paths — no guard |
| Delete project data | project admin | **Still out of scope** — no single dedicated endpoint; node deprecate (developer) is the closest. Revisit if a hard-delete endpoint is added. |

### Risk notes

- **Lookup-then-check ordering.** Bypass (global admin / legacy key) runs before the DB lookup — verified by `TestRequireProjectRoleForEntity_GlobalAdminSkipsLookup`. This keeps MCP/CLI free of extra reads and 403s.
- **404 vs 403 for missing entities.** A non-member probing a non-existent id gets 404 (lookup miss) while an existing id they can't access gets 403 — a minor existence-disclosure difference. Acceptable for an internal tool; noted, not silently chosen.
- **Double read on updates.** The guard's node lookup (`NodeStore.GetNode`) is a second read in addition to the one `UpdateService` does internally. Acceptable (cheap, indexed by PK); not optimized to keep the change surgical and the service layer untouched.
- **`UpdateNodeDescription` targets a knowledge_nodes row** resolved via the node lookup (same `nodeProjectResolver` as Task 2); edge ops use `EdgeStore.GetProjectID`. Both columns verified present.
- **Injected lookups keep handlers unit-testable.** Every guarded handler receives its lookup as an `EntityProjectFunc` (not a hard call to a store/service), so zero-value-handler tests inject fakes and never touch a DB.

### Placeholder / type-consistency check

- `EntityProjectFunc` signature identical across type def, helper param, all setters, and main.go closures — consistent.
- `requireProjectRoleForEntity` reuses Phase A `requireProjectRole`/`writeInsufficientRole` — no duplicated role logic.
- Setter names consistent: `SetRoleResolver` (all), `SetNodeProjectResolver` (UpdateHandler, DeprecateHandler, KGGenerationHandler), `SetEdgeProjectResolver` (KGGenerationHandler), `SetDataSourceProjectResolver` (DataSourceHandler).
- `EdgeStore.GetProjectID` returns `(string, error)` matching `EntityProjectFunc`.
- All guards use `models.ProjectMemberRoleDeveloper` per the matrix.

### Items requiring confirmation during implementation (grep, don't guess)

- Variable names in `main.go`: `UpdateHandler` (`grep NewUpdateHandler`), `DeprecateHandler` (`grep NewDeprecateHandler`), data-source service var feeding `dsHandler` at line 473 (`dsSvc`?), `nodeStore`/`edgeStore` exact names.
- `EdgeStore` DB-handle field name in `edge.go` (`s.db`?) and the test-DB bootstrap helper in `edge_test.go`.
- Per-handler path-id variable names and whether each decodes a body before the guard point.
