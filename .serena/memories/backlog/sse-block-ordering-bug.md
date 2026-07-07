# RESOLVED — 2026-07-01

Bug D (sse-block-ordering-bug) has been fixed. See `mem:checkpoint/daab-2026-07-01` for full details.

**Root cause:** Data race between heartbeat goroutine and `proxyFromPython` both writing to `http.ResponseWriter` without mutex in `sse_stream.go`.

**Fix:** `lockedResponseWriter` wrapper in Go + `data.content` field fix in FE `onBlockContent` handler.

This backlog entry can be deleted.
