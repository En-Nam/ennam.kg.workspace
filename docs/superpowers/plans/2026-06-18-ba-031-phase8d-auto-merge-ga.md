# BA-031 Phase 8d (Auto-Merge GA — Degree-Gated + Cost Ceiling) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn on auto-merge for **low-degree** entities while routing **high-degree hubs** to human review, behind a hard **per-run and per-document cost ceiling** (independent of BA-009) with a gleaning marginal-yield breaker and per-run cost telemetry. **Exit gate (GA): cost ceiling enforced before any batch; un-merge runbook drilled; degree-gating verified (hubs never auto-merge); auto-merge runs only after the 8c precision/recall gate passed.**

**Architecture:** A config-gated apply path consumes `merge_suggestions` (8c) and, per suggestion, either **applies** the merge transaction (8c `MergeService.Merge`) when `degree_max < degree_threshold`, or marks it `needs_review` when the suggestion touches a hub. A pre-batch cost estimator (Go) rejects/queues any extraction+resolution run whose projected token spend exceeds the per-run or per-document ceiling; the gleaning loop self-disables round 2 when marginal yield falls below a floor. Per-run token + $ are summed from the existing `AIUsageStore` and surfaced in the admin run view.

**Tech Stack:** Go (`store.AIUsageStore`/`models.AIUsageLog.CostCalculated`, `internal/ai`), PostgreSQL, Python (gleaning breaker in `extraction/gleaning.py` from 8a).

> ## Sequential execution note (8b → 8c → 8d in one run) — CRITICAL SAFETY
> - **Build the full apply path but LEAVE IT OFF.** Tasks 1–6 (degree count, cost ceiling, telemetry + runs endpoint, gleaning breaker, apply service, apply endpoint) are built and tested. **The config default ships `resolution.apply_mode="shadow"`.** In an automated 8b→8c→8d run the 8c precision/recall gate is `PENDING-DATA` (no VI dataset), so **the agent MUST NOT flip `apply_mode` to `apply` and MUST NOT declare GA.** Auto-merge stays disabled until a human runs the 8c gate to a real PASS on `vi_blocking_v1.json`.
> - **GA gate (Task 7) outcome in the mạch = `PENDING-DATA`/`NOT-DECLARED`.** Tasks 7 Steps 1–4 (cost-ceiling enforced, degree-gating on synthetic seeds, telemetry, reversibility re-confirm) are real PASS/FAIL — run them. Step 5 (declare GA + flip `apply_mode`) is **blocked** on the 8c data gate; record it as not-declared, surface why (Rule 12). Do not enable apply to "complete" the plan.
> - **Migration:** 8d uses **000065** (after 8c's 000064). Integration steps needing the live stack/model → mark DEFERRED if unavailable, never skip silently.

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
- `ennam.kg.go/db/migrations/000065_ai_usage_log_run_id.up.sql`/`.down.sql` — add `run_id` to `ai_usage_log` (no run correlation exists today).
- `ennam.kg.go/internal/store/run_cost.go` (+ test) — per-run token/$ summary from `ai_usage_log` by `run_id`.
- `ennam.kg.go/internal/handler/extraction.go` (modify) — add `GET /api/v1/ingestion/runs/{runId}` (net-new; 8a only built the `POST .../extract` trigger).
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

> Wire `EnforceCeiling` into the existing 8a trigger **`POST /api/v1/ingestion/documents/{docId}/extract`** (`ExtractionHandler.TriggerExtract`, `handler/extraction.go:86`) so a run that would exceed the ceiling is rejected before any chunk is enqueued/extracted. Add a step to call it there (after enumerating chunks, before dispatch) + a handler test asserting a 4xx/refusal with zero dispatch when over-ceiling.

---

## Task 3: Per-run cost telemetry + runs status endpoint (Go) — heaviest 8d task

**Verified gaps this task must close (not optional):**
- `ai_usage_log` has **no run/session correlation column** (`models.AIUsageLog` = ProviderID, RequestType, InputTokens, OutputTokens, CostCalculated, LatencyMs, … — no run_id/session_id). Cost cannot be attributed to a BA-031 run today.
- There is **no `GET /api/v1/ingestion/runs/{runId}` endpoint and no run persistence** — `TriggerExtract` (8a) generates an ephemeral `run_id` and returns it but stores no run record. (`chunk_extraction_state` does carry `run_id`, so per-run extraction counts are recoverable from it.)

**Files:**
- Create: `db/migrations/000065_ai_usage_log_run_id.up.sql`/`.down.sql` — `ALTER TABLE ai_usage_log ADD COLUMN run_id TEXT;` + index `(run_id)`.
- Create: `internal/store/run_cost.go`, `run_cost_test.go`.
- Create/extend: `internal/handler/extraction.go` — add `GET /api/v1/ingestion/runs/{runId}`.

**Interfaces:**
- `func (s *RunCostStore) SummariseRun(ctx, runID string) (RunCost, error)` where `RunCost{RunID string; InputTokens, OutputTokens int64; CostUSD float64; Calls int}` — `SELECT SUM(input_tokens), SUM(output_tokens), SUM(cost_calculated), COUNT(*) FROM ai_usage_log WHERE run_id=$1`.
- Run-counts come from `chunk_extraction_state` (extracted/dropped/gleaning per `run_id`) — aggregate there for the counts half of the response.

- [ ] **Step 1: Migration + thread `run_id` through the usage-log write.** Add the column. Then thread the BA-031 `run_id` to `AIUsageStore.LogUsage` at the extraction/resolution AI call sites — `AIRequest` already carries `request_type` (IMP-006); add a `run_id` passthrough (Python `AIRequest` → Go AI proxy → `AIUsageLog.RunID`). Write a store test that a logged row carries `run_id`.
- [ ] **Step 2: Failing `SummariseRun` test** — two `ai_usage_log` rows with the same `run_id` sum correctly; rows with other run_ids are excluded.
- [ ] **Step 3:** FAIL → implement `RunCostStore`.
- [ ] **Step 4:** PASS.
- [ ] **Step 5: Build `GET /api/v1/ingestion/runs/{runId}`** returning `{run_id, extraction_model, resolution_model, counts:{extracted,dropped,gleaning_rounds,merged}, cost:{input_tokens,output_tokens,cost_usd,calls}}` — counts from `chunk_extraction_state`, cost from `RunCostStore`. Handler test asserts the shape. (This is the runs endpoint the spec §8 proposed but 8a did not build.)
- [ ] **Step 6: Commit** `feat(ba031-8d): run_id on ai_usage_log + per-run cost telemetry + runs status endpoint`.

> This task is larger than a single metric: it adds a column + threads run_id through the AI call path + builds a net-new status endpoint. Right-size it as its own reviewable unit; do not fold into Task 2.

---

## Task 4: Gleaning marginal-yield breaker (Python)

**Files:** Modify `src/ennam_kg/extraction/gleaning.py`; Test: extend `tests/extraction/test_gleaning.py`.

**Interfaces:** extend `run_gleaning` (8a) with a **keyword arg `min_new_per_round:int = 0`** (default 0 = breaker off, so 8a's existing caller + tests keep passing) — if a completed round yields fewer than `min_new_per_round` new in-vocab items, **disable further rounds** for the remainder of the batch (return a flag the caller records). This is the per-corpus marginal-yield breaker (don't pay 3× for ~1pp).

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

## Verified at plan-review time (2026-06-18)
- `models.AIProvider.CostPerInputToken`/`CostPerOutputToken` are `int64` microdollars (`ai_provider.go:65-66`, used at `selector.go:153`) — Task 2 formula confirmed.
- `models.AIUsageLog` has **no** run/session column (`ai_provider.go:76-86`) → Task 3 adds `run_id` (migration **000065**) + threads it through the AI call path.
- 8a's trigger is `POST /api/v1/ingestion/documents/{docId}/extract` (`extraction.go:86`); there is **no** `GET .../runs/{runId}` yet → Task 3 builds it. `run_id` is ephemeral in `TriggerExtract`; `chunk_extraction_state` carries `run_id` for the counts half.
- Migration numbering: 8c uses 000064, 8d uses 000065 (8a shipped 000061/062/063).

## Soft spots (read before writing)
(a) how to thread `run_id` from the Python `AIRequest` through the Go AI proxy to `AIUsageStore.LogUsage` (Task 3 — `request_type` already flows; add a parallel `run_id`); (b) how config is hot-reloaded for `apply_mode`/thresholds (`extraction-config` PUT vs restart) (Task 6); (c) confirm `chunk_extraction_state` has the fields needed for the runs-endpoint counts, else extend it (Task 3).

## Self-Review
- **Spec coverage (8d):** OQ-005 / FR-NEW-7 degree-gating → Tasks 1, 5, 6, 7; FR-NEW-2 cost ceiling + gleaning breaker + telemetry → Tasks 2, 3, 4, 7; FR-008 routing reused (8a); auto-merge GA gate (spec §9 8d) → Task 7; reuses FR-005 merge + FR-NEW-1 un-merge from 8c (not re-implemented). NFR-256 10%-tolerance-leaf-only enforced by degree gating.
- **Placeholder scan:** no TBD/TODO; each task has concrete steps + assertions.
- **Type consistency:** `Degree`, `CostEstimate`/`EstimateExtractionCost`/`EnforceCeiling`/`ErrCostCeilingExceeded`, `RunCost`/`SummariseRun`, `ApplySuggestionsService.Apply`, and the config keys are referenced identically across tasks. Apply path consumes 8c's `MergeService.Merge`/`Unmerge` and 8c's `merge_suggestions` verbatim.
