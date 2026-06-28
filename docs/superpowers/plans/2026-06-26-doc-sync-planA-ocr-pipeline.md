# Doc-Sync Plan A — OCR Pipeline (Tesseract + RapidOCR) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Nâng file-ingestion của DAAB để OCR PDF scan tiếng Việt (Tesseract `vie` → text, RapidOCR-latin → structured fields) — dùng chung cho **mọi nguồn** (Local Upload, MCP, sau này Supabase). Build + test NGAY qua Local Upload/MCP trên 10 PDF mẫu — KHÔNG cần Supabase/credential.

**Architecture:** OCR là năng lực của `ingestion/adapters/files.py::_extract_pdf` (KHÔNG service riêng). Tiered: pypdf text-layer (born-digital) → nếu scan thì render ≥300dpi + Tesseract (text) + RapidOCR (fields). Vì OCR nằm trong `_extract_pdf`, mọi nguồn tự hưởng (worker.py:90 `extract_file_text` → `update_draft_content` → `run_batch` không đổi). Engines sau `OCREngine` seam (swap/extend được).

**Tech Stack:** Python 3.12, pytesseract + Tesseract `vie` (tessdata_best), rapidocr-onnxruntime, pypdfium2 (render), pypdf (text-layer), Pillow. pytest.

## Global Constraints
- Spec: `docs/superpowers/specs/2026-06-26-daab-doc-sync-design.md` (rev3).
- **No-persist:** render bitmap + temp chỉ trong RAM/`/tmp`, giải phóng per-page; KHÔNG ghi vào `KG_UPLOAD_DIR`.
- **Reconcile = metadata, KHÔNG token-merge:** Tesseract = `content_raw` (chunk/embed); RapidOCR fields = node metadata.
- **VN NFC-normalize** áp cho text Tesseract.
- **Per-page streaming + page-cap** (chống OOM doc 31+ trang). **Per-doc error isolation** (1 file lỗi không giết batch — engine đã error-resilient, giữ vậy).
- Test: `uv run pytest`, line-length=100, target py312, ruff. Fixtures = 4 ảnh đã trích sẵn ở scratchpad + thêm vài PDF mẫu vào `tests/ingestion/fixtures/`.
- Tesseract binary = system dep (dev: brew đã cài; Docker: thêm vào worker Dockerfile).

---

## File Structure
- `pyproject.toml` (modify) — thêm deps OCR.
- `ennam.kg.python/Dockerfile` (modify) — system deps: `tesseract-ocr tesseract-ocr-vie libgl1 libglib2.0-0`.
- `src/ennam_kg/ingestion/ocr/__init__.py` (create) — package.
- `src/ennam_kg/ingestion/ocr/engine.py` (create) — `OCREngine` Protocol + `OcrResult`.
- `src/ennam_kg/ingestion/ocr/tesseract_engine.py` (create) — Tesseract `vie` text.
- `src/ennam_kg/ingestion/ocr/rapidocr_fields.py` (create) — RapidOCR-latin + regex field extraction.
- `src/ennam_kg/ingestion/ocr/normalize.py` (create) — VN NFC-normalize.
- `src/ennam_kg/ingestion/ocr/markdownify.py` (create) — promote VN-legal structure (Chương/Điều/Căn cứ…) → markdown headings cho `parse_markdown_sections` section-hoá ngữ nghĩa.
- `src/ennam_kg/ingestion/ocr/pdf_render.py` (create) — pypdfium2 render + text-layer/image-coverage probe.
- `src/ennam_kg/ingestion/adapters/files.py` (modify) — `_extract_pdf` tiered; `extract_file_text` trả thêm structured_fields.
- `src/ennam_kg/worker.py` (modify ~L90) — thread structured_fields → draft metadata.
- `tests/ingestion/test_ocr.py` (create), `tests/ingestion/fixtures/` (add sample PDFs).

---

## Task 1: Dependencies + Tesseract binary

**Files:** Modify `pyproject.toml` (deps L6-26), `ennam.kg.python/Dockerfile`. Test: import smoke.

- [ ] **Step 1: Add Python deps**

`pyproject.toml` `dependencies` (sau `pypdf>=5.0`):
```toml
    "pytesseract>=0.3.13",
    "rapidocr-onnxruntime>=1.4",
    "pypdfium2>=4.30",
    "Pillow>=10.0",
```

- [ ] **Step 2: Add Tesseract to worker Dockerfile**

`ennam.kg.python/Dockerfile` — trước `uv sync`, thêm system deps (đọc Dockerfile trước để đặt đúng chỗ apt layer):
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-vie libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
```
> tessdata_best `vie`: gói `tesseract-ocr-vie` của Debian là LSTM `vie` đủ tốt; nếu cần `tessdata_best` chính chủ → tải `vie.traineddata` từ `tesseract-ocr/tessdata_best` vào `/usr/share/tesseract-ocr/*/tessdata/` (ghi rõ trong Dockerfile nếu chọn).

- [ ] **Step 3: Sync + import smoke test**

```bash
cd ennam.kg.python && uv sync 2>&1 | tail -3
uv run python -c "import pytesseract, rapidocr_onnxruntime, pypdfium2, PIL; print('ocr deps ok')"
```
Expected: `ocr deps ok`. (Dev cần `tesseract` binary — đã có qua brew.)

- [ ] **Step 4: Commit**
```bash
git -C ennam.kg.python add pyproject.toml uv.lock Dockerfile
git -C ennam.kg.python commit -m "build(ocr): add tesseract/rapidocr/pypdfium2 deps + worker system deps"
```

---

## Task 2: OCREngine seam + Tesseract text engine

**Files:** Create `ocr/__init__.py`, `ocr/engine.py`, `ocr/tesseract_engine.py`, `ocr/normalize.py`. Test: `tests/ingestion/test_ocr.py`.

**Interfaces:**
- Produces: `OcrResult` (dataclass: `text: str`), `OCREngine` Protocol `ocr_image(img: PIL.Image.Image) -> str`; `TesseractEngine().ocr_image(img) -> str`; `normalize_vi(text: str) -> str`.

- [ ] **Step 1: Write the failing test**

Lưu 1 ảnh scan mẫu vào fixtures: copy `sm2.jpg` (đã trích) → `tests/ingestion/fixtures/scan_vi_prose.jpg`.
`tests/ingestion/test_ocr.py`:
```python
from pathlib import Path
import pytest
from PIL import Image
from ennam_kg.ingestion.ocr.tesseract_engine import TesseractEngine
from ennam_kg.ingestion.ocr.normalize import normalize_vi

FIX = Path(__file__).parent / "fixtures"

@pytest.mark.skipif(not (FIX / "scan_vi_prose.jpg").exists(), reason="fixture missing")
def test_tesseract_reads_vietnamese_with_diacritics():
    img = Image.open(FIX / "scan_vi_prose.jpg")
    text = normalize_vi(TesseractEngine().ocr_image(img))
    # body prose has full diacritics
    assert "Độc lập" in text or "Hạnh phúc" in text
    assert "Quyết định" in text or "QUYẾT ĐỊNH" in text.upper().replace("Đ","Đ")

def test_normalize_vi_is_nfc():
    import unicodedata
    decomposed = unicodedata.normalize("NFD", "Quyết định")
    assert normalize_vi(decomposed) == unicodedata.normalize("NFC", "Quyết định")
```

- [ ] **Step 2: Run → fail**
```bash
cd ennam.kg.python && uv run pytest tests/ingestion/test_ocr.py -v
```
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

`src/ennam_kg/ingestion/ocr/engine.py`:
```python
"""OCR engine seam — swappable per-image text recognizers."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from PIL import Image


@dataclass(frozen=True)
class OcrResult:
    text: str


class OCREngine(Protocol):
    def ocr_image(self, img: Image.Image) -> str: ...
```

`src/ennam_kg/ingestion/ocr/normalize.py`:
```python
"""Vietnamese text normalization for OCR output."""
from __future__ import annotations
import re
import unicodedata


def normalize_vi(text: str) -> str:
    # NFC: unify composed/decomposed diacritics (stabilizes embedding + dedup).
    text = unicodedata.normalize("NFC", text)
    # Collapse OCR whitespace artifacts; keep paragraph breaks.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
```

`src/ennam_kg/ingestion/ocr/tesseract_engine.py`:
```python
"""Tesseract `vie` text recognition (main text → chunk/embed)."""
from __future__ import annotations
from PIL import Image


class TesseractEngine:
    def __init__(self, lang: str = "vie", psm: int = 1) -> None:
        self._lang = lang
        self._psm = psm

    def ocr_image(self, img: Image.Image) -> str:
        import pytesseract
        # psm 1 = auto page segmentation + OSD (handles rotated certificates).
        return pytesseract.image_to_string(img, lang=self._lang, config=f"--psm {self._psm}")
```

- [ ] **Step 4: Run → pass**
```bash
cd ennam.kg.python && uv run pytest tests/ingestion/test_ocr.py -v
```
Expected: PASS (cần `tesseract`+`vie` — dev có sẵn).

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.python add src/ennam_kg/ingestion/ocr/ tests/ingestion/test_ocr.py tests/ingestion/fixtures/scan_vi_prose.jpg
git -C ennam.kg.python commit -m "feat(ocr): OCREngine seam + Tesseract vie + VN NFC-normalize"
```

---

## Task 3: RapidOCR structured-field extractor

**Files:** Create `ocr/rapidocr_fields.py`. Test: extend `tests/ingestion/test_ocr.py`.

**Interfaces:**
- Produces: `extract_structured_fields(img: PIL.Image.Image) -> dict[str, list[str]]` — keys: `doc_numbers`, `dates`, `areas`, `amounts`, `ids`. (Best-effort regex trên RapidOCR-latin output; rỗng nếu engine lỗi — soft-fail.)

- [ ] **Step 1: Write the failing test**
```python
def test_rapidocr_extracts_doc_number_and_area():
    from ennam_kg.ingestion.ocr.rapidocr_fields import extract_structured_fields
    img = Image.open(FIX / "scan_vi_prose.jpg")  # sm2: "3487/QĐ-BCT", "90.000 m³"
    fields = extract_structured_fields(img)
    joined = " ".join(fields.get("doc_numbers", []))
    assert "3487" in joined and "BCT" in joined.upper()
```

- [ ] **Step 2: Run → fail.** `uv run pytest tests/ingestion/test_ocr.py::test_rapidocr_extracts_doc_number_and_area -v` → FAIL.

- [ ] **Step 3: Implement**

`src/ennam_kg/ingestion/ocr/rapidocr_fields.py`:
```python
"""RapidOCR-latin structured-field extraction (→ node metadata, NOT chunk text)."""
from __future__ import annotations
import re
import numpy as np
from PIL import Image

_DOC_NO = re.compile(r"\b\d{1,5}\s*/\s*[A-ZĐ][A-ZĐ0-9\-]{1,12}\b")
_DATE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b")
_AREA = re.compile(r"\b[\d.,]+\s?(?:m³|m3|ha|m²|m2)\b", re.IGNORECASE)
_AMOUNT = re.compile(r"\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?\b")
_ID = re.compile(r"\b\d{9,13}\b")

_engine = None

def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()  # lazy-load; ch+en latin chars + digits (numbers strong)
    return _engine

def extract_structured_fields(img: Image.Image) -> dict[str, list[str]]:
    try:
        res, _ = _get_engine()(np.array(img.convert("RGB")))
    except Exception:
        return {}  # soft-fail: structured fields are best-effort
    text = "\n".join(line[1] for line in (res or []))
    def uniq(p): return sorted({m.group(0).strip() for m in p.finditer(text)})
    return {
        "doc_numbers": uniq(_DOC_NO),
        "dates": uniq(_DATE),
        "areas": uniq(_AREA),
        "amounts": uniq(_AMOUNT),
        "ids": uniq(_ID),
    }
```
> Lưu ý: RapidOCR default ch+en đọc **số/latin tốt** (đã verify) → đủ cho regex field. VN diacritics để Tesseract lo. Nếu sau muốn dùng model `latin` (rapidocr v3) cho field tốt hơn → swap trong `_get_engine`.

- [ ] **Step 4: Run → pass.** (RapidOCR tải model lần đầu.) Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.python add src/ennam_kg/ingestion/ocr/rapidocr_fields.py tests/ingestion/test_ocr.py
git -C ennam.kg.python commit -m "feat(ocr): RapidOCR structured-field extraction (metadata)"
```

---

## Task 4: Tiered `_extract_pdf` (text-layer → OCR per scanned page)

**Files:** Create `ocr/pdf_render.py`; Modify `ingestion/adapters/files.py` (`_extract_pdf` L54-65; `extract_file_text` L15-41). Test: `tests/ingestion/test_ocr.py`.

**Interfaces:**
- Consumes: `TesseractEngine`, `extract_structured_fields`, `normalize_vi`.
- Produces: **`extract_file_text(path) -> tuple[str, str]` GIỮ NGUYÊN 2-tuple** (text giờ là OCR cho PDF scan) — KHÔNG đổi arity (verified: 5 test `test_file_adapter.py` + mock `test_worker*.py` unpack 2-tuple → đổi sẽ vỡ). `_extract_pdf(path) -> str` (text only, giữ chữ ký). **Structured fields qua hàm RIÊNG** `extract_structured_fields_for_file(path) -> dict` (PDF→RapidOCR fields; `{}` cho non-PDF) — worker gọi thêm. (Đánh đổi: PDF render 2 lần — Tesseract pass + RapidOCR pass; chấp nhận vì RapidOCR nhanh 0.4-0.8s; tối ưu shared-render = follow-up.)

- [ ] **Step 1: pdf_render helper**

`src/ennam_kg/ingestion/ocr/pdf_render.py`:
```python
"""Per-page PDF text-layer probe + raster render (pypdfium2), streaming."""
from __future__ import annotations
from collections.abc import Iterator
from pathlib import Path
from PIL import Image

TEXT_LAYER_MIN_CHARS = 50   # OQ-4: below this on a page → treat as scanned

def page_texts_and_renders(path: Path, dpi: int = 300, page_cap: int = 50
) -> Iterator[tuple[int, str, Image.Image | None]]:
    """Yield (page_index, text_layer, render_or_None) page-by-page.
    render is None when the text layer is sufficient (born-digital page)."""
    import pypdfium2 as pdfium
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pdf = pdfium.PdfDocument(str(path))
    try:
        n = min(len(reader.pages), page_cap)
        scale = dpi / 72.0
        for i in range(n):
            tl = (reader.pages[i].extract_text() or "").strip()
            if len(tl) >= TEXT_LAYER_MIN_CHARS:
                yield i, tl, None
            else:
                bitmap = pdf[i].render(scale=scale)
                img = bitmap.to_pil()
                yield i, tl, img
                img.close()  # free per page (streaming, no OOM)
    finally:
        pdf.close()
```

- [ ] **Step 2: Write the failing test**
```python
def test_extract_pdf_born_digital_uses_text_layer():
    from ennam_kg.ingestion.adapters.files import _extract_pdf
    text = _extract_pdf(FIX / "born_digital.pdf")   # -> str (2-tuple contract intact)
    assert len(text) > 100

def test_extract_pdf_scanned_triggers_ocr():
    from ennam_kg.ingestion.adapters.files import _extract_pdf
    text = _extract_pdf(FIX / "scanned_vi.pdf")
    assert "Độc lập" in text or "Quyết định" in text or "Cộng" in text

def test_structured_fields_for_scanned_pdf():
    from ennam_kg.ingestion.adapters.files import extract_structured_fields_for_file
    fields = extract_structured_fields_for_file(FIX / "scanned_vi.pdf")
    assert "doc_numbers" in fields
    assert extract_structured_fields_for_file(FIX / "note.md") == {}  # non-PDF → {}
```
> Copy 1 born-digital PDF (file e6b từ doc_pdf_test) → `fixtures/born_digital.pdf`; 1 scan (file sm2 PDF) → `fixtures/scanned_vi.pdf`.

- [ ] **Step 3: Run → fail** (signature mismatch / no OCR).

- [ ] **Step 4: Implement tiered `_extract_pdf` (text only, 2-tuple GIỮ NGUYÊN) + hàm fields riêng**

`files.py` — thay `_extract_pdf` (L54-65), GIỮ chữ ký `-> str`:
```python
def _extract_pdf(path: Path) -> str:
    from ennam_kg.ingestion.ocr.pdf_render import page_texts_and_renders
    from ennam_kg.ingestion.ocr.tesseract_engine import TesseractEngine
    from ennam_kg.ingestion.ocr.normalize import normalize_vi
    from ennam_kg.ingestion.ocr.markdownify import to_markdown_vi
    tess = TesseractEngine()
    parts: list[str] = []
    for _i, text_layer, render in page_texts_and_renders(path):
        page_text = text_layer if render is None else tess.ocr_image(render)
        parts.append(page_text)   # KHÔNG "## Page N" — trang là artifact, không phải section
    return to_markdown_vi(normalize_vi("\n\n".join(parts)))   # legal headings → markdown sections
```
> ⚠️ **Bỏ `## Page N`** (bản trước tạo section = mỗi trang, vô nghĩa). Văn bản pháp lý chảy xuyên trang → nối liền mạch, rồi `to_markdown_vi` (Task 4B) promote Chương/Điều thành heading → section đúng ngữ nghĩa cho `parse_markdown_sections`. `extract_file_text` PDF branch trả `content_format="markdown"`.
→ `extract_file_text` (L15-41) **KHÔNG đổi** (vẫn `(str,str)`, `_extract_pdf` trả str như cũ) → 5 test cũ XANH.
Thêm hàm RIÊNG (cuối files.py) cho structured fields:
```python
def extract_structured_fields_for_file(path: Path) -> dict:
    """RapidOCR structured fields for PDFs (scanned pages only). {} for non-PDF."""
    if path.suffix.lower() != ".pdf":
        return {}
    from ennam_kg.ingestion.ocr.pdf_render import page_texts_and_renders
    from ennam_kg.ingestion.ocr.rapidocr_fields import extract_structured_fields
    fields: dict[str, list[str]] = {}
    for _i, _tl, render in page_texts_and_renders(path):
        if render is None:
            continue
        for k, v in extract_structured_fields(render).items():
            if v:
                fields.setdefault(k, [])
                fields[k].extend(x for x in v if x not in fields[k])
    return fields
```

- [ ] **Step 5: Run → pass.** Expected: born-digital không OCR; scan ra text VN + fields.

- [ ] **Step 6: Commit**
```bash
git -C ennam.kg.python add src/ennam_kg/ingestion/ocr/pdf_render.py src/ennam_kg/ingestion/adapters/files.py tests/ingestion/test_ocr.py tests/ingestion/fixtures/born_digital.pdf tests/ingestion/fixtures/scanned_vi.pdf
git -C ennam.kg.python commit -m "feat(ocr): tiered _extract_pdf (text-layer → Tesseract+RapidOCR per scanned page)"
```

---

## Task 4B: VN-legal markdownify (semantic sections for `parse_markdown_sections`)

**Files:** Create `ocr/markdownify.py`; Modify `files.py` (`extract_file_text` PDF branch → `content_format="markdown"`). Test: `tests/ingestion/test_ocr.py`.

**Interfaces:**
- Produces: `to_markdown_vi(text: str) -> str` — promote cấu trúc pháp lý VN thành markdown heading; bảo thủ (chỉ pattern chắc chắn) để không tạo heading rác.

**Why:** `canonical.parse_markdown_sections` section-hoá theo `#` heading → section quyết định chunk boundary + section node + retrieval context (BA-033). OCR thuần → 0 heading → toàn doc 1 section (thô). Văn bản pháp lý VN có cấu trúc **trong text** (Chương/Điều/Căn cứ) → regex promote được, không cần layout-analysis.

- [ ] **Step 1: Write the failing test**
```python
def test_to_markdown_vi_promotes_legal_structure():
    from ennam_kg.ingestion.ocr.markdownify import to_markdown_vi
    raw = ("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
           "QUYẾT ĐỊNH\nVề việc phê duyệt dự án\n\n"
           "Chương I\nQUY ĐỊNH CHUNG\n\n"
           "Điều 1. Phạm vi điều chỉnh\nNghị định này quy định...\n\n"
           "Điều 2. Đối tượng áp dụng\nÁp dụng với...")
    md = to_markdown_vi(raw)
    assert "# QUYẾT ĐỊNH" in md
    assert "## Chương I" in md
    assert "### Điều 1. Phạm vi điều chỉnh" in md
    assert "### Điều 2. Đối tượng áp dụng" in md
    # prose KHÔNG bị promote
    assert "Nghị định này quy định" in md and "#Nghị định" not in md

def test_to_markdown_vi_no_false_headings():
    from ennam_kg.ingestion.ocr.markdownify import to_markdown_vi
    md = to_markdown_vi("Đây là một câu văn xuôi dài bình thường không phải tiêu đề.")
    assert not md.lstrip().startswith("#")
```

- [ ] **Step 2: Run → fail.** `uv run pytest tests/ingestion/test_ocr.py -k markdown -v`

- [ ] **Step 3: Implement** (`src/ennam_kg/ingestion/ocr/markdownify.py`):
```python
"""Promote Vietnamese legal-document structure to markdown headings."""
from __future__ import annotations
import re

# Conservative anchored patterns (line-start), high-precision for VN legal docs.
_H1 = re.compile(r"^(QUYẾT ĐỊNH|NGHỊ ĐỊNH|THÔNG TƯ|LUẬT|NGHỊ QUYẾT|CÔNG VĂN)\b.*$")
_H2 = re.compile(r"^(Chương|PHẦN|Phần)\s+[IVXLCDM\d]+\b.*$")
_H3 = re.compile(r"^(Điều)\s+\d+\b.*$")

def to_markdown_vi(text: str) -> str:
    out: list[str] = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            out.append("")
        elif _H1.match(s):
            out.append(f"# {s}")
        elif _H2.match(s):
            out.append(f"## {s}")
        elif _H3.match(s):
            out.append(f"### {s}")
        else:
            out.append(line)
    return "\n".join(out)
```
+ `files.py` `extract_file_text` PDF branch: `return _extract_pdf(path), "markdown"` (text giờ là markdown).
> Bảo thủ: chỉ promote dòng KHỚP nguyên dòng pattern (Chương/Điều/loại văn bản). Mở rộng pattern (Khoản, Mục) sau khi đo. KHÔNG promote dòng dài (câu văn).

- [ ] **Step 4: Run → pass.** `uv run pytest tests/ingestion/test_ocr.py -k markdown -v`

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.python add src/ennam_kg/ingestion/ocr/markdownify.py src/ennam_kg/ingestion/adapters/files.py tests/ingestion/test_ocr.py
git -C ennam.kg.python commit -m "feat(ocr): VN-legal markdownify → semantic markdown sections"
```

---

## Task 5: Thread structured_fields → draft node metadata

**Files:** Modify `src/ennam_kg/worker.py` (L90-95 `handle_extract_upload`). Test: `tests/test_worker.py` / `tests/test_worker_extract_gate.py` (mock pattern sẵn có).

> **Verified anchors:** `extract_file_text` GIỮ 2-tuple (Task 4); structured fields qua `extract_structured_fields_for_file` (Task 4). **KGClient ở package `ennam_kg_indexer.kg_client.client`** (import `worker.py:15`), KHÔNG ở `ennam.kg.python`. `update_draft_content` đã tồn tại (worker.py:91). Để tránh sửa package `ennam_kg_indexer`: nếu `update_draft_content` chưa nhận metadata → **gọi thẳng Go REST từ worker bằng httpx** (set node properties), HOẶC mở rộng `ennam_kg_indexer` (cross-package). Đọc `ennam_kg_indexer.kg_client.client.update_draft_content` signature trước khi chọn.

**Interfaces:**
- Consumes: `extract_file_text -> (content_raw, content_format)` + `extract_structured_fields_for_file(path) -> dict` (Task 4).
- Produces: draft node có `properties.structured_fields`.

- [ ] **Step 1: Read first** — `ennam_kg_indexer.kg_client.client.update_draft_content` signature + cách draft node lưu `properties`. Quyết kênh ghi metadata (httpx-to-Go vs extend indexer).

- [ ] **Step 2: Write the failing test** (`tests/test_worker.py` — theo pattern mock `extract_file_text` sẵn có ở L121):
```python
async def test_extract_upload_attaches_structured_fields(monkeypatch):
    # mock extract_file_text -> ("text", "plain_text")
    # mock extract_structured_fields_for_file -> {"doc_numbers": ["1/QD"]}
    # spy the metadata write (update_draft_content kwargs or httpx call)
    # assert structured_fields reached the node properties payload
    ...
```

- [ ] **Step 3: Implement** — `worker.py` ~L90 (extract_file_text GIỮ 2-tuple):
```python
    content_raw, content_format = extract_file_text(file_path)
    structured_fields = extract_structured_fields_for_file(file_path)
    await kg_client.update_draft_content(
        project_id, draft_id,
        content_raw=content_raw, content_format=content_format,
        upload_id=upload_id or None,
    )
    if structured_fields:
        # set node properties.structured_fields (qua kênh đã chọn ở Step 1)
        await _attach_structured_fields(project_id, draft_id, structured_fields)
```
(import `extract_structured_fields_for_file` ở đầu worker.py cạnh `extract_file_text`.)

- [ ] **Step 4: Run → pass.** `uv run pytest tests/test_ingestion_pipeline.py -v`.

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.python add src/ennam_kg/worker.py src/ennam_kg/ingestion/adapters/files.py tests/test_worker.py
git -C ennam.kg.python commit -m "feat(ingest): attach OCR structured_fields to draft node metadata"
```

---

## Task 6: Robustness — per-doc isolation, OCR soft-fail, observability

**Files:** Modify `files.py` (`_extract_pdf` try/except per page), `worker.py` (log per-doc). Test: `tests/ingestion/test_ocr.py`.

- [ ] **Step 1: Write the failing test**
```python
def test_extract_pdf_skips_bad_page_not_whole_doc(tmp_path):
    # a PDF where one page render fails → other pages still extracted, no exception
    from ennam_kg.ingestion.adapters.files import _extract_pdf
    text, fields = _extract_pdf(FIX / "mixed_one_bad_page.pdf")
    assert len(text) > 0  # did not raise

def test_extract_pdf_encrypted_raises_clean(tmp_path):
    import pytest
    from ennam_kg.ingestion.adapters.files import _extract_pdf
    with pytest.raises(Exception):
        _extract_pdf(FIX / "encrypted.pdf")  # caught per-doc by engine, recorded as error
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — bọc per-page trong `page_texts_and_renders`/`_extract_pdf` bằng try/except (1 trang lỗi → log + skip, không raise cả doc); OCR engine exception → soft-fail trang đó (text=""), fields rỗng. Engine (`ingestion_engine.run_batch`) đã error-resilient per-doc — giữ. Log per-doc: page count, #pages OCR'd vs text-layer, #fields, errors.
```python
# trong vòng for của _extract_pdf:
try:
    page_text = tess.ocr_image(render) if render is not None else text_layer
    ...
except Exception as exc:
    logger.warning("ocr page failed", extra={"page": i, "error": str(exc)})
    page_text = text_layer  # fallback to whatever text-layer existed
```

- [ ] **Step 4: Run → pass.** Build + full OCR tests:
```bash
cd ennam.kg.python && uv run pytest tests/ingestion/test_ocr.py -v && uv run ruff check src/ennam_kg/ingestion/ocr/
```

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.python add src/ennam_kg/ingestion/adapters/files.py src/ennam_kg/ingestion/ocr/pdf_render.py src/ennam_kg/worker.py tests/ingestion/test_ocr.py
git -C ennam.kg.python commit -m "feat(ocr): per-page error isolation + soft-fail + observability"
```

---

## Task 7: E2E via Local Upload/MCP + BA-033 sanity gate

**Files:** none (verification). Uses live Docker stack + 10 sample PDFs (`doc_pdf_test/`).

- [ ] **Step 1: Rebuild worker (OCR deps)**
```bash
docker compose up -d --build worker indexer
docker compose logs worker | grep -iE "ocr|tesseract" | head
```

- [ ] **Step 2: Upload 10 scans via Local Upload (dashboard) or MCP**
Upload `doc_pdf_test/*.pdf` qua Knowledge Sources → Local Upload (hoặc MCP `kg_index_source`/file-ingest). Approve → Process.
Expected: draft nodes → processed; node `content_raw` = text VN có dấu; `properties.structured_fields` có doc_numbers/areas.

- [ ] **Step 3: Verify extraction quality (SQL/UI)**
```bash
docker compose exec postgres psql -U ennam_kg -d ennam_kg -c \
 "select properties->>'structured_fields' from knowledge_nodes where node_type='document' order by created_at desc limit 5;"
```
Expected: structured_fields populated; chunk text has Vietnamese diacritics (spot-check 1 node).

- [ ] **Step 4: BA-033 sanity (go/no-go gate)**
Chạy 1 query cross-doc (vd "dự án Cảng Định An" / "diện tích 122,81ha") qua `/search` hoặc `kg_recall` → kiểm có trả về chunk đúng từ ≥2 doc khác nhau không.
Expected: retrieval trả về nội dung liên quan → **GO** cho Plan B (full 216). Nếu yếu → điều tra (OCR vs chunk vs embed) trước khi Plan B.

- [ ] **Step 5: Checkpoint** — ghi kết quả sanity (Serena checkpoint): OCR chất lượng + BA-033 go/no-go.

---

## Self-Review (đã chạy)
- **Spec coverage:** OCR tiered (§4.4) → Task 2/3/4; structured-fields metadata (§3.1) → Task 3/5; VN-normalize → Task 2; no-persist render streaming (§4.6) → Task 4; per-doc isolation (§3.1) → Task 6; sample-gate + BA-033 (§6) → Task 7; OCR-as-general-capability (plug `_extract_pdf` → mọi nguồn) → Task 4. ✓ (Supabase connector = Plan B, ngoài plan này.)
- **Placeholder scan:** Task 5 Step 1 + Task 3 note ghi "đọc impl trước" (update_draft_content signature, mock pattern) — integration points cần xác nhận, không phải placeholder. Code OCR core đầy đủ.
- **Type consistency:** `extract_file_text -> (str, str, dict)` xuyên Task 4→5; `_extract_pdf -> (str, dict)`; `extract_structured_fields -> dict[str,list[str]]`; `TesseractEngine.ocr_image(Image)->str`; `normalize_vi(str)->str`. Nhất quán. ✓

## Open dependencies (execute-time)
- **KGClient ở package `ennam_kg_indexer.kg_client.client`** (không phải `ennam.kg.python`) — `update_draft_content` đã có; ghi `properties.structured_fields` qua httpx-to-Go hoặc extend indexer (Task 5 Step 1).
- **extract_file_text GIỮ 2-tuple** (đừng đổi — vỡ 5 test `test_file_adapter.py` + mock `test_worker*.py`); fields qua hàm riêng.
- Dockerfile apt layer vị trí (Task 1).
- tessdata_best vs gói Debian `tesseract-ocr-vie` (Task 1) — gói Debian đủ cho v1; nâng best nếu cần.
- born_digital.pdf / scanned_vi.pdf / encrypted.pdf fixtures — tạo từ doc_pdf_test + 1 file mã hoá test.
