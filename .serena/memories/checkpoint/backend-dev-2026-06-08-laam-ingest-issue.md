# Checkpoint: backend-dev — 2026-06-08 (LAAM ingest issue report — diagnose + fix)

## What was done
Xử lý report `kg_test_mcp/notes/2026-06-08-kg-ingest-issue-report.md` (test thật flow LAAM ingest, project `1f991b74...`). Chẩn đoán 3 issue, đối chiếu code, sửa môi trường + 1 enhancement code, verify E2E LIVE.

### Chẩn đoán (đối chiếu code, read-only)
- **ISSUE-1 (kẹt `approved`)** = root cause **`ingestion.auto_queue_processing=false`** (default), KHÔNG phải do embedding chết. Bằng chứng: node ở `approved` (không phải `processing`) ⇒ `ProcessBatch` chưa từng gọi (UpsertFromIngestion chỉ gọi ProcessBatch khi setting bật). Không có cron poll draft approved.
- **ISSUE-2 (semantic 502)** = **transient**: lúc test service `indexer:8081` down/restart; verify lại đã healthy (200, 7.8ms, 384-dim).
- **ISSUE-3 (UX)** = gap thật → enhancement.

### A — fix môi trường + gỡ kẹt (LIVE, user đã đồng ý)
- `UPDATE system_settings SET value='true' WHERE key='ingestion.auto_queue_processing'`.
- Trigger reprocess draft `ed5fcaa3` qua `POST /api/v1/projects/{id}/draft-nodes/process`.
- **Verify E2E**: draft `approved→processing→processed`; sinh **1 external hub + 14 document_section + 10 concept**; **14 embeddings @384-dim**; full-text + semantic search đều trả kết quả (502 hết). = chính là Task 7 E2E của plan LAAM, nay đã chứng minh thật.

### B — ISSUE-3 (code, commit `6fce1cb`)
Thêm `processing_state` (awaiting_approval|pending_indexing|indexing|searchable|failed) + `hint` vào response ingest single/batch + endpoint poll status; helper `service.ProcessingStateFor(draftStatus)`. TDD: `TestProcessingStateFor` (6 case) + `_ApprovedNotSearchable` PASS. Verify LIVE: poll `ed5fcaa3` → `processing_state:"searchable"`.

## Files changed (branch task/implement_mcp)
- `internal/service/ingest_public.go` — `ProcessingStateFor` + 2 field, wire single/batch
- `internal/service/ingest_public_test.go` — new (TDD)
- `internal/handler/ingest_public.go` — thêm processing_state/hint vào Status poll

## Current state
- LAAM ingest E2E xanh trên stack live; note "Cảng Định An" đã nhớ + search được.
- `go build ./...` OK; service+handler test green; gofmt clean. Bridge proxy response nên không cần đổi schema.
- `auto_queue_processing=true` đã set trên DB live (project test).

## Next steps
- (Hoãn) Fail-soft phía Python worker (ISSUE-1.2): embedding lỗi vẫn index full-text + đánh dấu `embedding_pending`, không kẹt.
- Cân nhắc default `auto_queue_processing` cho project memory (product decision).

## Blockers / Risks
- Không có. Setting live đặt cho project test `1f991b74`; nếu deploy môi trường khác phải set lại (toggle mặc định false).
