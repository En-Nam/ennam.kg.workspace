# QA: selection-at-scale @ prod scale — 2026-08-03 — KẾT LUẬN CUỐI, ĐẦY ĐỦ

## ⚠️ "read→write trong 1 lượt = 0% tuyệt đối" — ĐÃ SỬA, phần lớn không phải bug
3 probe `multi-read-write`/`ctx-audit-write`/`ctx-web-write` dùng `trello_create_card` (yêu cầu
`idList`, `trello.ts:139`) nhưng câu hỏi không cho biết list nào — model đúng ra hỏi lại thay vì
bịa ID (Rule 13), không phải hỏng. Đã sửa cả 3 probe trong `suite.scale.eval.ts`. Xác nhận trong
suite thật, k=8, mốc 60: `multi-read-write` 8/8, `ctx-audit-write` 8/8. `ctx-web-write` vẫn 0/8 —
nguyên nhân KHÁC: model kẹt ở bước ĐỌC vì stub `web_search` trả kết quả rõ ràng giả, tìm lại liên
tục (~17 vòng), có lúc tự bịa URL Reuters để `web_read` (vi phạm Rule 13). Vấn đề của stub, không
phải orchestrator. BÀI HỌC: 0% "quá sạch" nên nghi probe trước khi tin là bug — soi trace trước.

## ⚠️ "Final-completion trả rỗng cho user" — ĐÃ ĐIỀU TRA, KHÔNG PHẢI LEAD MỚI
`byteplusStream` không có tham số `tools` (`lib/llm/byteplus.ts:242-247`), và đã xác nhận qua
trace: model vẫn có thể tự sinh `tool_calls` ở đúng bước này, khiến generator không yield gì. NHƯNG
đọc `route.ts` phát hiện production ĐÃ CÓ 3 lớp phòng thủ cho đúng hiện tượng này (do team trước
tự quan sát production, comment ghi rõ nguyên nhân + đã xác nhận bằng tay): (1) SYNTH_NUDGE khi
hitBackstop, (2) retry 1 lần kèm SYNTH_NUDGE khi hoàn tất đầu rỗng, (3) EMPTY_REPLY fail-loud nếu
retry cũng rỗng. Cơ chế ĐÚNG nhưng KHÔNG có test — đã thêm 2 test D2b vào `route.test.ts` (xác
nhận đỏ khi tắt thử retry, xanh khi khôi phục). KHÔNG có thay đổi hành vi, chỉ thêm test.
Đây là bài học thứ 2 trong đợt này: đọc code hiện có TRƯỚC khi báo "phát hiện mới".

## KẾT LUẬN CHÍNH (đứng vững qua toàn bộ investigation) — 3 probe history-poisoning đều có bằng chứng THẬT
mcp-detail-voice, mcp-detail-poisoned, mcp-detail-poisoned-switch-to-text: đều 16/16 (k=16, mốc
60), P(kết quả này nếu tỉ lệ hỏng thật vẫn 17,6%) chỉ 4,5%/probe. Không dùng drilldown (fix #2)
— model tự chọn đúng nhờ fix #1 (prompt) + fix #4 (grounding guard). Investigation khép.

## Kết quả 1 — số lượng tool KHÔNG làm giảm độ chính xác chọn tool (xác nhận nhiều lần chạy)
Mọi probe không-phải-detail: 100% phẳng từ 4→60 tool. "Thu hẹp action space" KHÔNG có dữ liệu
ủng hộ về độ chính xác với model này. Vẫn đáng làm vì CHI PHÍ (5 975 token/round ở 60 tool).

## Việc còn lại — KHÔNG còn phát hiện "nghiêm trọng chưa giải quyết" nào từ toàn bộ đợt eval
1. `ctx-web-write`: sửa stub cho thực tế hơn (không cấp thiết, không phải bug thật).
2. Thu hẹp action space — lý do chi phí, làm khi cần tiết kiệm token, không phải để sửa lỗi.
3. Mọi lead khác đã điều tra và đóng (hoặc xác nhận không phải bug, hoặc đã có test bảo vệ).
