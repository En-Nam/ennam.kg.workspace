# Checkpoint: fuzzy-hub merge drain — 2026-07-03

## What was done
- Reviewed + fixed fuzzy-hub plan (fakeApplier compile-break, no main.go change) — committed.
- Committed + pushed Plan B (python LLM adjudication) + D (SSE race) across repos; deleted 7 CSV/.numbers analysis artifacts + gitignore rule.
- Rebuilt full docker stack; migration 000075 (`review_cleared`) verified live (version 75, dirty=f).
- **Executed fuzzy-hub drain on project 592c7ff7-9f6f-4cc5-9094-d9b3b685277e:**
  - `hub_partition_cli` dry-run: 4044 needs_review → 897 typo (de-diacritic equal) / 3147 danger.
  - Flipped 897 → `review_cleared`; read-only manifest preview: 666 groups, 1 group at ceiling (degree 43).
  - Applied via `POST /api/v1/internal/resolution/apply-review-cleared` (temp KG_AUTH_NOOP=true, dummy bearer, restored to false after).
  - Result: **applied=896, needs_review=1** (hub degree 43 route-back). review_cleared=0.

## Current state (verified)
- decision breakdown 592c: applied=7233, needs_review=3148, review_cleared=0.
- merged_into nodes=4137 (cumulative), superseded_by_merge edges=590.
- Auth restored KG_AUTH_NOOP=false (401 no-header confirmed). Stack healthy.
- Server host port is **:8082** (compose maps 8082->8080), NOT 8080.

## Next steps
- **3148 danger stratum** still parked — needs a separate human-review strategy (per-canonical, keeps diacritics). Not auto-clearable by design.
- PR merge task/implement_docs_sync → main (B + D + fuzzy-hub across 5 repos).
- /graph will now show ~896 fewer duplicate nodes — user may want to refresh.
- Next feature candidate: BA-033 slice 2 (kg_recall retriever, ecosystem keystone).

## Blockers / Risks
- None. Merges reversible via merge_undo. Auth endpoint requires Authorization header even under noop (middleware extractAPIKey gate).
