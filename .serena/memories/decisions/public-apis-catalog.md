# Quyết định: tích hợp public-apis.github.io vào LAAM (2026-09-16)

## Bối cảnh
Người dùng muốn LAAM (chat agent) có thể trả lời câu hỏi cần dữ liệu thời gian thực
(thời tiết, tỷ giá, chuyến bay...) bằng cách gọi API từ github.com/public-apis/public-apis
(~1400 API). Không nạp toàn bộ 1400 API làm tool schema (chi phí token quá lớn, model
dễ chọn sai — xem cảnh báo có sẵn trong code LAAM về việc menu tool lớn làm giảm độ chính
xác chọn tool của MCP).

## Kiến trúc đã chọn
Catalog cố định, tự viết tay (KHÔNG dùng RAG/embedding — ở quy mô 15-20 entry, keyword
match đơn giản đã đủ; RAG chỉ đáng làm khi catalog vượt ~100 entry). Mỗi connector có
đúng 2 tool: `*_search(query)` tìm trong catalog, `*_call(id, params)` build URL từ
template cố định trong catalog rồi gọi. Model KHÔNG BAO GIỜ tự cung cấp URL — đây là
điều giữ thiết kế an toàn khỏi SSRF, khác với 1 tool "gọi URL bất kỳ".

Helper dùng chung: `src/lib/connectors/catalogApi.ts` (buildCatalogUrl, searchCatalog,
requireParams, findSpec, fetchJson) — dùng bởi cả 2 connector mới.

## 2 connector mới
1. **apilayer** (`src/lib/connectors/apilayer.ts`) — `auth.type: "token"`, 1 access_key
   dùng chung cho 9 sản phẩm APILayer mà user đã subscribe: ipstack, aviationstack,
   marketstack, positionstack, mediastack, countrylayer, serpstack, mailboxlayer,
   scrapestack. Base URL + path của TỪNG sản phẩm lấy từ docs.apilayer.com (trang
   SwaggerHub-backed thật, scrape qua `curl` vì trang render JS nên WebFetch không đọc
   được) — không đoán theo README.
2. **public_apis** (`src/lib/connectors/publicApis.ts`) — `auth.type: "none"`, 8 API
   không cần key, mỗi entry đã TEST LIVE bằng curl thật (không tin README).

## API đã thử nhưng LOẠI BỎ (verify thật cho thấy không dùng được)
- **Frankfurter**: không hỗ trợ VND (chỉ 29 tiền tệ ECB) → thay bằng
  `currency-api` (fawazahmed0, qua jsdelivr CDN) — free, có VND, test live OK.
- **REST Countries v3.1**: đã bị khai tử hoàn toàn (domain redirect sang dịch vụ mới,
  trả lỗi "This API version has been deprecated") → thay bằng `countrylayer_country`
  (APILayer, user đã có key).
- **Nominatim**: không gọi được từ môi trường dev hiện tại (DNS resolve về 127.0.0.1 —
  có thể là chặn mạng của sandbox) + có usage-policy rate-limit trong thực tế → thay
  bằng `positionstack_geocode` (APILayer).
- **ipapi.co**: bị rate-limit ngay ở lần test đầu tiên (free tier chia sẻ IP) → bỏ,
  dùng `ipstack_lookup` (APILayer, key riêng của user) thay thế.
- **balldontlie**: README ghi "No Auth" nhưng thực tế trả về "Unauthorized" — đã đổi
  sang yêu cầu key.
- **Goldprice.dev**: trả "Forbidden"; trang docs có tích hợp PayPal checkout → nghi đã
  chuyển sang trả phí.
- **Football Standings**: chỉ là code trên GitHub để tự host, không phải API online.
- **Noozra**: trang có CSP tích hợp PayPal → nghi ngờ là dịch vụ trả phí.

## Bài học
README của public-apis là do cộng đồng tự duy trì — nhãn "No Auth"/"Yes" không đáng tin
tuyệt đối. MỌI entry đưa vào catalog phải verify bằng cách gọi live (curl) hoặc đọc docs
thật (không phải trang README), không được suy diễn từ tên/mô tả.

## Việc đã hoãn (theo yêu cầu người dùng)
Trang quản lý bật/tắt từng API riêng lẻ trong catalog — người dùng đồng ý để sau, chưa
làm trong lần này. Hiện tại chỉ có bật/tắt ở cấp connector (qua trang /connectors có sẵn).

## File liên quan
- `src/lib/connectors/catalogApi.ts` (helper dùng chung, mới)
- `src/lib/connectors/apilayer.ts` + `apilayer.test.ts` (mới)
- `src/lib/connectors/publicApis.ts` + `publicApis.test.ts` (mới)
- `src/lib/connectors/registry.ts` + `registry.test.ts` (cập nhật: 12 connector, 46 tool)
