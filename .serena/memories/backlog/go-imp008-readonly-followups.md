# Backlog: IMP-008 readonly profile — follow-ups (Go bridge)

Source: IMP-008 final whole-branch review (2026-06-17). Both are non-blocking
Minors — IMP-008 shipped without them by agreement. Neither is a bug.

Go branch ref: IMP-008 = `60cb1aa..efae831` on `task/implement_mcp` (repo `ennam.kg.go`).

## 1. `MaxValue`/`MinValue` not enforced server-side in the bridge (defense-in-depth)

- **What:** `internal/bridge/schema.go` `validateValue` (TypeInteger/TypeNumber
  branches) only does type coercion; it never reads `MaxValue`/`MinValue`. So
  `kg_search_chunks.limit` `MaxValue:10` (and `kg_search.limit` `MaxValue:100`)
  are advertised as JSON-schema `maximum` hints to the client but NOT enforced
  at the bridge. Real ceiling = whatever the REST API enforces.
- **Why deferred:** read-only tools, low stakes; REST API still caps it; FR-1's
  acceptance was "MaxValue in schema" which IS met. Fixing `validateValue`
  touches ALL tools → own tests/review, out of IMP-008 scope. Same category as
  the plan's own out-of-scope note (`kg_search_chunks.offset` lacks `MinValue:0`).
- **When to pick up:** good fit for Phase 8 (scoped API keys / input-hardening
  pass). If done: add a bounds check in `validateValue` + table tests; also close
  the `offset` `MinValue:0` gap at the same time.

## 2. `kg_list_drafts` in `QwenReadOnlyToolProfile` exposes un-approved drafts — PRODUCT DECISION

- **What:** `QwenReadOnlyToolProfile` (schema.go) includes `kg_list_drafts`. It is
  correctly READ-class (a GET) so it is NOT a security defect and the profile's
  read-only invariant holds. But it surfaces ingestion *draft* nodes (un-approved,
  potentially noisy/low-quality KG content) to the Qwen/LAAM read-only profile.
- **Action:** confirm with the feature owner whether drafts SHOULD be visible to
  that profile. If not, drop `kg_list_drafts` from the profile var and update
  `TestQwenReadOnlyToolProfileContents` (length 6→5). No other code change.
- **Not a code task until the product call is made.**
