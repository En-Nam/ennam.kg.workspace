# Python Team → All Teams: Anthropic API Key Issue Acknowledged

**Date**: 2026-04-29
**From**: Python Team
**To**: All Teams
**Re**: Response to comms/frontend-config-issue-anthropic-key

---

## Root Cause Confirmed

`ANTHROPIC_API_KEY=` empty in `.env` is the true root cause of chat failures. The chain:

```
Empty API key → Go AI provider sends request with no auth → Anthropic returns empty/error
→ Go returns empty content to Python → json.loads("") fails → INTENT_PARSE_FAILED
```

Python's retry fix (commit `baca818`) provides resilience for transient failures, but cannot fix a permanently missing API key. Retrying with the same empty key will produce the same empty response.

## Action Items

| # | Action | Owner | Status |
|---|--------|-------|--------|
| 1 | Set `ANTHROPIC_API_KEY=sk-ant-...` in root `.env` | DevOps / Project Owner | REQUIRED |
| 2 | `docker compose restart kg-server indexer worker` | DevOps | After item 1 |
| 3 | Re-test chat end-to-end | Frontend Team | After item 2 |

## Python Side Status

- Intent parser retry logic: DEPLOYED (handles transient empty responses)
- SSE streaming pipeline: WORKING (confirmed by SSE trace — progress events fire correctly)
- No further Python changes needed for this issue
