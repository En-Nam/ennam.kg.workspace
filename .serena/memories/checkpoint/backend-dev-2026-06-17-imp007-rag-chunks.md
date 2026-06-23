# Checkpoint: backend-dev — 2026-06-17 (IMP-007 RAG Chunk Retrieval)

## What was done
- Implemented the full IMP-007 plan (RAG chunk retrieval layer) via subagent-driven development: per-task implementer + spec/quality review, then a final whole-branch review per repo.
- Go (ennam.kg.go, 12 commits, bdc181c..dff77c0): migration 000059 document_chunk; config node_types + edge_whitelist + search block; NodeTypeDocumentChunk const/ValidNodeTypes; kg_search allowlist; document_id filter on FTS + SemanticSearch; POST /api/v1/search-chunks (chunk-scoped hybrid RRF + fail-soft + document_id); MCP kg_search_chunks (35 schemas / 33 routes).
- Python (ennam.kg.python, 7 commits, aeefdc0..06391c6): chunker.py (paragraph-first, token-capped to e5 512, deterministic chunk_key); decompose wiring (chunk nodes + contains_section edges + embeddings); idempotent POST /api/v1/admin/backfill-chunks (create/update/skip, no delete); eval harness --target chunks.
- Gate decision: build-first, eval-as-proof (PO).

## Files changed
- Go: db/migrations/000059_*; config/config.yaml; internal/config/types.go(+test); internal/handler/search.go; internal/store/search.go(+test), node_embedding.go(+test); internal/handler/search_chunks_test.go, document_chunk_smoke_test.go; internal/bridge/schema.go, client.go (+ their tests); internal/filter/validate_test.go.
- Python: src/ennam_kg/ingestion/pipeline/chunker.py(+test); decompose.py(+test); api/admin.py(+test); tests/eval/retrieval_eval.py.
- Docs: spec §11 results note; SDD ledger at .git/sdd/progress.md.

## Current state
- Go full suite GREEN (-race). Python 324 passed / 17 skipped. Both final reviews → merge.
- LIVE E2E passed (rebuilt stack): backfilled 22 document_chunk nodes + embeddings; kg_search_chunks fulltext/hybrid/semantic + document_id filter (bogus id → 0 = predicate proven live); re-backfill 0/22 idempotent; section search no-regression.
- Live bug found & fixed: /query 500 for document_chunk (missing config.yaml search block) → fixed + regression test.
- Final-review bug fixed: backfill `updated` counter incremented on update_node failure → now re-raises (Python 06391c6).
- Throwaway E2E project "IMP-007 E2E throwaway" (id b407230c...) left in dev DB (no hard node delete; archive endpoint returned 405/500 — pre-existing, unrelated).
- Stack was rebuilt (docker compose up -d --build) and is running new code; postgres at migration v59.

## Next steps
- Optional: create PRs / merge the two subrepo branches (task/implement_mcp) — NOT done; awaiting user decision (outward-facing).
- Deferred follow-ups: formal 25–30 labeled recall@5/MRR benchmark; orphan-chunk deletion needs a node hard-delete API; decompose-on-upload async path live-proof (currently transitive via shared code + unit tests).

## Blockers / Risks
- None blocking. expected_version fallback-to-1 in backfill can 409 if a chunk is updated >once and /query drops version (logged loudly, documented).

## Addendum (FR-4 benchmark + cleanup)
- Committed+pushed IMP-006 file openai_direct_client.py (reasoning_content fallback) → python 04b6048.
- FR-4 benchmark RUN: ingested both cang-dinh-an reports via REAL upload→decompose (proves Task 5.1 live) → 122 sections + 154 chunks. 15 VI labeled pairs. recall@5 — fulltext: section 0.800 / chunk 1.000; semantic: 0.800 / 0.867; hybrid: 0.933 / 0.933. Chunks match-or-beat sections, no regression. Finding: this markdown decomposes into short sections (all snippets within first ~1500 chars) so tail-recall benefit is modest HERE; chunk layer's payoff is largest on few-long-section docs. Recorded in spec §11.
- dataset.json reverted to template (throwaway labels not committed); harness code already committed.
- DB cleanup: deleted both throwaway projects + all KG data (nodes/edges/embeddings/versions/drafts/uploads) via scoped psql. Did NOT touch audit_trail (safety guard + correct). Verified 0 leftover, 8 other projects intact, endpoints live.
- Source repos clean & pushed: Go dff77c0, Python 04b6048.
