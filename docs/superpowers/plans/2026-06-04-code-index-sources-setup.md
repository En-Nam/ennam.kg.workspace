# Code Index Sources Setup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the broken `repo_path`/`repo_url` naming bug, add multi-repo support per project, and expose a "Code Sources" UI in Settings with per-path "Index Now" buttons.

**Architecture:** Add `repo_paths TEXT[]` to the `projects` table; wire it through Go model → store → service → new `POST /api/v1/projects/{id}/index` endpoint that publishes `index_project` queue messages. NextJS Settings page gains a dynamic source-list component with Index triggers. Python adds `POST /index/batch` for direct HTTP callers.

**Tech Stack:** Go (stdlib net/http, lib/pq, database/sql), Python (FastAPI), TypeScript/NextJS 16, PostgreSQL 16, Redis queue

---

## Files

| Action | Path |
|--------|------|
| Create | `ennam.kg.go/db/migrations/000056_add_repo_paths.up.sql` |
| Create | `ennam.kg.go/db/migrations/000056_add_repo_paths.down.sql` |
| Modify | `ennam.kg.go/internal/models/project.go` |
| Modify | `ennam.kg.go/internal/store/project.go` |
| Modify | `ennam.kg.go/internal/service/project.go` |
| Modify | `ennam.kg.go/internal/service/project_test.go` |
| Modify | `ennam.kg.go/internal/handler/project.go` |
| Modify | `ennam.kg.go/cmd/kg-server/main.go` |
| Modify | `ennam.kg.python/src/ennam_kg/api/indexing.py` |
| Modify | `ennam.kg.next/src/types/project.ts` |
| Modify | `ennam.kg.next/src/hooks/use-projects.ts` |
| Modify | `ennam.kg.next/src/app/(dashboard)/settings/page.tsx` |

---

### Task 1: DB Migration — add `repo_paths TEXT[]`

**Files:**
- Create: `ennam.kg.go/db/migrations/000056_add_repo_paths.up.sql`
- Create: `ennam.kg.go/db/migrations/000056_add_repo_paths.down.sql`

- [ ] **Step 1: Write the up migration**

```sql
-- 000056_add_repo_paths.up.sql
ALTER TABLE projects
    ADD COLUMN repo_paths TEXT[] NOT NULL DEFAULT '{}';

-- Backfill: migrate non-empty repo_url into the new array.
UPDATE projects
    SET repo_paths = ARRAY[repo_url]
    WHERE repo_url <> '';
```

- [ ] **Step 2: Write the down migration**

```sql
-- 000056_add_repo_paths.down.sql
ALTER TABLE projects DROP COLUMN repo_paths;
```

- [ ] **Step 3: Run migration**

```bash
cd ennam.kg.go
make db-migrate
# Expected: "migrate: 1 up" or similar — no error
make db-migrate-version
# Expected: current version = 56
```

- [ ] **Step 4: Verify column exists**

```bash
make db-shell
# In psql:
\d projects
# Expected: repo_paths text[] column present
\q
```

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add db/migrations/000056_add_repo_paths.up.sql db/migrations/000056_add_repo_paths.down.sql
git commit -m "feat: add repo_paths column to projects table"
```

---

### Task 2: Go Model + Store — expose `repo_paths`

**Files:**
- Modify: `ennam.kg.go/internal/models/project.go`
- Modify: `ennam.kg.go/internal/store/project.go`

- [ ] **Step 1: Add `RepoPaths` field to Project model**

In `ennam.kg.go/internal/models/project.go`, add the new field after `RepoURL`:

```go
// Project represents a knowledge graph project.
type Project struct {
	ID          string     `json:"id"`
	Name        string     `json:"name"`
	Description string     `json:"description"`
	RepoURL     string     `json:"repo_url"`
	RepoPaths   []string   `json:"repo_paths"`
	Status      string     `json:"status"`
	CreatedAt   time.Time  `json:"created_at"`
	UpdatedAt   time.Time  `json:"updated_at"`
	ArchivedAt  *time.Time `json:"archived_at,omitempty"`
	ArchivedBy  *string    `json:"archived_by,omitempty"`
}
```

- [ ] **Step 2: Update `store/project.go` — add `repo_paths` to every SELECT, RETURNING, INSERT, and Scan**

Replace the entire file content. Key changes:
- Every `SELECT`/`RETURNING` clause gains `, repo_paths` after `repo_url`
- Every `.Scan(...)` gains `pq.Array(&p.RepoPaths)` after `&p.RepoURL`
- `Create` gains `repo_paths = $4` parameter
- `Update` gains `repo_paths = $5` parameter and new `repoPaths []string` argument
- Interface signature of `Update` changes (updated in Task 3)

```go
package store

import (
	"context"
	"database/sql"

	"github.com/ennam/ennam-kg/internal/models"
	"github.com/lib/pq"
)

// ProjectStore provides data access for projects.
type ProjectStore struct {
	db *sql.DB
}

// NewProjectStore creates a new ProjectStore.
func NewProjectStore(db *sql.DB) *ProjectStore {
	return &ProjectStore{db: db}
}

// List returns projects ordered by name.
func (s *ProjectStore) List(ctx context.Context, includeArchived bool) ([]models.Project, error) {
	query := `
		SELECT id, name, description, repo_url, repo_paths, status, created_at, updated_at, archived_at, archived_by
		FROM projects`
	if !includeArchived {
		query += `
		WHERE status = 'active'`
	}
	query += `
		ORDER BY name`
	rows, err := s.db.QueryContext(ctx, query)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var projects []models.Project
	for rows.Next() {
		var p models.Project
		if err := rows.Scan(&p.ID, &p.Name, &p.Description, &p.RepoURL, pq.Array(&p.RepoPaths), &p.Status,
			&p.CreatedAt, &p.UpdatedAt, &p.ArchivedAt, &p.ArchivedBy); err != nil {
			return nil, err
		}
		projects = append(projects, p)
	}
	return projects, rows.Err()
}

// GetByID returns a single project by its UUID.
func (s *ProjectStore) GetByID(ctx context.Context, id string) (*models.Project, error) {
	var p models.Project
	err := s.db.QueryRowContext(ctx, `
		SELECT id, name, description, repo_url, repo_paths, status, created_at, updated_at, archived_at, archived_by
		FROM projects WHERE id = $1
	`, id).Scan(&p.ID, &p.Name, &p.Description, &p.RepoURL, pq.Array(&p.RepoPaths), &p.Status,
		&p.CreatedAt, &p.UpdatedAt, &p.ArchivedAt, &p.ArchivedBy)
	if err != nil {
		return nil, err
	}
	return &p, nil
}

// Create inserts a new project.
func (s *ProjectStore) Create(ctx context.Context, p *models.Project) (*models.Project, error) {
	repoPaths := p.RepoPaths
	if repoPaths == nil {
		repoPaths = []string{}
	}
	err := s.db.QueryRowContext(ctx, `
		INSERT INTO projects (name, description, repo_url, repo_paths, status)
		VALUES ($1, $2, $3, $4, 'active')
		RETURNING id, name, description, repo_url, repo_paths, status, created_at, updated_at
	`, p.Name, p.Description, p.RepoURL, pq.Array(repoPaths)).Scan(
		&p.ID, &p.Name, &p.Description, &p.RepoURL, pq.Array(&p.RepoPaths), &p.Status, &p.CreatedAt, &p.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	return p, nil
}

// Update modifies project metadata.
func (s *ProjectStore) Update(ctx context.Context, id string, name, description, repoURL string, repoPaths []string) (*models.Project, error) {
	if repoPaths == nil {
		repoPaths = []string{}
	}
	var p models.Project
	err := s.db.QueryRowContext(ctx, `
		UPDATE projects
		SET name = $2, description = $3, repo_url = $4, repo_paths = $5, updated_at = NOW()
		WHERE id = $1
		RETURNING id, name, description, repo_url, repo_paths, status, created_at, updated_at, archived_at, archived_by
	`, id, name, description, repoURL, pq.Array(repoPaths)).Scan(
		&p.ID, &p.Name, &p.Description, &p.RepoURL, pq.Array(&p.RepoPaths), &p.Status,
		&p.CreatedAt, &p.UpdatedAt, &p.ArchivedAt, &p.ArchivedBy,
	)
	if err != nil {
		return nil, err
	}
	return &p, nil
}

// Archive sets a project's status to 'archived'.
func (s *ProjectStore) Archive(ctx context.Context, id, archivedBy string) (*models.Project, error) {
	var p models.Project
	err := s.db.QueryRowContext(ctx, `
		UPDATE projects
		SET status = 'archived', archived_at = NOW(), archived_by = $2, updated_at = NOW()
		WHERE id = $1 AND status = 'active'
		RETURNING id, name, description, repo_url, repo_paths, status, created_at, updated_at, archived_at, archived_by
	`, id, archivedBy).Scan(
		&p.ID, &p.Name, &p.Description, &p.RepoURL, pq.Array(&p.RepoPaths), &p.Status,
		&p.CreatedAt, &p.UpdatedAt, &p.ArchivedAt, &p.ArchivedBy,
	)
	if err != nil {
		return nil, err
	}
	return &p, nil
}

// Unarchive restores an archived project.
func (s *ProjectStore) Unarchive(ctx context.Context, id string) (*models.Project, error) {
	var p models.Project
	err := s.db.QueryRowContext(ctx, `
		UPDATE projects
		SET status = 'active', archived_at = NULL, archived_by = NULL, updated_at = NOW()
		WHERE id = $1 AND status = 'archived'
		RETURNING id, name, description, repo_url, repo_paths, status, created_at, updated_at, archived_at, archived_by
	`, id).Scan(
		&p.ID, &p.Name, &p.Description, &p.RepoURL, pq.Array(&p.RepoPaths), &p.Status,
		&p.CreatedAt, &p.UpdatedAt, &p.ArchivedAt, &p.ArchivedBy,
	)
	if err != nil {
		return nil, err
	}
	return &p, nil
}

// ListForUser returns projects where the given user is a member.
func (s *ProjectStore) ListForUser(ctx context.Context, userID string, includeArchived bool) ([]models.Project, error) {
	var query string
	var args []interface{}

	if userID == "" {
		query = `SELECT id, name, description, repo_url, repo_paths, status, created_at, updated_at, archived_at, archived_by
				 FROM projects`
		if !includeArchived {
			query += ` WHERE status = 'active'`
		}
		query += ` ORDER BY name`
	} else {
		query = `SELECT p.id, p.name, p.description, p.repo_url, p.repo_paths, p.status, p.created_at, p.updated_at, p.archived_at, p.archived_by
				 FROM projects p
				 JOIN project_members pm ON pm.project_id = p.id
				 WHERE pm.user_id = $1`
		if !includeArchived {
			query += ` AND p.status = 'active'`
		}
		query += ` ORDER BY p.name`
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
		if err := rows.Scan(&p.ID, &p.Name, &p.Description, &p.RepoURL, pq.Array(&p.RepoPaths), &p.Status,
			&p.CreatedAt, &p.UpdatedAt, &p.ArchivedAt, &p.ArchivedBy); err != nil {
			return nil, err
		}
		projects = append(projects, p)
	}
	return projects, rows.Err()
}

// ListByIDs returns active projects matching the given IDs.
func (s *ProjectStore) ListByIDs(ctx context.Context, ids []string) ([]models.Project, error) {
	if len(ids) == 0 {
		return []models.Project{}, nil
	}
	query := `SELECT id, name, description, repo_url, repo_paths, status, created_at, updated_at, archived_at, archived_by
			  FROM projects WHERE id = ANY($1) AND status = 'active' ORDER BY name`
	rows, err := s.db.QueryContext(ctx, query, pq.Array(ids))
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var projects []models.Project
	for rows.Next() {
		var p models.Project
		if err := rows.Scan(&p.ID, &p.Name, &p.Description, &p.RepoURL, pq.Array(&p.RepoPaths), &p.Status,
			&p.CreatedAt, &p.UpdatedAt, &p.ArchivedAt, &p.ArchivedBy); err != nil {
			return nil, err
		}
		projects = append(projects, p)
	}
	if projects == nil {
		projects = []models.Project{}
	}
	return projects, rows.Err()
}
```

> ⚠️ **Note**: The replacement above omits `GetStats`. After writing the new store content, **append** the following function at the end of the file:

```go
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

- [ ] **Step 3: Build to verify compilation**

```bash
cd ennam.kg.go
go build ./internal/store/... ./internal/models/...
# Expected: no output (clean)
```

- [ ] **Step 4: Commit**

```bash
git add internal/models/project.go internal/store/project.go
git commit -m "feat: add RepoPaths to Project model and store"
```

---

### Task 3: Go Service — update interface + request types

**Files:**
- Modify: `ennam.kg.go/internal/service/project.go`

- [ ] **Step 1: Update `ProjectRepository` interface, request types, and `UpdateProject` logic**

In `ennam.kg.go/internal/service/project.go`, make these changes:

```go
// ProjectRepository — Update gains repoPaths parameter
type ProjectRepository interface {
	Create(ctx context.Context, p *models.Project) (*models.Project, error)
	GetByID(ctx context.Context, id string) (*models.Project, error)
	Update(ctx context.Context, id string, name, description, repoURL string, repoPaths []string) (*models.Project, error)
	Archive(ctx context.Context, id, archivedBy string) (*models.Project, error)
	Unarchive(ctx context.Context, id string) (*models.Project, error)
	ListForUser(ctx context.Context, userID string, includeArchived bool) ([]models.Project, error)
	GetStats(ctx context.Context, projectID string) (*models.ProjectStats, error)
}
```

```go
// CreateProjectRequest — add RepoPaths
type CreateProjectRequest struct {
	Name        string   `json:"name"`
	Description string   `json:"description"`
	RepoURL     string   `json:"repo_url"`
	RepoPaths   []string `json:"repo_paths"`
	CreatorID   string   `json:"-"`
}
```

```go
// UpdateProjectRequest — add RepoPaths
type UpdateProjectRequest struct {
	Name        *string  `json:"name,omitempty"`
	Description *string  `json:"description,omitempty"`
	RepoURL     *string  `json:"repo_url,omitempty"`
	RepoPaths   *[]string `json:"repo_paths,omitempty"`
}
```

In `CreateProject`, pass `RepoPaths` when creating the model:
```go
p, err := s.projects.Create(ctx, &models.Project{
	Name:        name,
	Description: strings.TrimSpace(req.Description),
	RepoURL:     strings.TrimSpace(req.RepoURL),
	RepoPaths:   req.RepoPaths,
})
```

Replace `UpdateProject` with:
```go
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
	repoPaths := existing.RepoPaths
	if req.RepoPaths != nil {
		cleaned := make([]string, 0, len(*req.RepoPaths))
		for _, p := range *req.RepoPaths {
			if t := strings.TrimSpace(p); t != "" {
				cleaned = append(cleaned, t)
			}
		}
		repoPaths = cleaned
	}
	if repoPaths == nil {
		repoPaths = []string{}
	}

	return s.projects.Update(ctx, id, name, desc, repoURL, repoPaths)
}
```

- [ ] **Step 2: Update mock in `internal/service/project_test.go`**

The mock `Update` at line 48 uses the old 4-arg signature. Replace it to match the new interface:

```go
func (m *mockProjectRepo) Update(_ context.Context, id, name, description, repoURL string, repoPaths []string) (*models.Project, error) {
	if m.updateErr != nil {
		return nil, m.updateErr
	}
	p, ok := m.projects[id]
	if !ok {
		return nil, sql.ErrNoRows
	}
	p.Name = name
	p.Description = description
	p.RepoURL = repoURL
	p.RepoPaths = repoPaths
	p.UpdatedAt = time.Now().UTC()
	result := *p
	return &result, nil
}
```

- [ ] **Step 3: Build + run tests**

```bash
cd ennam.kg.go
go build ./internal/service/... ./internal/handler/...
go test ./internal/service/... -v
# Expected: all tests pass, no compile errors
```

- [ ] **Step 4: Commit**

```bash
git add internal/service/project.go internal/service/project_test.go
git commit -m "feat: add RepoPaths to project service request types, update logic and test mock"
```

---

### Task 4: Go Handler — add `POST /api/v1/projects/{id}/index` endpoint

**Files:**
- Modify: `ennam.kg.go/internal/handler/project.go`
- Modify: `ennam.kg.go/cmd/kg-server/main.go`

- [ ] **Step 1: Add `pub` field + setter to `ProjectHandler`**

In `ennam.kg.go/internal/handler/project.go`, add `pub queue.Publisher` to the struct and a setter:

Add import:
```go
import (
	// existing imports...
	"github.com/ennam/ennam-kg/internal/queue"
)
```

Add field to struct:
```go
type ProjectHandler struct {
	store   *store.ProjectStore
	service *service.ProjectService
	logger  *slog.Logger
	pub     queue.Publisher // optional; set via SetIndexPublisher
}
```

Add setter method (after `NewProjectHandler`):
```go
// SetIndexPublisher wires a queue publisher for the index trigger endpoint.
func (h *ProjectHandler) SetIndexPublisher(pub queue.Publisher) {
	h.pub = pub
}
```

- [ ] **Step 2: Add `HandleTriggerIndex` handler**

Add this method to `project.go`:

```go
type triggerIndexRequest struct {
	RepoPaths []string `json:"repo_paths"`
}

type triggerIndexResponse struct {
	Queued int `json:"queued"`
}

// HandleTriggerIndex handles POST /api/v1/projects/{id}/index.
// Publishes one index_project queue message per non-empty repo path.
func (h *ProjectHandler) HandleTriggerIndex(w http.ResponseWriter, r *http.Request) {
	if h.pub == nil {
		errorResponse(w, http.StatusServiceUnavailable, "queue not configured")
		return
	}

	id := r.PathValue("id")
	if id == "" {
		errorResponse(w, http.StatusBadRequest, "project id is required")
		return
	}

	// Check access: global admin or project member.
	if !isGlobalAdmin(r) {
		identity := middleware.GetDeveloperIdentity(r.Context())
		if identity == nil || !identity.HasProjectAccess(id) {
			errorResponse(w, http.StatusForbidden, "access denied for this project")
			return
		}
	}

	var req triggerIndexRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid request body")
		return
	}

	queued := 0
	for _, path := range req.RepoPaths {
		if strings.TrimSpace(path) == "" {
			continue
		}
		if err := h.pub.Publish(r.Context(), queue.IndexMessage{
			Type:      queue.MsgIndexProject,
			ProjectID: id,
			RepoPath:  strings.TrimSpace(path),
		}); err != nil {
			h.logger.Warn("failed to publish index job", "error", err, "path", path)
			continue
		}
		queued++
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted)
	_ = json.NewEncoder(w).Encode(triggerIndexResponse{Queued: queued})
}
```

- [ ] **Step 3: Register the new route**

In `RegisterRoutes` in `project.go`, add:
```go
mux.HandleFunc("POST /api/v1/projects/{id}/index", h.HandleTriggerIndex)
```

- [ ] **Step 4: Wire `SetIndexPublisher` in main.go**

In `ennam.kg.go/cmd/kg-server/main.go`, find the line:
```go
projectHandler := handler.NewProjectHandler(projectStore, projectSvc, logger)
projectHandler.RegisterRoutes(apiMux)
```

Add the publisher wire **between** those two lines:
```go
projectHandler := handler.NewProjectHandler(projectStore, projectSvc, logger)
projectHandler.SetIndexPublisher(pub)
projectHandler.RegisterRoutes(apiMux)
```

- [ ] **Step 5: Build full binary**

```bash
cd ennam.kg.go
go build ./...
# Expected: no output (clean)
```

- [ ] **Step 6: Commit**

```bash
git add internal/handler/project.go cmd/kg-server/main.go
git commit -m "feat: add POST /api/v1/projects/{id}/index endpoint for triggering code indexing"
```

---

### Task 5: Python — add `POST /index/batch` endpoint

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/api/indexing.py`

- [ ] **Step 1: Write failing test**

In `ennam.kg.python/tests/test_api_indexing.py` (create if it doesn't exist):

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from ennam_kg.main import app

client = TestClient(app)


def test_batch_index_rejects_empty_repo_paths():
    resp = client.post("/index/batch", json={"project_id": "proj-1", "repo_paths": []})
    assert resp.status_code == 400


def test_batch_index_rejects_blank_path():
    resp = client.post("/index/batch", json={"project_id": "proj-1", "repo_paths": ["  "]})
    assert resp.status_code == 400


def test_batch_index_missing_project_id():
    resp = client.post("/index/batch", json={"repo_paths": ["/some/path"]})
    assert resp.status_code == 422  # pydantic validation
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
cd ennam.kg.python
uv run pytest tests/test_api_indexing.py -v
# Expected: 3 failures — endpoint does not exist yet
```

- [ ] **Step 3: Add `POST /index/batch` to `api/indexing.py`**

```python
class BatchIndexRequest(BaseModel):
    project_id: str
    repo_paths: list[str]


@router.post("/batch")
async def index_batch(body: BatchIndexRequest) -> dict:
    """Trigger full scans for multiple repo paths under one project."""
    valid_paths = [p.strip() for p in body.repo_paths if p.strip()]
    if not valid_paths:
        raise HTTPException(status_code=400, detail="repo_paths must contain at least one non-empty path")
    engine = _make_engine()
    results = []
    for path in valid_paths:
        result = await engine.full_scan(body.project_id, path)
        results.append({"repo_path": path, "files_scanned": result.files_scanned,
                         "nodes_created": result.nodes_created, "nodes_updated": result.nodes_updated,
                         "errors": result.errors})
    return {"project_id": body.project_id, "scanned": len(results), "results": results}
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/test_api_indexing.py -v
# Expected: 3 passed
```

- [ ] **Step 5: Lint**

```bash
uv run ruff check src/ennam_kg/api/indexing.py
# Expected: no errors
```

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/api/indexing.py tests/test_api_indexing.py
git commit -m "feat: add POST /index/batch endpoint for multi-repo indexing"
```

---

### Task 6: NextJS — fix types + add `useIndexSources` hook

**Files:**
- Modify: `ennam.kg.next/src/types/project.ts`
- Modify: `ennam.kg.next/src/hooks/use-projects.ts`

- [ ] **Step 1: Fix `types/project.ts`**

Replace the current content:

```typescript
export interface Project {
  id: string;
  name: string;
  description: string;
  repo_url: string;
  repo_paths: string[];
  status?: 'active' | 'archived';
  archived_at?: string;
  archived_by?: string;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}
```

> Note: `repo_path` (broken alias) is removed. `repo_url` is the primary single path (backward compat). `repo_paths` is the new array.

- [ ] **Step 2: Add `useIndexSources` to `hooks/use-projects.ts`**

Add after the existing `useUpdateProject` export:

```typescript
async function triggerIndex(args: { projectId: string; repoPaths: string[] }): Promise<{ queued: number }> {
  const res = await fetch(`/api/kg/projects/${args.projectId}/index`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo_paths: args.repoPaths }),
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(`Index trigger failed: ${msg}`);
  }
  return res.json();
}

export function useIndexSources(projectId: string) {
  return useMutation({
    mutationFn: (repoPaths: string[]) => triggerIndex({ projectId, repoPaths }),
  });
}
```

- [ ] **Step 3: Type-check**

```bash
cd ennam.kg.next
npx tsc --noEmit
# Expected: no errors (or only pre-existing errors unrelated to these files)
```

- [ ] **Step 4: Fix remaining `repo_path` reference in `projects/[id]/page.tsx:196`**

In `ennam.kg.next/src/app/(dashboard)/projects/[id]/page.tsx`, find and change:

```tsx
// BEFORE
<InfoRow label="Repository Path" value={project.repo_path} />

// AFTER
<InfoRow label="Repository Path" value={project.repo_url} />
```

Then verify no other stray `repo_path` references remain:

```bash
grep -rn "repo_path" src/
# Expected: only settings/page.tsx (handled in Task 7) or nothing
```

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.next
git add src/types/project.ts src/hooks/use-projects.ts
git commit -m "feat: fix repo_path naming bug, add repo_paths type and useIndexSources hook"
```

---

### Task 7: NextJS Settings UI — Code Sources section

**Files:**
- Modify: `ennam.kg.next/src/app/(dashboard)/settings/page.tsx`

- [ ] **Step 1: Replace the settings page**

Full replacement of `ennam.kg.next/src/app/(dashboard)/settings/page.tsx`:

```tsx
'use client';

import { useState, useEffect } from 'react';
import { useProject } from '@/lib/context/project';
import { useProjectDetail, useUpdateProject, useIndexSources } from '@/hooks/use-projects';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Separator } from '@/components/ui/separator';
import { useVfx } from '@/lib/context/vfx';
import { Sparkles, Moon, Plus, Trash2, Play, Loader2 } from 'lucide-react';

export default function SettingsPage() {
  const { projectId } = useProject();
  const { data: project, isLoading } = useProjectDetail(projectId);
  const updateProject = useUpdateProject();
  const indexSources = useIndexSources(projectId);

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [repoPaths, setRepoPaths] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const { mode, setMode } = useVfx();

  useEffect(() => {
    if (project) {
      setName(project.name ?? '');
      setDescription(project.description ?? '');
      setRepoPaths(project.repo_paths?.length ? project.repo_paths : []);
    }
  }, [project]);

  const handleSave = () => {
    setSaved(false);
    updateProject.mutate(
      {
        id: projectId,
        data: {
          name,
          description,
          repo_paths: repoPaths.filter((p) => p.trim() !== ''),
        },
      },
      { onSuccess: () => setSaved(true) }
    );
  };

  const addPath = () => setRepoPaths((prev) => [...prev, '']);
  const removePath = (i: number) => setRepoPaths((prev) => prev.filter((_, idx) => idx !== i));
  const updatePath = (i: number, val: string) =>
    setRepoPaths((prev) => prev.map((p, idx) => (idx === i ? val : p)));

  const validPaths = repoPaths.filter((p) => p.trim() !== '');

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Project metadata */}
      <Card variant="glass">
        <CardHeader>
          <CardTitle className="text-sm font-medium">Project Settings</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="project-name">
              Project Name
            </label>
            <Input
              id="project-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Project"
            />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="project-description">
              Description
            </label>
            <Textarea
              id="project-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="A brief description of this project"
              rows={3}
            />
          </div>

          <div className="flex items-center gap-3">
            <Button onClick={handleSave} disabled={updateProject.isPending}>
              {updateProject.isPending ? 'Saving...' : 'Save Changes'}
            </Button>
            {saved && <span className="text-sm text-green-500">Changes saved successfully.</span>}
            {updateProject.isError && (
              <span className="text-sm text-destructive">Failed to save. Please try again.</span>
            )}
          </div>
        </CardContent>
      </Card>

      <Separator />

      {/* Code Sources */}
      <Card variant="glass">
        <CardHeader>
          <CardTitle className="text-sm font-medium">Code Sources</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Local filesystem paths to source code repositories. The indexer scans these paths to build
            code knowledge nodes. Multiple repos can share one project.
          </p>

          {repoPaths.map((path, i) => (
            <div key={i} className="flex gap-2 items-center">
              <Input
                value={path}
                onChange={(e) => updatePath(i, e.target.value)}
                placeholder="/path/to/repository"
                className="flex-1 font-mono text-xs"
              />
              <Button
                size="sm"
                variant="outline"
                disabled={!path.trim() || indexSources.isPending}
                onClick={() => indexSources.mutate([path])}
                title="Index this path now"
              >
                {indexSources.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Play className="h-3 w-3" />
                )}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => removePath(i)}
                title="Remove this path"
              >
                <Trash2 className="h-3 w-3 text-destructive" />
              </Button>
            </div>
          ))}

          <div className="flex flex-wrap gap-2 pt-1">
            <Button size="sm" variant="outline" onClick={addPath}>
              <Plus className="h-3 w-3 mr-1" />
              Add Source Path
            </Button>
            {validPaths.length > 1 && (
              <Button
                size="sm"
                disabled={indexSources.isPending}
                onClick={() => indexSources.mutate(validPaths)}
              >
                {indexSources.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1" />
                ) : (
                  <Play className="h-3 w-3 mr-1" />
                )}
                Index All Sources ({validPaths.length})
              </Button>
            )}
          </div>

          {indexSources.isError && (
            <p className="text-xs text-destructive">
              {(indexSources.error as Error).message}
            </p>
          )}
          {indexSources.isSuccess && (
            <p className="text-xs text-green-500">
              Queued {indexSources.data.queued} indexing job(s).
            </p>
          )}

          <div className="flex items-center gap-3 pt-2 border-t border-border">
            <Button onClick={handleSave} size="sm" disabled={updateProject.isPending}>
              {updateProject.isPending ? 'Saving...' : 'Save Source Paths'}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Separator />

      {/* Appearance */}
      <Card variant="glass">
        <CardHeader>
          <CardTitle className="text-sm font-medium">Appearance</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground mb-4">
            Choose your visual effects intensity.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={() => setMode('balanced')}
              className={`flex flex-col items-center gap-2 p-4 rounded-xl border transition-all ${
                mode === 'balanced'
                  ? 'border-primary bg-primary/10 glow-cyan'
                  : 'border-border hover:border-primary/50'
              }`}
            >
              <Sparkles className={`size-6 ${mode === 'balanced' ? 'text-primary' : 'text-muted-foreground'}`} />
              <span className="text-sm font-medium">Balanced Neon</span>
              <span className="text-xs text-muted-foreground text-center">
                Full glassmorphism, glows, and neon effects
              </span>
            </button>
            <button
              onClick={() => setMode('subtle')}
              className={`flex flex-col items-center gap-2 p-4 rounded-xl border transition-all ${
                mode === 'subtle'
                  ? 'border-primary bg-primary/10 glow-cyan'
                  : 'border-border hover:border-primary/50'
              }`}
            >
              <Moon className={`size-6 ${mode === 'subtle' ? 'text-primary' : 'text-muted-foreground'}`} />
              <span className="text-sm font-medium">Subtle Dark</span>
              <span className="text-xs text-muted-foreground text-center">
                Reduced glows, minimal glass effects
              </span>
            </button>
          </div>
        </CardContent>
      </Card>

      <Separator />

      {/* Danger Zone */}
      <Card className="border-destructive/50">
        <CardHeader>
          <CardTitle className="text-sm font-medium text-destructive">Danger Zone</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground mb-3">
            Archiving a project will hide it from all views. This action can be reversed.
          </p>
          <Button variant="destructive" disabled>
            Archive Project
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
cd ennam.kg.next
npx tsc --noEmit
# Expected: no errors from settings/page.tsx
```

- [ ] **Step 3: Run dev server and smoke-test**

```bash
npm run dev
# Open http://localhost:3500/settings
# Verify:
# - "Code Sources" card is visible
# - Can add paths with "+ Add Source Path"
# - "Save Source Paths" sends repo_paths array (check Network tab)
# - "Index Now" (▶) button per path is present
# - "Index All Sources" button appears when ≥2 valid paths exist
```

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.next
git add src/app/\(dashboard\)/settings/page.tsx
git commit -m "feat: add Code Sources section to Settings page with multi-repo and Index Now UI"
```

---

## Self-Review

### Spec coverage

| Requirement | Task |
|-------------|------|
| Fix `repo_path` → `repo_url` naming bug | Task 6 (type fix) + Task 7 (form sends `repo_paths`) |
| Multi-repo paths per project | Task 1 (DB) + Task 2 (store) + Task 3 (service) + Task 7 (UI) |
| "Index Now" per path | Task 4 (Go endpoint) + Task 7 (button) |
| "Index All" button | Task 7 |
| Python batch endpoint | Task 5 |
| Guard empty `repo_path` in worker | Already done (pre-plan fix) |

### Type consistency check

- `Project.repo_paths: string[]` defined in Task 6, consumed in Task 7 ✓
- `useIndexSources` returns `{ queued: number }` — matches `triggerIndexResponse` from Task 4 ✓  
- `UpdateProjectRequest.RepoPaths *[]string` defined in Task 3, used in store's `Update(... repoPaths []string)` from Task 2 ✓
- `pq.Array(&p.RepoPaths)` scan pattern consistent across all store functions in Task 2 ✓

### Placeholder scan

None found — all steps contain actual code.
