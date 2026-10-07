# Runbook — Tab "Data mapping" (ánh xạ dữ liệu) trên dashboard DAAB

Ngày: 2026-10-07. Áp dụng cho: `ennam.kg.go` từ commit `d30326a` (endpoint), dashboard `ennam.kg.next` từ `e96a45f` (tab), packs `ennam.kg.packs` 0.3.0 (commit `e24d473`, mới commit local, chưa push).
Kế hoạch: `docs/superpowers/plans/2026-10-07-data-mapping-tab.md`. Báo cáo kiểm chứng: `docs/superpowers/test-results/2026-10-07-data-mapping-verification.md`.

## 1. Tab này làm gì, ai được dùng

"Ánh xạ dữ liệu" (mapping) nói cho DAAB biết bảng và cột nào trong cơ sở dữ liệu của khách tương ứng với từng nhóm dữ liệu chuẩn của template ngành. Ví dụ: nhóm `sale` lấy từ bảng `transactions`, trường `sold_at` lấy từ cột `transaction_datetime`. Các chỉ số (doanh thu, margin, tỷ lệ hoàn tiền…) chỉ tính được khi những nhóm dữ liệu mà chúng cần đã được ánh xạ.

Trước đây chỉ làm được bằng dòng lệnh (`kg-packs import-mapping`) và sửa tay file `_projects/.../mapping.yaml`. Tab mới cho phép làm trên giao diện:

- xem nhóm dữ liệu nào đã ánh xạ, nhóm nào còn thiếu và chỉ số nào đang cần nó;
- tải **file mẫu** (template) hoặc **file ánh xạ hiện tại**;
- tải file YAML đã điền lên, xem **danh sách vấn đề** bằng lời dễ hiểu và **những gì sẽ thay đổi** so với ánh xạ hiện tại;
- **áp dụng** (apply). Sau đó DAAB tự xếp lịch tính lại các con số của dự án.

**Ai dùng được:** chỉ **Admin của dự án**, hoặc quản trị viên máy chủ (tài khoản admin toàn hệ thống, hay API key admin không giới hạn dự án).

- Viewer, Developer, người ngoài dự án và API key chỉ gắn với dự án (không có người dùng đứng sau) đều bị từ chối (403) ở cả 5 endpoint.
- Người không phải admin mở tab sẽ chỉ thấy câu "Only project admins can change the data mapping." Hiện chưa có bản tóm tắt chỉ-đọc cho họ.

Vị trí: dashboard DAAB (:3500) → vào dự án → tab **Data mapping** (ngay sau **Industry Templates**). Giao diện dashboard DAAB bằng tiếng Anh nên tên nút trong hướng dẫn giữ nguyên tiếng Anh.

## 2. Thứ tự bắt buộc: pack → ánh xạ → tính lại

1. **Pack (template ngành).** Bật pack cho dự án ở tab **Industry Templates** (ví dụ `retail`, rồi `pharmacy`). Tab Data mapping chỉ liệt kê và kiểm tra các nhóm dữ liệu của những pack **đang bật**.
2. **Nguồn dữ liệu.** Nguồn đã đăng ký trong dự án và đã **đồng bộ schema** (Data Sources → sync schema). Việc kiểm tra file chỉ dùng schema đã đồng bộ lưu trong DAAB, **không kết nối tới cơ sở dữ liệu của khách**. Hiện chỉ đọc trực tiếp được nguồn PostgreSQL.
3. **Ánh xạ.** Tải file mẫu → điền → tải lên → sửa hết lỗi → áp dụng.
4. **Tính lại.** Áp dụng thành công thì DAAB xếp lịch tính lại chỉ số của dự án. Chưa có thanh tiến độ: theo dõi qua trang trạng thái dữ liệu (data status) hoặc chờ vài phút rồi xem lại các con số.

### Lưu ý về pack 0.3.0 (bắt buộc đọc trước khi cập nhật pack)

- Pack 0.3.0 thêm trường `description` (mô tả bằng lời) cho từng trường dữ liệu. File mẫu và màn hình dùng mô tả này để giải thích.
- **Bản DAAB (`kg-server`) build từ trước commit `853ad99` của `ennam.kg.go` không đọc được pack 0.3.0.** Nó báo lỗi thuộc tính lạ `description` và **không nạp pack nào**.
- Vì vậy phải **build lại DAAB từ `853ad99` trở về sau, rồi mới cài hoặc nạp lại pack 0.3.0**. Không làm ngược thứ tự.
- Pack 0.3.0 hiện mới commit local trong `ennam.kg.packs`, chưa push. Việc push và build lại cần người phụ trách đồng ý.

## 3. Các bước trên giao diện

1. **Xem tóm tắt.** Đầu trang hiện số nhóm dữ liệu đã thiết lập và số nhóm cần chú ý. Mỗi nhóm có một trong các trạng thái:
   - *Set up*: đã duyệt;
   - *Needs approval*: đã tải lên nhưng chưa duyệt;
   - *Needs attention*: hỏng, hoặc thiếu trường bắt buộc;
   - *Not set up*: chưa ánh xạ.

   Nhóm chưa xong có dòng "Needed for: …" liệt kê các chỉ số đang chờ nó, và danh sách trường bắt buộc còn thiếu.
2. **Bước 1 — Download a template.**
   - Chọn nguồn dữ liệu (nếu dự án có nhiều nguồn) rồi bấm **Download template**. File `mapping-template.yaml` có sẵn `project_id`, `data_source_id` và mọi nhóm dữ liệu, mọi trường để trống `""`.
   - Phía trên mỗi trường có một dòng chú thích: mô tả, kiểu, bắt buộc hay tuỳ chọn, có phải khoá không, và các giá trị được phép nếu trường chỉ nhận một danh sách cố định.
   - Nếu đã có ánh xạ, bấm **Download the current mapping** để lấy `mapping-current.yaml`. **Luôn tải và cất file này trước khi áp dụng file mới**, vì hệ thống chưa có lịch sử hay nút quay lại (xem mục 6).
3. **Điền file** bằng một trình soạn thảo văn bản:
   - `from:` là tên bảng nguồn, ví dụ `transactions` hoặc `sales.orders`.
   - Mỗi trường điền tên cột, hoặc một biểu thức đơn giản như `subtotal - discount_amount` hay `claim_status = 'Rejected'`.
   - Hằng chuỗi phải để trong cả hai loại ngoặc, ví dụ `"'America/Chicago'"`.
   - Trường không ánh xạ được thì để nguyên `""`. Nhóm dữ liệu bỏ trống hoàn toàn sẽ được bỏ qua.
   - Trường có danh sách giá trị cố định thì khai báo `enum_map`, ví dụ `status: { Completed: completed, Voided: voided }`: bên trái là giá trị trong dữ liệu của khách, bên phải là giá trị chuẩn được phép.
   - Nhóm đọc từ bảng đã tải lên ("Dữ liệu bảng") thì dùng `mode: file` và `file_dataset: <tên dataset>`.
4. **Bước 2 — Upload your file.** Kéo thả hoặc chọn file `.yaml`/`.yml`, tối đa 256 KB. Hệ thống **tự kiểm tra ngay**; bước kiểm tra không ghi gì vào hệ thống.
5. **Đọc kết quả.**
   - Banner xanh nghĩa là tốt, vàng là có cảnh báo, đỏ là có lỗi.
   - Mục *What we found* liệt kê từng vấn đề theo nhóm dữ liệu và trường, kèm câu giải thích và việc cần làm.
   - Mục *What would change* liệt kê nhóm nào được thêm mới, nhóm nào thay đổi (trường nào, từ giá trị nào sang giá trị nào), và nhóm nào có trong hệ thống nhưng không có trong file.
   - Sửa file rồi tải lên lại cho tới khi **không còn lỗi**. Cảnh báo không chặn việc áp dụng.
6. **Áp dụng.**
   - Nút **Apply mapping** chỉ bấm được khi file không còn lỗi. Hộp xác nhận nhắc rằng các con số sẽ được tính lại và nên tải ánh xạ hiện tại về trước.
   - Dashboard luôn áp dụng ở chế độ **đã duyệt**.
   - Thành công thì hiện "Mapping applied. Recalculating your numbers…".
   - Nếu báo schema chưa đồng bộ: vào **Data Sources**, đồng bộ schema của nguồn, rồi thử lại.
7. **Start over** xoá file đang xem để làm lại từ đầu.

## 4. Bảng mã vấn đề và mã lỗi

### 4a. Vấn đề trong file (kết quả kiểm tra, mục *What we found*)

| Mã | Mức | Nghĩa | Cần làm gì |
|---|---|---|---|
| `parse_error` | lỗi | File không đọc được, sai cấu trúc hoặc thiếu thông tin cơ bản: sai cú pháp YAML (có số dòng), khóa lạ, giá trị sai dạng, file rỗng, không nhóm nào có trường được điền, thiếu `data_source_id`, thiếu `from`, `mode` lạ, thiếu `file_dataset`… | Sửa đúng chỗ được chỉ. Số dòng của lỗi cú pháp đôi khi là **dòng ngay trước** dòng sai (xem mục 7), nên hãy xem cả dòng kế tiếp. |
| `project_mismatch` | lỗi | File thuộc dự án khác (`project_id` không khớp); hoặc nguồn dữ liệu của một nhóm thuộc dự án khác hay không tìm thấy trong dự án này. | Tải file mẫu của **chính dự án này**. Dùng `data_source_id` của một nguồn trong dự án. |
| `unknown_entity` | lỗi | Tên nhóm dữ liệu không có trong pack nào đã cài. | Kiểm tra chính tả tên nhóm theo file mẫu, hoặc xoá nhóm đó. |
| `entity_not_in_enabled_packs` | cảnh báo | Nhóm thuộc một pack đã cài nhưng chưa bật cho dự án. Nhóm vẫn được lưu nhưng chưa được dùng. | Bật pack đó ở tab Industry Templates nếu cần. |
| `unknown_field` | lỗi | Trường không thuộc nhóm dữ liệu này. | Sửa tên trường theo file mẫu, hoặc xoá dòng đó. |
| `missing_required_field` | lỗi | Trường bắt buộc chưa được ánh xạ. | Điền cột nguồn cho trường đó. |
| `invalid_spec` | lỗi | Khai báo không hợp lệ: `enum_map` cho trường chưa ánh xạ, hoặc cho trường không có danh sách giá trị cố định. | Ánh xạ trường đó, hoặc bỏ `enum_map` của nó. |
| `invalid_expression` | lỗi | Giá trị của trường không phải biểu thức hợp lệ, ví dụ có `;`. | Chỉ dùng tên cột hoặc biểu thức đơn giản. |
| `invalid_timezone` | lỗi | Tên múi giờ của dự án không hợp lệ (gần như không gặp). | Báo cho quản trị kỹ thuật. |
| `unknown_table` | lỗi | Không thấy bảng ghi ở `from` trong schema đã đồng bộ. | Sửa tên bảng; nếu bảng mới được tạo thì đồng bộ lại schema nguồn. |
| `unknown_column` | lỗi | Không thấy cột trong bảng đó. | Sửa tên cột; nếu cột mới được thêm thì đồng bộ lại schema. |
| `source_not_ready` | lỗi | Nguồn dữ liệu chưa được đồng bộ schema. | Data Sources → đồng bộ schema → thử lại. |
| `unsupported_source` | lỗi | Nguồn không phải PostgreSQL. Hiện chỉ đọc trực tiếp được PostgreSQL. | Dùng nguồn PostgreSQL, hoặc tải dữ liệu lên dạng bảng (`mode: file`). |
| `enum_value_unknown` | **lỗi** | Giá trị chuẩn bên phải trong `enum_map` không nằm trong danh sách được phép. Câu báo lỗi liệt kê các giá trị đúng. | Đổi sang một giá trị được phép. Đây là lỗi chứ không chỉ là cảnh báo, vì lưu vào sẽ làm nhóm đó bị hỏng khi tính. |
| `removed_entity` | cảnh báo | Nhóm có trong ánh xạ hiện tại nhưng không có trong file. Nó **vẫn được giữ nguyên**, không bị xoá. | Không cần làm gì nếu muốn giữ. Hiện chưa có cách xoá một nhóm trên giao diện. |

### 4b. Mã lỗi của request (HTTP)

| HTTP | Mã | Khi nào | Cần làm gì |
|---|---|---|---|
| 400 | `invalid_request` | Mã dự án hoặc mã nguồn dữ liệu sai dạng; nguồn không thuộc dự án; nội dung gửi lên không đúng dạng `{"yaml": …}`. | Tải lại trang và làm lại; nếu vẫn lỗi thì báo kỹ thuật. |
| 403 | `forbidden` (hoặc thông báo thiếu quyền) | Không phải Admin dự án, hoặc là API key không có người dùng. | Nhờ Admin dự án làm. |
| 404 | `no_mapping` | Tải "ánh xạ hiện tại" khi dự án chưa có ánh xạ nào. | Bắt đầu từ file mẫu. |
| 409 | `schema_not_synced` | Áp dụng khi nguồn chưa đồng bộ schema. Không có gì được ghi. | Đồng bộ schema rồi áp dụng lại. |
| 413 | `too_large` | File lớn hơn 256 KB. | Bỏ bớt chú thích hoặc tách file. |
| 422 | `mapping_rejected` | Áp dụng file còn lỗi. **Không có gì được ghi.** Danh sách vấn đề đi kèm. | Sửa theo bảng 4a. |
| 503 | `packs_unavailable` | Máy chủ chưa nạp được template ngành. | Thử lại sau, hoặc báo quản trị kiểm tra pack (xem lưu ý 0.3.0 ở mục 2). |
| 503 | `mapping_unavailable` | Máy chủ chưa cấu hình khoá mã hoá (`KG_ENCRYPTION_KEY`), nên chưa kiểm tra hay áp dụng được. Tóm tắt và tải file vẫn dùng được. | Báo quản trị kỹ thuật. |
| 500 | `internal` | Lỗi phía máy chủ. Nếu thông báo là "Saving the mapping stopped part way…" thì việc lưu đã dừng giữa chừng. | Áp dụng **lại đúng file đó** để hoàn tất (áp dụng lặp lại là an toàn); nếu vẫn lỗi thì báo kỹ thuật. |

## 5. Cách hoạt động cần biết

- **Ô để trống nghĩa là "không ánh xạ".** Trường `""` bị bỏ qua. Nhóm hoàn toàn trống (không có `from`, không trường nào) bị bỏ qua. Một file mẫu chưa điền gì sẽ báo đúng một lỗi: "The file has no entities with mapped fields."
- **Trường tuỳ chọn để trống** được tính là rỗng (NULL); chỉ số vẫn chạy. Trường **bắt buộc** thì phải điền.
- **`enum_value_unknown` là lỗi**, không phải cảnh báo.
- **Áp dụng không xoá nhóm nào.** Nhóm có trong hệ thống nhưng không có trong file thì được giữ nguyên, kèm cảnh báo `removed_entity`.
- **Áp dụng lặp lại là an toàn.**
  - Cùng một file áp dụng hai lần thì không đổi phiên bản (`changed: false`).
  - Nhóm nào thay đổi thì tăng phiên bản.
  - Mỗi lần áp dụng thành công đều xếp lịch tính lại, kể cả khi không có gì thay đổi.
- **Áp dụng là "tất cả hoặc không gì cả" ở bước kiểm tra.** Còn bất kỳ lỗi nào thì không ghi gì. Nếu lỗi máy chủ làm dừng giữa lúc ghi, áp dụng lại đúng file đó.
- **Kiểm tra không bao giờ ghi** và không kết nối tới cơ sở dữ liệu của khách.
- **File có BOM hoặc xuống dòng kiểu Windows (CRLF)** vẫn được chấp nhận.
- **Nhật ký** chỉ ghi dòng `intel mapping: applied` kèm dự án, người áp dụng và số nhóm, không bao giờ ghi nội dung file.

## 6. Chưa làm (giới hạn hiện tại)

- **Chưa có lịch sử hay quay lại ánh xạ.** Luôn bấm **Download the current mapping** và cất file trước khi áp dụng file mới; muốn quay lại thì áp dụng lại file đã cất.
- **Chưa có AI soạn nháp ánh xạ.** Đây là giai đoạn 2.
- **Chưa cho biết "sửa trường X thì chỉ số nào hỏng"** ở mức trường. Hiện chỉ biết ở mức nhóm dữ liệu (dòng "Needed for").
- **Chưa có bản tóm tắt chỉ-đọc cho người không phải admin.**
- **Chưa có tiến độ tính lại.** Không có mã lần chạy hay thanh tiến độ. Nếu hàng đợi tính lại đang đầy thì yêu cầu có thể bị bỏ qua mà giao diện vẫn báo đã xếp lịch.
- **Chưa xoá được một nhóm dữ liệu** khỏi ánh xạ trên giao diện.

## 7. Hiện tượng đã biết (khi hỗ trợ người dùng)

- **Số dòng của lỗi cú pháp YAML có thể lệch 1.** Ví dụ thiếu `]` ở dòng 49 thì báo "line 48". Đây là cách thư viện YAML báo dòng; hãy xem cả dòng kế tiếp.
- **Lỗi cú pháp kèm một đoạn mô tả tiếng Anh của thư viện**, ví dụ "did not find expected ',' or ']'".
- **Khi nguồn chưa đồng bộ schema, mỗi nhóm dữ liệu báo một dòng giống nhau** (`source_not_ready`). Chỉ cần đồng bộ một lần.
- **Danh sách nguồn ở bước tải file mẫu có cả nguồn không dùng được để đọc trực tiếp**, chẳng hạn nguồn SQL Server hoặc nguồn chưa đồng bộ schema. Chọn những nguồn đó thì file kiểm tra sẽ báo `unsupported_source` hoặc `source_not_ready`.
- **Số "cần chú ý" trên dashboard được tính phía trình duyệt.** Nó gồm cả nhóm chưa thiết lập, nên có thể khác `entities_attention` của API (API chỉ đếm nhóm đang chờ duyệt hoặc bị hỏng).

## 8. Dành cho kỹ thuật

- Endpoint, đều dưới `/api/v1/projects/{id}/mapping` và đều yêu cầu Admin dự án:
  - `GET` (tóm tắt);
  - `GET /template[?data_source_id=]`;
  - `GET /current`;
  - `POST /validate` với body `{"yaml"}`;
  - `POST /apply` với body `{"yaml","approve"}`.

  Hợp đồng đầy đủ nằm trong file kế hoạch.
- Dashboard gọi qua proxy `/api/kg/...`. Proxy chuyển nguyên các phản hồi `application/x-yaml`, giữ `Content-Disposition`.
- Dòng lệnh `kg-packs import-mapping` vẫn dùng được. Nó dùng chung thư viện kiểm tra (`internal/intel/admin`), nhưng kiểm tra theo **mọi** pack đã cài chứ không chỉ các pack đang bật.
- Kiểm thử đầu-cuối ở tầng HTTP: `ennam.kg.go/internal/handler/intel_mapping_e2e*_test.go`. Cần `KG_TEST_DATABASE_URL` (DB dev cổng **5433**) và `PACKS_DIR=<workspace>/ennam.kg.packs`.
