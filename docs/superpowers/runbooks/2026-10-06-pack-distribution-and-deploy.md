# Runbook — Phân phối template ngành (pack): phát hành, cài đặt, cập nhật, quay lại, triển khai

> Ngày: 2026-10-06. Kế hoạch: `docs/superpowers/plans/2026-10-06-pack-distribution.md`.
> Trong tài liệu này "pack" và "template ngành" là một (màn hình gọi là *template*, kỹ thuật gọi là *pack*).
> Tài liệu chỉ nêu **tên** biến môi trường, không bao giờ ghi giá trị token.

## (a) Thay đổi gì và ai làm gì

**Trước đây:** pack nằm trong thư mục `packs/` của repo workspace, được mount **chỉ đọc** vào DAAB (`kg-server`) và LAAM (`app`). Muốn đổi pack thì phải sửa repo, build lại image hoặc khởi động lại `daab-server`.

**Bây giờ:**

| Thành phần | Vai trò |
|---|---|
| Repo `ennam.kg.packs` | Nguồn duy nhất của nội dung pack (`retail/`, `pharmacy/`), có lịch sử và số phiên bản riêng. Không chứa mapping của khách (`_projects/`). |
| Dịch vụ `kg-pack-registry` (container `daab-packs`, cổng 8090) | Kho lưu các phiên bản pack đã phát hành. CI đẩy lên, DAAB và LAAM tải về. Một phiên bản đã phát hành là **bất biến**. |
| DAAB — trang **Template Library** (dashboard, mục ADMIN) | Quản trị viên máy chủ cài, cập nhật, quay lại phiên bản cũ. Pack mới được nạp **không cần khởi động lại**. |
| LAAM — **Cài đặt → Mẫu theo ngành** ("Industry templates") | Owner/admin của LAAM cài, cập nhật, quay lại, và "cho giống DAAB". |
| CLI `kg-packs fetch / versions / rollback` | Cách làm bằng dòng lệnh cho vận hành (có sẵn trong image DAAB: `/app/kg-packs`). |
| `PACKS_DIR` (`/packs` trong container) | Thư mục pack đang dùng. Nay phải **ghi được** vì việc cài đặt ghi vào đó. |

**Phân vai:**
- **Quản trị viên máy chủ** (global admin của DAAB; owner/admin của LAAM): cài, cập nhật, quay lại phiên bản pack **cho cả máy chủ**.
- **Quản trị viên dự án**: vẫn **bật/tắt** pack cho từng dự án như trước (tab **Industry Templates** trong dự án DAAB, bảng `pack_install`). Phần này không đổi.

**Trạng thái của bản phát hành này:** dịch vụ registry, CLI và trang LAAM đã xong. Các endpoint thư viện của DAAB (`/api/v1/admin/packs/...`) và trang Template Library trên dashboard **đang được thêm trong bản phát hành này**; nội dung bên dưới mô tả theo hợp đồng trong kế hoạch (Task 4 và Task 6).

**Bố cục trên đĩa** (giống nhau cho DAAB và LAAM):

```text
PACKS_DIR/
├── retail/                     # phiên bản đang dùng (tên thư mục = key của pack)
├── pharmacy/
├── _versions/<key>/<version>/  # các phiên bản trước, để quay lại
└── _staging/                   # vùng tạm khi cài; có khóa và nhật ký đổi phiên bản
```

Thư mục bắt đầu bằng `_` hoặc `.` bị bộ nạp pack bỏ qua. Mọi thư mục khác đều được coi là một pack (phải có `pack.yaml`), nên `PACKS_DIR` **không** được trỏ thẳng vào bản clone của repo `ennam.kg.packs` (thư mục `scripts/` sẽ làm DAAB nạp lỗi): hãy dùng thư mục do `kg-packs fetch` / màn hình cài đặt tạo ra, hoặc một bản chép chỉ gồm các thư mục pack.

**Lưu ý cho stack dev (đến khi gỡ `packs/` khỏi workspace):** mặc định `PACKS_HOST_DIR` là `./packs`, tức thư mục đang được git theo dõi. Cài/cập nhật/quay lại sẽ đổi file trong `packs/retail`, `packs/pharmacy` và tạo `packs/_versions`, `packs/_staging` trong repo workspace. Khi thử cài đặt ở dev, hãy đặt `PACKS_HOST_DIR` sang một thư mục riêng (đường dẫn tuyệt đối), hoặc chấp nhận và đừng commit các thay đổi đó.

## (b) Phát hành một phiên bản pack

Làm trong repo `ennam.kg.packs`:

1. Sửa nội dung pack. Mọi thay đổi metric, evidence, luật hoặc nội dung khác **đều phải tăng `version`** trong `<key>/pack.yaml`:
   - MAJOR: xóa hoặc đổi tên metric, entity, mã luật;
   - MINOR: thêm metric, entity, luật, kịch bản, trường;
   - PATCH: sửa ngưỡng hoặc câu chữ.
2. Thêm mục `## [x.y.z] - YYYY-MM-DD` vào `CHANGELOG.md`. Nội dung mục này được gửi lên registry làm "có gì mới" (hiện trong nút **See what's new** / ghi chú phiên bản).
3. Kiểm tra cục bộ: `bash scripts/release_test.sh`, rồi `bash scripts/release.sh <key>` (tạo `dist/<key>-<version>.tar.gz` và `.sha256`).
4. Commit, gắn tag `vX.Y.Z` và push tag.

**CI làm gì** (workflow `.github/workflows/publish.yml`, chạy khi push tag `v*` hoặc chạy tay):
- Kiểm tra hai secret của repo có mặt: `PACKS_REGISTRY_URL` (địa chỉ registry) và `PACKS_PUBLISH_TOKEN` (token ghi). Secret chỉ đi qua biến môi trường, không in ra log.
- Chạy test của công cụ phát hành, đóng gói **mọi** pack, rồi gửi từng gói lên `PUT <registry>/v1/packs/<key>/<version>` kèm mã kiểm tra và changelog.
- Kết quả: `201` = đã phát hành; `200` = phiên bản đó đã có với nội dung y hệt (không làm gì, bình thường với pack không đổi); `409` = phiên bản đó đã tồn tại với nội dung **khác** → job đỏ: phải tăng version rồi phát hành lại. Không có cách ghi đè một phiên bản đã phát hành.

## (c) Cài đặt / cập nhật / quay lại

Điều kiện chung: trên máy chủ đã đặt `PACKS_SOURCE` và `PACKS_TOKEN` (xem mục f). Nếu chưa đặt, màn hình báo "chưa có nguồn template" và không hiện nút cài.

### DAAB — Template Library (dashboard)

Dashboard DAAB (:3500) → mục **ADMIN → Template Library** (chỉ global admin; khóa API theo dự án bị từ chối).

- Mỗi thẻ template: tên, "Version in use", trạng thái ("Up to date" / "New version … available" / "Not installed"), số dự án đang dùng.
- **Install** / **Update**: có hộp xác nhận ("Alerts and numbers for the {n} projects that use it may change…"). Sau khi cài, DAAB nạp lại danh mục pack ngay; nếu bản mới nạp lỗi thì DAAB **giữ bản cũ** và báo lỗi.
- **See what's new**: hiện changelog của phiên bản đích.
- **Go back to an earlier version**: chọn một phiên bản đã lưu trên máy chủ, xác nhận.
- Endpoint phía sau (global admin): `GET /api/v1/admin/packs/library`, `POST /api/v1/admin/packs/{key}/install` (`{"version":"0.2.0"}`), `POST /api/v1/admin/packs/{key}/rollback` (`{"version":"0.1.0"}`), `POST /api/v1/admin/packs/reload`.
- Trong tab **Industry Templates** của từng dự án sẽ có phiên bản đang dùng và nhãn nhỏ "Update available".

### LAAM — Cài đặt → Mẫu theo ngành

Đăng nhập owner/admin → **Cài đặt → Mẫu theo ngành** (`/settings/industry-templates`).

- Mỗi mẫu: "Đang dùng: x.y.z", "Công cụ dữ liệu của bạn (DAAB) dùng: …" với nhãn xanh **Cùng phiên bản** hoặc nhãn vàng **Khác với công cụ dữ liệu của bạn (DAAB) — kết quả có thể sai**, "Mới nhất hiện có: …".
- Nút **Cập nhật lên bản mới nhất**, **Dùng giống công cụ dữ liệu của bạn (DAAB): x.y.z** (chỉ hiện khi khác), **Cho tất cả giống công cụ dữ liệu của bạn (DAAB)**, và trong "Thêm lựa chọn": **Dùng một phiên bản đã lưu khác**.
- Mọi thao tác đều hỏi xác nhận; mỗi lần ghi có một dòng `audit_log` (`intel.packs.install`, `intel.packs.rollback`).
- LAAM nạp pack theo từng lần phân tích, nên phiên bản mới có hiệu lực **từ lần kiểm tra tới**; không cần khởi động lại.

### Dòng lệnh `kg-packs`

Trong container DAAB (release: `docker compose -f docker-compose.release.yml exec kg-server /app/kg-packs …`; dev: `docker exec -w /app daab-server go run ./cmd/kg-packs …`):

```bash
kg-packs versions                                   # phiên bản đang dùng và đã lưu của từng pack
kg-packs fetch    --pack pharmacy --version 0.3.0   # tải, kiểm tra, cài và kích hoạt
kg-packs rollback --pack pharmacy --version 0.2.0   # quay lại một phiên bản đã lưu
```

- `--source` mặc định lấy từ `PACKS_SOURCE`; token chỉ đọc từ biến môi trường (`PACKS_TOKEN`, hoặc tên biến khác qua `--token-env`). **Không bao giờ** truyền token làm giá trị cờ.
- `--packs-dir` mặc định `$PACKS_DIR` hoặc `/packs`.
- **Quan trọng:** CLI chỉ đổi file trên đĩa. DAAB đang chạy **chưa** thấy thay đổi cho đến khi nạp lại: bấm nạp lại trong Template Library hoặc gọi `POST /api/v1/admin/packs/reload` (global admin). LAAM thấy ở lần phân tích tới.
- Lệnh `install` cũ giữ nguyên nghĩa: **bật** pack cho một dự án (`kg-packs install --project <uuid> --pack <key>`).

## (d) Cập nhật, quay lại, "cho giống DAAB"; lệch phiên bản; "đang bận"

**Cập nhật:** chỉ cài được phiên bản **cao hơn** phiên bản đang dùng. Cài phiên bản thấp hơn bị từ chối (DAAB trả `409 downgrade`): muốn về bản cũ thì dùng **quay lại**.

**Quay lại:** chọn một phiên bản đã lưu trong `_versions/<key>/`. Mỗi lần cập nhật, bản đang dùng được cất vào đó, nên luôn quay lại được bản ngay trước. Quay lại không cần mạng.

**Cho giống DAAB (LAAM):** LAAM cài **đúng** phiên bản DAAB đang dùng cho từng pack bị lệch. Nếu bản của DAAB **cũ hơn** và chưa được lưu trên máy LAAM, LAAM báo "phiên bản cũ hơn … chưa được lưu trên máy chủ này": cần cài phiên bản đó trước (hoặc cập nhật DAAB lên).

**Bất biến:** cùng key + version mà nội dung khác thì bị từ chối (`immutable`), cả khi phát hành lẫn khi cài. Nếu gặp: báo người phát hành pack, đừng xóa tay.

**Lệch phiên bản hiện ra ở đâu:**
- LAAM, trang Mẫu theo ngành: nhãn vàng và dải cảnh báo "Một số mẫu khác phiên bản với công cụ dữ liệu của bạn (DAAB)…".
- Cảnh báo trong kết quả phân tích của LAAM: mục bắt đầu bằng `pack_version_mismatch:`.
- DAAB Template Library: danh sách `drift` (phiên bản ghi trong dự án khác phiên bản trên đĩa).
- Khi DAAB và LAAM dùng **chung** một thư mục pack (stack dev: cùng `./packs` trên máy), cài ở một bên là cả hai cùng đổi. Khi dùng thư mục riêng (thường gặp ở máy chủ thật), phải cập nhật cả hai, hoặc dùng "cho giống DAAB" ở LAAM.

**"Đang bận" (busy) nghĩa là gì:** tại mỗi thời điểm chỉ một thao tác cài/quay lại được chạy trên một thư mục pack, kể cả khi DAAB (Go) và LAAM (Node) cùng dùng chung thư mục. Thao tác thứ hai chờ tối đa khoảng 60 giây rồi báo "Một thay đổi mẫu khác đang chạy. Hãy đợi một phút rồi thử lại." (DAAB: `409 busy`). Cứ đợi rồi thử lại.
- Nếu tiến trình đang giữ khóa bị chết: trên **cùng máy** khóa được lấy lại ngay khi tiến trình đó không còn chạy; ở máy khác (hoặc container khác) khóa **tự hết hạn sau 15 phút**. Không cần xóa khóa bằng tay.
- Nếu một lần đổi phiên bản bị ngắt giữa chừng (mất điện, container bị dừng), hệ thống ghi một "nhật ký đổi phiên bản" trước khi đổi; lần cài kế tiếp đọc nhật ký và **tự đưa bản cũ về chỗ cũ**. Phiên bản đang dùng không bao giờ bị để dở dang.
- Nếu màn hình báo "cần kiểm tra thủ công" (`needs_repair`): báo kỹ thuật kiểm tra `PACKS_DIR/_staging/` và `_versions/<key>/` trước khi thử lại.

**Nguồn không truy cập được:** DAAB và LAAM vẫn chạy bình thường với các pack đã cài; màn hình chỉ báo "không kết nối được nguồn template, thử lại sau".

## (e) Mapping là việc riêng

Pack chỉ định nghĩa **mô hình dữ liệu chuẩn, metric và luật**. Cách nối dữ liệu của từng khách vào mô hình đó (**mapping**) **không** nằm trong repo `ennam.kg.packs`; mapping của dự án demo vẫn ở workspace (`packs/_projects/…`, sẽ chuyển sang chỗ khác khi gỡ `packs/` khỏi workspace) và được lưu trong DB DAAB (`project_mapping`).

Thứ tự đúng cho một dự án mới hoặc khi pack đổi entity/trường:

1. **Pack**: cài/cập nhật phiên bản (mục c), rồi bật pack cho dự án (tab Industry Templates hoặc `kg-packs install --project <uuid> --pack <key>`).
2. **Mapping**: `kg-packs import-mapping --project <uuid> --file mapping.yaml [--approve]`.
3. **Metric**: `kg-packs run-metrics --project <uuid> [--from … --to …] [--metric key]…`.

Một bản pack MINOR/MAJOR thêm entity hoặc trường có thể cần cập nhật mapping trước khi metric mới chạy được.

## (f) Biến môi trường

| Biến | Đặt ở đâu | Ý nghĩa |
|---|---|---|
| `KG_PACKS_STORAGE_DIR` | dịch vụ `kg-pack-registry` | Thư mục lưu các gói đã phát hành (compose: `/data/packs`, volume `packs_registry`). Bắt buộc. |
| `KG_PACKS_READ_TOKEN` | `kg-pack-registry` | Token đọc (xem danh mục, tải về). Bắt buộc: thiếu thì dịch vụ không khởi động. |
| `KG_PACKS_PUBLISH_TOKEN` | `kg-pack-registry` | Token ghi (CI phát hành). Bắt buộc. Cũng dùng được để đọc. |
| `KG_PACKS_PORT` | `kg-pack-registry` và compose | Cổng dịch vụ (mặc định 8090; compose dùng nó cho cổng phía máy chủ). |
| `PACKS_DIR` | DAAB `kg-server`, LAAM `app` | Thư mục pack trong container, `/packs`. Phải ghi được. |
| `PACKS_SOURCE` | DAAB `kg-server`, LAAM `app` | Địa chỉ gốc của registry (vd `https://packs.daab.ennam.vn`). Riêng DAAB trong cùng stack docker có thể dùng `http://kg-pack-registry:8090`. LAAM là một compose riêng (mạng `default` + `ecosystem-net`, **không** vào mạng `ennam-kg`), nên tên `kg-pack-registry` không phân giải được từ LAAM: dùng địa chỉ HTTPS, hoặc cổng registry trên máy chủ (vd `http://host.docker.internal:8090`, chỉ trong mạng nội bộ). Để trống = tắt chức năng cài. |
| `PACKS_TOKEN` | DAAB `kg-server`, LAAM `app` | Token **đọc** của registry (cùng giá trị với `KG_PACKS_READ_TOKEN`). |
| `PACKS_HOST_DIR` | compose (máy chủ) | Thư mục trên máy chủ được mount vào `/packs`. Mặc định `./packs` (workspace) và `../packs` (LAAM). **Hãy dùng đường dẫn tuyệt đối**: đường dẫn tương đối được tính theo thư mục của từng file compose. |
| `PACKS_REGISTRY_URL`, `PACKS_PUBLISH_TOKEN` | secret của repo `ennam.kg.packs` trên GitHub | Dùng cho CI phát hành. |

**Giá trị điền ở đâu:** vận hành điền vào các file env theo từng dịch vụ mà DevOps quản lý (hoặc module secrets). Không ghi giá trị vào file compose, tài liệu hay commit.

**Lưu ý compose:** các file compose khai báo `PACKS_SOURCE: ${PACKS_SOURCE:-}` và `PACKS_TOKEN: ${PACKS_TOKEN:-}` trong `environment:`. Giá trị lấy từ môi trường shell hoặc file `.env` cạnh file compose **lúc compose đọc file**, và **ghi đè** giá trị cùng tên trong `env_file:`. Nếu DevOps chỉ để giá trị trong một `env_file:` riêng mà compose không dùng để nội suy, biến sẽ bị thành rỗng: hãy đặt chúng ở nơi compose nội suy được, hoặc bỏ hai dòng đó khỏi `environment:` trên máy chủ đó.

## (g) Yêu cầu hạ tầng cho DevOps

1. **Địa chỉ riêng cho registry**, HTTPS, ví dụ `packs.daab.ennam.vn`, trỏ tới dịch vụ `kg-pack-registry` (cổng 8090 trong container). Cần `/healthz` và `/readyz` (không cần xác thực) cho health check của load balancer.
2. **HTTPS là bắt buộc** cho DAAB/LAAM khi gọi registry qua mạng ngoài. `http://` thường chỉ chấp nhận trong mạng nội bộ (vd `http://kg-pack-registry:8090` cho DAAB trong cùng mạng docker `ennam-kg`; LAAM hiện không ở mạng đó).
3. **Lưu trữ:** hiện tại là volume (`packs_registry`, gắn vào `/data/packs`); cần sao lưu như dữ liệu. Sau này có thể chuyển sang S3: lưu trữ nằm sau interface `Store` trong `ennam.kg.go/internal/packdist/store.go` (`Put`, `Open`, `Catalog`), chỉ cần thêm một bản cài đặt S3, không đổi API.
4. **Hai token** (đọc và ghi) tạo mới, lưu trong module secrets:
   - token đọc → `KG_PACKS_READ_TOKEN` của registry và `PACKS_TOKEN` của DAAB và LAAM;
   - token ghi → `KG_PACKS_PUBLISH_TOKEN` của registry và secret `PACKS_PUBLISH_TOKEN` của repo `ennam.kg.packs`.
   Token không bao giờ xuất hiện trong log hay phản hồi; đổi token = đổi secret rồi tạo lại container.
5. **Secret CI** trên GitHub repo `ennam.kg.packs`: `PACKS_REGISTRY_URL` (địa chỉ HTTPS ở mục 1) và `PACKS_PUBLISH_TOKEN`. GitHub Actions phải gọi được tới địa chỉ đó.
6. **Volume `/packs` ghi được** cho DAAB (`kg-server`) và LAAM (`app`):
   - thư mục trên máy chủ (`PACKS_HOST_DIR`) phải **tồn tại trước** và **ghi được bởi uid 1000** (DAAB chạy bằng user `ennam` uid 1000, LAAM bằng user `node` uid 1000). Nếu thư mục chưa có, Docker tự tạo với chủ sở hữu root và việc cài sẽ lỗi;
   - nên dùng đường dẫn tuyệt đối; nên sao lưu (chứa cả các phiên bản đã lưu để quay lại);
   - DAAB và LAAM có thể dùng chung một thư mục (an toàn nhờ khóa dùng chung giữa hai bên) hoặc thư mục riêng (khi chạy trên máy khác nhau).
   - Lần đầu: chép nội dung pack hiện tại vào thư mục đó, hoặc để trống rồi cài từ Template Library / `kg-packs fetch`.
7. **Sửa compose bản phát hành:** `docker-compose.release.yml` trước đây **không có** `PACKS_DIR` và volume pack cho `kg-server` (stack bản phát hành chạy mà không có pack nào). Nay đã thêm `PACKS_DIR: /packs`, volume `${PACKS_HOST_DIR:-./packs}:/packs`, `PACKS_SOURCE`, `PACKS_TOKEN`; dịch vụ `kg-pack-registry` cũng đã có trong file đó.
8. **Sau khi cấu hình:** build lại image DAAB và LAAM rồi tạo lại container (người vận hành làm; agent không deploy).

**Câu hỏi cho DevOps:**
- LAAM chạy ở đâu (cùng máy/cùng mạng docker với DAAB hay máy khác)? Điều này quyết định LAAM gọi registry qua mạng nội bộ hay qua HTTPS công khai, và hai bên dùng chung hay riêng thư mục pack.
- Ai quản lý tên miền và load balancer cho `packs.daab.ennam.vn` (hoặc tên khác) và chứng chỉ TLS?
- Đã có sẵn registry/kho artifact hoặc CloudFront/S3 dùng được thay cho volume chưa? Nếu có, ta viết bản `Store` cho S3 thay vì giữ volume.
- Chính sách sao lưu và giữ lại cho volume `packs_registry` và thư mục `/packs`?

## Phụ lục: lấy repo pack về máy

Dòng của repo `ennam.kg.packs` trong `scripts/repos.txt` đã có nhưng còn là chú thích (chưa bật), vì thư mục `packs/` vẫn còn trong repo workspace và `bootstrap.sh` sẽ báo lỗi khi gặp một đường dẫn đã tồn tại mà không phải repo git. Sau khi gỡ `packs/` khỏi workspace, bỏ dấu `#` ở dòng đó. Trước lúc đó, clone tay vào chỗ khác rồi trỏ `PACKS_DIR` / `PACKS_HOST_DIR` tới đó:

```bash
git clone git@github-dragoon:En-Nam/ennam.kg.packs.git <thư mục>
```

`github-dragoon` là một Host alias trong `~/.ssh/config` của từng máy (các repo khác trong `repos.txt` dùng `github.com`); máy không có alias này thì dùng `git@github.com:En-Nam/ennam.kg.packs.git`.

Test cũng tìm pack theo `PACKS_DIR` trước, rồi mới tới `packs/` của workspace, ví dụ `PACKS_DIR=<thư mục pack đã cài> go test ./internal/intel/...` và `PACKS_DIR=<thư mục pack đã cài> npx vitest run src/lib/intel` (LAAM). Lưu ý:
- `<thư mục pack đã cài>` chỉ chứa các thư mục pack (xem mục a), không phải bản clone repo.
- Các test cần DB (`internal/intel/packtest`, `engine/pharmacy_enum_test.go`, khi đặt `KG_TEST_DATABASE_URL`) còn đọc `_projects/pharmacy-chain/mapping.yaml` trong `PACKS_DIR`; thư mục pack không có `_projects/` thì các test này lỗi cho đến khi chỗ đặt mapping demo được chuyển (bước bàn giao cuối).
- `packs-content.test.ts` của LAAM đang ghi cứng phiên bản `0.1.0`; với pack `0.2.0` của repo mới thì test đó báo lỗi cho đến khi được cập nhật.
