# Checkpoint: daab-ingestion-fix — 2026-07-13 (session B)

## What was done
- **Tested FR-001 auto-population with a REAL new deal** (user's demand signal, resolving the "no deals flowing" discipline concern). Created project **Sala Food** (`b9a4d353-2bd9-458f-a78a-eb3b54998706`) in DB, ingested 15 M&A PDFs from `doc_pdf_test/project_2` via `POST /api/v1/projects/{id}/ingest/upload`.
- **Diagnosed B (ingestion pipeline silent-failure)** — every doc reported `status=approved`, pipeline `errors=0`, but produced 0 sections / 0 chunks / 0 embeddings / 0 similar_to. Documented in `mem:backlog/daab-ingestion-pipeline-silent-failures`.
- **Root-caused (surprise):** NOT the Python truncation (it already caps `summary[:8000]` code points). It was a **byte-vs-rune bug in the Go validator** `internal/service/node.go:validateFieldValue` — used `len()` (bytes) against `max_length`/`min_length` which config documents as CHARACTER limits. Vietnamese multi-byte → 8000-rune summary (~9365 bytes) rejected → section create 400 → 0 sections → 0 chunks → 0 embeddings. Affects ALL Vietnamese text fields near their limit.
- **Fixed (commit `9f7f5b7`):** `len()` → `utf8.RuneCountInString`. TDD unit test `TestValidateFieldValue_MaxLengthCountsRunesNotBytes` (RED→GREEN). Rebuilt + redeployed daab-server from branch (`docker compose build kg-server && up -d`) — also brought the ef_search fix `fc9afa6` LIVE on :8082.
- **Verified end-to-end** on a fresh Sala re-ingest: pipeline `sections=1 embeddings=10/11`/doc; DB document_chunk 124/124 embedded, document_section 65/65 embedded; linker → 85 similar_to edges; `POST /api/v1/retrieve/graph` returns real cross-document results (seed_relevance ~0.87). Full FR-001 loop ingest→embed→link→retrieve works on a new deal.

## Commits on task/implement_docs_sync (this + prior session)
- `fc9afa6` feat: raise HNSW ef_search on graph-retrieve chunk seeds (seed-scoped WithEfSearch).
- `9f7f5b7` fix: count characters (runes) not bytes in node field length validation.

## Current state
- daab-server :8082 = rebuilt from branch (BOTH fixes live).
- Sala Food (`b9a4d353…`) has MIXED data (leftover queued docs from the first broken run + 3 clean re-ingested). For a clean corpus: delete project data + re-ingest all 15 (planned next as step "b").
- Working tree clean (both fixes committed).

## Next steps (user-approved order: a then b)
- **a) Fix 2 (fail-loud)** — stop swallowing section/chunk/embedding failures in `decompose.py`; count them, surface in PipelineBatchResult, don't mark a 0-substrate draft "approved". **Fix 4 (auto-link)** — auto-trigger `POST /api/v1/internal/graphrag/link` after a project's chunk embeddings complete (currently manual).
- **b) Clean re-ingest all 15 Sala docs** on the fixed pipeline for a clean corpus.
- Fix 3 (read-path 403 "load architecture nodes") = the key-creation-auto-default bug, already tracked in `mem:backlog/daab-agent-context-project-resolution-bug`. Orthogonal to substrate.

## Blockers / Risks
- ⚠️ Cleanup debt (unchanged): revoke test API keys (incl. the global-admin `ennam_kg_e953…` used for ingest), rotate leaked daab-postgres dev password.
- The 4 XLSX files in project_2 were not ingested (PDF-only path); check whether the extract path supports XLSX if the deal needs them.
