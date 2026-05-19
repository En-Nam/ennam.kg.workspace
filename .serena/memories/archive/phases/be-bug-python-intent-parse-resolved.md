# BUG: Python Intent Parse Failure — RESOLVED (Config Issue)

**Date**: 2026-04-29
**Original report**: Frontend Team
**Root cause**: `ANTHROPIC_API_KEY=` empty in `.env` — NOT a code bug

## Timeline
1. FE reported: all chat messages fail with `INTENT_PARSE_FAILED`
2. FE debugged via Chrome DevTools: SSE pipeline confirmed working, error from Python
3. Python team deployed retry fix (commit `baca818`) — still failing
4. FE discovered: `.env` has `ANTHROPIC_API_KEY=` (empty)
5. Resolution: config issue — set API key and restart containers

## Python Code Fix (still valid improvement)
- Empty AI response now detected before json.loads → clearer error message
- Retry logic: 1 automatic retry on empty/invalid JSON

## Status
- Python code: FIXED (deployed)
- Config: PENDING — owner needs to set ANTHROPIC_API_KEY
- FE: READY — all SSE handling, error display, rich rendering complete
