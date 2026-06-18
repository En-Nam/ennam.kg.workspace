# Dart Parser for `ennam-kg-indexer` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Dart **stub** (`parsers/dart.py`, currently raises `NotImplementedError`) with a real `DartParser` that extracts type-level + function/method symbols from `.dart` source into KG nodes — unlocking indexing of Flutter/Dart codebases via the existing CLI / `kg_index_source` flow.

**Architecture:** Rewrite `parsers/dart.py` (`DartParser(BaseParser)`) to walk the tree-sitter `dart` AST (from `tree-sitter-language-pack`), structured like `PythonParser`/`GoParser`. One recursive `_walk` routine handles both `source_file` children and each container body: it dispatches type declarations (class/mixin/enum/extension → `CLASS`, typedef → `TYPE_ALIAS`), top-level functions (`FUNCTION`), and class/mixin/enum/extension members (methods/constructors/getters/setters/operators → `METHOD`), nested via the `parent` field. Containment edges form automatically through the existing extractor.

**Tech Stack:** Python 3.12, `tree-sitter>=0.25.2`, `tree-sitter-language-pack` (provides the `dart` grammar), pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-06-06-dart-parser-design.md` (Approved). All grammar node types, name-extraction rules, and the member-classification approach below were verified empirically on 2026-06-07 against the installed `tree-sitter-language-pack` Dart grammar (nielsenko/tree-sitter-dart, precompiled).

---

## What's already done (do NOT redo)

The Markdown parser (landed earlier) already made the shared changes the Dart spec assumed it would make:

- **`pyproject.toml`**: `tree-sitter-language-pack>=0.9` is already a dependency and `tree-sitter>=0.25.2` is already the floor. **No pyproject change needed** — verified.
- **`parsers/__init__.py`**: `DartParser` is already imported and `_register(DartParser)` is already called (the stub kept the class name/registration). **No `__init__.py` change needed.**
- **`indexer/extractor.py`**: Dart emits `CLASS` parents + `relates_to` containment edges, both already handled by the existing `extract_edges` (CLASS is in the parent-kind set). **No extractor change needed.**
- **`scanner.py`**: `.dart` is already a discovered extension (the stub's `supported_extensions()` returned `{".dart"}`). **No scanner change needed.**

So this plan touches exactly **two files**: rewrite `parsers/dart.py`, and rewrite `tests/test_parsers/test_dart.py`.

## Clarifications beyond the spec's literal text (read first)

Empirical verification surfaced three refinements; all are folded into this plan:

1. **Existing stub test breaks.** `tests/test_parsers/test_dart.py::test_parse_raises_not_implemented` asserts the stub raises `NotImplementedError`. The real parser doesn't raise → that test must be **replaced**. Task 1 rewrites the whole file. (No other test breaks: `test_scanner.py:62` keeps `assert ".dart" in exts` — still true — though its inline comment "even though it raises" becomes stale; optionally drop that comment, not required.)

2. **Spec test #2's example is single-line.** `int topLevel(String s) => s.length;` is one line, so `line_end == line_start` — the spec's `line_end > line_start` assertion would **fail** on its own example. To meaningfully test that the span covers the body, this plan uses a **multi-line** function body in that test (`{ return s.length; }`).

3. **Factory constructor name.** The spec says take "text before the `formal_parameter_list`", but for a factory that text is `'factory Foo.make'` (includes the `factory` keyword). Verified cleaner rule: **join the signature's `identifier` children with `.`** → `Foo`, `Foo.named`, `Foo.make` (the `factory`/`const` keyword tokens aren't `identifier` nodes, so they drop out naturally). This plan uses identifier-join for both constructor and factory.

### Verified grammar facts (do not re-guess)

- **Top-level (`source_file` children):** `documentation_comment`, `function_signature` (+ a following `function_body` sibling), `type_alias`, `mixin_declaration`, `enum_declaration`, `extension_declaration`, `class_definition`.
- **Name extraction:** `name` field works for `class_definition` / `enum_declaration` / `extension_declaration` / `function_signature` / `getter_signature` / `setter_signature`. `name` field is **`None`** for `mixin_declaration` (use first `identifier` child) and `type_alias` (use first `type_identifier` child). Unnamed `extension on T {}` → `name` field `None` → **skip**.
- **Container body node type varies:** class & mixin → `class_body`; extension → `extension_body`; enum → `enum_body`. Locate by **matching the child whose type ends in `_body`** (do not hard-code `class_body`). `enum_body` also contains `enum_constant` children (skip them).
- **Members** are `method_signature` (with body) or `declaration` (no body / fields). Classify by **scanning the member's children for the first node whose type ends in `_signature`** (`function_signature`, `getter_signature`, `setter_signature`, `constructor_signature`, `factory_constructor_signature`, `operator_signature`). No `_signature` child → it's a field → **skip**. This naturally skips modifier tokens (`static`, `external`, `abstract`, `factory`, …) and sibling nodes (`initializers`).
- **Signature ↔ body pairing:** a member/function with a body parses as the `*_signature`/`method_signature`/`declaration` node **followed by a separate `function_body` sibling**. No body → no `function_body` sibling.
- **Constructor/factory name:** join `identifier` children with `.` (`Foo`, `Foo.named`, `Foo.make`). **Operator name:** `"operator " + <text between the `operator` keyword and the `formal_parameter_list`>` (verified for `+`, `==`, `[]`, `[]=`, unary `-`).

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/dart.py` | `DartParser` — Dart AST → `list[Symbol]` (replaces the stub) | **Rewrite** |
| `packages/ennam-kg-indexer/tests/test_parsers/test_dart.py` | All `DartParser` tests (replaces the stub test) | **Rewrite** |

Paths are relative to the workspace root. All commands run from `ennam.kg.python/` (the `uv` project root — `$PY`).

### Mirror references (read before starting)

- `parsers/python_lang.py` / `parsers/go_lang.py` — parser shape, helpers, error handling, doc-comment adjacency.
- `parsers/base.py` — `Symbol` + `SymbolKind` (`CLASS`, `METHOD`, `FUNCTION`, `TYPE_ALIAS` already exist).
- `tests/test_engine_relative_paths.py` — the mocked-`full_scan` integration test pattern (Task 9 mirrors it).

---

## Task 1: Replace the stub — full parser + top-level functions

Replace the stub body with the complete `DartParser` (the recursive `_walk` + all helpers), then rewrite `test_dart.py` with the registration/non-stub regression guard and the top-level-function test. The parser is a cohesive recursive module, so it is written whole here; Tasks 2–8 add TDD coverage per construct (each expects PASS against this parser, with a fix path if a regression is found).

**Files:**
- Rewrite: `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/dart.py`
- Rewrite: `packages/ennam-kg-indexer/tests/test_parsers/test_dart.py`

- [ ] **Step 1: Write the failing tests (rewrite `test_dart.py`)**

Replace the entire contents of `packages/ennam-kg-indexer/tests/test_parsers/test_dart.py` with:

```python
"""Tests for the Dart parser."""

from __future__ import annotations

from pathlib import Path

from ennam_kg_indexer.parsers import SymbolKind, get_parser
from ennam_kg_indexer.parsers.dart import DartParser


def _write(tmp_path: Path, body: str) -> Path:
    f = tmp_path / "sample.dart"
    f.write_text(body)
    return f


def test_parser_registered(tmp_path: Path) -> None:
    parser = get_parser(_write(tmp_path, "class A {}\n"))
    assert parser is not None
    assert isinstance(parser, DartParser)


def test_supported_extensions() -> None:
    assert DartParser().supported_extensions() == {".dart"}


def test_parse_does_not_raise_not_implemented(tmp_path: Path) -> None:
    # Regression guard against the old stub, which raised NotImplementedError.
    f = _write(tmp_path, "class A {}\n")
    result = DartParser().parse(f)  # must not raise
    assert isinstance(result, list)


def test_top_level_function(tmp_path: Path) -> None:
    # Multi-line body so the span (signature + body) is meaningfully line_end > line_start.
    f = _write(tmp_path, "int topLevel(String s) {\n  return s.length;\n}\n")
    symbols = DartParser().parse(f)
    fn = next(s for s in symbols if s.name == "topLevel")
    assert fn.kind == SymbolKind.FUNCTION
    assert fn.parent is None
    assert fn.line_end > fn.line_start  # span covers the body
    assert fn.body_hash
    assert fn.signature.startswith("int topLevel")
    assert fn.decorators == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_dart.py -v`
Expected: FAIL — `test_top_level_function` raises `NotImplementedError` from the stub (and `test_parse_does_not_raise_not_implemented` fails for the same reason).

- [ ] **Step 3: Rewrite `dart.py` with the full parser**

Replace the entire contents of `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/dart.py` with:

```python
"""Dart parser using the tree-sitter `dart` grammar (language-pack).

Extracts type declarations (class/mixin/enum/extension → CLASS, typedef →
TYPE_ALIAS), top-level functions (FUNCTION), and type members
(methods/constructors/getters/setters/operators → METHOD). Mirrors the
PythonParser/GoParser design. Fields, top-level variables, enum constants,
annotations, and imports are intentionally not extracted.
"""

from __future__ import annotations

import logging
from pathlib import Path

from tree_sitter import Parser
from tree_sitter_language_pack import get_language

from .base import BaseParser, Symbol, SymbolKind

logger = logging.getLogger(__name__)

DART_LANGUAGE = get_language("dart")

# Member-classification: a member is a method iff one of its children is a
# node whose type ends in this suffix (function/getter/setter/constructor/
# factory_constructor/operator signature). Otherwise it is a field → skip.
_SIGNATURE_SUFFIX = "_signature"


class DartParser(BaseParser):
    """Extracts type-level and function/method symbols from Dart source."""

    def __init__(self) -> None:
        self._parser = Parser(DART_LANGUAGE)

    def supported_extensions(self) -> set[str]:
        return {".dart"}

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
        self._walk(tree.root_node.children, source, str(file_path), None, symbols)
        return symbols

    # ------------------------------------------------------------------
    # Traversal (shared by source_file and each container body)
    # ------------------------------------------------------------------

    def _walk(
        self,
        children: list,
        source: bytes,
        fp: str,
        parent: str | None,
        symbols: list[Symbol],
    ) -> None:
        """Walk a child list, emitting symbols. `parent` is None at top level,
        else the enclosing type name (for members)."""
        pending_doc: list = []
        kids = list(children)
        for i, child in enumerate(kids):
            ntype = child.type  # type: ignore[attr-defined]

            if ntype == "documentation_comment":
                # Accumulate consecutive doc comments; reset on a blank-line gap.
                if pending_doc and child.start_point[0] > pending_doc[-1].end_point[0] + 1:  # type: ignore[attr-defined]
                    pending_doc = []
                pending_doc.append(child)
                continue

            doc = self._leading_doc(pending_doc, child, source)
            pending_doc = []

            nxt = kids[i + 1] if i + 1 < len(kids) else None
            body = nxt if (nxt is not None and nxt.type == "function_body") else None  # type: ignore[attr-defined]

            if ntype in (
                "class_definition",
                "mixin_declaration",
                "enum_declaration",
                "extension_declaration",
            ):
                name = self._type_name(child, source)
                if not name:
                    continue  # unnamed extension → skip
                symbols.append(
                    self._make(child, None, source, fp, name, SymbolKind.CLASS, parent, doc)
                )
                container_body = self._child_ending_in(child, "_body")
                if container_body is not None:
                    self._walk(container_body.children, source, fp, name, symbols)  # type: ignore[attr-defined]

            elif ntype == "type_alias":
                name = self._first_child_text(child, "type_identifier", source)
                if name:
                    symbols.append(
                        self._make(child, None, source, fp, name, SymbolKind.TYPE_ALIAS, parent, doc)
                    )

            elif ntype == "function_signature":
                name = self._child_text(child, "name", source)
                if name:
                    symbols.append(
                        self._make(child, body, source, fp, name, SymbolKind.FUNCTION, parent, doc)
                    )

            elif ntype in ("method_signature", "declaration"):
                sig = self._classify_member(child)
                if sig is None:
                    continue  # field → skip
                name = self._node_name(sig, source)
                if name:
                    symbols.append(
                        self._make(child, body, source, fp, name, SymbolKind.METHOD, parent, doc)
                    )

            # function_body (consumed via pairing), enum_constant, tokens → ignored

    # ------------------------------------------------------------------
    # Classification + name extraction
    # ------------------------------------------------------------------

    def _classify_member(self, node: object) -> object | None:
        """Return the inner `*_signature` node of a member, or None for a field."""
        for child in node.children:  # type: ignore[attr-defined]
            if child.type.endswith(_SIGNATURE_SUFFIX):  # type: ignore[attr-defined]
                return child
        return None

    def _type_name(self, node: object, source: bytes) -> str | None:
        """Name of a class/mixin/enum/extension declaration."""
        if node.type == "mixin_declaration":  # type: ignore[attr-defined]
            return self._first_child_text(node, "identifier", source)
        return self._child_text(node, "name", source)

    def _node_name(self, sig: object, source: bytes) -> str | None:
        """Name from an inner `*_signature` node, per the verified rules."""
        stype = sig.type  # type: ignore[attr-defined]
        if stype in ("constructor_signature", "factory_constructor_signature"):
            # Join identifier children with '.' → Foo, Foo.named, Foo.make.
            # (The `factory`/`const` keyword tokens are not `identifier` nodes.)
            ids = [
                self._text(c, source)
                for c in sig.children  # type: ignore[attr-defined]
                if c.type == "identifier"
            ]
            return ".".join(ids) if ids else None
        if stype == "operator_signature":
            kw = self._child_by_type(sig, "operator")
            fpl = self._child_by_type(sig, "formal_parameter_list")
            if kw is not None and fpl is not None:
                op = source[kw.end_byte : fpl.start_byte].decode("utf-8", errors="replace").strip()  # type: ignore[attr-defined]
                return f"operator {op}"
            return None
        # function/getter/setter signatures: the `name` field works.
        name = self._child_text(sig, "name", source)
        if name:
            return name
        return self._first_child_text(sig, "identifier", source)

    # ------------------------------------------------------------------
    # Symbol construction
    # ------------------------------------------------------------------

    def _make(
        self,
        decl: object,
        body: object | None,
        source: bytes,
        fp: str,
        name: str,
        kind: SymbolKind,
        parent: str | None,
        doc: str,
    ) -> Symbol:
        end_node = body if body is not None else decl
        return Symbol(
            name=name,
            kind=kind,
            file_path=fp,
            line_start=decl.start_point[0] + 1,  # type: ignore[attr-defined]
            line_end=end_node.end_point[0] + 1,  # type: ignore[attr-defined]
            signature=self._signature_line(decl, source),
            body_hash=self._compute_body_hash(source, decl.start_byte, end_node.end_byte),  # type: ignore[attr-defined]
            parent=parent,
            docstring=doc,
            decorators=[],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _signature_line(self, node: object, source: bytes) -> str:
        """Text up to the first `{`, `=>`, or `;` (whichever first), collapsed."""
        text = self._text(node, source)
        cuts = [text.find(t) for t in ("{", "=>", ";")]
        cuts = [c for c in cuts if c != -1]
        head = text if not cuts else text[: min(cuts)]
        return " ".join(head.split())

    def _leading_doc(self, pending_doc: list, decl_node: object, source: bytes) -> str:
        """Join an adjacent `documentation_comment` block (strip `///` / `/** */`)."""
        if not pending_doc:
            return ""
        last = pending_doc[-1]
        if last.end_point[0] + 1 != decl_node.start_point[0]:  # type: ignore[attr-defined]
            return ""
        lines = [self._text(c, source).lstrip("/* ").rstrip("*/ ").strip() for c in pending_doc]
        return "\n".join(lines).strip()

    def _text(self, node: object, source: bytes) -> str:
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")  # type: ignore[attr-defined]

    def _child_text(self, node: object, field_name: str, source: bytes) -> str | None:
        child = node.child_by_field_name(field_name)  # type: ignore[attr-defined]
        if child is None:
            return None
        return self._text(child, source)

    def _first_child_text(self, node: object, type_name: str, source: bytes) -> str | None:
        child = self._child_by_type(node, type_name)
        return self._text(child, source) if child is not None else None

    def _child_by_type(self, node: object, type_name: str) -> object | None:
        for child in node.children:  # type: ignore[attr-defined]
            if child.type == type_name:  # type: ignore[attr-defined]
                return child
        return None

    def _child_ending_in(self, node: object, suffix: str) -> object | None:
        for child in node.children:  # type: ignore[attr-defined]
            if child.type.endswith(suffix):  # type: ignore[attr-defined]
                return child
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_dart.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/dart.py \
        packages/ennam-kg-indexer/tests/test_parsers/test_dart.py
git commit -m "feat(indexer): replace Dart stub with real tree-sitter DartParser (top-level functions)"
```

---

## Task 2: Classes + methods (parent), incl. static modifier

Verify class extraction, member methods with `parent`, and that the `_signature`-suffix scan skips the `static` modifier.

**Files:**
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_dart.py`
- Modify (only if a test fails): `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/dart.py`

- [ ] **Step 1: Write the tests**

Append to `test_dart.py`:

```python
def test_class_and_method_parent(tmp_path: Path) -> None:
    f = _write(tmp_path, "class Foo {\n  int bar(int a) => a;\n}\n")
    symbols = DartParser().parse(f)
    foo = next(s for s in symbols if s.name == "Foo")
    bar = next(s for s in symbols if s.name == "bar")
    assert foo.kind == SymbolKind.CLASS
    assert foo.parent is None
    assert bar.kind == SymbolKind.METHOD
    assert bar.parent == "Foo"


def test_static_method_skips_modifier(tmp_path: Path) -> None:
    # method_signature is [static, function_signature]; classification must scan
    # for the *_signature child, not read the first child (the `static` token).
    f = _write(tmp_path, "class Foo {\n  static int s() => 1;\n}\n")
    s = next(x for x in DartParser().parse(f) if x.name == "s")
    assert s.kind == SymbolKind.METHOD
    assert s.parent == "Foo"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_dart.py -k "class_and_method or static_method" -v`
Expected: PASS — `class_definition` → CLASS, body members classified via the `_signature` scan (which ignores `static`), `parent` set to the enclosing type. If FAIL, the `_walk` recursion or `_classify_member` regressed.

- [ ] **Step 3: Commit**

```bash
git add packages/ennam-kg-indexer/tests/test_parsers/test_dart.py
git commit -m "test(indexer): Dart class/method parent + static-modifier classification"
```

---

## Task 3: Constructors (default, named, factory, with-body)

Verify constructor name extraction (identifier-join) including the factory variant and a constructor with an initializer list + body.

**Files:**
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_dart.py`
- Modify (only if a test fails): `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/dart.py`

- [ ] **Step 1: Write the tests**

Append to `test_dart.py`:

```python
def test_constructors(tmp_path: Path) -> None:
    src = (
        "class Foo {\n"
        "  Foo(this.x);\n"
        "  Foo.named(this.x);\n"
        "  factory Foo.make() => Foo(1);\n"
        "  int x;\n"
        "}\n"
    )
    names = {s.name for s in DartParser().parse(_write(tmp_path, src)) if s.kind == SymbolKind.METHOD}
    assert "Foo" in names           # default constructor
    assert "Foo.named" in names     # named constructor
    assert "Foo.make" in names      # factory (factory_constructor_signature, not constructor_signature)


def test_constructor_with_body_span(tmp_path: Path) -> None:
    # Initializer list + body: method_signature [constructor_signature, initializers] + function_body.
    src = "class Foo {\n  Foo.init(this.x) : assert(x > 0) {\n    print(x);\n  }\n  int x;\n}\n"
    init = next(s for s in DartParser().parse(_write(tmp_path, src)) if s.name == "Foo.init")
    assert init.kind == SymbolKind.METHOD
    assert init.parent == "Foo"
    assert init.line_end > init.line_start  # span covers the body
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_dart.py -k "constructors or constructor_with_body" -v`
Expected: PASS — `_node_name` joins `identifier` children for `constructor_signature`/`factory_constructor_signature` (so `factory` keyword drops out → `Foo.make`), and the body pairing covers the initializer-list constructor's body. If `Foo.make` FAILS, the `factory_constructor_signature` branch regressed.

- [ ] **Step 3: Commit**

```bash
git add packages/ennam-kg-indexer/tests/test_parsers/test_dart.py
git commit -m "test(indexer): Dart constructors (default/named/factory/with-body)"
```

---

## Task 4: Getters, setters, operators

Verify getter/setter names and operator-overload naming (the `_signature`-suffix scan catches `operator_signature`).

**Files:**
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_dart.py`
- Modify (only if a test fails): `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/dart.py`

- [ ] **Step 1: Write the tests**

Append to `test_dart.py`:

```python
def test_getter_setter(tmp_path: Path) -> None:
    f = _write(tmp_path, "class V {\n  int get val => 1;\n  set val(int v) {}\n}\n")
    methods = [s for s in DartParser().parse(f) if s.kind == SymbolKind.METHOD]
    assert any(m.name == "val" and m.parent == "V" for m in methods)


def test_operators(tmp_path: Path) -> None:
    src = (
        "class V {\n"
        "  V operator +(V o) => this;\n"
        "  bool operator ==(Object o) => true;\n"
        "  int operator [](int i) => i;\n"
        "  void operator []=(int i, int v) {}\n"
        "}\n"
    )
    names = {s.name for s in DartParser().parse(_write(tmp_path, src)) if s.kind == SymbolKind.METHOD}
    assert {"operator +", "operator ==", "operator []", "operator []="} <= names
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_dart.py -k "getter_setter or operators" -v`
Expected: PASS — getter/setter names come from the `name` field; operator names come from the text between the `operator` keyword and the `formal_parameter_list`. If an operator FAILS, the `operator_signature` branch in `_node_name` regressed.

- [ ] **Step 3: Commit**

```bash
git add packages/ennam-kg-indexer/tests/test_parsers/test_dart.py
git commit -m "test(indexer): Dart getters/setters/operators"
```

---

## Task 5: Abstract methods (no body) + field skip

Verify an abstract method (a `declaration` with a `function_signature`, no body) is captured, and a field (a `declaration` with no `*_signature`) is skipped.

**Files:**
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_dart.py`
- Modify (only if a test fails): `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/dart.py`

- [ ] **Step 1: Write the tests**

Append to `test_dart.py`:

```python
def test_abstract_method(tmp_path: Path) -> None:
    # Abstract members parse as `declaration` (no function_body), not method_signature.
    f = _write(tmp_path, "abstract class A {\n  void doThing();\n}\n")
    doing = next(s for s in DartParser().parse(f) if s.name == "doThing")
    assert doing.kind == SymbolKind.METHOD
    assert doing.parent == "A"


def test_field_skipped(tmp_path: Path) -> None:
    # A field declaration has no *_signature child → not indexed.
    f = _write(tmp_path, "class C {\n  int x = 0;\n}\n")
    assert not any(s.name == "x" for s in DartParser().parse(f))
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_dart.py -k "abstract_method or field_skipped" -v`
Expected: PASS — `declaration` with `function_signature` → METHOD; `declaration` with no `*_signature` → `_classify_member` returns None → skipped.

- [ ] **Step 3: Commit**

```bash
git add packages/ennam-kg-indexer/tests/test_parsers/test_dart.py
git commit -m "test(indexer): Dart abstract methods + field skip"
```

---

## Task 6: mixin / enum / extension / typedef + body-node variance

Verify the non-class type declarations, typedef name extraction, the unnamed-extension skip, and that members inside `extension_body`/`enum_body` are found (the `_body`-suffix match) while enum constants are skipped.

**Files:**
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_dart.py`
- Modify (only if a test fails): `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/dart.py`

- [ ] **Step 1: Write the tests**

Append to `test_dart.py`:

```python
def test_mixin_enum_extension_typedef(tmp_path: Path) -> None:
    def kinds(src):
        return {(s.name, s.kind) for s in DartParser().parse(_write(tmp_path, src))}

    assert ("Logger", SymbolKind.CLASS) in kinds("mixin Logger {}\n")        # name via identifier
    assert ("Color", SymbolKind.CLASS) in kinds("enum Color { red, green }\n")
    assert ("StrX", SymbolKind.CLASS) in kinds("extension StrX on String {}\n")
    assert kinds("extension on int {}\n") == set()                            # unnamed extension → no symbol
    assert ("IntList", SymbolKind.TYPE_ALIAS) in kinds("typedef IntList = List<int>;\n")
    assert any(
        n == "Compare" and k == SymbolKind.TYPE_ALIAS
        for (n, k) in kinds("typedef Compare = int Function(int a, int b);\n")
    )


def test_members_in_extension_and_enum_body(tmp_path: Path) -> None:
    # Regression guard for the _body-suffix match (not hard-coded class_body).
    ext = _write(tmp_path, "extension StrX on String { String shout() => toUpperCase(); }\n")
    assert any(s.name == "shout" and s.parent == "StrX" for s in DartParser().parse(ext))

    enum_src = "enum Planet { earth, mars; bool get habitable => true; }\n"
    syms = DartParser().parse(_write(tmp_path, enum_src))
    assert any(s.name == "habitable" and s.parent == "Planet" for s in syms)
    assert not any(s.name in ("earth", "mars") for s in syms)  # enum constants not indexed
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_dart.py -k "mixin_enum_extension_typedef or members_in_extension" -v`
Expected: PASS — mixin name via first `identifier`, typedef via first `type_identifier`, unnamed extension skipped (no `name` field), and `_child_ending_in(node, "_body")` finds `extension_body`/`enum_body` so their members are walked while `enum_constant` children are ignored. If members FAIL, the body lookup hard-coded `class_body`.

- [ ] **Step 3: Commit**

```bash
git add packages/ennam-kg-indexer/tests/test_parsers/test_dart.py
git commit -m "test(indexer): Dart mixin/enum/extension/typedef + body-node variance"
```

---

## Task 7: Doc comments + adjacency

Verify a `///` doc comment directly above a declaration attaches, and one separated by a blank line does not.

**Files:**
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_dart.py`
- Modify (only if a test fails): `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/dart.py`

- [ ] **Step 1: Write the tests**

Append to `test_dart.py`:

```python
def test_doc_comment_adjacent(tmp_path: Path) -> None:
    f = _write(tmp_path, "class K {\n  /// Persists.\n  int save() => 1;\n}\n")
    save = next(s for s in DartParser().parse(f) if s.name == "save")
    assert "Persists." in save.docstring


def test_doc_comment_blank_gap_not_attached(tmp_path: Path) -> None:
    f = _write(tmp_path, "class K {\n  /// Far.\n\n  int save() => 1;\n}\n")
    save = next(s for s in DartParser().parse(f) if s.name == "save")
    assert save.docstring == ""
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_dart.py -k doc_comment -v`
Expected: PASS — `_leading_doc` attaches the accumulated `documentation_comment` block only when its last line is directly above the declaration. If the blank-gap case FAILS, the adjacency check regressed.

- [ ] **Step 3: Commit**

```bash
git add packages/ennam-kg-indexer/tests/test_parsers/test_dart.py
git commit -m "test(indexer): Dart doc-comment extraction with line-adjacency"
```

---

## Task 8: Resilience

Confirm malformed/unreadable Dart never raises.

**Files:**
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_dart.py`
- Modify (only if a test fails): `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/dart.py`

- [ ] **Step 1: Write the tests**

Append to `test_dart.py`:

```python
def test_broken_dart_does_not_raise(tmp_path: Path) -> None:
    f = _write(tmp_path, "class { borked <<< no name {{{ \n")
    result = DartParser().parse(f)  # must not raise
    assert isinstance(result, list)


def test_unreadable_file_returns_empty(tmp_path: Path) -> None:
    assert DartParser().parse(tmp_path / "does_not_exist.dart") == []
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_dart.py -k "broken or unreadable" -v`
Expected: PASS — `parse()` returns `[]` on `OSError` and logs-and-extracts on `has_error`. If a test raises, align `parse()` with the `python_lang.py`/`go_lang.py` pattern (do not change the test).

- [ ] **Step 3: Commit**

```bash
git add packages/ennam-kg-indexer/tests/test_parsers/test_dart.py
git commit -m "test(indexer): Dart resilience to malformed/unreadable input"
```

---

## Task 9: Containment edge (integration)

Prove the type→method `parent` flows through `engine.full_scan` into an edge (extractor unchanged — Dart `CLASS` is already in the parent-kind set and uses `relates_to`).

**Files:**
- Test: `packages/ennam-kg-indexer/tests/test_parsers/test_dart.py`

- [ ] **Step 1: Write the test**

Append to `test_dart.py` (hoist the new imports to the top import block of the file):

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
async def test_full_scan_creates_containment_edge(tmp_path: Path) -> None:
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "foo.dart").write_text("class Foo {\n  int bar() => 1;\n}\n")
    client = _mock_kg_client()
    result = await IndexingEngine(client).full_scan("proj-dart", str(tmp_path))
    assert result.edges_created >= 1, "Foo->bar containment edge must be created"
    edge = client.create_edge.call_args_list[0].args[0]
    assert edge["relationship"] == "relates_to"  # code containment uses relates_to
    assert edge["source_id"] == "n-1"
    assert edge["target_id"] == "n-1"
    assert result.errors == []
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_dart.py::test_full_scan_creates_containment_edge -v`
Expected: PASS — the scanner discovers `.dart` (already supported), `DartParser` sets `bar.parent = "Foo"`, `Foo` is a `CLASS`, and `extract_edges` keys the edge on `{file_path}:Foo:class` in the same file. If `edges_created == 0`, the `parent` linkage (Task 2) regressed.

- [ ] **Step 3: Commit**

```bash
git add packages/ennam-kg-indexer/tests/test_parsers/test_dart.py
git commit -m "test(indexer): integration — Dart type->method containment edge"
```

---

## Task 10: Full-suite verification + lint

**Files:** none (verification only)

- [ ] **Step 1: Run the full indexer test suite**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests -q`
Expected: PASS — all pre-existing tests plus the new Dart tests. Zero failures. (The old stub test was replaced in Task 1; no other pre-existing test asserted Dart raised, so nothing else needs updating.)

- [ ] **Step 2: Lint and format**

Run:

```bash
cd $PY
uv run ruff check packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/dart.py \
                  packages/ennam-kg-indexer/tests/test_parsers/test_dart.py
uv run ruff format packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/dart.py \
                   packages/ennam-kg-indexer/tests/test_parsers/test_dart.py
```

Expected: ruff reports no errors (line-length 100, target py312). If `ruff format` changes anything, re-run the suite to confirm still green.

- [ ] **Step 3: Smoke test against a real Dart repo**

```bash
cd $PY
uv run python -c "
from pathlib import Path
from ennam_kg_indexer.parsers.dart import DartParser
import glob
fs = glob.glob('/Users/danhtrinh/Projects/Exnodes/Salonbookly/Sources/mobile_sources/mobile.customer_2_versions/**/*.dart', recursive=True)[:3]
p = DartParser()
for f in fs:
    syms = p.parse(Path(f))
    print(Path(f).name, '->', len(syms), 'symbols')
"
```

Expected: each `.dart` file reports a symbol count with no traceback. (If the path has no `.dart` files, substitute any Dart repo; this step is a sanity check, not a hard gate.)

- [ ] **Step 4: Commit any formatting changes**

```bash
git add -A packages/ennam-kg-indexer
git commit -m "chore(indexer): ruff format DartParser and tests" --allow-empty
```

---

## Self-Review

**Spec coverage (the 11 test cases):**
- #1 Registration & non-stub → Task 1 (`test_parser_registered`, `test_parse_does_not_raise_not_implemented`). ✓
- #2 Top-level function span → Task 1 (multi-line body so `line_end > line_start` is meaningful — clarification #2). ✓
- #3 Class + methods + static modifier → Task 2. ✓
- #4 Constructors (default/named/factory/with-body) → Task 3 (identifier-join naming — clarification #3). ✓
- #5 Getter/setter/operator → Task 4. ✓
- #6 Abstract method (no body) → Task 5. ✓
- #7 Field skipped → Task 5. ✓
- #8 mixin/enum/extension/typedef (+ unnamed-extension skip, function typedef) → Task 6. ✓
- #8b Members in extension_body/enum_body (+ enum constants skipped) → Task 6. ✓
- #9 Doc comment + adjacency → Task 7. ✓
- #10 Containment edge (integration) → Task 9. ✓
- #11 Resilience → Task 8. ✓

**Decisions / mapping table coverage:** class/mixin/enum/extension → CLASS; typedef → TYPE_ALIAS; top-level function → FUNCTION; members via `_signature`-suffix scan → METHOD; constructors/getters/setters/operators as METHOD; fields/top-level vars/enum constants skipped; `decorators=[]`, `imports` empty; doc comments captured. All in `_walk`/`_classify_member`/`_node_name`. ✓

**Already-done / no-op confirmations:** pyproject (dep + tree-sitter floor), `__init__.py` registration, extractor, scanner — all unchanged, verified present. ✓

**Clarifications surfaced:** stub test replacement (Task 1), single-line span (Task 1 multi-line body), factory identifier-join naming (Task 3) — all flagged at top.

**Out of scope (not implemented, per spec):** Flutter widget detection, fields/top-level vars, annotations/imports edges, mixin `on`/`implements` edges, generic type-params, migrating py/ts/go parsers. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N" — every code block is complete.

**Type consistency:** Method names consistent — `parse`, `_walk`, `_classify_member`, `_type_name`, `_node_name`, `_make`, `_signature_line`, `_leading_doc`, `_text`, `_child_text`, `_first_child_text`, `_child_by_type`, `_child_ending_in`. `_make(decl, body, source, fp, name, kind, parent, doc)` matches every call site. `SymbolKind.CLASS/METHOD/FUNCTION/TYPE_ALIAS` all pre-exist in `base.py`. ✓

---

## Execution Handoff
