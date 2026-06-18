# Phase 6 Sprint 5: BA-024 Public API + AI Pipeline — Implementation Plan

> **Parent:** [`2026-05-28-phase6-master.md`](2026-05-28-phase6-master.md) · **Requires:** Sprint 1–3 (Sprint 4 Jira/GDrive **deferred**)

**Goal:** Satellite platforms ingest via REST/MCP; approved drafts run 4-step AI pipeline creating nodes, intra-source edges, and cross-source links.

---

## Migrations 051–052 — taxonomy extension

**Files:**
- `db/migrations/000051_extend_node_types_ingestion.up.sql` — add initiative, document, dataset, external to node_type CHECK
- `db/migrations/000052_extend_edge_types_ingestion.up.sql` — add 12 edge types from design spec §8

Update `config.yaml` or node/edge validation whitelist in Go handler.

---

## Go — Public ingest REST (FR-001)

**Files:** `internal/handler/ingest_public.go`

| Method | Path | Body |
|--------|------|------|
| POST | `/api/v1/projects/{id}/ingest` | `{ title, content_raw, source_type, source_id, content_format?, metadata?, auto_approve? }` |
| POST | `/api/v1/projects/{id}/ingest/batch` | `{ items: [...] }` max 100 |
| GET | `/api/v1/projects/{id}/ingest/status/{draftId}` | status + knowledge_node_id |

- API key auth (existing middleware)
- Rate limit 100 req/min per key (NFR-191)
- Upsert via DraftNodeStore.Upsert
- `auto_approve` respects connection + global `ingestion.auto_approve_external`

---

## Go — MCP tools (FR-002)

**File:** `internal/mcp/tools/ingest.go`

Register 5 tools (names per BA-024):
- `kg_ingest_node` — single draft submit
- `kg_ingest_batch` — max 50 items
- `kg_list_drafts` — filters status, source_type
- `kg_approve_drafts` — 1–50 IDs
- `kg_process_drafts` — trigger pipeline

Wire in MCP bridge registry alongside existing 25 tools → 30 total.

---

## Python — IngestionPipelineEngine

**Files:**
- `src/ennam_kg/ingestion/pipeline/engine.py`
- `src/ennam_kg/ingestion/pipeline/extract.py`
- `src/ennam_kg/ingestion/pipeline/nodes.py`
- `src/ennam_kg/ingestion/pipeline/intra_edges.py`
- `src/ennam_kg/ingestion/pipeline/cross_edges.py`

**Worker handler** for `ennam:kg_generation` messages:

```python
async def handle_kg_generation(msg: dict) -> None:
    engine = IngestionPipelineEngine(kg_client, ai_client)
    await engine.run_batch(
        project_id=msg["project_id"],
        draft_ids=msg["draft_node_ids"],
        batch_id=msg["batch_id"],
    )
```

### Step 1 — Extract (Haiku)

Prompt: extract topic, entities, decisions, referenced tables/APIs, people.
Output: JSON stored in draft metadata `extraction_result`.

### Step 2 — Node creation (deterministic)

Map source_type → node_type (MVP):
- `local_upload` + md/pdf/docx → document
- `local_upload` + csv/xlsx → dataset
- `satellite_api` → external
- `manual` → document

*(Jira → task/initiative, GDrive → document — Phase 6.1)*

POST `/api/v1/nodes` via KGClient with project_id.

Update draft: `knowledge_node_id`, status handled in Step 4 batch finalize.

### Step 3 — Intra-source edges (deterministic)

From metadata (MVP): `upload_batch` for files uploaded together in one request.

*(Jira hierarchy, folder_contains — Phase 6.1)*

POST `/api/v1/edges` idempotent (ON CONFLICT DO NOTHING).

### Step 4 — Cross-source (Sonnet, 1 call/batch)

Fetch recent KG nodes (30 days) + batch extractions.
Prompt: propose edges with confidence 0.0–1.0.
Only create edges with confidence ≥ 0.5.
Target NFR-195: ≥70% precision on manual sample.

**Finalize:** PATCH draft status processed/failed via Go API; update job metadata `{processed, failed}`.

---

## Go — Worker callback endpoints (if needed)

Option A: Python calls existing node/edge APIs (preferred — stateless).
Option B: Add internal `PATCH /api/v1/projects/{id}/draft-nodes/{id}/complete` for worker status updates.

---

## NextJS — Ingestion sub-tab enhancements

- API key management section
- Processing monitor with step progress (poll draft statuses)
- Graph view: cross-source edge opacity by confidence (BA-024 §9)

---

## E2E verification

```bash
# Public ingest
curl -X POST -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"title":"Test","content_raw":"See users table","source_type":"satellite_api","source_id":"ext-1","auto_approve":true}' \
  "http://localhost:8080/api/v1/projects/$PROJECT_ID/ingest"

# Process via MCP or REST
curl -X POST .../draft-nodes/process -d '{"draft_node_ids":["..."]}'

# Wait for worker — verify knowledge_node_id populated
curl .../ingest/status/{draftId}
```

---

## Sprint 5 Done Checklist

- [ ] Public ingest + batch + status endpoints
- [ ] 5 MCP tools callable from Claude Code
- [ ] Full pipeline: approved draft → knowledge node + edges
- [ ] Cross-source edge created between document mentioning table and schema_table node
- [ ] Migrations 051–052 applied
- [ ] Phase 6 **MVP** success criteria SC-1 through SC-6 verified (see master plan)

**Phase 6 complete** — run full regression + update Serena `services/*.md` + KG backfill.
