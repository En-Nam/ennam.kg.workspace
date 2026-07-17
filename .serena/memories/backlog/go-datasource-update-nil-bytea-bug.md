# Backlog: DataSourceStore.Update nil-bytea bug (same as fixed SourceConnectionStore bug)

**Found:** 2026-07-15, during Task 5 of `mem:checkpoint/subagent-driven-doc-sync-planA` (DAAB↔AAAA doc-sync plan).

**Bug:** `ennam.kg.go/internal/store/datasource.go`, `DataSourceStore.Update` (~lines 253-271), has:
```sql
connection_string_encrypted = CASE WHEN $4::bytea IS NOT NULL THEN $4 ELSE connection_string_encrypted END
```
called with `ds.ConnectionStringEncrypted` (a Go `[]byte`) passed directly as `$4`.

This is ineffective: a Go `nil`/empty `[]byte` passed as a `database/sql` query arg does NOT become a real SQL `NULL` — it's a "valid" driver value per Go's rules, and `lib/pq` encodes it as an EMPTY bytea, not NULL. So `$4::bytea IS NOT NULL` is TRUE even when the caller didn't intend to update the credential, and the CASE-WHEN takes the wrong branch — silently overwriting the stored encrypted connection string with empty bytes instead of preserving it.

**Confirmed same root cause as a bug found and fixed in `SourceConnectionStore.Update`'s identical pattern for `credential_encrypted`** (fix commit `d38d822` in `ennam.kg.go`, `mem:checkpoint/subagent-driven-doc-sync-planA`). That fix: convert nil/empty slice to a genuine `interface{}(nil)` before use as a query arg:
```go
var credArg interface{}
if len(x) > 0 {
    credArg = x
}
```

**Fix:** apply the identical pattern to `DataSourceStore.Update`'s `connection_string_encrypted` argument.

**Why not fixed immediately:** out of scope for the doc-sync plan's Task 5 (which only touches `SourceConnectionStore`); correctly left untouched per Rule 3 (surgical changes) — flagged instead of silently fixed or silently ignored.

**Risk:** any `DataSource` update call that doesn't re-supply the connection string (e.g. updating just a display name) will silently blank the stored encrypted DB credential. Worth verifying whether this has already caused a real incident before treating it as low-priority.
