# Industry packs

## 2.1 Vị trí pack và cấu hình
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

## 2.2 Định dạng file pack

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

