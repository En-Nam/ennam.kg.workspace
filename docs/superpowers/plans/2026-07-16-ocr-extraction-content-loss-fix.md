# OCR / Extraction Content-Loss Fix (Bug A + Bug B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Stop the ingestion pipeline from silently destroying document text. Two independent, confirmed bugs in the **shared** extraction path (affects Local Upload AND AAAA doc-sync equally): **(B)** all content before the first markdown heading is dropped; **(A)** PDFs carrying a garbage embedded text layer bypass OCR entirely.

**Architecture:** Both fixes are surgical, single-function changes in `ennam.kg.python`. Bug B in `ingestion/pipeline/document_tree.py::parse_markdown_sections` (emit a leading section for pre-heading content). Bug A in `ingestion/ocr/pdf_render.py::page_texts_and_renders` (add the image-coverage half of the probe the spec always specified). No API, schema, or Go changes. Fix order: **B → A** (B is higher impact and independent).

**Tech Stack:** Python 3.12, `uv`, pytest, pypdf, pypdfium2, pytesseract (`-l vie`), ruff (line-length=100).

## Global Constraints
- **This is NOT a doc-sync bug.** Proven: project `Dasin 3` (AAAA doc-sync) and `Dasin 4` (direct Local Upload) contain **byte-identical** results per document. Do not "fix" anything in `worker.py` / `handle_aaaa_sync` / the AAAA endpoints.
- **Fail loud (AGENTS.md Rule 12):** both bugs today discard text with **no error**. Every new discard/override decision MUST be logged at INFO/WARNING with page/doc identity.
- **Surgical (AGENTS.md Rule 3):** touch only `document_tree.py`, `pdf_render.py`, and their tests. Do NOT refactor the chunker, canonical builder, decompose, or `_build_recovered_fields_section`.
- **TDD:** every task writes a failing test first, runs it to see it fail, then implements. Reproductions are already known (below) — use them.
- **Test/verify commands:** `cd ennam.kg.python && uv run pytest <file> -v` · lint `uv run ruff check src/ tests/` · format `uv run ruff format src/ tests/`.
- **Real fixtures available:** `/Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace/doc_pdf_test/project_3/*.pdf` (the 9 Dasin PDFs). Integration tests MUST `pytest.skip` if the directory is absent (do not hard-fail CI).
- Nested git: commit with `git -C ennam.kg.python`.

## Evidence (verified 2026-07-16 — do not re-litigate)

| PDF | text layer | `extract_file_text` | headings | stored in KG |
|---|---|---|---|---|
| `BCTC KIEM TOAN 2024` | **none** (12 pages, 12 images) | **19,038 chars, VN diacritics 0.189, 17.2s** ✅ | **0** | **2,208 chars — only the appended figures** ❌ |
| `GPDT X3.CNLA` | none | 5,435 chars, 0.200 ✅ | 4 (`### Điều 1..4`) | 3,643 ✅ (preamble still lost) |
| `GPDT X1-` | **1,807 chars/page, 0 diacritics (garbage)** | **7,234 chars, 0 diacritics, 0.0s** ❌ | — | 7,224 garbage ❌ |

Diacritic health: manual corpora 93–97% · **Dasin (both projects) 20–27%**. Tesseract ran 248×, `-l vie`, **0 render failures**, no OOM → OCR itself is healthy.

**Minimal repro (Bug B) — already proven:**
```
body (9,857 chars, no headings)                    -> 1 section "Document",  9,856 chars kept ✅
body + "\n\n## Recovered Figures (OCR fields)\n..." -> 1 section "Recovered Figures", 48 chars kept
                                                    => 9,857 chars of real text SILENTLY DROPPED ❌
```
Root cause chain: OCR'd scans produce **no markdown headings** → B2's `_build_recovered_fields_section` appends `## Recovered Figures` → that becomes the **only** heading → `parse_markdown_sections` starts its loop at `headers[0]` → the entire body before it is dropped. (Without the appended heading, the `if not headers:` branch would have kept everything — the B2 fix is what triggers the loss.)

---

## File Structure
- `src/ennam_kg/ingestion/pipeline/document_tree.py` (modify) — `parse_markdown_sections`: emit pre-heading content as a leading section. Sole responsibility: markdown → flat sections.
- `tests/test_document_tree.py` (modify) — preamble-retention tests.
- `src/ennam_kg/ingestion/ocr/pdf_render.py` (modify) — probe: add garbage-text-layer / image detection + loud logging.
- `tests/test_pdf_render.py` (create) — unit tests for the new helpers + a skip-if-absent integration test on the real PDFs.

---

## Task 1: Bug B — stop dropping content before the first heading

**Files:**
- Modify: `src/ennam_kg/ingestion/pipeline/document_tree.py` (`parse_markdown_sections`)
- Test: `tests/test_document_tree.py`

**Interfaces:**
- Produces: `parse_markdown_sections(content: str, *, max_sections: int = 200) -> list[MarkdownSection]` — unchanged signature. New behaviour: when `headers` is non-empty AND non-whitespace content exists before `headers[0]`, the returned list **starts with** an extra `MarkdownSection(title="Document", level=1, line_start=1, line_end=<first heading line>, text=<preamble>[:50000])`. `"Document"` matches the existing no-headings fallback title, so downstream (`build_document_tree_json`, `canonical.py`, `decompose.py`) needs no change.
- Consumed by: `canonical.py:86` `raw_sections = parse_markdown_sections(canonical_text)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_document_tree.py`:
```python
def test_content_before_first_heading_is_kept_as_leading_section():
    # Regression: OCR'd scans have no headings; B2 appends "## Recovered Figures",
    # which used to make the appended heading the ONLY heading and silently drop
    # the entire document body before it.
    body = "BÁO CÁO TÀI CHÍNH ĐÃ ĐƯỢC KIÊM TOÁN\nCÔNG TY TNHH ĐẠI TÂN\nDoanh thu thuần 102.512.628.181"
    content = body + "\n\n## Recovered Figures (OCR fields)\namounts: 1,2,3\n"

    sections = parse_markdown_sections(content)

    assert [s.title for s in sections] == ["Document", "Recovered Figures (OCR fields)"]
    assert "BÁO CÁO TÀI CHÍNH" in sections[0].text
    assert "Doanh thu thuần 102.512.628.181" in sections[0].text
    assert sections[0].level == 1
    assert sections[0].line_start == 1


def test_no_preamble_section_when_content_starts_with_a_heading():
    sections = parse_markdown_sections("# Title\nbody text\n")
    assert [s.title for s in sections] == ["Title"]


def test_blank_lines_before_first_heading_do_not_create_a_section():
    sections = parse_markdown_sections("\n\n   \n# Title\nbody\n")
    assert [s.title for s in sections] == ["Title"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_document_tree.py -k "preamble or before_first_heading or blank_lines" -v`
Expected: `test_content_before_first_heading_is_kept_as_leading_section` FAILS — actual titles are `["Recovered Figures (OCR fields)"]` (the body is dropped). The other two PASS already (they guard against regression).

- [ ] **Step 3: Write minimal implementation**

In `parse_markdown_sections`, immediately after the `if not headers: ...` block and **before** the `for idx, (line_num, level, title) in enumerate(headers):` loop, insert:
```python
    flat: list[MarkdownSection] = []

    # Content before the first heading is real document body. OCR'd scans have
    # no headings of their own, so an appended section (e.g. "## Recovered
    # Figures") would otherwise make the whole body vanish. Emit it as a
    # leading section instead of dropping it.
    first_header_line = headers[0][0]
    preamble = "\n".join(lines[: first_header_line - 1]).strip()
    if preamble:
        flat.append(
            MarkdownSection(
                title="Document",
                level=1,
                line_start=1,
                line_end=first_header_line,
                text=preamble[:50000],
            )
        )
```
Then delete the now-duplicated `flat: list[MarkdownSection] = []` line that used to precede the loop (keep exactly one declaration). The loop body itself is unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_document_tree.py -v`
Expected: PASS, and **all pre-existing tests in this file still pass** (the preamble only appears when there is pre-heading content).

- [ ] **Step 5: Run the wider consumers' tests (no regression)**

Run: `cd ennam.kg.python && uv run pytest tests/test_canonical.py tests/test_decompose_canonical.py tests/test_decompose_chunks.py tests/test_chunker.py -v`
Expected: PASS. If a test asserts an exact section count for a fixture that has a preamble, that count legitimately grows by 1 — update the expectation only after confirming the fixture really has pre-heading text.
> Note the tree side-effect: a level-1 `"Document"` preamble followed by a level-2+ first heading nests those headings under it in `build_document_tree_json`. That is intended (document → sections) and matches the existing no-headings fallback level.

- [ ] **Step 6: Commit**
```bash
git -C ennam.kg.python add src/ennam_kg/ingestion/pipeline/document_tree.py tests/test_document_tree.py
git -C ennam.kg.python commit -m "fix(ingestion): keep document body before the first heading instead of dropping it"
```

---

## Task 2: Bug A — OCR pages whose embedded text layer is garbage

**Files:**
- Modify: `src/ennam_kg/ingestion/ocr/pdf_render.py`
- Test: `tests/test_pdf_render.py` (create)

**Interfaces:**
- Produces: `page_texts_and_renders(path: Path, dpi: int = 300, page_cap: int = 50) -> Iterator[tuple[int, str, Image.Image | None]]` — unchanged signature/contract (`render is None` ⇒ caller uses `text_layer`). New behaviour: a page whose text layer is long enough BUT looks like source-side Latin-mangled Vietnamese **on a page that contains an image** is now rendered and OCR'd instead of trusted.
- New module-level helpers (tested directly): `_looks_like_mangled_vi(text: str) -> bool`, `_page_has_image(page) -> bool`.
- Consumed by: `ingestion/adapters/files.py:77`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pdf_render.py`:
```python
from pathlib import Path

import pytest

from ennam_kg.ingestion.ocr.pdf_render import (
    _looks_like_mangled_vi,
    page_texts_and_renders,
)

PDF_DIR = Path(
    "/Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace/doc_pdf_test/project_3"
)


def test_mangled_vi_detected():
    # Real GPDT X1 text-layer sample: Vietnamese with every diacritic destroyed.
    mangled = (
        "uv seN NHAN oAN rsANu puo uo cni rtrxnr na,x QuAr,l r,'f cAc xnu cnt xuAr "
        "vA c6xc ucnrPr CQNG HOA XA HQI CHTNGHIAVIPTNAM DQc l$p - Tr; do - Hlnh phtic "
        "GrAY cHUNc NHAN DANG x{'oAu rU Md sli tin 7666509593 Chilng nhdn ldn"
    )
    assert _looks_like_mangled_vi(mangled) is True


def test_healthy_vi_not_flagged():
    healthy = (
        "BÁO CÁO TÀI CHÍNH ĐÃ ĐƯỢC KIỂM TOÁN CÔNG TY TNHH ĐẠI TÂN "
        "Cho năm tài chính kết thúc ngày 31/12/2024 Đơn vị tính: Đồng Việt Nam "
        "Doanh thu thuần về bán hàng và cung cấp dịch vụ trong kỳ kế toán"
    )
    assert _looks_like_mangled_vi(healthy) is False


def test_short_text_is_not_flagged():
    # Too little evidence — must not trigger an expensive OCR on a stub page.
    assert _looks_like_mangled_vi("Trang 1") is False


@pytest.mark.skipif(not PDF_DIR.exists(), reason="real PDF fixtures not present")
def test_garbage_text_layer_pdf_is_rendered_for_ocr():
    # GPDT X1 has a 1,807-chars/page GARBAGE text layer + a full-page image.
    # Before the fix the probe returned render=None (no OCR) for every page.
    pages = list(page_texts_and_renders(PDF_DIR / "GPDT X1-.pdf"))
    assert pages, "expected pages"
    assert any(render is not None for _, _, render in pages), (
        "garbage text layer must be overridden -> page must be rendered for OCR"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_pdf_render.py -v`
Expected: FAIL — `ImportError: cannot import name '_looks_like_mangled_vi'`.

- [ ] **Step 3: Write minimal implementation**

In `src/ennam_kg/ingestion/ocr/pdf_render.py`, add `import re` and, below `TEXT_LAYER_MIN_CHARS`:
```python
# A page that carries an image AND whose text layer has almost no Vietnamese
# diacritics is a scan whose text layer was produced by a Latin-only OCR at the
# source (verified on the Dasin corpus: 1.5k-7.5k chars/page, 0 diacritics).
# Trusting it silently ships garbage into the KG, so OCR the page instead.
# This is the image-coverage half of the probe the design always specified.
_VI_DIACRITICS = re.compile(
    "[àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ"
    "ÀÁẢÃẠĂÂĐÈÉÊÌÍÒÓÔƠÙÚƯÝ]"
)
_MANGLED_MIN_LETTERS = 100   # below this there is not enough evidence to judge
_MANGLED_MAX_DIACRITIC_RATIO = 0.01


def _looks_like_mangled_vi(text: str) -> bool:
    """True when text has plenty of letters but virtually no VN diacritics."""
    letters = sum(1 for c in text if c.isalpha())
    if letters < _MANGLED_MIN_LETTERS:
        return False
    return len(_VI_DIACRITICS.findall(text)) / letters < _MANGLED_MAX_DIACRITIC_RATIO


def _page_has_image(page) -> bool:
    """True when the page embeds at least one image XObject (i.e. a scan)."""
    try:
        resources = page.get("/Resources") or {}
        xobjects = resources.get("/XObject")
        if not xobjects:
            return False
        xobjects = xobjects.get_object()
        return any(
            xobjects[k].get_object().get("/Subtype") == "/Image" for k in xobjects
        )
    except Exception:  # malformed resources must never kill extraction
        return False
```
Then replace the probe decision inside the loop:
```python
        for i in range(n):
            page = reader.pages[i]
            tl = (page.extract_text() or "").strip()
            mangled = len(tl) >= TEXT_LAYER_MIN_CHARS and _looks_like_mangled_vi(tl) and _page_has_image(page)
            if mangled:
                logger.warning(
                    "text layer looks Latin-mangled on an image page — forcing OCR: "
                    "path=%s page=%d text_layer_chars=%d",
                    path,
                    i,
                    len(tl),
                )
            if len(tl) >= TEXT_LAYER_MIN_CHARS and not mangled:
                yield i, tl, None
            else:
                try:
                    bitmap = pdf[i].render(scale=scale)
                    img = bitmap.to_pil()
                    bitmap.close()  # free native bitmap immediately (MINOR-2)
                    yield i, tl, img
                    img.close()  # free per page (streaming, no OOM)
                except Exception as exc:
                    logger.warning(
                        "pdf page render failed — falling back to text layer: page=%d error=%s",
                        i,
                        exc,
                    )
                    yield i, tl, None  # caller uses text_layer as fallback
```
(The only changes: hoist `page`, compute `mangled`, log it, and add `and not mangled` to the trust condition. Everything else is untouched.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_pdf_render.py -v`
Expected: PASS (all 4).

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.python add src/ennam_kg/ingestion/ocr/pdf_render.py tests/test_pdf_render.py
git -C ennam.kg.python commit -m "fix(ocr): OCR pages whose embedded text layer is Latin-mangled Vietnamese"
```

---

## Task 3: End-to-end verification on the real corpus (evidence, not vibes)

**Files:** none modified. Test: `tests/test_extraction_regression.py` (create).

**Interfaces:** Consumes `extract_file_text` (`ingestion/adapters/files.py:18`, returns `(text, format)`) and `parse_markdown_sections`.

- [ ] **Step 1: Write the regression test**

Create `tests/test_extraction_regression.py`:
```python
import re
from pathlib import Path

import pytest

from ennam_kg.ingestion.adapters.files import extract_file_text
from ennam_kg.ingestion.pipeline.document_tree import parse_markdown_sections

PDF_DIR = Path(
    "/Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace/doc_pdf_test/project_3"
)
_DIA = re.compile("[àáảãạăâđèéẻẽẹêìíỉĩịòóỏõọôơùúủũụưỳýỷỹỵÀÁẢÃẠĂÂĐÈÉÊÌÍÒÓÔƠÙÚƯÝ]")

pytestmark = pytest.mark.skipif(not PDF_DIR.exists(), reason="real PDF fixtures not present")


def _diacritic_ratio(s: str) -> float:
    letters = sum(1 for c in s if c.isalpha())
    return (len(_DIA.findall(s)) / letters) if letters else 0.0


@pytest.mark.parametrize("name", ["GPDT X1-.pdf", "GPDT X2-.pdf", "GCNDKKD L8.DASIN.pdf"])
def test_garbage_text_layer_docs_now_have_vietnamese(name):
    """Bug A: these used to return in ~0.0s with 0 diacritics (text layer trusted)."""
    text, _ = extract_file_text(PDF_DIR / name)
    assert _diacritic_ratio(text) > 0.05, f"{name} still has no Vietnamese diacritics"


def test_bctc_body_survives_sectioning():
    """Bug B: BCTC OCR'd to ~19k chars but only the appended figures section was kept."""
    text, _ = extract_file_text(PDF_DIR / "BCTC KIEM TOAN 2024 DASIN-VND.pdf")
    assert len(text) > 15000
    assert _diacritic_ratio(text) > 0.05

    body_marker = "## Recovered Figures (OCR fields)"
    sections = parse_markdown_sections(text + f"\n\n{body_marker}\namounts: 1,2,3\n")
    retained = sum(len(s.text) for s in sections)
    assert retained > 15000, f"body dropped: only {retained} chars retained"
    assert any("TÀI CHÍNH" in s.text or "ĐẠI TÂN" in s.text for s in sections)
```

- [ ] **Step 2: Run it**

Run: `cd ennam.kg.python && uv run pytest tests/test_extraction_regression.py -v`
Expected: PASS. (These are slow — each OCRs a real PDF; `GPDT X1` ≈ 4 pages, `BCTC 2024` ≈ 17s.)

- [ ] **Step 3: Lint + full suite**

Run: `cd ennam.kg.python && uv run ruff format src/ tests/ && uv run ruff check src/ tests/ && uv run pytest -q`
Expected: clean; no pre-existing test broken.

- [ ] **Step 4: Commit**
```bash
git -C ennam.kg.python add tests/test_extraction_regression.py
git -C ennam.kg.python commit -m "test(ingestion): regression coverage for OCR text-layer and body-retention bugs"
```

---

## Task 4: Rebuild the Dasin corpus and measure the fix (operational)

**Files:** none. Requires the Docker stack up (`daab-worker`, `daab-postgres` on :5433, `daab-server` on :8082).

**Baseline to beat (measured 2026-07-16):** Dasin 3 = 40 chunks, **8** with diacritics (20%); BCTC 2024 = 2 chunks / 2,208 chars. Healthy reference: manual corpora 93–97%.

- [ ] **Step 1: Rebuild the worker image** (the fix lives in the Python worker)
```bash
cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace
docker compose up -d --build daab-worker
```

- [ ] **Step 2: Re-ingest.** Delete DAAB projects `Dasin`, `Dasin 2`, `Dasin 3`, `Dasin 4` in the dashboard (`localhost:3500/projects`), then re-create one project and re-run the AAAA Sync (or Local Upload of `doc_pdf_test/project_3`).
> Re-syncing an existing project will **skip** every doc: `aaaa_synced_document` dedups on `(document_id, content_hash)` and the bytes have not changed. Delete the project (cascades the sync-state rows) or the run is a no-op.

- [ ] **Step 3: Measure — diacritic health**
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -F'|' -c "
SELECT p.name, count(*) AS chunks,
       count(*) FILTER (WHERE kn.properties->>'content' ~ '[àáảãạăâđèéẻẽẹêìíỉĩịòóỏõọôơùúủũụưỳýỷỹỵÀÁẢÃẠĂÂĐÈÉÊÌÍÒÓÔƠÙÚƯÝ]') AS with_diacritics
FROM knowledge_nodes kn JOIN projects p ON p.id=kn.project_id
WHERE kn.node_type='document_chunk' AND p.name LIKE 'Dasin%' GROUP BY 1;"
```
Expected: **with_diacritics / chunks ≥ 0.85** (vs 0.20 baseline).

- [ ] **Step 4: Measure — body retention per document**
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -F'|' -c "
SELECT left(d.title,32), count(c.id) chunks, sum(length(c.properties->>'content')) chars
FROM knowledge_nodes d
JOIN knowledge_edges e ON e.source_id=d.id AND e.edge_type='contains_section'
JOIN knowledge_edges e2 ON e2.source_id=e.target_id
JOIN knowledge_nodes c ON c.id=e2.target_id AND c.node_type='document_chunk'
WHERE d.node_type='document' AND d.project_id=(SELECT id FROM projects WHERE name='Dasin 3')
GROUP BY 1 ORDER BY 3 DESC;"
```
Expected: `BCTC KIEM TOAN 2024` ≈ **15k–19k chars** (vs 2,208 baseline) and many more than 2 chunks.

- [ ] **Step 5: Measure — graph density** (the user-visible symptom: disconnected islands)
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -t -A -F'|' -c "
SELECT kn.node_type, count(*) FROM knowledge_nodes kn
WHERE kn.project_id=(SELECT id FROM projects WHERE name='Dasin 3') GROUP BY 1 ORDER BY 2 DESC;
SELECT e.edge_type, count(*) FROM knowledge_edges e
WHERE e.project_id=(SELECT id FROM projects WHERE name='Dasin 3') GROUP BY 1 ORDER BY 2 DESC;"
```
Expected: entity/concept + `mentions` counts materially above baseline (Dasin 3 was 28 concepts / 56 mentions from ~20% of the text).

- [ ] **Step 6: Checkpoint** — `mcp__serena__write_memory("checkpoint/ocr-content-loss-fix-<YYYY-MM-DD>", …)` with before/after numbers, and delete `backlog/…` entries this closes.

---

## Self-Review

- **Spec/evidence coverage:** Bug B (pre-heading drop, proven by the 9,857-char minimal repro) → Task 1. Bug A (garbage text layer trusted, proven by `extract_file_text(GPDT X1)` = 0.0s/0 diacritics) → Task 2. Real-corpus proof both are fixed → Task 3. Operational rebuild + the user-visible symptom (sparse graph) → Task 4. ✓
- **No placeholders:** every step has real code, a real command, and a stated expected result. Integration tests skip cleanly when the PDF fixtures are absent.
- **Type consistency:** `parse_markdown_sections` signature and `MarkdownSection(title, level, line_start, line_end, text, children)` unchanged (Task 1) → consumers `canonical.py:86` / `build_document_tree_json` need no change. `page_texts_and_renders` keeps its `(int, str, Image|None)` contract and the `render is None ⇒ use text_layer` invariant relied on by `files.py:77-92` (Task 2). Task 3 uses `extract_file_text -> (str, str)` as it exists today.
- **Out of scope (deliberate):** `_build_recovered_fields_section` stays as-is — Task 1 makes appending a heading safe, which is the correct layer to fix. `worker.py`, `handle_aaaa_sync`, and the AAAA endpoints are untouched (Dasin 3 ≡ Dasin 4 proves the pipeline, not the channel, is at fault). The known `except → yield i, tl, None` render-failure fallback (which can still surface garbage on a mangled page) is left alone — it now only triggers on an actual render failure, and is logged.
- **Risk / watch-item:** `_looks_like_mangled_vi` is Vietnamese-specific. That matches the pipeline, which is already VN-specific (`normalize_vi`, `to_markdown_vi`, Tesseract `-l vie`). A born-digital, image-bearing, all-numeric page could be OCR'd unnecessarily — cost is latency, not correctness, and the `_MANGLED_MIN_LETTERS = 100` floor plus the `_page_has_image` requirement keep it narrow. If a non-VN corpus is ever ingested, gate this behind a setting.
