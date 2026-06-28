# Checkpoint: backend-dev — 2026-06-28

## What was done

Implemented the full RBAC Isolation Keystone Gate plan (`docs/superpowers/plans/2026-06-28-rbac-isolation-keystone-gate.md`) via subagent-driven development.

**Task 1 (commit 73ca225):** Store — closed the neighbor NODE cross-project leak
- Added `AllowedProjectIDs []string json:"-"` and `RestrictToAllowed bool json:"-"` to `NeighborParams`
- Added n.project_id filter to BOTH main query and count query in `buildNeighborQuery`
- New test: `internal/store/neighbors_isolation_test.go` — `TestGetNeighbors_DoesNotLeakCrossProjectNode` (3 assertions: same-project no leak, cross restricted-to-A no leak, cross restricted-to-AB B appears)

**Task 2 (commit 5dc3320):** Handler — plumbed caller identity into neighbor queries
- Added `resolveNeighborProjectScope(ctx) (restrict, allowed)` pure helper in `internal/handler/neighbors.go`
- Wired into `HandleGetNeighbors` after `requireProjectAccess` guard
- New test: `internal/handler/neighbors_isolation_test.go` — 3 sub-tests covering scoped/admin/nil

**Task 3:** Regression-lock tests — pre-existing in `recall_isolation_test.go` (commit 6ceda27). All 31 isolation unit tests PASS.

**Task 4:** Full isolation suite run (all PASS except pre-existing `TestSectionNeighbors_ParentChildrenSiblings` chk_title_min_length issue, unrelated). Verdict recorded in Serena memory `decisions/daab-rbac-isolation-keystone-gate-verdict`.

## Files changed

- `ennam.kg.go/internal/store/neighbors.go` — NeighborParams + node filter in main + count
- `ennam.kg.go/internal/store/neighbors_isolation_test.go` — NEW
- `ennam.kg.go/internal/handler/neighbors.go` — resolveNeighborProjectScope + handler wiring
- `ennam.kg.go/internal/handler/neighbors_isolation_test.go` — NEW

## Current state

- Branch: `task/implement_docs_sync`
- HEAD of ennam.kg.go: `5dc3320`
- All target tests passing
- Final review: PASS, Ready to merge
- Minor gap noted: admin-all path not tested at store level (low risk, follow-up)

## Next steps

- Merge `task/implement_docs_sync` into main when ready
- Optional follow-up: add `RestrictToAllowed=false` store-level test for admin-all path
- Optional follow-up: `knowledge_nodes.user_id` migration for user-vs-user isolation (separate issue, not blocking ecosystem consumers)

## Blockers / Risks

- None. The keystone gate passes. Ecosystem work (AAAA/LAAM) is unblocked at project-level isolation.
