# FE Integration: Real-time Progress + Unified Job Listing

**Date**: 2026-04-23 (v2 — per-node broadcast + unified listing)
**Status**: BE DEPLOYED

## Key Changes from v1
1. `GET /data-sources/{id}/sync-jobs` now returns **BOTH sync_jobs AND kg_generation_jobs merged** — FE only needs ONE endpoint
2. KG generation broadcasts **per-node** during `generating_nodes` (0-33%), not just 4 events
3. SSE endpoint works for both job types via same URL

## Unified Job Listing

```
GET /api/v1/data-sources/{id}/sync-jobs
```

Returns merged array of sync_jobs + kg_generation_jobs, sorted by created_at DESC. Each job has `job_type` field (`schema_extraction`, `schema_sync`, or `kg_generation`). KG jobs include extra fields: `nodes_created`, `edges_explicit`, `edges_implicit`.

## SSE Endpoint

```
GET /api/v1/sync/{job_id}/progress/stream
```

Works for any job_id (from either table). Goes through BFF proxy.

## SSE Event Format

```
event: progress
data: {"job_id":"uuid","status":"running","current_phase":"extracting","progress_pct":42,"tables_total":314,"tables_processed":132,"errors_count":0}
```

## Phases by Job Type

### Schema Extraction: starting → extracting (per-table, 0-100%) → done
### KG Generation: generating_nodes (per-node, 0-33%) → mapping_edges (33%) → detecting_implicit (66%) → done (100%)

## FE Implementation

### 1. SSE Hook
```typescript
export function useJobProgress(jobId: string | null) {
  const [progress, setProgress] = useState(null);
  useEffect(() => {
    if (!jobId) return;
    const source = new EventSource(`/api/kg/sync/${jobId}/progress/stream`);
    source.addEventListener('progress', (e) => {
      const msg = JSON.parse(e.data);
      setProgress(msg);
      if (msg.status === 'completed' || msg.status === 'failed') source.close();
    });
    return () => source.close();
  }, [jobId]);
  return progress;
}
```

### 2. BFF SSE Pass-through
In `src/app/api/kg/[...path]/route.ts`:
```typescript
if (contentType.includes('text/event-stream')) {
  return new Response(res.body, {
    status: res.status,
    headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
  });
}
```

### 3. Job List — just poll sync-jobs (covers all job types now)
```typescript
const { data } = useQuery(['sync-jobs', dsId], () =>
  fetch(`/api/kg/data-sources/${dsId}/sync-jobs`).then(r => r.json())
);
// data = [{job_type: 'schema_extraction', ...}, {job_type: 'kg_generation', nodes_created: 314, ...}]
```

## Endpoints Summary

| Endpoint | What |
|----------|------|
| `GET /api/v1/sync/{job_id}/progress/stream` | SSE real-time progress |
| `GET /api/v1/data-sources/{id}/sync-jobs` | **Unified list (sync + KG merged)** |
| `POST /api/v1/data-sources/{id}/extract-schema` | Trigger extraction |
| `POST /api/v1/data-sources/{id}/generate-kg` | Trigger KG gen |
| `POST /api/v1/sync/{ds_id}/trigger` | Trigger any job type |
