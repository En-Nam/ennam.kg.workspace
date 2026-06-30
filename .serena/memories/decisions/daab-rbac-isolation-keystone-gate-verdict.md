# RBAC Isolation Keystone Gate — VERDICT: PASS

**Date:** 2026-06-28
**Plan:** `docs/superpowers/plans/2026-06-28-rbac-isolation-keystone-gate.md`
**Branch:** `task/implement_docs_sync`
**Commits:** fb69001 (base) → 73ca225 (Task 1) → 5dc3320 (Task 2)

## Status: GATE PASSES

All 7 audited cross-project read paths are now closed or accounted for:

| Path | Status | Notes |
|------|--------|-------|
| 1. Search body-override | ✅ LOCKED | `requireProjectAccess` guard; regression test: `TestSearch_ForeignProjectInBody_Forbidden` |
| 2. cross_project_ids | ✅ LOCKED | same guard; regression test: `TestSearch_CrossProjectIDs_Forbidden` |
| 3. History IDOR | ✅ LOCKED | `requireNodeProjectAccess` (404); regression tests in `recall_isolation_test.go` + integration |
| 4. Document IDOR | ✅ LOCKED | same `requireNodeProjectAccess`; `GetDocumentStructure` + `GetSectionContent` both guarded |
| 5. Neighbors NODE leak | ✅ FIXED | Task 1 (store) + Task 2 (handler); `TestGetNeighbors_DoesNotLeakCrossProjectNode` PASS |
| 6. Admin-all / NOOP | ✅ BY-DESIGN | `Role==Admin && len(ProjectIDs)==0` = unrestricted; `identity==nil` = unrestricted |
| 7. User-vs-user | ⚠️ KNOWN GAP | Requires `knowledge_nodes.user_id` migration (separate follow-up; out of scope) |

## Key changes (Tasks 1–2)

**Task 1 — Store (`internal/store/neighbors.go`):**
- Added `AllowedProjectIDs []string json:"-"` and `RestrictToAllowed bool json:"-"` to `NeighborParams`
- Added neighbor-NODE project filter to BOTH main query and count query in `buildNeighborQuery`
- Filter: `!IncludeCrossProject` → `n.project_id = $N`; `RestrictToAllowed` → `n.project_id = ANY($N)` with `pq.Array`

**Task 2 — Handler (`internal/handler/neighbors.go`):**
- Added `resolveNeighborProjectScope(ctx) (restrict bool, allowed []string)` pure helper
- Admin-all (Role==Admin && len(ProjectIDs)==0) → restrict=false; nil identity → restrict=false; scoped key → restrict=true, allowed=key.ProjectIDs
- Called after `requireProjectAccess` guard in `HandleGetNeighbors`; feeds into `NeighborParams`

## Test evidence (2026-06-28)

```
TestGetNeighbors_DoesNotLeakCrossProjectNode: PASS (3 sub-assertions)
TestResolveNeighborProjectScope: PASS (3 sub-tests)
All handler Neighbor tests: PASS
Recall isolation tests: PASS (31 tests)
Pre-existing failure: TestSectionNeighbors_ParentChildrenSiblings (chk_title_min_length fixture issue, unrelated)
```

## Ecosystem unblock

Project-level RBAC isolation is complete. Consumer-facing ecosystem work (AAAA/LAAM) is **unblocked** for project-level isolation.

**Remaining gap:** User-level isolation (user A vs user B within the same project) requires a `knowledge_nodes.user_id` column migration — separate follow-up, only needed for multi-user-within-one-project tenancy. Not blocking ecosystem consumers today.

Links: `mem:ecosystem-hermes-allocation` `mem:global/ecosystem/daab-plan`
