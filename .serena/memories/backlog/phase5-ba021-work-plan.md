# Phase 5 BA-021 Claude OAuth Integration — Work Plan

**Updated**: 2026-04-15
**Status**: GO + PYTHON COMPLETE — 12/19 tasks done, NextJS remaining

## Go API Team — ALL DONE

| # | Task | Status |
|---|------|--------|
| G8 | Migration 040: oauth_tokens table + 3 settings | DONE |
| G9 | OAuthStore: encrypted token CRUD | DONE |
| G10 | OAuthService: PKCE flow, token exchange | DONE |
| G11 | Token refresh goroutine: background auto-refresh | DONE |
| G12 | OAuthHandler: 5 endpoints | DONE |
| G13 | Anthropic adapter: Bearer token + OAuth priority | DONE |
| G14 | Selector: OAuth token fallback chain | DONE |
| G15 | EmbeddingGenerator: configurable provider | DONE |
| G16 | Wire OAuth routes + refresh in main.go | DONE |

**Branch**: `feature/phase5-ba021-claude-oauth` → merged to main (9 commits, +2009 lines)
**Migration**: 040 applied (oauth_tokens table + 3 settings)
**Endpoints**: 5 new OAuth endpoints on /api/v1/auth/claude/*

## Python Team — ALL DONE

| # | Task | Status |
|---|------|--------|
| P5 | Bearer token propagation from Go API | DONE |
| P6 | Local embedding model (all-MiniLM-L6-v2, 384 dims) | DONE |
| P7 | Embedding endpoint POST /api/v1/embeddings | DONE |

**Branch**: `feature/ba021-python-oauth-embeddings` → merged to main (5 commits, +339 lines)
**New endpoint**: POST /api/v1/embeddings (local model, 384-dim vectors)
**Auth**: Bearer token propagation via `default_bearer_token` on AIClient
**Tests**: 16 new tests, 42 total passing
**Dependencies**: sentence-transformers>=3.0, numpy>=1.26
## NextJS Team — TODO (7 tasks)

See original plan for details.
