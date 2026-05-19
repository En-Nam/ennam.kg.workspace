# Fix: KG Generation Progress Not Visible to FE

**Date**: 2026-04-23
**Status**: FIXED — commit 26aede5
**Priority**: High

## Problems

### 1. SSE stream empty during node generation
KG generator broadcasts only 4 events (0%, 33%, 66%, 100%). The `generating_nodes` phase takes 20-30 min (AI call per node × 314 nodes) with ZERO events between 0% and 33%. FE SSE stream appears empty.

**Fix**: Add per-node broadcast inside `generateNodes()` loop in `kg_generator.go`. Similar to extraction's per-table broadcast.

```go
// In generateNodes loop, after each node created:
if g.broadcaster != nil {
    pct := (created * 33) / totalTables // Scale 0-33% for node phase
    g.broadcaster.BroadcastProgress(jobID, "running", "generating_nodes", pct, totalTables, created)
}
```

### 2. FE doesn't see KG jobs in sync-jobs endpoint
KG generation writes to `kg_generation_jobs`, not `sync_jobs`. FE polls `GET /data-sources/{id}/sync-jobs` which only queries `sync_jobs` → KG gen jobs invisible.

**Fix options**:
- **A (quick)**: Add `GET /data-sources/{id}/kg-jobs` endpoint that queries `kg_generation_jobs` — FE polls both
- **B (proper)**: Modify `GET /data-sources/{id}/sync-jobs` handler to UNION both tables, returning a unified job list
- **C (ideal)**: Create a `GET /data-sources/{id}/jobs` endpoint that merges sync_jobs + kg_generation_jobs with a common response format

### 3. generateNodes needs job_id for broadcasting
Currently `generateNodes()` doesn't receive `job.ID`. Need to pass it through.

## Files to Change
- `internal/service/kg_generator.go` — per-node broadcast in generateNodes loop
- `internal/handler/datasource.go` or `sync_portal.go` — unified job list endpoint
- FE: poll the right endpoint for KG jobs

## Constraint
Do NOT restart kg-server while KG generation is running — goroutine will die.
Wait for current job (314 nodes with AI descriptions, ~24 min remaining) to complete.
