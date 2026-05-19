# Phase A Verification Fixes — 2026-04-20

**Status**: ALL 6 bugs FIXED
**Commits**: 1172778, 6040061, a11a2d0, d838f73, f47d0c0 on main

## Fixed Bugs

| # | Bug | Root Cause | Fix | Commit |
|---|-----|------------|-----|--------|
| P0 | API keys don't authenticate | Login revoked Platform Admin Key (seed key shared with user) | Login now only revokes `web-session-*` labeled keys; seed creates separate web-session key | 1172778 |
| P1 | Archive write protection not effective | Check was in project handlers, not node/edge handlers | Added ProjectStatusCheckerFunc in ProjectID middleware — blocks POST/PUT/PATCH/DELETE on archived projects | 6040061 |
| P1 | Thread archive filter missing | List query didn't filter archived threads | Added `is_archived = false` default filter + `include_archived` param | a11a2d0 |
| P1 | Thread search missing | Search param ignored | Added ILIKE search in thread list query | a11a2d0 |
| P2 | Login revokes ALL previous keys | Login revoked any key pointed to by user.api_key_id | Login checks label prefix before revoking — only `web-session-*` keys revoked | 1172778 |
| P2 | SSE route 500 "streaming not supported" | Logging middleware wraps ResponseWriter, hiding http.Flusher | Added Unwrapper interface to walk wrapper chain and find Flusher | d838f73 |

## Additional Fix
- Seed script: user.api_key_id now points to Platform Admin Key for dev; status='active' for easier testing | f47d0c0

## RBAC Testing Now Unblocked
With P0 API key fix, created API keys now authenticate correctly. All RBAC test cases can proceed.
