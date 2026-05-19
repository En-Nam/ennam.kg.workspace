# Checkpoint: Sprint P3 + N3 Complete (2026-03-25)

## Python Service — Sprint P3 (Indexing Pipeline)
- Commit: `8df2dd1` on `ennam.kg.python/main`
- **57 tests passing** (30 new + 27 from P1/P2)
- Files: extractor.py, differ.py, engine.py + tests + KG client extensions
- Engine: `full_scan()` and `incremental_scan()` with error isolation
- Extractor: Symbol → Go API node payloads, edge extraction (parent-child, imports)
- Differ: Natural key `(file_path:name:kind)` + body_hash for create/update/archive
- KG client: 5 new async methods (create_node, update_node, search_nodes, get_nodes, create_edge)
- API endpoints: Real implementations replacing 501 stubs

## NextJS Dashboard — Sprint N3 (Graph Visualization)
- Commit: `1827d68` on `ennam.kg.next/main`
- **Build passes with zero TS errors**
- Files: 9 new (graph components, adapter, styles, hooks, API helpers, types)
- KnowledgeGraph.tsx: Cytoscape.js with dynamic import, 5 layouts, selection, export
- GraphControls: layout selector, zoom, type filter, search, PNG export
- NodeInspector: Sheet panel with node details, edge lists, clickable navigation
- Adapter: FlatResponse → Cytoscape elements with broken-edge filtering
- Styles: Color-coded per node type with selected/highlighted/dimmed states

## Remaining Sprints
- **P4**: AI summarization (Haiku 4.5) + queue consumer (Redis BLPOP)
- **N4**: Code map, impact analysis, metrics, settings pages
- **Go**: No gaps remaining — queue wired into 7 handlers

## Cumulative State
- Go: 2 commits (Phase 1 + queue wiring)
- Python: 2 commits (P1+P2 scaffold + P3 pipeline)
- NextJS: 2 commits (N1 scaffold + N2 views, N3 graph)
