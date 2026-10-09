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
> Chỉ dùng container `daab-postgres` (cổng 5433). Không đụng cổng 5432. DB LAAM (5500) chỉ dùng ở bước 8–10.

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
# → demo_mockdata_shifted_70/ (25 CSV + targets.xlsx + SHIFT_MANIFEST.json) + in ra các lệnh cutover
```

- Lệnh từ chối nếu ngày 2026-10-09 vẫn là "ngày mai" ở Chicago. Nếu cần, có thể chạy tay:

  ```bash
  cd scripts/demo_data
  uv run pytest -q   # kỳ vọng: 112 passed
  uv run python shift_dates.py --days 70 --output ../../demo_mockdata_shifted_70
  uv run python retarget_demo.py --data ../../demo_mockdata_shifted_70
  cd ../..
  ```

- `demo_mockdata/` gốc giữ nguyên. Thư mục `demo_mockdata_shifted_70/` không được commit.

## 3. Sao lưu (bắt buộc)

```bash
TS=$(date +%Y%m%dT%H%M%S); mkdir -p ~/backups/demo-shift
U=$(docker exec daab-postgres printenv POSTGRES_USER)
docker exec daab-postgres pg_dump -U "$U" -Fc pharmacy_demo > ~/backups/demo-shift/pharmacy_demo_$TS.dump
docker exec daab-postgres pg_dump -U "$U" -Fc -t metric_value -t project_intel_settings -t file_dataset -t file_dataset_row ennam_kg \
  > ~/backups/demo-shift/ennam_kg_intel_$TS.dump
docker exec -i daab-postgres pg_restore --list < ~/backups/demo-shift/pharmacy_demo_$TS.dump | grep -c "TABLE DATA public"   # 25
LU=$(docker exec laam-postgres printenv POSTGRES_USER)
docker exec laam-postgres psql -U "$LU" -d laam -c \
  "select id, \"metricsProvider\", \"daabProjectId\", \"asOfOverride\" from business_project order by id" \
  | tee ~/backups/demo-shift/laam_business_project_$TS.txt
```

## 4. Nạp dữ liệu mới vào `pharmacy_demo`

```bash
DEMO_DATA_DIR=demo_mockdata_shifted_70 DAAB_PG_CONTAINER=daab-postgres CONFIRM_LIVE_RELOAD=yes \
  scripts/demo_data/load_pharmacy_demo.sh ~/backups/demo-shift/pharmacy_demo_$TS.dump      # 25 dòng "ok"
docker exec -i daab-postgres psql -U "$U" -d pharmacy_demo -X -v shift_days=70 -f - < scripts/demo_data/verify_plants.sql
```

Kết quả `verify_plants.sql` phải như sau:

| Kiểm tra | Kỳ vọng |
|---|---|
| `window` | 2025-10-10 → 2026-10-09 |
| Tỉ lệ từ chối claim | PH-004 15.9%, các store khác 4.6–5.8% |
| `rx_margin_pct` PH-003 | 17.7 / 20.0 |
| `sarah_refunds_jul` | 60 |
| `movement_types` | RECEIPT 2571 / REFUND_RETURN 688 / SALE 93435 |

⚠️ Phải có `DEMO_DATA_DIR`. Thiếu biến này thì script nạp lại cửa sổ **cũ**.

## 5. Đồng bộ schema DAAB

```bash
DAAB_API_KEY=<khoá developer> scripts/demo_data/resync_daab_schema.sh   # source_tables=25 architecture_nodes=25/25
```

## 6. DAAB: as-of → chỉ tiêu → metric (đúng thứ tự)

```bash
# 6a. as-of TRƯỚC (chỉ sau 00:00 giờ Chicago ngày 2026-10-09)
docker exec -w /app daab-server go run ./cmd/kg-packs set-as-of --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --date 2026-10-09
# 6b. thay dataset chỉ tiêu (write_mode=replace thay toàn bộ 170 dòng cũ bằng 150 dòng mới)
curl -fsS -X POST -H "Authorization: Bearer $DAAB_API_KEY" -F ingest_mode=tabular -F dataset_name=store_targets \
  -F write_mode=replace -F file=@demo_mockdata_shifted_70/targets.xlsx \
  http://localhost:8082/api/v1/projects/4ad7a5fa-a036-4f6a-8229-39a20af23e38/ingest/upload
#     (hoặc giao diện Knowledge Sources → "Dữ liệu bảng", dataset store_targets, chế độ thay thế)
# 6c. tính lại toàn bộ metric
docker exec -w /app daab-server go run ./cmd/kg-packs run-metrics --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --from 2025-08-01 --to 2026-10-10
```

- `--from 2025-08-01` là ngày đầu của dữ liệu **gốc**. Bộ lưu xoá rồi ghi lại theo cửa sổ, nên bắt đầu từ đó thì xoá hết metric cũ của 2025-08-01..2025-10-09.
- Việc tải chỉ tiêu tự kích hoạt một lần tính metric. `run-metrics` vẫn phải chạy để tính lại toàn bộ lịch sử.
- Không cần khởi động lại `daab-server`.

Kiểm tra:

```bash
docker exec daab-postgres psql -U "$U" -d ennam_kg -c "select metric_key, min(period_date), max(period_date) from metric_value where project_id='4ad7a5fa-a036-4f6a-8229-39a20af23e38' group by 1 order by 1"
```

Kỳ vọng:
- Metric ngày nằm trong 2025-10-10..2026-10-09.
- `retail.target_net_sales` có kỳ 2026-10-01.

## 7. Seed LAAM: KHÔNG chạy lại trước khi sửa (repo LAAM, người điều phối sửa)

`LAAM/scripts/seed-intel-demo.ts` ghi `asOfOverride = DEMO_AS_OF` ("2026-07-31") cho **cả** `bp-pharmacy-chain-demo` lẫn `bp-demo-synthetic` (dòng 63). Chạy lại seed sẽ đưa as-of về 07-31.

Dự án tổng hợp dùng `LAAM/scripts/intel-demo-fixture.ts`, trong đó có nhiều ngày cài cứng (05-01, 07-01, 07-18). Vì vậy **đừng** đổi `DEMO_AS_OF` chung. Chỉ sửa một dòng:

```ts
// LAAM/scripts/seed-intel-demo.ts:63
    timezone: TIME_ZONE, localeDefault: "en", asOfOverride: id === BP_SYNTHETIC_ID ? DEMO_AS_OF : "2026-10-09", updatedAt: new Date(),
```

Kèm sửa comment dòng 36 thành `--date 2026-10-09`.

Chỉ khi muốn dự án tổng hợp cũng "trẻ" lại, mới cần sửa thêm:
- Đổi `DEMO_AS_OF` thành "2026-10-09".
- Trong `intel-demo-fixture.ts:37-38`, đổi `from: "2026-07-18"` thành `"2026-09-26"` và cộng 70 ngày cho các `from` khác (05-01 → 07-10, 07-01 → 09-09).
- Cập nhật `intel-demo-fixture.test.ts`.

## 8. LAAM: đặt as-of cho dự án demo

```bash
docker exec laam-postgres psql -U "$LU" -d laam -c "select id, \"metricsProvider\", \"daabProjectId\", \"asOfOverride\" from business_project where id in ('bp-pharmacy-chain-demo','bp-demo-retail-mart','bp-demo-synthetic')"
docker exec laam-postgres psql -U "$LU" -d laam -c "update business_project set \"asOfOverride\"='2026-10-09', \"updatedAt\"=now() where id='bp-pharmacy-chain-demo'"
```

`bp-demo-retail-mart`: chỉ đổi khi `metricsProvider='daab'` và `daabProjectId='4ad7a5fa-…'`. Nếu dùng fixture giả thì để nguyên, xem mục 7.

## 9. Chạy lại phân tích LAAM

Cách 1: trang quản trị dự án → **Kiểm tra hằng ngày** → **Chạy ngay**.

Cách 2:

```bash
docker exec laam-postgres psql -U "$LU" -d laam -c "update analysis_job set \"nextRunAt\"=now() - interval '1 minute' where \"businessProjectId\"='bp-pharmacy-chain-demo' and kind='daily'"
```

## 10. Kiểm tra

```bash
node --env-file=LAAM/.env scripts/check-expected-findings.ts      # kỳ vọng: PASS 9/9
```

Nên sửa phần mô tả trong `demo_mockdata/expected_findings.csv` (trình kiểm tra không đọc phần này):
- FND-009: "From 2026-07-18" → "From 2026-09-26".
- FND-008: "net sales in July 2026 are roughly 40% below June 2026" → "month-to-date net sales in October 2026 are about 43% below target".

Trên **LAAM Home** (`bp-pharmacy-chain-demo`):
- Dòng trạng thái: "Data through Oct 9, 2026".
- **Không** còn câu "Dữ liệu cũ hơn … ngày" (đúng cho các lần chạy tới hết 2026-10-16).
- 9 phát hiện: hoàn tiền của Sarah Miller (EMP-0006), hao hụt PH-005, hoàn tiền trùng, override PH-002 (EMP-0023), từ chối claim PH-004, thiếu két PH-005 (EMP-0102), in lại hoá đơn trước hoàn tiền, PH-004 dưới chỉ tiêu (critical), biên Rx PH-003 giảm từ 2026-09-26.

## 11. Làm mới trước một ngày demo khác

```bash
scripts/demo_data/refresh_demo.sh <ngày-demo hoặc hôm trước>            # không phá gì, in ra lệnh
REFRESH_REPLACE=yes CONFIRM_LIVE_RELOAD=yes scripts/demo_data/refresh_demo.sh <ngày> ~/backups/demo-shift/<bản sao lưu>.dump
```

- Script lấy N = bội số 7 lớn nhất sao cho 2026-07-31 + N ≤ ngày đó. Script luôn dời từ **gói gốc**, không dời chồng.
- Chạy với `CONFIRM_LIVE_RELOAD=yes` + bản sao lưu thì script chỉ nạp lại `pharmacy_demo` và chạy `verify_plants`. Các bước 5–10 vẫn phải làm tay theo lệnh nó in ra.
- Chọn ngày demo hoặc ngày trước đó, để độ trễ ≤ 7.

## 12. Hoàn tác

```bash
docker exec daab-postgres pg_dump -U "$U" -Fc pharmacy_demo > ~/backups/demo-shift/pharmacy_demo_shifted_$TS.dump
DAAB_PG_CONTAINER=daab-postgres CONFIRM_LIVE_RELOAD=yes scripts/demo_data/load_pharmacy_demo.sh ~/backups/demo-shift/pharmacy_demo_shifted_$TS.dump   # nạp lại CSV gốc
DAAB_API_KEY=<khoá> scripts/demo_data/resync_daab_schema.sh
docker exec -w /app daab-server go run ./cmd/kg-packs set-as-of --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --date 2026-07-31
curl -fsS -X POST -H "Authorization: Bearer $DAAB_API_KEY" -F ingest_mode=tabular -F dataset_name=store_targets -F write_mode=replace \
  -F file=@demo_mockdata/targets.xlsx http://localhost:8082/api/v1/projects/4ad7a5fa-a036-4f6a-8229-39a20af23e38/ingest/upload
docker exec -w /app daab-server go run ./cmd/kg-packs run-metrics --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --from 2025-08-01 --to 2026-10-10
docker exec laam-postgres psql -U "$LU" -d laam -c "update business_project set \"asOfOverride\"='2026-07-31', \"updatedAt\"=now() where id='bp-pharmacy-chain-demo'"
```

Khi hoàn tác, `--to 2026-10-10` xoá luôn các metric của 2026-08-01..2026-10-09.

Nếu cần khôi phục đúng nguyên trạng DB: `pg_restore` bản `pharmacy_demo_$TS.dump` vào một `pharmacy_demo` vừa tạo lại, và `ennam_kg_intel_$TS.dump` (cẩn thận: chỉ 4 bảng intel).

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
