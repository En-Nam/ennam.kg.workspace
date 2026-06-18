# Phase 6 Sprint 1: BA-022 Go Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.
>
> **Parent:** [`2026-05-28-phase6-master.md`](2026-05-28-phase6-master.md)
>
> **Working directory:** `ennam.kg.go/`

**Goal:** Ship draft node + source connection data model, CRUD/state-machine APIs, and Redis job publishing so Sprint 3 upload and Sprint 5 AI pipeline have a foundation.

**Architecture:** Handler → Service → Store. `DraftNodeService` owns valid state transitions (BA-022 BR-001.1). `IngestionQueueService` LPUSHes to `ennam:kg_generation`. Reuse existing `KGGenerationStore` pattern if present; otherwise add minimal `ingestion_jobs` metadata in job message only (defer job table if `kg_generation_jobs` already exists).

**Tech Stack:** Go stdlib, `database/sql`, Redis client (match existing queue publisher in codebase)

---

## File Structure

### New files

```text
db/migrations/000047_create_draft_nodes.up.sql
db/migrations/000047_create_draft_nodes.down.sql
db/migrations/000048_create_source_connections.up.sql
db/migrations/000048_create_source_connections.down.sql

internal/models/draft_node.go
internal/models/source_connection.go

internal/store/draft_node.go
internal/store/draft_node_test.go
internal/store/source_connection.go
internal/store/source_connection_test.go

internal/service/draft_node.go
internal/service/draft_node_test.go
internal/service/source_connection.go
internal/service/ingestion_queue.go

internal/handler/draft_node.go
internal/handler/draft_node_test.go
internal/handler/source_connection.go
internal/handler/source_connection_test.go
```

### Modified files

```text
cmd/kg-server/main.go              # wire stores, services, handlers, routes
internal/middleware/project.go     # ensure project membership on /draft-nodes, /connections
```

---

## Task 1: Migration 047 — draft_nodes

**Files:**
- Create: `db/migrations/000047_create_draft_nodes.up.sql`
- Create: `db/migrations/000047_create_draft_nodes.down.sql`

- [ ] **Step 1: Write up migration**

```sql
-- db/migrations/000047_create_draft_nodes.up.sql
CREATE TABLE draft_nodes (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id          UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_type         VARCHAR(50) NOT NULL
        CHECK (source_type IN ('jira', 'google_drive', 'local_upload', 'satellite_api', 'manual')),
    source_id           VARCHAR(500) NOT NULL,
    source_url          TEXT,
    title               TEXT NOT NULL,
    content_raw         TEXT NOT NULL DEFAULT '',
    content_format      VARCHAR(50) NOT NULL DEFAULT 'plain_text',
    metadata            JSONB NOT NULL DEFAULT '{}',
    status              VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'processing', 'processed', 'failed', 'rejected')),
    approved_by         VARCHAR(255),
    approved_at         TIMESTAMPTZ,
    processed_at        TIMESTAMPTZ,
    knowledge_node_id   UUID REFERENCES knowledge_nodes(id),
    batch_id            UUID,
    connection_id       UUID,  -- FK added after 048
    created_by          VARCHAR(255) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_draft_nodes_source UNIQUE (project_id, source_type, source_id)
);

CREATE INDEX idx_draft_nodes_project_status ON draft_nodes (project_id, status);
CREATE INDEX idx_draft_nodes_project_source ON draft_nodes (project_id, source_type);
CREATE INDEX idx_draft_nodes_batch_id ON draft_nodes (batch_id) WHERE batch_id IS NOT NULL;
CREATE INDEX idx_draft_nodes_created_at ON draft_nodes (created_at DESC);

CREATE OR REPLACE FUNCTION trg_draft_nodes_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_draft_nodes_updated_at
    BEFORE UPDATE ON draft_nodes
    FOR EACH ROW EXECUTE FUNCTION trg_draft_nodes_updated_at();
```

- [ ] **Step 2: Write down migration**

```sql
-- db/migrations/000047_create_draft_nodes.down.sql
DROP TABLE IF EXISTS draft_nodes;
```

- [ ] **Step 3: Apply migration locally**

Run: `cd ennam.kg.go && make migrate-up`
Expected: migration 047 applied without error

- [ ] **Step 4: Commit**

```bash
git add db/migrations/000047_create_draft_nodes.up.sql db/migrations/000047_create_draft_nodes.down.sql
git commit -m "feat(phase6): add draft_nodes migration 047"
```

---

## Task 2: Migration 048 — source_connections

**Files:**
- Create: `db/migrations/000048_create_source_connections.up.sql`
- Create: `db/migrations/000048_create_source_connections.down.sql`

- [ ] **Step 1: Write up migration** (include FK from draft_nodes.connection_id)

```sql
-- db/migrations/000048_create_source_connections.up.sql
CREATE TABLE source_connections (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id       UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_type      VARCHAR(50) NOT NULL
        CHECK (source_type IN ('jira', 'google_drive', 'local_upload', 'satellite_api')),
    display_name     VARCHAR(255) NOT NULL,
    config           JSONB NOT NULL DEFAULT '{}',
    oauth_token_id   UUID REFERENCES oauth_tokens(id),
    webhook_secret   VARCHAR(255),
    status           VARCHAR(20) NOT NULL DEFAULT 'disconnected'
        CHECK (status IN ('disconnected', 'connecting', 'connected', 'syncing', 'error')),
    error_message    TEXT,
    last_synced_at   TIMESTAMPTZ,
    created_by       UUID NOT NULL REFERENCES users(id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_source_connections_project_type UNIQUE (project_id, source_type)
);

CREATE INDEX idx_source_connections_project ON source_connections (project_id);
CREATE INDEX idx_source_connections_webhook ON source_connections (webhook_secret)
    WHERE webhook_secret IS NOT NULL;

ALTER TABLE draft_nodes
    ADD CONSTRAINT fk_draft_nodes_connection
    FOREIGN KEY (connection_id) REFERENCES source_connections(id);

CREATE TRIGGER trg_source_connections_updated_at
    BEFORE UPDATE ON source_connections
    FOR EACH ROW EXECUTE FUNCTION trg_draft_nodes_updated_at();
```

- [ ] **Step 2: Apply and commit** (same pattern as Task 1)

---

## Task 3: Models — draft_node.go

**Files:**
- Create: `internal/models/draft_node.go`

- [ ] **Step 1: Write model with constants**

```go
package models

import "time"

type DraftNodeStatus string

const (
    DraftStatusPending    DraftNodeStatus = "pending"
    DraftStatusApproved   DraftNodeStatus = "approved"
    DraftStatusProcessing DraftNodeStatus = "processing"
    DraftStatusProcessed  DraftNodeStatus = "processed"
    DraftStatusFailed     DraftNodeStatus = "failed"
    DraftStatusRejected   DraftNodeStatus = "rejected"
)

type DraftSourceType string

const (
    DraftSourceJira         DraftSourceType = "jira"
    DraftSourceGoogleDrive  DraftSourceType = "google_drive"
    DraftSourceLocalUpload  DraftSourceType = "local_upload"
    DraftSourceSatelliteAPI DraftSourceType = "satellite_api"
    DraftSourceManual       DraftSourceType = "manual"
)

type DraftNode struct {
    ID              string          `json:"id"`
    ProjectID       string          `json:"project_id"`
    SourceType      DraftSourceType `json:"source_type"`
    SourceID        string          `json:"source_id"`
    SourceURL       *string         `json:"source_url,omitempty"`
    Title           string          `json:"title"`
    ContentRaw      string          `json:"content_raw"`
    ContentFormat   string          `json:"content_format"`
    Metadata        []byte          `json:"metadata"` // JSONB
    Status          DraftNodeStatus `json:"status"`
    ApprovedBy      *string         `json:"approved_by,omitempty"`
    ApprovedAt      *time.Time      `json:"approved_at,omitempty"`
    ProcessedAt     *time.Time      `json:"processed_at,omitempty"`
    KnowledgeNodeID *string         `json:"knowledge_node_id,omitempty"`
    BatchID         *string         `json:"batch_id,omitempty"`
    ConnectionID    *string         `json:"connection_id,omitempty"`
    CreatedBy       string          `json:"created_by"`
    CreatedAt       time.Time       `json:"created_at"`
    UpdatedAt       time.Time       `json:"updated_at"`
}

// ValidDraftTransition returns true if from→to is allowed (BA-022 BR-001.1).
func ValidDraftTransition(from, to DraftNodeStatus) bool {
    switch from {
    case DraftStatusPending:
        return to == DraftStatusApproved || to == DraftStatusRejected
    case DraftStatusApproved:
        return to == DraftStatusProcessing || to == DraftStatusRejected
    case DraftStatusProcessing:
        return to == DraftStatusProcessed || to == DraftStatusFailed
    case DraftStatusFailed:
        return to == DraftStatusPending
    default:
        return false
    }
}
```

- [ ] **Step 2: Commit**

---

## Task 4: Store — DraftNodeStore with upsert

**Files:**
- Create: `internal/store/draft_node.go`
- Create: `internal/store/draft_node_test.go`

- [ ] **Step 1: Write failing test for Upsert idempotency**

```go
func TestDraftNodeStore_Upsert_Idempotent(t *testing.T) {
    // setup test DB with project fixture
    store := NewDraftNodeStore(testDB)
    d := &models.DraftNode{
        ProjectID:  testProjectID,
        SourceType: models.DraftSourceManual,
        SourceID:   "doc-1",
        Title:      "First",
        ContentRaw: "v1",
        CreatedBy:  "test",
    }
    if err := store.Upsert(ctx, d); err != nil {
        t.Fatal(err)
    }
    id1 := d.ID

    d2 := &models.DraftNode{
        ProjectID:  testProjectID,
        SourceType: models.DraftSourceManual,
        SourceID:   "doc-1",
        Title:      "Updated",
        ContentRaw: "v2",
        CreatedBy:  "test",
    }
    if err := store.Upsert(ctx, d2); err != nil {
        t.Fatal(err)
    }
    if d2.ID != id1 {
        t.Fatalf("expected same id, got %s vs %s", id1, d2.ID)
    }
    got, _ := store.GetByID(ctx, testProjectID, id1)
    if got.Title != "Updated" {
        t.Fatalf("title not updated: %s", got.Title)
    }
}
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestDraftNodeStore_Upsert -v`
Expected: FAIL — `NewDraftNodeStore` undefined

- [ ] **Step 3: Implement Upsert, GetByID, List with filters**

Use `INSERT ... ON CONFLICT (project_id, source_type, source_id) DO UPDATE SET title=..., content_raw=..., updated_at=NOW() WHERE draft_nodes.status IN ('pending','failed','rejected')` — do NOT reset status if approved/processing (BR-001.2).

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

---

## Task 5: Service — DraftNodeService state machine

**Files:**
- Create: `internal/service/draft_node.go`
- Create: `internal/service/draft_node_test.go`

- [ ] **Step 1: Write failing test Approve from pending**

```go
func TestDraftNodeService_Approve_FromPending(t *testing.T) {
    svc := NewDraftNodeService(mockStore)
    mockStore.draft = &models.DraftNode{ID: "d1", ProjectID: "p1", Status: models.DraftStatusPending}
    out, err := svc.Approve(ctx, "p1", "d1", "user-1")
    if err != nil {
        t.Fatal(err)
    }
    if out.Status != models.DraftStatusApproved {
        t.Fatalf("got %s", out.Status)
    }
    if out.ApprovedBy == nil || *out.ApprovedBy != "user-1" {
        t.Fatal("approved_by not set")
    }
}
```

- [ ] **Step 2: Write failing test invalid transition processing→approved returns error**

- [ ] **Step 3: Implement Approve, Reject, Retry, BulkApprove, BulkReject**

Return `ErrInvalidTransition` mapped to 400 in handler.

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Commit**

---

## Task 6: Handler — draft node REST (8 endpoints)

**Files:**
- Create: `internal/handler/draft_node.go`
- Create: `internal/handler/draft_node_test.go`

- [ ] **Step 1: Register routes** (match BA-022 §8)

```go
func (h *DraftNodeHandler) RegisterRoutes(mux *http.ServeMux) {
    mux.HandleFunc("GET /api/v1/projects/{projectId}/draft-nodes", h.List)
    mux.HandleFunc("GET /api/v1/projects/{projectId}/draft-nodes/{draftId}", h.Get)
    mux.HandleFunc("POST /api/v1/projects/{projectId}/draft-nodes/{draftId}/approve", h.Approve)
    mux.HandleFunc("POST /api/v1/projects/{projectId}/draft-nodes/{draftId}/reject", h.Reject)
    mux.HandleFunc("POST /api/v1/projects/{projectId}/draft-nodes/bulk-approve", h.BulkApprove)
    mux.HandleFunc("POST /api/v1/projects/{projectId}/draft-nodes/bulk-reject", h.BulkReject)
    mux.HandleFunc("POST /api/v1/projects/{projectId}/draft-nodes/{draftId}/retry", h.Retry)
    mux.HandleFunc("POST /api/v1/projects/{projectId}/draft-nodes/process", h.ProcessBatch)
}
```

- [ ] **Step 2: Integration test List + Approve**

Use httptest + test DB seed one pending draft.

- [ ] **Step 3: Wire in main.go**

- [ ] **Step 4: Manual smoke**

```bash
curl -s -H "Authorization: Bearer $API_KEY" \
  "http://localhost:8080/api/v1/projects/$PROJECT_ID/draft-nodes" | jq .
```

- [ ] **Step 5: Commit**

---

## Task 7: Source connections CRUD (7 endpoints)

**Files:**
- Create: `internal/models/source_connection.go`
- Create: `internal/store/source_connection.go`
- Create: `internal/service/source_connection.go`
- Create: `internal/handler/source_connection.go`

- [ ] **Step 1: Store CRUD + GetByWebhookSecret**

- [ ] **Step 2: Handler RegisterRoutes** per BA-022 §8 Source Connection table

- [ ] **Step 3: On Create — generate `webhook_secret` with crypto/rand, 32 bytes hex**

- [ ] **Step 4: Stats endpoint** — `SELECT status, COUNT(*) FROM draft_nodes WHERE connection_id=$1 GROUP BY status`

- [ ] **Step 5: Integration test + commit**

---

## Task 8: ProcessBatch + Redis queue publish

**Files:**
- Create: `internal/service/ingestion_queue.go`
- Modify: `internal/service/draft_node.go` — ProcessBatch method

- [ ] **Step 1: Write failing test ProcessBatch rejects non-approved**

- [ ] **Step 2: Implement ProcessBatch**

Rules:
- Only `approved` drafts (BR-005.1)
- Max 50 (read from settings or hardcode 50 until 053)
- Single TX: set batch_id, status=processing
- One active job per project → 409 (check Redis key or DB flag)
- LPUSH `ennam:kg_generation` JSON message

- [ ] **Step 3: Verify Redis message**

Run process endpoint, then `redis-cli LRANGE ennam:kg_generation 0 0`

- [ ] **Step 4: Commit**

---

## Sprint 1 Done Checklist

- [ ] Migrations 047–048 applied
- [ ] 15 REST endpoints respond (8 draft + 7 connection)
- [ ] State machine rejects invalid transitions with 400
- [ ] Upsert idempotent on (project_id, source_type, source_id)
- [ ] ProcessBatch publishes to Redis
- [ ] `go test ./... -count=1` passes (existing failures documented separately)
- [ ] Update `.serena/memories/services/go-api.md` with Phase 6 Sprint 1 state

**Next:** Sprint 2 — webhooks + NextJS Knowledge Sources tab
