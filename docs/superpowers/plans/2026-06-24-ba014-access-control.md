# BA-014 / BA-015 Access Control Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce role-based access control on project membership endpoints (Go) and gate admin UI surfaces (Next.js).

**Architecture:** Two-layer approach — (1) Go API returns 403 at the server using `UserIdentity` already injected by `middleware.Auth` + `WithUserResolver`; (2) Next.js gates `/admin/*` via a server-component route-group layout guard and hides UI controls via the user's role. No new tables or migrations.

**Tech Stack:** Go stdlib `net/http`, `internal/middleware` (`GetUserIdentity`, `GetDeveloperIdentity`), `internal/service.ProjectService` + `MemberRepository`, Next.js 16 App Router server-component layouts, iron-session `getSession()`, TanStack Query (`useCurrentUser`, `useProjectMembers`).

## Global Constraints

- **Go: `WithUserResolver` is ALREADY wired** in `cmd/kg-server/main.go:1073-1074`. `middleware.GetUserIdentity(r.Context())` returns `*middleware.UserIdentity` with `.UserID string` (UUID) and `.Role string` ("admin"|"developer"|"viewer"). Returns `nil` for legacy API keys with no linked user.
- **Go: legacy API keys** (MCP agents, CLI) use `middleware.GetDeveloperIdentity`, NOT `GetUserIdentity`. Admin-bypass logic must check both.
- **Go: helpers in `internal/handler/project.go`** (same package `handler`): `resolveUserID(r) string` and `isGlobalAdmin(r) bool`. `errorResponse(w, code, msg)` is in `internal/handler/search.go`.
- **Go: model symbols** — `models.UserRoleAdmin UserRole = "admin"`; `models.ProjectMemberRoleAdmin/Developer/Viewer`; `(ProjectMemberRole).CanManage() bool` (true for admin only).
- **Go: test convention** — tests live in `package handler` (in-package, NOT `handler_test`), use in-package mock repos implementing service interfaces (see `mockUserRepo` in `user_test.go`), construct a real `service.NewProjectService(...)` with the mock. Inject identity via `context.WithValue(ctx, middleware.UserIdentityKey, &middleware.UserIdentity{...})` — `UserIdentityKey` is an exported package var.
- **Go: `service.MemberRepository` interface** (in `internal/service/project.go`) methods: `Add`, `Remove`, `ChangeRole`, `ListByProject`, `ListByUser`, `GetMembership(ctx, projectID, userID) (*models.ProjectMember, error)`, `CountAdmins(ctx, projectID) (int, error)`.
- **Next.js: `(dashboard)/layout.tsx` already** calls `getSession()` and redirects unauthenticated → `/login` and `requiresPasswordChange` → `/change-password`. Do NOT duplicate the auth redirect. It renders `<DashboardShell displayName username role={session.role}>`.
- **Next.js: `SessionData.role`** is the global role string. `useCurrentUser()` (in `src/hooks/use-auth.ts`) fetches `/api/kg/users/me` → `User` (has `.id` and `.role`). `useProjectMembers(projectId)` returns members with `.user_id` and `.role`.
- **Tests: Go** — table-driven, `go test -race ./internal/handler/...`.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `ennam.kg.go/internal/handler/project.go` | Modify | `isGlobalAdmin` recognises `UserIdentity.Role == "admin"` (Phase 3 sessions) |
| `ennam.kg.go/internal/service/project.go` | Modify | Expose public `GetMembership` on `ProjectService` |
| `ennam.kg.go/internal/handler/project_member.go` | Modify | Add `requireProjectAdmin`/`isMember` helpers; fill 4 TODOs |
| `ennam.kg.go/internal/handler/project_member_test.go` | Create | Table-driven tests with mock `MemberRepository` |
| `ennam.kg.next/src/app/(dashboard)/admin/layout.tsx` | Create | Server-component guard: non-admin → redirect `/` |
| `ennam.kg.next/src/components/layout/DashboardShell.tsx` | Modify | Pass `role` to `<Sidebar>` |
| `ennam.kg.next/src/components/layout/Sidebar.tsx` | Modify | Hide ADMIN nav section when `role !== 'admin'` |
| `ennam.kg.next/src/hooks/use-my-project-role.ts` | Create | Derive caller's project role from members list + `useCurrentUser` |
| `ennam.kg.next/src/app/(dashboard)/projects/[id]/members/page.tsx` | Modify | Replace `canManage = true` with real role check |

---

## Task 1: `isGlobalAdmin` recognises Phase 3 user sessions

**Files:**
- Modify: `ennam.kg.go/internal/handler/project.go` (function `isGlobalAdmin`, ~lines 49-56)

**Interfaces:**
- Produces: `isGlobalAdmin(r *http.Request) bool` — true when caller is global admin via Phase 3 `UserIdentity` OR legacy admin API key.

> Behaviour is verified by Task 3's global-admin test (a global admin with no membership is NOT forbidden). No standalone test in this task — the change is a small predicate exercised end-to-end in Task 3.

- [ ] **Step 1: Read the current function**

Read `ennam.kg.go/internal/handler/project.go:49-56` to confirm the current body matches the `BEFORE` below.

- [ ] **Step 2: Replace `isGlobalAdmin`**

```go
// isGlobalAdmin checks whether the authenticated caller has global admin role.
// Prefers Phase 3 UserIdentity (dashboard login sessions); falls back to the
// legacy DeveloperIdentity (API key role) for MCP agents and CLI tools.
func isGlobalAdmin(r *http.Request) bool {
	if userIdentity := middleware.GetUserIdentity(r.Context()); userIdentity != nil {
		return userIdentity.Role == string(models.UserRoleAdmin)
	}
	identity := middleware.GetDeveloperIdentity(r.Context())
	if identity == nil {
		return false
	}
	return identity.Role == models.APIKeyRoleAdmin && len(identity.ProjectIDs) == 0
}
```

`middleware` and `models` are already imported in `project.go`.

- [ ] **Step 3: Verify it compiles**

Run: `cd ennam.kg.go && go build ./...`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git -C ennam.kg.go add internal/handler/project.go
git -C ennam.kg.go commit -m "fix(handler): isGlobalAdmin recognises Phase 3 UserIdentity sessions"
```

---

## Task 2: Expose `GetMembership` on `ProjectService`

**Files:**
- Modify: `ennam.kg.go/internal/service/project.go`

**Interfaces:**
- Produces: `func (s *ProjectService) GetMembership(ctx context.Context, projectID, userID string) (*models.ProjectMember, error)`
- Consumed by: Task 3.

- [ ] **Step 1: Confirm it does not already exist**

Run: `grep -n "func (s \*ProjectService) GetMembership" ennam.kg.go/internal/service/project.go`
Expected: no output.

- [ ] **Step 2: Add the method at the end of the file**

```go
// GetMembership returns a user's project membership record, or nil if the user
// is not a member of the project.
func (s *ProjectService) GetMembership(ctx context.Context, projectID, userID string) (*models.ProjectMember, error) {
	return s.members.GetMembership(ctx, projectID, userID)
}
```

- [ ] **Step 3: Verify it compiles**

Run: `cd ennam.kg.go && go build ./...`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git -C ennam.kg.go add internal/service/project.go
git -C ennam.kg.go commit -m "feat(service): expose GetMembership on ProjectService for access checks"
```

---

## Task 3: Enforce access control on all 4 member endpoints

**Files:**
- Modify: `ennam.kg.go/internal/handler/project_member.go`
- Create: `ennam.kg.go/internal/handler/project_member_test.go`

**Interfaces:**
- Consumes: `isGlobalAdmin(r)` (Task 1), `h.service.GetMembership(...)` (Task 2), `resolveUserID(r)`.
- Produces: 403 from `ListMembers` (non-member), and from `AddMember`/`ChangeRole`/`RemoveMember` (non project-admin).

**Access rules (BA-015 BR-004):**
- `ListMembers` (GET): member OR global admin.
- `AddMember`/`ChangeRole`/`RemoveMember`: project role `admin` OR global admin.

- [ ] **Step 1: Write the failing tests**

Create `ennam.kg.go/internal/handler/project_member_test.go`:

```go
package handler

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/service"
)

// mockMemberRepo implements service.MemberRepository for access-control tests.
type mockMemberRepo struct {
	memberships map[string]*models.ProjectMember // key: projectID+"|"+userID
}

func newMockMemberRepo() *mockMemberRepo {
	return &mockMemberRepo{memberships: make(map[string]*models.ProjectMember)}
}

func memberKey(projectID, userID string) string { return projectID + "|" + userID }

func (m *mockMemberRepo) Add(_ context.Context, member *models.ProjectMember) (*models.ProjectMember, error) {
	m.memberships[memberKey(member.ProjectID, member.UserID)] = member
	return member, nil
}
func (m *mockMemberRepo) Remove(_ context.Context, projectID, userID string) (*models.ProjectMember, error) {
	delete(m.memberships, memberKey(projectID, userID))
	return &models.ProjectMember{ProjectID: projectID, UserID: userID}, nil
}
func (m *mockMemberRepo) ChangeRole(_ context.Context, projectID, userID string, newRole models.ProjectMemberRole) (*models.ProjectMember, error) {
	mem := m.memberships[memberKey(projectID, userID)]
	if mem == nil {
		mem = &models.ProjectMember{ProjectID: projectID, UserID: userID}
	}
	mem.Role = newRole
	return mem, nil
}
func (m *mockMemberRepo) ListByProject(_ context.Context, projectID string) ([]models.ProjectMemberWithUser, error) {
	return nil, nil
}
func (m *mockMemberRepo) ListByUser(_ context.Context, userID string) ([]models.ProjectMember, error) {
	return nil, nil
}
func (m *mockMemberRepo) GetMembership(_ context.Context, projectID, userID string) (*models.ProjectMember, error) {
	return m.memberships[memberKey(projectID, userID)], nil
}
func (m *mockMemberRepo) CountAdmins(_ context.Context, projectID string) (int, error) {
	count := 0
	for _, mem := range m.memberships {
		if mem.ProjectID == projectID && mem.Role == models.ProjectMemberRoleAdmin {
			count++
		}
	}
	return count, nil
}

// newTestMemberHandler builds a handler backed by a real ProjectService + mock repo.
// apiKeys=nil and projects=nil are unused by the access-control paths under test.
func newTestMemberHandler(repo service.MemberRepository) *ProjectMemberHandler {
	svc := service.NewProjectService(nil, repo, nil, slog.Default())
	return NewProjectMemberHandler(svc, slog.Default())
}

// withUser attaches a Phase 3 UserIdentity to the request context.
func withUser(r *http.Request, userID, role string) *http.Request {
	ctx := context.WithValue(r.Context(), middleware.UserIdentityKey, &middleware.UserIdentity{
		UserID: userID,
		Role:   role,
	})
	return r.WithContext(ctx)
}

func TestListMembers_NonMember_Returns403(t *testing.T) {
	// Arrange: caller is a developer with NO membership in proj-1.
	h := newTestMemberHandler(newMockMemberRepo())
	req := httptest.NewRequest(http.MethodGet, "/api/v1/projects/proj-1/members", nil)
	req.SetPathValue("id", "proj-1")
	req = withUser(req, "user-outsider", "developer")
	rr := httptest.NewRecorder()

	// Act
	h.ListMembers(rr, req)

	// Assert: non-members must not see the roster (BA-015 UC-004.4 / BR-003.3).
	if rr.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d: %s", rr.Code, rr.Body.String())
	}
}

func TestListMembers_Member_NotForbidden(t *testing.T) {
	repo := newMockMemberRepo()
	repo.memberships[memberKey("proj-1", "user-dev")] = &models.ProjectMember{
		ProjectID: "proj-1", UserID: "user-dev", Role: models.ProjectMemberRoleDeveloper,
	}
	h := newTestMemberHandler(repo)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/projects/proj-1/members", nil)
	req.SetPathValue("id", "proj-1")
	req = withUser(req, "user-dev", "developer")
	rr := httptest.NewRecorder()

	h.ListMembers(rr, req)

	// A member may list; access check must not block (200 from the nil-mock ListByProject).
	if rr.Code == http.StatusForbidden {
		t.Fatalf("member should not be forbidden, got 403: %s", rr.Body.String())
	}
}

func TestAddMember_NonAdminMember_Returns403(t *testing.T) {
	repo := newMockMemberRepo()
	repo.memberships[memberKey("proj-1", "user-dev")] = &models.ProjectMember{
		ProjectID: "proj-1", UserID: "user-dev", Role: models.ProjectMemberRoleDeveloper,
	}
	h := newTestMemberHandler(repo)
	body, _ := json.Marshal(map[string]string{"user_id": "user-new", "role": "developer"})
	req := httptest.NewRequest(http.MethodPost, "/api/v1/projects/proj-1/members", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.SetPathValue("id", "proj-1")
	req = withUser(req, "user-dev", "developer")
	rr := httptest.NewRecorder()

	h.AddMember(rr, req)

	// Only project admins manage membership (BA-015 BR-004.1).
	if rr.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d: %s", rr.Code, rr.Body.String())
	}
}

func TestAddMember_GlobalAdmin_NotForbidden(t *testing.T) {
	repo := newMockMemberRepo() // global admin has NO explicit membership
	h := newTestMemberHandler(repo)
	body, _ := json.Marshal(map[string]string{"user_id": "user-new", "role": "developer"})
	req := httptest.NewRequest(http.MethodPost, "/api/v1/projects/proj-1/members", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.SetPathValue("id", "proj-1")
	req = withUser(req, "user-admin", "admin")
	rr := httptest.NewRecorder()

	h.AddMember(rr, req)

	// Global admin bypasses membership requirement (BA-015 BR-004.2).
	if rr.Code == http.StatusForbidden {
		t.Fatalf("global admin must not be forbidden, got 403: %s", rr.Body.String())
	}
}

func TestRemoveMember_NonAdmin_Returns403(t *testing.T) {
	repo := newMockMemberRepo()
	repo.memberships[memberKey("proj-1", "user-dev")] = &models.ProjectMember{
		ProjectID: "proj-1", UserID: "user-dev", Role: models.ProjectMemberRoleDeveloper,
	}
	h := newTestMemberHandler(repo)
	req := httptest.NewRequest(http.MethodDelete, "/api/v1/projects/proj-1/members/user-x", nil)
	req.SetPathValue("id", "proj-1")
	req.SetPathValue("user_id", "user-x")
	req = withUser(req, "user-dev", "developer")
	rr := httptest.NewRecorder()

	h.RemoveMember(rr, req)

	if rr.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d: %s", rr.Code, rr.Body.String())
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run 'TestListMembers|TestAddMember|TestRemoveMember' -v`
Expected: FAIL — current handlers do not return 403 (the access checks are TODO stubs).

- [ ] **Step 3: Add helpers + fill TODOs in `project_member.go`**

Add `"context"` to the import block. Add these helpers above `ListMembers`:

```go
// isMember reports whether the caller may view the project (global admin OR any member).
func (h *ProjectMemberHandler) isMember(ctx context.Context, projectID string, r *http.Request) bool {
	if isGlobalAdmin(r) {
		return true
	}
	callerID := resolveUserID(r)
	if callerID == "" {
		return false
	}
	membership, err := h.service.GetMembership(ctx, projectID, callerID)
	return err == nil && membership != nil
}

// requireProjectAdmin reports whether the caller may manage membership
// (global admin OR a member whose project role can manage — i.e. admin).
func (h *ProjectMemberHandler) requireProjectAdmin(ctx context.Context, projectID string, r *http.Request) bool {
	if isGlobalAdmin(r) {
		return true
	}
	callerID := resolveUserID(r)
	if callerID == "" {
		return false
	}
	membership, err := h.service.GetMembership(ctx, projectID, callerID)
	if err != nil || membership == nil {
		return false
	}
	return membership.Role.CanManage()
}
```

In `ListMembers`, replace the TODO comment block (lines ~34-36) with:

```go
	if !h.isMember(r.Context(), projectID, r) {
		errorResponse(w, http.StatusForbidden, "access denied: you are not a member of this project")
		return
	}
```

In `AddMember`, replace the TODO comment (lines ~67-68) with:

```go
	if !h.requireProjectAdmin(r.Context(), projectID, r) {
		errorResponse(w, http.StatusForbidden, "access denied: project admin role required")
		return
	}
```

In `ChangeRole`, replace the TODO comment (line ~128) with the same `requireProjectAdmin` block (inserted after the projectID/userID empty check, before `json.NewDecoder`).

In `RemoveMember`, replace the TODO comment (line ~182) with the same `requireProjectAdmin` block (inserted after the projectID/userID empty check, before `h.service.RemoveMember`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.go && go test -race ./internal/handler/ -run 'TestListMembers|TestAddMember|TestRemoveMember' -v`
Expected: PASS (5 tests)

Run: `cd ennam.kg.go && go build ./...`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/handler/project_member.go internal/handler/project_member_test.go
git -C ennam.kg.go commit -m "feat(ba014): enforce project membership access control on member endpoints"
```

---

## Task 4: Server-component guard for `/admin/*` routes

**Files:**
- Create: `ennam.kg.next/src/app/(dashboard)/admin/layout.tsx`

**Interfaces:**
- Produces: a server layout that redirects non-admin users away from any `/admin/*` route.
- Consumes: `getSession()` from `@/lib/auth/session`.

**Why a layout, not edge middleware:** all `/admin/*` routes live under `(dashboard)/admin/`. The existing `(dashboard)/layout.tsx` already does server-side `getSession()` + auth redirect, so an admin sub-layout matches the established pattern and avoids the edge-runtime session-secret pitfall.

- [ ] **Step 1: Create the admin layout**

```tsx
import { redirect } from 'next/navigation';
import { getSession } from '@/lib/auth/session';

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await getSession();

  // The parent (dashboard) layout already guards isLoggedIn; here we gate role.
  if (session.role !== 'admin') {
    redirect('/');
  }

  return <>{children}</>;
}
```

- [ ] **Step 2: Verify build**

Run: `cd ennam.kg.next && npm run build`
Expected: no errors.

- [ ] **Step 3: Test in browser** (`npm run dev`)

1. Log in as `developer` → navigate to `/admin/users` → redirected to `/`.
2. Log in as `admin` → `/admin/users` loads.

- [ ] **Step 4: Commit**

```bash
git -C ennam.kg.next add "src/app/(dashboard)/admin/layout.tsx"
git -C ennam.kg.next commit -m "feat(ba014): server-side admin route guard for /admin/* routes"
```

---

## Task 5: Hide ADMIN sidebar section for non-admins

**Files:**
- Modify: `ennam.kg.next/src/components/layout/DashboardShell.tsx` (pass `role` to `<Sidebar>`)
- Modify: `ennam.kg.next/src/components/layout/Sidebar.tsx`

**Interfaces:**
- Consumes: `role` prop — already received by `DashboardShell` from `(dashboard)/layout.tsx`.
- Produces: `<Sidebar role={role} />`; Sidebar hides the ADMIN section when `role !== 'admin'`.

> `(dashboard)/layout.tsx` already passes `session.role` to `DashboardShell`. Do NOT modify the layout — only thread `role` from the shell into `Sidebar`.

- [ ] **Step 1: Pass `role` to `<Sidebar>` in `DashboardShell.tsx`**

The component already accepts a `role?: string` prop. Find the `<Sidebar />` render (around line 25) and change it to:

```tsx
<Sidebar role={role} />
```

Confirm `role` is in scope at that render site (the inner component must receive `role` as a prop — if `<Sidebar />` is rendered inside a child that doesn't get `role`, thread it through). Read the file first to confirm the prop reaches the render site.

- [ ] **Step 2: Accept and use `role` in `Sidebar.tsx`**

Change the component signature from `export default function Sidebar()` to accept props, and filter the ADMIN section:

```tsx
interface SidebarProps {
  role?: string;
}

export default function Sidebar({ role }: SidebarProps) {
```

Then where `navSections.map(...)` is used to render sections, filter first:

```tsx
const visibleSections = navSections.filter(
  (section) => section.label !== 'ADMIN' || role === 'admin',
);
```

Replace the `navSections.map(...)` iteration with `visibleSections.map(...)`.

- [ ] **Step 3: Verify build**

Run: `cd ennam.kg.next && npx tsc --noEmit && npm run build`
Expected: no errors.

- [ ] **Step 4: Test in browser**

1. Log in as `developer` → ADMIN section absent from sidebar.
2. Log in as `admin` → ADMIN section present.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.next add src/components/layout/DashboardShell.tsx src/components/layout/Sidebar.tsx
git -C ennam.kg.next commit -m "feat(ba014): hide ADMIN sidebar section for non-admin users"
```

---

## Task 6: Real `canManage` on the project members page

**Files:**
- Create: `ennam.kg.next/src/hooks/use-my-project-role.ts`
- Modify: `ennam.kg.next/src/app/(dashboard)/projects/[id]/members/page.tsx`

**Interfaces:**
- Produces: `useMyProjectRole(projectId: string)` → `{ role: ProjectMemberRole | null; isAdmin: boolean; isLoading: boolean }`.
- Consumes: `useCurrentUser()` (`User` with `.id`, `.role`) + `useProjectMembers(projectId)` (members with `.user_id`, `.role`).

> No new API route. The members list is already fetched; find the current user in it by `user.id === member.user_id`. Global admins (who may not be explicit members) are granted manage rights via the user's global `role`.

- [ ] **Step 1: Create the hook**

```typescript
import { useMemo } from 'react';
import { useCurrentUser } from '@/hooks/use-auth';
import { useProjectMembers } from '@/hooks/use-project-members';
import type { ProjectMemberRole } from '@/types/project-member';

export function useMyProjectRole(projectId: string) {
  const { data: currentUser, isLoading: userLoading } = useCurrentUser();
  const { data: members, isLoading: membersLoading } = useProjectMembers(projectId);

  const role = useMemo<ProjectMemberRole | null>(() => {
    if (!currentUser?.id || !members) return null;
    const me = members.find((m) => m.user_id === currentUser.id);
    return (me?.role as ProjectMemberRole) ?? null;
  }, [currentUser?.id, members]);

  // Global admins manage any project even without explicit membership (BA-015 BR-004.2).
  const isAdmin = role === 'admin' || currentUser?.role === 'admin';

  return { role, isAdmin, isLoading: userLoading || membersLoading };
}
```

- [ ] **Step 2: Verify `User` and member field names**

Run:
```bash
grep -n "id\|role" ennam.kg.next/src/types/user.ts | head
grep -n "user_id\|role" ennam.kg.next/src/types/project-member.ts | head
```
Expected: `User` has `id: string` and `role`; member type has `user_id` and `role`. If `useProjectMembers` returns a wrapped shape, confirm `.find` runs on the array (it returns the array per prior fix).

- [ ] **Step 3: Use the hook in the members page**

In `ennam.kg.next/src/app/(dashboard)/projects/[id]/members/page.tsx`, add the import and replace `const canManage = true;`:

```tsx
import { useMyProjectRole } from '@/hooks/use-my-project-role';
// ...
const { isAdmin: canManage } = useMyProjectRole(id);
```

(`id` is the existing route param used elsewhere in the file.)

- [ ] **Step 4: Verify build**

Run: `cd ennam.kg.next && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Test in browser**

1. Project `developer` member → Add Member button + role controls hidden.
2. Project `admin` member → all controls visible.
3. Global `admin` (not an explicit member) → controls visible (via `currentUser.role === 'admin'`).

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.next add src/hooks/use-my-project-role.ts "src/app/(dashboard)/projects/[id]/members/page.tsx"
git -C ennam.kg.next commit -m "feat(ba014): derive members-page canManage from real project role"
```

---

## Self-Review

### Spec coverage (BA-015)

| Requirement | Status |
|---|---|
| BR-004.1 project admin manages members | Task 3 (`requireProjectAdmin` on Add/Change/Remove) |
| BR-004.2 global admin implicit access | Task 1 + Task 3 (`isGlobalAdmin` bypass) |
| BR-004.3 last-admin protection | **Already implemented** in `service.ChangeRole`/`RemoveMember` (verified) |
| UC-004.4 member lists members | Task 3 (`isMember` on `ListMembers`) |
| Admin UI surfaces gated | Tasks 4–6 |

### Out of scope (separate follow-up plan — NOT covered here)

These are real BA-015 gaps but distinct work; flagged so they are not assumed done:
- **BR-002.3 archived-project write block** — needs a write-guard across node/edge/sync handlers.
- **BR-003.1/3.3 membership-filtered GET `/projects` + detail 403** — partly present in `project.go` via the legacy `DeveloperIdentity` path; needs auditing against Phase 3 `UserIdentity` (Task 1 improves this, but a full pass on `HandleListProjects`/`HandleGetProject` is not in this plan).
- **BR-001.1 POST `/projects` admin-only** — already enforced in `HandleCreateProject` (verified); Task 1 makes it work for dashboard admins too. No new task.

### Risk notes

- **Go tests use a real `ProjectService` + mock repo** (not a nil service). `service.NewProjectService(nil, repo, nil, logger)` is safe for the membership paths under test: `AddMember`/`RemoveMember`/`ChangeRole` all guard `if s.apiKeys != nil` before syncing (verified), so the nil `apiKeys` syncer never panics; `projects` (nil) is unused on these paths. The global-admin `AddMember` test therefore reaches `201 Created` (mock `Add` returns cleanly), asserting only `!= 403`.
- **Next.js admin guard** relies on `(dashboard)/layout.tsx` already redirecting unauthenticated users; the admin layout only adds the role gate. If route-group nesting changes, re-verify.

### Placeholder / type-consistency check

- No TBDs. All code blocks complete.
- `UserIdentity.Role` (string) compared to `string(models.UserRoleAdmin)` — consistent.
- `ProjectMemberRole.CanManage()` used in `requireProjectAdmin` — exists (verified).
- Hook returns `{ role, isAdmin, isLoading }`; page destructures `{ isAdmin: canManage }` — consistent.
