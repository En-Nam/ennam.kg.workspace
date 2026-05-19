# FE Action Required: Schema Graph Data Source Selector

**Date**: 2026-04-22
**Priority**: HIGH — schema-graph page only shows first data source

## Problem
`src/app/(dashboard)/schema-graph/page.tsx` line 467:
```typescript
const dataSourceId = dataSources?.[0]?.id ?? '';
```
Hardcoded to always use the first data source. When multiple data sources exist in a project (C4K + QA DB), only one is visible.

## Fix
Add a data source dropdown selector:
1. State: `const [selectedDsId, setSelectedDsId] = useState('')`
2. Effect: set default to first DS when `dataSources` loads
3. UI: add dropdown next to layout picker, listing all data sources by name
4. Pass `selectedDsId` to `useSchemaGraph(selectedDsId)` and `useMetadata(selectedDsId)`

## Current Data Sources
- C4K (index 0): 95 tables, 0 FK edges (data warehouse, no FKs)
- QA DB (index 1): 39 tables, 44 FK edges

## Impact
Users cannot see QA DB schema graph at all unless C4K is deleted or the code is changed.
