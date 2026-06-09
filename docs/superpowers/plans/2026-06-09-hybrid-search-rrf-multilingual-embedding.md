# Hybrid Search (RRF) + Multilingual Embedding — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `hybrid` `kg_search` mode that fuses full-text (`ts_rank`) and semantic (pgvector cosine) results via Reciprocal Rank Fusion, and swap the section-embedding model to multilingual `intfloat/multilingual-e5-small` (still 384-dim) so Vietnamese recall works — all on managed RDS, no new extension, no `vector(384)` migration.

**Architecture:** Two independent embedding systems exist; this plan touches **only** the 384-dim `knowledge_node_embeddings` system (NOT the 1536-dim BA-020 table-schema embeddings). Python gains prefix-aware e5 encode helpers and a re-embed admin endpoint. Go gains a pure RRF fusion function, a hybrid handler branch that runs the two existing arms concurrently with fail-soft, a `mode` MCP param, and a project-scoped embeddings-list endpoint to back the backfill.

**Tech Stack:** Go (stdlib `net/http`, `database/sql`, `sync.WaitGroup`, `log/slog`, `go test`), Python 3.12 (FastAPI, sentence-transformers, pytest), PostgreSQL 16 + pgvector (HNSW cosine index already present).

**Spec:** `../specs/2026-06-09-hybrid-search-rrf-multilingual-embedding-design.md`

---

## File Structure

**Python (`ennam.kg.python/`)**
- Modify `src/ennam_kg/embeddings/local_model.py` — add `encode_query` / `encode_passage` (prefix-aware).
- Modify `src/ennam_kg/embeddings/models.py` — add `input_type` to `EmbeddingRequest`.
- Modify `src/ennam_kg/api/embeddings.py` — route to the matching helper by `input_type`.
- Modify `src/ennam_kg/ingestion/pipeline/decompose.py:194` — use `encode_passage`.
- Modify `src/ennam_kg/config.py:26` — default model → e5.
- Create `src/ennam_kg/api/admin.py` — `POST /api/v1/admin/reembed`.
- Modify `src/ennam_kg/main.py:60` — register the admin router.
- Modify `packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py` — add `list_node_embeddings`.

**Go (`ennam.kg.go/`)**
- Create `internal/store/rrf.go` — pure `ReciprocalRankFusion`.
- Modify `internal/store/node_embedding.go` — add `ListByProject`.
- Modify `internal/handler/search.go` — `Mode` field, mode normalization, hybrid branch, store interfaces.
- Modify `internal/handler/document.go` — `GET .../node-embeddings` list endpoint.
- Modify `internal/bridge/schema.go:1102` — `mode` param + `node_types` enum extension.

---

## Ordering & Rationale

Python embedding parity first (foundational, isolated), then Go RRF core (pure, no deps), then the Go hybrid wiring, then the MCP schema, then the backfill read+write path, then the eval. Each task is independently testable and committable.

---

## Task 1: Python — prefix-aware encode helpers

e5 requires `"query: "` / `"passage: "` prefixes; a mismatch silently degrades cosine. Centralize the prefix in one place; make it model-aware so non-e5 models (the current `all-MiniLM`) are never prefixed.

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/embeddings/local_model.py`
- Test: `ennam.kg.python/tests/test_embeddings/test_prefix.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.python/tests/test_embeddings/test_prefix.py`:

```python
"""IMP-005: e5 asymmetric prefix parity."""
from unittest.mock import MagicMock

from ennam_kg.embeddings.local_model import LocalEmbeddingModel


def _model_with_capture(name: str):
    m = LocalEmbeddingModel(model_name=name)
    captured: list[list[str]] = []

    def fake_encode(texts):
        captured.append(list(texts))
        return [[0.0] * 384 for _ in texts]

    m.encode = fake_encode  # type: ignore[assignment]
    return m, captured


def test_e5_query_prefix_applied():
    m, captured = _model_with_capture("intfloat/multilingual-e5-small")
    m.encode_query(["rủi ro pháp lý"])
    assert captured[0] == ["query: rủi ro pháp lý"]


def test_e5_passage_prefix_applied():
    m, captured = _model_with_capture("intfloat/multilingual-e5-small")
    m.encode_passage(["Điều khoản hợp đồng"])
    assert captured[0] == ["passage: Điều khoản hợp đồng"]


def test_non_e5_model_gets_no_prefix():
    m, captured = _model_with_capture("all-MiniLM-L6-v2")
    m.encode_query(["hello"])
    m.encode_passage(["world"])
    assert captured[0] == ["hello"]
    assert captured[1] == ["world"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_embeddings/test_prefix.py -v`
Expected: FAIL — `AttributeError: 'LocalEmbeddingModel' object has no attribute 'encode_query'`

- [ ] **Step 3: Implement the helpers**

In `ennam.kg.python/src/ennam_kg/embeddings/local_model.py`, add these methods to `LocalEmbeddingModel` (after `encode`):

```python
    def _needs_e5_prefix(self) -> bool:
        # e5 family requires asymmetric prefixes; non-e5 models (e.g. all-MiniLM) must NOT be prefixed.
        return "e5" in self._model_name.lower()

    def encode_query(self, texts: list[str]) -> list[list[float]]:
        prepared = [f"query: {t}" for t in texts] if self._needs_e5_prefix() else texts
        return self.encode(prepared)

    def encode_passage(self, texts: list[str]) -> list[list[float]]:
        prepared = [f"passage: {t}" for t in texts] if self._needs_e5_prefix() else texts
        return self.encode(prepared)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_embeddings/test_prefix.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/embeddings/local_model.py tests/test_embeddings/test_prefix.py
git commit -m "feat: prefix-aware e5 encode_query/encode_passage helpers (IMP-005 FR-2)"
```

---

## Task 2: Python — `input_type` on EmbeddingRequest + route endpoint to helper

The query endpoint must apply the `query:` prefix. Add `input_type` (default `"query"`) and route to the matching helper.

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/embeddings/models.py`
- Modify: `ennam.kg.python/src/ennam_kg/api/embeddings.py`
- Test: `ennam.kg.python/tests/test_embeddings/test_endpoint_input_type.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.python/tests/test_embeddings/test_endpoint_input_type.py`:

```python
"""IMP-005: /api/v1/embeddings applies query prefix by default, passage when asked."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from ennam_kg.main import app

client = TestClient(app)


def _post(body):
    return client.post("/api/v1/embeddings", json=body, headers={"Authorization": "Bearer test"})


@patch("ennam_kg.api.embeddings._get_local_model")
def test_default_input_type_is_query(mock_get_model):
    model = mock_get_model.return_value
    model.model_name = "intfloat/multilingual-e5-small"
    model.dimensions = 384
    model.encode_query.return_value = [[0.0] * 384]
    model.encode_passage.return_value = [[0.0] * 384]

    resp = _post({"texts": ["hello"]})
    assert resp.status_code == 200
    model.encode_query.assert_called_once_with(["hello"])
    model.encode_passage.assert_not_called()


@patch("ennam_kg.api.embeddings._get_local_model")
def test_passage_input_type_routes_to_passage(mock_get_model):
    model = mock_get_model.return_value
    model.model_name = "intfloat/multilingual-e5-small"
    model.dimensions = 384
    model.encode_query.return_value = [[0.0] * 384]
    model.encode_passage.return_value = [[0.0] * 384]

    resp = _post({"texts": ["hello"], "input_type": "passage"})
    assert resp.status_code == 200
    model.encode_passage.assert_called_once_with(["hello"])
    model.encode_query.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_embeddings/test_endpoint_input_type.py -v`
Expected: FAIL — endpoint still calls `model.encode(...)`, so `encode_query` is never called (`assert_called_once_with` fails).

- [ ] **Step 3: Add `input_type` to the request model**

In `ennam.kg.python/src/ennam_kg/embeddings/models.py`, add the field to `EmbeddingRequest` (after `model`):

```python
class EmbeddingRequest(BaseModel):
    texts: list[str]
    model: str | None = None
    input_type: str = "query"  # "query" (default) | "passage" — selects e5 prefix
```

- [ ] **Step 4: Route the endpoint to the matching helper**

In `ennam.kg.python/src/ennam_kg/api/embeddings.py`, replace the encode line:

```python
    start = time.monotonic()
    if body.input_type == "passage":
        vectors = model.encode_passage(body.texts)
    else:
        vectors = model.encode_query(body.texts)
    elapsed_ms = int((time.monotonic() - start) * 1000)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_embeddings/test_endpoint_input_type.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/embeddings/models.py src/ennam_kg/api/embeddings.py tests/test_embeddings/test_endpoint_input_type.py
git commit -m "feat: route /api/v1/embeddings by input_type to query/passage helper (IMP-005 FR-2)"
```

---

## Task 3: Python — ingest passages via `encode_passage`

The ingest pipeline embeds sections as **passages**. Route `decompose.py` through `encode_passage` so the prefix matches the query side.

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/pipeline/decompose.py:194`
- Test: `ennam.kg.python/tests/test_pipeline/test_decompose_passage.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.python/tests/test_pipeline/test_decompose_passage.py`:

```python
"""IMP-005: decompose embeds sections as passages."""
import inspect

from ennam_kg.ingestion.pipeline import decompose


def test_decompose_uses_encode_passage_not_raw_encode():
    src = inspect.getsource(decompose.decompose_document)
    assert "encode_passage(" in src, "section embedding must use encode_passage"
    assert "model.encode(" not in src, "raw encode() must not be used for passages"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_pipeline/test_decompose_passage.py -v`
Expected: FAIL — `decompose.py` still calls `model.encode(batch_texts)`.

- [ ] **Step 3: Switch to `encode_passage`**

In `ennam.kg.python/src/ennam_kg/ingestion/pipeline/decompose.py`, change the encode call inside the batch loop (currently `vectors = model.encode(batch_texts)`):

```python
                vectors = model.encode_passage(batch_texts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_pipeline/test_decompose_passage.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the existing pipeline tests to confirm no regression**

Run: `cd ennam.kg.python && uv run pytest tests/test_pipeline/ -v`
Expected: PASS (all existing pipeline tests still green)

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/ingestion/pipeline/decompose.py tests/test_pipeline/test_decompose_passage.py
git commit -m "feat: embed ingested sections as e5 passages (IMP-005 FR-2)"
```

---

## Task 4: Python — switch default model to multilingual e5

Change the default model. (Operationally this is the cutover step — in prod it is set via env; per BR-007 the backfill in Task 11 must run before queries use it. The code default change is safe because new ingest writes the new space and the backfill re-embeds old rows.)

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/config.py:26`
- Test: `ennam.kg.python/tests/test_config_model.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.python/tests/test_config_model.py`:

```python
"""IMP-005: default embedding model is multilingual e5, still 384-dim."""
from ennam_kg.config import Settings


def test_default_model_is_multilingual_e5():
    s = Settings()
    assert s.embedding_model_name == "intfloat/multilingual-e5-small"
    assert s.embedding_dimensions == 384  # locked — no pgvector migration
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_config_model.py -v`
Expected: FAIL — default is still `all-MiniLM-L6-v2`.

- [ ] **Step 3: Change the default**

In `ennam.kg.python/src/ennam_kg/config.py`, change the embedding model default (keep `embedding_dimensions` at 384):

```python
    embedding_model_name: str = "intfloat/multilingual-e5-small"  # Local embedding model (multilingual, 384-dim)
    embedding_dimensions: int = 384  # Must match pgvector config in BA-020 — LOCKED
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_config_model.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/config.py tests/test_config_model.py
git commit -m "feat: default embedding model -> multilingual-e5-small, 384-dim locked (IMP-005 FR-2)"
```

---

## Task 5: Go — pure RRF fusion function

Reciprocal Rank Fusion over N ranked lists. Pure, no DB — this is the risky math, so it gets thorough table-driven coverage.

**Files:**
- Create: `ennam.kg.go/internal/store/rrf.go`
- Test: `ennam.kg.go/internal/store/rrf_test.go` (create)

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/store/rrf_test.go`:

```go
package store

import (
	"testing"
	"time"
)

func res(id string, updated time.Time) SearchResult {
	return SearchResult{ID: id, UpdatedAt: updated}
}

func TestReciprocalRankFusion(t *testing.T) {
	t0 := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)

	t.Run("fuses two lists and dedups by id", func(t *testing.T) {
		lexical := []SearchResult{res("A", t0), res("B", t0)}
		semantic := []SearchResult{res("B", t0), res("C", t0)}
		out := ReciprocalRankFusion([][]SearchResult{lexical, semantic}, 60, 10)
		// B appears in both (rank1=2, rank2=1) -> highest score; A and C appear once.
		if len(out) != 3 {
			t.Fatalf("want 3 merged, got %d", len(out))
		}
		if out[0].ID != "B" {
			t.Fatalf("want B ranked first, got %s", out[0].ID)
		}
		// B score = 1/(60+2) + 1/(60+1) ; A = 1/(60+1)
		if out[0].Rank <= out[1].Rank {
			t.Fatalf("B rank %.6f must exceed runner-up %.6f", out[0].Rank, out[1].Rank)
		}
	})

	t.Run("empty arm is ignored", func(t *testing.T) {
		out := ReciprocalRankFusion([][]SearchResult{{res("A", t0)}, {}}, 60, 10)
		if len(out) != 1 || out[0].ID != "A" {
			t.Fatalf("want [A], got %+v", out)
		}
	})

	t.Run("truncates to limit", func(t *testing.T) {
		in := []SearchResult{res("A", t0), res("B", t0), res("C", t0)}
		out := ReciprocalRankFusion([][]SearchResult{in}, 60, 2)
		if len(out) != 2 {
			t.Fatalf("want 2, got %d", len(out))
		}
	})

	t.Run("tie-break by updated_at desc", func(t *testing.T) {
		older := t0
		newer := t0.Add(time.Hour)
		// Same rank position in single list -> same RRF score; newer must sort first.
		out := ReciprocalRankFusion([][]SearchResult{{res("OLD", older)}, {res("NEW", newer)}}, 60, 10)
		if out[0].ID != "NEW" {
			t.Fatalf("want NEW first on tie, got %s", out[0].ID)
		}
	})
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestReciprocalRankFusion -v`
Expected: FAIL — `undefined: ReciprocalRankFusion`

- [ ] **Step 3: Implement the function**

Create `ennam.kg.go/internal/store/rrf.go`:

```go
package store

import "sort"

// ReciprocalRankFusion merges several ranked result lists into one ranking using
// Reciprocal Rank Fusion: score(doc) = Σ 1/(k + rank_i(doc)), 1-based rank per list.
// Because it uses ranks (not raw scores), it tolerates the incomparable ts_rank
// (0–1) and cosine scales without normalization. Results are deduped by node id;
// the first list to surface a node supplies the returned row. Sorted by RRF score
// desc, tie-broken by UpdatedAt desc. The returned rows carry the RRF score in Rank.
func ReciprocalRankFusion(lists [][]SearchResult, k int, limit int) []SearchResult {
	if k <= 0 {
		k = 60
	}
	scores := make(map[string]float64)
	keep := make(map[string]SearchResult)
	order := make([]string, 0)

	for _, list := range lists {
		for i, row := range list {
			rank := i + 1 // 1-based
			scores[row.ID] += 1.0 / float64(k+rank)
			if _, seen := keep[row.ID]; !seen {
				keep[row.ID] = row
				order = append(order, row.ID)
			}
		}
	}

	merged := make([]SearchResult, 0, len(order))
	for _, id := range order {
		row := keep[id]
		row.Rank = scores[id]
		merged = append(merged, row)
	}

	sort.SliceStable(merged, func(a, b int) bool {
		if merged[a].Rank != merged[b].Rank {
			return merged[a].Rank > merged[b].Rank
		}
		return merged[a].UpdatedAt.After(merged[b].UpdatedAt)
	})

	if limit > 0 && len(merged) > limit {
		merged = merged[:limit]
	}
	return merged
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestReciprocalRankFusion -v`
Expected: PASS (all subtests)

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/store/rrf.go internal/store/rrf_test.go
git commit -m "feat: pure Reciprocal Rank Fusion over ranked result lists (IMP-005 FR-1)"
```

---

## Task 6: Go — mode normalization helper

Map the request (`mode` + legacy `semantic`) to one effective mode. Pure function, fully unit-tested.

**Files:**
- Modify: `ennam.kg.go/internal/handler/search.go` (add `Mode` field + `effectiveSearchMode`)
- Test: `ennam.kg.go/internal/handler/search_mode_test.go` (create)

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/handler/search_mode_test.go`:

```go
package handler

import "testing"

func TestEffectiveSearchMode(t *testing.T) {
	cases := []struct {
		name     string
		mode     string
		semantic bool
		want     string
	}{
		{"empty defaults to fulltext", "", false, "fulltext"},
		{"explicit fulltext", "fulltext", false, "fulltext"},
		{"explicit hybrid", "hybrid", false, "hybrid"},
		{"explicit semantic", "semantic", false, "semantic"},
		{"legacy semantic=true maps to semantic", "", true, "semantic"},
		{"mode takes precedence over legacy flag", "hybrid", true, "hybrid"},
		{"unknown mode falls back to fulltext", "bogus", false, "fulltext"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := effectiveSearchMode(c.mode, c.semantic)
			if got != c.want {
				t.Fatalf("effectiveSearchMode(%q,%v)=%q want %q", c.mode, c.semantic, got, c.want)
			}
		})
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestEffectiveSearchMode -v`
Expected: FAIL — `undefined: effectiveSearchMode`

- [ ] **Step 3: Add the `Mode` field and the helper**

In `ennam.kg.go/internal/handler/search.go`, add `Mode` to `searchRequest` (after `Semantic`):

```go
	Semantic        bool      `json:"semantic,omitempty"`
	Mode            string    `json:"mode,omitempty"` // "fulltext" (default) | "semantic" | "hybrid"
	QueryEmbedding  []float32 `json:"query_embedding,omitempty"`
```

Then add the helper (package-level, near the bottom of the file):

```go
// effectiveSearchMode resolves the request mode. `mode` wins; legacy semantic=true
// maps to "semantic"; anything unrecognized falls back to "fulltext".
func effectiveSearchMode(mode string, semantic bool) string {
	switch mode {
	case "hybrid":
		return "hybrid"
	case "semantic":
		return "semantic"
	case "fulltext":
		return "fulltext"
	}
	if semantic {
		return "semantic"
	}
	return "fulltext"
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestEffectiveSearchMode -v`
Expected: PASS (all subtests)

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/handler/search.go internal/handler/search_mode_test.go
git commit -m "feat: kg_search mode normalization (fulltext/semantic/hybrid) (IMP-005 FR-1)"
```

---

## Task 7: Go — store interfaces + hybrid branch with concurrent fail-soft

Introduce two tiny interfaces so the hybrid branch is unit-testable with fakes (the concrete stores already satisfy them — `NewSearchHandler` and `routes.go` are unchanged). Wire the hybrid branch: embed once, run both arms concurrently via `sync.WaitGroup`, fail-soft, fuse with RRF.

**Files:**
- Modify: `ennam.kg.go/internal/handler/search.go`
- Test: `ennam.kg.go/internal/handler/search_hybrid_test.go` (create)

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/handler/search_hybrid_test.go`:

```go
package handler

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/store"
)

type fakeLexical struct {
	resp *store.SearchResponse
	err  error
	last store.SearchParams
}

func (f *fakeLexical) Search(_ context.Context, p store.SearchParams) (*store.SearchResponse, error) {
	f.last = p
	return f.resp, f.err
}

type fakeSemantic struct {
	rows []store.SearchResult
	err  error
}

func (f *fakeSemantic) SemanticSearch(_ context.Context, _ string, _ []float32, _ int, _ []string) ([]store.SearchResult, error) {
	return f.rows, f.err
}

type fakeEmbedder struct {
	vec []float32
	err error
}

func (f *fakeEmbedder) EmbedQuery(_ context.Context, _ string) ([]float32, error) {
	return f.vec, f.err
}

func newHybridHandler(lex lexicalSearcher, sem semanticSearcher, emb QueryEmbedder) *SearchHandler {
	return &SearchHandler{store: lex, nodeEmb: sem, embedder: emb, rrfK: 60, logger: slog.Default()}
}

func doHybrid(h *SearchHandler, body string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(http.MethodPost, "/api/v1/search", strings.NewReader(body))
	w := httptest.NewRecorder()
	h.HandleSearch(w, r)
	return w
}

const hybridBody = `{"query":"x","project_id":"p1","mode":"hybrid"}`

func decodeResults(t *testing.T, w *httptest.ResponseRecorder) []store.SearchResult {
	t.Helper()
	var resp store.SearchResponse
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode: %v", err)
	}
	return resp.Results
}

func TestHybrid_FusesBothArms(t *testing.T) {
	lex := &fakeLexical{resp: &store.SearchResponse{Results: []store.SearchResult{{ID: "A"}, {ID: "B"}}}}
	sem := &fakeSemantic{rows: []store.SearchResult{{ID: "B"}, {ID: "C"}}}
	w := doHybrid(newHybridHandler(lex, sem, &fakeEmbedder{vec: []float32{0.1}}), hybridBody)
	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
	if got := len(decodeResults(t, w)); got != 3 {
		t.Fatalf("want 3 fused, got %d", got)
	}
}

func TestHybrid_EmbeddingDown_FallsBackToFulltext(t *testing.T) {
	lex := &fakeLexical{resp: &store.SearchResponse{Results: []store.SearchResult{{ID: "A"}}}}
	sem := &fakeSemantic{err: errors.New("should not be called")}
	w := doHybrid(newHybridHandler(lex, sem, &fakeEmbedder{err: errors.New("embed down")}), hybridBody)
	if w.Code != http.StatusOK {
		t.Fatalf("want 200 fail-soft, got %d", w.Code)
	}
	if got := len(decodeResults(t, w)); got != 1 {
		t.Fatalf("want 1 fulltext result, got %d", got)
	}
}

func TestHybrid_SemanticArmErrors_ReturnsLexicalOnly(t *testing.T) {
	lex := &fakeLexical{resp: &store.SearchResponse{Results: []store.SearchResult{{ID: "A"}}}}
	sem := &fakeSemantic{err: errors.New("pgvector boom")}
	w := doHybrid(newHybridHandler(lex, sem, &fakeEmbedder{vec: []float32{0.1}}), hybridBody)
	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
	if got := len(decodeResults(t, w)); got != 1 {
		t.Fatalf("want 1 lexical-only, got %d", got)
	}
}

func TestHybrid_BothArmsError_Returns500(t *testing.T) {
	lex := &fakeLexical{err: errors.New("fts boom")}
	sem := &fakeSemantic{err: errors.New("pgvector boom")}
	w := doHybrid(newHybridHandler(lex, sem, &fakeEmbedder{vec: []float32{0.1}}), hybridBody)
	if w.Code != http.StatusInternalServerError {
		t.Fatalf("want 500, got %d", w.Code)
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestHybrid -v`
Expected: FAIL — `undefined: lexicalSearcher` / `undefined: semanticSearcher` / `SearchHandler` has no field `rrfK`.

- [ ] **Step 3: Add interfaces, change struct fields, add `rrfK`**

In `ennam.kg.go/internal/handler/search.go`, add the interfaces near `QueryEmbedder`:

```go
// lexicalSearcher is the full-text arm (satisfied by *store.SearchStore).
type lexicalSearcher interface {
	Search(ctx context.Context, params store.SearchParams) (*store.SearchResponse, error)
}

// semanticSearcher is the vector arm (satisfied by *store.NodeEmbeddingStore).
type semanticSearcher interface {
	SemanticSearch(ctx context.Context, projectID string, queryEmbedding []float32, topK int, nodeTypes []string) ([]store.SearchResult, error)
}
```

Change the struct fields (was `store *store.SearchStore` and `nodeEmb *store.NodeEmbeddingStore`):

```go
type SearchHandler struct {
	store    lexicalSearcher
	nodeEmb  semanticSearcher
	embedder QueryEmbedder
	rrfK     int
	logger   *slog.Logger
}
```

Update `NewSearchHandler` to set `rrfK` with the default and keep its concrete parameter types (they satisfy the interfaces):

```go
func NewSearchHandler(s *store.SearchStore, nodeEmb *store.NodeEmbeddingStore, embedder QueryEmbedder, logger *slog.Logger) *SearchHandler {
	return &SearchHandler{
		store:    s,
		nodeEmb:  nodeEmb,
		embedder: embedder,
		rrfK:     defaultRRFK,
		logger:   logger,
	}
}
```

Add the constant near the top of the file (after imports):

```go
// defaultRRFK is the standard Reciprocal Rank Fusion constant.
const defaultRRFK = 60

// hybridEmbeddedNodeTypes is the candidate set both hybrid arms run over.
// Keep aligned with what the ingest worker actually embeds (today: document_section).
var hybridEmbeddedNodeTypes = []string{"document_section"}
```

- [ ] **Step 4: Add the hybrid branch in `HandleSearch`**

In `ennam.kg.go/internal/handler/search.go`, inside `HandleSearch`, **immediately before** the existing `// Phase 6.2: semantic vector search ...` block, insert the hybrid branch. (Add `"sync"` to the import block.)

```go
	// IMP-005: hybrid search — fuse FTS + semantic via RRF.
	if effectiveSearchMode(req.Mode, req.Semantic) == "hybrid" && h.nodeEmb != nil {
		h.handleHybrid(ctx, w, &req, limit)
		return
	}
```

Then add the method (package level, below `HandleSearch`):

```go
// handleHybrid runs the full-text and semantic arms concurrently and fuses them
// with RRF. Fail-soft: if the query cannot be embedded, fall back to a plain
// full-text search; if only one arm errors, return the other; only 500 if both fail.
func (h *SearchHandler) handleHybrid(ctx context.Context, w http.ResponseWriter, req *searchRequest, limit int) {
	// Embed the query once (server-side e5 "query:" prefix lives in Python).
	if err := h.ensureQueryEmbeddingForHybrid(ctx, req); err != nil {
		h.logger.WarnContext(ctx, "hybrid: embedding failed, falling back to fulltext", "error", err)
		h.respondFulltext(ctx, w, req, limit)
		return
	}

	// Candidate scope: both arms run over the embedded set (caller override wins).
	scope := req.NodeTypes
	if len(scope) == 0 {
		scope = hybridEmbeddedNodeTypes
	}

	var (
		wg          sync.WaitGroup
		lexResp     *store.SearchResponse
		lexErr      error
		semRows     []store.SearchResult
		semErr      error
	)
	wg.Add(2)
	go func() {
		defer wg.Done()
		lexResp, lexErr = h.store.Search(ctx, store.SearchParams{
			Query:           req.Query,
			ProjectID:       req.ProjectID,
			CrossProjectIDs: req.CrossProjectIDs,
			NodeTypes:       scope,
			Status:          req.Status,
			Limit:           limit,
			Offset:          0,
		})
	}()
	go func() {
		defer wg.Done()
		semRows, semErr = h.nodeEmb.SemanticSearch(ctx, req.ProjectID, req.QueryEmbedding, limit, scope)
	}()
	wg.Wait()

	if lexErr != nil && semErr != nil {
		h.logger.ErrorContext(ctx, "hybrid: both arms failed", "lexical", lexErr, "semantic", semErr)
		errorResponse(w, http.StatusInternalServerError, "search failed")
		return
	}

	lists := make([][]store.SearchResult, 0, 2)
	if lexErr == nil && lexResp != nil {
		lists = append(lists, lexResp.Results)
	} else if lexErr != nil {
		h.logger.WarnContext(ctx, "hybrid: lexical arm failed, semantic-only", "error", lexErr)
	}
	if semErr == nil {
		lists = append(lists, semRows)
	} else {
		h.logger.WarnContext(ctx, "hybrid: semantic arm failed, lexical-only", "error", semErr)
	}

	fused := store.ReciprocalRankFusion(lists, h.rrfK, limit)
	writeJSON(w, http.StatusOK, &store.SearchResponse{
		Results:    fused,
		TotalCount: len(fused),
		Limit:      limit,
		Offset:     req.Offset,
		Query:      req.Query,
	})
}

// ensureQueryEmbeddingForHybrid fills req.QueryEmbedding for hybrid mode (the
// existing ensureQueryEmbedding only fires when req.Semantic is set).
func (h *SearchHandler) ensureQueryEmbeddingForHybrid(ctx context.Context, req *searchRequest) error {
	if len(req.QueryEmbedding) > 0 || strings.TrimSpace(req.Query) == "" || h.embedder == nil {
		return nil
	}
	vec, err := h.embedder.EmbedQuery(ctx, req.Query)
	if err != nil {
		return err
	}
	req.QueryEmbedding = vec
	return nil
}

// respondFulltext runs a plain full-text search honoring only the caller's
// explicit node_types (no injected embedded-set restriction) — the most useful
// degradation when the embedding service is down.
func (h *SearchHandler) respondFulltext(ctx context.Context, w http.ResponseWriter, req *searchRequest, limit int) {
	resp, err := h.store.Search(ctx, store.SearchParams{
		Query:           req.Query,
		ProjectID:       req.ProjectID,
		CrossProjectIDs: req.CrossProjectIDs,
		NodeTypes:       req.NodeTypes,
		Status:          req.Status,
		Limit:           limit,
		Offset:          req.Offset,
		IncludeHeadline: req.IncludeHeadline,
	})
	if err != nil {
		h.logger.ErrorContext(ctx, "hybrid fallback fulltext failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "search failed")
		return
	}
	writeJSON(w, http.StatusOK, resp)
}
```

> `writeJSON(w, status, v)` already exists in this package (`document.go`) — reuse it; do **not** redefine it. Add only `"sync"` to the `search.go` import block (`encoding/json`, `strings`, `net/http`, `store` are already imported).

- [ ] **Step 5: Run the hybrid tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestHybrid -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full handler + store packages with race detector**

Run: `cd ennam.kg.go && go test ./internal/handler/ ./internal/store/ -race`
Expected: PASS (no regression; existing search tests still green)

- [ ] **Step 7: Commit**

```bash
cd ennam.kg.go
git add internal/handler/search.go internal/handler/search_hybrid_test.go
git commit -m "feat: hybrid kg_search branch — concurrent arms, RRF fusion, fail-soft (IMP-005 FR-1)"
```

---

## Task 8: Go — `mode` param on the `kg_search` MCP schema

Expose `mode` to MCP clients; keep `semantic` for back-compat; extend `node_types` enum so callers can target embedded types. Tool count must stay unchanged.

**Files:**
- Modify: `ennam.kg.go/internal/bridge/schema.go:1102-1162`
- Test: `ennam.kg.go/internal/bridge/schema_mode_test.go` (create)

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.go/internal/bridge/schema_mode_test.go`:

```go
package bridge

import "testing"

func TestKgSearchHasModeParam(t *testing.T) {
	s, ok := ListToolSchemas()["kg_search"]
	if !ok {
		t.Fatal("kg_search schema missing")
	}
	mode, ok := s.Properties["mode"]
	if !ok {
		t.Fatal("kg_search missing 'mode' property")
	}
	want := map[string]bool{"fulltext": true, "semantic": true, "hybrid": true}
	if len(mode.Enum) != len(want) {
		t.Fatalf("mode enum = %v, want keys %v", mode.Enum, want)
	}
	for _, v := range mode.Enum {
		if !want[v] {
			t.Fatalf("unexpected mode enum value %q", v)
		}
	}
}
```

> `ListToolSchemas()` is the public accessor used by the existing tests (`schema_test.go`, `schema_laam_test.go`). The existing `TestAllToolSchemasRegistered` asserts a fixed tool count (32) — adding a *property* to `kg_search` must keep that test green.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/bridge/ -run TestKgSearchHasModeParam -v`
Expected: FAIL — `kg_search missing 'mode' property`

- [ ] **Step 3: Add the `mode` property and extend `node_types`**

In `ennam.kg.go/internal/bridge/schema.go`, inside the `kg_search` `Properties` map, add a `mode` property (next to `semantic`):

```go
			"mode": {
				Type:        TypeString,
				Required:    false,
				Description: "Search mode: 'fulltext' (default, ts_rank), 'semantic' (vector cosine over section embeddings), or 'hybrid' (RRF fusion of both). Takes precedence over 'semantic'; semantic=true is equivalent to mode=semantic.",
				Enum:        []string{"fulltext", "semantic", "hybrid"},
			},
```

In the same `kg_search` schema, extend the `node_types` `Items.Enum` to include the embedded types used by hybrid/semantic:

```go
				Items: &ParamSchema{
					Type: TypeString,
					Enum: []string{
						"decision", "concept", "requirement", "task", "architecture", "discovery",
						"document", "document_section",
					},
				},
```

- [ ] **Step 4: Run the schema test + the existing tool-count test**

Run: `cd ennam.kg.go && go test ./internal/bridge/ -v`
Expected: PASS — `mode` present AND the existing tool-count test is still green (a property add does not change the tool count). If a pre-existing tool-count test was already failing before this task (see project memory on bridge tool-count drift), confirm it is unchanged by this diff, not newly broken.

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/bridge/schema.go internal/bridge/schema_mode_test.go
git commit -m "feat: kg_search MCP 'mode' param + embedded node_types enum (IMP-005 FR-4)"
```

---

## Task 9: Go — `ListByProject` store method + `GET .../node-embeddings` endpoint

Back the backfill: a paginated, project-scoped read of embedding rows. No existing endpoint reuses this.

**Files:**
- Modify: `ennam.kg.go/internal/store/node_embedding.go`
- Modify: `ennam.kg.go/internal/handler/document.go`
- Test: `ennam.kg.go/internal/store/node_embedding_list_test.go` (create)

- [ ] **Step 1: Write the failing test (store method, DB-backed)**

Create `ennam.kg.go/internal/store/node_embedding_list_test.go`. Mirror the DB setup helper used by the existing embedding/store tests in this package (e.g. `newTestDB(t)` or equivalent — use whatever `node_embedding`-adjacent tests already use; do not invent a new harness):

```go
package store

import (
	"context"
	"testing"
)

func TestNodeEmbeddingStore_ListByProject(t *testing.T) {
	db := newTestDB(t) // reuse the existing store test DB helper
	s := NewNodeEmbeddingStore(db)
	ctx := context.Background()

	projectID, nodeID := seedProjectAndNode(t, db) // reuse existing seed helper
	if err := s.Upsert(ctx, NodeEmbeddingUpsert{
		ProjectID: projectID, NodeID: nodeID,
		ChunkText: "hello world", ContentHash: "h1",
		Embedding: make([]float32, 384),
	}); err != nil {
		t.Fatalf("seed upsert: %v", err)
	}

	rows, total, err := s.ListByProject(ctx, projectID, 10, 0)
	if err != nil {
		t.Fatalf("ListByProject: %v", err)
	}
	if total != 1 || len(rows) != 1 {
		t.Fatalf("want total=1 len=1, got total=%d len=%d", total, len(rows))
	}
	if rows[0].NodeID != nodeID || rows[0].ChunkText != "hello world" || rows[0].ContentHash != "h1" {
		t.Fatalf("unexpected row: %+v", rows[0])
	}
}
```

> If the store package has no shared DB helper, place this test under the same build tag / setup as the existing `search_test.go` DB-backed tests and copy their setup. If the package's store tests are fully mocked rather than DB-backed, instead assert the generated SQL via a `sqlmock` in the style already used in this package.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestNodeEmbeddingStore_ListByProject -v`
Expected: FAIL — `s.ListByProject undefined` and `NodeEmbeddingRow` undefined.

- [ ] **Step 3: Implement `ListByProject` + row type**

In `ennam.kg.go/internal/store/node_embedding.go`, add:

```go
// NodeEmbeddingRow is a lightweight projection for backfill paging.
type NodeEmbeddingRow struct {
	NodeID      string `json:"node_id"`
	ChunkText   string `json:"chunk_text"`
	ContentHash string `json:"content_hash"`
}

// ListByProject returns one page of embedding rows for a project plus the total count.
func (s *NodeEmbeddingStore) ListByProject(ctx context.Context, projectID string, limit, offset int) ([]NodeEmbeddingRow, int, error) {
	if limit <= 0 {
		limit = 100
	}
	if offset < 0 {
		offset = 0
	}

	var total int
	if err := s.db.QueryRowContext(ctx,
		`SELECT COUNT(*) FROM knowledge_node_embeddings WHERE project_id = $1`, projectID,
	).Scan(&total); err != nil {
		return nil, 0, fmt.Errorf("list node embeddings count: %w", err)
	}

	rows, err := s.db.QueryContext(ctx,
		`SELECT node_id, chunk_text, content_hash
		 FROM knowledge_node_embeddings
		 WHERE project_id = $1
		 ORDER BY node_id
		 LIMIT $2 OFFSET $3`, projectID, limit, offset)
	if err != nil {
		return nil, 0, fmt.Errorf("list node embeddings: %w", err)
	}
	defer rows.Close()

	out := make([]NodeEmbeddingRow, 0)
	for rows.Next() {
		var r NodeEmbeddingRow
		if err := rows.Scan(&r.NodeID, &r.ChunkText, &r.ContentHash); err != nil {
			return nil, 0, fmt.Errorf("scan node embedding row: %w", err)
		}
		out = append(out, r)
	}
	return out, total, rows.Err()
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestNodeEmbeddingStore_ListByProject -v`
Expected: PASS

- [ ] **Step 5: Add the HTTP endpoint**

In `ennam.kg.go/internal/handler/document.go`, register the route inside `RegisterRoutes` (next to the existing `node-embeddings/batch`):

```go
	mux.HandleFunc("GET /api/v1/projects/{id}/node-embeddings", h.ListNodeEmbeddings)
```

Add the handler method (mirror the parameter parsing + `errorResponse` style already used in this file):

```go
// ListNodeEmbeddings returns one page of a project's section embeddings for backfill.
func (h *DocumentHandler) ListNodeEmbeddings(w http.ResponseWriter, r *http.Request) {
	if h.nodeEmb == nil {
		errorResponse(w, http.StatusServiceUnavailable, "node embeddings not configured")
		return
	}
	projectID := r.PathValue("id")
	if projectID == "" {
		errorResponse(w, http.StatusBadRequest, "project id is required")
		return
	}
	limit := 100
	offset := 0
	if v := r.URL.Query().Get("limit"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			limit = n
		}
	}
	if v := r.URL.Query().Get("offset"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			offset = n
		}
	}
	items, total, err := h.nodeEmb.ListByProject(r.Context(), projectID, limit, offset)
	if err != nil {
		h.logger.Error("list node embeddings failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "list node embeddings failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"items": items, "total_count": total})
}
```

> `DocumentHandler` has a `logger *slog.Logger` field (verified) and the package's `writeJSON(w, status, v)` is reused here. Add `"strconv"` to the `document.go` import block if not already present.

- [ ] **Step 6: Run handler + store tests**

Run: `cd ennam.kg.go && go test ./internal/handler/ ./internal/store/ -race`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd ennam.kg.go
git add internal/store/node_embedding.go internal/store/node_embedding_list_test.go internal/handler/document.go
git commit -m "feat: project-scoped node-embeddings list endpoint for backfill (IMP-005 FR-3)"
```

---

## Task 10: Python — KGClient list method + re-embed admin endpoint

Add `list_node_embeddings` to the client, then an admin endpoint that re-encodes every embedding row for the given projects with the current (e5) model.

**Files:**
- Modify: `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py`
- Create: `ennam.kg.python/src/ennam_kg/api/admin.py`
- Modify: `ennam.kg.python/src/ennam_kg/main.py:60`
- Test: `ennam.kg.python/tests/test_api/test_reembed.py` (create)

- [ ] **Step 1: Add the client method**

In `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py`, add a method near `upsert_node_embeddings`:

```python
    async def list_node_embeddings(
        self, project_id: str, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        """List one page of a project's section embeddings (IMP-005 backfill)."""
        return await self._request(
            "GET",
            f"/api/v1/projects/{project_id}/node-embeddings",
            params={"limit": limit, "offset": offset},
        )
```

> Confirm `_request` accepts a `params=` kwarg (it wraps httpx). If it does not, pass the query string in the path: `f"/api/v1/projects/{project_id}/node-embeddings?limit={limit}&offset={offset}"`.

- [ ] **Step 2: Write the failing test**

Create `ennam.kg.python/tests/test_api/test_reembed.py`:

```python
"""IMP-005: re-embed admin endpoint re-encodes all rows for given projects."""
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from ennam_kg.main import app

client = TestClient(app)


@patch("ennam_kg.api.admin._build_kg_client")
@patch("ennam_kg.api.admin.LocalEmbeddingModel")
def test_reembed_reencodes_and_upserts(mock_model_cls, mock_build_client):
    # One page with two rows, then an empty page to stop.
    kg = AsyncMock()
    kg.list_node_embeddings.side_effect = [
        {"items": [
            {"node_id": "n1", "chunk_text": "alpha", "content_hash": "h1"},
            {"node_id": "n2", "chunk_text": "beta", "content_hash": "h2"},
        ], "total_count": 2},
        {"items": [], "total_count": 2},
    ]
    kg.upsert_node_embeddings.return_value = 2
    mock_build_client.return_value.__aenter__.return_value = kg

    model = mock_model_cls.return_value
    model.encode_passage.return_value = [[0.0] * 384, [0.0] * 384]

    resp = client.post(
        "/api/v1/admin/reembed",
        json={"project_ids": ["p1"]},
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200
    assert resp.json()["reembedded"] == 2
    model.encode_passage.assert_called_once_with(["alpha", "beta"])
    kg.upsert_node_embeddings.assert_awaited_once()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_api/test_reembed.py -v`
Expected: FAIL — `404` (route not registered) / import error for `ennam_kg.api.admin`.

- [ ] **Step 4: Implement the admin endpoint**

Create `ennam.kg.python/src/ennam_kg/api/admin.py`:

```python
"""IMP-005 FR-3: re-embed/backfill admin endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from ennam_kg.config import settings
from ennam_kg.embeddings.local_model import LocalEmbeddingModel

logger = logging.getLogger(__name__)

router = APIRouter()

_PAGE = 100


class ReembedRequest(BaseModel):
    project_ids: list[str]


class ReembedResponse(BaseModel):
    reembedded: int
    model: str


def _build_kg_client():
    """Construct an async KGClient context manager (kept indirect for test patching)."""
    from ennam_kg_indexer.kg_client.client import KGClient

    return KGClient(base_url=settings.embedding_service_url.replace(":8081", ":8080"))


@router.post("/api/v1/admin/reembed", response_model=ReembedResponse)
async def reembed(body: ReembedRequest, authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization header required")

    model = LocalEmbeddingModel(model_name=settings.embedding_model_name)
    total = 0

    async with _build_kg_client() as kg:
        for project_id in body.project_ids:
            offset = 0
            while True:
                page = await kg.list_node_embeddings(project_id, limit=_PAGE, offset=offset)
                items = page.get("items", [])
                if not items:
                    break
                vectors = model.encode_passage([it["chunk_text"] for it in items])
                upsert_items = [
                    {
                        "node_id": it["node_id"],
                        "chunk_text": it["chunk_text"],
                        "content_hash": it["content_hash"],  # preserved unchanged
                        "embedding": vec,
                    }
                    for it, vec in zip(items, vectors, strict=True)
                ]
                total += await kg.upsert_node_embeddings(project_id, upsert_items)
                offset += len(items)

    logger.info("reembed complete: %d rows, model=%s", total, model.model_name)
    return ReembedResponse(reembedded=total, model=model.model_name)
```

> Confirm `KGClient` is an async context manager and how it is normally constructed elsewhere (e.g. base URL + bearer token); reuse that construction. If KGClient needs an auth token, read it from `settings` the same way the worker does and pass it in `_build_kg_client`. The `.replace(":8081", ":8080")` is a pragmatic default to reach the Go API — replace with the canonical Go-API URL setting if one exists in `settings`.

- [ ] **Step 5: Register the router**

In `ennam.kg.python/src/ennam_kg/main.py`, add after the other `include_router` lines (~line 61):

```python
from ennam_kg.api import admin  # noqa: E402  (add to the existing api imports block)
app.include_router(admin.router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_api/test_reembed.py -v`
Expected: PASS (1 passed)

- [ ] **Step 7: Commit**

```bash
cd ennam.kg.python
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py src/ennam_kg/api/admin.py src/ennam_kg/main.py tests/test_api/test_reembed.py
git commit -m "feat: /api/v1/admin/reembed backfill endpoint + KGClient list method (IMP-005 FR-3)"
```

---

## Task 11: Retrieval eval harness (VI + EN, before/after)

A small standalone harness that scores `recall@5` / `MRR` per mode per language and tunes RRF `k`. It runs against a live stack (manual), so it is a script + fixture, not part of the unit suite.

**Files:**
- Create: `ennam.kg.python/tests/eval/retrieval_eval.py`
- Create: `ennam.kg.python/tests/eval/dataset.json`

- [ ] **Step 1: Create the dataset fixture**

Create `ennam.kg.python/tests/eval/dataset.json` (seed with ~6 here; expand to 20–30 from the real Cảng Định An ingested content before running for real — each `expected_node_id` must be a real `document_section` id in the target project):

```json
{
  "project_id": "REPLACE_WITH_REAL_PROJECT_ID",
  "pairs": [
    {"lang": "vi", "query": "rủi ro pháp lý", "expected_node_id": "REPLACE", "kind": "semantic_only"},
    {"lang": "vi", "query": "điều khoản thanh toán hợp đồng", "expected_node_id": "REPLACE", "kind": "lexical_only"},
    {"lang": "vi", "query": "tiến độ thi công cảng", "expected_node_id": "REPLACE", "kind": "paraphrase"},
    {"lang": "en", "query": "legal risk assessment", "expected_node_id": "REPLACE", "kind": "semantic_only"},
    {"lang": "en", "query": "contract payment terms", "expected_node_id": "REPLACE", "kind": "lexical_only"},
    {"lang": "en", "query": "port construction schedule", "expected_node_id": "REPLACE", "kind": "paraphrase"}
  ]
}
```

- [ ] **Step 2: Create the eval runner**

Create `ennam.kg.python/tests/eval/retrieval_eval.py`:

```python
"""IMP-005 FR-5: retrieval eval — recall@5 / MRR per mode per language.

Run against a LIVE stack:
    KG_API=http://localhost:8080 KG_TOKEN=<bearer> \
        uv run python tests/eval/retrieval_eval.py
Prints a table per mode (fulltext/semantic/hybrid) x language (vi/en).
"""
from __future__ import annotations

import json
import os
import pathlib

import httpx

API = os.environ.get("KG_API", "http://localhost:8080")
TOKEN = os.environ.get("KG_TOKEN", "")
MODES = ["fulltext", "semantic", "hybrid"]
TOP_K = 5

DATA = json.loads((pathlib.Path(__file__).parent / "dataset.json").read_text())


def _search(query: str, project_id: str, mode: str) -> list[str]:
    r = httpx.post(
        f"{API}/api/v1/search",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"query": query, "project_id": project_id, "mode": mode, "limit": TOP_K},
        timeout=30.0,
    )
    r.raise_for_status()
    return [row["id"] for row in r.json().get("results", [])]


def _score(pairs, project_id, mode):
    """Return (recall@5, MRR) over the given pairs."""
    hits = 0
    rr_sum = 0.0
    for p in pairs:
        ids = _search(p["query"], project_id, mode)
        if p["expected_node_id"] in ids:
            hits += 1
            rr_sum += 1.0 / (ids.index(p["expected_node_id"]) + 1)
    n = len(pairs) or 1
    return hits / n, rr_sum / n


def main():
    project_id = DATA["project_id"]
    print(f"{'mode':<10}{'lang':<6}{'recall@5':<12}{'MRR':<8}")
    for mode in MODES:
        for lang in ("vi", "en"):
            pairs = [p for p in DATA["pairs"] if p["lang"] == lang]
            recall, mrr = _score(pairs, project_id, mode)
            print(f"{mode:<10}{lang:<6}{recall:<12.3f}{mrr:<8.3f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke-check the runner parses (no live stack needed)**

Run: `cd ennam.kg.python && uv run python -c "import ast,pathlib; ast.parse(pathlib.Path('tests/eval/retrieval_eval.py').read_text()); print('ok')"`
Expected: prints `ok` (syntax valid). Full run requires a live stack + real node ids.

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.python
git add tests/eval/retrieval_eval.py tests/eval/dataset.json
git commit -m "feat: retrieval eval harness (recall@5/MRR, VI+EN, per mode) (IMP-005 FR-5)"
```

---

## Final Verification

- [ ] **Go: full suite with race detector**

Run: `cd ennam.kg.go && make test`
Expected: PASS (pre-existing failures noted in project memory — bridge tool-count drift — must be unchanged, not newly introduced by this work).

- [ ] **Go: lint**

Run: `cd ennam.kg.go && make lint`
Expected: clean (gofmt/goimports applied; no new lint findings).

- [ ] **Python: full unit suite**

Run: `cd ennam.kg.python && uv run pytest`
Expected: PASS (all new tests + no regression).

- [ ] **Python: lint/format**

Run: `cd ennam.kg.python && uv run ruff check src/ tests/`
Expected: clean.

- [ ] **Manual cutover rehearsal (staging, per BR-007)**
  1. Pause ingest (or set `ingestion.auto_queue_processing=false`).
  2. `POST /api/v1/admin/reembed {"project_ids": [...]}` → returns `{reembedded: N, model: "intfloat/multilingual-e5-small"}`.
  3. Confirm e5 is the query model (it already reads `embedding_model_name`); resume ingest.
  4. Run `tests/eval/retrieval_eval.py` (with real node ids) before/after; confirm **recall@5 (VI) > all-MiniLM baseline** and **no EN regression**; record the chosen RRF `k`.

---

## Spec Coverage Check

| Spec item | Task |
|-----------|------|
| FR-1 Hybrid RRF (fusion math) | Task 5 |
| FR-1 mode normalization + back-compat (BR-001/002) | Task 6 |
| FR-1 hybrid branch, concurrency, fail-soft (BR-003/004, D5) | Task 7 |
| FR-1 candidate scope = embedded set (D1) | Task 7 (`hybridEmbeddedNodeTypes`) |
| FR-2 multilingual model (D4, BR-006) | Task 4 |
| FR-2 prefix parity helper (BR-005) | Tasks 1–3 |
| FR-3 re-embed/backfill (D3, BR-007) | Tasks 9 (read) + 10 (job) |
| FR-4 MCP `mode` param, tool count unchanged | Task 8 |
| FR-5 retrieval eval (BR-009) | Task 11 |
| BR-006 384-dim, no migration | Task 4 (assert) + no migration anywhere |
| BR-008 no new extension | Nothing adds an extension (HNSW index already exists) |
| Out-of-scope: BA-020 1536-dim untouched | No task touches `embedding_generator.go` / `EmbeddingStore` |
