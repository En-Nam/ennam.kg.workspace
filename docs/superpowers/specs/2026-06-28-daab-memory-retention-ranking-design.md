# DAAB Memory Retention + Recall Ranking — Design

**Date:** 2026-06-28
**Status:** APPROVED (design) — ready for implementation plan
**Scope:** DAAB (`ennam.kg.go`) — the `agent_context` memory-of-record substrate
**Owner role:** DAAB is the ecosystem keystone owner of shared agent memory (`kg_remember`/`kg_recall`); AAAA + LAAM are thin consumers.
**Related decisions:** `mem:decisions/ecosystem-hermes-allocation`, `mem:decisions/daab-hermes-keystone-verification` (gate #2f), `mem:decisions/daab-rbac-isolation-keystone-gate-verdict`

---

## 1. Problem

`agent_context` is the shared memory substrate. Two failure modes are unaddressed today:

1. **Unbounded growth.** Nothing ever sets `is_archived`. Free-form memories (no `mem_key`) accumulate forever, and their 384-dim embeddings grow the `agent_context_embeddings` table + hnsw index without bound.
2. **Recall noise.** `kg_recall` ranks purely by RRF(semantic, lexical) with no recency/importance weighting, so stale memories compete equally with fresh, relevant ones.

The ecosystem decision frames these as **one problem**: *"AAAA stale-poisoning = DAAB unbounded-growth = one problem."* Gate #2f mandates: **rank at recall; compute decay/archive/dedup/growth-bound in a background job; enforce at recall.**

This design also closes a **pre-existing PII isolation hole in the recall path** (in scope because this work modifies recall and gate #2f requires user-scoped PII isolation).

## 2. Goals / Non-goals

**Goals**
- Bound memory growth (live working set **and** vector storage) for free-form memories.
- Improve recall quality with recency-weighted ranking.
- Respect user/project scope boundaries on recall (close gate #2f PII hole).
- Zero new infrastructure; mirror existing background-worker patterns.

**Non-goals (deferred — see §10)**
- Semantic (near-duplicate) dedup.
- Usage-based decay (decay-by-disuse). *(We add the column now; the policy ships later.)*
- Un-archive / recovery API; hard-delete TTL of archived rows.
- Full `audit_trail` records for the sweep (slog only for v1).
- Capture-path / gate-2 silent-amnesia work.

## 3. Established design decisions (product owner)

| # | Decision |
|---|----------|
| Q1 | Age-based archival of free-form memories; **`mem_key` rows are EXEMPT** (curated/durable). |
| Q2 | Growth cap per bucket `(project_id, user_id, scope)`, default **N=200**; archive oldest free-form beyond N; **archive, never hard-delete** the source row. |
| Q3 | **Exact** dedup now (normalize + hash, keep newest, archive older dups); semantic dedup deferred. |
| Q4 | Recall = RRF score **× recency decay** (configurable half-life). |

Reconciled additions from adversarial review (tech-consultant vs CTO):
- **`mem_key` rows are also EXEMPT from decay** (decay factor = 1.0) — symmetric with Q1's archival exemption, so a curated old `decision`/`correction` stays recallable.
- **Drop the embedding row when archiving** — otherwise the vector index grows forever and the growth-bound mandate is unmet.
- **Add `last_recalled_at` now** as cheap forward-compat insurance (table currently has no external consumers).
- **Scope-aware PII recall filter** is in scope.
- Sweep observability = **slog** (full `audit_trail` deferred — it needs an enum migration; out of proportion for a background janitor at v1).

## 4. Current-state facts (verified in code)

- `db/migrations/000068_agent_context.up.sql`: columns `project_id`, `user_id` (nullable), `source_agent`, `kind`, `scope`, `mem_key`, `content`, `tags`, `search_vector`, `is_archived` (default false), `created_at`, `updated_at`. Unique index on `(project_id, COALESCE(user_id,…), scope, mem_key) WHERE mem_key IS NOT NULL`. Sibling `agent_context_embeddings` (`vector(384)`, hnsw, `ON DELETE CASCADE` from `agent_context`).
- `store/agent_context.go`:
  - Free-form upsert (`mem_key==""`) always **INSERTs** → for free-form rows `updated_at == created_at` and never changes.
  - `RecallAgentContext` runs `recallSemantic` + `recallLexical`, each does `ORDER BY … LIMIT $N` **in SQL** (post-LIMIT before fusion), then `fuseAgentRecall` (RRF k=60, deterministic tie-break score desc → updated_at desc → id asc). Both branches filter `a.is_archived = false`.
  - `agentRecallFilters`: emits `AND a.user_id = $N` only when `UserID != ""`. **Bug:** (a) empty `UserID` ⇒ no user filter ⇒ returns other users' `scope='user'` rows; (b) `=` excludes NULL ⇒ a logged-in user never sees `scope='project'` (user_id NULL) shared rows.
- `service/oauth_refresh.go` + `cmd/kg-server/main.go:716-729` (`heartbeatFn`): the background-worker pattern to mirror (ticker loop, `Start(ctx)`/`Stop()`, single SQL UPDATE on a tick, no lock, logs rows-affected).
- `docker-compose.yml`: kg-server is a single container, no `deploy.replicas` ⇒ **single runner; no distributed lock needed**. All passes are idempotent, so a future multi-replica deploy degrades to duplicated work, not corruption.

## 5. Architecture

```
kg_recall (handler/agent_context.go)
        │
        ▼
RecallAgentContext (store)                 AgentContextRetentionWorker (service)
  scope-aware PII filter                     ticker loop (mirror oauth_refresh)
  over-fetch each branch (LIMIT max(K,50))   ├─ Pass A: dedup
  RRF fuse                                    ├─ Pass B: growth-bound
  × recency decay (mem_key ⇒ 1.0)            └─ DELETE embeddings for newly-archived rows
  trim to TopK                               slog counts; started in main.go
```

Two independent units, each testable in isolation:
- **Recall ranking** = pure read-path change in `store/agent_context.go`.
- **Retention sweep** = a new background worker + store method; pure SQL, no AI (AGENTS.md Rule 5).

## 6. Schema change (one small migration)

New migration pair `000071_agent_context_last_recalled_at.{up,down}.sql` (current head is `000070`):

```sql
-- up
ALTER TABLE agent_context ADD COLUMN IF NOT EXISTS last_recalled_at TIMESTAMPTZ;
-- down
ALTER TABLE agent_context DROP COLUMN IF EXISTS last_recalled_at;
```

- Nullable, **unpopulated in v1** (no write on the read path — honors Q1's "avoid write-on-read"). It exists so a future usage-based-decay policy needs no migration on a hot, consumer-attached table.

## 7. Recall ranking (read path)

### 7.1 Scope-aware PII filter
Replace the unconditional `a.user_id = $N` logic in `agentRecallFilters` with scope-aware visibility:

- `scope='user'` rows: returned **only** when `a.user_id` matches the caller's `user_id`. Never returned on an unscoped (empty `UserID`) recall.
- `scope='project'` and `scope='agent'` rows: visible within the project (these are shared by design); `user_id` is typically NULL and must NOT be excluded.

Concrete predicate (applied in both branches, combined with the existing `project_id` + `is_archived=false`):

```
AND (
      a.scope <> 'user'                       -- project/agent rows: shared
   OR ($userID <> '' AND a.user_id = $userID) -- user rows: only the owner
)
```

When the explicit `Kind`/`Scope`/`Tags` filters are supplied they still apply on top. The standalone `user_id = $N` filter is removed in favor of the scope-aware predicate. *(Edge case: an explicit `scope='user'` request with empty caller `UserID` returns nothing — correct: no owner, no user rows.)*

**Contract change (intentional).** This redefines the user-recall contract from *"a caller with `UserID` recalls **only** that user's memory"* (current store SQL `a.user_id = $N`, which over-filters and hides shared `scope='project'` rows — consultant bug (b)) to *"a caller recalls their own `scope='user'` rows **plus** shared `scope='project'`/`'agent'` rows."* The existing `agent_context_userscope_test.go` cases assert only **param wiring** through fakes, so they keep passing, but their doc-comment contract (*"recalls only that user's memory"*) must be updated, and a new store-level test (§11) must assert the new visibility. The cross-project isolation guarantee is unchanged (the `project_id` filter is untouched; cross-project recall stays blocked).

### 7.2 Over-fetch then decay
Each branch fetches `LIMIT max(TopK, 50)` (not `LIMIT TopK`). Decay+RRF then reorder the larger candidate set; `fuseAgentRecall` trims to `TopK` last. Without over-fetch, SQL's per-branch `LIMIT` truncates candidates before Go ever applies decay, making decay cosmetic.

### 7.3 Recency decay in `fuseAgentRecall`
`RecallAgentContext` passes `now` (injectable for tests) and `halfLifeHours` into `fuseAgentRecall`. For each fused row:

```
ageHours = max(0, now - row.UpdatedAt) in hours
decay    = 1.0                                  if row has mem_key
         = halfLifeHours / (halfLifeHours + ageHours)   otherwise
finalScore = rrfScore * decay
```

`SearchResult` does not currently carry `mem_key`; the recall SELECT must expose whether `mem_key IS NOT NULL` (e.g. a boolean projected into the row / properties) so `fuseAgentRecall` can apply the exemption. Tie-break chain is unchanged: `finalScore` desc → `updated_at` desc → `id` asc. `is_archived=false` filter unchanged.

## 8. Retention sweep (background worker)

New `service/agent_context_retention.go` — `AgentContextRetentionWorker`, structurally mirroring `OAuthRefreshWorker`: `Start(ctx)` spawns a goroutine with `time.NewTicker(interval)`; `Stop()` closes a stop channel; selects on `ticker.C` / `stopCh` / `ctx.Done()`. Started in `cmd/kg-server/main.go` beside the oauth/heartbeat workers, with `defer worker.Stop()`.

Each tick runs the passes in order. **Invariant for both passes:** operate only on rows where `is_archived = false AND mem_key IS NULL`; set `is_archived = true`; never touch `mem_key` rows; never `DELETE` the source row.

### Pass A — exact dedup (run first)
Within each bucket `(project_id, user_id, scope)` and identical normalized content:

```
survivor = ROW_NUMBER() OVER (
  PARTITION BY project_id, user_id, scope, md5(lower(btrim(content)))
  ORDER BY updated_at DESC, id
) = 1
```
Archive every non-survivor. Normalization is inline (`md5(lower(btrim(content)))`) — **not** coupled to `agent_context_embeddings.content_hash` (which lags / may be absent, written async by the Python worker). `id` in the ORDER BY makes the survivor deterministic when free-form timestamps tie.

### Pass B — growth-bound (run second, after dedup frees duplicates)
Within each bucket `(project_id, user_id, scope)`:

```
ROW_NUMBER() OVER (
  PARTITION BY project_id, user_id, scope
  ORDER BY updated_at DESC, id
) > bucket_cap
```
Archive every row beyond `bucket_cap` (oldest first). `PARTITION BY` groups NULL `user_id` (project-scope) rows into one bucket correctly — **never** use a correlated `inner.user_id = outer.user_id` form (silently drops NULLs).

### Embedding cleanup
In the same logical pass (same transaction as the archival UPDATE, or an immediately-following `DELETE` keyed off the just-archived ids):

```sql
DELETE FROM agent_context_embeddings
WHERE agent_context_id IN (<ids archived this tick>);
```
The source row survives (archived, recoverable); the regenerable derived embedding is dropped. This is what actually bounds vector storage. If a row is ever un-archived (deferred feature), the Python worker can regenerate its embedding.

### Observability
slog per tick: archived count for Pass A, Pass B, and embeddings deleted (mirrors `heartbeatFn`'s rows-affected logging). Since archival is reversible-by-SQL and `is_archived=true` rows remain queryable, this is sufficient traceability for v1.

## 9. Configuration

Via `config.yaml` + `system_settings` runtime override (existing pattern: DB overrides YAML, 60s cache):

| Setting | Default | Meaning |
|---------|---------|---------|
| `memory_recall_half_life_hours` | `720` (30 d) | Recall recency half-life (free-form only; mem_key exempt). |
| `memory_bucket_cap` | `200` | Max live free-form rows per `(project,user,scope)`. |
| `memory_retention_sweep_interval` | `1h` | Sweep tick interval. |

Config comments must state: cap + decay act on **free-form rows only**; `mem_key` rows are exempt from both.

## 10. Deferred — written follow-up tickets

1. **Usage-based decay** — populate `last_recalled_at` on recall + switch decay to disuse-based. Column ships now; policy later.
2. **Un-archive / recovery + hard-delete TTL** — archived rows are currently a one-way trapdoor. Need a recovery query and/or a TTL that hard-deletes long-archived rows (cascades to embeddings). Document the trapdoor until then.
3. **Semantic (near-duplicate) dedup** — needs embedding-pipeline integration + threshold tuning.
4. **`audit_trail` records for the sweep** — requires extending the `AuditOperation`/`AuditEntityType` CHECK enums (migration, pattern of 035) to add an archive operation + `agent_context` entity type.
5. **Capture contract / dedup ownership** — assert in writing: capture owns keyed dedup (the `mem_key` unique index, in-place upsert); retention owns free-form dedup only. Retention correctness is conditional on a complete capture path (gate-2 silent-amnesia).

## 11. Test plan (TDD)

**Recall (store):**
- `scope='user'` rows: user A's recall does NOT return user B's user-scoped rows; A's own are returned.
- `scope='project'`/`'agent'` (user_id NULL): returned to a logged-in caller (regression for the NULL-exclusion bug).
- Decay ordering: with equal RRF match, newer `updated_at` ranks above older.
- `mem_key` exempt from decay: a 1-year-old `mem_key` row outranks a weakly-matching recent free-form row.
- Over-fetch rescue: a recent-but-slightly-less-similar row that would be dropped at SQL rank #N survives into TopK after decay.

**Sweep (store/service):**
- Dedup keeps the newest of identical content; deterministic when timestamps tie (id tiebreak).
- Growth-bound archives exactly the oldest rows beyond `bucket_cap`.
- Project-scope (user_id NULL) bucket handled correctly.
- `mem_key` rows are never archived by either pass.
- Embedding row is deleted for each archived row.
- Idempotent: a second sweep with no new data archives nothing further.
- Worker lifecycle: `Start`/`Stop` clean shutdown.

## 12. Files touched (anticipated)

- `db/migrations/000071_agent_context_last_recalled_at.{up,down}.sql` — new column.
- `internal/store/agent_context.go` — scope-aware filter, over-fetch, decay (+ mem_key flag projection), new retention SQL store method(s).
- `internal/service/agent_context_retention.go` — new worker (+ test).
- `cmd/kg-server/main.go` — wire + start the worker.
- `config/config.yaml` (+ environment YAML if needed) — three settings + comments.
- Store/service/handler test files alongside the above.
- `internal/handler/agent_context_userscope_test.go` — update the doc-comment to the new contract (§7.1); param-wiring assertions stay as-is.
