# Checkpoint: claude-intel-pos-demo — 2026-11-01

## Đã làm
- Từ recap meeting 27/10 (pilot POS bán lẻ): spec + plan cho 3 tính năng LAAM Intel — heatmap cửa hàng × ngày, ngăn hoá đơn từ evidence (tool DAAB mới `kg_get_record`), video minh hoạ gắn hoá đơn (prototype).
- Chạy subagent-driven: Sonnet làm 10 task, Opus review từng task (tối đa 3 vòng) + review cuối toàn nhánh; 4 cảnh báo bảo mật tự động đều đã xử lý (sale_id trùng giữa cửa hàng, khoá cache heatmap, section cha trùng, membership không ràng entity).
- Merge local (chưa push): ennam.kg.go `task/DAAB/improve` 3dfdd97; LAAM `task/LAAM/improve` 80184932; repo gốc commit 6709e6b (master plan §2.5 getRecord).

## Files
- Spec: LAAM/docs/superpowers/specs/2026-11-01-intel-pos-demo-heatmap-receipt-video-design.md (rev 3)
- Plan: LAAM/docs/superpowers/plans/2026-11-01-intel-pos-demo-heatmap-receipt-video.md
- DAAB: internal/intel/engine/record.go, handler/intel_metrics.go, bridge schema/client, middleware scoped_routes + ReadOnlyPOSTPaths
- LAAM: lib/intel/home/heatmap.ts, load.ts, StoreHeatmap.tsx; provider types/daab/scoped/retry/chunked/fake getRecord; lib/intel/records.ts + records route; ReceiptDrawer, cell-text.ts; evidence_media (migration 0043), media.ts, media-manifest.ts, scripts/seed-demo-media.ts, api/intel/media/[id], range.ts, EvidenceVideo.tsx

## Trạng thái
- Go 40 pkg pass; LAAM tsc sạch, unit 7733, int/isolation 510+, lint 0 lỗi.
- Dev stack: daab-server + daab-bridge rebuild từ nhánh này; kg_get_record chạy thật (REF-000037 OK, scope lạ → found:false). LAAM image rebuild (image cũ tag `laam-app:pre-intel-pos-demo`), migration 0043 đã chạy trên DB dev, seed 3 clip giả (LAAM/media, gitignored) cho REF-000037/000042/000180.
- CHƯA kiểm trên trình duyệt (Chrome extension không kết nối).

## Next
- Kiểm tay trên trình duyệt: heatmap /home (sáng/tối), mở hoá đơn refund Sarah Miller + 9 refund trùng, video phát/tua, đồng hồ khớp giờ refund, user 1 cửa hàng.
- Push 2 nhánh task/* khi user đồng ý.
- Hỏi Huy/Phoebe: nguồn video thật (VMS hay upload), có cột quầy/register không, cần heatmap theo giờ không.

## Rủi ro
- 1 test unit chập chờn chưa rõ nguyên nhân (thấy 1 lần khi làm C2).
- Minor đã chấp nhận ship: không focus trap trong drawer, TOCTOU nhỏ ở route media, memo heatmap không TTL.
