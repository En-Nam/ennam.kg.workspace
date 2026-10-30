# Checkpoint: claude-daab-aaaa-connector-doc — 2026-10-30

## What was done
- Review cơ chế kết nối AAAA ↔ DAAB (Source Connection / pull connector) trên cả 4 repo: `am-ai-agents`, `ennam.kg.go`, `ennam.kg.python`, `ennam.kg.next`.
- Verify 4 câu hỏi trọng tâm bằng source (không suy đoán): có auto-sync sau connect không, webhook_secret có route nào dùng không, analyze có chạy sau sync không, auto-sync có bị defer theo spec không.
- Viết tài liệu tích hợp tiếng Việt cho hệ thống bên thứ ba.

## Files changed
- MỚI: `docs/integration/source-connection-pull-integration.md`
- MỚI (Serena): `decisions/aaaa-daab-source-connection-triggers`

## Current state
- Tài liệu hoàn chỉnh: 3 hướng tích hợp, sequence diagram, contract snake_case phía nguồn, trigger matrix có bằng chứng file:line, cách thêm nguồn pull mới, 3 phương án auto-trigger, checklist debug.
- Chưa implement bất kỳ fix nào — đúng scope user yêu cầu (review + viết doc).
- Chưa commit (worktree có sẵn nhiều file dirty không liên quan).

## Next steps
- Nếu owner duyệt: implement #1 (sync-on-connect, ~5 dòng FE) + #2 (scheduler phía Go cạnh `internal/jobengine/`).
- Cân nhắc validate UUID cho ô AAAA PROJECT ID + `autoComplete="new-password"` cho ô token trong `aaaa-connect-dialog.tsx`.
- Follow-up bảo mật: AAAA `verifyKey` không scope theo project — một key đọc được mọi project.

## Blockers / Risks
- Giá trị `config.aaaa_project_id` của connection đang chạy trên prod CHƯA được xác minh (screenshot có dấu hiệu Chrome autofill). Cần `GET /connections` để chắc.
- Auto-sync là non-goal đã chốt trong spec (`2026-07-15-daab-doc-sync-planA...:162`) — thay đổi cần owner đồng ý, không phải fix bug.
