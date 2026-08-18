# Checkpoint: claude — 2026-08-17 (vá time-window cho NL→SQL, DAAB)

## Vấn đề
Câu hỏi có cửa sổ thời gian ("trong vòng 48 giờ") không chạy được — cả một lớp câu hỏi phát hiện
gian lận, đúng thứ demo Michael Pharmacy Chain cần (Q16 = FND-007).
Planner sinh NGẪU NHIÊN một trong hai dạng, và **cả hai đều hỏng ở hai tầng khác nhau**:

| Dạng | Hỏng ở | Triệu chứng |
|---|---|---|
| `EXTRACT(EPOCH FROM a - b)` | `plan_harden.go` | `EXTRACT` không có trong `aggFuncRE`, `EPOCH` là từ trần → "unknown column(s) EPOCH" → trả về clarification |
| `col + interval '48 hours'` | `sql_generator.go` | Đường dự phòng chỉ nhận `bảng.cột` → bind thành `$N` → Postgres: "invalid input syntax for type timestamp" |

## Gốc rễ
Plan có sẵn cờ `ValueIsExpression` (models/ai_query.go:210) để ghép thẳng biểu thức, nhưng
**model không bật cờ**. `d46a38e` (08-17, của DAAB team) vá được nửa đơn giản: regex nhận
giá trị đúng dạng `ident.ident` → ghép thẳng. Biểu thức thì cố ý không nhận (comment nói rõ:
tránh inline text tuỳ ý = SQL injection).

**Nhận định làm nền cho bản vá:** `ValueIsExpression` khi bật thì ghép thẳng **không kiểm tra gì**
(`fmt.Sprintf("%s %s (%s)")`). Nên hệ thống ĐÃ chấp nhận inline biểu thức do AI sinh; regex chặt
chỉ để phân biệt "cột model quên đánh dấu" với "literal người dùng". ⇒ Nới đường dự phòng theo
một **ngữ pháp đóng** không mở thêm loại rủi ro mới.

## Đã làm (TDD, test viết trước, RED xác nhận)
1. **`sql_generator.go`** — thêm `columnIntervalPattern`:
   `^ident.ident \s*[+-]\s* INTERVAL '<chỉ gồm số + từ đơn vị>'$`, gate bằng CÙNG check
   `colRefPrefixes` (prefix phải là bảng/alias của plan). Thân interval không thể chứa nháy,
   ngoặc, chấm phẩy, comment → look-alike vẫn đi qua `$N`.
2. **`plan_harden.go`** — thêm `sqlTimeUnitRE` (xoá `<UNIT> FROM` của EXTRACT — xoá cả FROM,
   nếu không sẽ còn FROM lơ lửng) và `sqlIntervalKeywordRE` (xoá từ khoá INTERVAL). Đặt SAU
   `sqlStringLitRE` (thân interval đã bị xoá) và TRƯỚC khi quét identifier. Chỉ xoá TỪ KHOÁ —
   toán hạng vẫn được kiểm tra.

**Test thêm 4:**
- `TestGenerate_ColumnPlusIntervalIsEmittedAsExpression` — tái hiện đúng lỗi thật
- `TestGenerate_IntervalLookalikesStayParameterized` — 3 ca: prefix lạ, thân interval chứa
  `'); DROP TABLE receipts--`, và `now()`. Có assert cứng `!strings.Contains(sql,"DROP TABLE")`
- `TestValidatePlanColumns_AllowsExtractEpochAndInterval` — 3 fragment
- `TestValidatePlanColumns_StillCatchesUnknownColumnInsideExtract` — **chốt rằng nới lỏng
  không làm mù validator**

`go build ./...` sạch · `go test ./...` **22/22 package pass**.

## Verify chạy thật (sau rebuild + clear plan cache)
Chính câu trước đây fail:
> "…count the reprints for which the refund_datetime falls between the printed_datetime and
> 48 hours after it. Group by the employee who printed…"

→ SQL sinh ra:
```sql
WHERE r.print_type = $1
  AND rf.refund_datetime >= r.printed_datetime                        -- d46a38e
  AND rf.refund_datetime <= r.printed_datetime + interval '48 hours'  -- bản vá này
```
→ Kết quả: **EMP-0006 = 40**, đúng MỘT dòng. Khớp tuyệt đối answer key FND-007 ("40 matched
pairs") và ground truth SQL trực tiếp. Đây là câu trả lời gọn mà DAAB trước đó KHÔNG tạo được.

## Trạng thái
- `ennam.kg.go` **CHƯA COMMIT**: `sql_generator.go`, `plan_harden.go`, 2 file test,
  + `value_hints.go` (cap 120→200) từ trước đó.
- kg-server đã rebuild lần 3 và đang chạy bản này.
- **Plan cache vừa bị xoá sạch (10 dòng) — CẦN WARM LẠI trước demo** (chạy Q13,14,15,16,17
  + câu thay thế Q17 tiếng Việt, verify từng câu).

## Còn tồn
- Nguyên nhân gốc vẫn là model không bật `value_is_expression`. Hai bản vá này là lưới hứng ở
  tầng dưới, deterministic. Fix tận gốc = sửa prompt planner (nhưng LLM phi tất định, xem
  `mem:decisions/daab-nl-planner-nondeterminism`) ⇒ nên giữ CẢ HAI lớp.
- Q17 nguyên văn vẫn hỏng 4/4 (tautology) — không liên quan bản vá này.
