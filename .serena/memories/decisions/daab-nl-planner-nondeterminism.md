# DAAB NL→SQL planner là PHI TẤT ĐỊNH — cache là thứ ổn định hoá

**Ngày:** 2026-08-17 · Đo trên Michael Pharmacy Chain (21 bảng), sau khi rebuild kg-server.

## Bằng chứng quyết định
Cùng MỘT câu, không đổi một chữ — "Which store has the highest share of corporate invoices?":
- Lần 1 (plan mới): `WHERE billing_type='Corporate'` rồi mới chia ⇒ luôn 100%, trả **PH-005 SAI**.
- Xoá đúng dòng cache đó → hỏi lại y nguyên.
- Lần 2 (plan mới): `SUM(CASE WHEN …)/COUNT(*) GROUP BY store_id` ⇒ **PH-002 35,27% ĐÚNG**.

⇒ Không phải do từ vựng, không phải do câu ghép, không phải do thiếu tên cột.

## Các giả thuyết ĐÃ BỊ BÁC BỎ (đừng đi lại đường này)
- ~~"Phải nhắc tên cột (`billing_type`, `store_id`) thì mới đúng"~~ — SAI. Câu tiếng Việt đời
  thường *"Cửa hàng nào có tỉ lệ hóa đơn xuất cho doanh nghiệp cao nhất, so với hóa đơn cho khách lẻ?"*
  chạy đúng, không có tên cột nào. (User phản biện đúng: bắt end-user biết tên cột là phá giá trị sản phẩm.)
- ~~"Lỗi do câu hỏi ghép 2 ý"~~ — SAI. Câu 1 ý *"share of corporate invoices"* cũng hỏng (lần 1).
- ~~"Lỗi do dạng 'share of <tính từ> <danh từ>'"~~ — SAI. *"share of rejected claims"* chạy đúng
  (PH-004 15,47%), cùng dạng y hệt.
- ~~"Mô tả AI node receipts bịa giá trị ví dụ gây lỗi Q15"~~ — SAI (xem `mem:qa/latest-results`);
  Q15 sai/đúng đổi qua lại cũng do phi tất định.

## Mức độ ổn định quan sát được
| Cách hỏi | Số lần thử | Đúng |
|---|---|---|
| Q17 nguyên văn (ghép 2 ý) | 3 plan mới | 0/3 ở vế "store nào" (vế tỉ lệ tổng thì đúng: 314 corporate / 658 personal) |
| 1 ý, tiếng Anh | 2 plan mới | 1/2 |
| 1 ý, tiếng Việt nêu rõ mẫu số | 1 | 1/1 |
| Q10 "rejection rate" | 1 | 1/1 |
⇒ Câu ghép hỏng ỔN ĐỊNH hơn; câu đơn là xác suất.

## Hệ quả vận hành (QUAN TRỌNG cho demo)
`nl_plan_cache` (key = normalized_query + schema_fingerprint) khiến một plan ĐÃ ĐÚNG được tái
dùng nguyên vẹn ⇒ **cache chính là cơ chế biến câu trả lời thành tất định**.
Quy trình demo an toàn, KHÔNG cần end-user biết gì về schema:
1. Hỏi mỗi câu 1 lần trước demo, **verify kết quả**.
2. Câu nào sai → xoá đúng dòng cache đó rồi hỏi lại cho tới khi đúng.
3. **KHÔNG xoá cache trước khi demo.** Plan tốt nằm sẵn, demo chạy lại đúng y hệt.
4. Tách câu ghép thành từng ý (lời khuyên này end-user làm được, không cần tên cột).

⚠️ Ngược lại: sau MỌI lần rebuild ảnh hưởng planner thì PHẢI xoá cache (nếu không nó phục vụ
plan cũ) — rồi warm lại từ đầu. Hai yêu cầu này xung đột nhau về thời điểm: rebuild → clear →
warm → demo. Đừng rebuild sát giờ demo.

## Việc nên làm với DAAB team
Đây là bug chất lượng planner, không phải bug dữ liệu: cùng input cho ra plan đúng/sai ngẫu
nhiên trên câu hỏi dạng tỉ lệ. Kèm 2 ca tái hiện: (a) filter-then-divide ⇒ 100%;
(b) group-by chính cột đang tính share ⇒ 1 và 0.
