# Bug: KG Generation Has 2 Entry Points, 1 Broken

**Date**: 2026-04-23
**Status**: FIXED — commit ef6c6b2
**Priority**: Medium

## Problem
KG generation has 2 handlers writing to 2 different tables:

| Handler | Endpoint | Table | Works? |
|---------|----------|-------|--------|
| `KGGenerationHandler.GenerateKG` | `POST /api/v1/data-sources/{id}/generate-kg` | `kg_generation_jobs` | YES |
| `SyncPortalHandler.TriggerSync` | `POST /api/v1/sync/{ds_id}/trigger` (job_type=kg_generation) | `sync_jobs` | **NO — creates placeholder, never executes** |

## Root Cause
`sync_portal.go` line 181-194: `kg_generation` case creates a `sync_jobs` record then does nothing (line 194: `// TODO: publish message to Redis queue for Python worker`). Job stays pending forever.

FE dashboard "Sync" button triggers SyncPortal → broken path.

## Recommended Fix (option 1 — preferred)
In `sync_portal.go` `kg_generation` case, call `generator.Generate()` directly (same pattern as `schema_extraction` case) instead of creating a placeholder:
- Add `kgGenerator *service.KGGenerator` to SyncPortalHandler
- Wire in main.go
- Call `kgGenerator.Generate(ctx, dataSourceID, projectID)` 
- Remove TODO placeholder

## Files
- `internal/handler/sync_portal.go` lines 181-194
- `cmd/kg-server/main.go` — wire generator into SyncPortalHandler
