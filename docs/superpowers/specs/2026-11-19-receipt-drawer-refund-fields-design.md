# Card #5 — full refund drawer fields + whole-row click

Owner decisions 2026-11-19: do row click; do ALL drawer fields from the card; DAAB/pack changes allowed; T-log XML may be
edited and re-ingested (only the files with refunds).

## Why
Card #5 BUG-02 asks the drawer to show: refund id, amount, currency if known, reason, receipt-present flag, original and
refund transaction ids, store/register, employee/approving manager, dates, days since purchase, risk score, source record,
related links. Today the drawer (DAAB `kg_get_record`, fixed SELECT in `ennam.kg.go/internal/intel/engine/record.go`) has
no reason, no days since purchase, no risk score, no currency label; and only id cells open it.

## Findings that shape the design
- `refund.reason_code` is already canonical and already mapped by the POSLog crosswalk (`p:LineItem/p:Return/p:ReasonCode`);
  the local landed T-log refunds carry it ("No Receipt" 103, "Product Defective" 143, …). Only the record SELECT omits it.
- No canonical risk score exists, and T-log has none. The demo generator's rule
  (`scripts/demo_data/pharmacy_demo_gen/operations.py`) is `10 + 40·(no receipt) + 20·(refunded at/after 20:00) +
  20·(amount ≥ 100)` — computable from T-log fields.
- Demo XML: `.superpowers/sdd/2026-11-11-pos-data-model-tlog-landed/e2e-data/poslog-12m/` (1905 files, 511 contain a
  `<Return>`). Ingest is an upsert, so re-loading the 511 files updates refunds without duplicates. Local DAAB reads packs
  from the `ennam.kg.packs` folder.

## Design
1. **Pack (ennam.kg.packs)**: canonical `refund.risk_score: { type: numeric, description: "Refund risk score supplied by
   the source (0-100)" }`. Bump retail + pharmacy pack versions (0.7.2 → 0.7.3), every crosswalk `canonical:` pin, the Go
   real-pack test pins, CHANGELOG, data dictionary. POSLog crosswalk maps `risk_score` from a documented vendor extension
   element `p:LineItem/p:Return/p:RiskScore` (same pattern as `@RX`); absent → null.
2. **XML script** (`scripts/landed/add-refund-risk-score.py`, workspace repo): copies `poslog-12m` to `poslog-12m-risk`
   and, in every `<Return>`, inserts `<RiskScore>` computed by the demo rule from the transaction itself (receipt present
   = the transaction has an original-transaction reference, the same signal the crosswalk uses for `has_receipt`; time =
   transaction begin time; amount = the return transaction's refunded amount). Also writes the list of changed files.
   Unit tests. Re-ingest locally only the changed files with `scripts/landed/load-demo-data.py`.
3. **DAAB (ennam.kg.go)**: the refund record SELECT (head and refunds-of-sale) also returns `reason_code` and
   `risk_score` when the catalog declares them (same `declares` guard as `terminal_id`, so older packs keep working).
4. **LAAM**:
   - Drawer: show reason, risk score, days since purchase (refund date − original sale date, computed in the drawer when
     both exist), and "currency not specified" next to amounts when no currency is configured (`intelCurrency()` empty).
     Column labels via the intel i18n dictionary (vi/en/zh).
   - Whole-row click in chat result tables: clicking a row (outside an id button) opens the row's primary record —
     `refund_id` if the row has a link for it, else the first sale link. Keyboard path stays the id buttons.
   - Store / employee / customer ids: out of scope (no detail views), noted on the card.
5. **Prod**: deploy checklist entry — release packs 0.7.3 before DAAB reads them; re-load the 511 changed files on prod
   with the same script. Not done in this work.

## Non-goals
DAAB computing risk itself; detail views for store/employee/customer.

## Tests / verification
Pack: Go real-pack tests + crosswalk tests on 0.7.3; python crosswalk test that `<RiskScore>` maps. Script: unit tests on
rule + insertion. DAAB: record tests for the new columns and the old-catalog fallback. LAAM: drawer + row-click tests.
E2E local: re-ingest, then the natural VI/EN refund question → click a refund → drawer shows reason, risk score, days since
purchase, "currency not specified".
