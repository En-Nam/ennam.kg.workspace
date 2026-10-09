# Runbook: làm "trẻ" dữ liệu demo nhà thuốc (+70 ngày, as-of 2026-10-09)

## Mục đích

LAAM Home đang báo "Dữ liệu cũ hơn bản phân tích này 68 ngày", vì gói dữ liệu demo kết thúc ngày 2026-07-31. Ta dời **mọi** cột ngày/giờ của 25 bảng thêm **70 ngày** (10 tuần), nên cửa sổ dữ liệu mới là **2025-10-10 → 2026-10-09** (thứ Sáu, giống 2026-07-31). Sau đó ta tạo lại chỉ tiêu cửa hàng (`targets.xlsx`) cho tháng mới, để đủ 9 phát hiện kỳ vọng vẫn còn.

Đã kiểm tra trên DB tạm (đã xoá), DB thật `pharmacy_demo` **chưa** bị đụng tới (2026-10-09):
- 25/25 bảng khớp số dòng.
- Từng bảng sau khi trừ lại 70 ngày trùng md5 100% với bản gốc.
- `verify_plants.sql -v shift_days=70` cho kết quả y hệt bản gốc, chỉ khác dòng `window`.
- Ngày lớn nhất của các bảng sự kiện chính là 2026-10-09.
- Luật chỉ tiêu (RET-SALES-001, RET-MARGIN-001) được tính lại bằng SQL mô phỏng đúng công thức của LAAM. Kết quả ở mục 1.

> Chạy lệnh từ thư mục gốc workspace: `cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace`.
> Chỉ dùng container `daab-postgres` (cổng 5433). Không đụng cổng 5432. Phía LAAM chỉ đi qua `docker exec laam-v2-app node` (mục 4, phần 3).

## 0. Vì sao là +70, và giới hạn thời gian

**Cách tính as-of và độ tươi (đọc từ mã nguồn):**
- DAAB `kg-packs set-as-of` từ chối ngày **sau "hôm nay" theo múi giờ dự án (America/Chicago)** (`ennam.kg.go/cmd/kg-packs/main.go`, `setAsOf`). Ngày bằng hôm nay thì được chấp nhận.
- DAAB đo độ tươi bằng `as_of − ngày mới nhất của dữ liệu`:
  - 0 = current, 1–6 = delayed, ≥7 = stale (`engine/runner.go`, `measureFreshness`).
  - Data kết thúc đúng as-of nên luôn là "current".
  - Các dòng có ngày sau as-of cho độ trễ âm, cũng là "current".
- LAAM Home tính độ trễ = `floor((thời điểm chạy phân tích − as_of 00:00Z) / 1 ngày)` và chỉ cảnh báo khi > 7 (`LAAM/src/components/intel/home/DataStatus.tsx`, `STALE_AFTER_DAYS = 7`). LAAM không có kiểm tra "as-of ở tương lai".
- Job hằng ngày chạy lúc 06:00 America/Chicago (11:00 UTC), tức là tự chạy mỗi ngày.

**So sánh hai lựa chọn:**

| Shift | as-of | Độ trễ khi chạy hôm nay | Cảnh báo |
|---|---|---|---|
| +63 | 2026-10-02 | 7 | Quay lại từ lần chạy 2026-10-10 |
| **+70** | **2026-10-09** | 0 | Yên lặng tới hết lần chạy **2026-10-16**; lần chạy 2026-10-17 báo "8 ngày" |

→ Chọn **+70**.

⚠️ **Ràng buộc giờ:**
- `set-as-of --date 2026-10-09` chỉ chạy được sau **2026-10-09 00:00 giờ Chicago** (= 05:00 UTC = 12:00 giờ Việt Nam). Trước giờ đó lệnh bị từ chối vì là "ngày tương lai".
- Ngày 2026-10-09 lúc 06:00 Chicago, ngày 9/10 trên thực tế mới bắt đầu, nhưng dữ liệu demo đã có đủ cả ngày đó. Phân tích vẫn đúng vì mọi luật lọc theo as-of. Đây chỉ là chuyện ngữ nghĩa.

## 1. Chỉ tiêu cửa hàng: vì sao phải tạo lại, và công thức

**Vì sao phải tạo lại:**
- RET-SALES-001 so **doanh số từ đầu tháng tới as-of** với **chỉ tiêu tháng × số ngày đã qua / số ngày của tháng** (`LAAM/src/lib/intel/engine/rules.ts`, `compare: target`, `monthToDate`). RET-MARGIN-001 so tỉ lệ lãi gộp, không chia theo ngày.
- Chỉ tiêu đến từ dataset file `store_targets`, được tải lên từ `targets.xlsx` (mapping `target`, mode=file, cột `Store ID | Metric Key | Period | Target Value`).
- Dời ngày làm as-of rơi vào tháng 10/2026, chỉ có 9 ngày (1–9/10, tức 23–31/7 của dữ liệu gốc). Nếu giữ `targets.xlsx` cũ, kết quả là: PH-004 0.946 (chỉ warning), PH-002 0.972, PH-001 1.16. Mất mức critical của FND-008.

**Cách tạo lại:** `scripts/demo_data/retarget_demo.py` (có test, chạy lại luôn ra cùng kết quả).

Số liệu thực tế được tính theo đúng định nghĩa metric `retail.net_sales` / `retail.gross_margin_pct` trên mapping `pharmacy_demo`:
- Chỉ đơn `completed`.
- Bỏ sản phẩm kê đơn.
- Doanh số thuần = SL × giá − giảm giá.
- Giá vốn = SL × COALESCE(giá vốn dòng, giá vốn sản phẩm).

`run_rate(tháng) = thực tế × số ngày của tháng / số ngày có dữ liệu trong tháng`.

| Tháng | Công thức net_sales |
|---|---|
| Trước tháng as-of | `floor100(run_rate × 0.98)` (giống bộ sinh dữ liệu: "đạt chỉ tiêu") |
| Tháng as-of, các cửa hàng khác | `floor100(run_rate × 0.98)` → tỉ lệ ≥ 1/0.98 = 1.0204 |
| Tháng as-of, PH-004 | `round100(run_rate / plant_ratio)` → tỉ lệ ≈ plant_ratio |
| Sau tháng as-of | `round100(thực tế cùng tháng năm trước × 1.03)` |

- `plant_ratio` = thực tế tháng 7/2026 gốc của PH-004 / chỉ tiêu tháng 7 gốc = **0.5666**. Script đọc giá trị này từ gói gốc, không đặt cứng.
- `gross_margin_pct` = `round(gm_thực_tế − 0.55, 1)` cho các tháng có dữ liệu. Tháng tương lai dùng trung bình 3 tháng đủ gần nhất − 0.55. Vì vậy RET-MARGIN-001 không bao giờ bắn: luật cần gm ≤ chỉ tiêu − 2.
- Khoảng tháng: từ tháng đầu có dữ liệu (2025-10) tới tháng 12 của năm as-of (2026-12). Tổng 15 tháng × 5 cửa hàng × 2 metric = 150 dòng. Bản gốc có 170 dòng, gồm 2025-08..09 nay không còn dữ liệu.

**Kết quả** (SQL mô phỏng trên DB tạm, as-of 2026-10-09, cửa sổ từ đầu tháng 1–9/10):

| Cửa hàng | Doanh số từ đầu tháng | Chỉ tiêu chia theo ngày | Tỉ lệ | RET-SALES-001 |
|---|---|---|---|---|
| PH-001 | 21 092 | 20 642 | 1.0218 | — |
| PH-002 | 19 391 | 18 987 | 1.0213 | — |
| PH-003 | 19 035 | 18 639 | 1.0212 | — |
| **PH-004** | 16 637 | 29 352 | **0.5668** | **critical** (gốc 0.5666) |
| PH-005 | 19 068 | 18 668 | 1.0214 | — |

RET-MARGIN-001: không cửa hàng nào bắn (gm thực tế cao hơn chỉ tiêu 0.5–0.6 điểm).

Gốc (as-of 2026-07-31): PH-004 0.5666 critical, các cửa hàng khác 1.0199–1.0208. SQL mô phỏng tái tạo đúng kết quả này, nên công thức mô phỏng là đáng tin.

⚠️ **Điều người xem có thể thấy:**
- Chỉ tiêu tháng 10 của PH-004 là **101 100**, trong khi các cửa hàng khác chỉ 64–71 nghìn. Lý do: trong 23–31/7 gốc, PH-004 đã hồi phục một phần (chỉ còn thấp hơn khoảng 15% so với các cửa hàng khác). Muốn giữ tỉ lệ 0.57 thì chỉ tiêu phải cao.
- Nếu muốn chỉ tiêu PH-004 "bình thường" (bằng mức trước khi sụt, tức thực tế tháng 8/2026 = 70 370), tỉ lệ sẽ là **0.814**: high, sát ngưỡng critical 0.80. FND-008 vẫn được bắt, vì trình kiểm tra không xét mức độ.
- Hiện script dùng 0.5666 theo yêu cầu.

## 2. Tạo gói dữ liệu (không phá gì)

```bash
scripts/demo_data/refresh_demo.sh 2026-10-09
```

Lệnh này tạo `demo_mockdata_shifted_70/`, gồm 25 CSV, `targets.xlsx` và `SHIFT_MANIFEST.json`, rồi in ra các bước cutover theo đúng thứ tự.

- Lệnh từ chối nếu ở Chicago vẫn chưa sang ngày 2026-10-09.
- Nếu cần, có thể chạy tay:

  ```bash
  cd scripts/demo_data && uv run pytest -q          # kỳ vọng: 127 passed
  uv run python shift_dates.py --days 70 --output ../../demo_mockdata_shifted_70
  uv run python retarget_demo.py --data ../../demo_mockdata_shifted_70 && cd ../..
  ```

- `demo_mockdata/` gốc giữ nguyên. Thư mục `demo_mockdata_shifted_70/` không được commit.

## 3. Sao lưu (bắt buộc)

```bash
TS=$(date +%Y%m%dT%H%M%S); B=.superpowers/backups; mkdir -p $B     # thư mục này đã được git-ignore
U=$(docker exec daab-postgres printenv POSTGRES_USER)
docker exec daab-postgres pg_dump -U "$U" -Fc pharmacy_demo > $B/pharmacy_demo_precutover_$TS.dump
docker exec daab-postgres pg_dump -U "$U" -Fc -t metric_value -t project_intel_settings -t file_dataset -t file_dataset_row ennam_kg \
  > $B/ennam_kg_intel_precutover_$TS.dump
docker exec -i daab-postgres pg_restore --list < $B/pharmacy_demo_precutover_$TS.dump | grep -c "TABLE DATA public"   # 25
```

Cutover 2026-10-09 đã dùng các bản sao lưu `pharmacy_demo_precutover_20261009T103542.dump` và `ennam_kg_intel_precutover_20261009T103542.dump`, nằm trong `.superpowers/backups/`.

## 4. Cutover: thứ tự đã chạy thành công (2026-10-09)

Ba phần đều nằm trong `scripts/demo_data/cutover.sh`. Script này được tổng quát hoá từ các script `cutover_part1/2/3.sh` mà người điều phối đã chạy. Các script gốc chỉ nằm trong scratchpad của phiên và **không** có trong repo. Script mới không chạy gì nếu thiếu tham số.

Yêu cầu chung:
- Chạy từ thư mục gốc workspace.
- `DAAB_API_KEY` phải có trong môi trường. Script không in khoá này.
- Cổng kg-server lấy từ `KG_SERVER_PORT` trong `.env` (chỉ đọc đúng khoá đó), mặc định 8082.

| Phần | Khi nào chạy | Lệnh | Các bước bên trong |
|---|---|---|---|
| 1 | Bất cứ lúc nào | `CONFIRM_LIVE_RELOAD=yes scripts/demo_data/cutover.sh part1 demo_mockdata_shifted_70 $B/pharmacy_demo_precutover_$TS.dump` | (1) nạp `pharmacy_demo`<br>(2) `verify_plants.sql -v shift_days=70`<br>(3) kiểm tra ngày cuối = 2026-10-09<br>(4) `resync_daab_schema.sh`<br>(5) tải `store_targets` lần 1 (replace, kỳ vọng 150 dòng) |
| 2 | Từ **00:00 giờ Chicago ngày 2026-10-09** (12:00 giờ VN); script tự chặn nếu sớm | `scripts/demo_data/cutover.sh part2 demo_mockdata_shifted_70` | (6) `kg-packs set-as-of --date 2026-10-09`<br>(7) `kg-packs run-metrics --from 2025-08-01 --to 2026-10-10`, tính các metric **không** phải file<br>(8) **tải `store_targets` LẦN 2** (replace)<br>(9) chờ tới khi mọi `data_status` có chữ `target` là `current` và `period_to` của `metric:*target*` ≥ 2026-10-01 |
| 3 | Sau phần 2 | `scripts/demo_data/cutover.sh part3 demo_mockdata_shifted_70` | (10) LAAM `business_project.asOfOverride='2026-10-09'` cho `bp-pharmacy-chain-demo`, và đặt `analysis_job.nextRunAt` về quá khứ<br>(11) chờ một lần chạy `succeeded` mới<br>(12) `check-expected-findings --findings-json` **chỉ trên lần chạy đó** |

**Vì sao phải tải chỉ tiêu hai lần:**
- `kg-packs run-metrics` chạy bằng `docker exec daab-server go run ./cmd/kg-packs …` **không có bộ đọc nguồn cho mode=file**. Với entity `target` (dataset `store_targets`), nó báo lỗi `no source resolver for mode "file"`.
- Vì vậy `retail.target_net_sales`, `retail.target_gross_margin_pct` và `entity:target` vẫn ở trạng thái `delayed`, kỳ cũ là tháng 7.
- Chỉ lần tính metric **bên trong server**, được kích hoạt khi tải dataset lên, mới có bộ đọc file. Lần tải đó phải diễn ra **sau** `set-as-of`, thì metric chỉ tiêu mới được tính cho tháng của as-of mới.

**Triệu chứng nếu quên lần tải thứ 2:**
- LAAM Home hiện 3 cảnh báo "… đang về trễ hơn thường lệ" (entity `target` và 2 metric chỉ tiêu).
- RET-SALES-001 không bắn cho PH-004, nên thiếu FND-008 và check-expected-findings chỉ đạt 8/9.
- Cách sửa: tải `store_targets` lại, chờ các metric chỉ tiêu `current`, rồi chạy lại phân tích LAAM.

**LAAM.** Phần 3 không dùng `psql` vào DB của LAAM. Nó chạy `docker exec -i -w /app laam-v2-app node …` với `DATABASE_URL` có sẵn trong container của app; script không bao giờ đọc hay in giá trị này. Có thể thay bước (10) bằng giao diện: trang quản trị dự án → ngày dữ liệu → **Chạy ngay**.

**Các câu kiểm tra** (đều chỉ đọc):

```bash
P=4ad7a5fa-a036-4f6a-8229-39a20af23e38
# sau phần 1
docker exec -i daab-postgres psql -U "$U" -d pharmacy_demo -X -v shift_days=70 -f - < scripts/demo_data/verify_plants.sql
docker exec daab-postgres psql -U "$U" -d ennam_kg -At -c "select row_count from file_dataset where project_id='$P' and name='store_targets'"   # 150
# sau phần 2
docker exec daab-postgres psql -U "$U" -d ennam_kg -At -c "select count(*) from data_status where project_id='$P' and status <> 'current'"      # 0
docker exec daab-postgres psql -U "$U" -d ennam_kg -At -c "select subject, status, period_to from data_status where project_id='$P' and subject like '%target%' order by 1"
#   kỳ vọng: current, metric:retail.target_* period_to = 2026-10-31
```

Kết quả `verify_plants.sql` phải như sau:

| Kiểm tra | Kỳ vọng |
|---|---|
| `window` | 2025-10-10 → 2026-10-09 |
| Tỉ lệ từ chối claim | PH-004 15.9%, các store khác 4.6–5.8% |
| `rx_margin_pct` PH-003 | 17.7 / 20.0 |
| `sarah_refunds_jul` | 60 |
| `movement_types` | RECEIPT 2571 / REFUND_RETURN 688 / SALE 93435 |

Cutover 2026-10-09 đạt kết quả:
- 48/48 dòng `data_status` ở trạng thái `current`.
- Metric chỉ tiêu có `period_to` = 2026-10-31.
- check-expected-findings **PASS 9/9** trên lần chạy mới nhất.

⚠️ **Kiểm tra phát hiện chỉ trên lần chạy mới nhất** (phần 3 tự làm việc này):
- Phát hiện được gộp theo `luật + dims`, không theo ngày (`LAAM/src/lib/intel/engine/dedupe.ts`). Các dòng tạo từ thời as-of 07-31 vẫn còn, nên đọc cả bảng `finding` sẽ PASS kể cả khi dữ liệu mới không phát hiện gì.
- Mỗi lần ghi đều đặt `lastRunId` (`store/repo.ts`). Phần 3 xuất `{ruleId, dims, severity}` của các dòng `"lastRunId" = <lần chạy mới nhất>` rồi chạy `node scripts/check-expected-findings.ts --findings-json <file>`. Kỳ vọng: PASS 9/9.
- Các phát hiện cũ mà lần chạy mới không tạo lại vẫn nằm trên Home với trạng thái cũ. Nếu muốn dọn, xem danh sách (`"lastRunId" <> <lần chạy mới>` và chưa resolved/dismissed) rồi mới quyết định.

## 5. Seed LAAM: KHÔNG chạy lại trước khi sửa (repo LAAM, người điều phối sửa)

`LAAM/scripts/seed-intel-demo.ts` ghi `asOfOverride = DEMO_AS_OF` ("2026-07-31") cho **cả** `bp-pharmacy-chain-demo` lẫn `bp-demo-synthetic` (dòng 63). Chạy lại seed sẽ đưa as-of về 07-31.

Đừng đổi `DEMO_AS_OF` chung, vì fixture tổng hợp có các ngày cài cứng. Chỉ sửa một dòng:

```ts
// LAAM/scripts/seed-intel-demo.ts:63
    timezone: TIME_ZONE, localeDefault: "en", asOfOverride: id === BP_SYNTHETIC_ID ? DEMO_AS_OF : "2026-10-09", updatedAt: new Date(),
```

Kèm sửa comment dòng 36 thành `--date 2026-10-09`.

Chỉ khi muốn dự án tổng hợp cũng "trẻ" lại, mới cần sửa thêm:
- Đổi `DEMO_AS_OF` thành "2026-10-09".
- Trong `intel-demo-fixture.ts:37-38`, đổi `"2026-07-18"` thành `"2026-09-26"`, và cộng 70 ngày cho các `from` khác (05-01 → 07-10, 07-01 → 09-09).
- Cập nhật `intel-demo-fixture.test.ts`.

## 6. Mô tả kỳ vọng và Home

Nên sửa phần mô tả trong `demo_mockdata/expected_findings.csv` (trình kiểm tra không đọc phần này):
- FND-009: "From 2026-07-18" → "From 2026-09-26".
- FND-008: "net sales in July 2026 are roughly 40% below June 2026" → "month-to-date net sales in October 2026 are about 43% below target".

Trên **LAAM Home** (`bp-pharmacy-chain-demo`):
- Dòng trạng thái: "Data through Oct 9, 2026".
- Không còn câu "Dữ liệu cũ hơn … ngày" (đúng cho các lần chạy tới hết 2026-10-16).
- Không còn cảnh báo "về trễ".
- 9 phát hiện: hoàn tiền của Sarah Miller (EMP-0006), hao hụt PH-005, hoàn tiền trùng, override PH-002 (EMP-0023), từ chối claim PH-004, thiếu két PH-005 (EMP-0102), in lại hoá đơn trước hoàn tiền, PH-004 dưới chỉ tiêu (critical), biên Rx PH-003 giảm từ 2026-09-26.

## 7. Làm mới trước một ngày demo khác

```bash
scripts/demo_data/refresh_demo.sh <ngày-demo hoặc hôm trước>      # không phá gì: tạo gói + in các bước theo thứ tự
REFRESH_REPLACE=yes CONFIRM_LIVE_RELOAD=yes DAAB_API_KEY=… scripts/demo_data/refresh_demo.sh <ngày> <bản sao lưu>.dump   # chạy luôn phần 1
scripts/demo_data/cutover.sh part2 demo_mockdata_shifted_<N>      # từ 00:00 Chicago của ngày as-of
scripts/demo_data/cutover.sh part3 demo_mockdata_shifted_<N>
```

- Script lấy N = bội số 7 lớn nhất sao cho 2026-07-31 + N ≤ ngày đó, và luôn dời từ **gói gốc**.
- Chọn ngày demo hoặc ngày trước đó, để độ trễ ≤ 7.

## 8. Hoàn tác

Thứ tự giống cutover: as-of trước, rồi tải chỉ tiêu **sau** `run-metrics`.

```bash
docker exec daab-postgres pg_dump -U "$U" -Fc pharmacy_demo > $B/pharmacy_demo_shifted_$TS.dump
DAAB_PG_CONTAINER=daab-postgres CONFIRM_LIVE_RELOAD=yes scripts/demo_data/load_pharmacy_demo.sh $B/pharmacy_demo_shifted_$TS.dump   # nạp lại CSV gốc
scripts/demo_data/resync_daab_schema.sh
docker exec -w /app daab-server go run ./cmd/kg-packs set-as-of --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --date 2026-07-31
docker exec -w /app daab-server go run ./cmd/kg-packs run-metrics --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --from 2025-08-01 --to 2026-10-10
curl -fsS -X POST -H "Authorization: Bearer $DAAB_API_KEY" -F ingest_mode=tabular -F dataset_name=store_targets -F write_mode=replace \
  -F file=@demo_mockdata/targets.xlsx http://localhost:8082/api/v1/projects/4ad7a5fa-a036-4f6a-8229-39a20af23e38/ingest/upload
# LAAM: asOfOverride='2026-07-31' cho bp-pharmacy-chain-demo (giao diện quản trị, hoặc docker exec laam-v2-app node như cutover.sh part3), rồi Chạy ngay
```

- `--to 2026-10-10` xoá luôn các metric của 2026-08-01..2026-10-09.
- Nếu cần khôi phục đúng nguyên trạng DB: `pg_restore` bản `pharmacy_demo_precutover_*.dump` vào một `pharmacy_demo` vừa tạo lại, và `ennam_kg_intel_precutover_*.dump` (cẩn thận: chỉ có 4 bảng intel).

## Ghi chú

**Dòng có ngày sau as-of (2026-10-09).** Các dòng này vốn đã nằm sau as-of trong gói gốc, tới tối đa 2026-08-25. Luật lọc theo `< as_of + 1`, và độ trễ âm vẫn tính là "current", nên không ảnh hưởng:

| Bảng.cột | Số dòng | Ngày muộn nhất |
|---|---|---|
| refunds | 27 | 2026-11-03 |
| receipts | 30 | |
| inventory_movements | 38 | |
| audit_events | 25 | |
| invoices.issued | 6 | |
| invoices.paid | 39 | |
| invoices.due | 97 | |
| prescriptions.picked_up | 111 | |
| insurance_claims.resolved | 1 | |

**Cột không dời và lý do:**
- `invoices.invoice_number` (`2026-NNNNNN`): mọi ngày phát hành sau khi dời vẫn ở năm 2026.
- `days_after_purchase`, `turnaround_minutes`, `lead_time_days`: là khoảng thời gian, không đổi.
- `order_weekday`: 70 chia hết cho 7.

**Các luật cửa sổ trượt giữ nguyên kết quả.** 31 metric dữ liệu của DAAB đều theo ngày và không dùng hàm lịch (date_trunc, tháng, thứ). Các cửa sổ của LAAM (`windowEnding`, `shiftWindow`, nền cùng thứ 4 tuần) đều tính tương đối theo as-of. Dữ liệu dời +70 trùng md5 với gốc, và as-of cũng dời +70, nên các luật này cho đúng giá trị như trước.

Chỉ có hai metric theo tháng (chỉ tiêu) là phụ thuộc lịch; chúng được xử lý ở mục 1.

Múi giờ cũng không ảnh hưởng: DAAB chỉ đổi giờ địa phương (`AT TIME ZONE`) cho cột **có** múi giờ (`ennam.kg.go/internal/intel/compile.go`). Các cột của `pharmacy_demo` là `timestamp without time zone`, nên được đọc nguyên, kể cả quanh các ngày đổi giờ mùa hè.

**Home hiển thị chỉ tiêu.** Mục dự báo trên Home so (doanh số từ đầu tháng + dự báo các ngày còn lại) với chỉ tiêu tháng (`home/derive.ts`, `targetView`). PH-004 sẽ hiện chỉ tiêu 101 100 và "thấp hơn chỉ tiêu" khoảng 40%, khớp với câu chuyện FND-008. Các cửa hàng khác sẽ quanh mức đạt chỉ tiêu.
