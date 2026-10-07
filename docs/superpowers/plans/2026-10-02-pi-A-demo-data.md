# Pharmacy Demo Data (P0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mở rộng `pharmacy_demo` từ 13 tuần lên **12 tháng (2025-08-01 → 2026-07-31)** có mùa vụ tuần/tháng, giữ nguyên 7 finding cài sẵn + PH-004 sụt doanh số tháng 7, cài thêm kịch bản **margin PH-003** (giá vốn 5 thuốc Rx +8%, reimbursement đứng yên), bổ sung giá vốn theo thời gian, vendor + nhập hàng + lead time, snapshot tồn kho hằng tuần, lương theo giờ; xuất `targets.xlsx` cho demo upload; cập nhật `expected_findings.csv` và viết `scripts/check-expected-findings.ts` (Task M5 của master dùng).

**Architecture:** Không tìm thấy generator gốc ⇒ viết generator Python **tất định** (`scripts/demo_data/pharmacy_demo_gen`, 1 `random.Random(20260801)`). Chiến lược **"mở rộng, không sinh lại"**: 21 CSV gốc chuyển vào `demo_mockdata/base/` làm input bất biến (cửa sổ 2026-05-01 → 2026-07-31 đã được verify, chứa toàn bộ plant); generator sinh thêm 9 tháng lịch sử trước đó + top-up có kiểm soát trong cửa sổ gốc (chỉ doanh số cuối tuần và Rx), rồi ghi 25 CSV ra `demo_mockdata/`. Tồn kho mô phỏng **ngược** từ lần kiểm kê gốc 2026-07-31 để snapshot gốc vẫn là mốc. Nạp DB bằng `schema/base.sql` (pg_dump của DB hiện tại) + `schema/extension.sql` (chỉ thêm) + `\copy`, có backup bắt buộc; sau đó DAAB chạy extract-schema → sync-schema → generate-kg.

**Tech Stack:** Python ≥3.12 (uv, pytest 8, openpyxl 3.1.5) · Bash + Docker (`daab-postgres`, Postgres 16) · Node 24 (TypeScript chạy trực tiếp bằng type-stripping, `node:test`) · LAAM Postgres (`laam-postgres`, cổng 5500) chỉ đọc.

**Spec:** `docs/superpowers/specs/2026-09-25-industry-pack-proactive-intelligence-design.md` (rev 4 — §2.3, §6.2, §7.3 bảng độ phủ, §8, OD-5, OD-7)
**Master:** `docs/superpowers/plans/2026-10-02-proactive-intelligence-master.md` (§2 hợp đồng khoá — plan này không đổi; Task M4 dùng backfill `--from 2025-08-01 --to 2026-08-01`, Task M5 dùng `scripts/check-expected-findings.ts`)

## Global Constraints

- **Kế thừa toàn bộ Global Constraints của master** (LLM không tạo số; core không chứa từ ngữ ngành; DB khách chỉ đọc; sub-project là repo lồng nhau; DAAB dev DB cổng 5433; …).
- **Không đổi tên/xoá bảng hoặc cột hiện có của `pharmacy_demo`** (mapping `packs/_projects/pharmacy-chain/mapping.yaml` của Plan B dựa vào chúng). Chỉ **thêm**: cột `employees.hourly_wage`, `prescriptions.acquisition_cost`; bảng `vendors`, `product_costs`, `purchase_orders`, `purchase_order_lines`; giá trị mới `RECEIPT` cho `inventory_movements.movement_type`.
- **Dữ liệu gốc (2026-05-01 → 2026-07-31) giữ nguyên từng giá trị**, trừ đúng các thay đổi liệt kê ở mục "Thay đổi trên dữ liệu gốc" (pin bằng `tests/test_preserve.py`).
- **Trong cửa sổ gốc không sinh thêm** refund, void, override, drawer session, shift; chênh lệch kiểm kê (inventory adjustment) sinh ở mức bình thường tới hết **tháng 6/2026**, **không** sinh trong tháng 7 (tháng của plant PH-005); top-up không bao giờ gán cho `EMP-0006`, `EMP-0023`, `EMP-0102`.
- **Liên tục tại 2026-05-01**: lịch sử hiệu chỉnh từ chính cửa sổ gốc (giỏ hàng theo từng cửa hàng, phân bố số lượng/dòng, tỉ lệ override theo cửa hàng không tính người cài, mức nền theo tháng 5) — không được có bậc thang doanh số/override/shrink ở ranh giới (pin: `tests/test_continuity.py`).
- **Tất định**: một RNG duy nhất truyền qua `Ctx`; thứ tự gọi trong `generate()` là một phần hợp đồng; CSV ghi `lineterminator="\n"`. Đổi bất kỳ hằng số nào trong `config.py` ⇒ chạy lại toàn bộ test và sinh lại dữ liệu commit (Task 7).
- **As-of theo master: `as_of = 2026-07-31` (BAO GỒM — ngày dữ liệu cuối)**; cửa sổ truy vấn dùng `to = as_of + 1 ngày = 2026-08-01` (không gồm). Generator: `HISTORY_END` = as_of; `AS_OF_EXCLUSIVE` chỉ là `to` của truy vấn. Plan này không dời ngày dữ liệu.
- **Không DROP `pharmacy_demo` khi chưa có backup `pg_dump -Fc` đã kiểm bằng `pg_restore --list`**, lưu ở `~/Backups/EnnamKG/<YYYY-MM-DD>/daab/` (quyền 700, không commit). Script nạp tự từ chối nếu thiếu.
- **`git add` chỉ đường dẫn cụ thể**: workspace đang có file bẩn từ trước (`.gitignore`, `AGENTS.md`, `CLAUDE.md`, `.claude/settings.json`) — không dùng `git add -A`/`git commit -a` (memory `preexisting-uncommitted-changes-before-git-add`).
- **Task 1–7 phải land cùng nhau trên một nhánh**: từ Task 1 (git mv vào `base/`) tới Task 7 thư mục `demo_mockdata/` không có CSV ở gốc; Plan B/D chạy song song không được kéo trạng thái giữa chừng này.
- Checker `.ts` chạy bằng Node 24 không cần build: chỉ cú pháp xoá được (không `enum`, không parameter properties), import nội bộ có đuôi `.ts`, không thêm dependency npm.

## Review Focus

1. **Top-up/lịch sử làm loãng hoặc giả mạo một plant** (ví dụ sinh refund cho Sarah trong tháng 7, thêm shrink tháng 7 làm PH-005 hết nổi bật, lịch sử có một nhân viên khác vượt ngưỡng) — người xem demo mong mỗi finding chỉ trỏ đúng người/cửa hàng đã cài. Pin: `test_plants.py` (mỗi plant có kiểm tra dương **và** kiểm tra âm "không ai khác giống thế") + `test_window.py::test_no_generated_exceptions_inside_original_window` + `test_continuity.py` (không có bậc thang ở 2026-05-01 làm rule so kỳ trước bắn giả) (Task 6), `test_sales.py` (Task 3).
2. **Margin plant không nhìn thấy được**: nếu metric tính giá vốn = `quantity × product.unit_cost` cố định (spec §6.2) thì +8% không bao giờ tới metric; nếu rule so sánh **$ cộng dồn cấp cửa hàng** thì nhiễu khối lượng (đo được ±10–18% giữa các cửa hàng) lấn tín hiệu. Pin: `test_rx.py::test_original_fill_cost_follows_paid_amount_and_plant` (Task 4), `test_margin_plant.py` (Task 6: margin % PH-003 giảm ≥ 8% còn cửa hàng khác lệch ≤ 2%; gap/đơn vị của 5 thuốc giảm ≥ 40%) + OQ-2/OQ-3 gửi Plan B/D.
3. **Dữ liệu gốc bị sửa âm thầm** (rebase Rx lan sang cột khác, xoá nhầm receipt ngoài 3 dòng rác) — số trên demo cũ (Q1–Q17) phải giữ nguyên. Pin: `test_preserve.py::test_original_rows_are_kept_verbatim` (Task 6), `test_tables.py::test_load_base_drops_write_test_leftovers` (Task 1, đúng 5342 receipt).
4. **Nạp lại DB làm mất dữ liệu** (drop khi chưa có backup, nạp thiếu bảng mà vẫn báo xong). Pin: guard + so số dòng CSV↔DB trong `load_pharmacy_demo.sh`, diễn tập trên container tạm ở Task 9 (Step 4 kiểm guard phải exit 1; Step 6 phải in 25 dòng `ok`).
5. **Checker báo PASS sai** khi LAAM chưa sinh finding nào hoặc bảng `finding` dùng cột camelCase (`"ruleId"`, giống `"scheduledFor"` của LAAM). Pin: `check-expected-findings.test.ts` — "zero finding rows is a failure, never PASS 0/0" và "finding columns are detected in snake_case and camelCase" (Task 8).

## Phát hiện khi khảo sát (2026-10-02, đã tự kiểm tra)

- **Không có generator gốc**: `git log -- demo_mockdata` chỉ có 2 commit import CSV (`c90a539`, `926b8cc`, tác giả Sines Nguyen, "Co-Authored-By: Claude Fable 5"); không script nào trong `scripts/`, `db-export/`, `seeds/` ghi các CSV này ⇒ OD-7: viết generator mới, seed cố định.
- DB `pharmacy_demo` (daab-postgres:5433, user `ennam_kg`) có 21 bảng; khác CSV ở các dòng rác của test ghi DAAB (2026-08-03/04): 2 transaction id UUID (`88dcc884-…`, `4007cc95-…`), `EMP-9999`, `CUS-99991..3`, và `payments.status` = NULL ở 5001 dòng (CSV ghi `Approved`).
- **`receipts.csv` gốc chứa 3 dòng rác**: `RCT-0005317`, `RCT-0005319` (receipt Original của 2 transaction UUID) và `RCT-0005328` (reprint do `EMP-9999` in) ⇒ CSV gốc vi phạm FK nếu nạp nguyên. Đây chính là "2 giao dịch lạc tháng 8" của spec §2.3.
- **Kinh tế Rx gốc sai đơn vị**: `products.unit_cost` của 74 thuốc Rx là giá theo hộp, `prescriptions.quantity` là số viên ⇒ Σ`quantity × unit_cost` mỗi cửa hàng 250k–315k USD trong khi Σ`approved_amount` chỉ 10k–14k USD. Không rebase thì `rx_margin` âm ~95%.
- Mật độ gốc: ~11 giao dịch/cửa hàng/ngày, ~3,3 đơn Rx/cửa hàng/ngày, không có mùa vụ theo thứ (Mon..Sun 693–734 giao dịch), 22% giao dịch không có customer. `inventory_adjustments` gốc chỉ có tháng 7/2026. 27 refund ngày 2026-08-01..25 và 31 reprint tháng 8 là refund của giao dịch tháng 7 — **giữ nguyên**.
- Node v24.18.0 chạy `.ts` trực tiếp (đã thử `node --test a.test.ts`). LAAM DB chưa có bảng `finding` (Plan D tạo).
- Prototype đầy đủ đã chạy trong scratchpad trên dữ liệu thật: sinh dữ liệu ~4 giây, 57 test pytest ~14 giây, nạp thử vào container Postgres 16 tạm: 25/25 bảng khớp số dòng. Mã trong plan này là đúng mã đã chạy.

## Thay đổi trên dữ liệu gốc

| Thay đổi | Lý do / bằng chứng | Pin bởi |
|---|---|---|
| 74 dòng `products` Rx: `unit_cost`, `retail_price`, `gross_margin_percent` đổi sang giá **theo đơn vị cấp phát** (4 chữ số thập phân) | Giá theo hộp × số viên ⇒ giá vốn gấp ~20 lần doanh thu (xem trên) | `test_preserve.py` (chỉ 3 cột này được đổi, chỉ ở dòng Rx), `test_catalog.py::test_rx_cost_is_per_dispensing_unit` |
| Thêm cột cuối `employees.hourly_wage`, `prescriptions.acquisition_cost` | RET-LABOR-001 cần lương; PH-MARGIN-001 cần giá vốn theo ngày | `test_integrity.py::test_new_columns_are_appended_last` |
| Bỏ `receipts` `RCT-0005317`, `RCT-0005319`, `RCT-0005328` | Rác của test ghi DAAB, trỏ tới transaction/employee không có trong CSV | `test_tables.py::test_load_base_drops_write_test_leftovers`, `test_integrity.py::test_write_test_leftovers_are_gone` |
| Khi nạp lại DB: mất 2 transaction UUID (+ item/payment/movement), `EMP-9999`, `CUS-99991..3` | Chỉ có trong DB, không có trong CSV | `verify_plants.sql` (`bad_ids = 0`) |
| Khi nạp lại DB: `payments.status` của dòng gốc từ NULL thành `Approved` | CSV gốc ghi `Approved`; DB hiện tại được nạp bằng đường khác. **Làm đổi câu trả lời NL→SQL nào lọc theo `payments.status`** | — (ghi nhận, không test) |

## File Structure

| Đường dẫn | Tạo/Sửa | Trách nhiệm |
|---|---|---|
| `demo_mockdata/base/*.csv` (21 file) | Move (git mv) | Gói gốc bất biến — input của generator |
| `demo_mockdata/*.csv` (25 file) | Sinh lại (Task 7) | Dữ liệu 12 tháng để nạp `pharmacy_demo` (21 bảng cũ + 4 bảng mới) |
| `demo_mockdata/targets.xlsx` | Sinh (Task 7) | KPI target dạng dài `Store ID \| Metric Key \| Period \| Target Value` (2025-08 → 2026-12) cho demo upload "Dữ liệu bảng" |
| `demo_mockdata/DATA_SUMMARY.txt` | Sinh (Task 7) | Seed, khoảng ngày, thông số plant, số dòng mỗi bảng |
| `demo_mockdata/expected_findings.csv` | Sửa (Task 8) | Ground truth: thêm cột `rule_ids`, FND-008 (PH-004 sales decline), FND-009 (margin PH-003) |
| `demo_mockdata/README.txt`, `demo_mockdata/Michael_Pharmacy_Chain_Full_Mock_Data_Manifest.txt` | Sửa (Task 7) | Mô tả bản mở rộng 12 tháng + anomaly 10 |
| `scripts/demo_data/pyproject.toml`, `uv.lock`, `.gitignore` | Tạo | Project uv (openpyxl, pytest, cấu hình ruff) |
| `scripts/demo_data/pharmacy_demo_gen/config.py` | Tạo | Mọi hằng số: seed, ngày, plant, mùa vụ, tỉ lệ, lương |
| `scripts/demo_data/pharmacy_demo_gen/tables.py` | Tạo | `Table`, đọc/ghi CSV tất định, `load_base`, `IdSeq` |
| `scripts/demo_data/pharmacy_demo_gen/ctx.py` | Tạo | `Ctx`: RNG, lookup nhân viên/khách, giá vốn theo ngày + cửa hàng |
| `scripts/demo_data/pharmacy_demo_gen/catalog.py` | Tạo | Rebase Rx, chọn 5 thuốc plant, `vendors`, `product_costs` |
| `scripts/demo_data/pharmacy_demo_gen/staff.py` | Tạo | `employees.hourly_wage` |
| `scripts/demo_data/pharmacy_demo_gen/retail.py` | Tạo | Giao dịch front-store lịch sử + top-up cuối tuần, item, payment, receipt, movement SALE, void, override |
| `scripts/demo_data/pharmacy_demo_gen/operations.py` | Tạo | Refund nền, shift, cash drawer (chỉ lịch sử) |
| `scripts/demo_data/pharmacy_demo_gen/rx.py` | Tạo | Prescription + claim 12 tháng, top-up Rx, `acquisition_cost` |
| `scripts/demo_data/pharmacy_demo_gen/inventory.py` | Tạo | Mô phỏng tồn kho ngược, PO + RECEIPT, snapshot thứ Sáu, adjustment kiểm kê lịch sử |
| `scripts/demo_data/pharmacy_demo_gen/targets.py` | Tạo | `targets.xlsx` hiệu chỉnh từ thực tế đã sinh |
| `scripts/demo_data/pharmacy_demo_gen/generate.py`, `__main__.py` | Tạo | Điều phối + CLI + `DATA_SUMMARY.txt` |
| `scripts/demo_data/tests/*.py` (13 file) | Tạo | Unit test từng module + acceptance test trên output |
| `scripts/demo_data/schema/base.sql` | Tạo (pg_dump) | DDL 21 bảng hiện có (PK/FK) |
| `scripts/demo_data/schema/extension.sql` | Tạo | Chỉ thêm cột/bảng/FK mới |
| `scripts/demo_data/load_pharmacy_demo.sh` | Tạo | Drop/create/nạp `pharmacy_demo` có guard backup + so số dòng |
| `scripts/demo_data/verify_plants.sql` | Tạo | Smoke check sau khi nạp |
| `scripts/demo_data/resync_daab_schema.sh` | Tạo | extract-schema → sync-schema → generate-kg + kiểm đếm node |
| `scripts/check-expected-findings.ts`, `scripts/check-expected-findings.test.ts` | Tạo | So finding LAAM với ground truth (`PASS n/n`) |

Thông số đã đo trên prototype (seed 20260801): 20.679 giao dịch, 38.538 đơn Rx, 96.691 movement (RECEIPT 2.568), 79.500 snapshot; giá trị/giao dịch lịch sử lệch ≤ 5% so với cửa sổ gốc ở mọi cửa hàng (gốc $176–185); doanh số/ngày tháng 4→5 lệch ≤ 10%; override lịch sử 2,9–5,3% giao dịch (gốc không tính EMP-0023: 3,0–4,9%); shrink tháng 5–6 ~3–5k USD/cửa hàng (lịch sử ~3,5–4,3k, tháng 7 không-plant ~4,4k, PH-005 tháng 7 14,5k); PH-004 tỉ lệ từ chối claim tháng 5–7 = 15,9% (các cửa hàng khác 4,6–5,8%); Rx margin % PH-003 14 ngày cuối 17,7% so với 20,0% 28 ngày trước (cửa hàng khác ±0,2 điểm); lương ≈ 12–18% doanh thu; CSV sinh ra ~45 MB (git nén tốt).

---
## Tasks

Mọi lệnh chạy từ gốc workspace `/Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace` trừ khi ghi `cd`. Lệnh Python luôn chạy trong `scripts/demo_data` qua `uv run`.

### Task 1: Đóng băng gói gốc + khung project generator

**Files:**
- Move: `demo_mockdata/{audit_events,cash_drawers,customers,discount_overrides,employee_shifts,employees,insurance_claims,inventory_adjustments,inventory_movements,inventory_snapshots,invoices,payments,prescriptions,products,receipts,refund_items,refunds,stores,transaction_items,transactions,voids}.csv` → `demo_mockdata/base/`
- Create: `scripts/demo_data/pyproject.toml`, `scripts/demo_data/.gitignore`, `scripts/demo_data/pharmacy_demo_gen/__init__.py`, `scripts/demo_data/pharmacy_demo_gen/config.py`, `scripts/demo_data/pharmacy_demo_gen/tables.py`
- Test: `scripts/demo_data/tests/conftest.py`, `scripts/demo_data/tests/helpers.py`, `scripts/demo_data/tests/test_tables.py`

**Interfaces:**
- Consumes: 21 CSV gốc.
- Produces: `config` (hằng số, kể cả `SEED`, `HISTORY_START`, `CORE_START`, `HISTORY_END`, `AS_OF_EXCLUSIVE`, `LEFTOVER_RECEIPT_IDS`, `PLANTED_PEOPLE`); `tables.Table(columns: list[str], rows: list[dict[str,str]])` với `add(row: dict) -> dict`; `fmt(value) -> str`; `read_table(path) -> Table`; `load_base(base_dir: Path) -> dict[str, Table]`; `write_table(path, table) -> None`; `IdSeq(prefix, width, start).next() -> str`; `parse_dt(text) -> datetime`; `BASE_TABLES`, `NEW_TABLES`. Test fixtures `out` (output đã sinh, dùng từ Task 6), `base`; helpers `PRIMARY_KEYS`, `FOREIGN_KEYS`, `within`, `day_of`, `is_generated`, `ts`.

- [ ] **Step 1: Chuyển gói gốc vào `base/`** (giữ lịch sử git; thư mục gốc tạm thời không có CSV cho tới Task 7)

```bash
mkdir -p demo_mockdata/base
for t in audit_events cash_drawers customers discount_overrides employee_shifts employees insurance_claims \
         inventory_adjustments inventory_movements inventory_snapshots invoices payments prescriptions products \
         receipts refund_items refunds stores transaction_items transactions voids; do
  git mv "demo_mockdata/$t.csv" "demo_mockdata/base/$t.csv"
done
ls demo_mockdata/base | wc -l
```
Expected: `21`.

- [ ] **Step 2: Tạo project uv**

`scripts/demo_data/pyproject.toml`:
```toml
[project]
name = "pharmacy-demo-gen"
version = "0.1.0"
description = "Deterministic generator for the 12-month pharmacy_demo dataset"
requires-python = ">=3.12"
dependencies = ["openpyxl==3.1.5"]

[dependency-groups]
dev = ["pytest==8.3.4"]

[tool.uv]
package = false

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "W"]
```

`scripts/demo_data/.gitignore`:
```text
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
```

`scripts/demo_data/pharmacy_demo_gen/__init__.py`:
```python
"""Deterministic 12-month generator for the pharmacy_demo dataset (Plan A, Phase P0)."""
```

- [ ] **Step 3: Viết test (fixtures + helpers + test_tables)**

`scripts/demo_data/tests/conftest.py`:
```python
import csv
import sys
from functools import lru_cache
from pathlib import Path

import pytest

DEMO_DATA_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = Path(__file__).resolve().parents[3]
BASE_DIR = WORKSPACE / "demo_mockdata" / "base"
sys.path.insert(0, str(DEMO_DATA_DIR))


class Out:
    """Read-only view over one generated output directory."""

    def __init__(self, path: Path):
        self.path = path

    @lru_cache(maxsize=None)
    def rows(self, table: str) -> list[dict[str, str]]:
        with (self.path / f"{table}.csv").open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    @lru_cache(maxsize=None)
    def columns(self, table: str) -> list[str]:
        with (self.path / f"{table}.csv").open(newline="", encoding="utf-8") as fh:
            return next(csv.reader(fh))


@pytest.fixture(scope="session")
def out(tmp_path_factory) -> Out:
    from pharmacy_demo_gen.generate import generate

    target = tmp_path_factory.mktemp("generated")
    generate(BASE_DIR, target)
    return Out(target)


@pytest.fixture(scope="session")
def base() -> Out:
    return Out(BASE_DIR)
```

`scripts/demo_data/tests/helpers.py`:
```python
"""Shared helpers for the tests (dates are naive local time, windows are inclusive days)."""
from datetime import date, datetime

AS_OF = date(2026, 7, 31)
CORE_START = date(2026, 5, 1)
GENERATED_PREFIXES = ("TXN-1", "REF-1", "VOID-1", "OVR-1", "DRW-1", "SHF-1", "ADJ-1", "SNP-1", "RX-1", "CLM-1")
STORES = ("PH-001", "PH-002", "PH-003", "PH-004", "PH-005")


def ts(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


def day_of(text: str) -> date:
    return date.fromisoformat(text[:10])


def within(text: str, start: date, end: date) -> bool:
    return start <= day_of(text) <= end


def is_generated(identifier: str) -> bool:
    return identifier.startswith(GENERATED_PREFIXES)


PRIMARY_KEYS = {
    "stores": "store_id", "products": "product_id", "employees": "employee_id", "customers": "customer_id",
    "transactions": "transaction_id", "transaction_items": "transaction_item_id", "payments": "payment_id",
    "receipts": "receipt_id", "invoices": "invoice_id", "refunds": "refund_id", "refund_items": "refund_item_id",
    "voids": "void_id", "discount_overrides": "override_id", "cash_drawers": "drawer_session_id",
    "employee_shifts": "shift_id", "inventory_movements": "movement_id", "inventory_adjustments": "adjustment_id",
    "inventory_snapshots": "snapshot_id", "prescriptions": "prescription_id", "insurance_claims": "claim_id",
    "audit_events": "audit_event_id", "vendors": "vendor_id", "product_costs": "product_cost_id",
    "purchase_orders": "po_id", "purchase_order_lines": "po_line_id",
}

FOREIGN_KEYS = [  # (table, column, referenced table) — mirrors pharmacy_demo FKs + extension.sql
    ("audit_events", "employee_id", "employees"), ("audit_events", "store_id", "stores"),
    ("cash_drawers", "employee_id", "employees"), ("cash_drawers", "store_id", "stores"),
    ("cash_drawers", "approving_manager_id", "employees"), ("customers", "preferred_store_id", "stores"),
    ("discount_overrides", "transaction_id", "transactions"), ("discount_overrides", "store_id", "stores"),
    ("discount_overrides", "product_id", "products"), ("discount_overrides", "approving_manager_id", "employees"),
    ("discount_overrides", "employee_id", "employees"), ("employee_shifts", "employee_id", "employees"),
    ("employee_shifts", "store_id", "stores"), ("employees", "store_id", "stores"),
    ("insurance_claims", "store_id", "stores"), ("insurance_claims", "prescription_id", "prescriptions"),
    ("inventory_adjustments", "product_id", "products"), ("inventory_adjustments", "employee_id", "employees"),
    ("inventory_adjustments", "store_id", "stores"), ("inventory_movements", "employee_id", "employees"),
    ("inventory_movements", "store_id", "stores"), ("inventory_movements", "product_id", "products"),
    ("inventory_snapshots", "product_id", "products"), ("inventory_snapshots", "store_id", "stores"),
    ("invoices", "transaction_id", "transactions"), ("invoices", "customer_id", "customers"),
    ("invoices", "store_id", "stores"), ("payments", "transaction_id", "transactions"),
    ("prescriptions", "pharmacist_employee_id", "employees"), ("prescriptions", "customer_id", "customers"),
    ("prescriptions", "store_id", "stores"), ("prescriptions", "technician_employee_id", "employees"),
    ("prescriptions", "product_id", "products"), ("receipts", "printed_by_employee_id", "employees"),
    ("receipts", "store_id", "stores"), ("receipts", "transaction_id", "transactions"),
    ("refund_items", "product_id", "products"), ("refund_items", "refund_id", "refunds"),
    ("refunds", "employee_id", "employees"), ("refunds", "customer_id", "customers"),
    ("refunds", "original_transaction_id", "transactions"), ("refunds", "store_id", "stores"),
    ("refunds", "approving_manager_id", "employees"), ("transaction_items", "product_id", "products"),
    ("transaction_items", "transaction_id", "transactions"), ("transactions", "customer_id", "customers"),
    ("transactions", "employee_id", "employees"), ("transactions", "store_id", "stores"),
    ("voids", "transaction_id", "transactions"), ("voids", "employee_id", "employees"),
    ("voids", "store_id", "stores"), ("products", "vendor_id", "vendors"),
    ("product_costs", "product_id", "products"), ("product_costs", "store_id", "stores"),
    ("product_costs", "vendor_id", "vendors"), ("purchase_orders", "store_id", "stores"),
    ("purchase_orders", "vendor_id", "vendors"), ("purchase_order_lines", "po_id", "purchase_orders"),
    ("purchase_order_lines", "product_id", "products"),
]
```

`scripts/demo_data/tests/test_tables.py`:
```python
from datetime import date, datetime

import pytest

from conftest import BASE_DIR
from pharmacy_demo_gen.tables import IdSeq, Table, fmt, load_base, read_table, write_table


def test_fmt_matches_original_csv_conventions():
    assert fmt(None) == ""
    assert fmt(True) == "True" and fmt(False) == "False"
    assert fmt(3.14159) == "3.14"
    assert fmt(7) == "7"
    assert fmt(datetime(2026, 7, 31, 9, 5, 0)) == "2026-07-31 09:05:00"
    assert fmt(date(2026, 7, 31)) == "2026-07-31"


def test_id_sequences_start_outside_the_original_range():
    seq = IdSeq("TXN-", 7, 1_000_001)
    assert [seq.next(), seq.next()] == ["TXN-1000001", "TXN-1000002"]


def test_table_rejects_unknown_columns():
    with pytest.raises(KeyError):
        Table(["a"]).add({"b": 1})


def test_write_then_read_roundtrip_uses_lf(tmp_path):
    table = Table(["id", "note"])
    table.add({"id": "X-1", "note": 'a, "quoted" value'})
    write_table(tmp_path / "x.csv", table)
    assert read_table(tmp_path / "x.csv").rows == table.rows
    assert b"\r" not in (tmp_path / "x.csv").read_bytes()


def test_load_base_drops_write_test_leftovers():
    tables = load_base(BASE_DIR)
    receipt_ids = {r["receipt_id"] for r in tables["receipts"].rows}
    assert not {"RCT-0005317", "RCT-0005319", "RCT-0005328"} & receipt_ids
    assert len(tables["receipts"].rows) == 5342
    assert len(tables["transactions"].rows) == 5000
```

- [ ] **Step 4: Chạy test — phải FAIL**

```bash
cd scripts/demo_data && uv sync && uv run pytest tests/test_tables.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'pharmacy_demo_gen.tables'`.

- [ ] **Step 5: Implement `config.py` và `tables.py`**

`scripts/demo_data/pharmacy_demo_gen/config.py`:
```python
"""Fixed parameters of the pharmacy_demo generator. Changing any value changes the output."""
from datetime import date

SEED = 20260801

HISTORY_START = date(2025, 8, 1)   # first generated day (Friday)
CORE_START = date(2026, 5, 1)      # first day of the original Aug-2026 package (kept verbatim)
HISTORY_END = date(2026, 7, 31)    # last day with sales (inclusive, Friday)
AS_OF_EXCLUSIVE = date(2026, 8, 1) # query `to` = as_of (HISTORY_END, inclusive) + 1 day

PRICE_UPDATE_DATE = date(2026, 1, 1)
PRICE_UPDATE_FACTOR = 1.015        # chain-wide cost AND price/reimbursement list update

MARGIN_PLANT_STORE = "PH-003"
MARGIN_PLANT_START = date(2026, 7, 18)   # last 14 days of history
MARGIN_PLANT_COST_FACTOR = 1.08
MARGIN_PLANT_DRUG_COUNT = 5
HEAVY_DRUG_WEIGHT = 20             # popularity weight of the 5 heavy Rx drugs vs 1 for the rest

# Rows of the original receipts.csv left behind by DAAB write tests (2 UUID transactions + EMP-9999).
LEFTOVER_RECEIPT_IDS = frozenset({"RCT-0005317", "RCT-0005319", "RCT-0005328"})

PLANTED_PEOPLE = frozenset({"EMP-0006", "EMP-0023", "EMP-0102"})

# Mon..Sun multipliers. Mon-Thu = 1 so May-Jul top-ups only add Fri/Sat/Sun volume.
WEEKDAY_SHAPE = (1.0, 1.0, 1.0, 1.0, 1.06, 1.12, 1.05)
RX_WEEKDAY_SHAPE = (1.08, 1.05, 1.05, 1.05, 1.07, 0.80, 0.55)
MONTH_WEIGHT = {8: 0.97, 9: 0.95, 10: 0.98, 11: 1.03, 12: 1.15, 1: 1.06,
                2: 1.02, 3: 0.99, 4: 0.98, 5: 1.0, 6: 1.0, 7: 1.0}

RX_BASE_PER_STORE_DAY = 22
RX_COST_TO_REVENUE = 0.80          # acquisition cost / (payer + copay) for generated fills
RX_REJECT_RATE = 0.05
RX_REJECT_PLANT = {"PH-004": (date(2026, 5, 1), 0.155)}

TAX_RATE = 0.0825
NULL_CUSTOMER_SHARE = 0.22
LINE_DISCOUNT_SHARE = 0.17          # + overrides ~= 19.3% discounted lines in the original window
# Basket shape: lines-per-transaction is measured PER STORE from the original window (retail.lines_weights);
# line quantity mix measured on the original window (qty 1: 18998, 2: 1185, 3: 1204, 4: 1209 of 22596 lines):
LINE_QTY_WEIGHTS = (84, 5, 5, 6)                                                 # qty 1..4
OVERRIDE_PERCENTS = (25, 35, 45, 50)                                             # original discount_percent values
VOID_RATE = 0.024                  # history only
REFUND_RATE = 0.03                 # history only, refund dated before CORE_START
SHIFTS_PER_STORE_DAY = 2.2         # history only
SNAPSHOT_VARIANCE_SHARE = 0.18     # weekly count variances (calibrated to the non-plant July shrink level)
COUNT_VARIANCE_END = date(2026, 7, 1)   # no generated count variances in July 2026 (PH-005 shrink plant month)

WAGE_BY_ROLE = {
    "Cashier": 15.50, "Pharmacy Technician": 20.00, "Inventory Associate": 17.00,
    "Shift Supervisor": 21.00, "Assistant Manager": 26.00, "Store Manager": 34.00,
    "Pharmacist": 62.00,
}

FRONT_ROLES = ("Cashier", "Shift Supervisor", "Assistant Manager", "Store Manager")
MANAGER_ROLES = ("Store Manager", "Assistant Manager")
APPROVER_ROLES = ("Store Manager", "Assistant Manager", "Shift Supervisor")   # original override approvers
PAYMENT_METHODS = (("Credit Card", 44), ("Debit Card", 28), ("Cash", 20), ("Gift Card", 5), ("Split Payment", 3))
PAYERS = (("Care Network", 26), ("PayerOne", 26), ("United Mock", 25), ("HealthPlan TX", 23))
REJECTION_CODES = ("E31", "E22", "E14", "E01")
RX_STATUSES = (("Picked Up", 706), ("Ready", 89), ("Not Collected", 81), ("Reversed", 68), ("Cancelled", 56))
REFUND_METHODS = (("Gift Card", 40), ("Cash", 30), ("Original Payment", 30))
REFUND_REASONS = ("Product Defective", "Customer Changed Mind", "Incorrect Product", "Other")
VOID_REASONS = ("Duplicate scan", "Payment issue", "Price dispute", "Customer changed mind")
VOID_STAGES = ("Before Payment", "After Receipt Printed", "After Payment Authorization")
REGISTERS = ("REG-01", "REG-02", "REG-03", "REG-04", "REG-05", "REG-06")
```

`scripts/demo_data/pharmacy_demo_gen/tables.py`:
```python
"""CSV tables as ordered column lists + list of string dicts; deterministic IO and ID sequences."""
import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import config as C

BASE_TABLES = (
    "stores", "products", "employees", "customers", "transactions", "transaction_items",
    "payments", "receipts", "invoices", "refunds", "refund_items", "voids",
    "discount_overrides", "cash_drawers", "employee_shifts", "inventory_movements",
    "inventory_adjustments", "inventory_snapshots", "prescriptions", "insurance_claims",
    "audit_events",
)
NEW_TABLES = ("vendors", "product_costs", "purchase_orders", "purchase_order_lines")


@dataclass
class Table:
    columns: list[str]
    rows: list[dict[str, str]] = field(default_factory=list)

    def add(self, row: dict) -> dict:
        unknown = set(row) - set(self.columns)
        if unknown:
            raise KeyError(f"unknown columns {sorted(unknown)}")
        clean = {c: fmt(row.get(c)) for c in self.columns}
        self.rows.append(clean)
        return clean


def fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def read_table(path: Path) -> Table:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = [dict(r) for r in reader]
        return Table(columns=list(reader.fieldnames or []), rows=rows)


def load_base(base_dir: Path) -> dict[str, Table]:
    """Original package minus the rows left behind by DAAB write tests (see config.LEFTOVER_RECEIPT_IDS)."""
    tables = {name: read_table(base_dir / f"{name}.csv") for name in BASE_TABLES}
    receipts = tables["receipts"]
    receipts.rows = [r for r in receipts.rows if r["receipt_id"] not in C.LEFTOVER_RECEIPT_IDS]
    return tables


def write_table(path: Path, table: Table) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=table.columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(table.rows)


class IdSeq:
    """Generated IDs live in a range that cannot collide with the original package (which starts at 1)."""

    def __init__(self, prefix: str, width: int, start: int):
        self.prefix, self.width, self.next_value = prefix, width, start

    def next(self) -> str:
        value = f"{self.prefix}{self.next_value:0{self.width}d}"
        self.next_value += 1
        return value


def parse_dt(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
```

- [ ] **Step 6: Chạy test — phải PASS**

```bash
cd scripts/demo_data && uv run pytest tests/test_tables.py -q && uvx ruff check .
```
Expected: `5 passed`; `All checks passed!`.

- [ ] **Step 7: Commit**

```bash
git add demo_mockdata/base demo_mockdata/*.csv scripts/demo_data/pyproject.toml scripts/demo_data/uv.lock \
        scripts/demo_data/.gitignore scripts/demo_data/pharmacy_demo_gen scripts/demo_data/tests
git commit -m "chore(demo-data): freeze original pharmacy package as generator input"
```
(`demo_mockdata/*.csv` ở đây chỉ để stage phần xoá của `git mv` nếu shell chưa stage; `git status` sau commit không được còn `deleted:` nào trong `demo_mockdata/`.)

### Task 2: Kinh tế sản phẩm — Rx theo đơn vị, 5 thuốc plant, vendor, lịch sử giá vốn, lương

**Files:**
- Create: `scripts/demo_data/pharmacy_demo_gen/ctx.py`, `scripts/demo_data/pharmacy_demo_gen/catalog.py`, `scripts/demo_data/pharmacy_demo_gen/staff.py`
- Test: `scripts/demo_data/tests/test_catalog.py`

**Interfaces:**
- Consumes: `load_base`, `config`, `Table`, `IdSeq`.
- Produces: `ctx.days(start, end)` (ngày, gồm 2 đầu); `ctx.price_factor(day) -> float`; `Ctx(tables, seed=SEED)` với `rng`, `t`, `products`, `rx_ids`, `retail_ids`, `employees`, `stores`, `ids`, `unit_cost_2026`, `rx_revenue_per_unit`, `store_cost_override`, `heavy_rx`, `stoch_round(x) -> int`, `weighted(pairs) -> str`, `at(day, hour_from, hour_to) -> datetime`, `staff(store, roles, day, exclude=frozenset()) -> list[str]`, `customer(day, allow_none=True) -> str | None`, `unit_cost(product_id, store, day) -> float`; `catalog.prepare_catalog(ctx)`, `catalog.build_vendors(ctx) -> Table`, `catalog.build_product_costs(ctx) -> Table`, `staff.add_hourly_wage(ctx)`.

- [ ] **Step 1: Viết test**

`scripts/demo_data/tests/test_catalog.py`:
```python
from collections import Counter
from datetime import date

import pytest

from conftest import BASE_DIR
from pharmacy_demo_gen import config as C
from pharmacy_demo_gen.catalog import build_product_costs, build_vendors, prepare_catalog
from pharmacy_demo_gen.ctx import Ctx
from pharmacy_demo_gen.staff import add_hourly_wage
from pharmacy_demo_gen.tables import load_base


@pytest.fixture(scope="module")
def ctx() -> Ctx:
    c = Ctx(load_base(BASE_DIR))
    prepare_catalog(c)
    return c


def test_rx_cost_is_per_dispensing_unit(ctx):
    assert len(ctx.rx_ids) == 74
    assert all(0 < ctx.unit_cost_2026[p] < 5 for p in ctx.rx_ids)
    for p in ctx.rx_ids:
        assert ctx.rx_revenue_per_unit[p] == pytest.approx(ctx.unit_cost_2026[p] / C.RX_COST_TO_REVENUE)


def test_plant_drugs_are_the_five_most_filled(ctx):
    fills = Counter(r["product_id"] for r in ctx.t["prescriptions"].rows)
    assert ctx.heavy_rx == sorted(ctx.rx_ids, key=lambda p: (-fills[p], p))[:5]


def test_unit_cost_timeline(ctx):
    drug = ctx.heavy_rx[0]
    now = ctx.unit_cost_2026[drug]
    assert ctx.unit_cost(drug, "PH-003", date(2026, 7, 17)) == pytest.approx(now)
    assert ctx.unit_cost(drug, "PH-003", date(2026, 7, 18)) == pytest.approx(now * 1.08)
    assert ctx.unit_cost(drug, "PH-001", date(2026, 7, 31)) == pytest.approx(now)
    assert ctx.unit_cost(drug, "PH-001", date(2025, 12, 31)) == pytest.approx(now / 1.015)


def test_vendors_and_cost_history(ctx):
    vendors = build_vendors(ctx)
    assert len(vendors.rows) == 35
    assert all(2 <= int(v["lead_time_days"]) <= 9 for v in vendors.rows)
    costs = build_product_costs(ctx)
    assert len(costs.rows) == 2 * 800 + 5
    assert [r["store_id"] for r in costs.rows if r["store_id"]] == ["PH-003"] * 5


def test_every_employee_gets_a_role_based_wage(ctx):
    add_hourly_wage(ctx)
    for e in ctx.t["employees"].rows:
        assert abs(float(e["hourly_wage"]) / C.WAGE_BY_ROLE[e["role"]] - 1) <= 0.051
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
cd scripts/demo_data && uv run pytest tests/test_catalog.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'pharmacy_demo_gen.catalog'`.

- [ ] **Step 3: Implement**

`scripts/demo_data/pharmacy_demo_gen/ctx.py`:
```python
"""Shared generation context: one seeded RNG, the tables, lookups and ID sequences."""
import bisect
import random
from datetime import date, datetime, time, timedelta

from . import config as C
from .tables import IdSeq, Table


def days(start: date, end: date):
    """Inclusive day range."""
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def price_factor(day: date) -> float:
    """Cost/price/reimbursement list level relative to the 2026 list."""
    return 1.0 if day >= C.PRICE_UPDATE_DATE else 1.0 / C.PRICE_UPDATE_FACTOR


class Ctx:
    def __init__(self, tables: dict[str, Table], seed: int = C.SEED):
        self.rng = random.Random(seed)
        self.t = tables
        self.products = {r["product_id"]: r for r in tables["products"].rows}
        self.rx_ids = sorted(p for p, r in self.products.items() if r["prescription_required"] == "True")
        self.retail_ids = sorted(p for p, r in self.products.items() if r["prescription_required"] != "True")
        self.employees = {r["employee_id"]: r for r in tables["employees"].rows}
        self.stores = sorted(r["store_id"] for r in tables["stores"].rows)
        signups = sorted((r["signup_date"], r["customer_id"]) for r in tables["customers"].rows)
        self._signup_dates = [s for s, _ in signups]
        self._signup_ids = [c for _, c in signups]
        self.ids = {
            "txn": IdSeq("TXN-", 7, 1_000_001), "rcp": IdSeq("RCP-", 8, 10_000_001),
            "li": IdSeq("LI-", 8, 10_000_001), "pay": IdSeq("PAY-", 8, 10_000_001),
            "rct": IdSeq("RCT-", 7, 1_000_001), "mov": IdSeq("MOV-", 8, 10_000_001),
            "ref": IdSeq("REF-", 6, 100_001), "rtx": IdSeq("RTX-", 6, 100_001),
            "rli": IdSeq("RLI-", 7, 1_000_001), "void": IdSeq("VOID-", 6, 100_001),
            "ovr": IdSeq("OVR-", 6, 100_001), "drw": IdSeq("DRW-", 7, 1_000_001),
            "shf": IdSeq("SHF-", 7, 1_000_001), "adj": IdSeq("ADJ-", 7, 1_000_001),
            "snp": IdSeq("SNP-", 8, 10_000_001), "rx": IdSeq("RX-", 7, 1_000_001),
            "rxn": IdSeq("RXN-", 7, 2_000_001), "clm": IdSeq("CLM-", 7, 1_000_001),
            "pc": IdSeq("PC-", 6, 1), "po": IdSeq("PO-", 6, 1), "pol": IdSeq("POL-", 7, 1),
        }
        self.unit_cost_2026: dict[str, float] = {}      # filled by catalog.prepare_catalog
        self.rx_revenue_per_unit: dict[str, float] = {}  # filled by catalog.prepare_catalog
        self.store_cost_override: dict[tuple[str, str], tuple[date, float]] = {}
        self.heavy_rx: list[str] = []
        self.override_rate: dict[str, float] = {}  # filled by retail.generate_sales
        self.lines_weights: dict[str, list[int]] = {}  # filled by retail.generate_sales

    # ---------- randomness helpers ----------
    def stoch_round(self, x: float) -> int:
        base = int(x)
        return base + (1 if self.rng.random() < x - base else 0)

    def weighted(self, pairs) -> str:
        values = [v for v, _ in pairs]
        weights = [w for _, w in pairs]
        return self.rng.choices(values, weights=weights, k=1)[0]

    def at(self, day: date, hour_from: int, hour_to: int) -> datetime:
        """Random timestamp on `day` with hour in [hour_from, hour_to]."""
        secs = self.rng.randint(hour_from * 3600, hour_to * 3600 + 3599)
        return datetime.combine(day, time()) + timedelta(seconds=secs)

    # ---------- lookups ----------
    def staff(self, store: str, roles, day: date, exclude=frozenset()) -> list[str]:
        out = [e for e, r in self.employees.items()
               if r["store_id"] == store and r["role"] in roles and r["hire_date"] <= day.isoformat()
               and e not in exclude]
        return sorted(out)

    def customer(self, day: date, allow_none: bool = True) -> str | None:
        if allow_none and self.rng.random() < C.NULL_CUSTOMER_SHARE:
            return None
        hi = bisect.bisect_right(self._signup_dates, day.isoformat())
        if hi == 0:
            return None
        return self._signup_ids[self.rng.randrange(hi)]

    def unit_cost(self, product_id: str, store: str, day: date) -> float:
        override = self.store_cost_override.get((product_id, store))
        if override and day >= override[0]:
            return override[1]
        return self.unit_cost_2026[product_id] * price_factor(day)
```

`scripts/demo_data/pharmacy_demo_gen/catalog.py`:
```python
"""Product economics: Rx per-unit rebasing, vendors, dated cost history and the margin plant."""
import statistics
from collections import Counter, defaultdict
from datetime import timedelta

from . import config as C
from .ctx import Ctx
from .tables import Table

VENDOR_COLUMNS = ["vendor_id", "vendor_name", "lead_time_days", "order_weekday", "payment_terms", "status"]
PRODUCT_COST_COLUMNS = ["product_cost_id", "product_id", "store_id", "vendor_id",
                        "effective_from", "effective_to", "unit_cost", "change_reason"]
_NAME_A = ("Lone Star", "Gulf Coast", "Prairie", "Trinity", "Red River",
           "Brazos", "Pecos", "Panhandle", "Hill Country", "Big Bend")
_NAME_B = ("Medical Supply", "Wholesale", "Distributors", "Health Partners")


def rebase_rx_products(ctx: Ctx) -> None:
    """Original Rx unit_cost is per package while prescriptions.quantity is per unit (cost ~20x revenue).
    Rebase Rx unit_cost/retail_price to per-dispensing-unit values derived from the original fills."""
    claims = {r["prescription_id"]: r for r in ctx.t["insurance_claims"].rows}
    paid_per_unit, cash_per_unit = defaultdict(list), defaultdict(list)
    for rx in ctx.t["prescriptions"].rows:
        qty = int(rx["quantity"])
        claim = claims[rx["prescription_id"]]
        cash_per_unit[rx["product_id"]].append(float(rx["cash_price"]) / qty)
        if claim["claim_status"] == "Approved":
            paid = float(claim["approved_amount"]) + float(claim["customer_amount"])
            paid_per_unit[rx["product_id"]].append(paid / qty)
    all_paid = statistics.median(v for vs in paid_per_unit.values() for v in vs)
    all_cash = statistics.median(v for vs in cash_per_unit.values() for v in vs)
    for pid in ctx.rx_ids:
        row = ctx.products[pid]
        revenue_u = statistics.median(paid_per_unit[pid]) if paid_per_unit[pid] else all_paid
        cash_u = statistics.median(cash_per_unit[pid]) if cash_per_unit[pid] else all_cash
        cost_u = revenue_u * C.RX_COST_TO_REVENUE
        retail_u = max(cash_u, revenue_u * 1.2)
        row["unit_cost"] = f"{cost_u:.4f}"
        row["retail_price"] = f"{retail_u:.4f}"
        row["gross_margin_percent"] = f"{(retail_u - cost_u) / retail_u * 100:.1f}"


def prepare_catalog(ctx: Ctx) -> None:
    rebase_rx_products(ctx)
    ctx.unit_cost_2026 = {pid: float(r["unit_cost"]) for pid, r in ctx.products.items()}
    ctx.rx_revenue_per_unit = {pid: ctx.unit_cost_2026[pid] / C.RX_COST_TO_REVENUE for pid in ctx.rx_ids}
    fills = Counter(r["product_id"] for r in ctx.t["prescriptions"].rows)
    ranked = sorted(ctx.rx_ids, key=lambda p: (-fills[p], p))
    ctx.heavy_rx = ranked[:C.MARGIN_PLANT_DRUG_COUNT]
    for pid in ctx.heavy_rx:
        planted = ctx.unit_cost_2026[pid] * C.MARGIN_PLANT_COST_FACTOR
        ctx.store_cost_override[(pid, C.MARGIN_PLANT_STORE)] = (C.MARGIN_PLANT_START, planted)


def build_vendors(ctx: Ctx) -> Table:
    table = Table(VENDOR_COLUMNS)
    vendor_ids = sorted({r["vendor_id"] for r in ctx.products.values()})
    for i, vid in enumerate(vendor_ids):
        table.add({
            "vendor_id": vid,
            "vendor_name": f"{_NAME_A[i % len(_NAME_A)]} {_NAME_B[i // len(_NAME_A) % len(_NAME_B)]}",
            "lead_time_days": ctx.rng.randint(2, 9),
            "order_weekday": ctx.rng.randint(0, 4),
            "payment_terms": "Net 30",
            "status": "Active",
        })
    return table


def build_product_costs(ctx: Ctx) -> Table:
    table = Table(PRODUCT_COST_COLUMNS)
    before_update = C.PRICE_UPDATE_DATE - timedelta(days=1)
    for pid in sorted(ctx.products):
        vendor = ctx.products[pid]["vendor_id"]
        cost = ctx.unit_cost_2026[pid]
        table.add({"product_cost_id": ctx.ids["pc"].next(), "product_id": pid, "store_id": None,
                   "vendor_id": vendor, "effective_from": C.HISTORY_START, "effective_to": before_update,
                   "unit_cost": f"{cost / C.PRICE_UPDATE_FACTOR:.4f}", "change_reason": "Baseline price list"})
        table.add({"product_cost_id": ctx.ids["pc"].next(), "product_id": pid, "store_id": None,
                   "vendor_id": vendor, "effective_from": C.PRICE_UPDATE_DATE, "effective_to": None,
                   "unit_cost": f"{cost:.4f}", "change_reason": "Annual price list"})
    for (pid, store), (start, cost) in sorted(ctx.store_cost_override.items()):
        table.add({"product_cost_id": ctx.ids["pc"].next(), "product_id": pid, "store_id": store,
                   "vendor_id": ctx.products[pid]["vendor_id"], "effective_from": start, "effective_to": None,
                   "unit_cost": f"{cost:.4f}", "change_reason": "Vendor price increase"})
    return table
```

`scripts/demo_data/pharmacy_demo_gen/staff.py`:
```python
"""Employee hourly wage (new column) — needed for labor cost / labor % (RET-LABOR-001)."""
from . import config as C
from .ctx import Ctx


def add_hourly_wage(ctx: Ctx) -> None:
    table = ctx.t["employees"]
    if "hourly_wage" not in table.columns:
        table.columns.append("hourly_wage")
    for row in table.rows:
        base = C.WAGE_BY_ROLE[row["role"]]
        row["hourly_wage"] = f"{base * (1 + ctx.rng.uniform(-0.05, 0.05)):.2f}"
```

- [ ] **Step 4: Chạy test — phải PASS**

```bash
cd scripts/demo_data && uv run pytest tests/test_catalog.py -q
```
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add scripts/demo_data/pharmacy_demo_gen/ctx.py scripts/demo_data/pharmacy_demo_gen/catalog.py \
        scripts/demo_data/pharmacy_demo_gen/staff.py scripts/demo_data/tests/test_catalog.py
git commit -m "feat(demo-data): per-unit Rx economics, vendors, dated cost history and wages"
```

### Task 3: Bán hàng front-store 12 tháng + vận hành nền

**Files:**
- Create: `scripts/demo_data/pharmacy_demo_gen/retail.py`, `scripts/demo_data/pharmacy_demo_gen/operations.py`
- Test: `scripts/demo_data/tests/test_sales.py`

**Interfaces:**
- Consumes: `Ctx`, `prepare_catalog`, `config`.
- Produces: `retail.monthly_daily_base(ctx) -> dict[tuple[str,int], float]`; `retail.generate_sales(ctx) -> list[dict]` (mỗi phần tử: `transaction_id, store_id, day, datetime, register_id, cashier, customer_id, lines[{product_id, quantity, unit_price}]`); `retail.make_transaction(ctx, store, day, history) -> dict`; `operations.generate_refunds(ctx, sales)`; `operations.generate_shifts(ctx)` (kèm cash drawer cho vai trò front-store).

Quy tắc: lịch sử (2025-08-01 → 2026-04-30) = nền giao dịch/ngày của từng cửa hàng (**tháng 5/2026 gốc**, tháng liền kề ranh giới) × `WEEKDAY_SHAPE` × `MONTH_WEIGHT` × nhiễu ±10%. Giỏ hàng hiệu chỉnh từ cửa sổ gốc: số dòng/giao dịch theo **phân bố riêng từng cửa hàng** (`lines_weights`), số lượng/dòng `LINE_QTY_WEIGHTS = (84, 5, 5, 6)` (gốc: 84% dòng qty 1), giảm giá dòng 17% (+ override ≈ 19,3% như gốc). Override theo **tỉ lệ từng cửa hàng đo trên gốc, bỏ người cài** (`override_rates`; PH-002 gốc chỉ có EMP-0023 ⇒ dùng trung bình chuỗi), người duyệt gồm Store/Assistant Manager + Shift Supervisor như gốc, % giảm {25, 35, 45, 50} (> 40% gắn cờ như gốc); void 2,4%, refund 3% (chỉ ngày < 2026-05-01, mỗi giao dịch tối đa 1 lần). Cửa sổ gốc chỉ thêm `nền_tháng × (WEEKDAY_SHAPE − 1)` vào thứ Sáu/Bảy/CN (nền tính theo từng tháng nên giữ nguyên PH-004 sụt tháng 7), không exception, không người cài sẵn.

- [ ] **Step 1: Viết test**

`scripts/demo_data/tests/test_sales.py`:
```python
import pytest

from conftest import BASE_DIR
from pharmacy_demo_gen import config as C
from pharmacy_demo_gen.catalog import prepare_catalog
from pharmacy_demo_gen.ctx import Ctx
from pharmacy_demo_gen.operations import generate_refunds, generate_shifts
from pharmacy_demo_gen.retail import generate_sales
from pharmacy_demo_gen.tables import load_base, parse_dt


@pytest.fixture(scope="module")
def staged():
    c = Ctx(load_base(BASE_DIR))
    prepare_catalog(c)
    sales = generate_sales(c)
    generate_refunds(c, sales)
    generate_shifts(c)
    return c, sales


def test_history_starts_on_first_day_and_stays_in_window(staged):
    _, sales = staged
    assert min(s["day"] for s in sales) == C.HISTORY_START
    assert max(s["day"] for s in sales) <= C.HISTORY_END


def test_window_topups_are_weekend_only_and_skip_planted_people(staged):
    _, sales = staged
    topups = [s for s in sales if s["day"] >= C.CORE_START]
    assert topups and {s["day"].weekday() for s in topups} <= {4, 5, 6}
    assert not [s for s in topups if s["cashier"] in C.PLANTED_PEOPLE]


def test_generated_transaction_totals_add_up(staged):
    c, _ = staged
    for t in c.t["transactions"].rows:
        if t["transaction_id"].startswith("TXN-1"):
            expected = float(t["subtotal"]) - float(t["discount_amount"]) + float(t["tax_amount"])
            assert abs(float(t["total_amount"]) - expected) <= 0.011, t["transaction_id"]


def test_exception_rows_are_generated_only_before_the_original_window(staged):
    c, _ = staged
    checks = [("refunds", "refund_id", "refund_datetime", "REF-1"), ("voids", "void_id", "void_datetime", "VOID-1"),
              ("discount_overrides", "override_id", "override_datetime", "OVR-1"),
              ("cash_drawers", "drawer_session_id", "opened_at", "DRW-1"),
              ("employee_shifts", "shift_id", "scheduled_start", "SHF-1")]
    for table, pk, col, prefix in checks:
        generated = [r for r in c.t[table].rows if r[pk].startswith(prefix)]
        assert generated, table
        assert all(parse_dt(r[col]).date() < C.CORE_START for r in generated), table


def test_each_generated_sale_is_refunded_at_most_once(staged):
    c, _ = staged
    originals = [r["original_transaction_id"] for r in c.t["refunds"].rows if r["refund_id"].startswith("REF-1")]
    assert len(originals) == len(set(originals))
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
cd scripts/demo_data && uv run pytest tests/test_sales.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'pharmacy_demo_gen.operations'`.

- [ ] **Step 3: Implement**

`scripts/demo_data/pharmacy_demo_gen/retail.py`:
```python
"""Front-store sales: 9 months of history + weekend top-ups inside the original May-Jul window."""
from collections import Counter
from datetime import date, timedelta

from . import config as C
from .ctx import Ctx, days, price_factor
from .tables import parse_dt


def monthly_daily_base(ctx: Ctx) -> dict[tuple[str, int], float]:
    """Average original transactions per store per day for months 5, 6, 7 (keeps the PH-004 July dip)."""
    counts = Counter()
    for r in ctx.t["transactions"].rows:
        dt = parse_dt(r["transaction_datetime"])
        if C.CORE_START <= dt.date() <= C.HISTORY_END:
            counts[(r["store_id"], dt.month)] += 1
    month_days = {5: 31, 6: 30, 7: 31}
    return {(s, m): counts[(s, m)] / month_days[m] for s in ctx.stores for m in (5, 6, 7)}


def override_rates(ctx: Ctx) -> dict[str, float]:
    """Overrides per transaction in the original window, excluding planted approvers; 0 => chain mean."""
    txns = Counter(r["store_id"] for r in ctx.t["transactions"].rows)
    overrides = Counter(r["store_id"] for r in ctx.t["discount_overrides"].rows
                        if r["approving_manager_id"] not in C.PLANTED_PEOPLE)
    rates = {s: overrides[s] / txns[s] for s in ctx.stores}
    known = [v for v in rates.values() if v > 0]
    mean = sum(known) / len(known)
    return {s: v if v > 0 else mean for s, v in rates.items()}


def lines_weights(ctx: Ctx) -> dict[str, list[int]]:
    """Per store: how many original transactions had 1..12 lines (keeps each store's basket size)."""
    store_of = {t["transaction_id"]: t["store_id"] for t in ctx.t["transactions"].rows}
    lines = Counter(li["transaction_id"] for li in ctx.t["transaction_items"].rows)
    dist = {s: [0] * 12 for s in ctx.stores}
    for txn, n in lines.items():
        dist[store_of[txn]][min(n, 12) - 1] += 1
    return dist


def generate_sales(ctx: Ctx) -> list[dict]:
    ctx.override_rate = override_rates(ctx)
    ctx.lines_weights = lines_weights(ctx)
    base_sm = monthly_daily_base(ctx)
    base_store = {s: base_sm[(s, 5)] for s in ctx.stores}   # anchor history to the adjacent month (May 2026)
    generated = []
    for day in days(C.HISTORY_START, C.CORE_START - timedelta(days=1)):
        for store in ctx.stores:
            expected = base_store[store] * C.WEEKDAY_SHAPE[day.weekday()] * C.MONTH_WEIGHT[day.month]
            for _ in range(ctx.stoch_round(expected * ctx.rng.uniform(0.9, 1.1))):
                generated.append(make_transaction(ctx, store, day, history=True))
    for day in days(C.CORE_START, C.HISTORY_END):
        for store in ctx.stores:
            extra = base_sm[(store, day.month)] * (C.WEEKDAY_SHAPE[day.weekday()] - 1.0)
            for _ in range(ctx.stoch_round(extra)):
                generated.append(make_transaction(ctx, store, day, history=False))
    return generated


def make_transaction(ctx: Ctx, store: str, day: date, history: bool) -> dict:
    exclude = frozenset() if history else C.PLANTED_PEOPLE
    txn = {"transaction_id": ctx.ids["txn"].next(), "store_id": store, "day": day,
           "datetime": ctx.at(day, 8, 20), "register_id": ctx.rng.choice(C.REGISTERS),
           "cashier": ctx.rng.choice(ctx.staff(store, C.FRONT_ROLES, day, exclude)),
           "customer_id": ctx.customer(day)}
    sums = _add_lines(ctx, txn, history)
    total = round(sums["subtotal"] - sums["discount"] + sums["tax"], 2)
    method, receipt_number, dt = ctx.weighted(C.PAYMENT_METHODS), ctx.ids["rcp"].next(), txn["datetime"]
    ctx.t["transactions"].add({
        "transaction_id": txn["transaction_id"], "receipt_number": receipt_number, "store_id": store,
        "register_id": txn["register_id"], "employee_id": txn["cashier"], "customer_id": txn["customer_id"],
        "transaction_datetime": dt, "transaction_type": "Sale", "subtotal": round(sums["subtotal"], 2),
        "discount_amount": round(sums["discount"], 2), "tax_amount": round(sums["tax"], 2),
        "total_amount": total, "payment_method": method, "item_count": sums["units"],
        "prescription_included": False,
        "loyalty_used": txn["customer_id"] is not None and ctx.rng.random() < 0.5,
        "manager_override": sums["override"], "status": "Completed"})
    ctx.t["payments"].add({"payment_id": ctx.ids["pay"].next(), "transaction_id": txn["transaction_id"],
                           "payment_method": method, "amount": total, "payment_datetime": dt, "status": "Approved"})
    ctx.t["receipts"].add({"receipt_id": ctx.ids["rct"].next(), "transaction_id": txn["transaction_id"],
                           "receipt_number": receipt_number, "print_type": "Original",
                           "printed_datetime": dt + timedelta(seconds=60), "printed_by_employee_id": txn["cashier"],
                           "register_id": txn["register_id"], "store_id": store, "print_reason": None})
    if history and ctx.rng.random() < C.VOID_RATE:
        _add_void(ctx, txn, total)
    return txn


def _add_lines(ctx: Ctx, txn: dict, history: bool) -> dict:
    store, day, dt = txn["store_id"], txn["day"], txn["datetime"]
    n_lines = ctx.rng.choices(range(1, 13), weights=ctx.lines_weights[store])[0]
    wants_override = history and ctx.rng.random() < ctx.override_rate[store]
    override_line = ctx.rng.randrange(n_lines) if wants_override else None
    approver = ctx.rng.choice(ctx.staff(store, C.APPROVER_ROLES, day)) if wants_override else None
    sums = {"subtotal": 0.0, "discount": 0.0, "tax": 0.0, "units": 0, "override": override_line is not None}
    txn["lines"] = []
    for i in range(n_lines):
        pid = ctx.rng.choice(ctx.retail_ids)
        qty = ctx.rng.choices([1, 2, 3, 4], weights=C.LINE_QTY_WEIGHTS)[0]
        price = round(float(ctx.products[pid]["retail_price"]) * price_factor(day), 2)
        gross = round(qty * price, 2)
        if i == override_line:
            discount = _add_override(ctx, txn, pid, gross, approver)
        elif ctx.rng.random() < C.LINE_DISCOUNT_SHARE:
            discount = round(gross * ctx.rng.choice([0.05, 0.10, 0.20]), 2)
        else:
            discount = 0.0
        line_total = round(gross - discount, 2)
        tax = round(line_total * C.TAX_RATE, 2)
        ctx.t["transaction_items"].add({
            "transaction_item_id": ctx.ids["li"].next(), "transaction_id": txn["transaction_id"],
            "product_id": pid, "quantity": qty, "unit_price": price,
            "unit_cost": round(ctx.unit_cost(pid, store, day), 2), "discount_amount": discount,
            "tax_amount": tax, "line_total": line_total, "override_applied": i == override_line,
            "override_employee_id": approver if i == override_line else None,
            "department": ctx.products[pid]["category"]})
        ctx.t["inventory_movements"].add({
            "movement_id": ctx.ids["mov"].next(), "store_id": store, "product_id": pid, "movement_datetime": dt,
            "movement_type": "SALE", "quantity_change": -qty, "reference_id": txn["transaction_id"],
            "employee_id": txn["cashier"]})
        txn["lines"].append({"product_id": pid, "quantity": qty, "unit_price": price})
        sums["subtotal"] += gross
        sums["discount"] += discount
        sums["tax"] += tax
        sums["units"] += qty
    return sums


def _add_override(ctx: Ctx, txn: dict, pid: str, gross: float, approver: str) -> float:
    pct = ctx.rng.choice(C.OVERRIDE_PERCENTS)
    discount = round(gross * pct / 100, 2)
    ctx.t["discount_overrides"].add({
        "override_id": ctx.ids["ovr"].next(), "transaction_id": txn["transaction_id"],
        "store_id": txn["store_id"], "employee_id": txn["cashier"], "approving_manager_id": approver,
        "product_id": pid, "override_datetime": txn["datetime"], "original_amount": gross,
        "adjusted_amount": round(gross - discount, 2), "discount_amount": discount,
        "discount_percent": f"{pct:.1f}", "override_reason": "Manager price override",
        "approval_method": "Manager PIN", "flagged": pct > 40,
        "flag_reason": "Discount exceeds 40%" if pct > 40 else None})
    return discount


def _add_void(ctx: Ctx, txn: dict, total: float) -> None:
    void_dt = txn["datetime"] + timedelta(minutes=ctx.rng.randint(1, 30))
    amount = round(total * ctx.rng.uniform(0.2, 1.0), 2)
    late_high = void_dt.hour >= 20 and amount >= 100
    ctx.t["voids"].add({
        "void_id": ctx.ids["void"].next(), "transaction_id": txn["transaction_id"], "store_id": txn["store_id"],
        "register_id": txn["register_id"], "employee_id": txn["cashier"],
        "approving_manager_id": ctx.rng.choice(ctx.staff(txn["store_id"], C.MANAGER_ROLES, txn["day"])),
        "void_datetime": void_dt, "void_amount": amount, "void_reason": ctx.rng.choice(C.VOID_REASONS),
        "stage": ctx.rng.choice(C.VOID_STAGES), "flagged": late_high,
        "flag_reason": "Late high-value void" if late_high else None})
```

`scripts/demo_data/pharmacy_demo_gen/operations.py`:
```python
"""History-only background operations: refunds, shifts and cash drawer sessions (normal rates, no plants)."""
from datetime import datetime, time, timedelta

from . import config as C
from .ctx import Ctx, days


def generate_refunds(ctx: Ctx, sales: list[dict]) -> None:
    """At most one refund per generated history sale, always dated before CORE_START."""
    for txn in sales:
        if txn["day"] >= C.CORE_START or ctx.rng.random() >= C.REFUND_RATE:
            continue
        refund_day = txn["day"] + timedelta(days=ctx.rng.randint(0, 30))
        if refund_day >= C.CORE_START:
            continue
        _add_refund(ctx, txn, refund_day)


def _add_refund(ctx: Ctx, txn: dict, refund_day) -> None:
    store = txn["store_id"]
    line = ctx.rng.choice(txn["lines"])
    qty = ctx.rng.randint(1, line["quantity"])
    amount = round(qty * line["unit_price"], 2)
    refund_dt = max(ctx.at(refund_day, 9, 20), txn["datetime"] + timedelta(hours=1))
    has_receipt = ctx.rng.random() < 0.85
    late, high = refund_dt.hour >= 20, amount >= 100
    reasons = [r for r, on in (("No receipt", not has_receipt), ("After 8 PM", late), ("High value", high)) if on]
    risk = 10 + 40 * (not has_receipt) + 20 * late + 20 * high
    returned = ctx.rng.random() < 0.85
    employee = ctx.rng.choice(ctx.staff(store, C.FRONT_ROLES, refund_day))
    refund_id = ctx.ids["ref"].next()
    ctx.t["refunds"].add({
        "refund_id": refund_id, "refund_transaction_id": ctx.ids["rtx"].next(),
        "original_transaction_id": txn["transaction_id"], "store_id": store, "register_id": txn["register_id"],
        "employee_id": employee, "approving_manager_id": ctx.rng.choice(ctx.staff(store, C.MANAGER_ROLES, refund_day)),
        "customer_id": txn["customer_id"], "refund_datetime": refund_dt, "refund_amount": amount,
        "refund_method": ctx.weighted(C.REFUND_METHODS),
        "refund_reason": "No Receipt" if not has_receipt else ctx.rng.choice(C.REFUND_REASONS),
        "original_receipt_present": has_receipt, "days_after_purchase": (refund_day - txn["day"]).days,
        "manager_override": high, "risk_score": risk, "flagged": risk >= 50,
        "flag_reason": "; ".join(reasons) if risk >= 50 else None})
    ctx.t["refund_items"].add({
        "refund_item_id": ctx.ids["rli"].next(), "refund_id": refund_id, "product_id": line["product_id"],
        "quantity": qty, "original_unit_price": line["unit_price"], "refunded_amount": amount,
        "returned_to_inventory": returned, "item_condition": "Resellable" if returned else "Damaged",
        "disposal_required": not returned})
    if returned:
        ctx.t["inventory_movements"].add({
            "movement_id": ctx.ids["mov"].next(), "store_id": store, "product_id": line["product_id"],
            "movement_datetime": refund_dt, "movement_type": "REFUND_RETURN", "quantity_change": qty,
            "reference_id": refund_id, "employee_id": employee})


def generate_shifts(ctx: Ctx) -> None:
    for day in days(C.HISTORY_START, C.CORE_START - timedelta(days=1)):
        for store in ctx.stores:
            managers = ctx.staff(store, ("Store Manager",), day)
            staff = ctx.staff(store, tuple(C.WAGE_BY_ROLE), day)
            for _ in range(ctx.stoch_round(C.SHIFTS_PER_STORE_DAY * ctx.rng.uniform(0.8, 1.2))):
                _add_shift(ctx, store, day, ctx.rng.choice(staff), managers[0])


def _add_shift(ctx: Ctx, store, day, employee, manager) -> None:
    start = datetime.combine(day, time(ctx.rng.choice([8, 10, 14])))
    end = start + timedelta(hours=8)
    late = ctx.rng.randint(1, 15) if ctx.rng.random() < 0.1 else 0
    early = ctx.rng.randint(0, 15)
    overtime = ctx.rng.choices([0.0, 0.25, 0.5], weights=[30, 50, 20])[0]
    clock_in = start + timedelta(minutes=late)
    clock_out = end - timedelta(minutes=early) + timedelta(hours=overtime)
    role = ctx.employees[employee]["role"]
    ctx.t["employee_shifts"].add({
        "shift_id": ctx.ids["shf"].next(), "employee_id": employee, "store_id": store,
        "scheduled_start": start, "scheduled_end": end, "actual_clock_in": clock_in, "actual_clock_out": clock_out,
        "regular_hours": "8", "overtime_hours": f"{overtime:.2f}", "late_minutes": late,
        "early_departure_minutes": early, "role_during_shift": role, "manager_on_duty": manager})
    if role in C.FRONT_ROLES:
        _add_drawer(ctx, store, day, employee, clock_in, clock_out)


def _add_drawer(ctx: Ctx, store, day, employee, opened, closed) -> None:
    sales = round(ctx.rng.uniform(600, 1500), 2)
    refunds = round(ctx.rng.uniform(0, 120), 2)
    expected = round(200.0 + sales - refunds, 2)
    variance = round(ctx.rng.gauss(0, 2.5), 2)
    ctx.t["cash_drawers"].add({
        "drawer_session_id": ctx.ids["drw"].next(), "store_id": store, "register_id": ctx.rng.choice(C.REGISTERS),
        "employee_id": employee, "opened_at": opened, "closed_at": closed, "opening_cash": "200.0",
        "expected_cash": expected, "counted_cash": round(expected + variance, 2), "cash_variance": variance,
        "no_sale_open_count": ctx.rng.choices([0, 1, 2, 3, 4], weights=[25, 35, 25, 10, 5])[0],
        "cash_refund_total": refunds, "cash_sales_total": sales,
        "approving_manager_id": ctx.rng.choice(ctx.staff(store, C.MANAGER_ROLES, day)),
        "flagged": False, "flag_reason": None})
```

- [ ] **Step 4: Chạy test — phải PASS**

```bash
cd scripts/demo_data && uv run pytest tests/test_sales.py -q
```
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add scripts/demo_data/pharmacy_demo_gen/retail.py scripts/demo_data/pharmacy_demo_gen/operations.py \
        scripts/demo_data/tests/test_sales.py
git commit -m "feat(demo-data): 12-month front-store history with weekly/monthly seasonality"
```

### Task 4: Rx — volume 12 tháng, claim, `acquisition_cost`, margin plant

**Files:**
- Create: `scripts/demo_data/pharmacy_demo_gen/rx.py`
- Test: `scripts/demo_data/tests/test_rx.py`

**Interfaces:**
- Consumes: `Ctx` (đã `prepare_catalog`: `heavy_rx`, `rx_revenue_per_unit`, `store_cost_override`), `config.RX_*`.
- Produces: `rx.generate_prescriptions(ctx)` (thêm prescription + insurance_claim; cửa sổ gốc chỉ bù tới mục tiêu ngày); `rx.add_acquisition_cost(ctx, original_ids: set[str])` (điền cột mới cho mọi dòng — caller phải `columns.append("acquisition_cost")` trước khi sinh).

Quy tắc: mục tiêu `RX_BASE_PER_STORE_DAY (22) × RX_WEEKDAY_SHAPE × MONTH_WEIGHT × nhiễu ±10%`; 5 thuốc plant có trọng số 20 (chiếm ≥ 25% giá vốn Rx của PH-003). Giá vốn đơn sinh = `quantity × unit_cost(ngày, cửa hàng)`; đơn gốc = `(insurance_payment + customer_payment) × 0.80 × hệ số plant` vì số lượng gốc không tương quan với giá (nếu dùng `quantity × unit_cost` cho đơn gốc thì nhiễu làm margin các cửa hàng khác lệch tới ±18%, đã đo). Reimbursement không phụ thuộc giá vốn ⇒ "đứng yên". PH-004 từ chối 15,5% từ 2026-05-01, mặc định 5%.

- [ ] **Step 1: Viết test**

`scripts/demo_data/tests/test_rx.py`:
```python
from collections import Counter
from datetime import date

import pytest

from conftest import BASE_DIR
from pharmacy_demo_gen import config as C
from pharmacy_demo_gen.catalog import prepare_catalog
from pharmacy_demo_gen.ctx import Ctx
from pharmacy_demo_gen.rx import add_acquisition_cost, generate_prescriptions
from pharmacy_demo_gen.tables import load_base, parse_dt


@pytest.fixture(scope="module")
def staged():
    c = Ctx(load_base(BASE_DIR))
    prepare_catalog(c)
    original = {r["prescription_id"] for r in c.t["prescriptions"].rows}
    c.t["prescriptions"].columns.append("acquisition_cost")
    generate_prescriptions(c)
    add_acquisition_cost(c, original)
    return c, original


def test_every_store_day_has_rx_volume(staged):
    c, _ = staged
    per_day = Counter((r["store_id"], parse_dt(r["received_datetime"]).date()) for r in c.t["prescriptions"].rows)
    assert len(per_day) == 5 * 365
    assert min(per_day.values()) >= 8


def test_ph004_rejection_plant_only_from_may(staged):
    c, _ = staged
    total, rejected = Counter(), Counter()
    for claim in c.t["insurance_claims"].rows:
        key = (claim["store_id"], parse_dt(claim["submitted_datetime"]).date() >= C.CORE_START)
        total[key] += 1
        rejected[key] += claim["claim_status"] == "Rejected"
    assert 0.13 <= rejected[("PH-004", True)] / total[("PH-004", True)] <= 0.18
    assert rejected[("PH-004", False)] / total[("PH-004", False)] <= 0.07


def test_original_fill_cost_follows_paid_amount_and_plant(staged):
    c, original = staged
    for r in c.t["prescriptions"].rows:
        if r["prescription_id"] not in original:
            continue
        paid = float(r["insurance_payment"]) + float(r["customer_payment"])
        planted = r["store_id"] == "PH-003" and r["product_id"] in c.heavy_rx \
            and parse_dt(r["filled_datetime"]).date() >= date(2026, 7, 18)
        factor = 1.08 if planted else 1.0
        assert float(r["acquisition_cost"]) == pytest.approx(paid * 0.80 * factor, abs=0.011)


def test_generated_fill_cost_is_quantity_times_dated_unit_cost(staged):
    c, original = staged
    for r in c.t["prescriptions"].rows[-500:]:
        assert r["prescription_id"] not in original
        day = parse_dt(r["filled_datetime"]).date()
        expected = int(r["quantity"]) * c.unit_cost(r["product_id"], r["store_id"], day)
        assert float(r["acquisition_cost"]) == pytest.approx(expected, abs=0.011)
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
cd scripts/demo_data && uv run pytest tests/test_rx.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'pharmacy_demo_gen.rx'`.

- [ ] **Step 3: Implement**

`scripts/demo_data/pharmacy_demo_gen/rx.py`:
```python
"""Prescriptions + insurance claims: full history, May-Jul volume top-up, acquisition_cost column."""
from collections import Counter
from datetime import timedelta

from . import config as C
from .ctx import Ctx, days, price_factor
from .tables import parse_dt


def generate_prescriptions(ctx: Ctx) -> None:
    existing = Counter((r["store_id"], parse_dt(r["received_datetime"]).date())
                       for r in ctx.t["prescriptions"].rows)
    weights = [C.HEAVY_DRUG_WEIGHT if p in ctx.heavy_rx else 1 for p in ctx.rx_ids]
    for day in days(C.HISTORY_START, C.HISTORY_END):
        for store in ctx.stores:
            target = C.RX_BASE_PER_STORE_DAY * C.RX_WEEKDAY_SHAPE[day.weekday()] * C.MONTH_WEIGHT[day.month]
            count = ctx.stoch_round(target * ctx.rng.uniform(0.9, 1.1))
            if day >= C.CORE_START:
                count = max(0, count - existing[(store, day)])
            for _ in range(count):
                pid = ctx.rng.choices(ctx.rx_ids, weights=weights)[0]
                _add_fill(ctx, store, day, pid)


def _reject_rate(store: str, day) -> float:
    plant = C.RX_REJECT_PLANT.get(store)
    if plant and day >= plant[0]:
        return plant[1]
    return C.RX_REJECT_RATE


def _add_fill(ctx: Ctx, store: str, day, pid: str) -> None:
    received = ctx.at(day, 8, 19)
    turnaround = ctx.rng.randint(10, 60)
    filled = received + timedelta(minutes=turnaround)
    qty = ctx.rng.choice((30, 30, 30, 30, 60, 90))
    pf = price_factor(day)
    paid = round(qty * ctx.rx_revenue_per_unit[pid] * pf * ctx.rng.uniform(0.98, 1.02), 2)
    copay = round(paid * ctx.rng.uniform(0.05, 0.15), 2)
    cash_price = round(qty * float(ctx.products[pid]["retail_price"]) * pf, 2)
    rejected = ctx.rng.random() < _reject_rate(store, day)
    approved = 0.0 if rejected else round(paid - copay, 2)
    status = ctx.weighted(C.RX_STATUSES)
    rx_id = ctx.ids["rx"].next()
    ctx.t["prescriptions"].add({
        "prescription_id": rx_id, "prescription_number": ctx.ids["rxn"].next(), "store_id": store,
        "pharmacist_employee_id": ctx.rng.choice(ctx.staff(store, ("Pharmacist",), day)),
        "technician_employee_id": ctx.rng.choice(ctx.staff(store, ("Pharmacy Technician",), day)),
        "customer_id": ctx.customer(day, allow_none=False), "product_id": pid,
        "received_datetime": received, "filled_datetime": filled,
        "picked_up_datetime": filled + timedelta(hours=ctx.rng.randint(2, 48)) if status == "Picked Up" else None,
        "quantity": qty, "refill_number": ctx.rng.randint(0, 5), "cash_price": cash_price,
        "customer_payment": copay, "insurance_payment": approved, "status": status,
        "turnaround_minutes": turnaround, "reversal_flag": status == "Reversed", "exception_reason": None,
        "acquisition_cost": None})
    ctx.t["insurance_claims"].add({
        "claim_id": ctx.ids["clm"].next(), "prescription_id": rx_id, "store_id": store,
        "payer_name": ctx.weighted(C.PAYERS), "submitted_datetime": received, "claim_amount": cash_price,
        "approved_amount": approved, "customer_amount": copay,
        "claim_status": "Rejected" if rejected else "Approved",
        "rejection_code": ctx.rng.choice(C.REJECTION_CODES) if rejected else None,
        "resubmission_count": ctx.rng.randint(0, 2) if rejected else 0,
        "resolved_datetime": received + timedelta(minutes=ctx.rng.randint(5, 60))})


def add_acquisition_cost(ctx: Ctx, original_ids: set[str]) -> None:
    """New column. Generated fills: quantity x unit cost effective at fill date + store.
    Original fills: their quantity is unrelated to their price, so cost = paid amount x RX_COST_TO_REVENUE,
    scaled by the same dated store cost factor (keeps the margin plant visible and low-noise)."""
    for row in ctx.t["prescriptions"].rows:
        fill_day = parse_dt(row["filled_datetime"] or row["received_datetime"]).date()
        unit_cost = ctx.unit_cost(row["product_id"], row["store_id"], fill_day)
        if row["prescription_id"] in original_ids:
            factor = unit_cost / (ctx.unit_cost_2026[row["product_id"]] * price_factor(fill_day))
            paid = float(row["insurance_payment"]) + float(row["customer_payment"])
            cost = paid * C.RX_COST_TO_REVENUE * factor
        else:
            cost = int(row["quantity"]) * unit_cost
        row["acquisition_cost"] = f"{cost:.2f}"
```

- [ ] **Step 4: Chạy test — phải PASS**

```bash
cd scripts/demo_data && uv run pytest tests/test_rx.py -q
```
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add scripts/demo_data/pharmacy_demo_gen/rx.py scripts/demo_data/tests/test_rx.py
git commit -m "feat(demo-data): 12-month Rx volume, acquisition cost and PH-003 margin plant"
```

### Task 5: Tồn kho — nhập hàng từ vendor, PO, lead time, snapshot hằng tuần

**Files:**
- Create: `scripts/demo_data/pharmacy_demo_gen/inventory.py`
- Test: `scripts/demo_data/tests/test_inventory.py`

**Interfaces:**
- Consumes: `Ctx`, bảng `vendors` (`build_vendors`), `inventory_movements`/`inventory_adjustments`/`inventory_snapshots` hiện có trong `ctx.t`.
- Produces: `inventory.simulate_inventory(ctx, vendors: Table) -> tuple[Table, Table]` = (`purchase_orders`, `purchase_order_lines`); thêm vào `ctx.t`: movement `RECEIPT` (`reference_id = po_id`), snapshot thứ Sáu `SNP-1…`, adjustment kiểm kê lịch sử `ADJ-1…`.

Thuật toán: với từng (cửa hàng, sản phẩm front-store), bắt đầu từ `counted_quantity` của snapshot gốc 2026-07-31 (hoặc `2×reorder_point + rnd` nếu không có), lùi từng ngày trừ biến động; khi tồn quá khứ vượt `4×reorder_point` thì chèn một lần nhập hàng (hàng về ngày đó, PO đặt trước `lead_time_days` (+0/1) ngày). Thứ Sáu trước 2026-07-01 (`COUNT_VARIANCE_END`, gồm cả tháng 5–6 gốc vốn không có adjustment): 18% dòng có chênh lệch kiểm kê −2..+1 (sinh adjustment; mức này khớp shrink không-plant của tháng 7 gốc); thứ Sáu tháng 7: chênh lệch 0 — tháng 7 chỉ có kiểm kê gốc (chứa plant PH-005). Rx không mô phỏng (dữ liệu gốc không có movement cho đơn thuốc).

- [ ] **Step 1: Viết test**

`scripts/demo_data/tests/test_inventory.py`:
```python
from datetime import date

import pytest

from conftest import BASE_DIR
from pharmacy_demo_gen import config as C
from pharmacy_demo_gen.catalog import build_vendors, prepare_catalog
from pharmacy_demo_gen.ctx import Ctx
from pharmacy_demo_gen.inventory import simulate_inventory
from pharmacy_demo_gen.tables import load_base, parse_dt


@pytest.fixture(scope="module")
def staged():
    c = Ctx(load_base(BASE_DIR))
    prepare_catalog(c)
    vendors = build_vendors(c)
    orders, lines = simulate_inventory(c, vendors)
    return c, vendors, orders, lines


def test_receipt_movements_reference_purchase_orders(staged):
    c, _, orders, lines = staged
    po_ids = {o["po_id"] for o in orders.rows}
    receipts = [m for m in c.t["inventory_movements"].rows if m["movement_type"] == "RECEIPT"]
    assert len(receipts) == len(lines.rows) > 0
    assert all(m["reference_id"] in po_ids and int(m["quantity_change"]) > 0 for m in receipts)


def test_purchase_order_lead_time_matches_vendor(staged):
    _, vendors, orders, _ = staged
    lead = {v["vendor_id"]: int(v["lead_time_days"]) for v in vendors.rows}
    for o in orders.rows:
        days = (parse_dt(o["received_datetime"]).date() - date.fromisoformat(o["order_date"])).days
        assert days in (lead[o["vendor_id"]], lead[o["vendor_id"]] + 1)


def test_weekly_snapshots_on_fridays_with_variances_until_june_only(staged):
    c, _, _, _ = staged
    generated = [s for s in c.t["inventory_snapshots"].rows if s["snapshot_id"].startswith("SNP-1")]
    assert len(generated) == 52 * 1500
    assert all(date.fromisoformat(s["snapshot_date"]).weekday() == 4 for s in generated)
    july = [s for s in generated if date.fromisoformat(s["snapshot_date"]) >= C.COUNT_VARIANCE_END]
    assert july and all(s["variance_quantity"] == "0" for s in july)
    may_june = [s for s in generated
                if C.CORE_START <= date.fromisoformat(s["snapshot_date"]) < C.COUNT_VARIANCE_END]
    share = sum(s["variance_quantity"] != "0" for s in may_june) / len(may_june)
    assert 0.12 <= share <= 0.24, share


def test_history_count_adjustments_mirror_snapshot_variances(staged):
    c, _, _, _ = staged
    variances = [s for s in c.t["inventory_snapshots"].rows
                 if s["snapshot_id"].startswith("SNP-1") and s["variance_quantity"] != "0"]
    adjustments = [a for a in c.t["inventory_adjustments"].rows if a["adjustment_id"].startswith("ADJ-1")]
    assert len(adjustments) == len(variances) > 0
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
cd scripts/demo_data && uv run pytest tests/test_inventory.py -q
```
Expected: FAIL — `ModuleNotFoundError: No module named 'pharmacy_demo_gen.inventory'`.

- [ ] **Step 3: Implement**

`scripts/demo_data/pharmacy_demo_gen/inventory.py`:
```python
"""Stock simulation run BACKWARD from the original 2026-07-31 count, so the original snapshot stays the anchor.
Produces vendor receipts (RECEIPT movements + purchase orders), weekly Friday snapshots and count
adjustments before July 2026 (July keeps only the original count, which carries the PH-005 shrink plant).
Rx stock is not simulated (prescriptions never produced movements in the original data)."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from . import config as C
from .ctx import Ctx
from .tables import Table, parse_dt

PO_COLUMNS = ["po_id", "store_id", "vendor_id", "order_date", "expected_date", "received_datetime", "status"]
PO_LINE_COLUMNS = ["po_line_id", "po_id", "product_id", "quantity", "unit_cost"]


def _daily_deltas(ctx: Ctx) -> dict[tuple[str, str], dict[date, int]]:
    deltas: dict[tuple[str, str], dict[date, int]] = defaultdict(lambda: defaultdict(int))
    for m in ctx.t["inventory_movements"].rows:
        deltas[(m["store_id"], m["product_id"])][parse_dt(m["movement_datetime"]).date()] += int(m["quantity_change"])
    for a in ctx.t["inventory_adjustments"].rows:
        day = parse_dt(a["adjustment_datetime"]).date()
        deltas[(a["store_id"], a["product_id"])][day] += int(a["adjustment_quantity"])
    return deltas


def _snapshot_status(system: int, counted: int, value: float) -> str:
    if counted <= 0:
        return "Out of Stock"
    if counted == system:
        return "Matched"
    if abs(counted - system) >= 5 or abs(value) >= 100:
        return "Major Variance"
    return "Minor Variance"


def simulate_inventory(ctx: Ctx, vendors: Table) -> tuple[Table, Table]:
    deltas = _daily_deltas(ctx)
    anchors = {(s["store_id"], s["product_id"]): int(s["counted_quantity"]) for s in ctx.t["inventory_snapshots"].rows}
    snapshots, adjustments, receipts = [], [], []
    for store in ctx.stores:
        for pid in ctx.retail_ids:
            rp = int(ctx.products[pid]["reorder_point"])
            key = (store, pid)
            stock = anchors.get(key, rp * 2 + ctx.rng.randint(0, rp))
            day = C.HISTORY_END
            while day >= C.HISTORY_START:
                if key in anchors and day.weekday() == 4 and day < C.HISTORY_END:
                    stock = _weekly_count(ctx, key, day, stock, snapshots, adjustments)
                stock -= deltas[key].get(day, 0)
                if stock > 4 * rp:
                    qty = stock - ctx.rng.randint(max(1, rp // 4), rp)
                    receipts.append((day, store, ctx.products[pid]["vendor_id"], pid, qty))
                    stock -= qty
                day -= timedelta(days=1)
    _emit_snapshots(ctx, snapshots)
    _emit_adjustments(ctx, adjustments)
    return _emit_receipts(ctx, vendors, receipts)


def _weekly_count(ctx: Ctx, key, day, stock, snapshots, adjustments) -> int:
    """`stock` is end-of-day book after the count; returns book before the count adjustment."""
    variance = 0
    if day < C.COUNT_VARIANCE_END and ctx.rng.random() < C.SNAPSHOT_VARIANCE_SHARE:
        variance = ctx.rng.choice([-2, -1, -1, 1])
    snapshots.append((day, key[0], key[1], stock - variance, stock))
    if variance:
        adjustments.append((day, key[0], key[1], stock - variance, variance))
    return stock - variance


def _emit_snapshots(ctx: Ctx, snapshots) -> None:
    for day, store, pid, system, counted in sorted(snapshots):
        value = round((counted - system) * ctx.unit_cost(pid, store, day), 2)
        ctx.t["inventory_snapshots"].add({
            "snapshot_id": ctx.ids["snp"].next(), "snapshot_date": day, "store_id": store, "product_id": pid,
            "system_quantity": system, "counted_quantity": counted, "variance_quantity": counted - system,
            "variance_value": value, "expired_quantity": 0, "status": _snapshot_status(system, counted, value)})


def _emit_adjustments(ctx: Ctx, adjustments) -> None:
    for day, store, pid, before, variance in sorted(adjustments):
        kind = "Shrinkage" if variance < 0 else "Cycle Count"
        counters = ctx.staff(store, ("Inventory Associate",), day) or ctx.staff(store, ("Store Manager",), day)
        ctx.t["inventory_adjustments"].add({
            "adjustment_id": ctx.ids["adj"].next(), "store_id": store, "product_id": pid,
            "employee_id": ctx.rng.choice(counters),
            "approving_manager_id": ctx.rng.choice(ctx.staff(store, C.MANAGER_ROLES, day)),
            "adjustment_datetime": datetime.combine(day, time(16)), "adjustment_type": kind,
            "quantity_before": before, "adjustment_quantity": variance, "quantity_after": before + variance,
            "adjustment_value": round(variance * ctx.unit_cost(pid, store, day), 2), "reason": kind,
            "reference_document": None, "flagged": False, "flag_reason": None})


def _emit_receipts(ctx: Ctx, vendors: Table, receipts) -> tuple[Table, Table]:
    lead = {v["vendor_id"]: int(v["lead_time_days"]) for v in vendors.rows}
    orders, lines = Table(PO_COLUMNS), Table(PO_LINE_COLUMNS)
    grouped = defaultdict(list)
    for day, store, vendor, pid, qty in receipts:
        grouped[(day, store, vendor)].append((pid, qty))
    for (day, store, vendor), items in sorted(grouped.items()):
        order_date = day - timedelta(days=lead[vendor] + ctx.rng.randint(0, 1))
        received = datetime.combine(day, time(9)) + timedelta(minutes=ctx.rng.randint(0, 120))
        receiver = ctx.staff(store, ("Inventory Associate",), day) or ctx.staff(store, ("Store Manager",), day)
        po_id = ctx.ids["po"].next()
        orders.add({"po_id": po_id, "store_id": store, "vendor_id": vendor, "order_date": order_date,
                    "expected_date": order_date + timedelta(days=lead[vendor]), "received_datetime": received,
                    "status": "Received"})
        employee = ctx.rng.choice(receiver)
        for pid, qty in sorted(items):
            lines.add({"po_line_id": ctx.ids["pol"].next(), "po_id": po_id, "product_id": pid, "quantity": qty,
                       "unit_cost": f"{ctx.unit_cost(pid, store, order_date):.4f}"})
            ctx.t["inventory_movements"].add({
                "movement_id": ctx.ids["mov"].next(), "store_id": store, "product_id": pid,
                "movement_datetime": received, "movement_type": "RECEIPT", "quantity_change": qty,
                "reference_id": po_id, "employee_id": employee})
    return orders, lines
```

- [ ] **Step 4: Chạy test — phải PASS**

```bash
cd scripts/demo_data && uv run pytest tests/test_inventory.py -q
```
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add scripts/demo_data/pharmacy_demo_gen/inventory.py scripts/demo_data/tests/test_inventory.py
git commit -m "feat(demo-data): vendor receipts, purchase orders and weekly inventory snapshots"
```

### Task 6: Targets + điều phối + CLI + acceptance test trên output

**Files:**
- Create: `scripts/demo_data/pharmacy_demo_gen/targets.py`, `scripts/demo_data/pharmacy_demo_gen/generate.py`, `scripts/demo_data/pharmacy_demo_gen/__main__.py`
- Test: `scripts/demo_data/tests/test_integrity.py`, `test_preserve.py`, `test_window.py`, `test_plants.py`, `test_continuity.py`, `test_margin_plant.py`, `test_targets.py` (cùng thư mục `scripts/demo_data/tests/`)

**Interfaces:**
- Consumes: mọi module Task 1–5.
- Produces: `generate.generate(base_dir: Path, out_dir: Path, seed: int = SEED) -> dict[str, Table]` (ghi 25 CSV + `targets.xlsx` + `DATA_SUMMARY.txt`); `generate.write_summary(path, tables, ctx, seed)`; `targets.HEADER = ("Store ID", "Metric Key", "Period", "Target Value")`, `targets.retail_actuals(tables)` (gm % thang 0–100), `targets.build_targets(tables) -> list[dict]` (key = HEADER, 1 dòng/store×tháng×metric), `targets.write_targets_xlsx(path, rows)`; CLI `python -m pharmacy_demo_gen --base <dir> --out <dir> [--seed N]` (từ chối khi `--base` = `--out`).

`targets.xlsx` theo hợp đồng master (Global Constraints): **đúng 1 sheet** (`targets`), **định dạng dài**, cột đúng `Store ID | Metric Key | Period | Target Value`; `Metric Key` ∈ {`net_sales`, `gross_margin_pct`}; `Period` = ô ngày Excel thật, ngày đầu tháng; `gross_margin_pct` là số thường thang **0–100** (ví dụ `41.9`, không phải `0.419`, không định dạng `%`). Mỗi (cửa hàng × tháng × metric) đúng 1 dòng: 5 × 17 (2025-08 → 2026-12) × 2 = 170 dòng. Net sales = Σ`line_total` không gồm thuế và dòng Rx. Tháng đã có số: target = thực tế × 0,98 (làm tròn trăm) ⇒ đạt; **riêng PH-004 2026-07 = mức tháng 6 ⇒ hụt** (phục vụ RET-MARGIN-001/RET-SALES-001 so target); tháng tương lai = cùng tháng năm trước × 1,03. Margin % target = thực tế − 0,5 điểm (luôn đạt).

Ngưỡng trong `test_plants.py` là **proxy** (rule thật ở Plan D): mỗi plant phải vượt ≥ 3× trung bình đồng nghiệp (request yêu cầu 2,5×) và có kiểm tra âm trên lịch sử. Ngoại lệ có lý do: so tháng 7/tháng 6 các cửa hàng khác cho phép ±25% vì dữ liệu gốc PH-003 đã +18%.

- [ ] **Step 1: Viết acceptance test**

`scripts/demo_data/tests/test_integrity.py`:
```python
"""Every CSV must load into pharmacy_demo with its PK/FK constraints (schema/base.sql + schema/extension.sql)."""
import re

from helpers import FOREIGN_KEYS, PRIMARY_KEYS


def test_primary_keys_are_unique(out):
    for table, pk in PRIMARY_KEYS.items():
        values = [r[pk] for r in out.rows(table)]
        assert len(values) == len(set(values)), f"duplicate {table}.{pk}"
        assert all(values), f"empty {table}.{pk}"


def test_foreign_keys_resolve(out):
    for table, column, ref in FOREIGN_KEYS:
        keys = {r[PRIMARY_KEYS[ref]] for r in out.rows(ref)}
        dangling = {r[column] for r in out.rows(table) if r[column] and r[column] not in keys}
        assert not dangling, f"{table}.{column} -> {ref}: {sorted(dangling)[:5]}"


def test_write_test_leftovers_are_gone(out):
    assert all(re.fullmatch(r"TXN-\d{7}", r["transaction_id"]) for r in out.rows("transactions"))
    assert "EMP-9999" not in {r["employee_id"] for r in out.rows("employees")}
    assert "EMP-9999" not in {r["printed_by_employee_id"] for r in out.rows("receipts")}
    assert not {"CUS-99991", "CUS-99992", "CUS-99993"} & {r["customer_id"] for r in out.rows("customers")}


def test_new_columns_are_appended_last(out, base):
    assert out.columns("employees") == base.columns("employees") + ["hourly_wage"]
    assert out.columns("prescriptions") == base.columns("prescriptions") + ["acquisition_cost"]
    assert all(float(r["hourly_wage"]) > 0 for r in out.rows("employees"))
```

`scripts/demo_data/tests/test_preserve.py`:
```python
"""The original May-Jul 2026 package is the verified ground truth: its rows must survive unchanged."""
from helpers import PRIMARY_KEYS, is_generated

# Only deliberate value changes to original rows (see plan "Thay đổi trên dữ liệu gốc").
REBASED_PRODUCT_COLUMNS = {"unit_cost", "retail_price", "gross_margin_percent"}
DROPPED = {"RCT-0005317", "RCT-0005319", "RCT-0005328"}  # write-test leftovers in receipts.csv


def test_original_rows_are_kept_verbatim(out, base):
    for table, pk in PRIMARY_KEYS.items():
        if table in ("vendors", "product_costs", "purchase_orders", "purchase_order_lines"):
            continue
        generated = {r[pk]: r for r in out.rows(table)}
        for original in base.rows(table):
            if original[pk] in DROPPED:
                assert original[pk] not in generated
                continue
            row = generated.get(original[pk])
            assert row is not None, f"{table} lost {original[pk]}"
            rebased = table == "products" and original["prescription_required"] == "True"
            skip = REBASED_PRODUCT_COLUMNS if rebased else set()
            changed = {c for c in base.columns(table) if c not in skip and row[c] != original[c]}
            assert not changed, f"{table} {original[pk]} changed {sorted(changed)}"


def test_rx_products_are_priced_per_dispensing_unit(out):
    rx = [p for p in out.rows("products") if p["prescription_required"] == "True"]
    assert len(rx) == 74
    assert all(0 < float(p["unit_cost"]) < 5 for p in rx), "Rx unit_cost must be per unit, not per package"


def test_generated_rx_cost_is_about_80_percent_of_paid(out):
    claims = {c["prescription_id"]: c for c in out.rows("insurance_claims")}
    paid = cost = 0.0
    for rx in out.rows("prescriptions"):
        claim = claims[rx["prescription_id"]]
        if is_generated(rx["prescription_id"]) and claim["claim_status"] == "Approved" \
                and rx["store_id"] != "PH-003":
            paid += float(claim["approved_amount"]) + float(claim["customer_amount"])
            cost += float(rx["acquisition_cost"])
    assert 0.78 <= cost / paid <= 0.82
```

`scripts/demo_data/tests/test_window.py`:
```python
"""12-month coverage, seasonality, and the rule that May-Jul additions never touch the planted signals."""
from collections import Counter, defaultdict
from datetime import date, timedelta

from helpers import AS_OF, CORE_START, STORES, day_of, is_generated

HISTORY_START = date(2025, 8, 1)
PLANTED = {"EMP-0006", "EMP-0023", "EMP-0102"}


def test_sales_cover_every_store_every_day_for_12_months(out):
    per_day = Counter((r["store_id"], day_of(r["transaction_datetime"])) for r in out.rows("transactions"))
    days = [HISTORY_START + timedelta(days=i) for i in range((AS_OF - HISTORY_START).days + 1)]
    missing = [(s, d) for s in STORES for d in days if per_day[(s, d)] == 0]
    assert not missing, missing[:5]
    assert max(day_of(r["transaction_datetime"]) for r in out.rows("transactions")) == AS_OF


def test_history_has_weekly_seasonality(out):
    by_weekday = defaultdict(list)
    per_day = Counter(day_of(r["transaction_datetime"]) for r in out.rows("transactions"))
    for d, n in per_day.items():
        if d < CORE_START:
            by_weekday[d.weekday()].append(n)
    mean = {k: sum(v) / len(v) for k, v in by_weekday.items()}
    assert mean[5] / mean[1] >= 1.08, "Saturday must be busier than Tuesday"


def test_history_has_december_peak(out):
    per_month = Counter(r["transaction_datetime"][:7] for r in out.rows("transactions"))
    assert per_month["2025-12"] > per_month["2025-11"] > per_month["2025-09"]


def test_no_generated_exceptions_inside_original_window(out):
    checks = [("refunds", "refund_id", "refund_datetime"), ("voids", "void_id", "void_datetime"),
              ("discount_overrides", "override_id", "override_datetime"),
              ("cash_drawers", "drawer_session_id", "opened_at"),
              ("employee_shifts", "shift_id", "scheduled_start")]
    for table, pk, col in checks:
        late = [r[pk] for r in out.rows(table) if is_generated(r[pk]) and day_of(r[col]) >= CORE_START]
        assert not late, f"{table}: {late[:3]}"
    # Count adjustments continue through May-June at the normal rate, but never in July (PH-005 plant month).
    july = [a["adjustment_id"] for a in out.rows("inventory_adjustments")
            if is_generated(a["adjustment_id"]) and day_of(a["adjustment_datetime"]) >= date(2026, 7, 1)]
    assert not july, july[:3]


def test_planted_people_get_no_generated_sales_in_original_window(out):
    hits = [r["transaction_id"] for r in out.rows("transactions")
            if is_generated(r["transaction_id"]) and day_of(r["transaction_datetime"]) >= CORE_START
            and r["employee_id"] in PLANTED]
    assert not hits


def test_rx_volume_supports_store_level_rules(out):
    window = Counter(r["store_id"] for r in out.rows("prescriptions")
                     if date(2026, 7, 18) <= day_of(r["received_datetime"]) <= AS_OF)
    assert all(window[s] / 14 >= 15 for s in STORES), window


def test_vendor_receipts_and_weekly_snapshots_exist(out):
    kinds = Counter(r["movement_type"] for r in out.rows("inventory_movements"))
    assert kinds["RECEIPT"] > 1000
    assert {"SALE", "REFUND_RETURN", "RECEIPT"} == set(kinds)
    fridays = {r["snapshot_date"] for r in out.rows("inventory_snapshots")}
    assert len(fridays) == 53 and all(date.fromisoformat(d).weekday() == 4 for d in fridays)
    lead = {r["vendor_id"]: int(r["lead_time_days"]) for r in out.rows("vendors")}
    assert len(lead) == 35 and all(2 <= v <= 9 for v in lead.values())
```

`scripts/demo_data/tests/test_plants.py`:
```python
"""FND-001..FND-008 must still trigger on the 12-month data, and nothing else may look like them.
Thresholds are PROXIES (the real rules live in Plan D); each asserts with headroom above the request's 2.5x."""
from collections import Counter, defaultdict
from datetime import date, timedelta

from helpers import AS_OF, CORE_START, STORES, day_of, ts, within

LAST_30 = (AS_OF - timedelta(days=29), AS_OF)
LAST_90 = (AS_OF - timedelta(days=89), AS_OF)


def _history_months(rows, col):
    return {r[col][:7] for r in rows if day_of(r[col]) < CORE_START}


def test_fnd001_sarah_refund_rate_far_above_peers(out):
    sales = Counter(r["employee_id"] for r in out.rows("transactions") if within(r["transaction_datetime"], *LAST_30))
    refunds = Counter(r["employee_id"] for r in out.rows("refunds") if within(r["refund_datetime"], *LAST_30))
    rate = {e: refunds[e] / n for e, n in sales.items()}
    peers = [v for e, v in rate.items() if e != "EMP-0006"]
    assert refunds["EMP-0006"] >= 10
    assert rate["EMP-0006"] >= 3 * (sum(peers) / len(peers))
    assert all(n < 10 for e, n in refunds.items() if e != "EMP-0006")


def test_fnd001_no_refund_outlier_in_history(out):
    rows = out.rows("refunds")
    for month in _history_months(rows, "refund_datetime"):
        per_emp = Counter(r["employee_id"] for r in rows if r["refund_datetime"].startswith(month))
        assert max(per_emp.values()) < 10, month


def _shrink_by_store_month(out):
    acc = defaultdict(float)
    for r in out.rows("inventory_adjustments"):
        if r["adjustment_type"] == "Shrinkage":
            acc[(r["adjustment_datetime"][:7], r["store_id"])] += -float(r["adjustment_value"])
    return acc


def test_fnd002_ph005_shrink_concentrated_in_july(out):
    acc = _shrink_by_store_month(out)
    others = [acc[("2026-07", s)] for s in STORES if s != "PH-005"]
    assert acc[("2026-07", "PH-005")] >= 2.5 * (sum(others) / len(others))


def test_fnd002_no_shrink_outlier_in_history(out):
    acc = _shrink_by_store_month(out)
    for month in sorted({m for m, _ in acc if m < "2026-07"}):   # history + generated May-June counts
        values = {s: acc[(month, s)] for s in STORES}
        for s, v in values.items():
            rest = [x for t, x in values.items() if t != s]
            assert v < 1.5 * (sum(rest) / len(rest)), (month, s)


def test_fnd003_exactly_twelve_double_refunds(out):
    per_txn = Counter(r["original_transaction_id"] for r in out.rows("refunds"))
    assert sum(1 for n in per_txn.values() if n >= 2) == 12


def test_fnd004_ph002_manager_override_concentration(out):
    rows = [r for r in out.rows("discount_overrides") if within(r["override_datetime"], *LAST_30)]
    per = Counter(r["approving_manager_id"] for r in rows)
    peers = [n for e, n in per.items() if e != "EMP-0023"]
    assert per["EMP-0023"] >= 3 * (sum(peers) / len(peers))
    rows = out.rows("discount_overrides")
    for month in _history_months(rows, "override_datetime"):
        per_month = Counter(r["approving_manager_id"] for r in rows if r["override_datetime"].startswith(month))
        # 12 = the busiest NON-plant approver in the original window (EMP-0100, 10/month) + 20%;
        # EMP-0023 approves 38-54/month in the original window.
        assert max(per_month.values()) <= 12, month


def _reject_rates(out, start, end):
    total, rejected = Counter(), Counter()
    for c in out.rows("insurance_claims"):
        if within(c["submitted_datetime"], start, end):
            total[c["store_id"]] += 1
            rejected[c["store_id"]] += c["claim_status"] == "Rejected"
    return {s: rejected[s] / total[s] for s in STORES}


def test_fnd005_ph004_claim_rejection_above_chain(out):
    rates = _reject_rates(out, CORE_START, AS_OF)
    others = [rates[s] for s in STORES if s != "PH-004"]
    assert rates["PH-004"] >= 2 * (sum(others) / len(others))
    assert max(others) <= 0.08


def test_fnd005_no_rejection_outlier_in_history(out):
    month = date(2025, 8, 1)
    while month < CORE_START:
        nxt = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        rates = _reject_rates(out, month, nxt - timedelta(days=1))
        assert max(rates.values()) <= 0.09, (month, rates)
        month = nxt


def test_fnd006_daniel_ross_repeated_shortages(out):
    short = Counter(r["employee_id"] for r in out.rows("cash_drawers")
                    if within(r["opened_at"], *LAST_90) and float(r["cash_variance"]) <= -10)
    assert short["EMP-0102"] >= 5
    assert all(n < 2 for e, n in short.items() if e != "EMP-0102")
    rows = out.rows("cash_drawers")
    for month in _history_months(rows, "opened_at"):
        monthly = Counter(r["employee_id"] for r in rows
                          if r["opened_at"].startswith(month) and float(r["cash_variance"]) <= -10)
        assert all(n < 2 for n in monthly.values()), month


def test_fnd007_reprint_before_own_refund(out):
    reprints = defaultdict(list)
    for r in out.rows("receipts"):
        if r["print_type"] == "Reprint":
            reprints[(r["transaction_id"], r["printed_by_employee_id"])].append(ts(r["printed_datetime"]))
    pairs = Counter()
    for f in out.rows("refunds"):
        when = ts(f["refund_datetime"])
        for printed in reprints[(f["original_transaction_id"], f["employee_id"])]:
            if timedelta(hours=1) <= when - printed <= timedelta(hours=48):
                pairs[f["employee_id"]] += 1
                break
    assert pairs["EMP-0006"] == 40
    assert all(n <= 2 for e, n in pairs.items() if e != "EMP-0006")


def _net_sales(out):
    acc = defaultdict(float)
    for t in out.rows("transactions"):
        acc[(t["store_id"], t["transaction_datetime"][:7])] += float(t["subtotal"]) - float(t["discount_amount"])
    return acc


def test_fnd008_ph004_july_sales_decline(out):
    acc = _net_sales(out)
    change = {s: acc[(s, "2026-07")] / acc[(s, "2026-06")] - 1 for s in STORES}
    assert change["PH-004"] <= -0.30
    assert all(abs(change[s]) <= 0.25 for s in STORES if s != "PH-004"), change  # original data swings up to +18%
```

`scripts/demo_data/tests/test_continuity.py`:
```python
"""No step change on 2026-05-01: the generated history must look like the original window it is glued to."""
import calendar
from collections import Counter, defaultdict
from statistics import mean

from helpers import CORE_START, STORES, day_of

PLANTED_APPROVER = "EMP-0023"


def _sales(out):
    net, count = defaultdict(float), Counter()
    for t in out.rows("transactions"):
        value = float(t["subtotal"]) - float(t["discount_amount"])
        net[(t["store_id"], t["transaction_datetime"][:7])] += value
        period = "history" if day_of(t["transaction_datetime"]) < CORE_START else "original"
        net[(t["store_id"], period)] += value
        count[(t["store_id"], period)] += 1
    return net, count


def test_history_basket_size_matches_original_window(out):
    net, count = _sales(out)
    for s in STORES:
        hist = net[(s, "history")] / count[(s, "history")]
        orig = net[(s, "original")] / count[(s, "original")]
        assert abs(hist / orig - 1) <= 0.05, (s, round(hist, 1), round(orig, 1))


def test_april_to_may_sales_have_no_step(out):
    """Net sales PER DAY (April has 30 days, May 31) across the history/original boundary."""
    net, _ = _sales(out)
    for s in STORES:
        change = (net[(s, "2026-05")] / 31) / (net[(s, "2026-04")] / 30) - 1
        assert abs(change) <= 0.10, (s, round(change, 3))


def test_override_rate_continues_into_original_window(out):
    _, count = _sales(out)
    overrides = Counter()
    for o in out.rows("discount_overrides"):
        if o["approving_manager_id"] != PLANTED_APPROVER:
            period = "history" if day_of(o["override_datetime"]) < CORE_START else "original"
            overrides[(o["store_id"], period)] += 1
    for s in STORES:
        orig = overrides[(s, "original")] / count[(s, "original")]
        hist = overrides[(s, "history")] / count[(s, "history")]
        assert 0.02 <= hist <= 0.07, (s, hist)
        if orig > 0:  # PH-002: every original override is the EMP-0023 plant
            assert abs(hist / orig - 1) <= 0.25, (s, round(hist, 4), round(orig, 4))


def test_shrink_continues_through_may_and_june(out):
    acc = defaultdict(float)
    for a in out.rows("inventory_adjustments"):
        if a["adjustment_type"] == "Shrinkage":
            acc[(a["store_id"], a["adjustment_datetime"][:7])] += -float(a["adjustment_value"])
    for s in STORES:
        baseline = mean(acc[(s, m)] for m in ("2026-01", "2026-02", "2026-03", "2026-04"))
        for month in ("2026-05", "2026-06"):
            assert abs(acc[(s, month)] / baseline - 1) <= 0.40, (s, month)


def test_sales_per_day_never_collapse_month_to_month(out):
    net, _ = _sales(out)
    months = sorted({m for (_, m) in net if m[:2] == "20" and m <= "2026-06"})

    def per_day(s, m):
        return net[(s, m)] / calendar.monthrange(int(m[:4]), int(m[5:]))[1]

    for s in STORES:
        for prev, cur in zip(months, months[1:]):
            assert per_day(s, cur) / per_day(s, prev) - 1 >= -0.15, (s, prev, cur)
```

`scripts/demo_data/tests/test_margin_plant.py`:
```python
"""FND-009: acquisition cost +8% on 5 Rx drugs at PH-003 from 2026-07-18, reimbursement flat.
Robust signals are ratio-type (margin %) and per-unit gap; store-level additive $ is volume-noisy (see plan)."""
from datetime import date

from helpers import STORES, is_generated, within

RECENT = (date(2026, 7, 18), date(2026, 7, 31))
PRIOR = (date(2026, 6, 20), date(2026, 7, 17))


def _plant_drugs(out) -> set[str]:
    return {r["product_id"] for r in out.rows("product_costs") if r["store_id"] == "PH-003"}


def _rx_totals(out, store, window, products=None, generated_only=False):
    claims = {c["prescription_id"]: c for c in out.rows("insurance_claims")}
    acc = {"revenue": 0.0, "payer": 0.0, "cost": 0.0, "units": 0}
    for rx in out.rows("prescriptions"):
        claim = claims[rx["prescription_id"]]
        if rx["store_id"] != store or not within(rx["received_datetime"], *window):
            continue
        if rx["status"] in ("Reversed", "Cancelled") or claim["claim_status"] != "Approved":
            continue
        if products is not None and rx["product_id"] not in products:
            continue
        if generated_only and not is_generated(rx["prescription_id"]):
            continue
        acc["revenue"] += float(claim["approved_amount"]) + float(claim["customer_amount"])
        acc["payer"] += float(claim["approved_amount"])
        acc["cost"] += float(rx["acquisition_cost"])
        acc["units"] += int(rx["quantity"])
    return acc


def test_cost_history_plants_exactly_five_drugs_at_ph003(out):
    rows = [r for r in out.rows("product_costs") if r["store_id"]]
    assert len(rows) == 5
    assert {r["store_id"] for r in rows} == {"PH-003"}
    assert {r["effective_from"] for r in rows} == {"2026-07-18"}
    chain = {r["product_id"]: float(r["unit_cost"]) for r in out.rows("product_costs")
             if not r["store_id"] and r["effective_from"] == "2026-01-01"}
    for r in rows:
        assert abs(float(r["unit_cost"]) / chain[r["product_id"]] - 1.08) < 0.001


def test_ph003_margin_pct_drops_others_flat(out):
    change = {}
    for s in STORES:
        a, b = _rx_totals(out, s, RECENT), _rx_totals(out, s, PRIOR)
        change[s] = ((a["revenue"] - a["cost"]) / a["revenue"]) / ((b["revenue"] - b["cost"]) / b["revenue"]) - 1
    assert change["PH-003"] <= -0.08, change
    assert all(abs(change[s]) <= 0.02 for s in STORES if s != "PH-003"), change


def test_plant_drugs_drive_the_drop(out):
    drugs = _plant_drugs(out)
    recent = _rx_totals(out, "PH-003", RECENT)
    planted = _rx_totals(out, "PH-003", RECENT, drugs)
    assert planted["cost"] / recent["cost"] >= 0.25, "5 drugs must carry a large share of PH-003 Rx cost"
    before = _rx_totals(out, "PH-003", PRIOR, drugs)
    gap_now = (planted["payer"] - planted["cost"]) / planted["units"]
    gap_before = (before["payer"] - before["cost"]) / before["units"]
    assert gap_now / gap_before - 1 <= -0.40


def test_reimbursement_stays_flat_for_plant_drugs(out):
    for drug in sorted(_plant_drugs(out)):
        now = _rx_totals(out, "PH-003", RECENT, {drug}, generated_only=True)
        before = _rx_totals(out, "PH-003", PRIOR, {drug}, generated_only=True)
        per_unit_change = (now["revenue"] / now["units"]) / (before["revenue"] / before["units"]) - 1
        assert abs(per_unit_change) <= 0.03, (drug, per_unit_change)
```

`scripts/demo_data/tests/test_targets.py`:
```python
"""targets.xlsx follows the master contract (1 sheet, long format, 0-100 %) and only PH-004 July misses."""
from collections import Counter, defaultdict
from datetime import datetime

from openpyxl import load_workbook


def _rows(out):
    wb = load_workbook(out.path / "targets.xlsx")
    assert wb.sheetnames == ["targets"], "exactly one sheet"
    return list(wb["targets"].iter_rows(values_only=True))


def test_header_and_long_format(out):
    rows = _rows(out)
    assert rows[0] == ("Store ID", "Metric Key", "Period", "Target Value")
    body = rows[1:]
    assert len(body) == 5 * 17 * 2
    assert {r[1] for r in body} == {"net_sales", "gross_margin_pct"}
    assert all(isinstance(r[2], datetime) and r[2].day == 1 and r[2].hour == 0 for r in body)
    per_key = Counter((r[0], r[1], r[2]) for r in body)
    assert set(per_key.values()) == {1}, "one row per store x metric x month"
    assert all(isinstance(r[3], (int, float)) for r in body)


def test_percent_targets_are_on_a_0_to_100_scale(out):
    wb = load_workbook(out.path / "targets.xlsx")
    ws = wb["targets"]
    for row in ws.iter_rows(min_row=2):
        if row[1].value == "gross_margin_pct":
            assert 5 <= row[3].value <= 95, row[3].value
            assert "%" not in row[3].number_format


def _actual_net(out):
    rx = {p["product_id"] for p in out.rows("products") if p["prescription_required"] == "True"}
    txn = {t["transaction_id"]: (t["store_id"], t["transaction_datetime"][:7]) for t in out.rows("transactions")}
    net = defaultdict(float)
    for li in out.rows("transaction_items"):
        if li["product_id"] not in rx:
            net[txn[li["transaction_id"]]] += float(li["line_total"])
    return net


def test_only_ph004_july_misses_net_sales_target(out):
    net = _actual_net(out)
    misses = []
    for store, key, period, value in _rows(out)[1:]:
        month = period.strftime("%Y-%m")
        if key == "net_sales" and month <= "2026-07" and net[(store, month)] < value:
            misses.append((store, month))
    assert misses == [("PH-004", "2026-07")]
    ph004 = {(p.strftime("%Y-%m")): v for s, k, p, v in _rows(out)[1:] if s == "PH-004" and k == "net_sales"}
    assert net[("PH-004", "2026-07")] <= 0.70 * ph004["2026-07"], "FND-008: July must miss by >= 30%"
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
cd scripts/demo_data && uv run pytest tests/test_integrity.py tests/test_preserve.py tests/test_window.py \
  tests/test_plants.py tests/test_continuity.py tests/test_margin_plant.py tests/test_targets.py -q
```
Expected: FAIL/ERROR ở fixture `out` — `ModuleNotFoundError: No module named 'pharmacy_demo_gen.generate'`.

- [ ] **Step 3: Implement**

`scripts/demo_data/pharmacy_demo_gen/targets.py`:
```python
"""Store KPI targets per month for the 'Dữ liệu bảng' upload demo.
Master contract: ONE sheet, LONG format, columns exactly `Store ID | Metric Key | Period | Target Value`;
Metric Key in {net_sales, gross_margin_pct}; Period = first-of-month Excel date; percent on a 0-100 scale."""
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from . import config as C
from .tables import Table, parse_dt

HEADER = ("Store ID", "Metric Key", "Period", "Target Value")
METRIC_KEYS = ("net_sales", "gross_margin_pct")
TARGET_MONTHS = [(2025, m) for m in range(8, 13)] + [(2026, m) for m in range(1, 13)]
FIXED_DOC_TIME = datetime(2026, 8, 1, 0, 0, 0)


def retail_actuals(tables: dict[str, Table]) -> dict[tuple[str, tuple[int, int]], dict[str, float]]:
    """Retail net sales (= line_total, excl. tax and Rx lines) and gross margin % (0-100) per store-month."""
    rx = {p["product_id"] for p in tables["products"].rows if p["prescription_required"] == "True"}
    txn = {t["transaction_id"]: (t["store_id"], parse_dt(t["transaction_datetime"]))
           for t in tables["transactions"].rows}
    acc = defaultdict(lambda: {"net": 0.0, "cost": 0.0})
    for li in tables["transaction_items"].rows:
        if li["product_id"] in rx or li["transaction_id"] not in txn:
            continue
        store, dt = txn[li["transaction_id"]]
        a = acc[(store, (dt.year, dt.month))]
        a["net"] += float(li["line_total"])
        a["cost"] += int(li["quantity"]) * float(li["unit_cost"])
    return {k: {"net_sales": v["net"], "gm_pct": (v["net"] - v["cost"]) / v["net"] * 100} for k, v in acc.items()}


def _store_month_targets(actual, store: str, ym: tuple[int, int], recent_gm: float) -> tuple[float, float]:
    if (store, ym) in actual and ym <= (C.HISTORY_END.year, C.HISTORY_END.month):
        net = round(actual[(store, ym)]["net_sales"] * 0.98, -2)       # achieved
        gm = actual[(store, ym)]["gm_pct"] - 0.5                         # achieved, 0-100 scale
    else:
        net = round(actual[(store, (ym[0] - 1, ym[1]))]["net_sales"] * 1.03, -2)
        gm = recent_gm - 0.5
    if (store, ym) == ("PH-004", (2026, 7)):
        # FND-008: July target follows June's level, so the July sales decline misses the target.
        net = round(actual[("PH-004", (2026, 6))]["net_sales"] * C.MONTH_WEIGHT[7] / C.MONTH_WEIGHT[6], -2)
    return float(net), round(gm - 0.05, 1)   # round DOWN to 1 decimal so the target stays below actual


def build_targets(tables: dict[str, Table]) -> list[dict]:
    """One row per store x month x metric (long format)."""
    actual = retail_actuals(tables)
    stores = sorted(s["store_id"] for s in tables["stores"].rows)
    rows = []
    for store in stores:
        recent_gm = sum(actual[(store, (2026, m))]["gm_pct"] for m in (5, 6, 7)) / 3
        for ym in TARGET_MONTHS:
            net, gm = _store_month_targets(actual, store, ym, recent_gm)
            period = datetime(ym[0], ym[1], 1)
            rows.append({"Store ID": store, "Metric Key": "net_sales", "Period": period, "Target Value": net})
            rows.append({"Store ID": store, "Metric Key": "gross_margin_pct", "Period": period, "Target Value": gm})
    return rows


def write_targets_xlsx(path: Path, rows: list[dict]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "targets"
    ws.append(list(HEADER))
    for r in rows:
        ws.append([r[h] for h in HEADER])
        ws.cell(row=ws.max_row, column=3).number_format = "yyyy-mm-dd"
        ws.cell(row=ws.max_row, column=4).number_format = "0.0" if r["Metric Key"] == "gross_margin_pct" else "0"
    wb.properties.creator = "pharmacy_demo_gen"
    wb.properties.created = FIXED_DOC_TIME
    wb.properties.modified = FIXED_DOC_TIME
    wb.save(path)
```

`scripts/demo_data/pharmacy_demo_gen/generate.py`:
```python
"""Orchestrates the generation. Call order is part of the determinism contract — do not reorder."""
from collections import Counter
from pathlib import Path

from . import config as C
from .catalog import build_product_costs, build_vendors, prepare_catalog
from .ctx import Ctx
from .inventory import simulate_inventory
from .operations import generate_refunds, generate_shifts
from .retail import generate_sales
from .rx import add_acquisition_cost, generate_prescriptions
from .staff import add_hourly_wage
from .tables import Table, load_base, write_table
from .targets import build_targets, write_targets_xlsx


def generate(base_dir: Path, out_dir: Path, seed: int = C.SEED) -> dict[str, Table]:
    tables = load_base(base_dir)
    ctx = Ctx(tables, seed)
    prepare_catalog(ctx)
    add_hourly_wage(ctx)
    vendors = build_vendors(ctx)
    product_costs = build_product_costs(ctx)
    original_rx = {r["prescription_id"] for r in tables["prescriptions"].rows}
    tables["prescriptions"].columns.append("acquisition_cost")
    sales = generate_sales(ctx)
    generate_refunds(ctx, sales)
    generate_shifts(ctx)
    generate_prescriptions(ctx)
    add_acquisition_cost(ctx, original_rx)
    purchase_orders, purchase_order_lines = simulate_inventory(ctx, vendors)
    result = {**tables, "vendors": vendors, "product_costs": product_costs,
              "purchase_orders": purchase_orders, "purchase_order_lines": purchase_order_lines}
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, table in result.items():
        write_table(out_dir / f"{name}.csv", table)
    write_targets_xlsx(out_dir / "targets.xlsx", build_targets(result))
    write_summary(out_dir / "DATA_SUMMARY.txt", result, ctx, seed)
    return result


def write_summary(path: Path, tables: dict[str, Table], ctx: Ctx, seed: int) -> None:
    lines = ["pharmacy_demo — generated by scripts/demo_data (do not edit by hand)",
             f"seed: {seed}",
             f"history: {C.HISTORY_START} .. {C.HISTORY_END} "
             f"(as_of {C.HISTORY_END} inclusive; query to {C.AS_OF_EXCLUSIVE})",
             f"original package kept verbatim from {C.CORE_START}", "",
             f"margin plant: store {C.MARGIN_PLANT_STORE}, from {C.MARGIN_PLANT_START}, "
             f"acquisition cost x{C.MARGIN_PLANT_COST_FACTOR}, reimbursement unchanged",
             f"margin plant drugs: {', '.join(ctx.heavy_rx)}", "", "row counts:"]
    for name in sorted(tables):
        lines.append(f"  {name}: {len(tables[name].rows)}")
    kinds = Counter(r["movement_type"] for r in tables["inventory_movements"].rows)
    lines += ["", "inventory_movements by type: " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items()))]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

`scripts/demo_data/pharmacy_demo_gen/__main__.py`:
```python
"""CLI: uv run python -m pharmacy_demo_gen --base ../../demo_mockdata/base --out ../../demo_mockdata"""
import argparse
import sys
from pathlib import Path

from . import config as C
from .generate import generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the 12-month pharmacy_demo CSV package.")
    parser.add_argument("--base", type=Path, required=True, help="directory with the original 21 CSVs")
    parser.add_argument("--out", type=Path, required=True, help="output directory (demo_mockdata)")
    parser.add_argument("--seed", type=int, default=C.SEED)
    args = parser.parse_args(argv)
    if args.base.resolve() == args.out.resolve():
        print("--base and --out must differ (base is the immutable input)", file=sys.stderr)
        return 2
    tables = generate(args.base, args.out, args.seed)
    for name in sorted(tables):
        print(f"{name}: {len(tables[name].rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Chạy test — phải PASS**

```bash
cd scripts/demo_data && uv run pytest tests/test_integrity.py tests/test_preserve.py tests/test_window.py \
  tests/test_plants.py tests/test_continuity.py tests/test_margin_plant.py tests/test_targets.py -q && uvx ruff check .
```
Expected: `37 passed`; `All checks passed!`. Nếu một ngưỡng proxy fail: **không nới ngưỡng** — chạy `superpowers:systematic-debugging`, so với số đo ở mục "Thông số đã đo"; mã trong plan cho đúng các số đó với seed 20260801.

- [ ] **Step 5: Commit**

```bash
git add scripts/demo_data/pharmacy_demo_gen/targets.py scripts/demo_data/pharmacy_demo_gen/generate.py \
        scripts/demo_data/pharmacy_demo_gen/__main__.py scripts/demo_data/tests/test_integrity.py \
        scripts/demo_data/tests/test_preserve.py scripts/demo_data/tests/test_window.py \
        scripts/demo_data/tests/test_plants.py scripts/demo_data/tests/test_continuity.py \
        scripts/demo_data/tests/test_margin_plant.py \
        scripts/demo_data/tests/test_targets.py
git commit -m "feat(demo-data): generator orchestration, store targets and plant acceptance tests"
```

### Task 7: Sinh dữ liệu commit + kiểm tra tất định + README

**Files:**
- Create (sinh): `demo_mockdata/{21 bảng cũ}.csv`, `demo_mockdata/vendors.csv`, `demo_mockdata/product_costs.csv`, `demo_mockdata/purchase_orders.csv`, `demo_mockdata/purchase_order_lines.csv`, `demo_mockdata/targets.xlsx`, `demo_mockdata/DATA_SUMMARY.txt`
- Modify: `demo_mockdata/README.txt`, `demo_mockdata/Michael_Pharmacy_Chain_Full_Mock_Data_Manifest.txt`
- Test: `scripts/demo_data/tests/test_determinism.py`

**Interfaces:**
- Consumes: `generate.generate`, CLI.
- Produces: bộ CSV 12 tháng mà Task 9/10 nạp; `targets.xlsx` mà master Task M4 Step 3 upload (dataset `store_targets`); `DATA_SUMMARY.txt` (nguồn duy nhất cho số dòng — README trỏ tới, không chép số).

- [ ] **Step 1: Viết test**

`scripts/demo_data/tests/test_determinism.py`:
```python
"""Same seed => byte-identical CSVs; the committed demo_mockdata CSVs must equal a fresh run."""
import hashlib

from conftest import WORKSPACE, BASE_DIR
from pharmacy_demo_gen.generate import generate
from pharmacy_demo_gen.tables import BASE_TABLES, NEW_TABLES


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_two_runs_are_identical(out, tmp_path):
    generate(BASE_DIR, tmp_path)
    for name in BASE_TABLES + NEW_TABLES:
        assert _digest(out.path / f"{name}.csv") == _digest(tmp_path / f"{name}.csv"), name


def test_committed_csvs_match_generator(out):
    committed = WORKSPACE / "demo_mockdata"
    for name in BASE_TABLES + NEW_TABLES:
        assert _digest(committed / f"{name}.csv") == _digest(out.path / f"{name}.csv"), \
            f"{name}.csv is stale: rerun the generator (Task 7)"
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
cd scripts/demo_data && uv run pytest tests/test_determinism.py -q
```
Expected: `test_two_runs_are_identical` PASS; `test_committed_csvs_match_generator` FAIL — `FileNotFoundError: … demo_mockdata/stores.csv` (CSV gốc đã chuyển vào `base/` ở Task 1).

- [ ] **Step 3: Sinh dữ liệu**

```bash
cd scripts/demo_data && uv run python -m pharmacy_demo_gen --base ../../demo_mockdata/base --out ../../demo_mockdata
```
Expected (đúng từng số với seed 20260801):
```text
audit_events: 5220
cash_drawers: 2223
customers: 5000
discount_overrides: 981
employee_shifts: 4027
employees: 110
insurance_claims: 38538
inventory_adjustments: 14382
inventory_movements: 96691
inventory_snapshots: 79500
invoices: 972
payments: 20679
prescriptions: 38538
product_costs: 1605
products: 800
purchase_order_lines: 2568
purchase_orders: 2309
receipts: 21021
refund_items: 758
refunds: 652
stores: 5
transaction_items: 93435
transactions: 20679
vendors: 35
voids: 484
```
Và `grep "margin plant drugs" ../../demo_mockdata/DATA_SUMMARY.txt` → `margin plant drugs: PRD-00067, PRD-00030, PRD-00057, PRD-00316, PRD-00324`.

- [ ] **Step 4: Chạy toàn bộ test — phải PASS**

```bash
cd scripts/demo_data && uv run pytest -q
```
Expected: `62 passed`.

- [ ] **Step 5: Cập nhật README + Manifest** — thêm vào **cuối** cả `demo_mockdata/README.txt` và `demo_mockdata/Michael_Pharmacy_Chain_Full_Mock_Data_Manifest.txt` (giữ nguyên phần cũ, phần "Package size" cũ mô tả gói gốc):

```text

12-MONTH EXTENSION (2026-10, Proactive Intelligence P0)
========================================================
- The original package (2026-05-01 .. 2026-07-31) is kept verbatim in base/ and is the generator input.
- The CSVs in this folder are GENERATED by scripts/demo_data (seed 20260801): history 2025-08-01 .. 2026-07-31
  with weekly/monthly seasonality. Do not edit them by hand; see DATA_SUMMARY.txt for row counts.
- New tables: vendors, product_costs (dated unit cost; store_id empty = chain price list),
  purchase_orders, purchase_order_lines. New columns: employees.hourly_wage, prescriptions.acquisition_cost.
  inventory_movements.movement_type also has RECEIPT (vendor delivery, reference_id = po_id).
- Rx products are priced per dispensing unit (the original per-package unit_cost was ~20x the reimbursement).
- targets.xlsx: monthly store KPI targets (net sales, front-store gross margin %) for the tabular upload demo.

Intentional anomaly added
-------------------------
10. From 2026-07-18 the acquisition cost of 5 Rx drugs at PH-003 rose 8% while reimbursement stayed flat
    (see DATA_SUMMARY.txt for the drug ids). PH-003 Rx margin % drops from about 20% to about 18%.

Regenerate: cd scripts/demo_data && uv run python -m pharmacy_demo_gen --base ../../demo_mockdata/base --out ../../demo_mockdata
Reload DB: scripts/demo_data/load_pharmacy_demo.sh <backup.dump>, then scripts/demo_data/resync_daab_schema.sh
```

- [ ] **Step 6: Commit**

```bash
git add demo_mockdata/*.csv demo_mockdata/targets.xlsx demo_mockdata/DATA_SUMMARY.txt demo_mockdata/README.txt \
        demo_mockdata/Michael_Pharmacy_Chain_Full_Mock_Data_Manifest.txt scripts/demo_data/tests/test_determinism.py
git commit -m "feat(demo-data): generate 12-month pharmacy_demo package and store targets"
```
(`demo_mockdata/expected_findings.csv` chưa đổi ở task này — Task 8.)

### Task 8: Ground truth + `scripts/check-expected-findings.ts`

**Files:**
- Modify: `demo_mockdata/expected_findings.csv`
- Create: `scripts/check-expected-findings.ts`
- Test: `scripts/check-expected-findings.test.ts`

**Interfaces:**
- Consumes: bảng LAAM `finding` (Plan D, spec §7.4) — chỉ cần cột rule id (`rule_id` hoặc `"ruleId"`), `dims` (jsonb), `severity`, và tuỳ chọn cột project (`project_id`/`"projectId"`); đọc qua `docker exec -i laam-postgres psql -U laam -d laam` (override bằng env `LAAM_PSQL`).
- Produces (export): `parseCsv(text) -> Record<string,string>[]`, `loadExpected(csvText) -> ExpectedFinding[]`, `matches(expected, actual) -> boolean`, `checkFindings(expected, actual) -> CheckResult`, `formatReport(result, total, actualCount) -> {ok, text}`, `findingColumns(cols) -> {ruleCol, projCol}`, `readFindingsFromDb(project) -> ActualFinding[]`. CLI: `node scripts/check-expected-findings.ts [--project <business_project id>] [--findings-json <file>] [--expected <csv>]` → in `PASS n/n` (exit 0) hoặc danh sách `MISS …` / `UNEXPECTED CRITICAL …` (exit 1). `ActualFinding = {ruleId, dims, severity}` (cũng là định dạng file `--findings-json`).

Luật khớp: `rule_id` thuộc `rule_ids` (cột mới, phân tách `|`) **và** `dims.location_id` = `store_id` (chuỗi hoặc mảng; `Multiple` = mọi chi nhánh) **và** nếu dòng expected có `employee_id` thì: dims không có giá trị `EMP-*` nào ⇒ chấp nhận (rule cấp cửa hàng), có ⇒ phải chứa đúng nhân viên đó (key bất kỳ — FND-004 là approver). Finding `critical` (không phân biệt hoa thường) không khớp rule family + chi nhánh của dòng expected nào ⇒ fail. 0 dòng finding ⇒ fail. Cột `severity` của CSV chỉ để đọc, không dùng để khớp (request không cho mức của FND-008/009 ⇒ để trống).

- [ ] **Step 1: Viết test**

`scripts/check-expected-findings.test.ts`:
```ts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { checkFindings, findingColumns, formatReport, loadExpected, parseCsv } from './check-expected-findings.ts';
import type { ActualFinding } from './check-expected-findings.ts';

const csv = readFileSync(new URL('../demo_mockdata/expected_findings.csv', import.meta.url), 'utf8');
const expected = loadExpected(csv);

const allFound: ActualFinding[] = [
  { ruleId: 'RET-REF-001', dims: { location_id: 'PH-001', employee_id: 'EMP-0006' }, severity: 'high' },
  { ruleId: 'RET-INV-010', dims: { location_id: 'PH-005' }, severity: 'high' },
  { ruleId: 'RET-REF-004', dims: { location_id: ['PH-001', 'PH-002'] }, severity: 'high' },
  { ruleId: 'RET-DISC-003', dims: { location_id: 'PH-002', approver_id: 'EMP-0023' }, severity: 'medium' },
  { ruleId: 'PH-CLAIM-001', dims: { location_id: 'PH-004' }, severity: 'high' },
  { ruleId: 'RET-CASH-001', dims: { location_id: 'PH-005', employee_id: 'EMP-0102' }, severity: 'high' },
  { ruleId: 'RET-X-REPRINT-001', dims: { location_id: 'PH-001', employee_id: 'EMP-0006' }, severity: 'high' },
  { ruleId: 'RET-SALES-001', dims: { location_id: 'PH-004' }, severity: 'medium' },
  { ruleId: 'PH-MARGIN-001', dims: { location_id: 'PH-003' }, severity: 'critical' },
];

test('expected file carries a rule family for every row, incl. the new FND-008/009', () => {
  assert.equal(expected.length, 9);
  assert.deepEqual(expected.at(-1)?.ruleIds, ['PH-MARGIN-001', 'RET-MARGIN-002', 'RET-VENDOR-001']);
});

test('parseCsv keeps quoted commas inside one field', () => {
  const rows = parseCsv('a,b\n"x, y",2\n');
  assert.deepEqual(rows, [{ a: 'x, y', b: '2' }]);
});

test('PASS n/n when every expected finding is found and the only critical one is expected', () => {
  const report = formatReport(checkFindings(expected, allFound), expected.length, allFound.length);
  assert.equal(report.ok, true);
  assert.match(report.text, /^PASS 9\/9/);
});

test('a missing plant is reported by id', () => {
  const actual = allFound.filter((a) => a.ruleId !== 'PH-CLAIM-001');
  const report = formatReport(checkFindings(expected, actual), expected.length, actual.length);
  assert.equal(report.ok, false);
  assert.match(report.text, /MISS FND-005/);
});

test('right rule at the wrong store or wrong employee does not count', () => {
  const actual = allFound.map((a) => (a.ruleId === 'RET-REF-001' ? { ...a, dims: { location_id: 'PH-001', employee_id: 'EMP-0007' } } : a));
  const result = checkFindings(expected, actual);
  assert.deepEqual(result.missing.map((e) => e.findingId), ['FND-001']);
  const moved = allFound.map((a) => (a.ruleId === 'RET-INV-010' ? { ...a, dims: { location_id: 'PH-001' } } : a));
  assert.deepEqual(checkFindings(expected, moved).missing.map((e) => e.findingId), ['FND-002']);
});

test('an unexpected critical finding fails the run (case-insensitive severity)', () => {
  const actual = [...allFound, { ruleId: 'RET-VOID-001', dims: { location_id: 'PH-003' }, severity: 'CRITICAL' }];
  const report = formatReport(checkFindings(expected, actual), expected.length, actual.length);
  assert.equal(report.ok, false);
  assert.match(report.text, /UNEXPECTED CRITICAL RET-VOID-001/);
});

test('zero finding rows is a failure, never PASS 0/0', () => {
  const report = formatReport(checkFindings(expected, []), expected.length, 0);
  assert.equal(report.ok, false);
  assert.match(report.text, /no finding rows/);
});

test('finding columns are detected in snake_case and camelCase, missing table is an error', () => {
  assert.deepEqual(findingColumns(['id', 'rule_id', 'dims', 'severity', 'project_id']), { ruleCol: 'rule_id', projCol: 'project_id' });
  assert.deepEqual(findingColumns(['id', 'ruleId', 'dims', 'severity', 'projectId']), { ruleCol: 'ruleId', projCol: 'projectId' });
  assert.throws(() => findingColumns([]), /not found/);
  assert.throws(() => findingColumns(['id', 'dims']), /lacks/);
});
```

- [ ] **Step 2: Chạy test — phải FAIL**

```bash
node --test scripts/check-expected-findings.test.ts
```
Expected: FAIL — `ERR_MODULE_NOT_FOUND` cho `scripts/check-expected-findings.ts`.

- [ ] **Step 3: Cập nhật `demo_mockdata/expected_findings.csv`** (thay toàn bộ nội dung; 7 dòng cũ giữ nguyên chữ, thêm cột cuối `rule_ids` theo bảng độ phủ spec §7.3 và 2 dòng mới):
```csv
finding_id,severity,finding_type,store_id,employee_id,summary,recommended_action,rule_ids
FND-001,High,Excessive refund activity,PH-001,EMP-0006,"Sarah Miller refund rate is far above company average, with many no-receipt and late-evening refunds.",Review linked refunds and manager approvals.,RET-REF-001|RET-REF-002
FND-002,High,Inventory shrinkage,PH-005,,Large negative inventory variances are concentrated in OTC and medical supplies.,Perform cycle count and review adjustment history.,RET-INV-010
FND-003,High,Duplicate refunds,Multiple,,Twelve original transactions appear to have been refunded twice.,Review cross-store refund activity and payment methods.,RET-REF-004
FND-004,Medium,Manager override concentration,PH-002,EMP-0023,Evening price overrides and discounts are unusually concentrated under one manager.,Review override approvals and affected employees.,RET-DISC-003|RET-REF-005
FND-005,High,Claim rejection rate,PH-004,,Insurance claim rejection rate is materially above chain average.,Review rejection codes and technician shifts.,PH-CLAIM-001
FND-006,High,Cash drawer shortages,PH-005,EMP-0102,Repeated shortages coincide with no-sale drawer openings on closing shifts.,Review drawer sessions and cash refunds.,RET-CASH-001|RET-CASH-004
FND-007,High,Receipt reprint before refund,PH-001,EMP-0006,"Sarah Miller reprinted original sale receipts 1-48 hours before processing her own refunds of the same transactions (40 matched pairs), which explains why her refunds show the original receipt as present.",Correlate the receipt reprint log with refund timestamps and review each matched pair.,RET-X-REPRINT-001
FND-008,,Front-store sales decline,PH-004,,"PH-004 front-store net sales in July 2026 are roughly 40% below June 2026, while the other stores are within normal month-to-month variation.",Review July traffic and staffing at PH-004 and compare against the store target.,RET-SALES-001
FND-009,,Rx margin decline from acquisition cost,PH-003,,"From 2026-07-18 the acquisition cost of 5 Rx drugs (PRD-00067, PRD-00030, PRD-00057, PRD-00316, PRD-00324) rose 8% at PH-003 while reimbursement stayed flat; PH-003 Rx margin fell from about 20% to about 18% over the last 14 days.",Review vendor pricing for the 5 drugs and compare with other suppliers.,PH-MARGIN-001|RET-MARGIN-002|RET-VENDOR-001
```

Kiểm tra id thuốc trong FND-009 khớp generator: `grep "margin plant drugs" demo_mockdata/DATA_SUMMARY.txt`.

- [ ] **Step 4: Implement checker**

`scripts/check-expected-findings.ts`:
```ts
// Compares LAAM findings with demo_mockdata/expected_findings.csv (ground truth of the pharmacy demo).
// Usage: node scripts/check-expected-findings.ts [--project <business_project id>] [--findings-json <file>]
//        [--expected <csv>]   env LAAM_PSQL overrides the psql command (default: docker exec laam-postgres).
// Prints "PASS n/n" (exit 0) or the misses / unexpected critical findings (exit 1).
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export interface ExpectedFinding { findingId: string; storeId: string; employeeId: string; ruleIds: string[] }
export interface ActualFinding { ruleId: string; dims: Record<string, unknown>; severity: string }
export interface CheckResult {
  matched: { expected: ExpectedFinding; actual: ActualFinding }[];
  missing: ExpectedFinding[];
  unexpectedCritical: ActualFinding[];
}

const DEFAULT_PSQL = 'docker exec -i laam-postgres psql -U laam -d laam';
const MULTIPLE = 'multiple';

export function parseCsv(text: string): Record<string, string>[] {
  const records: string[][] = [];
  let field = '';
  let row: string[] = [];
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i++; } else if (ch === '"') quoted = false; else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { row.push(field); field = ''; }
    else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(field); field = '';
      if (row.some((v) => v !== '')) records.push(row);
      row = [];
    } else field += ch;
  }
  if (field !== '' || row.length) { row.push(field); records.push(row); }
  const [header, ...body] = records;
  return body.map((r) => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ''])));
}

export function loadExpected(csvText: string): ExpectedFinding[] {
  return parseCsv(csvText).map((r) => {
    const ruleIds = (r.rule_ids ?? '').split('|').map((s) => s.trim()).filter(Boolean);
    if (!ruleIds.length) throw new Error(`expected finding ${r.finding_id} has no rule_ids`);
    return { findingId: r.finding_id, storeId: r.store_id.trim(), employeeId: r.employee_id.trim(), ruleIds };
  });
}

function dimValues(dims: Record<string, unknown>): string[] {
  return Object.values(dims).flatMap((v) => (Array.isArray(v) ? v.map(String) : [String(v)]));
}

function locationMatches(expected: ExpectedFinding, dims: Record<string, unknown>): boolean {
  if (expected.storeId.toLowerCase() === MULTIPLE) return true;
  const loc = dims.location_id;
  return Array.isArray(loc) ? loc.map(String).includes(expected.storeId) : String(loc) === expected.storeId;
}

function employeeMatches(expected: ExpectedFinding, dims: Record<string, unknown>): boolean {
  if (!expected.employeeId) return true;
  const employees = dimValues(dims).filter((v) => /^EMP-/.test(v));
  return employees.length === 0 || employees.includes(expected.employeeId);
}

export function matches(expected: ExpectedFinding, actual: ActualFinding): boolean {
  return expected.ruleIds.includes(actual.ruleId)
    && locationMatches(expected, actual.dims)
    && employeeMatches(expected, actual.dims);
}

export function checkFindings(expected: ExpectedFinding[], actual: ActualFinding[]): CheckResult {
  const matched: CheckResult['matched'] = [];
  const missing: ExpectedFinding[] = [];
  for (const e of expected) {
    const hit = actual.find((a) => matches(e, a));
    if (hit) matched.push({ expected: e, actual: hit }); else missing.push(e);
  }
  const unexpectedCritical = actual.filter((a) => a.severity.toLowerCase() === 'critical'
    && !expected.some((e) => e.ruleIds.includes(a.ruleId) && locationMatches(e, a.dims)));
  return { matched, missing, unexpectedCritical };
}

export function formatReport(result: CheckResult, total: number, actualCount: number): { ok: boolean; text: string } {
  if (actualCount === 0) return { ok: false, text: 'FAIL: no finding rows (did the analysis run?)' };
  const lines: string[] = [];
  for (const m of result.matched) lines.push(`  ok   ${m.expected.findingId} <- ${m.actual.ruleId} ${JSON.stringify(m.actual.dims)}`);
  for (const e of result.missing) lines.push(`  MISS ${e.findingId} (rules ${e.ruleIds.join('|')}, store ${e.storeId}${e.employeeId ? `, employee ${e.employeeId}` : ''})`);
  for (const a of result.unexpectedCritical) lines.push(`  UNEXPECTED CRITICAL ${a.ruleId} ${JSON.stringify(a.dims)}`);
  const ok = result.missing.length === 0 && result.unexpectedCritical.length === 0;
  const head = ok ? `PASS ${result.matched.length}/${total}` : `FAIL ${result.matched.length}/${total}`;
  return { ok, text: [head, ...lines].join('\n') };
}

function psql(sql: string): string {
  const [cmd, ...args] = (process.env.LAAM_PSQL ?? DEFAULT_PSQL).split(/\s+/).filter(Boolean);
  return execFileSync(cmd, [...args, '-At', '-c', sql], { encoding: 'utf8' }).trim();
}

// LAAM's Drizzle tables use quoted camelCase columns ("scheduledFor"); accept either naming.
export function findingColumns(cols: string[]): { ruleCol: string; projCol: string | null } {
  if (!cols.length) throw new Error('table "finding" not found in LAAM DB (Plan D migrations applied?)');
  const pick = (...names: string[]) => names.find((n) => cols.includes(n)) ?? null;
  const ruleCol = pick('rule_id', 'ruleId');
  if (!ruleCol || !cols.includes('dims') || !cols.includes('severity')) {
    throw new Error(`finding table lacks rule_id/dims/severity columns: ${cols.join(', ')}`);
  }
  return { ruleCol, projCol: pick('project_id', 'projectId') };
}

export function readFindingsFromDb(project: string | null): ActualFinding[] {
  const cols = psql("select column_name from information_schema.columns where table_schema='public' and table_name='finding'")
    .split('\n').filter(Boolean);
  const { ruleCol, projCol } = findingColumns(cols);
  let where = '';
  if (project) {
    if (!/^[0-9A-Za-z_-]+$/.test(project)) throw new Error('invalid --project value');
    if (!projCol) throw new Error('finding table has no project column');
    where = ` where "${projCol}" = '${project}'`;
  }
  const json = psql(`select coalesce(json_agg(json_build_object('ruleId', "${ruleCol}", 'dims', "dims", 'severity', "severity")), '[]') from finding${where}`);
  return (JSON.parse(json) as ActualFinding[]).map((a) => ({ ...a, dims: a.dims ?? {}, severity: a.severity ?? '' }));
}

function arg(name: string): string | null {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : null;
}

function main(): void {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const expectedPath = arg('--expected') ?? path.join(root, 'demo_mockdata', 'expected_findings.csv');
  const expected = loadExpected(readFileSync(expectedPath, 'utf8'));
  const jsonPath = arg('--findings-json');
  const actual = jsonPath ? (JSON.parse(readFileSync(jsonPath, 'utf8')) as ActualFinding[]) : readFindingsFromDb(arg('--project'));
  const report = formatReport(checkFindings(expected, actual), expected.length, actual.length);
  console.log(report.text);
  process.exit(report.ok ? 0 : 1);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    main();
  } catch (err) {
    console.error(`FAIL: ${(err as Error).message}`);
    process.exit(1);
  }
}
```

- [ ] **Step 5: Chạy test — phải PASS**

```bash
node --test scripts/check-expected-findings.test.ts
```
Expected: `ℹ pass 8`, `ℹ fail 0`.

- [ ] **Step 6: Smoke CLI**

```bash
echo '[{"ruleId":"PH-CLAIM-001","dims":{"location_id":"PH-004"},"severity":"high"}]' > /tmp/pi-a-findings.json
node scripts/check-expected-findings.ts --findings-json /tmp/pi-a-findings.json; echo "exit=$?"
node scripts/check-expected-findings.ts; echo "exit=$?"
```
Expected: lần 1 in `FAIL 1/9`, dòng `ok   FND-005 <- PH-CLAIM-001 …`, 8 dòng `MISS …`, `exit=1`. Lần 2 (Plan D chưa tạo bảng): `FAIL: table "finding" not found in LAAM DB (Plan D migrations applied?)`, `exit=1`. Sau khi Plan D xong, master Task M5 chạy `node scripts/check-expected-findings.ts --project <business_project id>` → `PASS 9/9`.

- [ ] **Step 7: Commit**

```bash
git add demo_mockdata/expected_findings.csv scripts/check-expected-findings.ts scripts/check-expected-findings.test.ts
git commit -m "feat(demo-data): ground-truth rule families and expected-findings checker"
```

### Task 9: Schema + script nạp + diễn tập trên container tạm

**Files:**
- Create: `scripts/demo_data/schema/base.sql` (pg_dump), `scripts/demo_data/schema/extension.sql`, `scripts/demo_data/load_pharmacy_demo.sh`, `scripts/demo_data/verify_plants.sql`

**Interfaces:**
- Consumes: `demo_mockdata/*.csv` (Task 7), container Postgres có `POSTGRES_USER`.
- Produces: `load_pharmacy_demo.sh <backup.dump>` (env `DAAB_PG_CONTAINER`, `PHARMACY_DB`) — exit 0 và in `ok <table> <rows>` cho 25 bảng, exit 1 khi thiếu/sai backup hoặc lệch số dòng; `verify_plants.sql` (chỉ đọc).

- [ ] **Step 1: Chụp DDL hiện tại** (phải chạy **trước** Task 10 — đây là schema 21 bảng trước khi thay)

```bash
PGU="$(docker exec daab-postgres printenv POSTGRES_USER)"
mkdir -p scripts/demo_data/schema
docker exec daab-postgres pg_dump -U "$PGU" -d pharmacy_demo --schema-only --no-owner --no-privileges \
  > scripts/demo_data/schema/base.sql
grep -c "^CREATE TABLE public\." scripts/demo_data/schema/base.sql
grep -c "FOREIGN KEY" scripts/demo_data/schema/base.sql
```
Expected: `21` và `51`.

- [ ] **Step 2: Viết `extension.sql`**

`scripts/demo_data/schema/extension.sql`:
```sql
-- pharmacy_demo extension for Proactive Intelligence P0 (Plan A).
-- Only ADDs tables/columns: existing table and column names are a contract for packs/_projects mapping.
-- Applied after base.sql and BEFORE loading CSVs (load order in load_pharmacy_demo.sh respects the FKs).

ALTER TABLE public.employees ADD COLUMN hourly_wage numeric;
ALTER TABLE public.prescriptions ADD COLUMN acquisition_cost numeric;

CREATE TABLE public.vendors (
    vendor_id text PRIMARY KEY,
    vendor_name text NOT NULL,
    lead_time_days integer NOT NULL CHECK (lead_time_days > 0),
    order_weekday integer NOT NULL CHECK (order_weekday BETWEEN 0 AND 6),
    payment_terms text,
    status text
);

CREATE TABLE public.product_costs (
    product_cost_id text PRIMARY KEY,
    product_id text NOT NULL REFERENCES public.products(product_id),
    store_id text REFERENCES public.stores(store_id),          -- NULL = chain-wide price list
    vendor_id text REFERENCES public.vendors(vendor_id),
    effective_from date NOT NULL,
    effective_to date,                                           -- NULL = still effective
    unit_cost numeric NOT NULL,
    change_reason text
);
CREATE INDEX product_costs_lookup ON public.product_costs (product_id, store_id, effective_from);

CREATE TABLE public.purchase_orders (
    po_id text PRIMARY KEY,
    store_id text NOT NULL REFERENCES public.stores(store_id),
    vendor_id text NOT NULL REFERENCES public.vendors(vendor_id),
    order_date date NOT NULL,
    expected_date date NOT NULL,
    received_datetime timestamp without time zone,
    status text NOT NULL
);

CREATE TABLE public.purchase_order_lines (
    po_line_id text PRIMARY KEY,
    po_id text NOT NULL REFERENCES public.purchase_orders(po_id),
    product_id text NOT NULL REFERENCES public.products(product_id),
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_cost numeric NOT NULL
);

ALTER TABLE public.products
    ADD CONSTRAINT fk_products_vendor FOREIGN KEY (vendor_id) REFERENCES public.vendors(vendor_id);

COMMENT ON COLUMN public.employees.hourly_wage IS 'Hourly wage in USD (labor cost = shift hours x wage)';
COMMENT ON COLUMN public.prescriptions.acquisition_cost IS 'Acquisition cost of the dispensed quantity at fill date and store (USD)';
COMMENT ON TABLE public.product_costs IS 'Dated unit cost history; store_id NULL = chain price list, non-NULL = store-specific override';
COMMENT ON COLUMN public.inventory_movements.movement_type IS 'SALE | REFUND_RETURN | RECEIPT (vendor delivery, reference_id = purchase_orders.po_id)';
```

- [ ] **Step 3: Viết script nạp + smoke SQL**

`scripts/demo_data/load_pharmacy_demo.sh`:
```bash
#!/usr/bin/env bash
# Rebuild the pharmacy_demo database from demo_mockdata/*.csv.
#   scripts/demo_data/load_pharmacy_demo.sh <verified pg_dump -Fc backup of pharmacy_demo>
# Env: DAAB_PG_CONTAINER (default daab-postgres), PHARMACY_DB (default pharmacy_demo).
# Refuses to drop anything unless the backup file exists and contains pharmacy_demo table data.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DATA="$ROOT/demo_mockdata"
SCHEMA="$ROOT/scripts/demo_data/schema"
CONTAINER="${DAAB_PG_CONTAINER:-daab-postgres}"
DB="${PHARMACY_DB:-pharmacy_demo}"
BACKUP="${1:-}"
LOAD_ORDER="stores vendors products employees customers transactions transaction_items payments receipts
invoices refunds refund_items voids discount_overrides cash_drawers employee_shifts inventory_movements
inventory_adjustments inventory_snapshots prescriptions insurance_claims audit_events product_costs
purchase_orders purchase_order_lines"

if [ -z "$BACKUP" ] || [ ! -s "$BACKUP" ]; then
  echo "usage: $0 <backup.dump>  (backup missing or empty — refusing to drop $DB)" >&2
  exit 1
fi
if ! docker exec -i "$CONTAINER" pg_restore --list < "$BACKUP" | grep -q "TABLE DATA public transactions"; then
  echo "backup $BACKUP has no pharmacy_demo table data — refusing to drop $DB" >&2
  exit 1
fi

missing=""
for f in "$SCHEMA/base.sql" "$SCHEMA/extension.sql"; do [ -s "$f" ] || missing="$missing $f"; done
for table in $LOAD_ORDER; do [ -s "$DATA/$table.csv" ] || missing="$missing $DATA/$table.csv"; done
if [ -n "$missing" ]; then
  echo "missing inputs — refusing to drop $DB:$missing" >&2
  exit 1
fi

PGUSER_NAME="$(docker exec "$CONTAINER" printenv POSTGRES_USER)"
run_psql() { docker exec -i "$CONTAINER" psql -U "$PGUSER_NAME" -v ON_ERROR_STOP=1 -q "$@"; }

run_psql -d postgres -c "DROP DATABASE IF EXISTS $DB WITH (FORCE)"
run_psql -d postgres -c "CREATE DATABASE $DB"
run_psql -d "$DB" < "$SCHEMA/base.sql" > /dev/null
run_psql -d "$DB" < "$SCHEMA/extension.sql"

for table in $LOAD_ORDER; do
  columns="$(head -1 "$DATA/$table.csv")"
  run_psql -d "$DB" -c "\\copy public.$table ($columns) FROM pstdin WITH (FORMAT csv, HEADER true)" < "$DATA/$table.csv"
done
run_psql -d "$DB" -c "ANALYZE"

status=0
for table in $LOAD_ORDER; do
  expected=$(( $(wc -l < "$DATA/$table.csv") - 1 ))
  actual="$(run_psql -d "$DB" -At -c "SELECT count(*) FROM public.$table")"
  if [ "$expected" != "$actual" ]; then
    echo "MISMATCH $table: csv=$expected db=$actual" >&2
    status=1
  else
    echo "ok $table $actual"
  fi
done
exit $status
```

`scripts/demo_data/verify_plants.sql`:
```sql
-- Post-load smoke check of pharmacy_demo (read-only). Expected values in the plan, Task 9.
\pset footer off
SELECT 'window' AS check, min(transaction_datetime)::date AS first_day, max(transaction_datetime)::date AS last_day,
       count(*) FILTER (WHERE transaction_id !~ '^TXN-[0-9]{7}$') AS bad_ids
FROM transactions;

SELECT 'claim_rejection_may_jul' AS check, store_id,
       round(100.0 * avg((claim_status = 'Rejected')::int), 1) AS reject_pct
FROM insurance_claims WHERE submitted_datetime >= '2026-05-01' AND submitted_datetime < '2026-08-01'
GROUP BY store_id ORDER BY store_id;

SELECT 'rx_margin_pct' AS check, p.store_id,
       round(100 * (1 - sum(p.acquisition_cost) FILTER (WHERE p.received_datetime >= '2026-07-18')
             / sum(c.approved_amount + c.customer_amount) FILTER (WHERE p.received_datetime >= '2026-07-18')), 1) AS last_14d,
       round(100 * (1 - sum(p.acquisition_cost) FILTER (WHERE p.received_datetime < '2026-07-18')
             / sum(c.approved_amount + c.customer_amount) FILTER (WHERE p.received_datetime < '2026-07-18')), 1) AS prior_28d
FROM prescriptions p JOIN insurance_claims c USING (prescription_id)
WHERE c.claim_status = 'Approved' AND p.status NOT IN ('Reversed', 'Cancelled')
  AND p.received_datetime >= '2026-06-20' AND p.received_datetime < '2026-08-01'
GROUP BY p.store_id ORDER BY p.store_id;

SELECT 'sarah_refunds_jul' AS check, count(*) AS refunds FROM refunds
WHERE employee_id = 'EMP-0006' AND refund_datetime >= '2026-07-02' AND refund_datetime < '2026-08-01';

SELECT 'movement_types' AS check, movement_type, count(*) FROM inventory_movements GROUP BY 2 ORDER BY 2;
```

```bash
chmod +x scripts/demo_data/load_pharmacy_demo.sh && bash -n scripts/demo_data/load_pharmacy_demo.sh
```

- [ ] **Step 4: Test guard (phải từ chối)** — chạy trên container tạm để chắc chắn không chạm DB thật:

```bash
docker run -d --rm --name pi-a-rehearsal-pg -e POSTGRES_USER=ennam_kg -e POSTGRES_PASSWORD=rehearsal postgres:16
until docker exec pi-a-rehearsal-pg pg_isready -U ennam_kg -q; do sleep 1; done
DAAB_PG_CONTAINER=pi-a-rehearsal-pg scripts/demo_data/load_pharmacy_demo.sh /nonexistent.dump; echo "exit=$?"
```
Expected: `usage: … (backup missing or empty — refusing to drop pharmacy_demo)` và `exit=1`.

- [ ] **Step 5: Diễn tập nạp** (backup gần nhất chỉ dùng để qua guard; nạp vào container tạm)

```bash
LATEST_BACKUP="$(ls -1d "$HOME"/Backups/EnnamKG/*/daab/pharmacy_demo.dump | sort | tail -1)"
echo "$LATEST_BACKUP"
mv demo_mockdata/vendors.csv /tmp/pi-a-vendors.csv
DAAB_PG_CONTAINER=pi-a-rehearsal-pg scripts/demo_data/load_pharmacy_demo.sh "$LATEST_BACKUP"; echo "exit=$?"
mv /tmp/pi-a-vendors.csv demo_mockdata/vendors.csv
DAAB_PG_CONTAINER=pi-a-rehearsal-pg scripts/demo_data/load_pharmacy_demo.sh "$LATEST_BACKUP"
```
Expected: dòng đầu là đường dẫn backup (ví dụ `/Users/danhtrinh/Backups/EnnamKG/2026-10-02/daab/pharmacy_demo.dump`); lần chạy thiếu `vendors.csv` in `missing inputs — refusing to drop pharmacy_demo: …/demo_mockdata/vendors.csv` và `exit=1` **trước** khi DROP; lần chạy đủ in 25 dòng `ok <table> <rows>` đúng bằng số ở Task 7 Step 3, exit 0.

- [ ] **Step 6: Smoke SQL trên bản diễn tập**

```bash
docker exec -i pi-a-rehearsal-pg psql -U ennam_kg -d pharmacy_demo < scripts/demo_data/verify_plants.sql
docker rm -f pi-a-rehearsal-pg
```
Expected:
```text
window | 2025-08-01 | 2026-07-31 | 0
claim_rejection_may_jul: PH-001 4.6 · PH-002 5.8 · PH-003 5.1 · PH-004 15.9 · PH-005 5.2
rx_margin_pct (last_14d / prior_28d): PH-001 20.1/20.0 · PH-002 20.1/19.9 · PH-003 17.7/20.0 · PH-004 19.9/19.9 · PH-005 20.0/20.0
sarah_refunds_jul | 60
movement_types: RECEIPT 2568 · REFUND_RETURN 688 · SALE 93435
```

- [ ] **Step 7: Commit**

```bash
git add scripts/demo_data/schema/base.sql scripts/demo_data/schema/extension.sql \
        scripts/demo_data/load_pharmacy_demo.sh scripts/demo_data/verify_plants.sql
git commit -m "feat(demo-data): pharmacy_demo schema extension and guarded reload script"
```

### Task 10: Nạp lại `pharmacy_demo` thật + đồng bộ schema DAAB

**Files:**
- Create: `scripts/demo_data/resync_daab_schema.sh`

**Interfaces:**
- Consumes: `load_pharmacy_demo.sh`, `verify_plants.sql`, DAAB API `POST /api/v1/data-sources/{id}/extract-schema` (`{"created_by"}`), `POST …/sync-schema` (`{"created_by"}`), `POST …/generate-kg` (`{"project_id"}`), `GET …/sync-jobs` (mảng job `{id, job_type ∈ schema_extraction|schema_sync|kg_generation, status}`); data source `3c7af733-b069-4654-b98e-beb5afde588c` (Pharmacy POS DB), project `4ad7a5fa-a036-4f6a-8229-39a20af23e38` (Michael Pharmacy Chain).
- Produces: `pharmacy_demo` 25 bảng; `source_tables` = 25 và 25 node `architecture` `public.<table>` (không nhân đôi) cho Plan B (sync schema/mapping) và master Task M4.

Điều kiện trước: không ai đang demo; có `DAAB_API_KEY` (API key quyền developer trên project — operator cung cấp, không ghi vào file); `kg-server` đang chạy ở `http://localhost:${KG_SERVER_PORT}` — trên máy dev là **8082** (`.env`: `KG_SERVER_PORT=8082`; cổng 8080 trên host là ứng dụng khác). Script tự đọc `KG_SERVER_PORT` từ `.env` (mặc định 8082) và kiểm `/healthz` trước khi gọi; override bằng `DAAB_API_URL`. Chạy Step 1–6 **trong cùng một shell** (biến `B` đặt một lần ở Step 1).

- [ ] **Step 1: Backup bắt buộc**

```bash
PGU="$(docker exec daab-postgres printenv POSTGRES_USER)"
B="$HOME/Backups/EnnamKG/$(date +%F)/daab"; mkdir -p "$B"; chmod 700 "$(dirname "$B")" "$B"
echo "backup dir: $B"   # ghi lại đường dẫn này vào checkpoint; các bước sau dùng "$B", không tính lại ngày
docker exec daab-postgres pg_dump -U "$PGU" -d pharmacy_demo -Fc > "$B/pharmacy_demo.before-pi-A.dump"
chmod 600 "$B/pharmacy_demo.before-pi-A.dump"
docker exec -i daab-postgres pg_restore --list < "$B/pharmacy_demo.before-pi-A.dump" | grep -c "TABLE DATA public"
docker exec daab-postgres psql -U "$PGU" -d postgres -Atc "SELECT count(*) FROM pg_stat_activity WHERE datname = 'pharmacy_demo'"
# Step 5 ghi lại metadata DAAB (source_tables/source_columns) — backup cả ennam_kg và đếm mô tả đã curate
docker exec daab-postgres pg_dump -U "$PGU" -d ennam_kg -Fc > "$B/ennam_kg.before-pi-A.dump"
chmod 600 "$B/ennam_kg.before-pi-A.dump"
docker exec daab-postgres psql -U "$PGU" -d ennam_kg -Atc "SELECT count(*) FILTER (WHERE coalesce(sc.user_description, '') <> '') FROM source_columns sc JOIN source_tables st ON st.id = sc.source_table_id JOIN source_schemas ss ON ss.id = st.source_schema_id WHERE ss.data_source_id = '3c7af733-b069-4654-b98e-beb5afde588c'"
```
Expected: `21` (bảng có dữ liệu trong backup); số kết nối đang mở (thường 0–2 của pool DAAB; `WITH (FORCE)` sẽ ngắt); số mô tả cột đã curate = `6` (đo 2026-10-02) — ghi lại số này.

- [ ] **Step 2: Nạp**

```bash
scripts/demo_data/load_pharmacy_demo.sh "$B/pharmacy_demo.before-pi-A.dump"
```
Expected: 25 dòng `ok …` như Task 9 Step 5, exit 0.

- [ ] **Step 3: Smoke SQL trên DB thật**

```bash
docker exec -i daab-postgres psql -U "$(docker exec daab-postgres printenv POSTGRES_USER)" -d pharmacy_demo \
  < scripts/demo_data/verify_plants.sql
```
Expected: đúng các giá trị của Task 9 Step 6.

- [ ] **Step 4: Viết script đồng bộ DAAB**

`scripts/demo_data/resync_daab_schema.sh`:
```bash
#!/usr/bin/env bash
# After load_pharmacy_demo.sh: refresh DAAB's view of the Pharmacy POS DB data source.
# Order matters (checkpoint 2026-08-17): extract-schema -> sync-schema -> generate-kg.
# sync-schema alone only refreshes source_tables metadata; KG nodes public.<table> come from generate-kg.
# Env: DAAB_API_KEY (required, developer role on the project), DAAB_API_URL (default: localhost + KG_SERVER_PORT
#      from the workspace .env, else 8082), PHARMACY_DATA_SOURCE_ID, PHARMACY_PROJECT_ID, DAAB_PG_CONTAINER,
#      EXPECTED_TABLES (default 25).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# kg-server's host port comes from KG_SERVER_PORT in the workspace .env (8082 on the dev machine; 8080 is
# only the container-internal port and may belong to an unrelated app on the host).
if [ -z "${KG_SERVER_PORT:-}" ] && [ -f "$ROOT/.env" ]; then
  KG_SERVER_PORT="$(grep -E '^KG_SERVER_PORT=' "$ROOT/.env" | tail -1 | cut -d= -f2)"
fi
API="${DAAB_API_URL:-http://localhost:${KG_SERVER_PORT:-8082}}"
curl -fsS "$API/healthz" > /dev/null || { echo "kg-server not reachable at $API (set DAAB_API_URL)" >&2; exit 1; }
KEY="${DAAB_API_KEY:?set DAAB_API_KEY (API key with developer role on the pharmacy project)}"
DS="${PHARMACY_DATA_SOURCE_ID:-3c7af733-b069-4654-b98e-beb5afde588c}"
PROJECT="${PHARMACY_PROJECT_ID:-4ad7a5fa-a036-4f6a-8229-39a20af23e38}"
CONTAINER="${DAAB_PG_CONTAINER:-daab-postgres}"
EXPECTED_TABLES="${EXPECTED_TABLES:-25}"

post() {
  curl -fsS -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d "$2" "$API$1" > /dev/null
}

list_jobs() { curl -fsS -H "Authorization: Bearer $KEY" "$API/api/v1/data-sources/$DS/sync-jobs"; }

wait_job() {  # $1 = job_type (schema_extraction | schema_sync | kg_generation), $2 = JSON array of job ids seen before
  local status="none"
  for _ in $(seq 1 120); do
    status="$(list_jobs | jq -r --arg t "$1" --argjson seen "$2" \
      '[.[] | select(.job_type == $t and ((.id as $i | $seen | index($i)) == null))][0].status // "none"')"
    case "$status" in
      completed) echo "$1 completed"; return 0 ;;
      failed) echo "$1 failed" >&2; return 1 ;;
    esac
    sleep 5
  done
  echo "$1 did not finish (last status: $status)" >&2
  return 1
}

seen="$(list_jobs | jq -c '[.[].id]')"
post "/api/v1/data-sources/$DS/extract-schema" '{"created_by":"pi-plan-a"}'
wait_job schema_extraction "$seen"
post "/api/v1/data-sources/$DS/sync-schema" '{"created_by":"pi-plan-a"}'
wait_job schema_sync "$seen"
post "/api/v1/data-sources/$DS/generate-kg" "{\"project_id\":\"$PROJECT\"}"
wait_job kg_generation "$seen"

PGUSER_NAME="$(docker exec "$CONTAINER" printenv POSTGRES_USER)"
q() { docker exec "$CONTAINER" psql -U "$PGUSER_NAME" -d ennam_kg -At -c "$1"; }
tables="$(q "SELECT count(*) FROM source_tables st JOIN source_schemas ss ON ss.id = st.source_schema_id WHERE ss.data_source_id = '$DS'")"
nodes="$(q "SELECT count(*) || '/' || count(DISTINCT title) FROM latest_knowledge_nodes WHERE project_id = '$PROJECT' AND node_type = 'architecture' AND title LIKE 'public.%'")"
echo "source_tables=$tables architecture_nodes(total/distinct)=$nodes"
if [ "$tables" != "$EXPECTED_TABLES" ] || [ "$nodes" != "$EXPECTED_TABLES/$EXPECTED_TABLES" ]; then
  echo "expected $EXPECTED_TABLES source tables and $EXPECTED_TABLES/$EXPECTED_TABLES architecture nodes" >&2
  exit 1
fi
```

```bash
chmod +x scripts/demo_data/resync_daab_schema.sh && bash -n scripts/demo_data/resync_daab_schema.sh
```

- [ ] **Step 5: Chạy đồng bộ (test của bước này là kiểm đếm cuối script)**

```bash
DAAB_API_KEY=<key> scripts/demo_data/resync_daab_schema.sh
```
Expected:
```text
schema_extraction completed
schema_sync completed
kg_generation completed
source_tables=25 architecture_nodes(total/distinct)=25/25
```
Nếu số node là `46/25` hoặc tương tự (nhân đôi) ⇒ dừng, ghi lại bằng `kg_store_discovery` và báo — không tự xoá node.

Sau đó chạy lại câu đếm mô tả cột đã curate ở Step 1 (cùng lệnh `SELECT count(*) FILTER (WHERE coalesce(sc.user_description, '') <> '') …`). Expected: **không nhỏ hơn** số đã ghi ở Step 1. Nếu giảm ⇒ dừng, báo lại; khôi phục metadata từ `$B/ennam_kg.before-pi-A.dump` cần quyết định của chủ sở hữu DAAB (restore toàn bộ `ennam_kg` ghi đè mọi thay đổi KG sau thời điểm backup) — không tự restore.

- [ ] **Step 6: Đường lùi (chỉ khi Step 2–5 lỗi)**

```bash
PGU="$(docker exec daab-postgres printenv POSTGRES_USER)"
docker exec daab-postgres psql -U "$PGU" -d postgres -c "DROP DATABASE IF EXISTS pharmacy_demo WITH (FORCE)"
docker exec daab-postgres createdb -U "$PGU" pharmacy_demo
docker exec -i daab-postgres pg_restore -U "$PGU" -d pharmacy_demo --no-owner \
  < "$B/pharmacy_demo.before-pi-A.dump"   # B = đường dẫn đã echo ở Step 1 (đặt lại bằng chuỗi literal nếu mở shell mới)
EXPECTED_TABLES=21 DAAB_API_KEY=<key> scripts/demo_data/resync_daab_schema.sh
```
Expected: `source_tables=21 architecture_nodes(total/distinct)=…` — node của 4 bảng mới (nếu đã tạo) còn lại trong KG; ghi chú vào checkpoint.

- [ ] **Step 7: Commit**

```bash
git add scripts/demo_data/resync_daab_schema.sh
git commit -m "feat(demo-data): DAAB schema resync script for the reloaded pharmacy_demo"
```

- [ ] **Step 8: Ghi nhận** — `kg_store_task` (status done, nêu commit + đường dẫn backup) và checkpoint Serena `mcp__serena__write_memory("checkpoint/<agent>-<YYYY-MM-DD>", …)` theo CLAUDE.md, gồm: đường dẫn backup, số dòng, kết quả Step 5, và các Open question còn mở (OQ-2 là blocking cho master M5).

---
## Self-Review

### Độ phủ phạm vi (yêu cầu của Plan A + spec §8)

| Yêu cầu | Task | Bằng chứng |
|---|---|---|
| Tìm generator gốc; quyết định tái dùng hay viết mới (OD-7) | — (khảo sát) → Task 1–6 | Không có generator ⇒ viết mới, seed 20260801, Python/uv |
| Lịch sử 12 tháng 2025-08-01 → 2026-07-31, mùa vụ tuần/tháng (OD-5, §8.1) | 3, 4, 6 | `test_window.py` (đủ mọi cửa hàng × mọi ngày, thứ Bảy ≥ 1,08× thứ Ba, đỉnh tháng 12) |
| Giữ 7 finding + PH-004 sụt tháng 7 | 3, 6 | `test_plants.py` (12 test, dương + âm), `test_preserve.py` |
| Dọn 2 giao dịch lạc tháng 8 | 1, 10 | `load_base` bỏ 3 receipt rác; nạp lại từ CSV xoá dòng chỉ có trong DB; `verify_plants.sql` `bad_ids = 0` |
| Lịch sử giá vốn + kịch bản "giá vốn +8% ở ~5 thuốc Rx một cửa hàng, reimbursement đứng yên" (§8.3–8.4) | 2, 4 | `product_costs` + `prescriptions.acquisition_cost`; `test_margin_plant.py` |
| Vendor + nhập hàng (receipt movement) + lead time (§8.2–8.3) | 2, 5 | `vendors.lead_time_days`, `purchase_orders`, movement `RECEIPT`; `test_inventory.py` |
| Snapshot tồn kho hằng tuần (§8.2) | 5 | 52 thứ Sáu sinh thêm + snapshot gốc 2026-07-31 = 53 ngày; `test_window.py`, `test_inventory.py` |
| Lương theo giờ (§8.3) | 2 | `employees.hourly_wage`; lương ≈ 12–18% doanh thu (đo trên prototype) |
| Lot/expiry (tuỳ chọn) | — | **Không làm** — xem OQ-7 |
| Chỉ thêm bảng/cột, không đổi tên | 9 | `extension.sql` chỉ `ADD`/`CREATE`; `test_integrity.py::test_new_columns_are_appended_last` |
| `targets.xlsx` (net_sales, gross_margin_pct theo cửa hàng × tháng) (§8.7, hợp đồng master) | 6, 7 | `test_targets.py` (1 sheet; header `Store ID \| Metric Key \| Period \| Target Value`; định dạng dài 170 dòng, 1 dòng/store×tháng×metric; Period là ngày đầu tháng; % thang 0–100 không định dạng %; chỉ PH-004 2026-07 hụt, hụt ≥ 30% cho FND-008) |
| `expected_findings.csv` thêm margin plant + checker `PASS n/n` (§8.5, master M5) | 8 | FND-008, FND-009, cột `rule_ids`; `check-expected-findings.test.ts` (8 test) |
| Quy trình nạp lại an toàn (backup `~/Backups/EnnamKG/`, pg_dump trước khi thay) + DAAB re-sync | 9, 10 | Guard backup, diễn tập container tạm, so số dòng, extract → sync → generate-kg + đếm node |
| Bảng độ phủ §7.3: FND-001..007 + "PH-004 sales decline" ✅; "PH-004 expired stock" ❌ | 8 | 9 dòng expected = 7 cũ + FND-008 (sales decline) + FND-009 (margin); expired stock không có dòng (đúng ❌ của spec) |

Quét placeholder: không có "TBD"/"TODO"/"tương tự Task N"; mọi hàm được gọi đều được định nghĩa trong plan; tên hàm khớp giữa các task (`prepare_catalog`, `generate_sales`, `generate_refunds`, `generate_shifts`, `generate_prescriptions`, `add_acquisition_cost(ctx, original_ids)`, `simulate_inventory(ctx, vendors)`, `generate(base_dir, out_dir, seed)`). Hợp đồng §2 của master không bị đổi.

### Open questions (không tự quyết — cần chủ sở hữu trả lời)

- **OQ-1 (ĐÃ GIẢI QUYẾT ở master): "ngày hiện tại" của demo.** Master đã chốt `as_of` = ngày dữ liệu cuối, bao gồm (`2026-07-31`), độ tươi đánh giá theo `as_of`, `to = as_of + 1`; master Task M4 đặt `kg-packs set-as-of --date 2026-07-31` trước backfill. Plan A khớp quy ước này (`HISTORY_END = 2026-07-31`). Còn lại: Plan D phải dùng thứ tự `business_project.asOfOverride` → `as_of` của provider thay cho `asOfDate(now)` (bản nháp cũ trả `2026-10-01`).
- **OQ-2 (BLOCKING FND-009 — Plan B): giá vốn Rx theo thời gian phải tới được metric.** Spec §6.2 định nghĩa *acquisition cost = `prescription.quantity × product.unit_cost`* (một giá vốn/sản phẩm) ⇒ +8% (chỉ có trong `product_costs`/`acquisition_cost`) **không bao giờ** tới `pharmacy.rx_cost`/`rx_margin`/`reimbursement_gap`. Đề xuất: pack `pharmacy` mở rộng canonical `prescription` thêm field `acquisition_cost` (map từ `prescriptions.acquisition_cost`), metric dùng field đó; hoặc canonical entity `product_cost` có hiệu lực theo ngày + cửa hàng. Không xử lý ⇒ M5 không thể `PASS 9/9`.
- **OQ-3 (Plan D): cách so sánh của PH-MARGIN-001.** Trên dữ liệu này, $ margin cộng dồn cấp cửa hàng (14 ngày vs 28 ngày trước) dao động ±10–18% ở cửa hàng **không** cài plant (đo trên 4 seed), trong khi margin % ở các cửa hàng đó chỉ lệch ≤ 1% tương đối và gap/đơn vị theo sản phẩm của 5 thuốc giảm 57–68%. Đề xuất rule dùng metric `ratio` (margin %) hoặc `reimbursement_gap` theo `product_id` chuẩn hoá theo số lượng; nếu dùng $ cộng dồn cấp cửa hàng sẽ có finding giả hoặc bỏ sót.
- **OQ-4: mức severity của FND-008/FND-009.** Request không cho ⇒ để trống trong CSV; checker không dùng severity để khớp, chỉ để chặn `critical` ngoài danh sách. Nếu Plan D gán `critical` cho một rule nằm ngoài `rule_ids` của dòng tương ứng (ví dụ RET-SALES-006 store ranking cho PH-004) thì M5 fail — cần bổ sung `rule_ids` khi Plan D chốt danh sách rule.
- **OQ-5 (DAAB, ngoài P0): trần `valueHintMaxColumns = 120`** (`ennam.kg.go/internal/service/value_hints.go`). Đã có 133 cột ứng viên (checkpoint 2026-08-17); thêm 2 cột + 4 bảng mới đẩy thêm cột khỏi value-hints ⇒ chất lượng NL→SQL (Ask LAAM ngoài catalog) có thể giảm. Mô tả AI cho 4 bảng mới cũng chưa được curate (`decisions/daab-column-descriptions-curation`).
- **OQ-6: phạm vi lịch sử của một số bảng.** `receipts` (reprint), `invoices`, `audit_events` chỉ sinh Original receipt cho giao dịch mới; reprint/invoice/audit chỉ có trong 2026-05..07 như gói gốc. Rule `RET-X-REPRINT-001` và câu hỏi Q13–Q17 vì vậy chỉ có 3 tháng dữ liệu — chấp nhận cho beta? Tồn kho Rx cũng không mô phỏng (gói gốc không có movement cho đơn thuốc) ⇒ RET-INV-003 (stockout) chỉ áp dụng cho hàng front-store.
- **OQ-7: lot/expiry.** Không thêm bảng lô/hạn dùng vì spec §7.3 đánh dấu "PH-004 expired stock" ❌ và rule expiry không có trong beta rule set; dấu vết duy nhất vẫn là `inventory_snapshots.expired_quantity` (2026-07-31, 31 sản phẩm PH-004). Cần nếu khách muốn demo finding hết hạn.
- **OQ-8: thay đổi chain-wide giá vốn +1,5% ngày 2026-01-01** (kèm giá bán/reimbursement +1,5% nên margin không đổi) là nền "bình thường" cho RET-VENDOR-001. Ngưỡng RET-VENDOR-001 chưa có trong request ⇒ nếu ngưỡng < 1,5% rule sẽ bắn trên toàn chuỗi (không phải `critical` theo checker, nhưng làm nhiễu brief).
- **OQ-9 (ĐÃ CHỐT): commit CSV sinh ra (~45 MB) vào repo workspace** — coordinator chấp nhận; giữ `test_committed_csvs_match_generator`.
- **OQ-10: ngưỡng proxy/liên tục được hiệu chỉnh ở seed 20260801** (cả 62 test pass). Thử seed 1–4 với acceptance test: seed 4 pass hết; seed 1–3 fail 1–2 test (`test_sales_per_day_never_collapse_month_to_month`, `test_april_to_may_sales_have_no_step`, `test_shrink_continues_through_may_and_june`, `test_fnd008_ph004_july_sales_decline`) vì ngưỡng liên tục chặt (±10%, −15%/ngày). Seed là một phần hợp đồng; đổi seed phải chạy lại toàn bộ test trước khi commit dữ liệu.
- **OQ-11 (phụ thuộc Plan B): định nghĩa metric mà `targets.xlsx` giả định.** Target được hiệu chỉnh với *net sales* = Σ`transaction_items.line_total` (không thuế, bỏ dòng sản phẩm `prescription_required`) và *gross margin %* = (Σ`line_total` − Σ`quantity × transaction_items.unit_cost`) / Σ`line_total`, cùng bộ lọc; biên margin chỉ 0,5 điểm. Nếu `retail.net_sales`/`retail.gross_margin_pct` của Plan B tính khác (ví dụ dùng `products.unit_cost` — khác giá vốn theo dòng ở dữ liệu gốc tháng 5–7, hoặc lấy `transactions.subtotal − discount_amount`) thì RET-MARGIN-001 có thể bắn ở mọi cửa hàng ⇒ Plan B cần dùng đúng hai định nghĩa trên, hoặc báo lại để sinh lại target.
- **OQ-12 (ĐÃ ĐÓNG): extract-schema giữ mô tả cột đã curate** — coordinator đã xác minh `source_columns.user_description` còn nguyên sau extraction. Task 10 vẫn giữ bước đếm trước/sau làm kiểm tra rẻ.
