# Hướng dẫn test và sử dụng — DAAB + LAAM Proactive Intelligence (Pharmacy/Retail)

**Ngày:** 2026-10-05
**Liên quan:** `docs/superpowers/test-results/2026-10-05-beta-completion-report.md`, `docs/superpowers/runbooks/2026-10-02-real-customer-data-onboarding.md`

## 1. Các địa chỉ và tài khoản

| Thứ | Địa chỉ | Dùng để |
|---|---|---|
| LAAM (đã triển khai) | `http://localhost:3900` | Màn hình Home chủ động |
| DAAB dashboard | `http://localhost:3500` | Xem dữ liệu, schema, nguồn dữ liệu |
| DAAB API | `http://localhost:8082` | API của DAAB |

Tài khoản demo, mật khẩu `Dev123!@#`:
- `johnny@demo.local`: vai **executive**, xem toàn chuỗi 5 cửa hàng.
- `ph002.manager@demo.local`: vai **store_manager**, chỉ thấy PH-002. Mật khẩu của tài khoản này có thể khác, vì tài khoản được tạo ở lần seed trước và bước seed sau không đổi mật khẩu cũ. Tuy nhiên E2E đã đăng nhập thành công bằng nó.
- `dragoon@exnodes.vn`: tài khoản của bạn, executive, liên kết Supabase nên không đăng nhập bằng mật khẩu cục bộ.

Mục **Home** chỉ hiện cho tài khoản có `user_scope`. Tài khoản khác thấy LAAM cũ và không bị ảnh hưởng. Muốn tài khoản riêng thấy Home, thêm một dòng `user_scope` cho tài khoản đó (chỉ thêm dữ liệu, không đổi schema).

## 2. Kịch bản demo (đúng luồng §15 của yêu cầu)

Đăng nhập `johnny@demo.local`, vào **Home** (`/home?project=bp-pharmacy-chain-demo`):
1. **Lời chào + trạng thái dữ liệu** ("Updated … Data through Jul 31, 2026").
2. **Cần chú ý**: 5 thẻ, thẻ nghiêm trọng nhất đứng đầu. Hiện có: doanh thu PH-004 (critical), margin kê đơn PH-003, tồn kho PH-005, hoàn tiền PH-001, tồn kho PH-003.
3. **Mở margin PH-003** (thẻ "Prescription margin"):
   - *Điều gì đổi*: 17,7% so với 20,0%, tác động ~$260.
   - *Vì sao*: bảng yếu tố đóng góp theo sản phẩm.
   - *Dự báo 30 ngày*: biểu đồ + khoảng tin cậy.
   - *4 kịch bản* (Expected / Best / Risk / No action) và ô **Adjust assumptions** để chỉnh giả định.
   - **Show evidence**: các dòng dữ liệu nguồn.
4. **Assign** → chọn người phụ trách → **Create task**.
5. **Approve** (quyết định của Johnny) → **Mark done** kèm kết quả → **Confirm outcome** (đánh dấu dự đoán đúng hay không). Đây là "vòng học".
6. Đăng nhập `ph002.manager@demo.local` để cho thấy phân quyền: chỉ thấy PH-002, không có thẻ PH-004.

**Lưu ý khi diễn tập:** mỗi lần làm hết luồng với một phát hiện thì phát hiện đó thành "resolved" và biến khỏi Home. Muốn có lại phát hiện mới, xem mục 5.

## 3. Chạy kiểm thử tự động

Chạy trong thư mục `LAAM`:
```
PACKS_DIR=../packs npx vitest run src/lib/intel     # 1250 test của engine
```
E2E bằng Playwright cần dev server và biến môi trường (xem 3a). Test tự chọn một phát hiện chưa có task và đi hết luồng, nên **mỗi lần chạy tiêu thụ một phát hiện**.

Đối chiếu phát hiện cài sẵn với dữ liệu thật (chạy ở thư mục workspace):
```
node --env-file=LAAM/.env scripts/check-expected-findings.ts     # kỳ vọng: PASS 9/9
```

**3a. Chạy E2E:** khởi động dev server ở cổng 3100 (`npx next dev -p 3100`, đặt `PACKS_DIR=../packs`), rồi đặt `E2E_BASE_URL=http://localhost:3100`, `E2E_PROJECT=bp-pharmacy-chain-demo`, `E2E_EXEC_EMAIL/PASSWORD`, `E2E_PH002_EMAIL/PASSWORD`, và chạy `npx playwright test e2e/intel-smoke.spec.ts`. Ảnh chụp được lưu ở `docs/superpowers/test-results/`.

## 4. Vận hành hằng ngày

- **Phân tích tự chạy** lúc **06:00 giờ Chicago** mỗi ngày nhờ container `laam-v2-tick` (gọi LAAM mỗi 60 giây hỏi "có job đến hạn chưa"). Kết quả là bản tin mới cho từng vai.
- **Xem trạng thái nhanh:**
  - `docker ps | grep laam-v2` để xem `app` và `tick` có chạy.
  - Bảng `analysis_run` trong DB LAAM (cổng 5500) ghi từng lần chạy.
- **Chạy phân tích ngay (để test):** đặt `nextRunAt` của job về quá khứ trong bảng `analysis_job`, tick sẽ nhận trong vòng ~1 phút.

## 5. Khi muốn "làm mới" dữ liệu demo

- **Hết phát hiện mở sau nhiều lần diễn tập:** chạy lại phân tích như mục 4. Phát hiện mới được tạo lại nếu điều kiện vẫn đúng, nhưng phát hiện đã "resolved" thì không tự mở lại.
- **Đổi dữ liệu nguồn:** nạp lại bằng `scripts/demo_data/load_pharmacy_demo.sh`. Lệnh này thao tác lên DB DAAB (:5433) nên cần `CONFIRM_LIVE_RELOAD=yes` và bản sao lưu. Sau đó chạy `scripts/demo_data/resync_daab_schema.sh`.
- **Đổi luật hoặc metric trong `packs/`:** với **luật LAAM** chỉ cần chạy lại phân tích. Với **metric mới của DAAB**, thêm các bước: `kg-packs install`, `kg-packs run-metrics --metric …` (chạy trong container: `docker exec -w /app daab-server go run ./cmd/kg-packs …`), và **khởi động lại `daab-server`**, vì nó chỉ nạp danh mục pack lúc khởi động.

## 6. Khi có sự cố

- **Home trống hoặc không có bản tin:** kiểm tra `docker logs laam-v2-app`, và xem `analysis_run` có bản ghi `failed` không.
- **Quay lại bản LAAM cũ:** gắn lại tag `laam-app:pre-proactive-20261005` thành `laam-app:latest` rồi `docker compose up -d app`.
- **Giới hạn tốc độ (429):** cầu nối MCP của DAAB đã nâng lên 600 lần/phút trong compose. Nếu thấy lại, kiểm tra `KG_BRIDGE_RATE_LIMIT_CALLS`.

## 6b. Quản lý business project và template ngành

**Mở màn hình quản trị (LAAM):** đăng nhập bằng tài khoản owner/admin → **Cài đặt → Dự án kinh doanh** (`/settings/business-projects`). Người không phải admin bị chuyển về `/settings`. Mỗi thẻ project cho biết nguồn dữ liệu, số người xem, lịch chạy bằng một câu ("Chạy mỗi ngày lúc 06:00 …") và kết quả lần kiểm tra cuối.

**Tạo project (3 bước):** bấm "Dự án kinh doanh mới" → (1) chọn kết nối dữ liệu và dự án dữ liệu nguồn → (2) tên, ngôn ngữ bản tin, múi giờ → (3) chọn người phụ trách → "Tạo dự án kinh doanh".

**Trang chi tiết (bấm "Mở"):**
- **Mọi người:** "Thêm người", "Sửa", "Xóa khỏi dự án". Mỗi người có vai trò và danh sách cửa hàng được xem (hoặc "Tất cả cửa hàng"). Người phụ trách luôn giữ quyền, không xóa được.
- **Kiểm tra hằng ngày:** bật/tắt, đặt giờ và múi giờ (có dòng xem trước), rồi "Lưu thay đổi". Nút **Chạy ngay** chạy phân tích ngay (mất 1-2 phút); nếu đang có lần chạy khác sẽ báo bận. Múi giờ `Asia/Ho_Chi_Minh` được chấp nhận. Nếu quản trị viên từng đặt lịch cron riêng, màn hình báo rõ và lưu sẽ thay bằng lịch hằng ngày.

**Template ngành trên dashboard DAAB:** vào dự án trong dashboard DAAB (:3500) → tab **Industry Templates**. Bật/tắt từng pack (cần vai Admin). Pack `pharmacy` mở rộng `retail`, nên phải bật `retail` trước thì mới bật được `pharmacy`. Tắt có hộp xác nhận.

**Ghi chú cho vận hành:**
- Thư mục pack mới thêm vào ổ đĩa chỉ hiện sau khi **khởi động lại `daab-server`** (danh mục nạp lúc khởi động). Server dev chạy `air` nên code Go đổi sẽ tự nạp lại, nhưng thêm thư mục pack thì vẫn cần restart.
- Endpoint Go mới: `GET /api/v1/projects/{id}/packs` (liệt kê pack, trạng thái bật/tắt, phiên bản) và `PUT /api/v1/projects/{id}/packs` (bật/tắt). Thay đổi pack của một project được tuần tự hóa (khóa theo project); bật lại pack đã bật thì không ghi gì.
- Tổng quan project trên DAAB nay hiển thị số nguồn dữ liệu thật (trước đây luôn 0).
- Bộ chọn project ở Home nhớ project xem gần nhất (cookie `laam_home_project`) và tô nổi chip đang chọn.

**Chưa làm / chưa kiểm chứng:**
- Chưa có nút "làm mới dữ liệu" và trình sửa ngưỡng / ghi đè luật.
- Bước 2-3 của luồng tạo project chưa được kiểm trên trình duyệt thật (môi trường thử không đăng ký được kết nối MCP); chỉ có unit test.
- Image dashboard DAAB chưa build lại và image sản xuất LAAM (`laam-v2-app`) chưa triển khai lại với các màn hình này; cần đồng ý rõ ràng trước khi deploy.
- Có sẵn từ trước: tiêu đề `/settings` và thông báo 403 hiển thị tiếng Việt khi giao diện đang là tiếng Anh.
- Test E2E `e2e/intel-admin.spec.ts` chỉ đọc; cần `E2E_ADMIN_EMAIL/PASSWORD`, `E2E_EXEC_EMAIL/PASSWORD` (chưa chạy với tài khoản thật).

## 7. Giới hạn cần nói thật khi demo

- Con số margin PH-003 là số thật của dữ liệu mẫu (~$260 / 14 ngày; kịch bản rủi ro −$960 trong 30 ngày), **không phải $18.000 / 82%** như ví dụ trong yêu cầu. Ví dụ đó là minh họa ở quy mô lớn hơn.
- Bảng yếu tố đóng góp của PH-003 hiện chỉ thấy 2 trong 5 loại thuốc được cài tăng giá.
- Các ngưỡng gắn nhãn **Provisional threshold** là mặc định demo, chưa được khách xác nhận.
- Người dùng bị hạn chế theo cửa hàng sẽ mất công cụ MCP trong chat, vì đó là cách ngăn rò dữ liệu.
- Chưa làm: xoay API key đã dán trong chat, push/merge nhánh.
- Chưa kiểm tra các trang khác của LAAM trên :3900 ngoài trang đăng nhập và route `/home`.
