# Phase 6: Multi-Source Data Ingestion

**Date**: 2026-04-23
**Status**: BA documents COMPLETE, reviewed, committed (1ff19e5)
**Design Spec**: `ennam.kg.requirements/documents/phase6/phase6-multi-source-ingestion-design.md`

## Summary
Expand Ennam KG from database-only knowledge to multi-source knowledge hub. 4 source connectors + Public Ingestion API for satellite platforms. Draft node workflow for human-in-the-loop AI processing.

## Architecture: Unified Ingestion Framework
- Adapter pattern: Jira, Google Drive, Local Upload adapters + Public API
- Draft nodes: central staging table (pending → approved → processing → processed)
- Webhooks: real-time from Jira + Google Drive → Redis queue → async processing
- AI pipeline: 4-step (extraction → nodes → intra-source edges → cross-source linking)
- Public API: REST + MCP for satellite platforms (Ennam Code Assistant)

## Scope
- 4 connectors: Database (existing), Jira, Google Drive, Local Upload
- Public Ingestion API (REST + MCP) for satellite platforms
- Draft node workflow with admin review + auto-approve option
- AI cross-source edge detection (confidence-scored)
- Skip images (future phase)
- BA-003 (code indexing) DEPRECATED — moves to Ennam Code Assistant

## BA Documents (3 planned)
| BA | Title | Scope | NFR Range |
|----|-------|-------|-----------|
| BA-022 | Unified Ingestion Framework | Draft data model, admin UI, connections, webhooks | NFR-185→190 |
| BA-023 | Source Adapters & File Processing | Jira, Google Drive, Local Upload adapters | NFR-191→195 |
| BA-024 | Public Ingestion API & Cross-Source Intelligence | Public REST/MCP, AI pipeline, cross-source linking | NFR-196→198 |

Dev order: BA-022 → BA-023 + BA-024 (parallel)
Migrations: 040-046 (7 new)
Endpoints: 37 new REST + 5 MCP tools
New node types: task, initiative, document, dataset, external
New edge types: jira_*, folder_contains, references_*, data_maps_to_table, cross_source_reference
