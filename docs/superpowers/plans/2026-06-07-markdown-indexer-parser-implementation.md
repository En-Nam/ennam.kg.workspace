# Markdown Parser for `ennam-kg-indexer` (repo indexing) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `MarkdownParser` to `ennam-kg-indexer` so `.md`/`.markdown` files in an indexed repo are parsed into `document` (one hub per file) + `document_section` (one per heading) knowledge nodes, with `contains_section` containment edges — via the existing `kg_index_source`/CLI flow. Today `.md` has no parser → `get_parser` returns `None` → markdown is silently skipped.

**Architecture:** New `parsers/markdown.py` (`MarkdownParser(BaseParser)`) walks the tree-sitter `markdown` AST: one `DOCUMENT` hub symbol per file (name = basename) + one `SECTION` symbol per heading section, nested via the `parent` field. `base.py` gains two `SymbolKind` values and two `Symbol` fields. `extractor.py` gets a document branch in `symbol_to_node` (doc property shape, preserving the shared natural-key invariants) and a `contains_section` relationship in `extract_edges`. Engine/differ/scanner are unchanged — registering the parser is sufficient for discovery, and the repo-relative path / `repo_key` / archive model already works.

**Tech Stack:** Python 3.12, `tree-sitter>=0.25.2`, `tree-sitter-language-pack` (provides the `markdown` grammar — **new dependency**), pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-06-07-markdown-indexer-parser-design.md` (Approved). All grammar node types/fields and Go-side schema/edge-whitelist facts below were verified empirically on 2026-06-07 (grammar via an ephemeral `tree-sitter-language-pack` install; Go schemas read from `ennam.kg.go/config/config.yaml`).

---

## Clarifications beyond the spec's literal text (read first)

Empirical verification surfaced two points the spec under-specifies. Both are folded into this plan:

1. **`Symbol` needs `level` and `content` fields.** The spec's `base.py` note only mentions adding `SymbolKind` values, but `document_section` nodes carry `level` (1–6) and `content` (section body), and `Symbol` has neither field today. Task 1 adds two minimal, backward-compatible fields (`level: int | None = None`, `content: str = ""`). Code parsers ignore them (defaults).

2. **Doc nodes MUST carry `properties.repo_path`.** `engine.full_scan` calls the differ with `archive_scope="repo"` (verified `engine.py:69`), and the differ skips existing nodes whose `props["repo_path"] != repo_key` (verified `differ.py:91-93`). Without `repo_path`, re-indexing a repo would re-create every section (duplicates) and never archive removed ones. Task 6 sets `repo_path = repo_key` on both hub and section payloads — matching what code nodes already do (`extractor.py:81`).

### Verified grammar facts (do not re-guess)

- `document` → child `section` nodes (nested). Each heading `section` starts with an `atx_heading`; deeper headings are **child `section`s** of it.
- `atx_heading` children: `atx_h{N}_marker` (N = 1..6) + `inline` (the clean heading text, no `#`, no trailing newline).
- **Nesting:** `## A` under `# Title` is a child section of `# Title`'s section. Two `# H1`s are **sibling** sections at document level. Leading text before any heading is a **headingless** `section` (preamble).
- A `#` inside a fenced code block is `code_fence_content`, **not** a heading → no section.
- `setext_heading` (`===`/`---` underline form) produces a `setext_heading` node with **no** `atx_heading` child → treated as headingless → **skipped in v1** (spec Out-of-Scope; noted in Task 4).

### Verified Go-side invariants (do not break)

- Natural key (engine.py:194, differ.py:37/101): `f"{properties.file_path}:{title.split(': ',1)[-1]}:{properties.kind}"`. So `title` **must** stay `f"{kind.value}: {name}"` and `properties.kind` **must** stay `kind.value`. A colon-containing heading round-trips because split uses `maxsplit=1`.
- Differ archive scope is filtered to `created_by == "python-indexer"` (differ.py:89) → indexer never touches ingestion-created doc nodes.
- `document_section` schema (`config.yaml:248`): `required:[title]`; optional `summary`(≤8000), `content`(≤50000), `document_id`, `line_start`, `line_end`, `level`. `document` schema (`config.yaml:208`): `required:[title]`; optional `summary`(≤50000), `source_url`. Gate 1 validates declared fields + `required` and **tolerates extra JSONB properties** (so `kind`/`file_path`/`body_hash`/`repo_path` are fine).
- Edge whitelist (`config.yaml:585-597`): only `document --contains_section--> document_section` and `document_section --contains_section--> document_section`. Sending `relates_to` for these → Gate 1 422.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `packages/ennam-kg-indexer/pyproject.toml` | Declare `tree-sitter-language-pack`, bump `tree-sitter>=0.25.2` | **Modify** (deps block, lines 7–14) |
| `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/base.py` | `SymbolKind.DOCUMENT`/`SECTION` + `Symbol.level`/`content` | **Modify** |
| `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/markdown.py` | `MarkdownParser` — markdown AST → `list[Symbol]` | **Create** |
| `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/__init__.py` | Register + export `MarkdownParser` | **Modify** |
| `packages/ennam-kg-indexer/src/ennam_kg_indexer/indexer/extractor.py` | Doc-node property shape + `contains_section` edges | **Modify** |
| `packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py` | All `MarkdownParser` + extractor + integration tests | **Create** |

Paths are relative to the workspace root. All commands run from `ennam.kg.python/` (the `uv` project root — referred to below as `$PY`).

### Mirror references (read before starting)

- `parsers/python_lang.py` / `parsers/go_lang.py` — parser shape (helpers, error handling, dispatch).
- `parsers/base.py` — `Symbol` + `SymbolKind`.
- `indexer/extractor.py` — `symbol_to_node` (lines 35–83) and `extract_edges` (lines 85–156).
- `tests/test_engine_relative_paths.py` — the mocked-`full_scan` integration test pattern (Task 8 mirrors it).

---

## Task 1: Dependency + base.py (SymbolKind + Symbol fields)

Add the markdown grammar dependency and extend `base.py` with the two doc kinds and the two carrier fields.

**Files:**
- Modify: `packages/ennam-kg-indexer/pyproject.toml`
- Modify: `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/base.py`
- Test: inline below (a tiny `base.py` assertion, no new test file yet)

- [ ] **Step 1: Add the dependency to pyproject.toml**

In `packages/ennam-kg-indexer/pyproject.toml`, replace the dependencies block (lines 6–14):

```toml
dependencies = [
    "tree-sitter>=0.25.2",
    "tree-sitter-typescript>=0.23",
    "tree-sitter-python>=0.23",
    "tree-sitter-go>=0.23",
    "tree-sitter-language-pack>=0.9",
    "pathspec>=0.12",
    "httpx>=0.28",
    "pydantic>=2.7",
]
```

- [ ] **Step 2: Sync the environment**

Run: `cd $PY && uv sync`
Expected: resolves and installs `tree-sitter-language-pack` and `tree-sitter>=0.25.2`, no errors. Then verify the grammar loads:

Run: `cd $PY && uv run python -c "from tree_sitter_language_pack import get_language; get_language('markdown'); print('markdown grammar OK')"`
Expected: `markdown grammar OK`

- [ ] **Step 3: Write the failing assertion for the enum + fields**

Run this one-liner to confirm the new symbols do **not** yet exist:

Run: `cd $PY && uv run python -c "from ennam_kg_indexer.parsers.base import SymbolKind, Symbol; print(SymbolKind.DOCUMENT, SymbolKind.SECTION)"`
Expected: FAIL with `AttributeError: DOCUMENT`

- [ ] **Step 4: Extend `SymbolKind` and `Symbol` in base.py**

In `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/base.py`, add two members to `SymbolKind` (after `WIDGET = "widget"`):

```python
    WIDGET = "widget"  # Flutter
    DOCUMENT = "document"  # Markdown file hub (indexed docs)
    SECTION = "document_section"  # Markdown heading section
```

Add two fields to the `Symbol` dataclass (after the `imports` field):

```python
    imports: list[str] = field(default_factory=list)  # What this symbol imports/references
    level: int | None = None  # Heading level 1-6 (markdown sections)
    content: str = ""  # Section body text (markdown); empty for code symbols
```

- [ ] **Step 5: Verify the enum + fields exist and map correctly**

Run:

```bash
cd $PY && uv run python -c "
from ennam_kg_indexer.parsers.base import SymbolKind, Symbol
from ennam_kg_indexer.indexer.extractor import map_kind_to_type
assert map_kind_to_type(SymbolKind.DOCUMENT) == 'document'
assert map_kind_to_type(SymbolKind.SECTION) == 'document_section'
s = Symbol(name='x', kind=SymbolKind.SECTION, file_path='a.md', line_start=1, line_end=2, level=2, content='hi')
assert s.level == 2 and s.content == 'hi'
print('OK')
"
```

Expected: `OK` — confirms `map_kind_to_type` falls back to `kind.value` for the new kinds (no `_KIND_TO_TYPE` entry needed) and the carrier fields work.

- [ ] **Step 6: Commit**

```bash
git add packages/ennam-kg-indexer/pyproject.toml \
        packages/ennam-kg-indexer/uv.lock \
        packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/base.py
git commit -m "feat(indexer): add markdown grammar dep + DOCUMENT/SECTION kinds and Symbol level/content fields"
```

> Note: commit `uv.lock` only if your repo tracks it (it normally should). If `uv.lock` lives at the `$PY` root rather than the package dir, adjust the path.

---

## Task 2: MarkdownParser skeleton + document hub + registration

Establish the parser file: language, constructor, `parse()` emitting the per-file `DOCUMENT` hub, the section-walk scaffold (no section symbols yet), shared helpers, and registry wiring. End-to-end slice: any `.md` produces exactly one `DOCUMENT` hub named after the basename.

**Files:**
- Create: `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/markdown.py`
- Modify: `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/__init__.py`
- Create: `packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py`:

```python
"""Tests for the Markdown parser (repo-indexing flow)."""

from __future__ import annotations

from pathlib import Path

from ennam_kg_indexer.parsers import SymbolKind, get_parser
from ennam_kg_indexer.parsers.markdown import MarkdownParser


def _write(tmp_path: Path, body: str, name: str = "notes.md") -> Path:
    f = tmp_path / name
    f.write_text(body)
    return f


def test_parser_registered(tmp_path: Path) -> None:
    parser = get_parser(_write(tmp_path, "# Hi\n"))
    assert parser is not None
    assert isinstance(parser, MarkdownParser)


def test_supported_extensions() -> None:
    assert MarkdownParser().supported_extensions() == {".md", ".markdown"}


def test_document_hub_is_basename_not_h1(tmp_path: Path) -> None:
    # Hub name is the file basename, NOT the first H1 (a file may have 0 or many H1s).
    f = _write(tmp_path, "# Title\n\nbody\n", name="notes.md")
    symbols = MarkdownParser().parse(f)
    hubs = [s for s in symbols if s.kind == SymbolKind.DOCUMENT]
    assert len(hubs) == 1
    assert hubs[0].name == "notes.md"
    assert hubs[0].parent is None
    assert hubs[0].body_hash


def test_no_heading_file_one_hub_zero_sections(tmp_path: Path) -> None:
    f = _write(tmp_path, "just prose here\n\nmore prose\n")
    symbols = MarkdownParser().parse(f)
    assert len([s for s in symbols if s.kind == SymbolKind.DOCUMENT]) == 1
    assert len([s for s in symbols if s.kind == SymbolKind.SECTION]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ennam_kg_indexer.parsers.markdown'`

- [ ] **Step 3: Create `markdown.py` with skeleton, hub, and helpers**

Create `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/markdown.py`:

```python
"""Markdown parser using the tree-sitter `markdown` grammar (language-pack).

Indexes .md files into a `document` hub (one per file) + `document_section`
symbols (one per heading), nested via the `parent` field. Structural only —
no embedding (that is a shared server-side concern).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from tree_sitter import Parser
from tree_sitter_language_pack import get_language

from .base import BaseParser, Symbol, SymbolKind

logger = logging.getLogger(__name__)

DOC_LANGUAGE = get_language("markdown")


class MarkdownParser(BaseParser):
    """Extracts a document hub + heading sections from markdown files."""

    def __init__(self) -> None:
        self._parser = Parser(DOC_LANGUAGE)

    def supported_extensions(self) -> set[str]:
        return {".md", ".markdown"}

    def parse(self, file_path: Path) -> list[Symbol]:
        try:
            source = file_path.read_bytes()
        except OSError:
            logger.warning("Could not read file: %s", file_path)
            return []

        tree = self._parser.parse(source)
        if tree.root_node.has_error:
            logger.warning("Parse errors in %s — extracting what we can", file_path)

        fp = str(file_path)
        basename = file_path.name
        symbols: list[Symbol] = []

        # One document hub per file. name = basename (NOT the first H1 — unstable).
        # body_hash = whole-file hash, so any edit re-touches the hub.
        # content = preamble text (leading headingless section), if any.
        root = tree.root_node
        symbols.append(
            Symbol(
                name=basename,
                kind=SymbolKind.DOCUMENT,
                file_path=fp,
                line_start=1,
                line_end=root.end_point[0] + 1,
                body_hash=hashlib.sha256(source).hexdigest(),
                parent=None,
                content=self._preamble(root, source),
            )
        )

        # Walk top-level sections; their parent is the hub basename.
        for child in root.children:
            if child.type == "section":
                self._walk_section(child, source, fp, basename, symbols)
        return symbols

    # ------------------------------------------------------------------
    # Traversal (section symbols added in Task 3/4)
    # ------------------------------------------------------------------

    def _walk_section(
        self,
        section: object,
        source: bytes,
        fp: str,
        parent: str,
        symbols: list[Symbol],
    ) -> None:
        """Emit a SECTION for a heading section; recurse into child sections.

        Section-symbol emission is added in Task 3; for now this is a no-op
        scaffold so the hub-only slice works.
        """
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _preamble(self, root: object, source: bytes) -> str:
        """Text of the first leading headingless top-level section, else ''."""
        for child in root.children:  # type: ignore[attr-defined]
            if child.type == "section" and self._heading(child) is None:  # type: ignore[attr-defined]
                return self._text(child, source)
        return ""

    def _heading(self, section: object) -> object | None:
        """The section's child `atx_heading`, or None (headingless / setext)."""
        for child in section.children:  # type: ignore[attr-defined]
            if child.type == "atx_heading":  # type: ignore[attr-defined]
                return child
        return None

    def _text(self, node: object, source: bytes) -> str:
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")  # type: ignore[attr-defined]
```

- [ ] **Step 4: Register the parser**

In `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/__init__.py`:

Add the import (after the go import):

```python
from .go_lang import GoParser
from .markdown import MarkdownParser
from .python_lang import PythonParser
```

Add `"MarkdownParser",` to `__all__` (alphabetical, after `"GoParser"`):

```python
__all__ = [
    "BaseParser",
    "DartParser",
    "GoParser",
    "MarkdownParser",
    "PythonParser",
    "Symbol",
    "SymbolKind",
    "TypeScriptParser",
    "get_parser",
]
```

Add the registration (after `_register(GoParser)`):

```python
_register(GoParser)
_register(MarkdownParser)
```

- [ ] **Step 5: Fix pre-existing tests that assumed `.md` is unsupported**

Registering `MarkdownParser` makes `.md` a **supported** extension. Three existing tests used `.md`/`readme.md` as their canonical *unsupported* file and now fail (verified: `test_scanner.py::test_discover_files_finds_fixtures`, `test_scanner.py::test_filter_changed`, `test_engine.py::TestIncrementalScan::test_skips_unsupported_files`). Update them — `.md` is now discovered, so flip those assertions and use a genuinely-unsupported extension (`.json`/`.xml`) for the "skips unsupported" cases.

In `packages/ennam-kg-indexer/tests/test_parsers/test_scanner.py`:

```python
    assert "readme.md" in names  # .md now supported (MarkdownParser)
```

(replacing `assert "readme.md" not in names`), and:

```python
    assert ".md" in exts  # .md now supported (MarkdownParser)
```

(replacing `assert ".md" not in exts`).

In `packages/ennam-kg-indexer/tests/test_engine.py`, the incremental "skips unsupported" test — replace the changed-paths list so both entries are still unsupported:

```python
            "proj-1", str(fixtures_dir), ["data.json", "data.xml"]
```

(replacing `["readme.md", "data.json"]`). The `files_scanned == 0` / `symbols_found == 0` assertions stay.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py packages/ennam-kg-indexer/tests/test_parsers/test_scanner.py packages/ennam-kg-indexer/tests/test_engine.py -v`
Expected: PASS — the 4 new markdown tests plus the updated scanner/engine tests. (Running the full suite here also works and should be green.)

- [ ] **Step 7: Commit**

```bash
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/markdown.py \
        packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/__init__.py \
        packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py \
        packages/ennam-kg-indexer/tests/test_parsers/test_scanner.py \
        packages/ennam-kg-indexer/tests/test_engine.py
git commit -m "feat(indexer): MarkdownParser skeleton + hub + registration; update tests that assumed .md unsupported"
```

---

## Task 3: Heading sections — name, level, content, body_hash

Implement `_walk_section` to emit a `SECTION` symbol for each heading-bearing section: name = heading inline text, level from the marker, content + body_hash from the section's **own range** (heading start → first child section's start, else section end) so editing a subsection doesn't cascade-dirty its parent.

**Files:**
- Modify: `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/markdown.py`
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_markdown.py`:

```python
def test_sections_name_level_content(tmp_path: Path) -> None:
    f = _write(tmp_path, "# Title\n\n## Section A\n\ntext of A\n\n### Sub A1\n\nsub body\n")
    symbols = MarkdownParser().parse(f)
    secs = {s.name: s for s in symbols if s.kind == SymbolKind.SECTION}
    assert {"Title", "Section A", "Sub A1"} <= set(secs)
    assert secs["Title"].level == 1
    assert secs["Section A"].level == 2
    assert secs["Sub A1"].level == 3
    # Own-range content: Section A holds its own body but NOT Sub A1's body.
    assert "text of A" in secs["Section A"].content
    assert "sub body" not in secs["Section A"].content
    assert "sub body" in secs["Sub A1"].content
    assert secs["Section A"].body_hash
    # line span
    assert secs["Section A"].line_start >= 1
    assert secs["Section A"].line_end >= secs["Section A"].line_start


def test_own_range_isolates_subsection_hash(tmp_path: Path) -> None:
    # Editing a subsection must NOT change the parent's body_hash (own-range only).
    base = "## A\n\nparent body\n\n### B\n\n{child}\n"
    h1 = next(s for s in MarkdownParser().parse(_write(tmp_path, base.format(child="one")))
              if s.name == "A").body_hash
    h2 = next(s for s in MarkdownParser().parse(_write(tmp_path, base.format(child="two")))
              if s.name == "A").body_hash
    assert h1 == h2, "parent A's hash must be stable when only child B changes"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py -k "sections_name or own_range" -v`
Expected: FAIL — `_walk_section` is a no-op, so no SECTION symbols exist (`KeyError`/`StopIteration`).

- [ ] **Step 3: Implement `_walk_section` + heading helpers**

In `markdown.py`, replace the `_walk_section` no-op scaffold with:

```python
    def _walk_section(
        self,
        section: object,
        source: bytes,
        fp: str,
        parent: str,
        symbols: list[Symbol],
    ) -> None:
        """Emit a SECTION for a heading section; recurse into child sections.

        A headingless section (preamble / setext) emits nothing but still
        recurses into any well-formed child sections (carrying `parent` down).
        """
        heading = self._heading(section)
        if heading is None:
            for child in section.children:  # type: ignore[attr-defined]
                if child.type == "section":  # type: ignore[attr-defined]
                    self._walk_section(child, source, fp, parent, symbols)
            return

        name = self._heading_text(heading, source)
        if not name:
            # Malformed heading (no resolvable text) — skip, but recurse.
            for child in section.children:  # type: ignore[attr-defined]
                if child.type == "section":  # type: ignore[attr-defined]
                    self._walk_section(child, source, fp, parent, symbols)
            return

        start_byte, end_byte = self._own_range(section)
        own = source[start_byte:end_byte]
        symbols.append(
            Symbol(
                name=name,
                kind=SymbolKind.SECTION,
                file_path=fp,
                line_start=section.start_point[0] + 1,  # type: ignore[attr-defined]
                line_end=section.end_point[0] + 1,  # type: ignore[attr-defined]
                body_hash=hashlib.sha256(own).hexdigest(),
                parent=parent,
                level=self._heading_level(heading),
                content=own.decode("utf-8", errors="replace"),
            )
        )

        # Child sections nest under this heading's name.
        for child in section.children:  # type: ignore[attr-defined]
            if child.type == "section":  # type: ignore[attr-defined]
                self._walk_section(child, source, fp, name, symbols)
```

Add these helpers after `_heading`:

```python
    def _heading_text(self, heading: object, source: bytes) -> str:
        """The heading's `inline` text (no `#`, trimmed), or '' if none."""
        for child in heading.children:  # type: ignore[attr-defined]
            if child.type == "inline":  # type: ignore[attr-defined]
                return self._text(child, source).strip()
        return ""

    def _heading_level(self, heading: object) -> int | None:
        """Heading level from the `atx_h{N}_marker` child, or None."""
        for child in heading.children:  # type: ignore[attr-defined]
            ctype = child.type  # type: ignore[attr-defined]
            if ctype.startswith("atx_h") and ctype.endswith("_marker"):
                digit = ctype[len("atx_h") :].split("_")[0]
                if digit.isdigit():
                    return int(digit)
        return None

    def _own_range(self, section: object) -> tuple[int, int]:
        """Byte range of a section's own content: start → first child section
        start (else section end), so a subsection edit doesn't dirty the parent."""
        for child in section.children:  # type: ignore[attr-defined]
            if child.type == "section":  # type: ignore[attr-defined]
                return section.start_byte, child.start_byte  # type: ignore[attr-defined]
        return section.start_byte, section.end_byte  # type: ignore[attr-defined]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py -v`
Expected: PASS (all Task 2 + Task 3 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/markdown.py \
        packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py
git commit -m "feat(indexer): MarkdownParser heading-section extraction with own-range content/hash"
```

---

## Task 4: Hierarchy / parent + grammar edge cases

Lock the parent linkage (top sections → hub basename, nested → enclosing heading), and the edge cases: multiple H1s, preamble skip, code-fence-is-not-a-heading. (Implementation already handles these from Task 3; this task is regression tests, with a fix only if one fails.)

**Files:**
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py`
- Modify (only if a test fails): `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/markdown.py`

- [ ] **Step 1: Write the tests**

Append to `test_markdown.py`:

```python
def test_hierarchy_parents(tmp_path: Path) -> None:
    f = _write(tmp_path, "# Title\n\n## Section A\n\n### Sub A1\n\nx\n", name="notes.md")
    secs = {s.name: s for s in MarkdownParser().parse(f) if s.kind == SymbolKind.SECTION}
    assert secs["Title"].parent == "notes.md"      # top-level → hub basename
    assert secs["Section A"].parent == "Title"      # nested under H1
    assert secs["Sub A1"].parent == "Section A"     # nested under H2


def test_multiple_h1_and_preamble(tmp_path: Path) -> None:
    # Preamble (text before any heading) → no section. Two H1s → both top-level.
    f = _write(tmp_path, "Preamble text here.\n\n# A\n\nx\n\n# B\n\ny\n", name="notes.md")
    symbols = MarkdownParser().parse(f)
    secs = {s.name: s for s in symbols if s.kind == SymbolKind.SECTION}
    assert not any("Preamble" in s.name for s in symbols if s.kind == SymbolKind.SECTION)
    assert secs["A"].parent == "notes.md"
    assert secs["B"].parent == "notes.md"


def test_code_fence_is_not_a_heading(tmp_path: Path) -> None:
    f = _write(tmp_path, "# T\n\n## S\n\n```go\n# not a heading\n```\n")
    symbols = MarkdownParser().parse(f)
    assert not any(s.name == "not a heading" for s in symbols)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py -k "hierarchy or multiple_h1 or code_fence" -v`
Expected: PASS — the Task 3 recursion already threads `parent` correctly (top sections get the hub basename, nested get the enclosing heading), the preamble section is headingless (skipped), and `# not a heading` parses as `code_fence_content`, never a section. If any FAILS, the recursion's `parent` threading or the `_heading` check regressed — fix `_walk_section`, do not change the test.

> **Setext headings:** a `Title\n=====` heading produces a `setext_heading` node (no `atx_heading` child) → `_heading` returns `None` → treated as headingless → **skipped**. This is the documented v1 limitation (spec Out-of-Scope). No test asserts setext extraction; do not add setext handling in this task.

- [ ] **Step 3: Commit**

```bash
git add packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py
git commit -m "test(indexer): lock MarkdownParser hierarchy, multi-H1, preamble, and code-fence handling"
```

---

## Task 5: Resilience

Confirm the parser never raises on bad input. No production change expected (Task 2's `try/except OSError` + `has_error` log-and-continue cover it); this locks it with tests.

**Files:**
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py`
- Modify (only if a test fails): `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/markdown.py`

- [ ] **Step 1: Write the tests**

Append to `test_markdown.py`:

```python
def test_malformed_markdown_does_not_raise(tmp_path: Path) -> None:
    f = _write(tmp_path, "#### \n###unclosed [link](\n```\nunterminated fence\n")
    symbols = MarkdownParser().parse(f)  # must not raise
    assert isinstance(symbols, list)
    # The hub is always present even when content is messy.
    assert any(s.kind == SymbolKind.DOCUMENT for s in symbols)


def test_unreadable_file_returns_empty(tmp_path: Path) -> None:
    assert MarkdownParser().parse(tmp_path / "does_not_exist.md") == []
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py -k "malformed or unreadable" -v`
Expected: PASS — `parse()` returns `[]` on `OSError` and logs-and-extracts on `has_error`. If a test raises, align `parse()` with the `python_lang.py`/`go_lang.py` pattern (do not change test expectations).

- [ ] **Step 3: Commit**

```bash
git add packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py
git commit -m "test(indexer): lock MarkdownParser resilience to malformed and unreadable input"
```

---

## Task 6: Extractor — document/section node payload shape

Add a document branch to `symbol_to_node` that builds the `document` / `document_section` property shape while **preserving** the shared natural-key invariants (`title = f"{kind.value}: {name}"`, `properties.kind = kind.value`, `properties.file_path`). Code symbols are untouched.

**Files:**
- Modify: `packages/ennam-kg-indexer/src/ennam_kg_indexer/indexer/extractor.py`
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_markdown.py` (new imports — hoist these to the top import block of the file alongside the existing imports):

```python
from ennam_kg_indexer.indexer.extractor import NodeExtractor, map_kind_to_type


def _nodes_by_name(symbols, project_id="proj", repo_key="K"):
    ext = NodeExtractor()
    return {s.name: ext.symbol_to_node(s, project_id, repo_key=repo_key) for s in symbols}


def test_section_node_type_and_props(tmp_path: Path) -> None:
    assert map_kind_to_type(SymbolKind.SECTION) == "document_section"
    f = _write(tmp_path, "# Title\n\n## Section A\n\ntext\n\n### Sub A1\n\nsub\n")
    nodes = _nodes_by_name(MarkdownParser().parse(f))
    a = nodes["Section A"]
    assert a["node_type"] == "document_section"
    assert a["title"] == "document_section: Section A"   # kind-prefixed (natural-key invariant)
    assert a["created_by"] == "python-indexer"
    props = a["properties"]
    assert props["kind"] == "document_section"
    assert props["file_path"]
    assert props["body_hash"]
    assert props["repo_path"] == "K"                      # required for repo-scope archival
    assert props["level"] == 2
    assert "text" in props["content"]
    assert props["line_start"] >= 1 and props["line_end"] >= props["line_start"]
    assert props["summary"]                               # summary present
    assert "arch_type" not in props                       # dropped for doc nodes
    assert "signature" not in props
    assert nodes["Sub A1"]["properties"]["level"] == 3


def test_document_hub_node_props(tmp_path: Path) -> None:
    f = _write(tmp_path, "# Title\n\nbody\n", name="notes.md")
    nodes = _nodes_by_name(MarkdownParser().parse(f))
    hub = nodes["notes.md"]
    assert hub["node_type"] == "document"
    assert hub["title"] == "document: notes.md"
    props = hub["properties"]
    assert props["kind"] == "document"
    assert props["file_path"] and props["body_hash"] and props["repo_path"] == "K"
    assert "arch_type" not in props


def test_created_by_isolation(tmp_path: Path) -> None:
    # Indexed nodes carry created_by=python-indexer so the differ never archives
    # ingestion-created document_sections.
    f = _write(tmp_path, "# A\n\n## B\n\nx\n")
    for node in _nodes_by_name(MarkdownParser().parse(f)).values():
        assert node["created_by"] == "python-indexer"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py -k "node_type_and_props or hub_node or created_by_isolation" -v`
Expected: FAIL — `symbol_to_node` currently builds the code/`arch_type` shape for all kinds, so `arch_type` is present and doc fields (`level`, `content`, `repo_path`) are missing/wrong.

- [ ] **Step 3: Add the document branch to `symbol_to_node`**

In `packages/ennam-kg-indexer/src/ennam_kg_indexer/indexer/extractor.py`, at the **top** of `symbol_to_node` (before the `content = (...)` line at line 39), add the branch:

```python
    def symbol_to_node(
        self, symbol: Symbol, project_id: str, *, repo_key: str
    ) -> dict[str, object]:
        """Convert a Symbol to a Go API node creation payload."""
        # Document / section symbols use the doc-node property shape, but keep
        # the shared natural-key invariants (title="kind: name", properties.kind).
        if symbol.kind in (SymbolKind.DOCUMENT, SymbolKind.SECTION):
            return self._document_to_node(symbol, project_id, repo_key=repo_key)

        content = (
            f"File: {symbol.file_path}\n"
            # ... rest of the existing method unchanged ...
```

Add the new helper method directly after `symbol_to_node` (before `extract_edges`). Note the section-content truncations to the verified schema limits (`content` ≤50000, `summary` ≤8000):

```python
    def _document_to_node(
        self, symbol: Symbol, project_id: str, *, repo_key: str
    ) -> dict[str, object]:
        """Build a `document` hub or `document_section` node payload.

        Preserves the shared natural-key invariants: title is kind-prefixed and
        properties.kind == kind.value (so a colon-containing heading round-trips
        through title.split(': ', 1)[-1]). Stores repo_path for repo-scope
        archival. Drops code-only arch_type/signature/decorators.
        """
        title = f"{symbol.kind.value}: {symbol.name}"  # natural-key invariant
        properties: dict[str, object] = {
            "kind": symbol.kind.value,
            "file_path": symbol.file_path,
            "body_hash": symbol.body_hash,
            "repo_path": repo_key,  # stable logical repo identity (repo-scope archival)
        }
        if symbol.kind is SymbolKind.SECTION:
            properties["content"] = symbol.content[:50000]
            properties["summary"] = symbol.content[:8000]
            properties["line_start"] = symbol.line_start
            properties["line_end"] = symbol.line_end
            properties["level"] = symbol.level
        else:  # DOCUMENT hub
            properties["summary"] = symbol.content[:8000]  # preamble preview

        return {
            "node_type": map_kind_to_type(symbol.kind),  # "document" / "document_section"
            "title": title,
            "project_id": project_id,
            "created_by": "python-indexer",
            "status": "active",
            "properties": properties,
        }
```

Confirm `SymbolKind` is imported at the top of `extractor.py` — it already is (line 5: `from ennam_kg_indexer.parsers.base import Symbol, SymbolKind`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py -v`
Expected: PASS (all prior + 3 new). Also run the existing extractor tests to confirm code symbols are untouched:

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_extractor.py -v`
Expected: PASS (unchanged).

- [ ] **Step 5: Commit**

```bash
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/indexer/extractor.py \
        packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py
git commit -m "feat(indexer): document/document_section node payload shape in extractor"
```

---

## Task 7: Extractor — `contains_section` containment edges

Make `extract_edges` (a) include `DOCUMENT`/`SECTION` in the parent-kind search set and (b) emit `contains_section` (not `relates_to`) when the parent is a doc kind. Code-kind edges keep `relates_to`.

**Files:**
- Modify: `packages/ennam-kg-indexer/src/ennam_kg_indexer/indexer/extractor.py`
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py`

- [ ] **Step 1: Write the failing test**

Append to `test_markdown.py`:

```python
def test_extract_edges_contains_section(tmp_path: Path) -> None:
    # hub -> A (contains_section), A -> B (contains_section), B -> C (contains_section).
    f = _write(tmp_path, "# A\n\n## B\n\n### C\n\nx\n", name="notes.md")
    symbols = MarkdownParser().parse(f)
    ext = NodeExtractor()
    node_id_map = {
        f"{s.file_path}:{s.name}:{s.kind.value}": f"n{i}" for i, s in enumerate(symbols)
    }
    edges = ext.extract_edges(symbols, "proj", node_id_map)
    assert len(edges) == 3
    assert all(e["relationship"] == "contains_section" for e in edges), (
        "doc containment must use contains_section — relates_to is rejected by the edge whitelist"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py -k contains_section -v`
Expected: FAIL — current `extract_edges` only searches `CLASS/MODULE/COMPONENT/WIDGET` parent kinds (so doc parents aren't found → 0 edges) and hardcodes `relates_to`.

- [ ] **Step 3: Update `extract_edges`**

In `packages/ennam-kg-indexer/src/ennam_kg_indexer/indexer/extractor.py`, change the containment block (lines 113–134). Add the two doc kinds to the search tuple and choose the relationship by matched parent kind:

```python
            # Parent-child containment edges
            if symbol.parent is not None:
                # Try to find the parent in the node_id_map.
                # The parent field is just a name, so we look in the same file.
                for parent_kind in (
                    SymbolKind.CLASS,
                    SymbolKind.MODULE,
                    SymbolKind.COMPONENT,
                    SymbolKind.WIDGET,
                    SymbolKind.DOCUMENT,
                    SymbolKind.SECTION,
                ):
                    parent_key = f"{symbol.file_path}:{symbol.parent}:{parent_kind.value}"
                    parent_node_id = node_id_map.get(parent_key)
                    if parent_node_id is not None:
                        # Doc containment uses contains_section (relates_to is rejected
                        # by the edge whitelist for document/document_section).
                        relationship = (
                            "contains_section"
                            if parent_kind in (SymbolKind.DOCUMENT, SymbolKind.SECTION)
                            else "relates_to"
                        )
                        edges.append(
                            {
                                "source_id": parent_node_id,
                                "target_id": symbol_node_id,
                                "relationship": relationship,
                                "project_id": project_id,
                                "created_by": "python-indexer",
                            }
                        )
                        break
```

Leave the import-edges block (lines 136–154) unchanged — doc symbols never populate `imports`, and code symbols keep `relates_to`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py -v`
Expected: PASS (all prior + the edges test). Confirm code edges still use `relates_to`:

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_extractor.py packages/ennam-kg-indexer/tests/test_engine_relative_paths.py -v`
Expected: PASS (unchanged — code parsers still emit `relates_to`).

- [ ] **Step 5: Commit**

```bash
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/indexer/extractor.py \
        packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py
git commit -m "feat(indexer): contains_section edges for document/section containment"
```

---

## Task 8: Integration — `full_scan` edges + colon natural-key stability

End-to-end through `engine.full_scan` (mocked KG client): a doc with `#`/`##`/`###` produces `contains_section` edges, and a colon-containing heading round-trips so a re-scan creates **zero** duplicates (the natural-key regression guard).

**Files:**
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_markdown.py` (new imports — hoist `pytest`, `AsyncMock`, `IndexingEngine` to the top import block):

```python
import pytest
from unittest.mock import AsyncMock

from ennam_kg_indexer.indexer.engine import IndexingEngine


def _mock_kg_client() -> AsyncMock:
    c = AsyncMock()
    c.get_nodes.return_value = []
    c.create_node.return_value = {"node": {"id": "n-1"}}
    c.update_node.return_value = {"id": "n-1"}
    c.create_edge.return_value = {"id": "e-1"}
    return c


@pytest.mark.asyncio
async def test_full_scan_creates_contains_section_edges(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n\n## Setup\n\ndo this\n")
    client = _mock_kg_client()
    result = await IndexingEngine(client).full_scan("proj-md", str(tmp_path))
    assert result.edges_created >= 1, "document->section containment edge must be created"
    # Every edge created for this markdown repo must be contains_section.
    rels = [c.args[0]["relationship"] for c in client.create_edge.call_args_list]
    assert rels and all(r == "contains_section" for r in rels), rels
    assert result.errors == []


@pytest.mark.asyncio
async def test_colon_heading_natural_key_stable(tmp_path: Path) -> None:
    """A heading 'Part 1: Overview' must round-trip through the natural key so a
    re-scan with the section already in the KG produces ZERO creates for it."""
    (tmp_path / "doc.md").write_text("# Top\n\n## Part 1: Overview\n\nbody\n")

    # First scan: KG empty → nodes created.
    c1 = _mock_kg_client()
    await IndexingEngine(c1).full_scan("proj-md", str(tmp_path), repo_key="K")
    created = [c.args[0] for c in c1.create_node.call_args_list]
    assert any(p["title"] == "document_section: Part 1: Overview" for p in created)

    # Build existing-node records as the differ would see them next time.
    existing = []
    for i, p in enumerate(created):
        existing.append(
            {
                "id": f"n{i}",
                "title": p["title"],
                "created_by": "python-indexer",
                "properties": p["properties"],
            }
        )

    # Second scan from a different physical root, same logical repo_key, same content.
    other = tmp_path / "other"
    other.mkdir()
    (other / "doc.md").write_text("# Top\n\n## Part 1: Overview\n\nbody\n")
    c2 = _mock_kg_client()
    c2.get_nodes.return_value = existing
    await IndexingEngine(c2).full_scan("proj-md", str(other), repo_key="K")

    # The colon section must match its existing key → NOT re-created.
    recreated_titles = [c.args[0]["title"] for c in c2.create_node.call_args_list]
    assert "document_section: Part 1: Overview" not in recreated_titles, (
        f"colon heading was duplicated on re-scan — natural key did not round-trip: {recreated_titles}"
    )
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py -k "full_scan or colon_heading" -v`
Expected: PASS — the scanner discovers `.md` via `get_parser`, the engine relativizes `file_path` and keys edges through `node_id_map`, and the `title.split(': ', 1)[-1]` round-trip recovers the full `"Part 1: Overview"` heading so the differ matches the existing node (0 re-creates). If the colon test FAILS with the title in `recreated_titles`, a "clean" title was stored somewhere (Task 6 regression).

- [ ] **Step 3: Commit**

```bash
git add packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py
git commit -m "test(indexer): integration — contains_section edges and colon-heading natural-key stability"
```

---

## Task 9: Full-suite verification + lint

Confirm nothing regressed across the package and the new code passes lint/format.

**Files:** none (verification only)

- [ ] **Step 1: Run the full indexer test suite**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests -q`
Expected: PASS — all pre-existing tests plus the new markdown tests. Zero failures. (The 3 scanner/engine tests that previously assumed `.md` was unsupported were already updated in Task 2 Step 5; if any of them fail here, that update was missed.)

- [ ] **Step 2: Lint and format the new/changed files**

Run:

```bash
cd $PY
uv run ruff check packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/markdown.py \
                  packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/base.py \
                  packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/__init__.py \
                  packages/ennam-kg-indexer/src/ennam_kg_indexer/indexer/extractor.py \
                  packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py
uv run ruff format packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/markdown.py \
                   packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py
```

Expected: ruff reports no errors. If `ruff format` changes anything, re-run the test suite to confirm still green.

- [ ] **Step 3: Smoke test against a real markdown repo**

Index a real docs tree to confirm real-world output (the requirements repo is markdown-heavy):

```bash
cd $PY
uv run python -c "
from pathlib import Path
from ennam_kg_indexer.parsers.markdown import MarkdownParser
import glob
fs = glob.glob('../ennam.kg.requirements/documents/**/*.md', recursive=True)[:3]
p = MarkdownParser()
for f in fs:
    syms = p.parse(Path(f))
    hubs = sum(1 for s in syms if s.kind.value == 'document')
    secs = sum(1 for s in syms if s.kind.value == 'document_section')
    print(f, f'-> {hubs} hub, {secs} sections')
"
```

Expected: each file reports exactly 1 hub and a non-zero section count, no traceback.

- [ ] **Step 4: Commit any formatting changes**

```bash
git add -A packages/ennam-kg-indexer
git commit -m "chore(indexer): ruff format MarkdownParser and tests" --allow-empty
```

---

## Self-Review

**Spec coverage:**
- `document` hub (basename, not H1) + `document_section` per heading → Tasks 2, 3; `test_document_hub_is_basename_not_h1`. ✓
- No embedding (structural only) → parser produces structural symbols; no torch/sentence-transformers import. ✓
- tree-sitter grammar (code-fence handling) → Task 1 dep, `test_code_fence_is_not_a_heading`. ✓
- Hierarchy → containment edges via `parent` → Tasks 3, 4, 7; `test_hierarchy_parents`, `test_extract_edges_contains_section`. ✓
- Node mapping table (DOCUMENT→document, SECTION→document_section, headingless skip, nesting edge) → Tasks 2–4, 6; `map_kind_to_type` fallback verified Task 1. ✓
- `file_path` repo-relative / natural key / `body_hash` own-content → Tasks 3, 8; own-range guard `test_own_range_isolates_subsection_hash`. ✓
- `symbol_to_node` doc shape preserving natural-key invariants, drop arch_type, colon handling → Task 6; `test_section_node_type_and_props`, `test_colon_heading_natural_key_stable`. ✓
- `extract_edges` parent-kind set + `contains_section` → Task 7. ✓
- `base.py` SymbolKind additions → Task 1. ✓
- Registry → Task 2 + `test_parser_registered`. ✓
- pyproject dependency + tree-sitter bump → Task 1. ✓
- created_by isolation → Task 6 `test_created_by_isolation`. ✓
- Error handling (unreadable→[], has_error→subset, malformed section→skip, no-heading→hub only) → Tasks 2, 5; `test_no_heading_file_one_hub_zero_sections`, `test_malformed_markdown_does_not_raise`. ✓
- All 10 spec test cases (incl. 3b colon regression) → mapped across Tasks 2–8. ✓
- Out-of-scope (embedding, inline extraction, front-matter, setext, decompose routing) → not implemented; setext skip explicitly noted in Task 4. ✓

**Clarifications surfaced (beyond spec literal text):** `Symbol.level`/`content` fields (Task 1) and `properties.repo_path` on doc nodes (Task 6) — both necessary, both flagged at the top. **Pre-existing-test breakage** (Task 2 Step 5): registering the parser makes `.md` supported, breaking 3 tests that used `.md` as their unsupported example — empirically confirmed and remediated in-plan; the full suite goes 105 → 122 passing.

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N" — every code block is complete.

**Type consistency:** Method names consistent — `parse`, `_walk_section`, `_preamble`, `_heading`, `_heading_text`, `_heading_level`, `_own_range`, `_text` (parser); `symbol_to_node`, `_document_to_node`, `extract_edges`, `map_kind_to_type` (extractor). `_document_to_node(symbol, project_id, *, repo_key)` matches its single call site. `Symbol(... level=, content=)` matches the fields added in Task 1. Property keys (`kind`, `file_path`, `body_hash`, `repo_path`, `content`, `summary`, `level`, `line_start`, `line_end`) match the verified `config.yaml` schema field names. ✓

---

## Execution Handoff
