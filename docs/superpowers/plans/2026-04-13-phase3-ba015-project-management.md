# BA-015 Project Management & Access Control — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Phase 3, Step 2.** Depends on BA-014 (users table, migration 032). Must complete before BA-016 (API key overhaul).

**Goal:** Upgrade projects from read-only catalog entries into first-class managed resources with CRUD, membership roles, archiving, and project-scoped access control — replacing the flat `api_keys.project_ids` array with a proper `project_members` join table.

**Architecture:** Extends existing `internal/store/project.go`, `internal/handler/project.go`. New `project_member` store/handler pair. New `internal/service/project.go` for business logic (auto-membership, API key sync, last-admin guard). Middleware upgrades: wire `ProjectID` middleware, switch access checks from `api_keys.project_ids` to `project_members`, inject project role into context, block writes on archived projects.

**Tech Stack:** Go std lib, `database/sql`, PostgreSQL

**BA Reference:** `ennam.kg.requirements/documents/phase3/BA-015-project-management.md`

**Prerequisites:** BA-014 (users table + migration 032 must exist)

---

## What Already Exists

- `internal/models/project.go` — `Project` struct (ID, Name, Description, RepoURL, Status, CreatedAt, UpdatedAt)
- `internal/store/project.go` — `ProjectStore` with `List()` (active only) and `GetByID()`
- `internal/handler/project.go` — `ProjectHandler` with `GET /api/v1/projects` and `GET /api/v1/projects/{id}`
- `internal/middleware/project.go` — `ProjectID` middleware (fully implemented but **not wired** in `buildRouter`)
- `internal/middleware/auth.go` — `DeveloperIdentity` with `HasProjectAccess()` checking `api_keys.project_ids`
- `cmd/kg-server/main.go` — `buildRouter()` applies Auth middleware but not ProjectID middleware

## What's Missing

- **Migration 033**: `archived_at`/`archived_by` columns on `projects`, `project_members` table
- **ProjectMember model**: No struct for membership records
- **Project CRUD store methods**: Only List/GetByID exist — no Create, Update, Archive, Unarchive, GetStats
- **ProjectMember store**: Entirely missing — Add, Remove, ChangeRole, ListByProject, ListByUser, GetMembership, CountAdmins
- **Project service**: No business logic layer — auto-add creator as admin, API key sync, archive/unarchive orchestration
- **Membership service**: No member management — last-admin protection, role changes, API key sync on add/remove
- **Handler expansion**: No POST/PUT/Archive/Unarchive/Stats endpoints, no membership endpoints
- **Middleware wiring**: ProjectID middleware exists but is not called; access checks still use `api_keys.project_ids` instead of `project_members`; no archive write-block; no project role in context

---

## Permission Matrix

| Action | Viewer | Developer | Project Admin | Global Admin |
|---|:---:|:---:|:---:|:---:|
| Read project / list members | yes | yes | yes | yes |
| Write (nodes/edges/sync) | -- | yes | yes | yes |
| Update project metadata | -- | -- | yes | yes |
| Manage members (add/remove/change role) | -- | -- | yes | yes |
| Archive / Unarchive project | -- | -- | -- | yes |

---

## File Structure

### New Files

```
db/migrations/
├── 000033_project_extensions_and_members.up.sql
├── 000033_project_extensions_and_members.down.sql

internal/models/
├── project_member.go

internal/store/
├── project_member.go
├── project_member_test.go

internal/service/
├── project.go               # ProjectService + MembershipService
├── project_test.go

internal/handler/
├── project_member.go
├── project_member_test.go
```

### Modified Files

```
internal/models/project.go                 # Add ArchivedAt, ArchivedBy fields
internal/store/project.go                  # Add Create, Update, Archive, Unarchive, ListForUser, GetStats
internal/store/project_test.go             # Tests for new store methods
internal/handler/project.go                # Add 5 new endpoints + modify 2 existing
internal/handler/project_test.go           # Tests for new/modified endpoints
internal/middleware/project.go             # Add project role context + archive write-block
internal/middleware/auth.go                # Update HasProjectAccess to check project_members
cmd/kg-server/main.go                     # Wire ProjectID middleware, service layer, new handlers
```

---

## Task 1: Migration 033 — Project Extensions + Project Members

**Files:**
- Create: `db/migrations/000033_project_extensions_and_members.up.sql`
- Create: `db/migrations/000033_project_extensions_and_members.down.sql`

- [ ] **Step 1: Write up migration**

```sql
-- 000033_project_extensions_and_members.up.sql

-- Extend projects table with archive support.
ALTER TABLE projects ADD COLUMN archived_at TIMESTAMPTZ;
ALTER TABLE projects ADD COLUMN archived_by UUID REFERENCES users(id);
CREATE INDEX idx_projects_status ON projects (status);

-- Project membership table: replaces flat api_keys.project_ids for access control.
CREATE TABLE project_members (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role       VARCHAR(50) NOT NULL DEFAULT 'developer',
    added_by   UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(project_id, user_id),
    CHECK (role IN ('admin', 'developer', 'viewer'))
);

CREATE INDEX idx_project_members_project_id ON project_members (project_id);
CREATE INDEX idx_project_members_user_id ON project_members (user_id);
```

- [ ] **Step 2: Write down migration**

```sql
-- 000033_project_extensions_and_members.down.sql

DROP TABLE IF EXISTS project_members;
DROP INDEX IF EXISTS idx_projects_status;
ALTER TABLE projects DROP COLUMN IF EXISTS archived_by;
ALTER TABLE projects DROP COLUMN IF EXISTS archived_at;
```

- [ ] **Step 3: Verify migration runs**

```bash
cd ennam.kg.go && make db-migrate
make db-migrate-version  # Should show 033
```

- [ ] **Step 4: Commit**

```bash
git add db/migrations/000033_*
git commit -m "feat(db): add project archive columns and project_members table (BA-015)"
```

---

## Task 2: ProjectMember Model

**Files:**
- Create: `internal/models/project_member.go`
- Modify: `internal/models/project.go`

- [ ] **Step 1: Write ProjectMember model**

```go
// internal/models/project_member.go
package models

import "time"

// ProjectMemberRole represents the permission level of a project member.
type ProjectMemberRole string

const (
    ProjectMemberRoleAdmin     ProjectMemberRole = "admin"
    ProjectMemberRoleDeveloper ProjectMemberRole = "developer"
    ProjectMemberRoleViewer    ProjectMemberRole = "viewer"
)

// ValidProjectMemberRoles contains all valid project member role values.
var ValidProjectMemberRoles = []ProjectMemberRole{
    ProjectMemberRoleAdmin,
    ProjectMemberRoleDeveloper,
    ProjectMemberRoleViewer,
}

// IsValid checks whether the project member role is a recognized value.
func (r ProjectMemberRole) IsValid() bool {
    for _, v := range ValidProjectMemberRoles {
        if r == v {
            return true
        }
    }
    return false
}

// CanWrite returns true if the role permits write operations (nodes/edges/sync).
func (r ProjectMemberRole) CanWrite() bool {
    return r == ProjectMemberRoleAdmin || r == ProjectMemberRoleDeveloper
}

// CanManage returns true if the role permits project management (update metadata, manage members).
func (r ProjectMemberRole) CanManage() bool {
    return r == ProjectMemberRoleAdmin
}

// ProjectMember represents a user's membership in a project with a specific role.
type ProjectMember struct {
    ID        string            `json:"id" db:"id"`
    ProjectID string            `json:"project_id" db:"project_id"`
    UserID    string            `json:"user_id" db:"user_id"`
    Role      ProjectMemberRole `json:"role" db:"role"`
    AddedBy   *string           `json:"added_by,omitempty" db:"added_by"`
    CreatedAt time.Time         `json:"created_at" db:"created_at"`
}

// ProjectMemberWithUser includes user details alongside membership info,
// used when listing project members with full user context.
type ProjectMemberWithUser struct {
    ProjectMember
    UserEmail    string `json:"user_email"`
    UserName     string `json:"user_name"`
    UserProvider string `json:"user_provider"`
}
```

- [ ] **Step 2: Extend Project model with archive fields**

Add to `internal/models/project.go`:

```go
// Updated Project struct:
type Project struct {
    ID          string     `json:"id"`
    Name        string     `json:"name"`
    Description string     `json:"description"`
    RepoURL     string     `json:"repo_url"`
    Status      string     `json:"status"`
    CreatedAt   time.Time  `json:"created_at"`
    UpdatedAt   time.Time  `json:"updated_at"`
    ArchivedAt  *time.Time `json:"archived_at,omitempty"`
    ArchivedBy  *string    `json:"archived_by,omitempty"`
}

// IsArchived returns true if the project has been archived.
func (p *Project) IsArchived() bool {
    return p.ArchivedAt != nil
}

// ProjectStats holds aggregate statistics for a project.
type ProjectStats struct {
    ProjectID   string `json:"project_id"`
    NodeCount   int    `json:"node_count"`
    EdgeCount   int    `json:"edge_count"`
    MemberCount int    `json:"member_count"`
    SessionCount int   `json:"session_count"`
}
```

- [ ] **Step 3: Commit**

```bash
git add internal/models/project.go internal/models/project_member.go
git commit -m "feat(models): add ProjectMember model and extend Project with archive fields (BA-015)"
```

---

## Task 3: ProjectMember Store

**Files:**
- Create: `internal/store/project_member.go`
- Create: `internal/store/project_member_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- `TestAdd` — inserts a membership, returns created record
- `TestAdd_DuplicateConflict` — same (project_id, user_id) returns conflict error
- `TestRemove` — deletes membership, returns nil for nonexistent
- `TestChangeRole` — updates role column, returns updated record
- `TestListByProject` — returns all members of a project with user details, ordered by role then name
- `TestListByUser` — returns all projects a user is a member of
- `TestGetMembership` — returns single membership by (project_id, user_id), nil if not found
- `TestCountAdmins` — counts members with role='admin' for a project

- [ ] **Step 2: Implement ProjectMemberStore**

```go
// internal/store/project_member.go
package store

import (
    "context"
    "database/sql"

    "github.com/ennam/ennam-kg/internal/models"
)

// ProjectMemberStore provides data access for project memberships.
type ProjectMemberStore struct {
    db *sql.DB
}

// NewProjectMemberStore creates a new ProjectMemberStore.
func NewProjectMemberStore(db *sql.DB) *ProjectMemberStore {
    return &ProjectMemberStore{db: db}
}

// Add creates a new project membership. Returns conflict error if (project_id, user_id) already exists.
func (s *ProjectMemberStore) Add(ctx context.Context, member *models.ProjectMember) (*models.ProjectMember, error) {
    err := s.db.QueryRowContext(ctx, `
        INSERT INTO project_members (project_id, user_id, role, added_by)
        VALUES ($1, $2, $3, $4)
        RETURNING id, project_id, user_id, role, added_by, created_at
    `, member.ProjectID, member.UserID, member.Role, member.AddedBy).Scan(
        &member.ID, &member.ProjectID, &member.UserID,
        &member.Role, &member.AddedBy, &member.CreatedAt,
    )
    if err != nil {
        return nil, err // caller checks for unique constraint violation
    }
    return member, nil
}

// Remove deletes a project membership by project_id and user_id.
// Returns the number of rows affected (0 if not found).
func (s *ProjectMemberStore) Remove(ctx context.Context, projectID, userID string) (int64, error) {
    result, err := s.db.ExecContext(ctx, `
        DELETE FROM project_members WHERE project_id = $1 AND user_id = $2
    `, projectID, userID)
    if err != nil {
        return 0, err
    }
    return result.RowsAffected()
}

// ChangeRole updates the role of an existing membership.
func (s *ProjectMemberStore) ChangeRole(ctx context.Context, projectID, userID string, newRole models.ProjectMemberRole) (*models.ProjectMember, error) {
    var m models.ProjectMember
    err := s.db.QueryRowContext(ctx, `
        UPDATE project_members SET role = $3
        WHERE project_id = $1 AND user_id = $2
        RETURNING id, project_id, user_id, role, added_by, created_at
    `, projectID, userID, newRole).Scan(
        &m.ID, &m.ProjectID, &m.UserID, &m.Role, &m.AddedBy, &m.CreatedAt,
    )
    if err != nil {
        return nil, err
    }
    return &m, nil
}

// ListByProject returns all members of a project with user details.
func (s *ProjectMemberStore) ListByProject(ctx context.Context, projectID string) ([]models.ProjectMemberWithUser, error) {
    rows, err := s.db.QueryContext(ctx, `
        SELECT pm.id, pm.project_id, pm.user_id, pm.role, pm.added_by, pm.created_at,
               u.email, u.name, u.provider
        FROM project_members pm
        JOIN users u ON u.id = pm.user_id
        WHERE pm.project_id = $1
        ORDER BY
            CASE pm.role WHEN 'admin' THEN 1 WHEN 'developer' THEN 2 WHEN 'viewer' THEN 3 END,
            u.name
    `, projectID)
    if err != nil {
        return nil, err
    }
    defer rows.Close()

    var members []models.ProjectMemberWithUser
    for rows.Next() {
        var m models.ProjectMemberWithUser
        if err := rows.Scan(
            &m.ID, &m.ProjectID, &m.UserID, &m.Role, &m.AddedBy, &m.CreatedAt,
            &m.UserEmail, &m.UserName, &m.UserProvider,
        ); err != nil {
            return nil, err
        }
        members = append(members, m)
    }
    return members, rows.Err()
}

// ListByUser returns all project IDs and roles for a given user.
func (s *ProjectMemberStore) ListByUser(ctx context.Context, userID string) ([]models.ProjectMember, error) {
    rows, err := s.db.QueryContext(ctx, `
        SELECT id, project_id, user_id, role, added_by, created_at
        FROM project_members
        WHERE user_id = $1
        ORDER BY created_at
    `, userID)
    if err != nil {
        return nil, err
    }
    defer rows.Close()

    var members []models.ProjectMember
    for rows.Next() {
        var m models.ProjectMember
        if err := rows.Scan(&m.ID, &m.ProjectID, &m.UserID, &m.Role, &m.AddedBy, &m.CreatedAt); err != nil {
            return nil, err
        }
        members = append(members, m)
    }
    return members, rows.Err()
}

// GetMembership returns a single membership by project_id and user_id.
// Returns sql.ErrNoRows if not found.
func (s *ProjectMemberStore) GetMembership(ctx context.Context, projectID, userID string) (*models.ProjectMember, error) {
    var m models.ProjectMember
    err := s.db.QueryRowContext(ctx, `
        SELECT id, project_id, user_id, role, added_by, created_at
        FROM project_members
        WHERE project_id = $1 AND user_id = $2
    `, projectID, userID).Scan(&m.ID, &m.ProjectID, &m.UserID, &m.Role, &m.AddedBy, &m.CreatedAt)
    if err != nil {
        return nil, err
    }
    return &m, nil
}

// CountAdmins counts members with role='admin' for a project.
func (s *ProjectMemberStore) CountAdmins(ctx context.Context, projectID string) (int, error) {
    var count int
    err := s.db.QueryRowContext(ctx, `
        SELECT COUNT(*) FROM project_members
        WHERE project_id = $1 AND role = 'admin'
    `, projectID).Scan(&count)
    return count, err
}
```

- [ ] **Step 3: Run tests**

```bash
cd ennam.kg.go && go test ./internal/store/ -run TestProjectMember -v
```

- [ ] **Step 4: Commit**

```bash
git add internal/store/project_member.go internal/store/project_member_test.go
git commit -m "feat(store): add ProjectMemberStore with CRUD + membership queries (BA-015)"
```

---

## Task 4: Extend Project Store (Create, Update, Archive, Stats)

**Files:**
- Modify: `internal/store/project.go`
- Create/Modify: `internal/store/project_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- `TestCreate` — inserts new project, returns created record with generated UUID
- `TestCreate_DuplicateName` — returns error on duplicate name
- `TestUpdate` — updates name, description, repo_url; bumps updated_at
- `TestArchive` — sets archived_at + archived_by + status='archived'
- `TestUnarchive` — clears archived_at + archived_by + status='active'
- `TestListForUser` — returns only projects where user is a member (replaces public List)
- `TestGetStats` — returns node/edge/member/session counts for a project

- [ ] **Step 2: Implement new ProjectStore methods**

```go
// Create inserts a new project.
func (s *ProjectStore) Create(ctx context.Context, p *models.Project) (*models.Project, error) {
    err := s.db.QueryRowContext(ctx, `
        INSERT INTO projects (name, description, repo_url, status)
        VALUES ($1, $2, $3, 'active')
        RETURNING id, name, description, repo_url, status, created_at, updated_at
    `, p.Name, p.Description, p.RepoURL).Scan(
        &p.ID, &p.Name, &p.Description, &p.RepoURL, &p.Status, &p.CreatedAt, &p.UpdatedAt,
    )
    if err != nil {
        return nil, err
    }
    return p, nil
}

// Update modifies project metadata (name, description, repo_url).
func (s *ProjectStore) Update(ctx context.Context, id string, name, description, repoURL string) (*models.Project, error) {
    var p models.Project
    err := s.db.QueryRowContext(ctx, `
        UPDATE projects
        SET name = $2, description = $3, repo_url = $4, updated_at = NOW()
        WHERE id = $1
        RETURNING id, name, description, repo_url, status, created_at, updated_at, archived_at, archived_by
    `, id, name, description, repoURL).Scan(
        &p.ID, &p.Name, &p.Description, &p.RepoURL, &p.Status,
        &p.CreatedAt, &p.UpdatedAt, &p.ArchivedAt, &p.ArchivedBy,
    )
    if err != nil {
        return nil, err
    }
    return &p, nil
}

// Archive sets a project's status to 'archived' with timestamp and actor.
func (s *ProjectStore) Archive(ctx context.Context, id, archivedBy string) (*models.Project, error) {
    var p models.Project
    err := s.db.QueryRowContext(ctx, `
        UPDATE projects
        SET status = 'archived', archived_at = NOW(), archived_by = $2, updated_at = NOW()
        WHERE id = $1 AND status = 'active'
        RETURNING id, name, description, repo_url, status, created_at, updated_at, archived_at, archived_by
    `, id, archivedBy).Scan(
        &p.ID, &p.Name, &p.Description, &p.RepoURL, &p.Status,
        &p.CreatedAt, &p.UpdatedAt, &p.ArchivedAt, &p.ArchivedBy,
    )
    if err != nil {
        return nil, err
    }
    return &p, nil
}

// Unarchive restores an archived project to active status.
func (s *ProjectStore) Unarchive(ctx context.Context, id string) (*models.Project, error) {
    var p models.Project
    err := s.db.QueryRowContext(ctx, `
        UPDATE projects
        SET status = 'active', archived_at = NULL, archived_by = NULL, updated_at = NOW()
        WHERE id = $1 AND status = 'archived'
        RETURNING id, name, description, repo_url, status, created_at, updated_at, archived_at, archived_by
    `, id).Scan(
        &p.ID, &p.Name, &p.Description, &p.RepoURL, &p.Status,
        &p.CreatedAt, &p.UpdatedAt, &p.ArchivedAt, &p.ArchivedBy,
    )
    if err != nil {
        return nil, err
    }
    return &p, nil
}

// ListForUser returns projects where the given user is a member, ordered by name.
// If userID is empty, returns all active projects (for global admins).
func (s *ProjectStore) ListForUser(ctx context.Context, userID string) ([]models.Project, error) {
    var query string
    var args []interface{}

    if userID == "" {
        // Global admin: list all active projects.
        query = `SELECT id, name, description, repo_url, status, created_at, updated_at, archived_at, archived_by
                 FROM projects WHERE status = 'active' ORDER BY name`
    } else {
        query = `SELECT p.id, p.name, p.description, p.repo_url, p.status, p.created_at, p.updated_at, p.archived_at, p.archived_by
                 FROM projects p
                 JOIN project_members pm ON pm.project_id = p.id
                 WHERE pm.user_id = $1 AND p.status = 'active'
                 ORDER BY p.name`
        args = append(args, userID)
    }

    rows, err := s.db.QueryContext(ctx, query, args...)
    if err != nil {
        return nil, err
    }
    defer rows.Close()

    var projects []models.Project
    for rows.Next() {
        var p models.Project
        if err := rows.Scan(&p.ID, &p.Name, &p.Description, &p.RepoURL, &p.Status,
            &p.CreatedAt, &p.UpdatedAt, &p.ArchivedAt, &p.ArchivedBy); err != nil {
            return nil, err
        }
        projects = append(projects, p)
    }
    return projects, rows.Err()
}

// GetStats returns aggregate statistics for a project.
func (s *ProjectStore) GetStats(ctx context.Context, projectID string) (*models.ProjectStats, error) {
    stats := &models.ProjectStats{ProjectID: projectID}
    err := s.db.QueryRowContext(ctx, `
        SELECT
            (SELECT COUNT(*) FROM knowledge_nodes WHERE project_id = $1) AS node_count,
            (SELECT COUNT(*) FROM knowledge_edges WHERE project_id = $1) AS edge_count,
            (SELECT COUNT(*) FROM project_members WHERE project_id = $1) AS member_count,
            (SELECT COUNT(*) FROM sessions WHERE project_id = $1) AS session_count
    `, projectID).Scan(&stats.NodeCount, &stats.EdgeCount, &stats.MemberCount, &stats.SessionCount)
    if err != nil {
        return nil, err
    }
    return stats, nil
}
```

- [ ] **Step 3: Update existing List() and GetByID() to scan new columns**

Modify `List()` to scan `archived_at, archived_by` (will be NULL for active projects).
Modify `GetByID()` to scan `archived_at, archived_by`.

- [ ] **Step 4: Run tests**

```bash
cd ennam.kg.go && go test ./internal/store/ -run TestProject -v
```

- [ ] **Step 5: Commit**

```bash
git add internal/store/project.go internal/store/project_test.go
git commit -m "feat(store): extend ProjectStore with Create, Update, Archive, ListForUser, GetStats (BA-015)"
```

---

## Task 5: Project Service (Create + Auto-Membership + API Key Sync)

**Files:**
- Create: `internal/service/project.go`
- Create: `internal/service/project_test.go`

- [ ] **Step 1: Define repository interfaces**

```go
// internal/service/project.go
package service

import (
    "context"
    "database/sql"
    "fmt"
    "log/slog"
    "strings"

    "github.com/ennam/ennam-kg/internal/models"
)

// ProjectRepository defines the data access interface for projects.
type ProjectRepository interface {
    Create(ctx context.Context, p *models.Project) (*models.Project, error)
    GetByID(ctx context.Context, id string) (*models.Project, error)
    Update(ctx context.Context, id string, name, description, repoURL string) (*models.Project, error)
    Archive(ctx context.Context, id, archivedBy string) (*models.Project, error)
    Unarchive(ctx context.Context, id string) (*models.Project, error)
    ListForUser(ctx context.Context, userID string) ([]models.Project, error)
    GetStats(ctx context.Context, projectID string) (*models.ProjectStats, error)
}

// MemberRepository defines the data access interface for project memberships.
type MemberRepository interface {
    Add(ctx context.Context, member *models.ProjectMember) (*models.ProjectMember, error)
    Remove(ctx context.Context, projectID, userID string) (int64, error)
    ChangeRole(ctx context.Context, projectID, userID string, newRole models.ProjectMemberRole) (*models.ProjectMember, error)
    ListByProject(ctx context.Context, projectID string) ([]models.ProjectMemberWithUser, error)
    ListByUser(ctx context.Context, userID string) ([]models.ProjectMember, error)
    GetMembership(ctx context.Context, projectID, userID string) (*models.ProjectMember, error)
    CountAdmins(ctx context.Context, projectID string) (int, error)
}

// APIKeySyncer defines the interface for syncing API key project_ids.
// Implemented by store.APIKeyStore. This keeps API keys backward-compatible
// during the transition from flat project_ids to project_members.
type APIKeySyncer interface {
    AddProjectID(ctx context.Context, userID, projectID string) error
    RemoveProjectID(ctx context.Context, userID, projectID string) error
}
```

- [ ] **Step 2: Write failing tests for ProjectService**

Test cases:
- `TestCreateProject_Success` — creates project + auto-adds creator as admin
- `TestCreateProject_MissingName` — returns validation error
- `TestCreateProject_DuplicateName` — returns conflict error
- `TestUpdateProject_Success` — updates metadata
- `TestUpdateProject_NotAdmin` — returns 403 when caller is developer role
- `TestArchiveProject_Success` — archives + blocks further writes
- `TestArchiveProject_NotGlobalAdmin` — returns 403
- `TestUnarchiveProject_Success` — restores active status
- `TestGetProjectStats` — returns accurate counts

- [ ] **Step 3: Implement ProjectService**

```go
// CreateProjectRequest contains the fields for creating a new project.
type CreateProjectRequest struct {
    Name        string `json:"name"`
    Description string `json:"description"`
    RepoURL     string `json:"repo_url"`
    CreatorID   string `json:"-"` // Injected from auth context, not from request body.
}

// UpdateProjectRequest contains the fields for updating a project.
type UpdateProjectRequest struct {
    Name        *string `json:"name,omitempty"`
    Description *string `json:"description,omitempty"`
    RepoURL     *string `json:"repo_url,omitempty"`
}

// ProjectService provides business logic for project CRUD + archiving.
type ProjectService struct {
    projects ProjectRepository
    members  MemberRepository
    apiKeys  APIKeySyncer // nil if no sync needed
    logger   *slog.Logger
}

func NewProjectService(projects ProjectRepository, members MemberRepository, apiKeys APIKeySyncer, logger *slog.Logger) *ProjectService {
    if logger == nil {
        logger = slog.Default()
    }
    return &ProjectService{projects: projects, members: members, apiKeys: apiKeys, logger: logger}
}

// CreateProject creates a new project and auto-adds the creator as admin member.
// Also syncs the project ID to the creator's API keys for backward compatibility.
func (s *ProjectService) CreateProject(ctx context.Context, req CreateProjectRequest) (*models.Project, error) {
    // Validate.
    name := strings.TrimSpace(req.Name)
    if name == "" {
        return nil, &ValidationError{Field: "name", Message: "name is required"}
    }
    if len(name) > 200 {
        return nil, &ValidationError{Field: "name", Message: "name must be at most 200 characters"}
    }

    // Create project.
    p, err := s.projects.Create(ctx, &models.Project{
        Name:        name,
        Description: strings.TrimSpace(req.Description),
        RepoURL:     strings.TrimSpace(req.RepoURL),
    })
    if err != nil {
        return nil, fmt.Errorf("create project: %w", err)
    }

    // Auto-add creator as admin.
    if req.CreatorID != "" {
        _, addErr := s.members.Add(ctx, &models.ProjectMember{
            ProjectID: p.ID,
            UserID:    req.CreatorID,
            Role:      models.ProjectMemberRoleAdmin,
        })
        if addErr != nil {
            s.logger.Error("failed to auto-add creator as project admin",
                "project_id", p.ID, "user_id", req.CreatorID, "error", addErr)
            // Don't fail project creation — membership can be added manually.
        }

        // Sync to API key project_ids for backward compatibility.
        if s.apiKeys != nil {
            if syncErr := s.apiKeys.AddProjectID(ctx, req.CreatorID, p.ID); syncErr != nil {
                s.logger.Warn("failed to sync project to API key",
                    "project_id", p.ID, "user_id", req.CreatorID, "error", syncErr)
            }
        }
    }

    s.logger.Info("project created",
        "project_id", p.ID, "name", p.Name, "creator", req.CreatorID)

    return p, nil
}

// UpdateProject updates project metadata. Caller must have project admin or global admin role.
func (s *ProjectService) UpdateProject(ctx context.Context, id string, req UpdateProjectRequest, existing *models.Project) (*models.Project, error) {
    name := existing.Name
    if req.Name != nil {
        name = strings.TrimSpace(*req.Name)
        if name == "" {
            return nil, &ValidationError{Field: "name", Message: "name cannot be empty"}
        }
    }
    desc := existing.Description
    if req.Description != nil {
        desc = strings.TrimSpace(*req.Description)
    }
    repoURL := existing.RepoURL
    if req.RepoURL != nil {
        repoURL = strings.TrimSpace(*req.RepoURL)
    }

    return s.projects.Update(ctx, id, name, desc, repoURL)
}

// ArchiveProject archives a project. Only global admins can archive.
func (s *ProjectService) ArchiveProject(ctx context.Context, projectID, archivedByUserID string) (*models.Project, error) {
    p, err := s.projects.Archive(ctx, projectID, archivedByUserID)
    if err != nil {
        if err == sql.ErrNoRows {
            return nil, fmt.Errorf("project not found or already archived")
        }
        return nil, fmt.Errorf("archive project: %w", err)
    }

    s.logger.Info("project archived",
        "project_id", projectID, "archived_by", archivedByUserID)
    return p, nil
}

// UnarchiveProject restores an archived project to active status. Only global admins.
func (s *ProjectService) UnarchiveProject(ctx context.Context, projectID string) (*models.Project, error) {
    p, err := s.projects.Unarchive(ctx, projectID)
    if err != nil {
        if err == sql.ErrNoRows {
            return nil, fmt.Errorf("project not found or not archived")
        }
        return nil, fmt.Errorf("unarchive project: %w", err)
    }

    s.logger.Info("project unarchived", "project_id", projectID)
    return p, nil
}
```

- [ ] **Step 4: Run tests**

```bash
cd ennam.kg.go && go test ./internal/service/ -run TestProject -v
```

- [ ] **Step 5: Commit**

```bash
git add internal/service/project.go internal/service/project_test.go
git commit -m "feat(service): add ProjectService with create, update, archive + auto-membership (BA-015)"
```

---

## Task 6: Membership Service (Add/Remove/Change + Last-Admin Protection)

**Files:**
- Modify: `internal/service/project.go` (add MembershipService methods)
- Modify: `internal/service/project_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- `TestAddMember_Success` — adds member with specified role
- `TestAddMember_DuplicateConflict` — returns conflict error
- `TestAddMember_InvalidRole` — returns validation error
- `TestAddMember_SyncsAPIKey` — verifies API key sync called
- `TestRemoveMember_Success` — removes membership
- `TestRemoveMember_LastAdmin` — returns error when trying to remove last admin
- `TestRemoveMember_SyncsAPIKey` — verifies API key sync on removal
- `TestChangeRole_Success` — changes role
- `TestChangeRole_LastAdmin_Demote` — prevents demoting last admin to developer/viewer
- `TestListMembers` — returns members with user details

- [ ] **Step 2: Implement MembershipService on ProjectService**

```go
// AddMemberRequest contains the fields for adding a project member.
type AddMemberRequest struct {
    ProjectID string                   `json:"project_id"`
    UserID    string                   `json:"user_id"`
    Role      models.ProjectMemberRole `json:"role"`
    AddedBy   string                   `json:"-"` // from auth context
}

// ChangeRoleRequest contains the fields for changing a member's role.
type ChangeRoleRequest struct {
    ProjectID string                   `json:"project_id"`
    UserID    string                   `json:"user_id"`
    NewRole   models.ProjectMemberRole `json:"role"`
}

// AddMember adds a user to a project with the specified role.
// Syncs the project to the user's API keys for backward compatibility.
func (s *ProjectService) AddMember(ctx context.Context, req AddMemberRequest) (*models.ProjectMember, error) {
    if !req.Role.IsValid() {
        return nil, &ValidationError{
            Field:   "role",
            Message: fmt.Sprintf("invalid role %q: must be admin, developer, or viewer", req.Role),
        }
    }

    member, err := s.members.Add(ctx, &models.ProjectMember{
        ProjectID: req.ProjectID,
        UserID:    req.UserID,
        Role:      req.Role,
        AddedBy:   &req.AddedBy,
    })
    if err != nil {
        return nil, fmt.Errorf("add member: %w", err)
    }

    // Sync to API key.
    if s.apiKeys != nil {
        if syncErr := s.apiKeys.AddProjectID(ctx, req.UserID, req.ProjectID); syncErr != nil {
            s.logger.Warn("failed to sync project to API key on add",
                "project_id", req.ProjectID, "user_id", req.UserID, "error", syncErr)
        }
    }

    s.logger.Info("member added",
        "project_id", req.ProjectID, "user_id", req.UserID, "role", req.Role)
    return member, nil
}

// RemoveMember removes a user from a project.
// Prevents removal of the last admin. Syncs API key removal.
func (s *ProjectService) RemoveMember(ctx context.Context, projectID, userID string) error {
    // Check if this is the last admin.
    membership, err := s.members.GetMembership(ctx, projectID, userID)
    if err != nil {
        return fmt.Errorf("get membership: %w", err)
    }
    if membership == nil {
        return fmt.Errorf("membership not found")
    }

    if membership.Role == models.ProjectMemberRoleAdmin {
        adminCount, countErr := s.members.CountAdmins(ctx, projectID)
        if countErr != nil {
            return fmt.Errorf("count admins: %w", countErr)
        }
        if adminCount <= 1 {
            return &LastAdminError{ProjectID: projectID, UserID: userID}
        }
    }

    _, err = s.members.Remove(ctx, projectID, userID)
    if err != nil {
        return fmt.Errorf("remove member: %w", err)
    }

    // Sync API key removal.
    if s.apiKeys != nil {
        if syncErr := s.apiKeys.RemoveProjectID(ctx, userID, projectID); syncErr != nil {
            s.logger.Warn("failed to sync project removal from API key",
                "project_id", projectID, "user_id", userID, "error", syncErr)
        }
    }

    s.logger.Info("member removed", "project_id", projectID, "user_id", userID)
    return nil
}

// ChangeRole changes a member's role within a project.
// Prevents demoting the last admin.
func (s *ProjectService) ChangeRole(ctx context.Context, req ChangeRoleRequest) (*models.ProjectMember, error) {
    if !req.NewRole.IsValid() {
        return nil, &ValidationError{
            Field:   "role",
            Message: fmt.Sprintf("invalid role %q: must be admin, developer, or viewer", req.NewRole),
        }
    }

    // If demoting from admin, check last-admin guard.
    existing, err := s.members.GetMembership(ctx, req.ProjectID, req.UserID)
    if err != nil {
        return nil, fmt.Errorf("get membership: %w", err)
    }
    if existing == nil {
        return nil, fmt.Errorf("membership not found")
    }

    if existing.Role == models.ProjectMemberRoleAdmin && req.NewRole != models.ProjectMemberRoleAdmin {
        adminCount, countErr := s.members.CountAdmins(ctx, req.ProjectID)
        if countErr != nil {
            return nil, fmt.Errorf("count admins: %w", countErr)
        }
        if adminCount <= 1 {
            return nil, &LastAdminError{ProjectID: req.ProjectID, UserID: req.UserID}
        }
    }

    updated, err := s.members.ChangeRole(ctx, req.ProjectID, req.UserID, req.NewRole)
    if err != nil {
        return nil, fmt.Errorf("change role: %w", err)
    }

    s.logger.Info("member role changed",
        "project_id", req.ProjectID, "user_id", req.UserID,
        "old_role", existing.Role, "new_role", req.NewRole)
    return updated, nil
}

// ListMembers returns all members of a project with user details.
func (s *ProjectService) ListMembers(ctx context.Context, projectID string) ([]models.ProjectMemberWithUser, error) {
    members, err := s.members.ListByProject(ctx, projectID)
    if err != nil {
        return nil, fmt.Errorf("list members: %w", err)
    }
    if members == nil {
        members = []models.ProjectMemberWithUser{}
    }
    return members, nil
}

// --- Error Types ---

// LastAdminError indicates that an operation was rejected because it would
// remove or demote the last admin of a project.
type LastAdminError struct {
    ProjectID string `json:"project_id"`
    UserID    string `json:"user_id"`
}

func (e *LastAdminError) Error() string {
    return fmt.Sprintf("cannot remove or demote the last admin of project %s (user %s)", e.ProjectID, e.UserID)
}
```

- [ ] **Step 3: Run tests**

```bash
cd ennam.kg.go && go test ./internal/service/ -run TestMember -v
```

- [ ] **Step 4: Commit**

```bash
git add internal/service/project.go internal/service/project_test.go
git commit -m "feat(service): add membership management with last-admin protection and API key sync (BA-015)"
```

---

## Task 7: Project Handler Expansion (5 New + 2 Modified Endpoints)

**Files:**
- Modify: `internal/handler/project.go`
- Create/Modify: `internal/handler/project_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- `TestHandleCreateProject` — POST /projects creates project, returns 201
- `TestHandleCreateProject_MissingName` — returns 400
- `TestHandleUpdateProject` — PUT /projects/{id} updates metadata, returns 200
- `TestHandleUpdateProject_NotAdmin` — returns 403 for non-admin callers
- `TestHandleArchiveProject` — POST /projects/{id}/archive, returns 200
- `TestHandleArchiveProject_NotGlobalAdmin` — returns 403
- `TestHandleUnarchiveProject` — POST /projects/{id}/unarchive, returns 200
- `TestHandleGetProjectStats` — GET /projects/{id}/stats, returns stats JSON
- `TestHandleListProjects_Filtered` — GET /projects returns only user's projects
- `TestHandleGetProject_AccessCheck` — returns 403 if user is not a member

- [ ] **Step 2: Update ProjectHandler to accept service layer**

```go
// Updated ProjectHandler with service dependency.
type ProjectHandler struct {
    service *service.ProjectService
    store   *store.ProjectStore
    logger  *slog.Logger
}

func NewProjectHandler(svc *service.ProjectService, s *store.ProjectStore, logger *slog.Logger) *ProjectHandler {
    return &ProjectHandler{service: svc, store: s, logger: logger}
}
```

- [ ] **Step 3: Implement new endpoints**

```go
// HandleCreateProject handles POST /api/v1/projects.
func (h *ProjectHandler) HandleCreateProject(w http.ResponseWriter, r *http.Request) {
    identity := middleware.GetDeveloperIdentity(r.Context())
    if identity == nil {
        errorResponse(w, http.StatusUnauthorized, "authentication required")
        return
    }

    var req service.CreateProjectRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        errorResponse(w, http.StatusBadRequest, "invalid request body")
        return
    }
    req.CreatorID = identity.UserID // Set from auth context.

    project, err := h.service.CreateProject(r.Context(), req)
    if err != nil {
        // Map service errors to HTTP status codes.
        switch err.(type) {
        case *service.ValidationError:
            errorResponse(w, http.StatusBadRequest, err.Error())
        default:
            h.logger.ErrorContext(r.Context(), "create project failed", "error", err)
            errorResponse(w, http.StatusInternalServerError, "failed to create project")
        }
        return
    }

    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusCreated)
    _ = json.NewEncoder(w).Encode(project)
}

// HandleUpdateProject handles PUT /api/v1/projects/{id}.
func (h *ProjectHandler) HandleUpdateProject(w http.ResponseWriter, r *http.Request) {
    // Requires project admin or global admin — checked via context role.
    projectID := r.PathValue("id")

    existing, err := h.store.GetByID(r.Context(), projectID)
    if err != nil {
        errorResponse(w, http.StatusNotFound, "project not found")
        return
    }

    var req service.UpdateProjectRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        errorResponse(w, http.StatusBadRequest, "invalid request body")
        return
    }

    project, err := h.service.UpdateProject(r.Context(), projectID, req, existing)
    if err != nil {
        h.logger.ErrorContext(r.Context(), "update project failed", "error", err)
        errorResponse(w, http.StatusInternalServerError, "failed to update project")
        return
    }

    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusOK)
    _ = json.NewEncoder(w).Encode(project)
}

// HandleArchiveProject handles POST /api/v1/projects/{id}/archive.
func (h *ProjectHandler) HandleArchiveProject(w http.ResponseWriter, r *http.Request) {
    identity := middleware.GetDeveloperIdentity(r.Context())
    if identity == nil || identity.Role != models.APIKeyRoleAdmin {
        errorResponse(w, http.StatusForbidden, "only global admins can archive projects")
        return
    }

    projectID := r.PathValue("id")
    project, err := h.service.ArchiveProject(r.Context(), projectID, identity.UserID)
    if err != nil {
        h.logger.ErrorContext(r.Context(), "archive project failed", "error", err)
        errorResponse(w, http.StatusInternalServerError, "failed to archive project")
        return
    }

    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusOK)
    _ = json.NewEncoder(w).Encode(project)
}

// HandleUnarchiveProject handles POST /api/v1/projects/{id}/unarchive.
func (h *ProjectHandler) HandleUnarchiveProject(w http.ResponseWriter, r *http.Request) {
    identity := middleware.GetDeveloperIdentity(r.Context())
    if identity == nil || identity.Role != models.APIKeyRoleAdmin {
        errorResponse(w, http.StatusForbidden, "only global admins can unarchive projects")
        return
    }

    projectID := r.PathValue("id")
    project, err := h.service.UnarchiveProject(r.Context(), projectID)
    if err != nil {
        h.logger.ErrorContext(r.Context(), "unarchive project failed", "error", err)
        errorResponse(w, http.StatusInternalServerError, "failed to unarchive project")
        return
    }

    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusOK)
    _ = json.NewEncoder(w).Encode(project)
}

// HandleGetProjectStats handles GET /api/v1/projects/{id}/stats.
func (h *ProjectHandler) HandleGetProjectStats(w http.ResponseWriter, r *http.Request) {
    projectID := r.PathValue("id")
    stats, err := h.store.GetStats(r.Context(), projectID)
    if err != nil {
        h.logger.ErrorContext(r.Context(), "get project stats failed", "error", err)
        errorResponse(w, http.StatusInternalServerError, "failed to get project stats")
        return
    }

    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusOK)
    _ = json.NewEncoder(w).Encode(stats)
}
```

- [ ] **Step 4: Modify HandleListProjects to filter by membership**

```go
// HandleListProjects handles GET /api/v1/projects.
// Now returns only projects where the authenticated user is a member.
// Global admins see all active projects.
func (h *ProjectHandler) HandleListProjects(w http.ResponseWriter, r *http.Request) {
    identity := middleware.GetDeveloperIdentity(r.Context())

    var userID string
    if identity != nil && identity.Role != models.APIKeyRoleAdmin {
        userID = identity.UserID // Non-admin: filter by membership.
    }
    // Admin with empty userID: ListForUser returns all active.

    projects, err := h.store.ListForUser(r.Context(), userID)
    if err != nil {
        h.logger.ErrorContext(r.Context(), "list projects failed", "error", err)
        errorResponse(w, http.StatusInternalServerError, "failed to list projects")
        return
    }
    if projects == nil {
        projects = []models.Project{}
    }

    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusOK)
    _ = json.NewEncoder(w).Encode(map[string]interface{}{"projects": projects})
}
```

- [ ] **Step 5: Update RegisterRoutes with new endpoints**

```go
func (h *ProjectHandler) RegisterRoutes(mux *http.ServeMux) {
    mux.HandleFunc("GET /api/v1/projects", h.HandleListProjects)
    mux.HandleFunc("POST /api/v1/projects", h.HandleCreateProject)
    mux.HandleFunc("GET /api/v1/projects/{id}", h.HandleGetProject)
    mux.HandleFunc("PUT /api/v1/projects/{id}", h.HandleUpdateProject)
    mux.HandleFunc("POST /api/v1/projects/{id}/archive", h.HandleArchiveProject)
    mux.HandleFunc("POST /api/v1/projects/{id}/unarchive", h.HandleUnarchiveProject)
    mux.HandleFunc("GET /api/v1/projects/{id}/stats", h.HandleGetProjectStats)
}
```

- [ ] **Step 6: Run tests**

```bash
cd ennam.kg.go && go test ./internal/handler/ -run TestProject -v
```

- [ ] **Step 7: Commit**

```bash
git add internal/handler/project.go internal/handler/project_test.go
git commit -m "feat(handler): add project CRUD, archive/unarchive, stats endpoints (BA-015)"
```

---

## Task 8: Member Handler (4 Endpoints)

**Files:**
- Create: `internal/handler/project_member.go`
- Create: `internal/handler/project_member_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- `TestHandleListMembers` — GET /projects/{id}/members returns member list with user details
- `TestHandleAddMember` — POST /projects/{id}/members adds member, returns 201
- `TestHandleAddMember_InvalidRole` — returns 400
- `TestHandleAddMember_Duplicate` — returns 409
- `TestHandleRemoveMember` — DELETE /projects/{id}/members/{user_id} removes member, returns 204
- `TestHandleRemoveMember_LastAdmin` — returns 409
- `TestHandleChangeRole` — PATCH /projects/{id}/members/{user_id} changes role, returns 200
- `TestHandleChangeRole_LastAdminDemotion` — returns 409

- [ ] **Step 2: Implement ProjectMemberHandler**

```go
// internal/handler/project_member.go
package handler

import (
    "encoding/json"
    "log/slog"
    "net/http"

    "github.com/ennam/ennam-kg/internal/middleware"
    "github.com/ennam/ennam-kg/internal/models"
    "github.com/ennam/ennam-kg/internal/service"
)

// ProjectMemberHandler handles project membership REST API requests.
type ProjectMemberHandler struct {
    service *service.ProjectService
    logger  *slog.Logger
}

// NewProjectMemberHandler creates a new ProjectMemberHandler.
func NewProjectMemberHandler(svc *service.ProjectService, logger *slog.Logger) *ProjectMemberHandler {
    return &ProjectMemberHandler{service: svc, logger: logger}
}

// HandleListMembers handles GET /api/v1/projects/{id}/members.
func (h *ProjectMemberHandler) HandleListMembers(w http.ResponseWriter, r *http.Request) {
    projectID := r.PathValue("id")
    members, err := h.service.ListMembers(r.Context(), projectID)
    if err != nil {
        h.logger.ErrorContext(r.Context(), "list members failed", "error", err)
        errorResponse(w, http.StatusInternalServerError, "failed to list members")
        return
    }

    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusOK)
    _ = json.NewEncoder(w).Encode(map[string]interface{}{
        "members": members,
        "total":   len(members),
    })
}

// HandleAddMember handles POST /api/v1/projects/{id}/members.
func (h *ProjectMemberHandler) HandleAddMember(w http.ResponseWriter, r *http.Request) {
    identity := middleware.GetDeveloperIdentity(r.Context())
    if identity == nil {
        errorResponse(w, http.StatusUnauthorized, "authentication required")
        return
    }

    projectID := r.PathValue("id")

    var body struct {
        UserID string                   `json:"user_id"`
        Role   models.ProjectMemberRole `json:"role"`
    }
    if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
        errorResponse(w, http.StatusBadRequest, "invalid request body")
        return
    }

    member, err := h.service.AddMember(r.Context(), service.AddMemberRequest{
        ProjectID: projectID,
        UserID:    body.UserID,
        Role:      body.Role,
        AddedBy:   identity.UserID,
    })
    if err != nil {
        switch err.(type) {
        case *service.ValidationError:
            errorResponse(w, http.StatusBadRequest, err.Error())
        default:
            // Check for unique constraint violation (duplicate).
            if isDuplicateKeyError(err) {
                errorResponse(w, http.StatusConflict, "user is already a member of this project")
                return
            }
            h.logger.ErrorContext(r.Context(), "add member failed", "error", err)
            errorResponse(w, http.StatusInternalServerError, "failed to add member")
        }
        return
    }

    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusCreated)
    _ = json.NewEncoder(w).Encode(member)
}

// HandleRemoveMember handles DELETE /api/v1/projects/{id}/members/{user_id}.
func (h *ProjectMemberHandler) HandleRemoveMember(w http.ResponseWriter, r *http.Request) {
    projectID := r.PathValue("id")
    userID := r.PathValue("user_id")

    err := h.service.RemoveMember(r.Context(), projectID, userID)
    if err != nil {
        switch err.(type) {
        case *service.LastAdminError:
            errorResponse(w, http.StatusConflict, err.Error())
        default:
            h.logger.ErrorContext(r.Context(), "remove member failed", "error", err)
            errorResponse(w, http.StatusInternalServerError, "failed to remove member")
        }
        return
    }

    w.WriteHeader(http.StatusNoContent)
}

// HandleChangeRole handles PATCH /api/v1/projects/{id}/members/{user_id}.
func (h *ProjectMemberHandler) HandleChangeRole(w http.ResponseWriter, r *http.Request) {
    projectID := r.PathValue("id")
    userID := r.PathValue("user_id")

    var body struct {
        Role models.ProjectMemberRole `json:"role"`
    }
    if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
        errorResponse(w, http.StatusBadRequest, "invalid request body")
        return
    }

    member, err := h.service.ChangeRole(r.Context(), service.ChangeRoleRequest{
        ProjectID: projectID,
        UserID:    userID,
        NewRole:   body.Role,
    })
    if err != nil {
        switch err.(type) {
        case *service.ValidationError:
            errorResponse(w, http.StatusBadRequest, err.Error())
        case *service.LastAdminError:
            errorResponse(w, http.StatusConflict, err.Error())
        default:
            h.logger.ErrorContext(r.Context(), "change role failed", "error", err)
            errorResponse(w, http.StatusInternalServerError, "failed to change role")
        }
        return
    }

    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusOK)
    _ = json.NewEncoder(w).Encode(member)
}

// RegisterRoutes registers project member handler routes.
func (h *ProjectMemberHandler) RegisterRoutes(mux *http.ServeMux) {
    mux.HandleFunc("GET /api/v1/projects/{id}/members", h.HandleListMembers)
    mux.HandleFunc("POST /api/v1/projects/{id}/members", h.HandleAddMember)
    mux.HandleFunc("DELETE /api/v1/projects/{id}/members/{user_id}", h.HandleRemoveMember)
    mux.HandleFunc("PATCH /api/v1/projects/{id}/members/{user_id}", h.HandleChangeRole)
}

// isDuplicateKeyError checks if a database error is a unique constraint violation.
func isDuplicateKeyError(err error) bool {
    if err == nil {
        return false
    }
    return strings.Contains(err.Error(), "duplicate key") ||
        strings.Contains(err.Error(), "unique constraint")
}
```

- [ ] **Step 3: Run tests**

```bash
cd ennam.kg.go && go test ./internal/handler/ -run TestProjectMember -v
```

- [ ] **Step 4: Commit**

```bash
git add internal/handler/project_member.go internal/handler/project_member_test.go
git commit -m "feat(handler): add project member CRUD endpoints (BA-015)"
```

---

## Task 9: Wire ProjectID Middleware + Membership Check + Archive Block

**Files:**
- Modify: `internal/middleware/project.go`
- Modify: `internal/middleware/auth.go`
- Modify: `cmd/kg-server/main.go`

This is the most critical task — it connects the access control system.

- [ ] **Step 1: Add context keys for project role and archive status**

Add to `internal/middleware/project.go`:

```go
const (
    EffectiveProjectIDKey   contextKey = "effective_project_id"
    ProjectMemberRoleKey    contextKey = "project_member_role"
    ProjectArchivedKey      contextKey = "project_archived"
)

// GetProjectMemberRole extracts the project member role from context.
func GetProjectMemberRole(ctx context.Context) (models.ProjectMemberRole, bool) {
    if role, ok := ctx.Value(ProjectMemberRoleKey).(models.ProjectMemberRole); ok {
        return role, true
    }
    return "", false
}

// IsProjectArchived checks if the current project is archived.
func IsProjectArchived(ctx context.Context) bool {
    if archived, ok := ctx.Value(ProjectArchivedKey).(bool); ok {
        return archived
    }
    return false
}
```

- [ ] **Step 2: Add MembershipChecker interface to middleware**

```go
// MembershipChecker resolves project membership for a user.
// Implemented by store.ProjectMemberStore.
type MembershipChecker interface {
    GetMembership(ctx context.Context, projectID, userID string) (*models.ProjectMember, error)
}

// ProjectChecker resolves project archive status.
type ProjectChecker interface {
    GetByID(ctx context.Context, id string) (*models.Project, error)
}
```

- [ ] **Step 3: Update ProjectID middleware to inject role + archive status**

Update the `ProjectID` middleware function signature to accept `MembershipChecker` and `ProjectChecker`:

```go
func ProjectID(logger *slog.Logger, memberChecker MembershipChecker, projectChecker ProjectChecker) func(http.Handler) http.Handler {
    // ... existing resolution logic ...
    // After resolving effectiveID, look up membership:
    //   membership := memberChecker.GetMembership(ctx, effectiveID, identity.UserID)
    //   if membership != nil:
    //     inject ProjectMemberRoleKey into context
    //   else if identity.Role != admin:
    //     403 access denied
    //
    // Look up project archive status:
    //   project := projectChecker.GetByID(ctx, effectiveID)
    //   if project.IsArchived():
    //     inject ProjectArchivedKey = true
}
```

- [ ] **Step 4: Add archive write-block middleware**

```go
// ArchiveWriteBlock returns middleware that rejects write requests to archived projects.
// Must be applied AFTER ProjectID middleware.
func ArchiveWriteBlock(logger *slog.Logger) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            // Only block mutating methods.
            if r.Method == http.MethodGet || r.Method == http.MethodHead || r.Method == http.MethodOptions {
                next.ServeHTTP(w, r)
                return
            }

            if IsProjectArchived(r.Context()) {
                writeProjectError(w, http.StatusForbidden,
                    "project is archived",
                    "Write operations are not permitted on archived projects. Unarchive the project first.",
                    "",
                )
                return
            }

            next.ServeHTTP(w, r)
        })
    }
}
```

- [ ] **Step 5: Add UserID field to DeveloperIdentity**

In `internal/middleware/auth.go`, add `UserID string` to `DeveloperIdentity` struct. This is populated from the `users` table via the API key's developer mapping (introduced by BA-014).

```go
type DeveloperIdentity struct {
    KeyID                string
    DeveloperName        string
    Role                 models.APIKeyRole
    ProjectIDs           []string
    DefaultProjectID     *string
    AllowProjectOverride bool
    KeyPrefix            string
    UserID               string // NEW: links to users.id for membership checks
}
```

- [ ] **Step 6: Wire ProjectID middleware into buildRouter**

Update `cmd/kg-server/main.go` `buildRouter()`:

```go
// After creating stores:
memberStore := store.NewProjectMemberStore(db)

// Apply middleware chain to API routes:
// Auth -> ProjectID (with membership checker) -> ArchiveWriteBlock -> apiMux
protectedHandler := middleware.Auth(auth, logger)(
    middleware.ProjectID(logger, memberStore, projectStore)(
        middleware.ArchiveWriteBlock(logger)(apiMux),
    ),
)

// Wire new handlers:
projectSvc := service.NewProjectService(projectStore, memberStore, nil, logger)
projectHandler := handler.NewProjectHandler(projectSvc, projectStore, logger)
projectHandler.RegisterRoutes(apiMux)

memberHandler := handler.NewProjectMemberHandler(projectSvc, logger)
memberHandler.RegisterRoutes(apiMux)
```

- [ ] **Step 7: Run full test suite**

```bash
cd ennam.kg.go && make test
```

- [ ] **Step 8: Commit**

```bash
git add internal/middleware/project.go internal/middleware/auth.go cmd/kg-server/main.go
git commit -m "feat(middleware): wire ProjectID middleware with membership check and archive write-block (BA-015)"
```

---

## Task 10: Integration Verification

- [ ] **Step 1: Run full test suite with race detection**

```bash
cd ennam.kg.go && make test
```

- [ ] **Step 2: Verify migration up/down cycle**

```bash
cd ennam.kg.go && make db-migrate
make db-migrate-down
make db-migrate
```

- [ ] **Step 3: Smoke test endpoints with curl**

```bash
# Create project
curl -X POST http://localhost:8080/api/v1/projects \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"test-project","description":"smoke test"}'

# List projects (should be filtered)
curl http://localhost:8080/api/v1/projects \
  -H "Authorization: Bearer $API_KEY"

# Add member
curl -X POST http://localhost:8080/api/v1/projects/{id}/members \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"...","role":"developer"}'

# List members
curl http://localhost:8080/api/v1/projects/{id}/members \
  -H "Authorization: Bearer $API_KEY"

# Get stats
curl http://localhost:8080/api/v1/projects/{id}/stats \
  -H "Authorization: Bearer $API_KEY"

# Archive (admin only)
curl -X POST http://localhost:8080/api/v1/projects/{id}/archive \
  -H "Authorization: Bearer $ADMIN_KEY"

# Verify write blocked on archived project
curl -X POST http://localhost:8080/api/v1/nodes \
  -H "Authorization: Bearer $API_KEY" \
  -H "X-Project-ID: {id}" \
  -d '...'  # Expect 403
```

- [ ] **Step 4: Run lint**

```bash
cd ennam.kg.go && make lint
```

- [ ] **Step 5: Final commit (if any fixes)**

```bash
git add -A
git commit -m "fix: integration fixes for BA-015 project management (BA-015)"
```

---

## Endpoint Summary

### New Endpoints (11 total)

| Method | Path | Handler | Auth |
|--------|------|---------|------|
| `POST` | `/api/v1/projects` | `HandleCreateProject` | Any authenticated |
| `PUT` | `/api/v1/projects/{id}` | `HandleUpdateProject` | Project Admin / Global Admin |
| `POST` | `/api/v1/projects/{id}/archive` | `HandleArchiveProject` | Global Admin |
| `POST` | `/api/v1/projects/{id}/unarchive` | `HandleUnarchiveProject` | Global Admin |
| `GET` | `/api/v1/projects/{id}/stats` | `HandleGetProjectStats` | Any member |
| `GET` | `/api/v1/projects/{id}/members` | `HandleListMembers` | Any member |
| `POST` | `/api/v1/projects/{id}/members` | `HandleAddMember` | Project Admin / Global Admin |
| `DELETE` | `/api/v1/projects/{id}/members/{user_id}` | `HandleRemoveMember` | Project Admin / Global Admin |
| `PATCH` | `/api/v1/projects/{id}/members/{user_id}` | `HandleChangeRole` | Project Admin / Global Admin |

### Modified Endpoints (2)

| Method | Path | Change |
|--------|------|--------|
| `GET` | `/api/v1/projects` | Filtered by user membership (was: all active) |
| `GET` | `/api/v1/projects/{id}` | Access check via membership (was: open) |

---

## Task Summary

| # | Task | Type | Effort | Files |
|---|------|------|--------|-------|
| 1 | Migration 033 | New tables | Small | 2 |
| 2 | ProjectMember model | New model + extend existing | Small | 2 |
| 3 | ProjectMember store | New store + tests | Medium | 2 |
| 4 | Extend Project store | Extend existing + tests | Medium | 2 |
| 5 | Project service | New service + tests | Large | 2 |
| 6 | Membership service | Extend service + tests | Large | 2 |
| 7 | Project handler expansion | Extend + tests | Large | 2 |
| 8 | Member handler | New handler + tests | Medium | 2 |
| 9 | Middleware wiring | Modify 3 files | Large | 3 |
| 10 | Integration verification | Testing only | Small | 0 |
| **Total** | **10 tasks** | **~19 files** | | |

### Dependency Graph

```
Task 1 (migration)
  └─→ Task 2 (model)
       ├─→ Task 3 (member store)
       └─→ Task 4 (project store)
            ├─→ Task 5 (project service)
            │    └─→ Task 6 (membership service)
            │         ├─→ Task 7 (project handler)
            │         └─→ Task 8 (member handler)
            └─────────────→ Task 9 (middleware wiring)
                                └─→ Task 10 (integration)
```

Tasks 3 and 4 can run in parallel after Task 2.
Tasks 7 and 8 can run in parallel after Task 6.
Task 9 depends on Tasks 7, 8 (handlers must exist to wire).
Task 10 is the final serial verification.
