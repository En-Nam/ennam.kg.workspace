# GitHub Integration — Design Spec

**Date**: 2026-06-04
**Status**: Approved
**Goal**: Allow users to connect their GitHub account, select repos per project, and have them automatically cloned, indexed, and kept in sync via push webhooks.

---

## Context

Ennam KG Phase 1 indexes code via local filesystem paths (Docker volume mounts). This approach only works for Ennam's own repos on the same server. For the platform to be useful to external users, they must be able to index their own repositories. GitHub OAuth + repo selection (similar to how Vercel/Netlify/OpenAI Codex work) is the right solution.

---

## Scope

- GitHub only (not GitLab or Bitbucket)
- Default branch only (`main`/`master`)
- Public and private repos
- One GitHub account per user, connected once at account level
- One project can have multiple repos (multi-repo / monorepo support)
- Trigger: both manual "Sync Now" and automatic GitHub push webhook

---

## Data Model

No new tables needed. Reuses existing Phase 5/6 infrastructure.

### `oauth_tokens` (existing — BA-021)

Add GitHub as a new provider:

| Field          | Value                                                 |
| -------------- | ----------------------------------------------------- |
| `provider`     | `'github'`                                            |
| `access_token` | Encrypted GitHub personal access token or OAuth token |
| `scope`        | `'repo,admin:repo_hook'`                              |
| `user_id`      | FK to `users.id`                                      |

### `source_connections` (existing — BA-022)

One row per selected repo per project:

| Field            | Value                                                                                                                                                       |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `project_id`     | FK to `projects.id`                                                                                                                                         |
| `source_type`    | `'github_repo'`                                                                                                                                             |
| `config`         | JSONB: `{"owner": "exnodes", "repo": "ennam-kg-go", "full_name": "exnodes/ennam-kg-go", "default_branch": "main", "private": true, "webhook_id": 12345678}` |
| `webhook_secret` | Random secret for HMAC verification of push events                                                                                                          |
| `oauth_token_id` | FK to `oauth_tokens.id`                                                                                                                                     |
| `status`         | `'active'` \| `'error'` \| `'syncing'`                                                                                                                      |

### `projects.repo_paths` (existing)

Not used for GitHub-connected repos. Path is ephemeral (temp clone dir passed via queue message only, never persisted).

---

## Go API

### GitHub OAuth

| Method   | Path                           | Description                                                  |
| -------- | ------------------------------ | ------------------------------------------------------------ |
| `GET`    | `/api/v1/auth/github`          | Redirect to GitHub OAuth authorization URL                   |
| `GET`    | `/api/v1/auth/github/callback` | Exchange code for token, encrypt and store in `oauth_tokens` |
| `DELETE` | `/api/v1/auth/github`          | Disconnect: delete token, delete all webhooks from GitHub    |

OAuth app scopes required: `repo` (read private repos, clone), `admin:repo_hook` (create/delete webhooks).

### Repo Listing

| Method | Path                   | Description                                                                                                                                     |
| ------ | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET`  | `/api/v1/github/repos` | List all repos accessible via user's GitHub token (calls GitHub API). Returns: `name`, `full_name`, `private`, `description`, `default_branch`. |

### Repo Selection per Project

| Method   | Path                                             | Description                                                                                                                          |
| -------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| `POST`   | `/api/v1/projects/{id}/github-sources`           | Add a repo: create `source_connections` row, register webhook on GitHub, publish `index_project` to queue for immediate first index. |
| `DELETE` | `/api/v1/projects/{id}/github-sources/{conn_id}` | Remove a repo: delete `source_connections` row, delete webhook from GitHub.                                                          |
| `GET`    | `/api/v1/projects/{id}/github-sources`           | List all GitHub-connected repos for a project with status and last_synced_at.                                                        |

### Webhook Receiver

| Method | Path               | Description                                                                                                                                                            |
| ------ | ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST` | `/webhooks/github` | Receive GitHub push events. Verify HMAC-SHA256 signature using `webhook_secret`. Lookup `source_connections` by repo full_name. Publish `index_project` queue message. |

Webhook endpoint is unauthenticated (no API key) but secured by HMAC signature verification.

### Manual Sync

Reuses existing endpoint — no changes needed:

```
POST /api/v1/projects/{id}/index
Body: {} (empty — falls back to project's stored repo_paths, or triggers all github-sources)
```

---

## Python Worker — Clone Pipeline

### Updated `IndexMessage`

Two new optional fields added to the queue message:

```python
@dataclass
class IndexMessage:
    type: str            # 'index_project' | 'index_changed'
    project_id: str
    repo_path: str       # existing — local path (Docker mount or empty)
    repo_url: str = ''   # NEW — GitHub clone URL
    github_token: str = ''  # NEW — decrypted token for private repos
    files: list[str] = field(default_factory=list)
```

### Worker Dispatch Logic

```python
if message.repo_url:
    with GitCloner(message.repo_url, message.github_token) as repo_path:
        await engine.full_scan(message.project_id, repo_path)
else:
    # backward compatible — existing Docker mount path
    await engine.full_scan(message.project_id, message.repo_path)
```

### `GitCloner` — Context Manager

```python
class GitCloner:
    """Clone a GitHub repo to a temp dir, auto-cleanup on exit."""

    def __init__(self, repo_url: str, token: str):
        # Build authenticated URL:
        # https://x-token:{token}@github.com/owner/repo.git
        self.clone_url = repo_url.replace(
            'https://', f'https://x-token:{token}@'
        )
        self.tmp_dir: str | None = None

    def __enter__(self) -> str:
        self.tmp_dir = tempfile.mkdtemp(prefix='ennam-kg-clone-')
        subprocess.run(
            ['git', 'clone', '--depth=1', '--single-branch',
             self.clone_url, self.tmp_dir],
            check=True, capture_output=True
        )
        return self.tmp_dir

    def __exit__(self, *args):
        if self.tmp_dir:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
```

Token is NOT logged anywhere. `capture_output=True` prevents clone URL (which contains token) from appearing in logs.

---

## NextJS UI

### Account Settings Page (new) — `/settings/account`

- **Not connected state**: "Connect GitHub Account" button → triggers OAuth redirect
- **Connected state**: shows GitHub username, repo count, "Disconnect" button

> **PAT fallback (Phase 1 / self-hosted):** When connecting via a manually-pasted Personal Access Token instead of OAuth, the input caption MUST instruct the user to create the token with scope `repo, admin:repo_hook` — not `repo` alone. The `admin:repo_hook` scope is required for automatic push-webhook registration; without it, repos can be cloned and indexed but auto-sync on push will fail.

### Project Settings — Code Sources (updated)

Replace hardcoded Docker mount quick-add buttons with:

1. **"Add from GitHub"** button — opens repo selection modal
2. **Repo selection modal**: searchable list of all repos from connected GitHub account, multi-select checkboxes, "Add Selected Repos" confirm button
3. **Connected repo rows**: show `owner/repo`, branch, last indexed time, "Sync Now" button (manual trigger), remove button
4. **"+ Add manual path"** still available for Docker mount / local path use cases

Webhook status is not shown explicitly — it is registered automatically when a repo is added. If webhook registration fails, the row shows `status: error`.

---

## Flow Diagrams

### Connect GitHub + Add Repo

```
User clicks "Connect GitHub"
  → Go API redirects to GitHub OAuth
  → User authorizes
  → GitHub redirects to /api/v1/auth/github/callback
  → Go API stores encrypted token in oauth_tokens

User opens Project Settings → Add from GitHub
  → Go API calls GitHub API → returns repo list
  → User selects repos → clicks "Add"
  → Go API: creates source_connections row
  → Go API: registers webhook on GitHub repo
  → Go API: publishes index_project message to queue
  → Python worker: clones repo → full_scan → deletes clone
```

### Push Webhook Re-index

```
Developer pushes to GitHub repo
  → GitHub sends POST /webhooks/github
  → Go API: verifies HMAC signature
  → Go API: looks up source_connections by repo full_name
  → Go API: publishes index_project message to queue
  → Python worker: clones repo → full_scan → deletes clone
```

---

## Security

- GitHub token stored **encrypted** in `oauth_tokens.access_token` (AES-256-GCM, existing crypto layer)
- Token decrypted server-side, passed to Python worker via queue message (Redis), never sent to browser
- Webhook signature verified with HMAC-SHA256 before any processing
- Clone URL with embedded token: `capture_output=True` prevents token appearing in subprocess logs
- Token revocation: DELETE `/api/v1/auth/github` deletes all webhooks before removing token

---

## Out of Scope (this phase)

- GitLab / Bitbucket
- Branch selection per repo (always default branch)
- Incremental index on push (always full scan; incremental is a future optimization)
- GitHub App (using OAuth App instead — simpler, sufficient for Phase 1)
- Organization-level GitHub connections (personal account only for now)
