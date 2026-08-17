# Checkpoint: claude (workflow AI-gen ↔ MCP) — 2026-08-11

## Round 1 — MCP catalog vô hình với AI generation (ĐÃ SHIP, chưa commit)
`generate.ts` thiếu `"mcp"` trong `KINDS`/`GRAPH_FORMAT`/`coerceNode` → model trả kind:"mcp"
bị hạ thành `agent`, mất server/tool/args. `generate/route.ts` chỉ fetch connector OAuth
(`list()`), chưa gọi `listServers`/`discoverForUser` → user chỉ có DAAB nhận
`"(no connectors connected)"`. Sửa cả hai, +5 test.

## Round 2 — L1: mcp output shape (ĐÃ SHIP, chưa commit)
Dry-run thật: `interpolation: missing path "steps.query.output.query_id"`. Mọi node mcp trả
`{text: string}` (mcp/client.ts `callTool` gộp text block). Thêm `mcpOutputMisuseOf` vào
validate.ts, wire vào `assertRunnable` + `assertRunnableDag`. +6 test. 390/390 pass.

## Round 3 — Lỗi thứ 2 + spec + plan GĐ 1 (TÀI LIỆU, CHƯA CODE)
Sau L1, model tự thêm agent trích field nhưng khai `format {query_id}` trong khi field thật
là `id` (mô tả tool viết "id: query_id returned by..." → query_id là NGHĨA không phải TÊN).
Lớp lỗi gốc: **model đoán mù, chưa bao giờ gọi tool thật**.

**6 lỗ hổng tìm được khi tự rà design, gồm 1 lỗi sự thật của chính tôi** — đáng nhớ:
- H1: tôi khẳng định generate route có `requireMutator` — SAI, chỉ có `auth()`.
- H2: "lấy shape từ lịch sử hội thoại" KHÔNG chạy được — `ChatMessage` (orchestrator.ts:15)
  không mang tên tool trên message `role:"tool"`; kết quả bị `annotateEmptyResult`/
  `annotatePanelShown` bọc; repeat-detect (:312) + drilldown (:374) chèn message lệch nhịp.
  → **phải ghi (name,args,result) tại thời điểm dispatch**.
- H3: chưa nghĩ thread sống ở đâu giữa các lượt → chốt: giữ trong browser, không lưu DB.
- H4: chat chạy được KHÔNG chứng minh graph chạy được (chat có LLM giữa mỗi bước; graph dùng
  nội suy tĩnh + extractor agent — đúng mối nối đã hỏng 2 lần).
- H5: auto dry-run bị chặn bởi `workflow_run.workflowId notNull().references()`
  (schema.ts:418) → không chạy được graph chưa lưu; + mỗi agent node = 1 lần gọi model;
  + `kg_query_datasource` nhãn "read" nhưng TẠO ROW thật. → loại auto, để user bấm.
- H6: quên i18n vi/en/zh.
Bỏ tool `workflow_ready` tôi tự bịa (user ngồi đó, bấm nút là được — Rule 2).

**Chốt kiến trúc:** L1 thuần graph → ở lại `assertRunnable`. **L2 cần dữ liệu quan sát →
PHẢI tách riêng**, vì `assertRunnable` còn gác Save (`api/workflows/route.ts:17`,
`[id]/route.ts:53`) nơi không có quan sát → nhét vào sẽ vỡ Save. Plan đặt L2 ở **file riêng**
`extractGuard.ts` (sai lệch có chủ ý so với spec §5.3) để ràng buộc này là VẬT LÝ.

**L2 luật ba vế** (tránh chặn oan ca đổi tên hợp lệ): chặn ⟺ có quan sát ∧ `claimed ∩ real = ∅`
∧ prompt không nhắc tên nào trong `real`.

## Files changed
- ĐÃ SHIP (chưa commit): `src/lib/workflow/generate.ts`, `src/app/api/workflows/generate/route.ts`,
  `src/lib/workflow/validate.ts` + 3 file test
- MỚI: `docs/superpowers/specs/2026-08-11-workflow-generate-tool-grounded.md`
- MỚI: `docs/superpowers/plans/2026-08-11-workflow-generate-tool-grounded.md` (5 task TDD)

## Current state
- 390/390 test pass, tsc clean. **Chưa commit gì** (repo dirty sẵn từ phiên trước).
- Workflow `743c1336…` của user VẪN HỎNG — `assertRunnable` chỉ gác Save, không gác `/run`.
- GĐ 1 mới là spec + plan, **chưa implement dòng code nào**.

## Next steps
- Chạy plan Task 1→5. Task 5 là kiểm chứng bằng model THẬT (test tự động dùng model giả,
  không chứng minh được model hết đoán sai).
- GĐ 2 (panel chat nhiều lượt) chỉ làm sau khi Task 5 cho thấy GĐ 1 chưa đủ.

## Blockers / Risks
- Không có blocker. Rủi ro triển khai ghi trong plan (mục "Rủi ro cần theo dõi").
