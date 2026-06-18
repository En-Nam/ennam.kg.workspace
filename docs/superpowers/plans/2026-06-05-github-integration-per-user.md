# GitHub Integration (Per-User) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each user connect their own GitHub account via Personal Access Token, select repos per project, and have them cloned, indexed, and re-indexed on push.

**Architecture:** Per-user GitHub tokens live in a NEW `github_connections` table (one row per user, AES-256-GCM encrypted PAT) — we do **not** reuse `oauth_tokens` (that table is a platform-global singleton-per-provider, admin-only, built for Claude OAuth BA-021). Repo selection reuses the existing `source_connections` table with a new `github_repo` source_type. The Go API talks to the GitHub REST API (list repos, register/delete webhooks); on add or push it publishes an `index_project` queue message carrying an ephemeral clone URL + decrypted token. The Python worker clones to a temp dir via a `GitCloner` context manager, runs the existing `full_scan`, and deletes the clone.

**Tech Stack:** Go (stdlib `net/http`, `database/sql`, golang-migrate, `internal/crypto` AES-256-GCM), Python 3.12 (pydantic, subprocess `git`), NextJS 16 / React 19 / TanStack Query.

> **⚠ Spec discrepancy recorded:** The spec [`2026-06-04-github-integration-design.md`](../specs/2026-06-04-github-integration-design.md) is marked "Approved" but contradicts the live schema in two places: (1) it says "No new tables needed" and models GitHub tokens as per-user on `oauth_tokens`, but `oauth_tokens` is `UNIQUE(provider)` (one row per provider, platform-wide) — per-user requires a new table; (2) it relies on `source_connections` but that table's `source_type` CHECK lacks `github_repo` and its `UNIQUE(project_id, source_type)` blocks the spec's own "multiple repos per project" scope. This plan resolves both. Decision confirmed with product owner 2026-06-05: **per-user model, new `github_connections` table.**
>
> **⚠ BLOCKER discovered during planning — file-path stability (Task 12a, do this first in Phase 5):** The indexer's natural key for create/update/archive is `file_path:name:kind`, and `extractor.symbol_to_node` stores `file_path` as the **absolute path** (`fp = str(file_path)`). Today repos sit at stable Docker mounts (`/repos/ennam-kg-go`), so keys are stable across re-indexes. Clone-based indexing uses a **random** temp dir (`/tmp/ennam-kg-clone-XXXX`) per clone, so on every push the keys would not match prior nodes → **duplicate nodes accumulate and stale ones are never archived** (the differ only archives within the scanned file set). Fix: normalize `file_path` to **repo-relative** in the extractor so keys are independent of where the repo is checked out. This is a behavior change to existing data — existing mount-indexed projects store absolute paths and will need a one-time re-index. **Confirm with product owner before implementing Task 12a** (it touches the shared Docker-mount indexing path, not just GitHub).

---

## File Structure

**Go (`ennam.kg.go/`)**
- `db/migrations/000057_create_github_connections.{up,down}.sql` — new per-user token table
- `db/migrations/000058_source_connections_github_repo.{up,down}.sql` — add `github_repo` type + relax unique
- `internal/models/github_connection.go` — `GitHubConnection` struct + status constants
- `internal/store/github_connection.go` — encrypted CRUD (mirrors `oauth_token.go`)
- `internal/github/client.go` — GitHub REST client (GetUser, ListRepos, CreateWebhook, DeleteWebhook)
- `internal/service/github.go` — connect/disconnect/list-repos orchestration
- `internal/service/github_source.go` — per-project repo add/remove + webhook + publish index
- `internal/handler/github.go` — per-user routes (`/api/v1/github/*`)
- `internal/handler/github_source.go` — per-project routes (`/api/v1/projects/{id}/github-sources`)
- `internal/handler/github_webhook.go` — unauthenticated `POST /webhooks/github`
- `internal/queue/publisher.go:29-35` — extend `IndexMessage` with `RepoURL` + `GitHubToken`
- `cmd/kg-server/main.go` — wire the four handlers

**Python (`ennam.kg.python/`)**
- `src/ennam_kg/queue/messages.py:7-16` — add `repo_url` + `github_token` to `IndexProjectMessage`
- `src/ennam_kg/indexer/git_cloner.py` — `GitCloner` context manager
- `src/ennam_kg/worker.py:104-116` — clone-then-scan branch

**NextJS (`ennam.kg.next/`)**
- `src/types/github.ts` — request/response types
- `src/lib/api/github.ts` — fetch wrappers
- `src/hooks/use-github.ts` — TanStack Query hooks
- `src/app/(dashboard)/settings/github/page.tsx` — per-user PAT connect page
- `src/components/settings/GitHubConnect.tsx` — PAT input card
- `src/components/projects/GitHubRepoModal.tsx` — repo multi-select modal
- `src/components/projects/GitHubSourceRows.tsx` — connected-repo list with Sync/Remove

---

## Phase 0 — Database

### Task 1: Migration — `github_connections` table

**Files:**
- Create: `ennam.kg.go/db/migrations/000057_create_github_connections.up.sql`
- Create: `ennam.kg.go/db/migrations/000057_create_github_connections.down.sql`

- [ ] **Step 1: Write the up migration**

```sql
-- Migration 057: per-user GitHub connections (PAT or OAuth token, encrypted).
-- Distinct from oauth_tokens (which is a platform-global singleton-per-provider, BA-021).

CREATE TABLE github_connections (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    access_token    BYTEA NOT NULL,                      -- AES-256-GCM encrypted PAT/OAuth token
    github_username VARCHAR(255) NOT NULL,
    scopes          TEXT[] NOT NULL DEFAULT '{}',        -- granted token scopes, e.g. {repo, admin:repo_hook}
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'revoked', 'error')),
    error_message   TEXT,
    connected_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_github_connections_user UNIQUE (user_id)
);

CREATE INDEX idx_github_connections_user ON github_connections (user_id);
```

- [ ] **Step 2: Write the down migration**

```sql
DROP TABLE IF EXISTS github_connections;
```

- [ ] **Step 3: Apply and verify**

Run: `cd ennam.kg.go && make migrate-up` (or `migrate -path db/migrations -database "$DATABASE_URL" up`)
Expected: migration 057 applied, no error. Verify: `psql "$DATABASE_URL" -c "\d github_connections"` shows the table.

- [ ] **Step 4: Commit**

```bash
git add ennam.kg.go/db/migrations/000057_create_github_connections.*.sql
git commit -m "feat(db): add github_connections table for per-user GitHub tokens"
```

### Task 2: Migration — extend `source_connections` for `github_repo`

**Files:**
- Create: `ennam.kg.go/db/migrations/000058_source_connections_github_repo.up.sql`
- Create: `ennam.kg.go/db/migrations/000058_source_connections_github_repo.down.sql`

**Why two unique indexes:** existing source types (`jira`, `google_drive`, …) are singleton-per-project and rely on `UNIQUE(project_id, source_type)`. GitHub needs *many* repos per project but no duplicate of the same repo. So we drop the blanket unique, keep singleton semantics for non-github types via a partial index, and add a github-only partial index keyed on `config->>'full_name'`.

- [ ] **Step 1: Write the up migration**

```sql
-- Migration 058: allow github_repo source connections, multiple per project.

ALTER TABLE source_connections DROP CONSTRAINT IF EXISTS source_connections_source_type_check;
ALTER TABLE source_connections
    ADD CONSTRAINT source_connections_source_type_check
    CHECK (source_type IN ('jira', 'google_drive', 'local_upload', 'satellite_api', 'github_repo'));

-- Replace blanket singleton unique with per-type partial indexes.
ALTER TABLE source_connections DROP CONSTRAINT IF EXISTS uq_source_connections_project_type;

CREATE UNIQUE INDEX uq_source_connections_singleton
    ON source_connections (project_id, source_type)
    WHERE source_type <> 'github_repo';

CREATE UNIQUE INDEX uq_source_connections_github_repo
    ON source_connections (project_id, (config ->> 'full_name'))
    WHERE source_type = 'github_repo';
```

- [ ] **Step 2: Write the down migration**

```sql
DROP INDEX IF EXISTS uq_source_connections_github_repo;
DROP INDEX IF EXISTS uq_source_connections_singleton;
ALTER TABLE source_connections
    ADD CONSTRAINT uq_source_connections_project_type UNIQUE (project_id, source_type);

ALTER TABLE source_connections DROP CONSTRAINT IF EXISTS source_connections_source_type_check;
ALTER TABLE source_connections
    ADD CONSTRAINT source_connections_source_type_check
    CHECK (source_type IN ('jira', 'google_drive', 'local_upload', 'satellite_api'));
```

- [ ] **Step 3: Apply and verify**

Run: `cd ennam.kg.go && make migrate-up`
Expected: migration 058 applied. Verify two partial indexes exist: `psql "$DATABASE_URL" -c "\d source_connections"` lists `uq_source_connections_singleton` and `uq_source_connections_github_repo`.

- [ ] **Step 4: Add the model constant**

In `ennam.kg.go/internal/models/source_connection.go`, find the `DraftSourceType` constants block (the one with `DraftSourceJira`, `DraftSourceLocalUpload`, …) and add:

```go
	DraftSourceGitHubRepo DraftSourceType = "github_repo"
```

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.go/db/migrations/000058_*.sql ennam.kg.go/internal/models/source_connection.go
git commit -m "feat(db): allow multiple github_repo source connections per project"
```

---

## Phase 1 — Go: GitHub REST client

### Task 3: GitHub API client

**Files:**
- Create: `ennam.kg.go/internal/github/client.go`
- Test: `ennam.kg.go/internal/github/client_test.go`

- [ ] **Step 1: Write the failing test** (uses `httptest` to stub GitHub)

```go
package github_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/ennam/ennam-kg/internal/github"
)

func TestGetUser_ReturnsLoginAndScopes(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer ghp_test" {
			t.Fatalf("missing/wrong auth header: %q", r.Header.Get("Authorization"))
		}
		w.Header().Set("X-OAuth-Scopes", "repo, admin:repo_hook")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"login":"octocat"}`))
	}))
	defer srv.Close()

	c := github.NewClient(srv.URL)
	user, scopes, err := c.GetUser(context.Background(), "ghp_test")
	if err != nil {
		t.Fatalf("GetUser error: %v", err)
	}
	if user != "octocat" {
		t.Errorf("user = %q, want octocat", user)
	}
	if len(scopes) != 2 || scopes[0] != "repo" || scopes[1] != "admin:repo_hook" {
		t.Errorf("scopes = %v, want [repo admin:repo_hook]", scopes)
	}
}

func TestListRepos_ParsesFields(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`[{"name":"kg","full_name":"exnodes/kg","private":true,"description":"d","default_branch":"main","clone_url":"https://github.com/exnodes/kg.git"}]`))
	}))
	defer srv.Close()

	c := github.NewClient(srv.URL)
	repos, err := c.ListRepos(context.Background(), "ghp_test")
	if err != nil {
		t.Fatalf("ListRepos error: %v", err)
	}
	if len(repos) != 1 || repos[0].FullName != "exnodes/kg" || !repos[0].Private {
		t.Errorf("unexpected repos: %+v", repos)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/github/...`
Expected: FAIL — package `github` does not exist.

- [ ] **Step 3: Write the client**

```go
// Package github is a minimal GitHub REST v3 client (stdlib net/http, no SDK).
package github

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// DefaultBaseURL is the public GitHub API root.
const DefaultBaseURL = "https://api.github.com"

// Client talks to the GitHub REST API using a per-call bearer token.
type Client struct {
	baseURL string
	http    *http.Client
}

// NewClient returns a Client. Pass DefaultBaseURL in production; a test server URL in tests.
func NewClient(baseURL string) *Client {
	return &Client{baseURL: strings.TrimRight(baseURL, "/"), http: &http.Client{Timeout: 15 * time.Second}}
}

// Repo is a subset of GitHub's repository object.
type Repo struct {
	Name          string `json:"name"`
	FullName      string `json:"full_name"`
	Private       bool   `json:"private"`
	Description   string `json:"description"`
	DefaultBranch string `json:"default_branch"`
	CloneURL      string `json:"clone_url"`
}

func (c *Client) do(ctx context.Context, method, path, token string, body io.Reader) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Accept", "application/vnd.github+json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	return c.http.Do(req)
}

// GetUser validates the token and returns the login plus granted scopes (from X-OAuth-Scopes).
func (c *Client) GetUser(ctx context.Context, token string) (login string, scopes []string, err error) {
	resp, err := c.do(ctx, http.MethodGet, "/user", token, nil)
	if err != nil {
		return "", nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return "", nil, fmt.Errorf("github GetUser: status %d", resp.StatusCode)
	}
	var u struct {
		Login string `json:"login"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&u); err != nil {
		return "", nil, err
	}
	raw := resp.Header.Get("X-OAuth-Scopes")
	for _, s := range strings.Split(raw, ",") {
		if t := strings.TrimSpace(s); t != "" {
			scopes = append(scopes, t)
		}
	}
	return u.Login, scopes, nil
}

// ListRepos returns repos accessible to the token (first page, 100 per page).
func (c *Client) ListRepos(ctx context.Context, token string) ([]Repo, error) {
	resp, err := c.do(ctx, http.MethodGet, "/user/repos?per_page=100&sort=updated", token, nil)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("github ListRepos: status %d", resp.StatusCode)
	}
	var repos []Repo
	if err := json.NewDecoder(resp.Body).Decode(&repos); err != nil {
		return nil, err
	}
	return repos, nil
}

// CreateWebhook registers a push webhook on owner/repo, returning the webhook id.
func (c *Client) CreateWebhook(ctx context.Context, token, owner, repo, callbackURL, secret string) (int64, error) {
	payload := fmt.Sprintf(`{"name":"web","active":true,"events":["push"],"config":{"url":%q,"content_type":"json","secret":%q}}`, callbackURL, secret)
	resp, err := c.do(ctx, http.MethodPost, fmt.Sprintf("/repos/%s/%s/hooks", owner, repo), token, strings.NewReader(payload))
	if err != nil {
		return 0, err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusCreated {
		return 0, fmt.Errorf("github CreateWebhook: status %d", resp.StatusCode)
	}
	var hook struct {
		ID int64 `json:"id"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&hook); err != nil {
		return 0, err
	}
	return hook.ID, nil
}

// DeleteWebhook removes a webhook by id. A 404 is treated as already-deleted (no error).
func (c *Client) DeleteWebhook(ctx context.Context, token, owner, repo string, hookID int64) error {
	resp, err := c.do(ctx, http.MethodDelete, fmt.Sprintf("/repos/%s/%s/hooks/%d", owner, repo, hookID), token, nil)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusNoContent && resp.StatusCode != http.StatusNotFound {
		return fmt.Errorf("github DeleteWebhook: status %d", resp.StatusCode)
	}
	return nil
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/github/...`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.go/internal/github/
git commit -m "feat(github): add minimal GitHub REST client"
```

---

## Phase 2 — Go: per-user connection (model, store, service, handler)

### Task 4: `GitHubConnection` model + encrypted store

**Files:**
- Create: `ennam.kg.go/internal/models/github_connection.go`
- Create: `ennam.kg.go/internal/store/github_connection.go`
- Test: `ennam.kg.go/internal/store/github_connection_test.go`

- [ ] **Step 1: Write the model**

```go
package models

import "time"

// GitHubConnection maps to the github_connections table (migration 057).
// AccessTokenEnc is AES-256-GCM encrypted and never serialized to JSON.
type GitHubConnection struct {
	ID             string    `json:"id" db:"id"`
	UserID         string    `json:"user_id" db:"user_id"`
	AccessTokenEnc []byte    `json:"-" db:"access_token"`
	GitHubUsername string    `json:"github_username" db:"github_username"`
	Scopes         []string  `json:"scopes" db:"scopes"`
	Status         string    `json:"status" db:"status"`
	ErrorMessage   *string   `json:"error_message,omitempty" db:"error_message"`
	ConnectedAt    time.Time `json:"connected_at" db:"connected_at"`
	UpdatedAt      time.Time `json:"updated_at" db:"updated_at"`
}

// GitHub connection status constants.
const (
	GitHubStatusActive  = "active"
	GitHubStatusRevoked = "revoked"
	GitHubStatusError   = "error"
)
```

- [ ] **Step 2: Write the failing store test** (requires a test DB; mirrors existing `oauth_token` store tests — gate with the same build tag/env the repo uses, e.g. `KG_TEST_DATABASE_URL`)

```go
package store_test

import (
	"context"
	"os"
	"testing"

	"github.com/ennam/ennam-kg/internal/store"
)

func TestGitHubConnectionStore_UpsertAndGet_RoundTripsToken(t *testing.T) {
	dsn := os.Getenv("KG_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("KG_TEST_DATABASE_URL not set")
	}
	db := openTestDB(t, dsn) // existing test helper in this package
	key := make([]byte, 32)  // all-zero 32-byte AES key is fine for the round-trip test
	s := store.NewGitHubConnectionStore(db, key)

	userID := seedUser(t, db) // existing helper that inserts a users row, returns its UUID
	ctx := context.Background()

	got, err := s.Upsert(ctx, userID, "ghp_secret_value", "octocat", []string{"repo", "admin:repo_hook"})
	if err != nil {
		t.Fatalf("Upsert: %v", err)
	}
	if got.GitHubUsername != "octocat" {
		t.Errorf("username = %q, want octocat", got.GitHubUsername)
	}

	plain, err := s.GetToken(ctx, userID)
	if err != nil {
		t.Fatalf("GetToken: %v", err)
	}
	if plain != "ghp_secret_value" {
		t.Errorf("decrypted token = %q, want ghp_secret_value", plain)
	}
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd ennam.kg.go && KG_TEST_DATABASE_URL=$KG_TEST_DATABASE_URL go test ./internal/store/ -run TestGitHubConnectionStore`
Expected: FAIL — `store.NewGitHubConnectionStore` undefined.

- [ ] **Step 4: Write the store** (encryption mirrors `internal/store/oauth_token.go`)

```go
package store

import (
	"context"
	"database/sql"
	"fmt"

	"github.com/ennam/ennam-kg/internal/crypto"
	"github.com/ennam/ennam-kg/internal/models"
	"github.com/lib/pq"
)

// GitHubConnectionStore persists per-user GitHub connections with encrypted tokens.
type GitHubConnectionStore struct {
	db     *sql.DB
	encKey []byte // AES-256-GCM key (32 bytes)
}

// NewGitHubConnectionStore creates the store with a DB handle and 32-byte encryption key.
func NewGitHubConnectionStore(db *sql.DB, encKey []byte) *GitHubConnectionStore {
	return &GitHubConnectionStore{db: db, encKey: encKey}
}

// Upsert inserts or replaces the caller's GitHub connection (UNIQUE(user_id)).
func (s *GitHubConnectionStore) Upsert(ctx context.Context, userID, tokenPlain, username string, scopes []string) (*models.GitHubConnection, error) {
	enc, err := crypto.Encrypt([]byte(tokenPlain), s.encKey)
	if err != nil {
		return nil, fmt.Errorf("encrypt token: %w", err)
	}
	const q = `
		INSERT INTO github_connections (user_id, access_token, github_username, scopes, status)
		VALUES ($1, $2, $3, $4, 'active')
		ON CONFLICT (user_id) DO UPDATE
		SET access_token = EXCLUDED.access_token,
		    github_username = EXCLUDED.github_username,
		    scopes = EXCLUDED.scopes,
		    status = 'active',
		    error_message = NULL,
		    updated_at = NOW()
		RETURNING id, user_id, github_username, scopes, status, connected_at, updated_at`
	var c models.GitHubConnection
	// pq.Array on both bind and scan — matches the idiom in store/oauth_token.go.
	err = s.db.QueryRowContext(ctx, q, userID, enc, username, pq.Array(scopes)).Scan(
		&c.ID, &c.UserID, &c.GitHubUsername, pq.Array(&c.Scopes), &c.Status, &c.ConnectedAt, &c.UpdatedAt)
	if err != nil {
		return nil, fmt.Errorf("upsert github_connection: %w", err)
	}
	return &c, nil
}

// Get returns the caller's connection metadata, or (nil, nil) if not connected.
func (s *GitHubConnectionStore) Get(ctx context.Context, userID string) (*models.GitHubConnection, error) {
	const q = `
		SELECT id, user_id, github_username, scopes, status, error_message, connected_at, updated_at
		FROM github_connections WHERE user_id = $1`
	var c models.GitHubConnection
	err := s.db.QueryRowContext(ctx, q, userID).Scan(
		&c.ID, &c.UserID, &c.GitHubUsername, pq.Array(&c.Scopes), &c.Status, &c.ErrorMessage, &c.ConnectedAt, &c.UpdatedAt)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("get github_connection: %w", err)
	}
	return &c, nil
}

// GetToken decrypts and returns the caller's token. Errors if not connected.
func (s *GitHubConnectionStore) GetToken(ctx context.Context, userID string) (string, error) {
	var enc []byte
	err := s.db.QueryRowContext(ctx, `SELECT access_token FROM github_connections WHERE user_id = $1`, userID).Scan(&enc)
	if err == sql.ErrNoRows {
		return "", fmt.Errorf("no github connection for user")
	}
	if err != nil {
		return "", fmt.Errorf("get token: %w", err)
	}
	plain, err := crypto.Decrypt(enc, s.encKey)
	if err != nil {
		return "", fmt.Errorf("decrypt token: %w", err)
	}
	return string(plain), nil
}

// Delete removes the caller's connection.
func (s *GitHubConnectionStore) Delete(ctx context.Context, userID string) error {
	_, err := s.db.ExecContext(ctx, `DELETE FROM github_connections WHERE user_id = $1`, userID)
	if err != nil {
		return fmt.Errorf("delete github_connection: %w", err)
	}
	return nil
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd ennam.kg.go && KG_TEST_DATABASE_URL=$KG_TEST_DATABASE_URL go test ./internal/store/ -run TestGitHubConnectionStore`
Expected: PASS (or SKIP if no test DB — then verify compile with `go build ./...`).

- [ ] **Step 6: Commit**

```bash
git add ennam.kg.go/internal/models/github_connection.go ennam.kg.go/internal/store/github_connection.go ennam.kg.go/internal/store/github_connection_test.go
git commit -m "feat(github): per-user connection model + encrypted store"
```

### Task 5: GitHub service (connect / status / disconnect / repos)

**Files:**
- Create: `ennam.kg.go/internal/service/github.go`
- Test: `ennam.kg.go/internal/service/github_test.go`

- [ ] **Step 1: Write the failing test** (stub GitHub via the client's base URL)

```go
package service_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/ennam/ennam-kg/internal/github"
	"github.com/ennam/ennam-kg/internal/service"
)

func TestGitHubService_Connect_RejectsMissingHookScope(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("X-OAuth-Scopes", "repo") // missing admin:repo_hook
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"login":"octocat"}`))
	}))
	defer srv.Close()

	svc := service.NewGitHubService(nil, nil, github.NewClient(srv.URL), nil) // stores nil: scope validation runs before any store call
	_, err := svc.Connect(context.Background(), "user-1", "ghp_x")
	if err == nil || !service.IsMissingScopeError(err) {
		t.Fatalf("expected missing-scope error, got %v", err)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/service/ -run TestGitHubService_Connect`
Expected: FAIL — `service.NewGitHubService` undefined.

- [ ] **Step 3: Write the service**

```go
package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"

	"github.com/ennam/ennam-kg/internal/github"
	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/store"
)

// errMissingScope is returned when the token lacks admin:repo_hook (needed for webhook auto-sync).
var errMissingScope = errors.New("token missing required scope admin:repo_hook")

// IsMissingScopeError reports whether err is the missing-scope sentinel.
func IsMissingScopeError(err error) bool { return errors.Is(err, errMissingScope) }

// githubUserSourceStore is the subset of source persistence Disconnect needs to clean up
// every webhook the user owns before the token is deleted. Satisfied by *store.SourceConnectionStore.
// NOTE: the real Delete takes (projectID, id) — both are required by the existing store.
type githubUserSourceStore interface {
	// ListGitHubByCreatedBy returns all github_repo connections created by the user.
	ListGitHubByCreatedBy(ctx context.Context, userID string) ([]models.SourceConnection, error)
	Delete(ctx context.Context, projectID, id string) error
}

// GitHubService orchestrates per-user GitHub connection lifecycle.
type GitHubService struct {
	store   *store.GitHubConnectionStore
	sources githubUserSourceStore
	client  *github.Client
	logger  *slog.Logger
}

// NewGitHubService wires the connection store, source store (for webhook cleanup), GitHub client, and logger.
func NewGitHubService(s *store.GitHubConnectionStore, sources githubUserSourceStore, client *github.Client, logger *slog.Logger) *GitHubService {
	return &GitHubService{store: s, sources: sources, client: client, logger: logger}
}

// Connect validates a pasted PAT against GitHub, enforces required scopes, and stores it encrypted.
func (s *GitHubService) Connect(ctx context.Context, userID, token string) (*models.GitHubConnection, error) {
	login, scopes, err := s.client.GetUser(ctx, token)
	if err != nil {
		return nil, fmt.Errorf("validate token: %w", err)
	}
	if !hasScope(scopes, "repo") {
		return nil, fmt.Errorf("token missing required scope repo")
	}
	if !hasScope(scopes, "admin:repo_hook") {
		return nil, errMissingScope
	}
	return s.store.Upsert(ctx, userID, token, login, scopes)
}

// Status returns the caller's connection metadata, or (nil, nil) if not connected.
func (s *GitHubService) Status(ctx context.Context, userID string) (*models.GitHubConnection, error) {
	return s.store.Get(ctx, userID)
}

// ListRepos returns repos accessible to the caller's stored token.
func (s *GitHubService) ListRepos(ctx context.Context, userID string) ([]github.Repo, error) {
	token, err := s.store.GetToken(ctx, userID)
	if err != nil {
		return nil, err
	}
	return s.client.ListRepos(ctx, token)
}

// repoCfgFields is the minimal config shape needed to delete a webhook.
type repoCfgFields struct {
	Owner     string `json:"owner"`
	Repo      string `json:"repo"`
	WebhookID int64  `json:"webhook_id"`
}

// Disconnect deletes every webhook the user registered, removes their github_repo source rows,
// then deletes the token — matching the spec requirement "deletes all webhooks before removing token".
func (s *GitHubService) Disconnect(ctx context.Context, userID string) error {
	token, tokErr := s.store.GetToken(ctx, userID) // may fail if already gone; webhook cleanup is best-effort
	sources, err := s.sources.ListGitHubByCreatedBy(ctx, userID)
	if err != nil {
		s.logger.Warn("disconnect: could not list user sources, skipping webhook cleanup", "user", userID, "error", err)
	}
	for _, conn := range sources {
		var cfg repoCfgFields
		_ = json.Unmarshal(conn.Config, &cfg)
		if tokErr == nil && cfg.WebhookID != 0 {
			if delErr := s.client.DeleteWebhook(ctx, token, cfg.Owner, cfg.Repo, cfg.WebhookID); delErr != nil {
				s.logger.Warn("disconnect: failed to delete webhook (continuing)", "owner", cfg.Owner, "repo", cfg.Repo, "error", delErr)
			}
		}
		if delErr := s.sources.Delete(ctx, conn.ProjectID, conn.ID); delErr != nil {
			s.logger.Warn("disconnect: failed to delete source row (continuing)", "conn", conn.ID, "error", delErr)
		}
	}
	return s.store.Delete(ctx, userID)
}

func hasScope(scopes []string, want string) bool {
	for _, s := range scopes {
		if s == want {
			return true
		}
	}
	return false
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/service/ -run TestGitHubService_Connect`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.go/internal/service/github.go ennam.kg.go/internal/service/github_test.go
git commit -m "feat(github): connection service with scope validation"
```

### Task 6: Per-user HTTP handler `/api/v1/github/*`

**Files:**
- Create: `ennam.kg.go/internal/handler/github.go`
- Test: `ennam.kg.go/internal/handler/github_test.go`

- [ ] **Step 1: Write the failing test**

```go
package handler_test

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/handler"
)

func TestGitHubHandler_Connect_BadJSON_Returns400(t *testing.T) {
	h := handler.NewGitHubHandler(nil, nil) // service nil ok: JSON decode fails before service use
	mux := http.NewServeMux()
	h.RegisterRoutes(mux)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/github/connect", strings.NewReader("{bad"))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Errorf("status = %d, want 400", rec.Code)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestGitHubHandler_Connect`
Expected: FAIL — `handler.NewGitHubHandler` undefined.

- [ ] **Step 3: Write the handler** (auth via existing `middleware.GetUserIdentity`; reuse `errorResponse` already defined in the handler package)

```go
package handler

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"strings"

	"github.com/ennam/ennam-kg/internal/service"
)

// GitHubHandler serves per-user GitHub connection endpoints.
type GitHubHandler struct {
	svc    *service.GitHubService
	logger *slog.Logger
}

// NewGitHubHandler constructs the handler.
func NewGitHubHandler(svc *service.GitHubService, logger *slog.Logger) *GitHubHandler {
	return &GitHubHandler{svc: svc, logger: logger}
}

// RegisterRoutes registers per-user GitHub routes.
func (h *GitHubHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/github/connect", h.Connect)
	mux.HandleFunc("GET /api/v1/github/status", h.Status)
	mux.HandleFunc("DELETE /api/v1/github/connect", h.Disconnect)
	mux.HandleFunc("GET /api/v1/github/repos", h.Repos)
}

type connectRequest struct {
	Token string `json:"token"`
}

// Connect validates and stores the caller's pasted PAT.
func (h *GitHubHandler) Connect(w http.ResponseWriter, r *http.Request) {
	userID := resolveUserID(r)
	if userID == "" {
		errorResponse(w, http.StatusUnauthorized, "authentication required")
		return
	}
	var req connectRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid JSON request body")
		return
	}
	if strings.TrimSpace(req.Token) == "" {
		errorResponse(w, http.StatusBadRequest, "token is required")
		return
	}
	conn, err := h.svc.Connect(r.Context(), userID, strings.TrimSpace(req.Token))
	if err != nil {
		if service.IsMissingScopeError(err) {
			errorResponse(w, http.StatusBadRequest, "token must include scope admin:repo_hook (for webhook auto-sync)")
			return
		}
		errorResponse(w, http.StatusBadRequest, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, conn)
}

// Status returns connection metadata, or {"connected": false}.
func (h *GitHubHandler) Status(w http.ResponseWriter, r *http.Request) {
	userID := resolveUserID(r)
	if userID == "" {
		errorResponse(w, http.StatusUnauthorized, "authentication required")
		return
	}
	conn, err := h.svc.Status(r.Context(), userID)
	if err != nil {
		errorResponse(w, http.StatusInternalServerError, err.Error())
		return
	}
	if conn == nil {
		writeJSON(w, http.StatusOK, map[string]any{"connected": false})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"connected": true, "connection": conn})
}

// Disconnect deletes the caller's connection.
func (h *GitHubHandler) Disconnect(w http.ResponseWriter, r *http.Request) {
	userID := resolveUserID(r)
	if userID == "" {
		errorResponse(w, http.StatusUnauthorized, "authentication required")
		return
	}
	if err := h.svc.Disconnect(r.Context(), userID); err != nil {
		errorResponse(w, http.StatusInternalServerError, err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// Repos lists repos accessible to the caller's token.
func (h *GitHubHandler) Repos(w http.ResponseWriter, r *http.Request) {
	userID := resolveUserID(r)
	if userID == "" {
		errorResponse(w, http.StatusUnauthorized, "authentication required")
		return
	}
	repos, err := h.svc.ListRepos(r.Context(), userID)
	if err != nil {
		errorResponse(w, http.StatusBadGateway, "failed to list GitHub repos: "+err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"repos": repos})
}
```

> **Verified against codebase:** `resolveUserID(r)` already exists in `internal/handler/project.go` (returns the authenticated user UUID, or "" when there is no user — e.g. developer/API-key auth without a bound user). Reuse it; do NOT add a `currentUserID` duplicate. `writeJSON(w, status, v)` already exists in `internal/handler/document.go:150` and `errorResponse` is package-wide — reuse both. Drop the `middleware` import from this file if `resolveUserID` makes it unused.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestGitHubHandler_Connect`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.go/internal/handler/github.go ennam.kg.go/internal/handler/github_test.go
git commit -m "feat(github): per-user connection HTTP handler"
```

---

## Phase 3 — Go: per-project repo sources + queue message

### Task 7: Extend `queue.IndexMessage` with clone fields

**Files:**
- Modify: `ennam.kg.go/internal/queue/publisher.go:29-35`

- [ ] **Step 1: Add the two fields** to the `IndexMessage` struct

```go
// IndexMessage is the payload sent to the indexing queue.
type IndexMessage struct {
	Type        MessageType `json:"type"`
	ProjectID   string      `json:"project_id"`
	RepoPath    string      `json:"repo_path,omitempty"`
	RepoURL     string      `json:"repo_url,omitempty"`     // NEW: GitHub HTTPS clone URL
	GitHubToken string      `json:"github_token,omitempty"` // NEW: decrypted token for private clone
	Files       []string    `json:"files,omitempty"`
	Timestamp   time.Time   `json:"timestamp"`
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd ennam.kg.go && go build ./...`
Expected: builds clean (new fields are additive; existing publishers unaffected).

- [ ] **Step 3: Commit**

```bash
git add ennam.kg.go/internal/queue/publisher.go
git commit -m "feat(queue): add repo_url and github_token to IndexMessage"
```

### Task 8: GitHub source service (add/remove repo + webhook + publish index)

**Files:**
- Create: `ennam.kg.go/internal/service/github_source.go`
- Test: `ennam.kg.go/internal/service/github_source_test.go`

This service depends on: the `GitHubConnectionStore` (to get the token), the `github.Client` (to register/delete webhooks), the existing `SourceConnectionService`/store (to persist the `github_repo` row), and the `queue.Publisher` (to trigger the first index). Define a small interface for the source-connection store dependency so the service stays testable.

- [ ] **Step 1: Write the failing test** — verifies AddRepo publishes an `index_project` message carrying `RepoURL` + token

```go
package service_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/ennam/ennam-kg/internal/github"
	"github.com/ennam/ennam-kg/internal/queue"
	"github.com/ennam/ennam-kg/internal/service"
)

type capturePublisher struct{ last queue.IndexMessage }

func (c *capturePublisher) Publish(_ context.Context, m queue.IndexMessage) error { c.last = m; return nil }
func (c *capturePublisher) Close() error                                          { return nil }

func TestGitHubSourceService_AddRepo_PublishesCloneIndex(t *testing.T) {
	gh := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// CreateWebhook → return an id
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{"id":99}`))
	}))
	defer gh.Close()

	pub := &capturePublisher{}
	fakeStore := service.NewFakeGitHubSourceStore() // test double defined alongside the service
	tokens := service.NewStaticTokenProvider("ghp_secret")
	svc := service.NewGitHubSourceService(fakeStore, github.NewClient(gh.URL), tokens, pub, "https://kg.example.com", nil)

	conn, err := svc.AddRepo(context.Background(), service.AddRepoInput{
		ProjectID: "proj-1", UserID: "user-1",
		Owner: "exnodes", Repo: "kg", FullName: "exnodes/kg", DefaultBranch: "main", Private: true,
	})
	if err != nil {
		t.Fatalf("AddRepo: %v", err)
	}
	_ = conn
	if pub.last.Type != queue.MsgIndexProject {
		t.Errorf("published type = %q, want index_project", pub.last.Type)
	}
	if pub.last.RepoURL != "https://github.com/exnodes/kg.git" {
		t.Errorf("RepoURL = %q", pub.last.RepoURL)
	}
	if pub.last.GitHubToken != "ghp_secret" {
		t.Errorf("token not passed to worker")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/service/ -run TestGitHubSourceService_AddRepo`
Expected: FAIL — undefined `NewGitHubSourceService` / `NewFakeGitHubSourceStore` / `NewStaticTokenProvider`.

- [ ] **Step 3: Write the service + its small interfaces and test doubles**

```go
package service

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/ennam/ennam-kg/internal/github"
	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/queue"
)

// githubSourceStore is the subset of source-connection persistence this service needs.
// GetByID/Delete take (projectID, id) to match the existing *store.SourceConnectionStore signatures.
type githubSourceStore interface {
	CreateGitHubRepo(ctx context.Context, projectID, createdBy, displayName string, config json.RawMessage, webhookSecret string) (*models.SourceConnection, error)
	GetByID(ctx context.Context, projectID, id string) (*models.SourceConnection, error)
	ListGitHubByProject(ctx context.Context, projectID string) ([]models.SourceConnection, error)
	Delete(ctx context.Context, projectID, id string) error
}

// tokenProvider resolves a user's decrypted GitHub token.
type tokenProvider interface {
	GetToken(ctx context.Context, userID string) (string, error)
}

// GitHubSourceService manages github_repo source connections for a project.
type GitHubSourceService struct {
	store       githubSourceStore
	client      *github.Client
	tokens      tokenProvider
	pub         queue.Publisher
	callbackURL string // base URL of this server, e.g. https://kg.example.com
	logger      *slog.Logger
}

// NewGitHubSourceService wires dependencies. callbackBase is the public origin used to build the webhook URL.
func NewGitHubSourceService(store githubSourceStore, client *github.Client, tokens tokenProvider, pub queue.Publisher, callbackBase string, logger *slog.Logger) *GitHubSourceService {
	return &GitHubSourceService{store: store, client: client, tokens: tokens, pub: pub, callbackURL: callbackBase, logger: logger}
}

// AddRepoInput describes a repo the user selected to connect.
type AddRepoInput struct {
	ProjectID     string
	UserID        string
	Owner         string
	Repo          string
	FullName      string
	DefaultBranch string
	Private       bool
}

// repoConfig is the JSONB stored in source_connections.config for a github_repo.
type repoConfig struct {
	Owner         string `json:"owner"`
	Repo          string `json:"repo"`
	FullName      string `json:"full_name"`
	DefaultBranch string `json:"default_branch"`
	Private       bool   `json:"private"`
	WebhookID     int64  `json:"webhook_id"`
}

// AddRepo creates the source row, registers a push webhook, and triggers the first index.
func (s *GitHubSourceService) AddRepo(ctx context.Context, in AddRepoInput) (*models.SourceConnection, error) {
	token, err := s.tokens.GetToken(ctx, in.UserID)
	if err != nil {
		return nil, fmt.Errorf("resolve token: %w", err)
	}
	secret, err := randomSecret()
	if err != nil {
		return nil, err
	}
	hookID, err := s.client.CreateWebhook(ctx, token, in.Owner, in.Repo, s.callbackURL+"/webhooks/github", secret)
	if err != nil {
		return nil, fmt.Errorf("register webhook: %w", err)
	}
	cfg, _ := json.Marshal(repoConfig{
		Owner: in.Owner, Repo: in.Repo, FullName: in.FullName,
		DefaultBranch: in.DefaultBranch, Private: in.Private, WebhookID: hookID,
	})
	conn, err := s.store.CreateGitHubRepo(ctx, in.ProjectID, in.UserID, in.FullName, cfg, secret)
	if err != nil {
		// Best-effort rollback of the webhook we just created.
		_ = s.client.DeleteWebhook(ctx, token, in.Owner, in.Repo, hookID)
		return nil, fmt.Errorf("create source connection: %w", err)
	}
	if err := s.publishIndex(ctx, in.ProjectID, in.FullName, token); err != nil {
		s.logger.Warn("github source created but index publish failed", "project", in.ProjectID, "repo", in.FullName, "error", err)
	}
	return conn, nil
}

// RemoveRepo deletes the webhook on GitHub then the source row. The webhook is deleted using the
// CONNECTION OWNER's token (config/created_by), not the caller's — a teammate who never connected
// GitHub must still be able to remove a repo.
func (s *GitHubSourceService) RemoveRepo(ctx context.Context, projectID, connID string) error {
	conn, err := s.store.GetByID(ctx, projectID, connID)
	if err != nil {
		return fmt.Errorf("load connection: %w", err)
	}
	var cfg repoConfig
	_ = json.Unmarshal(conn.Config, &cfg)
	token, tokErr := s.tokens.GetToken(ctx, conn.CreatedBy) // owner's token
	if tokErr == nil && cfg.WebhookID != 0 {
		if delErr := s.client.DeleteWebhook(ctx, token, cfg.Owner, cfg.Repo, cfg.WebhookID); delErr != nil {
			s.logger.Warn("failed to delete webhook (continuing)", "repo", cfg.FullName, "error", delErr)
		}
	}
	return s.store.Delete(ctx, projectID, connID)
}

// List returns the project's github_repo connections.
func (s *GitHubSourceService) List(ctx context.Context, projectID string) ([]models.SourceConnection, error) {
	return s.store.ListGitHubByProject(ctx, projectID)
}

// Sync re-indexes one connected repo, cloning with the CONNECTION OWNER's token (not the caller's).
func (s *GitHubSourceService) Sync(ctx context.Context, projectID, connID string) error {
	conn, err := s.store.GetByID(ctx, projectID, connID)
	if err != nil {
		return fmt.Errorf("load connection: %w", err)
	}
	var cfg repoConfig
	_ = json.Unmarshal(conn.Config, &cfg)
	token, err := s.tokens.GetToken(ctx, conn.CreatedBy)
	if err != nil {
		return fmt.Errorf("resolve owner token: %w", err)
	}
	return s.publishIndex(ctx, projectID, cfg.FullName, token)
}

func (s *GitHubSourceService) publishIndex(ctx context.Context, projectID, fullName, token string) error {
	return s.pub.Publish(ctx, queue.IndexMessage{
		Type:        queue.MsgIndexProject,
		ProjectID:   projectID,
		RepoURL:     "https://github.com/" + fullName + ".git",
		GitHubToken: token,
		Timestamp:   time.Now(),
	})
}

func randomSecret() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", fmt.Errorf("generate webhook secret: %w", err)
	}
	return hex.EncodeToString(b), nil
}
```

- [ ] **Step 4: Add test doubles** in `ennam.kg.go/internal/service/github_source_test_doubles.go` (kept in the non-test package so the test can reference exported constructors; acceptable for this codebase's existing test-helper style — if the repo prefers `_test.go`-only doubles, move them there)

```go
package service

import (
	"context"
	"encoding/json"

	"github.com/ennam/ennam-kg/internal/models"
)

// fakeGitHubSourceStore is an in-memory githubSourceStore for tests.
type fakeGitHubSourceStore struct{ rows map[string]*models.SourceConnection }

// NewFakeGitHubSourceStore returns an in-memory store usable as a githubSourceStore.
func NewFakeGitHubSourceStore() *fakeGitHubSourceStore { return &fakeGitHubSourceStore{rows: map[string]*models.SourceConnection{}} }

func (f *fakeGitHubSourceStore) CreateGitHubRepo(_ context.Context, projectID, createdBy, displayName string, config json.RawMessage, _ string) (*models.SourceConnection, error) {
	c := &models.SourceConnection{ID: "conn-" + displayName, ProjectID: projectID, SourceType: models.DraftSourceGitHubRepo, DisplayName: displayName, Config: config, CreatedBy: createdBy, Status: models.ConnectionStatusConnected}
	f.rows[c.ID] = c
	return c, nil
}
func (f *fakeGitHubSourceStore) GetByID(_ context.Context, _ , id string) (*models.SourceConnection, error) { return f.rows[id], nil }
func (f *fakeGitHubSourceStore) ListGitHubByProject(_ context.Context, projectID string) ([]models.SourceConnection, error) {
	var out []models.SourceConnection
	for _, c := range f.rows {
		if c.ProjectID == projectID {
			out = append(out, *c)
		}
	}
	return out, nil
}
func (f *fakeGitHubSourceStore) Delete(_ context.Context, _, id string) error { delete(f.rows, id); return nil }

// staticTokenProvider always returns the same token.
type staticTokenProvider struct{ token string }

// NewStaticTokenProvider returns a tokenProvider yielding the given token for any user.
func NewStaticTokenProvider(token string) *staticTokenProvider { return &staticTokenProvider{token: token} }
func (s *staticTokenProvider) GetToken(_ context.Context, _ string) (string, error)  { return s.token, nil }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/service/ -run TestGitHubSourceService_AddRepo`
Expected: PASS.

- [ ] **Step 6: Implement the real store methods** on the existing `SourceConnectionStore` (file `ennam.kg.go/internal/store/source_connection.go`). Add `CreateGitHubRepo`, `ListGitHubByProject` if not present; reuse existing `GetByID`/`Delete` if they already exist (check first — the handler at `source_connection.go` implies CRUD exists). `CreateGitHubRepo` inserts a row with `source_type='github_repo'`, the JSONB config, `webhook_secret`, `status='connected'`. Mirror the existing insert in this file.

```go
// CreateGitHubRepo inserts a github_repo source connection. Mirrors the existing Create, with fixed source_type.
func (s *SourceConnectionStore) CreateGitHubRepo(ctx context.Context, projectID, createdBy, displayName string, config json.RawMessage, webhookSecret string) (*models.SourceConnection, error) {
	const q = `
		INSERT INTO source_connections (project_id, source_type, display_name, config, webhook_secret, status, created_by)
		VALUES ($1, 'github_repo', $2, $3, $4, 'connected', $5)
		RETURNING id, project_id, source_type, display_name, config, webhook_secret, status, created_by, created_at, updated_at`
	var c models.SourceConnection
	err := s.db.QueryRowContext(ctx, q, projectID, displayName, config, webhookSecret, createdBy).Scan(
		&c.ID, &c.ProjectID, &c.SourceType, &c.DisplayName, &c.Config, &c.WebhookSecret, &c.Status, &c.CreatedBy, &c.CreatedAt, &c.UpdatedAt)
	if err != nil {
		return nil, fmt.Errorf("create github_repo connection: %w", err)
	}
	return &c, nil
}

// ListGitHubByProject returns all github_repo connections for a project.
func (s *SourceConnectionStore) ListGitHubByProject(ctx context.Context, projectID string) ([]models.SourceConnection, error) {
	return s.scanGitHubList(ctx, `
		SELECT id, project_id, source_type, display_name, config, status, last_synced_at, created_by, created_at, updated_at
		FROM source_connections WHERE project_id = $1 AND source_type = 'github_repo' ORDER BY created_at`, projectID)
}

// ListGitHubByCreatedBy returns all github_repo connections created by a user (across all projects).
// Used by Disconnect to clean up every webhook the user registered before deleting their token.
func (s *SourceConnectionStore) ListGitHubByCreatedBy(ctx context.Context, userID string) ([]models.SourceConnection, error) {
	return s.scanGitHubList(ctx, `
		SELECT id, project_id, source_type, display_name, config, status, last_synced_at, created_by, created_at, updated_at
		FROM source_connections WHERE created_by = $1 AND source_type = 'github_repo' ORDER BY created_at`, userID)
}

func (s *SourceConnectionStore) scanGitHubList(ctx context.Context, q, arg string) ([]models.SourceConnection, error) {
	rows, err := s.db.QueryContext(ctx, q, arg)
	if err != nil {
		return nil, fmt.Errorf("list github connections: %w", err)
	}
	defer func() { _ = rows.Close() }()
	var out []models.SourceConnection
	for rows.Next() {
		var c models.SourceConnection
		if err := rows.Scan(&c.ID, &c.ProjectID, &c.SourceType, &c.DisplayName, &c.Config, &c.Status, &c.LastSyncedAt, &c.CreatedBy, &c.CreatedAt, &c.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}
```

- [ ] **Step 7: Run the full service + store packages**

Run: `cd ennam.kg.go && go build ./... && go test ./internal/service/ ./internal/store/`
Expected: builds; tests PASS (DB-backed store tests SKIP without `KG_TEST_DATABASE_URL`).

- [ ] **Step 8: Commit**

```bash
git add ennam.kg.go/internal/service/github_source.go ennam.kg.go/internal/service/github_source_test.go ennam.kg.go/internal/service/github_source_test_doubles.go ennam.kg.go/internal/store/source_connection.go
git commit -m "feat(github): per-project repo source service with webhook + index publish"
```

### Task 9: Per-project HTTP handler `/api/v1/projects/{id}/github-sources`

**Files:**
- Create: `ennam.kg.go/internal/handler/github_source.go`
- Test: `ennam.kg.go/internal/handler/github_source_test.go`

- [ ] **Step 1: Write the failing test** — a request with no project access is rejected with 403 BEFORE any body parsing. This encodes the security gate (the most important behavior of this handler).

```go
package handler_test

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/handler"
)

func TestGitHubSourceHandler_Add_NoProjectAccess_Returns403(t *testing.T) {
	h := handler.NewGitHubSourceHandler(nil, nil)
	mux := http.NewServeMux()
	h.RegisterRoutes(mux)

	// No identity in context and not a global admin → access denied, even before JSON is read.
	req := httptest.NewRequest(http.MethodPost, "/api/v1/projects/p1/github-sources", strings.NewReader("{bad"))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Errorf("status = %d, want 403", rec.Code)
	}
}
```

> The happy-path (valid access → AddRepo) is exercised end-to-end in Task 18; unit-testing it here would require constructing a real `GitHubSourceService` with stubs, which the service-layer test in Task 8 already covers.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestGitHubSourceHandler`
Expected: FAIL — `handler.NewGitHubSourceHandler` undefined.

- [ ] **Step 3: Write the handler**

```go
package handler

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/service"
)

// GitHubSourceHandler serves per-project github_repo source endpoints.
type GitHubSourceHandler struct {
	svc    *service.GitHubSourceService
	logger *slog.Logger
}

// NewGitHubSourceHandler constructs the handler.
func NewGitHubSourceHandler(svc *service.GitHubSourceService, logger *slog.Logger) *GitHubSourceHandler {
	return &GitHubSourceHandler{svc: svc, logger: logger}
}

// RegisterRoutes registers per-project GitHub source routes.
func (h *GitHubSourceHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/projects/{id}/github-sources", h.List)
	mux.HandleFunc("POST /api/v1/projects/{id}/github-sources", h.Add)
	mux.HandleFunc("DELETE /api/v1/projects/{id}/github-sources/{connId}", h.Remove)
	mux.HandleFunc("POST /api/v1/projects/{id}/github-sources/{connId}/sync", h.Sync)
}

// requireProjectAccess mirrors HandleTriggerIndex (project.go): global admins pass; otherwise the
// developer identity must have access to the project. Returns false (and writes 403) when denied.
// These endpoints register/delete GitHub webhooks and trigger indexing, so they MUST be gated —
// unlike the looser generic connections handler.
func requireProjectAccess(w http.ResponseWriter, r *http.Request, projectID string) bool {
	if isGlobalAdmin(r) {
		return true
	}
	identity := middleware.GetDeveloperIdentity(r.Context())
	if identity == nil || !identity.HasProjectAccess(projectID) {
		errorResponse(w, http.StatusForbidden, "access denied for this project")
		return false
	}
	return true
}

type addGitHubSourceRequest struct {
	Owner         string `json:"owner"`
	Repo          string `json:"repo"`
	FullName      string `json:"full_name"`
	DefaultBranch string `json:"default_branch"`
	Private       bool   `json:"private"`
}

// Add connects one repo to the project.
func (h *GitHubSourceHandler) Add(w http.ResponseWriter, r *http.Request) {
	projectID := r.PathValue("id")
	if !requireProjectAccess(w, r, projectID) {
		return
	}
	userID := resolveUserID(r)
	if userID == "" {
		errorResponse(w, http.StatusUnauthorized, "a user-bound session is required to connect a repo")
		return
	}
	var req addGitHubSourceRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid JSON request body")
		return
	}
	if req.FullName == "" || req.Owner == "" || req.Repo == "" {
		errorResponse(w, http.StatusBadRequest, "owner, repo, and full_name are required")
		return
	}
	conn, err := h.svc.AddRepo(r.Context(), service.AddRepoInput{
		ProjectID: projectID, UserID: userID,
		Owner: req.Owner, Repo: req.Repo, FullName: req.FullName,
		DefaultBranch: req.DefaultBranch, Private: req.Private,
	})
	if err != nil {
		errorResponse(w, http.StatusBadGateway, "failed to add repo: "+err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, conn)
}

// List returns the project's connected repos.
func (h *GitHubSourceHandler) List(w http.ResponseWriter, r *http.Request) {
	projectID := r.PathValue("id")
	if !requireProjectAccess(w, r, projectID) {
		return
	}
	conns, err := h.svc.List(r.Context(), projectID)
	if err != nil {
		errorResponse(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"sources": conns})
}

// Remove disconnects a repo (deletes webhook + row) using the connection owner's token.
func (h *GitHubSourceHandler) Remove(w http.ResponseWriter, r *http.Request) {
	projectID := r.PathValue("id")
	if !requireProjectAccess(w, r, projectID) {
		return
	}
	if err := h.svc.RemoveRepo(r.Context(), projectID, r.PathValue("connId")); err != nil {
		errorResponse(w, http.StatusInternalServerError, err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// Sync triggers a manual re-index of one connected repo (clones with the owner's token).
func (h *GitHubSourceHandler) Sync(w http.ResponseWriter, r *http.Request) {
	projectID := r.PathValue("id")
	if !requireProjectAccess(w, r, projectID) {
		return
	}
	if err := h.svc.Sync(r.Context(), projectID, r.PathValue("connId")); err != nil {
		errorResponse(w, http.StatusBadGateway, err.Error())
		return
	}
	w.WriteHeader(http.StatusAccepted)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestGitHubSourceHandler`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.go/internal/handler/github_source.go ennam.kg.go/internal/handler/github_source_test.go
git commit -m "feat(github): per-project github-sources HTTP handler"
```

---

## Phase 4 — Go: webhook receiver

### Task 10: `POST /webhooks/github` (unauthenticated, HMAC-verified)

**Files:**
- Create: `ennam.kg.go/internal/handler/github_webhook.go`
- Test: `ennam.kg.go/internal/handler/github_webhook_test.go`

The receiver verifies the `X-Hub-Signature-256` HMAC against the stored `webhook_secret`, looks up the `source_connections` row by repo `full_name`, and publishes an `index_project`. It needs a store lookup by full_name that returns `(projectID, webhookSecret, createdBy)`.

- [ ] **Step 1: Write the failing test** — valid signature → 202, bad signature → 401

```go
package handler_test

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/handler"
)

func sign(secret, body string) string {
	m := hmac.New(sha256.New, []byte(secret))
	_, _ = m.Write([]byte(body))
	return "sha256=" + hex.EncodeToString(m.Sum(nil))
}

func TestGitHubWebhook_BadSignature_Returns401(t *testing.T) {
	lookup := handler.WebhookLookupFunc(func(_ string) (handler.WebhookTarget, bool) {
		return handler.WebhookTarget{ProjectID: "p1", Secret: "topsecret", UserID: "u1"}, true
	})
	// tokens=nil and pub=nil are safe here: a bad signature is rejected before either is used.
	h := handler.NewGitHubWebhookHandler(lookup, nil, nil, nil)
	mux := http.NewServeMux()
	h.RegisterRoutes(mux)

	body := `{"repository":{"full_name":"exnodes/kg"}}`
	req := httptest.NewRequest(http.MethodPost, "/webhooks/github", strings.NewReader(body))
	req.Header.Set("X-GitHub-Event", "push")
	req.Header.Set("X-Hub-Signature-256", sign("WRONG", body))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("status = %d, want 401", rec.Code)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestGitHubWebhook`
Expected: FAIL — undefined symbols.

- [ ] **Step 3: Write the handler**

```go
package handler

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/ennam/ennam-kg/internal/queue"
)

// WebhookTarget is the resolved routing info for an incoming push.
type WebhookTarget struct {
	ProjectID string
	Secret    string
	UserID    string // owner of the connection; used to resolve the clone token
}

// WebhookLookupFunc resolves a repo full_name to its WebhookTarget.
type WebhookLookupFunc func(fullName string) (WebhookTarget, bool)

// webhookTokens resolves a user's decrypted GitHub token. Satisfied by *store.GitHubConnectionStore.
type webhookTokens interface {
	GetToken(ctx context.Context, userID string) (string, error)
}

// GitHubWebhookHandler receives GitHub push events.
type GitHubWebhookHandler struct {
	lookup WebhookLookupFunc
	tokens webhookTokens
	pub    queue.Publisher
	logger *slog.Logger
}

// NewGitHubWebhookHandler constructs the handler. lookup resolves repo→target; tokens resolves the
// owner's clone token; pub queues the re-index.
func NewGitHubWebhookHandler(lookup WebhookLookupFunc, tokens webhookTokens, pub queue.Publisher, logger *slog.Logger) *GitHubWebhookHandler {
	return &GitHubWebhookHandler{lookup: lookup, tokens: tokens, pub: pub, logger: logger}
}

// RegisterRoutes registers the unauthenticated webhook route. Mount on the ROOT mux, not the API mux.
func (h *GitHubWebhookHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /webhooks/github", h.Receive)
}

type pushPayload struct {
	Repository struct {
		FullName string `json:"full_name"`
	} `json:"repository"`
}

// Receive verifies the HMAC signature and queues a re-index.
func (h *GitHubWebhookHandler) Receive(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20)) // cap at 1 MiB
	if err != nil {
		errorResponse(w, http.StatusBadRequest, "cannot read body")
		return
	}
	var payload pushPayload
	if err := json.Unmarshal(body, &payload); err != nil || payload.Repository.FullName == "" {
		errorResponse(w, http.StatusBadRequest, "invalid push payload")
		return
	}
	target, ok := h.lookup(payload.Repository.FullName)
	if !ok {
		// Unknown repo — return 202 so GitHub doesn't retry forever; nothing to do.
		w.WriteHeader(http.StatusAccepted)
		return
	}
	if !validSignature(target.Secret, body, r.Header.Get("X-Hub-Signature-256")) {
		errorResponse(w, http.StatusUnauthorized, "invalid signature")
		return
	}
	// Resolve the connection owner's token so the worker can clone a private repo.
	token, err := h.tokens.GetToken(r.Context(), target.UserID)
	if err != nil {
		h.logger.Error("webhook: cannot resolve owner token", "repo", payload.Repository.FullName, "error", err)
		errorResponse(w, http.StatusInternalServerError, "owner token unavailable")
		return
	}
	if err := h.pub.Publish(r.Context(), queue.IndexMessage{
		Type:        queue.MsgIndexProject,
		ProjectID:   target.ProjectID,
		RepoURL:     "https://github.com/" + payload.Repository.FullName + ".git",
		GitHubToken: token,
		Timestamp:   time.Now(),
	}); err != nil {
		h.logger.Error("webhook index publish failed", "repo", payload.Repository.FullName, "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to queue index")
		return
	}
	w.WriteHeader(http.StatusAccepted)
}

// validSignature checks the GitHub HMAC-SHA256 signature header against the body.
func validSignature(secret string, body []byte, header string) bool {
	if secret == "" || header == "" {
		return false
	}
	m := hmac.New(sha256.New, []byte(secret))
	_, _ = m.Write(body)
	expected := "sha256=" + hex.EncodeToString(m.Sum(nil))
	return hmac.Equal([]byte(expected), []byte(header))
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestGitHubWebhook`
Expected: PASS (the bad-signature test never reaches token resolution, so `tokens=nil` is fine).

- [ ] **Step 5: Add the store lookup** `FindGitHubByFullName(ctx, fullName) (projectID, secret, createdBy string, ok bool, err error)` on `SourceConnectionStore` (query `WHERE source_type='github_repo' AND config->>'full_name' = $1`). Wire it into a `WebhookLookupFunc` in main.go (Task 11).

```go
// FindGitHubByFullName resolves a repo full_name to its project, webhook secret, and owner.
func (s *SourceConnectionStore) FindGitHubByFullName(ctx context.Context, fullName string) (projectID, secret, createdBy string, ok bool, err error) {
	const q = `
		SELECT project_id, COALESCE(webhook_secret,''), created_by
		FROM source_connections
		WHERE source_type='github_repo' AND config->>'full_name' = $1
		LIMIT 1`
	err = s.db.QueryRowContext(ctx, q, fullName).Scan(&projectID, &secret, &createdBy)
	if err == sql.ErrNoRows {
		return "", "", "", false, nil
	}
	if err != nil {
		return "", "", "", false, fmt.Errorf("find github by full_name: %w", err)
	}
	return projectID, secret, createdBy, true, nil
}
```

- [ ] **Step 6: Commit**

```bash
git add ennam.kg.go/internal/handler/github_webhook.go ennam.kg.go/internal/handler/github_webhook_test.go ennam.kg.go/internal/store/source_connection.go
git commit -m "feat(github): HMAC-verified push webhook receiver"
```

### Task 11: Wire handlers in `main.go`

**Files:**
- Modify: `ennam.kg.go/cmd/kg-server/main.go` (near the existing `connHandler` wiring ~line 543, and wherever the root/unauthenticated mux is built for the webhook)

- [ ] **Step 1: Construct stores/services/handlers** AFTER `connStore := store.NewSourceConnectionStore(db)` (line ~523, where `connStore` and `pub` are already in scope) and guard the whole block with `if encKey != nil` — `encKey` is function-scoped (declared `var encKey []byte` at line 378) but is nil when `KG_ENCRYPTION_KEY` is unset, exactly like the `oauthTokenStore` block at line 717.

```go
	// GitHub integration — token encryption requires KG_ENCRYPTION_KEY. Skip entirely if unset.
	if encKey != nil {
	ghConnStore := store.NewGitHubConnectionStore(db, encKey)
	ghClient := github.NewClient(github.DefaultBaseURL)
	// connStore (existing *store.SourceConnectionStore) satisfies githubUserSourceStore for webhook cleanup on disconnect.
	ghService := service.NewGitHubService(ghConnStore, connStore, ghClient, logger)
	ghHandler := handler.NewGitHubHandler(ghService, logger)
	ghHandler.RegisterRoutes(apiMux)

	callbackBase := os.Getenv("KG_PUBLIC_URL") // e.g. https://kg.example.com
	ghSourceService := service.NewGitHubSourceService(connStore, ghClient, ghConnStore, pub, callbackBase, logger)
	ghSourceHandler := handler.NewGitHubSourceHandler(ghSourceService, logger)
	ghSourceHandler.RegisterRoutes(apiMux)

	// Webhook receiver — UNAUTHENTICATED, mount on the root mux (not apiMux which has auth middleware).
	lookup := handler.WebhookLookupFunc(func(fullName string) (handler.WebhookTarget, bool) {
		projectID, secret, createdBy, ok, err := connStore.FindGitHubByFullName(context.Background(), fullName)
		if err != nil || !ok {
			return handler.WebhookTarget{}, false
		}
		return handler.WebhookTarget{ProjectID: projectID, Secret: secret, UserID: createdBy}, true
	})
	ghWebhookHandler := handler.NewGitHubWebhookHandler(lookup, ghConnStore, pub, logger) // ghConnStore satisfies webhookTokens via GetToken
	ghWebhookHandler.RegisterRoutes(rootMux) // rootMux = the server mux without auth middleware
	} // end if encKey != nil
```

> **Implementer notes:**
> - `connStore` is the existing `*store.SourceConnectionStore` already constructed at line 523 for `connHandler` (reuse it; don't build a second). It satisfies BOTH `githubSourceStore` (Task 8) and `githubUserSourceStore` (Task 5) once `CreateGitHubRepo`, `ListGitHubByProject`, `ListGitHubByCreatedBy`, and `FindGitHubByFullName` are added — its existing `GetByID(projectID,id)`/`Delete(projectID,id)` already match the interfaces.
> - `pub` is the existing `queue.Publisher`; `encKey` is the function-scoped key from line 378.
> - `ghConnStore.GetToken` has signature `(ctx, userID)` — it satisfies both `tokenProvider` (Task 8) and `webhookTokens` (Task 10).
> - **Unauthenticated webhook mux:** confirm the name of the raw/root mux. The webhook MUST bypass auth middleware. Mirror the existing unauthenticated precedent — grep how `publicIngestHandler` (line ~546) is mounted; if it registers on the same `apiMux` that is wrapped by auth, then `/webhooks/github` instead needs the auth middleware's public-path allowlist to include it (check `internal/middleware` for the allowlist). Do NOT invent a new mux; follow whatever makes `publicIngest` public today.
> - **Note (existing latent issue, do not "fix" here):** the generic `SourceConnectionHandler.Create` defaults `created_by` to the string `"system"` when no user is bound, which would violate the `created_by UUID REFERENCES users(id)` FK. The GitHub path avoids this by requiring a real `resolveUserID` (401 otherwise). Flag it for the connections owner; out of scope for this plan.

- [ ] **Step 2: Verify build**

Run: `cd ennam.kg.go && go build ./... && make lint`
Expected: builds clean, lint passes.

- [ ] **Step 3: Smoke test the routes** with the stack up

Run:
```bash
docker compose up -d --build kg-server
curl -s -X GET http://localhost:8080/api/v1/github/status -H "Authorization: Bearer $DEV_API_KEY" | jq .
```
Expected: `{"connected": false}` (200) for a user with no connection.

- [ ] **Step 4: Commit**

```bash
git add ennam.kg.go/cmd/kg-server/main.go
git commit -m "feat(github): wire connection, source, and webhook handlers"
```

---

## Phase 5 — Python worker: clone pipeline

### Task 12a: Stable repo-relative file paths (BLOCKER — confirm with product owner first)

**Why:** The indexer's natural key is `file_path:name:kind` and `extractor` stores `file_path` as the absolute path. Clone-based indexing uses a random temp dir each run, so keys would never match across re-indexes → duplicate nodes + stale nodes never archived. Fix: store `file_path` **relative to `repo_path`** so keys are stable wherever the repo is checked out. This also normalizes the existing Docker-mount flow (paths become e.g. `src/foo.py` instead of `/repos/ennam-kg-go/src/foo.py`), so **existing indexed projects need a one-time re-index** — get explicit sign-off before implementing.

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/indexer/extractor.py` (the `symbol_to_node` payload + the edge-key builder method — both currently use `symbol.file_path` directly)
- Test: `ennam.kg.python/tests/indexer/test_extractor_relpath.py`

- [ ] **Step 1: Write the failing test** — same logical file indexed from two different roots yields the same stored `file_path`

```python
import os

from ennam_kg.indexer.extractor import Extractor
from ennam_kg.parsers.base import Symbol, SymbolKind


def _symbol(abs_path: str) -> Symbol:
    return Symbol(
        name="foo",
        kind=SymbolKind.FUNCTION,
        file_path=abs_path,
        line_start=1,
        line_end=2,
        # fill any other required Symbol fields with minimal valid values per base.py
    )


def test_file_path_is_repo_relative_and_root_independent():
    ext = Extractor()
    node_a = ext.symbol_to_node(_symbol("/tmp/ennam-kg-clone-AAA/src/foo.py"), "proj-1", "/tmp/ennam-kg-clone-AAA")
    node_b = ext.symbol_to_node(_symbol("/repos/ennam-kg-go/src/foo.py"), "proj-1", "/repos/ennam-kg-go")
    props_a = node_a["properties"]  # type: ignore[index]
    props_b = node_b["properties"]  # type: ignore[index]
    assert props_a["file_path"] == "src/foo.py"
    assert props_a["file_path"] == props_b["file_path"]  # identical key regardless of checkout root
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/indexer/test_extractor_relpath.py -v`
Expected: FAIL — stored `file_path` is the absolute path.

- [ ] **Step 3: Add a helper and apply it at both path-storing sites**

In `extractor.py`, add a module-level helper and use it everywhere `symbol.file_path` is written into a payload or used to build a natural key:

```python
import os


def _rel_path(file_path: str, repo_path: str) -> str:
    """Return file_path relative to repo_path (POSIX-style), root-independent for stable KG keys.

    Falls back to the original path if it is not under repo_path (defensive; should not happen
    in normal scans).
    """
    try:
        return os.path.relpath(file_path, repo_path).replace(os.sep, "/")
    except ValueError:
        return file_path
```

Then in `symbol_to_node`, replace `"file_path": symbol.file_path` with `"file_path": _rel_path(symbol.file_path, repo_path)`. In the edge-key builder method, build keys from `_rel_path(symbol.file_path, repo_path)` instead of `symbol.file_path` (confirm that method receives `repo_path`; if it does not, thread it through from the caller in `engine._process_files`). Keep the separate `"repo_path"` property as-is.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/indexer/test_extractor_relpath.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full indexer suite to catch key/edge regressions**

Run: `cd ennam.kg.python && uv run pytest tests/ -k "extractor or differ or engine or edge" -v`
Expected: PASS. If existing tests assert absolute `file_path`, update them to the relative form (this is the intended behavior change).

- [ ] **Step 6: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/indexer/extractor.py ennam.kg.python/tests/indexer/test_extractor_relpath.py
git commit -m "fix(indexer): store repo-relative file paths for stable keys across checkouts"
```

### Task 12: Add clone fields to `IndexProjectMessage`

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/queue/messages.py:7-16`

- [ ] **Step 1: Add the fields**

```python
class IndexProjectMessage(BaseModel):
    """Message to trigger full project indexing."""

    type: str  # "index_project"
    project_id: str
    repo_path: str = ""
    repo_url: str = ""       # NEW: GitHub HTTPS clone URL (when set, worker clones instead of using repo_path)
    github_token: str = ""   # NEW: decrypted token for private clone
    timestamp: str = ""
```

- [ ] **Step 2: Verify import**

Run: `cd ennam.kg.python && uv run python -c "from ennam_kg.queue.messages import IndexProjectMessage; print(IndexProjectMessage(type='index_project', project_id='p', repo_url='u').github_token)"`
Expected: prints empty string, no error.

- [ ] **Step 3: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/queue/messages.py
git commit -m "feat(worker): add repo_url and github_token to IndexProjectMessage"
```

### Task 13: `GitCloner` context manager

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/indexer/git_cloner.py`
- Test: `ennam.kg.python/tests/indexer/test_git_cloner.py`

- [ ] **Step 1: Write the failing test** — clones a local bare repo (no network), cleans up on exit

```python
import subprocess
from pathlib import Path

from ennam_kg.indexer.git_cloner import GitCloner


def _make_local_repo(tmp_path: Path) -> str:
    src = tmp_path / "origin"
    src.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=src, check=True)
    (src / "hello.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=src, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "add"], cwd=src, check=True)
    return str(src)


def test_git_cloner_clones_and_cleans_up(tmp_path):
    origin = _make_local_repo(tmp_path)
    cloned_path = None
    with GitCloner(origin, token="") as repo_path:
        cloned_path = repo_path
        assert (Path(repo_path) / "hello.py").exists()
    # After exit, temp dir is removed.
    assert not Path(cloned_path).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/indexer/test_git_cloner.py -v`
Expected: FAIL — module `ennam_kg.indexer.git_cloner` not found.

- [ ] **Step 3: Write `GitCloner`**

```python
"""Clone a GitHub repo to a temp dir for indexing, with guaranteed cleanup."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)


class GitCloner:
    """Context manager that shallow-clones a repo to a temp dir and removes it on exit.

    The token (if any) is embedded in the clone URL but NEVER logged: subprocess output is
    captured, and only the sanitized repo URL is logged.
    """

    def __init__(self, repo_url: str, token: str = "") -> None:
        self._repo_url = repo_url
        if token:
            # https://github.com/owner/repo.git -> https://x-access-token:TOKEN@github.com/...
            self._clone_url = repo_url.replace("https://", f"https://x-access-token:{token}@", 1)
        else:
            self._clone_url = repo_url
        self._tmp_dir: str | None = None

    def __enter__(self) -> str:
        self._tmp_dir = tempfile.mkdtemp(prefix="ennam-kg-clone-")
        logger.info("Cloning %s", self._repo_url)  # sanitized URL only, no token
        try:
            subprocess.run(
                ["git", "clone", "--depth=1", "--single-branch", self._clone_url, self._tmp_dir],
                check=True,
                capture_output=True,  # keeps the token-bearing URL out of logs
            )
        except subprocess.CalledProcessError as exc:
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None
            # stderr may echo the URL; scrub before re-raising.
            raise RuntimeError(f"git clone failed for {self._repo_url}") from exc
        return self._tmp_dir

    def __exit__(self, *_exc: object) -> None:
        if self._tmp_dir:
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/indexer/test_git_cloner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/indexer/git_cloner.py ennam.kg.python/tests/indexer/test_git_cloner.py
git commit -m "feat(worker): GitCloner context manager for temp clone + cleanup"
```

### Task 14: Worker dispatch — clone-then-scan branch

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/worker.py:104-116` (the `index_project` branch)

- [ ] **Step 1: Replace the `index_project` branch** to handle `repo_url`

```python
        if msg_type == "index_project":
            repo_url = msg.get("repo_url", "")
            if repo_url.strip():
                github_token = msg.get("github_token", "")
                logger.info("Starting full scan from GitHub clone: project=%s url=%s", project_id, repo_url)
                from ennam_kg.indexer.git_cloner import GitCloner

                with GitCloner(repo_url, github_token) as repo_path:
                    result = await engine.full_scan(project_id, repo_path)
            else:
                repo_path = msg.get("repo_path", "")
                if not repo_path.strip():
                    logger.warning("index_project skipped: repo_path and repo_url both empty (project=%s)", project_id)
                    return
                logger.info("Starting full scan: project=%s repo=%s", project_id, repo_path)
                result = await engine.full_scan(project_id, repo_path)
            logger.info(
                "Full scan done: %d files, %d symbols, %d created, %d updated",
                result.files_scanned,
                result.symbols_found,
                result.nodes_created,
                result.nodes_updated,
            )
```

- [ ] **Step 2: Verify the module imports and the worker still starts**

Run: `cd ennam.kg.python && uv run python -c "import ennam_kg.worker"` then `uv run ruff check src/ennam_kg/worker.py`
Expected: imports cleanly; ruff passes.

- [ ] **Step 3: Run the worker test suite**

Run: `cd ennam.kg.python && uv run pytest tests/ -k "worker or index" -v`
Expected: PASS (existing tests still green; the empty-path warning path is preserved).

- [ ] **Step 4: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/worker.py
git commit -m "feat(worker): clone GitHub repo before full_scan when repo_url is set"
```

---

## Phase 6 — NextJS UI

### Task 15: Types + API client + hooks

**Files:**
- Create: `ennam.kg.next/src/types/github.ts`
- Create: `ennam.kg.next/src/lib/api/github.ts`
- Create: `ennam.kg.next/src/hooks/use-github.ts`

- [ ] **Step 1: Write the types**

```ts
export interface GitHubRepo {
  name: string;
  full_name: string;
  private: boolean;
  description: string;
  default_branch: string;
  clone_url: string;
}

export interface GitHubConnection {
  github_username: string;
  scopes: string[];
  status: 'active' | 'revoked' | 'error';
  connected_at: string;
}

export interface GitHubStatusResponse {
  connected: boolean;
  connection?: GitHubConnection;
}

export interface GitHubSource {
  id: string;
  project_id: string;
  display_name: string;
  status: string;
  last_synced_at: string | null;
  config: { full_name: string; default_branch: string; private: boolean };
}
```

- [ ] **Step 2: Write the API client** (follow the existing `lib/api/client.ts` request helper; check its exported name and reuse it)

```ts
import { apiRequest } from './client'; // reuse the existing fetch wrapper; rename import if the project exports a different symbol
import type { GitHubRepo, GitHubSource, GitHubStatusResponse } from '@/types/github';

export const githubApi = {
  status: () => apiRequest<GitHubStatusResponse>('/api/v1/github/status'),
  connect: (token: string) =>
    apiRequest<GitHubStatusResponse>('/api/v1/github/connect', { method: 'POST', body: JSON.stringify({ token }) }),
  disconnect: () => apiRequest<void>('/api/v1/github/connect', { method: 'DELETE' }),
  repos: () => apiRequest<{ repos: GitHubRepo[] }>('/api/v1/github/repos'),
  listSources: (projectId: string) =>
    apiRequest<{ sources: GitHubSource[] }>(`/api/v1/projects/${projectId}/github-sources`),
  addSource: (projectId: string, repo: GitHubRepo) =>
    apiRequest<GitHubSource>(`/api/v1/projects/${projectId}/github-sources`, {
      method: 'POST',
      body: JSON.stringify({
        owner: repo.full_name.split('/')[0],
        repo: repo.name,
        full_name: repo.full_name,
        default_branch: repo.default_branch,
        private: repo.private,
      }),
    }),
  removeSource: (projectId: string, connId: string) =>
    apiRequest<void>(`/api/v1/projects/${projectId}/github-sources/${connId}`, { method: 'DELETE' }),
  syncSource: (projectId: string, connId: string) =>
    apiRequest<void>(`/api/v1/projects/${projectId}/github-sources/${connId}/sync`, { method: 'POST' }),
};
```

- [ ] **Step 3: Write the hooks** (mirror `hooks/use-api-keys.ts` TanStack Query patterns)

```ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { githubApi } from '@/lib/api/github';

export function useGitHubStatus() {
  return useQuery({ queryKey: ['github', 'status'], queryFn: githubApi.status });
}

export function useGitHubRepos(enabled: boolean) {
  return useQuery({ queryKey: ['github', 'repos'], queryFn: githubApi.repos, enabled });
}

export function useConnectGitHub() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (token: string) => githubApi.connect(token),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['github', 'status'] }),
  });
}

export function useDisconnectGitHub() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => githubApi.disconnect(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['github', 'status'] }),
  });
}

export function useGitHubSources(projectId: string) {
  return useQuery({ queryKey: ['github', 'sources', projectId], queryFn: () => githubApi.listSources(projectId) });
}

export function useAddGitHubSource(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (repo: Parameters<typeof githubApi.addSource>[1]) => githubApi.addSource(projectId, repo),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['github', 'sources', projectId] }),
  });
}

export function useRemoveGitHubSource(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (connId: string) => githubApi.removeSource(projectId, connId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['github', 'sources', projectId] }),
  });
}

export function useSyncGitHubSource(projectId: string) {
  return useMutation({ mutationFn: (connId: string) => githubApi.syncSource(projectId, connId) });
}
```

- [ ] **Step 4: Verify typecheck**

Run: `cd ennam.kg.next && npm run lint`
Expected: no type/lint errors (fix import names if `apiRequest`/`apiClient` differs).

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.next/src/types/github.ts ennam.kg.next/src/lib/api/github.ts ennam.kg.next/src/hooks/use-github.ts
git commit -m "feat(ui): GitHub API types, client, and hooks"
```

### Task 16: Settings — per-user PAT connect card + page

**Files:**
- Create: `ennam.kg.next/src/components/settings/GitHubConnect.tsx`
- Create: `ennam.kg.next/src/app/(dashboard)/settings/github/page.tsx`

- [ ] **Step 1: Write the connect card** (caption MUST state both scopes — this is the spec note we recorded)

```tsx
'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { useGitHubStatus, useConnectGitHub, useDisconnectGitHub } from '@/hooks/use-github';

export default function GitHubConnect() {
  const { data: status, isLoading } = useGitHubStatus();
  const connect = useConnectGitHub();
  const disconnect = useDisconnectGitHub();
  const [token, setToken] = useState('');

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  if (status?.connected && status.connection) {
    return (
      <div className="rounded-lg border p-4">
        <p className="font-medium">Connected as {status.connection.github_username}</p>
        <p className="text-sm text-muted-foreground">Scopes: {status.connection.scopes.join(', ')}</p>
        <Button variant="destructive" className="mt-3" onClick={() => disconnect.mutate()} disabled={disconnect.isPending}>
          Disconnect
        </Button>
      </div>
    );
  }

  return (
    <div className="rounded-lg border p-4 space-y-3">
      <label htmlFor="gh-pat" className="block text-sm font-medium">Personal Access Token</label>
      <input
        id="gh-pat"
        type="password"
        placeholder="ghp_…"
        value={token}
        onChange={(e) => setToken(e.target.value)}
        className="w-full rounded-md border px-3 py-2 text-sm"
      />
      <p className="text-xs text-muted-foreground">
        Create a token at github.com/settings/tokens with scope <code>repo, admin:repo_hook</code>.
        The <code>admin:repo_hook</code> scope is required so pushes auto-trigger re-indexing. Stored encrypted server-side.
      </p>
      {connect.isError && <p className="text-xs text-destructive">{(connect.error as Error).message}</p>}
      <Button onClick={() => connect.mutate(token)} disabled={!token.trim() || connect.isPending}>
        {connect.isPending ? 'Connecting…' : 'Connect'}
      </Button>
    </div>
  );
}
```

- [ ] **Step 2: Write the page**

```tsx
import GitHubConnect from '@/components/settings/GitHubConnect';

export default function GitHubSettingsPage() {
  return (
    <section className="space-y-4">
      <header>
        <h1 className="text-xl font-semibold">GitHub</h1>
        <p className="text-sm text-muted-foreground">Connect your GitHub account to index repositories.</p>
      </header>
      <GitHubConnect />
    </section>
  );
}
```

- [ ] **Step 3: Verify it renders**

Run: `cd ennam.kg.next && npm run dev` then open `http://localhost:3500/settings/github`
Expected: shows the PAT input with the `repo, admin:repo_hook` caption (or connected state if already connected).

- [ ] **Step 4: Commit**

```bash
git add "ennam.kg.next/src/components/settings/GitHubConnect.tsx" "ennam.kg.next/src/app/(dashboard)/settings/github/page.tsx"
git commit -m "feat(ui): per-user GitHub PAT connect page"
```

### Task 17: Project settings — repo selection modal + connected rows

**Files:**
- Create: `ennam.kg.next/src/components/projects/GitHubRepoModal.tsx`
- Create: `ennam.kg.next/src/components/projects/GitHubSourceRows.tsx`
- Modify: the project settings/code-sources view to render these (locate the existing "Code Sources" / repo_paths section; the spec calls for an "Add from GitHub" button beside the existing "+ Add manual path")

- [ ] **Step 1: Write the connected-rows component**

```tsx
'use client';

import { Button } from '@/components/ui/button';
import { useGitHubSources, useRemoveGitHubSource, useSyncGitHubSource } from '@/hooks/use-github';

export default function GitHubSourceRows({ projectId }: { projectId: string }) {
  const { data } = useGitHubSources(projectId);
  const remove = useRemoveGitHubSource(projectId);
  const sync = useSyncGitHubSource(projectId);
  const sources = data?.sources ?? [];

  if (sources.length === 0) return null;

  return (
    <ul className="divide-y rounded-md border">
      {sources.map((s) => (
        <li key={s.id} className="flex items-center justify-between px-3 py-2">
          <div>
            <p className="text-sm font-medium">{s.config.full_name}</p>
            <p className="text-xs text-muted-foreground">
              {s.config.default_branch} · {s.last_synced_at ? `synced ${new Date(s.last_synced_at).toLocaleString()}` : 'never synced'}
              {s.status === 'error' && <span className="text-destructive"> · error</span>}
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => sync.mutate(s.id)} disabled={sync.isPending}>Sync Now</Button>
            <Button variant="ghost" size="sm" onClick={() => remove.mutate(s.id)} disabled={remove.isPending}>Remove</Button>
          </div>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 2: Write the repo selection modal** (multi-select; uses a shadcn Dialog already in the project)

```tsx
'use client';

import { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { useGitHubRepos, useAddGitHubSource } from '@/hooks/use-github';
import type { GitHubRepo } from '@/types/github';

export default function GitHubRepoModal({ projectId }: { projectId: string }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Record<string, GitHubRepo>>({});
  const { data, isLoading } = useGitHubRepos(open);
  const add = useAddGitHubSource(projectId);

  const repos = (data?.repos ?? []).filter((r) => r.full_name.toLowerCase().includes(search.toLowerCase()));

  const handleAdd = async () => {
    for (const repo of Object.values(selected)) {
      await add.mutateAsync(repo);
    }
    setSelected({});
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">Add from GitHub</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Select repositories</DialogTitle></DialogHeader>
        <input
          placeholder="Search repos…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full rounded-md border px-3 py-2 text-sm"
        />
        <div className="max-h-72 overflow-y-auto">
          {isLoading && <p className="text-sm text-muted-foreground p-2">Loading repos…</p>}
          {repos.map((r) => (
            <label key={r.full_name} className="flex items-center gap-2 px-2 py-1.5 text-sm">
              <input
                type="checkbox"
                checked={!!selected[r.full_name]}
                onChange={(e) =>
                  setSelected((prev) => {
                    const next = { ...prev };
                    if (e.target.checked) next[r.full_name] = r;
                    else delete next[r.full_name];
                    return next;
                  })
                }
              />
              <span>{r.full_name}</span>
              {r.private && <span className="text-xs text-muted-foreground">private</span>}
            </label>
          ))}
        </div>
        <Button onClick={handleAdd} disabled={Object.keys(selected).length === 0 || add.isPending}>
          Add Selected Repos
        </Button>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3: Mount both** in the project's Code Sources section (render `<GitHubRepoModal projectId={id} />` and `<GitHubSourceRows projectId={id} />` next to the existing manual-path UI). Keep the existing "+ Add manual path" control.

- [ ] **Step 4: Verify typecheck + render**

Run: `cd ennam.kg.next && npm run lint && npm run build`
Expected: builds clean.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.next/src/components/projects/GitHubRepoModal.tsx ennam.kg.next/src/components/projects/GitHubSourceRows.tsx
git commit -m "feat(ui): project GitHub repo selection modal + connected source rows"
```

---

## Phase 7 — End-to-end verification

### Task 18: Manual E2E against the Docker stack

- [ ] **Step 1: Bring up the stack**

Run: `docker compose up -d --build`
Expected: all services healthy (`docker compose ps`). Ensure `KG_ENCRYPTION_KEY` and `KG_PUBLIC_URL` are set in the kg-server env.

- [ ] **Step 2: Connect a token** (use a real PAT with `repo, admin:repo_hook` on a throwaway test repo)

Run:
```bash
curl -s -X POST http://localhost:8080/api/v1/github/connect \
  -H "Authorization: Bearer $DEV_API_KEY" -H "Content-Type: application/json" \
  -d "{\"token\":\"$TEST_PAT\"}" | jq .
```
Expected: 200 with `github_username` and `scopes` including `admin:repo_hook`. A token missing `admin:repo_hook` → 400 with the scope message.

- [ ] **Step 3: List repos and add one**

Run:
```bash
curl -s http://localhost:8080/api/v1/github/repos -H "Authorization: Bearer $DEV_API_KEY" | jq '.repos[0]'
curl -s -X POST http://localhost:8080/api/v1/projects/$PROJ/github-sources \
  -H "Authorization: Bearer $DEV_API_KEY" -H "Content-Type: application/json" \
  -d '{"owner":"OWNER","repo":"REPO","full_name":"OWNER/REPO","default_branch":"main","private":true}' | jq .
```
Expected: 201; a webhook appears under the repo's GitHub Settings → Webhooks; worker logs show "Starting full scan from GitHub clone".

- [ ] **Step 4: Verify index landed + cleanup happened**

Run: `docker compose logs worker | grep -E "Cloning|Full scan done"`
Expected: clone logged (sanitized URL, no token), scan completed. Confirm no `ennam-kg-clone-*` dirs linger in the worker container: `docker compose exec worker ls /tmp | grep ennam-kg-clone || echo "clean"` → `clean`.

- [ ] **Step 5: Verify push webhook** (requires `KG_PUBLIC_URL` reachable by GitHub, e.g. via tunnel)

Push a commit to the test repo. Expected: kg-server logs a `POST /webhooks/github` 202; worker re-indexes. If `KG_PUBLIC_URL` is local-only, verify HMAC logic instead with a signed curl using the stored `webhook_secret`.

- [ ] **Step 6: Record results + checkpoint**

Write `.serena/checkpoint/<agent>-2026-06-05.md` per the project's mandatory checkpoint protocol, noting what passed and any deferred items (e.g. webhook test if no public tunnel).

---

## Self-Review Notes (for the planner, completed)

- **Spec coverage:** OAuth endpoints → replaced by PAT connect (Task 6) per confirmed per-user/PAT decision; `/github/repos` → Task 6; `github-sources` add/list/remove/sync → Task 9; webhook receiver → Task 10; **disconnect deletes all webhooks before removing token** (spec security requirement) → Task 5 `Disconnect`; `GitCloner` + worker dispatch → Tasks 13–14; `IndexMessage` fields → Tasks 7, 12; stable keys for re-index → Task 12a; UI account-settings + repo modal + rows → Tasks 16–17; security (encryption, HMAC, no token in logs) → Tasks 4, 10, 13. **Deliberately deferred (matches spec "Out of Scope"):** GitHub OAuth App redirect flow (Phase 2; data model already supports it), branch selection, incremental push index (always full scan), org-level connections.
- **Type consistency:** `queue.IndexMessage.RepoURL/GitHubToken` (Go) ↔ `repo_url/github_token` (Python pydantic + worker `msg.get`) ↔ never sent to browser. `DraftSourceGitHubRepo = "github_repo"` used consistently in migration CHECK, store inserts, and partial index. `tokenProvider.GetToken` (Task 8) and `webhookTokens.GetToken` (Task 10) both satisfied by `GitHubConnectionStore.GetToken`. `NewGitHubWebhookHandler(lookup, tokens, pub, logger)` is 4-arg consistently across def (Task 10), test (Task 10), and wiring (Task 11). `NewGitHubService(connStore, sourceStore, client, logger)` is 4-arg across def, test (Task 5), and wiring (Task 11). `full_name` is the repo identity key in: source config JSONB, the github-only unique index, and `FindGitHubByFullName`.
- **Known wiring decision left to implementer (Task 11):** which mux serves the unauthenticated `/webhooks/github` — resolved by mirroring the existing `publicIngestHandler` precedent rather than inventing a new pattern.
- **Accepted Phase-1 limitations (noted, not blocking):** (1) webhook returns 202 for unknown repos vs 401 for known-bad-signature, which lets a prober distinguish connected repos — acceptable for Phase 1; (2) `ListRepos` returns only the first 100 repos (no pagination) — fine until a user exceeds 100 accessible repos; (3) service test doubles in Task 8 ship in the binary unless moved into a `_test.go` (same package) — prefer moving them.
