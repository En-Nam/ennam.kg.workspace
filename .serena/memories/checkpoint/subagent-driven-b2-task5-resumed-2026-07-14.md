# Checkpoint: subagent-driven-b2-task5-resumed — 2026-07-14

## What was done
- Resumed B2 Task 5 (live re-ingest verification) from the earlier BLOCKED state. The destructive cleanup (delete of the 3 golden-set docs' old substrate — 95 nodes, 92 embeddings, 143 edges, 3 canonical rows, hard-gate verified 0-live) was already done in a prior session and was NOT repeated.
- User supplied a working, Cảng-scoped API key. Verified live (HTTP 200 on `GET /api/v1/projects/592c7ff7-.../`).
- Sanity-checked the ready-made re-ingest script (`reingest_b2_task5.py`, scratchpad) against the actual Go source (`ingest_upload.go`, `draft_node.go`, `models/draft_node.go`) before running — route, multipart field names (`file`/`title`/`auto_approve`), response field `draft_id`, and terminal statuses (`processed`/`failed`/`rejected`) all matched; no script changes needed.
- Re-ingested all 3 target PDFs (`11381263.pdf`, the 33,6ha planning doc, `06 Nộp tiền thuê đất.pdf`) via `POST /ingest/upload`. All 3 reached `status=processed`.
- Confirmed via source read (`ennam.kg.go/internal/store/canonical_document.go`) that the dedup lookup filters `deleted_at IS NULL`, and the earlier cleanup hard-deleted (not soft-deleted) the canonical rows — so dedup was structurally guaranteed to miss. Empirically confirmed 0 "content-hash dedup hit" log lines for these 3 drafts.
- Ran `b2_figure_metrics.py` (unmodified) — reproduced the documented baseline exactly (2 FOUND / 3 MISS), as expected since that harness always runs raw Tesseract with no preprocessing, independent of the live pipeline.
- Queried live DB (`draft_nodes.metadata->>'structured_fields'`) for the 3 new hub node ids: `"33,6ha"` FOUND verbatim (+ 3 matching chunks); `"98,18ha"` and `"4,38ha"` (previously Tesseract-mangled) now FOUND correctly on the live RapidOCR-fields path; control figure `"122,81ha"` unregressed.
- Spot-checked one unrelated document (`de64038d-...`) — untouched, 26 substrate nodes + 1 live canonical row, unaffected.
- Project `document` node count: 74 → 77 (exactly +3, round-trips the earlier 77→74 delete).

## Files changed
- `docs/superpowers/plans/b2-golden-set.md` — appended "Task 5 — Live Re-ingest Verification (RESUMED — complete)" section with full before/after evidence. Committed workspace-root `5b165cb`.
- No code changes (operational/verification task only). `reingest_b2_task5.py` (scratchpad) used as-is, unmodified.

## Current state
- B2 plan fully complete: Tasks 1-5 all done. New hub node ids: `8464e764-...` (11381263.pdf), `2be30882-...` (33,6ha doc), `ef0fb424-...` (06 Nộp tiền thuê đất.pdf).
- All Task 5 / §8 success criteria met: target figure retrievable, both mangled figures corrected, no regression, other 74 docs unaffected.
- Only remaining open item in the whole B2 plan: Task 3's vi/latin PP-OCR model-conversion half — explicitly spike-gated and deferred by design (unit-tolerance regex ships regardless).

## Next steps
- None required for B2. If picked up later: optionally revisit the Task 3 model-conversion spike if a future corpus reproduces Tesseract-style digit-confusable mangling on the RapidOCR-fields path (not observed on this golden set).
- Note (not this task's scope): re-ingest triggers B1 entity resolution re-run on the new nodes per NFR-256 — investor variants may re-merge/re-queue; independent of this fix, not verified here.

## Blockers / Risks
- None. Task complete, verified, committed.
