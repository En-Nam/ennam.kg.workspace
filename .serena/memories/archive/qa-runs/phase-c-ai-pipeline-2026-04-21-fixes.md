# Phase C AI Pipeline Fixes — 2026-04-21

**Status**: ALL 4 blockers FIXED
**Commit**: 27a2115 on main
**Migration**: 041 (ssl_mode CHECK expanded)

## Fixed

| # | Blocker | Fix |
|---|---------|-----|
| 1 | AI selector built at startup only | Added `Selector.RebuildEntries()` — called after provider create/update/deactivate in handler |
| 2 | Docker PG no SSL | Migration 041 adds `disable` + `prefer` to ssl_mode CHECK constraint |
| 3 | Extract-schema requires JSON body | Handler now accepts empty body, defaults created_by from auth context |
| 4 | Health check fails with OAuth | Handler checks OAuthService for active token, uses it instead of dummy api_key |

## AI Pipeline Now Unblocked
- Data source can connect with ssl_mode=disable ✅
- Schema extraction works without body ✅
- AI providers reload dynamically ✅
- Health check works with OAuth ✅
