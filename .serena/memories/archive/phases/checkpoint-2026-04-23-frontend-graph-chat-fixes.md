# Checkpoint: Frontend Graph UX + Chat Fixes — 2026-04-23

## Summary
Two major areas: (1) /graph page UX upgrade with 3d-force-graph, (2) /chat production bug fixes from QA.

## Graph Page UX Upgrade
- Migrated from vanilla `3d-force-graph` to `react-force-graph-3d` React wrapper
- SSR-safe dynamic import via `KnowledgeGraphWrapper.tsx` (ssr: false)
- **Bloom effect**: UnrealBloomPass (strength=2, radius=0.5, threshold=0) — disabled on init, enabled on first interaction
- **Click-to-focus**: exact demo pattern (distance=40, distRatio, 3s animation)
- **Gradient links**: custom THREE.Line with vertexColors, frustumCulled=false
- **Highlight/dim**: nodeColor prop function with hex alpha (reads from refs, no re-render)
- **Camera jitter fix**: IsolatedInspector component owns selection state separately — ForceGraph3D never re-renders on node select
- **Layout**: flex row with fixed-width inspector (360px), graph canvas flex-1 with ResizeObserver dimensions
- **View modes**: Graph View (free force) / Tree View (dagMode='td') via dropdown
- **Node dragging**: fix-on-drop pattern (fx/fy/fz)

### Key lesson (saved to Serena memory)
Any React re-render of ForceGraph3D disrupts camera animations. Selection state must be isolated in a separate component tree. Callbacks via stable refs. See `frontend/react-force-graph-3d-lessons`.

## Chat Bug Fixes (from QA report)
- P0: Replaced hardcoded `projectId = 'default'` with `useProject()` in 4 pages
- P1: BFF SSE proxy — text/event-stream pass-through without buffering
- P1: Added `project_id` to StreamRequest type + stream.mutate() calls
- P2: Wired ResponseRenderer, InsightCards, SuggestedActions into ChatMessage.tsx

## Files Changed (graph)
- `src/components/graph/KnowledgeGraph.tsx` — full rewrite (react-force-graph-3d)
- `src/components/graph/KnowledgeGraphWrapper.tsx` — NEW: SSR-safe dynamic import + memo
- `src/components/graph/GraphControls.tsx` — Graph View / Tree View
- `src/components/graph/NodeInspector.tsx` — fixed-width, bg-zinc-900
- `src/app/(dashboard)/graph/page.tsx` — IsolatedInspector, flex layout
- `src/types/d3-force-3d.d.ts` — NEW: type declaration

## Files Changed (chat)
- `src/app/(dashboard)/chat/page.tsx` — useProject(), project_id in stream
- `src/app/(dashboard)/chat/[threadId]/page.tsx` — same
- `src/app/(dashboard)/query/page.tsx` — useProject()
- `src/app/(dashboard)/favorites/page.tsx` — useProject()
- `src/app/api/kg/[...path]/route.ts` — SSE pass-through
- `src/components/chat/ChatMessage.tsx` — rich response rendering
- `src/components/chat/ChatMessageList.tsx` — onSuggestedAction
- `src/types/thread.ts` — project_id in StreamRequest

## Remaining
- Go API: Thread search return [] not null
- Go API: Thread name max length 100
- Go API: Invalid UUID → 400 not 500
