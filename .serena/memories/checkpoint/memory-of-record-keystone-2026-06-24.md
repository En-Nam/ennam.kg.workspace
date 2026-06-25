# Checkpoint: memory-of-record keystone (kg_remember/kg_recall) — 2026-06-24

## What was done
DAAB Phase-1 keystone vertical slice SHIPPED via subagent-driven development (9 TDD tasks, implementer+reviewer per task, opus final review). Implements `mem:decisions/ecosystem-hermes-allocation` + `mem:decisions/daab-hermes-keystone-verification` P1.
- Spec: `docs/superpowers/specs/2026-06-24-memory-of-record-kg-remember-recall-design.md`
- Plan: `docs/superpowers/plans/2026-06-24-memory-of-record-kg-remember-recall.md`
- SDD ledger: `.superpowers/sdd/progress.md` (full per-task commit trail + deferred items).

## Files changed (committed, NOT pushed; branch task/implement_mcp both sub-repos)
ennam.kg.go 21e3044..47815da (10 commits): db/migrations/000068_agent_context.{up,down}.sql; internal/store/agent_context.go (+fusion_test, +integration tests in agent_context_test.go); internal/queue/agent_context_messages.go(+test); internal/handler/agent_context.go(+test, +isolation integration test); cmd/kg-server/main.go (buildRouter param + run() publisher); internal/bridge/{schema,client,schema_test,handler_test,client_test,integration_test}.go.
ennam.kg.python 896f335..e5cf2e4 (1 commit): config.py (agent_context_queue_name), worker.py (4th consumer + embed_agent_context closure branch + LocalEmbeddingModel), packages/.../kg_client/client.py (upsert_agent_context_embeddings), tests/test_embed_agent_context_handler.py.

## Current state — WORKING, verified on live DB (port 5433)
- agent_context + agent_context_embeddings(vector 384) tables; kg_remember (write, durable embed enqueue) + kg_recall (read, hybrid RRF, raw windowed, soft-fail) over MCP+REST. Bridge invariant 42/39/3 → 44/41/3.
- Embed-on-write: kg_remember → Redis queue `ennam:agent_context_embed` → Python worker `encode_passage` 384-dim → POST /api/v1/projects/{id}/agent-context/embeddings/batch.
- All 7 cross-component contracts verified end-to-end (opus). Isolation gate GREEN (key-resolved project_id, not body-spoofable). store+handler integration, queue, bridge, go build, python test ALL PASS.
- Handler integration DSN var = KG_TEST_DSN (libpq kv); store = KG_TEST_DATABASE_URL (URL). For 5433: `KG_TEST_DSN="host=localhost port=5433 dbname=ennam_kg user=ennam_kg password=ennam_kg_dev sslmode=disable"`.

## Next steps
- Run `make test` (-race/cgo) + `make lint` (golangci-lint) in CI — not run locally.
- Gate g2 for consumer (AAAA/LAAM) enablement still needs: `user_id` migration (D1) + consumer-key class (D3). Consumer keys MUST set default_project_id (recall/remember resolve project via ResolveProjectID("")=DefaultProjectID ONLY).
- Follow-up spec (retention/consumer-key): I1-fixed already; deferred = content_hash skip-re-embed; UPDATE→INSERT TOCTOU (vs spec's ON CONFLICT); test gaps (embedding-upsert, enqueue_failed, top_k clamp); nil-UUID sentinel CHECK; mem_key length guard.

## Blockers / Risks
- None blocking. Deviation from spec §4 (UPDATE-then-INSERT instead of ON CONFLICT) → retryable 500 under concurrent same-mem_key writes; documented, deferred.
- Not pushed per user instruction (commit-only).
