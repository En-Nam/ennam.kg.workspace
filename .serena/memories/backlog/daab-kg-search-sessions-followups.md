# Backlog — kg_search_sessions follow-ups

Filed 2026-06-29 after shipping `kg_search_sessions` (DAAB session/conversation search). Branch `task/implement_docs_sync`, HEAD `0e0523a`. Plan: `docs/superpowers/plans/2026-06-29-daab-kg-search-sessions.md` §10 + final-review notes.

## Deferred from spec §10 (contract-stable v2)
- **Semantic + hybrid (RRF):** add embedding-based recall and reciprocal-rank-fusion over the FTS path. The MCP tool contract (`kg_search_sessions`) was designed opaque so this lands without a breaking change.
- **Trigram / CJK:** pg_trgm fallback + CJK tokenization for non-space-delimited queries (current `simple` config is whitespace-tokenized).
- ~~**Cross-user `monitoring` scope:**~~ **DONE 2026-06-29** (verified 2026-07-07 by reading source, not just report). Decision + threat model: `mem:decisions/monitoring-scope-kg-search-sessions`. Implemented: handler gate (`internal/handler/session_search.go`), SQL project-bound collapse (`internal/store/thread_message.go`), `kg_audit_log` (migration 000073), MCP bridge schema + route, full test coverage (admin/non-admin/project-boundary/Phase3). Remaining unknown: whether a human security-review sign-off happened (checklist's last item) — not verifiable from source alone. LAAM-side actual consumption not yet confirmed (out of this repo).
- **`response_blocks` indexing:** index structured assistant response blocks, not just `thread_messages.content`.
- ~~**Archived-thread filter:**~~ **DONE 2026-06-29** — `include_archived` bool (default false: archived excluded). Store `SessionSearchParams.IncludeArchived` + inlined `AND t.is_archived = false` clause (both count & page queries); handler `include_archived` field; bridge schema `include_archived` property. ⚠️ BEHAVIOR CHANGE: archived threads were previously returned; now excluded by default. Tests: 2 unit (handler forward) + 2 integration (g/h: excluded by default, returned on opt-in). Done pre-adoption so the default flip is safe.
- **Accented snippets:** v1 `ts_headline` runs on `f_unaccent(content)` so snippets are diacritic-stripped — restore original-accent snippets (documented accepted v1 limitation).

## From final whole-branch review (non-blocking behavioral notes)
- **REST role validation:** the REST handler accepts an unknown `role` value as "no filter" (the MCP bridge enum guards the MCP path). Consider 400 on unrecognized `role` at the REST layer for symmetry. `internal/handler/session_search.go` + `internal/store/thread_message.go` (`roleActive` gate).
- **Write-path coupling:** the generated `search_vector` column couples every `thread_messages` INSERT/UPDATE to `to_tsvector('simple', f_unaccent(content))`; a pathological message (tsvector ~1MB lexeme limit) would fail message creation, not just search. New failure mode on a core write path — low probability, worth awareness/monitoring.

## Migration ops note
`000072_thread_messages_fts.up.sql` does a full-table rewrite (ACCESS EXCLUSIVE) + non-CONCURRENTLY index. A deployment-note comment was added in-file. If `thread_messages` is large in prod, split into ADD COLUMN / backfill / `CREATE INDEX CONCURRENTLY` (separate non-transactional migrations) before deploy.

Related: `mem:backlog/agent-context-retention-followups`.