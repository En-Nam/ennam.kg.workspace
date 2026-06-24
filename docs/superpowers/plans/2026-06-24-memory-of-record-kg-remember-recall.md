# Memory-of-record (`kg_remember` / `kg_recall`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a project-scoped memory-of-record in DAAB — an `agent_context` table plus `kg_remember` (write, durable embed-on-write) and `kg_recall` (read, hybrid RRF) MCP/REST tools.

**Architecture:** A new sibling table `agent_context` (+ `agent_context_embeddings vector(384)`) stores memories. `kg_remember` writes a row synchronously and enqueues a 384-dim embed job on a dedicated Redis queue; a Python worker embeds the content (e5 `passage`) and POSTs the vector back to a Go batch endpoint. `kg_recall` embeds the query (e5 `query`, sync), runs a semantic + lexical query scoped by `project_id`, fuses with Reciprocal Rank Fusion, and returns raw windowed snippets — no LLM summary.

**Tech Stack:** Go (`net/http`, `database/sql`, `lib/pq`, pgvector), PostgreSQL 16 + pgvector, Redis (raw RESP publisher), Python 3.12 (worker, `sentence-transformers` e5, `httpx`).

**Spec:** `docs/superpowers/specs/2026-06-24-memory-of-record-kg-remember-recall-design.md` (read it first).

## Global Constraints

- **Repos are nested git repos.** Go code: `ennam.kg.go/` (commit with `git -C ennam.kg.go`). Python: `ennam.kg.python/`. Each has its own history; the workspace-root HEAD will not move for sub-project commits.
- **Embedding dimension is 384, Python-local only** (`intfloat/multilingual-e5-small`). NEVER use the Go `generateDescription` / 1536-dim `text-embedding-3-small` path for `agent_context`.
- **e5 asymmetric prefix:** write side embeds with `encode_passage` (`"passage: "`); recall side embeds with `encode_query` (`"query: "`, the default of the Python `/api/v1/embeddings` endpoint). Mismatch silently degrades recall.
- **pgvector is passed as a text literal** via the existing `float32SliceToVectorString` helper + a `$N::vector` SQL cast. Do NOT add a pgvector driver dependency.
- **No opaque-UUID tool args.** `kg_remember`/`kg_recall` MUST NOT accept `project_id`/`user_id`/`source_agent` — resolve them from the authenticated API key (`DeveloperIdentity`).
- **`user_id` is nullable this slice.** Wire the filter but do not rely on user-level isolation (gated on the D3 consumer-key class, out of scope).
- **`kg_recall` soft-fails:** any embed/store error returns `{"results": []}` with HTTP 200 and a logged error — never a 5xx (recall must not break an agent's turn).
- **DB-backed tests** use the `//go:build integration` tag and `KG_TEST_DSN`; they run in CI / local Docker, not on a bare dev box. DB-free unit tests must pass anywhere.
- **Conventions:** match existing store/handler/queue patterns exactly (constructors take `*sql.DB`; handlers expose `RegisterRoutes(mux)`; response via `writeJSON`/`errorResponse`). Per-file ≤ 800 lines.

---

## File Structure

**Create:**
- `ennam.kg.go/db/migrations/000068_agent_context.up.sql` / `.down.sql` — schema, trigger, indexes.
- `ennam.kg.go/internal/store/agent_context.go` — `AgentContextStore`: upsert, recall (semantic+lexical+fusion), embedding upsert.
- `ennam.kg.go/internal/store/agent_context_test.go` — DB-free fusion test + `//go:build integration` store tests.
- `ennam.kg.go/internal/handler/agent_context.go` — `AgentContextHandler`: `kg_remember`, `kg_recall`, batch-embeddings endpoint.
- `ennam.kg.go/internal/handler/agent_context_test.go` — DB-free handler tests (fake store/embedder/publisher).
- `ennam.kg.go/internal/handler/agent_context_isolation_integration_test.go` — cross-project isolation (`//go:build integration`).
- `ennam.kg.go/internal/queue/agent_context_messages.go` — `AgentContextPublisher` + message.
- `ennam.kg.go/internal/queue/agent_context_messages_test.go` — queue-name + marshal test.
- `ennam.kg.python/tests/test_embed_agent_context_handler.py` — worker handler unit test.

**Modify:**
- `ennam.kg.go/internal/bridge/schema.go` — add `kg_remember` + `kg_recall` schemas.
- `ennam.kg.go/internal/bridge/client.go` — add `kg_remember` + `kg_recall` routes.
- `ennam.kg.go/internal/bridge/{schema_test,handler_test,client_test}.go` + the integration tool-enum test — bump invariant counts.
- `ennam.kg.go/cmd/kg-server/main.go` — wire `AgentContextHandler` + publisher into `buildRouter`.
- `ennam.kg.python/src/ennam_kg/config.py` — add `agent_context_queue_name`.
- `ennam.kg.python/src/ennam_kg/worker.py` — 4th consumer + `embed_agent_context` branch + model instance.
- `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py` — `upsert_agent_context_embeddings`.

---

## Task 1: Migration 000068 — `agent_context` schema

**Files:**
- Create: `ennam.kg.go/db/migrations/000068_agent_context.up.sql`
- Create: `ennam.kg.go/db/migrations/000068_agent_context.down.sql`

**Interfaces:**
- Produces: tables `agent_context` (cols: `id, project_id, user_id, source_agent, kind, scope, mem_key, content, tags, search_vector, is_archived, created_at, updated_at`) and `agent_context_embeddings` (`id, project_id, agent_context_id, content_hash, embedding vector(384), created_at, updated_at`); trigger `trg_agent_context_search_vector`; partial unique index `uq_agent_context_memkey`.

- [ ] **Step 1: Confirm the vector index type used by migration 000055**

Run: `grep -i "USING\|vector_cosine\|hnsw\|ivfflat" ennam.kg.go/db/migrations/000055_*.up.sql`
Expected: shows the index DDL for `knowledge_node_embeddings`. Use the SAME index type/opclass in Step 2 (do not introduce `hnsw` if 000055 uses `ivfflat`, or vice-versa). The DDL below assumes `hnsw vector_cosine_ops`; adjust to match.

- [ ] **Step 2: Write the up migration**

Create `ennam.kg.go/db/migrations/000068_agent_context.up.sql`:

```sql
-- agent_context: memory-of-record sibling table (NOT graph nodes).
-- See docs/superpowers/specs/2026-06-24-memory-of-record-kg-remember-recall-design.md
CREATE TABLE IF NOT EXISTS agent_context (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id    UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id       UUID,
    source_agent  TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('preference','decision','fact','correction')),
    scope         TEXT NOT NULL CHECK (scope IN ('project','user','agent')),
    mem_key       TEXT,
    content       TEXT NOT NULL,
    tags          TEXT[] NOT NULL DEFAULT '{}',
    search_vector tsvector,
    is_archived   BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_context_project       ON agent_context (project_id);
CREATE INDEX IF NOT EXISTS idx_agent_context_project_user  ON agent_context (project_id, user_id);
CREATE INDEX IF NOT EXISTS idx_agent_context_kind          ON agent_context (kind);
CREATE INDEX IF NOT EXISTS idx_agent_context_tags          ON agent_context USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_agent_context_search        ON agent_context USING GIN (search_vector);

-- At most one row per (project, user, scope, mem_key) when mem_key is set (dedup guard).
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_context_memkey
    ON agent_context (project_id, COALESCE(user_id, '00000000-0000-0000-0000-000000000000'::uuid), scope, mem_key)
    WHERE mem_key IS NOT NULL;

CREATE OR REPLACE FUNCTION update_agent_context_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.content, '')), 'A') ||
        setweight(to_tsvector('english', array_to_string(NEW.tags, ' ')), 'B');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_agent_context_search_vector
    BEFORE INSERT OR UPDATE OF content, tags ON agent_context
    FOR EACH ROW
    EXECUTE FUNCTION update_agent_context_search_vector();

CREATE TABLE IF NOT EXISTS agent_context_embeddings (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id       UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_context_id UUID NOT NULL REFERENCES agent_context(id) ON DELETE CASCADE,
    content_hash     TEXT NOT NULL,
    embedding        vector(384) NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT agent_context_embeddings_ctx_key UNIQUE (agent_context_id)
);

-- Match the index type/opclass of migration 000055 (see Step 1).
CREATE INDEX IF NOT EXISTS idx_agent_context_emb_hnsw
    ON agent_context_embeddings USING hnsw (embedding vector_cosine_ops);
```

- [ ] **Step 3: Write the down migration**

Create `ennam.kg.go/db/migrations/000068_agent_context.down.sql`:

```sql
DROP TABLE IF EXISTS agent_context_embeddings;
DROP TRIGGER IF EXISTS trg_agent_context_search_vector ON agent_context;
DROP FUNCTION IF EXISTS update_agent_context_search_vector();
DROP TABLE IF EXISTS agent_context;
```

- [ ] **Step 4: Verify migration applies and reverts (requires a DB)**

Run (with a reachable Postgres, e.g. `docker compose up -d postgres`):
`cd ennam.kg.go && make migrate-up && make migrate-down && make migrate-up`
Expected: up → down → up all succeed with no error. (If `make` targets differ, use the project's golang-migrate command from `ennam.kg.go/CLAUDE.md`.) If no DB is available, state that explicitly and defer this step to CI.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add db/migrations/000068_agent_context.up.sql db/migrations/000068_agent_context.down.sql
git -C ennam.kg.go commit -m "feat(agent_context): migration 000068 — memory-of-record tables"
```

---

## Task 2: Store — upsert + embedding upsert

**Files:**
- Create: `ennam.kg.go/internal/store/agent_context.go`
- Test: `ennam.kg.go/internal/store/agent_context_test.go` (integration-tagged portion)

**Interfaces:**
- Consumes: existing `float32SliceToVectorString` (store package), `github.com/lib/pq`.
- Produces:
  - `type AgentContextUpsert struct { ProjectID, UserID, SourceAgent, Kind, Scope, MemKey, Content string; Tags []string }`
  - `type AgentContextEmbeddingUpsert struct { ProjectID, AgentContextID, ContentHash string; Embedding []float32 }`
  - `func NewAgentContextStore(db *sql.DB) *AgentContextStore`
  - `func (s *AgentContextStore) UpsertAgentContext(ctx, AgentContextUpsert) (id string, created bool, err error)`
  - `func (s *AgentContextStore) UpsertAgentContextEmbedding(ctx, AgentContextEmbeddingUpsert) error`

- [ ] **Step 1: Write the failing integration test**

Create `ennam.kg.go/internal/store/agent_context_test.go`:

```go
//go:build integration

package store_test

import (
	"context"
	"database/sql"
	"testing"

	"github.com/ennam/ennam-kg/internal/store"
	_ "github.com/lib/pq"
)

const (
	acProj = "cccccccc-0000-0000-0000-000000000010"
)

func acDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := getTestDSN(t) // reuse the existing store-package integration DSN helper; if absent, read KG_TEST_DSN directly
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		t.Fatalf("open db: %v", err)
	}
	return db
}

func acSeedProject(t *testing.T, db *sql.DB) {
	t.Helper()
	ctx := context.Background()
	cleanup := func() {
		db.ExecContext(ctx, `DELETE FROM projects WHERE id = $1`, acProj)
	}
	cleanup()
	t.Cleanup(cleanup)
	if _, err := db.ExecContext(ctx, `INSERT INTO projects (id, name) VALUES ($1, 'ac-test')`, acProj); err != nil {
		t.Fatalf("seed project: %v", err)
	}
}

func TestUpsertAgentContext_DedupOnMemKey(t *testing.T) {
	db := acDB(t)
	acSeedProject(t, db)
	s := store.NewAgentContextStore(db)
	ctx := context.Background()

	id1, created1, err := s.UpsertAgentContext(ctx, store.AgentContextUpsert{
		ProjectID: acProj, SourceAgent: "agentA", Kind: "preference", Scope: "project",
		MemKey: "k1", Content: "prefers tabs", Tags: []string{"style"},
	})
	if err != nil || !created1 {
		t.Fatalf("first upsert: id=%s created=%v err=%v", id1, created1, err)
	}

	id2, created2, err := s.UpsertAgentContext(ctx, store.AgentContextUpsert{
		ProjectID: acProj, SourceAgent: "agentA", Kind: "preference", Scope: "project",
		MemKey: "k1", Content: "prefers spaces", Tags: []string{"style"},
	})
	if err != nil {
		t.Fatalf("second upsert err: %v", err)
	}
	if created2 {
		t.Errorf("second upsert with same mem_key should UPDATE, got created=true")
	}
	if id2 != id1 {
		t.Errorf("upsert should reuse row id: id1=%s id2=%s", id1, id2)
	}

	var content string
	if err := db.QueryRowContext(ctx, `SELECT content FROM agent_context WHERE id=$1`, id1).Scan(&content); err != nil {
		t.Fatalf("read back: %v", err)
	}
	if content != "prefers spaces" {
		t.Errorf("content not replaced: got %q", content)
	}
}

func TestUpsertAgentContext_NoMemKeyAlwaysInserts(t *testing.T) {
	db := acDB(t)
	acSeedProject(t, db)
	s := store.NewAgentContextStore(db)
	ctx := context.Background()

	idA, _, err := s.UpsertAgentContext(ctx, store.AgentContextUpsert{
		ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "x",
	})
	if err != nil {
		t.Fatal(err)
	}
	idB, createdB, err := s.UpsertAgentContext(ctx, store.AgentContextUpsert{
		ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "x",
	})
	if err != nil {
		t.Fatal(err)
	}
	if !createdB || idA == idB {
		t.Errorf("no mem_key must always insert a new row: idA=%s idB=%s created=%v", idA, idB, createdB)
	}
}
```

Note: `getTestDSN` — reuse whatever helper the store package's existing integration tests use; if none exists, replace with `dsn := os.Getenv("KG_TEST_DSN"); if dsn == "" { t.Skip("KG_TEST_DSN not set") }`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ennam.kg.go && KG_TEST_DSN="$KG_TEST_DSN" go test -tags=integration ./internal/store/ -run TestUpsertAgentContext -v`
Expected: FAIL to compile — `undefined: store.NewAgentContextStore`. (If no DB, the build failure alone confirms RED.)

- [ ] **Step 3: Write the store implementation**

Create `ennam.kg.go/internal/store/agent_context.go`:

```go
package store

import (
	"context"
	"database/sql"
	"fmt"

	"github.com/lib/pq"
)

// AgentContextUpsert is the input to UpsertAgentContext (the kg_remember write path).
type AgentContextUpsert struct {
	ProjectID   string
	UserID      string // empty -> NULL
	SourceAgent string
	Kind        string
	Scope       string
	MemKey      string // empty -> no dedup, always insert
	Content     string
	Tags        []string
}

// AgentContextEmbeddingUpsert is one memory embedding row (worker callback path).
type AgentContextEmbeddingUpsert struct {
	ProjectID      string
	AgentContextID string
	ContentHash    string
	Embedding      []float32
}

// AgentContextStore manages the agent_context memory-of-record table.
type AgentContextStore struct {
	db *sql.DB
}

// NewAgentContextStore creates an AgentContextStore.
func NewAgentContextStore(db *sql.DB) *AgentContextStore {
	return &AgentContextStore{db: db}
}

// UpsertAgentContext inserts a memory, or replaces the existing row with the same
// (project_id, user_id, scope, mem_key) when mem_key is set. Returns the row id and
// whether a new row was created (false = an existing row was updated).
func (s *AgentContextStore) UpsertAgentContext(ctx context.Context, m AgentContextUpsert) (string, bool, error) {
	var userID interface{}
	if m.UserID != "" {
		userID = m.UserID
	}
	tags := m.Tags
	if tags == nil {
		tags = []string{}
	}

	if m.MemKey == "" {
		var id string
		err := s.db.QueryRowContext(ctx, `
			INSERT INTO agent_context (project_id, user_id, source_agent, kind, scope, mem_key, content, tags)
			VALUES ($1, $2, $3, $4, $5, NULL, $6, $7)
			RETURNING id`,
			m.ProjectID, userID, m.SourceAgent, m.Kind, m.Scope, m.Content, pq.Array(tags),
		).Scan(&id)
		if err != nil {
			return "", false, fmt.Errorf("insert agent_context: %w", err)
		}
		return id, true, nil
	}

	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return "", false, fmt.Errorf("begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	var id string
	err = tx.QueryRowContext(ctx, `
		UPDATE agent_context
		   SET content = $1, tags = $2, kind = $3, source_agent = $4, updated_at = now()
		 WHERE project_id = $5
		   AND user_id IS NOT DISTINCT FROM $6
		   AND scope = $7
		   AND mem_key = $8
		RETURNING id`,
		m.Content, pq.Array(tags), m.Kind, m.SourceAgent,
		m.ProjectID, userID, m.Scope, m.MemKey,
	).Scan(&id)
	switch {
	case err == nil:
		if err := tx.Commit(); err != nil {
			return "", false, fmt.Errorf("commit update: %w", err)
		}
		return id, false, nil
	case err != sql.ErrNoRows:
		return "", false, fmt.Errorf("update agent_context: %w", err)
	}

	err = tx.QueryRowContext(ctx, `
		INSERT INTO agent_context (project_id, user_id, source_agent, kind, scope, mem_key, content, tags)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
		RETURNING id`,
		m.ProjectID, userID, m.SourceAgent, m.Kind, m.Scope, m.MemKey, m.Content, pq.Array(tags),
	).Scan(&id)
	if err != nil {
		return "", false, fmt.Errorf("insert agent_context: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return "", false, fmt.Errorf("commit insert: %w", err)
	}
	return id, true, nil
}

// UpsertAgentContextEmbedding replaces the 384-dim embedding for a memory.
func (s *AgentContextStore) UpsertAgentContextEmbedding(ctx context.Context, e AgentContextEmbeddingUpsert) error {
	vecStr := float32SliceToVectorString(e.Embedding)
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO agent_context_embeddings (project_id, agent_context_id, content_hash, embedding, updated_at)
		VALUES ($1, $2, $3, $4::vector, now())
		ON CONFLICT (agent_context_id) DO UPDATE SET
			content_hash = EXCLUDED.content_hash,
			embedding = EXCLUDED.embedding,
			updated_at = now()`,
		e.ProjectID, e.AgentContextID, e.ContentHash, vecStr,
	)
	if err != nil {
		return fmt.Errorf("upsert agent_context embedding %s: %w", e.AgentContextID, err)
	}
	return nil
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ennam.kg.go && go build ./... && KG_TEST_DSN="$KG_TEST_DSN" go test -tags=integration ./internal/store/ -run TestUpsertAgentContext -v`
Expected: `go build` succeeds; with a DB, both tests PASS. (Without a DB: confirm `go build ./...` and `go vet ./internal/store/` pass; defer the DB run to CI and say so.)

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/store/agent_context.go internal/store/agent_context_test.go
git -C ennam.kg.go commit -m "feat(agent_context): store upsert + embedding upsert"
```

---

## Task 3: Store — hybrid recall + deterministic fusion

**Files:**
- Modify: `ennam.kg.go/internal/store/agent_context.go`
- Test: `ennam.kg.go/internal/store/agent_context_test.go` (add DB-free fusion test + integration recall test)

**Interfaces:**
- Consumes: `SearchResult` (store package), `float32SliceToVectorString`, `github.com/lib/pq`.
- Produces:
  - `type AgentRecallParams struct { ProjectID, UserID string; QueryEmbedding []float32; Query, Kind, Scope string; Tags []string; TopK int }`
  - `func (s *AgentContextStore) RecallAgentContext(ctx, AgentRecallParams) ([]SearchResult, error)` — returned rows carry: `ID`=memory id, `NodeType`=kind, `Scope`=scope, `Properties`=`{"content","tags","source_agent"}`, `Headline`=lexical snippet, `Rank`=fused RRF score, `CreatedAt`/`UpdatedAt`. Order: fused score desc → updated_at desc → id asc.

- [ ] **Step 1: Write the failing DB-free fusion test**

Add to `ennam.kg.go/internal/store/agent_context_test.go` a SECOND file section — but the fusion test must NOT be behind the integration tag. Create a separate file `ennam.kg.go/internal/store/agent_context_fusion_test.go` (no build tag) so it runs without a DB:

```go
package store

import (
	"testing"
	"time"
)

func TestFuseAgentRecall_DeterministicOrder(t *testing.T) {
	older := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	newer := time.Date(2026, 2, 1, 0, 0, 0, 0, time.UTC)

	// "b" appears in both lists (rank 1 then rank 1) → highest fused score.
	// "a" appears once at rank 1; "c" once at rank 2.
	semantic := []SearchResult{{ID: "b", UpdatedAt: newer}, {ID: "c", UpdatedAt: older}}
	lexical := []SearchResult{{ID: "b", UpdatedAt: newer}, {ID: "a", UpdatedAt: older}}

	out := fuseAgentRecall([][]SearchResult{semantic, lexical}, 10)

	if len(out) != 3 {
		t.Fatalf("want 3 fused, got %d", len(out))
	}
	if out[0].ID != "b" {
		t.Errorf("b should rank first (appears in both lists): got %s", out[0].ID)
	}
	// fused score must be written onto Rank
	if out[0].Rank <= out[1].Rank {
		t.Errorf("Rank must be the fused score in descending order: %v", out)
	}
}

func TestFuseAgentRecall_TieBreakByIDWhenScoreAndTimeEqual(t *testing.T) {
	ts := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	// Two single-appearance rows at the same rank → equal score + equal time.
	a := []SearchResult{{ID: "zeta", UpdatedAt: ts}}
	b := []SearchResult{{ID: "alpha", UpdatedAt: ts}}
	out := fuseAgentRecall([][]SearchResult{a, b}, 10)
	if out[0].ID != "alpha" {
		t.Errorf("equal score+time must tie-break by id asc: got %s first", out[0].ID)
	}
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestFuseAgentRecall -v`
Expected: FAIL to compile — `undefined: fuseAgentRecall`.

- [ ] **Step 3: Implement recall + fusion**

Append to `ennam.kg.go/internal/store/agent_context.go` (add `"sort"` to the import block):

```go
// AgentRecallParams are the inputs to RecallAgentContext (the kg_recall read path).
type AgentRecallParams struct {
	ProjectID      string
	UserID         string    // empty -> no user filter
	QueryEmbedding []float32 // empty -> skip the semantic branch
	Query          string    // text for the lexical (FTS) branch
	Kind           string
	Scope          string
	Tags           []string
	TopK           int
}

const agentRecallRRFk = 60

// RecallAgentContext runs the semantic + lexical branches, fuses them with RRF,
// and returns the top-K in fully deterministic order.
func (s *AgentContextStore) RecallAgentContext(ctx context.Context, p AgentRecallParams) ([]SearchResult, error) {
	if p.TopK <= 0 {
		p.TopK = 8
	}
	sem, err := s.recallSemantic(ctx, p)
	if err != nil {
		return nil, err
	}
	lex, err := s.recallLexical(ctx, p)
	if err != nil {
		return nil, err
	}
	return fuseAgentRecall([][]SearchResult{sem, lex}, p.TopK), nil
}

// agentRecallFilters appends the optional WHERE clauses (user/kind/scope/tags)
// shared by both branches and returns the SQL fragment plus the grown args.
func agentRecallFilters(p AgentRecallParams, args []interface{}) (string, []interface{}) {
	clause := ""
	if p.UserID != "" {
		args = append(args, p.UserID)
		clause += fmt.Sprintf(" AND a.user_id = $%d", len(args))
	}
	if p.Kind != "" {
		args = append(args, p.Kind)
		clause += fmt.Sprintf(" AND a.kind = $%d", len(args))
	}
	if p.Scope != "" {
		args = append(args, p.Scope)
		clause += fmt.Sprintf(" AND a.scope = $%d", len(args))
	}
	if len(p.Tags) > 0 {
		args = append(args, pq.Array(p.Tags))
		clause += fmt.Sprintf(" AND a.tags && $%d", len(args))
	}
	return clause, args
}

const agentSelectCols = `
	a.id, a.project_id, a.kind AS node_type, '' AS title, '' AS status,
	jsonb_build_object('content', a.content, 'tags', a.tags, 'source_agent', a.source_agent) AS properties,
	a.scope, 0 AS version, a.source_agent AS created_by,
	a.created_at, a.updated_at, NULL::text AS session_id`

func (s *AgentContextStore) recallSemantic(ctx context.Context, p AgentRecallParams) ([]SearchResult, error) {
	if len(p.QueryEmbedding) == 0 {
		return nil, nil
	}
	vecStr := float32SliceToVectorString(p.QueryEmbedding)
	args := []interface{}{vecStr, p.ProjectID}
	where, args := agentRecallFilters(p, args)
	args = append(args, p.TopK)
	q := fmt.Sprintf(`
		SELECT %s,
			(1 - (e.embedding <=> $1::vector))::float8 AS rank,
			'' AS headline
		FROM agent_context_embeddings e
		JOIN agent_context a ON a.id = e.agent_context_id
		WHERE a.project_id = $2 AND a.is_archived = false%s
		ORDER BY e.embedding <=> $1::vector
		LIMIT $%d`, agentSelectCols, where, len(args))
	return s.scanAgentResults(ctx, q, args...)
}

func (s *AgentContextStore) recallLexical(ctx context.Context, p AgentRecallParams) ([]SearchResult, error) {
	args := []interface{}{p.Query, p.ProjectID}
	where, args := agentRecallFilters(p, args)
	args = append(args, p.TopK)
	q := fmt.Sprintf(`
		SELECT %s,
			ts_rank(a.search_vector, plainto_tsquery('english', $1))::float8 AS rank,
			ts_headline('english', a.content, plainto_tsquery('english', $1),
				'StartSel=<mark>, StopSel=</mark>, MaxWords=35, MinWords=15, MaxFragments=2') AS headline
		FROM agent_context a
		WHERE a.project_id = $2 AND a.is_archived = false
			AND a.search_vector @@ plainto_tsquery('english', $1)%s
		ORDER BY ts_rank(a.search_vector, plainto_tsquery('english', $1)) DESC
		LIMIT $%d`, agentSelectCols, where, len(args))
	return s.scanAgentResults(ctx, q, args...)
}

func (s *AgentContextStore) scanAgentResults(ctx context.Context, query string, args ...interface{}) ([]SearchResult, error) {
	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("agent_context recall: %w", err)
	}
	defer rows.Close()
	var out []SearchResult
	for rows.Next() {
		var r SearchResult
		if err := rows.Scan(
			&r.ID, &r.ProjectID, &r.NodeType, &r.Title, &r.Status,
			&r.Properties, &r.Scope, &r.Version, &r.CreatedBy,
			&r.CreatedAt, &r.UpdatedAt, &r.SessionID, &r.Rank, &r.Headline,
		); err != nil {
			return nil, fmt.Errorf("scan agent_context result: %w", err)
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// fuseAgentRecall merges branch results with Reciprocal Rank Fusion (k=60, the
// same constant as store/rrf.go) and returns the top-K in fully deterministic
// order: fused score desc, then updated_at desc, then id asc. It reimplements
// the small RRF formula (rather than calling ReciprocalRankFusion) so the fused
// score can be written onto each row's Rank and its ties broken by id — the
// shared helper exposes neither. rrf.go is left untouched for knowledge search.
func fuseAgentRecall(lists [][]SearchResult, topK int) []SearchResult {
	score := make(map[string]float64)
	keep := make(map[string]SearchResult)
	for _, list := range lists {
		for i, row := range list {
			score[row.ID] += 1.0 / float64(agentRecallRRFk+i+1)
			if _, ok := keep[row.ID]; !ok {
				keep[row.ID] = row
			}
		}
	}
	out := make([]SearchResult, 0, len(keep))
	for id := range keep {
		row := keep[id]
		row.Rank = score[id]
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

- [ ] **Step 4: Run the DB-free fusion test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestFuseAgentRecall -v`
Expected: PASS (both fusion tests).

- [ ] **Step 5: Add an integration recall test**

Add to `ennam.kg.go/internal/store/agent_context_test.go` (integration-tagged file):

```go
func TestRecallAgentContext_LexicalFindsUnembeddedRow(t *testing.T) {
	db := acDB(t)
	acSeedProject(t, db)
	s := store.NewAgentContextStore(db)
	ctx := context.Background()

	id, _, err := s.UpsertAgentContext(ctx, store.AgentContextUpsert{
		ProjectID: acProj, SourceAgent: "a", Kind: "decision", Scope: "project",
		Content: "we chose durable queue for embed on write",
	})
	if err != nil {
		t.Fatal(err)
	}

	// No embedding written yet → semantic branch is empty; lexical must still find it.
	res, err := s.RecallAgentContext(ctx, store.AgentRecallParams{
		ProjectID: acProj, Query: "durable queue", TopK: 5,
	})
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, r := range res {
		if r.ID == id {
			found = true
		}
	}
	if !found {
		t.Errorf("lexical recall must surface unembedded row %s; got %d results", id, len(res))
	}
}

func TestRecallAgentContext_ArchivedExcluded(t *testing.T) {
	db := acDB(t)
	acSeedProject(t, db)
	s := store.NewAgentContextStore(db)
	ctx := context.Background()

	id, _, _ := s.UpsertAgentContext(ctx, store.AgentContextUpsert{
		ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "archived secret token",
	})
	if _, err := db.ExecContext(ctx, `UPDATE agent_context SET is_archived = true WHERE id = $1`, id); err != nil {
		t.Fatal(err)
	}
	res, _ := s.RecallAgentContext(ctx, store.AgentRecallParams{ProjectID: acProj, Query: "secret token", TopK: 5})
	for _, r := range res {
		if r.ID == id {
			t.Errorf("archived row must not be recalled")
		}
	}
}
```

- [ ] **Step 6: Run integration recall tests (requires DB)**

Run: `cd ennam.kg.go && KG_TEST_DSN="$KG_TEST_DSN" go test -tags=integration ./internal/store/ -run TestRecallAgentContext -v`
Expected: with a DB, PASS. Without a DB: confirm `go build ./...` + `go vet ./internal/store/`; defer to CI.

- [ ] **Step 7: Commit**

```bash
git -C ennam.kg.go add internal/store/agent_context.go internal/store/agent_context_test.go internal/store/agent_context_fusion_test.go
git -C ennam.kg.go commit -m "feat(agent_context): hybrid recall with deterministic RRF fusion"
```

---

## Task 4: Queue — `AgentContextPublisher` + message

**Files:**
- Create: `ennam.kg.go/internal/queue/agent_context_messages.go`
- Test: `ennam.kg.go/internal/queue/agent_context_messages_test.go`

**Interfaces:**
- Consumes: existing `newRedisPublisher`, `redisPublisher.lpush`, `config.RedisQueueConfig` (queue package internals — mirror `extraction_messages.go`).
- Produces:
  - `const AgentContextQueueName = "ennam:agent_context_embed"`, `const MessageTypeEmbedAgentContext = "embed_agent_context"`
  - `type AgentContextEmbedMessage struct { Type, ProjectID, AgentContextID, Content string; CreatedAt time.Time }`
  - `type AgentContextPublisher interface { PublishEmbedAgentContext(ctx, AgentContextEmbedMessage) error; Close() error }`
  - `func NewAgentContextPublisher(cfg config.RedisQueueConfig, logger *slog.Logger) (AgentContextPublisher, error)`

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/queue/agent_context_messages_test.go`:

```go
package queue_test

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/queue"
)

func TestAgentContextQueueName(t *testing.T) {
	if queue.AgentContextQueueName != "ennam:agent_context_embed" {
		t.Errorf("AgentContextQueueName: got %q", queue.AgentContextQueueName)
	}
}

func TestAgentContextEmbedMessageJSON(t *testing.T) {
	b, err := json.Marshal(queue.AgentContextEmbedMessage{
		Type:           queue.MessageTypeEmbedAgentContext,
		ProjectID:      "p1",
		AgentContextID: "ac1",
		Content:        "hello",
	})
	if err != nil {
		t.Fatal(err)
	}
	s := string(b)
	for _, want := range []string{`"type":"embed_agent_context"`, `"project_id":"p1"`, `"agent_context_id":"ac1"`, `"content":"hello"`} {
		if !strings.Contains(s, want) {
			t.Errorf("marshaled message missing %s: %s", want, s)
		}
	}
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/queue/ -run TestAgentContext -v`
Expected: FAIL to compile — `undefined: queue.AgentContextQueueName`.

- [ ] **Step 3: Implement the publisher (mirror extraction_messages.go)**

Create `ennam.kg.go/internal/queue/agent_context_messages.go`:

```go
package queue

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/ennam/ennam-kg/internal/config"
)

const (
	// AgentContextQueueName is the Redis list key for agent_context embed jobs.
	AgentContextQueueName = "ennam:agent_context_embed"

	// MessageTypeEmbedAgentContext triggers a 384-dim embed for one memory.
	MessageTypeEmbedAgentContext = "embed_agent_context"
)

// AgentContextEmbedMessage is the payload sent to the agent_context embed queue.
// The struct IS the envelope (mirrors ingestion.go / extraction_messages.go).
type AgentContextEmbedMessage struct {
	Type           string    `json:"type"`
	ProjectID      string    `json:"project_id"`
	AgentContextID string    `json:"agent_context_id"`
	Content        string    `json:"content"`
	CreatedAt      time.Time `json:"created_at,omitempty"`
}

// AgentContextPublisher publishes agent_context embed messages.
type AgentContextPublisher interface {
	PublishEmbedAgentContext(ctx context.Context, msg AgentContextEmbedMessage) error
	Close() error
}

type redisAgentContextPublisher struct {
	redis *redisPublisher
}

// NewAgentContextPublisher creates a Redis-backed agent_context embed publisher.
func NewAgentContextPublisher(cfg config.RedisQueueConfig, logger *slog.Logger) (AgentContextPublisher, error) {
	cfg.QueueName = AgentContextQueueName
	redisPub, err := newRedisPublisher(cfg, logger)
	if err != nil {
		return nil, err
	}
	return &redisAgentContextPublisher{redis: redisPub}, nil
}

func (p *redisAgentContextPublisher) PublishEmbedAgentContext(ctx context.Context, msg AgentContextEmbedMessage) error {
	if msg.Type == "" {
		msg.Type = MessageTypeEmbedAgentContext
	}
	if msg.CreatedAt.IsZero() {
		msg.CreatedAt = time.Now().UTC()
	}
	payload, err := json.Marshal(msg)
	if err != nil {
		return fmt.Errorf("marshal agent_context embed message: %w", err)
	}
	if err := p.redis.lpush(ctx, string(payload)); err != nil {
		return err
	}
	p.redis.logger.Debug("published agent_context embed message",
		"type", msg.Type,
		"project_id", msg.ProjectID,
		"agent_context_id", msg.AgentContextID,
		"queue", p.redis.queueName,
	)
	return nil
}

func (p *redisAgentContextPublisher) Close() error {
	return p.redis.Close()
}
```

Note: verify `config.RedisQueueConfig` has a `QueueName` field and `newRedisPublisher(cfg, logger)` exists with this signature — they are used identically in `extraction_messages.go:50-51`. If `redisPublisher` exposes `logger`/`queueName` as unexported fields (it does — `redis.go:21-24`), this compiles because the file is in package `queue`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ennam.kg.go && go build ./... && go test ./internal/queue/ -run TestAgentContext -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/queue/agent_context_messages.go internal/queue/agent_context_messages_test.go
git -C ennam.kg.go commit -m "feat(agent_context): dedicated embed queue publisher"
```

---

## Task 5: Handler skeleton + batch-embeddings endpoint + server wiring

**Files:**
- Create: `ennam.kg.go/internal/handler/agent_context.go`
- Create: `ennam.kg.go/internal/handler/agent_context_test.go`
- Modify: `ennam.kg.go/cmd/kg-server/main.go`

**Interfaces:**
- Consumes: `store.AgentContextEmbeddingUpsert`/`UpsertAgentContextEmbedding` (Task 2), `store.AgentContextUpsert`/`UpsertAgentContext` + `AgentRecallParams`/`RecallAgentContext` (Tasks 2-3), `queue.AgentContextEmbedMessage`/`AgentContextPublisher` (Task 4), `QueryEmbedder` (handler package), `writeJSON`/`errorResponse`.
- Produces:
  - interfaces `agentContextStore`, `agentContextEmbedPublisher`
  - `func NewAgentContextHandler(s agentContextStore, embedder QueryEmbedder, pub agentContextEmbedPublisher, logger *slog.Logger) *AgentContextHandler`
  - `func (h *AgentContextHandler) RegisterRoutes(mux *http.ServeMux)` registering `POST /api/v1/agent-context/remember`, `POST /api/v1/agent-context/recall`, `POST /api/v1/projects/{id}/agent-context/embeddings/batch`
  - `func (h *AgentContextHandler) BatchUpsertEmbeddings(w, r)`

- [ ] **Step 1: Write the failing batch-endpoint test (DB-free, fake store)**

Create `ennam.kg.go/internal/handler/agent_context_test.go`:

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

	"github.com/ennam/ennam-kg/internal/store"
)

// fakeAgentStore implements agentContextStore for DB-free tests.
type fakeAgentStore struct {
	upserts     []store.AgentContextUpsert
	embUpserts  []store.AgentContextEmbeddingUpsert
	upsertID    string
	upsertNew   bool
	recallRows  []store.SearchResult
	recallErr   error
	upsertErr   error
}

func (f *fakeAgentStore) UpsertAgentContext(_ context.Context, m store.AgentContextUpsert) (string, bool, error) {
	if f.upsertErr != nil {
		return "", false, f.upsertErr
	}
	f.upserts = append(f.upserts, m)
	id := f.upsertID
	if id == "" {
		id = "mem-1"
	}
	return id, f.upsertNew, nil
}

func (f *fakeAgentStore) RecallAgentContext(_ context.Context, _ store.AgentRecallParams) ([]store.SearchResult, error) {
	return f.recallRows, f.recallErr
}

func (f *fakeAgentStore) UpsertAgentContextEmbedding(_ context.Context, e store.AgentContextEmbeddingUpsert) error {
	f.embUpserts = append(f.embUpserts, e)
	return nil
}

func newTestHandler(s agentContextStore) *AgentContextHandler {
	return NewAgentContextHandler(s, nil, nil, slog.Default())
}

func TestBatchUpsertEmbeddings_UpsertsItems(t *testing.T) {
	fs := &fakeAgentStore{}
	h := newTestHandler(fs)

	body, _ := json.Marshal(map[string]interface{}{
		"items": []map[string]interface{}{
			{"agent_context_id": "ac1", "content_hash": "h1", "embedding": []float32{0.1, 0.2}},
		},
	})
	req := httptest.NewRequest(http.MethodPost, "/api/v1/projects/proj-1/agent-context/embeddings/batch", bytes.NewReader(body))
	req.SetPathValue("id", "proj-1")
	w := httptest.NewRecorder()

	h.BatchUpsertEmbeddings(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
	if len(fs.embUpserts) != 1 || fs.embUpserts[0].AgentContextID != "ac1" || fs.embUpserts[0].ProjectID != "proj-1" {
		t.Errorf("embedding upsert not recorded correctly: %+v", fs.embUpserts)
	}
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestBatchUpsertEmbeddings -v`
Expected: FAIL to compile — `undefined: NewAgentContextHandler`.

- [ ] **Step 3: Implement the handler skeleton + batch endpoint**

Create `ennam.kg.go/internal/handler/agent_context.go`:

```go
package handler

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/ennam/ennam-kg/internal/queue"
	"github.com/ennam/ennam-kg/internal/store"
)

// agentContextStore is the store surface the handler depends on (interface for testability).
type agentContextStore interface {
	UpsertAgentContext(ctx context.Context, m store.AgentContextUpsert) (string, bool, error)
	RecallAgentContext(ctx context.Context, p store.AgentRecallParams) ([]store.SearchResult, error)
	UpsertAgentContextEmbedding(ctx context.Context, e store.AgentContextEmbeddingUpsert) error
}

// agentContextEmbedPublisher enqueues durable embed-on-write jobs.
type agentContextEmbedPublisher interface {
	PublishEmbedAgentContext(ctx context.Context, msg queue.AgentContextEmbedMessage) error
}

// AgentContextHandler serves kg_remember / kg_recall and the worker embed callback.
type AgentContextHandler struct {
	store     agentContextStore
	embedder  QueryEmbedder
	publisher agentContextEmbedPublisher
	logger    *slog.Logger
}

// NewAgentContextHandler creates an AgentContextHandler.
func NewAgentContextHandler(s agentContextStore, embedder QueryEmbedder, pub agentContextEmbedPublisher, logger *slog.Logger) *AgentContextHandler {
	return &AgentContextHandler{store: s, embedder: embedder, publisher: pub, logger: logger}
}

// RegisterRoutes registers the agent_context API routes.
func (h *AgentContextHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/agent-context/remember", h.Remember)
	mux.HandleFunc("POST /api/v1/agent-context/recall", h.Recall)
	mux.HandleFunc("POST /api/v1/projects/{id}/agent-context/embeddings/batch", h.BatchUpsertEmbeddings)
}

type agentContextEmbeddingBatchRequest struct {
	Items []struct {
		AgentContextID string    `json:"agent_context_id"`
		ContentHash    string    `json:"content_hash"`
		Embedding      []float32 `json:"embedding"`
	} `json:"items"`
}

// BatchUpsertEmbeddings stores memory embeddings posted by the Python worker.
func (h *AgentContextHandler) BatchUpsertEmbeddings(w http.ResponseWriter, r *http.Request) {
	projectID := r.PathValue("id")
	if projectID == "" {
		errorResponse(w, http.StatusBadRequest, "project id is required")
		return
	}
	var body agentContextEmbeddingBatchRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if len(body.Items) == 0 {
		errorResponse(w, http.StatusBadRequest, "items required")
		return
	}
	if len(body.Items) > 64 {
		errorResponse(w, http.StatusBadRequest, "max 64 items per batch")
		return
	}
	upserted := 0
	for _, item := range body.Items {
		if item.AgentContextID == "" || len(item.Embedding) == 0 {
			continue
		}
		if err := h.store.UpsertAgentContextEmbedding(r.Context(), store.AgentContextEmbeddingUpsert{
			ProjectID:      projectID,
			AgentContextID: item.AgentContextID,
			ContentHash:    item.ContentHash,
			Embedding:      item.Embedding,
		}); err != nil {
			h.logger.ErrorContext(r.Context(), "agent_context embedding upsert failed", "error", err, "agent_context_id", item.AgentContextID)
			continue
		}
		upserted++
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"upserted": upserted})
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ennam.kg.go && go build ./... && go test ./internal/handler/ -run TestBatchUpsertEmbeddings -v`
Expected: PASS.

- [ ] **Step 5: Wire the handler into the server**

In `ennam.kg.go/cmd/kg-server/main.go`, find the `buildRouter` block where `docHandler` is constructed (the `nodeEmbStore := store.NewNodeEmbeddingStore(db)` / `handler.NewDocumentHandler(...)` lines) and where `embedClient` is built (`embed.NewClient(embPythonURL, ...)`). Add immediately after the document handler wiring:

```go
	// Agent-context memory-of-record (kg_remember / kg_recall).
	acStore := store.NewAgentContextStore(db)
	acPublisher, err := queue.NewAgentContextPublisher(<QUEUE_REDIS_CFG>, logger)
	if err != nil {
		return nil, fmt.Errorf("agent_context publisher: %w", err)
	}
	acHandler := handler.NewAgentContextHandler(acStore, embedClient, acPublisher, logger)
	acHandler.RegisterRoutes(apiMux)
```

Resolve `<QUEUE_REDIS_CFG>` by mirroring the existing extraction publisher wiring:
Run: `grep -n "NewExtractionPublisher\|NewIngestionPublisher" ennam.kg.go/cmd/kg-server/main.go`
Use the SAME config argument (e.g. `serverCfg.Queue.Redis` or `appCfg.Queue.Redis`) and the same `Close()`-registration pattern those publishers use. If `buildRouter` does not return an `error`, construct the publisher where the other publishers are constructed (likely `run`/`main`) and pass it into the router builder, matching the extraction publisher's lifecycle.

- [ ] **Step 6: Verify the build and route registration**

Run: `cd ennam.kg.go && go build ./... && go vet ./cmd/... ./internal/handler/...`
Expected: clean build. (If a DB-backed smoke test is available, hit `POST /api/v1/projects/{id}/agent-context/embeddings/batch` and expect 200; otherwise defer to CI.)

- [ ] **Step 7: Commit**

```bash
git -C ennam.kg.go add internal/handler/agent_context.go internal/handler/agent_context_test.go cmd/kg-server/main.go
git -C ennam.kg.go commit -m "feat(agent_context): handler skeleton + embed batch endpoint + wiring"
```

---

## Task 6: `kg_remember` + `kg_recall` handlers

**Files:**
- Modify: `ennam.kg.go/internal/handler/agent_context.go`
- Modify: `ennam.kg.go/internal/handler/agent_context_test.go`

**Interfaces:**
- Consumes: `middleware.GetDeveloperIdentity`, `DeveloperIdentity.ResolveProjectID`/`DeveloperName` (Task data), `QueryEmbedder.EmbedQuery`, store + publisher from Task 5.
- Produces: `Remember(w, r)` and `Recall(w, r)` methods; recall response shape `{"results":[{id,kind,scope,content,snippet,tags,source_agent,created_at,updated_at,score}]}`.

- [ ] **Step 1: Write failing tests for remember + recall (DB-free)**

Add to `ennam.kg.go/internal/handler/agent_context_test.go` (add imports `"strings"`, `"time"`, and `"github.com/ennam/ennam-kg/internal/middleware"`, `"github.com/ennam/ennam-kg/internal/models"`):

```go
// fakeEmbedder implements QueryEmbedder.
type fakeEmbedder struct {
	vec []float32
	err error
}

func (f fakeEmbedder) EmbedQuery(_ context.Context, _ string) ([]float32, error) {
	return f.vec, f.err
}

// reqWithIdentity attaches an authenticated identity (project-scoped key).
func reqWithIdentity(r *http.Request, projectID string) *http.Request {
	def := projectID
	id := &middleware.DeveloperIdentity{
		DeveloperName:    "agentA",
		Role:             models.APIKeyRoleDeveloper,
		ProjectIDs:       []string{projectID},
		DefaultProjectID: &def,
	}
	ctx := context.WithValue(r.Context(), middleware.DeveloperIdentityKey, id)
	return r.WithContext(ctx)
}

func TestRemember_RejectsBadEnum(t *testing.T) {
	h := NewAgentContextHandler(&fakeAgentStore{}, nil, nil, slog.Default())
	body, _ := json.Marshal(map[string]interface{}{"kind": "bogus", "content": "x", "scope": "project"})
	req := reqWithIdentity(httptest.NewRequest(http.MethodPost, "/api/v1/agent-context/remember", bytes.NewReader(body)), "proj-1")
	w := httptest.NewRecorder()
	h.Remember(w, req)
	if w.Code != http.StatusBadRequest {
		t.Fatalf("want 400 for bad kind, got %d", w.Code)
	}
}

func TestRemember_ResolvesProjectFromKeyAndStores(t *testing.T) {
	fs := &fakeAgentStore{upsertID: "mem-9", upsertNew: true}
	h := NewAgentContextHandler(fs, nil, nil, slog.Default())
	body, _ := json.Marshal(map[string]interface{}{"kind": "fact", "content": "the sky is blue", "scope": "project"})
	req := reqWithIdentity(httptest.NewRequest(http.MethodPost, "/api/v1/agent-context/remember", bytes.NewReader(body)), "proj-1")
	w := httptest.NewRecorder()
	h.Remember(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d (%s)", w.Code, w.Body.String())
	}
	if len(fs.upserts) != 1 || fs.upserts[0].ProjectID != "proj-1" || fs.upserts[0].SourceAgent != "agentA" {
		t.Errorf("project/source_agent must come from the key: %+v", fs.upserts)
	}
}

func TestRecall_SoftFailsToEmptyOnStoreError(t *testing.T) {
	fs := &fakeAgentStore{recallErr: context.DeadlineExceeded}
	h := NewAgentContextHandler(fs, fakeEmbedder{vec: []float32{0.1}}, nil, slog.Default())
	body, _ := json.Marshal(map[string]interface{}{"query": "anything"})
	req := reqWithIdentity(httptest.NewRequest(http.MethodPost, "/api/v1/agent-context/recall", bytes.NewReader(body)), "proj-1")
	w := httptest.NewRecorder()
	h.Recall(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("recall must soft-fail with 200, got %d", w.Code)
	}
	if !strings.Contains(w.Body.String(), `"results":[]`) {
		t.Errorf("want empty results on store error, got %s", w.Body.String())
	}
}

func TestRecall_MapsPropertiesToView(t *testing.T) {
	props, _ := json.Marshal(map[string]interface{}{"content": "tabs over spaces", "tags": []string{"style"}, "source_agent": "agentA"})
	fs := &fakeAgentStore{recallRows: []store.SearchResult{{
		ID: "mem-1", NodeType: "preference", Scope: "project", Properties: props,
		Headline: "tabs <mark>over</mark> spaces", Rank: 0.5, UpdatedAt: time.Now(),
	}}}
	h := NewAgentContextHandler(fs, fakeEmbedder{vec: []float32{0.1}}, nil, slog.Default())
	body, _ := json.Marshal(map[string]interface{}{"query": "tabs"})
	req := reqWithIdentity(httptest.NewRequest(http.MethodPost, "/api/v1/agent-context/recall", bytes.NewReader(body)), "proj-1")
	w := httptest.NewRecorder()
	h.Recall(w, req)
	var resp struct {
		Results []struct {
			ID, Kind, Content, Snippet, SourceAgent string
			Tags                                    []string
		} `json:"results"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatal(err)
	}
	if len(resp.Results) != 1 || resp.Results[0].Kind != "preference" || resp.Results[0].Content != "tabs over spaces" {
		t.Errorf("view mapping wrong: %+v", resp.Results)
	}
}
```

Note: confirm the exact context key + role constants by grep: `grep -n "DeveloperIdentityKey\|APIKeyRoleDeveloper\|APIKeyRoleAdmin\|func.*Context.*Identity" ennam.kg.go/internal/middleware/auth.go ennam.kg.go/internal/models/*.go` and adjust to the real names. **If `DeveloperIdentityKey` is unexported** (so a `package handler` test cannot set it directly), either use the middleware's exported identity-injection helper if one exists, or write these as `package handler_test` and drive them through a test server behind `middleware.Auth` + a fake authenticator (the harness Task 8 reuses). Pick whichever the existing handler tests already use.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run "TestRemember|TestRecall" -v`
Expected: FAIL to compile — `h.Remember`/`h.Recall` undefined.

- [ ] **Step 3: Implement Remember + Recall**

Append to `ennam.kg.go/internal/handler/agent_context.go` (add imports `"strings"`, `"time"`, `"github.com/ennam/ennam-kg/internal/middleware"`):

```go
type rememberRequest struct {
	Kind    string   `json:"kind"`
	Content string   `json:"content"`
	Scope   string   `json:"scope"`
	MemKey  string   `json:"mem_key"`
	Tags    []string `json:"tags"`
}

type recallRequest struct {
	Query string   `json:"query"`
	Kind  string   `json:"kind"`
	Scope string   `json:"scope"`
	Tags  []string `json:"tags"`
	TopK  int      `json:"top_k"`
}

type recallView struct {
	ID          string    `json:"id"`
	Kind        string    `json:"kind"`
	Scope       string    `json:"scope"`
	Content     string    `json:"content"`
	Snippet     string    `json:"snippet,omitempty"`
	Tags        []string  `json:"tags"`
	SourceAgent string    `json:"source_agent"`
	CreatedAt   time.Time `json:"created_at"`
	UpdatedAt   time.Time `json:"updated_at"`
	Score       float64   `json:"score"`
}

var validKinds = map[string]bool{"preference": true, "decision": true, "fact": true, "correction": true}
var validScopes = map[string]bool{"project": true, "user": true, "agent": true}

// Remember persists a memory (kg_remember). project_id/user_id/source_agent are
// resolved from the API key, never from the request body. The embed is enqueued
// on the durable queue (embed-on-write).
func (h *AgentContextHandler) Remember(w http.ResponseWriter, r *http.Request) {
	projectID, sourceAgent, ok := h.resolveWriteIdentity(w, r)
	if !ok {
		return
	}
	var body rememberRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if strings.TrimSpace(body.Content) == "" {
		errorResponse(w, http.StatusBadRequest, "content is required")
		return
	}
	if !validKinds[body.Kind] {
		errorResponse(w, http.StatusBadRequest, "invalid kind (preference|decision|fact|correction)")
		return
	}
	if !validScopes[body.Scope] {
		errorResponse(w, http.StatusBadRequest, "invalid scope (project|user|agent)")
		return
	}
	id, created, err := h.store.UpsertAgentContext(r.Context(), store.AgentContextUpsert{
		ProjectID:   projectID,
		SourceAgent: sourceAgent,
		Kind:        body.Kind,
		Scope:       body.Scope,
		MemKey:      body.MemKey,
		Content:     body.Content,
		Tags:        body.Tags,
	})
	if err != nil {
		h.logger.ErrorContext(r.Context(), "agent_context upsert failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "failed to store memory")
		return
	}
	embedStatus := "queued"
	if h.publisher != nil {
		if perr := h.publisher.PublishEmbedAgentContext(r.Context(), queue.AgentContextEmbedMessage{
			ProjectID:      projectID,
			AgentContextID: id,
			Content:        body.Content,
		}); perr != nil {
			// Loud: a dropped enqueue means no semantic embedding until re-remembered
			// (FTS recall still works). Retention/reconcile is out of scope this slice.
			h.logger.ErrorContext(r.Context(), "agent_context embed enqueue failed", "error", perr, "agent_context_id", id)
			embedStatus = "enqueue_failed"
		}
	}
	status := "updated"
	if created {
		status = "created"
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"id": id, "status": status, "embedding": embedStatus})
}

// Recall returns memories for the key's project (kg_recall). Soft-fails to an
// empty result set on any embed/store error — never a 5xx.
func (h *AgentContextHandler) Recall(w http.ResponseWriter, r *http.Request) {
	identity := middleware.GetDeveloperIdentity(r.Context())
	projectID := ""
	userID := ""
	if identity != nil {
		pid, ok := identity.ResolveProjectID("")
		if !ok {
			writeJSON(w, http.StatusOK, map[string]interface{}{"results": []recallView{}})
			return
		}
		projectID = pid
	}
	var body recallRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		errorResponse(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if strings.TrimSpace(body.Query) == "" {
		errorResponse(w, http.StatusBadRequest, "query is required")
		return
	}
	if body.TopK <= 0 {
		body.TopK = 8
	}
	if body.TopK > 50 {
		body.TopK = 50
	}
	var qvec []float32
	if h.embedder != nil {
		if v, err := h.embedder.EmbedQuery(r.Context(), body.Query); err != nil {
			h.logger.WarnContext(r.Context(), "agent_context recall query embed failed; lexical-only", "error", err)
		} else {
			qvec = v
		}
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
	})
	if err != nil {
		h.logger.ErrorContext(r.Context(), "agent_context recall failed", "error", err)
		writeJSON(w, http.StatusOK, map[string]interface{}{"results": []recallView{}})
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"results": toRecallView(rows)})
}

// resolveWriteIdentity returns the key's project and agent name for a write.
// When unauthenticated (dev/no-op mode) it returns ("", "unknown", true) so local
// dev still works; production keys always carry a project.
func (h *AgentContextHandler) resolveWriteIdentity(w http.ResponseWriter, r *http.Request) (string, string, bool) {
	identity := middleware.GetDeveloperIdentity(r.Context())
	if identity == nil {
		return "", "unknown", true
	}
	pid, ok := identity.ResolveProjectID("")
	if !ok {
		errorResponse(w, http.StatusBadRequest, "no project context for this key")
		return "", "", false
	}
	return pid, identity.DeveloperName, true
}

func toRecallView(rs []store.SearchResult) []recallView {
	out := make([]recallView, 0, len(rs))
	for _, r := range rs {
		var props struct {
			Content     string   `json:"content"`
			Tags        []string `json:"tags"`
			SourceAgent string   `json:"source_agent"`
		}
		_ = json.Unmarshal(r.Properties, &props)
		if props.Tags == nil {
			props.Tags = []string{}
		}
		out = append(out, recallView{
			ID:          r.ID,
			Kind:        r.NodeType,
			Scope:       r.Scope,
			Content:     props.Content,
			Snippet:     r.Headline,
			Tags:        props.Tags,
			SourceAgent: props.SourceAgent,
			CreatedAt:   r.CreatedAt,
			UpdatedAt:   r.UpdatedAt,
			Score:       r.Rank,
		})
	}
	return out
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ennam.kg.go && go build ./... && go test ./internal/handler/ -run "TestRemember|TestRecall|TestBatchUpsertEmbeddings" -v`
Expected: PASS (all handler tests).

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/handler/agent_context.go internal/handler/agent_context_test.go
git -C ennam.kg.go commit -m "feat(agent_context): kg_remember + kg_recall handlers"
```

---

## Task 7: Bridge — register `kg_remember` + `kg_recall` (MCP)

**Files:**
- Modify: `ennam.kg.go/internal/bridge/schema.go`
- Modify: `ennam.kg.go/internal/bridge/client.go`
- Modify: `ennam.kg.go/internal/bridge/schema_test.go`, `handler_test.go`, `client_test.go`, and the integration tool-enum test.

**Interfaces:**
- Produces: two new routed MCP tools. Invariant moves from **42 schemas / 39 routed / 3 local → 44 / 41 / 3**. `kg_remember` = `RouteWrite`, `kg_recall` = `RouteRead` (read-only is conveyed by `RouteRead`, which the readonly scope gate honors).

- [ ] **Step 1: Bump the invariant test counts first (RED)**

Make these exact edits (verify the current literal by `grep -n "!= 42\|!= 39\|Read=\|Write=\|want 39\|want 42" ennam.kg.go/internal/bridge/*_test.go` first, then change):
- `internal/bridge/schema_test.go`: `if len(schemas) != 42 {` → `!= 44`, and the message `42` → `44`.
- `internal/bridge/handler_test.go`: `if len(tools) != 42 {` → `!= 44`, message `42` → `44`.
- `internal/bridge/client_test.go`: `if len(names) != 39 {` → `!= 41`, message `39` → `41`.
- `internal/bridge/client_test.go` route-class block: total `39` → `41`; `kg_recall` is read so bump Read `17` → `18`; `kg_remember` is write so bump Write `22` → `23`. (Grep `grep -n "Read\|Write\|total" ennam.kg.go/internal/bridge/client_test.go` to find the exact assertion lines.)
- Integration tool-enum test (find it: `grep -rn "kg_search\"" ennam.kg.go/internal/bridge/*integration*_test.go ennam.kg.go/internal/bridge/*_test.go | grep -i enum`): add `"kg_remember"` and `"kg_recall"` to the expected name set.

- [ ] **Step 2: Run the bridge tests to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/bridge/ -v`
Expected: FAIL — counts now expect 44/41 but only 42/39 are registered.

- [ ] **Step 3: Add the route entries**

In `ennam.kg.go/internal/bridge/client.go`, inside the `toolRoutes` map, add (near the other read/write tools; `apiPrefix` is the existing path-prefix var):

```go
	// === Agent-context memory-of-record ===
	"kg_remember": {
		Method:       http.MethodPost,
		PathTemplate: apiPrefix + "/agent-context/remember",
		Class:        RouteWrite,
	},
	"kg_recall": {
		Method:       http.MethodPost,
		PathTemplate: apiPrefix + "/agent-context/recall",
		Class:        RouteRead,
	},
```

- [ ] **Step 4: Add the tool schemas**

In `ennam.kg.go/internal/bridge/schema.go`, inside `buildToolSchemas()`, add (confirm the integer param type constant first: `grep -n "TypeInteger\|TypeNumber\|Type: Type" ennam.kg.go/internal/bridge/schema.go` and use whatever existing integer params use):

```go
	// === kg_remember ===
	schemas["kg_remember"] = &ToolSchema{
		ToolName:    "kg_remember",
		Description: "Persist a durable memory (preference/decision/fact/correction) for the calling agent's project. Re-remembering with the same mem_key replaces the prior memory. project_id/user_id are resolved from the API key — do not pass them.",
		Properties: map[string]ParamSchema{
			"kind":    {Type: TypeString, Required: true, Description: "Memory kind", Enum: []string{"preference", "decision", "fact", "correction"}},
			"content": {Type: TypeString, Required: true, Description: "The memory text", MinLength: intPtr(1), MaxLength: intPtr(8000)},
			"scope":   {Type: TypeString, Required: true, Description: "What the memory is about", Enum: []string{"project", "user", "agent"}},
			"mem_key": {Type: TypeString, Required: false, Description: "Idempotency key; same key replaces the prior memory"},
			"tags":    {Type: TypeArray, Required: false, Description: "Optional tags", Items: &ParamSchema{Type: TypeString}},
		},
	}

	// === kg_recall ===
	schemas["kg_recall"] = &ToolSchema{
		ToolName:    "kg_recall",
		Description: "Recall memories for the calling agent's project via hybrid semantic + keyword search. Returns raw snippets, most relevant first. project_id/user_id are resolved from the API key.",
		Properties: map[string]ParamSchema{
			"query": {Type: TypeString, Required: true, Description: "What to recall", MinLength: intPtr(1), MaxLength: intPtr(500)},
			"kind":  {Type: TypeString, Required: false, Description: "Filter by kind", Enum: []string{"preference", "decision", "fact", "correction"}},
			"scope": {Type: TypeString, Required: false, Description: "Filter by scope", Enum: []string{"project", "user", "agent"}},
			"tags":  {Type: TypeArray, Required: false, Description: "Filter by tags (any match)", Items: &ParamSchema{Type: TypeString}},
			"top_k": {Type: TypeInteger, Required: false, Description: "Max results (default 8, max 50)"},
		},
	}
```

Also update the `buildToolSchemas` doc-comment count and the `make(map[string]*ToolSchema, 42)` capacity hint to `44` (cosmetic, keeps the comment honest).

- [ ] **Step 5: Run the bridge tests to verify they pass**

Run: `cd ennam.kg.go && go build ./... && go test ./internal/bridge/ -v`
Expected: PASS — schemas=44, routed=41, local=3; route-class Read=18, Write=23.

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.go add internal/bridge/
git -C ennam.kg.go commit -m "feat(agent_context): register kg_remember + kg_recall MCP tools"
```

---

## Task 8: Cross-project isolation gating test

**Files:**
- Create: `ennam.kg.go/internal/handler/agent_context_isolation_integration_test.go`

**Interfaces:**
- Consumes: the full Auth → ProjectID → handler chain (mirror `recall_isolation_integration_test.go`), `AgentContextHandler`, `AgentContextStore`.

- [ ] **Step 1: Write the isolation test (RED before, GREEN after — it should already pass given key-resolved scoping)**

Create `ennam.kg.go/internal/handler/agent_context_isolation_integration_test.go`. Mirror the harness in `recall_isolation_integration_test.go` (same `//go:build integration`, `fakeAuthenticator`, server builder, `doReq` helper — reuse those helpers if they are package-visible in the same `handler_test` package; otherwise copy the minimal harness). Seed two projects + a memory in each, and a key scoped to P_A only:

```go
//go:build integration

package handler_test

import (
	"context"
	"database/sql"
	"net/http"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/store"
)

const (
	acIsoPA       = "dddddddd-0000-0000-0000-000000000001"
	acIsoPB       = "eeeeeeee-0000-0000-0000-000000000002"
	acIsoSentinel = "ZZ_agentctx_sentinel"
)

func seedAgentContextIsolation(t *testing.T, db *sql.DB) {
	t.Helper()
	ctx := context.Background()
	cleanup := func() {
		db.ExecContext(ctx, `DELETE FROM agent_context WHERE project_id IN ($1,$2)`, acIsoPA, acIsoPB)
		db.ExecContext(ctx, `DELETE FROM projects WHERE id IN ($1,$2)`, acIsoPA, acIsoPB)
	}
	cleanup()
	t.Cleanup(cleanup)
	for _, p := range []string{acIsoPA, acIsoPB} {
		if _, err := db.ExecContext(ctx, `INSERT INTO projects (id, name) VALUES ($1, $2)`, p, "ac-iso-"+p[:4]); err != nil {
			t.Fatalf("seed project: %v", err)
		}
	}
	s := store.NewAgentContextStore(db)
	if _, _, err := s.UpsertAgentContext(ctx, store.AgentContextUpsert{
		ProjectID: acIsoPB, SourceAgent: "seed", Kind: "fact", Scope: "project",
		Content: acIsoSentinel + " project B secret",
	}); err != nil {
		t.Fatalf("seed P_B memory: %v", err)
	}
}

func TestAgentContextRecall_Isolation(t *testing.T) {
	db := integrationDB(t)          // reuse helper from recall_isolation_integration_test.go
	seedAgentContextIsolation(t, db)
	srv := agentContextIsolationServer(t, db) // build a server whose key "key-a" is scoped to acIsoPA only

	// A P_A key recalls "secret" — must NOT see P_B's memory (project resolved from key).
	code, body := doReq(t, srv, http.MethodPost, "/api/v1/agent-context/recall", "key-a",
		`{"query":"`+acIsoSentinel+` secret"}`)
	if code != http.StatusOK {
		t.Fatalf("recall want 200, got %d", code)
	}
	if strings.Contains(body, acIsoSentinel) {
		t.Errorf("LEAK: P_A key recalled P_B memory: %s", body)
	}
}
```

Implement `agentContextIsolationServer` by mirroring the existing `isolationServer` builder but registering `AgentContextHandler` (with `NewAgentContextStore(db)`, a nil embedder so recall is lexical-only and deterministic, and a nil publisher) behind the same Auth + ProjectID middleware chain and the same `fakeAuthenticator` seeding `key-a → {ProjectIDs:[acIsoPA]}`.

- [ ] **Step 2: Run the isolation test (requires DB)**

Run: `cd ennam.kg.go && KG_TEST_DSN="$KG_TEST_DSN" go test -tags=integration ./internal/handler/ -run TestAgentContextRecall_Isolation -v`
Expected: with a DB, PASS (no leak). Without a DB: confirm it compiles under `-tags=integration` (`go vet -tags=integration ./internal/handler/`); defer the run to CI.

- [ ] **Step 3: Commit**

```bash
git -C ennam.kg.go add internal/handler/agent_context_isolation_integration_test.go
git -C ennam.kg.go commit -m "test(agent_context): cross-project recall isolation gate"
```

---

## Task 9: Python worker — `embed_agent_context` consumer

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/config.py`
- Modify: `ennam.kg.python/src/ennam_kg/worker.py`
- Modify: `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py`
- Create: `ennam.kg.python/tests/test_embed_agent_context_handler.py`

**Interfaces:**
- Consumes: the Go batch endpoint `POST /api/v1/projects/{id}/agent-context/embeddings/batch` (Task 5), the `embed_agent_context` message (Task 4), `LocalEmbeddingModel.encode_passage`.
- Produces: a 4th consumer on `settings.agent_context_queue_name`, an `embed_agent_context` branch in `handle_message`, and `KGClient.upsert_agent_context_embeddings`.

- [ ] **Step 1: Write the failing worker handler test**

Create `ennam.kg.python/tests/test_embed_agent_context_handler.py` (mirror `tests/test_ba031a_resolve_document_handler.py` patterns + `pytest-httpx`):

```python
import pytest
from unittest.mock import patch


def _make_settings():
    from ennam_kg.config import Settings
    return Settings(
        go_api_url="http://localhost:8080",
        go_api_key="test-key",
        redis_url="redis://localhost:6379/0",
    )


@pytest.mark.asyncio
async def test_embed_agent_context_posts_vectors(httpx_mock):
    settings = _make_settings()
    test_msg = {
        "type": "embed_agent_context",
        "project_id": "proj-1",
        "agent_context_id": "ac-1",
        "content": "prefers durable queues",
    }
    httpx_mock.add_response(
        method="POST",
        url="http://localhost:8080/api/v1/projects/proj-1/agent-context/embeddings/batch",
        json={"upserted": 1},
    )

    class _FakeConsumer:
        def __init__(self, _redis_url, queue_name):
            self._queue_name = queue_name

        async def consume_forever(self, handler):
            if self._queue_name == "ennam:agent_context_embed":
                await handler(test_msg)

        def stop(self):
            pass

    class _FakeModel:
        def __init__(self, *a, **k):
            pass

        def encode_passage(self, texts):
            return [[0.01] * 384 for _ in texts]

    with (
        patch("ennam_kg.worker.RedisQueueConsumer", lambda url, name: _FakeConsumer(url, name)),
        patch("ennam_kg.worker.LocalEmbeddingModel", _FakeModel),
        patch("ennam_kg.worker.IndexingEngine"),
        patch("ennam_kg.worker.KGGenerationEngine"),
        patch("ennam_kg.worker.NLQueryEngine"),
        patch("ennam_kg.worker.BenchmarkEngine"),
        patch("ennam_kg.worker.IngestionPipelineEngine"),
    ):
        from ennam_kg.worker import _run_worker
        await _run_worker(settings)

    req = httpx_mock.get_request()
    assert req is not None
    assert req.headers["Authorization"] == "Bearer test-key"
```

Note: the exact `patch(...)` target list must match the engines `worker.py` constructs at startup — grep `worker.py` for the classes instantiated in `_run_worker` and patch each so startup doesn't load real models/DBs. If `worker.py` imports `LocalEmbeddingModel` lazily, patch its real import path instead of `ennam_kg.worker.LocalEmbeddingModel`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_embed_agent_context_handler.py -v`
Expected: FAIL — `embed_agent_context` not handled (no POST captured) and/or `agent_context_queue_name` / `LocalEmbeddingModel` not wired in `worker.py`.

- [ ] **Step 3: Add the settings field**

In `ennam.kg.python/src/ennam_kg/config.py`, after `extraction_queue_name`:

```python
    # Agent-context memory embedding queue (kg_remember embed-on-write)
    agent_context_queue_name: str = "ennam:agent_context_embed"
```

- [ ] **Step 4: Add the KGClient method**

In `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py`, after `upsert_node_embeddings`:

```python
    async def upsert_agent_context_embeddings(
        self,
        project_id: str,
        items: list[dict[str, Any]],
    ) -> int:
        """POST /api/v1/projects/{id}/agent-context/embeddings/batch — returns upserted count."""
        result = await self._request(
            "POST",
            f"/api/v1/projects/{project_id}/agent-context/embeddings/batch",
            json={"items": items},
        )
        return int(result.get("upserted", 0))
```

- [ ] **Step 5: Wire the worker (model + 4th consumer + branch)**

In `ennam.kg.python/src/ennam_kg/worker.py`:

(a) Import + instantiate the model in `_run_worker` (after the other engines are built):
```python
from ennam_kg.embeddings.local_model import LocalEmbeddingModel
# ...
embedding_model = LocalEmbeddingModel(model_name=settings.embedding_model_name)
```

(b) Add the 4th consumer after `extraction_consumer` (worker.py ~line 62-64):
```python
    embed_agent_context_consumer = RedisQueueConsumer(
        settings.redis_url,
        settings.agent_context_queue_name,
    )
```

(c) Register it in the signal handler (where `extraction_consumer.stop()` is called):
```python
    embed_agent_context_consumer.stop()
```

(d) Add it to the `asyncio.gather` block:
```python
        embed_agent_context_consumer.consume_forever(handle_message),
```

(e) Add the dispatch branch in `handle_message`, before the final `else:` (add `import hashlib` at module top):
```python
    elif msg_type == "embed_agent_context":
        agent_context_id = msg.get("agent_context_id", "")
        content = msg.get("content", "")
        if not project_id or not agent_context_id or not content:
            logger.warning("embed_agent_context missing required fields: %s", msg)
            return
        vectors = embedding_model.encode_passage([content])
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        await kg_client.upsert_agent_context_embeddings(
            project_id,
            [{
                "agent_context_id": agent_context_id,
                "content_hash": content_hash,
                "embedding": vectors[0],
            }],
        )
        logger.info("embed_agent_context done: project=%s id=%s", project_id, agent_context_id)
```

Note: `handle_message` must be able to see `embedding_model` and `kg_client` — confirm whether `handle_message` is a closure inside `_run_worker` (it can capture both) or a module-level function (then pass them in / use the existing mechanism the other branches use for `kg_client`). Match whatever pattern `kg_client` already uses in the `extract_document` branch.

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_embed_agent_context_handler.py -v`
Expected: PASS — the worker embeds and POSTs to the batch endpoint with the Bearer key.

- [ ] **Step 7: Lint + commit**

```bash
cd ennam.kg.python && uv run ruff check src/ tests/ && uv run pytest tests/test_embed_agent_context_handler.py -q
git -C ennam.kg.python add src/ennam_kg/config.py src/ennam_kg/worker.py packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py tests/test_embed_agent_context_handler.py
git -C ennam.kg.python commit -m "feat(agent_context): worker embed_agent_context consumer (384-dim passage)"
```

---

## End-to-end verification (after all tasks)

- [ ] With the full stack up (`docker compose up -d --build`), call `kg_remember` (via MCP or `POST /api/v1/agent-context/remember` with a project-scoped key), then `kg_recall` with a matching query. Expect the memory back, `score > 0`, and (after the worker drains the queue) a row in `agent_context_embeddings`.
- [ ] `cd ennam.kg.go && make test && make lint` green in CI (with DB + golangci-lint + cgo for `-race`).
- [ ] Confirm `kg_recall` appears under a read-only tool profile and `kg_remember` does not (readonly scope gate honors `RouteRead`/`RouteWrite`).
