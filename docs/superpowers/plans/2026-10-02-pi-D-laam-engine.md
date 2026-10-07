# LAAM Intelligence Engine (Plan D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây phần "phân tích + quyết định" của LAAM (spec P3 + P4): bảng dữ liệu intel, `MetricsProvider` (DAAB + Fake + wrapper phạm vi chi nhánh), pack loader, evaluator biểu thức an toàn, rule engine (so sánh, nguyên nhân, confidence, priority, dedup/cooldown, Store Health Score), forecast Holt-Winters có backtest, scenario engine 4 preset, analysis job chạy qua tick, endpoint chạy tay, seed demo, và nội dung `packs/{retail,pharmacy}/laam`.

**Architecture:** Toàn bộ code mới nằm dưới `LAAM/src/lib/intel/` và **không chứa từ ngữ ngành** (master Task M3). Engine chỉ biết interface `MetricsProvider` (master §2.5); tên tool DAAB chỉ xuất hiện trong `provider/daab.ts`. Mọi con số do code xác định tính từ dữ liệu provider; pack YAML (đọc từ `PACKS_DIR`) chứa metric key, rule, ngưỡng. Logic thuần (evaluator, rule, nguyên nhân, confidence, forecast, scenario, dedup) tách khỏi I/O; tầng DB mỏng (`store/`), test logic bằng `FakeMetricsProvider` + repo in-memory, test claim bằng fake db như `schedule.test.ts`.

**Tech Stack:** Next.js 16 App Router · TypeScript strict · Drizzle ORM 0.45 + drizzle-kit 0.31 (migration `0020`) · zod 4 · Vitest 4 (jsdom mặc định, `node:fs`/`node:crypto` dùng được) · thư viện `yaml` (thêm mới, Task 1).

**Spec:** `docs/superpowers/specs/2026-09-25-industry-pack-proactive-intelligence-design.md` (rev 4 — §2.4 I1–I5, §3 D2/D7/D9–D11, §5, §7.1–7.7, §7.11 phần data model, §12a, §12b, §13).
**Master:** `docs/superpowers/plans/2026-10-02-proactive-intelligence-master.md` (§2.2 định dạng pack và §2.5 interface TS là **khoá**).
**Request gốc (ngưỡng rule):** `~/Downloads/# DAAB + LAAM Pharmacy Update.txt` Part 3 ("Retail Analytics Rules").

## Global Constraints

- **LLM không tạo con số.** Plan D không gọi LLM ở đâu cả; mọi số (value, compare, impact, confidence, priority, forecast, scenario) tính bằng code tất định.
- **Không từ ngữ ngành trong core.** `LAAM/src/lib/intel/**` và `LAAM/src/app/api/intel/**` (kể cả comment, tên biến, ví dụ) không chứa `pharmacy|prescription|reimburse|claim_rejection|ndc|pbm|payer`. Ví dụ trong code core dùng key trung tính (`acme.revenue`, `acme.refund_rate`). Từ ngữ ngành chỉ ở `packs/`, `scripts/`, và file `*.test.ts` / `fixtures/` (master M3 loại trừ chúng). Task 23 chạy `scripts/check-core-vocabulary.sh`.
- **Hợp đồng khoá:** `provider/types.ts` chép **nguyên văn** master §2.5. Định dạng `rules.yaml`/`forecasts.yaml`/`scenarios.yaml` theo master §2.2; mọi mở rộng là **trường tuỳ chọn, cộng thêm** — file theo đúng master hôm nay vẫn load được (xem "Đề xuất bổ sung master §2.2").
- **Ngưỡng chỉ lấy từ request.** Mức request không cho ⇒ để trống, **trừ** các ngưỡng demo tạm user đã duyệt ngày 2026-10-02: chúng phải mang `threshold_status: provisional` + `threshold_note` (E11) và finding hiện badge "ngưỡng tạm". Rule thiếu cả dữ liệu lẫn ngưỡng ⇒ **không có `condition`** ⇒ tắt với lý do `threshold_tbd` (hiện trong summary). Severity tier request không cho ⇒ vẫn để trống.
- **Ratio:** gộp kỳ = `scale × Σnumerator / Σdenominator`; `scale` suy từ dữ liệu (`value / (numerator/denominator)`), không giả định "percent ⇒ ×100". Không bao giờ trung bình tỉ lệ ngày. Rule viết theo **điểm phần trăm** (`/ 100`, `compare_value - 2`) trên metric `unit: percent` ⇒ nếu scale suy ra ≠ 100 thì rule bị bỏ qua với lý do `ratio_scale_mismatch` (không chạy sai im lặng).
- **Engine luôn truyền `grain` và `groupBy` tường minh** khi gọi `getMetrics`; không dựa vào mặc định của DAAB. Engine không dùng `grain: "week"` (tuần bắt đầu thứ mấy chưa được §2.4 định nghĩa).
- **MCP:** gọi qua `execute(userId, "mcp__<slug>__<tool>", args)` export từ `@/lib/connectors` (`executeMcp` là hàm **private**); kiểm `error` / `isError` **trước**, rồi `unwrapToolResult`; `null` (text không phải JSON — kể cả bị cắt ở 200.000 ký tự) ⇒ **ném lỗi**, không coi là rỗng. Chuỗi theo ngày (history forecast, `count_days`) **chia theo location** để mỗi lần gọi nhỏ hơn giới hạn.
- **Phạm vi chi nhánh:** mọi lời gọi provider đi qua `scopeProvider` (mode `system` | `user`). Mode `user` có `locationIds` ⇒ ép `dimsFilter.location_id`; metric **không có** dim `location_id` ⇒ từ chối (`scope_denied`) vì DAAB bỏ qua filter với dim không tồn tại (master §2.4) ⇒ sẽ lộ số toàn chuỗi.
- **Không gửi gì ra ngoài** (D9): engine chỉ ghi DB. Không notification, không email.
- **Precedence override** đúng nguyên văn request/spec/master: **customer → location → category → pack default** (khớp đầu tiên thắng).
- **DB:** chỉ migration (`npx drizzle-kit generate --name intel_engine` → commit `drizzle/` → `npm run db:migrate`), không `db:push`. Mọi bảng intel dùng `projectId = business_project.id` (không phải bảng `project` — đó là phiên Claude Code, I2).
- **Code comment + commit message bằng tiếng Anh** (LAAM CLAUDE.md). Prose của plan bằng tiếng Việt.
- **Commit:** LAAM là git lồng ⇒ `git -C LAAM …`; `packs/` commit ở repo workspace.
- **Scenario engine chạy được trên trình duyệt.** `src/lib/intel/scenario/engine.ts` và **mọi module nó import (bắc cầu)** không được import `@/db`, `drizzle-orm`, `pg`, `server-only`, `next/server`, `@/auth`, `@/lib/connectors` hay module chỉ có trên Node (`node:*`, `fs`, `path`, `crypto`, `os`, `child_process`); package ngoài chỉ được `zod`. Lý do: Plan E import `computeCustom` trong client component. Pin: `scenario/browser-safe.test.ts` (Task 15).
- **Test:** `cd LAAM && npx vitest run <file>`. Báo cáo "PASS" chỉ khi không có test bị skip (AGENTS Rule 12).

## Review Focus

1. **Kết quả MCP bị cắt/không phải JSON bị coi là "không có dữ liệu"** — engine im lặng không sinh finding. Pin: `provider/daab.test.ts` › "throws bad_payload when the text is not JSON (e.g. truncated at 200k chars)" và "throws tool_error on isError before unwrapping".
2. **User chỉ có 1 chi nhánh thấy số toàn chuỗi** qua metric không có dim location, hoặc evidence của chi nhánh khác. Pin: `provider/scoped.test.ts` › "denies metrics without a location dim in user mode" và "denies evidence for a location outside scope".
3. **Tỉ lệ bị gộp sai** (trung bình tỉ lệ ngày, hoặc peer average lấy trung bình các tỉ lệ nhân viên). Pin: `provider/fake.test.ts` › "ratio total is sum(num)/sum(den), not the mean of daily ratios" và `engine/rules.test.ts` › "peer average for a ratio metric is ratio-of-sums over peers".
4. **Finding nhân đôi hoặc spam brief** khi hai run chạy cùng lúc / finding không đổi xuất hiện lại mỗi ngày. Pin: `engine/dedupe.test.ts` › "unchanged active finding is updated but not resurfaced" + unique index `finding_project_dedupe` (Task 1) + `store/memory-repo` upsert test trong `pipeline.test.ts` › "second run on identical data creates no new finding and surfaces nothing".
5. **Forecast "reliable" khi thua baseline / khoảng tin cậy rỗng giả vờ chắc chắn / scenario no-action tính driver hai lần.** Pin: `forecast/forecast.test.ts` › "falls back to the best baseline when the model loses the backtest" + "fewer than two backtest origins: no interval, not reliable, warning"; `scenario/engine.test.ts` › "no_action persists the current level once and never re-applies the measured driver" + "no_action ~ persistence of the new level; expected = damped forecast".

---

## Đề xuất bổ sung master §2.2 (cần chủ master duyệt trước khi merge Task 6)

Plan D **cần** các trường tuỳ chọn sau. Tất cả là cộng thêm; file theo master hiện tại vẫn hợp lệ.

| # | Mở rộng | Vì sao / rule cần |
|---|---|---|
| E1 | `compare: none` (không so sánh; `compare_value` không có) | Rule ngưỡng tuyệt đối: RET-REF-002 (>20%), RET-REF-004 (≥1 nhóm trùng), RET-INV-001 (≥$100), RET-CASH-001 (≤−$25), RET-INV-003, RET-LABOR-006, RET-X-REPRINT-001 |
| E2 | `condition` tuỳ chọn — thiếu ⇒ rule tắt `threshold_tbd`; `disabled_reason` tuỳ chọn | Rule request không cho ngưỡng: RET-DISC-003, RET-CASH-004, RET-LABOR-001, RET-LABOR-006, RET-INV-010, PH-CLAIM-001; RET-VOID-001 (thiếu số giao dịch tối thiểu); RET-SALES-006 (cần ranking tổng hợp) |
| E3 | `min_sample` tuỳ chọn | Request nói "minimum volume" nhưng không cho số (RET-SALES-001, RET-MARGIN-002) |
| E4 | `severity` tuỳ chọn — thiếu ⇒ severity theo impact (request Part 3 §19) | Rule chỉ có trigger, không có tên mức: RET-REF-001/002/004, RET-MARGIN-002, RET-CASH-001, RET-INV-001… |
| E5 | `count_days: "<biểu thức theo ngày>"` ⇒ biến `days_hit` | Rule "đếm số ngày vượt ngưỡng". Không rule beta nào dùng nữa: RET-CASH-001 chuyển sang `retail.cash_shortage_count` (đếm theo **lần đóng két** — đếm theo ngày làm −$30 và +$10 cùng ngày bù nhau). Giữ trong engine, có thể bỏ khỏi đề xuất nếu chủ master muốn tối giản |
| E6 | `companions: [metric_key…]` | Spec §7.3a bước 4 (tín hiệu đi kèm cho nguyên nhân) |
| E7 | `overrides: <rule_id>` | Spec §5.3 (pack con ghi đè rule pack cha) |
| E8 | `scenarios[].horizon_days` (mặc định 30) | Spec §7.7 dùng tổng 30 ngày; master không có trường horizon |
| E10 | ✅ **Đã chấp nhận ở master §2.4/§2.5**: `asOf` trong kết quả `listMetrics`/`getMetrics`/`getDataStatus` | Cửa sổ phân tích theo ngày dữ liệu cuối, không theo đồng hồ |
| E11 | `threshold_status: confirmed \| provisional` (mặc định `confirmed`) + `threshold_note` (bắt buộc khi `provisional`) | Quyết định của user 2026-10-02: bật các rule request chưa cho ngưỡng bằng **giá trị demo tạm** — RET-DISC-003, RET-CASH-004, PH-CLAIM-001, RET-INV-010, PH-MARGIN-001, `min_sample` của RET-VOID-001; finding mang trạng thái để UI hiện badge |
| E9 | File mới `laam/scoring.yaml` | Trọng số priority (request §18), severity theo impact (§19), Store Health Score (§15), tham số resurfacing/confidence — spec nói "cấu hình pack" nhưng master chưa có chỗ |

## Hợp đồng metric cần từ Plan B (DAAB)

Rule/forecast/scenario trong pack (Task 21–22) tham chiếu các metric dưới đây. Spec §6.4 chỉ liệt kê tên; bảng này chốt **ngữ nghĩa** mà engine dựa vào. Metric thiếu trong `kg_list_metrics` ⇒ rule phụ thuộc tự tắt (`metric_unknown`), không lỗi.

| Metric | aggregation | unit | dims | numerator / denominator | sample_size |
|---|---|---|---|---|---|
| `retail.net_sales` | additive | currency | location_id, category | — | số giao dịch |
| `retail.cogs` | additive | currency | location_id, category | — | số dòng bán |
| `retail.gross_margin_pct` | ratio | percent | location_id, category | lãi gộp $ / net sales $ | số giao dịch |
| `retail.transactions` | additive | count | location_id | — | số giao dịch |
| `retail.avg_ticket` | ratio | currency | location_id | net sales $ / số giao dịch | số giao dịch |
| `retail.target_net_sales` | snapshot (grain month) | currency | location_id | — (target cả tháng, file upload Plan C) | 1 |
| `retail.target_gross_margin_pct` | snapshot (grain month) | percent | location_id | — | 1 |
| `retail.inventory_variance_value` | additive | currency | location_id, product_id | — | số lần kiểm |
| `retail.days_of_cover` | snapshot | days | location_id, product_id | — (Plan B: tồn × 28 / số bán 28 ngày trước lần kiểm; NULL khi không bán) | số sản phẩm |
| `retail.refund_rate` | ratio | percent | location_id, employee_id | giá trị refund $ / net sales trước refund $ | **số refund** |
| `retail.no_receipt_refund_pct` | ratio | percent | location_id, employee_id | refund không hoá đơn / tổng refund | số refund |
| `retail.duplicate_refund_groups` | additive | count | location_id | — | số refund xét |
| `retail.discount_rate` | ratio | percent | location_id, employee_id | discount $ / gross sales $ | số giao dịch đủ điều kiện |
| `retail.override_rate` | ratio | percent | location_id, employee_id | số override / số dòng bán | số dòng bán |
| `retail.manual_override_count` | additive | count | location_id, employee_id, approver_id | — (Plan B; `approver_id = ""` = không rõ người duyệt) | số override |
| `retail.void_rate` | ratio | percent | location_id, employee_id | giao dịch void / giao dịch bắt đầu | số giao dịch bắt đầu |
| `retail.cash_variance` | additive | currency | location_id, employee_id | — (counted − expected) | số lần đóng két |
| `retail.cash_shortage_count` | additive | count | location_id, employee_id | — **số lần đóng két có chênh lệch ≤ −$25** (ngưỡng mặc định request RET-CASH-001; Plan B đang thêm) | số lần đóng két |
| `retail.no_sale_rate` | ratio | percent | location_id, employee_id | mở két không bán / tổng lần mở két | số lần mở két |
| `retail.overtime_hours` | additive | hours | location_id, employee_id | — (giờ overtime khách **đã ghi trên ca**, không tính lại theo ngưỡng tuần — Plan B) | số ca |
| `retail.labor_cost_pct` | ratio | percent | location_id | chi phí lương $ / net sales $ (DAAB **tắt** cho tới khi có cột lương) | số ca |
| `retail.avg_unit_cost` | ratio | currency | location_id, product_id | tổng giá vốn $ / số đơn vị (lịch sử giá vốn — P0 data) | số dòng nhập/bán |
| `retail.reprint_before_refund_count` | additive | count | location_id, employee_id | — | số refund |
| `pharmacy.claim_rejection_rate` | ratio | percent | location_id | claim bị từ chối / tổng claim | số claim |
| `pharmacy.rx_margin_pct` | ratio | percent | location_id, product_id | (rx_revenue − rx_cost) $ / rx_revenue $ | số đơn thuốc |
| `pharmacy.rx_revenue` | additive | currency | location_id, product_id | — | số đơn thuốc |
| `pharmacy.rx_cost` | additive | currency | location_id, product_id | — (giá vốn mua theo từng đơn thuốc) | số đơn thuốc |

Đã đối chiếu với mục "Sai khác so với Plan D" của Plan B (key/aggregation/unit/dims khớp; khác biệt định nghĩa ghi ngay trong bảng). Metric Plan B thêm mà Plan D không dùng: `retail.refund_count`, `retail.labor_hours`, `retail.labor_cost`, `pharmacy.rx_margin`, `pharmacy.reimbursement_gap`.

Ghi chú: `pharmacy.rx_margin_pct` phải là **tỉ lệ** (tử/mẫu), không phải tổng tiền — tổng tiền theo cửa hàng dao động ±10–18% ở cửa hàng không cài kịch bản (Plan A đã đo) và sẽ sinh finding giả. Kịch bản Plan A: PH-003, giá vốn 5 thuốc Rx +8% từ 2026-07-18, reimbursement đứng yên ⇒ Rx margin 20,1% → 18,0% (cửa hàng khác ±0,1 điểm); breakdown `product_id` phải đưa đúng 5 thuốc lên top.

---

## File Structure

```text
LAAM/
├── package.json                                   # Task 1: + dependency "yaml"
├── drizzle/0020_intel_engine.sql (+ meta)         # Task 1: generated
├── src/db/schema.ts                               # Task 1: 11 bảng intel
├── src/lib/intel/
│   ├── task-status.ts                             # Task 1: TASK_CLOSED_STATUSES (Plan E dùng)
│   ├── expr.ts / expr.test.ts                     # Task 2: evaluator an toàn
│   ├── provider/
│   │   ├── types.ts                               # Task 3: master §2.5 nguyên văn
│   │   ├── errors.ts                              # Task 3: ProviderError
│   │   ├── aggregate.ts / aggregate.test.ts       # Task 3: ratioScaleOf, aggregatePoints, dimsKey
│   │   ├── fake.ts / fake.test.ts                 # Task 3: FakeMetricsProvider
│   │   ├── daab.ts / daab.test.ts                 # Task 4: DaabMetricsProvider
│   │   ├── scoped.ts / scoped.test.ts             # Task 5: scopeProvider (user/system)
│   │   └── factory.ts / factory.test.ts           # Task 5: providerForProject
│   ├── time.ts / time.test.ts                     # Task 7: ngày địa phương, cửa sổ, cron theo TZ
│   ├── pack/
│   │   ├── schema.ts                              # Task 6: zod schema + type
│   │   ├── loader.ts / loader.test.ts             # Task 6: extends, merge, validate
│   │   └── packs-content.test.ts                  # Task 22: kiểm tra packs/ thật
│   ├── overrides.ts / overrides.test.ts           # Task 8: rule_override precedence
│   ├── engine/
│   │   ├── glob.ts                                # Task 10: so khớp rule_id theo glob
│   │   ├── rules.ts / rules.test.ts               # Task 9: rule engine
│   │   ├── causes.ts / causes.test.ts             # Task 10: nguyên nhân
│   │   ├── confidence.ts / confidence.test.ts     # Task 10: confidence
│   │   ├── scoring.ts / scoring.test.ts           # Task 11: severity theo impact + priority
│   │   ├── dedupe.ts / dedupe.test.ts             # Task 11: dedupe key + resurfacing
│   │   └── health.ts / health.test.ts             # Task 12: Store Health Score
│   ├── forecast/
│   │   ├── holt-winters.ts                        # Task 13
│   │   ├── forecast.ts / forecast.test.ts         # Task 13: baseline, backtest, gate, khoảng
│   │   └── service.ts / service.test.ts           # Task 14: chạy theo forecasts.yaml
│   ├── scenario/engine.ts / engine.test.ts        # Task 15
│   ├── store/repo.ts                              # Task 16: IntelRepo + drizzle impl
│   ├── testing/
│   │   ├── memory-repo.ts                         # Task 16: repo in-memory cho test
│   │   └── fixtures.ts                            # Task 3: dữ liệu tổng hợp trung tính
│   ├── pipeline.ts / pipeline.test.ts             # Task 17
│   ├── run-project.ts                             # Task 18: nối DB + provider + pack
│   └── jobs.ts / jobs.test.ts                     # Task 18: claim/execute analysis job
├── src/app/api/workflows/tick/route.ts            # Task 18: gọi tickAnalysis
├── src/app/api/intel/analysis/run/route.ts (+test)# Task 19
└── scripts/
    ├── seed-intel-demo.ts                         # Task 20
    └── intel-demo-fixture.ts                      # Task 20: dữ liệu giả cho --fake-run
packs/
├── retail/laam/{rules,forecasts,scenarios,glossary,roles,scoring}.yaml   # Task 21
└── pharmacy/laam/{rules,forecasts,scenarios,glossary,roles,scoring}.yaml # Task 22
```

Bảng `task` và `feedback` **được định nghĩa ở Plan D** (Task 1, cùng migration `0020`) để Plan E không phải tạo migration thứ hai cho cùng nhóm bảng; Plan D chỉ **đọc** `task` (tìm task quá hạn cho resurfacing). Hành vi task/feedback (API, UI, chuyển trạng thái) thuộc Plan E.

---

## Exports for plan E

Plan E chỉ dùng các export sau (chữ ký khoá bởi plan này; task tương ứng tham chiếu lại mục này):

```ts
// src/db/schema.ts (Task 1)
export const businessProjects, userScopes, analysisJobs, analysisRuns, findings, findingEvents,
  forecastRuns, scenarioRuns, tasks, feedback, ruleOverrides;
export type BusinessProject, UserScope, AnalysisJob, AnalysisRun, Finding, FindingEvent,
  ForecastRun, ScenarioRun, IntelTask, Feedback, RuleOverride;
export const FINDING_STATUSES: readonly ["new","acknowledged","assigned","monitoring","resolved","dismissed"];
export type FindingStatus = (typeof FINDING_STATUSES)[number];

// src/lib/intel/task-status.ts (Task 1)
export const TASK_CLOSED_STATUSES: readonly string[];   // task.status ∉ list && dueAt < now ⇒ overdue

// src/lib/intel/provider/types.ts (Task 3) — master §2.5 verbatim
export type DimsFilter; export interface MetricPoint, MetricSeries, DataStatusItem, MetricCatalogItem, EvidencePage, MetricsProvider;
// src/lib/intel/provider/errors.ts (Task 3)
export class ProviderError extends Error { code: "tool_error"|"bad_payload"|"scope_denied"|"not_configured" }
// src/lib/intel/provider/fake.ts (Task 3)
export class FakeMetricsProvider implements MetricsProvider { constructor(data: FakeMetricData); readonly calls: {method:string; args:unknown}[] }
// src/lib/intel/provider/scoped.ts (Task 5)
export const LOCATION_DIM = "location_id";
export type ProviderScope = { mode: "system" } | { mode: "user"; locationIds: readonly string[] };
export function scopeProvider(base: MetricsProvider, scope: ProviderScope): MetricsProvider;
// src/lib/intel/provider/factory.ts (Task 5)
export async function providerForProject(bp: BusinessProject, scope: ProviderScope, deps?: FactoryDeps): Promise<MetricsProvider>;
export async function scopeForUser(businessProjectId: string, userId: string): Promise<ProviderScope | null>; // null = no user_scope row ⇒ no access

// src/lib/intel/pack/loader.ts (Task 6)
export async function loadPacks(packsDir: string, enabled: readonly string[]): Promise<LoadedPack>;
export function packsDir(): string;          // env PACKS_DIR, default "/packs"
// src/lib/intel/pack/schema.ts (Task 6)
export type Rule, ForecastCfg, ScenarioTemplate, Glossary, Roles, Scoring, LoadedPack, Severity;
export const SEVERITY_ORDER: readonly Severity[];   // highest first
export const RECOMMENDED_ACTIONS: readonly ["review","investigate","compare","approve","reorder_review","price_review","vendor_review","inventory_count","transfer_review","schedule_review","request_information","monitor"];
export const scenarioSchema: z.ZodType<ScenarioTemplate>;   // zod strictObject + superRefine; .parse(yamlObject) -> ScenarioTemplate

// src/lib/intel/time.ts (Task 7)
export interface DateWindow { from: string; to: string }   // YYYY-MM-DD, `to` exclusive
export function addDays(date: string, n: number): string;
export function monthToDate(asOf: string): { window: DateWindow; month: DateWindow; elapsedDays: number; daysInMonth: number };

// src/lib/intel/engine/causes.ts (Task 10) — shape of finding.contributingFactors (jsonb) = CauseBreakdown[]
export interface CompanionChange { current: number | null; baseline: number | null; changePct: number | null }
export interface Factor { key: string; current: number | null; baseline: number | null; contribution: number; valueEffect: number | null; mixEffect: number | null; dim: string; share: number | null; companions: Record<string, CompanionChange> }
export interface CauseBaseline { kind: "rule_compare_windows" | "aligned_previous_period"; windows: DateWindow[]; ruleCompare: CompareMode }
export interface CauseBreakdown { dim: string; totalDelta: number; factors: Factor[]; topShare: number | null; baselineWindows: DateWindow[]; baseline?: CauseBaseline }   // baseline optional for older rows; always set by analyzeCauses

// src/lib/intel/expr.ts (Task 2)
export function evalNumber(expr: string, vars: Vars): number;
export function evalBool(expr: string, vars: Vars): boolean;

// src/lib/intel/scenario/engine.ts (Task 15) — UI recompute without LLM
export function computeScenario(tpl: ScenarioTemplate, input: ScenarioInput): ScenarioResult;
export function computeCustom(tpl: ScenarioTemplate, base: Record<string, number>, variables: Record<string, number>): CustomResult;
export class ScenarioError extends Error {}
export interface PresetResult { preset: PresetName; trend: "damped" | "persist_driver"; assumptions: Record<string, number>; changed: string[]; outputs: Record<string, number>; primary: number; deltaVsBaseline: Record<string, number>; notes: string[] }
export interface CustomResult { assumptions: Record<string, number>; outputs: Record<string, number>; primary: number; deltaVsBaseline: Record<string, number> }
export interface ScenarioInput { base: Record<string, number>; persistBase?: Record<string, number> | null; driver?: { variable: string; value: number } | null; presetSets?: Record<PresetName, Record<string, number>> }
export interface ScenarioResult { key: string; label: string; horizonDays: number; base: Record<string, number>; persistBase: Record<string, number> | null; baseline: { assumptions: Record<string, number>; outputs: Record<string, number>; primary: number }; presets: PresetResult[]; driver: { variable: string; measured: number } | null; disclaimer: string }
// no_action = persistBase (undamped model sums) with defaults; the measured driver is NEVER re-applied.

// src/lib/intel/forecast/forecast.ts (Task 13) — shape behind forecast_run rows
export interface HorizonForecast { horizonDays: number; model: ModelName; reliable: boolean; interval: boolean; point: number[]; lower: number[]; upper: number[]; sum: { point: number; lower: number | null; upper: number | null }; dampedPoint: number[]; dampedSum: number; backtest: Record<ModelName, BacktestStats> | null }
// BROWSER-SAFE: Plan E imports computeCustom in a client component — see Global Constraints + Task 15 browser-safe test.

// Shared TEST fixtures (Plan E imports in its tests; signatures locked)
// src/lib/intel/testing/fixtures.ts (Task 3)
export interface PointInit { value?: number | null; numerator?: number | null; denominator?: number | null; sampleSize?: number }
export function plusDays(date: string, n: number): string;
export function dailyPoints(from: string, days: number, dims: Record<string, string>, f: (i: number, date: string) => PointInit): MetricPoint[];
export function catalogItem(key: string, aggregation: "additive" | "ratio" | "snapshot", dims: string[], over?: Partial<MetricCatalogItem>): MetricCatalogItem;
export function currentStatus(keys: string[], status?: DataStatusItem["status"]): DataStatusItem[];
// src/lib/intel/provider/fake.ts (Task 3)
export interface FakeMetricData { catalog: MetricCatalogItem[]; packs?: {key:string;version:string}[]; points: Record<string, MetricPoint[]>; dataStatus?: DataStatusItem[]; disabledMetrics?: {metricKey:string;reason:string}[]; evidence?: Record<string, {columns:string[]; rows:unknown[][]}>; versionsInSeries?: Record<string, number[]>; asOf?: string }
export class FakeMetricsProvider implements MetricsProvider { constructor(data: FakeMetricData); readonly calls: { method: string; args: unknown }[] }
// src/lib/intel/testing/memory-repo.ts (Task 16)
export class MemoryRepo implements IntelRepo   // findings/events/forecasts/scenarios/overrides/tasks/runs public arrays/maps

// src/lib/intel/jobs.ts / run-project.ts (Task 18)
export async function runAnalysisForProject(businessProjectId: string, opts: { runId: string; now: Date }): Promise<AnalysisSummary>;
// src/lib/intel/pipeline.ts (Task 17)
export interface AnalysisSummary; export interface HealthScore (re-export from engine/health)
```

Dữ liệu Plan E đọc từ DB (hợp đồng JSON trong cột `jsonb`, định nghĩa ở Task 1 + Task 17):
- `finding.thresholdStatus` (`confirmed` | `provisional`) + `finding.thresholdNote` (text, có khi provisional) ⇒ Plan E hiện badge **"ngưỡng tạm"** cạnh finding (kèm tooltip là `thresholdNote`). Không ảnh hưởng confidence/priority.
- `finding.contributingFactors` = `CauseBreakdown[]`; mỗi phần tử có `baseline` (`kind: rule_compare_windows | aligned_previous_period`, `windows`, `ruleCompare`) ⇒ UI ghi rõ "so với kỳ trước" khi rule so target/peer.
- `scenario_run.result` = `ScenarioResult` (có `persistBase`; `driver = { variable, measured }` chỉ để hiển thị — no_action **không** áp lại driver). Khi user chỉnh biến, gọi `computeCustom(template, result.base, values)` (base damped).
- `forecast_run`: `lower`/`upper` = `[]` và `sum.lower`/`sum.upper` = `null` khi `sum.interval = false` (< 2 gốc backtest, cảnh báo `insufficient_backtest`/`no_backtest`) ⇒ UI không vẽ dải tin cậy.
- `finding.evidenceRefs` = `{ metricKey, from, to, dims }` ⇒ gọi `provider.getEvidence({ ...evidenceRefs, dimsFilter?, limit, offset })` qua `scopeProvider` mode user.
- `finding.locationIds` = danh sách location liên quan; `[]` = finding cấp chuỗi ⇒ chỉ user không giới hạn chi nhánh thấy.
- `finding.briefEligible = false` khi freshness = 0 (dữ liệu `incomplete/stale/blocked`) ⇒ không đưa vào brief.
- `finding.lastSurfacedAt` + `surfaceReason` ⇒ finding được "đưa lên brief" ở run gần nhất.
- `analysis_run.summary.healthScores` = `HealthScore[]`; `scenario_run.result` = `ScenarioResult`; `forecast_run.*` = `ForecastOutput` (Task 13).

**Cột `finding` mà checker của Plan A (`scripts/check-expected-findings.ts`) đọc — giữ ổn định:** bảng `finding`, cột camelCase có dấu ngoặc kép như mọi bảng LAAM: `"ruleId"` (text), `dims` (jsonb, ví dụ `{"location_id":"PH-004"}` hoặc `{"location_id":"PH-001","employee_id":"EMP-0006"}` — `location_id` luôn là **chuỗi**, finding nhiều chi nhánh được tách theo từng chi nhánh hoặc liệt kê ở `"locationIds"`), `severity` (text thường: `critical|high|medium|warning|low`), `"projectId"` (= `business_project.id`, demo: `bp-pharmacy-chain-demo`), `"locationIds"` (text[]), `status`. Đổi tên/kiểu các cột này phải báo Plan A.

---
## Tasks

### Task 1: Dependency `yaml` + 11 bảng intel (Drizzle) + migration 0020

**Files:**
- Modify: `LAAM/package.json`, `LAAM/package-lock.json` (npm install)
- Modify: `LAAM/src/db/schema.ts` (append cuối file)
- Create: `LAAM/src/lib/intel/task-status.ts`
- Create: `LAAM/src/lib/intel/schema.test.ts`
- Generated: `LAAM/drizzle/0020_intel_engine.sql`, `LAAM/drizzle/meta/0020_snapshot.json`, `LAAM/drizzle/meta/_journal.json`

**Interfaces:**
- Consumes: `users` (schema.ts:32).
- Produces: xem "Exports for plan E" → `src/db/schema.ts`, `task-status.ts`.

- [ ] **Step 1: Thêm dependency YAML**

```bash
cd LAAM && npm install yaml@^2.6.0
```
Expected: `package.json` có `"yaml": "^2.6.0"` trong `dependencies` (thư viện tự có type, không cần `@types`). `js-yaml` hiện chỉ có mặt gián tiếp qua eslint — không dùng.

- [ ] **Step 2: Viết test thất bại** — `LAAM/src/lib/intel/schema.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { getTableConfig } from "drizzle-orm/pg-core";
import {
  businessProjects, userScopes, analysisJobs, analysisRuns, findings, findingEvents,
  forecastRuns, scenarioRuns, tasks, feedback, ruleOverrides, FINDING_STATUSES,
} from "@/db/schema";
import { TASK_CLOSED_STATUSES } from "./task-status";

// Why: the dedupe guarantees of the engine (one finding per rule+dims per project, one run
// per job slot) live in the DB, not only in code — two concurrent runs must not duplicate.
describe("intel schema", () => {
  test("finding has a unique (projectId, dedupeKey) constraint", () => {
    const cfg = getTableConfig(findings);
    const uniques = cfg.uniqueConstraints.map((u) => u.columns.map((c) => c.name));
    expect(uniques).toContainEqual(["projectId", "dedupeKey"]);
  });

  test("analysis_run has a unique (jobId, scheduledFor) slot", () => {
    const cfg = getTableConfig(analysisRuns);
    const uniques = cfg.uniqueConstraints.map((u) => u.columns.map((c) => c.name));
    expect(uniques).toContainEqual(["jobId", "scheduledFor"]);
  });

  test("user_scope primary key is (businessProjectId, userId)", () => {
    const cfg = getTableConfig(userScopes);
    expect(cfg.primaryKeys[0].columns.map((c) => c.name)).toEqual(["businessProjectId", "userId"]);
  });

  test("rule_override is unique per (projectId, targetKey, scopeKey)", () => {
    const cfg = getTableConfig(ruleOverrides);
    const uniques = cfg.uniqueConstraints.map((u) => u.columns.map((c) => c.name));
    expect(uniques).toContainEqual(["projectId", "targetKey", "scopeKey"]);
  });

  test("all eleven intel tables exist with the agreed SQL names", () => {
    const names = [businessProjects, userScopes, analysisJobs, analysisRuns, findings, findingEvents,
      forecastRuns, scenarioRuns, tasks, feedback, ruleOverrides].map((t) => getTableConfig(t).name);
    expect(names).toEqual(["business_project", "user_scope", "analysis_job", "analysis_run", "finding",
      "finding_event", "forecast_run", "scenario_run", "task", "feedback", "rule_override"]);
  });

  test("finding carries the threshold status for a provisional-threshold badge (E11)", () => {
    const cols = getTableConfig(findings).columns.map((c) => c.name);
    expect(cols).toEqual(expect.arrayContaining(["thresholdStatus", "thresholdNote"]));
  });

  test("finding statuses and closed task statuses are the shared vocabulary", () => {
    expect(FINDING_STATUSES).toEqual(["new", "acknowledged", "assigned", "monitoring", "resolved", "dismissed"]);
    expect(TASK_CLOSED_STATUSES).toEqual(["completed", "rejected", "dismissed", "cancelled"]);
  });
});
```

- [ ] **Step 3: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/schema.test.ts
```
Expected: FAIL — `businessProjects` (và các bảng khác) không được export từ `@/db/schema`; `./task-status` không tồn tại.

- [ ] **Step 4: Thêm bảng vào cuối `LAAM/src/db/schema.ts`** (các import `sql`, `pgTable`, `text`, `integer`, `doublePrecision`, `jsonb`, `timestamp`, `primaryKey`, `unique`, `boolean`, `index` đã có ở đầu file)

```ts
// ---------------------------------------------------------------------------
// Proactive intelligence (intel). Industry-neutral: metric keys, rule ids and thresholds
// are DATA from packs, never code. Every `projectId` below is business_project.id — NOT
// the `project` table (that one is a Claude Code session cwd, see spec §2.4 I2).
// Numbers are doublePrecision (JS numbers end-to-end, same as costUsd above).
// ---------------------------------------------------------------------------

export const FINDING_STATUSES = ["new", "acknowledged", "assigned", "monitoring", "resolved", "dismissed"] as const;
export type FindingStatus = (typeof FINDING_STATUSES)[number];

// One business project <-> one metrics source (one DAAB project). ownerUserId is the identity
// system jobs call MCP as (MCP config is per user, spec §2.4 I4) — restrict delete so a job
// never silently loses its identity.
export const businessProjects = pgTable("business_project", {
  id: text("id").primaryKey().$defaultFn(() => crypto.randomUUID()),
  name: text("name").notNull(),
  metricsProvider: text("metricsProvider").notNull().default("daab"), // "daab" is the only value in beta
  daabProjectId: text("daabProjectId"),
  mcpConnectorSlug: text("mcpConnectorSlug"),
  ownerUserId: text("ownerUserId").notNull().references(() => users.id, { onDelete: "restrict" }),
  timezone: text("timezone").notNull().default("UTC"),
  localeDefault: text("localeDefault").notNull().default("en"),
  // YYYY-MM-DD. Pins the analysis date (last complete data day) when the data ends before
  // "yesterday" — e.g. demo data ending 2026-07-31. NULL = yesterday in `timezone`.
  asOfOverride: text("asOfOverride"),
  createdAt: timestamp("createdAt", { mode: "date" }).notNull().defaultNow(),
  updatedAt: timestamp("updatedAt", { mode: "date" }).notNull().defaultNow(),
});

// LAAM has no per-project membership (spec §2.4 I5). No row = no access to the project.
// locationIds empty = every location (e.g. an executive).
export const userScopes = pgTable(
  "user_scope",
  {
    businessProjectId: text("businessProjectId").notNull().references(() => businessProjects.id, { onDelete: "cascade" }),
    userId: text("userId").notNull().references(() => users.id, { onDelete: "cascade" }),
    persona: text("persona").notNull(), // key of a persona in the pack's roles.yaml
    locationIds: text("locationIds").array().notNull().default(sql`'{}'::text[]`),
    createdAt: timestamp("createdAt", { mode: "date" }).notNull().defaultNow(),
    updatedAt: timestamp("updatedAt", { mode: "date" }).notNull().defaultNow(),
  },
  (t) => [primaryKey({ columns: [t.businessProjectId, t.userId] })],
);

// Own schedule table: workflow_schedule.workflowId is NOT NULL so analysis cannot reuse it (I1).
export const analysisJobs = pgTable("analysis_job", {
  id: text("id").primaryKey().$defaultFn(() => crypto.randomUUID()),
  businessProjectId: text("businessProjectId").notNull().references(() => businessProjects.id, { onDelete: "cascade" }),
  kind: text("kind").notNull().default("daily"),
  cron: text("cron").notNull(), // 5-field, evaluated in `timezone`
  timezone: text("timezone").notNull(),
  nextRunAt: timestamp("nextRunAt", { mode: "date" }),
  lastRunAt: timestamp("lastRunAt", { mode: "date" }),
  enabled: boolean("enabled").notNull().default(true),
  lastError: text("lastError"),
  consecutiveErrors: integer("consecutiveErrors").notNull().default(0),
  createdAt: timestamp("createdAt", { mode: "date" }).notNull().defaultNow(),
  updatedAt: timestamp("updatedAt", { mode: "date" }).notNull().defaultNow(),
});

// unique(jobId, scheduledFor) dedupes racing tick pokes for the same slot (same pattern as
// workflow_run). Manual runs have jobId NULL — they are protected by finding's unique key.
export const analysisRuns = pgTable(
  "analysis_run",
  {
    id: text("id").primaryKey().$defaultFn(() => crypto.randomUUID()),
    jobId: text("jobId").references(() => analysisJobs.id, { onDelete: "set null" }),
    businessProjectId: text("businessProjectId").notNull().references(() => businessProjects.id, { onDelete: "cascade" }),
    trigger: text("trigger").notNull(), // schedule | manual
    scheduledFor: timestamp("scheduledFor", { mode: "date" }),
    status: text("status").notNull().default("queued"), // queued | running | succeeded | failed
    startedAt: timestamp("startedAt", { mode: "date" }),
    finishedAt: timestamp("finishedAt", { mode: "date" }),
    error: text("error"),
    summary: jsonb("summary"),
    createdAt: timestamp("createdAt", { mode: "date" }).notNull().defaultNow(),
  },
  (t) => [
    unique("analysis_run_job_slot").on(t.jobId, t.scheduledFor),
    index("analysis_run_project_created_idx").on(t.businessProjectId, t.createdAt),
  ],
);

export const findings = pgTable(
  "finding",
  {
    id: text("id").primaryKey().$defaultFn(() => crypto.randomUUID()),
    projectId: text("projectId").notNull().references(() => businessProjects.id, { onDelete: "cascade" }),
    ruleId: text("ruleId").notNull(),
    ruleVersion: integer("ruleVersion").notNull(),
    packVersion: text("packVersion").notNull(),
    metricKey: text("metricKey").notNull(),
    dims: jsonb("dims").$type<Record<string, string>>().notNull(),
    // Locations this finding touches ([] = chain-level). Plan E filters visibility on it.
    locationIds: text("locationIds").array().notNull().default(sql`'{}'::text[]`),
    currentValue: doublePrecision("currentValue").notNull(),
    expectedValue: doublePrecision("expectedValue"),
    variance: doublePrecision("variance"),
    variancePct: doublePrecision("variancePct"),
    comparison: jsonb("comparison").notNull(),
    estimatedImpact: doublePrecision("estimatedImpact"),
    impactUnit: text("impactUnit"),
    severity: text("severity").notNull(),
    severityReason: text("severityReason").notNull(),
    confidence: doublePrecision("confidence").notNull(),
    confidenceReason: jsonb("confidenceReason").notNull(),
    priorityScore: doublePrecision("priorityScore").notNull(),
    priorityComponents: jsonb("priorityComponents").notNull(),
    contributingFactors: jsonb("contributingFactors").notNull().default(sql`'[]'::jsonb`),
    recommendedAction: text("recommendedAction").notNull(),
    defaultOwnerRole: text("defaultOwnerRole").notNull(),
    wording: text("wording").notNull(),
    evidenceRefs: jsonb("evidenceRefs").notNull(),
    dataStatusSnapshot: jsonb("dataStatusSnapshot").notNull().default(sql`'[]'::jsonb`),
    briefEligible: boolean("briefEligible").notNull().default(true),
    // E11: "provisional" = the rule ran on a demo default the request does not give (UI badge).
    thresholdStatus: text("thresholdStatus").$type<"confirmed" | "provisional">().notNull().default("confirmed"),
    thresholdNote: text("thresholdNote"),
    sampleSize: integer("sampleSize").notNull().default(0),
    status: text("status").$type<FindingStatus>().notNull().default("new"),
    statusChangedAt: timestamp("statusChangedAt", { mode: "date" }).notNull().defaultNow(),
    dismissReason: text("dismissReason"),
    dedupeKey: text("dedupeKey").notNull(),
    occurrences: integer("occurrences").notNull().default(1),
    firstSeenAt: timestamp("firstSeenAt", { mode: "date" }).notNull().defaultNow(),
    lastSeenAt: timestamp("lastSeenAt", { mode: "date" }).notNull().defaultNow(),
    lastSurfacedAt: timestamp("lastSurfacedAt", { mode: "date" }),
    surfaceReason: text("surfaceReason"),
    lastRunId: text("lastRunId").references(() => analysisRuns.id, { onDelete: "set null" }),
    createdAt: timestamp("createdAt", { mode: "date" }).notNull().defaultNow(),
    updatedAt: timestamp("updatedAt", { mode: "date" }).notNull().defaultNow(),
  },
  (t) => [
    unique("finding_project_dedupe").on(t.projectId, t.dedupeKey),
    index("finding_project_status_priority_idx").on(t.projectId, t.status, t.priorityScore),
  ],
);

export const findingEvents = pgTable(
  "finding_event",
  {
    id: text("id").primaryKey().$defaultFn(() => crypto.randomUUID()),
    findingId: text("findingId").notNull().references(() => findings.id, { onDelete: "cascade" }),
    type: text("type").notNull(), // created | updated | resurfaced | reopened | (Plan E adds status changes)
    payload: jsonb("payload"),
    actor: text("actor").notNull(), // "system" or a user id
    at: timestamp("at", { mode: "date" }).notNull().defaultNow(),
  },
  (t) => [index("finding_event_finding_at_idx").on(t.findingId, t.at)],
);

export const forecastRuns = pgTable(
  "forecast_run",
  {
    id: text("id").primaryKey().$defaultFn(() => crypto.randomUUID()),
    projectId: text("projectId").notNull().references(() => businessProjects.id, { onDelete: "cascade" }),
    runId: text("runId").references(() => analysisRuns.id, { onDelete: "set null" }),
    metricKey: text("metricKey").notNull(),
    dims: jsonb("dims").$type<Record<string, string>>().notNull(),
    horizonDays: integer("horizonDays").notNull(),
    status: text("status").notNull(), // ok | insufficient_history
    label: text("label"), // normal | low_confidence | null
    model: text("model"),
    modelVersion: text("modelVersion").notNull(),
    baselineModel: text("baselineModel"),
    reliable: boolean("reliable").notNull().default(false),
    historyDays: integer("historyDays").notNull(),
    point: jsonb("point").$type<number[]>().notNull(),
    lower: jsonb("lower").$type<number[]>().notNull(),
    upper: jsonb("upper").$type<number[]>().notNull(),
    sum: jsonb("sum").notNull(),
    backtest: jsonb("backtest"),
    warnings: jsonb("warnings").$type<string[]>().notNull().default(sql`'[]'::jsonb`),
    startDate: text("startDate").notNull(), // first forecast day, YYYY-MM-DD (project-local)
    computedAt: timestamp("computedAt", { mode: "date" }).notNull().defaultNow(),
  },
  (t) => [index("forecast_run_project_metric_idx").on(t.projectId, t.metricKey, t.computedAt)],
);

export const scenarioRuns = pgTable("scenario_run", {
  id: text("id").primaryKey().$defaultFn(() => crypto.randomUUID()),
  projectId: text("projectId").notNull().references(() => businessProjects.id, { onDelete: "cascade" }),
  findingId: text("findingId").references(() => findings.id, { onDelete: "set null" }),
  templateKey: text("templateKey").notNull(),
  assumptions: jsonb("assumptions").notNull(),
  result: jsonb("result").notNull(),
  baseline: jsonb("baseline").notNull(),
  computedAt: timestamp("computedAt", { mode: "date" }).notNull().defaultNow(),
  createdBy: text("createdBy").notNull(), // "system" or a user id
});

// Behaviour (API/UI/state machine) belongs to Plan E; defined here so all intel tables ship in
// one migration. Plan D only reads it (an overdue task re-surfaces its finding).
export const tasks = pgTable(
  "task",
  {
    id: text("id").primaryKey().$defaultFn(() => crypto.randomUUID()),
    projectId: text("projectId").notNull().references(() => businessProjects.id, { onDelete: "cascade" }),
    findingId: text("findingId").references(() => findings.id, { onDelete: "set null" }),
    title: text("title").notNull(),
    actionType: text("actionType").notNull(),
    ownerUserId: text("ownerUserId").references(() => users.id, { onDelete: "set null" }),
    ownerRole: text("ownerRole"),
    priority: doublePrecision("priority"),
    dueAt: timestamp("dueAt", { mode: "date" }),
    approvalRequired: boolean("approvalRequired").notNull().default(false),
    status: text("status").notNull().default("open"),
    decision: text("decision"),
    decisionReason: text("decisionReason"),
    actualResult: jsonb("actualResult"),
    completedAt: timestamp("completedAt", { mode: "date" }),
    createdBy: text("createdBy").references(() => users.id, { onDelete: "set null" }),
    createdAt: timestamp("createdAt", { mode: "date" }).notNull().defaultNow(),
    updatedAt: timestamp("updatedAt", { mode: "date" }).notNull().defaultNow(),
  },
  (t) => [index("task_project_finding_idx").on(t.projectId, t.findingId)],
);

export const feedback = pgTable("feedback", {
  id: text("id").primaryKey().$defaultFn(() => crypto.randomUUID()),
  projectId: text("projectId").notNull().references(() => businessProjects.id, { onDelete: "cascade" }),
  targetType: text("targetType").notNull(), // finding | forecast | scenario | task | recommendation
  targetId: text("targetId").notNull(),
  kind: text("kind").notNull(),
  value: jsonb("value"),
  userId: text("userId").references(() => users.id, { onDelete: "set null" }),
  at: timestamp("at", { mode: "date" }).notNull().defaultNow(),
});

// targetKey: a rule id | "priority_weights" | "scenario:<key>:<preset>". scopeKey is the
// canonical form of scope ("" customer-wide, "location:<id>", "category:<name>") so the
// unique constraint works without comparing jsonb.
export const ruleOverrides = pgTable(
  "rule_override",
  {
    id: text("id").primaryKey().$defaultFn(() => crypto.randomUUID()),
    projectId: text("projectId").notNull().references(() => businessProjects.id, { onDelete: "cascade" }),
    targetKey: text("targetKey").notNull(),
    scope: jsonb("scope").$type<{ location_id?: string; category?: string }>().notNull().default(sql`'{}'::jsonb`),
    scopeKey: text("scopeKey").notNull().default(""),
    value: jsonb("value").$type<Record<string, unknown>>().notNull(),
    updatedBy: text("updatedBy").references(() => users.id, { onDelete: "set null" }),
    updatedAt: timestamp("updatedAt", { mode: "date" }).notNull().defaultNow(),
  },
  (t) => [unique("rule_override_target_scope").on(t.projectId, t.targetKey, t.scopeKey)],
);

export type BusinessProject = typeof businessProjects.$inferSelect;
export type UserScope = typeof userScopes.$inferSelect;
export type AnalysisJob = typeof analysisJobs.$inferSelect;
export type AnalysisRun = typeof analysisRuns.$inferSelect;
export type Finding = typeof findings.$inferSelect;
export type NewFinding = typeof findings.$inferInsert;
export type FindingEvent = typeof findingEvents.$inferSelect;
export type ForecastRun = typeof forecastRuns.$inferSelect;
export type ScenarioRun = typeof scenarioRuns.$inferSelect;
export type IntelTask = typeof tasks.$inferSelect;
export type Feedback = typeof feedback.$inferSelect;
export type RuleOverride = typeof ruleOverrides.$inferSelect;
```

- [ ] **Step 5: Tạo `LAAM/src/lib/intel/task-status.ts`**

```ts
// Shared task-status vocabulary. Plan D only needs "is this task still open?" to re-surface a
// finding whose task is overdue; Plan E owns the full state machine and MUST use these values
// for terminal states.
export const TASK_CLOSED_STATUSES = ["completed", "rejected", "dismissed", "cancelled"] as const;
export type TaskClosedStatus = (typeof TASK_CLOSED_STATUSES)[number];
```

- [ ] **Step 6: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/schema.test.ts
```
Expected: PASS 7/7.

- [ ] **Step 7: Sinh migration và kiểm tra SQL**

```bash
cd LAAM && npx drizzle-kit generate --name intel_engine
ls drizzle | grep 0020
grep -c "CREATE TABLE" drizzle/0020_intel_engine.sql
grep -n "finding_project_dedupe\|analysis_run_job_slot\|rule_override_target_scope\|user_scope_businessProjectId_userId_pk" drizzle/0020_intel_engine.sql
```
Expected: có file `0020_intel_engine.sql`; `11` câu `CREATE TABLE`; đủ 3 unique + 1 PK. **Không** có `DROP`/`ALTER` trên bảng cũ (nếu có ⇒ schema đã lệch snapshot 0019 — dừng, báo cáo, không commit).

- [ ] **Step 8: Áp migration vào DB dev và kiểm tra**

```bash
cd LAAM && set -a && . ./.env && set +a   # psql/tsx do not read .env; LAAM's DB is on :5500, not the :5432 fallback
npm run db:migrate
psql "$DATABASE_URL" -c "\dt" | grep -E "business_project|user_scope|analysis_job|analysis_run|finding|forecast_run|scenario_run|task|feedback|rule_override"
```
Expected: đủ 11 bảng (`DATABASE_URL` lấy từ `LAAM/.env`; theo `.env.example` cổng 5500). Nếu `echo $DATABASE_URL` rỗng hoặc trỏ :5432 ⇒ dừng — đang nhắm sai DB.

- [ ] **Step 9: Commit**

```bash
git -C LAAM add package.json package-lock.json src/db/schema.ts src/lib/intel/task-status.ts src/lib/intel/schema.test.ts drizzle/0020_intel_engine.sql drizzle/meta/0020_snapshot.json drizzle/meta/_journal.json
git -C LAAM commit -m "feat(intel): add intel tables (business project, scopes, jobs, findings, forecasts, scenarios, tasks, feedback, overrides)"
```

---

### Task 2: Evaluator biểu thức an toàn (`expr.ts`)

**Files:**
- Create: `LAAM/src/lib/intel/expr.ts`, `LAAM/src/lib/intel/expr.test.ts`
- Không sửa: `LAAM/src/lib/agent/tools/util/calc.ts` (tool chat giữ nguyên hành vi).

**Interfaces:**
- Consumes: không có (thuần). Kế thừa tokenizer của `calc.ts` (số, `+ - * / % ^`, ngoặc, unary, `-2^2 = -4`) và **mở rộng**: biến, so sánh, `and/or/not`, `true/false`, hàm `abs/min/max`.
- Produces:
```ts
export class ExprError extends Error {}
export type Value = number | boolean;
export type Vars = Readonly<Record<string, number | boolean | null | undefined>>;
export interface CompiledExpr { readonly source: string; readonly variables: ReadonlySet<string> }
export function compileExpr(source: string): CompiledExpr;
export function evaluate(expr: string | CompiledExpr, vars: Vars): Value;
export function evalNumber(expr: string | CompiledExpr, vars: Vars): number;
export function evalBool(expr: string | CompiledExpr, vars: Vars): boolean;
```

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/lib/intel/expr.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { compileExpr, evalBool, evalNumber, evaluate, ExprError } from "./expr";

// Why: rule thresholds from packs run against customer numbers. The evaluator must be exact,
// never execute code, and fail loudly (not silently false) on bad input.
describe("arithmetic matches util_calc semantics", () => {
  test.each([
    ["1 + 2 * 3", 7],
    ["(1 + 2) * 3", 9],
    ["10 / 4", 2.5],
    ["7 % 3", 1],
    ["2 ^ 3 ^ 2", 512], // right-associative
    ["-2 ^ 2", -4], // unary binds looser than ^
    ["2 ^ -2", 0.25],
    ["--3", 3],
    ["+4", 4],
    ["0.5 * 4", 2],
    [".5 + .5", 1],
  ])("%s = %d", (expr, want) => {
    expect(evalNumber(expr, {})).toBeCloseTo(want as number, 12);
  });
});

describe("variables", () => {
  test("reads numeric variables", () => {
    expect(evalNumber("value - compare_value", { value: 12, compare_value: 2 })).toBe(10);
  });
  test("missing variable is an error, not zero", () => {
    expect(() => evalNumber("value * 2", {})).toThrow(ExprError);
    expect(() => evalNumber("value * 2", { value: null })).toThrow(/missing variable "value"/);
  });
  test("prototype names are not variables", () => {
    expect(() => evalNumber("constructor + 1", {})).toThrow(/missing variable/);
    expect(() => evalNumber("toString", {})).toThrow(/missing variable/);
  });
  test("compileExpr lists referenced variables (functions and keywords excluded)", () => {
    const c = compileExpr("abs(value - compare_value) > 3 and not flag or true");
    expect([...c.variables].sort()).toEqual(["compare_value", "flag", "value"]);
  });
});

describe("comparisons and logic", () => {
  test.each([
    ["value >= 2.5 * compare_value", { value: 25, compare_value: 10 }, true],
    ["value >= 2.5 * compare_value", { value: 24.99, compare_value: 10 }, false],
    ["value > 20", { value: 20 }, false],
    ["value <= -25", { value: -25 }, true],
    ["value < 1", { value: 0 }, true],
    ["value == 3", { value: 3 }, true],
    ["value != 3", { value: 3 }, false],
    ["a > 1 and b > 1", { a: 2, b: 0 }, false],
    ["a > 1 or b > 1", { a: 2, b: 0 }, true],
    ["not a > 1", { a: 2 }, false],
    ["a > 1 or b > 1 and c > 1", { a: 2, b: 0, c: 0 }, true], // and binds tighter than or
    ["(a > 1 or b > 1) and c > 1", { a: 2, b: 0, c: 0 }, false],
    ["true and not false", {}, true],
    ["flag == true", { flag: true }, true],
  ])("%s with %o → %s", (expr, vars, want) => {
    expect(evalBool(expr, vars as Record<string, number | boolean>)).toBe(want);
  });

  test("and/or short-circuit: right side not evaluated", () => {
    expect(evalBool("false and missing > 1", {})).toBe(false);
    expect(evalBool("true or missing > 1", {})).toBe(true);
  });

  test("comparison is non-associative", () => {
    expect(() => evaluate("1 < 2 < 3", {})).toThrow(ExprError);
  });
});

describe("functions", () => {
  test("abs/min/max", () => {
    expect(evalNumber("abs(-3)", {})).toBe(3);
    expect(evalNumber("min(4, 2, 9)", {})).toBe(2);
    expect(evalNumber("max(value, 0)", { value: -5 })).toBe(0);
    expect(evalNumber("-min(value, 0)", { value: -40 })).toBe(40);
  });
  test("arity is checked", () => {
    expect(() => evalNumber("abs(1, 2)", {})).toThrow(/abs expects 1 argument/);
    expect(() => evalNumber("min()", {})).toThrow(/min expects at least 1 argument/);
  });
  test("unknown functions are rejected at compile time", () => {
    expect(() => compileExpr("eval(1)")).toThrow(/unknown function "eval"/);
    expect(() => compileExpr("process(1)")).toThrow(ExprError);
  });
});

describe("type and runtime safety", () => {
  test.each(["1 + true", "not 3", "1 and 2", "true > false"])("type error: %s", (expr) => {
    expect(() => evaluate(expr, {})).toThrow(ExprError);
  });

  test("division and modulo by zero throw", () => {
    expect(() => evalNumber("1 / 0", {})).toThrow(/division by zero/);
    expect(() => evalNumber("1 % 0", {})).toThrow(/division by zero/);
  });

  test("non-finite results throw", () => {
    expect(() => evalNumber("10 ^ 400", {})).toThrow(/not finite/);
  });

  test("evalNumber rejects booleans and evalBool rejects numbers", () => {
    expect(() => evalNumber("1 > 0", {})).toThrow(/expected a number/);
    expect(() => evalBool("1 + 1", {})).toThrow(/expected a boolean/);
  });
});

describe("syntax errors are loud", () => {
  test.each([
    "",
    "1 +",
    "(1 + 2",
    "1 + 2)",
    "1 = 2",
    "1 ! 2",
    "1.2.3",
    ".",
    "a b",
    "value; drop",
    "value[0]",
    "\"text\"",
    "max(1,)",
  ])("rejects %j", (expr) => {
    expect(() => compileExpr(expr)).toThrow(ExprError);
  });

  test("length and nesting are bounded", () => {
    expect(() => compileExpr("1+".repeat(600) + "1")).toThrow(/too long/);
    expect(() => compileExpr("(".repeat(80) + "1" + ")".repeat(80))).toThrow(/too deeply nested/);
  });
});
```

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/expr.test.ts
```
Expected: FAIL — `Cannot find module './expr'`.

- [ ] **Step 3: Implement** — `LAAM/src/lib/intel/expr.ts`

```ts
// Safe expression evaluator for pack rules and scenarios. NEVER eval()/Function().
// Extends the util_calc tokenizer (numbers, + - * / % ^, parentheses, unary +/-) with
// identifiers, comparisons, and/or/not, true/false and abs/min/max. Arithmetic semantics
// match util_calc (^ right-associative, -2^2 = -4); util_calc itself is left untouched.
//
// Grammar, lowest -> highest precedence:
//   or    := and ("or" and)*
//   and   := not ("and" not)*
//   not   := "not" not | cmp
//   cmp   := add (CMP add)?                 non-associative
//   add   := mul (("+" | "-") mul)*
//   mul   := unary (("*" | "/" | "%") unary)*
//   unary := ("+" | "-") unary | pow
//   pow   := atom ("^" unary)?              right-associative through unary
//   atom  := NUMBER | "true" | "false" | IDENT | IDENT "(" or ("," or)* ")" | "(" or ")"

export class ExprError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ExprError";
  }
}

export type Value = number | boolean;
export type Vars = Readonly<Record<string, number | boolean | null | undefined>>;

type Tok =
  | { t: "num"; v: number }
  | { t: "id"; v: string }
  | { t: "op"; v: string }
  | { t: "lp" }
  | { t: "rp" }
  | { t: "comma" };

type Fn = "abs" | "min" | "max";

type Node =
  | { k: "num"; v: number }
  | { k: "bool"; v: boolean }
  | { k: "var"; name: string }
  | { k: "un"; op: "-" | "+" | "not"; a: Node }
  | { k: "bin"; op: string; a: Node; b: Node }
  | { k: "call"; fn: Fn; args: Node[] };

const FUNCTIONS: ReadonlySet<string> = new Set<Fn>(["abs", "min", "max"]);
const KEYWORDS: ReadonlySet<string> = new Set(["and", "or", "not", "true", "false"]);
const CMP_OPS: ReadonlySet<string> = new Set(["<", "<=", ">", ">=", "==", "!="]);
const MAX_SOURCE_CHARS = 1000;
const MAX_DEPTH = 64;

export interface CompiledExpr {
  readonly source: string;
  readonly variables: ReadonlySet<string>;
}
interface CompiledInternal extends CompiledExpr {
  readonly ast: Node;
}

function isDigit(c: string): boolean {
  return c >= "0" && c <= "9";
}
function isIdentStart(c: string): boolean {
  return (c >= "a" && c <= "z") || (c >= "A" && c <= "Z") || c === "_";
}

function tokenize(s: string): Tok[] {
  const toks: Tok[] = [];
  let i = 0;
  while (i < s.length) {
    const c = s[i];
    if (c === " " || c === "\t" || c === "\n" || c === "\r") { i++; continue; }
    if (isDigit(c) || c === ".") {
      let j = i;
      let dots = 0;
      while (j < s.length && (isDigit(s[j]) || s[j] === ".")) {
        if (s[j] === ".") dots++;
        j++;
      }
      const raw = s.slice(i, j);
      if (dots > 1 || raw === ".") throw new ExprError(`invalid number "${raw}"`);
      const n = Number(raw);
      if (!Number.isFinite(n)) throw new ExprError(`invalid number "${raw}"`);
      toks.push({ t: "num", v: n });
      i = j;
      continue;
    }
    if (isIdentStart(c)) {
      let j = i + 1;
      while (j < s.length && (isIdentStart(s[j]) || isDigit(s[j]))) j++;
      toks.push({ t: "id", v: s.slice(i, j) });
      i = j;
      continue;
    }
    const two = s.slice(i, i + 2);
    if (two === ">=" || two === "<=" || two === "==" || two === "!=") {
      toks.push({ t: "op", v: two });
      i += 2;
      continue;
    }
    if ("+-*/%^<>".includes(c)) { toks.push({ t: "op", v: c }); i++; continue; }
    if (c === "(") { toks.push({ t: "lp" }); i++; continue; }
    if (c === ")") { toks.push({ t: "rp" }); i++; continue; }
    if (c === ",") { toks.push({ t: "comma" }); i++; continue; }
    throw new ExprError(`invalid character "${c}" at ${i}`);
  }
  return toks;
}

class Parser {
  private pos = 0;
  private depth = 0;
  readonly variables = new Set<string>();
  constructor(private readonly toks: Tok[]) {}

  parse(): Node {
    if (this.toks.length === 0) throw new ExprError("empty expression");
    const n = this.or();
    if (this.pos < this.toks.length) throw new ExprError("unexpected token after end of expression");
    return n;
  }

  private peek(): Tok | undefined {
    return this.toks[this.pos];
  }
  private isOp(v: string): boolean {
    const t = this.peek();
    return !!t && t.t === "op" && t.v === v;
  }
  private isWord(v: string): boolean {
    const t = this.peek();
    return !!t && t.t === "id" && t.v === v;
  }
  private enter(): void {
    if (++this.depth > MAX_DEPTH) throw new ExprError("expression too deeply nested");
  }
  private leave(): void {
    this.depth--;
  }
  private takeOp(): string {
    const t = this.toks[this.pos++];
    return (t as { v: string }).v;
  }

  private or(): Node {
    this.enter();
    let n = this.and();
    while (this.isWord("or")) { this.pos++; n = { k: "bin", op: "or", a: n, b: this.and() }; }
    this.leave();
    return n;
  }
  private and(): Node {
    let n = this.not();
    while (this.isWord("and")) { this.pos++; n = { k: "bin", op: "and", a: n, b: this.not() }; }
    return n;
  }
  private not(): Node {
    if (this.isWord("not")) {
      this.pos++;
      this.enter();
      const a = this.not();
      this.leave();
      return { k: "un", op: "not", a };
    }
    return this.cmp();
  }
  private cmp(): Node {
    const a = this.add();
    const t = this.peek();
    if (t && t.t === "op" && CMP_OPS.has(t.v)) {
      this.pos++;
      const b = this.add();
      const next = this.peek();
      if (next && next.t === "op" && CMP_OPS.has(next.v)) throw new ExprError("comparisons cannot be chained");
      return { k: "bin", op: t.v, a, b };
    }
    return a;
  }
  private add(): Node {
    let n = this.mul();
    while (this.isOp("+") || this.isOp("-")) {
      const op = this.takeOp();
      n = { k: "bin", op, a: n, b: this.mul() };
    }
    return n;
  }
  private mul(): Node {
    let n = this.unary();
    while (this.isOp("*") || this.isOp("/") || this.isOp("%")) {
      const op = this.takeOp();
      n = { k: "bin", op, a: n, b: this.unary() };
    }
    return n;
  }
  private unary(): Node {
    if (this.isOp("-") || this.isOp("+")) {
      const op = this.takeOp() as "-" | "+";
      this.enter();
      const a = this.unary();
      this.leave();
      return { k: "un", op, a };
    }
    return this.pow();
  }
  private pow(): Node {
    const base = this.atom();
    if (this.isOp("^")) {
      this.pos++;
      this.enter();
      const exp = this.unary();
      this.leave();
      return { k: "bin", op: "^", a: base, b: exp };
    }
    return base;
  }
  private atom(): Node {
    const t = this.peek();
    if (!t) throw new ExprError("unexpected end of expression");
    if (t.t === "num") { this.pos++; return { k: "num", v: t.v }; }
    if (t.t === "lp") {
      this.pos++;
      const n = this.or();
      if (this.peek()?.t !== "rp") throw new ExprError("missing )");
      this.pos++;
      return n;
    }
    if (t.t === "id") {
      this.pos++;
      if (t.v === "true") return { k: "bool", v: true };
      if (t.v === "false") return { k: "bool", v: false };
      if (KEYWORDS.has(t.v)) throw new ExprError(`unexpected keyword "${t.v}"`);
      if (this.peek()?.t === "lp") {
        if (!FUNCTIONS.has(t.v)) throw new ExprError(`unknown function "${t.v}"`);
        this.pos++;
        const args: Node[] = [];
        if (this.peek()?.t !== "rp") {
          args.push(this.or());
          while (this.peek()?.t === "comma") { this.pos++; args.push(this.or()); }
        }
        if (this.peek()?.t !== "rp") throw new ExprError(`missing ) after arguments of ${t.v}`);
        this.pos++;
        const fn = t.v as Fn;
        if (fn === "abs" && args.length !== 1) throw new ExprError("abs expects 1 argument");
        if ((fn === "min" || fn === "max") && args.length < 1) throw new ExprError(`${fn} expects at least 1 argument`);
        return { k: "call", fn, args };
      }
      this.variables.add(t.v);
      return { k: "var", name: t.v };
    }
    throw new ExprError("unexpected token");
  }
}

const cache = new Map<string, CompiledInternal>();
const CACHE_LIMIT = 2000;

function compileInternal(source: string): CompiledInternal {
  if (typeof source !== "string") throw new ExprError("expression must be a string");
  const hit = cache.get(source);
  if (hit) return hit;
  if (source.length > MAX_SOURCE_CHARS) throw new ExprError("expression too long");
  const parser = new Parser(tokenize(source));
  const ast = parser.parse();
  const compiled: CompiledInternal = { source, ast, variables: parser.variables };
  if (cache.size >= CACHE_LIMIT) cache.clear();
  cache.set(source, compiled);
  return compiled;
}

export function compileExpr(source: string): CompiledExpr {
  return compileInternal(source);
}

function asNum(v: Value, ctx: string): number {
  if (typeof v !== "number") throw new ExprError(`${ctx}: expected a number operand`);
  return v;
}
function asBool(v: Value, ctx: string): boolean {
  if (typeof v !== "boolean") throw new ExprError(`${ctx}: expected a boolean operand`);
  return v;
}
function finite(v: number): number {
  if (!Number.isFinite(v)) throw new ExprError("result is not finite");
  return v;
}

function ev(n: Node, vars: Vars): Value {
  switch (n.k) {
    case "num":
      return n.v;
    case "bool":
      return n.v;
    case "var": {
      const v = Object.hasOwn(vars, n.name) ? vars[n.name] : undefined;
      if (v === undefined || v === null) throw new ExprError(`missing variable "${n.name}"`);
      if (typeof v !== "number" && typeof v !== "boolean") throw new ExprError(`variable "${n.name}" has an unsupported type`);
      return v;
    }
    case "un": {
      const a = ev(n.a, vars);
      if (n.op === "not") return !asBool(a, "not");
      return n.op === "-" ? -asNum(a, "unary -") : asNum(a, "unary +");
    }
    case "call": {
      const args = n.args.map((x) => asNum(ev(x, vars), n.fn));
      if (n.fn === "abs") return Math.abs(args[0]);
      return n.fn === "min" ? Math.min(...args) : Math.max(...args);
    }
    case "bin": {
      if (n.op === "and") return asBool(ev(n.a, vars), "and") ? asBool(ev(n.b, vars), "and") : false;
      if (n.op === "or") return asBool(ev(n.a, vars), "or") ? true : asBool(ev(n.b, vars), "or");
      const a = ev(n.a, vars);
      const b = ev(n.b, vars);
      if (n.op === "==" || n.op === "!=") {
        if (typeof a !== typeof b) throw new ExprError(`${n.op}: operands must have the same type`);
        return n.op === "==" ? a === b : a !== b;
      }
      const x = asNum(a, n.op);
      const y = asNum(b, n.op);
      switch (n.op) {
        case "<": return x < y;
        case "<=": return x <= y;
        case ">": return x > y;
        case ">=": return x >= y;
        case "+": return finite(x + y);
        case "-": return finite(x - y);
        case "*": return finite(x * y);
        case "/": if (y === 0) throw new ExprError("division by zero"); return finite(x / y);
        case "%": if (y === 0) throw new ExprError("division by zero"); return finite(x % y);
        case "^": return finite(Math.pow(x, y));
        default: throw new ExprError(`unknown operator "${n.op}"`);
      }
    }
  }
}

export function evaluate(expr: string | CompiledExpr, vars: Vars): Value {
  const c = compileInternal(typeof expr === "string" ? expr : expr.source);
  return ev(c.ast, vars);
}

export function evalNumber(expr: string | CompiledExpr, vars: Vars): number {
  const v = evaluate(expr, vars);
  if (typeof v !== "number") throw new ExprError("expected a number result");
  return finite(v);
}

export function evalBool(expr: string | CompiledExpr, vars: Vars): boolean {
  const v = evaluate(expr, vars);
  if (typeof v !== "boolean") throw new ExprError("expected a boolean result");
  return v;
}
```

Đối chiếu thông báo lỗi với test: `"1 = 2"`/`"1 ! 2"`/`"value; drop"`/`"value[0]"`/`"\"text\""` ⇒ `invalid character`; `"1.2.3"`/`"."` ⇒ `invalid number`; `"a b"`/`"1 + 2)"` ⇒ `unexpected token after end of expression`; `"max(1,)"` ⇒ `unexpected token`; `"(1 + 2"` ⇒ `missing )`; `"1 +"` ⇒ `unexpected end of expression`; `""` ⇒ `empty expression`. `"1 + true"` ⇒ `+: expected a number operand`.

- [ ] **Step 4: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/expr.test.ts src/lib/agent/tools/util
```
Expected: PASS toàn bộ `expr.test.ts`; test `util_calc` hiện có (nếu có) không đổi.

- [ ] **Step 5: Commit**

```bash
git -C LAAM add src/lib/intel/expr.ts src/lib/intel/expr.test.ts
git -C LAAM commit -m "feat(intel): safe expression evaluator with variables, comparisons and logic"
```

---

### Task 3: Hợp đồng provider + `FakeMetricsProvider` (bản tham chiếu cách gộp)

**Files:**
- Create: `LAAM/src/lib/intel/provider/types.ts`, `provider/errors.ts`, `provider/aggregate.ts`, `provider/aggregate.test.ts`, `provider/fake.ts`, `provider/fake.test.ts`
- Create: `LAAM/src/lib/intel/testing/fixtures.ts`

**Interfaces:**
- Consumes: master §2.5 (chép nguyên văn).
- Produces:
```ts
// provider/types.ts — master §2.5 verbatim (DimsFilter, MetricPoint, MetricSeries, DataStatusItem,
// MetricCatalogItem, EvidencePage, MetricsProvider)
// provider/errors.ts
export type ProviderErrorCode = "tool_error" | "bad_payload" | "scope_denied" | "not_configured";
export class ProviderError extends Error { readonly code: ProviderErrorCode }
// provider/aggregate.ts
export type Aggregation = MetricSeries["aggregation"];
export interface Aggregate { value: number | null; numerator: number | null; denominator: number | null; sampleSize: number }
export function dimsKey(dims: Readonly<Record<string, string>>, keys?: readonly string[]): string;
export function inferRatioScale(points: readonly MetricPoint[]): number | null;   // null = not inferable
export function ratioScaleOf(points: readonly MetricPoint[]): number;              // inferRatioScale ?? 1
export function aggregatePoints(points: readonly MetricPoint[], aggregation: Aggregation, scale: number): Aggregate;
// provider/fake.ts
export interface FakeMetricData { catalog; packs?; points: Record<string, MetricPoint[]>; dataStatus?; disabledMetrics?; evidence?; versionsInSeries?; asOf? }
export class FakeMetricsProvider implements MetricsProvider
// testing/fixtures.ts
export function plusDays(date: string, n: number): string;
export function dailyPoints(from: string, days: number, dims: Record<string, string>, f: (i: number, date: string) => PointInit): MetricPoint[];
export function catalogItem(key: string, aggregation: Aggregation, dims: string[], over?: Partial<MetricCatalogItem>): MetricCatalogItem;
export function currentStatus(keys: string[], status?: DataStatusItem["status"]): DataStatusItem[];
```

- [ ] **Step 1: Tạo `provider/types.ts` (nguyên văn master §2.5) và `provider/errors.ts`**

`LAAM/src/lib/intel/provider/types.ts`:
```ts
// MetricsProvider contract — copied VERBATIM from the master plan §2.5 (LOCKED).
// Change the master plan first, then this file.
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

`LAAM/src/lib/intel/provider/errors.ts`:
```ts
export type ProviderErrorCode = "tool_error" | "bad_payload" | "scope_denied" | "not_configured";

// One error type for every provider failure so callers can tell "the source said no" from
// "we could not read the answer" from "the user may not see this".
export class ProviderError extends Error {
  constructor(readonly code: ProviderErrorCode, message: string) {
    super(message);
    this.name = "ProviderError";
  }
}
```

- [ ] **Step 2: Viết test thất bại cho aggregate** — `LAAM/src/lib/intel/provider/aggregate.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { aggregatePoints, dimsKey, ratioScaleOf } from "./aggregate";
import type { MetricPoint } from "./types";

const p = (period: string, over: Partial<MetricPoint>): MetricPoint => ({
  period, dims: {}, value: null, numerator: null, denominator: null, sampleSize: 1, ...over,
});

describe("aggregatePoints", () => {
  // Why: a period ratio must weight days by their denominator; a quiet day (1 of 2) must not
  // pull a 30-day rate to 40% when the true rate is ~30%.
  test("ratio = scale * sum(num) / sum(den), not the mean of daily ratios", () => {
    const pts = [p("2026-07-01", { value: 50, numerator: 1, denominator: 2 }), p("2026-07-02", { value: 30, numerator: 30, denominator: 100 })];
    const agg = aggregatePoints(pts, "ratio", 100);
    expect(agg.value).toBeCloseTo((100 * 31) / 102, 10);
    expect(agg.value).not.toBeCloseTo(40, 1);
    expect(agg.numerator).toBe(31);
    expect(agg.denominator).toBe(102);
    expect(agg.sampleSize).toBe(2);
  });

  test("ratio with zero denominator has no value", () => {
    expect(aggregatePoints([p("2026-07-01", { numerator: 0, denominator: 0 })], "ratio", 100).value).toBeNull();
  });

  test("additive sums values and sample sizes", () => {
    const agg = aggregatePoints([p("2026-07-01", { value: 10, sampleSize: 3 }), p("2026-07-02", { value: 5, sampleSize: 2 })], "additive", 1);
    expect(agg).toEqual({ value: 15, numerator: null, denominator: null, sampleSize: 5 });
  });

  test("snapshot takes the latest period per series and sums across series", () => {
    const pts = [
      p("2026-07-01", { dims: { item: "a" }, value: 10 }),
      p("2026-07-03", { dims: { item: "a" }, value: 7 }),
      p("2026-07-02", { dims: { item: "b" }, value: 4 }),
    ];
    expect(aggregatePoints(pts, "snapshot", 1).value).toBe(11);
  });

  test("empty input has no value", () => {
    expect(aggregatePoints([], "additive", 1)).toEqual({ value: null, numerator: null, denominator: null, sampleSize: 0 });
  });
});

describe("ratioScaleOf", () => {
  test("derives x100 for percent series from the data", () => {
    expect(ratioScaleOf([p("d", { value: 25, numerator: 1, denominator: 4 })])).toBe(100);
  });
  test("derives x1 for plain ratios and ignores zero numerators", () => {
    expect(ratioScaleOf([p("d", { value: 0, numerator: 0, denominator: 4 }), p("d", { value: 0.25, numerator: 1, denominator: 4 })])).toBe(1);
  });
  test("defaults to 1 when nothing tells", () => {
    expect(ratioScaleOf([])).toBe(1);
  });
});

describe("dimsKey", () => {
  test("is independent of key order and can be restricted", () => {
    expect(dimsKey({ b: "2", a: "1" })).toBe(dimsKey({ a: "1", b: "2" }));
    expect(dimsKey({ a: "1", b: "2" }, ["a"])).toBe(dimsKey({ a: "1" }));
  });
});
```

- [ ] **Step 3: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/provider/aggregate.test.ts
```
Expected: FAIL — `Cannot find module './aggregate'`.

- [ ] **Step 4: Implement** — `LAAM/src/lib/intel/provider/aggregate.ts`

```ts
import type { MetricPoint, MetricSeries } from "./types";

export type Aggregation = MetricSeries["aggregation"];

export interface Aggregate {
  value: number | null;
  numerator: number | null;
  denominator: number | null;
  sampleSize: number;
}

/** Stable key for a dims object, optionally restricted to `keys`. */
export function dimsKey(dims: Readonly<Record<string, string>>, keys?: readonly string[]): string {
  const ks = [...(keys ?? Object.keys(dims))].sort();
  return JSON.stringify(ks.map((k) => [k, dims[k] ?? null]));
}

/**
 * Scale between value and numerator/denominator, read from the data itself (a percent series
 * reports value = 100 * num / den). Snapped to a power of ten so float noise never leaks into
 * re-aggregated values. Defaults to 1 when no point carries enough information.
 */
export function inferRatioScale(points: readonly MetricPoint[]): number | null {
  for (const p of points) {
    if (p.value == null || p.numerator == null || p.denominator == null) continue;
    if (p.value === 0 || p.numerator === 0 || p.denominator === 0) continue;
    const raw = p.value / (p.numerator / p.denominator);
    if (!Number.isFinite(raw) || raw <= 0) continue;
    return 10 ** Math.round(Math.log10(raw));
  }
  return null; // nothing tells (e.g. every numerator is 0)
}

export function ratioScaleOf(points: readonly MetricPoint[]): number {
  return inferRatioScale(points) ?? 1;
}

/**
 * Collapse points into one value per the metric's aggregation (spec §6.4):
 * additive = sum; ratio = scale * sum(num) / sum(den) (never the mean of ratios);
 * snapshot = latest period of each underlying series, summed across series.
 */
export function aggregatePoints(points: readonly MetricPoint[], aggregation: Aggregation, scale: number): Aggregate {
  if (points.length === 0) return { value: null, numerator: null, denominator: null, sampleSize: 0 };
  if (aggregation === "ratio") {
    let num = 0;
    let den = 0;
    let n = 0;
    for (const p of points) {
      num += p.numerator ?? 0;
      den += p.denominator ?? 0;
      n += p.sampleSize;
    }
    return { value: den === 0 ? null : (scale * num) / den, numerator: num, denominator: den, sampleSize: n };
  }
  const source =
    aggregation === "snapshot"
      ? [...points.reduce((latest, p) => {
          const k = dimsKey(p.dims);
          const cur = latest.get(k);
          if (!cur || p.period > cur.period) latest.set(k, p);
          return latest;
        }, new Map<string, MetricPoint>()).values()]
      : points;
  let sum = 0;
  let any = false;
  let n = 0;
  for (const p of source) {
    n += p.sampleSize;
    if (p.value != null) {
      sum += p.value;
      any = true;
    }
  }
  return { value: any ? sum : null, numerator: null, denominator: null, sampleSize: n };
}
```

- [ ] **Step 5: Chạy test aggregate — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/provider/aggregate.test.ts
```
Expected: PASS.

- [ ] **Step 6: Tạo fixtures dùng chung** — `LAAM/src/lib/intel/testing/fixtures.ts`

```ts
// Neutral synthetic data helpers for intel tests. Metric keys used by core tests are
// industry-neutral ("acme.*"); pack-specific keys appear only in pack-content tests.
import type { DataStatusItem, MetricCatalogItem, MetricPoint } from "../provider/types";
import type { Aggregation } from "../provider/aggregate";

export interface PointInit {
  value?: number | null;
  numerator?: number | null;
  denominator?: number | null;
  sampleSize?: number;
}

export function plusDays(date: string, n: number): string {
  const d = new Date(date + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function dailyPoints(
  from: string,
  days: number,
  dims: Record<string, string>,
  f: (i: number, date: string) => PointInit,
): MetricPoint[] {
  const out: MetricPoint[] = [];
  for (let i = 0; i < days; i++) {
    const period = plusDays(from, i);
    const r = f(i, period);
    out.push({
      period,
      dims: { ...dims },
      value: r.value ?? null,
      numerator: r.numerator ?? null,
      denominator: r.denominator ?? null,
      sampleSize: r.sampleSize ?? 1,
    });
  }
  return out;
}

export function catalogItem(
  key: string,
  aggregation: Aggregation,
  dims: string[],
  over: Partial<MetricCatalogItem> = {},
): MetricCatalogItem {
  return {
    key,
    unit: aggregation === "ratio" ? "percent" : "currency",
    aggregation,
    grain: "day",
    dims,
    requires: [],
    enabled: true,
    disabledReason: null,
    ...over,
  };
}

export function currentStatus(keys: string[], status: DataStatusItem["status"] = "current"): DataStatusItem[] {
  return keys.map((k) => ({ subject: `metric:${k}`, status, lastSuccessAt: "2026-07-31T23:00:00Z", issues: [] }));
}
```

- [ ] **Step 7: Viết test thất bại cho Fake** — `LAAM/src/lib/intel/provider/fake.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { FakeMetricsProvider } from "./fake";
import { ProviderError } from "./errors";
import { catalogItem, currentStatus, dailyPoints } from "../testing/fixtures";

function provider() {
  return new FakeMetricsProvider({
    catalog: [
      catalogItem("acme.revenue", "additive", ["location_id", "employee_id"]),
      catalogItem("acme.refund_rate", "ratio", ["location_id"]),
      catalogItem("acme.target", "snapshot", ["location_id"], { grain: "month" }),
      catalogItem("acme.off", "additive", ["location_id"], { enabled: false, disabledReason: "missing data" }),
    ],
    points: {
      "acme.revenue": [
        ...dailyPoints("2026-07-01", 3, { location_id: "L1", employee_id: "E1" }, () => ({ value: 10, sampleSize: 2 })),
        ...dailyPoints("2026-07-01", 3, { location_id: "L1", employee_id: "E2" }, () => ({ value: 5, sampleSize: 1 })),
        ...dailyPoints("2026-07-01", 3, { location_id: "L2", employee_id: "E3" }, () => ({ value: 1, sampleSize: 1 })),
      ],
      "acme.refund_rate": [
        { period: "2026-07-01", dims: { location_id: "L1" }, value: 50, numerator: 1, denominator: 2, sampleSize: 2 },
        { period: "2026-07-02", dims: { location_id: "L1" }, value: 30, numerator: 30, denominator: 100, sampleSize: 100 },
      ],
      "acme.target": [{ period: "2026-07-01", dims: { location_id: "L1" }, value: 40, numerator: null, denominator: null, sampleSize: 1 }],
    },
    dataStatus: currentStatus(["acme.revenue", "acme.refund_rate"]),
    evidence: { "acme.revenue": { columns: ["id"], rows: [["a"], ["b"], ["c"]] } },
  });
}

describe("FakeMetricsProvider.getMetrics", () => {
  test("ratio total is sum(num)/sum(den), not the mean of daily ratios", async () => {
    const { series } = await provider().getMetrics({ metricKeys: ["acme.refund_rate"], from: "2026-07-01", to: "2026-07-03", grain: "total", groupBy: ["location_id"] });
    expect(series[0].points).toHaveLength(1);
    expect(series[0].points[0].value).toBeCloseTo((100 * 31) / 102, 10);
  });

  test("groupBy collapses dims that are not listed", async () => {
    const { series } = await provider().getMetrics({ metricKeys: ["acme.revenue"], from: "2026-07-01", to: "2026-07-04", grain: "total", groupBy: ["location_id"] });
    const byLoc = Object.fromEntries(series[0].points.map((pt) => [pt.dims.location_id, pt.value]));
    expect(byLoc).toEqual({ L1: 45, L2: 3 });
  });

  test("dimsFilter restricts rows; a filter on a dim the metric lacks is ignored", async () => {
    const { series } = await provider().getMetrics({
      metricKeys: ["acme.revenue"], from: "2026-07-01", to: "2026-07-04", grain: "total", groupBy: ["location_id"],
      dimsFilter: { location_id: ["L2"], region: ["north"] },
    });
    expect(series[0].points.map((pt) => pt.dims.location_id)).toEqual(["L2"]);
  });

  test("day grain returns one point per day and group; to is exclusive", async () => {
    const { series } = await provider().getMetrics({ metricKeys: ["acme.revenue"], from: "2026-07-01", to: "2026-07-03", grain: "day", groupBy: ["location_id"] });
    expect(series[0].points.filter((pt) => pt.dims.location_id === "L1").map((pt) => pt.period)).toEqual(["2026-07-01", "2026-07-02"]);
  });

  test("month grain buckets on the first day of the month", async () => {
    const { series } = await provider().getMetrics({ metricKeys: ["acme.target"], from: "2026-07-01", to: "2026-08-01", grain: "month", groupBy: ["location_id"] });
    expect(series[0].points[0]).toMatchObject({ period: "2026-07-01", value: 40 });
  });

  test("unknown or disabled metrics are errors", async () => {
    await expect(provider().getMetrics({ metricKeys: ["acme.nope"], from: "2026-07-01", to: "2026-07-02", grain: "total" })).rejects.toBeInstanceOf(ProviderError);
    await expect(provider().getMetrics({ metricKeys: ["acme.off"], from: "2026-07-01", to: "2026-07-02", grain: "total" })).rejects.toThrow(/metric_disabled/);
  });

  test("data status only for the requested metrics", async () => {
    const { dataStatus } = await provider().getMetrics({ metricKeys: ["acme.revenue"], from: "2026-07-01", to: "2026-07-02", grain: "total" });
    expect(dataStatus.map((s) => s.subject)).toEqual(["metric:acme.revenue"]);
  });
});

describe("FakeMetricsProvider.getEvidence / getDataStatus", () => {
  test("pages evidence with hasMore", async () => {
    const page = await provider().getEvidence({ metricKey: "acme.revenue", from: "2026-07-01", to: "2026-07-02", dims: {}, limit: 2, offset: 0 });
    expect(page).toEqual({ columns: ["id"], rows: [["a"], ["b"]], hasMore: true, sourceMode: "live" });
  });

  test("reports asOf: explicit value, else the latest data day", async () => {
    expect((await provider().getDataStatus()).asOf).toBe("2026-07-03");
    expect((await new FakeMetricsProvider({ catalog: [], points: {}, asOf: "2026-07-31" }).listMetrics()).asOf).toBe("2026-07-31");
  });

  test("records calls so wrappers can be asserted", async () => {
    const fp = provider();
    await fp.getDataStatus();
    expect(fp.calls.map((c) => c.method)).toEqual(["getDataStatus"]);
  });
});
```

- [ ] **Step 8: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/provider/fake.test.ts
```
Expected: FAIL — `Cannot find module './fake'`.

- [ ] **Step 9: Implement** — `LAAM/src/lib/intel/provider/fake.ts`

```ts
// In-memory MetricsProvider. It is the reference implementation of the aggregation contract
// (master §2.4): tests and offline demos use it, and it must agree with DAAB on semantics.
// Week grain buckets on Monday here; the engine never requests week grain (undefined in §2.4).
import type {
  DataStatusItem, DimsFilter, EvidencePage, MetricCatalogItem, MetricPoint, MetricSeries, MetricsProvider,
} from "./types";
import { aggregatePoints, dimsKey, ratioScaleOf } from "./aggregate";
import { ProviderError } from "./errors";

export interface FakeMetricData {
  catalog: MetricCatalogItem[];
  packs?: { key: string; version: string }[];
  /** Raw points per metric key at the metric's own grain (day, or 1st of month for grain=month). */
  points: Record<string, MetricPoint[]>;
  dataStatus?: DataStatusItem[];
  disabledMetrics?: { metricKey: string; reason: string }[];
  evidence?: Record<string, { columns: string[]; rows: unknown[][] }>;
  versionsInSeries?: Record<string, number[]>;
  /** Last data day, inclusive (master §2.4 `as_of`). Defaults to the latest period in `points`; "" simulates a source without one. */
  asOf?: string;
}

type MetricsQuery = Parameters<MetricsProvider["getMetrics"]>[0];
type EvidenceQuery = Parameters<MetricsProvider["getEvidence"]>[0];
type Grain = MetricsQuery["grain"];

function matchesFilter(dims: Record<string, string>, filter?: DimsFilter): boolean {
  if (!filter) return true;
  for (const [k, allowed] of Object.entries(filter)) {
    if (!(k in dims)) continue; // contract: a filter on a dim the metric lacks is ignored
    if (!allowed.includes(dims[k])) return false;
  }
  return true;
}

function bucketOf(period: string, grain: Grain, from: string): string {
  if (grain === "day") return period;
  if (grain === "month") return period.slice(0, 7) + "-01";
  if (grain === "total") return from;
  const d = new Date(period + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
}

export class FakeMetricsProvider implements MetricsProvider {
  readonly calls: { method: string; args: unknown }[] = [];

  constructor(private readonly data: FakeMetricData) {}

  private asOf(): string {
    if (this.data.asOf !== undefined) return this.data.asOf;
    let max = "";
    for (const pts of Object.values(this.data.points)) for (const p of pts) if (p.period > max) max = p.period;
    return max;
  }

  async listMetrics(): Promise<{ asOf: string; packs: { key: string; version: string }[]; metrics: MetricCatalogItem[] }> {
    this.calls.push({ method: "listMetrics", args: null });
    return { asOf: this.asOf(), packs: this.data.packs ?? [], metrics: this.data.catalog };
  }

  async getMetrics(q: MetricsQuery): Promise<{ asOf: string; series: MetricSeries[]; dataStatus: DataStatusItem[] }> {
    this.calls.push({ method: "getMetrics", args: q });
    if (q.from >= q.to) throw new ProviderError("tool_error", "invalid_range");
    const series = q.metricKeys.map((key): MetricSeries => {
      const item = this.data.catalog.find((c) => c.key === key);
      if (!item) throw new ProviderError("tool_error", `unknown_metric: ${key}`);
      if (!item.enabled) throw new ProviderError("tool_error", `metric_disabled: ${key}`);
      const all = this.data.points[key] ?? [];
      const scale = ratioScaleOf(all);
      const groupBy = q.groupBy ?? item.dims;
      const buckets = new Map<string, { period: string; dims: Record<string, string>; points: MetricPoint[] }>();
      for (const p of all) {
        if (p.period < q.from || p.period >= q.to || !matchesFilter(p.dims, q.dimsFilter)) continue;
        const dims: Record<string, string> = {};
        for (const d of groupBy) if (d in p.dims) dims[d] = p.dims[d];
        const period = bucketOf(p.period, q.grain, q.from);
        const k = period + "|" + dimsKey(dims);
        const b = buckets.get(k) ?? { period, dims, points: [] };
        b.points.push(p);
        buckets.set(k, b);
      }
      const points = [...buckets.values()]
        .map((b): MetricPoint => ({ period: b.period, dims: b.dims, ...aggregatePoints(b.points, item.aggregation, scale) }))
        .sort((a, b) => a.period.localeCompare(b.period) || dimsKey(a.dims).localeCompare(dimsKey(b.dims)));
      return {
        metricKey: key,
        unit: item.unit,
        aggregation: item.aggregation,
        points,
        versionsInSeries: this.data.versionsInSeries?.[key] ?? [1],
      };
    });
    const subjects = new Set(q.metricKeys.map((k) => `metric:${k}`));
    return { asOf: this.asOf(), series, dataStatus: (this.data.dataStatus ?? []).filter((s) => subjects.has(s.subject)) };
  }

  async getEvidence(q: EvidenceQuery): Promise<EvidencePage> {
    this.calls.push({ method: "getEvidence", args: q });
    const ev = this.data.evidence?.[q.metricKey] ?? { columns: [], rows: [] };
    return {
      columns: ev.columns,
      rows: ev.rows.slice(q.offset, q.offset + q.limit),
      hasMore: q.offset + q.limit < ev.rows.length,
      sourceMode: "live",
    };
  }

  async getDataStatus(): Promise<{ asOf: string; items: DataStatusItem[]; disabledMetrics: { metricKey: string; reason: string }[] }> {
    this.calls.push({ method: "getDataStatus", args: null });
    return { asOf: this.asOf(), items: this.data.dataStatus ?? [], disabledMetrics: this.data.disabledMetrics ?? [] };
  }
}
```

- [ ] **Step 10: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/provider
```
Expected: PASS (`aggregate.test.ts`, `fake.test.ts`).

- [ ] **Step 11: Commit**

```bash
git -C LAAM add src/lib/intel/provider src/lib/intel/testing/fixtures.ts
git -C LAAM commit -m "feat(intel): metrics provider contract, aggregation helpers and in-memory fake"
```

---

### Task 4: `DaabMetricsProvider`

**Files:**
- Create: `LAAM/src/lib/intel/provider/daab.ts`, `LAAM/src/lib/intel/provider/daab.test.ts`

**Interfaces:**
- Consumes: `execute(userId, toolName, args)` từ `@/lib/connectors` (index.ts:562 — `executeMcp` là private, được `execute` gọi khi tên bắt đầu `mcp__`); `unwrapToolResult` từ `@/lib/agent/drilldown` (:61). Tool name = `mcp__<slug>__<tool>` (route key trong `mcp/discovery.ts`, có cả tên gốc khi bị đổi tên do trùng).
- Produces:
```ts
export type ToolCaller = (userId: string, toolName: string, args: Record<string, unknown>) => Promise<unknown>;
export interface DaabProviderConfig { userId: string; connectorSlug: string; projectId: string; call?: ToolCaller }
export class DaabMetricsProvider implements MetricsProvider { constructor(cfg: DaabProviderConfig) }
```

Ghi chú hành vi đã kiểm trong code:
- `mcp/client.ts:callTool` trả `{ text, isError? }` khi mọi block là text; text dài hơn 200.000 ký tự bị **cắt và nối thêm ghi chú** ⇒ JSON hỏng ⇒ `unwrapToolResult` trả `null` ⇒ provider ném `bad_payload`.
- Lỗi cấp connector (`{ error: "..." }` từ `executeMcp`) và lỗi in-band (`isError: true`) phải kiểm **trước** unwrap — nếu không, một `text` lỗi có dạng JSON sẽ bị coi là dữ liệu.
- `executeMcp` chạy `pinKnownIds`: nếu `instructions` của server DAAB nêu đúng một `project_id` khác, `project_id` gửi đi bị **ghi đè im lặng**. Task 5 (`providerForProject`) chặn trường hợp này.
- `executeMcp` đã retry 1 lần với lỗi tạm thời; provider không retry thêm.

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/lib/intel/provider/daab.test.ts`

```ts
import { describe, expect, test, vi } from "vitest";

const h = vi.hoisted(() => ({ execute: vi.fn() }));
vi.mock("@/lib/connectors", () => ({ execute: h.execute }));

import { DaabMetricsProvider, type ToolCaller } from "./daab";
import { ProviderError } from "./errors";

const text = (obj: unknown) => ({ text: JSON.stringify(obj) });

function make(call: ToolCaller) {
  return new DaabMetricsProvider({ userId: "u-owner", connectorSlug: "daab", projectId: "p-1", call });
}

const metricsPayload = {
  series: [{
    metric_key: "acme.revenue", unit: "currency", aggregation: "additive",
    points: [{ period: "2026-07-01", dims: { location_id: "L1" }, value: "1234.50", numerator: null, denominator: null, sample_size: 42 }],
    versions_in_series: [1],
  }],
  data_status: [{ subject: "metric:acme.revenue", status: "current", last_success_at: "2026-08-01T05:00:00Z" }],
  as_of: "2026-07-31",
};

describe("DaabMetricsProvider", () => {
  test("calls the namespaced MCP tool as the configured user with snake_case args", async () => {
    const call = vi.fn<ToolCaller>(async () => text(metricsPayload));
    const out = await make(call).getMetrics({
      metricKeys: ["acme.revenue"], from: "2026-07-01", to: "2026-08-01", grain: "total",
      groupBy: ["location_id"], dimsFilter: { location_id: ["L1"] },
    });
    expect(call).toHaveBeenCalledWith("u-owner", "mcp__daab__kg_get_metrics", {
      project_id: "p-1", metric_keys: ["acme.revenue"], from: "2026-07-01", to: "2026-08-01", grain: "total",
      group_by: ["location_id"], dims_filter: { location_id: ["L1"] },
    });
    expect(out.series[0]).toEqual({
      metricKey: "acme.revenue", unit: "currency", aggregation: "additive", versionsInSeries: [1],
      points: [{ period: "2026-07-01", dims: { location_id: "L1" }, value: 1234.5, numerator: null, denominator: null, sampleSize: 42 }],
    });
    expect(out.dataStatus).toEqual([{ subject: "metric:acme.revenue", status: "current", lastSuccessAt: "2026-08-01T05:00:00Z", issues: [] }]);
    expect(out.asOf).toBe("2026-07-31");
  });

  test("a missing or malformed as_of is a bad payload, not a silent default", async () => {
    const { as_of: _drop, ...noAsOf } = metricsPayload;
    const call = vi.fn<ToolCaller>(async () => text(noAsOf));
    await expect(make(call).getMetrics({ metricKeys: ["acme.revenue"], from: "2026-07-01", to: "2026-08-01", grain: "total" }))
      .rejects.toMatchObject({ code: "bad_payload" });
  });

  test("omits optional args instead of sending undefined", async () => {
    const call = vi.fn<ToolCaller>(async () => text(metricsPayload));
    await make(call).getMetrics({ metricKeys: ["acme.revenue"], from: "2026-07-01", to: "2026-08-01", grain: "day" });
    expect(Object.keys(call.mock.calls[0][2]).sort()).toEqual(["from", "grain", "metric_keys", "project_id", "to"]);
  });

  test("throws tool_error on isError before unwrapping, even when the text is JSON", async () => {
    const call = vi.fn<ToolCaller>(async () => ({ text: JSON.stringify(metricsPayload), isError: true }));
    await expect(make(call).getMetrics({ metricKeys: ["acme.revenue"], from: "2026-07-01", to: "2026-08-01", grain: "total" }))
      .rejects.toMatchObject({ code: "tool_error" });
  });

  test("throws tool_error on a connector-level error object", async () => {
    const call = vi.fn<ToolCaller>(async () => ({ error: "MCP server \"daab\" chưa cấu hình" }));
    await expect(make(call).getDataStatus()).rejects.toMatchObject({ code: "tool_error" });
  });

  test("throws bad_payload when the text is not JSON (e.g. truncated at 200k chars)", async () => {
    const truncated = JSON.stringify(metricsPayload).slice(0, 40) + "\n\n[... nội dung đã rút gọn 12345 ký tự cho vừa ngữ cảnh]";
    const call = vi.fn<ToolCaller>(async () => ({ text: truncated }));
    await expect(make(call).getMetrics({ metricKeys: ["acme.revenue"], from: "2026-07-01", to: "2026-08-01", grain: "total" }))
      .rejects.toMatchObject({ code: "bad_payload" });
  });

  test("surfaces DAAB error envelopes with their code", async () => {
    const call = vi.fn<ToolCaller>(async () => text({ error: { code: "unknown_metric", message: "acme.x" } }));
    await expect(make(call).getMetrics({ metricKeys: ["acme.x"], from: "2026-07-01", to: "2026-08-01", grain: "total" }))
      .rejects.toThrow(/unknown_metric/);
  });

  // DAAB's auth middleware still answers with the legacy flat shape {"error": "...", "message": "..."}.
  test.each([
    [{ error: "Unauthorized", message: "missing or invalid API key", status: 401 }, /: unauthorized: missing or invalid API key/],
    [{ error: "Forbidden", message: "no access to project" }, /: forbidden: no access to project/],
    [{ error: "Teapot", message: "odd" }, /: Teapot: odd/],
  ])("maps the legacy flat error shape %o", async (payload, re) => {
    const call = vi.fn<ToolCaller>(async () => text(payload));
    await expect(make(call).getDataStatus()).rejects.toThrow(re);
    await expect(make(call).getDataStatus()).rejects.toMatchObject({ code: "tool_error" });
  });

  test("rejects an unexpected shape instead of guessing", async () => {
    const call = vi.fn<ToolCaller>(async () => text({ series: [{ metric_key: "acme.revenue" }] }));
    await expect(make(call).getMetrics({ metricKeys: ["acme.revenue"], from: "2026-07-01", to: "2026-08-01", grain: "total" }))
      .rejects.toMatchObject({ code: "bad_payload" });
  });

  test("maps catalog, evidence and data status", async () => {
    const call = vi.fn<ToolCaller>(async (_u, tool) => {
      if (tool.endsWith("kg_list_metrics")) return text({ as_of: "2026-07-31", packs: [{ key: "acme", version: "0.1.0" }], metrics: [{ key: "acme.revenue", unit: "currency", aggregation: "additive", grain: "day", dims: ["location_id"], requires: ["sale"], sample_size: "transactions", enabled: false, disabled_reason: "missing entity" }] });
      if (tool.endsWith("kg_get_evidence")) return text({ columns: ["id", "_source_ref"], rows: [["1", "t:1"]], has_more: false, source_mode: "live" });
      return text({ as_of: "2026-07-31", items: [{ subject: "entity:sale", status: "delayed", last_success_at: null, period_from: "2026-01-01", period_to: "2026-07-31", issues: [{ code: "late", message: "late", detail: {} }] }], disabled_metrics: [{ metric_key: "acme.x", reason: "no data" }] });
    });
    const p = make(call);
    const list = await p.listMetrics(); // call once so mock.calls[1] is the evidence call
    expect(list.asOf).toBe("2026-07-31");
    expect(list.metrics[0]).toEqual({ key: "acme.revenue", unit: "currency", aggregation: "additive", grain: "day", dims: ["location_id"], requires: ["sale"], enabled: false, disabledReason: "missing entity" });
    expect(await p.getEvidence({ metricKey: "acme.revenue", from: "2026-07-01", to: "2026-07-02", dims: { location_id: "L1" }, limit: 50, offset: 0 }))
      .toEqual({ columns: ["id", "_source_ref"], rows: [["1", "t:1"]], hasMore: false, sourceMode: "live" });
    expect(call.mock.calls[1][2]).toEqual({ project_id: "p-1", metric_key: "acme.revenue", from: "2026-07-01", to: "2026-07-02", dims: { location_id: "L1" }, limit: 50, offset: 0 });
    expect(await p.getDataStatus()).toEqual({
      asOf: "2026-07-31",
      items: [{ subject: "entity:sale", status: "delayed", lastSuccessAt: null, issues: [{ code: "late", message: "late" }] }],
      disabledMetrics: [{ metricKey: "acme.x", reason: "no data" }],
    });
  });

  test("default caller goes through connectors.execute", async () => {
    h.execute.mockResolvedValueOnce(text({ as_of: "2026-07-31", items: [], disabled_metrics: [] }));
    const p = new DaabMetricsProvider({ userId: "u1", connectorSlug: "daab", projectId: "p-1" });
    await p.getDataStatus();
    expect(h.execute).toHaveBeenCalledWith("u1", "mcp__daab__kg_get_data_status", { project_id: "p-1" });
  });

  test("refuses to build without identity, slug or project", () => {
    expect(() => new DaabMetricsProvider({ userId: "", connectorSlug: "daab", projectId: "p" })).toThrow(ProviderError);
  });
});
```

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/provider/daab.test.ts
```
Expected: FAIL — `Cannot find module './daab'`.

- [ ] **Step 3: Implement** — `LAAM/src/lib/intel/provider/daab.ts`

```ts
// MetricsProvider backed by the DAAB MCP bridge (spec §6.7, master §2.4). The ONLY file in the
// engine that knows DAAB tool names (spec D7). Calls run as a LAAM user because MCP server
// config is decrypted per user (spec §2.4 I4).
import { z } from "zod";
import { unwrapToolResult } from "@/lib/agent/drilldown";
import { ProviderError } from "./errors";
import type { DataStatusItem, EvidencePage, MetricCatalogItem, MetricSeries, MetricsProvider } from "./types";

export type ToolCaller = (userId: string, toolName: string, args: Record<string, unknown>) => Promise<unknown>;

export interface DaabProviderConfig {
  userId: string;
  connectorSlug: string;
  projectId: string;
  call?: ToolCaller;
}

const TOOLS = {
  list: "kg_list_metrics",
  metrics: "kg_get_metrics",
  evidence: "kg_get_evidence",
  status: "kg_get_data_status",
} as const;

// Lazy import keeps the connector registry (DB + crypto) out of modules that only need types.
const defaultCaller: ToolCaller = async (userId, toolName, args) => {
  const { execute } = await import("@/lib/connectors");
  return execute(userId, toolName, args);
};

// Postgres NUMERIC may arrive as a JSON string; accept plain decimal strings only.
const num = z.union([z.number(), z.string().regex(/^-?\d+(\.\d+)?([eE][+-]?\d+)?$/).transform(Number)]);
const optNum = num.nullable().optional().transform((v) => (v === undefined ? null : v));
const dims = z.record(z.string(), z.union([z.string(), z.number()]).transform(String));
const aggregation = z.enum(["additive", "ratio", "snapshot"]);
// Last data day, inclusive (master §2.4). Required: windows are computed from it.
const asOf = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "as_of must be YYYY-MM-DD");
const status = z.enum(["current", "delayed", "incomplete", "stale", "blocked"]);
const statusItem = z.object({
  subject: z.string(),
  status,
  last_success_at: z.string().nullable().optional(),
  issues: z.array(z.object({ code: z.string(), message: z.string() })).optional(),
});

const metricsOut = z.object({
  series: z.array(
    z.object({
      metric_key: z.string(),
      unit: z.string(),
      aggregation,
      points: z.array(
        z.object({
          period: z.string(),
          dims: dims.default({}),
          value: optNum,
          numerator: optNum,
          denominator: optNum,
          sample_size: num,
        }),
      ),
      versions_in_series: z.array(num).optional(),
    }),
  ),
  data_status: z.array(statusItem).optional(),
  as_of: asOf,
});
const evidenceOut = z.object({
  columns: z.array(z.string()),
  rows: z.array(z.array(z.unknown())),
  has_more: z.boolean(),
  source_mode: z.enum(["live", "file", "landed"]),
});
const statusOut = z.object({
  as_of: asOf,
  items: z.array(statusItem),
  disabled_metrics: z.array(z.object({ metric_key: z.string(), reason: z.string() })).optional(),
});
const listOut = z.object({
  as_of: asOf,
  packs: z.array(z.object({ key: z.string(), version: z.string() })),
  metrics: z.array(
    z.object({
      key: z.string(),
      unit: z.string(),
      aggregation,
      grain: z.enum(["day", "month"]),
      dims: z.array(z.string()),
      requires: z.array(z.string()).optional(),
      enabled: z.boolean(),
      disabled_reason: z.string().nullable().optional(),
    }),
  ),
});

function mapStatus(s: z.infer<typeof statusItem>): DataStatusItem {
  return { subject: s.subject, status: s.status, lastSuccessAt: s.last_success_at ?? null, issues: s.issues ?? [] };
}

export class DaabMetricsProvider implements MetricsProvider {
  private readonly call: ToolCaller;

  constructor(private readonly cfg: DaabProviderConfig) {
    if (!cfg.userId || !cfg.connectorSlug || !cfg.projectId) {
      throw new ProviderError("not_configured", "DAAB provider needs userId, connectorSlug and projectId");
    }
    this.call = cfg.call ?? defaultCaller;
  }

  private async callTool<S extends z.ZodType>(tool: string, args: Record<string, unknown>, schema: S): Promise<z.output<S>> {
    const name = `mcp__${this.cfg.connectorSlug}__${tool}`;
    const raw = await this.call(this.cfg.userId, name, { project_id: this.cfg.projectId, ...args });
    // Errors first: an in-band error text can itself be valid JSON and must never be read as data.
    if (raw && typeof raw === "object") {
      const r = raw as { error?: unknown; isError?: unknown; text?: unknown };
      if (typeof r.error === "string") throw new ProviderError("tool_error", `${tool}: ${r.error.slice(0, 300)}`);
      if (r.isError === true) {
        throw new ProviderError("tool_error", `${tool}: ${String(r.text ?? "tool reported an error").slice(0, 300)}`);
      }
    }
    const payload = unwrapToolResult(raw);
    if (payload === null || typeof payload !== "object") {
      // unwrapToolResult returns null for non-JSON text — including results the MCP client
      // truncated at 200k chars. Treating that as "no data" would silently hide findings.
      throw new ProviderError("bad_payload", `${tool}: result is not JSON (truncated or malformed)`);
    }
    const envelope = (payload as { error?: unknown }).error;
    if (envelope && typeof envelope === "object") {
      // master §2.4 shape: {error: {code, message}}
      const e = envelope as { code?: unknown; message?: unknown };
      throw new ProviderError("tool_error", `${tool}: ${String(e.code ?? "error")}: ${String(e.message ?? "").slice(0, 300)}`);
    }
    if (typeof envelope === "string") {
      // Legacy flat shape from DAAB's auth middleware: {error: "Forbidden", message: "..."}; the
      // code is derived from the HTTP status when present, else from the error word.
      const flat = payload as { message?: unknown; status?: unknown };
      const code =
        flat.status === 401 || /^unauthori[sz]ed$/i.test(envelope) ? "unauthorized"
        : flat.status === 403 || /^forbidden$/i.test(envelope) ? "forbidden"
        : envelope.slice(0, 60);
      throw new ProviderError("tool_error", `${tool}: ${code}: ${String(flat.message ?? "").slice(0, 300)}`);
    }
    const parsed = schema.safeParse(payload);
    if (!parsed.success) {
      throw new ProviderError("bad_payload", `${tool}: unexpected shape (${parsed.error.issues[0]?.message ?? "invalid"})`);
    }
    return parsed.data;
  }

  async listMetrics(): Promise<{ asOf: string; packs: { key: string; version: string }[]; metrics: MetricCatalogItem[] }> {
    const out = await this.callTool(TOOLS.list, {}, listOut);
    return {
      asOf: out.as_of,
      packs: out.packs,
      metrics: out.metrics.map((m) => ({
        key: m.key,
        unit: m.unit,
        aggregation: m.aggregation,
        grain: m.grain,
        dims: m.dims,
        requires: m.requires ?? [],
        enabled: m.enabled,
        disabledReason: m.disabled_reason ?? null,
      })),
    };
  }

  async getMetrics(q: Parameters<MetricsProvider["getMetrics"]>[0]): Promise<{ asOf: string; series: MetricSeries[]; dataStatus: DataStatusItem[] }> {
    const args: Record<string, unknown> = { metric_keys: q.metricKeys, from: q.from, to: q.to, grain: q.grain };
    if (q.groupBy) args.group_by = q.groupBy;
    if (q.dimsFilter) args.dims_filter = q.dimsFilter;
    const out = await this.callTool(TOOLS.metrics, args, metricsOut);
    return {
      asOf: out.as_of,
      series: out.series.map((s) => ({
        metricKey: s.metric_key,
        unit: s.unit,
        aggregation: s.aggregation,
        versionsInSeries: s.versions_in_series ?? [],
        points: s.points.map((p) => ({
          period: p.period,
          dims: p.dims,
          value: p.value,
          numerator: p.numerator,
          denominator: p.denominator,
          sampleSize: p.sample_size,
        })),
      })),
      dataStatus: (out.data_status ?? []).map(mapStatus),
    };
  }

  async getEvidence(q: Parameters<MetricsProvider["getEvidence"]>[0]): Promise<EvidencePage> {
    const args: Record<string, unknown> = {
      metric_key: q.metricKey, from: q.from, to: q.to, dims: q.dims, limit: q.limit, offset: q.offset,
    };
    if (q.dimsFilter) args.dims_filter = q.dimsFilter;
    const out = await this.callTool(TOOLS.evidence, args, evidenceOut);
    return { columns: out.columns, rows: out.rows, hasMore: out.has_more, sourceMode: out.source_mode };
  }

  async getDataStatus(): Promise<{ asOf: string; items: DataStatusItem[]; disabledMetrics: { metricKey: string; reason: string }[] }> {
    const out = await this.callTool(TOOLS.status, {}, statusOut);
    return {
      asOf: out.as_of,
      items: out.items.map(mapStatus),
      disabledMetrics: (out.disabled_metrics ?? []).map((d) => ({ metricKey: d.metric_key, reason: d.reason })),
    };
  }
}
```

- [ ] **Step 4: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/provider/daab.test.ts
```
Expected: PASS 14/14.

- [ ] **Step 5: Commit**

```bash
git -C LAAM add src/lib/intel/provider/daab.ts src/lib/intel/provider/daab.test.ts
git -C LAAM commit -m "feat(intel): DAAB metrics provider over MCP with strict payload checks"
```

---

### Task 5: Wrapper phạm vi chi nhánh + factory

**Files:**
- Create: `LAAM/src/lib/intel/provider/scoped.ts`, `provider/scoped.test.ts`, `provider/factory.ts`, `provider/factory.test.ts`

**Interfaces:**
- Consumes: `MetricsProvider` (Task 3), `DaabMetricsProvider`/`ToolCaller` (Task 4), `BusinessProject`, `userScopes` (Task 1), `mcpInstructions` + `singlePinnedValue` từ `@/lib/connectors` (index.ts:375, :417).
- Produces: xem "Exports for plan E" (`LOCATION_DIM`, `ProviderScope`, `scopeProvider`, `providerForProject`, `scopeForUser`).
```ts
export interface FactoryDeps {
  call?: ToolCaller;
  connectors?: { mcpInstructions(userId: string): Promise<{ slug: string; text: string }[]>; singlePinnedValue(text: string, label: string): string | undefined };
}
```

Hợp đồng `dims_filter` (master §2.4 cập nhật): DAAB trả **400 `invalid_request`** nếu `dims_filter` nêu dim mà metric không có. Vì vậy: mode `system` (và user không giới hạn chi nhánh) **không gắn filter nào**; mode `user` chỉ gắn `location_id` cho metric mà catalog có dim `location_id` — metric không có dim đó bị **từ chối trước khi gọi** (`scope_denied`), nên không bao giờ gửi filter sai. Các filter khác của engine (theo dims của chính rule/forecast) luôn là dim của metric đó; companion trong nguyên nhân chỉ được dùng khi có đủ dims của rule (Task 10).

Quyết định: **cả hai mode gọi MCP dưới danh nghĩa `business_project.ownerUserId`** (spec §7.1 nói system dùng owner; với mode user, nếu dùng userId của từng user thì mỗi user phải tự cấu hình MCP DAAB). Phạm vi user được thực thi bởi wrapper — đúng phương án beta §7.11. Ghi ở Open questions.

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/lib/intel/provider/scoped.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { scopeProvider } from "./scoped";
import { FakeMetricsProvider } from "./fake";
import { catalogItem, dailyPoints } from "../testing/fixtures";

function base() {
  return new FakeMetricsProvider({
    catalog: [
      catalogItem("acme.revenue", "additive", ["location_id"]),
      catalogItem("acme.chain_total", "additive", []),
    ],
    points: {
      "acme.revenue": [
        ...dailyPoints("2026-07-01", 2, { location_id: "L1" }, () => ({ value: 1 })),
        ...dailyPoints("2026-07-01", 2, { location_id: "L2" }, () => ({ value: 2 })),
      ],
      "acme.chain_total": dailyPoints("2026-07-01", 2, {}, () => ({ value: 9 })),
    },
    evidence: { "acme.revenue": { columns: ["id"], rows: [["x"]] } },
  });
}
const q = { metricKeys: ["acme.revenue"], from: "2026-07-01", to: "2026-07-03", grain: "total" as const, groupBy: ["location_id"] };

describe("scopeProvider", () => {
  test("system mode passes calls through unchanged and adds no dims_filter", async () => {
    const b = base();
    const out = await scopeProvider(b, { mode: "system" }).getMetrics(q);
    expect(out.series[0].points).toHaveLength(2);
    expect((b.calls.find((c) => c.method === "getMetrics")!.args as { dimsFilter?: unknown }).dimsFilter).toBeUndefined();
  });

  test("user mode injects the user's locations into every metric call", async () => {
    const b = base();
    const out = await scopeProvider(b, { mode: "user", locationIds: ["L2"] }).getMetrics(q);
    expect(out.series[0].points.map((p) => p.dims.location_id)).toEqual(["L2"]);
    const sent = b.calls.find((c) => c.method === "getMetrics")!.args as { dimsFilter: Record<string, string[]> };
    expect(sent.dimsFilter.location_id).toEqual(["L2"]);
  });

  test("a requested filter is intersected with the scope, never widened", async () => {
    const b = base();
    await scopeProvider(b, { mode: "user", locationIds: ["L2"] }).getMetrics({ ...q, dimsFilter: { location_id: ["L1", "L2"] } });
    const sent = b.calls.find((c) => c.method === "getMetrics")!.args as { dimsFilter: Record<string, string[]> };
    expect(sent.dimsFilter.location_id).toEqual(["L2"]);
  });

  test("denies a filter that only names locations outside scope", async () => {
    await expect(scopeProvider(base(), { mode: "user", locationIds: ["L2"] }).getMetrics({ ...q, dimsFilter: { location_id: ["L1"] } }))
      .rejects.toMatchObject({ code: "scope_denied" });
  });

  // Why: DAAB ignores a filter on a dim the metric does not have (master §2.4), so a chain-level
  // metric would leak every location's total to a single-store user.
  test("denies metrics without a location dim in user mode", async () => {
    await expect(scopeProvider(base(), { mode: "user", locationIds: ["L2"] }).getMetrics({ ...q, metricKeys: ["acme.chain_total"], groupBy: [] }))
      .rejects.toMatchObject({ code: "scope_denied" });
  });

  test("denies evidence for a location outside scope", async () => {
    await expect(scopeProvider(base(), { mode: "user", locationIds: ["L2"] }).getEvidence({
      metricKey: "acme.revenue", from: "2026-07-01", to: "2026-07-02", dims: { location_id: "L1" }, limit: 10, offset: 0,
    })).rejects.toMatchObject({ code: "scope_denied" });
  });

  test("evidence for a chain-level finding is filtered to the user's locations", async () => {
    const b = base();
    await scopeProvider(b, { mode: "user", locationIds: ["L2"] }).getEvidence({
      metricKey: "acme.revenue", from: "2026-07-01", to: "2026-07-02", dims: {}, limit: 10, offset: 0,
    });
    const sent = b.calls.find((c) => c.method === "getEvidence")!.args as { dimsFilter: Record<string, string[]> };
    expect(sent.dimsFilter).toEqual({ location_id: ["L2"] });
  });

  test("empty locationIds means every location (unrestricted user)", async () => {
    const out = await scopeProvider(base(), { mode: "user", locationIds: [] }).getMetrics({ ...q, metricKeys: ["acme.chain_total"], groupBy: [] });
    expect(out.series[0].points[0].value).toBe(18);
  });
});
```

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/provider/scoped.test.ts
```
Expected: FAIL — `Cannot find module './scoped'`.

- [ ] **Step 3: Implement** — `LAAM/src/lib/intel/provider/scoped.ts`

```ts
// The single place location scope is enforced for metrics and evidence (spec §7.1, §7.11).
// Screens and chat never call a provider directly; they get one wrapped here.
import { ProviderError } from "./errors";
import type { DimsFilter, MetricCatalogItem, MetricsProvider } from "./types";

export const LOCATION_DIM = "location_id";

export type ProviderScope = { mode: "system" } | { mode: "user"; locationIds: readonly string[] };

export function scopeProvider(base: MetricsProvider, scope: ProviderScope): MetricsProvider {
  // System runs see every location; a user with no location restriction behaves the same.
  if (scope.mode === "system" || scope.locationIds.length === 0) return base;
  const allowed = [...new Set(scope.locationIds)];

  let catalogP: Promise<Map<string, MetricCatalogItem>> | null = null;
  const catalog = (): Promise<Map<string, MetricCatalogItem>> =>
    (catalogP ??= base.listMetrics().then((r) => new Map(r.metrics.map((m) => [m.key, m]))));

  function narrow(filter?: DimsFilter): DimsFilter {
    const requested = filter?.[LOCATION_DIM];
    const locs = requested ? requested.filter((l) => allowed.includes(l)) : allowed;
    if (locs.length === 0) throw new ProviderError("scope_denied", "requested locations are outside the user's scope");
    return { ...(filter ?? {}), [LOCATION_DIM]: locs };
  }

  async function requireLocationDim(keys: readonly string[]): Promise<void> {
    const cat = await catalog();
    for (const k of keys) {
      const item = cat.get(k);
      if (!item || !item.dims.includes(LOCATION_DIM)) {
        // The source ignores filters on dims a metric lacks, so this would expose all locations.
        throw new ProviderError("scope_denied", `metric ${k} cannot be limited to the user's locations`);
      }
    }
  }

  return {
    listMetrics: () => base.listMetrics(),
    getDataStatus: () => base.getDataStatus(),
    async getMetrics(q) {
      await requireLocationDim(q.metricKeys);
      return base.getMetrics({ ...q, dimsFilter: narrow(q.dimsFilter) });
    },
    async getEvidence(q) {
      await requireLocationDim([q.metricKey]);
      const loc = q.dims[LOCATION_DIM];
      if (loc !== undefined && !allowed.includes(loc)) {
        throw new ProviderError("scope_denied", "evidence location is outside the user's scope");
      }
      return base.getEvidence({ ...q, dimsFilter: narrow(q.dimsFilter) });
    },
  };
}
```

- [ ] **Step 4: Chạy test scoped — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/provider/scoped.test.ts
```
Expected: PASS 8/8.

- [ ] **Step 5: Viết test thất bại cho factory** — `LAAM/src/lib/intel/provider/factory.test.ts`

```ts
import { describe, expect, test, vi } from "vitest";

const h = vi.hoisted(() => ({ rows: [] as unknown[] }));
vi.mock("@/db", () => ({
  db: { select: () => ({ from: () => ({ where: () => ({ limit: async () => h.rows }) }) }) },
}));

import { providerForProject, scopeForUser } from "./factory";
import type { BusinessProject } from "@/db/schema";

const bp: BusinessProject = {
  id: "bp1", name: "Demo", metricsProvider: "daab", daabProjectId: "4ad7a5fa-a036-4f6a-8229-39a20af23e38",
  mcpConnectorSlug: "daab", ownerUserId: "owner", timezone: "America/Chicago", localeDefault: "en",
  asOfOverride: null, createdAt: new Date(), updatedAt: new Date(),
};
const connectors = (text: string) => ({
  mcpInstructions: vi.fn(async () => [{ slug: "daab", text }]),
  singlePinnedValue: (t: string, label: string) => {
    const m = [...t.matchAll(new RegExp(`\\b${label}\\s*:\\s*([0-9a-fA-F-]{36})`, "gi"))].map((x) => x[1]);
    return new Set(m).size === 1 ? m[0] : undefined;
  },
});

describe("providerForProject", () => {
  test("builds a DAAB provider that calls as the owner", async () => {
    const call = vi.fn(async () => ({ text: JSON.stringify({ as_of: "2026-07-31", items: [], disabled_metrics: [] }) }));
    const p = await providerForProject(bp, { mode: "system" }, { call, connectors: connectors("project_id: 4ad7a5fa-a036-4f6a-8229-39a20af23e38") });
    await p.getDataStatus();
    expect(call).toHaveBeenCalledWith("owner", "mcp__daab__kg_get_data_status", { project_id: bp.daabProjectId });
  });

  // Why: executeMcp's pinKnownIds silently rewrites project_id to the one named in the server
  // instructions — numbers from another project would be analysed under this one.
  test("refuses when the MCP server is bound to a different project", async () => {
    await expect(providerForProject(bp, { mode: "system" }, { call: vi.fn(), connectors: connectors("project_id: 11111111-2222-3333-4444-555555555555") }))
      .rejects.toMatchObject({ code: "not_configured" });
  });

  test("refuses an incomplete configuration", async () => {
    await expect(providerForProject({ ...bp, mcpConnectorSlug: null }, { mode: "system" }, { call: vi.fn(), connectors: connectors("") }))
      .rejects.toMatchObject({ code: "not_configured" });
    await expect(providerForProject({ ...bp, metricsProvider: "other" }, { mode: "system" }, { call: vi.fn(), connectors: connectors("") }))
      .rejects.toMatchObject({ code: "not_configured" });
  });
});

describe("scopeForUser", () => {
  test("no user_scope row means no access", async () => {
    h.rows = [];
    expect(await scopeForUser("bp1", "u1")).toBeNull();
  });
  test("a row maps to a user scope", async () => {
    h.rows = [{ locationIds: ["PH-002"] }];
    expect(await scopeForUser("bp1", "u1")).toEqual({ mode: "user", locationIds: ["PH-002"] });
  });
});
```

- [ ] **Step 6: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/provider/factory.test.ts
```
Expected: FAIL — `Cannot find module './factory'`.

- [ ] **Step 7: Implement** — `LAAM/src/lib/intel/provider/factory.ts`

```ts
import { and, eq } from "drizzle-orm";
import { db } from "@/db";
import { userScopes, type BusinessProject } from "@/db/schema";
import { DaabMetricsProvider, type ToolCaller } from "./daab";
import { ProviderError } from "./errors";
import { scopeProvider, type ProviderScope } from "./scoped";
import type { MetricsProvider } from "./types";

export interface FactoryDeps {
  call?: ToolCaller;
  connectors?: {
    mcpInstructions(userId: string): Promise<{ slug: string; text: string }[]>;
    singlePinnedValue(text: string, label: string): string | undefined;
  };
}

/**
 * Provider for a business project, already wrapped in the given scope. Both modes call MCP as the
 * project owner (system jobs must, spec §7.1); per-user location scope is enforced by the wrapper.
 */
export async function providerForProject(bp: BusinessProject, scope: ProviderScope, deps: FactoryDeps = {}): Promise<MetricsProvider> {
  if (bp.metricsProvider !== "daab") {
    throw new ProviderError("not_configured", `unsupported metrics provider "${bp.metricsProvider}"`);
  }
  if (!bp.daabProjectId || !bp.mcpConnectorSlug) {
    throw new ProviderError("not_configured", "business project has no DAAB project id or MCP connector slug");
  }
  const connectors = deps.connectors ?? (await import("@/lib/connectors"));
  const instructions = (await connectors.mcpInstructions(bp.ownerUserId)).find((i) => i.slug === bp.mcpConnectorSlug);
  const pinned = instructions ? connectors.singlePinnedValue(instructions.text, "project_id") : undefined;
  if (pinned && pinned !== bp.daabProjectId) {
    // executeMcp → pinKnownIds would silently rewrite our project_id to `pinned`.
    throw new ProviderError(
      "not_configured",
      `MCP server "${bp.mcpConnectorSlug}" is bound to project ${pinned}, not ${bp.daabProjectId}`,
    );
  }
  const base = new DaabMetricsProvider({
    userId: bp.ownerUserId,
    connectorSlug: bp.mcpConnectorSlug,
    projectId: bp.daabProjectId,
    call: deps.call,
  });
  return scopeProvider(base, scope);
}

/** The user's scope on a business project, or null when the user has no access (no row). */
export async function scopeForUser(businessProjectId: string, userId: string): Promise<ProviderScope | null> {
  const rows = await db
    .select({ locationIds: userScopes.locationIds })
    .from(userScopes)
    .where(and(eq(userScopes.businessProjectId, businessProjectId), eq(userScopes.userId, userId)))
    .limit(1);
  const row = rows[0];
  return row ? { mode: "user", locationIds: row.locationIds } : null;
}
```

- [ ] **Step 8: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/provider
```
Expected: PASS toàn bộ thư mục provider.

- [ ] **Step 9: Commit**

```bash
git -C LAAM add src/lib/intel/provider/scoped.ts src/lib/intel/provider/scoped.test.ts src/lib/intel/provider/factory.ts src/lib/intel/provider/factory.test.ts
git -C LAAM commit -m "feat(intel): location-scoped provider wrapper and business-project factory"
```

---

### Task 6: Pack schema + loader (extends, merge, validate)

**Files:**
- Create: `LAAM/src/lib/intel/pack/schema.ts`, `pack/loader.ts`, `pack/loader.test.ts`

**Interfaces:**
- Consumes: `compileExpr` (Task 2), thư viện `yaml` (Task 1).
- Produces: xem "Exports for plan E" (`loadPacks`, `packsDir`, các type). Chi tiết:
```ts
// pack/schema.ts
export const SEVERITY_ORDER: readonly ["critical","high","medium","warning","low"]; export type Severity;
export const SEVERITY_RANK: Record<Severity, number>;
export const COMPARE_MODES: readonly ["peer_average","baseline_same_weekday_4w","target","previous_period","none"];
export const RECOMMENDED_ACTIONS: readonly [...12 actions];
export const ruleSchema, forecastSchema, scenarioSchema, glossarySchema, rolesSchema, scoringSchema, packMetaSchema;
export type Rule = z.output<typeof ruleSchema>; ForecastCfg; ScenarioTemplate; Glossary; Roles; Scoring;
export const RULE_VARIABLES: readonly string[];   // value, compare_value, numerator, denominator, sample_size
export const DAY_VARIABLES: readonly string[];    // value, numerator, denominator, sample_size
export interface LoadedPack { packs: {key:string;version:string}[]; packVersion: string; rules: Rule[]; forecasts: ForecastCfg[]; scenarios: ScenarioTemplate[]; glossary: Glossary; roles: Roles; scoring: Scoring }
// pack/loader.ts
export class PackError extends Error {}
export function packsDir(): string;
export async function loadPacks(dir: string, enabled: readonly string[]): Promise<LoadedPack>;
```

Quy tắc merge (spec §5.3 + E7): thứ tự giải quyết = cha trước con (DFS theo `extends`); rule con có `overrides: <rule_id>` thay rule cha; trùng `rule_id` mà không `overrides` ⇒ lỗi; forecast trùng `(metric, dims)` ⇒ con thay cha; scenario trùng `key` ⇒ lỗi; glossary/roles: con ghi đè từng term/persona; `scoring.yaml`: con ghi đè từng khoá cấp 1, sau đó validate đầy đủ (thiếu ⇒ lỗi — số ưu tiên/severity không có mặc định trong core).

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/lib/intel/pack/loader.test.ts`

```ts
import { afterEach, beforeEach, describe, expect, test } from "vitest";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { loadPacks, PackError } from "./loader";

let dir: string;
beforeEach(async () => { dir = await mkdtemp(path.join(tmpdir(), "intel-packs-")); });
afterEach(async () => { await rm(dir, { recursive: true, force: true }); });

async function put(rel: string, body: string) {
  const file = path.join(dir, rel);
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, body, "utf8");
}

const SCORING = `
priority_weights: { financial: 30, urgency: 20, confidence: 15, target_variance: 10, locations: 10, repeated: 10, strategic: 5 }
urgency: { critical: 1, high: 0.75, medium: 0.5, warning: 0.5, low: 0.25 }
severity_by_impact:
  sales_metric: base.revenue
  tiers:
    - { level: critical, min_amount: 10000, min_pct_weekly_sales: 1 }
  otherwise: low
normalization: { target_variance_pct: 20, repeated_occurrences: 4 }
strategic_rules: []
resurfacing: { impact_change_pct: 20, sample_growth_pct: 25 }
confidence: { deviation_z_midpoint: 2, relative_z_scale: 10, freshness_current: 1, freshness_delayed: 0.7, min_interval_factor: 0.2 }
health_score:
  components:
    sales: { weight: 30, rules: ["BASE-*"] }
  data_quality_weight: 10
  severity_penalty: { critical: 60, high: 40, medium: 20, warning: 20, low: 5 }
  status_bands: [{ min: 85, label: healthy }, { min: 0, label: high_priority }]
`;

const RULE = (id: string, extra = "") => `
  - rule_id: ${id}
    version: 1
    name: Revenue drop
    metric: base.revenue
    dims: [location_id]
    window_days: 7
    compare: previous_period
    condition: "value <= 0.9 * compare_value"
    recommended_action: investigate
    default_owner_role: manager
    cooldown_days: 7
    wording: "Revenue dropped"
${extra}`;

async function basePack() {
  await put("base/pack.yaml", "key: base\nversion: 0.1.0\ndisplay_name: Base\n");
  await put("base/laam/rules.yaml", "rules:" + RULE("BASE-REV-001"));
  await put("base/laam/forecasts.yaml", "forecasts:\n  - { metric: base.revenue, dims: [location_id], horizons_days: [7, 30], season_length: 7 }\n");
  await put("base/laam/scoring.yaml", SCORING);
  await put("base/laam/glossary.yaml", "terms:\n  revenue: { en: Revenue, vi: Doanh thu }\n");
  await put("base/laam/roles.yaml", "personas:\n  executive: { max_findings: 5, sections: [greeting, needs_attention] }\n");
}

describe("loadPacks", () => {
  test("resolves extends parents-first and reports a combined pack version", async () => {
    await basePack();
    await put("child/pack.yaml", "key: child\nversion: 0.2.0\nextends: [base]\ndisplay_name: Child\n");
    const pack = await loadPacks(dir, ["child"]);
    expect(pack.packs).toEqual([{ key: "base", version: "0.1.0" }, { key: "child", version: "0.2.0" }]);
    expect(pack.packVersion).toBe("base@0.1.0+child@0.2.0");
    expect(pack.rules.map((r) => r.rule_id)).toEqual(["BASE-REV-001"]);
    expect(pack.rules[0].breakdown).toEqual([]);
    expect(pack.rules[0].confidence_weights).toEqual({ sample: 0.4, deviation: 0.4, freshness: 0.2 });
  });

  test("a child rule replaces a parent rule only through `overrides`", async () => {
    await basePack();
    await put("child/pack.yaml", "key: child\nversion: 0.1.0\nextends: [base]\ndisplay_name: Child\n");
    await put("child/laam/rules.yaml", "rules:" + RULE("CHILD-REV-001", "    overrides: BASE-REV-001\n"));
    const pack = await loadPacks(dir, ["child"]);
    expect(pack.rules.map((r) => r.rule_id)).toEqual(["CHILD-REV-001"]);
  });

  test("a duplicate rule id without overrides is an error", async () => {
    await basePack();
    await put("child/pack.yaml", "key: child\nversion: 0.1.0\nextends: [base]\ndisplay_name: Child\n");
    await put("child/laam/rules.yaml", "rules:" + RULE("BASE-REV-001"));
    await expect(loadPacks(dir, ["child"])).rejects.toThrow(/duplicate rule_id BASE-REV-001/);
  });

  test("extends cycles are detected", async () => {
    await put("a/pack.yaml", "key: a\nversion: 0.1.0\nextends: [b]\ndisplay_name: A\n");
    await put("b/pack.yaml", "key: b\nversion: 0.1.0\nextends: [a]\ndisplay_name: B\n");
    await expect(loadPacks(dir, ["a"])).rejects.toThrow(/extends cycle: a -> b -> a/);
  });

  test("pack keys cannot escape the packs directory", async () => {
    await expect(loadPacks(dir, ["../etc"])).rejects.toThrow(PackError);
  });

  test("unknown variables in rule expressions are rejected with the rule id", async () => {
    await basePack();
    await put("base/laam/rules.yaml", "rules:" + RULE("BASE-REV-001").replace("value <= 0.9 * compare_value", "value <= peer_value"));
    await expect(loadPacks(dir, ["base"])).rejects.toThrow(/BASE-REV-001 condition: unknown variable "peer_value"/);
  });

  test("days_hit is only available when count_days is declared", async () => {
    await basePack();
    await put("base/laam/rules.yaml", "rules:" + RULE("BASE-REV-001").replace("value <= 0.9 * compare_value", "days_hit >= 3"));
    await expect(loadPacks(dir, ["base"])).rejects.toThrow(/unknown variable "days_hit"/);
    await put("base/laam/rules.yaml", "rules:" + RULE("BASE-REV-001", '    count_days: "value <= -25"\n').replace("value <= 0.9 * compare_value", "days_hit >= 3"));
    await expect(loadPacks(dir, ["base"])).resolves.toBeTruthy();
  });

  test("compare: target requires target_metric", async () => {
    await basePack();
    await put("base/laam/rules.yaml", "rules:" + RULE("BASE-REV-001").replace("compare: previous_period", "compare: target"));
    await expect(loadPacks(dir, ["base"])).rejects.toThrow(/target_metric/);
  });

  test("a rule without a condition loads (threshold not provided yet)", async () => {
    await basePack();
    await put("base/laam/rules.yaml", "rules:" + RULE("BASE-REV-001").replace('    condition: "value <= 0.9 * compare_value"\n', ""));
    const pack = await loadPacks(dir, ["base"]);
    expect(pack.rules[0].condition).toBeUndefined();
  });

  test("scenario references are checked", async () => {
    await basePack();
    await put("base/laam/scenarios.yaml", `
scenarios:
  - key: base.revenue_change
    label: Revenue change
    dims: [location_id]
    base:
      revenue: { forecast_of: base.revenue }
    variables:
      change_pct: { default: 0, min: -30, max: 30 }
    outputs:
      revenue_out: "revenue * (1 + change_pct / 100)"
    primary_output: revenue_out
    presets:
      expected:  { trend: damped }
      best:      { trend: damped, set: { change_pct: 5 } }
      risk:      { trend: damped, set: { other_pct: -5 } }
      no_action: { trend: persist_driver }
`);
    await expect(loadPacks(dir, ["base"])).rejects.toThrow(/preset risk sets unknown variable "other_pct"/);
  });

  test("a rule driver must name a variable of its scenario template", async () => {
    await basePack();
    await put("base/laam/scenarios.yaml", `
scenarios:
  - key: base.revenue_change
    label: Revenue change
    dims: [location_id]
    base: { revenue: { forecast_of: base.revenue } }
    variables: { change_pct: { default: 0, min: -30, max: 30 } }
    outputs: { revenue_out: "revenue * (1 + change_pct / 100)" }
    primary_output: revenue_out
    presets:
      expected:  { trend: damped }
      best:      { trend: damped, set: { change_pct: 5 } }
      risk:      { trend: damped, set: { change_pct: -5 } }
      no_action: { trend: persist_driver }
`);
    await put("base/laam/rules.yaml", "rules:" + RULE("BASE-REV-001", '    scenario_template: base.revenue_change\n    driver: { variable: nope_pct, expr: "value / compare_value - 1" }\n'));
    await expect(loadPacks(dir, ["base"])).rejects.toThrow(/driver variable "nope_pct"/);
  });

  test("scoring is required somewhere in the enabled packs", async () => {
    await put("solo/pack.yaml", "key: solo\nversion: 0.1.0\ndisplay_name: Solo\n");
    await expect(loadPacks(dir, ["solo"])).rejects.toThrow(/scoring\.yaml/);
  });

  // Why: the master §2.2 format is locked; a rules.yaml written exactly as the master example
  // must keep loading after the optional extensions E1–E9.
  test("threshold_status defaults to confirmed; provisional needs a note (E11)", async () => {
    await basePack();
    expect((await loadPacks(dir, ["base"])).rules[0].threshold_status).toBe("confirmed");
    await put("base/laam/rules.yaml", "rules:" + RULE("BASE-REV-001", "    threshold_status: provisional\n    threshold_note: Demo default\n"));
    expect((await loadPacks(dir, ["base"])).rules[0]).toMatchObject({ threshold_status: "provisional", threshold_note: "Demo default" });
    await put("base/laam/rules.yaml", "rules:" + RULE("BASE-REV-001", "    threshold_status: provisional\n"));
    await expect(loadPacks(dir, ["base"])).rejects.toThrow(/provisional requires threshold_note/);
    await put("base/laam/rules.yaml", "rules:" + RULE("BASE-REV-001", "    threshold_status: guessed\n"));
    await expect(loadPacks(dir, ["base"])).rejects.toThrow(PackError);
  });

  test("the master §2.2 rule example loads unchanged", async () => {
    await basePack();
    await put("base/laam/rules.yaml", `
rules:
  - rule_id: RET-REF-001
    version: 1
    name: Refund rate concentration by employee
    metric: retail.refund_rate
    dims: [location_id, employee_id]
    window_days: 30
    compare: peer_average
    target_metric: null
    min_sample: 10
    condition: "value >= 2.5 * compare_value"
    severity:
      high: "value >= 2.5 * compare_value"
    impact: "(value - compare_value) * denominator"
    impact_unit: currency
    breakdown: []
    scenario_template: null
    driver: null
    recommended_action: investigate
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Repeated exception pattern requiring management review"
    confidence_weights: { sample: 0.4, deviation: 0.4, freshness: 0.2 }
`);
    const pack = await loadPacks(dir, ["base"]);
    expect(pack.rules[0].rule_id).toBe("RET-REF-001");
  });
});
```

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/pack/loader.test.ts
```
Expected: FAIL — `Cannot find module './loader'`.

- [ ] **Step 3: Implement schema** — `LAAM/src/lib/intel/pack/schema.ts`

```ts
// Zod schemas for the LAAM half of an industry pack (master §2.2 + optional extensions E1–E9).
// Pack files carry all domain vocabulary; this module stays industry-neutral.
import { z } from "zod";

export const SEVERITY_ORDER = ["critical", "high", "medium", "warning", "low"] as const; // highest first
export type Severity = (typeof SEVERITY_ORDER)[number];
export const SEVERITY_RANK: Record<Severity, number> = { critical: 5, high: 4, medium: 3, warning: 2, low: 1 };

export const THRESHOLD_STATUSES = ["confirmed", "provisional"] as const;
export type ThresholdStatus = (typeof THRESHOLD_STATUSES)[number];

export const COMPARE_MODES = ["peer_average", "baseline_same_weekday_4w", "target", "previous_period", "none"] as const;
export type CompareMode = (typeof COMPARE_MODES)[number];

export const RECOMMENDED_ACTIONS = [
  "review", "investigate", "compare", "approve", "reorder_review", "price_review", "vendor_review",
  "inventory_count", "transfer_review", "schedule_review", "request_information", "monitor",
] as const;

/** Variables available to condition / severity / impact / driver expressions. */
export const RULE_VARIABLES = ["value", "compare_value", "numerator", "denominator", "sample_size"] as const;
/** Variables available to a per-day `count_days` expression. */
export const DAY_VARIABLES = ["value", "numerator", "denominator", "sample_size"] as const;

const metricKey = z.string().regex(/^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/, "must be <pack>.<name>");
const ident = z.string().regex(/^[a-z_][a-z0-9_]*$/, "must be a lower_snake identifier");

export const packMetaSchema = z.object({
  key: z.string().regex(/^[a-z][a-z0-9_]*$/),
  version: z.string().regex(/^\d+\.\d+\.\d+$/, "must be semver"),
  extends: z.array(z.string()).default([]),
  display_name: z.string().min(1),
});

export const ruleSchema = z
  .strictObject({
    rule_id: z.string().regex(/^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$/),
    version: z.number().int().positive(),
    name: z.string().min(1),
    metric: metricKey,
    dims: z.array(ident),
    window_days: z.number().int().min(1).max(366),
    compare: z.enum(COMPARE_MODES),
    target_metric: metricKey.nullable().optional(),
    min_sample: z.number().int().min(0).optional(), // E3
    condition: z.string().min(1).optional(), // E2: absent => rule disabled (threshold_tbd)
    severity: z.partialRecord(z.enum(SEVERITY_ORDER), z.string().min(1)).optional(), // E4
    impact: z.string().min(1).nullable().optional(),
    impact_unit: z.string().nullable().optional(),
    breakdown: z.array(ident).default([]),
    companions: z.array(metricKey).default([]), // E6
    count_days: z.string().min(1).nullable().optional(), // E5
    scenario_template: z.string().nullable().optional(),
    driver: z.strictObject({ variable: ident, expr: z.string().min(1) }).nullable().optional(),
    recommended_action: z.enum(RECOMMENDED_ACTIONS),
    default_owner_role: z.string().min(1),
    cooldown_days: z.number().int().min(0),
    wording: z.string().min(1),
    confidence_weights: z
      .strictObject({ sample: z.number().min(0), deviation: z.number().min(0), freshness: z.number().min(0) })
      .default({ sample: 0.4, deviation: 0.4, freshness: 0.2 }),
    overrides: z.string().optional(), // E7
    disabled_reason: z.string().min(1).optional(), // E2
    threshold_status: z.enum(THRESHOLD_STATUSES).default("confirmed"), // E11
    threshold_note: z.string().min(1).optional(), // E11, required when provisional
  })
  .superRefine((r, ctx) => {
    if (r.threshold_status === "provisional" && !r.threshold_note) {
      ctx.addIssue({ code: "custom", path: ["threshold_note"], message: "threshold_status: provisional requires threshold_note" });
    }
    if (r.compare === "target" && !r.target_metric) {
      ctx.addIssue({ code: "custom", path: ["target_metric"], message: "compare: target requires target_metric" });
    }
    if (r.driver && !r.scenario_template) {
      ctx.addIssue({ code: "custom", path: ["driver"], message: "driver requires scenario_template" });
    }
  });
export type Rule = z.output<typeof ruleSchema>;

export const forecastSchema = z.strictObject({
  metric: metricKey,
  dims: z.array(ident),
  horizons_days: z.array(z.number().int().min(1).max(90)).min(1),
  season_length: z.number().int().min(2).max(31),
});
export type ForecastCfg = z.output<typeof forecastSchema>;

const presetSchema = z.strictObject({
  trend: z.enum(["damped", "persist_driver"]),
  set: z.record(ident, z.number()).default({}),
});
export type ScenarioPreset = z.output<typeof presetSchema>;
export const PRESET_NAMES = ["expected", "best", "risk", "no_action"] as const;
export type PresetName = (typeof PRESET_NAMES)[number];

export const scenarioSchema = z
  .strictObject({
    key: metricKey,
    label: z.string().min(1),
    dims: z.array(ident),
    horizon_days: z.number().int().min(1).max(90).default(30), // E8
    base: z.record(ident, z.strictObject({ forecast_of: metricKey })),
    variables: z.record(ident, z.strictObject({ default: z.number(), min: z.number(), max: z.number() })),
    outputs: z.record(ident, z.string().min(1)),
    primary_output: ident,
    presets: z.strictObject({ expected: presetSchema, best: presetSchema, risk: presetSchema, no_action: presetSchema }),
  })
  .superRefine((s, ctx) => {
    if (!(s.primary_output in s.outputs)) {
      ctx.addIssue({ code: "custom", path: ["primary_output"], message: `primary_output "${s.primary_output}" is not an output` });
    }
    for (const [name, v] of Object.entries(s.variables)) {
      if (v.min > v.max || v.default < v.min || v.default > v.max) {
        ctx.addIssue({ code: "custom", path: ["variables", name], message: `variable "${name}" needs min <= default <= max` });
      }
      if (name in s.base) ctx.addIssue({ code: "custom", path: ["variables", name], message: `"${name}" is both a base and a variable` });
    }
  });
export type ScenarioTemplate = z.output<typeof scenarioSchema>;

export const glossarySchema = z.strictObject({
  terms: z.record(z.string(), z.strictObject({ en: z.string().min(1), vi: z.string().min(1) })).default({}),
});
export type Glossary = z.output<typeof glossarySchema>;

export const rolesSchema = z.strictObject({
  personas: z
    .record(ident, z.strictObject({ max_findings: z.number().int().min(1).max(20), sections: z.array(z.string().min(1)).min(1) }))
    .default({}),
});
export type Roles = z.output<typeof rolesSchema>;

const nonNeg = z.number().min(0);
const unit = z.number().min(0).max(1);
const pos = z.number().positive();
const bySeverity = <T extends z.ZodType>(t: T) =>
  z.strictObject({ critical: t, high: t, medium: t, warning: t, low: t });

export const scoringSchema = z.strictObject({
  priority_weights: z.strictObject({
    financial: nonNeg, urgency: nonNeg, confidence: nonNeg, target_variance: nonNeg,
    locations: nonNeg, repeated: nonNeg, strategic: nonNeg,
  }),
  urgency: bySeverity(unit),
  severity_by_impact: z.strictObject({
    sales_metric: metricKey,
    tiers: z.array(z.strictObject({ level: z.enum(SEVERITY_ORDER), min_amount: nonNeg, min_pct_weekly_sales: nonNeg })).min(1),
    otherwise: z.enum(SEVERITY_ORDER),
  }),
  normalization: z.strictObject({ target_variance_pct: pos, repeated_occurrences: pos }),
  strategic_rules: z.array(z.string()).default([]),
  resurfacing: z.strictObject({ impact_change_pct: pos, sample_growth_pct: pos }),
  confidence: z.strictObject({
    deviation_z_midpoint: z.number(),
    relative_z_scale: pos,
    freshness_current: unit,
    freshness_delayed: unit,
    min_interval_factor: unit,
  }),
  health_score: z.strictObject({
    components: z.record(ident, z.strictObject({ weight: nonNeg, rules: z.array(z.string().min(1)).min(1) })),
    data_quality_weight: nonNeg,
    severity_penalty: bySeverity(nonNeg),
    status_bands: z.array(z.strictObject({ min: z.number().min(0).max(100), label: z.string().min(1) })).min(1),
  }),
});
export type Scoring = z.output<typeof scoringSchema>;

export const rulesFileSchema = z.strictObject({ rules: z.array(ruleSchema).default([]) });
export const forecastsFileSchema = z.strictObject({ forecasts: z.array(forecastSchema).default([]) });
export const scenariosFileSchema = z.strictObject({ scenarios: z.array(scenarioSchema).default([]) });

export interface LoadedPack {
  /** Resolution order, parents first. */
  packs: { key: string; version: string }[];
  /** e.g. "base@0.1.0+child@0.2.0" — stored on every finding. */
  packVersion: string;
  rules: Rule[];
  forecasts: ForecastCfg[];
  scenarios: ScenarioTemplate[];
  glossary: Glossary;
  roles: Roles;
  scoring: Scoring;
}
```

- [ ] **Step 4: Implement loader** — `LAAM/src/lib/intel/pack/loader.ts`

```ts
// Reads `<PACKS_DIR>/<key>/pack.yaml` and `<key>/laam/*.yaml`, resolves `extends`, merges and
// validates every expression up front so a bad pack fails at load time, not mid-analysis.
import { readFile } from "node:fs/promises";
import path from "node:path";
import { parse as parseYaml } from "yaml";
import type { z } from "zod";
import { compileExpr, ExprError } from "../expr";
import {
  DAY_VARIABLES, forecastsFileSchema, glossarySchema, packMetaSchema, PRESET_NAMES, RULE_VARIABLES, rolesSchema,
  rulesFileSchema, scenariosFileSchema, scoringSchema,
  type ForecastCfg, type Glossary, type LoadedPack, type Roles, type Rule, type ScenarioTemplate,
} from "./schema";

export class PackError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PackError";
  }
}

const KEY_RE = /^[a-z][a-z0-9_]*$/;

export function packsDir(): string {
  return process.env.PACKS_DIR || "/packs";
}

async function readYaml(file: string): Promise<unknown | undefined> {
  let raw: string;
  try {
    raw = await readFile(file, "utf8");
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return undefined;
    throw e;
  }
  try {
    return parseYaml(raw);
  } catch (e) {
    throw new PackError(`${file}: invalid YAML: ${(e as Error).message}`);
  }
}

function parseWith<S extends z.ZodType>(schema: S, value: unknown, file: string): z.output<S> {
  const r = schema.safeParse(value ?? {});
  if (!r.success) {
    const issue = r.error.issues[0];
    throw new PackError(`${file}: ${issue.path.join(".") || "(root)"}: ${issue.message}`);
  }
  return r.data;
}

function checkExpr(source: string, allowed: readonly string[], where: string): void {
  let vars: ReadonlySet<string>;
  try {
    vars = compileExpr(source).variables;
  } catch (e) {
    if (e instanceof ExprError) throw new PackError(`${where}: ${e.message}`);
    throw e;
  }
  for (const v of vars) {
    if (!allowed.includes(v)) throw new PackError(`${where}: unknown variable "${v}" (allowed: ${allowed.join(", ")})`);
  }
}

type PackMeta = { key: string; version: string; extends: string[] };

async function resolveOrder(dir: string, enabled: readonly string[]): Promise<PackMeta[]> {
  const order: PackMeta[] = [];
  const done = new Set<string>();
  const visiting = new Set<string>();
  async function visit(key: string, chain: string[]): Promise<void> {
    if (!KEY_RE.test(key)) throw new PackError(`invalid pack key "${key}"`);
    if (done.has(key)) return;
    if (visiting.has(key)) throw new PackError(`extends cycle: ${[...chain, key].join(" -> ")}`);
    visiting.add(key);
    const file = path.join(dir, key, "pack.yaml");
    const raw = await readYaml(file);
    if (raw === undefined) throw new PackError(`${file}: pack not found`);
    const meta = parseWith(packMetaSchema, raw, file);
    if (meta.key !== key) throw new PackError(`${file}: key "${meta.key}" does not match directory "${key}"`);
    for (const parent of meta.extends) await visit(parent, [...chain, key]);
    visiting.delete(key);
    done.add(key);
    order.push({ key: meta.key, version: meta.version, extends: meta.extends });
  }
  for (const k of enabled) await visit(k, []);
  return order;
}

function validate(rules: Rule[], scenarios: ScenarioTemplate[]): void {
  const byKey = new Map(scenarios.map((s) => [s.key, s]));
  for (const r of rules) {
    const vars: string[] = [...RULE_VARIABLES, ...(r.count_days ? ["days_hit"] : [])];
    if (r.condition) checkExpr(r.condition, vars, `${r.rule_id} condition`);
    for (const [level, expr] of Object.entries(r.severity ?? {})) checkExpr(expr, vars, `${r.rule_id} severity.${level}`);
    if (r.impact) checkExpr(r.impact, vars, `${r.rule_id} impact`);
    if (r.count_days) checkExpr(r.count_days, DAY_VARIABLES, `${r.rule_id} count_days`);
    if (r.scenario_template) {
      const tpl = byKey.get(r.scenario_template);
      if (!tpl) throw new PackError(`${r.rule_id}: unknown scenario_template "${r.scenario_template}"`);
      if (r.driver) {
        if (!(r.driver.variable in tpl.variables)) {
          throw new PackError(`${r.rule_id}: driver variable "${r.driver.variable}" is not a variable of ${tpl.key}`);
        }
        checkExpr(r.driver.expr, vars, `${r.rule_id} driver.expr`);
      }
    }
  }
  for (const s of scenarios) {
    const allowed = [...Object.keys(s.base), ...Object.keys(s.variables)];
    for (const [name, expr] of Object.entries(s.outputs)) checkExpr(expr, allowed, `${s.key} output ${name}`);
    for (const preset of PRESET_NAMES) {
      for (const v of Object.keys(s.presets[preset].set)) {
        if (!(v in s.variables)) throw new PackError(`${s.key}: preset ${preset} sets unknown variable "${v}"`);
      }
    }
  }
}

export async function loadPacks(dir: string, enabled: readonly string[]): Promise<LoadedPack> {
  if (enabled.length === 0) throw new PackError("no packs enabled");
  const order = await resolveOrder(dir, enabled);

  const rules = new Map<string, Rule>();
  const forecasts = new Map<string, ForecastCfg>();
  const scenarios = new Map<string, ScenarioTemplate>();
  let glossary: Glossary = { terms: {} };
  let roles: Roles = { personas: {} };
  let scoringRaw: Record<string, unknown> | undefined;

  for (const meta of order) {
    const base = path.join(dir, meta.key, "laam");
    const rf = path.join(base, "rules.yaml");
    for (const r of parseWith(rulesFileSchema, await readYaml(rf), rf).rules) {
      if (r.overrides) {
        if (!rules.has(r.overrides)) throw new PackError(`${rf}: ${r.rule_id} overrides unknown rule ${r.overrides}`);
        rules.delete(r.overrides);
      } else if (rules.has(r.rule_id)) {
        throw new PackError(`${rf}: duplicate rule_id ${r.rule_id} (use overrides to replace a parent rule)`);
      }
      rules.set(r.rule_id, r);
    }
    const ff = path.join(base, "forecasts.yaml");
    for (const f of parseWith(forecastsFileSchema, await readYaml(ff), ff).forecasts) {
      forecasts.set(`${f.metric}|${[...f.dims].sort().join(",")}`, f);
    }
    const sf = path.join(base, "scenarios.yaml");
    for (const s of parseWith(scenariosFileSchema, await readYaml(sf), sf).scenarios) {
      if (scenarios.has(s.key)) throw new PackError(`${sf}: duplicate scenario key ${s.key}`);
      scenarios.set(s.key, s);
    }
    const gf = path.join(base, "glossary.yaml");
    const g = await readYaml(gf);
    if (g !== undefined) glossary = { terms: { ...glossary.terms, ...parseWith(glossarySchema, g, gf).terms } };
    const of = path.join(base, "roles.yaml");
    const ro = await readYaml(of);
    if (ro !== undefined) roles = { personas: { ...roles.personas, ...parseWith(rolesSchema, ro, of).personas } };
    const scf = path.join(base, "scoring.yaml");
    const sc = await readYaml(scf);
    if (sc !== undefined) {
      if (!sc || typeof sc !== "object" || Array.isArray(sc)) throw new PackError(`${scf}: must be a mapping`);
      scoringRaw = { ...(scoringRaw ?? {}), ...(sc as Record<string, unknown>) };
    }
  }
  if (!scoringRaw) throw new PackError(`no scoring.yaml in enabled packs (${order.map((o) => o.key).join(", ")})`);
  const scoring = parseWith(scoringSchema, scoringRaw, "scoring.yaml (merged)");

  const ruleList = [...rules.values()];
  const scenarioList = [...scenarios.values()];
  validate(ruleList, scenarioList);

  return {
    packs: order.map((o) => ({ key: o.key, version: o.version })),
    packVersion: order.map((o) => `${o.key}@${o.version}`).join("+"),
    rules: ruleList,
    forecasts: [...forecasts.values()],
    scenarios: scenarioList,
    glossary,
    roles,
    scoring,
  };
}
```

- [ ] **Step 5: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/pack/loader.test.ts
```
Expected: PASS 14/14.

- [ ] **Step 6: Commit**

```bash
git -C LAAM add src/lib/intel/pack
git -C LAAM commit -m "feat(intel): industry pack schema and loader with extends, overrides and expression checks"
```

---

### Task 7: Thời gian theo múi giờ dự án (`time.ts`)

**Files:**
- Create: `LAAM/src/lib/intel/time.ts`, `LAAM/src/lib/intel/time.test.ts`

**Interfaces:**
- Consumes: `nextRunAt` từ `@/lib/workflow/cron` (cron.ts — mốc phút **strictly >** `from`, theo getter **local** của server).
- Produces:
```ts
export interface DateWindow { from: string; to: string }        // YYYY-MM-DD, `to` exclusive
export function addDays(date: string, n: number): string;
export function daysBetween(from: string, to: string): number;  // to - from in days
export function localDate(now: Date, timeZone: string): string;
export function asOfDate(now: Date, timeZone: string): string;  // last complete local day
export function windowEnding(asOf: string, days: number): DateWindow;
export function shiftWindow(w: DateWindow, days: number): DateWindow;
export function monthToDate(asOf: string): { window: DateWindow; month: DateWindow; elapsedDays: number; daysInMonth: number };
export function nextRunInTimeZone(cron: string, after: Date, timeZone: string): Date;
```

Lý do: cron hiện có của workflow chạy theo giờ **server** (cron.ts:1-5 ghi "tz/DST hoãn"); job phân tích phải chạy theo giờ của project (`America/Chicago`) và "hôm qua" phải là ngày địa phương (spec §6.2 "period_date theo giờ địa phương").

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/lib/intel/time.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { addDays, asOfDate, daysBetween, localDate, monthToDate, nextRunInTimeZone, shiftWindow, windowEnding } from "./time";

describe("dates", () => {
  test("addDays crosses month and year boundaries", () => {
    expect(addDays("2026-07-31", 1)).toBe("2026-08-01");
    expect(addDays("2026-01-01", -1)).toBe("2025-12-31");
  });
  test("daysBetween", () => {
    expect(daysBetween("2026-07-01", "2026-08-01")).toBe(31);
  });
  test("localDate uses the project time zone, not the server's", () => {
    // 03:00 UTC on Oct 2 is still Oct 1 in Chicago (UTC-5 in October).
    expect(localDate(new Date("2026-10-02T03:00:00Z"), "America/Chicago")).toBe("2026-10-01");
    expect(localDate(new Date("2026-10-02T03:00:00Z"), "Asia/Ho_Chi_Minh")).toBe("2026-10-02");
  });
  test("asOfDate is the last complete local day", () => {
    expect(asOfDate(new Date("2026-10-02T12:00:00Z"), "America/Chicago")).toBe("2026-10-01");
  });
  test("windowEnding includes asOf and is end-exclusive", () => {
    expect(windowEnding("2026-07-31", 7)).toEqual({ from: "2026-07-25", to: "2026-08-01" });
    expect(shiftWindow({ from: "2026-07-25", to: "2026-08-01" }, -7)).toEqual({ from: "2026-07-18", to: "2026-07-25" });
  });
  test("monthToDate", () => {
    expect(monthToDate("2026-07-10")).toEqual({
      window: { from: "2026-07-01", to: "2026-07-11" },
      month: { from: "2026-07-01", to: "2026-08-01" },
      elapsedDays: 10,
      daysInMonth: 31,
    });
  });
});

describe("nextRunInTimeZone", () => {
  test("06:00 Chicago in daylight time is 11:00 UTC", () => {
    expect(nextRunInTimeZone("0 6 * * *", new Date("2026-10-02T10:00:00Z"), "America/Chicago").toISOString()).toBe("2026-10-02T11:00:00.000Z");
  });
  test("strictly after: a run at the slot moves to the next day", () => {
    expect(nextRunInTimeZone("0 6 * * *", new Date("2026-10-02T11:00:00Z"), "America/Chicago").toISOString()).toBe("2026-10-03T11:00:00.000Z");
  });
  test("06:00 Chicago in standard time is 12:00 UTC", () => {
    expect(nextRunInTimeZone("0 6 * * *", new Date("2026-11-10T00:00:00Z"), "America/Chicago").toISOString()).toBe("2026-11-10T12:00:00.000Z");
  });
  test("invalid time zones fail loudly", () => {
    expect(() => nextRunInTimeZone("0 6 * * *", new Date(), "Mars/Base")).toThrow(RangeError);
  });
});
```

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/time.test.ts
```
Expected: FAIL — `Cannot find module './time'`.

- [ ] **Step 3: Implement** — `LAAM/src/lib/intel/time.ts`

```ts
// Calendar helpers in the PROJECT's time zone. Day strings are YYYY-MM-DD; windows are
// [from, to) like the metrics contract (master §2.4).
import { nextRunAt as cronNext } from "@/lib/workflow/cron";

export interface DateWindow {
  from: string;
  to: string;
}

const pad = (n: number): string => String(n).padStart(2, "0");

export function addDays(date: string, n: number): string {
  const d = new Date(date + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to + "T00:00:00Z") - Date.parse(from + "T00:00:00Z")) / 86_400_000);
}

const formatters = new Map<string, Intl.DateTimeFormat>();
function formatter(timeZone: string): Intl.DateTimeFormat {
  let f = formatters.get(timeZone);
  if (!f) {
    // Throws RangeError for an unknown zone — fail loud rather than silently using UTC.
    f = new Intl.DateTimeFormat("en-US", {
      timeZone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
    formatters.set(timeZone, f);
  }
  return f;
}

interface WallClock { year: number; month: number; day: number; hour: number; minute: number; second: number }

function wallClock(d: Date, timeZone: string): WallClock {
  const parts = formatter(timeZone).formatToParts(d);
  const get = (type: Intl.DateTimeFormatPartTypes): number => Number(parts.find((p) => p.type === type)?.value);
  return { year: get("year"), month: get("month"), day: get("day"), hour: get("hour"), minute: get("minute"), second: get("second") };
}

export function localDate(now: Date, timeZone: string): string {
  const w = wallClock(now, timeZone);
  return `${w.year}-${pad(w.month)}-${pad(w.day)}`;
}

export function asOfDate(now: Date, timeZone: string): string {
  return addDays(localDate(now, timeZone), -1);
}

export function windowEnding(asOf: string, days: number): DateWindow {
  return { from: addDays(asOf, -(days - 1)), to: addDays(asOf, 1) };
}

export function shiftWindow(w: DateWindow, days: number): DateWindow {
  return { from: addDays(w.from, days), to: addDays(w.to, days) };
}

export function monthToDate(asOf: string): { window: DateWindow; month: DateWindow; elapsedDays: number; daysInMonth: number } {
  const monthStart = asOf.slice(0, 8) + "01";
  const [y, m] = monthStart.split("-").map(Number);
  const nextMonth = m === 12 ? `${y + 1}-01-01` : `${y}-${pad(m + 1)}-01`;
  return {
    window: { from: monthStart, to: addDays(asOf, 1) },
    month: { from: monthStart, to: nextMonth },
    elapsedDays: daysBetween(monthStart, asOf) + 1,
    daysInMonth: daysBetween(monthStart, nextMonth),
  };
}

function offsetMs(instant: number, timeZone: string): number {
  const w = wallClock(new Date(instant), timeZone);
  return Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute, w.second) - Math.floor(instant / 1000) * 1000;
}

/**
 * Next cron slot strictly after `after`, with the cron fields read in `timeZone`. The workflow
 * cron matcher reads server-local getters, so we hand it a server-local Date that carries the
 * zone's wall clock, then convert the matched wall clock back to an instant.
 */
export function nextRunInTimeZone(cron: string, after: Date, timeZone: string): Date {
  const w = wallClock(after, timeZone);
  const carrier = new Date(w.year, w.month - 1, w.day, w.hour, w.minute, w.second, 0);
  const next = cronNext(cron, carrier);
  const wallUtc = Date.UTC(next.getFullYear(), next.getMonth(), next.getDate(), next.getHours(), next.getMinutes(), 0, 0);
  let instant = wallUtc - offsetMs(wallUtc, timeZone);
  const corrected = wallUtc - offsetMs(instant, timeZone);
  if (corrected !== instant) instant = corrected; // the guess crossed a DST change
  return new Date(instant);
}
```

- [ ] **Step 4: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/time.test.ts
```
Expected: PASS 10/10.

- [ ] **Step 5: Commit**

```bash
git -C LAAM add src/lib/intel/time.ts src/lib/intel/time.test.ts
git -C LAAM commit -m "feat(intel): project time-zone calendar helpers and zoned cron"
```

---

### Task 8: `rule_override` — precedence customer → location → category → pack

**Files:**
- Create: `LAAM/src/lib/intel/overrides.ts`, `LAAM/src/lib/intel/overrides.test.ts`

**Interfaces:**
- Consumes: `Rule`, `Scoring`, `ScenarioTemplate`, `SEVERITY_ORDER`, `PRESET_NAMES` (Task 6); `compileExpr` (Task 2).
- Produces:
```ts
export interface OverrideRow { targetKey: string; scope: { location_id?: string; category?: string }; value: Record<string, unknown> }
export type OverrideLevel = "customer" | "location" | "category";
export class OverrideError extends Error {}
export function scopeKeyOf(scope: OverrideRow["scope"]): string;      // "" | "location:<id>" | "category:<name>"
export function pickOverride(rows: readonly OverrideRow[], targetKey: string, dims: Readonly<Record<string, string>>): { row: OverrideRow; level: OverrideLevel } | null;
export function resolveRule(rule: Rule, rows: readonly OverrideRow[], dims: Readonly<Record<string, string>>): { rule: Rule; source: "pack" | OverrideLevel };
export function resolvePriorityWeights(scoring: Scoring, rows: readonly OverrideRow[]): Scoring["priority_weights"];
export function resolvePresetSets(tpl: ScenarioTemplate, rows: readonly OverrideRow[]): Record<PresetName, Record<string, number>>;
```

Quy ước: "customer" = override không có `location_id` lẫn `category`; override có cả hai được coi là cấp location. Trường override được của rule: `condition`, `severity`, `impact`, `min_sample`, `cooldown_days`, `disabled_reason` (`null` ⇒ bật lại). `window_days`/`compare`/`metric` **không** override được (đổi cửa sổ theo từng nhóm sẽ phá việc gọi provider một lần cho cả rule). Override lỗi ⇒ `OverrideError` (engine ghi vào skip của rule, không chạy với ngưỡng sai).

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/lib/intel/overrides.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { OverrideError, pickOverride, resolvePresetSets, resolvePriorityWeights, resolveRule, scopeKeyOf, type OverrideRow } from "./overrides";
import { ruleSchema, scenarioSchema, type Scoring } from "./pack/schema";

const rule = ruleSchema.parse({
  rule_id: "ACME-REV-001", version: 1, name: "Revenue drop", metric: "acme.revenue", dims: ["location_id"],
  window_days: 7, compare: "previous_period", condition: "value <= 0.9 * compare_value",
  recommended_action: "investigate", default_owner_role: "manager", cooldown_days: 7, wording: "Revenue dropped",
});
const row = (scope: OverrideRow["scope"], condition: string): OverrideRow => ({ targetKey: "ACME-REV-001", scope, value: { condition } });

describe("pickOverride precedence (customer -> location -> category -> pack)", () => {
  const rows = [
    row({ category: "food" }, "value <= 0.7 * compare_value"),
    row({ location_id: "L1" }, "value <= 0.8 * compare_value"),
    row({}, "value <= 0.85 * compare_value"),
  ];
  // Why: the request lists threshold precedence as customer, location, category, pack default.
  // Implemented literally — the first matching level wins.
  test("a customer-wide override wins over location and category overrides", () => {
    expect(pickOverride(rows, "ACME-REV-001", { location_id: "L1", category: "food" })?.level).toBe("customer");
  });
  test("location wins over category when there is no customer override", () => {
    expect(pickOverride(rows.slice(0, 2), "ACME-REV-001", { location_id: "L1", category: "food" })?.level).toBe("location");
  });
  test("category applies when location does not match", () => {
    expect(pickOverride(rows.slice(0, 2), "ACME-REV-001", { location_id: "L9", category: "food" })?.level).toBe("category");
  });
  test("no match falls back to the pack default", () => {
    expect(pickOverride(rows.slice(0, 2), "ACME-REV-001", { location_id: "L9" })).toBeNull();
    expect(resolveRule(rule, rows.slice(0, 2), { location_id: "L9" })).toEqual({ rule, source: "pack" });
  });
});

describe("resolveRule", () => {
  test("merges only the overridden fields", () => {
    const out = resolveRule(rule, [{ targetKey: "ACME-REV-001", scope: { location_id: "L1" }, value: { min_sample: 50, severity: { high: "value <= 0.5 * compare_value" } } }], { location_id: "L1" });
    expect(out.source).toBe("location");
    expect(out.rule).toMatchObject({ condition: rule.condition, min_sample: 50, severity: { high: "value <= 0.5 * compare_value" } });
  });
  test("can disable and re-enable a rule", () => {
    const off = resolveRule(rule, [{ targetKey: "ACME-REV-001", scope: {}, value: { disabled_reason: "seasonal store" } }], {});
    expect(off.rule.disabled_reason).toBe("seasonal store");
    const on = resolveRule({ ...rule, disabled_reason: "threshold_tbd" }, [{ targetKey: "ACME-REV-001", scope: {}, value: { disabled_reason: null } }], {});
    expect(on.rule.disabled_reason).toBeUndefined();
  });
  test("an override that sets the threshold makes it confirmed for that scope (E11)", () => {
    const provisional = { ...rule, threshold_status: "provisional" as const, threshold_note: "Demo default" };
    const out = resolveRule(provisional, [{ targetKey: "ACME-REV-001", scope: { location_id: "L1" }, value: { condition: "value <= 0.8 * compare_value" } }], { location_id: "L1" });
    expect(out.rule).toMatchObject({ threshold_status: "confirmed", threshold_note: undefined });
    expect(resolveRule(provisional, [], { location_id: "L1" }).rule.threshold_status).toBe("provisional"); // other scopes keep the default
    const stillTemp = resolveRule(provisional, [{ targetKey: "ACME-REV-001", scope: {}, value: { condition: "value <= 0.8 * compare_value", threshold_status: "provisional", threshold_note: "Trial value" } }], {});
    expect(stillTemp.rule).toMatchObject({ threshold_status: "provisional", threshold_note: "Trial value" });
    expect(() => resolveRule(provisional, [{ targetKey: "ACME-REV-001", scope: {}, value: { threshold_status: "provisional" } }], {})).toThrow(OverrideError);
    const cooldownOnly = resolveRule(provisional, [{ targetKey: "ACME-REV-001", scope: {}, value: { cooldown_days: 3 } }], {});
    expect(cooldownOnly.rule.threshold_status).toBe("provisional"); // not a threshold change
  });

  test("rejects unknown fields and broken expressions instead of running with them", () => {
    expect(() => resolveRule(rule, [{ targetKey: "ACME-REV-001", scope: {}, value: { window_days: 3 } }], {})).toThrow(OverrideError);
    expect(() => resolveRule(rule, [{ targetKey: "ACME-REV-001", scope: {}, value: { condition: "value <=" } }], {})).toThrow(OverrideError);
  });
});

describe("scopeKeyOf", () => {
  test("canonical scope keys", () => {
    expect(scopeKeyOf({})).toBe("");
    expect(scopeKeyOf({ location_id: "L1", category: "x" })).toBe("location:L1");
    expect(scopeKeyOf({ category: "x" })).toBe("category:x");
  });
});

describe("priority weights and scenario presets", () => {
  const weights: Scoring["priority_weights"] = { financial: 30, urgency: 20, confidence: 15, target_variance: 10, locations: 10, repeated: 10, strategic: 5 };
  test("customer override replaces individual weights", () => {
    const out = resolvePriorityWeights({ priority_weights: weights } as Scoring, [{ targetKey: "priority_weights", scope: {}, value: { financial: 40, strategic: 0 } }]);
    expect(out).toEqual({ ...weights, financial: 40, strategic: 0 });
  });
  test("preset overrides replace a preset's variable settings", () => {
    const tpl = scenarioSchema.parse({
      key: "acme.change", label: "Change", dims: ["location_id"], base: { revenue: { forecast_of: "acme.revenue" } },
      variables: { change_pct: { default: 0, min: -30, max: 30 } }, outputs: { out: "revenue * (1 + change_pct / 100)" }, primary_output: "out",
      presets: { expected: { trend: "damped" }, best: { trend: "damped", set: { change_pct: 5 } }, risk: { trend: "damped", set: { change_pct: -5 } }, no_action: { trend: "persist_driver" } },
    });
    const sets = resolvePresetSets(tpl, [{ targetKey: "scenario:acme.change:best", scope: {}, value: { set: { change_pct: 8 } } }]);
    expect(sets).toEqual({ expected: {}, best: { change_pct: 8 }, risk: { change_pct: -5 }, no_action: {} });
  });
});
```

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/overrides.test.ts
```
Expected: FAIL — `Cannot find module './overrides'`.

- [ ] **Step 3: Implement** — `LAAM/src/lib/intel/overrides.ts`

```ts
// Project-level overrides of pack defaults (spec §5.3, §7.4 rule_override). Precedence is the
// request's list taken literally: customer-wide, then location, then category, then the pack.
import { z } from "zod";
import { compileExpr, ExprError } from "./expr";
import {
  PRESET_NAMES, SEVERITY_ORDER,
  type PresetName, type Rule, type ScenarioTemplate, type Scoring,
} from "./pack/schema";

export interface OverrideRow {
  targetKey: string;
  scope: { location_id?: string; category?: string };
  value: Record<string, unknown>;
}
export type OverrideLevel = "customer" | "location" | "category";

export class OverrideError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OverrideError";
  }
}

const ruleOverrideValue = z.strictObject({
  condition: z.string().min(1).optional(),
  severity: z.partialRecord(z.enum(SEVERITY_ORDER), z.string().min(1)).optional(),
  impact: z.string().min(1).nullable().optional(),
  min_sample: z.number().int().min(0).optional(),
  cooldown_days: z.number().int().min(0).optional(),
  disabled_reason: z.string().min(1).nullable().optional(), // null re-enables
  threshold_status: z.enum(["confirmed", "provisional"]).optional(), // E11
  threshold_note: z.string().min(1).optional(),
});
const weightsOverride = z.strictObject({
  financial: z.number().min(0).optional(),
  urgency: z.number().min(0).optional(),
  confidence: z.number().min(0).optional(),
  target_variance: z.number().min(0).optional(),
  locations: z.number().min(0).optional(),
  repeated: z.number().min(0).optional(),
  strategic: z.number().min(0).optional(),
});
const presetOverride = z.strictObject({ set: z.record(z.string(), z.number()) });

function levelOf(scope: OverrideRow["scope"]): OverrideLevel {
  if (scope.location_id) return "location";
  if (scope.category) return "category";
  return "customer";
}

export function scopeKeyOf(scope: OverrideRow["scope"]): string {
  if (scope.location_id) return `location:${scope.location_id}`;
  if (scope.category) return `category:${scope.category}`;
  return "";
}

export function pickOverride(
  rows: readonly OverrideRow[],
  targetKey: string,
  dims: Readonly<Record<string, string>>,
): { row: OverrideRow; level: OverrideLevel } | null {
  const mine = rows.filter((r) => r.targetKey === targetKey);
  const customer = mine.find((r) => levelOf(r.scope) === "customer");
  if (customer) return { row: customer, level: "customer" };
  const loc = dims.location_id;
  const byLocation = loc !== undefined ? mine.find((r) => r.scope.location_id === loc) : undefined;
  if (byLocation) return { row: byLocation, level: "location" };
  const cat = dims.category;
  const byCategory = cat !== undefined ? mine.find((r) => levelOf(r.scope) === "category" && r.scope.category === cat) : undefined;
  if (byCategory) return { row: byCategory, level: "category" };
  return null;
}

export function resolveRule(
  rule: Rule,
  rows: readonly OverrideRow[],
  dims: Readonly<Record<string, string>>,
): { rule: Rule; source: "pack" | OverrideLevel } {
  const hit = pickOverride(rows, rule.rule_id, dims);
  if (!hit) return { rule, source: "pack" };
  const parsed = ruleOverrideValue.safeParse(hit.row.value);
  if (!parsed.success) {
    throw new OverrideError(`override of ${rule.rule_id} (${hit.level}) is invalid: ${parsed.error.issues[0]?.message ?? "invalid"}`);
  }
  const v = parsed.data;
  const merged: Rule = { ...rule };
  if (v.condition !== undefined) merged.condition = v.condition;
  if (v.severity !== undefined) merged.severity = v.severity;
  if (v.impact !== undefined) merged.impact = v.impact;
  if (v.min_sample !== undefined) merged.min_sample = v.min_sample;
  if (v.cooldown_days !== undefined) merged.cooldown_days = v.cooldown_days;
  if (v.disabled_reason !== undefined) merged.disabled_reason = v.disabled_reason ?? undefined;
  // E11: an override that sets the trigger or its tiers is the customer's own threshold for this
  // scope -> confirmed, unless the override itself says it is provisional.
  const setsThreshold = v.condition !== undefined || v.severity !== undefined || v.min_sample !== undefined;
  if (setsThreshold || v.threshold_status !== undefined) {
    const status = v.threshold_status ?? "confirmed";
    if (status === "provisional" && !v.threshold_note) {
      throw new OverrideError(`override of ${rule.rule_id} (${hit.level}): provisional threshold requires threshold_note`);
    }
    merged.threshold_status = status;
    merged.threshold_note = status === "provisional" ? v.threshold_note : undefined;
  }
  for (const expr of [merged.condition, merged.impact, ...Object.values(merged.severity ?? {})]) {
    if (!expr) continue;
    try {
      compileExpr(expr);
    } catch (e) {
      if (e instanceof ExprError) throw new OverrideError(`override of ${rule.rule_id} (${hit.level}): ${e.message}`);
      throw e;
    }
  }
  return { rule: merged, source: hit.level };
}

export function resolvePriorityWeights(scoring: Scoring, rows: readonly OverrideRow[]): Scoring["priority_weights"] {
  const hit = pickOverride(rows, "priority_weights", {});
  if (!hit) return scoring.priority_weights;
  const parsed = weightsOverride.safeParse(hit.row.value);
  if (!parsed.success) throw new OverrideError(`priority_weights override is invalid: ${parsed.error.issues[0]?.message ?? "invalid"}`);
  return { ...scoring.priority_weights, ...parsed.data };
}

export function resolvePresetSets(tpl: ScenarioTemplate, rows: readonly OverrideRow[]): Record<PresetName, Record<string, number>> {
  const out = {} as Record<PresetName, Record<string, number>>;
  for (const name of PRESET_NAMES) {
    const hit = pickOverride(rows, `scenario:${tpl.key}:${name}`, {});
    if (!hit) {
      out[name] = { ...tpl.presets[name].set };
      continue;
    }
    const parsed = presetOverride.safeParse(hit.row.value);
    if (!parsed.success) throw new OverrideError(`override of ${tpl.key}:${name} is invalid`);
    for (const k of Object.keys(parsed.data.set)) {
      if (!(k in tpl.variables)) throw new OverrideError(`override of ${tpl.key}:${name} sets unknown variable "${k}"`);
    }
    out[name] = { ...parsed.data.set };
  }
  return out;
}
```

- [ ] **Step 4: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/overrides.test.ts
```
Expected: PASS 11/11.

- [ ] **Step 5: Commit**

```bash
git -C LAAM add src/lib/intel/overrides.ts src/lib/intel/overrides.test.ts
git -C LAAM commit -m "feat(intel): rule overrides with customer, location, category precedence"
```

---

### Task 9: Rule engine (cửa sổ, 5 chế độ so sánh, min_sample, severity, impact, count_days)

**Files:**
- Create: `LAAM/src/lib/intel/engine/rules.ts`, `LAAM/src/lib/intel/engine/rules.test.ts`

**Interfaces:**
- Consumes: `MetricsProvider` (Task 3), `aggregate.ts` (Task 3), `evalBool/evalNumber/ExprError` (Task 2), `Rule/Severity/SEVERITY_ORDER` (Task 6), `windowEnding/shiftWindow/monthToDate` (Task 7), `resolveRule/OverrideRow` (Task 8).
- Produces:
```ts
export interface RuleContext {
  provider: MetricsProvider;
  asOf: string;                                   // last complete local day (time.asOfDate)
  catalog: ReadonlyMap<string, MetricCatalogItem>;
  disabledMetrics: ReadonlyMap<string, string>;   // from getDataStatus().disabledMetrics
  overrides: readonly OverrideRow[];
}
export interface Comparison { mode: CompareMode; windows: DateWindow[]; peerCount?: number; targetMonth?: DateWindow; prorated?: { elapsedDays: number; daysInMonth: number } | null }
export interface RuleCandidate {
  rule: Rule; ruleSource: "pack" | OverrideLevel; metricKey: string; aggregation: Aggregation; unit: string; scale: number;
  dims: Record<string, string>; window: DateWindow; value: number; compareValue: number | null; sigma: number | null;
  numerator: number | null; denominator: number | null; sampleSize: number; variance: number | null; variancePct: number | null;
  severity: Severity | null; severityReason: string | null; impact: number | null; impactUnit: string | null;
  vars: Record<string, number>; comparison: Comparison; dataStatus: DataStatusItem[];
}
export interface RuleSkip { ruleId: string; reason: string }
export interface RuleEvaluation { candidates: RuleCandidate[]; skipped: RuleSkip[] }
export async function evaluateRule(rule: Rule, ctx: RuleContext): Promise<RuleEvaluation>;
export async function evaluateRules(rules: readonly Rule[], ctx: RuleContext): Promise<RuleEvaluation>;
```

Định nghĩa so sánh (ghi vào comment code, test pin từng cái):
- `peer_average`: peer = **mọi nhóm khác** cùng `dims` của rule trong cùng cửa sổ (toàn chuỗi — "company or peer average"); ratio = `scale·Σnum/Σden` các peer; additive/snapshot = trung bình giá trị peer; `sigma` = độ lệch chuẩn giá trị peer.
- `previous_period`: cửa sổ cùng độ dài liền trước.
- `baseline_same_weekday_4w`: 4 cửa sổ lùi `k × 7 × ceil(W/7)` ngày (k = 1..4) ⇒ cùng thứ trong tuần, không chồng nhau; cần **đủ 4** cửa sổ có số liệu; ratio gộp tổng tử/mẫu, additive lấy trung bình; `sigma` = độ lệch chuẩn 4 giá trị.
- `target`: cửa sổ = **từ đầu tháng tới `asOf`**; target lấy `target_metric` grain `month` của tháng đó; metric additive ⇒ target × `elapsedDays/daysInMonth`; ratio/snapshot ⇒ target nguyên (spec §6.4 "target theo kỳ"). `window_days` bị bỏ qua.
- `none`: không có `compare_value`.
- Severity: duyệt `critical → high → medium → warning → low`, mức đầu tiên đúng; rule không có `severity` (hoặc không mức nào đúng) ⇒ `severity: null` ⇒ pipeline quyết theo impact (Task 11).
- Nhóm thiếu `compare_value` khi điều kiện cần nó (không có peer, baseline thiếu tuần) ⇒ bỏ nhóm, ghi `compare_unavailable` vào `skipped`.
- Rule không có `condition`/có `disabled_reason` (sau override cấp customer, khi không có override cấp location/category nào) ⇒ `skipped` với lý do; metric không có trong catalog ⇒ `metric_unknown:<key>`; metric tắt ⇒ `metric_disabled:<key>: <lý do>`.

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/lib/intel/engine/rules.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { evaluateRule, evaluateRules, type RuleContext } from "./rules";
import { FakeMetricsProvider, type FakeMetricData } from "../provider/fake";
import { ruleSchema, type Rule } from "../pack/schema";
import { catalogItem, currentStatus, dailyPoints } from "../testing/fixtures";
import type { OverrideRow } from "../overrides";

const ASOF = "2026-07-31";

function rule(over: Record<string, unknown>): Rule {
  return ruleSchema.parse({
    rule_id: "ACME-T-001", version: 1, name: "t", metric: "acme.revenue", dims: ["location_id"], window_days: 7,
    compare: "previous_period", condition: "value >= 1.05 * compare_value", recommended_action: "investigate",
    default_owner_role: "manager", cooldown_days: 7, wording: "w", ...over,
  });
}

function ctx(data: FakeMetricData, overrides: OverrideRow[] = [], asOf = ASOF): RuleContext & { fake: FakeMetricsProvider } {
  const fake = new FakeMetricsProvider(data);
  return {
    fake, provider: fake, asOf, overrides,
    catalog: new Map(data.catalog.map((c) => [c.key, c])),
    disabledMetrics: new Map((data.disabledMetrics ?? []).map((d) => [d.metricKey, d.reason])),
  };
}

describe("peer_average", () => {
  const data: FakeMetricData = {
    catalog: [catalogItem("acme.refund_rate", "ratio", ["location_id", "employee_id"])],
    points: {
      "acme.refund_rate": [
        { period: "2026-07-20", dims: { location_id: "L1", employee_id: "E1" }, value: 30, numerator: 30, denominator: 100, sampleSize: 12 },
        { period: "2026-07-20", dims: { location_id: "L1", employee_id: "E2" }, value: 2, numerator: 2, denominator: 100, sampleSize: 10 },
        { period: "2026-07-20", dims: { location_id: "L2", employee_id: "E3" }, value: 100, numerator: 1, denominator: 1, sampleSize: 1 },
      ],
    },
    dataStatus: currentStatus(["acme.refund_rate"]),
  };
  const r = rule({ metric: "acme.refund_rate", dims: ["location_id", "employee_id"], window_days: 30, compare: "peer_average", min_sample: 10, condition: "value >= 2.5 * compare_value", impact: "numerator - compare_value / 100 * denominator", impact_unit: "currency" });

  // Why: the mean of peer rates would be (2 + 100) / 2 = 51% because one peer had a single
  // event; the true peer rate is 3 / 101 = 2.97%. Using the mean hides the real outlier.
  test("peer average for a ratio metric is ratio-of-sums over peers", async () => {
    const { candidates } = await evaluateRule(r, ctx(data));
    const e1 = candidates.find((c) => c.dims.employee_id === "E1")!;
    expect(e1).toBeDefined();
    expect(e1.compareValue).toBeCloseTo((100 * 3) / 101, 10);
    expect(e1.comparison).toMatchObject({ mode: "peer_average", peerCount: 2 });
    expect(e1.impact).toBeCloseTo(30 - ((100 * 3) / 101 / 100) * 100, 10);
    expect(e1.severity).toBeNull(); // no tier in the rule => decided from impact later
  });

  test("groups below min_sample never become findings but still count as peers", async () => {
    const { candidates } = await evaluateRule(r, ctx(data));
    expect(candidates.map((c) => c.dims.employee_id)).toEqual(["E1"]);
  });

  test("a location override can raise min_sample for one location", async () => {
    const { candidates } = await evaluateRule(r, ctx(data, [{ targetKey: "ACME-T-001", scope: { location_id: "L1" }, value: { min_sample: 20 } }]));
    expect(candidates).toHaveLength(0);
  });
});

describe("baseline_same_weekday_4w", () => {
  const data: FakeMetricData = {
    catalog: [catalogItem("acme.revenue", "additive", ["location_id"])],
    points: {
      "acme.revenue": [
        ...dailyPoints("2026-06-27", 28, { location_id: "L1" }, () => ({ value: 100, sampleSize: 5 })),
        ...dailyPoints("2026-07-25", 7, { location_id: "L1" }, () => ({ value: 70, sampleSize: 5 })),
        ...dailyPoints("2026-07-25", 7, { location_id: "L2" }, () => ({ value: 10, sampleSize: 5 })),
      ],
    },
    dataStatus: currentStatus(["acme.revenue"]),
  };
  const r = rule({
    compare: "baseline_same_weekday_4w", condition: "value <= 0.95 * compare_value",
    severity: { critical: "value <= 0.80 * compare_value", high: "value <= 0.90 * compare_value", warning: "value <= 0.95 * compare_value" },
    impact: "compare_value - value", impact_unit: "currency",
  });

  test("compares the last 7 days to the mean of the four prior same-weekday windows", async () => {
    const { candidates } = await evaluateRule(r, ctx(data));
    const l1 = candidates.find((c) => c.dims.location_id === "L1")!;
    expect(l1.value).toBe(490);
    expect(l1.compareValue).toBe(700);
    expect(l1.variancePct).toBeCloseTo(-30, 10);
    expect(l1.severity).toBe("critical"); // highest matching tier wins
    expect(l1.impact).toBe(210);
    expect(l1.comparison.windows).toEqual([
      { from: "2026-07-18", to: "2026-07-25" }, { from: "2026-07-11", to: "2026-07-18" },
      { from: "2026-07-04", to: "2026-07-11" }, { from: "2026-06-27", to: "2026-07-04" },
    ]);
  });

  test("a location without four baseline windows is skipped and reported", async () => {
    const out = await evaluateRule(r, ctx(data));
    expect(out.candidates.map((c) => c.dims.location_id)).toEqual(["L1"]);
    expect(out.skipped).toContainEqual({ ruleId: "ACME-T-001", reason: "compare_unavailable for 1 group(s)" });
  });
});

describe("previous_period and severity tiers", () => {
  const data: FakeMetricData = {
    catalog: [catalogItem("acme.revenue", "additive", ["location_id"])],
    points: {
      "acme.revenue": [
        ...dailyPoints("2026-07-18", 7, { location_id: "L1" }, () => ({ value: 100 })),
        ...dailyPoints("2026-07-25", 7, { location_id: "L1" }, () => ({ value: 108 })),
      ],
    },
  };
  test("picks the highest tier whose expression holds", async () => {
    const r = rule({ severity: { critical: "value >= 1.20 * compare_value", high: "value >= 1.10 * compare_value", warning: "value >= 1.05 * compare_value" } });
    const [c] = (await evaluateRule(r, ctx(data))).candidates;
    expect(c.compareValue).toBe(700);
    expect(c.severity).toBe("warning");
    expect(c.severityReason).toBe("warning: value >= 1.05 * compare_value");
  });
});

describe("target (month-to-date)", () => {
  test("additive targets are prorated by elapsed days; ratio targets are not", async () => {
    const data: FakeMetricData = {
      catalog: [
        catalogItem("acme.revenue", "additive", ["location_id"]),
        catalogItem("acme.target_revenue", "snapshot", ["location_id"], { grain: "month" }),
        catalogItem("acme.margin_pct", "ratio", ["location_id"]),
        catalogItem("acme.target_margin_pct", "snapshot", ["location_id"], { grain: "month" }),
      ],
      points: {
        "acme.revenue": dailyPoints("2026-07-01", 10, { location_id: "L1" }, () => ({ value: 80 })),
        "acme.target_revenue": [{ period: "2026-07-01", dims: { location_id: "L1" }, value: 3100, numerator: null, denominator: null, sampleSize: 1 }],
        "acme.margin_pct": dailyPoints("2026-07-01", 10, { location_id: "L1" }, () => ({ value: 35, numerator: 35, denominator: 100 })),
        "acme.target_margin_pct": [{ period: "2026-07-01", dims: { location_id: "L1" }, value: 40, numerator: null, denominator: null, sampleSize: 1 }],
      },
    };
    const c1 = ctx(data, [], "2026-07-10");
    const rev = (await evaluateRule(rule({ compare: "target", target_metric: "acme.target_revenue", condition: "value < compare_value" }), c1)).candidates[0];
    expect(rev.value).toBe(800);
    expect(rev.compareValue).toBeCloseTo(1000, 10);
    expect(rev.window).toEqual({ from: "2026-07-01", to: "2026-07-11" });
    expect(rev.comparison.prorated).toEqual({ elapsedDays: 10, daysInMonth: 31 });
    const mar = (await evaluateRule(rule({ metric: "acme.margin_pct", compare: "target", target_metric: "acme.target_margin_pct", condition: "value <= compare_value - 2" }), c1)).candidates[0];
    expect(mar.value).toBeCloseTo(35, 10);
    expect(mar.compareValue).toBe(40);
    expect(mar.comparison.prorated).toBeNull();
  });
});

describe("none + count_days", () => {
  const data: FakeMetricData = {
    catalog: [catalogItem("acme.cash_diff", "additive", ["location_id", "employee_id"])],
    points: {
      "acme.cash_diff": [
        ...dailyPoints("2026-07-01", 30, { location_id: "L1", employee_id: "E1" }, (i) => ({ value: [3, 7, 12].includes(i) ? -30 : 1 })),
        ...dailyPoints("2026-07-01", 30, { location_id: "L2", employee_id: "E2" }, (i) => ({ value: [3, 7].includes(i) ? -30 : 1 })),
      ],
    },
  };
  const r = rule({ metric: "acme.cash_diff", dims: ["location_id", "employee_id"], window_days: 31, compare: "none", count_days: "value <= -25", condition: "days_hit >= 3", impact: "-min(value, 0)" });

  test("counts qualifying days per group", async () => {
    const { candidates } = await evaluateRule(r, ctx(data));
    expect(candidates.map((c) => [c.dims.employee_id, c.vars.days_hit])).toEqual([["E1", 3]]);
    expect(candidates[0].compareValue).toBeNull();
  });

  // Why: daily series for every group in one call can exceed the MCP result cap (200k chars);
  // per-location calls keep each response small.
  test("daily fetches are split by the first rule dim", async () => {
    const c = ctx(data);
    await evaluateRule(r, c);
    const daily = c.fake.calls.filter((x) => (x.args as { grain?: string } | null)?.grain === "day");
    expect(daily.map((x) => (x.args as { dimsFilter: Record<string, string[]> }).dimsFilter)).toEqual([{ location_id: ["L1"] }, { location_id: ["L2"] }]);
  });
});

describe("ratio scale guard", () => {
  // Why (review): thresholds like "compare_value - 2" assume percentage points; a source reporting
  // a 0-1 rate for a "percent" metric would make every such rule wrong without any error.
  test("a percent ratio reported as a 0-1 fraction skips the rule with a reason", async () => {
    const data: FakeMetricData = {
      catalog: [catalogItem("acme.margin_pct", "ratio", ["location_id"])],
      points: { "acme.margin_pct": dailyPoints("2026-07-18", 14, { location_id: "L1" }, () => ({ value: 0.35, numerator: 35, denominator: 100 })) },
    };
    const out = await evaluateRule(rule({ metric: "acme.margin_pct", condition: "value <= compare_value - 2" }), ctx(data));
    expect(out.candidates).toHaveLength(0);
    expect(out.skipped[0].reason).toMatch(/^ratio_scale_mismatch:acme.margin_pct/);
  });
});

describe("unknown dims", () => {
  // Why: DAAB stores a NULL dimension as "" — an "unknown approver" bucket must not be flagged as
  // a person nor drag the peer average.
  test("groups with an empty dim value are neither subjects nor peers", async () => {
    const data: FakeMetricData = {
      catalog: [catalogItem("acme.override_count", "additive", ["location_id", "approver_id"])],
      points: {
        "acme.override_count": [
          { period: "2026-07-20", dims: { location_id: "L1", approver_id: "" }, value: 500, numerator: null, denominator: null, sampleSize: 500 },
          { period: "2026-07-20", dims: { location_id: "L1", approver_id: "A1" }, value: 30, numerator: null, denominator: null, sampleSize: 30 },
          { period: "2026-07-20", dims: { location_id: "L1", approver_id: "A2" }, value: 10, numerator: null, denominator: null, sampleSize: 10 },
          { period: "2026-07-20", dims: { location_id: "L2", approver_id: "A3" }, value: 10, numerator: null, denominator: null, sampleSize: 10 },
        ],
      },
    };
    const r = rule({ metric: "acme.override_count", dims: ["location_id", "approver_id"], window_days: 30, compare: "peer_average", condition: "value > 2.5 * compare_value" });
    const { candidates } = await evaluateRule(r, ctx(data));
    expect(candidates.map((c) => c.dims.approver_id)).toEqual(["A1"]);
    expect(candidates[0].compareValue).toBe(10);
  });
});

describe("rules that cannot run are reported, never silently dropped", () => {
  const data: FakeMetricData = {
    catalog: [catalogItem("acme.revenue", "additive", ["location_id"]), catalogItem("acme.off", "additive", ["location_id"], { enabled: false, disabledReason: "no source" })],
    points: { "acme.revenue": dailyPoints("2026-07-18", 14, { location_id: "L1" }, () => ({ value: 1 })) },
  };
  test.each([
    [{ condition: undefined }, "threshold_tbd"],
    [{ disabled_reason: "requires_composite_ranking" }, "requires_composite_ranking"],
    [{ metric: "acme.nope" }, "metric_unknown:acme.nope"],
    [{ metric: "acme.off" }, "metric_disabled:acme.off: no source"],
    [{ dims: ["region"] }, "dims_not_in_metric:region"],
  ])("%o => %s", async (over, reason) => {
    const out = await evaluateRules([rule(over)], ctx(data));
    expect(out.candidates).toHaveLength(0);
    expect(out.skipped).toEqual([{ ruleId: "ACME-T-001", reason }]);
  });

  test("a location override can supply the missing threshold for one location", async () => {
    const out = await evaluateRules([rule({ condition: undefined })], ctx(
      { ...data, points: { "acme.revenue": [...dailyPoints("2026-07-18", 14, { location_id: "L1" }, (i) => ({ value: i < 7 ? 1 : 2 })), ...dailyPoints("2026-07-18", 14, { location_id: "L2" }, (i) => ({ value: i < 7 ? 1 : 2 }))] } },
      [{ targetKey: "ACME-T-001", scope: { location_id: "L1" }, value: { condition: "value > compare_value" } }],
    ));
    expect(out.candidates.map((c) => c.dims.location_id)).toEqual(["L1"]);
  });

  test("a provider failure on one rule does not stop the others", async () => {
    const out = await evaluateRules([rule({ rule_id: "ACME-T-002", metric: "acme.nope2" }), rule({ condition: "value >= 0" })], ctx(data));
    expect(out.skipped[0].ruleId).toBe("ACME-T-002");
    expect(out.candidates.map((c) => c.rule.rule_id)).toEqual(["ACME-T-001"]);
  });
});
```

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/engine/rules.test.ts
```
Expected: FAIL — `Cannot find module './rules'`.

- [ ] **Step 3: Implement** — `LAAM/src/lib/intel/engine/rules.ts`

```ts
// Rule engine: evaluates pack rules over metric totals from the provider. Pure apart from
// provider calls; every number is computed here, never by an LLM (spec §0, D2).
import { evalBool, evalNumber, ExprError } from "../expr";
import { dimsKey, inferRatioScale, ratioScaleOf, type Aggregate, type Aggregation } from "../provider/aggregate";
import type { DataStatusItem, MetricCatalogItem, MetricsProvider } from "../provider/types";
import { OverrideError, resolveRule, type OverrideLevel, type OverrideRow } from "../overrides";
import { SEVERITY_ORDER, type CompareMode, type Rule, type Severity } from "../pack/schema";
import { monthToDate, shiftWindow, windowEnding, type DateWindow } from "../time";

export interface RuleContext {
  provider: MetricsProvider;
  asOf: string;
  catalog: ReadonlyMap<string, MetricCatalogItem>;
  disabledMetrics: ReadonlyMap<string, string>;
  overrides: readonly OverrideRow[];
}

export interface Comparison {
  mode: CompareMode;
  windows: DateWindow[];
  peerCount?: number;
  targetMonth?: DateWindow;
  prorated?: { elapsedDays: number; daysInMonth: number } | null;
}

export interface RuleCandidate {
  rule: Rule;
  ruleSource: "pack" | OverrideLevel;
  metricKey: string;
  aggregation: Aggregation;
  unit: string;
  scale: number;
  dims: Record<string, string>;
  window: DateWindow;
  value: number;
  compareValue: number | null;
  sigma: number | null;
  numerator: number | null;
  denominator: number | null;
  sampleSize: number;
  variance: number | null;
  variancePct: number | null;
  severity: Severity | null;
  severityReason: string | null;
  impact: number | null;
  impactUnit: string | null;
  vars: Record<string, number>;
  comparison: Comparison;
  dataStatus: DataStatusItem[];
}

export interface RuleSkip {
  ruleId: string;
  reason: string;
}
export interface RuleEvaluation {
  candidates: RuleCandidate[];
  skipped: RuleSkip[];
}

interface Group {
  dims: Record<string, string>;
  agg: Aggregate;
}
interface Totals {
  groups: Map<string, Group>;
  scale: number;
  inferredScale: number | null;
  dataStatus: DataStatusItem[];
}
interface CompareResult {
  value: number | null;
  sigma: number | null;
  peerCount?: number;
}

const BASELINE_WINDOWS = 4;

function pick(dims: Readonly<Record<string, string>>, keys: readonly string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const k of keys) if (dims[k] !== undefined) out[k] = dims[k];
  return out;
}

function mean(xs: readonly number[]): number {
  return xs.reduce((s, x) => s + x, 0) / xs.length;
}

function stdev(xs: readonly number[]): number | null {
  if (xs.length < 2) return null;
  const m = mean(xs);
  return Math.sqrt(xs.reduce((s, x) => s + (x - m) ** 2, 0) / xs.length);
}

/** Combine several aggregates: ratio-of-sums for ratios, mean of values otherwise. */
function combine(aggs: readonly Aggregate[], aggregation: Aggregation, scale: number): number | null {
  if (aggs.length === 0) return null;
  if (aggregation === "ratio") {
    let num = 0;
    let den = 0;
    for (const a of aggs) {
      num += a.numerator ?? 0;
      den += a.denominator ?? 0;
    }
    return den === 0 ? null : (scale * num) / den;
  }
  const vals = aggs.map((a) => a.value).filter((v): v is number => v != null);
  return vals.length ? mean(vals) : null;
}

async function fetchTotals(p: MetricsProvider, metricKey: string, w: DateWindow, groupBy: readonly string[], grain: "total" | "month" = "total"): Promise<Totals> {
  const res = await p.getMetrics({ metricKeys: [metricKey], from: w.from, to: w.to, grain, groupBy: [...groupBy] });
  const series = res.series.find((s) => s.metricKey === metricKey);
  if (!series) throw new Error(`provider returned no series for ${metricKey}`);
  const groups = new Map<string, Group>();
  for (const pt of series.points) {
    // The source stores a NULL dim as "" (unknown approver/employee): never a subject nor a peer.
    if (groupBy.some((d) => pt.dims[d] === "")) continue;
    groups.set(dimsKey(pt.dims, groupBy), {
      dims: pick(pt.dims, groupBy),
      agg: { value: pt.value, numerator: pt.numerator, denominator: pt.denominator, sampleSize: pt.sampleSize },
    });
  }
  return { groups, scale: ratioScaleOf(series.points), inferredScale: inferRatioScale(series.points), dataStatus: res.dataStatus };
}

function safeBool(expr: string, vars: Record<string, number>): boolean {
  try {
    return evalBool(expr, vars);
  } catch (e) {
    if (e instanceof ExprError) return false;
    throw e;
  }
}

function safeNumber(expr: string, vars: Record<string, number>): number | null {
  try {
    return evalNumber(expr, vars);
  } catch (e) {
    if (e instanceof ExprError) return null;
    throw e;
  }
}

function metricProblem(key: string, ctx: RuleContext): string | null {
  const item = ctx.catalog.get(key);
  if (!item) return `metric_unknown:${key}`;
  const disabled = ctx.disabledMetrics.get(key);
  if (!item.enabled || disabled) return `metric_disabled:${key}: ${item.disabledReason ?? disabled ?? "disabled"}`;
  return null;
}

/** Days per group on which `count_days` holds. Fetched per value of the first rule dim so
 * each response stays far below the MCP result cap. */
async function countDays(p: MetricsProvider, rule: Rule, window: DateWindow, groups: Map<string, Group>): Promise<Map<string, number>> {
  const counts = new Map<string, number>();
  const first = rule.dims[0];
  const chunks: (Record<string, string[]> | undefined)[] = first
    ? [...new Set([...groups.values()].map((g) => g.dims[first]).filter((v): v is string => v !== undefined))].map((v) => ({ [first]: [v] }))
    : [undefined];
  for (const dimsFilter of chunks) {
    const res = await p.getMetrics({ metricKeys: [rule.metric], from: window.from, to: window.to, grain: "day", groupBy: [...rule.dims], dimsFilter });
    for (const pt of res.series.find((s) => s.metricKey === rule.metric)?.points ?? []) {
      const vars: Record<string, number> = { sample_size: pt.sampleSize };
      if (pt.value != null) vars.value = pt.value;
      if (pt.numerator != null) vars.numerator = pt.numerator;
      if (pt.denominator != null) vars.denominator = pt.denominator;
      if (safeBool(rule.count_days as string, vars)) {
        const k = dimsKey(pt.dims, rule.dims);
        counts.set(k, (counts.get(k) ?? 0) + 1);
      }
    }
  }
  return counts;
}

export async function evaluateRule(rule: Rule, ctx: RuleContext): Promise<RuleEvaluation> {
  const skip = (reason: string): RuleEvaluation => ({ candidates: [], skipped: [{ ruleId: rule.rule_id, reason }] });

  // Customer-level view decides whether the rule runs at all, unless narrower overrides exist
  // (they may enable it for one location/category).
  const scoped = ctx.overrides.some((o) => o.targetKey === rule.rule_id && (o.scope.location_id || o.scope.category));
  if (!scoped) {
    let base: Rule;
    try {
      base = resolveRule(rule, ctx.overrides, {}).rule;
    } catch (e) {
      if (e instanceof OverrideError) return skip(`override_error: ${e.message}`);
      throw e;
    }
    if (base.disabled_reason) return skip(base.disabled_reason);
    if (!base.condition) return skip("threshold_tbd");
  }

  const problem = metricProblem(rule.metric, ctx) ?? (rule.target_metric ? metricProblem(rule.target_metric, ctx) : null);
  if (problem) return skip(problem);
  const item = ctx.catalog.get(rule.metric) as MetricCatalogItem;
  const missingDim = rule.dims.find((d) => !item.dims.includes(d));
  if (missingDim) return skip(`dims_not_in_metric:${missingDim}`);

  const mtd = monthToDate(ctx.asOf);
  const window = rule.compare === "target" ? mtd.window : windowEnding(ctx.asOf, rule.window_days);
  const current = await fetchTotals(ctx.provider, rule.metric, window, rule.dims);
  const scale = current.scale;
  // Pack expressions on percent ratios are written in percentage points ("compare_value - 2",
  // "/ 100"). If the source reports the rate on another scale they would be silently wrong.
  if (item.aggregation === "ratio" && item.unit === "percent" && current.inferredScale !== null && current.inferredScale !== 100) {
    return skip(`ratio_scale_mismatch:${rule.metric}: unit percent but value = ${current.inferredScale} x numerator/denominator`);
  }

  // ---- comparison data -------------------------------------------------------------------
  let comparison: Comparison = { mode: rule.compare, windows: [] };
  let compareFor: (key: string) => CompareResult = () => ({ value: null, sigma: null });

  if (rule.compare === "peer_average") {
    compareFor = (key) => {
      const peers = [...current.groups.entries()].filter(([k, g]) => k !== key && g.agg.value != null).map(([, g]) => g.agg);
      return {
        value: combine(peers, item.aggregation, scale),
        sigma: stdev(peers.map((a) => a.value as number)),
        peerCount: peers.length,
      };
    };
  } else if (rule.compare === "previous_period") {
    const prevW = shiftWindow(window, -rule.window_days);
    const prev = await fetchTotals(ctx.provider, rule.metric, prevW, rule.dims);
    comparison = { mode: rule.compare, windows: [prevW] };
    compareFor = (key) => ({ value: prev.groups.get(key)?.agg.value ?? null, sigma: null });
  } else if (rule.compare === "baseline_same_weekday_4w") {
    const step = 7 * Math.ceil(rule.window_days / 7);
    const wins = Array.from({ length: BASELINE_WINDOWS }, (_, i) => shiftWindow(window, -(i + 1) * step));
    const totals = await Promise.all(wins.map((w) => fetchTotals(ctx.provider, rule.metric, w, rule.dims)));
    comparison = { mode: rule.compare, windows: wins };
    compareFor = (key) => {
      const aggs = totals.map((t) => t.groups.get(key)?.agg).filter((a): a is Aggregate => !!a && a.value != null);
      if (aggs.length < BASELINE_WINDOWS) return { value: null, sigma: null };
      return { value: combine(aggs, item.aggregation, scale), sigma: stdev(aggs.map((a) => a.value as number)) };
    };
  } else if (rule.compare === "target") {
    const targetKey = rule.target_metric as string;
    const targets = await fetchTotals(ctx.provider, targetKey, mtd.month, rule.dims, "month");
    const prorate = item.aggregation === "additive";
    comparison = {
      mode: rule.compare,
      windows: [],
      targetMonth: mtd.month,
      prorated: prorate ? { elapsedDays: mtd.elapsedDays, daysInMonth: mtd.daysInMonth } : null,
    };
    compareFor = (key) => {
      const t = targets.groups.get(key)?.agg.value;
      if (t == null) return { value: null, sigma: null };
      return { value: prorate ? (t * mtd.elapsedDays) / mtd.daysInMonth : t, sigma: null };
    };
  }

  const daysHit = rule.count_days ? await countDays(ctx.provider, rule, window, current.groups) : null;

  // ---- per group -------------------------------------------------------------------------
  const candidates: RuleCandidate[] = [];
  const problems = new Map<string, number>();
  const note = (reason: string) => problems.set(reason, (problems.get(reason) ?? 0) + 1);

  for (const [key, g] of current.groups) {
    if (g.agg.value == null) continue;
    let resolved: { rule: Rule; source: "pack" | OverrideLevel };
    try {
      resolved = resolveRule(rule, ctx.overrides, g.dims);
    } catch (e) {
      if (e instanceof OverrideError) {
        note(`override_error: ${e.message}`);
        continue;
      }
      throw e;
    }
    const r = resolved.rule;
    if (r.disabled_reason || !r.condition) continue;
    if (r.min_sample !== undefined && g.agg.sampleSize < r.min_sample) continue;

    const cmp = compareFor(key);
    const vars: Record<string, number> = { value: g.agg.value, sample_size: g.agg.sampleSize };
    if (g.agg.numerator != null) vars.numerator = g.agg.numerator;
    if (g.agg.denominator != null) vars.denominator = g.agg.denominator;
    if (cmp.value != null) vars.compare_value = cmp.value;
    if (daysHit) vars.days_hit = daysHit.get(key) ?? 0;

    let hit: boolean;
    try {
      hit = evalBool(r.condition, vars);
    } catch (e) {
      if (!(e instanceof ExprError)) throw e;
      note(cmp.value == null && rule.compare !== "none" ? "compare_unavailable" : `expression_error: ${e.message}`);
      continue;
    }
    if (!hit) continue;

    let severity: Severity | null = null;
    let severityReason: string | null = null;
    for (const level of SEVERITY_ORDER) {
      const expr = r.severity?.[level];
      if (expr && safeBool(expr, vars)) {
        severity = level;
        severityReason = `${level}: ${expr}`;
        break;
      }
    }

    const variance = cmp.value != null ? g.agg.value - cmp.value : null;
    candidates.push({
      rule: r,
      ruleSource: resolved.source,
      metricKey: rule.metric,
      aggregation: item.aggregation,
      unit: item.unit,
      scale,
      dims: g.dims,
      window,
      value: g.agg.value,
      compareValue: cmp.value,
      sigma: cmp.sigma,
      numerator: g.agg.numerator,
      denominator: g.agg.denominator,
      sampleSize: g.agg.sampleSize,
      variance,
      variancePct: variance != null && cmp.value != null && cmp.value !== 0 ? (variance / Math.abs(cmp.value)) * 100 : null,
      severity,
      severityReason,
      impact: r.impact ? safeNumber(r.impact, vars) : null,
      impactUnit: r.impact_unit ?? null,
      vars,
      comparison: cmp.peerCount !== undefined ? { ...comparison, peerCount: cmp.peerCount } : comparison,
      dataStatus: current.dataStatus,
    });
  }

  const skipped = [...problems.entries()].map(([reason, n]) => ({ ruleId: rule.rule_id, reason: `${reason} for ${n} group(s)` }));
  return { candidates, skipped };
}

export async function evaluateRules(rules: readonly Rule[], ctx: RuleContext): Promise<RuleEvaluation> {
  const out: RuleEvaluation = { candidates: [], skipped: [] };
  // Sequential on purpose: each rule makes several MCP calls; parallel rules would hammer the
  // source for no gain in a daily batch.
  for (const rule of rules) {
    try {
      const r = await evaluateRule(rule, ctx);
      out.candidates.push(...r.candidates);
      out.skipped.push(...r.skipped);
    } catch (e) {
      out.skipped.push({ ruleId: rule.rule_id, reason: `provider_error: ${e instanceof Error ? e.message : String(e)}` });
    }
  }
  return out;
}
```

Ghi chú khớp test: test `{ metric: "acme.nope" }` cho reason `metric_unknown:acme.nope` qua `metricProblem` (không gọi provider). Test "provider failure on one rule" dùng `acme.nope2` ⇒ cũng là `metric_unknown` (skip trước khi gọi provider) — mục đích test là "một rule hỏng không chặn rule khác"; nhánh `provider_error` được phủ ở `pipeline.test.ts` (Task 17).

- [ ] **Step 4: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/engine/rules.test.ts
```
Expected: PASS (18 test). Nếu `baseline` test lệch cửa sổ, kiểm lại `shiftWindow(window, -(i+1)*step)` — đừng sửa test.

- [ ] **Step 5: Commit**

```bash
git -C LAAM add src/lib/intel/engine/rules.ts src/lib/intel/engine/rules.test.ts
git -C LAAM commit -m "feat(intel): rule engine with peer, baseline, target, previous-period and threshold comparisons"
```

---

### Task 10: Nguyên nhân (contributing factors) + confidence

**Files:**
- Create: `LAAM/src/lib/intel/engine/glob.ts`, `engine/causes.ts`, `engine/causes.test.ts`, `engine/confidence.ts`, `engine/confidence.test.ts`

**Interfaces:**
- Consumes: `RuleCandidate` (Task 9), `MetricsProvider`, `aggregate.ts` (Task 3), `shiftWindow/daysBetween` (Task 7), `Scoring` (Task 6).
- Produces:
```ts
// engine/glob.ts
export function globMatch(pattern: string, value: string): boolean;     // "*" only
export function matchesAny(patterns: readonly string[], value: string): boolean;
// engine/causes.ts
export interface CompanionChange { current: number | null; baseline: number | null; changePct: number | null }
export interface Factor { dim: string; key: string; current: number | null; baseline: number | null; contribution: number; valueEffect: number | null; mixEffect: number | null; share: number | null; companions: Record<string, CompanionChange> }
export interface CauseBaseline { kind: "rule_compare_windows" | "aligned_previous_period"; windows: DateWindow[]; ruleCompare: CompareMode }
export interface CauseBreakdown { dim: string; totalDelta: number; factors: Factor[]; topShare: number | null; baselineWindows: DateWindow[]; baseline?: CauseBaseline }   // baseline optional for older rows; always set by analyzeCauses
export interface Part { key: string; current: number | null; baseline: number | null; contribution: number; valueEffect: number | null; mixEffect: number | null }
export function decomposeAdditive(cur: ReadonlyMap<string, Aggregate>, base: ReadonlyMap<string, Aggregate>): { totalDelta: number; parts: Part[] };
export function decomposeRatio(cur: ReadonlyMap<string, Aggregate>, base: ReadonlyMap<string, Aggregate>, scale: number): { totalDelta: number; parts: Part[] };
export function topFactors(parts: readonly Part[], totalDelta: number, n: number): { top: Part[]; topShare: number | null };
export async function analyzeCauses(provider: MetricsProvider, cand: RuleCandidate, catalog: ReadonlyMap<string, MetricCatalogItem>, topN?: number): Promise<CauseBreakdown[]>;
// engine/confidence.ts
export interface ConfidenceInput { sampleSize: number; minSample: number | undefined; value: number; compareValue: number | null; sigma: number | null; freshness: DataStatusItem["status"] | null; weights: { sample: number; deviation: number; freshness: number }; params: Scoring["confidence"] }
export interface ConfidenceResult { score: number; parts: { sample: number; deviation: number; freshness: number }; reason: { sampleSize: number; minSample: number | null; sigmas: number | null; relativeDeviationPct: number | null; freshnessStatus: string | null } }
export function computeConfidence(i: ConfidenceInput): ConfidenceResult;
export function forecastIntervalFactor(point: number, lower: number, upper: number, minFactor: number): number;
```

Công thức (spec §7.3a):
- **Đóng góp additive**: Δᵢ = hiện tại − baseline của thành phần; tổng Δ = ΣΔᵢ.
- **Đóng góp ratio** (tách hiệu ứng giá trị và cơ cấu, đối xứng nên cộng lại **đúng bằng** chênh lệch tổng): với tỷ trọng wᵢ = denᵢ/Σden và tỉ lệ rᵢ = numᵢ/denᵢ ở hai kỳ, `value = scale·(w₁+w₀)/2·(r₁−r₀)`, `mix = scale·(w₁−w₀)·(r₁+r₀)/2`. Thành phần chỉ có ở một kỳ: dùng tỉ lệ của kỳ kia (hiệu ứng giá trị = 0).
- **Kỳ so sánh cho nguyên nhân** = các cửa sổ so sánh của rule nếu có (`previous_period`, `baseline_same_weekday_4w`) ⇒ `baseline.kind = "rule_compare_windows"`. Nếu không (`peer_average`, `target`, `none`) ⇒ kỳ **trước đó lùi một bội số 7 ngày** (`7·ceil(L/7)`, cùng độ dài L, cùng thứ trong tuần — cửa sổ MTD 10 ngày lùi 14 ngày, không lùi 10) ⇒ `baseline.kind = "aligned_previous_period"` kèm `ruleCompare` để UI ghi rõ "nguyên nhân giải thích thay đổi so với kỳ trước, không phải chênh lệch so với target/peer". Dùng nhóm peer làm baseline: chưa làm — không rule peer nào trong pack beta khai báo `breakdown` (Open questions).
- **Top N** (mặc định 5) theo |đóng góp|; `topShare` = Σ đóng góp top / tổng Δ ("5 thành phần chiếm 78% mức giảm").
- **Confidence** = trung bình có trọng số (trọng số của rule) của: `sample = min(1, n / (3·min_sample))` (không có min_sample ⇒ 1 nếu n>0); `deviation = sigmoid(z − z₀)` với z = |v−c|/σ nếu có σ, ngược lại |v−c|/|c|·`relative_z_scale`; rule `compare: none` ⇒ deviation = 1 (vi phạm ngưỡng tuyệt đối, không phải phát hiện thống kê); `freshness` = 1 (current) / 0.7 (delayed) / 0 (khác) — lấy từ `scoring.confidence`.

- [ ] **Step 1: Viết test thất bại cho nguyên nhân** — `LAAM/src/lib/intel/engine/causes.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { analyzeCauses, decomposeAdditive, decomposeRatio, topFactors } from "./causes";
import { globMatch } from "./glob";
import type { Aggregate } from "../provider/aggregate";
import { FakeMetricsProvider } from "../provider/fake";
import { catalogItem, dailyPoints } from "../testing/fixtures";
import type { RuleCandidate } from "./rules";
import { ruleSchema } from "../pack/schema";

const ratio = (num: number, den: number): Aggregate => ({ value: (100 * num) / den, numerator: num, denominator: den, sampleSize: den });
const add = (v: number): Aggregate => ({ value: v, numerator: null, denominator: null, sampleSize: 1 });

describe("decomposeRatio", () => {
  // Why: "margin fell 11pp" can come from rates changing or from the mix shifting toward a
  // low-rate component. The split must add up exactly to the total change.
  test("value + mix effects sum exactly to the total change", () => {
    const base = new Map([["A", ratio(50, 100)], ["B", ratio(10, 100)]]); // 30%
    const cur = new Map([["A", ratio(45, 100)], ["B", ratio(30, 300)]]); // 18.75%
    const { totalDelta, parts } = decomposeRatio(cur, base, 100);
    expect(totalDelta).toBeCloseTo(-11.25, 10);
    expect(parts.reduce((s, p) => s + p.contribution, 0)).toBeCloseTo(totalDelta, 10);
    const b = parts.find((p) => p.key === "B")!;
    expect(b.valueEffect).toBeCloseTo(0, 10); // B's rate did not change — pure mix
    expect(b.mixEffect).toBeCloseTo(2.5, 10);
    const a = parts.find((p) => p.key === "A")!;
    expect(a.valueEffect).toBeCloseTo(-1.875, 10);
    expect(a.mixEffect).toBeCloseTo(-11.875, 10);
  });

  test("a component present in only one period has no value effect", () => {
    const { totalDelta, parts } = decomposeRatio(new Map([["A", ratio(10, 100)], ["N", ratio(0, 100)]]), new Map([["A", ratio(10, 100)]]), 100);
    expect(parts.find((p) => p.key === "N")!.valueEffect).toBe(0);
    expect(parts.reduce((s, p) => s + p.contribution, 0)).toBeCloseTo(totalDelta, 10);
  });
});

describe("decomposeAdditive + topFactors", () => {
  test("ranks by absolute contribution and reports the cumulative share", () => {
    const { totalDelta, parts } = decomposeAdditive(
      new Map([["A", add(20)], ["B", add(90)], ["C", add(55)]]),
      new Map([["A", add(100)], ["B", add(100)], ["C", add(50)]]),
    );
    expect(totalDelta).toBe(-85);
    const { top, topShare } = topFactors(parts, totalDelta, 1);
    expect(top.map((p) => p.key)).toEqual(["A"]);
    expect(topShare).toBeCloseTo(80 / 85, 10);
  });
  test("no change means no share", () => {
    expect(topFactors([], 0, 5).topShare).toBeNull();
  });
});

describe("analyzeCauses", () => {
  const catalog = [
    catalogItem("acme.revenue", "additive", ["location_id", "category"]),
    catalogItem("acme.cost", "additive", ["location_id", "category"]),
  ];
  const provider = new FakeMetricsProvider({
    catalog,
    points: {
      "acme.revenue": [
        ...dailyPoints("2026-07-18", 7, { location_id: "L1", category: "x" }, () => ({ value: 100 })),
        ...dailyPoints("2026-07-25", 7, { location_id: "L1", category: "x" }, () => ({ value: 40 })),
        ...dailyPoints("2026-07-18", 14, { location_id: "L1", category: "y" }, () => ({ value: 50 })),
        ...dailyPoints("2026-07-18", 14, { location_id: "L2", category: "x" }, () => ({ value: 999 })),
      ],
      "acme.cost": [
        ...dailyPoints("2026-07-18", 7, { location_id: "L1", category: "x" }, () => ({ value: 10 })),
        ...dailyPoints("2026-07-25", 7, { location_id: "L1", category: "x" }, () => ({ value: 12 })),
      ],
    },
  });
  const rule = ruleSchema.parse({
    rule_id: "ACME-T-001", version: 1, name: "t", metric: "acme.revenue", dims: ["location_id"], window_days: 7,
    compare: "previous_period", condition: "value < compare_value", breakdown: ["category"], companions: ["acme.cost"],
    recommended_action: "investigate", default_owner_role: "m", cooldown_days: 7, wording: "w",
  });
  const cand = {
    rule, metricKey: "acme.revenue", aggregation: "additive", scale: 1, dims: { location_id: "L1" },
    window: { from: "2026-07-25", to: "2026-08-01" },
    comparison: { mode: "previous_period", windows: [{ from: "2026-07-18", to: "2026-07-25" }] },
  } as unknown as RuleCandidate;

  test("finds the component behind the change, scoped to the finding's dims, with companion signals", async () => {
    const [b] = await analyzeCauses(provider, cand, new Map(catalog.map((c) => [c.key, c])));
    expect(b.dim).toBe("category");
    expect(b.totalDelta).toBe(-420); // only L1: x fell 700 -> 280, y flat; L2 excluded
    expect(b.factors[0]).toMatchObject({ key: "x", current: 280, baseline: 700, contribution: -420 });
    expect(b.factors[0].companions["acme.cost"]).toEqual({ current: 84, baseline: 70, changePct: 20 });
    expect(b.topShare).toBeCloseTo(1, 10);
    expect(b.baseline).toEqual({ kind: "rule_compare_windows", windows: [{ from: "2026-07-18", to: "2026-07-25" }], ruleCompare: "previous_period" });
  });

  // Why (review): a target rule has no time window; the fallback must keep weekdays aligned and
  // say that it explains the change vs an earlier period, not the gap to target.
  test("target rules explain vs a week-aligned previous period and label it", async () => {
    const mtd = { ...cand, window: { from: "2026-07-01", to: "2026-07-11" }, comparison: { mode: "target", windows: [] } } as unknown as RuleCandidate;
    const [b] = await analyzeCauses(provider, mtd, new Map(catalog.map((c) => [c.key, c])));
    expect(b.baseline).toEqual({ kind: "aligned_previous_period", windows: [{ from: "2026-06-17", to: "2026-06-27" }], ruleCompare: "target" });
  });
});

describe("globMatch", () => {
  test("star matches any run; other characters are literal", () => {
    expect(globMatch("ACME-*", "ACME-REV-001")).toBe(true);
    expect(globMatch("ACME-*", "XACME-REV")).toBe(false);
    expect(globMatch("A.B", "AxB")).toBe(false);
  });
});
```

- [ ] **Step 2: Viết test thất bại cho confidence** — `LAAM/src/lib/intel/engine/confidence.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { computeConfidence, forecastIntervalFactor, type ConfidenceInput } from "./confidence";

const params = { deviation_z_midpoint: 2, relative_z_scale: 10, freshness_current: 1, freshness_delayed: 0.7, min_interval_factor: 0.2 };
const base: ConfidenceInput = {
  sampleSize: 30, minSample: 10, value: 30, compareValue: 10, sigma: 5, freshness: "current",
  weights: { sample: 0.4, deviation: 0.4, freshness: 0.2 }, params,
};

describe("computeConfidence", () => {
  test("sample part saturates at three times the minimum sample", () => {
    expect(computeConfidence({ ...base, sampleSize: 15 }).parts.sample).toBeCloseTo(0.5, 10);
    expect(computeConfidence({ ...base, sampleSize: 300 }).parts.sample).toBe(1);
  });
  // Why: confidence must fall when evidence is thin or stale (spec §13).
  test("smaller samples lower confidence", () => {
    expect(computeConfidence({ ...base, sampleSize: 10 }).score).toBeLessThan(computeConfidence(base).score);
  });
  test("larger deviations raise confidence; z is reported in sigmas", () => {
    const small = computeConfidence({ ...base, value: 12 });
    const big = computeConfidence(base);
    expect(big.score).toBeGreaterThan(small.score);
    expect(big.reason.sigmas).toBeCloseTo(4, 10);
    expect(big.parts.deviation).toBeCloseTo(1 / (1 + Math.exp(-(4 - 2))), 4); // parts are rounded to 4 dp
  });
  test("without sigma the relative deviation is scaled into z", () => {
    const r = computeConfidence({ ...base, sigma: null, value: 11, compareValue: 10 });
    expect(r.parts.deviation).toBeCloseTo(1 / (1 + Math.exp(-(1 - 2))), 4); // 10% * 10 = 1
    expect(r.reason.relativeDeviationPct).toBeCloseTo(10, 10);
  });
  test("delayed data lowers confidence; stale data zeroes freshness", () => {
    expect(computeConfidence({ ...base, freshness: "delayed" }).parts.freshness).toBe(0.7);
    const stale = computeConfidence({ ...base, freshness: "stale" });
    expect(stale.parts.freshness).toBe(0);
    expect(stale.score).toBeLessThan(computeConfidence(base).score);
  });
  test("absolute-threshold rules (no comparison) get full deviation credit", () => {
    expect(computeConfidence({ ...base, compareValue: null, sigma: null }).parts.deviation).toBe(1);
  });
  test("score stays within [0, 1]", () => {
    const r = computeConfidence({ ...base, sampleSize: 0, freshness: null, value: 10 });
    expect(r.score).toBeGreaterThanOrEqual(0);
    expect(r.score).toBeLessThanOrEqual(1);
  });
});

describe("forecastIntervalFactor", () => {
  test("narrower intervals are more trustworthy, with a floor", () => {
    expect(forecastIntervalFactor(100, 95, 105, 0.2)).toBeCloseTo(0.95, 10);
    expect(forecastIntervalFactor(100, 0, 400, 0.2)).toBe(0.2);
    expect(forecastIntervalFactor(0, -1, 1, 0.2)).toBe(0.2);
  });
});
```

- [ ] **Step 3: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/engine/causes.test.ts src/lib/intel/engine/confidence.test.ts
```
Expected: FAIL — module `./causes`, `./glob`, `./confidence` không tồn tại.

- [ ] **Step 4: Implement glob** — `LAAM/src/lib/intel/engine/glob.ts`

```ts
// Minimal glob for rule-id patterns in pack config ("PREFIX-*"). Only "*" is special.
export function globMatch(pattern: string, value: string): boolean {
  const escaped = pattern.split("*").map((part) => part.replace(/[.+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp("^" + escaped.join(".*") + "$").test(value);
}

export function matchesAny(patterns: readonly string[], value: string): boolean {
  return patterns.some((p) => globMatch(p, value));
}
```

- [ ] **Step 5: Implement causes** — `LAAM/src/lib/intel/engine/causes.ts`

```ts
// "Why did it change?" — deterministic decomposition of a finding's change into components of a
// breakdown dimension (spec §7.3a). The LLM only narrates these numbers later.
import { ratioScaleOf, type Aggregate, type Aggregation } from "../provider/aggregate";
import type { MetricCatalogItem, MetricsProvider } from "../provider/types";
import { daysBetween, shiftWindow, type DateWindow } from "../time";
import type { CompareMode } from "../pack/schema";
import type { RuleCandidate } from "./rules";

export interface CompanionChange {
  current: number | null;
  baseline: number | null;
  changePct: number | null;
}
export interface Part {
  key: string;
  current: number | null;
  baseline: number | null;
  contribution: number;
  valueEffect: number | null;
  mixEffect: number | null;
}
export interface Factor extends Part {
  dim: string;
  share: number | null;
  companions: Record<string, CompanionChange>;
}
export interface CauseBaseline {
  kind: "rule_compare_windows" | "aligned_previous_period";
  windows: DateWindow[];
  /** The rule's own comparison — when not time-based, factors explain a different delta than the finding. */
  ruleCompare: CompareMode;
}
export interface CauseBreakdown {
  dim: string;
  totalDelta: number;
  factors: Factor[];
  topShare: number | null;
  baselineWindows: DateWindow[];
  baseline?: CauseBaseline;
}

const DEFAULT_TOP_N = 5;

export function decomposeAdditive(cur: ReadonlyMap<string, Aggregate>, base: ReadonlyMap<string, Aggregate>): { totalDelta: number; parts: Part[] } {
  const keys = new Set([...cur.keys(), ...base.keys()]);
  const parts: Part[] = [];
  let totalDelta = 0;
  for (const key of keys) {
    const c = cur.get(key)?.value ?? null;
    const b = base.get(key)?.value ?? null;
    const contribution = (c ?? 0) - (b ?? 0);
    totalDelta += contribution;
    parts.push({ key, current: c, baseline: b, contribution, valueEffect: null, mixEffect: null });
  }
  return { totalDelta, parts };
}

export function decomposeRatio(cur: ReadonlyMap<string, Aggregate>, base: ReadonlyMap<string, Aggregate>, scale: number): { totalDelta: number; parts: Part[] } {
  const sumDen = (m: ReadonlyMap<string, Aggregate>) => [...m.values()].reduce((s, a) => s + (a.denominator ?? 0), 0);
  const sumNum = (m: ReadonlyMap<string, Aggregate>) => [...m.values()].reduce((s, a) => s + (a.numerator ?? 0), 0);
  const d1 = sumDen(cur);
  const d0 = sumDen(base);
  const r1Total = d1 > 0 ? sumNum(cur) / d1 : 0;
  const r0Total = d0 > 0 ? sumNum(base) / d0 : 0;
  const totalDelta = scale * (r1Total - r0Total);
  const rateOf = (a: Aggregate | undefined) => (a && (a.denominator ?? 0) > 0 ? (a.numerator ?? 0) / (a.denominator as number) : null);

  const parts: Part[] = [];
  for (const key of new Set([...cur.keys(), ...base.keys()])) {
    const a1 = cur.get(key);
    const a0 = base.get(key);
    const w1 = d1 > 0 ? (a1?.denominator ?? 0) / d1 : 0;
    const w0 = d0 > 0 ? (a0?.denominator ?? 0) / d0 : 0;
    let r1 = rateOf(a1);
    let r0 = rateOf(a0);
    // A component missing in one period takes the other period's rate: no value effect.
    if (r1 === null) r1 = r0 ?? 0;
    if (r0 === null) r0 = r1;
    const valueEffect = scale * ((w1 + w0) / 2) * (r1 - r0);
    const mixEffect = scale * (w1 - w0) * ((r1 + r0) / 2);
    parts.push({
      key,
      current: rateOf(a1) !== null ? scale * (rateOf(a1) as number) : null,
      baseline: rateOf(a0) !== null ? scale * (rateOf(a0) as number) : null,
      contribution: valueEffect + mixEffect,
      valueEffect,
      mixEffect,
    });
  }
  return { totalDelta, parts };
}

export function topFactors(parts: readonly Part[], totalDelta: number, n: number): { top: Part[]; topShare: number | null } {
  const top = [...parts].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution)).slice(0, n);
  if (totalDelta === 0) return { top, topShare: null };
  return { top, topShare: top.reduce((s, p) => s + p.contribution, 0) / totalDelta };
}

function mergeWindows(maps: readonly Map<string, Aggregate>[], aggregation: Aggregation, scale: number): Map<string, Aggregate> {
  const out = new Map<string, Aggregate>();
  const keys = new Set(maps.flatMap((m) => [...m.keys()]));
  for (const key of keys) {
    const aggs = maps.map((m) => m.get(key));
    const sampleSize = aggs.reduce((s, a) => s + (a?.sampleSize ?? 0), 0);
    if (aggregation === "ratio") {
      const num = aggs.reduce((s, a) => s + (a?.numerator ?? 0), 0);
      const den = aggs.reduce((s, a) => s + (a?.denominator ?? 0), 0);
      out.set(key, { value: den > 0 ? (scale * num) / den : null, numerator: num, denominator: den, sampleSize });
    } else {
      // Mean over windows; a window without the component counts as zero.
      const value = aggs.reduce((s, a) => s + (a?.value ?? 0), 0) / maps.length;
      out.set(key, { value, numerator: null, denominator: null, sampleSize });
    }
  }
  return out;
}

async function componentTotals(
  provider: MetricsProvider,
  metricKey: string,
  windows: readonly DateWindow[],
  groupBy: readonly string[],
  dim: string,
  dimsFilter: Record<string, string[]>,
  aggregation: Aggregation,
): Promise<{ map: Map<string, Aggregate>; scale: number }> {
  const maps: Map<string, Aggregate>[] = [];
  let scale = 1;
  for (const w of windows) {
    const res = await provider.getMetrics({ metricKeys: [metricKey], from: w.from, to: w.to, grain: "total", groupBy: [...groupBy], dimsFilter });
    const series = res.series.find((s) => s.metricKey === metricKey);
    const m = new Map<string, Aggregate>();
    for (const pt of series?.points ?? []) {
      const key = pt.dims[dim];
      if (key === undefined) continue;
      m.set(key, { value: pt.value, numerator: pt.numerator, denominator: pt.denominator, sampleSize: pt.sampleSize });
    }
    if (series) scale = Math.max(scale, ratioScaleOf(series.points));
    maps.push(m);
  }
  return { map: maps.length === 1 ? maps[0] : mergeWindows(maps, aggregation, scale), scale };
}

export async function analyzeCauses(
  provider: MetricsProvider,
  cand: RuleCandidate,
  catalog: ReadonlyMap<string, MetricCatalogItem>,
  topN: number = DEFAULT_TOP_N,
): Promise<CauseBreakdown[]> {
  const item = catalog.get(cand.metricKey);
  if (!item) return [];
  // Without time-based compare windows (target / peer / none), explain the change vs the previous
  // window shifted by a whole number of weeks so weekdays line up (an MTD window of 10 days is
  // compared with the same 10 days two weeks earlier, not 10 days earlier).
  const len = daysBetween(cand.window.from, cand.window.to);
  const fromRule = cand.comparison.windows.length > 0;
  const baseWindows = fromRule ? cand.comparison.windows : [shiftWindow(cand.window, -7 * Math.ceil(len / 7))];
  const baseline: CauseBaseline = {
    kind: fromRule ? "rule_compare_windows" : "aligned_previous_period",
    windows: [...baseWindows],
    ruleCompare: cand.comparison.mode,
  };
  const dimsFilter = Object.fromEntries(Object.entries(cand.dims).map(([k, v]) => [k, [v]]));
  const out: CauseBreakdown[] = [];

  for (const dim of cand.rule.breakdown) {
    if (!item.dims.includes(dim) || cand.rule.dims.includes(dim)) continue;
    const groupBy = [...cand.rule.dims, dim];
    const cur = await componentTotals(provider, cand.metricKey, [cand.window], groupBy, dim, dimsFilter, item.aggregation);
    const base = await componentTotals(provider, cand.metricKey, baseWindows, groupBy, dim, dimsFilter, item.aggregation);
    const scale = Math.max(cur.scale, base.scale);
    const { totalDelta, parts } = item.aggregation === "ratio"
      ? decomposeRatio(cur.map, base.map, scale)
      : decomposeAdditive(cur.map, base.map);
    const { top, topShare } = topFactors(parts, totalDelta, topN);

    const companions: Record<string, { cur: Map<string, Aggregate>; base: Map<string, Aggregate> }> = {};
    for (const key of cand.rule.companions) {
      const c = catalog.get(key);
      // dims_filter naming a dim the metric lacks is a 400 at DAAB (master §2.4): the companion must
      // carry every rule dim used in the filter, plus the breakdown dim.
      if (!c || !c.enabled || !c.dims.includes(dim) || !cand.rule.dims.every((d) => c.dims.includes(d))) continue;
      companions[key] = {
        cur: (await componentTotals(provider, key, [cand.window], groupBy, dim, dimsFilter, c.aggregation)).map,
        base: (await componentTotals(provider, key, baseWindows, groupBy, dim, dimsFilter, c.aggregation)).map,
      };
    }

    out.push({
      dim,
      totalDelta,
      topShare,
      baselineWindows: [...baseWindows],
      baseline,
      factors: top.map((p) => ({
        ...p,
        dim,
        share: totalDelta !== 0 ? p.contribution / totalDelta : null,
        companions: Object.fromEntries(
          Object.entries(companions).map(([key, m]) => {
            const c = m.cur.get(p.key)?.value ?? null;
            const b = m.base.get(p.key)?.value ?? null;
            return [key, { current: c, baseline: b, changePct: c != null && b != null && b !== 0 ? ((c - b) / Math.abs(b)) * 100 : null }];
          }),
        ),
      })),
    });
  }
  return out;
}
```

- [ ] **Step 6: Implement confidence** — `LAAM/src/lib/intel/engine/confidence.ts`

```ts
// Deterministic confidence (0-1) for a finding (spec §7.3a). Weights come from the rule, the
// curve parameters from the pack's scoring.yaml — no constants are decided here.
import type { Scoring } from "../pack/schema";
import type { DataStatusItem } from "../provider/types";

export interface ConfidenceInput {
  sampleSize: number;
  minSample: number | undefined;
  value: number;
  compareValue: number | null;
  sigma: number | null;
  freshness: DataStatusItem["status"] | null;
  weights: { sample: number; deviation: number; freshness: number };
  params: Scoring["confidence"];
}

export interface ConfidenceResult {
  score: number;
  parts: { sample: number; deviation: number; freshness: number };
  reason: {
    sampleSize: number;
    minSample: number | null;
    sigmas: number | null;
    relativeDeviationPct: number | null;
    freshnessStatus: string | null;
  };
}

const round4 = (x: number): number => Math.round(x * 10_000) / 10_000;

export function computeConfidence(i: ConfidenceInput): ConfidenceResult {
  const sample = i.minSample && i.minSample > 0 ? Math.min(1, i.sampleSize / (3 * i.minSample)) : i.sampleSize > 0 ? 1 : 0;

  let deviation = 1;
  let sigmas: number | null = null;
  let relativeDeviationPct: number | null = null;
  if (i.compareValue !== null) {
    const diff = i.value - i.compareValue;
    relativeDeviationPct = i.compareValue !== 0 ? (diff / Math.abs(i.compareValue)) * 100 : null;
    let z: number;
    if (i.sigma !== null && i.sigma > 0) {
      sigmas = diff / i.sigma;
      z = Math.abs(sigmas);
    } else if (i.compareValue !== 0) {
      z = (Math.abs(diff) / Math.abs(i.compareValue)) * i.params.relative_z_scale;
    } else {
      z = diff === 0 ? 0 : Number.POSITIVE_INFINITY;
    }
    deviation = 1 / (1 + Math.exp(-(z - i.params.deviation_z_midpoint)));
  }

  const freshness =
    i.freshness === "current" ? i.params.freshness_current : i.freshness === "delayed" ? i.params.freshness_delayed : 0;

  const w = i.weights;
  const totalW = w.sample + w.deviation + w.freshness;
  const score = totalW > 0 ? (w.sample * sample + w.deviation * deviation + w.freshness * freshness) / totalW : 0;

  return {
    score: round4(Math.min(1, Math.max(0, score))),
    parts: { sample: round4(sample), deviation: round4(deviation), freshness },
    reason: { sampleSize: i.sampleSize, minSample: i.minSample ?? null, sigmas, relativeDeviationPct, freshnessStatus: i.freshness },
  };
}

/** Narrower backtest intervals => more trust in a forecast-based figure (spec §7.3a). */
export function forecastIntervalFactor(point: number, lower: number, upper: number, minFactor: number): number {
  if (point === 0) return minFactor;
  const f = 1 - (upper - lower) / (2 * Math.abs(point));
  return Math.min(1, Math.max(minFactor, f));
}
```

- [ ] **Step 7: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/engine/causes.test.ts src/lib/intel/engine/confidence.test.ts
```
Expected: PASS (causes 7, confidence 8).

- [ ] **Step 8: Commit**

```bash
git -C LAAM add src/lib/intel/engine/glob.ts src/lib/intel/engine/causes.ts src/lib/intel/engine/causes.test.ts src/lib/intel/engine/confidence.ts src/lib/intel/engine/confidence.test.ts
git -C LAAM commit -m "feat(intel): contributing-factor decomposition and deterministic confidence"
```

---

### Task 11: Severity theo impact, priority score, dedup/cooldown/resurfacing

**Files:**
- Create: `LAAM/src/lib/intel/engine/scoring.ts`, `engine/scoring.test.ts`, `engine/dedupe.ts`, `engine/dedupe.test.ts`

**Interfaces:**
- Consumes: `Scoring`, `Severity`, `SEVERITY_RANK`, `CompareMode` (Task 6); `matchesAny` (Task 10); `FindingStatus` (Task 1).
- Produces:
```ts
// engine/scoring.ts
export function impactThreshold(tier: Scoring["severity_by_impact"]["tiers"][number], weeklySales: number | null): number;
export function severityByImpact(impact: number | null, impactUnit: string | null, weeklySales: number | null, cfg: Scoring["severity_by_impact"]): { level: Severity; reason: string };
export interface PriorityInput { impact: number | null; impactUnit: string | null; weeklySales: number | null; severity: Severity; confidence: number; compareMode: CompareMode; variancePct: number | null; locationCount: number; totalLocations: number; occurrences: number; ruleId: string }
export type PriorityComponents = Record<keyof Scoring["priority_weights"], number>;
export function priorityScore(i: PriorityInput, scoring: Scoring, weights: Scoring["priority_weights"]): { score: number; components: PriorityComponents };
// engine/dedupe.ts
export function dimsHash(dims: Readonly<Record<string, string>>): string;
export function dedupeKey(ruleId: string, dims: Readonly<Record<string, string>>): string;
export interface ExistingFinding { id: string; status: FindingStatus; severity: Severity; estimatedImpact: number | null; sampleSize: number; occurrences: number; statusChangedAt: Date; lastSurfacedAt: Date | null; windowDays: number | null }
export type SurfaceReason = "new" | "recurred" | "severity_increased" | "impact_changed" | "new_evidence" | "task_overdue" | "monitoring";
export interface FindingDecision { action: "insert" | "update"; surface: boolean; reason: SurfaceReason | null; reopen: boolean; occurrences: number }
export function decideFinding(existing: ExistingFinding | null, cand: { severity: Severity; impact: number | null; sampleSize: number; windowDays: number | null }, ctx: { now: Date; cooldownDays: number; taskOverdue: boolean; resurfacing: Scoring["resurfacing"] }): FindingDecision;
```

Định nghĩa:
- **Severity theo impact** (request Part 3 §19): duyệt `tiers` (critical, high, medium) — vượt `max(min_amount, min_pct_weekly_sales% × doanh thu tuần)` ⇒ mức đó; không có impact tiền ⇒ `otherwise` (`low` = "informational / early trend").
- **Priority** = `100 × Σ wᵢ·cᵢ / Σ wᵢ`, trọng số request §18 (financial 30 · urgency 20 · confidence 15 · target variance 10 · locations 10 · repeated 10 · strategic 5) từ `scoring.yaml`, override bằng `rule_override` `priority_weights`. Thành phần: financial = |impact| / ngưỡng tier cao nhất (chặn 1); urgency = `scoring.urgency[severity]`; confidence; target variance = |variance%| / `normalization.target_variance_pct` (chỉ rule `compare: target`); locations = số location của finding / tổng location; repeated = (occurrences − 1) / `normalization.repeated_occurrences`; strategic = rule khớp `strategic_rules`.
- **Dedup** = `rule_id + ":" + sha256(dims đã sắp key)`.
- **Resurfacing** (spec §7.5, request §18 "Alert cooldown"): finding đang mở chỉ lên lại brief khi severity tăng, |impact đổi| > `impact_change_pct`%, sample tăng ≥ `sample_growth_pct`% (evidence mới), task quá hạn, hoặc trạng thái `monitoring` và đã qua `cooldown_days` từ lần lên brief trước. Finding `resolved`: tái xuất trong `cooldown_days` ⇒ cập nhật im lặng; sau đó ⇒ mở lại (`recurred`). Finding `dismissed`: giữ dismissed trừ khi severity tăng.

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/lib/intel/engine/scoring.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { priorityScore, severityByImpact, type PriorityInput } from "./scoring";
import type { Scoring } from "../pack/schema";

const scoring = {
  priority_weights: { financial: 30, urgency: 20, confidence: 15, target_variance: 10, locations: 10, repeated: 10, strategic: 5 },
  urgency: { critical: 1, high: 0.75, medium: 0.5, warning: 0.5, low: 0.25 },
  severity_by_impact: {
    sales_metric: "acme.revenue",
    tiers: [
      { level: "critical", min_amount: 10000, min_pct_weekly_sales: 1 },
      { level: "high", min_amount: 5000, min_pct_weekly_sales: 0.5 },
      { level: "medium", min_amount: 1000, min_pct_weekly_sales: 0.1 },
    ],
    otherwise: "low",
  },
  normalization: { target_variance_pct: 20, repeated_occurrences: 4 },
  strategic_rules: ["ACME-STRAT-*"],
} as unknown as Scoring;

describe("severityByImpact (request §19)", () => {
  test.each([
    [12000, 100000, "critical"], // > max(10000, 1000)
    [12000, 2_000_000, "high"], // critical needs > 20000 at this size; high needs > 10000
    [6000, 100000, "high"],
    [1500, 100000, "medium"],
    [900, 100000, "low"],
    [-6000, 100000, "high"], // magnitude counts
  ])("impact %d with weekly sales %d => %s", (impact, weekly, level) => {
    expect(severityByImpact(impact, "currency", weekly, scoring.severity_by_impact).level).toBe(level);
  });
  test("no currency impact falls to the 'otherwise' level and says why", () => {
    const r = severityByImpact(null, null, 100000, scoring.severity_by_impact);
    expect(r.level).toBe("low");
    expect(r.reason).toMatch(/no currency impact/);
    expect(severityByImpact(50, "count", 100000, scoring.severity_by_impact).level).toBe("low");
  });
  test("thresholds fall back to the fixed amount when weekly sales are unknown", () => {
    expect(severityByImpact(10001, "currency", null, scoring.severity_by_impact).level).toBe("critical");
  });
});

describe("priorityScore (request §18 weights)", () => {
  const base: PriorityInput = {
    impact: 0, impactUnit: "currency", weeklySales: 100000, severity: "low", confidence: 0, compareMode: "none",
    variancePct: null, locationCount: 0, totalLocations: 5, occurrences: 1, ruleId: "ACME-X-001",
  };
  test("a maximal finding scores 100", () => {
    const r = priorityScore({ ...base, impact: 50000, severity: "critical", confidence: 1, compareMode: "target", variancePct: -40, locationCount: 5, occurrences: 9, ruleId: "ACME-STRAT-1" }, scoring, scoring.priority_weights);
    expect(r.score).toBe(100);
  });
  test("each component is weighted as configured", () => {
    expect(priorityScore({ ...base, impact: 10000 }, scoring, scoring.priority_weights).components.financial).toBe(1);
    expect(priorityScore({ ...base, impact: 10000, severity: "low" }, scoring, scoring.priority_weights).score).toBeCloseTo(30 + 20 * 0.25, 10);
    expect(priorityScore({ ...base, confidence: 0.8 }, scoring, scoring.priority_weights).score).toBeCloseTo(20 * 0.25 + 15 * 0.8, 10);
  });
  test("target variance only counts for target comparisons", () => {
    expect(priorityScore({ ...base, compareMode: "previous_period", variancePct: -40 }, scoring, scoring.priority_weights).components.target_variance).toBe(0);
    expect(priorityScore({ ...base, compareMode: "target", variancePct: -10 }, scoring, scoring.priority_weights).components.target_variance).toBe(0.5);
  });
  test("repeats and locations scale up to their caps", () => {
    const r = priorityScore({ ...base, occurrences: 3, locationCount: 2 }, scoring, scoring.priority_weights);
    expect(r.components.repeated).toBe(0.5);
    expect(r.components.locations).toBe(0.4);
  });
  test("overridden weights change the score", () => {
    const r = priorityScore({ ...base, impact: 10000 }, scoring, { ...scoring.priority_weights, financial: 0 });
    expect(r.components.financial).toBe(1);
    expect(r.score).toBeCloseTo(7.14, 2); // 100 * 5 / 70, score rounded to 2 dp
  });
});
```

- [ ] **Step 2: Viết test thất bại** — `LAAM/src/lib/intel/engine/dedupe.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { decideFinding, dedupeKey, type ExistingFinding } from "./dedupe";

const now = new Date("2026-08-01T12:00:00Z");
const daysAgo = (n: number) => new Date(now.getTime() - n * 86_400_000);
const resurfacing = { impact_change_pct: 20, sample_growth_pct: 25 };
const existing = (over: Partial<ExistingFinding> = {}): ExistingFinding => ({
  id: "f1", status: "acknowledged", severity: "high", estimatedImpact: 1000, sampleSize: 100, occurrences: 3,
  statusChangedAt: daysAgo(20), lastSurfacedAt: daysAgo(10), windowDays: 30, ...over,
});
const cand = { severity: "high" as const, impact: 1000, sampleSize: 100, windowDays: 30 };
const ctx = { now, cooldownDays: 7, taskOverdue: false, resurfacing };

describe("dedupeKey", () => {
  test("is stable regardless of dims key order and differs per rule", () => {
    expect(dedupeKey("R-1", { b: "2", a: "1" })).toBe(dedupeKey("R-1", { a: "1", b: "2" }));
    expect(dedupeKey("R-1", { a: "1" })).not.toBe(dedupeKey("R-2", { a: "1" }));
    expect(dedupeKey("R-1", { a: "1" })).toMatch(/^R-1:[0-9a-f]{64}$/);
  });
});

describe("decideFinding", () => {
  test("a new finding is inserted and surfaced", () => {
    expect(decideFinding(null, cand, ctx)).toEqual({ action: "insert", surface: true, reason: "new", reopen: false, occurrences: 1 });
  });

  // Why: request §18 — "Do not repeat the same finding unless …". An unchanged problem must
  // not reappear in every morning brief.
  test("unchanged active finding is updated but not resurfaced", () => {
    expect(decideFinding(existing(), cand, ctx)).toEqual({ action: "update", surface: false, reason: null, reopen: false, occurrences: 4 });
  });

  test.each([
    [{ severity: "critical" as const }, {}, "severity_increased"],
    [{ impact: 1300 }, {}, "impact_changed"],
    [{ impact: 700 }, {}, "impact_changed"],
    [{ sampleSize: 130 }, {}, "new_evidence"],
    [{}, { taskOverdue: true }, "task_overdue"],
  ])("resurfaces when %o / %o => %s", (c, x, reason) => {
    const d = decideFinding(existing(), { ...cand, ...c }, { ...ctx, ...x });
    expect(d).toMatchObject({ action: "update", surface: true, reason });
  });

  // Why (review): month-to-date windows grow by one day per run; raw totals would resurface the
  // same finding every morning of the first week ("new evidence", "impact changed").
  test("a growing month-to-date window does not resurface at the same daily rate", () => {
    const mtd = existing({ estimatedImpact: 200, sampleSize: 40, windowDays: 2 });
    expect(decideFinding(mtd, { severity: "high", impact: 300, sampleSize: 60, windowDays: 3 }, ctx).surface).toBe(false);
    expect(decideFinding(mtd, { severity: "high", impact: 600, sampleSize: 60, windowDays: 3 }, ctx)).toMatchObject({ surface: true, reason: "impact_changed" });
    expect(decideFinding({ ...mtd, windowDays: null }, { severity: "high", impact: 300, sampleSize: 60, windowDays: 3 }, ctx).surface).toBe(true); // unknown length: raw comparison
  });

  test("small impact changes do not resurface", () => {
    expect(decideFinding(existing(), { ...cand, impact: 1100 }, ctx).surface).toBe(false);
  });

  test("monitoring findings resurface only after the cooldown since the last surfacing", () => {
    expect(decideFinding(existing({ status: "monitoring", lastSurfacedAt: daysAgo(3) }), cand, ctx).surface).toBe(false);
    expect(decideFinding(existing({ status: "monitoring", lastSurfacedAt: daysAgo(8) }), cand, ctx)).toMatchObject({ surface: true, reason: "monitoring" });
  });

  test("resolved findings stay quiet within the cooldown and reopen after it", () => {
    expect(decideFinding(existing({ status: "resolved", statusChangedAt: daysAgo(2) }), cand, ctx)).toMatchObject({ surface: false, reopen: false });
    expect(decideFinding(existing({ status: "resolved", statusChangedAt: daysAgo(9) }), cand, ctx)).toMatchObject({ surface: true, reopen: true, reason: "recurred" });
  });

  test("dismissed findings stay dismissed unless severity increases", () => {
    expect(decideFinding(existing({ status: "dismissed" }), { ...cand, impact: 5000 }, ctx)).toMatchObject({ surface: false, reopen: false });
    expect(decideFinding(existing({ status: "dismissed" }), { ...cand, severity: "critical" }, ctx)).toMatchObject({ surface: true, reopen: true, reason: "severity_increased" });
  });
});
```

- [ ] **Step 3: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/engine/scoring.test.ts src/lib/intel/engine/dedupe.test.ts
```
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 4: Implement scoring** — `LAAM/src/lib/intel/engine/scoring.ts`

```ts
// Severity-by-impact (request Part 3 §19) and priority score (request Part 3 §18). All
// thresholds and weights come from the pack's scoring.yaml (or rule_override).
import { matchesAny } from "./glob";
import type { CompareMode, Scoring, Severity } from "../pack/schema";

type Tier = Scoring["severity_by_impact"]["tiers"][number];

export function impactThreshold(tier: Tier, weeklySales: number | null): number {
  const pctAmount = weeklySales != null ? (tier.min_pct_weekly_sales / 100) * weeklySales : 0;
  return Math.max(tier.min_amount, pctAmount);
}

const fmt = (x: number): string => (Math.round(x * 100) / 100).toString();

export function severityByImpact(
  impact: number | null,
  impactUnit: string | null,
  weeklySales: number | null,
  cfg: Scoring["severity_by_impact"],
): { level: Severity; reason: string } {
  if (impact == null || impactUnit !== "currency") {
    return { level: cfg.otherwise, reason: `no currency impact; default ${cfg.otherwise}` };
  }
  const magnitude = Math.abs(impact);
  for (const tier of cfg.tiers) {
    const t = impactThreshold(tier, weeklySales);
    if (magnitude > t) {
      return {
        level: tier.level,
        reason: `impact ${fmt(magnitude)} > ${fmt(t)} (greater of ${tier.min_amount} and ${tier.min_pct_weekly_sales}% of weekly sales)`,
      };
    }
  }
  return { level: cfg.otherwise, reason: `impact ${fmt(magnitude)} below every tier; default ${cfg.otherwise}` };
}

export interface PriorityInput {
  impact: number | null;
  impactUnit: string | null;
  weeklySales: number | null;
  severity: Severity;
  confidence: number;
  compareMode: CompareMode;
  variancePct: number | null;
  locationCount: number;
  totalLocations: number;
  occurrences: number;
  ruleId: string;
}

export type PriorityComponents = Record<keyof Scoring["priority_weights"], number>;

const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));

export function priorityScore(
  i: PriorityInput,
  scoring: Scoring,
  weights: Scoring["priority_weights"],
): { score: number; components: PriorityComponents } {
  const topThreshold = Math.max(...scoring.severity_by_impact.tiers.map((t) => impactThreshold(t, i.weeklySales)));
  const components: PriorityComponents = {
    financial: i.impact != null && i.impactUnit === "currency" && topThreshold > 0 ? clamp01(Math.abs(i.impact) / topThreshold) : 0,
    urgency: scoring.urgency[i.severity],
    confidence: clamp01(i.confidence),
    target_variance:
      i.compareMode === "target" && i.variancePct != null
        ? clamp01(Math.abs(i.variancePct) / scoring.normalization.target_variance_pct)
        : 0,
    locations: i.totalLocations > 0 ? clamp01(i.locationCount / i.totalLocations) : 0,
    repeated: clamp01(Math.max(0, i.occurrences - 1) / scoring.normalization.repeated_occurrences),
    strategic: matchesAny(scoring.strategic_rules, i.ruleId) ? 1 : 0,
  };
  const keys = Object.keys(weights) as (keyof PriorityComponents)[];
  const totalW = keys.reduce((s, k) => s + weights[k], 0);
  const weighted = keys.reduce((s, k) => s + weights[k] * components[k], 0);
  return { score: totalW > 0 ? Math.round(((100 * weighted) / totalW) * 100) / 100 : 0, components };
}
```

- [ ] **Step 5: Implement dedupe** — `LAAM/src/lib/intel/engine/dedupe.ts`

```ts
// One finding per (rule, dims) per project, and the rules for when an existing finding goes
// back into the brief (spec §7.5; request Part 3 §18 "Alert cooldown").
import { createHash } from "node:crypto";
import type { FindingStatus } from "@/db/schema";
import { SEVERITY_RANK, type Scoring, type Severity } from "../pack/schema";

export function dimsHash(dims: Readonly<Record<string, string>>): string {
  const sorted = Object.fromEntries(Object.entries(dims).sort(([a], [b]) => a.localeCompare(b)));
  return createHash("sha256").update(JSON.stringify(sorted)).digest("hex");
}

export function dedupeKey(ruleId: string, dims: Readonly<Record<string, string>>): string {
  return `${ruleId}:${dimsHash(dims)}`;
}

export interface ExistingFinding {
  id: string;
  status: FindingStatus;
  severity: Severity;
  estimatedImpact: number | null;
  sampleSize: number;
  occurrences: number;
  statusChangedAt: Date;
  lastSurfacedAt: Date | null;
  /** Length of the evaluated window (days); month-to-date windows grow daily. Null = unknown. */
  windowDays: number | null;
}

export type SurfaceReason =
  | "new" | "recurred" | "severity_increased" | "impact_changed" | "new_evidence" | "task_overdue" | "monitoring";

export interface FindingDecision {
  action: "insert" | "update";
  surface: boolean;
  reason: SurfaceReason | null;
  reopen: boolean;
  occurrences: number;
}

const DAY_MS = 86_400_000;

export function decideFinding(
  existing: ExistingFinding | null,
  cand: { severity: Severity; impact: number | null; sampleSize: number; windowDays: number | null },
  ctx: { now: Date; cooldownDays: number; taskOverdue: boolean; resurfacing: Scoring["resurfacing"] },
): FindingDecision {
  if (!existing) return { action: "insert", surface: true, reason: "new", reopen: false, occurrences: 1 };
  const occurrences = existing.occurrences + 1;
  const quiet: FindingDecision = { action: "update", surface: false, reason: null, reopen: false, occurrences };
  const loud = (reason: SurfaceReason, reopen = false): FindingDecision => ({ action: "update", surface: true, reason, reopen, occurrences });
  const severityUp = SEVERITY_RANK[cand.severity] > SEVERITY_RANK[existing.severity];
  const sinceStatus = (ctx.now.getTime() - existing.statusChangedAt.getTime()) / DAY_MS;

  if (existing.status === "resolved") {
    return sinceStatus >= ctx.cooldownDays ? loud("recurred", true) : quiet;
  }
  if (existing.status === "dismissed") {
    return severityUp ? loud("severity_increased", true) : quiet;
  }

  if (severityUp) return loud("severity_increased");
  // Impact and sample grow with the window length. A month-to-date window grows by a day every run
  // (sample +25%/day in the first week), so compare PER-DAY rates whenever both lengths are known;
  // for fixed windows (equal lengths) this is the plain comparison.
  const perDay = existing.windowDays && cand.windowDays ? { old: existing.windowDays, cur: cand.windowDays } : { old: 1, cur: 1 };
  const old = existing.estimatedImpact != null ? existing.estimatedImpact / perDay.old : null;
  const cur = cand.impact != null ? cand.impact / perDay.cur : null;
  if (old != null && old !== 0 && cur != null) {
    if ((Math.abs(cur - old) / Math.abs(old)) * 100 > ctx.resurfacing.impact_change_pct) return loud("impact_changed");
  }
  const oldSample = existing.sampleSize / perDay.old;
  const curSample = cand.sampleSize / perDay.cur;
  if (oldSample > 0 && ((curSample - oldSample) / oldSample) * 100 >= ctx.resurfacing.sample_growth_pct) {
    return loud("new_evidence");
  }
  if (ctx.taskOverdue) return loud("task_overdue");
  if (existing.status === "monitoring") {
    const sinceSurfaced = existing.lastSurfacedAt ? (ctx.now.getTime() - existing.lastSurfacedAt.getTime()) / DAY_MS : Infinity;
    if (sinceSurfaced >= ctx.cooldownDays) return loud("monitoring");
  }
  return quiet;
}
```

- [ ] **Step 6: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/engine/scoring.test.ts src/lib/intel/engine/dedupe.test.ts
```
Expected: PASS (scoring 13, dedupe 13).

- [ ] **Step 7: Commit**

```bash
git -C LAAM add src/lib/intel/engine/scoring.ts src/lib/intel/engine/scoring.test.ts src/lib/intel/engine/dedupe.ts src/lib/intel/engine/dedupe.test.ts
git -C LAAM commit -m "feat(intel): impact-based severity, priority score, dedupe and resurfacing rules"
```

---

### Task 12: Store Health Score (engine, trọng số trong pack)

**Files:**
- Create: `LAAM/src/lib/intel/engine/health.ts`, `LAAM/src/lib/intel/engine/health.test.ts`

**Interfaces:**
- Consumes: `Scoring["health_score"]`, `Scoring["confidence"]` (Task 6), `matchesAny` (Task 10), `DataStatusItem` (Task 3).
- Produces:
```ts
export interface HealthFindingInput { ruleId: string; severity: Severity; locationIds: readonly string[] }
export interface HealthComponent { score: number; weight: number; reasons: string[] }
export interface HealthScore { locationId: string; score: number; status: string; components: Record<string, HealthComponent>; change: number | null }
export function computeHealthScores(i: { locations: readonly string[]; findings: readonly HealthFindingInput[]; dataStatus: readonly DataStatusItem[]; cfg: Scoring["health_score"]; freshness: { current: number; delayed: number }; previous?: Readonly<Record<string, number>> }): HealthScore[];
```

Thiết kế (request Part 3 §15): điểm 0–100 = trung bình có trọng số của các thành phần trong `health_score.components` (retail: sales & margin 30, inventory 25, refund/discount/LP 20, labor 15) + data quality 10. Mỗi thành phần bắt đầu 100 và **chỉ bị trừ** theo `severity_penalty` của các finding hiện tại ở location đó có `rule_id` khớp glob của thành phần — **không có điểm cộng**, nên doanh thu lớn không thể "che" vấn đề cash/inventory/LP. Data quality = trung bình freshness của các mục `data_status` × 100 (current = `freshness_current`, delayed = `freshness_delayed`, khác = 0). Trạng thái theo `status_bands` (85 healthy / 70 monitor / 50 needs attention / 0 high priority). `change` = so với điểm của run trước (đọc từ `analysis_run.summary`, Task 16). Finding cấp chuỗi (`locationIds = []`) không trừ điểm location nào (không quy được cho location cụ thể).

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/lib/intel/engine/health.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { computeHealthScores } from "./health";
import type { Scoring } from "../pack/schema";
import { currentStatus } from "../testing/fixtures";

const cfg: Scoring["health_score"] = {
  components: {
    sales_margin: { weight: 30, rules: ["ACME-SALES-*"] },
    inventory: { weight: 25, rules: ["ACME-INV-*"] },
    loss_prevention: { weight: 20, rules: ["ACME-LP-*"] },
    labor: { weight: 15, rules: ["ACME-LAB-*"] },
  },
  data_quality_weight: 10,
  severity_penalty: { critical: 60, high: 40, medium: 20, warning: 20, low: 5 },
  status_bands: [{ min: 85, label: "healthy" }, { min: 70, label: "monitor" }, { min: 50, label: "needs_attention" }, { min: 0, label: "high_priority" }],
};
const freshness = { current: 1, delayed: 0.7 };

describe("computeHealthScores", () => {
  test("no findings and current data => 100 healthy", () => {
    const [s] = computeHealthScores({ locations: ["L1"], findings: [], dataStatus: currentStatus(["a"]), cfg, freshness });
    expect(s).toMatchObject({ locationId: "L1", score: 100, status: "healthy", change: null });
  });

  test("findings subtract from their component at their location only", () => {
    const out = computeHealthScores({
      locations: ["L1", "L2"],
      findings: [{ ruleId: "ACME-LP-001", severity: "critical", locationIds: ["L1"] }, { ruleId: "ACME-INV-002", severity: "high", locationIds: ["L1"] }],
      dataStatus: currentStatus(["a"]), cfg, freshness,
    });
    const l1 = out.find((s) => s.locationId === "L1")!;
    expect(l1.components.loss_prevention).toEqual({ score: 40, weight: 20, reasons: ["ACME-LP-001 (critical)"] });
    expect(l1.components.inventory.score).toBe(60);
    expect(l1.score).toBeCloseTo((30 * 100 + 25 * 60 + 20 * 40 + 15 * 100 + 10 * 100) / 100, 10); // 78
    expect(l1.status).toBe("monitor");
    expect(out.find((s) => s.locationId === "L2")!.score).toBe(100);
  });

  // Why: request §15 — one large sales number must not hide cash/inventory/LP problems.
  test("there is no positive offset: penalties only, floored at zero", () => {
    const [s] = computeHealthScores({
      locations: ["L1"],
      findings: Array.from({ length: 3 }, () => ({ ruleId: "ACME-LP-9", severity: "critical" as const, locationIds: ["L1"] })),
      dataStatus: currentStatus(["a"]), cfg, freshness,
    });
    expect(s.components.loss_prevention.score).toBe(0);
  });

  test("data quality follows data status; change is measured against the previous run", () => {
    const [s] = computeHealthScores({
      locations: ["L1"], findings: [],
      dataStatus: [...currentStatus(["a"]), ...currentStatus(["b"], "delayed"), ...currentStatus(["c"], "stale")],
      cfg, freshness, previous: { L1: 99 },
    });
    expect(s.components.data_quality.score).toBeCloseTo(((1 + 0.7 + 0) / 3) * 100, 10);
    expect(s.components.data_quality.reasons).toEqual(["metric:b delayed", "metric:c stale"]);
    expect(s.change).toBeCloseTo(s.score - 99, 10);
  });

  test("chain-level findings (no location) do not penalise any location", () => {
    const [s] = computeHealthScores({ locations: ["L1"], findings: [{ ruleId: "ACME-LP-1", severity: "critical", locationIds: [] }], dataStatus: currentStatus(["a"]), cfg, freshness });
    expect(s.score).toBe(100);
  });
});
```

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/engine/health.test.ts
```
Expected: FAIL — `Cannot find module './health'`.

- [ ] **Step 3: Implement** — `LAAM/src/lib/intel/engine/health.ts`

```ts
// Store Health Score (request Part 3 §15). Components and weights are pack config; components
// only lose points (penalties per finding severity), so strong sales cannot mask control issues.
import { matchesAny } from "./glob";
import type { Scoring, Severity } from "../pack/schema";
import type { DataStatusItem } from "../provider/types";

export interface HealthFindingInput {
  ruleId: string;
  severity: Severity;
  locationIds: readonly string[];
}
export interface HealthComponent {
  score: number;
  weight: number;
  reasons: string[];
}
export interface HealthScore {
  locationId: string;
  score: number;
  status: string;
  components: Record<string, HealthComponent>;
  change: number | null;
}

const DATA_QUALITY = "data_quality";
const round1 = (x: number): number => Math.round(x * 10) / 10;

export function computeHealthScores(i: {
  locations: readonly string[];
  findings: readonly HealthFindingInput[];
  dataStatus: readonly DataStatusItem[];
  cfg: Scoring["health_score"];
  freshness: { current: number; delayed: number };
  previous?: Readonly<Record<string, number>>;
}): HealthScore[] {
  const fresh = (s: DataStatusItem["status"]) => (s === "current" ? i.freshness.current : s === "delayed" ? i.freshness.delayed : 0);
  const dqScore = i.dataStatus.length ? (i.dataStatus.reduce((s, d) => s + fresh(d.status), 0) / i.dataStatus.length) * 100 : 100;
  const dqReasons = i.dataStatus.filter((d) => d.status !== "current").map((d) => `${d.subject} ${d.status}`);
  const bands = [...i.cfg.status_bands].sort((a, b) => b.min - a.min);

  return i.locations.map((loc) => {
    const components: Record<string, HealthComponent> = {};
    for (const [name, comp] of Object.entries(i.cfg.components)) {
      const hits = i.findings.filter((f) => f.locationIds.includes(loc) && matchesAny(comp.rules, f.ruleId));
      const penalty = hits.reduce((s, f) => s + i.cfg.severity_penalty[f.severity], 0);
      components[name] = { score: Math.max(0, 100 - penalty), weight: comp.weight, reasons: hits.map((f) => `${f.ruleId} (${f.severity})`) };
    }
    components[DATA_QUALITY] = { score: dqScore, weight: i.cfg.data_quality_weight, reasons: dqReasons };
    const totalW = Object.values(components).reduce((s, c) => s + c.weight, 0);
    const score = round1(totalW > 0 ? Object.values(components).reduce((s, c) => s + c.weight * c.score, 0) / totalW : 0);
    const status = bands.find((b) => score >= b.min)?.label ?? bands[bands.length - 1].label;
    const prev = i.previous?.[loc];
    return { locationId: loc, score, status, components, change: prev != null ? round1(score - prev) : null };
  });
}
```

Ghi chú khớp test: `score` làm tròn 1 chữ số ⇒ test data-quality `change` dùng `toBeCloseTo(s.score - 99, 10)` vẫn đúng vì cả hai cùng từ `score` đã làm tròn; `data_quality.score` không làm tròn (`toBeCloseTo(56.666…, 10)`). Test `l1.score` = 78 chính xác.

- [ ] **Step 4: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/engine/health.test.ts
```
Expected: PASS 5/5.

- [ ] **Step 5: Commit**

```bash
git -C LAAM add src/lib/intel/engine/health.ts src/lib/intel/engine/health.test.ts
git -C LAAM commit -m "feat(intel): store health score with pack-configured components"
```

---

### Task 13: Forecast — Holt-Winters damped, baseline, backtest, khoảng P10–P90, cổng lịch sử

**Files:**
- Create: `LAAM/src/lib/intel/forecast/holt-winters.ts`, `forecast/forecast.ts`, `forecast/forecast.test.ts`

**Interfaces:**
- Consumes: không (thuần).
- Produces:
```ts
// holt-winters.ts
export interface HwParams { alpha: number; beta: number; gamma: number; phi: number }
export interface HwModel { params: HwParams; level: number; trend: number; season: number[]; seasonLength: number; n: number; sse: number }
export const ALL_PHIS: readonly number[]; export const DAMPED_PHIS: readonly number[];
export function fitHoltWinters(y: readonly number[], m: number, p: HwParams): HwModel;
export function forecastHoltWinters(model: HwModel, h: number): number[];
export function fitBest(y: readonly number[], m: number, phis: readonly number[]): HwModel;
// forecast.ts
export const MODEL_VERSION = "hw-additive-grid-v1";
export const HISTORY_GATE = { minDays: 56, normalDays: 126 };   // 8 / 18 weeks (spec §7.6)
export type ModelName = "holt_winters" | "seasonal_naive" | "moving_average_28";
export interface BacktestStats { mae: number; mape: number | null; origins: number }
export const MIN_BACKTEST_ORIGINS = 2;
export interface HorizonForecast { horizonDays: number; model: ModelName; reliable: boolean; interval: boolean; point: number[]; lower: number[]; upper: number[]; sum: { point: number; lower: number | null; upper: number | null }; dampedPoint: number[]; dampedSum: number; backtest: Record<ModelName, BacktestStats> | null }   // interval=false => lower/upper = [] and sum bounds null
export interface ForecastOutput { status: "ok" | "insufficient_history"; label: "normal" | "low_confidence" | null; historyDays: number; modelVersion: string; warnings: string[]; horizons: HorizonForecast[] }
export function seasonalNaive(y: readonly number[], m: number, h: number): number[];
export function movingAverage(y: readonly number[], window: number, h: number): number[];
export function quantile(xs: readonly number[], q: number): number;
export function forecastSeries(y: readonly number[], opts: { horizons: readonly number[]; seasonLength: number; versionsInSeries: readonly number[]; origins?: number; step?: number }): ForecastOutput;
```

Thiết kế (spec §7.6, request RET-PRED-001 + "Prediction validation"):
- **Holt-Winters cộng tính**, mùa vụ m (7), có tham số **damped trend φ**. Khởi tạo: level/trend từ trung bình 2 mùa đầu, mùa vụ = độ lệch so với đường xu hướng ⇒ chuỗi "tuyến tính + mùa vụ" được tái tạo **chính xác** (test có đáp án). Tham số chọn bằng grid search theo SSE một bước (α 6 giá trị × β 4 × γ 4 × φ).
- Model công bố dùng φ ∈ {0.8, 0.9, 0.95, 0.98, 1}; dự báo cho preset *expected* dùng **chỉ φ < 1** (`dampedPoint`).
- **Baseline**: seasonal-naive (cùng thứ tuần trước) và trung bình động 28 ngày.
- **Backtest rolling-origin**: K = 6 gốc, cách nhau 7 ngày, gốc `o = n − H − j·7` (H = horizon lớn nhất), train `y[0..o)`, so `H` ngày kế; mỗi horizon h dùng h ngày đầu. MAE, MAPE (bỏ ngày thực tế = 0).
- **Chỉ công bố "reliable"** khi MAE (và MAPE nếu có) của Holt-Winters **nhỏ hơn hẳn** cả hai baseline; hoà = thua. Ngược lại công bố baseline có MAE nhỏ nhất, `reliable = false` (UI hiện nhãn).
- **Khoảng** = điểm + phân vị P10/P90 của residual backtest (gộp mọi bước); khoảng cho tổng horizon = phân vị của residual tổng theo từng gốc. **Cần ≥ 2 gốc backtest** (`MIN_BACKTEST_ORIGINS`): ít hơn ⇒ `interval: false`, `lower/upper = []`, `sum.lower/upper = null`, `reliable = false`, cảnh báo `no_backtest`/`insufficient_backtest` (56–64 ngày với horizon 30 chỉ có 0–1 gốc). Pipeline khi đó dùng `min_interval_factor` cho confidence của scenario thay vì coi khoảng rỗng là chắc chắn.
- **Cổng lịch sử**: < 56 ngày ⇒ `insufficient_history` (không dự báo); 56–125 ngày ⇒ `low_confidence`; ≥ 126 ⇒ `normal`. `versionsInSeries.length > 1` ⇒ cảnh báo `mixed_metric_versions`.
- Mùa vụ năm (request PRED-03, cần ≥ 12 tháng) **không** làm trong beta — ghi Open questions.

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/lib/intel/forecast/forecast.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { fitBest, fitHoltWinters, forecastHoltWinters, ALL_PHIS, type HwModel } from "./holt-winters";
import { forecastSeries, movingAverage, quantile, seasonalNaive } from "./forecast";

const S = [10, -5, 0, 5, -10, 3, -3]; // sums to 0
const linearSeasonal = (n: number, a = 100, b = 2) => Array.from({ length: n }, (_, t) => a + b * t + S[t % 7]);

describe("Holt-Winters (known answers)", () => {
  // Why: with level/trend/season initialised from the data, a noise-free trend + weekly
  // pattern must be reproduced exactly for any smoothing constants when phi = 1.
  test("a linear + weekly series is forecast exactly", () => {
    const y = linearSeasonal(70);
    const m = fitHoltWinters(y, 7, { alpha: 0.3, beta: 0.1, gamma: 0.2, phi: 1 });
    expect(m.sse).toBeCloseTo(0, 8);
    const f = forecastHoltWinters(m, 10);
    f.forEach((v, k) => expect(v).toBeCloseTo(100 + 2 * (70 + k) + S[(70 + k) % 7], 8));
  });

  test("damped trend adds phi + phi^2 + ... of the trend", () => {
    const model: HwModel = { params: { alpha: 0, beta: 0, gamma: 0, phi: 0.5 }, level: 100, trend: 4, season: [0, 0, 0, 0, 0, 0, 0], seasonLength: 7, n: 14, sse: 0 };
    expect(forecastHoltWinters(model, 3)).toEqual([102, 103, 103.5]);
    expect(forecastHoltWinters({ ...model, params: { ...model.params, phi: 1 } }, 3)).toEqual([104, 108, 112]);
  });

  test("grid search prefers the parameters with the lowest SSE", () => {
    expect(fitBest(linearSeasonal(70), 7, ALL_PHIS).params.phi).toBe(1);
  });

  test("needs two full seasons", () => {
    expect(() => fitHoltWinters([1, 2, 3], 7, { alpha: 0.1, beta: 0.1, gamma: 0.1, phi: 1 })).toThrow(/at least 14/);
  });
});

describe("baselines and quantiles", () => {
  test("seasonal naive repeats the last observed week", () => {
    expect(seasonalNaive([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14], 7, 9)).toEqual([8, 9, 10, 11, 12, 13, 14, 8, 9]);
  });
  test("moving average is flat at the mean of the last window", () => {
    expect(movingAverage([1, 1, 1, 3, 3, 3], 3, 2)).toEqual([3, 3]);
  });
  test("quantile interpolates linearly", () => {
    expect(quantile([0, 10], 0.1)).toBeCloseTo(1, 10);
    expect(quantile([5], 0.9)).toBe(5);
  });
});

describe("forecastSeries", () => {
  test("publishes Holt-Winters as reliable when it beats both baselines", () => {
    const out = forecastSeries(linearSeasonal(200), { horizons: [7, 30], seasonLength: 7, versionsInSeries: [1] });
    expect(out).toMatchObject({ status: "ok", label: "normal", historyDays: 200, warnings: [] });
    const h30 = out.horizons.find((h) => h.horizonDays === 30)!;
    expect(h30.model).toBe("holt_winters");
    expect(h30.reliable).toBe(true);
    expect(h30.point[0]).toBeCloseTo(100 + 2 * 200 + S[200 % 7], 6);
    expect(h30.backtest!.holt_winters.mae).toBeLessThan(h30.backtest!.seasonal_naive.mae);
    expect(h30.upper[0] - h30.lower[0]).toBeCloseTo(0, 6);
    expect(h30.dampedSum).toBeLessThan(h30.sum.point); // expected preset grows slower on an upward trend
  });

  // Why: request — "Do not publish a prediction as reliable if it cannot outperform the approved
  // baseline". A tie is not outperforming: here seasonal-naive is exact, so HW cannot beat it.
  test("falls back to the best baseline when the model loses the backtest", () => {
    const periodic = Array.from({ length: 140 }, (_, t) => 50 + S[t % 7]);
    const h7 = forecastSeries(periodic, { horizons: [7], seasonLength: 7, versionsInSeries: [1] }).horizons[0];
    expect(h7.reliable).toBe(false);
    expect(h7.model).toBe("seasonal_naive");
    expect(h7.point).toEqual(seasonalNaive(periodic, 7, 7));
    expect(h7.dampedPoint).toEqual(h7.point);
  });

  test("history gate: under 8 weeks no forecast, 8-18 weeks low confidence", () => {
    expect(forecastSeries(linearSeasonal(50), { horizons: [7], seasonLength: 7, versionsInSeries: [1] })).toMatchObject({ status: "insufficient_history", horizons: [] });
    expect(forecastSeries(linearSeasonal(80), { horizons: [7], seasonLength: 7, versionsInSeries: [1] }).label).toBe("low_confidence");
  });

  // Why (review): with 56-64 days and horizons [7, 30] only 0-1 backtest origins exist; a
  // zero-width interval would read as "certain" and give the best interval factor.
  test("fewer than two backtest origins: no interval, not reliable, warning", () => {
    const out = forecastSeries(linearSeasonal(60), { horizons: [7, 30], seasonLength: 7, versionsInSeries: [1] });
    expect(out.warnings).toContain("insufficient_backtest");
    const h30 = out.horizons.find((h) => h.horizonDays === 30)!;
    expect(h30).toMatchObject({ interval: false, reliable: false, lower: [], upper: [], sum: { lower: null, upper: null } });
    expect(h30.point).toHaveLength(30);
  });

  test("warns when the series mixes metric versions", () => {
    expect(forecastSeries(linearSeasonal(130), { horizons: [7], seasonLength: 7, versionsInSeries: [1, 2] }).warnings).toContain("mixed_metric_versions");
  });

  test("noisy history yields a non-degenerate P10-P90 interval", () => {
    const noisy = linearSeasonal(180).map((v, t) => v + ((t * 7919) % 13) - 6);
    const h = forecastSeries(noisy, { horizons: [30], seasonLength: 7, versionsInSeries: [1] }).horizons[0];
    expect(h.upper[0] - h.lower[0]).toBeGreaterThan(0);
    expect(h.sum.upper).toBeGreaterThan(h.sum.lower);
    expect(h.backtest!.holt_winters.origins).toBe(6);
  });
});
```

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/forecast/forecast.test.ts
```
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 3: Implement** — `LAAM/src/lib/intel/forecast/holt-winters.ts`

```ts
// Additive Holt-Winters with an optional damped trend (spec §7.6). Initialisation follows the
// classic decomposition: level/trend from the first two seasons, seasonal indices as deviations
// from that trend line — a noise-free "trend + weekly pattern" series is then fitted exactly.
export interface HwParams {
  alpha: number;
  beta: number;
  gamma: number;
  phi: number;
}
export interface HwModel {
  params: HwParams;
  level: number;
  trend: number;
  season: number[];
  seasonLength: number;
  n: number;
  sse: number;
}

const ALPHAS = [0.05, 0.1, 0.2, 0.3, 0.5, 0.7];
const BETAS = [0.01, 0.05, 0.1, 0.2];
const GAMMAS = [0.05, 0.1, 0.2, 0.3];
export const DAMPED_PHIS: readonly number[] = [0.8, 0.9, 0.95, 0.98];
export const ALL_PHIS: readonly number[] = [...DAMPED_PHIS, 1];

const avg = (xs: readonly number[]): number => xs.reduce((s, x) => s + x, 0) / xs.length;

export function fitHoltWinters(y: readonly number[], m: number, p: HwParams): HwModel {
  if (y.length < 2 * m) throw new Error(`Holt-Winters needs at least ${2 * m} points, got ${y.length}`);
  const mean1 = avg(y.slice(0, m));
  const mean2 = avg(y.slice(m, 2 * m));
  const trend0 = (mean2 - mean1) / m;
  const center = (m - 1) / 2;
  const season = Array.from({ length: m }, (_, i) => y[i] - (mean1 + trend0 * (i - center)));
  let level = mean1 + trend0 * (m - 1 - center); // level at t = m - 1
  let trend = trend0;
  let sse = 0;
  for (let t = m; t < y.length; t++) {
    const s = season[t % m];
    const err = y[t] - (level + p.phi * trend + s);
    sse += err * err;
    const newLevel = p.alpha * (y[t] - s) + (1 - p.alpha) * (level + p.phi * trend);
    trend = p.beta * (newLevel - level) + (1 - p.beta) * p.phi * trend;
    season[t % m] = p.gamma * (y[t] - newLevel) + (1 - p.gamma) * s;
    level = newLevel;
  }
  return { params: p, level, trend, season, seasonLength: m, n: y.length, sse };
}

export function forecastHoltWinters(model: HwModel, h: number): number[] {
  const out: number[] = [];
  let damp = 0;
  let phiPow = 1;
  for (let k = 1; k <= h; k++) {
    phiPow *= model.params.phi;
    damp += phiPow;
    out.push(model.level + damp * model.trend + model.season[(model.n - 1 + k) % model.seasonLength]);
  }
  return out;
}

export function fitBest(y: readonly number[], m: number, phis: readonly number[]): HwModel {
  let best: HwModel | null = null;
  for (const alpha of ALPHAS) {
    for (const beta of BETAS) {
      for (const gamma of GAMMAS) {
        for (const phi of phis) {
          const model = fitHoltWinters(y, m, { alpha, beta, gamma, phi });
          if (!best || model.sse < best.sse) best = model;
        }
      }
    }
  }
  return best as HwModel;
}
```

- [ ] **Step 4: Implement** — `LAAM/src/lib/intel/forecast/forecast.ts`

```ts
// Forecast with baselines, rolling-origin backtest, residual intervals and a history gate
// (spec §7.6). A model is "reliable" only if it beats BOTH baselines; otherwise the best
// baseline is published with reliable = false.
import { ALL_PHIS, DAMPED_PHIS, fitBest, forecastHoltWinters } from "./holt-winters";

export const MODEL_VERSION = "hw-additive-grid-v1";
export const HISTORY_GATE = { minDays: 56, normalDays: 126 } as const;
const MA_WINDOW = 28;
const DEFAULT_ORIGINS = 6;
// Residual quantiles from one origin are not an interval (q10 = q90 = that single error).
export const MIN_BACKTEST_ORIGINS = 2;
const DEFAULT_STEP = 7;

export type ModelName = "holt_winters" | "seasonal_naive" | "moving_average_28";
const MODELS: readonly ModelName[] = ["holt_winters", "seasonal_naive", "moving_average_28"];

export interface BacktestStats {
  mae: number;
  mape: number | null;
  origins: number;
}
export interface HorizonForecast {
  horizonDays: number;
  model: ModelName;
  reliable: boolean;
  /** False when fewer than MIN_BACKTEST_ORIGINS backtest origins exist: no honest interval. */
  interval: boolean;
  point: number[];
  lower: number[]; // [] when interval = false
  upper: number[]; // [] when interval = false
  sum: { point: number; lower: number | null; upper: number | null };
  dampedPoint: number[];
  dampedSum: number;
  backtest: Record<ModelName, BacktestStats> | null;
}
export interface ForecastOutput {
  status: "ok" | "insufficient_history";
  label: "normal" | "low_confidence" | null;
  historyDays: number;
  modelVersion: string;
  warnings: string[];
  horizons: HorizonForecast[];
}

export function seasonalNaive(y: readonly number[], m: number, h: number): number[] {
  const n = y.length;
  return Array.from({ length: h }, (_, k) => y[n - m + (k % m)]);
}

export function movingAverage(y: readonly number[], window: number, h: number): number[] {
  const tail = y.slice(Math.max(0, y.length - window));
  const mean = tail.reduce((s, x) => s + x, 0) / tail.length;
  return Array.from({ length: h }, () => mean);
}

export function quantile(xs: readonly number[], q: number): number {
  const s = [...xs].sort((a, b) => a - b);
  if (s.length === 0) return 0;
  const pos = (s.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}

const sum = (xs: readonly number[]): number => xs.reduce((s, x) => s + x, 0);

type Forecaster = (train: readonly number[], h: number) => number[];

function forecasters(m: number): Record<ModelName, Forecaster> {
  return {
    holt_winters: (train, h) => forecastHoltWinters(fitBest(train, m, ALL_PHIS), h),
    seasonal_naive: (train, h) => seasonalNaive(train, m, h),
    moving_average_28: (train, h) => movingAverage(train, MA_WINDOW, h),
  };
}

interface Errors {
  abs: number[];
  ape: number[];
  residuals: number[];
  sumResiduals: number[];
}

function backtest(
  y: readonly number[],
  horizons: readonly number[],
  m: number,
  originsWanted: number,
  step: number,
): { origins: number; errors: Record<ModelName, Map<number, Errors>> } {
  const H = Math.max(...horizons);
  const minTrain = Math.max(2 * m, MA_WINDOW);
  const fns = forecasters(m);
  const errors = Object.fromEntries(
    MODELS.map((name) => [name, new Map(horizons.map((h) => [h, { abs: [], ape: [], residuals: [], sumResiduals: [] } as Errors]))]),
  ) as Record<ModelName, Map<number, Errors>>;
  let origins = 0;
  for (let j = 0; j < originsWanted; j++) {
    const o = y.length - H - j * step;
    if (o < minTrain) break;
    origins++;
    const train = y.slice(0, o);
    const actual = y.slice(o, o + H);
    for (const name of MODELS) {
      const f = fns[name](train, H);
      for (const h of horizons) {
        const e = errors[name].get(h) as Errors;
        for (let k = 0; k < h; k++) {
          const r = actual[k] - f[k];
          e.residuals.push(r);
          e.abs.push(Math.abs(r));
          if (actual[k] !== 0) e.ape.push(Math.abs(r) / Math.abs(actual[k]));
        }
        e.sumResiduals.push(sum(actual.slice(0, h)) - sum(f.slice(0, h)));
      }
    }
  }
  return { origins, errors };
}

function stats(e: Errors, origins: number): BacktestStats {
  return {
    mae: e.abs.length ? sum(e.abs) / e.abs.length : Number.POSITIVE_INFINITY,
    mape: e.ape.length ? (100 * sum(e.ape)) / e.ape.length : null,
    origins,
  };
}

function beats(a: BacktestStats, b: BacktestStats): boolean {
  if (!(a.mae < b.mae)) return false;
  if (a.mape !== null && b.mape !== null && !(a.mape < b.mape)) return false;
  return true;
}

export function forecastSeries(
  y: readonly number[],
  opts: { horizons: readonly number[]; seasonLength: number; versionsInSeries: readonly number[]; origins?: number; step?: number },
): ForecastOutput {
  const warnings: string[] = [];
  if (opts.versionsInSeries.length > 1) warnings.push("mixed_metric_versions");
  const n = y.length;
  if (n < HISTORY_GATE.minDays) {
    return { status: "insufficient_history", label: null, historyDays: n, modelVersion: MODEL_VERSION, warnings, horizons: [] };
  }
  const m = opts.seasonLength;
  const label = n < HISTORY_GATE.normalDays ? "low_confidence" : "normal";
  const { origins, errors } = backtest(y, opts.horizons, m, opts.origins ?? DEFAULT_ORIGINS, opts.step ?? DEFAULT_STEP);
  if (origins === 0) warnings.push("no_backtest");
  else if (origins < MIN_BACKTEST_ORIGINS) warnings.push("insufficient_backtest");
  const hasInterval = origins >= MIN_BACKTEST_ORIGINS;

  const fns = forecasters(m);
  const H = Math.max(...opts.horizons);
  const full: Record<ModelName, number[]> = {
    holt_winters: fns.holt_winters(y, H),
    seasonal_naive: fns.seasonal_naive(y, H),
    moving_average_28: fns.moving_average_28(y, H),
  };
  const damped = forecastHoltWinters(fitBest(y, m, DAMPED_PHIS), H);

  const horizons = opts.horizons.map((h): HorizonForecast => {
    const bt = origins > 0
      ? (Object.fromEntries(MODELS.map((name) => [name, stats(errors[name].get(h) as Errors, origins)])) as Record<ModelName, BacktestStats>)
      : null;
    const reliable = hasInterval && !!bt && beats(bt.holt_winters, bt.seasonal_naive) && beats(bt.holt_winters, bt.moving_average_28);
    const model: ModelName = reliable
      ? "holt_winters"
      : bt && bt.moving_average_28.mae < bt.seasonal_naive.mae
        ? "moving_average_28"
        : "seasonal_naive";
    const point = full[model].slice(0, h);
    const e = errors[model].get(h) as Errors;
    const pointSum = sum(point);
    const dampedPoint = reliable ? damped.slice(0, h) : point;
    const q10 = hasInterval ? quantile(e.residuals, 0.1) : 0;
    const q90 = hasInterval ? quantile(e.residuals, 0.9) : 0;
    return {
      horizonDays: h,
      model,
      reliable,
      interval: hasInterval,
      point,
      lower: hasInterval ? point.map((v) => v + q10) : [],
      upper: hasInterval ? point.map((v) => v + q90) : [],
      sum: {
        point: pointSum,
        lower: hasInterval ? pointSum + quantile(e.sumResiduals, 0.1) : null,
        upper: hasInterval ? pointSum + quantile(e.sumResiduals, 0.9) : null,
      },
      dampedPoint,
      dampedSum: sum(dampedPoint),
      backtest: bt,
    };
  });
  return { status: "ok", label, historyDays: n, modelVersion: MODEL_VERSION, warnings, horizons };
}
```

- [ ] **Step 5: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/forecast/forecast.test.ts
```
Expected: PASS 13/13 (thời gian chạy < 10s; grid 480 tổ hợp × 7 lần fit mỗi chuỗi).

- [ ] **Step 6: Commit**

```bash
git -C LAAM add src/lib/intel/forecast/holt-winters.ts src/lib/intel/forecast/forecast.ts src/lib/intel/forecast/forecast.test.ts
git -C LAAM commit -m "feat(intel): Holt-Winters damped forecast with baselines, backtest gate and residual intervals"
```

---

### Task 14: Forecast service (theo `forecasts.yaml`, chia theo nhóm)

**Files:**
- Create: `LAAM/src/lib/intel/forecast/service.ts`, `LAAM/src/lib/intel/forecast/service.test.ts`

**Interfaces:**
- Consumes: `MetricsProvider`, `dimsKey` (Task 3), `ForecastCfg` (Task 6), `addDays/daysBetween` (Task 7), `forecastSeries` (Task 13).
- Produces:
```ts
export interface ForecastResult { metricKey: string; dims: Record<string, string>; startDate: string; output: ForecastOutput }
export interface ForecastSkip { metricKey: string; reason: string }
export async function runForecasts(provider: MetricsProvider, cfgs: readonly ForecastCfg[], catalog: ReadonlyMap<string, MetricCatalogItem>, asOf: string, opts?: { historyDays?: number }): Promise<{ results: ForecastResult[]; skipped: ForecastSkip[] }>;
export function forecastSum(results: readonly ForecastResult[], metricKey: string, dims: Readonly<Record<string, string>>, horizonDays: number, trend: "damped" | "model"): { value: number; reliable: boolean; lower: number | null; upper: number | null } | null;
```

Quy tắc: chỉ metric `additive` (spec §7.6 — margin suy ra từ doanh thu − chi phí, không dự báo tỉ lệ); lịch sử mặc định 400 ngày; liệt kê nhóm bằng một lời gọi `grain: total`, rồi **mỗi nhóm một lời gọi `grain: day` với `dimsFilter` của nhóm** (giữ mỗi phản hồi nhỏ — Review Focus #1); ngày thiếu trong khoảng ⇒ 0 và cảnh báo `filled_missing_days:<n>`.

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/lib/intel/forecast/service.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { forecastSum, runForecasts } from "./service";
import { FakeMetricsProvider } from "../provider/fake";
import { catalogItem, dailyPoints } from "../testing/fixtures";

const S = [10, -5, 0, 5, -10, 3, -3];
const catalog = [
  catalogItem("acme.revenue", "additive", ["location_id"]),
  catalogItem("acme.rate", "ratio", ["location_id"]),
];
const fake = () => new FakeMetricsProvider({
  catalog,
  points: {
    "acme.revenue": [
      ...dailyPoints("2026-02-01", 181, { location_id: "L1" }, (i) => (i === 100 ? {} : { value: 100 + i + S[i % 7] })),
      ...dailyPoints("2026-06-01", 61, { location_id: "L2" }, (i) => ({ value: 50 + S[i % 7] })),
    ],
  },
});
const cfg = [
  { metric: "acme.revenue", dims: ["location_id"], horizons_days: [7, 30], season_length: 7 },
  { metric: "acme.rate", dims: ["location_id"], horizons_days: [7], season_length: 7 },
  { metric: "acme.none", dims: [], horizons_days: [7], season_length: 7 },
];

describe("runForecasts", () => {
  test("forecasts additive metrics per group and skips the rest with a reason", async () => {
    const p = fake();
    const { results, skipped } = await runForecasts(p, cfg, new Map(catalog.map((c) => [c.key, c])), "2026-07-31");
    expect(results.map((r) => r.dims.location_id).sort()).toEqual(["L1", "L2"]);
    expect(skipped).toEqual([
      { metricKey: "acme.rate", reason: "not_additive" },
      { metricKey: "acme.none", reason: "metric_unknown" },
    ]);
    const l1 = results.find((r) => r.dims.location_id === "L1")!;
    expect(l1.startDate).toBe("2026-08-01");
    expect(l1.output.historyDays).toBe(181);
    expect(l1.output.warnings).toContain("filled_missing_days:1");
    expect(results.find((r) => r.dims.location_id === "L2")!.output.label).toBe("low_confidence");
  });

  test("daily history is fetched one group at a time", async () => {
    const p = fake();
    await runForecasts(p, cfg.slice(0, 1), new Map(catalog.map((c) => [c.key, c])), "2026-07-31");
    const daily = p.calls.filter((c) => (c.args as { grain?: string } | null)?.grain === "day");
    expect(daily.map((c) => (c.args as { dimsFilter: unknown }).dimsFilter)).toEqual([{ location_id: ["L1"] }, { location_id: ["L2"] }]);
  });

  test("forecastSum returns the damped or model sum for a horizon", async () => {
    const { results } = await runForecasts(fake(), cfg.slice(0, 1), new Map(catalog.map((c) => [c.key, c])), "2026-07-31");
    const damped = forecastSum(results, "acme.revenue", { location_id: "L1" }, 30, "damped")!;
    const model = forecastSum(results, "acme.revenue", { location_id: "L1" }, 30, "model")!;
    expect(damped.value).toBeGreaterThan(0);
    expect(model.value).toBeGreaterThan(0);
    expect(forecastSum(results, "acme.revenue", { location_id: "L9" }, 30, "damped")).toBeNull();
    expect(forecastSum(results, "acme.revenue", { location_id: "L1" }, 14, "damped")).toBeNull();
  });
});
```

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/forecast/service.test.ts
```
Expected: FAIL — `Cannot find module './service'`.

- [ ] **Step 3: Implement** — `LAAM/src/lib/intel/forecast/service.ts`

```ts
// Runs the pack's forecasts.yaml against the provider. Additive metrics only (spec §7.6);
// one daily-history call per group keeps each MCP response small.
import { dimsKey } from "../provider/aggregate";
import type { MetricCatalogItem, MetricsProvider } from "../provider/types";
import type { ForecastCfg } from "../pack/schema";
import { addDays, daysBetween } from "../time";
import { forecastSeries, type ForecastOutput } from "./forecast";

export interface ForecastResult {
  metricKey: string;
  dims: Record<string, string>;
  startDate: string;
  output: ForecastOutput;
}
export interface ForecastSkip {
  metricKey: string;
  reason: string;
}

const DEFAULT_HISTORY_DAYS = 400;

export async function runForecasts(
  provider: MetricsProvider,
  cfgs: readonly ForecastCfg[],
  catalog: ReadonlyMap<string, MetricCatalogItem>,
  asOf: string,
  opts: { historyDays?: number } = {},
): Promise<{ results: ForecastResult[]; skipped: ForecastSkip[] }> {
  const results: ForecastResult[] = [];
  const skipped: ForecastSkip[] = [];
  const from = addDays(asOf, -((opts.historyDays ?? DEFAULT_HISTORY_DAYS) - 1));
  const to = addDays(asOf, 1);

  for (const cfg of cfgs) {
    const item = catalog.get(cfg.metric);
    if (!item) { skipped.push({ metricKey: cfg.metric, reason: "metric_unknown" }); continue; }
    if (!item.enabled) { skipped.push({ metricKey: cfg.metric, reason: "metric_disabled" }); continue; }
    if (item.aggregation !== "additive") { skipped.push({ metricKey: cfg.metric, reason: "not_additive" }); continue; }
    const missing = cfg.dims.find((d) => !item.dims.includes(d));
    if (missing) { skipped.push({ metricKey: cfg.metric, reason: `dims_not_in_metric:${missing}` }); continue; }

    try {
      const totals = await provider.getMetrics({ metricKeys: [cfg.metric], from, to, grain: "total", groupBy: [...cfg.dims] });
      const groups = (totals.series.find((s) => s.metricKey === cfg.metric)?.points ?? []).map((p) => p.dims);
      for (const dims of groups) {
        const dimsFilter = Object.fromEntries(Object.entries(dims).map(([k, v]) => [k, [v]]));
        const res = await provider.getMetrics({ metricKeys: [cfg.metric], from, to, grain: "day", groupBy: [...cfg.dims], dimsFilter });
        const series = res.series.find((s) => s.metricKey === cfg.metric);
        const pts = [...(series?.points ?? [])].sort((a, b) => a.period.localeCompare(b.period));
        if (pts.length === 0) continue;
        const byDay = new Map(pts.map((p) => [p.period, p.value]));
        const start = pts[0].period;
        const len = daysBetween(start, to);
        let filled = 0;
        const y = Array.from({ length: len }, (_, i) => {
          const v = byDay.get(addDays(start, i));
          if (v == null) { filled++; return 0; }
          return v;
        });
        const output = forecastSeries(y, { horizons: cfg.horizons_days, seasonLength: cfg.season_length, versionsInSeries: series?.versionsInSeries ?? [] });
        if (filled > 0) output.warnings.push(`filled_missing_days:${filled}`);
        results.push({ metricKey: cfg.metric, dims, startDate: to, output });
      }
    } catch (e) {
      skipped.push({ metricKey: cfg.metric, reason: `provider_error: ${e instanceof Error ? e.message : String(e)}` });
    }
  }
  return { results, skipped };
}

export function forecastSum(
  results: readonly ForecastResult[],
  metricKey: string,
  dims: Readonly<Record<string, string>>,
  horizonDays: number,
  trend: "damped" | "model",
): { value: number; reliable: boolean; lower: number | null; upper: number | null } | null {
  const want = dimsKey(dims);
  const r = results.find((x) => x.metricKey === metricKey && dimsKey(x.dims) === want && x.output.status === "ok");
  const h = r?.output.horizons.find((x) => x.horizonDays === horizonDays);
  if (!h) return null;
  return { value: trend === "damped" ? h.dampedSum : h.sum.point, reliable: h.reliable, lower: h.sum.lower, upper: h.sum.upper };
}
```

Ghi chú khớp test: L1 có 181 ngày từ 2026-02-01 đến 2026-07-31, ngày thứ 100 thiếu ⇒ `historyDays` 181 và `filled_missing_days:1`; L2 có 61 ngày ⇒ `low_confidence`.

- [ ] **Step 4: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/forecast/service.test.ts
```
Expected: PASS 3/3.

- [ ] **Step 5: Commit**

```bash
git -C LAAM add src/lib/intel/forecast/service.ts src/lib/intel/forecast/service.test.ts
git -C LAAM commit -m "feat(intel): forecast service over pack forecasts with per-group history fetches"
```

---

### Task 15: Scenario engine (4 preset, liên kết finding → kịch bản)

**Files:**
- Create: `LAAM/src/lib/intel/scenario/engine.ts`, `LAAM/src/lib/intel/scenario/engine.test.ts`, `LAAM/src/lib/intel/scenario/browser-safe.test.ts`

**Interfaces:**
- Consumes: `ScenarioTemplate`, `PRESET_NAMES`, `PresetName` (Task 6); `evalNumber` (Task 2); `forecastSum`, `ForecastResult` (Task 14).
- Produces (Plan E dùng `computeScenario`/`computeCustom` để tính lại tức thì khi user chỉnh biến — không LLM):
```ts
export const DISCLAIMER = "decision support — not a guarantee";
export class ScenarioError extends Error {}
export interface ScenarioInput { base: Record<string, number>; persistBase?: Record<string, number> | null; driver?: { variable: string; value: number } | null; presetSets?: Record<PresetName, Record<string, number>> }
export interface PresetResult { preset: PresetName; trend: "damped" | "persist_driver"; assumptions: Record<string, number>; changed: string[]; outputs: Record<string, number>; primary: number; deltaVsBaseline: Record<string, number>; notes: string[] }
export interface ScenarioResult { key: string; label: string; horizonDays: number; base: Record<string, number>; persistBase: Record<string, number> | null; baseline: { assumptions: Record<string, number>; outputs: Record<string, number>; primary: number }; presets: PresetResult[]; driver: { variable: string; measured: number } | null; disclaimer: string }
export interface CustomResult { assumptions: Record<string, number>; outputs: Record<string, number>; primary: number; deltaVsBaseline: Record<string, number> }
export function computeScenario(tpl: ScenarioTemplate, input: ScenarioInput): ScenarioResult;
export function computeCustom(tpl: ScenarioTemplate, base: Record<string, number>, variables: Record<string, number>): CustomResult;
export function scenarioBaseFromForecasts(tpl: ScenarioTemplate, results: readonly ForecastResult[], dims: Readonly<Record<string, string>>): { base: Record<string, number>; persistBase: Record<string, number>; reliable: boolean; lower: Record<string, number> | null; upper: Record<string, number> | null } | null;
```

Định nghĩa 4 preset (spec §7.7, request Part 1 §9 / Part 3 §17):
- **base** = tổng dự báo **damped** trong `horizon_days` của từng metric `forecast_of`, theo dims của finding. **Baseline** = mọi biến ở `default` trên base damped. **expected** = base damped + `set` của preset (thường rỗng). **best/risk** = expected + `set`.
- **no_action** = **persistBase** = tổng dự báo của model **không damped** (`sum.point`) — mức và xu hướng hiện tại kéo dài nguyên vẹn — với biến ở `default` + `set` của preset. **Driver của finding KHÔNG được áp lại**: thay đổi đo được (giá vốn +8%, doanh số −35%…) đã nằm trong dữ liệu gần nhất mà model học, nên áp lại sẽ **tính hai lần** (review: RET-SALES-001 từng cho 14.145 thay vì 20.208). Driver chỉ được báo cáo (`driver.measured`, ghi chú `driver_embedded_in_base:<biến>`). Không có `persistBase` ⇒ no_action dùng base damped + ghi chú `no_persist_base`.
- Model không vượt baseline (forecast `reliable = false`) ⇒ cả hai base là cùng một chuỗi baseline ⇒ no_action = expected — đúng nghĩa "không có xu hướng tin cậy để tắt dần".
- `presetSets` cho phép `rule_override` thay `set` (Task 8 `resolvePresetSets`). Kết quả luôn kèm `assumptions`, `changed`, `deltaVsBaseline`, `disclaimer`.

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/lib/intel/scenario/engine.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { computeCustom, computeScenario, DISCLAIMER, ScenarioError, scenarioBaseFromForecasts } from "./engine";
import { scenarioSchema } from "../pack/schema";
import { forecastSeries } from "../forecast/forecast";
import type { ForecastResult } from "../forecast/service";

const tpl = scenarioSchema.parse({
  key: "acme.cost_change", label: "Cost change", dims: ["location_id"],
  base: { revenue: { forecast_of: "acme.revenue" }, cost: { forecast_of: "acme.cost" } },
  variables: { cost_change_pct: { default: 0, min: -30, max: 30 }, price_change_pct: { default: 0, min: -30, max: 30 } },
  outputs: { margin: "revenue * (1 + price_change_pct / 100) - cost * (1 + cost_change_pct / 100)" },
  primary_output: "margin",
  presets: {
    expected: { trend: "damped" },
    best: { trend: "damped", set: { price_change_pct: 3 } },
    risk: { trend: "damped", set: { cost_change_pct: 5 } },
    no_action: { trend: "persist_driver" },
  },
});
const base = { revenue: 10000, cost: 6000 }; // damped sums
const persistBase = { revenue: 10000, cost: 6600 }; // undamped: the higher cost level keeps going
const driver = { variable: "cost_change_pct", value: 10 };

describe("computeScenario", () => {
  test("four presets give four different results on an adverse change", () => {
    const r = computeScenario(tpl, { base, persistBase, driver });
    expect(r.presets.map((p) => p.preset)).toEqual(["expected", "best", "risk", "no_action"]);
    const primaries = r.presets.map((p) => p.primary);
    expect(new Set(primaries).size).toBe(4);
    primaries.forEach((v, i) => expect(v).toBeCloseTo([4000, 4300, 3700, 3400][i], 6));
  });

  // Why (review finding): the measured change is already in the data the forecast learned from.
  // Re-applying it (6600 x 1.10 => 2740) would count the problem twice.
  test("no_action persists the current level once and never re-applies the measured driver", () => {
    const r = computeScenario(tpl, { base, persistBase, driver });
    const na = r.presets.find((p) => p.preset === "no_action")!;
    expect(na.primary).toBeCloseTo(3400, 6);
    expect(na.assumptions).toEqual({ cost_change_pct: 0, price_change_pct: 0 });
    expect(na.notes).toEqual(expect.arrayContaining(["persisted_level", "driver_embedded_in_base:cost_change_pct"]));
    expect(r.driver).toEqual({ variable: "cost_change_pct", measured: 10 });
  });

  test("no_action is not better than expected for an adverse persisted trend", () => {
    const r = computeScenario(tpl, { base, persistBase, driver });
    const get = (n: string) => r.presets.find((p) => p.preset === n)!.primary;
    expect(get("no_action")).toBeLessThanOrEqual(get("expected"));
  });

  test("is deterministic", () => {
    expect(computeScenario(tpl, { base, persistBase, driver })).toEqual(computeScenario(tpl, { base, persistBase, driver }));
  });

  test("reports assumptions, changed variables, delta vs baseline and the disclaimer", () => {
    const r = computeScenario(tpl, { base, persistBase, driver });
    const risk = r.presets.find((p) => p.preset === "risk")!;
    expect(risk.assumptions).toEqual({ cost_change_pct: 5, price_change_pct: 0 });
    expect(risk.changed).toEqual(["cost_change_pct"]);
    expect(risk.deltaVsBaseline.margin).toBeCloseTo(-300, 6);
    expect(r.baseline.primary).toBeCloseTo(4000, 6);
    expect(r.disclaimer).toBe(DISCLAIMER);
  });

  test("without a persisted base no_action equals expected and says so", () => {
    const na = computeScenario(tpl, { base }).presets.find((p) => p.preset === "no_action")!;
    expect(na.primary).toBeCloseTo(4000, 6);
    expect(na.notes).toContain("no_persist_base");
  });

  test("preset overrides replace a preset's settings", () => {
    const r = computeScenario(tpl, { base, presetSets: { expected: {}, best: { price_change_pct: 10 }, risk: { cost_change_pct: 5 }, no_action: {} } });
    expect(r.presets.find((p) => p.preset === "best")!.primary).toBeCloseTo(5000, 6);
  });

  test("missing base values and unknown drivers are errors", () => {
    expect(() => computeScenario(tpl, { base: { revenue: 1 } })).toThrow(ScenarioError);
    expect(() => computeScenario(tpl, { base, persistBase: { revenue: 1 } })).toThrow(ScenarioError);
    expect(() => computeScenario(tpl, { base, driver: { variable: "nope", value: 1 } })).toThrow(ScenarioError);
  });
});

describe("finding -> scenario on a level step (no double count)", () => {
  // A cost level step (+8% for the last 14 days) is what a finding driver measures. The
  // persisted path must carry the new level once: no_action = revenue - cost, never cost x 1.08.
  test("no_action ~ persistence of the new level; expected = damped forecast", () => {
    const cost = Array.from({ length: 154 }, (_, t) => (t < 140 ? 100 : 108));
    const revenue = Array.from({ length: 154 }, () => 150);
    const res = (metricKey: string, y: number[]): ForecastResult => ({
      metricKey, dims: { location_id: "L1" }, startDate: "2026-08-01",
      output: forecastSeries(y, { horizons: [30], seasonLength: 7, versionsInSeries: [1] }),
    });
    const b = scenarioBaseFromForecasts(tpl, [res("acme.revenue", revenue), res("acme.cost", cost)], { location_id: "L1" })!;
    expect(Math.abs(b.persistBase.cost - 108 * 30) / (108 * 30)).toBeLessThan(0.05); // the new level, once
    const r = computeScenario(tpl, { base: b.base, persistBase: b.persistBase, driver: { variable: "cost_change_pct", value: 8 } });
    const na = r.presets.find((p) => p.preset === "no_action")!;
    expect(na.primary).toBeCloseTo(b.persistBase.revenue - b.persistBase.cost, 6);
    expect(Math.abs(na.primary - (b.persistBase.revenue - b.persistBase.cost * 1.08))).toBeGreaterThan(200);
    expect(r.presets.find((p) => p.preset === "expected")!.primary).toBeCloseTo(b.base.revenue - b.base.cost, 6);
  });
});

describe("computeCustom", () => {
  test("recomputes outputs for user-chosen variables", () => {
    const r = computeCustom(tpl, base, { cost_change_pct: 10 });
    expect(r.assumptions).toEqual({ cost_change_pct: 10, price_change_pct: 0 });
    expect(r.outputs.margin).toBeCloseTo(3400, 6);
    expect(r.primary).toBeCloseTo(3400, 6);
    expect(r.deltaVsBaseline.margin).toBeCloseTo(-600, 6);
  });
  test("rejects unknown variables and values outside the bounds", () => {
    expect(() => computeCustom(tpl, base, { nope: 1 })).toThrow(/unknown variable/);
    expect(() => computeCustom(tpl, base, { cost_change_pct: 31 })).toThrow(/between -30 and 30/);
  });
});

describe("scenarioBaseFromForecasts", () => {
  const fr = (metricKey: string, dampedSum: number, reliable = true, interval = true): ForecastResult => ({
    metricKey, dims: { location_id: "L1" }, startDate: "2026-08-01",
    output: { status: "ok", label: "normal", historyDays: 200, modelVersion: "v", warnings: [], horizons: [{
      horizonDays: 30, model: "holt_winters", reliable, interval, point: [], lower: [], upper: [],
      sum: { point: dampedSum + 1, lower: interval ? dampedSum - 10 : null, upper: interval ? dampedSum + 10 : null },
      dampedPoint: [], dampedSum, backtest: null,
    }] },
  });
  test("damped sums for expected, model sums for the persisted path, for the finding's dims", () => {
    const out = scenarioBaseFromForecasts(tpl, [fr("acme.revenue", 9000), fr("acme.cost", 5000, false)], { location_id: "L1", employee_id: "E1" });
    expect(out).toEqual({
      base: { revenue: 9000, cost: 5000 }, persistBase: { revenue: 9001, cost: 5001 }, reliable: false,
      lower: { revenue: 8990, cost: 4990 }, upper: { revenue: 9010, cost: 5010 },
    });
  });
  test("no interval when any base forecast lacks one", () => {
    const out = scenarioBaseFromForecasts(tpl, [fr("acme.revenue", 9000), fr("acme.cost", 5000, true, false)], { location_id: "L1" })!;
    expect(out.lower).toBeNull();
    expect(out.upper).toBeNull();
  });
  test("returns null when a base metric has no forecast", () => {
    expect(scenarioBaseFromForecasts(tpl, [fr("acme.revenue", 9000)], { location_id: "L1" })).toBeNull();
  });
});
```

- [ ] **Step 1b: Viết test "browser-safe" thất bại** — `LAAM/src/lib/intel/scenario/browser-safe.test.ts`

```ts
import { existsSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";

// Why: Plan E imports computeCustom in a client component. One transitive import of the DB,
// drizzle, a Node built-in or server-only would break the client bundle (or leak server code).
// Walks the import graph from engine.ts statically, including type-only imports.
const SRC = path.resolve(process.cwd(), "src");
const ENTRY = path.join(SRC, "lib/intel/scenario/engine.ts");
const ALLOWED_PACKAGES = new Set(["zod"]);
const FORBIDDEN_ALIASES = /^@\/(db|auth|lib\/connectors)(\/|$)/;
const SPEC_RE = /(?:import|export)\s[^"']*?from\s*["']([^"']+)["']|import\s*\(\s*["']([^"']+)["']\s*\)|import\s+["']([^"']+)["']/g;

function resolveLocal(from: string, spec: string): string | null {
  const base = spec.startsWith("@/") ? path.join(SRC, spec.slice(2)) : path.resolve(path.dirname(from), spec);
  for (const cand of [base, base + ".ts", base + ".tsx", path.join(base, "index.ts")]) {
    if (existsSync(cand) && statSync(cand).isFile()) return cand;
  }
  return null;
}

function walk(): { visited: string[]; violations: string[] } {
  const visited = new Set<string>();
  const violations: string[] = [];
  const stack = [ENTRY];
  while (stack.length) {
    const file = stack.pop() as string;
    if (visited.has(file)) continue;
    visited.add(file);
    const src = readFileSync(file, "utf8");
    for (const m of src.matchAll(SPEC_RE)) {
      const spec = (m[1] ?? m[2] ?? m[3]) as string;
      const rel = path.relative(SRC, file);
      if (spec.startsWith(".") || spec.startsWith("@/")) {
        if (FORBIDDEN_ALIASES.test(spec)) { violations.push(`${rel} -> ${spec}`); continue; }
        const next = resolveLocal(file, spec);
        if (!next) { violations.push(`${rel} -> ${spec} (unresolved)`); continue; }
        stack.push(next);
      } else if (!ALLOWED_PACKAGES.has(spec)) {
        violations.push(`${rel} -> ${spec}`); // node:*, fs, drizzle-orm, server-only, next/server, ...
      }
    }
  }
  return { visited: [...visited].map((f) => path.relative(SRC, f)).sort(), violations };
}

describe("scenario engine is browser-safe", () => {
  test("no transitive import of the DB, server-only code or Node built-ins", () => {
    const { visited, violations } = walk();
    expect(violations).toEqual([]);
    expect(visited).toContain("lib/intel/scenario/engine.ts");
    expect(visited).toContain("lib/intel/expr.ts"); // sanity: the walker followed the graph
  });
});
```
Expected khi chạy ở Step 2: FAIL (`ENOENT … engine.ts` — chưa có file). Đồ thị import dự kiến sau Step 3: `engine.ts → expr.ts, forecast/service.ts, pack/schema.ts (zod) → provider/aggregate.ts, provider/types.ts, time.ts → workflow/cron.ts (không import gì), forecast/forecast.ts → forecast/holt-winters.ts` — đều thuần. **Không** được thêm `import` DB/connector vào các file này về sau; cần dữ liệu server thì truyền vào qua tham số.

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/scenario/engine.test.ts src/lib/intel/scenario/browser-safe.test.ts
```
Expected: FAIL — module chưa tồn tại (cả hai file).

- [ ] **Step 3: Implement** — `LAAM/src/lib/intel/scenario/engine.ts`

```ts
// Deterministic what-if engine (spec §7.7). Outputs are pack expressions evaluated by the safe
// evaluator over forecast bases + variables; the UI recomputes instantly without an LLM.
// BROWSER-SAFE: imported by a client component (Plan E) — no DB, server-only or Node imports here
// or in anything this file imports (pinned by browser-safe.test.ts).
import { evalNumber, ExprError } from "../expr";
import { forecastSum, type ForecastResult } from "../forecast/service";
import { PRESET_NAMES, type PresetName, type ScenarioTemplate } from "../pack/schema";

export const DISCLAIMER = "decision support — not a guarantee";

export class ScenarioError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ScenarioError";
  }
}

export interface ScenarioInput {
  /** Damped forecast sums over the horizon (expected / best / risk). */
  base: Record<string, number>;
  /** Undamped model sums: the current level and trend continue unchanged (no_action). */
  persistBase?: Record<string, number> | null;
  /** The finding's measured change. Informational only: it is already embedded in the data the
   * forecasts learned from, so it is never re-applied (that would count it twice). */
  driver?: { variable: string; value: number } | null;
  presetSets?: Record<PresetName, Record<string, number>>;
}
export interface PresetResult {
  preset: PresetName;
  trend: "damped" | "persist_driver";
  assumptions: Record<string, number>;
  changed: string[];
  outputs: Record<string, number>;
  primary: number;
  deltaVsBaseline: Record<string, number>;
  notes: string[];
}
export interface ScenarioResult {
  key: string;
  label: string;
  horizonDays: number;
  base: Record<string, number>;
  persistBase: Record<string, number> | null;
  baseline: { assumptions: Record<string, number>; outputs: Record<string, number>; primary: number };
  presets: PresetResult[];
  driver: { variable: string; measured: number } | null;
  disclaimer: string;
}
export interface CustomResult {
  assumptions: Record<string, number>;
  outputs: Record<string, number>;
  primary: number;
  deltaVsBaseline: Record<string, number>;
}

function requireBase(tpl: ScenarioTemplate, base: Record<string, number>, what: string): void {
  for (const name of Object.keys(tpl.base)) {
    if (typeof base[name] !== "number" || !Number.isFinite(base[name])) throw new ScenarioError(`${tpl.key}: missing ${what} value "${name}"`);
  }
}

function defaults(tpl: ScenarioTemplate): Record<string, number> {
  return Object.fromEntries(Object.entries(tpl.variables).map(([k, v]) => [k, v.default]));
}

function clamp(tpl: ScenarioTemplate, name: string, value: number): { value: number; clamped: boolean } {
  const v = tpl.variables[name];
  const c = Math.min(v.max, Math.max(v.min, value));
  return { value: c, clamped: c !== value };
}

function outputsFor(tpl: ScenarioTemplate, base: Record<string, number>, assumptions: Record<string, number>): Record<string, number> {
  const vars = { ...base, ...assumptions };
  const out: Record<string, number> = {};
  for (const [name, expr] of Object.entries(tpl.outputs)) {
    try {
      out[name] = evalNumber(expr, vars);
    } catch (e) {
      if (e instanceof ExprError) throw new ScenarioError(`${tpl.key} output ${name}: ${e.message}`);
      throw e;
    }
  }
  return out;
}

function delta(a: Record<string, number>, b: Record<string, number>): Record<string, number> {
  return Object.fromEntries(Object.keys(a).map((k) => [k, a[k] - b[k]]));
}

export function computeScenario(tpl: ScenarioTemplate, input: ScenarioInput): ScenarioResult {
  requireBase(tpl, input.base, "base");
  if (input.persistBase) requireBase(tpl, input.persistBase, "persisted base");
  if (input.driver && !(input.driver.variable in tpl.variables)) {
    throw new ScenarioError(`${tpl.key}: driver variable "${input.driver.variable}" is unknown`);
  }
  const defs = defaults(tpl);
  const baselineOutputs = outputsFor(tpl, input.base, defs);

  const presets = PRESET_NAMES.map((name): PresetResult => {
    const preset = tpl.presets[name];
    const set = input.presetSets?.[name] ?? preset.set;
    const notes: string[] = [];
    const assumptions = { ...defs };
    for (const [k, v] of Object.entries(set)) {
      if (!(k in tpl.variables)) throw new ScenarioError(`${tpl.key}: preset ${name} sets unknown variable "${k}"`);
      const c = clamp(tpl, k, v);
      assumptions[k] = c.value;
      if (c.clamped) notes.push(`clamped:${k}`);
    }
    let base = input.base;
    if (preset.trend === "persist_driver") {
      if (input.persistBase) {
        base = input.persistBase;
        notes.push("persisted_level");
      } else {
        notes.push("no_persist_base");
      }
      if (input.driver) notes.push(`driver_embedded_in_base:${input.driver.variable}`);
    }
    const outputs = outputsFor(tpl, base, assumptions);
    return {
      preset: name,
      trend: preset.trend,
      assumptions,
      changed: Object.keys(assumptions).filter((k) => assumptions[k] !== defs[k]),
      outputs,
      primary: outputs[tpl.primary_output],
      deltaVsBaseline: delta(outputs, baselineOutputs),
      notes,
    };
  });

  return {
    key: tpl.key,
    label: tpl.label,
    horizonDays: tpl.horizon_days,
    base: { ...input.base },
    persistBase: input.persistBase ? { ...input.persistBase } : null,
    baseline: { assumptions: defs, outputs: baselineOutputs, primary: baselineOutputs[tpl.primary_output] },
    presets,
    driver: input.driver ? { variable: input.driver.variable, measured: input.driver.value } : null,
    disclaimer: DISCLAIMER,
  };
}

export function computeCustom(tpl: ScenarioTemplate, base: Record<string, number>, variables: Record<string, number>): CustomResult {
  requireBase(tpl, base, "base");
  const defs = defaults(tpl);
  const assumptions = { ...defs };
  for (const [k, v] of Object.entries(variables)) {
    const spec = tpl.variables[k];
    if (!spec) throw new ScenarioError(`${tpl.key}: unknown variable "${k}"`);
    if (!Number.isFinite(v) || v < spec.min || v > spec.max) {
      throw new ScenarioError(`${tpl.key}: "${k}" must be between ${spec.min} and ${spec.max}`);
    }
    assumptions[k] = v;
  }
  const outputs = outputsFor(tpl, base, assumptions);
  const baseline = outputsFor(tpl, base, defs);
  return { assumptions, outputs, primary: outputs[tpl.primary_output], deltaVsBaseline: delta(outputs, baseline) };
}

export function scenarioBaseFromForecasts(
  tpl: ScenarioTemplate,
  results: readonly ForecastResult[],
  dims: Readonly<Record<string, string>>,
): { base: Record<string, number>; persistBase: Record<string, number>; reliable: boolean; lower: Record<string, number> | null; upper: Record<string, number> | null } | null {
  const scoped = Object.fromEntries(tpl.dims.filter((d) => dims[d] !== undefined).map((d) => [d, dims[d]]));
  const base: Record<string, number> = {};
  const persistBase: Record<string, number> = {};
  const lower: Record<string, number> = {};
  const upper: Record<string, number> = {};
  let reliable = true;
  let hasInterval = true;
  for (const [name, spec] of Object.entries(tpl.base)) {
    const damped = forecastSum(results, spec.forecast_of, scoped, tpl.horizon_days, "damped");
    const model = forecastSum(results, spec.forecast_of, scoped, tpl.horizon_days, "model");
    if (!damped || !model) return null;
    base[name] = damped.value;
    persistBase[name] = model.value;
    reliable = reliable && damped.reliable;
    if (damped.lower === null || damped.upper === null) hasInterval = false;
    else {
      lower[name] = damped.lower;
      upper[name] = damped.upper;
    }
  }
  return { base, persistBase, reliable, lower: hasInterval ? lower : null, upper: hasInterval ? upper : null };
}
```

Ghi chú khớp test: expected = 10000 − 6000 = 4000; best = 10300 − 6000 = 4300; risk = 10000 − 6300 = 3700; no_action = 10000 − 6600 (persistBase, driver không áp lại) = 3400; `computeCustom` cost +10 ⇒ 3400 (so sánh `toBeCloseTo` vì 6000 × 1.1 trong số thực ≠ 6600 tuyệt đối). Chuỗi bậc thang: backtest các gốc đều không vượt baseline (hoà) ⇒ model = seasonal-naive ⇒ persistBase.cost = 7 ngày cuối (108) lặp lại = 3240.

- [ ] **Step 4: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/scenario/engine.test.ts src/lib/intel/scenario/browser-safe.test.ts
```
Expected: PASS 14/14 + 1/1. Nếu browser-safe fail: bỏ import vi phạm (không nới danh sách cho phép).

- [ ] **Step 5: Commit**

```bash
git -C LAAM add src/lib/intel/scenario
git -C LAAM commit -m "feat(intel): deterministic scenario engine with four presets and finding drivers"
```

---

### Task 16: Tầng lưu trữ (`IntelRepo`: Drizzle + in-memory)

**Files:**
- Create: `LAAM/src/lib/intel/store/repo.ts`, `LAAM/src/lib/intel/testing/memory-repo.ts`, `LAAM/src/lib/intel/testing/memory-repo.test.ts`

**Interfaces:**
- Consumes: bảng Task 1; `ExistingFinding`, `FindingDecision` (Task 11); `OverrideRow` (Task 8); `TASK_CLOSED_STATUSES` (Task 1).
- Produces:
```ts
export type FindingValues = Omit<NewFinding, "id" | "projectId" | "dedupeKey" | "status" | "statusChangedAt" | "dismissReason" | "occurrences" | "firstSeenAt" | "lastSeenAt" | "lastSurfacedAt" | "surfaceReason" | "lastRunId" | "createdAt" | "updatedAt">;
export interface FindingWrite { dedupeKey: string; decision: FindingDecision; values: FindingValues; scenario: { templateKey: string; assumptions: unknown; result: unknown; baseline: unknown } | null }
export interface ForecastWrite { metricKey: string; dims: Record<string, string>; horizonDays: number; startDate: string; status: string; label: string | null; model: string | null; modelVersion: string; baselineModel: string | null; reliable: boolean; historyDays: number; point: number[]; lower: number[]; upper: number[]; sum: unknown; backtest: unknown; warnings: string[] }
export interface PersistInput { projectId: string; runId: string; now: Date; findings: FindingWrite[]; forecasts: ForecastWrite[] }
export interface PersistSummary { inserted: number; updated: number; surfaced: number; reopened: number; scenarios: number; forecasts: number }
export interface IntelRepo {
  loadOverrides(projectId: string): Promise<OverrideRow[]>;
  loadExisting(projectId: string, dedupeKeys: readonly string[]): Promise<Map<string, ExistingFinding>>;
  overdueFindingIds(projectId: string, now: Date): Promise<Set<string>>;
  previousHealthScores(projectId: string, excludeRunId: string): Promise<Record<string, number>>;
  persist(input: PersistInput): Promise<PersistSummary>;
}
export function drizzleRepo(db: typeof Db): IntelRepo;
// testing/memory-repo.ts
export class MemoryRepo implements IntelRepo { findings: Map<string, StoredFinding>; events; forecasts; scenarios; overrides; tasks; runs }
```

Quy tắc ghi (một transaction mỗi run): finding `INSERT … ON CONFLICT (projectId, dedupeKey) DO UPDATE` — nên hai run chạy song song (manual + lịch, `jobId` NULL không được unique slot bảo vệ) **không** tạo trùng; `occurrences = occurrences + 1` tính trong SQL. Cập nhật luôn ghi giá trị mới + `lastSeenAt`/`lastRunId`; chỉ khi `surface` mới ghi `lastSurfacedAt`/`surfaceReason`; `reopen` đặt lại `status = 'new'`, `statusChangedAt`, xoá `dismissReason`. Mỗi finding ghi một `finding_event` (`created` | `updated` | `resurfaced` | `reopened`, actor `system`). Scenario của finding ghi `scenario_run` (createdBy `system`). Forecast ghi `forecast_run` (lịch sử, không ghi đè).

`MemoryRepo` là bản tham chiếu cùng ngữ nghĩa cho test pipeline (Task 17) — không có test DB thật trong repo này (xem Open questions). Tầng Drizzle được kiểm bằng typecheck + chạy thật ở Task 23 Step 1–2.

- [ ] **Step 1: Viết test thất bại cho MemoryRepo** — `LAAM/src/lib/intel/testing/memory-repo.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { MemoryRepo } from "./memory-repo";
import type { FindingWrite } from "../store/repo";

const now = new Date("2026-08-01T12:00:00Z");
const write = (over: Partial<FindingWrite> = {}): FindingWrite => ({
  dedupeKey: "R-1:abc",
  decision: { action: "insert", surface: true, reason: "new", reopen: false, occurrences: 1 },
  values: {
    ruleId: "R-1", ruleVersion: 1, packVersion: "p@1", metricKey: "acme.revenue", dims: { location_id: "L1" }, locationIds: ["L1"],
    currentValue: 1, expectedValue: 2, variance: -1, variancePct: -50, comparison: {}, estimatedImpact: 1, impactUnit: "currency",
    severity: "high", severityReason: "x", confidence: 0.5, confidenceReason: {}, priorityScore: 10, priorityComponents: {},
    contributingFactors: [], recommendedAction: "investigate", defaultOwnerRole: "m", wording: "w", evidenceRefs: {},
    dataStatusSnapshot: [], briefEligible: true, sampleSize: 10,
  },
  scenario: null,
  ...over,
});

describe("MemoryRepo", () => {
  test("insert then quiet update keeps one finding and bumps occurrences", async () => {
    const repo = new MemoryRepo();
    await repo.persist({ projectId: "bp", runId: "r1", now, findings: [write()], forecasts: [] });
    const s = await repo.persist({ projectId: "bp", runId: "r2", now, findings: [write({ decision: { action: "update", surface: false, reason: null, reopen: false, occurrences: 2 } })], forecasts: [] });
    expect(s).toMatchObject({ inserted: 0, updated: 1, surfaced: 0 });
    expect(repo.findings.size).toBe(1);
    const f = [...repo.findings.values()][0];
    expect(f.occurrences).toBe(2);
    expect(f.lastRunId).toBe("r2");
    expect(f.lastSurfacedAt).toEqual(now); // from the insert, not changed by the quiet update
    expect(repo.events.map((e) => e.type)).toEqual(["created", "updated"]);
  });

  test("reopen resets status and records the reason", async () => {
    const repo = new MemoryRepo();
    await repo.persist({ projectId: "bp", runId: "r1", now, findings: [write()], forecasts: [] });
    [...repo.findings.values()][0].status = "resolved";
    await repo.persist({ projectId: "bp", runId: "r2", now, findings: [write({ decision: { action: "update", surface: true, reason: "recurred", reopen: true, occurrences: 2 } })], forecasts: [] });
    const f = [...repo.findings.values()][0];
    expect(f.status).toBe("new");
    expect(f.surfaceReason).toBe("recurred");
    expect(repo.events.at(-1)?.type).toBe("reopened");
  });

  test("overdue tasks and previous health scores", async () => {
    const repo = new MemoryRepo();
    repo.tasks.push({ projectId: "bp", findingId: "f1", dueAt: new Date("2026-07-30"), status: "open" }, { projectId: "bp", findingId: "f2", dueAt: new Date("2026-07-30"), status: "completed" });
    expect([...(await repo.overdueFindingIds("bp", now))]).toEqual(["f1"]);
    repo.runs.push({ id: "r0", projectId: "bp", status: "succeeded", finishedAt: new Date("2026-07-31"), healthScores: [{ locationId: "L1", score: 80 }] });
    expect(await repo.previousHealthScores("bp", "r1")).toEqual({ L1: 80 });
  });
});
```

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/testing/memory-repo.test.ts
```
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 3: Implement** — `LAAM/src/lib/intel/store/repo.ts`

```ts
// Thin persistence layer for the analysis pipeline. All decisions (insert/update/surface/reopen)
// are made by pure engine code; this module only writes them, in one transaction per run.
import { and, desc, eq, inArray, isNotNull, lt, ne, notInArray, sql } from "drizzle-orm";
import type { db as Db } from "@/db";
import {
  analysisRuns, findingEvents, findings, forecastRuns, ruleOverrides, scenarioRuns, tasks,
  type FindingStatus, type NewFinding,
} from "@/db/schema";
import { TASK_CLOSED_STATUSES } from "../task-status";
import type { ExistingFinding, FindingDecision } from "../engine/dedupe";
import type { OverrideRow } from "../overrides";
import type { Severity } from "../pack/schema";

export type FindingValues = Omit<
  NewFinding,
  | "id" | "projectId" | "dedupeKey" | "status" | "statusChangedAt" | "dismissReason" | "occurrences" | "firstSeenAt"
  | "lastSeenAt" | "lastSurfacedAt" | "surfaceReason" | "lastRunId" | "createdAt" | "updatedAt"
>;

export interface FindingWrite {
  dedupeKey: string;
  decision: FindingDecision;
  values: FindingValues;
  scenario: { templateKey: string; assumptions: unknown; result: unknown; baseline: unknown } | null;
}

export interface ForecastWrite {
  metricKey: string;
  dims: Record<string, string>;
  horizonDays: number;
  startDate: string;
  status: string;
  label: string | null;
  model: string | null;
  modelVersion: string;
  baselineModel: string | null;
  reliable: boolean;
  historyDays: number;
  point: number[];
  lower: number[];
  upper: number[];
  sum: unknown;
  backtest: unknown;
  warnings: string[];
}

export interface PersistInput {
  projectId: string;
  runId: string;
  now: Date;
  findings: FindingWrite[];
  forecasts: ForecastWrite[];
}

export interface PersistSummary {
  inserted: number;
  updated: number;
  surfaced: number;
  reopened: number;
  scenarios: number;
  forecasts: number;
}

export interface IntelRepo {
  loadOverrides(projectId: string): Promise<OverrideRow[]>;
  loadExisting(projectId: string, dedupeKeys: readonly string[]): Promise<Map<string, ExistingFinding>>;
  overdueFindingIds(projectId: string, now: Date): Promise<Set<string>>;
  previousHealthScores(projectId: string, excludeRunId: string): Promise<Record<string, number>>;
  persist(input: PersistInput): Promise<PersistSummary>;
}

/** Window length (days) stored in finding.comparison.window by the pipeline; null when absent. */
export function windowDaysOf(comparison: unknown): number | null {
  const w = (comparison as { window?: { from?: unknown; to?: unknown } } | null)?.window;
  if (!w || typeof w.from !== "string" || typeof w.to !== "string") return null;
  const days = Math.round((Date.parse(w.to + "T00:00:00Z") - Date.parse(w.from + "T00:00:00Z")) / 86_400_000);
  return Number.isFinite(days) && days > 0 ? days : null;
}

export function eventTypeOf(d: FindingDecision): "created" | "updated" | "resurfaced" | "reopened" {
  if (d.action === "insert") return "created";
  if (d.reopen) return "reopened";
  return d.surface ? "resurfaced" : "updated";
}

export function drizzleRepo(db: typeof Db): IntelRepo {
  return {
    async loadOverrides(projectId) {
      const rows = await db
        .select({ targetKey: ruleOverrides.targetKey, scope: ruleOverrides.scope, value: ruleOverrides.value })
        .from(ruleOverrides)
        .where(eq(ruleOverrides.projectId, projectId));
      return rows;
    },

    async loadExisting(projectId, dedupeKeys) {
      const out = new Map<string, ExistingFinding>();
      if (dedupeKeys.length === 0) return out;
      const rows = await db
        .select()
        .from(findings)
        .where(and(eq(findings.projectId, projectId), inArray(findings.dedupeKey, [...dedupeKeys])));
      for (const r of rows) {
        out.set(r.dedupeKey, {
          id: r.id,
          status: r.status,
          severity: r.severity as Severity,
          estimatedImpact: r.estimatedImpact,
          sampleSize: r.sampleSize,
          occurrences: r.occurrences,
          statusChangedAt: r.statusChangedAt,
          lastSurfacedAt: r.lastSurfacedAt,
          windowDays: windowDaysOf(r.comparison),
        });
      }
      return out;
    },

    async overdueFindingIds(projectId, now) {
      const rows = await db
        .select({ findingId: tasks.findingId })
        .from(tasks)
        .where(and(
          eq(tasks.projectId, projectId),
          isNotNull(tasks.findingId),
          lt(tasks.dueAt, now),
          notInArray(tasks.status, [...TASK_CLOSED_STATUSES]),
        ));
      return new Set(rows.map((r) => r.findingId as string));
    },

    async previousHealthScores(projectId, excludeRunId) {
      const rows = await db
        .select({ summary: analysisRuns.summary })
        .from(analysisRuns)
        .where(and(eq(analysisRuns.businessProjectId, projectId), eq(analysisRuns.status, "succeeded"), ne(analysisRuns.id, excludeRunId)))
        .orderBy(desc(analysisRuns.finishedAt))
        .limit(1);
      const scores = (rows[0]?.summary as { healthScores?: { locationId: string; score: number }[] } | null)?.healthScores ?? [];
      return Object.fromEntries(scores.map((s) => [s.locationId, s.score]));
    },

    async persist(input) {
      const summary: PersistSummary = { inserted: 0, updated: 0, surfaced: 0, reopened: 0, scenarios: 0, forecasts: 0 };
      const { now, runId, projectId } = input;
      await db.transaction(async (tx) => {
        for (const w of input.findings) {
          const common = { ...w.values, lastSeenAt: now, lastRunId: runId, updatedAt: now };
          const surface = w.decision.surface ? { lastSurfacedAt: now, surfaceReason: w.decision.reason } : {};
          const reopen = w.decision.reopen ? { status: "new" as FindingStatus, statusChangedAt: now, dismissReason: null } : {};
          const [row] = await tx
            .insert(findings)
            .values({
              ...common,
              projectId,
              dedupeKey: w.dedupeKey,
              status: "new",
              statusChangedAt: now,
              occurrences: 1,
              firstSeenAt: now,
              lastSurfacedAt: now,
              surfaceReason: "new",
            })
            .onConflictDoUpdate({
              target: [findings.projectId, findings.dedupeKey],
              set: { ...common, ...surface, ...reopen, occurrences: sql`${findings.occurrences} + 1` },
            })
            .returning({ id: findings.id });
          await tx.insert(findingEvents).values({
            findingId: row.id,
            type: eventTypeOf(w.decision),
            payload: { runId, reason: w.decision.reason, severity: w.values.severity, impact: w.values.estimatedImpact ?? null },
            actor: "system",
            at: now,
          });
          if (w.scenario) {
            await tx.insert(scenarioRuns).values({ projectId, findingId: row.id, ...w.scenario, computedAt: now, createdBy: "system" });
            summary.scenarios++;
          }
          if (w.decision.action === "insert") summary.inserted++;
          else summary.updated++;
          if (w.decision.surface) summary.surfaced++;
          if (w.decision.reopen) summary.reopened++;
        }
        if (input.forecasts.length > 0) {
          await tx.insert(forecastRuns).values(input.forecasts.map((f) => ({ ...f, projectId, runId, computedAt: now })));
          summary.forecasts = input.forecasts.length;
        }
      });
      return summary;
    },
  };
}
```

- [ ] **Step 4: Implement** — `LAAM/src/lib/intel/testing/memory-repo.ts`

```ts
// In-memory IntelRepo with the same semantics as drizzleRepo (unique (project, dedupeKey),
// occurrences + 1 on conflict, surface/reopen fields). Used by pipeline tests and the offline
// demo run; it is NOT a production store.
import type { ExistingFinding } from "../engine/dedupe";
import type { OverrideRow } from "../overrides";
import type { Severity } from "../pack/schema";
import { TASK_CLOSED_STATUSES } from "../task-status";
import { eventTypeOf, windowDaysOf, type FindingValues, type ForecastWrite, type IntelRepo, type PersistInput, type PersistSummary } from "../store/repo";
import type { FindingStatus } from "@/db/schema";

export interface StoredFinding extends FindingValues {
  id: string;
  projectId: string;
  dedupeKey: string;
  status: FindingStatus;
  statusChangedAt: Date;
  dismissReason: string | null;
  occurrences: number;
  firstSeenAt: Date;
  lastSeenAt: Date;
  lastSurfacedAt: Date | null;
  surfaceReason: string | null;
  lastRunId: string;
}

export class MemoryRepo implements IntelRepo {
  readonly findings = new Map<string, StoredFinding>(); // key: projectId|dedupeKey
  readonly events: { findingId: string; type: string; payload: unknown }[] = [];
  readonly forecasts: (ForecastWrite & { projectId: string; runId: string })[] = [];
  readonly scenarios: { projectId: string; findingId: string; templateKey: string; result: unknown }[] = [];
  readonly overrides: (OverrideRow & { projectId?: string })[] = [];
  readonly tasks: { projectId: string; findingId: string; dueAt: Date; status: string }[] = [];
  readonly runs: { id: string; projectId: string; status: string; finishedAt: Date; healthScores: { locationId: string; score: number }[] }[] = [];
  private seq = 0;

  async loadOverrides(projectId: string): Promise<OverrideRow[]> {
    return this.overrides.filter((o) => !o.projectId || o.projectId === projectId);
  }

  async loadExisting(projectId: string, dedupeKeys: readonly string[]): Promise<Map<string, ExistingFinding>> {
    const out = new Map<string, ExistingFinding>();
    for (const key of dedupeKeys) {
      const f = this.findings.get(`${projectId}|${key}`);
      if (f) {
        out.set(key, {
          id: f.id, status: f.status, severity: f.severity as Severity, estimatedImpact: f.estimatedImpact ?? null,
          sampleSize: f.sampleSize ?? 0, occurrences: f.occurrences, statusChangedAt: f.statusChangedAt, lastSurfacedAt: f.lastSurfacedAt,
          windowDays: windowDaysOf(f.comparison),
        });
      }
    }
    return out;
  }

  async overdueFindingIds(projectId: string, now: Date): Promise<Set<string>> {
    const closed: readonly string[] = TASK_CLOSED_STATUSES;
    return new Set(this.tasks.filter((t) => t.projectId === projectId && t.dueAt < now && !closed.includes(t.status)).map((t) => t.findingId));
  }

  async previousHealthScores(projectId: string, excludeRunId: string): Promise<Record<string, number>> {
    const prev = this.runs
      .filter((r) => r.projectId === projectId && r.status === "succeeded" && r.id !== excludeRunId)
      .sort((a, b) => b.finishedAt.getTime() - a.finishedAt.getTime())[0];
    return Object.fromEntries((prev?.healthScores ?? []).map((s) => [s.locationId, s.score]));
  }

  async persist(input: PersistInput): Promise<PersistSummary> {
    const summary: PersistSummary = { inserted: 0, updated: 0, surfaced: 0, reopened: 0, scenarios: 0, forecasts: 0 };
    const { now, runId, projectId } = input;
    for (const w of input.findings) {
      const k = `${projectId}|${w.dedupeKey}`;
      const cur = this.findings.get(k);
      let stored: StoredFinding;
      if (!cur) {
        stored = {
          ...w.values, id: `f${++this.seq}`, projectId, dedupeKey: w.dedupeKey, status: "new", statusChangedAt: now,
          dismissReason: null, occurrences: 1, firstSeenAt: now, lastSeenAt: now, lastSurfacedAt: now, surfaceReason: "new", lastRunId: runId,
        };
      } else {
        stored = { ...cur, ...w.values, lastSeenAt: now, lastRunId: runId, occurrences: cur.occurrences + 1 };
        if (w.decision.surface) {
          stored.lastSurfacedAt = now;
          stored.surfaceReason = w.decision.reason;
        }
        if (w.decision.reopen) {
          stored.status = "new";
          stored.statusChangedAt = now;
          stored.dismissReason = null;
        }
      }
      this.findings.set(k, stored);
      this.events.push({ findingId: stored.id, type: eventTypeOf(w.decision), payload: { runId, reason: w.decision.reason } });
      if (w.scenario) {
        this.scenarios.push({ projectId, findingId: stored.id, templateKey: w.scenario.templateKey, result: w.scenario.result });
        summary.scenarios++;
      }
      if (w.decision.action === "insert") summary.inserted++;
      else summary.updated++;
      if (w.decision.surface) summary.surfaced++;
      if (w.decision.reopen) summary.reopened++;
    }
    for (const f of input.forecasts) this.forecasts.push({ ...f, projectId, runId });
    summary.forecasts = input.forecasts.length;
    return summary;
  }
}
```

- [ ] **Step 5: Chạy test + typecheck — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/testing/memory-repo.test.ts && npx tsc --noEmit -p . 2>&1 | grep "src/lib/intel" ; echo "tsc-intel-exit:$?"
```
Expected: PASS 3/3; `grep` không in dòng lỗi nào trong `src/lib/intel` (exit của grep = 1 ⇒ in `tsc-intel-exit:1` nghĩa là **không có lỗi**). Lỗi TS ở chỗ khác có sẵn từ trước thì ghi nhận, không sửa.

- [ ] **Step 6: Commit**

```bash
git -C LAAM add src/lib/intel/store src/lib/intel/testing/memory-repo.ts src/lib/intel/testing/memory-repo.test.ts
git -C LAAM commit -m "feat(intel): finding/forecast/scenario persistence with upsert semantics and in-memory twin"
```

---

### Task 17: Pipeline phân tích (`runAnalysis`)

**Files:**
- Create: `LAAM/src/lib/intel/pipeline.ts`, `LAAM/src/lib/intel/pipeline.test.ts`

**Interfaces:**
- Consumes: mọi module Task 3–16.
- Produces:
```ts
export interface AnalysisDeps { provider: MetricsProvider; pack: LoadedPack; repo: IntelRepo; projectId: string; runId: string; now: Date; timeZone: string; asOf?: string }
export interface AnalysisSummary {
  asOf: string; asOfSource: "override" | "provider" | "clock"; packVersion: string;
  rules: { evaluated: number; candidates: number; skipped: RuleSkip[] };
  findings: PersistSummary;
  forecasts: { results: number; skipped: ForecastSkip[] };
  healthScores: HealthScore[];
  warnings: string[];
}
export async function runAnalysis(d: AnalysisDeps): Promise<AnalysisSummary>;
export function resolveAsOf(override: string | undefined, providerAsOf: string | null | undefined, now: Date, timeZone: string): { asOf: string; source: "override" | "provider" | "clock" };
export type { HealthScore } from "./engine/health";
```

**Ngày phân tích (`asOf`, ngày dữ liệu cuối — bao gồm)**, thứ tự theo master §2.4/§2.5 (E10 đã chấp nhận): (1) `deps.asOf` = `business_project.asOfOverride`; (2) `asOf` của provider lấy từ `getDataStatus()` (DAAB `as_of`; demo đặt bằng `kg-packs set-as-of --date 2026-07-31`); (3) hôm qua theo `timeZone`. `asOf` của provider không đúng dạng `YYYY-MM-DD` ⇒ bỏ qua, ghi cảnh báo `provider_as_of_invalid`. `summary.asOfSource` cho biết nhánh nào được dùng. Mọi cửa sổ rule/forecast/so target tính theo `asOf`; `now` chỉ dùng cho mốc thời gian ghi DB, cooldown và task quá hạn. LAAM **không** tự tính độ tươi từ đồng hồ — chỉ đọc nhãn `status` của DAAB (DAAB phải đánh giá nhãn đó theo `as_of` của nó — phụ thuộc Plan B, xem Open questions).

Trình tự (spec §7.2): `listMetrics + getDataStatus` (lỗi ở đây ⇒ **ném**, run `failed` — nguồn không đọc được thì không được báo "không có vấn đề") → overrides → **rules** → **forecast** → doanh thu tuần theo location (cho severity §19) → với mỗi candidate: **nguyên nhân** (nếu có `breakdown`), **confidence**, severity (tier của rule hoặc theo impact), **scenario** (nếu có `scenario_template` + forecast đủ) → **dedup/resurfacing** + **priority** → **health score** → **persist**. Lỗi từng rule/forecast/nguyên nhân/scenario ⇒ ghi vào `skipped`/`warnings` của summary (không nuốt).

- `finding.locationIds` = location của dims; nếu finding cấp chuỗi thì = các location có đóng góp ≠ 0 trong breakdown `location_id`.
- `briefEligible` = `confidence.parts.freshness > 0` (spec §7.3a — dữ liệu incomplete/stale/blocked bị chặn khỏi brief).
- Confidence của scenario = confidence của finding × `forecastIntervalFactor` trên tổng base (spec §7.3a "finding có impact dựa trên dự báo"); lưu trong `scenario.result.confidence`.
- `evidenceRefs` = `{ metricKey, from, to, dims }` (cửa sổ hiện tại của rule).

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/lib/intel/pipeline.test.ts`

```ts
import { describe, expect, test } from "vitest";
import { runAnalysis } from "./pipeline";
import { FakeMetricsProvider, type FakeMetricData } from "./provider/fake";
import { MemoryRepo } from "./testing/memory-repo";
import { catalogItem, currentStatus, dailyPoints } from "./testing/fixtures";
import { ruleSchema, scenarioSchema, scoringSchema, type LoadedPack } from "./pack/schema";
import type { MetricsProvider } from "./provider/types";

const NOW = new Date("2026-08-01T15:00:00Z"); // asOf (America/Chicago) = 2026-07-31
const S = [10, -5, 0, 5, -10, 3, -3];
const LOCS = ["L1", "L2", "L3"];

function data(status: FakeMetricData["dataStatus"] = currentStatus(["acme.revenue", "acme.cost", "acme.refund_rate"])): FakeMetricData {
  return {
    catalog: [
      catalogItem("acme.revenue", "additive", ["location_id"]),
      catalogItem("acme.cost", "additive", ["location_id"]),
      catalogItem("acme.refund_rate", "ratio", ["location_id", "employee_id"]),
    ],
    points: {
      "acme.revenue": LOCS.flatMap((l) => dailyPoints("2026-01-13", 200, { location_id: l }, (i) => ({ value: (1000 + S[i % 7]) * (l === "L1" && i >= 193 ? 0.7 : 1), sampleSize: 50 }))),
      "acme.cost": LOCS.flatMap((l) => dailyPoints("2026-01-13", 200, { location_id: l }, (i) => ({ value: 600 + S[i % 7], sampleSize: 50 }))),
      "acme.refund_rate": LOCS.flatMap((l) => [1, 2].flatMap((e) => dailyPoints("2026-07-02", 30, { location_id: l, employee_id: `${l}-E${e}` }, () => {
        const num = l === "L1" && e === 1 ? 3 : 1;
        return { value: num, numerator: num, denominator: 100, sampleSize: 1 };
      }))),
    },
    dataStatus: status,
  };
}

const pack: LoadedPack = {
  packs: [{ key: "acme", version: "0.1.0" }],
  packVersion: "acme@0.1.0",
  rules: [
    ruleSchema.parse({
      rule_id: "ACME-SALES-001", version: 1, name: "Sales decline", metric: "acme.revenue", dims: ["location_id"], window_days: 7,
      compare: "baseline_same_weekday_4w", condition: "value <= 0.95 * compare_value",
      severity: { critical: "value <= 0.80 * compare_value", high: "value <= 0.90 * compare_value", warning: "value <= 0.95 * compare_value" },
      impact: "compare_value - value", impact_unit: "currency", scenario_template: "acme.sales_change",
      driver: { variable: "change_pct", expr: "(value / compare_value - 1) * 100" },
      recommended_action: "investigate", default_owner_role: "store_manager", cooldown_days: 7, wording: "Sales decline",
    }),
    ruleSchema.parse({
      rule_id: "ACME-LP-001", version: 1, name: "Refund concentration", metric: "acme.refund_rate", dims: ["location_id", "employee_id"],
      window_days: 30, compare: "peer_average", min_sample: 10, condition: "value > 2.5 * compare_value",
      impact: "numerator - compare_value / 100 * denominator", impact_unit: "currency",
      recommended_action: "investigate", default_owner_role: "store_manager", cooldown_days: 7, wording: "Repeated exception pattern",
      threshold_status: "provisional", threshold_note: "Demo default",
    }),
  ],
  forecasts: [
    { metric: "acme.revenue", dims: ["location_id"], horizons_days: [7, 30], season_length: 7 },
    { metric: "acme.cost", dims: ["location_id"], horizons_days: [30], season_length: 7 },
  ],
  scenarios: [scenarioSchema.parse({
    key: "acme.sales_change", label: "Sales change", dims: ["location_id"],
    base: { revenue: { forecast_of: "acme.revenue" }, cost: { forecast_of: "acme.cost" } },
    variables: { change_pct: { default: 0, min: -30, max: 30 } },
    outputs: { profit: "revenue * (1 + change_pct / 100) - cost" }, primary_output: "profit",
    presets: { expected: { trend: "damped" }, best: { trend: "damped", set: { change_pct: 10 } }, risk: { trend: "damped", set: { change_pct: -5 } }, no_action: { trend: "persist_driver" } },
  })],
  glossary: { terms: {} },
  roles: { personas: {} },
  scoring: scoringSchema.parse({
    priority_weights: { financial: 30, urgency: 20, confidence: 15, target_variance: 10, locations: 10, repeated: 10, strategic: 5 },
    urgency: { critical: 1, high: 0.75, medium: 0.5, warning: 0.5, low: 0.25 },
    severity_by_impact: { sales_metric: "acme.revenue", tiers: [{ level: "critical", min_amount: 10000, min_pct_weekly_sales: 1 }, { level: "high", min_amount: 5000, min_pct_weekly_sales: 0.5 }, { level: "medium", min_amount: 1000, min_pct_weekly_sales: 0.1 }], otherwise: "low" },
    normalization: { target_variance_pct: 20, repeated_occurrences: 4 },
    strategic_rules: [],
    resurfacing: { impact_change_pct: 20, sample_growth_pct: 25 },
    confidence: { deviation_z_midpoint: 2, relative_z_scale: 10, freshness_current: 1, freshness_delayed: 0.7, min_interval_factor: 0.2 },
    health_score: {
      components: { sales: { weight: 30, rules: ["ACME-SALES-*"] }, lp: { weight: 20, rules: ["ACME-LP-*"] } },
      data_quality_weight: 10,
      severity_penalty: { critical: 60, high: 40, medium: 20, warning: 20, low: 5 },
      status_bands: [{ min: 85, label: "healthy" }, { min: 70, label: "monitor" }, { min: 50, label: "needs_attention" }, { min: 0, label: "high_priority" }],
    },
  }),
};

const deps = (provider: MetricsProvider, repo = new MemoryRepo(), runId = "run-1") =>
  ({ provider, pack, repo, projectId: "bp1", runId, now: NOW, timeZone: "America/Chicago" });

describe("runAnalysis", () => {
  test("first run creates surfaced findings with factors, scenario, forecasts and health scores", async () => {
    const repo = new MemoryRepo();
    const summary = await runAnalysis(deps(new FakeMetricsProvider(data()), repo));
    expect(summary.asOf).toBe("2026-07-31");
    expect(summary.findings).toMatchObject({ inserted: 2, updated: 0, surfaced: 2, scenarios: 1 });
    const all = [...repo.findings.values()];
    const sales = all.find((f) => f.ruleId === "ACME-SALES-001")!;
    expect(sales).toMatchObject({ severity: "critical", locationIds: ["L1"], briefEligible: true, status: "new", packVersion: "acme@0.1.0" });
    expect(sales.evidenceRefs).toEqual({ metricKey: "acme.revenue", from: "2026-07-25", to: "2026-08-01", dims: { location_id: "L1" } });
    const lp = all.find((f) => f.ruleId === "ACME-LP-001")!;
    expect(lp.dims).toEqual({ location_id: "L1", employee_id: "L1-E1" });
    // E11: the provisional flag reaches the finding; the confirmed rule stays confirmed.
    expect(lp).toMatchObject({ thresholdStatus: "provisional", thresholdNote: "Demo default" });
    expect(sales).toMatchObject({ thresholdStatus: "confirmed", thresholdNote: null });
    expect(lp.severityReason).toMatch(/impact|no currency/); // no tier in the rule => request §19 by impact
    const sc = repo.scenarios[0].result as { presets: { preset: string; primary: number }[] };
    const p = Object.fromEntries(sc.presets.map((x) => [x.preset, x.primary]));
    expect(p.no_action).toBeLessThanOrEqual(p.expected); // equal when the model does not beat its baselines
    expect(repo.forecasts.filter((f) => f.metricKey === "acme.revenue")).toHaveLength(6); // 3 locations x 2 horizons
    expect(summary.healthScores.map((h) => h.locationId)).toEqual(LOCS);
    expect(summary.healthScores.find((h) => h.locationId === "L1")!.score).toBeLessThan(100);
    expect(summary.healthScores.find((h) => h.locationId === "L2")!.score).toBe(100);
  });

  test("second run on identical data creates no new finding and surfaces nothing", async () => {
    const repo = new MemoryRepo();
    await runAnalysis(deps(new FakeMetricsProvider(data()), repo, "run-1"));
    const second = await runAnalysis(deps(new FakeMetricsProvider(data()), repo, "run-2"));
    expect(second.findings).toMatchObject({ inserted: 0, updated: 2, surfaced: 0 });
    expect(repo.findings.size).toBe(2);
  });

  // Why: the demo data ends 2026-07-31 while the real clock is months later; windows derived
  // from the wall clock would read empty periods and report nothing. Order (master §2.4):
  // project override -> provider as_of -> yesterday in the project time zone.
  const LATE = new Date("2026-10-02T15:00:00Z");

  test("as-of branch 1: the project override wins over the provider's as-of", async () => {
    const repo = new MemoryRepo();
    const summary = await runAnalysis({ ...deps(new FakeMetricsProvider({ ...data(), asOf: "2026-07-15" }), repo), now: LATE, asOf: "2026-07-31" });
    expect(summary).toMatchObject({ asOf: "2026-07-31", asOfSource: "override" });
    expect(summary.findings.inserted).toBe(2);
    expect(repo.forecasts[0].startDate).toBe("2026-08-01");
  });

  test("as-of branch 2: without an override the provider's as-of drives every window", async () => {
    const summary = await runAnalysis({ ...deps(new FakeMetricsProvider({ ...data(), asOf: "2026-07-31" })), now: LATE });
    expect(summary).toMatchObject({ asOf: "2026-07-31", asOfSource: "provider" });
    expect(summary.findings.inserted).toBe(2);
    expect(summary.warnings.some((w) => w.startsWith("provider_as_of_invalid"))).toBe(false);
  });

  test("as-of branch 3: no usable provider as-of falls back to yesterday in the project zone and warns", async () => {
    const summary = await runAnalysis(deps(new FakeMetricsProvider({ ...data(), asOf: "" })));
    expect(summary).toMatchObject({ asOf: "2026-07-31", asOfSource: "clock" }); // NOW = 2026-08-01 10:00 Chicago
    expect(summary.warnings).toContain('provider_as_of_invalid:""');
  });

  test("stale data keeps the finding but blocks it from the brief", async () => {
    const repo = new MemoryRepo();
    await runAnalysis(deps(new FakeMetricsProvider(data([...currentStatus(["acme.cost", "acme.refund_rate"]), ...currentStatus(["acme.revenue"], "stale")])), repo));
    expect([...repo.findings.values()].find((f) => f.ruleId === "ACME-SALES-001")!.briefEligible).toBe(false);
  });

  test("a source that cannot list metrics fails the run loudly", async () => {
    const broken = new FakeMetricsProvider(data());
    broken.listMetrics = async () => { throw new Error("source down"); };
    await expect(runAnalysis(deps(broken))).rejects.toThrow("source down");
  });

  test("a provider error on one rule is reported and other rules still run", async () => {
    const fake = new FakeMetricsProvider(data());
    const provider: MetricsProvider = {
      listMetrics: () => fake.listMetrics(),
      getDataStatus: () => fake.getDataStatus(),
      getEvidence: (q) => fake.getEvidence(q),
      getMetrics: async (q) => {
        if (q.metricKeys.includes("acme.refund_rate")) throw new Error("timeout");
        return fake.getMetrics(q);
      },
    };
    const summary = await runAnalysis(deps(provider));
    expect(summary.rules.skipped).toContainEqual({ ruleId: "ACME-LP-001", reason: "provider_error: timeout" });
    expect(summary.findings.inserted).toBe(1);
  });
});
```

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/pipeline.test.ts
```
Expected: FAIL — `Cannot find module './pipeline'`.

- [ ] **Step 3: Implement** — `LAAM/src/lib/intel/pipeline.ts`

```ts
// One analysis run: load -> rules -> forecast -> causes/confidence/severity/scenario -> dedupe
// + priority -> health -> persist (spec §7.2). Every number is computed here or in the provider;
// partial failures are reported in the summary, never swallowed.
import { evalNumber, ExprError } from "./expr";
import { analyzeCauses, type CauseBreakdown } from "./engine/causes";
import { computeConfidence, forecastIntervalFactor } from "./engine/confidence";
import { decideFinding, dedupeKey } from "./engine/dedupe";
import { computeHealthScores, type HealthScore } from "./engine/health";
import { evaluateRules, type RuleCandidate, type RuleSkip } from "./engine/rules";
import { priorityScore, severityByImpact } from "./engine/scoring";
import { runForecasts, type ForecastSkip } from "./forecast/service";
import { resolvePresetSets, resolvePriorityWeights } from "./overrides";
import type { LoadedPack, Severity } from "./pack/schema";
import { LOCATION_DIM } from "./provider/scoped";
import type { DataStatusItem, MetricCatalogItem, MetricsProvider } from "./provider/types";
import { computeScenario, scenarioBaseFromForecasts, type ScenarioResult } from "./scenario/engine";
import type { FindingWrite, ForecastWrite, IntelRepo, PersistSummary } from "./store/repo";
import { asOfDate, daysBetween, windowEnding } from "./time";

export type { HealthScore } from "./engine/health";

export interface AnalysisDeps {
  provider: MetricsProvider;
  pack: LoadedPack;
  repo: IntelRepo;
  projectId: string;
  runId: string;
  now: Date;
  timeZone: string;
  /** business_project.asOfOverride (last complete data day). Wins over the provider's asOf. */
  asOf?: string;
}

export interface AnalysisSummary {
  asOf: string;
  asOfSource: "override" | "provider" | "clock";
  packVersion: string;
  rules: { evaluated: number; candidates: number; skipped: RuleSkip[] };
  findings: PersistSummary;
  forecasts: { results: number; skipped: ForecastSkip[] };
  healthScores: HealthScore[];
  warnings: string[];
}

const WEEK_DAYS = 7;

interface WeeklySales {
  byLocation: Map<string, number>;
  total: number | null;
  locations: string[];
}

async function weeklySales(
  provider: MetricsProvider,
  metricKey: string,
  catalog: ReadonlyMap<string, MetricCatalogItem>,
  asOf: string,
  warnings: string[],
): Promise<WeeklySales> {
  const item = catalog.get(metricKey);
  if (!item || !item.enabled) {
    warnings.push(`severity_sales_metric_unavailable:${metricKey}`);
    return { byLocation: new Map(), total: null, locations: [] };
  }
  const w = windowEnding(asOf, WEEK_DAYS);
  const groupBy = item.dims.includes(LOCATION_DIM) ? [LOCATION_DIM] : [];
  const res = await provider.getMetrics({ metricKeys: [metricKey], from: w.from, to: w.to, grain: "total", groupBy });
  const byLocation = new Map<string, number>();
  let total = 0;
  for (const p of res.series.find((s) => s.metricKey === metricKey)?.points ?? []) {
    if (p.value == null) continue;
    total += p.value;
    const loc = p.dims[LOCATION_DIM];
    if (loc !== undefined) byLocation.set(loc, p.value);
  }
  return { byLocation, total, locations: [...byLocation.keys()].sort() };
}

function freshnessOf(cand: RuleCandidate, items: readonly DataStatusItem[]): DataStatusItem["status"] | null {
  const subject = `metric:${cand.metricKey}`;
  return cand.dataStatus.find((s) => s.subject === subject)?.status ?? items.find((s) => s.subject === subject)?.status ?? null;
}

function locationIdsOf(cand: RuleCandidate, causes: readonly CauseBreakdown[]): string[] {
  const own = cand.dims[LOCATION_DIM];
  if (own !== undefined) return [own];
  const fromCauses = causes.filter((c) => c.dim === LOCATION_DIM).flatMap((c) => c.factors.filter((f) => f.contribution !== 0).map((f) => f.key));
  return [...new Set(fromCauses)].sort();
}

function driverValue(cand: RuleCandidate): number | null {
  if (!cand.rule.driver) return null;
  try {
    return evalNumber(cand.rule.driver.expr, cand.vars);
  } catch (e) {
    if (e instanceof ExprError) return null;
    throw e;
  }
}

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

/** Analysis date: project override -> provider's last data day -> yesterday in the project zone. */
export function resolveAsOf(
  override: string | undefined,
  providerAsOf: string | null | undefined,
  now: Date,
  timeZone: string,
): { asOf: string; source: "override" | "provider" | "clock" } {
  if (override) return { asOf: override, source: "override" };
  if (providerAsOf && DAY_RE.test(providerAsOf)) return { asOf: providerAsOf, source: "provider" };
  return { asOf: asOfDate(now, timeZone), source: "clock" };
}

export async function runAnalysis(d: AnalysisDeps): Promise<AnalysisSummary> {
  const warnings: string[] = [];
  const scoring = d.pack.scoring;

  // A source we cannot read must fail the run — "no findings" would be a false all-clear.
  const { metrics } = await d.provider.listMetrics();
  const status = await d.provider.getDataStatus();
  const resolved = resolveAsOf(d.asOf, status.asOf, d.now, d.timeZone);
  if (!d.asOf && resolved.source === "clock") warnings.push(`provider_as_of_invalid:${JSON.stringify(status.asOf ?? null)}`);
  const asOf = resolved.asOf;
  const catalog = new Map(metrics.map((m) => [m.key, m]));
  const disabledMetrics = new Map(status.disabledMetrics.map((x) => [x.metricKey, x.reason]));
  const overrides = await d.repo.loadOverrides(d.projectId);
  const weights = resolvePriorityWeights(scoring, overrides);

  const evaluation = await evaluateRules(d.pack.rules, { provider: d.provider, asOf, catalog, disabledMetrics, overrides });
  const fc = await runForecasts(d.provider, d.pack.forecasts, catalog, asOf);
  const weekly = await weeklySales(d.provider, scoring.severity_by_impact.sales_metric, catalog, asOf, warnings);

  interface Prepared {
    cand: RuleCandidate;
    key: string;
    causes: CauseBreakdown[];
    confidence: ReturnType<typeof computeConfidence>;
    severity: { level: Severity; reason: string };
    weeklySales: number | null;
    locationIds: string[];
    scenario: FindingWrite["scenario"];
  }
  const prepared: Prepared[] = [];

  for (const cand of evaluation.candidates) {
    let causes: CauseBreakdown[] = [];
    if (cand.rule.breakdown.length > 0) {
      try {
        causes = await analyzeCauses(d.provider, cand, catalog);
      } catch (e) {
        warnings.push(`causes_failed:${cand.rule.rule_id}: ${e instanceof Error ? e.message : String(e)}`);
      }
    }
    const confidence = computeConfidence({
      sampleSize: cand.sampleSize,
      minSample: cand.rule.min_sample,
      value: cand.value,
      compareValue: cand.compareValue,
      sigma: cand.sigma,
      freshness: freshnessOf(cand, status.items),
      weights: cand.rule.confidence_weights,
      params: scoring.confidence,
    });
    const loc = cand.dims[LOCATION_DIM];
    const ws = loc !== undefined ? weekly.byLocation.get(loc) ?? null : weekly.total;
    const severity = cand.severity
      ? { level: cand.severity, reason: cand.severityReason ?? cand.severity }
      : severityByImpact(cand.impact, cand.impactUnit, ws, scoring.severity_by_impact);

    let scenario: FindingWrite["scenario"] = null;
    if (cand.rule.scenario_template) {
      const tpl = d.pack.scenarios.find((s) => s.key === cand.rule.scenario_template);
      const base = tpl ? scenarioBaseFromForecasts(tpl, fc.results, cand.dims) : null;
      if (!tpl || !base) {
        warnings.push(`scenario_unavailable:${cand.rule.rule_id}:${cand.rule.scenario_template}`);
      } else {
        const dv = driverValue(cand);
        const result: ScenarioResult & { confidence?: number; baseReliable?: boolean } = computeScenario(tpl, {
          base: base.base,
          persistBase: base.persistBase, // no_action: current level persists; the driver is NOT re-applied
          driver: dv !== null && cand.rule.driver ? { variable: cand.rule.driver.variable, value: dv } : null,
          presetSets: resolvePresetSets(tpl, overrides),
        });
        const sumOf = (r: Record<string, number>) => Object.values(r).reduce((s, x) => s + x, 0);
        // No backtest interval (short history) => the most cautious factor, never "perfectly certain".
        const factor = base.lower && base.upper
          ? forecastIntervalFactor(sumOf(base.base), sumOf(base.lower), sumOf(base.upper), scoring.confidence.min_interval_factor)
          : scoring.confidence.min_interval_factor;
        result.confidence = confidence.score * factor;
        result.baseReliable = base.reliable;
        scenario = { templateKey: tpl.key, assumptions: result.presets.map((p) => ({ preset: p.preset, assumptions: p.assumptions })), result, baseline: result.baseline };
      }
    }
    prepared.push({
      cand,
      key: dedupeKey(cand.rule.rule_id, cand.dims),
      causes,
      confidence,
      severity,
      weeklySales: ws,
      locationIds: locationIdsOf(cand, causes),
      scenario,
    });
  }

  const existing = await d.repo.loadExisting(d.projectId, prepared.map((p) => p.key));
  const overdue = await d.repo.overdueFindingIds(d.projectId, d.now);
  const totalLocations = weekly.locations.length || new Set(prepared.flatMap((p) => p.locationIds)).size;

  const writes: FindingWrite[] = prepared.map((p) => {
    const ex = existing.get(p.key) ?? null;
    const decision = decideFinding(
      ex,
      { severity: p.severity.level, impact: p.cand.impact, sampleSize: p.cand.sampleSize, windowDays: daysBetween(p.cand.window.from, p.cand.window.to) },
      { now: d.now, cooldownDays: p.cand.rule.cooldown_days, taskOverdue: ex ? overdue.has(ex.id) : false, resurfacing: scoring.resurfacing },
    );
    const priority = priorityScore(
      {
        impact: p.cand.impact,
        impactUnit: p.cand.impactUnit,
        weeklySales: p.weeklySales,
        severity: p.severity.level,
        confidence: p.confidence.score,
        compareMode: p.cand.rule.compare,
        variancePct: p.cand.variancePct,
        locationCount: p.locationIds.length,
        totalLocations,
        occurrences: decision.occurrences,
        ruleId: p.cand.rule.rule_id,
      },
      scoring,
      weights,
    );
    return {
      dedupeKey: p.key,
      decision,
      scenario: p.scenario,
      values: {
        ruleId: p.cand.rule.rule_id,
        ruleVersion: p.cand.rule.version,
        packVersion: d.pack.packVersion,
        metricKey: p.cand.metricKey,
        dims: p.cand.dims,
        locationIds: p.locationIds,
        currentValue: p.cand.value,
        expectedValue: p.cand.compareValue,
        variance: p.cand.variance,
        variancePct: p.cand.variancePct,
        comparison: { ...p.cand.comparison, window: p.cand.window, sigma: p.cand.sigma, unit: p.cand.unit, ruleSource: p.cand.ruleSource },
        estimatedImpact: p.cand.impact,
        impactUnit: p.cand.impactUnit,
        severity: p.severity.level,
        severityReason: p.severity.reason,
        confidence: p.confidence.score,
        confidenceReason: { parts: p.confidence.parts, ...p.confidence.reason },
        priorityScore: priority.score,
        priorityComponents: { components: priority.components, weights },
        contributingFactors: p.causes,
        recommendedAction: p.cand.rule.recommended_action,
        defaultOwnerRole: p.cand.rule.default_owner_role,
        wording: p.cand.rule.wording,
        evidenceRefs: { metricKey: p.cand.metricKey, from: p.cand.window.from, to: p.cand.window.to, dims: p.cand.dims },
        dataStatusSnapshot: p.cand.dataStatus,
        briefEligible: p.confidence.parts.freshness > 0,
        thresholdStatus: p.cand.rule.threshold_status, // E11 badge; deliberately not used in confidence
        thresholdNote: p.cand.rule.threshold_note ?? null,
        sampleSize: p.cand.sampleSize,
      },
    };
  });

  const locations = weekly.locations.length ? weekly.locations : [...new Set(prepared.flatMap((p) => p.locationIds))].sort();
  const healthScores = computeHealthScores({
    locations,
    findings: prepared.map((p) => ({ ruleId: p.cand.rule.rule_id, severity: p.severity.level, locationIds: p.locationIds })),
    dataStatus: status.items,
    cfg: scoring.health_score,
    freshness: { current: scoring.confidence.freshness_current, delayed: scoring.confidence.freshness_delayed },
    previous: await d.repo.previousHealthScores(d.projectId, d.runId),
  });

  // Explicit element types: without them TS infers `label: null` / `model: null` and rejects the
  // union with the "ok" branch (TS2345).
  const forecastWrites: ForecastWrite[] = fc.results.flatMap((r): ForecastWrite[] => {
    if (r.output.status !== "ok") {
      const cfg = d.pack.forecasts.find((f) => f.metric === r.metricKey);
      return (cfg?.horizons_days ?? []).map((h): ForecastWrite => ({
        metricKey: r.metricKey, dims: r.dims, horizonDays: h, startDate: r.startDate, status: r.output.status, label: null,
        model: null, modelVersion: r.output.modelVersion, baselineModel: null, reliable: false, historyDays: r.output.historyDays,
        point: [], lower: [], upper: [], sum: {}, backtest: null, warnings: r.output.warnings,
      }));
    }
    return r.output.horizons.map((h): ForecastWrite => ({
      metricKey: r.metricKey, dims: r.dims, horizonDays: h.horizonDays, startDate: r.startDate, status: r.output.status,
      label: r.output.label, model: h.model, modelVersion: r.output.modelVersion,
      baselineModel: h.reliable ? null : h.model, reliable: h.reliable, historyDays: r.output.historyDays,
      point: h.point, lower: h.lower, upper: h.upper, // [] when there is no backtest interval
      sum: { ...h.sum, damped: h.dampedSum, interval: h.interval }, backtest: h.backtest, warnings: r.output.warnings,
    }));
  });

  const findingsSummary = await d.repo.persist({ projectId: d.projectId, runId: d.runId, now: d.now, findings: writes, forecasts: forecastWrites });

  return {
    asOf,
    asOfSource: resolved.source,
    packVersion: d.pack.packVersion,
    rules: { evaluated: d.pack.rules.length, candidates: evaluation.candidates.length, skipped: evaluation.skipped },
    findings: findingsSummary,
    forecasts: { results: fc.results.length, skipped: fc.skipped },
    healthScores,
    warnings,
  };
}
```

Ghi chú khớp test:
- asOf: `2026-08-01T15:00Z` ở Chicago là 10:00 ngày 1/8 ⇒ asOf = 2026-07-31; cửa sổ 7 ngày = 07-25..07-31; dữ liệu 200 ngày từ 2026-01-13 kết thúc 2026-07-31 (i = 193..199 là 7 ngày cuối ⇒ giảm 30% ⇒ `critical`).
- `ACME-LP-001`: L1-E1 tỉ lệ 3% so với peer (5 nhân viên còn lại) 1% ⇒ > 2.5×; mẫu 30 ≥ 10. Impact ≈ $60 ⇒ dưới mọi tier ⇒ `low` theo request §19 (reason chứa "impact").
- Forecast `acme.revenue`: 3 location × horizon [7, 30] = 6 dòng; `acme.cost`: 3 × [30].
- Health: L1 bị trừ ở `sales` (critical 60) và `lp` (low 5) ⇒ < 100; L2/L3 = 100.

- [ ] **Step 4: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/pipeline.test.ts
```
Expected: PASS 8/8 (có thể mất 10–30s do grid search forecast; nếu > 60s, báo cáo — đừng giảm grid trong test).

- [ ] **Step 5: Commit**

```bash
git -C LAAM add src/lib/intel/pipeline.ts src/lib/intel/pipeline.test.ts
git -C LAAM commit -m "feat(intel): analysis pipeline from metrics to persisted findings, forecasts and scenarios"
```

---

### Task 18: Analysis job (claim theo pattern workflow) + nối vào route tick

**Files:**
- Create: `LAAM/src/lib/intel/jobs.ts`, `LAAM/src/lib/intel/jobs.test.ts`, `LAAM/src/lib/intel/run-project.ts`, `LAAM/src/lib/intel/run-project.test.ts`
- Modify: `LAAM/src/app/api/workflows/tick/route.ts`

**Interfaces:**
- Consumes: `analysisJobs`, `analysisRuns`, `businessProjects` (Task 1); `nextRunInTimeZone` (Task 7); `providerForProject` (Task 5); `loadPacks/packsDir` (Task 6); `runAnalysis` (Task 17); `drizzleRepo` (Task 16); `isTickAuthorized` (tick-auth.ts — không đổi).
- Produces:
```ts
// jobs.ts
export const MAX_CONSECUTIVE_ERRORS = 3;
export type RunPipeline = (businessProjectId: string, opts: { runId: string; now: Date }) => Promise<unknown>;
export interface ClaimedRun { id: string; jobId: string | null; businessProjectId: string }
export async function claimDueAnalysisJobs(db: typeof Db, now: Date): Promise<string[]>;
export async function claimQueuedAnalysisRuns(db: typeof Db, now: Date, limit?: number): Promise<ClaimedRun[]>;
export async function executeAnalysisRun(db: typeof Db, run: ClaimedRun, deps: { runPipeline: RunPipeline; now: Date }): Promise<"succeeded" | "failed">;
export async function tickAnalysis(db: typeof Db, now: Date, deps: { runPipeline: RunPipeline; staleMinutes?: number }): Promise<{ claimed: number; executed: number; failed: number; stale: number }>;
export async function failStaleRuns(db: typeof Db, now: Date, staleMinutes: number): Promise<number>;
export async function recordJobFailure(db: typeof Db, jobId: string, message: string): Promise<void>;
export function staleRunMinutes(): number;   // env INTEL_RUN_STALE_MINUTES, default 60
// run-project.ts
export async function runAnalysisForProject(businessProjectId: string, opts: { runId: string; now: Date }): Promise<AnalysisSummary>;
```

Pattern (copy `lib/workflow/schedule.ts:48-143`, spec §2.4 I1): claim = trong **một** transaction `INSERT analysis_run{queued, scheduledFor = nextRunAt đã lưu, làm tròn phút} ON CONFLICT (jobId, scheduledFor) DO NOTHING` + đẩy `nextRunAt` (cron tính theo `timezone` của job, strictly > now, không chạy bù). Lỗi khi claim (cron/timezone sai) ⇒ **tự tắt** job (update riêng, ngoài tx), các job khác vẫn chạy. Lấy run `queued` để chạy bằng `UPDATE … WHERE id IN (SELECT … FOR UPDATE SKIP LOCKED LIMIT n)` (kiểu `tickResume`, không kiểu `tickExecute`) ⇒ hai poke song song không chạy trùng một run. Run lỗi ⇒ `consecutiveErrors + 1`; đạt `MAX_CONSECUTIVE_ERRORS` (3) ⇒ `enabled = false`; run thành công ⇒ reset về 0. Run kẹt `running` quá `INTEL_RUN_STALE_MINUTES` phút (mặc định 60, process chết giữa chừng) ⇒ mỗi tick đánh `failed` (`stale: …`) và tính lỗi cho job (`failStaleRuns`). Route tick bọc phần analysis trong `try/catch` riêng ⇒ lỗi intel **không** làm hỏng scheduler workflow.

`runAnalysisForProject`: đọc `business_project` → provider (mode `system`, gọi MCP dưới danh nghĩa owner) → danh sách pack đang bật lấy từ `listMetrics().packs` (DAAB `pack_install` là nguồn sự thật, spec §5.3) → `loadPacks(PACKS_DIR, keys)` → `runAnalysis({ …, asOf: bp.asOfOverride ?? undefined })`; version pack DAAB ≠ version file LAAM ⇒ cảnh báo `pack_version_mismatch:*` trong summary.

- [ ] **Step 1: Viết test thất bại cho jobs** — `LAAM/src/lib/intel/jobs.test.ts`

```ts
import { describe, expect, test, vi } from "vitest";
import { claimDueAnalysisJobs, claimQueuedAnalysisRuns, executeAnalysisRun, failStaleRuns, MAX_CONSECUTIVE_ERRORS } from "./jobs";

const NAME = Symbol.for("drizzle:Name");
const tname = (t: unknown) => (t as Record<symbol, string>)[NAME];
type Log = { op: "insert" | "update"; table: string; values: Record<string, unknown>; inTx: boolean };

function fakeDb(opts: { jobs?: unknown[]; jobRow?: unknown; insertReturns?: () => unknown[]; updateReturns?: unknown[] } = {}) {
  const log: Log[] = [];
  const forCalls: unknown[][] = [];
  let txCount = 0;
  const api = (inTx: boolean) => ({
    select: () => ({
      from: (t: unknown) => ({
        where: () => {
          const rows = tname(t) === "analysis_job" ? (opts.jobRow ? [opts.jobRow] : opts.jobs ?? []) : [];
          return Object.assign(Promise.resolve(rows), {
            limit: () => Object.assign(Promise.resolve(rows), {
              for: (...a: unknown[]) => { forCalls.push(a); return { sub: true }; },
            }),
          });
        },
      }),
    }),
    insert: (t: unknown) => ({
      values: (v: Record<string, unknown>) => ({
        onConflictDoNothing: () => ({
          returning: async () => {
            log.push({ op: "insert", table: tname(t), values: v, inTx });
            return opts.insertReturns ? opts.insertReturns() : [{ id: v.id }];
          },
        }),
      }),
    }),
    update: (t: unknown) => ({
      set: (v: Record<string, unknown>) => ({
        where: () => {
          log.push({ op: "update", table: tname(t), values: v, inTx });
          return Object.assign(Promise.resolve(), { returning: async () => opts.updateReturns ?? [] });
        },
      }),
    }),
  });
  const db = { ...api(false), transaction: async (fn: (tx: unknown) => Promise<void>) => { txCount++; await fn(api(true)); } };
  return { db: db as never, log, forCalls, txCount: () => txCount };
}

const job = (over: Record<string, unknown> = {}) => ({
  id: "j1", businessProjectId: "bp1", cron: "0 6 * * *", timezone: "America/Chicago",
  nextRunAt: new Date("2026-10-02T11:00:00Z"), enabled: true, consecutiveErrors: 0, ...over,
});

describe("claimDueAnalysisJobs", () => {
  test("claims the slot and advances nextRunAt (in the job's time zone) in the same transaction", async () => {
    const f = fakeDb({ jobs: [job()] });
    const ids = await claimDueAnalysisJobs(f.db, new Date("2026-10-02T11:00:30Z"));
    expect(ids).toHaveLength(1);
    expect(f.txCount()).toBe(1);
    const ins = f.log.find((l) => l.op === "insert")!;
    expect(ins).toMatchObject({ table: "analysis_run", inTx: true, values: { jobId: "j1", trigger: "schedule", status: "queued" } });
    expect((ins.values.scheduledFor as Date).toISOString()).toBe("2026-10-02T11:00:00.000Z");
    const upd = f.log.find((l) => l.op === "update")!;
    expect(upd.inTx).toBe(true);
    expect((upd.values.nextRunAt as Date).toISOString()).toBe("2026-10-03T11:00:00.000Z");
  });

  test("a slot already claimed by a racing poke is not counted but still advances", async () => {
    const f = fakeDb({ jobs: [job()], insertReturns: () => [] });
    expect(await claimDueAnalysisJobs(f.db, new Date("2026-10-02T11:00:30Z"))).toEqual([]);
    expect(f.log.some((l) => l.op === "update" && l.values.nextRunAt)).toBe(true);
  });

  test("a job that cannot be scheduled is disabled and does not block the others", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    const f = fakeDb({ jobs: [job({ id: "bad", timezone: "Mars/Base" }), job({ id: "ok" })] });
    const ids = await claimDueAnalysisJobs(f.db, new Date("2026-10-02T11:00:30Z"));
    expect(ids).toHaveLength(1);
    expect(f.log).toContainEqual(expect.objectContaining({ op: "update", table: "analysis_job", inTx: false, values: expect.objectContaining({ enabled: false }) }));
    err.mockRestore();
  });
});

describe("claimQueuedAnalysisRuns", () => {
  test("claims with FOR UPDATE SKIP LOCKED so two pokes never run the same analysis", async () => {
    const f = fakeDb({ updateReturns: [{ id: "r1", jobId: "j1", businessProjectId: "bp1" }] });
    const runs = await claimQueuedAnalysisRuns(f.db, new Date());
    expect(runs).toEqual([{ id: "r1", jobId: "j1", businessProjectId: "bp1" }]);
    expect(f.forCalls[0]).toEqual(["update", { skipLocked: true }]);
    expect(f.log[0]).toMatchObject({ op: "update", table: "analysis_run", values: { status: "running" } });
  });
});

describe("failStaleRuns", () => {
  // Why (review): a run left `running` by a crash would sit there forever and its job would never
  // count the failure (manual runs and schedule slots alike).
  test("fails runs stuck in running and counts the error on their job", async () => {
    const f = fakeDb({ updateReturns: [{ id: "r9", jobId: "j1" }], jobRow: { consecutiveErrors: 0, enabled: true } });
    const n = await failStaleRuns(f.db, new Date("2026-10-02T12:00:00Z"), 60);
    expect(n).toBe(1);
    expect(f.log[0]).toMatchObject({ table: "analysis_run", values: { status: "failed", error: "stale: still running after 60 minutes" } });
    expect(f.log[1]).toMatchObject({ table: "analysis_job", values: { consecutiveErrors: 1, enabled: true } });
  });
});

describe("executeAnalysisRun", () => {
  const run = { id: "r1", jobId: "j1", businessProjectId: "bp1" };

  test("success stores the summary and resets the job's error count", async () => {
    const f = fakeDb();
    const status = await executeAnalysisRun(f.db, run, { runPipeline: async () => ({ ok: 1 }), now: new Date() });
    expect(status).toBe("succeeded");
    expect(f.log[0]).toMatchObject({ table: "analysis_run", values: { status: "succeeded", summary: { ok: 1 } } });
    expect(f.log[1]).toMatchObject({ table: "analysis_job", values: { consecutiveErrors: 0, lastError: null } });
  });

  test("failure is recorded on the run and counted on the job", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    const f = fakeDb({ jobRow: { consecutiveErrors: 0, enabled: true } });
    const status = await executeAnalysisRun(f.db, run, { runPipeline: async () => { throw new Error("source down"); }, now: new Date() });
    expect(status).toBe("failed");
    expect(f.log[0]).toMatchObject({ table: "analysis_run", values: { status: "failed", error: "source down" } });
    expect(f.log[1]).toMatchObject({ table: "analysis_job", values: { consecutiveErrors: 1, enabled: true } });
    err.mockRestore();
  });

  test(`the ${MAX_CONSECUTIVE_ERRORS}rd consecutive failure disables the job`, async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    const f = fakeDb({ jobRow: { consecutiveErrors: MAX_CONSECUTIVE_ERRORS - 1, enabled: true } });
    await executeAnalysisRun(f.db, run, { runPipeline: async () => { throw new Error("x"); }, now: new Date() });
    expect(f.log[1].values).toMatchObject({ consecutiveErrors: MAX_CONSECUTIVE_ERRORS, enabled: false });
    err.mockRestore();
  });

  test("manual runs (no job) only update the run", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    const f = fakeDb();
    await executeAnalysisRun(f.db, { ...run, jobId: null }, { runPipeline: async () => { throw new Error("x"); }, now: new Date() });
    expect(f.log.map((l) => l.table)).toEqual(["analysis_run"]);
    err.mockRestore();
  });
});
```

- [ ] **Step 2: Viết test thất bại cho run-project** — `LAAM/src/lib/intel/run-project.test.ts`

```ts
import { describe, expect, test, vi } from "vitest";

const h = vi.hoisted(() => ({
  bp: null as Record<string, unknown> | null,
  runAnalysis: vi.fn(),
  loadPacks: vi.fn(),
  listMetrics: vi.fn(),
}));
vi.mock("@/db", () => ({ db: { select: () => ({ from: () => ({ where: () => ({ limit: async () => (h.bp ? [h.bp] : []) }) }) }) } }));
vi.mock("./provider/factory", () => ({ providerForProject: vi.fn(async () => ({ listMetrics: h.listMetrics })) }));
vi.mock("./pack/loader", () => ({ loadPacks: h.loadPacks, packsDir: () => "/packs" }));
vi.mock("./pipeline", () => ({ runAnalysis: h.runAnalysis }));
vi.mock("./store/repo", () => ({ drizzleRepo: () => ({}) }));

import { runAnalysisForProject } from "./run-project";

describe("runAnalysisForProject", () => {
  test("uses the packs enabled at the source, the project time zone and its as-of override", async () => {
    h.bp = { id: "bp1", timezone: "America/Chicago", asOfOverride: "2026-07-31" };
    h.listMetrics.mockResolvedValue({ packs: [{ key: "retail", version: "0.1.0" }, { key: "pharmacy", version: "0.2.0" }], metrics: [] });
    h.loadPacks.mockResolvedValue({ packs: [{ key: "retail", version: "0.1.0" }, { key: "pharmacy", version: "0.1.0" }] });
    h.runAnalysis.mockResolvedValue({ warnings: [] });
    const now = new Date("2026-10-02T12:00:00Z");
    const summary = await runAnalysisForProject("bp1", { runId: "r1", now });
    expect(h.loadPacks).toHaveBeenCalledWith("/packs", ["retail", "pharmacy"]);
    expect(h.runAnalysis).toHaveBeenCalledWith(expect.objectContaining({ projectId: "bp1", runId: "r1", now, timeZone: "America/Chicago", asOf: "2026-07-31" }));
    expect(summary.warnings).toEqual(["pack_version_mismatch:pharmacy: source=0.2.0 laam=0.1.0"]);
  });

  test("fails loudly for an unknown project or a source with no packs", async () => {
    h.bp = null;
    await expect(runAnalysisForProject("nope", { runId: "r", now: new Date() })).rejects.toThrow(/not found/);
    h.bp = { id: "bp1", timezone: "UTC", asOfOverride: null };
    h.listMetrics.mockResolvedValue({ packs: [], metrics: [] });
    await expect(runAnalysisForProject("bp1", { runId: "r", now: new Date() })).rejects.toThrow(/no enabled packs/);
  });
});
```

- [ ] **Step 3: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/jobs.test.ts src/lib/intel/run-project.test.ts
```
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 4: Implement** — `LAAM/src/lib/intel/jobs.ts`

```ts
// Analysis job scheduling, same claim pattern as workflow schedules (lib/workflow/schedule.ts):
// a unique (jobId, scheduledFor) slot dedupes racing tick pokes, nextRunAt advances in the SAME
// transaction as the claim, and a job that keeps failing disables itself. analysis_job is a
// separate table because workflow_schedule requires a workflow (spec §2.4 I1).
import { and, eq, inArray, lt, lte } from "drizzle-orm";
import type { db as Db } from "@/db";
import { analysisJobs, analysisRuns } from "@/db/schema";
import { nextRunInTimeZone } from "./time";

export const MAX_CONSECUTIVE_ERRORS = 3;
const MAX_RUNS_PER_TICK = 5;

export type RunPipeline = (businessProjectId: string, opts: { runId: string; now: Date }) => Promise<unknown>;

export interface ClaimedRun {
  id: string;
  jobId: string | null;
  businessProjectId: string;
}

const floorMinute = (d: Date): Date => new Date(Math.floor(d.getTime() / 60_000) * 60_000);
const errText = (e: unknown): string => (e instanceof Error ? e.message : String(e)).slice(0, 1000);

export async function claimDueAnalysisJobs(db: typeof Db, now: Date): Promise<string[]> {
  const due = await db
    .select()
    .from(analysisJobs)
    .where(and(eq(analysisJobs.enabled, true), lte(analysisJobs.nextRunAt, now)));
  const claimed: string[] = [];
  for (const job of due) {
    if (!job.nextRunAt) continue;
    try {
      const scheduledFor = floorMinute(job.nextRunAt); // stored slot, not `now`: racing pokes agree
      const next = nextRunInTimeZone(job.cron, now, job.timezone); // strictly > now, no catch-up burst
      await db.transaction(async (tx) => {
        const runId = crypto.randomUUID();
        const ins = await tx
          .insert(analysisRuns)
          .values({ id: runId, jobId: job.id, businessProjectId: job.businessProjectId, trigger: "schedule", status: "queued", scheduledFor })
          .onConflictDoNothing({ target: [analysisRuns.jobId, analysisRuns.scheduledFor] })
          .returning({ id: analysisRuns.id });
        await tx.update(analysisJobs).set({ nextRunAt: next, lastRunAt: now, updatedAt: now }).where(eq(analysisJobs.id, job.id));
        if (ins.length > 0) claimed.push(runId);
      });
    } catch (err) {
      // Isolate one bad job from its siblings; disable it so it is not re-selected every tick.
      console.error(`[intel] analysis job ${job.id} claim failed -> auto-disable`, err);
      try {
        await db.update(analysisJobs).set({ enabled: false, lastError: errText(err), updatedAt: now }).where(eq(analysisJobs.id, job.id));
      } catch (disableErr) {
        console.error(`[intel] analysis job ${job.id} auto-disable also failed`, disableErr);
      }
    }
  }
  return claimed;
}

export async function claimQueuedAnalysisRuns(db: typeof Db, now: Date, limit: number = MAX_RUNS_PER_TICK): Promise<ClaimedRun[]> {
  // Atomic and bounded inside the UPDATE (same as tickResume): concurrent pokes skip locked rows.
  const sub = db
    .select({ id: analysisRuns.id })
    .from(analysisRuns)
    .where(eq(analysisRuns.status, "queued"))
    .limit(limit)
    .for("update", { skipLocked: true });
  return (await db
    .update(analysisRuns)
    .set({ status: "running", startedAt: now })
    .where(inArray(analysisRuns.id, sub))
    .returning({ id: analysisRuns.id, jobId: analysisRuns.jobId, businessProjectId: analysisRuns.businessProjectId })) as ClaimedRun[];
}

export async function executeAnalysisRun(
  db: typeof Db,
  run: ClaimedRun,
  deps: { runPipeline: RunPipeline; now: Date },
): Promise<"succeeded" | "failed"> {
  try {
    const summary = await deps.runPipeline(run.businessProjectId, { runId: run.id, now: deps.now });
    await db.update(analysisRuns).set({ status: "succeeded", finishedAt: new Date(), summary }).where(eq(analysisRuns.id, run.id));
    if (run.jobId) {
      await db.update(analysisJobs).set({ consecutiveErrors: 0, lastError: null, updatedAt: new Date() }).where(eq(analysisJobs.id, run.jobId));
    }
    return "succeeded";
  } catch (err) {
    const message = errText(err);
    console.error(`[intel] analysis run ${run.id} failed`, err);
    await db.update(analysisRuns).set({ status: "failed", finishedAt: new Date(), error: message }).where(eq(analysisRuns.id, run.id));
    if (run.jobId) await recordJobFailure(db, run.jobId, message);
    return "failed";
  }
}

/** Count one failure on a job; MAX_CONSECUTIVE_ERRORS in a row disables it. */
export async function recordJobFailure(db: typeof Db, jobId: string, message: string): Promise<void> {
  const [job] = await db
    .select({ consecutiveErrors: analysisJobs.consecutiveErrors, enabled: analysisJobs.enabled })
    .from(analysisJobs)
    .where(eq(analysisJobs.id, jobId))
    .limit(1);
  if (!job) return;
  const n = job.consecutiveErrors + 1;
  await db
    .update(analysisJobs)
    .set({ consecutiveErrors: n, lastError: message, enabled: job.enabled && n < MAX_CONSECUTIVE_ERRORS, updatedAt: new Date() })
    .where(eq(analysisJobs.id, jobId));
}

/** Minutes after which a `running` run is considered dead (process crash / restart). */
export function staleRunMinutes(): number {
  const v = Number(process.env.INTEL_RUN_STALE_MINUTES);
  return Number.isFinite(v) && v > 0 ? v : 60;
}

/**
 * Fail runs stuck in `running` for longer than `staleMinutes` (the process died mid-run; there is
 * no resume for analysis — the next slot recomputes everything) and count the error on their job.
 */
export async function failStaleRuns(db: typeof Db, now: Date, staleMinutes: number): Promise<number> {
  const cutoff = new Date(now.getTime() - staleMinutes * 60_000);
  const message = `stale: still running after ${staleMinutes} minutes`;
  const stale = (await db
    .update(analysisRuns)
    .set({ status: "failed", finishedAt: now, error: message })
    .where(and(eq(analysisRuns.status, "running"), lt(analysisRuns.startedAt, cutoff)))
    .returning({ id: analysisRuns.id, jobId: analysisRuns.jobId })) as { id: string; jobId: string | null }[];
  for (const r of stale) if (r.jobId) await recordJobFailure(db, r.jobId, message);
  return stale.length;
}

export async function tickAnalysis(
  db: typeof Db,
  now: Date,
  deps: { runPipeline: RunPipeline; staleMinutes?: number },
): Promise<{ claimed: number; executed: number; failed: number; stale: number }> {
  const stale = await failStaleRuns(db, now, deps.staleMinutes ?? staleRunMinutes());
  const claimed = await claimDueAnalysisJobs(db, now);
  const runs = await claimQueuedAnalysisRuns(db, now);
  let failed = 0;
  for (const run of runs) {
    if ((await executeAnalysisRun(db, run, { runPipeline: deps.runPipeline, now })) === "failed") failed++;
  }
  return { claimed: claimed.length, executed: runs.length, failed, stale };
}
```

- [ ] **Step 5: Implement** — `LAAM/src/lib/intel/run-project.ts`

```ts
// Production wiring for one analysis run: DB + provider (system scope, owner identity) + packs
// enabled at the metrics source + Drizzle repo.
import { eq } from "drizzle-orm";
import { db } from "@/db";
import { businessProjects } from "@/db/schema";
import { loadPacks, packsDir } from "./pack/loader";
import { runAnalysis, type AnalysisSummary } from "./pipeline";
import { providerForProject } from "./provider/factory";
import { drizzleRepo } from "./store/repo";

export async function runAnalysisForProject(businessProjectId: string, opts: { runId: string; now: Date }): Promise<AnalysisSummary> {
  const [bp] = await db.select().from(businessProjects).where(eq(businessProjects.id, businessProjectId)).limit(1);
  if (!bp) throw new Error(`business project ${businessProjectId} not found`);
  const provider = await providerForProject(bp, { mode: "system" });
  // The metrics source owns which packs are installed (spec §5.3); LAAM keeps no copy.
  const { packs: installed } = await provider.listMetrics();
  if (installed.length === 0) throw new Error("the metrics source reports no enabled packs for this project");
  const pack = await loadPacks(packsDir(), installed.map((p) => p.key));
  const summary = await runAnalysis({
    provider,
    pack,
    repo: drizzleRepo(db),
    projectId: bp.id,
    runId: opts.runId,
    now: opts.now,
    timeZone: bp.timezone,
    asOf: bp.asOfOverride ?? undefined,
  });
  for (const p of installed) {
    const local = pack.packs.find((x) => x.key === p.key);
    if (local && local.version !== p.version) {
      summary.warnings.push(`pack_version_mismatch:${p.key}: source=${p.version} laam=${local.version}`);
    }
  }
  return summary;
}
```

- [ ] **Step 6: Sửa route tick** — `LAAM/src/app/api/workflows/tick/route.ts` (thay toàn bộ file)

```ts
import { NextResponse } from "next/server";
import { db } from "@/db";
import { publish } from "@/lib/events-bus";
import { tickClaim, tickExecute, tickResume } from "@/lib/workflow/schedule";
import { buildRunNode } from "@/lib/workflow/runtime";
import { isTickAuthorized } from "@/lib/workflow/tick-auth";
import { notifyWorkflowTerminal } from "@/lib/notifications";
import { tickAnalysis } from "@/lib/intel/jobs";
import { runAnalysisForProject } from "@/lib/intel/run-project";

// POST /api/workflows/tick — máy gọi (Windows Task poke mỗi phút). KHÔNG session:
// auth = localhost HOẶC x-workflow-tick-secret === WORKFLOW_TICK_SECRET. Claim
// (atomic) các schedule due rồi execute các run queued. now = giờ server.
export async function POST(req: Request) {
  if (!isTickAuthorized(req.headers, { WORKFLOW_TICK_SECRET: process.env.WORKFLOW_TICK_SECRET })) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const now = new Date();
  const claimed = await tickClaim(db, now);
  // Execute SAU claim (pha tách rời, PIN-D1): chạy run queued (gồm vừa claim).
  const executed = await tickExecute(db, { db, publish, buildRunNode, notify: notifyWorkflowTerminal });
  // Resume any runs orphaned by a crash (boot sweep marked them 'resumable').
  const resumed = await tickResume(db, { publish, buildRunNode, notify: notifyWorkflowTerminal });
  // Proactive analysis jobs share this poke. Isolated so an intel failure never breaks workflows.
  let analysis: { claimed: number; executed: number; failed: number; stale: number } | { error: string };
  try {
    analysis = await tickAnalysis(db, now, { runPipeline: runAnalysisForProject });
  } catch (err) {
    console.error("[intel] analysis tick failed", err);
    analysis = { error: err instanceof Error ? err.message : String(err) };
  }
  return NextResponse.json({ ok: true, claimed: claimed.length, executed, resumed, analysis });
}
```

- [ ] **Step 7: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/jobs.test.ts src/lib/intel/run-project.test.ts src/lib/workflow/schedule.test.ts
```
Expected: PASS (jobs 9, run-project 2; `schedule.test.ts` không đổi kết quả).

- [ ] **Step 8: Kiểm tra route tick bằng tay (dev server đang chạy, chưa có job nào)**

```bash
cd LAAM && curl -s -X POST -H "x-workflow-tick-secret: $WORKFLOW_TICK_SECRET" http://localhost:3100/api/workflows/tick
```
Expected: JSON có thêm `"analysis":{"claimed":0,"executed":0,"failed":0,"stale":0}`. (Header là `x-workflow-tick-secret` theo `tick-auth.ts:46` — **không phải** `Authorization: Bearer` như bản nháp sidecar của master M2; xem Open questions.)

- [ ] **Step 9: Commit**

```bash
git -C LAAM add src/lib/intel/jobs.ts src/lib/intel/jobs.test.ts src/lib/intel/run-project.ts src/lib/intel/run-project.test.ts src/app/api/workflows/tick/route.ts
git -C LAAM commit -m "feat(intel): schedule analysis jobs through the workflow tick with slot dedupe and auto-disable"
```

---

### Task 19: `POST /api/intel/analysis/run` (admin, chạy tay)

**Files:**
- Create: `LAAM/src/app/api/intel/analysis/run/route.ts`, `LAAM/src/app/api/intel/analysis/run/route.test.ts`

**Interfaces:**
- Consumes: `auth` (`@/auth`), `requireRole` (`lib/auth/rbac.ts:19`), `businessProjects`, `analysisRuns`, `auditLog` (schema), `executeAnalysisRun` (Task 18), `runAnalysisForProject` (Task 18).
- Produces: `POST /api/intel/analysis/run` body `{ "businessProjectId": string }` → `200 { runId, status: "succeeded", error: null, summary }` | `500 { runId, status: "failed", error, summary: null }` | `400` body sai | `401` chưa đăng nhập | `403` không phải owner/admin | `404` không có project. Ghi `audit_log` action `intel.analysis.run`. Chạy **đồng bộ** (demo bấm và chờ); run tạo với `status: "running"` nên tick không nhặt lại; finding không trùng với run theo lịch nhờ unique `finding_project_dedupe` (Task 1/16).

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/app/api/intel/analysis/run/route.test.ts`

```ts
import { afterEach, describe, expect, test, vi } from "vitest";

const h = vi.hoisted(() => ({
  session: null as { user?: { id: string; role: string } } | null,
  project: [] as unknown[],
  runRow: [] as unknown[],
  inserts: [] as { table: string; values: Record<string, unknown> }[],
  execute: vi.fn(),
}));
const NAME = Symbol.for("drizzle:Name");
vi.mock("@/auth", () => ({ auth: vi.fn(async () => h.session) }));
vi.mock("@/db", () => ({
  db: {
    select: () => ({ from: (t: Record<symbol, string>) => ({ where: () => ({ limit: async () => (t[NAME] === "business_project" ? h.project : h.runRow) }) }) }),
    insert: (t: Record<symbol, string>) => ({ values: async (v: Record<string, unknown>) => { h.inserts.push({ table: t[NAME], values: v }); } }),
  },
}));
vi.mock("@/lib/intel/jobs", () => ({ executeAnalysisRun: h.execute }));
vi.mock("@/lib/intel/run-project", () => ({ runAnalysisForProject: vi.fn() }));

import { POST } from "./route";

const req = (body: unknown) => new Request("http://x/api/intel/analysis/run", { method: "POST", body: JSON.stringify(body) });

afterEach(() => {
  h.session = null; h.project = []; h.runRow = []; h.inserts = []; h.execute.mockReset();
});

describe("POST /api/intel/analysis/run", () => {
  test("401 without a session, 403 for non-admins", async () => {
    expect((await POST(req({ businessProjectId: "bp1" }))).status).toBe(401);
    h.session = { user: { id: "u1", role: "member" } };
    expect((await POST(req({ businessProjectId: "bp1" }))).status).toBe(403);
    expect(h.execute).not.toHaveBeenCalled();
  });

  test("400 on a bad body, 404 for an unknown project", async () => {
    h.session = { user: { id: "u1", role: "admin" } };
    expect((await POST(req({}))).status).toBe(400);
    expect((await POST(req({ businessProjectId: "nope" }))).status).toBe(404);
  });

  test("runs the analysis now, audits it and returns the summary", async () => {
    h.session = { user: { id: "u1", role: "owner" } };
    h.project = [{ id: "bp1" }];
    h.execute.mockResolvedValue("succeeded");
    h.runRow = [{ status: "succeeded", error: null, summary: { findings: { inserted: 3 } } }];
    const res = await POST(req({ businessProjectId: "bp1" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toMatchObject({ status: "succeeded", summary: { findings: { inserted: 3 } } });
    const run = h.inserts.find((i) => i.table === "analysis_run")!;
    expect(run.values).toMatchObject({ businessProjectId: "bp1", trigger: "manual", status: "running", jobId: null });
    expect(h.inserts.find((i) => i.table === "audit_log")!.values).toMatchObject({ userId: "u1", action: "intel.analysis.run", target: "bp1" });
    expect(h.execute.mock.calls[0][1]).toEqual({ id: body.runId, jobId: null, businessProjectId: "bp1" });
  });

  test("a failed analysis is a 500 with the error", async () => {
    h.session = { user: { id: "u1", role: "admin" } };
    h.project = [{ id: "bp1" }];
    h.execute.mockResolvedValue("failed");
    h.runRow = [{ status: "failed", error: "source down", summary: null }];
    const res = await POST(req({ businessProjectId: "bp1" }));
    expect(res.status).toBe(500);
    expect(await res.json()).toMatchObject({ status: "failed", error: "source down" });
  });
});
```

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/app/api/intel/analysis/run/route.test.ts
```
Expected: FAIL — `Cannot find module './route'`.

- [ ] **Step 3: Implement** — `LAAM/src/app/api/intel/analysis/run/route.ts`

```ts
import { NextResponse } from "next/server";
import { eq } from "drizzle-orm";
import { z } from "zod";
import { auth } from "@/auth";
import { db } from "@/db";
import { analysisRuns, auditLog, businessProjects } from "@/db/schema";
import { requireRole } from "@/lib/auth/rbac";
import { executeAnalysisRun } from "@/lib/intel/jobs";
import { runAnalysisForProject } from "@/lib/intel/run-project";

// Manual analysis run (owner/admin) — the demo's "run now" and master Task M5 step 2.
// Synchronous on purpose: the caller waits for the summary. The run row starts as "running" so
// the tick never picks it up; findings stay unique per (project, dedupeKey) even if a scheduled
// run overlaps.
const bodySchema = z.strictObject({ businessProjectId: z.string().min(1) });

export async function POST(req: Request) {
  const session = await auth();
  const gate = requireRole(session, ["owner", "admin"]);
  if (gate instanceof Response) return gate;

  const parsed = bodySchema.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "Tham số không hợp lệ" }, { status: 400 });

  const [bp] = await db
    .select({ id: businessProjects.id })
    .from(businessProjects)
    .where(eq(businessProjects.id, parsed.data.businessProjectId))
    .limit(1);
  if (!bp) return NextResponse.json({ error: "Không tìm thấy dự án" }, { status: 404 });

  const runId = crypto.randomUUID();
  const now = new Date();
  await db.insert(analysisRuns).values({ id: runId, jobId: null, businessProjectId: bp.id, trigger: "manual", status: "running", startedAt: now });
  await db.insert(auditLog).values({ userId: session?.user?.id ?? null, action: "intel.analysis.run", target: bp.id });

  const status = await executeAnalysisRun(db, { id: runId, jobId: null, businessProjectId: bp.id }, { runPipeline: runAnalysisForProject, now });
  const [row] = await db
    .select({ status: analysisRuns.status, error: analysisRuns.error, summary: analysisRuns.summary })
    .from(analysisRuns)
    .where(eq(analysisRuns.id, runId))
    .limit(1);
  return NextResponse.json(
    { runId, status, error: row?.error ?? null, summary: row?.summary ?? null },
    { status: status === "succeeded" ? 200 : 500 },
  );
}
```

- [ ] **Step 4: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/app/api/intel/analysis/run/route.test.ts
```
Expected: PASS 4/4.

- [ ] **Step 5: Commit**

```bash
git -C LAAM add src/app/api/intel
git -C LAAM commit -m "feat(intel): admin endpoint to run an analysis on demand"
```

(Kiểm tra end-to-end trên DB dev của endpoint này nằm ở Task 23 Step 2 — cần seed Task 20 và packs Task 21–22.)

---

### Task 20: Seed demo (`business_project`, `user_scope`, `analysis_job`) + chạy giả lập tuỳ chọn

**Files:**
- Create: `LAAM/scripts/seed-intel-demo.ts`, `LAAM/scripts/intel-demo-fixture.ts`

**Interfaces:**
- Consumes: bảng Task 1; `nextRunInTimeZone` (Task 7); `bcryptjs` (đã có, `register/route.ts:63` dùng cost 12); với `--fake-run`: `FakeMetricsProvider` (Task 3), `loadPacks/packsDir` (Task 6), `runAnalysis` (Task 17), `drizzleRepo` (Task 16).
- Produces (master M5 Step 1 dùng): lệnh
```bash
cd LAAM && PACKS_DIR=../packs SEED_OWNER_EMAIL=<owner có MCP DAAB> SEED_MCP_SLUG=daab \
  SEED_EXEC_EMAIL=johnny@demo.local SEED_EXEC_PASSWORD=<…> \
  SEED_MANAGER_EMAIL=ph002.manager@demo.local SEED_MANAGER_PASSWORD=<…> \
  node --env-file=.env node_modules/.bin/tsx scripts/seed-intel-demo.ts [--fake-run]
```
tạo/cập nhật (idempotent): `business_project` id **`bp-pharmacy-chain-demo`** (DAAB project `4ad7a5fa-a036-4f6a-8229-39a20af23e38`, `America/Chicago`, locale `en`, `asOfOverride = 2026-07-31` — ngày dữ liệu cuối của Plan A, khớp `kg-packs set-as-of --date 2026-07-31` phía DAAB; override thắng `as_of` của provider); user **Johnny** (`persona executive`, mọi chi nhánh) và **quản lý PH-002** (`store_manager`, `["PH-002"]`) — tạo user nếu chưa có (role `member`), owner cũng được `executive`; `analysis_job` hằng ngày `0 6 * * *` theo `America/Chicago`. `--fake-run` ghi một lần phân tích trên dữ liệu **tổng hợp** vào project riêng **`bp-demo-synthetic`** (không lẫn với project thật) để Plan E dựng UI khi DAAB chưa sẵn.

- [ ] **Step 1: Tạo fixture tổng hợp** — `LAAM/scripts/intel-demo-fixture.ts`

```ts
// Synthetic, deterministic metric data for an offline demo run (seed-intel-demo.ts --fake-run)
// when DAAB's metric tools are not available. Not ground truth: Plan A's pharmacy_demo through
// DAAB is the real demo path. Metrics not listed here are absent, so their rules are reported
// as metric_unknown — that is intended.
import type { FakeMetricData } from "../src/lib/intel/provider/fake";
import type { DataStatusItem, MetricCatalogItem, MetricPoint } from "../src/lib/intel/provider/types";

const LOCATIONS = ["PH-001", "PH-002", "PH-003", "PH-004", "PH-005"];
const CATEGORIES = ["otc", "personal_care", "grocery"];
const PRODUCTS = ["PRD-00067", "PRD-00030", "PRD-00057", "PRD-00316", "PRD-00324", "PRD-00100"];
const PLANT_DRUGS = PRODUCTS.slice(0, 5);
const WEEKDAY = [1.0, 0.9, 0.95, 1.0, 1.1, 1.25, 1.15]; // Sun..Sat
const employees = (loc: string): string[] => [1, 2, 3, 4].map((i) => `${loc}-E${i}`);

interface Plant { match: Record<string, string>; from: string; factor: number; productIn?: string[] }
interface Spec {
  key: string;
  aggregation: "additive" | "ratio" | "snapshot";
  unit: string;
  dims: string[];
  grain?: "day" | "month";
  base: number; // additive: value per day; ratio: rate in percent; snapshot(month): value
  plants?: Plant[];
}

const SALES_DIP: Plant = { match: { location_id: "PH-004" }, from: "2026-07-01", factor: 0.6 };
const SPECS: Spec[] = [
  { key: "retail.net_sales", aggregation: "additive", unit: "currency", dims: ["location_id", "category"], base: 1000, plants: [SALES_DIP] },
  { key: "retail.cogs", aggregation: "additive", unit: "currency", dims: ["location_id", "category"], base: 650, plants: [SALES_DIP] },
  { key: "retail.gross_margin_pct", aggregation: "ratio", unit: "percent", dims: ["location_id", "category"], base: 35 },
  { key: "retail.target_net_sales", aggregation: "snapshot", unit: "currency", dims: ["location_id"], grain: "month", base: 90000 },
  { key: "retail.target_gross_margin_pct", aggregation: "snapshot", unit: "percent", dims: ["location_id"], grain: "month", base: 34.5 },
  { key: "retail.refund_rate", aggregation: "ratio", unit: "percent", dims: ["location_id", "employee_id"], base: 3, plants: [{ match: { employee_id: "PH-001-E2" }, from: "2026-05-01", factor: 4 }] },
  { key: "retail.cash_shortage_count", aggregation: "additive", unit: "count", dims: ["location_id", "employee_id"], base: 0.02, plants: [{ match: { employee_id: "PH-005-E3" }, from: "2026-07-01", factor: 50 }] },
  { key: "pharmacy.claim_rejection_rate", aggregation: "ratio", unit: "percent", dims: ["location_id"], base: 5, plants: [{ match: { location_id: "PH-004" }, from: "2026-05-01", factor: 3.1 }] },
  { key: "pharmacy.rx_revenue", aggregation: "additive", unit: "currency", dims: ["location_id", "product_id"], base: 200 },
  { key: "pharmacy.rx_cost", aggregation: "additive", unit: "currency", dims: ["location_id", "product_id"], base: 160, plants: [{ match: { location_id: "PH-003" }, from: "2026-07-18", factor: 1.08, productIn: PLANT_DRUGS }] },
  { key: "pharmacy.rx_margin_pct", aggregation: "ratio", unit: "percent", dims: ["location_id", "product_id"], base: 20, plants: [{ match: { location_id: "PH-003" }, from: "2026-07-18", factor: 0.6, productIn: PLANT_DRUGS }] },
];

function addDays(date: string, n: number): string {
  const d = new Date(date + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function lcg(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function combos(dims: readonly string[]): Record<string, string>[] {
  return LOCATIONS.flatMap((loc) => {
    if (dims.includes("employee_id")) return employees(loc).map((e) => ({ location_id: loc, employee_id: e }));
    if (dims.includes("category")) return CATEGORIES.map((c) => ({ location_id: loc, category: c }));
    if (dims.includes("product_id")) return PRODUCTS.map((p) => ({ location_id: loc, product_id: p }));
    return [{ location_id: loc }];
  });
}

function plantFactor(spec: Spec, dims: Record<string, string>, day: string): number {
  let f = 1;
  for (const p of spec.plants ?? []) {
    if (day < p.from) continue;
    if (!Object.entries(p.match).every(([k, v]) => dims[k] === v)) continue;
    if (p.productIn && !p.productIn.includes(dims.product_id)) continue;
    f *= p.factor;
  }
  return f;
}

export function buildDemoFixture(asOf: string, days = 400): FakeMetricData {
  const rand = lcg(20261002);
  const start = addDays(asOf, -(days - 1));
  const catalog: MetricCatalogItem[] = SPECS.map((s) => ({
    key: s.key, unit: s.unit, aggregation: s.aggregation, grain: s.grain ?? "day", dims: s.dims,
    requires: [], enabled: true, disabledReason: null,
  }));
  const points: Record<string, MetricPoint[]> = {};
  for (const s of SPECS) {
    const out: MetricPoint[] = [];
    for (const dims of combos(s.dims)) {
      if (s.grain === "month") {
        for (let m = start.slice(0, 7) + "-01"; m <= asOf; m = addDays(m, 32).slice(0, 7) + "-01") {
          out.push({ period: m, dims, value: s.base, numerator: null, denominator: null, sampleSize: 1 });
        }
        continue;
      }
      for (let i = 0; i < days; i++) {
        const day = addDays(start, i);
        const shape = WEEKDAY[new Date(day + "T00:00:00Z").getUTCDay()];
        const noise = 1 + (rand() - 0.5) * 0.1;
        const f = plantFactor(s, dims, day);
        if (s.aggregation === "ratio") {
          const den = 1000 * shape * noise;
          const num = den * (s.base / 100) * f;
          out.push({ period: day, dims, value: (100 * num) / den, numerator: num, denominator: den, sampleSize: 20 });
        } else {
          out.push({ period: day, dims, value: s.base * shape * noise * f, numerator: null, denominator: null, sampleSize: 20 });
        }
      }
    }
    points[s.key] = out;
  }
  const dataStatus: DataStatusItem[] = catalog.map((c) => ({ subject: `metric:${c.key}`, status: "current", lastSuccessAt: `${asOf}T23:00:00Z`, issues: [] }));
  return { catalog, packs: [{ key: "retail", version: "0.1.0" }, { key: "pharmacy", version: "0.1.0" }], points, dataStatus };
}
```

- [ ] **Step 2: Tạo seed script** — `LAAM/scripts/seed-intel-demo.ts`

```ts
// Seeds the proactive-intelligence demo (master plan Task M5 step 1): business project, user
// scopes (Johnny = executive / all stores, PH-002 manager = store_manager / PH-002) and the daily
// analysis job. Idempotent. Run on the host after `npm run db:migrate`:
//   PACKS_DIR=../packs SEED_OWNER_EMAIL=... SEED_EXEC_EMAIL=... SEED_EXEC_PASSWORD=... \
//   SEED_MANAGER_EMAIL=... SEED_MANAGER_PASSWORD=... node --env-file=.env node_modules/.bin/tsx scripts/seed-intel-demo.ts [--fake-run]
// --fake-run additionally writes one analysis over SYNTHETIC data into a separate project
// (bp-demo-synthetic) so UI work can start before DAAB's metric tools exist.
// `npx tsx` does not load .env and src/db/index.ts silently falls back to localhost:5432 (a
// different database). dotenv/config is imported FIRST (ESM evaluates imports in order) as a second
// guard to `node --env-file=.env`, and main() refuses to run without DATABASE_URL.
import "dotenv/config";
import bcrypt from "bcryptjs";
import { and, eq } from "drizzle-orm";
import { db } from "../src/db/index";
import { analysisJobs, analysisRuns, businessProjects, userScopes, users } from "../src/db/schema";
import { nextRunInTimeZone } from "../src/lib/intel/time";
import { FakeMetricsProvider } from "../src/lib/intel/provider/fake";
import { loadPacks, packsDir } from "../src/lib/intel/pack/loader";
import { runAnalysis } from "../src/lib/intel/pipeline";
import { drizzleRepo } from "../src/lib/intel/store/repo";
import { buildDemoFixture } from "./intel-demo-fixture";

const BP_ID = "bp-pharmacy-chain-demo";
const BP_SYNTHETIC_ID = "bp-demo-synthetic";
const DAAB_PROJECT_ID = "4ad7a5fa-a036-4f6a-8229-39a20af23e38";
const TIME_ZONE = "America/Chicago";
const DAILY_CRON = "0 6 * * *";
// Last day of Plan A's demo data (inclusive). Must match the DAAB side:
//   kg-packs set-as-of --project 4ad7a5fa-a036-4f6a-8229-39a20af23e38 --date 2026-07-31
const DEMO_AS_OF = "2026-07-31";

function env(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`missing env ${name}`);
  return v;
}

async function ensureUser(email: string, name: string, password: string | undefined): Promise<string> {
  const [found] = await db.select({ id: users.id }).from(users).where(eq(users.email, email)).limit(1);
  if (found) return found.id;
  if (!password) throw new Error(`user ${email} does not exist and no password was given to create it`);
  const [created] = await db
    .insert(users)
    .values({ email, name, passwordHash: await bcrypt.hash(password, 12), role: "member" })
    .returning({ id: users.id });
  return created.id;
}

async function upsertProject(id: string, name: string, ownerUserId: string, slug: string): Promise<void> {
  const values = {
    id, name, metricsProvider: "daab", daabProjectId: DAAB_PROJECT_ID, mcpConnectorSlug: slug, ownerUserId,
    timezone: TIME_ZONE, localeDefault: "en", asOfOverride: DEMO_AS_OF, updatedAt: new Date(),
  };
  await db.insert(businessProjects).values(values).onConflictDoUpdate({ target: businessProjects.id, set: values });
}

async function upsertScope(businessProjectId: string, userId: string, persona: string, locationIds: string[]): Promise<void> {
  await db
    .insert(userScopes)
    .values({ businessProjectId, userId, persona, locationIds })
    .onConflictDoUpdate({ target: [userScopes.businessProjectId, userScopes.userId], set: { persona, locationIds, updatedAt: new Date() } });
}

async function ensureDailyJob(businessProjectId: string): Promise<void> {
  const [job] = await db
    .select({ id: analysisJobs.id })
    .from(analysisJobs)
    .where(and(eq(analysisJobs.businessProjectId, businessProjectId), eq(analysisJobs.kind, "daily")))
    .limit(1);
  if (job) return;
  await db.insert(analysisJobs).values({
    businessProjectId, kind: "daily", cron: DAILY_CRON, timezone: TIME_ZONE,
    nextRunAt: nextRunInTimeZone(DAILY_CRON, new Date(), TIME_ZONE), enabled: true,
  });
}

async function fakeRun(): Promise<void> {
  const pack = await loadPacks(packsDir(), ["pharmacy"]);
  const runId = crypto.randomUUID();
  const now = new Date();
  await db.insert(analysisRuns).values({ id: runId, businessProjectId: BP_SYNTHETIC_ID, trigger: "manual", status: "running", startedAt: now });
  const summary = await runAnalysis({
    provider: new FakeMetricsProvider(buildDemoFixture(DEMO_AS_OF)),
    pack, repo: drizzleRepo(db), projectId: BP_SYNTHETIC_ID, runId, now, timeZone: TIME_ZONE, asOf: DEMO_AS_OF,
  });
  await db.update(analysisRuns).set({ status: "succeeded", finishedAt: new Date(), summary }).where(eq(analysisRuns.id, runId));
  console.log("synthetic run", runId, JSON.stringify(summary.findings), "skipped:", summary.rules.skipped.length);
}

async function main(): Promise<void> {
  if (!process.env.DATABASE_URL) throw new Error("DATABASE_URL is not set — run with node --env-file=.env (see header)");
  const slug = process.env.SEED_MCP_SLUG ?? "daab";
  const [owner] = await db.select({ id: users.id }).from(users).where(eq(users.email, env("SEED_OWNER_EMAIL"))).limit(1);
  if (!owner) throw new Error("SEED_OWNER_EMAIL must be an existing LAAM user with the DAAB MCP server configured");
  const johnny = await ensureUser(env("SEED_EXEC_EMAIL"), "Johnny", process.env.SEED_EXEC_PASSWORD);
  const manager = await ensureUser(env("SEED_MANAGER_EMAIL"), "PH-002 Store Manager", process.env.SEED_MANAGER_PASSWORD);

  const projects: [string, string][] = [[BP_ID, "Pharmacy Chain (demo)"]];
  if (process.argv.includes("--fake-run")) projects.push([BP_SYNTHETIC_ID, "Pharmacy Chain (synthetic data)"]);
  for (const [id, name] of projects) {
    await upsertProject(id, name, owner.id, slug);
    await upsertScope(id, owner.id, "executive", []);
    await upsertScope(id, johnny, "executive", []);
    await upsertScope(id, manager, "store_manager", ["PH-002"]);
  }
  await ensureDailyJob(BP_ID); // the synthetic project never runs on a schedule
  console.log(`seeded ${BP_ID} (owner ${owner.id}, johnny ${johnny}, ph-002 manager ${manager})`);
  if (process.argv.includes("--fake-run")) await fakeRun();
}

main().then(
  () => process.exit(0),
  (err) => {
    console.error(err);
    process.exit(1);
  },
);
```

- [ ] **Step 3: Typecheck hai script** (chạy thật ở Task 23 Step 1, sau khi có packs Task 21–22)

```bash
cd LAAM && npx tsc --noEmit -p . 2>&1 | grep -E "scripts/(seed-intel-demo|intel-demo-fixture)" ; echo "scripts-tsc-matches:$?"
```
Expected: `scripts-tsc-matches:1` (không có lỗi TS trong hai file).

- [ ] **Step 4: Commit**

```bash
git -C LAAM add scripts/seed-intel-demo.ts scripts/intel-demo-fixture.ts
git -C LAAM commit -m "feat(intel): demo seed for business project, scopes, daily job and synthetic run"
```

---

### Task 21: Nội dung pack `packs/retail/laam`

**Files:**
- Create: `packs/retail/laam/rules.yaml`, `forecasts.yaml`, `scenarios.yaml`, `glossary.yaml`, `roles.yaml`, `scoring.yaml`
- **Phụ thuộc BẮT BUỘC: master Task M1 phải xong trước** (`packs/retail/pack.yaml`, `packs/pharmacy/pack.yaml`). Thiếu `pack.yaml` ⇒ loader báo "pack not found" và toàn bộ `packs-content.test.ts` (14 test) fail — đó là lỗi thứ tự thực hiện, không phải lỗi pack. Nếu M1 chưa làm: tạo đúng nội dung M1 Step 1–2 rồi mới tiếp.

**Interfaces:**
- Consumes: định dạng Task 6 (master §2.2 + E1–E9); metric key theo bảng "Hợp đồng metric cần từ Plan B".
- Produces: rule set beta (spec §7.3, request Part 3 §23 "Beta 1"), forecast/scenario/glossary/roles/scoring cho retail. Được kiểm bởi `packs-content.test.ts` (Task 22).

Nguồn ngưỡng (request Part 3, đã đọc nguyên văn): RET-SALES-001 (5/10/20%), RET-MARGIN-001 (2/5/10 điểm), RET-MARGIN-002 (3 điểm + công thức impact), RET-INV-001 (≥ $100; ≥ 5 đơn vị cần metric số lượng riêng), RET-INV-003 (critical = đã hết hàng, high = hết trong 7 ngày; warning cần lead time), RET-REF-001 (> 2,5 × peer và ≥ 10 refund), RET-REF-002 (> 20% và ≥ 5 refund), RET-REF-004 (≥ 2 refund cùng giao dịch gốc ⇒ metric đếm nhóm ≥ 1), RET-DISC-002 (> 2,5 × peer và ≥ 20 giao dịch), RET-VOID-001 (> 2,5 × peer; số giao dịch tối thiểu **không có số**), RET-CASH-001 (≤ −$25; ≥ 3 lần thiếu), RET-VENDOR-001 (5/10/20%), severity theo impact §19, trọng số priority §18, Store Health §15. **Không có số:** RET-SALES-006 (ranking tổng hợp 6 chỉ số), RET-DISC-003, RET-CASH-004, RET-LABOR-001, RET-INV-010 ("configured threshold"), RET-LABOR-006 (giờ **dự kiến** vượt ngưỡng tăng ca tuần của khách; metric chỉ có giờ overtime đã ghi).

`window_days` và `cooldown_days` **không** có trong request (request chỉ nêu "comparison_period"/"cooldown_period" là trường bắt buộc): file ghi giá trị cấu hình ban đầu (cooldown 7; cửa sổ 7/14/30 theo bản chất so sánh) và liệt kê ở Open questions để khách duyệt — chúng không phải ngưỡng kích hoạt.

- [ ] **Step 1: Tạo `packs/retail/laam/rules.yaml`**

```yaml
# Retail Analytics Pack — LAAM rules (request "Retail Analytics Rules", Part 3; spec §7.3 beta set).
# Thresholds are copied from the request. Where the request gives no number, the rule either carries
# a PROVISIONAL demo default (threshold_status: provisional + threshold_note, E11 — decision
# 2026-10-02) or, when the DATA is missing too (RET-LABOR-001/006), no condition => threshold_tbd.
# window_days / cooldown_days are initial configuration (the request gives no values) — confirm
# with the customer; override per project through rule_override.
rules:
  - rule_id: RET-SALES-001
    version: 1
    name: Material sales decline
    metric: retail.net_sales
    dims: [location_id]
    window_days: 30              # ignored for compare: target (month-to-date vs prorated monthly target)
    compare: target              # request: compare with "Customer target" (also 4-week baseline / last year — see open questions)
    target_metric: retail.target_net_sales
    # min_sample: TBD — request: "only trigger when the location meets the minimum transaction volume" (no number)
    condition: "value <= 0.95 * compare_value"
    severity:
      critical: "value <= 0.80 * compare_value"   # decline of 20% or more
      high: "value <= 0.90 * compare_value"       # decline of 10% or more
      warning: "value <= 0.95 * compare_value"    # decline of 5% or more
    impact: "compare_value - value"
    impact_unit: currency
    breakdown: [category]
    scenario_template: retail.sales_change
    # No driver: the gap to target is not a measured change, and no_action already persists the
    # current sales level through the undamped forecast (the driver is never re-applied).
    recommended_action: investigate
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Net sales are materially below target"

  - rule_id: RET-SALES-006
    version: 1
    name: Store ranking change
    metric: retail.net_sales
    dims: [location_id]
    window_days: 7
    compare: peer_average
    # Request ranks stores on 6 measures (net sales growth, gross margin %, target achievement,
    # inventory availability, refund rate, labor %) and alerts on: drop >= 5 positions, entering the
    # bottom 10%, or bottom 20% for 3 consecutive periods. The composite ranking is not built in beta.
    disabled_reason: requires_composite_ranking
    recommended_action: compare
    default_owner_role: regional_manager
    cooldown_days: 7
    wording: "Store ranking changed versus comparable stores"

  - rule_id: RET-MARGIN-001
    version: 1
    name: Margin below target
    metric: retail.gross_margin_pct
    dims: [location_id]
    window_days: 30              # ignored for compare: target
    compare: target
    target_metric: retail.target_gross_margin_pct
    condition: "value <= compare_value - 2"
    severity:
      critical: "value <= compare_value - 10"     # 10 percentage points below target
      high: "value <= compare_value - 5"          # 5 points below
      warning: "value <= compare_value - 2"       # 2 points below
    impact: "denominator * (compare_value - value) / 100"
    impact_unit: currency
    breakdown: [category]
    recommended_action: review
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Gross margin is below target"

  - rule_id: RET-MARGIN-002
    version: 1
    name: Margin deterioration
    metric: retail.gross_margin_pct
    dims: [location_id]
    window_days: 14
    compare: baseline_same_weekday_4w
    # min sales value: TBD — request: "minimum sales value is met" (no number)
    condition: "value <= compare_value - 3"
    impact: "denominator * (compare_value - value) / 100"   # Current Net Sales x (Baseline % - Current %)
    impact_unit: currency
    breakdown: [category]
    companions: [retail.cogs, retail.net_sales]
    recommended_action: review
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Gross margin has deteriorated versus the comparable baseline"

  - rule_id: RET-INV-001
    version: 1
    name: Inventory variance
    metric: retail.inventory_variance_value
    dims: [location_id, product_id]
    window_days: 30
    compare: none
    # Request also triggers on |quantity variance| >= 5 units — needs a quantity metric; value trigger only here.
    condition: "abs(value) >= 100"
    impact: "abs(value)"
    impact_unit: currency
    recommended_action: inventory_count
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Inventory variance requiring a count"

  - rule_id: RET-INV-010
    version: 1
    name: Possible shrink
    metric: retail.inventory_variance_value
    dims: [location_id]
    window_days: 30
    compare: none
    # Request: "variance exceeds the configured value or quantity threshold" — no number given.
    # Provisional demo default: the RET-INV-001 value default ($100) applied to unexplained loss.
    condition: "value <= -100"
    threshold_status: provisional
    threshold_note: "Demo default — not in request; pending customer confirmation"
    impact: "-min(value, 0)"
    impact_unit: currency
    recommended_action: inventory_count
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Possible inventory loss requiring review"

  - rule_id: RET-INV-003
    version: 1
    name: Stockout risk
    metric: retail.days_of_cover
    dims: [location_id, product_id]
    window_days: 1
    compare: none
    # Warning tier ("stockout expected within vendor lead time") needs lead-time data — not included.
    condition: "value <= 7"
    severity:
      critical: "value <= 0"       # already out of stock
      high: "value <= 7"           # stockout expected within seven days
    recommended_action: reorder_review
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Stockout risk — review reorder"

  - rule_id: RET-REF-001
    version: 1
    name: Refund rate concentration
    metric: retail.refund_rate
    dims: [location_id, employee_id]
    window_days: 30
    compare: peer_average
    min_sample: 10                 # at least 10 refunds in the period
    condition: "value > 2.5 * compare_value"
    impact: "numerator - compare_value / 100 * denominator"   # refund value above the peer rate
    impact_unit: currency
    recommended_action: investigate
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Repeated exception pattern requiring management review"

  - rule_id: RET-REF-002
    version: 1
    name: No-receipt refund concentration
    metric: retail.no_receipt_refund_pct
    dims: [location_id, employee_id]
    window_days: 30
    compare: none
    min_sample: 5                  # at least five refund transactions
    condition: "value > 20"
    recommended_action: review
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "High share of refunds without a receipt — management review"

  - rule_id: RET-REF-004
    version: 1
    name: Duplicate refund
    metric: retail.duplicate_refund_groups
    dims: [location_id]
    window_days: 30
    compare: none
    condition: "value >= 1"        # a group = two or more refunds referencing the same original
    recommended_action: investigate
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Possible duplicate refunds — verify whether the original sale supported multiple returns"

  - rule_id: RET-DISC-002
    version: 1
    name: Employee discount concentration
    metric: retail.discount_rate
    dims: [location_id, employee_id]
    window_days: 30
    compare: peer_average
    min_sample: 20                 # at least 20 qualifying sales
    # "total discount impact exceeds the configured minimum" — no number given (TBD).
    condition: "value > 2.5 * compare_value"
    impact: "numerator - compare_value / 100 * denominator"
    impact_unit: currency
    recommended_action: review
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Discounting concentrated on one employee — management review"

  - rule_id: RET-DISC-003
    version: 1
    name: Repeated manual override
    metric: retail.manual_override_count   # approver view (Plan B): a rate cannot carry the approver dim
    dims: [location_id, approver_id]       # FND-004 is the approving manager, not the cashier
    window_days: 30
    compare: peer_average
    # Request: overrides "exceed the configured daily or weekly limit" / "materially exceed peers" — no number.
    # Provisional demo default: 2.5 x peer average (approver_id "" = unknown, excluded by the engine).
    condition: "value > 2.5 * compare_value"
    threshold_status: provisional
    threshold_note: "Demo default — not in request; pending customer confirmation"
    recommended_action: review
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Repeated manual price overrides requiring management review"

  - rule_id: RET-VOID-001
    version: 1
    name: Void-rate anomaly
    metric: retail.void_rate
    dims: [location_id, employee_id]
    window_days: 30
    compare: peer_average
    condition: "value > 2.5 * compare_value"       # from the request
    # Request also requires a minimum transaction count and a minimum voided value — no numbers given.
    # Provisional demo default: at least 50 started transactions (minimum voided value still open).
    min_sample: 50
    threshold_status: provisional
    threshold_note: "Demo default — not in request; pending customer confirmation"
    recommended_action: review
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Void rate well above peers — management review"

  - rule_id: RET-CASH-001
    version: 1
    name: Cash variance
    metric: retail.cash_shortage_count   # Plan B: drawer closes with cash variance <= -$25 (request default)
    dims: [location_id, employee_id]
    window_days: 30                # rolling review period
    compare: none
    condition: "value >= 3"        # three or more shortages in the review period
    # Counted per drawer close (a same-day -$30 and +$10 must not net to -$20). No dollar impact on this
    # metric => severity by request §19 falls back to "low" until a shortage-amount metric exists.
    recommended_action: investigate
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Repeated cash shortages requiring management review"

  - rule_id: RET-CASH-004
    version: 1
    name: Excessive no-sale drawer openings
    metric: retail.no_sale_rate
    dims: [location_id, employee_id]
    window_days: 30
    compare: peer_average
    # Request: compare with peers / history and "require a minimum event count" — no numbers.
    # Provisional demo default: 2.5 x peer average (minimum event count still open).
    condition: "value > 2.5 * compare_value"
    threshold_status: provisional
    threshold_note: "Demo default — not in request; pending customer confirmation"
    recommended_action: review
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "No-sale drawer openings above peers — management review"

  - rule_id: RET-LABOR-006
    version: 1
    name: Overtime risk
    metric: retail.overtime_hours
    dims: [location_id, employee_id]
    window_days: 7
    compare: none
    # Trigger TBD: the request fires when PROJECTED weekly hours exceed the customer's overtime
    # threshold. retail.overtime_hours is overtime already recorded per shift (Plan B), not hours vs
    # that weekly threshold, and scheduled hours are not available — so no condition yet.
    recommended_action: schedule_review
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Overtime this week — review the schedule"

  - rule_id: RET-LABOR-001
    version: 1
    name: Labor-cost percentage
    metric: retail.labor_cost_pct
    dims: [location_id]
    window_days: 30
    compare: previous_period
    # Request lists comparisons (store target, comparable stores, previous period) but no trigger (TBD).
    # DAAB also disables retail.labor_cost_pct until a wage column exists (Plan B).
    recommended_action: schedule_review
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Labor cost share of sales has changed"

  - rule_id: RET-VENDOR-001
    version: 1
    name: Vendor price increase
    metric: retail.avg_unit_cost
    dims: [location_id, product_id]
    window_days: 14
    compare: previous_period
    condition: "value >= 1.05 * compare_value"
    severity:
      critical: "value >= 1.20 * compare_value"   # increase of at least 20%
      high: "value >= 1.10 * compare_value"       # at least 10%
      warning: "value >= 1.05 * compare_value"    # at least 5%
    impact: "(value - compare_value) * denominator"
    impact_unit: currency
    recommended_action: vendor_review
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Vendor unit cost increased — review pricing"

  - rule_id: RET-X-REPRINT-001
    version: 1
    name: Receipt reprint before refund
    metric: retail.reprint_before_refund_count
    dims: [location_id, employee_id]
    window_days: 30
    compare: none
    # Custom rule (not in the request): reprint of the original receipt 1-48h before a refund of the
    # same transaction by the same employee. The metric counts matched pairs.
    condition: "value >= 1"
    recommended_action: investigate
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Receipt reprints before refunds of the same sale — review the matched pairs"
```

- [ ] **Step 2: Tạo `packs/retail/laam/forecasts.yaml`**

```yaml
# Additive metrics only (spec §7.6). Margin is derived from these, never forecast as a rate.
forecasts:
  - metric: retail.net_sales
    dims: [location_id]
    horizons_days: [7, 30]
    season_length: 7
  - metric: retail.cogs
    dims: [location_id]
    horizons_days: [7, 30]
    season_length: 7
```

- [ ] **Step 3: Tạo `packs/retail/laam/scenarios.yaml`**

```yaml
scenarios:
  - key: retail.sales_change
    label: Sales change
    dims: [location_id]
    horizon_days: 30
    base:
      net_sales: { forecast_of: retail.net_sales }
      cogs:      { forecast_of: retail.cogs }
    variables:
      sales_change_pct: { default: 0, min: -30, max: 30 }
    outputs:
      revenue: "net_sales * (1 + sales_change_pct / 100)"
      gross_profit: "(net_sales - cogs) * (1 + sales_change_pct / 100)"
    primary_output: gross_profit
    presets:
      expected:  { trend: damped }
      best:      { trend: damped, set: { sales_change_pct: 10 } }    # RET-SCN-004 default demand increase 10%
      risk:      { trend: damped, set: { sales_change_pct: -5 } }    # RET-SCN-003 sales decline 5%
      no_action: { trend: persist_driver }
```

- [ ] **Step 4: Tạo `packs/retail/laam/glossary.yaml`**

```yaml
terms:
  net_sales:            { en: "Net sales", vi: "Doanh thu thuần" }
  gross_margin:         { en: "Gross margin", vi: "Biên lợi nhuận gộp" }
  target:               { en: "Target", vi: "Mục tiêu" }
  refund_rate:          { en: "Refund rate", vi: "Tỉ lệ hoàn tiền" }
  no_receipt_refund:    { en: "No-receipt refund", vi: "Hoàn tiền không hoá đơn" }
  duplicate_refund:     { en: "Possible duplicate refund", vi: "Có thể hoàn tiền trùng" }
  discount_rate:        { en: "Discount rate", vi: "Tỉ lệ giảm giá" }
  manual_override:      { en: "Manual price override", vi: "Ghi đè giá thủ công" }
  void_rate:            { en: "Void rate", vi: "Tỉ lệ huỷ giao dịch" }
  cash_variance:        { en: "Cash variance", vi: "Chênh lệch tiền mặt" }
  no_sale_opening:      { en: "No-sale drawer opening", vi: "Mở két không bán hàng" }
  inventory_variance:   { en: "Inventory variance", vi: "Chênh lệch tồn kho" }
  possible_shrink:      { en: "Possible inventory loss", vi: "Có thể thất thoát hàng tồn" }
  stockout_risk:        { en: "Stockout risk", vi: "Nguy cơ hết hàng" }
  overtime:             { en: "Overtime", vi: "Làm thêm giờ" }
  labor_cost_pct:       { en: "Labor cost %", vi: "Tỉ lệ chi phí nhân công" }
  vendor_price_increase: { en: "Vendor price increase", vi: "Nhà cung cấp tăng giá" }
  receipt_reprint:      { en: "Receipt reprint", vi: "In lại hoá đơn" }
  store_health_score:   { en: "Store Health Score", vi: "Điểm sức khoẻ cửa hàng" }
  forecast:             { en: "Forecast", vi: "Dự báo" }
  scenario_expected:    { en: "Expected", vi: "Dự kiến" }
  scenario_best:        { en: "Best case", vi: "Thuận lợi" }
  scenario_risk:        { en: "Risk case", vi: "Rủi ro" }
  scenario_no_action:   { en: "No action", vi: "Không hành động" }
```

- [ ] **Step 5: Tạo `packs/retail/laam/roles.yaml`** (persona theo spec OD-6; tối đa 5 finding chính theo request §18)

```yaml
personas:
  executive:        { max_findings: 5, sections: [greeting, data_status, needs_attention, predictions, scenarios, actions] }
  regional_manager: { max_findings: 5, sections: [greeting, data_status, needs_attention, predictions, scenarios, actions] }
  store_manager:    { max_findings: 5, sections: [greeting, data_status, needs_attention, actions] }
  analyst:          { max_findings: 5, sections: [greeting, data_status, needs_attention, predictions, scenarios, actions] }
```

- [ ] **Step 6: Tạo `packs/retail/laam/scoring.yaml`**

```yaml
# Priority weights: request Part 3 §18. Severity by impact: §19. Store Health weights/bands: §15.
# Values marked "engine parameter" are not in the request — initial values, confirm with the customer.
priority_weights: { financial: 30, urgency: 20, confidence: 15, target_variance: 10, locations: 10, repeated: 10, strategic: 5 }
urgency: { critical: 1, high: 0.75, medium: 0.5, warning: 0.5, low: 0.25 }          # engine parameter
severity_by_impact:
  sales_metric: retail.net_sales
  tiers:
    - { level: critical, min_amount: 10000, min_pct_weekly_sales: 1 }      # greater of $10,000 or 1% of weekly sales
    - { level: high,     min_amount: 5000,  min_pct_weekly_sales: 0.5 }    # greater of $5,000 or 0.5%
    - { level: medium,   min_amount: 1000,  min_pct_weekly_sales: 0.1 }    # greater of $1,000 or 0.1%
  otherwise: low                                                           # informational / early trend
normalization: { target_variance_pct: 20, repeated_occurrences: 4 }       # engine parameter
strategic_rules: []
resurfacing: { impact_change_pct: 20, sample_growth_pct: 25 }             # engine parameter ("materially")
confidence: { deviation_z_midpoint: 2, relative_z_scale: 10, freshness_current: 1, freshness_delayed: 0.7, min_interval_factor: 0.2 }  # spec §7.3a; z/scale engine parameters
health_score:
  components:
    sales_margin:    { weight: 30, rules: ["RET-SALES-*", "RET-MARGIN-*"] }
    inventory:       { weight: 25, rules: ["RET-INV-*"] }
    loss_prevention: { weight: 20, rules: ["RET-REF-*", "RET-DISC-*", "RET-VOID-*", "RET-CASH-*", "RET-X-*"] }
    labor:           { weight: 15, rules: ["RET-LABOR-*"] }
  data_quality_weight: 10
  severity_penalty: { critical: 60, high: 40, medium: 20, warning: 20, low: 5 }    # engine parameter
  status_bands:
    - { min: 85, label: healthy }
    - { min: 70, label: monitor }
    - { min: 50, label: needs_attention }
    - { min: 0,  label: high_priority }
```

- [ ] **Step 7: Kiểm tra retail tải được** (test đầy đủ ở Task 22)

```bash
cd LAAM && npx tsx -e "import { loadPacks } from './src/lib/intel/pack/loader'; loadPacks('../packs', ['retail']).then(p => console.log(p.packVersion, p.rules.length, p.scenarios.length))"
```
Expected: `retail@0.1.0 19 1`.

- [ ] **Step 8: Commit (repo workspace)**

```bash
git add packs/retail/laam
git commit -m "feat(packs): retail LAAM rules, forecasts, scenarios, glossary, roles and scoring"
```

---

### Task 22: Nội dung pack `packs/pharmacy/laam` + test nội dung packs

**Files:**
- Create: `packs/pharmacy/laam/rules.yaml`, `forecasts.yaml`, `scenarios.yaml`, `glossary.yaml`, `scoring.yaml` (không có `roles.yaml` — kế thừa retail; spec OD-6 chỉ có 4 persona)
- Create: `LAAM/src/lib/intel/pack/packs-content.test.ts`
- **Phụ thuộc BẮT BUỘC: master Task M1** (`packs/pharmacy/pack.yaml` với `extends: [retail]`) và Task 21. Thiếu `pack.yaml` ⇒ 14 test của `packs-content.test.ts` fail vì loader không tìm thấy pack.

**Interfaces:**
- Consumes: Task 6, Task 15, Task 21.
- Produces: rule pharmacy (spec §7.3: `PH-CLAIM-001`, `PH-MARGIN-001` — **ID mới**, request không đặt ID và **không cho ngưỡng**; chạy bằng ngưỡng demo **provisional**, E11), forecast `rx_revenue`/`rx_cost`, scenario `pharmacy.acq_cost_change` (nguyên văn master §2.2), glossary, scoring (thêm `PH-*` vào Store Health).

- [ ] **Step 1: Viết test thất bại** — `LAAM/src/lib/intel/pack/packs-content.test.ts`

```ts
import path from "node:path";
import { describe, expect, test } from "vitest";
import { loadPacks } from "./loader";
import { computeScenario } from "../scenario/engine";

// Reads the real packs/ directory (workspace root). Industry words are allowed here: test files
// are excluded from the core vocabulary guard (master Task M3).
const DIR = process.env.PACKS_DIR ?? path.resolve(process.cwd(), "../packs");

const BETA_RULES = [
  "RET-SALES-001", "RET-SALES-006", "RET-MARGIN-001", "RET-MARGIN-002", "RET-INV-001", "RET-INV-010", "RET-INV-003",
  "RET-REF-001", "RET-REF-002", "RET-REF-004", "RET-DISC-002", "RET-DISC-003", "RET-VOID-001", "RET-CASH-001",
  "RET-CASH-004", "RET-LABOR-006", "RET-LABOR-001", "RET-VENDOR-001", "PH-CLAIM-001", "PH-MARGIN-001", "RET-X-REPRINT-001",
];
// Still without a condition: the data is missing as well as the number (wage column, projected hours).
const THRESHOLD_TBD = ["RET-LABOR-001", "RET-LABOR-006"];
// Enabled on provisional demo defaults (user decision 2026-10-02, E11).
const PROVISIONAL: Record<string, string> = {
  "RET-DISC-003": "value > 2.5 * compare_value",
  "RET-CASH-004": "value > 2.5 * compare_value",
  "PH-CLAIM-001": "value > 2.5 * compare_value",
  "RET-INV-010": "value <= -100",
  "PH-MARGIN-001": "value <= compare_value - 2",
  "RET-VOID-001": "value > 2.5 * compare_value",
};
const PROVISIONAL_NOTE = "Demo default — not in request; pending customer confirmation";

async function pharmacy() {
  return loadPacks(DIR, ["pharmacy"]);
}
const rule = async (id: string) => (await pharmacy()).rules.find((r) => r.rule_id === id)!;

describe("packs/ content", () => {
  test("pharmacy extends retail and loads cleanly", async () => {
    expect((await pharmacy()).packVersion).toBe("retail@0.1.0+pharmacy@0.1.0");
  });

  test("every beta rule of spec §7.3 is present exactly once", async () => {
    const ids = (await pharmacy()).rules.map((r) => r.rule_id);
    expect([...ids].sort()).toEqual([...BETA_RULES].sort());
  });

  // Why: rules whose data does not exist yet must surface as threshold_tbd, not run on a guess.
  test("rules missing both data and threshold carry no condition", async () => {
    const p = await pharmacy();
    for (const id of THRESHOLD_TBD) expect(p.rules.find((r) => r.rule_id === id)!.condition, id).toBeUndefined();
  });

  // Why: numbers the request does not give may run only as visibly provisional defaults (badge),
  // and every number from the request stays "confirmed".
  test("demo defaults are marked provisional with the agreed note; request thresholds stay confirmed", async () => {
    const p = await pharmacy();
    for (const [id, condition] of Object.entries(PROVISIONAL)) {
      expect(p.rules.find((r) => r.rule_id === id), id).toMatchObject({ condition, threshold_status: "provisional", threshold_note: PROVISIONAL_NOTE });
    }
    expect((await rule("RET-VOID-001")).min_sample).toBe(50);
    const confirmed = p.rules.filter((r) => !(r.rule_id in PROVISIONAL)).map((r) => r.threshold_status);
    expect(new Set(confirmed)).toEqual(new Set(["confirmed"]));
  });

  // Plan A's checker matches FND-004 on the approving manager; Plan B exposes approvers only on counts.
  test("the override rule groups by approver on the approver-capable metric", async () => {
    expect(await rule("RET-DISC-003")).toMatchObject({ metric: "retail.manual_override_count", dims: ["location_id", "approver_id"] });
  });

  test("rules that need a capability not built in beta are disabled with the reason", async () => {
    expect((await rule("RET-SALES-006")).disabled_reason).toBe("requires_composite_ranking");
    expect((await rule("RET-VOID-001")).disabled_reason).toBeUndefined();
  });

  test("thresholds are copied from the request", async () => {
    expect(await rule("RET-SALES-001")).toMatchObject({
      compare: "target", condition: "value <= 0.95 * compare_value",
      severity: { critical: "value <= 0.80 * compare_value", high: "value <= 0.90 * compare_value", warning: "value <= 0.95 * compare_value" },
    });
    expect((await rule("RET-MARGIN-001")).severity).toEqual({ critical: "value <= compare_value - 10", high: "value <= compare_value - 5", warning: "value <= compare_value - 2" });
    expect(await rule("RET-MARGIN-002")).toMatchObject({ condition: "value <= compare_value - 3", impact: "denominator * (compare_value - value) / 100" });
    expect(await rule("RET-REF-001")).toMatchObject({ condition: "value > 2.5 * compare_value", min_sample: 10, compare: "peer_average" });
    expect(await rule("RET-REF-002")).toMatchObject({ condition: "value > 20", min_sample: 5 });
    expect(await rule("RET-DISC-002")).toMatchObject({ condition: "value > 2.5 * compare_value", min_sample: 20 });
    expect(await rule("RET-CASH-001")).toMatchObject({ metric: "retail.cash_shortage_count", condition: "value >= 3" });
    expect((await rule("RET-CASH-001")).count_days).toBeUndefined(); // per drawer close, not per day
    expect((await rule("RET-INV-001")).condition).toBe("abs(value) >= 100");
    expect((await rule("RET-VENDOR-001")).severity).toEqual({ critical: "value >= 1.20 * compare_value", high: "value >= 1.10 * compare_value", warning: "value >= 1.05 * compare_value" });
    expect((await rule("RET-INV-003")).severity).toEqual({ critical: "value <= 0", high: "value <= 7" });
  });

  test("no severity tier exists that the request does not give", async () => {
    for (const id of ["RET-REF-001", "RET-REF-002", "RET-REF-004", "RET-CASH-001", "RET-MARGIN-002", "RET-INV-001", "RET-DISC-002", "RET-X-REPRINT-001", "PH-MARGIN-001"]) {
      expect((await rule(id)).severity, id).toBeUndefined();
    }
  });

  // Plan A: a +1.5% chain-wide price update on 2026-01-01 must not look like a vendor increase.
  test("a 1.5% cost change cannot trigger the vendor price rule", async () => {
    const { evalBool } = await import("../expr");
    expect(evalBool((await rule("RET-VENDOR-001")).condition!, { value: 101.5, compare_value: 100 })).toBe(false);
    expect(evalBool((await rule("RET-VENDOR-001")).condition!, { value: 105, compare_value: 100 })).toBe(true);
  });

  test("the margin rule for prescriptions compares a rate, not dollar totals, and links its scenario", async () => {
    expect(await rule("PH-MARGIN-001")).toMatchObject({
      metric: "pharmacy.rx_margin_pct", breakdown: ["product_id"], scenario_template: "pharmacy.acq_cost_change",
      driver: { variable: "cost_change_pct" },
    });
  });

  test("scenarios: four distinct presets, no_action not better than expected for an adverse driver", async () => {
    const p = await pharmacy();
    // persistBase = undamped forecasts that already contain the adverse change (cost up / sales down).
    const acq = computeScenario(p.scenarios.find((s) => s.key === "pharmacy.acq_cost_change")!, { base: { rx_revenue: 10000, rx_cost: 8000 }, persistBase: { rx_revenue: 10000, rx_cost: 8640 }, driver: { variable: "cost_change_pct", value: 8 } });
    const sales = computeScenario(p.scenarios.find((s) => s.key === "retail.sales_change")!, { base: { net_sales: 10000, cogs: 6500 }, persistBase: { net_sales: 9000, cogs: 5850 } });
    for (const r of [acq, sales]) {
      const v = Object.fromEntries(r.presets.map((x) => [x.preset, x.primary]));
      expect(new Set(Object.values(v)).size).toBe(4);
      expect(v.no_action).toBeLessThanOrEqual(v.expected);
    }
    acq.presets.forEach((x, i) => expect(x.primary).toBeCloseTo([2000, 2300, 1600, 1360][i], 6));
  });

  test("priority and health weights follow the request", async () => {
    const s = (await pharmacy()).scoring;
    expect(s.priority_weights).toEqual({ financial: 30, urgency: 20, confidence: 15, target_variance: 10, locations: 10, repeated: 10, strategic: 5 });
    expect(Object.fromEntries(Object.entries(s.health_score.components).map(([k, c]) => [k, c.weight]))).toEqual({ sales_margin: 30, inventory: 25, loss_prevention: 20, labor: 15 });
    expect(s.health_score.data_quality_weight).toBe(10);
    expect(s.health_score.components.loss_prevention.rules).toContain("PH-CLAIM-*");
  });

  test("glossary has English and Vietnamese; roles have the four personas", async () => {
    const p = await pharmacy();
    for (const [term, t] of Object.entries(p.glossary.terms)) {
      expect(t.en.length, term).toBeGreaterThan(0);
      expect(t.vi.length, term).toBeGreaterThan(0);
    }
    expect(Object.keys(p.roles.personas).sort()).toEqual(["analyst", "executive", "regional_manager", "store_manager"]);
  });

  // Spec §13: enabling only the retail pack on the same data must work and carry no pharmacy rule.
  test("retail alone loads and contains no pharmacy rule", async () => {
    const r = await loadPacks(DIR, ["retail"]);
    expect(r.rules.some((x) => x.rule_id.startsWith("PH-"))).toBe(false);
    expect(r.scenarios.map((x) => x.key)).toEqual(["retail.sales_change"]);
  });
});
```

- [ ] **Step 2: Chạy test — expected FAIL**

```bash
cd LAAM && npx vitest run src/lib/intel/pack/packs-content.test.ts
```
Expected: FAIL — `packs/pharmacy/laam/*` chưa có (thiếu PH-*, scenario `pharmacy.acq_cost_change`, `PH-CLAIM-*` trong scoring).

- [ ] **Step 3: Tạo `packs/pharmacy/laam/rules.yaml`**

```yaml
# Pharmacy pack — LAAM rules. The request (Part 3 §22) lists pharmacy analytics but gives no rule
# ids and no thresholds for them: ids are new (spec §7.3) and triggers are PROVISIONAL demo defaults
# (threshold_status: provisional, E11) until the customer confirms them via rule_override or a pack bump.
rules:
  - rule_id: PH-CLAIM-001
    version: 1
    name: Claim rejection rate above chain average
    metric: pharmacy.claim_rejection_rate
    dims: [location_id]
    window_days: 30
    compare: peer_average
    # Request: "claim-rejection rate" analytics, no multiplier or level given.
    # Provisional demo default: 2.5 x the average of the other stores (chain/peer average).
    condition: "value > 2.5 * compare_value"
    threshold_status: provisional
    threshold_note: "Demo default — not in request; pending customer confirmation"
    recommended_action: review
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Claim rejection rate is above the chain average"

  - rule_id: PH-MARGIN-001
    version: 1
    name: Prescription margin deterioration
    metric: pharmacy.rx_margin_pct          # a RATE: dollar totals swing +-10-18% at stores without any change
    dims: [location_id]
    window_days: 14
    compare: baseline_same_weekday_4w
    # Request gives no pharmacy margin threshold. Provisional demo default: a drop of 2 percentage
    # points vs baseline (RET-MARGIN-002's 3 points would miss the ~2.1-point demo plant).
    condition: "value <= compare_value - 2"
    threshold_status: provisional
    threshold_note: "Demo default — not in request; pending customer confirmation"
    impact: "denominator * (compare_value - value) / 100"
    impact_unit: currency
    breakdown: [product_id]
    companions: [pharmacy.rx_cost, pharmacy.rx_revenue]
    scenario_template: pharmacy.acq_cost_change
    # Cost change implied by the margin move with revenue held flat: (1 - m1) / (1 - m0) - 1.
    driver: { variable: cost_change_pct, expr: "((100 - value) / (100 - compare_value) - 1) * 100" }
    recommended_action: vendor_review
    default_owner_role: store_manager
    cooldown_days: 7
    wording: "Prescription margin has deteriorated — review acquisition costs"
```

- [ ] **Step 4: Tạo `packs/pharmacy/laam/forecasts.yaml`**

```yaml
forecasts:
  - metric: pharmacy.rx_revenue
    dims: [location_id]
    horizons_days: [7, 30]
    season_length: 7
  - metric: pharmacy.rx_cost
    dims: [location_id]
    horizons_days: [7, 30]
    season_length: 7
```

- [ ] **Step 5: Tạo `packs/pharmacy/laam/scenarios.yaml`** (nguyên văn master §2.2)

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

- [ ] **Step 6: Tạo `packs/pharmacy/laam/glossary.yaml`**

```yaml
terms:
  claim_rejection_rate: { en: "Claim rejection rate", vi: "Tỉ lệ claim bị từ chối" }
  rx_margin:            { en: "Prescription margin", vi: "Biên lợi nhuận đơn thuốc" }
  rx_revenue:           { en: "Prescription revenue", vi: "Doanh thu đơn thuốc" }
  reimbursement:        { en: "Reimbursement", vi: "Tiền bên chi trả thanh toán" }
  acquisition_cost:     { en: "Acquisition cost", vi: "Giá vốn mua thuốc" }
  payer:                { en: "Payer", vi: "Đơn vị chi trả" }
```

- [ ] **Step 7: Tạo `packs/pharmacy/laam/scoring.yaml`** (chỉ ghi đè `health_score` để tính rule `PH-*`; các khoá khác kế thừa retail)

```yaml
health_score:
  components:
    sales_margin:    { weight: 30, rules: ["RET-SALES-*", "RET-MARGIN-*", "PH-MARGIN-*"] }
    inventory:       { weight: 25, rules: ["RET-INV-*"] }
    loss_prevention: { weight: 20, rules: ["RET-REF-*", "RET-DISC-*", "RET-VOID-*", "RET-CASH-*", "RET-X-*", "PH-CLAIM-*"] }
    labor:           { weight: 15, rules: ["RET-LABOR-*"] }
  data_quality_weight: 10
  severity_penalty: { critical: 60, high: 40, medium: 20, warning: 20, low: 5 }
  status_bands:
    - { min: 85, label: healthy }
    - { min: 70, label: monitor }
    - { min: 50, label: needs_attention }
    - { min: 0,  label: high_priority }
```

- [ ] **Step 8: Chạy test — expected PASS**

```bash
cd LAAM && npx vitest run src/lib/intel/pack/packs-content.test.ts
```
Expected: PASS 14/14.

- [ ] **Step 9: Commit (repo workspace + LAAM)**

```bash
git add packs/pharmacy/laam
git commit -m "feat(packs): pharmacy LAAM rules, forecasts, acquisition-cost scenario, glossary and scoring"
git -C LAAM add src/lib/intel/pack/packs-content.test.ts
git -C LAAM commit -m "test(intel): pin pack content to the request's thresholds and the beta rule set"
```

---

### Task 23: Kiểm chứng toàn bộ + guard từ ngữ ngành + CHANGELOG

**Files:**
- Modify: `LAAM/CHANGELOG.md` (mục `[Unreleased]`)
- Dùng: `scripts/check-core-vocabulary.sh` (master Task M3), `LAAM/scripts/seed-intel-demo.ts` (Task 20), endpoint Task 19, packs Task 21–22.

- [ ] **Step 1: Seed + chạy giả lập trên DB dev** (cần Task 1 đã migrate, packs Task 21–22)

```bash
cd LAAM && set -a && . ./.env && set +a   # psql/tsx do not read .env; LAAM's DB is on :5500, not the :5432 fallback
PACKS_DIR=../packs SEED_OWNER_EMAIL="$(psql "$DATABASE_URL" -Atc "select email from \"user\" where role='owner' limit 1")" \
  SEED_EXEC_EMAIL=johnny@demo.local SEED_EXEC_PASSWORD='Demo-Johnny-2026!' \
  SEED_MANAGER_EMAIL=ph002.manager@demo.local SEED_MANAGER_PASSWORD='Demo-PH002-2026!' \
  node --env-file=.env node_modules/.bin/tsx scripts/seed-intel-demo.ts --fake-run
psql "$DATABASE_URL" -c 'select "businessProjectId", persona, "locationIds" from user_scope order by 1, 2'
psql "$DATABASE_URL" -c 'select "ruleId", dims->>'"'"'location_id'"'"' loc, severity, "briefEligible" from finding where "projectId" = '"'"'bp-demo-synthetic'"'"' order by "priorityScore" desc'
```
Expected: in `seeded bp-pharmacy-chain-demo …` và `synthetic run … {"inserted":N,…}` với N ≥ 3; `user_scope` có 3 dòng mỗi project (owner/Johnny `executive {}`, manager `store_manager {PH-002}`); finding tổng hợp gồm ít nhất `RET-SALES-001` (PH-004, so target tháng 7), `RET-REF-001` (PH-001-E2), `RET-CASH-001` (PH-005-E3). Chạy lại lệnh lần hai ⇒ không lỗi, `inserted: 0` cho run tổng hợp (idempotent + dedup). Đây cũng là bài kiểm thật duy nhất của `drizzleRepo` (upsert, event, forecast/scenario insert).

- [ ] **Step 2: End-to-end với DAAB thật qua endpoint** (cần 4 tool `kg_*` của Plan B, mapping + pack đã cài ở DAAB — master M4; dev server LAAM đang chạy)

```bash
cd LAAM && set -a && . ./.env && set +a   # for psql below
curl -s -X POST -H "Content-Type: application/json" -b "<cookie phiên admin>" \
  -d '{"businessProjectId":"bp-pharmacy-chain-demo"}' http://localhost:3100/api/intel/analysis/run | jq '.status, .summary.findings, .summary.rules.skipped'
psql "$DATABASE_URL" -c 'select "ruleId", dims, severity, "briefEligible" from finding where "projectId" = '"'"'bp-pharmacy-chain-demo'"'"' order by "priorityScore" desc'
```
Expected: `"succeeded"`; `skipped` chỉ còn RET-LABOR-001/006 (`threshold_tbd`), RET-SALES-006 (`requires_composite_ranking`) (Task 21–22); finding của rule provisional có `"thresholdStatus" = 'provisional'` và metric DAAB chưa có (`metric_unknown:*`) — **ghi lại danh sách vào checkpoint**; có `provider_error` ⇒ không được coi là PASS. Nếu Plan B chưa xong: ghi rõ "Step 2 chưa chạy — chờ Plan B", không đánh dấu hoàn thành bước này.

- [ ] **Step 3: Chạy toàn bộ test intel + route + workflow liên quan**

```bash
cd LAAM && npx vitest run src/lib/intel src/app/api/intel src/lib/workflow/schedule.test.ts 2>&1 | tail -15
```
Expected: mọi file PASS, `0 skipped`. Có skip/todo ⇒ không được báo hoàn thành (AGENTS Rule 12).

- [ ] **Step 4: Toàn bộ test suite LAAM (không hồi quy)**

```bash
cd LAAM && npx vitest run 2>&1 | tail -8
```
Expected: số test fail **không tăng** so với trước Task 1 (ghi số fail trước/sau vào checkpoint nếu suite vốn có fail).

- [ ] **Step 5: Typecheck + lint các file mới**

```bash
cd LAAM && npx tsc --noEmit -p . 2>&1 | grep -E "src/lib/intel|src/app/api/intel|src/app/api/workflows/tick|scripts/(seed-intel|intel-demo)" ; echo "intel-tsc-matches:$?"
npx eslint src/lib/intel src/app/api/intel src/app/api/workflows/tick scripts/seed-intel-demo.ts scripts/intel-demo-fixture.ts
```
Expected: `intel-tsc-matches:1` (grep không thấy lỗi nào ở file của plan này); eslint không lỗi.

- [ ] **Step 6: Guard từ ngữ ngành (master M3)**

```bash
cd .. && ./scripts/check-core-vocabulary.sh
```
Expected: `core vocabulary OK`. Nếu script M3 chưa có: chạy tương đương
```bash
grep -rniE 'pharmacy|prescription|reimburse|claim_rejection|\bndc\b|\bpbm\b|\bpayer\b' LAAM/src/lib/intel LAAM/src/app/api/intel --include='*.ts' | grep -vE '\.test\.ts:|/testing/|/fixtures/' ; echo "exit:$?"
```
→ `exit:1` (không có dòng nào).

- [ ] **Step 7: Ghi CHANGELOG** — thêm vào đầu mục `## [Unreleased]` của `LAAM/CHANGELOG.md`:

```markdown
### Đã thêm — Engine phân tích chủ động (Proactive Intelligence, giai đoạn P3 + P4)
- Bảng mới (migration `0020`): `business_project`, `user_scope`, `analysis_job`, `analysis_run`, `finding`,
  `finding_event`, `forecast_run`, `scenario_run`, `task`, `feedback`, `rule_override`. Finding là duy nhất theo
  `(project, rule + dims)` ⇒ hai lần chạy song song không tạo trùng.
- `src/lib/intel/` (không chứa từ ngữ ngành): đọc số qua `MetricsProvider` (DAAB qua MCP, có wrapper giới hạn
  chi nhánh theo `user_scope`), nạp Industry Pack từ `PACKS_DIR`, evaluator biểu thức an toàn (biến, so sánh,
  and/or/not, abs/min/max — không `eval`), rule engine (so peer / 4 tuần cùng thứ / target theo tháng / kỳ trước /
  ngưỡng tuyệt đối), nguyên nhân (tách hiệu ứng giá trị và cơ cấu), độ tin cậy, severity theo impact, điểm ưu tiên,
  chống lặp + điều kiện đưa lại lên brief, Store Health Score, dự báo Holt-Winters (damped) có backtest so với
  2 baseline, kịch bản 4 phương án (expected/best/risk/no-action).
- Job phân tích hằng ngày chạy qua `POST /api/workflows/tick` (theo múi giờ của dự án; tự tắt sau 3 lần lỗi liên
  tiếp); chạy tay bằng `POST /api/intel/analysis/run` (owner/admin, ghi `audit_log`).
- `scripts/seed-intel-demo.ts`: tạo dự án demo, phạm vi Johnny (mọi chi nhánh) và quản lý PH-002; `--fake-run`
  ghi một lần phân tích trên dữ liệu tổng hợp vào dự án riêng.
- Rule nào request chưa cho ngưỡng được **tắt kèm lý do** `threshold_tbd` thay vì tự đặt số.
```

- [ ] **Step 8: Commit**

```bash
git -C LAAM add CHANGELOG.md
git -C LAAM commit -m "docs(changelog): proactive intelligence engine (P3 + P4)"
```

- [ ] **Step 9: Checkpoint** — ghi `checkpoint/<agent>-<YYYY-MM-DD>` qua Serena MCP (LAAM CLAUDE.md): việc đã làm, danh sách `skipped` thực tế của Task 23 Step 1–2, các Open questions còn mở.

---

## Self-Review

1. **Độ phủ yêu cầu của caller:** (1) bảng → Task 1 (gồm `task`/`feedback`, lý do ở File Structure; thêm `asOfOverride` theo ràng buộc Plan A); (2) MetricsProvider Daab/Fake/scoped → Task 3–5; (3) loader + extends + override precedence → Task 6, 8; (4) evaluator → Task 2; (5) rule engine, 4+1 chế độ so sánh, min_sample, severity, impact, dedupe, cooldown/resurfacing, priority → Task 9, 11; (6) nguyên nhân + confidence → Task 10; (7) forecast → Task 13–14; (8) scenario → Task 15; (9) job/claim/tick/endpoint/seed → Task 18–20; (10) nội dung pack + Store Health → Task 12, 21–22. Pipeline nối tất cả → Task 17.
2. **Placeholder:** không có "TBD" trong code; "TBD" chỉ xuất hiện trong YAML comment/`disabled_reason` để đánh dấu ngưỡng request chưa cho — đó là hành vi có chủ đích (rule tắt kèm lý do), được test pin (Task 22).
3. **Nhất quán kiểu:** `RuleCandidate` (Task 9) được `analyzeCauses` (Task 10), `pipeline` (Task 17) dùng đúng trường; `FindingValues` (Task 16) khớp cột Task 1; `ForecastWrite` khớp `forecast_run` (cột `sum` NOT NULL ⇒ pipeline ghi `{}` khi thiếu lịch sử); `ProviderScope`/`LOCATION_DIM` dùng chung Task 5/17; `AnalysisSummary.healthScores` là nơi `previousHealthScores` đọc lại.
4. **Rủi ro chưa kiểm tự động:** tầng Drizzle (`drizzleRepo`, `scopeForUser`) chỉ được typecheck + kiểm tay (Task 23 Step 1–2) vì repo LAAM không có hạ tầng test DB thật; `MemoryRepo` mô phỏng cùng ngữ nghĩa. Ghi rõ trong checkpoint khi thực hiện.
5. **Hiệu năng:** grid search 480 tổ hợp × (6 gốc backtest + 2 fit) mỗi chuỗi; 20 chuỗi × 400 ngày ≈ vài giây. Mỗi rule 1–6 lời gọi MCP tuần tự; ~20 rule ⇒ ~100 lời gọi/run (mỗi lời gọi ≤ 15s timeout).

## Open questions

Đã đối chiếu với code/tài liệu khi viết plan; các mục dưới là việc cần người quyết, không phải giả định ẩn.

1. **Ngưỡng tạm (provisional) — quyết định của user 2026-10-02.** Bật bằng giá trị demo, `threshold_status: provisional`, note "Demo default — not in request; pending customer confirmation": RET-DISC-003 (> 2,5 × peer, nhóm theo người duyệt ⇒ **FND-004**), RET-CASH-004 (> 2,5 × peer), PH-CLAIM-001 (> 2,5 × trung bình các cửa hàng khác ⇒ **FND-005**), RET-INV-010 (thất thoát ≥ $100 ⇒ **FND-002**), PH-MARGIN-001 (giảm ≥ 2 điểm ⇒ **FND-009**, kịch bản Plan A −2,1 điểm), RET-VOID-001 (giữ 2,5 × peer của request + `min_sample` tạm 50). ⇒ FND-002/004/005/009 nay **có thể** đạt trong M5 (vẫn phụ thuộc metric Plan B có dữ liệu). Khách xác nhận/sửa bằng `rule_override` (tự thành `confirmed` cho phạm vi đó) hoặc nâng version pack. Còn `threshold_tbd` vì **thiếu cả dữ liệu**: RET-LABOR-001 (chưa có cột lương), RET-LABOR-006 (chưa có giờ dự kiến/lịch làm). Còn mở: giá trị voided tối thiểu của VOID-001, số sự kiện tối thiểu của CASH-004, chiều số lượng (≥ 5 đơn vị) của INV-001/INV-010.
2. **Mở rộng master §2.2 (E1–E9)** vẫn cần chủ master duyệt. **E10 (`asOf`) đã chấp nhận** và đã áp dụng: thứ tự `business_project.asOfOverride` → `asOf` của provider (`getDataStatus`) → hôm qua theo múi giờ (Task 17 `resolveAsOf`, 3 test). Quy ước: ngày dữ liệu cuối **bao gồm**; cửa sổ dùng `to = asOf + 1`.
3. **Độ tươi dữ liệu:** LAAM chỉ đọc nhãn `status` của DAAB, và master §2.4 nay quy định DAAB đánh giá nhãn theo `as_of` (Plan B: `current` tới `as_of`, `delayed` trễ 1–2 ngày, `stale` > 3 ngày — ngưỡng của Plan B, chờ khách duyệt). Không còn chặn; kiểm lại ở Task 23 Step 2 rằng finding demo có `briefEligible = true`.
4. **RET-SALES-001 chỉ dùng so sánh target** (request liệt kê 3 phép so: 4 tuần cùng thứ, target, cùng kỳ năm trước). Một `rule_id` chỉ có một chế độ so sánh; chọn target vì Plan A thiết kế `targets.xlsx` (PH-004 tháng 7) cho đúng rule này và mức sụt cả tháng không lộ ra khi so 7 ngày với 4 tuần đều thuộc tháng 7. Biến thể 4 tuần cần một ID mới (vd `RET-SALES-001W`) — cần khách duyệt tên. Nếu file target chưa upload, rule báo `metric_unknown:retail.target_net_sales`.
5. **`window_days`, `cooldown_days`, tham số engine** (urgency map, chuẩn hoá priority, resurfacing 20%/25%, z-midpoint 2, hệ số 10, phạt Store Health 60/40/20/5) không có trong request — giá trị khởi đầu nằm trong pack (`scoring.yaml`, `rules.yaml`), override được theo project; cần khách duyệt.
6. **Danh tính MCP ở mode user:** cả hai mode gọi DAAB dưới danh nghĩa `ownerUserId` (wrapper thực thi phạm vi chi nhánh). Nếu muốn mỗi user dùng cấu hình MCP riêng (tiền đề cho "mỗi user một API key DAAB", spec §12b), `providerForProject` cần nhận `actingUserId`.
7. **Tick sidecar của master M2** gửi `Authorization: Bearer $TICK_SECRET`, nhưng `tick-auth.ts:46` chỉ đọc header `x-workflow-tick-secret` ⇒ sidecar sẽ nhận 401 khi `WORKFLOW_TICK_SECRET` được đặt. Sửa ở M2 (đổi header), không sửa tick-auth.
8. ~~Run kẹt `running`~~ — **đã xử lý**: `failStaleRuns` mỗi tick đánh `failed` run `running` quá `INTEL_RUN_STALE_MINUTES` (mặc định 60) và tính lỗi cho job. Còn mở: chọn N cho môi trường thật (run dài nhất đo được + biên).
9. **Hợp đồng metric với Plan B:** đã đối chiếu mục "Sai khác so với Plan D" của Plan B — key/dims khớp; cần Plan D xác nhận: `retail.days_of_cover` dùng cửa sổ bán 28 ngày (chấp nhận cho beta); `retail.avg_unit_cost` lấy từ dòng bán (chưa có lịch sử giá nhập) nên RET-VENDOR-001 chỉ thấy đổi giá vốn khi có bán hàng; `retail.refund_rate` mẫu số gồm dòng Rx trong POS; dim NULL được DAAB lưu là `""` — khi đặt ngưỡng cho rule nhóm theo `approver_id`/`employee_id` cần loại nhóm `""` (engine hiện chưa lọc).
10. **Mùa vụ năm** (request PRED-03, ≥ 12 tháng) chưa mô hình hoá — Holt-Winters chỉ mùa vụ tuần. Dữ liệu Plan A có 12 tháng nên có thể bổ sung sau qua điểm nối model.
11. **Store Health "không che vấn đề":** thiết kế chỉ trừ điểm, nhưng một finding critical về LP vẫn có thể để tổng ≥ 85 ("healthy") nếu các thành phần khác tốt (vd 100/100/40/100/100 ⇒ 88). Request yêu cầu "không để một con số doanh thu lớn che vấn đề" — cân nhắc trần trạng thái khi có finding critical (cần khách quyết).
12. **Trigger diễn giải còn lại:** RET-INV-003 dùng mốc **high** (≤ 7 ngày) làm trigger vì mốc warning ("trong lead time") cần lead time — finding mức warning chưa xuất hiện. (RET-LABOR-006 đã chuyển sang `threshold_tbd`: Plan B xác nhận `retail.overtime_hours` là giờ overtime đã ghi trên ca, không phải giờ dự kiến so với ngưỡng tuần của khách.)
13. **RET-DISC-003 (FND-004):** đã trỏ sang `retail.manual_override_count` với `dims: [location_id, approver_id]` (Plan B: tỉ lệ không thể mang dim người duyệt) — vẫn `threshold_tbd`; khi khách cho ngưỡng, điều kiện phải viết trên **số lượng** override (không phải tỉ lệ) và so với peer là các người duyệt khác.
14. **`packs-content.test.ts` đọc `../packs`** (ngoài repo LAAM lồng nhau): checkout LAAM đứng riêng/CI của LAAM sẽ fail test này trừ khi đặt `PACKS_DIR`. Cần quyết: chạy test này ở CI workspace, hoặc mount `packs/` vào job CI của LAAM.
15. **Severity theo impact dùng `retail.net_sales` làm "doanh thu tuần"** (không gồm doanh thu Rx) ⇒ ngưỡng %-doanh-thu cho finding pharmacy thấp hơn thực tế. Nếu muốn tính tổng (`retail.net_sales + pharmacy.rx_revenue`, spec §6.2), `severity_by_impact.sales_metric` cần nhận danh sách metric — mở rộng nhỏ của `scoring.yaml`.

16. **Yêu cầu gửi Plan B — `retail.cash_shortage_count`** (Plan B đã nhận): additive, unit `count`, dims `[location_id, employee_id]`, grain day; `value` = số lần **đóng két** trong ngày có `counted_cash − expected_cash ≤ −25` (ngưỡng mặc định RET-CASH-001 của request); `sample_size` = số lần đóng két. Ngưỡng −$25 nằm trong SQL của DAAB ⇒ đổi ngưỡng theo khách cần version metric mới (hoặc tham số metric sau beta). Tuỳ chọn: `retail.cash_shortage_amount` (tổng tiền thiếu của các lần đó) để RET-CASH-001 có impact tiền — hiện không có ⇒ severity theo §19 rơi về `low`.
17. **Nguyên nhân cho rule so peer:** baseline nhóm peer (thay vì kỳ trước) chưa làm vì không rule peer nào trong pack beta có `breakdown`; nếu thêm, cần nhánh `baseline.kind = "peer_group"` trong `analyzeCauses`.