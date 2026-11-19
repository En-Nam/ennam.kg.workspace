# Deploy checklist — Card #5 (chat UI bugs, clickable records, refund drawer fields)

Ships together with card #4-speed on branch `task/improve_by_feedback_19112026`. Deploy only on the owner's go.

## Repos and order
1. **ennam.kg.packs 0.7.3** (adds `refund.risk_score`; POSLog crosswalk 1.3.0 maps `p:LineItem/p:Return/p:RiskScore`).
   Merge → main → tag `v0.7.3` (publishes the packs). Check first: `grep -rn "0\.7\.2" ennam.kg.packs` shows only CHANGELOG history.
2. **ennam.kg.go (DAAB)**: record SELECT returns `reason_code` / `risk_score` when declared. Deploy, then reload packs
   (`POST /api/v1/admin/packs/reload` or restart) and confirm the project runs packs 0.7.3.
3. **ennam.kg.python**: tests only for this card (no runtime change needed).
4. **LAAM**: chat i18n, clickable ids + row click, columnar result tables, `/api/chat/records/...`, drawer fields, BUG-03 prompt rule.

## Demo data backfill (prod demo project only)
The demo T-logs with `<RiskScore>`: `.superpowers/sdd/2026-11-11-pos-data-model-tlog-landed/e2e-data/poslog-12m-risk-changed/`
(511 files; produced by `scripts/landed/add-refund-risk-score.py`).
1. AFTER packs 0.7.3 are live on prod DAAB: run `scripts/landed/load-demo-data.py --poslog-dir poslog-12m-risk-changed
   --from <yesterday> --to <yesterday>` (same env as the 2026-11-16 demo load doc). This re-applies the refund mapping (autofill).
2. **Required:** the re-upload alone changes NOTHING (the writer records changed transactions as `conflicts`). For every
   batch created in step 1 call `POST /api/v1/projects/{pid}/landed/feeds/{feedId}/batches/{batchId}/replay` (admin) and
   wait until the queue is empty.
   If a replayed batch still reports `conflicts > 0`: read the batch's error and counts (the batch detail / feed batch list),
   then re-run replay for THAT batch and wait again. Repeat until `conflicts` is 0. Never edit landed rows by hand.
   Live-source orgs (e.g. Pharmacy Demo) need NO backfill: they read the source directly, and their refund mapping
   must map `reason_code` / `risk_score` for those fields to appear in the drawer.
3. Verify: refunds with a non-null `risk_score` ≈ number of refunds from the 12-month set (local: 651 of 655; the 4 without
   are the planted/top-up refunds outside `poslog-12m`). Batch counts: `superseded` > 0, `conflicts` 0.

## Demo camera clips for the T-log org (prod demo project only)
The chat drawer already shows a record's camera clips (same `recordResponse` as Intel; files served by
`/api/intel/media/{id}`, a 302 to the S3 object). The T-log org had none, so 3 demo clips are linked to its
highest-risk Nov refunds by `scripts/landed/tlog-demo-media.json` (reuses the existing `laam-demo/*.mp4` files in S3).
1. The `entityId` is the landed composite id `<first 8 chars of the T-log feed id>:[store, register, date, RTX]`. The local
   file uses `add94069`. On prod, look up the T-log feed id of the Pharmacy Demo (T-log) project
   (`select id from ingest_feed` in `ennam_landed`, or DAAB dashboard → Landed feeds) and replace the prefix in a COPY of
   the file. Store/register/date/RTX are the same (same XML).
2. Find the prod business project id of "Pharmacy Demo (T-log)" (`select id, name from business_project`).
3. `cd LAAM && SEED_CONFIRM=yes node --env-file=<prod env> node_modules/.bin/tsx scripts/seed-demo-media.ts <bp id> <copy>.json`
   (prints the target database first; `INTEL_MEDIA_BASE_URL` must be the same S3 origin). Idempotent.
4. Verify: chat "Cho tôi xem các lần hoàn tiền ngày 11/11/2026" → click `RTX-000177` → the drawer plays
   "Register 2 (demo)". Also the existing demo org (live source): `REF-000001` from chat shows its clip.

## Smoke test after deploy (EN + VI)
- Chat: "Cho tôi xem các lần hoàn tiền tháng 11/2026" → a code-built table under the answer, short ids (`RTX-…`, `TXN-…`) clickable.
- Click an id and a row → drawer shows reason, risk score, days since purchase, "currency not specified" (chat drawer only; the Home transactions and finding drawers use the configured currency and hide it); Escape keeps chat scroll.
- Pharmacy Demo (live source) org: ask the screenshot question; click `REF-000137`; check the answer does not claim
  "no original receipt" and flags the future date as "needs review" without a cause.

## Known pre-existing (not this card)
- DAAB `landedapi` TestMarginMetricEnabledAfterProductUpload fails on the base commits too.
- `scripts/check-core-words.sh` flags `db/landed_migrations/000007_join_key_columns.down.sql` (card #4-speed commit).
