# Phase 3: Projects, Users & Platform Administration — Master Plan

> **For agentic workers:** Execute plans in order: BA-014 → BA-015 → BA-016. Each plan is self-contained.

**Goal:** Add user accounts, authentication, project management with per-project roles, API key management, activity feed, and system settings to the Ennam KG Go API.

**Architecture:** Extends Phase 1-2's 3-layer pattern (Handler → Service → Store). New `users` + `project_members` + `system_settings` tables. Login via Go API with bcrypt, session via iron-session on FE. ProjectID middleware (already exists) gets wired into router with membership checks.

**Tech Stack:** Go std lib, `golang.org/x/crypto/bcrypt` (already in go.mod), PostgreSQL, `database/sql`

---

## Execution Order (Sequential — NOT Parallel)

```
Step 1: BA-014 → Users + Auth (12 endpoints, migration 032)
                 ↓ outputs: users table, login, middleware updates
Step 2: BA-015 → Projects + Members (11 endpoints, migration 033)
                 ↓ outputs: project_members, CRUD, permission enforcement
Step 3: BA-016 → Admin (12 endpoints, migrations 034-035)
                 ↓ outputs: API key REST, activity feed, settings
```

**Why sequential:** BA-015 needs `users` table from BA-014. BA-016 needs both `users` and `project_members`.

---

## Plan Documents

| Plan | BA | File | Endpoints | Migration |
|------|-----|------|-----------|-----------|
| Step 1 | BA-014 | [`phase3-ba014-user-accounts-auth.md`](2026-04-13-phase3-ba014-user-accounts-auth.md) | 12 | 032 |
| Step 2 | BA-015 | [`phase3-ba015-project-management.md`](2026-04-13-phase3-ba015-project-management.md) | 11 | 033 |
| Step 3 | BA-016 | [`phase3-ba016-platform-admin.md`](2026-04-13-phase3-ba016-platform-admin.md) | 12 | 034-035 |

---

## Migration Numbering

| # | Table | BA | Content |
|---|-------|----|---------|
| 032 | `users` | BA-014 | CREATE + indexes + seed admin + migrate existing API keys to system users |
| 033 | `project_members` | BA-015 | CREATE + ALTER projects (archived_at, archived_by) + indexes |
| 034 | `system_settings` | BA-016 | CREATE + seed 12 default settings |
| 035 | audit_trail ext | BA-016 | Add Phase 2+3 operation types to audit_trail |

---

## New Packages / Files Summary

```
internal/models/
├── user.go                     # User struct + constants + password validation (BA-014)
├── project_member.go           # ProjectMember struct (BA-015)
├── settings.go                 # SystemSetting struct (BA-016)

internal/store/
├── user.go                     # UserStore: CRUD + login tracking (BA-014)
├── project_member.go           # ProjectMemberStore: membership CRUD (BA-015)
├── settings.go                 # SettingsStore: key-value CRUD (BA-016)

internal/service/
├── user.go                     # UserService: create + auto-key + login + password (BA-014)
├── project_service.go          # ProjectService: create + archive + membership sync (BA-015)
├── membership.go               # MembershipService: add/remove + role change + key sync (BA-015)
├── settings.go                 # SettingsService: get/set with cache + YAML fallback (BA-016)

internal/handler/
├── user.go                     # 8 user management endpoints (BA-014)
├── auth.go                     # 3 auth endpoints (BA-014)
├── project_member.go           # 4 member endpoints (BA-015)
├── apikey.go                   # 6 API key management endpoints (BA-016)
├── activity.go                 # 2 activity feed endpoints (BA-016)
├── settings.go                 # 4 settings endpoints (BA-016)
```

Modified files:
```
cmd/kg-server/main.go           # Wire all new handlers + middleware
internal/middleware/auth.go      # Login path exemption + user context injection
internal/middleware/project.go   # Membership check + archive block (already exists, needs wiring)
internal/handler/project.go      # Extend with create/update/archive/stats (BA-015)
internal/store/project.go        # Add Create/Update/Archive/Stats methods (BA-015)
internal/store/audit.go          # Add GetActivityFeed + GetActivityStats (BA-016)
```

---

## Total Scope

| Metric | Count |
|--------|-------|
| New endpoints | 35 |
| Modified endpoints | 2 |
| New migrations | 4 (032-035) |
| New tables | 3 (users, project_members, system_settings) |
| New model files | 3 |
| New store files | 3 |
| New service files | 4 |
| New handler files | 6 |
| Modified files | 6 |
| Business rules | 37 |

---

## Key Conventions (Inherited)

- **3-layer**: Handler → Service → Store (no shortcuts)
- **Standard library HTTP**: `net/http`, `http.ServeMux`
- **Pure SQL stores**: `database/sql` with `$1` params
- **Error mapping**: validation → 400, not found → 404, conflict → 409, forbidden → 403, auth → 401
- **Response format**: Direct struct or `{"items": [...], "total_count": N}` for paginated lists
- **bcrypt cost**: 12 (matches existing APIKey pattern)
- **Logging**: `log/slog` with structured key-value pairs
- **Composition root**: All handlers wired in `buildRouter()` in `cmd/kg-server/main.go`
