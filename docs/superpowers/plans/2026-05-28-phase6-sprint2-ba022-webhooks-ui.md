# Phase 6 Sprint 2: BA-022 Admin UI + Settings — Implementation Plan

> **Parent:** [`2026-05-28-phase6-master.md`](2026-05-28-phase6-master.md) · **Requires:** Sprint 1 merged
>
> **Scope note (2026-05-28):** Jira/GDrive webhooks **deferred** — Sprint 2 MVP = Knowledge Sources UI + ingestion settings + auto-approve cho upload/public API.

**Goal:** NextJS "Knowledge Sources" tab, migration 053 ingestion settings, auto-approve path cho `local_upload` và `satellite_api`.

---

## Go — Auto-approve (FR-006, scoped)

**Files:** Modify `internal/service/draft_node.go`

Sau upsert từ upload hoặc public ingest:

1. Nếu request có `auto_approve=true` → approve với `approved_by=system:auto_approve`
2. Hoặc connection `local_upload` / `satellite_api` có `config.auto_approve=true`
3. Filter: `max_file_size_bytes`, `content_formats` (bỏ `issue_types`, `folder_ids` — chỉ dùng khi Phase 6.1)
4. Nếu `ingestion.auto_queue_processing=true` → gọi ProcessBatch

**Không làm trong sprint này:** webhook auto-approve (chưa có webhook).

---

## Migration 053 — ingestion settings

**Files:** `db/migrations/000053_seed_ingestion_settings.up.sql`

Seed 6 keys từ BA-022 FR-007 (`ingestion.max_upload_size_bytes`, `ingestion.max_batch_size`, `ingestion.auto_approve_external`, `ingestion.auto_queue_processing`, `ingestion.webhook_rate_limit_per_minute`, `ingestion.draft_retention_days`).

Webhook rate limit setting giữ seed sẵn cho Phase 6.1; chưa enforce.

---

## NextJS — Knowledge Sources tab

**Files:**
- Create: `src/app/(dashboard)/projects/[projectId]/sources/page.tsx`
- Create: `src/components/sources/draft-list.tsx`, `draft-preview.tsx`, `connection-bar.tsx`, `stats-bar.tsx`
- Modify: project layout tabs — add "Knowledge Sources"

**Features (FR-003, MVP scope):**
- Stats bar: counts by status
- Connection bar: chỉ hiển thị `local_upload` (+ placeholder "Jira / GDrive — coming soon" disabled)
- Draft list: filters (`source_type`, `status`, search), pagination
- Bulk actions: Approve / Reject / Process Selected
- Draft preview drawer: title, content_raw, metadata JSON

**Không làm:** OAuth connect flows, Add Jira/GDrive connection dialog.

**API client:** TanStack Query → BFF → Go `/api/v1/projects/{id}/draft-nodes`.

---

## Sprint 2 Done Checklist

- [ ] Knowledge Sources tab loads drafts from API
- [ ] Bulk approve + process selected works from UI
- [ ] Migration 053 seeded
- [ ] Auto-approve works for upload với `auto_approve=true` (script path)
- [ ] Connection bar shows local_upload only; external sources greyed out

**Next:** Sprint 3 — local upload

**Deferred to Phase 6.1:** Webhooks, WebhookConsumer Python stub — xem [`2026-05-28-phase6-sprint4-ba023-jira-gdrive.md`](2026-05-28-phase6-sprint4-ba023-jira-gdrive.md)
