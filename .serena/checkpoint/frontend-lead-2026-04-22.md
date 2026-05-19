# Checkpoint: frontend-lead -- 2026-04-22

## What was done
- Migrated /graph from vanilla 3d-force-graph to `react-force-graph-3d` React wrapper
  - Fixes stale closure bug where onNodeClick/onBackgroundClick never updated
  - All callbacks now React props — always fresh references
- Created KnowledgeGraphWrapper.tsx for SSR-safe dynamic import (ssr: false)
- Installed `react-force-graph-3d` as separate package (avoids AFRAME crash from react-force-graph umbrella)
- Node registry pattern: nodeRegistryRef (Map) + linkRegistryRef (Array) for material access
- Bloom (UnrealBloomPass) + selective dimming verified working via Chrome DevTools
- Camera zoom-to-selection uses manual bbox calculation (zoomToFit nodeFilterFn is buggy in v1.79)
- DAG mode, dagLevelDistance, d3VelocityDecay, numDimensions all set via React props (not ref methods)
- d3Force calls (charge, collision) via ref (valid ForceGraphMethods)
- Gradient links, node dragging with fix-on-drop, search highlighting all preserved

## Files changed
- `ennam.kg.next/src/components/graph/KnowledgeGraph.tsx` -- Full rewrite using react-force-graph-3d
- `ennam.kg.next/src/components/graph/KnowledgeGraphWrapper.tsx` -- NEW: SSR-safe dynamic import wrapper
- `ennam.kg.next/src/components/graph/GraphControls.tsx` -- Layout: Graph View / Tree View
- `ennam.kg.next/src/app/(dashboard)/graph/page.tsx` -- Import wrapper, default 'graph' layout
- `ennam.kg.next/src/components/nodes/ImpactAnalysis.tsx` -- Import wrapper, layout='graph'
- `ennam.kg.next/src/types/d3-force-3d.d.ts` -- NEW: type declaration
- `ennam.kg.next/package.json` -- Added three, @types/three, react-force-graph-3d

## Current state
- Graph renders correctly (615 nodes, 478 edges)
- Bloom + focus+context dimming works (verified via DevTools manual test)
- Camera zoom-to-selection works
- Gradient links visible
- Tree View (dagMode='td') available via dropdown
- Node click → onNodeSelect callback → React state update → useEffect bloom: SHOULD work (closure fix applied)
- Needs user click test on actual browser to confirm end-to-end

## Next steps
- User QA: click nodes in browser to confirm bloom triggers automatically
- Fine-tune bloom parameters if needed
- Test Tree View with cycle data
- Test drag + fix behavior

## Session 2: Chat QA Bug Fixes

### What was done
- P0: Replaced hardcoded `projectId = 'default'` with `useProject()` in 4 files (chat, chat/[threadId], query, favorites)
- P1: BFF SSE proxy — added `text/event-stream` detection before `res.json()`, pass-through streaming response without buffering
- P2: Wired ResponseRenderer, InsightCards, SuggestedActions into ChatMessage.tsx (production /chat now renders rich blocks like /chat-demo)
- Updated ChatMessageList to pass `onSuggestedAction` callback through to ChatMessage

### Files changed
- `src/app/(dashboard)/chat/page.tsx` — useProject() + onSuggestedAction
- `src/app/(dashboard)/chat/[threadId]/page.tsx` — useProject() + onSuggestedAction
- `src/app/(dashboard)/query/page.tsx` — useProject()
- `src/app/(dashboard)/favorites/page.tsx` — useProject()
- `src/app/api/kg/[...path]/route.ts` — SSE pass-through
- `src/components/chat/ChatMessage.tsx` — ResponseRenderer + InsightCards + SuggestedActions
- `src/components/chat/ChatMessageList.tsx` — onSuggestedAction prop

### Session 2b: StreamRequest fix (2026-04-23)
- Added `project_id` to `StreamRequest` type in `src/types/thread.ts`
- Passed `project_id: projectId` in `stream.mutate()` in both chat pages
- This was the final blocker for AI streaming — Go API requires project_id

### Remaining from QA report (Go API team)
- Thread search should return [] not null when no matches
- Thread name max length validation (100 chars)
- Invalid UUID returns 500 (should 400)

## Blockers / Risks
- WebGL raycasting cannot be simulated via DevTools (need real mouse clicks)
- `react-force-graph-3d` ForceGraphMethods type is incomplete (many methods missing)
- Performance with 600+ nodes using individual MeshStandardMaterial per node — monitor
