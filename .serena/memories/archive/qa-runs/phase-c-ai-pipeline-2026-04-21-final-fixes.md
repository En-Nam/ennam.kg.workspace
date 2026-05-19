# Phase C Final Fixes — AI Pipeline Unblocked

**Date**: 2026-04-21
**Commits**: 27a2115 (4 infra fixes) + bd984bd (2 pipeline fixes)

## Bug #1: Provider base_url not persisted
- `updateProviderRequest` was missing `base_url` field
- PATCH couldn't set/fix base_url → provider had empty URL → all AI calls fail
- Fix: added `base_url` to update request + partial update logic

## Bug #2: Stream project resolution
- Stream handler only resolved project_id from API key identity
- Admin unscoped keys have no default → 400
- Fix: accept `project_id` in request body, 3-tier fallback (body → identity → middleware)

## AI Pipeline Status: UNBLOCKED
With base_url set to `https://api.anthropic.com` and OAuth token connected, the AI selector can now route requests through Claude Max subscription.
