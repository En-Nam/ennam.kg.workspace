# Checkpoint: claude — 2026-11-03 (pharmacy demo: new days, receipt photo, collapse animation, CEO setup)

## State (all LOCAL; nothing committed or pushed)
- DAAB local project 90e0ba5c: data source "Pharmacy DB" TEMPORARILY points at local pharmacy_demo (postgres:5432, sslmode=disable) because the shared source host (EC2 devshared-...:5432, db connector_db) stopped answering at about 18:35 VN. Revert steps: ~/Backups/EnnamKG/2026-11-02/README.md.
- Data ends 2026-11-02 via scripts/demo_data/extend_demo.py (clones Sat/Sun/Mon of the prior week; refunds and snapshots not cloned; voids re-filed against new sales with an earlier-weekday fallback; --keep-claim-plant PH-004 flips the fewest approved claims, 10 here, so PH-CLAIM-001 stays above 2.5x, ratio 2.61).
  Build: uv run python extend_demo.py --input ../../demo_mockdata_shifted_91 --output ../../demo_mockdata_shifted_91_ext3 --days 3 --keep-claim-plant PH-004 ; then retarget_demo.py --data <out> ; load_pharmacy_demo.sh (CONFIRM_LIVE_RELOAD=yes + backup).
- DAAB: as-of 2026-11-02, 48/48 current, 0 blocked. LAAM analysis: 75 findings (1 critical, 2 high, 1 medium), expected-findings check PASS 9/9.
- No packs, rules, thresholds or Go/dashboard code changed. Data tweaks are the synthetic extension above plus the claim flips.
- Receipt photos: LAAM evidence_media.kind (migration 0044), ReceiptImage with collapse animation, make_receipt_images.py. Seeded 3 videos + 4 photos (REF-000037, REF-000047, TXN-0004046, TXN-0004665).
- owner.demo@yopmail.com: profile wizard done and preset "CEO chuỗi nhà thuốc UnityCare" (id 89bbee1a-3ed0-4ebe-b5d8-88a183dfa227, published v1, template sales, one agent, no workflows/connectors) assigned. Backup laam.0311-2133-before-ceo-setup.dump. Open: role field is "sales" (no executive option), Home banner still lists "create preset from role template".
- Tests: LAAM unit 7772, media int 3, demo_data 159, ruff clean.

## Open
- Shared source host down; push of the extended data, switching the data source back, and re-running metrics + analysis once it is back.
- Details for inventory/refund findings still have no cause/forecast/chart (needs trend chart + cause configs).
- Commit: LAAM (media kind + ReceiptImage + migration 0044), scripts/demo_data (extend_demo, make_receipt_images, tests, pyproject/uv.lock). LAAM/media and demo_mockdata_* are untracked.
