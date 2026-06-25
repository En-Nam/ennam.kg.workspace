# Design — Memory-of-record vertical slice (`kg_remember` / `kg_recall`)

**Status:** DESIGN (approved for spec) · **Date:** 2026-06-24 · **Owner:** DAAB (ennam.kg) · **Service:** `ennam.kg.go` (+ `ennam.kg.python` embed worker)
**Implements:** Phase-1 keystone slice of `mem:decisions/ecosystem-hermes-allocation` · verified by `mem:decisions/daab-hermes-keystone-verification` · tracked in `mem:backlog/cto-directives-2026-06-23` (P1).

> **TL;DR (vi):** Xây *memory-of-record* làm substrate dùng chung: bảng sibling `agent_context` (+embeddings 384-dim), hai MCP/REST tool `kg_remember` (ghi, một write-path duy nhất, embed-on-write durable) và `kg_recall` (đọc, hybrid RRF, raw windowed, không LLM summary). Slice tối thiểu chạy end-to-end trong DAAB. Retention job + consumer-key class + `kg_search_sessions` **ngoài phạm vi** (spec riêng).

---

## 1. Goal & non-goals

### Goal
A working, end-to-end memory-of-record inside DAAB that any agent (DAAB-internal first; AAAA/LAAM later) can:
- **write** a durable, deduplicated memory via `kg_remember`, and
- **recall** it semantically + lexically via `kg_recall`,

scoped by project (and by user once the consumer-key class lands), with embeddings produced on the proven Python-local 384-dim path and never silently dropped.

### Non-goals (this slice — each is a separate spec)
- **Retention background job** (decay / archive / dedup-sweep / growth-bound). `is_archived` column is added now (cheap), but no job computes it yet; recall simply filters `is_archived = false`.
- **Consumer-key class** (D3): distinguishing consumer vs internal keys, `role=agent`, `allow_project_override=false`, and the `user_id`-bearing key. Until this lands, `user_id` is **nullable** and user-level isolation is **not** enforceable.
- **`kg_search_sessions`** — DESCOPED from the shared seam (D4).
- **`confidence` / `importance`** scoring fields — deferred to the retention spec.
- **Memory versioning** — `kg_remember` upserts in place; no version history table.

### Hard gate inherited
This slice ships value for the **single-platform** DAAB deployment regardless of Hermes. **Consumer enablement (AAAA/LAAM keys) stays blocked** behind gate **g2** (`g2a` RBAC CI-green AND `g2b` `user_id` live) per the CTO directive — out of scope here, but the design must not violate it.

---

## 2. Architecture overview

```
  Agent (MCP client)                         ennam.kg.go (bridge + API)                 ennam.kg.python
  ───────────────────                        ──────────────────────────                ───────────────
  kg_remember(kind,content,    ──MCP/REST──▶ Auth → resolve project/user/agent
             scope,mem_key?,                  from API key (NO opaque-UUID args)
             tags?)                           │
                                              ├─▶ store.UpsertAgentContext (sync)  ── INSERT/UPSERT row
                                              │                                        agent_context
                                              └─▶ queue.Publish(MsgEmbedAgentContext) ─────────────────▶  worker consumes
                                                  (Redis LPUSH, durable)                                  embeds content @384-dim
                                                                                                          (multilingual-e5-small)
                                              POST /api/v1/projects/{id}/agent-context/embeddings/batch ◀─ POST back
                                              store.UpsertAgentContextEmbedding ── UPSERT agent_context_embeddings

  kg_recall(query,kind?,       ──MCP/REST──▶ Auth → resolve project/user from key
            scope?,tags?,                     │  embed.Client.EmbedQuery(query) @384-dim (SYNC inline, Python /embeddings)
            top_k?)                           │  store.RecallAgentContext:
                                              │     • semantic: agent_context_embeddings <=> qvec  (scoped project_id[,user_id])
                                              │     • lexical : agent_context FTS on content        (scoped project_id[,user_id])
                                              │     • fuse    : ReciprocalRankFusion(k=60)
                                              └─▶ deterministic order (score → updated_at desc → id), raw windowed, NO LLM summary
```

Two reused, already-proven mechanisms (verified 2026-06-24 against the codebase):
- **Durable embed-on-write** mirrors the node-embedding path: Go publishes a job to the Redis queue (`internal/queue`), the Python worker generates the 384-dim vector locally, and POSTs it back to a batch endpoint (mirror of `DocumentHandler.BatchUpsertEmbeddings`, `internal/handler/document.go:171-212`). This is the durable, **not-request-bound** pattern — distinct from and **not** to be confused with the buggy request-context goroutine in `internal/handler/embedding.go:74-86`, which is the unrelated **1536-dim table-embedding** path.
- **Sync query-embed at recall** mirrors `SearchHandler.ensureQueryEmbedding` (`internal/handler/search.go:57-70`) calling `embed.Client.EmbedQuery` (`internal/embed/client.go:36-66`, Python `POST /api/v1/embeddings`, 384-dim).

---

## 3. Capture model (the crux — resolved)

**`kg_remember` is the single, explicit write path.** There is no second auto-snapshot mechanism (rejected as YAGNI + garbage-memory risk; curation stays deliberate, never an unconditional hook — also keeps write off LAAM's local 8B per Rule 13).

**"Always-runs capture" (D8) = embed is never silently dropped, NOT a sync inline embed.** The row is written synchronously; the embed job is enqueued on the **durable** Redis queue. A durable queue satisfies the anti-gate-2 property ("silent amnesia") *better* than a synchronous cross-service call that can fail and block (or abort) the write. The capture contract is defined **once**, at `kg_remember` — not piggybacked on the skippable session-end gate-2.

**Embedding dimension is pinned to 384-dim Python-local** (`intfloat/multilingual-e5-small`). The Go `generateDescription` / `text-embedding-3-small` 1536-dim path (`internal/service/embedding_generator.go`) is **forbidden** for `agent_context` — the two embedding spaces are incompatible and must not be conflated.

**e5 asymmetric prefix (correctness requirement).** The model requires asymmetric prefixes for retrieval quality. The write path embeds content as a **passage** (`LocalEmbeddingModel.encode_passage`, prefix `"passage: "`); the recall path embeds the query as a **query** (`encode_query` / `embed.Client.EmbedQuery` → Python `/api/v1/embeddings` default `input_type="query"`, prefix `"query: "`). Getting this wrong silently degrades recall.

**Stated trade-off (eventual-consistency window):** a `kg_recall` issued immediately after `kg_remember`, before the worker finishes embedding, will **not** match the new memory on the *semantic* branch — but the **FTS branch hits it instantly** (the row + its `search_vector` exist synchronously). Acceptable; documented behavior. Recall must therefore never assume an embedding exists for every row (left-join, see §6).

**Alternative considered — sync inline embed (rejected).** Because the Python `/api/v1/embeddings` endpoint already exists, `kg_remember` *could* call it synchronously and write the embedding inline — materially less code (no new queue message type, worker handler, or batch endpoint). Rejected: a synchronous cross-service call in the write path adds latency (CTO open-Q#3) and, on failure, leaves the embedding permanently missing unless a retry is bolted on — which reintroduces exactly the silent-amnesia failure mode D8 targets. The durable queue *is* the retry/durability mechanism, so async is the principled fit for "always-runs." (If the queue extension proves disproportionately costly at plan time, revisit sync-inline + a failed-embed reconcile pass.)

---

## 4. Data model

New migration **`000068`** (current head verified at `000067_add_derived_record`; `agent_context` + `agent_context_embeddings`).

### `agent_context`
| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK DEFAULT uuid_generate_v4()` | |
| `project_id` | `UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE` | tenant boundary (this slice's enforced scope) |
| `user_id` | `UUID NULL` | **nullable this slice**; populated + enforced once D3 consumer-key lands |
| `source_agent` | `TEXT NOT NULL` | resolved from API key (`DeveloperName`/key prefix); never a tool arg |
| `kind` | `TEXT NOT NULL CHECK (kind IN ('preference','decision','fact','correction'))` | enumerated; extensible by migration |
| `scope` | `TEXT NOT NULL CHECK (scope IN ('project','user','agent'))` | the *level* the memory is about (agent declares); value resolved from key |
| `mem_key` | `TEXT NULL` | optional idempotency/upsert key → bounded growth |
| `content` | `TEXT NOT NULL` | the embedded + FTS-indexed payload |
| `tags` | `TEXT[] NOT NULL DEFAULT '{}'` | optional secondary filter |
| `search_vector` | `tsvector`, **trigger-maintained** | mirror `update_search_vector` trigger pattern (migration `000010`); `BEFORE INSERT OR UPDATE OF content, tags`; english config (see §9 note) |
| `is_archived` | `BOOLEAN NOT NULL DEFAULT false` | retention hook (no job yet; recall filters it) |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | bumped on upsert; recall tiebreak |

**Upsert key (dedup):** partial unique index
`CREATE UNIQUE INDEX ... ON agent_context (project_id, COALESCE(user_id,'00000000-...'::uuid), scope, mem_key) WHERE mem_key IS NOT NULL;`
`kg_remember` with a matching `(project_id, user_id, scope, mem_key)` performs `INSERT ... ON CONFLICT DO UPDATE` (replace `content`/`tags`, bump `updated_at`). On content change, the embed job is re-enqueued.

**Indexes:** btree `(project_id)`, `(project_id, user_id)`, `(kind)`; GIN on `search_vector`; GIN on `tags`.

### `agent_context_embeddings`
Mirror of `knowledge_node_embeddings` (migration `000055`):
| Column | Type | Notes |
|---|---|---|
| `id` | `UUID PK DEFAULT uuid_generate_v4()` | |
| `project_id` | `UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE` | redundant-but-cheap scope guard |
| `agent_context_id` | `UUID NOT NULL REFERENCES agent_context(id) ON DELETE CASCADE` | |
| `content_hash` | `TEXT NOT NULL` | skip re-embed when unchanged |
| `embedding` | `vector(384) NOT NULL` | |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | |
| | `UNIQUE (agent_context_id)` | one embedding per memory |

Vector index: HNSW (or ivfflat, matching whatever `000055` uses for consistency) on `embedding` with cosine ops.

---

## 5. Tool surface

Both tools are bridge-mirrored (MCP schema in `internal/bridge/schema.go` + HTTP route in `internal/bridge/client.go` `toolRoutes`). Neither takes `project_id`/`user_id`/`source_agent` as arguments — all resolved from the authenticated key via `DeveloperIdentity.ResolveProjectID("")` (`internal/middleware/auth.go:77-89`).

### `kg_remember` — write (`RouteWrite`)
| Param | Type | Req | Notes |
|---|---|---|---|
| `kind` | enum string | ✓ | preference / decision / fact / correction |
| `content` | string | ✓ | the memory text |
| `scope` | enum string | ✓ | project / user / agent |
| `mem_key` | string | – | upsert/idempotency key |
| `tags` | string[] | – | |

Returns `{ id, status: "created"|"updated", embedding: "queued" }`. Soft-validates enums (400 on bad enum). Writes row sync, enqueues embed.

### `kg_recall` — read (`RouteRead`, `readOnlyHint=true`)
| Param | Type | Req | Notes |
|---|---|---|---|
| `query` | string | ✓ | embedded @384-dim inline + used for FTS |
| `kind` | enum string | – | filter |
| `scope` | enum string | – | filter |
| `tags` | string[] | – | filter (any-match) |
| `top_k` | int | – | default 8, cap 50 |

Returns `{ results: [{ id, kind, scope, content, snippet, tags, source_agent, created_at, updated_at, score }] }`, ordered deterministically. **Raw windowed `ts_headline` snippet, no LLM summary.** **Soft-fail:** any embed/store error → `{ results: [] }` + logged, never a 5xx to the agent (recall must never break an agent's turn).

---

## 6. Recall query & ranking

1. Resolve `project_id` (required; from key default) and `user_id` (nullable; from key when present).
2. **Semantic branch:** `EmbedQuery(query)` → `SELECT ... FROM agent_context_embeddings e JOIN agent_context a ON a.id=e.agent_context_id WHERE a.project_id=$p [AND a.user_id=$u] AND a.is_archived=false [AND a.kind=$k] [AND a.scope=$s] [AND a.tags && $tags] ORDER BY e.embedding <=> $qvec LIMIT topK`.
3. **Lexical branch:** same filters, `WHERE a.search_vector @@ plainto_tsquery('english', $query) ORDER BY ts_rank(...) LIMIT topK`, with windowed `ts_headline`.
4. **Fuse:** `store.ReciprocalRankFusion([semantic, lexical], k=60, limit=topK)` (`internal/store/rrf.go`). Both branches return `[]store.SearchResult`; `agent_context` rows hydrate it directly (`ID`=`agent_context.id`, `ProjectID`, `Scope`, `CreatedAt`/`UpdatedAt`, `Rank`=branch rank, `Headline`=windowed snippet, `content` carried in `Properties`/`Title`) — **no new result struct needed**. RRF dedupes on `row.ID`.
5. **Deterministic order:** the shared `rrf.go` sorts by fused score → `UpdatedAt` desc only. To guarantee full determinism without editing the shared function, recall applies a **stable re-sort on the RRF output**: score desc → `updated_at` desc → `id` asc.
6. Memories without an embedding yet (eventual-consistency window) still surface via the lexical branch — recall **must not** inner-join embeddings (left-join or separate-query the embedding set).

---

## 7. RBAC isolation (must-have)

The existing guards (`requireProjectAccess` / `requireNodeProjectAccess`, `internal/handler/authz.go`) cover **only `knowledge_nodes` paths** — they do **not** auto-protect the new table. Therefore:

- **`kg_recall` and `kg_remember` apply project scoping inside the store query themselves** (`WHERE project_id = <resolved>`), using the key-resolved project, never a body-supplied one (no body-override surface exists because `project_id` is not a tool arg).
- New gating test **`internal/handler/agent_context_isolation_test.go`** (mirrors `recall_isolation_test.go`): 2-project / 2-key seed; assert a project-A key cannot `kg_recall` project-B memories and cannot read a project-B `agent_context` row by id. RED before wiring, GREEN after.
- `user_id` filter is **wired but inert** this slice (always nullable) — its enforcement is gate `g2b`, blocked on the D3 consumer-key migration. Documented so it is not mistaken for live user isolation.

---

## 8. Components & boundaries (isolation/clarity)

| Unit | Responsibility | Depends on |
|---|---|---|
| `db/migrations/000068_agent_context*.sql` | tables, indexes, trigger, upsert constraint | pgvector, `projects` |
| `internal/store/agent_context.go` | `UpsertAgentContext`, `RecallAgentContext`, `UpsertAgentContextEmbedding` | `database/sql`, `rrf.go` |
| `internal/handler/agent_context.go` | `kg_remember` / `kg_recall` REST handlers; key-resolve; soft-fail; isolation | store, `embed.Client`, `queue`, `authz` |
| `internal/queue` (extend) | `MsgEmbedAgentContext` type const + payload (carry `agent_context_id`, `project_id`, `content`); publish via existing `Publisher.Publish` (envelope mirrors `IndexMessage`, `publisher.go:18-35`) | existing Redis publisher |
| `ennam.kg.python` worker (extend) | new `elif msg_type == "embed_agent_context"` in `worker.py` `handle_message`; `encode_passage` @384; POST back | existing `LocalEmbeddingModel` + HTTP client |
| batch endpoint (mirror `BatchUpsertEmbeddings`, `document.go:171-212`) | `POST /api/v1/projects/{id}/agent-context/embeddings/batch` → `store.UpsertAgentContextEmbedding` | store |
| `internal/bridge/{schema,client}.go` | 2 tool schemas + 2 routes | — |

Each unit is independently testable; the handler is the only place that knows all three (store + queue + embed).

---

## 9. Testing & known limitations

**Tests**
- `internal/store/agent_context_test.go` — upsert dedup, recall fusion ordering, archived filtering, embedding left-join (no-embedding row still recalled).
- `internal/handler/agent_context_test.go` — key-resolve (no project arg), enum validation, soft-fail on embed error, `kg_recall` no-write-path test.
- `internal/handler/agent_context_isolation_test.go` — cross-project isolation (§7).
- **Bridge invariant bumps** (verified current counts 42/39/3 → 44/41/3):
  - `internal/bridge/schema_test.go:55` `42 → 44`
  - `internal/bridge/handler_test.go:276` `42 → 44`
  - `internal/bridge/client_test.go:216` `39 → 41`; `:1070` total `39 → 41`; `:1060` route-class Write `22 → 23` (`kg_remember`), Read `17 → 18` (`kg_recall`)
  - integration_test tool enum (add both names)
- Python worker unit test: `MsgEmbedAgentContext` → 384-dim → batch POST shape.

**Known limitations (documented, accepted)**
- **FTS is english-config-only** (`internal/store/search.go` precedent). Vietnamese/CJK lexical recall is weak; **semantic branch (multilingual-e5-small) carries non-English recall**. A VN FTS config is out of scope (same limitation as existing search).
- **Eventual-consistency window** on semantic recall right after remember (§3) — FTS covers the gap.
- **No user-level isolation** until D3 (`user_id` nullable). Single shared-project user-vs-user leakage is impossible to prevent this slice — by design, gated.
- `make test` `-race` / `golangci-lint` / integration suite need CI (no cgo / linter / DB on dev box) — same constraint noted in the RBAC fix.

---

## 10. Open items handed to the plan
- **Which queue carries the worker's jobs.** `worker.py` `handle_message` consumes one queue handling `index_*`/`extract_document`/`resolve_document`, but the Go side has multiple publishers (indexing `Publisher`, plus `IngestionPublisher`/`ExtractionPublisher`). The plan must confirm the queue name the worker BRPOPs and publish `embed_agent_context` to **that** queue (reuse the matching Go publisher or add one targeting it). Do not assume the indexing `Publisher` is correct without checking the queue name.
- Whether to reuse the `IndexMessage` envelope (add an `agent_context_id,omitempty` field + new type) or add a dedicated message struct/publisher — pick the smaller change once the target queue is known.
- Confirm the e5 model is invoked via `encode_passage` in the new worker handler (write side) — not `encode` without prefix.

*(Resolved during spec verification: next migration = `000068`; `search_vector` is trigger-maintained per migration `000010`; `SearchResult` reused directly for RRF.)*

---

## Provenance
Brainstormed 2026-06-24 from the ratified verdicts in `mem:decisions/ecosystem-hermes-allocation` (CTO) and `mem:decisions/daab-hermes-keystone-verification` (DAAB principal), scoped per `mem:backlog/cto-directives-2026-06-23` P1. Load-bearing infra claims (embeddings table 384-dim, RRF k=60, durable queue + node-embedding callback pattern, embed bug locus, bridge registration counts, key→project resolution, isolation guards) were verified by direct code inspection of `ennam.kg.go` on 2026-06-24 before writing.
