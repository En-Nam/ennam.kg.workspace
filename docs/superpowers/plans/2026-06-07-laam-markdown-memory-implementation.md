# LAAM Markdown Memory — Ingestion + Semantic Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan spans **two services (Go + Python)** — most work is Go.

**Goal:** Let LAAM (an MCP satellite) persist "things to remember" as markdown via `kg_ingest_node`, have them auto-decomposed + embedded, and **recall them semantically through an MCP-reachable path** (`kg_search` with `semantic=true`). Plus thread `source_url` provenance through the ingest path.

**Architecture (decisions made — see "Findings" for why):**
- **Recall = spec option (b):** expose `semantic` on the `kg_search` MCP tool; the Go `/search` handler, when `semantic=true` and no pre-computed vector is supplied, embeds the query text by calling the **existing** Python `POST /api/v1/embeddings` (384-dim, the *same* `LocalEmbeddingModel` ingestion uses → model parity by construction), then runs the **existing** `NodeEmbeddingStore.SemanticSearch`. No new Python code for recall; no embedding model re-implemented in Go.
- **Processing trigger = spec option (a):** enable the **existing** `ingestion.auto_queue_processing` setting so a single `kg_ingest_node(auto_approve=true)` upserts → auto-approves → `ProcessBatch` (enqueues the Python worker → decompose + 384-dim embed). Zero new code — a system-settings toggle.
- **`source_url` provenance:** thread it through the ingest request → draft. The DB column + store SQL already persist it; only the request structs + MCP schema are missing.
- **Hub node_type:** keep `external` (what `resolve_node_type("satellite_api", …)` returns). A one-line change to `document` is noted as optional (cosmetic for recall).

**Tech Stack:** Go (stdlib `net/http`, `database/sql`), Python 3.12 (FastAPI — reused, not modified for recall), PostgreSQL 16 + pgvector, Redis, `make`/`go test`/`uv`.

**Spec:** `docs/superpowers/specs/2026-06-07-laam-markdown-memory-ingestion-design.md` (Approved). All file:line references below were verified against the codebase on 2026-06-07.

---

## Findings that refine the spec (read first)

Codebase exploration on 2026-06-07 found the gap is **narrower and more Go-centric** than the spec's "the recall half is the real work" framing. These are confirmed, load-bearing facts:

1. **Recall orchestration already exists in Python** — `src/ennam_kg/agentic/tools.py::_exec_search_kg_semantic` (line 693) already embeds a query at 384-dim via `embed_texts_remote(..., base_url=settings.embedding_service_url)` and calls `KGClient.search_semantic` over `["document_section","document","concept"]`. It is **not MCP-reachable for LAAM** (it sits behind the agentic streaming endpoint). So recall is a **wiring** task, not green-field.

2. **The 384-dim query-embedding endpoint already exists** — Python `POST /api/v1/embeddings` (`src/ennam_kg/api/embeddings.py:28`) returns `{embeddings, model, dimensions}` using the same `LocalEmbeddingModel(settings.embedding_model_name)` (`embedding_dimensions=384`). The spec's claim "nothing produces the 384-dim query vector in a server-reachable place" is **outdated** — this endpoint does, and the Go server can call it (`KG_PYTHON_URL` already wired for the SSE service, `cmd/kg-server/main.go:645`).

3. **The Go `/search` REST endpoint already accepts `semantic` + `query_embedding`** — `internal/handler/search.go` `searchRequest` has both fields and the `SemanticSearch` branch (lines ~31-43, 168-190). The gap is only: (a) the `kg_search` **MCP bridge** schema doesn't expose `semantic` (`internal/bridge/schema.go:1102`), and (b) nothing embeds the query *text* server-side when no vector is supplied.

4. **`ingestion.auto_queue_processing` exists (Go-side)** — `internal/service/ingestion_settings.go:78` (default `false`), and `UpsertFromIngestion` already calls `ProcessBatch` when it's on (`internal/service/draft_node.go:172`). The earlier impression that this setting "doesn't exist" was Python-scoped; the enqueue orchestration is Go-side. So Q4(a) is a **setting toggle**, not a build.

5. **`source_url` is fully persisted at the store layer** — `internal/store/draft_node.go:17,30,89` (INSERT column, `EXCLUDED.source_url`, bound param) and `DraftNode.SourceURL` model field exist. Missing only: the ingest **request** structs + the **MCP schema** + the request→draft mapping.

6. **Node-type resolution is Python-side** — `src/ennam_kg/ingestion/pipeline/nodes.py:14` `resolve_node_type` returns `"external"` for `satellite_api`. Q-hub is a one-line Python change if `document` is wanted.

**Net:** the build is mostly Go wiring (MCP `semantic` param + a small Go→Python embed call + `source_url` plumbing) plus a settings toggle. No new Python recall code is required for option (b).

> **Alternative not taken (option a):** wrap the existing `_exec_search_kg_semantic` in a new Python `/api/v1/recall` endpoint + a new `kg_recall` Go bridge tool that proxies to it. Rejected because it adds a new Python endpoint, a new bridge tool, and a Go→Python→Go call loop, whereas (b) reuses the existing `kg_search` tool, `/embeddings`, and in-process `SemanticSearch` with a single Go→Python embed hop. If the team prefers keeping all recall logic in Python, switch to (a) — the recall behavior is identical.

### Verification reality (important)

Full end-to-end recall (ingest → decompose → 384-embed → semantic recall) needs a **running stack** (Postgres+pgvector, Redis, Go server, Python worker+API). This plan's automated tests are **Go unit tests** (httptest + a mocked embed client + a fake settings reader) and **bridge schema tests** — these cover every code change. The cross-service behavior is verified by the **manual E2E checklist** in Task 7 (run against `docker compose up`). Each task states which kind of verification applies.

> **De-risk result (2026-06-07 — applied the plan's Go changes, built, then reverted):**
> - ✅ `go build ./...` **passes** with all changes — production code (main.go wiring, routes.go signature, search.go, `internal/embed`, schema.go, ingest plumbing) integrates cleanly.
> - ✅ `go test ./internal/embed/` and `go test ./internal/bridge/` (incl. the 32-tool count + the two new schema tests) **pass**.
> - ⚠️ **The `internal/handler` *test* package does not compile on this branch — pre-existing, unrelated to this work.** Multiple committed test files are broken (e.g. `sync_portal_test.go` calls `NewSyncPortalHandler` with 4 args vs 6; `session_gate2_test.go` has `testConfig` redeclared; `internal/service` has `testDecisionConfig` redeclared + `mockAPIKeyRepo` missing `Delete`). This is almost certainly WIP from the other mono-repo branches. **Consequence:** `go test ./internal/handler/` and `make test` (Task 6) will fail for reasons that have nothing to do with this feature. Before relying on those gates, either (a) get the branch's handler/service test packages compiling again, or (b) run **targeted** tests: `go test ./internal/embed/ ./internal/bridge/` and, for the handler, `go test ./internal/handler/ -run "TestEnsureQueryEmbedding|TestSearchHandler"` only after the pre-existing breakage is resolved. Flag this to whoever owns the branch.

---

## File Structure

| File | Change | Action |
|------|--------|--------|
| system_settings (DB) or `config/config.yaml` | set `ingestion.auto_queue_processing=true` | **Config** |
| `ennam.kg.go/internal/handler/ingest_public.go` | `source_url` in request struct + pass-through | **Modify** |
| `ennam.kg.go/internal/service/ingest_public.go` | `SourceURL` in `PublicIngestItem` + map to draft | **Modify** |
| `ennam.kg.go/internal/bridge/schema.go` | `source_url` on `kg_ingest_node`; `semantic` on `kg_search` | **Modify** |
| `ennam.kg.go/internal/embed/client.go` | new: Go client for Python `/api/v1/embeddings` | **Create** |
| `ennam.kg.go/internal/handler/search.go` | embed query text when `semantic && no vector` (+ `QueryEmbedder` field on `SearchHandler`) | **Modify** |
| `ennam.kg.go/internal/handler/routes.go` | thread embedder through `NewQueryHandlers` → `NewSearchHandler` (line 30/38) | **Modify** |
| `ennam.kg.go/internal/handler/search_test.go` | add `nil` embedder arg to the **8** `NewSearchHandler(` calls + new `ensureQueryEmbedding` tests | **Modify** |
| `ennam.kg.go/internal/handler/routes_test.go` | add `nil` embedder arg to the **4** `NewSearchHandler(` calls (de-risk finding) | **Modify** |
| `ennam.kg.go/internal/bridge/schema_laam_test.go` | new: bridge schema tests (`source_url`, `semantic`) | **Create** |
| `ennam.kg.go/cmd/kg-server/main.go` | build embed client; pass to `NewQueryHandlers` (line 339) | **Modify** |
| `ennam.kg.go/internal/.../**_test.go` | Go tests per task | **Create/Modify** |

> Paths are relative to the workspace root. Go commands run from `ennam.kg.go/` (referred to as `$GO`); the Python service is only *called*, not modified (for option b). Confirm exact struct/field names against the cited file:line before each edit — match existing style.

### Reference points (read before starting)

- `internal/handler/search.go` — `searchRequest` (has `Semantic`, `QueryEmbedding`), `HandleSearch`, the semantic branch (`if req.Semantic && len(req.QueryEmbedding) > 0 && h.nodeEmb != nil`).
- `internal/store/node_embedding.go:49` — `SemanticSearch(ctx, projectID, queryEmbedding []float32, topK int, nodeTypes []string)`.
- `internal/bridge/schema.go:1102` (`kg_search`), `:1326` (`kg_ingest_node`); `internal/bridge/client.go` routing + `PathParams` (non-path params are marshaled into the JSON body).
- `internal/handler/ingest_public.go:20` (`publicIngestRequest`), `internal/service/ingest_public.go:22` (`PublicIngestItem`), `internal/service/draft_node.go:139` (`UpsertFromIngestion`), `internal/store/draft_node.go:16` (Upsert SQL — already has `source_url`).
- Python `src/ennam_kg/api/embeddings.py:28` — `POST /api/v1/embeddings`, request `{texts:[str], model?}`, response `{embeddings:[[float]], model, dimensions}`.

---

## Task 1: Enable + verify the one-call processing trigger (Q4a)

Enable `ingestion.auto_queue_processing` so a single `kg_ingest_node(auto_approve=true)` yields a recallable memory, and lock the behavior with a service test. No production-code change — the enqueue path already exists in `UpsertFromIngestion` (`draft_node.go:172`).

**Files:**
- Config: system_settings (DB) — key `ingestion.auto_queue_processing`
- Test: `ennam.kg.go/internal/service/draft_node_test.go` (or the existing ingestion-settings test file)

- [ ] **Step 1: Write a failing test that auto-approved ingest enqueues processing when the setting is on**

Add to `internal/service/draft_node_test.go`. **All facts below verified 2026-06-07:** `NewDraftNodeService(store draftNodeStore, ingestionPub ingestionPublisher, settingsReader settingsReader, logger)`; `settingsReader` = `Get(ctx, key) (json.RawMessage, error)`; `ingestionPublisher` = `PublishKGGeneration(ctx, queue.IngestionMessage) error`; `ProcessBatch` **errors if `ingestionPub == nil`** (so pass a real spy, not `nil`); the option field is **`RequestAutoApprove`** (not `AutoApprove`); the existing `mockDraftNodeStore.UpdateStatus` already transitions `draft.Status`, so the auto-approve→reload→ProcessBatch chain works. Tests use plain `testing` style (no testify — match the file). Two small new fakes are needed (none reusable: the oauth `mockSettingsRepo` returns `*models.SystemSetting`, which does **not** satisfy `settingsReader`):

```go
// New fakes (add to draft_node_test.go). Needs imports: "encoding/json", "github.com/ennam/ennam-kg/internal/queue".
type fakeSettingsReader map[string]json.RawMessage

func (f fakeSettingsReader) Get(_ context.Context, key string) (json.RawMessage, error) {
	return f[key], nil // absent key → nil → readBoolSetting falls back to false
}

type mockIngestionPublisher struct{ published bool }

func (m *mockIngestionPublisher) PublishKGGeneration(_ context.Context, _ queue.IngestionMessage) error {
	m.published = true
	return nil
}

func newSatelliteDraft(sourceID string) *models.DraftNode {
	return &models.DraftNode{
		ProjectID: "p1", SourceType: models.DraftSourceTypeSatelliteAPI, SourceID: sourceID,
		Title: "Mem", ContentRaw: "# A\n\nbody\n", ContentFormat: "markdown",
		Status: models.DraftNodeStatusPending,
	}
}

func TestUpsertFromIngestion_AutoQueueWhenSettingOn(t *testing.T) {
	store := &mockDraftNodeStore{draft: &models.DraftNode{Status: models.DraftNodeStatusPending}}
	pub := &mockIngestionPublisher{}
	settings := fakeSettingsReader{"ingestion.auto_queue_processing": json.RawMessage("true")}
	svc := NewDraftNodeService(store, pub, settings, slog.Default())

	_, err := svc.UpsertFromIngestion(context.Background(), newSatelliteDraft("laam:memory:test-1"),
		IngestUpsertOptions{RequestAutoApprove: true})
	if err != nil {
		t.Fatalf("UpsertFromIngestion: %v", err)
	}
	if !pub.published {
		t.Error("auto_queue_processing=true must enqueue (PublishKGGeneration) after auto-approve")
	}
}

func TestUpsertFromIngestion_NoQueueWhenSettingOff(t *testing.T) {
	store := &mockDraftNodeStore{draft: &models.DraftNode{Status: models.DraftNodeStatusPending}}
	pub := &mockIngestionPublisher{}
	settings := fakeSettingsReader{} // auto_queue absent → false
	svc := NewDraftNodeService(store, pub, settings, slog.Default())

	_, err := svc.UpsertFromIngestion(context.Background(), newSatelliteDraft("laam:memory:test-2"),
		IngestUpsertOptions{RequestAutoApprove: true})
	if err != nil {
		t.Fatalf("UpsertFromIngestion: %v", err)
	}
	if pub.published {
		t.Error("setting off must NOT enqueue")
	}
}
```

> Verified (2026-06-07), no longer open concerns: (1) `shouldAutoApprove` ends with `passesAutoApproveFilters(draft, opts)`, which **only applies content/size filters when `opts.Connection != nil`**. The LAAM path (`kg_ingest_node` → `PublicIngestItem`, no `Connection`) and this test fixture both pass `Connection == nil`, so `passesAutoApproveFilters` returns `true` and the auto-approve→ProcessBatch branch runs — the one-call flow is sound. (2) `ProcessBatch` calls `LoadIngestionSettings` again for `MaxBatchSize`; the `fakeSettingsReader` returns nil for that key → it falls back to the default (fine).

- [ ] **Step 2: Run tests (behavior already wired) — note the package caveat**

Run: `cd $GO && go test ./internal/service/ -run TestUpsertFromIngestion_ -v`
Expected: PASS — `UpsertFromIngestion` (`draft_node.go:163-180`) already auto-approves then calls `ProcessBatch` guarded by `settings.AutoQueueProcessing`. ⚠️ **`internal/service` is one of the pre-existing-broken test packages on this branch** (`testDecisionConfig`/`TestNodeService_StoreDecision_*` redeclared in `node_test.go` vs `decision_test.go`; `mockAPIKeyRepo` missing `Delete`) — so `go test ./internal/service/` will **fail to compile** until that's resolved (see "Verification reality"). Get the package compiling first, then run this. If these two new tests fail (not compile-fail), it's the `passesAutoApproveFilters` caveat above — adjust the fixture, not the production code.

- [ ] **Step 3: Enable the setting in the running environment**

Set the system setting (runtime, no restart — `system_settings` overrides YAML, 60s cache per the Go CLAUDE.md):

```bash
# Via the DB (psql) — adjust to your settings-write path / admin API if one exists:
cd $GO && make db-shell
# then:  UPDATE system_settings SET value='true' WHERE key='ingestion.auto_queue_processing';
#        INSERT ... ON CONFLICT if the row doesn't exist.
```

Document in the PR that LAAM's memory project relies on this setting being `true`. (Alternatively set the default in `config/config.yaml` if a global default is acceptable — but a DB/system-settings toggle keeps it scoped and reversible.)

- [ ] **Step 4: Commit**

```bash
git add internal/service/draft_node_test.go
git commit -m "test(ingest): lock auto_queue_processing enqueue for one-call satellite memory"
```

---

## Task 2: `source_url` plumbing through the ingest path

Thread `source_url` from the MCP `kg_ingest_node` call into `draft_nodes.source_url`. The store SQL already writes the column (`draft_node.go:17,30,89`); wire the request → item → draft mapping + the MCP schema.

**Files:**
- Modify: `ennam.kg.go/internal/handler/ingest_public.go` (`publicIngestRequest`, the `IngestSingle` call)
- Modify: `ennam.kg.go/internal/service/ingest_public.go` (`PublicIngestItem`, the draft construction in `upsertItem`)
- Modify: `ennam.kg.go/internal/bridge/schema.go` (`kg_ingest_node` schema)
- Test: `ennam.kg.go/internal/bridge/schema_laam_test.go` (new)

- [ ] **Step 1: Write the failing test (bridge schema)**

> **De-risk finding (2026-06-07):** a handler-level test was originally planned (`fakeIngestService` spy), but `IngestPublicHandler.svc` is a **concrete** `*service.PublicIngestService` (not an interface) and **no `ingest_public_test.go` / mock harness exists** — so a fake-service test would not compile. The unit-testable assertion is the **bridge schema** (below); the request→`PublicIngestItem`→`draft.SourceURL` mapping is plain field pass-through (the production edits in Steps 3–4) and is verified end-to-end in **Task 7 Step 6** (`SELECT source_url FROM draft_nodes …`). The store layer already persists `source_url` (`store/draft_node.go:17,30,89`), so no store change/test is needed.

Bridge schema test — add a new file `internal/bridge/schema_laam_test.go` (avoids editing the existing `schema_test.go`; same `package bridge`, plain `testing` style — the bridge tests do **not** use testify):

```go
package bridge

import "testing"

func TestKgIngestNode_HasSourceURLParam(t *testing.T) {
	s, ok := ListToolSchemas()["kg_ingest_node"] // ListToolSchemas() is the public accessor (schema.go:202)
	if !ok {
		t.Fatal("kg_ingest_node schema missing")
	}
	if _, ok := s.Properties["source_url"]; !ok {
		t.Error("kg_ingest_node must expose source_url")
	}
}
```

> Verified: the bridge exposes schemas via `ListToolSchemas()` (`schema.go:202`); there is no `DefaultSchemas()`. Adding a *property* (not a tool) keeps the tool count at 32, so `schema_test.go`'s `len(schemas) == 32` assertion still passes.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $GO && go test ./internal/bridge/ -run TestKgIngestNode_HasSourceURLParam -v`
Expected: FAIL — `publicIngestRequest`/`PublicIngestItem` have no `SourceURL` field; the schema has no `source_url` property.

- [ ] **Step 3: Add `source_url` to the request struct + pass-through (handler)**

In `internal/handler/ingest_public.go`, add the field to `publicIngestRequest` (after `ContentFormat`):

```go
type publicIngestRequest struct {
	Title         string          `json:"title"`
	ContentRaw    string          `json:"content_raw"`
	SourceID      string          `json:"source_id"`
	ContentFormat string          `json:"content_format,omitempty"`
	SourceURL     string          `json:"source_url,omitempty"`
	Metadata      json.RawMessage `json:"metadata,omitempty"`
	AutoApprove   bool            `json:"auto_approve,omitempty"`
}
```

And pass it into the service item in the `Ingest` handler:

```go
	result, _, err := h.svc.IngestSingle(r.Context(), projectID, service.PublicIngestItem{
		Title:              req.Title,
		ContentRaw:         req.ContentRaw,
		SourceID:           req.SourceID,
		ContentFormat:      req.ContentFormat,
		SourceURL:          req.SourceURL,
		Metadata:           req.Metadata,
		RequestAutoApprove: req.AutoApprove,
	}, actor)
```

- [ ] **Step 4: Add `SourceURL` to `PublicIngestItem` + map onto the draft (service)**

In `internal/service/ingest_public.go`, add to `PublicIngestItem` (after `ContentFormat`):

```go
	SourceURL          string          `json:"source_url,omitempty"`
```

In the same file's `upsertItem` (where the `models.DraftNode` is built before `UpsertFromIngestion`/`drafts.UpsertFromIngestion`), set `SourceURL` (it is `*string` on the model — use a pointer, leave nil when empty):

```go
	var sourceURL *string
	if item.SourceURL != "" {
		sourceURL = &item.SourceURL
	}
	draft := &models.DraftNode{
		// ...existing fields...
		SourceURL: sourceURL,
	}
```

> Confirm the exact draft-construction site (the service builds the `DraftNode` then calls `drafts.UpsertFromIngestion`, or passes the item down to `DraftNodeService.UpsertFromIngestion` which builds it). Set `SourceURL` wherever the `DraftNode` is constructed from the item. The store `Upsert` already binds `draft.SourceURL` (`store/draft_node.go:89`), so no store change is needed.

- [ ] **Step 5: Add `source_url` to the `kg_ingest_node` MCP schema (bridge)**

In `internal/bridge/schema.go` (the `schemas["kg_ingest_node"]` block, ~line 1326), add a property (non-path params are marshaled into the JSON body by the bridge client, so no `client.go` change is needed):

```go
			"source_url": {
				Type:        TypeString,
				Required:    false,
				Description: "Provenance pointer back to the satellite's own copy (e.g. laam://memory/<id>)",
			},
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd $GO && go test ./internal/bridge/ -run TestKgIngestNode_HasSourceURLParam -v`
Expected: PASS. Then the broader packages: `go test ./internal/handler/ ./internal/service/ ./internal/bridge/ -count=1` → PASS (no regressions).

- [ ] **Step 7: Commit**

```bash
git add internal/handler/ingest_public.go internal/service/ingest_public.go internal/bridge/schema.go \
        internal/bridge/schema_laam_test.go
git commit -m "feat(ingest): thread source_url from kg_ingest_node into draft provenance"
```

---

## Task 3: Go client for the Python embedding service

A small, injectable Go client that POSTs query text to the existing Python `POST /api/v1/embeddings` and returns the 384-dim vector. This is the **only** new piece that gives Go a 384-dim query vector with model parity.

**Files:**
- Create: `ennam.kg.go/internal/embed/client.go`
- Create: `ennam.kg.go/internal/embed/client_test.go`

- [ ] **Step 1: Write the failing test (httptest fake of the Python endpoint)**

`internal/embed/client_test.go`:

```go
package embed

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestClient_EmbedQuery_ReturnsVector(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/embeddings" || r.Method != http.MethodPost {
			t.Fatalf("unexpected request: %s %s", r.Method, r.URL.Path)
		}
		var body struct {
			Texts []string `json:"texts"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		if len(body.Texts) != 1 || body.Texts[0] != "hello" {
			t.Fatalf("unexpected texts: %v", body.Texts)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"embeddings": [][]float32{{0.1, 0.2, 0.3}},
			"model":      "all-MiniLM-L6-v2",
			"dimensions": 3,
		})
	}))
	defer srv.Close()

	c := NewClient(srv.URL, "test-token", srv.Client())
	vec, err := c.EmbedQuery(context.Background(), "hello")
	if err != nil {
		t.Fatalf("EmbedQuery error: %v", err)
	}
	if len(vec) != 3 || vec[0] != 0.1 {
		t.Fatalf("unexpected vector: %v", vec)
	}
}

func TestClient_EmbedQuery_ErrorOnEmptyEmbeddings(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"embeddings": [][]float32{}})
	}))
	defer srv.Close()
	c := NewClient(srv.URL, "t", srv.Client())
	if _, err := c.EmbedQuery(context.Background(), "x"); err == nil {
		t.Fatal("expected error when no embeddings returned")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $GO && go test ./internal/embed/ -v`
Expected: FAIL — package `embed` / `NewClient` / `EmbedQuery` don't exist.

- [ ] **Step 3: Implement the client**

Create `internal/embed/client.go`:

```go
// Package embed calls the Python embedding service to produce 384-dim query
// vectors using the SAME sentence-transformers model that ingestion uses,
// preserving cosine-search model parity (see LAAM memory design spec).
package embed

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
)

// Client embeds query text via the Python POST /api/v1/embeddings endpoint.
type Client struct {
	baseURL string
	token   string
	http    *http.Client
}

// NewClient builds an embedding client. baseURL is the Python service root
// (e.g. KG_PYTHON_URL, "http://localhost:8081"); token is sent as a Bearer
// header (the endpoint requires a bearer prefix).
func NewClient(baseURL, token string, httpClient *http.Client) *Client {
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	return &Client{baseURL: baseURL, token: token, http: httpClient}
}

type embedRequest struct {
	Texts []string `json:"texts"`
}

type embedResponse struct {
	Embeddings [][]float32 `json:"embeddings"`
	Dimensions int         `json:"dimensions"`
}

// EmbedQuery returns the 384-dim vector for a single query string.
func (c *Client) EmbedQuery(ctx context.Context, query string) ([]float32, error) {
	payload, err := json.Marshal(embedRequest{Texts: []string{query}})
	if err != nil {
		return nil, fmt.Errorf("marshal embed request: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/api/v1/embeddings", bytes.NewReader(payload))
	if err != nil {
		return nil, fmt.Errorf("build embed request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.token)

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("call embed service: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("embed service status %d", resp.StatusCode)
	}

	var out embedResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, fmt.Errorf("decode embed response: %w", err)
	}
	if len(out.Embeddings) == 0 || len(out.Embeddings[0]) == 0 {
		return nil, fmt.Errorf("embed service returned no vectors")
	}
	return out.Embeddings[0], nil
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $GO && go test ./internal/embed/ -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add internal/embed/client.go internal/embed/client_test.go
git commit -m "feat(embed): Go client for Python 384-dim embedding endpoint (model parity)"
```

---

## Task 4: MCP-reachable semantic recall via `kg_search`

Expose `semantic` on the `kg_search` MCP tool, and have the `/search` handler embed the query text (via the Task 3 client) when `semantic=true` and no `query_embedding` was supplied — then the **existing** `SemanticSearch` branch runs. This is the CORE deliverable.

> **Verified codebase facts that shape this task (do not re-assume):**
> - `NewSearchHandler(s *store.SearchStore, nodeEmb *store.NodeEmbeddingStore, logger *slog.Logger)` lives in `search.go:23`. `nodeEmb` is a **concrete** `*store.NodeEmbeddingStore`, not an interface.
> - It is wired at `routes.go:38` inside `NewQueryHandlers(db *sql.DB, cfg *config.Config, logger *slog.Logger)` (`routes.go:30`), which is called at `cmd/kg-server/main.go:339` (`handler.NewQueryHandlers(db, appCfg, logger)`), then `queryHandlers.RegisterAll(apiMux)` at `:340`. **`main.go` does not call `NewSearchHandler` directly.**
> - The existing `search_test.go` constructs the handler with `NewSearchHandler(store.NewSearchStore(nil), nil, testLogger())` (passing `nil` for `nodeEmb`) and only tests **validation paths** — there is **no `fakeNodeEmbStore`** and the semantic execution path is not unit-tested (it needs a real DB). There are **8** `NewSearchHandler(` call sites in that file.
>
> Consequences: (1) the bridge schema is read via `ListToolSchemas()`, not `DefaultSchemas()`; (2) we inject the embedder through the constructor → **all 12 existing test call sites** (8 in `search_test.go` + 4 in `routes_test.go`) + `routes.go:38` + `NewQueryHandlers` + `main.go:339` must be updated; (3) the embed decision is extracted into a small method so it can be unit-tested **without a DB** (matching how the codebase already avoids DB-dependent search tests) — full embed→`SemanticSearch` execution is verified in Task 7 (E2E).

**Files:**
- Modify: `ennam.kg.go/internal/bridge/schema.go` (`kg_search` schema); append the `semantic` test to `internal/bridge/schema_laam_test.go` (created in Task 2)
- Modify: `ennam.kg.go/internal/handler/search.go` (`QueryEmbedder` interface, embedder field, `ensureQueryEmbedding` method, call it in `HandleSearch`)
- Modify: `ennam.kg.go/internal/handler/search_test.go` (new helper test + update the 8 existing constructor calls)
- Modify: `ennam.kg.go/internal/handler/routes.go` (`NewQueryHandlers` + `NewSearchHandler` call)
- Modify: `ennam.kg.go/cmd/kg-server/main.go` (build embed client; pass to `NewQueryHandlers`)

- [ ] **Step 1: Write the failing tests**

Bridge schema test — append to `internal/bridge/schema_laam_test.go` (the file created in Task 2; plain `testing` style, no testify):

```go
func TestKgSearch_HasSemanticParam(t *testing.T) {
	s, ok := ListToolSchemas()["kg_search"] // public accessor (schema.go:202)
	if !ok {
		t.Fatal("kg_search schema missing")
	}
	if _, ok := s.Properties["semantic"]; !ok {
		t.Error("kg_search must expose semantic")
	}
}
```

Handler test (`internal/handler/search_test.go`) — test the extracted `ensureQueryEmbedding` method directly with a fake embedder (no DB, no `nodeEmb` needed). Construct the handler via a struct literal (the test is in `package handler`, so unexported fields are accessible):

```go
type fakeEmbedder struct {
	called bool
	vec    []float32
}

func (f *fakeEmbedder) EmbedQuery(_ context.Context, _ string) ([]float32, error) {
	f.called = true
	return f.vec, nil
}

func TestEnsureQueryEmbedding_EmbedsWhenSemanticAndNoVector(t *testing.T) {
	emb := &fakeEmbedder{vec: []float32{0.1, 0.2, 0.3}}
	h := &SearchHandler{embedder: emb, logger: testLogger()}
	req := searchRequest{Query: "how do I auth", Semantic: true}
	if err := h.ensureQueryEmbedding(context.Background(), &req); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !emb.called {
		t.Error("semantic + no vector must embed the query text")
	}
	if len(req.QueryEmbedding) != 3 {
		t.Errorf("expected embedded vector to be set, got %v", req.QueryEmbedding)
	}
}

func TestEnsureQueryEmbedding_SkipsWhenNotSemantic(t *testing.T) {
	emb := &fakeEmbedder{vec: []float32{0.1}}
	h := &SearchHandler{embedder: emb, logger: testLogger()}
	req := searchRequest{Query: "auth", Semantic: false}
	if err := h.ensureQueryEmbedding(context.Background(), &req); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if emb.called {
		t.Error("non-semantic must not embed")
	}
	if len(req.QueryEmbedding) != 0 {
		t.Error("non-semantic must not set a vector")
	}
}

func TestEnsureQueryEmbedding_SkipsWhenVectorAlreadyPresent(t *testing.T) {
	emb := &fakeEmbedder{vec: []float32{9}}
	h := &SearchHandler{embedder: emb, logger: testLogger()}
	req := searchRequest{Query: "auth", Semantic: true, QueryEmbedding: []float32{0.5}}
	if err := h.ensureQueryEmbedding(context.Background(), &req); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if emb.called {
		t.Error("a caller-supplied vector must not be overwritten")
	}
}
```

> Plain `testing` style (no testify) — matches the existing `search_test.go`; the handler test package does **not** import testify.

> The struct-literal `&SearchHandler{embedder: emb, logger: testLogger()}` deliberately leaves `store`/`nodeEmb` nil — `ensureQueryEmbedding` never touches them, so no DB is required. (Confirm the `SearchHandler` field names `embedder`/`logger` after Step 3 adds `embedder`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $GO && go test ./internal/bridge/ -run TestKgSearch_HasSemanticParam ./internal/handler/ -run TestEnsureQueryEmbedding -v`
Expected: FAIL — no `semantic` in the schema; `SearchHandler` has no `embedder` field; `ensureQueryEmbedding` doesn't exist.

- [ ] **Step 3: Add `semantic` to the `kg_search` MCP schema**

In `internal/bridge/schema.go` (the `schemas["kg_search"]` block, ~line 1102), add a property:

```go
			"semantic": {
				Type:        TypeBoolean,
				Required:    false,
				Description: "Run semantic vector search over section embeddings (text query is embedded server-side at 384-dim) instead of full-text",
			},
```

(The `query` param already exists. No `query_embedding` is exposed via MCP — LAAM passes text only; the server embeds it.)

- [ ] **Step 4: Add the embedder + `ensureQueryEmbedding` to `SearchHandler`**

In `internal/handler/search.go`:

(a) Define the interface (top of the file, near the types):

```go
// QueryEmbedder produces a 384-dim vector for a query string via the Python
// embedding service (the same sentence-transformers model used at ingestion).
type QueryEmbedder interface {
	EmbedQuery(ctx context.Context, query string) ([]float32, error)
}
```

(b) Add the field to the struct and the constructor param (4 params now; `nodeEmb` stays concrete):

```go
type SearchHandler struct {
	store    *store.SearchStore
	nodeEmb  *store.NodeEmbeddingStore
	embedder QueryEmbedder
	logger   *slog.Logger
}

func NewSearchHandler(s *store.SearchStore, nodeEmb *store.NodeEmbeddingStore, embedder QueryEmbedder, logger *slog.Logger) *SearchHandler {
	return &SearchHandler{store: s, nodeEmb: nodeEmb, embedder: embedder, logger: logger}
}
```

(c) Add the extracted method:

```go
// ensureQueryEmbedding fills req.QueryEmbedding by embedding the text query at
// 384-dim when the caller asked for semantic search without supplying a vector.
// No-op for non-semantic requests or when a vector is already present.
func (h *SearchHandler) ensureQueryEmbedding(ctx context.Context, req *searchRequest) error {
	if !req.Semantic || len(req.QueryEmbedding) > 0 || strings.TrimSpace(req.Query) == "" || h.embedder == nil {
		return nil
	}
	vec, err := h.embedder.EmbedQuery(ctx, req.Query)
	if err != nil {
		return err
	}
	req.QueryEmbedding = vec
	return nil
}
```

(d) Call it in `HandleSearch`, **after** the request is decoded and **before** the existing semantic branch (`if req.Semantic && len(req.QueryEmbedding) > 0 && h.nodeEmb != nil`):

```go
	if err := h.ensureQueryEmbedding(ctx, &req); err != nil {
		errorResponse(w, http.StatusBadGateway, "embedding service error: "+err.Error())
		return
	}
```

The existing branch then runs `SemanticSearch` with the now-populated `req.QueryEmbedding`. Leave the existing branch condition unchanged.

- [ ] **Step 5: Update the existing `NewSearchHandler` call sites**

The constructor gained a param, so update **every** existing call to pass an embedder (or `nil`). **Verified by de-risk (2026-06-07): there are 12 test call sites, not 8** — `search_test.go` (8) **and `routes_test.go` (4: lines ~87, 107, 227, 248)**. Both files use the identical literal `NewSearchHandler(store.NewSearchStore(nil), nil, testLogger())` → change each to `NewSearchHandler(store.NewSearchStore(nil), nil, nil, testLogger())`:

- `internal/handler/routes.go:38` (production) — see Step 6 (gets the real embedder).
- `internal/handler/search_test.go` — 8 calls.
- `internal/handler/routes_test.go` — 4 calls. (Easy to miss — these broke the build during de-risk.)

Run a sanity check that **no 3-arg calls remain anywhere**:

```bash
cd $GO
# Every NewSearchHandler call across the repo must now have 4 args. This finds stragglers:
grep -rn "NewSearchHandler(" --include="*.go" internal/ cmd/ | grep -v "func NewSearchHandler"
# Quick count of the updated literal (expect 12 across search_test.go + routes_test.go):
grep -rc "NewSearchHandler(store.NewSearchStore(nil), nil, nil, testLogger())" internal/handler/*_test.go
```

- [ ] **Step 6: Thread the embedder through `NewQueryHandlers` and `main.go`**

In `internal/handler/routes.go`, add an `embedder QueryEmbedder` param to `NewQueryHandlers` and pass it into `NewSearchHandler`:

```go
func NewQueryHandlers(db *sql.DB, cfg *config.Config, logger *slog.Logger, embedder QueryEmbedder) *QueryHandlers {
	searchStore := store.NewSearchStore(db)
	nodeEmbStore := store.NewNodeEmbeddingStore(db)
	// ...
	return &QueryHandlers{
		Search: NewSearchHandler(searchStore, nodeEmbStore, embedder, logger),
		// ...unchanged...
	}
}
```

In `cmd/kg-server/main.go`, build the embed client and pass it at the `NewQueryHandlers` call (line 339). The Python URL is resolved later in `main.go` (`KG_PYTHON_URL`, ~line 645) — hoist that resolution above line 339 (or read the env again here):

```go
	pythonURL := os.Getenv("KG_PYTHON_URL")
	if pythonURL == "" {
		pythonURL = "http://localhost:8081"
	}
	embedClient := embed.NewClient(pythonURL, internalAPIToken, http.DefaultClient)
	queryHandlers := handler.NewQueryHandlers(db, appCfg, logger, embedClient)
```

> Import the new `internal/embed` package. `internalAPIToken`: the Python `/api/v1/embeddings` endpoint only checks for a `Bearer ` prefix (it does not validate the token value — verified `api/embeddings.py`), so any non-empty token works; reuse an existing server token/config value if one is handy, otherwise a fixed non-empty constant is acceptable (note it in the PR). If `KG_PYTHON_URL` is already resolved elsewhere in `main.go`, reuse that variable instead of re-reading the env.

- [ ] **Step 7: Run tests to verify they pass + build**

Run:
```bash
cd $GO
go build ./...
go test ./internal/bridge/ -run TestKgSearch -v
# Handler tests: the package is pre-existing-broken on this branch (see Verification reality).
# Once that's resolved, run: go test ./internal/handler/ -run "TestEnsureQueryEmbedding|TestSearchHandler" -v
```
Expected: `go build ./...` OK — this is the key gate; it proves **all 12 test call sites** (8 in search_test.go + 4 in routes_test.go), routes.go, and main.go were updated (a missed call site fails the build). `go test ./internal/bridge/` PASSES.

- [ ] **Step 8: Commit**

```bash
git add internal/bridge/schema.go internal/bridge/schema_laam_test.go \
        internal/handler/search.go internal/handler/search_test.go internal/handler/routes.go internal/handler/routes_test.go \
        cmd/kg-server/main.go
git commit -m "feat(search): MCP-reachable semantic recall — kg_search embeds query text at 384-dim"
```

---

## Task 5: (Decision) Hub node_type — keep `external`

The spec leaves the hub type open. **Decision: keep `external`** (current `resolve_node_type("satellite_api", …)` output). Recall behaves identically either way (sections are `document_section` regardless), and `external` correctly signals "submitted by a satellite." No change needed.

**Files:** none (decision recorded).

- [ ] **Step 1: Record the decision; note the one-line alternative**

No code change. If the team later prefers a `document` hub for satellite memory, the only change is `src/ennam_kg/ingestion/pipeline/nodes.py:14` `resolve_node_type` — return `"document"` for `satellite_api` (and update the Python ingestion test that asserts `external`). Capture this in the PR description so the decision is explicit. Recall, embeddings, and `contains_section` edges are unaffected.

---

## Task 6: Go package verification + lint

**Files:** none (verification only)

- [ ] **Step 1: Full Go test suite (race)**

Run: `cd $GO && make test` (or `go test -race -count=1 ./...`)
Expected: the **new** packages are green — `go test ./internal/embed/ ./internal/bridge/` PASS. ⚠️ **`make test` / `go test ./...` currently FAILS on this branch due to pre-existing-broken test packages (`internal/handler`, `internal/service`) unrelated to this work — see "Verification reality."** Do not treat that as a regression from this feature. Either fix the branch's broken test packages first, or gate on: `go build ./...` (must pass) + `go vet ./internal/embed/ ./internal/bridge/` + the targeted handler tests once the package compiles. Confirm `go build ./...` is clean as the hard gate for this feature's code.

- [ ] **Step 2: Lint + build**

Run: `cd $GO && make lint && make build`
Expected: golangci-lint clean; all three binaries build (`kg-server`, `kg-bridge`, `kg-migrate`).

- [ ] **Step 3: Commit any lint fixups**

```bash
git add -A && git commit -m "chore(go): lint fixups for LAAM memory recall wiring" --allow-empty
```

---

## Task 7: End-to-end verification (running stack — manual)

These steps verify the cross-service behavior that unit tests can't. Run against the full stack. They mirror the spec's Verification section.

- [ ] **Step 1: Bring up the stack**

Run: `docker compose up -d --build` (from the workspace root). Confirm `docker compose ps` shows postgres, redis, kg-server (8080), indexer/worker (8081) healthy. Ensure `ingestion.auto_queue_processing=true` (Task 1 Step 3) is set for the target project.

- [ ] **Step 2: Ingest a memory (one call)**

Call `kg_ingest_node` (via the MCP bridge or `POST /api/v1/projects/{projectId}/ingest`) with:
```json
{"title":"Deploy runbook","content_raw":"# Deploy\n\n## Rollback\n\nRun make rollback.\n","content_format":"markdown","source_id":"laam:memory:test-1","source_url":"laam://memory/test-1","auto_approve":true}
```
Expected: HTTP 201, a draft with status `created`.

- [ ] **Step 3: Assert decompose + 384-dim embeddings ran**

```bash
cd ennam.kg.go && make db-shell
# one external hub + ≥1 document_section for this source:
#   SELECT node_type, title FROM knowledge_nodes WHERE created_by LIKE '%ingest%' AND title LIKE '%Deploy%';
# 384-dim embeddings exist for those sections:
#   SELECT count(*) FROM knowledge_node_embeddings e JOIN knowledge_nodes n ON n.id=e.node_id
#     WHERE n.node_type='document_section';   -- expect ≥1, vector dim 384
```
Expected: one `external` hub + ≥1 `document_section`; embedding rows present (vector(384)).

- [ ] **Step 4: Recall (the new path)**

Call `kg_search` with `{"project_id":"<p>","query":"how do I undo a deploy","semantic":true}`.
Expected: returns the **Rollback** section. Confirm the server embedded the query at **384-dim** (check kg-server logs / that the embed call hit Python `/api/v1/embeddings`, NOT the 1536-dim `context_builder` table path).

- [ ] **Step 5: Dedup on re-send**

Re-`kg_ingest_node` the **same** `source_id` with edited content. Expected: draft status `updated`, sections refreshed, **no duplicate** hub.

- [ ] **Step 6: Negative + provenance**

- A query unrelated to any memory → does **not** return the runbook (sanity).
- `SELECT source_url FROM draft_nodes WHERE source_id='laam:memory:test-1';` → `laam://memory/test-1`.
- No `uploaded_files` row and nothing under `./data/uploads` (Path B confirmed — text-only).

- [ ] **Step 7: Record results**

Write the E2E outcomes (pass/fail per step, with the SQL/log evidence) into the PR description or a checkpoint. If any step fails, debug before merging — these are the real acceptance criteria.

---

## Self-Review

**Spec "Work to build" coverage:**
- #1 MCP-reachable semantic recall (CORE) → Tasks 3 + 4 (option b: `kg_search` `semantic` + Go embed client → existing `SemanticSearch`). Model parity (Q5) preserved by calling the same 384-dim `LocalEmbeddingModel` via `/api/v1/embeddings`. ✓
- #2 `source_url` plumbing → Task 2. ✓
- #3 One-call ingest+process → Task 1 (enable existing `auto_queue_processing`; no `kg_remember` tool — YAGNI). ✓
- #4 Hub node_type decision → Task 5 (keep `external`; one-line alternative noted). ✓

**Decisions (Q1–Q6) honored:** Q1 ingestion pipeline (untouched); Q2 deterministic decompose (reused); Q3 `auto_approve=true` (passed through); Q4 (a) auto-queue (Task 1); Q5 384-dim parity (Task 3/4 hard constraint — calls the same model); Q6 Path B text-only (no upload path touched; `source_url` provenance in Task 2; E2E Step 6 asserts no blob). ✓

**Findings folded in:** recall pre-exists in Python (option b reuses `/embeddings` + `SemanticSearch` rather than rebuilding); `auto_queue_processing` is a Go setting (toggle, not build); `source_url` already persists at the store layer (only request/schema missing). All flagged in "Findings."

**Out of scope (per spec):** indexer markdown parser, Path A blob upload, new embedding storage/model, dimension change, decomposition re-spec, cross-source linking. Not touched. ✓

**Verification honesty:** unit/handler/bridge tests cover every code change (Tasks 1–4, 6); true cross-service E2E requires a running stack (Task 7 manual checklist). Stated explicitly up front.

**Placeholder scan:** No TBD/TODO. Code blocks are complete; the few "confirm the exact site / mirror existing fakes" notes point at real, cited structures (test harnesses and constructors that must be read, not invented) — not missing logic.

**Type consistency:** `embed.Client.EmbedQuery(ctx, string) ([]float32, error)` satisfies the `QueryEmbedder` interface field on `SearchHandler`; the corrected `NewSearchHandler(s, nodeEmb, embedder, logger)` signature is reflected at every call site (routes.go:38, the **12** test calls — 8 in search_test.go + 4 in routes_test.go — and the new `&SearchHandler{embedder:…}` literal); `NewQueryHandlers(db, cfg, logger, embedder)` (main.go:339) threads it. `ensureQueryEmbedding` populates `req.QueryEmbedding`, which the existing semantic branch keys on (`len(req.QueryEmbedding) > 0`). Bridge schemas are read via `ListToolSchemas()` (not `DefaultSchemas`). `PublicIngestItem.SourceURL` (string) maps to `DraftNode.SourceURL` (`*string`) via the nil-when-empty guard. ✓

**Structural assumptions verified against code (2026-06-07):** `NewSearchHandler`/`SearchHandler` shape (`search.go:16,23`); wiring chain `main.go:339 → NewQueryHandlers (routes.go:30) → NewSearchHandler (routes.go:38)`; existing `search_test.go` passes `nil` nodeEmb + tests only validation (8 constructor calls); `ListToolSchemas()` is the schema accessor (`schema.go:202`); store `Upsert` already binds `source_url` (`store/draft_node.go:17,30,89`); `SemanticSearch(ctx, projectID, []float32, int, []string) ([]store.SearchResult, error)` (`node_embedding.go:49`); `ingestion.auto_queue_processing` setting + `ProcessBatch` enqueue (`ingestion_settings.go:78`, `draft_node.go:172`); Python `/api/v1/embeddings` exists (`api/embeddings.py:28`). ✓

---

## Execution Handoff
