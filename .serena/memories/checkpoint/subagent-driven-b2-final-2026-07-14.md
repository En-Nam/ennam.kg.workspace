# Checkpoint: subagent-driven-development (B2 OCR figure fidelity) — 2026-07-14

## What was done
- Implemented all 5 tasks of `docs/superpowers/plans/2026-07-14-daab-ocr-figure-fidelity.md` via superpowers:subagent-driven-development: fresh implementer per task, task review (spec+quality) after each, fix loops for every Important finding, 2 independent whole-branch final reviews per explicit user request.
- Task 1: golden-set harness (`ennam.kg.python/scripts/b2_figure_metrics.py`) + `docs/superpowers/plans/b2-golden-set.md`. 1 fix loop (per-line `is_found` scoping).
- Task 2: `preprocess_for_ocr` (Otsu binarize + deskew), flag `ocr_preprocess_enabled`. A/B'd against golden set: retrievability flat, regression on item #5 → flag **kept OFF**. 1 fix loop (deskew tie-break).
- Task 3: `_repair_confusables_near_units` in RapidOCR fields path. vi/latin model spike **deferred** (no viable ONNX without conversion, verified). A/B: byte-identical no-op on this corpus (RapidOCR never reproduces Tesseract's confusable mangling) — shipped anyway as defense-in-depth, reviewer-approved.
- Task 4: `recover_or_flag` fallback (Tesseract as "the other detector", `extract_fields_from_text` factored out of Task 3's function for reuse). 1 fix loop (unhandled Tesseract exception could crash the whole extraction).
- Task 5 (operational): rebuilt worker/indexer; deleted+re-ingested the 3 golden-set target docs (scoped, hard-gate verified, 77→74→77 round-trip). Blocked once on an invalid API key (harness flagged the subagent's `.env` exploration as a security risk; audited and confirmed no unauthorized live request succeeded — all attempts were 401; user supplied a valid key, verified live, re-ingest completed).
- Final review pass 1: 1 Important + 2 Low findings (fallback over-flagged `unrecovered` on born-digital PDFs + wasted a duplicate Tesseract pass; preprocess-flag divergence; docstring drift). All fixed, commit `edc378e`, 2 new regression tests.
- Final review pass 2 (independent, fresh context): **surfaced that the "resolved" claim was overstated** — see below.

## Files changed (ennam.kg.python nested repo, base 046499c → HEAD edc378e, 8 commits)
- `src/ennam_kg/ingestion/ocr/preprocess.py` (new), `tesseract_engine.py`, `rapidocr_fields.py`, `fallback.py` (new)
- `src/ennam_kg/ingestion/adapters/files.py`, `src/ennam_kg/config.py`
- `scripts/b2_figure_metrics.py` (new)
- `tests/ingestion/test_ocr_preprocess.py`, `test_rapidocr_fields.py` (new), `test_ocr_fallback.py` (new), `test_ocr.py`
- workspace-root: `docs/superpowers/plans/b2-golden-set.md` (new, all real numbers), multiple commits recording each task's A/B/verification results

## Current state — IMPORTANT CORRECTION
Code is correct, safe, in-scope, tested (0 Critical/Important outstanding), scope-clean (no LLM/vision, no chunk/embed/resolution/RAG code touched). **But the plan's core goal is NOT achieved on the retrieval-visible path**: post-re-ingest, `document_chunk.content` for the target doc STILL contains the mangled `98,1 §`/`4.3§` figures (verified via direct DB query: 0 chunks have the clean parsed form). The fix landed only in `draft_nodes.metadata.structured_fields.areas`, which nothing reads for search/query/RAG (1 write-only reference in the whole Go codebase, `draft_node.go:348`). Root cause: Task 3's confusable-repair is scoped only to the RapidOCR fields path, not the Tesseract body-text/chunking path; Task 2's preprocessing (which would fix chunk content) is OFF by an evidence-based decision. "33,6ha" retrievability is real but is an unbroken control figure — doesn't demonstrate recovery.
Backlog `mem:backlog/daab-retrieval-quality-gaps-postfix` item 5 corrected from RESOLVED to PARTIALLY RESOLVED with full honest breakdown.

## Next steps
User needs to decide between (or defer both):
(a) wire `structured_fields` into an actual retrieval/search path so the already-fixed values are reachable, or
(b) extend Task 3's confusable-repair (or revisit Task 2's preprocessing decision) to cover the Tesseract body-text/chunking path so `document_chunk.content` itself gets corrected.
Neither is implemented — this checkpoint exists so a future session doesn't re-discover this gap from scratch.

## Blockers / Risks
None blocking further work; the gap above is a scope/strategy decision, not a code defect.
