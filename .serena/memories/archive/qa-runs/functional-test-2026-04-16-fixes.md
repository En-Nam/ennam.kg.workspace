# QA Bug Fixes — 2026-04-16

**Status**: ALL P0 + P1 Go API bugs FIXED
**Commits**: 6 fixes on main (a393a18 → 19d40f4)

## Fixed Bugs

| # | Priority | Bug | Root Cause | Fix | Commit |
|---|----------|-----|------------|-----|--------|
| 1 | P0 | UserIdentity never injected (15 endpoints blocked) | Auth middleware didn't look up user from API key | Added UserResolverFunc + wired in main.go | a393a18 |
| 2 | P1 | Session creation enum mismatch | PostgreSQL ENUM type vs text string | Added ::session_status cast in SQL | 3dd763c |
| 3 | P1 | Project members all 500 | Store query referenced wrong column names (u.name → u.display_name) | Fixed column references | 2476073 |
| 4 | P1 | Settings update always 500 | Used API key ID instead of user ID for updated_by FK | Use UserIdentity.UserID | 2476073 |
| 5 | P1 | AI query favorites 500 | New query_favorites schema uses UUID user_id, old code sent VARCHAR | Rewrote store methods + resolve from context | a2dd129 + 19d40f4 |
| 6 | P1 | Benchmark all 500 | NULL JSONB for expected_results + FK not caught | interface{} wrapper + FK error → 404 | 6cf289c + 19d40f4 |

## Remaining (Non-Go API)
- P1 #6: Create Project CTA → dead route `/projects/new` (NextJS team)
- P1 #7: Edit Project CTA → no visible result (NextJS team)
- P2: Dead CTAs, ghost buttons (NextJS team)
- P3: Disabled buttons without tooltips (NextJS team)

## Recurring Pattern Fixed
NULL JSONB → PostgreSQL error occurred in: sync_jobs (fixed earlier), SchemaBrowser foreign_keys (fixed earlier), benchmark expected_results (this fix). Convention: always use `var param interface{}; if len(field) > 0 { param = []byte(field) }` for nullable JSONB columns.
