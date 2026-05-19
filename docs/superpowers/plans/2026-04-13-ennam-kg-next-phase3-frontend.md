# Phase 3 Frontend — Users, Projects & Platform Admin

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user authentication (username/password), project membership & access control, API key management, activity feed, and system settings/feature flags to the NextJS dashboard.

**Architecture:** Sequential 3-step implementation (BA-014 → BA-015 → BA-016) because auth is a dependency for everything else. Login flow changes from "name + API key" to "username + password → Go API returns api_key → BFF stores in iron-session". All existing pages get auth guards and project membership checks. Feature flags gate optional Phase 2 features.

**Tech Stack:** Next.js 16, React 19, TypeScript strict, TanStack Query 5, iron-session 8, shadcn/ui, Tailwind CSS 4, Lucide icons

**Backend status:** Go API Phase 3 NOT STARTED. Frontend hooks use 404 graceful handling (empty defaults) so pages render with empty state until backend delivers endpoints.

---

## Important: Backend Dependency

Go API endpoints for Phase 3 (BA-014→016) are not yet implemented. This plan builds frontend types, hooks, pages, and components that will work end-to-end once backend delivers. All hooks return empty defaults on 404 — pages show appropriate empty/loading states.

**When backend is ready:** No frontend code changes needed — hooks auto-fetch real data.

---

## File Structure

### New Files to Create

```
src/types/
├── user.ts                    # User, UserRole, UserStatus, LoginRequest/Response, CreateUserRequest
├── project-member.ts          # ProjectMember, ProjectStats, AddMemberRequest
├── api-key.ts                 # ApiKey, CreateApiKeyRequest/Response
├── activity.ts                # ActivityFeedItem, ActivityStats
└── settings.ts                # SystemSetting, FeatureFlag, SettingCategory

src/hooks/
├── use-auth.ts                # useLogin, useLogout, useChangePassword, useCurrentUser
├── use-users.ts               # useUsers, useCreateUser, useDisableUser, useUnlockUser
├── use-project-members.ts     # useMembers, useAddMember, useChangeMemberRole, useRemoveMember
├── use-api-keys.ts            # useApiKeys, useCreateApiKey, useRevokeKey
├── use-activity.ts            # useActivityFeed, useActivityStats
└── use-settings.ts            # useSettings, usePublicSettings, useUpdateSetting

src/lib/
├── auth/session.ts            # MODIFY — new SessionData shape with user info
└── context/feature-flags.tsx   # NEW — FeatureFlagProvider + useFeatureFlag hook

src/app/
├── (auth)/login/
│   ├── page.tsx               # REWRITE — username/password login
│   └── actions.ts             # REWRITE — POST to Go /auth/login, store api_key
├── (auth)/change-password/
│   └── page.tsx               # NEW — mandatory password change
├── (dashboard)/
│   ├── layout.tsx             # MODIFY — auth guard + password change redirect
│   ├── page.tsx               # MODIFY — add activity widget
│   ├── admin/users/page.tsx   # NEW — user management (admin only)
│   ├── projects/
│   │   ├── page.tsx           # NEW — project list
│   │   └── [id]/
│   │       ├── page.tsx       # NEW — project detail + settings
│   │       └── members/page.tsx # NEW — member management
│   ├── settings/api-keys/page.tsx # REWRITE — API key management
│   ├── activity/page.tsx      # NEW — activity feed
│   └── admin/settings/page.tsx # NEW — system settings + feature flags

src/components/
├── auth/PasswordStrength.tsx  # Password validation indicator
├── users/UserTable.tsx        # Admin user list table
├── users/CreateUserDialog.tsx # Create user form + temp password display
├── projects/ProjectCard.tsx   # Project list card
├── projects/MemberTable.tsx   # Member management table
├── projects/AddMemberDialog.tsx # Add member form
├── api-keys/KeyTable.tsx      # API key list table
├── api-keys/CreateKeyDialog.tsx # Create key + one-time display
├── activity/ActivityFeed.tsx  # Feed item list component
├── activity/ActivityStats.tsx # Stats cards component
├── settings/SettingsPanel.tsx # Settings editor with categories
└── layout/UserMenu.tsx        # Header user menu dropdown
```

### Files to Modify

```
src/lib/auth/session.ts         # SessionData shape: add userId, username, displayName, role
src/app/(auth)/login/page.tsx   # Rewrite: username + password
src/app/(auth)/login/actions.ts # Rewrite: POST /auth/login, store api_key + user info
src/app/(dashboard)/layout.tsx  # Auth guard: check session, redirect to change-password if needed
src/app/(dashboard)/page.tsx    # Add activity widget
src/components/layout/Sidebar.tsx # Admin-only links, projects section
src/components/layout/Header.tsx  # User menu dropdown
src/components/layout/DashboardShell.tsx # Pass user info
src/components/layout/ProjectSwitcher.tsx # Membership-filtered
```

---

## Step 1: BA-014 — User Accounts & Authentication

### Task 1: User TypeScript Types

**Files:**
- Create: `ennam.kg.next/src/types/user.ts`

- [ ] **Step 1: Create user types**

```typescript
// src/types/user.ts

export type UserRole = 'admin' | 'developer' | 'viewer';
export type UserStatus = 'active' | 'pending_password_change' | 'disabled' | 'locked';

export interface User {
  id: string;
  username: string;
  display_name: string;
  email?: string;
  role: UserRole;
  status: UserStatus;
  last_login_at?: string;
  created_at: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  user: User;
  api_key: string;
  requires_password_change: boolean;
}

export interface ChangePasswordRequest {
  old_password: string;
  new_password: string;
}

export interface CreateUserRequest {
  username: string;
  display_name: string;
  email?: string;
  role: UserRole;
}

export interface CreateUserResponse {
  user: User;
  temporary_password: string;
}

export interface UserListResponse {
  users: User[];
  total_count: number;
}
```

- [ ] **Step 2: Verify and commit**

Run: `cd ennam.kg.next && npx tsc --noEmit`
```bash
git add src/types/user.ts && git commit -m "feat(types): add user and auth types for BA-014"
```

---

### Task 2: Update Session Shape

**Files:**
- Modify: `ennam.kg.next/src/lib/auth/session.ts`

- [ ] **Step 1: Update SessionData interface**

```typescript
// src/lib/auth/session.ts
import { getIronSession, type SessionOptions } from 'iron-session';
import { cookies } from 'next/headers';

export interface SessionData {
  apiKey?: string;
  userId?: string;
  username?: string;
  displayName?: string;
  role?: string;
  projectIds?: string[];
  isLoggedIn: boolean;
  requiresPasswordChange?: boolean;
}

const defaultSession: SessionData = {
  isLoggedIn: false,
};

const sessionOptions: SessionOptions = {
  password: process.env.SESSION_SECRET || 'complex_password_at_least_32_characters_long_for_dev',
  cookieName: 'ennam-kg-session',
  cookieOptions: {
    secure: process.env.NODE_ENV === 'production',
    httpOnly: true,
    sameSite: 'lax',
    maxAge: 60 * 60 * 24 * 15, // 15 days hard timeout
  },
};

export async function getSession() {
  const cookieStore = await cookies();
  const session = await getIronSession<SessionData>(cookieStore, sessionOptions);
  if (!session.isLoggedIn) {
    session.isLoggedIn = defaultSession.isLoggedIn;
  }
  return session;
}
```

- [ ] **Step 2: Verify and commit**

```bash
cd ennam.kg.next && npx tsc --noEmit
git add src/lib/auth/session.ts && git commit -m "feat(auth): update session shape with user info and 15-day timeout"
```

---

### Task 3: Rewrite Login Page + Server Action

**Files:**
- Rewrite: `ennam.kg.next/src/app/(auth)/login/actions.ts`
- Rewrite: `ennam.kg.next/src/app/(auth)/login/page.tsx`

- [ ] **Step 1: Rewrite login server action**

```typescript
// src/app/(auth)/login/actions.ts
'use server';
import { getSession } from '@/lib/auth/session';
import { redirect } from 'next/navigation';

export interface LoginState {
  error?: string;
}

export async function loginAction(_prevState: LoginState, formData: FormData): Promise<LoginState> {
  const username = formData.get('username') as string;
  const password = formData.get('password') as string;

  if (!username || !password) {
    return { error: 'Username and password are required' };
  }

  const goApiUrl = process.env.GO_API_URL || 'http://localhost:8080';
  try {
    const res = await fetch(`${goApiUrl}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });

    if (res.status === 401) {
      return { error: 'Invalid username or password' };
    }
    if (res.status === 403) {
      const data = await res.json().catch(() => ({}));
      if (data.error?.includes('locked')) return { error: 'Account locked. Contact admin.' };
      if (data.error?.includes('disabled')) return { error: 'Account disabled. Contact admin.' };
      return { error: 'Access denied' };
    }
    if (!res.ok) {
      return { error: 'Login failed. Please try again.' };
    }

    const data = await res.json();
    const session = await getSession();
    session.apiKey = data.api_key;
    session.userId = data.user.id;
    session.username = data.user.username;
    session.displayName = data.user.display_name;
    session.role = data.user.role;
    session.isLoggedIn = true;
    session.requiresPasswordChange = data.requires_password_change;
    await session.save();

    if (data.requires_password_change) {
      redirect('/change-password');
    }
  } catch (err) {
    if (err instanceof Error && err.message === 'NEXT_REDIRECT') throw err;
    return { error: 'Cannot reach API server' };
  }

  redirect('/');
}
```

- [ ] **Step 2: Rewrite login page UI**

```typescript
// src/app/(auth)/login/page.tsx
'use client';

import { useActionState } from 'react';
import { loginAction, type LoginState } from './actions';
import { Loader2 } from 'lucide-react';

const initialState: LoginState = {};

export default function LoginPage() {
  const [state, formAction, pending] = useActionState(loginAction, initialState);

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="w-full max-w-md">
        <div className="glass-strong rounded-2xl shadow-lg border border-border p-8">
          <div className="text-center mb-8">
            <h1 className="text-2xl font-heading font-bold text-foreground text-glow">
              Ennam Knowledge Graph
            </h1>
            <div className="neon-line my-4" />
            <p className="text-sm text-muted-foreground mt-2">
              Sign in to access the dashboard
            </p>
          </div>

          {state.error && (
            <div className="mb-4 p-3 rounded-lg bg-destructive/10 border border-destructive/30 text-destructive text-sm">
              {state.error}
            </div>
          )}

          <form action={formAction} className="space-y-5">
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-foreground mb-1.5">
                Username
              </label>
              <input
                id="username"
                name="username"
                type="text"
                required
                autoComplete="username"
                placeholder="e.g. admin"
                className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-foreground mb-1.5">
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                required
                autoComplete="current-password"
                placeholder="Enter your password"
                className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent text-sm"
              />
            </div>

            <button
              type="submit"
              disabled={pending}
              className="w-full py-2.5 px-4 rounded-lg bg-[#00D4FF] hover:bg-[#00D4FF]/90 disabled:opacity-50 disabled:cursor-not-allowed text-[#0D0F1A] font-semibold text-sm transition-colors shadow-[0_0_20px_rgba(0,212,255,0.3)]"
            >
              {pending ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Signing in...
                </span>
              ) : (
                'Sign In'
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify and commit**

```bash
cd ennam.kg.next && npx tsc --noEmit
git add src/app/\(auth\)/login/actions.ts src/app/\(auth\)/login/page.tsx
git commit -m "feat(auth): rewrite login to username/password via Go API /auth/login"
```

---

### Task 4: Change Password Page

**Files:**
- Create: `ennam.kg.next/src/app/(auth)/change-password/page.tsx`
- Create: `ennam.kg.next/src/components/auth/PasswordStrength.tsx`

- [ ] **Step 1: Create password strength indicator**

```typescript
// src/components/auth/PasswordStrength.tsx
'use client';

const RULES = [
  { label: 'At least 8 characters', test: (p: string) => p.length >= 8 },
  { label: 'Uppercase letter', test: (p: string) => /[A-Z]/.test(p) },
  { label: 'Number', test: (p: string) => /[0-9]/.test(p) },
  { label: 'Special character', test: (p: string) => /[!@#$%^&*()_+\-=[\]{};'\\|:"<>,.?/~`]/.test(p) },
];

export function validatePassword(password: string): { valid: boolean; failures: string[] } {
  const failures = RULES.filter((r) => !r.test(password)).map((r) => r.label);
  return { valid: failures.length === 0, failures };
}

export default function PasswordStrength({ password }: { password: string }) {
  if (!password) return null;
  return (
    <div className="flex flex-col gap-1 mt-2">
      {RULES.map((rule) => {
        const passed = rule.test(password);
        return (
          <div key={rule.label} className="flex items-center gap-2 text-xs">
            <span className={`h-1.5 w-1.5 rounded-full ${passed ? 'bg-[#00FF94]' : 'bg-[#FF4757]'}`} />
            <span className={passed ? 'text-[#00FF94]' : 'text-[#5C6080]'}>{rule.label}</span>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Create change password page**

Create `src/app/(auth)/change-password/page.tsx` — a client component with:
- Current Password, New Password, Confirm New Password fields
- PasswordStrength indicator under new password
- Client-side validation before submit
- POST to `/api/kg/auth/change-password` via server action
- Info banner when `requiresPasswordChange` is true
- Redirect to `/` on success

- [ ] **Step 3: Verify and commit**

```bash
cd ennam.kg.next && npx tsc --noEmit
git add src/components/auth/PasswordStrength.tsx src/app/\(auth\)/change-password/
git commit -m "feat(auth): add change password page with strength validation"
```

---

### Task 5: Auth Hooks

**Files:**
- Create: `ennam.kg.next/src/hooks/use-auth.ts`

- [ ] **Step 1: Create auth hooks**

Hooks to create:
1. `useCurrentUser()` — GET `/api/kg/users/me`, returns `User | null`, 404 → null
2. `useLogout()` — mutation POST `/api/kg/auth/logout`, on success invalidate all queries + redirect

Follow existing hook patterns in `src/hooks/use-data-sources.ts`. Add `retry: false` for 404 handling.

- [ ] **Step 2: Verify and commit**

```bash
git add src/hooks/use-auth.ts && git commit -m "feat(auth): add useCurrentUser and useLogout hooks"
```

---

### Task 6: User Management Hooks

**Files:**
- Create: `ennam.kg.next/src/hooks/use-users.ts`

- [ ] **Step 1: Create user management hooks**

Hooks:
1. `useUsers()` — GET `/api/kg/users` → bare array, 404 → []
2. `useCreateUser()` — mutation POST `/api/kg/users`
3. `useDisableUser()` — mutation POST `/api/kg/users/{id}/disable`
4. `useEnableUser()` — mutation POST `/api/kg/users/{id}/enable`
5. `useUnlockUser()` — mutation POST `/api/kg/users/{id}/unlock`
6. `useResetPassword()` — mutation POST `/api/kg/users/{id}/reset-password`

All with `retry: false`, 404 graceful handling.

- [ ] **Step 2: Verify and commit**

```bash
git add src/hooks/use-users.ts && git commit -m "feat(users): add user management hooks for BA-014"
```

---

### Task 7: Dashboard Layout Auth Guard + Header User Menu

**Files:**
- Modify: `ennam.kg.next/src/app/(dashboard)/layout.tsx`
- Create: `ennam.kg.next/src/components/layout/UserMenu.tsx`
- Modify: `ennam.kg.next/src/components/layout/Header.tsx`
- Modify: `ennam.kg.next/src/components/layout/DashboardShell.tsx`

- [ ] **Step 1: Update dashboard layout**

Add `requiresPasswordChange` check — redirect to `/change-password` if true.
Pass `session.displayName`, `session.role`, `session.username` to DashboardShell.

- [ ] **Step 2: Create UserMenu component**

Dropdown in header: user avatar/initial, display name, role badge, "Log Out" action.

- [ ] **Step 3: Wire into Header**

Replace hardcoded avatar in Header with `<UserMenu />` component.

- [ ] **Step 4: Verify and commit**

```bash
cd ennam.kg.next && npx tsc --noEmit
git add src/app/\(dashboard\)/layout.tsx src/components/layout/UserMenu.tsx src/components/layout/Header.tsx src/components/layout/DashboardShell.tsx
git commit -m "feat(auth): dashboard auth guard, password change redirect, user menu"
```

---

### Task 8: Admin User Management Page

**Files:**
- Create: `ennam.kg.next/src/app/(dashboard)/admin/users/page.tsx`
- Create: `ennam.kg.next/src/components/users/UserTable.tsx`
- Create: `ennam.kg.next/src/components/users/CreateUserDialog.tsx`

- [ ] **Step 1: Create UserTable component**

Table columns: Username, Display Name, Email, Role (badge), Status (badge), Last Login, Actions.
Actions: Edit, Disable/Enable, Unlock (if locked), Reset Password.

- [ ] **Step 2: Create CreateUserDialog**

Dialog with: username, display_name, email, role selector.
On success: show temporary password in one-time display with copy button.

- [ ] **Step 3: Create admin users page**

Page at `/admin/users`. Uses `useUsers()` hook. Shows UserTable + "New User" button.
Admin-only access — check `session.role === 'admin'` or show 403.

- [ ] **Step 4: Update Sidebar**

Add "Users" link under ADMIN section, visible only to admin role.

- [ ] **Step 5: Verify and commit**

```bash
cd ennam.kg.next && npx tsc --noEmit
git add src/app/\(dashboard\)/admin/users/page.tsx src/components/users/ src/components/layout/Sidebar.tsx
git commit -m "feat(users): add admin user management page with CRUD"
```

---

## Step 2: BA-015 — Project Management & Access Control

### Task 9: Project Member Types

**Files:**
- Create: `ennam.kg.next/src/types/project-member.ts`
- Modify: `ennam.kg.next/src/types/project.ts`

- [ ] **Step 1: Create project member types + update Project type**

Add `ProjectMember`, `ProjectStats`, `AddMemberRequest`, `ChangeMemberRoleRequest`.
Update `Project` interface: add `status: 'active' | 'archived'`, `archived_at`, `archived_by`.

- [ ] **Step 2: Verify and commit**

```bash
git add src/types/project-member.ts src/types/project.ts
git commit -m "feat(types): add project member and stats types for BA-015"
```

---

### Task 10: Project Member Hooks

**Files:**
- Create: `ennam.kg.next/src/hooks/use-project-members.ts`

- [ ] **Step 1: Create member hooks**

1. `useProjectMembers(projectId)` — GET `/api/kg/projects/{id}/members`
2. `useProjectStats(projectId)` — GET `/api/kg/projects/{id}/stats`
3. `useAddMember()` — mutation POST `/api/kg/projects/{id}/members`
4. `useChangeMemberRole()` — mutation PATCH `/api/kg/projects/{id}/members/{userId}`
5. `useRemoveMember()` — mutation DELETE `/api/kg/projects/{id}/members/{userId}`
6. `useArchiveProject()` — mutation POST `/api/kg/projects/{id}/archive`
7. `useUnarchiveProject()` — mutation POST `/api/kg/projects/{id}/unarchive`

- [ ] **Step 2: Verify and commit**

```bash
git add src/hooks/use-project-members.ts && git commit -m "feat(projects): add project member and stats hooks for BA-015"
```

---

### Task 11: Project List Page

**Files:**
- Create: `ennam.kg.next/src/app/(dashboard)/projects/page.tsx`
- Create: `ennam.kg.next/src/components/projects/ProjectCard.tsx`

- [ ] **Step 1: Create ProjectCard component**

Card showing: project name, description, member count, status badge (active/archived).
Click → navigate to `/projects/[id]`.

- [ ] **Step 2: Create projects list page**

Uses `useProjects()` (existing hook, already membership-filtered by API).
Grid of ProjectCard components. "Create Project" button (admin only).
Checkbox: "Include archived projects".

- [ ] **Step 3: Verify and commit**

```bash
git add src/app/\(dashboard\)/projects/page.tsx src/components/projects/ProjectCard.tsx
git commit -m "feat(projects): add project list page with cards"
```

---

### Task 12: Project Detail + Members Pages

**Files:**
- Create: `ennam.kg.next/src/app/(dashboard)/projects/[id]/page.tsx`
- Create: `ennam.kg.next/src/app/(dashboard)/projects/[id]/members/page.tsx`
- Create: `ennam.kg.next/src/components/projects/MemberTable.tsx`
- Create: `ennam.kg.next/src/components/projects/AddMemberDialog.tsx`

- [ ] **Step 1: Create project detail page**

Shows: project info, stats cards (nodes, edges, data sources, queries, members), edit button (admin), archive button (global admin).

- [ ] **Step 2: Create MemberTable component**

Table: Username, Display Name, Role (editable dropdown for admins), Added Date, Actions (remove).

- [ ] **Step 3: Create AddMemberDialog**

User search/select + role picker. POST to add member.

- [ ] **Step 4: Create members page**

Page at `/projects/[id]/members`. Uses `useProjectMembers(id)`.

- [ ] **Step 5: Update Sidebar and ProjectSwitcher**

Add "Projects" link in sidebar. Update ProjectSwitcher to use membership-filtered list.

- [ ] **Step 6: Verify and commit**

```bash
cd ennam.kg.next && npx tsc --noEmit
git add src/app/\(dashboard\)/projects/ src/components/projects/ src/components/layout/Sidebar.tsx src/components/layout/ProjectSwitcher.tsx
git commit -m "feat(projects): add project detail, members pages, and membership-filtered switcher"
```

---

## Step 3: BA-016 — Platform Administration

### Task 13: Admin Types

**Files:**
- Create: `ennam.kg.next/src/types/api-key.ts`
- Create: `ennam.kg.next/src/types/activity.ts`
- Create: `ennam.kg.next/src/types/settings.ts`

- [ ] **Step 1: Create all admin types**

ApiKey, CreateApiKeyRequest/Response, ActivityFeedItem, ActivityStats, SystemSetting, FeatureFlag, SettingCategory.

- [ ] **Step 2: Verify and commit**

```bash
git add src/types/api-key.ts src/types/activity.ts src/types/settings.ts
git commit -m "feat(types): add api-key, activity, settings types for BA-016"
```

---

### Task 14: Admin Hooks

**Files:**
- Create: `ennam.kg.next/src/hooks/use-api-keys.ts`
- Create: `ennam.kg.next/src/hooks/use-activity.ts`
- Create: `ennam.kg.next/src/hooks/use-settings.ts`

- [ ] **Step 1: Create API key hooks**

1. `useApiKeys()` — GET `/api/kg/api-keys`, 404 → []
2. `useCreateApiKey()` — mutation POST `/api/kg/api-keys`
3. `useRevokeApiKey()` — mutation POST `/api/kg/api-keys/{id}/revoke`

- [ ] **Step 2: Create activity hooks**

1. `useActivityFeed(projectId?)` — GET `/api/kg/activity/feed?project_id=`
2. `useActivityStats(period)` — GET `/api/kg/activity/stats?period=`

- [ ] **Step 3: Create settings hooks**

1. `useSettings()` — GET `/api/kg/settings` (admin only)
2. `usePublicSettings()` — GET `/api/kg/settings/public` (all authenticated)
3. `useUpdateSetting()` — mutation PUT `/api/kg/settings/{key}`

- [ ] **Step 4: Verify and commit**

```bash
git add src/hooks/use-api-keys.ts src/hooks/use-activity.ts src/hooks/use-settings.ts
git commit -m "feat(hooks): add api-keys, activity, settings hooks for BA-016"
```

---

### Task 15: Feature Flag Provider

**Files:**
- Create: `ennam.kg.next/src/lib/context/feature-flags.tsx`
- Modify: `ennam.kg.next/src/app/layout.tsx` (wrap with provider)

- [ ] **Step 1: Create FeatureFlagProvider + useFeatureFlag**

```typescript
// src/lib/context/feature-flags.tsx
'use client';

import { createContext, useContext } from 'react';
import { usePublicSettings } from '@/hooks/use-settings';

interface FeatureFlagContextValue {
  isEnabled: (flagName: string) => boolean;
  isLoading: boolean;
}

const FeatureFlagContext = createContext<FeatureFlagContextValue>({
  isEnabled: () => true, // default: all features enabled
  isLoading: true,
});

export function FeatureFlagProvider({ children }: { children: React.ReactNode }) {
  const { data: settings, isLoading } = usePublicSettings();

  const isEnabled = (flagName: string): boolean => {
    if (!settings || !Array.isArray(settings)) return true; // default enabled while loading
    const flag = settings.find((s: { key: string }) => s.key === `feature.${flagName}`);
    if (!flag) return true; // feature not flagged = enabled
    const value = flag.value;
    if (typeof value === 'object' && value !== null && 'enabled' in value) {
      return (value as { enabled: boolean }).enabled;
    }
    return true;
  };

  return (
    <FeatureFlagContext.Provider value={{ isEnabled, isLoading }}>
      {children}
    </FeatureFlagContext.Provider>
  );
}

export function useFeatureFlag(flagName: string): boolean {
  const { isEnabled } = useContext(FeatureFlagContext);
  return isEnabled(flagName);
}
```

- [ ] **Step 2: Wrap app with FeatureFlagProvider**

Add `<FeatureFlagProvider>` inside root layout (after QueryProvider).

- [ ] **Step 3: Verify and commit**

```bash
git add src/lib/context/feature-flags.tsx src/app/layout.tsx
git commit -m "feat(settings): add feature flag provider and useFeatureFlag hook"
```

---

### Task 16: API Key Management Page

**Files:**
- Rewrite: `ennam.kg.next/src/app/(dashboard)/settings/api-keys/page.tsx`
- Create: `ennam.kg.next/src/components/api-keys/KeyTable.tsx`
- Create: `ennam.kg.next/src/components/api-keys/CreateKeyDialog.tsx`

- [ ] **Step 1: Create KeyTable**

Table: Key prefix (masked), Label, Role badge, Projects, Created, Status badge, Actions (Revoke).

- [ ] **Step 2: Create CreateKeyDialog**

Form: Label, Role selector, Project multi-select. On success: show one-time plaintext key with copy button + warning "This key will not be shown again".

- [ ] **Step 3: Rewrite API keys page**

Full page with KeyTable + "Create Key" button.

- [ ] **Step 4: Verify and commit**

```bash
cd ennam.kg.next && npx tsc --noEmit
git add src/app/\(dashboard\)/settings/api-keys/page.tsx src/components/api-keys/
git commit -m "feat(api-keys): add API key management page with create/revoke"
```

---

### Task 17: Activity Feed Page

**Files:**
- Create: `ennam.kg.next/src/app/(dashboard)/activity/page.tsx`
- Create: `ennam.kg.next/src/components/activity/ActivityFeed.tsx`
- Create: `ennam.kg.next/src/components/activity/ActivityStats.tsx`

- [ ] **Step 1: Create ActivityFeed component**

Feed list: each item shows actor avatar/initial, summary text, project badge, relative timestamp.
Project filter dropdown. Empty state. Pagination (load more).

- [ ] **Step 2: Create ActivityStats component**

3 stat cards for Today/7d/30d: Nodes Created, Queries, Syncs, Active Users.

- [ ] **Step 3: Create activity page**

Page with stats cards at top + feed below.

- [ ] **Step 4: Add activity widget to dashboard home**

Small activity feed (5 items) on the dashboard overview page.

- [ ] **Step 5: Verify and commit**

```bash
cd ennam.kg.next && npx tsc --noEmit
git add src/app/\(dashboard\)/activity/page.tsx src/components/activity/ src/app/\(dashboard\)/page.tsx
git commit -m "feat(activity): add activity feed page with stats and dashboard widget"
```

---

### Task 18: Admin Settings Page

**Files:**
- Create: `ennam.kg.next/src/app/(dashboard)/admin/settings/page.tsx`
- Create: `ennam.kg.next/src/components/settings/SettingsPanel.tsx`

- [ ] **Step 1: Create SettingsPanel component**

Category tabs: AI, Sync, Auth, Feature Flags, General.
Each setting row: key name, current value (editable), description, last updated by/at.
Feature flags: toggle switches.
Save: PUT to `/api/kg/settings/{key}` + toast notification.

- [ ] **Step 2: Create admin settings page**

Admin-only page. Uses `useSettings()` hook. Shows SettingsPanel.

- [ ] **Step 3: Update Sidebar**

Add links: "Activity" (all users), "API Keys" (all users), "Admin Settings" (admin only).

- [ ] **Step 4: Verify and commit**

```bash
cd ennam.kg.next && npx tsc --noEmit
git add src/app/\(dashboard\)/admin/settings/page.tsx src/components/settings/ src/components/layout/Sidebar.tsx
git commit -m "feat(settings): add admin settings page with category tabs and feature flags"
```

---

### Task 19: Final Build Verification

- [ ] **Step 1: TypeScript check**

```bash
cd ennam.kg.next && npx tsc --noEmit
```
Expected: 0 errors.

- [ ] **Step 2: Lint**

```bash
cd ennam.kg.next && npm run lint
```

- [ ] **Step 3: Build**

```bash
cd ennam.kg.next && npm run build
```
Verify all new routes appear in build output.

- [ ] **Step 4: Update CLAUDE.md**

Add Phase 3 routes, auth flow documentation, feature flag usage to CLAUDE.md.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md && git commit -m "docs: update CLAUDE.md with Phase 3 auth flow, routes, and feature flags"
```

---

## Task Count Summary

| Step | BA | Tasks | New Files | Modified Files |
|------|-----|-------|-----------|----------------|
| Step 1 | BA-014 Auth | 8 | 8 | 5 |
| Step 2 | BA-015 Projects | 4 | 8 | 2 |
| Step 3 | BA-016 Admin | 6 | 10 | 3 |
| Final | — | 1 | 0 | 1 |
| **Total** | | **19** | **26** | **11** |
