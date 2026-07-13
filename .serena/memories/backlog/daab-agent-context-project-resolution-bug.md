# BUG — kg_remember/kg_recall unusable with dashboard-created keys (project resolution)

**Found:** 2026-07-08 via live dogfood (branch server real-auth on :9090 vs daab-postgres). **Severity: HIGH** — explains why `agent_context` had **0 rows** (memory-of-record never successfully used by anyone).

## ⚠️ SECOND SURFACE CONFIRMED 2026-07-10 — READ PATH (query/search/neighbors/traverse) — NOT fixed
Live smoke test (single-project key, `?project_id=P`) → `POST /api/v1/query` and `/search` return **403 "project override not permitted"**. Root cause is the SAME dashboard gap (no `default_project_id` set) but a DIFFERENT code path: `middleware/project.go:114` computes `isOverride := explicit != "" && (DefaultProjectID==nil || explicit != *DefaultProjectID)` — so passing the key's OWN scoped project counts as an "override" when there's no default, and `CanOverrideProject()` is false for a scoped (non-admin-empty) key → 403. This blocks the ENTIRE read surface for AAAA's exact key shape (single-project developer). The `ae6a43e` fix only touched agent_context handlers, not this middleware path (deliberately, per advisor).
**Correct fix (advisor-confirmed, deferred — provisioning-gated, no wired consumer yet): key-creation handler auto-sets `default_project_id = project_ids[0]` when exactly one project is given.** Fixes BOTH the memory bug and this read-path bug at the source, zero RBAC-middleware change, matches the sanctioned happy path ("use the default project"). Do NOT relax `isOverride` in the middleware (shared g2 chain, unbounded blast radius). Verify-before-ship: auto-default must not interact with the bridge per-project-pin IDOR closure (`mem:bridge-files-proxy-per-project-pin`) — setting a default ≠ pinning, still can't reach outside scope, expected clean.
**Stopgap for local testing:** admin key with BLANK project_ids → `CanOverrideProject()`=true → read tools work.

## ✅ FIXED 2026-07-08 — commit `ae6a43e` on `task/implement_docs_sync`
Handler-local fix (NOT the shared primitive — advisor-guided): new `resolveAgentProject(identity)` in `internal/handler/agent_context.go` falls back to the sole `ProjectIDs[0]` when a key is scoped to exactly one project; wired into `Recall` + `resolveWriteIdentity`. `middleware.ResolveProjectID` (RBAC g2 chain) left UNTOUCHED. Unit test `TestResolveAgentProject` (5 cases incl. ambiguous-multiple → false, default-wins). **Live dogfood proof:** user-created developer key scoped to project `592c7ff7` (no default) → `kg_remember` x3 = 200, `kg_recall` round-trip returns them, `last_recalled_at` populated on the recalled row, `updated_at` untouched. agent_context now has real rows.
Correction to the "smallest" note below: option **(A) global is the BROADEST** (shared primitive), not smallest; the handler-local fix shipped is the genuinely smallest.

## Symptom (reproduced live)
A **developer** API key created via the dashboard (`/settings/api-keys`), scoped to exactly one project P (`project_ids={P}`), **cannot write or read agent memory**:
- `POST /api/v1/agent-context/remember` **no header** → `400 "no project context for this key"`.
- Same with `X-Project-ID: P` (its OWN scoped project) → `403 "project override not permitted"`.

An **admin** key with `project_ids={}` (all) + no default behaves the same (400 / override-denied). So NO dashboard key works with the memory API.

## Root cause (code-verified)
- `middleware/auth.go:247-252` builds `DeveloperIdentity` with `DefaultProjectID: key.DefaultProjectID` — a **direct copy, no fallback to project_ids**.
- `DeveloperIdentity.ResolveProjectID(explicit)` (`auth.go:85-89`) returns a project ONLY from `explicit` (empty on the memory path) or `DefaultProjectID`; **never falls back to `project_ids[0]`**.
- The agent_context handlers (`handler/agent_context.go` Remember/`resolveWriteIdentity` + Recall) call `identity.ResolveProjectID("")` — they do NOT consume the ProjectID-middleware's header-resolved effective project. So `X-Project-ID` is ignored for the write-identity, and when passed it is treated as an "override" gated by `allow_project_override` (false by default) → 403 even for the key's own allowed project.
- The dashboard **Create API Key** form (screenshot 2026-07-08) exposes only Label / Role / Project IDs — **no `default_project_id` field**. So every dashboard-created key has `default_project_id = NULL` → memory API unusable.

## Fix options (pick when demand pulls it — targeted, TDD)
- **(A, smallest)** `ResolveProjectID("")` falls back to `project_ids[0]` when the key has exactly one project. Single-project keys then auto-resolve. Least surprising for consumer keys (D3: role=agent, non-empty project_ids, override=false).
- **(B)** agent_context handlers honor the middleware-resolved effective project (`GetEffectiveProjectID`) so `X-Project-ID` works, consistent with node/search handlers.
- **(C)** Dashboard exposes + sets `default_project_id` on create (and API sets it when exactly one project_id given).

Recommend **(A)** (+ maybe C for ergonomics). Add a handler/integration test: single-project developer key can remember+recall into its scoped project with no header.

## Why this matters strategically
This is the **real, non-speculative blocker** on the keystone critical path: any consumer (AAAA/LAAM) — or DAAB dogfooding itself — hits this immediately. Fixing it is demand-driven, not building-ahead. It is almost certainly why the keystone shows 0 usage. See `mem:checkpoint/daab-decay-impl-verify-2026-07-08` and the "keystone built but unused" thread.
