# Thu tiền theo chi nhánh qua Stripe cho LAAM + DAAB — giai đoạn 1

**Ngày:** 2026-11-09 · **Trạng thái:** bản hợp nhất, không còn câu hỏi mở — đã cập nhật theo review plan (2026-11-09) (đã qua 1 lần đọc thử của builder và 2 lần review chuyên gia Stripe)
**Repo:** `ennam.kg.admin` (Ennam Admin), `LAAM`. DAAB (`ennam.kg.go`) không đổi. Nhánh: `task/payment-subscription` ở mọi repo.
**Liên quan:** `docs/pricing/ennam-pricing-us-au-2026-11.html` (bảng giá), `docs/pricing/ennam-pricing-model-explainer.html`, `docs/pricing/ennam-owner-journey.html`; backlog Serena `backlog/billing-email-provider`.
Tài liệu này là **bản duy nhất có hiệu lực**; khác với các trang HTML thì tài liệu này thắng.

---

## 1. Mục đích

Cho khách ở Mỹ **tự đăng ký, trả tiền bằng thẻ qua Stripe và dùng LAAM ngay**, theo mô hình giá đã chốt sau nghiên cứu thị trường: tính tiền **theo chi nhánh**, nhân viên không giới hạn, **không có seat**; **AI tiêu chuẩn (Haiku) đã gồm**; AI mạnh (Sonnet) và giọng đọc HD dùng **AI credit**. Hiện Admin chỉ bán gói token chuyển khoản VND/ghi tay, org tự đăng ký phải chờ duyệt, LAAM không có trang thanh toán.

Nguyên tắc với khách:
- **Không bao giờ tự tính thêm tiền.** Hoá đơn tháng = số chi nhánh × giá gói. Chỉ trừ thêm khi khách tự mua gói credit.
- **AI mạnh không bao giờ chặn:** hết credit thì tự chạy bằng Haiku, giọng HD → giọng máy.
- **AI tiêu chuẩn chỉ tạm dừng** khi org **vừa vượt ngưỡng dùng hợp lý vừa hết credit** (§6.4).

## 2. Bảng giá giai đoạn 1 (chỉ USD, tài khoản Stripe đăng ký ở Mỹ, chỉ gói tháng)

| Mục | Quy tắc |
|---|---|
| Essentials | **$29 / chi nhánh / tháng** |
| Pro | **$49 / chi nhánh / tháng** |
| Giảm theo số lượng | giá bậc luỹ tiến (graduated): chi nhánh 1–10 giá đủ · 11–50 −15% · từ 51 −30% |
| AI credit đi kèm | Essentials **200**, Pro **600** credit / chi nhánh / kỳ, dùng chung cả org, hết hạn cuối kỳ |
| Gói credit mua thêm | **1.000 credit $25**, **3.000 credit $65** — trả một lần, không hết hạn |
| Cách trừ credit | **Theo chi phí thật: 1 credit = $0,014 chi phí model** (hằng số). Trung bình 1 câu Sonnet ≈ 10, 1 câu trả lời giọng HD ≈ 2; câu dài tốn hơn |
| Ngưỡng AI tiêu chuẩn | **$6 chi phí Haiku × số chi nhánh / kỳ** (≈ 500 câu/chi nhánh). Trang giá ghi "khoảng 500 câu mỗi chi nhánh mỗi tháng"; app không hiện bộ đếm |
| Nguồn dữ liệu | Nguồn đầu tiên **đã gồm** (Ennam kết nối giúp). Nguồn thứ hai trở đi **$29/tháng** (xem §13 về thời điểm làm) |
| Phí hỗ trợ kết nối $199 | **Không làm trong giai đoạn 1** (nguồn đầu tiên miễn phí; phí cho hệ thống phức tạp nếu có thì xử lý ngoài hệ thống) |

Không có trong giai đoạn 1: giá năm, giá AUD/GST, Stripe Tax (nhưng giá đặt `tax_behavior=exclusive` và Checkout thu địa chỉ để bật sau).

## 3. Phạm vi

**Giai đoạn 1 = đạt nghiệm thu trên Stripe sandbox (§4).** Ngoài ra có **"cổng trước khi bán thật"**: việc bắt buộc trước khi chuyển sang Stripe live, nhưng không cần cho nghiệm thu sandbox.

| Việc | Giai đoạn 1 | Trước khi bán thật |
|---|---|---|
| Đăng ký, dùng thử, Free, gói tháng, gói credit, nâng cấp | ✅ | |
| Sổ credit, ngưỡng AI tiêu chuẩn, quay về Haiku, giới hạn theo người | ✅ | |
| Trang org cho nhân viên (xem gói, hoá đơn, thanh toán, credit) | ✅ | |
| Nút "đồng bộ lại org từ Stripe" và "chạy lại sự kiện lỗi" | ✅ | |
| Nút nhân viên: thêm/ngừng nguồn thứ hai ($29), đổi gói/giảm chi nhánh, huỷ, hoàn tiền (owner chốt dời; backlog `billing-staff-stripe-actions`, quy tắc ở §13) | | ✅ |
| Đối soát hằng đêm, xử lý khiếu nại thẻ tự động | | ✅ (giai đoạn 1 chỉ báo động) |
| Trần credit giữa lượt (chuyển Haiku giữa câu) | | ✅ (giai đoạn 1: kiểm tra trước lượt + không để âm) |
| Giới hạn tần suất workflow theo gói (Essentials 1 lần/ngày, Pro 15 phút) | | ✅ |
| Dữ liệu nhà thuốc mẫu cho org dùng thử | nên có | bắt buộc |
| Dịch vụ email (xác minh, nhắc dùng thử, cảnh báo credit) | | backlog |
| DAAB phần 0 (bảo mật), key LAAM→Admin gắn theo org, trang bảo mật dữ liệu | | ✅ |

**Không làm (hiện tại):** khách tự kết nối LAAM với DAAB hoặc tự thêm nguồn dữ liệu (luôn do nhân viên Ennam làm trong Admin); nhân viên dùng Stripe Dashboard (trừ khiếu nại thẻ — chỉ vai trò admin); tự động mua credit; gói năm.

**Tuyệt đối tránh:** trừ tiền ngoài ý muốn hoặc hai lần; khách trả tiền mà không được kích hoạt; cộng credit trùng; số dư âm, hoặc credit kỳ sau / credit đã mua bị trừ ngầm; LAAM giữ hoặc gọi khoá Stripe; tiền và sổ lệch mà không ai biết.

## 4. Nghiệm thu (Stripe sandbox + test clock)

1. Mở trang đăng ký LAAM, nhập 3 chi nhánh, chọn **Essentials**.
2. Stripe Checkout (sandbox), trả **$87** bằng thẻ `4242…`.
3. Quay lại LAAM: org **kích hoạt ngay**, có **600 credit đi kèm**.
4. Hỏi Haiku vài câu → **không trừ** credit. Hỏi Sonnet 1 câu → trừ **≈ chi phí thật ÷ $0,014** (khoảng 10).
5. Owner vào **Cài đặt → AI credit**, giới hạn một nhân viên 50 credit; nhân viên đó dùng hết → câu tiếp theo tự chạy bằng Haiku.
6. Mua gói 1.000 credit ($25) → credit tăng ngay.
7. Tăng 3 → 4 chi nhánh (qua màn nâng cấp của LAAM → Stripe) → Stripe thu tiền chênh lệch ngay và org nhận ngay credit tương ứng thời gian còn lại của kỳ (200 × phần kỳ còn lại).
8. Tua test clock qua kỳ (+1 giờ sau mốc kỳ) → Stripe gia hạn, Admin cấp **800** credit kỳ mới, phần còn lại của kỳ cũ hết hạn.
9. Huỷ cuối kỳ → dùng tới hết kỳ → org về **Free**; credit đã mua vẫn còn.
10. Trong Admin, nhân viên thấy org: gói, số chi nhánh, trạng thái subscription, hoá đơn, thanh toán, credit đã dùng.
11. **Dùng thử:** đăng ký "Dùng thử" → org chờ duyệt → nhân viên duyệt trong Admin → dùng 14 ngày (tính từ lúc duyệt) → công cụ dev lùi ngày → hết hạn → về Free.
12. **Ngưỡng AI tiêu chuẩn:** công cụ dev đẩy chi phí Haiku của org vượt ngưỡng → câu Haiku tiếp theo trừ credit; hết credit → chat tạm dừng với lựa chọn mua credit / chờ kỳ sau.

Lưu ý test clock: tối đa 3 customer/clock và 3 subscription/customer; tua tối đa 2 kỳ mỗi lần; mô phỏng tự xoá sau 30 ngày (lưu bằng chứng trước); Customer chỉ gắn clock lúc tạo → Admin có hook `test_clock` **chỉ ở dev**, dùng ngay từ bước 1.

## 5. Kiến trúc

```
Khách ──► LAAM (đăng ký, chọn gói, chat, cài đặt credit)
            │  API Admin (key sản phẩm, hợp đồng v1 + trường tuỳ chọn mới)
            ▼
        Ennam Admin ──► Stripe (Customer, Checkout, Subscription, Portal)
            ▲                    │
            └──── webhook ◄──────┘
        Sổ token (ledger_entry) = nguồn sự thật cho số dư
```
- **Chỉ Admin giữ khoá Stripe** (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` đặt trong env, không dán vào chat/tài liệu/log). LAAM chỉ chuyển hướng tới URL do Admin tạo.
- **Ghim phiên bản API Stripe `2026-10-28.endive`** ở SDK và endpoint webhook; sự kiện có `api_version` khác bị từ chối. Với basil: id subscription của hoá đơn ở `invoice.parent.subscription_details.subscription`; thanh toán ở `invoice.payments`; kỳ hiện tại nằm ở **subscription item** (`current_period_*`).

## 6. Hành vi sản phẩm

### 6.1 Đăng ký
- Trang đăng ký công khai (`REGISTER_MODE=open` hoặc tương đương) có **3 lựa chọn**: **Dùng thử 14 ngày**, **Essentials**, **Pro** (chọn số chi nhánh, giá hiện ngay), và "**Liên hệ Ennam**" cho chuỗi lớn (nhân viên tạo org bằng tay như hiện nay). Không có nút chọn Free.
- **Chưa có xác minh email** (backlog). Thay vào đó **org dùng thử phải được nhân viên Ennam duyệt** (dùng lại luồng `pending` + trang `/pending` hiện có). **14 ngày tính từ lúc duyệt.**
- **Org trả phí kích hoạt ngay** sau khi thanh toán (thanh toán thành công thay cho xác minh). Trong lúc chờ thanh toán, org là `pending` kèm `subscription_status='awaiting_payment'` (dùng lại cơ chế giam org pending của LAAM và chỉ mục chống đăng ký trùng của Admin), **không** vào hàng chờ duyệt của nhân viên. Người dùng được đăng nhập trước khi sang Checkout. Bỏ dở Checkout thì màn `/pending` cho tiếp tục thanh toán, đổi gói hoặc chuyển sang dùng thử; org chờ thanh toán quá 7 ngày bị từ chối với lý do `checkout_abandoned`.
- Chống lạm dụng đơn giản: giới hạn đăng ký theo IP (đã có), chặn tên miền email tạm, chuẩn hoá email (bỏ `+…`, bỏ dấu chấm với Gmail) khi kiểm tra "mỗi email một lần dùng thử".
- Org trả phí ngay không có thêm 14 ngày miễn phí. Cam kết hoàn tiền 30 ngày: **chưa có**.

### 6.2 Dùng thử và bản Free
- **Dùng thử (14 ngày từ lúc duyệt):** như Pro cho 1 chi nhánh, **không có DAAB**, dùng **dữ liệu nhà thuốc mẫu** và hỏi đáp tài liệu tải lên; ngưỡng AI tiêu chuẩn **$6** cho cả thời gian dùng thử (≈ 500 câu); **200 credit** dùng thử. Org dùng thử **không mua** gói credit. Hết hạn → Free.
- **Free (không hết hạn):** 1 chi nhánh, ngưỡng AI tiêu chuẩn **$1,2 / tháng** (≈ 100 câu, tính từ ngày về Free), hỏi đáp tài liệu, dữ liệu mẫu; **không** credit đi kèm, **không** brief/cảnh báo từ dữ liệu thật; nhân viên đã mời vẫn đăng nhập.
- Org từng trả phí rồi huỷ / thu tiền thất bại hẳn → Free: **Admin ngừng trả kết nối DAAB và tăng `connections_version`**; dữ liệu giữ 90 ngày (cơ chế xoá thật để sau); **credit đã mua vẫn dùng được** theo cùng quy tắc §6.4.

### 6.3 Nâng cấp và quản lý gói
- Chỉ **owner**. Nhân viên khác chỉ thấy dòng "Liên hệ chủ tài khoản để nâng cấp".
- Chỗ hiện nút: banner (dùng thử còn N ngày / đang dùng Free), khi chạm giới hạn hoặc bấm tính năng bị khoá, **Cài đặt → Gói và thanh toán**. Nhắc dùng thử chỉ trong app (email để sau).
- **Org chưa có subscription** (dùng thử/Free): màn chọn gói của LAAM → Admin tạo **Checkout** → trả tiền → kích hoạt. Thời gian dùng thử kết thúc ngay; credit dùng thử còn lại hết hạn trong cùng transaction với lần cấp credit đầu.
- **Org đã có subscription:** **không tạo Checkout mới** (chống trùng). Tăng chi nhánh / Essentials → Pro: LAAM gửi lựa chọn → Admin kiểm tra đúng là **tăng** → tạo **phiên Portal deep link** (`flow_data.type=subscription_update_confirm` với item và số lượng/giá mới, dùng **cấu hình Portal cho phép update**) → khách xác nhận trên Stripe → Stripe thu tiền chênh lệch ngay.
- **Cấu hình Portal mặc định:** không cho update gói/số lượng; cho đổi thẻ, xem hoá đơn, **huỷ cuối kỳ**. (Stripe không có tuỳ chọn "chỉ cho tăng", nên giới hạn được làm bằng deep link + kiểm tra của Admin.) **Không dùng subscription schedule** (nó khoá khách khỏi Portal).
- **Giảm chi nhánh / Pro → Essentials:** khách liên hệ Ennam (xem §13 về nút nhân viên).
- Sau khi trả phí: LAAM hiện "**Ennam sẽ liên hệ để kết nối dữ liệu của bạn**" (form ngắn: phần mềm đang dùng, liên hệ). Nhân viên kết nối bằng thẻ DAAB trong Admin.

### 6.4 AI credit và ngưỡng
- **Đo usage giữ nguyên:** mỗi lần gọi model LAAM gửi usage event (model, token in/out, cache đọc/ghi, ký tự TTS); Admin tính `charged_tokens` và `cost_usd_micros`. **Hệ số giá trong `price_book` = giá vốn** ⇒ 1 token Ennam = $0,000001 chi phí thật. **Credit hiển thị = token ÷ 14.000** (hằng số, không đổi). Credit đi kèm và gói credit chỉ là quy đổi (200 credit = 2,8 triệu token; 1.000 credit = 14 triệu token). Mọi model mở cho khách phải có giá vốn trong `price_book`.
- **Chi phí DAAB** (mỗi lượt DAAB có dùng LLM) phải được cộng vào **cả** `charged_tokens` và `cost_usd_micros` (hiện chỉ cộng vào `charged_tokens`, `pricing.ts:115`); `daab_call_tokens` đổi thành chi phí USD cố định mỗi lượt (cấu hình). DAAB đi theo model chat của lượt: lượt Haiku tính vào ngưỡng, lượt Sonnet trừ credit.
- **Model tiêu chuẩn** = Haiku 5.5 và `none` (event chỉ có lượt DAAB) (danh sách cấu hình trong Admin). Chi phí model tiêu chuẩn **do người dùng hoặc lịch của org kích hoạt** (chat, workflow, intel brief của org) tính vào ngưỡng; tác vụ nền của hệ thống không do org kích hoạt thì không tính.
- **Ngưỡng tính theo "kỳ đã ghi"** của org (kỳ subscription hiện tại theo dữ liệu Stripe đã lưu; dùng thử: cả thời gian dùng thử; Free: tháng tính từ ngày về Free), **không** theo `occurred_at` (vì test clock dùng thời gian giả lập). Ngưỡng = $6 × **số chi nhánh tại đầu kỳ** (trả phí), $6 (dùng thử), $1,2 (Free).
- **Admin khi nhận usage event của model tiêu chuẩn** (dưới `lockOrg`): cộng dồn chi phí tiêu chuẩn của kỳ; phần trong ngưỡng **không trừ**; phần vượt (kể cả phần vượt của một event nằm vắt qua ngưỡng) **trừ credit nhưng không bao giờ làm số dư âm** (kẹp ở 0); ghi phần được miễn vào `usage_event`.
- **Model AI mạnh** (Sonnet) và giọng HD: trừ toàn bộ chi phí thật vào credit, **kẹp ở 0** (lượt cuối có thể vượt số dư một chút — phần vượt được miễn, không thành nợ).
- **Không còn trừ nợ:** bỏ việc `netDebt` trừ phần âm vào grant mới (`ledger.ts:100–141`) trong luồng này; số dư không âm.
- **Thứ tự trừ:** credit đi kèm (gần hết hạn trước) → credit mua thêm.
- **Org vượt ngưỡng tiêu chuẩn và hết credit** (mọi gói, kể cả dùng thử và Free) → entitlement báo **tạm dừng AI tiêu chuẩn** (`fair_use_exhausted`) → LAAM chặn chat kèm lựa chọn **mua credit** (trả phí / Free), **nâng cấp** (dùng thử / Free) hoặc **chờ kỳ sau**. Org còn credit (kể cả credit đã mua, ở Free) thì vẫn dùng tiếp, trừ vào credit.
- **Khách thấy:** trước khi gửi bằng Sonnet: "~10 credit" (ước lượng trung bình theo model, Admin gửi kèm entitlement); sau khi trả lời: số credit thật; trang AI credit có lịch sử theo người.

### 6.5 Quay về Haiku và giới hạn theo người (LAAM)
- **Chỉ model Claude cho org khách:** Haiku 5.5 mặc định, Sonnet 5.5 là AI mạnh. BytePlus, Cerebras, DeepSeek, model local chỉ cho org nội bộ. Sửa: mặc định chat (`chat-default.ts:12-17` đang ưu tiên BytePlus và rơi về Sonnet), danh sách model ở trang chọn model theo org (owner chỉ ghim được Claude), `resolveTask` (tác vụ nền dùng Haiku).
- Trước mỗi lượt dùng Sonnet / giọng HD: nếu org **không còn credit** (`strong_ai_allowed=false`) hoặc người dùng **bị tắt** / **chạm giới hạn tháng** → chạy bằng Haiku (giọng máy) và báo nhẹ lý do. **Không bao giờ chặn** vì hết credit.
- **Cài đặt → AI credit** (chỉ owner): bật/tắt AI mạnh và giọng HD từng người; giới hạn credit/tháng từng người; mức mặc định cho người mới; chi tiêu theo người và theo loại; số dư org (đi kèm / mua thêm). Có ở **cả Essentials và Pro**.
- Chi tiêu từng người LAAM tự tính từ usage cục bộ (`usage_outbox` theo `user_id`) × giá trong entitlement, trong kỳ do entitlement cung cấp. Chỉ tính AI mạnh + giọng HD.
- Cảnh báo owner **trong app** khi credit org còn 25% và khi hết.
- **Bật kiểm tra thật cho org khách** (`USAGE_ENFORCE`, hiện chỉ ghi log) và xử lý lý do chặn mới trong `gates.ts` (`tokenBlockOf` hiện chỉ biết `no_tokens`, `billing_unavailable`). **Thêm kiểm tra trạng thái org và credit cho `/api/tts`, `/api/tts/stream`** (hiện không có).
- Phanh kỹ thuật: giữ mỗi lần gọi Haiku dưới 100 nghìn token prompt (vượt là Anthropic tính gấp 5 cả lần gọi).

## 7. Stripe

### 7.1 Đối tượng
- Sản phẩm **Essentials**, **Pro**: mỗi cái một giá tháng, **graduated tiers** theo số lượng (= số chi nhánh), `tax_behavior=exclusive`.
- 2 giá trả một lần cho gói credit 1.000 / 3.000.
- Sản phẩm "Thêm nguồn dữ liệu" $29/tháng (chỉ dùng khi có nút nhân viên, §13).
- ID giá lưu trong cấu hình Admin (không viết cứng) để tạo lại trên live.
- **Mỗi org đúng một Stripe Customer**, Admin tạo trước Checkout với idempotency key, lưu id trên org.
- Mọi subscription mang `metadata.kind` (`plan` | `addon`) và `metadata.org_id`; Checkout mang `client_reference_id = org_id`.
- Smart Retries hết lượt → **huỷ subscription**. Bật email của chính Stripe: hoá đơn/biên nhận, thẻ lỗi, cần xác thực 3DS.

### 7.2 Kích hoạt và cấp credit
- **Kích hoạt** khi subscription `kind=plan` của org thành `active` (từ webhook **hoặc** từ đường đồng bộ bên dưới).
- **Đường đồng bộ khi khách quay lại:** `success_url` chứa `{CHECKOUT_SESSION_ID}`; LAAM gọi Admin; Admin lấy phiên từ Stripe, chạy **cùng logic** kích hoạt idempotent, và nếu `subscription.latest_invoice` đã `paid` thì chạy luôn logic cấp credit (cũng idempotent). Gói credit: phiên `payment_status=paid` → cộng credit. LAAM xoá cache entitlement và tải lại ngay.
- **Cấp credit đi kèm** chỉ khi: `invoice.paid`, subscription của hoá đơn **là subscription `plan` hiện tại của org**, `billing_reason ∈ {subscription_create, subscription_cycle}`.
  - Số credit = credit/chi nhánh của gói × **quantity của dòng gói không phải proration** trên hoá đơn (không lấy từ bảng org).
  - **Khoá:** `ref_type='sub_period'`, `ref_id='<subscription_id>:<period.start của dòng gói>'` (không dùng `invoice.period_start`, vì nó trùng nhau giữa hoá đơn tạo mới và hoá đơn gia hạn đầu tiên), với **unique index một phần** `ledger_entry(org_id, ref_type, ref_id) WHERE type='grant'`.
  - Hạn = `period.end` của dòng gói + **3 ngày ân hạn** (để không về 0 trong lúc Stripe đang thu kỳ mới; nếu thu thất bại kéo dài thì credit đi kèm về 0 sau ân hạn — có chủ đích). UI ghi "hết hạn cuối kỳ".
  - Trong cùng transaction: ghi `expire` cho phần còn lại của các grant đi kèm **có kỳ sớm hơn**; bỏ qua grant đã quá hạn.
- **Nâng cấp giữa kỳ cấp credit ngay theo ngày còn lại** (owner chốt (b) 2026-11-09): khi `invoice.paid` có `billing_reason=subscription_update` của subscription `plan` hiện tại và là **tăng** (thêm chi nhánh hoặc Essentials → Pro), cấp thêm **(credit/kỳ mới − credit/kỳ cũ) × (thời gian còn lại của kỳ ÷ độ dài kỳ)**, làm tròn xuống. Credit/kỳ = credit mỗi chi nhánh của gói × số chi nhánh. Tỷ lệ thời gian lấy từ `period` của các dòng proration trên hoá đơn đó. Khoá: `ref_type='sub_prorate'`, `ref_id='<invoice_id>'` (cùng unique index một phần). Hạn = hạn của grant đi kèm kỳ hiện tại. Không cấp gì khi giảm (giảm chỉ qua nhân viên, đã dời sau). Ví dụ: 3 chi nhánh Essentials lên Pro ở giữa kỳ 30 ngày → +(1.800 − 600) × 15/30 = **+600 credit**; thêm chi nhánh thứ 4 Essentials ở giữa kỳ → +200 × 15/30 = **+100 credit**.
- Cấm mọi cập nhật làm reset `billing_cycle_anchor`.
- **Gói credit:** Checkout `mode=payment` mang `metadata {org_id, kind:'credit_pack', pack}` (không dùng `purchase_request`) → bút toán `purchase` không hết hạn, khoá theo `payment_intent` (dùng lại khi hoàn tiền).
- **Nhận subscription ở bất kỳ sự kiện nào đến trước** (`invoice.paid`, `checkout.session.completed`, `customer.subscription.*`, xác nhận khi quay lại): subscription có `metadata.kind='plan'` và `org_id` khớp, org chưa có subscription sống → gắn vào org rồi mới xử lý.

### 7.3 Đồng bộ trạng thái
- Sự kiện `customer.subscription.*` chỉ là **tín hiệu**: Admin lấy lại subscription mới nhất từ Stripe rồi ghi toàn bộ trạng thái (gói theo giá, số lượng, trạng thái, kỳ từ subscription item).
- Chỉ subscription **`kind=plan` hiện tại** của org được ghi vào gói/trạng thái org; `kind=addon` đi đường riêng (§13).
- Phát hiện **subscription `plan` thứ hai** cho cùng org (đã chặn ở §6.3 nhưng vẫn kiểm tra) → gắn cờ cho nhân viên, **không** cấp credit cho nó.
- `past_due`: org vẫn dùng được, owner thấy nhắc trong app. `canceled`, `unpaid`, `incomplete_expired` → **Free** (§6.2), ghi `expire` phần credit đi kèm còn lại.
- Huỷ cuối kỳ: dùng tới hết kỳ → Free.
- Webhook dùng lại phần **chống trùng** `payment_event` (`provider_event_id` duy nhất) nhưng **không** đi qua `upsertPayment`/`fulfillPayment` cho hoá đơn subscription (đang viết cứng VND và gắn `purchase_request`). Trả 2xx nhanh cho `invoice.created`.

### 7.4 Hoàn tiền và khiếu nại
- `charge.refunded` (tìm hoá đơn qua `invoice.payments`): gói credit → **trừ lại phần credit mua còn lại, không làm số dư âm**; hoá đơn tháng → không thu hồi credit. Đối chiếu theo id refund để không ghi trùng khi refund do Admin tạo.
- `charge.dispute.created` → báo động nhân viên, chặn mua mới, đặt `pause_collection` cho subscription của org. `charge.dispute.closed`: thua với gói credit → trừ phần credit còn lại; thắng → bỏ cờ. Nộp bằng chứng: chỉ vai trò admin làm trên Stripe Dashboard.

## 8. Ennam Admin

- **Org:** thêm gói (`managed`/`trial`/`free`/`essentials`/`pro`; `managed` = org nội bộ, org nhân viên tạo và org có trước migration — luật cũ, có DAAB, không ngưỡng, không khối billing), số chi nhánh, trạng thái subscription, ngày hết dùng thử, Stripe customer id, subscription id (`plan`), kỳ hiện tại (đầu/cuối), số chi nhánh đầu kỳ. Dùng thử (đã duyệt), Free và trả phí (đã thanh toán) đều `status='active'`; `pending` dùng cho dùng thử chờ duyệt **và** org trả phí chờ thanh toán (phân biệt bằng `subscription_status='awaiting_payment'`, không vào hàng chờ duyệt). Bỏ giới hạn `max_members` cho org theo gói.
- **Bỏ VND viết cứng** (`providers.ts:76`, `orgs.ts:41`, `create-internal-org-cli.ts:15`, mặc định schema) → org mới mặc định **USD**. Luồng chuyển khoản/ghi tay cũ giữ cho nhân viên (gói token → hiển thị như gói credit).
- **Cài đặt đổi đơn vị:** `trial.tokens` (200 credit = 2,8 triệu token), `balance.low_tokens` (25% theo credit), `usage.daab_call_tokens` → chi phí USD/lượt DAAB. Thêm: danh sách model tiêu chuẩn, ngưỡng $/chi nhánh, ngưỡng dùng thử/Free, credit đi kèm mỗi gói, ID giá Stripe. Theo quy ước `requireStaff` + TOTP + audit.
- **Dữ liệu billing cũ ở dev** (chưa có khách thật — owner xác nhận) được bỏ bằng migration riêng (trigger chỉ-ghi-thêm phải tắt/bật có chủ đích như lần 1E); giữ org, user, audit, kết nối DAAB, product client.
- **Trang org cho nhân viên:** gói, số chi nhánh, trạng thái subscription, hoá đơn và thanh toán (lấy từ Stripe theo customer — danh sách không lọc sẽ không thấy đối tượng test clock), credit đi kèm/mua/đã dùng, ngưỡng tiêu chuẩn đã dùng; nút **đồng bộ lại từ Stripe** và **chạy lại sự kiện lỗi**; duyệt org dùng thử (đã có).
- **Bảo mật phiên Stripe:** `success_url`/`cancel_url`/`return_url` do Admin dựng từ cấu hình, không lấy từ LAAM; LAAM chỉ gọi khi `role === 'owner'`; Admin ghi audit mỗi phiên tạo ra.
- **Công cụ chỉ ở dev:** hook `test_clock` khi tạo Customer; lùi ngày dùng thử / mốc Free; đẩy chi phí tiêu chuẩn của org (bước 11–12).

## 9. Hợp đồng Admin ↔ LAAM

- **Giữ `CONTRACT_VERSION = 1`, chỉ thêm trường tuỳ chọn** (Admin hiện từ chối mọi version khác ⇒ tăng version làm LAAM lỗi khi deploy lệch).
- `OrgStatus`/`BlockReason` là `z.enum` chặt: **không thêm giá trị mới vào enum cũ**. Lý do chặn mới (`fair_use_exhausted`, trạng thái chờ thanh toán…) đi trong **trường tuỳ chọn mới** (ví dụ `billing.block`). Không giới hạn thành viên: trường tuỳ chọn mới thay vì đổi `Positive`. Hợp đồng vẫn giống hệt từng byte ở hai repo.
- **Thứ tự deploy:** LAAM (đọc được trường mới, bỏ qua nếu thiếu) → Admin (bắt đầu gửi trường mới).
- **Entitlement thêm (tuỳ chọn):** gói, số chi nhánh, trạng thái subscription, ngày hết dùng thử, kỳ hiện tại, số dư credit (đi kèm / mua / hạn gần nhất), `strong_ai_allowed`, trạng thái ngưỡng tiêu chuẩn (đã dùng/ngưỡng, `fair_use_exhausted`), credit ước lượng trung bình theo model; giá theo model (đã có) để LAAM tính chi tiêu theo người.
- **API mới (Admin):** tạo Checkout đăng ký/nâng cấp; tạo Checkout gói credit; tạo phiên Portal mặc định và phiên Portal deep link (tăng chi nhánh / Essentials → Pro); xác nhận phiên Checkout khi khách quay lại (§7.2).
- Usage event: **giữ nguyên**.

## 10. Ràng buộc

- Chỉ USD; Stripe đăng ký ở Mỹ; sandbox cho tới khi đạt §4 và xong cột "Trước khi bán thật".
- Quy ước từng repo (`CLAUDE.md`/`AGENTS.md`): Admin Next.js 16 + Drizzle + Postgres, service nhận `db: DbOrTx`, audit cùng transaction, migration viết tay khi cần, không `drizzle-kit push`; sổ chỉ ghi thêm; comment/commit tiếng Anh, tài liệu tiếng Việt. Admin và LAAM là git repo riêng; hợp đồng sửa ở Admin trước rồi chép sang LAAM.
- DB dev Admin: container `laam-postgres` (`ennam_admin`, test `ennam_admin_test`); không chạy hai `test:int` cùng lúc.

## 11. Rủi ro và backlog

- Key LAAM→Admin không gắn org — siết trước khi bán thật.
- DAAB phần 0 (bảo mật) — trước khi khách thật dùng DAAB.
- Chưa có email (backlog `billing-email-provider`): chưa xác minh email, nhắc/cảnh báo chỉ trong app; dùng thử dựa vào duyệt tay.
- HIPAA / trang bảo mật dữ liệu nhà thuốc — người mua sẽ hỏi.
- Commit tính tiền cache của Admin (`417b6e4`) chưa vào `main` trong khi LAAM đã gửi trường cache — kiểm tra khi deploy.

## 12. Builder quyết

Tên bảng/cột/trạng thái; cấu trúc module Stripe (mở rộng `PaymentProvider` hay module riêng dùng chung `payment`/`payment_event`); `stripe` Node SDK (phiên bản cố định); cách LAAM xử lý quay lại từ Checkout/Portal; cách dựng dữ liệu nhà thuốc mẫu; thời điểm dọn org chờ thanh toán.

## 13. Quyết định cuối và quy tắc cho phần dời sau

1. **Nâng cấp giữa kỳ:** **cấp ngay phần credit tương ứng thời gian còn lại của kỳ** (owner chốt (b) 2026-11-09) — quy tắc ở §7.2. Lý do: khách trả thêm tiền lúc nào thì nhận thêm credit lúc đó; người nâng cấp giữa kỳ thường đang cần thêm credit ngay.
2. **Các nút nhân viên** (thêm/ngừng nguồn thứ hai $29, đổi gói/giảm chi nhánh, huỷ, hoàn tiền): **dời sang "trước khi bán thật"** (owner chốt 2026-11-09; backlog Serena `backlog/billing-staff-stripe-actions`). Trong giai đoạn 1, org chỉ có nguồn dữ liệu đầu tiên; giảm/huỷ/hoàn tiền khi test sandbox làm bằng nút "đồng bộ lại từ Stripe" sau thao tác của khách trên Portal. Khi làm, áp dụng:
   - **Nguồn thứ hai:** subscription riêng `kind=addon`, cùng customer/thẻ, `billing_cycle_anchor` = cuối kỳ hiện tại của subscription chính, có proration; huỷ theo khi subscription chính bị xoá; khách tự huỷ addon trên Portal → báo nhân viên và tạm dừng nguồn đó; khách nhận 2 hoá đơn/tháng.
   - **Đổi gói/số lượng qua API:** tăng → `proration_behavior=always_invoice`, `payment_behavior=pending_if_incomplete`; giảm / hạ gói → hiệu lực **cuối kỳ** bằng job riêng của Admin (không dùng schedule), không hoàn tiền giữa kỳ.
   - **Hoàn tiền hoá đơn tháng** có lựa chọn "hoàn + huỷ"; hoàn gói credit theo §7.4.
