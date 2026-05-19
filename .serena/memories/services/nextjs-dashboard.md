# NextJS Dashboard — Service State

**Last updated**: 2026-05-12
**Latest commit**: `0d76f34` on `main` (+ uncommitted: agentic AI chat components)

## Dashboard Pages

| Page | Path | Purpose |
|------|------|---------|
| Graph | `/graph` | 3D force-directed knowledge graph (react-force-graph-3d) |
| Chat | `/chat`, `/chat/[threadId]` | AI chat with SSE streaming |
| Data Sources | `/data-sources`, `/data-sources/[id]` | CRUD for database connections |
| Query | `/query` | Direct SQL query interface |
| Schema Graph | `/schema-graph` | Database schema visualization |
| Code Map | `/code-map` | Code structure visualization |
| Activity | `/activity` | Recent activity feed |
| Benchmarks | `/benchmarks` | Performance benchmarks |
| Favorites | `/favorites` | Bookmarked nodes |
| Impact | `/impact` | Impact analysis |
| Decisions | `/decisions` | Decision tracking |
| Metrics | `/metrics` | System metrics |
| Settings | `/settings` | User settings |
| Admin Sync | `/admin/sync` | Sync job management |
| Projects | `/projects` | Project management |

## Key Components

### Graph (`components/graph/`)
- `KnowledgeGraph.tsx`: 3D force graph with focus+context effect, smooth camera transitions
- `KnowledgeGraphWrapper.tsx`: Client-side wrapper (dynamic import for SSR)
- `GraphControls.tsx`: Graph control panel
- `NodeInspector.tsx`: Node detail panel
- **CRITICAL**: Selection state is isolated from ForceGraph3D to prevent camera jitter

### Chat (`components/chat/`)
- `ChatMessage.tsx`: Renders messages with block-based content, error display, agentic components
- `ChatMessageList.tsx`: Message list with SSE streaming, block_id handling
- `QueryInputBar.tsx`: Query input with TierSelector (Quick/Deep toggle)

### Agentic AI Components (uncommitted, 2026-05-12)
- `TierSelector.tsx`: Quick/Deep segmented control with localStorage persistence
- `AgenticProgress.tsx`: Collapsible step timeline with PhaseIndicator + ToolCallStepRow
- `ClarificationPrompt.tsx`: Inline clarification form with CountdownRing (600s SVG timer)
- `KgNodeChip.tsx`: Colored pill badges for KG node references
- `MultiSourceResults.tsx`: Tabbed datasource results display
- `use-agentic-stream.ts` hook: Manages full agentic SSE lifecycle
- `sse-handler.ts`: Extended with 8 agentic callbacks
- `types/agentic.ts`: All agentic TypeScript types

### Data Sources (`components/data-sources/`)
- `DataSourceForm.tsx`, `DataSourceTable.tsx`, `SyncProgressBar.tsx`

### BFF Proxy
- `src/app/api/kg/[...path]/route.ts`: Proxies all Go API calls, includes SSE passthrough

## react-force-graph-3d — Critical Lessons

1. Use `react-force-graph-3d` (separate package), NOT umbrella `react-force-graph`
2. Selection state must NOT live in same component tree as ForceGraph3D (causes camera jitter)
3. Use stable refs for callbacks (empty deps `useCallback`), not state
4. `nodeColor` prop as function reading from refs — NOT `nodeThreeObject` material manipulation
5. Custom links: set `line.frustumCulled = false` to prevent disappearing on zoom
6. Inspector panel must be fixed-width in flex row, not absolute positioned
7. `zoomToFit` nodeFilterFn is buggy in v1.79 — use manual bbox + `cameraPosition()`

## Architecture Notes
- NextJS App Router with `(dashboard)` route group
- BFF pattern: all Go API calls proxied through `/api/kg/[...path]`
- Chat streaming: EventSource connects to BFF proxy which forwards SSE from Go
