# Checkpoint: subagent-driven-retrieval-token-efficiency — 2026-07-13

## What was done
- Implemented `docs/superpowers/plans/2026-07-13-daab-retrieval-token-efficiency.md` end-to-end using superpowers:subagent-driven-development: fresh implementer subagent per task, task-scoped reviewer per task, 2 fix loops for review findings, then 2 independent whole-plan final reviews (user explicitly asked for "kiểm tra lần 1" + a second re-check).
- Part A: `kg_graph_retrieve` gained opt-in `include_snippet` (project-scoped `ChunkContentByIDs` store method, batch-fetched null-discriminated rune-safe-truncated snippet inlining) + unconditional `title` on `entity_neighbors`.
- Part B: `kg_get_neighbors` gained opt-in `view=slim` (frozen 9-field projection) + an `edge_id ASC` paging tie-break fix for tied `edge_created_at` rows.
- Both bridge tool schemas (`kg_graph_retrieve`, `kg_get_neighbors`) extended in-place; bridge invariant held (47 schemas, zero net new tools) end to end.
- Live-smoked `view=slim` against the running dev stack (docker, `air` live-reload — no rebuild needed): slim vs full byte reduction confirmed on a real node, invalid `view` → 400, default unchanged, paging tie-break shows zero overlap across offset pages. `include_snippet` could NOT be live-smoked (sandbox has no embedding-provider credentials — "embedding service unavailable"); relied on Tasks 1-4's reviewed unit/integration tests instead (real Postgres, `-race`).
- 2nd final review pass directly re-ran all DB-dependent acceptance-gate tests (incl. the security-critical cross-project isolation test) against live Postgres itself, rather than trusting prior reports — all passed.
- Marked backlog gap #3 in `mem:backlog/daab-retrieval-quality-gaps-postfix` as RESOLVED.

## Files changed (ennam.kg.go, nested git repo)
- `internal/store/graph_retrieve.go` (+test) — `ChunkContentByIDs`, `SharedEntityNeighbors` gains `title`
- `internal/service/graph_retriever.go` (+test) — `IncludeSnippet`/`Result.Snippet`/`ContentReader`/`WithChunkContent`, `EntityResult.Title`
- `internal/handler/graph_retrieve.go` (+test) — `include_snippet` request field
- `internal/handler/neighbors.go` (+test) — `view=slim` projection, `toSlimNeighborResponse`
- `internal/store/neighbors.go` (+test, new file `neighbors_paging_test.go`) — `ORDER BY edge_created_at DESC, edge_id ASC`
- `internal/bridge/schema.go` (+test) — `include_snippet` on `kg_graph_retrieve`, `view` on `kg_get_neighbors`
- `cmd/kg-server/main.go` — wires `WithChunkContent(graphRetrieveStore)`

## Current state
Branch `task/implement_docs_sync` in `ennam.kg.go`, HEAD `3714904` (was `d1d24ce` at plan start). All 7 tasks complete, all reviews clean (0 Critical/Important across every task review + both final passes). Working tree clean, nothing left uncommitted. NOT pushed, NOT merged — awaiting user decision on next step (PR / merge / continue on branch).

## Next steps
- User may want to push/PR this branch, or continue with other backlog items (gaps #4-7 in the retrieval-quality-gaps memory still open).
- One-shot live smoke of `include_snippet` recommended once embedding-provider credentials are available in a test environment (noted as a Recommendation in both final reviews, not a blocker).
- Optional non-blocking cleanup noted by reviewers: pre-existing (not branch-introduced) gofmt misalignment in `neighbors.go`/`schema.go`; bridge `include_snippet` description could clarify the 4KB truncation cap.

## Blockers / Risks
None outstanding. Ledger at `.superpowers/sdd/daab-retrieval-token-efficiency-progress.md` has full task-by-task detail if resuming or auditing later.
