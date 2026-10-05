# Báo cáo hoàn thành Beta — DAAB + LAAM Pharmacy/Retail (2026-10-05)

Đối chiếu với §16 "Beta Completion Definition" và §15 "Beta Demo" của yêu cầu. Trạng thái: ✅ đạt có bằng chứng · ⚠️ đạt một phần / chưa kiểm chứng đủ · ❌ chưa đạt.

## 11 tiêu chí §16

| # | Tiêu chí | TT | Bằng chứng / ghi chú |
|---|---|---|---|
| 1 | Nhà thuốc/bán lẻ mới nhập dữ liệu bằng cấu hình | ⚠️ | Pack (`packs/retail`, `packs/pharmacy`) + `_projects/pharmacy-chain/mapping.yaml` + CLI `kg-packs`; metric mới thêm chỉ bằng SQL + YAML (RET-INV-003 v2). Chưa thử với khách thứ hai thật; mỗi khi đổi pack phải restart `daab-server` (catalog nạp lúc khởi động). |
| 2 | DAAB tổ chức và kiểm tra dữ liệu | ✅ | Đồng bộ schema 25 bảng / 25 node; `data_status` theo metric; nạp CSV mục tiêu (`store_targets` 170 dòng). |
| 3 | Báo cáo chuẩn bị tự động | ⚠️ | 30 metric + metric mới được chạy bằng `kg-packs run-metrics`; LAAM có job phân tích hằng ngày (06:00 America/Chicago) nhưng **tick chưa được lập lịch tự động** (cần `WORKFLOW_TICK_SECRET` + sidecar, quyết định vận hành). |
| 4 | LAAM chào bằng phát hiện chủ động | ✅ | Home có lời chào + 5 thẻ "Cần chú ý"; bản tin do LLM viết, có kiểm tra grounding, fallback template. Giới hạn ≤2 thẻ/luật. |
| 5 | Ít nhất một dự báo hoạt động | ✅ | Dự báo 30 ngày (Holt-Winters + backtest); panel "30-day forecast" hiển thị trên chi tiết phát hiện. 40/48 dự báo `ok`, 8 `error` (chưa phân tích nguyên nhân). |
| 6 | Ít nhất một so sánh kịch bản chỉnh được | ✅ | Bảng 4 kịch bản (Expected/Best/Risk/No action) + "Adjust assumptions". E2E xác nhận bảng có 5 hàng. |
| 7 | Mỗi phát hiện liên kết dữ liệu hỗ trợ | ✅ | `evidenceRefs` + SQL bằng chứng mỗi metric (cả metric mới); nút Evidence trên chi tiết. |
| 8 | Khuyến nghị → task được giao | ✅ | E2E: Assign → Create task → trạng thái `assigned`. |
| 9 | Quyết định và kết quả được ghi lại | ✅ | E2E chạy hết: giao task → duyệt → đánh dấu xong kèm kết quả → xác nhận kết quả ("dự đoán đúng"). DB ghi `outcome_confirmed`, `recommendation_accepted`, `intel.task.approve/complete`, `intel.finding.resolve` trong `feedback`/`audit_log`. |
| 10 | Quyền khách hàng/chi nhánh được thực thi | ⚠️ | Test E2E: quản lý PH-002 không thấy thẻ PH-004; test đơn vị scope/visibility xanh. Còn mở: người dùng bị hạn chế mất công cụ MCP trong chat; CSRF là follow-up. |
| 11 | Demo hoàn chỉnh từ nhập dữ liệu đến hành động cuối | ✅ | Nhập/chuẩn bị dữ liệu chạy bằng CLI; từ Home đến hành động cuối chạy bằng Playwright, qua 2 lần liên tiếp sau khi đổi luật tồn kho (test tự chọn finding chưa có task). |

## Luồng demo §15

| Bước | TT |
|---|---|
| Nhập dữ liệu; DAAB nhận diện cửa hàng/sản phẩm/chi phí/tồn kho/giao dịch | ✅ |
| Báo cáo chuẩn bị sẵn | ✅ |
| Đăng nhập Johnny; lời chào chủ động | ✅ |
| Ba phát hiện quan trọng | ✅ (Home hiển thị 5) |
| Mở rủi ro biên lợi nhuận/hoàn trả | ⚠️ PH-MARGIN-001 (PH-003) được phát hiện nhưng tác động chỉ ~$260, ví dụ yêu cầu là $18.000 / 82% — chưa chỉnh dữ liệu/ngưỡng |
| Giải thích điều gì đổi và vì sao | ✅ (bảng yếu tố đóng góp) |
| Dự báo 30 ngày | ✅ |
| So sánh 4 kịch bản | ✅ |
| Mở bằng chứng nguồn | ✅ |
| Giao hành động khuyến nghị | ✅ |
| Ghi quyết định của Johnny | ✅ (approve) |
| Kết quả quay lại vòng học | ✅ (feedback `outcome_confirmed` + audit) |

## Phát hiện cài sẵn (ground truth)
`check-expected-findings`: **PASS 9/9** (FND-001…009) sau khi gộp tồn kho theo cửa hàng. FND-006 chỉ được bắt bởi RET-CASH-001.

## Thay đổi chất lượng trong phiên này
- Home: tối đa 2 thẻ chính cho cùng một luật (`cda2378`).
- Bố cục: hết tràn ngang ở 375/768/1024 (`5c1a762`).
- RET-INV-003 v2: một phát hiện mỗi cửa hàng theo `retail.stockout_sku_count`, mức `medium`/`high`, **ngưỡng provisional do mình chọn**; lệch khỏi tầng critical theo SKU của yêu cầu (quyết định 2026-10-05, test ghi rõ).

## Còn mở / cần quyết định
1. Chỉnh dữ liệu demo/ngưỡng để PH-003 giống ví dụ $18.000? (chưa làm)
2. Lập lịch tự động: `WORKFLOW_TICK_SECRET` trong `LAAM/.env` + tick sidecar.
3. Triển khai code mới lên container `laam-v2-app` (:3900, image cũ).
4. Xoay API key đã dán trong chat.
5. Push/merge, `finishing-a-development-branch` chưa chạy.
6. **Màn hình quản trị: đã xong trong code** (chưa deploy). Gồm Cài đặt → Dự án kinh doanh (danh sách, tạo 3 bước, người/cửa hàng, giờ kiểm tra hằng ngày, "Chạy ngay"), tab Industry Templates trên DAAB và API `GET/PUT /api/v1/projects/{id}/packs`. Còn lại: nút làm mới dữ liệu và trình sửa ngưỡng/ghi đè luật chưa làm; bước 2-3 của luồng tạo chưa kiểm trên trình duyệt thật (không đăng ký được kết nối MCP trong môi trường thử); image dashboard chưa build lại và image sản xuất LAAM chưa triển khai lại với các màn hình này; tiêu đề `/settings` và thông báo 403 tiếng Việt hiện ở giao diện tiếng Anh (có sẵn từ trước).
7. Tồn đọng kỹ thuật: pipeline không tự đóng phát hiện cũ khi luật đổi version; race "Tạo task" ngay khi mở phát hiện (409); quản lý cửa hàng không duyệt task của nhân viên; upload yêu cầu vai Developer; thiếu test DB parity cho repo Drizzle; TOCTOU lần chạy thủ công (cần migration, phối hợp nhánh phân quyền); 3 test `ConstellationClient` fail và 1 lỗi `tsc` ở `executors.test.ts` (chưa xác nhận có sẵn từ trước).

## Màn hình quản trị
- Ảnh chụp (list/detail/hộp thoại người/bước 1 tạo project; vi/en/zh; 320-1440px): `docs/superpowers/test-results/admin-ui/`.
- Kết quả kiểm chứng trên trình duyệt thật (môi trường thử): `.superpowers/sdd/2026-10-05-admin-pages/admin-ui-verification.md` — lúc kiểm chứng **16 PASS / 1 PARTIAL / 1 FAIL**; mọi lỗi đã báo đều được sửa sau đó, trừ các lỗi có sẵn từ trước (tiêu đề `/settings` và 403 tiếng Việt trong giao diện tiếng Anh).
- Commit: ennam.kg.go `df07da3`, `11d43a9`, `ef95284`, `99c1600`; ennam.kg.next `5b30c6f`; LAAM `df6948b`, `63246dd`, `449c98d`, `e71b99e`, `1b41bbc`, `14be718`, `1b7478d`, `5872a57`, `3b0c897`.
