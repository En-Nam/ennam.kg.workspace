# P3: BA-013 Benchmark Suite Expansion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Priority: P3 (MEDIUM)** — Quality gate for Phase 2 (95% accuracy exit condition). Needs BA-011 NL query pipeline working.

**Goal:** Expand basic benchmark skeleton (list questions + submit result) into a full suite: question CRUD, automated test runner, multi-level accuracy scoring, regression detection, and baseline comparison.

**Architecture:** Extends existing `benchmark.go` store/handler. New `BenchmarkRunner` service orchestrates parallel question execution via BA-011 NL pipeline. New `BenchmarkScorer` computes exact/semantic/partial/failure scores with SHA-256 result hashing.

**Tech Stack:** Go std lib, `crypto/sha256`, `internal/service/nl_query.go` (BA-011), PostgreSQL

**BA Reference:** `ennam.kg.requirements/documents/phase2/BA-013-benchmark-suite.md`

**Prerequisites:** BA-011 NL query pipeline (runner calls the NL→SQL pipeline for each question)

---

## What Already Exists

- `internal/models/benchmark.go` — BenchmarkQuestion, BenchmarkRun, BenchmarkResult ✅
- `internal/store/benchmark.go` — GetQuestionsByDataSource, CreateResult, GetRunByID ✅
- `internal/handler/benchmark.go` — GET questions, POST result ✅
- Migration 024 — benchmark_questions, benchmark_runs, benchmark_results ✅

## What's Missing

- **Store**: Question CRUD, Run CRUD, ListResults, Regression queries, Baseline management
- **Services**: BenchmarkRunner (parallel execution), BenchmarkScorer (accuracy), result hashing, regression detection
- **Handler**: 6 missing endpoints (create question, trigger run, get results, comparison, set baseline, verify answer)
- **Migration**: Extend models with is_active, verified_at, result_hash, baseline fields

---

## File Structure

### New Files

```
db/migrations/
├── 000028_extend_benchmarks.up.sql         # Add missing columns
├── 000028_extend_benchmarks.down.sql

internal/service/
├── benchmark_runner.go                     # Orchestrates parallel question execution
├── benchmark_runner_test.go
├── benchmark_scorer.go                     # Multi-level accuracy scoring + result hashing
├── benchmark_scorer_test.go
```

### Modified Files

```
internal/models/benchmark.go               # Add fields, constants
internal/store/benchmark.go                 # Add CRUD methods, result queries
internal/handler/benchmark.go               # Add 6 endpoints
cmd/kg-server/main.go                      # Wire runner + scorer into handler
```

---

## Task 1: Migration 028 — extend benchmark tables

- [ ] **Step 1: Write migration**

```sql
-- 000028_extend_benchmarks.up.sql

-- Extend benchmark_questions
ALTER TABLE benchmark_questions ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE benchmark_questions ADD COLUMN IF NOT EXISTS result_hash VARCHAR(64);
ALTER TABLE benchmark_questions ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE benchmark_questions ADD COLUMN IF NOT EXISTS needs_reverification BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE benchmark_questions ADD COLUMN IF NOT EXISTS created_by VARCHAR(255);

-- Extend benchmark_runs
ALTER TABLE benchmark_runs ADD COLUMN IF NOT EXISTS exact_matches INTEGER DEFAULT 0;
ALTER TABLE benchmark_runs ADD COLUMN IF NOT EXISTS semantic_matches INTEGER DEFAULT 0;
ALTER TABLE benchmark_runs ADD COLUMN IF NOT EXISTS partial_matches INTEGER DEFAULT 0;
ALTER TABLE benchmark_runs ADD COLUMN IF NOT EXISTS failures INTEGER DEFAULT 0;
ALTER TABLE benchmark_runs ADD COLUMN IF NOT EXISTS is_baseline BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE benchmark_runs ADD COLUMN IF NOT EXISTS alert_triggered BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE benchmark_runs ADD COLUMN IF NOT EXISTS created_by VARCHAR(255);

-- Index for active questions
CREATE INDEX IF NOT EXISTS idx_benchmark_questions_active
    ON benchmark_questions(data_source_id, is_active) WHERE is_active = true;

-- Index for baseline runs
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_baseline
    ON benchmark_runs(data_source_id, is_baseline) WHERE is_baseline = true;
```

- [ ] **Step 2: Commit**

```bash
git add db/migrations/000028_*
git commit -m "feat(db): extend benchmark tables with scoring, baseline, verification fields (BA-013)"
```

---

## Task 2: Extend Models + Store

- [ ] **Step 1: Add fields to existing models**

Add to BenchmarkQuestion: `IsActive`, `ResultHash`, `VerifiedAt`, `NeedsReverification`, `CreatedBy`
Add to BenchmarkRun: `ExactMatches`, `SemanticMatches`, `PartialMatches`, `Failures`, `IsBaseline`, `AlertTriggered`, `CreatedBy`

- [ ] **Step 2: Add store methods**

```go
// New methods on BenchmarkStore:
func (s *BenchmarkStore) CreateQuestion(ctx, q *BenchmarkQuestion) error
func (s *BenchmarkStore) UpdateQuestion(ctx, q *BenchmarkQuestion) error
func (s *BenchmarkStore) GetQuestionByID(ctx, id string) (*BenchmarkQuestion, error)
func (s *BenchmarkStore) CountActiveQuestions(ctx, dataSourceID string) (int, error)
func (s *BenchmarkStore) CreateRun(ctx, run *BenchmarkRun) error
func (s *BenchmarkStore) UpdateRun(ctx, run *BenchmarkRun) error
func (s *BenchmarkStore) ListRuns(ctx, dataSourceID string) ([]*BenchmarkRun, error)
func (s *BenchmarkStore) GetResultsByRun(ctx, runID string) ([]*BenchmarkResult, error)
func (s *BenchmarkStore) SetBaseline(ctx, runID string) error    // unset prev baseline, set new
func (s *BenchmarkStore) GetBaseline(ctx, dataSourceID string) (*BenchmarkRun, error)
func (s *BenchmarkStore) VerifyQuestion(ctx, id, resultHash string) error
func (s *BenchmarkStore) FlagReverification(ctx, dataSourceID string) error  // flag all questions
```

- [ ] **Step 3: Write tests, commit**

```bash
git add internal/models/benchmark.go internal/store/benchmark.go internal/store/benchmark_test.go
git commit -m "feat(store): extend BenchmarkStore with full CRUD, baseline, verification (BA-013)"
```

---

## Task 3: Benchmark Scorer

**Files:**
- Create: `internal/service/benchmark_scorer.go`
- Create: `internal/service/benchmark_scorer_test.go`

- [ ] **Step 1: Write failing tests**

Test cases:
- Exact match: identical result hashes → score=1.0, level="exact"
- Semantic match: same data, different column order or row order → level="semantic"
- Partial credit: correct tables/joins but wrong filter → level="partial"
- Failure: completely wrong → level="failure"
- Accuracy formula: `(exact + semantic) / total * 100`
- Sub-scores by difficulty AND query type
- Result hash: SHA-256 of sorted, normalized rows

- [ ] **Step 2: Implement BenchmarkScorer**

```go
type BenchmarkScorer struct {
    logger *slog.Logger
}

type ScoreResult struct {
    Score      float64 `json:"score"`
    ScoreLevel string  `json:"score_level"` // exact, semantic, partial, failure
    Detail     string  `json:"detail"`
}

// ScoreResult compares generated results against expected results.
func (s *BenchmarkScorer) Score(expected, actual json.RawMessage, expectedSQL, generatedSQL string) *ScoreResult

// ComputeResultHash normalizes and hashes query results for comparison.
// 1. Sort rows by all columns  2. NULL → "__NULL__"  3. Numeric: 4 decimal places
// 4. String: trim + lowercase  5. SHA-256 of JSON
func (s *BenchmarkScorer) ComputeResultHash(results json.RawMessage) string

// ComputeAccuracy calculates overall + breakdown scores for a run.
type AccuracyReport struct {
    Overall         float64            `json:"overall"`
    ByDifficulty    map[string]float64 `json:"by_difficulty"`
    ByQueryType     map[string]float64 `json:"by_query_type"`
    ExactMatches    int                `json:"exact_matches"`
    SemanticMatches int                `json:"semantic_matches"`
    PartialMatches  int                `json:"partial_matches"`
    Failures        int                `json:"failures"`
}
func (s *BenchmarkScorer) ComputeAccuracy(results []*models.BenchmarkResult, questions []*models.BenchmarkQuestion) *AccuracyReport
```

- [ ] **Step 3: Run tests, commit**

```bash
git add internal/service/benchmark_scorer.go internal/service/benchmark_scorer_test.go
git commit -m "feat(service): add BenchmarkScorer with multi-level accuracy and result hashing (BA-013)"
```

---

## Task 4: Benchmark Runner

**Files:**
- Create: `internal/service/benchmark_runner.go`
- Create: `internal/service/benchmark_runner_test.go`

- [ ] **Step 1: Implement BenchmarkRunner**

```go
type BenchmarkRunner struct {
    benchStore *store.BenchmarkStore
    nlService  *NLQueryService      // from BA-011
    scorer     *BenchmarkScorer
    logger     *slog.Logger
    concurrency int                 // default 5, max 20
    timeout     time.Duration       // default 60s per question
}

// RunBenchmark executes all active questions against the NL pipeline.
func (r *BenchmarkRunner) RunBenchmark(ctx context.Context, run *models.BenchmarkRun) error {
    // Pre-flight checks:
    // 1. Data source exists and connected
    // 2. >= 50 active verified questions (warn if < 50, don't block)
    // 3. No other active run for this data source

    // Execute:
    // 1. Get all active questions
    // 2. Run in parallel (semaphore with r.concurrency)
    // 3. For each question: submit to NL pipeline, capture SQL + results
    // 4. Score each result against expected
    // 5. Persist results
    // 6. Compute accuracy, update run

    // Regression detection:
    // 1. Get baseline run
    // 2. Compare: baseline (exact|semantic) but current (partial|failure) = regression
    // 3. If accuracy drop > 2% from baseline → set alert_triggered
}
```

- [ ] **Step 2: Write tests with mocked NL pipeline**

- [ ] **Step 3: Commit**

```bash
git add internal/service/benchmark_runner.go internal/service/benchmark_runner_test.go
git commit -m "feat(service): add BenchmarkRunner with parallel execution and regression detection (BA-013)"
```

---

## Task 5: Expand Handler with 6 New Endpoints

**Files:**
- Modify: `internal/handler/benchmark.go`

- [ ] **Step 1: Add endpoints**

```go
// Add to RegisterRoutes:
mux.HandleFunc("POST /api/v1/benchmark/questions", h.CreateQuestion)
mux.HandleFunc("PUT /api/v1/benchmark/questions/{id}", h.UpdateQuestion)
mux.HandleFunc("POST /api/v1/benchmark/questions/{id}/verify-answer", h.VerifyAnswer)
mux.HandleFunc("POST /api/v1/benchmark/runs", h.TriggerRun)
mux.HandleFunc("GET /api/v1/benchmark/runs/{id}", h.GetRun)
mux.HandleFunc("POST /api/v1/benchmark/runs/{id}/set-baseline", h.SetBaseline)
```

Endpoint details:
- `POST questions` → 201, create question with text, difficulty, query_type, expected_sql
- `PUT questions/{id}` → 200, update question fields
- `POST questions/{id}/verify-answer` → 200, execute expected_sql, store result_hash
- `POST runs` → 202 Accepted, triggers async benchmark run via runner
- `GET runs/{id}` → 200, run details with accuracy breakdown
- `POST runs/{id}/set-baseline` → 200, designate as baseline

- [ ] **Step 2: Wire runner + scorer into handler, update composition root**

- [ ] **Step 3: Commit**

```bash
git add internal/handler/benchmark.go cmd/kg-server/main.go
git commit -m "feat(handler): expand BenchmarkHandler with CRUD, runner trigger, and baseline (BA-013)"
```

---

## Task Summary

| # | Task | Type | Effort |
|---|------|------|--------|
| 1 | Migration 028 | Extend tables | Small |
| 2 | Extend models + store | Modify | Medium |
| 3 | Benchmark Scorer | New service | Large — hashing + multi-level scoring |
| 4 | Benchmark Runner | New service | Large — parallel execution + regression |
| 5 | Expand handler (6 endpoints) | Modify | Medium |
| **Total** | **5 tasks** | **~10 files** | |
