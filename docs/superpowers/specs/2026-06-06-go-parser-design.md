# Go Parser for `ennam-kg-indexer` — Design Spec

**Date**: 2026-06-06
**Status**: Approved (design)
**Goal**: Add a `GoParser` to the `ennam-kg-indexer` package so `.go` source is parsed into KG symbol nodes — unlocking indexing of the platform's own `ennam.kg.go` server (and any Go repo) via the existing CLI / `kg_index_source` MCP tool.

**Depends on**: `ennam-kg-indexer` package (DONE — `parsers/`, engine, differ). `tree-sitter-go>=0.23` is **already declared** in `packages/ennam-kg-indexer/pyproject.toml` (no dependency change needed).

---

## Context

The indexer has real parsers for TypeScript (`typescript.py`) and Python (`python_lang.py`), a Dart stub, and a registry (`parsers/__init__.py`) mapping file extensions → parser singletons via `get_parser(Path)`. Go is the highest-value missing language: `ennam.kg.go` (the core API server, ~150 files) currently cannot be indexed at all.

**Design principle (confirmed):** mirror the **Python parser** — same extraction style, same `Symbol` fields, same error-resilience — applied to Go idioms. No engine/differ/extractor changes; those are already language-agnostic (a parser only produces `list[Symbol]`).

---

## Decisions (confirmed)

| # | Decision | Choice |
|---|----------|--------|
| Scope | What to extract | Top-level declarations, **both exported and unexported** (mirrors Python/TS, which index all). No struct fields. |
| const/var | Index package-level const/var? | **Yes** — one addition beyond a strict Python mirror (Go const/var, e.g. error vars `var ErrX = ...`, exported consts, carry knowledge). |
| Docstring | Capture doc comments? | **Yes** — mirror Python. Go convention: the contiguous `//` comment block immediately preceding a declaration. |
| Route detection | FastAPI-style route detection? | **No** — Python detects routes via *decorators*; Go has no decorators and route handlers are ordinary funcs registered elsewhere (`mux.HandleFunc(...)`), not a declaration-level structure. No clean analog → out of scope. |
| Imports/edges | Populate `Symbol.imports`? | **No** — leave empty. Go imports are package paths that won't match the extractor's name-based edge logic. Only **containment** edges (receiver type → method) are produced, and those work automatically. Documented as future work. |
| `decorators` | — | Always `[]` (Go has no decorators). |

---

## Construct → SymbolKind mapping (verified against the installed `tree-sitter-go` grammar)

| Go source | tree-sitter node | SymbolKind | `parent` |
|-----------|------------------|------------|----------|
| `func Foo()` | `function_declaration` (field `name`) | `FUNCTION` | none |
| `func (r *Repo) Save()` | `method_declaration` (fields `receiver`, `name`) | `METHOD` | receiver type `Repo` (strip leading `*`) |
| `type Repo struct {…}` | `type_declaration` → `type_spec` (field `type` = `struct_type`) | `CLASS` | none |
| `type Store interface {…}` | `type_declaration` → `type_spec` (`type` = `interface_type`) | `INTERFACE` | none |
| `type ID = string` | `type_declaration` → `type_alias` | `TYPE_ALIAS` | none |
| `type Celsius float64` | `type_declaration` → `type_spec` (`type` = other, e.g. `type_identifier`) | `TYPE_ALIAS` | none |
| `const Max = 10` / `const ( A=1; B=2 )` | `const_declaration` → `const_spec` (one per name) | `CONSTANT` | none |
| `var count int` / `var a, b int` | `var_declaration` → `var_spec` (one per name) | `VARIABLE` | none |
| `import "fmt"` | `import_declaration` | — (skipped) | — |

Notes:
- `struct`→`CLASS` is the closest existing kind (no `STRUCT` kind, and the extractor maps every code symbol to the `architecture` node type regardless of kind — so the choice is cosmetic for the KG).
- A `const`/`var` block with multiple specs/names yields **one Symbol per name**.
- Methods set `parent` = receiver type name; the extractor's containment logic looks up `parent` among `CLASS`/`MODULE`/`COMPONENT`/`WIDGET` kinds, and `struct`=`CLASS`, so the `Repo`→`Save` containment edge is created automatically (no extractor change).

---

## Component design

**New file:** `parsers/go_lang.py` — `GoParser(BaseParser)`, structured like `PythonParser`:

- Module-level: `GO_LANGUAGE = Language(tree_sitter_go.language())`; constructor builds `Parser(GO_LANGUAGE)`.
- `supported_extensions() -> {".go"}`.
- `parse(file_path)`:
  - Read bytes; on `OSError` log a warning and return `[]` (mirror Python).
  - Parse; if `tree.root_node.has_error`, log a warning and extract what's parseable (mirror Python).
  - Walk `source_file` children, dispatching by node type to focused handlers:
    - `function_declaration` → `_handle_function(parent=None)`
    - `method_declaration` → `_handle_method` (extract receiver type → parent, then emit METHOD)
    - `type_declaration` → `_handle_type` (iterate `type_spec`/`type_alias` children → CLASS/INTERFACE/TYPE_ALIAS)
    - `const_declaration` / `var_declaration` → `_handle_value_spec` (one Symbol per name)
- Helpers mirrored from `python_lang.py`: `_text`, `_child_text`, `_child_by_type`, `_compute_body_hash` (inherited), plus:
  - `_signature_line(node)` — text up to the first `{` (or first newline if none), whitespace-collapsed.
  - `_leading_doc_comment(node, source)` — collect the contiguous run of `comment` siblings (`//…`) immediately preceding the declaration node, strip the `//` markers, join with newlines. Empty if none.
  - `_receiver_type(method_node, source)` — from the `receiver` field (`parameter_list` → `parameter_declaration` → `type`), descend through an optional `pointer_type` to the `type_identifier` and return its text; `None` if not found.

**Registry:** in `parsers/__init__.py`, import `GoParser`, add to `__all__`, and `_register(GoParser)` alongside the others.

**Unchanged:** `engine.py`, `differ.py`, `extractor.py`, `scanner.py`, `base.py`. The scanner already discovers `.go` files; `get_parser` will now return `GoParser` for them.

---

## Error handling

- Unreadable file → log warning, return `[]` (one bad file never halts a scan; the engine collects errors).
- Parse errors (`has_error`) → log warning, still emit every cleanly-parsed top-level symbol.
- A declaration missing its `name` field → skip that node (do not emit a nameless Symbol), mirror Python's `if not name: return`.
- Malformed receiver (no resolvable type) → emit the method with `parent=None` rather than dropping it.

---

## Testing (TDD) — `tests/test_parsers/test_go.py`

Mirror `test_python.py` structure. Use small inline Go sources written to `tmp_path`.

1. **Registration:** `get_parser(Path("x.go"))` returns a `GoParser`; `supported_extensions()` == `{".go"}`.
2. **Functions:** a file with `func Hello()` → one `FUNCTION` symbol named `Hello`, correct line span, signature starts with `func Hello`.
3. **Methods + receiver parent:** `func (r *Repo) Save() error` → `METHOD` named `Save` with `parent == "Repo"` (pointer receiver). Also test a value receiver `func (r Repo) Name() string` → `parent == "Repo"`.
4. **Structs / interfaces / aliases:** `type Repo struct{}` → `CLASS`; `type Store interface{}` → `INTERFACE`; `type ID = string` and `type Celsius float64` → `TYPE_ALIAS`.
5. **Const / var:** `const Max = 10` → `CONSTANT` `Max`; `var count int` → `VARIABLE` `count`; a `const ( A = 1\n B = 2 )` block → two `CONSTANT` symbols `A`, `B`.
6. **Unexported included:** a lowercase `func helper()` → emitted (scope decision: index all).
7. **Doc comment:** a `// Save persists the repo.` line directly above `func (r *Repo) Save()` → `docstring` contains "Save persists the repo." (and a declaration with no preceding comment → empty `docstring`).
8. **Containment edge (integration):** a full `engine.full_scan` (mocked KG client) over a file with a struct + a method on it produces ≥1 edge (receiver→method), proving `parent` flows into `extract_edges`. (Mirror the edge-regression test in `test_engine_relative_paths.py`.)
9. **Resilience:** a syntactically broken `.go` file does not raise from `parse()` (returns the parseable subset or `[]`).

Run from `$PY`: `uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_go.py -v`, then the full suite `uv run pytest packages/ennam-kg-indexer/tests -q`.

---

## Out of Scope

- Struct fields and individual interface method signatures (top-level types only).
- Go route/handler detection (no decorator analog).
- Import/reference edges (package-path imports don't fit the name-based edge model).
- Generics type-parameter extraction (the symbol is still captured; type params are not separately modeled).
- Building/bundling any grammar — `tree-sitter-go` ships a PyPI wheel and is already a dependency.
