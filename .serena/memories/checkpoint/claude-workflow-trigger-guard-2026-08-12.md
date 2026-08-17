# Checkpoint: claude — 2026-08-12 (L3 bare-{{trigger}} guard)

## Bối cảnh
GĐ 1 (probe + shape hints + L2) do user triển khai đã CHẠY ĐÚNG: node extract giờ dùng đúng
tên field thật `id` thay vì `query_id`. Nhưng chạy thử lộ lỗi MỚI khác lớp:
`natural_language_query = {{trigger}}` → MCP báo `expected string, got object`.

## Nguyên nhân gốc — lỗi ở PROMPT của chính chúng ta
`generate.ts:78` (cũ) dạy model: *"...and the trigger payload with {{trigger}}"* — quảng cáo một
tính năng KHÔNG tồn tại. Sole-token trong arg giữ nguyên KIỂU (interpolate.ts:38), mà
`RunContext.trigger` luôn là object → truyền object vào tham số string.
`templates.ts:120` ĐÃ có comment cảnh báo đúng điều này từ trước, nhưng kiến thức chưa bao giờ
lan sang 2 chỗ thực sự phát `{{trigger}}` ra ngoài: prompt cho model + `variableHints.ts:36`
(gợi ý đầu tiên trong editor cho NGƯỜI DÙNG). Cùng kiểu thất bại lan-truyền như Round 1 (mcp
kind vào editor nhưng không vào generate).

## LỖI TÔI TỰ GÂY RA VÀ TỰ BẮT — đáng nhớ nhất
Bản L3 đầu tiên chặn MỌI `{{trigger...}}` trừ `{{trigger.source}}`, lý lẽ: `run.ts:158` là chỗ
DUY NHẤT tạo RunContext và luôn truyền `{source}`. **Sai — làm quá tay.** 2 test engine đỏ ngay
và chúng chính là bằng chứng: `engine.test.ts` chạy foreach trên `{{trigger.items}}` với
`emptyContext({items:[1,2,3]})` — ENGINE THẬT SỰ hỗ trợ trigger payload. Và `engine.ts:363`
`runWorkflow` gọi `assertRunnable`, nên luật đó cấm luôn một năng lực đang có + chặn trước mọi
webhook trigger tương lai.
→ **Bài học: "hôm nay production không truyền X" là sự thật SẢN PHẨM, không được đóng băng vào
validator (tầng engine). Chỉ đóng băng thứ chứng minh được là hỏng.**

## Luật cuối (đã thu hẹp)
Chặn **bare `{{trigger}}`** chỉ trong trường sink **"arg"** (connector/mcp args, condition.when,
foreach.items) — đệ quy vào foreach body. KHÔNG chặn:
- `{{trigger.<field>}}` — engine hỗ trợ thật.
- bare `{{trigger}}` trong `agent.prompt` — sink "text" nên JSON.stringify, vô dụng nhưng KHÔNG hỏng.
Phân biệt arg/text sink là khái niệm SẴN CÓ của codebase (interpolate.ts), không phải luật bịa mới.
Phần "hôm nay không có trigger payload" chuyển sang dạy trong prompt generate.

## Files changed
- `src/lib/workflow/validate.ts` — `triggerMisuseOf` + `assertNoTriggerMisuse`, wire vào CẢ HAI
  nhánh `assertRunnable` / `assertRunnableDag`.
- `src/lib/workflow/validate.test.ts` — +7 test L3 (gồm 2 test "NOT rejected" khoá đúng 2 năng
  lực mà bản quá tay đã phá); sửa fixture 1 test L1 cũ (dùng `{{trigger.list}}` làm dữ liệu độn
  → đổi sang `{{steps.m1.output.text}}` để test vẫn kiểm đúng thứ nó mang tên).
- `src/lib/workflow/generate.ts` — bỏ quảng cáo "trigger payload"; dạy: không có đầu vào, hằng số
  phải viết literal, chỉ có `{{trigger.source}}`.
- `src/components/workflows/editor/variableHints.ts` — gợi ý `{{trigger.source}}` thay `{{trigger}}`.
- `variableHints.test.ts`, `NodeConfigPanel.test.tsx` — cập nhật kỳ vọng theo gợi ý mới.

## Current state
- `npx vitest run` toàn repo: **2666 pass / 7 fail**. tsc sạch.
- 7 fail đó là **CÓ SẴN TỪ TRƯỚC, không phải do thay đổi này** — đã chứng minh bằng
  `git stash` rồi chạy lại baseline: y hệt 7 fail. Nằm ở `src/lib/search.test.ts` (4) và
  `src/components/constellation/ConstellationClient.test.tsx` (3), không import gì đã sửa.
  **Cần điều tra riêng, không thuộc phạm vi này.**
- Chưa commit (working tree có 6 file sửa + `.spectex/` untracked).

## Next steps
- Sinh lại workflow bằng ✨ và chạy thử: kỳ vọng `natural_language_query` là chuỗi literal
  ("Top 5 employees…") thay vì `{{trigger}}`; nếu model vẫn ra `{{trigger}}` thì L3 sẽ chặn +
  đưa lỗi ngược cho vòng self-repair.
- Điều tra 7 test đỏ có sẵn (search scoping + constellation) — riêng biệt.
- Quan sát: graph sinh ra có 2 chuỗi truy vấn lặp (q1→extract1→status1, q2→extract2→status2) —
  nếu 2 câu hỏi trùng nhau thì đang tốn gấp đôi; chưa điều tra.

## Blockers / Risks
- Không có blocker.
