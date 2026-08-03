# Migration 000080 collision — mysql/mariadb pair renumbered to 000083

**Từ:** claude (DAAB) · **Tới:** dev làm mysql/mariadb support (`schema_querier_mysql.go`) · **Ngày:** 2026-08-03

Hai PR song song cùng lấy số 000080:
- `000080_ai_queries_clarification_status` (PR #16, merge TRƯỚC, đã áp lên DB dev :5433 — version 80)
- `000080_add_mysql_mariadb_db_type` (merge sau)

golang-migrate coi duplicate là fatal → **auto-migration trên main đã gãy** ("duplicate migration file"), server chỉ WARN rồi chạy tiếp với schema cũ — 000081 (widen) cũng không được áp cho tới khi sửa.

**Đã sửa** trên branch `task/mcp-write-datasource`: `git mv` cặp mysql → **000083** (giữ nguyên nội dung). DB dev :5433 giờ áp sạch 81→82→83, version=83.

**Action cho bạn:** nếu môi trường local của bạn đã áp bản mysql như version 80 thì DB bạn sẽ KHÔNG tự áp `ai_queries_clarification_status` (số 80 đã bị "tiêu") — cần áp tay phần đó (ALTER constraint ai_queries_status_check thêm 'clarification_needed') hoặc reset schema_migrations về 79 rồi migrate lại. Kiểm tra: `SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ai_queries_status_check';` — nếu thiếu 'clarification_needed' là dính.

Đề xuất quy ước tránh tái diễn: trước khi tạo migration mới, `git fetch origin main` và lấy số theo main mới nhất; hoặc dùng timestamp-style numbering (đổi lớn, cần bàn).

→ Move file này vào comms/resolved/ khi bạn xác nhận env ổn.
