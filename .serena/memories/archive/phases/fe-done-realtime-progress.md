# FE Integration: Real-time Progress via SSE — DONE

**Date**: 2026-04-23
**Status**: FRONTEND COMPLETE — Unified SSE across all 3 pages

## Architecture
One SSE endpoint for ALL job types: `GET /api/kg/sync/{job_id}/progress/stream`
- Schema extraction: phases starting → extracting → done (per-table 0-100%)
- KG generation: phases generating_nodes → mapping_edges → detecting_implicit → done (0/33/66/100%)
- Goes through BFF proxy (same origin, no CORS)

## Files
- `src/hooks/use-job-progress.ts` — unified SSE hook (replaces old use-extraction-progress.ts)
- `src/components/data-sources/SyncProgressBar.tsx` — progress bar with phase labels for all job types

## Wired into all 3 pages consistently:
| Page | SSE for Extraction | SSE for KG Gen | Captures job_id |
|------|:--:|:--:|:--:|
| `/data-sources` (list) | YES | — | On trigger success |
| `/data-sources/[id]` (detail) | YES (auto-detect running job) | YES (auto-detect running KG job) | From syncJobs/generationJob |
| `/admin/sync` (portal) | YES | YES | On trigger success |

## Deleted files
- `src/hooks/use-extraction-progress.ts` — replaced by use-job-progress.ts
- `src/hooks/use-ws-progress.ts` — deleted (WebSocket approach abandoned)
