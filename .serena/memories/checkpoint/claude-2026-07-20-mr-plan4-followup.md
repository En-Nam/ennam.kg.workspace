# Checkpoint: claude (MR Plan 4 follow-up) — 2026-07-20

## What was done
User asked to close open item 2 from the Plan 4 completion report: the generic node endpoints bypassed the `derived_record` `content` guard.

**Gap:** the dedicated `/derived-records` endpoint rejected an incoming `content` field, but `POST /api/v1/nodes` and `PUT /nodes/{id}` did not — `NodeService.validateStoreRequest` deliberately allows unknown fields into JSONB, and `UpdateService.validateUpdateRequest` did NO property validation whatsoever (only id/expected_version/change_reason/changed_by). So a hand-rolled REST call could plant `content` on a derived_record, the shared trigger would index it, and the D4 leak would reopen.

**Fix (commit `bf5a5be`, ennam.kg.go):** new `internal/service/derived_record_guard.go` with `rejectLegacyContentOnDerivedRecord`, wired into `validateStoreRequest`, `UpdateNode`, and `UpdateNodeWithProvenance`. Both paths return 400. 8 new tests in `internal/handler/generic_node_content_guard_test.go` (3 guard-positive + 5 negative controls).

## Key design decision
Guard is deliberately NARROW — `node_type=='derived_record'` + key `content` only. Rejected the "general" alternative (block any trigger-indexed key not declared in a node type's config) because live data shows many types legitimately use those keys (concept/name 3878, organization/description 1743, document_chunk/content 1525). A general rule = broad behavior change, real regression risk, no extra D4 benefit.

## Current state
- All 8 guard tests pass; full `go test ./... -count=1` zero failures; `go vet` clean.
- Live invariant: 0 `derived_record` rows carry `content`. Real record `215aad3f` intact (no content, record_body 34862).
- Negative controls hold: document_chunk 1525 / document_section 406 / architecture 317 still carry `content` legitimately.
- Production reachability confirmed at `cmd/kg-server/main.go:483` (`WithNodeReader`) — not test-only wiring.

## Reviewer's write-path census (rules out bypasses — reuse this if the question recurs)
Guarded: generic POST/PUT + all 6 per-type update handlers + the dedicated endpoint. NOT holes: `kg_generator.go:266` writes directly to the store but its NodeType is the hardcoded literal `"architecture"`; `deprecate.go:113` builds `UpdateNodeParams` without `Properties` at all; `internal/partial` has no store access; the Python indexer writes over REST onto guarded handlers; no PATCH route exists for nodes.

## Next steps / open items
- Rotate the dev-stack admin API key (leaked into a scratch report earlier, redacted, never git-tracked).
- Run real `golangci-lint` in CI — unavailable in this sandbox throughout; `go vet` substituted (always clean).
- **New tracked Minor:** update-path validators fail-open if `nodeReader.GetNode` hits a transient error (`existing` set nil, guard skipped). PRE-EXISTING swallow that `gate2ValidateUpdate` and `validateProvenanceLinks` already depend on identically — deserves its own ticket about the swallow, not a unilateral change.
- Cosmetic: `config.yaml:701` prose still says "full non-indexed content".

## Blockers / Risks
None. Full audit trail in `.superpowers/sdd/progress.md`. See `mem:checkpoint/claude-2026-07-20-mr-plan4` for the main plan.
