# Checkpoint: claude — 2026-08-17 (import pharmacy demo 2026-08-17)

## Đã làm
1. Backup `pharmacy_demo` cũ (19 bảng, 2026-08-03) → scratchpad `pharmacy_demo_BEFORE-2026-08-17.dump`
   (1.249.857 B, trùng đúng size dump 08-03 ⇒ DB chưa drift). Dump cũ vẫn còn ở
   `daab-export-2026-08-03/` làm đường lùi thứ 2. 0 kết nối đang mở khi drop.
2. drop → create → `pg_restore` bản 2026-08-17 vào **daab-postgres (cổng 5433)**.
3. Verify khớp README: 21 bảng · invoices 972 · receipts 5.345 · Sarah Miller (EMP-0006)
   50 reprint, người nhì 7 · **40 cặp** reprint 1–48h trước refund do chính cô xử lý.
   (transactions 5001→5002, employees 110→111 — README không nhắc, khác nhỏ so bản cũ.)
4. `POST /data-sources/{id}/extract-schema` → completed 21/21 (`source_tables` có invoices+receipts).
5. `POST /data-sources/{id}/sync-schema` → completed 21/21.
6. **`POST /data-sources/{id}/generate-kg`** → 21 node `architecture` (`public.<table>`) + FK edges
   (invoices→customers/stores/transactions, receipts→employees/stores/transactions).

## ⚠️ README THIẾU MỘT BƯỚC
README ghi *"đăng ký datasource và bấm sync-schema để 21 bảng vào schema graph"* — **sai/thiếu**.
`sync-schema` chỉ đồng bộ METADATA (`source_tables`); sau khi chạy nó xong knowledge graph VẪN
19 node cũ nguyên mốc 2026-08-03. Node `public.<table>` do **`generate-kg`** tạo
(`internal/handler/kg_generation.go:88` — *"Creates one knowledge_node per schema table"*).
Thứ tự đúng: extract-schema → sync-schema → **generate-kg**.

## Hai vấn đề tìm được (KHÔNG phải lỗi import — cần quyết định riêng)

### A. Q15 sinh SQL thiếu filter `print_type='Reprint'`
Hỏi đúng nguyên văn Q15 "Which employees reprint receipts the most?" → SQL đếm TOÀN BỘ receipt,
không lọc print_type. Sarah vẫn #1 nhưng **142 vs 109** thay vì **50 vs 7** ⇒ tín hiệu outlier
làm nên FND-007 bị san phẳng, demo mất sức thuyết phục.
Nguyên nhân góp phần: mô tả AI của node `public.receipts` **bịa giá trị ví dụ** —
*"the type of print (e.g., customer copy, merchant copy) in `print_type`"*; thực tế là
`Original / Reprint / Gift Receipt`. Mô tả sai kéo planner khỏi cột/giá trị đúng.
(Câu tôi tự đặt còn tệ hơn: lọc nhầm sang `print_reason` → 0 dòng.)
README nói Q15 đã verify e2e 2026-08-17 ⇒ có thể môi trường DAAB team dùng model khác.

### B. Import ĐẨY 13 CỘT RA KHỎI value-hints (regression thật, âm thầm)
`ValueHinter` (`internal/service/value_hints.go`) có trần `valueHintMaxColumns = 120`, duyệt
theo thứ tự tên bảng rồi dừng. Số cột ứng viên: **119 trước import → 133 sau import**.
13 cột rơi khỏi trần: `transactions.employee_id/customer_id/transaction_type/payment_method/status`
và **toàn bộ `voids`** (void_reason, stage, flag_reason, ...).
Đây đúng là lớp lỗi ValueHinter sinh ra để chặn (doc của chính nó: planner đoán `'rejected'`
trong khi data là `'Rejected'` → 0 dòng, "confidently WRONG"). Ảnh hưởng Q12 (voids/after-hours)
và mọi câu lọc theo status/type/payment_method của transactions.
`receipts.print_type` ở vị trí 91 nên KHÔNG bị cắt — tức A và B là hai nguyên nhân độc lập.

## Next steps
- Quyết định về B: nâng `valueHintMaxColumns` (120 → ~160) trong `ennam.kg.go` rồi rebuild, hoặc
  chấp nhận rủi ro. Chưa sửa vì nằm ngoài phạm vi "import data" + là repo khác.
- Quyết định về A: sửa mô tả node `public.receipts` (PATCH /api/v1/kg-nodes/{id} có nhận
  `ai_description`) để nêu đúng giá trị thật, hoặc hỏi DAAB team môi trường họ verify Q15.
- Chạy thử Q13/Q14/Q16/Q17 trước demo — mới chỉ test Q15.

## Blockers / Risks
- Không có blocker cho việc import. Rủi ro demo: A + B ở trên.
