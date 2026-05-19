# Go API Team → Python Team: MSSQL Dialect Support

**Date**: 2026-04-23
**From**: Go API Team (ennam.kg.go)
**To**: Python Team (ennam.kg.python)
**Re**: SQL dialect field added to stream request — Python needs to consume it
**Priority**: HIGH — currently testing on MSSQL data source

---

## What Changed (Go side, commit a35638b)

`POST /api/v1/ai/stream` request body now includes a new field:

```json
{
  "thread_id": "uuid",
  "message_id": "uuid",
  "project_id": "uuid",
  "data_source_id": "uuid",
  "query": "Show me top 10 users",
  "tier": "balanced",
  "dialect": "mssql",          ← NEW FIELD
  "context_messages": [...]
}
```

### Field: `dialect`
- **Type**: string, optional
- **Values**: `"postgres"` (default if absent) or `"mssql"`
- **Source**: Resolved from `data_sources.db_type` by Go API before sending to Python
- **Purpose**: Python should use this to generate correct SQL syntax

### MSSQL vs PostgreSQL SQL Differences

| Feature | PostgreSQL | MSSQL |
|---------|-----------|-------|
| Row limit | `LIMIT 10` | `SELECT TOP 10` |
| Type cast | `column::integer` | `CAST(column AS INT)` |
| Case-insensitive match | `ILIKE` | `LIKE` (MSSQL is CI by default) |
| String concat | `\|\|` | `+` |
| Boolean | `true/false` | `1/0` |
| Current timestamp | `NOW()` | `GETDATE()` |
| Date truncate | `date_trunc('month', col)` | `DATETRUNC(month, col)` or `CONVERT` |
| Schema qualifier | `public.table` | `dbo.table` |
| Identity column | `SERIAL` / `GENERATED` | `IDENTITY(1,1)` |
| Upsert | `ON CONFLICT DO UPDATE` | `MERGE` |
| Returning | `RETURNING *` | `OUTPUT inserted.*` |

### Python Team Action Required

In `generate_sql()` (or equivalent), consume the `dialect` field from the stream request:

```python
# Example
dialect = request.get("dialect", "postgres")

if dialect == "mssql":
    # Use TOP N instead of LIMIT N
    # Use CAST() instead of ::type
    # Use GETDATE() instead of NOW()
    # Use dbo schema prefix instead of public
```

If `dialect` is absent or empty, default to `"postgres"` (backward compatible).

### Testing

We have a live MSSQL data source: **C4K Staging** (314 tables, Azure SQL). Schema extraction and KG generation completed successfully. Chat queries are the next test — need Python to generate MSSQL-compatible SQL.

### Go-side Async NL Pipeline

Go's own `SQLGenerator` also hardcodes `LIMIT N` (PostgreSQL). This is a known gap but lower priority — chat streaming (Python path) is the primary user-facing flow. Go team will add dialect to the internal SQL generator later if needed.
