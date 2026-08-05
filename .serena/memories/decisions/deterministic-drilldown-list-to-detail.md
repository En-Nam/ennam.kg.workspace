# Quyết định: bước tra cứu XÁC ĐỊNH "liệt kê → chi tiết" (D2)

## Bối cảnh
Model chat (`gpt-oss-120b`) được đưa **60 tool** cùng lúc (12 LAAM + 48 DAAB qua MCP). Với câu hỏi
"chi tiết về <đối tượng>" — cần 2 bước (liệt kê lấy id → đọc bản ghi chi tiết) — model làm bước 2
không ổn định: đo được cả kiểu dừng luôn sau tool liệt kê lẫn kiểu gọi sai tool (`laam_query_stats`
cho câu hỏi về dự án). Sửa prompt (xem `mem:checkpoint/voice-tool-grounding-2026-08-03`) đẩy được model
đi tiếp nhưng KHÔNG dạy được nó đi đúng chỗ.

## Quyết định
Bước 2 do CODE quyết, không để model chọn (Rule 5). `lib/agent/drilldown.ts`:
- Sau khi tool `listTool` chạy xong, tìm mảng entity trong kết quả (tự dò khoá, đọc được cả shape MCP
  `{text: "<json>"}`), so khớp `nameField` với câu hỏi của user.
- Khớp đúng một tên → code tự dispatch `detailTool` với `{ [idArg]: id }`, append vào convo đúng shape
  tool-turn (assistant tool_call + tool result) để trace/citation nhìn thấy như tool bình thường.

## Vì sao trigger là "khớp tên từ dữ liệu tool", không phải "dò ý định"
Dò ý định "chi tiết về X" bằng regex tiếng Việt/Anh dễ vỡ và dễ bắt nhầm sang miền khác. Khớp tên lấy
từ CHÍNH kết quả tool là tập đóng, do code lấy được (Rule 13). Hệ quả tốt: câu "liệt kê…" không nhắc
tên nào → không kéo thêm lượt nào (đã đo 2/2).

## Ràng buộc user đặt ra
**Không hardcode DAAB trong LAAM** — DAAB chỉ là connector MCP cắm từ ngoài vào. Cặp tool khai báo ở
env `TOOL_DRILLDOWN_PAIRS` (mẫu trong `.env.example`); không đặt env ⇒ tính năng tắt, tool-loop y như cũ.

## Biên đã chốt (có test)
- mơ hồ (hai tên khớp dài bằng nhau) → bỏ qua, không đoán
- tên < 3 ký tự → bỏ qua (khớp bừa vào chữ bất kỳ)
- tối đa 1 lần/lượt (model gọi lại tool liệt kê cũng không kéo thêm)
- tool chi tiết lỗi → fail-soft, lượt vẫn trả lời bằng dữ liệu liệt kê; riêng `PendingWriteSignal` ném ra
  ngoài để route suspend (cấu hình nhầm sang tool ghi phải nổ, không im lặng)

## Kết quả đo (production build, 2026-08-03)
12/12 lượt voice hỏi chi tiết → `kg_list_projects → kg_get_master_record`, câu trả lời 2.0–4.1k ký tự
(các lượt hỏng trước chỉ ~200–400). 2/2 lượt "liệt kê" giữ nguyên 1 tool.

## Việc còn bỏ ngỏ
- 60 tool trong một lượt vẫn là gốc rễ của lớp lỗi chọn nhầm tool — mới chỉ vá cho một dạng câu hỏi.
  Hướng tiếp: thu hẹp action space theo lượt/nhóm (đã đề xuất, user chưa chọn).
- History replay vẫn không có tool-trace → một câu trả lời nông cũ trong hội thoại vẫn có thể tự lặp lại.
