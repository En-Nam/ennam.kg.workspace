# BE Change Request: Data Source Sync Status Tracking

**Date**: 2026-04-13
**Status**: IMPLEMENTED AND DEPLOYED
**Commit**: `f5c0901` on `ennam.kg.go/main`
**Migration**: 000030_add_sync_status_to_datasources

---

## Resolution

Implemented Approach A as proposed. Changes:

1. **Migration 030**: Added `last_sync_status`, `last_sync_at`, `last_sync_job_id` to `data_sources`
2. **Model + Store**: Updated DataSource struct, GetByID, ListByProject scans, new `UpdateSyncStatus()` method
3. **Service hooks**: SchemaExtractorService and SchemaSyncService update data source sync status at MarkStarted, MarkCompleted, and failJob
4. **Auto-status**: Sync completed → `status = "connected"` (overrides test-connection error)
5. **Backfill**: Ran SQL to populate existing data sources from latest sync jobs

## Remaining: FE Changes

See `project/fe-action-required-sync-status` for FE action items:
- Update TypeScript type (add 3 new fields)
- Invalidate data-sources query on sync mutations
- Add staleTime + conditional polling
- Display sync status badge
