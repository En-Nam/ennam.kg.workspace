# DAAB `kg_search_sessions` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Vietnamese-correct, user+project-scoped full-text search over conversation messages, exposed as a stable opaque MCP tool `kg_search_sessions`.

**Architecture:** A generated `tsvector` column on `thread_messages` (config `simple` + `unaccent`) with a GIN index; a `ThreadMessageStore.SearchMessages` read path that JOINs to `conversation_threads` for user/project/soft-delete scoping, ranks with `ts_rank`, and windows snippets with `ts_headline` on the result page only; a REST handler with server-resolved scope; and an MCP bridge tool. Semantic/hybrid is a deferred, contract-stable v2.

**Tech Stack:** Go (stdlib `net/http`, `database/sql`), PostgreSQL 16 (FTS `simple` + `unaccent` + pg_trgm), golang-migrate. Tests: `go test` table-driven (unit) + `-tags=integration` against Postgres.

**Design spec:** `docs/superpowers/specs/2026-06-29-daab-kg-search-sessions-design.md`

## Global Constraints

- Repo: `ennam.kg.go` is a **nested git repo** — run all `git`/`go`/`make` from `/Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace/ennam.kg.go`.
- Integration tests: tag `//go:build integration`. **Store** tests read `KG_TEST_DATABASE_URL`; **handler** tests read `KG_TEST_DSN` (default :5432 — WRONG; the dev DB is :5433). Always export BOTH to the :5433 DSN: `postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable`.
- Run tests with `-race`. `gofmt`/`goimports` after every edit.
- Migration head is `000071`; new pair is `000072`.
- All FTS uses config **`simple`** (NOT `english`) wrapped in **`f_unaccent`**. `to_tsvector`, `plainto_tsquery`, and `ts_headline` must ALL use `simple` + `f_unaccent`, or highlights are silently empty.
- RBAC: `user_id` + `project_id` are resolved **server-side from the key identity**, never from the request body. Empty `user_id` (pure service key) → empty results.
- Snippet is diacritic-stripped in v1 (ts_headline runs on `f_unaccent(content)`); this is an accepted documented limitation.
- MCP bridge invariant (`e2e_tools_test.go:805`): `len(schemas) == len(routes) + len(localToolNames)`. `kg_search_sessions` is a ROUTED (non-local) read tool: routes 41→42, schemas 44→45, local stays 3.

---

### Task 1: Migration — `thread_messages` FTS column

**Files:**
- Create: `db/migrations/000072_thread_messages_fts.up.sql`
- Create: `db/migrations/000072_thread_messages_fts.down.sql`

**Interfaces:**
- Produces: `f_unaccent(text)` IMMUTABLE; `thread_messages.search_vector tsvector` (generated, `to_tsvector('simple', f_unaccent(content))`); GIN index `idx_thread_messages_search_vector`.

- [ ] **Step 1: Write the up migration**

`db/migrations/000072_thread_messages_fts.up.sql`:
```sql
-- Session/conversation search (kg_search_sessions). Vietnamese-correct FTS:
-- config 'simple' (no stemming) + unaccent (diacritic-insensitive).
CREATE EXTENSION IF NOT EXISTS unaccent;

-- unaccent() is STABLE; pin the dictionary so the wrapper is IMMUTABLE and
-- therefore usable inside a generated column / index expression.
CREATE OR REPLACE FUNCTION f_unaccent(text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT unaccent('unaccent', $1) $$;

ALTER TABLE thread_messages
  ADD COLUMN search_vector tsvector
  GENERATED ALWAYS AS (to_tsvector('simple', f_unaccent(content))) STORED;

CREATE INDEX idx_thread_messages_search_vector
  ON thread_messages USING GIN (search_vector);
```

- [ ] **Step 2: Write the down migration**

`db/migrations/000072_thread_messages_fts.down.sql`:
```sql
DROP INDEX IF EXISTS idx_thread_messages_search_vector;
ALTER TABLE thread_messages DROP COLUMN IF EXISTS search_vector;
DROP FUNCTION IF EXISTS f_unaccent(text);
-- unaccent extension left installed (cheap, may be reused).
```

- [ ] **Step 3: Apply and verify**

Run: `make db-migrate && make db-migrate-version`
Expected: version `72`. Then `make db-shell`, run `\d thread_messages` — expected a `search_vector | tsvector` row and `idx_thread_messages_search_vector` GIN index. Verify unaccent: `SELECT f_unaccent('Việt Nam');` → `Viet Nam`.

- [ ] **Step 4: Verify reversibility**

Run: `make db-migrate-down && make db-migrate && make db-migrate-version`
Expected: ends at `72`, no errors.

- [ ] **Step 5: Commit**

```bash
git add db/migrations/000072_thread_messages_fts.up.sql db/migrations/000072_thread_messages_fts.down.sql
git commit -m "feat(daab): thread_messages FTS column (simple+unaccent) for kg_search_sessions"
```

---

### Task 2: Store — `ThreadMessageStore.SearchMessages`

**Files:**
- Modify: `internal/store/thread_message.go`
- Test: `internal/store/thread_message_search_test.go` (create, integration-tagged)

**Interfaces:**
- Consumes: migration 000072 (`search_vector`, `f_unaccent`).
- Produces:
  - `type SessionSearchHit struct { ThreadID, ThreadName, MessageID, Role, Snippet string; CreatedAt time.Time; Score float64 }`
  - `type SessionSearchParams struct { UserID, ProjectID, Query, Role string; Limit, Offset int }`
  - `func (s *ThreadMessageStore) SearchMessages(ctx context.Context, p SessionSearchParams) ([]SessionSearchHit, int, error)` — returns hits (page) + total_count. Empty `UserID` → `(nil, 0, nil)`.

- [ ] **Step 1: Write the failing integration test**

Create `internal/store/thread_message_search_test.go`:
```go
//go:build integration

package store_test

import (
	"context"
	"database/sql"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/store"
)

// seedThread inserts a thread for (user,project) and returns its id.
func seedThread(t *testing.T, db *sql.DB, threadID, userID, projectID, name string) {
	t.Helper()
	_, err := db.ExecContext(context.Background(),
		`INSERT INTO conversation_threads (id, user_id, project_id, name) VALUES ($1,$2,$3,$4)`,
		threadID, userID, projectID, name)
	if err != nil {
		t.Fatalf("seed thread: %v", err)
	}
}

func seedMsg(t *testing.T, ms *store.ThreadMessageStore, threadID, role, content string) string {
	t.Helper()
	m, err := ms.Create(context.Background(), &models.ThreadMessage{
		ThreadID: threadID, Role: models.ThreadMessageRole(role), Content: content,
	})
	if err != nil {
		t.Fatalf("seed msg: %v", err)
	}
	return m.ID
}

func ssTestSetup(t *testing.T) (*sql.DB, *store.ThreadMessageStore) {
	db := setupTestDB(t) // KG_TEST_DATABASE_URL
	ctx := context.Background()
	// Two users in one project, plus a second project, all cleaned up after.
	const proj = "dddddddd-0000-0000-0000-000000000001"
	const proj2 = "dddddddd-0000-0000-0000-000000000002"
	const uA = "dddddddd-1111-0000-0000-000000000001"
	const uB = "dddddddd-2222-0000-0000-000000000002"
	for _, p := range []string{proj, proj2} {
		db.ExecContext(ctx, `DELETE FROM projects WHERE id=$1`, p) //nolint:errcheck
		if _, err := db.ExecContext(ctx, `INSERT INTO projects (id,name) VALUES ($1,$2)`, p, "ss-"+p[:4]); err != nil {
			t.Fatalf("seed project: %v", err)
		}
	}
	for _, u := range []string{uA, uB} {
		db.ExecContext(ctx, `DELETE FROM users WHERE id=$1`, u) //nolint:errcheck
		// users.display_name is NOT NULL (no default); username NOT NULL; password_hash nullable.
		if _, err := db.ExecContext(ctx, `INSERT INTO users (id, username, display_name) VALUES ($1,$2,$2)`, u, "u-"+u[:8]); err != nil {
			t.Fatalf("seed user: %v", err)
		}
	}
	t.Cleanup(func() {
		db.ExecContext(ctx, `DELETE FROM projects WHERE id IN ($1,$2)`, proj, proj2)  //nolint:errcheck
		db.ExecContext(ctx, `DELETE FROM users WHERE id IN ($1,$2)`, uA, uB)          //nolint:errcheck
	})
	return db, store.NewThreadMessageStore(db)
}

func TestSearchMessages_UnaccentAndIsolation(t *testing.T) {
	db, ms := ssTestSetup(t)
	const proj = "dddddddd-0000-0000-0000-000000000001"
	const uA = "dddddddd-1111-0000-0000-000000000001"
	const uB = "dddddddd-2222-0000-0000-000000000002"
	seedThread(t, db, "dddddddd-aaaa-0000-0000-000000000001", uA, proj, "A thread")
	seedThread(t, db, "dddddddd-bbbb-0000-0000-000000000002", uB, proj, "B thread")
	seedMsg(t, ms, "dddddddd-aaaa-0000-0000-000000000001", "user", "Dự án cảng Định An tại Trà Vinh")
	seedMsg(t, ms, "dddddddd-bbbb-0000-0000-000000000002", "user", "Cảng Định An bí mật của user B")

	// Unaccented query matches accented content; only user A's row returned.
	hits, total, err := ms.SearchMessages(context.Background(), store.SessionSearchParams{
		UserID: uA, ProjectID: proj, Query: "dinh an", Limit: 10,
	})
	if err != nil {
		t.Fatalf("search: %v", err)
	}
	if total != 1 || len(hits) != 1 {
		t.Fatalf("want 1 hit for user A, got total=%d len=%d", total, len(hits))
	}
	if !strings.Contains(hits[0].Snippet, "<mark>") {
		t.Errorf("snippet should highlight the match, got %q", hits[0].Snippet)
	}
	if hits[0].ThreadName != "A thread" {
		t.Errorf("thread_name not joined, got %q", hits[0].ThreadName)
	}
}

func TestSearchMessages_EmptyUserReturnsNothing(t *testing.T) {
	_, ms := ssTestSetup(t)
	hits, total, err := ms.SearchMessages(context.Background(), store.SessionSearchParams{
		UserID: "", ProjectID: "dddddddd-0000-0000-0000-000000000001", Query: "anything", Limit: 10,
	})
	if err != nil || total != 0 || len(hits) != 0 {
		t.Errorf("empty userID must return no rows and no error; got hits=%d total=%d err=%v", len(hits), total, err)
	}
}

func TestSearchMessages_SoftDeletedExcludedAndPagination(t *testing.T) {
	db, ms := ssTestSetup(t)
	const proj = "dddddddd-0000-0000-0000-000000000001"
	const uA = "dddddddd-1111-0000-0000-000000000001"
	seedThread(t, db, "dddddddd-cccc-0000-0000-000000000003", uA, proj, "live")
	seedThread(t, db, "dddddddd-dddd-0000-0000-000000000004", uA, proj, "deleted")
	db.ExecContext(context.Background(), `UPDATE conversation_threads SET deleted_at=now() WHERE id=$1`, "dddddddd-dddd-0000-0000-000000000004") //nolint:errcheck
	seedMsg(t, ms, "dddddddd-cccc-0000-0000-000000000003", "user", "alpha one")
	seedMsg(t, ms, "dddddddd-cccc-0000-0000-000000000003", "user", "alpha two")
	seedMsg(t, ms, "dddddddd-dddd-0000-0000-000000000004", "user", "alpha deleted")

	hits, total, err := ms.SearchMessages(context.Background(), store.SessionSearchParams{
		UserID: uA, ProjectID: proj, Query: "alpha", Limit: 1, Offset: 0,
	})
	if err != nil {
		t.Fatalf("search: %v", err)
	}
	if total != 2 { // soft-deleted thread's message excluded from count
		t.Errorf("want total=2 (deleted excluded), got %d", total)
	}
	if len(hits) != 1 {
		t.Errorf("limit=1 should return 1 hit, got %d", len(hits))
	}
	// page 2
	hits2, _, _ := ms.SearchMessages(context.Background(), store.SessionSearchParams{
		UserID: uA, ProjectID: proj, Query: "alpha", Limit: 1, Offset: 1,
	})
	if len(hits2) != 1 || hits2[0].MessageID == hits[0].MessageID {
		t.Errorf("offset pagination should return a distinct second row")
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `export KG_TEST_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable"; go test -tags=integration ./internal/store/ -run TestSearchMessages -v`
Expected: FAIL — `SearchMessages` undefined.

- [ ] **Step 3: Implement `SearchMessages`**

In `internal/store/thread_message.go` add (ensure imports include `time`; `fmt` and `context` are already present):
```go
// SessionSearchHit is one message-level result from SearchMessages.
type SessionSearchHit struct {
	ThreadID   string
	ThreadName string
	MessageID  string
	Role       string
	Snippet    string
	CreatedAt  time.Time
	Score      float64
}

// SessionSearchParams are the inputs to SearchMessages (kg_search_sessions).
type SessionSearchParams struct {
	UserID    string // required; empty => no results
	ProjectID string // required
	Query     string
	Role      string // optional: 'user' | 'assistant'
	Limit     int    // default 8, cap 50
	Offset    int
}

// SearchMessages runs Vietnamese-correct FTS (simple + unaccent) over the
// caller's own (user+project) conversation messages, excluding soft-deleted
// threads. Returns the page of hits plus the total match count. ts_headline is
// computed only on the returned page; snippets are diacritic-stripped.
func (s *ThreadMessageStore) SearchMessages(ctx context.Context, p SessionSearchParams) ([]SessionSearchHit, int, error) {
	if p.UserID == "" || p.ProjectID == "" {
		return nil, 0, nil
	}
	if p.Limit <= 0 {
		p.Limit = 8
	}
	if p.Limit > 50 {
		p.Limit = 50
	}
	if p.Offset < 0 {
		p.Offset = 0
	}

	roleActive := p.Role == "user" || p.Role == "assistant"

	// total_count — role is $4 here (after user,project,query).
	var total int
	countArgs := []interface{}{p.UserID, p.ProjectID, p.Query}
	countRole := ""
	if roleActive {
		countArgs = append(countArgs, p.Role)
		countRole = " AND m.role = $4"
	}
	countQ := `
		SELECT count(*)
		FROM thread_messages m
		JOIN conversation_threads t ON t.id = m.thread_id
		CROSS JOIN plainto_tsquery('simple', f_unaccent($3)) AS q(tsq)
		WHERE t.user_id = $1 AND t.project_id = $2 AND t.deleted_at IS NULL
		  AND m.search_vector @@ q.tsq` + countRole
	if err := s.db.QueryRowContext(ctx, countQ, countArgs...).Scan(&total); err != nil {
		return nil, 0, fmt.Errorf("count session messages: %w", err)
	}
	if total == 0 {
		return nil, 0, nil
	}

	// page: rank+limit first (inner), ts_headline only on the page (outer).
	// role is $6 here (after user,project,query,limit,offset).
	pageArgs := []interface{}{p.UserID, p.ProjectID, p.Query, p.Limit, p.Offset}
	pageRole := ""
	if roleActive {
		pageArgs = append(pageArgs, p.Role)
		pageRole = " AND m.role = $6"
	}
	q := `
		WITH q AS (SELECT plainto_tsquery('simple', f_unaccent($3)) AS tsq),
		page AS (
			SELECT m.id, m.thread_id, m.role, m.content, m.created_at,
			       ts_rank(m.search_vector, q.tsq)::float8 AS score
			FROM thread_messages m
			JOIN conversation_threads t ON t.id = m.thread_id
			CROSS JOIN q
			WHERE t.user_id = $1 AND t.project_id = $2 AND t.deleted_at IS NULL
			  AND m.search_vector @@ q.tsq` + pageRole + `
			ORDER BY score DESC, m.created_at DESC, m.id
			LIMIT $4 OFFSET $5
		)
		SELECT p.id, p.thread_id, t.name, p.role, p.created_at,
		       ts_headline('simple', f_unaccent(p.content), q.tsq,
		         'StartSel=<mark>, StopSel=</mark>, MaxFragments=2, MaxWords=18, MinWords=6') AS snippet,
		       p.score
		FROM page p
		JOIN conversation_threads t ON t.id = p.thread_id
		CROSS JOIN q
		ORDER BY p.score DESC, p.created_at DESC, p.id`
	rows, err := s.db.QueryContext(ctx, q, pageArgs...)
	if err != nil {
		return nil, 0, fmt.Errorf("search session messages: %w", err)
	}
	defer rows.Close()
	var out []SessionSearchHit
	for rows.Next() {
		var h SessionSearchHit
		if err := rows.Scan(&h.MessageID, &h.ThreadID, &h.ThreadName, &h.Role, &h.CreatedAt, &h.Snippet, &h.Score); err != nil {
			return nil, 0, fmt.Errorf("scan session hit: %w", err)
		}
		out = append(out, h)
	}
	return out, total, rows.Err()
}
```
Note on the role placeholder: the count query has args `(user, project, query[, role])` so role is `$4`; the page query has args `(user, project, query, limit, offset[, role])` so role is `$6`. `roleClause` is written with `$6` (for the page query) and rewritten to `$4` for the count query via `strings.Replace`. Verify both compile and run.

- [ ] **Step 4: Run tests to verify pass**

Run: `go test -tags=integration ./internal/store/ -run TestSearchMessages -v`
Expected: PASS (unaccent match + isolation, empty-user, soft-delete + pagination).

- [ ] **Step 5: Commit**

```bash
git add internal/store/thread_message.go internal/store/thread_message_search_test.go
git commit -m "feat(daab): ThreadMessageStore.SearchMessages (simple+unaccent FTS, user/project scoped)"
```

---

### Task 3: Handler + REST route + isolation gate

**Files:**
- Create: `internal/handler/session_search.go`
- Test: `internal/handler/session_search_test.go` (unit, fake store)
- Test: `internal/handler/session_search_isolation_integration_test.go` (integration)
- Modify: `cmd/kg-server/main.go` (construct + register)

**Interfaces:**
- Consumes: `store.ThreadMessageStore.SearchMessages`, `middleware.GetDeveloperIdentity`.
- Produces: `POST /api/v1/sessions/search` returning `{results:[sessionHitView], total_count, next_cursor}`; constructor `NewSessionSearchHandler(searcher sessionSearcher, logger *slog.Logger)`.

- [ ] **Step 1: Write the failing unit test**

Create `internal/handler/session_search_test.go`:
```go
package handler

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"log/slog"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/store"
)

type fakeSearcher struct {
	lastParams store.SessionSearchParams
	hits       []store.SessionSearchHit
	total      int
}

func (f *fakeSearcher) SearchMessages(_ context.Context, p store.SessionSearchParams) ([]store.SessionSearchHit, int, error) {
	f.lastParams = p
	return f.hits, f.total, nil
}

func TestSessionSearch_ResolvesScopeFromIdentityNotBody(t *testing.T) {
	fs := &fakeSearcher{
		hits:  []store.SessionSearchHit{{ThreadID: "t1", ThreadName: "n", MessageID: "m1", Role: "user", Snippet: "<mark>x</mark>", CreatedAt: time.Now(), Score: 0.5}},
		total: 1,
	}
	h := NewSessionSearchHandler(fs, slog.Default())
	// Body tries to widen project; must be ignored.
	body := `{"query":"x","project_id":"ATTACKER-PROJECT"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/sessions/search", strings.NewReader(body))
	req = reqWithIdentityUser(req, "proj-1", "user-1") // helper sets project + user on identity
	w := httptest.NewRecorder()
	h.Search(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d: %s", w.Code, w.Body.String())
	}
	if fs.lastParams.ProjectID != "proj-1" || fs.lastParams.UserID != "user-1" {
		t.Errorf("scope must come from identity, got project=%q user=%q", fs.lastParams.ProjectID, fs.lastParams.UserID)
	}
	var resp struct {
		Results    []map[string]interface{} `json:"results"`
		TotalCount int                      `json:"total_count"`
	}
	json.Unmarshal(w.Body.Bytes(), &resp)
	if resp.TotalCount != 1 || len(resp.Results) != 1 {
		t.Errorf("expected 1 result, got %+v", resp)
	}
}
```
Add a `reqWithIdentityUser` helper, mirroring the existing `reqWithIdentity` in `agent_context_test.go` exactly (same injection mechanism — `context.WithValue(ctx, middleware.DeveloperIdentityKey, id)`), but also setting `UserID`:
```go
func reqWithIdentityUser(r *http.Request, projectID, userID string) *http.Request {
	def := projectID
	id := &middleware.DeveloperIdentity{
		DeveloperName:    "test",
		Role:             models.APIKeyRoleDeveloper,
		ProjectIDs:       []string{projectID},
		DefaultProjectID: &def,
		UserID:           userID,
	}
	ctx := context.WithValue(r.Context(), middleware.DeveloperIdentityKey, id)
	return r.WithContext(ctx)
}
```
Add the `github.com/ennam/ennam-kg/internal/models` import to the test file for `models.APIKeyRoleDeveloper`. (`DeveloperIdentity.UserID` exists — see `middleware/auth.go` and its use at `handler/agent_context.go:152`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/handler/ -run TestSessionSearch_ResolvesScope -v`
Expected: FAIL — `NewSessionSearchHandler` undefined.

- [ ] **Step 3: Implement the handler**

Create `internal/handler/session_search.go`:
```go
package handler

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/store"
)

// sessionSearcher is the store surface the handler depends on (for testability).
type sessionSearcher interface {
	SearchMessages(ctx context.Context, p store.SessionSearchParams) ([]store.SessionSearchHit, int, error)
}

// SessionSearchHandler serves kg_search_sessions (conversation search).
type SessionSearchHandler struct {
	store  sessionSearcher
	logger *slog.Logger
}

// NewSessionSearchHandler creates a SessionSearchHandler.
func NewSessionSearchHandler(s sessionSearcher, logger *slog.Logger) *SessionSearchHandler {
	return &SessionSearchHandler{store: s, logger: logger}
}

// RegisterRoutes registers the session search route.
func (h *SessionSearchHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/sessions/search", h.Search)
}

type sessionSearchRequest struct {
	Query  string `json:"query"`
	Role   string `json:"role"`
	Limit  int    `json:"limit"`
	Cursor string `json:"cursor"` // opaque; encodes offset
}

type sessionHitView struct {
	ThreadID   string    `json:"thread_id"`
	ThreadName string    `json:"thread_name"`
	MessageID  string    `json:"message_id"`
	Role       string    `json:"role"`
	Snippet    string    `json:"snippet"`
	CreatedAt  time.Time `json:"created_at"`
	Score      float64   `json:"score"`
}

// Search handles kg_search_sessions. Scope (user+project) is resolved from the
// key identity; the body never widens scope. Soft-fails to an empty result set.
func (h *SessionSearchHandler) Search(w http.ResponseWriter, r *http.Request) {
	identity := middleware.GetDeveloperIdentity(r.Context())
	projectID, userID := "", ""
	if identity != nil {
		if pid, ok := identity.ResolveProjectID(""); ok {
			projectID = pid
		}
		userID = identity.UserID
	}

	var body sessionSearchRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if strings.TrimSpace(body.Query) == "" {
		errorResponse(w, http.StatusBadRequest, "query is required")
		return
	}
	limit := body.Limit
	if limit <= 0 {
		limit = 8
	}
	offset := 0
	if body.Cursor != "" {
		if n, err := strconv.Atoi(body.Cursor); err == nil && n >= 0 {
			offset = n
		}
	}

	hits, total, err := h.store.SearchMessages(r.Context(), store.SessionSearchParams{
		UserID: userID, ProjectID: projectID, Query: body.Query, Role: body.Role,
		Limit: limit, Offset: offset,
	})
	if err != nil {
		h.logger.ErrorContext(r.Context(), "session search failed", "error", err)
		writeJSON(w, http.StatusOK, map[string]interface{}{"results": []sessionHitView{}, "total_count": 0})
		return
	}

	views := make([]sessionHitView, 0, len(hits))
	for _, hit := range hits {
		views = append(views, sessionHitView{
			ThreadID: hit.ThreadID, ThreadName: hit.ThreadName, MessageID: hit.MessageID,
			Role: hit.Role, Snippet: hit.Snippet, CreatedAt: hit.CreatedAt, Score: hit.Score,
		})
	}
	resp := map[string]interface{}{"results": views, "total_count": total}
	if offset+len(hits) < total {
		resp["next_cursor"] = strconv.Itoa(offset + limit)
	}
	writeJSON(w, http.StatusOK, resp)
}
```
The handler depends only on `middleware.GetDeveloperIdentity` (`auth.go:261`), `(*DeveloperIdentity).ResolveProjectID` (`auth.go:83`), and the `.UserID` field — all exist and are used identically by `handler/agent_context.go`'s `Recall`.

- [ ] **Step 4: Run unit test to verify pass**

Run: `go test ./internal/handler/ -run TestSessionSearch_ResolvesScope -v`
Expected: PASS.

- [ ] **Step 5: Write the isolation integration test**

Create `internal/handler/session_search_isolation_integration_test.go` mirroring `agent_context_isolation_integration_test.go` (full Auth→ProjectID→handler chain via `httptest`), with two users in one project. Assert: (a) user A's key search returns A's messages and NOT user B's; (b) a key scoped to project X cannot return project Y's messages; (c) a non-user-bound key returns empty `results`. Use `integrationDB(t)` (reads `KG_TEST_DSN`). Seed via direct SQL (threads + messages) like Task 2.
```go
//go:build integration

package handler_test
// (model the seed + server-chain setup on agent_context_isolation_integration_test.go;
//  assert results contain only the calling user's thread messages.)
```

- [ ] **Step 6: Wire into `cmd/kg-server/main.go`**

`thread_messages` store already exists in main as part of thread wiring; if a `ThreadMessageStore` is not already constructed, add `tmStore := store.NewThreadMessageStore(db)` near the other thread stores. Then, near the other handler registrations (e.g. after `acHandler.RegisterRoutes(apiMux)`):
```go
	sessionSearchHandler := handler.NewSessionSearchHandler(store.NewThreadMessageStore(db), logger)
	sessionSearchHandler.RegisterRoutes(apiMux)
```

- [ ] **Step 7: Build + run handler tests (unit + integration)**

Run:
```bash
go build ./...
go test -race ./internal/handler/ -run TestSessionSearch
export KG_TEST_DSN="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable"
go test -tags=integration ./internal/handler/ -run TestSessionSearch
```
Expected: build OK; unit + isolation integration PASS.

- [ ] **Step 8: Commit**

```bash
git add internal/handler/session_search.go internal/handler/session_search_test.go internal/handler/session_search_isolation_integration_test.go cmd/kg-server/main.go
git commit -m "feat(daab): kg_search_sessions REST handler + isolation gate"
```

---

### Task 4: MCP bridge tool `kg_search_sessions`

**Files:**
- Modify: `internal/bridge/schema.go` (add schema in `buildToolSchemas`)
- Modify: `internal/bridge/client.go` (add route to the routes map)
- Modify: `internal/bridge/client_test.go` (route count 41→42; route-class read count +1)
- Modify: `internal/bridge/handler_test.go` (schema count 44→45)

**Interfaces:**
- Consumes: REST route `POST /api/v1/sessions/search` (Task 3).
- Produces: MCP tool `kg_search_sessions` (RouteRead) → `ListToolNames()` includes it; `ListToolSchemas()` includes it.

- [ ] **Step 1: Run the bridge count tests to see them pass at current numbers (baseline)**

Run: `go test ./internal/bridge/ -run 'TestListToolNames|TestRouteClassCounts|TestListTools' -v` (use the actual test names; from greps: `client_test.go:216` asserts 41, `handler_test.go:276` asserts 44).
Expected: PASS at 41 / 44. (Establishes the baseline you will bump.)

- [ ] **Step 2: Add the schema in `buildToolSchemas` (schema.go), mirroring `kg_recall`**

In `internal/bridge/schema.go`, inside `buildToolSchemas()` (near the `kg_recall` block):
```go
	schemas["kg_search_sessions"] = &ToolSchema{
		ToolName:    "kg_search_sessions",
		Description: "Search the calling user's own conversation history (user+project scoped) via Vietnamese-correct full-text search. Returns raw windowed snippets, most relevant first, no summarization. Scope is resolved from the API key.",
		Properties: map[string]ParamSchema{
			"query":  {Type: TypeString, Required: true, Description: "What to search for in past conversations", MinLength: intPtr(1), MaxLength: intPtr(500)},
			"role":   {Type: TypeString, Required: false, Description: "Filter by message role", Enum: []string{"user", "assistant"}},
			"limit":  {Type: TypeInteger, Required: false, Description: "Max results (default 8, max 50)"},
			"cursor": {Type: TypeString, Required: false, Description: "Opaque pagination cursor from a prior next_cursor"},
		},
	}
```

- [ ] **Step 3: Add the route in `client.go`**

In `internal/bridge/client.go`, in the routes map (next to `kg_recall`):
```go
	"kg_search_sessions": {
		Method:       http.MethodPost,
		PathTemplate: apiPrefix + "/sessions/search",
		Class:        RouteRead,
	},
```

- [ ] **Step 4: Bump the count assertions**

In `internal/bridge/client_test.go:216-217` change `41` → `42` (both the condition and the message). In `TestRouteClassCounts` (`client_test.go:1052`), increment the expected `RouteRead` count by 1. In `internal/bridge/handler_test.go:276-277` change `44` → `45`.

- [ ] **Step 5: Run the bridge tests**

Run: `go test -race ./internal/bridge/ -run 'TestListToolNames|TestRouteClassCounts|TestListTools|Schema' -v` then `go test -race ./internal/bridge/`
Expected: PASS. The `e2e_tools_test.go:805` invariant `schemas(45) == routes(42) + local(3)` holds automatically.

- [ ] **Step 6: Commit**

```bash
git add internal/bridge/schema.go internal/bridge/client.go internal/bridge/client_test.go internal/bridge/handler_test.go
git commit -m "feat(daab): expose kg_search_sessions MCP tool"
```

---

### Task 5: Full verification

**Files:** none (verification only).

- [ ] **Step 1: Build, vet, unit tests**

Run:
```bash
go build ./... && go vet ./internal/store/... ./internal/handler/... ./internal/bridge/...
go test -race ./internal/store/ ./internal/handler/ ./internal/bridge/
```
Expected: build/vet OK; unit packages PASS.

- [ ] **Step 2: Integration tests (both DSN vars → :5433)**

Run:
```bash
export KG_TEST_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable"
export KG_TEST_DSN="$KG_TEST_DATABASE_URL"
go test -tags=integration ./internal/store/ -run TestSearchMessages
go test -tags=integration ./internal/handler/ -run TestSessionSearch
```
Expected: PASS. (Pre-existing unrelated failures may exist — confirm they are not in files this plan touched before treating as a regression.)

- [ ] **Step 3: Smoke test via running server**

Run: `docker compose up -d --build kg-server` then call `POST /api/v1/sessions/search` with a user-bound key and `{"query":"dinh an"}`; confirm a `results` array with a `<mark>`ed snippet, or `[]` if no data. Confirm a body `project_id` does not change scope.

- [ ] **Step 4: Commit any fixups**

```bash
git add -A && git commit -m "test(daab): verify kg_search_sessions end-to-end" --allow-empty
```

---

## Post-implementation

- File the deferred follow-ups from spec §10 (semantic + hybrid RRF; trigram/CJK; cross-user `monitoring` scope w/ decision record + threat model; `response_blocks` indexing; archived-thread filter; accented snippets) into Serena `backlog/`.
- Write a Serena checkpoint via `mcp__serena__write_memory`.
- Update `mem:decisions/ecosystem-hermes-allocation` consumers: DAAB Phase-1 keystone now complete (RBAC + retention/ranking + session search); LAAM Phase-2 consumer unblocked once the monitoring-scope decision lands.

## Self-Review notes (author)

- **Spec coverage:** migration §6 → T1; store `SearchMessages` §7 → T2; handler/RBAC/contract §8 → T3; MCP tool §8 → T4; isolation gate §9 → T3 Step 5; verification → T5. VN `simple`+`unaccent` §3/D2 → T1+T2; opaque contract §3/D4 → T3 view; offset pagination §7 → T2+T3. All covered.
- **Type consistency:** `SessionSearchHit{ThreadID,ThreadName,MessageID,Role,Snippet,CreatedAt,Score}` and `SessionSearchParams{UserID,ProjectID,Query,Role,Limit,Offset}` used identically in T2/T3; `SearchMessages(ctx, params) ([]hit, int, error)` consistent; `sessionHitView` JSON mirrors the spec envelope `{results, total_count, next_cursor}`.
- **Bridge counts:** routes 41→42 (`client_test.go:216`), schemas 44→45 (`handler_test.go:276`), invariant `45==42+3` holds; RouteRead class +1 (`TestRouteClassCounts`).
- **Verified anchors:** identity injection uses `context.WithValue(ctx, middleware.DeveloperIdentityKey, id)` (not a `WithDeveloperIdentity` fn); `DeveloperIdentity` has `UserID`; `users.display_name` is NOT NULL (seed includes it); role placeholders are now separate per query (`$4` count / `$6` page — no string rewrite); bridge counts 41→42 / 44→45 confirmed against `client_test.go:216` / `handler_test.go:276`.
