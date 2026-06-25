# BA-015 FR-005 Role-Based Permission Enforcement — Phase A

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the project permission matrix (viewer = read-only, developer = write, admin = manage) on the **body-scoped** project-data write endpoints and project update, returning the BR-005.6 403 body.

**Scope decision:** This is **Phase A** — only write handlers that already carry `project_id` in the request body (so the caller's project is known without an extra lookup), plus project update. **Entity-id handlers** (node update, deprecate, edge confirm/reject, data-source update/delete/sync, KG-gen confirm/reject) are deferred to **Phase B** (see the dedicated section at the end) because they identify the target by `r.PathValue("id")` and have no project context at the handler layer — enforcing them correctly requires resolving the entity's project, best done at the service layer.

**Architecture:** Handler-level enforcement via an injected `ProjectRoleResolverFunc` (mirroring the existing `ProjectArchiveCheckerFunc` / `archiveChecker` precedent) plus a shared `requireProjectRole` helper. The resolver wraps `ProjectService.GetMembership`; global admins bypass; **legacy API-key callers (no Phase 3 user account) also bypass** so MCP agents / CLI keep working.

**Tech Stack:** Go stdlib `net/http`, `internal/handler` helpers (`isGlobalAdmin`, `resolveUserID`), `internal/middleware` (`GetUserIdentity`), `internal/service.ProjectService.GetMembership`, `internal/models.ProjectMemberRole`.

## Global Constraints

- **FR-004 (membership management) is ALREADY implemented** — `ProjectMemberHandler.requireProjectAdmin`/`isMember`; `ProjectService.GetMembership` (`internal/service/project.go:361`). Do NOT redo.
- **Archived-write-block (BR-002.3) is ALREADY implemented** — `middleware/project.go:140-154` + node/edge `archiveChecker`. Not in scope.
- **An API-key-role viewer block already exists on node create and edge create** — `node.go:137` and `link.go:96` reject `models.APIKeyRoleViewer` (the caller's *global* API-key role). This is a DIFFERENT layer from project membership: a user whose global role is `developer` but who is only a `viewer` **in this project** passes that check today and must be caught by the new project-role guard. Keep both checks; they are complementary. Place the new guard AFTER the existing API-key-role check.
- **BR-005.6 403 body is mandatory and exact:** `{"error": "insufficient project role", "required": "<minRole>", "actual": "<callerRole|none>"}`. The new `writeInsufficientRole` helper emits exactly this; existing `errorResponse` emits a different envelope.
- **Role hierarchy is additive:** `viewer < developer < admin`. Values: `models.ProjectMemberRoleViewer`, `ProjectMemberRoleDeveloper`, `ProjectMemberRoleAdmin`.
- **Bypass rules (both MUST hold or callers break):** (1) `isGlobalAdmin(r)` → allow (BR-005.4); (2) `middleware.GetUserIdentity(r.Context()) == nil` → allow (legacy API-key callers already passed API-key project access in middleware; they have no `project_members` row).
- **Guard placement:** insert the guard AFTER the request body is decoded and `req.ProjectID` validated, and BEFORE the first use of `h.logger` or `h.svc` — so unit tests with a zero-value handler (nil logger/svc) reach the 403 without a nil-pointer panic.
- **Tests:** Go table-driven, `package handler` (in-package), inject identity via `context.WithValue(ctx, middleware.UserIdentityKey, &middleware.UserIdentity{...})`. `go test -race ./internal/handler/...`.

## Rationale for diverging from BR-005.5

BR-005.5 says enforcement happens in middleware that injects the role and handlers check it. We enforce in handlers via an injected resolver func because the write handlers (`NodeHandler`, `LinkHandler`, `DataSourceHandler`, `KGGenerationHandler`, `AIQueryHandler`) are independent structs that don't hold `ProjectService`, and the codebase's established answer to "a handler needs a cross-cutting project check" is an injected `ProjectArchiveCheckerFunc` wired in `main.go`. Mirroring it (AGENTS Rule 11) is the smallest, most consistent diff. Observable behavior — 403 with the BR-005.6 body for under-privileged members — is fully spec-compliant. Surfaced per AGENTS Rule 7.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `ennam.kg.go/internal/handler/project_role.go` | Create | `ProjectRoleResolverFunc`, `requireProjectRole`, `writeInsufficientRole`, `roleAtLeast` |
| `ennam.kg.go/internal/handler/project_role_test.go` | Create | Helper unit tests (viewer denied, developer allowed, non-member, global-admin & legacy bypass, exact 403 body) |
| `ennam.kg.go/internal/handler/node.go` | Modify | `roleResolver` field + `SetRoleResolver`; guard the 7 create handlers |
| `ennam.kg.go/internal/handler/link.go` | Modify | `roleResolver` field + `SetRoleResolver`; guard `HandleCreateLink` |
| `ennam.kg.go/internal/handler/datasource.go` | Modify | `roleResolver` field + `SetRoleResolver`; guard `Create` only |
| `ennam.kg.go/internal/handler/kg_generation.go` | Modify | `roleResolver` field + `SetRoleResolver`; guard `GenerateKG` only |
| `ennam.kg.go/internal/handler/ai_query.go` | Modify | `roleResolver` field + `SetRoleResolver`; guard `SubmitQuery` only |
| `ennam.kg.go/internal/handler/project.go` | Modify | `HandleUpdateProject`: replace `TODO(BA-014)` with project-admin check |
| `ennam.kg.go/cmd/kg-server/main.go` | Modify | Build one `roleResolver` closure; inject into the 5 handlers above |

---

## Task 1: Shared `requireProjectRole` helper + resolver type

**Files:**
- Create: `ennam.kg.go/internal/handler/project_role.go`
- Create: `ennam.kg.go/internal/handler/project_role_test.go`

**Interfaces:**
- Produces:
  - `type ProjectRoleResolverFunc func(ctx context.Context, projectID, userID string) (models.ProjectMemberRole, bool)`
  - `func requireProjectRole(w http.ResponseWriter, r *http.Request, projectID string, minRole models.ProjectMemberRole, resolver ProjectRoleResolverFunc) bool`
- Consumes: `isGlobalAdmin(r)`, `resolveUserID(r)` (from `project.go`), `middleware.GetUserIdentity`.

- [ ] **Step 1: Write the failing tests**

Create `ennam.kg.go/internal/handler/project_role_test.go`:

```go
package handler

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
)

func userReq(userID, globalRole string) *http.Request {
	r := httptest.NewRequest(http.MethodPost, "/api/v1/nodes", nil)
	ctx := context.WithValue(r.Context(), middleware.UserIdentityKey, &middleware.UserIdentity{
		UserID: userID,
		Role:   globalRole,
	})
	return r.WithContext(ctx)
}

func fixedResolver(role models.ProjectMemberRole, ok bool) ProjectRoleResolverFunc {
	return func(_ context.Context, _, _ string) (models.ProjectMemberRole, bool) {
		return role, ok
	}
}

func TestRequireProjectRole_ViewerDeniedDeveloperOp(t *testing.T) {
	w := httptest.NewRecorder()
	r := userReq("u-viewer", "developer") // global role is not admin → not global-admin bypass
	if requireProjectRole(w, r, "proj-1", models.ProjectMemberRoleDeveloper,
		fixedResolver(models.ProjectMemberRoleViewer, true)) {
		t.Fatal("viewer must be denied a developer-min operation")
	}
	if w.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d", w.Code)
	}
	var body map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &body)
	if body["error"] != "insufficient project role" ||
		body["required"] != "developer" || body["actual"] != "viewer" {
		t.Fatalf("BR-005.6 body mismatch: %v", body)
	}
}

func TestRequireProjectRole_DeveloperAllowed(t *testing.T) {
	w := httptest.NewRecorder()
	r := userReq("u-dev", "developer")
	if !requireProjectRole(w, r, "proj-1", models.ProjectMemberRoleDeveloper,
		fixedResolver(models.ProjectMemberRoleDeveloper, true)) {
		t.Fatalf("developer must be allowed; got %d %s", w.Code, w.Body.String())
	}
}

func TestRequireProjectRole_NonMemberDenied_ActualNone(t *testing.T) {
	w := httptest.NewRecorder()
	r := userReq("u-outsider", "developer")
	if requireProjectRole(w, r, "proj-1", models.ProjectMemberRoleDeveloper, fixedResolver("", false)) {
		t.Fatal("non-member must be denied")
	}
	var body map[string]string
	_ = json.Unmarshal(w.Body.Bytes(), &body)
	if body["actual"] != "none" {
		t.Fatalf("expected actual=none, got %q", body["actual"])
	}
}

func TestRequireProjectRole_GlobalAdminBypass(t *testing.T) {
	w := httptest.NewRecorder()
	r := userReq("u-admin", "admin")
	if !requireProjectRole(w, r, "proj-1", models.ProjectMemberRoleAdmin, fixedResolver("", false)) {
		t.Fatalf("global admin must bypass; got %d", w.Code)
	}
}

func TestRequireProjectRole_LegacyAPIKeyBypass(t *testing.T) {
	w := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodPost, "/api/v1/nodes", nil) // no UserIdentity → legacy key
	if !requireProjectRole(w, r, "proj-1", models.ProjectMemberRoleDeveloper, fixedResolver("", false)) {
		t.Fatalf("legacy API-key caller must bypass; got %d", w.Code)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestRequireProjectRole -v`
Expected: FAIL — undefined `requireProjectRole` / `ProjectRoleResolverFunc`.

- [ ] **Step 3: Create `project_role.go`**

```go
package handler

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
)

// ProjectRoleResolverFunc resolves a user's role within a project.
// Returns (role, true) when the user is a member, or ("", false) otherwise.
type ProjectRoleResolverFunc func(ctx context.Context, projectID, userID string) (models.ProjectMemberRole, bool)

func roleRank(role models.ProjectMemberRole) int {
	switch role {
	case models.ProjectMemberRoleAdmin:
		return 3
	case models.ProjectMemberRoleDeveloper:
		return 2
	case models.ProjectMemberRoleViewer:
		return 1
	default:
		return 0
	}
}

// roleAtLeast reports whether have >= want in the additive project-role hierarchy.
func roleAtLeast(have, want models.ProjectMemberRole) bool {
	return roleRank(have) >= roleRank(want)
}

// writeInsufficientRole emits the BR-005.6 403 response body.
func writeInsufficientRole(w http.ResponseWriter, required, actual models.ProjectMemberRole) {
	actualStr := string(actual)
	if actualStr == "" {
		actualStr = "none"
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusForbidden)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"error":    "insufficient project role",
		"required": string(required),
		"actual":   actualStr,
	})
}

// requireProjectRole enforces a minimum project role for the caller on projectID.
// Returns true if the operation may proceed; on denial writes the BR-005.6 403
// body and returns false.
//
// Bypass: global admins (BR-005.4) and legacy API-key callers without a Phase 3
// user account (MCP agents / CLI) are always allowed.
func requireProjectRole(
	w http.ResponseWriter,
	r *http.Request,
	projectID string,
	minRole models.ProjectMemberRole,
	resolver ProjectRoleResolverFunc,
) bool {
	if isGlobalAdmin(r) {
		return true
	}
	if middleware.GetUserIdentity(r.Context()) == nil {
		return true // legacy API-key caller — backward compatibility
	}
	if resolver == nil {
		writeInsufficientRole(w, minRole, "") // misconfiguration: fail closed for Phase 3 users
		return false
	}
	role, ok := resolver(r.Context(), projectID, resolveUserID(r))
	if !ok {
		writeInsufficientRole(w, minRole, "")
		return false
	}
	if !roleAtLeast(role, minRole) {
		writeInsufficientRole(w, minRole, role)
		return false
	}
	return true
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test -race ./internal/handler/ -run TestRequireProjectRole -v`
Expected: PASS (5 tests)

Run: `cd ennam.kg.go && go build ./...`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/handler/project_role.go internal/handler/project_role_test.go
git -C ennam.kg.go commit -m "feat(ba015): add requireProjectRole helper with BR-005.6 403 body"
```

---

## Task 2: Wire resolver in main.go + enforce on node create

**Files:**
- Modify: `ennam.kg.go/internal/handler/node.go`
- Modify: `ennam.kg.go/cmd/kg-server/main.go`

**Interfaces:**
- Consumes: `requireProjectRole`, `ProjectRoleResolverFunc` (Task 1); `projectSvc.GetMembership`.
- Produces: `(*NodeHandler).SetRoleResolver(fn ProjectRoleResolverFunc)`; the 7 node create handlers return 403 for project viewers.

**Guarded handlers (min `developer`), all read `req.ProjectID` from the decoded body:** `HandleStoreNode`, `HandleStoreDecision`, `HandleStoreConcept`, `HandleStoreRequirement`, `HandleStoreTask`, `HandleStoreArchitecture`, `HandleStoreDiscovery`.

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/handler/node_role_test.go`:

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

func TestHandleStoreNode_ProjectViewerForbidden(t *testing.T) {
	h := &NodeHandler{} // svc/logger nil — guard must fire before any use
	h.SetRoleResolver(func(_ context.Context, _, _ string) (models.ProjectMemberRole, bool) {
		return models.ProjectMemberRoleViewer, true
	})

	body := `{"project_id":"proj-1","type":"decision","title":"x"}`
	r := httptest.NewRequest(http.MethodPost, "/api/v1/nodes", strings.NewReader(body))
	ctx := context.WithValue(r.Context(), middleware.UserIdentityKey,
		&middleware.UserIdentity{UserID: "u-viewer", Role: "developer"}) // global dev, project viewer
	r = r.WithContext(ctx)
	w := httptest.NewRecorder()

	h.HandleStoreNode(w, r)

	if w.Code != http.StatusForbidden {
		t.Fatalf("project viewer creating a node must get 403, got %d: %s", w.Code, w.Body.String())
	}
}
```

> The global role is `developer`, so the existing `APIKeyRoleViewer` check at `node.go:137` does NOT fire — this test specifically exercises the NEW project-role guard.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestHandleStoreNode_ProjectViewerForbidden -v`
Expected: FAIL — `SetRoleResolver` undefined / no 403.

- [ ] **Step 3: Add field + setter to `NodeHandler`**

In the `NodeHandler` struct (node.go), add beside `archiveChecker`:

```go
	roleResolver ProjectRoleResolverFunc
```

Add a setter beside `SetArchiveChecker`:

```go
// SetRoleResolver wires the project-role resolver used to enforce write permissions.
func (h *NodeHandler) SetRoleResolver(fn ProjectRoleResolverFunc) {
	h.roleResolver = fn
}
```

- [ ] **Step 4: Add the guard in each of the 7 create handlers**

Universal placement rule: insert the guard **immediately after the body-decode error block** (so `req.ProjectID` is populated) and **before the first `h.logger` call** — this matters because the unit test uses a zero-value `&NodeHandler{}` with a nil `logger`, so the guard must return 403 before any `h.logger.InfoContext(...)` runs.

```go
	if !requireProjectRole(w, r, req.ProjectID, models.ProjectMemberRoleDeveloper, h.roleResolver) {
		return
	}
```

Per-handler notes (verified):
- `HandleStoreNode` (node.go) — has an existing `APIKeyRoleViewer` check (line ~137) AND an `archiveChecker` call (line ~149) before its `h.logger.InfoContext`. Place the new guard right after body decode; sitting before or after the archive check is fine (both are 403 gates).
- `HandleStoreDecision` (decision.go), `HandleStoreConcept` (concept.go), `HandleStoreTask` (task.go), `HandleStoreRequirement` (requirement.go), `HandleStoreArchitecture` (architecture.go), `HandleStoreDiscovery` (discovery.go) — these have **no archive check and no API-key-role check**; the flow is `decode → h.logger.InfoContext → service`. Insert the guard between the decode error block and the `h.logger.InfoContext` call. Each request struct (`storeDecisionRequest`, `storeConceptRequest`, etc.) has a `ProjectID string` field (verified) — use `req.ProjectID`.

- [ ] **Step 5: Build the resolver closure and inject it in `main.go`**

Beside the existing `archiveChecker` wiring (`cmd/kg-server/main.go:649-654`), add:

```go
	// Wire project-role resolver for FR-005 write-permission enforcement.
	roleResolver := handler.ProjectRoleResolverFunc(func(ctx context.Context, projectID, userID string) (models.ProjectMemberRole, bool) {
		m, err := projectSvc.GetMembership(ctx, projectID, userID)
		if err != nil || m == nil {
			return "", false
		}
		return m.Role, true
	})
	nodeHandler.SetRoleResolver(roleResolver)
```

Confirm `models` and `context` are imported in `main.go` (both are used elsewhere) and that the project service variable is named `projectSvc` (grep `NewProjectService` in main.go to confirm the exact name).

- [ ] **Step 6: Run test + build**

Run: `cd ennam.kg.go && go test -race ./internal/handler/ -run 'TestHandleStoreNode_ProjectViewerForbidden|TestRequireProjectRole' -v`
Expected: PASS

Run: `cd ennam.kg.go && go build ./...`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git -C ennam.kg.go add internal/handler/node.go internal/handler/node_role_test.go cmd/kg-server/main.go
git -C ennam.kg.go commit -m "feat(ba015): enforce developer-min project role on node creation"
```

---

## Task 3: Enforce on edge creation

**Files:**
- Modify: `ennam.kg.go/internal/handler/link.go`
- Modify: `ennam.kg.go/cmd/kg-server/main.go`

**Interfaces:**
- Produces: `(*LinkHandler).SetRoleResolver`; `HandleCreateLink` (POST /api/v1/edges) returns 403 for project viewers.

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/handler/link_role_test.go`:

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

func TestHandleCreateLink_ProjectViewerForbidden(t *testing.T) {
	h := &LinkHandler{}
	h.SetRoleResolver(func(_ context.Context, _, _ string) (models.ProjectMemberRole, bool) {
		return models.ProjectMemberRoleViewer, true
	})
	body := `{"project_id":"proj-1","source_id":"a","target_id":"b","relationship":"relates_to"}`
	r := httptest.NewRequest(http.MethodPost, "/api/v1/edges", strings.NewReader(body))
	ctx := context.WithValue(r.Context(), middleware.UserIdentityKey,
		&middleware.UserIdentity{UserID: "u-viewer", Role: "developer"})
	r = r.WithContext(ctx)
	w := httptest.NewRecorder()

	h.HandleCreateLink(w, r)

	if w.Code != http.StatusForbidden {
		t.Fatalf("project viewer creating an edge must get 403, got %d", w.Code)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestHandleCreateLink_ProjectViewerForbidden -v`
Expected: FAIL

- [ ] **Step 3: Add field + setter to `LinkHandler`** (mirror Task 2 Step 3 in link.go).

- [ ] **Step 4: Add the guard in `HandleCreateLink`**

Immediately after the existing archive check (`link.go:108`, `h.archiveChecker(ctx, req.ProjectID)`) and before the service call:

```go
	if !requireProjectRole(w, r, req.ProjectID, models.ProjectMemberRoleDeveloper, h.roleResolver) {
		return
	}
```

- [ ] **Step 5: Inject in `main.go`** beside `lifecycleHandlers.Link.SetArchiveChecker(archiveChecker)`:

```go
	lifecycleHandlers.Link.SetRoleResolver(roleResolver)
```

- [ ] **Step 6: Run test + build**

Run: `cd ennam.kg.go && go test -race ./internal/handler/ -run TestHandleCreateLink_ProjectViewerForbidden -v && go build ./...`
Expected: PASS, no errors

- [ ] **Step 7: Commit**

```bash
git -C ennam.kg.go add internal/handler/link.go internal/handler/link_role_test.go cmd/kg-server/main.go
git -C ennam.kg.go commit -m "feat(ba015): enforce developer-min project role on edge creation"
```

---

## Task 4: Enforce on the remaining body-scoped writes (data-source create, KG-gen trigger, AI-query submit)

**Files:**
- Modify: `ennam.kg.go/internal/handler/datasource.go` — `Create` only
- Modify: `ennam.kg.go/internal/handler/kg_generation.go` — `GenerateKG` only
- Modify: `ennam.kg.go/internal/handler/ai_query.go` — `SubmitQuery` only
- Modify: `ennam.kg.go/cmd/kg-server/main.go`

**Interfaces:**
- Produces: `SetRoleResolver` on `DataSourceHandler`, `KGGenerationHandler`, `AIQueryHandler`; the three handlers above return 403 for project viewers.

> Only these three operations carry `project_id` in the body. The other data-source ops (`Update`/`Delete`/`TestConnection`/`ExtractSchema`/`SyncSchema`) and KG-gen ops (`UpdateNodeDescription`/`UpdateConfidence`/`ConfirmEdge`/`RejectEdge`/`UnrejectEdge`) identify the target by `r.PathValue("id")` and belong to **Phase B**. `StarQuery`/`UnstarQuery` are personal favorites — never guarded.

- [ ] **Step 1: Write the failing tests**

Create `ennam.kg.go/internal/handler/role_writes_test.go` with three tests, one per handler. Each builds a zero-value handler, sets a viewer resolver, posts a body with `project_id`, injects a Phase-3 `developer`-global UserIdentity, and asserts 403. Example for `SubmitQuery`:

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

func viewerCtxReq(method, path, body string) *http.Request {
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	ctx := context.WithValue(r.Context(), middleware.UserIdentityKey,
		&middleware.UserIdentity{UserID: "u-viewer", Role: "developer"})
	return r.WithContext(ctx)
}

func viewerResolver() ProjectRoleResolverFunc {
	return func(_ context.Context, _, _ string) (models.ProjectMemberRole, bool) {
		return models.ProjectMemberRoleViewer, true
	}
}

func TestSubmitQuery_ProjectViewerForbidden(t *testing.T) {
	h := &AIQueryHandler{}
	h.SetRoleResolver(viewerResolver())
	w := httptest.NewRecorder()
	h.SubmitQuery(w, viewerCtxReq(http.MethodPost, "/api/v1/ai-queries",
		`{"project_id":"proj-1","data_source_id":"ds-1","natural_language_query":"q"}`))
	if w.Code != http.StatusForbidden {
		t.Fatalf("viewer submitting AI query must get 403, got %d", w.Code)
	}
}

func TestDataSourceCreate_ProjectViewerForbidden(t *testing.T) {
	h := &DataSourceHandler{}
	h.SetRoleResolver(viewerResolver())
	w := httptest.NewRecorder()
	h.Create(w, viewerCtxReq(http.MethodPost, "/api/v1/data-sources",
		`{"project_id":"proj-1","name":"ds","db_type":"postgres"}`))
	if w.Code != http.StatusForbidden {
		t.Fatalf("viewer creating data source must get 403, got %d", w.Code)
	}
}

func TestGenerateKG_ProjectViewerForbidden(t *testing.T) {
	h := &KGGenerationHandler{}
	h.SetRoleResolver(viewerResolver())
	r := viewerCtxReq(http.MethodPost, "/api/v1/data-sources/ds-1/generate-kg", `{"project_id":"proj-1"}`)
	r.SetPathValue("id", "ds-1")
	w := httptest.NewRecorder()
	h.GenerateKG(w, r)
	if w.Code != http.StatusForbidden {
		t.Fatalf("viewer triggering KG generation must get 403, got %d", w.Code)
	}
}
```

Before finalizing, read each handler to confirm the body field is `ProjectID` and the request struct/route shape; adjust the JSON bodies to match.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run 'TestSubmitQuery_ProjectViewerForbidden|TestDataSourceCreate_ProjectViewerForbidden|TestGenerateKG_ProjectViewerForbidden' -v`
Expected: FAIL

- [ ] **Step 3: Add field + setter to each of the three handler structs** (`AIQueryHandler`, `DataSourceHandler`, `KGGenerationHandler`), mirroring Task 2 Step 3.

- [ ] **Step 4: Add the guard to `SubmitQuery`, `Create`, `GenerateKG`**

In each, after `req` is decoded and `req.ProjectID` validated (these handlers already validate/log `req.ProjectID`) and BEFORE the first `h.logger`/service use:

```go
	if !requireProjectRole(w, r, req.ProjectID, models.ProjectMemberRoleDeveloper, h.roleResolver) {
		return
	}
```

- [ ] **Step 5: Inject in `main.go`** beside the other `SetRoleResolver` calls. Data-source handler is built conditionally as `dsHandler` (main.go:473) — set the resolver inside the same block (or guard with `if dsHandler != nil`):

```go
	aiQueryHandler.SetRoleResolver(roleResolver)
	kgGenHandler.SetRoleResolver(roleResolver)
	if dsHandler != nil {
		dsHandler.SetRoleResolver(roleResolver)
	}
```

(Confirm variable names `aiQueryHandler`, `kgGenHandler`, `dsHandler` at main.go:580/519/473.)

- [ ] **Step 6: Run tests + build**

Run: `cd ennam.kg.go && go test -race ./internal/handler/ -run 'ProjectViewerForbidden' -v && go build ./...`
Expected: PASS, no errors

- [ ] **Step 7: Commit**

```bash
git -C ennam.kg.go add internal/handler/datasource.go internal/handler/kg_generation.go internal/handler/ai_query.go internal/handler/role_writes_test.go cmd/kg-server/main.go
git -C ennam.kg.go commit -m "feat(ba015): enforce developer-min role on data-source create, KG-gen, AI-query submit"
```

---

## Task 5: Project update requires project admin (BR-001.5 / BR-005.3)

**Files:**
- Modify: `ennam.kg.go/internal/handler/project.go` (`HandleUpdateProject`, the `TODO(BA-014)` ~line 218)

**Interfaces:**
- Consumes: `h.service.GetMembership` directly — `ProjectHandler` DOES hold `*service.ProjectService` (unlike the node/edge handlers), so no resolver injection is needed here.
- Produces: `PUT /api/v1/projects/{id}` returns 403 for non-admin members.

- [ ] **Step 1: Read the current handler**

Read `ennam.kg.go/internal/handler/project.go:198-235` to confirm the `TODO(BA-014)` block and that `id := r.PathValue("id")`.

- [ ] **Step 2: Write the failing test**

Create `ennam.kg.go/internal/handler/project_update_role_test.go`, reusing `mockMemberRepo`/`memberKey` from `project_member_test.go`:

```go
package handler

import (
	"context"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/service"
)

func TestHandleUpdateProject_DeveloperForbidden(t *testing.T) {
	repo := newMockMemberRepo()
	repo.memberships[memberKey("proj-1", "u-dev")] = &models.ProjectMember{
		ProjectID: "proj-1", UserID: "u-dev", Role: models.ProjectMemberRoleDeveloper,
	}
	svc := service.NewProjectService(nil, repo, nil, slog.Default())
	h := NewProjectHandler(nil, svc, slog.Default())

	r := httptest.NewRequest(http.MethodPut, "/api/v1/projects/proj-1", strings.NewReader(`{"name":"new"}`))
	r.SetPathValue("id", "proj-1")
	ctx := context.WithValue(r.Context(), middleware.UserIdentityKey,
		&middleware.UserIdentity{UserID: "u-dev", Role: "developer"})
	r = r.WithContext(ctx)
	w := httptest.NewRecorder()

	h.HandleUpdateProject(w, r)

	if w.Code != http.StatusForbidden {
		t.Fatalf("developer updating project must get 403, got %d: %s", w.Code, w.Body.String())
	}
}
```

`NewProjectHandler(nil, svc, slog.Default())` matches the verified signature `NewProjectHandler(s *store.ProjectStore, svc *service.ProjectService, logger *slog.Logger)`. The access check is near the top of `HandleUpdateProject`, before `h.service.GetProject`, so the nil store is never dereferenced.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestHandleUpdateProject_DeveloperForbidden -v`
Expected: FAIL — current code only checks `HasProjectAccess`, lets developer through.

- [ ] **Step 4: Replace the `TODO(BA-014)` block in `HandleUpdateProject`**

```go
	// Check access: global admin or project admin (BR-001.5 / BR-005.3).
	// `id` is the project id from r.PathValue("id"), already declared above this block.
	if !isGlobalAdmin(r) {
		if middleware.GetUserIdentity(r.Context()) != nil {
			// Phase 3 user: require project admin role.
			m, err := h.service.GetMembership(r.Context(), id, resolveUserID(r))
			if err != nil || m == nil || !m.Role.CanManage() {
				errorResponse(w, http.StatusForbidden, "access denied: project admin role required")
				return
			}
		} else {
			// Legacy API-key caller: fall back to API-key project access.
			identity := middleware.GetDeveloperIdentity(r.Context())
			if identity == nil || !identity.HasProjectAccess(id) {
				errorResponse(w, http.StatusForbidden, "access denied for this project")
				return
			}
		}
	}
```

This reuses the existing `id` variable (`id := r.PathValue("id")` near the top of the handler) — do not redeclare it.

- [ ] **Step 5: Run test + build**

Run: `cd ennam.kg.go && go test -race ./internal/handler/ -run TestHandleUpdateProject_DeveloperForbidden -v && go build ./...`
Expected: PASS, no errors

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.go add internal/handler/project.go internal/handler/project_update_role_test.go
git -C ennam.kg.go commit -m "feat(ba015): project update requires project admin role (BR-001.5)"
```

---

## Phase B — deferred (NOT in this plan, documented so it is not assumed done)

These write operations identify the target entity by `r.PathValue("id")` and have **no project context at the handler layer** (no body `project_id`, no archive check, and `GetEffectiveProjectID(ctx)` is unreliable because the Next.js BFF forwards only `Authorization`/`Content-Type`, so the effective project falls back to the API key's default — not the entity's real project). Enforcing them correctly requires resolving the **entity's own project**, best done at the **service layer** (the service already loads the entity to mutate it — e.g. `UpdateService.UpdateNode` loads the existing node), or via a dedicated entity→project lookup injected into the handler.

**Deferred handlers (all min `developer`, except project-data delete which is `admin`):**
- `UpdateHandler` (NOT `NodeHandler`): `HandleUpdateNode` + per-type `HandleUpdateDecision/Concept/Requirement/Task/Architecture/Discovery` (update.go, update_*.go).
- `deprecate.go`: `HandleDeprecateNode`.
- `kg_generation.go`: `UpdateNodeDescription`, `UpdateConfidence`, `ConfirmEdge`, `RejectEdge`, `UnrejectEdge`.
- `datasource.go`: `Update`, `Delete`, `TestConnection`, `ExtractSchema`, `SyncSchema`.

**Current protection gap until Phase B ships:** project-scoped viewers are NOT blocked from these operations by the new project-role guard. The pre-existing `APIKeyRoleViewer` check (`node.go`/`link.go`) only covers node/edge **create**, not these. A global-`developer` user who is a project `viewer` can still update/deprecate/confirm. This is a known, flagged gap — not silent.

**Also out of scope (cosmetic / cross-cutting):**
- BR-002.3 archived-block message wording (`"cannot write to archived project"` vs spec's `"project is archived: write operations are disabled"`).
- Frontend role-aware control disabling (hide Create/Edit for viewers) — drive from the `useMyProjectRole` hook (BA-014 plan). The API now returns 403 regardless.
- "Delete project data" matrix row (project admin) — no single endpoint identified; revisit during Phase B with the data-source/node delete handlers.

---

## Self-Review

### Spec coverage (FR-005 matrix) — Phase A

| Matrix row | Min role | Status |
|---|---|---|
| Create nodes | developer | Task 2 ✅ |
| Create edges | developer | Task 3 ✅ |
| Manage data sources (create) | developer | Task 4 ✅ (create only; update/delete/sync → Phase B) |
| Trigger KG generation | developer | Task 4 ✅ |
| Submit AI queries | developer | Task 4 ✅ |
| Update project details | project admin | Task 5 ✅ |
| Update/deprecate nodes, edge confirm/reject, data-source update/sync | developer | **Phase B** (deferred, documented) |
| Manage members / archive | admin / global | Already implemented (FR-004 / project.go) |
| View data / list members / stats | viewer | Read paths — no guard needed |

### Risk notes

- **Backward compatibility is load-bearing.** The legacy-API-key bypass (`GetUserIdentity == nil → allow`) keeps MCP/CLI working; `TestRequireProjectRole_LegacyAPIKeyBypass` locks it in.
- **Two complementary viewer checks on create.** Node/edge create now have BOTH the pre-existing `APIKeyRoleViewer` (global) check AND the new project-role guard. Intentional — they cover different layers. Not a duplicate to remove.
- **Guard placement before nil deref.** Tests use zero-value handlers (nil logger/svc); guards are placed after body-decode and before the first `h.logger`/`h.svc` use, so the 403 returns without panic. Verified for `HandleStoreNode` (guard sits at the archive-check point, before `h.logger.InfoContext`).
- **Phase A is correct-and-complete for the spec's only AC-tested write** (node create → viewer 403). Phase B covers the untested matrix remainder.

### Placeholder / type-consistency check

- 403 body shape identical in `writeInsufficientRole` and assertions — consistent.
- `ProjectRoleResolverFunc` signature identical across type def, helper param, and main.go closure — consistent.
- `SetRoleResolver` named identically across `NodeHandler`/`LinkHandler`/`DataSourceHandler`/`KGGenerationHandler`/`AIQueryHandler` — consistent.
- `NewProjectHandler(nil, svc, slog.Default())` matches the verified 3-arg signature.
- Min-role constants match the matrix (`…Developer` for data writes, `…Admin`/`CanManage()` for project update).
