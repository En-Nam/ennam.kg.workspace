# Runbook: dời ngày dữ liệu demo nhà thuốc lên 63 ngày (2026-07-31 → 2026-10-02)

Mục đích: LAAM Home đang báo "Dữ liệu cũ hơn bản phân tích này 68 ngày" vì dữ liệu demo kết thúc ngày 2026-07-31. Ta dời **mọi** cột ngày/giờ của 25 bảng thêm 63 ngày (đúng 9 tuần). Thứ trong tuần, giờ trong ngày, tỉ lệ và mọi mẫu dữ liệu cài sẵn đều giữ nguyên. Cửa sổ mới là **2025-10-03 → 2026-10-02**.

Đã kiểm tra trên DB tạm `pharmacy_demo_shift_check` (đã xoá sau khi kiểm tra), ngày 2026-10-08:
- 25/25 bảng khớp số dòng.
- So từng bảng với dữ liệu gốc sau khi trừ lại 63 ngày: trùng khớp 100% (md5).
- `verify_plants.sql -v shift_days=63` cho kết quả y hệt bản gốc, chỉ khác dòng `window`.
- Ngày lớn nhất của các bảng sự kiện chính là 2026-10-02.

DB thật `pharmacy_demo` **chưa** bị đụng tới.

> Lệnh chạy từ thư mục gốc workspace: `cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace`.
> Chỉ dùng container `daab-postgres` (cổng 5433). Không đụng cổng 5432. DB của LAAM (cổng 5500) chỉ dùng ở bước 7 và 9.

## 0. Quyết định trước khi làm (bắt buộc đọc)

1. **Phát hiện FND-008 (RET-SALES-001, PH-004 doanh số giảm) sẽ KHÔNG còn**, và sẽ có thêm **một cảnh báo critical lạ ở PH-005**, nếu chỉ dời +63 và giữ nguyên `targets.xlsx`.
   - Luật này so doanh số **từ đầu tháng tới ngày as-of** với chỉ tiêu tháng (chia theo số ngày).
   - As-of 2026-10-02 thì "từ đầu tháng" chỉ có 2 ngày (1–2/10, tức 30–31/7 của dữ liệu gốc), so với chỉ tiêu tháng 10/2026.
   - Ước tính (cùng công thức với metric `retail.net_sales`):

     | Store | Tỉ lệ so với chỉ tiêu | Kết quả |
     |---|---|---|
     | PH-004 | 1.08 | không bắn |
     | PH-005 | 0.72 | critical, ngoài kỳ vọng |
     | PH-001 | 0.89 | high |

   - Khi đó `check-expected-findings` sẽ **FAIL** (thiếu FND-008, thừa critical RET-SALES-001 ở PH-005).
   - Các luật dùng cửa sổ trượt (PH-CLAIM-001, PH-MARGIN-001, RET-MARGIN-002, RET-INV-010, RET-REF-*, RET-CASH-*, RET-VENDOR-001, RET-X-REPRINT-001, RET-DISC-003…) **không bị ảnh hưởng**.
2. **Cảnh báo "dữ liệu cũ" quay lại sau 7 ngày.** LAAM chỉ báo khi `ngày chạy − as_of > 7`. Với as-of 2026-10-02, các lần chạy **từ 2026-10-10** sẽ lại báo "8 ngày". Muốn Home "sạch" trong buổi demo thì phải chạy phân tích trước ngày 10/10, hoặc dời thêm 7·k ngày gần ngày demo hơn.
3. Các phương án (người điều phối chọn):
   - **(a) +63 như kế hoạch**, chấp nhận mất FND-008. Khi đó phải sửa kỳ vọng (bỏ hoặc tạm loại FND-008) và chấp nhận critical PH-005; hoặc tạo lại targets cho đúng tháng mới (vẫn chỉ có 2 ngày dữ liệu, rất nhiễu).
   - **(b) +56 ngày** (`--days 56`, as-of **2026-09-25**). Giữ được FND-008 mà không cần sửa `targets.xlsx`:
     - PH-004 tỉ lệ 0.66 → critical.
     - Các store khác 1.04–1.18 → không bắn.
     - Dữ liệu cũ 13 ngày vào ngày 8/10, nên cảnh báo "cũ" vẫn hiện.
   - **(c) +63, dời as-of về 2026-09-30.** PH-004 vẫn critical (0.64). Nhưng các luật cửa sổ trượt mất 2 ngày cuối của dữ liệu cài sẵn (biên margin PH-003 chỉ còn 12/14 ngày), nên **không khuyến nghị**.

   Phần còn lại của runbook viết cho +63 / 2026-10-02. Nếu chọn (b), thay `63` bằng `56` và `2026-10-02` bằng `2026-09-25`, `2026-10-03` bằng `2026-09-26`.

## 1. Tạo bộ CSV đã dời ngày

```bash
cd scripts/demo_data
uv run pytest -q                                  # kỳ vọng: 96 passed
uv run python shift_dates.py --dry-run | tail -3  # chỉ báo cáo, không ghi
rm -rf ../../demo_mockdata_shifted                # công cụ từ chối ghi vào thư mục không rỗng
uv run python shift_dates.py                      # ghi ../../demo_mockdata_shifted/ + SHIFT_MANIFEST.json
cd ../..
```

- `demo_mockdata/` giữ nguyên (đó là đầu ra của bộ sinh dữ liệu). `demo_mockdata_shifted/` không commit (47 MB).
- Công cụ từ chối dời hai lần: nếu thư mục vào đã có `SHIFT_MANIFEST.json` thì nó không chạy.

## 2. Sao lưu (bắt buộc)

```bash
TS=$(date +%Y%m%dT%H%M%S)
U=$(docker exec daab-postgres printenv POSTGRES_USER)
mkdir -p ~/backups/demo-shift
docker exec daab-postgres pg_dump -U "$U" -Fc pharmacy_demo > ~/backups/demo-shift/pharmacy_demo_$TS.dump
docker exec daab-postgres pg_dump -U "$U" -Fc -t metric_value -t project_intel_settings ennam_kg > ~/backups/demo-shift/ennam_kg_intel_$TS.dump
docker exec -i daab-postgres pg_restore --list < ~/backups/demo-shift/pharmacy_demo_$TS.dump | grep -c "TABLE DATA public"   # kỳ vọng 25
```

LAAM: ghi lại giá trị hiện tại để có thể hoàn tác (cổng 5500, chỉ đọc):

```bash
LU=$(docker exec laam-postgres printenv POSTGRES_USER)
docker exec laam-postgres psql -U "$LU" -d laam -c \
  "select id, \"metricsProvider\", \"daabProjectId\", \"asOfOverride\" from business_project order by id" \
  | tee ~/backups/demo-shift/laam_business_project_$TS.txt
```

## 3. Nạp dữ liệu mới vào `pharmacy_demo`

```bash
DEMO_DATA_DIR=demo_mockdata_shifted DAAB_PG_CONTAINER=daab-postgres CONFIRM_LIVE_RELOAD=yes \
  scripts/demo_data/load_pharmacy_demo.sh ~/backups/demo-shift/pharmacy_demo_$TS.dump
# kỳ vọng: 25 dòng "ok <bảng> <số dòng>", không có MISMATCH
docker exec -i daab-postgres psql -U "$U" -d pharmacy_demo -X -v shift_days=63 -f - < scripts/demo_data/verify_plants.sql
```

Kết quả `verify_plants.sql` phải như sau:

| Kiểm tra | Kỳ vọng |
|---|---|
| `window` | 2025-10-03 → 2026-10-02 |
| Tỉ lệ từ chối claim | PH-004 15.9%, các store khác 4.6–5.8% |
| `rx_margin_pct` PH-003 | last_14d 17.7 / prior 20.0 |
| `sarah_refunds_jul` | 60 |
| `movement_types` | RECEIPT 2571 / REFUND_RETURN 688 / SALE 93435 |

⚠️ Phải có `DEMO_DATA_DIR=demo_mockdata_shifted`. Thiếu biến này thì script nạp lại cửa sổ **cũ**.

## 4. Đồng bộ lại schema DAAB

```bash
DAAB_API_KEY=<khoá developer> scripts/demo_data/resync_daab_schema.sh
# kỳ vọng: source_tables=25 architecture_nodes(total/distinct)=25/25
```

## 5. Đặt as-of DAAB, rồi tính lại metric

Đặt as-of **trước** khi tính metric. `set-as-of` từ chối ngày ở tương lai.

```bash
docker exec -w /app daab-server go run ./cmd/kg-packs set-as-of --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --date 2026-10-02
docker exec -w /app daab-server go run ./cmd/kg-packs run-metrics --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --from 2025-08-01 --to 2026-10-03
```

- `--from 2025-08-01` là ngày **đầu cũ**. Bộ lưu xoá rồi ghi lại theo cửa sổ, nên đi từ ngày đầu cũ thì xoá được các dòng metric cũ của 2025-08-01..2025-10-02.
- Không cần khởi động lại `daab-server` vì danh mục pack không đổi.
- Nếu chọn sửa `targets.xlsx` (phương án a): tải lại dataset `store_targets` qua tab "Dữ liệu bảng" **trước** lệnh `run-metrics`.

Kiểm tra (chỉ đọc):

```bash
docker exec daab-postgres psql -U "$U" -d ennam_kg -c "select metric_key, min(period_date), max(period_date) from metric_value where project_id='4ad7a5fa-a036-4f6a-8229-39a20af23e38' group by 1 order by 1"
```

Kỳ vọng: metric theo ngày nằm trong 2025-10-03..2026-10-02. Không còn dòng nào trước 2025-10-03, trừ metric theo tháng (bắt đầu từ ngày 1 của tháng).

## 6. (Nếu cần) cập nhật seed LAAM

`LAAM/scripts/seed-intel-demo.ts` đang đặt cứng `DEMO_AS_OF = "2026-07-31"`. Nếu chạy lại seed, nó **ghi đè** as-of về 2026-07-31.
- Đổi thành `"2026-10-02"` trong repo LAAM.
- Đổi kèm `LAAM/scripts/intel-demo-fixture.ts:37-38` từ `"2026-07-18"` thành `"2026-09-19"`, kèm test của file đó.
- Xem `.superpowers/sdd/2026-10-08-demo-date-shift/stale-references.md`.

## 7. Cập nhật as-of LAAM cho các dự án demo

Kiểm tra trước, chỉ đổi dự án nào thật sự đọc DAAB project `4ad7a5fa-…`:

```bash
docker exec laam-postgres psql -U "$LU" -d laam -c "select id, \"metricsProvider\", \"daabProjectId\", \"asOfOverride\" from business_project where id in ('bp-pharmacy-chain-demo','bp-demo-retail-mart','bp-demo-synthetic')"
docker exec laam-postgres psql -U "$LU" -d laam -c "update business_project set \"asOfOverride\"='2026-10-02', \"updatedAt\"=now() where id in ('bp-pharmacy-chain-demo' /*, 'bp-demo-retail-mart' nếu daabProjectId = 4ad7a5fa-… */)"
```

- `bp-demo-retail-mart` (Mini Mart) và `bp-demo-synthetic` là dự án tổng hợp. Nếu chúng dùng fixture giả thì đặt as-of 2026-10-02 sẽ làm mẫu cài sẵn của fixture nằm ngoài cửa sổ. Khi đó chỉ đổi cùng lúc với bước 6.
- Có thể đổi bằng giao diện quản trị dự án (trường ngày dữ liệu) thay cho SQL.

## 8. Chạy lại phân tích LAAM

Cách 1: giao diện quản trị dự án → **Kiểm tra hằng ngày** → **Chạy ngay** (1–2 phút).

Cách 2: đưa `nextRunAt` về quá khứ, tick sẽ nhận trong khoảng 1 phút:

```bash
docker exec laam-postgres psql -U "$LU" -d laam -c "update analysis_job set \"nextRunAt\"=now() - interval '1 minute' where \"businessProjectId\"='bp-pharmacy-chain-demo' and kind='daily'"
```

## 9. Kiểm tra kết quả

```bash
node --env-file=LAAM/.env scripts/check-expected-findings.ts
```

- Phương án (b): kỳ vọng `PASS 9/9`.
- Phương án (a) với `targets.xlsx` nguyên: kỳ vọng `FAIL 8/9`, gồm `MISS FND-008` và `UNEXPECTED CRITICAL RET-SALES-001 PH-005`. Phải sửa `demo_mockdata/expected_findings.csv` (bỏ hoặc tạm loại FND-008) hoặc tạo lại targets.

Dù chọn phương án nào, nên sửa phần mô tả trong `expected_findings.csv`:
- FND-009: "From 2026-07-18" → "From 2026-09-19".
- FND-008: "July 2026 … June 2026" → mô tả theo cửa sổ mới.

Trình kiểm tra không đọc phần mô tả này, nhưng người xem demo sẽ đọc.

Trên **LAAM Home** (`bp-pharmacy-chain-demo`):
- Dòng trạng thái ghi "Data through Oct 2, 2026".
- **Không** còn câu "Dữ liệu cũ hơn bản phân tích này … ngày" (đúng nếu chạy trước 2026-10-10).
- Các phát hiện: Sarah Miller (EMP-0006) hoàn tiền, PH-005 hao hụt kho, hoàn tiền trùng, override PH-002 (EMP-0023), từ chối claim PH-004, thiếu két PH-005 (EMP-0102), in lại hoá đơn trước hoàn tiền, biên Rx PH-003 giảm từ 2026-09-19, và (tuỳ phương án) PH-004 doanh số giảm.

## 10. Hoàn tác

```bash
# pharmacy_demo về bản cũ (nạp lại từ CSV gốc; bản sao lưu của chính DB hiện tại được dùng làm "giấy phép")
docker exec daab-postgres pg_dump -U "$U" -Fc pharmacy_demo > ~/backups/demo-shift/pharmacy_demo_shifted_$TS.dump
DAAB_PG_CONTAINER=daab-postgres CONFIRM_LIVE_RELOAD=yes scripts/demo_data/load_pharmacy_demo.sh ~/backups/demo-shift/pharmacy_demo_shifted_$TS.dump
# hoặc khôi phục đúng bản sao lưu: docker exec daab-postgres psql -U "$U" -d postgres -c "DROP DATABASE pharmacy_demo WITH (FORCE)" -c "CREATE DATABASE pharmacy_demo"
#   docker exec -i daab-postgres pg_restore -U "$U" -d pharmacy_demo --no-owner < ~/backups/demo-shift/pharmacy_demo_$TS.dump
scripts/demo_data/resync_daab_schema.sh
docker exec -w /app daab-server go run ./cmd/kg-packs set-as-of --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --date 2026-07-31
docker exec -w /app daab-server go run ./cmd/kg-packs run-metrics --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --from 2025-08-01 --to 2026-10-03
docker exec laam-postgres psql -U "$LU" -d laam -c "update business_project set \"asOfOverride\"='2026-07-31', \"updatedAt\"=now() where id in ('bp-pharmacy-chain-demo')"
```

Khi hoàn tác, `run-metrics` dùng `--to 2026-10-03` để xoá luôn các metric của khoảng 2026-08-01..2026-10-02.

## Ghi chú về dữ liệu

Một số dòng nằm **sau ngày hôm nay** (2026-10-08). Chúng vốn đã nằm sau as-of trong gói gốc (hoàn tiền / in lại hoá đơn tới 2026-08-25):

| Bảng.cột | Số dòng sau 2026-10-08 | Ngày muộn nhất |
|---|---|---|
| refunds.refund_datetime | 15 | 2026-10-27 |
| receipts.printed_datetime | 17 | |
| inventory_movements.movement_datetime | 22 | |
| audit_events.event_datetime | 15 | |
| invoices.paid_date | 22 | |
| invoices.due_date | 72 | |

Các luật đều lọc theo `< as_of + 1`, nên không ảnh hưởng tới phân tích.

Những cột không dời và lý do:
- `invoices.invoice_number` (`2026-NNNNNN`): mọi `issued_datetime` sau khi dời vẫn nằm trong năm 2026.
- `refunds.days_after_purchase`, `prescriptions.turnaround_minutes`, `vendors.lead_time_days`: là khoảng thời gian, không đổi khi cả hai mốc cùng dời.
- `vendors.order_weekday`: 63 chia hết cho 7 nên thứ trong tuần không đổi.

`product_costs` đổi kỳ giá "Annual price list" từ 2026-01-01 sang **2026-03-05**. Mô tả `change_reason` vẫn ghi "Annual" và không ảnh hưởng luật nào.
