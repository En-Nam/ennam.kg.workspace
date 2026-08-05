# Checkpoint: voice tool-call debugging — 2026-08-03

## What was done
- Chẩn đoán: /constellation (voice) trả lời nông hoặc bịa khi hỏi dữ liệu DAAB. Đo A/B thật qua /api/chat, hội thoại mới, cùng model `gpt-oss-120b`, chỉ khác `mode`: **voice 3/17 hỏng, text 0/6**. Bằng chứng lấy từ bảng `chat_tool_call` (laam-postgres:5500).
- 2 dạng hỏng: (a) dừng sau `kg_list_projects` rồi trả lời bằng đúng các trường có sẵn trong danh sách; (b) **0 tool call + bịa nguyên hồ sơ dự án**. Vòng lặp tool KHÔNG chặn sớm (`DEFAULT_MAX_ROUNDS=25`) — model tự dừng.
- Nguyên nhân phía prompt: `VOICE_GUIDE` ("Ưu tiên ngắn gọn", "KHÔNG đọc ID/UUID") bị model hiểu là chỉ dẫn về mức độ TRA CỨU; các tool đi sâu (`kg_get_master_record`, `kg_search`) bắt buộc nhận `project_id` dạng UUID.
- Nguyên nhân dính-lỗi-trong-hội-thoại: history replay CHỈ có text user/assistant, KHÔNG có tool result (`route.ts` ~L352-387). Có một câu trả lời nông trong lịch sử → lượt sau lặp lại y hệt, kể cả khi đổi sang mode text. Test lại đúng kịch bản: conv nông → hỏi lại ở text vẫn nông; conv bịa → hỏi lại thì phục hồi. Hội thoại MỚI luôn đi sâu.
- Đã sửa 2 việc (TDD, tests đỏ trước):
  1. `lib/agent/context.ts` — neo "ngắn gọn"/"không đọc ID" vào LỜI NÓI RA; chỉ dẫn giữ độ sâu tra cứu đặt trong KHỐI TOOL để đường không-tool (Claude MVS) vẫn sạch từ ngữ tool (có test chặn regression).
  2. `lib/agent/orchestrator.ts` — grounding guard: vòng 0 + 0 tool call + có tool → chèn `GROUNDING_NUDGE`, hỏi lại đúng 1 lần (latch, giống nudge `web_read`). Điều kiện thuần cấu trúc, không phân loại ý định (Rule 5). Nudge có đường thoát nên chitchat không bị ép gọi tool.

## Files changed
- `src/lib/agent/context.ts` + `context.test.ts`
- `src/lib/agent/orchestrator.ts` + `orchestrator.test.ts`
- `src/app/api/chat/route.test.ts` (lượt không-tool nay tốn 3 fetch: round + hỏi lại + completion)
- `CHANGELOG.md` ([Unreleased])

## Current state
- `npx tsc --noEmit` sạch. Toàn bộ suite: 2272 passed, **7 failed đều là lỗi CÓ TỪ TRƯỚC** (ConstellationClient.test.tsx x3, search.test.ts x4 — xác nhận bằng cách stash thay đổi rồi chạy lại). `npm run lint` hỏng sẵn từ trước (`next lint` bị gỡ ở Next 16).
- Đo lại sau sửa (12 lượt voice, chạy trên bản copy dev ở port 3101, KHÔNG đụng server prod 3100 của user): 0 lượt không-gọi-tool; còn 2 lượt nông nhưng ĐỔI DẠNG — model có đi sâu nhưng chọn nhầm tool (`kg_get_node` trên chính id dự án, `laam_query_stats`). Cỡ mẫu chưa đủ để kết luận mức giảm tỉ lệ nông.
- Thay đổi CHƯA commit; server prod :3100 vẫn chạy build CŨ (chưa rebuild/restart).

## Next steps
- Bước tra cứu XÁC ĐỊNH cho câu hỏi "chi tiết về <đối tượng>" (list → get_master_record bằng code qua `seedRequestedTool`) — prompt không sửa được lỗi chọn nhầm tool.
- Chống nhiễm history: replay kèm tool-trace ngắn cho mỗi assistant message.
- Rebuild + restart :3100 để đưa fix vào bản đang dùng.
- Dọn các hội thoại probe do phiên này tạo (~30 conv ngày 2026-08-03, câu "Cho mình thông tin chi tiết project Dasin") — chưa xoá, chờ user xác nhận.

## Blockers / Risks
- Guard tốn thêm 1 vòng model cho MỌI lượt không-gọi-tool (chitchat ~+1.5s). Nếu sau này thấy tốn, thu hẹp điều kiện chứ đừng bỏ latch.
- Không chạy 2 instance Next trong cùng thư mục được (Next 16 khoá thư mục) — verify end-to-end phải dùng bản copy riêng.
