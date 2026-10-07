# Báo cáo kiểm chứng — Tab Data mapping (Task 5)

Ngày: 2026-10-07. Phiên bản được kiểm:
- `ennam.kg.go`: `d30326a` (endpoint), cộng với test mới ở `bf76517`
- `ennam.kg.next`: `e96a45f`
- `ennam.kg.packs`: 0.3.0 (`e24d473`, commit local, chưa push)

Kế hoạch: `docs/superpowers/plans/2026-10-07-data-mapping-tab.md`. Runbook: `docs/superpowers/runbooks/2026-10-07-data-mapping.md`.

## 1. Phạm vi và cách làm

Kiểm thử đầu-cuối ở **tầng HTTP handler**, chạy trên DB dev (`daab-postgres`, **localhost:5433**). Test nằm ở hai file:
- `ennam.kg.go/internal/handler/intel_mapping_e2e_test.go`: dựng môi trường, seed dữ liệu, dọn dẹp, các hàm trợ giúp
- `ennam.kg.go/internal/handler/intel_mapping_e2e_flow_test.go`: kịch bản `TestIntelMappingE2E`

Brief yêu cầu một file; tôi tách làm hai để mỗi file dưới 500 dòng.

**Thành phần thật:**
- `IntelMappingHandler` được nối giống `cmd/kg-server/intel_wiring.go`, gồm:
  - `intelstore.Store`
  - `livesource.New(db, store.NewDataSourceStore(db), nil, nil)`, giống CLI
  - `engine.ProjectCatalog` cho danh mục của dự án; danh mục "all" do chính handler tính
  - `NewMappingSourceLister(DataSourceStore, SchemaMetadataStore)`
  - Role resolver là `store.ProjectMemberStore.GetMembership`, bọc giống `main.go:789`. Production đi qua `ProjectService.GetMembership`; ở đây gọi thẳng store.
- Pack thật nạp từ `PACKS_DIR=<workspace>/ennam.kg.packs` (retail và pharmacy, cả hai 0.3.0).
- Chỉ **bộ kích hoạt tính lại** là giả (`fakeTrigger`, đếm số lần gọi).

**Dữ liệu tự tạo, dọn sạch bằng `t.Cleanup` kể cả khi test fail:**
- 4 user (role toàn cục `developer`)
- 2 dự án: dự án chính và một dự án "khác"
- `project_members` với 3 vai admin, developer và viewer; user thứ tư không là thành viên
- 4 nguồn dữ liệu:
  - nguồn PostgreSQL đã đồng bộ schema
  - nguồn PostgreSQL chưa đồng bộ
  - nguồn `mssql`
  - một nguồn thuộc dự án khác
- `pack_install` retail và pharmacy cho dự án chính

Thứ tự xoá khi dọn: `project_mapping`, rồi `source_schemas` (kéo theo bảng và cột), rồi `data_sources`, rồi `projects` (kéo theo `pack_install` và `project_members`), cuối cùng `users`. Cleanup dùng `context.Background()` và đếm lại để xác nhận còn 0 dòng.

Test **không đọc và không ghi** dự án demo `4ad7a5fa-…`. Id demo trong fixture được thay bằng id tự tạo trước mọi lần tải lên. Ca "sai project_id" dùng một UUID ngẫu nhiên.

**Schema seed:** 15 bảng và đúng các cột mà fixture `internal/intel/packtest/testdata/pharmacy-chain-mapping.yaml` tham chiếu, kể cả cột chỉ xuất hiện trong biểu thức (`stage`, `claim_status`) và hai cột Plan A (`hourly_wage`, `acquisition_cost`). Mọi cột có kiểu `text`, giống cách `TestParseAndValidate_DemoFixtureAgainstRealPacks` làm.
- `stores`, `products`, `employees`, `transactions`, `transaction_items`, `refunds`, `voids`, `cash_drawers`
- `employee_shifts`, `inventory_movements`, `inventory_snapshots`, `receipts`, `discount_overrides`, `prescriptions`, `insurance_claims`

Không seed 6 bảng của DB demo mà fixture không đọc (DB demo có 21 bảng). Nhóm `target` dùng `mode: file`, nên không cần bảng.

## 2. Lệnh đã chạy

```bash
# DSN chỉ dựng từ `docker exec daab-postgres printenv POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB`, cổng 5433
export KG_TEST_DATABASE_URL='postgres://<user>:<pass>@localhost:5433/<db>?sslmode=disable'
export KG_TEST_DSN="$KG_TEST_DATABASE_URL"
cd ennam.kg.go
go build ./... && go vet ./...                                   # sạch
PACKS_DIR=$PWD/../ennam.kg.packs go test -race -count=1 -run TestIntelMappingE2E -v ./internal/handler/
PACKS_DIR=$PWD/../ennam.kg.packs go test -race -count=1 -v ./internal/handler/... ./internal/intel/... ./cmd/...
go test -count=1 -run TestIntelMappingE2E -v ./internal/handler/  # không có PACKS_DIR → SKIP
```

**Kết quả bộ đầy đủ** (có `PACKS_DIR`):
- **Thời gian theo package:**
  - `internal/handler` 43.8s
  - `internal/intel` 1.8s
  - `intel/admin` 2.4s
  - `intel/engine` 7.6s
  - `intel/filedata` 25.7s
  - `intel/intelstore` 3.6s
  - `intel/livesource` 3.0s
  - `intel/packtest` 5.4s
  - `intel/sqlexec` 5.9s
  - `cmd/kg-pack-registry` 5.0s
  - `cmd/kg-packs` 7.6s
  - `cmd/kg-server` 12.3s
- Mọi package `ok`. `cmd/kg-bridge` và `cmd/kg-migrate` không có test.
- **0 FAIL, 1467 dòng `--- PASS`** (đếm mọi cấp, tính cả subtest).
- **11 SKIP**, đều là stub `t.Skip` có sẵn từ trước, không có cái nào bị chặn vì thiếu DB:
  - `TestCompareHandler_*` (2)
  - `TestExportHandler_*` (3)
  - `TestFavoriteHandler_*` (6)
- **Khi đặt `PACKS_DIR`,** các test pack thật khác cũng đọc `ennam.kg.packs` thay cho `workspace/packs`. Tất cả đều PASS: `TestRealPacksLoad`, `packtest`, `filedata` parity, `TestParseAndValidate_DemoFixtureAgainstRealPacks`.

**Thông báo SKIP của test mới:**
- Thiếu pack: `Skipping data mapping e2e: PACKS_DIR not set (point it at the ennam.kg.packs checkout with packs 0.3.0)`
- Thiếu DB: `Skipping data mapping e2e: KG_TEST_DATABASE_URL / KG_TEST_DSN not set`
- DSN trỏ vào `localhost:5432`: test cũng SKIP, vì đó là một container khác.

## 3. Bảng PASS/FAIL

| # | Bước (qua HTTP handler) | Kỳ vọng | Kết quả |
|---|---|---|---|
| 01 | Pack retail và pharmacy là 0.3.0 | version `0.3.0` | PASS |
| 02 | `GET mapping` trước khi ánh xạ | `packs:["retail","pharmacy"]`, 17 nhóm đều chưa ánh xạ, `required_by_metrics` có cho `sale`; `data_sources` liệt kê đủ 3 nguồn của dự án (chỉ nguồn đã đồng bộ có `schema_synced:true`), không có nguồn của dự án khác | PASS |
| 03 | `GET template?data_source_id=` | `application/x-yaml`, `attachment; filename="mapping-template.yaml"`; đọc lại được bằng YAML; đúng `project_id` và `defaults`; đủ 17 nhóm; mọi trường `""`; có chú thích mô tả 0.3.0. Không có nguồn thì có placeholder; nguồn của dự án khác trả 400 | PASS |
| 04 | `GET current` khi chưa có ánh xạ | 404 `no_mapping` | PASS |
| 05 | Validate file mẫu chưa điền | `ok:false`, đúng 1 `parse_error` "The file has no entities with mapped fields."; không ghi | PASS |
| 06 | File mẫu chỉ điền nhóm `location` | `ok:true`, 1 nhóm `added` (các ô `""` bị bỏ qua) | PASS |
| 07 | Validate fixture demo đã điền | `ok:true`, 0 lỗi, **0 cảnh báo**, 17 `added` | PASS |
| 08 | Tắt pharmacy rồi validate fixture | `ok:true`, cảnh báo `entity_not_in_enabled_packs` cho `claim` và `prescription` | PASS |
| 09 | 13 file hỏng, mỗi file một lỗi, và 1 file nhiều lỗi | đúng mã, đúng nhóm/trường, mức `error`, câu báo dễ hiểu; validate không ghi | PASS (14/14) |
| 10 | Apply file tốt (`approve:true`) | 17 nhóm `approved`, v1, `changed:true`, gọi tính lại đúng 1 lần, có dòng audit, nhật ký không chứa nội dung file | PASS |
| 11 | `GET mapping` sau apply | `entities_total=17, mapped=17, approved=17, attention=0`, không nhóm nào thiếu trường bắt buộc | PASS |
| 12 | `GET current` đọc lại được | đúng header; `ParseMappingFile` OK; validate lại thì 17 `unchanged`, 0 added/changed/removed | PASS |
| 13 | Apply lại cùng file | mọi nhóm `changed:false`, v1, các dòng lưu trữ y hệt | PASS |
| 14 | Apply file đổi một trường | `sale` lên v2 `changed:true`, các nhóm khác không đổi. `approve:false` thì `product` thành `proposed` v2 và `attention=1` | PASS |
| 15 | Apply bị từ chối | 422 `mapping_rejected` khi có lỗi; 409 `schema_not_synced` khi nguồn chưa đồng bộ; ảnh chụp `ListMappings` trước và sau giống hệt; không gọi tính lại | PASS |
| 16 | File thiếu nhóm `target` | cảnh báo `removed_entity`, `removed:1`; sau apply `target` vẫn còn | PASS |
| 17 | Phân quyền: viewer, developer, người ngoài dự án, key gắn dự án, key của dự án khác × 5 route | 403 cho cả 25 lời gọi; không ghi gì; không gọi tính lại | PASS |

**Tổng: 17/17 bước PASS (31 subtest PASS), 0 FAIL.**

Chi tiết bước 09:

| Ca hỏng | Mã | Câu báo (nguyên văn) |
|---|---|---|
| Sai bảng (`transactionz`) | `unknown_table` | Table 'transactionz' was not found in the data source. |
| Sai cột (`transaction_dt`) | `unknown_column` (sale.sold_at) | Column 'transaction_dt' does not exist in table 'transactions'. |
| Thiếu trường bắt buộc | `missing_required_field` (sale.sold_at) | Required field 'sold_at' is not mapped. |
| Nhóm lạ (`spaceship`) | `unknown_entity` | Entity 'spaceship' is not defined by any installed pack. |
| Trường lạ (`flavour`) | `unknown_field` | Field 'flavour' is not part of entity 'sale'. |
| Giá trị enum sai | `enum_value_unknown` (error) | Value 'complete' for field 'status' is not allowed; use one of: completed, voided, cancelled. |
| Biểu thức có `; DROP TABLE` | `invalid_expression` | The value of field 'net_amount' is not a valid expression: ';' is not allowed. (không lặp lại biểu thức) |
| Lỗi cú pháp YAML (`[` không đóng ở dòng 49) | `parse_error`, `line:48` | The file is not valid YAML at line 48: did not find expected ',' or ']'. (**lệch 1 dòng**, xem lỗi D1) |
| Sai `project_id` | `project_mismatch` | This file is for a different project (project_id does not match). Download the template of this project and fill it in. |
| Nguồn của dự án khác | `project_mismatch` | The data source of entity 'sale' belongs to another project. |
| Nguồn không tồn tại | `project_mismatch` | The data source of entity 'sale' was not found in this project. |
| Nguồn chưa đồng bộ | `source_not_ready` | The data source schema has not been synced yet. Sync the data source schema first. |
| Nguồn `mssql` | `unsupported_source` | The data source of entity 'sale' is not PostgreSQL; only PostgreSQL sources can be read live. |
| Nhiều lỗi trong một file | 4 vấn đề trong một lượt | `refund.refunded_at missing_required_field`, `sale.sold_at unknown_column`, `sale.status enum_value_unknown`, `spaceship unknown_entity` |

**Kiểm tra câu báo "dễ hiểu":** mọi câu báo đều được dò bằng danh sách cấm:
- `SELECT`, `CAST(`, `DROP`
- `livesource`, `intelstore`, `pq:`, `sql:`
- `%!`, `<nil>`, ký tự xuống dòng
- `panic`, `goroutine`, `MappingError`, `struct`, `yaml.v3`
- UUID

Không câu nào vi phạm.

## 4. Đầu ra JSON thực tế (đã cắt bớt)

Lấy từ lần chạy `-v` với dự án tạm `5c37383c-…`. Id của dự án tạm hiện trong log và đã bị xoá khi dọn.

`GET mapping` trước khi ánh xạ (8904 byte):
```json
{"project_id":"5c37383c-07df-454d-bb46-e28366a97449","packs":["retail","pharmacy"],
 "data_sources":[{"id":"f9e45f86-…","name":"E2E SQL Server","schema_synced":false},{"id":"edf4c29d-…","name":"E2E not synced yet","schema_synced":false},{"id":"17a996e6-…","name":"E2E Pharmacy POS","schema_synced":true}],
 "entities":[{"entity":"cash_drawer","description":"Cash drawer: unique ID of this drawer count, which store this belongs to, which employee was involved.","required_by_metrics":["retail.cash_shortage_count","retail.cash_variance","retail.no_sale_rate"],"mapped":false,"mode":"","status":"","version":0,"data_source_id":"","file_dataset":"","mapped_fields":[],"missing_required":["location_id","closed_at"],"missing_optional":["drawer_id","employee_id","expected_cash","counted_cash","no_sale_count"]}, …],
 "summary":{"entities_total":17,"entities_mapped":0,"entities_approved":0,"entities_attention":0}}
```
Phần đầu file mẫu (14618 byte):
```yaml
project_id: 5c37383c-07df-454d-bb46-e28366a97449
defaults:
  mode: live
  data_source_id: 17a996e6-d03f-4079-95b2-b88030c2008e
entities:
  cash_drawer:
    # Used by: retail.cash_shortage_count, retail.cash_variance, retail.no_sale_rate
    from: ""   # source table, e.g. orders or sales.orders
    fields:
      # Unique ID of this drawer count. Type: text, optional, key.
      drawer_id: ""
      # Which store this belongs to. Type: text, required.
      location_id: ""
```
Validate file mẫu chưa điền:
```json
{"ok":false,"issues":[{"entity":"","field":"","code":"parse_error","message":"The file has no entities with mapped fields.","severity":"error"}],"diff":[],"summary":{"entities":0,"errors":1,"warnings":0,"added":0,"changed":0,"unchanged":0,"removed":0}}
```
File mẫu chỉ điền `location`:
```json
{"ok":true,"issues":[],"diff":[{"entity":"location","change":"added","fields":[{"field":"from","before":"","after":"stores"},{"field":"location_id","before":"","after":"store_id"},{"field":"name","before":"","after":"store_name"},{"field":"timezone","before":"","after":"'America/Chicago'"}]}],"summary":{"entities":1,"errors":0,"warnings":0,"added":1,"changed":0,"unchanged":0,"removed":0}}
```
Validate fixture demo: `{"ok":true,"issues":[], "diff":[… 17 × "added" …]}`, 0 cảnh báo.

Apply fixture (1236 byte):
```json
{"applied":[{"entity":"cash_drawer","status":"approved","version":1,"changed":true}, … 17 nhóm …],"recompute_triggered":true}
```
`GET mapping` sau apply: `"summary":{"entities_total":17,"entities_mapped":17,"entities_approved":17,"entities_attention":0}`, không còn nhóm nào chưa ánh xạ.

Diff của file đổi một trường:
```json
[… {"entity":"sale","change":"changed","fields":[{"field":"tax_amount","before":"tax_amount","after":"COALESCE(tax_amount, 0)"}]} …]
```
Apply file đó cho `sale` `{"status":"approved","version":2,"changed":true}`. Apply với `approve:false` cho `product` `{"status":"proposed","version":2,"changed":true}`.

Apply bị từ chối (422):
```json
{"error":{"code":"mapping_rejected","message":"The mapping file has problems, so nothing was saved. Fix them and try again."},"issues":[{"entity":"sale","field":"sold_at","code":"unknown_column","message":"Column 'transaction_dt' does not exist in table 'transactions'.","severity":"error"}]}
```
Apply khi nguồn chưa đồng bộ (409, 2937 byte, mỗi nhóm một dòng giống nhau):
```json
{"error":{"code":"schema_not_synced","message":"The data source schema has not been synced yet. Sync the data source schema first."},"issues":[{"entity":"cash_drawer","code":"source_not_ready", …},{"entity":"claim", …}, …]}
```
`GET current` khi chưa có ánh xạ: `{"error":{"code":"no_mapping","message":"No data mapping has been saved for this project yet."}}`

Số lần gọi tính lại trong toàn bộ kịch bản: 6 lần, gồm:
- apply lần đầu
- apply lại không đổi
- apply đổi một trường
- `approve:false`
- duyệt lại
- file thiếu `target` (file này là fixture gốc, nên đồng thời đưa `sale` và `product` về định nghĩa ban đầu, lên v3)

Các lời gọi bị từ chối (422, 409, 403) không gọi tính lại lần nào.

## 5. Lỗi và điểm yếu phát hiện (xếp theo mức ảnh hưởng)

Theo yêu cầu, tôi chỉ ghi nhận, **không sửa** mã nguồn.

1. **D1 — Trung bình: số dòng của lỗi cú pháp YAML thường lệch 1 (báo dòng trước dòng sai).**
   - Vị trí: `ennam.kg.go/internal/intel/admin/mapping_parse.go:118-125`. Số dòng của yaml.v3 được chuyển nguyên cho người dùng.
   - E2E: `[` không đóng ở dòng 49 bị báo "line 48".
   - Thử riêng với yaml.v3 cũng ra như vậy: flow sequence không đóng, sai thụt lề và ký tự tab đều bị báo ở dòng N-1; riêng lỗi "mapping values are not allowed" thì báo đúng dòng.
   - Người dùng không chuyên sẽ tìm sai chỗ. Runbook đã ghi cách xử lý tạm. Cách sửa gợi ý: nói "khoảng dòng N–N+1", hoặc dùng mark của `yaml.Node`.
2. **D2 — Thấp/Trung bình: câu báo lỗi cú pháp kèm nguyên văn tiếng Anh kỹ thuật của thư viện,** ví dụ "did not find expected ',' or ']'".
   - Vị trí: `mapping_parse.go:125`.
   - Không lộ SQL hay mã Go, nhưng trái tinh thần "lời thường".
3. **D3 — Thấp: nhánh dự phòng của `invalid_spec` lặp lại `MappingError.Detail` của compiler.**
   - Vị trí: `mapping_check.go:154` ("The mapping of entity '%s' is not valid: %s.").
   - Detail có thể chứa chữ kỹ thuật, ví dụ "field x has unknown type …".
   - E2E không chạm tới được nhánh này; chỉ đọc mã.
4. **D4 — Thấp: nhận diện "nguồn không tồn tại" bằng cách so chuỗi `"not found"` trong lỗi.**
   - Vị trí: `mapping_check.go:132`.
   - E2E xác nhận nó đang hoạt động, ra `project_mismatch` với câu "was not found in this project". Nhưng nếu `DataSourceStore` đổi câu chữ thì sẽ thành 500.
   - Nên có lỗi sentinel. Task 2 cũng đã nêu.
5. **D5 — Thấp: apply không thay đổi gì vẫn gọi tính lại.**
   - Vị trí: `ennam.kg.go/internal/handler/intel_mapping_write.go:202-205`.
   - Trong kịch bản, re-apply y hệt (bước 13) vẫn kích hoạt tính lại: 1/6 lần là thừa. Lần duyệt lại ở bước 14 và lần apply ở bước 16 đều có thay đổi thật nên không thừa.
   - Vô hại nhưng tốn tài nguyên. Nên chỉ gọi khi có `Changed` hoặc trạng thái đổi.
6. **D6 — Thấp: `recompute_triggered:true` kể cả khi scheduler bỏ yêu cầu vì hàng đợi đầy.**
   - Vị trí: `intel_mapping_write.go:204`.
   - `Scheduler.Trigger` không trả kết quả. Đã ghi vào runbook.
7. **D7 — Thấp (UX): 409 `schema_not_synced` trả 1 issue cho mỗi nhóm, tức 16 dòng giống hệt nhau.**
   - Vị trí: `intel_mapping_write.go:183`, sinh issue từ `mapping_check.go:111-114`.
   - Dashboard nên gộp lại, hoặc API nên trả theo nguồn dữ liệu.
8. **D8 — Thấp (UX): danh sách `data_sources` và bộ chọn của file mẫu có cả nguồn không dùng được để đọc trực tiếp** (`mssql`, chưa đồng bộ).
   - Vị trí: `intel_mapping_write.go:252` và kiểm tra `hasSource` ở `intel_mapping.go:347`.
   - Template nhận các nguồn này mà không cảnh báo; chỉ tới bước kiểm tra mới báo `unsupported_source` hoặc `source_not_ready`.
   - Dù vậy `schema_synced:false` đã đúng (E2E xác nhận).

Không thấy lỗi nào ở các điểm sau:
- phân quyền (25/25 lời gọi bị chặn)
- tính "không ghi khi từ chối"
- tính lặp lại an toàn
- round-trip của `current`
- việc nhật ký không chứa nội dung file
- danh sách nguồn: không lộ nguồn của dự án khác

## 6. Chưa kiểm chứng

- **Trình duyệt thật với stack đã build lại.** Image DAAB và dashboard chưa build lại, container chưa tạo lại; việc này cần người phụ trách đồng ý. Kiểm tra giao diện hiện chỉ có ảnh chụp với fetch giả lập ở Task 4.
- **Proxy `/api/kg` chuyển YAML qua máy chủ thật** (giữ `Content-Type` và `Content-Disposition`). Mới đọc mã ở Task 4.
- **Việc trình duyệt thực sự lưu file khi tải** `mapping-template.yaml` hoặc `mapping-current.yaml`.
- **Một lần tính lại thật sau apply.** Trigger là giả; chưa chạy scheduler hay runner với ánh xạ vừa áp dụng.
- **Cơ sở dữ liệu thật của khách.** Schema được seed bằng tay, mọi cột kiểu `text`. Chưa đồng bộ schema từ `pharmacy_demo` thật hay DB khách thật. Kiểu cột thật, nhất là timestamp có hoặc không có múi giờ, chưa đi qua bước compile của lần kiểm tra này.
- **Role resolver qua `ProjectService`** như production. Test dùng thẳng `ProjectMemberStore.GetMembership`.
- **Trường hợp quản trị viên máy chủ** (user role admin, hoặc key admin không giới hạn). Đã có unit test với fake ở Task 3; e2e trên DB chưa chạy.
- **Hai lần apply đồng thời và nhiều bản server chạy song song.** Khoá chỉ có trong một tiến trình.
- **Gỡ pack khi đã có ánh xạ,** và nhóm ở trạng thái `broken` trên màn hình tóm tắt.
