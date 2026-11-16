# Decision: POS t-log ingestion into a separate "landed" store (L1–L14)

Source of truth: `docs/superpowers/specs/2026-11-11-tlog-landed-ingestion-design.md` (decision table L1–L14); plan `docs/superpowers/plans/2026-11-11-pos-data-model-tlog-landed.md`. Implemented on branch `task/pos-data-model` (go, python, next, packs, LAAM), 2026-11-11..13.

- L1 new metric mode `landed` (our stored, normalised data); switching live⇄landed needs no pack/LAAM change.
- L2 separate Postgres database `ennam_landed` (`LANDED_DATABASE_URL` / `LANDED_WRITER_URL` / `LANDED_ENGINE_URL`).
- L3 industry-neutral storage: `landed_record(entity, data jsonb)` partitioned; no sale/claim tables in core (D10).
- L4/L5 (Phase 2, not built): per-project view schema `pv_<uuid>` + login role `lp_<uuid>` for NL→SQL; session `set_config` is NOT an isolation boundary.
- L6 raw files in object storage; Postgres keeps batch/checksum/status; pending-deletion queue so purge/retention never loses keys.
- L7 monthly partitions on `business_date` + DEFAULT partition; retention 25 months (master feeds never expire by date).
- L8 Python worker parses (POSLog first), YAML crosswalk per vendor/version with overrides; Go↔Python path-grammar parity corpus in packs `_testdata`.
- L9 canonical 0.7.0 MINOR, additive (incl. `-- optional:` header, `master.natural_key`, crosswalk `group_key`).
- L10 RX = pharmacy-pack field `is_rx`, decided per line.
- L11 enabling landed = human system admin + consent note (append-only log).
- L12 master data uploaded into landed as complete lists (absent rows retired).
- L13 worker never reads packs directly: Go sends catalog snapshot + merged crosswalk; finish triggers coalesced recalc in Go.
- L14 neutral routes `/api/v1/projects/{id}/landed/*`, package `landed_ingest`, queue `ennam-kg:landed`, stuck-batch reaper with lease renew.

Deploy order: landed DB+roles → kg-server + worker with LANDED_* → packs. kg-server single replica. Gate: no real customer t-log until WS0 closes.

NOTE: KG MCP (kg_store_decision) was unavailable on 2026-11-13 (daab bridge "invalid api key") — these decisions still need backfill into the KG.
