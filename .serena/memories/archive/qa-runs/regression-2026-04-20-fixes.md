# QA Full Regression Bug Fixes — 2026-04-20

**Status**: ALL 13 Go API bugs FIXED
**Commit**: 05b21e9 on main (merged from fix/qa-regression-2026-04-20)
**Docker**: Rebuilt and deployed

## Fixed Bugs

### P0 Blockers (3)
| # | Bug | Fix |
|---|-----|-----|
| 2 | Non-admin user creation — empty ProjectIDs rejected | Added `Internal: true` flag to CreateKeyRequest, bypasses project_ids validation for user-linked keys |
| 3 | Admin self-disable not blocked | Added UserIdentity check in DisableUser handler, returns 400 "cannot disable your own account" |
| 4 | Auto-create thread crashes on stream | Added null safety in ai_stream handler for missing thread_id |

### P1 Critical (10)
| # | Bug | Fix |
|---|-----|-----|
| 6 | Viewer can create nodes (no RBAC) | Added viewer role check in node.go HandleStoreNode and link.go HandleCreateLink, returns 403 |
| 7 | Same password accepted | Added `currentPassword == newPassword` check in ChangePassword, returns validation error |
| 8 | Archive write protection missing | Added archived project check in project.go write handlers |
| 9 | Duplicate project name → 500 | Catch unique constraint violation, return 409 Conflict |
| W2#2 | Benchmark enum mismatch | Aligned validDifficulties/validQueryTypes with DB CHECK constraints |
| W2#3 | SSE/WS routing unreachable | Moved /stream/ and /ws/ routes from apiMux to outer mux |
| W2#4 | Column duplication in extraction | Fixed duplicate query/loop in schema_extractor via datasource handler |
| W2#5 | Extract-schema 500 race condition | Made extraction async (goroutine), return 202 immediately |
| W2#6 | Heartbeat kills long extractions | Changed stale detection from 3min to 30min interval |

## Files Changed (12)
- cmd/kg-server/main.go (SSE routing + heartbeat)
- internal/handler/ai_stream.go (thread null safety)
- internal/handler/benchmark.go (enum alignment)
- internal/handler/datasource.go (async extraction + dedup)
- internal/handler/link.go (viewer RBAC)
- internal/handler/node.go (viewer RBAC)
- internal/handler/project.go (archive block + duplicate 409)
- internal/handler/sync_portal.go (SSE/WS route split)
- internal/handler/user.go (admin self-disable block)
- internal/service/apikey.go (Internal flag)
- internal/service/user.go (Internal key + same-password check)
