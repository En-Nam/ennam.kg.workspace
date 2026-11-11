# T-log ingestion & `landed` mode — thiết kế

**Ngày:** 2026-11-11 · **Trạng thái:** Draft rev 3 (sau 2 vòng review độc lập) — Phase 1 build được với mặc định §9b; dữ liệu thật chờ WS0; Phase 2 chờ AIOS (§10)
**Nguồn yêu cầu:** `AIOS_POS_Standard_Data_Model_Requirements.docx` (Johnny Custer, 2026-11-05) · Trello card *[Data Foundation] Standard POS Data Model & T-Log Mapping — AIO Analytics*
**Kế thừa:** `2026-09-25-industry-pack-proactive-intelligence-design.md` (D4, D6, D10, §6.1, §6.3, §12b, §14.4)

---

## 1. Mục tiêu

Nhận t-log từ nhiều hãng POS, chuyển về **một model chuẩn**, lưu lại để DAAB tính metric và LAAM phân tích — không build riêng cho từng khách.

**Không thuộc phạm vi:** đổi engine metric/LAAM, cross-source join giữa hai DB khách, real-time streaming (batch theo lô trước).

## 2. Sự thật đã xác minh trong code

| # | Sự thật | Vị trí |
|---|---|---|
| F1 | Chỉ `live` + `file` có resolver; `landed` mới là hằng số | `ennam.kg.go/internal/intel/sources/sources.go` (`Build`), `internal/intel/types.go:19` |
| F2 | `metric_value.source_mode` đã cho phép `'landed'`; **`project_mapping.mode` thì KHÔNG** (`CHECK (mode IN ('live','file'))`) | `db/migrations/000090…:11`, `000089…` |
| F3 | Một entity = một mapping (`UNIQUE (project_id, entity)`) → live không gộp nhiều hãng POS | `000089`, `types.go:124` |
| F4 | Metric bị tắt nếu entity cần dùng nằm ở khác `LocationKey` (no cross-source join) | `internal/intel/engine/availability.go:62` |
| F5 | Mode `file` lưu dòng dạng `data JSONB` trong bảng chung, đọc qua `SourceTable.ColumnSQL = (src.data->>'x')` | `000092_file_tables`, `internal/intel/filedata/source_table.go` |
| F6 | `SourceExecutor` load data source (có `ProjectID`), chạy mọi query trong tx READ ONLY + `set_config(..., true)` | `internal/service/source_executor.go:203-272` |
| F7 | Đã có `storage.ObjectStorage` (local / S3) cho file upload | `internal/storage/storage.go` |
| F8 | Parse file đã đi qua Python indexer (`POST /api/v1/tabular/parse`) | `filedata/parser_client.go`, `ennam.kg.python/src/ennam_kg/api/tabular.py:97` |
| F9 | Mode switch nằm ở nhiều chỗ: `sources.Build`, `admin.ModeBinder`, `mapping_file.go`, `mapdraft`, `admin/mapping_coverage` | `internal/intel/...` |
| F10 | `requireProjectAccess` vẫn cho request không xác thực đi qua | `internal/handler/authz.go:36-38` |
| F11 | Metric hiện có `requires: [void]`, `[refund]`, `[price_override]`, `[receipt_print]` | `ennam.kg.packs/retail/daab/metrics/*.sql` |
| F12 | Spec gốc D10: core không chứa từ ngữ ngành (sale/claim/pharmacy…) | spec 2026-09-25 §3 |

## 3. Quyết định

| ID | Quyết định | Lý do |
|---|---|---|
| L1 | Thêm mode **`landed`** = dữ liệu do mình lưu, đã chuẩn hoá. Đổi `live ⇄ landed` không sửa pack/LAAM | Điểm nối đã chừa (§12b spec gốc) |
| L2 | **DB landed tách khỏi DB DAAB** — giai đoạn đầu là database riêng trên cùng instance Postgres; connection cấu hình cấp hệ thống (`LANDED_DATABASE_URL`) | Khối lượng, kiểu tải, vòng đời, pháp lý khác DB DAAB |
| L3 | **Lưu trữ trung tính ngành**: bảng chung `landed_record (… entity, data JSONB)` theo mẫu `file_dataset_row` — **không** tạo bảng `sale`/`sale_line`/`claim` trong core | D10 + F5. ⚠ Thay cho đề xuất cũ "~21 bảng viết tay" |
| L4 | Mỗi project có **schema view canonical** `pv_<uuid>` sinh tự động từ pack (view lọc sẵn `project_id`, owner = role maintenance, **không** `security_invoker`) — chỉ để NL→SQL đọc | AI viết SQL trên `data->>'x'` rất kém |
| L5 | **Cô lập tenant bằng role DB, không bằng biến session.** Mỗi project một login role `lp_<uuid>` (NOLOGIN→LOGIN, `NOBYPASSRLS`), chỉ có `USAGE` trên schema `pv_<uuid>` + `SELECT` các view của nó, **không** có quyền gì trên bảng gốc/partition. Mật khẩu role lưu mã hoá trong data source system của project. Engine metric (Go) dùng role `landed_engine` + RLS theo `current_setting('app.project_id')` do code đặt (SQL của pack, không phải SQL do AI viết) | Review 2026-11-11: `set_config` gọi được bên trong SELECT ⇒ biến session không chặn được SQL do AI viết; Python agentic/stream nối thẳng bằng DSN ⇒ chỉ role DB chặn được mọi đường |
| L6 | **Bronze = file gốc trên ObjectStorage (S3)**; Postgres chỉ giữ batch/checksum/trạng thái | Reuse F7; Postgres không phình |
| L7 | **Partition `landed_record` theo `business_date` (tháng)** ngay từ đầu | Query theo ngày nhanh; retention/xoá = drop partition |
| L8 | **Parse ở Python worker**; 1 parser **ARTS POSLog** + parser riêng cho hãng không theo chuẩn; crosswalk = YAML có version theo hãng/version POS | Theo F8; POSLog được dùng rộng (vd PharmX AU) |
| L9 | Canonical bump **0.7.0 = MINOR, chỉ thêm**; giữ `void`/`refund`/`price_override`/`receipt_print` | F11 — gộp vào `line_type` sẽ là MAJOR, vỡ Pharmacy Chain |
| L10 | Cờ RX là **field của pack pharmacy** (`is_rx` extend trên sale, sale_line, tender, void, refund, sale_adjustment, register_event); loại sự kiện RX thêm bằng cách pack pharmacy **khai báo lại enum** (`mergeEnums` ghi đè, `pack.go:525`) với đủ giá trị retail + RX. RX ước lượng & giao riêng, chờ Q4 + pháp lý | D10; rủi ro HIPAA |
| L13 | Worker **không đọc pack/ObjectStorage trực tiếp**: Go gửi kèm job snapshot catalog (entities/enums) + crosswalk đã merge; worker tải file gốc qua Go (`kg_client`, như `upload_files.py`); xong batch gọi `POST /api/v1/projects/{id}/metrics/recalculate` | Tránh lệch logic merge pack giữa Go/Python; giữ quy ước hiện có |
| L14 | Route và tên module trung tính, không trùng KG ingest: API core `/api/v1/projects/{id}/landed/*` (không dùng "pos" — từ ngành, D10); Python package `ennam_kg.landed_ingest`; queue riêng `ennam-kg:landed` + job dọn batch kẹt (`processing` > 30 phút ⇒ `failed`, có thể replay) | `/ingest/*` đã dùng cho KG ingest (`ingest_public.go:44`); BRPOP không ack |
| L11 | Bật landed = **admin hệ thống**, kèm ghi nhận đồng ý pháp lý; khách không tự bật | Lưu dữ liệu khách cần hợp đồng/DPA |
| L12 | Master data cùng chỗ với giao dịch: **upload vào landed** trước; **pull copy (watermark)** sau | F4 |

## 4. Kiến trúc

```
POS NCR / Square / … ─(file drop | API | DB export)─▶ Ingest API (Go) ─▶ ObjectStorage: raw/<project>/<feed>/<batch>  [Bronze]
                                                         │ enqueue (Redis)
                                                         ▼
                                     Python worker: parser (POSLog | vendor) → crosswalk(feed, version)
                                       → validate theo canonical → dedup/upsert
                                         ├─▶ landed_record      [Silver]  (partition theo tháng, RLS)
                                         ├─▶ landed_unmapped    field/mã chưa map
                                         └─▶ landed_reject      giao dịch hỏng/thiếu
                                                         │
DAAB intel: landed resolver (SourceTable trên landed_record) → metric_value  [Gold] → kg_get_metrics/evidence/record → LAAM
DAAB NL→SQL: data source kind=system → view canonical theo project (RLS) → kg_query_datasource → LAAM
```

## 5. Schema DB landed (core, trung tính ngành)

| Bảng | Cột chính | Ghi chú |
|---|---|---|
| `ingest_feed` | id, project_id, name, vendor, format (`poslog`/`vendor:<x>`), crosswalk_version, status | Mỗi hãng POS của project = 1 feed |
| `ingest_batch` | id, feed_id, project_id, object_key, sha256, received_at, status, counts (ok/dup/reject/unmapped), error | Idempotent theo sha256 |
| `landed_record` | id, project_id, source_id (feed), entity, business_date, natural_key, data JSONB, batch_id, version, ingested_at | Partition theo `business_date` (+ partition `DEFAULT`); **chỉ giữ bản hiện hành**; unique `(project_id, source_id, entity, natural_key)` nằm ở bảng `landed_key` (không partition) để giao dịch đổi ngày vẫn là một |
| `landed_key` | project_id, source_id, entity, natural_key, business_date, record_id, version | Chốt chống trùng toàn cục; đổi ngày ⇒ xoá bản ở partition cũ, ghi partition mới trong cùng transaction |
| `landed_record_history` | các cột như `landed_record` + superseded_at, superseded_by_batch | Bản cũ khi giao dịch bị gửi lại có nội dung khác |
| `feed_field_coverage` | project_id, feed_id, entity, field, seen_count, last_seen_at | Field nào feed thực sự gửi — dùng cho "unavailable" (§9c R3) |
| `landed_unmapped` | project_id, feed_id, batch_id, path/code, sample, count, first_seen, last_seen | Spec rule 6 |
| `landed_reject` | project_id, batch_id, reason, raw_ref | Giao dịch cụt/lệch header-footer |
| `sync_state` | project_id, data_source_id, table, watermark, last_success_at | Cho pull copy (Phase 3) |

- `natural_key` = JSON array các giá trị key do crosswalk khai báo (vd `["05","2","T0001"]`), lưu dạng text chuẩn hoá — không nối bằng `|` (tránh va chạm).
- Replay cùng key, cùng nội dung ⇒ bỏ qua; khác nội dung ⇒ chép bản cũ sang `landed_record_history`, ghi đè bản hiện hành, `version+1`.
- **Role DB (3 + 1/project):** `landed_maintenance` (owner: migration, partition, view, purge, tạo role project) · `landed_writer` (worker + Go ingest API: INSERT/UPDATE/DELETE trên bảng ingest/landed, qua RLS) · `landed_engine` (Go metric/evidence: SELECT qua RLS) · `lp_<uuid>` (NL→SQL: chỉ view của project mình).
- RLS: `ENABLE` + `FORCE` trên bảng cha **và mọi partition**; policy `project_id = NULLIF(current_setting('app.project_id', true), '')::uuid`; không grant gì trên partition cho role ngoài maintenance.
- Policy theo role: `project_isolation` (`TO landed_writer, landed_engine`) như trên; `maintenance_all` (`TO landed_maintenance USING (true)`). View `pv_<uuid>.*` do `landed_maintenance` sở hữu, `WITH (security_barrier = true)` (chặn đẩy filter của người dùng xuống dưới filter tenant — rò dữ liệu qua thông báo lỗi), chạy với quyền owner và **lọc cứng `project_id = '<uuid>'` trong định nghĩa view**. Role `lp_` thêm: `default_transaction_read_only = on`, `CONNECT` chỉ vào `ennam_landed` (các DB khác `REVOKE CONNECT, TEMP FROM PUBLIC`), `EXECUTE` hàm public bị thu hồi, mật khẩu đặt bằng SCRAM verifier ⇒ SQL do AI viết không đổi được filter, kể cả khi tự gọi `set_config`.
- Partition: tạo trước 2 tháng tới; partition `DEFAULT` hứng ngày ngoài khoảng (backfill), job hằng ngày tách dữ liệu DEFAULT ra partition tháng.

## 5b. Crosswalk (field t-log → field canonical)

- **Tầng 1 — mẫu theo hãng/version POS** (`poslog-6.0`, `ncr-…`, `square-…`): YAML có version, lưu cùng `ennam.kg.packs` (thư mục `crosswalks/`), publish qua registry; khai báo `canonical: <pack>@<version>`.
- **Tầng 2 — override theo feed**: lưu DB (`ingest_crosswalk_override`, gắn `ingest_feed`), chỉ phần khác mẫu (mã lý do, tender code riêng…), có version.
- Nội dung: `each` (đường dẫn lặp ra từng record), `natural_key`, `fields` (path → field canonical, cho phép biểu thức đơn giản), `enum_map` (mã hãng → mã chuẩn).
- `ingest_batch` ghi crosswalk version đã dùng; sửa crosswalk ⇒ replay từ raw trên ObjectStorage.
- UI (tab Data ingestion → feed → Crosswalk): bảng field chuẩn ↔ path, trạng thái Have/Partial/Missing, "Prepare with AI" (reuse `mapdraft`, chỉ đọc cấu trúc file mẫu), danh sách unmapped bấm-để-gắn, nút replay.
- Field không có trong crosswalk ⇒ `landed_unmapped`.

## 6. Workstreams

### WS0 — Điều kiện trước dữ liệu thật (BLOCKER)
- Đóng pass-through không xác thực của `requireProjectAccess` (F10, §14.4 spec gốc).
- Quyền theo chi nhánh trong DAAB (I9, §14.4).
- Sửa IDOR GenerateKG cross-project (đã ghi nhận trước đó).
- Pháp lý: DPA với AIOS/retailer; BAA nếu RX có PHI; data residency (AU).

### WS1 — Canonical 0.7.0 (`ennam.kg.packs`) — *làm ngay*
- `sale`: thêm `terminal_id`, `ended_at`, `transaction_type`, `training_flag`, `manager_id`, `loyalty_id`, `total_due`, `change_due`.
- `sale_line`: thêm `line_seq`, `line_type`, `line_at`, `weight`, `extended_amount`, `department`, `entry_method` (scanned/keyed), `reason_code`, `orig_sale_ref`, `promo_type` (hosted TPR / manual).
- Entity mới: `tender` (type, amount, seq), `register_event` (no_sale, suspend, recall, paid_in, paid_out[_subtype], gift_card_activate/renew, lock, mgmt_intervention, timings).
- `void`/`refund`/`price_override`: thêm `void_kind` (line/cancel/post_void), `reason_code`, `item_count`.
- Pharmacy: `is_rx` trên sale/sale_line, `register_event` RX (pharmacist_intervention, delivery_fee), `copay_refusal`.
- Metric Sales Capture & Sales Reducing (Value/Cust/Items cho mọi reducing fn) + quy tắc đảo/chồng (không đếm trùng); "missing ⇒ unavailable, không phải 0".
- Data dictionary (nghĩa, kiểu, required, grain, dấu) + CHANGELOG + version bump.

### WS2 — Crosswalk & gap analysis — *làm ngay (phần canonical), phần mẫu chờ AIOS*
- Bảng Have / Partial / Missing: spec AIOS ↔ canonical 0.6.0/0.7.0.
- Khi có mẫu: crosswalk POS của AIOS + 1 POS retailer mục tiêu.

### WS3 — DB landed (Go, `ennam.kg.go`)
- Config `LANDED_DATABASE_URL` (+ docker-compose service/db, envfiles).
- Thư mục migration riêng cho landed; bảng §5; RLS FORCE; roles; job tạo partition tháng tới + drop theo retention.

### WS4 — Ingestion pipeline
- Go: API nhận batch (upload / API push) → ObjectStorage → `ingest_batch` → enqueue; endpoint replay batch.
- Python worker: parser POSLog (6.0 + extension), framework parser vendor, crosswalk YAML có version, validate theo canonical (reuse logic `filedata/validate`), upsert/dedup, unmapped, reject, header↔footer & line-sum reconciliation, báo cáo batch.
- (Sau) SFTP/file-drop watcher; DB-export pull.

### WS5 — DAAB integration (Go)
- Migration: `project_mapping.mode` thêm `'landed'` (F2).
- `intel/landedsource`: `SourceResolver` + `SourceTable` trên `landed_record` (`Filter = project_id AND entity`, `ColumnSQL = data->>…`), executor trên reader role với `app.project_id`.
- Đăng ký ở mọi điểm switch mode (F9): `sources.Build`, `admin.ModeBinder`, `mapping_file.go`, `mapdraft`, `mapping_coverage`; `LocationKey` = `landed:<project>`.
- Mapping landed sinh tự động 1:1 khi bật; `data_status` lấy độ tươi từ `ingest_batch`.
- Parity test landed vs file (theo mẫu `filedata/parity_*_test.go`).

### WS6 — Hỏi tự do trên landed
- `data_sources.kind` (`customer` | `system`); tự tạo 1 data source system/project khi bật landed; UI ẩn sửa/xoá.
- Sinh view canonical per project (L4), schema sync đọc view.
- Data source system dùng **login role riêng của project** (`lp_<uuid>`, L5) — không dựa vào `set_config`; mọi đường (SourceExecutor, Python agentic/stream qua DSN) đều bị DB chặn.
- Test: SQL không có `WHERE`, SQL tự gọi `set_config('app.project_id', <project khác>)`, SQL đọc thẳng `landed_record`/partition/schema project khác ⇒ đều không thấy dữ liệu khác.

### WS7 — Master data
- Upload danh mục (product/employee/location) vào landed (reuse tabular parse F8).
- Pull copy theo watermark từ data source khách, chỉ bảng/cột đã map (`sync_state`).

### WS8 — UI (DAAB web)
- Tab **Data ingestion** (admin): bật landed + ghi nhận consent; danh sách feed; batch & thống kê; unmapped; reject; replay.
- **Data mapping**: thêm nguồn `landed`; cảnh báo metric bị tắt do khác nguồn (lý do từ `Availability`).
- **Data Sources**: dòng "Landed (system)" chỉ đọc.

### WS9 — Vận hành
- Retention theo project (mặc định đủ YoY, chờ AIOS); revoke ⇒ chuyển về live/xoá dữ liệu landed + raw, giữ `metric_value`, log xác nhận.
- Backup DB landed, lifecycle S3, monitor lag/batch lỗi.

### WS10 — QA (theo card)
- Case: bán thường, nhiều đơn vị/cân ký, split tender, discount/coupon, void, refund, cancel, post void, thiếu field, replay trùng, giao dịch cụt.
- Đối soát: detail ↔ tổng nguồn ↔ summary cashier/store/day.
- Cùng bộ báo cáo chạy trên 2 mapping POS khác nhau.

## 7. Phase

| Phase | Nội dung | Điều kiện |
|---|---|---|
| **P0** | WS1, WS2 (phần canonical), gửi câu hỏi AIOS, bắt đầu WS0 | Không |
| **P1** | WS3, WS4 (1 feed), WS5, WS8 (tối thiểu), WS10 → đạt acceptance của card | AIOS trả lời §10 Q1–Q3; WS0 xong trước khi nhận dữ liệu thật |
| **P2** | WS6 (NL→SQL trên landed) | P1 |
| **P3** | WS7 pull copy, feed thứ 2+ | Có khách cần |
| **RX** | Phần pharmacy của WS1/WS10 | Quyết định Q4 + pháp lý |

## 8. Mở rộng / thay đổi

| Khi | Làm | Không đụng |
|---|---|---|
| Hãng POS mới | Feed + parser (nếu không POSLog) + crosswalk | Schema, pack, LAAM |
| Field mới | Ghi vào `data`, thêm vào canonical (MINOR) | Schema DB |
| Ngành mới | Pack mới | Core, schema DB |
| Đổi region / server | Đổi `LANDED_DATABASE_URL` (hoặc map project → instance) | Code |
| Hiệu năng không đủ | Expression index / cột generated cho field nóng; sau cùng mới cân nhắc kho cột | Pack, LAAM |
| Khách rút quyền | `landed → live`, xoá landed + raw | Pack, LAAM |

## 9. Rủi ro

- JSONB chậm hơn cột có kiểu → partition + index `(project_id, entity, business_date)` + expression index khi đo thấy cần.
- View/RLS sai ⇒ rò dữ liệu → test bắt buộc ở WS6, review security.
- POSLog extension mỗi hãng khác ⇒ crosswalk theo version, unmapped log.
- Dữ liệu thật trước WS0 ⇒ vi phạm §14.4.

## 9b. Thiết kế cho câu hỏi chưa có lời đáp (mặc định + điểm chỉnh)

| Chưa biết | Thiết kế | Mặc định P1 | Đổi sau bằng |
|---|---|---|---|
| Kênh giao t-log & tần suất | Receiver là adapter cắm thêm, tất cả đổ về cùng `ingest_batch`; pipeline idempotent theo sha256 + natural_key nên tần suất nào cũng được | Upload API + push API | Thêm adapter SFTP / S3-drop / DB-export pull (không đổi phần sau) |
| Định dạng (POSLog hay riêng) | Parser registry theo `ingest_feed.format` | Parser POSLog 6.0 | Thêm parser hãng; crosswalk mẫu mới |
| Được lưu? lưu bao lâu? | Cờ `landed_enabled` + `retention_months` theo project; xoá = drop partition + xoá raw | Tắt; khi bật: 25 tháng (đủ YoY) | Đổi cấu hình; revoke ⇒ quy trình WS9 |
| Có PHI (RX)? | Field RX chỉ ở pack pharmacy; danh sách field nhạy cảm trong pack được mã hoá/mask ở ingest | Không nhận field định danh bệnh nhân | Bật field theo pack khi có BAA |
| Region | Map project → landed instance (`landed_instance` theo project, mặc định 1 instance) | 1 instance | Thêm instance region khác, chuyển project |
| RX phase này hay sau | RX = bật pack Pharmacy (Industry Templates đã có toggle) | Retail trước; RX theo pack | Bật pack + crosswalk RX |
| Lịch sử YoY | Endpoint backfill (nhận batch quá khứ, business_date cũ) + partition tự tạo theo ngày dữ liệu | Nhận bất kỳ khoảng nào ≤ retention | Tăng retention |

## 9c. Quy tắc đếm Sales Reducing (đảo / chồng / không trùng)

**Định nghĩa chung**
- C1 — **Value** luôn là số dương = số tiền bị giảm; **Items** = số đơn vị bị ảnh hưởng (hàng cân ký = 1); **Cust** = số giao dịch **khác nhau** bị ảnh hưởng (không phải khách loyalty).
- C0 — `sale_line` chỉ chứa **dòng hàng đã bán** (không dòng discount/tax/tender, không dòng bị void); void dòng ghi vào entity `line_void`; entity `void` chỉ còn void cấp giao dịch (cancel, post void) — để metric cũ (`cogs`, `net_sales`, `void_rate`…) giữ nguyên nghĩa. Chiều `employee_id` của mọi counter = **thu ngân của giao dịch**.
- C2 — Mỗi sự kiện giảm thuộc **đúng một** chức năng. Crosswalk phải gán; nếu POS gắn nhiều nhãn, thứ tự ưu tiên: employee discount > vendor coupon > store coupon > e-coupon > item discount > total discount > price modify.
- C3 — Sự kiện tính vào **business_date của giao dịch chứa nó** (refund tính ngày refund, không lùi về ngày bán gốc).
- C4 — Giao dịch **training mode** bị loại khỏi mọi counter, chỉ vào counter Training. Giao dịch suspend chưa recall không phải là sale; recall ⇒ tính một lần ở giao dịch hoàn tất.
- C5 — Replay/trùng xử lý bằng natural key ở ingest, không phải ở quy tắc đếm.

**Shrink (void / cancel / post void / refund) — không chồng Value**
| Chức năng | Value | Items | Ghi chú |
|---|---|---|---|
| Line void (entity `line_void`) | giá dòng tại thời điểm void (sau price modify) | units của dòng | Vẫn đếm dù sau đó giao dịch bị cancel (hành vi cần theo dõi) |
| Transaction cancel | tổng các dòng **còn lại** (chưa line-void) lúc cancel | units còn lại | Không cộng lại phần đã line-void ⇒ không chồng |
| Post void | net total của giao dịch gốc đã hoàn tất | units của giao dịch gốc | Giao dịch gốc **bị loại khỏi Sales Capture**; line void bên trong gốc vẫn giữ ở counter line void |
| Refund | số tiền hoàn của các dòng được hoàn | units hoàn | Liên kết `orig_sale_ref`; refund một phần chỉ tính phần hoàn; void một dòng refund ⇒ giảm Value refund |

**Margin & Tax (price modify / discount / coupon / tax exempt / tax modify)**
- M1 — Chỉ tính trên dòng/giao dịch **thực sự hoàn tất** (không line-void, không cancel, không post void) — vì không có bán thì không mất margin/tax.
- M2 — Price modify Value = (giá gốc − giá mới) × qty; dòng sau đó bị void ⇒ không tính price modify.
- M3 — Total discount: Items = toàn bộ units của giao dịch, Cust = 1.
- M4 — Tax exempt Value = thuế lẽ ra phải thu (nếu POS cung cấp, ngược lại `unavailable`); Tax modify Value = |thuế trước − thuế sau|.

**Gộp (rollup)**
- R1 — "Tổng shrink" Value = cộng Value các chức năng shrink (không chồng theo cách tính trên); Cust = COUNT DISTINCT giao dịch (không cộng Cust của từng chức năng).
- R2 — Counter theo từng chức năng là chính xác khi cộng theo dims (mỗi giao dịch có đúng một store/terminal/cashier/ngày); Cust **không cộng được giữa các chức năng**.
- R3 — Thiếu dữ liệu nguồn ⇒ `unavailable`, không ghi 0. **Cơ chế:** (a) metric khai báo field nó cần trong header `-- needs_fields: [sale_line.entry_method]`; (b) ingest ghi `feed_field_coverage`; (c) `Availability` tắt metric với lý do `source does not send <field>` khi không feed nào của project gửi field đó trong cửa sổ tính; (d) metric bị tắt ⇒ `kg_get_metrics` trả lỗi `metric_disabled` kèm lý do (hành vi engine hiện có), field cần mà **chưa map** (mọi mode) cũng tắt metric; (e) batch có giao dịch bị loại ⇒ `data_status = incomplete`, danh sách ngày bị ảnh hưởng ghi trong `issues.rejected_days`. Timing (ring/tender/idle/lock) chỉ có khi POS phát sự kiện thời gian.
- R4 — Đối soát (header↔footer, Σ dòng = tổng) là **quy tắc của pack**, khai báo trong crosswalk/pack (`reconcile:`), core chỉ chạy biểu thức — core không biết tên field ngành (D10).

## 9d. Summary theo cashier / terminal / store / ngày

- Dims của metric khai báo trong header SQL (`-- dims: [...]`, `internal/intel/header.go`). `kg_get_metrics` gộp khi đọc: `group_by` ⊆ dims và `grain` day/week/month (`internal/intel/engine/query.go:315`).
- ⇒ Mọi counter Sales Capture/Reducing mới lưu ở **mức chi tiết nhất**: `grain: day`, `dims: [location_id, terminal_id, employee_id]`. Summary theo cashier/terminal/store/kỳ bất kỳ = cùng một metric, khác `group_by`/`grain` — không cần bảng summary riêng.
- **Cust không cộng được qua chiều `function`:** header metric thêm `-- non_additive_dims: [function]`; `kg_get_metrics` từ chối `group_by` bỏ chiều đó (lỗi rõ ràng). "Tổng shrink/margin/tax" là metric riêng `sr_total_value|cust|items` dims `[location_id, terminal_id, employee_id, function_class]`, Cust = COUNT DISTINCT giao dịch trong class. Cộng qua `location/terminal/employee/day` vẫn đúng vì mỗi giao dịch thuộc đúng một tổ hợp.
- Metric cũ (`void_rate`, `refund_count`…) giữ nguyên dims; muốn thêm `terminal_id` thì bump `version` của metric (runner tính lại lịch sử).
- Drill-down: evidence SQL trả row canonical kèm `_source_ref`; với landed thêm `batch_id` để truy về file gốc.
- Canonical: `sale.terminal_id`, `location.address`, `location.phone` (WS1).

## 9e. UI — nguyên tắc dễ hiểu, dễ dùng

- Không dùng từ kỹ thuật trên UI: "landed" ⇒ **"Lưu dữ liệu POS"**, crosswalk ⇒ **"Ghép trường"**, unmapped ⇒ **"Trường chưa ghép"**, reject ⇒ **"Giao dịch lỗi"**.
- Một luồng thiết lập dạng **4 bước** (wizard), mỗi bước một việc, luôn có nút quay lại:
  1. *Chọn hãng POS* (danh sách có logo + "Khác") → hệ thống chọn sẵn mẫu ghép trường.
  2. *Tải lên file mẫu* (kéo-thả) → xem trước 3 giao dịch đã đọc được, hiển thị như hoá đơn.
  3. *Ghép trường* → mặc định đã ghép từ mẫu + AI; chỉ hiện những ô **cần người xem** (Partial/Missing) trước, phần đã xong thu gọn. Mỗi ô có ví dụ giá trị thật từ file mẫu.
  4. *Chọn cách gửi dữ liệu* (upload / API key / thư mục SFTP) → hiển thị hướng dẫn copy-paste.
- Màn **tổng quan feed** chỉ 3 con số lớn: *Giao dịch hôm nay*, *Lần nhận gần nhất*, *Cần chú ý* (trường chưa ghép + giao dịch lỗi). Trạng thái bằng màu + chữ: "Đang chạy tốt" / "Cần chú ý" / "Đã dừng".
- Mỗi cảnh báo có **hành động ngay** ("Ghép trường này", "Xem giao dịch lỗi", "Nhận lại lô này").
- Data mapping: khi một báo cáo bị tắt vì dữ liệu ở hai nơi, hiện câu dễ hiểu + nút sửa ("Báo cáo Biên lợi nhuận cần Danh mục sản phẩm ở cùng nơi với giao dịch → Tải danh mục lên").
- Bật lưu dữ liệu chỉ admin hệ thống thấy; khách thấy trạng thái chỉ đọc.
- Theo đúng pattern UI hiện có (card + badge "Set up", "Prepare with AI") để người dùng không phải học lại.

## 9f. Repo bị ảnh hưởng

| Repo | Thay đổi |
|---|---|
| `ennam.kg.packs` | Canonical 0.7.0 (retail + pharmacy), metric/evidence Sales Capture & Reducing, rule LAAM mới, `about.yaml`, thư mục `crosswalks/` (mẫu POSLog…), CHANGELOG |
| `ennam.kg.go` | Config `LANDED_DATABASE_URL`; migrations DAAB (`project_mapping.mode` + `'landed'`, `data_sources.kind`); migrations DB landed (bảng §5, RLS, partition); `intel/landedsource`; mode switch ở `sources.Build`/`admin.ModeBinder`/`mapping_file.go`/`mapdraft`/`mapping_coverage`; API ingest/feed/batch/replay; role DB riêng mỗi project + view canonical; `engine/record.go` thêm tender vào hoá đơn; WS0 authz |
| `ennam.kg.python` | Worker ingest: parser POSLog + framework parser hãng, engine crosswalk, validate, upsert/dedup, unmapped/reject, đối soát |
| `ennam.kg.next` | Tab "Dữ liệu POS" (wizard + tổng quan feed + ghép trường), nguồn landed trong Data mapping, dòng system trong Data Sources |
| `LAAM` | Nhỏ: nhãn field mới trong hoá đơn (`src/components/intel/detail/receipt-format.ts` — terminal, line type, tender); rule mới tự đến từ pack |
| Workspace root | `docker-compose.yml` (DB landed + init role), `envfiles/*.env`, spec/plan, Serena memories |
| `ennam.kg.admin` | Không cần ở P1 |
| `ennam.kg.requirements` | Tuỳ chọn: BA doc cho tính năng |

## 10. Câu hỏi chờ AIOS / nội bộ

1. T-log giao bằng cách nào (API, file drop, DB export) và tần suất?
2. POS có xuất ARTS POSLog không (version)? Xin vài giao dịch mẫu từ POS của AIOS + 1 retailer.
3. Được lưu bản sao không, lưu bao lâu, có PHI không, yêu cầu region?
4. RX trong release này hay phase sau?
5. Cần bao nhiêu lịch sử cho so sánh YoY?
6. (Nội bộ) Owner kỹ thuật, QA, estimate, ngày bắt đầu/kết thúc cho card.
