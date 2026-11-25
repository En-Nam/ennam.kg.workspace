# Thiết kế: làm mới User guide và đưa ra cấp Portal

Ngày: 2026-11-25. Nhánh: `task/improve_by_feedback_19112026` (LAAM). Người quyết định: chủ dự án.

## Vì sao
- Trang hướng dẫn `/guide` được viết trước card #4, #5, #6. Nhiều màn hình và luồng đã đổi: Portal, nút "Take action", Review items, workflow chạy từ cảnh báo, email nhắc việc, bộ công cụ, tiếng Anh/Việt theo cookie.
- Người dùng mới vào từ Portal (AIO Analytics), nhưng hướng dẫn chỉ mở được từ bên trong LAAM.

## Mục tiêu
- Đi từng chức năng LAAM trên local (`localhost:3900`) bằng Chrome DevTools. Sửa nội dung cho khớp đúng màn hình hiện tại: nhãn nút, các bước, ai thấy gì.
- Chụp lại mọi ảnh đã đổi, và thêm ảnh cho chức năng mới.
- Đưa `/guide` ra cấp Portal. Trên trang Portal có link "User guide".

## Không làm
- Phần DAAB: để đợt sau. Cấu trúc chừa sẵn chỗ cho chương DAAB.
- Không bản tiếng Việt.

## Quyết định đã chốt (chủ dự án, 2026-11-25)
1. **Vị trí:** `/guide` dùng header của Portal (AIO Analytics, không có menu LAAM) và thanh dưới AIO.
   - Trang Portal có link "User guide".
   - Menu "Guide" của LAAM và Settings vẫn trỏ tới `/guide`. Người không có DAAB không bao giờ thấy Portal, nhưng vẫn vào được hướng dẫn từ LAAM.
2. **Nội dung:** cấp AIO. Gồm "Getting started" (đăng nhập, Portal, chuyển giữa LAAM và DAAB), các chương LAAM, và chương Help. Chương DAAB thêm sau.
3. **Ngôn ngữ:** chỉ tiếng Anh. Ảnh chụp từ giao diện tiếng Anh, toàn bộ chữ trên ảnh là tiếng Anh, kể cả dữ liệu demo hiện trên màn hình.

## Cách làm
- **Dữ liệu và tài khoản:** org "Pharmacy T-log Demo Co" trên local, đã đồng bộ với prod.
  - Owner: John Smith.
  - Admin: Admin T-log.
  - Member: Member T-log, chỉ PH-001.
  - Ảnh của mục dành cho admin chụp bằng Owner hoặc Admin. Ảnh "ai thấy gì" chụp thêm bằng Member.
- **Đi theo thứ tự chương**, mỗi mục làm 3 việc:
  1. Đối chiếu chữ và các bước với màn hình thật.
  2. Sửa `src/lib/guide/content.ts`.
  3. Chụp lại ảnh `public/guide/*.webp`: rộng 1280, đúng tỉ lệ khai báo, có test kiểm.
- **Chức năng mới cần mục riêng:**
  - Portal.
  - Take action trên cảnh báo.
  - Review items và hành động hàng loạt.
  - Workflow chạy từ cảnh báo (xem trước rồi gửi).
  - Nhắc việc và email.
  - Bật/tắt hành động theo dự án.
  - Bộ công cụ: tạo từ template, giao, onboarding.
- **Kiểm tra:**
  - `content.test.ts` đạt: ảnh tồn tại, đúng kích thước, có alt.
  - `tsc` và `npm run build` đạt.
  - Mở `/guide` trên trình duyệt từ Portal và từ LAAM.

## Phần để người làm tự quyết
- Thứ tự mục trong mỗi chương, chữ của link trên Portal, và ảnh nào cần chụp lại.
- Theo nguyên tắc: chỉ chụp lại khi màn hình đã khác.
