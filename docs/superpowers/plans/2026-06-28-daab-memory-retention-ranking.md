# DAAB Memory Retention + Recall Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound `agent_context` memory growth (live rows + vector storage) and add recency-weighted, scope-safe recall ranking to the DAAB shared memory substrate.

**Architecture:** A pure-Go recency decay folded into the existing RRF fusion at recall, a scope-aware PII filter on the recall SQL, and a ticker-based background sweep (mirroring `OAuthRefreshWorker`) that archives free-form duplicates and over-cap rows and drops their embeddings. All retention logic is plain SQL — no AI.

**Tech Stack:** Go (stdlib `net/http`, `database/sql`, `log/slog`), PostgreSQL 16 + pgvector, golang-migrate. Tests: `go test` table-driven (unit) and `-tags=integration` against a Postgres test DB.

**Design spec:** `docs/superpowers/specs/2026-06-28-daab-memory-retention-ranking-design.md`

## Global Constraints

- Repo: `ennam.kg.go` is a **nested git repo** — run all `git`/`go`/`make` commands from `/Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace/ennam.kg.go`.
- Test DB for integration tests: `KG_TEST_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable"`. Integration tests use the `//go:build integration` tag; run with `go test -tags=integration`.
- Run tests with `-race`. Format with `gofmt`/`goimports` after every edit (no style debate).
- Migration head is `000070`; new migration is `000071`.
- **Settings convention (matches existing `ingestion.*`):** defaults live as Go constants; runtime override via `system_settings` keys read with `service.readIntSetting(... fallback)`. **No `config.yaml` entries** (deviation from spec §9, which named config.yaml; the codebase has no YAML path for these — follow the established pattern).
- Retention invariant (both sweep passes): operate ONLY on rows where `is_archived = false AND mem_key IS NULL`; set `is_archived = true`; never bump `updated_at`; never touch `mem_key` rows; never `DELETE` the source row.
- Archive is reversible-by-SQL; observability is `slog` only (full `audit_trail` is a deferred follow-up).
- Recency decay applies to free-form rows only; `mem_key` rows are decay-exempt (factor 1.0), symmetric with their archival exemption.

---

### Task 1: Migration — `last_recalled_at` column

Forward-compat insurance for future usage-based decay. Nullable, unpopulated in v1.

**Files:**
- Create: `db/migrations/000071_agent_context_last_recalled_at.up.sql`
- Create: `db/migrations/000071_agent_context_last_recalled_at.down.sql`

**Interfaces:**
- Produces: column `agent_context.last_recalled_at TIMESTAMPTZ NULL` (unused by v1 code).

- [ ] **Step 1: Write the up migration**

`db/migrations/000071_agent_context_last_recalled_at.up.sql`:
```sql
-- Forward-compat insurance for usage-based decay (not populated in v1).
ALTER TABLE agent_context ADD COLUMN IF NOT EXISTS last_recalled_at TIMESTAMPTZ;
```

- [ ] **Step 2: Write the down migration**

`db/migrations/000071_agent_context_last_recalled_at.down.sql`:
```sql
ALTER TABLE agent_context DROP COLUMN IF EXISTS last_recalled_at;
```

- [ ] **Step 3: Apply and verify the column exists**

Run: `make db-migrate && make db-migrate-version`
Expected: version prints `71`. Then run `make db-shell` and `\d agent_context` — expected: a `last_recalled_at | timestamp with time zone` row.

- [ ] **Step 4: Verify down then up (reversibility)**

Run: `make db-migrate-down && make db-migrate && make db-migrate-version`
Expected: ends at version `71`, no errors.

- [ ] **Step 5: Commit**

```bash
git add db/migrations/000071_agent_context_last_recalled_at.up.sql db/migrations/000071_agent_context_last_recalled_at.down.sql
git commit -m "feat(daab): add agent_context.last_recalled_at (retention forward-compat)"
```

---

### Task 2: Recency decay in RRF fusion (pure Go)

Add the decay factor to `fuseAgentRecall`, a `MemKey` field to `SearchResult`, and `Now`/`HalfLifeHours` to recall params. This task is unit-testable with no database.

**Files:**
- Modify: `internal/store/search.go` (add `MemKey` field to `SearchResult`)
- Modify: `internal/store/agent_context.go` (params, `RecallAgentContext`, `fuseAgentRecall`)
- Modify: `internal/store/agent_context_fusion_test.go` (update existing call sites to new signature)
- Test: `internal/store/agent_context_fusion_test.go` (add decay unit tests)

**Interfaces:**
- Produces:
  - `SearchResult.MemKey string` (json `mem_key,omitempty`).
  - `AgentRecallParams.Now time.Time` (zero ⇒ `time.Now()`), `AgentRecallParams.HalfLifeHours float64` (≤0 ⇒ `defaultRecallHalfLifeHours = 720`).
  - `fuseAgentRecall(lists [][]SearchResult, topK int, now time.Time, halfLifeHours float64) []SearchResult` — decay = 1.0 for `mem_key` rows; else `halfLifeHours/(halfLifeHours+ageHours)`. A **zero `now` disables decay** (age clamps to 0 ⇒ factor 1.0).

- [ ] **Step 1: Add the `MemKey` field to `SearchResult`**

In `internal/store/search.go`, after the `Headline` field (line 29):
```go
	Headline   string          `json:"headline,omitempty"`
	MemKey     string          `json:"mem_key,omitempty"`
```

- [ ] **Step 2: Write failing decay unit tests**

In `internal/store/agent_context_fusion_test.go`, add (this file has no build tag — pure Go):
```go
func TestFuseAgentRecall_DecayPromotesRecent(t *testing.T) {
	now := time.Now()
	old := SearchResult{ID: "old", UpdatedAt: now.Add(-365 * 24 * time.Hour)}
	recent := SearchResult{ID: "recent", UpdatedAt: now.Add(-1 * time.Hour)}
	// "old" appears first (higher base RRF), "recent" second (lower base RRF).
	out := fuseAgentRecall([][]SearchResult{{old, recent}}, 8, now, 720)
	if len(out) != 2 {
		t.Fatalf("want 2 results, got %d", len(out))
	}
	if out[0].ID != "recent" {
		t.Errorf("decay should promote recent over old: got %s first", out[0].ID)
	}
}

func TestFuseAgentRecall_MemKeyExemptFromDecay(t *testing.T) {
	now := time.Now()
	pinned := SearchResult{ID: "pinned", MemKey: "k1", UpdatedAt: now.Add(-365 * 24 * time.Hour)}
	recent := SearchResult{ID: "recent", UpdatedAt: now.Add(-1 * time.Hour)}
	// pinned appears first (higher base RRF) and is old but keyed -> must NOT be decayed below recent.
	out := fuseAgentRecall([][]SearchResult{{pinned, recent}}, 8, now, 720)
	if out[0].ID != "pinned" {
		t.Errorf("mem_key row must be decay-exempt and stay first: got %s", out[0].ID)
	}
}

func TestFuseAgentRecall_ZeroNowDisablesDecay(t *testing.T) {
	old := SearchResult{ID: "old", UpdatedAt: time.Now().Add(-365 * 24 * time.Hour)}
	recent := SearchResult{ID: "recent", UpdatedAt: time.Now()}
	out := fuseAgentRecall([][]SearchResult{{old, recent}}, 8, time.Time{}, 720)
	// zero now -> no decay -> original RRF order (old first, it had the higher base score).
	if out[0].ID != "old" {
		t.Errorf("zero now should disable decay (old keeps higher base RRF): got %s", out[0].ID)
	}
}
```
Add `"time"` to the test file imports if missing.

- [ ] **Step 3: Run tests to verify they fail**

Run: `go test ./internal/store/ -run TestFuseAgentRecall -v`
Expected: compile error (signature mismatch) / FAIL.

- [ ] **Step 4: Update params, `RecallAgentContext`, and `fuseAgentRecall`**

In `internal/store/agent_context.go`, add `"time"` to imports. Add a const near `agentRecallRRFk`:
```go
const agentRecallRRFk = 60

// defaultRecallHalfLifeHours is the recency-decay half-life used when the caller
// does not supply one (≈30 days).
const defaultRecallHalfLifeHours = 720.0
```
Add fields to `AgentRecallParams` (after `TopK int`):
```go
	TopK           int
	Now            time.Time // recall-time reference for recency decay; zero => time.Now()
	HalfLifeHours  float64   // recency decay half-life in hours; <=0 => defaultRecallHalfLifeHours
```
Change `RecallAgentContext` to resolve defaults and pass them through:
```go
func (s *AgentContextStore) RecallAgentContext(ctx context.Context, p AgentRecallParams) ([]SearchResult, error) {
	if p.TopK <= 0 {
		p.TopK = 8
	}
	now := p.Now
	if now.IsZero() {
		now = time.Now()
	}
	halfLife := p.HalfLifeHours
	if halfLife <= 0 {
		halfLife = defaultRecallHalfLifeHours
	}
	sem, err := s.recallSemantic(ctx, p)
	if err != nil {
		return nil, err
	}
	lex, err := s.recallLexical(ctx, p)
	if err != nil {
		return nil, err
	}
	return fuseAgentRecall([][]SearchResult{sem, lex}, p.TopK, now, halfLife), nil
}
```
Change `fuseAgentRecall` signature and the score loop (replace the existing `for id := range keep { ... row.Rank = score[id] ... }` block):
```go
func fuseAgentRecall(lists [][]SearchResult, topK int, now time.Time, halfLifeHours float64) []SearchResult {
	score := make(map[string]float64)
	keep := make(map[string]SearchResult)
	for _, list := range lists {
		for i, row := range list {
			score[row.ID] += 1.0 / float64(agentRecallRRFk+i+1)
			if existing, ok := keep[row.ID]; !ok {
				keep[row.ID] = row
			} else if existing.Headline == "" && row.Headline != "" {
				existing.Headline = row.Headline
				keep[row.ID] = existing
			}
		}
	}
	out := make([]SearchResult, 0, len(keep))
	for id := range keep {
		row := keep[id]
		// Recency decay: free-form rows decay with age; mem_key (curated) rows are
		// exempt. A zero `now` clamps age to 0, disabling decay entirely.
		decay := 1.0
		if row.MemKey == "" {
			ageHours := now.Sub(row.UpdatedAt).Hours()
			if ageHours < 0 {
				ageHours = 0
			}
			decay = halfLifeHours / (halfLifeHours + ageHours)
		}
		row.Rank = score[id] * decay
		out = append(out, row)
	}
	sort.SliceStable(out, func(a, b int) bool {
		if out[a].Rank != out[b].Rank {
			return out[a].Rank > out[b].Rank
		}
		if !out[a].UpdatedAt.Equal(out[b].UpdatedAt) {
			return out[a].UpdatedAt.After(out[b].UpdatedAt)
		}
		return out[a].ID < out[b].ID
	})
	if topK > 0 && len(out) > topK {
		out = out[:topK]
	}
	return out
}
```

- [ ] **Step 5: Update any existing `fuseAgentRecall` call sites in tests**

In `internal/store/agent_context_fusion_test.go`, update every existing `fuseAgentRecall(lists, k)` call to `fuseAgentRecall(lists, k, time.Time{}, 720)` (zero now ⇒ decay disabled ⇒ prior assertions hold).

- [ ] **Step 6: Run tests to verify pass**

Run: `go test ./internal/store/ -run TestFuseAgentRecall -v`
Expected: PASS (all three new tests + existing fusion tests).

- [ ] **Step 7: Commit**

```bash
git add internal/store/search.go internal/store/agent_context.go internal/store/agent_context_fusion_test.go
git commit -m "feat(daab): recency decay in agent_context recall fusion (mem_key exempt)"
```

---

### Task 3: Scope-aware PII filter on recall (store, integration)

Close the gate #2f hole: `scope='user'` rows are visible only to their owner; `scope='project'`/`'agent'` rows (user_id NULL) are shared and must not be excluded.

**Files:**
- Modify: `internal/store/agent_context.go` (`agentRecallFilters`)
- Test: `internal/store/agent_context_scope_test.go` (create, integration-tagged)

**Interfaces:**
- Consumes: `AgentRecallParams.UserID`, `.Query`, `.ProjectID` (existing).
- Produces: recall returns `scope='user'` rows only when `UserID` matches; project/agent rows always visible within the project.

- [ ] **Step 1: Write the failing integration test**

Create `internal/store/agent_context_scope_test.go`:
```go
//go:build integration

package store_test

import (
	"context"
	"testing"

	"github.com/ennam/ennam-kg/internal/store"
)

func TestRecall_ScopeAwareUserIsolation(t *testing.T) {
	db := setupTestDB(t)
	acSeedProject(t, db)
	s := store.NewAgentContextStore(db)
	ctx := context.Background()

	// user U1 private memory, user U2 private memory, and a shared project memory.
	mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, UserID: "11111111-1111-1111-1111-111111111111", SourceAgent: "a", Kind: "fact", Scope: "user", Content: "alpha u1 secret"})
	mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, UserID: "22222222-2222-2222-2222-222222222222", SourceAgent: "a", Kind: "fact", Scope: "user", Content: "alpha u2 secret"})
	mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "alpha shared project"})

	// Recall as U1: sees own user row + shared project row, NOT U2's row.
	got, err := s.RecallAgentContext(ctx, store.AgentRecallParams{
		ProjectID: acProj, UserID: "11111111-1111-1111-1111-111111111111", Query: "alpha", TopK: 10,
	})
	if err != nil {
		t.Fatalf("recall: %v", err)
	}
	ids := contentSet(t, got)
	if !ids["alpha u1 secret"] || !ids["alpha shared project"] {
		t.Errorf("U1 must see own user row + shared project row; got %v", ids)
	}
	if ids["alpha u2 secret"] {
		t.Errorf("U1 must NOT see U2's user-scoped row; got %v", ids)
	}

	// Recall with no user (agent key): sees shared project row, no user rows.
	got2, err := s.RecallAgentContext(ctx, store.AgentRecallParams{ProjectID: acProj, Query: "alpha", TopK: 10})
	if err != nil {
		t.Fatalf("recall no-user: %v", err)
	}
	ids2 := contentSet(t, got2)
	if !ids2["alpha shared project"] {
		t.Errorf("agent key must see shared project row; got %v", ids2)
	}
	if ids2["alpha u1 secret"] || ids2["alpha u2 secret"] {
		t.Errorf("agent key must NOT see user-scoped rows; got %v", ids2)
	}
}
```
Add these helpers to the same file (used by Tasks 3–4):
```go
func mustUpsert(t *testing.T, s *store.AgentContextStore, m store.AgentContextUpsert) string {
	t.Helper()
	id, _, err := s.UpsertAgentContext(context.Background(), m)
	if err != nil {
		t.Fatalf("upsert %q: %v", m.Content, err)
	}
	return id
}

func contentSet(t *testing.T, rows []store.SearchResult) map[string]bool {
	t.Helper()
	out := map[string]bool{}
	for _, r := range rows {
		var p struct {
			Content string `json:"content"`
		}
		if err := jsonUnmarshal(r.Properties, &p); err != nil {
			t.Fatalf("unmarshal properties: %v", err)
		}
		out[p.Content] = true
	}
	return out
}
```
Add a small JSON helper (or use `encoding/json` directly) at the top of the file:
```go
func jsonUnmarshal(b []byte, v interface{}) error { return json.Unmarshal(b, v) }
```
and add `"encoding/json"` to imports.

- [ ] **Step 2: Run test to verify it fails**

Run: `go test -tags=integration ./internal/store/ -run TestRecall_ScopeAwareUserIsolation -v`
Expected: FAIL — current code excludes the project row for U1 (uses `a.user_id = $N`) and/or leaks U2's row on the no-user path.

- [ ] **Step 3: Rewrite the user clause in `agentRecallFilters`**

In `internal/store/agent_context.go`, replace the `if p.UserID != "" { ... a.user_id = $%d ... }` block with:
```go
	if p.UserID != "" {
		args = append(args, p.UserID)
		// user-scoped rows only for their owner; project/agent rows are shared.
		clause += fmt.Sprintf(" AND (a.scope <> 'user' OR a.user_id = $%d)", len(args))
	} else {
		// no user identity -> never return user-scoped rows.
		clause += " AND a.scope <> 'user'"
	}
```
Leave the `Kind`, `Scope`, and `Tags` clauses unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `go test -tags=integration ./internal/store/ -run TestRecall_ScopeAwareUserIsolation -v`
Expected: PASS.

- [ ] **Step 5: Run the existing isolation integration test (regression)**

Run: `go test -tags=integration ./internal/handler/ -run TestAgentContextRecall_Isolation -v`
Expected: PASS (cross-project isolation unchanged).

- [ ] **Step 6: Commit**

```bash
git add internal/store/agent_context.go internal/store/agent_context_scope_test.go
git commit -m "fix(daab): scope-aware PII filter on agent_context recall (gate #2f)"
```

---

### Task 4: Over-fetch + project `mem_key` into results (store, integration)

Over-fetch each branch so decay reorders a real candidate set, and surface `mem_key` so decay can exempt curated rows end-to-end.

**Files:**
- Modify: `internal/store/agent_context.go` (`agentSelectCols`, `recallSemantic`, `recallLexical`, `scanAgentResults`, add `agentFetchLimit`)
- Test: `internal/store/agent_context_scope_test.go` (add two cases)

**Interfaces:**
- Consumes: `SearchResult.MemKey` (Task 2), `AgentRecallParams.TopK`.
- Produces: each branch fetches `agentFetchLimit(TopK) = max(TopK, 50)`; recalled rows carry `MemKey` (empty for free-form).

- [ ] **Step 1: Write the failing tests**

Append to `internal/store/agent_context_scope_test.go`:
```go
func TestRecall_ProjectsMemKey(t *testing.T) {
	db := setupTestDB(t)
	acSeedProject(t, db)
	s := store.NewAgentContextStore(db)
	ctx := context.Background()

	mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "preference", Scope: "project", MemKey: "k1", Content: "beta keyed pref"})
	mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "beta freeform fact"})

	got, err := s.RecallAgentContext(ctx, store.AgentRecallParams{ProjectID: acProj, Query: "beta", TopK: 10})
	if err != nil {
		t.Fatalf("recall: %v", err)
	}
	byKey := map[string]string{} // content -> mem_key
	for _, r := range got {
		var p struct {
			Content string `json:"content"`
		}
		_ = jsonUnmarshal(r.Properties, &p)
		byKey[p.Content] = r.MemKey
	}
	if byKey["beta keyed pref"] != "k1" {
		t.Errorf("keyed row should carry mem_key, got %q", byKey["beta keyed pref"])
	}
	if byKey["beta freeform fact"] != "" {
		t.Errorf("free-form row should have empty mem_key, got %q", byKey["beta freeform fact"])
	}
}

func TestRecall_OverFetchRescuesRecentRow(t *testing.T) {
	db := setupTestDB(t)
	acSeedProject(t, db)
	s := store.NewAgentContextStore(db)
	ctx := context.Background()

	// 19 strong-lexical-match rows, old; 1 weak-match row, brand new.
	old := time.Now().Add(-365 * 24 * time.Hour)
	for i := 0; i < 19; i++ {
		id := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "gamma gamma gamma strong"})
		backdate(t, db, id, old)
	}
	recentID := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "gamma weak"})

	got, err := s.RecallAgentContext(ctx, store.AgentRecallParams{ProjectID: acProj, Query: "gamma", TopK: 8})
	if err != nil {
		t.Fatalf("recall: %v", err)
	}
	found := false
	for _, r := range got {
		if r.ID == recentID {
			found = true
		}
	}
	if !found {
		t.Errorf("over-fetch + decay should rescue the recent weak-match row into top-8")
	}
}

func backdate(t *testing.T, db *sql.DB, id string, ts time.Time) {
	t.Helper()
	if _, err := db.ExecContext(context.Background(), `UPDATE agent_context SET updated_at=$2, created_at=$2 WHERE id=$1`, id, ts); err != nil {
		t.Fatalf("backdate %s: %v", id, err)
	}
}
```
Add `"database/sql"` and `"time"` to the file imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test -tags=integration ./internal/store/ -run 'TestRecall_ProjectsMemKey|TestRecall_OverFetchRescuesRecentRow' -v`
Expected: FAIL — `mem_key` not projected (empty for keyed row) and the recent row is dropped by the `LIMIT TopK`.

- [ ] **Step 3: Project `mem_key` in `agentSelectCols` and scan it**

In `internal/store/agent_context.go`, change `agentSelectCols` — append `a.mem_key` after the `session_id` column:
```go
const agentSelectCols = `
	a.id, a.project_id, a.kind AS node_type, '' AS title, '' AS status,
	jsonb_build_object('content', a.content, 'tags', a.tags, 'source_agent', a.source_agent) AS properties,
	a.scope, 0 AS version, a.source_agent AS created_by,
	a.created_at, a.updated_at, NULL::text AS session_id, a.mem_key`
```
Update `scanAgentResults` to scan the extra column (mem_key is nullable). Add `"database/sql"` to imports if not present (it is). Replace the scan block:
```go
	for rows.Next() {
		var r SearchResult
		var memKey sql.NullString
		if err := rows.Scan(
			&r.ID, &r.ProjectID, &r.NodeType, &r.Title, &r.Status,
			&r.Properties, &r.Scope, &r.Version, &r.CreatedBy,
			&r.CreatedAt, &r.UpdatedAt, &r.SessionID, &memKey, &r.Rank, &r.Headline,
		); err != nil {
			return nil, fmt.Errorf("scan agent_context result: %w", err)
		}
		r.MemKey = memKey.String
		out = append(out, r)
	}
```
(The branch queries select `%s, <rank>, <headline>` so the column order is `…, session_id, mem_key, rank, headline` — matching the scan.)

- [ ] **Step 4: Add `agentFetchLimit` and use it in both branches**

Add near the top of the recall helpers:
```go
// agentFetchLimit over-fetches per branch so recency decay reorders a real
// candidate set instead of an already-truncated TopK slice.
func agentFetchLimit(topK int) int {
	if topK < 50 {
		return 50
	}
	return topK
}
```
In `recallSemantic` and `recallLexical`, change `args = append(args, p.TopK)` to:
```go
	args = append(args, agentFetchLimit(p.TopK))
```
(The final trim to `TopK` already happens in `fuseAgentRecall`.)

- [ ] **Step 5: Run tests to verify pass**

Run: `go test -tags=integration ./internal/store/ -run 'TestRecall_ProjectsMemKey|TestRecall_OverFetchRescuesRecentRow|TestRecall_ScopeAwareUserIsolation' -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add internal/store/agent_context.go internal/store/agent_context_scope_test.go
git commit -m "feat(daab): over-fetch recall branches + project mem_key for decay"
```

---

### Task 5: `MemorySettings` provider (service, unit)

One typed reader for the three runtime-overridable memory settings, reusing the existing `settingsReader` + `readIntSetting` helpers.

**Files:**
- Create: `internal/service/memory_settings.go`
- Test: `internal/service/memory_settings_test.go`

**Interfaces:**
- Consumes: `settingsReader` (existing, `internal/service/ingestion_settings.go`), `readIntSetting` (existing).
- Produces:
  - `func NewMemorySettings(settingsStore *store.SettingsStore) *MemorySettings`
  - `(*MemorySettings).RecallHalfLifeHours(ctx) float64` (default 720)
  - `(*MemorySettings).BucketCap(ctx) int` (default 200)
  - `(*MemorySettings).SweepIntervalSeconds(ctx) int` (default 3600)
  - settings keys: `memory.recall_half_life_hours`, `memory.bucket_cap`, `memory.retention_sweep_interval_seconds`.

- [ ] **Step 1: Write the failing test**

Create `internal/service/memory_settings_test.go`:
```go
package service

import (
	"context"
	"encoding/json"
	"testing"
)

type fakeMemReader struct{ vals map[string]json.RawMessage }

func (f fakeMemReader) Get(_ context.Context, key string) (json.RawMessage, error) {
	if v, ok := f.vals[key]; ok {
		return v, nil
	}
	return nil, nil // missing -> reader returns empty -> default applies
}

func TestMemorySettings_Defaults(t *testing.T) {
	m := &MemorySettings{reader: fakeMemReader{vals: map[string]json.RawMessage{}}}
	if got := m.RecallHalfLifeHours(context.Background()); got != 720 {
		t.Errorf("half life default: want 720, got %v", got)
	}
	if got := m.BucketCap(context.Background()); got != 200 {
		t.Errorf("bucket cap default: want 200, got %v", got)
	}
	if got := m.SweepIntervalSeconds(context.Background()); got != 3600 {
		t.Errorf("interval default: want 3600, got %v", got)
	}
}

func TestMemorySettings_Override(t *testing.T) {
	m := &MemorySettings{reader: fakeMemReader{vals: map[string]json.RawMessage{
		"memory.recall_half_life_hours":            json.RawMessage(`168`),
		"memory.bucket_cap":                        json.RawMessage(`50`),
		"memory.retention_sweep_interval_seconds":  json.RawMessage(`600`),
	}}}
	if got := m.RecallHalfLifeHours(context.Background()); got != 168 {
		t.Errorf("half life override: want 168, got %v", got)
	}
	if got := m.BucketCap(context.Background()); got != 50 {
		t.Errorf("bucket cap override: want 50, got %v", got)
	}
	if got := m.SweepIntervalSeconds(context.Background()); got != 600 {
		t.Errorf("interval override: want 600, got %v", got)
	}
}

func TestMemorySettings_NilReaderUsesDefaults(t *testing.T) {
	m := &MemorySettings{reader: nil}
	if got := m.BucketCap(context.Background()); got != 200 {
		t.Errorf("nil reader should default: got %v", got)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/service/ -run TestMemorySettings -v`
Expected: FAIL — `MemorySettings` undefined.

- [ ] **Step 3: Implement `MemorySettings`**

Create `internal/service/memory_settings.go`:
```go
package service

import (
	"context"

	"github.com/ennam/ennam-kg/internal/store"
)

const (
	defaultRecallHalfLifeHours        = 720  // ~30 days
	defaultMemoryBucketCap            = 200  // max live free-form rows per (project,user,scope)
	defaultRetentionSweepIntervalSecs = 3600 // 1 hour
)

// MemorySettings reads runtime-overridable agent_context memory settings from
// system_settings, falling back to Go-constant defaults. Mirrors the
// ingestion settings pattern.
type MemorySettings struct {
	reader settingsReader
}

// NewMemorySettings builds a MemorySettings backed by system_settings.
func NewMemorySettings(settingsStore *store.SettingsStore) *MemorySettings {
	return &MemorySettings{reader: NewSettingsValueReader(settingsStore)}
}

// RecallHalfLifeHours is the recency-decay half-life (default 720h).
func (m *MemorySettings) RecallHalfLifeHours(ctx context.Context) float64 {
	if m == nil || m.reader == nil {
		return float64(defaultRecallHalfLifeHours)
	}
	v, err := readIntSetting(ctx, m.reader, "memory.recall_half_life_hours", defaultRecallHalfLifeHours)
	if err != nil || v <= 0 {
		return float64(defaultRecallHalfLifeHours)
	}
	return float64(v)
}

// BucketCap is the max live free-form rows per (project,user,scope) (default 200).
func (m *MemorySettings) BucketCap(ctx context.Context) int {
	if m == nil || m.reader == nil {
		return defaultMemoryBucketCap
	}
	v, err := readIntSetting(ctx, m.reader, "memory.bucket_cap", defaultMemoryBucketCap)
	if err != nil || v <= 0 {
		return defaultMemoryBucketCap
	}
	return v
}

// SweepIntervalSeconds is the retention sweep tick interval (default 3600s).
func (m *MemorySettings) SweepIntervalSeconds(ctx context.Context) int {
	if m == nil || m.reader == nil {
		return defaultRetentionSweepIntervalSecs
	}
	v, err := readIntSetting(ctx, m.reader, "memory.retention_sweep_interval_seconds", defaultRetentionSweepIntervalSecs)
	if err != nil || v <= 0 {
		return defaultRetentionSweepIntervalSecs
	}
	return v
}
```

- [ ] **Step 4: Run test to verify pass**

Run: `go test ./internal/service/ -run TestMemorySettings -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/service/memory_settings.go internal/service/memory_settings_test.go
git commit -m "feat(daab): MemorySettings provider for recall/retention config"
```

---

### Task 6: Retention sweep store method (store, integration)

The two SQL passes + embedding deletion in one transaction.

**Files:**
- Modify: `internal/store/agent_context.go` (add `RetentionSweepResult` + `RunRetentionSweep`)
- Test: `internal/store/agent_context_retention_test.go` (create, integration-tagged)

**Interfaces:**
- Produces:
  - `type RetentionSweepResult struct { DedupArchived, CapArchived, EmbeddingsDeleted int }`
  - `func (s *AgentContextStore) RunRetentionSweep(ctx context.Context, bucketCap int) (RetentionSweepResult, error)`

- [ ] **Step 1: Write the failing integration tests**

Create `internal/store/agent_context_retention_test.go`:
```go
//go:build integration

package store_test

import (
	"context"
	"testing"
	"time"

	"github.com/ennam/ennam-kg/internal/store"
)

func TestRetention_DedupKeepsNewest(t *testing.T) {
	db := setupTestDB(t)
	acSeedProject(t, db)
	s := store.NewAgentContextStore(db)
	ctx := context.Background()

	// three identical free-form rows, distinct ages; one keyed row same content.
	idOld := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "dup content"})
	backdate(t, db, idOld, time.Now().Add(-72*time.Hour))
	idMid := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "dup content"})
	backdate(t, db, idMid, time.Now().Add(-48*time.Hour))
	idNew := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "dup content"})
	backdate(t, db, idNew, time.Now().Add(-1*time.Hour))
	idKeyed := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", MemKey: "kx", Content: "dup content"})

	res, err := s.RunRetentionSweep(ctx, 1000)
	if err != nil {
		t.Fatalf("sweep: %v", err)
	}
	if res.DedupArchived != 2 {
		t.Errorf("want 2 dedup-archived, got %d", res.DedupArchived)
	}
	assertArchived(t, db, idOld, true)
	assertArchived(t, db, idMid, true)
	assertArchived(t, db, idNew, false) // newest survives
	assertArchived(t, db, idKeyed, false) // keyed never archived
}

func TestRetention_GrowthBoundArchivesOldest(t *testing.T) {
	db := setupTestDB(t)
	acSeedProject(t, db)
	s := store.NewAgentContextStore(db)
	ctx := context.Background()

	var ids []string
	for i := 0; i < 5; i++ {
		id := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "row " + time.Duration(i).String()})
		backdate(t, db, id, time.Now().Add(-time.Duration(100-i)*time.Hour)) // ids[0] oldest
		ids = append(ids, id)
	}
	res, err := s.RunRetentionSweep(ctx, 2)
	if err != nil {
		t.Fatalf("sweep: %v", err)
	}
	if res.CapArchived != 3 {
		t.Errorf("want 3 cap-archived, got %d", res.CapArchived)
	}
	assertArchived(t, db, ids[0], true)  // oldest archived
	assertArchived(t, db, ids[1], true)
	assertArchived(t, db, ids[2], true)
	assertArchived(t, db, ids[3], false) // 2 newest survive
	assertArchived(t, db, ids[4], false)
}

func TestRetention_DeletesEmbeddingAndIsIdempotent(t *testing.T) {
	db := setupTestDB(t)
	acSeedProject(t, db)
	s := store.NewAgentContextStore(db)
	ctx := context.Background()

	keep := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "keep"})
	drop := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "drop"})
	backdate(t, db, keep, time.Now())
	backdate(t, db, drop, time.Now().Add(-100*time.Hour))
	seedEmbedding(t, s, drop)

	res, err := s.RunRetentionSweep(ctx, 1)
	if err != nil {
		t.Fatalf("sweep: %v", err)
	}
	if res.EmbeddingsDeleted != 1 {
		t.Errorf("want 1 embedding deleted, got %d", res.EmbeddingsDeleted)
	}
	assertEmbeddingExists(t, db, drop, false)

	// idempotent: second run archives nothing more.
	res2, err := s.RunRetentionSweep(ctx, 1)
	if err != nil {
		t.Fatalf("sweep2: %v", err)
	}
	if res2.DedupArchived+res2.CapArchived != 0 {
		t.Errorf("second sweep should be a no-op, got %+v", res2)
	}
}
```
Add these helpers (same file):
```go
func assertArchived(t *testing.T, db *sql.DB, id string, want bool) {
	t.Helper()
	var got bool
	if err := db.QueryRowContext(context.Background(), `SELECT is_archived FROM agent_context WHERE id=$1`, id).Scan(&got); err != nil {
		t.Fatalf("read is_archived %s: %v", id, err)
	}
	if got != want {
		t.Errorf("row %s is_archived=%v, want %v", id, got, want)
	}
}

func seedEmbedding(t *testing.T, s *store.AgentContextStore, acID string) {
	t.Helper()
	vec := make([]float32, 384)
	vec[0] = 0.1
	if err := s.UpsertAgentContextEmbedding(context.Background(), store.AgentContextEmbeddingUpsert{
		ProjectID: acProj, AgentContextID: acID, ContentHash: "h", Embedding: vec,
	}); err != nil {
		t.Fatalf("seed embedding: %v", err)
	}
}

func assertEmbeddingExists(t *testing.T, db *sql.DB, acID string, want bool) {
	t.Helper()
	var n int
	if err := db.QueryRowContext(context.Background(), `SELECT count(*) FROM agent_context_embeddings WHERE agent_context_id=$1`, acID).Scan(&n); err != nil {
		t.Fatalf("count embeddings %s: %v", acID, err)
	}
	if (n > 0) != want {
		t.Errorf("embedding for %s exists=%v, want %v", acID, n > 0, want)
	}
}
```
Add `"database/sql"` to imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `go test -tags=integration ./internal/store/ -run TestRetention -v`
Expected: FAIL — `RunRetentionSweep` undefined.

- [ ] **Step 3: Implement `RunRetentionSweep`**

In `internal/store/agent_context.go`, add:
```go
// RetentionSweepResult reports what a single sweep archived/deleted.
type RetentionSweepResult struct {
	DedupArchived     int
	CapArchived       int
	EmbeddingsDeleted int
}

// RunRetentionSweep archives free-form duplicate and over-cap memories and drops
// their embeddings, in one transaction. mem_key rows and already-archived rows
// are never touched. updated_at is preserved (not bumped) so age and Pass-B
// ordering stay stable.
func (s *AgentContextStore) RunRetentionSweep(ctx context.Context, bucketCap int) (RetentionSweepResult, error) {
	var res RetentionSweepResult
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return res, fmt.Errorf("begin retention tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	archivedIDs := map[string]struct{}{}

	// Pass A — exact dedup within (project,user,scope,normalized content).
	dedupIDs, err := archiveByWindow(ctx, tx, `
		WITH ranked AS (
			SELECT id, ROW_NUMBER() OVER (
				PARTITION BY project_id, user_id, scope, md5(lower(btrim(content)))
				ORDER BY updated_at DESC, id
			) AS rn
			FROM agent_context
			WHERE is_archived = false AND mem_key IS NULL
		)
		UPDATE agent_context a SET is_archived = true
		FROM ranked r
		WHERE a.id = r.id AND r.rn > 1
		RETURNING a.id`)
	if err != nil {
		return res, fmt.Errorf("dedup pass: %w", err)
	}
	res.DedupArchived = len(dedupIDs)
	for _, id := range dedupIDs {
		archivedIDs[id] = struct{}{}
	}

	// Pass B — growth-bound within (project,user,scope); dedup'd rows already gone.
	capIDs, err := archiveByWindow(ctx, tx, `
		WITH ranked AS (
			SELECT id, ROW_NUMBER() OVER (
				PARTITION BY project_id, user_id, scope
				ORDER BY updated_at DESC, id
			) AS rn
			FROM agent_context
			WHERE is_archived = false AND mem_key IS NULL
		)
		UPDATE agent_context a SET is_archived = true
		FROM ranked r
		WHERE a.id = r.id AND r.rn > $1
		RETURNING a.id`, bucketCap)
	if err != nil {
		return res, fmt.Errorf("growth-bound pass: %w", err)
	}
	res.CapArchived = len(capIDs)
	for _, id := range capIDs {
		archivedIDs[id] = struct{}{}
	}

	// Drop embeddings for everything archived this tick.
	if len(archivedIDs) > 0 {
		ids := make([]string, 0, len(archivedIDs))
		for id := range archivedIDs {
			ids = append(ids, id)
		}
		ct, err := tx.ExecContext(ctx, `DELETE FROM agent_context_embeddings WHERE agent_context_id = ANY($1)`, pq.Array(ids))
		if err != nil {
			return res, fmt.Errorf("delete archived embeddings: %w", err)
		}
		n, _ := ct.RowsAffected()
		res.EmbeddingsDeleted = int(n)
	}

	if err := tx.Commit(); err != nil {
		return res, fmt.Errorf("commit retention: %w", err)
	}
	return res, nil
}

// archiveByWindow runs an archival UPDATE...RETURNING id and collects the ids.
func archiveByWindow(ctx context.Context, tx *sql.Tx, query string, args ...interface{}) ([]string, error) {
	rows, err := tx.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, rows.Err()
}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `go test -tags=integration ./internal/store/ -run TestRetention -v`
Expected: PASS (dedup, growth-bound, embedding delete + idempotent).

- [ ] **Step 5: Commit**

```bash
git add internal/store/agent_context.go internal/store/agent_context_retention_test.go
git commit -m "feat(daab): agent_context retention sweep (dedup + growth-bound + embedding drop)"
```

---

### Task 7: Retention worker (service, unit)

Ticker worker mirroring `OAuthRefreshWorker`, reading interval/cap from `MemorySettings`.

**Files:**
- Create: `internal/service/agent_context_retention.go`
- Test: `internal/service/agent_context_retention_test.go`

**Interfaces:**
- Consumes: `store.RetentionSweepResult`, `*MemorySettings` (Task 5).
- Produces:
  - `type retentionSweeper interface { RunRetentionSweep(ctx, bucketCap int) (store.RetentionSweepResult, error) }`
  - `func NewAgentContextRetentionWorker(sweeper retentionSweeper, settings *MemorySettings, logger *slog.Logger) *AgentContextRetentionWorker`
  - `(*AgentContextRetentionWorker).Start(ctx)`, `.Stop()`, and unexported `.sweepOnce(ctx)`.

- [ ] **Step 1: Write the failing test**

Create `internal/service/agent_context_retention_test.go`:
```go
package service

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/ennam/ennam-kg/internal/store"
)

type fakeSweeper struct {
	mu       sync.Mutex
	calls    int
	lastCap  int
	failNext bool
}

func (f *fakeSweeper) RunRetentionSweep(_ context.Context, cap int) (store.RetentionSweepResult, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls++
	f.lastCap = cap
	if f.failNext {
		return store.RetentionSweepResult{}, errors.New("boom")
	}
	return store.RetentionSweepResult{CapArchived: 1}, nil
}

func (f *fakeSweeper) count() int { f.mu.Lock(); defer f.mu.Unlock(); return f.calls }

func TestRetentionWorker_SweepOnceUsesConfiguredCap(t *testing.T) {
	sw := &fakeSweeper{}
	ms := &MemorySettings{reader: fakeMemReader{vals: nil}} // defaults
	w := NewAgentContextRetentionWorker(sw, ms, nil)
	w.sweepOnce(context.Background())
	if sw.count() != 1 {
		t.Fatalf("want 1 sweep, got %d", sw.count())
	}
	if sw.lastCap != 200 {
		t.Errorf("want default cap 200, got %d", sw.lastCap)
	}
}

func TestRetentionWorker_SweepOnceSurvivesError(t *testing.T) {
	sw := &fakeSweeper{failNext: true}
	w := NewAgentContextRetentionWorker(sw, nil, nil)
	w.sweepOnce(context.Background()) // must not panic
	if sw.count() != 1 {
		t.Errorf("sweep should have been attempted once, got %d", sw.count())
	}
}

func TestRetentionWorker_StartStopLifecycle(t *testing.T) {
	sw := &fakeSweeper{}
	w := NewAgentContextRetentionWorker(sw, nil, nil)
	w.interval = 10 * time.Millisecond
	w.Start(context.Background())
	// wait for at least one tick
	deadline := time.Now().Add(1 * time.Second)
	for time.Now().Before(deadline) && sw.count() == 0 {
		time.Sleep(5 * time.Millisecond)
	}
	w.Stop()
	if sw.count() == 0 {
		t.Errorf("worker should have swept at least once")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/service/ -run TestRetentionWorker -v`
Expected: FAIL — worker undefined.

- [ ] **Step 3: Implement the worker**

Create `internal/service/agent_context_retention.go`:
```go
package service

import (
	"context"
	"log/slog"
	"time"

	"github.com/ennam/ennam-kg/internal/store"
)

// retentionSweeper is the store surface the worker drives.
type retentionSweeper interface {
	RunRetentionSweep(ctx context.Context, bucketCap int) (store.RetentionSweepResult, error)
}

// AgentContextRetentionWorker periodically archives free-form duplicate/over-cap
// memories and drops their embeddings. Mirrors OAuthRefreshWorker.
type AgentContextRetentionWorker struct {
	store    retentionSweeper
	settings *MemorySettings
	interval time.Duration
	logger   *slog.Logger
	stopCh   chan struct{}
}

// NewAgentContextRetentionWorker resolves the tick interval from settings
// (default 1h) at construction.
func NewAgentContextRetentionWorker(sweeper retentionSweeper, settings *MemorySettings, logger *slog.Logger) *AgentContextRetentionWorker {
	if logger == nil {
		logger = slog.Default()
	}
	interval := time.Duration(defaultRetentionSweepIntervalSecs) * time.Second
	if settings != nil {
		interval = time.Duration(settings.SweepIntervalSeconds(context.Background())) * time.Second
	}
	return &AgentContextRetentionWorker{
		store:    sweeper,
		settings: settings,
		interval: interval,
		logger:   logger,
		stopCh:   make(chan struct{}),
	}
}

// Start runs the sweep loop until Stop() or ctx cancellation.
func (w *AgentContextRetentionWorker) Start(ctx context.Context) {
	go func() {
		w.logger.Info("agent_context retention worker started", "interval", w.interval)
		ticker := time.NewTicker(w.interval)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				w.sweepOnce(ctx)
			case <-w.stopCh:
				w.logger.Info("agent_context retention worker stopped")
				return
			case <-ctx.Done():
				w.logger.Info("agent_context retention worker context cancelled")
				return
			}
		}
	}()
}

// Stop signals the worker to stop.
func (w *AgentContextRetentionWorker) Stop() { close(w.stopCh) }

// sweepOnce reads the current bucket cap and runs one sweep.
func (w *AgentContextRetentionWorker) sweepOnce(ctx context.Context) {
	cap := defaultMemoryBucketCap
	if w.settings != nil {
		cap = w.settings.BucketCap(ctx)
	}
	res, err := w.store.RunRetentionSweep(ctx, cap)
	if err != nil {
		w.logger.ErrorContext(ctx, "agent_context retention sweep failed", "error", err)
		return
	}
	if res.DedupArchived+res.CapArchived+res.EmbeddingsDeleted > 0 {
		w.logger.InfoContext(ctx, "agent_context retention sweep",
			"dedup_archived", res.DedupArchived,
			"cap_archived", res.CapArchived,
			"embeddings_deleted", res.EmbeddingsDeleted,
			"bucket_cap", cap,
		)
	}
}
```

- [ ] **Step 4: Run test to verify pass**

Run: `go test -race ./internal/service/ -run TestRetentionWorker -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/service/agent_context_retention.go internal/service/agent_context_retention_test.go
git commit -m "feat(daab): agent_context retention background worker"
```

---

### Task 8: Composition — wire half-life into recall + start the worker

Inject `MemorySettings` into the recall handler and start the retention worker in the server.

**Files:**
- Modify: `internal/handler/agent_context.go` (constructor + `Recall`)
- Modify: `internal/handler/agent_context_test.go` (and any other `NewAgentContextHandler` call sites — pass `nil`)
- Modify: `cmd/kg-server/main.go` (relocate handler construction after settings; wire reader; start worker)

**Interfaces:**
- Consumes: `*service.MemorySettings` (Task 5), `store.RetentionSweepResult`/`RunRetentionSweep` (Task 6), `service.NewAgentContextRetentionWorker` (Task 7).
- Produces: recall passes `HalfLifeHours` into `AgentRecallParams`; the worker runs for the server lifetime.

- [ ] **Step 1: Add a settings dependency to the handler**

In `internal/handler/agent_context.go`, define a minimal interface and extend the struct/constructor:
```go
// recallSettings supplies runtime recall tuning (half-life).
type recallSettings interface {
	RecallHalfLifeHours(ctx context.Context) float64
}
```
Add `settings recallSettings` to `AgentContextHandler`, and update the constructor:
```go
func NewAgentContextHandler(s agentContextStore, embedder QueryEmbedder, pub agentContextEmbedPublisher, settings recallSettings, logger *slog.Logger) *AgentContextHandler {
	return &AgentContextHandler{store: s, embedder: embedder, publisher: pub, settings: settings, logger: logger}
}
```
In `Recall`, compute the half-life and pass it into the params (insert before the `RecallAgentContext` call and add the field):
```go
	var halfLife float64
	if h.settings != nil {
		halfLife = h.settings.RecallHalfLifeHours(r.Context())
	}
	rows, err := h.store.RecallAgentContext(r.Context(), store.AgentRecallParams{
		ProjectID:      projectID,
		UserID:         userID,
		QueryEmbedding: qvec,
		Query:          body.Query,
		Kind:           body.Kind,
		Scope:          body.Scope,
		Tags:           body.Tags,
		TopK:           body.TopK,
		HalfLifeHours:  halfLife,
	})
```

- [ ] **Step 2: Fix handler test constructors (build first)**

Run: `go build ./... ` — it will fail at `NewAgentContextHandler` call sites. Update each (e.g. in `internal/handler/agent_context_test.go` and `agent_context_userscope_test.go`) to pass `nil` for the new `settings` argument:
```go
h := NewAgentContextHandler(fs, embedder, pub, nil, logger)
```
(Match the actual local variable names at each site.)

- [ ] **Step 3: Run handler tests to confirm green**

Run: `go test ./internal/handler/ -run AgentContext -v`
Expected: PASS (param-wiring tests unaffected by `nil` settings — half-life 0 ⇒ store default).

- [ ] **Step 4: Wire in `cmd/kg-server/main.go`**

`acStore` (line 393) stays. **Move** the handler construction + route registration (current lines 394–395) to **after** `settingsStore`/`settingsSvc` are created (after line 536), and pass a `MemorySettings`:
```go
	memSettings := service.NewMemorySettings(settingsStore)
	acHandler := handler.NewAgentContextHandler(acStore, embedClient, agentCtxPub, memSettings, logger)
	acHandler.RegisterRoutes(apiMux)
```
Then start the retention worker near the other background workers (after line 889, beside the oauth worker), using the existing `acStore`:
```go
	retentionWorker := service.NewAgentContextRetentionWorker(acStore, memSettings, logger)
	retentionWorker.Start(context.Background())
	defer retentionWorker.Stop()
```

- [ ] **Step 5: Build and run the full unit + integration suite**

Run:
```bash
go build ./...
go test -race ./internal/store/ ./internal/service/ ./internal/handler/
go test -tags=integration ./internal/store/ -run 'TestRecall_|TestRetention'
```
Expected: build OK; unit packages PASS; integration recall + retention tests PASS. (Pre-existing unrelated failures — e.g. `TestSectionNeighbors_ParentChildrenSiblings` `chk_title_min_length` fixture — may appear; confirm they are not in the files this plan touched before treating as a regression.)

- [ ] **Step 6: Smoke-test the worker boots**

Run: `docker compose up -d --build kg-server && docker compose logs kg-server | grep "retention worker started"`
Expected: a log line `agent_context retention worker started interval=1h0m0s` (or the configured interval).

- [ ] **Step 7: Commit**

```bash
git add internal/handler/agent_context.go internal/handler/agent_context_test.go internal/handler/agent_context_userscope_test.go cmd/kg-server/main.go
git commit -m "feat(daab): wire recall half-life + start retention worker"
```

---

## Post-implementation

- Update the doc-comment in `internal/handler/agent_context_userscope_test.go` to the new recall contract (user sees own user rows **+** shared project/agent rows) — see spec §7.1. (Folded into Task 8 Step 2's edits to that file; verify the comment, not just the constructor.)
- File the deferred follow-up tickets from spec §10 (usage-based decay using `last_recalled_at`; un-archive/recovery + hard-delete TTL; semantic dedup; `audit_trail` enum migration for the sweep; capture-contract dedup ownership).
- Write a Serena checkpoint (`mcp__serena__write_memory("checkpoint/<agent>-2026-06-28", …)`).

## Self-Review notes (author)

- **Spec coverage:** migration §6 → T1; recall decay §7.3 → T2; scope-aware filter §7.1 → T3; over-fetch + mem_key §7.2/§7.3 → T4; config §9 → T5 (Go-defaults + system_settings, no YAML — documented deviation); sweep passes + embedding drop §8 → T6; worker §8/§5 → T7; wiring §5 → T8. All covered.
- **Type consistency:** `RetentionSweepResult{DedupArchived,CapArchived,EmbeddingsDeleted}`, `RunRetentionSweep(ctx,bucketCap)`, `fuseAgentRecall(lists,topK,now,halfLifeHours)`, `MemorySettings.{RecallHalfLifeHours,BucketCap,SweepIntervalSeconds}` used identically across tasks.
- **Defaults:** half-life 720h, cap 200, interval 3600s defined once in `service/memory_settings.go`; the store's `defaultRecallHalfLifeHours=720` is the independent fallback when the handler passes 0 (kept in sync; both 720).
