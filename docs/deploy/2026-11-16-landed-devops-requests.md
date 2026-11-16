# `ennam_landed` — việc cần DevOps hỗ trợ tiếp (16/11/2026)

Bổ sung cho handoff `envfiles/ennam-landed-handoff.md` (RDS dev-shared, ap-southeast-1). Tất cả chạy trên RDS bằng
**tài khoản master**. Không cần gửi lại mật khẩu: env của DAAB đã có đủ 4 tài khoản.

## Bước 1 — làm ngay, trước khi đội Ennam chạy migration

```sql
-- 1a. Sửa search_path. Hiện bị đặt thành MỘT schema tên "landed, public" (có ngoặc kép) không tồn tại:
--     cả 4 tài khoản đang có current_schema = NULL, migration sẽ lỗi ở câu CREATE TABLE đầu tiên.
--     Bảng của DAAB nằm trong schema public (code đọc public.landed_record), nên trả về mặc định.
ALTER ROLE landed_maintenance RESET search_path;
ALTER ROLE landed_writer      RESET search_path;
ALTER ROLE landed_engine      RESET search_path;
ALTER ROLE landed_ai          RESET search_path;

-- 1b. Tạm cho landed_maintenance chạy migration (bản 6 có ALTER ROLE landed_ai SET ...).
ALTER ROLE landed_maintenance CREATEROLE;
```

Kiểm tra: đăng nhập bằng `landed_maintenance`, `SELECT current_schema();` phải ra `public`.

Làm xong → báo đội Ennam. Đội Ennam chạy migration (~1–2 phút).

## Bước 2 — ngay sau khi đội Ennam báo migration xong

```sql
ALTER ROLE landed_maintenance NOCREATEROLE;
```

## Bước 3 — trước khi bật "hỏi tự do" trên prod (việc A trong handoff)

Chặn `landed_ai` (chạy SQL do AI sinh ra) vào các database khác trên cùng RDS. Với từng database
`ennam_kg`, `laam_db`, `ennam_admin`, `pharmacy_demo`:

```sql
-- chỉ khi tài khoản app của database đó KHÔNG phải owner
GRANT CONNECT ON DATABASE <db> TO <app user>;
-- sau đó
REVOKE CONNECT, TEMP ON DATABASE <db> FROM PUBLIC;
```

Làm **từng database một**, kiểm tra app của database đó vẫn chạy rồi mới sang database tiếp theo
(revoke khi app chưa có quyền riêng sẽ làm app mất kết nối).

Kiểm tra cuối — chỉ được trả về `ennam_landed`:

```sql
SELECT datname FROM pg_database
WHERE datallowconn AND has_database_privilege('landed_ai', datname, 'CONNECT');
```

## Không chặn đợt deploy này

Việc B–E trong handoff (parameter group, CloudWatch log, mã hoá ổ đĩa, cảnh báo dung lượng) làm sau.

## Ghi chú cho DevOps

- Schema `landed` và các `ALTER DEFAULT PRIVILEGES` trên nó sẽ không được dùng (bảng nằm trong `public`). Có thể
  để nguyên. Quyền SELECT mặc định cho `landed_ai` trên schema đó không mở được dữ liệu: mọi bảng gốc của DAAB
  bật RLS (FORCE) và không có chính sách nào cho `landed_ai`, nó chỉ đọc qua các view đã lọc theo cửa hàng.
- Không cấp `CREATEROLE` cố định cho `landed_maintenance`: trên PG15 quyền này sửa được mọi tài khoản không phải
  superuser của cả RDS dùng chung, còn mật khẩu `landed_maintenance` nằm trong env của DAAB.
- Mỗi lần có migration landed mới: lặp lại bước 1b → đội Ennam chạy → bước 2.

## Đội Ennam tự làm sau bước 2

Kiểm tra migration bản 6, deploy với env `LANDED_*` (đã có), kiểm log `landed ingest API enabled` và
`landed free questions are ready`, nạp dữ liệu demo T-log, thử "hỏi tự do" bằng owner và quản lý cửa hàng.
