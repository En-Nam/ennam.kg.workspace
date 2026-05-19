# Anthropic OAuth Limitation — Discovered 2026-04-21

## Finding
Anthropic Messages API (`/v1/messages`) does NOT support OAuth token authentication.
Error: `"OAuth authentication is currently not supported."`

Claude OAuth scopes (`user:inference`) work ONLY via:
- Claude.ai web interface
- Claude Code CLI
- Claude MCP servers

They do NOT work via:
- Direct REST API calls to `api.anthropic.com/v1/messages`

## Impact on Ennam KG
- BA-021 OAuth integration works for CONNECTION + TOKEN STORAGE
- But OAuth tokens CANNOT be used for AI inference calls from Go backend
- All AI features (NL query, insights, embeddings) need standard `sk-ant-api03-*` API key

## Recommendation
- Register AI provider with standard Anthropic API key (not OAuth)
- Keep OAuth integration for future when Anthropic enables API OAuth support
- Update BA-021 spec to note this platform limitation
