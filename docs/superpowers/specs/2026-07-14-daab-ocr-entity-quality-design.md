# DAAB OCR Quality → Entity-Variant Reduction — Design Spec

**Date:** 2026-07-14
**Status:** Draft (pending user review)
**Branch:** task/implement_docs_sync
**Related:** Gap #3/#5 in `mem:backlog/daab-retrieval-quality-gaps-postfix`; evidence `other_projects/daab-sim-consumer/findings-rerun-2.md`; BA-031 entity resolution.
**Provenance:** 2-round adversarial review (CTO ⇄ OCR/NLP consultant), then source-verified. The debate's "add a fuzzy candidate channel" was refined after verification — fuzzy alias merge already exists; the surgical fix is the shared normalizer (§6).

---

## 1. Problem

The retrieval *reading* layer is now strong (inline snippets, slim neighbors — shipped & live-verified). The remaining ceiling is the *relationship* layer, and source verification shows its root cause is **OCR quality**, which splits into two independent problems:

- **Problem E — Entity fragmentation (high value).** The investor "Công ty TNHH Xây dựng Hàm Giang" is split across **≥4 un-merged concept heads** because OCR produces name variants: `CÔNG TY TNHH NAY DỰNG HÀM GIANG` ("NAY"≠"XÂY" — a glyph error), `THNN`≠`TNHH`, lost diacritics `Ham`≠`Hàm`. This starves the shared-entity / related-documents / centrality signals that M&A due-diligence leans on.
- **Problem F — Figure fidelity (narrow).** Key numbers are OCR-lost: "33,6 ha" (a phase-2 area) is unretrievable anywhere → a real contradiction can't be confirmed; captured-but-mangled figures `122,8Iha`, `4.3§ ha`, `Số O9`.

**Key architectural insight (verified):** the two problems do **not** share a fix, and **only F requires touching OCR.** E's variants already exist as text nodes in the graph — merging them is a *resolution* operation (no re-OCR). F's "33,6 ha" was never captured — only re-reading pixels can recover it.

## 2. Current architecture (verified — build ON this, don't reinvent)

**Two-engine OCR** (both run per PDF page, rendered at 300 DPI by `pdf_render.py`; low-DPI ruled out):
- **Tesseract `vie`, psm 1** — main body text → chunks + embeddings. Fed the **raw** rendered image: **zero preprocessing** (`tesseract_engine.py:16`). ← Problem F root.
- **RapidOCR** (`rapidocr_fields.py:27` — default `RapidOCR()` = **ch+en model, no Vietnamese charset**) + regex → structured fields (doc no, date, `ha/m²` area, amount) → node metadata. ← wrong-language model for VN figures.

**Entity resolution** (BA-031), all normalization anchored on one function:
- **`_normalize()`** (`resolution/rules.py:50`) = `NFC + lower + strip separators + strip honorifics`. **NFC preserves diacritics; no ASCII/tone fold; no abbreviation canonicalization.** So `Ham`≠`Hàm`, `THNN`≠`TNHH` never collapse.
- **Candidate generation** is Python-side: `emit_hub_candidates_cli.py` groups nodes by `_normalize(name)` → "exact normalized name match" suggestions (Go `merge_suggestion.go` only *stores* them; comment at `merge_suggestion.go:174` confirms normalization lives in Python).
- **Fuzzy alias merge already exists:** `fuzzy_llm_adjudicate.run_fuzzy_llm_adjudication(degree_threshold=0.84)` runs after each `resolve_document`; pairs ≥ threshold → **LLM (Haiku) adjudication** → auto-apply or `needs_review`.
- **Embedding-sim path:** `resolution_sim_threshold=0.74`, top_k 10 → cross-encoder (`BAAI/bge-reranker-v2-m3`) → Haiku verify (`resolution_merge_confidence_threshold=0.75`).
- **Precision guardrails already present:** `name_class.py` genericness gate; `danger_guards.py` antonym / pre-post / digit-mismatch guards; a BA-031 benchmark with precision sampling (`fuzzy_sample_cli.py`, Wilson LCB).

**Corpus:** 77 scanned Vietnamese legal PDFs, ~8k nodes. Embeddings multilingual-e5-small 384-dim (local).

## 3. Scope

**In scope (resource-ranked; performance/resource is the explicit priority):**
- **#0 Measurement harness** — the gate for everything.
- **#1 Improve the shared `_normalize()`** (ASCII/tone-fold + abbrev-canon) + **re-run resolution over existing nodes**. Fixes E. Python-only, ~zero compute, no re-OCR.
- **#2 CPU preprocessing before Tesseract** (binarize/deskew/denoise). Fixes captured-but-mangled F, some hard F.
- **#4 Fix the RapidOCR fields-path language bug** (ch+en → vi/latin) + fuzzy-unit tolerance. Fixes F figures.
- **#3 Residual-figure fallback (CPU, mechanism-agnostic)** — for the hard-detection F residual after #2/#4: a second detector pass + `needs_review`. **Not LLM-vision** (see §5).

**Out of scope (rejected on resource grounds):**
- Full 77-doc re-ingest (re-pays the Haiku extraction bill a third time).
- `marker`/`omniparse`/GPU engines (PyTorch + multi-GB VRAM for 77 CPU docs).
- Wholesale Tesseract→PaddleOCR main-text engine swap (deferred; do only if the harness shows preprocessed-Tesseract still has a large CER gap).
- Any `resolution_sim_threshold` change (global or org-only) — false merges (unrelated parties collapsing) are worse for diligence than fragmentation. Recall comes from better normalization + the existing fuzzy channel, not a looser gate.
- **LLM-vision OCR** — noted as a future last-resort only; requires vision plumbing that does not exist (§5).

**Sequencing:** #0 first (gate). Then #1 (highest value/cost). Then #2 + #4 (cheap figure wins). #3 only if the harness proves figures still lost.

---

## 4. Intervention design

### #0 — Measurement harness (gate for all changes)
A tiny golden set (~25–40 hand-labeled items) built from the *known* failures:
- The exact bad figures with page + ground-truth: `33,6 ha`, `122,81 ha`, `4.35 ha`, `Số 09`.
- The Hàm-Giang variant cluster: all surface forms → one canonical entity.

Three single-number metrics:
1. **Entity-head count** for the Hàm-Giang investor (target **≥4 → 1**) — the primary ship gate for E.
2. **BA-031 precision** must not regress (run the existing benchmark pairs incl. the antonym/pre-post danger cases) + a small **over-merge audit** on resulting org clusters — the precision counter-gate.
3. **Figure retrievability** (boolean: is each target figure present anywhere in extracted text/metadata after a change) — the gate for F. **CER** on labeled crops is a **diagnostic only** (for choosing preprocessing configs), not a ship gate.

**No change in #1/#2/#4 ships without its harness cell green.**

### #1 — Improve `_normalize()` + re-run resolution (fixes E)
Extend the single shared `_normalize()` in `resolution/rules.py` (feeds exact-match candidate-gen, classify, danger guards simultaneously):
- **ASCII/tone fold**: add a fold variant (NFD → strip combining marks → ASCII) so `Hàm`→`ham`, `Hàm`≡`Ham`. (Keep the NFC form too where diacritic-sensitive callers need it — add a `fold=` option rather than changing the default blindly; the candidate-gen grouping uses the folded form.)
- **Abbreviation canonicalization**: a small deterministic map for Vietnamese company/legal tokens — `thnn`/`tnhh`→`tnhh`, `cty`/`c.ty`/`cong ty`→`công ty` (folded: `cong ty`), etc. Removes the `THNN`/`TNHH` edit *before* fuzzy so the residual distance stays small and the threshold stays tight (precision).
- After folding + canon, variants collapse: `Ham/Hàm`→exact match; `THNN/TNHH`→exact match; `NAY/XÂY` (glyph error, full-string Levenshtein = 1, ratio ≈ 0.97) → caught by the **existing** fuzzy degree path (0.84) + LLM adjudication once its inputs are folded/canon'd; the compound `THNN+NAY` case → canon removes the THNN edit, leaving the safe distance-1 residual.
- **Fuzzy stays additive & verifier-gated:** folded/fuzzy matches enter as *candidates* that DEFER to the existing cross-encoder + Haiku adjudication — they do **not** auto-merge. No threshold change. `name_class` generic-reject and `danger_guards` stay in force.
- **Re-run resolution over the existing corpus** (not per-new-doc only): run `emit_hub_candidates_cli` + `fuzzy_llm_adjudicate` against the current 8k nodes. Cost ≈ **5–10% of a full re-ingest** — Haiku adjudication on candidate pairs only; **no re-OCR, no re-embed, no re-extract**.

**Gate:** Hàm-Giang heads ≥4 → 1, BA-031 precision flat, over-merge audit clean.

### #2 — CPU preprocessing before Tesseract (fixes captured-but-mangled F)
Add an image-preprocessing step inside the Tesseract path (behind the existing `OCREngine` seam): grayscale → adaptive/Otsu binarize → deskew → light denoise; optional 1.5× upscale for small-font pages. CPU-only, ~tens of ms/page. Recovers `122,8Iha`-class errors and makes some faint regions detectable.
**Gate:** CER drop on labeled crops (diagnostic); figure-retrievability improves.
**Scope:** applies to **new** ingests immediately; for the existing corpus, **targeted re-OCR only** on the pages behind fragmented entities / low-yield fields — never a full 77-doc re-OCR.

### #4 — Fix RapidOCR fields-path language + unit tolerance (fixes F figures)
- **Model-language correction (a bug, not a swap):** point `rapidocr_fields.py` off the default ch+en `RapidOCR()` to the **vi/latin** model (ONNX runtime already installed — config/model-file change, CPU). Shipping VN figure extraction on a ch+en charset is a defect.
- **Fuzzy-unit tolerance** in the `_AREA`/amount regex: tolerate adjacent-to-unit confusables (`I/l→1`, `§/S→5`, `O→0`) and a stray char between number and `ha/m²/m³`, so `122,8Iha`→`122,8 ha`.
**Gate:** the labeled figures parse; no regression on currently-correct fields.

### #3 — Residual-figure fallback (CPU, mechanism-agnostic) — fixes hard-detection F residual
For figures the harness flags as **still missing after #2/#4** (hard-detection misses — a region no engine detected):
- **Default (CPU, zero new dep):** run the *other* detector on the flagged page — a full-page **RapidOCR (vi)** pass (its detector differs from Tesseract's; `rapidocr_onnxruntime` already installed). What Tesseract's detection missed, PP-OCR's may catch.
- **Then:** if still missing, flag the field to the existing **`needs_review`** mechanism (human fills). Zero compute.
- **LLM-vision is explicitly NOT built here.** It would require vision plumbing that does not exist today (§5) and is reserved as a future last-resort only if the harness later shows *many important* figures unrecoverable by CPU means.
**Gate:** "33,6 ha" retrievable **or** flagged `needs_review` (fail-loud, not silently dropped).

---

## 5. Why LLM-vision is deferred (not just cost)

Verified: the platform's AI abstraction is **text-only**. Python `AIRequest` carries `prompt: str` → Go `messages:[{content:<string>}]`; the Go Anthropic/OpenAI adapters have **no image/vision/media_type/base64 support** (grep = 0). The `/admin/settings/ai-providers` page configures text providers (`claude_max`/`anthropic_api`/`openai`) that Python routes through — but none of that plumbing accepts an image. So LLM-vision is **not a config add**; it needs either (a) extending the AI abstraction for image content-blocks (Python + Go, multi-service), or (b) a direct Python-side vision call bypassing the provider governance. Both are out of scope; #3 uses CPU means instead.

## 6. Correction to the review (verified against source)

The debate proposed "add a rapidfuzz token-set candidate channel." Source verification refined this:
1. **Fuzzy alias merge already exists** (`fuzzy_llm_adjudicate`, degree 0.84, LLM-gated) — no new channel needed; the fix is feeding it better-normalized inputs.
2. **Candidate normalization is one Python function** (`_normalize`, used by `emit_hub_candidates_cli`). Improving it is Python-only; no Go change.
3. **No new dependency** — the residual `NAY/XÂY` case is full-string Levenshtein = 1; Python stdlib `difflib.SequenceMatcher.ratio()` suffices where a fuzzy compare is needed (runs only on ANN-blocked candidate pairs, not hot-path). rapidfuzz is unnecessary.

## 7. Error handling & precision

- **Fail-loud on lost figures:** a figure that survives #2/#4/#3-detector must be flagged `needs_review`, never silently absent (AGENTS.md Rule 12).
- **Precision is the hard constraint for E:** every merge still passes `name_class` generic-reject, `danger_guards`, and Haiku adjudication; the BA-031 benchmark + over-merge audit gate the ship. Fragmentation-down must not buy false-merge-up.
- **No `sim_threshold` change** — recall comes from normalization + the existing fuzzy channel.

## 8. Success criteria

1. **Primary (E):** the Hàm-Giang investor collapses from ≥4 concept heads to **1**, restoring its shared-entity / related-documents / centrality signal — with **BA-031 precision flat** and a clean over-merge audit.
2. **F:** "33,6 ha" becomes **retrievable** (via #2/#4) or is explicitly **`needs_review`** (via #3) — never silently lost; mangled figures (`122,8Iha`→`122,81 ha`) parse correctly.
3. **Resource:** E is fixed by a resolution-only re-run (~5–10% of a full re-ingest); no full re-OCR, no engine swap, no new heavyweight dependency, no vision API.
4. **No regression:** existing correct fields and existing resolution precision (BA-031) unchanged.
