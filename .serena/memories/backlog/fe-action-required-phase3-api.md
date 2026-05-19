# FE Action Required: Phase 3 API Endpoints — User Accounts, Projects, Admin

**Date**: 2026-04-13
**Status**: BE branches ready to merge, endpoints documented below

---

## M1: User Management (8 endpoints)

### POST /api/v1/users — Create user (admin only)
```json
Request: {"username": "danny", "display_name": "Danny", "email": "danny@example.com", "role": "developer"}
Response 201: {"user": {id, username, display_name, email, role, status: "pending_password_change", created_at}, "temporary_password": "aB3$xK9mPq2!wZ7n"}
```

### GET /api/v1/users — List all users (admin only)
Response 200: bare array `User[]`

### GET /api/v1/users/me — Current user profile (any auth)
Response 200: `User` object

### GET /api/v1/users/{id} — Get user (admin or self)
Response 200: `User` object

### PATCH /api/v1/users/{id} — Update user (admin only)
```json
Request: {"display_name": "New Name", "email": "new@example.com", "role": "admin"}
```

### POST /api/v1/users/{id}/disable — Disable account (admin only)
Revokes internal API key. Response 200.

### POST /api/v1/users/{id}/enable — Re-enable account (admin only)
Generates new API key. Response 200.

### POST /api/v1/users/{id}/unlock — Unlock locked account (admin only)
Response 200.

### POST /api/v1/users/{id}/reset-password — Generate temp password (admin only)
Response 200: `{"temporary_password": "..."}`

---

## M2: Authentication (3 endpoints)

### POST /api/v1/auth/login — Login (PUBLIC, no auth required)
```json
Request: {"username": "danny", "password": "MyP@ss1"}
Response 200: {
  "user": {id, username, display_name, email, role, status},
  "api_key": "ennam_kg_...",
  "requires_password_change": false
}
```
Errors: 401 invalid credentials, 403 disabled/locked

> **FE flow**: POST to BFF `/api/kg/auth/login` → BFF forwards to Go API → stores `api_key` in iron-session cookie → redirect to dashboard

### POST /api/v1/auth/change-password — Change password (authenticated)
```json
Request: {"old_password": "old", "new_password": "NewP@ss1"}
Response 200: {"message": "Password changed successfully"}
```

### POST /api/v1/auth/logout — Logout (authenticated)
Response 200: `{"message": "Logged out successfully"}`
FE clears iron-session cookie.

---

## M3: Project Management (7 endpoints)

### POST /api/v1/projects — Create project (admin only)
```json
Request: {"name": "C4K Platform", "description": "...", "repo_url": "https://..."}
Response 201: Project object (creator auto-added as project admin)
```

### GET /api/v1/projects — List projects (membership-filtered)
Admin sees all. Others see only their projects. Supports `?include_archived=true`.
Response 200: bare array `Project[]`

### GET /api/v1/projects/{id} — Get project (member or admin)
Response 200: `Project` with `archived_at`, `archived_by` fields

### PUT /api/v1/projects/{id} — Update project (project admin or global admin)
```json
Request: {"name": "New Name", "description": "...", "repo_url": "..."}
```

### POST /api/v1/projects/{id}/archive — Archive (global admin only)
### POST /api/v1/projects/{id}/unarchive — Unarchive (global admin only)

### GET /api/v1/projects/{id}/stats — Project stats (member)
```json
Response 200: {"project_id": "uuid", "node_count": 150, "edge_count": 200, "data_source_count": 3, "member_count": 5, "query_count": 45, "last_activity_at": "ISO8601"}
```

---

## M4: Project Members (4 endpoints)

### GET /api/v1/projects/{id}/members — List members (member access)
Response 200: bare array `ProjectMember[]` (includes user info)

### POST /api/v1/projects/{id}/members — Add member (project admin)
```json
Request: {"user_id": "uuid", "role": "developer"}
Response 201: ProjectMember
```

### PATCH /api/v1/projects/{id}/members/{user_id} — Change role (project admin)
```json
Request: {"role": "admin"}
```

### DELETE /api/v1/projects/{id}/members/{user_id} — Remove member (project admin)
Response 204. Cannot remove last admin (409).

---

## M5: API Key Management (6 endpoints)

### POST /api/v1/api-keys — Create key (authenticated)
```json
Request: {"label": "mcp-agent", "role": "developer", "project_ids": ["uuid1"]}
Response 201: {"id": "uuid", "key": "ennam_kg_...", "key_prefix": "ennam_kg", "label": "mcp-agent", "role": "developer", ...}
```
> `key` plaintext returned ONCE only.

### GET /api/v1/api-keys — List own keys (admin: all)
Filters out internal `web-session-*` keys. Response 200: bare array.

### GET /api/v1/api-keys/{id} — Get key detail
### PATCH /api/v1/api-keys/{id} — Update label
### POST /api/v1/api-keys/{id}/revoke — Revoke key
### DELETE /api/v1/api-keys/{id} — Permanent delete (admin only)

---

## M6: Activity Feed (2 endpoints)

### GET /api/v1/activity/feed?project_id={uuid}&limit=20&offset=0
Membership-scoped. Actor shows `display_name` (joined from users table).
```json
Response 200: {
  "items": [{"id": "uuid", "operation": "node.create", "entity_type": "node", "entity_id": "uuid", "actor": "Danny", "project_id": "uuid", "project_name": "C4K", "summary": "Created node 'public.orders'", "performed_at": "ISO8601"}],
  "total_count": 150, "limit": 20, "offset": 0
}
```

### GET /api/v1/activity/stats
```json
Response 200: {"today": {"nodes_created": 5, "queries_run": 12, "syncs_completed": 1}, "week": {...}, "month": {...}}
```

---

## M7: System Settings (4 endpoints)

### GET /api/v1/settings — List all (admin only)
```json
Response 200: {"settings": [{"key": "ai.default_provider", "value": "claude_max", "description": "...", "category": "ai", "updated_at": "ISO8601"}]}
```

### GET /api/v1/settings/public — Public settings (any auth)
Returns feature_flags + general categories only.

### GET /api/v1/settings/{key} — Single setting (admin)
### PUT /api/v1/settings/{key} — Update setting (admin)
```json
Request: {"value": "new_value", "description": "optional new description"}
```

---

## TypeScript Types

```typescript
interface User {
  id: string;
  username: string;
  email: string | null;
  display_name: string;
  role: 'admin' | 'developer' | 'viewer';
  status: 'active' | 'disabled' | 'pending_password_change' | 'locked';
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

interface LoginResponse {
  user: User;
  api_key: string;
  requires_password_change: boolean;
}

interface ProjectMember {
  id: string;
  project_id: string;
  user_id: string;
  role: 'admin' | 'developer' | 'viewer';
  added_by: string | null;
  created_at: string;
  // When joined with user:
  display_name?: string;
  username?: string;
}

interface ProjectStats {
  project_id: string;
  node_count: number;
  edge_count: number;
  data_source_count: number;
  member_count: number;
  query_count: number;
  last_activity_at: string | null;
}

interface SystemSetting {
  key: string;
  value: unknown; // JSONB — could be string, number, object
  description: string | null;
  category: 'ai' | 'sync' | 'auth' | 'feature_flags' | 'general';
  updated_by: string | null;
  updated_at: string;
}

interface ActivityFeedItem {
  id: string;
  operation: string;
  entity_type: string;
  entity_id: string;
  actor: string;
  project_id: string;
  project_name: string;
  summary: string;
  performed_at: string;
}
```

## BFF Login Integration

FE needs a new server action or API route for login:
```typescript
// src/app/api/kg/auth/login/route.ts
export async function POST(request: Request) {
  const body = await request.json();
  const res = await fetch(`${GO_API_URL}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) return NextResponse.json(await res.json(), { status: res.status });
  const data = await res.json();
  // Store api_key in iron-session
  const session = await getIronSession(cookies(), sessionOptions);
  session.apiKey = data.api_key;
  session.developerName = data.user.display_name;
  session.role = data.user.role;
  await session.save();
  return NextResponse.json({ user: data.user, requires_password_change: data.requires_password_change });
}
```
