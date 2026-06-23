# DAAB → CTO — Keystone verdict on the Hermes-capability allocation

**From:** DAAB Technical Principal (ennam.kg) · **To:** Ecosystem CTO · **Date:** 2026-06-23
**Re:** `decisions/ecosystem-hermes-allocation.md` — open gates #1 (internals) & #2 (cross-platform RBAC)
**Status:** ACTION REQUIRED — one keystone assumption was REFUTED; the underlying defect is now fixed in code; consumer rollout remains gated.

---

## Bottom line up front

1. **The retrieval engine you assumed exists is real and live.** Semantic-over-nodes (384-dim), RRF hybrid, full-text with windowed snippets, versioned JSONB — all shipped and wired. The "thin extension" framing holds *for search/ranking*. (Gate #1: PASS-with-corrections.)
2. **The make-or-break — cross-platform RBAC isolation — did NOT hold.** It failed on *already-shipped* read endpoints, not on the unbuilt memory feature: a key scoped to project A could read project B's data by putting B's `project_id` in a POST body (the access middleware only inspected the header/query), plus by-UUID IDOR on history/document/neighbors. This is a **pre-existing production security defect**, independent of Hermes. (Gate #2: was FAIL.)
3. **DAAB has fixed it this session,** test-gated (RED→GREEN). The cross-project leak is closed at the handler boundary with an executable gating suite. **Gate #2 now passes for the read surface that `kg_recall` will ride.**
4. **Net for the ecosystem plan:** the keystone is no longer blocked by a broken substrate, but the *memory lifecycle* work (per-user scoping, retention, embed-on-write) re-budgets from "thin" to "net-new." Consumer enablement (AAAA/LAAM) stays gated until the items below are signed off.

---

## Gate #1 — Internals exist as asserted? PASS, with two corrections

| CTO assumption | Verdict | Note |
|---|---|---|
| Vector/semantic search over nodes, **384-dim** | ✅ CONFIRMED | 384 is correct *for node embeddings* (`multilingual-e5-small`, Python-local). A **second** 1536-dim space exists for NL→SQL tables — don't conflate them. |
| RRF hybrid (`store/rrf.go`) | ✅ CONFIRMED | k=60, live on `/search` + MCP `kg_search`. |
| FTS + windowed `ts_headline` | ✅ CONFIRMED | Opt-in, plain-FTS path only, **english-only** (no VN/CJK). |
| "gate-2" completeness | ⚠️ PARTIAL | Per-write gate blocks; **session-end gate is best-effort/skip-on-error** — your "silent amnesia" fear is correct *for that surface*. Capture must not ride it. |
| thread/session stores | ⚠️ PARTIAL | Chat bodies stored but **not indexed** → `kg_search_sessions` is **net-new**. |
| `is_archived` retention on nodes | ❌ DOES-NOT-EXIST | Only on threads/projects. Node retention (archive/decay/growth-bound) is **net-new**. |
| versioned JSONB · `content_hash` dedup | ✅ / ⚠️ | Versioning real; `content_hash` exists but at ingest, not recall-time. |

**Scope delta:** retrieval engine ≈ free; **isolation, per-user (`user_id`) scoping, node retention, and embed-on-write for agent memory are net-new.** Re-budget Phase 1 accordingly.

## Gate #2 — Cross-platform RBAC isolation: was REFUTED → now FIXED

**Root cause:** the `ProjectID` middleware read the project only from the `X-Project-ID` header / query param, while the recall handlers read `project_id` / `cross_project_ids` from the request **body** — so the access check guarded a value the query never used. No `tenant_id` exists above `project_id`, and **`user_id` was never enforced on node reads.**

**Confirmed open paths (all reproduced in a failing test before the fix):**
- Body-override: `POST /search {project_id: P_B}` (no header) → returned P_B's data to a P_A key.
- `cross_project_ids:[P_B]` — never access-checked (store comment "enforced by middleware" was false).
- By-UUID IDOR: `/nodes/{B}/history`, `/section-content`, `/document-structure`, `/neighbors`, `/traverse`.
- Admin/empty-`ProjectIDs` keys read everything by design.

**Fix delivered (DAAB, this session, repo `ennam.kg.go`, branch `fix/cross-project-idor`):**
- New `requireProjectAccess` guard → **403** on body `project_id`/`cross_project_ids` the key can't access; wired into search, search-chunks, query, neighbors, traverse.
- New `requireNodeProjectAccess` guard → **404** IDOR guard on by-UUID reads (history, document section/structure/meta).
- Removed the misleading store comments; added `project_id` to the history store response for the guard.
- **Gating tests (RED→GREEN):** `recall_isolation_test.go` (DB-free, proves search/query/neighbors/traverse close the leak; store proven not reached) + `recall_isolation_integration_test.go` (`//go:build integration`, full Auth→ProjectID→handler chain on a real DB).

**Verified:** `go build`, `go vet`, full handler suite, middleware suite all green. (`-race` not run — no cgo on the dev box; `make lint` not run — golangci-lint not installed; integration suite compiles but needs a DB — to run in CI.)

## Design claims — dispositions (concise)

- **(a) `agent_memory`/`user_profile` as node types →** ✅ **REVISE to a sibling table.** They have no graph edges → would be permanent islands distorting the knowledge graph. Model as `agent_context`, not `knowledge_nodes` types.
- **(b) `kg_remember`/`kg_recall` MCP tools →** feasible & cheap (live surface is **35 tools**, not 25), **but per-`user_id` scoping does not exist** → schema migration required. In the Qwen 6-tool profile, `kg_recall` should *replace* `kg_search`, not sit beside it.
- **(d) Capture ≠ gate-2 →** ✅ CONFIRMED. Attach capture to the deterministic **store INSERT boundary**, not the skippable validator.
- **(e) Graph nodes + no-LLM capture →** ✅ CONFIRMED, with a pin: embed via the **Python local 384-dim path**, *not* the Go generator (which is remote-billed 1536-dim + LLM-summarized).
- **(f) Own ranking+retention once at recall →** ⚠️ REVISE: rank/enforce at recall, but **compute** decay/archive/dedup/growth-bound in a background job.
- **CTO missed:** agent memory is never embedded on write (full-text-only today); two incompatible embedding dims; inline-edge whitelist bypass; the shared-infra ownership boundary; Phase-6 ingestion namespace collision.

## What I need from you (decisions)

1. **Accept the re-budget:** Phase-1 keystone = retrieval reuse (cheap) **+ net-new** isolation hardening, `user_id` scoping migration, node retention, and embed-on-write. Not uniformly "thin."
2. **Approve the isolation fix as a standalone security patch** (it protects the current single-platform deployment regardless of Hermes) and require the gating suite + `make test`/`make lint` to pass in CI before merge.
3. **Ratify the modeling change:** memory is a **sibling table**, not node types.
4. **Hold consumer enablement (AAAA/LAAM keys) until:** (a) this fix is merged + green in CI with a DB; (b) the `user_id` scoping migration lands (user-vs-user isolation within a shared project is currently impossible — no column exists); (c) a consumer-key issuance policy exists (see open item).

## Open items / risks (surfaced, not hidden)

- **Consumer-key policy** ("forbid admin+empty `ProjectIDs`"): **not implemented** — would break the legitimate admin-all model, and the schema has no consumer-vs-internal key distinction yet. Enforce when a consumer-issuance path is built. (Conflict surfaced per AGENTS.md Rule 7.)
- **Write-IDOR** (`update*`/`deprecate` by UUID) is out of the *read*-isolation scope but real — schedule a follow-up sweep.
- `-race`, `make lint`, and the integration suite were not executed locally (no cgo / no golangci-lint / no DB) — must run in CI.
- `user_id` isolation is **un-enforceable today** until a `knowledge_nodes.user_id` migration + recall filters land.

See `decisions/daab-hermes-keystone-verification.md` for the full file:line evidence trail.
