# Checkpoint: claude — 2026-08-04 (Larvis display panel)

## What was done
- Export hội thoại LAAM `98d66697-…` ra md để phân tích: 46 msg, 11 bảng markdown, 4 block ```chart, **9 lượt hỏng** (`Stopped after many tool steps`). Vài lỗi nội dung: "store có rejection rate CAO NHẤT" trả 0%, bảng receipt lệch cột + tổng không khớp, 1 lượt trả nhầm ngữ cảnh câu cũ. User tạm gác phần chất lượng trả lời.
- Brainstorm + chốt thiết kế **Larvis Display Panel** (tách kênh nói khỏi kênh nhìn). Spec: `LAAM/docs/superpowers/specs/2026-08-04-larvis-display-panel-design.md`, commit `9a80ab5` + `ff1441d` trên branch `task/improve-mcp-tool-call-voice`.

## Phát hiện code quan trọng (tiết kiệm rất nhiều việc)
- `src/lib/chat/voice.ts` **đã có parser bảng GFM** (`isTableRow`/`isTableSeparator`/`splitTableCells`) phục vụ `tablesToProse`. Chỉ cần đổi đích đến → descriptor, không viết parser mới.
- Tool result là **object có cấu trúc** (`orchestrator.ts:151-152` stringify sau khi dispatch); `drilldown.ts` đã có helper nhận cả `{text:"<json>"}` (MCP) lẫn object thuần.
- `frames.ts` có sẵn giao thức frame U+001E với tiền lệ `pending_write` / `proactive` = card render riêng, số do code suy ra. Thêm `{t:"view"}` an toàn: cả 2 consumer lọc bằng `if (f.t === …)`, KHÔNG switch vét cạn.
- Cụm dock góc dưới phải (`gpt-oss-120b` + chat + mic) ở `ConstellationClient.tsx:572`, KHÔNG phải `CommandDock.tsx:41` (dòng đó là ô nhập chat, chỉ hiện khi `chatOpen`).

## Quyết định đã chốt với user
- Panel kính **giữa màn hình** (D2, alpha .92), không modal, viền vàng thở theo `useAudioAnalyser`. Không full-height để chừa cung nối tới node agent.
- Nút `×` + `Esc` đóng; click ra ngoài KHÔNG đóng. Đóng → pill `▦ Xem bảng · N` bên trái `<select>` model. **Pill chỉ hiện khi đóng.**
- Panel luôn hiển thị lượt mới nhất (thay thế, không stack).
- Nguồn descriptor: **code suy từ tool result** (ưu tiên), fallback tách markdown model viết. Badge nguồn `DAAB` vs `AI tổng hợp` = ranh giới tin cậy.
- Một lượt chỉ phát **1** frame `view` — chọn `table`/`chart` CUỐI CÙNG (vì `drilldown` list→detail: bước hai mới là thứ user hỏi).

## Current state
- Spec đã commit, chưa có plan, chưa code gì.
- Visual companion còn chạy: `LAAM/.superpowers/brainstorm/68424-1785832284` (port 63221). `.superpowers/` đã trong .gitignore.
- File export hội thoại nằm ở workspace root: `laam-chat-98d66697-michael-pharmacy.md` (untracked, chưa hỏi user muốn để đâu).

## Next steps
- User review spec → `superpowers:writing-plans`.
- Khi viết plan: đọc kỹ thứ tự phát frame ở `route.ts` (backlog có `sse-block-ordering-bug`).
- Thứ tự bắt buộc trong pipeline nói: `extractForSpeech` → chèn câu chỉ dẫn → `splitForSpeech` → TTS. Sai thứ tự thì soft cap 280 ký tự băm bảng rồi đọc to `| PH-005 | 1015 |`.

## Blockers / Risks
- Panel KHÔNG sửa chất lượng trả lời — 9/21 lượt rỗng vẫn còn nguyên (xem `checkpoint/voice-tool-grounding-2026-08-03`, `backlog/daab-agent-context-project-resolution-bug`).
- Branch `task/improve-mcp-tool-call-voice` có fix voice-grounding từ 2026-08-03 **chưa rebuild/restart** ở server prod :3100.
