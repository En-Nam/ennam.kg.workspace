# Schema Extraction Fix — 2026-04-21

## Bug: Extraction stalled at 1/39 tables
- **Symptom**: Job status "running", progress 2% (1/39), no error message, goroutine appeared hung
- **Root cause**: `BulkUpsertForeignKeys` used `ON CONFLICT (source_table_id, constraint_name)` but unique constraint `source_fk_unique` is `(source_table_id, constraint_name, column_name)` — 3 columns not 2
- **Why it looked stuck**: Error propagated to `failJob` which also failed (type casting issue in UpdateStatus), so goroutine died silently. Air hot-reload buffered stdout, hiding all logs.
- **Fix**: Changed ON CONFLICT to match full 3-column unique constraint
- **Result**: 39/39 tables extracted in <5 seconds
- **Commit**: `b7051e5`

## AI Pipeline Status: READY FOR E2E TEST
All blockers cleared:
1. ✅ Anthropic API key working (health check: healthy)
2. ✅ Schema extraction: 39/39 tables
3. ✅ Python worker: service key works, can list projects
4. ✅ Heartbeat: updated_at column, won't kill long jobs
5. ✅ OAuth injection: scoped to claude_max only
6. ✅ Error diagnostics: full error body capture

Next: QA can run full NL→SQL pipeline test
