# FE Sync Status Integration — COMPLETED

**Date**: 2026-04-13
**Status**: DONE — all items implemented and pushed

## What Was Done (commit 46a8398)

### 5 files changed:

1. **`src/types/datasource.ts`** — Fixed `DataSourceStatus` enum to match BE (`pending|connected|error|disabled`), added `SyncStatus` type, added 3 new fields to `DataSource` interface

2. **`src/hooks/use-data-sources.ts`** — Added `staleTime: 30s`, `refetchOnWindowFocus: false`, conditional polling every 5s when `last_sync_status === 'running'`

3. **`src/hooks/use-sync.ts`** — Added `queryClient.invalidateQueries(['data-sources'])` and `['data-source']` to both `useTriggerSync` and `useCancelSync` onSuccess

4. **`src/components/data-sources/DataSourceTable.tsx`** — Fixed `StatusBadge` to use correct BE enum, added `SyncBadge` component (with spinner for running), fixed `lastSyncedText()` to use `last_sync_at`, fixed `isSyncing` to use `last_sync_status`

5. **`src/app/(dashboard)/data-sources/[id]/page.tsx`** — Fixed STATUS_MAP, added sync history section showing last 10 jobs with status badges and table counts, added last sync info to details panel
