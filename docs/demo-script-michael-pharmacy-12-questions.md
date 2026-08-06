# Hướng dẫn hỏi — 12 câu hỏi (Michael Pharmacy Chain)

> Dành cho người dùng bình thường, hỏi bằng LAAM `/chat` hoặc `/constellation` (Larvis) —
> **cứ hỏi bằng lời tự nhiên**, không cần biết tên bảng/cột trong database.
> Số liệu bên dưới đối chiếu trực tiếp từ dữ liệu thật ngày **2026-08-05**, để bạn tự kiểm tra
> câu trả lời của AI có đúng không.

## Cách dùng chung

- Cứ gõ câu hỏi như hỏi một đồng nghiệp — không cần thêm chữ tiếng Anh kỹ thuật nào.
- Đôi khi AI sẽ **hỏi lại** để chốt ý trước khi trả lời (ví dụ "đếm số lần hay tổng số lượng?").
  Đó là điều **tốt** — nó thà hỏi lại còn hơn đoán bừa. Cứ trả lời theo ý bạn muốn bằng lời
  thường, không cần dùng đúng từ nó vừa nói.
- Vài câu hỏi ngược của AI hiện vẫn còn lộ **thuật ngữ kỹ thuật** (tên bảng, tên cột) mà người
  dùng thường không biết — các câu đó được đánh dấu ⚠️ bên dưới, kèm gợi ý cách trả lời.
- Thỉnh thoảng (khoảng 1/10 lượt) AI trả lời chưa trọn hoặc báo lỗi thoáng qua — không phải do
  bạn hỏi sai, cứ hỏi lại y nguyên câu đó.
- Nếu hỏi nhiều câu liên tiếp, hỏi **trong cùng một cửa sổ chat** — AI nhớ được ngữ cảnh
  (ví dụ đã biết bạn hỏi về Sarah Miller ở câu trước) nên trả lời càng lúc càng chính xác hơn.

---

## 12 câu hỏi

### 1. Nhân viên nào hoàn tiền nhiều nhất?
```
Which employee refunds the most?
```
✅ AI trả lời thẳng: **Sarah Miller (EMP-0006)** — tổng **3,689.32 USD**.

### 2. Xem toàn bộ các lần hoàn tiền của Sarah Miller
```
Show every refund processed by Sarah Miller.
```
✅ AI trả lời thẳng: **62 lần hoàn tiền**, có bảng chi tiết từng lần.

### 3. Quản lý nào duyệt hoàn tiền nhiều nhất?
```
Which managers approve the most refunds?
```
✅ AI trả lời thẳng: đứng đầu **Ava Ross — 23 lần**, tiếp theo Amanda Lee (19), Ethan Hill (18)...

### 4. Có refund nào bị trùng giữa các cửa hàng không?
```
Show duplicate refunds across stores.
```
✅ AI trả lời thẳng: **9 giao dịch** bị hoàn tiền ở 2 cửa hàng khác nhau cho cùng một lần mua.

> Câu này từng có lúc AI trả lời sai "không có trùng lặp nào" — đã sửa. Nếu gặp lại câu trả lời
> kiểu "không có gì trùng", nên hỏi lại một lần nữa trước khi tin.

### 5. Sản phẩm nào bị hoàn trả nhiều nhất?
```
Which products are most frequently refunded?
```
⚠️ Câu này có thể ra **số khác nhau giữa các lần hỏi**, vì "nhiều nhất" có thể hiểu là "nhiều lần
bị trả nhất" hoặc "tổng số lượng trả nhiều nhất" — hai cách đều hợp lý nhưng ra kết quả khác nhau
(ví dụ: School Supplies Value Pack đứng đầu theo số lần, nhưng Vitamin C 50 Count đứng đầu theo
số lượng). Nếu AI không hỏi lại mà trả lời luôn, cứ hỏi thêm: *"Ý mình là sản phẩm bị hoàn nhiều
LẦN nhất, không phải tổng số lượng"* để chốt lại đúng ý bạn cần.

### 6. Xem chi tiết hoá đơn một giao dịch cụ thể
```
Show the full receipt and all line items for a selected transaction.
```
✅ AI sẽ hỏi lại **"giao dịch nào?"** — đây là câu hỏi hợp lý vì bạn chưa nói rõ giao dịch nào.
Trả lời bằng mã giao dịch (ví dụ AI có thể đã nhắc tới `TXN-0004917` ở câu trả lời trước, hoặc
bạn hỏi trước "cho xem 5 giao dịch gần nhất" để lấy mã).

### 7. Cửa hàng nào có chênh lệch tồn kho cao nhất?
```
Which stores have the highest inventory variance?
```
✅ AI thường trả lời thẳng: **PH-005 (UnityCare Irving)** đứng đầu.

⚠️ Lưu ý: "chênh lệch" có thể tính theo **số lượng hàng** hoặc theo **giá trị tiền** — hai cách
cho ra **thứ hạng ngược nhau hoàn toàn** (PH-005 đứng đầu nếu tính theo số lượng, nhưng đứng
**chót** nếu tính theo tiền, vì tuy lệch nhiều món nhưng toàn món rẻ). Nếu câu trả lời có vẻ lạ,
hỏi rõ thêm: *"Ý mình là tính theo số tiền thiệt hại, không phải số lượng món hàng"*.

### 8. Sản phẩm nào đang bị âm kho?
```
Which products have negative inventory?
```
✅ Đáp án đúng là **"không có sản phẩm nào"** — đây KHÔNG phải AI trả lời sai hay né tránh.

⚠️ Đôi khi AI sẽ hỏi lại bằng cách liệt kê tên bảng kỹ thuật (nghe rất khó hiểu, kiểu
*"bạn muốn dùng bảng inventory_adjustments hay inventory_snapshots?"*). Nếu gặp câu hỏi ngược
kiểu này, cứ trả lời đơn giản: *"Dùng số liệu tồn kho mới nhất là được"* — AI sẽ tự chọn nguồn
hợp lý.

### 9. Nhân viên nào hay bị thiếu tiền trong két lặp đi lặp lại?
```
Which employee has repeated cash drawer shortages?
```
✅ AI trả lời thẳng: **Robert Reed — 9 lần thiếu tiền**, nhiều nhất trong 58 nhân viên từng bị
thiếu tiền hơn 1 lần.

### 10. Cửa hàng nào có tỷ lệ từ chối bảo hiểm cao nhất?
```
Which store has the highest insurance claim rejection rate?
```
✅ AI trả lời thẳng: **UnityCare Frisco (PH-004)** — tỷ lệ từ chối **15.47%** (41 trên 265 yêu
cầu).

### 11. So sánh doanh số, hoàn tiền, tồn kho và bảo hiểm giữa các cửa hàng
```
Compare store sales, refunds, inventory variance, and claims.
```
⚠️ Câu này **gộp 4 thứ khác nhau cùng lúc** nên AI hay bị quá tải, có thể trả lời không đầy đủ
hoặc yêu cầu bạn chờ. Cách hỏi mượt hơn: **tách thành từng câu nhỏ trong cùng một đoạn chat**,
ví dụ hỏi lần lượt "doanh số từng cửa hàng thế nào?", rồi "còn hoàn tiền thì sao?", rồi "tồn kho
thì sao?", rồi "yêu cầu bảo hiểm thì sao?" — cuối cùng hỏi **"vậy cửa hàng nào đang ổn nhất, cửa
hàng nào đáng lo nhất?"**. AI sẽ tự tổng hợp lại các câu trả lời trước đó và đưa ra nhận định.

> Kỳ vọng: **PH-002 khoẻ nhất** (doanh số cao, hoàn tiền thấp, tồn kho ổn), **PH-005 đáng lo
> nhất** (dù doanh số tốt nhưng lệch tồn kho nặng và yêu cầu bảo hiểm cao nhất).

### 12. Có phát hiện gì bất thường ngoài giờ làm việc hay hoạt động đáng ngờ không?
```
Show all after-hours overrides and sensitive activities.
```
⚠️ Đây là câu **mơ hồ nhất** trong 12 câu — hệ thống không có định nghĩa rõ "ngoài giờ" là mấy
giờ, hay "đáng ngờ" là loại hành động gì, nên AI có thể hỏi lại nhiều lần hoặc thăm dò một lúc
trước khi trả lời. Nếu AI hỏi lại kiểu kỹ thuật (nhắc tên bảng), cứ trả lời bằng ý thường:
*"Ý mình là các lần giảm giá bất thường ngoài giờ hành chính, và các lần hoàn tiền có dấu hiệu
gian lận"* — AI sẽ tự tìm đúng chỗ. Số liệu để đối chiếu: khoảng **162** lần điều chỉnh giá
ngoài giờ (trước 9h sáng hoặc sau 6h chiều), và **232** lần hoàn tiền có gắn cờ cần xem xét.

---

## Tóm tắt nhanh

| # | Trả lời thẳng được? | Ghi chú |
|---|---|---|
| 1 | ✅ | |
| 2 | ✅ | |
| 3 | ✅ | |
| 4 | ✅ | từng có lúc trả lời sai, nên hỏi lại nếu thấy "không có gì" |
| 5 | ⚠️ | có thể ra số khác nhau, nên hỏi rõ "theo số lần" nếu cần |
| 6 | ✅ (hỏi lại hợp lý) | câu hỏi gốc thiếu thông tin, AI hỏi lại là đúng |
| 7 | ✅ | nên hỏi rõ "theo tiền" nếu câu trả lời có vẻ lạ |
| 8 | ✅ | đáp án "không có" là đúng, không phải né tránh |
| 9 | ✅ | |
| 10 | ✅ | |
| 11 | ⚠️ | nên tách hỏi từng phần thay vì hỏi gộp |
| 12 | ⚠️ | câu mơ hồ nhất, cần vài lượt qua lại |

**9/12 câu trả lời thẳng và đáng tin cậy.** 3 câu còn lại (5, 11, 12) không phải AI "dở" — mà vì
bản thân câu hỏi có nhiều cách hiểu hoặc gộp quá nhiều ý, nên cách tốt nhất là hỏi tự nhiên như
đang trò chuyện, nếu câu trả lời có gì chưa hợp lý thì hỏi lại rõ hơn — giống như đang nói chuyện
với một nhân viên mới, không phải như đang ra lệnh cho máy.
