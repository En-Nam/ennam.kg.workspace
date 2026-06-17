# BA-031 Phase 8d (Auto-Merge GA — Degree-Gated + Cost Ceiling) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn on auto-merge for **low-degree** entities while routing **high-degree hubs** to human review, behind a hard **per-run and per-document cost ceiling** (independent of BA-009) with a gleaning marginal-yield breaker and per-run cost telemetry. **Exit gate (GA): cost ceiling enforced before any batch; un-merge runbook drilled; degree-gating verified (hubs never auto-merge); auto-merge runs only after the 8c precision/recall gate passed.**

**Architecture:** A config-gated apply path consumes `merge_suggestions` (8c) and, per suggestion, either **applies** the merge transaction (8c `MergeService.Merge`) when `degree_max < degree_threshold`, or marks it `needs_review` when the suggestion touches a hub. A pre-batch cost estimator (Go) rejects/queues any extraction+resolution run whose projected token spend exceeds the per-run or per-document ceiling; the gleaning loop self-disables round 2 when marginal yield falls below a floor. Per-run token + $ are summed from the existing `AIUsageStore` and surfaced in the admin run view.

**Tech Stack:** Go (`store.AIUsageStore`/`models.AIUsageLog.CostCalculated`, `internal/ai`), PostgreSQL, Python (gleaning breaker in `extraction/gleaning.py` from 8a).

## Global Constraints

- **Degree-gated (OQ-005, FR-NEW-7):** `degree_max < degree_threshold` → auto-apply; `>= degree_threshold` → `needs_review` (human confirm), never auto-applied. NFR-256's 10% wrong-merge tolerance applies to **leaf nodes only — never hubs.**
- **Cost ceiling is independent of BA-009 (FR-NEW-2):** BA-009's budget is per-provider monthly ($50 default) and the **Claude Max path reports cost=0 and bypasses it** — so a per-run + per-document ceiling, enforced *before* a batch starts, is mandatory and cannot be delegated to BA-009.
- **Reversibility precondition:** auto-merge may turn on only after 8c's un-merge drill passed and the precision/recall gate passed. 8d does not re-implement merge/un-merge — it consumes them.
- **Apply uses the 8c merge transaction verbatim** (optimistic lock, lossless edges, audit, stamping) — no second merge implementation.
- **Go:** `make -C ennam.kg.go test lint build`. **Python:** `cd ennam.kg.python && uv run pytest`.

---

## File Structure

- `ennam.kg.go/internal/store/degree.go` (+ test) — node degree count.
- `ennam.kg.go/internal/service/apply_suggestions.go` (+ test) — consume `merge_suggestions` → apply or needs_review.
- `ennam.kg.go/internal/handler/apply_suggestions.go` (+ test) — `POST /api/v1/internal/resolution/apply`.
- `ennam.kg.go/internal/ai/cost_ceiling.go` (+ test) — pre-batch estimate + enforce.
- `ennam.kg.go/internal/store/run_cost.go` (+ test) — per-run token/$ summary from `AIUsageStore`.
- `ennam.kg.python/src/ennam_kg/extraction/gleaning.py` (modify) — marginal-yield breaker.
- `ennam.kg.go/config/config.yaml` (modify) — `resolution.degree_threshold`, `resolution.apply_mode`, `cost.per_run_ceiling_usd`, `cost.per_doc_ceiling_usd`, `gleaning.min_yield_per_100`.

---

## Task 1: Node degree count (Go store)

**Files:** Create `internal/store/degree.go`, `degree_test.go`.

**Interfaces:** `func (s *EdgeStore) Degree(ctx, nodeID string) (int, error)` — `SELECT count(*) FROM knowledge_edges WHERE (source_id=$1 OR target_id=$1) AND COALESCE(properties->>'superseded_by_merge','')=''` (exclude merge-superseded edges).

- [ ] **Step 1: Failing test** — a node with 3 live edges + 1 superseded edge returns degree 3. **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** commit `feat(ba031-8d): node degree count (excludes merge-superseded edges)`.

---

## Task 2: Cost ceiling estimator + enforcement (Go)

**Files:** Create `internal/ai/cost_ceiling.go`, `cost_ceiling_test.go`.

**Interfaces:**
- `type CostEstimate struct { Chunks, GleaningRounds int; EstInputTokens, EstOutputTokens int64; EstCostUSD float64 }`
- `func EstimateExtractionCost(chunks int, gleaningRounds int, avgChunkTokens int, model *models.AIProvider) CostEstimate` — `calls = chunks * (1 + gleaningRounds)`; cost from `model.CostPerInputToken`/`CostPerOutputToken` (same fields the selector uses, `selector.go:153`).
- `func EnforceCeiling(est CostEstimate, perRunCeilingUSD, perDocCeilingUSD float64) error` — returns a typed `ErrCostCeilingExceeded` (with the offending limit + estimate) when either ceiling is exceeded; the caller refuses to start the batch (fail loud) rather than silently truncating.

- [ ] **Step 1: Failing tests** — an estimate above `perRunCeilingUSD` returns `ErrCostCeilingExceeded`; below both ceilings returns nil; gleaning rounds multiply the call count. **Step 2:** FAIL. **Step 3:** implement (reuse the cost formula from `selector.go:153-155`). **Step 4:** PASS. **Step 5:** commit `feat(ba031-8d): pre-batch cost ceiling estimator + enforcement (BA-009-independent)`.

> Wire `EnforceCeiling` into the Go `/extract` trigger (8a Task 4) so a run that would exceed the ceiling is rejected before any LLM call. Add a step to call it there + a handler test asserting a 4xx/refusal when over-ceiling.

---

## Task 3: Per-run cost telemetry (Go)

**Files:** Create `internal/store/run_cost.go`, `run_cost_test.go`.

**Interfaces:** `func (s *RunCostStore) SummariseRun(ctx, runID string) (RunCost, error)` where `RunCost{RunID string; InputTokens, OutputTokens int64; CostUSD float64; Calls int}` — aggregates `AIUsageLog` rows for the run (`SUM(input_tokens), SUM(output_tokens), SUM(cost_calculated), COUNT(*)`). Surface it on the existing `GET /api/v1/ingestion/runs/{runId}` response (extend, don't add a new route).

- [ ] **Step 1: Failing test** — two usage-log rows for a run sum correctly. **Step 2:** FAIL. **Step 3:** implement (read `AIUsageLog` table the selector writes via `AIUsageStore.LogUsage`; confirm the run/session linkage column). **Step 4:** PASS. **Step 5:** commit `feat(ba031-8d): per-run cost telemetry (tokens + $ from AIUsageStore)`.

> Soft spot: confirm how `AIUsageLog` rows are correlated to a BA-031 run (a `session_id`/`run_id` column or a join). If no correlation exists, add the run id to the usage log write at the extraction/resolution call sites.

---

## Task 4: Gleaning marginal-yield breaker (Python)

**Files:** Modify `src/ennam_kg/extraction/gleaning.py`; Test: extend `tests/extraction/test_gleaning.py`.

**Interfaces:** extend `run_gleaning` (8a) with `min_new_per_round:int` — if a completed round yields fewer than `min_new_per_round` new in-vocab items, **disable further rounds** for the remainder of the batch (return a flag the caller records). This is the per-corpus marginal-yield breaker (don't pay 3× for ~1pp).

- [ ] **Step 1: Failing test** — a round yielding 0–1 new items with `min_new_per_round=2` stops further rounds and reports `breaker_tripped=True`; a productive round continues. **Step 2:** FAIL. **Step 3:** implement (additive to 8a's early-stop). **Step 4:** PASS. **Step 5:** commit `feat(ba031-8d): gleaning marginal-yield breaker`.

---

## Task 5: Apply-suggestions service (degree-gated) — FR-NEW-7

**Files:** Create `internal/service/apply_suggestions.go`, `apply_suggestions_test.go`.

**Interfaces:**
- Consumes: `MergeSuggestionStore.ListByProject(project,'suggested')` (8c), `EdgeStore.Degree` (Task 1), `MergeService.Merge` (8c Task 3), `MergeSuggestionStore.UpdateDecision`.
- Produces: `func (s *ApplySuggestionsService) Apply(ctx, projectID string, degreeThreshold int) (ApplyResult, error)` — for each `suggested` row: compute `degree_max = max(Degree(node_a), Degree(node_b))`; if `< degreeThreshold` → call `MergeService.Merge` and `UpdateDecision('applied')`; else `UpdateDecision('needs_review')` (no merge). Returns `{applied, needs_review, errors}`. **Hubs are never auto-merged.**

- [ ] **Step 1: Failing tests (test DB)** — a low-degree pair is merged + marked `applied`; a high-degree (≥ threshold) pair is **not** merged and marked `needs_review` (assert both nodes still `active`); a merge that errors leaves the suggestion `suggested` (not lost). **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** commit `feat(ba031-8d): degree-gated apply of merge suggestions`.

---

## Task 6: Apply endpoint + apply-mode config gate

**Files:** Create `internal/handler/apply_suggestions.go`, `apply_suggestions_test.go`; modify `config.yaml`.

**Interfaces:** `POST /api/v1/internal/resolution/apply` (`{project_id}`) — runs `ApplySuggestionsService.Apply` **only if** `config resolution.apply_mode == "apply"`; when `apply_mode == "shadow"` (default, the 8c posture) it returns a no-op with a clear message. `degree_threshold` from config (`resolution.degree_threshold`, default e.g. 10). Admin-gated.

- [ ] **Step 1: Failing test** — with `apply_mode="shadow"` the endpoint applies nothing; with `apply_mode="apply"` it invokes the service. **Step 2:** FAIL. **Step 3:** implement + add config keys (`resolution.apply_mode`, `resolution.degree_threshold`, `cost.per_run_ceiling_usd`, `cost.per_doc_ceiling_usd`, `gleaning.min_yield_per_100`). **Step 4:** PASS. **Step 5:** commit `feat(ba031-8d): apply endpoint + apply-mode/degree config gate`.

---

## Task 7: GA integration gate

**Files:** Create `internal/integration/ba031_ga_test.go`.

- [ ] **Step 1: Cost-ceiling enforcement test** — a run estimated over `per_run_ceiling_usd` is refused **before** any LLM call (assert zero model calls + a typed error).
- [ ] **Step 2: Degree-gating test** — seed a low-degree pair and a hub pair as `suggested`; run apply with a degree threshold; assert the low-degree pair merged (`applied`) and the hub pair `needs_review` (still `active`, not merged).
- [ ] **Step 3: Telemetry test** — after a run, `GET /api/v1/ingestion/runs/{runId}` returns non-zero token/$ summary.
- [ ] **Step 4: Reversibility re-confirm** — apply a low-degree merge via the endpoint, then `/internal/resolution/unmerge` (8c) restores it (byte-equivalent).
- [ ] **Step 5: GA gate decision (logged, Rule 12)** — GA allowed iff: cost ceiling enforced; degree-gating verified (hubs never auto-merge); un-merge drilled; **and the 8c precision/recall gate previously passed**. Record the decision + the live config (`degree_threshold`, ceilings, `apply_mode="apply"`). Surface any unmet condition rather than enabling apply.
- [ ] **Step 6: Commit** `test(ba031-8d): GA gate — cost ceiling, degree-gating, telemetry, reversibility`.

---

## Phase 8d Done — Definition of Done

- [ ] Per-run **and** per-doc cost ceiling enforced before batch start; over-ceiling runs refused with zero LLM calls (Tasks 2, 7).
- [ ] Gleaning marginal-yield breaker live (Task 4).
- [ ] Per-run token + $ surfaced on the run endpoint (Task 3).
- [ ] Degree-gated apply: low-degree auto-merged, hubs → `needs_review`, never auto-merged (Tasks 1, 5, 6, 7).
- [ ] Apply path reuses 8c merge + un-merge; reversibility re-confirmed (Task 7).
- [ ] GA gate decision logged; `apply_mode` flips to `apply` only when all conditions + the 8c precision/recall gate are green (Task 7).
- [ ] `make -C ennam.kg.go test lint build` clean; `cd ennam.kg.python && uv run pytest` green.

## Soft spots (read before writing)
(a) the `AIUsageLog` schema + how to correlate rows to a BA-031 run (Task 3); (b) the exact `models.AIProvider` cost field names (`CostPerInputToken`/`CostPerOutputToken`) used at `selector.go:153` (Task 2); (c) the `/extract` trigger from 8a Task 4 to wire `EnforceCeiling` into (Task 2); (d) how config is hot-reloaded for `apply_mode`/thresholds (`extraction-config` PUT vs restart) (Task 6).

## Self-Review
- **Spec coverage (8d):** OQ-005 / FR-NEW-7 degree-gating → Tasks 1, 5, 6, 7; FR-NEW-2 cost ceiling + gleaning breaker + telemetry → Tasks 2, 3, 4, 7; FR-008 routing reused (8a); auto-merge GA gate (spec §9 8d) → Task 7; reuses FR-005 merge + FR-NEW-1 un-merge from 8c (not re-implemented). NFR-256 10%-tolerance-leaf-only enforced by degree gating.
- **Placeholder scan:** no TBD/TODO; each task has concrete steps + assertions.
- **Type consistency:** `Degree`, `CostEstimate`/`EstimateExtractionCost`/`EnforceCeiling`/`ErrCostCeilingExceeded`, `RunCost`/`SummariseRun`, `ApplySuggestionsService.Apply`, and the config keys are referenced identically across tasks. Apply path consumes 8c's `MergeService.Merge`/`Unmerge` and 8c's `merge_suggestions` verbatim.
