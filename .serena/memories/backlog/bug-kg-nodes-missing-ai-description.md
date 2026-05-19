# Bug: Schema Nodes Missing AI Descriptions After Re-run

**Date**: 2026-04-23
**Status**: KNOWN — deferred fix
**Priority**: Medium

## Problem
314 schema_table nodes have placeholder content (`"Schema table dbo.X (N columns, ~M rows)"`) instead of AI-generated descriptions. Only 0/314 have `ai_description`.

## Root Cause
`kg_generator.go` line 177-183: existing nodes are **skipped** via `continue` for idempotency. `generateDescription()` is only called for NEW nodes (line 186).

First KG generation ran WITHOUT AI provider → nodes created with placeholder content. Subsequent runs see nodes exist → skip them → AI description never generated.

## Code Path
```
generateNodes() loop:
  if existingMap[title] exists → continue (SKIP, no AI call)
  else → generateDescription(ctx, treeTable, schema) → create node with AI content
```

## Fix Options

### Option A: Backfill command (recommended)
Add a new endpoint or CLI command: `POST /data-sources/{id}/generate-descriptions`
- Iterates existing schema_table nodes
- Calls `generateDescription()` for nodes with placeholder content
- Updates node properties with AI description
- Idempotent: skips nodes already having AI descriptions

### Option B: Re-generate on existing nodes
Change `generateNodes()` to also call `generateDescription()` for existing nodes that lack AI content:
```go
if existingID, ok := existingMap[title]; ok {
    nodeMap[title] = existingID
    // Check if node needs AI description
    if needsAIDescription(existingID) {
        aiDesc := g.generateDescription(ctx, treeTable, schemaName)
        if aiDesc != "" {
            updateNodeContent(ctx, existingID, aiDesc)
        }
    }
    continue
}
```
Risk: slows down re-runs (AI call per node), may conflict with user edits.

### Option C: Delete + regenerate
Delete all schema_table nodes for the data source, then re-run KG generation.
Destructive: loses edges, versioning, any manual edits.

## Workaround (immediate)
Delete existing nodes + edges for the data source, re-trigger KG generation while AI provider is active:
```sql
DELETE FROM knowledge_edges WHERE source_id IN (
  SELECT id FROM knowledge_nodes WHERE properties->>'source_data_source_id' = '{ds_id}'
);
DELETE FROM knowledge_nodes WHERE properties->>'source_data_source_id' = '{ds_id}';
```
Then re-trigger `POST /data-sources/{id}/generate-kg`.

## Files
- `internal/service/kg_generator.go` lines 177-194 (generateNodes idempotency skip)
- `internal/service/kg_generator.go` lines 252-300 (generateDescription AI call)
