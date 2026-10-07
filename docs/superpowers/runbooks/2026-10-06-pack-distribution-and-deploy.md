# Runbook — Phân phối template ngành (pack): phát hành, cài đặt, cập nhật, quay lại, triển khai

> Ngày: 2026-10-06 (cập nhật sau final review 2026-10-07). Kế hoạch: `docs/superpowers/plans/2026-10-06-pack-distribution.md`.
> Trong tài liệu này "pack" và "template ngành" là một: màn hình gọi là *template*, kỹ thuật gọi là *pack*.
> Tài liệu chỉ nêu **tên** biến môi trường, không bao giờ ghi giá trị token.

## (a) Thay đổi gì và ai làm gì

**Trước đây:** pack nằm trong thư mục `packs/` của repo workspace, được mount **chỉ đọc** vào DAAB (`kg-server`) và LAAM (`app`). Muốn đổi pack thì phải sửa repo, build lại image hoặc khởi động lại `daab-server`.

**Bây giờ:**

| Thành phần | Vai trò |
|---|---|
| Repo `ennam.kg.packs` | Nguồn duy nhất của nội dung pack (`retail/`, `pharmacy/`), có lịch sử và số phiên bản riêng. Công cụ phát hành nằm trong `_scripts/`. Không còn chứa mapping của khách (`_projects/`) ở bản mới nhất. |
| Dịch vụ `kg-pack-registry` (container `daab-packs`, cổng 8090) | Kho lưu các phiên bản pack đã phát hành. CI đẩy lên, DAAB và LAAM tải về. Một phiên bản đã phát hành là **bất biến**. |
| DAAB: trang **Template Library** (dashboard, mục ADMIN) | Quản trị viên máy chủ cài, cập nhật, quay lại phiên bản cũ và **nạp lại** (Reload). Pack mới được nạp **không cần khởi động lại**. |
| LAAM: **Cài đặt → Mẫu theo ngành** ("Industry templates") | Owner/admin của LAAM cài, cập nhật, quay lại, và "cho giống DAAB". |
| CLI `kg-packs fetch / versions / rollback` | Cách làm bằng dòng lệnh cho vận hành (có sẵn trong image DAAB: `/app/kg-packs`). |
| `PACKS_DIR` (`/packs` trong container) | Thư mục pack đang dùng. Nay phải **ghi được** vì việc cài đặt ghi vào đó. |

**Phân vai:**
- **Quản trị viên máy chủ** (global admin của DAAB; owner/admin của LAAM): cài, cập nhật, quay lại phiên bản pack **cho cả máy chủ**.
- **Quản trị viên dự án**: vẫn **bật/tắt** pack cho từng dự án như trước (tab **Industry Templates** trong dự án DAAB, bảng `pack_install`). Phần này không đổi.

**Trạng thái:** đã xong cả bốn phần: dịch vụ registry, CLI, các endpoint thư viện của DAAB (`/api/v1/admin/packs/...`) cùng trang Template Library trên dashboard, và trang Mẫu theo ngành của LAAM.

**Bố cục trên đĩa** (giống nhau cho DAAB và LAAM):

```text
PACKS_DIR/
├── retail/                     # phiên bản đang dùng (tên thư mục = key của pack)
├── pharmacy/
├── _versions/<key>/<version>/  # các phiên bản trước, để quay lại
└── _staging/                   # vùng tạm khi cài; có khóa (.lockdir) và nhật ký đổi phiên bản (swap.json)
```

Bộ nạp pack bỏ qua các thư mục bắt đầu bằng `_` hoặc `.`; mọi thư mục khác phải là một pack (có `pack.yaml`). Vì công cụ của repo `ennam.kg.packs` nằm trong `_scripts/`, **thư mục gốc của một bản clone repo cũng là một `PACKS_DIR` hợp lệ** (dùng được cho test và cho dev chỉ đọc). Chỉ nên cài/cập nhật vào một thư mục riêng, không cài vào bản clone (xem lưu ý dev ở mục f).

## (b) Phát hành một phiên bản pack

Làm trong repo `ennam.kg.packs`:

1. Sửa nội dung pack. Mọi thay đổi metric, evidence, luật hoặc nội dung khác **đều phải tăng `version`** trong `<key>/pack.yaml`:
   - MAJOR: xóa hoặc đổi tên metric, entity, mã luật;
   - MINOR: thêm metric, entity, luật, kịch bản, trường;
   - PATCH: sửa ngưỡng hoặc câu chữ.
2. Thêm mục `## [x.y.z] - YYYY-MM-DD` vào `CHANGELOG.md`. Nội dung mục này được gửi lên registry làm "có gì mới" (nút **See what's new** ở DAAB).
3. Kiểm tra cục bộ: `bash _scripts/release_test.sh`, rồi `bash _scripts/release.sh <key>` (tạo `dist/<key>-<version>.tar.gz` và `.sha256`). Bước này chỉ để kiểm tra; **không** dùng bản build cục bộ để phát hành.
4. Commit, gắn tag `vX.Y.Z` và push tag.

**Chỉ CI phát hành.** Không ai `PUT` một phiên bản lên registry bằng tay. Lý do: một phiên bản là bất biến, và tarball build trên máy khác (macOS/bsdtar so với Ubuntu/GNU tar trên CI) có thể khác byte. Nếu ai đó phát hành tay trước, lần chạy CI cho tag đó sẽ nhận `409` và đỏ.

**CI làm gì** (workflow `.github/workflows/publish.yml`, chạy khi push tag `v*` hoặc chạy tay):
- Kiểm tra hai secret của repo có mặt: `PACKS_REGISTRY_URL` (địa chỉ registry) và `PACKS_PUBLISH_TOKEN` (token ghi). Secret chỉ đi qua biến môi trường, không in ra log.
- Chạy test của công cụ phát hành, đóng gói **mọi** pack, rồi gửi từng gói lên `PUT <registry>/v1/packs/<key>/<version>` kèm mã kiểm tra và changelog.
- Kết quả:
  - `201`: đã phát hành;
  - `200`: phiên bản đó đã có với nội dung y hệt. CI không làm gì; đây là trường hợp bình thường cho pack không đổi trong tag này;
  - `409`: phiên bản đó đã tồn tại với nội dung **khác**, job đỏ. Nguyên nhân thường gặp: quên tăng `version` sau khi sửa pack, hoặc có người đã phát hành tay. Cách xử lý: tăng `version` (và CHANGELOG), gắn tag mới, push lại. Không có cách ghi đè một phiên bản đã phát hành.

## (c) Cài đặt / cập nhật / quay lại / nạp lại

Điều kiện chung: trên máy chủ đã đặt `PACKS_SOURCE` và `PACKS_TOKEN` (xem mục f). Nếu chưa đặt, màn hình báo "chưa có nguồn template" và không hiện nút cài. Quay lại và nạp lại vẫn dùng được khi không có nguồn.

### DAAB: Template Library (dashboard)

Vào dashboard DAAB (:3500), mục **ADMIN → Template Library**. Chỉ global admin vào được; khóa API theo dự án bị từ chối.

- Mỗi thẻ template có tên, phiên bản đang dùng, trạng thái và số dự án đang dùng. Trạng thái là một trong:
  - "Up to date";
  - "New version … available";
  - "Not installed";
  - **"Installed X, but the server is still using Y"** hoặc "…but the server hasn't loaded it yet". Nghĩa là đã cài trên đĩa nhưng DAAB chưa nạp; xem **Reload** bên dưới.
- **Install** / **Update** hỏi xác nhận trước ("Alerts and numbers for the {n} projects that use it may change…"). Sau khi cài, DAAB nạp lại danh mục pack ngay trong cùng thao tác. Nếu bản mới nạp lỗi, DAAB **đưa bản cũ về** và báo lỗi (`reload_failed`).
- **See what's new** hiện changelog của phiên bản đích.
- **Go back to an earlier version** cho chọn một phiên bản đã lưu trên máy chủ, có xác nhận.
- **Reload**: nút này hiện trên thẻ khi thẻ ở trạng thái "đã cài nhưng chưa nạp", và hiện ở đầu trang khi máy chủ chưa nạp template nào ("Templates are not loaded on this server yet."). Reload đọc lại thư mục pack, nên DAAB dùng đúng phiên bản đang có trên đĩa mà không cần khởi động lại. Cần Reload khi:
  - pack được đổi **bên ngoài** DAAB: `kg-packs fetch` / `rollback` từ dòng lệnh, hoặc LAAM cài vào **cùng** thư mục pack;
  - DAAB khởi động lúc thư mục đang bận hoặc lỗi. DAAB tự thử nạp lại ở nền, lần đầu sau 30 giây, rồi giãn dần tới mỗi 5 phút. Nó dừng ngay khi đã nạp được, nhờ chính lần thử đó, nhờ Reload hoặc nhờ một lần cài. Bấm Reload thì không phải chờ.
- Endpoint phía sau (chỉ global admin):
  - `GET /api/v1/admin/packs/library`. Mỗi pack đã cài có thêm `loaded_version` (phiên bản DAAB đang chạy) và `needs_reload`. Trang còn có:
    - `registry_loaded`: false nghĩa là chưa nạp pack nào;
    - `source_error_kind`: `unreachable`, `unauthorized` hoặc `bad_response`;
    - `needs_repair`: thư mục cần người kiểm tra.
  - `POST /api/v1/admin/packs/{key}/install`, body `{"version":"0.2.0"}`;
  - `POST /api/v1/admin/packs/{key}/rollback`, body `{"version":"0.1.0"}`;
  - `POST /api/v1/admin/packs/reload`.
- Tab **Industry Templates** của từng dự án hiện phiên bản đang dùng và nhãn nhỏ "Update available".

### LAAM: Cài đặt → Mẫu theo ngành

Đăng nhập bằng owner/admin, rồi vào **Cài đặt → Mẫu theo ngành** (`/settings/industry-templates`).

- Mỗi mẫu hiện:
  - "Đang dùng: x.y.z";
  - "Công cụ dữ liệu của bạn (DAAB) dùng: …", kèm nhãn xanh **Cùng phiên bản** hoặc nhãn vàng **Khác với công cụ dữ liệu của bạn (DAAB) — kết quả có thể sai**;
  - "Mới nhất hiện có: …".
- Các nút:
  - **Cập nhật lên bản mới nhất**;
  - **Dùng giống công cụ dữ liệu của bạn (DAAB): x.y.z**, chỉ hiện khi khác;
  - **Cho tất cả giống công cụ dữ liệu của bạn (DAAB)**;
  - trong "Thêm lựa chọn": **Dùng một phiên bản đã lưu khác**.
- Mọi thao tác đều hỏi xác nhận. Mỗi lần ghi có một dòng `audit_log` (`intel.packs.install`, `intel.packs.rollback`).
- LAAM nạp pack theo từng lần phân tích, nên phiên bản mới có hiệu lực **từ lần kiểm tra tới** mà không cần khởi động lại. Bản tin của một lần chạy cũ dùng đúng phiên bản ghi trong lần chạy đó, nếu phiên bản ấy còn lưu trong `_versions/`.

### Dòng lệnh `kg-packs`

Chạy trong container DAAB:
- release: `docker compose -f docker-compose.release.yml exec kg-server /app/kg-packs …`;
- dev: `docker exec -w /app daab-server go run ./cmd/kg-packs …`.

```bash
kg-packs versions                                   # phiên bản đang dùng và đã lưu của từng pack
kg-packs fetch    --pack pharmacy --version 0.3.0   # tải, kiểm tra, cài và kích hoạt
kg-packs rollback --pack pharmacy --version 0.2.0   # quay lại một phiên bản đã lưu
```

- `--source` mặc định lấy từ `PACKS_SOURCE`. Token chỉ đọc từ biến môi trường: `PACKS_TOKEN`, hoặc tên biến khác qua `--token-env`. **Không bao giờ** truyền token làm giá trị cờ.
- `--packs-dir` mặc định là `$PACKS_DIR`, nếu không có thì `/packs`.
- **Quan trọng:** CLI chỉ đổi file trên đĩa. DAAB đang chạy vẫn dùng phiên bản cũ cho tới khi bấm **Reload** trong Template Library (thẻ sẽ hiện "Installed X, but the server is still using Y") hoặc gọi `POST /api/v1/admin/packs/reload`. LAAM thấy thay đổi ở lần phân tích tới.
- Lệnh `install` cũ giữ nguyên nghĩa: **bật** pack cho một dự án (`kg-packs install --project <uuid> --pack <key>`).

## (d) Cập nhật, quay lại, "cho giống DAAB"; lệch phiên bản; "đang bận"; mã lỗi

**Cập nhật:** chỉ cài được phiên bản **cao hơn** phiên bản đang dùng. Cài phiên bản thấp hơn bị từ chối (`downgrade`); muốn về bản cũ thì dùng **quay lại**.

**Quay lại:** chọn một phiên bản đã lưu trong `_versions/<key>/`. Mỗi lần cập nhật, bản đang dùng được cất vào đó, nên luôn quay lại được bản ngay trước. Quay lại không cần mạng.

**Cho giống DAAB (LAAM):** LAAM chỉ đi **tiến lên**. Với mỗi pack mà DAAB đang dùng bản **mới hơn**, LAAM cài đúng phiên bản đó. LAAM không bao giờ tự lùi về một bản cũ hơn.
- Khi bản của DAAB **cũ hơn** bản của LAAM:
  - Nếu hai bên dùng chung thư mục pack, điều đó có nghĩa DAAB chưa nạp lại sau khi LAAM cài. Trang LAAM nói rõ: "Công cụ dữ liệu của bạn (DAAB) chưa nạp phiên bản mới hơn. Hãy mở Thư viện mẫu của nó và bấm Tải lại, hoặc khởi động lại nó." Trang không hiện nút Match.
  - Nếu hai bên dùng thư mục riêng, cách đúng là **cập nhật DAAB** lên cùng phiên bản. Nếu cố cho LAAM lùi, LAAM trả `version_not_stored`.

**Hai bên độc lập:** cài ở DAAB không đổi phiên bản **đang chạy** của LAAM, và ngược lại.
- Khi hai bên dùng **thư mục riêng** (thường gặp ở máy chủ thật), phải cập nhật cả hai, hoặc dùng "cho giống DAAB" ở LAAM.
- Khi dùng **chung** một thư mục, file trên đĩa đổi cho cả hai, nhưng mỗi bên chỉ dùng bản mới khi tự nạp lại:
  - LAAM nạp lại ở lần phân tích tới;
  - DAAB nạp lại khi bấm **Reload**. Sau khi LAAM cài vào thư mục chung, Template Library hiện "Installed X, but the server is still using Y".

**Lệch phiên bản hiện ra ở đâu:**
- Trang Mẫu theo ngành của LAAM: nhãn vàng, kèm dải cảnh báo "Một số mẫu khác phiên bản với công cụ dữ liệu của bạn (DAAB)…".
- Kết quả phân tích của LAAM: cảnh báo bắt đầu bằng `pack_version_mismatch:`.
- Template Library của DAAB: trạng thái "Installed X, but the server is still using Y", tức đĩa và bản đang chạy khác nhau.

**"Đang bận" (`busy`):** tại mỗi thời điểm chỉ một thao tác cài, quay lại hoặc nạp lại được chạy trên một thư mục pack, kể cả khi DAAB (Go) và LAAM (Node) dùng chung thư mục. Thao tác thứ hai chờ một lúc rồi báo bận:
- **DAAB chờ 5 giây** rồi trả `busy` (để trang web không bị treo). Hãy đợi một phút rồi thử lại.
- **LAAM chờ 60 giây** rồi báo "Một thay đổi mẫu khác đang chạy…".
- CLI chờ theo `--lock-timeout`.

**Khóa bị bỏ lại** khi tiến trình đang giữ khóa chết giữa chừng:
- Thông thường khóa **tự hết hạn sau 15 phút**, rồi thao tác kế tiếp tự chiếm lại.
- Ngoại lệ 1: nếu khóa ghi đúng pid và máy (host) của chính tiến trình hiện tại nhưng được tạo **trước khi tiến trình này khởi động**, thì đó là khóa của lần chạy trước. Trường hợp điển hình là container vừa khởi động lại: `kg-server` là PID 1 và giữ nguyên hostname. Khóa này được chiếm lại **ngay**.
- Ngoại lệ 2: khóa không có, hoặc có thời điểm tạo (`startedAt`) không đọc được, cũng được coi là bỏ lại và chiếm lại ngay.
- Khi gặp lỗi `cleanup_failed`, khóa **không** tự gỡ được. Người vận hành phải kiểm tra và xóa `_staging/.lockdir` trong thư mục pack (xem bảng mã lỗi).

**Đổi phiên bản bị ngắt giữa chừng** (mất điện, container bị dừng): trước khi đổi, hệ thống ghi nhật ký `_staging/swap.json`. Thao tác kế tiếp đọc nhật ký và tự đưa bản cũ về chỗ cũ. Nếu nhật ký bị hỏng, đáng ngờ, hoặc không đưa bản cũ về được, cả DAAB lẫn LAAM đều báo `needs_repair`, giữ nguyên nhật ký và không đụng vào gì.

**Nguồn không truy cập được:** DAAB và LAAM vẫn chạy bình thường với các pack đã cài. Màn hình báo lỗi nguồn (xem bảng) và các nút cài tạm không dùng được.

**Mã lỗi màn hình có thể hiện:**

| Mã | Ở đâu | Nghĩa | Người vận hành làm gì |
|---|---|---|---|
| `busy` | DAAB, LAAM | Một thay đổi khác đang chạy trên thư mục pack. | Đợi một phút rồi thử lại. Nếu kéo dài quá 15 phút, xem mục "Khóa bị bỏ lại". |
| `downgrade` | DAAB, LAAM | Phiên bản chọn thấp hơn bản đang dùng. | Dùng "quay lại" thay vì cài. |
| `immutable` | DAAB, LAAM | Phiên bản đó đã có trên máy với nội dung khác bản tải về. | Không ghi đè. Báo người phát hành pack; kiểm tra registry có bị phát hành lại sai không. |
| `version_not_found` | DAAB, LAAM | Phiên bản không có trên nguồn (khi cài) hoặc không có trong `_versions` (khi quay lại). | Tải lại trang và chọn phiên bản khác. Kiểm tra catalog của registry. |
| `source_not_configured` | DAAB, LAAM | Chưa đặt `PACKS_SOURCE` (hoặc giá trị không hợp lệ). | Đặt `PACKS_SOURCE` / `PACKS_TOKEN` trong file env của dịch vụ rồi tạo lại container. |
| `source_unreachable` | DAAB, LAAM | Không kết nối được registry (mạng, DNS, registry dừng). | Kiểm tra registry (`/healthz`), DNS và tường lửa; thử lại sau. |
| `source_unauthorized` | DAAB, LAAM | Registry từ chối token (sai hoặc đã đổi). | Kiểm tra `PACKS_TOKEN` trùng với `KG_PACKS_READ_TOKEN` của registry, rồi tạo lại container. |
| `source_bad_response` | DAAB, LAAM | Registry trả về dữ liệu không đọc được, hoặc chuyển hướng, hoặc gói không có mã kiểm tra. Thường do `PACKS_SOURCE` trỏ sai chỗ, ví dụ vào trang của proxy. | Kiểm tra `PACKS_SOURCE` là địa chỉ gốc của registry (`<url>/v1/catalog` phải trả JSON). |
| `download_rejected` | DAAB | Gói tải về không qua kiểm tra an toàn (sai mã kiểm tra, cấu trúc lạ, quá lớn). Không có gì thay đổi. | Báo người phát hành pack; kiểm tra gói trên registry. |
| `bad_pack` | LAAM | Như `download_rejected`: gói tải về bị từ chối. | Như trên. |
| `reload_failed` | DAAB | Bản mới cài xong nhưng không nạp được, nên DAAB đã đưa bản cũ về. Chi tiết kỹ thuật (`file:dòng`) nằm ở trường `error.detail` của phản hồi API và trong log; thông báo trên màn hình là câu thường. | Báo người phát hành pack: phiên bản đó có lỗi nội dung. |
| `restore_failed` | DAAB | Bản mới không nạp được, **và** việc đưa bản cũ về cũng thất bại. Thư mục đang chứa bản mới. | Xử lý ngay: kiểm tra quyền ghi của `PACKS_DIR` và `_versions/<key>/`, rồi quay lại bằng `kg-packs rollback` trước khi khởi động lại DAAB. |
| `cleanup_failed` | DAAB | Thay đổi đã áp dụng và đang dùng, nhưng không gỡ được khóa. Các thay đổi sau sẽ báo bận. | Kiểm tra và xóa `_staging/.lockdir` trong thư mục pack, sau khi chắc chắn không còn thao tác nào đang chạy. |
| `timeout` | DAAB | Thao tác quá lâu và bị dừng (thường do tải chậm). | Xem lại danh sách trên trang để biết thay đổi đã áp dụng chưa; thử lại sau. |
| `cancelled` | DAAB | Yêu cầu bị ngắt trước khi xong (đóng trang, mất kết nối). | Xem lại danh sách; thử lại nếu cần. |
| `bad_local` | LAAM | Một bản đã lưu trên máy bị hỏng; không có gì thay đổi. | Kiểm tra `PACKS_DIR/<key>` và `_versions/<key>/`. |
| `version_not_stored` | LAAM | "Cho giống DAAB" sẽ phải đưa LAAM lùi về một bản cũ hơn; LAAM chỉ làm được việc đó từ các bản đã lưu. | Cập nhật DAAB lên cùng phiên bản. Nếu hai bên dùng chung thư mục, bấm Reload trong Template Library của DAAB. |
| `needs_repair` | DAAB, LAAM | Một lần đổi phiên bản trước bị ngắt, và nhật ký bị hỏng, đáng ngờ hoặc không đưa bản cũ về được. Không có gì bị đụng tới. Template Library của DAAB cũng hiện cảnh báo này. | Kiểm tra `_staging/swap.json`, `<key>/` và `_versions/<key>/` bằng tay rồi xóa nhật ký. |
| `daab_unavailable` | LAAM | Không hỏi được DAAB đang dùng phiên bản nào, nên chưa thể "cho giống DAAB". | Kiểm tra kết nối LAAM → DAAB; thử lại sau. |
| `forbidden` | DAAB, LAAM | Người dùng không phải quản trị viên máy chủ. | Dùng tài khoản global admin (DAAB) hoặc owner/admin (LAAM). |

## (e) Mapping là việc riêng

Pack chỉ định nghĩa **mô hình dữ liệu chuẩn, metric và luật**. Cách nối dữ liệu của từng khách vào mô hình đó (**mapping**) **không** thuộc repo `ennam.kg.packs`. Mapping được lưu trong DB DAAB (`project_mapping`) và được nạp từ file của dự án.

Thứ tự đúng cho một dự án mới, hoặc khi pack đổi entity/trường:

1. **Pack**: cài hoặc cập nhật phiên bản (mục c), rồi bật pack cho dự án (tab Industry Templates hoặc `kg-packs install --project <uuid> --pack <key>`).
2. **Mapping**: `kg-packs import-mapping --project <uuid> --file mapping.yaml [--approve]`.
3. **Metric**: `kg-packs run-metrics --project <uuid> [--from … --to …] [--metric key]…`.

Một bản pack MINOR/MAJOR thêm entity hoặc trường có thể cần cập nhật mapping trước khi metric mới chạy được.

## (f) Biến môi trường

| Biến | Đặt ở đâu | Ý nghĩa |
|---|---|---|
| `KG_PACKS_STORAGE_DIR` | dịch vụ `kg-pack-registry` | Thư mục lưu các gói đã phát hành (compose: `/data/packs`, volume `packs_registry`). Bắt buộc. |
| `KG_PACKS_READ_TOKEN` | `kg-pack-registry` | Token đọc (xem danh mục, tải về). Bắt buộc: thiếu thì dịch vụ không khởi động (và compose khởi động lại liên tục). |
| `KG_PACKS_PUBLISH_TOKEN` | `kg-pack-registry` | Token ghi (CI phát hành). Bắt buộc. Cũng dùng được để đọc. |
| `KG_PACKS_PORT` | `kg-pack-registry` và compose | Cổng dịch vụ (mặc định 8090; compose dùng nó cho cổng phía máy chủ). |
| `PACKS_DIR` | DAAB `kg-server`, LAAM `app` | Thư mục pack trong container, `/packs`. Phải ghi được. |
| `PACKS_SOURCE` | DAAB `kg-server`, LAAM `app` | Địa chỉ gốc của registry, ví dụ `https://packs.daab.ennam.vn`. Để trống thì tắt chức năng cài. Xem các lưu ý về địa chỉ bên dưới bảng. |
| `PACKS_TOKEN` | DAAB `kg-server`, LAAM `app` | Token **đọc** của registry (cùng giá trị với `KG_PACKS_READ_TOKEN`). |
| `PACKS_HOST_DIR` | compose (máy chủ) | Thư mục trên máy chủ được mount vào `/packs`. Mặc định `./packs` (workspace) và `../packs` (LAAM). **Hãy dùng đường dẫn tuyệt đối**: đường dẫn tương đối được tính theo thư mục của từng file compose. |
| `PACKS_REGISTRY_URL`, `PACKS_PUBLISH_TOKEN` | secret của repo `ennam.kg.packs` trên GitHub | Dùng cho CI phát hành. |

**Lưu ý về địa chỉ `PACKS_SOURCE`:**
- DAAB chạy trong cùng stack docker với registry có thể dùng `http://kg-pack-registry:8090`.
- LAAM là một compose riêng, nằm trên mạng `default` và `ecosystem-net`, **không** vào mạng `ennam-kg`. Vì vậy tên `kg-pack-registry` không phân giải được từ LAAM. LAAM cần dùng địa chỉ HTTPS, hoặc cổng registry trên máy chủ (ví dụ `http://host.docker.internal:8090`, chỉ trong mạng nội bộ).

**Giá trị điền ở đâu:** vận hành điền vào các file env theo từng dịch vụ mà DevOps quản lý (hoặc module secrets). Không ghi giá trị vào file compose, tài liệu hay commit.

**Lưu ý compose:**
- Các file compose khai báo `PACKS_SOURCE: ${PACKS_SOURCE:-}` và `PACKS_TOKEN: ${PACKS_TOKEN:-}` trong `environment:`.
- Compose lấy giá trị từ môi trường shell hoặc từ file `.env` cạnh file compose, **lúc đọc file compose**. Giá trị này **ghi đè** biến cùng tên trong `env_file:`.
- Nếu DevOps chỉ để giá trị trong một `env_file:` riêng, là file compose không dùng để nội suy, thì biến sẽ thành rỗng. Hãy đặt chúng ở nơi compose nội suy được, hoặc bỏ hai dòng đó khỏi `environment:` trên máy chủ đó.

**Lưu ý dev:**
- Mặc định `PACKS_HOST_DIR=./packs`. Thư mục này hiện vẫn được git theo dõi, và sau khi chuyển repo nó là một bản clone của `ennam.kg.packs`.
- Cài, cập nhật hay quay lại từ UI hoặc CLI sẽ đổi file trong đó và tạo `_versions/`, `_staging/`.
- Khi thử cài đặt, hãy đặt `PACKS_HOST_DIR` sang một thư mục riêng (đường dẫn tuyệt đối), rồi `kg-packs fetch` vào đó.

## (g) Yêu cầu hạ tầng cho DevOps

1. **Địa chỉ riêng cho registry, có HTTPS**, ví dụ `packs.daab.ennam.vn`, trỏ tới dịch vụ `kg-pack-registry` (cổng 8090 trong container). Health check của load balancer dùng `/healthz` và `/readyz` (không cần xác thực).
2. **Registry nghe trên `0.0.0.0:8090` bằng HTTP thường, không có TLS.**
   - Đặt nó sau một reverse proxy hoặc ALB có HTTPS.
   - Chặn cổng 8090 trên máy chủ bằng tường lửa. Chỉ proxy được gọi tới, và docker bridge nếu LAAM chạy trên cùng máy.
   - Token ghi đi kèm mọi lần phát hành, và token đọc đi kèm mọi lần tải về, nên không được để chúng đi qua mạng ngoài bằng HTTP thường.
   - DAAB và LAAM chỉ dùng `http://` trong mạng nội bộ.
3. **Lưu trữ.**
   - Hiện tại registry lưu trên volume (`packs_registry`, gắn vào `/data/packs`); cần sao lưu như dữ liệu.
   - Sau này có thể chuyển sang S3. Lưu trữ nằm sau interface `Store` trong `ennam.kg.go/internal/packdist/store.go` (`Put`, `Open`, `Catalog`), nên chỉ cần thêm một bản cài đặt S3 mà không đổi API.
4. **Hai token** (đọc và ghi), tạo mới và lưu trong module secrets:
   - token đọc → `KG_PACKS_READ_TOKEN` của registry, và `PACKS_TOKEN` của DAAB và LAAM;
   - token ghi → `KG_PACKS_PUBLISH_TOKEN` của registry, và secret `PACKS_PUBLISH_TOKEN` của repo `ennam.kg.packs`.

   Token không bao giờ xuất hiện trong log hay phản hồi. Muốn đổi token thì đổi secret rồi tạo lại container.
5. **Chỉ CI phát hành.** Secret CI trên GitHub repo `ennam.kg.packs` gồm `PACKS_REGISTRY_URL` (địa chỉ HTTPS ở mục 1) và `PACKS_PUBLISH_TOKEN`. GitHub Actions phải gọi tới được địa chỉ đó. Chỉ hệ thống CI giữ token ghi. Nếu job báo `409`, nghĩa là phiên bản đó đã có với nội dung khác: người phát hành phải tăng version, DevOps không làm gì trên registry (mục b).
6. **Volume `/packs` ghi được** cho DAAB (`kg-server`) và LAAM (`app`):
   - Thư mục trên máy chủ (`PACKS_HOST_DIR`) phải **tồn tại trước** và **ghi được bởi uid 1000**. DAAB release chạy bằng user `ennam` (uid 1000), LAAM bằng user `node` (uid 1000). Nếu thư mục chưa có, Docker tự tạo với chủ sở hữu root và việc cài sẽ lỗi.
   - Nên dùng đường dẫn tuyệt đối, và nên sao lưu (thư mục chứa cả các phiên bản đã lưu để quay lại).
   - **Dùng chung một `PACKS_DIR`** cho DAAB và LAAM chỉ được khi hai bên chạy **cùng uid** (1000 trong cả hai image release). Thư mục ghi được cho cả nhóm (group-writable) **không** giải quyết được, vì cả hai bộ cài đều đặt quyền 0755/0644.
   - `kg-server` của stack dev (stage `development`) chạy bằng **root**. Trên máy Linux, khi DAAB dev đã tạo `_staging/` hoặc `_versions/`, LAAM cài sẽ lỗi `EACCES`. Có hai cách: dùng hai `PACKS_HOST_DIR` riêng, hoặc chạy cả hai bằng uid 1000.
   - Lần đầu, có thể chép nội dung pack hiện tại vào thư mục, hoặc để trống rồi cài từ Template Library hay `kg-packs fetch`. Thư mục trống vẫn khởi động được, chỉ là chưa có pack nào.
7. **Sửa compose bản phát hành.** `docker-compose.release.yml` trước đây **không có** `PACKS_DIR` và volume pack cho `kg-server`, nên stack bản phát hành chạy mà không có pack nào. Nay đã thêm `PACKS_DIR: /packs`, volume `${PACKS_HOST_DIR:-./packs}:/packs`, `PACKS_SOURCE` và `PACKS_TOKEN`. Dịch vụ `kg-pack-registry` cũng đã có trong file đó.
8. **Image mới.** Các tag release cũ không có `/app/kg-pack-registry` và `/app/kg-packs`, nên cần build image mới cho DAAB, dashboard và LAAM rồi tạo lại container. Người vận hành làm bước này; agent không deploy.
9. **Lịch sử repo pack trước khi push.** Lịch sử git của `ennam.kg.packs` vẫn còn file `_projects/pharmacy-chain/mapping.yaml` ở các commit cũ. File này chứa UUID của dự án và nguồn dữ liệu demo, không có thông tin đăng nhập. Cần quyết định có chấp nhận điều đó hay không **trước khi push** lên GitHub. Nếu không chấp nhận, phải viết lại lịch sử (`git filter-repo --path _projects --invert-paths`) trước khi push.

**Câu hỏi cho DevOps:**
- LAAM chạy ở đâu: cùng máy và cùng mạng docker với DAAB, hay máy khác? Câu trả lời quyết định hai điều: LAAM gọi registry qua mạng nội bộ hay qua HTTPS công khai, và hai bên dùng chung hay riêng thư mục pack.
- Ai quản lý tên miền, load balancer và chứng chỉ TLS cho `packs.daab.ennam.vn` (hoặc tên khác)?
- Đã có sẵn registry, kho artifact hoặc CloudFront/S3 dùng được thay cho volume chưa? Nếu có, ta viết bản `Store` cho S3 thay vì giữ volume.
- Chính sách sao lưu và thời gian giữ lại cho volume `packs_registry` và thư mục `/packs` là gì?

## Phụ lục: lấy repo pack về máy

Dòng của repo `ennam.kg.packs` trong `scripts/repos.txt` đã có, nhưng vẫn để dạng chú thích (chưa bật). Lý do: thư mục `packs/` vẫn còn trong repo workspace, và `bootstrap.sh` báo lỗi khi gặp một đường dẫn đã tồn tại mà không phải repo git. Sau khi gỡ `packs/` khỏi workspace, bỏ dấu `#` ở dòng đó. Trước lúc đó, clone tay vào chỗ khác rồi trỏ `PACKS_DIR` / `PACKS_HOST_DIR` tới đó:

```bash
git clone git@github-dragoon:En-Nam/ennam.kg.packs.git <thư mục>
```

`github-dragoon` là một Host alias trong `~/.ssh/config` của từng máy (các repo khác trong `repos.txt` dùng `github.com`). Máy không có alias này thì dùng `git@github.com:En-Nam/ennam.kg.packs.git`.

Test tìm pack theo `PACKS_DIR` trước, nếu không có mới dùng `packs/` của workspace. Ví dụ: `PACKS_DIR=<thư mục pack> go test ./internal/intel/...` và `PACKS_DIR=<thư mục pack> npx vitest run src/lib/intel` (LAAM). Thư mục gốc của bản clone `ennam.kg.packs` dùng được trực tiếp.
