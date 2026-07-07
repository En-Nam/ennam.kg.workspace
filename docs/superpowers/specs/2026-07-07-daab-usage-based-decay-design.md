# DAAB Usage-Based Decay + Capture-Contract — Design

**Date:** 2026-07-07
**Status:** APPROVED (design) — ready for implementation plan
**Scope:** DAAB (`ennam.kg.go`) — the `agent_context` memory-of-record substrate
**Owner role:** DAAB is the ecosystem keystone owner of shared agent memory (`kg_remember`/`kg_recall`); AAAA + LAAM are consumers (not yet wired).
**Related:** `mem:backlog/agent-context-retention-followups` (items ① + ⑤), prior spec `docs/superpowers/specs/2026-06-28-daab-memory-retention-ranking-design.md` (§10 deferred these), `mem:decisions/daab-hermes-keystone-verification`
**Review provenance:** 2 rounds of adversarial review (CTO ⇄ tech-consultant, then steelman ⇄ synthesis-auditor). This design is the round-2 convergence; §7 records what was explicitly rejected and why.

---

## 1. Problem

The 2026-06-28 retention work shipped growth-bound archival + recency-ranked recall, but **deferred usage-based decay** (item ①) and left the **capture-vs-retention dedup ownership contract** (item ⑤) only implicit in code.

Two concrete gaps remain:

1. **Destructive eviction is blind to usage.** `RunRetentionSweep` Pass B archives free-form rows past `bucket_cap` ordered by `updated_at DESC` only, and archival **DELETEs the embedding** (`store/agent_context.go:349`) with no un-archive path. The first time any `(project_id,user_id,scope)` bucket crosses 200, the sweep can permanently evict the *most-recalled but oldest* memory. Column `last_recalled_at` exists (migration 000071) precisely to fix this, but is **read/written nowhere**.
2. **The capture-vs-retention dedup contract is unwritten.** Capture owns keyed dedup (`mem_key` unique upsert, in-place); retention owns free-form (`mem_key IS NULL`) dedup only. Code already behaves this way, but no doc + no test pins the *cap*-exemption of keyed rows in Pass B.

**Why now (not deferred):** The Pass B ordering change is provably inert while `last_recalled_at` is NULL (`GREATEST(updated_at, COALESCE(NULL, updated_at)) = updated_at` — bit-for-bit identical), so landing it now carries ~zero regression risk and installs the protection *before* the first bucket overflow — an event whose timing DAAB does not control or observe (no recall telemetry exists). Deferring is a race against an irreversible, unobservable data-loss operation. This is **not** the BA-033 case (that deferred for an *architectural prohibition* on the consumer; here the consumer is permitted and expected, merely not yet wired).

## 2. Goals / Non-goals

**Goals**
- Make free-form eviction usage-aware: a recalled-but-old memory outranks an un-recalled newer one for *survival*.
- Start populating `last_recalled_at` on recall (best-effort, zero read-path cost).
- Pin the capture-vs-retention dedup ownership contract in docs + one test.
- Zero new infrastructure; reuse the existing background-worker lifecycle pattern.

**Non-goals (stay deferred)**
- **Recall *ranking* change** — do NOT feed usage-recency into `fuseAgentRecall` decay (rich-get-richer feedback loop; see §7).
- Un-archive / recovery API + hard-delete TTL (item ②).
- Semantic near-duplicate dedup (item ③ — YAGNI until exact dedup proven insufficient).
- Full `audit_trail` for the sweep (item ④).
- Config-tunable throttle knob (use a `const`; add a `system_settings` knob only when real traffic proves tuning is needed).

## 3. Established design decisions (post-debate)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Effective-recency `= GREATEST(updated_at, COALESCE(last_recalled_at, updated_at))` drives **Pass B growth-bound ORDER BY only**. | Survival is ①'s point; NULL column ⇒ identical to today. |
| D2 | **Pass A (exact dedup) stays `updated_at DESC`.** | Duplicates share content; "which copy to keep" tracks write time, not recall time. Surgical. |
| D3 | **Recall ranking (`fuseAgentRecall`) is UNCHANGED** — stays `updated_at` recency decay. | Avoids rich-get-richer feedback loop; freezes read semantics as consumers attach. |
| D4 | Populate `last_recalled_at` via a **batched, best-effort, single-writer** flusher; **never** a goroutine-per-recall. | No pool contention, no shutdown leak; idle-when-quiet = no cost under zero traffic. |
| D5 | The write touches **`last_recalled_at` ONLY** — must NOT bump `updated_at`. Only the **top-K actually returned** are recorded, not the over-fetch pool. | `updated_at` is load-bearing in Pass A/B ordering + fusion decay; bumping it would make every recalled row look freshest AND reset its decay clock. |
| D6 | Throttle via SQL `WHERE last_recalled_at IS NULL OR last_recalled_at < now() - interval`, `interval` a **`const`** (default 1h). | Suppresses write amplification on hot rows; Postgres re-evals WHERE under row lock so concurrent double-recall updates 0 rows. |
| D7 | ⑤ = doc-comment at the capture/retention boundary + **one** new test: a keyed (`mem_key`) row driven past `bucket_cap` is NOT archived by Pass B. | The existing keyed test only exercises Pass A dedup; the cap-exemption path (`agent_context.go:329`) is untested. |

## 4. Current-state facts (verified in code)

- `db/migrations/000071_agent_context_last_recalled_at.up.sql`: adds nullable `last_recalled_at`, **no index**. Comment: *"forward-compat insurance … not populated in v1."*
- `store/agent_context.go`:
  - `RecallAgentContext` (~153) → `recallSemantic` + `recallLexical` (each `ORDER BY … LIMIT` in SQL, over-fetch `agentFetchLimit`=50) → `fuseAgentRecall` (RRF k=60; recency decay computed **in Go** as `halfLife/(halfLife+ageHours)` over `row.UpdatedAt`; `mem_key` rows decay-exempt; deterministic tie-break rank↓ → updated_at↓ → id↑).
  - `agentSelectCols` (~203) selects `a.updated_at` but **not** `a.last_recalled_at`; `scanAgentResults` (~255) does not scan it. → threading `last_recalled_at` into recall is only needed if D3 changed (it does not); for eviction (D1) the column is read in SQL, not Go.
  - `RunRetentionSweep` (~289): Pass A dedup `md5(lower(btrim(content)))` keep `updated_at DESC`; Pass B growth-bound keep top `bucket_cap` by `updated_at DESC`; both `WHERE is_archived=false AND mem_key IS NULL`; archived rows' embeddings `DELETE`d in same tx. Doc-comment (~286) asserts *"updated_at is preserved … Pass-B ordering stay stable"* — **must be updated** once Pass B orders by effective-recency.
- `service/agent_context_retention.go:48-69`: the worker-lifecycle template to reuse for D4 (`Start(ctx)` goroutine + `stopCh` + `sync.Once` `Stop()`). Started on `context.Background()` at `cmd/kg-server/main.go:~920`.
- Existing tests: `store/agent_context_retention_test.go` (`backdate()` helper writes synthetic timestamps; `idKeyed` asserts keyed row never archived in Pass A dedup); `store/agent_context_fusion_test.go` (synthetic-clock decay tests). Effective-recency eviction and keyed cap-exemption are **fully testable today** with these helpers — no consumer traffic required.
- P1 check (2026-07-07): `kg_recall` wired as MCP tool (`bridge/schema.go:1707`, `client.go:371`); **no application caller today** (dashboard 0, python 0, AAAA/LAAM unwired); no recall telemetry. ⇒ near-zero real traffic now; the D4 writer is idle-when-quiet.

## 5. Design — three independent tickets

Split because the pieces touch different clauses of the same query and have no inter-dependency. Ship order: T1 → T2 → T3 (T3 only becomes observable once recall traffic exists, but is safe to land anytime).

### T1 — ⑤ capture-contract finalize (~0 risk)
- Add a doc-comment block at `Remember` (capture) and `RunRetentionSweep` (retention) stating: *capture owns keyed dedup (`mem_key` unique upsert, in-place); retention archives free-form (`mem_key IS NULL`) only; keyed rows are exempt from BOTH dedup and cap.*
- New test: seed a `(project,user,scope)` bucket past `bucket_cap` including one `mem_key` row; assert Pass B archives free-form overflow but the keyed row survives.

### T2 — ① eviction-half (~0 risk, provably inert until T3 populates data)
- `RunRetentionSweep` Pass B: change the ranked-CTE `ORDER BY updated_at DESC` → `ORDER BY GREATEST(a.updated_at, COALESCE(a.last_recalled_at, a.updated_at)) DESC, a.id`.
- Update the Pass-B doc-comment invariant (`~286`) to state eviction ranking is usage-aware and eventually-consistent w.r.t. concurrent recalls.
- Record the decision *"no functional index on effective-recency; Pass B intentionally full-scans + window-sorts each tick"* so it is not later "optimized" into HOT-update-breaking index bloat.
- Test (integration, synthetic data via `backdate` + a new `setLastRecalled` helper): a bucket over cap where an *old-by-`updated_at`* row has a recent `last_recalled_at` and a *newer-written* row has none → assert Pass B evicts the newer-written, keeps the recalled one.

### T3 — ① write-half (low risk; idle-when-quiet)
- New store fn `TouchRecalled(ctx, ids []string)`:
  `UPDATE agent_context SET last_recalled_at = now() WHERE id = ANY($1) AND is_archived = false AND (last_recalled_at IS NULL OR last_recalled_at < now() - $2::interval)`, ids sorted (`ORDER BY id` semantics) to avoid deadlock ordering against the sweep. **Never** touches `updated_at`.
- New batched writer (reuse `agent_context_retention.go:48-69` lifecycle): a buffered channel receives top-K id-slices from recall; a single goroutine coalesces and flushes `TouchRecalled` every few seconds (or on buffer threshold). Drop-on-full (best-effort). Joined to server shutdown via the worker's `Stop()`.
- Recall handler: after building the response, push the **returned top-K ids** (guard `len(ids)==0`) onto the writer's channel — non-blocking, fire-and-forget. Recall's soft-fail-to-empty contract (`handler/agent_context.go:145-147` doc, success return `:203`) is untouched; a writer failure only logs.
- Throttle `interval` = `const` (default 1h).

## 6. Testing (TDD)

| Test | Ticket | Encodes |
|------|--------|---------|
| Keyed row past cap survives Pass B | T1 | ⑤ cap-exemption invariant (Rule 9) |
| Effective-recency eviction: recalled-old survives, un-recalled-new evicted | T2 | ①'s core purpose |
| Pass B eviction determinism: equal effective-recency ties break by `id` | T2 | stable, repeatable eviction set (not recall fusion — fusion is unchanged) |
| `TouchRecalled` throttle: 1st call bumps len(ids), immediate 2nd bumps 0, backdated bumps again | T3 | D6 write-amplification suppression |
| `TouchRecalled` empty ids = no-op; archived id updates 0 rows | T3 | D5 guards (4.1/4.2) |
| Batched writer: idle with no input; flushes on input; drop-on-full | T3 | D4 lifecycle |
| Recall stays 200 + returns results when writer errors (injected) | T3 | soft-fail contract preserved |
| (integration, `//go:build integration`) concurrent sweep vs touch on overlapping rows → no deadlock, final state is one of the documented-legal outcomes | T3 | §7 race is tolerable, not corrupting |

## 7. Explicitly rejected (with reason)

| Rejected | Why |
|----------|-----|
| Feed usage-recency into recall **ranking** (`fuseAgentRecall`) | Rich-get-richer feedback loop over a 720h half-life; changes read semantics as consumers attach. Only *survival* (Pass B) uses it. |
| Goroutine-per-recall write | Unbounded goroutines + a 3rd pool connection per hot-path call → starves recalls; detached goroutine leaks past shutdown (`database is closed`). Replaced by batched single-writer. |
| Bump `updated_at` on recall | Load-bearing in Pass A/B ordering + fusion decay; would make recalled rows look freshest and reset decay. |
| `system_settings` throttle knob | YAGNI — no traffic to tune against; `const` suffices. |
| Effective-recency in Pass A dedup | Duplicates are identical content; tie-break immaterial; keep surgical. |
| Functional index on `GREATEST(...)` | Pass B already full-scans; an index would break HOT updates on the hourly bump → index bloat. |
| Defer all of ① (round-1 synthesis) | Overcorrection: the eviction-half is provably inert-safe now and closes an irreversible-eviction race whose trigger DAAB can't observe. |

## 8. Rollout / risk

- T1, T2 are behavior-preserving under current (all-NULL) data — safe to merge immediately, verified by synthetic-data tests.
- T3 is idle under zero traffic; becomes active the moment any agent calls `kg_recall` (already possible via the MCP tool). No backfill needed — signal accumulates from first recall.
- Reversibility: half-life/decay is re-tunable; `last_recalled_at` can be nulled; no destructive migration. The only destructive op (eviction) is made *safer*, not newly enabled.
- Nested-repo note: all changes in `ennam.kg.go` (its own git). Commit/branch via `git -C ennam.kg.go`.

## 9. Success criteria

- Pass B evicts by usage-aware effective-recency (test-proven with synthetic data).
- `last_recalled_at` populated best-effort on recall without changing recall latency, determinism, or the soft-fail contract.
- Keyed (`mem_key`) rows proven exempt from Pass B cap.
- Recall *ranking* output unchanged vs pre-change (no consumer-visible ranking shift).
- All existing agent_context tests stay green; new tests cover the table in §6.
