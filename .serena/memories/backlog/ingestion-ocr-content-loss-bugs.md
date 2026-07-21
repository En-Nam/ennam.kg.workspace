# RESOLVED 2026-07-16 — Ingestion pipeline silently destroyed document text (Bug A + Bug B)

**STATUS: FIXED + VERIFIED on the real corpus.** Kept for the root-cause record; do NOT re-investigate.
Plan: `docs/superpowers/plans/2026-07-16-ocr-extraction-content-loss-fix.md` · Checkpoint: `mem:checkpoint/ocr-content-loss-fix-2026-07-16`

## Results (measured before → after)
| Metric | Before | After |
|---|---|---|
| Dasin diacritic health | 8/40 = **20%** | 130/147 = **88%** (manual corpora ref: 93–97%) |
| BCTC KIEM TOAN 2024 | 2 chunks / **2,208 chars** | 19 / **19,023** (extractor yields 19,038 → ~100% retention) |
| BCTC 2023 / 2025 | 4/3,933 · 4/4,496 | 37/**40,693** · 40/**42,498** |
| Chunks (project) | 40 | **147** (3.7×) |
| concepts / mentions | 28 / 56 | **41 / 82** |

Commits (`ennam.kg.python`): `5918f62` (Bug B), `456837e` (Bug A), `98c86bd` (regression tests), `f8df24e` (ruff format).
Verification: regression on the 9 real PDFs **4/4 PASSED**; full suite **701 passed**; ruff clean on all 5 touched files.

## Bug B — content before the first heading was dropped (the big one)
`ingestion/pipeline/document_tree.py::parse_markdown_sections` looped from `headers[0]`; only the `if not headers:` branch kept full text. **Trigger was B2's own fix**: `_build_recovered_fields_section` appends `## Recovered Figures`; OCR'd scans have no headings of their own, so that became the ONLY heading → entire body dropped, silently.
**Fix:** emit a leading `MarkdownSection(title="Document", level=1)` for pre-heading content. B2's append left untouched (fixed at the right layer).

## Bug A — probe trusted a garbage text layer, skipped OCR
`ingestion/ocr/pdf_render.py` used char-count only (`>= 50` → trust); the **image-coverage half the design specified was never implemented**. Scans carrying a source-side Latin-OCR text layer (1.5k–7.5k chars/page, 0 diacritics) bypassed OCR.
**Fix:** `_looks_like_mangled_vi()` (≥100 letters AND diacritic ratio <0.01) + `_page_has_image()` → force OCR, logged at WARNING (no longer silent).

## Key lesson (worth keeping)
It was **NOT a doc-sync bug** — proven by `Dasin 3` (doc-sync) vs `Dasin 4` (direct upload) holding **byte-identical** results. The shared extraction path was at fault. Tesseract was healthy all along (248 runs, `-l vie`, 0 render failures, no OOM). The extractor was healthy too (`extract_file_text(BCTC)` = 19,038 good chars); the loss happened downstream in sectioning.

## Still open (NOT part of this fix)
- ~~**`concept`-type entity gap**~~ — **FIXED 2026-07-16**, see `mem:checkpoint/concept-dedup-fix-2026-07-16` (plan: `docs/superpowers/plans/2026-07-16-concept-dedup-fix.md`, commit `06df209`). `decompose.py` now prefetches the project's existing `concept` nodes and reuses them via a `fold_name`-based key (+ a small VN legal-form abbreviation map) instead of creating one node per mention. Measured on Dasin (re-ingested, 9 docs): concepts 41→26, 0 exact-duplicate titles, and the cross-document bridge query (concepts shared by ≥2 documents) went from **0 rows → 11 concepts** — `CÔNG TY TRÁCH NHIỆM HỮU HẠN ĐẠI TÂN` alone bridges 8/9 documents. This is a lighter-weight fix than full `needs_review` LLM-confirmed resolution (which still doesn't cover `concept` type) — it only catches case/whitespace/legal-form-abbreviation variants via deterministic folding, not semantic near-duplicates. That residual gap is still the separate, open decision in `mem:backlog/ba033-slice2-readiness-path`.
- **Pre-existing test failure** (NOT a regression — fails identically at `86615c5`, before the fix): `tests/extraction/test_parser.py::test_drops_out_of_range_span_and_orphan_relation`. Also 16 pre-existing ruff F401s in `benchmark/runner.py`.
- 1 doc failed sync: `94af7d35-ffdf-4fb4-be58-7ea929df2aa5` — "no signed URL returned" (per-doc isolation worked; root cause untriaged).
- `.mcp.json` in daab-sim-consumer hardcodes an API key (repeatedly revoked) → move to env; same class as `mem:backlog/aaaa-daab-sync-token-settings-ui`.

## Re-ingest gotcha (cost us a no-op once)
Re-syncing an existing project **skips everything**: `aaaa_synced_document` dedups on `(document_id, content_hash)` and bytes don't change. Delete the project (cascades sync-state) to force a rebuild.
