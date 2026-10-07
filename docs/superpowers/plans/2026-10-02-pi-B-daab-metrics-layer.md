# Plan B — DAAB Metrics Layer (Pack loader, Mapping compiler, Metric runner, 4 MCP tools) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DAAB đọc Industry Pack từ `PACKS_DIR`, biên dịch mapping của project thành CTE + metric SQL, chạy read-only trên DB khách (`mode: live`), lưu chuỗi `metric_value` + `data_status` (độ tươi tính theo `as_of`), và mở 4 MCP tool `kg_get_metrics`, `kg_get_evidence`, `kg_get_data_status`, `kg_list_metrics` đúng hợp đồng master §2.4 — kèm pack `retail` + `pharmacy` (32 metric + 32 evidence, khớp hợp đồng metric của Plan D) và mapping cho project Pharmacy Chain.

**Architecture:** Code mới dưới `ennam.kg.go/internal/intel/` (core trung tính ngành). Package `intel` thuần (không DB): model pack + loader, SQL lexer, expression validator (allow-list), dialect, param binding, compiler, interface nguồn (`SourceTable`/`SourceResolver` — Plan C hiện thực `mode=file`). `intel/intelstore` = SQL cho 5 bảng mới. `intel/sqlexec` = executor READ ONLY trong DB DAAB (test + Plan C). `intel/livesource` = resolver `mode=live` trên `service.SourceExecutor` + metadata schema đã sync. `intel/engine` = availability, runner (chunk, lookback, truncation, version bump, freshness theo as-of, data status), scheduler (ticker + advisory lock + trigger), query service (gộp theo aggregation, evidence). HTTP ở `internal/handler/intel_metrics.go`; bridge thêm 4 tool, gỡ 2 tool chết; CLI `cmd/kg-packs`.

**Tech Stack:** Go 1.25 (stdlib `net/http`, `database/sql`, `log/slog`, `gopkg.in/yaml.v3` — đã có trong go.mod), golang-migrate, PostgreSQL 16, `github.com/lib/pq`. Không thêm dependency (go.mod không có SQL parser ⇒ tokenizer allow-list tự viết, `internal/intel/sqllex.go`).

**Spec:** `docs/superpowers/specs/2026-09-25-industry-pack-proactive-intelligence-design.md` (rev 4) — §2.4 I6–I9, I11; §3 D1, D4–D8, D11; §5; §6; §12a; §12b; §13.
**Master:** `docs/superpowers/plans/2026-10-02-proactive-intelligence-master.md` — §2.1–2.4 (khoá, bản cập nhật có `as_of`), Global Constraints (As-of date, Giá vốn Rx, targets.xlsx, thứ tự migration), §4 M4.

> Toàn bộ code trong plan này đã được dựng và chạy trên một bản copy `ennam.kg.go` + Postgres 16 dùng một lần (2026-10-02): `go build ./...`, `go vet`, `go test -race` các package mới + `internal/bridge` đều xanh, 0 SKIP; 31 metric (trừ `retail.cash_shortage_count` thêm sau, đã kiểm trên fixture) chạy được trên `pharmacy_demo` thật (read-only, backfill 3 tháng ≈ 5 giây) và khớp ground truth (PH-004 claim rejection 15,47%; refund trùng; 40 cặp reprint-trước-refund).

## Global Constraints

Kế thừa toàn bộ Global Constraints của master. Bổ sung cho plan này:

- **Không đổi hợp đồng khoá** (master §2.1–2.4): DDL 000088–000091 đúng master (thêm bảng `project_intel_settings` trong 000088 theo yêu cầu điều phối); JSON 4 tool đúng §2.4 (có `as_of`); `data_status.subject` chỉ `entity:<name>` | `metric:<key>` (runner) | `file:<dataset>` (Plan C, helper `intel.FileSubject`); header metric chỉ các key §2.2. Mọi bổ sung ngoài khoá được liệt kê ở **Open questions** để sửa master trước khi merge.
- Core (`internal/intel/**` trừ `_test.go`/`testdata`, `internal/handler/intel_metrics.go`, `cmd/kg-packs`, `cmd/kg-server/intel_wiring.go`) **không chứa từ ngữ ngành** — chạy `./scripts/check-core-vocabulary.sh` (master M3) ở Task 18.
- SQL tới DB khách chỉ qua `service.SourceExecutor` (session read-only, guard `SELECT`/`WITH`, timeout 30s). Compiler luôn quote định danh; biểu thức mapping chỉ qua `intel.ValidateExpr`; pack SQL chỉ được đọc entity trong `requires` hoặc CTE tự định nghĩa (`intel.CheckRelations`) — không bao giờ chạm bảng thật của khách bằng tên.
- `Truncated=true` ⇒ chunk đó **không ghi**; runner tự chia đôi cửa sổ tới 1 ngày; vẫn cắt ⇒ `data_status=blocked` (issue `row_limit`).
- Tham số pack `:from`/`:to` luôn bind thành `CAST($n AS date)`; `:dim_<d>` thành `CAST($n AS text)`.
- `value` của metric `ratio` chỉ tính bằng `engine.RatioValue` (×100 chỉ khi `unit: percent`), dùng cả lúc ghi lẫn lúc gộp kỳ.
- `dims_hash` = sha256 hex của `json.Marshal(map[string]string)` (encoding/json sắp key); dim NULL lưu là `""`.
- **As-of** = ngày dữ liệu cuối cùng, **bao gồm** (master): `project_intel_settings.as_of_override` nếu có (demo `2026-07-31`), ngược lại hôm qua theo múi giờ project. Cửa sổ lookback kết thúc ở `as_of + 1` (không gồm); nhãn độ tươi tính theo `as_of`, không theo đồng hồ; `to` mặc định của `kg_get_metrics` = `as_of + 1`. Slot chạy hằng ngày của scheduler theo đồng hồ thật.
- **Envelope lỗi:** mọi lỗi do 4 route intel tự trả (400/403/500/503) là `{error:{code,message}}`; **ngoại lệ**: 401 do middleware Auth trả trước khi tới handler vẫn là body cũ `{"error":"Unauthorized","message","status_code"}` — provider LAAM xử lý `error` không phải object theo status (401 ⇒ `unauthorized`, 403 ⇒ `forbidden`).
- **`dims_filter`** nêu dim mà metric không có ⇒ 400 `invalid_request` (master §2.4 ghi "bỏ qua" — bỏ qua âm thầm có thể nới phạm vi chi nhánh; mọi metric pack đều có `location_id`). Cần sửa câu này ở master.
- Test DB: `KG_TEST_DATABASE_URL` trỏ DB dev **cổng 5433**; mọi lệnh test DB chạy `-v` và **kiểm tra không có dòng `--- SKIP`** (lệnh mẫu in số dòng SKIP, phải là 0).
- Migration DB dev: `KG_DB_PORT=5433 go run ./cmd/kg-migrate/ up` (không dùng `make db-migrate` — mặc định 5432 là container khác).
- Commit Go: `git -C ennam.kg.go …`; `packs/` commit ở repo workspace.

## Review Focus

1. **Backfill vượt giới hạn dòng bị cắt âm thầm** — Task 9 `TestRunner_TruncatedChunkSplitsThenBlocks` + `TestRunner_TruncatedAtOneDayWritesNothing`.
2. **Dữ liệu đến muộn không cập nhật ngày gốc** (đơn đổi trạng thái sau vài ngày; tổ hợp dims biến mất) — Task 9 `TestRunner_LookbackReplacesWindow`.
3. **Biểu thức mapping / pack SQL độc hại** (`; DROP`, subquery, comment, hàm lạ, đọc bảng ngoài `requires`) — Task 4 `TestValidateExpr_Rejects`, Task 2 `TestLoadRegistry_Rejects` (đọc bảng ngoài `requires`, comma join, `JOIN LATERAL`, join trong ngoặc, `TABLE` trong CTE và trong `IN`), Task 14 `TestImportMapping_ValidatesAgainstSyncedSchema`.
4. **Gộp tỉ lệ sai / lọc chi nhánh sau khi đọc** — Task 11 `TestQuery_RatioAggregatesSums` + `TestQuery_DimsFilterInSQLAndGrain` + `TestQuery_EvidencePagingAndBranchScope`.
5. **Số tool bridge lệch / tool chết còn trong schema** — Task 13 `TestListToolNames`, `TestRouteClassCounts`, `TestAllToolSchemasRegistered` (54 route = 29 read + 25 write; 57 schema; `kg_get_context`, `kg_get_impact_analysis` đã gỡ).

## Phụ thuộc với plan khác

| Plan | Phụ thuộc task nào của plan này | Nội dung |
|---|---|---|
| **M1** (master) | — (plan này cần M1 trước Task 15) | `packs/retail/pack.yaml`, `packs/pharmacy/pack.yaml`, mount `/packs` + `PACKS_DIR` vào `kg-server` |
| **A** (demo data) | Task 16–17 cần `prescriptions.acquisition_cost`, `employees.hourly_wage`, movement `RECEIPT` (Plan A thêm); Task 19 chạy sau Plan A | Nếu Plan A chưa xong: `import-mapping` **thất bại rõ ràng** ở entity `prescription`/`labor_rate` (đúng thiết kế, không ghi gì) |
| **C** (tabular upload) | **Task 3** (interface), **Task 7** (`sqlexec.New`), **Task 6** (`intelstore.Store.UpsertDataStatus`), **Task 10** (`intel.RunTrigger`), **Task 12** (`buildIntel` — chỗ đăng ký resolver `intel.ModeFile`), **Task 2** (`(*intel.Registry).CanonicalEntity`) | Xem mục **Exports cho Plan C** |
| **D** (LAAM engine) | Task 13 (tên tool + route), master §2.4, Task 15–16 (metric key) | Hợp đồng metric ở `2026-10-02-pi-D-laam-engine.md` §"Hợp đồng metric cần từ Plan B" — xem mục **Sai khác so với Plan D** |
| **M4** | Task 14 (`kg-packs` `import-mapping` / `install` / `set-as-of` / `run-metrics`), Task 17 (mapping.yaml) | Trong container: `docker exec daab-server go run ./cmd/kg-packs …` (image dev có Go toolchain) |

## Exports cho Plan C (tên cuối cùng — Plan C dùng đúng các tên này)

Plan C đã giả định tên khác (`internal/intel/source`, `FromClause/ColumnExpr/Mode`, `(*Runner).TriggerProject`, biến `metricRunner`). Tên chốt là:

```go
import "github.com/ennam/ennam-kg/internal/intel"

// Plan C hiện thực cho mode=file (vd. package internal/intel/filesource):
type SourceTable interface {
    Relation() string          // SQL sau FROM, PHẢI tự gắn alias "src": `file_dataset_row AS src`
    Filter() string            // điều kiện WHERE không có chữ WHERE: `src.dataset_id = '<uuid>'` ("" = không lọc)
    RefLabel() string          // nhãn _source_ref, vd tên dataset
    Columns() []intel.SourceColumn          // {Name, DataType} các cột mapping được phép dùng
    ColumnSQL(name string) string           // vd `CAST(src.data->>'store_id' AS text)` theo kiểu cột của dataset
}
type SourceResolver interface {
    Prepare(ctx context.Context, projectID string, ms []intel.Mapping) error   // file: return nil
    Bind(ctx context.Context, projectID string, m intel.Mapping) (*intel.BoundSource, error)
}
type BoundSource struct { Table SourceTable; Executor QueryExecutor; Watermark string }
type QueryExecutor interface { Query(ctx context.Context, sql string, args []any, maxRows int) (*intel.QueryRows, error) }
var ErrSourceNotReady error   // Bind trả lỗi này khi dataset chưa upload ⇒ entity "incomplete", không "broken"
type MappingError struct{ Entity, Code, Detail string } // Bind trả khi cột/bảng không khớp ⇒ mapping "broken"
type RunTrigger interface { Trigger(projectID string) } // *engine.Scheduler hiện thực; gọi sau upload (bất đồng bộ)
```

- Executor cho `mode=file`: `sqlexec.New(db, 30*time.Second)` (package `internal/intel/sqlexec`, chạy trong `ennam_kg`, transaction READ ONLY) — **không** qua `source_executor`.
- Biểu thức field của mapping `mode=file` là tên cột trần (validator chấp nhận vì có trong `Columns()`); compiler tự `CAST(... AS <kiểu canonical>)`.
- Đăng ký: trong `cmd/kg-server/intel_wiring.go` (`buildIntel`, Task 12) thêm `resolvers[intel.ModeFile] = <resolver của C>`; scheduler trả về từ `buildIntel` (biến `intelScheduler` trong `main.go`) là `intel.RunTrigger` để truyền vào đường upload.
- Ghi data status kết quả validate upload: `(*intelstore.Store).UpsertDataStatus(ctx, intel.DataStatus{Subject: intel.FileSubject("<dataset>"), …})` ⇒ subject `file:<dataset>` (master §2.3). Subject `entity:target` do runner ghi khi bind/validate entity.
- Canonical: `(*intel.Registry).CanonicalEntity("target")` → `*intel.Entity{Fields []intel.Field{Name, Type, Key, Required}}`. Entity `target` (pack `retail`): `location_id` text required, `metric_key` text required (enum `[net_sales, gross_margin_pct]`), `period` **date** required, `value` numeric required, **không có key** (`_source_ref` = NULL trừ khi C thêm). Khớp hợp đồng `targets.xlsx` (`Store ID | Metric Key | Period | Target Value`, `Period` = ngày đầu tháng, % là 0–100).
- `import-mapping` không yêu cầu dataset `mode=file` tồn tại (chỉ kiểm tra entity có trong pack). Plan C thêm block `target:` (mode `file`, `file_dataset: store_targets`) vào `packs/_projects/pharmacy-chain/mapping.yaml`.
- Thứ tự migration: 000092 (C) chỉ chạy sau 000088–000091.

## File Structure

| File | Trách nhiệm |
|---|---|
| `ennam.kg.go/db/migrations/000088_pack_install.{up,down}.sql` | `pack_install` + `project_intel_settings` (as-of, timezone) |
| `ennam.kg.go/db/migrations/000089_project_mapping.{up,down}.sql` | `project_mapping` (master §2.3) |
| `ennam.kg.go/db/migrations/000090_metric_value.{up,down}.sql` | `metric_value` + index |
| `ennam.kg.go/db/migrations/000091_data_status.{up,down}.sql` | `data_status` |
| `internal/intel/types.go` | Kiểu lõi: SourceMode, FieldType, Aggregation, Grain, Field/Entity, MetricDef, EvidenceDef, Mapping, DataStatus, Issue |
| `internal/intel/sqllex.go` | Lexer SQL tối thiểu (string, quoted ident, comment, `:param`, `::`), chuẩn hoá một câu lệnh |
| `internal/intel/header.go` | Parse header metric/evidence, kiểm tra tham số, `CheckRelations` |
| `internal/intel/pack.go` | Loader `PACKS_DIR`, merge `extends`, `Catalog`, `CanonicalEntity` |
| `internal/intel/source.go` | Interface nguồn (Plan C hiện thực `mode=file`), lỗi chuẩn, `RunTrigger` |
| `internal/intel/dialect.go` | `Dialect` + `Postgres` |
| `internal/intel/expr.go` | Validator biểu thức mapping (allow-list) + rewrite cột |
| `internal/intel/compile.go` | CTE theo entity, metric/evidence statement, SQL kiểm tra enum/NULL/độ tươi |
| `internal/intel/mapping_file.go` | Định dạng YAML seed mapping |
| `internal/intel/testdata/packs/**` | Pack mẫu trung tính (`base`, `child`) cho unit test |
| `internal/intel/intelstore/store.go` | SQL 5 bảng mới + truy vấn gộp kỳ |
| `internal/intel/sqlexec/sqlexec.go` | Executor READ ONLY trong DB DAAB |
| `internal/intel/livesource/live.go` | Resolver `mode=live` (metadata đã sync + `SourceExecutor`) |
| `internal/intel/engine/values.go` | `RatioValue`, `DimsHash`, parse kết quả metric |
| `internal/intel/engine/availability.go` | Router nguồn, metric bật/tắt, timezone, business today, bind entity |
| `internal/intel/engine/runner.go, lock.go` | Metric runner + advisory lock |
| `internal/intel/engine/scheduler.go` | Worker ticker hằng ngày + `Trigger` |
| `internal/intel/engine/query.go` | Logic 4 tool |
| `internal/intel/packtest/fixture_test.go` | Test mọi metric pack thật trên fixture tính tay |
| `internal/service/source_executor.go (sửa)` | `ExecuteWithLimit` (giới hạn dòng riêng); `Execute` giữ nguyên hành vi |
| `internal/handler/intel_metrics.go` | 4 endpoint HTTP, envelope lỗi `{error:{code,message}}` |
| `cmd/kg-server/intel_wiring.go + main.go (sửa)` | Wiring + start/stop scheduler |
| `internal/bridge/client.go, schema.go (sửa) + 5 file test` | +4 tool, −2 tool chết, cập nhật mọi assert số lượng |
| `internal/config/types.go (sửa comment)` | Bỏ tham chiếu tool đã gỡ |
| `cmd/kg-packs/main.go` | CLI `import-mapping`, `install`, `set-as-of`, `run-metrics` |
| `Makefile (sửa)` | build `bin/kg-packs` |
| `packs/retail/daab/{canonical.yaml,metrics/*.sql,evidence/*.sql}` | 26 metric retail + evidence |
| `packs/pharmacy/daab/{canonical.yaml,metrics/*.sql,evidence/*.sql}` | 6 metric pharmacy + evidence |
| `packs/_projects/pharmacy-chain/mapping.yaml` | Mapping `pharmacy_demo` → canonical |

Đường dẫn `internal/…`, `cmd/…`, `db/…` dưới đây đều tương đối với `ennam.kg.go/`; `packs/…` tương đối với gốc workspace.

### Task 1: Migrations 000088–000091

**Files:** Create `db/migrations/000088_pack_install.up.sql`, `000088_pack_install.down.sql`, `000089_project_mapping.{up,down}.sql`, `000090_metric_value.{up,down}.sql`, `000091_data_status.{up,down}.sql`.

**Interfaces:** Consumes: bảng `projects`, `data_sources` (000002, 000016). Produces: 5 bảng — DDL 4 bảng đúng master §2.3; `project_intel_settings(project_id PK, as_of_override date, timezone text, updated_at)` bổ sung theo yêu cầu điều phối (master Global Constraints "As-of date").

- [ ] **Step 1: Kiểm tra trạng thái trước (failing check)**
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -Atc "SELECT version FROM schema_migrations; SELECT to_regclass('pack_install');"
```
Expected: `87` và dòng rỗng (bảng chưa có).

- [ ] **Step 2: Tạo 8 file migration**

`db/migrations/000088_pack_install.up.sql`:
```sql
-- Industry packs enabled per project (spec §5.3, master §2.3). DAAB is the
-- source of truth for which packs are on; LAAM reads it via kg_list_metrics.
CREATE TABLE pack_install (
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pack_key   TEXT NOT NULL,
  version    TEXT NOT NULL,
  enabled    BOOLEAN NOT NULL DEFAULT TRUE,
  installed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, pack_key)
);

-- Per-project metrics settings. as_of_override pins the as-of date — the last data
-- day, inclusive — used by analysis windows and freshness (demo data stops on
-- 2026-07-31; master Global Constraints "As-of date"); timezone overrides the
-- business timezone.
CREATE TABLE project_intel_settings (
  project_id     UUID PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  as_of_override DATE,
  timezone       TEXT,
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`db/migrations/000088_pack_install.down.sql`:
```sql
DROP TABLE IF EXISTS project_intel_settings;
DROP TABLE IF EXISTS pack_install;
```

`db/migrations/000089_project_mapping.up.sql`:
```sql
-- Per-project mapping of customer tables/columns to canonical entities
-- (spec §6.3, master §2.3). Only status = 'approved' rows are executed.
CREATE TABLE project_mapping (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  entity TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('live','file')),
  data_source_id UUID REFERENCES data_sources(id),
  file_dataset TEXT,                      -- mode=file: tên dataset logic (Plan C)
  spec JSONB NOT NULL,                    -- {from, fields:{canonical: expr}, enum_map?}
  status TEXT NOT NULL CHECK (status IN ('proposed','approved','broken')),
  version INT NOT NULL DEFAULT 1,
  approved_by TEXT, approved_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, entity)
);
```

`db/migrations/000089_project_mapping.down.sql`:
```sql
DROP TABLE IF EXISTS project_mapping;
```

`db/migrations/000090_metric_value.up.sql`:
```sql
-- Daily metric series computed by the metric runner (spec §6.4, master §2.3).
CREATE TABLE metric_value (
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  metric_key TEXT NOT NULL,
  period_date DATE NOT NULL,
  dims JSONB NOT NULL DEFAULT '{}',
  dims_hash TEXT NOT NULL,                -- sha256 hex của JSON dims đã sắp key
  value NUMERIC, numerator NUMERIC, denominator NUMERIC,
  sample_size INT NOT NULL,
  metric_version INT NOT NULL, pack_version TEXT NOT NULL,
  source_mode TEXT NOT NULL CHECK (source_mode IN ('live','file','landed')),
  source_watermark TEXT,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, metric_key, period_date, dims_hash)
);
CREATE INDEX metric_value_lookup ON metric_value (project_id, metric_key, period_date);
```

`db/migrations/000090_metric_value.down.sql`:
```sql
DROP TABLE IF EXISTS metric_value;
```

`db/migrations/000091_data_status.up.sql`:
```sql
-- Freshness / completeness per entity and metric (spec §6.6, master §2.3).
CREATE TABLE data_status (
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  subject TEXT NOT NULL,                  -- 'entity:<name>' | 'metric:<key>'
  status TEXT NOT NULL CHECK (status IN ('current','delayed','incomplete','stale','blocked')),
  last_success_at TIMESTAMPTZ,
  period_from DATE, period_to DATE,
  issues JSONB NOT NULL DEFAULT '[]',     -- [{code, message, detail}]
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, subject)
);
```

`db/migrations/000091_data_status.down.sql`:
```sql
DROP TABLE IF EXISTS data_status;
```

- [ ] **Step 3: Chạy up → down → up trên DB dev (5433)**
```bash
cd ennam.kg.go
KG_DB_PORT=5433 go run ./cmd/kg-migrate/ up && KG_DB_PORT=5433 go run ./cmd/kg-migrate/ steps -4 && KG_DB_PORT=5433 go run ./cmd/kg-migrate/ up
KG_DB_PORT=5433 go run ./cmd/kg-migrate/ version
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -c "\d project_intel_settings"
```
Expected: `Version: 91, Dirty: false`; bảng có cột `as_of_override date`, `timezone text`.

- [ ] **Step 4: Commit**
```bash
git -C ennam.kg.go add db/migrations/000088_pack_install.up.sql db/migrations/000088_pack_install.down.sql db/migrations/000089_project_mapping.up.sql db/migrations/000089_project_mapping.down.sql db/migrations/000090_metric_value.up.sql db/migrations/000090_metric_value.down.sql db/migrations/000091_data_status.up.sql db/migrations/000091_data_status.down.sql
git -C ennam.kg.go commit -m "feat(intel): add pack, mapping, metric and data-status tables" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 2: Pack model + loader (`PACKS_DIR`, extends, semver, header metric, evidence)

**Files:** Create `internal/intel/types.go`, `internal/intel/sqllex.go`, `internal/intel/header.go`, `internal/intel/pack.go`, `internal/intel/pack_test.go`, `internal/intel/testdata/packs/base/{pack.yaml,daab/canonical.yaml,daab/metrics/order_total.sql,daab/metrics/open_count.sql,daab/evidence/order_total.sql}`, `internal/intel/testdata/packs/child/{pack.yaml,daab/canonical.yaml,daab/metrics/closed_share.sql}`.

**Interfaces:**
- Produces: `func LoadRegistry(dir string) (*Registry, error)`; `func (r *Registry) Effective(keys []string) (*Catalog, error)`; `func (r *Registry) CanonicalEntity(name string) (*Entity, bool)`; `func (c *Catalog) MetricKeys() []string`; `func ParseMetricSQL(file, src string) (*MetricDef, error)`; `func ParseEvidenceSQL(file, src string, dims []string) (*EvidenceDef, error)`; `func CheckRelations(body string, requires []string) error`; kiểu `Registry, Pack, Catalog, PackRef{Key, Version}, Entity, Field, MetricDef, EvidenceDef, Mapping, MappingSpec, DataStatus, Issue`, hằng `ModeLive/ModeFile/ModeLanded`, `Status*`, `Mapping*`, `func EntitySubject(string) string`, `func MetricSubject(string) string`.
- Consumes: `gopkg.in/yaml.v3`.

- [ ] **Step 1: Viết testdata + test (failing)**

`internal/intel/testdata/packs/base/pack.yaml`:
```yaml
key: base
version: 0.1.0
display_name: Base
```

`internal/intel/testdata/packs/base/daab/canonical.yaml`:
```yaml
entities:
  location:
    fields:
      location_id: { type: text, key: true }
      timezone:    { type: text }
  order:
    fields:
      order_id:    { type: text, key: true }
      location_id: { type: text, required: true }
      ordered_at:  { type: timestamp, required: true }
      amount:      { type: numeric }
      status:      { type: text }
enums:
  order.status: [open, closed]
```

`internal/intel/testdata/packs/base/daab/metrics/order_total.sql`:
```sql
-- key: base.order_total
-- version: 2
-- grain: day
-- dims: [location_id]
-- unit: currency
-- aggregation: additive        -- gộp kỳ = SUM(value)
-- sample_size: number of orders
-- requires: [order]
-- Free text explanation line that is ignored.
SELECT location_id,
       CAST(ordered_at AS date) AS period_date,
       SUM(amount)              AS value,
       COUNT(*)                 AS sample_size
FROM "order"
WHERE ordered_at >= :from AND ordered_at < :to AND status = 'closed'
GROUP BY 1, 2;
```

`internal/intel/testdata/packs/base/daab/metrics/open_count.sql`:
```sql
-- key: base.open_count
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: count
-- aggregation: snapshot
-- sample_size: number of orders
-- requires: [order]
SELECT location_id, CAST(ordered_at AS date) AS period_date,
       COUNT(*) FILTER (WHERE status = 'open') AS value, COUNT(*) AS sample_size
FROM "order"
WHERE ordered_at >= :from AND ordered_at < :to
GROUP BY 1, 2
```

`internal/intel/testdata/packs/base/daab/evidence/order_total.sql`:
```sql
-- key: base.order_total
SELECT order_id, ordered_at, amount, _source_ref
FROM "order"
WHERE ordered_at >= :from AND ordered_at < :to AND (:dim_location_id IS NULL OR location_id = :dim_location_id)
ORDER BY ordered_at, order_id
```

`internal/intel/testdata/packs/child/pack.yaml`:
```yaml
key: child
version: 1.2.3
extends: [base]
display_name: Child
```

`internal/intel/testdata/packs/child/daab/canonical.yaml`:
```yaml
entities:
  order:
    extend: true
    fields:
      channel: { type: text }
```

`internal/intel/testdata/packs/child/daab/metrics/closed_share.sql`:
```sql
-- key: child.closed_share
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: number of orders
-- requires: [order]
-- lookback_days: 3
WITH o AS (SELECT * FROM "order" WHERE ordered_at >= :from AND ordered_at < :to)
SELECT location_id, CAST(ordered_at AS date) AS period_date,
       COUNT(*) FILTER (WHERE status = 'closed') AS numerator,
       COUNT(*) AS denominator, COUNT(*) AS sample_size
FROM o GROUP BY 1, 2
```

`internal/intel/pack_test.go`:
```go
package intel

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadRegistry_MergesExtends(t *testing.T) {
	reg, err := LoadRegistry("testdata/packs")
	if err != nil {
		t.Fatalf("LoadRegistry: %v", err)
	}
	if len(reg.Packs) != 2 {
		t.Fatalf("packs = %d, want 2 (_projects must be skipped)", len(reg.Packs))
	}
	cat, err := reg.Effective([]string{"child"})
	if err != nil {
		t.Fatalf("Effective: %v", err)
	}
	if len(cat.Packs) != 2 || cat.Packs[0].Key != "base" || cat.Packs[1].Key != "child" {
		t.Fatalf("packs order = %+v, want base then child", cat.Packs)
	}
	order := cat.Entities["order"]
	if order == nil || len(order.Fields) != 6 || order.Fields[5].Name != "channel" {
		t.Fatalf("order fields = %+v, want 5 parent fields + channel", order)
	}
	m := cat.Metrics["base.order_total"]
	if m == nil || m.Version != 2 || m.Aggregation != AggAdditive || m.LookbackDays != 7 || m.PackVersion != "0.1.0" {
		t.Fatalf("order_total = %+v", m)
	}
	if strings.HasSuffix(strings.TrimSpace(m.Body), ";") || strings.HasPrefix(m.Body, "--") {
		t.Fatalf("body must drop header comments and trailing ';': %q", m.Body)
	}
	if cs := cat.Metrics["child.closed_share"]; cs == nil || cs.LookbackDays != 3 || cs.Unit != "percent" {
		t.Fatalf("closed_share = %+v", cs)
	}
	if cat.Evidence["base.order_total"] == nil {
		t.Fatal("evidence for base.order_total not loaded")
	}
}

func TestRegistry_CanonicalEntity(t *testing.T) {
	reg, err := LoadRegistry("testdata/packs")
	if err != nil {
		t.Fatal(err)
	}
	e, ok := reg.CanonicalEntity("order")
	if !ok || len(e.Fields) != 6 {
		t.Fatalf("order = %+v %v (want parent + child fields)", e, ok)
	}
	if f, _ := e.Field("location_id"); !f.Required || f.Type != TypeText {
		t.Fatalf("location_id = %+v", f)
	}
	if _, ok := reg.CanonicalEntity("ghost"); ok {
		t.Fatal("unknown entity must not be found")
	}
}

func writePack(t *testing.T, root, key, packYAML, canonical string, metrics map[string]string) {
	t.Helper()
	dir := filepath.Join(root, key)
	must := func(err error) {
		if err != nil {
			t.Fatal(err)
		}
	}
	must(os.MkdirAll(filepath.Join(dir, "daab", "metrics"), 0o755))
	must(os.WriteFile(filepath.Join(dir, "pack.yaml"), []byte(packYAML), 0o644))
	if canonical != "" {
		must(os.WriteFile(filepath.Join(dir, "daab", "canonical.yaml"), []byte(canonical), 0o644))
	}
	for name, sql := range metrics {
		must(os.WriteFile(filepath.Join(dir, "daab", "metrics", name+".sql"), []byte(sql), 0o644))
	}
}

const okCanonical = "entities:\n  thing:\n    fields:\n      thing_id: { type: text, key: true }\n"

func TestLoadRegistry_Rejects(t *testing.T) {
	cases := []struct {
		name, packYAML, canonical string
		metrics                   map[string]string
		want                      string
	}{
		{"bad semver", "key: p\nversion: 1.0\n", okCanonical, nil, "not semver"},
		{"unknown parent", "key: p\nversion: 0.1.0\nextends: [nope]\n", okCanonical, nil, "unknown pack"},
		{"bad field type", "key: p\nversion: 0.1.0\n", "entities:\n  thing:\n    fields:\n      x: { type: money }\n", nil, "not allowed"},
		{"metric key mismatch", "key: p\nversion: 0.1.0\n", okCanonical, map[string]string{"m": "-- key: p.other\n-- version: 1\n-- grain: day\n-- dims: []\n-- unit: count\n-- aggregation: additive\n-- sample_size: n\n-- requires: [thing]\nSELECT 1"}, "declares key"},
		{"missing header", "key: p\nversion: 0.1.0\n", okCanonical, map[string]string{"m": "-- key: p.m\nSELECT 1"}, "missing header"},
		{"unknown param", "key: p\nversion: 0.1.0\n", okCanonical, map[string]string{"m": "-- key: p.m\n-- version: 1\n-- grain: day\n-- dims: []\n-- unit: count\n-- aggregation: additive\n-- sample_size: n\n-- requires: [thing]\nSELECT :since"}, "not allowed"},
		{"two statements", "key: p\nversion: 0.1.0\n", okCanonical, map[string]string{"m": "-- key: p.m\n-- version: 1\n-- grain: day\n-- dims: []\n-- unit: count\n-- aggregation: additive\n-- sample_size: n\n-- requires: [thing]\nSELECT 1; SELECT 2"}, "single statement"},
		{"reads table outside requires", "key: p\nversion: 0.1.0\n", okCanonical, map[string]string{"m": "-- key: p.m\n-- version: 1\n-- grain: day\n-- dims: []\n-- unit: count\n-- aggregation: additive\n-- sample_size: n\n-- requires: [thing]\nSELECT 1 FROM thing JOIN orders o ON true"}, "neither a required entity"},
		{"schema-qualified relation", "key: p\nversion: 0.1.0\n", okCanonical, map[string]string{"m": "-- key: p.m\n-- version: 1\n-- grain: day\n-- dims: []\n-- unit: count\n-- aggregation: additive\n-- sample_size: n\n-- requires: [thing]\nSELECT 1 FROM public.thing"}, "schema-qualified"},
		{"comma join outside requires", "key: p\nversion: 0.1.0\n", okCanonical, map[string]string{"m": "-- key: p.m\n-- version: 1\n-- grain: day\n-- dims: []\n-- unit: count\n-- aggregation: additive\n-- sample_size: n\n-- requires: [thing]\nSELECT 1 FROM thing t, customers c"}, "neither a required entity"},
		{"lateral outside requires", "key: p\nversion: 0.1.0\n", okCanonical, map[string]string{"m": "-- key: p.m\n-- version: 1\n-- grain: day\n-- dims: []\n-- unit: count\n-- aggregation: additive\n-- sample_size: n\n-- requires: [thing]\nSELECT 1 FROM thing t JOIN LATERAL customers c ON true"}, "neither a required entity"},
		{"parenthesised join", "key: p\nversion: 0.1.0\n", okCanonical, map[string]string{"m": "-- key: p.m\n-- version: 1\n-- grain: day\n-- dims: []\n-- unit: count\n-- aggregation: additive\n-- sample_size: n\n-- requires: [thing]\nSELECT 1 FROM (customers c JOIN thing t ON true)"}, "neither a required entity"},
		{"TABLE in CTE", "key: p\nversion: 0.1.0\n", okCanonical, map[string]string{"m": "-- key: p.m\n-- version: 1\n-- grain: day\n-- dims: []\n-- unit: count\n-- aggregation: additive\n-- sample_size: n\n-- requires: [thing]\nWITH x AS (TABLE customers) SELECT 1 FROM x"}, "TABLE"},
		{"TABLE in IN list", "key: p\nversion: 0.1.0\n", okCanonical, map[string]string{"m": "-- key: p.m\n-- version: 1\n-- grain: day\n-- dims: []\n-- unit: count\n-- aggregation: additive\n-- sample_size: n\n-- requires: [thing]\nSELECT 1 FROM thing WHERE thing_id IN (TABLE customers)"}, "TABLE"},
		{"unknown required entity", "key: p\nversion: 0.1.0\n", okCanonical, map[string]string{"m": "-- key: p.m\n-- version: 1\n-- grain: day\n-- dims: []\n-- unit: count\n-- aggregation: additive\n-- sample_size: n\n-- requires: [ghost]\nSELECT 1"}, "unknown entity"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			root := t.TempDir()
			writePack(t, root, "p", tc.packYAML, tc.canonical, tc.metrics)
			_, err := LoadRegistry(root)
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("err = %v, want containing %q", err, tc.want)
			}
		})
	}
}

func TestCheckRelations_AllowsPackShapes(t *testing.T) {
	ok := []string{
		"SELECT 1 FROM thing t LEFT JOIN thing u ON true WHERE t.thing_id = u.thing_id",
		"WITH x AS (SELECT * FROM thing) SELECT * FROM x, thing t",
		"SELECT * FROM thing t JOIN LATERAL (SELECT 1 FROM thing) l ON true",
		"SELECT EXTRACT(EPOCH FROM ts) FROM thing GROUP BY 1",
		"SELECT * FROM (SELECT * FROM thing) s ORDER BY 1",
	}
	for _, q := range ok {
		if err := CheckRelations(q, []string{"thing"}); err != nil {
			t.Errorf("%q rejected: %v", q, err)
		}
	}
}

func TestParseEvidenceSQL_RequiresOrderByAndNoLimit(t *testing.T) {
	if _, err := ParseEvidenceSQL("e.sql", "-- key: p.m\nSELECT a FROM t", nil); err == nil || !strings.Contains(err.Error(), "ORDER BY") {
		t.Fatalf("missing ORDER BY not rejected: %v", err)
	}
	if _, err := ParseEvidenceSQL("e.sql", "-- key: p.m\nSELECT a FROM t ORDER BY a LIMIT 5", nil); err == nil || !strings.Contains(err.Error(), "LIMIT") {
		t.Fatalf("LIMIT not rejected: %v", err)
	}
	if _, err := ParseEvidenceSQL("e.sql", "-- key: p.m\nSELECT a FROM t WHERE x = :dim_store ORDER BY a", []string{"location_id"}); err == nil {
		t.Fatal(":dim_store must be rejected when the metric has no dim store")
	}
	if _, err := ParseEvidenceSQL("e.sql", "-- key: p.m\nSELECT a FROM t WHERE x = :dim_location_id ORDER BY a", []string{"location_id"}); err != nil {
		t.Fatalf("valid evidence rejected: %v", err)
	}
}
```

- [ ] **Step 2: Chạy test — phải FAIL**
```bash
cd ennam.kg.go && go test -count=1 ./internal/intel/
```
Expected: FAIL — `undefined: LoadRegistry` (package chưa có code).

- [ ] **Step 3: Implement**

`internal/intel/types.go`:
```go
// Package intel is the industry-neutral core of the metrics layer: pack model and
// loader, mapping expression validation, SQL dialect, parameter binding and the
// compiler that turns a project mapping + pack metric SQL into one read-only
// statement. It has no database dependency; storage lives in intel/intelstore and
// execution in intel/engine.
//
// Industry vocabulary must never appear in this package (spec D10): every
// industry word lives in packs/ YAML and SQL only.
package intel

import "time"

// SourceMode is where an entity's rows physically live (spec D4).
type SourceMode string

const (
	ModeLive   SourceMode = "live"
	ModeFile   SourceMode = "file"
	ModeLanded SourceMode = "landed"
)

// FieldType is a canonical field type (master §2.2).
type FieldType string

const (
	TypeText      FieldType = "text"
	TypeNumeric   FieldType = "numeric"
	TypeInteger   FieldType = "integer"
	TypeBoolean   FieldType = "boolean"
	TypeDate      FieldType = "date"
	TypeTimestamp FieldType = "timestamp"
)

// Valid reports whether t is one of the six allowed canonical types.
func (t FieldType) Valid() bool {
	switch t {
	case TypeText, TypeNumeric, TypeInteger, TypeBoolean, TypeDate, TypeTimestamp:
		return true
	}
	return false
}

// Aggregation says how daily values roll up into longer periods (spec §6.4).
type Aggregation string

const (
	AggAdditive Aggregation = "additive"
	AggRatio    Aggregation = "ratio"
	AggSnapshot Aggregation = "snapshot"
)

// Grain is the period of one stored metric row.
type Grain string

const (
	GrainDay   Grain = "day"
	GrainMonth Grain = "month"
)

// Field is one canonical field of an entity.
type Field struct {
	Name     string
	Type     FieldType
	Key      bool
	Required bool
}

// Entity is a canonical entity after extends-merging.
type Entity struct {
	Name   string
	Fields []Field // declaration order: parent fields first, then extensions
}

// Field returns the named field.
func (e *Entity) Field(name string) (Field, bool) {
	for _, f := range e.Fields {
		if f.Name == name {
			return f, true
		}
	}
	return Field{}, false
}

// KeyField returns the field flagged key: true, if any.
func (e *Entity) KeyField() (Field, bool) {
	for _, f := range e.Fields {
		if f.Key {
			return f, true
		}
	}
	return Field{}, false
}

// MetricDef is one parsed daab/metrics/<name>.sql file.
type MetricDef struct {
	Key          string
	Pack         string // owning pack key
	PackVersion  string
	Version      int
	Grain        Grain
	Dims         []string
	Unit         string
	Aggregation  Aggregation
	SampleSize   string // human description of what sample_size counts
	Requires     []string
	LookbackDays int
	Body         string // SQL with the header comments removed and one trailing ';' stripped
	File         string
}

// EvidenceDef is one parsed daab/evidence/<name>.sql file.
type EvidenceDef struct {
	MetricKey string
	Body      string
	File      string
}

// Mapping is one approved/proposed row of project_mapping.
type Mapping struct {
	ID           string
	ProjectID    string
	Entity       string
	Mode         SourceMode
	DataSourceID string // mode=live
	FileDataset  string // mode=file (Plan C)
	Spec         MappingSpec
	Status       string // proposed | approved | broken
	Version      int
	UpdatedAt    time.Time
}

// MappingSpec is the JSONB stored in project_mapping.spec (master §2.3).
type MappingSpec struct {
	From    string                       `json:"from" yaml:"from"`
	Fields  map[string]string            `json:"fields" yaml:"fields"`
	EnumMap map[string]map[string]string `json:"enum_map,omitempty" yaml:"enum_map,omitempty"`
}

// LocationKey identifies the physical database an entity lives in. Entities with
// different keys can never be joined in one statement (spec §6.3).
func (m Mapping) LocationKey() string {
	switch m.Mode {
	case ModeLive:
		return "live:" + m.DataSourceID
	default:
		return string(m.Mode) + ":" + m.ProjectID
	}
}

// Mapping statuses.
const (
	MappingProposed = "proposed"
	MappingApproved = "approved"
	MappingBroken   = "broken"
)

// Data status values (spec §6.6).
const (
	StatusCurrent    = "current"
	StatusDelayed    = "delayed"
	StatusIncomplete = "incomplete"
	StatusStale      = "stale"
	StatusBlocked    = "blocked"
)

// Issue is one entry of data_status.issues.
type Issue struct {
	Code    string `json:"code"`
	Message string `json:"message"`
	Detail  any    `json:"detail,omitempty"`
}

// DataStatus is one row of data_status.
type DataStatus struct {
	ProjectID     string
	Subject       string // entity:<name> | metric:<key> | file:<dataset>
	Status        string
	LastSuccessAt *time.Time
	PeriodFrom    *time.Time
	PeriodTo      *time.Time
	Issues        []Issue
	UpdatedAt     time.Time
}

// EntitySubject / MetricSubject / FileSubject build data_status subjects
// (master §2.3: entity:<name> | metric:<key> written by the runner, file:<dataset>
// written by the tabular-upload validation of Plan C).
func EntitySubject(entity string) string { return "entity:" + entity }
func MetricSubject(key string) string    { return "metric:" + key }
func FileSubject(dataset string) string  { return "file:" + dataset }
```

`internal/intel/sqllex.go`:
```go
package intel

import (
	"fmt"
	"strings"
)

// tokKind classifies a lexical token of the small SQL subset the intel layer
// needs to understand (pack SQL and mapping expressions).
type tokKind int

const (
	tokIdent     tokKind = iota // bare identifier or keyword
	tokQuoted                   // "quoted identifier"
	tokNumber                   // 12, 1.5
	tokString                   // 'literal' (Text holds the raw source incl. quotes)
	tokParam                    // :name (Text holds ":name"; see paramName)
	tokCast                     // ::
	tokOp                       // = <> != < > <= >= + - * / % ||
	tokLParen                   // (
	tokRParen                   // )
	tokComma                    // ,
	tokSemicolon                // ;
	tokDot                      // .
	tokComment                  // -- … or /* … */ (Text holds raw source)
	tokSpace                    // whitespace run
	tokOther                    // anything else ($, \, [, ] …)
)

type token struct {
	Kind tokKind
	Text string
}

// lexSQL splits src into tokens, preserving every byte (concatenating Text of all
// tokens reproduces src). Unterminated strings, quoted identifiers or block
// comments are errors.
func lexSQL(src string) ([]token, error) {
	var out []token
	i := 0
	n := len(src)
	for i < n {
		c := src[i]
		switch {
		case c == ' ' || c == '\t' || c == '\n' || c == '\r':
			j := i
			for j < n && (src[j] == ' ' || src[j] == '\t' || src[j] == '\n' || src[j] == '\r') {
				j++
			}
			out = append(out, token{tokSpace, src[i:j]})
			i = j
		case c == '-' && i+1 < n && src[i+1] == '-':
			j := strings.IndexByte(src[i:], '\n')
			if j < 0 {
				j = n
			} else {
				j += i
			}
			out = append(out, token{tokComment, src[i:j]})
			i = j
		case c == '/' && i+1 < n && src[i+1] == '*':
			j := strings.Index(src[i+2:], "*/")
			if j < 0 {
				return nil, fmt.Errorf("unterminated block comment")
			}
			end := i + 2 + j + 2
			out = append(out, token{tokComment, src[i:end]})
			i = end
		case c == '\'':
			j := i + 1
			for {
				if j >= n {
					return nil, fmt.Errorf("unterminated string literal")
				}
				if src[j] == '\'' {
					if j+1 < n && src[j+1] == '\'' {
						j += 2
						continue
					}
					break
				}
				j++
			}
			out = append(out, token{tokString, src[i : j+1]})
			i = j + 1
		case c == '"':
			j := strings.IndexByte(src[i+1:], '"')
			if j < 0 {
				return nil, fmt.Errorf("unterminated quoted identifier")
			}
			end := i + 1 + j + 1
			out = append(out, token{tokQuoted, src[i:end]})
			i = end
		case c == ':' && i+1 < n && src[i+1] == ':':
			out = append(out, token{tokCast, "::"})
			i += 2
		case c == ':' && i+1 < n && isIdentStart(src[i+1]):
			j := i + 1
			for j < n && isIdentPart(src[j]) {
				j++
			}
			out = append(out, token{tokParam, src[i:j]})
			i = j
		case isIdentStart(c):
			j := i
			for j < n && isIdentPart(src[j]) {
				j++
			}
			out = append(out, token{tokIdent, src[i:j]})
			i = j
		case c >= '0' && c <= '9':
			j := i
			for j < n && ((src[j] >= '0' && src[j] <= '9') || src[j] == '.') {
				j++
			}
			out = append(out, token{tokNumber, src[i:j]})
			i = j
		case c == '(':
			out = append(out, token{tokLParen, "("})
			i++
		case c == ')':
			out = append(out, token{tokRParen, ")"})
			i++
		case c == ',':
			out = append(out, token{tokComma, ","})
			i++
		case c == ';':
			out = append(out, token{tokSemicolon, ";"})
			i++
		case c == '.':
			out = append(out, token{tokDot, "."})
			i++
		case strings.ContainsRune("=<>!+-*/%|", rune(c)):
			j := i + 1
			if j < n {
				two := src[i : j+1]
				switch two {
				case "<>", "!=", "<=", ">=", "||":
					j++
				}
			}
			op := src[i:j]
			if op == "!" || op == "|" {
				out = append(out, token{tokOther, op})
			} else {
				out = append(out, token{tokOp, op})
			}
			i = j
		default:
			out = append(out, token{tokOther, string(c)})
			i++
		}
	}
	return out, nil
}

// paramName returns the name of a tokParam token without the leading ':'.
func paramName(t token) string { return t.Text[1:] }

func isIdentStart(c byte) bool {
	return c == '_' || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
}

func isIdentPart(c byte) bool {
	return isIdentStart(c) || (c >= '0' && c <= '9')
}

// significant drops whitespace and comment tokens.
func significant(toks []token) []token {
	out := make([]token, 0, len(toks))
	for _, t := range toks {
		if t.Kind != tokSpace && t.Kind != tokComment {
			out = append(out, t)
		}
	}
	return out
}

// normalizeStatement strips leading comments/whitespace and exactly one trailing
// ';'. Any other ';' is rejected: pack SQL is always a single statement.
func normalizeStatement(src string) (string, []token, error) {
	toks, err := lexSQL(src)
	if err != nil {
		return "", nil, err
	}
	start := 0
	for start < len(toks) && (toks[start].Kind == tokSpace || toks[start].Kind == tokComment) {
		start++
	}
	end := len(toks)
	for end > start && (toks[end-1].Kind == tokSpace || toks[end-1].Kind == tokComment) {
		end--
	}
	if end > start && toks[end-1].Kind == tokSemicolon {
		end--
		for end > start && (toks[end-1].Kind == tokSpace || toks[end-1].Kind == tokComment) {
			end--
		}
	}
	body := toks[start:end]
	for _, t := range body {
		if t.Kind == tokSemicolon {
			return "", nil, fmt.Errorf("statement contains ';' — only a single statement is allowed")
		}
	}
	var sb strings.Builder
	for _, t := range body {
		sb.WriteString(t.Text)
	}
	return sb.String(), body, nil
}
```

`internal/intel/header.go`:
```go
package intel

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

var headerLine = regexp.MustCompile(`^--\s*([a-z_]+)\s*:\s*(.*)$`)

// metricHeaderKeys are the only header keys master §2.2 defines.
var metricHeaderKeys = map[string]bool{
	"key": true, "version": true, "grain": true, "dims": true, "unit": true,
	"aggregation": true, "sample_size": true, "requires": true, "lookback_days": true,
}

var allowedUnits = map[string]bool{
	"currency": true, "percent": true, "count": true, "hours": true, "days": true, "ratio": true,
}

// parseHeader reads the leading run of `--` comment lines of a pack SQL file and
// returns the recognised `key: value` pairs. Comment lines with unknown keys or
// free text (explanations) are ignored. A value may carry a trailing `-- …`
// comment, which is dropped.
func parseHeader(src string) map[string]string {
	out := map[string]string{}
	for _, raw := range strings.Split(src, "\n") {
		line := strings.TrimSpace(raw)
		if line == "" {
			continue
		}
		if !strings.HasPrefix(line, "--") {
			break
		}
		m := headerLine.FindStringSubmatch(line)
		if m == nil || !metricHeaderKeys[m[1]] {
			continue
		}
		val := m[2]
		if i := strings.Index(val, "--"); i >= 0 {
			val = val[:i]
		}
		out[m[1]] = strings.TrimSpace(val)
	}
	return out
}

// parseList parses "[a, b]" (or "[]") into its items.
func parseList(v string) ([]string, error) {
	v = strings.TrimSpace(v)
	if !strings.HasPrefix(v, "[") || !strings.HasSuffix(v, "]") {
		return nil, fmt.Errorf("expected [a, b] list, got %q", v)
	}
	inner := strings.TrimSpace(v[1 : len(v)-1])
	if inner == "" {
		return []string{}, nil
	}
	parts := strings.Split(inner, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if !identRe.MatchString(p) {
			return nil, fmt.Errorf("invalid list item %q", p)
		}
		out = append(out, p)
	}
	return out, nil
}

var identRe = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)

// ParseMetricSQL parses one daab/metrics/<name>.sql file (master §2.2).
func ParseMetricSQL(file, src string) (*MetricDef, error) {
	h := parseHeader(src)
	for _, k := range []string{"key", "version", "grain", "dims", "unit", "aggregation", "sample_size", "requires"} {
		if _, ok := h[k]; !ok {
			return nil, fmt.Errorf("%s: missing header %q", file, k)
		}
	}
	def := &MetricDef{Key: h["key"], Unit: h["unit"], SampleSize: h["sample_size"], File: file, LookbackDays: 7}
	var err error
	if def.Version, err = strconv.Atoi(h["version"]); err != nil || def.Version < 1 {
		return nil, fmt.Errorf("%s: version must be a positive integer", file)
	}
	def.Grain = Grain(h["grain"])
	if def.Grain != GrainDay && def.Grain != GrainMonth {
		return nil, fmt.Errorf("%s: grain must be day|month", file)
	}
	def.Aggregation = Aggregation(h["aggregation"])
	if def.Aggregation != AggAdditive && def.Aggregation != AggRatio && def.Aggregation != AggSnapshot {
		return nil, fmt.Errorf("%s: aggregation must be additive|ratio|snapshot", file)
	}
	if !allowedUnits[def.Unit] {
		return nil, fmt.Errorf("%s: unit %q not allowed", file, def.Unit)
	}
	if def.Dims, err = parseList(h["dims"]); err != nil {
		return nil, fmt.Errorf("%s: dims: %w", file, err)
	}
	if def.Requires, err = parseList(h["requires"]); err != nil {
		return nil, fmt.Errorf("%s: requires: %w", file, err)
	}
	if len(def.Requires) == 0 {
		return nil, fmt.Errorf("%s: requires must list at least one entity", file)
	}
	if v, ok := h["lookback_days"]; ok {
		if def.LookbackDays, err = strconv.Atoi(v); err != nil || def.LookbackDays < 0 {
			return nil, fmt.Errorf("%s: lookback_days must be a non-negative integer", file)
		}
	}
	body, toks, err := normalizeStatement(src)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", file, err)
	}
	if err := checkParams(toks, map[string]bool{"from": true, "to": true}); err != nil {
		return nil, fmt.Errorf("%s: %w", file, err)
	}
	if err := CheckRelations(body, def.Requires); err != nil {
		return nil, fmt.Errorf("%s: %w", file, err)
	}
	def.Body = body
	return def, nil
}

// ParseEvidenceSQL parses one daab/evidence/<name>.sql file. dims are the dims of
// the metric it belongs to: only :from, :to and :dim_<dim> are allowed. The body
// must contain ORDER BY and must not contain LIMIT/OFFSET (the engine appends them).
func ParseEvidenceSQL(file, src string, dims []string) (*EvidenceDef, error) {
	h := parseHeader(src)
	key, ok := h["key"]
	if !ok {
		return nil, fmt.Errorf("%s: missing header \"key\"", file)
	}
	body, toks, err := normalizeStatement(src)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", file, err)
	}
	allowed := map[string]bool{"from": true, "to": true}
	for _, d := range dims {
		allowed["dim_"+d] = true
	}
	if err := checkParams(toks, allowed); err != nil {
		return nil, fmt.Errorf("%s: %w", file, err)
	}
	sig := significant(toks)
	hasOrderBy := false
	for i, t := range sig {
		if t.Kind != tokIdent {
			continue
		}
		up := strings.ToUpper(t.Text)
		if up == "LIMIT" || up == "OFFSET" || up == "FETCH" {
			return nil, fmt.Errorf("%s: evidence SQL must not contain %s (the engine appends LIMIT/OFFSET)", file, up)
		}
		if up == "ORDER" && i+1 < len(sig) && strings.EqualFold(sig[i+1].Text, "BY") {
			hasOrderBy = true
		}
	}
	if !hasOrderBy {
		return nil, fmt.Errorf("%s: evidence SQL must have ORDER BY", file)
	}
	return &EvidenceDef{MetricKey: key, Body: body, File: file}, nil
}

// fromInsideFunc lists functions whose argument syntax uses FROM (not a relation).
var fromInsideFunc = map[string]bool{"EXTRACT": true, "SUBSTRING": true, "TRIM": true, "OVERLAY": true, "POSITION": true}

// notAlias are keywords that can follow a relation and therefore are not an alias.
var notAlias = map[string]bool{
	"WHERE": true, "JOIN": true, "INNER": true, "LEFT": true, "RIGHT": true, "FULL": true, "CROSS": true,
	"NATURAL": true, "OUTER": true, "ON": true, "USING": true, "GROUP": true, "ORDER": true, "HAVING": true,
	"WINDOW": true, "UNION": true, "INTERSECT": true, "EXCEPT": true, "LIMIT": true, "OFFSET": true,
	"FETCH": true, "LATERAL": true, "TABLESAMPLE": true,
}

// CheckRelations ensures every relation the statement reads — after FROM or JOIN,
// in comma-separated FROM lists, after LATERAL, inside parenthesised joins — is
// one of the required canonical entities or a CTE the statement defines itself,
// and is never schema-qualified. The bare TABLE command is rejected. Pack SQL
// must not reach a physical table of the customer database by name: only the
// compiled entity CTEs are visible to it.
func CheckRelations(body string, requires []string) error {
	toks, err := lexSQL(body)
	if err != nil {
		return err
	}
	sig := significant(toks)
	ok := map[string]bool{}
	for _, r := range requires {
		ok[r] = true
	}
	for i := 0; i+2 < len(sig); i++ {
		if (sig[i].Kind == tokIdent || sig[i].Kind == tokQuoted) && strings.EqualFold(sig[i+1].Text, "AS") && sig[i+2].Kind == tokLParen {
			ok[identName(sig[i])] = true
		}
	}
	for _, t := range sig {
		if t.Kind == tokIdent && strings.EqualFold(t.Text, "TABLE") {
			return fmt.Errorf("the TABLE command is not allowed")
		}
	}
	var parens []bool // true = '(' opened by a function whose syntax uses FROM
	for i := 0; i < len(sig); i++ {
		t := sig[i]
		switch t.Kind {
		case tokLParen:
			parens = append(parens, i > 0 && sig[i-1].Kind == tokIdent && fromInsideFunc[strings.ToUpper(sig[i-1].Text)])
			continue
		case tokRParen:
			if len(parens) > 0 {
				parens = parens[:len(parens)-1]
			}
			continue
		case tokIdent:
		default:
			continue
		}
		up := strings.ToUpper(t.Text)
		if up != "FROM" && up != "JOIN" {
			continue
		}
		if up == "FROM" && len(parens) > 0 && parens[len(parens)-1] {
			continue
		}
		if _, err := checkFromItems(sig, i+1, ok); err != nil {
			return err
		}
	}
	return nil
}

// checkFromItems validates the FROM item starting at sig[j] and, through commas,
// every following item of the same list. It returns the index after the list.
func checkFromItems(sig []token, j int, ok map[string]bool) (int, error) {
	for {
		if j >= len(sig) {
			return j, fmt.Errorf("FROM/JOIN without relation")
		}
		if sig[j].Kind == tokIdent && strings.EqualFold(sig[j].Text, "LATERAL") {
			j++
			continue
		}
		break
	}
	switch sig[j].Kind {
	case tokLParen:
		end := matchParen(sig, j)
		if end < 0 {
			return j, fmt.Errorf("unbalanced parentheses")
		}
		k := j
		for k < end && sig[k].Kind == tokLParen {
			k++
		}
		first := strings.ToUpper(sig[k].Text)
		if sig[k].Kind != tokIdent || (first != "SELECT" && first != "WITH" && first != "VALUES") {
			// parenthesised join: its first relation is checked here, the joined
			// ones by the JOIN scan of CheckRelations.
			if _, err := checkFromItems(sig, j+1, ok); err != nil {
				return j, err
			}
		}
		j = end + 1
	case tokIdent, tokQuoted:
		name := identName(sig[j])
		if j+1 < len(sig) && sig[j+1].Kind == tokDot {
			return j, fmt.Errorf("schema-qualified relation %s is not allowed", name)
		}
		if !ok[name] {
			return j, fmt.Errorf("relation %q is neither a required entity nor a CTE of the statement", name)
		}
		j++
	default:
		return j, fmt.Errorf("unexpected token %q after FROM/JOIN", sig[j].Text)
	}
	// optional alias and column list
	if j < len(sig) && sig[j].Kind == tokIdent && strings.EqualFold(sig[j].Text, "AS") {
		j++
	}
	if j < len(sig) && (sig[j].Kind == tokQuoted || (sig[j].Kind == tokIdent && !notAlias[strings.ToUpper(sig[j].Text)])) {
		j++
		if j < len(sig) && sig[j].Kind == tokLParen {
			if end := matchParen(sig, j); end > 0 {
				j = end + 1
			}
		}
	}
	if j < len(sig) && sig[j].Kind == tokComma {
		return checkFromItems(sig, j+1, ok)
	}
	return j, nil
}

func matchParen(sig []token, open int) int {
	depth := 0
	for k := open; k < len(sig); k++ {
		switch sig[k].Kind {
		case tokLParen:
			depth++
		case tokRParen:
			depth--
			if depth == 0 {
				return k
			}
		}
	}
	return -1
}

func identName(t token) string {
	if t.Kind == tokQuoted {
		return strings.ReplaceAll(t.Text[1:len(t.Text)-1], `""`, `"`)
	}
	return strings.ToLower(t.Text)
}

func checkParams(toks []token, allowed map[string]bool) error {
	for _, t := range toks {
		if t.Kind == tokParam && !allowed[paramName(t)] {
			return fmt.Errorf("parameter %s is not allowed", t.Text)
		}
	}
	return nil
}
```

`internal/intel/pack.go`:
```go
package intel

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"
)

var (
	packKeyRe = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)
	semverRe  = regexp.MustCompile(`^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`)
)

// Pack is one loaded pack directory (its own files only; see Registry.Effective
// for the extends-merged view).
type Pack struct {
	Key         string
	Version     string
	DisplayName string
	Extends     []string
	Dir         string
	Entities    map[string]*packEntity
	Enums       map[string][]string
	Metrics     map[string]*MetricDef
	Evidence    map[string]*EvidenceDef // by metric key
}

type packEntity struct {
	Extend bool
	Fields []Field
}

// Registry holds every pack found under PACKS_DIR.
type Registry struct {
	Dir   string
	Packs map[string]*Pack
}

type packYAML struct {
	Key         string   `yaml:"key"`
	Version     string   `yaml:"version"`
	Extends     []string `yaml:"extends"`
	DisplayName string   `yaml:"display_name"`
}

type canonicalYAML struct {
	Entities map[string]struct {
		Extend bool      `yaml:"extend"`
		Fields yaml.Node `yaml:"fields"`
	} `yaml:"entities"`
	Enums map[string][]string `yaml:"enums"`
}

type fieldYAML struct {
	Type     string `yaml:"type"`
	Key      bool   `yaml:"key"`
	Required bool   `yaml:"required"`
}

// LoadRegistry loads every pack directory under dir (directories whose name starts
// with '_' or '.' are skipped — they hold project files, not packs) and validates
// the whole set: keys, semver, extends graph, canonical merge, metric headers,
// evidence pairing.
func LoadRegistry(dir string) (*Registry, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("packs: read %s: %w", dir, err)
	}
	reg := &Registry{Dir: dir, Packs: map[string]*Pack{}}
	for _, e := range entries {
		if !e.IsDir() || strings.HasPrefix(e.Name(), "_") || strings.HasPrefix(e.Name(), ".") {
			continue
		}
		p, err := loadPack(filepath.Join(dir, e.Name()))
		if err != nil {
			return nil, err
		}
		if p.Key != e.Name() {
			return nil, fmt.Errorf("packs: directory %q declares key %q (must match)", e.Name(), p.Key)
		}
		reg.Packs[p.Key] = p
	}
	for _, p := range reg.Packs {
		if _, err := reg.Effective([]string{p.Key}); err != nil {
			return nil, err
		}
	}
	return reg, nil
}

func loadPack(dir string) (*Pack, error) {
	raw, err := os.ReadFile(filepath.Join(dir, "pack.yaml"))
	if err != nil {
		return nil, fmt.Errorf("packs: %w", err)
	}
	var py packYAML
	if err := yaml.Unmarshal(raw, &py); err != nil {
		return nil, fmt.Errorf("packs: %s/pack.yaml: %w", dir, err)
	}
	if !packKeyRe.MatchString(py.Key) {
		return nil, fmt.Errorf("packs: %s: invalid key %q", dir, py.Key)
	}
	if !semverRe.MatchString(py.Version) {
		return nil, fmt.Errorf("packs: %s: version %q is not semver", py.Key, py.Version)
	}
	p := &Pack{
		Key: py.Key, Version: py.Version, DisplayName: py.DisplayName, Extends: py.Extends, Dir: dir,
		Entities: map[string]*packEntity{}, Enums: map[string][]string{},
		Metrics: map[string]*MetricDef{}, Evidence: map[string]*EvidenceDef{},
	}
	if err := p.loadCanonical(filepath.Join(dir, "daab", "canonical.yaml")); err != nil {
		return nil, err
	}
	metricFiles, _ := filepath.Glob(filepath.Join(dir, "daab", "metrics", "*.sql"))
	sort.Strings(metricFiles)
	byName := map[string]*MetricDef{}
	for _, f := range metricFiles {
		src, err := os.ReadFile(f)
		if err != nil {
			return nil, fmt.Errorf("packs: %w", err)
		}
		def, err := ParseMetricSQL(filepath.Base(f), string(src))
		if err != nil {
			return nil, fmt.Errorf("packs: %s: %w", p.Key, err)
		}
		name := strings.TrimSuffix(filepath.Base(f), ".sql")
		if def.Key != p.Key+"."+name {
			return nil, fmt.Errorf("packs: %s: metric file %s declares key %q, want %q", p.Key, filepath.Base(f), def.Key, p.Key+"."+name)
		}
		def.Pack, def.PackVersion = p.Key, p.Version
		p.Metrics[def.Key] = def
		byName[name] = def
	}
	evidenceFiles, _ := filepath.Glob(filepath.Join(dir, "daab", "evidence", "*.sql"))
	sort.Strings(evidenceFiles)
	for _, f := range evidenceFiles {
		name := strings.TrimSuffix(filepath.Base(f), ".sql")
		m, ok := byName[name]
		if !ok {
			return nil, fmt.Errorf("packs: %s: evidence %s has no metric with the same name", p.Key, filepath.Base(f))
		}
		src, err := os.ReadFile(f)
		if err != nil {
			return nil, fmt.Errorf("packs: %w", err)
		}
		ev, err := ParseEvidenceSQL(filepath.Base(f), string(src), m.Dims)
		if err != nil {
			return nil, fmt.Errorf("packs: %s: %w", p.Key, err)
		}
		if ev.MetricKey != m.Key {
			return nil, fmt.Errorf("packs: %s: evidence %s declares key %q, want %q", p.Key, filepath.Base(f), ev.MetricKey, m.Key)
		}
		if err := CheckRelations(ev.Body, m.Requires); err != nil {
			return nil, fmt.Errorf("packs: %s: %s: %w", p.Key, filepath.Base(f), err)
		}
		p.Evidence[m.Key] = ev
	}
	return p, nil
}

func (p *Pack) loadCanonical(path string) error {
	raw, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("packs: %w", err)
	}
	var cy canonicalYAML
	if err := yaml.Unmarshal(raw, &cy); err != nil {
		return fmt.Errorf("packs: %s/daab/canonical.yaml: %w", p.Key, err)
	}
	for name, ent := range cy.Entities {
		if !identRe.MatchString(name) {
			return fmt.Errorf("packs: %s: invalid entity name %q", p.Key, name)
		}
		fields, err := decodeFields(ent.Fields)
		if err != nil {
			return fmt.Errorf("packs: %s: entity %s: %w", p.Key, name, err)
		}
		p.Entities[name] = &packEntity{Extend: ent.Extend, Fields: fields}
	}
	for k, vals := range cy.Enums {
		p.Enums[k] = vals
	}
	return nil
}

// decodeFields keeps YAML declaration order (a mapping node is ordered).
func decodeFields(n yaml.Node) ([]Field, error) {
	if n.Kind != yaml.MappingNode {
		return nil, fmt.Errorf("fields must be a mapping")
	}
	var out []Field
	for i := 0; i+1 < len(n.Content); i += 2 {
		name := n.Content[i].Value
		if !identRe.MatchString(name) || strings.HasPrefix(name, "_") {
			return nil, fmt.Errorf("invalid field name %q", name)
		}
		var fy fieldYAML
		if err := n.Content[i+1].Decode(&fy); err != nil {
			return nil, fmt.Errorf("field %s: %w", name, err)
		}
		ft := FieldType(fy.Type)
		if !ft.Valid() {
			return nil, fmt.Errorf("field %s: type %q not allowed", name, fy.Type)
		}
		out = append(out, Field{Name: name, Type: ft, Key: fy.Key, Required: fy.Required})
	}
	return out, nil
}

// PackRef is a pack key + version, as reported by kg_list_metrics.
type PackRef struct {
	Key     string `json:"key"`
	Version string `json:"version"`
}

// Catalog is the extends-merged view of a set of packs.
type Catalog struct {
	Packs    []PackRef
	Entities map[string]*Entity
	Enums    map[string][]string // "<entity>.<field>" -> allowed canonical values
	Metrics  map[string]*MetricDef
	Evidence map[string]*EvidenceDef
}

// MetricKeys returns the metric keys sorted.
func (c *Catalog) MetricKeys() []string {
	keys := make([]string, 0, len(c.Metrics))
	for k := range c.Metrics {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// Effective returns the merged catalog for the given pack keys plus all their
// ancestors (extends closure). Parents are merged before children.
func (r *Registry) Effective(keys []string) (*Catalog, error) {
	order, err := r.closure(keys)
	if err != nil {
		return nil, err
	}
	c := &Catalog{Entities: map[string]*Entity{}, Enums: map[string][]string{},
		Metrics: map[string]*MetricDef{}, Evidence: map[string]*EvidenceDef{}}
	for _, key := range order {
		p := r.Packs[key]
		c.Packs = append(c.Packs, PackRef{Key: p.Key, Version: p.Version})
		names := make([]string, 0, len(p.Entities))
		for n := range p.Entities {
			names = append(names, n)
		}
		sort.Strings(names)
		for _, name := range names {
			pe := p.Entities[name]
			existing, ok := c.Entities[name]
			switch {
			case pe.Extend && !ok:
				return nil, fmt.Errorf("packs: %s extends entity %q that no parent pack defines", p.Key, name)
			case !pe.Extend && ok:
				return nil, fmt.Errorf("packs: %s redefines entity %q (use extend: true)", p.Key, name)
			case !ok:
				c.Entities[name] = &Entity{Name: name, Fields: append([]Field(nil), pe.Fields...)}
			default:
				for _, f := range pe.Fields {
					if _, dup := existing.Field(f.Name); dup {
						return nil, fmt.Errorf("packs: %s redefines field %s.%s", p.Key, name, f.Name)
					}
					if f.Key {
						return nil, fmt.Errorf("packs: %s: extension field %s.%s cannot be a key", p.Key, name, f.Name)
					}
					existing.Fields = append(existing.Fields, f)
				}
			}
		}
		for k, v := range p.Enums {
			c.Enums[k] = v
		}
		for k, m := range p.Metrics {
			c.Metrics[k] = m
		}
		for k, e := range p.Evidence {
			c.Evidence[k] = e
		}
	}
	for k := range c.Enums {
		ent, field, ok := strings.Cut(k, ".")
		if !ok {
			return nil, fmt.Errorf("packs: enum key %q must be <entity>.<field>", k)
		}
		e, okE := c.Entities[ent]
		if !okE {
			return nil, fmt.Errorf("packs: enum %q references unknown entity", k)
		}
		if f, okF := e.Field(field); !okF || f.Type != TypeText {
			return nil, fmt.Errorf("packs: enum %q must reference a text field", k)
		}
	}
	for _, m := range c.Metrics {
		for _, req := range m.Requires {
			if _, ok := c.Entities[req]; !ok {
				return nil, fmt.Errorf("packs: metric %s requires unknown entity %q", m.Key, req)
			}
		}
	}
	return c, nil
}

// CanonicalEntity returns the extends-merged definition of a canonical entity as
// declared by any loaded pack (used by the tabular-upload path, Plan C, to validate
// a file against the entity's fields: Field{Name, Type, Key, Required}).
func (r *Registry) CanonicalEntity(name string) (*Entity, bool) {
	keys := make([]string, 0, len(r.Packs))
	for k := range r.Packs {
		keys = append(keys, k)
	}
	cat, err := r.Effective(keys)
	if err != nil {
		return nil, false
	}
	e, ok := cat.Entities[name]
	return e, ok
}

// closure returns keys plus ancestors in parent-first order; detects cycles.
func (r *Registry) closure(keys []string) ([]string, error) {
	var order []string
	state := map[string]int{} // 1 visiting, 2 done
	var visit func(k string) error
	visit = func(k string) error {
		switch state[k] {
		case 1:
			return fmt.Errorf("packs: extends cycle at %q", k)
		case 2:
			return nil
		}
		p, ok := r.Packs[k]
		if !ok {
			return fmt.Errorf("packs: unknown pack %q", k)
		}
		state[k] = 1
		parents := append([]string(nil), p.Extends...)
		sort.Strings(parents)
		for _, parent := range parents {
			if err := visit(parent); err != nil {
				return err
			}
		}
		state[k] = 2
		order = append(order, k)
		return nil
	}
	sorted := append([]string(nil), keys...)
	sort.Strings(sorted)
	for _, k := range sorted {
		if err := visit(k); err != nil {
			return nil, err
		}
	}
	return order, nil
}
```

- [ ] **Step 4: Chạy test — PASS**
```bash
cd ennam.kg.go && go test -count=1 ./internal/intel/
```
Expected: `ok  github.com/ennam/ennam-kg/internal/intel`

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.go add internal/intel/types.go internal/intel/sqllex.go internal/intel/header.go internal/intel/pack.go internal/intel/pack_test.go internal/intel/testdata
git -C ennam.kg.go commit -m "feat(intel): industry pack model and loader" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 3: Interface nguồn + dialect (Plan C phụ thuộc task này)

**Files:** Create `internal/intel/source.go`, `internal/intel/dialect.go`, `internal/intel/dialect_test.go`.

**Interfaces:** Produces đúng như mục **Exports cho Plan C**: `SourceColumn`, `SourceTable`, `QueryRows`, `QueryExecutor`, `BoundSource`, `SourceResolver`, `ErrSourceNotReady`, `MappingError`, `RunTrigger`; `type Dialect interface{ QuoteIdent; QuoteLiteral; Placeholder(int); TypeName(FieldType); LocalTimestamp(expr, tz string); LimitOffset(l, o string) }`, `type Postgres struct{}`. Consumes: `Mapping` (Task 2).

- [ ] **Step 1: Viết test (failing)**
`internal/intel/dialect_test.go`:
```go
package intel

import (
	"errors"
	"fmt"
	"testing"
)

func TestPostgresDialect(t *testing.T) {
	d := Postgres{}
	cases := map[string]string{
		d.QuoteIdent(`we"ird`):                     `"we""ird"`,
		d.QuoteLiteral("it's"):                     `'it''s'`,
		d.Placeholder(3):                           `$3`,
		d.TypeName(TypeInteger):                    `bigint`,
		d.TypeName(TypeText):                       `text`,
		d.LocalTimestamp(`src."ts"`, "Asia/Tokyo"): `(src."ts" AT TIME ZONE 'Asia/Tokyo')`,
		d.LimitOffset("$4", "$5"):                  ` LIMIT $4 OFFSET $5`,
	}
	for got, want := range cases {
		if got != want {
			t.Errorf("got %s, want %s", got, want)
		}
	}
}

func TestMappingLocationKeyAndErrors(t *testing.T) {
	live := Mapping{ProjectID: "p", Mode: ModeLive, DataSourceID: "ds1"}
	file := Mapping{ProjectID: "p", Mode: ModeFile, FileDataset: "targets"}
	if live.LocationKey() != "live:ds1" || file.LocationKey() != "file:p" {
		t.Fatalf("keys = %s %s", live.LocationKey(), file.LocationKey())
	}
	if EntitySubject("sale") != "entity:sale" || MetricSubject("a.b") != "metric:a.b" || FileSubject("store_targets") != "file:store_targets" {
		t.Fatal("data_status subjects must follow master §2.3")
	}
	wrapped := fmt.Errorf("bind: %w", ErrSourceNotReady)
	if !errors.Is(wrapped, ErrSourceNotReady) {
		t.Fatal("ErrSourceNotReady must survive wrapping")
	}
	var me *MappingError
	if !errors.As(fmt.Errorf("x: %w", &MappingError{Entity: "e", Code: "missing_table"}), &me) || me.Code != "missing_table" {
		t.Fatal("MappingError must be matchable with errors.As")
	}
}
```

- [ ] **Step 2: Chạy — FAIL**
```bash
cd ennam.kg.go && go test -count=1 -run 'TestPostgresDialect|TestMappingLocationKeyAndErrors' ./internal/intel/
```
Expected: FAIL — `undefined: Postgres`, `undefined: ErrSourceNotReady`.

- [ ] **Step 3: Implement**
`internal/intel/source.go`:
```go
package intel

import (
	"context"
	"errors"
	"fmt"
)

// SourceColumn is one physical column a mapping may reference.
type SourceColumn struct {
	Name     string // physical column name as the source reports it
	DataType string // lower-case source type, e.g. "numeric", "timestamp without time zone"
}

// SourceTable is the physical relation behind one canonical entity, as the
// compiler sees it. Implementations: livesource (mode=live, this plan) and the
// file-dataset resolver (mode=file, Plan C).
type SourceTable interface {
	// Relation is the SQL placed after FROM in the entity CTE. It MUST expose the
	// alias "src" (e.g. `"public"."orders" AS src` or
	// `file_dataset_row AS src`) and contain no user-supplied text unquoted.
	Relation() string
	// Filter is an optional SQL boolean placed in the CTE WHERE clause (no
	// "WHERE" keyword), e.g. `src.dataset_id = '<uuid>'`. Empty means no filter.
	Filter() string
	// RefLabel is the label used in `_source_ref` ('<label>:' || key).
	RefLabel() string
	// Columns lists the columns a mapping expression may reference.
	Columns() []SourceColumn
	// ColumnSQL returns the SQL expression reading one column returned by
	// Columns(), e.g. `src."claim_status"` or `(src.data->>'claim_status')`.
	ColumnSQL(name string) string
}

// QueryRows is the result of one compiled statement.
type QueryRows struct {
	Columns   []string
	Rows      [][]any // values as returned by the driver (see engine.parse* helpers)
	Truncated bool    // more than maxRows rows existed; Rows holds the first maxRows
}

// QueryExecutor runs one compiled read-only statement where the data lives.
type QueryExecutor interface {
	Query(ctx context.Context, sql string, args []any, maxRows int) (*QueryRows, error)
}

// BoundSource is a mapping resolved to its physical relation and executor.
type BoundSource struct {
	Table     SourceTable
	Executor  QueryExecutor
	Watermark string // opaque freshness marker stored in metric_value.source_watermark ("" = none)
}

// SourceResolver binds mappings of one SourceMode.
type SourceResolver interface {
	// Prepare runs once per metric run before any Bind (live: refresh the synced
	// schema of every data source used by ms — spec I11). A failure means the
	// source is unreachable; the runner marks the entities delayed/stale.
	Prepare(ctx context.Context, projectID string, ms []Mapping) error
	// Bind resolves one mapping. It returns *MappingError when the mapping no
	// longer matches the source (missing table/column ⇒ mapping broken) and
	// ErrSourceNotReady when the source has no data yet (e.g. file not uploaded).
	Bind(ctx context.Context, projectID string, m Mapping) (*BoundSource, error)
}

// ErrSourceNotReady means the source exists in configuration but has no data yet.
var ErrSourceNotReady = errors.New("source not ready")

// MappingError means a mapping does not fit its source (spec §6.1: schema drift ⇒ broken).
type MappingError struct {
	Entity string
	Code   string // missing_table | missing_column | invalid_expression | missing_required_field | invalid_spec
	Detail string
}

func (e *MappingError) Error() string {
	return fmt.Sprintf("mapping %s: %s: %s", e.Entity, e.Code, e.Detail)
}

// RunTrigger asks the metric runner to recompute a project soon (asynchronously).
// Plan C calls it after a tabular upload; the scheduler implements it.
type RunTrigger interface {
	Trigger(projectID string)
}
```

`internal/intel/dialect.go`:
```go
package intel

import (
	"fmt"
	"strings"
)

// Dialect isolates the SQL that differs between source databases (spec §12b).
// Beta implements Postgres only; MSSQL/MySQL add an implementation later.
type Dialect interface {
	QuoteIdent(name string) string
	QuoteLiteral(s string) string
	// Placeholder returns the positional parameter for 1-based index n.
	Placeholder(n int) string
	// TypeName maps a canonical type to the dialect's cast target.
	TypeName(t FieldType) string
	// LocalTimestamp converts a timezone-aware timestamp expression to local
	// wall-clock time in tz (an IANA name already validated by the caller).
	LocalTimestamp(expr, tz string) string
	// LimitOffset renders the paging suffix appended to evidence SQL.
	LimitOffset(limitPlaceholder, offsetPlaceholder string) string
}

// Postgres is the beta dialect.
type Postgres struct{}

func (Postgres) QuoteIdent(name string) string {
	return `"` + strings.ReplaceAll(name, `"`, `""`) + `"`
}

func (Postgres) QuoteLiteral(s string) string {
	return "'" + strings.ReplaceAll(s, "'", "''") + "'"
}

func (Postgres) Placeholder(n int) string { return fmt.Sprintf("$%d", n) }

func (Postgres) TypeName(t FieldType) string {
	switch t {
	case TypeNumeric:
		return "numeric"
	case TypeInteger:
		return "bigint"
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

func (p Postgres) LocalTimestamp(expr, tz string) string {
	return "(" + expr + " AT TIME ZONE " + p.QuoteLiteral(tz) + ")"
}

func (Postgres) LimitOffset(l, o string) string { return " LIMIT " + l + " OFFSET " + o }
```

- [ ] **Step 4: Chạy — PASS**
```bash
cd ennam.kg.go && go test -count=1 ./internal/intel/
```
Expected: `ok`

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.go add internal/intel/source.go internal/intel/dialect.go internal/intel/dialect_test.go
git -C ennam.kg.go commit -m "feat(intel): source resolver interfaces and postgres dialect" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 4: Validator biểu thức mapping (allow-list)

**Files:** Create `internal/intel/expr.go`, `internal/intel/expr_test.go`.

**Interfaces:** Produces `func ValidateExpr(expr string, columns []SourceColumn, colSQL func(string) string) (string, error)` (lỗi kiểu `*ExprError`), `func IsStringLiteral(expr string) (string, bool)`, `const MaxExprLen = 500`. Consumes `lexSQL` (Task 2), `SourceColumn` (Task 3).

Allow-list (spec §6.3): cột của bảng nguồn (không phân biệt hoa thường, được rewrite qua `colSQL`), số, chuỗi `'…'`, `= <> != < > <= >= + - * / % ||`, ngoặc, `AND OR NOT IS NULL TRUE FALSE CASE WHEN THEN ELSE END IN LIKE ILIKE BETWEEN`, hàm `COALESCE LOWER UPPER TRIM`, `CAST(x AS t)` / `x::t` với `t ∈ {text,varchar,integer,int,bigint,numeric,decimal,boolean,date,timestamp}`. Cấm: `;`, comment, quoted identifier, `$`, `.`, subquery (SELECT không phải cột), hàm khác, `AS` ngoài CAST, `,` ngoài hàm/IN, ngoặc/CASE lệch.

- [ ] **Step 1: Viết test (failing)**
`internal/intel/expr_test.go`:
```go
package intel

import (
	"errors"
	"testing"
)

var exprCols = []SourceColumn{
	{Name: "claim_status", DataType: "text"},
	{Name: "Total", DataType: "numeric"},
	{Name: "discount", DataType: "numeric"},
	{Name: "created_at", DataType: "timestamp with time zone"},
}

func colRef(name string) string { return `src."` + name + `"` }

func TestValidateExpr_Accepts(t *testing.T) {
	cases := map[string]string{
		"claim_status":                                  `src."claim_status"`,
		"claim_status = 'Rejected'":                     `src."claim_status" = 'Rejected'`,
		"COALESCE(total, 0) - discount":                 `COALESCE( src."Total" , 0 ) - src."discount"`,
		"lower(trim(claim_status))":                     `LOWER( TRIM( src."claim_status" ) )`,
		"CAST(total AS numeric) * 1.5":                  `CAST( src."Total" AS numeric ) * 1.5`,
		"total::integer":                                `src."Total" ::integer`,
		"claim_status IN ('A', 'B')":                    `src."claim_status" IN ( 'A' , 'B' )`,
		"claim_status IS NOT NULL":                      `src."claim_status" IS NOT NULL`,
		"CASE WHEN total > 0 THEN 'pos' ELSE 'neg' END": `CASE WHEN src."Total" > 0 THEN 'pos' ELSE 'neg' END`,
		"'it''s' || claim_status":                       `'it''s' || src."claim_status"`,
		"'America/Chicago'":                             `'America/Chicago'`,
	}
	for in, want := range cases {
		got, err := ValidateExpr(in, exprCols, colRef)
		if err != nil {
			t.Errorf("%q rejected: %v", in, err)
			continue
		}
		if got != want {
			t.Errorf("%q\n got %s\nwant %s", in, got, want)
		}
	}
}

// Review Focus #3: LLM-proposed mappings run on the customer DB; anything outside
// the allow-list must be refused before it reaches SQL generation.
func TestValidateExpr_Rejects(t *testing.T) {
	bad := []string{
		"claim_status; DROP TABLE x",
		"claim_status = 'a'; --",
		"claim_status -- comment",
		"claim_status /* c */",
		"(SELECT 1)",
		"total = (select max(total) from orders)",
		"pg_sleep(10)",
		"now()",
		"unknown_col",
		`"claim_status"`,
		"$1",
		"total AS x",
		"total, discount",
		"(total",
		"total)",
		"CASE WHEN total > 0 THEN 1",
		"total::regclass",
		"CAST(total AS bytea)",
		"public.orders",
		"",
	}
	for _, in := range bad {
		_, err := ValidateExpr(in, exprCols, colRef)
		var ee *ExprError
		if !errors.As(err, &ee) {
			t.Errorf("%q: expected *ExprError, got %v", in, err)
		}
	}
}

func TestIsStringLiteral(t *testing.T) {
	if v, ok := IsStringLiteral("'America/Chicago'"); !ok || v != "America/Chicago" {
		t.Fatalf("got %q %v", v, ok)
	}
	if _, ok := IsStringLiteral("tz_col"); ok {
		t.Fatal("column must not be a literal")
	}
}
```

- [ ] **Step 2: Chạy — FAIL**
```bash
cd ennam.kg.go && go test -count=1 -run 'TestValidateExpr|TestIsStringLiteral' ./internal/intel/
```
Expected: FAIL — `undefined: ValidateExpr`.

- [ ] **Step 3: Implement**
`internal/intel/expr.go`:
```go
package intel

import (
	"fmt"
	"strings"
)

// MaxExprLen bounds a mapping expression.
const MaxExprLen = 500

var exprKeywords = map[string]bool{
	"AND": true, "OR": true, "NOT": true, "IS": true, "NULL": true, "TRUE": true, "FALSE": true,
	"CASE": true, "WHEN": true, "THEN": true, "ELSE": true, "END": true,
	"IN": true, "LIKE": true, "ILIKE": true, "BETWEEN": true,
}

var exprFunctions = map[string]bool{"COALESCE": true, "LOWER": true, "UPPER": true, "TRIM": true}

var exprCastTypes = map[string]string{
	"TEXT": "text", "VARCHAR": "text", "INTEGER": "integer", "INT": "integer", "BIGINT": "bigint",
	"NUMERIC": "numeric", "DECIMAL": "numeric", "BOOLEAN": "boolean", "DATE": "date", "TIMESTAMP": "timestamp",
}

// ExprError is a rejected mapping expression.
type ExprError struct {
	Expr   string
	Reason string
}

func (e *ExprError) Error() string {
	return fmt.Sprintf("mapping expression %q rejected: %s", e.Expr, e.Reason)
}

// ValidateExpr checks a mapping field expression against the allow-list of spec
// §6.3 and returns it rewritten for SQL generation:
//   - identifiers must be columns of the source table (case-insensitive) and are
//     replaced by colSQL(column) — the only way a name reaches the SQL;
//   - literals (numbers, 'strings'), comparison/logic/arithmetic operators, ||,
//     parentheses, CASE…END, IN (…), LIKE, BETWEEN, IS [NOT] NULL;
//   - functions COALESCE, LOWER, UPPER, TRIM; CAST(x AS type) and x::type with
//     type in a fixed list.
//
// Everything else is rejected: ';', comments, quoted identifiers, '$', subqueries
// (SELECT is not a column), other functions, AS outside CAST, ',' outside a
// function/IN list, unbalanced parentheses or CASE.
func ValidateExpr(expr string, columns []SourceColumn, colSQL func(string) string) (string, error) {
	reject := func(reason string) (string, error) { return "", &ExprError{Expr: expr, Reason: reason} }
	if strings.TrimSpace(expr) == "" {
		return reject("empty expression")
	}
	if len(expr) > MaxExprLen {
		return reject(fmt.Sprintf("longer than %d characters", MaxExprLen))
	}
	toks, err := lexSQL(expr)
	if err != nil {
		return reject(err.Error())
	}
	cols := make(map[string]string, len(columns))
	for _, c := range columns {
		cols[strings.ToLower(c.Name)] = c.Name
	}

	type frame int
	const (
		frameGroup frame = iota // ( … )
		frameFunc               // COALESCE( … )
		frameCast               // CAST( … AS type )
		frameIn                 // IN ( … )
	)
	var stack []frame
	caseDepth := 0
	var out []string
	sig := significantKeepComments(toks)
	for i := 0; i < len(sig); i++ {
		t := sig[i]
		next := func() *token {
			if i+1 < len(sig) {
				return &sig[i+1]
			}
			return nil
		}
		switch t.Kind {
		case tokComment:
			return reject("comments are not allowed")
		case tokSemicolon:
			return reject("';' is not allowed")
		case tokQuoted:
			return reject("quoted identifiers are not allowed")
		case tokParam:
			return reject("parameters are not allowed")
		case tokOther, tokDot:
			return reject(fmt.Sprintf("character %q is not allowed", t.Text))
		case tokNumber:
			if strings.Count(t.Text, ".") > 1 {
				return reject("malformed number " + t.Text)
			}
			out = append(out, t.Text)
		case tokString:
			out = append(out, t.Text)
		case tokOp:
			out = append(out, t.Text)
		case tokCast:
			n := next()
			if n == nil || n.Kind != tokIdent {
				return reject("'::' must be followed by a type")
			}
			typ, ok := exprCastTypes[strings.ToUpper(n.Text)]
			if !ok {
				return reject("cast type " + n.Text + " is not allowed")
			}
			out = append(out, "::"+typ)
			i++
		case tokComma:
			if len(stack) == 0 || (stack[len(stack)-1] != frameFunc && stack[len(stack)-1] != frameIn) {
				return reject("',' is only allowed inside a function call or IN list")
			}
			out = append(out, ",")
		case tokLParen:
			stack = append(stack, frameGroup)
			out = append(out, "(")
		case tokRParen:
			if len(stack) == 0 {
				return reject("unbalanced ')'")
			}
			stack = stack[:len(stack)-1]
			out = append(out, ")")
		case tokIdent:
			up := strings.ToUpper(t.Text)
			n := next()
			switch {
			case exprFunctions[up]:
				if n == nil || n.Kind != tokLParen {
					return reject(up + " must be followed by '('")
				}
				stack = append(stack, frameFunc)
				out = append(out, up+"(")
				i++
			case up == "CAST":
				if n == nil || n.Kind != tokLParen {
					return reject("CAST must be followed by '('")
				}
				stack = append(stack, frameCast)
				out = append(out, "CAST(")
				i++
			case up == "AS":
				if len(stack) == 0 || stack[len(stack)-1] != frameCast {
					return reject("AS is only allowed inside CAST(…)")
				}
				if n == nil || n.Kind != tokIdent {
					return reject("AS must be followed by a type")
				}
				typ, ok := exprCastTypes[strings.ToUpper(n.Text)]
				if !ok {
					return reject("cast type " + n.Text + " is not allowed")
				}
				out = append(out, "AS", typ)
				i++
			case up == "IN":
				if n == nil || n.Kind != tokLParen {
					return reject("IN must be followed by '('")
				}
				stack = append(stack, frameIn)
				out = append(out, "IN (")
				i++
			case up == "CASE":
				caseDepth++
				out = append(out, up)
			case up == "END":
				if caseDepth == 0 {
					return reject("END without CASE")
				}
				caseDepth--
				out = append(out, up)
			case exprKeywords[up]:
				out = append(out, up)
			default:
				if n != nil && n.Kind == tokLParen {
					return reject("function " + t.Text + " is not allowed")
				}
				name, ok := cols[strings.ToLower(t.Text)]
				if !ok {
					return reject("unknown column or keyword " + t.Text)
				}
				out = append(out, colSQL(name))
			}
		default:
			return reject("unexpected token " + t.Text)
		}
	}
	if len(stack) != 0 {
		return reject("unbalanced '('")
	}
	if caseDepth != 0 {
		return reject("CASE without END")
	}
	return strings.Join(out, " "), nil
}

// significantKeepComments drops whitespace only, so comments can be rejected.
func significantKeepComments(toks []token) []token {
	out := make([]token, 0, len(toks))
	for _, t := range toks {
		if t.Kind != tokSpace {
			out = append(out, t)
		}
	}
	return out
}

// IsStringLiteral reports whether expr is exactly one SQL string literal and
// returns its unescaped value (used to read a constant timezone from mapping).
func IsStringLiteral(expr string) (string, bool) {
	toks, err := lexSQL(strings.TrimSpace(expr))
	if err != nil || len(toks) != 1 || toks[0].Kind != tokString {
		return "", false
	}
	raw := toks[0].Text
	return strings.ReplaceAll(raw[1:len(raw)-1], "''", "'"), true
}
```

- [ ] **Step 4: Chạy — PASS**
```bash
cd ennam.kg.go && go test -count=1 -run 'TestValidateExpr|TestIsStringLiteral' ./internal/intel/
```
Expected: `ok`

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.go add internal/intel/expr.go internal/intel/expr_test.go
git -C ennam.kg.go commit -m "feat(intel): allow-list validator for mapping expressions" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 5: Compiler (mapping → CTE, enum, timezone, `_source_ref`, `:param` → `$n`) + mapping YAML (Plan C phụ thuộc)

**Files:** Create `internal/intel/compile.go`, `internal/intel/mapping_file.go`, `internal/intel/compile_test.go`, `internal/intel/testdata/packs/_projects/demo/mapping.yaml`.

**Interfaces:**
- Produces: `type Compiler struct{ Dialect Dialect; Catalog *Catalog }`; `func (c *Compiler) EntityCTE(entity string, m Mapping, t SourceTable, tz string) (string, error)`; `func (c *Compiler) CompileMetric(def *MetricDef, ctes map[string]string) (*Compiled, error)`; `func (c *Compiler) CompileEvidence(ev *EvidenceDef, requires []string, ctes map[string]string) (*Compiled, error)` (thêm `LIMIT $n OFFSET $m` với tham số `_limit`, `_offset`); `func (c *Compiler) RawFieldSQL(...)`, `EnumValuesSQL(...)`, `RequiredNullsSQL(...)`, `LatestDateSQL(...)`; `type Compiled struct{ SQL string; Params []string }` + `func (c *Compiled) Args(map[string]any) ([]any, error)`; `const SourceRefField = "_source_ref"`; `func ParseMappingFile([]byte) (*MappingFile, error)`.
- Consumes: Task 2–4.

Quy tắc compiler: mỗi field canonical → `CAST(<expr> AS <kiểu>) AS "<field>"`; field không map: required ⇒ `MappingError{missing_required_field}`, optional ⇒ `CAST(NULL AS <kiểu>)`; field có `enum_map` ⇒ `CASE <expr> WHEN 'raw' THEN 'canonical' … ELSE NULL END`; field timestamp map thẳng vào cột `… with time zone` ⇒ `(<expr> AT TIME ZONE '<tz>')` (timestamp không múi giờ coi là giờ địa phương — spec I12); `_source_ref` = `'<RefLabel>:' || CAST(<key> AS text)`. Pack SQL bắt đầu bằng `WITH` được gộp vào cùng một danh sách CTE.

- [ ] **Step 1: Viết test (failing)**
`internal/intel/testdata/packs/_projects/demo/mapping.yaml`:
```yaml
project_id: 11111111-2222-3333-4444-555555555555
defaults:
  mode: live
  data_source_id: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
entities:
  location:
    from: shops
    fields:
      location_id: shop_code
      timezone: "'America/Chicago'"
  order:
    from: public.orders
    fields:
      order_id: id
      location_id: shop_code
      ordered_at: created_at
      amount: COALESCE(total, 0) - discount
      status: state
    enum_map:
      status: { OPEN: open, CLOSED: closed }
```

`internal/intel/compile_test.go`:
```go
package intel

import (
	"errors"
	"os"
	"strings"
	"testing"
)

// fakeTable is a live-style SourceTable for compiler tests.
type fakeTable struct {
	rel  string
	cols []SourceColumn
}

func (f fakeTable) Relation() string             { return f.rel + " AS src" }
func (f fakeTable) Filter() string               { return "" }
func (f fakeTable) RefLabel() string             { return "orders" }
func (f fakeTable) Columns() []SourceColumn      { return f.cols }
func (f fakeTable) ColumnSQL(name string) string { return `src."` + name + `"` }

func demoCompiler(t *testing.T) (*Compiler, *MappingFile) {
	t.Helper()
	reg, err := LoadRegistry("testdata/packs")
	if err != nil {
		t.Fatal(err)
	}
	cat, err := reg.Effective([]string{"child"})
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile("testdata/packs/_projects/demo/mapping.yaml")
	if err != nil {
		t.Fatal(err)
	}
	mf, err := ParseMappingFile(raw)
	if err != nil {
		t.Fatal(err)
	}
	return &Compiler{Dialect: Postgres{}, Catalog: cat}, mf
}

func mappingFor(mf *MappingFile, entity string) Mapping {
	for _, m := range mf.Mappings {
		if m.Entity == entity {
			return m
		}
	}
	return Mapping{}
}

var ordersTable = fakeTable{rel: `"public"."orders"`, cols: []SourceColumn{
	{Name: "id", DataType: "text"}, {Name: "shop_code", DataType: "text"},
	{Name: "created_at", DataType: "timestamp with time zone"}, {Name: "total", DataType: "numeric"},
	{Name: "discount", DataType: "numeric"}, {Name: "state", DataType: "text"},
}}

func TestEntityCTE_RendersMappingEnumTimezoneAndSourceRef(t *testing.T) {
	c, mf := demoCompiler(t)
	cte, err := c.EntityCTE("order", mappingFor(mf, "order"), ordersTable, "America/Chicago")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{
		`"order" AS (SELECT `,
		`CAST(src."id" AS text) AS "order_id"`,
		`CAST((src."created_at" AT TIME ZONE 'America/Chicago') AS timestamp) AS "ordered_at"`,
		`CAST(COALESCE( src."total" , 0 ) - src."discount" AS numeric) AS "amount"`,
		`CAST(CASE src."state" WHEN 'CLOSED' THEN 'closed' WHEN 'OPEN' THEN 'open' ELSE NULL END AS text) AS "status"`,
		`CAST(NULL AS text) AS "channel"`,
		`'orders:' || CAST(src."id" AS text) AS "_source_ref"`,
		`FROM "public"."orders" AS src)`,
	} {
		if !strings.Contains(cte, want) {
			t.Errorf("CTE missing %s\n%s", want, cte)
		}
	}
}

func TestEntityCTE_MappingErrors(t *testing.T) {
	c, mf := demoCompiler(t)
	m := mappingFor(mf, "order")
	m.Spec.Fields = map[string]string{"order_id": "id", "ordered_at": "created_at"} // location_id required, missing
	_, err := c.EntityCTE("order", m, ordersTable, "UTC")
	var me *MappingError
	if !errors.As(err, &me) || me.Code != "missing_required_field" {
		t.Fatalf("want missing_required_field, got %v", err)
	}
	m = mappingFor(mf, "order")
	m.Spec.Fields = map[string]string{"order_id": "id", "location_id": "gone_col", "ordered_at": "created_at"}
	_, err = c.EntityCTE("order", m, ordersTable, "UTC")
	if !errors.As(err, &me) || me.Code != "invalid_expression" {
		t.Fatalf("want invalid_expression, got %v", err)
	}
}

func TestCompileMetric_BindsParamsAndMergesWith(t *testing.T) {
	c, mf := demoCompiler(t)
	cte, err := c.EntityCTE("order", mappingFor(mf, "order"), ordersTable, "UTC")
	if err != nil {
		t.Fatal(err)
	}
	ctes := map[string]string{"order": cte}

	plain, err := c.CompileMetric(c.Catalog.Metrics["base.order_total"], ctes)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(plain.SQL, `WITH "order" AS (`) || strings.Count(plain.SQL, "WITH") != 1 {
		t.Fatalf("bad prefix:\n%s", plain.SQL)
	}
	if !strings.Contains(plain.SQL, "ordered_at >= CAST($1 AS date) AND ordered_at < CAST($2 AS date)") {
		t.Fatalf("params not bound:\n%s", plain.SQL)
	}
	if strings.Join(plain.Params, ",") != "from,to" {
		t.Fatalf("params = %v", plain.Params)
	}

	merged, err := c.CompileMetric(c.Catalog.Metrics["child.closed_share"], ctes)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(merged.SQL, ",\no AS (SELECT") || strings.Count(merged.SQL, "WITH ") != 1 {
		t.Fatalf("pack WITH not merged into one WITH list:\n%s", merged.SQL)
	}
}

func TestCompileEvidence_AppendsPaging(t *testing.T) {
	c, mf := demoCompiler(t)
	cte, _ := c.EntityCTE("order", mappingFor(mf, "order"), ordersTable, "UTC")
	ev, err := c.CompileEvidence(c.Catalog.Evidence["base.order_total"], []string{"order"}, map[string]string{"order": cte})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(ev.Params, ",") != "from,to,dim_location_id,_limit,_offset" {
		t.Fatalf("params = %v", ev.Params)
	}
	if !strings.HasSuffix(ev.SQL, " LIMIT $4 OFFSET $5") || !strings.Contains(ev.SQL, "location_id = CAST($3 AS text)") {
		t.Fatalf("sql:\n%s", ev.SQL)
	}
	args, err := ev.Args(map[string]any{"from": "2026-07-01", "to": "2026-07-02", "dim_location_id": "S1", "_limit": 51, "_offset": 0})
	if err != nil || len(args) != 5 || args[2] != "S1" {
		t.Fatalf("args = %v, %v", args, err)
	}
	if _, err := ev.Args(map[string]any{"from": "x"}); err == nil {
		t.Fatal("missing param must error")
	}
}

func TestCompileMetric_MissingEntityCTE(t *testing.T) {
	c, _ := demoCompiler(t)
	if _, err := c.CompileMetric(c.Catalog.Metrics["base.order_total"], map[string]string{}); err == nil {
		t.Fatal("expected error for missing CTE")
	}
}

func TestParseMappingFile_Validates(t *testing.T) {
	_, mf := demoCompiler(t)
	if mf.ProjectID != "11111111-2222-3333-4444-555555555555" || len(mf.Mappings) != 2 {
		t.Fatalf("mf = %+v", mf)
	}
	o := mappingFor(mf, "order")
	if o.Mode != ModeLive || o.DataSourceID != "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" || o.Spec.From != "public.orders" {
		t.Fatalf("order mapping = %+v", o)
	}
	bad := []string{
		"project_id: x\nentities: {a: {from: t, fields: {a: b}}}",
		"project_id: 11111111-2222-3333-4444-555555555555\nentities: {a: {mode: live, from: t, fields: {a: b}}}",
		"project_id: 11111111-2222-3333-4444-555555555555\ndefaults: {mode: live, data_source_id: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee}\nentities: {a: {from: 't; drop', fields: {a: b}}}",
		"project_id: 11111111-2222-3333-4444-555555555555\nentities: {a: {mode: file, from: t, fields: {a: b}}}",
	}
	for _, b := range bad {
		if _, err := ParseMappingFile([]byte(b)); err == nil {
			t.Errorf("accepted invalid file:\n%s", b)
		}
	}
}
```

- [ ] **Step 2: Chạy — FAIL**
```bash
cd ennam.kg.go && go test -count=1 -run 'TestEntityCTE|TestCompile|TestParseMappingFile' ./internal/intel/
```
Expected: FAIL — `undefined: Compiler`, `undefined: ParseMappingFile`.

- [ ] **Step 3: Implement**
`internal/intel/compile.go`:
```go
package intel

import (
	"fmt"
	"sort"
	"strings"
)

// Compiled is one statement ready for a QueryExecutor. Params lists the named
// parameter of every positional placeholder ($1 = Params[0], …).
type Compiled struct {
	SQL    string
	Params []string
}

// Args builds the positional argument slice from named values. Every name in
// c.Params must be present.
func (c *Compiled) Args(values map[string]any) ([]any, error) {
	args := make([]any, len(c.Params))
	for i, name := range c.Params {
		v, ok := values[name]
		if !ok {
			return nil, fmt.Errorf("missing value for parameter :%s", name)
		}
		args[i] = v
	}
	return args, nil
}

// Compiler turns mappings + pack SQL into statements (spec §6.3).
type Compiler struct {
	Dialect Dialect
	Catalog *Catalog
}

// SourceRefField is the virtual field every entity CTE exposes.
const SourceRefField = "_source_ref"

// EntityCTE renders `"<entity>" AS (SELECT … FROM <relation>)` for one mapping.
// tz is the business timezone used to convert timezone-aware source timestamps
// to local wall-clock time; timestamps without zone are taken as local already.
func (c *Compiler) EntityCTE(entityName string, m Mapping, t SourceTable, tz string) (string, error) {
	ent, ok := c.Catalog.Entities[entityName]
	if !ok {
		return "", &MappingError{Entity: entityName, Code: "invalid_spec", Detail: "entity is not defined by any installed pack"}
	}
	for f := range m.Spec.Fields {
		if _, ok := ent.Field(f); !ok {
			return "", &MappingError{Entity: entityName, Code: "invalid_spec", Detail: "unknown canonical field " + f}
		}
	}
	for f := range m.Spec.EnumMap {
		if _, ok := c.Catalog.Enums[entityName+"."+f]; !ok {
			return "", &MappingError{Entity: entityName, Code: "invalid_spec", Detail: "enum_map on non-enum field " + f}
		}
	}
	d := c.Dialect
	cols := t.Columns()
	var selects []string
	exprs := map[string]string{}
	for _, f := range ent.Fields {
		raw, mapped := m.Spec.Fields[f.Name]
		if !mapped {
			if f.Required {
				return "", &MappingError{Entity: entityName, Code: "missing_required_field", Detail: f.Name}
			}
			selects = append(selects, fmt.Sprintf("CAST(NULL AS %s) AS %s", d.TypeName(f.Type), d.QuoteIdent(f.Name)))
			continue
		}
		sqlExpr, err := ValidateExpr(raw, cols, t.ColumnSQL)
		if err != nil {
			return "", &MappingError{Entity: entityName, Code: "invalid_expression", Detail: err.Error()}
		}
		if f.Type == TypeTimestamp && isTimezoneAwareColumn(raw, cols) {
			sqlExpr = d.LocalTimestamp(sqlExpr, tz)
		}
		if em, ok := m.Spec.EnumMap[f.Name]; ok {
			sqlExpr = enumCase(d, sqlExpr, em)
		}
		exprs[f.Name] = sqlExpr
		selects = append(selects, fmt.Sprintf("CAST(%s AS %s) AS %s", sqlExpr, d.TypeName(f.Type), d.QuoteIdent(f.Name)))
	}
	ref := "CAST(NULL AS text)"
	if kf, ok := ent.KeyField(); ok {
		if e, ok := exprs[kf.Name]; ok {
			ref = fmt.Sprintf("%s || CAST(%s AS text)", d.QuoteLiteral(t.RefLabel()+":"), e)
		}
	}
	selects = append(selects, fmt.Sprintf("%s AS %s", ref, d.QuoteIdent(SourceRefField)))
	where := ""
	if f := t.Filter(); f != "" {
		where = " WHERE " + f
	}
	return fmt.Sprintf("%s AS (SELECT %s FROM %s%s)", d.QuoteIdent(entityName), strings.Join(selects, ", "), t.Relation(), where), nil
}

func enumCase(d Dialect, expr string, em map[string]string) string {
	keys := make([]string, 0, len(em))
	for k := range em {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var sb strings.Builder
	sb.WriteString("CASE " + expr)
	for _, k := range keys {
		sb.WriteString(" WHEN " + d.QuoteLiteral(k) + " THEN " + d.QuoteLiteral(em[k]))
	}
	sb.WriteString(" ELSE NULL END")
	return sb.String()
}

func isTimezoneAwareColumn(raw string, cols []SourceColumn) bool {
	name := strings.TrimSpace(raw)
	for _, c := range cols {
		if strings.EqualFold(c.Name, name) {
			return strings.Contains(c.DataType, "with time zone")
		}
	}
	return false
}

// RawFieldSQL returns the validated source expression of a mapped field before
// enum mapping and casting (used by validation queries).
func (c *Compiler) RawFieldSQL(m Mapping, t SourceTable, field string) (string, bool, error) {
	raw, ok := m.Spec.Fields[field]
	if !ok {
		return "", false, nil
	}
	s, err := ValidateExpr(raw, t.Columns(), t.ColumnSQL)
	if err != nil {
		return "", true, &MappingError{Entity: m.Entity, Code: "invalid_expression", Detail: err.Error()}
	}
	return s, true, nil
}

// EnumValuesSQL lists the distinct raw values of an enum field (at most limit),
// so the runner can report values the mapping does not normalise (spec §14.5).
func (c *Compiler) EnumValuesSQL(m Mapping, t SourceTable, field string, limit int) (string, error) {
	raw, ok, err := c.RawFieldSQL(m, t, field)
	if err != nil || !ok {
		return "", err
	}
	where := " WHERE (" + raw + ") IS NOT NULL"
	if f := t.Filter(); f != "" {
		where += " AND " + f
	}
	return fmt.Sprintf("SELECT DISTINCT CAST(%s AS text) AS v FROM %s%s LIMIT %d", raw, t.Relation(), where, limit), nil
}

// LatestDateSQL returns the newest date of a mapped field (freshness check).
func (c *Compiler) LatestDateSQL(m Mapping, t SourceTable, field string) (string, error) {
	raw, ok, err := c.RawFieldSQL(m, t, field)
	if err != nil || !ok {
		return "", err
	}
	where := ""
	if f := t.Filter(); f != "" {
		where = " WHERE " + f
	}
	return fmt.Sprintf("SELECT MAX(CAST(%s AS date)) AS latest FROM %s%s", raw, t.Relation(), where), nil
}

// RequiredNullsSQL counts NULLs of every mapped required field over at most
// sample rows. Result columns: total, then one column per field in fields order.
func (c *Compiler) RequiredNullsSQL(m Mapping, t SourceTable, fields []string, sample int) (string, error) {
	d := c.Dialect
	var inner, counts []string
	for i, f := range fields {
		raw, ok, err := c.RawFieldSQL(m, t, f)
		if err != nil {
			return "", err
		}
		if !ok {
			continue
		}
		alias := fmt.Sprintf("f%d", i)
		inner = append(inner, fmt.Sprintf("%s AS %s", raw, alias))
		counts = append(counts, fmt.Sprintf("COUNT(*) FILTER (WHERE %s IS NULL) AS %s", alias, d.QuoteIdent(f)))
	}
	if len(inner) == 0 {
		return "", nil
	}
	where := ""
	if f := t.Filter(); f != "" {
		where = " WHERE " + f
	}
	return fmt.Sprintf("SELECT COUNT(*) AS total, %s FROM (SELECT %s FROM %s%s LIMIT %d) s",
		strings.Join(counts, ", "), strings.Join(inner, ", "), t.Relation(), where, sample), nil
}

// CompileMetric prefixes the metric body with the CTEs of its required entities
// and binds :from/:to to positional date parameters.
func (c *Compiler) CompileMetric(def *MetricDef, ctes map[string]string) (*Compiled, error) {
	return c.compile(def.Body, def.Requires, ctes, false)
}

// CompileEvidence does the same for evidence SQL and appends LIMIT/OFFSET bound to
// the parameters "_limit" and "_offset".
func (c *Compiler) CompileEvidence(ev *EvidenceDef, requires []string, ctes map[string]string) (*Compiled, error) {
	return c.compile(ev.Body, requires, ctes, true)
}

func (c *Compiler) compile(body string, requires []string, ctes map[string]string, paging bool) (*Compiled, error) {
	parts := make([]string, 0, len(requires))
	for _, r := range requires {
		cte, ok := ctes[r]
		if !ok {
			return nil, fmt.Errorf("compile: no mapping for required entity %q", r)
		}
		parts = append(parts, cte)
	}
	bound, names, err := bindNamedParams(body, c.Dialect)
	if err != nil {
		return nil, err
	}
	toks, err := lexSQL(bound)
	if err != nil {
		return nil, err
	}
	sig := significant(toks)
	if len(sig) == 0 {
		return nil, fmt.Errorf("compile: empty statement")
	}
	var sql string
	first := strings.ToUpper(sig[0].Text)
	switch {
	case first == "WITH":
		if len(sig) > 1 && strings.EqualFold(sig[1].Text, "RECURSIVE") {
			return nil, fmt.Errorf("compile: WITH RECURSIVE is not supported in pack SQL")
		}
		rest := strings.TrimSpace(bound)[len("WITH"):]
		sql = "WITH " + strings.Join(parts, ",\n") + ",\n" + strings.TrimSpace(rest)
	case first == "SELECT":
		sql = "WITH " + strings.Join(parts, ",\n") + "\n" + bound
	default:
		return nil, fmt.Errorf("compile: pack SQL must start with SELECT or WITH")
	}
	if paging {
		names = append(names, "_limit", "_offset")
		sql += c.Dialect.LimitOffset(c.Dialect.Placeholder(len(names)-1), c.Dialect.Placeholder(len(names)))
	}
	return &Compiled{SQL: sql, Params: names}, nil
}

// bindNamedParams replaces :from/:to with CAST($n AS date) and :dim_<x> with
// CAST($n AS text); a name used twice reuses its index.
func bindNamedParams(body string, d Dialect) (string, []string, error) {
	toks, err := lexSQL(body)
	if err != nil {
		return "", nil, err
	}
	index := map[string]int{}
	var names []string
	var sb strings.Builder
	for _, t := range toks {
		if t.Kind != tokParam {
			sb.WriteString(t.Text)
			continue
		}
		name := paramName(t)
		n, ok := index[name]
		if !ok {
			names = append(names, name)
			n = len(names)
			index[name] = n
		}
		typ := "text"
		if name == "from" || name == "to" {
			typ = "date"
		}
		sb.WriteString(fmt.Sprintf("CAST(%s AS %s)", d.Placeholder(n), typ))
	}
	return sb.String(), names, nil
}
```

`internal/intel/mapping_file.go`:
```go
package intel

import (
	"fmt"
	"regexp"
	"sort"

	"gopkg.in/yaml.v3"
)

// MappingFile is the YAML seed format read by `kg-packs import-mapping`
// (packs/_projects/<project>/mapping.yaml). Runtime reads project_mapping only.
//
//	project_id: <uuid>
//	defaults: { mode: live, data_source_id: <uuid> }
//	entities:
//	  <entity>:
//	    mode: live|file              # optional, defaults.mode
//	    data_source_id: <uuid>       # mode=live, optional, defaults.data_source_id
//	    file_dataset: <name>         # mode=file
//	    from: <table>                # live: [schema.]table ; file: dataset name
//	    fields: { <canonical field>: <expression> }
//	    enum_map: { <field>: { <raw value>: <canonical value> } }
type MappingFile struct {
	ProjectID string
	Mappings  []Mapping // sorted by entity
}

type mappingFileYAML struct {
	ProjectID string `yaml:"project_id"`
	Defaults  struct {
		Mode         string `yaml:"mode"`
		DataSourceID string `yaml:"data_source_id"`
	} `yaml:"defaults"`
	Entities map[string]struct {
		Mode         string                       `yaml:"mode"`
		DataSourceID string                       `yaml:"data_source_id"`
		FileDataset  string                       `yaml:"file_dataset"`
		From         string                       `yaml:"from"`
		Fields       map[string]string            `yaml:"fields"`
		EnumMap      map[string]map[string]string `yaml:"enum_map"`
	} `yaml:"entities"`
}

var (
	uuidRe      = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)
	tableNameRe = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$`)
)

// ParseMappingFile parses and structurally validates a mapping seed file. Column
// existence and expressions are validated later against the bound source.
func ParseMappingFile(raw []byte) (*MappingFile, error) {
	var y mappingFileYAML
	if err := yaml.Unmarshal(raw, &y); err != nil {
		return nil, fmt.Errorf("mapping file: %w", err)
	}
	if !uuidRe.MatchString(y.ProjectID) {
		return nil, fmt.Errorf("mapping file: project_id must be a UUID")
	}
	if len(y.Entities) == 0 {
		return nil, fmt.Errorf("mapping file: no entities")
	}
	out := &MappingFile{ProjectID: y.ProjectID}
	for name, e := range y.Entities {
		if !identRe.MatchString(name) {
			return nil, fmt.Errorf("mapping file: invalid entity name %q", name)
		}
		mode := SourceMode(e.Mode)
		if mode == "" {
			mode = SourceMode(y.Defaults.Mode)
		}
		m := Mapping{ProjectID: y.ProjectID, Entity: name, Mode: mode,
			Spec: MappingSpec{From: e.From, Fields: e.Fields, EnumMap: e.EnumMap}}
		switch mode {
		case ModeLive:
			m.DataSourceID = e.DataSourceID
			if m.DataSourceID == "" {
				m.DataSourceID = y.Defaults.DataSourceID
			}
			if !uuidRe.MatchString(m.DataSourceID) {
				return nil, fmt.Errorf("mapping file: %s: data_source_id must be a UUID", name)
			}
			if !tableNameRe.MatchString(e.From) {
				return nil, fmt.Errorf("mapping file: %s: from %q must be [schema.]table", name, e.From)
			}
		case ModeFile:
			if e.FileDataset == "" {
				return nil, fmt.Errorf("mapping file: %s: mode=file requires file_dataset", name)
			}
			m.FileDataset = e.FileDataset
		default:
			return nil, fmt.Errorf("mapping file: %s: mode must be live or file", name)
		}
		if len(e.Fields) == 0 {
			return nil, fmt.Errorf("mapping file: %s: fields is empty", name)
		}
		out.Mappings = append(out.Mappings, m)
	}
	sort.Slice(out.Mappings, func(i, j int) bool { return out.Mappings[i].Entity < out.Mappings[j].Entity })
	return out, nil
}
```

- [ ] **Step 4: Chạy — PASS (cả package)**
```bash
cd ennam.kg.go && go test -count=1 ./internal/intel/
```
Expected: `ok`

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.go add internal/intel/compile.go internal/intel/mapping_file.go internal/intel/compile_test.go internal/intel/testdata/packs/_projects
git -C ennam.kg.go commit -m "feat(intel): compile project mappings into entity CTEs" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 6: Store (`pack_install`, `project_intel_settings`, `project_mapping`, `metric_value`, `data_status`)

**Files:** Create `internal/intel/intelstore/store.go`, `internal/intel/intelstore/store_test.go`.

**Interfaces:** Produces `func New(*sql.DB) *Store`; `DB()`; `ListInstalls`, `UpsertInstall(ctx, projectID, packKey, version string, enabled bool)`, `ProjectsWithEnabledPacks`; `GetProjectSettings(ctx, projectID) (ProjectSettings, error)`, `SetAsOf(ctx, projectID string, asOf *time.Time, timezone string) error`; `ListMappings`, `UpsertMapping(ctx, intel.Mapping, approvedBy string) (int, error)` (tăng `version` chỉ khi mode/nguồn/spec đổi), `SetMappingStatus`; `ReplaceMetricRows(ctx, WriteMeta, deleteFrom, deleteTo *time.Time, rows []MetricRow) error` (xoá cửa sổ + upsert trong 1 transaction, batch 500 dòng); `SeriesExtent(ctx, projectID, key) (maxVersion int, minPeriod time.Time, found bool, err error)`; `QuerySeries(ctx, SeriesQuery) ([]SeriesPoint, error)` (gộp trong SQL, `dims_filter` ở WHERE); `VersionsInSeries`; `UpsertDataStatus(ctx, intel.DataStatus) error` (writer dùng chung — Plan C dùng), `ListDataStatus`, `GetDataStatus`.

- [ ] **Step 1: Viết test (failing)**
`internal/intel/intelstore/store_test.go`:
```go
package intelstore_test

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"testing"
	"time"

	_ "github.com/lib/pq" // postgres driver for integration tests

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/intelstore"
)

// openDB skips unless KG_TEST_DATABASE_URL is set (dev DB is on port 5433).
func openDB(t *testing.T) *sql.DB {
	t.Helper()
	url := os.Getenv("KG_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("Skipping integration test: KG_TEST_DATABASE_URL not set")
	}
	db, err := sql.Open("postgres", url)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	if err := db.Ping(); err != nil {
		t.Fatalf("ping: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	return db
}

// seedProject creates a throwaway project; ON DELETE CASCADE cleans the intel tables.
func seedProject(t *testing.T, db *sql.DB) string {
	t.Helper()
	var id string
	name := fmt.Sprintf("intel-store-test-%d", time.Now().UnixNano())
	if err := db.QueryRow(`INSERT INTO projects (name) VALUES ($1) RETURNING id::text`, name).Scan(&id); err != nil {
		t.Fatalf("seed project: %v", err)
	}
	t.Cleanup(func() { _, _ = db.Exec(`DELETE FROM projects WHERE id = $1`, id) })
	return id
}

func f(v float64) *float64 { return &v }

func day(s string) time.Time {
	d, _ := time.Parse("2006-01-02", s)
	return d
}

func TestStore_InstallsAndMappingVersioning(t *testing.T) {
	db := openDB(t)
	s := intelstore.New(db)
	ctx := context.Background()
	pid := seedProject(t, db)

	if err := s.UpsertInstall(ctx, pid, "base", "0.1.0", true); err != nil {
		t.Fatal(err)
	}
	ins, err := s.ListInstalls(ctx, pid)
	if err != nil || len(ins) != 1 || ins[0].Version != "0.1.0" || !ins[0].Enabled {
		t.Fatalf("installs = %+v, %v", ins, err)
	}

	m := intel.Mapping{ProjectID: pid, Entity: "order", Mode: intel.ModeFile, FileDataset: "orders",
		Spec: intel.MappingSpec{From: "orders", Fields: map[string]string{"order_id": "id"}}, Status: intel.MappingApproved}
	v1, err := s.UpsertMapping(ctx, m, "tester")
	if err != nil || v1 != 1 {
		t.Fatalf("first upsert v=%d err=%v", v1, err)
	}
	v1b, _ := s.UpsertMapping(ctx, m, "tester")
	if v1b != 1 {
		t.Fatalf("unchanged spec must keep version 1, got %d", v1b)
	}
	m.Spec.Fields["location_id"] = "shop"
	v2, _ := s.UpsertMapping(ctx, m, "tester")
	if v2 != 2 {
		t.Fatalf("changed spec must bump to 2, got %d", v2)
	}
	if err := s.SetMappingStatus(ctx, pid, "order", intel.MappingBroken); err != nil {
		t.Fatal(err)
	}
	ms, _ := s.ListMappings(ctx, pid)
	if len(ms) != 1 || ms[0].Status != intel.MappingBroken || ms[0].Spec.Fields["location_id"] != "shop" {
		t.Fatalf("mappings = %+v", ms)
	}
}

func TestStore_ReplaceWindowDeletesVanishedRows(t *testing.T) {
	db := openDB(t)
	s := intelstore.New(db)
	ctx := context.Background()
	pid := seedProject(t, db)
	meta := intelstore.WriteMeta{ProjectID: pid, MetricKey: "base.x", MetricVersion: 1, PackVersion: "0.1.0", SourceMode: intel.ModeLive}

	rows := []intelstore.MetricRow{
		{PeriodDate: day("2026-07-01"), Dims: map[string]string{"location_id": "A"}, DimsHash: "hA", Value: f(10), SampleSize: 1},
		{PeriodDate: day("2026-07-01"), Dims: map[string]string{"location_id": "B"}, DimsHash: "hB", Value: f(20), SampleSize: 2},
	}
	if err := s.ReplaceMetricRows(ctx, meta, nil, nil, rows); err != nil {
		t.Fatal(err)
	}
	from, to := day("2026-07-01"), day("2026-07-02")
	meta.MetricVersion = 2
	if err := s.ReplaceMetricRows(ctx, meta, &from, &to, rows[:1]); err != nil {
		t.Fatal(err)
	}
	pts, err := s.QuerySeries(ctx, intelstore.SeriesQuery{ProjectID: pid, MetricKey: "base.x", From: from, To: to,
		Grain: "day", GroupBy: []string{"location_id"}, Aggregation: intel.AggAdditive})
	if err != nil {
		t.Fatal(err)
	}
	if len(pts) != 1 || pts[0].Dims["location_id"] != "A" || *pts[0].Value != 10 {
		t.Fatalf("window replace must drop B: %+v", pts)
	}
	if _, found, _ := s.StaleSince(ctx, pid, "base.x", 2); found {
		t.Fatal("no row is older than version 2 after the replace")
	}
	if p, found, _ := s.StaleSince(ctx, pid, "base.x", 3); !found || !p.Equal(from) {
		t.Fatalf("version 3 must find the v2 row at %v, got %v %v", from, p, found)
	}
	vmax, pmin, found, err := s.SeriesExtent(ctx, pid, "base.x")
	if err != nil || !found || vmax != 2 || !pmin.Equal(from) {
		t.Fatalf("extent = %d %v %v %v", vmax, pmin, found, err)
	}
}

func TestStore_DataStatusKeepsLastSuccess(t *testing.T) {
	db := openDB(t)
	s := intelstore.New(db)
	ctx := context.Background()
	pid := seedProject(t, db)
	now := time.Now().UTC().Truncate(time.Second)
	if err := s.UpsertDataStatus(ctx, intel.DataStatus{ProjectID: pid, Subject: "metric:base.x", Status: intel.StatusCurrent, LastSuccessAt: &now}); err != nil {
		t.Fatal(err)
	}
	if err := s.UpsertDataStatus(ctx, intel.DataStatus{ProjectID: pid, Subject: "metric:base.x", Status: intel.StatusBlocked,
		Issues: []intel.Issue{{Code: "row_limit", Message: "truncated"}}}); err != nil {
		t.Fatal(err)
	}
	st, err := s.GetDataStatus(ctx, pid, "metric:base.x")
	if err != nil || st == nil || st.Status != intel.StatusBlocked || st.LastSuccessAt == nil || !st.LastSuccessAt.Equal(now) || len(st.Issues) != 1 {
		t.Fatalf("status = %+v, %v", st, err)
	}
}

func TestStore_ProjectSettings(t *testing.T) {
	db := openDB(t)
	s := intelstore.New(db)
	ctx := context.Background()
	pid := seedProject(t, db)
	if got, err := s.GetProjectSettings(ctx, pid); err != nil || got.AsOfOverride != nil || got.Timezone != "" {
		t.Fatalf("no row must give zero settings: %+v %v", got, err)
	}
	d := day("2026-08-01")
	if err := s.SetAsOf(ctx, pid, &d, "America/Chicago"); err != nil {
		t.Fatal(err)
	}
	if err := s.SetAsOf(ctx, pid, &d, ""); err != nil { // timezone kept when omitted
		t.Fatal(err)
	}
	got, err := s.GetProjectSettings(ctx, pid)
	if err != nil || got.AsOfOverride == nil || !got.AsOfOverride.Equal(d) || got.Timezone != "America/Chicago" {
		t.Fatalf("settings = %+v %v", got, err)
	}
	if err := s.SetAsOf(ctx, pid, nil, ""); err != nil {
		t.Fatal(err)
	}
	if got, _ := s.GetProjectSettings(ctx, pid); got.AsOfOverride != nil {
		t.Fatal("nil must clear the override")
	}
}
```

- [ ] **Step 2: Chạy — FAIL**
```bash
cd ennam.kg.go && export KG_TEST_DATABASE_URL="postgres://ennam_kg:${KG_DB_PASSWORD:-ennam_kg_dev}@localhost:5433/ennam_kg?sslmode=disable"
go test -v -count=1 ./internal/intel/intelstore/ 2>&1 | tee /tmp/planb.out | grep -E "^(--- |ok|FAIL)"
grep -c -- '--- SKIP' /tmp/planb.out   # phải in 0 — test DB bị SKIP vẫn báo ok
```
Expected: FAIL — `undefined: intelstore.New` (compile error).

- [ ] **Step 3: Implement**
`internal/intel/intelstore/store.go`:
```go
// Package intelstore is the PostgreSQL storage of the metrics layer: pack_install,
// project_mapping, metric_value and data_status (master §2.3).
package intelstore

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/lib/pq"

	"github.com/ennam/ennam-kg/internal/intel"
)

// Store wraps the DAAB database.
type Store struct{ db *sql.DB }

// New returns a Store.
func New(db *sql.DB) *Store { return &Store{db: db} }

// DB exposes the handle (advisory locks need a dedicated connection).
func (s *Store) DB() *sql.DB { return s.db }

// ---------- pack_install ----------

// Install is one pack_install row.
type Install struct {
	PackKey     string
	Version     string
	Enabled     bool
	InstalledAt time.Time
}

// ListInstalls returns every pack row of a project, sorted by key.
func (s *Store) ListInstalls(ctx context.Context, projectID string) ([]Install, error) {
	rows, err := s.db.QueryContext(ctx,
		`SELECT pack_key, version, enabled, installed_at FROM pack_install WHERE project_id = $1 ORDER BY pack_key`, projectID)
	if err != nil {
		return nil, fmt.Errorf("intelstore: list installs: %w", err)
	}
	defer rows.Close()
	var out []Install
	for rows.Next() {
		var in Install
		if err := rows.Scan(&in.PackKey, &in.Version, &in.Enabled, &in.InstalledAt); err != nil {
			return nil, fmt.Errorf("intelstore: scan install: %w", err)
		}
		out = append(out, in)
	}
	return out, rows.Err()
}

// UpsertInstall enables (or disables) a pack for a project at a version.
func (s *Store) UpsertInstall(ctx context.Context, projectID, packKey, version string, enabled bool) error {
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO pack_install (project_id, pack_key, version, enabled)
		VALUES ($1, $2, $3, $4)
		ON CONFLICT (project_id, pack_key) DO UPDATE
		SET version = EXCLUDED.version, enabled = EXCLUDED.enabled, installed_at = now()`,
		projectID, packKey, version, enabled)
	if err != nil {
		return fmt.Errorf("intelstore: upsert install: %w", err)
	}
	return nil
}

// ProjectsWithEnabledPacks lists projects that have at least one enabled pack.
func (s *Store) ProjectsWithEnabledPacks(ctx context.Context) ([]string, error) {
	rows, err := s.db.QueryContext(ctx,
		`SELECT DISTINCT project_id::text FROM pack_install WHERE enabled ORDER BY 1`)
	if err != nil {
		return nil, fmt.Errorf("intelstore: projects with packs: %w", err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out = append(out, id)
	}
	return out, rows.Err()
}

// ---------- project_intel_settings ----------

// ProjectSettings is the per-project row of project_intel_settings (zero value
// when the project has none).
type ProjectSettings struct {
	AsOfOverride *time.Time // as-of override: last data day, inclusive
	Timezone     string     // business timezone override ("" = none)
}

// GetProjectSettings returns the project's settings or the zero value.
func (s *Store) GetProjectSettings(ctx context.Context, projectID string) (ProjectSettings, error) {
	var out ProjectSettings
	var asOf sql.NullTime
	var tz sql.NullString
	err := s.db.QueryRowContext(ctx,
		`SELECT as_of_override, timezone FROM project_intel_settings WHERE project_id = $1`, projectID).Scan(&asOf, &tz)
	if errors.Is(err, sql.ErrNoRows) {
		return out, nil
	}
	if err != nil {
		return out, fmt.Errorf("intelstore: get project settings: %w", err)
	}
	if asOf.Valid {
		d := time.Date(asOf.Time.Year(), asOf.Time.Month(), asOf.Time.Day(), 0, 0, 0, 0, time.UTC)
		out.AsOfOverride = &d
	}
	out.Timezone = tz.String
	return out, nil
}

// SetAsOf sets (asOf != nil) or clears (nil) the as-of override; timezone is
// written only when non-empty.
func (s *Store) SetAsOf(ctx context.Context, projectID string, asOf *time.Time, timezone string) error {
	var d, tz any
	if asOf != nil {
		d = asOf.Format("2006-01-02")
	}
	if timezone != "" {
		tz = timezone
	}
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO project_intel_settings (project_id, as_of_override, timezone) VALUES ($1, $2, $3)
		ON CONFLICT (project_id) DO UPDATE SET
		  as_of_override = EXCLUDED.as_of_override,
		  timezone = COALESCE(EXCLUDED.timezone, project_intel_settings.timezone),
		  updated_at = now()`, projectID, d, tz)
	if err != nil {
		return fmt.Errorf("intelstore: set as-of: %w", err)
	}
	return nil
}

// ---------- project_mapping ----------

// ListMappings returns every mapping of a project (all statuses), sorted by entity.
func (s *Store) ListMappings(ctx context.Context, projectID string) ([]intel.Mapping, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT id::text, entity, mode, COALESCE(data_source_id::text, ''), COALESCE(file_dataset, ''),
		       spec, status, version, updated_at
		FROM project_mapping WHERE project_id = $1 ORDER BY entity`, projectID)
	if err != nil {
		return nil, fmt.Errorf("intelstore: list mappings: %w", err)
	}
	defer rows.Close()
	var out []intel.Mapping
	for rows.Next() {
		m := intel.Mapping{ProjectID: projectID}
		var mode string
		var spec []byte
		if err := rows.Scan(&m.ID, &m.Entity, &mode, &m.DataSourceID, &m.FileDataset, &spec, &m.Status, &m.Version, &m.UpdatedAt); err != nil {
			return nil, fmt.Errorf("intelstore: scan mapping: %w", err)
		}
		m.Mode = intel.SourceMode(mode)
		if err := json.Unmarshal(spec, &m.Spec); err != nil {
			return nil, fmt.Errorf("intelstore: mapping %s spec: %w", m.Entity, err)
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

// UpsertMapping inserts or replaces the mapping of (project, entity). The version
// increases only when mode, source or spec actually change. approvedBy is
// recorded when m.Status is approved. Returns the stored version.
func (s *Store) UpsertMapping(ctx context.Context, m intel.Mapping, approvedBy string) (int, error) {
	spec, err := json.Marshal(m.Spec)
	if err != nil {
		return 0, fmt.Errorf("intelstore: marshal spec: %w", err)
	}
	var dsID, dataset, by any
	var at any
	if m.DataSourceID != "" {
		dsID = m.DataSourceID
	}
	if m.FileDataset != "" {
		dataset = m.FileDataset
	}
	if m.Status == intel.MappingApproved {
		by, at = approvedBy, time.Now().UTC()
	}
	var version int
	err = s.db.QueryRowContext(ctx, `
		INSERT INTO project_mapping (project_id, entity, mode, data_source_id, file_dataset, spec, status, version, approved_by, approved_at)
		VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, 1, $8, $9)
		ON CONFLICT (project_id, entity) DO UPDATE SET
		  version = project_mapping.version + CASE
		    WHEN project_mapping.spec IS DISTINCT FROM EXCLUDED.spec
		      OR project_mapping.mode <> EXCLUDED.mode
		      OR project_mapping.data_source_id IS DISTINCT FROM EXCLUDED.data_source_id
		      OR project_mapping.file_dataset IS DISTINCT FROM EXCLUDED.file_dataset
		    THEN 1 ELSE 0 END,
		  mode = EXCLUDED.mode, data_source_id = EXCLUDED.data_source_id,
		  file_dataset = EXCLUDED.file_dataset, spec = EXCLUDED.spec, status = EXCLUDED.status,
		  approved_by = EXCLUDED.approved_by, approved_at = EXCLUDED.approved_at, updated_at = now()
		RETURNING version`,
		m.ProjectID, m.Entity, string(m.Mode), dsID, dataset, string(spec), m.Status, by, at).Scan(&version)
	if err != nil {
		return 0, fmt.Errorf("intelstore: upsert mapping %s: %w", m.Entity, err)
	}
	return version, nil
}

// SetMappingStatus changes the status of one mapping (runner: approved → broken).
func (s *Store) SetMappingStatus(ctx context.Context, projectID, entity, status string) error {
	res, err := s.db.ExecContext(ctx,
		`UPDATE project_mapping SET status = $3, updated_at = now() WHERE project_id = $1 AND entity = $2`,
		projectID, entity, status)
	if err != nil {
		return fmt.Errorf("intelstore: set mapping status: %w", err)
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return fmt.Errorf("intelstore: mapping %s not found", entity)
	}
	return nil
}

// ---------- metric_value ----------

// MetricRow is one computed (period, dims) row of a metric.
type MetricRow struct {
	PeriodDate  time.Time
	Dims        map[string]string
	DimsHash    string
	Value       *float64
	Numerator   *float64
	Denominator *float64
	SampleSize  int
}

// WriteMeta describes where a batch of rows came from.
type WriteMeta struct {
	ProjectID     string
	MetricKey     string
	MetricVersion int
	PackVersion   string
	SourceMode    intel.SourceMode
	Watermark     string
}

const insertBatch = 500

// ReplaceMetricRows deletes the stored rows of the metric with period in
// [deleteFrom, deleteTo) (when deleteFrom != nil) and upserts rows, in one
// transaction — so a recomputed window never keeps a dims combination that
// disappeared at the source (late data, spec §6.1 lookback).
func (s *Store) ReplaceMetricRows(ctx context.Context, meta WriteMeta, deleteFrom, deleteTo *time.Time, rows []MetricRow) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("intelstore: begin: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	if deleteFrom != nil && deleteTo != nil {
		if _, err := tx.ExecContext(ctx,
			`DELETE FROM metric_value WHERE project_id = $1 AND metric_key = $2 AND period_date >= $3 AND period_date < $4`,
			meta.ProjectID, meta.MetricKey, deleteFrom.Format("2006-01-02"), deleteTo.Format("2006-01-02")); err != nil {
			return fmt.Errorf("intelstore: delete window: %w", err)
		}
	}
	var watermark any
	if meta.Watermark != "" {
		watermark = meta.Watermark
	}
	for start := 0; start < len(rows); start += insertBatch {
		end := min(start+insertBatch, len(rows))
		var sb strings.Builder
		sb.WriteString(`INSERT INTO metric_value (project_id, metric_key, period_date, dims, dims_hash, value, numerator, denominator,
			sample_size, metric_version, pack_version, source_mode, source_watermark) VALUES `)
		args := make([]any, 0, (end-start)*13)
		for i, r := range rows[start:end] {
			dims, err := json.Marshal(r.Dims)
			if err != nil {
				return fmt.Errorf("intelstore: marshal dims: %w", err)
			}
			if i > 0 {
				sb.WriteString(", ")
			}
			b := len(args)
			fmt.Fprintf(&sb, "($%d,$%d,$%d,$%d::jsonb,$%d,$%d,$%d,$%d,$%d,$%d,$%d,$%d,$%d)",
				b+1, b+2, b+3, b+4, b+5, b+6, b+7, b+8, b+9, b+10, b+11, b+12, b+13)
			args = append(args, meta.ProjectID, meta.MetricKey, r.PeriodDate.Format("2006-01-02"), string(dims), r.DimsHash,
				nullable(r.Value), nullable(r.Numerator), nullable(r.Denominator), r.SampleSize,
				meta.MetricVersion, meta.PackVersion, string(meta.SourceMode), watermark)
		}
		sb.WriteString(` ON CONFLICT (project_id, metric_key, period_date, dims_hash) DO UPDATE SET
			dims = EXCLUDED.dims, value = EXCLUDED.value, numerator = EXCLUDED.numerator,
			denominator = EXCLUDED.denominator, sample_size = EXCLUDED.sample_size,
			metric_version = EXCLUDED.metric_version, pack_version = EXCLUDED.pack_version,
			source_mode = EXCLUDED.source_mode, source_watermark = EXCLUDED.source_watermark,
			computed_at = now()`)
		if _, err := tx.ExecContext(ctx, sb.String(), args...); err != nil {
			return fmt.Errorf("intelstore: upsert metric rows: %w", err)
		}
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("intelstore: commit: %w", err)
	}
	return nil
}

func nullable(f *float64) any {
	if f == nil {
		return nil
	}
	return *f
}

// SeriesExtent reports the highest stored metric_version and the earliest stored
// period of a metric (found=false when nothing is stored); the runner reports the
// earliest period as data_status.period_from.
func (s *Store) SeriesExtent(ctx context.Context, projectID, metricKey string) (maxVersion int, minPeriod time.Time, found bool, err error) {
	var v sql.NullInt64
	var p sql.NullTime
	err = s.db.QueryRowContext(ctx,
		`SELECT MAX(metric_version), MIN(period_date) FROM metric_value WHERE project_id = $1 AND metric_key = $2`,
		projectID, metricKey).Scan(&v, &p)
	if err != nil {
		return 0, time.Time{}, false, fmt.Errorf("intelstore: series extent: %w", err)
	}
	if !v.Valid {
		return 0, time.Time{}, false, nil
	}
	return int(v.Int64), p.Time, true, nil
}

// StaleSince returns the earliest stored period whose metric_version is lower than
// version (found=false when every stored row is current). The runner recomputes
// from there, so a version-bump backfill that failed half-way resumes on the next
// run instead of leaving old-version periods forever (MAX(version) would hide them).
func (s *Store) StaleSince(ctx context.Context, projectID, metricKey string, version int) (time.Time, bool, error) {
	var p sql.NullTime
	err := s.db.QueryRowContext(ctx,
		`SELECT MIN(period_date) FROM metric_value WHERE project_id = $1 AND metric_key = $2 AND metric_version < $3`,
		projectID, metricKey, version).Scan(&p)
	if err != nil {
		return time.Time{}, false, fmt.Errorf("intelstore: stale since: %w", err)
	}
	return p.Time, p.Valid, nil
}

// SeriesQuery selects and rolls up stored rows (read path of kg_get_metrics).
type SeriesQuery struct {
	ProjectID   string
	MetricKey   string
	From, To    time.Time // [From, To)
	Grain       string    // day | week | month | total
	GroupBy     []string  // dims kept in the output (already intersected with the metric dims)
	Filter      map[string][]string
	Aggregation intel.Aggregation
}

// SeriesPoint is one rolled-up point. For ratio metrics Value is nil and the
// caller derives it from Numerator/Denominator (engine.RatioValue).
type SeriesPoint struct {
	Period      time.Time
	Dims        map[string]string
	Value       *float64
	Numerator   *float64
	Denominator *float64
	SampleSize  int64
}

// QuerySeries aggregates in SQL: additive = SUM(value); ratio = SUM(numerator),
// SUM(denominator); snapshot = SUM over the group of the values on the last
// period_date of each bucket. dims_filter is applied in the WHERE clause.
func (s *Store) QuerySeries(ctx context.Context, q SeriesQuery) ([]SeriesPoint, error) {
	args := []any{q.ProjectID, q.MetricKey, q.From.Format("2006-01-02"), q.To.Format("2006-01-02")}
	arg := func(v any) string { args = append(args, v); return fmt.Sprintf("$%d", len(args)) }

	var bucket string
	switch q.Grain {
	case "day":
		bucket = "period_date"
	case "week":
		bucket = "CAST(date_trunc('week', period_date) AS date)"
	case "month":
		bucket = "CAST(date_trunc('month', period_date) AS date)"
	case "total":
		bucket = "CAST($3 AS date)"
	default:
		return nil, fmt.Errorf("intelstore: unknown grain %q", q.Grain)
	}
	where := "project_id = $1 AND metric_key = $2 AND period_date >= CAST($3 AS date) AND period_date < CAST($4 AS date)"
	for _, k := range sortedKeys(q.Filter) {
		where += fmt.Sprintf(" AND dims->>%s = ANY(%s)", arg(k), arg(pq.Array(q.Filter[k])))
	}
	groupCols := make([]string, len(q.GroupBy))
	groupSel := ""
	for i, g := range q.GroupBy {
		groupCols[i] = fmt.Sprintf("g%d", i)
		groupSel += fmt.Sprintf(", dims->>%s AS g%d", arg(g), i)
	}
	gl := ""
	if len(groupCols) > 0 {
		gl = ", " + strings.Join(groupCols, ", ")
	}

	var query string
	switch q.Aggregation {
	case intel.AggAdditive:
		query = fmt.Sprintf(`WITH f AS (SELECT %s AS period%s, value, numerator, denominator, sample_size FROM metric_value WHERE %s)
			SELECT period%s, SUM(value), CAST(NULL AS numeric), CAST(NULL AS numeric), SUM(sample_size) FROM f GROUP BY period%s ORDER BY period%s`,
			bucket, groupSel, where, gl, gl, gl)
	case intel.AggRatio:
		query = fmt.Sprintf(`WITH f AS (SELECT %s AS period%s, value, numerator, denominator, sample_size FROM metric_value WHERE %s)
			SELECT period%s, CAST(NULL AS numeric), SUM(numerator), SUM(denominator), SUM(sample_size) FROM f GROUP BY period%s ORDER BY period%s`,
			bucket, groupSel, where, gl, gl, gl)
	case intel.AggSnapshot:
		join := "f.period = l.period AND f.period_date = l.last_date"
		fgl := ""
		for _, c := range groupCols {
			join += fmt.Sprintf(" AND f.%s IS NOT DISTINCT FROM l.%s", c, c)
			fgl += ", f." + c
		}
		query = fmt.Sprintf(`WITH f AS (SELECT %s AS period%s, period_date, value, sample_size FROM metric_value WHERE %s),
			l AS (SELECT period%s, MAX(period_date) AS last_date FROM f GROUP BY period%s)
			SELECT f.period%s, SUM(f.value), CAST(NULL AS numeric), CAST(NULL AS numeric), SUM(f.sample_size)
			FROM f JOIN l ON %s GROUP BY f.period%s ORDER BY f.period%s`,
			bucket, groupSel, where, gl, gl, fgl, join, fgl, fgl)
	default:
		return nil, fmt.Errorf("intelstore: unknown aggregation %q", q.Aggregation)
	}

	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("intelstore: query series: %w", err)
	}
	defer rows.Close()
	var out []SeriesPoint
	for rows.Next() {
		var p SeriesPoint
		groups := make([]sql.NullString, len(q.GroupBy))
		dest := []any{&p.Period}
		for i := range groups {
			dest = append(dest, &groups[i])
		}
		var v, n, d sql.NullFloat64
		var ss sql.NullInt64
		dest = append(dest, &v, &n, &d, &ss)
		if err := rows.Scan(dest...); err != nil {
			return nil, fmt.Errorf("intelstore: scan series: %w", err)
		}
		p.Dims = map[string]string{}
		for i, g := range q.GroupBy {
			if groups[i].Valid {
				p.Dims[g] = groups[i].String
			}
		}
		p.Value, p.Numerator, p.Denominator = ptr(v), ptr(n), ptr(d)
		p.SampleSize = ss.Int64
		out = append(out, p)
	}
	return out, rows.Err()
}

func ptr(n sql.NullFloat64) *float64 {
	if !n.Valid {
		return nil
	}
	v := n.Float64
	return &v
}

// VersionsInSeries returns the distinct metric_version values stored in [from, to).
func (s *Store) VersionsInSeries(ctx context.Context, projectID, metricKey string, from, to time.Time) ([]int, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT DISTINCT metric_version FROM metric_value
		WHERE project_id = $1 AND metric_key = $2 AND period_date >= $3 AND period_date < $4 ORDER BY 1`,
		projectID, metricKey, from.Format("2006-01-02"), to.Format("2006-01-02"))
	if err != nil {
		return nil, fmt.Errorf("intelstore: versions in series: %w", err)
	}
	defer rows.Close()
	out := []int{}
	for rows.Next() {
		var v int
		if err := rows.Scan(&v); err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

// ---------- data_status ----------

// UpsertDataStatus writes one subject's status.
func (s *Store) UpsertDataStatus(ctx context.Context, st intel.DataStatus) error {
	issues := st.Issues
	if issues == nil {
		issues = []intel.Issue{}
	}
	raw, err := json.Marshal(issues)
	if err != nil {
		return fmt.Errorf("intelstore: marshal issues: %w", err)
	}
	_, err = s.db.ExecContext(ctx, `
		INSERT INTO data_status (project_id, subject, status, last_success_at, period_from, period_to, issues, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, now())
		ON CONFLICT (project_id, subject) DO UPDATE SET
		  status = EXCLUDED.status,
		  last_success_at = COALESCE(EXCLUDED.last_success_at, data_status.last_success_at),
		  period_from = COALESCE(EXCLUDED.period_from, data_status.period_from),
		  period_to = COALESCE(EXCLUDED.period_to, data_status.period_to),
		  issues = EXCLUDED.issues, updated_at = now()`,
		st.ProjectID, st.Subject, st.Status, st.LastSuccessAt, dateOrNil(st.PeriodFrom), dateOrNil(st.PeriodTo), string(raw))
	if err != nil {
		return fmt.Errorf("intelstore: upsert data status %s: %w", st.Subject, err)
	}
	return nil
}

func dateOrNil(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.Format("2006-01-02")
}

// ListDataStatus returns all subjects of a project sorted by subject.
func (s *Store) ListDataStatus(ctx context.Context, projectID string) ([]intel.DataStatus, error) {
	rows, err := s.db.QueryContext(ctx, `
		SELECT subject, status, last_success_at, period_from, period_to, issues, updated_at
		FROM data_status WHERE project_id = $1 ORDER BY subject`, projectID)
	if err != nil {
		return nil, fmt.Errorf("intelstore: list data status: %w", err)
	}
	defer rows.Close()
	var out []intel.DataStatus
	for rows.Next() {
		st := intel.DataStatus{ProjectID: projectID}
		var last, pf, pt sql.NullTime
		var issues []byte
		if err := rows.Scan(&st.Subject, &st.Status, &last, &pf, &pt, &issues, &st.UpdatedAt); err != nil {
			return nil, fmt.Errorf("intelstore: scan data status: %w", err)
		}
		st.LastSuccessAt, st.PeriodFrom, st.PeriodTo = timePtr(last), timePtr(pf), timePtr(pt)
		if err := json.Unmarshal(issues, &st.Issues); err != nil {
			return nil, fmt.Errorf("intelstore: data status issues: %w", err)
		}
		out = append(out, st)
	}
	return out, rows.Err()
}

// GetDataStatus returns one subject or (nil, nil) when absent.
func (s *Store) GetDataStatus(ctx context.Context, projectID, subject string) (*intel.DataStatus, error) {
	all, err := s.ListDataStatus(ctx, projectID)
	if err != nil {
		return nil, err
	}
	for i := range all {
		if all[i].Subject == subject {
			return &all[i], nil
		}
	}
	return nil, nil
}

func timePtr(t sql.NullTime) *time.Time {
	if !t.Valid {
		return nil
	}
	v := t.Time
	return &v
}

func sortedKeys(m map[string][]string) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
```

- [ ] **Step 4: Chạy — PASS, 0 SKIP**
```bash
cd ennam.kg.go && export KG_TEST_DATABASE_URL="postgres://ennam_kg:${KG_DB_PASSWORD:-ennam_kg_dev}@localhost:5433/ennam_kg?sslmode=disable"
go test -v -count=1 ./internal/intel/intelstore/ 2>&1 | tee /tmp/planb.out | grep -E "^(--- |ok|FAIL)"
grep -c -- '--- SKIP' /tmp/planb.out   # phải in 0 — test DB bị SKIP vẫn báo ok
```
Expected: 4 test PASS (`TestStore_InstallsAndMappingVersioning`, `TestStore_ReplaceWindowDeletesVanishedRows`, `TestStore_DataStatusKeepsLastSuccess`, `TestStore_ProjectSettings`); dòng cuối in `0`.

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.go add internal/intel/intelstore
git -C ennam.kg.go commit -m "feat(intel): storage for packs, mappings, metric values and data status" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 7: `SourceExecutor.ExecuteWithLimit` + executor DAAB (`sqlexec`) + resolver `mode=live`

**Files:**
- Modify `internal/service/source_executor.go:64-75` (thêm `ExecuteWithLimit`, `Execute` uỷ quyền) và `:139` (dùng `rowLimit`).
- Create `internal/service/source_executor_limit_test.go`, `internal/intel/sqlexec/sqlexec.go`, `internal/intel/sqlexec/sqlexec_test.go`, `internal/intel/livesource/live.go`, `internal/intel/livesource/live_test.go`.

**Interfaces:**
- Produces: `func (e *SourceExecutor) ExecuteWithLimit(ctx, dataSourceID, sqlQuery string, params []interface{}, rowLimit int) (*QueryResult, error)` (rowLimit ≤ 0 ⇒ 10.000 như cũ); `func sqlexec.New(db *sql.DB, timeout time.Duration) *sqlexec.Executor` (implements `intel.QueryExecutor`); `func livesource.New(db *sql.DB, ds dataSourceGetter, sync schemaSyncer, exec sourceExecutor) *livesource.Resolver` (implements `intel.SourceResolver`), `livesource.Table{Schema, Name, Cols}`, `livesource.SyncActor = "metric-runner"`.
- Consumes: `store.DataSourceStore.GetByID`, `service.SchemaSyncService.SyncSchema(ctx, dsID, createdBy, dryRun)` (I11 — runner gọi trước mỗi lần chạy), metadata `source_schemas/tables/columns`.

Blast radius `Execute`: 4 caller (`nl_query.go:89,181,219`, `value_hints.go:129`) — hành vi giữ nguyên (cap 10.000), LOW.

- [ ] **Step 1: Viết test (failing)**
`internal/service/source_executor_limit_test.go`:
```go
package service

import (
	"context"
	"crypto/rand"
	"database/sql"
	"fmt"
	"os"
	"testing"
	"time"

	"github.com/ennam/ennam-kg/internal/crypto"
	"github.com/ennam/ennam-kg/internal/store"
)

// TestSourceExecutor_ExecuteWithLimit_Truncates verifies the caller-chosen row cap
// (metric runner) and that Execute keeps its historical 10,000 cap. Integration:
// the "source" is the test database itself.
func TestSourceExecutor_ExecuteWithLimit_Truncates(t *testing.T) {
	dsn := os.Getenv("KG_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("Skipping integration test: KG_TEST_DATABASE_URL not set")
	}
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	ctx := context.Background()

	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		t.Fatal(err)
	}
	enc, err := crypto.Encrypt([]byte(dsn), key)
	if err != nil {
		t.Fatal(err)
	}
	var projectID, dsID string
	if err := db.QueryRowContext(ctx, `INSERT INTO projects (name) VALUES ($1) RETURNING id::text`,
		fmt.Sprintf("exec-limit-%d", time.Now().UnixNano())).Scan(&projectID); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = db.Exec(`DELETE FROM data_sources WHERE project_id = $1`, projectID)
		_, _ = db.Exec(`DELETE FROM projects WHERE id = $1`, projectID)
	})
	if err := db.QueryRowContext(ctx, `
		INSERT INTO data_sources (project_id, name, db_type, host, port, database_name, connection_string_encrypted, created_by)
		VALUES ($1, 'self', 'postgresql', 'localhost', 5432, 'test', $2, 'test') RETURNING id::text`,
		projectID, enc).Scan(&dsID); err != nil {
		t.Fatal(err)
	}

	exec := NewSourceExecutor(store.NewDataSourceStore(db), key, nil)
	res, err := exec.ExecuteWithLimit(ctx, dsID, "SELECT g FROM generate_series(1, 20) g", nil, 5)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Truncated || res.RowCount != 5 {
		t.Fatalf("limit 5: truncated=%v rows=%d, want true/5", res.Truncated, res.RowCount)
	}
	res, err = exec.Execute(ctx, dsID, "SELECT g FROM generate_series(1, 20) g", nil)
	if err != nil || res.Truncated || res.RowCount != 20 {
		t.Fatalf("default cap: %+v %v", res, err)
	}
}
```

`internal/intel/sqlexec/sqlexec_test.go`:
```go
package sqlexec_test

import (
	"context"
	"database/sql"
	"os"
	"strings"
	"testing"

	_ "github.com/lib/pq"

	"github.com/ennam/ennam-kg/internal/intel/sqlexec"
)

func TestExecutor_ReadOnlyAndTruncation(t *testing.T) {
	url := os.Getenv("KG_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("Skipping integration test: KG_TEST_DATABASE_URL not set")
	}
	db, err := sql.Open("postgres", url)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	e := sqlexec.New(db, 0)
	ctx := context.Background()

	res, err := e.Query(ctx, "SELECT g, CAST(g AS numeric) / 2 AS half FROM generate_series(1, 10) g", nil, 4)
	if err != nil {
		t.Fatal(err)
	}
	if !res.Truncated || len(res.Rows) != 4 || res.Columns[1] != "half" {
		t.Fatalf("res = %+v", res)
	}
	if _, ok := res.Rows[0][1].(string); !ok {
		t.Fatalf("numeric must come back as string, got %T", res.Rows[0][1])
	}
	_, err = e.Query(ctx, "CREATE TEMP TABLE intel_should_fail (x int)", nil, 1)
	if err == nil || !strings.Contains(err.Error(), "read-only") {
		t.Fatalf("write must fail in a read-only transaction, got %v", err)
	}
}
```

`internal/intel/livesource/live_test.go`:
```go
package livesource

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"testing"
	"time"

	_ "github.com/lib/pq"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/service"
)

type fakeDS struct {
	projectID string
	dbType    string // "" = postgresql
}

func (f fakeDS) GetByID(_ context.Context, id string) (*models.DataSource, error) {
	t := f.dbType
	if t == "" {
		t = "postgresql"
	}
	return &models.DataSource{ID: id, ProjectID: f.projectID, DBType: t}, nil
}

// The compiler only emits PostgreSQL: a mapping on an MSSQL/MySQL source must be
// refused as a mapping error (⇒ broken), never run.
func TestBind_RejectsNonPostgresSource(t *testing.T) {
	for _, dbType := range []string{"mssql", "mysql", "mariadb"} {
		r := New(nil, fakeDS{projectID: "p", dbType: dbType}, nil, nil)
		_, err := r.Bind(context.Background(), "p", intel.Mapping{Entity: "order", Mode: intel.ModeLive, DataSourceID: "ds", Spec: intel.MappingSpec{From: "orders"}})
		var me *intel.MappingError
		if !errors.As(err, &me) || me.Code != "unsupported_source" {
			t.Errorf("%s: want unsupported_source, got %v", dbType, err)
		}
	}
}

type fakeSync struct{ calls []string }

func (f *fakeSync) SyncSchema(_ context.Context, id, _ string, _ bool) (*service.SyncResult, error) {
	f.calls = append(f.calls, id)
	return &service.SyncResult{}, nil
}

type fakeExec struct {
	gotLimit int
	res      *service.QueryResult
}

func (f *fakeExec) ExecuteWithLimit(_ context.Context, _ string, _ string, _ []interface{}, limit int) (*service.QueryResult, error) {
	f.gotLimit = limit
	return f.res, nil
}

func TestExecutor_OrdersColumnsAndPassesLimit(t *testing.T) {
	fe := &fakeExec{res: &service.QueryResult{Columns: []string{"b", "a"},
		Rows: []map[string]interface{}{{"a": 1, "b": "x"}}, Truncated: true}}
	e := &Executor{exec: fe, dataSourceID: "ds"}
	rows, err := e.Query(context.Background(), "SELECT 1", nil, 77)
	if err != nil {
		t.Fatal(err)
	}
	if fe.gotLimit != 77 || !rows.Truncated || rows.Rows[0][0] != "x" || rows.Rows[0][1] != 1 {
		t.Fatalf("rows = %+v limit=%d", rows, fe.gotLimit)
	}
}

func TestPrepare_SyncsEachLiveSourceOnce(t *testing.T) {
	fs := &fakeSync{}
	r := New(nil, fakeDS{projectID: "p"}, fs, nil)
	ms := []intel.Mapping{
		{Entity: "a", Mode: intel.ModeLive, DataSourceID: "ds1"},
		{Entity: "b", Mode: intel.ModeLive, DataSourceID: "ds1"},
		{Entity: "c", Mode: intel.ModeFile},
	}
	if err := r.Prepare(context.Background(), "p", ms); err != nil {
		t.Fatal(err)
	}
	if len(fs.calls) != 1 || fs.calls[0] != "ds1" {
		t.Fatalf("sync calls = %v", fs.calls)
	}
	if err := New(nil, fakeDS{projectID: "other"}, fs, nil).Prepare(context.Background(), "p", ms); err == nil {
		t.Fatal("data source of another project must be refused")
	}
}

// TestBind_UsesSyncedMetadata needs the DAAB schema (source_* tables).
func TestBind_UsesSyncedMetadata(t *testing.T) {
	url := os.Getenv("KG_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("Skipping integration test: KG_TEST_DATABASE_URL not set")
	}
	db, err := sql.Open("postgres", url)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	ctx := context.Background()
	var pid, dsID, schemaID, tableID string
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	must(db.QueryRow(`INSERT INTO projects (name) VALUES ($1) RETURNING id::text`, fmt.Sprintf("live-bind-%d", time.Now().UnixNano())).Scan(&pid))
	must(db.QueryRow(`INSERT INTO data_sources (project_id, name, host, database_name, connection_string_encrypted, created_by)
		VALUES ($1, 'src', 'h', 'd', '\x00', 't') RETURNING id::text`, pid).Scan(&dsID))
	t.Cleanup(func() {
		_, _ = db.Exec(`DELETE FROM source_schemas WHERE data_source_id = $1`, dsID)
		_, _ = db.Exec(`DELETE FROM data_sources WHERE id = $1`, dsID)
		_, _ = db.Exec(`DELETE FROM projects WHERE id = $1`, pid)
	})
	must(db.QueryRow(`INSERT INTO source_schemas (data_source_id, schema_name) VALUES ($1, 'public') RETURNING id::text`, dsID).Scan(&schemaID))
	must(db.QueryRow(`INSERT INTO source_tables (source_schema_id, table_name) VALUES ($1, 'orders') RETURNING id::text`, schemaID).Scan(&tableID))
	_, err = db.Exec(`INSERT INTO source_columns (source_table_id, column_name, data_type, ordinal_position) VALUES
		($1, 'id', 'text', 1), ($1, 'created_at', 'timestamp with time zone', 2)`, tableID)
	must(err)

	r := New(db, fakeDS{projectID: pid}, nil, &fakeExec{})
	b, err := r.Bind(ctx, pid, intel.Mapping{Entity: "order", Mode: intel.ModeLive, DataSourceID: dsID, Spec: intel.MappingSpec{From: "orders"}})
	if err != nil {
		t.Fatal(err)
	}
	cols := b.Table.Columns()
	if len(cols) != 2 || cols[1].DataType != "timestamp with time zone" || b.Table.Relation() != `"public"."orders" AS src` {
		t.Fatalf("table = %+v %s", cols, b.Table.Relation())
	}
	_, err = r.Bind(ctx, pid, intel.Mapping{Entity: "order", Mode: intel.ModeLive, DataSourceID: dsID, Spec: intel.MappingSpec{From: "public.gone"}})
	var me *intel.MappingError
	if !errors.As(err, &me) || me.Code != "missing_table" {
		t.Fatalf("want missing_table, got %v", err)
	}
}
```

- [ ] **Step 2: Chạy — FAIL**
```bash
cd ennam.kg.go && export KG_TEST_DATABASE_URL="postgres://ennam_kg:${KG_DB_PASSWORD:-ennam_kg_dev}@localhost:5433/ennam_kg?sslmode=disable"
go test -v -count=1 -run 'ExecuteWithLimit|TestExecutor|TestPrepare|TestBind' ./internal/service/ ./internal/intel/sqlexec/ ./internal/intel/livesource/ 2>&1 | tee /tmp/planb.out | grep -E "^(--- |ok|FAIL)"
grep -c -- '--- SKIP' /tmp/planb.out   # phải in 0 — test DB bị SKIP vẫn báo ok
```
Expected: FAIL — `exec.ExecuteWithLimit undefined`, `undefined: sqlexec.New`, `undefined: New`.

- [ ] **Step 3: Implement**

Sửa `internal/service/source_executor.go`:
Thay đoạn (khớp chính xác):
```go
// Execute runs parameterized SQL against the source database identified by dataSourceID.
// Enforces a 30-second timeout and a 10,000 row limit.
func (e *SourceExecutor) Execute(
	ctx context.Context,
	dataSourceID string,
	sqlQuery string,
	params []interface{},
) (*QueryResult, error) {
```
bằng:
```go
// Execute runs parameterized SQL against the source database identified by dataSourceID.
// Enforces a 30-second timeout and a 10,000 row limit.
func (e *SourceExecutor) Execute(
	ctx context.Context,
	dataSourceID string,
	sqlQuery string,
	params []interface{},
) (*QueryResult, error) {
	return e.ExecuteWithLimit(ctx, dataSourceID, sqlQuery, params, maxRows)
}

// ExecuteWithLimit is Execute with a caller-chosen row cap (rowLimit <= 0 means the
// default 10,000). The metric runner uses its own cap and treats Truncated=true
// as an error (spec §6.1) instead of the NL→SQL cap.
func (e *SourceExecutor) ExecuteWithLimit(
	ctx context.Context,
	dataSourceID string,
	sqlQuery string,
	params []interface{},
	rowLimit int,
) (*QueryResult, error) {
	if rowLimit <= 0 {
		rowLimit = maxRows
	}
```

Thay đoạn (khớp chính xác):
```go
		if len(resultRows) >= maxRows {
```
bằng:
```go
		if len(resultRows) >= rowLimit {
```

`internal/intel/sqlexec/sqlexec.go`:
```go
// Package sqlexec runs compiled intel statements inside a database/sql handle in
// a READ ONLY transaction with a timeout. It backs mode=file (rows stored in the
// DAAB database, Plan C) and the metric fixture tests.
package sqlexec

import (
	"context"
	"database/sql"
	"fmt"
	"time"

	"github.com/ennam/ennam-kg/internal/intel"
)

// Executor implements intel.QueryExecutor on a *sql.DB.
type Executor struct {
	db      *sql.DB
	timeout time.Duration
}

// New returns an Executor; timeout <= 0 means 30s (same as source_executor).
func New(db *sql.DB, timeout time.Duration) *Executor {
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	return &Executor{db: db, timeout: timeout}
}

// Query runs sqlText read-only and returns at most maxRows rows; Truncated is set
// when more rows existed. []byte values are returned as string.
func (e *Executor) Query(ctx context.Context, sqlText string, args []any, maxRows int) (*intel.QueryRows, error) {
	ctx, cancel := context.WithTimeout(ctx, e.timeout)
	defer cancel()
	tx, err := e.db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		return nil, fmt.Errorf("sqlexec: begin read-only: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	rows, err := tx.QueryContext(ctx, sqlText, args...)
	if err != nil {
		return nil, fmt.Errorf("sqlexec: query: %w", err)
	}
	defer rows.Close()
	cols, err := rows.Columns()
	if err != nil {
		return nil, fmt.Errorf("sqlexec: columns: %w", err)
	}
	out := &intel.QueryRows{Columns: cols, Rows: [][]any{}}
	for rows.Next() {
		if maxRows > 0 && len(out.Rows) >= maxRows {
			out.Truncated = true
			break
		}
		vals := make([]any, len(cols))
		ptrs := make([]any, len(cols))
		for i := range vals {
			ptrs[i] = &vals[i]
		}
		if err := rows.Scan(ptrs...); err != nil {
			return nil, fmt.Errorf("sqlexec: scan: %w", err)
		}
		for i, v := range vals {
			if b, ok := v.([]byte); ok {
				vals[i] = string(b)
			}
		}
		out.Rows = append(out.Rows, vals)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("sqlexec: rows: %w", err)
	}
	return out, nil
}
```

`internal/intel/livesource/live.go`:
```go
// Package livesource implements intel.SourceResolver for mode=live: the mapping's
// table lives in a customer database registered as a DAAB data source and every
// statement runs through service.SourceExecutor (read-only session, 30s timeout).
// Nothing is created on the customer database (spec D4).
package livesource

import (
	"context"
	"database/sql"
	"fmt"
	"strings"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/models"
	"github.com/ennam/ennam-kg/internal/service"
)

// dataSourceGetter is the part of store.DataSourceStore the resolver needs.
type dataSourceGetter interface {
	GetByID(ctx context.Context, id string) (*models.DataSource, error)
}

// schemaSyncer is the part of service.SchemaSyncService the resolver needs (I11).
type schemaSyncer interface {
	SyncSchema(ctx context.Context, dataSourceID, createdBy string, dryRun bool) (*service.SyncResult, error)
}

// sourceExecutor is the part of service.SourceExecutor the resolver needs.
type sourceExecutor interface {
	ExecuteWithLimit(ctx context.Context, dataSourceID, sqlQuery string, params []interface{}, rowLimit int) (*service.QueryResult, error)
}

// Resolver binds live mappings.
type Resolver struct {
	db   *sql.DB // DAAB database: synced schema metadata (source_* tables)
	ds   dataSourceGetter
	sync schemaSyncer
	exec sourceExecutor
}

// New returns a live resolver. sync may be nil (tests): Prepare then skips the refresh.
func New(db *sql.DB, ds dataSourceGetter, sync schemaSyncer, exec sourceExecutor) *Resolver {
	return &Resolver{db: db, ds: ds, sync: sync, exec: exec}
}

// SyncActor is recorded as created_by on the schema sync jobs the runner starts.
const SyncActor = "metric-runner"

// Prepare refreshes the synced schema of every data source used by ms (spec I11:
// sync used to be manual only; the runner calls it before each run).
func (r *Resolver) Prepare(ctx context.Context, projectID string, ms []intel.Mapping) error {
	seen := map[string]bool{}
	for _, m := range ms {
		if m.Mode != intel.ModeLive || seen[m.DataSourceID] {
			continue
		}
		seen[m.DataSourceID] = true
		if _, err := r.checkProject(ctx, projectID, m.DataSourceID); err != nil {
			return err
		}
		if r.sync == nil {
			continue
		}
		if _, err := r.sync.SyncSchema(ctx, m.DataSourceID, SyncActor, false); err != nil {
			return fmt.Errorf("livesource: sync schema %s: %w", m.DataSourceID, err)
		}
	}
	return nil
}

func (r *Resolver) checkProject(ctx context.Context, projectID, dsID string) (*models.DataSource, error) {
	ds, err := r.ds.GetByID(ctx, dsID)
	if err != nil {
		return nil, fmt.Errorf("livesource: data source %s: %w", dsID, err)
	}
	if ds.ProjectID != projectID {
		return nil, fmt.Errorf("livesource: data source %s belongs to another project", dsID)
	}
	return ds, nil
}

// supportedDBTypes: the compiler emits PostgreSQL (dialect Postgres) and the
// expression lexer assumes standard_conforming_strings; other engines need their
// own dialect first (spec §12b).
var supportedDBTypes = map[string]bool{"postgres": true, "postgresql": true}

// Bind resolves the mapping's [schema.]table against the synced metadata.
func (r *Resolver) Bind(ctx context.Context, projectID string, m intel.Mapping) (*intel.BoundSource, error) {
	if m.Mode != intel.ModeLive {
		return nil, fmt.Errorf("livesource: mapping %s has mode %s", m.Entity, m.Mode)
	}
	ds, err := r.checkProject(ctx, projectID, m.DataSourceID)
	if err != nil {
		return nil, err
	}
	if !supportedDBTypes[ds.DBType] {
		return nil, &intel.MappingError{Entity: m.Entity, Code: "unsupported_source",
			Detail: fmt.Sprintf("data source %s is %q; mode=live supports PostgreSQL only", m.DataSourceID, ds.DBType)}
	}
	schema, table := "public", m.Spec.From
	if s, t, ok := strings.Cut(m.Spec.From, "."); ok {
		schema, table = s, t
	}
	cols, err := r.columns(ctx, m.DataSourceID, schema, table)
	if err != nil {
		return nil, err
	}
	if len(cols) == 0 {
		return nil, &intel.MappingError{Entity: m.Entity, Code: "missing_table",
			Detail: fmt.Sprintf("%s.%s is not in the synced schema of data source %s", schema, table, m.DataSourceID)}
	}
	return &intel.BoundSource{
		Table:    &Table{Schema: schema, Name: table, Cols: cols},
		Executor: &Executor{exec: r.exec, dataSourceID: m.DataSourceID},
	}, nil
}

func (r *Resolver) columns(ctx context.Context, dsID, schema, table string) ([]intel.SourceColumn, error) {
	rows, err := r.db.QueryContext(ctx, `
		SELECT c.column_name, LOWER(c.data_type)
		FROM source_columns c
		JOIN source_tables t ON t.id = c.source_table_id
		JOIN source_schemas s ON s.id = t.source_schema_id
		WHERE s.data_source_id = $1 AND s.schema_name = $2 AND t.table_name = $3
		ORDER BY c.ordinal_position`, dsID, schema, table)
	if err != nil {
		return nil, fmt.Errorf("livesource: list columns: %w", err)
	}
	defer rows.Close()
	var out []intel.SourceColumn
	for rows.Next() {
		var c intel.SourceColumn
		if err := rows.Scan(&c.Name, &c.DataType); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// Table is a live relation. Exported so tests in other packages can build one.
type Table struct {
	Schema string
	Name   string
	Cols   []intel.SourceColumn
}

func (t *Table) Relation() string {
	q := intel.Postgres{}
	return q.QuoteIdent(t.Schema) + "." + q.QuoteIdent(t.Name) + " AS src"
}
func (t *Table) Filter() string                { return "" }
func (t *Table) RefLabel() string              { return t.Name }
func (t *Table) Columns() []intel.SourceColumn { return t.Cols }
func (t *Table) ColumnSQL(name string) string  { return "src." + intel.Postgres{}.QuoteIdent(name) }

// Executor adapts service.SourceExecutor to intel.QueryExecutor.
type Executor struct {
	exec         sourceExecutor
	dataSourceID string
}

// Query runs sqlText on the customer database (read-only, 30s) with the row cap.
func (e *Executor) Query(ctx context.Context, sqlText string, args []any, maxRows int) (*intel.QueryRows, error) {
	res, err := e.exec.ExecuteWithLimit(ctx, e.dataSourceID, sqlText, args, maxRows)
	if err != nil {
		return nil, err
	}
	out := &intel.QueryRows{Columns: res.Columns, Truncated: res.Truncated, Rows: make([][]any, 0, len(res.Rows))}
	for _, row := range res.Rows {
		vals := make([]any, len(res.Columns))
		for i, c := range res.Columns {
			vals[i] = row[c]
		}
		out.Rows = append(out.Rows, vals)
	}
	return out, nil
}
```

- [ ] **Step 4: Chạy — PASS, 0 SKIP (kèm test cũ của executor)**
```bash
cd ennam.kg.go && export KG_TEST_DATABASE_URL="postgres://ennam_kg:${KG_DB_PASSWORD:-ennam_kg_dev}@localhost:5433/ennam_kg?sslmode=disable"
go test -v -count=1 -run 'SourceExecutor|TestExecutor|TestPrepare|TestBind' ./internal/service/ ./internal/intel/sqlexec/ ./internal/intel/livesource/ 2>&1 | tee /tmp/planb.out | grep -E "^(--- |ok|FAIL)"
grep -c -- '--- SKIP' /tmp/planb.out   # phải in 0 — test DB bị SKIP vẫn báo ok
```
Expected: PASS gồm `TestSourceExecutor_RejectsNonReadStatements`, `TestSourceExecutor_AllowsSelectAndWith`, `TestSourceExecutor_ExecuteWithLimit_Truncates`, `TestExecutor_ReadOnlyAndTruncation`, `TestBind_UsesSyncedMetadata`, `TestBind_RejectsNonPostgresSource`; SKIP = 0.

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.go add internal/service/source_executor.go internal/service/source_executor_limit_test.go internal/intel/sqlexec internal/intel/livesource
git -C ennam.kg.go commit -m "feat(intel): live source resolver and per-caller row cap on source executor" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 8: Engine — giá trị metric, availability, timezone, as-of

**Files:** Create `internal/intel/engine/values.go`, `internal/intel/engine/availability.go`, `internal/intel/engine/values_test.go`.

**Interfaces:** Produces `func RatioValue(num, den *float64, unit string) *float64`; `func DimsHash(map[string]string) string`; `func ParseResult(def *intel.MetricDef, res *intel.QueryRows, from, to time.Time) ([]intelstore.MetricRow, error)`; `type SourceRouter`, `func NewSourceRouter(map[intel.SourceMode]intel.SourceResolver) *SourceRouter`; `type MetricState{Def, Enabled, Reason}`; `func Availability(cat *intel.Catalog, mappings []intel.Mapping) map[string]MetricState`; `func ProjectCatalog(ctx, reg, st, projectID) (*intel.Catalog, error)`; `func ResolveTimezone(settings intelstore.ProjectSettings, mappings []intel.Mapping, def string) *time.Location` (settings > literal `location.timezone` > default); `func AsOf(settings intelstore.ProjectSettings, now time.Time, loc *time.Location) time.Time` (override, ngược lại hôm qua theo múi giờ project — ngày dữ liệu cuối, bao gồm).

`ParseResult` nhận mọi dạng giá trị executor trả về: `float64` (NUMERIC thập phân sau `normalizeDBValue`), **chuỗi** (NUMERIC nguyên, hoặc mọi numeric từ `sqlexec`), `int64` (COUNT), `time.Time` (DATE — không gọi `.Local()`).

- [ ] **Step 1: Viết test (failing)**
`internal/intel/engine/values_test.go`:
```go
package engine

import (
	"strings"
	"testing"
	"time"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/intelstore"
)

func fp(v float64) *float64 { return &v }

func TestRatioValue(t *testing.T) {
	if v := RatioValue(fp(1), fp(4), "percent"); v == nil || *v != 25 {
		t.Fatalf("percent: %v", v)
	}
	if v := RatioValue(fp(30), fp(4), "currency"); v == nil || *v != 7.5 {
		t.Fatalf("currency: %v", v)
	}
	if RatioValue(fp(1), fp(0), "percent") != nil || RatioValue(nil, fp(1), "percent") != nil {
		t.Fatal("zero or missing denominator/numerator must give nil")
	}
}

func TestDimsHash_StableAcrossInsertionOrder(t *testing.T) {
	a := map[string]string{}
	a["location_id"] = "S1"
	a["employee_id"] = "E1"
	b := map[string]string{"employee_id": "E1", "location_id": "S1"}
	if DimsHash(a) != DimsHash(b) || len(DimsHash(a)) != 64 {
		t.Fatal("hash must not depend on key order and must be sha256 hex")
	}
	if DimsHash(nil) != DimsHash(map[string]string{}) {
		t.Fatal("nil and empty dims must hash the same")
	}
}

func TestParseResult_AcceptsAllDriverShapes(t *testing.T) {
	def := &intel.MetricDef{Key: "p.r", Dims: []string{"location_id"}, Aggregation: intel.AggRatio, Unit: "percent"}
	from, to := time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC), time.Date(2026, 7, 3, 0, 0, 0, 0, time.UTC)
	res := &intel.QueryRows{
		Columns: []string{"location_id", "period_date", "numerator", "denominator", "sample_size"},
		Rows: [][]any{
			{"S1", time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC), int64(1), "4", int64(4)},
			{int64(7), "2026-07-02", 0.5, float64(2), "2"},
		},
	}
	rows, err := ParseResult(def, res, from, to)
	if err != nil {
		t.Fatal(err)
	}
	if *rows[0].Value != 25 || rows[1].Dims["location_id"] != "7" || *rows[1].Value != 25 || rows[1].SampleSize != 2 {
		t.Fatalf("rows = %+v %+v", rows[0], rows[1])
	}
}

func TestParseResult_Rejects(t *testing.T) {
	def := &intel.MetricDef{Key: "p.a", Dims: []string{"location_id"}, Aggregation: intel.AggAdditive, Unit: "currency"}
	from, to := time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC), time.Date(2026, 7, 2, 0, 0, 0, 0, time.UTC)
	cases := map[string]*intel.QueryRows{
		"missing column": {Columns: []string{"location_id", "period_date", "sample_size"}, Rows: [][]any{}},
		"outside window": {Columns: []string{"location_id", "period_date", "value", "sample_size"},
			Rows: [][]any{{"S1", "2026-07-02", 1.0, int64(1)}}},
		"duplicate": {Columns: []string{"location_id", "period_date", "value", "sample_size"},
			Rows: [][]any{{"S1", "2026-07-01", 1.0, int64(1)}, {"S1", "2026-07-01", 2.0, int64(1)}}},
		"bad number": {Columns: []string{"location_id", "period_date", "value", "sample_size"},
			Rows: [][]any{{"S1", "2026-07-01", "abc", int64(1)}}},
	}
	for name, res := range cases {
		if _, err := ParseResult(def, res, from, to); err == nil {
			t.Errorf("%s: expected error", name)
		} else if !strings.Contains(err.Error(), "p.a") {
			t.Errorf("%s: error should name the metric: %v", name, err)
		}
	}
}

func TestAvailability(t *testing.T) {
	cat := &intel.Catalog{Metrics: map[string]*intel.MetricDef{
		"p.one": {Key: "p.one", Requires: []string{"a"}},
		"p.two": {Key: "p.two", Requires: []string{"a", "b"}},
		"p.tri": {Key: "p.tri", Requires: []string{"c"}},
		"p.mix": {Key: "p.mix", Requires: []string{"a", "d"}},
	}}
	ms := []intel.Mapping{
		{Entity: "a", Mode: intel.ModeLive, DataSourceID: "ds1", Status: intel.MappingApproved},
		{Entity: "b", Mode: intel.ModeLive, DataSourceID: "ds1", Status: intel.MappingBroken},
		{Entity: "c", Mode: intel.ModeLive, DataSourceID: "ds1", Status: intel.MappingProposed},
		{Entity: "d", Mode: intel.ModeFile, ProjectID: "p", Status: intel.MappingApproved},
	}
	av := Availability(cat, ms)
	if !av["p.one"].Enabled {
		t.Fatal("p.one must be enabled")
	}
	for key, want := range map[string]string{"p.two": "broken", "p.tri": "not approved", "p.mix": "different sources"} {
		if av[key].Enabled || !strings.Contains(av[key].Reason, want) {
			t.Errorf("%s: %+v, want reason containing %q", key, av[key], want)
		}
	}
}

func TestResolveTimezoneAndAsOf(t *testing.T) {
	ms := []intel.Mapping{{Entity: "location", Spec: intel.MappingSpec{Fields: map[string]string{"timezone": "'America/Chicago'"}}}}
	if ResolveTimezone(intelstore.ProjectSettings{}, ms, "UTC").String() != "America/Chicago" {
		t.Fatal("literal timezone of the location mapping must beat the default")
	}
	if ResolveTimezone(intelstore.ProjectSettings{Timezone: "Asia/Ho_Chi_Minh"}, ms, "UTC").String() != "Asia/Ho_Chi_Minh" {
		t.Fatal("project settings must beat the mapping literal")
	}
	if ResolveTimezone(intelstore.ProjectSettings{Timezone: "Not/AZone"}, nil, "Bad/Zone").String() != "UTC" {
		t.Fatal("invalid names must fall back to UTC")
	}
	now := time.Date(2026, 10, 2, 3, 0, 0, 0, time.UTC) // still Oct 1 in Chicago
	chi, _ := time.LoadLocation("America/Chicago")
	if d := AsOf(intelstore.ProjectSettings{}, now, chi); d.Format(dateFmt) != "2026-09-30" {
		t.Fatalf("default as_of = yesterday in Chicago, got %s", d.Format(dateFmt))
	}
	asOf := time.Date(2026, 7, 31, 0, 0, 0, 0, time.UTC)
	if d := AsOf(intelstore.ProjectSettings{AsOfOverride: &asOf}, now, chi); !d.Equal(asOf) {
		t.Fatal("as-of override must win over the clock")
	}
}
```

- [ ] **Step 2: Chạy — FAIL**
```bash
cd ennam.kg.go && go test -count=1 ./internal/intel/engine/
```
Expected: FAIL — `undefined: RatioValue`.

- [ ] **Step 3: Implement**
`internal/intel/engine/values.go`:
```go
// Package engine runs the metrics layer: availability, the metric runner,
// scheduling and the read/query service behind the 4 MCP tools.
package engine

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/intelstore"
)

const dateFmt = "2006-01-02"

// RatioValue is THE function that turns numerator/denominator into a value — used
// when the runner writes daily rows and when the query service rolls periods up,
// so a ratio is always SUM(num)/SUM(den), never an average of daily ratios
// (spec §6.4). ×100 only for unit percent. nil when either side is missing or
// the denominator is 0.
func RatioValue(num, den *float64, unit string) *float64 {
	if num == nil || den == nil || *den == 0 {
		return nil
	}
	v := *num / *den
	if unit == "percent" {
		v *= 100
	}
	return &v
}

// DimsHash is sha256 hex of the JSON of dims; encoding/json sorts map keys, so
// the hash does not depend on map iteration order.
func DimsHash(dims map[string]string) string {
	if dims == nil {
		dims = map[string]string{}
	}
	raw, _ := json.Marshal(dims)
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

// parseNumber accepts every shape the executors return: float64 (decimal-looking
// NUMERIC after service.normalizeDBValue), string (integer-looking NUMERIC, or any
// numeric from sqlexec), int64 (COUNT), []byte. nil stays nil.
func parseNumber(v any) (*float64, error) {
	switch x := v.(type) {
	case nil:
		return nil, nil
	case float64:
		return &x, nil
	case float32:
		f := float64(x)
		return &f, nil
	case int64:
		f := float64(x)
		return &f, nil
	case int:
		f := float64(x)
		return &f, nil
	case int32:
		f := float64(x)
		return &f, nil
	case []byte:
		return parseNumber(string(x))
	case string:
		f, err := strconv.ParseFloat(strings.TrimSpace(x), 64)
		if err != nil {
			return nil, fmt.Errorf("not a number: %q", x)
		}
		return &f, nil
	default:
		return nil, fmt.Errorf("unsupported numeric type %T", v)
	}
}

// parseDate accepts time.Time (driver DATE, midnight UTC — never call .Local()),
// or "YYYY-MM-DD[...]" strings.
func parseDate(v any) (time.Time, error) {
	switch x := v.(type) {
	case time.Time:
		return time.Date(x.Year(), x.Month(), x.Day(), 0, 0, 0, 0, time.UTC), nil
	case []byte:
		return parseDate(string(x))
	case string:
		if len(x) < 10 {
			return time.Time{}, fmt.Errorf("not a date: %q", x)
		}
		return time.Parse("2006-01-02", x[:10])
	default:
		return time.Time{}, fmt.Errorf("unsupported date type %T", v)
	}
}

// dimString stringifies a dim value so the same dimension always hashes the same.
// NULL becomes "".
func dimString(v any) string {
	switch x := v.(type) {
	case nil:
		return ""
	case string:
		return x
	case []byte:
		return string(x)
	case int64:
		return strconv.FormatInt(x, 10)
	case float64:
		return strconv.FormatFloat(x, 'f', -1, 64)
	case bool:
		return strconv.FormatBool(x)
	case time.Time:
		return x.Format("2006-01-02")
	default:
		return fmt.Sprint(x)
	}
}

// ParseResult validates a metric statement's result against the metric contract
// (master §2.2: every dim, period_date, sample_size, and value or
// numerator+denominator) and converts it to rows ready for metric_value.
// Every period_date must fall inside [from, to); a (period, dims) pair may appear
// only once.
func ParseResult(def *intel.MetricDef, res *intel.QueryRows, from, to time.Time) ([]intelstore.MetricRow, error) {
	idx := map[string]int{}
	for i, c := range res.Columns {
		idx[c] = i
	}
	need := append([]string{"period_date", "sample_size"}, def.Dims...)
	if def.Aggregation == intel.AggRatio {
		need = append(need, "numerator", "denominator")
	} else {
		need = append(need, "value")
	}
	for _, c := range need {
		if _, ok := idx[c]; !ok {
			return nil, fmt.Errorf("metric %s: result has no column %q", def.Key, c)
		}
	}
	seen := map[string]bool{}
	out := make([]intelstore.MetricRow, 0, len(res.Rows))
	for n, row := range res.Rows {
		pd, err := parseDate(row[idx["period_date"]])
		if err != nil {
			return nil, fmt.Errorf("metric %s row %d: period_date: %w", def.Key, n, err)
		}
		if pd.Before(from) || !pd.Before(to) {
			return nil, fmt.Errorf("metric %s row %d: period_date %s outside window [%s, %s)",
				def.Key, n, pd.Format("2006-01-02"), from.Format("2006-01-02"), to.Format("2006-01-02"))
		}
		dims := make(map[string]string, len(def.Dims))
		for _, d := range def.Dims {
			dims[d] = dimString(row[idx[d]])
		}
		ss, err := parseNumber(row[idx["sample_size"]])
		if err != nil || ss == nil || *ss < 0 {
			return nil, fmt.Errorf("metric %s row %d: sample_size must be a non-negative number", def.Key, n)
		}
		r := intelstore.MetricRow{PeriodDate: pd, Dims: dims, DimsHash: DimsHash(dims), SampleSize: int(*ss)}
		if def.Aggregation == intel.AggRatio {
			if r.Numerator, err = parseNumber(row[idx["numerator"]]); err != nil {
				return nil, fmt.Errorf("metric %s row %d: numerator: %w", def.Key, n, err)
			}
			if r.Denominator, err = parseNumber(row[idx["denominator"]]); err != nil {
				return nil, fmt.Errorf("metric %s row %d: denominator: %w", def.Key, n, err)
			}
			r.Value = RatioValue(r.Numerator, r.Denominator, def.Unit)
		} else if r.Value, err = parseNumber(row[idx["value"]]); err != nil {
			return nil, fmt.Errorf("metric %s row %d: value: %w", def.Key, n, err)
		}
		key := pd.Format("2006-01-02") + "|" + r.DimsHash
		if seen[key] {
			return nil, fmt.Errorf("metric %s: duplicate row for period %s dims %v", def.Key, pd.Format("2006-01-02"), dims)
		}
		seen[key] = true
		out = append(out, r)
	}
	return out, nil
}
```

`internal/intel/engine/availability.go`:
```go
package engine

import (
	"context"
	"fmt"
	"sort"
	"time"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/intelstore"
)

// SourceRouter dispatches a mapping to the resolver of its mode. Plan B registers
// intel.ModeLive; Plan C adds intel.ModeFile in cmd/kg-server/main.go.
type SourceRouter struct {
	resolvers map[intel.SourceMode]intel.SourceResolver
}

// NewSourceRouter returns a router over the given resolvers.
func NewSourceRouter(resolvers map[intel.SourceMode]intel.SourceResolver) *SourceRouter {
	return &SourceRouter{resolvers: resolvers}
}

// Resolver returns the resolver for mode.
func (r *SourceRouter) Resolver(mode intel.SourceMode) (intel.SourceResolver, error) {
	res, ok := r.resolvers[mode]
	if !ok || res == nil {
		return nil, fmt.Errorf("no source resolver for mode %q", mode)
	}
	return res, nil
}

// MetricState says whether a metric can run for a project and why not.
type MetricState struct {
	Def     *intel.MetricDef
	Enabled bool
	Reason  string
}

// Availability decides, from mappings alone, which catalog metrics can run: every
// required entity needs an approved mapping, and all of them must live in the same
// physical database (no cross-mode joins, spec §6.3).
func Availability(cat *intel.Catalog, mappings []intel.Mapping) map[string]MetricState {
	byEntity := map[string]intel.Mapping{}
	for _, m := range mappings {
		byEntity[m.Entity] = m
	}
	out := make(map[string]MetricState, len(cat.Metrics))
	for key, def := range cat.Metrics {
		st := MetricState{Def: def, Enabled: true}
		loc := ""
		for _, req := range def.Requires {
			m, ok := byEntity[req]
			switch {
			case !ok:
				st.Enabled, st.Reason = false, fmt.Sprintf("no mapping for entity %s", req)
			case m.Status == intel.MappingBroken:
				st.Enabled, st.Reason = false, fmt.Sprintf("mapping for entity %s is broken", req)
			case m.Status != intel.MappingApproved:
				st.Enabled, st.Reason = false, fmt.Sprintf("mapping for entity %s is not approved", req)
			case loc != "" && loc != m.LocationKey():
				st.Enabled, st.Reason = false, "required entities live in different sources (no cross-source join)"
			default:
				loc = m.LocationKey()
			}
			if !st.Enabled {
				break
			}
		}
		out[key] = st
	}
	return out
}

// ProjectCatalog builds the extends-merged catalog of the packs enabled for a project.
func ProjectCatalog(ctx context.Context, reg *intel.Registry, st *intelstore.Store, projectID string) (*intel.Catalog, error) {
	installs, err := st.ListInstalls(ctx, projectID)
	if err != nil {
		return nil, err
	}
	var keys []string
	for _, in := range installs {
		if in.Enabled {
			keys = append(keys, in.PackKey)
		}
	}
	sort.Strings(keys)
	return reg.Effective(keys)
}

// ResolveTimezone is the business timezone of a project: project_intel_settings
// .timezone, else the location mapping's `timezone` field when it is a constant
// string literal (e.g. "'America/Chicago'", spec §6.2), else def. Invalid names
// are skipped; the last resort is UTC.
func ResolveTimezone(settings intelstore.ProjectSettings, mappings []intel.Mapping, def string) *time.Location {
	candidates := []string{settings.Timezone}
	for _, m := range mappings {
		if m.Entity == "location" {
			if lit, ok := intel.IsStringLiteral(m.Spec.Fields["timezone"]); ok {
				candidates = append(candidates, lit)
			}
		}
	}
	candidates = append(candidates, def)
	for _, c := range candidates {
		if c == "" {
			continue
		}
		if loc, err := time.LoadLocation(c); err == nil {
			return loc
		}
	}
	return time.UTC
}

// AsOf is the project's as-of date — the LAST data day, inclusive (master Global
// Constraints "As-of date"): the project's override when set (demo: 2026-07-31),
// else yesterday in the project's timezone. Query windows end at AsOf+1 (exclusive);
// freshness labels are measured against it, never against the wall clock.
func AsOf(settings intelstore.ProjectSettings, now time.Time, loc *time.Location) time.Time {
	if settings.AsOfOverride != nil {
		return *settings.AsOfOverride
	}
	n := now.In(loc)
	return time.Date(n.Year(), n.Month(), n.Day(), 0, 0, 0, 0, time.UTC).AddDate(0, 0, -1)
}

// binding is the compiled SQL context of a set of entities living in one source.
type binding struct {
	ctes      map[string]string
	exec      intel.QueryExecutor
	mode      intel.SourceMode
	watermark string
}

// bindEntities binds and compiles the CTE of every entity in entities. All must be
// approved and share one LocationKey; the executor of the first is used.
func bindEntities(ctx context.Context, router *SourceRouter, comp *intel.Compiler, projectID string,
	mappings []intel.Mapping, entities []string, tz string) (*binding, error) {
	byEntity := map[string]intel.Mapping{}
	for _, m := range mappings {
		byEntity[m.Entity] = m
	}
	b := &binding{ctes: map[string]string{}}
	for _, e := range entities {
		m, ok := byEntity[e]
		if !ok || m.Status != intel.MappingApproved {
			return nil, fmt.Errorf("entity %s has no approved mapping", e)
		}
		res, err := router.Resolver(m.Mode)
		if err != nil {
			return nil, err
		}
		bound, err := res.Bind(ctx, projectID, m)
		if err != nil {
			return nil, err
		}
		cte, err := comp.EntityCTE(e, m, bound.Table, tz)
		if err != nil {
			return nil, err
		}
		b.ctes[e] = cte
		if b.exec == nil {
			b.exec, b.mode, b.watermark = bound.Executor, m.Mode, bound.Watermark
		}
	}
	return b, nil
}
```

- [ ] **Step 4: Chạy — PASS**
```bash
cd ennam.kg.go && go test -count=1 ./internal/intel/engine/
```
Expected: `ok`

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.go add internal/intel/engine/values.go internal/intel/engine/availability.go internal/intel/engine/values_test.go
git -C ennam.kg.go commit -m "feat(intel): metric value parsing, ratio rollup and availability" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 9: Metric runner + advisory lock (chunk, truncation, lookback, version bump, freshness theo as-of)

**Files:** Create `internal/intel/engine/runner.go`, `internal/intel/engine/lock.go`, `internal/intel/engine/fixture_test.go`, `internal/intel/engine/runner_test.go`.

**Interfaces:** Produces `type RunnerConfig{MaxRows, ChunkDays int; DefaultTimezone string; StaleAfterDays int; Now func() time.Time}`; `func RunnerConfigFromEnv() (RunnerConfig, error)` (env `METRIC_RUNNER_MAX_ROWS`=50000, `METRIC_RUNNER_CHUNK_DAYS`=7, `METRIC_RUNNER_TIMEZONE`=UTC, `METRIC_STALE_AFTER_DAYS`=3; giá trị sai ⇒ lỗi); `func NewRunner(reg, st, router, cfg, logger) *Runner`; `func (r *Runner) Run(ctx, projectID string, opts RunOptions) (*RunSummary, error)`; `type RunOptions{From, To *time.Time; Metrics []string}`; `var ErrRunInProgress`; `func TryProjectLock(ctx, db, projectID) (release func(), ok bool, err error)`.

Luồng `Run`: advisory lock theo project → catalog (pack bật) → mapping + settings → timezone, business today → **Prepare** (live: sync schema — I11; lỗi ⇒ entity `delayed` nếu lần thành công gần nhất ≤ 48h, ngược lại `stale`) → **Bind + EntityCTE** từng entity cần dùng (`MappingError` ⇒ mapping `broken` + entity `blocked`; `ErrSourceNotReady` ⇒ `incomplete`) → kiểm tra enum chưa map, NULL ở field required (mẫu 100k dòng), độ tươi (ngày mới nhất của field timestamp required đầu tiên so với `as_of`: bằng `as_of` ⇒ `current`, trễ 1..`StaleAfterDays-1` ngày ⇒ `delayed`, còn lại `stale`) → từng metric bật: cửa sổ = `[as_of − lookback_days, as_of+1)` (hoặc `--from/--to`; version tăng ⇒ từ kỳ cũ nhất đã lưu; grain month căn theo tháng) → chunk `ChunkDays` → truncated ⇒ chia đôi tới 1 ngày, vẫn cắt ⇒ `blocked/row_limit` → `ReplaceMetricRows` (version tăng được phát hiện bằng `StaleSince` = kỳ sớm nhất còn `metric_version` cũ — MIN, không phải MAX — nên backfill hỏng giữa chừng sẽ tiếp tục ở lần chạy sau; unlock advisory lock lỗi ⇒ huỷ connection thay vì trả về pool; cửa sổ chạm lookback: xoá rồi ghi lại — dữ liệu đến muộn; cửa sổ cũ: chỉ xoá từ kỳ sớm nhất nguồn còn trả về — không xoá lịch sử nguồn đã purge) → `data_status` metric = trạng thái xấu nhất của các entity.

- [ ] **Step 1: Viết fixture helper + test (failing)**
`internal/intel/engine/fixture_test.go`:
```go
package engine

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"testing"
	"time"

	_ "github.com/lib/pq"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/intelstore"
	"github.com/ennam/ennam-kg/internal/intel/livesource"
	"github.com/ennam/ennam-kg/internal/intel/sqlexec"
)

// env is one isolated integration fixture: a project, a data source row (FK of
// project_mapping), and a scratch schema holding the "customer" tables.
type env struct {
	db       *sql.DB
	store    *intelstore.Store
	reg      *intel.Registry
	pid      string
	dsID     string
	schema   string
	resolver *fixtureResolver
	router   *SourceRouter
}

func newEnv(t *testing.T) *env {
	t.Helper()
	url := os.Getenv("KG_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("Skipping integration test: KG_TEST_DATABASE_URL not set")
	}
	db, err := sql.Open("postgres", url)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	reg, err := intel.LoadRegistry("../testdata/packs")
	if err != nil {
		t.Fatal(err)
	}
	e := &env{db: db, store: intelstore.New(db), reg: reg, schema: fmt.Sprintf("intel_eng_%d", time.Now().UnixNano())}
	e.exec(t, `INSERT INTO projects (name) VALUES ('`+e.schema+`')`)
	if err := db.QueryRow(`SELECT id::text FROM projects WHERE name = $1`, e.schema).Scan(&e.pid); err != nil {
		t.Fatal(err)
	}
	if err := db.QueryRow(`INSERT INTO data_sources (project_id, name, host, database_name, connection_string_encrypted, created_by)
		VALUES ($1, 'fixture', 'h', 'd', '\x00', 't') RETURNING id::text`, e.pid).Scan(&e.dsID); err != nil {
		t.Fatal(err)
	}
	e.exec(t, `CREATE SCHEMA `+e.schema)
	e.exec(t, `CREATE TABLE `+e.schema+`.orders (id text, shop_code text, created_at timestamptz, total numeric, discount numeric, state text)`)
	t.Cleanup(func() {
		_, _ = db.Exec(`DROP SCHEMA ` + e.schema + ` CASCADE`)
		_, _ = db.Exec(`DELETE FROM project_mapping WHERE project_id = $1`, e.pid)
		_, _ = db.Exec(`DELETE FROM data_sources WHERE id = $1`, e.dsID)
		_, _ = db.Exec(`DELETE FROM projects WHERE id = $1`, e.pid)
	})
	e.resolver = &fixtureResolver{db: db, schema: e.schema}
	e.router = NewSourceRouter(map[intel.SourceMode]intel.SourceResolver{intel.ModeLive: e.resolver})
	if err := e.store.UpsertInstall(context.Background(), e.pid, "base", "0.1.0", true); err != nil {
		t.Fatal(err)
	}
	e.mapOrders(t, "COALESCE(total, 0) - discount")
	return e
}

func (e *env) exec(t *testing.T, q string, args ...any) {
	t.Helper()
	if _, err := e.db.Exec(q, args...); err != nil {
		t.Fatalf("%s: %v", q, err)
	}
}

// mapOrders (re)writes the approved order mapping with the given amount expression.
func (e *env) mapOrders(t *testing.T, amountExpr string) {
	t.Helper()
	m := intel.Mapping{ProjectID: e.pid, Entity: "order", Mode: intel.ModeLive, DataSourceID: e.dsID, Status: intel.MappingApproved,
		Spec: intel.MappingSpec{From: "orders",
			Fields:  map[string]string{"order_id": "id", "location_id": "shop_code", "ordered_at": "created_at", "amount": amountExpr, "status": "state"},
			EnumMap: map[string]map[string]string{"status": {"OPEN": "open", "CLOSED": "closed"}}}}
	if _, err := e.store.UpsertMapping(context.Background(), m, "test"); err != nil {
		t.Fatal(err)
	}
}

// order inserts one source row; ts is UTC wall-clock "YYYY-MM-DD HH:MM".
func (e *env) order(t *testing.T, id, shop, ts string, total float64, state string) {
	t.Helper()
	e.exec(t, `INSERT INTO `+e.schema+`.orders VALUES ($1, $2, $3::timestamptz, $4, 0, $5)`, id, shop, ts+":00+00", total, state)
}

func (e *env) runner(maxRows int, now string) *Runner {
	n, _ := time.Parse("2006-01-02 15:04", now)
	return NewRunner(e.reg, e.store, e.router, RunnerConfig{MaxRows: maxRows, ChunkDays: 7, DefaultTimezone: "UTC",
		Now: func() time.Time { return n }}, nil)
}

func (e *env) series(t *testing.T, key, from, to, grain string, agg intel.Aggregation) []intelstore.SeriesPoint {
	t.Helper()
	f, _ := time.Parse(dateFmt, from)
	tt, _ := time.Parse(dateFmt, to)
	pts, err := e.store.QuerySeries(context.Background(), intelstore.SeriesQuery{ProjectID: e.pid, MetricKey: key, From: f, To: tt,
		Grain: grain, GroupBy: []string{"location_id"}, Aggregation: agg})
	if err != nil {
		t.Fatal(err)
	}
	return pts
}

// fixtureResolver is a mode=live resolver over a scratch schema of the test DB.
type fixtureResolver struct {
	db         *sql.DB
	schema     string
	prepareErr error
	prepared   int
}

func (f *fixtureResolver) Prepare(context.Context, string, []intel.Mapping) error {
	f.prepared++
	return f.prepareErr
}

func (f *fixtureResolver) Bind(ctx context.Context, _ string, m intel.Mapping) (*intel.BoundSource, error) {
	rows, err := f.db.QueryContext(ctx, `SELECT column_name, data_type FROM information_schema.columns
		WHERE table_schema = $1 AND table_name = $2 ORDER BY ordinal_position`, f.schema, m.Spec.From)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var cols []intel.SourceColumn
	for rows.Next() {
		var c intel.SourceColumn
		if err := rows.Scan(&c.Name, &c.DataType); err != nil {
			return nil, err
		}
		cols = append(cols, c)
	}
	if len(cols) == 0 {
		return nil, &intel.MappingError{Entity: m.Entity, Code: "missing_table", Detail: m.Spec.From}
	}
	return &intel.BoundSource{Table: &livesource.Table{Schema: f.schema, Name: m.Spec.From, Cols: cols}, Executor: sqlexec.New(f.db, 0)}, nil
}
```

`internal/intel/engine/runner_test.go`:
```go
package engine

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/intelstore"
)

func dayT(s string) time.Time { v, _ := time.Parse(dateFmt, s); return v }

func outcome(t *testing.T, sum *RunSummary, key string) MetricOutcome {
	t.Helper()
	for _, m := range sum.Metrics {
		if m.Key == key {
			return m
		}
	}
	t.Fatalf("metric %s not in summary %+v", key, sum.Metrics)
	return MetricOutcome{}
}

// Review Focus #2: a late change at the source (closed order reopened, amount
// corrected) must rewrite the original day inside the lookback window, and a dims
// combination that vanished must not survive.
func TestRunner_LookbackReplacesWindow(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	e.order(t, "o1", "S1", "2026-07-08 10:00", 10, "CLOSED")
	e.order(t, "o2", "S2", "2026-07-09 11:00", 5, "CLOSED")
	r := e.runner(1000, "2026-07-10 12:00")

	sum, err := r.Run(ctx, e.pid, RunOptions{Metrics: []string{"base.order_total"}})
	if err != nil {
		t.Fatal(err)
	}
	if o := outcome(t, sum, "base.order_total"); o.Status != intel.StatusCurrent || o.Rows != 2 || o.From != "2026-07-02" || o.To != "2026-07-10" {
		t.Fatalf("first run = %+v", o)
	}

	e.exec(t, `UPDATE `+e.schema+`.orders SET state = 'OPEN' WHERE id = 'o2'`)
	e.exec(t, `UPDATE `+e.schema+`.orders SET total = 12 WHERE id = 'o1'`)
	if _, err := r.Run(ctx, e.pid, RunOptions{Metrics: []string{"base.order_total"}}); err != nil {
		t.Fatal(err)
	}
	pts := e.series(t, "base.order_total", "2026-07-01", "2026-07-11", "day", intel.AggAdditive)
	if len(pts) != 1 || pts[0].Dims["location_id"] != "S1" || *pts[0].Value != 12 {
		t.Fatalf("after late change: %+v", pts)
	}
	st, _ := e.store.GetDataStatus(ctx, e.pid, "metric:base.order_total")
	if st == nil || st.Status != intel.StatusCurrent || st.LastSuccessAt == nil {
		t.Fatalf("data status = %+v", st)
	}
}

// Review Focus #1: a window over the row cap is split, never silently cut.
func TestRunner_TruncatedChunkSplitsThenBlocks(t *testing.T) {
	e := newEnv(t)
	e.order(t, "o1", "S1", "2026-07-01 10:00", 1, "CLOSED")
	e.order(t, "o2", "S2", "2026-07-03 10:00", 2, "CLOSED")
	from, to := dayT("2026-07-01"), dayT("2026-07-05")
	sum, err := e.runner(1, "2026-07-04 12:00").Run(context.Background(), e.pid,
		RunOptions{From: &from, To: &to, Metrics: []string{"base.order_total"}})
	if err != nil {
		t.Fatal(err)
	}
	if o := outcome(t, sum, "base.order_total"); o.Status != intel.StatusCurrent || o.Rows != 2 {
		t.Fatalf("split run = %+v", o)
	}
	if pts := e.series(t, "base.order_total", "2026-07-01", "2026-07-05", "day", intel.AggAdditive); len(pts) != 2 {
		t.Fatalf("points = %+v", pts)
	}
}

func TestRunner_TruncatedAtOneDayWritesNothing(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	e.order(t, "o1", "S1", "2026-07-01 10:00", 1, "CLOSED")
	e.order(t, "o2", "S2", "2026-07-01 11:00", 2, "CLOSED")
	from, to := dayT("2026-07-01"), dayT("2026-07-02")
	sum, err := e.runner(1, "2026-07-02 12:00").Run(ctx, e.pid, RunOptions{From: &from, To: &to, Metrics: []string{"base.order_total"}})
	if err != nil {
		t.Fatal(err)
	}
	if o := outcome(t, sum, "base.order_total"); o.Status != intel.StatusBlocked || o.Rows != 0 {
		t.Fatalf("outcome = %+v", o)
	}
	if pts := e.series(t, "base.order_total", "2026-07-01", "2026-07-02", "day", intel.AggAdditive); len(pts) != 0 {
		t.Fatalf("truncated result must not be written: %+v", pts)
	}
	st, _ := e.store.GetDataStatus(ctx, e.pid, "metric:base.order_total")
	if st == nil || st.Status != intel.StatusBlocked || len(st.Issues) != 1 || st.Issues[0].Code != "row_limit" {
		t.Fatalf("data status = %+v", st)
	}
}

func TestRunner_SchemaDriftMarksMappingBroken(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	e.mapOrders(t, "gone_column")
	sum, err := e.runner(1000, "2026-07-10 12:00").Run(ctx, e.pid, RunOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if sum.Entities["order"] != intel.StatusBlocked {
		t.Fatalf("entities = %+v", sum.Entities)
	}
	if o := outcome(t, sum, "base.order_total"); o.Status != "skipped" {
		t.Fatalf("metric over a broken mapping must be skipped: %+v", o)
	}
	ms, _ := e.store.ListMappings(ctx, e.pid)
	if ms[0].Status != intel.MappingBroken {
		t.Fatalf("mapping status = %s", ms[0].Status)
	}
	if e.resolver.prepared != 1 {
		t.Fatalf("Prepare (schema sync) must run once before binding, ran %d", e.resolver.prepared)
	}
}

func TestRunner_UnmappedEnumMakesMetricIncomplete(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	e.order(t, "o1", "S1", "2026-07-08 10:00", 10, "CLOSED")
	e.order(t, "o2", "S1", "2026-07-08 11:00", 10, "ON_HOLD")
	sum, err := e.runner(1000, "2026-07-10 12:00").Run(ctx, e.pid, RunOptions{Metrics: []string{"base.order_total"}})
	if err != nil {
		t.Fatal(err)
	}
	if sum.Entities["order"] != intel.StatusIncomplete || outcome(t, sum, "base.order_total").Status != intel.StatusIncomplete {
		t.Fatalf("summary = %+v", sum)
	}
	st, _ := e.store.GetDataStatus(ctx, e.pid, "entity:order")
	if st == nil || len(st.Issues) == 0 || st.Issues[0].Code != "unmapped_enum_value" {
		t.Fatalf("entity status = %+v", st)
	}
}

func TestRunner_VersionBumpRecomputesStoredSeries(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	e.order(t, "o1", "S1", "2026-06-01 10:00", 7, "CLOSED")
	old := 999.0
	// A row stored by metric version 1 (the pack now declares version 2).
	if err := e.store.ReplaceMetricRows(ctx, intelstore.WriteMeta{ProjectID: e.pid, MetricKey: "base.order_total", MetricVersion: 1,
		PackVersion: "0.0.9", SourceMode: intel.ModeLive}, nil, nil, []intelstore.MetricRow{{PeriodDate: dayT("2026-06-01"),
		Dims: map[string]string{"location_id": "S1"}, DimsHash: DimsHash(map[string]string{"location_id": "S1"}), Value: &old, SampleSize: 1}}); err != nil {
		t.Fatal(err)
	}
	sum, err := e.runner(1000, "2026-07-10 12:00").Run(ctx, e.pid, RunOptions{Metrics: []string{"base.order_total"}})
	if err != nil {
		t.Fatal(err)
	}
	if o := outcome(t, sum, "base.order_total"); o.From != "2026-06-01" {
		t.Fatalf("version bump must recompute from the first stored period: %+v", o)
	}
	vers, _ := e.store.VersionsInSeries(ctx, e.pid, "base.order_total", dayT("2026-06-01"), dayT("2026-06-02"))
	pts := e.series(t, "base.order_total", "2026-06-01", "2026-06-02", "day", intel.AggAdditive)
	if len(vers) != 1 || vers[0] != 2 || len(pts) != 1 || *pts[0].Value != 7 {
		t.Fatalf("versions = %v points = %+v", vers, pts)
	}
}

// A bump backfill that failed half-way leaves the newest periods on the new version
// and older ones on the old version; the next run must still go back to the oldest
// old-version period (detection by MIN, not MAX, of stored versions).
func TestRunner_VersionBumpResumesAfterPartialFailure(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	e.order(t, "o1", "S1", "2026-06-01 10:00", 7, "CLOSED")
	old, done := 999.0, 1.0
	dims := map[string]string{"location_id": "S1"}
	for _, r := range []struct {
		d string
		v int
		x *float64
	}{{"2026-06-01", 1, &old}, {"2026-07-05", 2, &done}} {
		if err := e.store.ReplaceMetricRows(ctx, intelstore.WriteMeta{ProjectID: e.pid, MetricKey: "base.order_total", MetricVersion: r.v,
			PackVersion: "x", SourceMode: intel.ModeLive}, nil, nil, []intelstore.MetricRow{{PeriodDate: dayT(r.d), Dims: dims,
			DimsHash: DimsHash(dims), Value: r.x, SampleSize: 1}}); err != nil {
			t.Fatal(err)
		}
	}
	sum, err := e.runner(1000, "2026-07-10 12:00").Run(ctx, e.pid, RunOptions{Metrics: []string{"base.order_total"}})
	if err != nil {
		t.Fatal(err)
	}
	if o := outcome(t, sum, "base.order_total"); o.From != "2026-06-01" {
		t.Fatalf("must resume from the oldest old-version period: %+v", o)
	}
	if _, found, _ := e.store.StaleSince(ctx, e.pid, "base.order_total", 2); found {
		t.Fatal("every period must be on version 2 after the resumed run")
	}
}

func TestRunner_SourceUnreachableIsStaleWithoutHistory(t *testing.T) {
	e := newEnv(t)
	e.resolver.prepareErr = errors.New("connection refused")
	sum, err := e.runner(1000, "2026-07-10 12:00").Run(context.Background(), e.pid, RunOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if sum.Entities["order"] != intel.StatusStale || outcome(t, sum, "base.order_total").Status != intel.StatusStale {
		t.Fatalf("summary = %+v", sum)
	}
}

// Demo data ends in the past: the project's as-of override (last data day,
// inclusive) moves the lookback window and freshness to the data, not the clock.
func TestRunner_AsOfDrivesWindowAndFreshness(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	e.order(t, "o1", "S1", "2026-07-30 10:00", 10, "CLOSED")
	e.order(t, "o2", "S1", "2026-07-31 10:00", 5, "CLOSED")
	r := e.runner(1000, "2026-10-02 12:00")

	sum, err := r.Run(ctx, e.pid, RunOptions{Metrics: []string{"base.order_total"}})
	if err != nil {
		t.Fatal(err)
	}
	if o := outcome(t, sum, "base.order_total"); o.Status != intel.StatusStale || o.Rows != 0 {
		t.Fatalf("without as-of the data is 2 months old: %+v", o)
	}

	asOf := dayT("2026-07-31")
	if err := e.store.SetAsOf(ctx, e.pid, &asOf, ""); err != nil {
		t.Fatal(err)
	}
	sum, err = r.Run(ctx, e.pid, RunOptions{Metrics: []string{"base.order_total"}})
	if err != nil {
		t.Fatal(err)
	}
	o := outcome(t, sum, "base.order_total")
	if sum.AsOf != "2026-07-31" || o.Status != intel.StatusCurrent || o.Rows != 2 || o.From != "2026-07-24" || o.To != "2026-08-01" {
		t.Fatalf("summary = %+v outcome = %+v", sum, o)
	}
	st, _ := e.store.GetDataStatus(ctx, e.pid, "entity:order")
	if st == nil || st.PeriodTo == nil || st.PeriodTo.Format(dateFmt) != "2026-07-31" || st.Status != intel.StatusCurrent {
		t.Fatalf("entity status = %+v", st)
	}
}

func TestRunnerConfigFromEnv_RejectsBadValues(t *testing.T) {
	t.Setenv("METRIC_RUNNER_MAX_ROWS", "0")
	if _, err := RunnerConfigFromEnv(); err == nil {
		t.Fatal("METRIC_RUNNER_MAX_ROWS=0 must be an error")
	}
	t.Setenv("METRIC_RUNNER_MAX_ROWS", "")
	t.Setenv("METRIC_RUNNER_TIMEZONE", "Mars/Base")
	if _, err := RunnerConfigFromEnv(); err == nil {
		t.Fatal("unknown timezone must be an error")
	}
	t.Setenv("METRIC_RUNNER_TIMEZONE", "America/Chicago")
	cfg, err := RunnerConfigFromEnv()
	if err != nil || cfg.MaxRows != 50000 || cfg.ChunkDays != 7 || cfg.StaleAfterDays != 3 || cfg.DefaultTimezone != "America/Chicago" {
		t.Fatalf("cfg = %+v, %v", cfg, err)
	}
}

// If unlocking fails (session killed), release must discard the connection rather
// than return a session that may still hold the lock; the lock is then free again.
func TestTryProjectLock_ReleaseAfterSessionLoss(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	release, ok, err := TryProjectLock(ctx, e.db, e.pid)
	if err != nil || !ok {
		t.Fatalf("lock: %v %v", ok, err)
	}
	key := lockKey(e.pid)
	var backend int
	if err := e.db.QueryRow(`SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted
		AND classid = CAST(CAST($1 AS bigint) AS oid) AND objid = CAST(CAST($2 AS bigint) AS oid)`,
		int64(uint32(uint64(key)>>32)), int64(uint32(uint64(key)))).Scan(&backend); err != nil {
		t.Fatalf("find lock holder: %v", err)
	}
	if _, err := e.db.Exec(`SELECT pg_terminate_backend($1)`, backend); err != nil {
		t.Fatal(err)
	}
	release() // unlock fails on the dead session; must not panic or poison the pool
	release2, ok, err := TryProjectLock(ctx, e.db, e.pid)
	if err != nil || !ok {
		t.Fatalf("lock must be free after the session is gone: %v %v", ok, err)
	}
	release2()
}

func TestRunner_SecondRunnerGetsInProgress(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	release, ok, err := TryProjectLock(ctx, e.db, e.pid)
	if err != nil || !ok {
		t.Fatalf("lock: %v %v", ok, err)
	}
	defer release()
	if _, err := e.runner(1000, "2026-07-10 12:00").Run(ctx, e.pid, RunOptions{}); !errors.Is(err, ErrRunInProgress) {
		t.Fatalf("want ErrRunInProgress, got %v", err)
	}
}

func TestChunkWindows(t *testing.T) {
	d := func(s string) time.Time { v, _ := time.Parse(dateFmt, s); return v }
	w := chunkWindows(d("2026-07-01"), d("2026-07-16"), intel.GrainDay, 7)
	if len(w) != 3 || !w[2][0].Equal(d("2026-07-15")) || !w[2][1].Equal(d("2026-07-16")) {
		t.Fatalf("day windows = %v", w)
	}
	m := chunkWindows(d("2026-05-01"), d("2026-08-01"), intel.GrainMonth, 7)
	if len(m) != 3 || !m[1][0].Equal(d("2026-06-01")) {
		t.Fatalf("month windows = %v", m)
	}
}
```

- [ ] **Step 2: Chạy — FAIL**
```bash
cd ennam.kg.go && export KG_TEST_DATABASE_URL="postgres://ennam_kg:${KG_DB_PASSWORD:-ennam_kg_dev}@localhost:5433/ennam_kg?sslmode=disable"
go test -v -count=1 ./internal/intel/engine/ 2>&1 | tee /tmp/planb.out | grep -E "^(--- |ok|FAIL)"
grep -c -- '--- SKIP' /tmp/planb.out   # phải in 0 — test DB bị SKIP vẫn báo ok
```
Expected: FAIL — `undefined: NewRunner`, `undefined: TryProjectLock`.

- [ ] **Step 3: Implement**
`internal/intel/engine/lock.go`:
```go
package engine

import (
	"context"
	"database/sql"
	"database/sql/driver"
	"fmt"
	"hash/fnv"
)

// lockKey maps a project to a stable bigint advisory-lock key.
func lockKey(projectID string) int64 {
	h := fnv.New64a()
	_, _ = h.Write([]byte("intel.metric_runner:" + projectID))
	return int64(h.Sum64())
}

// TryProjectLock takes a session-level Postgres advisory lock for the project on a
// dedicated connection (database/sql pools connections, so lock and unlock must
// run on the same *sql.Conn). ok=false means another runner holds it (spec I7:
// no duplicate runs).
func TryProjectLock(ctx context.Context, db *sql.DB, projectID string) (release func(), ok bool, err error) {
	conn, err := db.Conn(ctx)
	if err != nil {
		return nil, false, fmt.Errorf("advisory lock: conn: %w", err)
	}
	key := lockKey(projectID)
	if err := conn.QueryRowContext(ctx, `SELECT pg_try_advisory_lock($1)`, key).Scan(&ok); err != nil {
		_ = conn.Close()
		return nil, false, fmt.Errorf("advisory lock: %w", err)
	}
	if !ok {
		_ = conn.Close()
		return nil, false, nil
	}
	return func() {
		if _, err := conn.ExecContext(context.Background(), `SELECT pg_advisory_unlock($1)`, key); err != nil {
			// The session may still hold the lock: discard the connection instead of
			// returning it to the pool, so the server ends the session and frees it.
			_ = conn.Raw(func(any) error { return driver.ErrBadConn })
		}
		_ = conn.Close()
	}, true, nil
}
```

`internal/intel/engine/runner.go`:
```go
package engine

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"sort"
	"strconv"
	"time"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/intelstore"
)

// RunnerConfig tunes the metric runner.
type RunnerConfig struct {
	MaxRows         int    // row cap per statement (own cap, not the NL→SQL one)
	ChunkDays       int    // window size for backfill / version recompute
	DefaultTimezone string // business timezone when settings/location mapping give none
	StaleAfterDays  int    // data lag (days behind as-of) from which an entity is stale; 1..StaleAfterDays-1 = delayed
	Now             func() time.Time
}

// RunnerConfigFromEnv reads METRIC_RUNNER_MAX_ROWS (default 50000),
// METRIC_RUNNER_CHUNK_DAYS (default 7), METRIC_RUNNER_TIMEZONE (default UTC) and
// METRIC_STALE_AFTER_DAYS (default 3). Invalid values are errors, not defaults.
func RunnerConfigFromEnv() (RunnerConfig, error) {
	cfg := RunnerConfig{MaxRows: 50000, ChunkDays: 7, DefaultTimezone: "UTC", StaleAfterDays: 3, Now: time.Now}
	ints := []struct {
		env string
		dst *int
	}{{"METRIC_RUNNER_MAX_ROWS", &cfg.MaxRows}, {"METRIC_RUNNER_CHUNK_DAYS", &cfg.ChunkDays}, {"METRIC_STALE_AFTER_DAYS", &cfg.StaleAfterDays}}
	for _, it := range ints {
		if v := os.Getenv(it.env); v != "" {
			n, err := strconv.Atoi(v)
			if err != nil || n <= 0 {
				return cfg, fmt.Errorf("%s %q must be a positive integer", it.env, v)
			}
			*it.dst = n
		}
	}
	if v := os.Getenv("METRIC_RUNNER_TIMEZONE"); v != "" {
		if _, err := time.LoadLocation(v); err != nil {
			return cfg, fmt.Errorf("METRIC_RUNNER_TIMEZONE %q: %w", v, err)
		}
		cfg.DefaultTimezone = v
	}
	return cfg, nil
}

// ErrRunInProgress is returned when another runner holds the project lock.
var ErrRunInProgress = errors.New("metric run already in progress for this project")

var (
	errTruncated     = errors.New("row limit reached even for a one-period window")
	errInvalidResult = errors.New("invalid metric result")
)

// RunOptions narrows a run. From/To (both or neither) force an explicit window
// [From, To) — backfill; otherwise the window is the metric's lookback ending at
// the as-of date inclusive (or the whole stored series after a version bump).
type RunOptions struct {
	From, To *time.Time
	Metrics  []string
}

// MetricOutcome reports one metric of a run.
type MetricOutcome struct {
	Key    string `json:"key"`
	Status string `json:"status"` // current | delayed | incomplete | stale | blocked | skipped
	Rows   int    `json:"rows"`
	From   string `json:"from,omitempty"`
	To     string `json:"to,omitempty"`
	Error  string `json:"error,omitempty"`
}

// RunSummary is what Run returns (the CLI prints it).
type RunSummary struct {
	ProjectID string            `json:"project_id"`
	AsOf      string            `json:"as_of"`
	Started   time.Time         `json:"started"`
	Entities  map[string]string `json:"entities"`
	Metrics   []MetricOutcome   `json:"metrics"`
}

// Runner computes metric_value for a project (spec §6.4 "Metric runner").
type Runner struct {
	reg    *intel.Registry
	store  *intelstore.Store
	router *SourceRouter
	cfg    RunnerConfig
	logger *slog.Logger
	lock   func(ctx context.Context, projectID string) (release func(), ok bool, err error)
}

// NewRunner wires a runner; the project lock is a Postgres advisory lock.
func NewRunner(reg *intel.Registry, st *intelstore.Store, router *SourceRouter, cfg RunnerConfig, logger *slog.Logger) *Runner {
	if logger == nil {
		logger = slog.Default()
	}
	if cfg.Now == nil {
		cfg.Now = time.Now
	}
	if cfg.MaxRows <= 0 {
		cfg.MaxRows = 50000
	}
	if cfg.ChunkDays <= 0 {
		cfg.ChunkDays = 7
	}
	if cfg.StaleAfterDays <= 0 {
		cfg.StaleAfterDays = 3
	}
	r := &Runner{reg: reg, store: st, router: router, cfg: cfg, logger: logger}
	r.lock = func(ctx context.Context, projectID string) (func(), bool, error) {
		return TryProjectLock(ctx, st.DB(), projectID)
	}
	return r
}

// statusRank orders statuses from best to worst; a metric takes the worst status
// of the entities it reads.
var statusRank = map[string]int{
	intel.StatusCurrent: 0, intel.StatusDelayed: 1, intel.StatusIncomplete: 2, intel.StatusStale: 3, intel.StatusBlocked: 4,
}

func worse(a, b string) string {
	if statusRank[b] > statusRank[a] {
		return b
	}
	return a
}

type entityState struct {
	usable bool
	status string
	issues []intel.Issue
	latest *time.Time // newest event date at the source (freshness), nil when not measured
}

// runCtx is the per-run context shared by the steps.
type runCtx struct {
	projectID string
	now       time.Time
	asOf      time.Time // last data day, inclusive
	loc       *time.Location
	comp      *intel.Compiler
	mappings  []intel.Mapping
	entities  map[string]*entityState
}

// Run computes every enabled metric of the project (or opts.Metrics).
func (r *Runner) Run(ctx context.Context, projectID string, opts RunOptions) (*RunSummary, error) {
	if (opts.From == nil) != (opts.To == nil) {
		return nil, fmt.Errorf("runner: from and to must be given together")
	}
	if opts.From != nil && !opts.From.Before(*opts.To) {
		return nil, fmt.Errorf("runner: from must be before to")
	}
	release, ok, err := r.lock(ctx, projectID)
	if err != nil {
		return nil, fmt.Errorf("runner: lock: %w", err)
	}
	if !ok {
		return nil, ErrRunInProgress
	}
	defer release()

	cat, err := ProjectCatalog(ctx, r.reg, r.store, projectID)
	if err != nil {
		return nil, fmt.Errorf("runner: catalog: %w", err)
	}
	mappings, err := r.store.ListMappings(ctx, projectID)
	if err != nil {
		return nil, fmt.Errorf("runner: mappings: %w", err)
	}
	settings, err := r.store.GetProjectSettings(ctx, projectID)
	if err != nil {
		return nil, fmt.Errorf("runner: settings: %w", err)
	}
	rc := &runCtx{projectID: projectID, now: r.cfg.Now(), mappings: mappings,
		comp: &intel.Compiler{Dialect: intel.Postgres{}, Catalog: cat}}
	rc.loc = ResolveTimezone(settings, mappings, r.cfg.DefaultTimezone)
	rc.asOf = AsOf(settings, rc.now, rc.loc)
	sum := &RunSummary{ProjectID: projectID, AsOf: rc.asOf.Format(dateFmt), Started: rc.now, Entities: map[string]string{}}
	if len(cat.Metrics) == 0 {
		return sum, nil
	}

	rc.entities = r.prepareEntities(ctx, rc)
	for name, st := range rc.entities {
		sum.Entities[name] = st.status
	}
	avail := Availability(cat, rc.mappings)

	for _, key := range cat.MetricKeys() {
		if len(opts.Metrics) > 0 && !contains(opts.Metrics, key) {
			continue
		}
		def := cat.Metrics[key]
		if st := avail[key]; !st.Enabled {
			sum.Metrics = append(sum.Metrics, MetricOutcome{Key: key, Status: "skipped", Error: st.Reason})
			continue
		}
		if blocked, status, issues := blockedByEntity(def, rc.entities); blocked {
			r.writeStatus(ctx, intel.DataStatus{ProjectID: projectID, Subject: intel.MetricSubject(key), Status: status, Issues: issues})
			sum.Metrics = append(sum.Metrics, MetricOutcome{Key: key, Status: status, Error: issues[0].Message})
			continue
		}
		sum.Metrics = append(sum.Metrics, r.runMetric(ctx, rc, def, opts))
	}
	return sum, nil
}

// prepareEntities refreshes sources, binds every approved mapping used by the
// catalog, marks drifted mappings broken, validates enums / required fields and
// measures freshness against the as-of date.
func (r *Runner) prepareEntities(ctx context.Context, rc *runCtx) map[string]*entityState {
	needed := map[string]bool{}
	for _, m := range rc.comp.Catalog.Metrics {
		for _, e := range m.Requires {
			needed[e] = true
		}
	}
	byMode := map[intel.SourceMode][]int{}
	for i, m := range rc.mappings {
		if needed[m.Entity] && m.Status == intel.MappingApproved {
			byMode[m.Mode] = append(byMode[m.Mode], i)
		}
	}
	out := map[string]*entityState{}
	modes := make([]string, 0, len(byMode))
	for mode := range byMode {
		modes = append(modes, string(mode))
	}
	sort.Strings(modes)
	for _, modeName := range modes {
		idxs := byMode[intel.SourceMode(modeName)]
		group := make([]intel.Mapping, 0, len(idxs))
		for _, i := range idxs {
			group = append(group, rc.mappings[i])
		}
		res, err := r.router.Resolver(intel.SourceMode(modeName))
		if err == nil {
			err = res.Prepare(ctx, rc.projectID, group)
		}
		if err != nil {
			for _, m := range group {
				st := &entityState{status: r.unreachableStatus(ctx, rc, m.Entity),
					issues: []intel.Issue{{Code: "source_unreachable", Message: err.Error()}}}
				out[m.Entity] = st
				r.writeStatus(ctx, intel.DataStatus{ProjectID: rc.projectID, Subject: intel.EntitySubject(m.Entity), Status: st.status, Issues: st.issues})
			}
			continue
		}
		for _, i := range idxs {
			m := &rc.mappings[i]
			st := r.prepareEntity(ctx, rc, res, m)
			out[m.Entity] = st
			ds := intel.DataStatus{ProjectID: rc.projectID, Subject: intel.EntitySubject(m.Entity), Status: st.status, Issues: st.issues, PeriodTo: st.latest}
			if st.usable {
				t := rc.now.UTC()
				ds.LastSuccessAt = &t
			}
			r.writeStatus(ctx, ds)
		}
	}
	return out
}

func (r *Runner) prepareEntity(ctx context.Context, rc *runCtx, res intel.SourceResolver, m *intel.Mapping) *entityState {
	bound, err := res.Bind(ctx, rc.projectID, *m)
	if err == nil {
		_, err = rc.comp.EntityCTE(m.Entity, *m, bound.Table, rc.loc.String())
	}
	var me *intel.MappingError
	switch {
	case errors.As(err, &me):
		if serr := r.store.SetMappingStatus(ctx, rc.projectID, m.Entity, intel.MappingBroken); serr != nil {
			r.logger.ErrorContext(ctx, "intel: mark mapping broken", "entity", m.Entity, "error", serr)
		}
		m.Status = intel.MappingBroken
		return &entityState{status: intel.StatusBlocked, issues: []intel.Issue{{Code: "mapping_broken", Message: me.Error(), Detail: me.Code}}}
	case errors.Is(err, intel.ErrSourceNotReady):
		return &entityState{status: intel.StatusIncomplete, issues: []intel.Issue{{Code: "source_not_ready", Message: err.Error()}}}
	case err != nil:
		return &entityState{status: intel.StatusDelayed, issues: []intel.Issue{{Code: "bind_failed", Message: err.Error()}}}
	}
	st := &entityState{usable: true, status: intel.StatusCurrent}
	st.issues = r.validateEntity(ctx, rc.comp, *m, bound)
	if len(st.issues) > 0 {
		st.status = intel.StatusIncomplete
	}
	r.measureFreshness(ctx, rc, *m, bound, st)
	return st
}

// measureFreshness compares the newest event date of a transactional entity (its
// first required timestamp field) with the as-of date: lag 0 (data through as-of)
// = current, 1..StaleAfterDays-1 = delayed, more = stale (spec §6.6, master "As-of date").
func (r *Runner) measureFreshness(ctx context.Context, rc *runCtx, m intel.Mapping, b *intel.BoundSource, st *entityState) {
	ent := rc.comp.Catalog.Entities[m.Entity]
	var field string
	for _, f := range ent.Fields {
		if f.Required && f.Type == intel.TypeTimestamp {
			field = f.Name
			break
		}
	}
	if field == "" {
		return
	}
	q, err := rc.comp.LatestDateSQL(m, b.Table, field)
	if err != nil || q == "" {
		return
	}
	res, err := b.Executor.Query(ctx, q, nil, 1)
	if err != nil || len(res.Rows) == 0 || res.Rows[0][0] == nil {
		st.status = worse(st.status, intel.StatusIncomplete)
		st.issues = append(st.issues, intel.Issue{Code: "no_records", Message: fmt.Sprintf("%s has no records with %s", m.Entity, field)})
		return
	}
	latest, err := parseDate(res.Rows[0][0])
	if err != nil {
		return
	}
	st.latest = &latest
	lag := int(rc.asOf.Sub(latest).Hours() / 24)
	switch {
	case lag >= r.cfg.StaleAfterDays:
		st.status = worse(st.status, intel.StatusStale)
		st.issues = append(st.issues, intel.Issue{Code: "stale_data",
			Message: fmt.Sprintf("%s: newest record %s is %d days behind as-of %s", m.Entity, latest.Format(dateFmt), lag, rc.asOf.Format(dateFmt))})
	case lag >= 1:
		st.status = worse(st.status, intel.StatusDelayed)
		st.issues = append(st.issues, intel.Issue{Code: "late_data",
			Message: fmt.Sprintf("%s: newest record %s is %d day(s) behind as-of %s", m.Entity, latest.Format(dateFmt), lag, rc.asOf.Format(dateFmt))})
	}
}

// validateEntity reports enum values the mapping does not normalise and NULLs in
// required fields (spec §6.3 validation, §14.5) — reported, never silently dropped.
func (r *Runner) validateEntity(ctx context.Context, comp *intel.Compiler, m intel.Mapping, b *intel.BoundSource) []intel.Issue {
	var issues []intel.Issue
	ent := comp.Catalog.Entities[m.Entity]
	for _, f := range ent.Fields {
		allowed, isEnum := comp.Catalog.Enums[m.Entity+"."+f.Name]
		if !isEnum {
			continue
		}
		q, err := comp.EnumValuesSQL(m, b.Table, f.Name, 1001)
		if err != nil || q == "" {
			continue
		}
		res, err := b.Executor.Query(ctx, q, nil, 1000)
		if err != nil {
			issues = append(issues, intel.Issue{Code: "validation_failed", Message: fmt.Sprintf("%s.%s: %v", m.Entity, f.Name, err)})
			continue
		}
		ok := map[string]bool{}
		if em, has := m.Spec.EnumMap[f.Name]; has {
			for raw := range em {
				ok[raw] = true
			}
		} else {
			for _, v := range allowed {
				ok[v] = true
			}
		}
		var bad []string
		for _, row := range res.Rows {
			v := dimString(row[0])
			if !ok[v] && len(bad) < 20 {
				bad = append(bad, v)
			}
		}
		if len(bad) > 0 {
			issues = append(issues, intel.Issue{Code: "unmapped_enum_value",
				Message: fmt.Sprintf("%s.%s has source values not mapped to canonical values", m.Entity, f.Name), Detail: bad})
		}
	}
	var required []string
	for _, f := range ent.Fields {
		if f.Required {
			required = append(required, f.Name)
		}
	}
	q, err := comp.RequiredNullsSQL(m, b.Table, required, 100000)
	if err != nil || q == "" {
		return issues
	}
	res, err := b.Executor.Query(ctx, q, nil, 1)
	if err != nil {
		return append(issues, intel.Issue{Code: "validation_failed", Message: err.Error()})
	}
	if len(res.Rows) == 0 {
		return issues
	}
	total, _ := parseNumber(res.Rows[0][0])
	for i := 1; i < len(res.Columns); i++ {
		n, _ := parseNumber(res.Rows[0][i])
		if n != nil && *n > 0 && total != nil {
			issues = append(issues, intel.Issue{Code: "null_required_field",
				Message: fmt.Sprintf("%s.%s: %.0f of %.0f sampled rows are NULL", m.Entity, res.Columns[i], *n, *total)})
		}
	}
	return issues
}

// unreachableStatus: the source could not be reached. Delayed while the last
// success is recent (≤ 48h of wall-clock time), stale afterwards.
func (r *Runner) unreachableStatus(ctx context.Context, rc *runCtx, entity string) string {
	prev, err := r.store.GetDataStatus(ctx, rc.projectID, intel.EntitySubject(entity))
	if err == nil && prev != nil && prev.LastSuccessAt != nil && rc.now.Sub(*prev.LastSuccessAt) <= 48*time.Hour {
		return intel.StatusDelayed
	}
	return intel.StatusStale
}

func blockedByEntity(def *intel.MetricDef, entities map[string]*entityState) (bool, string, []intel.Issue) {
	for _, e := range def.Requires {
		st, ok := entities[e]
		if !ok {
			return true, intel.StatusBlocked, []intel.Issue{{Code: "entity_unavailable", Message: "entity " + e + " was not prepared"}}
		}
		if !st.usable {
			return true, st.status, st.issues
		}
	}
	return false, "", nil
}

type chunkCtx struct {
	def           *intel.MetricDef
	compiled      *intel.Compiled
	exec          intel.QueryExecutor
	meta          intelstore.WriteMeta
	lookbackStart time.Time
}

func (r *Runner) runMetric(ctx context.Context, rc *runCtx, def *intel.MetricDef, opts RunOptions) MetricOutcome {
	out := MetricOutcome{Key: def.Key}
	fail := func(code string, err error) MetricOutcome {
		out.Status, out.Error = intel.StatusBlocked, err.Error()
		r.writeStatus(ctx, intel.DataStatus{ProjectID: rc.projectID, Subject: intel.MetricSubject(def.Key), Status: intel.StatusBlocked,
			Issues: []intel.Issue{{Code: code, Message: err.Error()}}})
		return out
	}
	b, err := bindEntities(ctx, r.router, rc.comp, rc.projectID, rc.mappings, def.Requires, rc.loc.String())
	if err != nil {
		return fail("bind_failed", err)
	}
	compiled, err := rc.comp.CompileMetric(def, b.ctes)
	if err != nil {
		return fail("compile_failed", err)
	}
	from, to, lookbackStart, err := r.window(ctx, rc.projectID, def, opts, rc.asOf)
	if err != nil {
		return fail("window_failed", err)
	}
	out.From, out.To = from.Format(dateFmt), to.Format(dateFmt)
	cc := chunkCtx{def: def, compiled: compiled, exec: b.exec, lookbackStart: lookbackStart,
		meta: intelstore.WriteMeta{ProjectID: rc.projectID, MetricKey: def.Key, MetricVersion: def.Version,
			PackVersion: def.PackVersion, SourceMode: b.mode, Watermark: b.watermark}}
	for _, w := range chunkWindows(from, to, def.Grain, r.cfg.ChunkDays) {
		n, err := r.runChunk(ctx, cc, w[0], w[1])
		out.Rows += n
		if err != nil {
			code := "query_failed"
			switch {
			case errors.Is(err, errTruncated):
				code = "row_limit"
			case errors.Is(err, context.DeadlineExceeded):
				code = "query_timeout"
			case errors.Is(err, errInvalidResult):
				code = "invalid_result"
			}
			return fail(code, fmt.Errorf("window %s..%s: %w", w[0].Format(dateFmt), w[1].Format(dateFmt), err))
		}
	}
	status, issues := intel.StatusCurrent, []intel.Issue(nil)
	for _, e := range def.Requires {
		if st := rc.entities[e]; st != nil && st.status != intel.StatusCurrent {
			status = worse(status, st.status)
			issues = append(issues, st.issues...)
		}
	}
	t := rc.now.UTC()
	ds := intel.DataStatus{ProjectID: rc.projectID, Subject: intel.MetricSubject(def.Key), Status: status, Issues: issues, LastSuccessAt: &t}
	if _, minP, found, err := r.store.SeriesExtent(ctx, rc.projectID, def.Key); err == nil && found {
		last := to.AddDate(0, 0, -1)
		ds.PeriodFrom, ds.PeriodTo = &minP, &last
	}
	r.writeStatus(ctx, ds)
	out.Status = status
	return out
}

// runChunk executes one window; on truncation it halves the window down to one
// period (day grain) and blocks if a single period still exceeds the cap.
func (r *Runner) runChunk(ctx context.Context, cc chunkCtx, from, to time.Time) (int, error) {
	args, err := cc.compiled.Args(map[string]any{"from": from.Format(dateFmt), "to": to.Format(dateFmt)})
	if err != nil {
		return 0, err
	}
	res, err := cc.exec.Query(ctx, cc.compiled.SQL, args, r.cfg.MaxRows)
	if err != nil {
		return 0, err
	}
	if res.Truncated {
		days := int(to.Sub(from).Hours() / 24)
		if cc.def.Grain != intel.GrainDay || days <= 1 {
			return 0, errTruncated
		}
		mid := from.AddDate(0, 0, days/2)
		n1, err := r.runChunk(ctx, cc, from, mid)
		if err != nil {
			return n1, err
		}
		n2, err := r.runChunk(ctx, cc, mid, to)
		return n1 + n2, err
	}
	rows, err := ParseResult(cc.def, res, from, to)
	if err != nil {
		return 0, fmt.Errorf("%w: %v", errInvalidResult, err)
	}
	var deleteFrom *time.Time
	switch {
	case to.After(cc.lookbackStart):
		deleteFrom = &from // recent window: replace fully (late data, vanished dims)
	case len(rows) > 0:
		minP := rows[0].PeriodDate
		for _, row := range rows {
			if row.PeriodDate.Before(minP) {
				minP = row.PeriodDate
			}
		}
		deleteFrom = &minP // older window: never wipe days the source no longer holds
	}
	if err := r.store.ReplaceMetricRows(ctx, cc.meta, deleteFrom, &to, rows); err != nil {
		return 0, err
	}
	return len(rows), nil
}

// window picks [from, to) for a metric run: the lookback ending at asOf inclusive.
func (r *Runner) window(ctx context.Context, projectID string, def *intel.MetricDef, opts RunOptions, asOf time.Time) (from, to, lookbackStart time.Time, err error) {
	lookbackStart = asOf.AddDate(0, 0, -def.LookbackDays)
	if opts.From != nil {
		from, to = *opts.From, *opts.To
	} else {
		from, to = lookbackStart, asOf.AddDate(0, 0, 1)
		staleFrom, found, e := r.store.StaleSince(ctx, projectID, def.Key, def.Version)
		if e != nil {
			return from, to, lookbackStart, e
		}
		if found && staleFrom.Before(from) {
			from = staleFrom // version bump (or a bump backfill that failed half-way): recompute from the oldest old-version period
		}
	}
	if def.Grain == intel.GrainMonth {
		from = time.Date(from.Year(), from.Month(), 1, 0, 0, 0, 0, time.UTC)
		last := to.AddDate(0, 0, -1)
		to = time.Date(last.Year(), last.Month(), 1, 0, 0, 0, 0, time.UTC).AddDate(0, 1, 0)
		lookbackStart = time.Date(lookbackStart.Year(), lookbackStart.Month(), 1, 0, 0, 0, 0, time.UTC)
	}
	return from, to, lookbackStart, nil
}

// chunkWindows splits [from, to) into chunkDays-day windows (month grain: one month each).
func chunkWindows(from, to time.Time, grain intel.Grain, chunkDays int) [][2]time.Time {
	var out [][2]time.Time
	for cur := from; cur.Before(to); {
		next := cur.AddDate(0, 0, chunkDays)
		if grain == intel.GrainMonth {
			next = cur.AddDate(0, 1, 0)
		}
		if next.After(to) {
			next = to
		}
		out = append(out, [2]time.Time{cur, next})
		cur = next
	}
	return out
}

func (r *Runner) writeStatus(ctx context.Context, st intel.DataStatus) {
	if err := r.store.UpsertDataStatus(ctx, st); err != nil {
		r.logger.ErrorContext(ctx, "intel: write data status", "subject", st.Subject, "error", err)
	}
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}
```

- [ ] **Step 4: Chạy — PASS, 0 SKIP (thêm `-race`)**
```bash
cd ennam.kg.go && export KG_TEST_DATABASE_URL="postgres://ennam_kg:${KG_DB_PASSWORD:-ennam_kg_dev}@localhost:5433/ennam_kg?sslmode=disable"
go test -v -count=1 -race ./internal/intel/engine/ 2>&1 | tee /tmp/planb.out | grep -E "^(--- |ok|FAIL)"
grep -c -- '--- SKIP' /tmp/planb.out   # phải in 0 — test DB bị SKIP vẫn báo ok
```
Expected: PASS gồm `TestRunner_LookbackReplacesWindow`, `TestRunner_TruncatedChunkSplitsThenBlocks`, `TestRunner_TruncatedAtOneDayWritesNothing`, `TestRunner_SchemaDriftMarksMappingBroken`, `TestRunner_UnmappedEnumMakesMetricIncomplete`, `TestRunner_VersionBumpRecomputesStoredSeries`, `TestRunner_VersionBumpResumesAfterPartialFailure`, `TestRunner_SourceUnreachableIsStaleWithoutHistory`, `TestRunner_AsOfDrivesWindowAndFreshness`, `TestTryProjectLock_ReleaseAfterSessionLoss`, `TestRunner_SecondRunnerGetsInProgress`; SKIP = 0.

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.go add internal/intel/engine/runner.go internal/intel/engine/lock.go internal/intel/engine/fixture_test.go internal/intel/engine/runner_test.go
git -C ennam.kg.go commit -m "feat(intel): metric runner with chunked backfill, lookback and freshness" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 10: Scheduler hằng ngày + trigger (Plan C phụ thuộc `Trigger`)

**Files:** Create `internal/intel/engine/scheduler.go`, `internal/intel/engine/scheduler_test.go`.

**Interfaces:** Produces `type SchedulerConfig{DailyAt string; Interval time.Duration; DefaultTimezone string; Now func() time.Time}`; `func SchedulerConfigFromEnv() SchedulerConfig` (`METRIC_RUNNER_DAILY_AT`=05:00 theo múi giờ project, `METRIC_RUNNER_TIMEZONE`); `func NewScheduler(runner projectRunner, st schedulerStore, cfg SchedulerConfig, logger *slog.Logger) (*Scheduler, error)`; `(*Scheduler).Start(ctx)`, `Stop()`, `Tick(ctx)`, `Trigger(projectID string)` (implements `intel.RunTrigger`). Mẫu worker như `AgentContextRetentionWorker` (`internal/service/agent_context_retention.go`); chạy trùng giữa process bị chặn bởi advisory lock của runner; sau restart, `last_success_at` của `metric:*` ≥ slot hôm nay được coi là đã chạy.

- [ ] **Step 1: Viết test (failing)**
`internal/intel/engine/scheduler_test.go`:
```go
package engine

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/intelstore"
)

type fakeRunner struct {
	mu    sync.Mutex
	calls []string
	ch    chan string
}

func (f *fakeRunner) Run(_ context.Context, pid string, _ RunOptions) (*RunSummary, error) {
	f.mu.Lock()
	f.calls = append(f.calls, pid)
	f.mu.Unlock()
	if f.ch != nil {
		f.ch <- pid
	}
	return &RunSummary{ProjectID: pid}, nil
}

func (f *fakeRunner) count() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.calls)
}

type fakeSchedStore struct {
	statuses []intel.DataStatus
}

func (fakeSchedStore) ProjectsWithEnabledPacks(context.Context) ([]string, error) {
	return []string{"p1"}, nil
}
func (fakeSchedStore) ListMappings(context.Context, string) ([]intel.Mapping, error) {
	return []intel.Mapping{{Entity: "location", Spec: intel.MappingSpec{Fields: map[string]string{"timezone": "'America/Chicago'"}}}}, nil
}
func (f fakeSchedStore) ListDataStatus(context.Context, string) ([]intel.DataStatus, error) {
	return f.statuses, nil
}
func (fakeSchedStore) GetProjectSettings(context.Context, string) (intelstore.ProjectSettings, error) {
	return intelstore.ProjectSettings{}, nil
}

func chicago(t *testing.T, s string) time.Time {
	loc, _ := time.LoadLocation("America/Chicago")
	v, err := time.ParseInLocation("2006-01-02 15:04", s, loc)
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func TestScheduler_RunsOncePerDayAfterSlotInProjectTimezone(t *testing.T) {
	now := chicago(t, "2026-07-10 04:59")
	fr := &fakeRunner{}
	s, err := NewScheduler(fr, fakeSchedStore{}, SchedulerConfig{DailyAt: "05:00", Now: func() time.Time { return now }}, nil)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	s.Tick(ctx)
	if fr.count() != 0 {
		t.Fatal("must not run before 05:00 local")
	}
	now = chicago(t, "2026-07-10 05:01")
	s.Tick(ctx)
	s.Tick(ctx)
	if fr.count() != 1 {
		t.Fatalf("runs = %d, want exactly 1 per day", fr.count())
	}
	now = chicago(t, "2026-07-11 05:00")
	s.Tick(ctx)
	if fr.count() != 2 {
		t.Fatalf("runs = %d, want a new run the next day", fr.count())
	}
}

func TestScheduler_RestartTrustsDataStatus(t *testing.T) {
	done := chicago(t, "2026-07-10 05:03").UTC()
	st := fakeSchedStore{statuses: []intel.DataStatus{{Subject: "metric:base.x", LastSuccessAt: &done}}}
	fr := &fakeRunner{}
	s, _ := NewScheduler(fr, st, SchedulerConfig{DailyAt: "05:00", Now: func() time.Time { return chicago(t, "2026-07-10 09:00") }}, nil)
	s.Tick(context.Background())
	if fr.count() != 0 {
		t.Fatal("a metric success after today's slot means the daily run already happened")
	}
}

func TestScheduler_TriggerRunsAsynchronously(t *testing.T) {
	fr := &fakeRunner{ch: make(chan string, 1)}
	s, _ := NewScheduler(fr, fakeSchedStore{}, SchedulerConfig{DailyAt: "23:59", Interval: time.Hour}, nil)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	s.Start(ctx)
	defer s.Stop()
	s.Trigger("p-upload")
	select {
	case pid := <-fr.ch:
		if pid != "p-upload" {
			t.Fatalf("ran %s", pid)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("trigger was not processed")
	}
}

func TestNewScheduler_RejectsBadDailyAt(t *testing.T) {
	if _, err := NewScheduler(&fakeRunner{}, fakeSchedStore{}, SchedulerConfig{DailyAt: "25:00"}, nil); err == nil {
		t.Fatal("25:00 must be rejected")
	}
}
```

- [ ] **Step 2: Chạy — FAIL**
```bash
cd ennam.kg.go && go test -count=1 -run 'TestScheduler|TestNewScheduler' ./internal/intel/engine/
```
Expected: FAIL — `undefined: NewScheduler`.

- [ ] **Step 3: Implement**
`internal/intel/engine/scheduler.go`:
```go
package engine

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/intelstore"
)

// SchedulerConfig tunes the daily metric run.
type SchedulerConfig struct {
	DailyAt         string        // "HH:MM" in the project's business timezone (METRIC_RUNNER_DAILY_AT, default 05:00)
	Interval        time.Duration // tick interval (default 1 minute)
	DefaultTimezone string        // used when the location mapping has no timezone literal
	Now             func() time.Time
}

// SchedulerConfigFromEnv reads METRIC_RUNNER_DAILY_AT and METRIC_RUNNER_TIMEZONE.
// The daily slot uses the wall clock (it is when the job runs); the analysis
// window inside the run uses the project's as-of date.
func SchedulerConfigFromEnv() SchedulerConfig {
	cfg := SchedulerConfig{DailyAt: "05:00", Interval: time.Minute, DefaultTimezone: "UTC", Now: time.Now}
	if v := os.Getenv("METRIC_RUNNER_DAILY_AT"); v != "" {
		cfg.DailyAt = v
	}
	if v := os.Getenv("METRIC_RUNNER_TIMEZONE"); v != "" {
		cfg.DefaultTimezone = v
	}
	return cfg
}

type projectRunner interface {
	Run(ctx context.Context, projectID string, opts RunOptions) (*RunSummary, error)
}

type schedulerStore interface {
	ProjectsWithEnabledPacks(ctx context.Context) ([]string, error)
	ListMappings(ctx context.Context, projectID string) ([]intel.Mapping, error)
	ListDataStatus(ctx context.Context, projectID string) ([]intel.DataStatus, error)
	GetProjectSettings(ctx context.Context, projectID string) (intelstore.ProjectSettings, error)
}

// Scheduler runs the metric runner once a day per project (after the configured
// local time) and on demand via Trigger (Plan C: after a tabular upload). It is a
// time.NewTicker worker like the other DAAB workers (spec I7); duplicate runs
// across processes are prevented by the runner's advisory lock.
type Scheduler struct {
	runner  projectRunner
	store   schedulerStore
	cfg     SchedulerConfig
	hh, mm  int
	logger  *slog.Logger
	trigger chan string
	stopCh  chan struct{}
	once    sync.Once
	mu      sync.Mutex
	done    map[string]time.Time // project → daily slot already completed
}

var _ intel.RunTrigger = (*Scheduler)(nil)

// NewScheduler validates DailyAt ("HH:MM").
func NewScheduler(runner projectRunner, st schedulerStore, cfg SchedulerConfig, logger *slog.Logger) (*Scheduler, error) {
	var hh, mm int
	if _, err := fmt.Sscanf(strings.TrimSpace(cfg.DailyAt), "%d:%d", &hh, &mm); err != nil || hh < 0 || hh > 23 || mm < 0 || mm > 59 {
		return nil, fmt.Errorf("scheduler: METRIC_RUNNER_DAILY_AT %q must be HH:MM", cfg.DailyAt)
	}
	if cfg.Interval <= 0 {
		cfg.Interval = time.Minute
	}
	if cfg.Now == nil {
		cfg.Now = time.Now
	}
	if logger == nil {
		logger = slog.Default()
	}
	return &Scheduler{runner: runner, store: st, cfg: cfg, hh: hh, mm: mm, logger: logger,
		trigger: make(chan string, 64), stopCh: make(chan struct{}), done: map[string]time.Time{}}, nil
}

// Trigger queues a run for projectID without blocking; a full queue drops the
// request with a warning (the next daily run still covers it).
func (s *Scheduler) Trigger(projectID string) {
	select {
	case s.trigger <- projectID:
	default:
		s.logger.Warn("intel scheduler: trigger queue full, dropping", "project_id", projectID)
	}
}

// Start runs the loop until Stop or ctx cancellation.
func (s *Scheduler) Start(ctx context.Context) {
	go func() {
		s.logger.Info("intel metric scheduler started", "daily_at", s.cfg.DailyAt, "interval", s.cfg.Interval)
		ticker := time.NewTicker(s.cfg.Interval)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				s.Tick(ctx)
			case pid := <-s.trigger:
				s.run(ctx, pid, "trigger")
			case <-s.stopCh:
				s.logger.Info("intel metric scheduler stopped")
				return
			case <-ctx.Done():
				return
			}
		}
	}()
}

// Stop signals the loop to exit.
func (s *Scheduler) Stop() { s.once.Do(func() { close(s.stopCh) }) }

// Tick runs every project whose daily slot has passed and is not done yet.
func (s *Scheduler) Tick(ctx context.Context) {
	projects, err := s.store.ProjectsWithEnabledPacks(ctx)
	if err != nil {
		s.logger.ErrorContext(ctx, "intel scheduler: list projects", "error", err)
		return
	}
	for _, pid := range projects {
		slot, due, err := s.due(ctx, pid)
		if err != nil {
			s.logger.ErrorContext(ctx, "intel scheduler: due check", "project_id", pid, "error", err)
			continue
		}
		if !due {
			continue
		}
		if s.run(ctx, pid, "daily") {
			s.mu.Lock()
			s.done[pid] = slot
			s.mu.Unlock()
		}
	}
}

// due reports whether today's slot (in the project's timezone) has passed and no
// run completed since. After a restart the last metric success time from
// data_status stands in for the in-memory record.
func (s *Scheduler) due(ctx context.Context, pid string) (time.Time, bool, error) {
	mappings, err := s.store.ListMappings(ctx, pid)
	if err != nil {
		return time.Time{}, false, err
	}
	settings, err := s.store.GetProjectSettings(ctx, pid)
	if err != nil {
		return time.Time{}, false, err
	}
	loc := ResolveTimezone(settings, mappings, s.cfg.DefaultTimezone)
	now := s.cfg.Now().In(loc)
	slot := time.Date(now.Year(), now.Month(), now.Day(), s.hh, s.mm, 0, 0, loc)
	if now.Before(slot) {
		return slot, false, nil
	}
	s.mu.Lock()
	last, ok := s.done[pid]
	s.mu.Unlock()
	if ok && !last.Before(slot) {
		return slot, false, nil
	}
	statuses, err := s.store.ListDataStatus(ctx, pid)
	if err != nil {
		return slot, false, err
	}
	for _, st := range statuses {
		if strings.HasPrefix(st.Subject, "metric:") && st.LastSuccessAt != nil && !st.LastSuccessAt.Before(slot) {
			s.mu.Lock()
			s.done[pid] = slot
			s.mu.Unlock()
			return slot, false, nil
		}
	}
	return slot, true, nil
}

func (s *Scheduler) run(ctx context.Context, pid, reason string) bool {
	sum, err := s.runner.Run(ctx, pid, RunOptions{})
	if errors.Is(err, ErrRunInProgress) {
		s.logger.InfoContext(ctx, "intel scheduler: run already in progress", "project_id", pid, "reason", reason)
		return false
	}
	if err != nil {
		s.logger.ErrorContext(ctx, "intel scheduler: run failed", "project_id", pid, "reason", reason, "error", err)
		return false
	}
	s.logger.InfoContext(ctx, "intel scheduler: run finished", "project_id", pid, "reason", reason, "metrics", len(sum.Metrics))
	return true
}
```

- [ ] **Step 4: Chạy — PASS**
```bash
cd ennam.kg.go && go test -count=1 -run 'TestScheduler|TestNewScheduler' -race ./internal/intel/engine/
```
Expected: `ok`

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.go add internal/intel/engine/scheduler.go internal/intel/engine/scheduler_test.go
git -C ennam.kg.go commit -m "feat(intel): daily metric scheduler with upload trigger" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 11: Query service cho 4 tool (gộp kỳ, dims_filter trong SQL, evidence ≤ 12s, as_of)

**Files:** Create `internal/intel/engine/query.go`, `internal/intel/engine/query_test.go`.

**Interfaces:** Produces `func NewQueryService(reg, st, router, cfg RunnerConfig, logger) *QueryService`; `GetMetrics(ctx, MetricsRequest) (*MetricsResponse, error)`, `GetEvidence(ctx, EvidenceRequest) (*EvidenceResponse, error)`, `GetDataStatus(ctx, projectID) (*DataStatusResponse, error)`, `ListMetrics(ctx, projectID) (*ListMetricsResponse, error)`; JSON đúng master §2.4 (thêm `as_of` ở cả 3 output); `type APIError{Code, Message}`; mã lỗi `unknown_metric`, `invalid_range`, `metric_disabled` (+ `invalid_request` — xem Open questions). Giới hạn: ≤ 50 metric/lần, khoảng ≤ 731 ngày (metrics) / ≤ 92 ngày (evidence), `limit` 1..200 (mặc định 50), `EvidenceTimeout = 12s`.

Quy tắc: `grain` mặc định `day`; `to` bỏ trống ⇒ `as_of + 1` (`as_of` = ngày dữ liệu cuối, bao gồm); `group_by` bỏ trống ⇒ mọi dim của metric, dim lạ bị bỏ qua; `dims_filter` nêu dim metric không có ⇒ `invalid_request`, còn lại đặt trong WHERE; ratio ⇒ `value = RatioValue(SUM(num), SUM(den))`; snapshot ⇒ tổng giá trị ngày cuối mỗi kỳ; evidence: `dims` là **tập con bất kỳ** của dims metric — dim bỏ trống được bind `NULL` và không lọc (mọi evidence SQL viết `(:dim_x IS NULL OR COALESCE(col, ) = :dim_x)`), dim không thuộc metric ⇒ `invalid_request`, dim bị `dims_filter` giới hạn mà không có trong `dims` ⇒ `invalid_request` (phạm vi chi nhánh không thể nới bằng cách bỏ dim), giá trị nằm ngoài `dims_filter` ⇒ trang rỗng **không** truy vấn nguồn; timestamp trả dạng giờ địa phương `YYYY-MM-DDTHH:MM:SS`.

- [ ] **Step 1: Viết test (failing)**
`internal/intel/engine/query_test.go`:
```go
package engine

import (
	"context"
	"errors"
	"testing"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/intelstore"
)

func (e *env) query() *QueryService {
	return NewQueryService(e.reg, e.store, e.router, RunnerConfig{DefaultTimezone: "UTC"}, nil)
}

func (e *env) put(t *testing.T, key string, version int, rows ...intelstore.MetricRow) {
	t.Helper()
	for i := range rows {
		rows[i].DimsHash = DimsHash(rows[i].Dims)
	}
	if err := e.store.ReplaceMetricRows(context.Background(), intelstore.WriteMeta{ProjectID: e.pid, MetricKey: key,
		MetricVersion: version, PackVersion: "x", SourceMode: intel.ModeLive}, nil, nil, rows); err != nil {
		t.Fatal(err)
	}
}

func ratioRow(d, loc string, num, den float64, ss int) intelstore.MetricRow {
	return intelstore.MetricRow{PeriodDate: dayT(d), Dims: map[string]string{"location_id": loc}, Numerator: &num, Denominator: &den, SampleSize: ss}
}

func valueRow(d, loc string, v float64) intelstore.MetricRow {
	return intelstore.MetricRow{PeriodDate: dayT(d), Dims: map[string]string{"location_id": loc}, Value: &v, SampleSize: 1}
}

// Review Focus #4: 30-day rollup of a ratio is SUM(num)/SUM(den) — a low-volume
// day must not weigh like a high-volume one.
func TestQuery_RatioAggregatesSums(t *testing.T) {
	e := newEnv(t)
	if err := e.store.UpsertInstall(context.Background(), e.pid, "child", "1.2.3", true); err != nil {
		t.Fatal(err)
	}
	e.put(t, "child.closed_share", 1,
		ratioRow("2026-07-01", "S1", 1, 1, 1),   // 100% on 1 order
		ratioRow("2026-07-02", "S1", 0, 99, 99), // 0% on 99 orders
	)
	resp, err := e.query().GetMetrics(context.Background(), MetricsRequest{ProjectID: e.pid,
		MetricKeys: []string{"child.closed_share"}, From: "2026-07-01", To: "2026-07-31", Grain: "total"})
	if err != nil {
		t.Fatal(err)
	}
	p := resp.Series[0].Points[0]
	if *p.Numerator != 1 || *p.Denominator != 100 || *p.Value != 1 || p.SampleSize != 100 || p.Period != "2026-07-01" {
		t.Fatalf("point = %+v (average of daily ratios would be 50)", p)
	}
	if resp.Series[0].Aggregation != "ratio" || resp.Series[0].Unit != "percent" {
		t.Fatalf("series = %+v", resp.Series[0])
	}
}

func TestQuery_DimsFilterInSQLAndGrain(t *testing.T) {
	e := newEnv(t)
	e.put(t, "base.order_total", 2,
		valueRow("2026-06-29", "S1", 1), // Monday of ISO week 27
		valueRow("2026-07-01", "S1", 2),
		valueRow("2026-07-01", "S2", 50),
		valueRow("2026-07-06", "S1", 4),
	)
	q := e.query()
	resp, err := q.GetMetrics(context.Background(), MetricsRequest{ProjectID: e.pid, MetricKeys: []string{"base.order_total"},
		From: "2026-06-29", To: "2026-07-13", Grain: "week", DimsFilter: map[string][]string{"location_id": {"S1"}}})
	if err != nil {
		t.Fatal(err)
	}
	pts := resp.Series[0].Points
	if len(pts) != 2 || pts[0].Period != "2026-06-29" || *pts[0].Value != 3 || pts[1].Period != "2026-07-06" || *pts[1].Value != 4 {
		t.Fatalf("weekly S1 points = %+v", pts)
	}
	if len(resp.Series[0].VersionsInSeries) != 1 || resp.Series[0].VersionsInSeries[0] != 2 {
		t.Fatalf("versions = %v", resp.Series[0].VersionsInSeries)
	}
	var ae *APIError
	if _, err := q.GetMetrics(context.Background(), MetricsRequest{ProjectID: e.pid, MetricKeys: []string{"base.order_total"},
		From: "2026-06-29", To: "2026-07-13", DimsFilter: map[string][]string{"location_id": {"S1"}, "not_a_dim": {"x"}}}); !errors.As(err, &ae) || ae.Code != CodeInvalidRequest {
		t.Fatalf("dims_filter on a dim the metric lacks must be invalid_request, got %v", err)
	}
	all, err := q.GetMetrics(context.Background(), MetricsRequest{ProjectID: e.pid, MetricKeys: []string{"base.order_total"},
		From: "2026-07-01", To: "2026-08-01", Grain: "month", GroupBy: []string{}})
	if err != nil {
		t.Fatal(err)
	}
	if len(all.Series[0].Points) != 1 || *all.Series[0].Points[0].Value != 56 || len(all.Series[0].Points[0].Dims) != 0 {
		t.Fatalf("monthly total = %+v", all.Series[0].Points)
	}
}

func TestQuery_ToDefaultsToAsOfPlusOne(t *testing.T) {
	e := newEnv(t)
	asOf := dayT("2026-07-31")
	if err := e.store.SetAsOf(context.Background(), e.pid, &asOf, ""); err != nil {
		t.Fatal(err)
	}
	e.put(t, "base.order_total", 2, valueRow("2026-07-31", "S1", 5), valueRow("2026-08-01", "S1", 99))
	resp, err := e.query().GetMetrics(context.Background(), MetricsRequest{ProjectID: e.pid, MetricKeys: []string{"base.order_total"},
		From: "2026-07-01", Grain: "total"})
	if err != nil {
		t.Fatal(err)
	}
	if resp.AsOf != "2026-07-31" || len(resp.Series[0].Points) != 1 || *resp.Series[0].Points[0].Value != 5 {
		t.Fatalf("resp = %+v (to must default to as_of + 1, exclusive)", resp)
	}
}

func TestQuery_SnapshotTakesLastDayOfBucket(t *testing.T) {
	e := newEnv(t)
	e.put(t, "base.open_count", 1, valueRow("2026-07-01", "S1", 10), valueRow("2026-07-05", "S1", 3), valueRow("2026-07-05", "S2", 4))
	resp, err := e.query().GetMetrics(context.Background(), MetricsRequest{ProjectID: e.pid, MetricKeys: []string{"base.open_count"},
		From: "2026-07-01", To: "2026-07-08", Grain: "total", GroupBy: []string{}})
	if err != nil {
		t.Fatal(err)
	}
	if p := resp.Series[0].Points[0]; *p.Value != 7 {
		t.Fatalf("snapshot total = %v, want 3+4 on the last day", *p.Value)
	}
}

func TestQuery_Errors(t *testing.T) {
	e := newEnv(t)
	q := e.query()
	cases := map[string]struct {
		req  MetricsRequest
		code string
	}{
		"unknown":  {MetricsRequest{ProjectID: e.pid, MetricKeys: []string{"child.closed_share"}, From: "2026-07-01", To: "2026-07-02"}, CodeUnknownMetric},
		"range":    {MetricsRequest{ProjectID: e.pid, MetricKeys: []string{"base.order_total"}, From: "2026-07-02", To: "2026-07-01"}, CodeInvalidRange},
		"bad date": {MetricsRequest{ProjectID: e.pid, MetricKeys: []string{"base.order_total"}, From: "07/01/2026", To: "2026-07-02"}, CodeInvalidRange},
		"grain":    {MetricsRequest{ProjectID: e.pid, MetricKeys: []string{"base.order_total"}, From: "2026-07-01", To: "2026-07-02", Grain: "hour"}, CodeInvalidRequest},
	}
	for name, tc := range cases {
		_, err := q.GetMetrics(context.Background(), tc.req)
		var ae *APIError
		if !errors.As(err, &ae) || ae.Code != tc.code {
			t.Errorf("%s: err = %v, want code %s", name, err, tc.code)
		}
	}
	e.mapOrders(t, "total")
	if err := e.store.SetMappingStatus(context.Background(), e.pid, "order", intel.MappingBroken); err != nil {
		t.Fatal(err)
	}
	_, err := q.GetMetrics(context.Background(), MetricsRequest{ProjectID: e.pid, MetricKeys: []string{"base.order_total"}, From: "2026-07-01", To: "2026-07-02"})
	var ae *APIError
	if !errors.As(err, &ae) || ae.Code != CodeMetricDisabled {
		t.Fatalf("broken mapping: %v", err)
	}
	ds, err := q.GetDataStatus(context.Background(), e.pid)
	if err != nil || len(ds.DisabledMetrics) != 2 || ds.DisabledMetrics[0].MetricKey != "base.open_count" {
		t.Fatalf("data status = %+v, %v", ds, err)
	}
}

func TestQuery_EvidencePagingAndBranchScope(t *testing.T) {
	e := newEnv(t)
	e.order(t, "o1", "S1", "2026-07-08 10:00", 10, "CLOSED")
	e.order(t, "o2", "S1", "2026-07-08 11:00", 20, "CLOSED")
	e.order(t, "o3", "S1", "2026-07-08 12:00", 30, "CLOSED")
	e.order(t, "o4", "S2", "2026-07-08 12:00", 40, "CLOSED")
	q := e.query()
	ctx := context.Background()
	page, err := q.GetEvidence(ctx, EvidenceRequest{ProjectID: e.pid, MetricKey: "base.order_total", From: "2026-07-08", To: "2026-07-09",
		Dims: map[string]string{"location_id": "S1"}, Limit: 2})
	if err != nil {
		t.Fatal(err)
	}
	if len(page.Rows) != 2 || !page.HasMore || page.SourceMode != "live" || page.Columns[3] != "_source_ref" {
		t.Fatalf("page 1 = %+v", page)
	}
	if page.Rows[0][3] != "orders:o1" || page.Rows[0][1] != "2026-07-08T10:00:00" {
		t.Fatalf("row = %v", page.Rows[0])
	}
	page2, _ := q.GetEvidence(ctx, EvidenceRequest{ProjectID: e.pid, MetricKey: "base.order_total", From: "2026-07-08", To: "2026-07-09",
		Dims: map[string]string{"location_id": "S1"}, Limit: 2, Offset: 2})
	if len(page2.Rows) != 1 || page2.HasMore {
		t.Fatalf("page 2 = %+v", page2)
	}
	scoped, err := q.GetEvidence(ctx, EvidenceRequest{ProjectID: e.pid, MetricKey: "base.order_total", From: "2026-07-08", To: "2026-07-09",
		Dims: map[string]string{"location_id": "S2"}, DimsFilter: map[string][]string{"location_id": {"S1"}}})
	if err != nil || len(scoped.Rows) != 0 {
		t.Fatalf("out-of-scope evidence must be empty: %+v %v", scoped, err)
	}
	// Subset of dims (here: none) = no filter on the omitted dim — rows of S1 and S2.
	all, err := q.GetEvidence(ctx, EvidenceRequest{ProjectID: e.pid, MetricKey: "base.order_total", From: "2026-07-08", To: "2026-07-09"})
	if err != nil || len(all.Rows) != 4 {
		t.Fatalf("omitted dim must not filter: %+v %v", all, err)
	}
	var ae *APIError
	if _, err := q.GetEvidence(ctx, EvidenceRequest{ProjectID: e.pid, MetricKey: "base.order_total", From: "2026-07-08", To: "2026-07-09",
		Dims: map[string]string{"product_id": "P1"}}); !errors.As(err, &ae) || ae.Code != CodeInvalidRequest {
		t.Fatalf("unknown dim must be invalid_request, got %v", err)
	}
	if _, err := q.GetEvidence(ctx, EvidenceRequest{ProjectID: e.pid, MetricKey: "base.order_total", From: "2026-07-08", To: "2026-07-09",
		DimsFilter: map[string][]string{"location_id": {"S1"}}}); !errors.As(err, &ae) || ae.Code != CodeInvalidRequest {
		t.Fatalf("a scoped dim omitted from dims must be rejected (scope cannot widen), got %v", err)
	}
}

func TestQuery_ListMetrics(t *testing.T) {
	e := newEnv(t)
	asOf := dayT("2026-07-31")
	if err := e.store.SetAsOf(context.Background(), e.pid, &asOf, ""); err != nil {
		t.Fatal(err)
	}
	resp, err := e.query().ListMetrics(context.Background(), e.pid)
	if err != nil {
		t.Fatal(err)
	}
	if resp.AsOf != "2026-07-31" || len(resp.Packs) != 1 || resp.Packs[0].Key != "base" || len(resp.Metrics) != 2 {
		t.Fatalf("resp = %+v", resp)
	}
	m := resp.Metrics[1]
	if m.Key != "base.order_total" || !m.Enabled || m.DisabledReason != nil || m.Aggregation != "additive" || m.Grain != "day" {
		t.Fatalf("metric = %+v", m)
	}
}
```

- [ ] **Step 2: Chạy — FAIL**
```bash
cd ennam.kg.go && export KG_TEST_DATABASE_URL="postgres://ennam_kg:${KG_DB_PASSWORD:-ennam_kg_dev}@localhost:5433/ennam_kg?sslmode=disable"
go test -v -count=1 -run 'TestQuery' ./internal/intel/engine/ 2>&1 | tee /tmp/planb.out | grep -E "^(--- |ok|FAIL)"
grep -c -- '--- SKIP' /tmp/planb.out   # phải in 0 — test DB bị SKIP vẫn báo ok
```
Expected: FAIL — `undefined: NewQueryService`.

- [ ] **Step 3: Implement**
`internal/intel/engine/query.go`:
```go
package engine

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sort"
	"time"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/intelstore"
)

// Error codes of the 4 tools (master §2.4). CodeInvalidRequest is the one
// addition (malformed body / unknown grain / missing dims) — see plan Open questions.
const (
	CodeUnknownMetric  = "unknown_metric"
	CodeInvalidRange   = "invalid_range"
	CodeMetricDisabled = "metric_disabled"
	CodeInvalidRequest = "invalid_request"
)

// APIError is a client error rendered as HTTP 400 {error:{code,message}}.
type APIError struct {
	Code    string
	Message string
}

func (e *APIError) Error() string { return e.Code + ": " + e.Message }

func apiErr(code, format string, args ...any) error {
	return &APIError{Code: code, Message: fmt.Sprintf(format, args...)}
}

// Limits of the read path.
const (
	MaxMetricKeys       = 50
	MaxMetricRangeDays  = 731
	MaxEvidenceDays     = 92
	DefaultEvidenceRows = 50
	MaxEvidenceRows     = 200
	EvidenceTimeout     = 12 * time.Second // LAAM's MCP timeout is 15s (spec I4)
)

// QueryService serves kg_get_metrics / kg_get_evidence / kg_get_data_status /
// kg_list_metrics. It never queries the customer DB except for evidence.
type QueryService struct {
	reg             *intel.Registry
	store           *intelstore.Store
	router          *SourceRouter
	defaultTimezone string
	now             func() time.Time
	logger          *slog.Logger
}

// NewQueryService wires the read service (cfg supplies the default timezone and clock).
func NewQueryService(reg *intel.Registry, st *intelstore.Store, router *SourceRouter, cfg RunnerConfig, logger *slog.Logger) *QueryService {
	if logger == nil {
		logger = slog.Default()
	}
	now := cfg.Now
	if now == nil {
		now = time.Now
	}
	return &QueryService{reg: reg, store: st, router: router, defaultTimezone: cfg.DefaultTimezone, now: now, logger: logger}
}

// ---- JSON shapes (master §2.4) ----

// MetricsRequest is the kg_get_metrics input.
type MetricsRequest struct {
	ProjectID  string              `json:"project_id"`
	MetricKeys []string            `json:"metric_keys"`
	From       string              `json:"from"`
	To         string              `json:"to"`
	Grain      string              `json:"grain"`
	GroupBy    []string            `json:"group_by"`
	DimsFilter map[string][]string `json:"dims_filter"`
}

// Point is one output point.
type Point struct {
	Period      string            `json:"period"`
	Dims        map[string]string `json:"dims"`
	Value       *float64          `json:"value"`
	Numerator   *float64          `json:"numerator"`
	Denominator *float64          `json:"denominator"`
	SampleSize  int64             `json:"sample_size"`
}

// Series is one metric's output.
type Series struct {
	MetricKey        string  `json:"metric_key"`
	Unit             string  `json:"unit"`
	Aggregation      string  `json:"aggregation"`
	Points           []Point `json:"points"`
	VersionsInSeries []int   `json:"versions_in_series"`
}

// StatusItem is one data_status entry.
type StatusItem struct {
	Subject       string        `json:"subject"`
	Status        string        `json:"status"`
	LastSuccessAt *time.Time    `json:"last_success_at"`
	PeriodFrom    *string       `json:"period_from"`
	PeriodTo      *string       `json:"period_to"`
	Issues        []intel.Issue `json:"issues"`
}

// MetricsResponse is the kg_get_metrics output.
type MetricsResponse struct {
	Series     []Series     `json:"series"`
	DataStatus []StatusItem `json:"data_status"`
	AsOf       string       `json:"as_of"`
}

// EvidenceRequest is the kg_get_evidence input.
type EvidenceRequest struct {
	ProjectID  string              `json:"project_id"`
	MetricKey  string              `json:"metric_key"`
	From       string              `json:"from"`
	To         string              `json:"to"`
	Dims       map[string]string   `json:"dims"`
	DimsFilter map[string][]string `json:"dims_filter"`
	Limit      int                 `json:"limit"`
	Offset     int                 `json:"offset"`
}

// EvidenceResponse is the kg_get_evidence output.
type EvidenceResponse struct {
	Columns    []string `json:"columns"`
	Rows       [][]any  `json:"rows"`
	HasMore    bool     `json:"has_more"`
	SourceMode string   `json:"source_mode"`
}

// DisabledMetric is one entry of kg_get_data_status.disabled_metrics.
type DisabledMetric struct {
	MetricKey string `json:"metric_key"`
	Reason    string `json:"reason"`
}

// DataStatusResponse is the kg_get_data_status output. AsOf is the last data day
// (inclusive): the project's override, else yesterday in its timezone (master §2.4).
type DataStatusResponse struct {
	AsOf            string           `json:"as_of"`
	Items           []StatusItem     `json:"items"`
	DisabledMetrics []DisabledMetric `json:"disabled_metrics"`
}

// CatalogMetric is one entry of kg_list_metrics.metrics.
type CatalogMetric struct {
	Key            string   `json:"key"`
	Unit           string   `json:"unit"`
	Aggregation    string   `json:"aggregation"`
	Grain          string   `json:"grain"`
	Dims           []string `json:"dims"`
	Requires       []string `json:"requires"`
	SampleSize     string   `json:"sample_size"`
	Enabled        bool     `json:"enabled"`
	DisabledReason *string  `json:"disabled_reason"`
}

// ListMetricsResponse is the kg_list_metrics output (AsOf: see DataStatusResponse).
type ListMetricsResponse struct {
	AsOf    string          `json:"as_of"`
	Packs   []intel.PackRef `json:"packs"`
	Metrics []CatalogMetric `json:"metrics"`
}

// ---- helpers ----

func parseDay(s, field string) (time.Time, error) {
	t, err := time.Parse(dateFmt, s)
	if err != nil {
		return time.Time{}, apiErr(CodeInvalidRange, "%s must be YYYY-MM-DD", field)
	}
	return t, nil
}

func parseRange(from, to string, maxDays int) (time.Time, time.Time, error) {
	f, err := parseDay(from, "from")
	if err != nil {
		return f, f, err
	}
	t, err := parseDay(to, "to")
	if err != nil {
		return f, t, err
	}
	if !f.Before(t) {
		return f, t, apiErr(CodeInvalidRange, "from must be before to (to is exclusive)")
	}
	if t.Sub(f) > time.Duration(maxDays)*24*time.Hour {
		return f, t, apiErr(CodeInvalidRange, "range exceeds %d days", maxDays)
	}
	return f, t, nil
}

// projectState is everything the read path needs about a project.
type projectState struct {
	cat      *intel.Catalog
	mappings []intel.Mapping
	avail    map[string]MetricState
	loc      *time.Location
	asOf     time.Time
}

func (q *QueryService) state(ctx context.Context, projectID string) (*projectState, error) {
	if projectID == "" {
		return nil, apiErr(CodeInvalidRequest, "project_id is required")
	}
	cat, err := ProjectCatalog(ctx, q.reg, q.store, projectID)
	if err != nil {
		return nil, err
	}
	mappings, err := q.store.ListMappings(ctx, projectID)
	if err != nil {
		return nil, err
	}
	settings, err := q.store.GetProjectSettings(ctx, projectID)
	if err != nil {
		return nil, err
	}
	loc := ResolveTimezone(settings, mappings, q.defaultTimezone)
	return &projectState{cat: cat, mappings: mappings, avail: Availability(cat, mappings), loc: loc,
		asOf: AsOf(settings, q.now(), loc)}, nil
}

func toStatusItem(st intel.DataStatus) StatusItem {
	it := StatusItem{Subject: st.Subject, Status: st.Status, LastSuccessAt: st.LastSuccessAt, Issues: st.Issues}
	if it.Issues == nil {
		it.Issues = []intel.Issue{}
	}
	if st.PeriodFrom != nil {
		s := st.PeriodFrom.Format(dateFmt)
		it.PeriodFrom = &s
	}
	if st.PeriodTo != nil {
		s := st.PeriodTo.Format(dateFmt)
		it.PeriodTo = &s
	}
	return it
}

// checkFilterDims rejects a dims_filter naming a dim the metric does not have: a
// silently ignored filter would widen a caller's branch scope the day a metric
// without that dim is asked for (every pack metric carries location_id).
func checkFilterDims(filter map[string][]string, def *intel.MetricDef) error {
	for d := range filter {
		if !contains(def.Dims, d) {
			return apiErr(CodeInvalidRequest, "dims_filter.%s is not a dim of %s (dims: %v)", d, def.Key, def.Dims)
		}
	}
	return nil
}

func intersect(want, dims []string) []string {
	var out []string
	for _, d := range dims {
		if contains(want, d) {
			out = append(out, d)
		}
	}
	return out
}

// ---- tools ----

// GetMetrics reads metric_value and rolls it up per the metric's aggregation.
func (q *QueryService) GetMetrics(ctx context.Context, req MetricsRequest) (*MetricsResponse, error) {
	if len(req.MetricKeys) == 0 || len(req.MetricKeys) > MaxMetricKeys {
		return nil, apiErr(CodeInvalidRequest, "metric_keys must list 1..%d keys", MaxMetricKeys)
	}
	if req.Grain == "" {
		req.Grain = "day"
	}
	switch req.Grain {
	case "day", "week", "month", "total":
	default:
		return nil, apiErr(CodeInvalidRequest, "grain must be day|week|month|total")
	}
	ps, err := q.state(ctx, req.ProjectID)
	if err != nil {
		return nil, err
	}
	if req.To == "" {
		req.To = ps.asOf.AddDate(0, 0, 1).Format(dateFmt) // default `to` = as_of + 1 (exclusive)
	}
	from, to, err := parseRange(req.From, req.To, MaxMetricRangeDays)
	if err != nil {
		return nil, err
	}
	cat, avail := ps.cat, ps.avail
	for _, k := range req.MetricKeys {
		st, ok := avail[k]
		if !ok {
			return nil, apiErr(CodeUnknownMetric, "metric %s is not in the packs enabled for this project", k)
		}
		if !st.Enabled {
			return nil, apiErr(CodeMetricDisabled, "metric %s is disabled: %s", k, st.Reason)
		}
		if err := checkFilterDims(req.DimsFilter, cat.Metrics[k]); err != nil {
			return nil, err
		}
	}
	resp := &MetricsResponse{Series: []Series{}, DataStatus: []StatusItem{}, AsOf: ps.asOf.Format(dateFmt)}
	for _, k := range req.MetricKeys {
		def := cat.Metrics[k]
		groupBy := def.Dims
		if req.GroupBy != nil {
			groupBy = intersect(req.GroupBy, def.Dims)
		}
		filter := map[string][]string{}
		for dim, vals := range req.DimsFilter {
			filter[dim] = vals // every key was checked against the metric's dims above
		}
		pts, err := q.store.QuerySeries(ctx, intelstore.SeriesQuery{ProjectID: req.ProjectID, MetricKey: k, From: from, To: to,
			Grain: req.Grain, GroupBy: groupBy, Filter: filter, Aggregation: def.Aggregation})
		if err != nil {
			return nil, err
		}
		versions, err := q.store.VersionsInSeries(ctx, req.ProjectID, k, from, to)
		if err != nil {
			return nil, err
		}
		s := Series{MetricKey: k, Unit: def.Unit, Aggregation: string(def.Aggregation), Points: make([]Point, 0, len(pts)), VersionsInSeries: versions}
		for _, p := range pts {
			pt := Point{Period: p.Period.Format(dateFmt), Dims: p.Dims, Value: p.Value, Numerator: p.Numerator, Denominator: p.Denominator, SampleSize: p.SampleSize}
			if def.Aggregation == intel.AggRatio {
				pt.Value = RatioValue(p.Numerator, p.Denominator, def.Unit)
			}
			s.Points = append(s.Points, pt)
		}
		resp.Series = append(resp.Series, s)
	}
	statuses, err := q.store.ListDataStatus(ctx, req.ProjectID)
	if err != nil {
		return nil, err
	}
	for _, st := range statuses {
		for _, k := range req.MetricKeys {
			if st.Subject == intel.MetricSubject(k) {
				resp.DataStatus = append(resp.DataStatus, toStatusItem(st))
			}
		}
	}
	return resp, nil
}

// GetEvidence runs the metric's evidence SQL where the data lives (live: on the
// customer DB, shown and discarded — never stored). dims may be any subset of the
// metric's dims (omitted = not filtered); unknown dim names are rejected. The
// branch filter is checked before any query is issued.
func (q *QueryService) GetEvidence(ctx context.Context, req EvidenceRequest) (*EvidenceResponse, error) {
	if req.MetricKey == "" {
		return nil, apiErr(CodeInvalidRequest, "metric_key is required")
	}
	if req.Limit == 0 {
		req.Limit = DefaultEvidenceRows
	}
	if req.Limit < 1 || req.Limit > MaxEvidenceRows || req.Offset < 0 {
		return nil, apiErr(CodeInvalidRequest, "limit must be 1..%d and offset >= 0", MaxEvidenceRows)
	}
	from, to, err := parseRange(req.From, req.To, MaxEvidenceDays)
	if err != nil {
		return nil, err
	}
	ps, err := q.state(ctx, req.ProjectID)
	if err != nil {
		return nil, err
	}
	cat, mappings := ps.cat, ps.mappings
	st, ok := ps.avail[req.MetricKey]
	if !ok {
		return nil, apiErr(CodeUnknownMetric, "metric %s is not in the packs enabled for this project", req.MetricKey)
	}
	if !st.Enabled {
		return nil, apiErr(CodeMetricDisabled, "metric %s is disabled: %s", req.MetricKey, st.Reason)
	}
	ev, ok := cat.Evidence[req.MetricKey]
	if !ok {
		return nil, apiErr(CodeUnknownMetric, "metric %s has no evidence query", req.MetricKey)
	}
	def := cat.Metrics[req.MetricKey]
	values := map[string]any{"from": from.Format(dateFmt), "to": to.Format(dateFmt), "_limit": req.Limit + 1, "_offset": req.Offset}
	for d := range req.Dims {
		if !contains(def.Dims, d) {
			return nil, apiErr(CodeInvalidRequest, "dims.%s is not a dim of %s (dims: %v)", d, req.MetricKey, def.Dims)
		}
	}
	if err := checkFilterDims(req.DimsFilter, def); err != nil {
		return nil, err
	}
	// A dim the caller omits is not filtered (findings are often rolled up to a
	// subset of the metric's dims): it is bound as NULL and every evidence query
	// reads `(:dim_x IS NULL OR col = :dim_x)`. A dim restricted by dims_filter
	// (branch scope) must be given explicitly, so scope can never widen by omission.
	for _, d := range def.Dims {
		v, ok := req.Dims[d]
		allowed, filtered := req.DimsFilter[d]
		if !ok {
			if filtered {
				return nil, apiErr(CodeInvalidRequest, "dims.%s is required because dims_filter restricts it", d)
			}
			values["dim_"+d] = nil
			continue
		}
		if filtered && !contains(allowed, v) {
			// Out of the caller's branch scope: answer empty without touching the source.
			return &EvidenceResponse{Columns: []string{}, Rows: [][]any{}, HasMore: false, SourceMode: q.modeOf(mappings, def)}, nil
		}
		values["dim_"+d] = v
	}
	tz := ps.loc.String()
	comp := &intel.Compiler{Dialect: intel.Postgres{}, Catalog: cat}
	b, err := bindEntities(ctx, q.router, comp, req.ProjectID, mappings, def.Requires, tz)
	if err != nil {
		return nil, fmt.Errorf("evidence bind: %w", err)
	}
	compiled, err := comp.CompileEvidence(ev, def.Requires, b.ctes)
	if err != nil {
		return nil, fmt.Errorf("evidence compile: %w", err)
	}
	args, err := compiled.Args(values)
	if err != nil {
		return nil, err
	}
	qctx, cancel := context.WithTimeout(ctx, EvidenceTimeout)
	defer cancel()
	res, err := b.exec.Query(qctx, compiled.SQL, args, req.Limit+1)
	if err != nil {
		if errors.Is(qctx.Err(), context.DeadlineExceeded) {
			return nil, fmt.Errorf("evidence query exceeded %s: %w", EvidenceTimeout, err)
		}
		return nil, fmt.Errorf("evidence query: %w", err)
	}
	out := &EvidenceResponse{Columns: res.Columns, Rows: make([][]any, 0, len(res.Rows)), SourceMode: string(b.mode)}
	for i, row := range res.Rows {
		if i == req.Limit {
			out.HasMore = true
			break
		}
		out.Rows = append(out.Rows, jsonRow(row))
	}
	if res.Truncated {
		out.HasMore = true
	}
	return out, nil
}

func (q *QueryService) modeOf(mappings []intel.Mapping, def *intel.MetricDef) string {
	for _, m := range mappings {
		if m.Entity == def.Requires[0] {
			return string(m.Mode)
		}
	}
	return ""
}

// jsonRow renders timestamps as local wall-clock "YYYY-MM-DDTHH:MM:SS" (sources
// store local time, spec §6.2) and dates as "YYYY-MM-DD".
func jsonRow(row []any) []any {
	out := make([]any, len(row))
	for i, v := range row {
		switch x := v.(type) {
		case time.Time:
			if x.Hour() == 0 && x.Minute() == 0 && x.Second() == 0 && x.Nanosecond() == 0 {
				out[i] = x.Format(dateFmt)
			} else {
				out[i] = x.Format("2006-01-02T15:04:05")
			}
		case []byte:
			out[i] = string(x)
		default:
			out[i] = v
		}
	}
	return out
}

// GetDataStatus returns every data_status row plus metrics disabled by missing data.
func (q *QueryService) GetDataStatus(ctx context.Context, projectID string) (*DataStatusResponse, error) {
	ps, err := q.state(ctx, projectID)
	if err != nil {
		return nil, err
	}
	avail := ps.avail
	statuses, err := q.store.ListDataStatus(ctx, projectID)
	if err != nil {
		return nil, err
	}
	resp := &DataStatusResponse{AsOf: ps.asOf.Format(dateFmt), Items: make([]StatusItem, 0, len(statuses)), DisabledMetrics: []DisabledMetric{}}
	for _, st := range statuses {
		resp.Items = append(resp.Items, toStatusItem(st))
	}
	keys := make([]string, 0, len(avail))
	for k := range avail {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		if !avail[k].Enabled {
			resp.DisabledMetrics = append(resp.DisabledMetrics, DisabledMetric{MetricKey: k, Reason: avail[k].Reason})
		}
	}
	return resp, nil
}

// ListMetrics returns the enabled packs and the metric catalog with availability.
func (q *QueryService) ListMetrics(ctx context.Context, projectID string) (*ListMetricsResponse, error) {
	ps, err := q.state(ctx, projectID)
	if err != nil {
		return nil, err
	}
	cat, avail := ps.cat, ps.avail
	resp := &ListMetricsResponse{AsOf: ps.asOf.Format(dateFmt), Packs: cat.Packs, Metrics: []CatalogMetric{}}
	if resp.Packs == nil {
		resp.Packs = []intel.PackRef{}
	}
	for _, k := range cat.MetricKeys() {
		d := cat.Metrics[k]
		cm := CatalogMetric{Key: k, Unit: d.Unit, Aggregation: string(d.Aggregation), Grain: string(d.Grain),
			Dims: d.Dims, Requires: d.Requires, SampleSize: d.SampleSize, Enabled: avail[k].Enabled}
		if !cm.Enabled {
			r := avail[k].Reason
			cm.DisabledReason = &r
		}
		resp.Metrics = append(resp.Metrics, cm)
	}
	return resp, nil
}
```

- [ ] **Step 4: Chạy — PASS, 0 SKIP**
```bash
cd ennam.kg.go && export KG_TEST_DATABASE_URL="postgres://ennam_kg:${KG_DB_PASSWORD:-ennam_kg_dev}@localhost:5433/ennam_kg?sslmode=disable"
go test -v -count=1 -race ./internal/intel/engine/ 2>&1 | tee /tmp/planb.out | grep -E "^(--- |ok|FAIL)"
grep -c -- '--- SKIP' /tmp/planb.out   # phải in 0 — test DB bị SKIP vẫn báo ok
```
Expected: PASS toàn package (runner, scheduler, query); SKIP = 0.

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.go add internal/intel/engine/query.go internal/intel/engine/query_test.go
git -C ennam.kg.go commit -m "feat(intel): query service for metrics, evidence, data status and catalog" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 12: HTTP endpoints + wiring `kg-server`

**Files:**
- Create `internal/handler/intel_metrics.go`, `internal/handler/intel_metrics_test.go`, `cmd/kg-server/intel_wiring.go`.
- Modify `cmd/kg-server/main.go:1107-1110` (sau block related-documents: build + đăng ký) và `:1321` (`return mux, …` — thêm scheduler vào danh sách stoppable).
- Modify `internal/middleware/project.go:15` (thêm `ReadOnlyPOSTPaths`) và `:166-167` (archive write-protection bỏ qua POST chỉ đọc); Create `internal/middleware/project_readonly_post_test.go`.

**Interfaces:** Produces routes `POST /api/v1/intel/metrics/query` (kg_get_metrics), `POST /api/v1/intel/evidence` (kg_get_evidence), `GET /api/v1/intel/data-status?project_id=` (kg_get_data_status), `GET /api/v1/intel/metrics?project_id=` (kg_list_metrics); `func NewIntelMetricsHandler(q intelQuerier, roleResolver ProjectRoleResolverFunc, logger *slog.Logger) *IntelMetricsHandler`; `func buildIntel(db, dsStore, syncSvc, encKey, roleResolver, logger) (*handler.IntelMetricsHandler, *engine.Scheduler)`. Kiểm tra quyền theo đúng luật của `requireProjectAccess` (`internal/handler/authz.go:35`: scope API key, sau đó `project_members` cho user web, request không xác thực đi qua) nhưng trả 403 theo envelope intel `{error:{code:"forbidden"}}` — **bắt buộc** cho `project_id` trong body vì middleware ProjectID chỉ đọc header/query; 401 từ middleware Auth vẫn là body cũ (ngoại lệ ghi ở Global Constraints); `writeJSON` (`internal/handler/document.go:253`). Lỗi theo envelope `{error:{code,message}}` (không dùng `errorResponse` cũ); 500 không lộ chi tiết.

Env mới của `kg-server`: `PACKS_DIR` (mặc định `/packs`; M1 mount), `METRIC_RUNNER_DAILY_AT`, `METRIC_RUNNER_TIMEZONE`, `METRIC_RUNNER_MAX_ROWS`, `METRIC_RUNNER_CHUNK_DAYS`, `METRIC_STALE_AFTER_DAYS`. Thiếu pack ⇒ 4 route trả 503 `packs_unavailable`, server vẫn chạy.

- [ ] **Step 1: Viết test (failing)**
`internal/handler/intel_metrics_test.go`:
```go
package handler

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ennam/ennam-kg/internal/intel/engine"
	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
)

type fakeIntelQuerier struct {
	gotMetrics  engine.MetricsRequest
	gotEvidence engine.EvidenceRequest
	err         error
}

func (f *fakeIntelQuerier) GetMetrics(_ context.Context, req engine.MetricsRequest) (*engine.MetricsResponse, error) {
	f.gotMetrics = req
	if f.err != nil {
		return nil, f.err
	}
	return &engine.MetricsResponse{Series: []engine.Series{}, DataStatus: []engine.StatusItem{}}, nil
}
func (f *fakeIntelQuerier) GetEvidence(_ context.Context, req engine.EvidenceRequest) (*engine.EvidenceResponse, error) {
	f.gotEvidence = req
	return &engine.EvidenceResponse{Columns: []string{"a"}, Rows: [][]any{{1}}, SourceMode: "live"}, f.err
}
func (f *fakeIntelQuerier) GetDataStatus(context.Context, string) (*engine.DataStatusResponse, error) {
	return &engine.DataStatusResponse{Items: []engine.StatusItem{}, DisabledMetrics: []engine.DisabledMetric{}}, f.err
}
func (f *fakeIntelQuerier) ListMetrics(context.Context, string) (*engine.ListMetricsResponse, error) {
	return &engine.ListMetricsResponse{}, f.err
}

func intelMux(q intelQuerier) *http.ServeMux {
	mux := http.NewServeMux()
	NewIntelMetricsHandler(q, nil, nil).RegisterRoutes(mux)
	return mux
}

func withKey(r *http.Request, projects ...string) *http.Request {
	id := &middleware.DeveloperIdentity{KeyID: "k", Role: models.APIKeyRoleDeveloper, ProjectIDs: projects}
	return r.WithContext(context.WithValue(r.Context(), middleware.DeveloperIdentityKey, id))
}

func decodeIntelError(t *testing.T, rec *httptest.ResponseRecorder) (string, string) {
	t.Helper()
	var body struct {
		Error struct{ Code, Message string } `json:"error"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("body %s: %v", rec.Body.String(), err)
	}
	return body.Error.Code, body.Error.Message
}

func TestIntelMetrics_PassesBodyAndChecksBodyProject(t *testing.T) {
	fq := &fakeIntelQuerier{}
	mux := intelMux(fq)
	body := `{"project_id":"p1","metric_keys":["x.y"],"from":"2026-07-01","to":"2026-08-01","grain":"week","group_by":["location_id"],"dims_filter":{"location_id":["S1"]}}`

	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, withKey(httptest.NewRequest(http.MethodPost, "/api/v1/intel/metrics/query", strings.NewReader(body)), "p1"))
	if rec.Code != http.StatusOK || fq.gotMetrics.Grain != "week" || fq.gotMetrics.DimsFilter["location_id"][0] != "S1" {
		t.Fatalf("code=%d req=%+v body=%s", rec.Code, fq.gotMetrics, rec.Body.String())
	}

	rec = httptest.NewRecorder()
	mux.ServeHTTP(rec, withKey(httptest.NewRequest(http.MethodPost, "/api/v1/intel/metrics/query", strings.NewReader(body)), "other"))
	if code, _ := decodeIntelError(t, rec); rec.Code != http.StatusForbidden || code != "forbidden" {
		t.Fatalf("project in body not owned by key must be 403 {error:{code:forbidden}}, got %d %s", rec.Code, rec.Body.String())
	}
	rec = httptest.NewRecorder()
	mux.ServeHTTP(rec, withKey(httptest.NewRequest(http.MethodGet, "/api/v1/intel/data-status?project_id=p1", nil), "other"))
	if code, _ := decodeIntelError(t, rec); rec.Code != http.StatusForbidden || code != "forbidden" {
		t.Fatalf("GET route must use the same envelope, got %d %s", rec.Code, rec.Body.String())
	}
}

func TestIntelMetrics_ErrorEnvelope(t *testing.T) {
	mux := intelMux(&fakeIntelQuerier{err: &engine.APIError{Code: engine.CodeUnknownMetric, Message: "nope"}})
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/api/v1/intel/metrics/query",
		strings.NewReader(`{"project_id":"p1","metric_keys":["x"],"from":"2026-07-01","to":"2026-07-02"}`)))
	if code, _ := decodeIntelError(t, rec); rec.Code != http.StatusBadRequest || code != "unknown_metric" {
		t.Fatalf("code=%d err=%s", rec.Code, code)
	}

	rec = httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/api/v1/intel/evidence", strings.NewReader(`{bad`)))
	if code, _ := decodeIntelError(t, rec); rec.Code != http.StatusBadRequest || code != "invalid_request" {
		t.Fatalf("bad json: code=%d err=%s", rec.Code, code)
	}

	mux = intelMux(&fakeIntelQuerier{err: errors.New("db down")})
	rec = httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/intel/data-status?project_id=p1", nil))
	if code, msg := decodeIntelError(t, rec); rec.Code != http.StatusInternalServerError || code != "internal" || strings.Contains(msg, "db down") {
		t.Fatalf("internal errors must not leak: code=%d %s %s", rec.Code, code, msg)
	}
}

func TestIntelMetrics_GetRoutesNeedProjectAndPacks(t *testing.T) {
	rec := httptest.NewRecorder()
	intelMux(&fakeIntelQuerier{}).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/intel/metrics", nil))
	if code, _ := decodeIntelError(t, rec); rec.Code != http.StatusBadRequest || code != "invalid_request" {
		t.Fatalf("missing project_id: %d %s", rec.Code, code)
	}
	rec = httptest.NewRecorder()
	intelMux(nil).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/intel/metrics?project_id=p1", nil))
	if code, _ := decodeIntelError(t, rec); rec.Code != http.StatusServiceUnavailable || code != "packs_unavailable" {
		t.Fatalf("nil querier: %d %s", rec.Code, code)
	}
}
```

`internal/middleware/project_readonly_post_test.go`:
```go
package middleware

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/ennam/ennam-kg/internal/models"
)

// Archived projects stay readable: the read-only intel POST routes pass the
// archive write-protection, any other POST is still blocked.
func TestProjectID_ArchivedAllowsReadOnlyPOST(t *testing.T) {
	identity := &DeveloperIdentity{KeyID: "k", Role: models.APIKeyRoleDeveloper,
		ProjectIDs: []string{"proj-1"}, DefaultProjectID: strPtr("proj-1")}
	archived := ProjectStatusCheckerFunc(func(context.Context, string) (bool, error) { return true, nil })
	ok := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusOK) })
	h := injectIdentity(identity, ProjectID(testLogger(), nil, archived)(ok))

	for path, want := range map[string]int{
		"/api/v1/intel/metrics/query": http.StatusOK,
		"/api/v1/intel/evidence":      http.StatusOK,
		"/api/v1/nodes":               http.StatusForbidden,
	} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, path, nil))
		if rec.Code != want {
			t.Errorf("POST %s on archived project = %d, want %d", path, rec.Code, want)
		}
	}
}
```

- [ ] **Step 2: Chạy — FAIL**
```bash
cd ennam.kg.go && go test -count=1 -run 'TestIntelMetrics|TestProjectID_ArchivedAllowsReadOnlyPOST' ./internal/handler/ ./internal/middleware/
```
Expected: FAIL — `undefined: NewIntelMetricsHandler`; middleware: `POST /api/v1/intel/metrics/query on archived project = 403, want 200`.

- [ ] **Step 3: Implement handler + wiring**
`internal/handler/intel_metrics.go`:
```go
package handler

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"

	"github.com/ennam/ennam-kg/internal/intel/engine"
	"github.com/ennam/ennam-kg/internal/middleware"
)

// intelQuerier is the read surface of engine.QueryService (interface for tests).
type intelQuerier interface {
	GetMetrics(ctx context.Context, req engine.MetricsRequest) (*engine.MetricsResponse, error)
	GetEvidence(ctx context.Context, req engine.EvidenceRequest) (*engine.EvidenceResponse, error)
	GetDataStatus(ctx context.Context, projectID string) (*engine.DataStatusResponse, error)
	ListMetrics(ctx context.Context, projectID string) (*engine.ListMetricsResponse, error)
}

// IntelMetricsHandler serves the 4 metrics-provider endpoints behind the MCP tools
// kg_get_metrics, kg_get_evidence, kg_get_data_status and kg_list_metrics
// (spec §6.7, master §2.4). project_id travels in the body (POST) or the query
// string (GET); both are checked here (same rules as requireProjectAccess, intel
// error envelope) because the ProjectID middleware never reads the body.
type IntelMetricsHandler struct {
	q            intelQuerier
	roleResolver ProjectRoleResolverFunc
	logger       *slog.Logger
}

// NewIntelMetricsHandler returns the handler. q == nil (packs not loaded) makes
// every route answer 503.
func NewIntelMetricsHandler(q intelQuerier, roleResolver ProjectRoleResolverFunc, logger *slog.Logger) *IntelMetricsHandler {
	if logger == nil {
		logger = slog.Default()
	}
	return &IntelMetricsHandler{q: q, roleResolver: roleResolver, logger: logger}
}

// RegisterRoutes mounts the 4 routes.
func (h *IntelMetricsHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/v1/intel/metrics/query", h.GetMetrics)
	mux.HandleFunc("POST /api/v1/intel/evidence", h.GetEvidence)
	mux.HandleFunc("GET /api/v1/intel/data-status", h.GetDataStatus)
	mux.HandleFunc("GET /api/v1/intel/metrics", h.ListMetrics)
}

// writeIntelError renders {error:{code,message}} — the shape LAAM's provider
// parses (master §2.4), not the legacy errorResponse shape.
func writeIntelError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]any{"error": map[string]string{"code": code, "message": message}})
}

func (h *IntelMetricsHandler) fail(w http.ResponseWriter, r *http.Request, err error) {
	var ae *engine.APIError
	if errors.As(err, &ae) {
		writeIntelError(w, http.StatusBadRequest, ae.Code, ae.Message)
		return
	}
	h.logger.ErrorContext(r.Context(), "intel metrics request failed", "path", r.URL.Path, "error", err)
	writeIntelError(w, http.StatusInternalServerError, "internal", "metrics request failed")
}

func (h *IntelMetricsHandler) ready(w http.ResponseWriter) bool {
	if h.q == nil {
		writeIntelError(w, http.StatusServiceUnavailable, "packs_unavailable", "industry packs are not loaded (check PACKS_DIR)")
		return false
	}
	return true
}

// access is requireProjectAccess (authz.go) with the intel error envelope: the same
// rules (API-key scope, else project_members for web-login users, unauthenticated
// dev callers pass) but a 403 body LAAM can parse — {error:{code:"forbidden"}}.
func (h *IntelMetricsHandler) access(w http.ResponseWriter, r *http.Request, projectID string) bool {
	if projectID == "" {
		writeIntelError(w, http.StatusBadRequest, engine.CodeInvalidRequest, "project_id is required")
		return false
	}
	identity := middleware.GetDeveloperIdentity(r.Context())
	if identity == nil || identity.HasProjectAccess(projectID) {
		return true
	}
	if user := middleware.GetUserIdentity(r.Context()); user != nil && h.roleResolver != nil {
		if _, ok := h.roleResolver(r.Context(), projectID, user.UserID); ok {
			return true
		}
	}
	writeIntelError(w, http.StatusForbidden, "forbidden", "access denied for project: "+projectID)
	return false
}

// GetMetrics handles POST /api/v1/intel/metrics/query (kg_get_metrics).
func (h *IntelMetricsHandler) GetMetrics(w http.ResponseWriter, r *http.Request) {
	if !h.ready(w) {
		return
	}
	var req engine.MetricsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeIntelError(w, http.StatusBadRequest, engine.CodeInvalidRequest, "invalid JSON body: "+err.Error())
		return
	}
	if !h.access(w, r, req.ProjectID) {
		return
	}
	resp, err := h.q.GetMetrics(r.Context(), req)
	if err != nil {
		h.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

// GetEvidence handles POST /api/v1/intel/evidence (kg_get_evidence).
func (h *IntelMetricsHandler) GetEvidence(w http.ResponseWriter, r *http.Request) {
	if !h.ready(w) {
		return
	}
	var req engine.EvidenceRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeIntelError(w, http.StatusBadRequest, engine.CodeInvalidRequest, "invalid JSON body: "+err.Error())
		return
	}
	if !h.access(w, r, req.ProjectID) {
		return
	}
	resp, err := h.q.GetEvidence(r.Context(), req)
	if err != nil {
		h.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

// GetDataStatus handles GET /api/v1/intel/data-status?project_id= (kg_get_data_status).
func (h *IntelMetricsHandler) GetDataStatus(w http.ResponseWriter, r *http.Request) {
	if !h.ready(w) {
		return
	}
	pid := r.URL.Query().Get("project_id")
	if !h.access(w, r, pid) {
		return
	}
	resp, err := h.q.GetDataStatus(r.Context(), pid)
	if err != nil {
		h.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

// ListMetrics handles GET /api/v1/intel/metrics?project_id= (kg_list_metrics).
func (h *IntelMetricsHandler) ListMetrics(w http.ResponseWriter, r *http.Request) {
	if !h.ready(w) {
		return
	}
	pid := r.URL.Query().Get("project_id")
	if !h.access(w, r, pid) {
		return
	}
	resp, err := h.q.ListMetrics(r.Context(), pid)
	if err != nil {
		h.fail(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}
```

`cmd/kg-server/intel_wiring.go`:
```go
package main

import (
	"database/sql"
	"log/slog"
	"os"

	"github.com/ennam/ennam-kg/internal/handler"
	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/engine"
	"github.com/ennam/ennam-kg/internal/intel/intelstore"
	"github.com/ennam/ennam-kg/internal/intel/livesource"
	"github.com/ennam/ennam-kg/internal/service"
	"github.com/ennam/ennam-kg/internal/store"
)

// buildIntel wires the industry-pack metrics layer (Plan B). The handler is always
// returned (it answers 503 when packs cannot be loaded); the scheduler is nil when
// the layer is disabled. Plan C registers intel.ModeFile in the resolver map and
// hands the scheduler (an intel.RunTrigger) to the tabular-upload path.
func buildIntel(db *sql.DB, dsStore *store.DataSourceStore, syncSvc *service.SchemaSyncService, encKey []byte,
	roleResolver handler.ProjectRoleResolverFunc, logger *slog.Logger) (*handler.IntelMetricsHandler, *engine.Scheduler) {
	packsDir := os.Getenv("PACKS_DIR")
	if packsDir == "" {
		packsDir = "/packs"
	}
	reg, err := intel.LoadRegistry(packsDir)
	if err != nil {
		logger.Warn("industry packs not loaded — metrics endpoints answer 503", "packs_dir", packsDir, "error", err)
		return handler.NewIntelMetricsHandler(nil, roleResolver, logger), nil
	}
	st := intelstore.New(db)
	resolvers := map[intel.SourceMode]intel.SourceResolver{}
	if encKey != nil && dsStore != nil && syncSvc != nil {
		resolvers[intel.ModeLive] = livesource.New(db, dsStore, syncSvc, service.NewSourceExecutor(dsStore, encKey, logger))
	} else {
		logger.Warn("mode=live metrics disabled: KG_ENCRYPTION_KEY not set")
	}
	router := engine.NewSourceRouter(resolvers)
	rcfg, err := engine.RunnerConfigFromEnv()
	if err != nil {
		logger.Error("metrics layer disabled: invalid METRIC_* configuration", "error", err)
		return handler.NewIntelMetricsHandler(nil, roleResolver, logger), nil
	}
	runner := engine.NewRunner(reg, st, router, rcfg, logger)
	query := engine.NewQueryService(reg, st, router, rcfg, logger)
	sched, err := engine.NewScheduler(runner, st, engine.SchedulerConfigFromEnv(), logger)
	if err != nil {
		logger.Error("metric scheduler disabled", "error", err)
		sched = nil
	}
	logger.Info("industry-pack metrics layer enabled", "packs_dir", packsDir, "packs", len(reg.Packs),
		"routes", []string{"POST /api/v1/intel/metrics/query", "POST /api/v1/intel/evidence",
			"GET /api/v1/intel/data-status", "GET /api/v1/intel/metrics"})
	return handler.NewIntelMetricsHandler(query, roleResolver, logger), sched
}
```

Sửa `cmd/kg-server/main.go` (1) — sau block log related-documents:
Thay đoạn (khớp chính xác):
```go
	logger.Info("related-documents endpoints enabled (DAAB)", "routes", []string{
		"GET /api/v1/projects/{projectId}/documents/{document_id}/related",
		"GET /api/v1/projects/{projectId}/documents/{document_id}/shared-entities",
	})
```
bằng:
```go
	logger.Info("related-documents endpoints enabled (DAAB)", "routes", []string{
		"GET /api/v1/projects/{projectId}/documents/{document_id}/related",
		"GET /api/v1/projects/{projectId}/documents/{document_id}/shared-entities",
	})

	// Industry-pack metrics layer (Plan B): kg_get_metrics / kg_get_evidence /
	// kg_get_data_status / kg_list_metrics endpoints + the daily metric runner.
	intelHandler, intelScheduler := buildIntel(db, dsStore, syncSvc, encKey, roleResolver, logger)
	intelHandler.RegisterRoutes(apiMux)
	if intelScheduler != nil {
		intelScheduler.Start(context.Background())
	}
```

Sửa `internal/middleware/project.go` (1) — danh sách POST chỉ đọc:
Thay đoạn (khớp chính xác):
```go
type ProjectStatusCheckerFunc func(ctx context.Context, projectID string) (archived bool, err error)
```
bằng:
```go
type ProjectStatusCheckerFunc func(ctx context.Context, projectID string) (archived bool, err error)

// ReadOnlyPOSTPaths are POST routes that never write (their body is just a query),
// so archive write-protection must not block them: reading an archived project's
// metrics and evidence is allowed like any GET.
var ReadOnlyPOSTPaths = map[string]bool{
	"/api/v1/intel/metrics/query": true,
	"/api/v1/intel/evidence":      true,
}
```

Sửa `internal/middleware/project.go` (2):
Thay đoạn (khớp chính xác):
```go
				// Archive write-protection: block POST/PUT/PATCH/DELETE on archived projects.
				if checker != nil {
```
bằng:
```go
				// Archive write-protection: block POST/PUT/PATCH/DELETE on archived projects.
				// POST routes that only read (ReadOnlyPOSTPaths) stay open.
				if checker != nil && !(r.Method == http.MethodPost && ReadOnlyPOSTPaths[r.URL.Path]) {
```

Sửa `cmd/kg-server/main.go` (2) — cuối `buildRouter`:
Thay đoạn (khớp chính xác):
```go
	return mux, []stoppable{retentionWorker, recalledWriter, chunkLinkWorker}
```
bằng:
```go
	workers := []stoppable{retentionWorker, recalledWriter, chunkLinkWorker}
	if intelScheduler != nil {
		workers = append(workers, intelScheduler)
	}
	return mux, workers
```

- [ ] **Step 4: Chạy — PASS + build**
```bash
cd ennam.kg.go && go test -count=1 -run 'TestIntelMetrics|TestProjectID' -v ./internal/handler/ ./internal/middleware/ && go build ./cmd/... && go vet ./cmd/kg-server/ ./internal/handler/ ./internal/middleware/
```
Expected: 3 test `TestIntelMetrics*`, `TestProjectID_ArchivedAllowsReadOnlyPOST` và các `TestProjectID_*` cũ PASS; build/vet không lỗi.

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.go add internal/handler/intel_metrics.go internal/handler/intel_metrics_test.go cmd/kg-server/intel_wiring.go cmd/kg-server/main.go internal/middleware/project.go internal/middleware/project_readonly_post_test.go
git -C ennam.kg.go commit -m "feat(intel): metrics provider HTTP endpoints and runner wiring" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 13: Bridge — thêm 4 tool, gỡ 2 tool chết, cập nhật mọi assert

**Files:**
- Modify `internal/bridge/client.go:285-289` (xoá `kg_get_context`), `:297-302` (xoá `kg_get_impact_analysis`), `:451-456` (thêm 4 route sau `kg_execute_playbook`).
- Modify `internal/bridge/schema.go:106` (helper `dateParam`), `:120` (param `projectIDOptionalParam`), `:1436-1459` (xoá schema `kg_get_context`), `:1476-1501` (xoá schema `kg_get_impact_analysis`), `:1976` (thêm 4 schema trước `return schemas`).
- Modify `config/config.yaml:1329` (comment) và `LAAM/scripts/eval/scale/mcp-pool.json` (snapshot eval: bỏ 2 tool đã gỡ).
- Modify tests: `internal/bridge/client_test.go:166-177, 213-217, 232-233, 1061-1072`; `internal/bridge/schema_test.go:8, 33-34, 65-72, 99-100, 135-136, 301-310, 580-588, 780-801, 854-871, 1036-1037, 1119-1125` (file có BOM — giữ nguyên byte đầu); `internal/bridge/handler_test.go:276-277`; `internal/bridge/e2e_tools_test.go:317-348, 746`; `internal/bridge/integration_test.go:716-800, 892, 918-920, 997-1013`; `internal/config/types.go:491-492` (comment).

**Interfaces:** Produces tool `kg_get_metrics` → `POST /api/v1/intel/metrics/query`; `kg_get_evidence` → `POST /api/v1/intel/evidence`; `kg_get_data_status` → `GET /api/v1/intel/data-status` (QueryParams `project_id`); `kg_list_metrics` → `GET /api/v1/intel/metrics` (QueryParams `project_id`); cả 4 `RouteRead`. `project_id` nằm ở body/query (không phải path `{projectId}`) để `defaultProjectKey` (`serve.go:461`) ghim đúng khoá `project_id` theo hợp đồng §2.4. Tổng: **54 route (29 read, 25 write), 57 schema** (54 + 3 local). `kg_get_context`/`kg_get_impact_analysis` bị gỡ vì server không có handler (`POST /api/v1/context`, `/nodes/{id}/impact` 404 — spec I8). Test dùng hai tool đó làm ví dụ cho validator chung được chuyển sang `kg_get_neighbors` (`node_types` array-enum) và `kg_get_metrics` (`grain` enum, pattern ngày) — không mất độ phủ.

- [ ] **Step 1: Sửa test trước (failing)**

**`internal/bridge/client_test.go`**

Thay đoạn (khớp chính xác):
```go
		{
			name:       "kg_get_context",
			toolName:   "kg_get_context",
			wantMethod: "POST",
			wantPath:   "/api/v1/context",
		},
		{
			name:       "kg_get_impact_analysis",
			toolName:   "kg_get_impact_analysis",
			wantMethod: "POST",
			wantPath:   "/api/v1/nodes/{id}/impact",
		},
```
bằng:
```go
		{
			name:       "kg_get_metrics",
			toolName:   "kg_get_metrics",
			wantMethod: "POST",
			wantPath:   "/api/v1/intel/metrics/query",
		},
		{
			name:       "kg_list_metrics",
			toolName:   "kg_list_metrics",
			wantMethod: "GET",
			wantPath:   "/api/v1/intel/metrics",
		},
		{
			name:     "removed dead tool kg_get_context",
			toolName: "kg_get_context",
			wantErr:  true,
		},
		{
			name:     "removed dead tool kg_get_impact_analysis",
			toolName: "kg_get_impact_analysis",
			wantErr:  true,
		},
```

Thay đoạn (khớp chính xác):
```go
// TestListToolNames verifies all 50 HTTP-routed tools are registered.
func TestListToolNames(t *testing.T) {
	names := ListToolNames()
	if len(names) != 52 {
		t.Errorf("got %d tools, want 52", len(names))
	}
```
bằng:
```go
// TestListToolNames verifies all 54 HTTP-routed tools are registered.
func TestListToolNames(t *testing.T) {
	names := ListToolNames()
	if len(names) != 54 {
		t.Errorf("got %d tools, want 54", len(names))
	}
```

Thay đoạn (khớp chính xác):
```go
		"kg_get_context":         true,
		"kg_get_impact_analysis": true,
		"kg_get_history":         true,
```
bằng:
```go
		"kg_get_history":         true,
		"kg_get_metrics":         true,
		"kg_get_evidence":        true,
		"kg_get_data_status":     true,
		"kg_list_metrics":        true,
```

Thay đoạn (khớp chính xác):
```go
	want := map[RouteClass]int{
		RouteRead:  27,
		RouteWrite: 25,
	}
```
bằng:
```go
	// Plan B: + intel metrics provider (+4 read), − dead kg_get_context /
	// kg_get_impact_analysis (−2 read): 29 read, 25 write.
	want := map[RouteClass]int{
		RouteRead:  29,
		RouteWrite: 25,
	}
```

Thay đoạn (khớp chính xác):
```go
	// Total routed = 52
	total := counts[RouteRead] + counts[RouteWrite]
	if total != 52 {
		t.Errorf("total routed routes: got %d, want 52", total)
	}
```
bằng:
```go
	// Total routed = 54
	total := counts[RouteRead] + counts[RouteWrite]
	if total != 54 {
		t.Errorf("total routed routes: got %d, want 54", total)
	}
```

**`internal/bridge/handler_test.go`**

Thay đoạn (khớp chính xác):
```go
	if len(tools) != 55 {
		t.Errorf("expected 55 tools, got %d", len(tools))
	}
```
bằng:
```go
	if len(tools) != 57 {
		t.Errorf("expected 57 tools, got %d", len(tools))
	}
```

**`internal/bridge/schema_test.go`**

Thay đoạn (khớp chính xác):
```go
// TestAllToolSchemasRegistered verifies that all 55 MCP tools (52 HTTP-proxy + 3 local-exec) have schemas.
```
bằng:
```go
// TestAllToolSchemasRegistered verifies that all 57 MCP tools (54 HTTP-proxy + 3 local-exec) have schemas.
```

Thay đoạn (khớp chính xác):
```go
		"kg_get_context",
		"kg_get_impact_analysis",
		"kg_get_history",
```
bằng:
```go
		"kg_get_history",
		"kg_get_metrics",
		"kg_get_evidence",
		"kg_get_data_status",
		"kg_list_metrics",
```

Thay đoạn (khớp chính xác):
```go
	schemas := ListToolSchemas()
	if len(schemas) != 55 {
		t.Errorf("expected 55 tool schemas, got %d", len(schemas))
	}

	for _, name := range expectedTools {
		if schemas[name] == nil {
			t.Errorf("missing schema for tool %q", name)
		}
	}
```
bằng:
```go
	schemas := ListToolSchemas()
	if len(schemas) != 57 {
		t.Errorf("expected 57 tool schemas, got %d", len(schemas))
	}

	for _, name := range expectedTools {
		if schemas[name] == nil {
			t.Errorf("missing schema for tool %q", name)
		}
	}
	for _, dead := range []string{"kg_get_context", "kg_get_impact_analysis"} {
		if schemas[dead] != nil {
			t.Errorf("dead tool %q (route never existed on the server) must stay removed", dead)
		}
	}
```

(xuất hiện 2 lần — thay tất cả)
Thay đoạn (khớp chính xác):
```go
	if len(schemas) != 55 {
		t.Errorf("expected 55 tool schemas (unchanged), got %d", len(schemas))
	}
```
bằng:
```go
	if len(schemas) != 57 {
		t.Errorf("expected 57 tool schemas (unchanged), got %d", len(schemas))
	}
```

Thay đoạn (khớp chính xác):
```go
			name: "array field receives string",
			tool: "kg_get_impact_analysis",
			params: map[string]interface{}{
				"id":            "550e8400-e29b-41d4-a716-446655440000",
				"project_id":    "550e8400-e29b-41d4-a716-446655440001",
				"include_types": "decision",
			},
			errorField:   "include_types",
```
bằng:
```go
			name: "array field receives string",
			tool: "kg_get_neighbors",
			params: map[string]interface{}{
				"id":         "550e8400-e29b-41d4-a716-446655440000",
				"project_id": "550e8400-e29b-41d4-a716-446655440001",
				"node_types": "decision",
			},
			errorField:   "node_types",
```

Thay đoạn (khớp chính xác):
```go
// TestValidateToolParams_ValidGetContext tests kg_get_context.
func TestValidateToolParams_ValidGetContext(t *testing.T) {
	result := ValidateToolParams("kg_get_context", map[string]interface{}{
		"project_id":   "550e8400-e29b-41d4-a716-446655440001",
		"scope":        "task",
		"filter_value": "TASK-042",
	})
```
bằng:
```go
// TestValidateToolParams_ValidGetMetrics tests kg_get_metrics.
func TestValidateToolParams_ValidGetMetrics(t *testing.T) {
	result := ValidateToolParams("kg_get_metrics", map[string]interface{}{
		"project_id":  "550e8400-e29b-41d4-a716-446655440001",
		"metric_keys": []interface{}{"retail.net_sales"},
		"from":        "2026-07-01",
		"to":          "2026-08-01",
		"grain":       "week",
		"dims_filter": map[string]interface{}{"location_id": []interface{}{"PH-002"}},
	})
```

Thay đoạn (khớp chính xác):
```go
// TestValidateToolParams_ScopeEnum tests scope enum validation in kg_get_context.
func TestValidateToolParams_ScopeEnum(t *testing.T) {
	t.Run("valid scope", func(t *testing.T) {
		result := ValidateToolParams("kg_get_context", map[string]interface{}{
			"project_id": "550e8400-e29b-41d4-a716-446655440001",
			"scope":      "full",
		})
		if !result.Valid {
			t.Errorf("expected validation to pass, errors: %v", result.Errors)
		}
	})

	t.Run("invalid scope", func(t *testing.T) {
		result := ValidateToolParams("kg_get_context", map[string]interface{}{
			"project_id": "550e8400-e29b-41d4-a716-446655440001",
			"scope":      "invalid_scope",
		})
		if result.Valid {
			t.Error("expected validation to fail for invalid scope")
		}
	})
```
bằng:
```go
// TestValidateToolParams_GrainEnum tests string enum validation (kg_get_metrics grain)
// and the YYYY-MM-DD pattern on from/to.
func TestValidateToolParams_GrainEnum(t *testing.T) {
	t.Run("valid grain", func(t *testing.T) {
		result := ValidateToolParams("kg_get_metrics", map[string]interface{}{
			"metric_keys": []interface{}{"retail.net_sales"},
			"from":        "2026-07-01",
			"to":          "2026-08-01",
			"grain":       "total",
		})
		if !result.Valid {
			t.Errorf("expected validation to pass, errors: %v", result.Errors)
		}
	})

	t.Run("invalid grain and date", func(t *testing.T) {
		result := ValidateToolParams("kg_get_metrics", map[string]interface{}{
			"metric_keys": []interface{}{"retail.net_sales"},
			"from":        "07/01/2026",
			"to":          "2026-08-01",
			"grain":       "hour",
		})
		if result.Valid || len(result.Errors) != 2 {
			t.Errorf("expected 2 errors (grain enum + from pattern), got %v", result.Errors)
		}
	})
```

Thay đoạn (khớp chính xác):
```go
	result := ValidateToolParams("kg_get_impact_analysis", map[string]interface{}{
		"id":         "550e8400-e29b-41d4-a716-446655440000",
		"project_id": "550e8400-e29b-41d4-a716-446655440001",
		"include_types": []interface{}{
			"decision",
			"invalid_type",
			"task",
		},
	})
```
bằng:
```go
	result := ValidateToolParams("kg_get_neighbors", map[string]interface{}{
		"id":         "550e8400-e29b-41d4-a716-446655440000",
		"project_id": "550e8400-e29b-41d4-a716-446655440001",
		"node_types": []interface{}{
			"decision",
			"invalid_type",
			"task",
		},
	})
```

Thay đoạn (khớp chính xác):
```go
		if strings.Contains(err.Field, "include_types[1]") && strings.Contains(err.Message, "must be one of") {
```
bằng:
```go
		if strings.Contains(err.Field, "node_types[1]") && strings.Contains(err.Message, "must be one of") {
```

Thay đoạn (khớp chính xác):
```go
		"kg_get_context":         {"project_id": "string", "scope": "string"},
		"kg_get_impact_analysis": {"id": "string", "project_id": "string"},
```
bằng:
```go
		"kg_get_metrics":         {"metric_keys": "array", "from": "string"},
		"kg_get_evidence":        {"metric_key": "string", "from": "string", "to": "string"},
```

Thay đoạn (khớp chính xác):
```go
		{
			tool: "kg_get_context",
			params: map[string]interface{}{
				"project_id": "550e8400-e29b-41d4-a716-446655440001",
				"scope":      "full",
			},
		},
```
bằng:
```go
		{
			tool: "kg_get_metrics",
			params: map[string]interface{}{
				"metric_keys": []interface{}{"retail.net_sales"},
				"from":        "2026-07-01",
				"to":          "2026-08-01",
			},
		},
```

**`internal/bridge/e2e_tools_test.go`**

Thay đoạn (khớp chính xác):
```go
		{
			toolName: "kg_get_context",
			params: map[string]interface{}{
				"project_id": "proj-1",
				"scope":      "new_feature",
				"node_types": []interface{}{"decision", "requirement", "architecture"},
			},
			wantMethod:   "POST",
			wantPath:     "/api/v1/context",
			wantBodyKeys: []string{"project_id", "scope", "node_types"},
			respStatus:   http.StatusOK,
			respBody: map[string]interface{}{
				"project_id": "proj-1",
				"context":    map[string]interface{}{"decisions": float64(5)},
			},
		},
		{
			toolName: "kg_get_impact_analysis",
			params: map[string]interface{}{
				"id":         "node-dec-1",
				"project_id": "proj-1",
				"max_depth":  float64(3),
			},
			wantMethod:   "POST",
			wantPath:     "/api/v1/nodes/node-dec-1/impact",
			wantBodyKeys: []string{"project_id", "max_depth"},
			excludeBody:  []string{"id"},
			respStatus:   http.StatusOK,
			respBody: map[string]interface{}{
				"node_id":        "node-dec-1",
				"affected_nodes": []interface{}{"node-req-1"},
			},
		},
```
bằng:
```go
		{
			toolName: "kg_get_metrics",
			params: map[string]interface{}{
				"project_id":  "proj-1",
				"metric_keys": []interface{}{"retail.net_sales"},
				"from":        "2026-07-01",
				"to":          "2026-08-01",
				"grain":       "week",
			},
			wantMethod:   "POST",
			wantPath:     "/api/v1/intel/metrics/query",
			wantBodyKeys: []string{"project_id", "metric_keys", "from", "to", "grain"},
			respStatus:   http.StatusOK,
			respBody: map[string]interface{}{
				"series":      []interface{}{},
				"data_status": []interface{}{},
			},
		},
		{
			toolName: "kg_list_metrics",
			params: map[string]interface{}{
				"project_id": "proj-1",
			},
			wantMethod:     "GET",
			wantPath:       "/api/v1/intel/metrics",
			wantQueryParts: []string{"project_id=proj-1"},
			respStatus:     http.StatusOK,
			respBody: map[string]interface{}{
				"packs":   []interface{}{},
				"metrics": []interface{}{},
			},
		},
```

Thay đoạn (khớp chính xác):
```go
			"kg_get_context": false, "kg_get_impact_analysis": false,
			"kg_get_history": false,
```
bằng:
```go
			"kg_get_history": false,
			"kg_get_metrics": false, "kg_get_evidence": false,
			"kg_get_data_status": false, "kg_list_metrics": false,
```

**`internal/bridge/integration_test.go`**

Thay đoạn (khớp chính xác):
```go
// TestIntegration_GetContext verifies kg_get_context forwards to POST /api/v1/context.
func TestIntegration_GetContext(t *testing.T) {
	expectedResp := map[string]interface{}{
		"project_id": "proj-1",
		"context": map[string]interface{}{
			"decisions":    float64(5),
			"requirements": float64(3),
		},
	}
```
bằng:
```go
// TestIntegration_GetMetrics verifies kg_get_metrics forwards to
// POST /api/v1/intel/metrics/query with project_id kept in the body.
func TestIntegration_GetMetrics(t *testing.T) {
	expectedResp := map[string]interface{}{
		"series":      []interface{}{},
		"data_status": []interface{}{},
	}
```

Thay đoạn (khớp chính xác):
```go
	resp, err := client.CallTool(context.Background(), ToolRequest{
		ToolName: "kg_get_context",
		Params: map[string]interface{}{
			"project_id": "proj-1",
			"scope":      "new_feature",
			"node_types": []interface{}{"decision", "requirement"},
		},
	})

	if err != nil {
		t.Fatalf("CallTool error: %v", err)
	}

	if captured.Method != "POST" {
		t.Errorf("method = %q, want POST", captured.Method)
	}
	if captured.Path != "/api/v1/context" {
		t.Errorf("path = %q, want /api/v1/context", captured.Path)
	}
	if captured.Body["scope"] != "new_feature" {
		t.Errorf("body scope = %v, want new_feature", captured.Body["scope"])
	}
	if resp.StatusCode != http.StatusOK {
		t.Errorf("status = %d, want 200", resp.StatusCode)
	}
}
```
bằng:
```go
	resp, err := client.CallTool(context.Background(), ToolRequest{
		ToolName: "kg_get_metrics",
		Params: map[string]interface{}{
			"project_id":  "proj-1",
			"metric_keys": []interface{}{"retail.net_sales"},
			"from":        "2026-07-01",
			"to":          "2026-08-01",
			"dims_filter": map[string]interface{}{"location_id": []interface{}{"PH-002"}},
		},
	})

	if err != nil {
		t.Fatalf("CallTool error: %v", err)
	}

	if captured.Method != "POST" {
		t.Errorf("method = %q, want POST", captured.Method)
	}
	if captured.Path != "/api/v1/intel/metrics/query" {
		t.Errorf("path = %q, want /api/v1/intel/metrics/query", captured.Path)
	}
	if captured.Body["project_id"] != "proj-1" || captured.Body["dims_filter"] == nil {
		t.Errorf("body = %v, want project_id and dims_filter forwarded", captured.Body)
	}
	if resp.StatusCode != http.StatusOK {
		t.Errorf("status = %d, want 200", resp.StatusCode)
	}
}
```

Thay đoạn (khớp chính xác):
```go
// TestIntegration_GetImpactAnalysis verifies kg_get_impact_analysis forwards to
// POST /api/v1/nodes/{id}/impact with path parameter substitution.
func TestIntegration_GetImpactAnalysis(t *testing.T) {
	expectedResp := map[string]interface{}{
		"node_id": "node-123",
		"impact": map[string]interface{}{
			"direct":   float64(3),
			"indirect": float64(7),
		},
		"affected_nodes": []interface{}{"node-2", "node-3", "node-4"},
	}
```
bằng:
```go
// TestIntegration_GetDataStatus verifies kg_get_data_status forwards to
// GET /api/v1/intel/data-status?project_id=….
func TestIntegration_GetDataStatus(t *testing.T) {
	expectedResp := map[string]interface{}{
		"items":            []interface{}{},
		"disabled_metrics": []interface{}{},
	}
```

Thay đoạn (khớp chính xác):
```go
	resp, err := client.CallTool(context.Background(), ToolRequest{
		ToolName: "kg_get_impact_analysis",
		Params: map[string]interface{}{
			"id":         "node-123",
			"project_id": "proj-1",
			"max_depth":  float64(2),
		},
	})

	if err != nil {
		t.Fatalf("CallTool error: %v", err)
	}

	if captured.Method != "POST" {
		t.Errorf("method = %q, want POST", captured.Method)
	}
	if captured.Path != "/api/v1/nodes/node-123/impact" {
		t.Errorf("path = %q, want /api/v1/nodes/node-123/impact", captured.Path)
	}
	if _, ok := captured.Body["id"]; ok {
		t.Error("id should be removed from body (moved to path)")
	}
	if resp.StatusCode != http.StatusOK {
		t.Errorf("status = %d, want 200", resp.StatusCode)
	}
	if resp.Body["node_id"] != "node-123" {
		t.Errorf("resp node_id = %v, want node-123", resp.Body["node_id"])
	}
```
bằng:
```go
	resp, err := client.CallTool(context.Background(), ToolRequest{
		ToolName: "kg_get_data_status",
		Params: map[string]interface{}{
			"project_id": "proj-1",
		},
	})

	if err != nil {
		t.Fatalf("CallTool error: %v", err)
	}

	if captured.Method != "GET" {
		t.Errorf("method = %q, want GET", captured.Method)
	}
	if captured.Path != "/api/v1/intel/data-status" || captured.Query != "project_id=proj-1" {
		t.Errorf("path = %q query = %q, want /api/v1/intel/data-status?project_id=proj-1", captured.Path, captured.Query)
	}
	if resp.StatusCode != http.StatusOK {
		t.Errorf("status = %d, want 200", resp.StatusCode)
	}
```

Thay đoạn (khớp chính xác):
```go
//   - kg_get_context, kg_get_impact_analysis, kg_get_history
```
bằng:
```go
//   - kg_get_history
```

Thay đoạn (khớp chính xác):
```go
		"kg_get_context",
		"kg_get_master_record",
		"kg_get_impact_analysis",
		"kg_get_history",
```
bằng:
```go
		"kg_get_master_record",
		"kg_get_history",
```

Thay đoạn (khớp chính xác):
```go
	allExpected = append(allExpected, sourceWriteTools...)
```
bằng:
```go
	allExpected = append(allExpected, sourceWriteTools...)
	allExpected = append(allExpected, intelMetricsTools...)
```

Thay đoạn (khớp chính xác):
```go
	allExpected := append(coreTools, typeSpecificUpdateTools...)
```
bằng:
```go
	// Plan B — industry-pack metrics provider (spec §6.7).
	intelMetricsTools := []string{
		"kg_get_metrics",
		"kg_get_evidence",
		"kg_get_data_status",
		"kg_list_metrics",
	}

	allExpected := append(coreTools, typeSpecificUpdateTools...)
```

- [ ] **Step 2: Chạy — FAIL**
```bash
cd ennam.kg.go && go test -count=1 ./internal/bridge/
```
Expected: FAIL — vd `got 52 tools, want 54`, `missing schema for tool "kg_get_metrics"`, `route class "read": got 27 routes, want 29`.

- [ ] **Step 3: Implement**

`internal/bridge/client.go` — xoá 2 route chết:
Thay đoạn (khớp chính xác):
```go
	"kg_get_context": {
		Method:       http.MethodPost,
		PathTemplate: apiPrefix + "/context",
		Class:        RouteRead,
	},
```
bằng: (xoá — để trống)
```go

```

Thay đoạn (khớp chính xác):
```go
	"kg_get_impact_analysis": {
		Method:       http.MethodPost,
		PathTemplate: apiPrefix + "/nodes/{id}/impact",
		PathParams:   []string{"id"},
		Class:        RouteRead,
	},
```
bằng: (xoá — để trống)
```go

```

`internal/bridge/client.go` — thêm 4 route:
Thay đoạn (khớp chính xác):
```go
	"kg_execute_playbook": {
		Method:       http.MethodPost,
		PathTemplate: apiPrefix + "/data-sources/{data_source_id}/playbooks/{name}/execute",
		PathParams:   []string{"data_source_id", "name"},
		Class:        RouteWrite,
	},
```
bằng:
```go
	"kg_execute_playbook": {
		Method:       http.MethodPost,
		PathTemplate: apiPrefix + "/data-sources/{data_source_id}/playbooks/{name}/execute",
		PathParams:   []string{"data_source_id", "name"},
		Class:        RouteWrite,
	},

	// === Industry-pack metrics provider (spec §6.7, master §2.4) — READ ===
	// project_id travels in the body/query (not the path) so the bridge pins the
	// configured default project into "project_id" (defaultProjectKey).
	"kg_get_metrics": {
		Method:       http.MethodPost,
		PathTemplate: apiPrefix + "/intel/metrics/query",
		Class:        RouteRead,
	},
	"kg_get_evidence": {
		Method:       http.MethodPost,
		PathTemplate: apiPrefix + "/intel/evidence",
		Class:        RouteRead,
	},
	"kg_get_data_status": {
		Method:       http.MethodGet,
		PathTemplate: apiPrefix + "/intel/data-status",
		QueryParams:  []string{"project_id"},
		Class:        RouteRead,
	},
	"kg_list_metrics": {
		Method:       http.MethodGet,
		PathTemplate: apiPrefix + "/intel/metrics",
		QueryParams:  []string{"project_id"},
		Class:        RouteRead,
	},
```

`internal/bridge/schema.go` — xoá schema `kg_get_context` (toàn bộ block):
Thay đoạn (khớp chính xác):
```go
	// === kg_get_context ===
	schemas["kg_get_context"] = &ToolSchema{
		ToolName:    "kg_get_context",
		Description: "Get knowledge context for a given scope",
		Properties: map[string]ParamSchema{
			"project_id": projectIDParam,
			"scope": {
				Type:        TypeString,
				Required:    true,
				Description: "Scope level to retrieve context for",
				Enum:        []string{"full", "phase", "task", "domain", "recent"},
			},
			"filter_value": {
				Type:        TypeString,
				Required:    false,
				Description: "Value to filter by (e.g., task_id for task scope, domain name for domain scope)",
			},
			"limit": {
				Type:     TypeInteger,
				Required: false,
				MinValue: intPtr(1),
				MaxValue: intPtr(200),
			},
		},
	}
```
bằng: (xoá — để trống)
```go

```

`internal/bridge/schema.go` — xoá schema `kg_get_impact_analysis`:
Thay đoạn (khớp chính xác):
```go
	// === kg_get_impact_analysis ===
	schemas["kg_get_impact_analysis"] = &ToolSchema{
		ToolName:    "kg_get_impact_analysis",
		Description: "Analyze the impact of a node by traversing its relationships",
		Properties: map[string]ParamSchema{
			"id":         nodeIDParam,
			"project_id": projectIDParam,
			"max_depth": {
				Type:     TypeInteger,
				Required: false,
				MinValue: intPtr(1),
				MaxValue: intPtr(3),
			},
			"include_types": {
				Type:        TypeArray,
				Required:    false,
				Description: "Node types to include in impact analysis",
				Items: &ParamSchema{
					Type: TypeString,
					Enum: []string{
						"decision", "concept", "requirement", "task", "architecture", "discovery",
					},
				},
			},
		},
	}
```
bằng: (xoá — để trống)
```go

```

`internal/bridge/schema.go` — helper:
Thay đoạn (khớp chính xác):
```go
// helper to create int pointers
func intPtr(v int) *int { return &v }
```
bằng:
```go
// helper to create int pointers
func intPtr(v int) *int { return &v }

// dateParam is a required YYYY-MM-DD string parameter.
func dateParam(desc string) ParamSchema {
	return ParamSchema{Type: TypeString, Required: true, Description: desc, Pattern: `^[0-9]{4}-[0-9]{2}-[0-9]{2}$`}
}
```

Thay đoạn (khớp chính xác):
```go
	sessionIDParam = ParamSchema{
```
bằng:
```go
	// projectIDOptionalParam: the bridge pins its configured default project into
	// "project_id" when one is set (serve.go defaultProjectKey).
	projectIDOptionalParam = ParamSchema{
		Type:        TypeString,
		Required:    false,
		Description: "Project id (the bridge fills in its configured default project)",
	}
	sessionIDParam = ParamSchema{
```

`internal/bridge/schema.go` — thêm 4 schema ngay trước `return schemas` cuối `buildToolSchemas` (mô tả hành động, không mô tả ngành — D11):
Thay đoạn (khớp chính xác):
```go
	return schemas
}
```
bằng:
```go
	// === Industry-pack metrics provider (spec §6.7, master §2.4) ===
	// Descriptions name the ACTION, never an industry (spec D11): adding an
	// industry adds pack content, not tools.
	schemas["kg_list_metrics"] = &ToolSchema{
		ToolName: "kg_list_metrics",
		Description: "List the industry packs enabled for the project and the catalog of precomputed metrics " +
			"(key, unit, aggregation additive|ratio|snapshot, grain, dims, required entities, what sample_size counts, " +
			"enabled + disabled_reason). Call this first to learn which metric keys and dims exist.",
		Properties: map[string]ParamSchema{
			"project_id": projectIDOptionalParam,
		},
	}
	schemas["kg_get_metrics"] = &ToolSchema{
		ToolName: "kg_get_metrics",
		Description: "Read precomputed metric time series for metric_keys over [from, to) (to is exclusive, dates YYYY-MM-DD). " +
			"Numbers come from fixed, versioned SQL computed by DAAB — use this, not kg_query_datasource, for any metric in kg_list_metrics. " +
			"grain day|week|month|total rolls periods up per the metric's aggregation (additive = sum, ratio = SUM(numerator)/SUM(denominator), " +
			"snapshot = value on the last day). group_by keeps only the listed dims; dims_filter restricts dims, e.g. {\"location_id\":[\"S1\"]}. " +
			"Returns series[].points[], data_status and as_of (the last data day, inclusive) — never present data whose status is not current as current.",
		Properties: map[string]ParamSchema{
			"project_id": projectIDOptionalParam,
			"metric_keys": {Type: TypeArray, Required: true, Description: "Metric keys from kg_list_metrics (1-50)",
				Items: &ParamSchema{Type: TypeString, MinLength: intPtr(1)}},
			"from": dateParam("First day included (YYYY-MM-DD)"),
			"to": {Type: TypeString, Required: false, Pattern: `^[0-9]{4}-[0-9]{2}-[0-9]{2}$`,
				Description: "First day NOT included (YYYY-MM-DD); default = the project's as_of + 1 day (as_of = last data day)"},
			"grain":    {Type: TypeString, Required: false, Description: "Roll-up period (default day)", Enum: []string{"day", "week", "month", "total"}},
			"group_by": {Type: TypeArray, Required: false, Description: "Dims to keep (default: all dims of the metric)", Items: &ParamSchema{Type: TypeString}},
			"dims_filter": {Type: TypeObject, Required: false,
				Description: "Map dim -> allowed values, applied in SQL; dims the metric does not have are ignored"},
		},
	}
	schemas["kg_get_evidence"] = &ToolSchema{
		ToolName: "kg_get_evidence",
		Description: "List the source rows behind one metric value: runs the metric's evidence query for [from, to) and the given dims " +
			"(any subset of the metric's dims; an omitted dim is not filtered) where the data lives, and returns columns, rows (each with _source_ref = '<table>:<key>'), " +
			"has_more and source_mode. Rows are shown, not stored. Page with limit (1-200, default 50) and offset.",
		Properties: map[string]ParamSchema{
			"project_id":  projectIDOptionalParam,
			"metric_key":  {Type: TypeString, Required: true, MinLength: intPtr(1), Description: "Metric key from kg_list_metrics"},
			"from":        dateParam("First day included (YYYY-MM-DD)"),
			"to":          dateParam("First day NOT included (YYYY-MM-DD)"),
			"dims":        {Type: TypeObject, Required: false, Description: "Values for any subset of the metric's dims, e.g. {\"location_id\":\"S1\"}; an omitted dim is not filtered (a dim restricted by dims_filter must be given)"},
			"dims_filter": {Type: TypeObject, Required: false, Description: "Map dim -> allowed values; dims outside it return no rows"},
			"limit":       {Type: TypeInteger, Required: false, MinValue: intPtr(1), MaxValue: intPtr(200), Description: "Rows per page (default 50)"},
			"offset":      {Type: TypeInteger, Required: false, MinValue: intPtr(0), Description: "Rows to skip"},
		},
	}
	schemas["kg_get_data_status"] = &ToolSchema{
		ToolName: "kg_get_data_status",
		Description: "Report data freshness and completeness per entity and metric (current|delayed|incomplete|stale|blocked, " +
			"last_success_at, covered period, issues) and the metrics disabled because data or mapping is missing.",
		Properties: map[string]ParamSchema{
			"project_id": projectIDOptionalParam,
		},
	}

	return schemas
}
```

`internal/config/types.go`:
Thay đoạn (khớp chính xác):
```go
// ScopeDefinition defines what knowledge is returned for a given scope level.
// Used by kg_get_context to determine query boundaries.
```
bằng:
```go
// ScopeDefinition defines what knowledge is returned for a given scope level.
// (Its only consumer, the kg_get_context MCP tool, was removed in Plan B: the
// route it called never existed on the server.)
```

`config/config.yaml:1329` (comment):
Thay đoạn (khớp chính xác):
```yaml
# Used by kg_get_context(scope) to determine query boundaries.
```
bằng:
```yaml
# (Their only consumer, the kg_get_context MCP tool, was removed in Plan B: the route never existed.)
```

`LAAM/scripts/eval/scale/mcp-pool.json` (snapshot tool MCP cho eval, dòng ~176 và ~309): xoá 2 entry tool đã gỡ (hoặc chụp lại bằng `npx tsx --env-file=.env scripts/eval/scale/snapshot-mcp-pool.ts <userId>` sau khi deploy bridge mới):
```bash
python3 - <<'EOF'
import json
p = "LAAM/scripts/eval/scale/mcp-pool.json"
pool = json.load(open(p))
dead = {"mcp__daab__kg_get_context", "mcp__daab__kg_get_impact_analysis"}
kept = [t for t in pool if t.get("function", {}).get("name") not in dead]
assert len(pool) - len(kept) == 2, len(pool) - len(kept)
with open(p, "w") as f:
    json.dump(kept, f, ensure_ascii=False, indent=2)
    f.write("\n")
EOF
git -C LAAM add scripts/eval/scale/mcp-pool.json && git -C LAAM commit -m "chore(eval): drop DAAB tools removed from the bridge" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Chạy — PASS (cả package bridge + config)**
```bash
cd ennam.kg.go && go test -count=1 ./internal/bridge/ ./internal/config/
```
Expected: `ok` cả hai; kiểm tra thêm `grep -rn "kg_get_context\|kg_get_impact_analysis" internal --include=*.go | grep -v _test` chỉ còn comment ở `internal/config/types.go`; `grep -n kg_get_context config/config.yaml` chỉ còn comment mới.

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.go add internal/bridge/client.go internal/bridge/schema.go internal/bridge/client_test.go internal/bridge/schema_test.go internal/bridge/handler_test.go internal/bridge/e2e_tools_test.go internal/bridge/integration_test.go internal/config/types.go config/config.yaml
git -C ennam.kg.go commit -m "feat(bridge): add metrics provider tools, drop tools whose routes never existed" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 14: CLI `cmd/kg-packs` (import-mapping, install, set-as-of, run-metrics)

**Files:** Create `cmd/kg-packs/main.go`, `cmd/kg-packs/main_test.go`; Modify `Makefile:78-81` (target `build`).

**Interfaces:** Produces lệnh (master §4 M4):
```text
kg-packs import-mapping --project <uuid> --file mapping.yaml [--approve] [--approved-by name] [--sync-schema]
kg-packs install        --project <uuid> --pack <key> [--pack <key>]... [--disable]
kg-packs set-as-of      --project <uuid> (--date YYYY-MM-DD | --clear) [--timezone IANA]
kg-packs run-metrics    --project <uuid> [--from YYYY-MM-DD --to YYYY-MM-DD] [--metric key]...
chung: --packs-dir (mặc định $PACKS_DIR hoặc /packs), --dsn (mặc định config kg-server + KG_DB_*)
```
`import-mapping` kiểm tra **mọi** entity (có trong pack; `mode=live`: bảng/cột theo schema đã sync + biểu thức qua validator) rồi mới ghi — lỗi ⇒ không ghi gì; `--sync-schema` refresh metadata trước (cần `KG_ENCRYPTION_KEY`; dùng sau khi Plan A thêm cột). `install` từ chối pack con khi pack cha chưa bật. `run-metrics` in `RunSummary` JSON, exit ≠ 0 nếu có metric `blocked`.

- [ ] **Step 1: Viết test (failing)**
`cmd/kg-packs/main_test.go`:
```go
package main

import (
	"bytes"
	"context"
	"database/sql"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	_ "github.com/lib/pq"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/intelstore"
)

func TestRunOptions(t *testing.T) {
	if _, err := runOptions("2026-07-01", "", nil); err == nil {
		t.Fatal("--from without --to must fail")
	}
	if _, err := runOptions("2026-07-02", "2026-07-01", nil); err == nil {
		t.Fatal("from after to must fail")
	}
	o, err := runOptions("2025-08-01", "2026-08-01", []string{"a.b"})
	if err != nil || o.From.Format("2006-01-02") != "2025-08-01" || o.Metrics[0] != "a.b" {
		t.Fatalf("opts = %+v, %v", o, err)
	}
}

func TestAsOfArg(t *testing.T) {
	if _, err := asOfArg("", false, ""); err == nil {
		t.Fatal("neither --date nor --clear must fail")
	}
	if _, err := asOfArg("2026-08-01", true, ""); err == nil {
		t.Fatal("both --date and --clear must fail")
	}
	if _, err := asOfArg("2026-08-01", false, "Mars/Base"); err == nil {
		t.Fatal("bad timezone must fail")
	}
	d, err := asOfArg("2026-08-01", false, "America/Chicago")
	if err != nil || d.Format("2006-01-02") != "2026-08-01" {
		t.Fatalf("d = %v, %v", d, err)
	}
	if d, err := asOfArg("", true, ""); err != nil || d != nil {
		t.Fatalf("clear = %v, %v", d, err)
	}
}

func cliDB(t *testing.T) (*sql.DB, string, string) {
	t.Helper()
	url := os.Getenv("KG_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("Skipping integration test: KG_TEST_DATABASE_URL not set")
	}
	db, err := sql.Open("postgres", url)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	var pid, dsID, schemaID, tableID string
	must := func(err error) {
		t.Helper()
		if err != nil {
			t.Fatal(err)
		}
	}
	must(db.QueryRow(`INSERT INTO projects (name) VALUES ($1) RETURNING id::text`, fmt.Sprintf("kg-packs-%d", time.Now().UnixNano())).Scan(&pid))
	must(db.QueryRow(`INSERT INTO data_sources (project_id, name, host, database_name, connection_string_encrypted, created_by)
		VALUES ($1, 'src', 'h', 'd', '\x00', 't') RETURNING id::text`, pid).Scan(&dsID))
	t.Cleanup(func() {
		_, _ = db.Exec(`DELETE FROM project_mapping WHERE project_id = $1`, pid)
		_, _ = db.Exec(`DELETE FROM source_schemas WHERE data_source_id = $1`, dsID)
		_, _ = db.Exec(`DELETE FROM data_sources WHERE id = $1`, dsID)
		_, _ = db.Exec(`DELETE FROM projects WHERE id = $1`, pid)
	})
	must(db.QueryRow(`INSERT INTO source_schemas (data_source_id, schema_name) VALUES ($1, 'public') RETURNING id::text`, dsID).Scan(&schemaID))
	must(db.QueryRow(`INSERT INTO source_tables (source_schema_id, table_name) VALUES ($1, 'orders') RETURNING id::text`, schemaID).Scan(&tableID))
	_, err = db.Exec(`INSERT INTO source_columns (source_table_id, column_name, data_type, ordinal_position) VALUES
		($1, 'id', 'text', 1), ($1, 'shop_code', 'text', 2), ($1, 'created_at', 'timestamp with time zone', 3),
		($1, 'total', 'numeric', 4), ($1, 'discount', 'numeric', 5), ($1, 'state', 'text', 6)`, tableID)
	must(err)
	return db, pid, dsID
}

func mappingYAML(pid, dsID, amount string) []byte {
	return []byte(fmt.Sprintf(`project_id: %s
defaults: { mode: live, data_source_id: %s }
entities:
  order:
    from: orders
    fields: { order_id: id, location_id: shop_code, ordered_at: created_at, amount: "%s", status: state }
    enum_map: { status: { OPEN: open, CLOSED: closed } }
`, pid, dsID, amount))
}

func TestImportMapping_ValidatesAgainstSyncedSchema(t *testing.T) {
	db, pid, dsID := cliDB(t)
	reg, err := intel.LoadRegistry("../../internal/intel/testdata/packs")
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()

	bad, _ := intel.ParseMappingFile(mappingYAML(pid, dsID, "total; DROP TABLE x"))
	var out bytes.Buffer
	if err := importMapping(ctx, db, reg, bad, true, "tester", &out); err == nil || !strings.Contains(err.Error(), "nothing written") {
		t.Fatalf("malicious expression must be rejected: %v", err)
	}
	if ms, _ := intelstore.New(db).ListMappings(ctx, pid); len(ms) != 0 {
		t.Fatalf("nothing may be written on rejection, got %+v", ms)
	}

	good, _ := intel.ParseMappingFile(mappingYAML(pid, dsID, "COALESCE(total, 0) - discount"))
	if err := importMapping(ctx, db, reg, good, true, "tester", &out); err != nil {
		t.Fatal(err)
	}
	ms, _ := intelstore.New(db).ListMappings(ctx, pid)
	if len(ms) != 1 || ms[0].Status != intel.MappingApproved || ms[0].Version != 1 {
		t.Fatalf("mappings = %+v", ms)
	}
}

func TestInstallPacks_RequiresAncestors(t *testing.T) {
	db, pid, _ := cliDB(t)
	reg, err := intel.LoadRegistry("../../internal/intel/testdata/packs")
	if err != nil {
		t.Fatal(err)
	}
	st := intelstore.New(db)
	ctx := context.Background()
	var out bytes.Buffer
	if err := installPacks(ctx, st, reg, pid, []string{"child"}, true, &out); err == nil || !strings.Contains(err.Error(), "extends base") {
		t.Fatalf("child without base must fail: %v", err)
	}
	if err := installPacks(ctx, st, reg, pid, []string{"base", "child"}, true, &out); err != nil {
		t.Fatal(err)
	}
	ins, _ := st.ListInstalls(ctx, pid)
	if len(ins) != 2 || ins[1].Version != "1.2.3" {
		t.Fatalf("installs = %+v", ins)
	}
}
```

- [ ] **Step 2: Chạy — FAIL**
```bash
cd ennam.kg.go && export KG_TEST_DATABASE_URL="postgres://ennam_kg:${KG_DB_PASSWORD:-ennam_kg_dev}@localhost:5433/ennam_kg?sslmode=disable"
go test -v -count=1 ./cmd/kg-packs/ 2>&1 | tee /tmp/planb.out | grep -E "^(--- |ok|FAIL)"
grep -c -- '--- SKIP' /tmp/planb.out   # phải in 0 — test DB bị SKIP vẫn báo ok
```
Expected: FAIL — `undefined: runOptions`, `undefined: importMapping`.

- [ ] **Step 3: Implement**
`cmd/kg-packs/main.go`:
```go
// Command kg-packs administers industry packs for a DAAB project (Plan B):
//
//	kg-packs import-mapping --project <uuid> --file mapping.yaml [--approve] [--approved-by name] [--sync-schema]
//	kg-packs install        --project <uuid> --pack <key> [--pack <key>]... [--disable]
//	kg-packs run-metrics    --project <uuid> [--from YYYY-MM-DD --to YYYY-MM-DD] [--metric key]...
//	kg-packs set-as-of      --project <uuid> (--date YYYY-MM-DD | --clear) [--timezone IANA]
//
// Common flags: --packs-dir (default $PACKS_DIR or /packs), --dsn (default: the
// kg-server config, i.e. config/environments/<env>.yaml + KG_DB_* env vars).
package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/ennam/ennam-kg/internal/config"
	"github.com/ennam/ennam-kg/internal/crypto"
	"github.com/ennam/ennam-kg/internal/database"
	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/engine"
	"github.com/ennam/ennam-kg/internal/intel/intelstore"
	"github.com/ennam/ennam-kg/internal/intel/livesource"
	"github.com/ennam/ennam-kg/internal/service"
	"github.com/ennam/ennam-kg/internal/store"
)

type multiFlag []string

func (m *multiFlag) String() string     { return strings.Join(*m, ",") }
func (m *multiFlag) Set(v string) error { *m = append(*m, v); return nil }

func main() {
	if len(os.Args) < 2 {
		usage(os.Stderr)
		os.Exit(2)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Hour)
	defer cancel()
	if err := run(ctx, os.Args[1], os.Args[2:], os.Stdout); err != nil {
		fmt.Fprintf(os.Stderr, "kg-packs %s: %v\n", os.Args[1], err)
		os.Exit(1)
	}
}

func usage(w io.Writer) {
	fmt.Fprintln(w, "usage: kg-packs <import-mapping|install|run-metrics|set-as-of> --project <uuid> [flags]")
}

// common holds flags shared by every subcommand.
type common struct {
	project  string
	packsDir string
	dsn      string
}

func (c *common) register(fs *flag.FlagSet) {
	fs.StringVar(&c.project, "project", "", "DAAB project id (required)")
	def := os.Getenv("PACKS_DIR")
	if def == "" {
		def = "/packs"
	}
	fs.StringVar(&c.packsDir, "packs-dir", def, "directory holding the packs")
	fs.StringVar(&c.dsn, "dsn", "", "PostgreSQL DSN of the DAAB database (default: kg-server config)")
}

func run(ctx context.Context, cmd string, args []string, out io.Writer) error {
	switch cmd {
	case "import-mapping":
		return cmdImportMapping(ctx, args, out)
	case "install":
		return cmdInstall(ctx, args, out)
	case "run-metrics":
		return cmdRunMetrics(ctx, args, out)
	case "set-as-of":
		return cmdSetAsOf(ctx, args, out)
	default:
		usage(out)
		return fmt.Errorf("unknown command %q", cmd)
	}
}

func openDB(dsn string) (*sql.DB, error) {
	if dsn == "" {
		env := config.GetEnvironment()
		dir := os.Getenv("KG_CONFIG_DIR")
		if dir == "" {
			dir = "config"
		}
		cfg, err := config.LoadServerConfigForEnv(dir, env)
		if err != nil {
			return nil, fmt.Errorf("load config: %w", err)
		}
		dsn = cfg.Database.DSN()
	}
	return database.ConnectDB(dsn)
}

func (c *common) open() (*sql.DB, *intel.Registry, error) {
	if c.project == "" {
		return nil, nil, errors.New("--project is required")
	}
	reg, err := intel.LoadRegistry(c.packsDir)
	if err != nil {
		return nil, nil, err
	}
	db, err := openDB(c.dsn)
	if err != nil {
		return nil, nil, err
	}
	return db, reg, nil
}

// cmdImportMapping validates every entity of the file against the packs and the
// synced source schema, then upserts project_mapping rows (all or nothing).
func cmdImportMapping(ctx context.Context, args []string, out io.Writer) error {
	fs := flag.NewFlagSet("import-mapping", flag.ContinueOnError)
	var c common
	c.register(fs)
	file := fs.String("file", "", "mapping YAML file (required)")
	approve := fs.Bool("approve", false, "store as approved (default: proposed)")
	approvedBy := fs.String("approved-by", os.Getenv("USER"), "recorded as approved_by")
	syncFirst := fs.Bool("sync-schema", false, "refresh the synced schema of every live data source first (needs KG_ENCRYPTION_KEY)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *file == "" {
		return errors.New("--file is required")
	}
	raw, err := os.ReadFile(*file)
	if err != nil {
		return err
	}
	mf, err := intel.ParseMappingFile(raw)
	if err != nil {
		return err
	}
	if c.project != "" && c.project != mf.ProjectID {
		return fmt.Errorf("--project %s does not match project_id %s in the file", c.project, mf.ProjectID)
	}
	c.project = mf.ProjectID
	db, reg, err := c.open()
	if err != nil {
		return err
	}
	defer db.Close()
	if *syncFirst {
		live, err := liveResolver(db)
		if err != nil {
			return err
		}
		if err := live.Prepare(ctx, mf.ProjectID, mf.Mappings); err != nil {
			return err
		}
	}
	return importMapping(ctx, db, reg, mf, *approve, *approvedBy, out)
}

// liveResolver builds the full mode=live resolver (schema sync + source executor).
func liveResolver(db *sql.DB) (*livesource.Resolver, error) {
	keyB64 := os.Getenv("KG_ENCRYPTION_KEY")
	if keyB64 == "" {
		return nil, errors.New("KG_ENCRYPTION_KEY is required to reach live data sources")
	}
	encKey, err := crypto.KeyFromBase64(keyB64)
	if err != nil {
		return nil, fmt.Errorf("KG_ENCRYPTION_KEY: %w", err)
	}
	logger := slog.New(slog.NewTextHandler(os.Stderr, nil))
	dsStore := store.NewDataSourceStore(db)
	metaStore := store.NewSchemaMetadataStore(db)
	jobStore := store.NewSyncJobStore(db)
	extractor := service.NewSchemaExtractorService(metaStore, jobStore, dsStore, encKey, logger)
	syncSvc := service.NewSchemaSyncService(metaStore, jobStore, extractor, logger)
	return livesource.New(db, dsStore, syncSvc, service.NewSourceExecutor(dsStore, encKey, logger)), nil
}

func importMapping(ctx context.Context, db *sql.DB, reg *intel.Registry, mf *intel.MappingFile, approve bool, approvedBy string, out io.Writer) error {
	all := make([]string, 0, len(reg.Packs))
	for k := range reg.Packs {
		all = append(all, k)
	}
	cat, err := reg.Effective(all)
	if err != nil {
		return err
	}
	comp := &intel.Compiler{Dialect: intel.Postgres{}, Catalog: cat}
	live := livesource.New(db, store.NewDataSourceStore(db), nil, nil)
	var problems []string
	for _, m := range mf.Mappings {
		if _, ok := cat.Entities[m.Entity]; !ok {
			problems = append(problems, fmt.Sprintf("%s: entity is not defined by any pack", m.Entity))
			continue
		}
		if m.Mode != intel.ModeLive {
			continue // mode=file: the dataset may not be uploaded yet (Plan C validates on upload)
		}
		bound, err := live.Bind(ctx, mf.ProjectID, m)
		if err == nil {
			_, err = comp.EntityCTE(m.Entity, m, bound.Table, "UTC")
		}
		if err != nil {
			problems = append(problems, fmt.Sprintf("%s: %v", m.Entity, err))
		}
	}
	if len(problems) > 0 {
		sort.Strings(problems)
		return fmt.Errorf("mapping rejected, nothing written:\n  %s", strings.Join(problems, "\n  "))
	}
	st := intelstore.New(db)
	status := intel.MappingProposed
	if approve {
		status = intel.MappingApproved
	}
	for _, m := range mf.Mappings {
		m.Status = status
		v, err := st.UpsertMapping(ctx, m, approvedBy)
		if err != nil {
			return err
		}
		fmt.Fprintf(out, "%-22s %-5s %-9s v%d\n", m.Entity, m.Mode, status, v)
	}
	return nil
}

// cmdInstall enables packs; every ancestor (extends) must be enabled too.
func cmdInstall(ctx context.Context, args []string, out io.Writer) error {
	fs := flag.NewFlagSet("install", flag.ContinueOnError)
	var c common
	c.register(fs)
	var packs multiFlag
	fs.Var(&packs, "pack", "pack key (repeatable)")
	disable := fs.Bool("disable", false, "disable the packs instead of enabling them")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if len(packs) == 0 {
		return errors.New("at least one --pack is required")
	}
	db, reg, err := c.open()
	if err != nil {
		return err
	}
	defer db.Close()
	return installPacks(ctx, intelstore.New(db), reg, c.project, packs, !*disable, out)
}

func installPacks(ctx context.Context, st *intelstore.Store, reg *intel.Registry, projectID string, packs []string, enable bool, out io.Writer) error {
	existing, err := st.ListInstalls(ctx, projectID)
	if err != nil {
		return err
	}
	on := map[string]bool{}
	for _, in := range existing {
		on[in.PackKey] = in.Enabled
	}
	for _, k := range packs {
		if _, ok := reg.Packs[k]; !ok {
			return fmt.Errorf("unknown pack %q", k)
		}
		on[k] = enable
	}
	for k, enabled := range on {
		if !enabled {
			continue
		}
		p, ok := reg.Packs[k]
		if !ok {
			continue
		}
		for _, parent := range p.Extends {
			if !on[parent] {
				return fmt.Errorf("pack %s extends %s, which is not enabled (install both)", k, parent)
			}
		}
	}
	for _, k := range packs {
		if err := st.UpsertInstall(ctx, projectID, k, reg.Packs[k].Version, enable); err != nil {
			return err
		}
		fmt.Fprintf(out, "%s %s enabled=%v\n", k, reg.Packs[k].Version, enable)
	}
	return nil
}

// cmdRunMetrics runs the metric runner once, synchronously (backfill when
// --from/--to are given). Exit status is non-zero when any metric is blocked.
func cmdRunMetrics(ctx context.Context, args []string, out io.Writer) error {
	fs := flag.NewFlagSet("run-metrics", flag.ContinueOnError)
	var c common
	c.register(fs)
	fromS := fs.String("from", "", "first day (YYYY-MM-DD), with --to")
	toS := fs.String("to", "", "first day NOT included (YYYY-MM-DD), with --from")
	var metrics multiFlag
	fs.Var(&metrics, "metric", "metric key to run (repeatable; default all)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	opts, err := runOptions(*fromS, *toS, metrics)
	if err != nil {
		return err
	}
	db, reg, err := c.open()
	if err != nil {
		return err
	}
	defer db.Close()
	live, err := liveResolver(db)
	if err != nil {
		return err
	}
	logger := slog.New(slog.NewTextHandler(os.Stderr, nil))
	router := engine.NewSourceRouter(map[intel.SourceMode]intel.SourceResolver{intel.ModeLive: live})
	st := intelstore.New(db)
	rcfg, err := engine.RunnerConfigFromEnv()
	if err != nil {
		return err
	}
	sum, err := engine.NewRunner(reg, st, router, rcfg, logger).Run(ctx, c.project, opts)
	if err != nil {
		return err
	}
	enc := json.NewEncoder(out)
	enc.SetIndent("", "  ")
	if err := enc.Encode(sum); err != nil {
		return err
	}
	var blocked []string
	for _, m := range sum.Metrics {
		if m.Status == intel.StatusBlocked {
			blocked = append(blocked, m.Key)
		}
	}
	if len(blocked) > 0 {
		return fmt.Errorf("%d metric(s) blocked: %s", len(blocked), strings.Join(blocked, ", "))
	}
	return nil
}

// cmdSetAsOf pins (or clears) the as-of date of a project — the LAST data day,
// inclusive (demo: 2026-07-31). Analysis windows end at as_of+1, freshness is
// measured against it, kg_get_metrics defaults `to` to as_of+1 (master "As-of date").
func cmdSetAsOf(ctx context.Context, args []string, out io.Writer) error {
	fs := flag.NewFlagSet("set-as-of", flag.ContinueOnError)
	var c common
	c.register(fs)
	dateS := fs.String("date", "", "last data day, inclusive (YYYY-MM-DD)")
	clearIt := fs.Bool("clear", false, "remove the override (as_of = yesterday in the project timezone)")
	tz := fs.String("timezone", "", "optional IANA business timezone override")
	if err := fs.Parse(args); err != nil {
		return err
	}
	asOf, err := asOfArg(*dateS, *clearIt, *tz)
	if err != nil {
		return err
	}
	if c.project == "" {
		return errors.New("--project is required")
	}
	db, err := openDB(c.dsn)
	if err != nil {
		return err
	}
	defer db.Close()
	if err := intelstore.New(db).SetAsOf(ctx, c.project, asOf, *tz); err != nil {
		return err
	}
	if asOf == nil {
		fmt.Fprintf(out, "%s as_of cleared\n", c.project)
	} else {
		fmt.Fprintf(out, "%s as_of=%s\n", c.project, asOf.Format("2006-01-02"))
	}
	return nil
}

func asOfArg(dateS string, clearIt bool, tz string) (*time.Time, error) {
	if (dateS == "") == !clearIt {
		return nil, errors.New("give exactly one of --date or --clear")
	}
	if tz != "" {
		if _, err := time.LoadLocation(tz); err != nil {
			return nil, fmt.Errorf("--timezone: %w", err)
		}
	}
	if clearIt {
		return nil, nil
	}
	d, err := time.Parse("2006-01-02", dateS)
	if err != nil {
		return nil, fmt.Errorf("--date: %w", err)
	}
	return &d, nil
}

func runOptions(fromS, toS string, metrics []string) (engine.RunOptions, error) {
	opts := engine.RunOptions{Metrics: metrics}
	if (fromS == "") != (toS == "") {
		return opts, errors.New("--from and --to must be given together")
	}
	if fromS == "" {
		return opts, nil
	}
	from, err := time.Parse("2006-01-02", fromS)
	if err != nil {
		return opts, fmt.Errorf("--from: %w", err)
	}
	to, err := time.Parse("2006-01-02", toS)
	if err != nil {
		return opts, fmt.Errorf("--to: %w", err)
	}
	if !from.Before(to) {
		return opts, errors.New("--from must be before --to")
	}
	opts.From, opts.To = &from, &to
	return opts, nil
}
```

`Makefile`:
Thay đoạn (khớp chính xác):
```makefile
	go build -o bin/kg-migrate ./cmd/kg-migrate/
```
bằng:
```makefile
	go build -o bin/kg-migrate ./cmd/kg-migrate/
	go build -o bin/kg-packs ./cmd/kg-packs/
```

- [ ] **Step 4: Chạy — PASS, 0 SKIP + build**
```bash
cd ennam.kg.go && export KG_TEST_DATABASE_URL="postgres://ennam_kg:${KG_DB_PASSWORD:-ennam_kg_dev}@localhost:5433/ennam_kg?sslmode=disable"
go test -v -count=1 ./cmd/kg-packs/ 2>&1 | tee /tmp/planb.out | grep -E "^(--- |ok|FAIL)"
grep -c -- '--- SKIP' /tmp/planb.out   # phải in 0 — test DB bị SKIP vẫn báo ok
```
Expected: 4 test PASS (`TestRunOptions`, `TestAsOfArg`, `TestImportMapping_ValidatesAgainstSyncedSchema`, `TestInstallPacks_RequiresAncestors`); SKIP = 0; sau đó `make build` tạo `bin/kg-packs`.

- [ ] **Step 5: Commit**
```bash
git -C ennam.kg.go add cmd/kg-packs Makefile
git -C ennam.kg.go commit -m "feat(intel): kg-packs CLI for mapping import, pack install, as-of and backfill" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 15: Pack `retail` — canonical + 26 metric + 26 evidence

**Files:** Create `packs/retail/daab/canonical.yaml`, `packs/retail/daab/metrics/*.sql` (26), `packs/retail/daab/evidence/*.sql` (26). `packs/retail/pack.yaml` do master M1 tạo (nội dung giống bên dưới — nếu M1 chưa làm thì tạo đúng nội dung này).

**Interfaces:** Produces metric key (dims) — mỗi metric ghi rule cần nó trong comment `Rules:`:

| Metric | Aggregation | Dims | Rule |
|---|---|---|---|
| `retail.avg_ticket` | ratio (currency) | [location_id] | RET-SALES-001 |
| `retail.avg_unit_cost` | ratio (currency) | [location_id, product_id] | RET-VENDOR-001 |
| `retail.cash_shortage_count` | additive (count) | [location_id, employee_id] | RET-CASH-001 |
| `retail.cash_variance` | additive (currency) | [location_id, employee_id] | RET-CASH-001 |
| `retail.cogs` | additive (currency) | [location_id, category] | RET-MARGIN-002 |
| `retail.days_of_cover` | snapshot (days) | [location_id, product_id] | RET-INV-003 |
| `retail.discount_rate` | ratio (percent) | [location_id, employee_id] | RET-DISC-002 |
| `retail.duplicate_refund_groups` | additive (count) | [location_id] | RET-REF-004, FND-003 |
| `retail.gross_margin_pct` | ratio (percent) | [location_id, category] | RET-MARGIN-001, RET-MARGIN-002 |
| `retail.inventory_variance_value` | additive (currency) | [location_id, product_id] | RET-INV-001, RET-INV-010 |
| `retail.labor_cost` | additive (currency) | [location_id] | RET-LABOR-001 |
| `retail.labor_cost_pct` | ratio (percent) | [location_id] | RET-LABOR-001 |
| `retail.labor_hours` | additive (hours) | [location_id, employee_id] | RET-LABOR-002/003, RET-LABOR-006 |
| `retail.manual_override_count` | additive (count) | [location_id, employee_id, approver_id] | RET-DISC-003, RET-REF-005, FND-004 |
| `retail.net_sales` | additive (currency) | [location_id, category] | RET-SALES-001, RET-SALES-006 |
| `retail.no_receipt_refund_pct` | ratio (percent) | [location_id, employee_id] | RET-REF-002 |
| `retail.no_sale_rate` | ratio (percent) | [location_id, employee_id] | RET-CASH-004, FND-006 |
| `retail.override_rate` | ratio (percent) | [location_id, employee_id] | RET-DISC-003, FND-004, RET-REF-005 |
| `retail.overtime_hours` | additive (hours) | [location_id, employee_id] | RET-LABOR-006 |
| `retail.refund_count` | additive (count) | [location_id, employee_id, approver_id] | RET-REF-005 |
| `retail.refund_rate` | ratio (percent) | [location_id, employee_id] | RET-REF-001 |
| `retail.reprint_before_refund_count` | additive (count) | [location_id, employee_id] | RET-X-REPRINT-001, FND-007 |
| `retail.target_gross_margin_pct` | snapshot (percent) | [location_id] | RET-MARGIN-001 |
| `retail.target_net_sales` | snapshot (currency) | [location_id] | RET-MARGIN-001, RET-SALES-001 |
| `retail.transactions` | additive (count) | [location_id] | RET-SALES-001 |
| `retail.void_rate` | ratio (percent) | [location_id, employee_id] | RET-VOID-001 |
| `pharmacy.claim_rejection_rate` | ratio (percent) | [location_id] | PH-CLAIM-001, FND-005 |
| `pharmacy.reimbursement_gap` | additive (currency) | [location_id, product_id] | PH-MARGIN-001 |
| `pharmacy.rx_cost` | additive (currency) | [location_id, product_id] | PH-MARGIN-001 |
| `pharmacy.rx_margin` | additive (currency) | [location_id, product_id] |  |
| `pharmacy.rx_margin_pct` | ratio (percent) | [location_id, product_id] | PH-MARGIN-001 |
| `pharmacy.rx_revenue` | additive (currency) | [location_id, product_id] | PH-MARGIN-001 |

Consumes: loader (Task 2), compiler (Task 5). Evidence SQL: mỗi dim viết `(:dim_x IS NULL OR COALESCE(<cột>, '') = :dim_x)` — dim không truyền thì không lọc (finding thường gộp theo tập con dims). `retail.labor_cost`/`retail.labor_cost_pct` đọc entity `labor_rate` (map từ `employees.hourly_wage` của Plan A, Task 17). `retail.days_of_cover` dùng nhu cầu trung bình 28 ngày trước lần kiểm; lead time (RET-INV-003) là phần của rule LAAM. **`retail.overtime_hours`** = giờ overtime mà hệ thống chấm công của khách đã ghi trên từng ca (`shift.overtime_hours`, tức giờ vượt quy tắc overtime của chính khách) — **không** tính lại theo ngưỡng; kiểm tra "giờ dự kiến trong tuần vượt ngưỡng" của RET-LABOR-006 do rule LAAM làm.

- [ ] **Step 1: Failing check** — loader phải nạp được pack thật:
```bash
cd ennam.kg.go && cat > /tmp/packs_check_test.go <<'EOF'
package intel
import "testing"
func TestRealPacksLoad(t *testing.T) {
	reg, err := LoadRegistry("../../../packs")
	if err != nil { t.Fatal(err) }
	cat, err := reg.Effective([]string{"retail"})
	if err != nil { t.Fatal(err) }
	if len(cat.Metrics) != 26 || len(cat.Evidence) != 26 { t.Fatalf("metrics=%d evidence=%d", len(cat.Metrics), len(cat.Evidence)) }
}
EOF
cp /tmp/packs_check_test.go internal/intel/zz_packs_check_test.go && go test -count=1 -run TestRealPacksLoad ./internal/intel/; rm internal/intel/zz_packs_check_test.go
```
Expected: FAIL (`metrics=0` hoặc thiếu `canonical.yaml`).

- [ ] **Step 2: Tạo nội dung pack**

`packs/retail/pack.yaml`:
```yaml
key: retail
version: 0.1.0
display_name: Retail
```

`packs/retail/daab/canonical.yaml`:
```yaml
# Retail canonical model (spec §6.2). Only fields a beta metric or evidence query
# uses, plus the spec §6.2 core list. Added beyond §6.2 (each tied to a rule):
#   labor_rate                 RET-LABOR-001 (labor % needs a wage rate)
#   receipt_print              RET-X-REPRINT-001 (reprint before refund, FND-007)
#   price_override             RET-DISC-003 / RET-REF-005 (manual override concentration, FND-004)
#   cash_drawer.no_sale_count  RET-CASH-004 (no-sale drawer openings)
#   inventory_snapshot.snapshot_id  evidence reference (_source_ref)
entities:
  location:
    fields:
      location_id: { type: text, key: true }
      name:        { type: text }
      region:      { type: text }
      timezone:    { type: text }
      opened_at:   { type: date }
      status:      { type: text }
  product:
    fields:
      product_id:   { type: text, key: true }
      sku:          { type: text }
      name:         { type: text }
      category:     { type: text }
      subcategory:  { type: text }
      unit_cost:    { type: numeric }
      list_price:   { type: numeric }
      vendor_id:    { type: text }
      is_regulated: { type: boolean }
  employee:
    fields:
      employee_id: { type: text, key: true }
      location_id: { type: text }
      role:        { type: text }
  labor_rate:
    fields:
      employee_id:    { type: text, key: true, required: true }
      effective_from: { type: date, required: true }
      hourly_rate:    { type: numeric, required: true }
  sale:
    fields:
      sale_id:         { type: text, key: true }
      location_id:     { type: text, required: true }
      employee_id:     { type: text }
      customer_id:     { type: text }
      sold_at:         { type: timestamp, required: true }
      gross_amount:    { type: numeric }
      discount_amount: { type: numeric }
      tax_amount:      { type: numeric }
      net_amount:      { type: numeric }
      status:          { type: text, required: true }
  sale_line:
    fields:
      sale_line_id:    { type: text, key: true }
      sale_id:         { type: text, required: true }
      product_id:      { type: text, required: true }
      quantity:        { type: numeric, required: true }
      unit_price:      { type: numeric }
      unit_cost:       { type: numeric }
      discount_amount: { type: numeric }
      override_flag:   { type: boolean }
  refund:
    fields:
      refund_id:        { type: text, key: true }
      location_id:      { type: text, required: true }
      employee_id:      { type: text }
      approver_id:      { type: text }
      original_sale_id: { type: text }
      refunded_at:      { type: timestamp, required: true }
      amount:           { type: numeric, required: true }
      has_receipt:      { type: boolean }
      method:           { type: text }
  void:
    fields:
      void_id:     { type: text, key: true }
      location_id: { type: text, required: true }
      employee_id: { type: text }
      voided_at:   { type: timestamp, required: true }
      amount:      { type: numeric }
      post_tender: { type: boolean }
  cash_drawer:
    fields:
      drawer_id:     { type: text, key: true }
      location_id:   { type: text, required: true }
      employee_id:   { type: text }
      closed_at:     { type: timestamp, required: true }
      expected_cash: { type: numeric }
      counted_cash:  { type: numeric }
      no_sale_count: { type: integer }
  shift:
    fields:
      shift_id:           { type: text, key: true }
      location_id:        { type: text, required: true }
      employee_id:        { type: text }
      start_at:           { type: timestamp }
      end_at:             { type: timestamp }
      regular_hours:      { type: numeric }
      overtime_hours:     { type: numeric }
  inventory_movement:
    fields:
      movement_id:   { type: text, key: true }
      location_id:   { type: text, required: true }
      product_id:    { type: text, required: true }
      moved_at:      { type: timestamp, required: true }
      movement_type: { type: text, required: true }
      quantity:      { type: numeric }
  inventory_snapshot:
    fields:
      snapshot_id:   { type: text, key: true }
      location_id:   { type: text, required: true }
      product_id:    { type: text, required: true }
      snapshot_date: { type: date, required: true }
      book_qty:      { type: numeric }
      counted_qty:   { type: numeric }
      expired_qty:   { type: numeric }
  receipt_print:
    fields:
      receipt_id:  { type: text, key: true }
      sale_id:     { type: text }
      location_id: { type: text, required: true }
      employee_id: { type: text }
      printed_at:  { type: timestamp, required: true }
      print_type:  { type: text, required: true }
  price_override:
    fields:
      override_id:     { type: text, key: true }
      sale_id:         { type: text }
      location_id:     { type: text, required: true }
      employee_id:     { type: text }
      approver_id:     { type: text }
      product_id:      { type: text }
      overridden_at:   { type: timestamp, required: true }
      original_amount: { type: numeric }
      adjusted_amount: { type: numeric }
      discount_amount: { type: numeric }
  target:
    fields:
      location_id: { type: text, required: true }
      metric_key:  { type: text, required: true }
      period:      { type: date, required: true }
      value:       { type: numeric, required: true }
enums:
  sale.status: [completed, voided, cancelled]
  inventory_movement.movement_type: [sale, receipt, return, adjustment, transfer]
  receipt_print.print_type: [original, reprint, gift]
  target.metric_key: [net_sales, gross_margin_pct]
```

`packs/retail/daab/metrics/avg_ticket.sql`:
```sql
-- key: retail.avg_ticket
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: currency
-- aggregation: ratio
-- sample_size: completed sales
-- requires: [sale, sale_line, product]
-- Rules: RET-SALES-001 (average-ticket change). numerator = net sales, denominator = sales.
SELECT s.location_id,
       CAST(s.sold_at AS date)                                         AS period_date,
       SUM(l.quantity * l.unit_price - COALESCE(l.discount_amount, 0)) AS numerator,
       COUNT(DISTINCT s.sale_id)                                       AS denominator,
       COUNT(DISTINCT s.sale_id)                                       AS sample_size
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
GROUP BY 1, 2
```

`packs/retail/daab/metrics/avg_unit_cost.sql`:
```sql
-- key: retail.avg_unit_cost
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: currency
-- aggregation: ratio
-- sample_size: sale lines
-- requires: [sale, sale_line]
-- Rules: RET-VENDOR-001 "Cost Change % = (New Unit Cost − Previous Unit Cost) ÷ Previous" —
-- LAAM compares periods; numerator = Σ quantity × unit cost, denominator = Σ quantity.
SELECT s.location_id, l.product_id,
       CAST(s.sold_at AS date)            AS period_date,
       SUM(l.quantity * l.unit_cost)      AS numerator,
       SUM(l.quantity)                    AS denominator,
       COUNT(*)                           AS sample_size
FROM sale s
JOIN sale_line l ON l.sale_id = s.sale_id
WHERE s.status = 'completed'
  AND l.unit_cost IS NOT NULL
  AND s.sold_at >= :from AND s.sold_at < :to
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/cash_shortage_count.sql`:
```sql
-- key: retail.cash_shortage_count
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: count
-- aggregation: additive
-- sample_size: drawer closes
-- requires: [cash_drawer]
-- Rules: RET-CASH-001 "Default shortage trigger: Cash Variance ≤ −$25" — counted per
-- drawer close (requested by Plan D so the rule counts shortages instead of summing
-- variances per day). The −25 is the request's default trigger.
SELECT location_id, employee_id,
       CAST(closed_at AS date)                                        AS period_date,
       COUNT(*) FILTER (WHERE counted_cash - expected_cash <= -25)    AS value,
       COUNT(*)                                                       AS sample_size
FROM cash_drawer
WHERE closed_at >= :from AND closed_at < :to
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/cash_variance.sql`:
```sql
-- key: retail.cash_variance
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: currency
-- aggregation: additive
-- sample_size: drawer closes
-- requires: [cash_drawer]
-- Rules: RET-CASH-001 "Cash Variance = Counted Cash − Expected Cash"; the ≤ −$25 and
-- "repeated shortage" thresholds stay in the LAAM rule (count_days over daily points).
SELECT location_id, employee_id,
       CAST(closed_at AS date)             AS period_date,
       SUM(counted_cash - expected_cash)   AS value,
       COUNT(*)                            AS sample_size
FROM cash_drawer
WHERE closed_at >= :from AND closed_at < :to
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/cogs.sql`:
```sql
-- key: retail.cogs
-- version: 1
-- grain: day
-- dims: [location_id, category]
-- unit: currency
-- aggregation: additive
-- sample_size: sale lines
-- requires: [sale, sale_line, product]
-- Rules: RET-MARGIN-002 (forecast input). Line cost, falling back to product cost.
SELECT s.location_id,
       p.category,
       CAST(s.sold_at AS date)                               AS period_date,
       SUM(l.quantity * COALESCE(l.unit_cost, p.unit_cost))  AS value,
       COUNT(*)                                              AS sample_size
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/days_of_cover.sql`:
```sql
-- key: retail.days_of_cover
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: days
-- aggregation: snapshot
-- sample_size: counted products
-- requires: [inventory_snapshot, sale, sale_line]
-- Rules: RET-INV-003 (stockout risk). On hand (counted, else book) ÷ average daily
-- units sold over the 28 days before the count. NULL when nothing sold (no cover
-- estimate), never a fake large number.
WITH s AS (
  SELECT location_id, product_id, snapshot_date, SUM(COALESCE(counted_qty, book_qty)) AS on_hand
  FROM inventory_snapshot
  WHERE snapshot_date >= :from AND snapshot_date < :to
  GROUP BY 1, 2, 3
),
d AS (
  SELECT s.location_id, s.product_id, s.snapshot_date, SUM(l.quantity) AS units_28d
  FROM s
  JOIN sale x      ON x.location_id = s.location_id AND x.status = 'completed'
                  AND x.sold_at >= s.snapshot_date - 28 AND x.sold_at < s.snapshot_date
  JOIN sale_line l ON l.sale_id = x.sale_id AND l.product_id = s.product_id
  GROUP BY 1, 2, 3
)
SELECT s.location_id, s.product_id, s.snapshot_date AS period_date,
       CASE WHEN d.units_28d > 0 THEN s.on_hand * 28.0 / d.units_28d END AS value,
       1 AS sample_size
FROM s
LEFT JOIN d ON d.location_id = s.location_id AND d.product_id = s.product_id AND d.snapshot_date = s.snapshot_date
```

`packs/retail/daab/metrics/discount_rate.sql`:
```sql
-- key: retail.discount_rate
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: completed sales
-- requires: [sale, sale_line, product]
-- Rules: RET-DISC-002 (employee discount rate vs peers, ≥ 20 qualifying sales).
SELECT s.location_id, s.employee_id,
       CAST(s.sold_at AS date)                 AS period_date,
       SUM(COALESCE(l.discount_amount, 0))     AS numerator,
       SUM(l.quantity * l.unit_price)          AS denominator,
       COUNT(DISTINCT s.sale_id)               AS sample_size
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/duplicate_refund_groups.sql`:
```sql
-- key: retail.duplicate_refund_groups
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: count
-- aggregation: additive
-- sample_size: refunds examined
-- requires: [refund]
-- lookback_days: 30
-- Rules: RET-REF-004 (FND-003). value = refunds of an original sale that was already
-- refunded earlier (any date, any location), on the day/location of the repeat.
SELECT r.location_id,
       CAST(r.refunded_at AS date) AS period_date,
       SUM(CASE WHEN r.original_sale_id IS NOT NULL AND EXISTS (
             SELECT 1 FROM refund e
             WHERE e.original_sale_id = r.original_sale_id
               AND (e.refunded_at < r.refunded_at
                    OR (e.refunded_at = r.refunded_at AND e.refund_id < r.refund_id)))
           THEN 1 ELSE 0 END)  AS value,
       COUNT(*)                AS sample_size
FROM refund r
WHERE r.refunded_at >= :from AND r.refunded_at < :to
GROUP BY 1, 2
```

`packs/retail/daab/metrics/gross_margin_pct.sql`:
```sql
-- key: retail.gross_margin_pct
-- version: 1
-- grain: day
-- dims: [location_id, category]
-- unit: percent
-- aggregation: ratio
-- sample_size: completed sales
-- requires: [sale, sale_line, product]
-- Rules: RET-MARGIN-001, RET-MARGIN-002. numerator = net sales − cost, denominator = net sales.
SELECT s.location_id,
       p.category,
       CAST(s.sold_at AS date) AS period_date,
       SUM(l.quantity * l.unit_price - COALESCE(l.discount_amount, 0)
           - l.quantity * COALESCE(l.unit_cost, p.unit_cost))          AS numerator,
       SUM(l.quantity * l.unit_price - COALESCE(l.discount_amount, 0)) AS denominator,
       COUNT(DISTINCT s.sale_id)                                       AS sample_size
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/inventory_variance_value.sql`:
```sql
-- key: retail.inventory_variance_value
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: currency
-- aggregation: additive
-- sample_size: inventory counts
-- requires: [inventory_snapshot, product]
-- Rules: RET-INV-001 "Value Variance = (Physical − Book) × Unit Cost"; RET-INV-010
-- (book > physical). Additive per count (plan D contract): each counted day adds its variance.
SELECT i.location_id, i.product_id,
       i.snapshot_date                                        AS period_date,
       SUM((i.counted_qty - i.book_qty) * p.unit_cost)        AS value,
       COUNT(*)                                               AS sample_size
FROM inventory_snapshot i
LEFT JOIN product p ON p.product_id = i.product_id
WHERE i.snapshot_date >= :from AND i.snapshot_date < :to
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/labor_cost.sql`:
```sql
-- key: retail.labor_cost
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: currency
-- aggregation: additive
-- sample_size: shifts with a wage rate
-- requires: [shift, labor_rate]
-- Rules: RET-LABOR-001 "Labor % = Total Labor Cost ÷ Net Sales × 100" (LAAM divides).
-- Beta: worked hours × the hourly rate effective on the shift date, no overtime premium.
WITH rate AS (
  SELECT employee_id, effective_from, hourly_rate,
         LEAD(effective_from) OVER (PARTITION BY employee_id ORDER BY effective_from) AS effective_to
  FROM labor_rate
)
SELECT s.location_id,
       CAST(s.start_at AS date) AS period_date,
       SUM((COALESCE(s.regular_hours, 0) + COALESCE(s.overtime_hours, 0)) * r.hourly_rate) AS value,
       COUNT(r.hourly_rate)     AS sample_size
FROM shift s
LEFT JOIN rate r
  ON r.employee_id = s.employee_id
 AND r.effective_from <= CAST(s.start_at AS date)
 AND (r.effective_to IS NULL OR CAST(s.start_at AS date) < r.effective_to)
WHERE s.start_at >= :from AND s.start_at < :to
GROUP BY 1, 2
```

`packs/retail/daab/metrics/labor_cost_pct.sql`:
```sql
-- key: retail.labor_cost_pct
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: shifts with a wage rate
-- requires: [shift, labor_rate, sale]
-- Rules: RET-LABOR-001 "Labor % = Total Labor Cost ÷ Net Sales × 100". Labor cost as in
-- retail.labor_cost (no overtime premium); net sales = sale header net_amount. Days
-- without any priced shift have a NULL numerator (no value), never 0.
WITH rate AS (
  SELECT employee_id, effective_from, hourly_rate,
         LEAD(effective_from) OVER (PARTITION BY employee_id ORDER BY effective_from) AS effective_to
  FROM labor_rate
),
x AS (
  SELECT s.location_id, CAST(s.start_at AS date) AS period_date,
         (COALESCE(s.regular_hours, 0) + COALESCE(s.overtime_hours, 0)) * r.hourly_rate AS cost,
         CAST(0 AS numeric) AS sold,
         CASE WHEN r.hourly_rate IS NULL THEN 0 ELSE 1 END AS priced
  FROM shift s
  LEFT JOIN rate r
    ON r.employee_id = s.employee_id
   AND r.effective_from <= CAST(s.start_at AS date)
   AND (r.effective_to IS NULL OR CAST(s.start_at AS date) < r.effective_to)
  WHERE s.start_at >= :from AND s.start_at < :to
  UNION ALL
  SELECT location_id, CAST(sold_at AS date), CAST(NULL AS numeric), COALESCE(net_amount, 0), 0
  FROM sale
  WHERE status = 'completed' AND sold_at >= :from AND sold_at < :to
)
SELECT location_id, period_date,
       SUM(cost)   AS numerator,
       SUM(sold)   AS denominator,
       SUM(priced) AS sample_size
FROM x
GROUP BY 1, 2
```

`packs/retail/daab/metrics/labor_hours.sql`:
```sql
-- key: retail.labor_hours
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: hours
-- aggregation: additive
-- sample_size: shifts
-- requires: [shift]
-- Rules: RET-LABOR-002/003 inputs, RET-LABOR-006. Worked hours = regular + overtime, dated by clock-in.
SELECT location_id, employee_id,
       CAST(start_at AS date)                                          AS period_date,
       SUM(COALESCE(regular_hours, 0) + COALESCE(overtime_hours, 0))   AS value,
       COUNT(*)                                                        AS sample_size
FROM shift
WHERE start_at >= :from AND start_at < :to
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/manual_override_count.sql`:
```sql
-- key: retail.manual_override_count
-- version: 1
-- grain: day
-- dims: [location_id, employee_id, approver_id]
-- unit: count
-- aggregation: additive
-- sample_size: overrides
-- requires: [price_override]
-- Rules: RET-DISC-003, RET-REF-005 (FND-004: group_by approver_id).
SELECT location_id, employee_id, approver_id,
       CAST(overridden_at AS date) AS period_date,
       COUNT(*)                    AS value,
       COUNT(*)                    AS sample_size
FROM price_override
WHERE overridden_at >= :from AND overridden_at < :to
GROUP BY 1, 2, 3, 4
```

`packs/retail/daab/metrics/net_sales.sql`:
```sql
-- key: retail.net_sales
-- version: 1
-- grain: day
-- dims: [location_id, category]
-- unit: currency
-- aggregation: additive
-- sample_size: completed sales
-- requires: [sale, sale_line, product]
-- Rules: RET-SALES-001, RET-SALES-006. Lines of regulated products are excluded
-- (their revenue is counted by the extending pack, spec §6.2 "không tính trùng").
SELECT s.location_id,
       p.category,
       CAST(s.sold_at AS date)                                         AS period_date,
       SUM(l.quantity * l.unit_price - COALESCE(l.discount_amount, 0)) AS value,
       COUNT(DISTINCT s.sale_id)                                       AS sample_size
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/no_receipt_refund_pct.sql`:
```sql
-- key: retail.no_receipt_refund_pct
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: refunds
-- requires: [refund]
-- Rules: RET-REF-002 "No-Receipt Refunds ÷ Total Refunds × 100". Unknown receipt flag is not counted as no-receipt.
SELECT location_id, employee_id,
       CAST(refunded_at AS date)                     AS period_date,
       COUNT(*) FILTER (WHERE has_receipt IS FALSE)  AS numerator,
       COUNT(*)                                      AS denominator,
       COUNT(*)                                      AS sample_size
FROM refund
WHERE refunded_at >= :from AND refunded_at < :to
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/no_sale_rate.sql`:
```sql
-- key: retail.no_sale_rate
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: drawer openings
-- requires: [cash_drawer, sale]
-- Rules: RET-CASH-004 (FND-006). numerator = no-sale drawer openings; denominator =
-- all drawer openings, approximated as no-sale openings + completed sales (the
-- source has no per-opening log).
WITH x AS (
  SELECT location_id, employee_id, CAST(closed_at AS date) AS period_date,
         COALESCE(no_sale_count, 0) AS no_sale, COALESCE(no_sale_count, 0) AS openings
  FROM cash_drawer
  WHERE closed_at >= :from AND closed_at < :to
  UNION ALL
  SELECT location_id, employee_id, CAST(sold_at AS date), 0, 1
  FROM sale
  WHERE status = 'completed' AND sold_at >= :from AND sold_at < :to
)
SELECT location_id, employee_id, period_date,
       SUM(no_sale)  AS numerator,
       SUM(openings) AS denominator,
       SUM(openings) AS sample_size
FROM x
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/override_rate.sql`:
```sql
-- key: retail.override_rate
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: sale lines
-- requires: [price_override, sale, sale_line]
-- Rules: RET-DISC-003 "Override rate materially exceeds peers". numerator = manual
-- overrides by the employee, denominator = sale lines the employee rang up. The
-- approving-manager view (FND-004, RET-REF-005) is retail.manual_override_count
-- grouped by approver_id.
WITH x AS (
  SELECT location_id, employee_id, CAST(overridden_at AS date) AS period_date, 1 AS overrides, 0 AS lines
  FROM price_override
  WHERE overridden_at >= :from AND overridden_at < :to
  UNION ALL
  SELECT s.location_id, s.employee_id, CAST(s.sold_at AS date), 0, 1
  FROM sale s
  JOIN sale_line l ON l.sale_id = s.sale_id
  WHERE s.status = 'completed' AND s.sold_at >= :from AND s.sold_at < :to
)
SELECT location_id, employee_id, period_date,
       SUM(overrides) AS numerator,
       SUM(lines)     AS denominator,
       SUM(lines)     AS sample_size
FROM x
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/overtime_hours.sql`:
```sql
-- key: retail.overtime_hours
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: hours
-- aggregation: additive
-- sample_size: shifts
-- requires: [shift]
-- Rules: RET-LABOR-006 (overtime risk). Definition: the overtime hours the customer's
-- time system already recorded on each shift (shift.overtime_hours, i.e. hours beyond
-- the customer's own overtime rule) — NOT recomputed here against a threshold. The
-- request's projected-weekly-hours check is done by the LAAM rule.
SELECT location_id, employee_id,
       CAST(start_at AS date)            AS period_date,
       SUM(COALESCE(overtime_hours, 0))  AS value,
       COUNT(*)                          AS sample_size
FROM shift
WHERE start_at >= :from AND start_at < :to
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/refund_count.sql`:
```sql
-- key: retail.refund_count
-- version: 1
-- grain: day
-- dims: [location_id, employee_id, approver_id]
-- unit: count
-- aggregation: additive
-- sample_size: refunds
-- requires: [refund]
-- Rules: RET-REF-005 (manager approval concentration: group_by approver_id).
SELECT location_id, employee_id, approver_id,
       CAST(refunded_at AS date) AS period_date,
       COUNT(*)                  AS value,
       COUNT(*)                  AS sample_size
FROM refund
WHERE refunded_at >= :from AND refunded_at < :to
GROUP BY 1, 2, 3, 4
```

`packs/retail/daab/metrics/refund_rate.sql`:
```sql
-- key: retail.refund_rate
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: refunds
-- requires: [refund, sale]
-- Rules: RET-REF-001 "Refund Value Rate = Refund Value ÷ Net Sales Before Refunds × 100"
-- (plan D contract: value ratio); min_sample counts refunds, so sample_size = refunds.
-- Net sales is the sale header net_amount (all POS lines).
WITH x AS (
  SELECT location_id, employee_id, CAST(refunded_at AS date) AS period_date,
         amount AS refunded, CAST(0 AS numeric) AS sold, 1 AS refunds
  FROM refund
  WHERE refunded_at >= :from AND refunded_at < :to
  UNION ALL
  SELECT location_id, employee_id, CAST(sold_at AS date), 0, COALESCE(net_amount, 0), 0
  FROM sale
  WHERE status = 'completed' AND sold_at >= :from AND sold_at < :to
)
SELECT location_id, employee_id, period_date,
       SUM(refunded) AS numerator,
       SUM(sold)     AS denominator,
       SUM(refunds)  AS sample_size
FROM x
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/reprint_before_refund_count.sql`:
```sql
-- key: retail.reprint_before_refund_count
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: count
-- aggregation: additive
-- sample_size: refunds
-- requires: [refund, receipt_print]
-- Rules: RET-X-REPRINT-001 (FND-007): value = refunds whose original sale receipt the
-- same employee reprinted 1–48 hours before refunding it; sample_size = all refunds.
SELECT r.location_id, r.employee_id,
       CAST(r.refunded_at AS date) AS period_date,
       SUM(CASE WHEN EXISTS (
             SELECT 1 FROM receipt_print p
             WHERE p.sale_id = r.original_sale_id
               AND p.print_type = 'reprint'
               AND p.employee_id = r.employee_id
               AND p.printed_at >= r.refunded_at - INTERVAL '48 hours'
               AND p.printed_at <= r.refunded_at - INTERVAL '1 hour')
           THEN 1 ELSE 0 END)  AS value,
       COUNT(*)                AS sample_size
FROM refund r
WHERE r.refunded_at >= :from AND r.refunded_at < :to
GROUP BY 1, 2, 3
```

`packs/retail/daab/metrics/target_gross_margin_pct.sql`:
```sql
-- key: retail.target_gross_margin_pct
-- version: 1
-- grain: month
-- dims: [location_id]
-- unit: percent
-- aggregation: snapshot
-- sample_size: target rows
-- requires: [target]
-- Rules: RET-MARGIN-001 "Actual Gross Margin % − Target Gross Margin %".
SELECT location_id,
       period     AS period_date,
       value,
       1          AS sample_size
FROM target
WHERE metric_key = 'gross_margin_pct'
  AND period >= :from AND period < :to
```

`packs/retail/daab/metrics/target_net_sales.sql`:
```sql
-- key: retail.target_net_sales
-- version: 1
-- grain: month
-- dims: [location_id]
-- unit: currency
-- aggregation: snapshot
-- sample_size: target rows
-- requires: [target]
-- Rules: RET-MARGIN-001 / RET-SALES-001 (customer target). Monthly target from the
-- uploaded file (mode=file, Plan C); LAAM prorates by days (spec §6.4).
SELECT location_id,
       period     AS period_date,
       value,
       1          AS sample_size
FROM target
WHERE metric_key = 'net_sales'
  AND period >= :from AND period < :to
```

`packs/retail/daab/metrics/transactions.sql`:
```sql
-- key: retail.transactions
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: count
-- aggregation: additive
-- sample_size: completed sales
-- requires: [sale]
-- Rules: RET-SALES-001 (transaction-count change, minimum volume).
SELECT location_id,
       CAST(sold_at AS date) AS period_date,
       COUNT(*)              AS value,
       COUNT(*)              AS sample_size
FROM sale
WHERE status = 'completed'
  AND sold_at >= :from AND sold_at < :to
GROUP BY 1, 2
```

`packs/retail/daab/metrics/void_rate.sql`:
```sql
-- key: retail.void_rate
-- version: 1
-- grain: day
-- dims: [location_id, employee_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: started sales
-- requires: [void, sale]
-- Rules: RET-VOID-001 "Voided Transactions ÷ Started Transactions × 100";
-- started = every sale row whatever its status.
WITH x AS (
  SELECT location_id, employee_id, CAST(voided_at AS date) AS period_date, 1 AS voids, 0 AS started
  FROM void
  WHERE voided_at >= :from AND voided_at < :to
  UNION ALL
  SELECT location_id, employee_id, CAST(sold_at AS date), 0, 1
  FROM sale
  WHERE sold_at >= :from AND sold_at < :to
)
SELECT location_id, employee_id, period_date,
       SUM(voids)   AS numerator,
       SUM(started) AS denominator,
       SUM(started) AS sample_size
FROM x
GROUP BY 1, 2, 3
```

`packs/retail/daab/evidence/avg_ticket.sql`:
```sql
-- key: retail.avg_ticket
SELECT s.sale_id, s.sold_at, s.employee_id, l.product_id, p.category,
       l.quantity, l.unit_price, l.unit_cost, l.discount_amount, l._source_ref
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(s.location_id, '') = :dim_location_id)
ORDER BY s.sold_at, s.sale_id, l.sale_line_id
```

`packs/retail/daab/evidence/avg_unit_cost.sql`:
```sql
-- key: retail.avg_unit_cost
SELECT s.sale_id, s.sold_at, l.quantity, l.unit_cost, l._source_ref
FROM sale s
JOIN sale_line l ON l.sale_id = s.sale_id
WHERE s.status = 'completed'
  AND l.unit_cost IS NOT NULL
  AND s.sold_at >= :from AND s.sold_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(s.location_id, '') = :dim_location_id)
  AND (:dim_product_id IS NULL OR COALESCE(l.product_id, '') = :dim_product_id)
ORDER BY s.sold_at, s.sale_id
```

`packs/retail/daab/evidence/cash_shortage_count.sql`:
```sql
-- key: retail.cash_shortage_count
SELECT drawer_id, closed_at, expected_cash, counted_cash, no_sale_count, _source_ref
FROM cash_drawer
WHERE closed_at >= :from AND closed_at < :to
  AND counted_cash - expected_cash <= -25
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
ORDER BY closed_at, drawer_id
```

`packs/retail/daab/evidence/cash_variance.sql`:
```sql
-- key: retail.cash_variance
SELECT drawer_id, closed_at, expected_cash, counted_cash, no_sale_count, _source_ref
FROM cash_drawer
WHERE closed_at >= :from AND closed_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
ORDER BY closed_at, drawer_id
```

`packs/retail/daab/evidence/cogs.sql`:
```sql
-- key: retail.cogs
SELECT s.sale_id, s.sold_at, s.employee_id, l.product_id, p.category,
       l.quantity, l.unit_price, l.unit_cost, l.discount_amount, l._source_ref
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(s.location_id, '') = :dim_location_id)
  AND (:dim_category IS NULL OR COALESCE(p.category, '') = :dim_category)
ORDER BY s.sold_at, s.sale_id, l.sale_line_id
```

`packs/retail/daab/evidence/days_of_cover.sql`:
```sql
-- key: retail.days_of_cover
SELECT snapshot_id, snapshot_date, book_qty, counted_qty, expired_qty, _source_ref
FROM inventory_snapshot
WHERE snapshot_date >= :from AND snapshot_date < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_product_id IS NULL OR COALESCE(product_id, '') = :dim_product_id)
ORDER BY snapshot_date, snapshot_id
```

`packs/retail/daab/evidence/discount_rate.sql`:
```sql
-- key: retail.discount_rate
SELECT s.sale_id, s.sold_at, s.employee_id, l.product_id, p.category,
       l.quantity, l.unit_price, l.unit_cost, l.discount_amount, l._source_ref
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(s.location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(s.employee_id, '') = :dim_employee_id)
ORDER BY s.sold_at, s.sale_id, l.sale_line_id
```

`packs/retail/daab/evidence/duplicate_refund_groups.sql`:
```sql
-- key: retail.duplicate_refund_groups
-- Every refund of the repeated original sales (earlier ones included, any location),
-- so the reviewer sees each pair.
SELECT e.original_sale_id, e.refund_id, e.refunded_at, e.location_id, e.employee_id,
       e.amount, e.method, e._source_ref
FROM refund e
WHERE e.original_sale_id IN (
  SELECT r.original_sale_id FROM refund r
  WHERE r.refunded_at >= :from AND r.refunded_at < :to
    AND (:dim_location_id IS NULL OR COALESCE(r.location_id, '') = :dim_location_id)
    AND r.original_sale_id IS NOT NULL
    AND EXISTS (
      SELECT 1 FROM refund x
      WHERE x.original_sale_id = r.original_sale_id
        AND (x.refunded_at < r.refunded_at
             OR (x.refunded_at = r.refunded_at AND x.refund_id < r.refund_id))))
ORDER BY e.original_sale_id, e.refunded_at, e.refund_id
```

`packs/retail/daab/evidence/gross_margin_pct.sql`:
```sql
-- key: retail.gross_margin_pct
SELECT s.sale_id, s.sold_at, s.employee_id, l.product_id, p.category,
       l.quantity, l.unit_price, l.unit_cost, l.discount_amount, l._source_ref
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(s.location_id, '') = :dim_location_id)
  AND (:dim_category IS NULL OR COALESCE(p.category, '') = :dim_category)
ORDER BY s.sold_at, s.sale_id, l.sale_line_id
```

`packs/retail/daab/evidence/inventory_variance_value.sql`:
```sql
-- key: retail.inventory_variance_value
SELECT i.snapshot_id, i.snapshot_date, i.book_qty, i.counted_qty, i.expired_qty, p.unit_cost, i._source_ref
FROM inventory_snapshot i
LEFT JOIN product p ON p.product_id = i.product_id
WHERE i.snapshot_date >= :from AND i.snapshot_date < :to
  AND (:dim_location_id IS NULL OR COALESCE(i.location_id, '') = :dim_location_id)
  AND (:dim_product_id IS NULL OR COALESCE(i.product_id, '') = :dim_product_id)
ORDER BY i.snapshot_date, i.snapshot_id
```

`packs/retail/daab/evidence/labor_cost.sql`:
```sql
-- key: retail.labor_cost
WITH rate AS (
  SELECT employee_id, effective_from, hourly_rate,
         LEAD(effective_from) OVER (PARTITION BY employee_id ORDER BY effective_from) AS effective_to
  FROM labor_rate
)
SELECT s.shift_id, s.employee_id, s.start_at, s.regular_hours, s.overtime_hours,
       r.hourly_rate, s._source_ref
FROM shift s
LEFT JOIN rate r
  ON r.employee_id = s.employee_id
 AND r.effective_from <= CAST(s.start_at AS date)
 AND (r.effective_to IS NULL OR CAST(s.start_at AS date) < r.effective_to)
WHERE s.start_at >= :from AND s.start_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(s.location_id, '') = :dim_location_id)
ORDER BY s.start_at, s.shift_id
```

`packs/retail/daab/evidence/labor_cost_pct.sql`:
```sql
-- key: retail.labor_cost_pct
WITH rate AS (
  SELECT employee_id, effective_from, hourly_rate,
         LEAD(effective_from) OVER (PARTITION BY employee_id ORDER BY effective_from) AS effective_to
  FROM labor_rate
)
SELECT s.shift_id, s.employee_id, s.start_at, s.regular_hours, s.overtime_hours,
       r.hourly_rate, s._source_ref
FROM shift s
LEFT JOIN rate r
  ON r.employee_id = s.employee_id
 AND r.effective_from <= CAST(s.start_at AS date)
 AND (r.effective_to IS NULL OR CAST(s.start_at AS date) < r.effective_to)
WHERE s.start_at >= :from AND s.start_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(s.location_id, '') = :dim_location_id)
ORDER BY s.start_at, s.shift_id
```

`packs/retail/daab/evidence/labor_hours.sql`:
```sql
-- key: retail.labor_hours
SELECT shift_id, start_at, end_at, regular_hours, overtime_hours, _source_ref
FROM shift
WHERE start_at >= :from AND start_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
ORDER BY start_at, shift_id
```

`packs/retail/daab/evidence/manual_override_count.sql`:
```sql
-- key: retail.manual_override_count
SELECT override_id, overridden_at, sale_id, product_id, original_amount, adjusted_amount,
       discount_amount, _source_ref
FROM price_override
WHERE overridden_at >= :from AND overridden_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
  AND (:dim_approver_id IS NULL OR COALESCE(approver_id, '') = :dim_approver_id)
ORDER BY overridden_at, override_id
```

`packs/retail/daab/evidence/net_sales.sql`:
```sql
-- key: retail.net_sales
SELECT s.sale_id, s.sold_at, s.employee_id, l.product_id, p.category,
       l.quantity, l.unit_price, l.unit_cost, l.discount_amount, l._source_ref
FROM sale s
JOIN sale_line l   ON l.sale_id = s.sale_id
LEFT JOIN product p ON p.product_id = l.product_id
WHERE s.status = 'completed'
  AND NOT COALESCE(p.is_regulated, false)
  AND s.sold_at >= :from AND s.sold_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(s.location_id, '') = :dim_location_id)
  AND (:dim_category IS NULL OR COALESCE(p.category, '') = :dim_category)
ORDER BY s.sold_at, s.sale_id, l.sale_line_id
```

`packs/retail/daab/evidence/no_receipt_refund_pct.sql`:
```sql
-- key: retail.no_receipt_refund_pct
SELECT refund_id, refunded_at, employee_id, approver_id, original_sale_id, amount, has_receipt, method, _source_ref
FROM refund
WHERE refunded_at >= :from AND refunded_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
ORDER BY refunded_at, refund_id
```

`packs/retail/daab/evidence/no_sale_rate.sql`:
```sql
-- key: retail.no_sale_rate
SELECT drawer_id, closed_at, no_sale_count, expected_cash, counted_cash, _source_ref
FROM cash_drawer
WHERE closed_at >= :from AND closed_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
ORDER BY closed_at, drawer_id
```

`packs/retail/daab/evidence/override_rate.sql`:
```sql
-- key: retail.override_rate
SELECT override_id, overridden_at, sale_id, product_id, approver_id, original_amount,
       adjusted_amount, discount_amount, _source_ref
FROM price_override
WHERE overridden_at >= :from AND overridden_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
ORDER BY overridden_at, override_id
```

`packs/retail/daab/evidence/overtime_hours.sql`:
```sql
-- key: retail.overtime_hours
SELECT shift_id, start_at, end_at, regular_hours, overtime_hours, _source_ref
FROM shift
WHERE start_at >= :from AND start_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
ORDER BY start_at, shift_id
```

`packs/retail/daab/evidence/refund_count.sql`:
```sql
-- key: retail.refund_count
SELECT refund_id, refunded_at, employee_id, approver_id, original_sale_id, amount, has_receipt, method, _source_ref
FROM refund
WHERE refunded_at >= :from AND refunded_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
  AND (:dim_approver_id IS NULL OR COALESCE(approver_id, '') = :dim_approver_id)
ORDER BY refunded_at, refund_id
```

`packs/retail/daab/evidence/refund_rate.sql`:
```sql
-- key: retail.refund_rate
SELECT refund_id, refunded_at, employee_id, approver_id, original_sale_id, amount, has_receipt, method, _source_ref
FROM refund
WHERE refunded_at >= :from AND refunded_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
ORDER BY refunded_at, refund_id
```

`packs/retail/daab/evidence/reprint_before_refund_count.sql`:
```sql
-- key: retail.reprint_before_refund_count
-- One row per (refund, matching reprint) pair.
SELECT r.refund_id, r.refunded_at, r.original_sale_id, r.amount,
       p.receipt_id, p.printed_at, r._source_ref
FROM refund r
JOIN receipt_print p
  ON p.sale_id = r.original_sale_id
 AND p.print_type = 'reprint'
 AND p.employee_id = r.employee_id
 AND p.printed_at >= r.refunded_at - INTERVAL '48 hours'
 AND p.printed_at <= r.refunded_at - INTERVAL '1 hour'
WHERE r.refunded_at >= :from AND r.refunded_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(r.location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(r.employee_id, '') = :dim_employee_id)
ORDER BY r.refunded_at, r.refund_id, p.printed_at
```

`packs/retail/daab/evidence/target_gross_margin_pct.sql`:
```sql
-- key: retail.target_gross_margin_pct
SELECT location_id, metric_key, period, value, _source_ref
FROM target
WHERE metric_key = 'gross_margin_pct'
  AND period >= :from AND period < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
ORDER BY period
```

`packs/retail/daab/evidence/target_net_sales.sql`:
```sql
-- key: retail.target_net_sales
SELECT location_id, metric_key, period, value, _source_ref
FROM target
WHERE metric_key = 'net_sales'
  AND period >= :from AND period < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
ORDER BY period
```

`packs/retail/daab/evidence/transactions.sql`:
```sql
-- key: retail.transactions
SELECT sale_id, sold_at, employee_id, gross_amount, discount_amount, net_amount, _source_ref
FROM sale
WHERE status = 'completed'
  AND sold_at >= :from AND sold_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
ORDER BY sold_at, sale_id
```

`packs/retail/daab/evidence/void_rate.sql`:
```sql
-- key: retail.void_rate
SELECT void_id, voided_at, amount, post_tender, _source_ref
FROM void
WHERE voided_at >= :from AND voided_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
  AND (:dim_employee_id IS NULL OR COALESCE(employee_id, '') = :dim_employee_id)
ORDER BY voided_at, void_id
```

- [ ] **Step 3: Chạy lại check ở Step 1** — Expected: PASS. (Test có giá trị tính tay cho từng metric ở Task 17.)

- [ ] **Step 4: Commit (repo workspace)**
```bash
git add packs/retail
git commit -m "feat(packs): retail canonical model, metrics and evidence queries" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 16: Pack `pharmacy` — canonical extension + 6 metric + 6 evidence

**Files:** Create `packs/pharmacy/daab/canonical.yaml`, `packs/pharmacy/daab/metrics/*.sql` (6), `packs/pharmacy/daab/evidence/*.sql` (6); `packs/pharmacy/pack.yaml` (M1).

**Interfaces:** `pharmacy.claim_rejection_rate`, `pharmacy.rx_revenue`, `pharmacy.rx_cost`, `pharmacy.rx_margin`, `pharmacy.rx_margin_pct`, `pharmacy.reimbursement_gap` (bảng ở Task 15). Giá vốn Rx = `prescription.acquisition_cost` (per-fill — master Global Constraints, thay công thức spec §6.2 `quantity × unit_cost`). Phát hiện margin dùng `pharmacy.rx_margin_pct` (ratio). `lookback_days: 14` vì claim đổi trạng thái sau nhiều ngày.

- [ ] **Step 1: Failing check** — như Task 15 Step 1 nhưng `reg.Effective([]string{"pharmacy"})` và kỳ vọng `len(cat.Metrics) == 32`. Expected: FAIL.

- [ ] **Step 2: Tạo nội dung pack**

`packs/pharmacy/pack.yaml`:
```yaml
key: pharmacy
version: 0.1.0
extends: [retail]
display_name: Pharmacy
```

`packs/pharmacy/daab/canonical.yaml`:
```yaml
# Pharmacy extension (spec §6.2 + master Global Constraints). Definitions:
#   reimbursement = claim.reimbursed_amount; Rx revenue = reimbursed + patient amount;
#   acquisition cost = prescription.acquisition_cost, the per-fill cost (master
#   "Giá vốn Rx" — supersedes spec §6.2 quantity × product.unit_cost);
#   revenue/cost exclude prescription.status in (reversed, cancelled);
#   claim_rejection_rate counts every claim.
entities:
  prescription:
    fields:
      prescription_id: { type: text, key: true }
      location_id:     { type: text, required: true }
      product_id:      { type: text, required: true }
      filled_at:       { type: timestamp }
      quantity:        { type: numeric }
      status:          { type: text, required: true }
      cash_price:      { type: numeric }
      acquisition_cost: { type: numeric, required: true }
      patient_paid:    { type: numeric }
      payer_paid:      { type: numeric }
  claim:
    fields:
      claim_id:          { type: text, key: true }
      prescription_id:   { type: text }
      location_id:       { type: text, required: true }
      payer:             { type: text }
      submitted_at:      { type: timestamp, required: true }
      billed_amount:     { type: numeric }
      reimbursed_amount: { type: numeric }
      patient_amount:    { type: numeric }
      is_rejected:       { type: boolean, required: true }
      rejection_code:    { type: text }
enums:
  prescription.status: [received, ready, picked_up, not_collected, reversed, cancelled]
```

`packs/pharmacy/daab/metrics/claim_rejection_rate.sql`:
```sql
-- key: pharmacy.claim_rejection_rate
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: claims
-- requires: [claim]
-- lookback_days: 14
-- Rules: PH-CLAIM-001 (FND-005). Every claim counts (spec §6.2). Longer lookback:
-- claims change status days after submission.
SELECT location_id,
       CAST(submitted_at AS date)            AS period_date,
       COUNT(*) FILTER (WHERE is_rejected)   AS numerator,
       COUNT(*)                              AS denominator,
       COUNT(*)                              AS sample_size
FROM claim
WHERE submitted_at >= :from AND submitted_at < :to
GROUP BY 1, 2
```

`packs/pharmacy/daab/metrics/reimbursement_gap.sql`:
```sql
-- key: pharmacy.reimbursement_gap
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: currency
-- aggregation: additive
-- sample_size: paid claims
-- requires: [claim, prescription]
-- lookback_days: 14
-- Rules: PH-MARGIN-001. Payer reimbursement − acquisition cost (request DAAB-04
-- "reimbursement variance"); copay excluded — pharmacy.rx_margin includes it.
SELECT c.location_id, p.product_id,
       CAST(c.submitted_at AS date)                                           AS period_date,
       SUM(COALESCE(c.reimbursed_amount, 0)) - SUM(p.acquisition_cost)        AS value,
       COUNT(*)                                                               AS sample_size
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')
  AND c.submitted_at >= :from AND c.submitted_at < :to
GROUP BY 1, 2, 3
```

`packs/pharmacy/daab/metrics/rx_cost.sql`:
```sql
-- key: pharmacy.rx_cost
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: currency
-- aggregation: additive
-- sample_size: paid claims
-- requires: [claim, prescription]
-- lookback_days: 14
-- Rules: PH-MARGIN-001, forecast input. Acquisition cost = per-fill prescription cost.
SELECT c.location_id, p.product_id,
       CAST(c.submitted_at AS date)   AS period_date,
       SUM(p.acquisition_cost)        AS value,
       COUNT(*)                       AS sample_size
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')
  AND c.submitted_at >= :from AND c.submitted_at < :to
GROUP BY 1, 2, 3
```

`packs/pharmacy/daab/metrics/rx_margin.sql`:
```sql
-- key: pharmacy.rx_margin
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: currency
-- aggregation: additive
-- sample_size: paid claims
-- requires: [claim, prescription]
-- lookback_days: 14
-- Rules: scenario/forecast input. Rx revenue − acquisition cost (includes copay).
-- Margin DETECTION uses pharmacy.rx_margin_pct (master: dollar totals swing ±10–18%).
SELECT c.location_id, p.product_id,
       CAST(c.submitted_at AS date) AS period_date,
       SUM(COALESCE(c.reimbursed_amount, 0) + COALESCE(c.patient_amount, 0) - p.acquisition_cost) AS value,
       COUNT(*)                     AS sample_size
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')
  AND c.submitted_at >= :from AND c.submitted_at < :to
GROUP BY 1, 2, 3
```

`packs/pharmacy/daab/metrics/rx_margin_pct.sql`:
```sql
-- key: pharmacy.rx_margin_pct
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: percent
-- aggregation: ratio
-- sample_size: paid claims
-- requires: [claim, prescription]
-- lookback_days: 14
-- Rules: PH-MARGIN-001 (margin decline detection, breakdown by product_id).
-- numerator = Rx revenue − acquisition cost, denominator = Rx revenue.
SELECT c.location_id, p.product_id,
       CAST(c.submitted_at AS date) AS period_date,
       SUM(COALESCE(c.reimbursed_amount, 0) + COALESCE(c.patient_amount, 0) - p.acquisition_cost) AS numerator,
       SUM(COALESCE(c.reimbursed_amount, 0) + COALESCE(c.patient_amount, 0))                      AS denominator,
       COUNT(*)                     AS sample_size
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')
  AND c.submitted_at >= :from AND c.submitted_at < :to
GROUP BY 1, 2, 3
```

`packs/pharmacy/daab/metrics/rx_revenue.sql`:
```sql
-- key: pharmacy.rx_revenue
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: currency
-- aggregation: additive
-- sample_size: paid claims
-- requires: [claim, prescription]
-- lookback_days: 14
-- Rules: PH-MARGIN-001, forecast input. Rx revenue = reimbursed (payer) + patient amount,
-- valid prescriptions only (status not reversed/cancelled), rejected claims excluded.
SELECT c.location_id, p.product_id,
       CAST(c.submitted_at AS date)                                            AS period_date,
       SUM(COALESCE(c.reimbursed_amount, 0) + COALESCE(c.patient_amount, 0))   AS value,
       COUNT(*)                                                                AS sample_size
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')
  AND c.submitted_at >= :from AND c.submitted_at < :to
GROUP BY 1, 2, 3
```

`packs/pharmacy/daab/evidence/claim_rejection_rate.sql`:
```sql
-- key: pharmacy.claim_rejection_rate
SELECT claim_id, submitted_at, prescription_id, payer, billed_amount, is_rejected, rejection_code, _source_ref
FROM claim
WHERE submitted_at >= :from AND submitted_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(location_id, '') = :dim_location_id)
ORDER BY is_rejected DESC, submitted_at, claim_id
```

`packs/pharmacy/daab/evidence/reimbursement_gap.sql`:
```sql
-- key: pharmacy.reimbursement_gap
SELECT c.claim_id, c.submitted_at, p.prescription_id, p.status, p.quantity, p.acquisition_cost,
       c.reimbursed_amount, c.patient_amount, c._source_ref
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')
  AND c.submitted_at >= :from AND c.submitted_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(c.location_id, '') = :dim_location_id)
  AND (:dim_product_id IS NULL OR COALESCE(p.product_id, '') = :dim_product_id)
ORDER BY c.submitted_at, c.claim_id
```

`packs/pharmacy/daab/evidence/rx_cost.sql`:
```sql
-- key: pharmacy.rx_cost
SELECT c.claim_id, c.submitted_at, p.prescription_id, p.status, p.quantity, p.acquisition_cost,
       c.reimbursed_amount, c.patient_amount, c._source_ref
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')
  AND c.submitted_at >= :from AND c.submitted_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(c.location_id, '') = :dim_location_id)
  AND (:dim_product_id IS NULL OR COALESCE(p.product_id, '') = :dim_product_id)
ORDER BY c.submitted_at, c.claim_id
```

`packs/pharmacy/daab/evidence/rx_margin.sql`:
```sql
-- key: pharmacy.rx_margin
SELECT c.claim_id, c.submitted_at, p.prescription_id, p.status, p.quantity, p.acquisition_cost,
       c.reimbursed_amount, c.patient_amount, c._source_ref
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')
  AND c.submitted_at >= :from AND c.submitted_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(c.location_id, '') = :dim_location_id)
  AND (:dim_product_id IS NULL OR COALESCE(p.product_id, '') = :dim_product_id)
ORDER BY c.submitted_at, c.claim_id
```

`packs/pharmacy/daab/evidence/rx_margin_pct.sql`:
```sql
-- key: pharmacy.rx_margin_pct
SELECT c.claim_id, c.submitted_at, p.prescription_id, p.status, p.quantity, p.acquisition_cost,
       c.reimbursed_amount, c.patient_amount, c._source_ref
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')
  AND c.submitted_at >= :from AND c.submitted_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(c.location_id, '') = :dim_location_id)
  AND (:dim_product_id IS NULL OR COALESCE(p.product_id, '') = :dim_product_id)
ORDER BY c.submitted_at, c.claim_id
```

`packs/pharmacy/daab/evidence/rx_revenue.sql`:
```sql
-- key: pharmacy.rx_revenue
SELECT c.claim_id, c.submitted_at, p.prescription_id, p.status,
       c.reimbursed_amount, c.patient_amount, c._source_ref
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')
  AND c.submitted_at >= :from AND c.submitted_at < :to
  AND (:dim_location_id IS NULL OR COALESCE(c.location_id, '') = :dim_location_id)
  AND (:dim_product_id IS NULL OR COALESCE(p.product_id, '') = :dim_product_id)
ORDER BY c.submitted_at, c.claim_id
```

- [ ] **Step 3: Chạy lại check** — Expected: PASS (32 metric, 32 evidence).

- [ ] **Step 4: Commit**
```bash
git add packs/pharmacy
git commit -m "feat(packs): pharmacy extension with per-fill cost and margin metrics" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 17: Mapping Pharmacy Chain + test mọi metric trên fixture tính tay

**Files:** Create `packs/_projects/pharmacy-chain/mapping.yaml`; `ennam.kg.go/internal/intel/packtest/fixture_test.go`.

**Interfaces:** Mapping `pharmacy_demo` (data source `3c7af733-b069-4654-b98e-beb5afde588c` "Pharmacy POS DB", project `4ad7a5fa-a036-4f6a-8229-39a20af23e38`), cột kiểm tra read-only ngày 2026-10-02. Enum đã thấy trong dữ liệu: `transactions.status ∈ {Completed}`, `prescriptions.status ∈ {Cancelled, Not Collected, Picked Up, Ready, Reversed}`, `inventory_movements.movement_type ∈ {SALE, REFUND_RETURN}` (+ `RECEIPT` sau Plan A), `receipts.print_type ∈ {Original, Reprint, Gift Receipt}`. `stores` không có cột timezone ⇒ literal `'America/Chicago'`. `labor_rate` map từ `employees` (`hourly_rate: hourly_wage`, `effective_from: hire_date` — cột Plan A thêm); `inventory_movements.movement_type` có thêm `RECEIPT` (Plan A). Chưa map: `target` (Plan C thêm).

Fixture (2 cửa hàng × 2 ngày, cùng tên bảng/cột với `pharmacy_demo` + `employee_wages`, `store_targets`) và giá trị kỳ vọng nằm ngay trong test; mỗi metric là một subtest; test còn chạy evidence của từng metric và kiểm tra cột cuối là `_source_ref`.

- [ ] **Step 1: Viết test (failing)**
`internal/intel/packtest/fixture_test.go`:
```go
// Package packtest runs every metric and evidence query of the real packs
// (workspace packs/) through the real mapping of the Pharmacy Chain project on a
// tiny fixture whose expected values were computed by hand. Industry words are
// allowed here: this is a _test.go file (D10 guard excludes tests).
package packtest

import (
	"context"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	_ "github.com/lib/pq"

	"github.com/ennam/ennam-kg/internal/intel"
	"github.com/ennam/ennam-kg/internal/intel/livesource"
	"github.com/ennam/ennam-kg/internal/intel/sqlexec"
)

// packsDir is PACKS_DIR or the workspace packs/ next to ennam.kg.go.
func packsDir(t *testing.T) string {
	t.Helper()
	dir := os.Getenv("PACKS_DIR")
	if dir == "" {
		dir = filepath.Join("..", "..", "..", "..", "packs")
	}
	if _, err := os.Stat(filepath.Join(dir, "retail", "pack.yaml")); err != nil {
		t.Skipf("Skipping: packs not found at %s (set PACKS_DIR)", dir)
	}
	return dir
}

// fixtureDDL creates the subset of the pharmacy_demo schema the mapping reads
// (incl. Plan A's employees.hourly_wage and prescriptions.acquisition_cost), plus
// store_targets for the target entity (mode=file in production, Plan C).
// {{S}} is replaced by a scratch schema name.
const fixtureDDL = `
CREATE TABLE {{S}}.products (product_id text, sku text, product_name text, category text, subcategory text,
  unit_cost numeric, retail_price numeric, vendor_id text, prescription_required boolean);
INSERT INTO {{S}}.products VALUES
 ('P1','SKU1','Pain relief','OTC','Analgesic',4,10,'V1',false),
 ('P2','SKU2','Chips','Snacks','Salty',1,3,'V2',false),
 ('RX1','SKU3','Amoxicillin','Rx','Antibiotic',2,9,'V3',true);

CREATE TABLE {{S}}.transactions (transaction_id text, store_id text, employee_id text, customer_id text,
  transaction_datetime timestamp, subtotal numeric, discount_amount numeric, tax_amount numeric, status text);
INSERT INTO {{S}}.transactions VALUES
 ('T1','S1','E1','C1','2026-07-01 10:00',23,1,0,'Completed'),
 ('T2','S1','E1',NULL,'2026-07-01 15:00',10,0,0,'Completed'),
 ('T3','S2','E3','C2','2026-07-01 11:00',18,0,0,'Completed'),
 ('T4','S1','E2',NULL,'2026-07-02 09:00',6,0,0,'Completed'),
 ('T5','S1','E1','C3','2026-06-30 23:00',10,0,0,'Completed');

CREATE TABLE {{S}}.transaction_items (transaction_item_id text, transaction_id text, product_id text,
  quantity integer, unit_price numeric, unit_cost numeric, discount_amount numeric, override_applied boolean);
INSERT INTO {{S}}.transaction_items VALUES
 ('L1','T1','P1',2,10,4,1,true),
 ('L2','T1','P2',1,3,1,0,false),
 ('L3','T2','P1',1,10,4,0,false),
 ('L4','T3','P2',3,3,1,0,false),
 ('L5','T3','RX1',1,9,2,0,false),
 ('L6','T4','P2',2,3,1.5,0,false),
 ('L7','T5','P1',1,10,4,0,false);

CREATE TABLE {{S}}.refunds (refund_id text, store_id text, employee_id text, approving_manager_id text,
  original_transaction_id text, refund_datetime timestamp, refund_amount numeric,
  original_receipt_present boolean, refund_method text);
INSERT INTO {{S}}.refunds VALUES
 ('R1','S1','E1','E2','T5','2026-07-01 12:00',10,true,'Cash'),
 ('R2','S2','E3',NULL,'T5','2026-07-01 16:00',10,false,'Cash'),
 ('R3','S1','E1','E2','T1','2026-07-02 13:00',5,false,'Card');

CREATE TABLE {{S}}.receipts (receipt_id text, transaction_id text, store_id text, printed_by_employee_id text,
  printed_datetime timestamp, print_type text);
INSERT INTO {{S}}.receipts VALUES
 ('RC1','T5','S1','E1','2026-06-30 23:01','Original'),
 ('RC2','T5','S1','E1','2026-07-01 08:00','Reprint'),
 ('RC3','T1','S1','E2','2026-07-02 10:00','Reprint'),
 ('RC4','T1','S1','E1','2026-07-02 12:30','Reprint');

CREATE TABLE {{S}}.voids (void_id text, store_id text, employee_id text, void_datetime timestamp,
  void_amount numeric, stage text);
INSERT INTO {{S}}.voids VALUES ('V1','S1','E1','2026-07-01 15:05',10,'After Receipt Printed');

CREATE TABLE {{S}}.discount_overrides (override_id text, transaction_id text, store_id text, employee_id text,
  approving_manager_id text, product_id text, override_datetime timestamp, original_amount numeric,
  adjusted_amount numeric, discount_amount numeric);
INSERT INTO {{S}}.discount_overrides VALUES
 ('O1','T1','S1','E1','E2','P1','2026-07-01 10:01',10,9,1),
 ('O2','T4','S1','E2','E2','P2','2026-07-02 09:01',3,3,0);

CREATE TABLE {{S}}.cash_drawers (drawer_session_id text, store_id text, employee_id text, closed_at timestamp,
  expected_cash numeric, counted_cash numeric, no_sale_open_count integer);
INSERT INTO {{S}}.cash_drawers VALUES
 ('DR1','S1','E1','2026-07-01 21:00',100,95,3),
 ('DR2','S2','E3','2026-07-01 21:00',50,50,0),
 ('DR3','S1','E1','2026-07-02 21:00',80,81,1),
 ('DR4','S2','E3','2026-07-02 21:00',100,70,0);

CREATE TABLE {{S}}.employee_shifts (shift_id text, store_id text, employee_id text, actual_clock_in timestamp,
  actual_clock_out timestamp, scheduled_start timestamp, scheduled_end timestamp,
  regular_hours numeric, overtime_hours numeric);
INSERT INTO {{S}}.employee_shifts VALUES
 ('SH1','S1','E1','2026-07-01 08:00','2026-07-01 17:30','2026-07-01 08:00','2026-07-01 16:00',8,1.5),
 ('SH2','S2','E3','2026-07-01 09:00','2026-07-01 17:00','2026-07-01 09:00','2026-07-01 17:00',8,0),
 ('SH3','S1','E2','2026-07-02 08:00','2026-07-02 16:00','2026-07-02 08:00','2026-07-02 12:00',8,0);

CREATE TABLE {{S}}.employees (employee_id text, store_id text, role text, hire_date date, hourly_wage numeric);
INSERT INTO {{S}}.employees VALUES ('E1','S1','Cashier','2026-01-01',20), ('E2','S1','Store Manager','2026-03-01',NULL),
 ('E3','S2','Cashier','2026-01-01',18);

CREATE TABLE {{S}}.inventory_snapshots (snapshot_id text, store_id text, product_id text, snapshot_date date,
  system_quantity integer, counted_quantity integer, expired_quantity integer);
INSERT INTO {{S}}.inventory_snapshots VALUES
 ('SN1','S1','P1','2026-07-01',10,8,0),
 ('SN2','S1','P2','2026-07-01',5,6,1),
 ('SN3','S2','P1','2026-07-02',4,4,0);


CREATE TABLE {{S}}.prescriptions (prescription_id text, store_id text, product_id text, filled_datetime timestamp,
  quantity integer, status text, cash_price numeric, customer_payment numeric, insurance_payment numeric,
  acquisition_cost numeric);
INSERT INTO {{S}}.prescriptions VALUES
 ('RXA','S1','RX1','2026-07-01 09:00',10,'Picked Up',40,5,30,20),
 ('RXB','S1','RX1','2026-07-01 10:00',5,'Reversed',20,2,15,10),
 ('RXC','S2','RX1','2026-07-01 11:00',3,'Ready',12,0,0,6),
 ('RXD','S2','RX1','2026-07-02 11:00',4,'Picked Up',16,3,12,8);

CREATE TABLE {{S}}.insurance_claims (claim_id text, prescription_id text, store_id text, payer_name text,
  submitted_datetime timestamp, claim_amount numeric, approved_amount numeric, customer_amount numeric,
  claim_status text, rejection_code text);
INSERT INTO {{S}}.insurance_claims VALUES
 ('C1','RXA','S1','PayerA','2026-07-01 09:30',40,30,5,'Approved',NULL),
 ('C2','RXB','S1','PayerA','2026-07-01 10:30',20,15,2,'Approved',NULL),
 ('C3','RXC','S2','PayerB','2026-07-01 11:30',12,0,0,'Rejected','75'),
 ('C4','RXD','S2','PayerB','2026-07-02 11:30',16,12,3,'Approved',NULL);

CREATE TABLE {{S}}.store_targets (store_id text, metric_key text, period date, target_value numeric);
INSERT INTO {{S}}.store_targets VALUES
 ('S1','net_sales','2026-07-01',1000), ('S1','gross_margin_pct','2026-07-01',35), ('S2','net_sales','2026-07-01',800);
`

// expected rows per metric: "period|dim=val,dim=val|v=..|s=.." or "|n=..|d=..|s=..";
// v=nil / n=nil mean NULL. Dims are listed in the metric's dims order.
var expected = map[string][]string{
	"retail.net_sales": {
		"2026-07-01|location_id=S1,category=OTC|v=29|s=2", "2026-07-01|location_id=S1,category=Snacks|v=3|s=1",
		"2026-07-01|location_id=S2,category=Snacks|v=9|s=1", "2026-07-02|location_id=S1,category=Snacks|v=6|s=1"},
	"retail.cogs": {
		"2026-07-01|location_id=S1,category=OTC|v=12|s=2", "2026-07-01|location_id=S1,category=Snacks|v=1|s=1",
		"2026-07-01|location_id=S2,category=Snacks|v=3|s=1", "2026-07-02|location_id=S1,category=Snacks|v=3|s=1"},
	"retail.gross_margin_pct": {
		"2026-07-01|location_id=S1,category=OTC|n=17|d=29|s=2", "2026-07-01|location_id=S1,category=Snacks|n=2|d=3|s=1",
		"2026-07-01|location_id=S2,category=Snacks|n=6|d=9|s=1", "2026-07-02|location_id=S1,category=Snacks|n=3|d=6|s=1"},
	"retail.avg_ticket": {
		"2026-07-01|location_id=S1|n=32|d=2|s=2", "2026-07-01|location_id=S2|n=9|d=1|s=1", "2026-07-02|location_id=S1|n=6|d=1|s=1"},
	"retail.transactions": {
		"2026-07-01|location_id=S1|v=2|s=2", "2026-07-01|location_id=S2|v=1|s=1", "2026-07-02|location_id=S1|v=1|s=1"},
	"retail.refund_rate": {
		"2026-07-01|location_id=S1,employee_id=E1|n=10|d=32|s=1", "2026-07-01|location_id=S2,employee_id=E3|n=10|d=18|s=1",
		"2026-07-02|location_id=S1,employee_id=E1|n=5|d=0|s=1", "2026-07-02|location_id=S1,employee_id=E2|n=0|d=6|s=0"},
	"retail.refund_count": {
		"2026-07-01|location_id=S1,employee_id=E1,approver_id=E2|v=1|s=1", "2026-07-01|location_id=S2,employee_id=E3,approver_id=|v=1|s=1",
		"2026-07-02|location_id=S1,employee_id=E1,approver_id=E2|v=1|s=1"},
	"retail.no_receipt_refund_pct": {
		"2026-07-01|location_id=S1,employee_id=E1|n=0|d=1|s=1", "2026-07-01|location_id=S2,employee_id=E3|n=1|d=1|s=1",
		"2026-07-02|location_id=S1,employee_id=E1|n=1|d=1|s=1"},
	"retail.duplicate_refund_groups": {
		"2026-07-01|location_id=S1|v=0|s=1", "2026-07-01|location_id=S2|v=1|s=1", "2026-07-02|location_id=S1|v=0|s=1"},
	"retail.reprint_before_refund_count": {
		"2026-07-01|location_id=S1,employee_id=E1|v=1|s=1", "2026-07-01|location_id=S2,employee_id=E3|v=0|s=1",
		"2026-07-02|location_id=S1,employee_id=E1|v=0|s=1"},
	"retail.void_rate": {
		"2026-07-01|location_id=S1,employee_id=E1|n=1|d=2|s=2", "2026-07-01|location_id=S2,employee_id=E3|n=0|d=1|s=1",
		"2026-07-02|location_id=S1,employee_id=E2|n=0|d=1|s=1"},
	"retail.discount_rate": {
		"2026-07-01|location_id=S1,employee_id=E1|n=1|d=33|s=2", "2026-07-01|location_id=S2,employee_id=E3|n=0|d=9|s=1",
		"2026-07-02|location_id=S1,employee_id=E2|n=0|d=6|s=1"},
	"retail.override_rate": {
		"2026-07-01|location_id=S1,employee_id=E1|n=1|d=3|s=3", "2026-07-01|location_id=S2,employee_id=E3|n=0|d=2|s=2",
		"2026-07-02|location_id=S1,employee_id=E2|n=1|d=1|s=1"},
	"retail.manual_override_count": {
		"2026-07-01|location_id=S1,employee_id=E1,approver_id=E2|v=1|s=1", "2026-07-02|location_id=S1,employee_id=E2,approver_id=E2|v=1|s=1"},
	"retail.cash_variance": {
		"2026-07-01|location_id=S1,employee_id=E1|v=-5|s=1", "2026-07-01|location_id=S2,employee_id=E3|v=0|s=1",
		"2026-07-02|location_id=S1,employee_id=E1|v=1|s=1", "2026-07-02|location_id=S2,employee_id=E3|v=-30|s=1"},
	"retail.cash_shortage_count": { // shortage row first: the evidence check uses the first row's dims
		"2026-07-02|location_id=S2,employee_id=E3|v=1|s=1", "2026-07-01|location_id=S1,employee_id=E1|v=0|s=1",
		"2026-07-01|location_id=S2,employee_id=E3|v=0|s=1", "2026-07-02|location_id=S1,employee_id=E1|v=0|s=1"},
	"retail.no_sale_rate": {
		"2026-07-01|location_id=S1,employee_id=E1|n=3|d=5|s=5", "2026-07-01|location_id=S2,employee_id=E3|n=0|d=1|s=1",
		"2026-07-02|location_id=S1,employee_id=E1|n=1|d=1|s=1", "2026-07-02|location_id=S1,employee_id=E2|n=0|d=1|s=1",
		"2026-07-02|location_id=S2,employee_id=E3|n=0|d=0|s=0"},
	"retail.labor_hours": {
		"2026-07-01|location_id=S1,employee_id=E1|v=9.5|s=1", "2026-07-01|location_id=S2,employee_id=E3|v=8|s=1",
		"2026-07-02|location_id=S1,employee_id=E2|v=8|s=1"},
	"retail.overtime_hours": {
		"2026-07-01|location_id=S1,employee_id=E1|v=1.5|s=1", "2026-07-01|location_id=S2,employee_id=E3|v=0|s=1",
		"2026-07-02|location_id=S1,employee_id=E2|v=0|s=1"},
	"retail.labor_cost": {
		"2026-07-01|location_id=S1|v=190|s=1", "2026-07-01|location_id=S2|v=144|s=1", "2026-07-02|location_id=S1|v=nil|s=0"},
	"retail.labor_cost_pct": {
		"2026-07-01|location_id=S1|n=190|d=32|s=1", "2026-07-01|location_id=S2|n=144|d=18|s=1", "2026-07-02|location_id=S1|n=nil|d=6|s=0"},
	"retail.inventory_variance_value": {
		"2026-07-01|location_id=S1,product_id=P1|v=-8|s=1", "2026-07-01|location_id=S1,product_id=P2|v=1|s=1",
		"2026-07-02|location_id=S2,product_id=P1|v=0|s=1"},
	"retail.days_of_cover": {
		"2026-07-01|location_id=S1,product_id=P1|v=224|s=1", "2026-07-01|location_id=S1,product_id=P2|v=nil|s=1",
		"2026-07-02|location_id=S2,product_id=P1|v=nil|s=1"},
	"retail.avg_unit_cost": {
		"2026-07-01|location_id=S1,product_id=P1|n=12|d=3|s=2", "2026-07-01|location_id=S1,product_id=P2|n=1|d=1|s=1",
		"2026-07-01|location_id=S2,product_id=P2|n=3|d=3|s=1", "2026-07-01|location_id=S2,product_id=RX1|n=2|d=1|s=1",
		"2026-07-02|location_id=S1,product_id=P2|n=3|d=2|s=1"},
	"retail.target_net_sales":        {"2026-07-01|location_id=S1|v=1000|s=1", "2026-07-01|location_id=S2|v=800|s=1"},
	"retail.target_gross_margin_pct": {"2026-07-01|location_id=S1|v=35|s=1"},
	"pharmacy.claim_rejection_rate": {
		"2026-07-01|location_id=S1|n=0|d=2|s=2", "2026-07-01|location_id=S2|n=1|d=1|s=1", "2026-07-02|location_id=S2|n=0|d=1|s=1"},
	"pharmacy.rx_revenue": {"2026-07-01|location_id=S1,product_id=RX1|v=35|s=1", "2026-07-02|location_id=S2,product_id=RX1|v=15|s=1"},
	"pharmacy.rx_cost":    {"2026-07-01|location_id=S1,product_id=RX1|v=20|s=1", "2026-07-02|location_id=S2,product_id=RX1|v=8|s=1"},
	"pharmacy.rx_margin":  {"2026-07-01|location_id=S1,product_id=RX1|v=15|s=1", "2026-07-02|location_id=S2,product_id=RX1|v=7|s=1"},
	"pharmacy.rx_margin_pct": {
		"2026-07-01|location_id=S1,product_id=RX1|n=15|d=35|s=1", "2026-07-02|location_id=S2,product_id=RX1|n=7|d=15|s=1"},
	"pharmacy.reimbursement_gap": {"2026-07-01|location_id=S1,product_id=RX1|v=10|s=1", "2026-07-02|location_id=S2,product_id=RX1|v=4|s=1"},
}

// extraMappings cover entities the demo database has no table for (target is a
// file dataset in production — Plan C; metric SQL is the same in every mode).
func extraMappings(projectID string) []intel.Mapping {
	return []intel.Mapping{
		{ProjectID: projectID, Entity: "target", Mode: intel.ModeLive, Status: intel.MappingApproved,
			Spec: intel.MappingSpec{From: "store_targets", Fields: map[string]string{
				"location_id": "store_id", "metric_key": "metric_key", "period": "period", "value": "target_value"}}},
	}
}

type fixture struct {
	db     *sql.DB
	schema string
	exec   *sqlexec.Executor
}

func newFixture(t *testing.T) *fixture {
	t.Helper()
	url := os.Getenv("KG_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("Skipping integration test: KG_TEST_DATABASE_URL not set")
	}
	db, err := sql.Open("postgres", url)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	f := &fixture{db: db, schema: fmt.Sprintf("packfx_%d", time.Now().UnixNano()), exec: sqlexec.New(db, 0)}
	if _, err := db.Exec(`CREATE SCHEMA ` + f.schema); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _, _ = db.Exec(`DROP SCHEMA ` + f.schema + ` CASCADE`) })
	if _, err := db.Exec(strings.ReplaceAll(fixtureDDL, "{{S}}", f.schema)); err != nil {
		t.Fatalf("fixture: %v", err)
	}
	return f
}

// table builds the live SourceTable of a fixture table from information_schema.
func (f *fixture) table(t *testing.T, name string) intel.SourceTable {
	t.Helper()
	rows, err := f.db.Query(`SELECT column_name, data_type FROM information_schema.columns
		WHERE table_schema = $1 AND table_name = $2 ORDER BY ordinal_position`, f.schema, name)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var cols []intel.SourceColumn
	for rows.Next() {
		var c intel.SourceColumn
		if err := rows.Scan(&c.Name, &c.DataType); err != nil {
			t.Fatal(err)
		}
		cols = append(cols, c)
	}
	return &livesource.Table{Schema: f.schema, Name: name, Cols: cols}
}

type wantRow struct {
	value, num, den *float64
	isNull, numNull bool
	ratio           bool
	sample          int
}

func parseWant(t *testing.T, s string) (string, wantRow) {
	t.Helper()
	parts := strings.Split(s, "|")
	key := parts[0] + "|" + parts[1]
	var w wantRow
	for _, p := range parts[2:] {
		k, v, _ := strings.Cut(p, "=")
		if v == "nil" {
			switch k {
			case "v":
				w.isNull = true
			case "n":
				w.numNull, w.ratio = true, true
			}
			continue
		}
		var f float64
		if _, err := fmt.Sscanf(v, "%g", &f); err != nil {
			t.Fatalf("bad expectation %q", s)
		}
		switch k {
		case "v":
			w.value = &f
		case "n":
			w.num, w.ratio = &f, true
		case "d":
			w.den = &f
		case "s":
			w.sample = int(f)
		}
	}
	return key, w
}

func near(a *float64, b float64) bool { return a != nil && *a-b < 1e-9 && b-*a < 1e-9 }

// TestPackMetrics_HandComputedFixture compiles every metric of retail+pharmacy
// with packs/_projects/pharmacy-chain/mapping.yaml and checks each result row.
func TestPackMetrics_HandComputedFixture(t *testing.T) {
	dir := packsDir(t)
	f := newFixture(t)
	reg, err := intel.LoadRegistry(dir)
	if err != nil {
		t.Fatal(err)
	}
	cat, err := reg.Effective([]string{"retail", "pharmacy"})
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(filepath.Join(dir, "_projects", "pharmacy-chain", "mapping.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	mf, err := intel.ParseMappingFile(raw)
	if err != nil {
		t.Fatal(err)
	}
	comp := &intel.Compiler{Dialect: intel.Postgres{}, Catalog: cat}
	byEntity := map[string]intel.Mapping{}
	for _, m := range append(mf.Mappings, extraMappings(mf.ProjectID)...) {
		byEntity[m.Entity] = m
	}
	ctes := map[string]string{}
	cte := func(entity string) string {
		if c, ok := ctes[entity]; ok {
			return c
		}
		m, ok := byEntity[entity]
		if !ok {
			t.Fatalf("no mapping for %s", entity)
		}
		c, err := comp.EntityCTE(entity, m, f.table(t, m.Spec.From), "America/Chicago")
		if err != nil {
			t.Fatalf("CTE %s: %v", entity, err)
		}
		ctes[entity] = c
		return c
	}

	if len(expected) != len(cat.Metrics) {
		t.Errorf("expectations for %d metrics, packs define %d — every metric needs a fixture", len(expected), len(cat.Metrics))
	}
	for _, key := range cat.MetricKeys() {
		t.Run(key, func(t *testing.T) {
			def := cat.Metrics[key]
			for _, r := range def.Requires {
				cte(r)
			}
			compiled, err := comp.CompileMetric(def, ctes)
			if err != nil {
				t.Fatal(err)
			}
			from, to := "2026-07-01", "2026-07-03"
			if def.Grain == intel.GrainMonth {
				to = "2026-08-01"
			}
			args, _ := compiled.Args(map[string]any{"from": from, "to": to})
			res, err := f.exec.Query(context.Background(), compiled.SQL, args, 1000)
			if err != nil {
				t.Fatalf("run: %v\n%s", err, compiled.SQL)
			}
			got := map[string]wantRow{}
			idx := map[string]int{}
			for i, c := range res.Columns {
				idx[c] = i
			}
			for _, row := range res.Rows {
				var dims []string
				for _, d := range def.Dims {
					v := row[idx[d]]
					if v == nil {
						v = ""
					}
					dims = append(dims, fmt.Sprintf("%s=%v", d, v))
				}
				pd := row[idx["period_date"]].(time.Time).Format("2006-01-02")
				k := pd + "|" + strings.Join(dims, ",")
				w := wantRow{sample: int(toF(t, row[idx["sample_size"]]))}
				if def.Aggregation == intel.AggRatio {
					d := toF(t, row[idx["denominator"]])
					w.den, w.ratio = &d, true
					if row[idx["numerator"]] == nil {
						w.numNull = true
					} else {
						n := toF(t, row[idx["numerator"]])
						w.num = &n
					}
				} else if row[idx["value"]] == nil {
					w.isNull = true
				} else {
					v := toF(t, row[idx["value"]])
					w.value = &v
				}
				got[k] = w
			}
			want := expected[key]
			if len(got) != len(want) {
				t.Errorf("rows = %d, want %d: got %+v", len(got), len(want), got)
			}
			for _, s := range want {
				k, w := parseWant(t, s)
				g, ok := got[k]
				switch {
				case !ok:
					t.Errorf("missing row %s", k)
				case g.sample != w.sample:
					t.Errorf("%s sample_size = %d, want %d", k, g.sample, w.sample)
				case w.isNull && !g.isNull:
					t.Errorf("%s value must be NULL", k)
				case w.value != nil && !near(g.value, *w.value):
					t.Errorf("%s value = %v, want %v", k, deref(g.value), *w.value)
				case w.numNull && !g.numNull:
					t.Errorf("%s numerator must be NULL", k)
				case w.ratio && w.numNull && !near(g.den, *w.den):
					t.Errorf("%s denominator = %v, want %v", k, deref(g.den), *w.den)
				case w.ratio && !w.numNull && (!near(g.num, *w.num) || !near(g.den, *w.den)):
					t.Errorf("%s num/den = %v/%v, want %v/%v", k, deref(g.num), deref(g.den), *w.num, *w.den)
				}
			}

			ev, ok := cat.Evidence[key]
			if !ok {
				t.Fatal("no evidence query")
			}
			ec, err := comp.CompileEvidence(ev, def.Requires, ctes)
			if err != nil {
				t.Fatal(err)
			}
			k0, _ := parseWant(t, want[0])
			vals := map[string]any{"from": from, "to": to, "_limit": 50, "_offset": 0}
			for _, kv := range strings.Split(strings.SplitN(k0, "|", 2)[1], ",") {
				d, v, _ := strings.Cut(kv, "=")
				vals["dim_"+d] = v
			}
			eargs, err := ec.Args(vals)
			if err != nil {
				t.Fatal(err)
			}
			er, err := f.exec.Query(context.Background(), ec.SQL, eargs, 50)
			if err != nil {
				t.Fatalf("evidence: %v\n%s", err, ec.SQL)
			}
			if er.Columns[len(er.Columns)-1] != intel.SourceRefField {
				t.Errorf("evidence must end with %s, columns = %v", intel.SourceRefField, er.Columns)
			}
			if len(def.Dims) > 1 && len(er.Rows) == 0 {
				t.Errorf("evidence with all dims of the first expected row returned nothing")
			}
		})
	}
}

// TestPackEvidence_SubsetOfDims: a finding rolled up to fewer dims than the metric
// (e.g. location only on a location × category metric) must see the source rows
// across the omitted dim; all dims keeps the narrow result.
func TestPackEvidence_SubsetOfDims(t *testing.T) {
	dir := packsDir(t)
	f := newFixture(t)
	reg, err := intel.LoadRegistry(dir)
	if err != nil {
		t.Fatal(err)
	}
	cat, err := reg.Effective([]string{"retail"})
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(filepath.Join(dir, "_projects", "pharmacy-chain", "mapping.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	mf, err := intel.ParseMappingFile(raw)
	if err != nil {
		t.Fatal(err)
	}
	comp := &intel.Compiler{Dialect: intel.Postgres{}, Catalog: cat}
	def := cat.Metrics["retail.net_sales"]
	ctes := map[string]string{}
	for _, m := range mf.Mappings {
		if contains(def.Requires, m.Entity) {
			c, err := comp.EntityCTE(m.Entity, m, f.table(t, m.Spec.From), "America/Chicago")
			if err != nil {
				t.Fatal(err)
			}
			ctes[m.Entity] = c
		}
	}
	ec, err := comp.CompileEvidence(cat.Evidence["retail.net_sales"], def.Requires, ctes)
	if err != nil {
		t.Fatal(err)
	}
	rows := func(category any) int {
		args, err := ec.Args(map[string]any{"from": "2026-07-01", "to": "2026-07-02", "_limit": 50, "_offset": 0,
			"dim_location_id": "S1", "dim_category": category})
		if err != nil {
			t.Fatal(err)
		}
		res, err := f.exec.Query(context.Background(), ec.SQL, args, 50)
		if err != nil {
			t.Fatal(err)
		}
		return len(res.Rows)
	}
	if n := rows(nil); n != 3 { // L1, L3 (OTC) + L2 (Snacks)
		t.Fatalf("location only: %d rows, want 3 across categories", n)
	}
	if n := rows("OTC"); n != 2 {
		t.Fatalf("location + category: %d rows, want 2", n)
	}
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

func toF(t *testing.T, v any) float64 {
	t.Helper()
	switch x := v.(type) {
	case int64:
		return float64(x)
	case float64:
		return x
	case string:
		var f float64
		if _, err := fmt.Sscanf(x, "%g", &f); err != nil {
			t.Fatalf("not a number: %q", x)
		}
		return f
	}
	t.Fatalf("unexpected %T", v)
	return 0
}

func deref(p *float64) any {
	if p == nil {
		return nil
	}
	return *p
}
```

- [ ] **Step 2: Chạy — FAIL**
```bash
cd ennam.kg.go && export KG_TEST_DATABASE_URL="postgres://ennam_kg:${KG_DB_PASSWORD:-ennam_kg_dev}@localhost:5433/ennam_kg?sslmode=disable"
go test -v -count=1 ./internal/intel/packtest/ 2>&1 | tail -5
```
Expected: FAIL — `open ../../../../packs/_projects/pharmacy-chain/mapping.yaml: no such file or directory`.

- [ ] **Step 3: Tạo mapping**
`packs/_projects/pharmacy-chain/mapping.yaml`:
```yaml
# Mapping of the Pharmacy Chain demo database (pharmacy_demo, read live) to the
# retail + pharmacy canonical model. Imported with:
#   kg-packs import-mapping --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 \
#     --file packs/_projects/pharmacy-chain/mapping.yaml --approve --sync-schema
# Columns verified against pharmacy_demo on 2026-10-02 (21 tables), except the
# columns Plan A adds — employees.hourly_wage and prescriptions.acquisition_cost —
# and the RECEIPT movement type (import fails loudly until Plan A has run).
# Not mapped here: target (mode=file — Plan C appends the block for dataset store_targets).
project_id: 4ad7a5fa-a036-4f6a-8229-39a20af23e38
defaults:
  mode: live
  data_source_id: 3c7af733-b069-4654-b98e-beb5afde588c   # "Pharmacy POS DB"
entities:
  location:
    from: stores
    fields:
      location_id: store_id
      name:        store_name
      region:      state
      timezone:    "'America/Chicago'"   # stores has no timezone column; timestamps are local (spec I12)
      opened_at:   opening_date
      status:      LOWER(status)
  product:
    from: products
    fields:
      product_id:   product_id
      sku:          sku
      name:         product_name
      category:     category
      subcategory:  subcategory
      unit_cost:    unit_cost
      list_price:   retail_price
      vendor_id:    vendor_id
      is_regulated: prescription_required
  employee:
    from: employees
    fields:
      employee_id: employee_id
      location_id: store_id
      role:        role
  labor_rate:            # one rate per employee, effective from hire date (Plan A: employees.hourly_wage)
    from: employees
    fields:
      employee_id:    employee_id
      effective_from: hire_date
      hourly_rate:    hourly_wage
  sale:
    from: transactions
    fields:
      sale_id:         transaction_id
      location_id:     store_id
      employee_id:     employee_id
      customer_id:     customer_id
      sold_at:         transaction_datetime
      gross_amount:    subtotal
      discount_amount: discount_amount
      tax_amount:      tax_amount
      net_amount:      subtotal - discount_amount
      status:          status
    enum_map:
      status: { Completed: completed, Voided: voided, Cancelled: cancelled }
  sale_line:
    from: transaction_items
    fields:
      sale_line_id:    transaction_item_id
      sale_id:         transaction_id
      product_id:      product_id
      quantity:        quantity
      unit_price:      unit_price
      unit_cost:       unit_cost
      discount_amount: discount_amount
      override_flag:   override_applied
  refund:
    from: refunds
    fields:
      refund_id:        refund_id
      location_id:      store_id
      employee_id:      employee_id
      approver_id:      approving_manager_id
      original_sale_id: original_transaction_id
      refunded_at:      refund_datetime
      amount:           refund_amount
      has_receipt:      original_receipt_present
      method:           refund_method
  void:
    from: voids
    fields:
      void_id:     void_id
      location_id: store_id
      employee_id: employee_id
      voided_at:   void_datetime
      amount:      void_amount
      post_tender: "stage <> 'Before Payment'"
  cash_drawer:
    from: cash_drawers
    fields:
      drawer_id:     drawer_session_id
      location_id:   store_id
      employee_id:   employee_id
      closed_at:     closed_at
      expected_cash: expected_cash
      counted_cash:  counted_cash
      no_sale_count: no_sale_open_count
  shift:
    from: employee_shifts
    fields:
      shift_id:           shift_id
      location_id:        store_id
      employee_id:        employee_id
      start_at:           actual_clock_in
      end_at:             actual_clock_out
      regular_hours:      regular_hours
      overtime_hours:     overtime_hours
  inventory_movement:
    from: inventory_movements
    fields:
      movement_id:   movement_id
      location_id:   store_id
      product_id:    product_id
      moved_at:      movement_datetime
      movement_type: movement_type
      quantity:      quantity_change
    enum_map:
      movement_type: { SALE: sale, REFUND_RETURN: return, RECEIPT: receipt }
  inventory_snapshot:
    from: inventory_snapshots
    fields:
      snapshot_id:   snapshot_id
      location_id:   store_id
      product_id:    product_id
      snapshot_date: snapshot_date
      book_qty:      system_quantity
      counted_qty:   counted_quantity
      expired_qty:   expired_quantity
  receipt_print:
    from: receipts
    fields:
      receipt_id:  receipt_id
      sale_id:     transaction_id
      location_id: store_id
      employee_id: printed_by_employee_id
      printed_at:  printed_datetime
      print_type:  print_type
    enum_map:
      print_type: { Original: original, Reprint: reprint, "Gift Receipt": gift }
  price_override:
    from: discount_overrides
    fields:
      override_id:     override_id
      sale_id:         transaction_id
      location_id:     store_id
      employee_id:     employee_id
      approver_id:     approving_manager_id
      product_id:      product_id
      overridden_at:   override_datetime
      original_amount: original_amount
      adjusted_amount: adjusted_amount
      discount_amount: discount_amount
  prescription:
    from: prescriptions
    fields:
      prescription_id: prescription_id
      location_id:     store_id
      product_id:      product_id
      filled_at:       filled_datetime
      quantity:        quantity
      status:          status
      cash_price:      cash_price
      patient_paid:    customer_payment
      payer_paid:      insurance_payment
      acquisition_cost: acquisition_cost   # column added by Plan A (per-fill cost)
    enum_map:
      status: { Received: received, Ready: ready, "Picked Up": picked_up, "Not Collected": not_collected, Reversed: reversed, Cancelled: cancelled }
  claim:
    from: insurance_claims
    fields:
      claim_id:          claim_id
      prescription_id:   prescription_id
      location_id:       store_id
      payer:             payer_name
      submitted_at:      submitted_datetime
      billed_amount:     claim_amount
      reimbursed_amount: approved_amount
      patient_amount:    customer_amount
      is_rejected:       "claim_status = 'Rejected'"
      rejection_code:    rejection_code
```

- [ ] **Step 4: Chạy — PASS, 32 subtest, 0 SKIP**
```bash
cd ennam.kg.go && export KG_TEST_DATABASE_URL="postgres://ennam_kg:${KG_DB_PASSWORD:-ennam_kg_dev}@localhost:5433/ennam_kg?sslmode=disable"
go test -v -count=1 ./internal/intel/packtest/ 2>&1 | tee /tmp/planb.out | grep -E "^(--- |ok|FAIL)"
grep -c -- '--- SKIP' /tmp/planb.out   # phải in 0 — test DB bị SKIP vẫn báo ok
```
Expected: `--- PASS: TestPackMetrics_HandComputedFixture` với 32 subtest PASS và `--- PASS: TestPackEvidence_SubsetOfDims` (evidence chỉ có `location_id` trả dòng của mọi category; đủ dims trả đúng phần hẹp); SKIP = 0. (Đã kiểm tra độ nhạy: đổi `v=29` thành `v=28` ở `retail.net_sales` làm test FAIL.)

- [ ] **Step 5: Commit (2 repo)**
```bash
git add packs/_projects/pharmacy-chain/mapping.yaml
git commit -m "feat(packs): pharmacy-chain mapping to the canonical model" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
```bash
git -C ennam.kg.go add internal/intel/packtest/fixture_test.go
git -C ennam.kg.go commit -m "test(intel): hand-computed fixture for every pack metric" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

### Task 18: Toàn bộ test + guard từ ngữ ngành

**Files:** không tạo file mới (chỉ chạy kiểm tra).

- [ ] **Step 1: Toàn bộ test package mới + bridge, có race, 0 SKIP**
```bash
cd ennam.kg.go && export KG_TEST_DATABASE_URL="postgres://ennam_kg:${KG_DB_PASSWORD:-ennam_kg_dev}@localhost:5433/ennam_kg?sslmode=disable" && export KG_TEST_DSN=$KG_TEST_DATABASE_URL   # handler tests đọc KG_TEST_DSN, mặc định :5432 là container khác
go build ./... && go vet ./internal/intel/... ./internal/bridge/ ./internal/handler/ ./cmd/...
go test -race -count=1 -v ./internal/intel/... ./cmd/kg-packs/ ./internal/bridge/ 2>&1 | tee /tmp/planb_all.out | grep -E "^(ok|FAIL)"
grep -c -- '--- SKIP' /tmp/planb_all.out
go test -count=1 ./... 2>&1 | grep -E "^FAIL" || echo "no failures"
```
Expected: mọi dòng `ok`; SKIP = 0; `no failures`.

- [ ] **Step 2: Guard từ ngữ ngành (master M3)**
```bash
./scripts/check-core-vocabulary.sh
grep -rniE 'pharmacy|prescription|reimburse|claim_rejection|\bndc\b|\bpbm\b|\bpayer\b' ennam.kg.go/cmd/kg-packs ennam.kg.go/cmd/kg-server/intel_wiring.go ennam.kg.go/internal/handler/intel_metrics.go --include='*.go' | grep -v _test.go || echo clean
```
Expected: `core vocabulary OK` và `clean`.

### Task 19: Kiểm chứng end-to-end trên stack dev (sau M1 + Plan A)

**Files:** không đổi code. Điều kiện: M1 (mount `/packs`, `PACKS_DIR`), Plan A đã thêm `prescriptions.acquisition_cost` vào `pharmacy_demo`, `KG_ENCRYPTION_KEY` có trong `.env`.

- [ ] **Step 1: Migrate + rebuild server**
```bash
cd ennam.kg.go && KG_DB_PORT=5433 go run ./cmd/kg-migrate/ up && cd .. && docker compose up -d --build kg-server
docker compose logs --tail=50 kg-server | grep -E "industry-pack metrics layer enabled|intel metric scheduler started"
```
Expected: hai dòng log, `packs=2`.

- [ ] **Step 2: Import mapping, bật pack, đặt as-of, backfill (lệnh M4)**
```bash
P=4ad7a5fa-a036-4f6a-8229-39a20af23e38
docker exec daab-server go run ./cmd/kg-packs import-mapping --file /packs/_projects/pharmacy-chain/mapping.yaml --approve --sync-schema
docker exec daab-server go run ./cmd/kg-packs install --project $P --pack retail --pack pharmacy
docker exec daab-server go run ./cmd/kg-packs set-as-of --project $P --date 2026-07-31
docker exec daab-server go run ./cmd/kg-packs run-metrics --project $P --from 2025-08-01 --to 2026-08-01 | tail -40
```
Expected: import in 16 dòng `approved`; run-metrics exit 0, `as_of` = `2026-07-31`, mọi entity `current`, mọi metric `current` trừ `retail.target_*` = `skipped` (chưa có `target` — Plan C). Nếu Plan A chưa chạy: import báo `unknown column or keyword acquisition_cost` / `hourly_wage` và **không ghi gì** — dừng, ghi vào checkpoint (không sửa mapping để lách).

- [ ] **Step 3: Đối chiếu số với ground truth**
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -c "SELECT metric_key, count(*) FROM metric_value WHERE project_id='4ad7a5fa-a036-4f6a-8229-39a20af23e38' GROUP BY 1 ORDER BY 1" -c "SELECT subject, status FROM data_status WHERE project_id='4ad7a5fa-a036-4f6a-8229-39a20af23e38' AND status <> 'current'"
KEY=${KG_API_KEY:-ennam_kg_dev_000000000000000000000000}
curl -s -X POST localhost:8082/api/v1/intel/metrics/query -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"project_id":"4ad7a5fa-a036-4f6a-8229-39a20af23e38","metric_keys":["pharmacy.claim_rejection_rate","retail.duplicate_refund_groups","retail.reprint_before_refund_count"],"from":"2026-05-01","grain":"total","group_by":[]}' | python3 -m json.tool | head -60
curl -s "localhost:8082/api/v1/intel/data-status?project_id=4ad7a5fa-a036-4f6a-8229-39a20af23e38" -H "Authorization: Bearer $KEY" | python3 -m json.tool | head -20
```
Expected: 30 metric có dòng; không có `blocked`; `as_of` = `2026-07-31`; ground truth trên dữ liệu hiện tại (đo 2026-10-02, cửa sổ tới 2026-08-01, trước khi Plan A sinh lại): claim rejection PH-004 = 15,47% (41/265), `reprint_before_refund_count` tổng = 40, `duplicate_refund_groups` tổng = 10 (12 cặp trên toàn bộ dữ liệu, 2 cặp rơi ngoài cửa sổ). Sau Plan A, đối chiếu `demo_mockdata/expected_findings.csv` mới và kịch bản PH-003 (Rx margin 20,1% → 18,0% từ 2026-07-18).

- [ ] **Step 4: MCP qua bridge**
```bash
cd ennam.kg.go && go run ./cmd/kg-bridge/ --help >/dev/null; go test -count=1 -run "TestListToolNames|TestAllToolSchemasRegistered" ./internal/bridge/
```
Expected: `ok`. (Gọi tool thật qua LAAM thuộc Plan D/M6.)

- [ ] **Step 5: Ghi KG + checkpoint** — `kg_store_task` (status done, link plan), checkpoint Serena `checkpoint/<agent>-<date>` theo CLAUDE.md; ghi rõ bước nào bị dừng (nếu có).

## Self-Review

**Độ phủ spec (phạm vi P1-live + P2):**

| Yêu cầu | Task |
|---|---|
| Loader `PACKS_DIR`, `pack.yaml` (semver, extends), canonical merge, header metric, evidence (§5, master §2.2) | 2 |
| Migrations 000088–000091 đúng master §2.3 (+ `project_intel_settings`) | 1 |
| Interface `SourceTable`/resolver cho Plan C; `mode=live` hiện thực | 3, 7 |
| Compiler CTE, enum, timezone, `_source_ref`, `:from/:to/:dim_x` → `$n` (Postgres, có lớp dialect) | 3, 5 |
| Validator biểu thức (allow-list, cấm `;`/subquery/comment/hàm lạ), quote định danh, bảng/cột phải có trong schema đã sync | 4, 5, 7, 14 |
| Runner: read-only, 30s, `Truncated` = lỗi + `blocked`, cap riêng, chunk backfill, lookback, upsert `dims_hash`, kiểm tra cột kết quả theo aggregation, `data_status`, sync schema trước khi chạy + mapping `broken`, version tăng ⇒ tính lại | 7, 8, 9 |
| Scheduler ticker + advisory lock + giờ chạy cấu hình + trigger sau upload | 9, 10 |
| CLI import-mapping/install/run-metrics (+ set-as-of theo master mới) | 14 |
| 4 endpoint + 4 MCP tool đúng §2.4, `dims_filter` trong SQL, gộp theo aggregation, `versions_in_series`, evidence LIMIT/OFFSET ≤ 12s, `as_of` | 11, 12, 13 |
| Gỡ 2 tool chết + cập nhật mọi assert | 13 |
| Pack retail/pharmacy đủ metric §6.4 + metric đếm cho rule §7.3 + mapping `pharmacy_demo` | 15, 16, 17 |
| Mỗi metric có test fixture tính tay (integration DB) | 17 |
| Không từ ngữ ngành trong core (D10) | 18 |

**Nhất quán kiểu:** `intel.Mapping`/`MappingSpec` dùng chung store–compiler–CLI; `intelstore.MetricRow` là đầu ra của `engine.ParseResult` và đầu vào của `ReplaceMetricRows`; `intelstore.ProjectSettings` đi qua `ResolveTimezone`/`AsOf` ở runner, scheduler, query; `engine.RunnerConfig` dùng cho cả runner và query (`NewQueryService(..., cfg, ...)`); `intel.RunTrigger` được `*engine.Scheduler` hiện thực (assert `var _ intel.RunTrigger = (*Scheduler)(nil)`). Thứ tự task đã được kiểm tra bằng cách build/test từng nhóm file theo đúng thứ tự task trên bản copy.

**Không có trong plan (cố ý):** `mode=file` (Plan C), `landed` (sau beta), UI mapping, LLM đề xuất mapping (chỉ có lệnh import YAML), row-level security trong DAAB (spec §12b/§14.4).

## Sai khác so với Plan D (hợp đồng metric)

Đối chiếu bảng "Hợp đồng metric cần từ Plan B" trong `docs/superpowers/plans/2026-10-02-pi-D-laam-engine.md`. Key, aggregation, unit, dims khớp cho **mọi** metric Plan D liệt kê; sai khác còn lại:

| Metric | Plan D | Plan B | Lý do / việc cần làm |
|---|---|---|---|
| `retail.avg_unit_cost` | tổng giá vốn / số đơn vị từ lịch sử giá vốn (dòng nhập/bán) | từ dòng bán (`sale_line.unit_cost`); sample = số dòng bán | Chưa có entity nhập hàng/lịch sử giá vốn; khi Plan A thêm `product_costs`/receipt có thể thêm entity + version 2 metric |
| `retail.no_sale_rate` | mở két không bán / tổng lần mở két | mẫu số ≈ lần mở không bán + số giao dịch hoàn tất | Nguồn không có log từng lần mở két |
| `retail.override_rate` | override / số dòng bán | mẫu số gồm mọi dòng bán (cả dòng sản phẩm `is_regulated`) | — |
| `retail.labor_cost_pct` | chi phí lương / net sales | mẫu số = `sale.net_amount`; tử số NULL khi không ca nào có đơn giá; không phụ trội overtime | Cần `employees.hourly_wage` (Plan A); một đơn giá/nhân viên từ ngày vào làm |
| `retail.days_of_cover` | snapshot (không nêu công thức) | tồn (đếm, nếu không có thì sổ sách) × 28 / số đơn vị bán 28 ngày trước lần kiểm; NULL khi không bán | Cửa sổ 28 ngày là lựa chọn của plan này — cần Plan D xác nhận |
| `retail.refund_rate` | giá trị refund / net sales trước refund | như Plan D; net sales = `sale.net_amount` (gồm dòng Rx trong POS) | Tỉ lệ theo số lượng (Refund Count Rate) không làm — Plan D không dùng |
| `retail.overtime_hours` | additive, số ca | như Plan D; định nghĩa: giờ overtime khách đã ghi trên ca, không tính lại theo ngưỡng | Ngưỡng tuần thuộc rule RET-LABOR-006 (LAAM) |
| Approver (FND-004, RET-REF-005) | `retail.override_rate` cần biết người duyệt | `retail.manual_override_count` dims `[location_id, employee_id, approver_id]` + `retail.refund_count` dims `[location_id, employee_id, approver_id]` (dùng `group_by: [approver_id]`) | Tỉ lệ không thể có dim người duyệt vì mẫu số (dòng bán) không có người duyệt |
| Metric thêm ngoài bảng Plan D | — | `retail.refund_count`, `retail.manual_override_count`, `retail.labor_hours`, `retail.labor_cost`, `pharmacy.rx_margin`, `pharmacy.reimbursement_gap` | Spec §6.4 danh sách tối thiểu / người duyệt; LAAM có thể bỏ qua |

## Open questions

- **Mã lỗi ngoài master §2.4.** Plan dùng thêm `invalid_request` (HTTP 400: body JSON hỏng, thiếu `project_id`, `grain` lạ, dim không thuộc metric trong `dims`/`dims_filter`, dim bị `dims_filter` giới hạn mà thiếu trong `dims`, `limit` sai), `forbidden` (403), `packs_unavailable` (503), `internal` (500). 401 của middleware Auth giữ body cũ. Cần bổ sung vào master §2.4 trước khi merge (master quy định "đổi thì sửa file này trước").
- **`project_intel_settings`** nằm trong migration 000088 (cùng `pack_install`) — master §2.3 chưa ghi DDL bảng này; cần thêm.
- **Ngưỡng độ tươi** (`METRIC_STALE_AFTER_DAYS`=3; trễ 1–2 ngày so với `as_of` = `delayed`) do plan tự đặt — request không cho số (Part 3 §3 chỉ định nghĩa chữ). Cần chốt với khách; có thể thành cấu hình theo entity.
- **Canonical bổ sung ngoài spec §6.2** (D6 — rủi ro "canonical sai từ đầu"): entity `labor_rate`, `receipt_print`, `price_override`; field `cash_drawer.no_sale_count`, `inventory_snapshot.snapshot_id`, `prescription.acquisition_cost` (required); enum `receipt_print.print_type`, `target.metric_key`. Mỗi cái ghi rule cần nó trong `canonical.yaml`. Cần review riêng.
- **Định nghĩa metric cần xác nhận** (ngoài bảng Plan D): `void_rate` mẫu số = mọi dòng sale (dữ liệu demo ghi void như sự kiện trên giao dịch đã hoàn tất); `duplicate_refund_groups` đếm mỗi refund lặp (sample = mọi refund trong ngày/cửa hàng); `gross_margin_pct`/`net_sales` loại dòng sản phẩm `is_regulated` — target margin của khách (`targets.xlsx`) phải cùng phạm vi (chỉ front-store).
- **Rule thiếu đầu vào:** RET-INV-003 cần lead time vendor (Plan A) — DAAB chỉ cung cấp `retail.days_of_cover`; RET-LABOR-001 dùng một đơn giá/nhân viên (`employees.hourly_wage` từ `hire_date`, chưa có lịch sử tăng lương); RET-SALES-006 "inventory availability"; RET-REF-002 so theo register/shift (dims chưa có); RET-DISC-004 after-hours (cần dim giờ).
- **Workspace `CLAUDE.md`** (Session Boot step 1 + bảng "When to query KG") yêu cầu agent gọi `kg_get_context` — tool này vốn 404 và nay bị gỡ khỏi bridge ⇒ cần sửa tài liệu (ngoài phạm vi plan này).
- **Sync schema trước mỗi lần chạy** gọi `SchemaSyncService.SyncSchema`, hàm này huỷ job sync đang chạy cùng data source (`prepareSyncJob` → `CancelByDataSource`). Chấp nhận được cho beta (05:00), nhưng có thể đụng sync thủ công.
- **Múi giờ theo location:** beta dùng một múi giờ cho cả project (settings > literal `location.timezone` > `METRIC_RUNNER_TIMEZONE`) để đổi cột `timestamp with time zone`; chuỗi nhiều múi giờ chưa hỗ trợ. Freshness dùng `CAST(<cột> AS date)` không đổi múi giờ.
- **Evidence khi nguồn live đã xoá kỳ cũ** trả trang rỗng; hợp đồng §2.4 chưa có trường để báo "bằng chứng không còn ở nguồn" (spec §6.5).
- **Dim NULL lưu là `""`** (vd refund không có người duyệt) — LAAM phải hiểu `""` là "không xác định".
- **Pack nạp lúc khởi động** — đổi file pack cần restart `kg-server` (CLI đọc mỗi lần chạy).
- **Version tăng khi nguồn đã xoá kỳ cũ:** `StaleSince` (MIN version) giữ các kỳ nguồn không còn ở version cũ ⇒ mỗi lần chạy lại quét lại từ kỳ đó (trả rỗng, không xoá). Đúng nhưng tốn query với lịch sử dài; nếu thành vấn đề, thêm `kg-packs` lệnh đánh dấu kỳ không tính lại được.
- **`retail.cash_shortage_count`** nhúng ngưỡng −$25 (mặc định của request RET-CASH-001) trong SQL theo yêu cầu Plan D — override ngưỡng theo khách (`rule_override` của LAAM) không áp được cho metric này; đổi ngưỡng = version mới của metric.
- **Spec §6.2** vẫn ghi "Acquisition cost = quantity × product.unit_cost"; master đã thay bằng per-fill — nên cập nhật spec. Trên `pharmacy_demo` hiện tại công thức cũ cho giá vốn 1,17 triệu so với doanh thu 72 nghìn (unit_cost là giá theo gói, không theo đơn vị).

