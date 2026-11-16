# Bật "hỏi tự do" trên production với dữ liệu demo (sau deploy thứ Hai 16/11/2026)

Mục tiêu: tạo kho T-log `ennam_landed` trên RDS, nạp dữ liệu demo (giả lập, không có khách thật) vào **một project
demo**, rồi bật "hỏi tự do". Các project khác không bị ảnh hưởng: chỉ project có dữ liệu trong kho T-log mới có
nguồn "Landed (system)".

Làm **sau khi** deploy thứ Hai đã chạy ổn với cờ tắt (checklist `2026-11-16-task-pos-data-model-checklist.md`).

## A. Devops — tạo kho T-log trên RDS (một lần)

Chạy bằng tài khoản master RDS, psql ≥ 15. Thay `<...>` bằng mật khẩu mạnh, lưu vào secret manager.

```sql
-- 1. DB và 4 tài khoản (không chạy nguyên file scripts/landed/init.sql trên RDS)
CREATE DATABASE ennam_landed;
CREATE ROLE landed_maintenance LOGIN PASSWORD '<maint_pw>'  NOBYPASSRLS;
CREATE ROLE landed_writer      LOGIN PASSWORD '<writer_pw>' NOBYPASSRLS;
CREATE ROLE landed_engine      LOGIN PASSWORD '<engine_pw>' NOBYPASSRLS;
CREATE ROLE landed_ai NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION;
-- 2. Bắt buộc trên RDS Postgres 15 trước khi chạy migration
GRANT landed_maintenance TO <tài khoản master>;
```

```bash
# 3. Migration kho landed tới 000006 (kho mới còn trống nên chạy nhanh). Từ ennam.kg.go, KG_DB_* = tài khoản master RDS
KG_DB_HOST=<rds-host> KG_DB_PORT=5432 KG_DB_USER=<master> KG_DB_PASSWORD=<...> KG_DB_SSLMODE=require \
  make landed-migrate LANDED_DB_NAME=ennam_landed
# Trên RDS sẽ có vài WARNING về quyền pg_catalog — bình thường (quy tắc chặn SQL thay thế).

# 4. Mật khẩu cho tài khoản AI (đọc từ biến môi trường, không ghi vào file)
LANDED_AI_PASSWORD='<ai_pw>' psql "host=<rds-host> dbname=postgres user=<master> sslmode=require" \
  -v ON_ERROR_STOP=1 -f scripts/landed/ai-role.sql
# WARNING "temp_file_limit not set" trên RDS là bình thường.
```

5. (Nên làm) Chặn tài khoản landed vào các DB khác cùng RDS. **Kiểm tra trước** từng DB `ennam_kg`, `laam_db`,
   `pharmacy_demo`…: tài khoản ứng dụng đang dùng DB đó là owner hoặc có `GRANT CONNECT` riêng
   (`SELECT datname, datacl, pg_get_userbyid(datdba) FROM pg_database;`). Nếu chưa: `GRANT CONNECT ON DATABASE <db> TO <app user>;`
   rồi mới `REVOKE CONNECT, TEMP ON DATABASE <db> FROM PUBLIC;`. Không chắc thì bỏ qua bước này — không ảnh hưởng chức năng.

## B. Devops — biến môi trường

File upload T-log dùng **chung kho lưu file (S3) đã cấu hình cho DAAB**; worker tải file qua API của DAAB. Không cần
cấu hình S3 mới.

kg-server (DAAB):

| Biến | Giá trị |
|---|---|
| `LANDED_DATABASE_URL` | `postgres://landed_maintenance:<maint_pw>@<rds-host>:5432/ennam_landed?sslmode=require` |
| `LANDED_WRITER_URL` | `postgres://landed_writer:<writer_pw>@<rds-host>:5432/ennam_landed?sslmode=require` |
| `LANDED_ENGINE_URL` | `postgres://landed_engine:<engine_pw>@<rds-host>:5432/ennam_landed?sslmode=require` |
| `LANDED_AI_URL` | `postgres://landed_ai:<ai_pw>@<rds-host>:5432/ennam_landed?sslmode=require` |
| `LANDED_CTX_KEYS` | `k1:<base64 của 32 byte ngẫu nhiên>` (ví dụ `k1:$(openssl rand -base64 32)`) |
| `LANDED_NL_QUERY` | **để trống lúc đầu**; đặt `1` ở bước D |

Worker Python (ennam.kg.python): `LANDED_WRITER_URL` = như trên (cùng giá trị). `LANDED_QUEUE_NAME` giữ mặc định ở
cả hai bên.

LAAM (bước D): `LANDED_FREE_QUESTIONS=1`, `INTEL_DIRECT_QUERY_TOOLS=kg_query_datasource,kg_query_datasource_status`.

Khởi động lại kg-server và worker. Log kg-server phải có `landed ingest API enabled`.

## C. Nạp dữ liệu demo (bên mình làm)

1. Tạo (hoặc chọn) **project demo** trên prod, bật pack `retail` + `pharmacy` 0.7.0.
2. **Bật nguồn T-log trên giao diện** (bắt buộc làm tay, API key không làm được): đăng nhập DAAB bằng tài khoản admin hệ thống → project demo → tab **POS data** → bật, ghi chú đồng ý "synthetic demo data".
3. Chạy từ máy có dữ liệu demo (5 cửa hàng PH-001..005, tháng 10/2026, 150 file T-log + 3 file danh mục):

```bash
DAAB_URL=https://<daab-prod> DAAB_API_KEY=<admin API key> PROJECT_ID=<project demo> \
DEMO_DATA_DIR=<thư mục có master/ và poslog30/> \
  uv run --project ennam.kg.python python scripts/landed/load-demo-data.py
```

Nếu quên bước 2, script dừng và nhắc bật trên giao diện. Script đi qua đường nạp chính thức (upload → worker → kho), chạy lại không nạp trùng, rồi chuyển chỉ số của project
sang nguồn T-log và tính lại tháng 10.

4. Trong LAAM: owner của project demo, và một tài khoản cửa hàng trưởng được giao **một** cửa hàng (ví dụ PH-001).

   **Lưu ý về kết nối LAAM → project T-log** (gặp trên local 16/11):
   - Bật nguồn T-log tự động bật `delegation_required` cho project. Từ đó DAAB chỉ trả dữ liệu cho lời gọi có vé phân
     quyền (`X-KG-Delegation`), và LAAM chỉ gắn vé lên **kết nối cấp tổ chức** do Ennam Admin cấp.
   - Connector DAAB cá nhân (trang Connectors) **không** có vé → daily check lỗi `kg_get_data_status: Permission denied`
     (log DAAB: `delegation enforcement denied reason=no_ticket`), danh sách cửa hàng để gán cũng trống.
   - **Org nội bộ** của LAAM (`LAAM_INTERNAL_ORG_ID`) không đồng bộ kết nối từ Admin, nên chỉ có connector cá nhân.
   - Cách làm đúng: tạo business project demo trong một **org khách** có kết nối DAAB do Ennam Admin cấp, trỏ đúng
     project T-log; đặt `KG_DELEGATION_KEYS` (DAAB) = `DAAB_DELEGATION_KEYS` (LAAM).
   - Tạm thời cho org nội bộ (chỉ demo, mất lớp chặn cửa hàng ở DAAB):
     `UPDATE projects SET delegation_required=false WHERE id='<project demo>';`
   - Danh sách cửa hàng ở "Gán cửa hàng" lấy từ các cửa hàng **đã xuất hiện trong kết quả kiểm tra**; sau lần chạy đầu
     có thể chỉ thấy vài cửa hàng, các lần chạy sau sẽ bổ sung.

## D. Bật "hỏi tự do"

1. DAAB: `LANDED_NL_QUERY=1`, khởi động lại. Log phải có `landed free questions are ready` (trên RDS kèm một WARN
   `items covered by the SQL guard` — bình thường). Nếu không ready, log ghi rõ điều kiện còn thiếu.
2. LAAM: đặt hai biến ở mục B, khởi động lại.
3. Kiểm tra:
   - owner hỏi "Tháng 10/2026, thứ mấy có nhiều giao dịch nhất?" → có số; log DAAB `free question executed`.
   - cửa hàng trưởng hỏi câu tương tự → chỉ số của cửa hàng mình; hỏi cửa hàng khác → bị từ chối.

## Rollback

- Tắt nhanh: bỏ `LANDED_NL_QUERY` (DAAB) và `LANDED_FREE_QUESTIONS` (LAAM), khởi động lại. Mọi thứ về như trước.
- Xoá dữ liệu demo: trong project demo, tắt nguồn T-log và chọn xoá dữ liệu (purge).
