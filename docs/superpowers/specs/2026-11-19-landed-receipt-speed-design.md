# Tăng tốc đọc dữ liệu landed (chứng từ + bằng chứng) — thiết kế

Ngày: 2026-11-19 · Nhánh: `task/improve_by_feedback_19112026` (ennam.kg.go, LAAM)

## Vì sao

Feedback của người dùng trên prod: mở chứng từ trong trang phát hiện mất **4,2–5,2 giây**, danh sách bằng chứng mất 1,4 giây (25 dòng)
và 2,3 giây (100 dòng). Chat dùng dữ liệu landed cũng chậm hơn bình thường.

Đo ở local (log SQL của Postgres, project T-log 48bd45cc, ~99 nghìn dòng `sale_line`):

- Khi mở chứng từ, route LAAM `findings/[id]/records/...` gọi `findingEvidenceHas` trước: nó tải lại bằng chứng của finding theo
  trang 200 dòng để kiểm tra chứng từ có thuộc finding không. Câu bằng chứng đó mất **~950 ms**; mọi câu đọc chứng từ cộng lại ~70 ms.
- Câu bằng chứng nối `sale ⨝ sale_line ON sale_id` và `LEFT JOIN product ON product_id`. Khoá nối đọc từ JSON
  (`NULLIF(src.data->>'sale_id','')`), không có index → Nested Loop quét lại ~99k dòng cho mỗi giao dịch (47 lần, 4,6 triệu so sánh).
- DAAB đọc landed bằng role `landed_engine` với RLS (FORCE). Hàm `->>` không leakproof nên Postgres **không dùng được index biểu
  thức trên JSON** dưới RLS (đã thử: admin 22 ms, `landed_engine` vẫn ~950 ms). Không thể đánh dấu leakproof trên RDS (không có superuser).
- Thử cột sinh sẵn (generated stored) `sale_id_key`/`product_id_key` + index, với đúng SQL compiler sinh ra (`CAST(CAST(src.sale_id_key AS text) AS text)`):
  **947 ms → 67 ms** dưới `landed_engine`; plan có `Index Cond: … sale_id_key = src.sale_id_key` và `product_id_key = …`. Thêm 2 cột ở local
  (~155 nghìn dòng) mất 4 giây.
- Chat có 2 đường đọc landed: (a) chỉ số / bằng chứng qua compiler (cùng `ColumnSQL`, tự hưởng lợi); (b) câu hỏi tự do — model viết SQL
  trên các view `security_barrier` của `landed_ai` (`internal/landed/aiviews.go`), view cũng đọc `r.data->>'sale_id'` → cùng bức tường.

## Mục tiêu

- Mở chứng từ trên prod còn ≲1 giây; danh sách bằng chứng nhanh hơn rõ rệt; câu chat nối giao dịch–dòng hàng–sản phẩm nhanh hơn.
- Kết quả mọi chỉ số / bằng chứng / chứng từ **không đổi** (cùng dòng, cùng thứ tự).

## Không làm (lần này)

- Lọc theo `business_date` để bỏ qua partition ngoài khoảng ngày (cần ánh xạ thời gian → `business_date` trong compiler; để sau, đo lại rồi tính).
- Đổi cách đọc `location_id` (cột sinh sẵn có từ 000006 nhưng không có NULLIF — ngữ nghĩa khác, không động vào).
- Không thay đổi RLS, role, hay quyền.

## Thiết kế

### DAAB (ennam.kg.go)

1. **Landed migration `000007_join_key_columns`**:
   - `ALTER TABLE landed_record ADD COLUMN sale_id_key text GENERATED ALWAYS AS (NULLIF(data->>'sale_id','')) STORED,
     ADD COLUMN product_id_key text GENERATED ALWAYS AS (NULLIF(data->>'product_id','')) STORED;`
   - Index `(project_id, entity, sale_id_key)` và `(project_id, entity, product_id_key)` trên bảng cha (tự tạo trên mọi partition).
   - Không cần grant (giống 000002/000006). Down: drop index rồi drop cột.
   - NULLIF giữ đúng ngữ nghĩa của `ColumnSQL` hiện tại (chuỗi rỗng → NULL).
2. **`landedsource.Table.ColumnSQL`**: với field `sale_id` / `product_id` kiểu text, khi cột khoá có trong DB → trả `src.sale_id_key` /
   `src.product_id_key` (cột trần, để `=` dùng được index dưới RLS). Các field khác giữ nguyên.
3. **An toàn khi deploy lệch**: landed migration trên RDS chạy tay (DevOps). Resolver kiểm tra **một lần mỗi process** (pg_attribute,
   có cache; lỗi → coi như chưa có, thử lại lần sau) xem `landed_record` đã có các cột khoá chưa; chưa có → giữ biểu thức JSON như cũ.
   Code mới chạy trước migration vẫn đúng, chỉ chưa nhanh. Kết quả "có" được nhớ mãi; "chưa có" chỉ nhớ ~2 phút rồi kiểm lại, để
   migration chạy sau vẫn có hiệu lực mà không cần restart.

4. **View AI (`aiviews.go` `viewDDL`)**: khi cột khoá có trong DB, view lấy `r.sale_id_key AS sale_id`, `r.product_id_key AS product_id`
   (giống cách đang lấy `r.location_id`). Hệ quả nhỏ: giá trị rỗng `''` của hai cột này trong view thành NULL (id rỗng là dữ liệu hỏng).
   View được tạo lại lúc DAAB khởi động / khi đổi pack — vì vậy migration chạy **trước** khi deploy DAAB mới.

### LAAM

5. **`findingEvidenceHas`** (`src/lib/intel/records.ts`): trang đầu 25 dòng (bằng trang người dùng đang xem), sau đó các trang 200 như cũ,
   tổng vẫn tối đa `EVIDENCE_MAX_ROWS` = 500 dòng.
6. **Route `findings/[id]/records/[entity]/[recordId]`**: chạy kiểm tra thuộc-finding và `getRecord` **song song**; chỉ trả chứng từ khi
   kiểm tra đúng. Kiểm tra sai → **luôn 404**, kể cả khi `getRecord` lỗi (không để lỗi của DAAB lộ ra thành 500 cho người không có quyền);
   kết quả `getRecord` bị bỏ. Quy tắc truy cập không đổi; các case cách ly hiện có của route phải giữ xanh.

## Rủi ro và thứ tự deploy

- Thứ tự: (1) chạy landed migration 000007 trên RDS lúc vắng (thủ công, như 000006); (2) deploy DAAB; (3) deploy LAAM. Migration không
  ảnh hưởng code cũ (cột mới không ai đọc).

- Migration 000007 **viết lại toàn bộ `landed_record`** (thêm cột STORED) và khoá bảng trong lúc chạy → làm lúc vắng; ghi vào checklist
  deploy. Ingest trong lúc đó bị chờ, không mất dữ liệu.
- Thêm 2 cột + 2 index → dung lượng bảng tăng nhẹ.

## Kiểm chứng

- Test tích hợp landed hiện có (parity landed ↔ file, resolver, RLS) phải xanh trên Postgres 15; thêm test: có cột → `ColumnSQL` dùng
  cột khoá; không có cột → biểu thức JSON; kết quả bằng chứng giống hệt trước/sau.
- Test DB phải thực sự chạy (`-v`, không SKIP; DB dev ở 5433), trên Postgres 15 như prod.
- EXPLAIN dưới `landed_engine`: câu bằng chứng finding PH-005 dùng index, < 100 ms ở local.
- LAAM: unit test cho trang đầu 25 + song song (sai thuộc-finding → 404, không lộ chứng từ).
- Sau deploy: đo lại trên prod (chứng từ, bằng chứng 25/100, một câu chat có nối dòng hàng).
