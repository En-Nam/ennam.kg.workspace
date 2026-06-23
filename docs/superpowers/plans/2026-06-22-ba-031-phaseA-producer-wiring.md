# BA-031 Phase A — Wire the Suggestion-Producer Chain (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. TDD per task (failing test → implement → pass). Steps use `- [ ]`.

**Created:** 2026-06-22
**Depends On:** BA-031 (closed vocabulary, apply path — all built). **Blocks:** the BA-031 turn-on runbook (`2026-06-22-ba-031-resolution-turn-on-runbook.md`) and BA-033.

## Goal

Make a freshly-ingested document actually flow **extract → Pass 1 (closed-schema entities) → Pass 2 (candidate→verify→write `merge_suggestions`)** end-to-end, so that the already-built apply path has input. Today the apply machinery is wired but **nothing produces `merge_suggestions`** — `run_pass1`/`run_pass2_shadow` exist but have no live caller, and the Python worker never consumes the extraction queue.

**Success criterion:** ingesting a 2-document corpus that shares an entity (e.g. "AIO Link" / "AIOLink") results in ≥1 `merge_suggestions` row (`decision='suggested'`) — verifiable by SQL — without `apply_mode` being `apply` (shadow-safe: suggestions only, no graph mutation).

## What's already built (verified 2026-06-22, do NOT re-implement)

| Piece | Location | Status |
|---|---|---|
| Closed-vocab `node_type` CHECK (OQ-001) | `ennam.kg.go/db/migrations/000061_ba031_closed_vocab.up.sql` | ✅ LANDED (Person/Organization/… allowed) |
| Pass 1 extractor `run_pass1(doc_id, run_id, project_id, deps)` | `ennam.kg.python/src/ennam_kg/extraction/pass1.py:91` | ✅ writes entities + closed edges + embeddings + provenance |
| Pass 2 orchestrator `run_pass2_shadow(doc_id, run_id, project_id, deps)` | `ennam.kg.python/src/ennam_kg/resolution/pass2.py:113` | ✅ embed→retrieve→verify→write suggestion |
| Candidate retriever `HttpxRetriever.retrieve()` | `ennam.kg.python/src/ennam_kg/resolution/candidates_client.py:51` | ✅ POSTs `/internal/resolution/candidates` |
| Verifier `verify_pair()` | `ennam.kg.python/src/ennam_kg/resolution/verify.py:162` | ✅ routes via AIClient (BA-009) |
| `KGClient.create_merge_suggestion()` | `…/kg_client/client.py:448` | ✅ POSTs `/internal/resolution/suggestions` (shadow-safe) |
| Go publishes `extract_document` per chunk → `ennam:extraction` | `ennam.kg.go/internal/handler/extraction.go:266-273`, `internal/queue/extraction_messages.go:13-96` | ✅ |
| `PublishResolveDocument` + recovery-sweep enqueue | `internal/queue/extraction_messages.go`, `internal/jobengine/extraction_recovery.go:57-60` | ✅ (recovery only, not forward path) |
| Message models `ExtractDocumentMessage` / `ResolveDocumentMessage` | `ennam.kg.python/src/ennam_kg/queue/messages.py:67-100` | ✅ |
| `chunk_extraction_state` (pending→extracting→extracted→resolving→resolved) | `db/migrations/000062_chunk_extraction_state.up.sql:7-8` | ✅ |
| resolution endpoints (candidates/suggestions/merge/unmerge/apply) | Go handlers | ✅ |

## The gaps (the actual Phase A work)

1. **Worker never consumes `ennam:extraction`** — both consumers listen on the index + kg_generation queues only (`worker.py:234-235`).
2. **`extract_document` handler is a STUB** (`worker.py:190-201`) — must call `run_pass1`.
3. **`resolve_document` handler is a STUB** (`worker.py:203-212`) — must call `run_pass2_shadow`.
4. **`get_entities` for Pass 2 is unimplemented** — no way to list a doc's just-extracted entities.
5. **No FORWARD trigger** extraction→resolution — extraction is fire-and-forget per chunk; only the recovery sweep enqueues `resolve_document`. A doc-level "all chunks extracted → resolve once" trigger is missing.
6. **Small adapters missing:** `AIClient.complete_json()`, `KGClient.get_node()`, `extraction_queue_name` + Pass-2 threshold config.

---

## ⚠️ Verified corrections (2026-06-22 — read before coding)

Two claims in an earlier draft of this plan were wrong; fixed in the tasks below:

- **E1 — `get_entities` MUST be synchronous.** `pass2.py:133` calls `deps.get_entities(doc_id, run_id, project_id)` **without `await`**, and `Deps.get_entities` is a plain sync `Callable` (the retriever `deps.retriever.retrieve()` at `pass2.py:149` is also sync). So `get_entities` cannot wrap the async `KGClient`. Implement it as a **sync HTTP client mirroring `HttpxRetriever`** (sync `httpx.Client`). A `lambda: await …` would hand Pass 2 a coroutine, not a list. (Task 4.)
- **E2 — there is NO bare `GET /api/v1/nodes/{id}` endpoint.** Only `/nodes/{id}/neighbors|section-content|document-structure|outline`, `PUT /nodes/{id}`, and `/deprecate` exist. The internal `NodeReader.GetNode` interface exists but has no route. Chunk hydration (Task 2) therefore needs a **new bare GET node endpoint added on the Go side** (Task 3) before `KGClient.get_node` can work. `get_node` itself may stay async (it runs inside the async `extract_document` handler).

Confirmed-correct (no change): `AIClient.complete_json` is genuinely absent (Task 1 adds it; `pass1.py:127` already calls it); `create_merge_suggestion` lives in `packages/ennam-kg-indexer/.../kg_client/client.py:448` and the worker imports that client; the `/candidates` default `min_similarity = 0.82` (D4 holds); the closed-vocab CHECK (000061) is landed.

---

## Critical design decisions (read before coding)

### D1 — SEAM: fill the `extract_document` handler, do NOT touch `run_batch`
Pass 1 emits N entity nodes + closed edges; the existing `extract_draft`→`run_batch` path emits ONE hub doc node + sections. They are **different pipelines that coexist**. Wire Pass 1 into the **per-chunk `extract_document`** handler (message shape already matches `run_pass1`'s `doc_id/run_id/project_id`). Leave `run_batch`/`extract_draft` untouched (engine.py:167,232).

### D2 — Per-chunk extract vs per-doc resolve (THE coordination risk)
Go publishes **one `extract_document` per chunk**, but Pass 2 resolves **per document** (a doc's entities against the existing graph). So resolution must fire **once per doc, after its last chunk is extracted**. Chosen mechanism (leverages existing `chunk_extraction_state`):

- Python `extract_document` handler, after `run_pass1` for a chunk, calls a **Go chunk-complete endpoint** (Task 3) that marks the chunk `extracted` and checks doc completion; when the **last** chunk of a doc flips to `extracted`, Go enqueues **one** `resolve_document` (`PublishResolveDocument`, already built).
- The existing recovery sweep stays as the **safety net** for chunks that never report complete.

> Alternative considered & rejected: Python enqueues `resolve_document` itself after each chunk → N duplicate resolves per doc, needs its own dedup. The Go chunk-complete + doc-completion check reuses `chunk_extraction_state` which already exists for exactly this.

### D3 — `get_entities` source (Task 4 + Task 5)
Pass 2 needs "the entities just extracted for this doc/run". Add a Go read endpoint `POST /api/v1/internal/resolution/entities` returning closed-schema nodes whose `properties.provenance[].source_doc_id = doc_id` (optionally filtered by `run_id`), mirroring the `/candidates` pattern. Python `list_entities_for_document` calls it. (Rejected: nested-JSONB filtering through the generic `/query` endpoint — brittle; a dedicated endpoint is clearer and testable.)

### D4 — Threshold config consistency
`/internal/resolution/candidates` defaults `min_similarity` to **0.82** (Go handler), but BA-031 8b/8c gate band is **0.74 [0.72-0.75]** and Pass 2 `Deps.resolution_sim_threshold` defaults **0.74**. Pass 2 must pass the threshold explicitly in the candidates request (do not rely on the Go default). Surface this in Task 4; reconcile the documented value during the turn-on runbook's threshold reconciliation.

---

## File structure

**Python (`ennam.kg.python/`):**
- `src/ennam_kg/config.py` (modify) — add `extraction_queue_name`, Pass-2 thresholds.
- `src/ennam_kg/ai_client/client.py` (modify) — add `complete_json()`.
- `packages/.../kg_client/client.py` (modify) — add `get_node()`, `list_entities_for_document()`.
- `src/ennam_kg/worker.py` (modify) — add extraction-queue consumer; fill `extract_document` + `resolve_document` handlers.
- `src/ennam_kg/resolution/deps_factory.py` (new) — build `Pass1Deps` / Pass-2 `Deps` from worker context (keep handler thin).
- `src/ennam_kg/resolution/entities_client.py` (new) — **sync** `HttpxEntitiesClient` for `get_entities` (E1; mirrors `candidates_client.py`).

**Go (`ennam.kg.go/`):**
- `internal/handler/node.go` (modify) or `node_read.go` (new, + test) — bare `GET /api/v1/nodes/{id}` (E2; `NodeReader.GetNode` exists).
- `internal/handler/resolution_entities.go` (+ test) — `POST /api/v1/internal/resolution/entities`.
- `internal/handler/extraction.go` (modify) — add `POST /api/v1/internal/extraction/chunk-complete`; on doc completion call `PublishResolveDocument`.
- `internal/store/chunk_extraction_state.go` (modify if needed) — "all chunks for doc extracted?" query.
- `cmd/kg-server/main.go` (modify) — wire the two new handlers.

---

## Task 1 — Python adapters + extraction-queue consumer

**Files:** `config.py`, `ai_client/client.py`, `kg_client/client.py`, `worker.py`.

- [ ] **Step 1 (config):** add `extraction_queue_name: str = "ennam:extraction"` and `resolution_merge_confidence_threshold: float = 0.75`, `resolution_sim_threshold: float = 0.74`, `resolution_top_k: int = 10` to `Settings`. Test: settings load with defaults.
- [ ] **Step 2 (complete_json):** add `AIClient.complete_json(prompt, system_prompt=None) -> dict` = `complete()` with `response_format="json"` then `json.loads(content)`. Failing test: a stubbed `complete` returning `'{"a":1}'` yields `{"a":1}`; invalid JSON raises a clear error (fail loud).
- [ ] **Step 3 (get_node):** add `KGClient.get_node(node_id) -> dict` = `GET /api/v1/nodes/{id}`. ⚠️ This endpoint does **not exist yet** — it is added in Task 3 Step 0 (Go). This step adds only the Python client method; it may stay async (called inside the async `extract_document` handler). Test against a stub transport.
- [ ] **Step 4 (consumer):** add a third `RedisQueueConsumer(settings.extraction_queue_name)` and include it in the `asyncio.gather(...)` at `worker.py:234-235`, dispatching to `handle_message`. Test: a message on the extraction queue reaches `handle_message`.
- [ ] **Step 5:** commit `feat(ba031-A): extraction-queue consumer + complete_json/get_node adapters`.

## Task 2 — Implement `extract_document` → run_pass1

**Files:** `worker.py` (replace stub 190-201), `resolution/deps_factory.py` (new).

**Interfaces:** `build_pass1_deps(kg_client, ai_client, settings, chunks) -> Pass1Deps`. Handler: hydrate the chunk via `kg_client.get_node(chunk_id)` → `properties.content`/`content_hash`; build `Pass1Deps(kg=kg_client, ai=ai_client, model=LocalEmbeddingModel(settings.embedding_model_name), chunks=[(chunk_id, content_hash, text)])`; `await run_pass1(doc_id, run_id, project_id, deps)`; then call the Go chunk-complete endpoint (Task 3) to report this chunk extracted.

- [ ] **Step 1: Failing test** — given a stub KG returning a chunk node and a stub AI returning a valid closed-schema extraction JSON, the handler calls `run_pass1` and the stub KG records ≥1 `create_node` of a closed type with `provenance`. **Step 2:** FAIL. **Step 3:** implement (thin handler + `deps_factory`). **Step 4:** PASS. **Step 5:** commit `feat(ba031-A): extract_document handler runs Pass 1 closed-schema extraction`.

> Reuse the embedding-model instantiation pattern from `decompose.py:244-247`. Do NOT modify `run_pass1` itself.

## Task 3 — Go entity-listing endpoint + chunk-complete trigger

**Files:** `internal/handler/node.go` (or new `node_read.go`, +test), `internal/handler/resolution_entities.go` (+test), `internal/handler/extraction.go` (modify), `internal/store/chunk_extraction_state.go` (modify), `cmd/kg-server/main.go`.

- [ ] **Step 0 (bare GET node — E2):** add `GET /api/v1/nodes/{id}` → returns the full `KnowledgeNode` (incl. `properties.content` for chunks). The internal `NodeReader.GetNode(ctx, id)` interface already exists; this just registers a route + thin handler. Failing handler test: GET a seeded `document_chunk` returns its `properties.content`; unknown id → 404. Implement + wire in `main.go`. (Pass 1 chunk hydration in Task 2 depends on this.)
- [ ] **Step 1 (entities endpoint):** `POST /api/v1/internal/resolution/entities` body `{project_id, doc_id, run_id?}` → returns closed-schema nodes (`person|organization|event|location|artifact|project|document_ref|concept`) whose `properties->'provenance'` contains an entry with `source_doc_id = doc_id`. Failing handler test: seed 2 entities for doc D and 1 for doc E; query D returns exactly the 2. Implement store query + handler. PASS.
- [ ] **Step 2 (doc-completion query):** add `ChunkExtractionStateStore.AllChunksExtracted(ctx, docID, runID) (bool, error)` — true when no chunk for the doc/run is still `pending`/`extracting`. Failing test then implement.
- [ ] **Step 3 (chunk-complete endpoint):** `POST /api/v1/internal/extraction/chunk-complete` body `{project_id, doc_id, chunk_id, run_id}` → mark chunk `extracted`; if `AllChunksExtracted` → `PublishResolveDocument` **once** (idempotent: guard so re-delivery doesn't double-enqueue — e.g. only publish when transitioning the doc to a `resolving` marker). Failing handler test: last chunk complete publishes exactly one resolve message; a non-final chunk publishes none. Implement.
- [ ] **Step 4:** wire both handlers in `main.go`; `make -C ennam.kg.go test lint build`. Commit `feat(ba031-A): resolution entities endpoint + chunk-complete doc-level resolve trigger`.

## Task 4 — Implement `resolve_document` → run_pass2_shadow

**Files:** `worker.py` (replace stub 203-212), `resolution/entities_client.py` (new — **sync**), `resolution/deps_factory.py`.

**Interfaces (E1 — get_entities is SYNC):** new `HttpxEntitiesClient(base_url, api_key).list_for_document(project_id, doc_id, run_id=None) -> list[dict]` built with a **sync `httpx.Client`**, mirroring `HttpxRetriever` (`candidates_client.py`), calling the Task 3 entities endpoint. `build_pass2_deps(...) -> Deps` wires `model`, `HttpxRetriever(...)`, `ai_client`, `kg_client`, and `get_entities = lambda doc_id, run_id, project_id: entities_client.list_for_document(project_id, doc_id, run_id)` — a **plain sync** callable matching `Deps.get_entities: Callable[[str,str,str], list[dict]]` (pass2 calls it without `await` at `pass2.py:133`). Do **not** use the async `KGClient` here. Thresholds from settings; D4 — pass `resolution_sim_threshold` explicitly into the retriever call (don't inherit the Go 0.82 default).

- [ ] **Step 1: Failing test** — given a doc whose entities the (stubbed) sync entities client returns and a stub verifier confirming a same-type pair (confidence ≥ threshold), the handler calls `run_pass2_shadow` and records exactly one `create_merge_suggestion` (`decision='suggested'`); a rejected pair records none. Assert `get_entities` is invoked synchronously (returns a list, not a coroutine). **Step 2:** FAIL. **Step 3:** implement handler + sync `HttpxEntitiesClient` + `deps_factory`. **Step 4:** PASS. **Step 5:** commit `feat(ba031-A): resolve_document handler runs Pass 2 (sync entities client), writes merge_suggestions`.

## Task 5 — End-to-end integration test (the success criterion)

**Files:** `internal/integration/ba031_producer_e2e_test.go` (Go, `//go:build integration`) OR a Python integration test that drives the live stack — choose the side that can exercise queue+worker; mark DEFERRED if the live worker/model is unavailable in CI (fail loud, never skip silently).

- [ ] **Step 1:** ingest 2 documents sharing an entity in different surface forms ("AIO Link" in doc A, "AIOLink" in doc B). **Step 2:** assert Pass 1 wrote closed-schema entities for both with provenance. **Step 3:** assert the doc-completion trigger enqueued `resolve_document`. **Step 4:** assert ≥1 `merge_suggestions` row (`decision='suggested'`) linking the two entities, **with `apply_mode=shadow`** (no merge yet). **Step 5:** commit `test(ba031-A): producer chain E2E — ingest → entities → merge_suggestions`.

> This test is the gate that proves Phase A is done: it is the precondition the turn-on runbook (Step 4/7) assumes.

## Task 6 — Verify + checkpoint

- [ ] `cd ennam.kg.python && uv run pytest` green; `make -C ennam.kg.go test lint build` green; integration test green (or DEFERRED with reason).
- [ ] Write `.serena/checkpoint/backend-dev-<date>-ba031-phaseA.md`.
- [ ] Update memory `ba031-resolution-thresholds-gates`: producer chain WIRED; turn-on runbook now actionable.

---

## Definition of Done

- [ ] Worker consumes `ennam:extraction`; `extract_document` runs Pass 1 closed-schema (Tasks 1, 2).
- [ ] Go entity-listing endpoint + doc-level `resolve_document` trigger live, idempotent (Task 3).
- [ ] `resolve_document` runs Pass 2 and writes `merge_suggestions` (Task 4).
- [ ] E2E: 2-doc shared-entity ingest produces ≥1 `merge_suggestions` row in shadow mode (Task 5).
- [ ] All suites green; checkpoint + memory updated (Task 6).
- [ ] **No graph mutation** occurs (shadow-safe): Pass 2 only writes `merge_suggestions`; apply stays gated by the runbook.

## Risks

- **Per-chunk→per-doc fan-in (D2)** is the load-bearing design risk: the doc-completion trigger must be idempotent under message re-delivery (at-least-once Redis) — guard with a `resolving` state transition so a doc enqueues resolve exactly once. Test this explicitly (Task 3 Step 3).
- **`get_entities` correctness (D3):** provenance is a JSONB array; the `source_doc_id` containment query must be indexed/correct or large projects slow down. Verify the query plan; add a GIN index on `properties` if needed.
- **Threshold mismatch (D4):** if Pass 2 doesn't pass `resolution_sim_threshold` explicitly, it inherits the Go `/candidates` default 0.82 and silently under-retrieves vs the 0.74 gate band. Assert the request threshold in Task 4.
- **Cost:** Pass 2 calls the verifier (strong model) per candidate pair. The 8d cost ceiling guards extraction batches; confirm Pass 2 verify calls are also counted/bounded before running on a large corpus.

## Downstream

Completing Phase A makes the **turn-on runbook actionable** (it assumes suggestions exist). Sequence: **Phase A (this) → turn-on runbook → BA-033**.
