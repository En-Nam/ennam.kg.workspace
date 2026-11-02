# Checkpoint: claude-intel-pos-followups — 2026-11-02

## Đã làm
- Heatmap Home lấy metric từ pack (`<pack>/laam/heatmap.yaml`), packs 0.6.0, nhãn từ glossary (+ term override_rate); dọn lỗi nhỏ drawer/media/heatmap/DAAB. Test chập chờn: 6 lần không tái hiện → không sửa mù.
- Fix thêm (nhánh fix/pack-parent-versions-fifo, merge vào task/LAAM/improve 2d6c7902):
  - `loadPacksStable` so snapshot (key + version) của MỌI pack sau khi giải extends (cả pack cha); tập key đổi hoặc resolveOrder lỗi → coi là "moved", retry 1 lần. Test đổi retail giữa lúc chỉ bật pharmacy: code cũ trả base@0.1.0 + BASE-NEW-001 (trộn), code mới đúng.
  - Test FIFO có `finally` mở O_WRONLY|O_NONBLOCK để nhả reader bị chặn (phòng ngừa; không tái hiện được treo).
- Merge local (chưa push): packs 978e46b + go 04cb7c9 vào task/DAAB/improve; LAAM 2d6c7902 vào task/LAAM/improve.

## Trạng thái
- LAAM tsc sạch, unit 7770, lint 0 lỗi; packs 40/0; go 40 pkg ok. Local stack: laam-v2-app + daab-server rebuild, packs 0.6.0.

## Next
- Kiểm tay trình duyệt (heatmap + chip claim_rejection_rate, drawer focus, video).
- Push các nhánh task/* khi user đồng ý; publish packs 0.6.0 qua `_scripts/release.sh`.

## Rollout packs 0.6.0
- Cập nhật packs trước LAAM hoặc restart LAAM sau; LAAM mới + packs 0.5.0 → heatmap ẩn. Restart DAAB sau khi đổi packs.

## Phiên chiều 2026-11-02 (LAAM, merge vào task/LAAM/improve rồi push)
- Dữ liệu demo pharmacy được dời +91 ngày, as-of 2026-10-30 (`refresh_demo.sh` + `cutover.sh` part1-3), check-expected-findings đạt 9/9. Bản sao lưu: `.superpowers/backups/*_precutover_20261102T132159.dump`. Seed `PHARMACY_AS_OF` = 2026-10-30.
- Media demo được gắn lại cho REF-000037 / REF-000047 / REF-000001, giờ quay dời theo dữ liệu (`LAAM/media/manifest.json`, không có trong git).
- Lần dời dữ liệu sau: clip phải nằm trong khoảng bằng chứng của các finding (01–31/10) và `capturedAt` phải dời theo.
- Ngăn hoá đơn trình bày lại như một hoá đơn: phần một dòng dạng nhãn/giá trị, dòng hàng hiện như hoá đơn in, ô tóm tắt kèm chip cảnh báo, rộng max-w-3xl. Module mới `receipt-format.ts`.
- Heatmap: bỏ ngưỡng `sampleSize >= 5`. Với metric tỉ lệ, DAAB đếm sample bằng sự kiện ở tử số, nên ngưỡng này làm mất các ngày 0%. Giờ chỉ coi là không có dữ liệu khi mẫu số ≤ 0. Trung vị ≤ 0 thì độ đậm tính theo max của dòng. Spec lên rev 5.
- Home: heatmap nằm ngay sau "Cần chú ý". Cột aside sticky được bọc trong `.asideCol` chiếm row 1, vì nếu không nó đè lên heatmap.
- Chip chọn metric dùng `scroll={false}` + `replace`, có marker pending ẩn để làm mờ lưới. Không còn chấm.
- Chrome crash khi bấm fullscreen video là lỗi của AppKit/SkyLight (macOS 27.0.1 + Chrome 156), không phải do app. Chưa thêm `nofullscreen` (user chưa quyết).
- Còn mở: viền finding phủ cả dải của PH-001 (việc số 3); heatmap có thể tách API riêng nếu đổi metric còn chậm.

## Ghi chú
- Pack hỏng thật (cycle/YAML sai ở pack.yaml) giờ chờ thêm 250 ms trước khi báo lỗi (do retry); chấp nhận được.
