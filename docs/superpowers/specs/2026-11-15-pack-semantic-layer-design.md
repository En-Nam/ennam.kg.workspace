# Pack semantic layer v1: business meaning for free questions (retail + pharmacy)

Date: 2026-11-15. Owner decisions are marked **(owner)**; everything else is the designer's call and can be changed.

## 1. Why

Free questions (AI-written SQL over the ticket-filtered `pos.*` views of the landed T-log store) now work, including on
AWS RDS PostgreSQL 15. Accuracy is the gap.

On 2026-11-15 "which weekday has the most sales transactions" returned two answers:
- 60/59/53 from the standard metric;
- 69/65/65 from a free question, which counted every `pos.sale` row.

Both were "right" under different meanings of *transaction*. The pack already holds the business meaning:
- field descriptions and enums in `canonical.yaml`;
- metric SQL in `metrics/*.sql`;
- en/vi labels in `laam/glossary.yaml`.

None of it reaches the model that writes free-question SQL. That prompt is built in `ennam.kg.go/internal/service/query_intent.go` and today sees only column names, types and an auto description. The `pos.*` views carry no column comments, sample values are switched off for the landed system source, and the planner prompt has no slot for pack context.

Research (2026-11-15) on Snowflake Cortex Analyst, Databricks Genie, dbt MetricFlow, Cube and LookML found the same minimal set of semantic-layer parts. In the dbt benchmark of April 2026, adding that layer raised accuracy from 84–90% to 98–100%; the sample was small.

## 2. Goals

- G1: A free question and the standard metric give **the same number** for the same business term, period and stores.
- G2: Common owner phrasings in English and Vietnamese map to one defined meaning. The answer says which definition it used when the phrasing was ambiguous.
- G3: Retail and pharmacy **(owner)**. Pharmacy inherits retail (`pharmacy/pack.yaml: extends: [retail]`) and adds only its own terms.
- G4: The semantic content lives in the pack (YAML, versioned with the pack), not in Go code or prompts.
- G5: A regression set of question→SQL pairs is part of the pack, so a pack change that breaks a definition fails a test.

## 3. Non-goals (v1)

- F&B, fashion and other industries (later packs reuse the same file format).
- A metric DSL or query compiler; the model still writes the SQL.
- Per-tenant overrides (fiscal calendar, week start, tax-inclusive pricing). v1 ships one documented default per rule.
- Changing standard metrics, the Home screen or LAAM's metric tools.
- Replacing the SQL keyword guard with a parser (separate backlog item `backlog/daab-free-questions-sql-parser-guard`).
- Footfall- or traffic-based KPIs, and anything needing data the canonical model does not hold.

## 4. Anti-goals

- A definition in `semantics.yaml` that disagrees with the metric of the same name. G1 must be enforced by test, not by care.
- Prompt growth that slows every free question noticeably. The injected block stays bounded; see D-6.
- Anything that weakens the ticket/view isolation or the SQL guard. Example SQL in the pack is subject to the same guard and runs only through the views.

## 5. Design decisions

- **D-1 File.** `ennam.kg.packs/<pack>/daab/semantics.yaml`, one per pack. A pack that `extends` another merges with it: child terms and examples are added; a child key equal to a parent key replaces it. The pack loader in Go validates and loads it alongside `canonical.yaml`. A missing file is allowed, meaning no semantic layer.
- **D-2 Contents.** Four sections:
  - `terms`: about 15 retail and about 6 pharmacy. Each term has:
    - `key`
    - `label` {en, vi}
    - `synonyms` {en: [...], vi: [...]}
    - `definition`: one plain sentence
    - `sql`: an expression or small SELECT fragment over `pos.*` view columns
    - `metric`: optional; the standard metric key it must agree with
  - `rules`: at most 12 short lines of defaults the model must follow (see D-4).
  - `examples`: 20–30 question→SQL pairs. Each has a `question` {en, vi} and `sql` against `pos.*` views with `$location`/date placeholders as the executor expects. Where checkable, an example also carries an `expect` reference to a metric.
  - `notes`: optional free text shown to the model, at most 10 lines.
- **D-3 Enums and field meaning flow automatically.** No duplication in `semantics.yaml`. `viewDDL` (`internal/landed/aiviews.go`) adds `COMMENT ON COLUMN` for each `pos.*` column from the canonical field `description`, plus `Allowed values: …` from the canonical enums. Schema extraction already reads DB comments into the planner prompt (fallback order in `buildSchemaContext`), so this reaches the model with no prompt change.
- **D-4 Default rules (v1).**
  - A *transaction* or *sale* is a completed sale (`status = 'completed'`), excluding voided, cancelled and training transactions.
  - *Sales* means net sales, tax-exclusive.
  - Refunds are reported separately, on the refund's business date, never netted into sales unless asked.
  - Dates use `business_date` (store-local).
  - A *week* starts on Monday (ISO).
  - "This week/month" includes the current partial period, and the answer says so.
  - "Best/busiest" ranks by net sales unless the question names another measure.
  - "Top products" ranks by net sales; ties are broken by units.
  - Weekday comparisons give totals and per-day averages when the weekday counts differ.
  - State the definition used whenever the question was ambiguous.

  Each rule must match how the corresponding standard metric is computed. Where a metric differs (for example `sc_txn_count` includes returns), the term follows the metric, and the rule text says so.
- **D-5 Injection point.** For the landed system source only, `query_intent.go` adds a "Business definitions" block to the planner prompt, built from the merged semantics of the project's pack. It contains rules, then terms (label, synonyms, definition, sql), then examples. The SQL in that block passes `CheckAISQL`. For user (non-landed) sources the prompt is unchanged.
- **D-6 Size bound.** The block is at most about 6k tokens. If the merged file exceeds it, the loader fails pack validation; it does not truncate silently. Relevance selection (top-k examples by keyword) is a later optimisation and is not in v1.
- **D-7 Tests.**
  - (a) Loader validation: schema, the size bound, and a term `sql` that may only reference `pos.*` views/columns that exist for that pack's canonical model.
  - (b) Every `examples[].sql` and `terms[].sql` executes without error against the AI views on the landed test DB, through the real ticket path, on PG15 and PG16.
  - (c) Consistency: for each term with `metric`, the term SQL and the metric return the same value on the fixture data for a fixed period and store set.
  - (d) A prompt-builder unit test shows the block is present for the landed system source and absent for others.
- **D-8 Language.** Labels and synonyms are en + vi (glossary parity). Definitions, rules and example SQL are English. Example questions carry both en and vi.

## 6. Starting term list (designer's call; refine while authoring)

Retail:
- net sales, gross sales, transactions (completed sales), average ticket / basket value, items per basket (UPT), items sold, discount amount and rate, refund amount / count / rate, void (post-void) count/value, line-void count/value, price override count/rate, no-sale count, tax, savings, sales by hour/daypart, sales by weekday
- cash over/short appears only if `cash_drawer` data exists; otherwise the term is omitted

Pharmacy (adds):
- Rx revenue, front-store revenue (non-Rx), script count, Rx margin and margin %, claim rejection rate, reimbursement gap

Each term with a standard metric names it, e.g. `net_sales` → `retail.net_sales` and `transactions` → `retail.sc_txn_count`.

## 7. What is left to the builder

- Exact YAML schema field names within D-2.
- Go types and loader placement, following how `canonical.yaml` is loaded and merged with `extends`.
- Fixture data for the consistency tests: reuse the existing landed test fixtures or the MOCKPOS golden records.
- Prompt block formatting.
- Placeholder conventions in example SQL, matching what the executor binds today (location and date parameters).

## 8. Acceptance

- The tests in D-7 are green on PG15 and PG16.
- Re-asking the 2026-11-15 weekday question in a browser E2E gives a number that matches the standard metric definition, or explicitly states the definition used.
- Then **(owner)** a full browser E2E regression of today's work, with flags on in the e2e env:
  - free question on simulated RDS;
  - store scoping (PH-003 refused);
  - guard;
  - flags off restores the old behaviour;
  - reaper on PG15 (covered by tests).

## 9. Builder-check answers (2026-11-15, designer's calls)

1. **Consistency test (D-7c).** Run the standard metric through the existing intel engine on a landed project. This is the same path as `internal/intel/landedsource` `TestMockposDemoFitTable`, which already reads `sr_*`/`sc_*` metrics from landed records. Run the term SQL through the AI views on the same fixture project (ticket `*`). Compare the period total, then per `location_id`, at day grain over the fixture period. No new adapter.
2. **Metric wins (G1, non-goal: metrics unchanged).** Term SQL replicates the metric's filters on the views: transaction types, status, and the post-void exclusion. Bucketing uses `business_date`. Metrics bucket by `CAST(sold_at AS date)`, so the fixture keeps `business_date` = sold date. The near-midnight difference is accepted and documented in the term's `definition`. Rules (D-4) describe what the metrics do. Where two metrics differ, there are two terms. For example:
   - `transactions`: completed sales of type sale, which is what the metric shown on 2026-11-15 counted (60 for PH-001 Fridays in Oct).
   - `transactions_incl_returns`: matches `sc_txn_count`, which includes returns and exchanges.
3. **Cause of the 2026-11-15 gap.** PH-001, October Fridays: 60 completed `sale` + 9 completed `return` rows = 69. The free question counted every `pos.sale` row; the metric counted sales only. The acceptance re-ask must yield 60 (or state "including returns: 69").
4. **No placeholders.**
   - The free-question model produces a plan that `SQLGenerator` turns into SQL with bound location/date parameters.
   - Pack examples are reference SQL for the planner. They use **literal dates** and never filter `location_id`, because the ticket scopes stores.
   - Tests execute them as-is through the ticket path.
   - Term `sql` is an expression or fragment the planner copies into its select/filter.
5. **Merge.** `terms` are keyed: a child key replaces the parent's. `rules`, `examples` and `notes` append (parent first). Size bounds (12 rules, about 6k tokens) apply to the merged result per pack. A pharmacy addition that breaks the bound fails pharmacy validation, not retail.
6. **Which pack.** The same pack the landed AI views are built from for that project (see `SyncAIViews` / the project's pack selection). No pack means no semantic block. A single pack per project, as today.
7. **Pharmacy data.** Include a pharmacy term only if its source columns exist in that pack's `pos.*` views (prescription/claim entities). Otherwise omit it, like cash over/short. The loader test (D-7a) enforces this.
8. **Column comments.**
   - `SyncAIViews` re-creates the views idempotently at startup and on pack reload, so `COMMENT ON COLUMN` (issued in the same sync, as the view owner) reaches deployed views with no migration.
   - The builder confirms that `buildSchemaContext`'s comment lookup covers views (`pg_description` on the view's columns). If it does not, extend that lookup for the landed system source.

## 10. Revision after independent review (2026-11-15) — supersedes D-2, D-3, D-4 dates, D-7b/c and §9.1–2, §9.4

Review: `.superpowers/sdd/semantic-layer-design-review.md` (verdict: right with changes).

The dbt 98–100% figure (§1) comes from metric selection plus a compiler, not prompt injection. It is not our expected gain.

- **R-1 Plan format, not SQL.**
  - The planner emits a plan: one base table, a flat filter list with a fixed operator set, no EXISTS, no CTEs.
  - A term is therefore: `population`, a derived subquery over `pos.*` placed as `tables[0]`; `measure`, the aggregation; `time_column`; and allowed `dims`.
  - Examples are **question → plan JSON**.
  - D-7b runs every example and every term through plan → `SQLGenerator` → `CheckAISQL` → ticket path, on PG15 and PG16.
  - If the plan format cannot express a needed population, the builder extends the planner/generator minimally (derived-table support) rather than falling back to raw SQL.
- **R-2 Single source of truth.**
  - A term tied to a metric derives its population and measure from that metric's definition. Either generate it from the metric file at load time, or keep both and enforce a check.
  - D-7c must be able to fail. The fixture includes return, exchange, post-void, cancelled sale and (pharmacy) regulated/Rx line rows, and the test asserts those rows exist.
  - Where metrics disagree, there is one term per metric, with distinct labels. Example: `retail.transactions` counts exchanges and keeps post-voids, so it is described exactly as the metric behaves.
  - D-4 rules are rewritten to describe the metrics, not an idealised definition.
- **R-3 Dates.**
  - Metrics bucket on `sold_at`, and the views cast `sold_at::timestamp`, which drops any offset.
  - Terms filter on `business_date` ±1 day (partition pruning), then filter and bucket on `sold_at::date` exactly as the metric does.
  - The prompt gets a store-local **today** (project/store time zone). `CURRENT_DATE` on RDS is UTC.
- **R-4 Column comments actually land.**
  - `syncOneView`'s fingerprint includes the column comments, so a comment-only change re-applies.
  - For the landed system source, the canonical description (column comment) outranks the auto-generated description in `columnDescription`.
- **R-5 Terms used.** The plan gets `terms_used: [keys]`, validated against the merged pack. The answer's definition text is rendered from the pack, not paraphrased by the model. A precedence line says a defined term or default rule resolves ambiguity, so the model does not ask a clarifying question for a term the pack defines.
- **R-6 Eval set.**
  - A held-out file of real phrasings (en + vi, including LAAM-style rewrites) with the expected term.
  - It runs through the live planner as an opt-in test (`SEMANTIC_EVAL=1`, needs a model key) and reports accuracy.
  - It is not in CI, but it is required once before acceptance, with the result recorded.
- **R-7 Join paths.** The semantic file declares view join keys (e.g. `sale_line.sale_id → sale.sale_id`), injected with the terms.
- **R-8 Sample values.** Low-cardinality columns get their allowed values from the canonical enums, in the comment and in the block. Sample values are not read from data.
- **R-9** The size bound and the all-examples approach stay as in D-6.
- **(owner, 2026-11-15)** Pharmacy "net sales/revenue" includes Rx by default (total = Rx + front-store); `rx_revenue` and `front_store_revenue` are separate terms for the split.
