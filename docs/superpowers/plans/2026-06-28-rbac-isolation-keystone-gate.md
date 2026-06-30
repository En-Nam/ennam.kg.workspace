# RBAC Isolation Keystone Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the last open cross-project read path (neighbors) and lock all recall paths with a regression gate, so the DAAB shared-memory keystone passes RBAC isolation and ecosystem consumers (AAAA/LAAM) can be unblocked.

**Architecture:** A 2026-06-23 audit found 7 cross-project read paths. A 2026-06-28 re-audit (this plan's basis) found **only the neighbors path still open** — paths 1–4 are now guarded by `requireProjectAccess`/`requireNodeProjectAccess`, traversal is safe, admin-all is by-design, user-scoping is N/A (no `user_id` column). The neighbors store filters the **edge** project but never the **neighbor node** project, so a cross-project edge leaks the foreign node (and `include_cross_project=true` drops even the edge filter). Fix = bound neighbor NODE rows to the caller's authorized project set, at the store SQL layer, with the allowed set plumbed from the handler's authenticated identity.

**Tech Stack:** Go (stdlib `net/http`, `database/sql`, `github.com/lib/pq`), PostgreSQL 16, `go test -race`. Repo: `ennam.kg.go`.

## Global Constraints

- All work in repo `ennam.kg.go` on branch `task/implement_docs_sync` (or a fresh branch off it).
- DB-backed tests require `KG_TEST_DATABASE_URL`; dev value: `postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable`. Tests must `setupTestDB(t)` (skips when unset).
- Match existing store-test fixture helpers in package `store_test`: `mustCreateProject(t, db, name) string`, `mustCreateNode(t, db, projectID, nodeType) string`, `insertEdge(t, db, projectID, sourceID, targetID, edgeType)` (all in `internal/store/graph_retrieve_test.go`).
- Node type `concept` violates a CHECK constraint with empty properties — use `discovery` as a stand-in concept node in fixtures.
- Identity injection in handler tests: `context.WithValue(r.Context(), middleware.DeveloperIdentityKey, &middleware.DeveloperIdentity{...})`.
- Admin-all semantics (must preserve): `Role == models.APIKeyRoleAdmin && len(ProjectIDs) == 0` reads all projects by design. `identity == nil` (KG_AUTH_NOOP / internal) is unrestricted by existing convention.
- Commit message format: `<type>: <description>` (no attribution trailer).

---

## File Structure

- `internal/store/neighbors.go` — add neighbor-node project filter to `buildNeighborQuery` (main + count); add 2 fields to `NeighborParams`.
- `internal/store/neighbors_isolation_test.go` (NEW) — DB-backed store tests proving the leak is closed.
- `internal/handler/neighbors.go` — compute `RestrictToAllowed`/`AllowedProjectIDs` from identity, pass into params.
- `internal/handler/neighbors_isolation_test.go` (NEW) — handler test proving identity → params plumbing.
- `internal/handler/recall_isolation_test.go` (NEW) — consolidated regression-lock asserting the already-fixed paths (search body-override, history IDOR, document IDOR) stay guarded.

---

## Task 1: Store — neighbor-node project filter (closes the leak)

**Files:**
- Modify: `internal/store/neighbors.go` (`NeighborParams` struct ~line 39; `buildNeighborQuery` main project filter ~line 209-218 and count project filter ~line 330-336)
- Test: `internal/store/neighbors_isolation_test.go` (new)

**Interfaces:**
- Consumes: `store_test` fixture helpers (see Global Constraints); `store.NeighborStore.GetNeighbors(ctx, NeighborParams) (*NeighborResponse, error)`; `NeighborResponse.Neighbors []NeighborNode`; `NeighborNode.ProjectID string`.
- Produces: `NeighborParams.AllowedProjectIDs []string` and `NeighborParams.RestrictToAllowed bool` (consumed by Task 2's handler).

- [ ] **Step 1: Write the failing test**

Create `internal/store/neighbors_isolation_test.go`:

```go
package store_test

import (
	"context"
	"testing"

	"github.com/ennam/ennam-kg/internal/store"
)

// neighborIDs returns the set of neighbor node IDs from a GetNeighbors call.
func neighborIDs(resp *store.NeighborResponse) map[string]bool {
	out := map[string]bool{}
	for _, n := range resp.Neighbors {
		out[n.ID] = true
	}
	return out
}

// WHY: the neighbors store filtered only the EDGE project, never the neighbor
// NODE project. A cross-project edge (owned by project A, pointing at a node in
// project B) leaked B's node to an A-scoped caller. include_cross_project=true
// dropped even the edge filter. This is the last open cross-project read path
// in the RBAC isolation keystone gate.
func TestGetNeighbors_DoesNotLeakCrossProjectNode(t *testing.T) {
	db := setupTestDB(t)
	s := store.NewNeighborStore(db)
	ctx := context.Background()

	projA := mustCreateProject(t, db, "rbac-neighbors-A")
	projB := mustCreateProject(t, db, "rbac-neighbors-B")
	nodeA := mustCreateNode(t, db, projA, "document_section")
	nodeB := mustCreateNode(t, db, projB, "document_section")
	// Cross-project edge owned by project A, pointing A -> B.
	insertEdge(t, db, projA, nodeA, nodeB, "mentions")
	t.Cleanup(func() {
		for _, p := range []string{projA, projB} {
			_, _ = db.ExecContext(ctx, `DELETE FROM knowledge_edges WHERE project_id = $1`, p)
			_, _ = db.ExecContext(ctx, `DELETE FROM knowledge_nodes WHERE project_id = $1`, p)
			_, _ = db.ExecContext(ctx, `DELETE FROM projects WHERE id = $1`, p)
		}
	})

	// NOTE: Direction MUST be set — the store's `switch params.Direction` has no
	// default case, so an empty Direction yields an empty UNION and a broken query.

	// Same-project query (include_cross_project=false): B must NOT appear.
	resp, err := s.GetNeighbors(ctx, store.NeighborParams{
		NodeID: nodeA, ProjectID: projA, Direction: "both", IncludeCrossProject: false, Limit: 50,
	})
	if err != nil {
		t.Fatalf("GetNeighbors same-project: %v", err)
	}
	if neighborIDs(resp)[nodeB] {
		t.Errorf("LEAK: project-B node %q returned to project-A same-project query", nodeB)
	}

	// Cross-project restricted to [A]: B must NOT appear.
	resp, err = s.GetNeighbors(ctx, store.NeighborParams{
		NodeID: nodeA, ProjectID: projA, Direction: "both", IncludeCrossProject: true,
		RestrictToAllowed: true, AllowedProjectIDs: []string{projA}, Limit: 50,
	})
	if err != nil {
		t.Fatalf("GetNeighbors cross restricted-to-A: %v", err)
	}
	if neighborIDs(resp)[nodeB] {
		t.Errorf("LEAK: project-B node %q returned when allowed set is [A]", nodeB)
	}

	// Cross-project restricted to [A,B]: B IS allowed and must appear.
	resp, err = s.GetNeighbors(ctx, store.NeighborParams{
		NodeID: nodeA, ProjectID: projA, Direction: "both", IncludeCrossProject: true,
		RestrictToAllowed: true, AllowedProjectIDs: []string{projA, projB}, Limit: 50,
	})
	if err != nil {
		t.Fatalf("GetNeighbors cross restricted-to-AB: %v", err)
	}
	if !neighborIDs(resp)[nodeB] {
		t.Errorf("project-B node %q must appear when allowed set is [A,B]", nodeB)
	}
}
```

- [ ] **Step 2: Run the test to verify it fails to compile, then fails**

Run: `cd ennam.kg.go && KG_TEST_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable" go test ./internal/store/ -run TestGetNeighbors_DoesNotLeakCrossProjectNode -v`
Expected: compile error — `NeighborParams` has no field `RestrictToAllowed`/`AllowedProjectIDs`.

- [ ] **Step 3: Add the two fields to `NeighborParams`**

In `internal/store/neighbors.go`, inside `type NeighborParams struct` (after the `IncludeCrossProject` field):

```go
	// AllowedProjectIDs bounds which projects a returned neighbor NODE may
	// belong to, used with RestrictToAllowed to enforce cross-project RBAC
	// isolation. Set by the handler from the authenticated caller's scope.
	AllowedProjectIDs []string `json:"-"`

	// RestrictToAllowed, when true, filters neighbor nodes to AllowedProjectIDs
	// (for cross-project queries). When false the node-project restriction is
	// skipped (admin-all keys or unauthenticated/internal callers). Same-project
	// queries are always bounded to ProjectID regardless of this flag.
	RestrictToAllowed bool `json:"-"`
```

- [ ] **Step 4: Add the neighbor-NODE project filter to the main query**

In `internal/store/neighbors.go`, in `buildNeighborQuery`, immediately AFTER the existing edge project-filter block (the `if !params.IncludeCrossProject { ... e.project_id = $argIdx ... }` near line 209-218), add a node-level filter mirroring the same arg-append pattern:

```go
		// Neighbor NODE project filter — the edge filter above bounds only the
		// edge's project, not the neighbor node's. Without this a cross-project
		// edge surfaces a node from an unauthorized project (RBAC isolation leak).
		if !params.IncludeCrossProject {
			conditions = append(conditions, fmt.Sprintf("n.project_id = $%d", argIdx))
			args = append(args, params.ProjectID)
			countArgs = append(countArgs, params.ProjectID)
			argIdx++
		} else if params.RestrictToAllowed {
			conditions = append(conditions, fmt.Sprintf("n.project_id = ANY($%d)", argIdx))
			args = append(args, pq.Array(params.AllowedProjectIDs))
			countArgs = append(countArgs, pq.Array(params.AllowedProjectIDs))
			argIdx++
		}
```

> Note: confirm `github.com/lib/pq` is imported in `neighbors.go` (it is used elsewhere in the store package). If the file does not already import it, add `"github.com/lib/pq"` to the import block.

- [ ] **Step 5: Add the same filter to the count query**

In `internal/store/neighbors.go`, the count query is built separately (the block around line 330-336 using `countArgs2`/`countArgIdx`). Immediately AFTER its existing `if !params.IncludeCrossProject { ... e.project_id = $countArgIdx ... }` block, add:

```go
		if !params.IncludeCrossProject {
			conditions = append(conditions, fmt.Sprintf("n.project_id = $%d", countArgIdx))
			countArgs2 = append(countArgs2, params.ProjectID)
			countArgIdx++
		} else if params.RestrictToAllowed {
			conditions = append(conditions, fmt.Sprintf("n.project_id = ANY($%d)", countArgIdx))
			countArgs2 = append(countArgs2, pq.Array(params.AllowedProjectIDs))
			countArgIdx++
		}
```

> The count query must stay consistent with the main query or pagination totals will mislead. Mirror exactly.

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd ennam.kg.go && KG_TEST_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable" go test ./internal/store/ -run TestGetNeighbors_DoesNotLeakCrossProjectNode -race -v`
Expected: PASS (all three sub-assertions).

- [ ] **Step 7: Run the full store package to check for regressions**

Run: `cd ennam.kg.go && KG_TEST_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable" go test ./internal/store/ -run Neighbor -race -v`
Expected: PASS. (Pre-existing unrelated failure `TestFavoriteStore_Update` may show in a full-package run — ignore; it is not in `-run Neighbor`.)

- [ ] **Step 8: Commit**

```bash
git -C ennam.kg.go add internal/store/neighbors.go internal/store/neighbors_isolation_test.go
git -C ennam.kg.go commit -m "fix(rbac): bound neighbor nodes by project to close cross-project read leak"
```

---

## Task 2: Handler — plumb allowed project set from identity

**Files:**
- Modify: `internal/handler/neighbors.go` (add a pure helper `resolveNeighborProjectScope`; call it in `HandleGetNeighbors` after the `requireProjectAccess` guard and set the two new params fields ~line 200-211)
- Test: `internal/handler/neighbors_isolation_test.go` (new)

**Interfaces:**
- Consumes: `NeighborParams.AllowedProjectIDs`/`RestrictToAllowed` (Task 1); `middleware.GetDeveloperIdentity(ctx) *middleware.DeveloperIdentity` (fields `Role`, `ProjectIDs`); `models.APIKeyRoleAdmin`/`APIKeyRoleDeveloper`.
- Produces: `resolveNeighborProjectScope(ctx context.Context) (restrict bool, allowed []string)` — pure, unit-testable.

> **Design note:** `NeighborHandler.store` is a concrete `*store.NeighborStore` (not an interface), and `NewNeighborHandler(*store.NeighborStore, *slog.Logger)` is called from `cmd/kg-server/main.go`. Do NOT refactor the store field to an interface just to test — that's needless churn (it would change the constructor + its main.go caller). Instead extract the identity→scope mapping into a pure function and unit-test that directly. The store-level DB test in Task 1 already proves the SQL filter works; this task only needs to prove the handler computes the right scope values.

- [ ] **Step 1: Write the failing test**

Create `internal/handler/neighbors_isolation_test.go`:

```go
package handler

import (
	"context"
	"testing"

	"github.com/ennam/ennam-kg/internal/middleware"
	"github.com/ennam/ennam-kg/internal/models"
)

func ctxWithDevIdentity(id *middleware.DeveloperIdentity) context.Context {
	return context.WithValue(context.Background(), middleware.DeveloperIdentityKey, id)
}

// WHY: a project-scoped key that asks for cross-project neighbors must only ever
// receive nodes from projects in its own scope; an unscoped admin key reads all
// by design; an unauthenticated/internal caller (nil identity) is unrestricted
// per the existing requireProjectAccess convention. This pure mapping is what
// the handler feeds into the store's RBAC filter (Task 1).
func TestResolveNeighborProjectScope(t *testing.T) {
	t.Run("scoped key restricts to its own projects", func(t *testing.T) {
		ctx := ctxWithDevIdentity(&middleware.DeveloperIdentity{
			Role: models.APIKeyRoleDeveloper, ProjectIDs: []string{"projA"},
		})
		restrict, allowed := resolveNeighborProjectScope(ctx)
		if !restrict {
			t.Fatal("scoped key: want restrict=true")
		}
		if len(allowed) != 1 || allowed[0] != "projA" {
			t.Errorf("scoped key: want allowed=[projA], got %v", allowed)
		}
	})

	t.Run("unscoped admin is unrestricted", func(t *testing.T) {
		ctx := ctxWithDevIdentity(&middleware.DeveloperIdentity{
			Role: models.APIKeyRoleAdmin, ProjectIDs: nil,
		})
		if restrict, _ := resolveNeighborProjectScope(ctx); restrict {
			t.Error("admin-all: want restrict=false (reads all by design)")
		}
	})

	t.Run("nil identity is unrestricted", func(t *testing.T) {
		if restrict, _ := resolveNeighborProjectScope(context.Background()); restrict {
			t.Error("nil identity: want restrict=false (KG_AUTH_NOOP / internal)")
		}
	})
}
```

- [ ] **Step 2: Run the test to verify it fails to compile**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestResolveNeighborProjectScope -v`
Expected: compile error — `resolveNeighborProjectScope` undefined.

- [ ] **Step 3: Implement the pure helper + call it in the handler**

In `internal/handler/neighbors.go`, add the helper (package-level func):

```go
// resolveNeighborProjectScope maps the authenticated caller to the project set
// their neighbor results may include. restrict=false means unrestricted:
// unscoped admin keys (read-all by design) and unauthenticated/internal callers
// (nil identity), matching the requireProjectAccess convention. Otherwise the
// caller is bounded to the API key's own project scope.
func resolveNeighborProjectScope(ctx context.Context) (restrict bool, allowed []string) {
	id := middleware.GetDeveloperIdentity(ctx)
	if id == nil {
		return false, nil
	}
	if id.Role == models.APIKeyRoleAdmin && len(id.ProjectIDs) == 0 {
		return false, nil
	}
	return true, id.ProjectIDs
}
```

Then in `HandleGetNeighbors`, AFTER the existing `requireProjectAccess` guard, compute the scope and add the two fields to the `store.NeighborParams{...}` literal:

```go
	restrictToAllowed, allowedProjectIDs := resolveNeighborProjectScope(r.Context())
```

```go
		AllowedProjectIDs:   allowedProjectIDs,
		RestrictToAllowed:   restrictToAllowed,
```

> Ensure `internal/handler/neighbors.go` imports `context`, `github.com/ennam/ennam-kg/internal/middleware`, and `github.com/ennam/ennam-kg/internal/models`. `context` and `middleware` may already be present; add `models` if missing.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run 'TestResolveNeighborProjectScope|Neighbor' -race -v`
Expected: PASS (the 3 sub-tests + the existing neighbors handler tests).

- [ ] **Step 5: Build + commit**

```bash
cd ennam.kg.go && go build ./...
git -C ennam.kg.go add internal/handler/neighbors.go internal/handler/neighbors_isolation_test.go
git -C ennam.kg.go commit -m "fix(rbac): plumb caller project scope into neighbor queries"
```

---

## Task 3: Regression-lock the already-fixed recall paths

**Files:**
- Test: `internal/handler/recall_isolation_test.go` (new)

**Interfaces:**
- Consumes: existing handlers `SearchHandler`, history handler, document handler; `requireProjectAccess`/`requireNodeProjectAccess` (already wired). This task adds NO production code — it pins current guards so a future refactor cannot silently reopen paths 1–4.

- [ ] **Step 1: Write the guard-presence tests**

These are lightweight: a project-A-scoped identity must be DENIED when naming project B in the body / by-id. They pass today (paths are fixed); they exist to FAIL loudly if a guard is removed. Create `internal/handler/recall_isolation_test.go`. For each handler, mirror that handler's existing test setup (construct via the same constructor its current `_test.go` uses; inspect the sibling test file for the exact wiring) and assert the denial status:

```go
package handler

// T1 — search body-override: A-scoped key naming project B in the body is 403.
//   Build SearchHandler as in search_test.go; POST {"query":"x","project_id":"projB"}
//   with DeveloperIdentity{ProjectIDs:["projA"]} in context; want 403.
//
// T2 — search cross_project_ids: same setup, body
//   {"query":"x","project_id":"projA","cross_project_ids":["projB"]}; want 403.
//
// T3 — history IDOR: GET history for a node whose ProjectID is "projB" with an
//   A-scoped identity; want 404 (requireNodeProjectAccess hides existence).
//
// T4 — document IDOR: GET /section-content (and /document-structure) for a
//   projB node with an A-scoped identity; want 404.
//
// Each test follows the same shape: build handler, inject DeveloperIdentity via
//   context.WithValue(r.Context(), middleware.DeveloperIdentityKey,
//     &middleware.DeveloperIdentity{Role: models.APIKeyRoleDeveloper, ProjectIDs: []string{"projA"}}),
//   call the handler, assert w.Code.
```

> Implement each of T1–T4 as a concrete `func Test...` using the real constructors and fakes/DB found in the sibling `search_test.go`, `history_test.go`, `document_test.go`. Where a handler needs a store, reuse that test file's existing fake or DB seed. Keep each test to the single assertion: correct denial status for a cross-project attempt.

- [ ] **Step 2: Run — they should PASS immediately (paths already fixed)**

Run: `cd ennam.kg.go && KG_TEST_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable" go test ./internal/handler/ -run Isolation -race -v`
Expected: PASS. If any FAILS, that path is actually open — STOP and treat as a real vulnerability (fix mirrors Task 1/2: guard before returning data).

- [ ] **Step 3: Commit**

```bash
git -C ennam.kg.go add internal/handler/recall_isolation_test.go
git -C ennam.kg.go commit -m "test(rbac): regression-lock search/history/document cross-project guards"
```

---

## Task 4: Record the gate verdict + unblock decision

**Files:**
- Serena memory (via `mcp__serena__write_memory`, NOT hand-edited): update `decisions/daab-hermes-keystone-verification` status, and write the gate result.

**Interfaces:** none (documentation).

- [ ] **Step 1: Re-run the full isolation suite as evidence**

Run: `cd ennam.kg.go && KG_TEST_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable" go test ./internal/store/ ./internal/handler/ -run 'Isolation|Neighbor' -race -v`
Expected: all PASS. Capture the output.

- [ ] **Step 2: Update Serena memory with the verdict**

Use `mcp__serena__write_memory` to record: RBAC isolation gate now PASSES — neighbors leak closed (store-level node-project filter + handler scope plumbing), paths 1–4 regression-locked, traversal safe, admin-all by-design, user-vs-user still requires a `knowledge_nodes.user_id` migration (separate follow-up, only needed for multi-user-within-one-project tenancy). Note that consumer-facing ecosystem work (AAAA/LAAM) is unblocked for project-level isolation; user-level isolation remains a known gap. Link `[[ecosystem-hermes-allocation]]` and `[[daab-hermes-keystone-verification]]`.

- [ ] **Step 3: Commit any tracked doc changes (if a plan/spec file was updated)**

```bash
# Only if a tracked file under docs/ or ennam.kg.requirements/ was edited.
git add -A && git commit -m "docs(rbac): record isolation keystone gate PASS + remaining user_id gap"
```

---

## Self-Review

**Spec coverage (vs the 7 audited paths):**
- Path 1 (search body-override) → Task 3 T1 (regression-lock; already fixed). ✓
- Path 2 (cross_project_ids) → Task 3 T2. ✓
- Path 3 (history IDOR) → Task 3 T3. ✓
- Path 4 (document IDOR) → Task 3 T4. ✓
- Path 5 (neighbors) → Task 1 (store fix) + Task 2 (handler plumbing). ✓ **the only code fix**
- Path 6 (admin-all / NOOP) → preserved explicitly: Task 2 admin-unrestricted test; `identity==nil` unrestricted. ✓
- Path 7 (user-vs-user) → out of scope (needs `knowledge_nodes.user_id` migration); documented as remaining gap in Task 4. ✓
- Traversal (safe) → no change; not re-tested here (CTE already filters every hop). Acceptable.

**Placeholder scan:** Task 3 intentionally describes T1–T4 as shapes rather than full literals because each must mirror its sibling handler's existing test constructor/fakes, which the executor reads at implementation time; the exact assertion (status code + identity injection) is specified. All code-bearing steps in Tasks 1–2 contain complete code.

**Type consistency:** `NeighborParams.AllowedProjectIDs []string` + `RestrictToAllowed bool` defined in Task 1, set by `resolveNeighborProjectScope` in Task 2. `GetNeighbors`/`NeighborResponse.Neighbors`/`NeighborNode.ID`/`NeighborNode.ProjectID` verified against source. `middleware.DeveloperIdentity{Role, ProjectIDs}` + `models.APIKeyRoleAdmin`/`APIKeyRoleDeveloper` verified. `NewNeighborStore`, `NewNeighborHandler(*store.NeighborStore, *slog.Logger)` verified — handler store field is concrete (Task 2 deliberately avoids interface churn).

**Known caveats (verified against source):**
1. The store builds main and count queries in **two separate closures** with independent arg slices (`args`/`argIdx` for main; `countArgs2`/`countArgIdx` for count — the main closure's `countArgs` is vestigial/unused, function returns `countArgs2`). Task 1 Step 4 (main) and Step 5 (count) must BOTH be applied or pagination `total` diverges from returned rows.
2. The store's `switch params.Direction` has **no default case** — an empty `Direction` produces an empty UNION and a broken query. All Task 1 store-test calls set `Direction: "both"`. (The handler supplies a direction from the request; the store relies on the caller.)

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-28-rbac-isolation-keystone-gate.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks.
2. **Inline Execution** — execute tasks in one session with checkpoints.

Which approach?
