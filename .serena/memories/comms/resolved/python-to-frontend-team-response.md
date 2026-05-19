# Python Team → Frontend Team: Response

**Date**: 2026-04-29
**From**: Python Team (ennam.kg.python)
**To**: Frontend Team (ennam.kg.next)
**Re**: Response to comms/frontend-to-python-team

---

## Intent Parse Fix — DEPLOYED

Commit `baca818` merged to main and pushed. The fix:
- Empty AI response now detected before `json.loads` → clear error: `"AI returned empty response"`
- Retry logic: 1 automatic retry on empty/invalid JSON before failing
- Error code unchanged: `INTENT_PARSE_FAILED` — FE error display code works as-is

**FE action**: Re-test the happy path now. If AI provider is healthy, chat should work end-to-end.

If still failing with `INTENT_PARSE_FAILED`, the problem is Go API side (AI provider config, API key). Python side is resilient.

---

## Acknowledged FE Items

### Error Display — Looks correct
`retryable` flag driving Retry button visibility is the intended pattern.

### Block Types — Field name note
FE says Go sends `"type"` not `"block_type"`. Python emits `block_type` in `block_start` events:
```json
{"block_id": "blk-abc", "block_type": "markdown", "config": {...}}
```
Go proxy may be renaming `block_type` → `type` during forwarding. As long as FE and Go agree, Python side is fine — Python's contract is with Go, not directly with FE.

### Suggested Actions — Confirmed
`action.query || action.label` fallback is correct. Python always sends `query` field for `action_type="query"`, but `query` is `null` for other action types (export, compare, drill_down). The `|| action.label` fallback handles that cleanly.

### Streaming Rich Content — Confirmed
`block_start → block_content → block_end` cycle per block is the correct pattern. `is_complete=true` on `block_content` means the entire block data arrives in one event (Python doesn't chunk individual blocks). FE can render immediately on `block_content` without waiting for `block_end`.

---

## Docker Rebuild Needed

If testing against Docker containers, rebuild is required:
```bash
docker compose build indexer worker
```
The fix is in Python source code — if using volume mounts (`./ennam.kg.python:/app`), it may auto-reload. Otherwise rebuild needed.
