# DAAB verification of the Hermes-allocation decision (answers gates #1 & #2)

**Status:** DECISION (DAAB Technical Principal) · **Date:** 2026-06-23 · **Verifies:** `decisions/ecosystem-hermes-allocation.md` open questions #1, #2, #4 · **Method:** file:line code inspection (16-agent adversarial sweep + principal firsthand reads).

## Verdict in one line
Retrieval engine = real & live (CTO right, thin reuse). **Keystone RBAC isolation = DOES-NOT-HOLD (CTO's #2 gate FAILS).** Memory lifecycle (retention, user-scoping, embed-on-write) = NET-NEW, not thin.

## Part 1 — Substrate gate (#1): PASS-WITH-CORRECTIONS
- Semantic search over nodes — EXISTS. `store/node_embedding.go:99-161` SemanticSearch over `knowledge_node_embeddings vector(384)` (`000055`). **384-dim CONFIRMED** (model `intfloat/multilingual-e5-small`, Python local). Dual space: `table_embeddings vector(1536)` (OpenAI, NL→SQL) is separate. Agent nodes are NOT embedded on write (only doc sections) → semantic recall of memory = net-new wiring.
- RRF hybrid — EXISTS, live. `store/rrf.go:11-48` (k=60), `handler/search.go:276-349`, MCP `mode=hybrid`.
- FTS + windowed ts_headline — EXISTS. `store/search.go:347-358`, opt-in, plain-FTS path only, english-only.
- gate-2 — PARTIAL. Per-write field gate blocks (`service/node.go:238`); session-end workflow gate is best-effort/skip-on-error (`service/session.go:185-211`) = the silent-amnesia path.
- thread/session stores — PARTIAL. Chat bodies stored (`thread_messages.content`) but NOT indexed (B-tree only). `kg_search_sessions` = NET-NEW.
- versioned JSONB ✅ / content_hash ✅ (ingest-time, not recall dedup) / **is_archived on nodes ❌** (only on threads+projects). Node retention = NET-NEW.

## Part 2c — RBAC isolation gate (#2): FAILS — ISOLATION-DOES-NOT-HOLD
Root cause: `ProjectID` middleware reads only `X-Project-ID` header + `?project_id` query (`middleware/project.go:191-201`); recall handlers read `project_id`/`cross_project_ids` from the JSON **body** (`handler/search.go:124-176`). Check guards a value the query never uses. No tenant_id above project_id; no user_id filter on nodes.

Open cross-project read paths (key scoped to A reads B):
1. Body-override `POST /search {project_id:B}` no header → reads B (`search.go:246-264`→`store/search.go:284`).
2. `cross_project_ids:[B]` body — never access-checked (store comment "enforced by middleware" is FALSE).
3. History IDOR by UUID — `handler/history.go:56-120` no check; `store/history.go` filters id only.
4. Document `/section-content` `/document-structure` IDOR — `GetNode(id)` no project predicate; only `GetDocumentMeta` guards (its comment names the IDOR class).
5. neighbors/traverse body path + `include_cross_project` drops edge project filter (`store/neighbors.go:209-218`).
6. admin/empty-ProjectIDs key (or `KG_AUTH_NOOP`) reads all by design.
7. user-vs-user leak inside a shared project is unpreventable (no user_id column).

**Gate test (must pass before ANY consumer):** new `internal/handler/recall_isolation_test.go`, full Auth→ProjectID→handler chain, 2-project/2-key seed. Cases T1–T7 (see verification report). T1–T5 FAIL today; T6 (user scoping) un-implementable until a `knowledge_nodes.user_id` migration. Fix = store-level invariant: every read takes `allowedProjectIDs`, reconcile body project vs `GetEffectiveProjectID`, guard by-id reads on fetched node's project (mirror `document.go:119`).

## Design verdicts
- (2a) node types `agent_memory`/`user_profile` → NEEDS-REVISION: model as **sibling table `agent_context`**, not graph nodes (would be edge-less graph islands; `config.yaml:706-1055`).
- (2b) kg_remember/kg_recall → NEEDS-REVISION: tools cheap (live count = 35, not 25); **user_id scoping does not exist** (schema migration needed). Replace kg_search w/ kg_recall in QwenReadOnlyToolProfile.
- (2d) capture ≠ gate-2 → CONFIRMED. Real risk is gate-2 no-op/skip (nil rule), not error-bypass. Attach at store INSERT boundary (`store/node.go:131`/CreateNodeTx).
- (2e) graph nodes + no-LLM capture → CONFIRMED, pin to Python local 384-dim path; forbid `generateDescription` LLM (`embedding_generator.go:224-256`); fix request-ctx-bound async (`handler/embedding.go:74-86`).
- (2f) own ranking+retention once → NEEDS-REVISION: ranking yes at recall; **compute** decay/archive/dedup/growth-bound in a background jobengine job, **enforce** at recall.

## CTO missed: agent memory never embedded on write; two incompatible embed dims; inline-edge whitelist bypass (`service/node.go:409-415`); Phase-2 shared-infra ownership boundary; Phase-6 ingestion namespace collision.

## Consequence for the ecosystem plan
Phase 1 keystone re-budgets: RBAC isolation = blocking NET-NEW (fix regardless of memory). All consumer-facing work BLOCKED until the gate test passes. See [[ecosystem-hermes-allocation]].
