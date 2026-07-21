# Checkpoint: OCR/extraction content-loss fix + doc-sync verified — 2026-07-16

## What was done
- **Doc-sync Plan A (AAAA↔DAAB) confirmed IMPLEMENTED** across 4 repos, all on `task/implement_docs_sync`, all committed clean: AAAA (list + signed-url endpoints, proxy exempt), Go (Sync, credential encrypt, `aaaa` allowlist), Python (worker sync cycle), Next (AAAA card + poll). 3 live connections (Dasin/2/3), 20 ingested / 1 failed.
- **Found + fixed 2 CRITICAL extraction bugs** via systematic-debugging (full record: `mem:backlog/ingestion-ocr-content-loss-bugs`):
  - **Bug B** — `parse_markdown_sections` dropped everything before the first heading; B2's appended `## Recovered Figures` became the only heading on OCR'd scans → whole body vanished silently.
  - **Bug A** — `pdf_render` probe was char-count-only (image-coverage half never implemented) → scans with a garbage Latin text layer bypassed OCR.
- **Verified by measurement:** Dasin diacritics **20% → 88%**; BCTC 2024 **2,208 → 19,023 chars** (extractor yields 19,038); BCTC 2023/2025 ~10×; chunks 40→147. Regression on 9 real PDFs 4/4 PASSED; 701 tests pass; ruff clean on touched files.
- **Proved doc-sync was NOT at fault**: `Dasin 3` (sync) ≡ `Dasin 4` (direct upload), byte-identical → shared extraction path was the culprit.
- **Verified DAAB MCP over HTTP works** from this session: `daab-bridge :8765` (`serve --http`, `KG_MCP_AUTH_PASSTHROUGH=true`), handshake `initialize` → `Mcp-Session-Id` → `tools/list` = ~30 `kg_*` tools; project scoping via `X-KG-Project-Id` header (no `.mcp.json` edit needed). Helper written: scratchpad `mcp_call.py` (`list` / `call <tool> '<json>'`).

## Files changed
- `ennam.kg.python/src/ennam_kg/ingestion/pipeline/document_tree.py` (Bug B), `.../ingestion/ocr/pdf_render.py` (Bug A)
- `ennam.kg.python/tests/ingestion/test_document_tree.py`, `tests/test_pdf_render.py`, `tests/test_extraction_regression.py` (new)
- `docs/superpowers/specs/2026-07-15-daab-doc-sync-planA-aaaa-endpoint-design.md`, `docs/superpowers/plans/2026-07-15-daab-doc-sync-planA.md`, `docs/superpowers/plans/2026-07-16-ocr-extraction-content-loss-fix.md` (new); superseded banners on the 2026-06-26 spec+planB.
- Commits: `5918f62`, `456837e`, `98c86bd`, `f8df24e`.

## Current state
- Corpus **clean for the first time** → sim-consumer harness is UNBLOCKED (running it earlier on 80%-garbage text would have produced misleading "retrieval is bad" findings).
- DAAB project `Dasin` = `da53ae43-8f7c-45ba-9e25-ecc46810f31f` (9 docs, 147 chunks, 41 concepts, 82 mentions, 70 similar_to). Dasin 2/3/4 deleted.
- Workspace-root docs/memories **not yet committed**; nothing merged to `main` on any of the 4 repos.

## Next steps (decided, evidence-led)
1. **Run the sim-consumer MCP harness on Dasin** (`other_projects/daab-sim-consumer`, persona+rubric already in its `CLAUDE.md`): write `questions-dasin.md` for the real DD set (3 audited financials 2023/24/25, GPĐT, GCNĐKKD, 5.1M USD capital increase) → cross-doc financial trend is exactly `kg_graph_retrieve`'s thesis. Deliverable: `findings-dasin.md` + synthesis.
   - **Caveat, don't overclaim:** Dasin is only 9 docs → validates the AAAA→sync→OCR→graph→MCP→consumer LOOP, but does NOT answer the corpus-level BA-033 Slice 2 go/no-go (that needs Cảng Định An, 145 docs). See `mem:backlog/ba033-slice2-readiness-path`.
2. Let the findings rank what's next — **including whether the `concept`-entity gap is worth fixing** (don't fix blind: concepts grew only 28→41 despite 4× text).
3. Then: commit root docs + decide merge/PR for the 4 branches.

## Blockers / Risks
- `.mcp.json` API keys keep getting revoked (hardcoded in-repo) — same class as `mem:backlog/aaaa-daab-sync-token-settings-ui`. Current working key was supplied by the user this session.
- Pre-existing (NOT caused here): `tests/extraction/test_parser.py::test_drops_out_of_range_span_and_orphan_relation` fails; 16 ruff F401 in `benchmark/runner.py`.
- Re-ingest gotcha: must DELETE a project to force re-sync (dedup on `(document_id, content_hash)` makes re-sync a no-op).
