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
| the `.md` file | one **document hub** | `DOCUMENT` → `document` | the file **basename** (e.g. `BA-002-mcp-bridge.md`) — **not** the first H1 (verified: a file may have **multiple H1s or none**, so the H1 is not a stable hub identity) |
| each heading `section` (has an `atx_heading`) | one **section node** | `SECTION` → `document_section` | the `atx_heading`'s `inline` text |
| a `section` with **no** `atx_heading` (preamble text before the first heading) | — | — | **skipped** (verified: leading content parses as a headingless `section`; it has no name) |
| heading nesting (`##` ⊃ `###`) | containment edge (`contains_section`) | — | child section's `parent` = enclosing section's heading; top-level sections' `parent` = the document hub (its basename) |

> **Verified grammar edge cases:** preamble before any heading → a headingless `section` (skip); multiple H1 → multiple sibling top-level `section`s (all become document_sections under the hub); a `#` inside a fenced code block is `code_fence_content`, not a heading.

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
  - one `DOCUMENT` hub symbol per file — `name = file_path.name` (basename; **not** the first H1, which is unstable), `parent=None`.
  - walk `section` nodes recursively → for each section that **has an `atx_heading`**, one `SECTION` symbol; `name` = heading inline text; `level` from the `atx_h{N}_marker`; `parent` = the enclosing heading section's name, or the hub basename for top-level sections.
  - a `section` with **no** `atx_heading` (preamble) → **skip** (recurse into any well-formed children).
- Helpers: `_heading(section)` → the child `atx_heading` or `None`; `_heading_text(atx)` (child `inline` text); `_heading_level(atx)` (from the `atx_h{N}_marker` type); `_section_own_range(section)` (start_byte → first child `section`'s start_byte, else section end) for `content`/`body_hash`. (`setext_heading` — `===`/`---` underline form — is best-effort; see Out of Scope.)

**Modify:** `parsers/base.py` — add to `SymbolKind`:
```python
DOCUMENT = "document"
SECTION = "document_section"
```
(values chosen so the extractor maps them with **no `_KIND_TO_TYPE` entry**: `map_kind_to_type` falls back to `kind.value`, yielding `"document"` / `"document_section"` automatically.)

**Modify:** `indexer/extractor.py` — three targeted changes (larger than first thought; verified against `config/config.yaml` schemas + edge whitelist):

1. **`symbol_to_node` — distinct property shape for `DOCUMENT`/`SECTION`** (the code shape `arch_type`/`signature` does not fit). The `document_section` schema (verified) is `required: [title]` with fields `summary` (≤8000), `content` (≤50000), `line_start`, `line_end`, `level`, `document_id` (all optional). So for a `SECTION` symbol emit:
   ```
   node_type=document_section, title=<heading>, status=active, created_by=python-indexer,
   properties = { summary: <section text ≤8000>, content: <section text ≤50000>,
                  line_start, line_end, level: <heading level 1-6>, body_hash: <hash> }
   ```
   For a `DOCUMENT` hub: `node_type=document, title=<basename>, properties={ summary, body_hash }`. Do **not** emit `arch_type`/`signature`/code fields for these kinds.
   - **`body_hash` placement (verify in plan):** the differ detects change via `properties.body_hash`, but `body_hash` is not a declared `document_section` field. Confirm Gate 1 permits properties beyond the schema (the `properties` JSONB is a bag — likely validates declared fields' types + `required` presence, ignoring extras). If Gate 1 is strict, fall back to having the differ hash `content` for these node types instead. (Edge whitelist rejects unknown *relationships*; node-property strictness must be checked.)

2. **`extract_edges` — relationship + parent-kind, for doc kinds.** Two coupled changes:
   - Add `DOCUMENT, SECTION` to the containment **parent-kind search set** (currently `CLASS, MODULE, COMPONENT, WIDGET`).
   - **Use relationship `contains_section` (NOT `relates_to`) when the parent is a `DOCUMENT`/`SECTION`.** Verified the edge whitelist allows only `document --contains_section--> document_section` and `document_section --contains_section--> document_section`; sending `relates_to` is rejected by Gate 1 (`edge_whitelist.go`: "unknown relationship type") → 422. So `extract_edges` must choose the relationship by parent kind: `contains_section` for doc kinds, `relates_to` for the existing code kinds.

3. These are cross-cutting but isolated to the new kinds; the code parsers (which never emit `DOCUMENT`/`SECTION`) keep producing `architecture` nodes + `relates_to` edges unchanged.

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
2. **Document hub (basename, not H1):** a file `notes.md` with `# Title` → one `DOCUMENT` symbol named **`notes.md`** (→ node_type `document`), not `Title`.
3. **Sections + node_type + props:** `## Section A` / `### Sub A1` → `SECTION` symbols `Section A`, `Sub A1` → node_type `document_section` (assert `map_kind_to_type(SymbolKind.SECTION) == "document_section"`); assert section properties carry `content`, `level` (2 and 3), `line_start`/`line_end` — and **not** `arch_type`/`signature`.
4. **Hierarchy / parent:** `Sub A1`.parent == `Section A`; top-level `Section A`.parent == the hub basename (`notes.md`).
5. **Containment edges + relationship (integration):** `engine.full_scan` (mocked KG client) over a doc with `#`/`##`/`###` produces document→section and section→subsection edges, and the created edges use **`relationship == "contains_section"`** (regression guard — `relates_to` would be rejected by the edge whitelist).
6. **Multiple H1 / preamble:** a file with preamble text then `# A` and `# B` (two H1s) → the preamble yields **no** section, and `A`, `B` are both `SECTION` symbols with `parent` == the hub basename.
7. **Code fence is not a heading:** a fenced block containing a line `# not a heading` → **no** section named "not a heading".
8. **No-heading file:** a `.md` with only prose → exactly one `DOCUMENT` symbol, zero sections.
9. **Resilience:** malformed markdown does not raise from `parse()`.
10. **created_by isolation (unit):** indexed nodes carry `created_by="python-indexer"` (so the differ never archives ingestion-created document_sections).

Run: `uv run pytest packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py -v`, then full suite.

---

## Out of Scope
- **Embedding / semantic recall** of indexed sections — shared server-side concern owned by `2026-06-07-laam-markdown-memory-ingestion-design.md` (the indexer stays structural + lightweight).
- Inline-level extraction (links, emphasis, tables, task lists) — heading-level structure only.
- Front-matter (YAML `---`) parsing into properties — possible later; v1 treats it as content of the first section / hub.
- Setext headings (`===`/`---` underlines) beyond best-effort — atx (`#`) is the primary form; note if setext needs explicit handling in the plan.
- Routing indexed markdown through the ingestion/decompose pipeline — it goes through `create_node` like other indexed code, by design.
