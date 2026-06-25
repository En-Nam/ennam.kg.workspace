# Session close handoff — 2026-06-24 (DAAB direction + BA-031/033 + memory-of-record)

Long session. Everything below is durable (committed+pushed / in Serena memory).

## Shipped this session (committed + PUSHED, branch task/implement_mcp)
- **BA-033 Slice 1** (chunk-sim retrieval): built; ship-gate **NO-GO** → built-but-gated. Spec+plan `docs/superpowers/{specs,plans}/2026-06-24-ba033-slice1-*`.
- **BA-031 graph cleanup (3 fixes)**: MarkDocResolved status-flip; chain-resolution drain (244 errors→0); batch-verify default 1→6 (G2 re-validated batch=6: precision 1.000/recall 0.917). Go `de4fabe` (incl. merged origin/main `21e3044`, 6 CI commits, 0 conflict), Python `e5cf2e4`.
- **Memory-of-record P0** — ✅ **DEPLOYED + VERIFIED end-to-end** this session. `agent_context` + `agent_context_embeddings` (migration 000068), `kg_remember`/`kg_recall` MCP+REST, hybrid RRF recall, dedicated embed queue + worker consumer. Go commits `d24abec..de4fabe`, Python `e5cf2e4` (pushed). Smoke-tested live: remember→worker embed→recall returns the memory.
  - **Deploy-gap caught+fixed:** worker was running pre-commit code (built 05:16Z, consumer commit 09:14Z) → embed queue not consumed → semantic recall dead. Fixed by `docker compose up -d --build worker`. Lesson (recurring this session): committed ≠ deployed; rebuild worker/server after Python/Go commits.

## Decisions (Serena)
- `mem:decisions/ecosystem-direction-cto-approved-2026-06-24` — CTO-APPROVED direction + **OCR confirmed needed** (Supabase stores binary PDFs; DAAB doc-sync = hybrid pypdf/OCR + VN-normalize). CTO doc: `docs/daab-ecosystem-direction-2026-06-24.md`.
- `mem:decisions/ba033-slice2-deferred` — Slice 2 (community) deferred (sparse graph after concept-exclusion, no consumer, no corpus).
- `mem:decisions/ecosystem-hermes-allocation` — DAAB = keystone memory owner; AAAA/LAAM thin consumers.

## Greenlit roadmap (next, in order)
1. **Consumers adopt `kg_recall`** — AAAA + LAAM (their work) → realises P0 value.
2. **DAAB fast-follow: Supabase identity → user-scope** — gated on AAAA Supabase login (the "D3" for memory-of-record Option-1 user_id; slice shipped project/agent-scope, user_id nullable).
3. **DAAB doc-sync** — pull binary PDF from Supabase Storage (S3) → hybrid pypdf/OCR (PaddleOCR front-runner, verify VN diacritics) → VN-normalize → chunk → graph + back-link. Seeds the real corpus.
4. **BA-033 retrieval/Slice 2** — deferred until doc-sync seeds a coherent corpus → re-measure density + falsifiability gate.

## Memory-of-record P1 follow-ups (not in this slice — confirm)
- Always-runs capture checkpoint (DON'T piggyback Gate-2 → silent amnesia). Recall ranking + **retention/growth-bound**. **Cross-platform RBAC isolation proof** (threat-model + test; cross-project test exists `31c26ae`, cross-platform needs Supabase identity).

## Known issues / ops (carry forward)
- **Lexical FTS uses 'english' tsconfig** → Vietnamese content matches poorly on non-exact tokens (semantic is primary path; flag if leaning on lexical).
- Embed service cold-start ~25s > server timeout → first query 502 (affects /search too). Pre-warm / raise timeout.
- merge_cli benchmark seeds `created_by='ba031-benchmark'` rows → delete before measuring real graph stats.
- **Deploy discipline:** rebuild kg-server (Go) / worker (Python) after commits — running containers go stale; verify via route 400-not-404 + worker queue-listen logs.
- Dev: API http://localhost:8082; admin login admin/Admin123!@# → api_key. kg_remember/kg_recall need a **project-scoped key with default_project_id** (admin key has no default → "no project context"); create via POST /api/v1/api-keys {developer_name, role:"agent", project_ids, default_project_id} → plaintext in `plaintext_key`.
