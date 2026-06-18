# MCP Interface & REST API Specification

> **Full specification**: See the following BA documents for complete details:
> - `ennam.kg.requirements/documents/phase1/BA-001-platform-foundation.md` §8 API Mapping (40+ REST endpoints)
> - `ennam.kg.requirements/documents/phase1/BA-002-mcp-bridge.md` §3 (all 25 MCP tool schemas with parameters)
> This file is a quick-reference summary.

## MCP Tools (30 total — all implemented in Go bridge)

### Phase 6 ingest (5)
```
kg_ingest_document(project_id, title, content_raw, source_id, auto_approve?, ...)
kg_ingest_process_draft(project_id, draft_id, mode?, force?)
kg_ingest_list_drafts(project_id, status?, limit?, offset?)
kg_ingest_get_draft(project_id, draft_id)
kg_ingest_approve_draft(project_id, draft_id)
```

### Store Tools (6)
```
kg_store_decision(project_id, title, context, rationale, alternatives[], impact, related_concepts[])
kg_store_concept(project_id, name, definition, domain, aliases[])
kg_store_discovery(project_id, description, category, related_to[])
kg_store_task(project_id, task_id, title, status, assignee, blockers[])
kg_store_architecture(project_id, type, content, version, related_to[])
kg_store_session(project_id, agent, summary, phase, decisions_made[], discoveries[])
```

### Update Tools (6)
kg_update_decision, kg_update_concept, kg_update_requirement, kg_update_task, kg_update_architecture, kg_update_discovery

### Query Tools (4)
```
kg_query(project_id, query_string)           — Structured JSON filtering + traversal
kg_search(project_id?, text, node_types[])   — Full-text search (tsvector)
kg_get_neighbors(node_id, direction, types)  — Direct neighbors
kg_traverse(node_id, depth, edge_types)      — Multi-hop graph traversal
```

### Other Tools
- kg_link(source_id, target_id, relationship_type, metadata?)
- kg_store_session / kg_end_session

## REST API Quick Reference
- Public: `GET /healthz`, `GET /readyz`
- Protected (`/api/v1/`): All require API key in `Authorization: Bearer <key>` header
- Node CRUD: `POST /api/v1/nodes/{type}`, `PATCH /api/v1/nodes/{type}/{id}`
- Query: `POST /api/v1/query`, `POST /api/v1/search`, `GET /api/v1/search`
- Graph: `GET|POST /api/v1/nodes/{id}/neighbors`, `GET|POST /api/v1/nodes/{id}/traverse`
- Edges: `POST /api/v1/edges`
- Sessions: `POST|GET /api/v1/sessions`, `PUT|POST /api/v1/sessions/{id}`

## Validation (Double Safety Net)
- **Gate 1 (MCP Layer)**: JSON schema validation — see `BA-005-enforcement.md` FR-001
- **Gate 2 (Hook Layer)**: Workflow completeness — see `BA-005-enforcement.md` FR-002
