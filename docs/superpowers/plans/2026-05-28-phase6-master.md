# Phase 6: Multi-Source Data Ingestion — Master Plan

> **For agentic workers:** Execute sprints in order: **1 → 2 → 3 → 5**. Sprint 4 (Jira/GDrive) is **deferred** — do not implement unless Phase 6.1 is approved.
>
> **MVP scope (2026-05-28):** Local upload + Public API/MCP + draft workflow + AI pipeline. **No Jira, no Google Drive.**
>
> **REQUIRED SUB-SKILL:** Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` per sprint.

**Goal (MVP):** Expand Ennam KG với **local upload** và **Public Ingestion API/MCP** — draft-node staging, human-in-the-loop review, và pipeline AI 4 bước (cross-link với DB schema hiện có). Jira/GDrive hoãn Phase 6.1.

**Architecture:** Unified ingestion framework (BA-022) owns `draft_nodes` + `source_connections` + Redis `ennam:kg_generation`. BA-023 MVP = file upload adapter only. BA-024 = Public REST/MCP + AI pipeline. Go = gateway; Python = file extraction + AI engine; NextJS = Knowledge Sources tab.

**Tech Stack:** Go (`net/http`, `database/sql`), Python 3.12 (FastAPI worker, Redis consumer), NextJS 16 App Router, PostgreSQL 16, Redis 7, Anthropic via BA-009 selector (Haiku extraction, Sonnet cross-linking)

**Source of truth:** `ennam.kg.requirements/documents/phase6/` (BA-022, BA-023, BA-024, design spec)

---

## Prerequisites (must be green before Sprint 1)

| Prerequisite | Status | Notes |
|--------------|--------|-------|
| Phase 3 auth + projects (BA-014/015) | ✅ Migrations 032–033 | Admin role for approve/reject |
| System settings (BA-016) | ✅ Migration 034 | Ingestion settings seeded in 053 |
| OAuth tokens (BA-021) | ✅ Migration 040 | Migration 050 (per-project) **deferred** with Jira/GDrive |
| Redis in Docker Compose | ✅ | MVP: `ennam:kg_generation` only |
| Phase 5 NextJS OAuth UI | — | **Not required** for MVP (no Jira/GDrive) |

**KG MCP:** Unavailable in Cursor session — fall back to Serena + BA docs. Backfill decisions to KG after Sprint 1.

---

## Critical: Migration Renumbering

BA-022 originally allocated migrations **040–046**. Those numbers are **already used** (oauth_tokens, agentic AI, etc.). Phase 6 uses **047–053**:

| Migration | Table / Change | BA |
|-----------|----------------|-----|
| `000047_create_draft_nodes` | `draft_nodes` + indexes + state machine CHECK | BA-022 |
| `000048_create_source_connections` | `source_connections` + webhook_secret index | BA-022 |
| `000049_create_uploaded_files` | `uploaded_files` + FK to draft_nodes | BA-023 |
| ~~`000050_oauth_tokens_project_scope`~~ | **Deferred Phase 6.1** (Jira/GDrive OAuth) | — |
| `000051_extend_node_types_ingestion` | Add `initiative`, `document`, `dataset`, `external` to node_type CHECK | BA-024 |
| `000052_extend_edge_types_ingestion` | Add references_*, cross_source_reference, upload_batch (+ jira_* reserved) | BA-024 |
| `000053_seed_ingestion_settings` | 6 rows in `system_settings` category `ingestion` | BA-022 |

---

## Execution Order (MVP: 4 sprints)

```text
Sprint 1: BA-022 Go foundation (draft CRUD, connections, queue publish)
    ↓
Sprint 2: BA-022 Admin UI + ingestion settings (NO webhooks)
    ↓
Sprint 3: BA-023 local upload + file extraction + ingest/upload alias
    ↓
Sprint 5: BA-024 Public ingest API + MCP + Python 4-step AI pipeline

Sprint 4: ⏸ DEFERRED — Jira + Google Drive (Phase 6.1)
```

**Parallelism:** Sprint 3 có thể bắt đầu ngay sau Sprint 1 (không cần chờ Sprint 2 UI).

---

## Sprint Documents

| Sprint | BA | Plan file | Deliverable |
|--------|-----|-----------|-------------|
| 1 | BA-022 | [`2026-05-28-phase6-sprint1-ba022-go-foundation.md`](2026-05-28-phase6-sprint1-ba022-go-foundation.md) | Draft + connection APIs, migrations 047–048, Redis job publish, integration tests |
| 2 | BA-022 | [`2026-05-28-phase6-sprint2-ba022-webhooks-ui.md`](2026-05-28-phase6-sprint2-ba022-webhooks-ui.md) | Knowledge Sources tab, settings 053, auto-approve (upload/API) |
| 3 | BA-023 | [`2026-05-28-phase6-sprint3-ba023-local-upload.md`](2026-05-28-phase6-sprint3-ba023-local-upload.md) | File upload, extraction, migration 049, fix `ingest-md-via-api.sh` |
| 4 | BA-023 | [`2026-05-28-phase6-sprint4-ba023-jira-gdrive.md`](2026-05-28-phase6-sprint4-ba023-jira-gdrive.md) | ⏸ **DEFERRED** — Jira/GDrive OAuth, adapters, webhooks |
| 5 | BA-024 | [`2026-05-28-phase6-sprint5-ba024-public-api-ai-pipeline.md`](2026-05-28-phase6-sprint5-ba024-public-api-ai-pipeline.md) | Public REST, MCP tools, 4-step pipeline, migrations 051–052 |

---

## Redis Queues (MVP)

| Queue | Producer | Consumer | Message shape |
|-------|----------|----------|---------------|
| `ennam:kg_generation` | Go `POST .../draft-nodes/process` | Python `IngestionPipelineEngine` | `{ job_id, batch_id, project_id, draft_node_ids[], created_at }` |

**Deferred (Phase 6.1):** `ennam:webhooks:jira`, `ennam:webhooks:gdrive`

Python `Settings`: thêm `redis_kg_generation_queue` (default `ennam:kg_generation`).

---

## Endpoint Inventory (MVP: ~21 REST + 5 MCP)

### BA-022 — Draft & Connections (15, no webhooks)

| Method | Path |
|--------|------|
| GET | `/api/v1/projects/{id}/draft-nodes` |
| GET | `/api/v1/projects/{id}/draft-nodes/{draftId}` |
| POST | `/api/v1/projects/{id}/draft-nodes/{draftId}/approve` |
| POST | `/api/v1/projects/{id}/draft-nodes/{draftId}/reject` |
| POST | `/api/v1/projects/{id}/draft-nodes/bulk-approve` |
| POST | `/api/v1/projects/{id}/draft-nodes/bulk-reject` |
| POST | `/api/v1/projects/{id}/draft-nodes/{draftId}/retry` |
| POST | `/api/v1/projects/{id}/draft-nodes/process` |
| GET | `/api/v1/projects/{id}/connections` |
| GET | `/api/v1/projects/{id}/connections/{connId}` |
| POST | `/api/v1/projects/{id}/connections` |
| PUT | `/api/v1/projects/{id}/connections/{connId}` |
| DELETE | `/api/v1/projects/{id}/connections/{connId}` |
| POST | `/api/v1/projects/{id}/connections/{connId}/sync` |
| GET | `/api/v1/projects/{id}/connections/{connId}/stats` |

~~Webhooks Jira/GDrive~~ — Phase 6.1

### BA-023 — Upload only (5, MVP)

| Method | Path |
|--------|------|
| POST | `/api/v1/projects/{id}/upload` |
| POST | `/api/v1/projects/{id}/ingest/upload` *(alias — matches existing script)* |
| GET | `/api/v1/projects/{id}/uploads` |
| GET | `/api/v1/projects/{id}/uploads/{uploadId}/download` |
| DELETE | `/api/v1/projects/{id}/uploads/{uploadId}` |

~~OAuth Jira/GDrive + BFF~~ — Phase 6.1

### BA-024 — Public Ingest (3 REST + 5 MCP)

| Method | Path / Tool |
|--------|-------------|
| POST | `/api/v1/projects/{id}/ingest` |
| POST | `/api/v1/projects/{id}/ingest/batch` |
| GET | `/api/v1/projects/{id}/ingest/status/{draftId}` |
| MCP | `kg_ingest_node`, `kg_ingest_batch`, `kg_list_drafts`, `kg_approve_drafts`, `kg_process_drafts` |

---

## Package Layout (new files)

### Go (`ennam.kg.go`)

```text
internal/models/
├── draft_node.go
├── source_connection.go
└── ingestion_job.go

internal/store/
├── draft_node.go
├── draft_node_test.go
├── source_connection.go
└── ingestion_job.go

internal/service/
├── draft_node.go          # state machine transitions
├── source_connection.go
├── ingestion_queue.go     # Redis LPUSH for kg_generation

internal/handler/
├── draft_node.go
├── draft_node_test.go
├── source_connection.go
├── ingest_upload.go       # Sprint 3
└── ingest_public.go       # Sprint 5
# Deferred: webhook.go, oauth_jira.go, oauth_gdrive.go

internal/mcp/tools/
└── ingest.go              # Sprint 5 — 5 MCP tools
```

### Python (`ennam.kg.python`)

```text
src/ennam_kg/ingestion/
├── __init__.py
├── pipeline/                # Sprint 5
│   ├── engine.py
│   ├── extract.py
│   ├── nodes.py
│   ├── intra_edges.py       # upload_batch only in MVP
│   └── cross_edges.py
├── adapters/
│   └── files.py             # Sprint 3 — md, pdf, docx, xlsx, csv
# Deferred: webhook_consumer.py, jira.py, gdrive.py
└── tests/
    ├── test_draft_pipeline.py
    └── test_file_adapter.py
```

### NextJS (`ennam.kg.next`)

```text
src/app/(dashboard)/projects/[id]/sources/
├── page.tsx                 # Knowledge Sources tab
├── components/
│   ├── draft-list.tsx
│   ├── draft-preview.tsx
│   ├── connection-bar.tsx
│   └── upload-dropzone.tsx  # Sprint 3
# Deferred: bff/oauth/jira, bff/oauth/gdrive
```

---

## Vertical Slice (Definition of Done — MVP)

End-to-end demo (upload + public API, no Jira/GDrive):

1. `POST /api/v1/projects/{id}/ingest/upload` with a `.md` file → draft `pending`
2. `POST .../draft-nodes/{id}/approve` → `approved`
3. `POST .../draft-nodes/process` → drafts `processing`, job on Redis
4. Python worker processes job → draft `processed`, `knowledge_node_id` set
5. Dashboard Knowledge Sources tab shows draft lifecycle
6. `scripts/ingest-md-via-api.sh report.md --process` exits 0

---

## Success Criteria (Phase 6 MVP complete)

| # | Criterion | Verification |
|---|-----------|--------------|
| SC-1 | MVP REST endpoints (~21) pass integration tests | Go tests + smoke script |
| SC-2 | 5 MCP ingest tools registered and callable | MCP tool list + `kg_ingest_node` |
| SC-3 | Upload `.md` → draft → approve → processed node | `ingest-md-via-api.sh --process` |
| SC-4 | Public ingest API idempotent upsert | Duplicate POST same source_id → update |
| SC-5 | Cross-source edge: upload doc ↔ existing DB schema node | Manual QA (NFR-195 sample) |
| SC-6 | Batch limit 50 enforced | POST 51 draft IDs → 400 |

**Deferred to Phase 6.1:** Jira webhook E2E, GDrive push E2E, webhook latency NFR-186

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Migration number collision | Use 047–053 only; update BA-022 doc comment in plan, not BA repo unless requested |
| Jira/GDrive scope creep | Explicitly deferred; Sprint 4 file marked DEFERRED |
| AI cost runaway | Default `ingestion.auto_queue_processing=false`; batch cap 50; Haiku for Step 1 |
| `ingest-md-via-api.sh` path drift | Sprint 3 adds `/ingest/upload` alias to `/upload` |
| MCP tool naming drift (spec vs BA-024) | Implement BA-024 names; deprecate draft mcp-api-spec names |

---

## Conventions (inherited)

- Handler → Service → Store (Go)
- Python stateless — credentials via Go-injected headers
- Errors: 400 validation, 401 auth, 403 forbidden, 404 not found, 409 conflict, 429 rate limit
- Paginated lists: `{"items": [...], "total_count": N}`
- Wire in `cmd/kg-server/main.go` `buildRouter()`
- Tests: Go table-driven + `*_integration_test.go`; Python pytest; NextJS component tests optional

---

## Self-Review (spec coverage)

| BA FR | Sprint |
|-------|--------|
| FR-001 Draft lifecycle | 1, 2 |
| FR-002 Source connections | 1, 2 |
| FR-003 Admin UI | 2 |
| FR-004 Webhooks | ⏸ Phase 6.1 |
| FR-005 Batch KG trigger | 1, 5 |
| FR-006 Auto-approve | 2, 3, 5 (upload/API only) |
| FR-007 Ingestion settings | 2 (053) |
| BA-023 file adapters | 3 |
| BA-023 Jira/GDrive | ⏸ Phase 6.1 (Sprint 4) |
| BA-024 public API + AI pipeline | 5 |

**MVP gaps (accepted):** FR-004 webhooks, Jira/GDrive adapters — tracked in Sprint 4 deferred doc.

---

## Execution Handoff

Plan saved. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per sprint task, review between tasks
2. **Inline Execution** — run Sprint 1 plan in this session with checkpoints

Which approach?
