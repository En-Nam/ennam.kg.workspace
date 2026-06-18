# Phase 6 Sprint 4: BA-023 Jira + Google Drive — DEFERRED

> **Status:** ⏸ **Không triển khai trong Phase 6 MVP** (quyết định 2026-05-28)
>
> **Parent:** [`2026-05-28-phase6-master.md`](2026-05-28-phase6-master.md)

Jira và Google Drive được hoãn sang **Phase 6.1** (hoặc sprint riêng khi có nhu cầu). Phase 6 MVP chỉ gồm:

- Local upload
- Public Ingestion API + MCP
- Draft workflow + AI pipeline (cross-source với DB schema hiện có)

---

## Phạm vi hoãn (không làm bây giờ)

| Hạng mục | BA |
|----------|-----|
| OAuth Jira / GDrive (Go + BFF) | BA-023 |
| Webhook receivers Jira / GDrive | BA-022 FR-004 |
| Python adapters `jira.py`, `gdrive.py` | BA-023 |
| Migration 050 (oauth_tokens per project) | BA-022/023 |
| Redis queues `ennam:webhooks:jira`, `ennam:webhooks:gdrive` | BA-022 |
| Edge types `jira_*`, `folder_contains` (có thể seed sẵn trong 052, không dùng) | BA-024 |

---

## Khi bật lại Phase 6.1

1. Chạy plan này như Sprint 4 gốc (OAuth → adapters → webhooks)
2. Bổ sung Sprint 2 webhook section (đã gỡ khỏi MVP)
3. Migration 050 nếu chưa apply
4. Cập nhật success criteria SC-3, SC-4, SC-7 trong master plan

**Plan gốc (reference):** git history của file này trước 2026-05-28.
