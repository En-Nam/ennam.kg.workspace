# Markdown Parser for `ennam-kg-indexer` (repo indexing) — Design Spec

**Date**: 2026-06-07
**Status**: Approved (design)
**Goal**: Add a `MarkdownParser` to `ennam-kg-indexer` so that **`.md` files in an indexed source repo** (e.g. a docs/requirements repo like `ennam.kg.requirements`, or a `docs/` tree inside a code repo) are parsed into **`document` / `document_section`** knowledge nodes via the existing `kg_index_source` / CLI flow. Today `.md` files have no parser → `get_parser` returns `None` → they are **silently skipped**, so a markdown-heavy repo indexes to almost nothing.

**Grammar**: tree-sitter `markdown` via **`tree-sitter-language-pack`** — already introduced as an indexer dependency by the Dart parser spec (`2026-06-06-dart-parser-design.md`); markdown adds no new dependency.

> **This is the repo-indexing flow — NOT the LAAM memory flow.** Distinct from `2026-06-07-laam-markdown-memory-ingestion-design.md`:
> | | This spec (index repo) | LAAM memory spec |
> |---|---|---|
> | Trigger | `kg_index_source` / CLI walking a repo | `kg_ingest_node` (ingestion) |
> | Mechanism | code-indexer parser → `create_node` | decompose pipeline → drafts |
> | Purpose | "what's in this repo" (structural) | "remember + recall this" |
> Both ultimately produce `document_section` nodes; **embedding + semantic recall is a shared, server-side concern owned by the LAAM/recall spec — out of scope here** (see Decisions).

---

## Decisions (confirmed)

| # | Decision | Choice |
|---|----------|--------|
| Node type | What node_type for indexed markdown? | **`document` hub (one per file) + `document_section` per heading.** Semantically correct for docs (not `architecture`), and consistent with the BA-025 document model. Verified the API `node_type` CHECK allows both. |
| Embedding | Does the indexer embed sections? | **No.** The indexer is a lightweight CLI on the agent's machine; it must not pull `torch`/`sentence-transformers`. It creates **structural nodes only**. Embedding 384-dim for any `document_section` (ingested OR indexed) is the **shared server-side mechanism** scoped by the LAAM recall spec. |
| Parser tech | tree-sitter vs regex | **tree-sitter `markdown`** (via language-pack) — correctly ignores `#` inside fenced code blocks (verified `code_fence_content`, not a heading), where a regex/line parser would misfire. |
| Hierarchy | section nesting | Heading nesting → **containment edges** (`document` → top sections → subsections), via the symbol `parent` field. |

---

## Construct → node mapping (verified against tree-sitter-language-pack `markdown`)

The grammar yields `document` → nested `section` nodes; each `section` begins with an `atx_heading` (`atx_h{1..6}_marker` for level + an `inline` child for the text) and may contain child `section`s for deeper headings.

| Source | Produces | SymbolKind → node_type | name |
|--------|----------|------------------------|------|
| the `.md` file | one **document hub** | `DOCUMENT` → `document` | first H1 text, else the file's basename |
| each heading `section` | one **section node** | `SECTION` → `document_section` | the `atx_heading`'s `inline` text |
| heading nesting (`##` ⊃ `###`) | containment edge | — | child section's `parent` = enclosing section's heading (top-level sections' `parent` = the document hub) |

- **`file_path`** = repo-relative path of the `.md` (engine already normalizes — repo-relative + `repo_key`, checkout-stable, re-index archives removed sections).
- **natural key** = `file_path:name:kind` (same model as code parsers): `doc.md:Section A:document_section`. Re-index updates/archives sections deterministically.
- **`body_hash`** = SHA-256 of the section's **own content** (heading line through the start of its first child section, or section end if none) — so editing one subsection doesn't cascade-dirty its parent.
- Code fences, lists, tables, paragraphs inside a section are **content**, not separate symbols (structural extraction is heading-level only).

---

## Component design

**New file:** `parsers/markdown.py` — `MarkdownParser(BaseParser)`:
- `DOC_LANGUAGE = get_language("markdown")` (from `tree_sitter_language_pack`); `Parser(DOC_LANGUAGE)`.
- `supported_extensions() -> {".md", ".markdown"}`.
- `parse(file_path)`: read bytes (`OSError` → log + `[]`); parse; on `has_error` log + extract what parses; emit:
  - one `DOCUMENT` symbol for the file (`name` = first H1 inline text, else `file_path.stem`; `parent=None`).
  - walk `section` nodes recursively → one `SECTION` symbol each; `name` = heading inline text; `parent` = the enclosing section's heading text, or the document hub's name for top-level sections.
- Helpers: `_heading_text(section)` (find child `atx_heading` → child `inline` → text; skip `setext_heading` edge case or handle similarly), `_section_own_range(section)` (start_byte → first child `section`'s start_byte, else section end) for `body_hash`/content.

**Modify:** `parsers/base.py` — add to `SymbolKind`:
```python
DOCUMENT = "document"
SECTION = "document_section"
```
(values chosen so the extractor maps them with **no `_KIND_TO_TYPE` entry**: `map_kind_to_type` falls back to `kind.value`, yielding `"document"` / `"document_section"` automatically.)

**Modify:** `indexer/extractor.py` — two targeted changes:
1. `symbol_to_node`: for `DOCUMENT`/`SECTION`, put the section text in `properties.content` (heading + own-content) and set `arch_type` to a doc-appropriate value (or omit it for these kinds). They must NOT be forced to `arch_type="pattern"`.
2. `extract_edges`: extend the containment **parent-kind search set** (currently `CLASS, MODULE, COMPONENT, WIDGET`) to also include `DOCUMENT, SECTION`, so `section → subsection` and `document → section` containment edges are created. This is the one cross-cutting extractor change (other parsers are unaffected — they don't emit DOCUMENT/SECTION).

**Modify:** `parsers/__init__.py` — import + `_register(MarkdownParser)`.

**Modify:** `pyproject.toml` — `tree-sitter-language-pack` (shared with Dart; if Dart lands first, no change). Bump `tree-sitter>=0.25.2` (same as Dart spec).

**Unchanged:** `engine.py`, `differ.py`, `scanner.py` — the repo-relative path / `repo_key` / archive-scope model and `get_parser`-driven discovery already work; registering `MarkdownParser` is sufficient for `.md` to be discovered and indexed.

### No collision with the ingestion pipeline
Both this parser and the ingestion `decompose` path create `document` / `document_section` nodes, but they **never collide**: the indexer tags nodes `created_by="python-indexer"` and the differ's archive scope is filtered to exactly that `created_by` (verified in the indexer's diff logic). Ingestion-created document_sections (different `created_by`, different `source_id` key space) are never touched by an indexer re-index, and vice-versa. A given `.md` normally travels one path, not both.

---

## Error handling
- Unreadable file → log warning, return `[]`.
- `has_error` → log warning, emit cleanly-parsed sections.
- A `section` with no resolvable heading text (e.g. malformed) → skip that section (no nameless symbol); still recurse into well-formed children.
- A file with no headings at all → emit just the `document` hub (name = basename), no sections.

---

## Testing (TDD) — `tests/test_parsers/test_markdown.py`
Mirror `test_python.py`. Inline markdown to `tmp_path`.
1. **Registration:** `get_parser(Path("x.md"))` → `MarkdownParser`; `supported_extensions() == {".md", ".markdown"}`.
2. **Document hub:** a file with `# Title` → one `DOCUMENT` symbol named `Title` (→ node_type `document`).
3. **Sections + node_type:** `## Section A` / `### Sub A1` → `SECTION` symbols `Section A`, `Sub A1`, mapping to node_type `document_section` (assert `map_kind_to_type(SymbolKind.SECTION) == "document_section"`).
4. **Hierarchy / parent:** `Sub A1`.parent == `Section A`; top-level `Section A`.parent == the document hub name (`Title`).
5. **Containment edges (integration):** `engine.full_scan` (mocked KG client) over a doc with `#`/`##`/`###` produces document→section and section→subsection edges (verifies the `extract_edges` parent-kind extension).
6. **Code fence is not a heading:** a fenced block containing a line `# not a heading` → **no** section named "not a heading" (regression guard for the tree-sitter choice).
7. **No-heading file:** a `.md` with only prose → exactly one `DOCUMENT` symbol, zero sections.
8. **Resilience:** malformed markdown does not raise from `parse()`.
9. **created_by isolation (unit):** indexed nodes carry `created_by="python-indexer"` (so the differ never archives ingestion-created document_sections).

Run: `uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py -v`, then full suite.

---

## Out of Scope
- **Embedding / semantic recall** of indexed sections — shared server-side concern owned by `2026-06-07-laam-markdown-memory-ingestion-design.md` (the indexer stays structural + lightweight).
- Inline-level extraction (links, emphasis, tables, task lists) — heading-level structure only.
- Front-matter (YAML `---`) parsing into properties — possible later; v1 treats it as content of the first section / hub.
- Setext headings (`===`/`---` underlines) beyond best-effort — atx (`#`) is the primary form; note if setext needs explicit handling in the plan.
- Routing indexed markdown through the ingestion/decompose pipeline — it goes through `create_node` like other indexed code, by design.
