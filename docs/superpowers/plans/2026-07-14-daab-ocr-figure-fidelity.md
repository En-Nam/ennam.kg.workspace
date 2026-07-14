# DAAB OCR Figure Fidelity (Plan B2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover OCR-lost / mangled figures in the scanned Vietnamese corpus — make "33,6 ha" retrievable (or explicitly `needs_review`) and fix captured-but-mangled numbers (`122,8Iha`→`122,81 ha`) — via CPU preprocessing + a language-correct field OCR + a CPU fallback, **without a full re-ingest, GPU, engine rip-out, or LLM-vision**.

**Architecture:** Three CPU-only levers behind the existing two-engine OCR (Tesseract `vie` for body text; RapidOCR for structured fields): (1) add image preprocessing before Tesseract; (2) fix the RapidOCR fields path to a Vietnamese/latin recognition model + tolerate digit/letter confusables in the unit regex; (3) a fallback that runs the *other* detector on pages whose expected figure is still missing, then routes the residual to `needs_review` (fail-loud). This is Plan **B2** of the OCR/entity spec; Plan **B1** (entity-variant reduction) shipped separately and is complete.

**Tech Stack:** Python 3.12 (Pillow/OpenCV for preprocessing, `rapidocr_onnxruntime`, `pytesseract`), pytest, the existing `OCREngine` seam.

## Global Constraints

- **CPU-only, no new heavyweight dependency, no full re-ingest, no GPU/marker/omniparse, no LLM-vision.** (LLM-vision is out — the platform AI abstraction is text-only; verified.)
- **Preprocessing must be behind a flag/seam and A/B-gated** — adopt a config only if the harness shows a CER / figure-retrievability win, never on faith.
- **Fail-loud (Rule 12):** a figure that survives none of the levers is recorded to the document node's metadata as an un-recovered expected field and logged at WARNING — never silently absent.
- **No change to chunking, embedding, resolution, or the query/RAG path** — B2 is OCR-side only. RAG latency stays unchanged; only extraction quality improves.
- **Targeted, not corpus-wide reprocessing:** re-OCR only the pages behind the labeled failures, never all 77 docs.
- Python: `ruff`, type hints, pytest.

**Key files & symbols (verified):**
- `ennam.kg.python/src/ennam_kg/ingestion/ocr/tesseract_engine.py` — `TesseractEngine.ocr_image(img: PIL.Image) -> str` (raw image, **zero preprocessing**; `pytesseract.image_to_string(img, lang='vie', config='--psm 1')`).
- `ennam.kg.python/src/ennam_kg/ingestion/ocr/pdf_render.py` — `page_texts_and_renders(path)` yields `(i, text_layer, render)`; `render` is a PIL Image (None when a text layer exists); 300 DPI.
- `ennam.kg.python/src/ennam_kg/ingestion/adapters/files.py` — `_extract_pdf` loops pages: `render is None → text_layer` else `tess.ocr_image(render)`; `extract_structured_fields_for_file` runs RapidOCR fields per scanned page.
- `ennam.kg.python/src/ennam_kg/ingestion/ocr/rapidocr_fields.py` — `_get_engine()` = `RapidOCR()` (**default ch+en model — the language bug**); `_AREA`/`_AMOUNT`/`_DOC_NO` regexes; `extract_structured_fields(img)`.
- `RapidOCR.__init__` accepts `config_path` + `**kwargs` (verified) — the vi/latin model is configurable, but the ONNX model+dict files must be **sourced** (see Task 3 spike).
- Cảng project `592c7ff7-9f6f-4cc5-9094-d9b3b685277e`; labeled failures (from `findings-rerun-2.md`): "33,6 ha" (unretrievable — hard-detection miss), `122,8Iha`/`4.3§ ha`/`Số O9` (captured-but-mangled), garbage chunk `a3856d16`.

---

### Task 1: Figure golden set + retrievability/CER harness (#0-F, gate)

**Files:**
- Create: `ennam.kg.python/scripts/b2_figure_metrics.py`
- Create: `docs/superpowers/plans/b2-golden-set.md`

**Interfaces:**
- Produces: a repeatable measurement of (a) **figure-retrievability** (boolean per target figure: present anywhere in a doc's extracted text/`structured_fields`?) and (b) **CER** on labeled line crops (diagnostic, for choosing preprocessing configs). Runs before/after each lever.

- [ ] **Step 1: Build the golden set**

Create `b2-golden-set.md`: for each labeled failure, record the **source PDF page** (path + page index) and the **ground-truth string** (`33,6 ha`, `122,81 ha`, `4.35 ha`, `Số 09`, plus the `a3856d16` garbage page). Source PDFs are under `doc_pdf_test/project_1`. Include the retrievability query:
```sql
-- Is a target figure present anywhere for the project after re-extraction?
SELECT count(*) FROM knowledge_nodes
WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e'
  AND node_type='document_chunk'
  AND unaccent(lower(properties->>'content')) LIKE '%33,6 ha%';
-- also check structured_fields on the document node:
SELECT properties->'structured_fields'->'areas' FROM knowledge_nodes
WHERE project_id='592c7ff7-...' AND node_type='document' AND ...;
```
(Use `unaccent` — Vietnamese diacritics survive `lower()`.)

- [ ] **Step 2: Write `b2_figure_metrics.py`**

A script that, given a list of `(pdf_path, page_index, ground_truth)` items: renders the page (reuse `pdf_render`), runs a supplied OCR callable, and reports per item: **found?** (ground-truth substring present, unaccent-normalized) and **CER** (a 10-line Levenshtein vs ground truth on the matched line). No production logic — a measurement wrapper. It must accept the OCR path as a parameter so it can score baseline vs preprocessed vs vi-model.

- [ ] **Step 3: Capture the BEFORE baseline**

Run against the golden set with the current pipeline. Record which figures are found (expect `33,6 ha` = NOT found; mangled ones found-but-wrong) + baseline CER. Save into `b2-golden-set.md`. This is the gate baseline.

- [ ] **Step 4: Commit**

```bash
cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace
git add ennam.kg.python/scripts/b2_figure_metrics.py docs/superpowers/plans/b2-golden-set.md
git commit -m "test(ocr): B2 figure retrievability + CER harness with golden set"
```

---

### Task 2: CPU preprocessing before Tesseract (#2 — the reliable core)

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/ingestion/ocr/preprocess.py`
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/ocr/tesseract_engine.py`
- Modify: `ennam.kg.python/src/ennam_kg/config.py` (a feature flag)
- Test: `ennam.kg.python/tests/ingestion/test_ocr_preprocess.py`

**Interfaces:**
- Produces: `preprocess_for_ocr(img: PIL.Image.Image) -> PIL.Image.Image` — grayscale → adaptive/Otsu binarize → deskew → light denoise (optional upscale for small pages). Deterministic. `TesseractEngine(preprocess: bool = <config>)` applies it before `image_to_string`.

- [ ] **Step 1: Write the failing tests**

Preprocessing transforms are deterministic and testable without OCR:

```python
from PIL import Image
import numpy as np
from ennam_kg.ingestion.ocr.preprocess import preprocess_for_ocr


def test_output_is_binary_grayscale():
    img = Image.new("RGB", (200, 100), (180, 180, 180))
    out = preprocess_for_ocr(img)
    arr = np.array(out.convert("L"))
    # after binarize, pixels are near-0 or near-255
    assert set(np.unique(arr)).issubset({0, 255}) or (arr.min() < 20 and arr.max() > 235)


def test_deskew_reduces_rotation():
    # a skewed synthetic text block should come back closer to axis-aligned;
    # assert the function runs and preserves size ballpark (no crash on rotation).
    img = Image.new("L", (300, 200), 255)
    out = preprocess_for_ocr(img.convert("RGB"))
    assert out.size[0] > 0 and out.size[1] > 0


def test_idempotent_on_clean_binary():
    img = Image.new("RGB", (100, 100), (255, 255, 255))
    once = preprocess_for_ocr(img)
    twice = preprocess_for_ocr(once)
    assert np.array(twice.convert("L")).shape == np.array(once.convert("L")).shape
```

> These lock the *contract* (binary grayscale output, no crash on rotation, stable). The real proof is Step 5's CER measurement, not unit assertions — preprocessing quality is measured, not asserted.

- [ ] **Step 2: Run to verify they fail**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_ocr_preprocess.py -v`
Expected: `ModuleNotFoundError: preprocess`.

- [ ] **Step 3: Implement `preprocess.py`**

Use Pillow + numpy (already deps); add OpenCV (`opencv-python-headless`) only if deskew needs it — prefer a Pillow/numpy deskew (moments/Hough via numpy) to avoid a new dep. Minimal:
```python
"""Image preprocessing for scanned-Vietnamese OCR: grayscale → binarize → deskew → denoise."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps


def _otsu_binarize(gray: np.ndarray) -> np.ndarray:
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    total = gray.size
    sum_all = np.dot(np.arange(256), hist)
    w_b = 0.0; sum_b = 0.0; best_t = 127; best_var = -1.0
    for t in range(256):
        w_b += hist[t]
        if w_b == 0: continue
        w_f = total - w_b
        if w_f == 0: break
        sum_b += t * hist[t]
        m_b = sum_b / w_b; m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best_var: best_var = var; best_t = t
    return (gray > best_t).astype(np.uint8) * 255


def preprocess_for_ocr(img: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(img)
    gray = gray.filter(ImageFilter.MedianFilter(size=3))  # light denoise
    binn = _otsu_binarize(np.array(gray))
    out = Image.fromarray(binn, mode="L")
    # deskew: estimate small rotation via the darkest-row projection variance; rotate back.
    # (keep simple — a bounded ±10° search maximizing horizontal projection variance)
    return _deskew(out)


def _deskew(img: Image.Image) -> Image.Image:
    # PERF: search the best angle on a DOWNSCALED copy (angle is scale-invariant),
    # then apply the single chosen rotation to the full-res image. A 300-DPI page is
    # ~2500x3500; searching 17 rotations at full res would cost ~1-3s/page. Downscale
    # to ~1000px wide first → the search is ~cheap, the final rotate is one op.
    small = img.copy()
    if small.width > 1000:
        small = small.resize((1000, max(1, round(small.height * 1000 / small.width))))
    best_angle = 0.0; best_score = -1.0
    for angle in np.arange(-8, 8.1, 1.0):
        rot = np.array(small.rotate(angle, expand=False, fillcolor=255))
        score = float(np.var(np.sum(255 - rot, axis=1)))
        if score > best_score: best_score = score; best_angle = angle
    return img.rotate(best_angle, expand=False, fillcolor=255) if best_angle else img
```
Then in `tesseract_engine.py`, add a `preprocess: bool` ctor param (default from config), and in `ocr_image`: `if self._preprocess: img = preprocess_for_ocr(img)` before `image_to_string`. Add `ocr_preprocess_enabled: bool = False` to `config.py` and wire `TesseractEngine(preprocess=settings.ocr_preprocess_enabled)` at the call site in `files.py`.

- [ ] **Step 4: Run unit tests**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_ocr_preprocess.py -v`
Expected: PASS.

- [ ] **Step 5: A/B on the golden set (the real gate)**

Run `b2_figure_metrics.py` with preprocessing ON vs OFF over the golden set. **Adopt (flip `ocr_preprocess_enabled` default to True) only if** figure-retrievability improves and/or CER drops with no regression on currently-correct figures. Record the numbers in `b2-golden-set.md`. If it doesn't help, keep it OFF and behind the flag (no harm).

- [ ] **Step 6: Lint + commit**

```bash
cd ennam.kg.python
uv run ruff check src/ennam_kg/ingestion/ocr/preprocess.py src/ennam_kg/ingestion/ocr/tesseract_engine.py
git add src/ennam_kg/ingestion/ocr/preprocess.py src/ennam_kg/ingestion/ocr/tesseract_engine.py src/ennam_kg/config.py tests/ingestion/test_ocr_preprocess.py
git commit -m "feat(ocr): CPU preprocessing (binarize/deskew/denoise) before Tesseract, flag-gated"
```

---

### Task 3: Fix RapidOCR fields language + unit tolerance (#4)

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/ocr/rapidocr_fields.py`
- Test: `ennam.kg.python/tests/ingestion/test_rapidocr_fields.py`

**Interfaces:**
- Produces: `extract_structured_fields` using a Vietnamese/latin RapidOCR rec model (if sourced) + a `_normalize_ocr_text` that repairs adjacent-to-unit confusables so `122,8Iha` parses as an area.

- [ ] **Step 1 (SPIKE — decision gate): source a vi/latin RapidOCR ONNX model**

`RapidOCR.__init__(config_path=..., **kwargs)` can point at a custom rec model. Determine, in ~30 min: is a **Vietnamese** or **latin** PP-OCR rec ONNX model + dict readily obtainable (PaddleOCR `latin`/`vi` model → ONNX; `git_research/PaddleOCR` ships `vi_dict.txt`)? 
- **If yes:** wire it via `config_path`/kwargs; this fixes the ch+en language bug at the source. Proceed to Step 2 with the model in place.
- **If not readily available (no ONNX artifact, only Paddle weights needing conversion):** **do NOT block B2 on model conversion.** Skip the model swap; the unit-tolerance regex (Steps 2-4) is the independent, reliable part. Note the deferral in `b2-golden-set.md`. The `latin` model (broader than ch+en, includes diacritics) is the pragmatic middle option if available without conversion.

Record the decision (model wired / deferred) — this is the honest scope gate for #4's model half.

- [ ] **Step 2: Write the failing unit-tolerance test**

The regex repair is deterministic and independent of the model. **Scope: number+unit (area/amount) spans only** — the verified critical failures. Doc-number confusables ("Số O9") are out of scope (a different pattern, lower value; extend later if needed).
```python
from ennam_kg.ingestion.ocr.rapidocr_fields import _repair_confusables_near_units, _AREA


def test_confusable_repair_recovers_area():
    # I→1, §→5, O→0 ONLY inside a number+unit span.
    assert _AREA.search(_repair_confusables_near_units("dien tich 122,8Iha")) is not None
    assert _repair_confusables_near_units("4.3§ ha") == "4.35 ha"


def test_repair_does_not_touch_normal_text():
    # Confusable letters OUTSIDE a number+unit span are untouched (no over-reach).
    assert _repair_confusables_near_units("Hàm Giang 122,81 ha") == "Hàm Giang 122,81 ha"
    assert _repair_confusables_near_units("So O9 tai lieu") == "So O9 tai lieu"  # no unit → unchanged
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_rapidocr_fields.py -v`
Expected: FAIL — `_repair_confusables_near_units` undefined.

- [ ] **Step 4: Implement the repair + wire the model (if spike succeeded)**

Add to `rapidocr_fields.py`:
```python
# Digit/letter confusables OCR emits inside numbers. Applied ONLY within a
# number+unit span, so normal words (incl. "So O9") are never rewritten.
_CONFUSABLE = str.maketrans({"I": "1", "l": "1", "§": "5", "O": "0", "o": "0"})
# A number+unit span, tolerant of confusable chars where a digit belongs.
_NUM_UNIT = re.compile(r"\d[\d.,IlOo§]*\s?(?:ha|m²|m2|m³|m3)", re.IGNORECASE)

def _repair_confusables_near_units(text: str) -> str:
    """Repair digit/letter confusables ONLY inside a number+unit span (areas/amounts)."""
    return _NUM_UNIT.sub(lambda m: m.group(0).translate(_CONFUSABLE), text)
```
> The repair is strictly span-scoped: `_NUM_UNIT` matches a digit-led run ending in a unit, and only that matched substring is translated — so `test_repair_does_not_touch_normal_text` (incl. the unit-less "So O9") stays unchanged. Note `S→5` is deliberately NOT in `_CONFUSABLE` (it would corrupt unit-adjacent text); if a real `S`-for-`5` case appears in an area, add it scoped to inside `_NUM_UNIT` only.

Call it inside `extract_structured_fields` after `_normalize_ocr_text`: `text = _repair_confusables_near_units(text)`. If the spike (Step 1) sourced a model, set `_engine = RapidOCR(config_path=<vi_config>)` (or kwargs) in `_get_engine`.

- [ ] **Step 5: Run tests + golden-set A/B**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_rapidocr_fields.py -v`
Expected: PASS. Then re-run `b2_figure_metrics.py` on the fields path; the mangled figures should now parse. Record.

- [ ] **Step 6: Lint + commit**

```bash
cd ennam.kg.python
uv run ruff check src/ennam_kg/ingestion/ocr/rapidocr_fields.py tests/ingestion/test_rapidocr_fields.py
git add src/ennam_kg/ingestion/ocr/rapidocr_fields.py tests/ingestion/test_rapidocr_fields.py
git commit -m "feat(ocr): repair digit/letter confusables in field extraction (+ vi model if sourced)"
```

---

### Task 4: Residual-figure fallback (#3 — CPU second detector + needs_review)

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/adapters/files.py` (or a small `ocr/fallback.py`)
- Test: `ennam.kg.python/tests/ingestion/test_ocr_fallback.py`

**Interfaces:**
- Produces: after #2/#4, for a page whose **expected** structured field is still empty, run RapidOCR (vi/latin if available, else default) full-page as a *second detector*; if the field is still missing, record it on the document node as an un-recovered expected field (`structured_fields.unrecovered`) and log WARNING (fail-loud). **No LLM-vision.**

- [ ] **Step 1: Write the failing test**

Test the fallback decision logic (mock the two detectors):
```python
from ennam_kg.ingestion.ocr.fallback import recover_or_flag


def test_second_detector_recovers():
    primary = {"areas": []}           # Tesseract/RapidOCR-fields missed it
    second = {"areas": ["33,6 ha"]}   # second detector found it
    out = recover_or_flag(primary, lambda: second, expected={"areas"})
    assert out["areas"] == ["33,6 ha"]
    assert "unrecovered" not in out


def test_flags_unrecovered_when_both_miss():
    primary = {"areas": []}
    out = recover_or_flag(primary, lambda: {"areas": []}, expected={"areas"})
    assert "areas" in out.get("unrecovered", [])   # fail-loud marker present
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_ocr_fallback.py -v`
Expected: `ModuleNotFoundError: fallback`.

- [ ] **Step 3: Implement `recover_or_flag`**

```python
"""Residual-figure fallback: second detector, then fail-loud needs_review marker. No LLM-vision."""
from __future__ import annotations

from collections.abc import Callable


def recover_or_flag(
    primary: dict[str, list[str]],
    second_detector: Callable[[], dict[str, list[str]]],
    expected: set[str],
) -> dict[str, list[str]]:
    out = {k: list(v) for k, v in primary.items()}
    missing = {f for f in expected if not out.get(f)}
    if not missing:
        return out
    second = second_detector()
    still_missing = set()
    for f in missing:
        if second.get(f):
            out[f] = second[f]
        else:
            still_missing.add(f)
    if still_missing:
        out.setdefault("unrecovered", []).extend(sorted(still_missing))
    return out
```
Wire it in `extract_structured_fields_for_file`: define `expected` per-doc conservatively (e.g. `{"areas"}` for land/planning docs, or a global expectation set), and call `recover_or_flag(fields, lambda: <full-page RapidOCR pass>, expected)`. Log WARNING when `unrecovered` is non-empty so the harness/operator sees it. **Only trigger the second detector when a field is missing** (bounded cost).

- [ ] **Step 4: Run tests to verify pass**

Run: `cd ennam.kg.python && uv run pytest tests/ingestion/test_ocr_fallback.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
cd ennam.kg.python
uv run ruff check src/ennam_kg/ingestion/ocr/fallback.py tests/ingestion/test_ocr_fallback.py
git add src/ennam_kg/ingestion/ocr/fallback.py src/ennam_kg/ingestion/adapters/files.py tests/ingestion/test_ocr_fallback.py
git commit -m "feat(ocr): residual-figure fallback (second detector + fail-loud needs_review marker)"
```

---

### Task 5: Rebuild + targeted re-OCR + verify

**Files:** none (operational; runbook in `b2-golden-set.md`).

**Interfaces:**
- Consumes: Tasks 1–4 deployed with `ocr_preprocess_enabled` set per the Task-2 A/B result.
- Produces: the labeled figures retrievable or explicitly `unrecovered`; no regression on correct fields.

- [ ] **Step 1: Rebuild the worker/indexer images**

```bash
cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace
docker compose up -d --build worker indexer
docker compose ps
```

- [ ] **Step 2: Targeted re-OCR of the labeled docs (MUST bypass content-hash dedup)**

**Critical:** the ingest pipeline has tier-3 content-hash dedup (`engine.py:241` "content-hash dedup hit") — **re-uploading an identical PDF reuses the existing node and SKIPS OCR entirely**, so a naive re-upload would run **none** of the new B2 OCR code and the verification would show no change. To force fresh OCR you MUST first remove the existing doc so the re-upload is treated as new:

1. For each labeled doc, **soft-delete its canonical row + delete its substrate** (hub + sections + chunks + embeddings + similar_to edges) — reuse the dedup-cleanup SQL pattern (`docs/superpowers/plans/2026-07-13-daab-document-dedup.md` Task 6 Step 2), scoped to just those `document_id`s (not the whole project).
2. **Verify** 0 live nodes + 0 live canonical rows for those docs (hard gate — else dedup will still reuse).
3. **Re-ingest only those specific docs** (from `doc_pdf_test/project_1`) via the upload path — NOT all 77.
4. Confirm the worker log shows fresh OCR (not "content-hash dedup hit") and new `structured_fields`.

> After re-ingest, B1's entity resolution will re-run on the new nodes (worker post-resolve) — expect the investor variants to re-merge/re-queue per NFR-256; that's fine and independent of the figure fix.

- [ ] **Step 3: Verify success criteria**

Run `b2_figure_metrics.py` against the re-processed docs. Expected:
- **"33,6 ha" retrievable** (in chunk content or `structured_fields.areas`) **OR** present in `structured_fields.unrecovered` (fail-loud — never silently absent).
- **Mangled figures parse:** `122,8Iha`→`122,81 ha`, etc., appear correctly in `areas`.
- **No regression:** figures that were already correct still parse; body-text chunks not degraded (spot-check a previously-good doc).

- [ ] **Step 4: Checkpoint + backlog**

Via `mcp__serena__write_memory("checkpoint/<agent>-2026-07-14", …)`: record before/after figure-retrievability, the preprocessing A/B result, and the #4 model spike decision (wired or deferred). Update `mem:backlog/daab-retrieval-quality-gaps-postfix`: OCR-figure half of the gap addressed; note any deferred model conversion.

---

## Self-Review

**Spec coverage (B2 portion):** §4 #0-figure (harness) → Task 1. §4 #2 (preprocessing) → Task 2. §4 #4 (rapidocr vi + unit tolerance) → Task 3 (model half spike-gated). §4 #3 (fallback: second detector + needs_review, NOT LLM-vision) → Task 4. §8 success criterion 2 ("33,6 ha" retrievable or needs_review; mangled parse) → Task 5 Step 3. Resource constraints (CPU-only, targeted, no vision) threaded through Global Constraints + Task 3 spike + Task 5 targeted re-OCR. **B1 entity scope is a separate, completed plan — not here.**

**Placeholder scan:** No TBDs. The Task-3 spike has an explicit two-branch decision (model wired / deferred) with a concrete fallback (unit-regex ships regardless) — a real decision gate, not a deferral. The Otsu/deskew code is complete; the regex spans are "adjust to satisfy the tests" with the over-reach guard test as the contract — deliberate, because exact OCR spans are data-shaped.

**Consistency / risk:** preprocessing is flag-gated and A/B-adopted (Task 2 Step 5) — never shipped on faith. #4's risky half (vi model) is isolated behind a spike so B2 delivers value (unit-tolerance + preprocessing + fallback) even if the model isn't readily available. Fail-loud (`unrecovered` marker) is tested (Task 4) and verified (Task 5) so no figure is silently dropped. No change touches chunk/embed/resolution/RAG — the performance claim (RAG unaffected, ingest ~neutral) holds.

**Type consistency:** `preprocess_for_ocr(img)->Image` (Task 2). `_repair_confusables_near_units(text)->str` (Task 3). `recover_or_flag(primary, second_detector, expected)->dict` (Task 4) identical across def/test.
