# Refund drawer fields + row click Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** the chat receipt drawer shows reason, risk score, days since purchase and "currency not specified"; clicking a chat table row opens its record.

**Architecture:** new canonical `refund.risk_score` (packs 0.7.3) fed from a POSLog vendor-extension element; a script adds that element to the demo T-log XML (511 files re-ingested); DAAB's record SELECT returns `reason_code`/`risk_score`; LAAM renders them and computes days since purchase.

**Spec:** `docs/superpowers/specs/2026-11-19-receipt-drawer-refund-fields-design.md`

## Global Constraints
- Branch `task/improve_by_feedback_19112026` in every repo (workspace root, `ennam.kg.packs`, `ennam.kg.go`, `ennam.kg.python`, `LAAM` are separate git repos — use `git -C <repo>`). No push/merge/deploy/tag.
- Workspace root has 36 pre-existing dirty files: commit ONLY your files with explicit paths.
- Pack version 0.7.2 → 0.7.3 for BOTH retail and pharmacy; afterwards `grep -rn "0\.7\.2" ennam.kg.packs ennam.kg.go/internal` must show only CHANGELOG/history lines.
- Risk rule (exact): `10 + 40·(no receipt) + 20·(begin time hour ≥ 20) + 20·(refunded amount ≥ 100)`; integer.
- Go core stays industry-neutral (`scripts/check-core-words.sh` in ennam.kg.go must pass): field names come from the catalog, no hardcoded "risk" semantics beyond the SELECT column list guarded by `declares`.
- LAAM: comments/commits English, UI strings via i18n vi/en/zh, connector-agnostic.
- Task-scoped tests only; full suites at the end.

## Review Focus
1. Old packs/mappings without `risk_score` or `reason_code` → record still loads (declares guard), drawer simply omits the field.
2. A refund with no original sale (no receipt) → days since purchase omitted, never NaN/negative.
3. XML script idempotent: running twice does not add a second `<RiskScore>`; non-return files byte-identical.
4. Row click must not fire when the click lands on an id button (no double open) nor on text selection drag.
5. "Currency not specified" only when no currency is configured; configured currency still formats as today.

---

### Task 7: packs 0.7.3 — canonical risk_score + POSLog mapping
**Files:** `ennam.kg.packs/retail/daab/canonical.yaml` (refund.risk_score, numeric), `retail/pack.yaml`, `pharmacy/pack.yaml` (version 0.7.3), every crosswalk `canonical:` pin listed by the grep above incl. `_testdata`, `retail/daab/crosswalks/poslog-6.0.yaml` (refund + refund_voided_lines share `&refund_fields`: add `risk_score: "p:LineItem/p:Return/p:RiskScore"`, document it as a vendor extension like `@RX` in the header comment), `CHANGELOG.md`, `docs/data-dictionary-*.md` (add field; follow the file's convention for new versions), `ennam.kg.go/internal/intel/pack_070_test.go` + `crosswalk_test.go` pins. Check whether pharmacy canonical extends retail's refund (if it redeclares refund, add the field there too).
- [ ] Bump + add field + mapping.
- [ ] `cd ennam.kg.go && PACKS_DIR=../ennam.kg.packs go test ./internal/intel/... -count=1` PASS (after the bump).
- [ ] Python crosswalk test: in `ennam.kg.python`, add a test that a POSLog return with `<RiskScore>42</RiskScore>` yields refund.risk_score 42 and without it null (find the existing POSLog crosswalk tests and follow them); `uv run pytest <that file>` PASS.
- [ ] Commit per repo: `feat(packs): refund.risk_score (0.7.3)` etc.

### Task 8: DAAB record SELECT returns reason_code and risk_score
**Files:** `ennam.kg.go/internal/intel/engine/record.go` (+ `record_test.go` / existing record tests).
- Head SELECT (`recordRefundSQL`) and `recordRefundsOfSaleSQL` add `reason_code` and `risk_score` only when the catalog declares them (use the existing `declares(ps.cat, entity, fields...)` pattern used for `terminal_id`; one helper that builds the column list is fine).
- [ ] Tests: catalog with both fields → columns present; catalog without → query unchanged and record loads. Run `go test ./internal/intel/engine/ -run Record -race -count=1` and `scripts/check-core-words.sh`.
- [ ] Commit `feat(intel): record shows refund reason and risk score when mapped`.

### Task 9: XML script adds RiskScore
**Files:** create `scripts/landed/add-refund-risk-score.py` + `scripts/landed/test_add_refund_risk_score.py` (workspace root repo; pytest runnable with `python3 -m pytest scripts/landed/test_add_refund_risk_score.py`).
- CLI: `--src <poslog-12m dir> --dst <poslog-12m-risk dir>`; copies every file; for each `<Transaction>` containing return line items inserts `<RiskScore>` as the last child before `<ItemAttributes>` (or last) of every `<Return>` (POSLog namespace preserved, `xml_declaration` kept), value from the rule using: receipt = the transaction carries an original-transaction reference (read `ennam.kg.packs/retail/daab/crosswalks/poslog-6.0.yaml` for the exact element the crosswalk uses for `has_receipt`), hour of `BeginDateTime`, refunded amount = sum of the return lines' `ExtendedAmount` (same as crosswalk `refund` block). Skips a `<Return>` that already has `<RiskScore>`. Prints changed-file count; writes `<dst>/changed-files.txt`.
- [ ] Tests: rule table (receipt/no receipt × before/after 20:00 × <100/≥100), idempotence, non-return file byte-identical, namespace kept.
- [ ] Run on the real folder: src `.superpowers/sdd/2026-11-11-pos-data-model-tlog-landed/e2e-data/poslog-12m`, dst sibling `poslog-12m-risk`; expect 511 changed.
- [ ] Commit script + test only (not the data).

### Task 10: LAAM drawer fields
**Files:** `LAAM/src/components/intel/detail/ReceiptDrawer.tsx`, `receipt-format.ts` (+ tests), `src/i18n/dictionaries/intel.ts`.
- Labels for `reason_code`, `risk_score` columns (vi "Lý do", "Điểm rủi ro"; en "Reason", "Risk score"; zh "原因", "风险分").
- Days since purchase: refund section `refunded_at` vs `original_sale` section's sale time column (read the existing section/column names in receipt-format.ts) → whole days ≥ 0; shown as a row in the refund section ("Số ngày từ lúc mua" / "Days since purchase" / "距购买天数"); omitted when either is missing or result < 0.
- "Currency not specified": where amounts are formatted (`formatMoney`), when no currency is configured append/label "chưa rõ tiền tệ" / "currency not specified" / "未注明币种" once in the drawer header near the amount. Configured currency path unchanged.
- [ ] Tests in the existing ReceiptDrawer/receipt-format test files; `npx tsc --noEmit`. Commit `feat(intel): receipt drawer shows reason, risk score, days since purchase, unspecified currency`.

### Task 11: LAAM whole-row click
**Files:** `LAAM/src/components/chat/ResultTables.tsx` (+ test).
- Row `onClick`: ignore if the event target is inside a `button`/`a`, or `window.getSelection()?.toString()` is non-empty; else open the row's primary link: first column whose `recordLinkOf` is a `refund` link, else the first `sale` link; rows with no link are not clickable (no pointer cursor). Clickable rows get `cursor-pointer` and a hover background using existing tokens. Focus return: pass the id button of that record as the opener if present (focus it with preventScroll before opening).
- [ ] Tests: row click opens refund (not sale) when both present; click on id button opens once; row without links does nothing. Commit `feat(chat): clicking a result row opens its record`.

## After tasks (controller)
Re-ingest the 511 changed files locally with `scripts/landed/load-demo-data.py --poslog-dir poslog-12m-risk` (only changed files: point at a folder containing just them), restart DAAB if packs need reload, rebuild LAAM, E2E EN+VI. Deploy-checklist note for prod (packs 0.7.3 release first; re-load 511 files). Full suites; final review.

---

## Plan review amendments (binding — override the tasks above where they differ)

**Task 7**
- Pin sites: pack.yaml ×2; `canonical:` line in poslog-6.0.yaml (~158), poslog-6.0-rx.yaml (~29), mockpos-demo-1.yaml (~73), salesforce-pos-poslog.yaml (~16) + the header comment on line 1 of poslog-6.0 / mockpos / salesforce; ennam.kg.go/internal/intel/pack_070_test.go (~75-76, 168-169), crosswalk_test.go (~30, 50). Bump poslog-6.0 crosswalk `version: 1.2.0` → `1.3.0` (CHANGELOG convention). Pharmacy uses `refund: extend: true` → no change there.
- Put `risk_score` in `&refund_fields` (covers refund_voided_lines via `<<:`).
- Goldens: `_testdata/crosswalk_coverage.json` add `p:RetailTransaction/p:LineItem/p:Return/p:RiskScore` (sorted) to BOTH "template" and "parent_disabled" lists. `_testdata/two_crosswalks/vendor_b_crosswalk.yaml` is GENERATED: regenerate with `uv run python scripts/landed_demo/two_crosswalks_golden.py build ...` in ennam.kg.python (never sed); golden_a/b.json should not change. `docs/data-dictionary-0.7.0.md` is generated: `go test ./internal/intel -run TestDictionaryUpToDate -update` (keep filename).
- Verify with python test_path_parity.py, test_two_crosswalks.py and Go landedapi matchpaths_parity_test + intel tests.

**Task 8**
- Guard EACH field separately with `declares` (reason_code must show on 0.7.2 packs even without risk_score). Undeclared → not in SELECT; declared-but-unmapped compiles to NULL (fine). Use a test-pack variant — `packs_receipt` (record_test.go ~38) is shared. check-core-words.sh does not scan record.go (moot).

**Task 9**
- has_receipt signal = `exists(p:LineItem/p:Return/p:OriginalTransaction)` relative to RetailTransaction; time = Transaction `BeginDateTime` (wall clock, no tz); amount = sum of Return `ExtendedAmount`, BUT when any return line has `@VoidFlag` use `Total[@TotalType='TransactionNetAmount']` (mirror crosswalk lines ~362-379). Insert the same score into each `<Return>` of the transaction. Copy non-return files byte-for-byte (never re-serialize); `ET.register_namespace('', NS)` to avoid ns0 prefixes. Expected: 651 return transactions in 511 files.
- Also write a subset folder for re-ingest: `<dst>-changed/<store>/<file>.xml` (only changed files) so load-demo-data `--poslog-dir` can point at it.

**Task 10**
- "Currency not specified" signal = the record has no `currency` column/value (option a). `intelCurrency()` is server-only and defaults USD; don't use it.
- `intel.receipt.col.reason_code` already exists → only add `risk_score` label; add `risk_score` to KNOWN_COLUMNS (receipt-format.test.ts ~51 requires labels) and to the number branch of cellKind.
- Section keys `refund`, `original_sale`; columns `refunded_at`, `sold_at`. Refund header is a generic section (ReceiptDrawer.tsx ~193-197) → inject "days since purchase" there or in ReceiptSummary (~306). Omit when original_sale is absent/masked (30 cross-store cases).

**Task 11**
- Compute the row's link over ALL columns (everyCol), not only preview columns; if the id button isn't rendered, open without an opener.

**Execution / after tasks**
- Parallel in shared trees: commit with explicit paths only.
- After-tasks order: reload packs (POST /api/v1/admin/packs/reload or restart daab-server) BEFORE re-ingest, so autofill re-applies the refund mapping with risk_score (stored landed mappings freeze their field list; missing field → NULL). Re-ingest needs DEMO_DATA_DIR with master/*.csv + the subset folder; keep the recalculation range narrow. Same order in the prod checklist.
