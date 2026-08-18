# QA — Pharmacy demo Q13–Q17 (2026-08-17, CHỐT SAU KHI VÁ + WARM CACHE)

DB `pharmacy_demo` 2026-08-17 (21 bảng) · `daab-postgres:5433` · kg-server build lần 3.
Chuỗi bắt buộc sau khi đổi data: extract-schema → sync-schema → **generate-kg**.
DAAB commit: `7cef8fe` (value-hints cap) + `3623470` (time window) trên
`task/implement_docs_sync` — **đã commit, CHƯA push**.

## BỘ CÂU HỎI DÙNG CHO DEMO — 7 plan đã verify + đang ấm trong cache

| # | Câu hỏi (dùng NGUYÊN VĂN) | Kết quả đã verify |
|---|---------------------------|-------------------|
| 13 | Which invoices are overdue, and what is the total outstanding amount by store? | PH-003 4463.13 · PH-001 4064.43 · PH-002 3900.23 · PH-004 2488.58 · PH-005 2215.88 |
| 14 | Show the complete document trail for transaction TXN-0000857: line items, payments, receipt prints, invoice, and any refund. | 6 dòng, đủ 6 bảng. Kể trọn FND-007. Fan-out — đừng SUM `amount`. |
| 15 | Which employees reprint receipts the most? | EMP-0006 **50** · EMP-0001 7 · EMP-0038 6 · EMP-0040 5 |
| 16 | List receipt reprints that happened shortly before a refund of the same transaction. Who printed them? | 50 dòng, **40 của Sarah**. Không có chặn trên thời gian. |
| **16b** ⭐ | **For each employee, how many times did they reprint a receipt and then, in the following 48 hours, process a refund for that same transaction? Only count reprints that came before the refund.** | **Sarah Miller (EMP-0006) = 40**, đúng 1 dòng, có TÊN. Khớp tuyệt đối answer key FND-007. |
| 17 | *(nguyên văn HỎNG 4/4 — đừng dùng)* Thay bằng 17b/17c ↓ | |
| **17b** vi | **Cửa hàng nào có tỉ lệ hóa đơn xuất cho doanh nghiệp cao nhất, so với hóa đơn cho khách lẻ?** | PH-002 **35,27%** ✓ |
| **17b** en | **Which store has the highest proportion of invoices billed to companies rather than to individuals?** | PH-002 **35,27%** ✓ |
| **17c** en | **Across all invoices, how many are billed to companies and how many to individuals?** | companies **314** / individuals **658** ✓ (32,3% / 67,7%) |

**16b là câu mạnh nhất cho FND-007**: đời thường (KHÔNG tên cột), ra đúng con số answer key,
kèm tên nhân viên. Chỉ chạy được nhờ 2 bản vá — trước đó câu này bất khả thi.

## Cạm bẫy đã đo được về cách hỏi (dùng để soạn kịch bản demo)
- "…and then refunded that same transaction within 48 hours" (KHÔNG nói rõ thứ tự) → planner bỏ
  chặn dưới ⇒ **42** thay vì 40, gồm 5 ca refund xảy ra TRƯỚC reprint (ngược logic). Sai tinh vi,
  Sarah vẫn nổi bật nên dễ lọt. **Phải thêm "Only count reprints that came before the refund."**
- Câu 17 nguyên văn (ghép 2 ý) hỏng ỔN ĐỊNH 4/4; câu đơn ~50/50 ⇒ tách từng ý.

## Đã chủ động XOÁ khỏi cache 3 plan hỏng/sai
Q17 nguyên văn (tautology) · câu Q16 kỹ thuật cũ (lỗi interval, nay đã vá nhưng bản kỹ thuật
không hợp demo) · bản 16 cho ra 42. ⇒ Cache chỉ còn plan đã verify đúng.
⚠️ **KHÔNG xoá cache trước demo. KHÔNG rebuild sát giờ demo** (rebuild ⇒ buộc phải clear ⇒ warm lại).

## Bản vá đã chứng minh trên thực tế
- `sql_generator.go` (interval): SQL sinh ra chứa `<= r.printed_datetime + interval '48 hours'` ✓
- `plan_harden.go` (EXTRACT/EPOCH): dạng `EXTRACT(EPOCH FROM …)` giờ chạy, trước đây báo
  "unknown column(s) EPOCH" ✓
- `value_hints.go` (cap 200): "How many voids happened after the receipt was printed…" dùng đúng
  literal `'After Receipt Printed'` → 36 dòng khớp ground truth ✓

## Còn tồn
- Planner phi tất định (xem `mem:decisions/daab-nl-planner-nondeterminism`) — bảng trên chỉ
  đảm bảo đúng chừng nào cache còn nguyên.
- Gốc rễ chưa sửa: model không bật `value_is_expression`. Hai bản vá là lưới hứng tầng dưới.
- 2 commit DAAB chưa push.
