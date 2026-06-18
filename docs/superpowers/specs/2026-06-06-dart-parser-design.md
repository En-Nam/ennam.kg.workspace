# Dart Parser for `ennam-kg-indexer` — Design Spec

**Date**: 2026-06-06
**Status**: Approved (design)
**Goal**: Replace the Dart **stub** (`parsers/dart.py`, currently raises `NotImplementedError`) with a real `DartParser` that extracts symbols from `.dart` source into KG nodes — unlocking indexing of Flutter / Dart codebases (e.g. `mobile.customer_2_versions`) via the existing CLI / `kg_index_source` MCP tool.

**Grammar source**: [nielsenko/tree-sitter-dart](https://github.com/nielsenko/tree-sitter-dart), consumed **precompiled** via the `tree-sitter-language-pack` PyPI package (no source build).

**Depends on**: `ennam-kg-indexer` package (parsers/, engine, differ — unchanged). Mirrors the existing `PythonParser`/`GoParser` design.

---

## Context & the packaging problem (the reason Dart was a stub)

`tree-sitter-dart` is **not published on PyPI** (confirmed 2026-06-06), which is why `dart.py` has been a stub. Three options were weighed; **`tree-sitter-language-pack` won** and its packageability into `ennam-kg-indexer` was verified:

| Check | Result |
|-------|--------|
| Dart present in pack? | ✅ `get_language("dart")` loads; `Parser(lang).parse(bytes)` parses a real Dart sample with `has_error == False` |
| Multi-platform wheels? | ✅ macOS (x86_64 + arm64), Linux (x86_64 + aarch64), **Windows (amd64 + arm64)** — `pip install` needs no compiler (critical: indexing runs on Windows) |
| Wheel size | ✅ ~2 MB per platform — grammars are **inside the wheel** (no runtime download); not the heavyweight bundle initially feared |
| Dependency constraint | `tree-sitter>=0.25.2` — the package already resolves `tree-sitter` 0.25.2; an ephemeral `uv run --with tree-sitter-language-pack` in the package's own env loaded Dart with **no conflict** against the existing `tree-sitter-python/typescript/go` deps |
| Grammar provenance | The pack's Dart grammar **is** nielsenko/tree-sitter-dart, precompiled — honours the requested grammar |

**Decision:** add `tree-sitter-language-pack` as a dependency of `ennam-kg-indexer`, and **bump the package's `tree-sitter` floor to `>=0.25.2`** to match. Keep the individual `tree-sitter-python/typescript/go` packages for the existing parsers (no refactor — surgical change); `tree-sitter-language-pack` is used **only** for Dart. The minor grammar redundancy (the pack also contains py/ts/go) is harmless at ~2 MB.

> Registry note: `parsers/__init__.py` already imports `DartParser` from `dart.py` and calls `_register(DartParser)`. Replacing the stub's body keeps the class name and registration unchanged — **no `__init__.py` edit needed**. `discover_files`/`filter_changed` already include `.dart` (the stub's `supported_extensions()` returns `{".dart"}`), so `.dart` files are already discovered — today they error per-file on the stub's `NotImplementedError`; this spec makes them parse.

---

## Decisions (confirmed)

| # | Decision | Choice |
|---|----------|--------|
| Packaging | Grammar source | `tree-sitter-language-pack` (`get_language("dart")`); add dep, bump tree-sitter floor |
| Scope | What to extract | **Type-level + functions/methods**, mirroring Python/Go. Include constructors and getters/setters as `METHOD`. **Skip** struct/class fields and top-level variables (mirrors Python skipping attributes). |
| Flutter widgets | Detect `StatelessWidget`/`StatefulWidget` subclasses → `WIDGET`? | **No** (out of scope for v1; classes are still captured as `CLASS`). |
| Doc comments | Capture? | **Yes** — Dart `documentation_comment` (`///`, `/** */`) nodes immediately preceding a declaration (line-adjacent), mirroring the Go parser's doc handling. |
| `decorators` / `imports` | — | Always `[]` (annotations and imports not modeled; only containment edges, which work). |

---

## Construct → SymbolKind mapping (verified against tree-sitter-language-pack Dart / nielsenko grammar)

### Top level (`source_file` children)

| Dart | node | SymbolKind | name extraction |
|------|------|------------|-----------------|
| `class Foo {}` / `abstract class S {}` | `class_definition` | `CLASS` | `child_by_field_name("name")` → works |
| `mixin Logger {}` | `mixin_declaration` | `CLASS` | **first `identifier` child** (the `name` field is `None`) |
| `enum Color {…}` | `enum_declaration` | `CLASS` | `child_by_field_name("name")` → works |
| `extension StrX on String {…}` | `extension_declaration` | `CLASS` | `child_by_field_name("name")`; **`None` for an unnamed `extension on T {}` → skip** |
| `typedef IntList = List<int>;` | `type_alias` | `TYPE_ALIAS` | **first `type_identifier` child** (the `name` field is `None`) |
| `int topLevel(String s) => …` | `function_signature` **+ following `function_body` sibling** | `FUNCTION` | `child_by_field_name("name")` on the signature |

### Class / mixin / enum / extension members (walk the `class_body`)

Members are irregular — both `method_signature` (members **with** a body) and `declaration` (members **without** a body: abstract methods, constructors, fields) wrap an inner signature node. **Classify by scanning the member's children for the first node whose type ends in `_signature`** (a robust rule that future-proofs against grammar additions — verified there are at least six such variants). If none is found, it's a field → skip.

| Inner `*_signature` node | SymbolKind | name | parent |
|--------------------------|------------|------|--------|
| `function_signature` | `METHOD` | signature `name` field / first `identifier` | enclosing type |
| `getter_signature` | `METHOD` | `identifier` child | enclosing type |
| `setter_signature` | `METHOD` | `identifier` child | enclosing type |
| `constructor_signature` | `METHOD` | text before the `formal_parameter_list` (`Foo`, or `Foo.named`) | enclosing type |
| `factory_constructor_signature` | `METHOD` | text before the `formal_parameter_list` (`Foo.make`) | enclosing type |
| `operator_signature` | `METHOD` | `"operator " + <operator token>` (e.g. `operator +`, `operator ==`) | enclosing type |
| *(no `*_signature` child)* — field, e.g. `declaration` with `type_identifier` + `initialized_identifier_list` | — | — | **skip** |

Modifier tokens (`static`, `external`, `abstract`, `factory`, `const`, `final`, `late`, `covariant`) and sibling nodes like `initializers` are naturally ignored by the scan because they do not end in `_signature` (verified: a static method is `method_signature` → `[static, function_signature]`; a constructor with an initializer list is `method_signature` → `[constructor_signature, initializers]` + `function_body`).

---

## Component design

**Rewrite:** `parsers/dart.py` — `DartParser(BaseParser)`, structured like `PythonParser`/`GoParser`:

- Module-level: `from tree_sitter_language_pack import get_language`; `DART_LANGUAGE = get_language("dart")`; constructor builds `Parser(DART_LANGUAGE)`.
- `supported_extensions() -> {".dart"}`.
- `parse(file_path)`: read bytes (`OSError` → log + `[]`); parse; on `has_error` log a warning and extract what parses (mirror Python/Go); walk `source_file` children.

**Walk (`source_file` and each container body share one routine):**
- Maintain a `pending_doc` accumulator of consecutive `documentation_comment` siblings; attach to the next declaration **only if line-adjacent** (last comment's end row is the row directly above the declaration's start row); any non-doc, non-declaration node resets it.
- Dispatch by node type:
  - `class_definition` / `mixin_declaration` / `enum_declaration` / `extension_declaration` → emit the type symbol (CLASS per table; skip an unnamed extension), then **recurse into the type's body child to emit members** with `parent` = the type's name. **The body node type differs per construct (verified):** `class` and `mixin` → `class_body`; `extension` → `extension_body`; `enum` → `enum_body`. Locate it by matching the child whose type ends in `_body` (do **not** hard-code `class_body`, or extension/enum members are silently missed). Inside `enum_body`, skip `enum_constant` children (enum values are out of scope, like fields).
  - `type_alias` → emit `TYPE_ALIAS`.
  - `function_signature` → emit `FUNCTION` (pair with the next `function_body` sibling for the end span; see pairing).
  - `method_signature` → classify by inner node → emit `METHOD` (pair with next `function_body`).
  - `declaration` (member context) → inspect inner node: `constructor_signature` → constructor METHOD; `function_signature`/`getter_signature`/`setter_signature` → abstract METHOD; otherwise a field → **skip**.

**Signature ↔ body pairing (verified):** a member/function with a body parses as `*_signature` (or `method_signature`) **followed by a separate `function_body` sibling**. A member without a body (abstract method, or a `;`-terminated declaration) has no `function_body` sibling. So the symbol span is:
- `line_start` = signature node start row + 1.
- `line_end` = the following `function_body` sibling's end row + 1 **if present**, else the signature/declaration node's own end row + 1.
- `body_hash` = SHA-256 over `[signature.start_byte, end_byte]` where `end_byte` is the body's end if paired, else the signature/declaration's end.

**Helpers** (mirror `python_lang.py`: `_text`, `_child_by_type`, `_compute_body_hash` inherited), plus:
- `_node_name(node)` — per-table name extraction: `name` field for class/enum/extension/function_signature; first `identifier` for mixin/getter/setter; first `type_identifier` for type_alias; for `constructor_signature`/`factory_constructor_signature` the text before the `formal_parameter_list` (`Foo`, `Foo.named`, `Foo.make`); for `operator_signature` the string `"operator " + <operator token>`.
- `_classify_member(node)` — given a `method_signature` or `declaration`, **scan its children for the first node whose `type` ends in `_signature`** (`function_signature`, `getter_signature`, `setter_signature`, `constructor_signature`, `factory_constructor_signature`, `operator_signature`). This suffix rule naturally skips modifier tokens (`static`, `external`, `abstract`, `factory`, …) and sibling nodes (`initializers`) without enumerating them, and is robust to additional signature variants. Returns `(METHOD, signature_node)`, or `None` when no `*_signature` child is present (a plain field declaration → skip).
- `_signature_line(node)` — text up to the first `{`, `=>`, or `;` (whichever first), whitespace-collapsed.
- `_leading_doc(decl_node, pending_doc, source)` — strip `///` / `/** */` markers from the adjacent `documentation_comment` block; empty if none/not adjacent.

**Unchanged:** `engine.py`, `differ.py`, `extractor.py`, `scanner.py`, `base.py`, `parsers/__init__.py`.

---

## Edges

Only **containment** edges (type → method). Methods carry `parent` = enclosing type name; the extractor matches `f"{file_path}:{parent}:{kind}"`, and Dart class/mixin/enum/extension → `CLASS`, so `Foo`→`bar` containment edges form automatically. **Dart members always live inside the type's body in the same file**, so (unlike Go) there is **no cross-file containment gap**. `imports` left empty (future work, same rationale as the other parsers).

---

## Error handling

- Unreadable file → log warning, return `[]`.
- `has_error` → log warning, emit every cleanly-parsed symbol.
- A declaration whose name cannot be resolved (e.g. unnamed `extension on T {}`) → skip that node, do not emit a nameless Symbol.
- A `method_signature`/`declaration` that classifies as a field → skip (not an error).

---

## Testing (TDD) — `tests/test_parsers/test_dart.py`

Mirror `test_python.py`. Inline Dart written to `tmp_path`; **fixtures must be valid Dart** (avoid `has_error`-inducing malformed snippets).

1. **Registration & non-stub:** `get_parser(Path("x.dart"))` returns a `DartParser`; `supported_extensions() == {".dart"}`; `parse()` of a valid file does **not** raise `NotImplementedError` (regression guard against the old stub).
2. **Top-level function:** `int topLevel(String s) => s.length;` → one `FUNCTION` `topLevel`, span covers signature **and** body (`line_end` > `line_start`).
3. **Class + methods (parent), incl. modifiers:** a class `Foo` with `int bar(int a) => …` → `CLASS` `Foo` and `METHOD` `bar` with `parent == "Foo"`; a `static int s() => 1;` → `METHOD` `s` (regression guard: `method_signature` is `[static, function_signature]`, so classification must skip the `static` modifier, not read the first child).
4. **Constructors (incl. factory & with-body):** `Foo(this.x);` → `METHOD` `Foo`; named `Foo.named(this.x);` → `METHOD` `Foo.named`; **`factory Foo.make() => …;` → `METHOD` `Foo.make`** (regression guard: factory parses as `factory_constructor_signature`, distinct from `constructor_signature`); a constructor with an initializer list + body `Foo(this.x) : assert(x>0) { … }` → `METHOD` `Foo` with span covering the body.
5. **Getter / setter / operator:** `int get val => x;` → `METHOD` `val`; `set val(int v) {…}` → `METHOD` `val`; **`Vec operator +(Vec o) => …;` → `METHOD` `operator +`** (regression guard: operator overloads parse as `operator_signature` — verifies the `_signature`-suffix scan catches them).
6. **Abstract method (no body):** `void doThing();` inside a class → `METHOD` `doThing` (regression guard: abstract members parse as `declaration`, not `method_signature`).
7. **Field skipped:** `int x = 0;` inside a class → **no** symbol named `x` (fields are not indexed).
8. **mixin / enum / extension / typedef:** `mixin Logger {}` → `CLASS` `Logger` (name via `identifier`, not the `name` field); `enum Color {…}` → `CLASS` `Color`; `extension StrX on String {}` → `CLASS` `StrX`; **unnamed `extension on int {}` → no symbol**; `typedef IntList = List<int>;` → `TYPE_ALIAS` `IntList` (name via first `type_identifier`); a function typedef `typedef Compare = int Function(int a, int b);` → `TYPE_ALIAS` `Compare`.
8b. **Members in extension_body / enum_body (regression guard for the body-node variance):** an extension `extension StrX on String { String shout() => …; }` → `METHOD` `shout` with `parent == "StrX"`; an enhanced enum `enum Planet { earth, mars; bool get habitable => …; }` → `METHOD` `habitable` with `parent == "Planet"` **and no symbol for the `earth`/`mars` enum constants**. (Fails if the walk hard-codes `class_body` instead of matching the `_body` suffix.)
9. **Doc comment + adjacency:** `/// Persists.` directly above a method → `docstring` contains "Persists."; a `documentation_comment` separated by a blank line → empty `docstring`.
10. **Containment edge (integration):** `engine.full_scan` (mocked KG client) over a class with a method produces ≥1 edge (type→method), mirroring the edge-regression test.
11. **Resilience:** a syntactically broken `.dart` file does not raise from `parse()` (returns the parseable subset or `[]`).

Run from `$PY`: `uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_dart.py -v`, then the full suite `uv run pytest packages/ennam-kg-indexer/tests -q`. Also `uv sync` after the dependency change and confirm the indexer imports on a clean resolve.

---

## Out of Scope

- Flutter widget detection (`StatelessWidget`/`StatefulWidget` → `WIDGET`).
- Class fields, top-level variables (`final`/`const`/`var`).
- Annotations (`@override`, etc.) and import/part directives (no edges from them).
- Mixin `on` constraints, `implements`/`extends`/`with` relationship edges.
- Generic type-parameter extraction (the symbol is captured; type params not separately modeled).
- Migrating the existing py/ts/go parsers onto `tree-sitter-language-pack` (deliberately untouched).
