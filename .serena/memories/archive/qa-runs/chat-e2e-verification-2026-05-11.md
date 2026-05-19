# AI Chat E2E Verification — 2026-05-11

## Test: "liệt kê 5 emails bất kỳ của users trong hệ thống" via C4K Staging

### Result: **PASS** (after 2 bug fixes)

## Bugs Found & Fixed

### Bug 1: ENCRYPTION_KEY missing from Python containers (P0)
- **Symptom**: Query returned "no results" despite Users table having 361K rows
- **Root cause**: `docker-compose.yml` did not pass `ENCRYPTION_KEY` env var to indexer/worker services
- **Impact**: Python could not decrypt `X-DB-DSN` header → fell back to Go proxy → no direct SQL execution
- **Fix**: Added `ENCRYPTION_KEY: ${KG_ENCRYPTION_KEY:-}` to both `indexer` and `worker` environment sections
- **File**: `docker-compose.yml` (2 locations)

### Bug 2: UnicodeDecodeError in MSSQL table streaming (P1)
- **Symptom**: `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe6` when serializing table block SSE event
- **Root cause**: pymssql.connect() called without `charset="UTF-8"` → returns raw cp1252 bytes for varchar columns → Pydantic model_dump crashes
- **Impact**: Markdown summary block streamed OK, but table block crashed → stream ended with INTERNAL_ERROR
- **Fix (3 layers)**:
  1. Added `charset="UTF-8"` to `pymssql.connect()` in `_get_mssql_conn()`
  2. Added defensive `bytes.decode("utf-8", errors="replace")` in `_execute_mssql()` after fetchmany
  3. Added fallback `_sse_default_encoder` for bytes in `format_sse()` JSON serialization
- **Files**: `ennam.kg.python/src/ennam_kg/db_client/client.py`, `ennam.kg.python/src/ennam_kg/streaming/models.py`

## Verification Matrix

| Layer | Test | Result |
|-------|------|--------|
| Infrastructure | All 6 Docker services healthy | PASS |
| Data Source | C4K Staging (MSSQL) connected, schema synced | PASS |
| AI Provider | Anthropic API (claude-sonnet-4) healthy, 0% error rate | PASS |
| API Auth | Login → session API key → UserIdentity resolved | PASS |
| SSE Pipeline | progress → generating_sql → executing → markdown → table → actions → done | PASS |
| Browser Login | /login → admin/Admin123!@# → Dashboard with C4K project | PASS |
| Browser Chat | /chat → New Thread → Type query → Stream → Display 5 emails | PASS |

## Emails Returned
- daragh@d3.ie
- roxanne@careforkids.com.au
- test12@careforkids.com.au
- test11@careforkids.com.au
- test10@careforkids.com.au

## Generated SQL
```sql
SELECT TOP 5 Users.*, UserCDetails.* FROM Users LEFT JOIN UserCDetails ON Users.ID = UserCDetails.UserID
```

## Minor Issues (non-blocking)
- Vietnamese diacritics display as `?` in thread sidebar titles (encoding issue in thread name, not content)
- CloudWatch metrics errors in Go logs (expected in local dev, no AWS credentials)
- PasswordHash binary data shows as `\ufffd` replacement chars in table block (expected, raw binary not displayable)
