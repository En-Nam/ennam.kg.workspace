# Pack Semantic Layer v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Free questions on landed T-log data use pack-defined business terms (retail + pharmacy), so they return the same numbers as the standard metrics and say which definition they used.

**Architecture:**
- Each pack gets `daab/semantics.yaml`: terms written in the planner's plan format, rules, join paths and question→plan examples. The Go intel loader validates and merges it along `extends`.
- For the landed system source only, the query planner prompt gets a bounded "Business definitions" block plus a store-local today.
- `pos.*` columns get canonical descriptions and allowed values as comments.
- Integration tests prove that every term and example executes and that terms match their metrics.

**Tech Stack:** Go (ennam.kg.go: internal/intel, internal/landed, internal/service), YAML packs (ennam.kg.packs), PostgreSQL 15/16.

**Spec:** `docs/superpowers/specs/2026-11-15-pack-semantic-layer-design.md` — §10 supersedes D-2, D-3, D-4 dates, D-7b/c, §9.1–2, §9.4.

## Global Constraints
- Branch `task/pos-data-model` in ennam.kg.go, ennam.kg.packs and the workspace root. Commit, never push. In the workspace root, `git add` only your files; unrelated dirty files exist.
- Every DB test passes on BOTH `pgvector/pgvector:pg15` and `pg16` (production is RDS PG 15.17).
- Standard metrics (`metrics/*.sql`) and their results do not change. Terms follow metrics (spec §9.2, R-2).
- Owner decisions:
  - Pharmacy "net sales/revenue" includes Rx by default; `rx_revenue` and `front_store_revenue` are separate terms.
  - Retail + pharmacy only.
- Week starts Monday (ISO). Refunds are reported separately, on the refund date. Labels and synonyms are en + vi; definitions, rules and plan SQL are English.
- Size bound: merged block per pack at most 6000 tokens (estimate as bytes/4) and at most 12 rules. Exceeding either fails pack load; never truncate.
- Every SQL fragment in semantics passes `landed.CheckAISQL` and references only `pos.*` views and columns that exist for that pack's canonical model.
- Non-landed data sources: planner prompt byte-identical to today.
- Flags default OFF; nothing changes for flags-off behaviour.

## Review Focus
1. A question that uses a synonym in Vietnamese ("số giao dịch", "doanh thu thuần") must pick the same term as the English label (eval set, Task 5).
2. A term population that references a column absent in the pharmacy or retail views must fail pack load with `file:line`, not at query time (Task 1).
3. The 2026-11-15 case must give 60, not 69: PH-001 October Fridays, `transactions` = completed sales of type sale; returns are not counted (Task 5 consistency fixture + E2E).
4. A store whose sales cross midnight UTC: the term buckets on `sold_at::date`, as the metric does, not on raw `business_date` (Task 5 fixture row near midnight with an offset).
5. A pack without `semantics.yaml`, or a project without a pack: the planner prompt has no block and no error (Task 4).

---

### Task 1: semantics.yaml schema, loader, extends-merge, validation (Go)

**Files:**
- Create `internal/intel/semantics.go` and `internal/intel/semantics_test.go`.
- Modify `internal/intel/pack.go`: call the loader in `loadPack`, and merge in the Catalog the way `mergeEntities` does.

**Interfaces — produces:**
```go
type Semantics struct { Terms []Term; Rules []string; Joins []Join; Examples []Example; Notes []string }
type Term struct {
  Key string; Label, Synonyms LocalText /* Synonyms: map lang -> []string */; Definition string
  Population string   // derived table SQL over pos.* views, used as plan.tables[0], e.g. "(SELECT ... FROM pos.sale s WHERE ...) AS t"
  Measure string      // aggregation over t, e.g. "COUNT(*)" or "SUM(t.net_amount)"
  TimeColumn string   // column of t used for date filter/bucket, e.g. "t.sold_date"
  Dims []string       // allowed group-by columns of t
  Metric string       // optional standard metric key it must equal, e.g. "retail.transactions"
}
type Join struct { From, To string } // "pos.sale_line.sale_id" -> "pos.sale.sale_id"
type Example struct { Question map[string]string; Terms []string; Plan json.RawMessage } // Plan unmarshals into models.QueryPlan
func (c *Catalog) Semantics(packKey string) (*Semantics, bool) // merged along extends; false when no file in the chain
func (s *Semantics) PromptBlock() string                     // deterministic rendering used by Task 4
```
Use the existing `LocalText`/label idiom if present; otherwise use `map[string]string` with keys `en`, `vi`.

- [ ] Write `semantics_test.go` tests:
  - **Load and merge.** Parent+child fixture packs (temp dirs, as in `pack_test.go`): a child term with the same key replaces the parent's; `rules`/`examples`/`notes`/`joins` append parent-first.
  - **Validation.** Each case fails with `<pack>/daab/semantics.yaml:<line>:`, as `hardening_test.go` does:
    - unknown top-level key
    - duplicate term key in one file
    - more than 12 merged rules
    - block over 6000 tokens
    - Population/Measure/example plan containing a refused fragment (`pg_`), checked via `landed.CheckAISQL`
    - Population referencing a view `pos.<entity>` whose entity is not in the merged canonical model
    - Population referencing a column `x.<field>` whose field is not a field of the referenced entity's view
    - Metric key not found in the pack chain
    - Example plan that does not unmarshal into `models.QueryPlan`
    - Example term key unknown
  - **Missing file** means `Semantics(key)` returns `false` with no error.
  - **`PromptBlock()` is deterministic** (same bytes across loads), and contains rules, then terms, then joins, then examples, in file order.
- [ ] Run `go test ./internal/intel/ -run Semantics`. Expect FAIL (undefined).
- [ ] Implement.
  - Column-reference validation can be a conservative token scan: `alias.field` where the alias is bound by `pos.<entity> <alias>` in the same fragment.
  - If `internal/intel` importing `internal/landed` creates an import cycle, move `CheckAISQL` into a small leaf package (e.g. `internal/landed/sqlguard`) and keep `landed.CheckAISQL` as a thin wrapper.
- [ ] Run `go test ./internal/intel/...`. Expect PASS.
- [ ] Commit (ennam.kg.go): `feat(intel): pack semantics.yaml loader with extends merge and validation`.

### Task 2: Author retail + pharmacy semantics (packs)

**Files:**
- Create `ennam.kg.packs/retail/daab/semantics.yaml`, `ennam.kg.packs/pharmacy/daab/semantics.yaml`, and `ennam.kg.packs/{retail,pharmacy}/daab/semantic_eval.yaml`.
  - The eval files are a held-out phrasing set. Each item has `question` (en or vi), `expect_terms: [key]` and an optional `note`. Use about 25 items for retail and about 10 for pharmacy, and include LAAM-style rewrites ("Show transactions by weekday for October 2026").
- Modify `ennam.kg.packs/docs/` only if the data dictionary generator requires it.

**Interfaces — consumes:** the Task 1 schema.

- [ ] Read each referenced metric (`metrics/*.sql`) and write the term so its Population, Measure and TimeColumn reproduce that metric's filters exactly:
  - transaction types and status
  - post-void exclusion
  - exchanges
  - regulated/Rx lines
  - `CAST(sold_at AS date)` bucketing, filtered via `business_date BETWEEN from-1 AND to+1` plus `sold_at::date` within range (spec R-3)

  Where two metrics disagree, write two terms with distinct labels. Required terms:

  | Pack | Term | Notes |
  |---|---|---|
  | retail | `transactions` | must equal the metric that gives 60 for PH-001 Oct Fridays; find it among `retail.transactions` / `sc_txn_count` and name it in `metric` |
  | retail | `transactions_incl_returns` | |
  | retail | `net_sales` | `retail.net_sales` |
  | retail | `gross_sales` | |
  | retail | `avg_ticket` | |
  | retail | `items_sold`, `units_per_transaction` | |
  | retail | `discount_amount`, `discount_rate` | |
  | retail | `refund_amount`, `refund_count`, `refund_rate` | |
  | retail | `post_void_count` | |
  | retail | `line_void_count` | |
  | retail | `price_override_count` | |
  | retail | `no_sale_count` | |
  | retail | `tax` | |
  | retail | `savings` | |
  | pharmacy | `net_sales` | overrides retail, includes Rx (owner) |
  | pharmacy | `rx_revenue`, `front_store_revenue` | |
  | pharmacy | `script_count` | |
  | pharmacy | `rx_margin`, `rx_margin_pct` | |
  | pharmacy | `claim_rejection_rate` | |
  | pharmacy | `reimbursement_gap` | |

  Omit any pharmacy term whose source columns are not in the pharmacy `pos.*` views, and note the omission in a YAML comment.
- [ ] Rules (at most 12): spec D-4 rewritten per R-2, plus the precedence line (R-5): "A term defined below or a default rule resolves the ambiguity; do not ask a clarifying question for it. Put the term keys you used in terms_used."
- [ ] Joins (R-7): every view foreign-key path between `pos.*` views of the pack.
- [ ] Examples:
  - 20–30 for retail and 6–10 for pharmacy, as question {en, vi} → plan JSON.
  - Use literal dates in 2026-10.
  - Never filter `location_id`; the ticket scopes stores.
  - Include weekday and hour bucketing, top products by net sales, refunds by hour, and a period comparison.
- [ ] Run `go test ./internal/intel/...` with `PACKS_DIR` pointing at ennam.kg.packs. Task 1's loader validates both real packs. Expect PASS.
- [ ] Commit (ennam.kg.packs): `feat(packs): retail and pharmacy semantic layer v1`.

### Task 3: Column comments that land, and description precedence (Go)

**Files:** modify `internal/landed/aiviews.go` (`viewDDL`, `syncOneView` fingerprint) and `internal/service/query_intent.go` (`columnDescription` call site for the landed system source). Tests go in `internal/landed/aiviews_integration_test.go` and `internal/service/query_intent_test.go`.

- [ ] Write tests:
  - `TestAIViewColumnsCarryCanonicalComments`: after `SyncAIViews`, `col_description` of `pos.sale.status` equals the canonical description + ` Allowed values: completed, voided, cancelled.` (values from the canonical enums, in canonical order).
  - `TestCommentOnlyChangeResyncs`: change only a field description in the fixture catalog, re-sync, and the new comment is present.
  - `TestLandedSystemColumnPrefersCanonicalComment`: for a landed system source column carrying both an auto `Description` and a `ColumnComment`, the schema context shows the comment. For a user source the precedence is unchanged (UserDescription > Description > ColumnComment).
- [ ] Run them. Expect FAIL.
- [ ] Implement:
  - `COMMENT ON COLUMN` statements are issued in the same transaction, on the temp view and the final view.
  - The fingerprint appends ordered `col_description` values.
  - Precedence for landed system: UserDescription > ColumnComment > Description.
- [ ] Run `go test ./internal/landed/... ./internal/service/...` on pg15 and pg16. Expect PASS.
- [ ] Commit (ennam.kg.go): `feat(landed): canonical descriptions and allowed values as pos.* column comments`.

### Task 4: Planner prompt block, store-local today, terms_used (Go)

**Files:** modify `internal/models/ai_query.go` (`QueryPlan.TermsUsed []string \`json:"terms_used,omitempty"\``), `internal/service/query_intent.go` (prompt assembly for the landed system source), and the free-question result path (wherever query results are returned to callers) to include `definitions_used`. Tests go in `internal/service/query_intent_test.go` and a result test.

**Interfaces — consumes:** `Catalog.Semantics(packKey)` and `PromptBlock()` from Task 1. The pack key for a project comes from the same place `SyncAIViews` gets the catalog/pack for landed projects.

- [ ] Write tests:
  - `TestLandedSystemPromptHasBusinessDefinitions`: the prompt for the landed system source contains `PromptBlock()` and a line `Today (store local): YYYY-MM-DD (<IANA zone>)`. The zone comes from the project/location configuration; if none is configured, use `UTC` and say "UTC — store time zone not configured".
  - `TestUserSourcePromptUnchanged`: the prompt for a non-landed source is byte-identical to a golden captured before the change.
  - `TestNoSemanticsNoBlock`: a pack without semantics produces no block and no error.
  - `TestTermsUsedValidated`: a plan with an unknown `terms_used` key gets the key dropped and a WARN logged, and the query still runs. Known keys produce `definitions_used: [{key, label_en, label_vi, definition}]` in the result, taken verbatim from the pack.
- [ ] Run them. Expect FAIL.
- [ ] Implement:
  - The block goes after the schema context and before the question.
  - Exact header: `Business definitions (from the industry pack; follow them exactly):`.
  - The planner JSON schema description gains `terms_used`.
- [ ] Run `go test ./internal/service/... ./internal/models/...`. Expect PASS.
- [ ] Commit (ennam.kg.go): `feat(service): pack business definitions and store-local today in the free-question planner`.

### Task 5: Execution, consistency and eval tests (Go integration)

**Files:** create `internal/intel/landedsource/semantics_integration_test.go`, plus an opt-in `internal/service/semantic_eval_test.go`. Extend fixtures in the landedsource test env.

- [ ] `TestSemanticsTermsAndExamplesExecute`, for both real packs:
  - Every term is rendered into a plan (`tables[0]` = Population, aggregation = Measure, TimeColumn filter for 2026-10) and every example plan is run.
  - Each goes through `SQLGenerator.Generate` → `CheckAISQL` → the ticket path (ticket `*`) on the fixture project, with no error.
  - Run on pg15 and pg16.
- [ ] `TestSemanticsTermsMatchMetrics`. The fixture must contain at least one each of:
  - completed sale
  - return
  - exchange
  - post-voided sale
  - cancelled sale
  - pharmacy Rx line
  - a sale whose `sold_at` carries an offset that puts its UTC date on a different day than its local date

  First assert those rows exist, and fail if any is missing. Then, for each term with `metric`, compare the period total and the per-`location_id` value to the metric computed through the intel engine (as `TestMockposDemoFitTable` does). Use exact equality for counts, and 0.005 for money.
- [ ] `TestSemanticEval`:
  - Skip unless `SEMANTIC_EVAL=1`.
  - Runs `semantic_eval.yaml` questions through the live planner and checks `terms_used ⊇ expect_terms`.
  - Prints accuracy per pack and writes `semantic-eval-result.md` to the test temp dir, with the path logged.
- [ ] Run on pg15 and pg16. Expect PASS (eval skipped). Run the eval once with a model key and record the accuracy in the report. The target is at least 80% per pack; below that, report it, but do not block.
- [ ] Commit (ennam.kg.go): `test(landed): semantic terms execute and match standard metrics`.

### After the tasks (controller)
- Final whole-branch review.
- Browser E2E on simulated RDS, with flags on:
  - re-ask the weekday question, which must say 60 or state the definition;
  - one pharmacy question if the e2e has pharmacy data;
  - PH-003 refused;
  - the guard;
  - flags-off regression.
- Restore the e2e state: grants and flags OFF.
