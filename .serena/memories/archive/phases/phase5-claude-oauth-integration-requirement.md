# Requirement: Claude OAuth Subscription Login for AI Provider

**Date**: 2026-04-14
**Requester**: Technical Lead
**Priority**: High — replaces API key-based AI auth with subscription-based OAuth
**Status**: PENDING BA ANALYSIS

---

## Requirement Summary

Thay thế `KG_EMBEDDING_API_KEY` (OpenAI API key) bằng Claude OAuth subscription login. Admin vào System Settings → login Claude giống cách VS Code extension làm → hệ thống dùng subscription token cho tất cả AI calls (embedding, inference, verification).

## Current State

- AI provider auth: manual API key (stored encrypted in `ai_providers.api_key_encrypted`)
- Embedding auth: `KG_EMBEDDING_API_KEY` env var (OpenAI key)
- Mỗi provider register riêng với plaintext API key

## Desired State

- Admin mở Settings page → click "Login with Claude" → browser redirect đến Claude OAuth
- OAuth flow hoàn tất → system nhận authorization token
- Token dùng cho TẤT CẢ AI calls: embedding, intent parsing, SQL generation, verification, insights
- Không cần manual API key nữa — subscription-based, zero per-token cost (Claude Max)

## OAuth Flow Reference (from VS Code extension)

```
URL: https://claude.com/cai/oauth/authorize
Params:
  code=true
  client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e    ← VS Code's client ID
  response_type=code                                  ← Authorization Code flow
  redirect_uri=https://platform.claude.com/oauth/code/callback
  scope=org:create_api_key user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload
  code_challenge=...                                  ← PKCE (S256)
  code_challenge_method=S256
  state=...                                           ← CSRF protection
```

Key observations:
- OAuth 2.0 Authorization Code flow with PKCE (most secure for server-side)
- Scope `user:inference` = direct inference via subscription (no per-token cost)
- Scope `org:create_api_key` = can create API keys programmatically
- VS Code uses `platform.claude.com/oauth/code/callback` as redirect URI

## Questions for BA Team

### Architecture Questions
1. **Client ID**: Do we need our own OAuth client_id from Anthropic? Or can we reuse VS Code's? (Likely need our own — Anthropic developer program registration required)

2. **Redirect URI**: What should our callback URL be?
   - Option A: `https://{our-domain}/api/v1/auth/claude/callback` (Go API handles directly)
   - Option B: `https://{our-domain}/settings/claude-callback` (NextJS page handles, then calls Go API)
   - Option C: Manual code paste (like VS Code's code display flow — no redirect needed)

3. **Token storage**: Where to store OAuth tokens?
   - Option A: `system_settings` table (encrypted, like other secrets)
   - Option B: New `oauth_tokens` table (with refresh token lifecycle)
   - Option C: `ai_providers` table (extend existing provider model)

4. **Token refresh**: Claude OAuth tokens likely expire. Need refresh token flow.

5. **Scope requirements**: Which scopes does our platform actually need?
   - `user:inference` — YES (core: all AI calls)
   - `org:create_api_key` — MAYBE (if we want to create per-user API keys)
   - `user:profile` — MAYBE (display connected account info)
   - Others — probably not needed

### Embedding Strategy
6. **Anthropic embedding**: Anthropic doesn't have a dedicated embedding API (as of early 2026). Options:
   - Option A: Use Claude model itself for embedding (expensive, high quality)
   - Option B: Continue using OpenAI embedding API separately (cheaper, needs separate key)
   - Option C: Use open-source embedding model locally (no external dependency)
   - Option D: Use Voyager (Anthropic's embedding model if released by then)

7. **If no Anthropic embedding**: Keep `KG_EMBEDDING_API_KEY` for embedding-only, use Claude OAuth for everything else?

### UX Questions
8. **Login flow in Settings page**: 
   - Admin clicks "Connect Claude Account"
   - Browser opens Claude OAuth page (popup or redirect?)
   - User authorizes
   - Callback stores token
   - Settings page shows "Connected as: user@email.com"

9. **Multiple admins**: Can multiple admins connect their own Claude accounts? Or is it one platform-wide connection?

10. **Disconnection**: Admin can disconnect → revoke OAuth token → fall back to manual API keys

### Security Questions
11. **Token encryption**: OAuth tokens (access + refresh) must be AES-256-GCM encrypted at rest (same as connection strings)
12. **Token scope**: Should the platform-level token be shared across all projects, or per-project?
13. **Rate limiting**: Claude Max subscription has rate limits — how does this interact with existing BA-009 circuit breaker?

## Impact Analysis

### Affected Components

| Component | Change Required |
|-----------|----------------|
| `internal/ai/selector.go` | Support OAuth token auth (not just API key) |
| `internal/ai/anthropic.go` | Token-based auth header instead of x-api-key |
| `internal/handler/settings.go` | OAuth initiation + callback endpoints |
| `internal/service/settings.go` | Token storage + refresh lifecycle |
| `cmd/kg-server/main.go` | Wire OAuth flow |
| `ennam.kg.next` Settings page | "Connect Claude" button + callback handling |
| `docker-compose.yml` | New env vars (CLIENT_ID, CLIENT_SECRET?) |
| `internal/service/embedding_generator.go` | Use Claude token or separate embedding key |

### Dependencies
- BA-009 (AI Provider Abstraction) — OAuth token becomes a new provider auth method
- BA-016 (System Settings) — token stored in settings
- BA-020 (Smart Context) — embedding API may change
- Anthropic Developer Program — need client_id registration

## Suggested BA Scope

This should be **BA-021: Claude OAuth Integration** covering:
- FR-001: OAuth Authorization Code flow with PKCE
- FR-002: Token storage (encrypted) + refresh lifecycle
- FR-003: Settings UI for admin OAuth management
- FR-004: AI provider adapter for OAuth token auth
- FR-005: Embedding strategy decision (Claude vs OpenAI vs local)
- FR-006: Fallback to manual API keys when OAuth not configured
