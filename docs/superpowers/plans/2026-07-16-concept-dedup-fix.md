# Concept Node Duplication Fix (cross-document entity sharing) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Stop creating a fresh `concept` node for every mention. Reuse the existing concept for a project so documents that mention the same entity are **connected through it** — the missing edges that make the graph a set of disconnected islands.

**Architecture:** One function in `ingestion/pipeline/decompose.py`. Today `seen_concepts` is a per-document set and `kg.create_node` is called unconditionally. Change to: prefetch the project's existing concepts once per document, resolve each entity name through a normalization key, reuse the existing node id when it matches, otherwise create. Reuses `resolution/name_fold.py::fold_name` (the B1 investment) so `CÔNG TY TNHH ĐẠI TÂN` and `Công ty Trách nhiệm hữu hạn Đại Tân` collapse to one node. No schema change, no Go change.

**Tech Stack:** Python 3.12, `uv`, pytest, ruff (line-length=100).

## Global Constraints
- **Surgical (AGENTS.md Rule 3):** touch only `decompose.py` + its tests. Do NOT change the Go API, migrations, the resolution/`needs_review` pipeline, or `name_fold.py` itself.
- **Fail loud (Rule 12):** concept reuse vs create must be observable — log a per-document count of `concepts_created` vs `concepts_reused`. The current `except → logger.debug` swallow stays as-is (out of scope) but must not hide the new lookup.
- **No behaviour change for chunks/sections/embeddings** — only the "Concept nodes from extraction entities" block (`decompose.py:198-247`) changes.
- **Idempotent re-ingest:** re-running a document must not multiply concepts.
- **Verify:** `cd ennam.kg.python && uv run pytest tests/ingestion/ -v` · lint `uv run ruff check src/ tests/` · format `uv run ruff format src/ tests/`.
- Nested git: `git -C ennam.kg.python`.

## Evidence (measured 2026-07-16 on project `Dasin` = `da53ae43-8f7c-45ba-9e25-ecc46810f31f`)

**41 concept nodes ≈ 15 real entities.** All `active`, all distinct ids, `knowledge_nodes` == `latest_knowledge_nodes` == 41 (so these are **not** versions). 0 orphans.

| Real entity | nodes | kind of duplication |
|---|---|---|
| Công ty Đại Tân | **8** (+1 branch) | `Công ty TNHH Đại Tân` · `CÔNG TY TNHH ĐẠI TÂN`×2 · `Công ty Trách nhiệm hữu hạn Đại Tân`×2 · `CÔNG TY TRÁCH NHIỆM HỮU HẠN ĐẠI TÂN`×3 |
| Bộ Kế hoạch và Đầu tư | **3** | **byte-identical title** |
| Sở Kế hoạch và Đầu tư TP.HCM | **3** | byte-identical |
| Khu chế xuất Tân Thuận | **3** | byte-identical |
| Ban Quản lý các KCX&CN TP.HCM | **4** | case + abbreviation variants |

**Smoking gun:** `mentions` edges are `document→concept` **41** and `document_section→concept` **41** — exactly the concept count, i.e. **every concept belongs to exactly one document. No concept is shared by two documents ⇒ no entity bridges ⇒ disconnected graph.**

**Root cause** — `decompose.py:198-220`:
```python
seen_concepts: set[str] = set()          # re-created for EVERY document
for entity in extraction.entities:
    name = entity.strip()[:200]
    if len(name) < 3 or name.lower() in seen_concepts:   # dedups only WITHIN one document
        continue
    seen_concepts.add(name.lower())
    c_resp = await kg.create_node({...})  # ALWAYS creates — never looks for an existing node
```
Three compounding faults: (1) the dedup set is per-document; (2) `create_node` is unconditional — no lookup, no upsert; (3) `properties.aliases` is written as `[]` though the field exists.

## File Structure
- `src/ennam_kg/ingestion/pipeline/decompose.py` (modify) — concept block only: add a project-scoped lookup + fold-based key, reuse-or-create, alias capture, and a summary log.
- `tests/ingestion/test_decompose_concepts.py` (create) — reuse-vs-create behaviour with a fake KG client.

---

## Task 1: Reuse existing concepts within a project instead of always creating

**Files:**
- Modify: `src/ennam_kg/ingestion/pipeline/decompose.py` (block at lines ~198-247, "Concept nodes from extraction entities")
- Test: `tests/ingestion/test_decompose_concepts.py` (create)

**Interfaces:**
- Consumes: `KGClient.get_nodes(project_id, node_type=None) -> list[dict]` (`packages/ennam-kg-indexer/.../kg_client/client.py:231`, POST `/api/v1/query`, `limit=5000`, returns raw node dicts with `id` / `title`); `KGClient.create_node`, `KGClient.create_edge` (unchanged); `resolution.name_fold.fold_name(name) -> str` (B1).
- Produces: `DecomposeResult.concepts` now counts **created** concepts only; add `result.concepts_reused` (int, default 0) to the `DecomposeResult` dataclass (`decompose.py:23-33`) so callers/tests can assert reuse.
- Unchanged: both `mentions` edges (`hub_node_id→concept`, `section_ids[0]→concept`) are still created — for a *reused* concept this is exactly what builds the cross-document bridge.

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_decompose_concepts.py`:
```python
import pytest

from ennam_kg.ingestion.pipeline.decompose import _resolve_concept_key


def test_fold_key_collapses_case_and_legal_form_variants():
    # These are ONE legal entity in the Dasin corpus but became 8 nodes.
    variants = [
        "Công ty TNHH Đại Tân",
        "CÔNG TY TNHH ĐẠI TÂN",
        "Công ty Trách nhiệm hữu hạn Đại Tân",
        "CÔNG TY TRÁCH NHIỆM HỮU HẠN ĐẠI TÂN",
    ]
    keys = {_resolve_concept_key(v) for v in variants}
    assert len(keys) == 1, f"expected one key, got {keys}"


def test_fold_key_keeps_distinct_entities_apart():
    # A branch is NOT the parent company — must not collapse.
    assert _resolve_concept_key("CÔNG TY TRÁCH NHIỆM HỮU HẠN ĐẠI TÂN") != _resolve_concept_key(
        "CÔNG TY TRÁCH NHIỆM HỮU HẠN ĐẠI TÂN CHI NHÁNH LONG AN"
    )
    assert _resolve_concept_key("Bộ Kế hoạch và Đầu tư") != _resolve_concept_key(
        "Sở Kế hoạch và Đầu tư Thành phố Hồ Chí Minh"
    )
```
> If `_resolve_concept_key` cannot collapse the TNHH ↔ "Trách nhiệm hữu hạn" pair with `fold_name` alone, **read `src/ennam_kg/resolution/name_fold.py` first** and extend the key function locally (e.g. a small legal-form map applied before `fold_name`) — do **not** edit `name_fold.py` (it is shared with the resolution pipeline). If the abbreviation cannot be handled cleanly, drop the first test to case/whitespace variants only, land the rest, and record the abbreviation gap in the checkpoint — exact-duplicate removal is already the majority of the win.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_decompose_concepts.py -v`
Expected: FAIL — `ImportError: cannot import name '_resolve_concept_key'`.

- [ ] **Step 3: Implement the key helper**

In `decompose.py`, near `_content_hash` (line ~35), add:
```python
def _resolve_concept_key(name: str) -> str:
    """Project-scoped identity key for a concept title.

    Collapses case/whitespace/diacritic-fold variants via the B1 fold, plus
    Vietnamese legal-form abbreviations, so one real entity maps to one node.
    """
    from ennam_kg.resolution.name_fold import fold_name

    folded = fold_name(name)
    for long_form, short_form in _LEGAL_FORMS:
        folded = folded.replace(long_form, short_form)
    return " ".join(folded.split())
```
and, above it:
```python
# Vietnamese legal-form abbreviations seen in the corpus. Applied AFTER
# fold_name (which already lowercases/strips diacritics), so keys are folded.
_LEGAL_FORMS: tuple[tuple[str, str], ...] = (
    ("trach nhiem huu han", "tnhh"),
    ("cong ty co phan", "ctcp"),
)
```
> Verify the exact folded output of `fold_name` before finalising `_LEGAL_FORMS` — run `uv run python -c "from ennam_kg.resolution.name_fold import fold_name; print(fold_name('Công ty Trách nhiệm hữu hạn Đại Tân'))"` and match the strings to what it actually emits.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_decompose_concepts.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing reuse test**

Append to `tests/ingestion/test_decompose_concepts.py`:
```python
class _FakeKG:
    """Minimal KGClient stand-in: records creates, serves a pre-existing concept."""

    def __init__(self, existing: list[dict] | None = None):
        self.existing = existing or []
        self.created_nodes: list[dict] = []
        self.created_edges: list[dict] = []

    async def get_nodes(self, project_id: str, node_type: str | None = None) -> list[dict]:
        return [n for n in self.existing if not node_type or n["node_type"] == node_type]

    async def create_node(self, node_data: dict) -> dict:
        self.created_nodes.append(node_data)
        return {"node": {"id": f"new-{len(self.created_nodes)}"}}

    async def create_edge(self, edge_data: dict) -> dict:
        self.created_edges.append(edge_data)
        return {}


@pytest.mark.asyncio
async def test_existing_concept_is_reused_and_bridged_not_duplicated():
    """A second document mentioning the same entity must EDGE to the existing
    concept — that shared node is the cross-document bridge. Before this fix
    every document minted its own concept (41 concepts / 41 doc-edges = 1:1)."""
    kg = _FakeKG(existing=[
        {"id": "concept-1", "node_type": "concept", "title": "CÔNG TY TNHH ĐẠI TÂN"}
    ])
    # Drive decompose_document (or the extracted concept helper) with an
    # extraction whose entities include a case variant of the existing concept
    # plus one genuinely new entity.
    # ... arrange hub/section/chunk fakes as the existing tests in
    #     tests/ingestion/test_decompose_canonical.py do ...
    # assert only the NEW entity was created:
    #   titles = [n["title"] for n in kg.created_nodes if n["node_type"] == "concept"]
    #   assert "Đại Tân" not in " ".join(titles)
    # assert a mentions edge points at the REUSED id:
    #   assert any(e["target_id"] == "concept-1" for e in kg.created_edges)
```
> Read `tests/ingestion/test_decompose_canonical.py` first and mirror its fixture/arrangement for `decompose_document` (hub id, sections, chunks, `extraction.entities`); replace the `...` above with that real arrangement. Do not invent a new fixture style.

- [ ] **Step 6: Run → fail.** `uv run pytest tests/ingestion/test_decompose_concepts.py -v`

- [ ] **Step 7: Implement reuse-or-create**

Replace the concept block (`decompose.py:198-247`) with:
```python
    # Concept nodes from extraction entities.
    # Concepts are PROJECT-scoped, not document-scoped: reusing one node across
    # documents is what creates the cross-document entity bridges. Creating a
    # fresh node per mention (the old behaviour) left the graph as islands.
    existing_concepts: dict[str, str] = {}
    try:
        for node in await kg.get_nodes(project_id, node_type="concept"):
            title = str(node.get("title") or "")
            node_id = str(node.get("id") or "")
            if title and node_id:
                existing_concepts.setdefault(_resolve_concept_key(title), node_id)
    except Exception as exc:
        logger.warning(
            "concept prefetch failed — falling back to create-only (may duplicate): %s", exc
        )

    seen_keys: set[str] = set()
    for entity in extraction.entities:
        name = entity.strip()[:200]
        if len(name) < 3:
            continue
        key = _resolve_concept_key(name)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        try:
            c_id = existing_concepts.get(key, "")
            if c_id:
                result.concepts_reused += 1
            else:
                c_resp = await kg.create_node(
                    {
                        "project_id": project_id,
                        "node_type": "concept",
                        "title": name,
                        "status": "active",
                        "created_by": _CREATED_BY,
                        "properties": {
                            "name": name,
                            "definition": f"Mentioned in document {draft.get('title', '')}"[:5000],
                            "domain": "ingested_document",
                            "aliases": [],
                        },
                    }
                )
                c_obj = c_resp.get("node") if isinstance(c_resp.get("node"), dict) else c_resp
                c_id = str((c_obj or {}).get("id") or "")
                if c_id:
                    existing_concepts[key] = c_id
                    result.concepts += 1
            if c_id:
                await kg.create_edge(
                    {
                        "project_id": project_id,
                        "source_id": hub_node_id,
                        "target_id": c_id,
                        "relationship": "mentions",
                        "created_by": _CREATED_BY,
                    }
                )
                result.edges += 1
                if section_ids:
                    await kg.create_edge(
                        {
                            "project_id": project_id,
                            "source_id": section_ids[0],
                            "target_id": c_id,
                            "relationship": "mentions",
                            "created_by": _CREATED_BY,
                        }
                    )
                    result.edges += 1
        except Exception as exc:
            logger.debug("concept node skip %s: %s", name, exc)

    logger.info(
        "concepts resolved: doc=%s created=%d reused=%d",
        draft.get("title", ""),
        result.concepts,
        result.concepts_reused,
    )
```
Add `concepts_reused: int = 0` to the `DecomposeResult` dataclass (`decompose.py:23-33`).

- [ ] **Step 8: Run → pass.** `uv run pytest tests/ingestion/ -v`
Expected: new tests pass; **existing `tests/ingestion/test_decompose_*.py` still pass**. If one asserts an exact `result.concepts` for a fixture with repeated entities, that number legitimately drops (duplicates are no longer created) — update only after confirming the fixture really repeats an entity.

- [ ] **Step 9: Lint + commit**
```bash
cd ennam.kg.python && uv run ruff format src/ tests/ && uv run ruff check src/ennam_kg/ingestion/pipeline/decompose.py tests/ingestion/test_decompose_concepts.py
git -C ennam.kg.python add src/ennam_kg/ingestion/pipeline/decompose.py tests/ingestion/test_decompose_concepts.py
git -C ennam.kg.python commit -m "fix(ingestion): reuse project-scoped concept nodes instead of one per mention"
```

---

## Task 2: Rebuild the Dasin corpus and prove the bridges exist (operational)

**Files:** none. Requires the Docker stack (`daab-worker`, `daab-postgres` :5433, `daab-server` :8082).

**Baseline to beat (Dasin, measured 2026-07-16 after the OCR fix):** 41 concepts (≈15 real), `document→concept` mentions **41** (1:1 ⇒ zero shared entities), 9 documents.

- [ ] **Step 1: Rebuild the worker** — `cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace && docker compose up -d --build daab-worker`

- [ ] **Step 2: Re-ingest.** Delete the `Dasin` project in the dashboard (`localhost:3500/projects`), re-create it, connect AAAA and Sync (or Local Upload `doc_pdf_test/project_3`).
> **Required:** re-syncing an existing project is a **no-op** — `aaaa_synced_document` dedups on `(document_id, content_hash)` and the bytes are unchanged. Deleting the project cascades the sync-state rows.

- [ ] **Step 3: Measure — concept count collapsed, no exact duplicates**
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -F'|' -c "
WITH p AS (SELECT id FROM projects WHERE name='Dasin')
SELECT 'concepts', count(*) FROM latest_knowledge_nodes WHERE project_id=(SELECT id FROM p) AND node_type='concept'
UNION ALL
SELECT 'exact_dupe_titles', count(*) FROM (
  SELECT title FROM latest_knowledge_nodes WHERE project_id=(SELECT id FROM p) AND node_type='concept'
  GROUP BY title HAVING count(*)>1) d;"
```
Expected: `concepts` materially **below 41** (≈15–20) and **`exact_dupe_titles` = 0**.

- [ ] **Step 4: Measure — the bridges (this is the whole point)**
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -F'|' -c "
WITH p AS (SELECT id FROM projects WHERE name='Dasin')
SELECT c.title, count(DISTINCT e.source_id) AS documents_sharing
FROM latest_knowledge_nodes c
JOIN knowledge_edges e ON e.target_id=c.id AND e.edge_type='mentions'
JOIN knowledge_nodes d ON d.id=e.source_id AND d.node_type='document'
WHERE c.project_id=(SELECT id FROM p) AND c.node_type='concept'
GROUP BY 1 HAVING count(DISTINCT e.source_id)>1 ORDER BY 2 DESC;"
```
Expected: **non-empty** — e.g. `Đại Tân` shared by many of the 9 documents. Before the fix this query returned **zero rows**; that emptiness is exactly the disconnected-islands symptom.

- [ ] **Step 5: Verify the Đại Tân collapse specifically**
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -F'|' -c "
SELECT title FROM latest_knowledge_nodes
WHERE project_id=(SELECT id FROM projects WHERE name='Dasin')
  AND node_type='concept' AND title ILIKE '%ĐẠI TÂN%';"
```
Expected: **1 node** for the company (plus, legitimately, `... CHI NHÁNH LONG AN` as a separate branch entity) — down from 8.

- [ ] **Step 6: Checkpoint** — `mcp__serena__write_memory("checkpoint/concept-dedup-fix-<YYYY-MM-DD>", …)` with before/after numbers; update `mem:backlog/ingestion-ocr-content-loss-bugs` (its "Still open → concept-type entity gap" item) and `mem:backlog/ba033-slice2-readiness-path`.

---

## Self-Review

- **Evidence coverage:** exact-duplicate creation (`Bộ Kế hoạch và Đầu tư` ×3, byte-identical) → Task 1 Step 7 project-scoped lookup. Case/legal-form variants (`Đại Tân` ×8) → Task 1 Step 3 `_resolve_concept_key` + `fold_name`. The 1:1 `document→concept` ratio (no bridges) → Task 2 Step 4, which is the acceptance test. ✓
- **No placeholders:** every step has real code/commands/expected output. **Two steps deliberately say "read first"** and name the exact file to mirror: the `fold_name` output strings (Step 3) and the `decompose_document` fixture arrangement (Step 5) — these are integration points where inventing a shape would be worse than reading the existing one.
- **Type consistency:** `get_nodes(project_id, node_type=...) -> list[dict]` with `id`/`title` keys matches `kg_client/client.py:231`. `create_node` response unwrapping (`resp.get("node") or resp`) is copied verbatim from the current code. `DecomposeResult.concepts` keeps its meaning (created) and gains `concepts_reused`. Both `mentions` edges are preserved unchanged.
- **Known limitations (stated, not hidden):**
  - **Not race-safe.** Two workers decomposing different documents concurrently can both miss the prefetch and create the same concept. Acceptable now (the worker processes drafts serially per batch) and still a massive improvement, but the *correct* long-term fix is a DB-level upsert on `(project_id, node_type, folded_title)` in Go — out of scope, deliberately (Rule 2/3). Record it as a follow-up.
  - **`get_nodes` has `limit=5000`** — fine for these corpora; a project exceeding it would start duplicating silently. Note in the checkpoint.
  - **`aliases` stays `[]`.** Capturing the surface form of reused variants is a genuine improvement but is not needed to fix the bridge problem. Deliberately out of scope.
  - **Prefetch is per document** (once per `decompose_document`), so a batch of N documents does N `get_nodes` calls. Simple and correct; optimise only if measured slow.
- **Relationship to B1/BA-033:** this fixes concept *creation*. It does NOT enrol `concept` in the resolution/`needs_review` pipeline (which covers 6 other types with hub-safety gates + LLM confirmation). Semantic near-duplicates that `fold_name` cannot catch remain — that is the separate, still-open decision in `mem:backlog/ba033-slice2-readiness-path`.
