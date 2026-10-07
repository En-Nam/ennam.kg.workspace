# DAAB Tabular Upload ("Dữ liệu bảng") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Màn hình Knowledge Sources nhận file CSV/XLSX/XLS ở chế độ **"Dữ liệu bảng"**. Toàn bộ dòng được parse, đoán kiểu và lưu vào `file_dataset`/`file_dataset_row` (JSONB). DAAB kiểm tra file theo mapping `mode=file` và trả báo cáo về UI, ghi `data_status` subject `file:<dataset>`, cung cấp `SourceTable` (mode=file) cho compiler của Plan B, rồi kích hoạt metric runner. Demo: `demo_mockdata/targets.xlsx` → dataset `store_targets` → entity `target`.

**Architecture:** Next.js gửi thêm `ingest_mode/dataset_name/write_mode` trong FormData; proxy chuyển nguyên. Go `ingest_upload.go` rẽ nhánh `tabular`: kiểm tra quyền project, nới write deadline, lưu file gốc (ObjectStorage + `uploaded_files`, **không tạo draft**). Sau đó Go gọi **đồng bộ** endpoint mới của Python indexer `POST /api/v1/tabular/parse` (openpyxl + xlrd, chạy trong thread). Python trả về các sheet đã chuẩn hoá: header snake_case, kiểu cột, giá trị là chuỗi chuẩn hoặc null. Gói Go mới `internal/intel/filedata` (core, không chứa từ ngữ ngành) lo việc ghi append/replace trong một transaction (COPY), validate theo mapping + canonical + enum, implement `intel.SourceTable`/`intel.SourceResolver` cho `intel.ModeFile` (đăng ký trong `buildIntel` của Plan B), ghi `data_status` subject `file:<dataset>` qua writer chung `intelstore.Store.UpsertDataStatus`, và gọi `intel.RunTrigger` (scheduler của B, không chặn) sau commit.

**Tech Stack:** Go 1.25 (stdlib `net/http`, `database/sql`, `lib/pq` COPY, `google/uuid`, golang-migrate) · Python 3.12 (FastAPI, openpyxl, **xlrd ≥ 2.0** mới, pytest; dev: **xlwt** để sinh fixture `.xls`) · NextJS 16 / React 19 / TanStack Query / Tailwind 4 · PostgreSQL 16.

**Spec:** `docs/superpowers/specs/2026-09-25-industry-pack-proactive-intelligence-design.md` (rev 4: §2.1 F2, §2.4 I10, §6.1 "file", §6.3, §13)
**Master:** `docs/superpowers/plans/2026-10-02-proactive-intelligence-master.md` (§2.2, §2.3 migration 000092 — **khoá**, §4 M4 Step 3)
**Plan B (đã xong, tên cuối):** `docs/superpowers/plans/2026-10-02-pi-B-daab-metrics-layer.md` mục **"Exports cho Plan C"** — package `intel` (`internal/intel/source.go`: `SourceTable`, `SourceResolver`, `BoundSource`, `QueryExecutor`, `ErrSourceNotReady`, `MappingError`, `RunTrigger`), `sqlexec.New`, `(*intelstore.Store).UpsertDataStatus`/`ListMappings`, `(*intel.Registry)`, `buildIntel` (`cmd/kg-server/intel_wiring.go`).

## Global Constraints

- Migration **`000092_file_tables`** viết **đúng nguyên văn** master §2.3: hai bảng `file_dataset`, `file_dataset_row`, không thêm cột, index hay bảng nào. Cần thêm schema thì sửa master trước.
- Core không chứa từ ngữ ngành (D10). `ennam.kg.go/internal/intel/filedata/**` bị script M3 quét. Từ ngữ ngành chỉ được xuất hiện trong `testdata/` và `*_test.go`.
- **Không cắt dữ liệu âm thầm.** Không có giới hạn 50.000 ký tự trên nhánh bảng. Vượt `MaxDatasetRows = 200_000` dòng (mỗi dataset, tính sau khi append) ⇒ **lỗi, không ghi dòng nào** (giống quy tắc `Truncated=true` là lỗi của master).
- Replace/append của mọi sheet trong một file chạy trong **một transaction**: lỗi ở bất kỳ bước nào ⇒ dữ liệu cũ còn nguyên.
- Python chỉ trả **chuỗi đã chuẩn hoá hoặc JSON null**: `integer` (vừa int64), `numeric`, `boolean` (`true`/`false`), `date` (`YYYY-MM-DD`), `timestamp` (`YYYY-MM-DDTHH:MM:SS[.ffffff]`, không múi giờ), `text`. Go **không suy lại kiểu**. `FileTable.ColumnSQL` ép về đúng kiểu đã lưu, và compiler B bọc thêm `CAST(… AS <kiểu canonical>)`. Phép cast này **luôn thành công** khi `castable(kiểu cột, kiểu canonical)` đúng; resolver và validation kiểm tra điều đó trước.
- **NFR-242** (`TestClassifyUploadFile_AllFormatsDeferExtract`: Go không tự extract) giữ nguyên. Go không parse file. `classifyUploadFile` **không đổi**: `.xls` chỉ được nhận ở nhánh bảng, còn nhánh tài liệu vẫn trả 400 cho `.xls`. Điểm lệch có chủ ý: request upload **chờ** indexer parse xong (đồng bộ) để trả báo cáo validate trong cùng response (xem Open question Q2).
- Endpoint parse của indexer chạy parse trong `asyncio.to_thread`, để một workbook lớn không chặn `/api/v1/embeddings` (Go gọi endpoint này với timeout 10s cho search). Client parse phía Go có timeout riêng là `ParseTimeout = 120s`, không dùng chung client embed.
- Write timeout của server là 10s ở production (`config/environments/production.yaml:13`). Chỉ nhánh bảng được nới bằng `http.NewResponseController(w).SetWriteDeadline(+3 phút)`. ReadTimeout (đọc body upload) **không đổi** (Open question Q3).
- Mọi upload kiểm tra `requireProjectAccess` **và** `requireProjectRole(…, ProjectMemberRoleDeveloper, …)` trên `projectId` ở path, **trước** `ParseMultipartForm`. Nhánh bảng **bắt buộc đúng 1 file** và chạy với context có hạn `tabularWriteDeadline − 15s`.
- Endpoint parse của indexer (cổng 8081 được publish) so token với `KG_INTERNAL_TOKEN` (dùng chung với kg-server) và từ chối body > 50 MiB. Reader stream với giới hạn dòng/cột, gọi `reset_dimensions()`, và đổi mọi lỗi parser của file hỏng thành `unreadable` (422, không phải 503).
- Sau một upload bảng thành công, gọi `intel.RunTrigger.Trigger(projectID)` (scheduler của B, đẩy vào hàng đợi, không chặn) **sau commit**, đúng một lần. **Không** gọi khi có entity `blocked`, khi validation lỗi, hoặc khi lớp metrics tắt (scheduler nil — không bao giờ đưa typed-nil vào interface).
- Mapping `mode=file`: mỗi field là **tên cột trần** của dataset (hợp đồng của B). Resolver trả lỗi bọc `intel.ErrSourceNotReady` (entity `incomplete`) cho **mọi** vấn đề dữ liệu: chưa upload, thiếu cột, kiểu không ép được. Resolver **không** trả `*intel.MappingError`, vì runner B biến lỗi đó thành mapping `broken` vĩnh viễn, trong khi upload lại file đúng là đủ sửa.
- `data_status` chỉ ghi qua writer chung `(*intelstore.Store).UpsertDataStatus`; Plan C không có writer riêng, và chỉ ghi subject `file:<dataset>` (runner B là nơi duy nhất ghi `entity:`/`metric:`).
- Thứ tự migration: 000088–000091 của B (000088 tạo cả `project_intel_settings`) **trước** 000092; Task 1 có cổng kiểm tra.
- DAAB dev DB ở cổng **5433**. Migration: `KG_DB_PORT=5433 go run ./cmd/kg-migrate/ up`. Test DB đọc `KG_TEST_DATABASE_URL` (store/intel). Test bị SKIP vẫn báo `ok` ở cấp package ⇒ luôn chạy với `-v` và grep `SKIP`.
- Sub-project là git repo lồng nhau: commit bằng `git -C ennam.kg.go|ennam.kg.python|ennam.kg.next`. Không `git add` file đã bẩn từ trước task (memory `preexisting-uncommitted-changes-before-git-add`): chỉ add đúng đường dẫn liệt kê trong task.
- `ennam.kg.next` **không có test runner** (package.json chỉ có `dev/build/start/lint`). Kiểm chứng UI bằng `npx tsc --noEmit`, `npm run lint` và kiểm tra trên trình duyệt. Không tự thêm framework test.

## Review Focus

1. **Replace hỏng giữa chừng xoá mất bảng cũ.** Dòng cũ bị `DELETE`, sau đó COPY lỗi. Ghim bằng test `TestStoreWrite_ReplaceFailureKeepsOldRows` và `TestStoreWrite_MultiSheetFailureWritesNothing` (Task 6).
2. **Cắt dòng âm thầm** (file lớn, append dồn quá giới hạn). Ghim bằng `test_parse_row_cap_is_an_error_not_a_truncation` (Task 3), `TestStoreWrite_AppendOverCapWritesNothing` (Task 6), `TestHandleUpload_TabularRowCapIs413` (Task 10).
3. **Đoán kiểu sai** khiến metric lỗi lúc chạy, mất số 0 đầu (`00123`), hoặc ngày bị lệch. Ghim bằng `test_infer_keeps_leading_zero_codes_as_text` (Task 2), `TestCastable` + `TestValidate_TextColumnCannotFeedNumericField` (Task 7), `TestResolver_BadColumnTypeIsNotReadyNotMappingError` (Task 8), `TestParity_FileModeMatchesLiveMode` (Task 11; có ô rỗng và mốc giờ qua nửa đêm).
4. **Runner không chạy sau upload, hoặc chạy trên dữ liệu `blocked`; target sai mã metric bị bỏ qua âm thầm** (`metric_key` ngoài enum ⇒ metric target của B không có dòng nào). Ghim bằng `TestValidate_ValuesOutsideTheEnumAreIncomplete` (Task 7), `TestIngest_TriggersRunnerOnceAfterCleanUpload`, `TestIngest_BlockedValidationDoesNotTrigger` và `TestIngest_WriteErrorDoesNotTriggerOrWriteStatus` (Task 9).
5. **Ghi dòng vào project của người khác, hoặc viewer ghi được** (path `projectId` không được middleware kiểm tra; `requireProjectAccess` cho mọi member qua). Ghim bằng `TestUpload_TabularDeniedForProjectOutsideKeyScope` + `TestUpload_ViewerCannotUpload` (Task 10).

---

## File Structure

```text
ennam.kg.go/
├── db/migrations/000092_file_tables.{up,down}.sql                 (Task 1)
├── internal/intel/filedata/                                        (core, trung tính ngành)
│   ├── types.go            Column, ParsedSheet, ParseResult, lỗi, widenType, regex   (Task 5)
│   ├── parser_client.go    HTTP client → Python /api/v1/tabular/parse                (Task 5)
│   ├── store.go            Write (append/replace, COPY, 1 tx), GetByName, LoadRows   (Task 6)
│   ├── validate.go         Validate(...) → EntityReport (thuần, không DB)             (Task 7)
│   ├── source_table_cast.go pgType/pgDataType/castable (bảng ép kiểu an toàn)        (Task 7)
│   ├── source_table.go     FileTable (implements intel.SourceTable)                  (Task 8)
│   ├── resolver.go         Resolver (implements intel.SourceResolver, ModeFile)       (Task 8)
│   ├── canonical.go        CanonicalSource + adapter *intel.Registry (fields + enums) (Task 8)
│   ├── service.go          Service.Ingest: parse → write → validate → status → RunTrigger (Task 9)
│   ├── *_test.go           unit + integration (KG_TEST_DATABASE_URL)
│   └── testdata/{sales_small.parsed.json, net_sales_metric.sql}
├── internal/service/file_upload.go          nhánh tabular trong HandleUpload           (Task 10)
├── internal/service/file_upload_tabular_test.go                                       (Task 10)
├── internal/handler/ingest_upload.go        đọc ingest_mode…, quyền, write deadline     (Task 10)
├── internal/handler/ingest_upload_tabular_test.go                                     (Task 10)
├── cmd/kg-server/intel_wiring.go            buildIntel: resolvers[intel.ModeFile] + service (Task 10)
└── cmd/kg-server/main.go                    nối tabularSvc + role resolver vào upload  (Task 10)

ennam.kg.python/
├── pyproject.toml, uv.lock                  + xlrd, + dev xlwt                         (Task 3)
├── src/ennam_kg/ingestion/tabular/{__init__,headers,infer,reader}.py                  (Task 2–3)
├── src/ennam_kg/api/tabular.py, src/ennam_kg/main.py                                  (Task 4)
└── tests/ingestion/test_tabular_{headers,infer,reader}.py, tests/test_tabular_api.py
    tests/ingestion/fixtures/tabular/{sales_small.csv, sales_small.parsed.json, semicolon_bom.csv}

ennam.kg.next/
├── src/lib/tabular-upload.ts                 đoán chế độ, gợi ý tên dataset, kiểm tra   (Task 12)
├── src/hooks/use-upload-files.ts             field mới + kiểu union                      (Task 12)
├── src/components/sources/upload-dropzone.tsx  bảng chọn "Tài liệu"/"Dữ liệu bảng"     (Task 12)
└── src/components/sources/tabular-upload-report.tsx  báo cáo validate                    (Task 12)
   (proxy src/app/api/kg/projects/[id]/ingest/upload/route.ts chuyển nguyên FormData — KHÔNG sửa)
```

**Quyết định parse ở đâu: Python indexer, gọi đồng bộ qua HTTP.**
- `ennam.kg.go/go.mod` không có thư viện Excel nào. Thư viện `.xls` cho Go ít được bảo trì. Python đã có `openpyxl>=3.1` (`pyproject.toml:31`) và đã đọc XLSX (`adapters/files.py:_extract_xlsx`). `xlrd 2.0.2` đọc `.xls` ổn định (đã kiểm tra bằng `uv run --with xlwt --with xlrd` trên Python 3.12.12: ghi và đọc lại được ô ngày tháng, `ctype=XL_CELL_DATE`).
- **Không đi qua worker queue.** Migration 000092 bị khoá, chỉ có hai bảng, không có cột trạng thái hay lỗi. Nếu parse bất đồng bộ thì không có chỗ ghi "parse lỗi" hoặc báo cáo validate khi chưa có mapping, trừ khi thêm migration 000093 (có rủi ro trùng số với Plan B). Gọi đồng bộ thì báo cáo nằm ngay trong response upload. Go đã có tiền lệ gọi đồng bộ indexer `KG_PYTHON_URL` (`embed.Client`, `main.go:382-386`; `SSEStreamService`, `main.go:950-954`).
- Ghi DB, validate, ghi `data_status` và trigger đều ở Go: dùng chung transaction và quyền truy cập, Python không ghi thẳng vào DB `ennam_kg`.

**Package:** `internal/intel/filedata` (B gợi ý `filesource`; tên package không thuộc hợp đồng, B chỉ cần resolver đăng ký vào `resolvers[intel.ModeFile]`).

---

### Task 1: Migration 000092 `file_dataset` + `file_dataset_row`

**Files:**
- Create: `ennam.kg.go/db/migrations/000092_file_tables.up.sql`
- Create: `ennam.kg.go/db/migrations/000092_file_tables.down.sql`

**Interfaces:**
- Consumes: bảng `projects(id UUID)`. Migration 000088–000091 của Plan B (000088 tạo `pack_install` + `project_intel_settings`) phải có trước (golang-migrate chạy theo thứ tự số).
- Produces: `file_dataset`, `file_dataset_row` đúng master §2.3.

- [ ] **Step 1: Kiểm tra trạng thái hiện tại (phải chưa có bảng)**

```bash
psql "postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable" -c '\d file_dataset'
```
Expected: `Did not find any relation named "file_dataset".`

- [ ] **Step 2: Viết migration up (nguyên văn master §2.3)**

`ennam.kg.go/db/migrations/000092_file_tables.up.sql`:
```sql
-- Plan C (Proactive Intelligence): rows of customer-uploaded tabular files ("Dữ liệu bảng").
-- OD-2 beta decision: rows are stored as JSONB in one shared table; no runtime DDL.
-- Schema is locked by docs/superpowers/plans/2026-10-02-proactive-intelligence-master.md §2.3.
CREATE TABLE file_dataset (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  columns JSONB NOT NULL,
  write_mode TEXT NOT NULL CHECK (write_mode IN ('append','replace')),
  row_count INT NOT NULL DEFAULT 0,
  source_file_id UUID, uploaded_by TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, name)
);
CREATE TABLE file_dataset_row (
  dataset_id UUID NOT NULL REFERENCES file_dataset(id) ON DELETE CASCADE,
  row_num INT NOT NULL,
  data JSONB NOT NULL,
  PRIMARY KEY (dataset_id, row_num)
);
```

`ennam.kg.go/db/migrations/000092_file_tables.down.sql`:
```sql
DROP TABLE IF EXISTS file_dataset_row;
DROP TABLE IF EXISTS file_dataset;
```

- [ ] **Step 3: Cổng thứ tự migration — chạy TRƯỚC `up`**

golang-migrate chỉ đi tiến từ version hiện tại. Nếu áp 000092 khi 000088–000091 của Plan B chưa có, DB sẽ ở version 92, và khi file của B tới sau, `up` sẽ **bỏ qua chúng vĩnh viễn** trên DB dev dùng chung (:5433). Vì vậy cổng kiểm tra phải chạy trước:
```bash
cd ennam.kg.go
ls db/migrations/000088_*.up.sql db/migrations/000089_*.up.sql db/migrations/000090_*.up.sql db/migrations/000091_*.up.sql
KG_DB_PORT=5433 go run ./cmd/kg-migrate/ version
```
Expected: `ls` liệt kê đủ **4 file**, `version` in ra **≥ 91**. Thiếu file hoặc version < 91 ⇒ **dừng, không chạy `up`**, báo người điều phối (Plan B chưa xong migration). Không tự đánh số lại.

- [ ] **Step 4: Chạy up → down → up trên DB dev (5433)**

```bash
cd ennam.kg.go
KG_DB_PORT=5433 go run ./cmd/kg-migrate/ up && KG_DB_PORT=5433 go run ./cmd/kg-migrate/ version
KG_DB_PORT=5433 go run ./cmd/kg-migrate/ steps -1 && KG_DB_PORT=5433 go run ./cmd/kg-migrate/ up
psql "postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable" -c '\d file_dataset_row'
```
Expected: `version` in ra `92`; `\d file_dataset_row` có PK `(dataset_id, row_num)` và FK `ON DELETE CASCADE`. Làm tương tự cho DB test (`KG_TEST_DATABASE_URL`) nếu đó là DB khác.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add db/migrations/000092_file_tables.up.sql db/migrations/000092_file_tables.down.sql
git -C ennam.kg.go commit -m "feat(db): add file_dataset tables for tabular uploads (migration 000092)"
```

---

### Task 2: Python — chuẩn hoá header + suy kiểu cột

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/ingestion/tabular/__init__.py`
- Create: `ennam.kg.python/src/ennam_kg/ingestion/tabular/headers.py`
- Create: `ennam.kg.python/src/ennam_kg/ingestion/tabular/infer.py`
- Test: `ennam.kg.python/tests/ingestion/test_tabular_headers.py`, `ennam.kg.python/tests/ingestion/test_tabular_infer.py`

**Interfaces:**
- Produces:
  - `normalize_name(raw: str) -> str`
  - `unique_names(raw: list[str], fallback_prefix: str) -> list[str]`
  - `COLUMN_TYPES: tuple[str, ...]`
  - `cell_token(value: object) -> str | None`
  - `token_kind(token: str) -> str`
  - `infer_type(tokens: Iterable[str | None]) -> str`
  - `normalize_token(token: str | None, column_type: str) -> str | None`

- [ ] **Step 1: Viết test thất bại**

`ennam.kg.python/tests/ingestion/test_tabular_headers.py`:
```python
"""Header names become the JSON keys that mappings reference, so they must be
stable, ASCII snake_case and unique — a Vietnamese header must not turn into an
empty or colliding key."""

from __future__ import annotations

import pytest

from ennam_kg.ingestion.tabular.headers import normalize_name, unique_names


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Store ID", "store_id"),
        ("Mã cửa hàng", "ma_cua_hang"),
        ("Đơn giá", "don_gia"),
        ("netAmount", "net_amount"),
        ("StoreID", "store_id"),
        ("Net Amount (VND)", "net_amount_vnd"),
        ("2026 Target", "c_2026_target"),
        ("   ", ""),
        ("営業", ""),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_unique_names_suffixes_collisions_and_fills_blanks() -> None:
    assert unique_names(["Store", "store", "", "STORE"], "column") == [
        "store",
        "store_2",
        "column_3",
        "store_3",
    ]


def test_unique_names_stay_within_63_chars() -> None:
    long = "x" * 80
    names = unique_names([long, long], "column")
    assert names[0] == "x" * 63
    assert names[1] == "x" * 61 + "_2"
    assert all(len(n) <= 63 for n in names)
```

`ennam.kg.python/tests/ingestion/test_tabular_infer.py`:
```python
"""Column types decide which SQL casts DAAB emits over the stored JSON. A wrong
guess either breaks a metric at run time (cast error) or silently changes data
(leading zeros of a code dropped), so inference is conservative: anything not
cleanly typed stays text."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from ennam_kg.ingestion.tabular.infer import cell_token, infer_type, normalize_token


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, "true"),
        (False, "false"),
        (15000, "15000"),
        (5.0, "5"),
        (12500.5, "12500.5"),
        (Decimal("3.10"), "3.10"),
        (datetime(2026, 7, 1), "2026-07-01"),
        (datetime(2026, 7, 1, 9, 15), "2026-07-01T09:15:00"),
        (date(2026, 7, 1), "2026-07-01"),
        ("  a\x00b  ", "ab"),
        ("   ", None),
    ],
)
def test_cell_token(value: object, expected: str | None) -> None:
    assert cell_token(value) == expected


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["1", "2", None], "integer"),
        (["1", "2.5"], "numeric"),
        (["1e3", "-0.5"], "numeric"),
        (["99999999999999999999"], "numeric"),
        (["1e999999"], "text"),  # exponent would overflow PostgreSQL numeric
        (["TRUE", "false"], "boolean"),
        (["2026-07-01", "2026-07-02"], "date"),
        (["2026-07-01", "2026-07-01 10:00"], "timestamp"),
        (["2026-07-01T10:00:00.250000"], "timestamp"),
        (["2026-02-30"], "text"),
        (["1", "true"], "text"),
        (["1,234.5"], "text"),
        (["01/07/2026"], "text"),
        (["2026-07-01T10:00:00+07:00"], "text"),
        ([None, None], "text"),
        ([], "text"),
    ],
)
def test_infer_type(tokens: list[str | None], expected: str) -> None:
    assert infer_type(tokens) == expected


def test_infer_keeps_leading_zero_codes_as_text() -> None:
    # Postal / product codes: casting "00123" to a number would lose the zeros.
    assert infer_type(["00123", "07001"]) == "text"
    assert infer_type(["00123", "45"]) == "text"


@pytest.mark.parametrize(
    ("token", "column_type", "expected"),
    [
        (None, "integer", None),
        ("TRUE", "boolean", "true"),
        ("2026-07-01", "timestamp", "2026-07-01T00:00:00"),
        ("2026-07-01 09:15", "timestamp", "2026-07-01T09:15:00"),
        ("2026-07-01", "date", "2026-07-01"),
        ("10.50", "numeric", "10.50"),
        ("00123", "text", "00123"),
    ],
)
def test_normalize_token(token: str | None, column_type: str, expected: str | None) -> None:
    assert normalize_token(token, column_type) == expected
```

- [ ] **Step 2: Chạy test, phải FAIL**

```bash
cd ennam.kg.python && uv run pytest tests/ingestion/test_tabular_headers.py tests/ingestion/test_tabular_infer.py -q
```
Expected: FAIL do `ModuleNotFoundError: No module named 'ennam_kg.ingestion.tabular'`.

- [ ] **Step 3: Implement**

`ennam.kg.python/src/ennam_kg/ingestion/tabular/__init__.py`:
```python
"""Tabular ("Dữ liệu bảng") upload parsing: full rows, typed columns, no truncation."""
```

`ennam.kg.python/src/ennam_kg/ingestion/tabular/headers.py`:
```python
"""Header / sheet-title normalisation for tabular uploads.

Normalised names are the JSON keys stored in file_dataset_row.data and the
column names a project mapping references, so they must be ASCII snake_case,
unique within a sheet, and at most 63 characters.
"""

from __future__ import annotations

import re
import unicodedata

_MAX_NAME = 63
_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_name(raw: str) -> str:
    """Return a snake_case ASCII identifier, or "" when nothing usable remains."""
    text = raw.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _CAMEL.sub(r"\1_\2", text).lower()
    text = _NON_ALNUM.sub("_", text).strip("_")
    if text and text[0].isdigit():
        text = f"c_{text}"
    return text[:_MAX_NAME].rstrip("_")


def unique_names(raw: list[str], fallback_prefix: str) -> list[str]:
    """Normalise every name; blanks become <prefix>_<position>, collisions get _2, _3…"""
    used: set[str] = set()
    out: list[str] = []
    for position, value in enumerate(raw, start=1):
        base = normalize_name(value) or f"{fallback_prefix}_{position}"
        name = base
        k = 2
        while name in used:
            suffix = f"_{k}"
            name = f"{base[: _MAX_NAME - len(suffix)]}{suffix}"
            k += 1
        used.add(name)
        out.append(name)
    return out
```

`ennam.kg.python/src/ennam_kg/ingestion/tabular/infer.py`:
```python
"""Column type inference and value normalisation for tabular uploads.

Every stored value is either JSON null or a canonical string that PostgreSQL
casts without error to the column's inferred type — DAAB relies on that when it
emits `(data->>'col')::<type>`. Anything ambiguous (locale dates, thousands
separators, leading-zero codes, timezone offsets) stays text.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import Decimal

COLUMN_TYPES = ("text", "integer", "numeric", "boolean", "date", "timestamp")

_INT_RE = re.compile(r"-?(0|[1-9][0-9]*)")
# Exponent bounded to 3 digits: "1e999999" would overflow PostgreSQL numeric.
_NUM_RE = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]{1,3})?")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TS_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{1,6})?)?")
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_BOOL_TOKENS = frozenset({"true", "false"})


def cell_token(value: object) -> str | None:
    """Turn one raw cell (CSV string or spreadsheet value) into a string token or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        if value.tzinfo is None and value.time() == time(0):
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, Decimal):
        return str(value)
    text = str(value).replace("\x00", "").strip()
    return text or None


def token_kind(token: str) -> str:
    """Classify one non-empty token."""
    if token.lower() in _BOOL_TOKENS:
        return "boolean"
    if _INT_RE.fullmatch(token):
        return "integer" if _INT64_MIN <= int(token) <= _INT64_MAX else "numeric"
    if _NUM_RE.fullmatch(token):
        return "numeric"
    if _DATE_RE.fullmatch(token) and _is_date(token):
        return "date"
    if _TS_RE.fullmatch(token) and _is_timestamp(token):
        return "timestamp"
    return "text"


def infer_type(tokens: Iterable[str | None]) -> str:
    """Narrowest type every non-null token fits; all-null or mixed columns are text."""
    kinds: set[str] = set()
    for token in tokens:
        if token is None:
            continue
        kind = token_kind(token)
        if kind == "text":
            return "text"
        kinds.add(kind)
    if not kinds:
        return "text"
    if kinds == {"boolean"}:
        return "boolean"
    if kinds == {"integer"}:
        return "integer"
    if kinds <= {"integer", "numeric"}:
        return "numeric"
    if kinds == {"date"}:
        return "date"
    if kinds <= {"date", "timestamp"}:
        return "timestamp"
    return "text"


def normalize_token(token: str | None, column_type: str) -> str | None:
    """Rewrite a token into the canonical string form of its column type."""
    if token is None:
        return None
    if column_type == "boolean":
        return token.lower()
    if column_type == "date":
        return date.fromisoformat(token).isoformat()
    if column_type == "timestamp":
        if _DATE_RE.fullmatch(token):
            return f"{date.fromisoformat(token).isoformat()}T00:00:00"
        return datetime.fromisoformat(token).isoformat()
    return token


def _is_date(token: str) -> bool:
    try:
        date.fromisoformat(token)
    except ValueError:
        return False
    return True


def _is_timestamp(token: str) -> bool:
    try:
        datetime.fromisoformat(token)
    except ValueError:
        return False
    return True
```

- [ ] **Step 4: Chạy test, phải PASS**

```bash
cd ennam.kg.python && uv run pytest tests/ingestion/test_tabular_headers.py tests/ingestion/test_tabular_infer.py -q && uv run ruff check src/ennam_kg/ingestion/tabular tests/ingestion/test_tabular_headers.py tests/ingestion/test_tabular_infer.py
```
Expected: tất cả PASS; ruff `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.python add src/ennam_kg/ingestion/tabular/__init__.py src/ennam_kg/ingestion/tabular/headers.py src/ennam_kg/ingestion/tabular/infer.py tests/ingestion/test_tabular_headers.py tests/ingestion/test_tabular_infer.py
git -C ennam.kg.python commit -m "feat(tabular): header normalisation and conservative column type inference"
```

---

### Task 3: Python — đọc CSV/XLSX/XLS thành sheet có kiểu (đủ dòng)

**Files:**
- Modify: `ennam.kg.python/pyproject.toml`, `ennam.kg.python/uv.lock` (qua `uv add`)
- Create: `ennam.kg.python/src/ennam_kg/ingestion/tabular/reader.py`
- Create: `ennam.kg.python/tests/ingestion/fixtures/tabular/sales_small.csv`
- Create: `ennam.kg.python/tests/ingestion/fixtures/tabular/sales_small.parsed.json` (golden — **hợp đồng với Go**, bản sao giống hệt ở Task 5)
- Create: `ennam.kg.python/tests/ingestion/fixtures/tabular/semicolon_bom.csv`
- Test: `ennam.kg.python/tests/ingestion/test_tabular_reader.py`

**Interfaces:**
- Consumes: openpyxl (đã có), xlrd (thêm ở Step 1). **Không** dùng lại `_trim_trailing_empty` của `files.py`: hàm đó cần cả lưới trong bộ nhớ, còn reader phải stream.
- Bộ nhớ (đo 2026-10-02): openpyxl read-only đệm mỗi dòng tới độ rộng `<dimension>`; một xlsx 54 KB khai `A1:XFD5001` lên đỉnh **801 MB**, sau `ws.reset_dimensions()` còn 52 MB. Reader luôn reset dimension, stream từng dòng, dừng ở dòng thứ `max_rows+1` và ở cột vượt `MAX_COLUMNS`, áp dụng cho cả CSV, XLSX và XLS.
- Produces:
  - `class TabularParseError(ValueError)` có thuộc tính `code: str`. Các code: `unsupported_type`, `encoding`, `unreadable` (mọi lỗi của openpyxl/xlrd/csv với file hỏng hoặc dán nhãn sai), `no_data`, `row_cap_exceeded`, `column_cap_exceeded`.
  - `@dataclass(frozen=True) ParsedColumn(name, source_name, type)`
  - `@dataclass(frozen=True) ParsedSheet(sheet, key, columns, rows)` kèm `to_dict()`
  - `parse_tabular(path: Path, *, max_rows: int, max_columns: int = MAX_COLUMNS) -> list[ParsedSheet]` (`MAX_COLUMNS = 1000`)
  - Quy tắc: dòng 1 là header. Hàng/cột rỗng ở đuôi bị cắt. Hàng rỗng ở giữa được **giữ lại** (toàn null), nên dòng dữ liệu thứ i luôn ứng với dòng i+1 của file. Sheet không có dòng dữ liệu bị bỏ qua. Cả file không có dữ liệu ⇒ `no_data`. CSV có `sheet=""` và `key=""`.

- [ ] **Step 1: Thêm dependency**

```bash
cd ennam.kg.python && uv add "xlrd>=2.0.2" && uv add --dev "xlwt>=1.3.0"
```
Expected: `pyproject.toml` có `"xlrd>=2.0.2"` trong `dependencies` và `"xlwt>=1.3.0"` trong `[dependency-groups].dev`; `uv.lock` cập nhật.

- [ ] **Step 2: Viết fixture (đáp án viết tay)**

`ennam.kg.python/tests/ingestion/fixtures/tabular/sales_small.csv` (có ô `Net Amount` rỗng và mốc giờ qua nửa đêm):
```csv
Sale ID,Store ID,Sold At,Net Amount
S-1,PH-001,2026-07-01 09:15:00,10.50
S-2,PH-001,2026-07-01 23:30:00,4.25
S-3,PH-001,2026-07-02 00:15:00,7
S-4,PH-002,2026-07-01 12:00:00,
S-5,PH-002,2026-07-02 08:00:00,20.00
```

`ennam.kg.python/tests/ingestion/fixtures/tabular/sales_small.parsed.json`:
```json
{
  "sheets": [
    {
      "sheet": "",
      "key": "",
      "columns": [
        {"name": "sale_id", "source_name": "Sale ID", "type": "text"},
        {"name": "store_id", "source_name": "Store ID", "type": "text"},
        {"name": "sold_at", "source_name": "Sold At", "type": "timestamp"},
        {"name": "net_amount", "source_name": "Net Amount", "type": "numeric"}
      ],
      "rows": [
        ["S-1", "PH-001", "2026-07-01T09:15:00", "10.50"],
        ["S-2", "PH-001", "2026-07-01T23:30:00", "4.25"],
        ["S-3", "PH-001", "2026-07-02T00:15:00", "7"],
        ["S-4", "PH-002", "2026-07-01T12:00:00", null],
        ["S-5", "PH-002", "2026-07-02T08:00:00", "20.00"]
      ],
      "row_count": 5
    }
  ]
}
```

`ennam.kg.python/tests/ingestion/fixtures/tabular/semicolon_bom.csv`: tạo bằng lệnh sau để có BOM UTF-8 và dòng rỗng ở giữa:
```bash
cd ennam.kg.python && printf '\xef\xbb\xbfM\xc3\xa3 c\xe1\xbb\xada h\xc3\xa0ng;S\xe1\xbb\x91 l\xc6\xb0\xe1\xbb\xa3ng;M\xc3\xa3 b\xc6\xb0u ch\xc3\xadnh\nPH-001;3;00123\n;;\nPH-002;5;07001\n' > tests/ingestion/fixtures/tabular/semicolon_bom.csv && head -1 tests/ingestion/fixtures/tabular/semicolon_bom.csv
```
Expected: in ra `Mã cửa hàng;Số lượng;Mã bưu chính` (BOM ẩn).

- [ ] **Step 3: Viết test thất bại**

`ennam.kg.python/tests/ingestion/test_tabular_reader.py`:
```python
"""The tabular reader is the only place rows enter DAAB's file tables. It must
return EVERY data row (no 50,000-char cap like the document path), keep row
positions stable so validation can point at file lines, and fail loudly instead
of truncating."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from ennam_kg.ingestion.tabular.reader import TabularParseError, parse_tabular

_FIX = Path(__file__).parent / "fixtures" / "tabular"


def _as_dicts(path: Path, max_rows: int = 1000) -> list[dict[str, object]]:
    return [s.to_dict() for s in parse_tabular(path, max_rows=max_rows)]


def test_csv_matches_golden_contract_shared_with_go() -> None:
    golden = json.loads((_FIX / "sales_small.parsed.json").read_text(encoding="utf-8"))
    assert {"sheets": _as_dicts(_FIX / "sales_small.csv")} == golden


def test_csv_with_bom_semicolons_and_blank_middle_row() -> None:
    [sheet] = _as_dicts(_FIX / "semicolon_bom.csv")
    assert [(c["name"], c["source_name"], c["type"]) for c in sheet["columns"]] == [
        ("ma_cua_hang", "Mã cửa hàng", "text"),
        ("so_luong", "Số lượng", "integer"),
        ("ma_buu_chinh", "Mã bưu chính", "text"),
    ]
    # The blank middle row is kept so data row i always maps to file line i + 1.
    assert sheet["rows"] == [
        ["PH-001", "3", "00123"],
        [None, None, None],
        ["PH-002", "5", "07001"],
    ]


def test_xlsx_one_sheet_per_dataset_and_empty_sheets_skipped(tmp_path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Targets 2026"
    ws.append(["Store ID", "Month", "Target Value", "Active"])
    ws.append(["PH-001", datetime(2026, 7, 1), 15000, True])
    ws.append(["PH-002", datetime(2026, 7, 1), 12500.5, False])
    notes = wb.create_sheet("Notes")
    notes.append(["Only a header"])
    plan = wb.create_sheet("Kế hoạch")
    plan.append(["A"])
    plan.append([1])
    path = tmp_path / "targets.xlsx"
    wb.save(path)

    sheets = _as_dicts(path)

    assert [(s["sheet"], s["key"]) for s in sheets] == [
        ("Targets 2026", "targets_2026"),
        ("Kế hoạch", "ke_hoach"),
    ]
    first = sheets[0]
    assert [(c["name"], c["type"]) for c in first["columns"]] == [
        ("store_id", "text"),
        ("month", "date"),
        ("target_value", "numeric"),
        ("active", "boolean"),
    ]
    assert first["rows"] == [
        ["PH-001", "2026-07-01", "15000", "true"],
        ["PH-002", "2026-07-01", "12500.5", "false"],
    ]
    assert sheets[1]["rows"] == [["1"]]


def test_xls_dates_and_integral_floats(tmp_path: Path) -> None:
    import xlwt

    wb = xlwt.Workbook()
    ws = wb.add_sheet("Sheet1")
    date_style = xlwt.easyxf(num_format_str="YYYY-MM-DD")
    for col, header in enumerate(["Store", "Opened", "Staff"]):
        ws.write(0, col, header)
    ws.write(1, 0, "PH-001")
    ws.write(1, 1, date(2025, 1, 15), date_style)
    ws.write(1, 2, 12)
    ws.write(2, 0, "PH-002")
    ws.write(2, 1, date(2024, 11, 3), date_style)
    ws.write(2, 2, 9)
    path = tmp_path / "stores.xls"
    wb.save(str(path))

    [sheet] = _as_dicts(path)

    assert [(c["name"], c["type"]) for c in sheet["columns"]] == [
        ("store", "text"),
        ("opened", "date"),
        ("staff", "integer"),
    ]
    assert sheet["rows"] == [["PH-001", "2025-01-15", "12"], ["PH-002", "2024-11-03", "9"]]


def test_data_wider_than_header_gets_generated_column_names(tmp_path: Path) -> None:
    path = tmp_path / "wide.csv"
    path.write_text("a\n1,2\n", encoding="utf-8")
    [sheet] = _as_dicts(path)
    assert [c["name"] for c in sheet["columns"]] == ["a", "column_2"]
    assert sheet["rows"] == [["1", "2"]]


def test_parse_row_cap_is_an_error_not_a_truncation(tmp_path: Path) -> None:
    path = tmp_path / "big.csv"
    path.write_text("a\n1\n2\n3\n", encoding="utf-8")
    with pytest.raises(TabularParseError) as exc:
        parse_tabular(path, max_rows=2)
    assert exc.value.code == "row_cap_exceeded"


def test_header_only_file_is_no_data(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("a,b\n", encoding="utf-8")
    with pytest.raises(TabularParseError) as exc:
        parse_tabular(path, max_rows=10)
    assert exc.value.code == "no_data"


def test_non_utf8_csv_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "latin1.csv"
    path.write_bytes(b"a,b\n\xff,1\n")
    with pytest.raises(TabularParseError) as exc:
        parse_tabular(path, max_rows=10)
    assert exc.value.code == "encoding"


def test_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("a\n1\n", encoding="utf-8")
    with pytest.raises(TabularParseError) as exc:
        parse_tabular(path, max_rows=10)
    assert exc.value.code == "unsupported_type"


def test_corrupt_xlsx_is_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"not a zip file")
    with pytest.raises(TabularParseError) as exc:
        parse_tabular(path, max_rows=10)
    assert exc.value.code == "unreadable"


def _rewrite_zip_member(src: Path, dest: Path, member: str, rewrite) -> None:
    import zipfile

    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == member:
                data = rewrite(data)
            zout.writestr(item, data)


def test_inflated_dimension_hits_row_cap_without_padding_memory(tmp_path: Path) -> None:
    """Measured 2026-10-02: openpyxl read-only pads each row to <dimension>; a 54 KB
    file declaring A1:XFD5001 peaked at 801 MB. The reader must reset the
    dimension, stream, and stop at the row cap with bounded memory."""
    import re
    import tracemalloc

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for r in range(5001):
        ws.append([f"r{r}", r, r * 2, "x", 1.5])
    plain = tmp_path / "plain.xlsx"
    wb.save(plain)
    inflated = tmp_path / "inflated.xlsx"
    _rewrite_zip_member(
        plain,
        inflated,
        "xl/worksheets/sheet1.xml",
        lambda d: re.sub(rb'<dimension ref="[^"]*"/>', b'<dimension ref="A1:XFD5001"/>', d),
    )

    tracemalloc.start()
    try:
        with pytest.raises(TabularParseError) as exc:
            parse_tabular(inflated, max_rows=1000)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert exc.value.code == "row_cap_exceeded"
    assert peak < 50 * 1024 * 1024, f"peak {peak / 1e6:.0f} MB — dimension padding is back"


def test_inflated_dimension_does_not_add_columns(tmp_path: Path) -> None:
    import re

    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["a", "b"])
    wb.active.append([1, 2])
    plain = tmp_path / "plain.xlsx"
    wb.save(plain)
    inflated = tmp_path / "inflated.xlsx"
    _rewrite_zip_member(
        plain,
        inflated,
        "xl/worksheets/sheet1.xml",
        lambda d: re.sub(rb'<dimension ref="[^"]*"/>', b'<dimension ref="A1:XFD2"/>', d),
    )
    [sheet] = _as_dicts(inflated)
    assert [c["name"] for c in sheet["columns"]] == ["a", "b"]


def test_value_beyond_column_cap_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "wide.csv"
    path.write_text("a," + ",".join([""] * 1000) + "x\n1\n", encoding="utf-8")
    with pytest.raises(TabularParseError) as exc:
        parse_tabular(path, max_rows=10)
    assert exc.value.code == "column_cap_exceeded"


def test_zip_mislabeled_as_xls_is_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "fake.xls"
    path.write_bytes(b"PK\x03\x04" + b"\x00" * 200)  # truncated zip, not a BIFF file
    with pytest.raises(TabularParseError) as exc:
        parse_tabular(path, max_rows=10)
    assert exc.value.code == "unreadable"


def test_malformed_sheet_xml_is_unreadable(tmp_path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["a"])
    wb.active.append([1])
    plain = tmp_path / "plain.xlsx"
    wb.save(plain)
    broken = tmp_path / "broken_xml.xlsx"
    _rewrite_zip_member(
        plain,
        broken,
        "xl/worksheets/sheet1.xml",
        lambda _d: b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        b'<sheetData><row r="1"><c r="A1"',
    )
    with pytest.raises(TabularParseError) as exc:
        parse_tabular(broken, max_rows=10)
    assert exc.value.code == "unreadable"
```

- [ ] **Step 4: Chạy test, phải FAIL**

```bash
cd ennam.kg.python && uv run pytest tests/ingestion/test_tabular_reader.py -q
```
Expected: FAIL `ModuleNotFoundError: No module named 'ennam_kg.ingestion.tabular.reader'`.

- [ ] **Step 5: Implement**

`ennam.kg.python/src/ennam_kg/ingestion/tabular/reader.py`:
```python
"""Parse CSV / XLSX / XLS uploads into typed sheets ("Dữ liệu bảng").

Unlike the document path (adapters/files.py → one text blob capped at 50,000
chars), this returns every data row. Row 1 is the header. Rows are STREAMED with
hard caps (rows, columns) so a hostile or padded file fails with a clear error
instead of exhausting memory:

- openpyxl's read-only worksheet pads every row to the sheet's <dimension>
  width. Measured 2026-10-02: a 54 KB xlsx declaring A1:XFD5001 peaked at
  801 MB; with ws.reset_dimensions() the same file peaked at 52 MB. The
  dimension is therefore always reset and each row trimmed to its last value.
- Trailing empty rows/columns are dropped; empty rows in the middle are kept so
  data row i is always file line i + 1.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import xlrd
from xlrd.sheet import Cell

from ennam_kg.ingestion.tabular.headers import unique_names
from ennam_kg.ingestion.tabular.infer import cell_token, infer_type, normalize_token

MAX_COLUMNS = 1000
_CSV_DELIMITERS = ",;\t|"
_SNIFF_CHARS = 65536

Grid = list[list[str | None]]


class TabularParseError(ValueError):
    """A file that cannot become table rows; `code` is machine-readable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParsedColumn:
    name: str
    source_name: str
    type: str


@dataclass(frozen=True)
class ParsedSheet:
    sheet: str
    key: str
    columns: tuple[ParsedColumn, ...]
    rows: list[list[str | None]]

    def to_dict(self) -> dict[str, object]:
        return {
            "sheet": self.sheet,
            "key": self.key,
            "columns": [
                {"name": c.name, "source_name": c.source_name, "type": c.type}
                for c in self.columns
            ],
            "rows": self.rows,
            "row_count": len(self.rows),
        }


def parse_tabular(path: Path, *, max_rows: int, max_columns: int = MAX_COLUMNS) -> list[ParsedSheet]:
    """Parse every sheet with data; raise TabularParseError instead of truncating."""
    ext = path.suffix.lower()
    if ext == ".csv":
        grids = [("", _read_csv(path, max_rows, max_columns))]
    elif ext == ".xlsx":
        grids = _read_xlsx(path, max_rows, max_columns)
    elif ext == ".xls":
        grids = _read_xls(path, max_rows, max_columns)
    else:
        raise TabularParseError(
            "unsupported_type", f"unsupported tabular file type: {ext or path.name}"
        )

    keys = unique_names([title for title, _ in grids], "sheet")
    sheets: list[ParsedSheet] = []
    for (title, grid), key in zip(grids, keys, strict=True):
        sheet = _build_sheet(title, "" if ext == ".csv" else key, grid)
        if sheet is not None:
            sheets.append(sheet)
    if not sheets:
        raise TabularParseError("no_data", "file has no data rows below the header row")
    return sheets


def _collect(
    rows: Iterable[Iterable[object]],
    to_token: Callable[[object], str | None],
    *,
    title: str,
    max_rows: int,
    max_columns: int,
) -> Grid:
    """Stream rows into a trimmed grid; stop with an error at the first row or
    column over the cap (header + max_rows data rows are allowed)."""
    grid: Grid = []
    pending_empty = 0
    for raw in rows:
        line = len(grid) + pending_empty + 1
        row = _trim_row(raw, to_token, title=title, line=line, max_columns=max_columns)
        if not row:
            pending_empty += 1  # materialised only if real data follows
            continue
        if len(grid) + pending_empty > max_rows:  # header + max_rows already held
            raise TabularParseError(
                "row_cap_exceeded",
                f"sheet {title or 'csv'!r} has more than {max_rows} data rows",
            )
        grid.extend([] for _ in range(pending_empty))
        pending_empty = 0
        grid.append(row)
    return grid


def _trim_row(
    raw: Iterable[object],
    to_token: Callable[[object], str | None],
    *,
    title: str,
    line: int,
    max_columns: int,
) -> list[str | None]:
    tokens: list[str | None] = []
    for idx, cell in enumerate(raw):
        token = to_token(cell)
        if token is None:
            if idx < max_columns:
                tokens.append(None)
            continue
        if idx >= max_columns:
            raise TabularParseError(
                "column_cap_exceeded",
                f"sheet {title or 'csv'!r} line {line} has a value in column {idx + 1}; "
                f"the limit is {max_columns} columns",
            )
        tokens.append(token)
    while tokens and tokens[-1] is None:
        tokens.pop()
    return tokens


def _build_sheet(title: str, key: str, grid: Grid) -> ParsedSheet | None:
    if len(grid) < 2:
        return None
    width = max(len(row) for row in grid)
    padded = [list(row) + [None] * (width - len(row)) for row in grid]
    header, body = padded[0], padded[1:]
    source_names = ["" if cell is None else str(cell) for cell in header]
    names = unique_names(source_names, "column")
    columns = tuple(
        ParsedColumn(
            name=name,
            source_name=source,
            type=infer_type(row[idx] for row in body),
        )
        for idx, (name, source) in enumerate(zip(names, source_names, strict=True))
    )
    rows = [[normalize_token(row[i], columns[i].type) for i in range(width)] for row in body]
    return ParsedSheet(sheet=title, key=key, columns=columns, rows=rows)


def _read_csv(path: Path, max_rows: int, max_columns: int) -> Grid:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TabularParseError("encoding", "CSV files must be UTF-8 encoded") from exc
    try:
        delimiter = csv.Sniffer().sniff(text[:_SNIFF_CHARS], delimiters=_CSV_DELIMITERS).delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        return _collect(reader, cell_token, title="", max_rows=max_rows, max_columns=max_columns)
    except csv.Error as exc:
        raise TabularParseError("unreadable", f"malformed CSV: {exc}") from exc


def _read_xlsx(path: Path, max_rows: int, max_columns: int) -> list[tuple[str, Grid]]:
    from openpyxl import load_workbook

    # Boundary to a third-party parser: corrupt or mislabeled files raise many
    # different exception types (BadZipFile, KeyError, XML parse errors…). All
    # of them mean "unreadable", never a server error.
    try:
        workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
    except Exception as exc:
        raise TabularParseError("unreadable", f"cannot read xlsx file: {exc}") from exc
    try:
        out: list[tuple[str, Grid]] = []
        for ws in workbook.worksheets:
            ws.reset_dimensions()  # never trust <dimension>: it drives row padding
            grid = _collect(
                ws.iter_rows(values_only=True),
                cell_token,
                title=ws.title,
                max_rows=max_rows,
                max_columns=max_columns,
            )
            out.append((ws.title, grid))
        return out
    except TabularParseError:
        raise
    except Exception as exc:
        raise TabularParseError("unreadable", f"cannot read xlsx file: {exc}") from exc
    finally:
        workbook.close()


def _read_xls(path: Path, max_rows: int, max_columns: int) -> list[tuple[str, Grid]]:
    # Same boundary rule as _read_xlsx: xlrd raises XLRDError, CompDocError,
    # BadZipFile (zip renamed to .xls), struct errors… — all "unreadable".
    try:
        book = xlrd.open_workbook(str(path), on_demand=True)
    except Exception as exc:
        raise TabularParseError("unreadable", f"cannot read xls file: {exc}") from exc
    try:
        out: list[tuple[str, Grid]] = []
        for index in range(book.nsheets):
            sheet = book.sheet_by_index(index)
            datemode = book.datemode
            grid = _collect(
                (sheet.row(r) for r in range(sheet.nrows)),
                lambda cell, dm=datemode: _xls_token(cell, dm),
                title=sheet.name,
                max_rows=max_rows,
                max_columns=max_columns,
            )
            out.append((sheet.name, grid))
        return out
    except TabularParseError:
        raise
    except Exception as exc:
        raise TabularParseError("unreadable", f"cannot read xls file: {exc}") from exc
    finally:
        book.release_resources()


def _xls_token(cell: Cell, datemode: int) -> str | None:
    """Map one legacy-Excel cell to a token; error cells (#DIV/0!) stay visible as text.

    Known limitation: a time-only cell (no date part) becomes 1899-12-31Txx:xx:xx.
    """
    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return None
    if cell.ctype == xlrd.XL_CELL_DATE:
        return cell_token(xlrd.xldate_as_datetime(cell.value, datemode))
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return cell_token(bool(cell.value))
    if cell.ctype == xlrd.XL_CELL_ERROR:
        return xlrd.error_text_from_code.get(cell.value, "#ERROR")
    return cell_token(cell.value)
```

- [ ] **Step 6: Chạy test, phải PASS (kể cả test cũ của `files.py`)**

```bash
cd ennam.kg.python && uv run pytest tests/ingestion/test_tabular_reader.py tests/ingestion/test_tabular_headers.py tests/ingestion/test_tabular_infer.py tests/test_file_adapter.py -q && uv run ruff check src/ennam_kg/ingestion/tabular tests/ingestion/test_tabular_reader.py
```
Expected: PASS hết; ruff sạch. Nếu `Sniffer` chọn sai dấu phân cách cho `semicolon_bom.csv` (test thứ hai đỏ), **không** hạ test. Hãy sửa `_read_csv` để thử `delimiters=";,\t|"` theo thứ tự đếm tần suất ở dòng header, rồi chạy lại.

- [ ] **Step 7: Commit**

```bash
git -C ennam.kg.python add pyproject.toml uv.lock src/ennam_kg/ingestion/tabular/reader.py tests/ingestion/test_tabular_reader.py tests/ingestion/fixtures/tabular/sales_small.csv tests/ingestion/fixtures/tabular/sales_small.parsed.json tests/ingestion/fixtures/tabular/semicolon_bom.csv
git -C ennam.kg.python commit -m "feat(tabular): parse csv/xlsx/xls into full typed sheets (adds xlrd)"
```

---

### Task 4: Python — endpoint `POST /api/v1/tabular/parse`

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/api/tabular.py`
- Modify: `ennam.kg.python/src/ennam_kg/main.py` (import + `include_router`)
- Modify: `ennam.kg.python/src/ennam_kg/config.py` (`kg_internal_token`)
- Modify: `docker-compose.yml` (workspace: `KG_INTERNAL_TOKEN` cho `kg-server` và `indexer`)
- Test: `ennam.kg.python/tests/test_tabular_api.py`

**Interfaces:**
- Consumes: `parse_tabular`, `TabularParseError` (Task 3).
- Produces (HTTP, hợp đồng với Go Task 5):
  - `POST /api/v1/tabular/parse?filename=<tên gốc>&max_rows=<int ≥ 1>`
  - Header `Authorization: Bearer <KG_INTERNAL_TOKEN>` (so khớp hằng-thời-gian với setting; setting rỗng ⇒ 503), body là byte thô của file, tối đa 50 MiB (`Content-Length` lớn hơn hoặc stream vượt ⇒ 413 `too_large`, không đọc hết vào RAM).
  - `200` ⇒ `{"sheets":[ParsedSheet.to_dict()]}`
  - `401` khi thiếu Bearer hoặc token sai; `503` khi chưa cấu hình secret; `413` khi body > 50 MiB.
  - `422` ⇒ `{"detail":{"code":"<code>","message":"…"}}`. Code: `unsupported_type`, `empty_file`, cùng các code của `TabularParseError`.

- [ ] **Step 1: Viết test thất bại**

`ennam.kg.python/tests/test_tabular_api.py`:
```python
"""kg-server calls this endpoint synchronously during an upload; its JSON is the
contract Go decodes (internal/intel/filedata/parser_client.go). Port 8081 is
published, so the endpoint must check the shared secret and cap the body."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ennam_kg.config import Settings
from ennam_kg.main import app

_FIX = Path(__file__).parent / "ingestion" / "fixtures" / "tabular"
_TOKEN = "test-internal-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


@pytest.fixture(autouse=True)
def internal_token():
    with patch("ennam_kg.api.tabular.settings", Settings(kg_internal_token=_TOKEN)):
        yield


def _post(body: bytes, filename: str, max_rows: int = 1000, headers: dict[str, str] | None = None):
    client = TestClient(app)
    return client.post(
        "/api/v1/tabular/parse",
        params={"filename": filename, "max_rows": max_rows},
        content=body,
        headers=headers if headers is not None else _AUTH,
    )


def test_parse_returns_golden_contract() -> None:
    body = (_FIX / "sales_small.csv").read_bytes()
    response = _post(body, "sales_small.csv")
    assert response.status_code == 200
    golden = json.loads((_FIX / "sales_small.parsed.json").read_text(encoding="utf-8"))
    assert response.json() == golden


def test_parse_requires_bearer_token() -> None:
    response = _post(b"a\n1\n", "a.csv", headers={})
    assert response.status_code == 401


def test_any_other_token_is_rejected() -> None:
    response = _post(b"a\n1\n", "a.csv", headers={"Authorization": "Bearer something-else"})
    assert response.status_code == 401


def test_unconfigured_secret_fails_closed() -> None:
    with patch("ennam_kg.api.tabular.settings", Settings(kg_internal_token="")):
        response = _post(b"a\n1\n", "a.csv")
    assert response.status_code == 503


async def test_declared_oversize_body_is_413_before_reading() -> None:
    from fastapi import HTTPException
    from starlette.requests import Request

    from ennam_kg.api.tabular import _read_body

    received = False

    async def receive():
        nonlocal received
        received = True
        return {"type": "http.request", "body": b"x", "more_body": False}

    request = Request({"type": "http", "headers": [(b"content-length", b"52428801")]}, receive)
    with pytest.raises(HTTPException) as exc:
        await _read_body(request)
    assert exc.value.status_code == 413
    assert not received, "the body must not be read when Content-Length is already too large"


def test_streamed_oversize_body_is_413() -> None:
    with patch("ennam_kg.api.tabular.MAX_BODY_BYTES", 8):
        response = _post(b"a\n1\n2\n3\n4\n", "a.csv")
    assert response.status_code == 413


def test_row_cap_is_422_with_code() -> None:
    response = _post(b"a\n1\n2\n3\n", "a.csv", max_rows=2)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "row_cap_exceeded"


def test_unsupported_extension_is_422() -> None:
    response = _post(b"%PDF-1.4", "report.pdf")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_type"


def test_empty_body_is_422() -> None:
    response = _post(b"", "a.csv")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "empty_file"
```

- [ ] **Step 2: Chạy test, phải FAIL**

```bash
cd ennam.kg.python && uv run pytest tests/test_tabular_api.py -q
```
Expected: FAIL. `test_parse_returns_golden_contract` nhận `404 != 200`.

- [ ] **Step 3: Implement**

`ennam.kg.python/src/ennam_kg/api/tabular.py`:
```python
"""Tabular upload parsing endpoint ("Dữ liệu bảng").

kg-server calls this synchronously during an upload so the user gets the
validation report in the same response. Parsing runs in a worker thread so a
large workbook does not stall the event loop that also serves /api/v1/embeddings.

Port 8081 is published by docker-compose, so this endpoint authenticates the
caller with a shared secret (KG_INTERNAL_TOKEN, same value in kg-server) and
refuses bodies above the upload cap before buffering them.
"""

from __future__ import annotations

import asyncio
import hmac
import tempfile
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ennam_kg.config import settings
from ennam_kg.ingestion.tabular.reader import TabularParseError, parse_tabular

router = APIRouter()

_ALLOWED_EXTENSIONS = frozenset({".csv", ".xlsx", ".xls"})
MAX_BODY_BYTES = 52_428_800  # 50 MiB — same per-file cap as kg-server (file_upload.go)


def _check_token(authorization: str | None) -> None:
    expected = settings.kg_internal_token
    if not expected:
        # Fail closed: an unconfigured secret must not mean "anyone may call".
        raise HTTPException(status_code=503, detail="tabular parsing is not configured")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid internal token")


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413, detail={"code": "too_large", "message": "file exceeds 50 MiB"}
        )
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise HTTPException(
                status_code=413, detail={"code": "too_large", "message": "file exceeds 50 MiB"}
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/api/v1/tabular/parse")
async def parse_tabular_upload(
    request: Request,
    filename: str = Query(..., min_length=1),
    max_rows: int = Query(..., ge=1),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    _check_token(authorization)

    ext = Path(filename).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unsupported_type",
                "message": f"tabular upload accepts .csv, .xlsx, .xls (got {ext or filename})",
            },
        )

    body = await _read_body(request)
    if not body:
        raise HTTPException(
            status_code=422, detail={"code": "empty_file", "message": "uploaded file is empty"}
        )

    with tempfile.TemporaryDirectory(prefix="kg-tabular-") as tmp:
        path = Path(tmp) / f"upload{ext}"
        path.write_bytes(body)
        try:
            sheets = await asyncio.to_thread(parse_tabular, path, max_rows=max_rows)
        except TabularParseError as exc:
            raise HTTPException(
                status_code=422, detail={"code": exc.code, "message": str(exc)}
            ) from exc

    return JSONResponse({"sheets": [sheet.to_dict() for sheet in sheets]})
```

`ennam.kg.python/src/ennam_kg/config.py` — thêm field vào `Settings` (env `KG_INTERNAL_TOKEN`, `env_prefix` là `""`):
```python
    # Shared secret kg-server sends to internal-only endpoints (tabular parse).
    # Empty = those endpoints answer 503 (fail closed).
    kg_internal_token: str = ""
```

`ennam.kg.python/src/ennam_kg/main.py`: sửa dòng import router và thêm `include_router`:
```python
from ennam_kg.api import health, indexing, phase2, streaming, embeddings, agentic, admin, tabular
```
```python
app.include_router(admin.router)
app.include_router(tabular.router)
```

`docker-compose.yml` (workspace): thêm cùng một biến cho **cả** service `kg-server` (khối `environment`, cạnh `KG_PYTHON_URL`) và service `indexer`:
```yaml
      KG_INTERNAL_TOKEN: ${KG_INTERNAL_TOKEN:-ennam_kg_internal_dev_token}
```

- [ ] **Step 4: Chạy test, phải PASS**

```bash
cd ennam.kg.python && uv run pytest tests/test_tabular_api.py tests/test_embeddings_api.py -q && uv run ruff check src/ennam_kg/api/tabular.py src/ennam_kg/main.py src/ennam_kg/config.py tests/test_tabular_api.py && docker compose config | grep -c KG_INTERNAL_TOKEN
```
Expected: PASS; ruff sạch; `docker compose config` có `KG_INTERNAL_TOKEN` ở 2 service (in `2`).

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.python add src/ennam_kg/api/tabular.py src/ennam_kg/main.py src/ennam_kg/config.py tests/test_tabular_api.py
git -C ennam.kg.python commit -m "feat(api): add authenticated, size-capped /api/v1/tabular/parse"
git add docker-compose.yml
git commit -m "chore(compose): share KG_INTERNAL_TOKEN between kg-server and the indexer"
```

---

### Task 5: Go — kiểu dữ liệu `filedata` + client gọi parser

**Files:**
- Create: `ennam.kg.go/internal/intel/filedata/types.go`
- Create: `ennam.kg.go/internal/intel/filedata/parser_client.go`
- Create: `ennam.kg.go/internal/intel/filedata/testdata/sales_small.parsed.json` (giống **từng byte** bản Python Task 3)
- Test: `ennam.kg.go/internal/intel/filedata/types_test.go`, `ennam.kg.go/internal/intel/filedata/parser_client_test.go`

**Interfaces:**
- Consumes: HTTP contract Task 4.
- Produces:
```go
const (TypeText = "text"; TypeInteger = "integer"; TypeNumeric = "numeric"; TypeBoolean = "boolean"; TypeDate = "date"; TypeTimestamp = "timestamp")
const MaxDatasetRows = 200_000
const ParseTimeout = 120 * time.Second
type Column struct { Name, SourceName, Type string }            // json: name, source_name, type
type ParsedSheet struct { Sheet, Key string; Columns []Column; Rows [][]*string; RowCount int }
type ParseResult struct { Sheets []ParsedSheet }
type ParseError struct { Code, Message string }                  // errors.Is(err, ErrRowCapExceeded) khi Code=row_cap_exceeded
var ErrInvalidInput, ErrRowCapExceeded, ErrColumnConflict, ErrDatasetNotFound, ErrInvalidParse, ErrParserUnavailable error
func NewParserClient(baseURL, token string, httpClient *http.Client) *ParserClient
func (c *ParserClient) Parse(ctx context.Context, filename string, body io.Reader, maxRows int) (*ParseResult, error)
```

- [ ] **Step 1: Sao golden**

```bash
mkdir -p ennam.kg.go/internal/intel/filedata/testdata
cp ennam.kg.python/tests/ingestion/fixtures/tabular/sales_small.parsed.json ennam.kg.go/internal/intel/filedata/testdata/sales_small.parsed.json
cmp ennam.kg.python/tests/ingestion/fixtures/tabular/sales_small.parsed.json ennam.kg.go/internal/intel/filedata/testdata/sales_small.parsed.json && echo identical
```
Expected: `identical`.

- [ ] **Step 2: Viết test thất bại**

`ennam.kg.go/internal/intel/filedata/types_test.go`:
```go
package filedata

import "testing"

// Appending a file whose column changed from integer to numeric (or date to
// timestamp) must keep every stored value castable; anything else degrades to
// text, which validation then reports as a type mismatch instead of failing a
// metric at run time.
func TestWidenType(t *testing.T) {
	cases := []struct{ a, b, want string }{
		{TypeInteger, TypeInteger, TypeInteger},
		{TypeInteger, TypeNumeric, TypeNumeric},
		{TypeNumeric, TypeInteger, TypeNumeric},
		{TypeDate, TypeTimestamp, TypeTimestamp},
		{TypeTimestamp, TypeDate, TypeTimestamp},
		{TypeBoolean, TypeInteger, TypeText},
		{TypeDate, TypeNumeric, TypeText},
		{TypeText, TypeInteger, TypeText},
	}
	for _, c := range cases {
		if got := widenType(c.a, c.b); got != c.want {
			t.Errorf("widenType(%s, %s) = %s, want %s", c.a, c.b, got, c.want)
		}
	}
}

func TestValidType(t *testing.T) {
	for _, ok := range []string{TypeText, TypeInteger, TypeNumeric, TypeBoolean, TypeDate, TypeTimestamp} {
		if !validType(ok) {
			t.Errorf("validType(%q) = false", ok)
		}
	}
	if validType("float") {
		t.Error(`validType("float") = true`)
	}
}
```

`ennam.kg.go/internal/intel/filedata/parser_client_test.go`:
```go
package filedata

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

func TestParserClient_DecodesGoldenContract(t *testing.T) {
	golden, err := os.ReadFile("testdata/sales_small.parsed.json")
	if err != nil {
		t.Fatal(err)
	}
	var gotQuery, gotAuth, gotBody string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotQuery = r.URL.RawQuery
		gotAuth = r.Header.Get("Authorization")
		b, _ := io.ReadAll(r.Body)
		gotBody = string(b)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(golden)
	}))
	defer srv.Close()

	res, err := NewParserClient(srv.URL, "kg-internal", nil).Parse(context.Background(), "sales small.csv", strings.NewReader("raw-bytes"), 7)
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if gotAuth != "Bearer kg-internal" || gotBody != "raw-bytes" {
		t.Errorf("auth=%q body=%q", gotAuth, gotBody)
	}
	if gotQuery != "filename=sales+small.csv&max_rows=7" {
		t.Errorf("query = %q", gotQuery)
	}
	if len(res.Sheets) != 1 || res.Sheets[0].RowCount != 5 || len(res.Sheets[0].Columns) != 4 {
		t.Fatalf("unexpected result: %+v", res)
	}
	if res.Sheets[0].Rows[3][3] != nil {
		t.Errorf("empty Net Amount must decode as nil, got %q", *res.Sheets[0].Rows[3][3])
	}
	if got := *res.Sheets[0].Rows[1][2]; got != "2026-07-01T23:30:00" {
		t.Errorf("sold_at row 2 = %q", got)
	}
}

func TestParserClient_422BecomesParseErrorAndRowCapIsDetectable(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusUnprocessableEntity)
		_, _ = w.Write([]byte(`{"detail":{"code":"row_cap_exceeded","message":"sheet has 3 data rows; the limit is 2"}}`))
	}))
	defer srv.Close()

	_, err := NewParserClient(srv.URL, "t", nil).Parse(context.Background(), "a.csv", strings.NewReader("x"), 2)
	var pe *ParseError
	if !errors.As(err, &pe) || pe.Code != "row_cap_exceeded" {
		t.Fatalf("want ParseError row_cap_exceeded, got %v", err)
	}
	if !errors.Is(err, ErrRowCapExceeded) {
		t.Error("row_cap_exceeded ParseError must match ErrRowCapExceeded")
	}
}

func TestParserClient_ServerErrorIsUnavailable(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer srv.Close()
	_, err := NewParserClient(srv.URL, "t", nil).Parse(context.Background(), "a.csv", strings.NewReader("x"), 2)
	if !errors.Is(err, ErrParserUnavailable) {
		t.Fatalf("want ErrParserUnavailable, got %v", err)
	}
}

// A parser bug must not reach the database: rows narrower than the header, bad
// column names or unknown types are rejected before anything is written.
func TestParserClient_RejectsMalformedResponses(t *testing.T) {
	bodies := map[string]string{
		"ragged row":     `{"sheets":[{"sheet":"","key":"","columns":[{"name":"a","type":"text"},{"name":"b","type":"text"}],"rows":[["x"]],"row_count":1}]}`,
		"bad name":       `{"sheets":[{"sheet":"","key":"","columns":[{"name":"A b","type":"text"}],"rows":[["x"]],"row_count":1}]}`,
		"unknown type":   `{"sheets":[{"sheet":"","key":"","columns":[{"name":"a","type":"float"}],"rows":[["1"]],"row_count":1}]}`,
		"count mismatch": `{"sheets":[{"sheet":"","key":"","columns":[{"name":"a","type":"text"}],"rows":[["x"]],"row_count":2}]}`,
		"duplicate name": `{"sheets":[{"sheet":"","key":"","columns":[{"name":"a","type":"text"},{"name":"a","type":"text"}],"rows":[["x","y"]],"row_count":1}]}`,
		"no sheets":      `{"sheets":[]}`,
	}
	for name, body := range bodies {
		t.Run(name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				_, _ = w.Write([]byte(body))
			}))
			defer srv.Close()
			_, err := NewParserClient(srv.URL, "t", nil).Parse(context.Background(), "a.csv", strings.NewReader("x"), 10)
			if !errors.Is(err, ErrInvalidParse) {
				t.Fatalf("want ErrInvalidParse, got %v", err)
			}
		})
	}
}
```

- [ ] **Step 3: Chạy test, phải FAIL**

```bash
cd ennam.kg.go && go test ./internal/intel/filedata/ -run 'TestWidenType|TestValidType|TestParserClient' -count=1
```
Expected: FAIL do build: `undefined: widenType`, `undefined: NewParserClient`, …

- [ ] **Step 4: Implement**

`ennam.kg.go/internal/intel/filedata/types.go`:
```go
// Package filedata stores customer-uploaded tabular files ("Dữ liệu bảng") as
// JSONB rows (file_dataset / file_dataset_row), validates them against the
// project's file-mode mappings and exposes them to the metric compiler as a
// intel.SourceTable (mode=file). It is industry-neutral core code.
package filedata

import (
	"errors"
	"regexp"
	"strings"
)

// Column types produced by the tabular parser. Stored values are canonical
// strings of these types (or JSON null), so FileTable.ColumnSQL casts never fail.
const (
	TypeText      = "text"
	TypeInteger   = "integer"
	TypeNumeric   = "numeric"
	TypeBoolean   = "boolean"
	TypeDate      = "date"
	TypeTimestamp = "timestamp"
)

// MaxDatasetRows caps one dataset (after an append). Exceeding it is an error;
// rows are never silently dropped.
const MaxDatasetRows = 200_000

var (
	// identRE matches parser column names, sheet keys and user dataset names.
	identRE = regexp.MustCompile(`^[a-z][a-z0-9_]{0,62}$`)
	// datasetNameRE also allows the "<dataset>__<sheet>" names of multi-sheet files.
	datasetNameRE = regexp.MustCompile(`^[a-z][a-z0-9_]{0,127}$`)
)

var (
	ErrInvalidInput      = errors.New("filedata: invalid input")
	ErrRowCapExceeded    = errors.New("filedata: row limit exceeded")
	ErrColumnConflict    = errors.New("filedata: columns differ from the existing dataset")
	ErrDatasetNotFound   = errors.New("filedata: dataset not found")
	ErrInvalidParse      = errors.New("filedata: invalid parser response")
	ErrParserUnavailable = errors.New("filedata: tabular parser unavailable")
)

// Column is one dataset column as stored in file_dataset.columns.
type Column struct {
	Name       string `json:"name"`
	SourceName string `json:"source_name,omitempty"`
	Type       string `json:"type"`
}

// ParsedSheet is one sheet returned by the parser. Rows[i][j] is nil for an
// empty cell; Rows are aligned with Columns.
type ParsedSheet struct {
	Sheet    string      `json:"sheet"`
	Key      string      `json:"key"`
	Columns  []Column    `json:"columns"`
	Rows     [][]*string `json:"rows"`
	RowCount int         `json:"row_count"`
}

// ParseResult is the parser response body.
type ParseResult struct {
	Sheets []ParsedSheet `json:"sheets"`
}

// ParseError is a file the parser refused (422); Code is machine-readable.
type ParseError struct {
	Code    string
	Message string
}

func (e *ParseError) Error() string {
	return "tabular parse failed (" + e.Code + "): " + e.Message
}

// Is lets callers treat the parser's row-cap refusal like the store's.
func (e *ParseError) Is(target error) bool {
	return target == ErrRowCapExceeded && e.Code == "row_cap_exceeded"
}

func validType(t string) bool {
	switch t {
	case TypeText, TypeInteger, TypeNumeric, TypeBoolean, TypeDate, TypeTimestamp:
		return true
	}
	return false
}

// widenType returns a type every value of both a and b still casts to.
func widenType(a, b string) string {
	switch {
	case a == b:
		return a
	case isOneOf(a, b, TypeInteger, TypeNumeric):
		return TypeNumeric
	case isOneOf(a, b, TypeDate, TypeTimestamp):
		return TypeTimestamp
	default:
		return TypeText
	}
}

func isOneOf(a, b, x, y string) bool {
	return (a == x || a == y) && (b == x || b == y)
}

func columnNames(cols []Column) string {
	names := make([]string, len(cols))
	for i, c := range cols {
		names[i] = c.Name
	}
	return strings.Join(names, ", ")
}
```

`ennam.kg.go/internal/intel/filedata/parser_client.go`:
```go
package filedata

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// ParseTimeout bounds one synchronous parse call to the Python indexer. It is
// separate from the 10s embed client so search keeps its own budget.
const ParseTimeout = 120 * time.Second

// ParserClient calls the indexer's POST /api/v1/tabular/parse.
type ParserClient struct {
	baseURL string
	token   string
	http    *http.Client
}

// NewParserClient builds a client; baseURL is the indexer root (KG_PYTHON_URL).
func NewParserClient(baseURL, token string, httpClient *http.Client) *ParserClient {
	if httpClient == nil {
		httpClient = &http.Client{Timeout: ParseTimeout}
	}
	return &ParserClient{baseURL: strings.TrimRight(baseURL, "/"), token: token, http: httpClient}
}

// Parse sends the raw file and returns validated sheets.
func (c *ParserClient) Parse(ctx context.Context, filename string, body io.Reader, maxRows int) (*ParseResult, error) {
	q := url.Values{}
	q.Set("filename", filename)
	q.Set("max_rows", strconv.Itoa(maxRows))
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/api/v1/tabular/parse?"+q.Encode(), body)
	if err != nil {
		return nil, fmt.Errorf("build parse request: %w", err)
	}
	req.Header.Set("Content-Type", "application/octet-stream")
	req.Header.Set("Authorization", "Bearer "+c.token)

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrParserUnavailable, err)
	}
	defer func() { _ = resp.Body.Close() }()

	switch resp.StatusCode {
	case http.StatusOK:
	case http.StatusUnprocessableEntity:
		var e struct {
			Detail struct {
				Code    string `json:"code"`
				Message string `json:"message"`
			} `json:"detail"`
		}
		if err := json.NewDecoder(resp.Body).Decode(&e); err != nil || e.Detail.Code == "" {
			return nil, fmt.Errorf("%w: parser returned 422 without a code", ErrInvalidParse)
		}
		return nil, &ParseError{Code: e.Detail.Code, Message: e.Detail.Message}
	default:
		return nil, fmt.Errorf("%w: parser status %d", ErrParserUnavailable, resp.StatusCode)
	}

	var out ParseResult
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, fmt.Errorf("%w: decode: %v", ErrInvalidParse, err)
	}
	if err := out.validate(); err != nil {
		return nil, err
	}
	return &out, nil
}

func (r *ParseResult) validate() error {
	if len(r.Sheets) == 0 {
		return fmt.Errorf("%w: no sheets", ErrInvalidParse)
	}
	for i, sh := range r.Sheets {
		if sh.Key != "" && !identRE.MatchString(sh.Key) {
			return fmt.Errorf("%w: sheet %d key %q", ErrInvalidParse, i+1, sh.Key)
		}
		if len(sh.Columns) == 0 {
			return fmt.Errorf("%w: sheet %d has no columns", ErrInvalidParse, i+1)
		}
		seen := make(map[string]bool, len(sh.Columns))
		for _, c := range sh.Columns {
			if !identRE.MatchString(c.Name) || seen[c.Name] || !validType(c.Type) {
				return fmt.Errorf("%w: sheet %d column %q type %q", ErrInvalidParse, i+1, c.Name, c.Type)
			}
			seen[c.Name] = true
		}
		if sh.RowCount != len(sh.Rows) {
			return fmt.Errorf("%w: sheet %d row_count %d != %d rows", ErrInvalidParse, i+1, sh.RowCount, len(sh.Rows))
		}
		for j, row := range sh.Rows {
			if len(row) != len(sh.Columns) {
				return fmt.Errorf("%w: sheet %d row %d has %d cells, want %d", ErrInvalidParse, i+1, j+1, len(row), len(sh.Columns))
			}
		}
	}
	return nil
}
```

- [ ] **Step 5: Chạy test, phải PASS**

```bash
cd ennam.kg.go && go test ./internal/intel/filedata/ -run 'TestWidenType|TestValidType|TestParserClient' -count=1 -v | grep -E '^(=== RUN|--- (PASS|FAIL)|ok|FAIL)'
```
Expected: mọi `--- PASS`, dòng cuối `ok  github.com/ennam/ennam-kg/internal/intel/filedata`.

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.go add internal/intel/filedata/types.go internal/intel/filedata/parser_client.go internal/intel/filedata/types_test.go internal/intel/filedata/parser_client_test.go internal/intel/filedata/testdata/sales_small.parsed.json
git -C ennam.kg.go commit -m "feat(filedata): add tabular types and indexer parse client"
```

---

### Task 6: Go — `Store.Write` (append/replace, một transaction, COPY)

**Files:**
- Create: `ennam.kg.go/internal/intel/filedata/store.go`
- Create: `ennam.kg.go/internal/intel/filedata/testdb_test.go` (helper dùng chung cho test integration)
- Test: `ennam.kg.go/internal/intel/filedata/store_integration_test.go`

**Interfaces:**
- Consumes: bảng Task 1; `pq.CopyIn` (`github.com/lib/pq` đã có trong go.mod).
- Produces:
```go
const (WriteAppend = "append"; WriteReplace = "replace")
type Dataset struct { ID, ProjectID uuid.UUID; Name string; Columns []Column; WriteMode string; RowCount int; UpdatedAt time.Time }
type WriteInput struct { ProjectID uuid.UUID; Name, WriteMode string; Columns []Column; Rows [][]*string; SourceFileID *uuid.UUID; UploadedBy string }
type WriteResult struct { Dataset Dataset; RowsWritten, RowOffset int }
type StoredRow struct { RowNum int; Values map[string]*string }
func NewStore(db *sql.DB) *Store
func (s *Store) Write(ctx context.Context, inputs []WriteInput) ([]WriteResult, error)   // tất cả hoặc không
func (s *Store) GetByName(ctx context.Context, projectID uuid.UUID, name string) (*Dataset, error)
func (s *Store) LoadRows(ctx context.Context, datasetID uuid.UUID) ([]StoredRow, error)
```
- Ngữ nghĩa:
  - `replace`, hoặc `append` vào dataset chưa có dòng nào: xoá hết dòng, ghi dòng mới từ `row_num` 1, `columns` = cột mới.
  - `append`: tập tên cột phải trùng (khác ⇒ `ErrColumnConflict`), kiểu cột được nới bằng `widenType`, `row_num` nối tiếp. Tổng số dòng > giới hạn ⇒ `ErrRowCapExceeded`.
  - Khoá dòng `file_dataset` bằng `FOR UPDATE` theo thứ tự tên để không deadlock.

- [ ] **Step 1: Viết helper + test thất bại**

`ennam.kg.go/internal/intel/filedata/testdb_test.go`:
```go
package filedata

import (
	"database/sql"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/google/uuid"
	_ "github.com/lib/pq" // postgres driver for integration tests
)

// openTestDB connects to the integration DB (DAAB dev DB is on :5433). Like the
// store integration tests it skips unless KG_TEST_DATABASE_URL is set — a SKIP
// still reports package "ok", so run with -v and grep SKIP.
func openTestDB(t *testing.T) *sql.DB {
	t.Helper()
	dsn := os.Getenv("KG_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("Skipping integration test: KG_TEST_DATABASE_URL not set")
	}
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		t.Fatalf("open test db: %v", err)
	}
	if err := db.Ping(); err != nil {
		t.Fatalf("ping test db: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	return db
}

// seedProject creates a throwaway project; ON DELETE CASCADE removes its datasets.
func seedProject(t *testing.T, db *sql.DB) uuid.UUID {
	t.Helper()
	var id uuid.UUID
	if err := db.QueryRow(
		`INSERT INTO projects (name, description) VALUES ($1, 'plan C filedata test') RETURNING id`,
		fmt.Sprintf("filedata-it-%d", time.Now().UnixNano()),
	).Scan(&id); err != nil {
		t.Fatalf("seed project: %v", err)
	}
	t.Cleanup(func() { _, _ = db.Exec(`DELETE FROM projects WHERE id = $1`, id) })
	return id
}

// cells turns literal strings into parser cells; "" means an empty cell (nil).
func cells(values ...string) []*string {
	out := make([]*string, len(values))
	for i, v := range values {
		if v != "" {
			s := v
			out[i] = &s
		}
	}
	return out
}

func mustExec(t *testing.T, db *sql.DB, q string, args ...any) {
	t.Helper()
	if _, err := db.Exec(q, args...); err != nil {
		t.Fatalf("exec %q: %v", q, err)
	}
}

func mustUUID(t *testing.T, s string) uuid.UUID {
	t.Helper()
	id, err := uuid.Parse(s)
	if err != nil {
		t.Fatal(err)
	}
	return id
}
```

`ennam.kg.go/internal/intel/filedata/store_integration_test.go`:
```go
package filedata

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"
)

var qtyColumns = []Column{{Name: "store_id", Type: TypeText}, {Name: "qty", Type: TypeInteger}}

func writeOne(t *testing.T, s *Store, in WriteInput) WriteResult {
	t.Helper()
	res, err := s.Write(context.Background(), []WriteInput{in})
	if err != nil {
		t.Fatalf("Write: %v", err)
	}
	return res[0]
}

func rowValues(t *testing.T, s *Store, id uuid.UUID, column string) []string {
	t.Helper()
	rows, err := s.LoadRows(context.Background(), id)
	if err != nil {
		t.Fatalf("LoadRows: %v", err)
	}
	out := make([]string, len(rows))
	for i, r := range rows {
		if r.RowNum != i+1 {
			t.Fatalf("row_num %d at position %d: rows must be contiguous from 1", r.RowNum, i)
		}
		if v := r.Values[column]; v != nil {
			out[i] = *v
		}
	}
	return out
}

func TestStoreWrite_ReplaceSwapsAllRows(t *testing.T) {
	db := openTestDB(t)
	pid := seedProject(t, db)
	s := NewStore(db)
	writeOne(t, s, WriteInput{ProjectID: pid, Name: "targets", WriteMode: WriteReplace, Columns: qtyColumns,
		Rows: [][]*string{cells("A", "1"), cells("B", "2"), cells("C", "3")}})

	res := writeOne(t, s, WriteInput{ProjectID: pid, Name: "targets", WriteMode: WriteReplace, Columns: qtyColumns,
		Rows: [][]*string{cells("D", "4"), cells("E", "")}})

	if res.RowOffset != 0 || res.RowsWritten != 2 || res.Dataset.RowCount != 2 {
		t.Fatalf("result = %+v", res)
	}
	if got := rowValues(t, s, res.Dataset.ID, "store_id"); len(got) != 2 || got[0] != "D" || got[1] != "E" {
		t.Fatalf("rows after replace = %v", got)
	}
	if got := rowValues(t, s, res.Dataset.ID, "qty"); got[1] != "" {
		t.Errorf("empty cell must be stored as JSON null, got %q", got[1])
	}
}

func TestStoreWrite_AppendContinuesRowNumbersAndWidensTypes(t *testing.T) {
	db := openTestDB(t)
	pid := seedProject(t, db)
	s := NewStore(db)
	writeOne(t, s, WriteInput{ProjectID: pid, Name: "sales", WriteMode: WriteReplace, Columns: qtyColumns,
		Rows: [][]*string{cells("A", "1"), cells("B", "2")}})

	// Same columns, different order, qty now has decimals.
	res := writeOne(t, s, WriteInput{ProjectID: pid, Name: "sales", WriteMode: WriteAppend,
		Columns: []Column{{Name: "qty", Type: TypeNumeric}, {Name: "store_id", Type: TypeText}},
		Rows:    [][]*string{cells("2.5", "C"), cells("4", "D")}})

	if res.RowOffset != 2 || res.Dataset.RowCount != 4 {
		t.Fatalf("result = %+v", res)
	}
	if got := rowValues(t, s, res.Dataset.ID, "store_id"); len(got) != 4 || got[2] != "C" {
		t.Fatalf("rows = %v", got)
	}
	ds, err := s.GetByName(context.Background(), pid, "sales")
	if err != nil {
		t.Fatal(err)
	}
	if ds.Columns[1].Name != "qty" || ds.Columns[1].Type != TypeNumeric {
		t.Errorf("qty must widen integer→numeric, columns = %+v", ds.Columns)
	}
}

func TestStoreWrite_AppendRejectsDifferentColumns(t *testing.T) {
	db := openTestDB(t)
	pid := seedProject(t, db)
	s := NewStore(db)
	first := writeOne(t, s, WriteInput{ProjectID: pid, Name: "sales", WriteMode: WriteReplace, Columns: qtyColumns,
		Rows: [][]*string{cells("A", "1")}})

	_, err := s.Write(context.Background(), []WriteInput{{ProjectID: pid, Name: "sales", WriteMode: WriteAppend,
		Columns: []Column{{Name: "store_id", Type: TypeText}, {Name: "amount", Type: TypeNumeric}},
		Rows:    [][]*string{cells("B", "9")}}})

	if !errors.Is(err, ErrColumnConflict) {
		t.Fatalf("want ErrColumnConflict, got %v", err)
	}
	if got := rowValues(t, s, first.Dataset.ID, "store_id"); len(got) != 1 {
		t.Fatalf("existing rows must be untouched, got %v", got)
	}
}

// Review focus 1: a replace that fails after the DELETE must leave the old
// rows in place — the whole write is one transaction.
func TestStoreWrite_ReplaceFailureKeepsOldRows(t *testing.T) {
	db := openTestDB(t)
	pid := seedProject(t, db)
	s := NewStore(db)
	first := writeOne(t, s, WriteInput{ProjectID: pid, Name: "targets", WriteMode: WriteReplace, Columns: qtyColumns,
		Rows: [][]*string{cells("A", "1"), cells("B", "2"), cells("C", "3")}})

	s.beforeInsert = func(string) error { return errors.New("injected failure after delete") }
	_, err := s.Write(context.Background(), []WriteInput{{ProjectID: pid, Name: "targets", WriteMode: WriteReplace,
		Columns: qtyColumns, Rows: [][]*string{cells("X", "9")}}})
	if err == nil {
		t.Fatal("expected the injected failure")
	}

	s.beforeInsert = nil
	if got := rowValues(t, s, first.Dataset.ID, "store_id"); len(got) != 3 || got[0] != "A" {
		t.Fatalf("old rows must survive a failed replace, got %v", got)
	}
	ds, _ := s.GetByName(context.Background(), pid, "targets")
	if ds.RowCount != 3 {
		t.Errorf("row_count = %d, want 3", ds.RowCount)
	}
}

func TestStoreWrite_MultiSheetFailureWritesNothing(t *testing.T) {
	db := openTestDB(t)
	pid := seedProject(t, db)
	s := NewStore(db)
	s.beforeInsert = func(name string) error {
		if name == "book__b" {
			return errors.New("injected failure on second sheet")
		}
		return nil
	}
	_, err := s.Write(context.Background(), []WriteInput{
		{ProjectID: pid, Name: "book__a", WriteMode: WriteReplace, Columns: qtyColumns, Rows: [][]*string{cells("A", "1")}},
		{ProjectID: pid, Name: "book__b", WriteMode: WriteReplace, Columns: qtyColumns, Rows: [][]*string{cells("B", "2")}},
	})
	if err == nil {
		t.Fatal("expected failure")
	}
	if _, err := s.GetByName(context.Background(), pid, "book__a"); !errors.Is(err, ErrDatasetNotFound) {
		t.Fatalf("first sheet must be rolled back too, got %v", err)
	}
}

// Review focus 2: exceeding the cap is an error that writes nothing.
func TestStoreWrite_AppendOverCapWritesNothing(t *testing.T) {
	db := openTestDB(t)
	pid := seedProject(t, db)
	s := NewStore(db)
	s.maxRows = 3
	first := writeOne(t, s, WriteInput{ProjectID: pid, Name: "sales", WriteMode: WriteReplace, Columns: qtyColumns,
		Rows: [][]*string{cells("A", "1"), cells("B", "2")}})

	_, err := s.Write(context.Background(), []WriteInput{{ProjectID: pid, Name: "sales", WriteMode: WriteAppend,
		Columns: qtyColumns, Rows: [][]*string{cells("C", "3"), cells("D", "4")}}})

	if !errors.Is(err, ErrRowCapExceeded) {
		t.Fatalf("want ErrRowCapExceeded, got %v", err)
	}
	if got := rowValues(t, s, first.Dataset.ID, "store_id"); len(got) != 2 {
		t.Fatalf("rows = %v, want the original 2", got)
	}
}

func TestStoreWrite_RejectsRaggedRowsBeforeTouchingTheDatabase(t *testing.T) {
	s := NewStore(nil) // never reaches the DB
	_, err := s.Write(context.Background(), []WriteInput{{ProjectID: uuid.New(), Name: "x", WriteMode: WriteReplace,
		Columns: qtyColumns, Rows: [][]*string{cells("only-one-cell")}}})
	if !errors.Is(err, ErrInvalidInput) {
		t.Fatalf("want ErrInvalidInput, got %v", err)
	}
}
```

- [ ] **Step 2: Chạy test, phải FAIL**

```bash
cd ennam.kg.go && KG_TEST_DATABASE_URL='postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable' go test ./internal/intel/filedata/ -run TestStoreWrite -count=1 -v 2>&1 | tail -5
```
Expected: FAIL do build `undefined: NewStore`.

- [ ] **Step 3: Implement**

`ennam.kg.go/internal/intel/filedata/store.go`:
```go
package filedata

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/lib/pq"
)

// Write modes chosen by the uploader.
const (
	WriteAppend  = "append"
	WriteReplace = "replace"
)

// Dataset is one file_dataset row.
type Dataset struct {
	ID        uuid.UUID
	ProjectID uuid.UUID
	Name      string
	Columns   []Column
	WriteMode string
	RowCount  int
	UpdatedAt time.Time // set by GetByName; the mode=file resolver uses it as the freshness watermark
}

// WriteInput is one sheet to store as a dataset.
type WriteInput struct {
	ProjectID    uuid.UUID
	Name         string
	WriteMode    string
	Columns      []Column
	Rows         [][]*string
	SourceFileID *uuid.UUID
	UploadedBy   string
}

// WriteResult describes what one WriteInput did. RowOffset is the number of
// rows that were already in the dataset before this write (0 for replace).
type WriteResult struct {
	Dataset     Dataset
	RowsWritten int
	RowOffset   int
}

// StoredRow is one file_dataset_row; a nil value is an empty cell.
type StoredRow struct {
	RowNum int
	Values map[string]*string
}

// Store reads and writes file datasets in DAAB's own database.
type Store struct {
	db      *sql.DB
	maxRows int
	// beforeInsert is a test seam: it runs after old rows were deleted and
	// before new rows are copied, to prove the write is atomic.
	beforeInsert func(name string) error
}

// NewStore creates a Store.
func NewStore(db *sql.DB) *Store {
	return &Store{db: db, maxRows: MaxDatasetRows}
}

// Write stores every input in ONE transaction: either all datasets change or none.
func (s *Store) Write(ctx context.Context, inputs []WriteInput) (results []WriteResult, err error) {
	if len(inputs) == 0 {
		return nil, fmt.Errorf("%w: nothing to write", ErrInvalidInput)
	}
	payloads := make([][][]byte, len(inputs))
	for i, in := range inputs {
		if err := s.checkWriteInput(in); err != nil {
			return nil, err
		}
		p, err := encodeRows(in.Columns, in.Rows)
		if err != nil {
			return nil, fmt.Errorf("dataset %s: %w", in.Name, err)
		}
		payloads[i] = p
	}
	order := make([]int, len(inputs))
	for i := range order {
		order[i] = i
	}
	// Fixed lock order across concurrent uploads of multi-sheet files.
	sort.Slice(order, func(a, b int) bool { return inputs[order[a]].Name < inputs[order[b]].Name })

	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin dataset write: %w", err)
	}
	defer func() {
		if err != nil {
			_ = tx.Rollback()
		}
	}()

	results = make([]WriteResult, len(inputs))
	for _, i := range order {
		res, werr := s.writeOne(ctx, tx, inputs[i], payloads[i])
		if werr != nil {
			return nil, werr
		}
		results[i] = *res
	}
	if err = tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit dataset write: %w", err)
	}
	return results, nil
}

func (s *Store) checkWriteInput(in WriteInput) error {
	switch {
	case in.ProjectID == uuid.Nil:
		return fmt.Errorf("%w: project id is required", ErrInvalidInput)
	case !datasetNameRE.MatchString(in.Name):
		return fmt.Errorf("%w: dataset name %q", ErrInvalidInput, in.Name)
	case in.WriteMode != WriteAppend && in.WriteMode != WriteReplace:
		return fmt.Errorf("%w: write mode %q", ErrInvalidInput, in.WriteMode)
	case len(in.Columns) == 0:
		return fmt.Errorf("%w: dataset %s has no columns", ErrInvalidInput, in.Name)
	case len(in.Rows) > s.maxRows:
		return fmt.Errorf("%w: dataset %s has %d rows (limit %d)", ErrRowCapExceeded, in.Name, len(in.Rows), s.maxRows)
	}
	return nil
}

func (s *Store) writeOne(ctx context.Context, tx *sql.Tx, in WriteInput, payloads [][]byte) (*WriteResult, error) {
	colsJSON, err := json.Marshal(in.Columns)
	if err != nil {
		return nil, fmt.Errorf("encode columns: %w", err)
	}
	if _, err := tx.ExecContext(ctx, `
		INSERT INTO file_dataset (project_id, name, columns, write_mode)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (project_id, name) DO NOTHING`,
		in.ProjectID, in.Name, string(colsJSON), in.WriteMode); err != nil {
		return nil, fmt.Errorf("create dataset %s: %w", in.Name, err)
	}

	ds := Dataset{ProjectID: in.ProjectID, Name: in.Name, WriteMode: in.WriteMode}
	var rawCols []byte
	var existingRows int
	if err := tx.QueryRowContext(ctx, `
		SELECT id, columns, row_count FROM file_dataset
		WHERE project_id = $1 AND name = $2
		FOR UPDATE`, in.ProjectID, in.Name).Scan(&ds.ID, &rawCols, &existingRows); err != nil {
		return nil, fmt.Errorf("lock dataset %s: %w", in.Name, err)
	}
	var existing []Column
	if err := json.Unmarshal(rawCols, &existing); err != nil {
		return nil, fmt.Errorf("decode columns of %s: %w", in.Name, err)
	}

	columns := in.Columns
	offset := 0
	if in.WriteMode == WriteAppend && existingRows > 0 {
		merged, err := mergeColumns(existing, in.Columns)
		if err != nil {
			return nil, fmt.Errorf("dataset %s: %w", in.Name, err)
		}
		if existingRows+len(payloads) > s.maxRows {
			return nil, fmt.Errorf("%w: dataset %s would hold %d rows (limit %d)",
				ErrRowCapExceeded, in.Name, existingRows+len(payloads), s.maxRows)
		}
		if err := tx.QueryRowContext(ctx,
			`SELECT COALESCE(MAX(row_num), 0) FROM file_dataset_row WHERE dataset_id = $1`, ds.ID).Scan(&offset); err != nil {
			return nil, fmt.Errorf("read last row of %s: %w", in.Name, err)
		}
		columns = merged
	} else if _, err := tx.ExecContext(ctx, `DELETE FROM file_dataset_row WHERE dataset_id = $1`, ds.ID); err != nil {
		return nil, fmt.Errorf("clear dataset %s: %w", in.Name, err)
	}

	if s.beforeInsert != nil {
		if err := s.beforeInsert(in.Name); err != nil {
			return nil, err
		}
	}
	if err := copyRows(ctx, tx, ds.ID, offset, payloads); err != nil {
		return nil, fmt.Errorf("insert rows of %s: %w", in.Name, err)
	}

	finalCols, err := json.Marshal(columns)
	if err != nil {
		return nil, fmt.Errorf("encode columns: %w", err)
	}
	rowCount := offset + len(payloads)
	var sourceFile any
	if in.SourceFileID != nil {
		sourceFile = *in.SourceFileID
	}
	if _, err := tx.ExecContext(ctx, `
		UPDATE file_dataset
		SET columns = $2, write_mode = $3, row_count = $4,
		    source_file_id = $5, uploaded_by = NULLIF($6, ''), updated_at = now()
		WHERE id = $1`,
		ds.ID, string(finalCols), in.WriteMode, rowCount, sourceFile, in.UploadedBy); err != nil {
		return nil, fmt.Errorf("update dataset %s: %w", in.Name, err)
	}
	ds.Columns = columns
	ds.RowCount = rowCount
	return &WriteResult{Dataset: ds, RowsWritten: len(payloads), RowOffset: offset}, nil
}

func copyRows(ctx context.Context, tx *sql.Tx, datasetID uuid.UUID, offset int, payloads [][]byte) error {
	stmt, err := tx.PrepareContext(ctx, pq.CopyIn("file_dataset_row", "dataset_id", "row_num", "data"))
	if err != nil {
		return err
	}
	for i, p := range payloads {
		if _, err := stmt.ExecContext(ctx, datasetID.String(), offset+i+1, string(p)); err != nil {
			_ = stmt.Close()
			return err
		}
	}
	if _, err := stmt.ExecContext(ctx); err != nil {
		_ = stmt.Close()
		return err
	}
	return stmt.Close()
}

// encodeRows turns aligned cells into JSON objects keyed by column name.
func encodeRows(columns []Column, rows [][]*string) ([][]byte, error) {
	out := make([][]byte, len(rows))
	for i, row := range rows {
		if len(row) != len(columns) {
			return nil, fmt.Errorf("%w: row %d has %d cells, want %d", ErrInvalidInput, i+1, len(row), len(columns))
		}
		obj := make(map[string]*string, len(columns))
		for j, col := range columns {
			if v := row[j]; v != nil && strings.ContainsRune(*v, 0) {
				return nil, fmt.Errorf("%w: row %d column %s contains a NUL character", ErrInvalidInput, i+1, col.Name)
			}
			obj[col.Name] = row[j]
		}
		b, err := json.Marshal(obj)
		if err != nil {
			return nil, fmt.Errorf("encode row %d: %w", i+1, err)
		}
		out[i] = b
	}
	return out, nil
}

// mergeColumns keeps the existing order and widens types; names must match exactly.
func mergeColumns(existing, incoming []Column) ([]Column, error) {
	if len(existing) != len(incoming) {
		return nil, columnConflict(existing, incoming)
	}
	byName := make(map[string]Column, len(incoming))
	for _, c := range incoming {
		byName[c.Name] = c
	}
	merged := make([]Column, len(existing))
	for i, old := range existing {
		nw, ok := byName[old.Name]
		if !ok {
			return nil, columnConflict(existing, incoming)
		}
		merged[i] = Column{Name: old.Name, SourceName: nw.SourceName, Type: widenType(old.Type, nw.Type)}
	}
	return merged, nil
}

func columnConflict(existing, incoming []Column) error {
	return fmt.Errorf("%w: dataset has [%s], upload has [%s]", ErrColumnConflict, columnNames(existing), columnNames(incoming))
}

// GetByName loads dataset metadata.
func (s *Store) GetByName(ctx context.Context, projectID uuid.UUID, name string) (*Dataset, error) {
	ds := Dataset{ProjectID: projectID, Name: name}
	var raw []byte
	err := s.db.QueryRowContext(ctx, `
		SELECT id, columns, write_mode, row_count, updated_at FROM file_dataset
		WHERE project_id = $1 AND name = $2`, projectID, name).Scan(&ds.ID, &raw, &ds.WriteMode, &ds.RowCount, &ds.UpdatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, fmt.Errorf("%w: %s", ErrDatasetNotFound, name)
	}
	if err != nil {
		return nil, fmt.Errorf("get dataset %s: %w", name, err)
	}
	if err := json.Unmarshal(raw, &ds.Columns); err != nil {
		return nil, fmt.Errorf("decode columns of %s: %w", name, err)
	}
	return &ds, nil
}

// LoadRows returns every row of a dataset ordered by row_num (bounded by MaxDatasetRows).
func (s *Store) LoadRows(ctx context.Context, datasetID uuid.UUID) ([]StoredRow, error) {
	rows, err := s.db.QueryContext(ctx,
		`SELECT row_num, data FROM file_dataset_row WHERE dataset_id = $1 ORDER BY row_num`, datasetID)
	if err != nil {
		return nil, fmt.Errorf("load rows: %w", err)
	}
	defer func() { _ = rows.Close() }()
	var out []StoredRow
	for rows.Next() {
		var r StoredRow
		var raw []byte
		if err := rows.Scan(&r.RowNum, &raw); err != nil {
			return nil, fmt.Errorf("scan row: %w", err)
		}
		if err := json.Unmarshal(raw, &r.Values); err != nil {
			return nil, fmt.Errorf("decode row %d: %w", r.RowNum, err)
		}
		out = append(out, r)
	}
	return out, rows.Err()
}
```

- [ ] **Step 4: Chạy test, phải PASS và không SKIP**

```bash
cd ennam.kg.go && KG_TEST_DATABASE_URL='postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable' go test ./internal/intel/filedata/ -run TestStoreWrite -count=1 -race -v 2>&1 | grep -E -- '--- (PASS|FAIL|SKIP)|^ok|^FAIL'
```
Expected: 7 dòng `--- PASS`, **không có** `--- SKIP`, dòng cuối `ok`.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/intel/filedata/store.go internal/intel/filedata/testdb_test.go internal/intel/filedata/store_integration_test.go
git -C ennam.kg.go commit -m "feat(filedata): transactional append/replace dataset store with row cap"
```

---

### Task 7: Go — `Validate` (thuần, không DB) theo `intel.Entity` + enum

**Files:**
- Create: `ennam.kg.go/internal/intel/filedata/validate.go`
- Create: `ennam.kg.go/internal/intel/filedata/source_table_cast.go` (`pgType`, `pgDataType`, `castable` — Task 8 dùng lại)
- Create: `ennam.kg.go/internal/intel/filedata/helpers_test.go` (fixture `target` đúng canonical của Plan B)
- Test: `ennam.kg.go/internal/intel/filedata/validate_test.go`

**Interfaces:**
- Consumes (Plan B, package `intel`): `intel.Mapping{Entity, Mode, FileDataset, Spec: intel.MappingSpec{Fields, EnumMap}, Status}`, `*intel.Entity{Fields []intel.Field{Name, Type intel.FieldType, Key, Required}}` + `(*intel.Entity).Field(name)`, `intel.FieldType` (`intel.TypeText|TypeNumeric|TypeInteger|TypeBoolean|TypeDate|TypeTimestamp`), `intel.StatusCurrent|StatusIncomplete|StatusBlocked`.
- Produces:
```go
const (MaxIssueRows = 20; MaxDuplicateGroups = 20; MaxEnumValues = 10)
type Issue struct { Code, Message, Field, Column string; Rows []int; Count int; Values []string }   // JSON cho UI
type ColumnStat struct { Field, Column, ColumnType string; CanonicalType intel.FieldType; NullCount int; NullRatio float64 }
type EntityReport struct { Entity, Status string; Issues []Issue; Columns []ColumnStat; IssuesTruncated bool }
func Validate(columns []Column, rows []StoredRow, m intel.Mapping, ent *intel.Entity, enums map[string][]string) EntityReport
func pgType(columnType string) string          // bigint|numeric|boolean|date|timestamp|text
func pgDataType(columnType string) string      // như pgType, riêng timestamp = "timestamp without time zone"
func castable(columnType string, canonical intel.FieldType) bool
```
- Quy tắc trạng thái (dùng hằng của `intel`):
  - `blocked`: `unknown_field`, `missing_field` (field bắt buộc chưa map), `unsupported_expression` (mode=file chỉ nhận **tên cột trần**, theo Exports của B), `missing_column`, `type_mismatch`.
  - `incomplete`: `required_null`; `enum_value` (giá trị không thuộc enum của pack sau khi áp `enum_map`; vd `target.metric_key ∈ {net_sales, gross_margin_pct}`); `duplicate_key` (chỉ khi entity khai báo field `key` và **mọi** field key đều map được — `target` của B không có key nên không kiểm).
  - Danh sách dòng ≤ 20, `Count` luôn đủ; giá trị enum lạ liệt kê ≤ 10.

- [ ] **Step 1: Viết test thất bại**

`ennam.kg.go/internal/intel/filedata/helpers_test.go`:
```go
package filedata

import "github.com/ennam/ennam-kg/internal/intel"

// targetEntity mirrors Plan B's packs/retail/daab/canonical.yaml entity `target`
// (all fields required, no key) — the demo's store_targets dataset feeds it.
func targetEntity() *intel.Entity {
	return &intel.Entity{Name: "target", Fields: []intel.Field{
		{Name: "location_id", Type: intel.TypeText, Required: true},
		{Name: "metric_key", Type: intel.TypeText, Required: true},
		{Name: "period", Type: intel.TypeDate, Required: true},
		{Name: "value", Type: intel.TypeNumeric, Required: true},
	}}
}

// targetEnums mirrors `enums: target.metric_key: [net_sales, gross_margin_pct]`.
func targetEnums() map[string][]string {
	return map[string][]string{"metric_key": {"net_sales", "gross_margin_pct"}}
}

func targetColumns() []Column {
	return []Column{
		{Name: "store_id", Type: TypeText},
		{Name: "metric_key", Type: TypeText},
		{Name: "period", Type: TypeDate},
		{Name: "target_value", Type: TypeNumeric},
	}
}

func targetMapping() intel.Mapping {
	return intel.Mapping{ProjectID: "4ad7a5fa-a036-4f6a-8229-39a20af23e38", Entity: "target", Mode: intel.ModeFile,
		FileDataset: "store_targets", Status: intel.MappingApproved,
		Spec: intel.MappingSpec{Fields: map[string]string{
			"location_id": "store_id",
			"metric_key":  "metric_key",
			"period":      "period",
			"value":       "target_value",
		}}}
}

// targetRow builds a stored row; "" is an empty cell.
func targetRow(n int, store, metric, period, value string) StoredRow {
	c := cells(store, metric, period, value)
	return StoredRow{RowNum: n, Values: map[string]*string{
		"store_id": c[0], "metric_key": c[1], "period": c[2], "target_value": c[3],
	}}
}
```

`ennam.kg.go/internal/intel/filedata/validate_test.go`:
```go
package filedata

import (
	"fmt"
	"reflect"
	"testing"

	"github.com/ennam/ennam-kg/internal/intel"
)

func issueCodes(r EntityReport) []string {
	out := make([]string, len(r.Issues))
	for i, is := range r.Issues {
		out[i] = is.Code
	}
	return out
}

func validTargets() []StoredRow {
	return []StoredRow{
		targetRow(1, "S1", "net_sales", "2026-07-01", "100"),
		targetRow(2, "S1", "gross_margin_pct", "2026-07-01", "35"),
	}
}

func TestValidate_CleanTargetsAreCurrent(t *testing.T) {
	rep := Validate(targetColumns(), validTargets(), targetMapping(), targetEntity(), targetEnums())
	if rep.Status != intel.StatusCurrent || len(rep.Issues) != 0 {
		t.Fatalf("status=%s issues=%v", rep.Status, rep.Issues)
	}
	if len(rep.Columns) != 4 || rep.Columns[3].CanonicalType != intel.TypeNumeric || rep.Columns[0].NullRatio != 0 {
		t.Errorf("columns = %+v", rep.Columns)
	}
}

// A required field the mapping forgot would make every metric on this entity
// fail; it must block, not just warn.
func TestValidate_UnmappedRequiredFieldBlocks(t *testing.T) {
	m := targetMapping()
	delete(m.Spec.Fields, "value")
	rep := Validate(targetColumns(), validTargets(), m, targetEntity(), targetEnums())
	if rep.Status != intel.StatusBlocked || !reflect.DeepEqual(issueCodes(rep), []string{"missing_field"}) || rep.Issues[0].Field != "value" {
		t.Fatalf("report = %+v", rep)
	}
}

func TestValidate_MappedColumnMissingFromDatasetBlocks(t *testing.T) {
	m := targetMapping()
	m.Spec.Fields["value"] = "amount"
	rep := Validate(targetColumns(), nil, m, targetEntity(), targetEnums())
	if rep.Status != intel.StatusBlocked || issueCodes(rep)[0] != "missing_column" || rep.Issues[0].Column != "amount" {
		t.Fatalf("report = %+v", rep)
	}
}

// Plan B's contract: mode=file fields are bare dataset column names.
func TestValidate_ExpressionInFileMappingBlocks(t *testing.T) {
	m := targetMapping()
	m.Spec.Fields["value"] = "target_value * 1000"
	rep := Validate(targetColumns(), validTargets(), m, targetEntity(), targetEnums())
	if rep.Status != intel.StatusBlocked || issueCodes(rep)[0] != "unsupported_expression" {
		t.Fatalf("report = %+v", rep)
	}
}

func TestValidate_TextColumnCannotFeedNumericField(t *testing.T) {
	cols := targetColumns()
	cols[3].Type = TypeText // e.g. "1,234.5" with a thousands separator
	rep := Validate(cols, []StoredRow{targetRow(1, "S1", "net_sales", "2026-07-01", "1,234.5")}, targetMapping(), targetEntity(), targetEnums())
	if rep.Status != intel.StatusBlocked || issueCodes(rep)[0] != "type_mismatch" {
		t.Fatalf("report = %+v", rep)
	}
}

func TestValidate_RequiredNullsAreIncompleteWithRowNumbers(t *testing.T) {
	rows := []StoredRow{
		targetRow(1, "S1", "net_sales", "2026-07-01", "1"),
		targetRow(2, "S2", "net_sales", "2026-07-01", ""),
		targetRow(3, "S3", "net_sales", "2026-07-01", "3"),
		targetRow(4, "S4", "net_sales", "2026-07-01", "4"),
		targetRow(5, "S5", "net_sales", "2026-07-01", ""),
	}
	rep := Validate(targetColumns(), rows, targetMapping(), targetEntity(), targetEnums())
	if rep.Status != intel.StatusIncomplete || len(rep.Issues) != 1 {
		t.Fatalf("report = %+v", rep)
	}
	is := rep.Issues[0]
	if is.Code != "required_null" || is.Field != "value" || !reflect.DeepEqual(is.Rows, []int{2, 5}) || is.Count != 2 {
		t.Fatalf("issue = %+v", is)
	}
	for _, st := range rep.Columns {
		if st.Field == "value" && st.NullRatio != 0.4 {
			t.Errorf("value null ratio = %v, want 0.4", st.NullRatio)
		}
	}
}

// The target metrics filter `metric_key = 'net_sales'`: a file that says
// "retail.net_sales" or "Net Sales" would silently produce no target at all.
func TestValidate_ValuesOutsideTheEnumAreIncomplete(t *testing.T) {
	rows := []StoredRow{
		targetRow(1, "S1", "net_sales", "2026-07-01", "1"),
		targetRow(2, "S1", "retail.net_sales", "2026-08-01", "1"),
		targetRow(3, "S2", "Net Sales", "2026-07-01", "1"),
	}
	rep := Validate(targetColumns(), rows, targetMapping(), targetEntity(), targetEnums())
	if rep.Status != intel.StatusIncomplete || len(rep.Issues) != 1 {
		t.Fatalf("report = %+v", rep)
	}
	is := rep.Issues[0]
	if is.Code != "enum_value" || !reflect.DeepEqual(is.Rows, []int{2, 3}) ||
		!reflect.DeepEqual(is.Values, []string{"retail.net_sales", "Net Sales"}) {
		t.Fatalf("issue = %+v", is)
	}
}

// enum_map is applied first, like the compiler's CASE: mapped values pass,
// values the map does not list become invalid.
func TestValidate_EnumMapNormalisesBeforeChecking(t *testing.T) {
	m := targetMapping()
	m.Spec.EnumMap = map[string]map[string]string{"metric_key": {"Net Sales": "net_sales", "GM%": "gross_margin_pct"}}
	rows := []StoredRow{
		targetRow(1, "S1", "Net Sales", "2026-07-01", "1"),
		targetRow(2, "S1", "GM%", "2026-07-01", "30"),
		targetRow(3, "S1", "net_sales", "2026-08-01", "1"),
	}
	rep := Validate(targetColumns(), rows, m, targetEntity(), targetEnums())
	if len(rep.Issues) != 1 || rep.Issues[0].Code != "enum_value" || !reflect.DeepEqual(rep.Issues[0].Rows, []int{3}) {
		t.Fatalf("report = %+v", rep)
	}
}

func TestValidate_DuplicateKeyIsIncompleteWhenThePackDeclaresKeys(t *testing.T) {
	ent := targetEntity()
	for i := 0; i < 3; i++ { // location_id, metric_key, period
		ent.Fields[i].Key = true
	}
	rows := []StoredRow{
		targetRow(1, "S1", "net_sales", "2026-07-01", "1"),
		targetRow(2, "S2", "net_sales", "2026-07-01", "2"),
		targetRow(3, "S1", "net_sales", "2026-07-01", "9"),
	}
	rep := Validate(targetColumns(), rows, targetMapping(), ent, targetEnums())
	if rep.Status != intel.StatusIncomplete || len(rep.Issues) != 1 || rep.Issues[0].Code != "duplicate_key" {
		t.Fatalf("report = %+v", rep)
	}
	if !reflect.DeepEqual(rep.Issues[0].Rows, []int{1, 3}) {
		t.Errorf("rows = %v", rep.Issues[0].Rows)
	}
	// Plan B's target has no key: the same rows are not reported as duplicates.
	if rep2 := Validate(targetColumns(), rows, targetMapping(), targetEntity(), targetEnums()); len(rep2.Issues) != 0 {
		t.Errorf("keyless entity must not report duplicates: %+v", rep2.Issues)
	}
}

func TestValidate_IssueRowListIsCappedButCountIsExact(t *testing.T) {
	var rows []StoredRow
	for i := 1; i <= 25; i++ {
		rows = append(rows, targetRow(i, fmt.Sprintf("S%d", i), "net_sales", "2026-07-01", ""))
	}
	rep := Validate(targetColumns(), rows, targetMapping(), targetEntity(), targetEnums())
	if len(rep.Issues[0].Rows) != MaxIssueRows || rep.Issues[0].Count != 25 {
		t.Fatalf("issue = %+v", rep.Issues[0])
	}
}

func TestValidate_WiderColumnTypesAreAccepted(t *testing.T) {
	cols := targetColumns()
	cols[2].Type = TypeTimestamp // period stored with a time part
	cols[3].Type = TypeInteger   // whole-number targets
	rep := Validate(cols, []StoredRow{targetRow(1, "S1", "net_sales", "2026-07-01T00:00:00", "100")}, targetMapping(), targetEntity(), targetEnums())
	if rep.Status != intel.StatusCurrent {
		t.Fatalf("report = %+v", rep)
	}
}

func TestValidate_UnknownMappedFieldBlocks(t *testing.T) {
	m := targetMapping()
	m.Spec.Fields["region"] = "store_id"
	rep := Validate(targetColumns(), nil, m, targetEntity(), targetEnums())
	if rep.Status != intel.StatusBlocked || issueCodes(rep)[0] != "unknown_field" {
		t.Fatalf("report = %+v", rep)
	}
}

func TestValidate_TooManyDuplicateGroupsMarksTruncated(t *testing.T) {
	ent := targetEntity()
	ent.Fields[0].Key = true // location_id
	var rows []StoredRow
	n := 0
	for g := 0; g < MaxDuplicateGroups+2; g++ {
		for k := 0; k < 2; k++ {
			n++
			rows = append(rows, targetRow(n, fmt.Sprintf("S%d", g), "net_sales", "2026-07-01", "1"))
		}
	}
	rep := Validate(targetColumns(), rows, targetMapping(), ent, targetEnums())
	if len(rep.Issues) != MaxDuplicateGroups || !rep.IssuesTruncated {
		t.Fatalf("issues=%d truncated=%v", len(rep.Issues), rep.IssuesTruncated)
	}
}

func TestCastable(t *testing.T) {
	ok := []struct {
		col   string
		canon intel.FieldType
	}{
		{TypeInteger, intel.TypeNumeric}, {TypeInteger, intel.TypeInteger}, {TypeNumeric, intel.TypeNumeric},
		{TypeDate, intel.TypeTimestamp}, {TypeTimestamp, intel.TypeDate}, {TypeBoolean, intel.TypeBoolean},
		{TypeNumeric, intel.TypeText}, {TypeText, intel.TypeText},
	}
	for _, c := range ok {
		if !castable(c.col, c.canon) {
			t.Errorf("castable(%s, %s) = false", c.col, c.canon)
		}
	}
	for _, c := range []struct {
		col   string
		canon intel.FieldType
	}{{TypeText, intel.TypeNumeric}, {TypeNumeric, intel.TypeInteger}, {TypeBoolean, intel.TypeNumeric}, {TypeDate, intel.TypeBoolean}} {
		if castable(c.col, c.canon) {
			t.Errorf("castable(%s, %s) = true", c.col, c.canon)
		}
	}
}
```

- [ ] **Step 2: Chạy test, phải FAIL**

```bash
cd ennam.kg.go && go test ./internal/intel/filedata/ -run 'TestValidate|TestCastable' -count=1
```
Expected: FAIL do build `undefined: Validate`. (Nếu báo `package github.com/ennam/ennam-kg/internal/intel` thiếu `Mapping`/`Entity` ⇒ Plan B Task 2–3 chưa merge ⇒ dừng, chờ B.)

- [ ] **Step 3: Implement**

`ennam.kg.go/internal/intel/filedata/source_table_cast.go`:
```go
package filedata

import "github.com/ennam/ennam-kg/internal/intel"

// pgType is the PostgreSQL type every stored canonical string of a column type
// casts to without error (the parser guarantees the string forms).
func pgType(columnType string) string {
	switch columnType {
	case TypeInteger:
		return "bigint"
	case TypeNumeric:
		return "numeric"
	case TypeBoolean:
		return "boolean"
	case TypeDate:
		return "date"
	case TypeTimestamp:
		return "timestamp"
	default:
		return "text"
	}
}

// pgDataType is the type reported in intel.SourceColumn.DataType (information_schema
// spelling, like livesource). "without time zone" keeps the compiler from applying
// a timezone conversion: file timestamps are local wall-clock time already.
func pgDataType(columnType string) string {
	if columnType == TypeTimestamp {
		return "timestamp without time zone"
	}
	return pgType(columnType)
}

// castable reports whether every stored value of columnType survives the
// compiler's CAST(... AS <canonical type>).
func castable(columnType string, canonical intel.FieldType) bool {
	switch canonical {
	case intel.TypeText:
		return validType(columnType)
	case intel.TypeInteger:
		return columnType == TypeInteger
	case intel.TypeNumeric:
		return columnType == TypeInteger || columnType == TypeNumeric
	case intel.TypeBoolean:
		return columnType == TypeBoolean
	case intel.TypeDate, intel.TypeTimestamp:
		return columnType == TypeDate || columnType == TypeTimestamp
	}
	return false
}
```

`ennam.kg.go/internal/intel/filedata/validate.go`:
```go
package filedata

import (
	"fmt"
	"slices"
	"sort"
	"strings"

	"github.com/ennam/ennam-kg/internal/intel"
)

// Report list caps; Issue.Count always carries the full number.
const (
	MaxIssueRows       = 20
	MaxDuplicateGroups = 20
	MaxEnumValues      = 10
)

// Issue is one validation finding shown to the uploader. Rows are dataset row_num values.
type Issue struct {
	Code    string   `json:"code"`
	Message string   `json:"message"`
	Field   string   `json:"field,omitempty"`
	Column  string   `json:"column,omitempty"`
	Rows    []int    `json:"rows,omitempty"`
	Count   int      `json:"count,omitempty"`
	Values  []string `json:"values,omitempty"`
}

// ColumnStat summarises one mapped column.
type ColumnStat struct {
	Field         string          `json:"field"`
	Column        string          `json:"column"`
	ColumnType    string          `json:"column_type"`
	CanonicalType intel.FieldType `json:"canonical_type"`
	NullCount     int             `json:"null_count"`
	NullRatio     float64         `json:"null_ratio"`
}

// EntityReport is the validation result for one entity fed by a dataset.
type EntityReport struct {
	Entity          string       `json:"entity"`
	Status          string       `json:"status"`
	Issues          []Issue      `json:"issues"`
	Columns         []ColumnStat `json:"columns"`
	IssuesTruncated bool         `json:"issues_truncated,omitempty"`
}

// Validate checks a dataset against one approved mode=file mapping, the entity's
// canonical fields and its enums ("<field>" → allowed values).
func Validate(columns []Column, rows []StoredRow, m intel.Mapping, ent *intel.Entity, enums map[string][]string) EntityReport {
	rep := EntityReport{Entity: m.Entity, Status: intel.StatusCurrent, Issues: []Issue{}, Columns: []ColumnStat{}}
	colTypes := make(map[string]string, len(columns))
	for _, c := range columns {
		colTypes[c.Name] = c.Type
	}

	for _, field := range sortedKeys(m.Spec.Fields) {
		if _, ok := ent.Field(field); !ok {
			rep.add(Issue{Code: "unknown_field", Field: field,
				Message: fmt.Sprintf("mapping field %q is not part of entity %q", field, m.Entity)}, true)
		}
	}

	usable := make(map[string]string, len(ent.Fields))
	for _, f := range ent.Fields {
		raw, mapped := m.Spec.Fields[f.Name]
		if !mapped {
			if f.Required {
				rep.add(Issue{Code: "missing_field", Field: f.Name,
					Message: fmt.Sprintf("required field %q is not mapped to a column", f.Name)}, true)
			}
			continue
		}
		column := strings.TrimSpace(raw)
		if !identRE.MatchString(column) {
			rep.add(Issue{Code: "unsupported_expression", Field: f.Name, Column: raw,
				Message: fmt.Sprintf("field %q: file mappings must name one dataset column, got %q", f.Name, raw)}, true)
			continue
		}
		colType, exists := colTypes[column]
		if !exists {
			rep.add(Issue{Code: "missing_column", Field: f.Name, Column: column,
				Message: fmt.Sprintf("column %q (for field %q) is not in the dataset", column, f.Name)}, true)
			continue
		}
		if !castable(colType, f.Type) {
			rep.add(Issue{Code: "type_mismatch", Field: f.Name, Column: column,
				Message: fmt.Sprintf("column %q holds %s values but field %q needs %s", column, colType, f.Name, f.Type)}, true)
			continue
		}
		usable[f.Name] = column
		nulls := nullRows(rows, column)
		stat := ColumnStat{Field: f.Name, Column: column, ColumnType: colType, CanonicalType: f.Type, NullCount: len(nulls)}
		if len(rows) > 0 {
			stat.NullRatio = float64(len(nulls)) / float64(len(rows))
		}
		rep.Columns = append(rep.Columns, stat)
		if f.Required && len(nulls) > 0 {
			rep.add(Issue{Code: "required_null", Field: f.Name, Column: column, Rows: capRows(nulls), Count: len(nulls),
				Message: fmt.Sprintf("required field %q is empty in %d of %d rows", f.Name, len(nulls), len(rows))}, false)
		}
		if allowed, ok := enums[f.Name]; ok {
			rep.checkEnum(rows, f.Name, column, allowed, m.Spec.EnumMap[f.Name])
		}
	}
	rep.checkDuplicateKeys(rows, keyColumns(ent, usable))
	return rep
}

func (r *EntityReport) add(issue Issue, blocking bool) {
	r.Issues = append(r.Issues, issue)
	if blocking {
		r.Status = intel.StatusBlocked
	} else if r.Status == intel.StatusCurrent {
		r.Status = intel.StatusIncomplete
	}
}

// checkEnum mirrors the compiler: enum_map (if any) is applied first and values
// it does not list become NULL; anything outside the pack's enum is reported.
func (r *EntityReport) checkEnum(rows []StoredRow, field, column string, allowed []string, enumMap map[string]string) {
	var bad []int
	var values []string
	seen := map[string]bool{}
	for _, row := range rows {
		v := row.Values[column]
		if v == nil {
			continue // empty cells are reported as required_null
		}
		canonical := *v
		if enumMap != nil {
			canonical = enumMap[*v]
		}
		if slices.Contains(allowed, canonical) {
			continue
		}
		bad = append(bad, row.RowNum)
		if !seen[*v] && len(values) < MaxEnumValues {
			values = append(values, *v)
		}
		seen[*v] = true
	}
	if len(bad) == 0 {
		return
	}
	r.add(Issue{Code: "enum_value", Field: field, Column: column, Rows: capRows(bad), Count: len(bad), Values: values,
		Message: fmt.Sprintf("field %q accepts only %s; %d rows have other values", field, strings.Join(allowed, ", "), len(bad))}, false)
}

// keyColumns returns the columns of the entity's key fields, or nil when the
// entity has no key or a key field is not usable.
func keyColumns(ent *intel.Entity, usable map[string]string) []string {
	var cols []string
	for _, f := range ent.Fields {
		if !f.Key {
			continue
		}
		col, ok := usable[f.Name]
		if !ok {
			return nil
		}
		cols = append(cols, col)
	}
	return cols
}

func (r *EntityReport) checkDuplicateKeys(rows []StoredRow, keyCols []string) {
	if len(keyCols) == 0 {
		return
	}
	groups := make(map[string][]int)
	var order []string
	for _, row := range rows {
		parts := make([]string, len(keyCols))
		complete := true
		for i, c := range keyCols {
			v := row.Values[c]
			if v == nil {
				complete = false
				break
			}
			parts[i] = *v
		}
		if !complete {
			continue // empty key cells are reported as required_null
		}
		k := strings.Join(parts, "\x1f")
		if _, seen := groups[k]; !seen {
			order = append(order, k)
		}
		groups[k] = append(groups[k], row.RowNum)
	}
	reported := 0
	for _, k := range order {
		nums := groups[k]
		if len(nums) < 2 {
			continue
		}
		if reported == MaxDuplicateGroups {
			r.IssuesTruncated = true
			break
		}
		reported++
		r.add(Issue{Code: "duplicate_key", Column: strings.Join(keyCols, ","), Rows: capRows(nums), Count: len(nums),
			Message: fmt.Sprintf("key (%s) = (%s) appears in %d rows",
				strings.Join(keyCols, ", "), strings.ReplaceAll(k, "\x1f", ", "), len(nums))}, false)
	}
}

func nullRows(rows []StoredRow, column string) []int {
	var out []int
	for _, r := range rows {
		if r.Values[column] == nil {
			out = append(out, r.RowNum)
		}
	}
	return out
}

func capRows(nums []int) []int {
	if len(nums) > MaxIssueRows {
		nums = nums[:MaxIssueRows]
	}
	return append([]int(nil), nums...)
}

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
```

- [ ] **Step 4: Chạy test, phải PASS**

```bash
cd ennam.kg.go && go test ./internal/intel/filedata/ -run 'TestValidate|TestCastable' -count=1 -v | grep -E -- '--- (PASS|FAIL)|^ok|^FAIL'
```
Expected: 14 `--- PASS`, `ok`.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/intel/filedata/validate.go internal/intel/filedata/source_table_cast.go internal/intel/filedata/helpers_test.go internal/intel/filedata/validate_test.go
git -C ennam.kg.go commit -m "feat(filedata): validate datasets against file-mode mappings, canonical fields and enums"
```

---

### Task 8: Go — `FileTable` (`intel.SourceTable`), `Resolver` (`intel.SourceResolver` cho `intel.ModeFile`), adapter canonical

**Files:**
- Create: `ennam.kg.go/internal/intel/filedata/source_table.go`
- Create: `ennam.kg.go/internal/intel/filedata/resolver.go`
- Create: `ennam.kg.go/internal/intel/filedata/canonical.go`
- Test: `ennam.kg.go/internal/intel/filedata/source_table_test.go`, `ennam.kg.go/internal/intel/filedata/canonical_test.go`, `ennam.kg.go/internal/intel/filedata/resolver_integration_test.go`

**Interfaces:**
- Consumes (Plan B, `github.com/ennam/ennam-kg/internal/intel`, file `internal/intel/source.go` — Task 3 của B):
  ```go
  type SourceColumn struct { Name string; DataType string }
  type SourceTable interface { Relation() string; Filter() string; RefLabel() string; Columns() []SourceColumn; ColumnSQL(name string) string }
  type QueryExecutor interface { Query(ctx context.Context, sql string, args []any, maxRows int) (*QueryRows, error) }
  type BoundSource struct { Table SourceTable; Executor QueryExecutor; Watermark string }
  type SourceResolver interface { Prepare(ctx context.Context, projectID string, ms []Mapping) error; Bind(ctx context.Context, projectID string, m Mapping) (*BoundSource, error) }
  var ErrSourceNotReady = errors.New("source not ready")
  type MappingError struct { Entity string; Code string; Detail string }
  ```
  `(*intel.Registry).Effective(keys []string) (*intel.Catalog, error)` với `Catalog.Entities map[string]*Entity`, `Catalog.Enums map[string][]string` (`"<entity>.<field>"`), `Registry.Packs` (map theo pack key) — cùng cách `(*Registry).CanonicalEntity` của B gom mọi pack đã nạp; `sqlexec.New(db, 30*time.Second)` (executor READ ONLY trong `ennam_kg`, Task 7 của B) được truyền vào `NewResolver` khi wiring (Task 10).
- Produces:
```go
var _ intel.SourceTable = (*FileTable)(nil)
func NewFileTable(ds Dataset) *FileTable
func (t *FileTable) Relation() string                // "file_dataset_row AS src"
func (t *FileTable) Filter() string                  // "src.dataset_id = '<uuid>'"
func (t *FileTable) RefLabel() string                // tên dataset
func (t *FileTable) Columns() []intel.SourceColumn   // {Name, DataType: pgDataType(type)}
func (t *FileTable) ColumnSQL(name string) string    // "CAST(NULLIF(src.data->>'col', '') AS <pgType>)"

type CanonicalSource interface { Entity(name string) (*intel.Entity, map[string][]string, bool) } // fields + enums theo field
func NewRegistryCanonical(reg *intel.Registry) CanonicalSource

var _ intel.SourceResolver = (*Resolver)(nil)
func NewResolver(datasets DatasetGetter, exec intel.QueryExecutor, canonical CanonicalSource) *Resolver
func (r *Resolver) Prepare(ctx context.Context, projectID string, ms []intel.Mapping) error // nil
func (r *Resolver) Bind(ctx context.Context, projectID string, m intel.Mapping) (*intel.BoundSource, error)
type DatasetGetter interface { GetByName(ctx context.Context, projectID uuid.UUID, name string) (*Dataset, error) }
```
- Ngữ nghĩa `Bind` (khớp cách runner B xử lý lỗi, `prepareEntity`):
  - dataset chưa upload / 0 dòng ⇒ lỗi bọc `intel.ErrSourceNotReady` ⇒ entity `incomplete`, mapping **giữ** `approved`;
  - cột không có trong dataset, biểu thức không phải tên cột trần, hoặc kiểu cột không ép được sang kiểu canonical ⇒ **cũng** bọc `intel.ErrSourceNotReady` (không trả `*intel.MappingError`). Lý do: ở mode=file, "schema" là file vừa upload — runner B biến `MappingError` thành mapping `broken` vĩnh viễn (phải import lại), trong khi chỉ cần upload lại file đúng là hết lỗi. Upload-time validation (Task 9) đã báo chi tiết từng cột cho người upload.
  - `Watermark = "file:" + updated_at (RFC3339Nano, UTC)` của dataset.
- Compiler B tự bọc `CAST(<ColumnSQL> AS <kiểu canonical>)`; `ColumnSQL` đã ép về `pgType` của cột nên cast ngoài luôn thành công khi `castable` đúng. Entity không có field `key` (vd `target`) ⇒ `_source_ref` = NULL (hành vi của compiler B).

- [ ] **Step 1: Viết test thất bại**

`ennam.kg.go/internal/intel/filedata/source_table_test.go`:
```go
package filedata

import (
	"reflect"
	"testing"

	"github.com/google/uuid"

	"github.com/ennam/ennam-kg/internal/intel"
)

func sampleTable() *FileTable {
	return NewFileTable(Dataset{
		ID:   uuid.MustParse("11111111-2222-3333-4444-555555555555"),
		Name: "store_targets",
		Columns: []Column{
			{Name: "store_id", Type: TypeText},
			{Name: "period", Type: TypeDate},
			{Name: "sold_at", Type: TypeTimestamp},
			{Name: "qty", Type: TypeInteger},
			{Name: "target_value", Type: TypeNumeric},
			{Name: "active", Type: TypeBoolean},
		},
	})
}

// The compiler builds `"<entity>" AS (SELECT … FROM <Relation> WHERE <Filter>)`
// and expects the alias "src" (Plan B Exports).
func TestFileTable_RelationFilterRefLabel(t *testing.T) {
	ft := sampleTable()
	if ft.Relation() != "file_dataset_row AS src" {
		t.Errorf("Relation = %q", ft.Relation())
	}
	if ft.Filter() != "src.dataset_id = '11111111-2222-3333-4444-555555555555'" {
		t.Errorf("Filter = %q", ft.Filter())
	}
	if ft.RefLabel() != "store_targets" {
		t.Errorf("RefLabel = %q", ft.RefLabel())
	}
}

func TestFileTable_ColumnsReportPostgresTypes(t *testing.T) {
	want := []intel.SourceColumn{
		{Name: "store_id", DataType: "text"},
		{Name: "period", DataType: "date"},
		{Name: "sold_at", DataType: "timestamp without time zone"},
		{Name: "qty", DataType: "bigint"},
		{Name: "target_value", DataType: "numeric"},
		{Name: "active", DataType: "boolean"},
	}
	if got := sampleTable().Columns(); !reflect.DeepEqual(got, want) {
		t.Fatalf("Columns = %+v", got)
	}
}

// Empty cells are JSON null; NULLIF also guards against "" so the typed cast
// never sees an empty string.
func TestFileTable_ColumnSQLCastsToTheStoredType(t *testing.T) {
	ft := sampleTable()
	cases := map[string]string{
		"store_id":     "CAST(NULLIF(src.data->>'store_id', '') AS text)",
		"period":       "CAST(NULLIF(src.data->>'period', '') AS date)",
		"sold_at":      "CAST(NULLIF(src.data->>'sold_at', '') AS timestamp)",
		"qty":          "CAST(NULLIF(src.data->>'qty', '') AS bigint)",
		"target_value": "CAST(NULLIF(src.data->>'target_value', '') AS numeric)",
		"active":       "CAST(NULLIF(src.data->>'active', '') AS boolean)",
		"QTY":          "CAST(NULLIF(src.data->>'qty', '') AS bigint)", // validator matches names case-insensitively
	}
	for name, want := range cases {
		if got := ft.ColumnSQL(name); got != want {
			t.Errorf("ColumnSQL(%s) = %q, want %q", name, got, want)
		}
	}
	// Never emits caller text: an unknown name yields a typed NULL, not SQL.
	if got := ft.ColumnSQL("x') OR true --"); got != "CAST(NULL AS text)" {
		t.Errorf("unknown column = %q", got)
	}
}
```

`ennam.kg.go/internal/intel/filedata/canonical_test.go`:
```go
package filedata

import (
	"reflect"
	"testing"

	"github.com/ennam/ennam-kg/internal/intel"
)

// Uses Plan B's neutral test packs (base + child extends base).
func TestRegistryCanonical_FieldsAndEnumsOfMergedEntity(t *testing.T) {
	reg, err := intel.LoadRegistry("../testdata/packs")
	if err != nil {
		t.Fatal(err)
	}
	ent, enums, ok := NewRegistryCanonical(reg).Entity("order")
	if !ok {
		t.Fatal("entity order not found")
	}
	if _, ok := ent.Field("channel"); !ok {
		t.Error("field added by the child pack must be present")
	}
	if !reflect.DeepEqual(enums["status"], []string{"open", "closed"}) {
		t.Errorf("enums = %v", enums)
	}
	if _, _, ok := NewRegistryCanonical(reg).Entity("nope"); ok {
		t.Error("unknown entity must not be found")
	}
}
```

`ennam.kg.go/internal/intel/filedata/resolver_integration_test.go`:
```go
package filedata

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/sqlexec"
)

type staticCanonical struct {
	ent   *intel.Entity
	enums map[string][]string
}

func (s staticCanonical) Entity(name string) (*intel.Entity, map[string][]string, bool) {
	if s.ent == nil || s.ent.Name != name {
		return nil, nil, false
	}
	return s.ent, s.enums, true
}

func newTestResolver(t *testing.T) (*Resolver, *Store, string) {
	t.Helper()
	db := openTestDB(t)
	pid := seedProject(t, db)
	st := NewStore(db)
	return NewResolver(st, sqlexec.New(db, 30*time.Second), staticCanonical{targetEntity(), targetEnums()}), st, pid.String()
}

func TestResolver_DatasetNotUploadedIsNotReady(t *testing.T) {
	r, _, pid := newTestResolver(t)
	_, err := r.Bind(context.Background(), pid, targetMapping())
	if !errors.Is(err, intel.ErrSourceNotReady) {
		t.Fatalf("err = %v, want ErrSourceNotReady", err)
	}
}

// A bad upload must not break the mapping forever: the runner turns
// *MappingError into mapping=broken, so file problems are "not ready" instead.
func TestResolver_BadColumnTypeIsNotReadyNotMappingError(t *testing.T) {
	r, st, pid := newTestResolver(t)
	cols := targetColumns()
	cols[3].Type = TypeText
	if _, err := st.Write(context.Background(), []WriteInput{{ProjectID: mustUUID(t, pid), Name: "store_targets", WriteMode: WriteReplace,
		Columns: cols, Rows: [][]*string{cells("S1", "net_sales", "2026-07-01", "1,000")}}}); err != nil {
		t.Fatal(err)
	}
	_, err := r.Bind(context.Background(), pid, targetMapping())
	var me *intel.MappingError
	if !errors.Is(err, intel.ErrSourceNotReady) || errors.As(err, &me) {
		t.Fatalf("err = %v, want ErrSourceNotReady and no MappingError", err)
	}
	if !strings.Contains(err.Error(), "target_value") {
		t.Errorf("error must name the column: %v", err)
	}
}

// End to end through the bound executor: Relation + Filter + ColumnSQL run
// read-only in ennam_kg and only see this dataset's rows.
func TestResolver_BoundSourceReadsOnlyItsDataset(t *testing.T) {
	r, st, pid := newTestResolver(t)
	ctx := context.Background()
	for _, name := range []string{"store_targets", "other_dataset"} {
		if _, err := st.Write(ctx, []WriteInput{{ProjectID: mustUUID(t, pid), Name: name, WriteMode: WriteReplace, Columns: targetColumns(),
			Rows: [][]*string{cells("S1", "net_sales", "2026-07-01", "1000.50"), cells("S2", "gross_margin_pct", "2026-07-01", "")}}}); err != nil {
			t.Fatal(err)
		}
	}
	b, err := r.Bind(ctx, pid, targetMapping())
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(b.Watermark, "file:") {
		t.Errorf("watermark = %q", b.Watermark)
	}
	tbl := b.Table
	q := "SELECT " + tbl.ColumnSQL("store_id") + ", " + tbl.ColumnSQL("target_value") + ", " + tbl.ColumnSQL("period") +
		" FROM " + tbl.Relation() + " WHERE " + tbl.Filter() + " ORDER BY src.row_num"
	res, err := b.Executor.Query(ctx, q, nil, 10)
	if err != nil {
		t.Fatalf("query %s: %v", q, err)
	}
	if len(res.Rows) != 2 || res.Truncated {
		t.Fatalf("rows = %+v", res.Rows)
	}
	if res.Rows[0][0] != "S1" || res.Rows[0][1] != "1000.50" || res.Rows[1][1] != nil {
		t.Errorf("rows = %+v (empty cell must be NULL)", res.Rows)
	}
	if d, ok := res.Rows[0][2].(time.Time); !ok || d.Format("2006-01-02") != "2026-07-01" {
		t.Errorf("period = %#v", res.Rows[0][2])
	}
}
```
- [ ] **Step 2: Chạy test, phải FAIL**

```bash
cd ennam.kg.go && go test ./internal/intel/filedata/ -run 'TestFileTable|TestRegistryCanonical|TestResolver' -count=1
```
Expected: FAIL do build `undefined: NewFileTable`, `undefined: NewResolver`.

- [ ] **Step 3: Implement**

`ennam.kg.go/internal/intel/filedata/source_table.go`:
```go
package filedata

import (
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/ennam/ennam-kg/internal/intel"
)

var _ intel.SourceTable = (*FileTable)(nil)

// FileTable exposes one stored dataset to the metric compiler (mode=file).
// Statements built on it run in DAAB's own database through sqlexec.
type FileTable struct {
	datasetID uuid.UUID
	name      string
	cols      []Column
	byName    map[string]Column
}

// NewFileTable wraps dataset metadata loaded by Store.GetByName or Store.Write.
func NewFileTable(ds Dataset) *FileTable {
	t := &FileTable{datasetID: ds.ID, name: ds.Name, byName: make(map[string]Column, len(ds.Columns))}
	for _, c := range ds.Columns {
		if !identRE.MatchString(c.Name) {
			continue // never put a non-identifier into a SQL literal
		}
		t.cols = append(t.cols, c)
		t.byName[c.Name] = c
	}
	return t
}

// Relation is the shared row table under the alias the compiler requires.
func (t *FileTable) Relation() string { return "file_dataset_row AS src" }

// Filter restricts the rows to this dataset (dataset ids come from the DB, not from users).
func (t *FileTable) Filter() string { return fmt.Sprintf("src.dataset_id = '%s'", t.datasetID) }

// RefLabel labels _source_ref values of entities that declare a key.
func (t *FileTable) RefLabel() string { return t.name }

// Columns lists the dataset columns a mapping may reference.
func (t *FileTable) Columns() []intel.SourceColumn {
	out := make([]intel.SourceColumn, len(t.cols))
	for i, c := range t.cols {
		out[i] = intel.SourceColumn{Name: c.Name, DataType: pgDataType(c.Type)}
	}
	return out
}

// ColumnSQL reads one column as its stored type; the compiler then casts it to
// the canonical type. Unknown names yield a typed NULL, never caller text.
func (t *FileTable) ColumnSQL(name string) string {
	c, ok := t.byName[strings.ToLower(name)]
	if !ok {
		return "CAST(NULL AS text)"
	}
	return fmt.Sprintf("CAST(NULLIF(src.data->>'%s', '') AS %s)", c.Name, pgType(c.Type))
}
```

`ennam.kg.go/internal/intel/filedata/canonical.go`:
```go
package filedata

import (
	"strings"

	"github.com/ennam/ennam-kg/internal/intel"
)

// CanonicalSource returns an entity's merged fields and its enums keyed by field name.
type CanonicalSource interface {
	Entity(name string) (*intel.Entity, map[string][]string, bool)
}

type registryCanonical struct {
	reg *intel.Registry
}

// NewRegistryCanonical adapts Plan B's pack registry. Like
// (*intel.Registry).CanonicalEntity it merges every loaded pack; it also returns
// the "<entity>.<field>" enums the validator needs.
func NewRegistryCanonical(reg *intel.Registry) CanonicalSource {
	return registryCanonical{reg: reg}
}

func (r registryCanonical) Entity(name string) (*intel.Entity, map[string][]string, bool) {
	keys := make([]string, 0, len(r.reg.Packs))
	for k := range r.reg.Packs {
		keys = append(keys, k)
	}
	cat, err := r.reg.Effective(keys)
	if err != nil {
		return nil, nil, false
	}
	ent, ok := cat.Entities[name]
	if !ok {
		return nil, nil, false
	}
	enums := map[string][]string{}
	prefix := name + "."
	for k, v := range cat.Enums {
		if field, found := strings.CutPrefix(k, prefix); found {
			enums[field] = v
		}
	}
	return ent, enums, true
}
```

`ennam.kg.go/internal/intel/filedata/resolver.go`:
```go
package filedata

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/ennam/ennam-kg/internal/intel"
)

var _ intel.SourceResolver = (*Resolver)(nil)

// DatasetGetter loads dataset metadata (Store in production).
type DatasetGetter interface {
	GetByName(ctx context.Context, projectID uuid.UUID, name string) (*Dataset, error)
}

// Resolver binds mode=file mappings to uploaded datasets. Register it as
// resolvers[intel.ModeFile] in buildIntel (cmd/kg-server/intel_wiring.go).
type Resolver struct {
	datasets  DatasetGetter
	exec      intel.QueryExecutor
	canonical CanonicalSource
}

// NewResolver creates a Resolver; exec is sqlexec.New(db, 30*time.Second).
func NewResolver(datasets DatasetGetter, exec intel.QueryExecutor, canonical CanonicalSource) *Resolver {
	return &Resolver{datasets: datasets, exec: exec, canonical: canonical}
}

// Prepare has nothing to refresh: uploads update file_dataset directly.
func (r *Resolver) Prepare(context.Context, string, []intel.Mapping) error { return nil }

// Bind resolves the mapping's dataset. Every data problem (not uploaded, column
// missing, column type unusable) is ErrSourceNotReady, so a bad file never marks
// the mapping broken — re-uploading a correct file recovers.
func (r *Resolver) Bind(ctx context.Context, projectID string, m intel.Mapping) (*intel.BoundSource, error) {
	if m.Mode != intel.ModeFile {
		return nil, fmt.Errorf("filedata: mapping %s has mode %s", m.Entity, m.Mode)
	}
	pid, err := uuid.Parse(projectID)
	if err != nil {
		return nil, fmt.Errorf("filedata: project id %q: %w", projectID, err)
	}
	ds, err := r.datasets.GetByName(ctx, pid, m.FileDataset)
	if errors.Is(err, ErrDatasetNotFound) {
		return nil, fmt.Errorf("filedata: dataset %q has not been uploaded: %w", m.FileDataset, intel.ErrSourceNotReady)
	}
	if err != nil {
		return nil, err
	}
	if ds.RowCount == 0 {
		return nil, fmt.Errorf("filedata: dataset %q has no rows: %w", m.FileDataset, intel.ErrSourceNotReady)
	}
	if err := r.checkFields(m, ds); err != nil {
		return nil, err
	}
	return &intel.BoundSource{
		Table:     NewFileTable(*ds),
		Executor:  r.exec,
		Watermark: "file:" + ds.UpdatedAt.UTC().Format(time.RFC3339Nano),
	}, nil
}

// checkFields enforces the mode=file contract the compiler cannot see: each
// field names one dataset column whose stored values cast to the field's type.
func (r *Resolver) checkFields(m intel.Mapping, ds *Dataset) error {
	types := make(map[string]string, len(ds.Columns))
	for _, c := range ds.Columns {
		types[c.Name] = c.Type
	}
	var ent *intel.Entity
	if r.canonical != nil {
		ent, _, _ = r.canonical.Entity(m.Entity)
	}
	for _, field := range sortedKeys(m.Spec.Fields) {
		column := strings.TrimSpace(m.Spec.Fields[field])
		colType, ok := types[column]
		if !identRE.MatchString(column) || !ok {
			return fmt.Errorf("filedata: field %s: %q is not a column of dataset %s: %w",
				field, column, ds.Name, intel.ErrSourceNotReady)
		}
		if ent == nil {
			continue // unknown entity: the compiler reports invalid_spec
		}
		if f, ok := ent.Field(field); ok && !castable(colType, f.Type) {
			return fmt.Errorf("filedata: field %s needs %s but column %s of dataset %s holds %s values: %w",
				field, f.Type, column, ds.Name, colType, intel.ErrSourceNotReady)
		}
	}
	return nil
}
```

- [ ] **Step 4: Chạy test, phải PASS và không SKIP**

```bash
cd ennam.kg.go && KG_TEST_DATABASE_URL='postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable' go test ./internal/intel/filedata/ -run 'TestFileTable|TestRegistryCanonical|TestResolver|TestStoreWrite' -count=1 -v 2>&1 | grep -E -- '--- (PASS|FAIL|SKIP)|^ok|^FAIL'
```
Expected: mọi `--- PASS` (3 FileTable + 1 canonical + 3 resolver + 7 store), không `SKIP`, `ok`.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/intel/filedata/source_table.go internal/intel/filedata/canonical.go internal/intel/filedata/resolver.go internal/intel/filedata/source_table_test.go internal/intel/filedata/canonical_test.go internal/intel/filedata/resolver_integration_test.go
git -C ennam.kg.go commit -m "feat(filedata): mode=file SourceTable and resolver for the metrics compiler"
```

---

### Task 9: Go — `Service.Ingest` (parse → write → validate → `data_status` → `intel.RunTrigger`)

**Files:**
- Create: `ennam.kg.go/internal/intel/filedata/service.go`
- Test: `ennam.kg.go/internal/intel/filedata/service_test.go`

**Interfaces:**
- Consumes (Plan B):
  - `(*intelstore.Store).ListMappings(ctx, projectID string) ([]intel.Mapping, error)`
  - `(*intelstore.Store).UpsertDataStatus(ctx, intel.DataStatus) error` (writer dùng chung; giữ `last_success_at` cũ khi nhận nil)
  - `intel.DataStatus{ProjectID, Subject, Status, LastSuccessAt, Issues []intel.Issue{Code, Message, Detail}}`; `intel.FileSubject(dataset string) string` (= `"file:" + dataset`, Plan B thêm cạnh `EntitySubject`/`MetricSubject`) cho subject `file:<dataset>` (master §2.3: kết quả validate upload của Plan C — runner B là nơi **duy nhất** ghi `entity:`/`metric:`)
  - `intel.RunTrigger{ Trigger(projectID string) }`: `*engine.Scheduler` hiện thực, **không chặn** (đẩy vào hàng đợi; đầy thì bỏ kèm warning)
  - `CanonicalSource` (Task 8).
- Produces:
```go
type Parser interface { Parse(ctx context.Context, filename string, body io.Reader, maxRows int) (*ParseResult, error) }
type DatasetWriter interface { Write(ctx context.Context, inputs []WriteInput) ([]WriteResult, error); LoadRows(ctx context.Context, datasetID uuid.UUID) ([]StoredRow, error) }
type MappingLister interface { ListMappings(ctx context.Context, projectID string) ([]intel.Mapping, error) }   // *intelstore.Store
type StatusSink interface { UpsertDataStatus(ctx context.Context, st intel.DataStatus) error }               // *intelstore.Store
type ServiceDeps struct { Parser Parser; Writer DatasetWriter; Mappings MappingLister; Canonical CanonicalSource; Status StatusSink; Trigger intel.RunTrigger; Logger *slog.Logger }
func NewService(deps ServiceDeps) *Service
type IngestInput struct { ProjectID uuid.UUID; Filename string; Body io.Reader; DatasetName, WriteMode string; SourceFileID *uuid.UUID; UploadedBy string }
type DatasetReport struct { Dataset, Sheet, WriteMode string; RowsWritten, RowOffset, RowCount int; Columns []Column; Validation []EntityReport; ValidationError string }
type IngestReport struct { Datasets []DatasetReport; HasIssues, MetricsTriggered bool; Warnings []string }
func (s *Service) Ingest(ctx context.Context, in IngestInput) (*IngestReport, error)
func DatasetNames(base string, sheets []ParsedSheet) ([]string, error)   // 1 sheet ⇒ base; nhiều ⇒ base__<key>
```
- Chỉ validate các mapping `Mode == intel.ModeFile && FileDataset == <dataset> && Status == intel.MappingApproved`.
- Mỗi dataset ghi **đúng một** `data_status` với subject `file:<dataset>` (helper `intel.FileSubject(name)` của Plan B — Plan C không tự ghép chuỗi `"file:" + …`), kể cả khi chưa có mapping nào đọc dataset: khi đó status là `current`, không issue, nghĩa là "đã nhận file".
  - Status = mức xấu nhất trong các entity được validate (`blocked` > `incomplete` > `current`).
  - Lỗi validate (vd entity không có trong pack) ⇒ `blocked` + issue `validation_error`.
  - Mỗi issue thành `intel.Issue{Code, Message, Detail: {entity, field, column, rows, count, values}}`.
  - `LastSuccessAt = now` trừ khi `blocked`; writer của B giữ giá trị cũ khi nhận nil.
  - Ghi status lỗi ⇒ báo vào `ValidationError`, không trigger.
- Plan C **không bao giờ** ghi `entity:` hay `metric:`.
- Cảnh báo `Warnings`: workbook nhiều sheet được lưu thành `<name>__<key>`. Nếu có mapping approved đang đọc đúng `<name>` thì báo cho người upload rằng dataset đó **không** được cập nhật (vd file vừa thêm sheet thứ 2).
- `Trigger(projectID.String())` được gọi **đúng một lần** khi: ghi xong (sau commit), có ít nhất một entity được validate, không entity nào `blocked` và không có lỗi validate. `Trigger` không chặn ⇒ gọi trực tiếp, không cần goroutine riêng. `Trigger == nil` (lớp metrics tắt) ⇒ không gọi, `MetricsTriggered=false`.
- `entity:<name>` / `metric:<key>` do runner B ghi sau lần chạy được trigger (enum/NULL/độ tươi theo `as_of`). `file:<dataset>` là báo cáo **tức thời** của lần upload gần nhất; hai loại subject không ghi đè nhau.

- [ ] **Step 1: Viết test thất bại**

`ennam.kg.go/internal/intel/filedata/service_test.go`:
```go
package filedata

import (
	"context"
	"errors"
	"io"
	"reflect"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/ennam/ennam-kg/internal/intel"
)

type fakeParser struct {
	result     *ParseResult
	err        error
	calls      int
	gotMaxRows int
}

func (f *fakeParser) Parse(_ context.Context, _ string, _ io.Reader, maxRows int) (*ParseResult, error) {
	f.calls++
	f.gotMaxRows = maxRows
	return f.result, f.err
}

type fakeWriter struct {
	inputs []WriteInput
	err    error
	rows   []StoredRow
}

func (f *fakeWriter) Write(_ context.Context, in []WriteInput) ([]WriteResult, error) {
	f.inputs = in
	if f.err != nil {
		return nil, f.err
	}
	out := make([]WriteResult, len(in))
	for i, w := range in {
		out[i] = WriteResult{
			Dataset:     Dataset{ID: uuid.New(), ProjectID: w.ProjectID, Name: w.Name, Columns: w.Columns, WriteMode: w.WriteMode, RowCount: len(w.Rows)},
			RowsWritten: len(w.Rows),
		}
	}
	return out, nil
}

func (f *fakeWriter) LoadRows(context.Context, uuid.UUID) ([]StoredRow, error) { return f.rows, nil }

type fakeMappings []intel.Mapping

func (f fakeMappings) ListMappings(context.Context, string) ([]intel.Mapping, error) { return f, nil }

type fakeStatus struct{ got []intel.DataStatus }

func (f *fakeStatus) UpsertDataStatus(_ context.Context, st intel.DataStatus) error {
	f.got = append(f.got, st)
	return nil
}

func (f *fakeStatus) summary() []string {
	out := make([]string, len(f.got))
	for i, st := range f.got {
		out[i] = st.Subject + "=" + st.Status
	}
	return out
}

type fakeTrigger struct{ projects []string }

func (f *fakeTrigger) Trigger(projectID string) { f.projects = append(f.projects, projectID) }

type failingCanonical struct{}

func (failingCanonical) Entity(string) (*intel.Entity, map[string][]string, bool) { return nil, nil, false }

func targetSheet(key string) ParsedSheet {
	return ParsedSheet{Sheet: key, Key: key, Columns: targetColumns(),
		Rows: [][]*string{cells("S1", "net_sales", "2026-07-01", "1"), cells("S1", "gross_margin_pct", "2026-07-01", "35")}, RowCount: 2}
}

type harness struct {
	parser  *fakeParser
	writer  *fakeWriter
	status  *fakeStatus
	trigger *fakeTrigger
	svc     *Service
}

func newHarness(sheets []ParsedSheet, mappings fakeMappings, canon CanonicalSource, rows []StoredRow) *harness {
	h := &harness{
		parser:  &fakeParser{result: &ParseResult{Sheets: sheets}},
		writer:  &fakeWriter{rows: rows},
		status:  &fakeStatus{},
		trigger: &fakeTrigger{},
	}
	h.svc = NewService(ServiceDeps{Parser: h.parser, Writer: h.writer, Mappings: mappings, Canonical: canon, Status: h.status, Trigger: h.trigger})
	return h
}

func input() IngestInput {
	return IngestInput{ProjectID: uuid.MustParse("4ad7a5fa-a036-4f6a-8229-39a20af23e38"), Filename: "targets.xlsx",
		Body: strings.NewReader("x"), DatasetName: "store_targets", WriteMode: WriteReplace}
}

var cleanRows = []StoredRow{
	targetRow(1, "S1", "net_sales", "2026-07-01", "1"),
	targetRow(2, "S1", "gross_margin_pct", "2026-07-01", "35"),
}

func canon() CanonicalSource { return staticCanonical{targetEntity(), targetEnums()} }

// Review focus 4: a clean upload of a mapped dataset asks the runner for exactly one run.
func TestIngest_TriggersRunnerOnceAfterCleanUpload(t *testing.T) {
	h := newHarness([]ParsedSheet{targetSheet("")}, fakeMappings{targetMapping()}, canon(), cleanRows)

	rep, err := h.svc.Ingest(context.Background(), input())
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(h.trigger.projects, []string{"4ad7a5fa-a036-4f6a-8229-39a20af23e38"}) || !rep.MetricsTriggered || rep.HasIssues {
		t.Fatalf("trigger=%v report=%+v", h.trigger.projects, rep)
	}
	if h.writer.inputs[0].Name != "store_targets" || h.parser.gotMaxRows != MaxDatasetRows {
		t.Errorf("name=%s maxRows=%d", h.writer.inputs[0].Name, h.parser.gotMaxRows)
	}
	if !reflect.DeepEqual(h.status.summary(), []string{"file:store_targets=current"}) || h.status.got[0].LastSuccessAt == nil {
		t.Errorf("status = %+v", h.status.got)
	}
}

func TestIngest_BlockedValidationDoesNotTrigger(t *testing.T) {
	m := targetMapping()
	delete(m.Spec.Fields, "value")
	h := newHarness([]ParsedSheet{targetSheet("")}, fakeMappings{m}, canon(), cleanRows)

	rep, err := h.svc.Ingest(context.Background(), input())
	if err != nil {
		t.Fatal(err)
	}
	if len(h.trigger.projects) != 0 || rep.MetricsTriggered || !rep.HasIssues {
		t.Fatalf("trigger=%v report=%+v", h.trigger.projects, rep)
	}
	got := h.status.got
	if !reflect.DeepEqual(h.status.summary(), []string{"file:store_targets=blocked"}) || got[0].LastSuccessAt != nil ||
		len(got[0].Issues) != 1 || got[0].Issues[0].Code != "missing_field" {
		t.Errorf("status = %+v", got)
	}
	if d, _ := got[0].Issues[0].Detail.(map[string]any); d["entity"] != "target" || d["field"] != "value" {
		t.Errorf("detail = %#v", got[0].Issues[0].Detail)
	}
}

func TestIngest_WriteErrorDoesNotTriggerOrWriteStatus(t *testing.T) {
	h := newHarness([]ParsedSheet{targetSheet("")}, fakeMappings{targetMapping()}, canon(), cleanRows)
	h.writer.err = ErrColumnConflict

	_, err := h.svc.Ingest(context.Background(), input())
	if !errors.Is(err, ErrColumnConflict) {
		t.Fatalf("err = %v", err)
	}
	if len(h.trigger.projects) != 0 || len(h.status.got) != 0 {
		t.Fatalf("trigger=%v status=%v", h.trigger.projects, h.status.got)
	}
}

// Only approved mode=file mappings of THIS dataset are validated.
func TestIngest_IgnoresMappingsOfOtherDatasetsModesAndStatuses(t *testing.T) {
	other := targetMapping()
	other.Entity, other.FileDataset = "budget", "budgets"
	proposed := targetMapping()
	proposed.Entity, proposed.Status = "plan", intel.MappingProposed
	live := targetMapping()
	live.Entity, live.Mode, live.FileDataset = "location", intel.ModeLive, ""
	h := newHarness([]ParsedSheet{targetSheet("")}, fakeMappings{other, proposed, live}, canon(), cleanRows)

	rep, err := h.svc.Ingest(context.Background(), input())
	if err != nil {
		t.Fatal(err)
	}
	if len(rep.Datasets[0].Validation) != 0 || len(h.trigger.projects) != 0 || rep.Datasets[0].RowsWritten != 2 ||
		!reflect.DeepEqual(h.status.summary(), []string{"file:store_targets=current"}) {
		t.Fatalf("report=%+v status=%v trigger=%v", rep, h.status.got, h.trigger.projects)
	}
}

func TestIngest_MultiSheetWorkbookBecomesOneDatasetPerSheet(t *testing.T) {
	h := newHarness([]ParsedSheet{targetSheet("q3"), targetSheet("q4")}, nil, canon(), nil)
	rep, err := h.svc.Ingest(context.Background(), input())
	if err != nil {
		t.Fatal(err)
	}
	if h.writer.inputs[0].Name != "store_targets__q3" || h.writer.inputs[1].Name != "store_targets__q4" {
		t.Fatalf("names = %s, %s", h.writer.inputs[0].Name, h.writer.inputs[1].Name)
	}
	if rep.Datasets[1].Sheet != "q4" {
		t.Errorf("sheet = %q", rep.Datasets[1].Sheet)
	}
	if !reflect.DeepEqual(h.status.summary(), []string{"file:store_targets__q3=current", "file:store_targets__q4=current"}) {
		t.Errorf("status = %v", h.status.summary())
	}
	if len(rep.Warnings) != 0 {
		t.Errorf("no mapping reads store_targets: warnings = %v", rep.Warnings)
	}
}

// A workbook that grows from 1 to 2 data sheets is stored as name__key; the
// mapping still reading "store_targets" silently keeps the old rows — warn.
func TestIngest_WarnsWhenAMappedDatasetNameIsNotWritten(t *testing.T) {
	h := newHarness([]ParsedSheet{targetSheet("q3"), targetSheet("q4")}, fakeMappings{targetMapping()}, canon(), nil)
	rep, err := h.svc.Ingest(context.Background(), input())
	if err != nil {
		t.Fatal(err)
	}
	if len(rep.Warnings) != 1 || !strings.Contains(rep.Warnings[0], "store_targets__q3") || !rep.HasIssues {
		t.Fatalf("warnings=%v hasIssues=%v", rep.Warnings, rep.HasIssues)
	}
}

func TestIngest_RowCapFromParserPropagates(t *testing.T) {
	h := newHarness(nil, nil, canon(), nil)
	h.parser.err = &ParseError{Code: "row_cap_exceeded", Message: "too many"}
	_, err := h.svc.Ingest(context.Background(), input())
	if !errors.Is(err, ErrRowCapExceeded) || h.writer.inputs != nil {
		t.Fatalf("err=%v writerCalled=%v", err, h.writer.inputs != nil)
	}
}

func TestIngest_InvalidOptionsNeverReachTheParser(t *testing.T) {
	h := newHarness([]ParsedSheet{targetSheet("")}, nil, canon(), nil)
	for _, in := range []IngestInput{
		{ProjectID: uuid.New(), DatasetName: "Store Targets", WriteMode: WriteReplace, Body: strings.NewReader("")},
		{ProjectID: uuid.New(), DatasetName: "store_targets", WriteMode: "merge", Body: strings.NewReader("")},
	} {
		if _, err := h.svc.Ingest(context.Background(), in); !errors.Is(err, ErrInvalidInput) {
			t.Errorf("input %+v: err = %v", in, err)
		}
	}
	if h.parser.calls != 0 {
		t.Errorf("parser called %d times", h.parser.calls)
	}
}

// Fail loud: data was written but could not be validated — report it, do not trigger.
func TestIngest_UnknownEntityIsReportedAndBlocksTrigger(t *testing.T) {
	h := newHarness([]ParsedSheet{targetSheet("")}, fakeMappings{targetMapping()}, failingCanonical{}, cleanRows)
	rep, err := h.svc.Ingest(context.Background(), input())
	if err != nil {
		t.Fatal(err)
	}
	if rep.Datasets[0].ValidationError == "" || !rep.HasIssues || len(h.trigger.projects) != 0 {
		t.Fatalf("report=%+v trigger=%v", rep, h.trigger.projects)
	}
	if !reflect.DeepEqual(h.status.summary(), []string{"file:store_targets=blocked"}) || h.status.got[0].Issues[0].Code != "validation_error" {
		t.Errorf("status = %+v", h.status.got)
	}
}

// The runner owns entity:/metric: subjects; an upload must never write them.
func TestIngest_NeverWritesEntityOrMetricSubjects(t *testing.T) {
	m := targetMapping()
	delete(m.Spec.Fields, "value")
	for _, maps := range []fakeMappings{nil, {targetMapping()}, {m}} {
		h := newHarness([]ParsedSheet{targetSheet("")}, maps, canon(), cleanRows)
		if _, err := h.svc.Ingest(context.Background(), input()); err != nil {
			t.Fatal(err)
		}
		for _, st := range h.status.got {
			if !strings.HasPrefix(st.Subject, "file:") {
				t.Fatalf("upload wrote subject %q", st.Subject)
			}
		}
	}
}

// With the metrics layer disabled (no scheduler) uploads still store rows.
func TestIngest_NilTriggerStoresWithoutTriggering(t *testing.T) {
	h := newHarness([]ParsedSheet{targetSheet("")}, fakeMappings{targetMapping()}, canon(), cleanRows)
	h.svc.deps.Trigger = nil
	rep, err := h.svc.Ingest(context.Background(), input())
	if err != nil || rep.MetricsTriggered {
		t.Fatalf("rep=%+v err=%v", rep, err)
	}
}

func TestDatasetNames_RejectsCollisions(t *testing.T) {
	_, err := DatasetNames("t", []ParsedSheet{{Key: "a"}, {Key: "a"}})
	if !errors.Is(err, ErrInvalidParse) {
		t.Fatalf("err = %v", err)
	}
}
```

- [ ] **Step 2: Chạy test, phải FAIL**

```bash
cd ennam.kg.go && go test ./internal/intel/filedata/ -run 'TestIngest|TestDatasetNames' -count=1
```
Expected: FAIL do build `undefined: NewService`.

- [ ] **Step 3: Implement**

`ennam.kg.go/internal/intel/filedata/service.go`:
```go
package filedata

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/ennam/ennam-kg/internal/intel"
)

// Parser turns an uploaded file into typed sheets (ParserClient in production).
type Parser interface {
	Parse(ctx context.Context, filename string, body io.Reader, maxRows int) (*ParseResult, error)
}

// DatasetWriter persists and reloads datasets (Store in production).
type DatasetWriter interface {
	Write(ctx context.Context, inputs []WriteInput) ([]WriteResult, error)
	LoadRows(ctx context.Context, datasetID uuid.UUID) ([]StoredRow, error)
}

// MappingLister lists a project's mappings (*intelstore.Store).
type MappingLister interface {
	ListMappings(ctx context.Context, projectID string) ([]intel.Mapping, error)
}

// StatusSink writes data_status (*intelstore.Store — the shared writer).
type StatusSink interface {
	UpsertDataStatus(ctx context.Context, st intel.DataStatus) error
}

// ServiceDeps wires a Service. Trigger may be nil (metrics layer disabled).
type ServiceDeps struct {
	Parser    Parser
	Writer    DatasetWriter
	Mappings  MappingLister
	Canonical CanonicalSource
	Status    StatusSink
	Trigger   intel.RunTrigger
	Logger    *slog.Logger
}

// Service ingests one tabular upload end to end.
type Service struct {
	deps   ServiceDeps
	logger *slog.Logger
	now    func() time.Time
}

// NewService creates a Service.
func NewService(deps ServiceDeps) *Service {
	logger := deps.Logger
	if logger == nil {
		logger = slog.Default()
	}
	return &Service{deps: deps, logger: logger, now: time.Now}
}

// IngestInput is one tabular upload.
type IngestInput struct {
	ProjectID    uuid.UUID
	Filename     string
	Body         io.Reader
	DatasetName  string
	WriteMode    string
	SourceFileID *uuid.UUID
	UploadedBy   string
}

// DatasetReport describes one stored dataset; row numbers in its issues are
// dataset row_num values (file data row = row_num - RowOffset).
type DatasetReport struct {
	Dataset         string         `json:"dataset"`
	Sheet           string         `json:"sheet,omitempty"`
	WriteMode       string         `json:"write_mode"`
	RowsWritten     int            `json:"rows_written"`
	RowOffset       int            `json:"row_offset"`
	RowCount        int            `json:"row_count"`
	Columns         []Column       `json:"columns"`
	Validation      []EntityReport `json:"validation"`
	ValidationError string         `json:"validation_error,omitempty"`
}

// IngestReport is returned to the uploader.
type IngestReport struct {
	Datasets         []DatasetReport `json:"datasets"`
	HasIssues        bool            `json:"has_issues"`
	MetricsTriggered bool            `json:"metrics_triggered"`
	Warnings         []string        `json:"warnings,omitempty"`
}

// Ingest parses, stores (one transaction), validates and — when every mapped
// entity is usable — asks the metric scheduler for a run (after the commit).
func (s *Service) Ingest(ctx context.Context, in IngestInput) (*IngestReport, error) {
	if !identRE.MatchString(in.DatasetName) {
		return nil, fmt.Errorf("%w: dataset name %q must be lowercase letters, digits and _ and start with a letter", ErrInvalidInput, in.DatasetName)
	}
	if in.WriteMode != WriteAppend && in.WriteMode != WriteReplace {
		return nil, fmt.Errorf("%w: write mode %q (want append or replace)", ErrInvalidInput, in.WriteMode)
	}

	parsed, err := s.deps.Parser.Parse(ctx, in.Filename, in.Body, MaxDatasetRows)
	if err != nil {
		return nil, err
	}
	names, err := DatasetNames(in.DatasetName, parsed.Sheets)
	if err != nil {
		return nil, err
	}
	inputs := make([]WriteInput, len(parsed.Sheets))
	for i, sh := range parsed.Sheets {
		inputs[i] = WriteInput{ProjectID: in.ProjectID, Name: names[i], WriteMode: in.WriteMode, Columns: sh.Columns,
			Rows: sh.Rows, SourceFileID: in.SourceFileID, UploadedBy: in.UploadedBy}
	}
	written, err := s.deps.Writer.Write(ctx, inputs)
	if err != nil {
		return nil, err
	}

	report := &IngestReport{Datasets: make([]DatasetReport, len(written))}
	if w := s.renamedDatasetWarnings(ctx, in.ProjectID, in.DatasetName, names); len(w) > 0 {
		report.Warnings = w
		report.HasIssues = true
	}
	canTrigger, anyValidated := true, false
	for i, w := range written {
		dr := DatasetReport{Dataset: w.Dataset.Name, Sheet: parsed.Sheets[i].Sheet, WriteMode: in.WriteMode,
			RowsWritten: w.RowsWritten, RowOffset: w.RowOffset, RowCount: w.Dataset.RowCount,
			Columns: w.Dataset.Columns, Validation: []EntityReport{}}
		reports, verr := s.validateDataset(ctx, in.ProjectID, w.Dataset)
		dr.Validation = append(dr.Validation, reports...)
		if serr := s.deps.Status.UpsertDataStatus(ctx, s.fileStatus(in.ProjectID, w.Dataset.Name, reports, verr)); serr != nil && verr == nil {
			verr = fmt.Errorf("write data status for %s: %w", intel.FileSubject(w.Dataset.Name), serr)
		}
		if verr != nil {
			s.logger.Error("tabular validation failed", "project_id", in.ProjectID, "dataset", w.Dataset.Name, "error", verr)
			dr.ValidationError = verr.Error()
			report.HasIssues = true
			canTrigger = false
		}
		for _, rep := range reports {
			anyValidated = true
			if len(rep.Issues) > 0 {
				report.HasIssues = true
			}
			if rep.Status == intel.StatusBlocked {
				canTrigger = false
			}
		}
		report.Datasets[i] = dr
	}

	if canTrigger && anyValidated && s.deps.Trigger != nil {
		// Non-blocking (Plan B scheduler queues the run).
		s.deps.Trigger.Trigger(in.ProjectID.String())
		report.MetricsTriggered = true
	}
	return report, nil
}

// renamedDatasetWarnings flags approved file mappings that still read the name
// the user typed when this upload stored a multi-sheet workbook as
// "<name>__<sheet>" (e.g. the file gained a second data sheet): that dataset was
// NOT updated, so the mapped entity keeps serving the previous upload.
func (s *Service) renamedDatasetWarnings(ctx context.Context, projectID uuid.UUID, base string, names []string) []string {
	if len(names) == 1 && names[0] == base {
		return nil
	}
	all, err := s.deps.Mappings.ListMappings(ctx, projectID.String())
	if err != nil {
		s.logger.Warn("cannot check mappings for renamed datasets", "project_id", projectID, "error", err)
		return nil
	}
	var out []string
	for _, m := range all {
		if m.Mode == intel.ModeFile && m.FileDataset == base && m.Status == intel.MappingApproved {
			out = append(out, fmt.Sprintf(
				"entity %s reads dataset %q, but this workbook has %d data sheets and was stored as %s — %q was not updated",
				m.Entity, base, len(names), strings.Join(names, ", "), base))
		}
	}
	return out
}

func (s *Service) validateDataset(ctx context.Context, projectID uuid.UUID, ds Dataset) ([]EntityReport, error) {
	all, err := s.deps.Mappings.ListMappings(ctx, projectID.String())
	if err != nil {
		return nil, fmt.Errorf("load mappings: %w", err)
	}
	var mappings []intel.Mapping
	for _, m := range all {
		if m.Mode == intel.ModeFile && m.FileDataset == ds.Name && m.Status == intel.MappingApproved {
			mappings = append(mappings, m)
		}
	}
	if len(mappings) == 0 {
		return nil, nil
	}
	rows, err := s.deps.Writer.LoadRows(ctx, ds.ID)
	if err != nil {
		return nil, fmt.Errorf("load rows: %w", err)
	}
	reports := make([]EntityReport, 0, len(mappings))
	for _, m := range mappings {
		ent, enums, ok := s.deps.Canonical.Entity(m.Entity)
		if !ok {
			return reports, fmt.Errorf("entity %s is not defined by any loaded pack", m.Entity)
		}
		reports = append(reports, Validate(ds.Columns, rows, m, ent, enums))
	}
	return reports, nil
}

var statusRank = map[string]int{intel.StatusCurrent: 0, intel.StatusIncomplete: 1, intel.StatusBlocked: 2}

// fileStatus folds the per-entity reports of one dataset into its file:<dataset>
// row: worst status wins, every issue keeps the entity it came from.
func (s *Service) fileStatus(projectID uuid.UUID, dataset string, reports []EntityReport, verr error) intel.DataStatus {
	st := intel.DataStatus{ProjectID: projectID.String(), Subject: intel.FileSubject(dataset), Status: intel.StatusCurrent,
		Issues: []intel.Issue{}}
	for _, rep := range reports {
		if statusRank[rep.Status] > statusRank[st.Status] {
			st.Status = rep.Status
		}
		for _, is := range rep.Issues {
			st.Issues = append(st.Issues, toIntelIssue(rep.Entity, is))
		}
	}
	if verr != nil {
		st.Status = intel.StatusBlocked
		st.Issues = append(st.Issues, intel.Issue{Code: "validation_error", Message: verr.Error()})
	}
	if st.Status != intel.StatusBlocked {
		now := s.now()
		st.LastSuccessAt = &now
	}
	return st
}

func toIntelIssue(entity string, is Issue) intel.Issue {
	detail := map[string]any{"entity": entity}
	if is.Field != "" {
		detail["field"] = is.Field
	}
	if is.Column != "" {
		detail["column"] = is.Column
	}
	if len(is.Rows) > 0 {
		detail["rows"] = is.Rows
	}
	if is.Count > 0 {
		detail["count"] = is.Count
	}
	if len(is.Values) > 0 {
		detail["values"] = is.Values
	}
	return intel.Issue{Code: is.Code, Message: is.Message, Detail: detail}
}

// DatasetNames maps sheets to dataset names: one sheet keeps the name the user
// typed; a workbook with several data sheets gets "<name>__<sheet key>".
func DatasetNames(base string, sheets []ParsedSheet) ([]string, error) {
	if len(sheets) == 1 {
		return []string{base}, nil
	}
	names := make([]string, len(sheets))
	seen := make(map[string]bool, len(sheets))
	for i, sh := range sheets {
		name := base + "__" + sh.Key
		if sh.Key == "" || !datasetNameRE.MatchString(name) || seen[name] {
			return nil, fmt.Errorf("%w: cannot name dataset for sheet %q", ErrInvalidParse, sh.Sheet)
		}
		seen[name] = true
		names[i] = name
	}
	return names, nil
}
```

- [ ] **Step 4: Chạy test, phải PASS**

```bash
cd ennam.kg.go && go test ./internal/intel/filedata/ -run 'TestIngest|TestDatasetNames' -count=1 -race -v | grep -E -- '--- (PASS|FAIL)|^ok|^FAIL'
```
Expected: 12 `--- PASS`, `ok`.

- [ ] **Step 5: Kiểm tra từ ngữ ngành trong core**

```bash
./scripts/check-core-vocabulary.sh
```
Expected: `core vocabulary OK`. (Fixture test có `PH-001` nhưng không có từ bị cấm, và chỉ nằm trong `_test.go`/`testdata`.)

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.go add internal/intel/filedata/service.go internal/intel/filedata/service_test.go
git -C ennam.kg.go commit -m "feat(filedata): ingest service with validation report, shared data_status and run trigger"
```

---

### Task 10: Go — nhánh `tabular` trong upload service + handler + wiring

**Files:**
- Modify: `ennam.kg.go/internal/service/file_upload.go`
- Modify: `ennam.kg.go/internal/handler/ingest_upload.go`
- Modify: `ennam.kg.go/cmd/kg-server/main.go`
- Test: `ennam.kg.go/internal/service/file_upload_tabular_test.go`, `ennam.kg.go/internal/handler/ingest_upload_tabular_test.go`

**Interfaces:**
- Consumes: `filedata.Service.Ingest` (Task 9). Từ Plan B (Task 12): `buildIntel(db, dsStore, syncSvc, encKey, roleResolver, logger) (*handler.IntelMetricsHandler, *engine.Scheduler)` trong `cmd/kg-server/intel_wiring.go` (biến `reg *intel.Registry`, `st *intelstore.Store`, map `resolvers`, `sched *engine.Scheduler` bên trong), lời gọi trong `buildRouter` của `main.go` (biến `intelScheduler`); `sqlexec.New(db, 30*time.Second)`.
- Sửa chữ ký (Plan C sở hữu phần đăng ký `intel.ModeFile`): `buildIntel(…, tabularParser filedata.Parser) (*handler.IntelMetricsHandler, *engine.Scheduler, *filedata.Service)`.
- Produces:
  - `service.IngestModeDocument = "document"`, `service.IngestModeTabular = "tabular"`
  - `service.ErrTabularOptions`, `service.ErrTabularUnavailable`
  - `UploadOptions{…, IngestMode, DatasetName, WriteMode string}`
  - `UploadResult{Mode string "mode"; DraftID string "draft_id,omitempty"; UploadID; Status; Tabular *filedata.IngestReport "tabular,omitempty"}`. Tài liệu vẫn có `draft_id`, thêm `mode:"document"`. Bảng có `status ∈ {ingested, ingested_with_issues}`.
  - `func (s *FileUploadService) SetTabularIngester(t tabularIngester)`
  - `func (h *IngestUploadHandler) SetRoleResolver(fn ProjectRoleResolverFunc)`
  - HTTP status:
    - 201 khi thành công.
    - 400: lựa chọn sai, nhiều file, đuôi file sai.
    - 403: không có quyền project.
    - 409: cột khác dataset cũ.
    - 413: vượt giới hạn dòng.
    - 422: parser từ chối (message chứa code).
    - 503: parser hoặc tabular chưa sẵn sàng.

- [ ] **Step 1: Viết test service thất bại**

`ennam.kg.go/internal/service/file_upload_tabular_test.go`:
```go
package service

import (
	"context"
	"errors"
	"mime/multipart"
	"testing"

	"github.com/google/uuid"

	"github.com/ennam/ennam-kg/internal/intel/filedata"
	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/storage"
)

const tabularProjectID = "4ad7a5fa-a036-4f6a-8229-39a20af23e38"

type uuidUploadStore struct {
	mockUploadedFileStore
	softDeleted bool
}

func (m *uuidUploadStore) Create(ctx context.Context, f *models.UploadedFile) error {
	if err := m.mockUploadedFileStore.Create(ctx, f); err != nil {
		return err
	}
	f.ID = "9b2f0c7e-1d1a-4c55-9e39-0d6f3f0c1a01"
	return nil
}

func (m *uuidUploadStore) SoftDelete(context.Context, string, string) error {
	m.softDeleted = true
	return nil
}

type countingDraftIngest struct{ calls int }

func (c *countingDraftIngest) UpsertFromIngestion(_ context.Context, d *models.DraftNode, _ IngestUpsertOptions) (*models.DraftNode, error) {
	c.calls++
	d.ID = "draft-1"
	return d, nil
}

type fakeTabular struct {
	got    filedata.IngestInput
	calls  int
	err    error
	report *filedata.IngestReport
}

func (f *fakeTabular) Ingest(_ context.Context, in filedata.IngestInput) (*filedata.IngestReport, error) {
	f.calls++
	f.got = in
	if f.err != nil {
		return nil, f.err
	}
	return f.report, nil
}

func newTabularSvc(t *testing.T, uploads *uuidUploadStore, drafts *countingDraftIngest, tab *fakeTabular) (*FileUploadService, storage.ObjectStorage) {
	t.Helper()
	objs := storage.NewLocalStorage(t.TempDir())
	svc := NewFileUploadService(uploads, &mockDraftContentStore2{}, drafts, &mockExtractPublisher{}, nil, objs, nil)
	if tab != nil {
		svc.SetTabularIngester(tab)
	}
	return svc, objs
}

func tabularOpts() UploadOptions {
	return UploadOptions{IngestMode: IngestModeTabular, DatasetName: "store_targets", WriteMode: "replace", UploadedBy: "u-1"}
}

func TestHandleUpload_TabularSkipsDraftAndCallsIngester(t *testing.T) {
	uploads := &uuidUploadStore{}
	drafts := &countingDraftIngest{}
	tab := &fakeTabular{report: &filedata.IngestReport{Datasets: []filedata.DatasetReport{{Dataset: "store_targets"}}}}
	svc, _ := newTabularSvc(t, uploads, drafts, tab)

	res, err := svc.HandleUpload(context.Background(), tabularProjectID,
		[]*multipart.FileHeader{buildMemoryFileHeader(t, "targets.xlsx", []byte("PK..."))}, tabularOpts())
	if err != nil {
		t.Fatal(err)
	}
	if drafts.calls != 0 {
		t.Fatalf("tabular upload must not create a document draft (calls=%d)", drafts.calls)
	}
	if len(res) != 1 || res[0].Mode != IngestModeTabular || res[0].DraftID != "" || res[0].Tabular == nil || res[0].Status != "ingested" {
		t.Fatalf("result = %+v", res)
	}
	if tab.got.DatasetName != "store_targets" || tab.got.WriteMode != "replace" || tab.got.Filename != "targets.xlsx" {
		t.Errorf("ingest input = %+v", tab.got)
	}
	if tab.got.ProjectID != uuid.MustParse(tabularProjectID) || tab.got.SourceFileID == nil || tab.got.SourceFileID.String() != "9b2f0c7e-1d1a-4c55-9e39-0d6f3f0c1a01" {
		t.Errorf("ids = %v / %v", tab.got.ProjectID, tab.got.SourceFileID)
	}
	if uploads.created == nil || uploads.created.OriginalFilename != "targets.xlsx" {
		t.Errorf("the original file must still be kept as an upload record")
	}
}

func TestHandleUpload_TabularWithIssuesHasDistinctStatus(t *testing.T) {
	tab := &fakeTabular{report: &filedata.IngestReport{HasIssues: true}}
	svc, _ := newTabularSvc(t, &uuidUploadStore{}, &countingDraftIngest{}, tab)
	res, err := svc.HandleUpload(context.Background(), tabularProjectID,
		[]*multipart.FileHeader{buildMemoryFileHeader(t, "t.csv", []byte("a\n1\n"))}, tabularOpts())
	if err != nil || res[0].Status != "ingested_with_issues" {
		t.Fatalf("res=%+v err=%v", res, err)
	}
}

func TestHandleUpload_TabularRequiresExactlyOneFile(t *testing.T) {
	tab := &fakeTabular{}
	svc, _ := newTabularSvc(t, &uuidUploadStore{}, &countingDraftIngest{}, tab)
	_, err := svc.HandleUpload(context.Background(), tabularProjectID, []*multipart.FileHeader{
		buildMemoryFileHeader(t, "a.csv", []byte("a\n1\n")),
		buildMemoryFileHeader(t, "b.csv", []byte("a\n1\n")),
	}, tabularOpts())
	if !errors.Is(err, ErrTabularOptions) || tab.calls != 0 {
		t.Fatalf("err=%v calls=%d", err, tab.calls)
	}
}

func TestHandleUpload_TabularIngestFailureRemovesTheStoredFile(t *testing.T) {
	uploads := &uuidUploadStore{}
	tab := &fakeTabular{err: &filedata.ParseError{Code: "no_data", Message: "empty"}}
	svc, objs := newTabularSvc(t, uploads, &countingDraftIngest{}, tab)

	_, err := svc.HandleUpload(context.Background(), tabularProjectID,
		[]*multipart.FileHeader{buildMemoryFileHeader(t, "t.csv", []byte("a\n"))}, tabularOpts())

	var pe *filedata.ParseError
	if !errors.As(err, &pe) {
		t.Fatalf("err = %v", err)
	}
	if !uploads.softDeleted {
		t.Error("upload record must be soft-deleted when ingest fails")
	}
	if _, oerr := objs.Open(context.Background(), uploads.created.StoredPath); !errors.Is(oerr, storage.ErrNotFound) {
		t.Errorf("stored object must be removed, open err = %v", oerr)
	}
}

func TestHandleUpload_TabularRejectsNonTableExtensions(t *testing.T) {
	svc, _ := newTabularSvc(t, &uuidUploadStore{}, &countingDraftIngest{}, &fakeTabular{})
	_, err := svc.HandleUpload(context.Background(), tabularProjectID,
		[]*multipart.FileHeader{buildMemoryFileHeader(t, "report.pdf", []byte("%PDF"))}, tabularOpts())
	if !errors.Is(err, ErrUnsupportedFileType) {
		t.Fatalf("err = %v", err)
	}
}

func TestHandleUpload_UnknownIngestModeIsRejected(t *testing.T) {
	svc, _ := newTabularSvc(t, &uuidUploadStore{}, &countingDraftIngest{}, &fakeTabular{})
	opts := tabularOpts()
	opts.IngestMode = "spreadsheet"
	_, err := svc.HandleUpload(context.Background(), tabularProjectID,
		[]*multipart.FileHeader{buildMemoryFileHeader(t, "t.csv", []byte("a\n1\n"))}, opts)
	if !errors.Is(err, ErrTabularOptions) {
		t.Fatalf("err = %v", err)
	}
}

func TestHandleUpload_TabularWithoutIngesterIsUnavailable(t *testing.T) {
	svc, _ := newTabularSvc(t, &uuidUploadStore{}, &countingDraftIngest{}, nil)
	_, err := svc.HandleUpload(context.Background(), tabularProjectID,
		[]*multipart.FileHeader{buildMemoryFileHeader(t, "t.csv", []byte("a\n1\n"))}, tabularOpts())
	if !errors.Is(err, ErrTabularUnavailable) {
		t.Fatalf("err = %v", err)
	}
}

// The document path is unchanged: .xls is still refused there (files.py cannot
// extract it), and a plain upload still creates a draft and reports mode=document.
func TestHandleUpload_DocumentPathUnchanged(t *testing.T) {
	drafts := &countingDraftIngest{}
	svc, _ := newTabularSvc(t, &uuidUploadStore{}, drafts, &fakeTabular{})
	if _, err := svc.HandleUpload(context.Background(), tabularProjectID,
		[]*multipart.FileHeader{buildMemoryFileHeader(t, "old.xls", []byte("x"))}, UploadOptions{}); !errors.Is(err, ErrUnsupportedFileType) {
		t.Fatalf(".xls as document: err = %v", err)
	}
	res, err := svc.HandleUpload(context.Background(), tabularProjectID,
		[]*multipart.FileHeader{buildMemoryFileHeader(t, "notes.csv", []byte("a\n1\n"))}, UploadOptions{})
	if err != nil || drafts.calls != 1 || res[0].Mode != IngestModeDocument || res[0].DraftID != "draft-1" {
		t.Fatalf("res=%+v err=%v drafts=%d", res, err, drafts.calls)
	}
}
```

- [ ] **Step 2: Chạy test, phải FAIL**

```bash
cd ennam.kg.go && go test ./internal/service/ -run 'TestHandleUpload_' -count=1
```
Expected: FAIL do build `undefined: IngestModeTabular`, `unknown field IngestMode`…

- [ ] **Step 3: Sửa `internal/service/file_upload.go`**

3a. Thêm import (khối import hiện có):
```go
	"github.com/google/uuid"

	"github.com/ennam/ennam-kg/internal/intel/filedata"
```

3b. Ngay sau khối `var ( ErrUploadTooLarge … )` thêm:
```go
// Ingest modes chosen in Knowledge Sources ("Tài liệu" / "Dữ liệu bảng").
const (
	IngestModeDocument = "document"
	IngestModeTabular  = "tabular"
)

var (
	ErrTabularOptions     = errors.New("invalid tabular upload options")
	ErrTabularUnavailable = errors.New("tabular upload is not configured")
)

// tabularIngester stores a table upload as datasets (filedata.Service).
type tabularIngester interface {
	Ingest(ctx context.Context, in filedata.IngestInput) (*filedata.IngestReport, error)
}
```

3c. Thay struct `UploadResult` bằng:
```go
// UploadResult is returned for each successfully ingested file. Document
// uploads carry DraftID; tabular uploads carry the dataset/validation report.
type UploadResult struct {
	Mode     string                 `json:"mode"`
	DraftID  string                 `json:"draft_id,omitempty"`
	UploadID string                 `json:"upload_id"`
	Status   string                 `json:"status"`
	Tabular  *filedata.IngestReport `json:"tabular,omitempty"`
}
```

3d. Trong struct `FileUploadService` thêm field cuối `tabular tabularIngester` và thêm method ngay sau `NewFileUploadService`:
```go
// SetTabularIngester enables the "Dữ liệu bảng" branch.
func (s *FileUploadService) SetTabularIngester(t tabularIngester) {
	s.tabular = t
}
```

3e. `UploadOptions` thêm 3 field:
```go
	IngestMode  string
	DatasetName string
	WriteMode   string
```

3f. Trong `HandleUpload`, ngay sau khối `if len(files) > maxFilesPerUploadRequest { … }` thêm:
```go
	mode := strings.TrimSpace(opts.IngestMode)
	if mode == "" {
		mode = IngestModeDocument
	}
	if mode != IngestModeDocument && mode != IngestModeTabular {
		return nil, fmt.Errorf("%w: unknown ingest_mode %q", ErrTabularOptions, mode)
	}
	if mode == IngestModeTabular && len(files) != 1 {
		return nil, fmt.Errorf("%w: upload exactly one file as table data (got %d)", ErrTabularOptions, len(files))
	}
```
và thay vòng lặp cuối:
```go
	if mode == IngestModeTabular {
		result, err := s.handleTabularFile(ctx, projectID, files[0], opts, maxFileBytes)
		if err != nil {
			return nil, err
		}
		return []UploadResult{*result}, nil
	}

	results := make([]UploadResult, 0, len(files))
	for _, fh := range files {
		result, err := s.handleOneFile(ctx, projectID, fh, opts, maxFileBytes, settings.RequireUploadApproval)
		if err != nil {
			return results, err
		}
		results = append(results, *result)
	}
	return results, nil
```

3g. Trong `handleOneFile`, câu `return &UploadResult{…}` thêm `Mode: IngestModeDocument,`:
```go
	return &UploadResult{
		Mode:     IngestModeDocument,
		DraftID:  ingested.ID,
		UploadID: upload.ID,
		Status:   string(ingested.Status),
	}, nil
```

3h. Thêm sau `handleOneFile`:
```go
// handleTabularFile stores the original file for audit, then ingests it as
// table rows. No document draft is created. Parsing happens in the Python
// indexer (filedata.ParserClient); Go never extracts content itself (NFR-242).
func (s *FileUploadService) handleTabularFile(
	ctx context.Context,
	projectID string,
	fh *multipart.FileHeader,
	opts UploadOptions,
	maxFileBytes int64,
) (*UploadResult, error) {
	if s.tabular == nil {
		return nil, ErrTabularUnavailable
	}
	ext := strings.ToLower(filepath.Ext(fh.Filename))
	if !isTabularExt(ext) {
		return nil, fmt.Errorf("%w: %s (table data accepts .csv, .xlsx, .xls)", ErrUnsupportedFileType, ext)
	}
	pid, err := uuid.Parse(projectID)
	if err != nil {
		return nil, fmt.Errorf("%w: project id %q is not a UUID", ErrTabularOptions, projectID)
	}

	upload, err := s.storeTabularObject(ctx, projectID, fh, ext, opts.UploadedBy, maxFileBytes)
	if err != nil {
		return nil, err
	}
	var sourceFileID *uuid.UUID
	if id, perr := uuid.Parse(upload.ID); perr == nil {
		sourceFileID = &id
	}

	body, err := fh.Open()
	if err != nil {
		s.discardTabularUpload(ctx, projectID, upload)
		return nil, fmt.Errorf("open upload file: %w", err)
	}
	defer body.Close()

	report, err := s.tabular.Ingest(ctx, filedata.IngestInput{
		ProjectID:    pid,
		Filename:     fh.Filename,
		Body:         body,
		DatasetName:  strings.TrimSpace(opts.DatasetName),
		WriteMode:    strings.TrimSpace(opts.WriteMode),
		SourceFileID: sourceFileID,
		UploadedBy:   opts.UploadedBy,
	})
	if err != nil {
		s.discardTabularUpload(ctx, projectID, upload)
		return nil, err
	}
	if err := s.uploads.MarkContentExtracted(ctx, projectID, upload.ID); err != nil {
		s.logger.Warn("failed to mark tabular upload extracted", "upload_id", upload.ID, "error", err)
	}

	status := "ingested"
	if report.HasIssues {
		status = "ingested_with_issues"
	}
	return &UploadResult{Mode: IngestModeTabular, UploadID: upload.ID, Status: status, Tabular: report}, nil
}

// storeTabularObject keeps the original file (ObjectStorage + uploaded_files).
func (s *FileUploadService) storeTabularObject(
	ctx context.Context,
	projectID string,
	fh *multipart.FileHeader,
	ext, uploadedBy string,
	maxFileBytes int64,
) (*models.UploadedFile, error) {
	uploadID, err := newUUID()
	if err != nil {
		return nil, err
	}
	relPath := path.Join(projectID, uploadID, sanitizeFilename(fh.Filename))
	src, err := fh.Open()
	if err != nil {
		return nil, fmt.Errorf("open upload file: %w", err)
	}
	defer src.Close()

	mimeType := fh.Header.Get("Content-Type")
	if mimeType == "" {
		mimeType = mimeTypeForExt(ext)
	}
	counter := &countingReader{r: io.LimitReader(src, maxFileBytes+1)}
	if err := s.objects.Put(ctx, relPath, counter, mimeType); err != nil {
		return nil, fmt.Errorf("store upload file: %w", err)
	}
	if counter.n > maxFileBytes {
		s.deleteObject(ctx, relPath)
		return nil, fmt.Errorf("%w: %s", ErrUploadTooLarge, fh.Filename)
	}
	upload := &models.UploadedFile{
		ProjectID:        projectID,
		OriginalFilename: fh.Filename,
		StoredPath:       relPath,
		MimeType:         stringPtr(mimeType),
		FileSizeBytes:    counter.n,
		UploadedBy:       uploadedBy,
	}
	if err := s.uploads.Create(ctx, upload); err != nil {
		s.deleteObject(ctx, relPath)
		return nil, fmt.Errorf("create upload record: %w", err)
	}
	return upload, nil
}

func (s *FileUploadService) discardTabularUpload(ctx context.Context, projectID string, upload *models.UploadedFile) {
	if err := s.uploads.SoftDelete(ctx, projectID, upload.ID); err != nil {
		s.logger.Warn("failed to soft-delete tabular upload", "upload_id", upload.ID, "error", err)
	}
	s.deleteObject(ctx, upload.StoredPath)
}

func isTabularExt(ext string) bool {
	switch ext {
	case ".csv", ".xlsx", ".xls":
		return true
	}
	return false
}
```

3i. Trong `mimeTypeForExt` thêm case (nhánh tài liệu không bao giờ tới đây với `.xls` vì `classifyUploadFile` đã từ chối trước):
```go
	case ".xls":
		return "application/vnd.ms-excel"
```

**Không** sửa `classifyUploadFile` (NFR-242 + `TestClassifyUploadFile_AllFormatsDeferExtract`).

- [ ] **Step 4: Chạy test service, phải PASS (kể cả test cũ)**

```bash
cd ennam.kg.go && go test ./internal/service/ -run 'TestHandleUpload_|TestClassifyUploadFile|TestFileUpload' -count=1 -race -v | grep -E -- '--- (PASS|FAIL)|^ok|^FAIL'
```
Expected: mọi `--- PASS`, `ok`.

- [ ] **Step 5: Viết test handler thất bại**

`ennam.kg.go/internal/handler/ingest_upload_tabular_test.go`:
```go
package handler

import (
	"bytes"
	"context"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/intel/filedata"
	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/service"
	"github.com/ennam/ennam-kg/internal/storage"
)

const tabProject = "4ad7a5fa-a036-4f6a-8229-39a20af23e38"

type tabUploadStore struct{ uploadsOnlyStore }

func (s *tabUploadStore) Create(_ context.Context, f *models.UploadedFile) error {
	f.ID = "9b2f0c7e-1d1a-4c55-9e39-0d6f3f0c1a01"
	return nil
}

type noDrafts struct{ calls int }

func (n *noDrafts) UpsertFromIngestion(_ context.Context, d *models.DraftNode, _ service.IngestUpsertOptions) (*models.DraftNode, error) {
	n.calls++
	d.ID = "draft-x"
	return d, nil
}

type stubTabular struct {
	got filedata.IngestInput
	err error
}

func (s *stubTabular) Ingest(_ context.Context, in filedata.IngestInput) (*filedata.IngestReport, error) {
	s.got = in
	if s.err != nil {
		return nil, s.err
	}
	return &filedata.IngestReport{Datasets: []filedata.DatasetReport{{Dataset: in.DatasetName, RowsWritten: 1}}}, nil
}

func tabularMux(t *testing.T, tab *stubTabular, drafts *noDrafts, resolver ...ProjectRoleResolverFunc) *http.ServeMux {
	t.Helper()
	svc := service.NewFileUploadService(&tabUploadStore{}, nil, drafts, nil, nil, storage.NewLocalStorage(t.TempDir()), nil)
	svc.SetTabularIngester(tab)
	h := NewIngestUploadHandler(svc, nil)
	if len(resolver) > 0 {
		h.SetRoleResolver(resolver[0])
	}
	mux := http.NewServeMux()
	h.RegisterRoutes(mux)
	return mux
}

// withWebUser gives the request a web-login session: a developer key with no
// project scope plus a Phase 3 user (membership decides access).
func withWebUser(r *http.Request, userID string) *http.Request {
	ctx := context.WithValue(r.Context(), middleware.DeveloperIdentityKey,
		&middleware.DeveloperIdentity{Role: models.APIKeyRoleDeveloper, ProjectIDs: []string{}})
	ctx = context.WithValue(ctx, middleware.UserIdentityKey, &middleware.UserIdentity{UserID: userID})
	return r.WithContext(ctx)
}

func memberAs(role models.ProjectMemberRole) ProjectRoleResolverFunc {
	return func(_ context.Context, projectID, _ string) (models.ProjectMemberRole, bool) {
		return role, projectID == tabProject
	}
}

func tabularRequest(t *testing.T, fields map[string]string, files ...string) *http.Request {
	t.Helper()
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	for k, v := range fields {
		_ = mw.WriteField(k, v)
	}
	for _, name := range files {
		fw, err := mw.CreateFormFile("file", name)
		if err != nil {
			t.Fatal(err)
		}
		_, _ = fw.Write([]byte("Store,Target\nA,1\n"))
	}
	_ = mw.Close()
	r := httptest.NewRequest(http.MethodPost, "/api/v1/projects/"+tabProject+"/ingest/upload", &buf)
	r.Header.Set("Content-Type", mw.FormDataContentType())
	return r
}

var tabFields = map[string]string{"ingest_mode": "tabular", "dataset_name": "store_targets", "write_mode": "replace"}

func TestUpload_TabularReturnsReportWithoutDraft(t *testing.T) {
	tab := &stubTabular{}
	drafts := &noDrafts{}
	rec := httptest.NewRecorder()
	tabularMux(t, tab, drafts).ServeHTTP(rec, tabularRequest(t, tabFields, "targets.csv"))

	if rec.Code != http.StatusCreated {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	var body map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &body)
	if body["mode"] != "tabular" || body["tabular"] == nil {
		t.Fatalf("body = %v", body)
	}
	if _, has := body["draft_id"]; has || drafts.calls != 0 {
		t.Fatalf("tabular upload must not create a draft: body=%v calls=%d", body, drafts.calls)
	}
	if tab.got.DatasetName != "store_targets" || tab.got.WriteMode != "replace" {
		t.Errorf("ingest got %+v", tab.got)
	}
}

func TestUpload_TabularTwoFilesIs400(t *testing.T) {
	rec := httptest.NewRecorder()
	tabularMux(t, &stubTabular{}, &noDrafts{}).ServeHTTP(rec, tabularRequest(t, tabFields, "a.csv", "b.csv"))
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status=%d", rec.Code)
	}
}

func TestUpload_TabularInvalidDatasetNameIs400(t *testing.T) {
	tab := &stubTabular{err: filedata.ErrInvalidInput}
	rec := httptest.NewRecorder()
	tabularMux(t, tab, &noDrafts{}).ServeHTTP(rec, tabularRequest(t, map[string]string{
		"ingest_mode": "tabular", "dataset_name": "Store Targets", "write_mode": "replace"}, "a.csv"))
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status=%d", rec.Code)
	}
}

func TestUpload_TabularParseErrorIs422WithCode(t *testing.T) {
	tab := &stubTabular{err: &filedata.ParseError{Code: "encoding", Message: "CSV files must be UTF-8 encoded"}}
	rec := httptest.NewRecorder()
	tabularMux(t, tab, &noDrafts{}).ServeHTTP(rec, tabularRequest(t, tabFields, "a.csv"))
	if rec.Code != http.StatusUnprocessableEntity || !strings.Contains(rec.Body.String(), "encoding") {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestHandleUpload_TabularRowCapIs413(t *testing.T) {
	tab := &stubTabular{err: &filedata.ParseError{Code: "row_cap_exceeded", Message: "too many rows"}}
	rec := httptest.NewRecorder()
	tabularMux(t, tab, &noDrafts{}).ServeHTTP(rec, tabularRequest(t, tabFields, "a.csv"))
	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("status=%d", rec.Code)
	}
}

func TestUpload_TabularColumnConflictIs409(t *testing.T) {
	tab := &stubTabular{err: filedata.ErrColumnConflict}
	rec := httptest.NewRecorder()
	tabularMux(t, tab, &noDrafts{}).ServeHTTP(rec, tabularRequest(t, tabFields, "a.csv"))
	if rec.Code != http.StatusConflict {
		t.Fatalf("status=%d", rec.Code)
	}
}

// Review focus 5: the ProjectID middleware only checks header/query project ids,
// not the path; rows written here feed metrics, so the branch checks the path.
func TestUpload_TabularDeniedForProjectOutsideKeyScope(t *testing.T) {
	tab := &stubTabular{}
	r := tabularRequest(t, tabFields, "a.csv")
	r = r.WithContext(context.WithValue(r.Context(), middleware.DeveloperIdentityKey,
		&middleware.DeveloperIdentity{Role: models.APIKeyRoleDeveloper, ProjectIDs: []string{"another-project"}}))
	rec := httptest.NewRecorder()
	tabularMux(t, tab, &noDrafts{}).ServeHTTP(rec, r)
	if rec.Code != http.StatusForbidden || tab.got.DatasetName != "" {
		t.Fatalf("status=%d ingestCalled=%v", rec.Code, tab.got.DatasetName != "")
	}
}

// A viewer is a member (requireProjectAccess lets them through) but must not
// write: neither table rows nor documents.
func TestUpload_ViewerCannotUpload(t *testing.T) {
	tab := &stubTabular{}
	drafts := &noDrafts{}
	for _, fields := range []map[string]string{tabFields, {}} {
		rec := httptest.NewRecorder()
		tabularMux(t, tab, drafts, memberAs(models.ProjectMemberRoleViewer)).
			ServeHTTP(rec, withWebUser(tabularRequest(t, fields, "a.csv"), "u-1"))
		if rec.Code != http.StatusForbidden {
			t.Fatalf("fields=%v status=%d, want 403", fields, rec.Code)
		}
	}
	if tab.got.DatasetName != "" || drafts.calls != 0 {
		t.Fatalf("nothing may be written: ingest=%q drafts=%d", tab.got.DatasetName, drafts.calls)
	}
}

func TestUpload_DeveloperMemberCanUploadTable(t *testing.T) {
	tab := &stubTabular{}
	rec := httptest.NewRecorder()
	tabularMux(t, tab, &noDrafts{}, memberAs(models.ProjectMemberRoleDeveloper)).
		ServeHTTP(rec, withWebUser(tabularRequest(t, tabFields, "a.csv"), "u-1"))
	if rec.Code != http.StatusCreated || tab.got.DatasetName != "store_targets" {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
}
```

- [ ] **Step 6: Chạy test handler, phải FAIL**

```bash
cd ennam.kg.go && go test ./internal/handler/ -run 'TestUpload_Tabular|TestHandleUpload_TabularRowCapIs413' -count=1
```
Expected: FAIL ở bước build: `h.SetRoleResolver undefined (type *IngestUploadHandler has no field or method SetRoleResolver)`. (Nếu tạm thêm `SetRoleResolver` để xem lỗi hành vi: handler chưa đọc `ingest_mode` nên mọi request đi nhánh tài liệu và trả **201** kèm `draft_id`. `TestUpload_TabularReturnsReportWithoutDraft` đỏ vì `mode=document`; `TwoFilesIs400`, `DeniedForProjectOutsideKeyScope` và `ViewerCannotUpload` đều nhận 201 thay vì 400/403.)

- [ ] **Step 7: Sửa `internal/handler/ingest_upload.go`**

7a. Import thêm `"context"`, `"time"`, `"github.com/ennam/ennam-kg/internal/intel/filedata"` và `"github.com/ennam/ennam-kg/internal/models"`.

7b. Thêm hằng số và field:
```go
// tabularWriteDeadline replaces the server-wide write timeout (10s in
// production) for "Dữ liệu bảng" uploads only: the whole sheet is parsed and
// stored inside the request so the validation report comes back with it.
const tabularWriteDeadline = 3 * time.Minute
```
```go
type IngestUploadHandler struct {
	svc          *service.FileUploadService
	logger       *slog.Logger
	roleResolver ProjectRoleResolverFunc
}

// SetRoleResolver wires the project_members lookup used by requireProjectAccess / requireProjectRole.
func (h *IngestUploadHandler) SetRoleResolver(fn ProjectRoleResolverFunc) { h.roleResolver = fn }
```

7c. Trong `Upload`, **ngay sau** khối kiểm tra `projectID == ""` và **trước** `r.ParseMultipartForm(...)` (kiểm quyền trước khi đọc body) thêm:
```go
	// Every upload writes into the path project. The ProjectID middleware only
	// checks header/query ids, so check access AND a writer role here, before the
	// body is read — like the other write handlers (decision.go, task.go).
	if !requireProjectAccess(w, r, h.roleResolver, projectID) {
		return
	}
	if !requireProjectRole(w, r, projectID, models.ProjectMemberRoleDeveloper, h.roleResolver) {
		return
	}
```
Khối này áp dụng cho **mọi** upload, kể cả "Tài liệu". Không thể chỉ kiểm nhánh bảng trước `ParseMultipartForm`, vì `ingest_mode` nằm trong form. Hệ quả: lỗ IDOR có từ trước ở nhánh tài liệu được đóng luôn, và viewer không còn upload được tài liệu (đúng ý nghĩa role). Legacy API key không có UserIdentity vẫn đi qua như các handler ghi khác.

Sau khối `files := collectUploadFiles(r) …` và trước `uploader := …` thêm:
```go
	ctx := r.Context()
	ingestMode := strings.TrimSpace(r.FormValue("ingest_mode"))
	if ingestMode == service.IngestModeTabular {
		if err := http.NewResponseController(w).SetWriteDeadline(time.Now().Add(tabularWriteDeadline)); err != nil {
			h.logger.Warn("could not extend write deadline for tabular upload", "error", err)
		}
		// Finish or roll back before the response deadline: a commit must never land
		// after the client has been cut off without seeing the result.
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, tabularWriteDeadline-15*time.Second)
		defer cancel()
	}
```
đổi lời gọi `h.svc.HandleUpload(r.Context(), …)` thành `h.svc.HandleUpload(ctx, …)`, và truyền thêm vào `service.UploadOptions{…}`:
```go
		IngestMode:         ingestMode,
		DatasetName:        r.FormValue("dataset_name"),
		WriteMode:          r.FormValue("write_mode"),
```

7d. Thay `handleUploadError` bằng:
```go
func (h *IngestUploadHandler) handleUploadError(w http.ResponseWriter, err error) {
	var parseErr *filedata.ParseError
	switch {
	case errors.Is(err, service.ErrUploadTooLarge):
		errorResponse(w, http.StatusRequestEntityTooLarge, err.Error())
	case errors.Is(err, service.ErrUploadQuotaExceeded):
		errorResponse(w, http.StatusRequestEntityTooLarge, err.Error())
	case errors.Is(err, service.ErrUnsupportedFileType),
		errors.Is(err, service.ErrTooManyUploadFiles),
		errors.Is(err, service.ErrTabularOptions),
		errors.Is(err, filedata.ErrInvalidInput):
		errorResponse(w, http.StatusBadRequest, err.Error())
	case errors.Is(err, filedata.ErrRowCapExceeded):
		errorResponse(w, http.StatusRequestEntityTooLarge, err.Error())
	case errors.Is(err, filedata.ErrColumnConflict):
		errorResponse(w, http.StatusConflict, err.Error())
	case errors.As(err, &parseErr):
		errorResponse(w, http.StatusUnprocessableEntity, parseErr.Code+": "+parseErr.Message)
	case errors.Is(err, service.ErrTabularUnavailable),
		errors.Is(err, filedata.ErrParserUnavailable),
		errors.Is(err, filedata.ErrInvalidParse):
		h.logger.Error("tabular upload unavailable", "error", err)
		errorResponse(w, http.StatusServiceUnavailable, "table upload is temporarily unavailable")
	default:
		h.logger.Error("upload failed", "error", err)
		errorResponse(w, http.StatusInternalServerError, "upload failed")
	}
}
```
(Thứ tự quan trọng: `ErrRowCapExceeded` đứng trước `errors.As(ParseError)` vì `ParseError{row_cap_exceeded}` khớp cả hai và phải ra 413.)

- [ ] **Step 8: Wiring — đăng ký `intel.ModeFile` trong `buildIntel` + nối service upload**

Plan B (Task 12) quy định: resolver `mode=file` đăng ký **trong** `buildIntel` (`cmd/kg-server/intel_wiring.go`), và scheduler (`intelScheduler`, là `intel.RunTrigger`) được đưa vào đường upload. Vì `buildIntel` tạo `reg` (registry pack) và `st` (`intelstore.Store`) bên trong, service upload cũng được dựng ở đó và trả ra ngoài như giá trị thứ ba.

Kiểm tra trước: `grep -rn "buildIntel(" ennam.kg.go/cmd ennam.kg.go/internal` chỉ có 1 lời gọi (trong `buildRouter`) + định nghĩa. Có thêm lời gọi khác (vd test) thì sửa luôn cho khớp chữ ký mới.

8a. `cmd/kg-server/intel_wiring.go`:
- Import thêm `"time"`, `"github.com/ennam/ennam-kg/internal/intel/filedata"`, `"github.com/ennam/ennam-kg/internal/intel/sqlexec"`.
- Đổi chữ ký:
```go
func buildIntel(db *sql.DB, dsStore *store.DataSourceStore, syncSvc *service.SchemaSyncService, encKey []byte,
	roleResolver handler.ProjectRoleResolverFunc, logger *slog.Logger,
	tabularParser filedata.Parser) (*handler.IntelMetricsHandler, *engine.Scheduler, *filedata.Service) {
```
- Hai câu `return handler.NewIntelMetricsHandler(nil, roleResolver, logger), nil` (pack không nạp được; cấu hình `METRIC_*` sai) đổi thành `…, nil, nil`. Khi lớp metrics tắt thì upload bảng trả 503 (`ErrTabularUnavailable`): không có canonical/mapping thì không validate được, và không ghi dữ liệu mà không có báo cáo.
- Ngay sau khối `if encKey != nil … resolvers[intel.ModeLive] = … } else { … }` thêm:
```go
	// Plan C: uploaded tables ("Dữ liệu bảng") are read in ennam_kg, read-only.
	fileStore := filedata.NewStore(db)
	canonical := filedata.NewRegistryCanonical(reg)
	resolvers[intel.ModeFile] = filedata.NewResolver(fileStore, sqlexec.New(db, 30*time.Second), canonical)
```
- Thay câu `return` cuối bằng:
```go
	tabularDeps := filedata.ServiceDeps{Parser: tabularParser, Writer: fileStore, Mappings: st, Canonical: canonical,
		Status: st, Logger: logger}
	if sched != nil {
		// Only a real scheduler: a typed-nil *engine.Scheduler inside the interface would panic on Trigger.
		tabularDeps.Trigger = sched
	}
	return handler.NewIntelMetricsHandler(query, roleResolver, logger), sched, filedata.NewService(tabularDeps)
```

8b. `cmd/kg-server/main.go`: thay khối Plan B đã thêm sau log related-documents
```go
	intelHandler, intelScheduler := buildIntel(db, dsStore, syncSvc, encKey, roleResolver, logger)
	intelHandler.RegisterRoutes(apiMux)
	if intelScheduler != nil {
		intelScheduler.Start(context.Background())
	}
```
bằng:
```go
	internalToken := os.Getenv("KG_INTERNAL_TOKEN") // same secret as the indexer's KG_INTERNAL_TOKEN
	if internalToken == "" {
		logger.Warn("KG_INTERNAL_TOKEN not set — table uploads will be refused by the indexer (503)")
	}
	intelHandler, intelScheduler, tabularSvc := buildIntel(db, dsStore, syncSvc, encKey, roleResolver, logger,
		filedata.NewParserClient(embPythonURL, internalToken, &http.Client{Timeout: filedata.ParseTimeout}))
	intelHandler.RegisterRoutes(apiMux)
	if intelScheduler != nil {
		intelScheduler.Start(context.Background())
	}
	// Plan C: "Dữ liệu bảng" uploads. nil when the metrics layer is disabled ⇒ table uploads answer 503.
	if tabularSvc != nil {
		uploadSvc.SetTabularIngester(tabularSvc)
	}
	uploadHandler.SetRoleResolver(roleResolver)
```
và thêm import `"github.com/ennam/ennam-kg/internal/intel/filedata"`.

Cả `uploadSvc` (`main.go:733`), `uploadHandler`, `embPythonURL` (`main.go:382`) và `roleResolver` đều nằm trong `buildRouter`, cùng hàm với lời gọi `buildIntel` (sau `main.go:1107`). Guard `tabularSvc != nil` tránh đưa typed-nil vào interface `tabularIngester`.

- [ ] **Step 9: Chạy test handler + build, phải PASS**

```bash
cd ennam.kg.go && go build ./... && go vet ./cmd/kg-server/ ./internal/handler/ ./internal/service/ ./internal/intel/... && go test ./internal/handler/ -run 'TestUpload_|TestHandleUpload_TabularRowCapIs413|TestDownload_|TestRequireProjectAccess|TestRequireProjectRole' -count=1 -race -v | grep -E -- '--- (PASS|FAIL)|^ok|^FAIL'
```
Expected: build sạch; mọi `--- PASS`; `ok`.

- [ ] **Step 10: Chạy toàn bộ test 3 package bị chạm + lint**

```bash
cd ennam.kg.go && go test ./internal/service/ ./internal/handler/ ./internal/intel/... -count=1 -race 2>&1 | tail -5 && make lint
```
Expected: 3 dòng `ok`; golangci-lint không báo lỗi mới. (Lúc viết plan, `grep -rn "UploadResult{" internal | grep _test` không tìm thấy literal nào so sánh nguyên struct. Nếu test nào đỏ vì field `Mode` mới, thêm `Mode: IngestModeDocument` vào giá trị mong đợi của test đó, không sửa code.)

- [ ] **Step 11: Xác minh `SetWriteDeadline` thật sự có tác dụng sau middleware**

`http.NewResponseController` chỉ tới được connection thật nếu **mọi** wrapper của `http.ResponseWriter` đều có `Unwrap() http.ResponseWriter`. Nếu không, hàm trả `ErrNotSupported`, handler chỉ log warning, và timeout 10s của production vẫn áp dụng. Test handler dùng `httptest.ResponseRecorder` (cũng `ErrNotSupported`) nên không bắt được trường hợp này.
```bash
cd ennam.kg.go && grep -rn "^\s*http.ResponseWriter$" internal/middleware cmd/kg-server | grep -v _test.go
grep -rn "Unwrap() http.ResponseWriter" internal/middleware
grep -rn "TimeoutHandler" internal cmd
```
Expected (đã kiểm tra lúc viết plan): wrapper duy nhất trên đường kg-server là `middleware/logging.go:13` (`responseRecorder`), có `Unwrap()` ở `logging.go:44`; không có `TimeoutHandler`. Nếu xuất hiện wrapper mới thiếu `Unwrap()`, thêm method `Unwrap() http.ResponseWriter { return x.ResponseWriter }` cho wrapper đó trong cùng commit. Nếu có `TimeoutHandler` hoặc middleware gắn deadline vào context, ghi vào Q3 (nới write deadline sẽ không đủ).

Kiểm tra thật trên stack dev: cấu hình `development.yaml` có `write_timeout: "400s"`, nên không tái hiện được 10s. Thay vào đó, chạy kg-server cục bộ với `REQUEST_TIMEOUT=2s`, upload một CSV khoảng 100.000 dòng ở chế độ tabular, và xác nhận nhận được response 201 (không bị reset kết nối).

- [ ] **Step 12: Commit**

```bash
git -C ennam.kg.go add internal/service/file_upload.go internal/service/file_upload_tabular_test.go internal/handler/ingest_upload.go internal/handler/ingest_upload_tabular_test.go cmd/kg-server/main.go cmd/kg-server/intel_wiring.go
git -C ennam.kg.go commit -m "feat(upload): route ingest_mode=tabular uploads to file datasets"
```

---

### Task 11: Kiểm chứng spec §13 — chế độ `file` ra cùng số với `live` (qua compiler thật của Plan B)

**Files:**
- Create: `ennam.kg.go/internal/intel/filedata/testdata/net_sales_metric.sql`
- Test: `ennam.kg.go/internal/intel/filedata/parity_integration_test.go`

**Interfaces:**
- Consumes (Plan B):
  - `intel.ParseMetricSQL(file, src string) (*intel.MetricDef, error)`.
  - `intel.Compiler{Dialect: intel.Postgres{}, Catalog: *intel.Catalog}` với `EntityCTE(entity string, m intel.Mapping, t intel.SourceTable, tz string) (string, error)`, `CompileMetric(def *intel.MetricDef, ctes map[string]string) (*intel.Compiled, error)`, `(*Compiled).Args(map[string]any) ([]any, error)`.
  - `livesource.Table{Schema, Name string; Cols []intel.SourceColumn}` (SourceTable của mode=live).
  - `sqlexec.New(db, timeout)`.
  - Từ Plan C: `Store`, `FileTable` (Task 6, 8); golden `testdata/sales_small.parsed.json` (= output Python của `sales_small.csv`, Task 3).
- Produces: test chứng minh cùng một metric pack (dạng `retail.net_sales`, SUM theo location × ngày), cùng mapping và cùng compiler cho **cùng** kết quả trên bảng live có kiểu gốc và trên dataset file. Kết quả cũng phải bằng đáp án tính tay: ô rỗng ⇒ NULL, và mốc 23:30 / 00:15 rơi đúng ngày.

- [ ] **Step 1: Metric SQL theo định dạng pack (header bắt buộc của master §2.2)**

`ennam.kg.go/internal/intel/filedata/testdata/net_sales_metric.sql`:
```sql
-- key: test.net_sales
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: currency
-- aggregation: additive
-- sample_size: number of sales
-- requires: [sale]
SELECT location_id,
       CAST(sold_at AS date) AS period_date,
       SUM(net_amount)       AS value,
       COUNT(*)              AS sample_size
FROM sale
WHERE sold_at >= :from AND sold_at < :to
GROUP BY 1, 2
ORDER BY 1, 2
```

- [ ] **Step 2: Viết test**

`ennam.kg.go/internal/intel/filedata/parity_integration_test.go`:
```go
package filedata

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/livesource"
	"github.com/ennam/ennam-kg/internal/intel/sqlexec"
)

type metricRow struct {
	Location string
	Day      string
	Value    string // "" = NULL
	Sample   string
}

func normalizeRows(t *testing.T, res *intel.QueryRows) []metricRow {
	t.Helper()
	out := make([]metricRow, len(res.Rows))
	for i, r := range res.Rows {
		day, ok := r[1].(time.Time)
		if !ok {
			t.Fatalf("period_date = %#v", r[1])
		}
		v := ""
		if r[2] != nil {
			v = fmt.Sprint(r[2])
		}
		out[i] = metricRow{Location: fmt.Sprint(r[0]), Day: day.Format("2006-01-02"), Value: v, Sample: fmt.Sprint(r[3])}
	}
	return out
}

// Spec §13: the same pack metric over the same data must give the same result in
// live mode (typed customer table) and file mode (uploaded CSV stored as JSONB),
// both compiled by Plan B's compiler from the same mapping.
func TestParity_FileModeMatchesLiveMode(t *testing.T) {
	db := openTestDB(t)
	ctx := context.Background()
	pid := seedProject(t, db)

	src, err := os.ReadFile("testdata/net_sales_metric.sql")
	if err != nil {
		t.Fatal(err)
	}
	def, err := intel.ParseMetricSQL("net_sales_metric.sql", string(src))
	if err != nil {
		t.Fatal(err)
	}
	comp := &intel.Compiler{Dialect: intel.Postgres{}, Catalog: &intel.Catalog{Entities: map[string]*intel.Entity{
		"sale": {Name: "sale", Fields: []intel.Field{
			{Name: "sale_id", Type: intel.TypeText, Key: true},
			{Name: "location_id", Type: intel.TypeText, Required: true},
			{Name: "sold_at", Type: intel.TypeTimestamp, Required: true},
			{Name: "net_amount", Type: intel.TypeNumeric},
		}},
	}}}
	fields := map[string]string{"sale_id": "sale_id", "location_id": "store_id", "sold_at": "sold_at", "net_amount": "net_amount"}
	exec := sqlexec.New(db, 30*time.Second)
	args := map[string]any{"from": "2026-07-01", "to": "2026-07-03"}

	run := func(m intel.Mapping, table intel.SourceTable) []metricRow {
		cte, err := comp.EntityCTE("sale", m, table, "America/Chicago")
		if err != nil {
			t.Fatalf("EntityCTE: %v", err)
		}
		compiled, err := comp.CompileMetric(def, map[string]string{"sale": cte})
		if err != nil {
			t.Fatal(err)
		}
		a, err := compiled.Args(args)
		if err != nil {
			t.Fatal(err)
		}
		res, err := exec.Query(ctx, compiled.SQL, a, 1000)
		if err != nil {
			t.Fatalf("query:\n%s\n%v", compiled.SQL, err)
		}
		return normalizeRows(t, res)
	}

	// Live side: natively typed table in a scratch schema, standing in for the customer DB.
	schema := fmt.Sprintf("pic_parity_%d", time.Now().UnixNano())
	mustExec(t, db, `CREATE SCHEMA `+schema)
	t.Cleanup(func() { _, _ = db.Exec(`DROP SCHEMA ` + schema + ` CASCADE`) })
	mustExec(t, db, `CREATE TABLE `+schema+`.sales (sale_id text, store_id text, sold_at timestamp, net_amount numeric)`)
	mustExec(t, db, `INSERT INTO `+schema+`.sales VALUES
		('S-1','PH-001','2026-07-01 09:15:00',10.50),
		('S-2','PH-001','2026-07-01 23:30:00',4.25),
		('S-3','PH-001','2026-07-02 00:15:00',7),
		('S-4','PH-002','2026-07-01 12:00:00',NULL),
		('S-5','PH-002','2026-07-02 08:00:00',20.00)`)
	liveTable := &livesource.Table{Schema: schema, Name: "sales", Cols: []intel.SourceColumn{
		{Name: "sale_id", DataType: "text"}, {Name: "store_id", DataType: "text"},
		{Name: "sold_at", DataType: "timestamp without time zone"}, {Name: "net_amount", DataType: "numeric"},
	}}
	live := run(intel.Mapping{ProjectID: pid.String(), Entity: "sale", Mode: intel.ModeLive,
		Spec: intel.MappingSpec{From: "sales", Fields: fields}}, liveTable)

	// File side: exactly what the Python parser returns for sales_small.csv.
	raw, err := os.ReadFile("testdata/sales_small.parsed.json")
	if err != nil {
		t.Fatal(err)
	}
	var parsed ParseResult
	if err := json.Unmarshal(raw, &parsed); err != nil {
		t.Fatal(err)
	}
	written, err := NewStore(db).Write(ctx, []WriteInput{{ProjectID: pid, Name: "sales_small",
		WriteMode: WriteReplace, Columns: parsed.Sheets[0].Columns, Rows: parsed.Sheets[0].Rows}})
	if err != nil {
		t.Fatal(err)
	}
	file := run(intel.Mapping{ProjectID: pid.String(), Entity: "sale", Mode: intel.ModeFile, FileDataset: "sales_small",
		Spec: intel.MappingSpec{Fields: fields}}, NewFileTable(written[0].Dataset))

	want := []metricRow{
		{"PH-001", "2026-07-01", "14.75", "2"},
		{"PH-001", "2026-07-02", "7", "1"},
		{"PH-002", "2026-07-01", "", "1"},
		{"PH-002", "2026-07-02", "20.00", "1"},
	}
	if !reflect.DeepEqual(live, want) {
		t.Fatalf("live = %+v, want %+v", live, want)
	}
	if !reflect.DeepEqual(file, live) {
		t.Fatalf("file mode %+v differs from live mode %+v", file, live)
	}
}
```

- [ ] **Step 3: Chạy test**

```bash
cd ennam.kg.go && KG_TEST_DATABASE_URL='postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable' go test ./internal/intel/filedata/ -run TestParity -count=1 -v 2>&1 | grep -E -- '--- (PASS|FAIL|SKIP)|^ok|^FAIL'
```
Expected: `--- PASS: TestParity_FileModeMatchesLiveMode`, không `SKIP`. Test này viết sau implementation (Task 6/8) nên lần chạy đầu đã xanh. Để chứng minh nó bắt được lỗi: tạm sửa `"2026-07-01T23:30:00"` trong `testdata/sales_small.parsed.json` (bản Go) thành `"2026-07-02T23:30:00"`, chạy lại ⇒ phải FAIL với `file mode … differs`. Hoàn tác bằng `git -C ennam.kg.go checkout -- internal/intel/filedata/testdata/sales_small.parsed.json`.

- [ ] **Step 4: Commit**

```bash
git -C ennam.kg.go add internal/intel/filedata/testdata/net_sales_metric.sql internal/intel/filedata/parity_integration_test.go
git -C ennam.kg.go commit -m "test(filedata): file-mode metric equals live-mode metric through the pack compiler"
```

---

### Task 12: Next.js — lựa chọn "Tài liệu" / "Dữ liệu bảng" + báo cáo validate

**Files:**
- Create: `ennam.kg.next/src/lib/tabular-upload.ts`
- Modify: `ennam.kg.next/src/hooks/use-upload-files.ts`
- Modify: `ennam.kg.next/src/components/sources/upload-dropzone.tsx`
- Create: `ennam.kg.next/src/components/sources/tabular-upload-report.tsx`
- **Không sửa:** `src/app/api/kg/projects/[id]/ingest/upload/route.ts` (đã chuyển nguyên `req.formData()`)

**Interfaces:**
- Consumes: JSON `UploadResult` của Task 10 (`mode`, `draft_id?`, `upload_id`, `status`, `tabular?`).
- Produces:
  - `useUploadFiles(projectId).mutateAsync({ files, title?, autoApprove?, ingestMode?, datasetName?, writeMode? })` trả `UploadFileResult[]`, với `UploadFileResult = DocumentUploadResult | TabularUploadResult` (union phân biệt bằng `mode`).
  - `guessIngestMode(files)`, `suggestDatasetName(filename)`, `isTabularFile(name)`, `tabularSelectionError(files, mode, datasetName)`.
- Hành vi:
  - Thả file mà **không** có file nào csv/xlsx/xls ⇒ upload ngay như cũ (Tài liệu).
  - Có file bảng ⇒ hiện bảng chọn. Mặc định là "Dữ liệu bảng" khi **mọi** file là csv/xlsx/xls. Tên dataset được gợi ý từ tên file (snake_case). Chế độ ghi mặc định `replace`.

- [ ] **Step 1: Ghi nhận trạng thái "đỏ" (không có test runner, dùng type-check)**

```bash
cd ennam.kg.next && npx tsc --noEmit 2>&1 | tail -3
```
Expected: sạch (trạng thái gốc). Ở Step 3, hook đổi sang union trước khi sửa dropzone ⇒ `tsc` phải báo lỗi tại `upload-dropzone.tsx` (`Property 'draft_id' does not exist on type 'TabularUploadResult'`). Đó là bằng chứng type-check bắt được chỗ crash `results[0].draft_id.slice` trước đây.

- [ ] **Step 2: Helper thuần**

`ennam.kg.next/src/lib/tabular-upload.ts`:
```ts
export type IngestMode = 'document' | 'tabular';
export type WriteMode = 'append' | 'replace';

const TABULAR_EXTENSIONS = new Set(['.csv', '.xlsx', '.xls']);
const DATASET_NAME_RE = /^[a-z][a-z0-9_]{0,62}$/;

export function fileExtension(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot < 0 ? '' : name.slice(dot).toLowerCase();
}

export function isTabularFile(name: string): boolean {
  return TABULAR_EXTENSIONS.has(fileExtension(name));
}

/** Table data only when every selected file is a spreadsheet/CSV; the user can still switch. */
export function guessIngestMode(files: File[]): IngestMode {
  return files.length > 0 && files.every((f) => isTabularFile(f.name)) ? 'tabular' : 'document';
}

/** Same normalisation as the server's header rules: ASCII snake_case, starts with a letter. */
export function suggestDatasetName(filename: string): string {
  const base = filename.replace(/\.[^.]+$/, '').replace(/đ/g, 'd').replace(/Đ/g, 'D');
  let slug = base
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
  if (!slug) slug = 'dataset';
  if (/^[0-9]/.test(slug)) slug = `d_${slug}`;
  return slug.slice(0, 63).replace(/_+$/, '');
}

export function isValidDatasetName(name: string): boolean {
  return DATASET_NAME_RE.test(name);
}

/** Returns a message explaining why the current selection cannot be uploaded, or null. */
export function tabularSelectionError(
  files: File[],
  mode: IngestMode,
  datasetName: string,
): string | null {
  if (mode === 'document') {
    const xls = files.find((f) => fileExtension(f.name) === '.xls');
    return xls ? `${xls.name}: .xls files can only be imported as Dữ liệu bảng` : null;
  }
  if (files.length !== 1) return 'Dữ liệu bảng imports one file at a time';
  if (!isTabularFile(files[0].name)) return 'Dữ liệu bảng accepts .csv, .xlsx or .xls';
  if (!isValidDatasetName(datasetName)) {
    return 'Dataset name: lowercase letters, digits and _, starting with a letter';
  }
  return null;
}
```

- [ ] **Step 3: Hook (union phân biệt + field mới)**

Thay toàn bộ `ennam.kg.next/src/hooks/use-upload-files.ts`:
```ts
'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { IngestMode, WriteMode } from '@/lib/tabular-upload';

export type ColumnInfo = { name: string; source_name?: string; type: string };

export type ValidationIssue = {
  code: string;
  message: string;
  field?: string;
  column?: string;
  rows?: number[];
  count?: number;
  values?: string[];
};

export type ColumnStat = {
  field: string;
  column: string;
  column_type: string;
  canonical_type: string;
  null_count: number;
  null_ratio: number;
};

export type EntityValidation = {
  entity: string;
  status: 'current' | 'incomplete' | 'blocked';
  issues: ValidationIssue[];
  columns: ColumnStat[];
  issues_truncated?: boolean;
};

export type DatasetReport = {
  dataset: string;
  sheet?: string;
  write_mode: WriteMode;
  rows_written: number;
  row_offset: number;
  row_count: number;
  columns: ColumnInfo[];
  validation: EntityValidation[];
  validation_error?: string;
};

export type TabularReport = {
  datasets: DatasetReport[];
  has_issues: boolean;
  metrics_triggered: boolean;
  warnings?: string[];
};

export type DocumentUploadResult = {
  mode: 'document';
  draft_id: string;
  upload_id: string;
  status: string;
};

export type TabularUploadResult = {
  mode: 'tabular';
  upload_id: string;
  status: 'ingested' | 'ingested_with_issues';
  tabular: TabularReport;
};

export type UploadFileResult = DocumentUploadResult | TabularUploadResult;

type UploadOptions = {
  title?: string;
  autoApprove?: boolean;
  ingestMode?: IngestMode;
  datasetName?: string;
  writeMode?: WriteMode;
};

async function uploadFiles(
  projectId: string,
  files: File[],
  options?: UploadOptions,
): Promise<UploadFileResult[]> {
  const formData = new FormData();
  for (const file of files) {
    formData.append('file', file);
  }
  if (options?.title) {
    formData.append('title', options.title);
  }
  if (options?.autoApprove) {
    formData.append('auto_approve', 'true');
  }
  if (options?.ingestMode) {
    formData.append('ingest_mode', options.ingestMode);
  }
  if (options?.ingestMode === 'tabular') {
    formData.append('dataset_name', options.datasetName ?? '');
    formData.append('write_mode', options.writeMode ?? 'replace');
  }

  const res = await fetch(
    `/api/kg/projects/${encodeURIComponent(projectId)}/ingest/upload`,
    {
      method: 'POST',
      body: formData,
    },
  );

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const detail =
      typeof err === 'object' && err && 'message' in err && (err as { message?: string }).message
        ? String((err as { message?: string }).message)
        : typeof err === 'object' && err && 'error' in err
          ? String((err as { error?: string }).error)
          : res.statusText;
    throw new Error(detail || `Upload failed (${res.status})`);
  }

  const data = await res.json();
  if (Array.isArray(data?.uploads)) {
    return data.uploads as UploadFileResult[];
  }
  return [data as UploadFileResult];
}

export function useUploadFiles(projectId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ files, ...options }: { files: File[] } & UploadOptions) =>
      uploadFiles(projectId, files, options),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['draft-nodes', projectId] });
      queryClient.invalidateQueries({ queryKey: ['draft-status-counts', projectId] });
    },
  });
}
```
(Lỗi từ Go có dạng `{error, message, status_code}`. Ưu tiên `message`, vì nó chứa thông tin cụ thể như `encoding: CSV files must be UTF-8 encoded`.)

Chạy `cd ennam.kg.next && npx tsc --noEmit 2>&1 | grep upload-dropzone`. Expected: có lỗi ở `upload-dropzone.tsx` (bằng chứng của Step 1).

- [ ] **Step 4: Component báo cáo**

`ennam.kg.next/src/components/sources/tabular-upload-report.tsx`:
```tsx
'use client';

import type {
  DatasetReport,
  EntityValidation,
  TabularReport,
} from '@/hooks/use-upload-files';

const STATUS_STYLE: Record<EntityValidation['status'], string> = {
  current: 'border-[#00FF94]/40 bg-[#00FF94]/10 text-[#00FF94]',
  incomplete: 'border-[#FFC857]/40 bg-[#FFC857]/10 text-[#FFC857]',
  blocked: 'border-[#FF6B6B]/40 bg-[#FF6B6B]/10 text-[#FF6B6B]',
};

/** Dataset row_num → what the user sees in the file (line 1 is the header). */
function rowLabel(rowNum: number, rowOffset: number): string {
  return rowNum > rowOffset ? `file line ${rowNum - rowOffset + 1}` : `existing row ${rowNum}`;
}

function EntityBlock({ validation, rowOffset }: { validation: EntityValidation; rowOffset: number }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-[#2A2E45] bg-[#12152A] p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs text-[#F0F0F8]">entity:{validation.entity}</span>
        <span
          className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider ${STATUS_STYLE[validation.status]}`}
        >
          {validation.status}
        </span>
      </div>
      {validation.issues.length === 0 ? (
        <p className="text-xs text-[#8C91AE]">All mapped fields are present and correctly typed.</p>
      ) : (
        <ul className="flex flex-col gap-1 text-xs text-[#F0F0F8]">
          {validation.issues.map((issue, i) => (
            <li key={`${issue.code}-${i}`} className="leading-relaxed">
              <span className="font-mono text-[#8C91AE]">{issue.code}</span> {issue.message}
              {issue.values && issue.values.length > 0 && (
                <span className="font-mono text-[#FFC857]"> [{issue.values.join(', ')}]</span>
              )}
              {issue.rows && issue.rows.length > 0 && (
                <span className="text-[#8C91AE]">
                  {' '}
                  ({issue.rows.map((r) => rowLabel(r, rowOffset)).join(', ')}
                  {issue.count && issue.count > issue.rows.length ? `, … ${issue.count} in total` : ''})
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {validation.issues_truncated && (
        <p className="text-xs text-[#8C91AE]">More issues exist; only the first ones are listed.</p>
      )}
    </div>
  );
}

function DatasetCard({ dataset }: { dataset: DatasetReport }) {
  return (
    <article className="flex flex-col gap-3 rounded-xl border border-[#2A2E45] bg-[#171A2B] p-3">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-mono text-sm text-[#00D4FF]">{dataset.dataset}</h3>
        <span className="text-xs text-[#8C91AE]">
          {dataset.rows_written} rows {dataset.write_mode === 'append' ? 'appended' : 'loaded'} ·{' '}
          {dataset.row_count} total
          {dataset.sheet ? ` · sheet “${dataset.sheet}”` : ''}
        </span>
      </header>
      <ul className="flex flex-wrap gap-1.5" aria-label="Columns">
        {dataset.columns.map((c) => (
          <li
            key={c.name}
            title={c.source_name}
            className="rounded-md border border-[#2A2E45] px-1.5 py-0.5 font-mono text-[11px] text-[#F0F0F8]"
          >
            {c.name} <span className="text-[#707694]">{c.type}</span>
          </li>
        ))}
      </ul>
      {dataset.validation_error && (
        <p role="alert" className="text-xs text-[#FF6B6B]">
          Validation could not run: {dataset.validation_error}
        </p>
      )}
      {dataset.validation.length === 0 && !dataset.validation_error && (
        <p className="text-xs text-[#8C91AE]">
          No approved mapping reads this dataset yet — rows are stored, nothing to validate.
        </p>
      )}
      {dataset.validation.map((v) => (
        <EntityBlock key={v.entity} validation={v} rowOffset={dataset.row_offset} />
      ))}
    </article>
  );
}

export default function TabularUploadReport({ report }: { report: TabularReport }) {
  return (
    <section aria-label="Table import report" className="flex flex-col gap-3">
      {report.warnings?.map((warning) => (
        <p key={warning} role="alert" className="text-xs text-[#FFC857]">
          {warning}
        </p>
      ))}
      {report.datasets.map((ds) => (
        <DatasetCard key={ds.dataset} dataset={ds} />
      ))}
      <p className="text-xs text-[#8C91AE]">
        {report.metrics_triggered
          ? 'Metrics are being recalculated from this data.'
          : 'Metrics were not recalculated — fix blocking issues or add a mapping for this dataset.'}
      </p>
    </section>
  );
}
```

- [ ] **Step 5: Dropzone**

Thay toàn bộ `ennam.kg.next/src/components/sources/upload-dropzone.tsx`:
```tsx
'use client';

import { useCallback, useRef, useState } from 'react';
import {
  Upload,
  Loader2,
  CheckCircle2,
  AlertCircle,
  FileText,
  FileSpreadsheet,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  useUploadFiles,
  type DocumentUploadResult,
  type TabularReport,
} from '@/hooks/use-upload-files';
import TabularUploadReport from '@/components/sources/tabular-upload-report';
import {
  guessIngestMode,
  isTabularFile,
  suggestDatasetName,
  tabularSelectionError,
  type IngestMode,
  type WriteMode,
} from '@/lib/tabular-upload';

const ACCEPT =
  '.md,.txt,.json,.csv,.pdf,.docx,.xlsx,.xls,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel';

const MODE_OPTIONS: { value: IngestMode; label: string; hint: string; Icon: typeof FileText }[] = [
  { value: 'document', label: 'Tài liệu', hint: 'Searchable document for Q&A', Icon: FileText },
  { value: 'tabular', label: 'Dữ liệu bảng', hint: 'Rows stored for metrics', Icon: FileSpreadsheet },
];

const WRITE_OPTIONS: { value: WriteMode; label: string }[] = [
  { value: 'replace', label: 'Replace all rows' },
  { value: 'append', label: 'Append rows' },
];

type PendingSelection = {
  files: File[];
  mode: IngestMode;
  datasetName: string;
  writeMode: WriteMode;
};

export default function UploadDropzone({
  projectId,
  onDraftsQueued,
}: {
  projectId: string;
  onDraftsQueued?: (draftIds: string[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingSelection | null>(null);
  const [tabularReport, setTabularReport] = useState<TabularReport | null>(null);

  const upload = useUploadFiles(projectId);

  const runUpload = useCallback(
    async (selection: PendingSelection) => {
      const { files, mode, datasetName, writeMode } = selection;
      setError(null);
      setMessage(null);
      setTabularReport(null);
      setProgress(10);

      try {
        const results = await upload.mutateAsync({
          files,
          autoApprove: true,
          ingestMode: mode,
          datasetName: mode === 'tabular' ? datasetName : undefined,
          writeMode: mode === 'tabular' ? writeMode : undefined,
        });
        const documents = results.filter((r): r is DocumentUploadResult => r.mode === 'document');
        onDraftsQueued?.(
          documents
            .filter((r) => r.status === 'processing')
            .map((r) => r.draft_id)
            .filter(Boolean),
        );
        setProgress(100);

        const tabular = results.find((r) => r.mode === 'tabular');
        if (tabular && tabular.mode === 'tabular') {
          setTabularReport(tabular.tabular);
          setMessage(
            tabular.status === 'ingested'
              ? `Imported ${files[0].name} as table data`
              : `Imported ${files[0].name} — review the issues below`,
          );
        } else {
          setMessage(
            documents.length === 1
              ? `Uploaded ${files[0].name} — draft ${documents[0].draft_id.slice(0, 8)}…`
              : `Uploaded ${results.length} files`,
          );
        }
      } catch (err) {
        setProgress(null);
        setError(err instanceof Error ? err.message : 'Upload failed');
      } finally {
        setTimeout(() => setProgress(null), 1200);
      }
    },
    [upload, onDraftsQueued],
  );

  const handleFiles = useCallback(
    (fileList: FileList | File[]) => {
      const files = Array.from(fileList);
      if (files.length === 0) return;
      const selection: PendingSelection = {
        files,
        mode: guessIngestMode(files),
        datasetName: suggestDatasetName(files[0].name),
        writeMode: 'replace',
      };
      if (!files.some((f) => isTabularFile(f.name))) {
        void runUpload(selection);
        return;
      }
      setError(null);
      setMessage(null);
      setTabularReport(null);
      setPending(selection);
    },
    [runUpload],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles],
  );

  const selectionError = pending
    ? tabularSelectionError(pending.files, pending.mode, pending.datasetName)
    : null;

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-[#2A2E45] bg-[#171A2B] p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-[#707694]">
          Upload files
        </span>
        <span className="text-xs text-[#8C91AE]">MD, TXT, JSON, CSV, PDF, DOCX, XLSX, XLS — max 50MB</span>
      </div>

      <div
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border border-dashed px-6 py-10 transition-colors ${
          dragOver
            ? 'border-[#00D4FF] bg-[#00D4FF10]'
            : 'border-[#2A2E45] hover:border-[#00D4FF]/60 hover:bg-[#00D4FF08]'
        }`}
      >
        {upload.isPending ? (
          <Loader2 className="h-8 w-8 animate-spin text-[#00D4FF]" />
        ) : (
          <Upload className="h-8 w-8 text-[#00D4FF]" />
        )}
        <p className="text-sm text-[#F0F0F8]">Drag and drop files here, or click to browse</p>
        <p className="text-xs text-[#8C91AE]">Up to 10 files per upload · tables one at a time</p>
      </div>

      <input
        ref={inputRef}
        type="file"
        className="hidden"
        multiple
        accept={ACCEPT}
        onChange={(e) => {
          if (e.target.files) handleFiles(e.target.files);
          e.target.value = '';
        }}
      />

      {pending && (
        <fieldset className="flex flex-col gap-3 rounded-xl border border-[#2A2E45] bg-[#12152A] p-3">
          <legend className="px-1 text-xs font-semibold uppercase tracking-wider text-[#707694]">
            Import {pending.files.length === 1 ? pending.files[0].name : `${pending.files.length} files`} as
          </legend>

          <div role="radiogroup" aria-label="Import mode" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {MODE_OPTIONS.map(({ value, label, hint, Icon }) => {
              const active = pending.mode === value;
              return (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => setPending({ ...pending, mode: value })}
                  className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00D4FF]/60 ${
                    active
                      ? 'border-[#00D4FF] bg-[#00D4FF14] text-[#F0F0F8]'
                      : 'border-[#2A2E45] text-[#8C91AE] hover:border-[#00D4FF]/50'
                  }`}
                >
                  <Icon className="mt-0.5 h-4 w-4 shrink-0 text-[#00D4FF]" />
                  <span className="flex flex-col">
                    <span className="text-sm font-medium">{label}</span>
                    <span className="text-xs text-[#8C91AE]">{hint}</span>
                  </span>
                </button>
              );
            })}
          </div>

          {pending.mode === 'tabular' && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-xs text-[#8C91AE]">
                Dataset name
                <Input
                  value={pending.datasetName}
                  onChange={(e) => setPending({ ...pending, datasetName: e.target.value.trim() })}
                  className="font-mono text-[#F0F0F8]"
                  spellCheck={false}
                  aria-invalid={selectionError !== null}
                />
              </label>
              <div role="radiogroup" aria-label="Write mode" className="flex flex-col gap-1 text-xs text-[#8C91AE]">
                If the dataset already exists
                <div className="flex gap-2">
                  {WRITE_OPTIONS.map(({ value, label }) => (
                    <button
                      key={value}
                      type="button"
                      role="radio"
                      aria-checked={pending.writeMode === value}
                      onClick={() => setPending({ ...pending, writeMode: value })}
                      className={`rounded-md border px-2.5 py-1.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#00D4FF]/60 ${
                        pending.writeMode === value
                          ? 'border-[#00D4FF] text-[#F0F0F8]'
                          : 'border-[#2A2E45] text-[#8C91AE] hover:border-[#00D4FF]/50'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {selectionError && (
            <p role="alert" className="text-xs text-[#FFC857]">
              {selectionError}
            </p>
          )}

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="border-[#2A2E45] text-[#F0F0F8]"
              onClick={() => setPending(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={selectionError !== null || upload.isPending}
              onClick={() => {
                const selection = pending;
                setPending(null);
                void runUpload(selection);
              }}
            >
              Upload
            </Button>
          </div>
        </fieldset>
      )}

      {progress !== null && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-[#2A2E45]">
          <div
            className="h-full rounded-full bg-[#00D4FF] transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}

      {message && (
        <p className="flex items-center gap-2 text-sm text-[#00FF94]">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          {message}
        </p>
      )}
      {error && (
        <p className="flex items-center gap-2 text-sm text-[#FF6B6B]">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </p>
      )}

      {tabularReport && <TabularUploadReport report={tabularReport} />}

      <div className="flex justify-end">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="border-[#2A2E45] text-[#F0F0F8]"
          disabled={upload.isPending}
          onClick={() => inputRef.current?.click()}
        >
          Choose files
        </Button>
      </div>
    </div>
  );
}
```
(Thanh progress vẫn animate `width` như code gốc; không đổi để giữ Rule 3.)

- [ ] **Step 6: Type-check + lint, phải sạch**

```bash
cd ennam.kg.next && npx tsc --noEmit && npm run lint -- src/lib/tabular-upload.ts src/hooks/use-upload-files.ts src/components/sources/upload-dropzone.tsx src/components/sources/tabular-upload-report.tsx
```
Expected: `tsc` không in lỗi; eslint không lỗi.

- [ ] **Step 7: Kiểm tra trên trình duyệt (stack chạy đủ: `docker compose up -d --build`, sau Task 1–10)**

Mở `http://localhost:3500/projects/<projectId>/sources` bằng Playwright MCP hoặc chrome-devtools rồi kiểm tra:
1. Thả `notes.md` ⇒ upload ngay, thông báo `Uploaded notes.md — draft …` (luồng tài liệu không đổi).
2. Thả `ennam.kg.python/tests/ingestion/fixtures/tabular/sales_small.csv` ⇒ hiện bảng chọn, "Dữ liệu bảng" đã được chọn, tên dataset `sales_small`, chế độ `Replace all rows`. Bấm Upload ⇒ có thẻ `sales_small`, `5 rows loaded`, 4 cột kèm kiểu `text/text/timestamp/numeric`, và dòng "No approved mapping reads this dataset yet".
3. Chọn lại file đó, đổi sang "Tài liệu" ⇒ upload tạo draft như cũ.
4. Chọn một file `.xls` rồi đổi sang "Tài liệu" ⇒ nút Upload bị vô hiệu, có cảnh báo `.xls files can only be imported as Dữ liệu bảng`.
5. Gõ tên dataset `Bad Name` ⇒ nút Upload bị vô hiệu kèm thông báo.
6. Bàn phím: Tab tới các nút radio, Enter/Space chọn được; focus ring hiển thị.
7. Chụp màn hình ở 375 px và 1024 px, thấy không cuộn ngang; lưu vào `docs/superpowers/test-results/2026-10-pi-c-upload-{375,1024}.png`.

- [ ] **Step 8: Commit**

```bash
git -C ennam.kg.next add src/lib/tabular-upload.ts src/hooks/use-upload-files.ts src/components/sources/upload-dropzone.tsx src/components/sources/tabular-upload-report.tsx
git -C ennam.kg.next commit -m "feat(sources): choose Tài liệu or Dữ liệu bảng on upload and show the table import report"
git add docs/superpowers/test-results/2026-10-pi-c-upload-375.png docs/superpowers/test-results/2026-10-pi-c-upload-1024.png
git commit -m "docs(test-results): tabular upload screenshots"
```

---

### Task 13: Demo — `targets.xlsx` → dataset `store_targets` → entity `target` (phối hợp A/B)

**Files:**
- Modify: `packs/_projects/pharmacy-chain/mapping.yaml` (workspace repo). Plan B tạo file này và để lại phần `target` cho Plan C, theo Exports: "Plan C thêm block `target:`".
- Kiểm tra (không sửa): `demo_mockdata/targets.xlsx` (Plan A sở hữu).

**Interfaces:**
- Consumes:
  - **Master (đã khoá):** `targets.xlsx` có 1 sheet, cột `Store ID | Metric Key | Period | Target Value`, `Period` là ngày đầu tháng, target % là số 0–100. **As-of** = ngày dữ liệu cuối cùng, **bao gồm** (demo `2026-07-31`); runner tính cửa sổ và độ tươi theo `as_of`, không theo đồng hồ.
  - **Plan B canonical `target`** (pack `retail`): `location_id` text, `metric_key` text với enum `[net_sales, gross_margin_pct]`, `period` date, `value` numeric. Cả 4 field required, **không có key**. Metric `retail.target_net_sales` / `retail.target_gross_margin_pct` (grain month, snapshot) lọc `WHERE metric_key = 'net_sales'` / `'gross_margin_pct'`. Vì vậy cột `Metric Key` trong file phải là **đúng** `net_sales` / `gross_margin_pct` (không phải `retail.net_sales`); sai giá trị sẽ bị validation báo `enum_value`.
  - **Định dạng mapping file của B** (`intel.ParseMappingFile`): `project_id`, `defaults`, `entities: { <entity>: { mode, file_dataset, from?, fields, enum_map? } }`. `import-mapping` **không** đòi dataset tồn tại.
  - Sau chuẩn hoá header (Task 2), file đúng hợp đồng có cột `store_id` text, `metric_key` text, `period` date, `target_value` numeric (hoặc integer nếu mọi giá trị nguyên, vẫn hợp lệ cho field `numeric`).
- Produces: block `target` trong mapping (bên dưới `entities:`):
  ```yaml
    target:
      mode: file
      file_dataset: store_targets
      fields:
        location_id: store_id
        metric_key:  metric_key
        period:      period
        value:       target_value
  ```

- [ ] **Step 1: Thêm block `target` vào mapping của B**

Trong `packs/_projects/pharmacy-chain/mapping.yaml`:
- Thêm block trên vào cuối map `entities:` (thụt lề 2 dấu cách như các entity khác; `mode: file` ghi đè `defaults.mode: live`).
- Trong comment đầu file, sửa dòng `# Not mapped yet: labor_rate (…) and` / `# target (mode=file — Plan C appends the block for dataset store_targets).` thành `# Not mapped yet: labor_rate (wage rate — add when Plan A ships a wage column).` và thêm dòng `# target is mode=file: rows come from the "Dữ liệu bảng" upload of dataset store_targets (Plan C).`

Kiểm tra cú pháp và hợp đồng bằng chính parser của B (chạy từ `ennam.kg.go`):
```bash
cd ennam.kg.go && cat > /tmp/pi_c_mapping_check_test.go <<'EOF'
package intel_test

import (
	"os"
	"testing"

	"github.com/ennam/ennam-kg/internal/intel"
)

func TestPiCTargetMapping(t *testing.T) {
	raw, err := os.ReadFile("../../../packs/_projects/pharmacy-chain/mapping.yaml")
	if err != nil {
		t.Fatal(err)
	}
	mf, err := intel.ParseMappingFile(raw)
	if err != nil {
		t.Fatal(err)
	}
	for _, m := range mf.Mappings {
		if m.Entity == "target" {
			if m.Mode != intel.ModeFile || m.FileDataset != "store_targets" || m.Spec.Fields["value"] != "target_value" {
				t.Fatalf("target = %+v", m)
			}
			return
		}
	}
	t.Fatal("no target mapping")
}
EOF
cp /tmp/pi_c_mapping_check_test.go internal/intel/zz_pi_c_mapping_check_test.go && go test ./internal/intel/ -run TestPiCTargetMapping -count=1 -v | grep -E -- '--- (PASS|FAIL)'; rm internal/intel/zz_pi_c_mapping_check_test.go
```
Expected: `--- PASS: TestPiCTargetMapping`. File test tạm bị xoá ngay sau khi chạy, không commit. Đồng thời chạy lại test fixture của B để chắc block mới không phá gì: `KG_TEST_DATABASE_URL=… go test ./internal/intel/packtest/ -count=1 -v | grep -cE -- '--- SKIP'` phải ra `0`, và package `ok`.

- [ ] **Step 2: Kiểm tra file target của A theo hợp đồng master (không sửa file của A)**

```bash
cd ennam.kg.python && uv run python -c "
from pathlib import Path
from ennam_kg.ingestion.tabular.reader import parse_tabular
sheets = parse_tabular(Path('../demo_mockdata/targets.xlsx'), max_rows=200000)
s = sheets[0]
print(len(sheets), [(c.name, c.type) for c in s.columns], len(s.rows))
print(sorted({r[1] for r in s.rows}))
print(max(float(r[3]) for r in s.rows if r[1] == 'gross_margin_pct'))"
```
Expected:
- `1 [('store_id', 'text'), ('metric_key', 'text'), ('period', 'date'), ('target_value', 'numeric')] <n>` — n = 5 store × 2 metric × số tháng.
- `['gross_margin_pct', 'net_sales']`
- Margin lớn nhất nằm trong khoảng 1–100 (thang 0–100, không phải 0–1).

Lệch ⇒ ghi `mcp__serena__write_memory("comms/active/pi-c-to-pi-a-targets-xlsx", …)` kèm hợp đồng master, rồi dừng (xem Q1: Plan A hiện vẫn mô tả định dạng "wide").

- [ ] **Step 3: Smoke trên stack đầy đủ**

Thứ tự (M4): import mapping (Step 1 của M4, đã gồm block `target`; `--project` là bắt buộc) → `kg-packs install --project …` → **`kg-packs set-as-of --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --date 2026-07-31` trước khi upload**. Lần chạy do upload trigger dùng `as_of` đã đặt; nếu chưa đặt thì as-of là "hôm qua", cửa sổ không chạm tháng 7 nên target tháng 7 chưa có. (Master M4 đã đặt `set-as-of` trước bước upload.)
```bash
docker exec daab-server go run ./cmd/kg-packs import-mapping --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --file /packs/_projects/pharmacy-chain/mapping.yaml --approve
docker exec daab-server go run ./cmd/kg-packs set-as-of --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --date 2026-07-31
curl -sS -X POST \
  -H "Authorization: Bearer ${KG_API_KEY:-ennam_kg_dev_000000000000000000000000}" \
  -F file=@demo_mockdata/targets.xlsx -F ingest_mode=tabular -F dataset_name=store_targets -F write_mode=replace \
  http://localhost:8080/api/v1/projects/4ad7a5fa-a036-4f6a-8229-39a20af23e38/ingest/upload \
  | jq '{status, mode, ds: .tabular.datasets[0] | {dataset, row_count, v: [.validation[] | {entity, status, issues}]}, triggered: .tabular.metrics_triggered}'
```
Expected:
```json
{"status":"ingested","mode":"tabular","ds":{"dataset":"store_targets","row_count":<n>,"v":[{"entity":"target","status":"current","issues":[]}]},"triggered":true}
```

```bash
psql "postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable" -c "
SELECT d.name, d.row_count, d.write_mode, (SELECT count(*) FROM file_dataset_row r WHERE r.dataset_id = d.id) AS rows
FROM file_dataset d WHERE d.project_id = '4ad7a5fa-a036-4f6a-8229-39a20af23e38';
SELECT metric_key, period_date, dims->>'location_id' AS loc, value, source_mode FROM metric_value
WHERE project_id = '4ad7a5fa-a036-4f6a-8229-39a20af23e38' AND metric_key LIKE 'retail.target_%' AND period_date = '2026-07-01'
ORDER BY 1, 3;
SELECT subject, status FROM data_status
WHERE project_id = '4ad7a5fa-a036-4f6a-8229-39a20af23e38' AND subject IN ('file:store_targets', 'entity:target', 'metric:retail.target_net_sales');"
```
Expected:
- `store_targets | n | replace | n`.
- 10 dòng `retail.target_*` cho `2026-07-01` (5 store × 2 metric), `source_mode = file`. Có thể cần chờ vài giây vì scheduler chạy bất đồng bộ; chạy lại query nếu chưa có.
- `file:store_targets` = `current` (ghi bởi upload); `entity:target` và `metric:retail.target_net_sales` (ghi bởi runner B sau trigger) khác `blocked`.
- Upload lại với `write_mode=replace` ⇒ `row_count` vẫn bằng n, không bị nhân đôi.

- [ ] **Step 4: Commit mapping (workspace repo) + checkpoint**

```bash
git add packs/_projects/pharmacy-chain/mapping.yaml
git commit -m "feat(packs): map entity target to the store_targets file dataset"
```
`mcp__serena__write_memory("checkpoint/pi-c-tabular-upload-<YYYY-MM-DD>", …)`: đã làm gì, kết quả smoke, các Open question còn mở.

---

## Self-Review

- **Độ phủ scope:**
  1. UI chọn chế độ, đoán theo đuôi file, chọn tên dataset và chế độ ghi: Task 12.
  2. Go đọc field cạnh `auto_approve`, nhánh không tạo draft, quyết định parse ở Python: Task 10, File Structure.
  3. Migration 000092 nguyên văn (sau 000088–000091 của B), append/replace trong một transaction: Task 1, Task 6.
  4. Báo cáo validate (field, kiểu, NULL, enum, khoá) + `data_status 'file:<dataset>'` qua writer chung của B (runner B là nơi duy nhất ghi `entity:`/`metric:`): Task 7, 9.
  5. `intel.SourceTable` + `intel.SourceResolver` (`intel.ModeFile`) đăng ký trong `buildIntel`, `intel.RunTrigger` sau upload: Task 8, 9, 10.
  6. Test parser/kiểu/append-replace/validate/handler/parity (qua compiler thật của B): Task 2–11.
  7. Demo `store_targets`/`target` + block mapping: Task 13.
- **Khớp Exports của Plan B (tên cuối):**
  - `intel.SourceTable{Relation, Filter, RefLabel, Columns, ColumnSQL}`; alias `src`; `Filter` không có chữ `WHERE`.
  - `intel.SourceResolver{Prepare, Bind}` với `projectID string`.
  - `intel.BoundSource{Table, Executor: sqlexec.New(db, 30s), Watermark}`.
  - `intel.ErrSourceNotReady` cho mọi vấn đề dữ liệu file.
  - `intel.RunTrigger.Trigger(projectID string)`, nhận từ `sched` trong `buildIntel` và chỉ gán khi khác nil.
  - `(*intelstore.Store).UpsertDataStatus` / `ListMappings`.
  - `(*intel.Registry).Effective` (cách gom pack giống `CanonicalEntity`, cộng enums).
- **Review Focus → test:** 5 rủi ro đều có test cụ thể, nêu tên ở đầu file, nằm trong task sở hữu.
- **Không cắt âm thầm:**
  - Python giữ mọi dòng; vượt giới hạn là lỗi `row_cap_exceeded`.
  - Store kiểm tra giới hạn cả khi append.
  - Parser trả JSON sai ⇒ `ErrInvalidParse` (503), không ghi.
  - Đường 50.000 ký tự (`nodes.py`) không nằm trên nhánh này.
- **Nhất quán tên giữa các task:**
  - `IngestReport/DatasetReport/EntityReport/Issue/ColumnStat` có JSON tag khớp type TS ở Task 12 (`rows_written`, `row_offset`, `issues_truncated`, `column_type`, `canonical_type`, `null_ratio`, `metrics_triggered`, `validation_error`). `Issue.values` (enum lạ) là trường tuỳ chọn mới: TS chỉ hiện `message` + `rows`, không vỡ.
  - `UploadResult.Mode` = `document|tabular` khớp `UploadFileResult`.
  - `ParseError.Is(ErrRowCapExceeded)` được dùng ở Task 9 và Task 10.
- **Rule 3 (thay đổi khoanh vùng):**
  - `classifyUploadFile` và `handleOneFile` (chỉ thêm `Mode`) không bị refactor.
  - `storeTabularObject` lặp lại khoảng 25 dòng lưu object của `handleOneFile`: chấp nhận để không chạm luồng tài liệu; ghi nhận để dọn sau.
  - Proxy Next không sửa.
  - Sửa file của B chỉ ở 2 điểm B đã giao cho C: đăng ký trong `buildIntel` (kèm giá trị trả thứ ba) và block `target` trong `mapping.yaml`.
- **Đã kiểm tra bằng code thật hoặc plan B:**
  - Tên field FormData (`file/title/auto_approve`), `collectUploadFiles`, `errorResponse` (`{error,message,status_code}`), `requireProjectAccess` và chữ ký `ProjectRoleResolverFunc`.
  - `middleware.ProjectID` chỉ đọc header/query (`project.go:217-227`).
  - `KG_PYTHON_URL` (`main.go:382-386`; embed client dùng token cố định `kg-internal`, client parse dùng `KG_INTERNAL_TOKEN`); `uploadSvc` (`main.go:733`) và lời gọi `buildIntel` đều nằm trong `buildRouter`; write timeout production 10s; wrapper `responseRecorder` có `Unwrap()`.
  - Trong Plan B: `EntityCTE` bọc `CAST(ColumnSQL AS kiểu canonical)` và chỉ dùng `RefLabel` khi entity có key; runner biến `MappingError` thành `broken` và `ErrSourceNotReady` thành `incomplete` (`prepareEntity`); `Scheduler.Trigger` không chặn; `UpsertDataStatus` giữ `last_success_at` cũ khi nhận nil.
  - openpyxl có sẵn; xlrd/xlwt chạy trên Python 3.12.12; `LoadIngestionSettings(nil)` dùng mặc định; Next không có test runner.

## Ghi chú / giới hạn đã chấp nhận (beta)

- **Lỗi resolver mode=file (điều phối đã duyệt):** mọi vấn đề dữ liệu file (chưa upload, thiếu cột, kiểu không ép được) trả lỗi bọc `intel.ErrSourceNotReady` ⇒ entity `incomplete`, mapping giữ `approved`. Upload lại file đúng là đủ sửa; không bao giờ trả `*intel.MappingError` (runner B biến lỗi đó thành mapping `broken`).
- **`_source_ref` của dữ liệu file:** entity không có field `key` (như `target`) ⇒ compiler B cho `_source_ref = NULL`, nên evidence của metric target không trỏ về dòng file. Đã chấp nhận cho beta (không cần evidence cho target). Nếu sau này cần: thêm field `key` vào canonical (B), hoặc cho compiler ref theo `src.row_num`.
- **Subject `data_status`:** upload ghi `file:<dataset>`; runner B ghi `entity:`/`metric:` (master §2.3). Hai nguồn không ghi đè nhau.
- **Ô chỉ có giờ trong `.xls`:** xlrd trả `datetime` ngày 1899-12-31 cho ô kiểu time-only ⇒ thành timestamp `1899-12-31Txx:xx:xx`. Beta không có canonical field kiểu giờ thuần; khách cần cột giờ thì lưu dạng text hoặc dùng `.xlsx`.
- **Workbook đổi từ 1 sang 2 sheet có dữ liệu** ⇒ dataset đổi tên thành `<name>__<key>`. Mapping cũ vẫn đọc `<name>` (dữ liệu cũ). Upload trả `warnings` khi có mapping approved đọc `<name>` (Task 9 `TestIngest_WarnsWhenAMappedDatasetNameIsNotWritten`); người dùng phải sửa mapping hoặc bỏ sheet thừa.
- **Kiểm quyền upload:** áp cho mọi upload (cả "Tài liệu"): `requireProjectAccess` + role ≥ developer, trước khi đọc body. Đóng lỗ IDOR có từ trước của nhánh tài liệu (trước đây là Open question).
- **Token nội bộ:** endpoint `/api/v1/embeddings` của indexer có cùng điểm yếu từ trước (chỉ kiểm có header Bearer, body không giới hạn). Plan này **không** sửa endpoint đó; chỉ `/api/v1/tabular/parse` dùng `KG_INTERNAL_TOKEN`.

## Open questions

- **Q1 (Plan A ↔ master — định dạng `targets.xlsx`; điều phối xác nhận A đang sửa sang dạng long + thang 0–100, C giữ hợp đồng):** Plan A (`2026-10-02-pi-A-demo-data.md`, Task 7 / `targets.py`) hiện sinh sheet `targets` dạng **wide**: `store_id, store_name, month, net_sales_target, gross_margin_pct_target`. Master (mới hơn, đã khoá) quy định dạng **long**: `Store ID | Metric Key | Period | Target Value`, với `Metric Key ∈ {net_sales, gross_margin_pct}` theo enum của B. Theo Rule 7, master thắng ⇒ Plan A cần sửa generator. Ngoài ra `gross_margin_pct_target = round(gm - 0.05, 1)` trong A ngụ ý `gm` là tỉ lệ 0–1, trái với quy định % là 0–100 ⇒ A cần xác nhận thang đo.
- **Q2 (NFR-242):** Request upload bảng **chờ** indexer parse (đồng bộ). Go vẫn không tự extract. Cần owner BA-023/NFR-242 xác nhận ngoại lệ này cho "Dữ liệu bảng".
- **Q3 (giới hạn kích thước ở production):** ReadTimeout production 10s áp cho việc đọc body upload, và plan này không nới (nới sẽ ảnh hưởng mọi route). File bảng lớn qua mạng chậm có thể bị cắt trước khi tới handler. Giới hạn 200.000 dòng/dataset và JSON trả về từ indexer (~vài chục MB) cũng cần đo trên dữ liệu thật trước khi onboard khách.
- **Q4 (định dạng ngày/số ngoài ISO):** `01/07/2026`, `1.234,5`, `1,234.5`, timestamp có múi giờ ⇒ cột `text` ⇒ validation báo `type_mismatch`. Nếu khách thật dùng định dạng địa phương, cần thêm tuỳ chọn locale khi upload (spec §14.3).
- **Q5 (ngôn ngữ UI):** Nhãn "Tài liệu"/"Dữ liệu bảng" theo spec/M4, phần còn lại tiếng Anh như component hiện có. Cần chốt có dịch toàn bộ hay không (ennam.kg.next chưa có i18n).
- **Q6 (đặt tên dataset theo từng sheet):** Beta chỉ có một ô tên dataset; workbook nhiều sheet ⇒ `<name>__<sheet_key>`. Chưa có UI đặt tên riêng từng sheet.
- **Q7 (lớp metrics tắt):** Khi `buildIntel` không nạp được pack hoặc cấu hình `METRIC_*` sai, upload bảng trả 503 thay vì lưu dữ liệu mà không có báo cáo. Nếu muốn vẫn lưu dataset trong trường hợp này, cần một service không có validation (chưa làm).
- **Q8 (có từ trước — proxy Next):** `src/app/api/kg/projects/[id]/ingest/upload/route.ts` dùng `session.apiKey || process.env.KG_API_KEY`. Khi không có session, request được gửi bằng key của server ⇒ bỏ qua kiểm quyền theo user. Plan này không sửa proxy (chuyển nguyên FormData); đề nghị sửa riêng: trả 401 khi không có session.
