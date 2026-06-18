# Go Parser for `ennam-kg-indexer` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `GoParser` to `ennam-kg-indexer` so `.go` source is parsed into KG symbol nodes, unlocking indexing of `ennam.kg.go` and any Go repo via the existing CLI / `kg_index_source` MCP tool.

**Architecture:** New `parsers/go_lang.py` defines `GoParser(BaseParser)`, structured exactly like `PythonParser` — a `parse(Path) -> list[Symbol]` that walks the `source_file` root, dispatching top-level nodes to focused handlers. Registered in `parsers/__init__.py` alongside the others. No changes to `engine.py`, `differ.py`, `extractor.py`, `scanner.py`, or `base.py` — they are already language-agnostic; a parser only produces `list[Symbol]`.

**Tech Stack:** Python 3.12, `tree-sitter>=0.23`, `tree-sitter-go>=0.23` (already declared in `pyproject.toml` — no dependency change), pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-06-06-go-parser-design.md` (Approved). Grammar node types/fields below were verified empirically against the installed `tree-sitter-go` (0.25.x) on 2026-06-07.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py` | `GoParser` — walk Go AST → `list[Symbol]` | **Create** |
| `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/__init__.py` | Register `GoParser`, export it | **Modify** (lines 8–9 imports, 12–20 `__all__`, 37–39 registration) |
| `packages/ennam-kg-indexer/tests/test_parsers/test_go.py` | All `GoParser` unit + edge-integration tests | **Create** |

All paths are relative to the workspace root `/Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace/`. All commands run from `ennam.kg.python/` (the `uv` project root — referred to below as `$PY`).

### Mirror reference (read these before starting)

- `parsers/python_lang.py` — the parser this mirrors (helpers, error handling, dispatch shape).
- `parsers/base.py` — `Symbol` dataclass + `SymbolKind` enum + inherited `_compute_body_hash`.
- `parsers/__init__.py` — the `_register` / `_EXTENSION_MAP` registry.
- `tests/test_engine_relative_paths.py::test_containment_edge_created` — the edge-integration test pattern Task 8 mirrors.

### Verified grammar facts (do not re-guess)

- Top-level node types under `source_file`: `comment`, `package_clause`, `import_declaration`, `function_declaration`, `method_declaration`, `type_declaration`, `const_declaration`, `var_declaration`.
- `function_declaration` / `method_declaration`: field `name` → identifier. `method_declaration` field `receiver` → `parameter_list`.
- Receiver nesting: `parameter_list` → `parameter_declaration` → (`type_identifier` | `pointer_type` → `type_identifier`) | (`pointer_type` → `generic_type` → `type_identifier`). Recurse to first `type_identifier`.
- `type_declaration` children: `type_spec` (fields `name`, `type`) or `type_alias` (fields `name`, `type`).
  - `type_spec` with `type` = `struct_type` → CLASS; `interface_type` → INTERFACE; anything else (e.g. `type_identifier` for `type Celsius float64`) → TYPE_ALIAS.
  - `type_alias` node (`type ID = string`) → TYPE_ALIAS.
- `const_declaration` → one or more `const_spec`; `var_declaration` → one or more `var_spec`. A spec's names are its **`identifier` children** (e.g. `var a, b int` is ONE `var_spec` with two `identifier` children). Do NOT use `child_by_field_name("name")` for specs.

---

## Task 1: GoParser skeleton + registration + functions

Establish the parser file with the module-level language, constructor, `parse()` dispatch, shared helpers, the `function_declaration` handler, and registry wiring. This is the minimal end-to-end slice: a `.go` file with a top-level func produces one `FUNCTION` symbol.

**Files:**
- Create: `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py`
- Modify: `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/__init__.py`
- Create: `packages/ennam-kg-indexer/tests/test_parsers/test_go.py`

- [ ] **Step 1: Write the failing tests (registration + functions)**

Create `packages/ennam-kg-indexer/tests/test_parsers/test_go.py`:

```python
"""Tests for the Go parser."""

from __future__ import annotations

from pathlib import Path

from ennam_kg_indexer.parsers import SymbolKind, get_parser
from ennam_kg_indexer.parsers.go_lang import GoParser


def _write(tmp_path: Path, body: str) -> Path:
    f = tmp_path / "sample.go"
    f.write_text(body)
    return f


def test_parser_registered(tmp_path: Path) -> None:
    parser = get_parser(_write(tmp_path, "package main\n"))
    assert parser is not None
    assert isinstance(parser, GoParser)


def test_supported_extensions() -> None:
    assert GoParser().supported_extensions() == {".go"}


def test_function(tmp_path: Path) -> None:
    f = _write(tmp_path, "package main\n\nfunc Hello() {}\n")
    symbols = GoParser().parse(f)
    hello = next(s for s in symbols if s.name == "Hello")
    assert hello.kind == SymbolKind.FUNCTION
    assert hello.parent is None
    assert hello.signature.startswith("func Hello")
    assert hello.line_start == 3
    assert hello.body_hash
    assert hello.decorators == []


def test_unexported_function_included(tmp_path: Path) -> None:
    f = _write(tmp_path, "package main\n\nfunc helper() {}\n")
    symbols = GoParser().parse(f)
    assert any(s.name == "helper" and s.kind == SymbolKind.FUNCTION for s in symbols)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_go.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ennam_kg_indexer.parsers.go_lang'`

- [ ] **Step 3: Create `go_lang.py` with skeleton, helpers, and function handler**

Create `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py`:

```python
"""Go parser using tree-sitter-go."""

from __future__ import annotations

import logging
from pathlib import Path

import tree_sitter_go as ts_go
from tree_sitter import Language, Parser

from .base import BaseParser, Symbol, SymbolKind

logger = logging.getLogger(__name__)

GO_LANGUAGE = Language(ts_go.language())


class GoParser(BaseParser):
    """Extracts symbols from Go source files."""

    def __init__(self) -> None:
        self._parser = Parser(GO_LANGUAGE)

    def supported_extensions(self) -> set[str]:
        return {".go"}

    def parse(self, file_path: Path) -> list[Symbol]:
        try:
            source = file_path.read_bytes()
        except OSError:
            logger.warning("Could not read file: %s", file_path)
            return []

        tree = self._parser.parse(source)
        if tree.root_node.has_error:
            logger.warning("Parse errors in %s — extracting what we can", file_path)

        symbols: list[Symbol] = []
        fp = str(file_path)
        self._walk_source_file(tree.root_node, source, fp, symbols)
        return symbols

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def _walk_source_file(
        self,
        root: object,
        source: bytes,
        fp: str,
        symbols: list[Symbol],
    ) -> None:
        """Walk top-level declarations in a Go source file."""
        for child in root.children:  # type: ignore[attr-defined]
            ntype = child.type  # type: ignore[attr-defined]
            if ntype == "function_declaration":
                self._handle_function(child, source, fp, symbols)

    def _handle_function(
        self,
        node: object,
        source: bytes,
        fp: str,
        symbols: list[Symbol],
    ) -> None:
        name = self._child_text(node, "name", source) or ""
        if not name:
            return
        symbols.append(self._make_symbol(node, source, fp, name, SymbolKind.FUNCTION, parent=None))

    # ------------------------------------------------------------------
    # Symbol construction
    # ------------------------------------------------------------------

    def _make_symbol(
        self,
        node: object,
        source: bytes,
        fp: str,
        name: str,
        kind: SymbolKind,
        parent: str | None,
        docstring: str = "",
    ) -> Symbol:
        return Symbol(
            name=name,
            kind=kind,
            file_path=fp,
            line_start=node.start_point[0] + 1,  # type: ignore[attr-defined]
            line_end=node.end_point[0] + 1,  # type: ignore[attr-defined]
            signature=self._signature_line(node, source),
            body_hash=self._compute_body_hash(source, node.start_byte, node.end_byte),  # type: ignore[attr-defined]
            parent=parent,
            docstring=docstring,
            decorators=[],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _signature_line(self, node: object, source: bytes) -> str:
        """Text up to the first '{' (or first newline if none), whitespace-collapsed."""
        text = self._text(node, source)
        brace = text.find("{")
        head = text if brace == -1 else text[:brace]
        return " ".join(head.split())

    def _text(self, node: object, source: bytes) -> str:
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")  # type: ignore[attr-defined]

    def _child_text(self, node: object, field_name: str, source: bytes) -> str | None:
        child = node.child_by_field_name(field_name)  # type: ignore[attr-defined]
        if child is None:
            return None
        return source[child.start_byte : child.end_byte].decode("utf-8", errors="replace")  # type: ignore[attr-defined]

    def _child_by_type(self, node: object, type_name: str) -> object | None:
        for child in node.children:  # type: ignore[attr-defined]
            if child.type == type_name:  # type: ignore[attr-defined]
                return child
        return None
```

- [ ] **Step 4: Register the parser**

In `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/__init__.py`:

Add the import after the dart import (currently line 8):

```python
from .dart import DartParser
from .go_lang import GoParser
from .python_lang import PythonParser
```

Add `"GoParser",` to `__all__` (alphabetical, after `"DartParser"`):

```python
__all__ = [
    "BaseParser",
    "DartParser",
    "GoParser",
    "PythonParser",
    "Symbol",
    "SymbolKind",
    "TypeScriptParser",
    "get_parser",
]
```

Add the registration call alongside the others (after `_register(DartParser)`):

```python
_register(TypeScriptParser)
_register(PythonParser)
_register(DartParser)
_register(GoParser)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_go.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py \
        packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/__init__.py \
        packages/ennam-kg-indexer/tests/test_parsers/test_go.py
git commit -m "feat(indexer): add GoParser skeleton with function extraction and registration"
```

---

## Task 2: Methods + receiver parent (incl. generic receiver)

Add `method_declaration` handling. The receiver type becomes the method's `parent` so the extractor's containment logic links `Repo` → `Save`. The receiver may be `Repo`, `*Repo`, or generic `*Box[T]`, so resolve the type by recursively descending to the first `type_identifier`.

**Files:**
- Modify: `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py`
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_go.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_go.py`:

```python
def test_method_pointer_receiver(tmp_path: Path) -> None:
    f = _write(tmp_path, "package main\n\nfunc (r *Repo) Save() error { return nil }\n")
    save = next(s for s in GoParser().parse(f) if s.name == "Save")
    assert save.kind == SymbolKind.METHOD
    assert save.parent == "Repo"


def test_method_value_receiver(tmp_path: Path) -> None:
    f = _write(tmp_path, "package main\n\nfunc (r Repo) Name() string { return \"\" }\n")
    name = next(s for s in GoParser().parse(f) if s.name == "Name")
    assert name.kind == SymbolKind.METHOD
    assert name.parent == "Repo"


def test_method_generic_receiver(tmp_path: Path) -> None:
    # Regression guard: *Box[T] nests pointer_type -> generic_type -> type_identifier.
    # A single pointer-unwrap would yield None; recursion must reach "Box".
    f = _write(tmp_path, "package main\n\nfunc (b *Box[T]) Get() T { var z T; return z }\n")
    get = next(s for s in GoParser().parse(f) if s.name == "Get")
    assert get.kind == SymbolKind.METHOD
    assert get.parent == "Box"


def test_method_malformed_receiver_still_emitted(tmp_path: Path) -> None:
    # No resolvable type identifier -> method still emitted with parent=None, not dropped.
    f = _write(tmp_path, "package main\n\nfunc () Orphan() {}\n")
    syms = GoParser().parse(f)
    orphan = next(s for s in syms if s.name == "Orphan")
    assert orphan.kind == SymbolKind.METHOD
    assert orphan.parent is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_go.py -k method -v`
Expected: FAIL — methods are not yet dispatched, so `next(...)` raises `StopIteration`.

- [ ] **Step 3: Add the dispatch branch and method handler**

In `go_lang.py`, add a branch in `_walk_source_file` (after the `function_declaration` branch):

```python
            elif ntype == "method_declaration":
                self._handle_method(child, source, fp, symbols)
```

Add the handler method (after `_handle_function`):

```python
    def _handle_method(
        self,
        node: object,
        source: bytes,
        fp: str,
        symbols: list[Symbol],
    ) -> None:
        name = self._child_text(node, "name", source) or ""
        if not name:
            return
        parent = self._receiver_type(node, source)
        symbols.append(self._make_symbol(node, source, fp, name, SymbolKind.METHOD, parent=parent))

    def _receiver_type(self, method_node: object, source: bytes) -> str | None:
        """Resolve the receiver's type name (strips pointers / generics).

        Recursively descends to the first type_identifier so that Repo, *Repo,
        and generic *Box[T] all resolve to the base type name. Returns None if
        no type_identifier is found.
        """
        receiver = method_node.child_by_field_name("receiver")  # type: ignore[attr-defined]
        if receiver is None:
            return None
        found = self._first_type_identifier(receiver, source)
        return found

    def _first_type_identifier(self, node: object, source: bytes) -> str | None:
        if node.type == "type_identifier":  # type: ignore[attr-defined]
            return self._text(node, source)
        for child in node.children:  # type: ignore[attr-defined]
            result = self._first_type_identifier(child, source)
            if result is not None:
                return result
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_go.py -v`
Expected: PASS (all Task 1 + Task 2 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py \
        packages/ennam-kg-indexer/tests/test_parsers/test_go.py
git commit -m "feat(indexer): GoParser method extraction with receiver-type parent resolution"
```

---

## Task 3: Types — structs, interfaces, aliases

Add `type_declaration` handling. Iterate `type_spec`/`type_alias` children and map by the underlying type: `struct_type` → CLASS, `interface_type` → INTERFACE, everything else (and `type_alias`) → TYPE_ALIAS.

**Files:**
- Modify: `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py`
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_go.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_go.py`:

```python
def test_struct_is_class(tmp_path: Path) -> None:
    f = _write(tmp_path, "package main\n\ntype Repo struct{}\n")
    repo = next(s for s in GoParser().parse(f) if s.name == "Repo")
    assert repo.kind == SymbolKind.CLASS


def test_interface(tmp_path: Path) -> None:
    f = _write(tmp_path, "package main\n\ntype Store interface{}\n")
    store = next(s for s in GoParser().parse(f) if s.name == "Store")
    assert store.kind == SymbolKind.INTERFACE


def test_type_alias_eq(tmp_path: Path) -> None:
    f = _write(tmp_path, "package main\n\ntype ID = string\n")
    ident = next(s for s in GoParser().parse(f) if s.name == "ID")
    assert ident.kind == SymbolKind.TYPE_ALIAS


def test_defined_type_is_alias_kind(tmp_path: Path) -> None:
    # `type Celsius float64` is a type_spec whose type is a plain type_identifier.
    f = _write(tmp_path, "package main\n\ntype Celsius float64\n")
    celsius = next(s for s in GoParser().parse(f) if s.name == "Celsius")
    assert celsius.kind == SymbolKind.TYPE_ALIAS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_go.py -k "struct or interface or alias or celsius" -v`
Expected: FAIL — `type_declaration` not dispatched → `StopIteration`.

- [ ] **Step 3: Add the dispatch branch and type handler**

In `go_lang.py`, add a branch in `_walk_source_file`:

```python
            elif ntype == "type_declaration":
                self._handle_type(child, source, fp, symbols)
```

Add the handler (after `_handle_method`):

```python
    def _handle_type(
        self,
        node: object,
        source: bytes,
        fp: str,
        symbols: list[Symbol],
    ) -> None:
        """Handle a type_declaration — one or more type_spec / type_alias children."""
        for spec in node.children:  # type: ignore[attr-defined]
            stype = spec.type  # type: ignore[attr-defined]
            if stype not in ("type_spec", "type_alias"):
                continue
            name_node = spec.child_by_field_name("name")  # type: ignore[attr-defined]
            if name_node is None:
                continue
            name = self._text(name_node, source)
            kind = self._type_kind(spec)
            symbols.append(self._make_symbol(spec, source, fp, name, kind, parent=None))

    def _type_kind(self, spec: object) -> SymbolKind:
        if spec.type == "type_alias":  # type: ignore[attr-defined]
            return SymbolKind.TYPE_ALIAS
        type_node = spec.child_by_field_name("type")  # type: ignore[attr-defined]
        if type_node is not None:
            if type_node.type == "struct_type":  # type: ignore[attr-defined]
                return SymbolKind.CLASS
            if type_node.type == "interface_type":  # type: ignore[attr-defined]
                return SymbolKind.INTERFACE
        return SymbolKind.TYPE_ALIAS
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_go.py -v`
Expected: PASS (all prior + 4 new)

- [ ] **Step 5: Commit**

```bash
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py \
        packages/ennam-kg-indexer/tests/test_parsers/test_go.py
git commit -m "feat(indexer): GoParser struct/interface/alias extraction"
```

---

## Task 4: Const / var (incl. multi-name specs)

Add `const_declaration` and `var_declaration` handling. Iterate each spec's `identifier` children (NOT the `name` field) and emit one CONSTANT/VARIABLE per name, so `var a, b int` yields two symbols and a `const (…)` block yields one per line.

**Files:**
- Modify: `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py`
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_go.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_go.py`. **Fixtures must be valid gofmt-formatted Go** — each spec in a grouped block on its own indented line, else `has_error` recovery can mangle symbols and make assertions flaky:

```python
def test_const_single(tmp_path: Path) -> None:
    f = _write(tmp_path, "package main\n\nconst Max = 10\n")
    mx = next(s for s in GoParser().parse(f) if s.name == "Max")
    assert mx.kind == SymbolKind.CONSTANT


def test_var_single(tmp_path: Path) -> None:
    f = _write(tmp_path, "package main\n\nvar count int\n")
    count = next(s for s in GoParser().parse(f) if s.name == "count")
    assert count.kind == SymbolKind.VARIABLE


def test_const_block(tmp_path: Path) -> None:
    f = _write(tmp_path, "package main\n\nconst (\n\tA = 1\n\tB = 2\n)\n")
    syms = GoParser().parse(f)
    consts = {s.name for s in syms if s.kind == SymbolKind.CONSTANT}
    assert {"A", "B"} <= consts


def test_var_multi_name(tmp_path: Path) -> None:
    # Regression guard: `var a, b int` is ONE var_spec with two identifier children.
    # Using child_by_field_name("name") would emit only "a".
    f = _write(tmp_path, "package main\n\nvar a, b int\n")
    syms = GoParser().parse(f)
    vnames = {s.name for s in syms if s.kind == SymbolKind.VARIABLE}
    assert {"a", "b"} <= vnames
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_go.py -k "const or var_" -v`
Expected: FAIL — const/var not dispatched → `StopIteration`.

- [ ] **Step 3: Add the dispatch branches and value-spec handler**

In `go_lang.py`, add two branches in `_walk_source_file`:

```python
            elif ntype == "const_declaration":
                self._handle_value_spec(child, source, fp, symbols, SymbolKind.CONSTANT, "const_spec")
            elif ntype == "var_declaration":
                self._handle_value_spec(child, source, fp, symbols, SymbolKind.VARIABLE, "var_spec")
```

Add the handler (after `_type_kind`):

```python
    def _handle_value_spec(
        self,
        node: object,
        source: bytes,
        fp: str,
        symbols: list[Symbol],
        kind: SymbolKind,
        spec_type: str,
    ) -> None:
        """Handle const_declaration / var_declaration.

        Each spec may declare multiple names (`var a, b int` is one spec with
        two identifier children), so iterate identifier children — one Symbol
        per name. signature/body_hash come from the enclosing spec node.
        """
        for spec in node.children:  # type: ignore[attr-defined]
            if spec.type != spec_type:  # type: ignore[attr-defined]
                continue
            for ident in spec.children:  # type: ignore[attr-defined]
                if ident.type != "identifier":  # type: ignore[attr-defined]
                    continue
                name = self._text(ident, source)
                symbols.append(self._make_symbol(spec, source, fp, name, kind, parent=None))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_go.py -v`
Expected: PASS (all prior + 4 new)

- [ ] **Step 5: Commit**

```bash
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py \
        packages/ennam-kg-indexer/tests/test_parsers/test_go.py
git commit -m "feat(indexer): GoParser const/var extraction with multi-name spec support"
```

---

## Task 5: Doc comments with line-adjacency

Attach Go doc comments — the contiguous `//` block directly above a declaration — to the symbol's `docstring`. Only attach if the comment block is line-adjacent (no blank-line gap), matching godoc convention. Strip leading `//` and join lines.

**Files:**
- Modify: `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py`
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_go.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_go.py`:

```python
def test_doc_comment_adjacent(tmp_path: Path) -> None:
    f = _write(tmp_path, "package main\n\n// Save persists the repo.\nfunc Save() {}\n")
    save = next(s for s in GoParser().parse(f) if s.name == "Save")
    assert "Save persists the repo." in save.docstring


def test_doc_comment_multiline(tmp_path: Path) -> None:
    src = "package main\n\n// Repo stores things.\n// Second line.\ntype Repo struct{}\n"
    repo = next(s for s in GoParser().parse(_write(tmp_path, src)) if s.name == "Repo")
    assert "Repo stores things." in repo.docstring
    assert "Second line." in repo.docstring


def test_no_doc_comment_is_empty(tmp_path: Path) -> None:
    f = _write(tmp_path, "package main\n\nfunc Bare() {}\n")
    bare = next(s for s in GoParser().parse(f) if s.name == "Bare")
    assert bare.docstring == ""


def test_doc_comment_with_blank_gap_not_attached(tmp_path: Path) -> None:
    # Comment separated from the declaration by a blank line is NOT a doc comment.
    src = "package main\n\n// Unrelated note.\n\nfunc Gap() {}\n"
    gap = next(s for s in GoParser().parse(_write(tmp_path, src)) if s.name == "Gap")
    assert gap.docstring == ""


def test_block_comment_not_attached(tmp_path: Path) -> None:
    # godoc convention is `//` line comments. A `/* */` block comment above a
    # declaration is NOT treated as a doc comment (would otherwise yield mangled
    # text like "* Block doc */" from lstrip("/")). Expect empty docstring.
    src = "package main\n\n/* Block doc */\nfunc F() {}\n"
    f = next(s for s in GoParser().parse(_write(tmp_path, src)) if s.name == "F")
    assert f.docstring == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_go.py -k "doc or block_comment" -v`
Expected: FAIL — `docstring` is always `""` from Tasks 1–4, so the asserts on non-empty content (`test_doc_comment_adjacent`, `test_doc_comment_multiline`) fail. The empty-expecting guards (`test_no_doc_comment_is_empty`, `test_doc_comment_with_blank_gap_not_attached`, `test_block_comment_not_attached`) happen to pass trivially at this point; they become real regression guards once the doc logic in Step 3 lands.

- [ ] **Step 3: Accumulate comments during the walk and attach when adjacent**

This changes how `_walk_source_file` dispatches: it tracks the most recent contiguous `comment` block and passes the resolved docstring to declaration handlers. Replace the entire `_walk_source_file` method and update the four handler signatures to accept `docstring`.

Replace `_walk_source_file` with:

```python
    def _walk_source_file(
        self,
        root: object,
        source: bytes,
        fp: str,
        symbols: list[Symbol],
    ) -> None:
        """Walk top-level declarations, tracking adjacent doc-comment blocks."""
        # Accumulate consecutive comment nodes; reset on any blank-line gap or
        # non-comment/non-declaration node. When a declaration follows directly,
        # the accumulated block becomes its doc comment.
        comments: list[object] = []

        for child in root.children:  # type: ignore[attr-defined]
            ntype = child.type  # type: ignore[attr-defined]
            if ntype == "comment":
                # Adjacent to the running block? (no blank line between comments)
                if comments and child.start_point[0] > comments[-1].end_point[0] + 1:  # type: ignore[attr-defined]
                    comments = []
                comments.append(child)
                continue

            docstring = self._doc_from_comments(comments, child, source)
            comments = []

            if ntype == "function_declaration":
                self._handle_function(child, source, fp, symbols, docstring)
            elif ntype == "method_declaration":
                self._handle_method(child, source, fp, symbols, docstring)
            elif ntype == "type_declaration":
                self._handle_type(child, source, fp, symbols, docstring)
            elif ntype == "const_declaration":
                self._handle_value_spec(
                    child, source, fp, symbols, SymbolKind.CONSTANT, "const_spec", docstring
                )
            elif ntype == "var_declaration":
                self._handle_value_spec(
                    child, source, fp, symbols, SymbolKind.VARIABLE, "var_spec", docstring
                )

    def _doc_from_comments(
        self,
        comments: list[object],
        decl_node: object,
        source: bytes,
    ) -> str:
        """Return the joined doc comment if the block is line-adjacent to decl_node."""
        if not comments:
            return ""
        last = comments[-1]
        # Adjacent = last comment ends on the line directly above the declaration.
        if last.end_point[0] + 1 != decl_node.start_point[0]:  # type: ignore[attr-defined]
            return ""
        lines = []
        for c in comments:
            text = self._text(c, source)
            # godoc docs are `//` line comments. Skip `/* */` block comments —
            # lstrip("/") would otherwise leave mangled text like "* foo */".
            if not text.startswith("//"):
                return ""
            lines.append(text.lstrip("/").strip())
        return "\n".join(lines).strip()
```

Update the handler signatures to thread `docstring` through to `_make_symbol`:

`_handle_function`:

```python
    def _handle_function(
        self,
        node: object,
        source: bytes,
        fp: str,
        symbols: list[Symbol],
        docstring: str = "",
    ) -> None:
        name = self._child_text(node, "name", source) or ""
        if not name:
            return
        symbols.append(
            self._make_symbol(node, source, fp, name, SymbolKind.FUNCTION, parent=None, docstring=docstring)
        )
```

`_handle_method`:

```python
    def _handle_method(
        self,
        node: object,
        source: bytes,
        fp: str,
        symbols: list[Symbol],
        docstring: str = "",
    ) -> None:
        name = self._child_text(node, "name", source) or ""
        if not name:
            return
        parent = self._receiver_type(node, source)
        symbols.append(
            self._make_symbol(node, source, fp, name, SymbolKind.METHOD, parent=parent, docstring=docstring)
        )
```

`_handle_type` (thread `docstring` into the per-spec symbol):

```python
    def _handle_type(
        self,
        node: object,
        source: bytes,
        fp: str,
        symbols: list[Symbol],
        docstring: str = "",
    ) -> None:
        for spec in node.children:  # type: ignore[attr-defined]
            stype = spec.type  # type: ignore[attr-defined]
            if stype not in ("type_spec", "type_alias"):
                continue
            name_node = spec.child_by_field_name("name")  # type: ignore[attr-defined]
            if name_node is None:
                continue
            name = self._text(name_node, source)
            kind = self._type_kind(spec)
            symbols.append(self._make_symbol(spec, source, fp, name, kind, parent=None, docstring=docstring))
```

`_handle_value_spec` (accept and thread `docstring`):

```python
    def _handle_value_spec(
        self,
        node: object,
        source: bytes,
        fp: str,
        symbols: list[Symbol],
        kind: SymbolKind,
        spec_type: str,
        docstring: str = "",
    ) -> None:
        for spec in node.children:  # type: ignore[attr-defined]
            if spec.type != spec_type:  # type: ignore[attr-defined]
                continue
            for ident in spec.children:  # type: ignore[attr-defined]
                if ident.type != "identifier":  # type: ignore[attr-defined]
                    continue
                name = self._text(ident, source)
                symbols.append(
                    self._make_symbol(spec, source, fp, name, kind, parent=None, docstring=docstring)
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_go.py -v`
Expected: PASS (all prior tests still pass + 4 new doc tests). The signature-thread changes are backward-compatible (`docstring` defaults to `""`).

- [ ] **Step 5: Commit**

```bash
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py \
        packages/ennam-kg-indexer/tests/test_parsers/test_go.py
git commit -m "feat(indexer): GoParser doc-comment extraction with line-adjacency rule"
```

---

## Task 6: Resilience

Confirm the parser never raises on bad input — an unreadable file or syntactically broken Go returns `[]` or the parseable subset, never an exception. No production code change is expected (the `try/except OSError` and `has_error` log-and-continue from Task 1 already cover this); this task locks the behavior with tests.

**Files:**
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_go.py`
- Modify (only if a test fails): `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_go.py`:

```python
def test_broken_go_does_not_raise(tmp_path: Path) -> None:
    # Garbage / truncated source must not raise from parse().
    f = _write(tmp_path, "package main\n\nfunc Broken( { this is not go\n")
    symbols = GoParser().parse(f)  # must not raise
    assert isinstance(symbols, list)


def test_broken_go_extracts_clean_symbols(tmp_path: Path) -> None:
    # A clean decl before a broken one is still extracted.
    src = "package main\n\nfunc Good() {}\n\nfunc Bad( { nonsense\n"
    symbols = GoParser().parse(_write(tmp_path, src))
    assert any(s.name == "Good" for s in symbols)


def test_unreadable_file_returns_empty(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.go"
    assert GoParser().parse(missing) == []
```

- [ ] **Step 2: Run tests to verify they pass (or fail)**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_go.py -k "broken or unreadable" -v`
Expected: PASS — Task 1's `parse()` already handles `OSError` (→ `[]`) and `has_error` (→ log + extract subset). If any test fails, the parser is raising where it should log-and-continue; fix `parse()` to match `python_lang.py`'s pattern (do not change test expectations).

- [ ] **Step 3: Commit**

```bash
git add packages/ennam-kg-indexer/tests/test_parsers/test_go.py
git commit -m "test(indexer): lock GoParser resilience to unreadable and malformed input"
```

---

## Task 7: Containment edge (integration)

Prove the receiver→method `parent` flows through the full pipeline into edge creation, mirroring `test_engine_relative_paths.py::test_containment_edge_created`. A `.go` file with a struct + a method on it must produce ≥1 edge through `engine.full_scan` with a mocked KG client.

**Files:**
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_go.py`

- [ ] **Step 1: Write the failing test**

Append to `test_go.py` (note the new imports at the top of the appended block — keep imports grouped at file top when you add them):

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
async def test_go_containment_edge_created(tmp_path: Path) -> None:
    # struct Repo + method (r *Repo) Save() in the same file -> Repo->Save edge.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "repo.go").write_text(
        "package pkg\n\ntype Repo struct{}\n\nfunc (r *Repo) Save() error { return nil }\n"
    )
    client = _mock_kg_client()
    result = await IndexingEngine(client).full_scan("proj-go", str(tmp_path))
    assert result.edges_created >= 1, "Repo->Save containment edge must be created"
    edge = client.create_edge.call_args_list[0].args[0]
    assert edge["source_id"] == "n-1"
    assert edge["target_id"] == "n-1"
```

> Note: `test_go.py` was created in Task 1 with imports at the top. When adding `pytest`, `AsyncMock`, and `IndexingEngine` imports, move them up next to the existing `from __future__ import annotations` / `pathlib` imports so the file has a single import block (ruff will flag imports-not-at-top otherwise).

- [ ] **Step 2: Run test to verify it passes**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_go.py::test_go_containment_edge_created -v`
Expected: PASS — `GoParser` sets `parent="Repo"` on `Save`, the struct `Repo` is a CLASS, and the extractor keys the containment edge on `{file_path}:Repo:class` within the same file. If it FAILS with `edges_created == 0`, the receiver-type→parent linkage (Task 2) or the struct→CLASS mapping (Task 3) regressed.

- [ ] **Step 3: Commit**

```bash
git add packages/ennam-kg-indexer/tests/test_parsers/test_go.py
git commit -m "test(indexer): integration test for GoParser receiver->method containment edge"
```

---

## Task 8: Full-suite verification + lint

Confirm nothing regressed across the package and the new code passes lint/format.

**Files:** none (verification only)

- [ ] **Step 1: Run the full indexer test suite**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests -q`
Expected: PASS — all pre-existing tests plus the new Go tests. Zero failures.

- [ ] **Step 2: Lint and format the new/changed files**

Run:

```bash
cd $PY
uv run ruff check packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py \
                  packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/__init__.py \
                  packages/ennam-kg-indexer/tests/test_parsers/test_go.py
uv run ruff format packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py \
                   packages/ennam-kg-indexer/tests/test_parsers/test_go.py
```

Expected: ruff reports no errors (line-length 100, target py312). If `ruff format` changes anything, re-run the test suite to confirm still green.

- [ ] **Step 3: Smoke test against the real Go server (optional but recommended)**

Index a slice of the platform's own Go code to confirm real-world output, using the CLI's dry/list path if available. At minimum, parse one real file directly:

```bash
cd $PY
uv run python -c "from pathlib import Path; from ennam_kg_indexer.parsers.go_lang import GoParser; import glob; \
  fs=glob.glob('../ennam.kg.go/internal/**/*.go', recursive=True)[:3]; \
  [print(f, len(GoParser().parse(Path(f))), 'symbols') for f in fs]"
```

Expected: each file reports a non-zero symbol count with no traceback.

- [ ] **Step 4: Commit any formatting changes**

```bash
git add -A packages/ennam-kg-indexer
git commit -m "chore(indexer): ruff format GoParser and tests" --allow-empty
```

---

## Self-Review

**Spec coverage:**
- Scope (top-level exported + unexported, no struct fields) → Tasks 1, 2; unexported guarded by `test_unexported_function_included`. ✓
- const/var indexing (incl. multi-name) → Task 4. ✓
- Doc comments (line-adjacent godoc block) → Task 5. ✓
- No route detection, no imports/edges beyond containment, `decorators` always `[]` → enforced by `_make_symbol` (always `decorators=[]`); no route/import code added. ✓
- Construct→SymbolKind mapping (func/method/struct/interface/alias/const/var) → Tasks 1–4, each with a test. ✓
- Multi-name spec via identifier iteration (not `name` field) → Task 4 `test_var_multi_name`. ✓
- Recursive `_receiver_type` for generic receivers → Task 2 `test_method_generic_receiver`. ✓
- Registry wiring → Task 1 Step 4 + `test_parser_registered`. ✓
- Error handling (unreadable → `[]`, `has_error` → subset, missing name → skip, malformed receiver → `parent=None`) → Tasks 1, 2, 6. ✓
- Containment edge integration → Task 7. ✓
- Out-of-scope items (struct fields, route detection, import edges, generics type-params, grammar building) → not implemented, consistent with spec. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N" — all code blocks are complete and self-contained. ✓

**Type consistency:** Method names used consistently across tasks — `_walk_source_file`, `_handle_function`, `_handle_method`, `_handle_type`, `_handle_value_spec`, `_make_symbol`, `_signature_line`, `_receiver_type`, `_first_type_identifier`, `_doc_from_comments`, `_type_kind`, `_text`, `_child_text`, `_child_by_type`. `_make_symbol` signature `(node, source, fp, name, kind, parent, docstring="")` matches every call site. Handler signatures gain `docstring: str = ""` in Task 5, backward-compatible with earlier call sites. ✓

---

## Execution Handoff
