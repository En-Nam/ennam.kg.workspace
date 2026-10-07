# Proactive Intelligence Beta — Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement each sub-plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đưa DAAB + LAAM từ hỏi-đáp sang chủ động: DAAB tính chuỗi chỉ số từ DB khách (query tại chỗ) và file upload theo Industry Pack; LAAM chạy rule/forecast/scenario, sinh finding và briefing "Good morning, Johnny", quản lý task và feedback — demo chạy trọn trên `pharmacy_demo`.

**Architecture:** Pack (YAML + SQL, thư mục `packs/`) có nửa `daab/` (canonical, metric, evidence) và nửa `laam/` (rule, forecast, scenario, glossary, roles). DAAB biên dịch mapping thành CTE + metric SQL, chạy trên DB khách hoặc bảng file, lưu `metric_value`, mở 4 MCP tool `kg_*`. LAAM đọc qua `MetricsProvider`, chạy analysis job theo lịch, lưu finding/forecast/scenario/task, LLM chỉ diễn giải số đã tính.

**Tech Stack:** Go (stdlib `net/http`, `database/sql`, golang-migrate) · Python 3.12 (uv, pytest) · NextJS 16 / React 19 (ennam.kg.next) · LAAM: Next.js + Drizzle + Vitest · PostgreSQL 16.

**Spec:** `docs/superpowers/specs/2026-09-25-industry-pack-proactive-intelligence-design.md` (rev 4). Runbook dữ liệu thật: `docs/superpowers/runbooks/2026-10-02-real-customer-data-onboarding.md`.

## Global Constraints

- LLM **không** tạo con số: mọi số do SQL (DAAB) hoặc code xác định (LAAM) tính; brief đi qua numeric grounding check.
- Core (code/schema/prompt) **không chứa từ ngữ ngành** (`pharmacy`, `claim`, `ndc`, `prescription`, `reimbursement`, `payer`, `pbm`) — chỉ xuất hiện trong `packs/` và fixture test (D10). CI grep ở Task M3.
- Tool mô tả hành động, không mô tả nghiệp vụ; beta thêm **đúng 4 tool**: `kg_get_metrics`, `kg_get_evidence`, `kg_get_data_status`, `kg_list_metrics` (D11).
- DB khách: chỉ `SELECT`/`WITH`, phiên read-only, **không DDL**; `Truncated=true` từ `source_executor` là **lỗi**, không ghi `metric_value`.
- Không gửi tin ra ngoài (email/Slack/Zalo) từ proactive engine; không tự đổi giá, đặt hàng, buộc tội nhân viên (D9).
- Ngưỡng rule lấy nguyên từ request. Mức request không cho ⇒ hoặc để trống (rule tắt `threshold_tbd`), hoặc đặt **ngưỡng tạm có đánh dấu `provisional` + ghi chú nguồn** (E11) — không bao giờ đặt số mà không đánh dấu.
- Metric `ratio` gộp kỳ bằng `SUM(numerator)/SUM(denominator)`; không bao giờ trung bình tỉ lệ ngày.
- `period_date` theo giờ địa phương location; demo `business_project.timezone = America/Chicago`.
- **As-of date**: mọi cửa sổ phân tích, độ tươi dữ liệu và mặc định `to` tính theo **`as_of`**, không theo đồng hồ hệ thống. **Quy ước: `as_of` = ngày dữ liệu cuối cùng, BAO GỒM** (demo: `2026-07-31`); cửa sổ truy vấn dùng `to = as_of + 1 ngày` (không gồm). DAAB trả `as_of` trong `kg_get_data_status`, `kg_list_metrics`, `kg_get_metrics` (mặc định = hôm qua theo múi giờ project) và **đánh giá nhãn độ tươi theo `as_of`**, không theo đồng hồ thật. LAAM: thứ tự `business_project.asOfOverride` → `as_of` của provider → hôm qua theo múi giờ.
- **Giá vốn Rx** lấy theo từng lần bán (`prescriptions.acquisition_cost`, Plan A thêm), không phải `quantity × product.unit_cost`. Phát hiện margin dùng **margin %** (ratio), không dùng tổng tiền cửa hàng (dao động ±10–18% tự nhiên).
- **`targets.xlsx`**: 1 sheet, cột `Store ID | Metric Key | Period | Target Value`; `Period` = ngày đầu tháng; target % là số 0–100.
- **Thứ tự migration**: 000088–000091 (Plan B) phải chạy trước 000092 (Plan C) trên mọi DB.
- Timeout: query metric phía Go ≤ 30s; evidence live phải xong ≤ 15s (timeout MCP của LAAM).
- DAAB dev DB ở cổng **5433** (`make db-migrate` mặc định 5432 là container khác). Test DB bị SKIP vẫn báo PASS — kiểm tra log SKIP.
- Kết quả MCP về LAAM bị stringify `{text:"<json>"}` — luôn qua `unwrapToolResult` (`LAAM/src/lib/agent/drilldown.ts:61`).
- Sub-project là **git repo lồng nhau** (`ennam.kg.go`, `ennam.kg.python`, `ennam.kg.next`, `LAAM`): commit bằng `git -C <repo>`; `packs/` và `demo_mockdata/` commit ở repo workspace.

## Review Focus

- **Backfill vượt giới hạn dòng** (metric location × product × ngày trên 12 tháng) — người dùng mong số đúng, không bị cắt âm thầm. Test: Plan B Task "runner truncation".
- **Dữ liệu đến muộn** (claim đổi Approved→Rejected sau 3 ngày) — tỉ lệ từ chối của ngày gốc phải cập nhật. Test: Plan B lookback.
- **User chỉ có PH-002** mở evidence / hỏi Ask LAAM về PH-004 — phải bị chặn. Test: Plan E scope.
- **Số trong brief khác số trong chat** cho cùng câu hỏi — phải bằng nhau vì cùng đi qua `kg_get_metrics`. Test: Plan E Ask-LAAM routing.
- **Mapping có biểu thức độc hại** (`; DROP`, subquery) từ LLM đề xuất — phải bị từ chối trước khi chạy. Test: Plan B expression validator.

---

## 1. Sub-plans và thứ tự

| Plan | File | Phase spec | Repo | Phụ thuộc |
|---|---|---|---|---|
| **M** | file này — hợp đồng chung + tích hợp cuối | — | workspace | — |
| **A** | `2026-10-02-pi-A-demo-data.md` | P0 | workspace (`demo_mockdata/`, `pharmacy_demo`) | — |
| **B** | `2026-10-02-pi-B-daab-metrics-layer.md` | P1 (live) + P2 | `ennam.kg.go`, `packs/*/daab` | M §2 |
| **C** | `2026-10-02-pi-C-daab-tabular-upload.md` | P1 (file) | `ennam.kg.next`, `ennam.kg.go`, `ennam.kg.python` | M §2, B Task "compiler" (interface `SourceTable`) |
| **D** | `2026-10-02-pi-D-laam-engine.md` | P3 + P4 | `LAAM`, `packs/*/laam` | M §2 (mock provider, không cần B chạy) |
| **E** | `2026-10-02-pi-E-laam-experience.md` | P5 + P6 | `LAAM` | D |
| **M-final** | §4 file này | P7 | tất cả | A–E |

```text
A ───────────────────────────────┐
B ──┬── C                        ├── M-final (E2E demo 14 bước)
    └───────────────┐            │
D (mock provider) ──┴── E ───────┘
```
- **Song song được ngay**: A, B, D (D dùng `FakeMetricsProvider` theo hợp đồng §2.4).
- C bắt đầu khi B xong task compiler. E bắt đầu khi D xong engine.

---

## 2. Hợp đồng chung (khoá — sub-plan không được đổi; đổi thì sửa file này trước)

### 2.1 Vị trí pack và cấu hình
- Pack ở **`packs/` tại gốc workspace** (repo workspace). Mount read-only: DAAB `kg-server` → `/packs`, LAAM `app` → `/packs`. Env `PACKS_DIR` (mặc định `/packs`; dev local: đường dẫn tuyệt đối). OD-1 (repo riêng) có thể chuyển sau — chỉ đổi mount.
- Mapping demo seed từ file `packs/_projects/pharmacy-chain/mapping.yaml` qua lệnh import (Plan B); runtime đọc từ DB DAAB (`project_mapping`).

```text
packs/
├── retail/
│   ├── pack.yaml
│   ├── daab/canonical.yaml
│   ├── daab/metrics/<name>.sql
│   ├── daab/evidence/<name>.sql
│   └── laam/{rules,forecasts,scenarios,glossary,roles}.yaml
├── pharmacy/ (cùng cấu trúc, extends retail)
└── _projects/pharmacy-chain/mapping.yaml
```
(`cards.yaml` trong spec §5.1: **hoãn** — beta dùng layout Home cố định.)

**Mở rộng đã duyệt (từ Plan D, E1–E10)** — các trường tuỳ chọn, file cũ vẫn hợp lệ:
| ID | Mở rộng |
|---|---|
| E1 | `compare: none` — ngưỡng tuyệt đối, không có `compare_value` |
| E2 | `condition` tuỳ chọn; thiếu ⇒ rule tắt với lý do `threshold_tbd`; `disabled_reason` tuỳ chọn |
| E3 | `min_sample` tuỳ chọn |
| E4 | `severity` tuỳ chọn; thiếu ⇒ severity theo impact (request Part 3 §19, cấu hình ở `scoring.yaml`) |
| E5 | `count_days: "<biểu thức theo ngày>"` ⇒ biến `days_hit` |
| E6 | `companions: [metric_key…]` — tín hiệu đi kèm cho nguyên nhân |
| E7 | `overrides: <rule_id>` — pack con ghi đè rule pack cha |
| E8 | `scenarios[].horizon_days` (mặc định 30) |
| E9 | File mới `laam/scoring.yaml`: trọng số priority, severity theo impact, Store Health Score, tham số resurfacing/confidence |
| E10 | `asOf` trong kết quả `getDataStatus()`/`listMetrics()`/`getMetrics()` (đã đưa vào §2.4–2.5) |
| E11 | Rule: `threshold_status: confirmed \| provisional` (mặc định confirmed) + `threshold_note` (bắt buộc khi provisional). Finding mang `thresholdStatus`/`thresholdNote` để UI hiện nhãn "ngưỡng tạm". `rule_override` đặt ngưỡng ⇒ `confirmed` cho phạm vi đó. **Demo:** DISC-003, CASH-004, CLAIM-001 (> 2,5 × trung bình), INV-010 (≥ $100), PH-MARGIN-001 (giảm ≥ 2 điểm %), VOID-001 min_sample 50 — đều `provisional`, chờ khách duyệt |

### 2.2 Định dạng file pack

**`pack.yaml`**
```yaml
key: pharmacy                 # [a-z][a-z0-9_]*
version: 0.1.0                # semver
extends: [retail]             # tuỳ chọn
display_name: Pharmacy
```

**`daab/canonical.yaml`** — entity pack định nghĩa hoặc mở rộng
```yaml
entities:
  claim:
    fields:
      claim_id:          { type: text, key: true }
      prescription_id:   { type: text }
      location_id:       { type: text, required: true }
      submitted_at:      { type: timestamp, required: true }
      reimbursed_amount: { type: numeric }
      patient_amount:    { type: numeric }
      is_rejected:       { type: boolean, required: true }
      rejection_code:    { type: text }
  product:                       # mở rộng entity của pack cha: chỉ thêm field
    extend: true
    fields:
      is_regulated: { type: boolean }
enums:
  prescription.status: [received, ready, picked_up, not_collected, reversed, cancelled]
```
Kiểu cho phép: `text, numeric, integer, boolean, date, timestamp`.

**`daab/metrics/<name>.sql`** — header là comment `-- key: value` liên tiếp ở đầu file:

| Header | Bắt buộc | Giá trị |
|---|---|---|
| `key` | ✅ | `<pack>.<name>` |
| `version` | ✅ | số nguyên |
| `grain` | ✅ | `day` \| `month` |
| `dims` | ✅ | `[location_id, …]` (có thể rỗng `[]`) |
| `unit` | ✅ | `currency` \| `percent` \| `count` \| `hours` \| `days` \| `ratio` |
| `aggregation` | ✅ | `additive` \| `ratio` \| `snapshot` |
| `sample_size` | ✅ | mô tả (vd `số claim`) |
| `requires` | ✅ | `[claim, prescription]` entity canonical |
| `lookback_days` | ❌ | số nguyên, mặc định 7 |

Cột kết quả bắt buộc: mọi cột trong `dims`, `period_date` (date), `sample_size` (int), và **`value`** (additive/snapshot) **hoặc** `numerator` + `denominator` (ratio). Tham số: chỉ `:from` (date, gồm) và `:to` (date, không gồm). Tham chiếu entity bằng tên trần (`FROM claim`).

**`daab/evidence/<name>.sql`** — cùng `<name>` với metric; header `-- key: <metric key>`. Tham số `:from`, `:to`, và `:dim_<dim>` cho từng dim (ví dụ `:dim_location_id`). Phải có `ORDER BY` và **không** có `LIMIT` (engine thêm `LIMIT/OFFSET`). Mọi cột trả về phải là field canonical; thêm cột `_source_ref` (text) = `'<bảng nguồn>:' || <khoá>` do compiler cung cấp qua field ảo `_source_ref` của mỗi entity.

**`laam/rules.yaml`**
```yaml
rules:
  - rule_id: RET-REF-001
    version: 1
    name: Refund rate concentration by employee
    metric: retail.refund_rate
    dims: [location_id, employee_id]
    window_days: 30
    compare: peer_average        # peer_average | baseline_same_weekday_4w | target | previous_period
    target_metric: null          # bắt buộc khi compare = target
    min_sample: 10
    condition: "value >= 2.5 * compare_value"
    severity:                    # chỉ các mức request cho; đánh giá từ cao xuống thấp
      high: "value >= 2.5 * compare_value"
    impact: "(value - compare_value) * denominator"   # tuỳ chọn; biến: value, compare_value, numerator, denominator, sample_size
    impact_unit: currency
    breakdown: []                # chiều tìm nguyên nhân
    scenario_template: null
    driver: null                 # { variable: <tên biến scenario>, expr: "<biểu thức>" }
    recommended_action: investigate   # review|investigate|compare|approve|reorder_review|price_review|vendor_review|inventory_count|transfer_review|schedule_review|request_information|monitor
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Repeated exception pattern requiring management review"
    confidence_weights: { sample: 0.4, deviation: 0.4, freshness: 0.2 }
```

**`laam/forecasts.yaml`**
```yaml
forecasts:
  - metric: retail.net_sales     # chỉ metric aggregation = additive
    dims: [location_id]
    horizons_days: [7, 30]
    season_length: 7
```

**`laam/scenarios.yaml`**
```yaml
scenarios:
  - key: pharmacy.acq_cost_change
    label: Acquisition cost change
    dims: [location_id]
    base:                         # biến = tổng dự báo horizon của metric additive
      rx_revenue: { forecast_of: pharmacy.rx_revenue }
      rx_cost:    { forecast_of: pharmacy.rx_cost }
    variables:
      cost_change_pct:          { default: 0, min: -30, max: 30 }
      reimbursement_change_pct: { default: 0, min: -30, max: 30 }
    outputs:
      margin: "rx_revenue * (1 + reimbursement_change_pct/100) - rx_cost * (1 + cost_change_pct/100)"
    primary_output: margin
    presets:
      expected:  { trend: damped }
      best:      { trend: damped, set: { reimbursement_change_pct: 3 } }
      risk:      { trend: damped, set: { cost_change_pct: 5 } }
      no_action: { trend: persist_driver }
```

**`laam/glossary.yaml`**: `terms: { <term>: { en: "...", vi: "..." } }`. **`laam/roles.yaml`**: `personas: { executive: { max_findings: 5, sections: [...] }, … }`.

### 2.3 Bảng DAAB (migrations bắt đầu từ `000088`, Plan B/C)

```sql
-- 000088_pack_install
CREATE TABLE pack_install (
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  pack_key   TEXT NOT NULL,
  version    TEXT NOT NULL,
  enabled    BOOLEAN NOT NULL DEFAULT TRUE,
  installed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, pack_key)
);
CREATE TABLE project_intel_settings (    -- cũng trong 000088
  project_id     UUID PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  as_of_override DATE,                   -- ngày dữ liệu cuối (bao gồm); NULL = hôm qua theo múi giờ
  timezone       TEXT,
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 000089_project_mapping
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
-- 000090_metric_value
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
-- 000091_data_status
CREATE TABLE data_status (
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  subject TEXT NOT NULL,                  -- 'entity:<name>' | 'metric:<key>' (runner) | 'file:<dataset>' (kết quả validate upload, Plan C)
  status TEXT NOT NULL CHECK (status IN ('current','delayed','incomplete','stale','blocked')),
  last_success_at TIMESTAMPTZ,
  period_from DATE, period_to DATE,
  issues JSONB NOT NULL DEFAULT '[]',     -- [{code, message, detail}]
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, subject)
);
-- 000092_file_tables (Plan C) — OD-2 chốt beta: dòng lưu JSONB, không tạo schema runtime
CREATE TABLE file_dataset (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,                     -- tên dataset logic, mapping tham chiếu
  columns JSONB NOT NULL,                 -- [{name, type}]
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
Mapping `mode=file` ⇒ compiler sinh CTE `SELECT (data->>'col')::<type> AS <field> … FROM file_dataset_row WHERE dataset_id = '<id>'` (Plan C cung cấp `SourceTable` cho compiler của Plan B).

### 2.4 MCP tool (DAAB bridge) — JSON

`kg_get_metrics`
```json
{"input": {"project_id":"uuid","metric_keys":["retail.net_sales"],"from":"2026-07-01","to":"2026-08-01",
           "grain":"day|week|month|total","group_by":["location_id"],"dims_filter":{"location_id":["PH-002"]}},
 "output":{"series":[{"metric_key":"retail.net_sales","unit":"currency","aggregation":"additive",
            "points":[{"period":"2026-07-01","dims":{"location_id":"PH-002"},"value":1234.5,
                       "numerator":null,"denominator":null,"sample_size":42}],
            "versions_in_series":[1]}],
           "data_status":[{"subject":"metric:retail.net_sales","status":"current","last_success_at":"…"}],
           "as_of":"2026-07-31"}}
```
`kg_get_evidence`
```json
{"input": {"project_id":"uuid","metric_key":"pharmacy.claim_rejection_rate","from":"2026-07-12","to":"2026-07-13",
           "dims":{"location_id":"PH-004"},"dims_filter":{"location_id":["PH-004"]},"limit":50,"offset":0},
 "output":{"columns":["claim_id","submitted_at","is_rejected","rejection_code","_source_ref"],
           "rows":[["C-1","2026-07-12T10:00:00",true,"75","insurance_claims:C-1"]],"has_more":true,"source_mode":"live"}}
```
`kg_get_data_status` — input `{"project_id"}` → `{"as_of":"2026-07-31","items":[{subject,status,last_success_at,period_from,period_to,issues}],"disabled_metrics":[{"metric_key","reason"}]}`.

`kg_list_metrics` — input `{"project_id"}` → `{"as_of":"2026-07-31","packs":[{"key","version"}],"metrics":[{"key","unit","aggregation","grain","dims","requires","sample_size","enabled","disabled_reason"}]}`.

Quy tắc: `dims_filter` là giao của các điều kiện `IN`; `dims_filter` nêu dim **không có** trong metric ⇒ 400 `invalid_request` (không bỏ qua — tránh nới rộng phạm vi chi nhánh). Lỗi 403 từ check quyền của route intel trả đúng `{error:{code:"forbidden"}}`; 401 từ middleware xác thực vẫn là định dạng cũ — LAAM coi `error` không phải object là `unauthorized`/`forbidden` theo HTTP status. Với `kg_get_evidence`, `dims` có thể là **tập con** dims của metric (finding gộp theo ít chiều hơn): dim không truyền = không lọc; tên dim không thuộc metric ⇒ 400 `invalid_request`. `grain=total` gộp cả khoảng. Gộp theo `aggregation` (§spec 6.4). Lỗi: `{error:{code, message}}` — 400 `unknown_metric` | `invalid_range` | `metric_disabled` | `invalid_request`; 503 `packs_unavailable`; 500 `internal`.

Route (Plan B): `kg_get_metrics` → `POST /api/v1/intel/metrics/query`; `kg_get_evidence` → `POST /api/v1/intel/evidence`; `kg_get_data_status` → `GET /api/v1/intel/data-status?project_id=`; `kg_list_metrics` → `GET /api/v1/intel/metrics?project_id=`. `project_id` luôn ở body/query, không ở path. Plan B **gỡ** 2 tool chết `kg_get_context`, `kg_get_impact_analysis` (server chưa từng có route) ⇒ bridge còn 54 route / 57 schema.

Ngưỡng độ tươi (Plan B, **chưa có trong request — chờ khách duyệt**): `current` nếu dữ liệu tới `as_of`; `delayed` nếu trễ 1–2 ngày; `stale` nếu trễ ≥ 3 ngày.

### 2.5 LAAM (Drizzle, Plan D/E)

Interface (TypeScript, `LAAM/src/lib/intel/provider/types.ts`):
```ts
export type DimsFilter = Record<string, string[]>;
export interface MetricPoint { period: string; dims: Record<string,string>; value: number|null; numerator: number|null; denominator: number|null; sampleSize: number }
export interface MetricSeries { metricKey: string; unit: string; aggregation: 'additive'|'ratio'|'snapshot'; points: MetricPoint[]; versionsInSeries: number[] }
export interface DataStatusItem { subject: string; status: 'current'|'delayed'|'incomplete'|'stale'|'blocked'; lastSuccessAt: string|null; issues: {code:string;message:string}[] }
export interface MetricCatalogItem { key: string; unit: string; aggregation: 'additive'|'ratio'|'snapshot'; grain: 'day'|'month'; dims: string[]; requires: string[]; enabled: boolean; disabledReason: string|null }
export interface EvidencePage { columns: string[]; rows: unknown[][]; hasMore: boolean; sourceMode: 'live'|'file'|'landed' }
export interface MetricsProvider {
  listMetrics(): Promise<{ asOf: string; packs: {key:string;version:string}[]; metrics: MetricCatalogItem[] }>;
  getMetrics(q: { metricKeys: string[]; from: string; to: string; grain: 'day'|'week'|'month'|'total'; groupBy?: string[]; dimsFilter?: DimsFilter }): Promise<{ asOf: string; series: MetricSeries[]; dataStatus: DataStatusItem[] }>;
  getEvidence(q: { metricKey: string; from: string; to: string; dims: Record<string,string>; dimsFilter?: DimsFilter; limit: number; offset: number }): Promise<EvidencePage>;
  getDataStatus(): Promise<{ asOf: string; items: DataStatusItem[]; disabledMetrics: {metricKey:string;reason:string}[] }>;
}
```
Bảng mới: `business_project`, `user_scope`, `analysis_job`, `analysis_run`, `finding`, `finding_event`, `forecast_run`, `scenario_run`, `task`, `feedback`, `rule_override` (cột theo spec §7.4, §7.2, §5.3; Plan D định nghĩa chi tiết Drizzle, Plan E dùng). Thư mục code mới: `LAAM/src/lib/intel/` (core trung tính ngành).

---

## 3. Task của master plan (làm trước khi các sub-plan bắt đầu)

### Task M1: Khung `packs/` + mount
**Files:** Create `packs/retail/pack.yaml`, `packs/pharmacy/pack.yaml`, `packs/README.md`; Modify `docker-compose.yml` (service `kg-server`: thêm volume `./packs:/packs:ro`, env `PACKS_DIR=/packs`), `LAAM/docker-compose.yml` (service `app`: volume `../packs:/packs:ro`, env `PACKS_DIR=/packs`).

- [ ] **Step 1:** Tạo `packs/retail/pack.yaml`:
```yaml
key: retail
version: 0.1.0
display_name: Retail
```
- [ ] **Step 2:** Tạo `packs/pharmacy/pack.yaml`:
```yaml
key: pharmacy
version: 0.1.0
extends: [retail]
display_name: Pharmacy
```
- [ ] **Step 3:** Tạo `packs/README.md` tóm tắt §2.1–2.2 (copy nguyên định dạng file).
- [ ] **Step 4:** Thêm mount + env vào 2 file compose như trên. Thêm `PACKS_DIR=../packs` vào `LAAM/.env.example` (và `LAAM/.env` local) cho dev server chạy trên host (Playwright `webServer` của Plan E chạy `npm run dev` ngoài docker); `ennam.kg.go` dev ngoài docker dùng `PACKS_DIR=../packs` tương tự.
- [ ] **Step 5:** Kiểm tra: `docker compose config | grep -n "/packs"` → thấy volume ở `kg-server`; `docker compose -f LAAM/docker-compose.yml config | grep -n "/packs"` → thấy ở `app`.
- [ ] **Step 6:** Commit (workspace + LAAM):
```bash
git add packs docker-compose.yml && git commit -m "feat(packs): scaffold industry packs and mount into DAAB"
git -C LAAM add docker-compose.yml .env.example && git -C LAAM commit -m "chore(docker): mount industry packs read-only"
```

### Task M2: Tick sidecar cho LAAM
**Files:** Modify `LAAM/docker-compose.yml`.
- [ ] **Step 1:** Thêm service:
```yaml
  tick:
    image: curlimages/curl:8.10.1
    restart: unless-stopped
    depends_on: [app]
    environment:
      TICK_SECRET: ${WORKFLOW_TICK_SECRET:?WORKFLOW_TICK_SECRET must be set (tick-auth only accepts localhost without it)}
    entrypoint: ["/bin/sh","-c","while true; do curl -fsS -X POST -H \"x-workflow-tick-secret: $$TICK_SECRET\" http://app:3000/api/workflows/tick >/dev/null || true; sleep 60; done"]
```
- [ ] **Step 2:** Header là `x-workflow-tick-secret` (`LAAM/src/lib/workflow/tick-auth.ts:46` chỉ đọc header này). Đối chiếu tên env `WORKFLOW_TICK_SECRET` và cổng nội bộ của service `app`; sửa cho khớp.
- [ ] **Step 3:** `docker compose -f LAAM/docker-compose.yml up -d tick && docker compose -f LAAM/docker-compose.yml logs --tail=20 app | grep -i tick` → thấy request tick 200.
- [ ] **Step 4:** Commit `git -C LAAM add docker-compose.yml && git -C LAAM commit -m "chore(docker): add tick sidecar for schedules"` (không dùng `-am`: LAAM có thể đang có file dirty khác).

### Task M3: CI guard "core không chứa từ ngữ ngành"
**Files:** Create `scripts/check-core-vocabulary.sh` (workspace).
- [ ] **Step 1:** Viết script:
```bash
#!/usr/bin/env bash
set -euo pipefail
WORDS='pharmacy|prescription|reimburse|claim_rejection|\bndc\b|\bpbm\b|\bpayer\b'
CANDIDATES=(ennam.kg.go/internal/intel ennam.kg.go/internal/intelstore LAAM/src/lib/intel "LAAM/src/app/(app)/home" LAAM/src/components/intel LAAM/src/app/api/intel)
PATHS=()
for p in "${CANDIDATES[@]}"; do [ -d "$p" ] && PATHS+=("$p"); done
if [ ${#PATHS[@]} -eq 0 ]; then echo "core vocabulary: SKIP (no core dirs yet)"; exit 0; fi
set +e
hits=$(grep -rniE "$WORDS" "${PATHS[@]}" --include='*.go' --include='*.ts' --include='*.tsx')
rc=$?
set -e
if [ $rc -ge 2 ]; then echo "grep failed (rc=$rc)"; exit 2; fi
hits=$(printf '%s\n' "$hits" | grep -vE '_test\.go:|\.test\.tsx?:|/testdata/|/fixtures/' || true)
if [ -n "$hits" ]; then echo "Industry vocabulary in core:"; echo "$hits"; exit 1; fi
echo "core vocabulary OK (${#PATHS[@]} dirs)"
```
- [ ] **Step 2:** `chmod +x scripts/check-core-vocabulary.sh && ./scripts/check-core-vocabulary.sh` → lúc này in `SKIP (no core dirs yet)` (thư mục chưa tồn tại — **không** để danh sách rỗng chạy `grep -r`, vì BSD grep sẽ quét thư mục hiện tại). Kiểm tra nhánh lỗi: tạo thư mục tạm `/tmp/vc/LAAM/src/lib/intel` chứa file `x.ts` có chữ `pharmacy`, chạy script từ `/tmp/vc` → exit 1. Script được chạy lại ở cuối Plan B, D, E.
- [ ] **Step 3:** Commit `git add scripts/check-core-vocabulary.sh && git commit -m "ci: guard industry vocabulary out of core"`.

---

## 4. M-final: Tích hợp và demo end-to-end (P7)

Chạy sau khi A–E xong.

### Task M4: Cài pack + mapping cho project Pharmacy Chain
> Mọi lệnh `kg-packs` chạy **trong container** vì `/packs` chỉ có ở đó: `docker exec -w /app daab-server go run ./cmd/kg-packs <subcommand> …` (dev image golang có mount source). Dưới đây viết tắt `kg-packs` = lệnh đầy đủ này.

- [ ] **Step 1:** Import mapping: lệnh do Plan B cung cấp (`go run ./cmd/kg-packs import-mapping --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --file /packs/_projects/pharmacy-chain/mapping.yaml --approve`).
- [ ] **Step 2:** Bật pack: `kg-packs install --project … --pack retail --pack pharmacy`.
- [ ] **Step 3:** Đặt as-of demo (`kg-packs set-as-of --project … --date 2026-07-31`), rồi chạy backfill: `kg-packs run-metrics --project … --from 2025-08-01 --to 2026-08-01`. Kiểm tra `SELECT metric_key, count(*) FROM metric_value GROUP BY 1` đủ mọi metric pack; `data_status` không có `blocked`.
- [ ] **Step 4:** Upload `demo_mockdata/targets.xlsx` qua Knowledge Sources, chọn "Dữ liệu bảng" (Plan C), dataset `store_targets`. (sau khi đặt as-of, để lần chạy do upload kích hoạt dùng đúng as-of). Kiểm tra `retail.target_*` có dòng 2026-07-01 với `source_mode=file`.

### Task M5: Ground truth
- [ ] **Step 1:** Tạo `business_project` + `user_scope` (Johnny = executive, quản lý PH-002 = store_manager `[PH-002]`) bằng seed script của Plan D.
- [ ] **Step 2:** Trigger analysis run thủ công (`POST /api/intel/analysis/run` của Plan D).
- [ ] **Step 3:** So finding với `demo_mockdata/expected_findings.csv` bằng script Plan A `scripts/check-expected-findings.ts`: mọi dòng ✅ trong bảng độ phủ (spec §7.3) phải xuất hiện; không có finding `critical` ngoài danh sách. Expected: `PASS n/n`.

### Task M6: E2E 14 bước (Playwright)

> Chạy trên DB vừa seed lại (Plan A reload + Plan D seed + M4/M5), vì mỗi lần chạy tạo thêm task. Finding margin dùng là PH-MARGIN-001 (ngưỡng tạm, có nhãn "Ngưỡng tạm" — chấp nhận trong demo).
**Files:** Create `LAAM/e2e/proactive-demo.spec.ts`.
- [ ] **Step 1:** Viết test theo request Part 2 §15:
```ts
import { test, expect } from '@playwright/test';
test('proactive pharmacy demo end-to-end', async ({ page }) => {
  await page.goto('/login'); await page.fill('[name=email]', process.env.E2E_EXEC_EMAIL!); await page.fill('[name=password]', process.env.E2E_EXEC_PASSWORD!); await page.click('button[type=submit]');
  await expect(page.getByRole('heading', { name: /Good (morning|afternoon|evening), Johnny/ })).toBeVisible();
  await expect(page.getByTestId('data-status')).toContainText(/Updated/);
  const cards = page.getByTestId('finding-card'); await expect(cards).toHaveCount(await cards.count()); expect(await cards.count()).toBeGreaterThanOrEqual(3);
  await page.getByTestId('finding-card').filter({ hasText: 'PH-003' }).filter({ hasText: /margin/i }).first().click(); // PH-MARGIN-001 (kịch bản margin cài ở Plan A, có scenario_template)
  await expect(page.getByTestId('contributing-factors')).toBeVisible();
  await expect(page.getByTestId('forecast-30d')).toBeVisible();
  await expect(page.getByTestId('scenario-table').getByRole('row')).toHaveCount(5); // header + 4 preset
  await page.getByRole('button', { name: /evidence/i }).click(); await expect(page.getByTestId('evidence-table').getByRole('row').nth(1)).toBeVisible();
  await page.getByRole('button', { name: /assign/i }).click(); await page.getByLabel(/owner/i).selectOption({ index: 1 }); await page.getByRole('button', { name: /create task/i }).click();
  await expect(page.getByTestId('task-status')).toHaveText(/assigned/i);
  await page.getByRole('button', { name: /approve/i }).click(); await expect(page.getByTestId('finding-status')).toHaveText(/assigned|monitoring/i);
});
test('store manager sees only own store', async ({ page }) => {
  await page.goto('/login'); await page.fill('[name=email]', process.env.E2E_PH002_EMAIL!); await page.fill('[name=password]', process.env.E2E_PH002_PASSWORD!); await page.click('button[type=submit]');
  await expect(page.getByTestId('finding-card').filter({ hasText: 'PH-004' })).toHaveCount(0);
});
```
- [ ] **Step 2:** Chạy `cd LAAM && npx playwright test e2e/proactive-demo.spec.ts` → PASS cả 2 test. Sửa selector theo `data-testid` mà Plan E định nghĩa (Plan E phải dùng đúng các `data-testid` ở trên).
- [ ] **Step 3:** Chụp màn hình Home ở 375/1024/1440 (rule web/testing) — lưu `docs/superpowers/test-results/2026-10-proactive-home-*.png`.
- [ ] **Step 4:** Commit `git -C LAAM add e2e/proactive-demo.spec.ts && git -C LAAM commit -m "test(e2e): proactive pharmacy demo flow"`.

### Task M7: Đối chiếu 11 tiêu chí
- [ ] Điền bảng 11 tiêu chí (spec §1) với bằng chứng (lệnh/test/ảnh) vào `docs/superpowers/test-results/2026-10-proactive-beta-criteria.md`. Tiêu chí nào chưa đạt ghi rõ lý do — không được ghi "đạt" nếu có bước bị bỏ qua.
