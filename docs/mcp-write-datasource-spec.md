# Spec: MCP write vào source database — describe / insert / playbook

**Ngày:** 2026-08-03
**Người yêu cầu:** LAAM team (use-case: "tạo employee mới", "tạo đơn hàng" qua chat/voice)
**Trạng thái:** Draft — chờ DAAB team review các quyết định mở ở §8
**Tiền đề:** spec `mcp-query-datasource` đã ship (branch `task/mcp-query-datasource`, verified e2e với LAAM).

---

## 1. Bối cảnh & mục tiêu

MCP hiện chỉ ĐỌC được rows của source DB (`kg_query_datasource`, pipeline sinh SELECT thuần).
Ghi vào source DB bị chặn có chủ đích (spec cũ §6 từ chối `kg_execute_sql`).

**Mục tiêu:** cho phép MCP consumer (LAAM) tạo dữ liệu vào source DB **connect trực tiếp**
một cách an toàn: model gom input từ hội thoại, server chịu trách nhiệm validation,
business rule, atomicity. Model KHÔNG BAO GIỜ soạn SQL ghi.

**Ngoài phạm vi:** UPDATE/DELETE rows (spec riêng nếu cần); write vào datasource
không có direct connection; write vào Knowledge Graph (đã có tools riêng).

## 2. Nguyên tắc thiết kế

1. **Opt-in per datasource:** cột mới `data_sources.allow_writes` (default `false`).
   Datasource không bật → mọi tool write trả 403 kèm lý do. Bật qua dashboard/PATCH (admin).
2. **Model không soạn SQL:** chỉ 2 hình thức ghi — insert đơn bảng có validate,
   hoặc gọi playbook có tên. Cả hai đều build SQL tham số hoá phía server.
3. **Rule 5 (AGENTS.md):** gom input từ hội thoại = judgment (model).
   Chuỗi insert + side-effect = deterministic (server).
4. **Fail loud:** thiếu trường bắt buộc / cột lạ / playbook stale → 400/409 với
   message liệt kê cụ thể, dạy model đường phục hồi (pattern đã dùng ở lỗi FK UUID).
5. **Write = RouteWrite:** không có readOnlyHint → LAAM hiện confirm-card. ĐÚNG UX
   cho hành động ghi; không "xếp Read cho tiện" như đã cân nhắc với query.

## 3. Tầng 1 — `kg_describe_table` (read, làm trước)

Trả metadata đủ để model biết "tạo X cần gì" và validate input người dùng TRƯỚC khi gọi write:

```json
{
  "table": "employees",
  "columns": [
    {"name": "employee_id", "type": "text", "required": true,  "pk": true},
    {"name": "store_id",    "type": "text", "required": false, "fk": "stores.store_id"},
    {"name": "hire_date",   "type": "date", "required": false, "max_length": null}
  ],
  "referenced_by": ["transactions.employee_id", "refunds.employee_id", "..."]
}
```

- `required` = `NOT NULL` và không có `column_default` (dữ liệu từ `source_columns`, có sẵn).
- Map REST: endpoint mới `GET /api/v1/data-sources/{id}/tables/{table}/describe`
  (đọc từ schema metadata store, không chạm source DB).
- Hữu ích độc lập với write (cải thiện cả NL query) — ship được riêng.

## 4. Tầng 2a — `kg_insert_datasource_row` (write, bảng độc lập)

Cho entity đơn giản không có side-effect (`customers`, `employees` sau khi team xác nhận):

- Input: `{data_source_id?, table, values{}}` (datasource fallback theo default project).
- Server validate theo metadata: cột lạ → 400 liệt kê; thiếu required → 400 liệt kê
  thiếu gì; vượt max_length / sai kiểu → 400. FK parent không tồn tại → lỗi FK DB
  map thành 400 kèm gợi ý ("store_id PH-009 không tồn tại — dùng kg_query_datasource
  để tra danh sách store").
- INSERT tham số hoá, single-use write connection, audit log (§7).
- **Chỉ chạy trên bảng được whitelist** trong cấu hình write của datasource (§8.2).

## 5. Tầng 2b — Playbook (write, flow đa bảng có business rule)

### 5.1 Định nghĩa

Playbook = write operation có tên, lưu server-side (bảng `write_playbooks`), version hoá:

```yaml
name: create_order
version: 3
status: approved            # draft | approved | stale | disabled
input:
  store_id:    {type: text, required: true,  fk: stores}
  employee_id: {type: text, required: true,  fk: employees}
  customer_id: {type: text, required: false, fk: customers}
  items:       {type: array, required: true, min: 1,
                item: {product_id: {fk: products}, qty: {type: int, min: 1}}}
steps:                       # chạy trong MỘT transaction — hỏng đâu rollback hết
  - insert: transactions     # id sinh server-side, map vào context
  - foreach items: insert transaction_items
  - foreach items: insert inventory_movements  # movement_type=SALE, quantity_change=-qty
  - insert: payments
```

MCP tools: `kg_list_playbooks` (read — tên + mô tả + input schema),
`kg_execute_playbook` (write — `{name, input{}}`).

### 5.2 AI đề xuất playbook từ schema (bootstrap)

Trả lời câu "làm sao biết cần bao nhiêu playbook": một analysis pass (tái dùng extraction
pipeline) phân loại bảng từ FK topology + naming + pattern dữ liệu:

| Tín hiệu | Suy ra | Ví dụ pharmacy |
|---|---|---|
| Nhiều FK trỏ VÀO, ít trỏ ra | Entity gốc → playbook `create_*` đơn | stores, products, customers, employees |
| B có FK về A + naming `A_items`/`A_lines` | Header–detail → playbook composite | transactions + transaction_items |
| Bảng có FK + timestamp + cột lượng | Ứng viên BƯỚC side-effect, không đứng riêng | inventory_movements, audit_events |
| Cột text khớp format id bảng khác + tương quan dấu/lượng | Side-effect ngầm (confidence score) | reference_id≈TXN-, quantity_change âm theo items |

Kết quả = playbook **draft** + confidence + evidence. **KHÔNG BAO GIỜ auto-approve** —
người review trên dashboard (tái dùng vòng đời draft→confirm/reject của KG edges).
Side-effect suy từ pattern bắt buộc có người xác nhận vì duyệt sai một write playbook
nguy hiểm hơn mọi lỗi đọc.

### 5.3 Chống drift: validate playbook theo sync-schema (BẮT BUỘC)

- Sau mỗi lần sync-schema: đối chiếu mọi playbook với `source_columns` mới.
  Bảng/cột biến mất, kiểu đổi → playbook chuyển `stale` kèm lý do cụ thể.
- Playbook `stale` từ chối chạy: 409 "create_order references dropped column X — needs review".
- Trạng thái hiện trên dashboard; `kg_list_playbooks` chỉ trả playbook `approved`.
- KG regenerate/update KHÔNG ảnh hưởng playbook (playbook bind vào schema thật, không bind node).

## 6. Hardening tiền đề (làm trong spec này)

- **Executor đọc hiện tại chưa enforce read-only ở tầng connection** (chỉ read-only
  by construction). Trước khi tồn tại bất kỳ write path nào: đọc phải set
  `default_transaction_read_only=on` (postgres) / `ApplicationIntent=ReadOnly` (mssql)
  để hai đường không bao giờ lẫn.
- Write connection tách riêng, single-use, timeout 30s như executor đọc.

## 7. Audit & an toàn

- Bảng `source_write_audit`: ai (key/user), datasource, playbook/table, input đã
  redact, row ids sinh ra, tx kết quả, timestamp. Ghi TRONG cùng transaction phía KG DB.
- RBAC: write yêu cầu role `developer`+ trên project (như submit query); cân nhắc
  role `admin` cho `kg_insert_datasource_row` bảng nhạy cảm (§8.3).
- Rate limit write per key (tránh model loop tạo hàng loạt).

## 8. Quyết định mở — cần team chốt trước khi code

1. **Phạm vi bước 1:** ship `kg_describe_table` + insert đơn bảng trước, playbook sau?
   (Đề xuất: CÓ — describe+insert là giá trị ngay, playbook cần bàn kỹ hơn.)
2. **Whitelist bảng cho insert đơn:** cấu hình per-datasource hay suy từ phân loại AI
   (entity gốc mới cho insert đơn)? (Đề xuất: cấu hình tường minh per-datasource.)
3. **Role cho write:** developer đủ, hay admin cho một số bảng? (Đề xuất: developer
   cho playbook approved; bảng trong whitelist thì developer.)
4. **Playbook DSL:** YAML trong DB (như phác ở §5.1) hay Go code có đăng ký?
   (Đề xuất: YAML declarative — validate máy được, AI đề xuất được, diff review được.)
5. **UPDATE/DELETE:** ngoài phạm vi spec này — xác nhận?

## 9. Acceptance criteria

1. Datasource `allow_writes=false` (default): mọi tool write 403 kèm lý do rõ.
2. `kg_describe_table('employees')` trả required/pk/fk đúng với metadata đã extract.
3. LAAM flow "tạo employee": model gọi describe → hỏi user đủ trường bắt buộc →
   `kg_insert_datasource_row` → confirm-card hiện → sau confirm, row có trong source DB
   + 1 dòng audit.
4. LAAM flow "tạo đơn 2 items": `kg_execute_playbook('create_order', …)` → transactions
   1 + transaction_items 2 + inventory_movements 2 (SALE, âm) + payments 1, TRONG một
   transaction; giết giữa chừng → rollback sạch.
5. Thiếu trường bắt buộc → 400 liệt kê đúng các trường thiếu (model relay được cho user).
6. Sau khi drop một cột đang được playbook dùng + sync-schema → playbook `stale`,
   `kg_execute_playbook` trả 409 nêu đúng cột; dashboard hiện cờ.
7. AI analysis trên pharmacy_demo đề xuất ≥4 playbook draft đúng phân loại ở §5.2,
   tất cả ở trạng thái draft (không cái nào tự chạy được).
8. Executor đọc từ chối chạy statement ghi (verify bằng test cố tình đưa INSERT).
