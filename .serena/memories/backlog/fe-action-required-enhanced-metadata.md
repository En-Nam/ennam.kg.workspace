# FE Action Required: Enhanced Schema Metadata Available

**Date**: 2026-04-13
**Status**: BE DEPLOYED — new fields available in API responses

---

## New Fields in API

### `GET /api/v1/data-sources/{id}` — 2 new fields

```json
{
  "database_size_bytes": 258589789583,
  "database_size_updated_at": "2026-04-13T10:00:00Z"
}
```

Display: `240.83 GB` (divide by 1024³)

### `GET /api/v1/data-sources/{id}/metadata` — table-level (8 new fields)

```json
{
  "table": {
    "total_size_bytes": 8237211648,
    "data_size_bytes": 8207745024,
    "index_size_bytes": 29466624,
    "toast_size_bytes": 0,
    "dead_rows": 0,
    "last_vacuum": null,
    "last_analyze": null,
    "table_comment": "JSON metadata from source DB or null"
  }
}
```

### Column-level (2 new fields)

```json
{
  "is_unique": false,
  "column_comment": "Description from source DB or null"
}
```

## FE Changes Suggested

### 1. Data Source list/detail: show total DB size
```
"C4K Datawarehouse — 240.8 GB"
```

### 2. StatBox or detail: show total data size
Sum `total_size_bytes` across all tables, format as human-readable.

### 3. SchemaBrowser: show table size
Next to row count estimate, show `"~48M rows · 56.8 GB"` per table.

### 4. SchemaBrowser: show unique badge on columns
If `is_unique: true`, show a UNIQUE badge/icon next to the column.

### 5. SchemaBrowser: show column comments as tooltip
If `column_comment` is not null, show as hover tooltip on the column row.

### TypeScript type updates needed

```typescript
// Add to SourceTable interface:
total_size_bytes: number;
data_size_bytes: number;
index_size_bytes: number;
toast_size_bytes: number;
dead_rows: number;
last_vacuum: string | null;
last_analyze: string | null;
table_comment: string | null;

// Add to SourceColumn interface:
is_unique: boolean;
column_comment: string | null;

// Add to DataSource interface:
database_size_bytes: number | null;
database_size_updated_at: string | null;
```

### Human-readable size formatter
```typescript
function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return (bytes / Math.pow(1024, i)).toFixed(i > 1 ? 1 : 0) + ' ' + units[i];
}
```
