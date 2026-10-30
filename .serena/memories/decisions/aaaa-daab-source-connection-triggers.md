# AAAA ↔ DAAB Source Connection — cơ chế trigger (verified 2026-10-30)

## Kết luận (đã verify trên source, không phải suy đoán)

- **Sync chỉ chạy khi admin DAAB bấm "Sync now"** trên dashboard. Không có cách nào khác.
- Không auto-sync sau khi Connect (`use-aaaa-connection.ts:53-59` chỉ invalidate queries).
- Không có scheduler/cron: `worker.py` `run_consumers()` chỉ `consume_forever` trên Redis queue, không timer nào.
- AAAA **không thể** tự trigger: `POST /sync` cần project-admin role (`source_connection.go:272`), và grep toàn `am-ai-agents/src` không có outbound call nào tới DAAB (chỉ 2 comment nhắc tên).
- `webhook_secret` được sinh + có `GetByWebhookSecret` ở store/service nhưng **KHÔNG route HTTP nào dùng** — scaffolding chết, sẵn sàng cho phương án webhook.
- **Analyze thì tự động**: `ingestion_engine.run_batch` chạy ngay sau `create_draft` trong cùng vòng lặp (`worker.py:517`). Không có bước duyệt draft thủ công.

## Đây là design decision, KHÔNG phải bug

`docs/superpowers/specs/2026-07-15-daab-doc-sync-planA-aaaa-endpoint-design.md:162`:
> ❌ Auto-sync / webhook (pull-on-trigger only — CTO: "chạy sau / khi trigger")

## Giới hạn generic

`POST /connections/{cid}/sync` trả **501** cho mọi `source_type` ≠ `aaaa` (`source_connection.go:282`).
Thêm nguồn pull mới = 4 thay đổi code DAAB (DraftSourceType, nhánh encrypt `service:64`, bỏ 501, adapter `DocSourceClient` + handler worker).
→ Với system thứ ba, **push qua `/ingest` là đường zero-code**, đừng quảng cáo pull là generic.

## Phương án tự động hoá (đề xuất, CHƯA implement)

1. Sync-on-connect — chain `syncAaaaConnection` vào `onSuccess` (~5 dòng FE).
2. Scheduler **phía Go** cạnh `internal/jobengine/`: publish thẳng `aaaa_sync` vào Redis, bỏ qua HTTP `/sync` nên không vướng admin-role. ⚠️ Khác hẳn `reconcile_connection` (hàm đó chỉ revoke derived_record bị tombstone).
3. Webhook `POST /api/v1/webhooks/source-connections/{secret}` dùng `GetByWebhookSecret` có sẵn + AAAA bắn từ Inngest sau analyze.

Khuyến nghị: #1 + #2 trước (gọn trong DAAB), #3 khi cần realtime.

## Bẫy khi debug "sync chạy mà không có gì"

Dialog Connect bị **Chrome autofill** điền email vào ô AAAA PROJECT ID và password vào ô token, dù cả 3 input đã có `autoComplete="off"`. Xác minh giá trị thật bằng `GET /connections` → `config.aaaa_project_id`, đừng tin screenshot. Project id sai → documents trả 0 rows + master-records trả `tombstone:true` (sync "thành công" nhưng rỗng). Token sai → 401.

## Bảo mật cần lưu ý cho nguồn mới

AAAA `verifyKey()` (`daab-key.service.ts:54`) chỉ kiểm key tồn tại/chưa revoke; `projectId` lấy từ query string → **một key đọc được mọi project**. Hệ thống nguồn mới nên scope key theo tenant/project.

## Tài liệu

Đã viết: `docs/integration/source-connection-pull-integration.md` (tiếng Việt, 9 mục, có sequence diagram + contract + trigger matrix + checklist debug).
