# Checkpoint: subagent-driven (B2 Task 7 — recovered fields searchable) — 2026-07-14

## What was done
- Diagnosed follow-up to Task 6 (`15f185b`): Task 6 wired confusable repair into Tesseract chunk-content path but did NOT close the golden-set gap for `98,18ha`/`4,38ha` — one is a scoped regex gap, the other needs `§→8` not `§→5` (context-dependent, no vision).
- Implemented Task 7: `handle_extract_upload` in `ennam.kg.python/src/ennam_kg/worker.py` now appends a `## Recovered Figures (OCR fields)` markdown section (built by new `_build_recovered_fields_section`) with RapidOCR's already-correct `structured_fields` values to `content_raw` BEFORE `update_draft_content`, making them full-text searchable. Excludes the `unrecovered` marker key. `_attach_structured_fields`'s separate metadata PATCH is untouched (additive).
- TDD: 3 new tests in `tests/test_worker_extract_gate.py::TestRecoveredFieldsAppendedToContent` (positive/empty/unrecovered-exclusion). RED confirmed before fix, GREEN after.
- Full suite: 667 passed, 1 skipped, 1 pre-existing unrelated failure (`tests/extraction/test_parser.py::test_drops_out_of_range_span_and_orphan_relation`, confirmed failing identically on `15f185b` — not a regression). `ruff check` clean.
- Live verification: rebuilt `daab-worker`, scoped-deleted the same 3 B2 golden-set docs (hard gate 0/0/0, 77→74), re-ingested via `reingest_b2_task5.py` (reused unchanged from prior session's scratchpad). New hub ids: `11381263.pdf`→`aa05c1ce-64cd-4b31-a41a-5c5f392c8f26`, 33,6ha doc→`2bfb480a-217d-4bd9-bf47-2f1997d277b9`, 06 Nộp tiền thuê đất.pdf→`ce77d987-36db-4ad5-9263-2505c807cdd4`.
- DB query confirmed `document_chunk.content` (knowledge_nodes.properties->>'content', node_type='document_chunk') for `11381263.pdf` NOW contains `98,18ha` (1 chunk) and `4,38ha` (1 chunk) verbatim. Controls unregressed: `122,81ha` (2 chunks), `33,6ha` on the other doc (1 chunk). Unrelated doc `de64038d-...` unaffected (26 substrate nodes unchanged, project doc count round-tripped 77→74→77).
- Documented as "Task 6" (retrospective, honest) + "Task 7" sections appended to `docs/superpowers/plans/b2-golden-set.md`.

## Files changed
- `ennam.kg.python/src/ennam_kg/worker.py` — new `_build_recovered_fields_section`, wired into `handle_extract_upload`.
- `ennam.kg.python/tests/test_worker_extract_gate.py` — 3 new tests.
- `docs/superpowers/plans/b2-golden-set.md` — Task 6 (retrospective) + Task 7 sections.

## Current state
- B2 golden-set OCR-figure-fidelity gap for `98,18ha`/`4,38ha` is CLOSED via retrievability fix (not OCR-accuracy fix). Live-verified on the actual re-ingested corpus, not just unit tests.
- Both commits made: `ennam.kg.python` repo `bd1dde6`; workspace-root repo `c4f3871`. Neither pushed (not requested).

## Next steps
- None required for this task. If future OCR work touches Task 3's confusable map, note the `§→8` vs `§→5` ambiguity documented in Task 6's retrospective section as a known limit of pure-regex repair.

## Blockers / Risks
- None. Docker stack (`daab-worker`, `daab-server`) left running/healthy post-rebuild — no cleanup needed, matches expected steady state.
