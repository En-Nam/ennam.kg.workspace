# Backlog: HandleArchiveProject crashes for non-UUID caller identity

**Found:** 2026-07-16, during ad-hoc project cleanup (unrelated to the DAAB↔AAAA doc-sync plan — pre-existing bug, discovered opportunistically).

## Bug
`POST /api/v1/projects/{id}/archive` (`ennam.kg.go/internal/handler/project.go:296`, `HandleArchiveProject`) writes the caller's resolved identity into `projects.archived_by` (a `uuid` column, FK to `users(id)`). When called with the internal/service API key (whose resolved identity is an email string like `"dragoon@exnodes.vn"`, not a UUID), the query fails:
```
archive project: pq: invalid input syntax for type uuid: "dragoon@exnodes.vn"
```
→ 500 on every archive attempt made via the internal API key path (as opposed to a real human session with a UUID user id).

## Root cause
The handler presumably calls something like `resolveUserID(r)` and passes the raw string straight into the `archived_by` parameter without validating it's a UUID / resolving it to a real user id first. `archived_by uuid` is nullable, so a reasonable fix is: if the resolved identity isn't a valid UUID (i.e. it's a service/API-key caller, not a session user), pass `NULL` for `archived_by` instead of the raw identity string — mirroring how other worker-facing endpoints treat legacy API-key callers without a `UserIdentity` (see `mem:checkpoint/subagent-driven-doc-sync-planA-2026-07-15`'s note on `requireProjectRole`).

## Workaround used
Archived 25 test/junk projects directly via SQL (`UPDATE projects SET status='archived', archived_at=NOW(), archived_by=<real-user-uuid> WHERE ...`) instead of the broken API, using a real user's UUID found by looking up the email in `users`.

## Status
Not fixed. Low priority (only affects service/API-key callers hitting Archive, which isn't a normal call pattern — human dashboard users have real UUID session identities and are unaffected). Flagged for whoever next touches `project.go`.
