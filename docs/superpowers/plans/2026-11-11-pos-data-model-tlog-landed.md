# POS Data Model & T-log Landed Ingestion — Implementation Plan (rev 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest POS t-logs from any vendor into one standard model, store them in a separate `landed` database, and let DAAB metrics / LAAM rules and NL→SQL run on them unchanged.

**Architecture:** Pack `retail`/`pharmacy` 0.7.0 extends the canonical model (additive). A separate DB `ennam_landed` holds industry-neutral `landed_record(entity, data jsonb)` rows written by a Python worker that reads a vendor file and applies a versioned crosswalk. DAAB gets a `landed` `SourceResolver`; pack SQL and LAAM do not change. NL→SQL reads per-project views through a per-project DB login role (tenant isolation enforced by DB grants, not session variables).

**Tech Stack:** Go stdlib `net/http` + `database/sql` + `lib/pq` + golang-migrate (`ennam.kg.go`); Python 3.12 + `asyncpg` + `defusedxml` + existing `kg_client` (`ennam.kg.python`); NextJS 16 + TanStack Query + shadcn (`ennam.kg.next`); YAML packs (`ennam.kg.packs`); Postgres 16; Redis lists.

**Spec:** `docs/superpowers/specs/2026-11-11-tlog-landed-ingestion-design.md` — read §2, §3 (L1–L14), §5, §5b, §9b–9f first.

**Rev 3 (2026-11-11):** second review — `sale_line` = item lines only + new `line_void` entity (protects existing metrics), view `security_barrier` + DB-level revokes + read-only role, writer concurrency/ordering, Go crosswalk loader + claim/finish endpoints + coalesced recalc, feed-prefixed IDs, unmapped `needs_fields` ⇒ unavailable, partition/retention mechanics, master feeds kept out of retention, `record.go` untouched.

**Rev 2 (2026-11-11):** rewritten after independent review — per-project DB roles (L5), `landed_key` + history table, role model, `needs_fields`/unavailable, `non_additive_dims`, worker contract via Go (L13), `/landed/*` routes + own queue (L14), enum override for RX (L10), fail-loud tests, AIOS-dependent work moved to Phase 2.

## Global Constraints

- Branches (user decision 2026-11-11): **every repo** (workspace root, go, python, next, packs, LAAM, admin, requirements) has `task/pos-data-model` created from the tip of `task/payment-subscription`. Consequences:
  - The POS PR in each repo contains payment's commits until payment is merged ⇒ **merge `task/payment-subscription` first**, then rebase `task/pos-data-model` onto `main` (or open the POS PR against `task/payment-subscription` until then).
  - Go migration chain stays linear: payment `000095` → ours `000096`.
  - Do not edit files payment owns (go: `internal/service/source_executor.go`, `nl_query.go`, `internal/models/ai_query.go`, `internal/bridge/*`; LAAM: billing/settings/drizzle; admin: everything) — this plan's only LAAM file is `receipt-format.ts` (+ test), untouched by payment; admin is not touched. If a task needs a payment-owned file, stop and flag.
  - Never commit on `task/payment-subscription`; before every commit `git branch --show-current` must print `task/pos-data-model`. Never `git add` a file that was dirty before your task.
- Core (`ennam.kg.go`, `ennam.kg.python` `landed_ingest`) MUST NOT contain industry words (`sale`, `refund`, `claim`, `pharmacy`, `rx`, `pos`, `tlog`…) in schema, code, routes, env names or prompts (spec D10, L14). Entity/field names arrive only from pack YAML / crosswalk.
- Canonical bump is **MINOR 0.7.0, additive only** (no entity/field removed or renamed).
- Env: `LANDED_DATABASE_URL` (maintenance), `LANDED_WRITER_URL`, `LANDED_ENGINE_URL`; queue `LANDED_QUEUE_NAME=ennam-kg:landed`.
- Missing source data ⇒ metric `unavailable`, never `0` (spec §9c R3). Cust is never summed across `function` (§9d).
- Retention default `25` months; monthly partitions on `business_date` + `DEFAULT` partition.
- UI copy: tab "POS data" / "Dữ liệu POS"; "Field matching"/"Ghép trường"; "Unmatched fields"/"Trường chưa ghép"; "Failed transactions"/"Giao dịch lỗi"; "Re-run this batch"/"Nhận lại lô này".
- Dev DB `:5433`. **Every DB-backed test must `t.Fatal`/`pytest.fail` when its env var is missing — no Skip** (`KG_TEST_DATABASE_URL`, `KG_TEST_LANDED_URL`, `PACKS_DIR`, `LANDED_TEST_URL`). Existing harness skips (`parity_pack_harness_test.go:87-95`, `testdb_test.go:19-21`): new tests call a `requireEnv(t, name)` helper instead.
- **Gate:** no real customer t-log until WS0 is closed (separate plan): `requireProjectAccess` unauthenticated pass-through (`authz.go:36-38`), branch-level authz I9, GenerateKG IDOR.

## Review Focus

1. **Tenant escape via NL→SQL** — SQL with no WHERE, SQL calling `set_config('app.project_id', <other>)`, SQL reading `landed_record`, a partition, or another project's view schema ⇒ zero foreign rows / permission denied → Task D2.
2. **Re-sent transaction with changed business date** ⇒ one current row, old copy in history, counters not doubled → Task B1 + C4.
3. **Hostile or huge file** (XXE, entity expansion, >256 MB, binary) ⇒ batch `failed` with code, worker keeps running → Task C2.
4. **Reversal/overlap counting** (cancel after line void, post void, partial refund, discount tie-break) ⇒ spec §9c exactly → Task A3.
5. **Field never sent by the POS** ⇒ metric `unavailable`, not 0 → Task A3 + B4.

---

## File Structure

| Repo | Path | Responsibility |
|---|---|---|
| packs | `retail/daab/canonical.yaml`, `pharmacy/daab/canonical.yaml` | 0.7.0 fields/entities/enums |
| packs | `retail/daab/metrics/sc_*.sql`, `sr_*.sql`, `evidence/*` ; `pharmacy/daab/metrics/rx_*.sql` | Sales Capture / Reducing |
| packs | `retail/daab/crosswalks/poslog-6.0.yaml` (+ `reconcile:` rules) | Crosswalk template (inside `daab/` ⇒ release layout unchanged) |
| packs | `docs/data-dictionary-0.7.0.md`, `docs/gap-aios-0.7.0.md` | Dictionary + Have/Partial/Missing |
| go | `internal/intel/header.go`, `engine/availability.go`, `engine/query.go` | `needs_fields`, `non_additive_dims` |
| go | `db/migrations/000096_landed_mode.*` | DAAB DB: mode `landed`, `data_sources.kind`, `project_landed_settings` |
| go | `db/landed_migrations/000001_init.*` | Landed DB: tables, roles, RLS, partitions |
| go | `internal/landed/` (`db.go`, `partitions.go`, `settings.go`, `projectrole.go`, `views.go`, `purge.go`) | Landed DB lifecycle |
| go | `internal/intel/landedsource/` (`resolver.go`, `table.go`) | `SourceResolver` (reuses `sqlexec`) |
| go | `internal/landedapi/` (`handler.go`, `service.go`, `store.go`) | `/api/v1/projects/{id}/landed/*` |
| python | `src/ennam_kg/landed_ingest/` (`readers/`, `crosswalk.py`, `validate.py`, `writer.py`, `handler.py`, `reaper.py`) | Worker pipeline |
| next | `src/app/(dashboard)/projects/[id]/pos-data/**`, `src/app/api/kg/projects/[id]/landed/upload/route.ts`, `src/components/pos-data/*`, `src/hooks/use-pos-data.ts` | UI + multipart upload route |
| LAAM | `src/components/intel/detail/receipt-format.ts` | Receipt labels |
| root | `docker-compose.yml`, `scripts/landed/init.sql`, `envfiles/*.env` | DB + roles + env |

---

## Plan A — Pack 0.7.0 + engine metric contracts · Phase 1, no AIOS dependency

### Task A0: Engine — `needs_fields` and `non_additive_dims`

**Files:** Modify `ennam.kg.go/internal/intel/header.go` (accept 2 optional keys), `internal/intel/types.go` (`MetricDef.NeedsFields []string`, `MetricDef.NonAdditiveDims []string`), `internal/intel/engine/availability.go`, `internal/intel/engine/query.go:300-330`. Test: `header_test.go`, `availability_test.go`, `query_test.go`.

**Interfaces — Produces:**
- `type FieldCoverage interface { HasField(ctx context.Context, projectID, entity, field string, since time.Time) (bool, error) }` — passed to `Availability`; `nil` ⇒ every field assumed present (live/file behaviour unchanged).
- `Availability(cat, mappings, cov FieldCoverage, since time.Time)`: a `needs_fields` field **not mapped** (any mode) ⇒ disabled `Reason = "field <entity.field> is not mapped"`; mapped but coverage says never sent in window (landed) ⇒ `Reason = "source does not send <entity.field>"`. Result surfaces through the existing `metric_disabled` error with that reason (spec R3(d) aligned to engine behaviour).
- `header.go` rejects unknown header keys (`header.go:13-16`) ⇒ **A0 must be deployed before packs 0.7.0 reach any server** (release note).
- Query: `group_by` that omits any `NonAdditiveDims` dim ⇒ error `ErrNonAdditiveRollup` (HTTP 400 `non_additive_rollup`).

- [ ] **Step 1:** failing tests `TestHeaderParsesNeedsFields`, `TestAvailabilityUnavailableWhenFieldNeverSent`, `TestAvailabilityNilCoverageUnchanged`, `TestAvailabilityUnmappedNeededFieldDisables` (file mode, `entry_method` not mapped ⇒ `sc_keyed_items` disabled, not 0), `TestQueryRejectsRollupOverNonAdditiveDim`.
- [ ] **Step 2:** `go test ./internal/intel/...` → FAIL. **Step 3:** implement. **Step 4:** PASS + `go test -race ./internal/intel/...`. **Step 5:** commit `feat(intel): needs_fields and non_additive_dims metric headers`.

### Task A1: Canonical 0.7.0 — retail

**Files:** `retail/daab/canonical.yaml`, `retail/pack.yaml` (`0.7.0`), `CHANGELOG.md`. Test: `ennam.kg.go/internal/intel/pack_070_test.go`.

**Interfaces — Produces** (`*` = required; every field has an English `description`):
- `location` + `address`, `phone`
- `sale` + `terminal_id`, `ended_at`, `transaction_type`, `training_flag` boolean, `manager_id`, `loyalty_id`, `total_due`, `change_due`
- `sale_line` (**item lines that were sold only** — never discount/tax/tender lines, never line-voided lines; existing metrics such as `cogs.sql`, `net_sales`, `gross_margin` sum every `sale_line` row and require `product_id`) + `location_id`, `terminal_id`, `employee_id`, `sold_at` timestamp (shared keys, AIOS rule 4), `line_seq` integer, `line_at`, `upc`, `description`, `weight`, `extended_amount`, `department`, `entry_method`, `reason_code`, `orig_sale_ref`, `promo_type`
- new `line_void`: `line_void_id` key, `sale_id`*, `location_id`*, `terminal_id`, `employee_id` (cashier of the transaction), `approver_id`, `voided_at`*, `product_id`, `line_seq`, `amount`*, `item_count`, `reason_code`
- `void` (**transaction-level only**: cancel / post void — keeps `void_rate` meaning) + `sale_id`, `terminal_id`, `void_kind`, `reason_code`, `item_count`
- AIOS "line type" (item/discount/coupon/tender/tax) is represented by the entity a line lands in (`sale_line`, `sale_adjustment`, `tender`, sale `tax_amount`) — recorded in the gap file
- `refund` + `terminal_id`, `reason_code`, `item_count`
- `price_override` + `terminal_id`, `reason_code`, `quantity`
- new `tender`: `tender_id` key, `sale_id`*, `location_id`*, `terminal_id`, `employee_id`, `tendered_at`*, `tender_seq` integer, `tender_type`*, `amount`*
- new `sale_adjustment`: `adjustment_id` key, `sale_id`*, `sale_line_id`, `location_id`*, `terminal_id`, `employee_id`, `adjusted_at`*, `adjustment_type`*, `amount`*, `item_count`, `reason_code`
- new `register_event`: `event_id` key, `location_id`*, `terminal_id`, `employee_id`, `event_at`*, `event_type`*, `amount`, `duration_sec`, `sale_id`
- enums: `sale_line.entry_method [scanned, keyed]`; `sale_line.promo_type [hosted_tpr, manual]`; `void.void_kind [transaction_cancel, post_void]`; `sale.transaction_type [sale, return, exchange, no_sale, training]`; `sale_adjustment.adjustment_type [item_discount, total_discount, employee_discount, store_coupon, vendor_coupon, e_coupon, tax_exempt, tax_modify]`; `register_event.event_type [no_sale, not_on_file, suspend, recall, paid_in, paid_out, paid_out_lotto, paid_out_gun_buyback, paid_out_used_games, paid_out_buyback, gift_card_activate, gift_card_renew, mgmt_intervention, training, lock, ring_time, tender_time, idle_time, other_time, total_time]`

- [ ] **Step 0:** change `loadPacks` in `parity_pack_harness_test.go` to `t.Fatalf` (not `Skipf`) when `PACKS_DIR` is set but the registry fails to load.
- [ ] **Step 1:** `TestPack070Catalog` (uses `requireEnv(t,"PACKS_DIR")`): version `0.7.0`; new entities exist; listed new fields exist; **every 0.6.0 entity and field still exists** (literal list copied from the 0.6.0 file); `TestExistingMetricsUnchangedOnGolden070` — `cogs`, `net_sales`, `gross_margin`, `discount_rate`, `void_rate` give the same values on a 0.6.0-shaped dataset before and after adding 0.7.0 rows of the new entities.
- [ ] **Step 2:** `cd ennam.kg.go && PACKS_DIR=../ennam.kg.packs go test ./internal/intel -run TestPack070Catalog` → FAIL.
- [ ] **Step 3:** edit YAML + CHANGELOG.
- [ ] **Step 4:** PASS; `PACKS_DIR=../ennam.kg.packs KG_TEST_DATABASE_URL=… go test ./internal/intel/...` PASS (no SKIP lines: `go test -v … | grep -c SKIP` = 0 for new tests); `bash _scripts/release_test.sh` PASS.
- [ ] **Step 5:** commit both repos.

### Task A2: Pharmacy 0.7.0 — RX layer (built, enabled only after Q4 + legal)

**Files:** `pharmacy/daab/canonical.yaml`, `pharmacy/pack.yaml` (`0.7.0`), CHANGELOG. Test: `pack_070_test.go`.

**Interfaces — Produces:** `extend: true` + `is_rx` boolean on `sale`, `sale_line`, `line_void`, `tender`, `void`, `refund`, `sale_adjustment`, `register_event`; pharmacy **redeclares** enums (override, `pack.go:525`): `register_event.event_type` = retail list + `pharmacist_intervention`, `paid_out_delivery_fee`; `sale_adjustment.adjustment_type` = retail list + `copay_refusal`.

- [ ] Steps: `TestPack070Pharmacy` (pharmacy catalog has `is_rx` on all 8 entities and the extra enum values; retail-only catalog has neither) → FAIL → edit → PASS → commit.

### Task A3: Sales Reducing metrics + golden counting tests

**Files:** `retail/daab/metrics/sr_value.sql`, `sr_cust.sql`, `sr_items.sql`, `sr_total_value.sql`, `sr_total_cust.sql`, `sr_total_items.sql`, `evidence/sr_value.sql`. Test: `ennam.kg.go/internal/intel/filedata/parity_pack_070_test.go`, data `testdata/golden_070/*.csv`.

**Interfaces — Produces:**
- `retail.sr_value|sr_cust|sr_items`: `grain: day`, `dims: [location_id, terminal_id, employee_id, function]`, `non_additive_dims: [function]` (on `sr_cust` only), `aggregation: additive`; `function ∈ {line_void, transaction_cancel, post_void, refund, price_modify, item_discount, total_discount, employee_discount, store_coupon, vendor_coupon, e_coupon, tax_exempt, tax_modify}`.
- `retail.sr_total_*`: dims `[location_id, terminal_id, employee_id, function_class]`, `function_class ∈ {shrink, margin, tax}`, Cust = COUNT DISTINCT sale per class.
- `needs_fields` on each metric = fields its SQL reads beyond keys. Availability is per metric (one missing field disables the whole metric — accepted; `sr_items` only lists `item_count` fields).
- `employee_id` dim = **cashier of the transaction** for every reducing function (approver/manager is a separate field, never a dim of `sr_*`) ⇒ Cust adds correctly across employees.
- `line_void` function reads entity `line_void`; `transaction_cancel`/`post_void` read `void`.

- [ ] **Step 1: golden tests** `TestSalesReducingGolden` (rows loaded via file-mode harness):
  - T1: lines A $10, B $20, C $30 with price modify −$5 on C; line void A; cancel ⇒ `line_void` 10/1/1; `transaction_cancel` 45/2/1; no `price_modify` row; `sr_total(shrink)` 55/3/**1**.
  - T2 completed then post-voided (net $40, 3 units) ⇒ `post_void` 40/3/1.
  - R1 refunds 1 of 3 units of a $12 line of T3 on a later date ⇒ `refund` 12/1/1 on R1's date.
  - T4 has one employee discount and one store coupon on different lines ⇒ each counted once in its own function, `sr_total(margin)` Cust 1.
  - T5 training ⇒ no `sr_*` rows.
  - `TestSrCustRollupOverFunctionRejected` ⇒ query error `non_additive_rollup`.
- [ ] **Step 2:** FAIL. **Step 3:** write SQL. **Step 4:** PASS. **Step 5:** commit.

### Task A3b: Sales Capture + RX metrics + reconciliation

**Files:** `retail/daab/metrics/sc_gross_sales.sql`, `sc_net_sales_tlog.sql`, `sc_tax.sql`, `sc_txn_count.sql`, `sc_customer_count.sql`, `sc_items_sold.sql`, `sc_scanned_items.sql`, `sc_keyed_items.sql`, `sc_event_value.sql`, `sc_event_cust.sql`, `sc_event_items.sql`, `sc_event_duration.sql`, `sc_savings.sql`; `pharmacy/daab/metrics/rx_sc_*.sql` and `rx_sr_*.sql` (same SQL filtered `is_rx`, incl. timing, scanned/keyed, tax). Test: extend `parity_pack_070_test.go`.

**Interfaces — Produces:** dims `[location_id, terminal_id, employee_id]` (+ `event_type` for `sc_event_*`); `sc_customer_count` = distinct sales with status completed (AIOS "Customer count"); `sc_keyed_items` `needs_fields: [sale_line.entry_method]`; `sc_event_duration` `needs_fields: [register_event.duration_sec]`; training transactions excluded except `sc_event_*(training)`; retail metrics include RX rows (store rollup), `rx_*` filter `is_rx = true`.

- [ ] **Step 1:** tests `TestSalesCaptureGolden` (suspend $30/2 items then recalled ⇒ suspend 30/1/2 and recall 30/1/2; gift card activate $50 ⇒ 50/1; paid_out_lotto $20; ring_time 95 s; qty-3 line ⇒ items 3; weighed 1.25 kg ⇒ items 1; split tender $10+$15 on one $25 sale ⇒ txn_count 1), `TestRxSplitRollup` (2 RX + 3 non-RX ⇒ `rx_sc_txn_count` 2, `sc_txn_count` 5), `TestSummaryReconciles` (Σ metric over all dims == direct aggregate of golden detail), `TestKeyedItemsUnavailableWithoutEntryMethod` (coverage fake says field never sent ⇒ metric disabled, reason `source does not send sale_line.entry_method`).
- [ ] Steps 2–5: FAIL → SQL → PASS → commit.

### Task A4: Data dictionary + AIOS gap

**Files:** `ennam.kg.packs/docs/data-dictionary-0.7.0.md`, `docs/gap-aios-0.7.0.md`; generator test `ennam.kg.go/internal/intel/dictionary_test.go`.

- [ ] **Step 1:** `TestDictionaryUpToDate` renders Markdown from the merged catalog and **fails if it differs** from the committed file (`-update` flag rewrites it).
- [ ] **Step 2:** gap file: every AIOS element → canonical field(s) + `Have | Partial | Missing` + note.
- [ ] **Step 3:** run test → PASS; commit.

### Task A5: POSLog crosswalk template + reconcile rules

**Files:** `retail/daab/crosswalks/poslog-6.0.yaml`. Test lives in C3.

**Interfaces — Produces (crosswalk schema used by C2–C4, E3):**
```yaml
crosswalk: <name>
version: <semver>
canonical: <pack>@<version>
extends: <crosswalk>                # optional overlay
reader: {type: xml|json|delimited|fixed_width, transaction: <path>, namespaces: {...}, ...}
entities:
  <entity>:
    each: <path>                    # relative to transaction or to parent
    parent: <entity>                # optional
    natural_key: [<path>, ...]      # stored as normalized JSON array text
    ids: {<id field>: [<path>, ...]}  # composite IDs, e.g. sale_id: [store, terminal, business_day, sequence]
    refs: [<field>, ...]            # fields referencing another entity's id (sale_id on lines, orig_sale_ref)
    business_date: <path>
    fields: {<canonical field>: <path> | "=literal" | "parent.<field>"}
    enum_map: {<field>: {<source>: <canonical>}}
reconcile:                          # pack-owned rules, core evaluates (spec R4)
  - name: <id>
    entity: <entity>
    expr: <restricted expression over fields/children, e.g. "abs(sum(children.sale_line.extended_amount) - net_amount) <= 0.01">
```
- Core prefixes every `ids`/`refs` value with the feed's short id (`<feed8>:` + JSON of parts) ⇒ IDs unique per project across feeds and across register/day sequence resets.
- [ ] Write template (header, LineItem Sale/Return/Void ⇒ `sale_line` / `line_void`, Tender, Discount/Coupon ⇒ `sale_adjustment`, ControlTransaction no-sale/paid in/out, Total) + reconcile rules (header↔footer keys, Σ lines = net). Commit.

### Task A6: Go crosswalk loader & validation

**Files:** `ennam.kg.go/internal/intel/crosswalk.go` (+ `pack.go` loads `daab/crosswalks/*.yaml` into `Pack.Crosswalks`), test `crosswalk_test.go`; `ennam.kg.packs/_scripts/release_test.sh` asserts `daab/crosswalks/` is in the tarball.

**Interfaces — Produces:** `type Crosswalk struct{Name, Version, Canonical, Extends string; Reader map[string]any; Entities map[string]CrosswalkEntity; Reconcile []ReconcileRule}`; `func (r *Registry) Crosswalk(name string) (*Crosswalk, bool)`; `func MergeCrosswalk(base *Crosswalk, overrideYAML []byte) (*Crosswalk, error)`; validation: every target entity/field exists in the merged catalog, enum_map targets are valid enum values, `canonical` pack@version matches a loaded pack.

- [ ] Steps: tests `TestLoadPoslogTemplate`, `TestCrosswalkUnknownFieldRejected`, `TestOverrideMerge`, `TestReleaseTarballHasCrosswalks` → FAIL → implement → PASS → commit.

---

## Plan B — Landed DB & DAAB integration · Phase 1

### Task B1: Landed DB — roles, tables, RLS, partitions

**Files:** root `docker-compose.yml` (create DB `ennam_landed` + roles via `scripts/landed/init.sql`), `envfiles/kg-server.env`, `envfiles/kg-worker.env` (append env with `# NEW: landed store`), `ennam.kg.go/db/landed_migrations/000001_init.{up,down}.sql`, Makefile `landed-migrate`. Test: `ennam.kg.go/internal/landed/schema_integration_test.go`.

**Interfaces — Produces:** tables per spec §5 (`ingest_feed`, `ingest_batch`, `landed_record` partitioned + `DEFAULT`, `landed_key`, `landed_record_history`, `landed_unmapped`, `landed_reject`, `feed_field_coverage`, `ingest_crosswalk_override`, `sync_state`); roles `landed_maintenance`, `landed_writer`, `landed_engine`; RLS `ENABLE`+`FORCE` on every table and partition; policies `project_isolation` (`TO landed_writer, landed_engine`, `NULLIF(current_setting('app.project_id', true),'')::uuid`) and `maintenance_all` (`TO landed_maintenance USING (true)`); no grants on partitions except maintenance. Database level: `REVOKE CONNECT, TEMP ON DATABASE ennam_landed, ennam_kg, pharmacy_demo FROM PUBLIC` then `GRANT CONNECT` only to the roles that need each DB; `REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC` in `ennam_landed`; `REVOKE CREATE ON SCHEMA public FROM PUBLIC`.

- [ ] **Step 1:** tests `TestEngineSeesOnlyOwnProject`, `TestEngineWithoutSettingSeesNothing` (no error on `''`), `TestEnginePartitionDirectDenied`, `TestWriterCannotDrop`, `TestKeyUniqueAcrossDates` (same natural key, two business dates ⇒ second insert conflicts on `landed_key`).
- [ ] Steps 2–5: FAIL (`KG_TEST_LANDED_URL` required) → migration → PASS → commit.

### Task B2: Partitions, settings, DAAB migration 000096

**Files:** `internal/landed/{db.go,partitions.go,settings.go}`, `db/migrations/000096_landed_mode.{up,down}.sql`. Tests: `partitions_integration_test.go`, `settings_integration_test.go`.

**Interfaces — Produces:**
- `func Open(url string) (*sql.DB, error)` via `pq.NewConnector` + `sql.OpenDB`.
- `func EnsurePartitions(ctx, db, from, to time.Time) error` — each new partition gets `ENABLE` + `FORCE ROW LEVEL SECURITY` and no grants.
- `func DrainDefault(ctx, db) (int, error)` — one transaction per month found in DEFAULT: `LOCK` DEFAULT, copy that month's rows to a temp table, delete them from DEFAULT, create the partition, re-insert (Postgres refuses to create a partition while DEFAULT holds rows of its range).
- `func DropExpired(ctx, db, retention map[uuid.UUID]int, store storage.ObjectStorage, now time.Time) (Report, error)` — per project, batched `DELETE` (10k rows/stmt) from `landed_record`, `landed_key`, `landed_record_history` for rows of **stream feeds** older than retention, plus their raw objects; rows of **master feeds** (`ingest_feed.kind = 'master'`) are kept; a partition is dropped only when it has no rows left for any project. Partition pruning on read is a known follow-up (entity CTE has no `business_date` predicate) — index `(project_id, entity, business_date)` covers P1 volumes.
- 000096: `project_mapping.mode` CHECK + `'landed'`; `data_sources.kind TEXT NOT NULL DEFAULT 'customer' CHECK (kind IN ('customer','system'))`; `project_landed_settings(project_id PK, enabled, retention_months DEFAULT 25, consent_note NOT NULL, enabled_by, enabled_at, instance DEFAULT 'default')`.
- `SettingsStore{Get, Enable(Settings) error /* rejects empty ConsentNote */, Disable}`.

- [ ] Steps: tests `TestEnsurePartitionsIdempotent`, `TestBackfillLandsInDefaultThenDrained`, `TestDropExpiredDeletesRowsAndRawObjects`, `TestDropExpiredKeepsMasterFeeds`, `TestNewPartitionHasForcedRLS`, `TestDrainDefaultWhileRowsPresent`, `TestEnableRequiresConsent` → FAIL → implement → PASS → `make db-migrate` up/down/up on `:5433` → commit.

### Task B3: `landed` SourceResolver

**Files:** `internal/intel/landedsource/{resolver.go,table.go}`; modify `internal/intel/sources/sources.go` (`Build(..., landed *landedsource.Resolver)`), `cmd/kg-server/intel_wiring.go`, `cmd/kg-packs/main.go`. Tests in package + `parity_integration_test.go`.

**Interfaces:**
- Consumes `intel.SourceResolver`, `intel.SourceTable`, `sqlexec.New` (`internal/intel/sqlexec`) — extend `sqlexec` with option `WithSessionSetting("app.project_id", id)` executed inside its existing read-only tx (engine SQL only — pack-authored, never AI SQL).
- Produces `NewResolver(engineDB *sql.DB, canonical filedata.CanonicalSource, cov intel.FieldCoverage, timeout time.Duration) *Resolver`; `Table.Relation() = "landed_record AS src"`; `Filter() = "src.project_id = '<uuid>' AND src.entity = '<entity>'"` (validated identifiers only); `ColumnSQL` = typed cast of `src.data->>'f'` reusing `filedata` cast helper (export it if unexported); `Watermark` = max `ingest_batch.finished_at`.

- [ ] Steps: tests `TestLandedTableRejectsBadEntity`, `TestLandedParityWithFileMode` (golden_070 via file vs landed ⇒ identical `metric_value` for every 0.7.0 metric), `TestEngineSessionScopedToProject` → FAIL → implement → PASS (`-race`) → commit.

### Task B4: Mode `landed` everywhere + autofill + coverage

**Files:** `internal/intel/admin/mapping_binders.go`, `mapping_check.go`, `mapping_marshal.go`, `mapping_parse.go`, `mapping_coverage.go`, `internal/intel/mapping_file.go`, `internal/intel/mapdraft/*`, `internal/intel/engine/availability.go` caller wiring (`FieldCoverage` from `feed_field_coverage`). Tests: existing files + `mapping_landed_test.go`.

**Interfaces — Produces:** `POST /api/v1/projects/{id}/mapping/landed-autofill` (project admin; 409 `landed_disabled`) writes approved `{mode: landed, spec:{from:<entity>, fields:{f:f}}}` for every catalog entity.

- [ ] Steps: tests `TestMappingFileAcceptsLanded`, `TestParseErrorsMentionLanded`, `TestAutofillOneToOne`, `TestAutofillRefusedWhenDisabled`, `TestMixedLiveLandedDisablesJoinMetric`, `TestCoverageWiredForLandedOnly` → FAIL → implement → PASS → commit.

---

## Plan C — Ingestion · Phase 1 (XML/POSLog + upload/API); other formats & drops Phase 2

### Task C1: Landed API + queue + reaper

**Files:** `internal/landedapi/{store.go,service.go,handler.go}`; register in `cmd/kg-server/main.go`; `internal/queue`: publisher for `LANDED_QUEUE_NAME` with `LandedBatchMessage{Type:"landed_batch", ProjectID, BatchID string}`. Next: `src/app/api/kg/projects/[id]/landed/feeds/[feedId]/batches/route.ts` **streams** the request body to Go (`fetch(url, {method:'POST', body: req.body, duplex:'half', headers:{content-type}})`) — no `formData()` buffering, no `req.text()`. Tests: `internal/landedapi/*_test.go`.

**Interfaces — Produces** (project admin unless noted; 409 `landed_disabled` when off):
- `POST|GET /api/v1/projects/{id}/landed/feeds` — feed `{name, vendor, crosswalk, delivery: upload|api}` / list with `{today_count, last_batch_at, attention_count, status: ok|attention|stopped}`
- `POST /api/v1/projects/{id}/landed/feeds/{feedId}/batches` multipart `file` (max `MaxBatchBytes = 256<<20`) → ObjectStorage key `landed/<project>/<feed>/<batch>/<name>`; same sha256 on same feed ⇒ 200 existing batch, no enqueue
- `GET …/feeds/{feedId}/batches`, `POST …/batches/{batchId}/replay`, `GET …/batches/{batchId}/file` (worker download via `kg_client`)
- Worker-only (service key of `kg_client`): `POST …/batches/{batchId}/claim` (`queued → processing`, returns job payload; 409 if not queued) and `POST …/batches/{batchId}/finish` `{status, counts, rejected_days, min_business_date, max_business_date, error?}`. `finish` records `data_status` issues (`issues.rejected_days`) and schedules recalculation **inside Go**: merges `[min,max]` into a per-project pending range and calls the existing recalculation service with explicit `from`/`to`; if a run is in progress (today 409 `recalculation_running`, `intel_metrics_admin.go:176-208`) the pending range runs right after it (coalesced) — worker never calls `/metrics/recalculate`.
- `ingest_feed.kind ∈ {stream, master}` (C7 creates master feeds).
- `GET …/landed/unmapped?feed=`, `GET …/landed/rejects?batch=`, `GET|PUT …/feeds/{feedId}/crosswalk`
- Job payload built by Go with A6 (`Registry.Crosswalk` + `MergeCrosswalk`): `{batch_id, project_id, feed_id, feed_short_id, received_at, catalog: {entities, enums}, crosswalk: <merged YAML>, crosswalk_version}`, returned by `claim`.
- **System admin only, fail-closed** (no identity ⇒ 401): `PUT /api/v1/projects/{id}/landed` `{enabled, retention_months, consent_note, purge?}`.
- Reaper (in kg-server scheduler, **maintenance role** — scans across projects): batches `processing` > 30 min ⇒ `failed` `reason: timeout`.

- [ ] Steps: tests `TestUploadDuplicateShaIdempotent`, `TestUploadRefusedWhenDisabled`, `TestEnableFailsClosedWithoutIdentity`, `TestEnableRequiresSystemAdmin`, `TestNonMember403`, `TestJobPayloadHasCatalogAndCrosswalk`, `TestReaperFailsStuckBatch`, `TestClaimOnlyOnce`, `TestFinishCoalescesRecalcWhileRunning`, `TestRoutesDoNotShadowKGIngest` → FAIL → implement → PASS → commit (go + next).

### Task C2: Readers (XML/POSLog in Phase 1)

**Files:** `ennam.kg.python/src/ennam_kg/landed_ingest/readers/{base.py,xml_reader.py}`; `defusedxml` in `pyproject.toml`. Test: `tests/landed_ingest/test_readers.py`, fixtures `tests/landed_ingest/fixtures/*.xml`.

**Interfaces — Produces (rev: C2 review ruling):** readers yield a DETACHED `xml.etree.ElementTree.Element` per transaction (Clark-notation names; all formats build Elements); `class Reader(Protocol): def iter_transactions(self, data: bytes) -> Iterator[Element]`; `def get_reader(cfg: dict) -> Reader`; errors `ReadError(code ∈ {too_large, malformed, forbidden_construct, binary_unsupported}, detail)`.

- [ ] Steps: tests `test_poslog_yields_each_transaction`, `test_rejects_xxe`, `test_rejects_entity_expansion`, `test_rejects_oversize`, `test_binary_rejected`, `test_malformed_reports_offset` → FAIL → implement (`defusedxml.ElementTree.iterparse`) → `uv run pytest tests/landed_ingest -q` PASS → commit.

### Task C3: Crosswalk engine

**Files:** `landed_ingest/crosswalk.py`. Test: `tests/landed_ingest/test_crosswalk.py` (template read from the job payload fixture, not from `PACKS_DIR`).

**Interfaces — Produces:** `Crosswalk.from_payload(yaml_text: str) -> Crosswalk`; `@dataclass(frozen=True) CanonicalRecord(entity, natural_key: str, business_date: date, data: dict)`; `UnmappedHit(path, sample)`; `def apply(cw: Crosswalk, txn: Node) -> tuple[list[CanonicalRecord], list[UnmappedHit]]`; natural key = `json.dumps(values, separators=(",",":"))`.

- [ ] Steps: tests `test_header_and_lines_mapped`, `test_parent_fields_copied_to_lines` (shared keys on sale_line), `test_enum_map_applied`, `test_unknown_path_unmapped`, `test_override_wins`, `test_natural_key_no_separator_collision` (`["a|b","c"]` ≠ `["a","b|c"]`), `test_discount_tie_break_employee_wins` (one source discount tagged employee+coupon ⇒ one record `employee_discount`) → FAIL → implement → PASS → commit.

### Task C4: Validate, reconcile, write

**Files:** `landed_ingest/validate.py`, `landed_ingest/writer.py`. Tests: `test_validate.py`, `test_writer_integration.py` (`LANDED_TEST_URL` required).

**Interfaces — Produces:**
- `validate(records, catalog: dict, reconcile_rules: list[dict]) -> tuple[list[CanonicalRecord], list[Reject]]` — types/required/enums from payload catalog; reconcile rules evaluated by a restricted evaluator (`ast`-whitelisted: names, attribute, `sum`, `abs`, `len`, comparisons, arithmetic) — no field names in core code.
- `LandedWriter(pool: asyncpg.Pool)`: `async upsert(project_id, source_id, batch_id, batch_received_at, records) -> WriteStats{inserted, unchanged, superseded, moved_date, stale_skipped}` — takes `pg_advisory_xact_lock(hashtext(project_id||source_id))` (one writer per feed), commits in chunks of 1,000 transactions, processes keys in sorted order, uses `INSERT … ON CONFLICT DO NOTHING` on `landed_key` then `SELECT … FOR UPDATE`; **supersedes only if `batch_received_at` > stored `landed_key.batch_received_at`** (replaying an old batch never overwrites newer content ⇒ `stale_skipped`); with `SET LOCAL app.project_id`: look up `landed_key`; same data ⇒ unchanged; different ⇒ copy to history, update (or delete+insert when `business_date` changed), bump version; update `feed_field_coverage`.

- [ ] Steps: tests `test_reconcile_rule_rejects_mismatch`, `test_missing_required_rejected`, `test_unknown_name_in_rule_is_config_error`, `test_same_batch_twice_unchanged`, `test_resent_in_new_batch_counted_once`, `test_changed_content_goes_to_history`, `test_business_date_change_moves_row_single_current`, `test_coverage_updated`, `test_two_concurrent_batches_same_feed_no_dup`, `test_replay_older_batch_does_not_overwrite_newer`, `test_feed_prefix_makes_ids_unique_across_feeds` → FAIL → implement → PASS → commit.

### Task C5: Worker handler + replay

**Files:** `landed_ingest/handler.py`; `src/ennam_kg/worker.py` (second consumer on `settings.landed_queue_name`, handler for `landed_batch`); `src/ennam_kg/config.py` (`landed_queue_name`, `landed_writer_url`); `kg_client` methods `claim_landed_batch`, `download_landed_batch`, `finish_landed_batch`. Test: `tests/landed_ingest/test_handler.py`.

**Interfaces — Consumes:** C1 job/file endpoints, C2–C4. **Produces:** batch `processing → done|failed` with counts `{ok, unchanged, superseded, rejected, unmapped}` via `finish_landed_batch`; unmapped upserted by `(feed_id, path)` with `count+1`; rejects ⇒ `data_status incomplete` for affected days (via finish payload); recalculation is scheduled by Go's `finish` (C1).

- [ ] Steps: tests `test_batch_done_counts`, `test_replay_new_crosswalk_supersedes`, `test_read_error_marks_failed_worker_continues`, `test_finish_sends_business_date_range` → FAIL → implement → PASS → commit.

### Task C6 (Phase 2, after AIOS Q1/Q2): other readers & drop receivers

- **C6a readers:** `json_reader.py`, `delimited_reader.py`, `fixed_width_reader.py` producing the same `Node` (tests `test_json_same_shape_as_xml`, `test_pipe_groups_lines_under_header`, `test_fixed_width_slices`, `test_unknown_record_type_unmapped`).
- **C6b receivers:** `receivers/{sftp_drop.py,s3_drop.py}` polling every `LANDED_DROP_POLL_SECONDS` (300), posting to C1 upload endpoint via `kg_client`; credentials encrypted like data-source credentials; **SSRF guard** rejects private/loopback/link-local hosts; processed files moved, never deleted (tests `test_posts_new_file_once`, `test_private_host_rejected`, `test_bad_credentials_feed_stopped`).

### Task C7: Master data upload into landed

**Files:** `internal/landedapi/master.go` — `POST /api/v1/projects/{id}/landed/master/{entity}` creates/uses the project's master feed (`kind='master'`) and a batch exactly like C1; Python worker reads it with a `tabular` reader (reuses `ingestion/tabular/reader.py`) and the **same C4 writer** (`natural_key` = entity key field, `business_date` = upload date). No second write path in Go. Tests: `TestMasterUploadReplacesSnapshot`, `TestMasterUnknownEntity400`, `TestMarginMetricEnabledAfterProductUpload` → FAIL → implement → PASS → commit.

### Task C8: Retention job & revoke purge

**Files:** `internal/landed/purge.go`; daily job in `cmd/kg-server/main.go` (`EnsurePartitions(now-1m, now+2m)`, `DrainDefault`, `DropExpired`). **Interfaces:** `PurgeProject(ctx, maintDB, store, projectID) (PurgeReport, error)` — deletes landed/ingest rows, raw objects, project role + view schema (D1/D2), keeps `metric_value`, writes activity log. Called by `PUT …/landed {enabled:false, purge:true}`. Tests `TestPurgeRemovesEverythingKeepsMetrics`, `TestRetentionPerProject` → FAIL → implement → PASS → commit.

---

## Plan D — NL→SQL on landed · Phase 2 (spec §7 P2)

### Task D1: Per-project role + view schema

**Files:** `internal/landed/projectrole.go`, `internal/landed/views.go`. Tests `projectrole_integration_test.go`, `views_integration_test.go`.

**Interfaces — Produces:**
- `EnsureProjectRole(ctx, maintDB, projectID) (dsn string, err error)` — `CREATE ROLE lp_<hex> LOGIN NOBYPASSRLS NOINHERIT CONNECTION LIMIT 5 PASSWORD '<SCRAM-SHA-256 verifier computed in Go>'` (never plaintext in DDL/logs); `ALTER ROLE lp_<hex> SET default_transaction_read_only = on` (covers the Python agentic path that runs without a read-only tx, `db_client/client.py:57-59`); `ALTER ROLE … SET statement_timeout = '30s'`; `GRANT CONNECT ON DATABASE ennam_landed` only; `GRANT USAGE ON SCHEMA pv_<hex>`; `GRANT SELECT ON ALL TABLES IN SCHEMA pv_<hex>`; `ALTER ROLE lp_<hex> SET search_path = pv_<hex>`; rotates password when called again.
- `SyncViews(ctx, maintDB, projectID, catalog)` — schema `pv_<hex>` owned by `landed_maintenance`; one view per entity `WITH (security_barrier = true)`, typed casts, **literal** `WHERE project_id = '<uuid>' AND entity = '<entity>'`, no `security_invoker`; re-`GRANT SELECT` after every (re)create; drops views of entities no longer in catalog; called on enable and on pack version change.

- [ ] Steps: tests `TestViewsTypedColumns`, `TestViewsDroppedWhenEntityRemoved`, `TestProjectRoleCannotReadBaseOrPartitions`, `TestProjectRoleCannotUseOtherSchema`, `TestProjectRoleCannotConnectToDAABDatabase`, `TestProjectRoleIsReadOnly`, `TestViewIsSecurityBarrier` (`pg_class.reloptions` contains `security_barrier=true`), `TestErrorLeakFilterDoesNotRevealOtherProject` (`SELECT * FROM pv_P1.sale_line WHERE upc::int = 0` never errors with a P2 value) → FAIL → implement → PASS → commit.

### Task D2: System data source using the project role

**Files:** `internal/models/datasource.go` (`Kind`), data source store/handlers (409 on edit/delete when `kind='system'`; hidden fields), enable flow in `landedapi` creates/rotates source `Landed (system)` with the `lp_` DSN (encrypted as today); disable/purge removes it. Schema sync works unchanged on the view schema.

- [ ] **Step 1:** tests `TestSystemSourceCreatedOnEnable`, `TestSystemSourceNotEditable`, and **attack tests via the NL-query executor and via a raw DSN connection (Python path)**: `SELECT count(*) FROM landed_record` ⇒ permission denied; `WITH x AS (SELECT set_config('app.project_id','<P2>',true)) SELECT count(*) FROM x, sale` ⇒ only P1 rows; `SELECT * FROM pv_<P2>.sale` ⇒ permission denied; `SELECT * FROM landed_record_y2026m11` ⇒ permission denied.
- [ ] Steps 2–5: FAIL → implement → PASS → commit → `security-reviewer` agent on Plans B–D diff; fix CRITICAL/HIGH.

---

## Plan E — UI (`ennam.kg.next`) & LAAM · Phase 1 (E1–E5), verification by lint/build + Chrome DevTools

### Task E1: Tab "POS data" + overview + enable
`layout.tsx` tab after "Data mapping"; `pos-data/page.tsx`; `hooks/use-pos-data.ts` over `/api/kg/projects/{id}/landed/*`; `components/pos-data/{feed-overview.tsx,landed-disabled-card.tsx}`. Disabled ⇒ explanation; system admin sees enable form (consent note required, retention). Enabled ⇒ feed cards with 3 numbers + status chip + "Add POS vendor".
- [ ] implement → `npm run lint && npm run build` → DevTools walkthrough → commit.

### Task E2: 4-step setup wizard
`components/pos-data/{setup-wizard,step-vendor,step-sample,step-match,step-delivery}.tsx`; sample upload uses the new multipart route; preview 3 transactions as receipts; read errors shown in plain words (binary ⇒ "Ask the vendor to export XML, JSON or text").
- [ ] implement → lint/build → walkthrough with `fixtures/poslog_small.xml` → commit.

### Task E3: Field matching + attention lists
`components/pos-data/{field-matching,unmatched-list,failed-list,batch-list}.tsx` — needs-review rows first, done rows collapsed, sample value per row, Have/Partial/Missing; click unmatched ⇒ pick canonical field ⇒ PUT crosswalk; "Re-run this batch".
- [ ] implement → lint/build → walkthrough → commit.

### Task E4: Data mapping, Data Sources, master upload
Mapping page: source option "POS data (stored)", button "Use POS data for all" (autofill), unavailable/disabled reasons in plain words with fix link (e.g. "Upload product list"); master-data upload card (C7); Data Sources: system row badge, no edit/delete (Phase 2 when D lands).
- [ ] implement → lint/build → walkthrough → commit.

### Task E5: LAAM receipt labels
`LAAM/src/components/intel/detail/receipt-format.ts` + test for `terminal_id`, `line_seq`, `entry_method`, `reason_code`, `upc`, `description`. `internal/intel/engine/record.go` is **not** changed (adding entity names to core would break D10); tenders stay visible through evidence.
- [ ] failing test → implement → `npm test -- receipt-format` PASS → commit.

---

## Plan F — Verification & handover

### Task F0: Pharmacy demo → POSLog exporter (test data, user decision 2026-11-11)

**Files:** workspace `scripts/demo_data/export_poslog.py` + `scripts/demo_data/tests/test_export_poslog.py` (stdlib `xml.etree` only — do **not** touch the pre-existing dirty `pyproject.toml` / `uv.lock`). Output (git-ignored): `scripts/demo_data/out/poslog/<store>/<business_date>.xml`.

**Interfaces — Produces:** `export(dsn: str, out_dir: Path, stores: list[str] | None, date_from: date, date_to: date) -> ExportStats` — **read-only** on `pharmacy_demo` (`SET TRANSACTION READ ONLY`); maps `transactions`/`transaction_items`/`payments`/`voids`/`refunds`+`refund_items`/`discount_overrides`/`cash_drawers` to POSLog 6.0 elements exactly as `retail/daab/crosswalks/poslog-6.0.yaml` (A5) reads them; transactions linked to `prescriptions` carry the RX marker the pharmacy overlay crosswalk maps to `is_rx`; no patient identifiers exported. CLI: `uv run python export_poslog.py --store <id> --from 2026-10-01 --to 2026-10-07`.

- [ ] Steps: tests `test_one_transaction_round_trips_through_crosswalk_paths` (fixture rows ⇒ XML ⇒ C3 `apply` ⇒ expected canonical records), `test_rx_marker_only_on_prescription_transactions`, `test_no_patient_fields_in_output`, `test_read_only_transaction` → FAIL → implement → PASS → commit (workspace root).


- [ ] **F1 API E2E on pharmacy demo data** (also asserts no `sale_id` collision across the two feeds): test project "Pharmacy Chain (landed test)" with retail + pharmacy packs; feed the F0 export (1 store × 7 days first, then all 5 stores × 30 days); **parity check: every metric computable in both modes gives the same `metric_value` for landed (from POSLog) and live (existing `pharmacy_demo` mapping) over the same window** — differences listed and explained; then: compose up; enable landed (consent "internal test data"); two feeds — POSLog fixture and an overlay crosswalk fixture of a second vendor shape — **automated test `TestSameReportsFromTwoCrosswalks`** (Go integration, both feeds' golden data ⇒ identical `sr_*`/`sc_*` per store/day); autofill; recalculate; replay same file ⇒ unchanged.
- [ ] **F1b Browser E2E with Chrome DevTools MCP** (`mcp__plugin_chrome-devtools-mcp_chrome-devtools__*`): on `http://localhost:3500` enable landed → wizard 4 steps (`upload_file` POSLog fixture) → map one unmatched field → batch done → "Re-run this batch" → Data mapping "Use POS data for all" → Refresh numbers → master upload. Each step: `take_snapshot` + `take_screenshot`; `list_console_messages` no errors; `list_network_requests` no 4xx/5xx on `/api/kg/projects/*/landed/*`. Screenshots to scratchpad, listed in checkpoint.
- [ ] **F2 Docs:** README/CLAUDE.md per repo (env, make target, queue, roles); Serena `services/*` + checkpoint via `mcp__serena__write_memory`; `kg_store_decision` L1–L14; CI grep guard for D10 words in `internal/landed*`, `internal/intel/landedsource`, `landed_ingest/`.
- [ ] **F3:** `superpowers:requesting-code-review` per repo; `superpowers:finishing-a-development-branch`.

## Coverage vs Trello card & AIOS doc

| Requirement | Task |
|---|---|
| Schema + dictionary, header/body/footer, line fields, shared keys on every record, versioning | A1, A2, A4, B1 |
| Sales Capture all measures (incl. customer count, timing, gift card, payouts, savings) | A3b |
| Sales Reducing Value/Cust/Items, shrink/margin/tax, reversal rules, no Cust double count | A0, A3 |
| Missing ⇒ unavailable, not 0 | A0, A3b, B4, C4 (coverage) |
| Raw → crosswalk → detail → summaries; lineage; unmapped visible | C1–C5 |
| Delivery upload/API (Phase 1), file drop/SFTP/other formats (Phase 2) | C1, C6 |
| Validation, duplicate/replay, rejected/incomplete | C4, C5, C1 reaper |
| Cashier/terminal/store/day summaries + drill-down | A3, A3b, B3, E5 (labels) |
| Have/Partial/Missing crosswalk | A4, A5, E3 |
| Same reports from two POS mappings | F1 `TestSameReportsFromTwoCrosswalks` |
| RX separate + store rollup, RX-only measures | A2, A3b |
| QA cases (normal, multi-unit/weighed, split tender, discounts/coupons, void, refund, cancel, post void, missing fields, replay, incomplete) | A3, A3b, C4 |
| Reconciliation detail ↔ source ↔ summaries | A5 reconcile, C4, A3b |
| History / retention / revoke (rows + raw files) | B2, C8 |
| Tenant isolation | B1, D1, D2 |
| Demo evidence | F1, F1b |

**Not code (team / AIOS):** real sample t-logs and the two real crosswalks built from them; AIOS answers §10; owners/estimates/dates on the card; DPA/BAA. **Separate plan:** WS0 security gate.

## Execution order

Phase 1: `A0 → A1 → A2 → A3 → A3b → A4 → A5 → A6` ‖ `B1 → B2 → B3 → B4` → `C1 → C2 → C3 → F0 → C4 → C5 → C7 → C8` → `E1 → E2 → E3 → E4 → E5` → `F1 → F1b`.
Phase 2: `C6` (after AIOS Q1/Q2) · `D1 → D2` (NL→SQL) → re-run F1b incl. Data Sources system row.
Real customer data only after the WS0 plan is done.
