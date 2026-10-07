# Design: Industry Pack + Proactive Intelligence (DAAB + LAAM Beta)

**Date:** 2026-09-25
**Status:** Draft — chờ review (rev 4, 2026-10-02: đối chiếu với code thật (§2.4) + bổ sung confidence, nguyên nhân, liên kết finding→scenario, lookback, target theo kỳ, an toàn SQL, chuyển sang dữ liệu thật (§14). Rev 3: metric tỉ lệ, forecast, presets, lọc chi nhánh, tên tool `kg_*`.)
**Scope:** Cross-repo — `ennam.kg.go` (DAAB API + MCP bridge), `ennam.kg.python` (DAAB ingestion — parse file "Dữ liệu bảng"), `ennam.kg.next` (màn hình Knowledge Sources), `LAAM` (analysis engine, briefing, UI). Thêm thư mục mới `packs/` (vị trí repo: xem Open Decision OD-1).
**Source request:** `~/Downloads/# DAAB + LAAM Pharmacy Update.txt` (3 phần: Pharmacy direction, Beta direction, Retail Analytics Rules).
**Supersedes:** (1) đề xuất đặt rule/forecast ở DAAB; (2) rev 1 của spec này (copy DB khách vào `raw.*`) — xem [§3.1](#31-quyết-định-bị-thay-thế).

---

## 0. Tóm tắt

Request yêu cầu chuyển DAAB + LAAM từ **trợ lý hỏi-đáp (reactive)** sang **hệ thống chủ động (proactive)**: trước khi user đăng nhập, hệ thống đã phân tích dữ liệu và chào *"Good morning, Johnny — 3 việc cần anh chú ý"*, kèm dự báo, kịch bản, hành động đề xuất, bằng chứng.

Thiết kế này:

1. **Chia vai rõ ràng.** DAAB = *chuẩn bị số* (query tại chỗ DB khách / lưu file khách upload thành bảng, map sang mô hình chuẩn, tính chuỗi chỉ số, giữ evidence, báo độ tươi). LAAM = *phân tích + quyết định* (rule, anomaly, dự báo, kịch bản, ưu tiên, finding, briefing, task, feedback).
2. **Đóng gói tri thức ngành thành Industry Pack** — chủ yếu là *cấu hình* (YAML + SQL), có một nửa cắm vào DAAB và một nửa cắm vào LAAM, bật theo **project**. Core không chứa từ ngữ ngành nào.
3. **Làm lát cắt dọc cho demo**: 2 pack (`retail`, `pharmacy` extends `retail`) trên dữ liệu `pharmacy_demo`, chạy trọn luồng import → metrics → findings → forecast → scenario → briefing → task → feedback.

Nguyên tắc xuyên suốt (request §4): **LLM không bao giờ tạo ra con số.** Số do SQL (DAAB) và code xác định (LAAM) tính; LLM chỉ diễn giải.

---

## 1. Vấn đề

Request định nghĩa 11 tiêu chí "Beta Completion Definition". Gap analysis (2026-09-25) cho kết quả: **0/11 đạt, 2/11 một phần.**

| # | Tiêu chí | Hiện trạng |
|---|---|---|
| 1 | Import khách mới bằng cấu hình | ❌ |
| 2 | DAAB tổ chức & validate dữ liệu | ❌ |
| 3 | Báo cáo tự tính sẵn | ❌ |
| 4 | LAAM chào user với finding chủ động | ❌ |
| 5 | ≥1 dự báo chạy được | ❌ |
| 6 | ≥1 kịch bản chỉnh được | ❌ |
| 7 | Finding link tới dữ liệu gốc | 🟡 |
| 8 | Recommendation → task | ❌ |
| 9 | Ghi quyết định & kết quả | ❌ |
| 10 | Quyền theo khách hàng/chi nhánh | 🟡 (chỉ cấp project) |
| 11 | Demo end-to-end | ❌ |

## 2. Hiện trạng (Findings)

Nhãn: **[V]** = đã tự kiểm tra trong session này; **[S]** = từ code sweep của subagent, chưa tự kiểm tra lại.

### 2.1 DAAB
- **F1 [V]** `pharmacy_demo` được **kết nối**, không được **ingest**. Dữ liệu được `pg_restore` thủ công từ `demo_mockdata/*.csv` vào DB `pharmacy_demo` (cùng container `daab-postgres`, DB tách biệt với `ennam_kg`). DAAB chỉ sync *schema* (→ 21 node `architecture`) và query live qua NL→SQL.
- **F2 [V]** Upload CSV/XLSX ở màn hình **Knowledge Sources** tạo **một node `dataset`**: CSV → một chuỗi text, XLSX → một chuỗi JSON (`ennam.kg.python/src/ennam_kg/ingestion/adapters/files.py:36-43`), cắt ở **50.000 ký tự** (`ingestion/pipeline/nodes.py:11,23,41`). Không có bảng/row ⇒ không tính chỉ số được. `.xls` nằm trong `_TABULAR_FORMATS` nhưng `files.py` từ chối.
- **F3 [S]** Không có SFTP, field mapping, validation lúc import, scheduler cho dữ liệu kinh doanh, materialized view, hay cấu hình theo tenant. BA-007/BA-012 hoãn scheduled sync.
- **F4 [S]** Playbook (`write_playbooks`) chỉ có bước insert, chỉ Postgres — không dùng làm rule engine được.
- **F5 [V]** `derived_record` nhận `links[]` nhưng target là KG node ID (`ennam.kg.go/internal/handler/derived_record.go:86,175`) — không trỏ được tới row nguồn.
- **F6 [S]** `kg_query_datasource` là NL→SQL; planner **không tất định** (`decisions/daab-nl-planner-nondeterminism`). ⇒ Không được dùng để tính chỉ số.
- **F7 [S]** Access control dừng ở project (`handler/authz.go:35`); không có org/location scoping.
- **F8 [S]** Audit tốt: `audit_trail`, `node_versions`, `source_write_audit`.

### 2.2 LAAM
- **F9 [V]** Không có bảng finding/task/rule/forecast/feedback trong `LAAM/src/db/schema.ts`.
- **F10 [V]** `/api/workflows/tick` không có caller trong container — chỉ `scripts/install-tick-task.ps1` (Windows Scheduled Task). [S] 2 schedule trong DB có `lastRunAt` rỗng.
- **F11 [V]** Connector Gmail/Slack/WhatsApp/Zalo có `workflowSafe: true`, **được CTO duyệt**, gate bằng recipient allowlist **fail-closed** (`LAAM/src/lib/connectors/gmail.ts:159` v.v.). Không phải lỗ hổng, nhưng proactive engine *không* được dùng đường này ở beta (xem D9).
- **F12 [S]** Guardrail chống bịa số mạnh (`planGuard`, `verify`, `frozenLiterals`, `empty-result`, `digest`) — nhưng **chưa có kiểm tra grounding cho con số trong câu trả lời cuối**.
- **F13 [S]** `/` redirect `/chat`; "proactive" hiện tại (`lib/agent/proactive.ts`) chỉ là cảnh báo agent-ops.
- **F14 [S]** Role hiện có: owner/admin/member/viewer; không có persona nghiệp vụ.

### 2.3 Dữ liệu `pharmacy_demo` [V]
- 5 cửa hàng `PH-001`…`PH-005` (UnityCare Downtown/Northside/West Plano/Frisco/Irving), 800 sản phẩm, 5.002 transactions, 1.500 prescriptions/claims.
- **Lịch sử: 2026-05-01 → 2026-07-31 (~13 tuần)** — dưới mức 18 tuần của request.
- `claim_status ∈ {Approved, Rejected}` (112 Rejected). `movement_type ∈ {SALE, REFUND_RETURN}` — **không có nhập hàng**. `transactions.status/type` chỉ `Completed/Sale`.
- Thiếu: NDC, PBM, lot/expiry date, vendor table, PO, wage rate, KPI target. `inventory_snapshots` chỉ 1 ngày.
- 7 finding cài sẵn (`demo_mockdata/expected_findings.csv`) đều là **loss-prevention retail** (refund, shrink, cash, void, override, claim rejection).

### 2.4 Điểm tích hợp đã đối chiếu với code [V — code sweep 2026-10-02]
- **I1** LAAM tick (`LAAM/src/app/api/workflows/tick/route.ts`, `lib/workflow/schedule.ts:48-143`): claim không khoá dòng; chống trùng bằng `workflow_run` unique `(scheduleId, scheduledFor)` + đẩy `nextRunAt` trong cùng transaction. `workflow_schedule.workflowId` và `workflow_run.workflowId/graphSnapshot` **NOT NULL** ⇒ analysis run **không** đi qua bảng workflow được. Auth tick: shared secret hoặc localhost (`tick-auth.ts:42-56`).
- **I2** LAAM `project` (`schema.ts:120-126`) là **phiên Claude Code** (`proj:<cwd>`), không phải dự án kinh doanh; không có liên kết sang DAAB. LAAM biết DAAB project id chỉ qua text `instructions` của MCP server (`ennam.kg.go/internal/bridge/connection_context.go`) + `pinKnownIds` (`LAAM/src/lib/connectors/index.ts:412-436`).
- **I3** `LAAM/src/lib/agent/tools/util/calc.ts`: chỉ số học (`+ - * / % ^`, ngoặc), không biến, không so sánh, không and/or. `LAAM/src/lib/workflow/predicate.ts` (`evalPredicate`) có so sánh + all/any nhưng không có số học.
- **I4** Gọi MCP từ LAAM (`lib/connectors/mcp/client.ts:113`, `executeMcp(userId,…)`): **gắn với userId** (config giải mã theo user), **timeout 15s**, cắt 200k ký tự. Workflow theo lịch đã chạy dưới danh nghĩa owner (`schedule.ts:80`). `unwrapToolResult` ở `lib/agent/drilldown.ts:61`.
- **I5** LAAM `user` chỉ có `role` toàn cục (`schema.ts:29,43`), không có membership theo project hay chi nhánh.
- **I6** DAAB `internal/service/source_executor.go`: `Execute(ctx, dataSourceID, sql, params []interface{})` nhận SQL bất kỳ, chỉ chặn nếu không bắt đầu bằng `SELECT`/`WITH` (`:167`); Postgres read-only (`:112`); **timeout 30s** (`:24`); **cắt 10.000 dòng, chỉ đánh dấu `Truncated=true`** (`:21,139`); tham số **theo vị trí** (`$1`/`?`/`@p1`), không hỗ trợ `:from`.
- **I7** DAAB không có cron. Việc định kỳ dùng worker `time.NewTicker` khởi tạo trong `cmd/kg-server/main.go` (ví dụ `NewAgentContextRetentionWorker :1055`); `internal/jobengine` chạy job có retry nhưng không lập lịch; **không có khoá chống chạy trùng**.
- **I8** Bridge: route ở `internal/bridge/client.go:118` (`toolRoutes`), schema ở `internal/bridge/schema.go`. Số lượng tool bị assert ở `client_test.go:216,1070` (52), `schema_test.go:65,99` + `handler_test.go:276` (55), `e2e_tools_test.go:805` (schemas = routes + local), danh sách ở `schema_test.go:20+,1036`, `e2e_tools_test.go:746`, `schema_laam_test.go`. `kg_get_context` (`POST /api/v1/context`) và `kg_get_impact_analysis` (`POST /api/v1/nodes/{id}/impact`) **vẫn trỏ tới route không tồn tại**.
- **I9** `requireProjectAccess` (`handler/authz.go:35-58`) chỉ dựa trên API key (`ProjectIDs`) hoặc `project_members` cho web user; **request không xác thực được cho qua** (`:37-38`). Bridge passthrough chuyển Bearer key của caller (`bridge/serve.go:87,194-202`) ⇒ **DAAB không biết user cuối**.
- **I10** Upload: `ennam.kg.next/src/components/sources/upload-dropzone.tsx` → `src/hooks/use-upload-files.ts` (FormData `file/title/auto_approve`) → proxy `src/app/api/kg/projects/[id]/ingest/upload/route.ts` → Go `internal/handler/ingest_upload.go` → `service/file_upload.go` (`HandleUpload`, `classifyUploadFile :353`) → `PublishExtractUpload :264` → Python worker. Mọi upload đều thành document draft.
- **I11** Schema sync của data source **chỉ chạy thủ công** (`POST /api/v1/data-sources/{id}/sync-schema`, `handler/datasource.go:91,441`; job `schema_sync` ở sync portal).
- **I12** `pharmacy_demo.receipts`: không có cờ reprint, nhưng có `print_type ∈ {Original, Reprint, Gift Receipt}` (259 Reprint) + `print_reason`. `stores` **không có cột timezone**; timestamp là `without time zone`.

---

## 3. Quyết định thiết kế

| ID | Quyết định | Lý do |
|---|---|---|
| **D1** | **DAAB = chuẩn bị số.** Truy cập nguồn (§D4), map canonical, tính metric time series, evidence, data status. | Tổng hợp phải chạy gần dữ liệu (hiệu năng); LAAM chỉ nhận số tổng hợp; chỉ DAAB biết schema khách hàng. |
| **D2** | **LAAM = phân tích + quyết định.** Rule, anomaly, forecast, scenario, priority, finding, briefing, task, feedback. | Khớp "LAAM Core" trong request (Part 2 §2). LAAM đã có workflow engine, scheduler, guardrail. |
| **D3** | **Industry Pack = cấu hình**, 2 nửa (`daab/`, `laam/`), bật **theo project**. Code extension point chỉ khi cần. | Không cần deploy khi bật pack; version/audit được; không chạy code tuỳ ý trong môi trường khách. |
| **D4** | **Hai loại nguồn, hai cách truy cập.** (a) **DB của khách → query tại chỗ (`mode: live`)**: DAAB chạy SQL tổng hợp read-only trên DB khách, **không copy dòng nào**, chỉ lưu kết quả vào `metric_value`. (b) **File khách upload (CSV/Excel) → lưu thành bảng trong DAAB (`mode: file`)** rồi tính trên đó. (c) **Kéo DB về (`mode: landed`)** chỉ bật khi khách cho phép hoặc cần join nhiều nguồn — **sau beta**. Chế độ là cấu hình theo từng nguồn; đổi chế độ không sửa pack/LAAM. | DB khách là hệ thống đang vận hành, mình chỉ được đọc; file là khách chủ động đưa. Không tạo gì trên DB khách (không DDL). `metric_value` luôn lưu ⇒ chuỗi lịch sử cho dự báo vẫn còn dù nguồn xoá dữ liệu cũ. |
| **D5** | **Mapping = YAML sinh SQL**, LLM đề xuất khớp cột, người duyệt. | Khách mới chỉ làm mapping; metrics/rules dùng lại nguyên vẹn. Dùng LLM cho phân loại (AGENTS.md rule 5). |
| **D6** | **Canonical model ổn định, trung tính ngành ở core**; pack chỉ *mở rộng*. | Canonical đổi ⇒ mọi pack vỡ. Đây là hợp đồng quan trọng nhất. |
| **D7** | **Hợp đồng DAAB↔LAAM là "metrics provider" chung**: 4 MCP tool mới `kg_get_metrics`, `kg_get_evidence`, `kg_get_data_status`, `kg_list_metrics` (§6.7). LAAM core chỉ biết interface `MetricsProvider`, không hardcode tên tool DAAB hay metric key. | LAAM phải connector-agnostic (memory `laam-must-stay-connector-agnostic`). Metric key chỉ xuất hiện trong pack YAML. |
| **D8** | **Không dùng `kg_query_datasource` (NL→SQL) cho metric.** Metric là SQL cố định, có version. | Planner không tất định (F6). |
| **D9** | **Beta không có hành động tự động ra ngoài.** Proactive engine chỉ ghi finding + in-app notification. Không đổi giá, không đặt hàng, không gửi tin. | Request Part 3 §20; tách khỏi đường `workflowSafe` (F11). |
| **D10** | **Core không chứa từ ngữ ngành.** Không có "pharmacy", "claim", "NDC" trong code/schema/prompt của core — kiểm tra bằng grep trong CI. | Tránh lặp lại việc prompt rule rút từ pharmacy lọt vào core (`LAAM/src/lib/agent/context.ts` P1–P3). |
| **D11** | **Tool mô tả *hành động*, không mô tả *nghiệp vụ*.** Thêm ngành = thêm pack (metric, evidence, rule, playbook), **không thêm tool**. Chỉ thêm tool khi có một *loại hành động* chưa tool nào làm được, và tool đó dùng chung mọi ngành (ví dụ `kg_get_entity(entity, id)`, không phải `get_claim`). Hệ thống ngoài của ngành (API PBM, POS) là **connector**, không phải tool. | Tool tăng theo ngành × chỉ số làm LLM chọn sai, mỗi tool mới phải sửa Go + bridge + deploy (trái D3), và tên ngành lọt vào core (trái D10). |

### 3.1 Quyết định bị thay thế
**(1)** Trong session, đề xuất ban đầu đặt rule engine / finding / forecast ở **DAAB**. Sau khi đối chiếu request (Part 2 §2 gán *rule execution, anomaly detection, prediction coordination, scenario generation, priority scoring* cho LAAM Core), thiết kế này chuyển các phần đó sang **LAAM** (D2). DAAB chỉ giữ phần *tổng hợp số liệu gần dữ liệu* (D1).

**(2)** Rev 1 của spec đặt metric chạy trên bản copy `raw.*` (kéo toàn bộ DB khách về DAAB). Rev 2 đổi thành: **DB khách query tại chỗ mặc định**, chỉ file upload được lưu; kéo DB về là tuỳ chọn sau beta (D4). Lý do: ít việc hơn cho beta (bỏ job sync), không giữ bản sao dữ liệu vận hành của khách, và vẫn chuyển sang `landed` được mà không viết lại.

---

## 4. Kiến trúc tổng thể

```text
NGUỒN KHÁCH HÀNG                 DAAB
────────────────                 ──────────────────────────────────────────────────────
DB của khách (read-only)  ◀────  live: 1 câu SQL = CTE từ mapping.yaml + metrics/*.sql
                                 (không copy dòng nào, không DDL trên DB khách)
CSV / Excel khách upload  ────▶  file: file_table (dòng dữ liệu) → cùng câu SQL chạy trong DAAB
SFTP / kéo DB về (landed)        sau beta
                                          │
                                          ▼
                                 metric_value   chuỗi chỉ số (key × dims × ngày) — luôn lưu
                                 data_status    độ tươi / thiếu dữ liệu / mapping hỏng
                                 MCP: kg_get_metrics · kg_get_evidence · kg_get_data_status · kg_list_metrics
                                          │
LAAM                                      ▼  (metrics provider, D7)
──────────────────────────────── Analysis Run (theo lịch / khi có dữ liệu mới)
                                   ├─ Rule engine      (pack laam/rules.yaml)
                                   ├─ Forecast service (pack laam/forecasts.yaml)
                                   ├─ Scenario engine  (pack laam/scenarios.yaml)
                                   ├─ Priority + dedup + cooldown
                                   └─ finding / forecast_run / scenario_run
                                          │
                                          ▼
                                 Briefing (LLM diễn giải, có grounding check)
                                   → Home dashboard → Task → Feedback → audit
```

---

## 5. Industry Pack

### 5.1 Cấu trúc

```text
packs/
├── retail/
│   ├── pack.yaml
│   ├── daab/
│   │   ├── canonical.yaml        # entity + field chuẩn mà pack cần
│   │   ├── metrics/*.sql         # công thức chỉ số trên entity canonical (claim, product…)
│   │   └── evidence/*.sql        # query lấy row nguồn cho từng chỉ số
│   └── laam/
│       ├── rules.yaml
│       ├── forecasts.yaml
│       ├── scenarios.yaml
│       ├── glossary.yaml         # thuật ngữ cho LLM diễn giải
│       ├── roles.yaml            # briefing profile theo persona
│       └── cards.yaml            # thẻ dashboard
└── pharmacy/                     # extends: retail
    └── (cùng cấu trúc, chỉ phần bổ sung)
```

### 5.2 `pack.yaml`

```yaml
key: pharmacy
version: 0.1.0
extends: [retail]
display_name: Pharmacy
requires_canonical: [location, product, prescription, claim]   # thiếu ⇒ metric/rule phụ thuộc bị tắt
metrics: [pharmacy.claim_rejection_rate, pharmacy.rx_revenue, pharmacy.rx_cost, pharmacy.rx_margin, pharmacy.reimbursement_gap]
```

### 5.3 Quy tắc
- **Namespace**: mọi key có tiền tố pack (`retail.net_sales`, `pharmacy.claim_rejection_rate`).
- **Extends**: pack con thêm entity/field/metric/rule; ghi đè rule của pack cha bằng `overrides: retail.<rule_id>`. Không được xoá field canonical của cha.
- **Version**: semver. Mỗi `metric_value`, `finding`, `forecast_run` lưu `pack_version` + `rule_version`/`metric_version`. Nâng version không sửa bản ghi cũ.
- **Thứ tự ưu tiên ngưỡng** (request Part 3 §2): customer override → location override → department/category override → pack default → **tắt nếu thiếu dữ liệu**.
- **Cài theo project**: bảng `pack_install(project_id, pack_key, version, enabled)` **ở DAAB — nguồn sự thật cho việc pack nào đang bật** (DAAB cần biết để chạy metric). LAAM biết qua `kg_list_metrics` (trả kèm danh sách pack + version đang bật), không giữ bản sao.
- **Override thuộc về bên sở hữu khái niệm**: override của *metric* (ví dụ múi giờ, cách gộp) ở DAAB; override *ngưỡng rule, trọng số priority, preset scenario* ở **LAAM** (bảng `rule_override`, §7.4) — DAAB không lưu khái niệm của LAAM.
- Beta: pack là thư mục trong repo, đọc từ file; chưa có UI cài/gỡ.
- **Liên kết project**: LAAM chưa có khái niệm dự án kinh doanh (I2) ⇒ tạo bảng mới `business_project(id, name, metrics_provider, daab_project_id, mcp_connector_slug, owner_user_id, timezone, locale_default)`. Một business project ↔ một DAAB project. `owner_user_id` là user mà job hệ thống chạy dưới danh nghĩa (I4). Bảng `project` hiện có (phiên Claude Code) giữ nguyên, không dùng lại.

---

## 6. DAAB

### 6.1 Truy cập nguồn

| Chế độ | Nguồn | Cách chạy | Lưu gì trong DAAB | Beta |
|---|---|---|---|---|
| `live` | DB của khách (Postgres beta; MSSQL/MySQL sau) | SQL tổng hợp chạy **read-only trên DB khách** (tốt nhất là replica), qua data source connector hiện có | Chỉ `metric_value`, `data_status` | ✅ |
| `file` | CSV / Excel khách upload | Parse **toàn bộ dòng** vào bảng `file_table` của project, rồi chạy SQL trên đó | Bảng dữ liệu từ file + `metric_value` | ✅ |
| `landed` | DB của khách, khi được phép | Job `SELECT` tăng dần (watermark) vào bản copy, chạy SQL trên bản copy | Bản copy + `metric_value` | Sau beta |

**`live` — query tại chỗ**
- Không tạo view/bảng trên DB khách (không DDL). Mỗi lần chạy = một câu `WITH <canonical CTE> <metric SQL>` (§6.3).
- Chạy tăng dần theo cửa sổ ngày, không quét toàn bảng mỗi ngày. Mỗi lần chạy tính lại một **cửa sổ lùi (lookback)** — mặc định 7 ngày, cấu hình theo metric — vì dữ liệu đến muộn hoặc bị sửa (claim đổi trạng thái sau vài ngày, refund ghi vào ngày gốc).
- **Tham số**: metric SQL trong pack viết `:from`/`:to`; engine đổi sang tham số theo vị trí của dialect (`$1` cho Postgres) trước khi gọi `source_executor` (I6).
- **Giới hạn dòng**: `source_executor` cắt ở 10.000 dòng và chỉ đánh dấu `Truncated` (I6). Metric runner **coi `Truncated=true` là lỗi** (không ghi `metric_value`, báo `data_status = blocked`) và **chia nhỏ cửa sổ thời gian** khi backfill (ví dụ metric location × product × ngày chạy theo từng tuần). Runner dùng giới hạn riêng (cấu hình) thay vì giới hạn dành cho NL→SQL.
- **Timeout**: query metric chạy phía Go (30s, I6) — không qua LAAM. Query evidence chạy live khi user mở phải xong trong **15s** (timeout MCP phía LAAM, I4) ⇒ evidence SQL luôn có `LIMIT` + lọc theo cửa sổ ngày và dims.
- Giới hạn chấp nhận ở beta: không join được giữa hai hệ thống; nguồn xoá dữ liệu cũ thì không tính lại được kỳ đó khi đổi công thức (chuỗi `metric_value` cũ vẫn giữ, ghi `metric_version`); nguồn tắt ⇒ `data_status = delayed/stale`, brief dùng số lần chạy gần nhất.
- Schema nguồn đổi ⇒ phát hiện bằng cách **metric runner gọi service sync schema có sẵn trước mỗi lần chạy** (hiện chỉ chạy thủ công, I11), so cột mapping cần với cột thực tế; thiếu cột ⇒ mapping `broken`, tắt metric phụ thuộc.

**`file` — file khách upload (mở rộng màn hình Knowledge Sources)**
- Thêm lựa chọn khi upload: **"Tài liệu"** (giữ nhánh hiện tại → node `dataset` để tìm kiếm/hỏi đáp) hoặc **"Dữ liệu bảng"** (nhánh mới). Hệ thống đoán theo đuôi file/nội dung, user sửa được.
- Đường đi (I10): thêm field `ingest_mode` vào FormData ở `use-upload-files.ts` → proxy chuyển nguyên → đọc trong `ingest_upload.go` cạnh `auto_approve` → rẽ nhánh trong `handleOneFile`/`classifyUploadFile`. Nhánh nạp bảng là phần mới.
- Nhánh "Dữ liệu bảng": parse đủ mọi dòng (không cắt 50.000 ký tự), mỗi sheet một bảng, đoán kiểu cột, lưu `file_table(project_id, file_id, sheet, version)` + dòng dữ liệu; hỗ trợ `.xls`.
- Validation lúc upload: cột bắt buộc theo mapping, kiểu dữ liệu, tỉ lệ NULL, trùng khoá ⇒ báo lỗi cụ thể từng cột/dòng, ghi vào `data_status`.
- Upload lại cùng loại file: chế độ `append` (thêm kỳ mới) hoặc `replace` (thay toàn bộ), cấu hình theo mapping.
- File dùng cho demo: **KPI target theo cửa hàng** (dữ liệu khách thường giữ trong sheet). Target chỉ được *so sánh* với thực tế ở rule của LAAM, không cần join từng dòng với dữ liệu DB (xem ràng buộc §6.3).

**`landed` — kéo DB về (sau beta)**
- Job `source_sync` đọc qua data source connector, watermark theo `updated_at` hoặc PK tăng dần, lưu `_sync_state(table, watermark, last_success_at, rows, status)`.
- Chuyển `live → landed`: bật sync, backfill lịch sử nguồn còn giữ, đổi `mode`. Chuyển `landed → live` (khách rút quyền): tắt sync, **xoá bản copy** và ghi log xác nhận, đổi `mode`; `metric_value` giữ lại.
- Mỗi `metric_value` ghi `source_mode` + watermark để truy vết số lệch lúc chuyển chế độ.

### 6.2 Canonical model (core, trung tính ngành)

Canonical là **tập entity và field logic** (hiện thực bằng CTE sinh từ mapping, không phải bảng lưu sẵn). Tối thiểu cho beta — mỗi entity có `source_ref` (bảng + PK gốc) để làm evidence:

| Entity | Field chính |
|---|---|
| `location` | location_id, name, region, timezone, opened_at, status |
| `product` | product_id, sku, name, category, subcategory, unit_cost, list_price, vendor_id, is_regulated |
| `employee` | employee_id, location_id, role |
| `sale` | sale_id, location_id, employee_id, customer_id, sold_at, gross_amount, discount_amount, tax_amount, net_amount, status |
| `sale_line` | sale_line_id, sale_id, product_id, quantity, unit_price, unit_cost, discount_amount, override_flag |
| `refund` | refund_id, location_id, employee_id, approver_id, original_sale_id, refunded_at, amount, has_receipt, method |
| `void` | void_id, location_id, employee_id, voided_at, amount, post_tender |
| `cash_drawer` | drawer_id, location_id, employee_id, closed_at, expected_cash, counted_cash |
| `shift` | shift_id, location_id, employee_id, start_at, end_at, regular_hours, overtime_hours |
| `inventory_movement` | movement_id, location_id, product_id, moved_at, movement_type (`sale`/`receipt`/`return`/`adjustment`/`transfer`), quantity |
| `inventory_snapshot` | location_id, product_id, snapshot_date, book_qty, counted_qty, expired_qty |
| `target` | location_id, metric_key, period, value |

**Pharmacy extension:**

| Entity | Field chính |
|---|---|
| `prescription` | prescription_id, location_id, product_id, filled_at, quantity, status, cash_price, patient_paid, payer_paid, acquisition_cost |
| `claim` | claim_id, prescription_id, location_id, payer, submitted_at, billed_amount, reimbursed_amount, patient_amount, is_rejected, rejection_code |

**Định nghĩa đã chốt cho pharmacy** (tránh nhập nhằng):
- *Reimbursement* = `claim.reimbursed_amount` (payer trả) — map từ `insurance_claims.approved_amount`.
- *Rx revenue* = `reimbursed_amount + patient_amount` (payer + copay).
- *Acquisition cost* = **giá vốn theo từng lần bán** `prescription.acquisition_cost` (Plan A thêm cột này vào `pharmacy_demo`). Công thức cũ `quantity × product.unit_cost` không dùng được: dữ liệu gốc ghi giá theo hộp trong khi quantity đếm theo viên ⇒ giá vốn cao gấp ~16× doanh thu Rx. Phát hiện margin dùng `pharmacy.rx_margin_pct` (ratio).
- *Prescription hợp lệ cho doanh thu/giá vốn*: loại `status ∈ {Reversed, Cancelled}` (102 + 84 trong dữ liệu). `claim_rejection_rate` vẫn tính trên **mọi** claim.
- *Không tính trùng retail/Rx* [V]: doanh thu Rx nằm ở `prescriptions`/`insurance_claims`, không ở `transaction_items` (chỉ 1 dòng Rx trong `transaction_items`). ⇒ `sale_line` canonical **loại** dòng có `product.is_regulated = true`; tổng doanh thu cửa hàng = `retail.net_sales + pharmacy.rx_revenue`.

**Giá trị enum chuẩn** (mapping phải chuẩn hoá về đúng các giá trị này; metric SQL chỉ dùng giá trị chuẩn):
- `prescription.status ∈ {received, ready, picked_up, not_collected, reversed, cancelled}`
- `inventory_movement.movement_type ∈ {sale, receipt, return, adjustment, transfer}`
- `sale.status ∈ {completed, voided, cancelled}`

**Múi giờ**: "ngày" (`period_date`) tính theo **giờ địa phương của location**. `location.timezone` lấy từ mapping nếu nguồn có, nếu không thì mặc định của project (`business_project.timezone`). Nguồn demo không có cột timezone và timestamp không kèm múi giờ (I12) ⇒ coi timestamp là giờ địa phương, project demo đặt `America/Chicago` (các cửa hàng ở Texas). Rule "sau 8 giờ tối" cũng dùng giờ địa phương.

### 6.3 Mapping (per project)

```yaml
# projects/<pharmacy-chain>/mapping.yaml
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

- Engine **không tạo view**. Nó sinh một **CTE** từ mapping và ghép trước SQL của metric thành một câu duy nhất:

```sql
WITH claim AS (                                   -- sinh từ mapping.yaml
  SELECT claim_id, prescription_id, store_id AS location_id, payer_name AS payer,
         submitted_datetime AS submitted_at, approved_amount AS reimbursed_amount,
         customer_amount AS patient_amount, claim_status = 'Rejected' AS is_rejected
  FROM insurance_claims                           -- live: bảng trên DB khách
)                                                 -- file/landed: bảng trong DAAB
SELECT … FROM claim …                             -- nguyên văn metrics/*.sql của pack
```

- Metric SQL trong pack tham chiếu **tên entity canonical** (`claim`, `prescription`, `product`), không có tiền tố schema. Cùng một file chạy được ở cả 3 chế độ.
- Một project có thể trộn nguồn: ví dụ `claim` từ DB (live), còn `target` từ file upload. **Không join trực tiếp giữa hai chế độ.** Mỗi metric chỉ dùng entity cùng một chế độ và được tính ở nơi dữ liệu nằm. So sánh chéo (thực tế từ DB so với target từ file) thực hiện ở **rule của LAAM** trên hai chuỗi `metric_value` (ví dụ `retail.gross_margin_pct` so với `retail.target_gross_margin_pct`).
  - ⇒ Dữ liệu cần **join từng dòng** với giao dịch (giá vốn, lương) phải ở **cùng chế độ** với giao dịch. Beta: để trong DB khách.
  - Sau beta, nếu khách chỉ có giá vốn/lương dạng file: thêm **"reference pushdown"** — engine nhúng bảng file nhỏ (giới hạn số dòng) vào câu SQL live dưới dạng `VALUES` CTE. Metric SQL của pack không đổi.
- Validation khi áp mapping: field bắt buộc có đủ; kiểu dữ liệu; tỉ lệ NULL; giá trị enum. Kết quả vào `data_status`.
- **LLM đề xuất mapping** từ metadata cột DAAB đã có (column descriptions, `ValueHinter`) → trạng thái `proposed` → người duyệt → `approved`. Chỉ `approved` mới được dùng.
- **An toàn SQL** (mapping và pack SQL chạy thẳng trên DB khách):
  - Chỉ chạy mapping `approved` và pack đã cài; phiên read-only (Postgres) + kiểm tra câu bắt đầu bằng `WITH`/`SELECT` (I6).
  - Biểu thức trong mapping (ví dụ `"claim_status = 'Rejected'"`) được **validate bằng parser SQL**: chỉ cho phép cột của bảng nguồn, hằng số, phép so sánh/logic/số học và danh sách hàm cho phép (`COALESCE`, `LOWER`, `CASE`, ép kiểu…). Cấm `;`, subquery, comment, hàm ngoài danh sách.
  - Tên bảng/cột trong mapping phải tồn tại trong schema đã sync; luôn quote định danh khi sinh SQL.

### 6.4 Metrics

Mỗi metric = 1 file SQL + header khai báo:

```sql
-- key: pharmacy.claim_rejection_rate
-- version: 1
-- grain: day
-- dims: [location_id]
-- unit: percent
-- aggregation: ratio          -- gộp kỳ = 100 * SUM(numerator) / SUM(denominator)
-- sample_size: số claim
-- requires: [claim]
SELECT
  location_id,
  submitted_at::date                                       AS period_date,
  COUNT(*) FILTER (WHERE is_rejected)                      AS numerator,
  COUNT(*)                                                 AS denominator,
  COUNT(*)                                                 AS sample_size
FROM claim
WHERE submitted_at >= :from AND submitted_at < :to
GROUP BY 1, 2;
```

```sql
-- key: pharmacy.reimbursement_gap
-- version: 1
-- grain: day
-- dims: [location_id, product_id]
-- unit: currency
-- aggregation: additive       -- gộp kỳ = SUM(value)
-- sample_size: số claim được duyệt
-- requires: [claim, prescription, product]
-- Nghĩa: tiền payer trả − giá vốn (request DAAB-04 "reimbursement variance").
-- Gồm cả copay ⇒ dùng pharmacy.rx_margin.
SELECT
  c.location_id,
  p.product_id,
  c.submitted_at::date                                  AS period_date,
  SUM(c.reimbursed_amount) - SUM(p.quantity * pr.unit_cost) AS value,
  COUNT(*)                                              AS sample_size
FROM claim c
JOIN prescription p ON p.prescription_id = c.prescription_id
JOIN product pr     ON pr.product_id     = p.product_id
WHERE NOT c.is_rejected
  AND p.status NOT IN ('reversed', 'cancelled')   -- giá trị đã chuẩn hoá bởi mapping
  AND c.submitted_at >= :from AND c.submitted_at < :to
GROUP BY 1, 2, 3;
```

- **Mỗi metric phải khai báo nghĩa của `sample_size`** (claim, refund, giao dịch…) vì `min_sample` của rule đếm trên đó (ví dụ RET-REF-001 đếm *số refund*, không phải số giao dịch).

- **Cách gộp kỳ phải khai báo** (`aggregation`):
  - `additive` (doanh thu, chi phí, số lượng, số tiền): SQL trả `value`; gộp tuần/tháng/30 ngày = `SUM(value)`.
  - `ratio` (margin %, tỉ lệ từ chối, refund rate, avg ticket): SQL trả `numerator` + `denominator`; `value` do engine tính; gộp kỳ = `SUM(numerator)/SUM(denominator)`. **Không bao giờ lấy trung bình các tỉ lệ ngày.**
  - `snapshot` (tồn kho, days on hand): gộp kỳ = giá trị ngày cuối kỳ.
- **Rule phát hiện theo bản ghi** (duplicate refund, reprint trước refund, shortage lặp lại) biểu diễn thành metric **đếm** (`additive`, ví dụ `retail.duplicate_refund_groups` theo location/ngày) + `evidence/*.sql` liệt kê các bản ghi cụ thể. Không cần loại metric riêng.
- **Metric runner** (Go, trong DAAB) có **scheduler riêng** — worker `time.NewTicker` mới theo mẫu worker có sẵn (I7), khởi tạo trong `cmd/kg-server/main.go`, có **Postgres advisory lock theo project** để không chạy trùng. Chạy hằng ngày theo giờ cấu hình cho nguồn `live` (sau bước sync schema), và chạy ngay sau mỗi lần upload với nguồn `file`. Tính lại cửa sổ lookback, upsert vào:

```text
metric_value(project_id, metric_key, metric_version, pack_version,
             period_date, dims jsonb, value numeric,
             numerator numeric, denominator numeric,   -- chỉ với aggregation = ratio
             sample_size int,
             computed_at, source_mode, source_watermark)   -- source_mode: live | file | landed
PK: (project_id, metric_key, period_date, dims_hash)
```

- Beta: tính theo ngày; tuần/tháng/cửa sổ rule gộp khi đọc theo `aggregation`.
- **Đổi version metric** ⇒ runner tính lại **toàn bộ kỳ mà nguồn còn giữ**. Kỳ không tính lại được giữ version cũ; `kg_get_metrics` trả `versions_in_series`, forecast **cảnh báo khi chuỗi lẫn version**.
- **Target theo kỳ**: metric target từ file khai báo `grain: month` (`aggregation: snapshot`). Rule so target dùng **từ đầu tháng tới nay** với target tháng **chia theo tỉ lệ số ngày** (hoặc theo phân bổ mùa vụ nếu pack khai báo).
- Retail metric tối thiểu: `net_sales`, `cogs`, `gross_margin_pct`, `avg_ticket`, `transactions`, `refund_rate` (dims location, employee), `no_receipt_refund_pct`, `void_rate`, `discount_rate`, `cash_variance`, `labor_hours`, `overtime_hours`, `labor_cost`, `inventory_variance_value`, `duplicate_refund_groups`, và các metric target từ file (`target_net_sales`, `target_gross_margin_pct`). Pharmacy: `claim_rejection_rate`, `rx_revenue`, `rx_cost`, `rx_margin`, `reimbursement_gap`.

### 6.5 Evidence
- Mỗi metric có `evidence/<key>.sql` trả về row canonical (kèm `source_ref`) cho một `(metric_key, period, dims)`.
- Chạy theo chế độ của nguồn: `live` ⇒ query tại chỗ lúc user mở, **hiển thị rồi bỏ, không lưu**; `file`/`landed` ⇒ đọc bảng trong DAAB. Nguồn live đã xoá kỳ cũ ⇒ báo rõ "bằng chứng không còn ở nguồn".
- `kg_get_evidence` giới hạn số row, phân trang, **lọc theo quyền trước khi truy vấn**.

### 6.6 Data status
`data_status(project_id, entity, last_success_at, period_covered, status ∈ {current, delayed, incomplete, stale, blocked}, issues jsonb)` — theo bảng trạng thái của request Part 3 §3. LAAM không được gọi dữ liệu `stale`/`incomplete` là "hiện tại".

### 6.7 MCP tools (hợp đồng với LAAM)

**4 tool mới** trong DAAB bridge (cùng chỗ với các tool `kg_*` hiện có). Mỗi tool = 1 endpoint API mới trong `ennam.kg.go` + 1 khai báo trong bridge.

| Tool | Input | Output | Phía sau |
|---|---|---|---|
| `kg_get_metrics` | `metric_keys[]`, `from`, `to`, `dims_filter?`, `group_by?`, `grain?` (day/week/month) | `[{metric_key, version, period, dims, value, numerator?, denominator?, sample_size}]` + `data_status` | Đọc `metric_value`, gộp theo `aggregation`. **Không query DB khách** |
| `kg_get_evidence` | `metric_key`, `period`, `dims`, `dims_filter?`, `limit`, `cursor?` | `{rows[], source_refs[], total}` | Chạy `evidence/<key>.sql` theo chế độ nguồn (§6.5) |
| `kg_get_data_status` | — | `data_status[]` + metric bị tắt vì thiếu dữ liệu | Đọc `data_status` |
| `kg_list_metrics` | — | pack + version đang bật; catalog metric (key, unit, aggregation, dims, requires) | Đọc `pack_install` + pack |

- `dims_filter` dùng để **lọc chi nhánh** (`location_id ∈ [...]`) — LAAM luôn truyền (§7.11). DAAB áp filter vào SQL, không lọc sau khi đọc.
- Tất cả qua `requireProjectAccess` như tool hiện có. DAAB chỉ biết API key, không biết user cuối (I9) — phạm vi chi nhánh beta do LAAM thực thi (§7.11).
- Khi thêm tool: cập nhật các chỗ assert số lượng tool của bridge (§12a); tiện thể xử lý 2 tool đang trỏ tới route không tồn tại (`kg_get_context`, `kg_get_impact_analysis` — theo ghi chú 2026-09-24, cần kiểm tra lại).

---

## 7. LAAM

### 7.1 Metrics provider
- Interface `MetricsProvider { listMetrics; getMetrics; getEvidence; getDataStatus }`. Implementation đầu tiên: `DaabMetricsProvider` gọi 4 tool `kg_*` ở §6.7. Core engine chỉ biết interface (D7) — tên tool DAAB chỉ xuất hiện trong `DaabMetricsProvider`.
- Mọi lời gọi đi qua một wrapper có 2 chế độ: **user** (gắn bộ lọc chi nhánh của user, §7.11) và **system** (analysis run, toàn bộ chi nhánh). Engine không gọi provider trực tiếp. Cả hai chế độ gọi MCP dưới danh nghĩa một userId (I4): chế độ system dùng `business_project.owner_user_id`.
- Kết quả MCP phải qua `unwrapToolResult` (I4) trước khi kiểm tra shape.

### 7.2 Analysis run
- Trigger: lịch hằng ngày (sau khi metric runner của DAAB chạy xong), dữ liệu mới (DAAB báo watermark đổi — beta: poll `kg_get_data_status`), user đăng nhập mà brief > N giờ, task quá hạn.
- Scheduler: **tick sidecar trong `docker-compose`** gọi `/api/workflows/tick` mỗi phút (OD-3). Route tick được **mở rộng để dispatch cả analysis run** qua bảng riêng `analysis_job(id, business_project_id, kind, cron, timezone, next_run_at, enabled, last_error)` + `analysis_run(id, job_id, scheduled_for, status, started_at, finished_at, error)` với **unique `(job_id, scheduled_for)`** — copy pattern claim của workflow (chống trùng bằng unique slot, đẩy `next_run_at` trong cùng transaction, tự tắt khi lỗi liên tiếp). Không dùng `workflow_schedule` vì bảng đó bắt buộc gắn workflow (I1).
- Chạy theo **ngữ cảnh hệ thống** (toàn bộ chi nhánh của project). Lọc chi nhánh chỉ áp khi *đọc* finding/brief cho từng user (§7.11).
- Pipeline: `load metrics → evaluate rules → forecast → scenarios → score → dedup/cooldown → persist → build briefing`.

### 7.3 Rule engine

```yaml
# packs/retail/laam/rules.yaml
- rule_id: RET-REF-001
  version: 1
  name: Refund rate concentration by employee
  metric: retail.refund_rate
  dims: [location_id, employee_id]
  window: 30d
  compare: peer_average            # peer_average | baseline_4w_same_weekday | target | previous_period
  condition: "value >= 2.5 * peer_value"
  min_sample: 10                   # 10 refund (sample_size của retail.refund_rate)
  severity:
    high: "value >= 2.5 * peer_value"   # request chỉ cho 1 mức; các mức khác = TBD với khách
  impact: "refund_amount_excess"   # biểu thức trên metric đã có
  recommended_action: investigate
  default_owner_role: store_manager
  cooldown: 7d
  wording: "Repeated exception pattern requiring management review"   # không buộc tội (request Part 3 §12)
```

- Biểu thức (`condition`, `severity`, `impact`, scenario `outputs`) chạy bằng **evaluator mới**, an toàn (không `eval`): mở rộng tokenizer shunting-yard của `LAAM/src/lib/agent/tools/util/calc.ts` thêm **biến, so sánh (`>= <= > < == !=`), `and/or/not`, và vài hàm (`abs`, `min`, `max`)** (I3). `calc.ts` hiện tại giữ nguyên hành vi cho tool chat.
- Rule khai báo thêm:
  ```yaml
    breakdown: [product_id, category]       # để tìm nguyên nhân (§7.3a)
    scenario_template: retail.refund_policy  # kịch bản gắn với finding (§7.7)
    driver: { variable: refund_rate_change_pct, from: "value / peer_value - 1" }
    confidence: { weights: { sample: 0.4, deviation: 0.4, freshness: 0.2 } }
  ```
- Rule tự tắt nếu metric cần thiết bị tắt; báo lý do trong data status.
- **Ngưỡng lấy nguyên từ request**; mức nào request không cho thì ghi `TBD` và chốt với khách, không tự đặt.
- Beta rule set — bám "Beta 1 — Must Work" (request Part 3 §23):

| Nhóm (Beta 1) | Rule | Ghi chú |
|---|---|---|
| Sales | `RET-SALES-001`, `RET-SALES-006` (store ranking) | |
| Margin | `RET-MARGIN-001` (cần target — P0), `RET-MARGIN-002` | |
| Inventory | `RET-INV-001`, `RET-INV-010` (possible shrink), `RET-INV-003` (stockout — cần receipt + lead time, P0) | |
| Refunds | `RET-REF-001`, `RET-REF-002`, `RET-REF-004` | |
| Discounts | `RET-DISC-002`, `RET-DISC-003` (manual override) | |
| Voids | `RET-VOID-001` | |
| Cash | `RET-CASH-001`, `RET-CASH-004` (no-sale openings) | |
| Labor | `RET-LABOR-006` (overtime risk), `RET-LABOR-001` (labor % — **cần wage rate**, P0) | |
| Vendor costs | `RET-VENDOR-001` (cần lịch sử giá vốn — P0) | |
| Pharmacy | `PH-CLAIM-001` (claim rejection so với trung bình chuỗi), `PH-MARGIN-001` (reimbursement gap giảm) | **ID mới**, request không đặt ID cho rule pharmacy |
| Custom | `RET-X-REPRINT-001` (reprint receipt trước refund cùng giao dịch) | **ID mới**, không có trong request; cần FND-007 |

#### 7.3a Nguyên nhân ("vì sao thay đổi") và độ tin cậy

**Nguyên nhân (`contributing_factors`)** — tính bằng code, LLM chỉ diễn giải:
1. Với mỗi chiều trong `breakdown` của rule, gọi `kg_get_metrics` theo `group_by` chiều đó, cho kỳ hiện tại và kỳ so sánh.
2. Tính **phần đóng góp vào chênh lệch** của từng thành phần: metric `additive` = chênh lệch của thành phần; metric `ratio` = tách thành hiệu ứng *giá trị* (tỉ lệ của thành phần đổi) và hiệu ứng *cơ cấu* (tỷ trọng của thành phần đổi).
3. Lấy top N (mặc định 5) theo trị tuyệt đối đóng góp; ghi tỉ lệ cộng dồn ("5 thuốc chiếm 78% mức giảm").
4. Có thể thêm **tín hiệu đi kèm** do rule khai báo (ví dụ margin giảm ⇒ kiểm tra `cost_change` và `reimbursement_change` của cùng thành phần) — đây là nguồn câu "giá vốn tăng trong khi reimbursement đứng yên".

**Độ tin cậy (`confidence`, 0–1)** — công thức xác định, trọng số trong pack:
- `sample` = `min(1, sample_size / (min_sample × 3))` — mẫu càng lớn so với ngưỡng tối thiểu càng tin.
- `deviation` = mức lệch so với baseline/peer chuẩn hoá (z-score qua hàm sigmoid) — lệch càng rõ càng tin.
- `freshness` = 1 nếu `data_status = current`, 0.7 nếu `delayed`, 0 nếu `incomplete/stale/blocked` (finding bị chặn khỏi brief khi = 0).
- Finding có **impact dựa trên dự báo**: nhân thêm hệ số từ độ rộng khoảng tin cậy backtest (khoảng càng hẹp càng tin).
- Hiển thị dạng % kèm lý do ("dựa trên 214 claim, lệch 3,1σ so với chuỗi, dữ liệu cập nhật hôm nay").

- **Store Health Score** (request Part 3 §15, thuộc Beta 1): composite 0–100 theo trọng số Sales & margin 30 · Inventory 25 · Refund/discount/LP 20 · Labor 15 · Data quality 10; cùng evaluator với priority score; hiển thị điểm thành phần, lý do, thay đổi so với kỳ trước.

**Độ phủ ground truth** (`demo_mockdata/expected_findings.csv`):

| Finding | Rule | Beta |
|---|---|---|
| FND-001 refund Sarah Miller (PH-001) | RET-REF-001/002 | ✅ |
| FND-002 shrink PH-005 | RET-INV-010 | ✅ |
| FND-003 duplicate refunds | RET-REF-004 | ✅ |
| FND-004 override concentration PH-002 | RET-DISC-003 (+ RET-REF-005 nếu cần) | ✅ |
| FND-005 claim rejection PH-004 | PH-CLAIM-001 | ✅ |
| FND-006 cash shortage PH-005 | RET-CASH-001 + RET-CASH-004 | ✅ |
| FND-007 reprint trước refund | RET-X-REPRINT-001 (custom): `receipts.print_type = 'Reprint'` trong 1–48 giờ trước refund cùng giao dịch, cùng nhân viên (I12) | ✅ |
| README: PH-004 sales decline tháng 7 | RET-SALES-001 | ✅ |
| README: PH-004 expired stock | RET-INV-* expiry | ❌ cần lot/expiry date (P0) hoặc chỉ `expired_quantity` |

### 7.4 Bảng (LAAM, Drizzle)

```text
finding(
  id, project_id, rule_id, rule_version, pack_version,
  dims jsonb, metric_key, current_value, expected_value, variance, comparison,
  estimated_impact numeric, impact_unit, severity, confidence numeric,
  priority_score numeric, contributing_factors jsonb, recommended_action,
  evidence_refs jsonb,            -- {metric_key, period, dims} để gọi kg_get_evidence
  data_status_snapshot jsonb,
  status  -- new | acknowledged | assigned | monitoring | resolved | dismissed
  dismiss_reason, dedupe_key, first_seen_at, last_seen_at, created_at)
finding_event(id, finding_id, type, payload jsonb, actor, at)     -- lịch sử & audit
forecast_run(id, project_id, metric_key, dims, horizon_days, model, model_version,
             baseline_model, history_days, point jsonb, lower jsonb, upper jsonb,
             backtest jsonb, computed_at)
scenario_run(id, project_id, finding_id?, template_key, assumptions jsonb,
             result jsonb, baseline jsonb, computed_at, created_by)
task(id, project_id, finding_id, title, action_type, owner_user_id, owner_role,
     priority, due_at, approval_required, status, decision, decision_reason,
     actual_result jsonb, completed_at, created_by)
feedback(id, project_id, target_type, target_id, kind, value jsonb, user_id, at)
business_project(...)   -- §5.3
user_scope(business_project_id, user_id, persona, location_ids[])   -- thay user_persona; LAAM chưa có membership (I5)
analysis_job(...), analysis_run(...)   -- §7.2
rule_override(project_id, target_key, scope jsonb, value jsonb, updated_by, updated_at)
  -- target_key: rule_id | priority_weights | scenario preset; scope: {location_id?, category?}
  -- thứ tự ưu tiên §5.3: customer → location → category → pack default
```
(`pack_install` ở DAAB — xem §5.3.) Trong các bảng LAAM ở trên, `project_id` = `business_project.id` (không phải bảng `project` phiên Claude Code, I2).

### 7.5 Priority, dedup, cooldown
- `priority_score` theo trọng số request Part 3 §18: Financial impact 30 · Urgency 20 · Confidence 15 · Target variance 10 · Số location 10 · Lặp lại 10 · Strategic 5. Trọng số là cấu hình pack.
- `dedupe_key = rule_id + dims_hash`. Finding đã có ⇒ cập nhật `last_seen_at`; **chỉ đưa lại lên brief** khi severity tăng, impact đổi > X%, có evidence mới, task quá hạn, hoặc user yêu cầu monitoring.
- Brief: tối đa 5 finding chính; còn lại ở "More insights"; critical trước; mới trước cũ.

### 7.6 Forecast
- **Chỉ dự báo metric `additive`**: `retail.net_sales`, `retail.cogs`, `pharmacy.rx_revenue`, `pharmacy.rx_cost` — theo location; horizon 7 và 30 ngày.
- **Margin suy ra từ dự báo** (doanh thu dự báo − chi phí dự báo), không dự báo trực tiếp tỉ lệ %. Khoảng tin cậy của margin tính từ khoảng của hai thành phần (beta: cộng trừ bảo thủ, ghi rõ trên UI).
- **Model**: Holt-Winters cộng tính, mùa vụ tuần, **có tham số damped trend** (dùng cho preset *expected*, §7.7). **Baseline**: seasonal-naive (cùng thứ tuần trước) và moving average 28 ngày. Model **chỉ được hiển thị là "reliable" nếu MAE/MAPE backtest tốt hơn cả hai baseline**; ngược lại hiển thị baseline kèm nhãn.
- Backtest rolling-origin: train trên dữ liệu có đến thời điểm t, dự báo t+h, so thực tế. Khoảng tin cậy = phân vị residual backtest (P10–P90).
- **Gate theo lịch sử**: < 8 tuần ⇒ không dự báo; 8–18 tuần ⇒ hiển thị với cảnh báo *"insufficient history — low confidence"*; ≥ 18 tuần ⇒ bình thường; seasonal năm chỉ khi ≥ 12 tháng (request PRED-03).
- Implementation: TypeScript trong LAAM (Holt-Winters ~100–150 dòng, có unit test với dữ liệu đã biết đáp án). Extension point cho model ngoài (Python service) để sau.

### 7.7 Scenario engine

```yaml
# packs/pharmacy/laam/scenarios.yaml
- key: pharmacy.acq_cost_change
  label: Acquisition cost change
  base_metrics:                   # tổng dự báo 30 ngày của metric, đặt tên biến cục bộ
    rx_revenue_30d: forecast_sum(pharmacy.rx_revenue, 30d)
    rx_cost_30d:    forecast_sum(pharmacy.rx_cost, 30d)
  variables:
    cost_change_pct:          { default: 0,  min: -30, max: 30 }
    reimbursement_change_pct: { default: 0,  min: -30, max: 30 }
  outputs:
    margin_30d: "rx_revenue_30d * (1 + reimbursement_change_pct/100) - rx_cost_30d * (1 + cost_change_pct/100)"
  presets:
    expected:  { forecast: damped }                                   # dự báo, xu hướng tắt dần
    best:      { forecast: damped, reimbursement_change_pct: 3 }
    risk:      { forecast: damped, cost_change_pct: 5 }
    no_action: { forecast: persist_driver }                           # vấn đề hiện tại kéo dài nguyên vẹn
```

**Định nghĩa 4 phương án** (request Part 1 §9, Part 3 §17):

| Phương án | Định nghĩa beta |
|---|---|
| **Expected** | Dự báo Holt-Winters với **damped trend** — biến động gần đây giảm dần theo thời gian (thực tế giá/doanh thu hiếm khi tăng/giảm mãi). |
| **No-action** | **Driver của finding giữ nguyên mức hiện tại** trong suốt horizon (ví dụ giá vốn giữ mức đã tăng 8%, không mean-revert), không có hành động khắc phục. Luôn ≤ expected khi finding là xấu. |
| **Best** | Expected + giả định thuận lợi hợp lý (biến trong pack). |
| **Risk** | Expected + giả định bất lợi hợp lý (biến trong pack). |

- Preset là **cấu hình pack** và override được theo project (`rule_override`), không nằm trong code.
- **Liên kết finding → kịch bản**: rule khai báo `scenario_template` + `driver` (§7.3). Khi tạo finding, engine tính giá trị driver đo được (ví dụ `cost_change_pct = +8%`) và chạy 4 preset; *no-action* giữ driver ở mức đo được.

- Tính **tất định** bằng cùng evaluator §7.3. Output luôn gồm: assumptions, baseline, changed variables, result, chênh lệch so với baseline, và nhãn *"decision support — not a guarantee"*.
- UI cho phép chỉnh `variables` ⇒ tính lại tức thì (không cần LLM).

### 7.8 Briefing + diễn giải bằng LLM
- Input cho LLM: JSON của top finding (đã có số, evidence refs, data status, forecast, scenario) + `glossary.yaml` + persona trong `roles.yaml`.
- Output: tiêu đề, 2–3 câu "what changed / why / what next", đề xuất hành động.
- **Numeric grounding check (mới, lấp F12)**: mọi số trong văn bản LLM phải khớp (sau chuẩn hoá làm tròn/đơn vị) với một số trong input JSON; vi phạm ⇒ sinh lại, lần hai vẫn vi phạm ⇒ dùng template không-LLM.
- Brief được lưu (cache) theo `(project, user, run_id)`; user đăng nhập đọc bản đã sinh.
- **Ngôn ngữ**: brief sinh theo locale của user (LAAM đã có i18n; mặc định `business_project.locale_default` — demo Johnny: English). Grounding check áp dụng mọi ngôn ngữ (chuẩn hoá dấu phân cách hàng nghìn/thập phân theo locale).

### 7.9 Home dashboard
Theo request Part 2 §10 — 5 phần:
1. Lời chào + data status (last update, locations, missing-data warning).
2. Needs Attention: 3–5 thẻ (finding, impact, location, confidence, action, evidence, owner, due).
3. Predictions: 7/30 ngày, so target, khoảng tin cậy.
4. Scenarios: expected / best / risk / no-action, chỉnh được biến.
5. Recommended actions: Review · Assign · Approve · Monitor · Dismiss (kèm lý do) · Complete.
+ Ô "Ask LAAM" (chat hiện có, truyền finding làm context).
  - Câu hỏi về chỉ số có trong `kg_list_metrics` ⇒ **bắt buộc dùng `kg_get_metrics`/`kg_get_evidence`** để số trong chat khớp với brief. `kg_query_datasource` (NL→SQL) chỉ dùng cho câu hỏi ngoài catalog, và câu trả lời gắn nhãn *"tính trực tiếp, không qua chỉ số chuẩn"*.
  - Chat cũng phải tuân thủ phạm vi chi nhánh của user (§7.11).
`/` trỏ về Home khi project có pack được bật; giữ `/chat` cho project không có pack.

### 7.10 Task & feedback
- Từ finding ⇒ tạo task (owner, priority, due, approval_required). Hành động: approve / reject (lý do) / dismiss (lý do) / complete + `actual_result`.
- Ghi `feedback` cho: mở finding, accept/reject/edit recommendation, dismiss, đánh dấu dự báo sai, xác nhận kết quả.
- Mọi thay đổi ghi `finding_event` + `audit_log` hiện có.
- **Không** tự điều chỉnh rule/threshold từ feedback trong beta (request LEARN-03) — chỉ lưu để phân tích.

### 7.11 Quyền & phạm vi chi nhánh
- LAAM chưa có membership theo project (I5) ⇒ bảng mới `user_scope(business_project_id, user_id, persona, location_ids[])` (`location_ids` rỗng = mọi chi nhánh, ví dụ executive). Không có dòng `user_scope` ⇒ không thấy project đó. `roles.yaml` quyết định *nội dung* brief theo persona.
- **Finding nhiều chi nhánh** (ví dụ FND-003 refund trùng ở nhiều cửa hàng): hiện cho user nếu có **ít nhất một** chi nhánh trong phạm vi; số liệu, impact và evidence hiển thị **chỉ phần thuộc chi nhánh của user**, kèm ghi chú "finding này liên quan cả chi nhánh khác".
- **LAAM thực thi phạm vi chi nhánh ở mọi bề mặt** (phương án beta):
  - Mọi lời gọi `MetricsProvider` (metric, evidence) tự gắn `dims_filter: location_id ∈ location_ids` của user — qua wrapper §7.1, không để từng màn hình tự nhớ.
  - Finding, forecast, scenario, brief chỉ hiển thị cho user có chi nhánh liên quan.
  - Ask LAAM: truyền phạm vi vào context; mọi tool call từ chat đi qua cùng wrapper; câu hỏi ngoài phạm vi ⇒ từ chối. `kg_query_datasource` không lọc được theo chi nhánh ⇒ **tắt cho user có `location_ids` giới hạn** trong beta.
- **Giới hạn đã biết**: DAAB vẫn tin LAAM — gọi thẳng DAAB (không qua LAAM) thì vẫn thấy mọi chi nhánh; DAAB cũng không biết user cuối và đang cho qua request không xác thực (I9). **Bắt buộc xử lý trước khi chạy với dữ liệu thật của khách** (§12b, §14).
- Kết quả: tiêu chí 10 đạt trong demo (đăng nhập quản lý PH-002 chỉ thấy PH-002, kể cả evidence và chat).

---

## 8. Kế hoạch dữ liệu demo (Phase 0)

Hai lựa chọn — không loại trừ nhau:

| | A. Dùng finding có sẵn | B. Cài kịch bản margin |
|---|---|---|
| Nội dung | 7 finding loss-prevention (refund Sarah Miller, shrink PH-005, duplicate refund, override PH-002, claim rejection PH-004, cash shortage Daniel Ross, reprint trước refund) | "PH-00x margin giảm ~X% trong 14 ngày: giá vốn 5 thuốc tăng, reimbursement đứng yên" (tương đương ví dụ Location 12 / $18k của request) |
| Rule | `RET-REF-*`, `RET-VOID-*`, `RET-CASH-*`, `RET-DISC-*`, `PH-CLAIM-001` | `PH-MARGIN-001`, `RET-MARGIN-002`, forecast margin, scenario acq cost |
| Công dữ liệu | Không | Có — sinh thêm dữ liệu |

**Đề xuất: làm cả hai.** Forecast cần ≥ 18 tuần nên dù sao cũng phải mở rộng dữ liệu. Việc cần làm:
1. Mở rộng lịch sử lên **≥ 12 tháng** (tối thiểu 18 tuần), có mùa vụ tuần/tháng; dọn 2 giao dịch lạc tháng 8.
2. Thêm `inventory_movements` loại nhập hàng (receipt), bảng `vendors`, snapshot tồn kho hằng tuần.
3. Thêm **vào `pharmacy_demo`**: lịch sử giá vốn theo thời gian (để cài "giá vốn tăng" + RET-VENDOR-001), **wage rate** cho nhân viên (labor %, RET-LABOR-001 — `employees` hiện không có cột lương [V]), lead time vendor (RET-INV-003), và lot/expiry date nếu muốn giữ finding expired-stock. (Giá vốn và lương phải ở cùng DB với giao dịch — §6.3.)
4. Cài kịch bản margin ở một store, giữ nguyên 7 finding cũ.
5. Cập nhật `expected_findings.csv` làm **ground truth** cho test tự động. Thêm `print_type` reprint đã có sẵn (I12) vào kiểm tra FND-007.
6. Dữ liệu giao dịch vẫn nằm trong `pharmacy_demo` đóng vai **DB của khách** ⇒ DAAB query tại chỗ (`live`).
7. Làm file Excel **KPI target theo cửa hàng** (doanh thu, margin %) để demo bước **upload** (`file`) — phục vụ RET-MARGIN-001. Demo thể hiện cả hai: "kết nối DB nhà thuốc" + "upload file khách có sẵn" → DAAB nhận diện chi nhánh, sản phẩm, giao dịch.

---

## 9. Phân kỳ & trách nhiệm

| Phase | Nội dung | Repo | Tiêu chí đạt |
|---|---|---|---|
| **P0** | Dữ liệu demo (§8) | workspace/`demo_mockdata` | tiền đề cho 5, 6 |
| **P1** | Pack format + loader; canonical core + pharmacy ext; mapping YAML → CTE (+ validate biểu thức, đổi tham số theo dialect); chế độ `live` trên `source_executor` (giới hạn dòng riêng, `Truncated` = lỗi); nhánh **"Dữ liệu bảng"** trên màn hình Knowledge Sources (parse đủ dòng, `.xls`, validation, `file_table`) | DAAB (py + go + next), `packs/` | 1, 2 |
| **P2** | Metric runner + **worker ticker Go + advisory lock** + lookback + gọi sync schema trước khi chạy + `metric_value` (additive/ratio/snapshot) + `data_status` + evidence SQL; 4 MCP tool `kg_get_metrics/kg_get_evidence/kg_get_data_status/kg_list_metrics` (có `dims_filter`); cập nhật assert số tool + gỡ/sửa 2 tool chết (I8) | DAAB | 3, 7 |
| **P3** | `business_project` + `user_scope`; MetricsProvider + wrapper (user/system); `analysis_job`/`analysis_run` + tick sidecar (mở rộng route tick); evaluator mới (mở rộng `calc.ts`) + rule engine; nguyên nhân + confidence (§7.3a); bảng finding/finding_event/rule_override; priority/dedup/cooldown | LAAM | (nền cho 4) |
| **P4** | Forecast (Holt-Winters damped + baseline + backtest, chỉ metric additive); scenario engine + 4 preset | LAAM | 5, 6 |
| **P5** | Briefing + grounding check; Home dashboard; evidence view | LAAM | 4, 7 |
| **P6** | Task, decision, feedback, audit; persona + phạm vi chi nhánh ở mọi bề mặt (kể cả Ask LAAM) | LAAM | 8, 9, 10 (đạt trong demo; xem giới hạn §7.11) |
| **P7** | Kịch bản demo end-to-end (14 bước của request Part 2 §15) thành test E2E | cả hai | 11 |

P1–P2 (DAAB) và P3 (LAAM, dùng mock provider trả `metric_value` cố định) **làm song song được** khi §6.7 đã chốt.

---

## 10. Ngoài phạm vi spec này
- Chế độ `landed` (kéo DB khách về), SFTP import, API connector mới, OCR cho dữ liệu bảng.
- `live` trên MSSQL/MySQL (beta chỉ Postgres).
- Join giữa hai DB khách khác nhau.
- UI chỉnh field mapping (beta: sửa YAML + LLM đề xuất qua script).
- UI cài/gỡ pack, marketplace, code plugin động.
- Org/tenant model và row-level/location-level security trong DAAB.
- Adaptive learning tự động (đổi threshold/model từ feedback), cross-customer learning.
- Các rule Beta 2 của request (customer segmentation, promotion optimization, advanced employee pattern…).
- Gửi thông báo ra ngoài (email/Slack/Zalo) từ proactive engine.
- Tự động hoá vòng đời user (request Part 1 §13: import danh sách nhân viên, thu hồi quyền khi nghỉ việc, quyền tạm thời).
- Mobile.

## 11. Open decisions

| ID | Câu hỏi | Đề xuất |
|---|---|---|
| **OD-1** | `packs/` nằm ở repo nào? (DAAB và LAAM cùng đọc) | Repo riêng `ennam.kg.packs` hoặc thư mục trong `ennam.kg.requirements`… — đề xuất **repo riêng**, cả hai service mount read-only |
| **OD-2** | Bảng dữ liệu từ file upload và `metric_value` nằm ở đâu? (golang-migrate chỉ quản lý schema cố định của DAAB) | `metric_value`, `data_status`, `file_table` (metadata) là bảng cố định qua migration trong `ennam_kg`. Dòng dữ liệu từ file: **schema theo project** (`p_<id>_files`) tạo lúc runtime bằng DDL có kiểm soát, hoặc JSONB một bảng chung nếu file nhỏ — chốt khi làm P1 |
| **OD-3** | Scheduler LAAM: tick sidecar trong compose hay scheduler in-process? | Sidecar `curl` mỗi 60s với tick token — ít thay đổi code nhất |
| **OD-4** | Metric runner (chạy SQL live/file) và parser file viết bằng Python hay Go? | Parser file: Python (pipeline upload đã ở đó). Metric runner: Go (đã có `source_executor` read-only + connector) — chốt khi làm P1 |
| **OD-5** | Có chuyển toàn bộ dữ liệu demo sang 12 tháng không, hay 18 tuần là đủ? | 12 tháng — rẻ hơn khi đã phải sinh lại, và demo được seasonal |
| **OD-7** | Dữ liệu demo 12 tháng sinh bằng gì? (không rõ generator gốc của `demo_mockdata`) | Tìm generator gốc; nếu không có, viết generator mới có seed cố định, tái tạo 7 finding cũ + kịch bản margin, rồi chạy lại kiểm tra `expected_findings` |
| **OD-6** | Tên persona & mapping sang role hiện có | executive / regional_manager / store_manager / analyst, độc lập với owner/admin/member/viewer |

## 12. Rủi ro
- **Canonical model sai từ đầu** ⇒ mọi pack phải sửa. Giảm thiểu: chỉ đưa field mà beta rule thật sự dùng; review riêng §6.2 trước khi code.
- **Forecast yếu trên dữ liệu tổng hợp** ⇒ không thắng baseline. Chấp nhận: hiển thị baseline kèm nhãn — vẫn đúng request.
- **Dữ liệu sinh "quá đẹp"** ⇒ demo thuyết phục nhưng không phản ánh thực tế. Giảm thiểu: thêm nhiễu, thiếu dữ liệu, một source trễ để demo data status.
- **Lan từ ngữ ngành vào core** ⇒ kiểm tra grep trong CI (D10).
- **Phạm vi phình** (plugin framework, UI mapping) ⇒ giữ §10.

## 12a. Ghi chú triển khai (bẫy đã gặp trong dự án)
- **Kết quả MCP về LAAM bị stringify** (`{text:"<json>"}`): `DaabMetricsProvider` phải unwrap (`unwrapToolResult`) trước khi kiểm tra shape — nếu không, guard im lặng không chạy mà test vẫn xanh.
- **Thêm tool vào bridge** phá invariant `schemas == routes + localToolNames`; cập nhật các chỗ assert số lượng tool.
- **Grounding check** phải chuẩn hoá U+2011/U+2212 (gạch nối/dấu trừ) và bỏ qua mã định danh (`PH-004`, `EMP-0006`, `FND-001`) khi so số.
- **DB dev của DAAB ở cổng 5433**; `make db-migrate` mặc định 5432 là container khác. Test DB bị SKIP vẫn báo PASS ở cấp package.

## 12b. Khả năng chuyển đổi / thay thế sau này

Mỗi lựa chọn beta được đặt sau một **điểm nối** (cấu hình hoặc interface), để đổi sang phương án đầy đủ mà không viết lại phần còn lại.

| Lựa chọn beta | Phương án sau này | Điểm nối — vì sao đổi dễ | Phải sửa gì khi đổi |
|---|---|---|---|
| DB khách query tại chỗ (`live`) | Kéo về (`landed`) khi khách cho phép | `mode` là cấu hình theo nguồn; metric SQL chạy trên CTE, không biết dữ liệu ở đâu (§6.3) | Thêm job sync + backfill. Pack, LAAM giữ nguyên |
| Chỉ KPI target ở dạng file; giá vốn/lương ở DB | Giá vốn/lương dạng file | Metric SQL tham chiếu tên entity, không phụ thuộc nơi lưu | Thêm *reference pushdown* (`VALUES` CTE) ở engine, hoặc bật `landed`. Pack giữ nguyên |
| Lọc chi nhánh do LAAM gắn (`dims_filter`) | DAAB tự kiểm tra row-level | Mọi lời gọi đã đi qua `dims_filter` + wrapper duy nhất ở LAAM | DAAB cần biết user cuối (I9): **mỗi user một API key DAAB** (cấu hình MCP của LAAM vốn theo user, I4) hoặc **header acting-user có ký**. DAAB thêm bảng user–chi nhánh, tự giao filter với quyền. LAAM không đổi. **Bắt buộc trước dữ liệu thật** |
| Expected = damped trend; No-action = driver giữ nguyên | Expected tính cả hành động đã lên kế hoạch (task được duyệt có tác động ước tính) | Preset là cấu hình pack + `rule_override` | Thêm trường `estimated_effect` cho task + preset mới. Engine scenario giữ nguyên |
| Holt-Winters trong TypeScript | Model khác / service Python | Forecast đi qua interface model; backtest so với baseline là cổng chung | Thêm implementation; cổng "phải thắng baseline" giữ nguyên |
| Pack là thư mục trong repo | UI cài/gỡ, registry | Loader đọc pack qua một interface (`PackSource`) | Thêm nguồn pack mới (DB/registry) |
| Mapping sửa bằng YAML + LLM đề xuất qua script | UI mapping | Mapping lưu dạng dữ liệu có trạng thái `proposed/approved` | Thêm UI đọc/ghi cùng dữ liệu |
| Postgres cho `live` | MSSQL/MySQL | CTE + metric SQL sinh qua một lớp dialect | Thêm dialect; metric SQL của pack viết theo tập con SQL chung |
| 4 tool `kg_*` qua DAAB | Nguồn metric khác (không phải DAAB) | LAAM chỉ biết `MetricsProvider` (D7) | Thêm provider mới |

## 13. Kiểm chứng
- **DAAB**: test mapping YAML → SQL; test mỗi metric trên fixture nhỏ có đáp án tính tay; test chạy cùng metric ở chế độ `live` (trên `pharmacy_demo`) và `file` (cùng dữ liệu upload dạng CSV) ⇒ **ra cùng kết quả**; test upload "Dữ liệu bảng" (đủ dòng, `.xls`, báo lỗi validation); test `kg_get_evidence` tôn trọng quyền project và `dims_filter`.
- **Runner**: test `Truncated=true` ⇒ không ghi `metric_value`, `data_status = blocked`; backfill chia cửa sổ cho kết quả bằng chạy một lần; lookback cập nhật được claim đổi trạng thái muộn; hai runner chạy cùng lúc ⇒ chỉ một chạy (advisory lock).
- **An toàn SQL**: biểu thức mapping chứa `;`, subquery, hàm lạ ⇒ bị từ chối.
- **Nguyên nhân & confidence**: kịch bản margin cài ở P0 ⇒ top 5 thuốc đóng góp đúng các thuốc đã cài; confidence giảm khi `sample_size` nhỏ hoặc dữ liệu `delayed`.
- **Metric tỉ lệ**: test gộp 30 ngày của `ratio` = `SUM(tử)/SUM(mẫu)`, khác với trung bình tỉ lệ ngày (fixture có ngày ít mẫu).
- **Phạm vi chi nhánh**: đăng nhập user chỉ có PH-002 ⇒ brief, evidence, forecast, chat đều không lộ PH-004; `kg_query_datasource` bị tắt cho user này.
- **Scenario**: no-action ≤ expected khi finding xấu; 4 preset ra 4 kết quả khác nhau trên dữ liệu demo.
- **LAAM**: unit test evaluator, rule (ngưỡng, min_sample, cooldown, dedup), priority score; Holt-Winters trên chuỗi đã biết; backtest chọn baseline khi model thua; scenario tất định; grounding check bắt số bịa.
- **Ground truth**: chạy analysis trên `pharmacy_demo` ⇒ phải tìm lại mọi finding có ✅ trong bảng độ phủ (§7.3) + kịch bản margin cài ở P0; không có finding critical giả.
- **Tính chung**: bật chỉ pack `retail` cho cùng dữ liệu ⇒ chạy được, không lỗi, rule pharmacy tắt đúng; grep core không có từ khoá ngành.
- **E2E**: Playwright chạy 14 bước demo (request Part 2 §15).

---

## 14. Chuyển từ dữ liệu demo sang dữ liệu thật của khách hàng

Mục tiêu thiết kế: **chuyển sang khách thật chủ yếu là cấu hình, không viết lại engine**. Checklist vận hành đầy đủ (kèm các mục bảo mật/pháp lý để sau): `docs/superpowers/runbooks/2026-10-02-real-customer-data-onboarding.md`. Dưới đây là những gì giữ nguyên, những gì chỉ cần cấu hình, và những gì có thể phải code thêm.

### 14.1 Không thay đổi
- Metric SQL, evidence SQL, rule, scenario, forecast config trong pack `retail`/`pharmacy`.
- Engine LAAM (rule, nguyên nhân, confidence, forecast, scenario, briefing), 4 tool `kg_*`, UI Home.
- Cách tính đã chốt (aggregation, lookback, target theo kỳ, grounding check).

### 14.2 Chỉ cấu hình (mỗi khách hàng)
| Việc | Ở đâu |
|---|---|
| Kết nối DB của khách (read-only, ưu tiên replica) | DAAB data source (đã có) |
| **Mapping** bảng/cột của khách → entity canonical, chuẩn hoá enum | `mapping.yaml` — LLM đề xuất từ schema đã sync, người duyệt |
| Chọn pack (`retail`, `pharmacy`…) | `pack_install` |
| Múi giờ, ngôn ngữ, user sở hữu job | `business_project` |
| KPI target | Upload file "Dữ liệu bảng" |
| Ngưỡng, trọng số ưu tiên, preset kịch bản theo khách/chi nhánh | `rule_override` |
| User, persona, chi nhánh được xem | `user_scope` |
| Giờ chạy hằng ngày, lookback theo metric | `analysis_job`, header metric / override |

### 14.3 Có thể phải code thêm (tuỳ khách)
| Trường hợp | Việc cần làm | Ghi chú |
|---|---|---|
| DB không phải Postgres (MSSQL, MySQL) | Thêm dialect cho bước sinh CTE + đổi tham số | Pack SQL viết theo tập SQL chung để không phải sửa |
| Khách có dữ liệu mà canonical chưa có (ví dụ NDC, lô/hạn dùng, PBM) | Mở rộng entity trong pack (nâng version pack) | Không sửa core (D6, D10) |
| Nguồn xoá lịch sử sớm, cần join nhiều hệ thống, hoặc chỉ có file/SFTP | Bật `landed` / reference pushdown / SFTP | Đã chừa điểm nối (§12b) |
| DB chậm hoặc dữ liệu lớn (query > 30s, > giới hạn dòng) | Index/replica phía khách; chia cửa sổ nhỏ hơn; timeout riêng theo metric | Runner đã coi cắt dòng là lỗi, không âm thầm sai |
| Định dạng file lạ (nhiều header, ô gộp, nhiều bảng trong một sheet) | Bổ sung parser/tuỳ chọn upload | — |

### 14.4 Bắt buộc trước khi dùng dữ liệu thật (không cần cho demo)
- **DAAB tự kiểm tra quyền chi nhánh** và biết user cuối (mỗi user một key, hoặc header acting-user có ký) — I9, §12b.
- **Chặn request không xác thực** đang được cho qua `requireProjectAccess` (I9).
- **Che cột thông tin cá nhân** trong evidence (tên, SĐT, ngày sinh của khách/bệnh nhân) theo cấu hình mapping; không đưa các cột này vào `metric_value`.
- Rà lại dữ liệu nào được gửi tới LLM (chỉ số tổng hợp, không gửi dòng dữ liệu cá nhân). Phần bảo mật/pháp lý chi tiết: **để sau, làm riêng khi triển khai** (theo quyết định 2026-09-28).

### 14.5 Dữ liệu thật "bẩn" hơn dữ liệu demo — cần quy trình, không cần đổi thiết kế
- **Enum và giá trị lạ** (trạng thái viết khác nhau, NULL, mã chi nhánh không khớp) ⇒ mapping chuẩn hoá + báo cáo validation; giá trị không map được ⇒ `data_status = incomplete`, không âm thầm bỏ qua.
- **Thiếu dữ liệu** ⇒ metric/rule phụ thuộc tự tắt và hiện lý do (đã có trong thiết kế).
- **Ngưỡng chưa phù hợp với khách** ⇒ **giai đoạn chạy thử (shadow mode) 2–4 tuần**: hệ thống sinh finding nhưng chỉ team nội bộ + người phụ trách phía khách xem, chỉnh `rule_override`, rồi mới bật brief cho toàn bộ user.
- **Không có đáp án sẵn như `expected_findings.csv`** ⇒ đo chất lượng bằng feedback (tỉ lệ finding bị dismiss kèm lý do "không đúng"), và backtest dự báo trên lịch sử thật của khách.
- **Lịch sử ngắn** ⇒ cổng lịch sử của forecast (§7.6) tự hạ độ tin cậy hoặc không dự báo.

### 14.6 Tài liệu (docs) của khách
- Chính sách, quy trình, hợp đồng, báo cáo dạng văn bản đi qua đường **"Tài liệu"** hiện có (Knowledge Sources → KG). Dùng cho Ask LAAM và làm ngữ cảnh khi diễn giải; **không** dùng để tính chỉ số.
- Tài liệu chứa bảng số (ví dụ bảng giá, target) ⇒ upload theo đường **"Dữ liệu bảng"**.
- Thiết kế này không thay đổi gì ở đường tài liệu.

### 14.7 Checklist onboarding một khách hàng thật
1. Tạo `business_project`, đặt múi giờ/ngôn ngữ/user sở hữu.
2. Kết nối DB (read-only, replica) → sync schema.
3. Chạy LLM đề xuất mapping → người duyệt → chạy validation, sửa đến khi `data_status` sạch.
4. Bật pack; upload target; khai báo `user_scope`.
5. Backfill metric (chia cửa sổ) → kiểm tra vài số đối chiếu với báo cáo khách đang dùng.
6. Shadow mode 2–4 tuần, chỉnh ngưỡng.
7. Bật brief cho user; theo dõi tỉ lệ dismiss và độ chính xác dự báo.
