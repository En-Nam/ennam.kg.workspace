# Backlog: DAAB doc-sync — future Option B (shared Supabase registry)

**Status:** DEFERRED (not chosen). Current build = **Option A** (AAAA integrations endpoint), spec `docs/superpowers/specs/2026-07-15-daab-doc-sync-planA-aaaa-endpoint-design.md`.

## Why A now, not B
Verified 2026-07-15 (2-agent grounding): AAAA's `documents` **metadata table is in AAAA's OWN Postgres (`am_ai_db`, Prisma), NOT on Supabase**. Only the Storage **bucket** `documents` (binaries) + auth are on Supabase. CTO's "Supabase đã có document table" = bucket≠table conflation. So a shared-Supabase VIEW (B) has nothing to select from — not buildable without relocating/mirroring AAAA's business DB. See `mem:decisions/ecosystem-direction-cto-approved-2026-06-24`.

## Trigger to revisit B (BOTH must hold)
1. Org **deliberately commits** to Supabase-as-shared-data-plane (not just shared auth — today Supabase is identity-plane only; DAAB keeps its own PG+pgvector).
2. **≥2 consumers** need cross-platform doc metadata (LAAM + system #3), so a hub beats point-to-point.

## How to do B when triggered (the RIGHT way)
- **Do NOT** relocate AAAA's internal `documents` table (heavy FK cluster: users/projects/analyses/investors) — breaks referential integrity.
- Create a **purpose-built shared registry table** on Supabase (projection: `document_id, project_id, file_name, doc_type, content_hash, status, file_path, updated_at`), populated by AAAA on analyze-complete via **reliable dual-write (outbox/Inngest retry) + one-time backfill**.
- Grant DAAB a scoped read role via a **`security_invoker` VIEW** (avoid RLS-bypass footgun) + a **Storage RLS policy** for DAAB's principal on bucket `documents` (so DAAB self-serves signed URLs).
- DAAB change = **swap adapter only**: add `SupabaseViewDocSource` impl of `DocSourceClient`; ingest/OCR/chunk/graph untouched. Contract columns + idempotency key `(document_id, content_hash)` are already identical to Option A → no re-ingest churn.

## Costs B carries (why it's not free)
Dual-write consistency (2 DBs → drift), backfill, second source of truth, storage-policy credential surface on DAAB. Only worth it as a considered platform bet, not for one consumer.

## Adapter seam (already built in A — makes the swap cheap)
`ingestion/adapters/doc_source.py` `DocSourceClient` Protocol: `list_documents`, `get_signed_urls`, `download`. A = `AaaaHttpDocSource`; B = `SupabaseViewDocSource`. System #3 = its own impl.
