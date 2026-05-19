# FE Action Required: Graph Page Edge Deduplication

**Date**: 2026-04-21
**Priority**: HIGH — graph page shows 615 edges instead of 44

## Problem
`/graph` page shows 39 nodes + 615 edges. DB has only 44 edges.

## Root Cause
BFF proxy at `src/app/api/kg/[...path]/route.ts` lines 58-76 converts ALL `traversal_nodes` into edges. With `max_depth=3`, the traversal walks the same FK edge multiple times from different starting nodes, creating duplicate entries.

Example: FK `orders→users` is traversed as:
- Depth 1 from `orders`: outgoing edge
- Depth 1 from `users`: incoming edge (reverse mapped)
- Depth 2+3: re-walks same edges from neighboring nodes

## Fix (BFF proxy, ~3 lines)
In `src/app/api/kg/[...path]/route.ts`, deduplicate by `edge_id`:

```typescript
// Before line 76, replace the edges array push logic:
const edgeMap = new Map<string, typeof edges[0]>();
// Inside the traversal loop, change edges.push(...) to:
if (edge_id && !edgeMap.has(edge_id)) {
  edgeMap.set(edge_id, {
    id: edge_id,
    source_id: isOutgoing ? source_node_id : nodeData.id,
    target_id: isOutgoing ? nodeData.id : source_node_id,
    edge_type: edge_type ?? 'relates_to',
    created_by: '',
    created_at: '',
  });
}
// Then: data.edges = Array.from(edgeMap.values());
```

## Alternative: Reduce max_depth
In `src/hooks/use-graph.ts` line 18, change `max_depth: 3` to `max_depth: 1`. This reduces traversal to direct neighbors only, which is sufficient for FK visualization. But dedup is the proper fix.

## Verification
After fix: `/graph` should show 39 nodes + 44 edges (matching DB count).
