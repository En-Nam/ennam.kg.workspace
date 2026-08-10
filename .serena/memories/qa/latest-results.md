# QA — Michael Pharmacy Chain, 12 câu hỏi demo — 2026-08-10

Chạy qua LAAM (localhost:3100, gpt-oss-120b) sau 4 thay đổi hop-reduction hôm nay.
Mỗi câu một hội thoại MỚI, gửi đúng nguyên văn trong `docs/demo-script-michael-pharmacy-12-questions.md`.
Đối chiếu đáp án kỳ vọng trong chính file đó.

## Kết quả: 11/12 đạt, 1 sai

| # | Câu | Kỳ vọng | Thực tế | Tool | KQ |
|---|---|---|---|---|---|
| 1 | Which employee refunds the most? | Sarah Miller EMP-0006, $3,689.32 | đúng | 2 | ✅ |
| 2 | Show every refund processed by Sarah Miller. | 62 lần + bảng | 62, có bảng | 2 | ✅ |
| 3 | Which managers approve the most refunds? | Ava Ross 23, Amanda Lee 19, Ethan Hill 18 | đúng cả 3 | 2 | ✅ |
| 4 | **Show duplicate refunds across stores.** | **9 giao dịch** | **8, 8, 2 (3 lần chạy)** | 2/2/6 | ❌ |
| 5 | Which products are most frequently refunded? | School Supplies Value Pack đứng đầu theo số lần | đúng, 6 lần | 2 | ✅ |
| 6 | Show the full receipt … selected transaction. | AI hỏi lại "giao dịch nào?" | hỏi lại | 0 | ✅ |
| 7 | Which stores have the highest inventory variance? | PH-005; script cảnh báo 2 cách đo ngược nhau | DAAB HỎI LẠI value vs quantity | 2 | ✅+ |
| 8 | Which products have negative inventory? | "không có sản phẩm nào" | đúng, dùng system_quantity (không rơi bẫy variance_quantity) | 4 | ✅ |
| 9 | Which employee has repeated cash drawer shortages? | Robert Reed 9 lần / 58 nhân viên | đúng cả hai số | 2 | ✅ |
| 10 | Which store has the highest insurance claim rejection rate? | PH-004, 15.47% | đúng | 2 | ✅ |
| 11 | Compare store sales, refunds, inventory variance, and claims. | ⚠️ hay quá tải/thiếu | HỎI LẠI (variance value/qty, sales amount/profit) | 2 | ✅+ |
| 12 | Show all after-hours overrides and sensitive activities. | ⚠️ mơ hồ nhất, hỏi lại nhiều lượt | hỏi lại, liệt kê các định nghĩa flagged | 3 | ✅ |

`✅+` = tốt hơn kỳ vọng: script ghi ⚠️ nhưng cơ chế hỏi-lại của DAAB xử lý đúng.

## Câu 4 — sai thật, và KHÔNG phải do thay đổi hôm nay

Planner nối theo **`customer_id`** (cùng KHÁCH, khác cửa hàng) thay vì **`original_transaction_id`**
(cùng GIAO DỊCH GỐC bị hoàn ở 2 nơi). Kiểm chứng trực tiếp trên `pharmacy_demo`:
- đúng: `group by original_transaction_id having count(distinct store_id) > 1` → **9**
- planner: `group by customer_id …` → **8**

Con số 8 là thật nhưng trả lời một câu hỏi KHÁC, và câu trả lời trình bày nó như thể đúng.

**Bằng chứng không phải regression:** lần chạy 04:55:01 gửi xuống DAAB **nguyên văn**
"Show duplicate refunds across stores." — planner vẫn chọn `customer_id`. Text vào đúng như ý,
key ra vẫn sai ⇒ lỗi nằm hoàn toàn trong planner của DAAB, các thay đổi ở LAAM/bridge hôm nay
không thể là nguyên nhân. Commit `ec949ac` (2026-08-07, TRƯỚC hôm nay) trích đúng câu SQL với
đúng join key này. Bản vá lúc đó là một NOTE, không sửa việc chọn key.

⚠️ `docs/demo-script-michael-pharmacy-12-questions.md` ghi câu 4 là "✅ 9 giao dịch — đã sửa".
**Không tái hiện được.** Nên sửa lại tài liệu, hoặc sửa planner, trước khi demo.

Phụ: 2 lần chạy sau, LAAM viết lại câu hỏi 4 lần liên tiếp (chốt "same customer, same amount,
same datetime") và kết quả tụt còn **2 dòng** — vấn đề viết-lại-câu-hỏi làm một đáp án sai thành
sai nặng hơn. Xem `mem:decisions/tool-result-notes-ignored-by-model`.

## Hiệu năng
Không câu nào cần quá 6 tool call. Các câu tra cứu thẳng đều **2 call**
(`kg_query_datasource` + `kg_query_datasource_status`) — trước loạt sửa hôm nay là 5.
`kg_list_projects` / `kg_list_datasources` không xuất hiện ở bất kỳ câu nào.
