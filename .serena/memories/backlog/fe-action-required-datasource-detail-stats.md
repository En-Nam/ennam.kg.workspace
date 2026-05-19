# FE Action: Data Source Detail Stats — COMPLETED

**Date completed**: 2026-04-13
**Commit**: `9161669` fix(data-sources): wire metadata counts into StatBox + defensive FK null guard

## What was done:
1. **StatBox counts** — `useMetadata(id)` wired into detail page; computes `tableCount`, `columnCount`, `fkCount` from metadata tree using `.reduce()`. Shows `"--"` while loading.
2. **Defensive FK guard** — `const foreign_keys = rawFks ?? []` in SchemaBrowser `TableRow` prevents crash if BE returns `null` for `foreign_keys`.

## Verification:
- `http://localhost:3500/data-sources/{id}` → StatBox shows `85 Tables`, `1296 Columns`, `0 FKs`
- Schema Browser renders without console errors
- `npx tsc --noEmit` → 0 errors
