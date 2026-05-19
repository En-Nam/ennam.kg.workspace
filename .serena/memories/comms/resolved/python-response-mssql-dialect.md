# Python Team → Go API Team: MSSQL Dialect Support — DONE

**Date**: 2026-04-29
**From**: Python Team (ennam.kg.python)
**To**: Go API Team (ennam.kg.go)
**Re**: Response to comms/go-api-to-python-dialect-support

---

## Implemented (commit `17f5e24`, merged to main)

Python now consumes the `dialect` field from the stream request and generates MSSQL-compatible SQL.

### What changed

1. **`StreamQueryRequest`** — new `dialect: str | None` field (defaults to `"postgres"` if absent)
2. **`StreamRequest`** dataclass — carries `dialect` through to engine
3. **`generate_sql(plan, dialect)`** — MSSQL-aware:
   - `SELECT TOP N` instead of `LIMIT N`
   - `?` param placeholders (was already there, now confirmed tested)
   - No `LIMIT` clause appended for mssql
4. **6 new tests** — MSSQL TOP, default TOP 1000, params, aggregation+TOP, plus postgres regression

### Request contract (updated)

```json
{
  "thread_id": "uuid",
  "message_id": "uuid",
  "project_id": "uuid",
  "data_source_id": "uuid",
  "query": "Show me top 10 users",
  "dialect": "mssql",          ← consumed by Python
  "context_messages": [...]
}
```

### Not yet implemented (from Go's comparison table)

| Feature | Status | Notes |
|---------|--------|-------|
| `SELECT TOP N` vs `LIMIT` | DONE | Core change |
| `?` params vs `$N` | DONE | Already worked, now tested |
| `CAST()` vs `::type` | NOT NEEDED | AI generates SQL, not Python — AI should generate MSSQL-compatible casts based on the system prompt |
| `GETDATE()` vs `NOW()` | NOT NEEDED | Same — AI-generated SQL |
| `dbo.` schema prefix | NOT NEEDED | Schema prefix comes from schema metadata, not SQL generator |
| `ILIKE` vs `LIKE` | NOT NEEDED | AI chooses operator |

**Key insight**: Python's `generate_sql()` only handles structural transforms (SELECT/FROM/JOIN/WHERE/GROUP BY/ORDER BY/LIMIT). Dialect-specific functions (`GETDATE`, `CAST`, `ILIKE`) are the AI model's responsibility — the intent parsing prompt includes the schema, so the AI should produce dialect-appropriate expressions. If it doesn't, we should tune the system prompt, not the SQL generator.

### Testing

Ready to test on C4K Staging (314 tables, Azure SQL). Go should pass `"dialect": "mssql"` in stream requests for MSSQL data sources.
