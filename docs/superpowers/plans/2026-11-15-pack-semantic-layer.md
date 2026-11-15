# Pack Semantic Layer v1 Implementation Plan (rev 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Free questions on landed T-log data use pack-defined business terms (retail + pharmacy). They return the same numbers as the standard metrics and say which definition they used.

**Architecture:**
- **Semantics file.** Each pack gets `daab/semantics.yaml` with terms in the planner's plan format (a derived population subquery plus a measure), rules, joins and question→plan examples.
- **Merge.** The intel `Effective(keys)` step merges the files for a project's enabled packs, along `extends`.
- **Planner.** It accepts a validated derived table as `tables[0]`. For the landed system source only, the planner prompt gets a bounded "Business definitions" block, the store-local today, and a precedence line.
- **Results.** They carry `definitions_used`.
- **Views.** `pos.*` columns carry canonical descriptions and allowed values as comments.

**Tech Stack:** Go (ennam.kg.go), YAML packs (ennam.kg.packs), PostgreSQL 15/16.

**Spec:** `docs/superpowers/specs/2026-11-15-pack-semantic-layer-design.md` (§10 supersedes D-2, D-3, D-4 dates, D-7b/c, §9.1–2, §9.4; §9.6 is corrected by this plan: the pack comes from `EnabledPackKeys`). Plan review: `.superpowers/sdd/semantic-layer-plan-review.md`.

## Global Constraints

- **Branch and commits.** Use branch `task/pos-data-model` in ennam.kg.go, ennam.kg.packs and the workspace root. Commit, never push. In the workspace root, `git add` only your own files.
- **Postgres versions.** Every DB test passes on both `pgvector/pgvector:pg15` and `pg16`. Production is RDS PG 15.17.
- **Metrics are fixed.** `metrics/*.sql` and metric results do not change. Each term reproduces its metric exactly and describes it truthfully.
  - Example: `retail.transactions` = `status='completed' AND COALESCE(transaction_type,'sale') <> 'return'`. It counts exchanges, no_sale and training rows, and keeps post-voids.
- **Owner decisions:**
  - Retail and pharmacy only.
  - Pharmacy "net sales/revenue" includes Rx by default.
  - Pharmacy Rx terms use the **T-log family** (`rx_sc_*` and Rx lines in the T-log), not claim/PMS data. Claim-based terms (`claim_rejection_rate`, `reimbursement_gap`, `pharmacy.rx_revenue` claim view) are omitted until a PMS feed lands; leave a YAML comment saying so.
  - Owner confirmed option A on 2026-11-15.
- **Defaults.** Week starts Monday (ISO). Refunds are reported separately, on their own date.
- **Language.** Labels and synonyms are en + vi. Definitions, rules and SQL are English.
- **Size bound.** The merged block per project is at most 10000 tokens (estimate bytes/4), with at most 12 rules. Exceeding it fails validation; never truncate. Measure one term and one example first (Task 6).
- **SQL safety.** Every SQL fragment in semantics passes `CheckAISQL` and passes `hardenPlan` validation.
- **Prompt scope.** Non-landed sources keep a planner prompt byte-identical to today.
- **Isolated failure (deploy safety).** An invalid `semantics.yaml` must never stop a pack, or its metrics, from loading in the server.
  - The server logs one ERROR naming `file:line` and runs with no semantics for the affected key set.
  - Strict failure exists only in tests: a `TestRealPacksSemanticsValid` test fails CI on any error.
  - The old Go ignores the file.
  - Deploy order stays: Go first, packs after.
- **No new flag.** The block only exists for the landed system source, which only exists when free questions are ready (`LANDED_NL_QUERY`, default OFF). Flags-off behaviour is unchanged.

## Review Focus

1. **The 2026-11-15 weekday question.**
   - PH-001 October Fridays have 60 completed `sale` rows and 9 `return` rows.
   - `transactions` (= `retail.transactions`) gives 60 when there are no exchange, no_sale or training rows. The E2E re-ask must show 60 or state the definition.
2. **Vietnamese synonyms.** "số giao dịch" and "doanh thu thuần" resolve to the same term as their English labels (Task 7 eval).
3. **Bad references fail at load time.** A term referencing a missing view or column fails pack validation with `file:line` when the pack loads, not when a question is asked (Task 2).
4. **`business_date` vs `sold_at`.** For a sale whose `business_date` differs from `sold_at::date`, the term buckets exactly like its metric (Task 6 fixture).
5. **Zero enabled packs.** No block and no error. With several packs (retail + pharmacy), the merged semantics follow `extends` order (Task 4).

---

### Task 1: SQL guard leaf package + semantics loader and merge (Go)

**Files:**
- Move `internal/landed/sqlguard.go` (+ test) to a new leaf package `internal/sqlguard`, and keep `landed.CheckAISQL`/`landed.ErrSQLRefused` as thin wrappers so callers are unchanged. This is mandatory: intel→landed is an import cycle (`landed/aiviews.go:11` imports intel).
- Create `internal/intel/semantics.go` and `semantics_test.go`.
- Modify `internal/intel/pack.go`: parse in `loadPack`; merge and validate in `Effective(keys)`. **Not** in the registry-wide `reg.all` merge (`pack.go:126`): validate per key, as `LoadRegistry`'s `Effective([]string{k})` loop already does.

**Interfaces — produces:**
```go
type Semantics struct { Terms []Term; Rules []string; Joins []Join; Examples []Example; Notes []string }
type Term struct {
  Key string; Label map[string]string; Synonyms map[string][]string; Definition string
  Population string   // "(SELECT ... FROM pos.<view> <alias> ...) AS t" — used as plan.tables[0]
  Columns []string    // the columns t exposes (validated against the SELECT list); hardenPlan validates t.<col> against this
  Measure string      // e.g. "COUNT(*)", "SUM(t.net_amount)"
  TimeColumn string   // e.g. "t.sold_date" (= sold_at::date, like the metric)
  PruneColumn string  // e.g. "t.business_date" — filtered from-1 .. to+1 for partition pruning
  Dims []string; Metric string
}
type Join struct { From, To string }
type Example struct { Question map[string]string; Terms []string; Plan json.RawMessage }
func (c *Catalog) Semantics() (*Semantics, bool)  // merged closure of the keys given to Effective; false when none
func (s *Semantics) PromptBlock() string          // deterministic: rules, terms, joins, examples (file order)
func (s *Semantics) TermByKey(k string) (Term, bool)
```

- [ ] Write tests:
  - **Merge.** A child term with the same key replaces the parent's; rules, examples, notes and joins append parent-first.
  - **Validation.** Run against the **merged** entities and enums: pharmacy terms may use retail's `sale` fields. Errors carry the `<pack>/daab/semantics.yaml:<line>:` prefix. Errors are collected per key: the pack and its metrics still load, `Semantics()` returns false, and the server logs one ERROR. Add `TestRealPacksSemanticsValid` (strict, real packs). Cover each of:
    - unknown key
    - duplicate term
    - more than 12 rules
    - over 10000 tokens
    - a refused fragment (via `sqlguard`)
    - a view or entity not in the model
    - an `alias.field` that is not a field of the view
    - a `Columns` entry not produced by the Population SELECT list
    - an unknown metric
    - an example plan that does not unmarshal into `models.QueryPlan`
    - an unknown example term
  - **Missing file.** `Semantics()` returns false.
  - **Deterministic `PromptBlock`.** Two loads produce identical output.
  - **Registry-wide merge.** `reg.all` does not fail because of the semantics bounds.
- [ ] Run `go test ./internal/sqlguard/ ./internal/intel/ ./internal/landed/`. Expect FAIL, then implement and PASS.
- [ ] Commit (ennam.kg.go): `feat(intel): pack semantics loader, extends merge and validation; sqlguard leaf package`.

### Task 2: Accept a validated derived table as tables[0] (Go)

**Problem:** `hardenPlan` → `validatePlanColumns` (`internal/service/plan_harden.go:251`) registers tables via `parseTableEntry` (`plan_normalize.go:148`). Given `"(SELECT ... ) AS t"`, it returns base `"(SELECT"`, and every `t.<col>` is rejected (`unknown column(s) t.location_id`). In production every term plan would become `clarification_needed`.

**Files:** modify `internal/service/plan_normalize.go`, `internal/service/plan_harden.go` and the call sites in `query_intent.go` (hardenPlan gains access to the current semantics). Tests go in `plan_harden_test.go`.

**Rule (security-relevant):**
- A derived `tables[0]` is accepted **only** when its text equals, after whitespace normalisation, the `Population` of a term in the current project's semantics.
- Its columns are then that term's `Columns`.
- Any other parenthesised `tables[0]` is handled exactly as today. Derived tables are trusted by design (`query_intent.go:637-643`); grants, the ticket and the guard are the boundary. On a match the plan carries the pack's canonical Population text, never the model's.
- The model cannot write arbitrary subqueries this way. The guard still runs on the final SQL.

- [ ] Write tests:
  - A plan whose `tables[0]` is a known Population, with `t.<col>` in select, filter and group_by, passes `hardenPlan`. An unknown `t.<col>` is rejected.
  - A plan whose `tables[0]` is a different subquery (e.g. one character changed) is rejected with today's error.
  - No semantics means today's behaviour, byte-for-byte, on the existing harden tests.
- [ ] Run `go test ./internal/service/ -run Harden`. Expect FAIL, then implement and PASS.
- [ ] Commit: `feat(service): planner accepts pack term populations as derived tables`.

### Task 3: Column comments that land (Go)

**Files:** `internal/intel` (carry enum values on the entity/field type `SyncAIViews` receives, or pass the merged enums alongside), `internal/landed/aiviews.go` (`viewDDL`, `syncOneView` fingerprint), `internal/service/query_intent.go:535` and `internal/service/context_builder.go:288` (both `columnDescription` call sites; the smart path is what production uses, `main.go:704`).

- [ ] Write tests:
  - `TestAIViewColumnsCarryCanonicalComments`: `col_description(pos.sale.status)` is the canonical description + ` Allowed values: completed, voided, cancelled.` (canonical order). The system column `business_date` gets `Store-local business day of the record.`
  - `TestCommentOnlyChangeResyncs`: a description-only change re-applies after a re-sync. The fingerprint includes the ordered column comments.
  - `TestLandedSystemColumnPrefersCanonicalComment`: on both call sites, for a landed system source the precedence is UserDescription > ColumnComment > Description. User sources are unchanged.
- [ ] Run, expect FAIL, implement, run `go test ./internal/landed/... ./internal/service/... ./internal/intel/...` on pg15 and pg16. Expect PASS.
- [ ] Commit: `feat(landed): canonical descriptions and allowed values as pos.* column comments`.

### Task 4: Per-project semantics, store-local today and prompt block (Go)

**Files:**
- `cmd/kg-server/main.go`: a composition-root option next to `WithLandedSourceCheck` (`main.go:728`).
- `internal/service/query_intent.go`: prompt assembly. Also `ContextBuilder` if the smart path builds the prompt there.
- Tests in `internal/service/`.

**Interfaces:**
- Option `WithLandedSemantics(func(ctx, projectID string) (*intel.Semantics, string /*IANA tz*/, error))`.
- Wiring chain: data source → `ProjectID` → `engine.EnabledPackKeys(ctx, intelstore, projectID)` (`internal/intel/engine/availability.go:185`) → `holder.Get().Effective(keys).Semantics()`.
- Time zone: `engine.ResolveTimezone(settings, mappings, def)` (`availability.go:212`). If unresolved, use `UTC` and the prompt line says `UTC — store time zone not configured`.
- Zero keys means no semantics.

- [ ] Switch all three `hardenPlan` call sites in `query_intent.go` (~280 cache re-validation, ~338, ~358) to `hardenPlanWithSemantics` with the project's semantics; otherwise cached term plans are silently discarded.
- [ ] Write tests:
  - `TestLandedSystemPromptHasBusinessDefinitions`: the landed system source prompt contains `PromptBlock()`, the header `Business definitions (from the industry pack; follow them exactly):`, `Today (store local): YYYY-MM-DD (<zone>)` and this precedence line, emitted by Go:
    > A term or rule defined above resolves ambiguity about that term; do not ask a clarifying question for it. List the term keys you used in "terms_used".

    The precedence line overrides the system prompt's "MUST ask when ambiguous" for defined terms only.
  - `TestUserSourcePromptUnchanged`: a golden captured before the change.
  - `TestNoPacksNoBlock`.
  - `TestRetailPlusPharmacyMergedInExtendsOrder`.
- [ ] Run, expect FAIL, implement, PASS.
- [ ] Commit: `feat(service): per-project pack definitions and store-local today in the free-question planner`.

### Task 5: terms_used and definitions_used (Go)

**Files:** `internal/models/ai_query.go` (`QueryPlan.TermsUsed []string \`json:"terms_used,omitempty"\``), `internal/service/nl_query.go` (the result is marshalled into `ai_queries.results`), and the planner JSON-schema text.

**Decision:** `definitions_used` is a field **inside the `results` JSON**. No migration. It is returned unchanged by the existing status/GetQuery API and reaches LAAM through `kg_query_datasource_status`, with no LAAM change.

- [ ] Write tests:
  - Known `terms_used` keys produce `results.definitions_used: [{key, label_en, label_vi, definition}]`, verbatim from the pack.
  - An unknown key is dropped with a single WARN, and the query still runs.
  - No semantics means no field.
- [ ] Run, expect FAIL, implement, PASS.
- [ ] Commit: `feat(service): free-question results name the pack definitions used`.

### Task 6: Retail semantics + execution and consistency harness

**Files:**
- `ennam.kg.packs/retail/daab/semantics.yaml`.
- Test `ennam.kg.go/internal/service/semantics_integration_test.go`: the ticket-path env lives in internal/service; landed packages cannot import service.
- Fixture rows added to the landed test env.
- The implementer may edit both the pack and the test in this task.

- [ ] **Size check first.** Write 1 term and 1 example and print the token estimate. If 20 terms + 25 examples would exceed 10000, reduce the examples to fit and record it.
- [ ] Terms, each reproducing its metric file exactly:

  | Term | Metric |
  |---|---|
  | `transactions` | `retail.transactions` |
  | `transactions_incl_returns` | `retail.sc_txn_count` (it also excludes post-voids) |
  | `net_sales` | `retail.net_sales` |
  | `gross_sales` | |
  | `avg_ticket` | |
  | `items_sold` | |
  | `units_per_transaction` | |
  | `discount_amount` | |
  | `discount_rate` | |
  | `refund_amount` | |
  | `refund_count` | |
  | `refund_rate` | |
  | `post_void_count` | |
  | `line_void_count` | |
  | `price_override_count` | |
  | `no_sale_count` | |
  | `tax` | |
  | `savings` | |

  Name the metric key in every term that has one. Write each definition truthfully, e.g. "Completed transactions except returns; includes exchanges and no-sale/training records, as the standard Transactions metric does."
- [ ] Rules: at most 12, describing what the metrics do. Joins: every view FK path. Examples: question {en, vi} → plan JSON, with literal 2026-10 dates and no `location_id` filter. Cover weekday, hour, top products, refunds by hour and period comparison.
- [ ] `TestSemanticsExecute`: every term (as a plan) and every example goes through **`hardenPlan` (with the real tree built from the real-pack views) → `SQLGenerator.Generate` → `CheckAISQL` → ticket path (`*`)** with no error, on pg15 and pg16.
- [ ] `TestSemanticsMatchMetrics`:
  - The fixture has at least one each of: completed sale, return, exchange, no_sale, training, post-voided sale, cancelled sale, and a sale with `business_date` ≠ `sold_at::date`.
  - Assert those rows exist first.
  - Each term with a `metric` must equal the metric computed by the intel engine on the same landed project, as `internal/intel/landedsource` `TestMockposDemoFitTable` does. Compare the period total and each `location_id`. Counts must be exact; money within 0.005.
- [ ] Run on pg15 and pg16. Expect PASS.
- [ ] Commit packs `feat(packs): retail semantic layer v1` and go `test(service): pack terms execute through the planner and match standard metrics`.

### Task 7: Pharmacy semantics + eval set

**Files:** `ennam.kg.packs/pharmacy/daab/semantics.yaml`, `ennam.kg.packs/{retail,pharmacy}/daab/semantic_eval.yaml`, `internal/service/semantic_eval_test.go`. Extend the Task 6 harness fixtures with Rx lines.

- [ ] Pharmacy terms, from the T-log family only (owner default A):

  | Term | Rule |
  |---|---|
  | `net_sales` | replaces retail's; includes Rx, matching the corresponding pharmacy T-log metric |
  | `rx_revenue` | matching `rx_sc_*` |
  | `front_store_revenue` | |
  | `script_count` | only if the Rx lines identify a script; otherwise omit with a comment |
  | `rx_margin`, `rx_margin_pct` | only if T-log Rx lines carry cost; otherwise omit |

  Claim-based terms are omitted with a comment. Each term passes `TestSemanticsExecute` and `TestSemanticsMatchMetrics` (extended to pharmacy).
- [ ] Eval files:
  - About 25 retail and about 10 pharmacy items, each with `question` (en or vi), `expect_terms` and an optional `note`.
  - Include LAAM-style rewrites, e.g. "Show transactions by weekday for October 2026".
- [ ] `TestSemanticEval`:
  - Skips unless `SEMANTIC_EVAL=1`.
  - Runs the live planner and checks that `terms_used` ⊇ `expect_terms`.
  - Prints accuracy per pack.
- [ ] Run it once with a model key and record the accuracy in the report. The target is at least 80% per pack; report a lower result, but it does not block.
- [ ] Commit packs `feat(packs): pharmacy semantic layer v1 and eval sets` and go `test(service): opt-in semantic eval`.

### After the tasks (controller)
- Final whole-branch review.
- Browser E2E on simulated RDS with flags on:
  - Re-ask the weekday question: 60, or the definition is stated, and `definitions_used` is present.
  - One pharmacy question, if e2e data has Rx lines.
  - PH-003 is refused.
  - Guard check.
  - Flags-off regression.
- Restore grants and set flags OFF.
