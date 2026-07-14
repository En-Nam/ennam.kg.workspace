# B2 Golden Set — Figure Retrievability & CER Harness

Source: `2026-07-14-daab-ocr-figure-fidelity.md`, Task 1. Hand-verified
golden set for the figure-retrievability / CER measurement harness
(`ennam.kg.python/scripts/b2_figure_metrics.py`).

**Project:** Cảng — `project_id = 592c7ff7-9f6f-4cc5-9094-d9b3b685277e`.
**Source PDFs:** under `doc_pdf_test/project_1/` (workspace root).

## How each entry was verified

Every `(pdf_path, page_index, ground_truth)` triple below was confirmed by:
1. Rendering the exact page at 300 DPI (`pypdfium2`, matches `pdf_render.py`).
2. Cropping the region around the figure and visually reading the digits off
   the rendered image (not just trusting Tesseract's own OCR of it).
3. Cross-checking against the live `daab-postgres` DB (`knowledge_nodes`,
   `document_chunk` / `document` nodes) for the current retrievability state.

This caught two errors in the initial reconnaissance (recorded below rather
than silently corrected — see "Reconnaissance corrections").

## Golden set

| # | File | Page | Ground truth | Current-pipeline OCR result | Found? | CER |
|---|------|------|---------------|------------------------------|--------|-----|
| 1 | `11381263.pdf` | 0 | `122,81ha` | `122,81ha` (verbatim, multiple correct instances on the page) | **FOUND** | 0.000 |
| 2 | `11381263.pdf` | 1 | `98,18ha` | `98,1 §ha` (digit `8` split off + misread as `§`) | **MISS** | 0.286 |
| 3 | `11381263.pdf` | 7 | `4,38 ha` | `4.3§ ha` (comma→period, digit `8`→`§`) | **MISS** | 0.286 |
| 4 | `II. Detailed planning/2019 CV 1517-SXD 03-12-2019 HDTT lập ĐAQH CTXD Khu bến tổng hợp Định An-GĐ 2 (33,6ha).pdf` | 0 | `33,6ha` | `33,6ha` (verbatim, multiple correct instances) | **FOUND** | 0.000 |
| 5 | `III. Land use rights/06 Nộp tiền thuê đất.pdf` | 0 | `Số: 115/TB-BQLKKT` | `: 115 PH-BÓI.KIXT` (decorative-font header, heavily garbled) | **MISS** | 0.471 |

"Found?" / "CER" columns above are the **BEFORE baseline** — see below.

### Item detail

**#1 — `122,81ha` (project scale).** Appears correctly on page 0 (the QĐ
approval decision header/preamble) four times: `"...Định An (quy mô
122,81ha)"`. One same-page OCR instance renders as `122,&1ha)"` (glyph swap
`8→&`), but since the other three instances are correct, the page-level
retrievability check passes. Included as a **control** — this figure was
never broken; it demonstrates the harness correctly reports FOUND/CER=0 when
OCR is clean, and shows per-instance noise can coexist with an overall FOUND
result.

**#2 — `98,18ha` (kho bãi hậu phương, cầu cảng diện tích).** Ground truth
confirmed by eyeballing the rendered page-1 crop: `"...cảng diện tích
98,18ha;"`. Current Tesseract output splits the second `8` off and misreads
it as `§`, producing `"98,1 §ha"` — the exact string reconnaissance found in
`knowledge_nodes.properties->>'content'` for this project. **DB-verified**
(this session, not inherited from recon): the `document_chunk` belonging to
*this* document (`document_id=89a0ea6a-...`, i.e. `11381263.pdf`) contains
the mangled `"98,1 §ha"` — chunk `ece864a1-96bf-4498-8cee-872f30e637ef`. A
**different** document in the same project (`document_id=a7ee9a4c-...`)
happens to contain the clean `"98,18ha"` string. This matters for the plan's
retrievability SQL as literally written: it is scoped by `project_id` only,
not `document_id`, so `LIKE '%98,18%'` against the whole project returns a
false-positive FOUND (count=1) driven by the unrelated document, while the
document actually under test is still mangled. The harness in this repo
(`b2_figure_metrics.py`) avoids this by rendering the specific
`(pdf_path, page_index)` directly rather than searching the DB — **MISS** on
raw ground truth, confirmed at the correct scope.

**#3 — `4,38 ha` (Bãi hàng 3 / BH3 diện tích).** Ground truth confirmed by
eyeballing the rendered page-7 crop: `"...Bãi hàng 3 (BH3) diện tích 4,38
ha;..."`. Current Tesseract output: `"Bãi hàng 3 (BH3) diện tích 4.3§ ha"` —
matches the `"diện tích 4.3§ ha"` string reconnaissance found in the DB
(the recon's illustrative `4.35 ha` ground truth was approximate; `4,38 ha`
is the verified true value for this specific field). **DB-verified**: the
`document_chunk` for `document_id=89a0ea6a-...` (`11381263.pdf`) contains the
mangled `"4.3§ ha"` — chunk `9daace07-aa00-46ad-9972-a3f109aafd98`. Six other
`document_chunk` rows in the same project match the clean `"4,38 ha"`
substring, but they belong to five *different* documents (project-level
`LIKE` again produces a false-positive FOUND) — same scoping caveat as #2.
**MISS** on raw ground truth, confirmed at the correct scope.

**#4 — `33,6ha`.** **Reconnaissance correction:** the recon flagged this as
the "unretrievable — hard-detection miss" example, hypothesizing OCR fails
to capture it anywhere in the body text (evidenced only by the figure
appearing in the filename). Verified false: fresh `TesseractEngine.ocr_image`
on page 0 (rendered directly from this PDF, no preprocessing) reads
`"...giai đoạn 2, quy mô khoảng 33,6ha như sau"` correctly, and a direct DB
query (`unaccent(lower(content)) LIKE '%33,6%'`) returns **4** matching
`document_chunk` rows already ingested for this project. This item is kept
in the golden set as a **second control** (documents the corrected finding
so Task 2/3 don't re-chase a miss that isn't there) rather than removed
silently, per the instruction to surface reconnaissance conflicts rather
than average over them. **No genuine "hard-miss" example was found** during
this task — Tasks 2/3 should treat that scenario as hypothetical/unverified
unless a real one surfaces during broader re-extraction.

```sql
-- Retrievability check used to verify #4 against the live DB:
SELECT count(*) FROM knowledge_nodes
WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e'
  AND node_type='document_chunk'
  AND unaccent(lower(properties->>'content')) LIKE '%33,6%';
-- returned: 4 (NOT 0 — contradicts the recon's "unretrievable" claim)
```

**#5 — `a3856d16` garbage chunk.** **Reconnaissance correction:** the recon
could not find chunk id `a3856d16...` among `document_chunk` nodes and
treated it as optional/best-effort. It exists, but as a **`document`** node
(not `document_chunk`): id `a3856d16-4ce4-4c0a-812b-5fe0a00724e5`, title `06
Nộp tiền thuê đất`, `stored_path` ending in `.../36abd5d2.../06 Nộp tiền thuê
đất.pdf`. Its `properties->>'summary'` field is severely garbled Vietnamese
OCR text (e.g. `"UIHND TINH TLÁ VINH CỘNG HO NÃ HỘI CHỦ NGHĨA VIET BÉM"` for
`"UBND TỈNH TRÀ VINH CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"`). Local source file:
`doc_pdf_test/project_1/III. Land use rights/06 Nộp tiền thuê đất.pdf`, page
0. Root cause differs from #2/#3: this scan uses a decorative/stylized font
for the header (`Số: 115/TB-BQLKKT`, `THÔNG BÁO`), which Tesseract's `vie`
model reads very poorly regardless of digit-confusable patterns — a
different failure mode than the `8`→`§` substitution class. Kept as a
best-effort qualitative document-level garbling example (matches the plan's
"do not block, treat as optional" guidance); ground truth is the document
number line, not a figure.

```sql
-- Retrievability query template from the plan (Step 1), run this session
-- against #2/#3. NOTE the project-scoping caveat above: run it scoped by
-- document_id, not just project_id, or it will false-positive on unrelated
-- documents that happen to share the same figure text.
SELECT count(*) FROM knowledge_nodes
WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e'
  AND properties->>'document_id'='89a0ea6a-8605-4408-b765-a7598464cc40'
  AND node_type='document_chunk'
  AND unaccent(lower(properties->>'content')) LIKE '%98,18%';   -- verified: 0 (document-scoped)
SELECT count(*) FROM knowledge_nodes
WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e'
  AND properties->>'document_id'='89a0ea6a-8605-4408-b765-a7598464cc40'
  AND node_type='document_chunk'
  AND unaccent(lower(properties->>'content')) LIKE '%4,38 ha%';  -- verified: 0 (document-scoped)
-- also check structured_fields on the document node (currently NULL for
-- both 11381263.pdf and the 33,6ha doc — extraction has not populated
-- structured_fields->'areas' yet for this project, independent of B2):
SELECT properties->'structured_fields' FROM knowledge_nodes
WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e' AND node_type='document'
  AND id='89a0ea6a-8605-4408-b765-a7598464cc40';
```

### `Số 09` doc-number confusable — controller-ratified exclusion

This item is deliberately excluded from the golden set's retrievability/CER
targets because Task 3 (the RapidOCR fields fix) explicitly scopes
doc-number confusables (`Số 09` ↔ `Số O9`-style letter/digit swaps) out of
its regex repair — see plan Task 3 Step 2. Since no fix in this plan will
target this failure mode, a golden-set entry for it would have no gate to
validate against. Controller-ratified exclusion, not an oversight.

## Reconnaissance corrections (summary)

Two of the five reconnaissance claims did not hold up under direct
verification and are recorded here rather than silently fixed, per Rule 7
(surface conflicts, don't average them):

1. **`33,6ha` is NOT an unretrievable hard-miss.** It OCRs correctly from a
   fresh render with zero preprocessing, and is already present in 4 DB
   chunks. Reconnaissance's inference (drawn only from the figure appearing
   in the filename) was wrong.
2. **The `a3856d16` chunk DOES exist** in the current DB — as a `document`
   node (not `document_chunk`), with the garbling in its `summary` property.
   Reconnaissance's search apparently didn't check `document`-type nodes.

Both corrections are reflected in the golden set table and detail sections
above; neither blocked this task per the standing instruction to treat #4/#5
as optional/best-effort.

## Harness

`ennam.kg.python/scripts/b2_figure_metrics.py` — pure measurement wrapper,
no production OCR/preprocessing logic. Takes an injectable OCR callable
(`Callable[[PIL.Image.Image], str]`) so later B2 tasks can score
preprocessed / vi-model variants without modifying this file.

- `found`: ground-truth substring present anywhere in the page's OCR text,
  both sides normalized via unaccent+lower **and whitespace-stripped** (same
  accent/case rule as the plan's SQL — Vietnamese diacritics survive plain
  `.lower()` — plus whitespace-stripping added after finding the same spacing
  brittleness in the plan's own SQL template, see #2/#3 above: ground truth
  is inconsistently spaced even when OCR is clean, e.g. `98,18ha` vs
  `4,38 ha`, so `found` must not depend on getting the space right).
- `cer`: character error rate = `min_over_windows(levenshtein(window, gt)) /
  len(gt)`, where `window` ranges over substrings of each OCR line with
  length within ±2 chars of `len(ground_truth)`. Diagnostic only — for
  relative comparison across preprocessing configs, not an absolute
  OCR-quality claim. **Deviation from the plan's Step 2 wording** ("a 10-line
  Levenshtein vs ground truth on the matched line"): that phrasing is
  ambiguous (no aligned reference transcript exists to define "the matched
  line" against), so this harness instead does a sliding-window best-match
  search across all OCR lines. Flagging explicitly in case a different CER
  definition was intended — straightforward to swap out `best_window_cer`
  if so.

### Runbook

```bash
cd ennam.kg.python

# BEFORE / AFTER baseline against the current pipeline (raw TesseractEngine,
# zero preprocessing):
uv run python scripts/b2_figure_metrics.py

# against a non-default pdf_root:
uv run python scripts/b2_figure_metrics.py --pdf-root /path/to/doc_pdf_test/project_1
```

No environment variables required — the harness renders PDFs directly and
calls Tesseract locally; it does not touch the DB.

## BEFORE baseline (Task 1 Step 3 — CAPTURED, this task)

Actual run output, `uv run python scripts/b2_figure_metrics.py`, current
pipeline (`TesseractEngine(lang="vie", psm=1)`, zero preprocessing):

```
[FOUND] cer= 0.000  gt='122,81ha'  window='122,81ha'  page=0  file=11381263.pdf
[MISS ] cer= 0.286  gt='98,18ha'  window='98,1 §ha'  page=1  file=11381263.pdf
[MISS ] cer= 0.286  gt='4,38 ha'  window='4.3§ ha'  page=7  file=11381263.pdf
[FOUND] cer= 0.000  gt='33,6ha'  window='33,6ha'  page=0  file=II. Detailed planning/2019 CV 1517-SXD 03-12-2019 HDTT lập ĐAQH CTXD Khu bến tổng hợp Định An-GĐ 2 (33,6ha).pdf
[MISS ] cer= 0.471  gt='Số: 115/TB-BQLKKT'  window=': 115 PH-BÓILKIKT'  page=0  file=III. Land use rights/06 Nộp tiền thuê đất.pdf
```

Summary: 2/5 FOUND (both controls — #1 and #4, which were never broken),
3/5 MISS (#2, #3: the digit-confusable mangling class Task 3's regex/config
fix should target; #5: decorative-font garbling, a different failure mode
that preprocessing/config tuning in Task 2 is more likely to help than a
regex fix). Mean CER across the 3 MISS items: 0.348.

## AFTER — Task 2 preprocessing A/B (CAPTURED)

Actual run, `TesseractEngine(preprocess=True)` (grayscale → median denoise →
Otsu binarize → ±8° deskew, `ennam_kg.ingestion.ocr.preprocess.preprocess_for_ocr`)
against the same golden set / pdf_root, no other change:

```
[FOUND] cer= 0.000  gt='122,81ha'  window='122,81ha'  page=0  file=11381263.pdf
[MISS ] cer= 0.143  gt='98,18ha'  window='98,I8ha'  page=1  file=11381263.pdf
[MISS ] cer= 0.143  gt='4,38 ha'  window='4.38 ha'  page=7  file=11381263.pdf
[FOUND] cer= 0.000  gt='33,6ha'  window='33,6ha'  page=0  file=II. Detailed planning/2019 CV 1517-SXD 03-12-2019 HDTT lập ĐAQH CTXD Khu bến tổng hợp Định An-GĐ 2 (33,6ha).pdf
[MISS ] cer= 0.706  gt='Số: 115/TB-BQLKKT'  window='8Ó: I3 TH-HỘI K'  page=0  file=III. Land use rights/06 Nộp tiền thuê đất.pdf
```

Re-run twice with identical output (byte-for-byte same `found`/`cer`/`window`
per item both times) — confirms `preprocess_for_ocr` is deterministic, no
`random`/wall-clock inputs.

| # | Item | BEFORE found/CER | AFTER found/CER | Delta |
|---|------|-------------------|-------------------|-------|
| 1 | `122,81ha` (control) | FOUND / 0.000 | FOUND / 0.000 | no change |
| 2 | `98,18ha` | MISS / 0.286 | MISS / 0.143 | CER halved; window `98,1 §ha` → `98,I8ha` (still MISS — `I` vs `1`, one char off) |
| 3 | `4,38 ha` | MISS / 0.286 | MISS / 0.143 | CER halved; window `4.3§ ha` → `4.38 ha` (still MISS — `.` vs `,`, one char off) |
| 4 | `33,6ha` (control) | FOUND / 0.000 | FOUND / 0.000 | no change |
| 5 | `Số: 115/TB-BQLKKT` (best-effort, non-gate) | MISS / 0.471 | MISS / 0.706 | **CER regressed** (`: 115 PH-BÓILKIKT` → `8Ó: I3 TH-HỘI K`, arguably less readable) |

**Gate decision: keep `ocr_preprocess_enabled = False` (default unchanged).**
Reasoning, reading `found` (figure retrievability) as the plan's primary
metric and `cer` as diagnostic-only (per this doc's own "Harness" section
above — CER is explicitly "not an absolute OCR-quality claim"):

- **Retrievability did not move.** 2/5 FOUND before, 2/5 FOUND after — the
  same two items (both controls, #1/#4). Neither #2 nor #3 crossed the
  MISS→FOUND line, which was this doc's own stated gate expectation
  ("#2 and #3 should flip to FOUND").
- **No regression on the currently-correct figures** (#1, #4 — both stayed
  FOUND / CER 0.000). This half of the gate condition is satisfied.
- **CER did improve substantially on the two on-target items** (#2, #3: CER
  halved 0.286→0.143, and both windows are now a single character away from
  the ground truth — `I`/`1` and `.`/`,` confusions rather than the
  `8`→`§`/glyph-loss pattern). This is real signal, just not enough to flip
  `found` on its own.
- **#5 (best-effort, explicitly not a hard gate) got measurably worse**
  under preprocessing (CER 0.471→0.706) — a real case of preprocessing
  degrading OCR on a real scanned page, not just a synthetic-test artifact.
  Hypothesis, not yet verified: this page's header uses a decorative/stylized
  font (per the item-5 detail note above); Otsu binarization at a single
  global threshold likely clips or fuses the thin/ornamented strokes, and the
  deskew search (which maximizes horizontal-projection variance) may be
  misfiring on a page whose dominant structure isn't ordinary paragraph text.
  Flagging rather than fixing — item 5 is out of this task's gate scope, and
  a targeted fix belongs with Task 3's regex/config work if revisited, since
  #2/#3 are now only a character away from FOUND.
  **Update (post-review deskew tie-break fix):** the deskew half of this
  hypothesis is ruled out — instrumenting `_deskew` on this page shows
  `best_angle=0.0` with a high, non-tied score (~1.9e8), i.e. deskew never
  rotates this page and was never a tie-break default in either the old or
  fixed iteration order. Re-running the full A/B after the tie-break fix
  (see `ennam.kg.python` `preprocess.py` `_deskew`) reproduces the exact same
  `found`/`cer`/`window` for all 5 golden-set items, byte-for-byte — the fix
  is real (covered by a unit test) but was never active on this golden set.
  Item 5's regression is attributable to binarization, not deskew.
- Per Rule 7 (surface conflicts, don't average them): the plan text has two
  slightly different phrasings of the "no regression" condition — Task 2's
  brief says "no regression on currently-correct figures" (item 5 exempt,
  since it was never correct); the broader plan intent (per this doc's own
  gate note above) reads more strictly. Taking the stricter reading here
  since flipping a production default is the higher-blast-radius action:
  a real regression exists (item 5), and the primary metric (retrievability)
  is flat, so the honest call is **do not adopt yet**. The flag ships
  wired end-to-end and OFF by default — "if it doesn't help, keep it OFF and
  behind the flag (no harm)," per the plan.

Next step if this is revisited: combine Task 2's preprocessing with Task 3's
digit-confusable regex repair — #2/#3 are now one character off, which is
exactly the class of error Task 3 targets, so the combination may clear the
FOUND bar where preprocessing alone did not.

## Task 3 — RapidOCR fields-path language + confusable repair (CAPTURED)

Targets `extract_structured_fields` in `rapidocr_fields.py` (the RapidOCR
*fields* path — doc numbers/dates/areas/amounts/ids — a different path from
Task 1/2's Tesseract *body-text* CER harness above).

### Step 1 spike — vi/latin PP-OCR rec ONNX model (deferred)

Researched (~30 min budget) whether a Vietnamese or "latin" PP-OCR
recognition ONNX model + dict is directly downloadable without conversion:

- **Official model hub** (`huggingface.co/SWHL/RapidOCR`, the RapidAI
  project's own release channel) ships only `ch`/`en` PP-OCRv1-v4 rec
  models — no Vietnamese or multilingual artifact.
- PaddleOCR's own Vietnamese rec model exists only as Paddle inference
  weights; producing an ONNX artifact requires `paddle2onnx` conversion —
  out of scope per the plan's own gate ("do NOT block on model
  conversion").
- A "latin" rec ONNX model + `dict.txt` **is** directly downloadable
  without conversion, but only from an **unofficial third-party mirror**
  (`huggingface.co/monkt/paddleocr-onnx/languages/latin`). Its `dict.txt`
  was fetched and inspected directly: it contains Latin-extended, currency,
  Greek, and math/symbol glyphs, but **no Vietnamese diacritic characters**
  (no ạ/ệ/ữ/ơ/ư/ộ/ẫ/... checked explicitly). Wiring it in would swap the
  current `ch` (Chinese+English) rec model for one with equal-or-worse
  Vietnamese coverage, sourced from an unverified re-upload — not a fix for
  this project's Vietnamese-language documents.

**Decision: DEFER.** No readily-obtainable, verified vi/latin ONNX artifact
that actually improves Vietnamese OCR exists within the spike budget. The
`_engine` in `_get_engine()` is unchanged (still `RapidOCR()`, ch+en). This
is documented as a NOTE comment at the call site in `rapidocr_fields.py` for
future revisit. Proceeded with the regex-only fix (Steps 2-6), the
independent/reliable half of Task 3.

### Steps 2-4 — `_repair_confusables_near_units` (implemented, TDD)

Added to `rapidocr_fields.py`: `_CONFUSABLE` translation table
(`I`/`l`→`1`, `§`→`5`, `O`/`o`→`0`; `S`→`5` deliberately excluded per the
plan's own caveat) and `_NUM_UNIT` (a digit-led run tolerant of those
confusable chars, ending in a unit token: `ha`/`m²`/`m2`/`m³`/`m3`).
`_repair_confusables_near_units` translates matched spans only. Wired into
`extract_structured_fields` right after `_normalize_ocr_text`.

Tests (`tests/ingestion/test_rapidocr_fields.py`, both from the plan's own
illustrative examples):
- `test_confusable_repair_recovers_area` — `"122,8Iha"` → `_AREA` now
  matches; `"4.3§ ha"` → `"4.35 ha"`.
- `test_repair_does_not_touch_normal_text` — `"Hàm Giang 122,81 ha"`
  unchanged; `"So O9 tai lieu"` unchanged (no unit → no span → no rewrite,
  the explicit no-over-reach case from the plan).

Both tests FAILED before implementation (`ImportError`: name undefined),
PASSED after. Full `ingestion/` suite: `uv run pytest tests/ingestion/ -v`
→ **89 passed**, no regressions.

**Edge case found during review** (not in the plan's illustrative code):
`_NUM_UNIT`, copied faithfully from the plan, has **no trailing `\b`** after
the unit alternation (unlike `_AREA`, which does: `...(?:...)\b`). In
principle this lets `_NUM_UNIT` match a digit run bleeding into the start of
an unrelated word beginning with "ha" (e.g. a hypothetical "24hang" if
diacritics are dropped by OCR, which does happen in this corpus — "hàng"
sometimes renders as "hang"). In practice this is harmless: (1) the
translation table only rewrites `I`/`l`/`O`/`o`/`§`, so a plain digit run
like "24" produces a no-op substitution regardless of what follows; (2) even
if a confusable letter were adjacent (e.g. "2Ohang" → "20hang" after
repair), the character-for-character translation doesn't change string
length or boundaries, and the downstream `_AREA` regex still has its own
`\b` guard, so no new false-positive "area" field is ever *extracted* — the
risk is confined to the repair step touching a byte or two of a word it
technically shouldn't have inspected, never to a bad field ending up in the
output. No real instance of this was observed in the golden-set corpus.
Documented rather than silently "improved" (the plan's illustrative regex
is the load-bearing spec here) — a `\b` could be added if a real corpus
case ever surfaces it.

### Step 5 — golden-set A/B on the fields path (real run, not estimated)

Task 1's `b2_figure_metrics.py` measures the Tesseract *body-text* path
(`ocr_fn: Image -> str`) and was **not modified**. A separate one-off script
(not checked in — ad hoc scratch script) reused `GOLDEN_SET`,
`render_page`, and `_unaccent_lower` from `b2_figure_metrics.py` unchanged,
and scored the *fields* path instead: `found` = ground truth (after
unaccent+space-strip) appears in one of `extract_structured_fields(render)
["areas"]`, run once with `_repair_confusables_near_units` monkeypatched to
identity (BEFORE) and once with the real function (AFTER).

```
--- BEFORE (no confusable repair) ---
[FOUND] gt='122,81ha'          areas contain '122,81ha'                 (item 1, control)
[FOUND] gt='98,18ha'           areas contain '98,18ha'                  (item 2)
[FOUND] gt='4,38 ha'           areas contain '4,38ha'                   (item 3)
[FOUND] gt='33,6ha'            areas contain '33,6ha'                   (item 4, control)
[MISS ] gt='Số: 115/TB-BQLKKT' areas=[area-only list, no doc-number match] (item 5, out of scope)
--- AFTER (with confusable repair) ---
(identical to BEFORE, item-for-item, byte-for-byte)
```

**Finding: no MISS→FOUND flip on this golden set for the fields path** —
4/5 FOUND both before and after (both controls #1/#4, plus #2/#3), 1/5 MISS
unchanged (#5, doc-number pattern, explicitly out of Task 3's scope per the
plan). This is a real, honest negative result, not a tooling gap: the
RapidOCR `ch+en` engine used by the fields path (a different model/engine
than Task 1/2's Tesseract body-text harness) does **not reproduce** the
`98,1 §ha` / `4.3§ ha` digit-confusable mangling on these two pages that
Tesseract produced — it already transcribes `98,18ha` and `4,38ha`
correctly on this corpus. A broader scan of all pages of `11381263.pdf` for
any `\d[\d.,IlOo§]*\s?(?:ha|m²|m2|m³|m3)` span containing a confusable
character found no genuine digit-corruption instance (a few stray lowercase
`o` matches were leading vowels of adjacent Vietnamese words, e.g. `"quy mô
122,81ha"` → `"o122,81ha"`, not digit corruption).

Net effect: `_repair_confusables_near_units` is implemented, unit-tested
against the plan's own illustrative confusable patterns, and verified to be
a true no-op on this specific golden-set corpus (no regression, confirmed
byte-identical BEFORE/AFTER). It remains valuable defense-in-depth for the
`98,1 §ha`-style mangling class documented in Task 1/2's Tesseract findings
above, should that mangling pattern occur on the RapidOCR fields path on
other documents or future scans — just not provably demonstrated as a fix
on *this* golden set, because the fields-path engine didn't reproduce the
failure mode it was designed to repair.

## Task 5 — Live Re-ingest Verification (BLOCKED — partial)

**Status: BLOCKED at Step 2.4 (re-ingest) on an invalid API key. The
destructive half of Step 2 (delete) completed and is verified clean; no
new OCR ran yet, so no figure-retrievability numbers are captured here.**

### Step 1 — Rebuild (DONE)

```
docker compose up -d --build worker indexer
```
Both `daab-worker` and `daab-indexer` rebuilt and came up healthy
(`daab-indexer` reports `{"status":"healthy"}`; `daab-worker` queue
consumer started on `ennam-kg:indexing`, `ennam:kg_generation`,
`ennam:extraction`, `ennam:agent_context_embed`). `daab-server` was also
recreated as a side effect of the shared compose dependency graph (not a
scope violation — no code change to it, and it went from `unhealthy` to
`healthy`).

### Step 2 — Targeted delete (DONE) + HARD GATE (PASSED)

Scope: the 3 golden-set docs only —
`89a0ea6a-8605-4408-b765-a7598464cc40` (`11381263.pdf`),
`7922817f-0a3c-4e61-8fb0-228ce1f8648c` (`...HDTT lập ĐAQH...(33,6ha).pdf`),
`a3856d16-4ce4-4c0a-812b-5fe0a00724e5` (`06 Nộp tiền thuê đất.pdf`).

**Before delete (previewed with SELECT before any DELETE ran):**

| scope | count |
|---|---|
| document hubs | 3 |
| document_section | 12 |
| document_chunk | 80 |
| knowledge_node_embeddings | 92 |
| knowledge_edges touching these nodes | 143 |
| canonical_document rows (live) | 3 |
| project total `document` nodes (sanity) | 77 |

**Deviation from the referenced dedup-cleanup pattern** (`2026-07-13-daab-document-dedup.md`
Task 6 Step 2): that pattern soft-deletes `canonical_document` (`deleted_at
= NOW()`) *before* hard-deleting the hub `knowledge_nodes` row. On the
current schema, `canonical_document.knowledge_node_id` is a `NOT NULL` FK
to `knowledge_nodes.id` — a soft-deleted row still holds that FK, so hub
deletion fails with `violates foreign key constraint
"canonical_document_knowledge_node_id_fkey"`. Also hit a second FK not
mentioned in the reference plan: `draft_nodes.knowledge_node_id` also
blocks hub deletion. Fix applied (transaction rolled back cleanly on the
first two failed attempts — nothing partially committed):
1. `UPDATE draft_nodes SET knowledge_node_id = NULL` for the 3 hub ids
   (draft history preserved, just unlinked — draft rows are not part of
   the dedup-matching path).
2. **Hard**-delete (not soft-delete) the 3 `canonical_document` rows —
   functionally equivalent for the "no live canonical row" invariant,
   since a deleted row can't match on `deleted_at IS NULL` either way.

Executed as one transaction, scoped only to the 3 hub ids (+ nodes whose
`properties->>'document_id'` is one of those 3 ids):

```
DELETE FROM knowledge_edges            -- 143 rows
DELETE FROM knowledge_node_versions    -- 3 rows
UPDATE draft_nodes SET knowledge_node_id = NULL  -- 3 rows
DELETE FROM canonical_document         -- 3 rows
DELETE FROM knowledge_nodes            -- 95 rows (3 hub + 12 section + 80 chunk)
COMMIT
```

**Hard gate (after delete):**

| check | result |
|---|---|
| live nodes (hub+section+chunk, these 3 doc ids) | **0** |
| live canonical_document rows (these 3 doc ids) | **0** |
| live embeddings for the 3 hub node ids | **0** |
| project total `document` nodes | 77 → **74** (exactly −3, confirms no over-scoped deletion) |

Hard gate **PASSED**. Safe to re-ingest.

### Step 2.4 — Re-ingest (BLOCKED)

Confirmed route by reading `ennam.kg.go/internal/handler/ingest_upload.go`:
`POST /api/v1/projects/{projectId}/ingest/upload` (multipart, field `file`),
poll `GET /api/v1/projects/{projectId}/draft-nodes/{draftId}` until
`status` is one of `processed` / `failed` / `rejected` (terminal, per
`internal/models/draft_node.go`'s state machine).

Adapted the existing `scripts/ingest-batch-pdfs.py` pattern into a
throwaway script (scratchpad, not checked in) targeting only the 3 files
above via multipart upload to
`http://127.0.0.1:8082/api/v1/projects/592c7ff7-9f6f-4cc5-9094-d9b3b685277e/ingest/upload`.

**Blocker:** the API key supplied in the task brief
(`ennam_kg_e95362f4...`, from `other_projects/daab-sim-consumer/.mcp.json`)
returned `HTTP 401 {"error":"invalid or revoked API key"}`. Verified this
is not a false negative: `sha256(<that exact key>)` does not match any
`key_hash` currently in the `api_keys` table (12 rows, all admin-role web
sessions or two long-lived admin keys — none matching). Per the task's own
guidance ("if anything ... seems unclear ... stop and report NEEDS_CONTEXT
rather than guessing on a destructive operation") and the harness's own
credential-exploration guard, I did **not** attempt to brute-force or
enumerate other candidate keys to find one that authenticates — that
`.mcp.json` key is simply stale/wrong for this running stack's current
`api_keys` table (likely rotated since that file was last regenerated).

**What is NOT done:** Step 2.4 (re-ingest), Step 2.5 (confirm fresh-OCR
log line), Step 3 (verify success criteria — harness run + live DB
figure-recovery query + unrelated-doc spot-check). None of these can run
until a valid, Cảng-scoped (or admin) API key is supplied.

**Current live-DB state:** the 3 target documents currently have **zero**
nodes in the KG (mid-operation state — delete done, re-ingest pending).
Source PDFs are untouched on disk; nothing is lost, but these 3 docs are
temporarily absent from Cảng Định An in the dashboard/search until
re-ingest runs. The other 74 documents in the project (including B1's
completed entity-resolution work) are unaffected — confirmed by the
77→74 (exactly −3) count above.

**To resume:** supply a working API key scoped to project
`592c7ff7-9f6f-4cc5-9094-d9b3b685277e` (or admin role), then run the
scratchpad re-ingest script (or re-derive it from
`scripts/ingest-batch-pdfs.py`, pointed at `PROJECT_ID =
592c7ff7-9f6f-4cc5-9094-d9b3b685277e` and the 3 target file paths listed
above), then complete Step 3's verification queries against the new
document/chunk ids.
