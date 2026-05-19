# FE Integration: MSSQL Data Source Support — DONE

**Date**: 2026-04-23
**Status**: FRONTEND COMPLETE

## What was implemented

1. **DatabaseType** expanded: `'postgresql' | 'mssql'` in `src/types/datasource.ts`
2. **SslMode** expanded: PostgreSQL modes + MSSQL modes (`disable/true/false/strict`)
3. **DatabaseIcon component** (`src/components/data-sources/DatabaseIcon.tsx`):
   - PostgreSQL: blue elephant SVG
   - MSSQL: red SQL Server SVG
   - `DatabaseLabel` helper for icon + text
4. **DataSourceTable**: db_type column with icon + label badge per row
5. **DataSourceForm wizard**:
   - Step 1: Visual card selector (PostgreSQL vs SQL Server) with logos
   - Step 2: Connection details with db_type-aware defaults (port 5432 vs 1433)
   - SSL dropdown with different options per db_type
   - Connection string format adapts (`postgresql://` vs `sqlserver://`)
   - MSSQL uses `encrypt=` parameter, PostgreSQL uses `sslmode=`
6. **Edit mode** skips Step 1 (db_type can't change for existing DS)

## Files changed
- `src/types/datasource.ts` — DatabaseType, SslMode
- `src/components/data-sources/DatabaseIcon.tsx` — NEW
- `src/components/data-sources/DataSourceTable.tsx` — db_type column + icons
- `src/components/data-sources/DataSourceForm.tsx` — wizard + SSL dropdown
- `src/app/(dashboard)/data-sources/page.tsx` — edit wiring + useUpdateDataSource
