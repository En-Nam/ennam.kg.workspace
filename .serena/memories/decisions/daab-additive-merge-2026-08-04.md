# Quyết định: merge cộng thêm (không thay thế) dump DAAB vào DB live — 2026-08-04

## Bối cảnh
User đưa `daab-export-2026-08-03/` (2 file .dump: `ennam_kg` + `pharmacy_demo`) yêu cầu nạp vào
DAAB đang chạy. README hướng dẫn `pg_restore` thẳng (không `--clean`) — dump đó viết cho Postgres
RỖNG, không phải để merge vào DB đang sống có dữ liệu khác.

## Vấn đề phát hiện trước khi làm
1. Dump chứa 6 project: 5 project **TRÙNG Y HỆT** (cùng UUID) 5/8 project đang live (Dasin, C4K
   Staging, Cảng Định An M&A/v3, Sala Food — thiếu 3 Salonbookly vì dump cũ hơn) + 1 project THẬT
   SỰ MỚI (Michael Pharmacy Chain, id `4ad7a5fa-a036-4f6a-8229-39a20af23e38`).
2. `pg_restore` COPY theo khối: 1 hàng trùng khoá → CẢ BẢNG rollback, không phải chỉ hàng đó. Chạy
   thẳng README's lệnh sẽ làm bảng `projects` (và mọi bảng phụ thuộc) KHÔNG insert được gì, kể cả
   dữ liệu Pharmacy Chain thật sự mới — trông như "restore thành công" (exit code không chặn) nhưng
   thực chất dữ liệu mới không vào.
3. Code hiện tại (`ennam.kg.go/python/next`) ở branch `task/implement_docs_sync`; dump cần branch
   `task/mcp-write-datasource` (chỉ có ở remote). `schema_migrations` cả 2 bên đều ghi version=84 —
   NHƯNG con số khớp KHÔNG đảm bảo schema thật khớp: `ai_queries_status_check` ở live thiếu giá trị
   `clarification_needed` mà dump dùng → 2 nhánh migrate tới "84 bước" khác nội dung nhau.

## Cách làm (an toàn, additive, không đụng dữ liệu cũ)
1. `pg_dump -Fc` backup toàn bộ `ennam_kg` hiện tại TRƯỚC khi làm gì (lưu ngoài container).
2. Restore TOÀN BỘ dump vào DB TẠM `ennam_kg_stage` (rỗng, cô lập tuyệt đối — pg_restore ở đây 0 lỗi
   vì không có gì để xung đột).
3. Merge có chọn lọc từ stage → live bằng `dblink` (extension có sẵn), `INSERT ... SELECT ... FROM
   dblink(...) ON CONFLICT (pk) DO NOTHING` — cột/kiểu dữ liệu lấy ĐỘNG từ `pg_attribute`/
   `format_type`, không đoán tay (đoán tay từng sai — vd `port` integer vs varchar).
4. Vòng lặp qua TẤT CẢ 54 bảng, lặp lại nhiều lượt tới khi không còn tiến triển (bảng con phụ thuộc
   FK vào bảng cha mới insert sẽ tự qua được ở lượt sau — không cần tự suy luận thứ tự khoá ngoại
   thủ công cho từng bảng).
5. **Vòng lặp KHÔNG giải quyết được circular FK**: `data_sources.last_sync_job_id → sync_jobs.id`
   và `sync_jobs.data_source_id → data_sources.id` tham chiếu vòng nhau. Fix: insert `data_sources`
   trước với `last_sync_job_id` ép NULL, để `sync_jobs` insert được (giờ cha đã có), rồi UPDATE lại
   `last_sync_job_id` từ stage sau khi `sync_jobs` đã tồn tại.
6. **CHECK constraint lệch schema thật** (`ai_queries_status_check` thiếu `clarification_needed`)
   phải nới bằng tay (`DROP CONSTRAINT` + `ADD CONSTRAINT` với danh sách giá trị mở rộng — chỉ
   THÊM, không đổi 4 giá trị cũ) rồi mới insert được `ai_queries` (29 dòng) + `query_clarifications`
   phụ thuộc nó (4 dòng).
7. Verify cuối: so `count(*)` MỌI bảng giữa stage và live — không còn "stage > live" thì coi là sạch.
8. `pharmacy_demo` (DB nguồn cho write-path demo) restore trực tiếp bằng README's lệnh gốc — AN
   TOÀN vì đây là DB HOÀN TOÀN MỚI, không có gì để xung đột (0 lỗi khi chạy thẳng).
9. Xoá `ennam_kg_stage` sau khi xong.

## Kết quả
9 project (8 cũ nguyên vẹn + Michael Pharmacy Chain mới). `data_sources` Pharmacy POS DB
`allow_writes=true`. Playbook `create_order v1 approved`. `ai_queries`/`query_clarifications`
(lịch sử demo hỏi-lại-khi-mơ-hồ) đã vào đủ. Backup `ennam_kg` trước-khi-sửa còn giữ ở scratchpad
phiên (không phải chỗ lâu dài — cân nhắc chuyển vào nơi lưu trữ bền nếu cần giữ lâu).

## Bài học tái dùng cho lần merge dump khác
- KHÔNG BAO GIỜ chạy `pg_restore` thẳng README's lệnh vào DB đang có dữ liệu nếu không rõ dump có
  overlap gì — luôn restore vào DB tạm trước, so sánh, rồi mới quyết cách merge.
- `schema_migrations.version` khớp số KHÔNG chứng minh schema khớp nội dung nếu 2 nhánh phân kỳ.
- dblink + vòng lặp retry-tới-khi-ổn-định là cách tổng quát tốt để merge qua FK graph phức tạp mà
  không cần tự vẽ sơ đồ phụ thuộc — chỉ cần xử lý riêng circular FK (không tự giải được bằng lặp).
