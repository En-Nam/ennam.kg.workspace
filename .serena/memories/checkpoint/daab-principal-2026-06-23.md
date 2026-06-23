# Checkpoint: daab-principal — 2026-06-23

## What was done
- Adversarially verified the CTO Hermes-allocation decision's DAAB claims (gates #1, #2, #4) with file:line evidence.
- Ran a 16-agent verification workflow (substrate ×6, design ×7, RBAC ×3) + firsthand principal reads of auth/project/apikey/node_embedding/rrf + migrations.
- Wrote verdict to `decisions/daab-hermes-keystone-verification.md`.

## Files changed
- + `.serena/memories/decisions/daab-hermes-keystone-verification.md`
- + `.serena/checkpoint/daab-principal-2026-06-23.md`
- (read-only inspection of ennam.kg.go internal/store, internal/middleware, internal/handler, internal/service, db/migrations; ennam.kg.python config/embeddings)

## Current state
- VERIFIED: node semantic search @384-dim (CONFIRMED), RRF hybrid, FTS+ts_headline — all EXIST & live.
- VERIFIED BROKEN: cross-platform RBAC isolation DOES-NOT-HOLD — body-override + cross_project_ids + by-UUID IDOR (history/section-content/neighbors) let a project-A key read project-B nodes. Root cause: ProjectID middleware reads header/query only, handlers read project_id from body.
- is_archived on nodes, user_id on nodes, decay/growth-bound, agent-memory embed-on-write, session-body search = DOES-NOT-EXIST (net-new).

## Next steps
- Phase 0 (RBAC gate) is the blocker: implement store-level project invariant + recall_isolation_test.go (T1–T7); ships value regardless of memory feature.
- Then: agent_context sibling table + always-runs capture at store boundary + Python-local embed; kg_recall/kg_remember MCP; background retention job; kg_search_sessions.

## Blockers / Risks
- RBAC isolation is a PRE-EXISTING security defect (cross-project IDOR), not just a memory-feature gap — affects current single-platform deployment too. Recommend prioritizing independent of Hermes work.
- Did NOT exhaustively sweep every by-id handler (update/edge-get/draft/merge/canonical-document/extraction) — same GetNode-without-check pattern likely recurs; sweep before relying on isolation.
- Verdict is by code-path inspection, not a live exploit run; T1–T7 should be implemented to confirm empirically.

---

# Checkpoint (append): cross-project IDOR fix — 2026-06-23 (session 2)

## What was done (TDD: RED→GREEN)
- Wrote failing gating tests proving the leak (search foreign project_id → got 200 with foreign data; query/neighbors/traverse → reached store), then fixed to green.
- Added `internal/handler/authz.go`: `requireProjectAccess` (body project_id + cross_project_ids → 403) and `requireNodeProjectAccess` (by-id node → 404 IDOR guard, mirrors GetDocumentMeta).
- Wired guards: search (HandleSearch + HandleSearchChunks), query, neighbors, traverse (project-access before store); document GetSectionContent/GetDocumentStructure + refactored GetDocumentMeta to the helper; history (added project_id to store response + handler guard).
- Removed the false "enforced by middleware" comments in store/search.go + store/query.go.

## Files changed
- + internal/handler/authz.go
- + internal/handler/recall_isolation_test.go (DB-free gating + helper unit tests)
- + internal/handler/recall_isolation_integration_test.go (//go:build integration; full Auth→ProjectID→handler chain, runs with KG_TEST_DSN)
- M internal/handler/{search,query,neighbors,traversal,document,history}.go
- M internal/store/{history,search,query}.go

## Verified
- go build ./... OK; go vet handler/store/middleware OK.
- DB-free gating tests RED (200/500) → GREEN (403/404). Full handler suite passes (go test ./internal/handler/ -count=1). middleware tests pass. store compiles.
- Could NOT run `make test` (-race needs cgo; no C compiler here) or `make lint` (golangci-lint not installed) — ran `go test` (no race) + `go vet` + gofmt instead. All my files gofmt-clean on canonical LF (working-tree CRLF is git autocrlf, normalizes on commit). Integration tests compile under -tags=integration but were NOT executed (no DB reachable: Docker down, no psql).

## Next steps / follow-ups (surfaced, not done)
- Run the integration suite + `make test`/`make lint` in CI / on a machine with a DB + C compiler.
- Sweep write-IDOR: update*/deprecate let a key modify another project's node by UUID (out of read-isolation scope but real). audit-by-id may also leak.
- Apikey policy "forbid admin+empty ProjectIDs for consumers": NOT implemented — would break the existing intentional admin-all model and there is no consumer/internal key distinction in the schema yet. Surfaced as a conflict (AGENTS.md Rule 7); enforce when a consumer-issuance path exists.
