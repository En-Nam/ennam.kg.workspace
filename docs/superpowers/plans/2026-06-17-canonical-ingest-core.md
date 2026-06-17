# Canonical Ingest Core (BA-030) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the three divergent text-extraction paths into one canonical document representation, produced once in the Python worker and consumed identically by DAAB (KG) and AAA (field extraction).

**Architecture:** A new `build_canonical_document(draft, raw_text)` entry point in the Python worker wraps the existing three stages (bytes→text, text→sections, text→chunks) behind one normalization step, persists a `canonical_document` row (new Go-owned table + REST endpoints, called via `KGClient`), enforces content-hash dedup, and becomes the *sole* producer of `document_chunk` nodes. Go ceases synchronous text extraction. All processing stays behind the existing approval gate.

**Tech Stack:** Go (stdlib `net/http`, `database/sql`, golang-migrate), Python 3.12 (worker, pytest, httpx `KGClient`), PostgreSQL 16.

## Global Constraints

- **Spec authority:** `docs/superpowers/specs/2026-06-17-canonical-ingest-core-design.md`. Where this plan and the BA disagree, the spec wins (it encodes the TC/CTO ruling).
- **v1 scope:** FR-001, FR-002 (incl. normalization), FR-003, FR-004, FR-006. **FR-005 (context headers) and the 2 GET endpoints are CUT** — do not implement.
- **Chunkable-format gate (decided 2026-06-17):** the canonical builder produces sections/chunks **only** for formats decomposed today — `CHUNKABLE_FORMATS = {markdown, md, plain_text, txt, text}` (mirrors `decompose.py:20` `_TEXT_FORMATS`). `.pdf`/`.docx` extract to `plain_text` so they ARE chunked; **`.json`/`.csv`/`.xlsx` stay hub-only (no chunks), preserving current behavior** (AGENTS.md Rule 3). A `canonical_document` row + `content_hash` is still produced for every format (FR-001/FR-004 are universal); only chunk production is gated.
- **NFR-239 (reframed):** cross-path equivalence is asserted for **text-format** content — the same logical text via a text-format upload vs `satellite_api` yields identical `content_hash` and chunks (both flow through the canonical builder + normalization). Structured formats (json/csv/xlsx) are hub-only; cross-path *structural* hash parity for them is **not** guaranteed and is out of scope (they are never chunked).
- **No new infra:** no new system binary, no new Python/Go dependency, no Docker image growth. OCR is out of scope.
- **Determinism (NFR-240):** extraction/normalization/hashing/chunk-keys are pure deterministic transforms — **no AI/model call** in this path (AGENTS.md Rule 5).
- **Approval gate (HARD, Option A):** extraction + canonicalization may run pre-approval; **decomposition / indexing / any KG mutation MUST NOT run before approval** — for **both** text and binary uploads.
- **Managed Postgres (NFR-250):** only RDS-allowlisted extensions (`vector`, `pg_trgm`, `uuid-ossp`). No new extension.
- **Embedding model invariance (NFR-251):** stays multilingual-e5-small, `vector(384)`. Do not change.
- **`extraction_method` values v1:** only `text` (text-extractable PDF) and `native` (non-PDF). `ocr`/`mixed` are reserved in the CHECK, never written.
- **Commit style:** conventional commits (`feat:`/`test:`/`refactor:`), one per task. Branch is `task/implement_mcp` (not main).

---

## File Structure

**Go (`ennam.kg.go/`)**
- Create: `db/migrations/000060_create_canonical_document.up.sql` / `.down.sql` — new table.
- Create: `internal/models/canonical_document.go` — `CanonicalDocument` struct.
- Create: `internal/store/canonical_document.go` — `CanonicalDocumentStore` (upsert-by-draft, get-by-source-hash).
- Create: `internal/handler/canonical_document.go` — REST handlers (member+/worker auth, same as the node/draft routes the worker already calls) for upsert + lookup + subtree-delete.
- Modify: `internal/store/node.go` — add `DeleteDocumentSubtree` (hard delete of a doc's section+chunk nodes; embeddings cascade).
- Modify: `internal/service/file_upload.go` — `classifyUploadFile` (~:355), delete `extractTextSync` (~:372) + its branch (~:241), `ContentExtracted` (~:222).
- Modify: `cmd/kg-server/main.go` — wire the new store + routes.
- Test: `internal/store/canonical_document_test.go` (nil-DB unit + `setupTestDB`-gated), `internal/store/node_test.go` (subtree delete), `internal/handler/canonical_document_test.go`, `internal/service/file_upload_test.go`.

**Python (`ennam.kg.python/`)**
- Create: `src/ennam_kg/ingestion/pipeline/normalize.py` — `normalize_canonical_text(raw_text, content_format) -> str`.
- Create: `src/ennam_kg/ingestion/pipeline/canonical.py` — `build_canonical_document(...)` + `CanonicalDocument`/`CanonicalChunk` dataclasses + `EmptyExtractionError`.
- Modify: `packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py` — add `get_canonical_document_by_source`, `upsert_canonical_document`, `delete_document_subtree` (Bearer auth via existing `_request`; the worker already authenticates with this client).
- Modify: `src/ennam_kg/ingestion/pipeline/engine.py` — `run_batch` dedup check + canonical persistence (~:52-120).
- Modify: `src/ennam_kg/ingestion/pipeline/decompose.py` — consume canonical chunk list, stop re-chunking (~:57, ~:135).
- Modify: `src/ennam_kg/worker.py` — `handle_extract_upload` extract-only, no `run_batch` (~:45-89).
- Test: `tests/ingestion/test_normalize.py`, `tests/ingestion/test_canonical.py`, `tests/ingestion/test_dedup.py`, `tests/ingestion/test_decompose_canonical.py`, `tests/test_worker_extract_gate.py`, `tests/ingestion/test_characterization.py`.

---

## PHASE 0 — Foundation: migration + characterization guard

> Goal: the canonical table exists (empty), and a characterization test pins **current** pipeline output so later refactors are regression-guarded. No behavior change yet.

### Task 0.1: Migration `000060` — `canonical_document` table

**Files:**
- Create: `ennam.kg.go/db/migrations/000060_create_canonical_document.up.sql`
- Create: `ennam.kg.go/db/migrations/000060_create_canonical_document.down.sql`

**Interfaces:**
- Produces: table `canonical_document` keyed `UNIQUE(draft_node_id)`, with dedup indexes `(project_id, source_type, source_id)` and `(project_id, content_hash) WHERE deleted_at IS NULL`.

- [ ] **Step 1: Write the up migration**

```sql
-- BA-030 FR-001: canonical document anchor (one per draft).
CREATE TABLE canonical_document (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id         UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    draft_node_id      UUID NOT NULL REFERENCES draft_nodes(id),
    knowledge_node_id  UUID NOT NULL REFERENCES knowledge_nodes(id),
    source_type        VARCHAR(50) NOT NULL
        CHECK (source_type IN ('jira','google_drive','local_upload','satellite_api','manual')),
    source_id          VARCHAR(500) NOT NULL,
    content_hash       TEXT NOT NULL,
    extraction_method  VARCHAR(20) NOT NULL
        CHECK (extraction_method IN ('text','ocr','mixed','native')),
    metadata           JSONB NOT NULL DEFAULT '{}',
    extracted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at         TIMESTAMPTZ
);

CREATE UNIQUE INDEX uq_canonical_document_draft ON canonical_document (draft_node_id);
CREATE INDEX idx_canonical_document_source ON canonical_document (project_id, source_type, source_id);
CREATE INDEX idx_canonical_document_hash ON canonical_document (project_id, content_hash) WHERE deleted_at IS NULL;
```

- [ ] **Step 2: Write the down migration**

```sql
DROP TABLE IF EXISTS canonical_document;
```

- [ ] **Step 3: Apply up then down then up, verify clean**

Run: `cd ennam.kg.go && make db-migrate && make db-migrate-down && make db-migrate` (targets wrap `go run ./cmd/kg-migrate/ up|down`; `make db-migrate-version` prints the current version).
Expected: up creates the table, down drops it with no error, re-up succeeds. Verify via `make db-shell` then `\d canonical_document` shows the three indexes.

- [ ] **Step 4: Commit**

```bash
git add ennam.kg.go/db/migrations/000060_create_canonical_document.*.sql
git commit -m "feat(db): add canonical_document table (BA-030 FR-001, migration 000060)"
```

### Task 0.2: Characterization test of current pipeline output

> Pins today's section/chunk content + offsets for the formats that are **actually chunked** — markdown, plain-text, and extracted-PDF text (which `files.py` returns as `plain_text` with `## Page N` markers). JSON/CSV/XLSX are **hub-only** today (the `_TEXT_FORMATS` gate at `decompose.py:50` skips them), so they are **not** part of this chunk-path guard. Reads the current path (`parse_markdown_sections` → `chunk_section`).

**Files:**
- Create: `ennam.kg.python/tests/ingestion/test_characterization.py`
- Create: `ennam.kg.python/tests/ingestion/fixtures/char_sample.md`, `char_sample.txt`, `char_sample_pdf.txt` (the last simulates pypdf output: `## Page 1\n\n<text>\n\n## Page 2\n\n<text>`)

**Interfaces:**
- Consumes: `parse_markdown_sections` (`document_tree.py:22`), `chunk_section` (`chunker.py:72`).
- Produces: a committed golden snapshot (`tests/ingestion/fixtures/char_golden.json`) of `{section_title, ordinal, content, char_start, char_end}` per chunk. **Note:** `chunk_key` is intentionally **excluded** from the golden — in production it embeds the persisted section-node UUID, which placeholder ids can't reproduce; the guard pins content/offsets/ordinal, which is what the refactor must preserve.

- [ ] **Step 1: Write fixtures** — a 3-heading markdown doc, a plain-text doc, and a `## Page N`-structured text doc (real content, ≤2 KB each).

- [ ] **Step 2: Write the failing characterization test**

```python
import json
from pathlib import Path
from ennam_kg.ingestion.pipeline.document_tree import parse_markdown_sections
from ennam_kg.ingestion.pipeline.chunker import chunk_section

FIX = Path(__file__).parent / "fixtures"
GOLDEN = FIX / "char_golden.json"

def _pipeline(content: str) -> list[dict]:
    out = []
    for sec_idx, sec in enumerate(parse_markdown_sections(content)):
        sec_id = f"sec{sec_idx}"  # placeholder; real key uses persisted node id
        for ch in chunk_section(sec_id, "doc0", sec.title, sec.text, sec.line_start):
            out.append({
                "section_title": sec.title,
                "ordinal": ch.ordinal,
                "content": ch.content,
                "char_start": ch.char_start,
                "char_end": ch.char_end,
            })
    return out

def test_characterization_matches_golden():
    samples = {}
    for name, f in [("md", "char_sample.md"), ("txt", "char_sample.txt"), ("pdf", "char_sample_pdf.txt")]:
        samples[name] = _pipeline((FIX / f).read_text(encoding="utf-8"))
    expected = json.loads(GOLDEN.read_text())
    assert samples == expected, "current chunk-path output drifted from golden snapshot"
```

- [ ] **Step 3: Generate the golden snapshot once, then run the test**

First run fails (no golden). Generate it deterministically:
Run: `cd ennam.kg.python && uv run python -c "import json,sys; sys.path.insert(0,'tests/ingestion'); from test_characterization import _pipeline; from pathlib import Path; FIX=Path('tests/ingestion/fixtures'); out={n:_pipeline((FIX/f).read_text()) for n,f in [('md','char_sample.md'),('txt','char_sample.txt'),('pdf','char_sample_pdf.txt')]}; (FIX/'char_golden.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))"`
Then: `uv run pytest tests/ingestion/test_characterization.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add ennam.kg.python/tests/ingestion/test_characterization.py ennam.kg.python/tests/ingestion/fixtures/
git commit -m "test: characterization snapshot of current chunk-path output (md/txt/pdf) — P0 guard"
```

---

## PHASE 1 — `build_canonical_document` + normalization + persistence (alongside, no cutover)

> Goal: the canonical builder exists and writes `canonical_document` rows **in addition to** the current flow. No consumer reroutes yet. Cross-path normalization closes the NFR-239 hole; fail-loud closes FR-003.

### Task 1.1: Cross-path normalization (FR-002 / NFR-239)

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/ingestion/pipeline/normalize.py`
- Test: `ennam.kg.python/tests/ingestion/test_normalize.py`

**Interfaces:**
- Produces: `normalize_canonical_text(raw_text: str) -> str` — pure, deterministic. Applied identically to all three paths' raw text before hashing/sectioning.

- [ ] **Step 1: Write the failing test**

```python
from ennam_kg.ingestion.pipeline.normalize import normalize_canonical_text

def test_crlf_normalized_to_lf():
    assert normalize_canonical_text("a\r\nb\rc") == "a\nb\nc"

def test_trailing_whitespace_and_bom_stripped():
    assert normalize_canonical_text("﻿hello \n") == "hello"

def test_idempotent():
    once = normalize_canonical_text("a\r\nb\n")
    assert normalize_canonical_text(once) == once

def test_same_logical_content_same_hash_regardless_of_line_endings():
    import hashlib
    a = normalize_canonical_text("x\r\ny")
    b = normalize_canonical_text("x\ny")
    assert hashlib.sha256(a.encode()).hexdigest() == hashlib.sha256(b.encode()).hexdigest()
```

- [ ] **Step 2: Run, verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_normalize.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement minimal normalization**

```python
"""FR-002 / NFR-239: single cross-path canonical-text normalization.

Pure deterministic transform applied to every ingest path's raw text BEFORE
hashing and sectioning, so identical logical content yields one content_hash
regardless of intake path. No AI (AGENTS.md Rule 5).
"""
from __future__ import annotations


def normalize_canonical_text(raw_text: str) -> str:
    text = raw_text.lstrip("﻿")          # strip BOM
    text = text.replace("\r\n", "\n").replace("\r", "\n")  # CRLF/CR -> LF
    text = "\n".join(line.rstrip() for line in text.split("\n"))  # trailing ws
    return text.strip()
```

- [ ] **Step 4: Run, verify pass**

Run: `uv run pytest tests/ingestion/test_normalize.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/ingestion/pipeline/normalize.py ennam.kg.python/tests/ingestion/test_normalize.py
git commit -m "feat(ingest): cross-path canonical text normalization (FR-002/NFR-239)"
```

### Task 1.2: `build_canonical_document` — wrap normalize + sections + chunks, fail-loud (FR-002/FR-003)

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/ingestion/pipeline/canonical.py`
- Test: `ennam.kg.python/tests/ingestion/test_canonical.py`

**Interfaces:**
- Consumes: `normalize_canonical_text` (Task 1.1), `parse_markdown_sections` → `list[MarkdownSection]`, `build_document_tree_json(list[MarkdownSection]) -> list[dict]` (`document_tree.py:72`), `chunk_section(section_id, document_id, section_title, text, section_line_start) -> list[Chunk]`.
- Produces:
  - `EmptyExtractionError(Exception)` with `.reason = "extraction_empty"`.
  - `CHUNKABLE_FORMATS = frozenset({"markdown","md","plain_text","txt","text"})` (mirrors `decompose.py:20`).
  - `MIN_USABLE_CHARS = 20`.
  - `CanonicalSection` dataclass (frozen): `local_id: str, title: str, level: int, line_start: int, line_end: int, text: str, section_path: str`.
  - `CanonicalChunk` dataclass (frozen): `section_local_id: str, ordinal: int, title: str, content: str, content_hash: str, line_start: int, line_end: int, char_start: int, char_end: int, token_estimate: int`. **No final `chunk_key`/`section_id`** — those embed the persisted section-node UUID and are stamped by `decompose` (Task 5.1) as `f"{section_node_id}:{ordinal}"`.
  - `CanonicalDocument` dataclass (frozen): `canonical_text: str, content_hash: str, extraction_method: str, sections: list[CanonicalSection], chunks: list[CanonicalChunk], tree: list[dict]`.
  - `build_canonical_document(*, raw_text: str, content_format: str, is_pdf: bool, min_chars: int = MIN_USABLE_CHARS) -> CanonicalDocument`. When `content_format` is not in `CHUNKABLE_FORMATS`, returns `sections=[]`, `chunks=[]`, `tree=[]` (hub-only) but still a valid `canonical_text`/`content_hash`/`extraction_method`.

- [ ] **Step 1: Write failing tests (determinism, fail-loud, section_path, chunk identity)**

```python
import pytest
from ennam_kg.ingestion.pipeline.canonical import (
    build_canonical_document, EmptyExtractionError, MIN_USABLE_CHARS,
)

MD = "# Doc Title\n\nintro para that is clearly long enough to pass.\n\n## Pricing\n\nbody about pricing terms here, also long enough.\n"

def test_deterministic_same_input_same_output():
    a = build_canonical_document(raw_text=MD, content_format="markdown", is_pdf=False)
    b = build_canonical_document(raw_text=MD, content_format="markdown", is_pdf=False)
    assert a.content_hash == b.content_hash
    assert [(c.section_local_id, c.ordinal) for c in a.chunks] == [(c.section_local_id, c.ordinal) for c in b.chunks]
    assert [c.char_start for c in a.chunks] == [c.char_start for c in b.chunks]

def test_fail_loud_on_empty():
    with pytest.raises(EmptyExtractionError) as ei:
        build_canonical_document(raw_text="   \n  ", content_format="plain_text", is_pdf=True)
    assert ei.value.reason == "extraction_empty"

def test_fail_loud_on_below_threshold():
    with pytest.raises(EmptyExtractionError):
        build_canonical_document(raw_text="x" * (MIN_USABLE_CHARS - 1), content_format="plain_text", is_pdf=True)

def test_section_path_reflects_nesting():
    doc = build_canonical_document(raw_text=MD, content_format="markdown", is_pdf=False)
    paths = [s.section_path for s in doc.sections]
    assert paths[0] == "Doc Title"
    assert any(p.endswith("Pricing") for p in paths)

def test_extraction_method_native_for_non_pdf():
    doc = build_canonical_document(raw_text=MD, content_format="markdown", is_pdf=False)
    assert doc.extraction_method == "native"

def test_extraction_method_text_for_pdf():
    doc = build_canonical_document(raw_text=MD, content_format="markdown", is_pdf=True)
    assert doc.extraction_method == "text"

def test_non_chunkable_format_is_hub_only():
    # json/csv/xlsx: canonical text + hash, but NO sections/chunks (gate preserved)
    doc = build_canonical_document(raw_text='{"a": 1, "deal": "value here long enough"}', content_format="json", is_pdf=False)
    assert doc.content_hash and doc.canonical_text
    assert doc.sections == [] and doc.chunks == [] and doc.tree == []

def test_provisional_chunk_carries_section_local_id_and_ordinal():
    doc = build_canonical_document(raw_text=MD, content_format="markdown", is_pdf=False)
    assert all(c.section_local_id.startswith("sec") for c in doc.chunks)
    # ordinals restart per section
    by_sec = {}
    for c in doc.chunks:
        by_sec.setdefault(c.section_local_id, []).append(c.ordinal)
    for ords in by_sec.values():
        assert ords == list(range(len(ords)))
```

- [ ] **Step 2: Run, verify fail**

Run: `uv run pytest tests/ingestion/test_canonical.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `canonical.py`**

```python
"""FR-002/FR-003: unified extraction entry point.

Wraps normalize -> sections -> chunks behind one deterministic builder. Fails
loud on empty/near-empty extraction instead of storing a near-empty document.
Chunk production is gated to text formats (CHUNKABLE_FORMATS), preserving the
current decompose._TEXT_FORMATS behaviour; structured formats stay hub-only.
No AI (AGENTS.md Rule 5).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ennam_kg.ingestion.pipeline.chunker import chunk_section
from ennam_kg.ingestion.pipeline.document_tree import (
    build_document_tree_json,
    parse_markdown_sections,
)
from ennam_kg.ingestion.pipeline.normalize import normalize_canonical_text

MIN_USABLE_CHARS = 20  # below this, treat as no usable text (FR-003 BR-003.1)
# Mirrors decompose._TEXT_FORMATS — only these formats are sectioned/chunked.
CHUNKABLE_FORMATS = frozenset({"markdown", "md", "plain_text", "txt", "text"})


class EmptyExtractionError(Exception):
    def __init__(self, reason: str = "extraction_empty") -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CanonicalSection:
    local_id: str
    title: str
    level: int
    line_start: int
    line_end: int
    text: str
    section_path: str


@dataclass(frozen=True)
class CanonicalChunk:
    section_local_id: str   # resolved to the persisted section node id by decompose
    ordinal: int
    title: str
    content: str
    content_hash: str
    line_start: int
    line_end: int
    char_start: int
    char_end: int
    token_estimate: int


@dataclass(frozen=True)
class CanonicalDocument:
    canonical_text: str
    content_hash: str
    extraction_method: str
    sections: list[CanonicalSection]
    chunks: list[CanonicalChunk]
    tree: list[dict]


def _section_path(stack: list[tuple[int, str]], title: str) -> str:
    return " / ".join([t for _, t in stack] + [title])


def build_canonical_document(
    *, raw_text: str, content_format: str, is_pdf: bool, min_chars: int = MIN_USABLE_CHARS
) -> CanonicalDocument:
    canonical_text = normalize_canonical_text(raw_text)
    if len(canonical_text) < min_chars:
        raise EmptyExtractionError("extraction_empty")

    content_hash = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    method = "text" if is_pdf else "native"
    fmt = (content_format or "").strip().lower()

    # Hub-only formats (json/csv/xlsx): canonical doc + hash, no chunks (gate preserved).
    if fmt not in CHUNKABLE_FORMATS:
        return CanonicalDocument(canonical_text, content_hash, method, [], [], [])

    raw_sections = parse_markdown_sections(canonical_text)
    tree = build_document_tree_json(raw_sections)

    sections: list[CanonicalSection] = []
    chunks: list[CanonicalChunk] = []
    stack: list[tuple[int, str]] = []
    for idx, sec in enumerate(raw_sections):
        while stack and stack[-1][0] >= sec.level:
            stack.pop()
        path = _section_path(stack, sec.title)
        stack.append((sec.level, sec.title))
        local_id = f"sec{idx}"
        sections.append(CanonicalSection(
            local_id=local_id, title=sec.title, level=sec.level,
            line_start=sec.line_start, line_end=sec.line_end,
            text=sec.text, section_path=path,
        ))
        # chunk_section keys on its section_id arg; we pass the local_id so the
        # boundary/ordinal logic is identical to today. decompose re-stamps the
        # final key f"{section_node_id}:{ordinal}" (label only, not a re-chunk).
        for ch in chunk_section(local_id, "", sec.title, sec.text, sec.line_start):
            chunks.append(CanonicalChunk(
                section_local_id=local_id, ordinal=ch.ordinal, title=ch.title,
                content=ch.content, content_hash=ch.content_hash,
                line_start=ch.line_start, line_end=ch.line_end,
                char_start=ch.char_start, char_end=ch.char_end,
                token_estimate=ch.token_estimate,
            ))

    return CanonicalDocument(canonical_text, content_hash, method, sections, chunks, tree)
```

- [ ] **Step 4: Run, verify pass**

Run: `uv run pytest tests/ingestion/test_canonical.py -v`
Expected: PASS (all 7).

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/ingestion/pipeline/canonical.py ennam.kg.python/tests/ingestion/test_canonical.py
git commit -m "feat(ingest): build_canonical_document — unified extractor + fail-loud (FR-002/FR-003)"
```

### Task 1.3: Go `canonical_document` model + store

**Files:**
- Create: `ennam.kg.go/internal/models/canonical_document.go`
- Create: `ennam.kg.go/internal/store/canonical_document.go`
- Test: `ennam.kg.go/internal/store/canonical_document_test.go`

**Interfaces:**
- Produces:
  - `models.CanonicalDocument` struct mirroring the table columns.
  - `store.CanonicalDocumentStore` with:
    - `UpsertByDraft(ctx, doc models.CanonicalDocument) (models.CanonicalDocument, error)` — insert or update keyed on `draft_node_id` (BR-001.1).
    - `FindBySourceHash(ctx, projectID, sourceType, sourceID, contentHash string) (*models.CanonicalDocument, error)` — dedup lookup, `deleted_at IS NULL` (FR-004 BR-004.1).

- [ ] **Step 1: Write the model**

```go
package models

import "time"

type CanonicalDocument struct {
    ID               string         `json:"id"`
    ProjectID        string         `json:"project_id"`
    DraftNodeID      string         `json:"draft_node_id"`
    KnowledgeNodeID  string         `json:"knowledge_node_id"`
    SourceType       string         `json:"source_type"`
    SourceID         string         `json:"source_id"`
    ContentHash      string         `json:"content_hash"`
    ExtractionMethod string         `json:"extraction_method"`
    Metadata         map[string]any `json:"metadata"`
    ExtractedAt      time.Time      `json:"extracted_at"`
    CreatedAt        time.Time      `json:"created_at"`
    UpdatedAt        time.Time      `json:"updated_at"`
}
```

- [ ] **Step 2: Write the failing tests — match repo convention exactly.** Simple stores use **nil-DB unit tests**; SQL behavior uses a `setupTestDB(t)`-gated real-DB test that **skips when `KG_TEST_DATABASE_URL` is unset** (see `internal/store/node_embedding_test.go`). Write both:

```go
// internal/store/canonical_document_test.go — unit (always runs)
func TestNewCanonicalDocumentStore_NotNil(t *testing.T) {
    if NewCanonicalDocumentStore(nil) == nil {
        t.Fatal("NewCanonicalDocumentStore returned nil")
    }
}
func TestCanonicalDocumentStore_FindBySourceHash_NilDB(t *testing.T) {
    s := NewCanonicalDocumentStore(nil)
    if _, err := s.FindBySourceHash(context.Background(), "p", "local_upload", "s", "h"); err == nil {
        t.Fatal("expected error on nil DB")
    }
}

// real-DB behavior (skips without KG_TEST_DATABASE_URL), in package store_test
func TestCanonicalDocumentStore_UpsertByDraft_SameRowOnReprocess(t *testing.T) {
    db := setupTestDB(t) // skips if KG_TEST_DATABASE_URL unset
    // seed project + draft + knowledge_node rows, then:
    s := store.NewCanonicalDocumentStore(db)
    doc := models.CanonicalDocument{ProjectID: projID, DraftNodeID: draftID,
        KnowledgeNodeID: nodeID, SourceType: "local_upload", SourceID: "upload:1",
        ContentHash: "h1", ExtractionMethod: "native", Metadata: map[string]any{}}
    got, err := s.UpsertByDraft(ctx, doc); require.NoError(t, err)
    doc.ContentHash = "h2"
    got2, err := s.UpsertByDraft(ctx, doc); require.NoError(t, err)
    require.Equal(t, got.ID, got2.ID)        // same row (BR-001.1, ON CONFLICT draft_node_id)
    require.Equal(t, "h2", got2.ContentHash)
}
// + TestCanonicalDocumentStore_FindBySourceHash_RespectsSoftDelete (insert→find hit; set deleted_at→find nil)
```

- [ ] **Step 3: Run, verify fail**

Run: `cd ennam.kg.go && go test ./internal/store/ -run Canonical -v`
Expected: unit tests FAIL (store not defined); real-DB test SKIPs without `KG_TEST_DATABASE_URL`.

- [ ] **Step 4: Implement the store** (`NewCanonicalDocumentStore(db *sql.DB)`). `UpsertByDraft`: `INSERT ... ON CONFLICT (draft_node_id) DO UPDATE SET content_hash=EXCLUDED.content_hash, knowledge_node_id=EXCLUDED.knowledge_node_id, extraction_method=EXCLUDED.extraction_method, metadata=EXCLUDED.metadata, extracted_at=EXCLUDED.extracted_at, updated_at=NOW() RETURNING *`. `FindBySourceHash`: `WHERE project_id=$1 AND source_type=$2 AND source_id=$3 AND content_hash=$4 AND deleted_at IS NULL LIMIT 1` (returns `(nil, nil)` on no rows). Mirror the `database/sql` + JSONB marshal/scan idiom in a sibling store (e.g. `draft_node.go`).

- [ ] **Step 5: Run, verify pass**

Run: `go test ./internal/store/ -run Canonical -v` (unit green; real-DB green locally with `KG_TEST_DATABASE_URL` set, else skipped — note which in the commit).
Expected: PASS/SKIP.

- [ ] **Step 6: Commit**

```bash
git add ennam.kg.go/internal/models/canonical_document.go ennam.kg.go/internal/store/canonical_document.go ennam.kg.go/internal/store/canonical_document_test.go
git commit -m "feat(go): canonical_document model + store (upsert-by-draft, find-by-source-hash)"
```

### Task 1.4: Go internal REST endpoints + wiring for canonical_document

**Files:**
- Create: `ennam.kg.go/internal/handler/canonical_document.go`
- Modify: `ennam.kg.go/cmd/kg-server/main.go`
- Test: `ennam.kg.go/internal/handler/canonical_document_test.go`

**Interfaces:**
- Produces (worker-facing, member+/worker auth — NOT the cut public GETs):
  - `POST /api/v1/projects/{projectId}/canonical-documents` → upsert; body = `models.CanonicalDocument` (sans ids server-fills); returns the row.
  - `GET  /api/v1/projects/{projectId}/canonical-documents/lookup?source_type=&source_id=&content_hash=` → `FindBySourceHash`; 200 with row or 404.

- [ ] **Step 1: Write failing handler test** (httptest, following `internal/handler/*_test.go` patterns) — POST creates and returns 200 with id; GET lookup returns 404 on miss, 200 on hit.

- [ ] **Step 2: Run, verify fail** — `go test ./internal/handler/ -run Canonical -v` → FAIL.

- [ ] **Step 3: Implement handlers** calling the Task 1.3 store; validate `projectId` access exactly like the sibling document handlers (member+); reject unknown `source_type`.

- [ ] **Step 4: Wire routes + store in `main.go`** next to the existing document routes.

- [ ] **Step 5: Run, verify pass + build** — `go test ./internal/handler/ -run Canonical -v && go build ./...` → PASS.

- [ ] **Step 6: Commit**

```bash
git add ennam.kg.go/internal/handler/canonical_document.go ennam.kg.go/internal/handler/canonical_document_test.go ennam.kg.go/cmd/kg-server/main.go
git commit -m "feat(go): canonical_document REST endpoints (upsert + source-hash lookup)"
```

### Task 1.5: `KGClient` methods for canonical_document

**Files:**
- Modify: `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py`
- Test: `ennam.kg.python/tests/ingestion/test_kgclient_canonical.py` (pytest-httpx mocks)

**Interfaces:**
- Produces:
  - `async def upsert_canonical_document(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]` → POST.
  - `async def get_canonical_document_by_source(self, project_id, source_type, source_id, content_hash) -> dict[str, Any] | None` → GET lookup; returns `None` on 404.

- [ ] **Step 1: Write failing test** mocking POST (returns id) and GET (404 → None, 200 → dict), asserting the URL/query shape matches Task 1.4.

- [ ] **Step 2: Run, verify fail** — `uv run pytest tests/ingestion/test_kgclient_canonical.py -v` → FAIL.

- [ ] **Step 3: Implement both methods** next to `get_draft_node`/`update_draft_content` (~:291-340), reusing `self._request`; treat 404 as `None` in the getter.

- [ ] **Step 4: Run, verify pass** — PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py ennam.kg.python/tests/ingestion/test_kgclient_canonical.py
git commit -m "feat(kgclient): canonical_document upsert + source-hash lookup methods"
```

### Task 1.6: Persist canonical_document in `run_batch` (alongside, no reroute yet)

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/pipeline/engine.py` (~:52-120, after `create_node`, before `decompose_document`)
- Test: `ennam.kg.python/tests/ingestion/test_engine_canonical_persist.py`

**Interfaces:**
- Consumes: `build_canonical_document` (1.2), `KGClient.upsert_canonical_document` (1.5). Reads `draft["metadata"]` (JSONB) which carries `original_filename`, `mime_type`, `stored_path`, `upload_id` for uploads (`file_upload.go:250-255`); absent for satellite drafts.
- Produces:
  - Helper `_is_pdf(meta: dict) -> bool`: `True` if `meta.get("mime_type") == "application/pdf"` or `str(meta.get("original_filename","")).lower().endswith(".pdf")`. Satellite (no meta) → `False` → `native`.
  - Helper `_canonical_metadata(draft, canonical) -> dict`: the BR-001.4 envelope — `source_type`, `source_id`, `original_filename` (meta or None), `mime_type` (meta or None), `extraction_method`, `extracted_at`, and `source_metadata` = the remaining draft.metadata (upload_id/stored_path, or satellite caller JSONB).
  - After hub `create_node`, exactly one `upsert_canonical_document` per draft with `knowledge_node_id = node_id`. **Existing flow unchanged** — `decompose_document` still runs as before.

- [ ] **Step 1: Write failing test** (mock `KGClient`) — (a) markdown draft → `upsert_canonical_document` called once with `knowledge_node_id == node_id` and `content_hash == sha256(normalize(content_raw))`; (b) draft whose metadata has `mime_type="application/pdf"` → envelope `extraction_method == "text"`; (c) `EmptyExtractionError` → draft completed `success=False` reason `extraction_empty`, **no** `create_node`/`upsert_canonical_document` (FR-003).

- [ ] **Step 2: Run, verify fail** — FAIL.

- [ ] **Step 3: Implement** — in `run_batch`, after loading the draft, read `meta = draft.get("metadata") or {}`; call `build_canonical_document(raw_text=str(draft.get("content_raw") or ""), content_format=str(draft.get("content_format") or ""), is_pdf=_is_pdf(meta))` inside `try`; on `EmptyExtractionError` `complete_draft_node(success=False, ...)` with the reason and `continue`. After the existing `create_node`, call `upsert_canonical_document(project_id, payload)` with the `_canonical_metadata` envelope. Keep `decompose_document` untouched this task. (The deterministic canonical build runs alongside the existing AI `extract_draft` — they are independent; canonical text/hash/chunks carry no AI.)

- [ ] **Step 4: Run, verify pass + full suite green** — `uv run pytest tests/ -q` → PASS (characterization test from 0.2 still green — no consumer reroute yet).

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/ingestion/pipeline/engine.py ennam.kg.python/tests/ingestion/test_engine_canonical_persist.py
git commit -m "feat(ingest): persist canonical_document in run_batch + fail-loud (FR-001/FR-003)"
```

---

## PHASE 2 — Go cutover + approval-gate (Option A)

> Goal: Go ceases synchronous text extraction; ALL local uploads defer to the worker; the worker extracts-only and does NOT index before approval. **P2 precondition:** backend-lead/PO one-line confirm that binary uploads now wait for approval (Option A). Do not land the cutover commit without it.

### Task 2.1: Worker `handle_extract_upload` becomes extract-only (approval-gate invariant)

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/worker.py` (~:45-89)
- Test: `ennam.kg.python/tests/test_worker_extract_gate.py`

**Interfaces:**
- Produces: `handle_extract_upload` extracts text + `update_draft_content` **only**; it does **not** call `ingestion_engine.run_batch`. Indexing happens via the existing approval-driven `kg_generation` path.

- [ ] **Step 1: Write failing test** (mock `kg_client` + `ingestion_engine`) — invoking `handle_extract_upload` calls `update_draft_content` once and `run_batch` **zero** times.

```python
async def test_extract_upload_does_not_index_before_approval(monkeypatch):
    calls = {"update": 0, "run_batch": 0}
    # wire mocks so kg_client.update_draft_content increments update,
    # ingestion_engine.run_batch increments run_batch
    await handle_extract_upload({"project_id": "p", "draft_node_id": "d", "stored_path": "p/u/f.pdf"})
    assert calls["update"] == 1
    assert calls["run_batch"] == 0  # Option A: gate preserved
```

- [ ] **Step 2: Run, verify fail** — `uv run pytest tests/test_worker_extract_gate.py -v` → FAIL (currently calls run_batch at :75).

- [ ] **Step 3: Implement** — delete the `run_batch` block (`worker.py:70-89`); leave extract + `update_draft_content`. Add a log line: extraction complete, awaiting approval.

- [ ] **Step 4: Run, verify pass** — PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/worker.py ennam.kg.python/tests/test_worker_extract_gate.py
git commit -m "feat(worker): extract-only handler, no index before approval (Option A, FR-002 gate)"
```

### Task 2.2: Go stops synchronous text extraction (delete `extractTextSync`)

**Files:**
- Modify: `ennam.kg.go/internal/service/file_upload.go` (`classifyUploadFile` ~:355, defer branch ~:241, `ContentExtracted` ~:222, delete `extractTextSync` ~:372)
- Test: `ennam.kg.go/internal/service/file_upload_test.go`

**Interfaces:**
- Produces: all upload formats create the draft with `deferExtract=true`, `ContentExtracted=false`, and publish an extract-upload message; no synchronous text decode in Go (NFR-242).

- [ ] **Step 1: Write failing test** — `classifyUploadFile(".md")` returns `deferExtract=true`; uploading a `.md` produces a draft with `ContentExtracted=false` and a published extract message; assert `extractTextSync` symbol is gone (compile-time once deleted).

- [ ] **Step 2: Run, verify fail** — `cd ennam.kg.go && go test ./internal/service/ -run Upload -v` → FAIL (`.md` currently `deferExtract=false`).

- [ ] **Step 3: Implement** — in `classifyUploadFile`, return `deferExtract=true` for `.md/.txt/.json/.csv`; delete the `if !deferExtract { extractTextSync(...) }` branch and the `extractTextSync` function; set `ContentExtracted: false` for all formats.

- [ ] **Step 4: Run, verify pass + build + vet** — `go test ./internal/service/ -run Upload -v && go build ./... && go vet ./...` → PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.go/internal/service/file_upload.go ennam.kg.go/internal/service/file_upload_test.go
git commit -m "feat(go): cease synchronous text extraction; all uploads defer to worker (NFR-242)"
```

---

## PHASE 3 — Contract pin + NFR-247 golden test

> Goal: pin AAA's authoritative read path to the canonical contract and re-point the golden test before any read cutover. **Hard gate:** OQ-009 must be answered by the AAA phase owner before this phase; CTO ratifies. Forbid direct `draft_nodes.content_raw` reads from AAA/DAAB.

### Task 3.1: Pin canonical read field + NFR-247 golden regression

**Files:**
- Create: `ennam.kg.python/tests/ingestion/test_aaa_non_regression.py`
- Modify: `docs/superpowers/specs/2026-06-17-canonical-ingest-core-design.md` (record the pinned field in §7/§12)

**Interfaces:**
- Consumes: the OQ-009 answer (authoritative field: `canonical_document` canonical text + chunk offsets, per the ratified contract).
- Produces: a golden test asserting that, for the Task 0.2 fixtures (md/txt/pdf — the chunked formats AAA consumes), the canonical path reproduces the AAA-authoritative canonical text + chunk char offsets the characterization snapshot captured. (Hub-only formats json/csv/xlsx have no chunks/offsets and are out of this golden.)

- [ ] **Step 1: Record the pinned field** in the spec (one line: "AAA reads canonical text + chunk offsets via `doc_id` → `canonical_document`; `content_raw` direct reads forbidden").

- [ ] **Step 2: Write the golden test** asserting `build_canonical_document` output (canonical_text + each chunk's `content`/`char_start`/`char_end`/`ordinal`) for the md/txt/pdf fixtures matches the Task 0.2 golden content/offsets — i.e. the unified entry point returns the same text + offsets AAA received pre-change (BR-002.6 superset guarantee made concrete).

- [ ] **Step 3: Run, verify pass** — `uv run pytest tests/ingestion/test_aaa_non_regression.py -v` → PASS.

- [ ] **Step 4: Commit**

```bash
git add ennam.kg.python/tests/ingestion/test_aaa_non_regression.py docs/superpowers/specs/2026-06-17-canonical-ingest-core-design.md
git commit -m "test: NFR-247 AAA non-regression golden against pinned canonical contract"
```

---

## PHASE 4 — Content-hash dedup (FR-004)

> Goal: ingest-once. Reuse path (no new chunks/embeddings on byte-identical re-ingest) and content-change regenerate path (replace stale chunks). The regenerate half is the riskiest — most test coverage here.

### Task 4.1: Dedup reuse path in `run_batch`

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/pipeline/engine.py`
- Test: `ennam.kg.python/tests/ingestion/test_dedup.py`

**Interfaces:**
- Consumes: `KGClient.get_canonical_document_by_source` (1.5), `build_canonical_document` (1.2).
- Produces: when an existing non-deleted canonical_document matches `(project_id, source_type, source_id)` **and** `content_hash`, `run_batch` reuses the existing `knowledge_node_id`, performs **no** `create_node`/`decompose`/embedding writes, completes the draft `success=True`, and increments a `reused` counter.

- [ ] **Step 1: Write failing test** — second `run_batch` of byte-identical content for the same source makes **zero** `create_node` and **zero** `upsert_node_embeddings` calls, and reuses the prior `knowledge_node_id` (NFR-243).

- [ ] **Step 2: Run, verify fail** — FAIL.

- [ ] **Step 3: Implement** — after `build_canonical_document`, call `get_canonical_document_by_source(...)`; on hit, complete the draft with the existing `knowledge_node_id` and `continue` (skip create/decompose).

- [ ] **Step 4: Run, verify pass** — PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/ingestion/pipeline/engine.py ennam.kg.python/tests/ingestion/test_dedup.py
git commit -m "feat(ingest): content-hash dedup reuse path (FR-004 BR-004.2, NFR-243)"
```

### Task 4.2a: Document-subtree delete capability (Go store + endpoint + client)

> **New capability — verified missing.** There is no node-delete method in `KGClient` and no node DELETE route in Go. The regenerate path needs to remove a document's stale section+chunk nodes. We hard-delete them so `knowledge_node_embeddings` (FK `ON DELETE CASCADE`, migration 000055) cleans up automatically — no orphan embeddings.

**Files:**
- Modify: `ennam.kg.go/internal/store/node.go` (add `DeleteDocumentSubtree`)
- Modify: `ennam.kg.go/internal/handler/canonical_document.go` (add route) + `cmd/kg-server/main.go`
- Modify: `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py`
- Test: `ennam.kg.go/internal/store/node_test.go` (nil-DB + `setupTestDB`-gated), `ennam.kg.python/tests/ingestion/test_kgclient_canonical.py` (add case)

**Interfaces:**
- Produces:
  - Go `store.NodeStore.DeleteDocumentSubtree(ctx, projectID, hubNodeID string) (int, error)` — `DELETE FROM knowledge_nodes WHERE project_id=$1 AND node_type IN ('document_section','document_chunk') AND properties->>'document_id' = $2` (cascades embeddings). Returns rows deleted.
  - Route `DELETE /api/v1/projects/{projectId}/documents/{docId}/subtree` (member+/worker auth, same as the other worker-called routes).
  - `KGClient.delete_document_subtree(self, project_id, document_id) -> int`.

- [ ] **Step 1: Write failing tests** — Go: nil-DB error test + `setupTestDB`-gated test asserting that after seeding a hub + 2 chunks + their embeddings, `DeleteDocumentSubtree` removes the chunks AND their embedding rows (cascade), leaving the hub. Python: mock the DELETE call, assert URL shape + returned count.

- [ ] **Step 2: Run, verify fail** — `go test ./internal/store/ -run Subtree -v` and `uv run pytest tests/ingestion/test_kgclient_canonical.py -v` → FAIL.

- [ ] **Step 3: Implement** the store method, the route/handler, the wiring, and the client method.

- [ ] **Step 4: Run, verify pass + build** — `go build ./... && go test ./internal/store/ -run Subtree -v` and pytest → PASS/SKIP.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.go/internal/store/node.go ennam.kg.go/internal/store/node_test.go ennam.kg.go/internal/handler/canonical_document.go ennam.kg.go/cmd/kg-server/main.go ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py ennam.kg.python/tests/ingestion/test_kgclient_canonical.py
git commit -m "feat(go): delete-document-subtree (hard delete, cascades embeddings) for regenerate"
```

### Task 4.2b: Content-change regenerate path (replace stale chunks)

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/pipeline/engine.py`
- Test: `ennam.kg.python/tests/ingestion/test_dedup.py` (add cases)

**Interfaces:**
- Consumes: `KGClient.delete_document_subtree` (4.2a), `KGClient.get_canonical_document_by_source` (1.5).
- Produces: when `(project_id, source_type, source_id)` matches an existing canonical_document but `content_hash` **differs**, `run_batch` calls `delete_document_subtree(project_id, existing_knowledge_node_id)` to remove stale sections+chunks (+cascaded embeddings) **before** re-decomposing, updates the canonical_document (`upsert_canonical_document`), and regenerates chunks against the existing hub node (NFR-244).

- [ ] **Step 1: Write failing tests** (mock `KGClient`) — (a) changed content → `delete_document_subtree` called once with the existing hub id, then decompose produces the new chunk set, and `content_hash` updates; (b) the reused-hub path keeps the same `knowledge_node_id` (hub not recreated); (c) no second canonical_document row (upsert, not insert).

- [ ] **Step 2: Run, verify fail** — FAIL.

- [ ] **Step 3: Implement** — extend the dedup branch from 4.1: on `get_canonical_document_by_source` hit with **differing** hash, take the existing `knowledge_node_id`, call `delete_document_subtree`, `upsert_canonical_document` (new hash/metadata), then run the FR-006 decompose against that hub id. (On hash **match** → reuse, Task 4.1. On **no** existing row → normal create path.)

- [ ] **Step 4: Run, verify pass** — PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/ingestion/pipeline/engine.py ennam.kg.python/tests/ingestion/test_dedup.py
git commit -m "feat(ingest): content-change regenerate path, no orphan chunks/embeddings (FR-004 BR-004.3, NFR-244)"
```

---

## PHASE 5 — Single chunk producer (FR-006) — LAST

> Goal: `decompose_document` consumes the canonical chunk list instead of re-parsing. This is the heavy, non-additive restructure — done last, on a trusted canonical surface. **Floor:** never before Phase 0.

### Task 5.1: Route canonical chunks into `decompose_document`

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/pipeline/decompose.py` (~:57 parse, ~:135 chunk loop)
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/pipeline/engine.py` (pass the canonical chunk list/sections into `decompose_document`)
- Test: `ennam.kg.python/tests/ingestion/test_decompose_canonical.py`

**Interfaces:**
- Consumes: the `CanonicalDocument` (sections + chunks + tree) built in `run_batch` (1.2/1.6), plus the existing `extraction: ExtractionResult` (still needed for the concept loop, `decompose.py:187-236`).
- Produces: `decompose_document(kg, *, project_id, hub_node_id, draft, extraction, node_type, canonical)` creates `document_section` + `document_chunk` nodes from `canonical`; it does **NOT** call `parse_markdown_sections` or `chunk_section` (NFR-248). It maps each section's `local_id` → persisted section node id, then for each `CanonicalChunk` stamps the final `chunk_key = f"{section_node_id}:{chunk.ordinal}"`, `section_id = section_node_id`, `document_id = hub_node_id`. `document_chunk` property shape unchanged (no `context_header` — FR-005 cut). The `## Page N` markers in extracted-PDF text survive unchanged (`files.py:64`). Hub `document_tree`/`section_count` set from `canonical.tree`/`len(canonical.sections)`. Concept loop and **both** embedding streams preserved (section summary `f"{title}\\n{summary}"` and each chunk body — `decompose.py:131,184`).

- [ ] **Step 1: Write failing tests** — (a) N canonical chunks → exactly N `document_chunk` nodes; each `chunk_key == f"{its_section_node_id}:{ordinal}"` and offsets equal the canonical chunk's; (b) NFR-248 code-path assertion: monkeypatch `parse_markdown_sections` and `chunk_section` in the decompose module to raise — `decompose_document` must still succeed (proving it re-parses nothing); (c) `document_chunk` properties have no `context_header`; (d) embeddings upserted for both section nodes and chunk nodes (count = sections + chunks).

- [ ] **Step 2: Run, verify fail** — `uv run pytest tests/ingestion/test_decompose_canonical.py -v` → FAIL.

- [ ] **Step 3: Implement** — add `canonical: CanonicalDocument` to `decompose_document`'s signature (**keep** `extraction`); delete the `parse_markdown_sections`/`build_document_tree_json` calls at :57-58 and the inline `chunk_section` loop at :135 (its body that creates chunk nodes is retained but now iterates `canonical.chunks`). Persist hub tree from `canonical.tree`. Create section nodes by iterating `canonical.sections` (using `section_path`/`text`/`level`/line offsets), recording `local_id → node_id` in a dict and the parent-stack edges as today. Then iterate `canonical.chunks`: resolve `section_node_id = local_map[chunk.section_local_id]`, create the `document_chunk` node with `chunk_key=f"{section_node_id}:{chunk.ordinal}"`, `section_id=section_node_id`, `document_id=hub_node_id`, and the existing offset/content/hash properties. Keep the concept loop and the dual embedding loop (section + chunk, 384-dim, unchanged model) exactly as today. The early-return format gate at :47-55 is now redundant (canonical already gated chunking) — leave the hub-only short-circuit so non-text drafts with empty `canonical.sections` create no sections, matching today. Update `run_batch` (engine) to pass `canonical=` through to `decompose_document`.

- [ ] **Step 4: Run, verify pass + FULL suite incl. characterization** — `uv run pytest tests/ -q`. The Task 0.2 characterization golden (md/txt/pdf chunk content + offsets) must still pass: the canonical path runs the same `parse_markdown_sections`/`chunk_section` logic on the same text, so chunk content/offsets/ordinals are unchanged. (Normalization is a no-op for the LF, no-trailing-whitespace fixtures; if a fixture legitimately changes under normalization, that's a real divergence to investigate, not a golden to silently bump.)

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/ingestion/pipeline/decompose.py ennam.kg.python/src/ennam_kg/ingestion/pipeline/engine.py ennam.kg.python/tests/ingestion/test_decompose_canonical.py
git commit -m "feat(ingest): single chunk producer — decompose consumes canonical chunks (FR-006/NFR-248)"
```

### Task 5.2: Full verification pass + lint

- [ ] **Step 1: Python** — `cd ennam.kg.python && uv run pytest tests/ -q && uv run ruff check src/ tests/`
- [ ] **Step 2: Go** — `cd ennam.kg.go && go test ./... && go build ./... && go vet ./... && make lint`
- [ ] **Step 3: Confirm NFR coverage** — NFR-239 (cross-path), NFR-240 (determinism), NFR-241/249 (fail-loud), NFR-242 (no Go extraction), NFR-243/244 (dedup), NFR-247 (AAA golden), NFR-248 (single producer) each have a green test.
- [ ] **Step 4: Commit any lint fixes**

```bash
git commit -am "chore: lint + final verification for BA-030 canonical ingest core"
```

---

## Plan Self-Review

- **Spec coverage:** FR-001 (1.3/1.4/1.6), FR-002 (1.1/1.2/2.1/2.2), FR-003 (1.2/1.6), FR-004 (4.1/4.2), FR-006 (5.1). Normalization (NFR-239) → 1.1. Approval gate → 2.1. Migration 000060 → 0.1. Characterization → 0.2. NFR-247 pin → 3.1. FR-005 + GET endpoints correctly **absent** (cut).
- **Cross-service surface** (worker→Go for canonical_document) is fully covered: store (1.3), endpoints (1.4), client (1.5), use (1.6) — this was under-specified in the BA and is made explicit here.
- **Verified against code (2026-06-17, 3 review passes):** migrate target is `make db-migrate` (not `migrate-up`); `is_pdf` derives from `draft.metadata` (`original_filename`/`mime_type`, set at `file_upload.go:250-255`), **not** `content_format` (which is `plain_text` for PDFs); `chunk_key` embeds the persisted section-node UUID, so the builder emits provisional `(section_local_id, ordinal)` and `decompose` stamps the final key (label-only, preserves NFR-248); `decompose_document` keeps its `extraction` param (concept loop) and both embedding streams; json/csv/xlsx remain hub-only per the chunkable-format gate; draft node types are only `document`/`external`/`dataset` (all valid canonical-doc hubs).
- **Test conventions matched:** Go simple stores → nil-DB unit tests; SQL behavior → `setupTestDB(t)`-gated real-DB tests that skip without `KG_TEST_DATABASE_URL` (per `node_embedding_test.go`). Python → pytest with mocked `KGClient`.
- **FR-004 regenerate gap closed:** there was no node-delete API (no `KGClient` method, no Go route). Task 4.2a adds `DeleteDocumentSubtree` + route + client method; hard delete cascades `knowledge_node_embeddings` (FK `ON DELETE CASCADE`) → no orphan embeddings. This was the riskiest half the CTO flagged.
- **Type consistency:** `CanonicalDocument`/`CanonicalChunk`/`CanonicalSection` defined in 1.2 (chunks carry `section_local_id`+`ordinal`, no final key) and consumed in 1.6/4.x/5.1; `upsert_canonical_document`/`get_canonical_document_by_source` defined in 1.5, used in 1.6/4.1; `UpsertByDraft`/`FindBySourceHash` defined in 1.3, used in 1.4.
- **Sequencing guards:** P5 (FR-006) is last; P2 cutover gated on the PO confirm; P3 gated on OQ-009. Characterization guard (0.2) precedes every refactor.

## Known Preconditions (carry into execution)
1. **P2:** backend-lead/PO confirm binaries-now-wait (Option A). 
2. **P3:** AAA phase owner answers OQ-009 (authoritative read field); CTO ratifies.
3. Both are cheap conversations, not engineering blockers — P0/P1 proceed without them.
