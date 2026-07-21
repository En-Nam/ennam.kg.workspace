# Checkpoint: subagent-driven (B2 Task 1) — 2026-07-14

## What was done
- Implemented Plan B2 Task 1: figure golden set + retrievability/CER measurement harness.
- Verified 5 golden-set items against actual rendered PDF pages (300 DPI crops, eyeballed digits) — not trusted from reconnaissance alone.
- Corrected two reconnaissance errors (documented in b2-golden-set.md, not silently fixed):
  1. "33,6ha" is NOT an unretrievable hard-miss — OCRs correctly with zero preprocessing, already in 4 DB chunks for this project.
  2. The `a3856d16` chunk DOES exist — as a `document`-type node (not `document_chunk`), garbling is in its `summary` property.
- Discovered and documented a scoping bug in the plan's own retrievability SQL template: it's scoped by `project_id` only, not `document_id`, so it produces false-positive FOUND when unrelated documents in the same project happen to contain the same figure substring (confirmed for #2 `98,18ha` and #3 `4,38 ha` — document-scoped counts are 0, project-scoped counts are 1 and 6 respectively, from other docs).
- Advisor caught a real bug before commit: `is_found` was whitespace-sensitive; fixed by stripping all whitespace in the normalization (ground truth is inconsistently spaced even in clean OCR — `98,18ha` vs `4,38 ha`). Re-ran to confirm the BEFORE baseline was unchanged by the fix (it was — the MISS items differ from ground truth by character substitution, not spacing).
- Captured a real BEFORE baseline via actual harness run against unmodified `TesseractEngine` (no preprocessing).

## Files changed
- Created (ennam.kg.python repo): `ennam.kg.python/scripts/b2_figure_metrics.py`
- Created (workspace-root repo): `docs/superpowers/plans/b2-golden-set.md`

## Current state
- Two commits made, one per repo (this is a nested-git-repo project — see `mem:ennam-go-is-nested-git-repo` for the pattern, same applies to ennam.kg.python):
  - `ennam.kg.python` @ dd954c8 — "test(ocr): B2 figure retrievability + CER harness"
  - workspace-root @ 4fe4835 — "docs(daab): B2 golden-set doc — ..."
- Harness works, no production OCR/preprocessing code touched.
- Golden set (5 items, 2 FOUND controls / 3 MISS targets):
  1. `11381263.pdf` p0 `122,81ha` → FOUND, cer=0.000 (control)
  2. `11381263.pdf` p1 `98,18ha` → MISS, cer=0.286 (mangled to `98,1 §ha`)
  3. `11381263.pdf` p7 `4,38 ha` → MISS, cer=0.286 (mangled to `4.3§ ha`)
  4. `.../33,6ha).pdf` p0 `33,6ha` → FOUND, cer=0.000 (control; corrects recon)
  5. `.../06 Nộp tiền thuê đất.pdf` p0 `Số: 115/TB-BQLKKT` → MISS, cer=0.471 (decorative-font garbling, different failure class; best-effort per brief)

## Next steps
- Task 2 (preprocessing) / Task 3 (RapidOCR + regex fixes) should re-run `uv run python scripts/b2_figure_metrics.py` with a preprocessed/vi-model OCR callable substituted for `TesseractEngine.ocr_image` to capture AFTER numbers.
- Gate: #2/#3 should flip to FOUND with CER trending toward 0; #1/#4 must stay FOUND (regression guard); #5 is best-effort, not a hard gate.
- No genuine "hard-detection miss" (figure present in source, absent everywhere in extracted text) was found during this task — if Task 2/3 need one, it may need fresh discovery rather than reusing the `33,6ha` example.

## Blockers / Risks
- None. Task complete, both commits verified, harness re-run after the whitespace fix to confirm baseline stability.
