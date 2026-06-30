# DAAB Exact-Name Hub Merge (1b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge corpus-wide exact-name duplicate entity nodes that are genuinely the same specific entity (creating cross-document links), gated by a genericness discriminator that never silently merges generic terms.

**Architecture:** Python owns the corpus-global name scan, the discriminator (deterministic buckets + one-shot LLM for the ambiguous residual), the per-name classification artifact, and the producer-side genericness guard (where `_normalize` lives). Go owns the artifact table/store, an upsert/read endpoint, and `ApplyHubNameMerges` (reuses the existing reversible pairwise merge). 1b candidates use a DISTINCT reason string so the worker's auto-apply never touches them.

**Tech Stack:** Python 3.12 (`ennam.kg.python`: resolution/, AIClient, argparse CLI), Go (`ennam.kg.go`: `database/sql`, golang-migrate). Tests: `pytest` (Python), `go test` (Go, `-tags=integration` for DB).

**Design spec:** `docs/superpowers/specs/2026-06-30-daab-exact-name-hub-merge-design.md`

## Global Constraints

- Nested repos — run `git`/`go`/`make` from `ennam.kg.go`, `uv run`/`pytest` from `ennam.kg.python`. Both under `/Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace`.
- Go integration tests: store tests read `KG_TEST_DATABASE_URL`, handler tests read `KG_TEST_DSN`; dev DB is **:5433** — export BOTH to `postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable`.
- Migration head is `000073`; new pair is `000074`.
- **Reuse, do not rewrite:** `_normalize` (`ennam.kg.python/.../resolution/rules.py:42`), `merge.go`/`unmerge.go`, `processSuggestion` (`ennam.kg.go/internal/service/apply_suggestions.go:129`), `MergeSuggestionStore.Insert` (`merge_suggestion.go:37`), `KGClient.create_merge_suggestion`, `AIClient` (`ennam.kg.python/.../ai_client/client.py`).
- **Footgun:** never tag 1b candidates `reason='exact normalized name match'` (worker auto-applies that, gate-bypassed). Use `reason='exact-name hub merge candidate'`.
- **Fail-safe discriminator:** only `class='specific'` is mergeable; `generic`/`uncertain`/absent → never auto-merge.
- **Precision measured on the real proposed population** — never cite the G2 1.000 curated number.
- Counts here are point-in-time (corpus grows); the jobs re-scan live.

---

## Phase 1 — Classification artifact (Go)

### Task 1: Migration — `entity_name_classification`

**Files:**
- Create: `ennam.kg.go/db/migrations/000074_entity_name_classification.up.sql`
- Create: `ennam.kg.go/db/migrations/000074_entity_name_classification.down.sql`

**Interfaces:**
- Produces table `entity_name_classification(project_id, normalized_name, class, source, rationale, reviewed_by, created_at, updated_at)`, PK `(project_id, normalized_name)`.

- [ ] **Step 1: Write the up migration**

`000074_entity_name_classification.up.sql`:
```sql
-- Per-name genericness classification for exact-name hub merge (1b).
-- See docs/superpowers/specs/2026-06-30-daab-exact-name-hub-merge-design.md
CREATE TABLE IF NOT EXISTS entity_name_classification (
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    normalized_name TEXT NOT NULL,
    class           TEXT NOT NULL CHECK (class IN ('specific','generic','uncertain')),
    source          TEXT NOT NULL CHECK (source IN ('rule','llm','human')),
    rationale       TEXT NOT NULL DEFAULT '',
    reviewed_by     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, normalized_name)
);
```

- [ ] **Step 2: Write the down migration**

`000074_entity_name_classification.down.sql`:
```sql
DROP TABLE IF EXISTS entity_name_classification;
```

- [ ] **Step 3: Apply + verify**

Run: `cd ennam.kg.go && make db-migrate && make db-migrate-version`
Expected: `74`. `make db-shell` → `\d entity_name_classification` shows the table + PK.

- [ ] **Step 4: Verify reversibility**

Run: `make db-migrate-down && make db-migrate && make db-migrate-version` → ends at `74`.

- [ ] **Step 5: Commit**

```bash
git add db/migrations/000074_entity_name_classification.up.sql db/migrations/000074_entity_name_classification.down.sql
git commit -m "feat(daab): entity_name_classification table for exact-name hub merge"
```

---

### Task 2: Go store — `EntityNameClassificationStore`

**Files:**
- Create: `ennam.kg.go/internal/store/entity_name_classification.go`
- Test: `ennam.kg.go/internal/store/entity_name_classification_test.go` (integration)

**Interfaces:**
- Produces:
  - `type NameClassification struct { ProjectID, NormalizedName, Class, Source, Rationale string; ReviewedBy *string }`
  - `func NewEntityNameClassificationStore(db *sql.DB) *EntityNameClassificationStore`
  - `Upsert(ctx, NameClassification) error` — `human` source never overwritten by `rule`/`llm`.
  - `Get(ctx, projectID, normalizedName) (*NameClassification, error)` — nil if absent.
  - `ListByProject(ctx, projectID) ([]NameClassification, error)`

- [ ] **Step 1: Write the failing integration test**

Create `entity_name_classification_test.go`:
```go
//go:build integration

package store_test

import (
	"context"
	"testing"

	"github.com/ennam/ennam-kg/internal/store"
)

func TestEntityNameClassification_UpsertAndHumanPrecedence(t *testing.T) {
	db := setupTestDB(t)
	acSeedProject(t, db) // reuses helper; seeds project acProj
	s := store.NewEntityNameClassificationStore(db)
	ctx := context.Background()

	must := func(c store.NameClassification) {
		if err := s.Upsert(ctx, c); err != nil {
			t.Fatalf("upsert %q: %v", c.NormalizedName, err)
		}
	}
	must(store.NameClassification{ProjectID: acProj, NormalizedName: "dự án", Class: "generic", Source: "llm", Rationale: "common noun"})
	got, err := s.Get(ctx, acProj, "dự án")
	if err != nil || got == nil || got.Class != "generic" {
		t.Fatalf("get: %+v err=%v", got, err)
	}
	// human override wins and is NOT overwritten by a later llm upsert
	rev := "reviewer-1"
	must(store.NameClassification{ProjectID: acProj, NormalizedName: "dự án", Class: "specific", Source: "human", Rationale: "manually confirmed", ReviewedBy: &rev})
	must(store.NameClassification{ProjectID: acProj, NormalizedName: "dự án", Class: "generic", Source: "llm", Rationale: "re-run"})
	got, _ = s.Get(ctx, acProj, "dự án")
	if got.Class != "specific" || got.Source != "human" {
		t.Errorf("human classification must not be overwritten by llm: got %+v", got)
	}
}
```

- [ ] **Step 2: Run → fail**

Run: `export KG_TEST_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable"; go test -tags=integration ./internal/store/ -run TestEntityNameClassification -v`
Expected: FAIL (undefined).

- [ ] **Step 3: Implement the store**

Create `entity_name_classification.go`:
```go
package store

import (
	"context"
	"database/sql"
	"fmt"
)

// NameClassification is one per-name genericness classification row.
type NameClassification struct {
	ProjectID      string
	NormalizedName string
	Class          string // specific | generic | uncertain
	Source         string // rule | llm | human
	Rationale      string
	ReviewedBy     *string
}

// EntityNameClassificationStore manages the entity_name_classification table.
type EntityNameClassificationStore struct{ db *sql.DB }

func NewEntityNameClassificationStore(db *sql.DB) *EntityNameClassificationStore {
	return &EntityNameClassificationStore{db: db}
}

// Upsert writes a classification. A 'human' row is authoritative: rule/llm
// upserts never overwrite an existing human classification.
func (s *EntityNameClassificationStore) Upsert(ctx context.Context, c NameClassification) error {
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO entity_name_classification
			(project_id, normalized_name, class, source, rationale, reviewed_by, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6, now())
		ON CONFLICT (project_id, normalized_name) DO UPDATE SET
			class       = EXCLUDED.class,
			source      = EXCLUDED.source,
			rationale   = EXCLUDED.rationale,
			reviewed_by = EXCLUDED.reviewed_by,
			updated_at  = now()
		WHERE entity_name_classification.source <> 'human'`,
		c.ProjectID, c.NormalizedName, c.Class, c.Source, c.Rationale, c.ReviewedBy,
	)
	if err != nil {
		return fmt.Errorf("upsert name classification %q: %w", c.NormalizedName, err)
	}
	return nil
}

// Get returns the classification for a name, or nil if absent.
func (s *EntityNameClassificationStore) Get(ctx context.Context, projectID, normalizedName string) (*NameClassification, error) {
	var c NameClassification
	err := s.db.QueryRowContext(ctx, `
		SELECT project_id, normalized_name, class, source, rationale, reviewed_by
		FROM entity_name_classification WHERE project_id=$1 AND normalized_name=$2`,
		projectID, normalizedName,
	).Scan(&c.ProjectID, &c.NormalizedName, &c.Class, &c.Source, &c.Rationale, &c.ReviewedBy)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("get name classification: %w", err)
	}
	return &c, nil
}

// ListByProject returns all classifications for a project.
func (s *EntityNameClassificationStore) ListByProject(ctx context.Context, projectID string) ([]NameClassification, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT project_id, normalized_name, class, source, rationale, reviewed_by
		FROM entity_name_classification WHERE project_id=$1`, projectID)
	if err != nil {
		return nil, fmt.Errorf("list name classifications: %w", err)
	}
	defer rows.Close()
	var out []NameClassification
	for rows.Next() {
		var c NameClassification
		if err := rows.Scan(&c.ProjectID, &c.NormalizedName, &c.Class, &c.Source, &c.Rationale, &c.ReviewedBy); err != nil {
			return nil, fmt.Errorf("scan name classification: %w", err)
		}
		out = append(out, c)
	}
	return out, rows.Err()
}
```

- [ ] **Step 4: Run → pass**

Run: `go test -tags=integration ./internal/store/ -run TestEntityNameClassification -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/store/entity_name_classification.go internal/store/entity_name_classification_test.go
git commit -m "feat(daab): EntityNameClassificationStore (human-precedence upsert)"
```

---

### Task 3: Go endpoint — upsert/read classifications

Python writes the artifact and reads it (producer guard) via HTTP, mirroring the existing producer/apply split.

**Files:**
- Create: `ennam.kg.go/internal/handler/name_classification.go`
- Test: `ennam.kg.go/internal/handler/name_classification_test.go`
- Modify: `ennam.kg.go/cmd/kg-server/main.go` (construct + register)

**Interfaces:**
- Produces: `POST /api/v1/internal/resolution/name-classification` (batch upsert `{project_id, items:[{normalized_name,class,source,rationale,reviewed_by}]}`) and `GET /api/v1/internal/resolution/name-classification?project_id=` (list).

- [ ] **Step 1: Write the failing unit test**

Create `name_classification_test.go` (mirror an existing internal-handler test that uses a fake store; assert a batch upsert calls the store per item and a GET returns the list). Use a `fakeNameClassStore` implementing the handler's store interface:
```go
package handler

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"log/slog"

	"github.com/ennam/ennam-kg/internal/store"
)

type fakeNameClassStore struct{ upserts []store.NameClassification }

func (f *fakeNameClassStore) Upsert(_ context.Context, c store.NameClassification) error {
	f.upserts = append(f.upserts, c)
	return nil
}
func (f *fakeNameClassStore) ListByProject(_ context.Context, _ string) ([]store.NameClassification, error) {
	return f.upserts, nil
}

func TestNameClassification_BatchUpsert(t *testing.T) {
	fs := &fakeNameClassStore{}
	h := NewNameClassificationHandler(fs, slog.Default())
	body := `{"project_id":"p1","items":[{"normalized_name":"dự án","class":"generic","source":"llm","rationale":"x"},{"normalized_name":"ubnd tỉnh trà vinh","class":"specific","source":"rule","rationale":"org marker"}]}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/internal/resolution/name-classification", bytes.NewReader([]byte(body)))
	w := httptest.NewRecorder()
	h.HandleUpsert(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d: %s", w.Code, w.Body.String())
	}
	if len(fs.upserts) != 2 || fs.upserts[0].ProjectID != "p1" || fs.upserts[0].Class != "generic" {
		t.Errorf("upserts not wired: %+v", fs.upserts)
	}
}
```

- [ ] **Step 2: Run → fail**

Run: `go test ./internal/handler/ -run TestNameClassification -v` → FAIL (undefined).

- [ ] **Step 3: Implement the handler**

Create `name_classification.go`:
```go
package handler

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/ennam/ennam-kg/internal/store"
)

type nameClassStore interface {
	Upsert(ctx context.Context, c store.NameClassification) error
	ListByProject(ctx context.Context, projectID string) ([]store.NameClassification, error)
}

// NameClassificationHandler serves the per-name genericness artifact (1b).
type NameClassificationHandler struct {
	store  nameClassStore
	logger *slog.Logger
}

func NewNameClassificationHandler(s nameClassStore, logger *slog.Logger) *NameClassificationHandler {
	return &NameClassificationHandler{store: s, logger: logger}
}

func (h *NameClassificationHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/internal/resolution/name-classification", h.HandleUpsert)
	mux.HandleFunc("GET /api/v1/internal/resolution/name-classification", h.HandleList)
}

type nameClassItem struct {
	NormalizedName string  `json:"normalized_name"`
	Class          string  `json:"class"`
	Source         string  `json:"source"`
	Rationale      string  `json:"rationale"`
	ReviewedBy     *string `json:"reviewed_by"`
}

func (h *NameClassificationHandler) HandleUpsert(w http.ResponseWriter, r *http.Request) {
	var body struct {
		ProjectID string          `json:"project_id"`
		Items     []nameClassItem `json:"items"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.ProjectID == "" {
		errorResponse(w, http.StatusBadRequest, "invalid body or missing project_id")
		return
	}
	var n int
	for _, it := range body.Items {
		if err := h.store.Upsert(r.Context(), store.NameClassification{
			ProjectID: body.ProjectID, NormalizedName: it.NormalizedName, Class: it.Class,
			Source: it.Source, Rationale: it.Rationale, ReviewedBy: it.ReviewedBy,
		}); err != nil {
			h.logger.ErrorContext(r.Context(), "name-classification upsert failed", "error", err, "name", it.NormalizedName)
			errorResponse(w, http.StatusInternalServerError, "upsert failed")
			return
		}
		n++
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"upserted": n})
}

func (h *NameClassificationHandler) HandleList(w http.ResponseWriter, r *http.Request) {
	pid := r.URL.Query().Get("project_id")
	if pid == "" {
		errorResponse(w, http.StatusBadRequest, "project_id is required")
		return
	}
	items, err := h.store.ListByProject(r.Context(), pid)
	if err != nil {
		errorResponse(w, http.StatusInternalServerError, "list failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"items": items})
}
```

- [ ] **Step 4: Run → pass; wire into main.go**

Run: `go test ./internal/handler/ -run TestNameClassification -v` → PASS.
Then in `cmd/kg-server/main.go`, near the other internal-resolution handler registrations (where `apply_suggestions`/`merge_suggestion` handlers are registered), add:
```go
	nameClassHandler := handler.NewNameClassificationHandler(store.NewEntityNameClassificationStore(db), logger)
	nameClassHandler.RegisterRoutes(apiMux)
```

- [ ] **Step 5: Build + commit**

```bash
go build ./... && go test ./internal/handler/ -run TestNameClassification
git add internal/handler/name_classification.go internal/handler/name_classification_test.go cmd/kg-server/main.go
git commit -m "feat(daab): name-classification upsert/list endpoint"
```

---

## Phase 2 — Discriminator (Python)

### Task 4: Deterministic bucket rules (pure, unit-tested)

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/resolution/name_class.py`
- Test: `ennam.kg.python/tests/resolution/test_name_class.py`

**Interfaces:**
- Produces: `classify_name_deterministic(normalized_name: str) -> str | None` → `'specific'` (org marker), `'generic'` (bare-geo or short-generic), or `None` (residual → LLM).

- [ ] **Step 1: Write failing tests**

Create `tests/resolution/test_name_class.py`:
```python
from ennam_kg.resolution.name_class import classify_name_deterministic

def test_org_marker_is_specific():
    for n in ["ubnd tỉnh trà vinh", "công ty tnhh xây dựng hàm giang",
              "ban quản lý khu kinh tế trà vinh", "sở giao thông vận tải"]:
        assert classify_name_deterministic(n) == "specific", n

def test_bare_geo_is_generic():
    assert classify_name_deterministic("tỉnh trà vinh") == "generic"
    assert classify_name_deterministic("huyện duyên hải") == "generic"

def test_short_single_token_generic():
    assert classify_name_deterministic("đầu tư") is None or classify_name_deterministic("vốn") == "generic"
    assert classify_name_deterministic("vốn") == "generic"  # <=12 chars, single token

def test_residual_returns_none():
    for n in ["dự án khu bến tổng hợp định an", "dự án", "pháp luật", "thủ tướng chính phủ"]:
        assert classify_name_deterministic(n) is None, n
```

- [ ] **Step 2: Run → fail**

Run: `cd ennam.kg.python && uv run pytest tests/resolution/test_name_class.py -v` → FAIL (no module).

- [ ] **Step 3: Implement**

Create `src/ennam_kg/resolution/name_class.py`:
```python
"""Deterministic genericness buckets for exact-name hub merge (1b).
Pairs with the one-shot LLM classifier for the residual (None) names.
"""
import re

# Org/legal markers → a specific named entity (marker precedence over geo).
_ORG_MARKERS = re.compile(
    r"(công ty|tổng công ty|tập đoàn|ngân hàng|hợp tác xã|doanh nghiệp|chi nhánh|"
    r"ủy ban nhân dân|ubnd|hđnd|hội đồng nhân dân|ban quản lý|ban chỉ đạo|"
    r"\bsở |\bbộ |\bcục |tổng cục|chi cục|\bphòng |trung tâm|\bviện |trường|đại học|"
    r"bệnh viện|kho bạc)"
)
# Bare geographic lead (no org marker) → generic partial-place reference.
_BARE_GEO = re.compile(r"^(tỉnh|thành phố|tp\.?|huyện|xã|phường|thị xã|thị trấn|ấp|khóm|quận)\b")


def classify_name_deterministic(normalized_name: str) -> str | None:
    """Return 'specific' / 'generic' / None (residual → defer to LLM)."""
    nm = normalized_name.strip()
    if not nm:
        return "generic"
    if _ORG_MARKERS.search(nm):          # marker precedence: wins even with a geo token
        return "specific"
    if _BARE_GEO.search(nm):
        return "generic"
    if len(nm) <= 12 and " " not in nm:  # short single token → generic
        return "generic"
    return None                           # residual: ambiguous → LLM
```
(Adjust the test for `đầu tư` — it is two tokens / >... actually "đầu tư" is 6 chars but has a space → residual `None`. Fix the test to assert `classify_name_deterministic("đầu tư") is None` and `classify_name_deterministic("vốn") == "generic"`.)

- [ ] **Step 4: Fix the test's `đầu tư` case + run → pass**

Update the `test_short_single_token_generic` case to:
```python
def test_short_single_token_generic():
    assert classify_name_deterministic("vốn") == "generic"      # single token, <=12
    assert classify_name_deterministic("đầu tư") is None        # has a space → residual
```
Run: `uv run pytest tests/resolution/test_name_class.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/resolution/name_class.py tests/resolution/test_name_class.py
git commit -m "feat(daab): deterministic genericness buckets for hub merge (1b)"
```

---

### Task 5: LLM classification of residual names

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/resolution/name_class.py` (add `classify_names_llm`)
- Test: `ennam.kg.python/tests/resolution/test_name_class_llm.py`

**Interfaces:**
- Consumes: an injected **`llm_json(prompt: str) -> dict`** callable (decouples from the async `AIClient`; the CLI in Task 6 wraps `AIClient.complete_json` via `asyncio.run`). `AIClient.complete_json` is **async** and returns a parsed `dict` (verified: `ai_client/client.py:67`).
- Produces: `classify_names_llm(names: list[str], llm_json, doc_freq: dict[str,int]) -> dict[str, tuple[str,str]]` → `{name: (class, rationale)}`, class in `{specific, generic, uncertain}`. Cross-check downgrade: LLM `specific` + short (≤12) + high `doc_freq` (≥15) → `uncertain`.

- [ ] **Step 1: Write failing test (fake llm_json)**

Create `tests/resolution/test_name_class_llm.py`:
```python
from ennam_kg.resolution.name_class import classify_names_llm

def make_llm(mapping):
    # complete_json returns a parsed dict; we model {"results":[{name,class,rationale}]}
    def llm_json(prompt: str) -> dict:
        names = [n for n in mapping if n in prompt]
        return {"results": [{"name": n, "class": mapping[n], "rationale": "x"} for n in names]}
    return llm_json

def test_llm_classifies_and_downgrades_high_docfreq():
    names = ["dự án khu bến tổng hợp định an", "dự án"]
    llm = make_llm({"dự án khu bến tổng hợp định an": "specific", "dự án": "specific"})
    # "dự án" is short AND high doc-frequency → downgrade specific→uncertain
    out = classify_names_llm(names, llm, doc_freq={"dự án": 40, "dự án khu bến tổng hợp định an": 31})
    assert out["dự án khu bến tổng hợp định an"][0] == "specific"
    assert out["dự án"][0] == "uncertain"  # downgraded
```

- [ ] **Step 2: Run → fail**

Run: `uv run pytest tests/resolution/test_name_class_llm.py -v` → FAIL.

- [ ] **Step 3: Implement `classify_names_llm`**

Append to `name_class.py`:
```python
# A short name with high corpus document-frequency is the generic signature.
_DOWNGRADE_MAX_LEN = 12
_DOWNGRADE_MIN_DOCFREQ = 15

_SYSTEM = (
    "Bạn phân loại các cụm từ tiếng Việt trích từ tài liệu pháp lý/dự án. "
    "Với mỗi tên: 'specific' nếu là MỘT thực thể có tên riêng cụ thể (tổ chức, địa danh, "
    "người, dự án, hoặc tài liệu cụ thể theo tên đầy đủ) — an toàn coi là CÙNG một thực thể "
    "khi xuất hiện ở nhiều tài liệu; 'generic' nếu là danh từ chung / loại / vai trò / "
    "tham chiếu pháp lý (vd 'điều 3', 'khoản 2', 'dự án', 'pháp luật', 'giám đốc') lặp lại "
    "y hệt ở nhiều tài liệu KHÔNG liên quan. "
    "Chỉ trả về JSON object: {\"results\":[{\"name\":..., \"class\":\"specific|generic\", \"rationale\":...}]}."
)

def _build_prompt(names: list[str]) -> str:
    joined = "\n".join(f"- {n}" for n in names)
    return _SYSTEM + "\n\nDanh sách tên:\n" + joined

def classify_names_llm(names: list[str], llm_json, doc_freq: dict[str, int]) -> dict[str, tuple[str, str]]:
    """One-shot LLM classification of residual names, with a deterministic downgrade.

    llm_json(prompt) -> dict — returns the parsed JSON (e.g. AIClient.complete_json,
    which is async; the CLI wraps it via asyncio.run). Chunk `names` if very large.
    """
    if not names:
        return {}
    parsed = llm_json(_build_prompt(names))
    by_name = {row["name"]: row for row in parsed.get("results", [])}
    out: dict[str, tuple[str, str]] = {}
    for n in names:
        row = by_name.get(n, {"class": "uncertain", "rationale": "missing from LLM output"})
        cls, rat = row.get("class", "uncertain"), row.get("rationale", "")
        if cls == "specific" and len(n) <= _DOWNGRADE_MAX_LEN and doc_freq.get(n, 0) >= _DOWNGRADE_MIN_DOCFREQ:
            cls, rat = "uncertain", (rat + " | downgraded: short + high doc-freq")
        out[n] = (cls, rat)
    return out
```

- [ ] **Step 4: Run → pass**

Run: `uv run pytest tests/resolution/test_name_class_llm.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ennam_kg/resolution/name_class.py tests/resolution/test_name_class_llm.py
git commit -m "feat(daab): one-shot LLM classifier for residual entity names (1b)"
```

---

## Phase 3 — Corpus scan + artifact (Python CLI)

### Task 6: `classify_corpus_names` CLI

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/resolution/classify_corpus_cli.py`
- Test: `ennam.kg.python/tests/resolution/test_classify_corpus.py` (logic unit test with injected deps)

**Interfaces:**
- Consumes: `_normalize` (rules.py), `classify_name_deterministic` + `classify_names_llm` (Tasks 4-5), DB read of concept nodes, the Go name-classification endpoint.
- Produces: a `classify_corpus(project_id, concepts, ai_client, writer) -> list[NameClass]` core function + a `main()` CLI (`python -m ennam_kg.resolution.classify_corpus_cli --project <uuid>`).

- [ ] **Step 1: Write the failing logic test**

Create `tests/resolution/test_classify_corpus.py` — test the pure core `classify_corpus(concepts, ai_client)` (no DB/HTTP): given concept rows (name, doc_freq), it groups by `_normalize`, keeps groups>1, applies deterministic buckets, routes residual to the (fake) LLM, and returns one classification per normalized name with the right `source` (`rule` vs `llm`).
```python
from ennam_kg.resolution.classify_corpus_cli import classify_corpus

def fake_llm_json(prompt: str) -> dict:
    # classify any name containing "dự án"/"pháp luật" exactly as generic, else specific
    import re
    names = [line[2:] for line in prompt.splitlines() if line.startswith("- ")]
    def cls(n): return "generic" if n in ("dự án", "pháp luật") else "specific"
    return {"results": [{"name": n, "class": cls(n), "rationale": "x"} for n in names]}

def test_classify_corpus_groups_and_routes():
    # (raw_name, doc_freq); duplicate groups
    concepts = [
        ("ubnd tỉnh trà vinh", 65), ("dự án", 40), ("pháp luật", 32),
        ("dự án khu bến tổng hợp định an", 31), ("tỉnh trà vinh", 34),
    ]
    out = {c.normalized_name: c for c in classify_corpus(concepts, fake_llm_json)}
    assert out["ubnd tỉnh trà vinh"].cls == "specific" and out["ubnd tỉnh trà vinh"].source == "rule"
    assert out["tỉnh trà vinh"].cls == "generic" and out["tỉnh trà vinh"].source == "rule"
    assert out["dự án"].cls == "generic" and out["dự án"].source == "llm"
    assert out["dự án khu bến tổng hợp định an"].cls == "specific" and out["dự án khu bến tổng hợp định an"].source == "llm"
```

- [ ] **Step 2: Run → fail**

Run: `uv run pytest tests/resolution/test_classify_corpus.py -v` → FAIL.

- [ ] **Step 3: Implement core + CLI**

Create `classify_corpus_cli.py`:
```python
"""Corpus-global exact-name classification job (1b).

Scans concept nodes, groups by _normalize(name), classifies each duplicate
group's name (deterministic buckets + one-shot LLM for the residual), and
upserts the classifications to the entity_name_classification artifact.
"""
from __future__ import annotations
import argparse
import os
from dataclasses import dataclass

from ennam_kg.resolution.rules import _normalize
from ennam_kg.resolution.name_class import classify_name_deterministic, classify_names_llm


@dataclass
class NameClass:
    normalized_name: str
    cls: str       # specific | generic | uncertain
    source: str    # rule | llm
    rationale: str


def classify_corpus(concepts: list[tuple[str, int]], llm_json) -> list[NameClass]:
    """concepts = [(raw_name, doc_freq)]. llm_json(prompt)->dict. One NameClass per group name."""
    groups: dict[str, int] = {}
    for raw, freq in concepts:
        nm = _normalize(raw)
        groups[nm] = groups.get(nm, 0) + freq
    out: list[NameClass] = []
    residual: list[str] = []
    for nm in groups:
        det = classify_name_deterministic(nm)
        if det is not None:
            out.append(NameClass(nm, det, "rule", "deterministic bucket"))
        else:
            residual.append(nm)
    if residual:
        llm = classify_names_llm(residual, llm_json, doc_freq=groups)
        for nm in residual:
            cls, rat = llm.get(nm, ("uncertain", "missing"))
            out.append(NameClass(nm, cls, "llm", rat))
    return out


def _load_concepts(project_id: str) -> list[tuple[str, int]]:
    """Read duplicate concept names + their distinct-document frequency from the DB."""
    import psycopg
    dsn = os.environ["KG_DATABASE_URL"]
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH dup AS (
              SELECT lower(btrim(title)) AS nm
              FROM knowledge_nodes WHERE node_type='concept' AND project_id=%s
              GROUP BY 1 HAVING count(*)>1)
            SELECT n.title,
                   (SELECT count(DISTINCT e.source_id) FROM knowledge_edges e
                    WHERE e.target_id=n.id AND e.edge_type='mentions') AS df
            FROM knowledge_nodes n
            JOIN dup ON dup.nm = lower(btrim(n.title))
            WHERE n.node_type='concept' AND n.project_id=%s
            """,
            (project_id, project_id),
        )
        return [(row[0], int(row[1] or 0)) for row in cur.fetchall()]


def _upsert(project_id: str, items: list[NameClass]) -> None:
    import httpx
    base = os.environ.get("KG_API_URL", "http://localhost:8082")
    key = os.environ.get("KG_API_KEY", "")
    payload = {"project_id": project_id, "items": [
        {"normalized_name": c.normalized_name, "class": c.cls, "source": c.source, "rationale": c.rationale}
        for c in items]}
    r = httpx.post(f"{base}/api/v1/internal/resolution/name-classification",
                   json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=60)
    r.raise_for_status()


def main() -> None:
    p = argparse.ArgumentParser(description="Classify corpus entity names for exact-name hub merge")
    p.add_argument("--project", required=True)
    p.add_argument("--dry-run", action="store_true", help="print classifications, do not upsert")
    args = p.parse_args()
    import asyncio
    from ennam_kg.ai_client.client import AIClient
    ai = AIClient(os.environ.get("KG_API_URL", "http://localhost:8082"), os.environ.get("KG_API_KEY", ""))
    # AIClient.complete_json is async + returns a parsed dict; wrap it as a sync llm_json.
    def llm_json(prompt: str) -> dict:
        return asyncio.run(ai.complete_json(prompt))
    items = classify_corpus(_load_concepts(args.project), llm_json)
    by_class: dict[str, int] = {}
    for c in items:
        by_class[c.cls] = by_class.get(c.cls, 0) + 1
    print(f"classified {len(items)} names: {by_class}")
    if not args.dry_run:
        _upsert(args.project, items)
        print("upserted to entity_name_classification")


if __name__ == "__main__":
    main()
```
(Confirm `KG_DATABASE_URL` is the env the Python side already uses for direct DB reads — check `worker.py`/settings; if it differs, use the existing settings accessor. Confirm `AIClient` constructor + `complete` shape and adapt `classify_names_llm`'s request accordingly.)

- [ ] **Step 4: Run → pass**

Run: `uv run pytest tests/resolution/test_classify_corpus.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ennam_kg/resolution/classify_corpus_cli.py tests/resolution/test_classify_corpus.py
git commit -m "feat(daab): classify_corpus_names CLI (scan + bucket + LLM + upsert)"
```

---

## Phase 4 — Producer guard (Python)

### Task 7: Genericness guard in `rules.py`

Stop the existing exact-name path from emitting auto-mergeable suggestions for generic names (closes the footgun at the source).

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/resolution/rules.py` (`rule_based_decision`)
- Test: `ennam.kg.python/tests/resolution/test_rules_guard.py`

**Interfaces (verified against `rules.py`):**
- `RuleResult(action, confidence, reason)`, `action ∈ {merge, reject, defer}` (no `needs_review` — `defer` passes the pair to the cross-encoder/LLM stage).
- Signature is `rule_based_decision(entity, candidate, sim, rule_sim_high) -> RuleResult` (pass2.py:110). Add an optional 5th param `name_class_lookup=None` (default ⇒ legacy behavior).
- Guard at the exact-name branch (rules.py:99-100): `generic` ⇒ `reject` (drop, never merge); `uncertain`/absent ⇒ `defer` (let the cross-encoder/LLM verify); `specific` ⇒ the existing `merge`.

- [ ] **Step 1: Write the failing test**

Create `tests/resolution/test_rules_guard.py` (sim high enough to clear the floor and reach the exact-name branch):
```python
from ennam_kg.resolution.rules import rule_based_decision

def _pair(name):
    return {"name": name}, {"name": name}

def test_generic_exact_name_rejects():
    a, b = _pair("dự án")
    res = rule_based_decision(a, b, 1.0, 0.95, name_class_lookup=lambda nm: "generic")
    assert res.action == "reject"

def test_uncertain_defers():
    a, b = _pair("đầu tư")
    res = rule_based_decision(a, b, 1.0, 0.95, name_class_lookup=lambda nm: "uncertain")
    assert res.action == "defer"

def test_specific_still_merges():
    a, b = _pair("ubnd tỉnh trà vinh")
    res = rule_based_decision(a, b, 1.0, 0.95, name_class_lookup=lambda nm: "specific")
    assert res.action == "merge" and res.reason == "exact normalized name match"

def test_no_lookup_preserves_legacy_behavior():
    a, b = _pair("ubnd tỉnh trà vinh")
    res = rule_based_decision(a, b, 1.0, 0.95)  # no lookup → unchanged
    assert res.action == "merge"
```

- [ ] **Step 2: Run → fail**

Run: `uv run pytest tests/resolution/test_rules_guard.py -v` → FAIL.

- [ ] **Step 3: Implement the guard**

In `rules.py`, add the optional `name_class_lookup` param to `rule_based_decision` and gate the exact-name branch (L99-100). Keep the existing positional params `(entity, candidate, sim, rule_sim_high)` intact; append the keyword:
```python
def rule_based_decision(entity, candidate, sim, rule_sim_high, name_class_lookup=None):
    ...                                 # existing sim-floor reject stays first
    if entity["name"] and _normalize(entity["name"]) == _normalize(candidate["name"]):
        nm = _normalize(entity["name"])
        cls = name_class_lookup(nm) if name_class_lookup is not None else "specific"
        if cls == "generic":
            return RuleResult("reject", 0.0, "exact name but classified generic")
        if cls in (None, "uncertain"):
            return RuleResult("defer", 0.0, "exact name, genericness uncertain — defer to verifier")
        return RuleResult("merge", EXACT_NAME_CONFIDENCE, "exact normalized name match")
    ...                                 # existing 'defer' fallthrough stays
```
(Use the real parameter names from rules.py:73 — `entity`/`candidate` here are illustrative; match the actual signature.) Wire `name_class_lookup` from `pass2.py`'s `Deps`: read the classification artifact once per run into a `dict[str,str]` and pass `lambda nm: classes.get(nm)`. Older callers that don't set it get `None` ⇒ legacy `merge`. No new `RuleResult.action` is needed — `reject`/`defer` are existing, and `pass2.py:111-116` already handles `merge`/`reject` (and falls through on `defer`).

- [ ] **Step 4: Run → pass**

Run: `uv run pytest tests/resolution/test_rules_guard.py tests/resolution/test_name_class.py -v` → PASS. Then run the existing resolution tests to confirm no regression: `uv run pytest tests/resolution/ -v`.

- [ ] **Step 5: Commit**

```bash
git add src/ennam_kg/resolution/rules.py tests/resolution/test_rules_guard.py
git commit -m "fix(daab): producer-side genericness guard on exact-name merge (close footgun)"
```

---

## Phase 5 — Candidate emission (Python)

### Task 8: `emit_hub_merge_candidates` CLI

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/resolution/emit_hub_candidates_cli.py`
- Test: `ennam.kg.python/tests/resolution/test_emit_hub_candidates.py`

**Interfaces:**
- Consumes: the classification artifact (only `class='specific'` names), concept node ids per group.
- Produces: for each specific group, N−1 pairwise `create_merge_suggestion` calls with `reason='exact-name hub merge candidate'`, `decision='suggested'`, `proposed_canonical_id` = the group's canonical (highest-degree, tiebreak earliest-created). A pure `build_candidates(groups) -> list[Candidate]` core + a `main()` CLI.

- [ ] **Step 1: Write failing test (pure core)**

Create `tests/resolution/test_emit_hub_candidates.py`:
```python
from ennam_kg.resolution.emit_hub_candidates_cli import build_candidates

def test_group_emits_n_minus_1_pairs_with_distinct_reason():
    # one specific group of 3 nodes (id, degree, created_at_iso)
    groups = {"ubnd tỉnh trà vinh": [("n1", 50, "2026-01-01"), ("n2", 5, "2026-01-02"), ("n3", 5, "2026-01-03")]}
    cands = build_candidates(groups)
    assert len(cands) == 2  # N-1
    canon = {c.proposed_canonical_id for c in cands}
    assert canon == {"n1"}  # highest degree is canonical
    assert all(c.reason == "exact-name hub merge candidate" for c in cands)
    assert {c.member_id for c in cands} == {"n2", "n3"}
```

- [ ] **Step 2: Run → fail**

Run: `uv run pytest tests/resolution/test_emit_hub_candidates.py -v` → FAIL.

- [ ] **Step 3: Implement**

Create `emit_hub_candidates_cli.py`:
```python
"""Emit exact-name hub merge candidates (1b) for names classified 'specific'.

Writes N-1 pairwise merge_suggestions per group via create_merge_suggestion,
tagged with a DISTINCT reason so the worker's /apply-exact-name never grabs them.
"""
from __future__ import annotations
import argparse
import os
from dataclasses import dataclass

HUB_MERGE_REASON = "exact-name hub merge candidate"


@dataclass
class Candidate:
    member_id: str
    proposed_canonical_id: str
    reason: str = HUB_MERGE_REASON


def _pick_canonical(members: list[tuple[str, int, str]]) -> str:
    """members = [(id, degree, created_at)]. Canonical = highest degree, tiebreak earliest created."""
    return sorted(members, key=lambda m: (-m[1], m[2]))[0][0]


def build_candidates(groups: dict[str, list[tuple[str, int, str]]]) -> list[Candidate]:
    out: list[Candidate] = []
    for _name, members in groups.items():
        if len(members) < 2:
            continue
        canon = _pick_canonical(members)
        for mid, _deg, _ca in members:
            if mid != canon:
                out.append(Candidate(member_id=mid, proposed_canonical_id=canon))
    return out


def _load_specific_groups(project_id: str) -> dict[str, list[tuple[str, int, str]]]:
    """Load nodes (id, degree, created_at) grouped by normalized name, only names class='specific'."""
    import psycopg
    dsn = os.environ["KG_DATABASE_URL"]
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT lower(btrim(n.title)) AS nm, n.id::text,
                   (SELECT count(*) FROM knowledge_edges e WHERE e.source_id=n.id OR e.target_id=n.id),
                   n.created_at::text
            FROM knowledge_nodes n
            JOIN entity_name_classification c
              ON c.project_id=n.project_id AND c.normalized_name=lower(btrim(n.title)) AND c.class='specific'
            WHERE n.node_type='concept' AND n.project_id=%s
              AND COALESCE((n.properties->>'merged_into'),'')=''
            ORDER BY 1
            """,
            (project_id,),
        )
        groups: dict[str, list[tuple[str, int, str]]] = {}
        for nm, nid, deg, ca in cur.fetchall():
            groups.setdefault(nm, []).append((nid, int(deg or 0), ca))
        return {k: v for k, v in groups.items() if len(v) > 1}


def main() -> None:
    p = argparse.ArgumentParser(description="Emit exact-name hub merge candidates (1b)")
    p.add_argument("--project", required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    cands = build_candidates(_load_specific_groups(args.project))
    print(f"{len(cands)} pairwise candidates")
    if args.dry_run:
        return
    import httpx
    base = os.environ.get("KG_API_URL", "http://localhost:8082")
    headers = {"Authorization": f"Bearer {os.environ.get('KG_API_KEY','')}"}
    # POST directly to the existing suggestion-create endpoint (handler/merge_suggestion.go).
    with httpx.Client(base_url=base, headers=headers, timeout=30) as client:
        for c in cands:
            r = client.post("/api/v1/internal/resolution/suggestions", json={
                "project_id": args.project,
                "node_a_id": c.member_id,
                "node_b_id": c.proposed_canonical_id,
                "proposed_canonical_id": c.proposed_canonical_id,
                "resolution_model": "exact-name-hub-1b",
                "reason": c.reason,                 # 'exact-name hub merge candidate' (distinct)
                "decision": "suggested",
                "embedding_similarity": 0.0,
                "merge_confidence": 0.99,
                "degree_max": 0,
            })
            r.raise_for_status()
    print("candidates written")


if __name__ == "__main__":
    main()
```
(Confirm `KGClientWriter.create_merge_suggestion` accepts these kwargs — inspect `ennam.kg.python/src/ennam_kg/benchmark/cli.py`; adapt names to the real signature. Confirm the `merged_into` property key + `created_at` casting against the schema.)

- [ ] **Step 4: Run → pass**

Run: `uv run pytest tests/resolution/test_emit_hub_candidates.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ennam_kg/resolution/emit_hub_candidates_cli.py tests/resolution/test_emit_hub_candidates.py
git commit -m "feat(daab): emit exact-name hub merge candidates (distinct reason, N-1 pairwise)"
```

---

## Phase 6 — Apply (Go)

### Task 9: `ApplyHubNameMerges` service + manifest + `ListHubMergeCandidates`

**Files:**
- Modify: `ennam.kg.go/internal/store/merge_suggestion.go` (add `ListHubMergeCandidates`)
- Modify: `ennam.kg.go/internal/service/apply_suggestions.go` (add `ApplyHubNameMerges`)
- Test: `ennam.kg.go/internal/service/apply_suggestions_test.go` (extend)

**Interfaces:**
- Consumes: `processSuggestion` (existing), `MergeSuggestion`.
- Produces:
  - `(*MergeSuggestionStore).ListHubMergeCandidates(ctx, projectID) ([]MergeSuggestion, error)` — clone of `ListExactNameSuggestions` (merge_suggestion.go:119) but `reason='exact-name hub merge candidate'`.
  - `type HubMergeManifest struct { Groups []HubMergeGroup }` / `HubMergeGroup{ CanonicalID string; MemberIDs []string; DegreeMax int }`.
  - `(*ApplySuggestionsService).ApplyHubNameMerges(ctx, projectID string, dryRun bool) (ApplyResult, HubMergeManifest, error)` — `dryRun` builds the manifest and applies nothing; otherwise applies via `processSuggestion(..., bypassDegreeGate=true)` and records the manifest.

- [ ] **Step 1: Write the failing test**

Append to `apply_suggestions_test.go` a test using the existing fakes/setup in that file (mirror how `ApplyExactNameMerges` is tested): seed a candidate row with `reason='exact-name hub merge candidate'`; assert `ApplyHubNameMerges(dryRun=true)` returns a manifest and applies 0; `dryRun=false` applies via the merge service and returns the merged result. (Use the file's existing fake `suggestionStore`/`mergeService` — match their interfaces.)

- [ ] **Step 2: Run → fail**

Run: `go test ./internal/service/ -run TestApplyHubName -v` → FAIL (undefined).

- [ ] **Step 3: Implement `ListHubMergeCandidates` + `ApplyHubNameMerges`**

In `merge_suggestion.go`, add (mirror `ListExactNameSuggestions` at L119, only the reason differs):
```go
// ListHubMergeCandidates returns 'suggested' rows with reason
// 'exact-name hub merge candidate' (the 1b distinct-reason band).
func (s *MergeSuggestionStore) ListHubMergeCandidates(ctx context.Context, projectID string) ([]MergeSuggestion, error) {
	return s.listByReason(ctx, projectID, "exact-name hub merge candidate")
}
```
(Refactor the existing `ListExactNameSuggestions` body into a private `listByReason(ctx, projectID, reason)` and have both call it — DRY; keep `ListExactNameSuggestions` calling it with `'exact normalized name match'`.)

In `apply_suggestions.go`, add:
```go
// HubMergeGroup is one canonical + its members in a hub-merge manifest.
type HubMergeGroup struct {
	CanonicalID string   `json:"canonical_id"`
	MemberIDs   []string `json:"member_ids"`
	DegreeMax   int      `json:"degree_max"`
}

// HubMergeManifest is the audit record of an ApplyHubNameMerges run.
type HubMergeManifest struct {
	Groups []HubMergeGroup `json:"groups"`
}

// ApplyHubNameMerges applies the 1b distinct-reason candidates. dryRun builds the
// manifest and applies nothing. These names are already cleared 'specific' by the
// producer (the genericness guard is upstream), so they bypass the degree gate.
func (s *ApplySuggestionsService) ApplyHubNameMerges(ctx context.Context, projectID string, dryRun bool) (ApplyResult, HubMergeManifest, error) {
	sugg, err := s.suggestionStore.ListHubMergeCandidates(ctx, projectID)
	if err != nil {
		return ApplyResult{}, HubMergeManifest{}, fmt.Errorf("list hub candidates: %w", err)
	}
	// Build the manifest (canonical -> members), and compute degree for visibility.
	byCanon := map[string]*HubMergeGroup{}
	for _, sg := range sugg {
		g := byCanon[sg.ProposedCanonicalID]
		if g == nil {
			g = &HubMergeGroup{CanonicalID: sg.ProposedCanonicalID}
			byCanon[sg.ProposedCanonicalID] = g
		}
		member := sg.NodeAID
		if sg.ProposedCanonicalID == sg.NodeAID {
			member = sg.NodeBID
		}
		g.MemberIDs = append(g.MemberIDs, member)
		if d, derr := s.edgeStore.Degree(ctx, sg.ProposedCanonicalID); derr == nil && d > g.DegreeMax {
			g.DegreeMax = d
		}
	}
	var manifest HubMergeManifest
	for _, g := range byCanon {
		manifest.Groups = append(manifest.Groups, *g)
	}
	if dryRun {
		return ApplyResult{}, manifest, nil
	}
	var res ApplyResult
	for _, sg := range sugg {
		if applyErr := s.processSuggestion(ctx, sg, 0, true, &res); applyErr != nil {
			res.Errors = append(res.Errors, fmt.Errorf("suggestion %s: %w", sg.ID, applyErr))
		}
	}
	s.logger.Info("apply hub-name merges", "project_id", projectID, "applied", res.Applied, "groups", len(manifest.Groups))
	return res, manifest, nil
}
```

- [ ] **Step 4: Run → pass**

Run: `go test ./internal/service/ -run TestApplyHubName -v` → PASS. Then the package: `go test -race ./internal/service/`.

- [ ] **Step 5: Commit**

```bash
git add internal/store/merge_suggestion.go internal/service/apply_suggestions.go internal/service/apply_suggestions_test.go
git commit -m "feat(daab): ApplyHubNameMerges (manifest + dryRun, reuses pairwise merge)"
```

---

### Task 10: Apply endpoint

**Files:**
- Modify: `ennam.kg.go/internal/handler/apply_suggestions.go` (add handler) + register in `RegisterRoutes`
- Test: `ennam.kg.go/internal/handler/apply_suggestions_test.go` (extend)

**Interfaces:**
- Produces: `POST /api/v1/internal/resolution/apply-hub-name` body `{project_id, dry_run}` → `{applied, needs_review, errors, manifest}`.

- [ ] **Step 1: Write the failing test**

Extend `apply_suggestions_test.go` (mirror the existing `HandleApplyExactName` test): a fake service returning a manifest; assert the endpoint returns 200 with the manifest, and `dry_run=true` is threaded to the service.

- [ ] **Step 2: Run → fail** — `go test ./internal/handler/ -run TestApplyHubName -v` → FAIL.

- [ ] **Step 3: Implement** — add to `apply_suggestions.go` handler (mirror `HandleApplyExactName` at L100, but call `ApplyHubNameMerges` and include the manifest in the response), and register `mux.HandleFunc("POST /api/v1/internal/resolution/apply-hub-name", h.HandleApplyHubName)` in `RegisterRoutes`. Decode `{project_id, dry_run}`; on success `writeJSON(w, 200, {applied, needs_review, errors, manifest})`.

- [ ] **Step 4: Run → pass; build** — `go test ./internal/handler/ -run TestApplyHubName && go build ./...`.

- [ ] **Step 5: Commit**

```bash
git add internal/handler/apply_suggestions.go internal/handler/apply_suggestions_test.go
git commit -m "feat(daab): /apply-hub-name endpoint (dry-run manifest + apply)"
```

---

## Phase 7 — Rollout & verification (operational runbook, no new code)

### Task 11: Shadow → review → apply → measure

**Files:** none (operational). Run against the live stack; record outputs.

- [ ] **Step 1: Re-verify the live numbers (Step-0)**

Run on the live DB (reconcile `:5433` vs the daab-* stack the 1a checkpoint cites):
```sql
SELECT decision, count(*) FROM merge_suggestions WHERE reason='exact normalized name match' GROUP BY 1;
-- bucket the duplicate groups (org_marker / bare_geo / short / residual) + residual node-mass
```
Expected: confirm Build A (≈0 parked exact-name) and the bucket sizes that size the review tiers.

**Scope note (retroactive audit):** 1a already auto-applied ~5725 exact-name merges with NO genericness guard. The big generic groups ("dự án" ×40) *survived unmerged* (they didn't co-block), so the retroactive risk is low — but it is NOT zero. After the artifact is built (Step 2), optionally spot-check: `SELECT … FROM <applied merges> JOIN entity_name_classification c ON c.normalized_name=… WHERE c.class='generic'` — any hit is a wrong 1a merge to `unmerge`. This is a low-priority follow-up, separate from 1b's forward fix; flag it, don't block on it.

- [ ] **Step 2: Build the classification artifact**

Run: `KG_DATABASE_URL=... KG_API_URL=http://localhost:8082 KG_API_KEY=... uv run python -m ennam_kg.resolution.classify_corpus_cli --project <PID>`
Verify `entity_name_classification` populated; spot-check: "dự án"/"pháp luật"/"điều 3" = `generic`; "ubnd tỉnh trà vinh"/"dự án khu bến tổng hợp định an" = `specific`.

- [ ] **Step 3: Human review of danger strata (gate)**

Query the artifact: review **all** `uncertain` + **all** `generic` (assert none should have been `specific`) + the **top-degree** groups (×103/×65/×63 — confirm each is truly ONE entity across all members). Fix via a `source='human'` upsert. **Pass = zero false `specific` in danger strata.**

- [ ] **Step 4: Emit candidates + dry-run manifest**

Run: `uv run python -m ennam_kg.resolution.emit_hub_candidates_cli --project <PID>` then
`curl -XPOST .../api/v1/internal/resolution/apply-hub-name -d '{"project_id":"<PID>","dry_run":true}'`.
Review the manifest; precision-sample N≈60–100 cleared `specific` groups (honestly a weak bound). **Pass = zero false merges in the sample.**

- [ ] **Step 5: Un-merge drill**

Apply a handful (or apply all, then) `unmerge` a few real merges; assert byte-equivalent restore via the existing un-merge path. **Pass = restore verified.**

- [ ] **Step 6: Apply + measure connectivity**

Run `apply-hub-name` with `dry_run=false`. Measure before/after: duplicate-node count drop, and a connectivity check — pick 2 documents that share a now-canonical entity and confirm a cross-document path exists that did not before. Record the manifest for rollback.

- [ ] **Step 7: Write a Serena checkpoint + update backlog**

`mcp__serena__write_memory("checkpoint/<agent>-<date>", …)`; update `mem:backlog/daab-entity-resolution-corpus-rerun` (1b done) and note Step-2 ("related documents / shared entities" feature) as the next increment.

---

## Self-Review notes (author)

- **Spec coverage:** artifact table §6 → T1-T3; discriminator §6 → T4-T5; corpus scan §7 → T6; producer guard §8.2 → T7; candidate emission §7/§8.1 → T8; apply+manifest §7/§9 → T9-T10; rollout §9 → T11. All covered.
- **Type/contract consistency:** `NameClassification{ProjectID,NormalizedName,Class,Source,Rationale,ReviewedBy}` (Go) ↔ `NameClass{normalized_name,cls,source,rationale}` (Python) ↔ endpoint `items[]` JSON — aligned. `reason='exact-name hub merge candidate'` identical in T8 (Python emit) and T9 (`ListHubMergeCandidates`). `proposed_canonical_id` semantics match `processSuggestion`'s pairwise contract (canonical must be node_a or node_b).
- **Footgun:** distinct reason (T8) + producer guard (T7) both implemented; the worker's `/apply-exact-name` (reason `'exact normalized name match'`) never sees 1b candidates or generic names.
- **Verified (corrected in this plan):** `RuleResult(action∈{merge,reject,defer}, confidence, reason)` — guard uses `reject`/`defer`, no new action (rules.py:58-72); `rule_based_decision(entity,candidate,sim,rule_sim_high,…)` 4-arg signature (pass2.py:110); `AIClient.complete_json(prompt,system_prompt)` is async→dict (client.py:67) — T5 takes an injected `llm_json`, T6 wraps it with `asyncio.run`; T8 POSTs directly to `/api/v1/internal/resolution/suggestions` with the verified body (merge_suggestion.go:26-36) instead of a non-existent `KGClientWriter.create_merge_suggestion`.
- **Implementer must still confirm (single-file, not design):** the Python direct-DB env var name (used `KG_DATABASE_URL` in T6/T8 — confirm against `worker.py`/settings); the `merged_into` property key + `created_at` cast in the T8 SQL; that the Go test-package helpers `setupTestDB`/`acSeedProject` are reusable from the new store/handler test files (they are in `store_test`/`handler` packages).
