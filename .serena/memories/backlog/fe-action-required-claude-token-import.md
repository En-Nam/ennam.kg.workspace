# FE Action Required: Claude Token Import Endpoint

**Date**: 2026-04-21
**Status**: BE DEPLOYED — endpoint live

## New Endpoint

### POST /api/v1/auth/claude/import-token (Admin only)

Two import methods:

### Method 1: Credentials JSON (recommended)
Admin login Claude Code locally → copy `.credentials.json` → paste in Settings.

```json
Request:
{
  "type": "credentials",
  "credentials": {
    "accessToken": "sk-ant-oat01-...",
    "refreshToken": "sk-ant-ort01-...",
    "expiresAt": 1776769257240,
    "scopes": ["user:inference", "user:profile"],
    "subscriptionType": "max",
    "rateLimitTier": "default_claude_max_20x"
  }
}

Response 200:
{
  "status": "connected",
  "provider": "anthropic",
  "expires_at": "2026-06-19T...",
  "connected_at": "2026-04-21T..."
}
```

### Method 2: Authorization Code
Admin pastes OAuth code from callback URL.

```json
Request:
{
  "type": "code",
  "code": "IGmKZKOSvpoPJnzbNtY3XX91yfLafsTyrFL1147kkHC0cz2x"
}

Response 200: same as above
Response 400: "ai.oauth_client_id not configured" (if no client_id set)
```

## FE Settings Page UI

Admin sees "Connect Claude" section with 2 tabs:

### Tab 1: "Paste Credentials" (default)
- Textarea for JSON paste
- Parse button → validates JSON → shows preview (subscription type, scopes, expiry)
- "Import" button → POST /auth/claude/import-token with type="credentials"

### Tab 2: "Paste Authorization Code"
- Single text input for code string
- "Import" button → POST /auth/claude/import-token with type="code"

### Status Display
After import, show:
- Green badge: "Connected — Claude Max"
- Expiry countdown: "Expires in 58 days"
- Scopes: "user:inference, user:profile"
- "Disconnect" button

## Credentials Location
Claude Code stores credentials at:
- macOS: `~/Library/Application Support/claude-code/.credentials.json`
- Linux: `~/.config/claude-code/.credentials.json`
- Windows: `%APPDATA%\claude-code\.credentials.json`

Only `claudeAiOauth` section needed — ignore `mcpOAuth`.
