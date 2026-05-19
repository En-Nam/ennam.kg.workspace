# FE Chat Feature Completion — DONE

**Date**: 2026-04-23

## All fixes applied

### P0: projectId — DONE (earlier session)
### P1: BFF SSE proxy — DONE (earlier session)
### P2: Rich response rendering — DONE

**Persisted messages**: ChatMessage.tsx renders ResponseRenderer, InsightCards, SuggestedActions from ThreadMessage fields.

**Live streaming (NEW)**: useStreamQuery now tracks:
- `streamBlocks[]` — accumulated from block_start/block_content/block_end SSE events
- `streamInsights[]` — from insights SSE event (not yet emitted by BE, placeholder ready)
- `streamActions[]` — from suggested_actions SSE event

ChatMessageList renders streaming blocks during live stream, then insights+actions after stream completes.

### Type fixes
- `Insight` — added `title?`, `detail?` fields (BE sends both formats)
- `SuggestedAction` — NEW type `{label, action_type, description}`
- `ThreadMessage.suggested_actions` — union `SuggestedAction[] | string[]` for backward compat
- `StreamRequest.tier` — added `'precise' | 'balanced' | 'fast'`

## Files changed
- `src/types/insight.ts` — Insight + SuggestedAction types
- `src/types/thread.ts` — StreamRequest.tier, suggested_actions union type
- `src/hooks/use-thread-messages.ts` — streamBlocks/streamInsights/streamActions state + SSE callbacks
- `src/components/chat/ChatMessageList.tsx` — renders streaming rich content
- `src/components/chat/ChatMessage.tsx` — handles SuggestedAction[] mapping
- `src/app/(dashboard)/chat/page.tsx` — passes stream state props
- `src/app/(dashboard)/chat/[threadId]/page.tsx` — same
- `src/app/(dashboard)/chat-demo/page.tsx` — SuggestedAction mapping fix
