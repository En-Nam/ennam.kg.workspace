# DAAB Usage-Based Decay + Capture-Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `agent_context` free-form eviction usage-aware (recalled-but-old memories survive over un-recalled-newer ones), populate `last_recalled_at` on recall via a batched best-effort writer, and pin the capture-vs-retention dedup ownership contract in docs + tests.

**Architecture:** Three independent tickets in `ennam.kg.go`. T1 (doc + one test) and T2 (Pass B SQL ordering swap, provably inert until data exists) ship as **one zero-risk PR**. T3 (write path) ships as a **separate PR**: a new store fn `TouchRecalled` + a batched single-writer worker reusing the `AgentContextRetentionWorker` lifecycle pattern, wired into the recall handler as fire-and-forget.

**Tech Stack:** Go (stdlib `net/http`, `database/sql`, `log/slog`), PostgreSQL 16, `github.com/lib/pq`. Integration tests are `//go:build integration` and need a live DB via `KG_TEST_DSN`.

## Global Constraints

- **Never bump `updated_at` on recall.** It is load-bearing in Pass A ordering (`store/agent_context.go:304`), Pass B ordering (`:326`), and fusion decay (`:412`). The recall write touches `last_recalled_at` ONLY.
- **Do NOT change recall ranking.** `fuseAgentRecall` (`store/agent_context.go:392`) stays on `updated_at` decay. Usage-recency feeds Pass B *survival* only. (Rejected: rich-get-richer feedback loop.)
- **No goroutine-per-recall.** Use one batched writer. (Rejected: pool contention + shutdown leak.)
- **No config knob.** Throttle interval is a Go `const` (`time.Hour`). (Rejected: YAGNI — no traffic to tune against.)
- **Effective-recency** `= GREATEST(updated_at, COALESCE(last_recalled_at, updated_at))`. NULL column ⇒ identical to current behavior.
- **Pass A (exact dedup) stays `updated_at DESC`** — only Pass B changes.
- Go style: `fmt.Errorf("ctx: %w", err)`, `log/slog`, table-driven where natural. Run tests with `-race`. Integration tests: `go test -tags=integration ./internal/... -run <Name>`.
- All work is in the nested repo `ennam.kg.go` — commit via `git -C ennam.kg.go` or `cd ennam.kg.go` first.

---

## File Structure

**PR1 — T1 + T2 (zero-risk):**
- Modify `ennam.kg.go/internal/store/agent_context.go` — Pass B ranked-CTE `ORDER BY` → effective-recency; update Pass-B doc-comment; add capture/retention ownership doc-comment.
- Modify `ennam.kg.go/internal/store/agent_context_retention_test.go` — add `setLastRecalled` helper; add `TestRetention_KeyedRowExemptFromCap` (T1); add `TestRetention_UsageRecencyEvictsColdOverHot` (T2).

**PR2 — T3 (write path):**
- Modify `ennam.kg.go/internal/store/agent_context.go` — add `TouchRecalled`; add `const defaultRecalledTouchMinInterval`.
- Modify `ennam.kg.go/internal/store/agent_context_retention_test.go` — add `TestTouchRecalled_ThrottleArchivedGuardAndUpdatedAtUntouched`.
- Create `ennam.kg.go/internal/service/agent_context_touch.go` — `RecalledTouchWriter` (batched worker).
- Create `ennam.kg.go/internal/service/agent_context_touch_test.go` — writer unit test (no DB).
- Modify `ennam.kg.go/internal/handler/agent_context.go` — add `recalledEnqueuer` field + ctor param; enqueue returned top-K ids in `Recall`.
- Modify `ennam.kg.go/cmd/kg-server/main.go` — construct/Start/Stop the writer; pass into handler ctor.
- Modify existing handler-test call sites of `NewAgentContextHandler` — pass `nil` for the new param.

---

# PR 1 — T1 (⑤ capture-contract) + T2 (① eviction-half)

## Task 1: T2 — Pass B eviction orders by effective-recency

**Files:**
- Modify: `ennam.kg.go/internal/store/agent_context.go` (Pass B CTE ~322-334; doc-comment ~285-288)
- Test: `ennam.kg.go/internal/store/agent_context_retention_test.go`

**Interfaces:**
- Consumes: `RunRetentionSweep(ctx, bucketCap int) (RetentionSweepResult, error)` (existing), `mustUpsert`, `backdate`, `assertArchived`, `acProj`, `setupTestDB`, `acSeedProject` (existing test helpers).
- Produces: `setLastRecalled(t, db, id, ts)` test helper (used again in PR2).

- [ ] **Step 1: Add the `setLastRecalled` test helper**

In `internal/store/agent_context_retention_test.go`, add after `assertArchived` (near line 108):

```go
func setLastRecalled(t *testing.T, db *sql.DB, id string, ts time.Time) {
	t.Helper()
	if _, err := db.ExecContext(context.Background(), `UPDATE agent_context SET last_recalled_at=$2 WHERE id=$1`, id, ts); err != nil {
		t.Fatalf("setLastRecalled %s: %v", id, err)
	}
}
```

- [ ] **Step 2: Write the failing test**

Add to `internal/store/agent_context_retention_test.go`:

```go
// A row that is old by updated_at but recently recalled must survive Pass B,
// while a newer-written but never-recalled row in the same bucket is evicted.
// This is the whole point of usage-based decay.
func TestRetention_UsageRecencyEvictsColdOverHot(t *testing.T) {
	db := setupTestDB(t)
	acSeedProject(t, db)
	s := store.NewAgentContextStore(db)
	ctx := context.Background()

	// distinct content -> Pass A dedup never fires; only Pass B (cap) matters.
	hot := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "hot"})
	backdate(t, db, hot, time.Now().Add(-100*time.Hour)) // oldest write
	setLastRecalled(t, db, hot, time.Now())              // but recalled just now

	mid := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "mid"})
	backdate(t, db, mid, time.Now().Add(-50*time.Hour)) // never recalled

	fresh := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "fresh"})
	backdate(t, db, fresh, time.Now().Add(-1*time.Hour)) // newest write, never recalled

	// cap=2: effective recency order = hot(now) > fresh(-1h) > mid(-50h); rn>2 -> mid evicted.
	res, err := s.RunRetentionSweep(ctx, 2)
	if err != nil {
		t.Fatalf("sweep: %v", err)
	}
	if res.CapArchived != 1 {
		t.Errorf("want 1 cap-archived, got %d", res.CapArchived)
	}
	assertArchived(t, db, hot, false)  // recalled-old survives (would be evicted under updated_at ordering)
	assertArchived(t, db, fresh, false)
	assertArchived(t, db, mid, true)   // cold middle evicted
}
```

- [ ] **Step 3: Run the test to verify it FAILS**

Run: `cd ennam.kg.go && go test -tags=integration ./internal/store/ -run TestRetention_UsageRecencyEvictsColdOverHot -v`
Expected: FAIL — under the current `ORDER BY updated_at DESC`, `hot` (oldest write) gets `rn=3` and is archived, so `assertArchived(hot, false)` fails (and `mid` survives).

- [ ] **Step 4: Change Pass B ordering to effective-recency**

In `internal/store/agent_context.go`, Pass B ranked CTE (currently ~326), change:

```go
				ORDER BY updated_at DESC, id
```

to (Pass B block ONLY — leave Pass A at ~304 unchanged):

```go
				ORDER BY GREATEST(updated_at, COALESCE(last_recalled_at, updated_at)) DESC, id
```

- [ ] **Step 5: Update the Pass-B doc-comment invariant**

In `internal/store/agent_context.go`, the `RunRetentionSweep` doc-comment (~285-288) currently says `updated_at` is preserved so "Pass-B ordering stay stable". Replace that sentence with:

```go
// RunRetentionSweep archives free-form duplicate and over-cap memories and drops
// their embeddings, in one transaction. mem_key rows and already-archived rows
// are never touched. updated_at is never written here. Pass B growth-bound
// survival is ordered by effective-recency = GREATEST(updated_at,
// COALESCE(last_recalled_at, updated_at)) DESC, so a recently-recalled old row
// outranks a never-recalled newer one. This ranking is eventually-consistent
// w.r.t. concurrent recalls (a touch landing mid-tick may shift one eviction by
// one sweep cycle). No functional index on effective-recency: Pass B already
// full-scans + window-sorts each tick; an index would break HOT updates on the
// hourly last_recalled_at bump.
```

- [ ] **Step 6: Run the test to verify it PASSES**

Run: `cd ennam.kg.go && go test -tags=integration ./internal/store/ -run TestRetention_UsageRecencyEvictsColdOverHot -v`
Expected: PASS

- [ ] **Step 7: Run the existing retention suite to confirm no regression**

Run: `cd ennam.kg.go && go test -tags=integration ./internal/store/ -run TestRetention -v`
Expected: PASS — `TestRetention_DedupKeepsNewest`, `TestRetention_GrowthBoundArchivesOldest`, `TestRetention_DeletesEmbeddingAndIsIdempotent` all still green (all their rows have NULL `last_recalled_at`, so effective-recency == `updated_at`).

- [ ] **Step 8: Commit**

```bash
cd ennam.kg.go
git add internal/store/agent_context.go internal/store/agent_context_retention_test.go
git commit -m "feat(daab): Pass B eviction orders by usage-aware effective-recency"
```

---

## Task 2: T1 — Keyed rows are exempt from the Pass B cap (⑤)

**Files:**
- Modify: `ennam.kg.go/internal/store/agent_context.go` (add ownership doc-comment; no logic change)
- Test: `ennam.kg.go/internal/store/agent_context_retention_test.go`

**Interfaces:**
- Consumes: `RunRetentionSweep`, `mustUpsert`, `backdate`, `assertArchived` (existing). No new production symbols.

- [ ] **Step 1: Write the failing test**

The existing `TestRetention_DedupKeepsNewest` proves keyed exemption only under Pass A (dedup). This proves it under Pass B (growth-bound cap), which is currently untested. Add to `internal/store/agent_context_retention_test.go`:

```go
// A mem_key (curated) row must never be archived by the Pass B growth-bound cap,
// even when free-form rows in the same bucket are over cap. Locks the
// capture-vs-retention ownership contract: retention only archives mem_key IS NULL.
func TestRetention_KeyedRowExemptFromCap(t *testing.T) {
	db := setupTestDB(t)
	acSeedProject(t, db)
	s := store.NewAgentContextStore(db)
	ctx := context.Background()

	// distinct content so Pass A dedup never fires.
	free1 := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "free1"})
	backdate(t, db, free1, time.Now().Add(-1*time.Hour))
	free2 := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "free2"})
	backdate(t, db, free2, time.Now().Add(-50*time.Hour))
	keyed := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", MemKey: "k1", Content: "keyed"})
	backdate(t, db, keyed, time.Now().Add(-200*time.Hour)) // oldest of all

	// cap=1: among free-form, free1 survives (rn1), free2 evicted (rn2). keyed excluded entirely.
	res, err := s.RunRetentionSweep(ctx, 1)
	if err != nil {
		t.Fatalf("sweep: %v", err)
	}
	if res.CapArchived != 1 {
		t.Errorf("want 1 cap-archived, got %d", res.CapArchived)
	}
	assertArchived(t, db, free1, false)
	assertArchived(t, db, free2, true)
	assertArchived(t, db, keyed, false) // keyed exempt from cap despite being oldest
}
```

- [ ] **Step 2: Run the test to verify it PASSES immediately (behavior already correct)**

Run: `cd ennam.kg.go && go test -tags=integration ./internal/store/ -run TestRetention_KeyedRowExemptFromCap -v`
Expected: PASS — Pass B's `WHERE is_archived=false AND mem_key IS NULL` already excludes keyed rows. This test is a *characterization/regression lock*: it will FAIL if anyone removes the `mem_key IS NULL` guard. (This is the legitimate case where the code precedes the test; the test still encodes an invariant per AGENTS Rule 9.)

- [ ] **Step 3: Add the ownership doc-comment at the capture boundary**

In `internal/store/agent_context.go`, immediately above the `UpsertAgentContext` function (the free-form/keyed upsert, near line 44), add:

```go
// Capture-vs-retention dedup ownership contract:
//   - CAPTURE (this upsert) owns keyed dedup: a mem_key row is upserted in place
//     via the (project_id, user_id, scope, mem_key) unique index — one durable,
//     curated row per key.
//   - RETENTION (RunRetentionSweep) owns free-form (mem_key IS NULL) dedup and the
//     growth-bound cap ONLY. Keyed rows are exempt from BOTH passes and from recall
//     recency decay. See TestRetention_KeyedRowExemptFromCap and
//     TestRetention_DedupKeepsNewest.
```

- [ ] **Step 4: Re-run to confirm still green after the comment**

Run: `cd ennam.kg.go && go test -tags=integration ./internal/store/ -run 'TestRetention' -v`
Expected: PASS (all retention tests)

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/store/agent_context.go internal/store/agent_context_retention_test.go
git commit -m "test(daab): lock keyed cap-exemption + document capture/retention ownership"
```

---

## Task 3: PR1 verification + open PR

- [ ] **Step 1: Full build + unit suite (no DB) with race**

Run: `cd ennam.kg.go && go build ./... && go test ./... -race -count=1`
Expected: all packages `ok` (unit level; integration tests are tag-gated and skipped here).

- [ ] **Step 2: Full integration store suite**

Run: `cd ennam.kg.go && go test -tags=integration ./internal/store/ -run 'TestRetention' -v`
Expected: PASS (5 tests: 3 pre-existing + 2 new).

- [ ] **Step 3: Push branch + open PR1**

```bash
cd ennam.kg.go
git push -u origin HEAD
```
PR title: `feat(daab): usage-aware Pass B eviction + keyed cap-exemption contract`. Body: link the spec `docs/superpowers/specs/2026-07-07-daab-usage-based-decay-design.md`; note T1+T2 are behavior-preserving under current all-NULL `last_recalled_at` data (the SQL change is bit-for-bit identical until T3 populates the column).

---

# PR 2 — T3 (① write-half)

## Task 4: Store — `TouchRecalled`

**Files:**
- Modify: `ennam.kg.go/internal/store/agent_context.go` (add const + method near the other consts ~147 and after `RunRetentionSweep`)
- Test: `ennam.kg.go/internal/store/agent_context_retention_test.go`

**Interfaces:**
- Consumes: `s.db` (`*sql.DB` on `AgentContextStore`), `github.com/lib/pq` (already imported).
- Produces: `func (s *AgentContextStore) TouchRecalled(ctx context.Context, ids []string, minInterval time.Duration) (int64, error)`; `const defaultRecalledTouchMinInterval = time.Hour`.

- [ ] **Step 1: Write the failing test**

Add to `internal/store/agent_context_retention_test.go`:

```go
// TouchRecalled bumps last_recalled_at only, honors the throttle window, skips
// archived rows, no-ops on empty ids, and never touches updated_at.
func TestTouchRecalled_ThrottleArchivedGuardAndUpdatedAtUntouched(t *testing.T) {
	db := setupTestDB(t)
	acSeedProject(t, db)
	s := store.NewAgentContextStore(db)
	ctx := context.Background()

	id := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "row"})
	before := readUpdatedAt(t, db, id)

	// empty ids -> no-op, no error.
	if n, err := s.TouchRecalled(ctx, nil, time.Hour); err != nil || n != 0 {
		t.Fatalf("empty ids: n=%d err=%v", n, err)
	}

	// first touch: last_recalled_at was NULL -> bumps.
	n, err := s.TouchRecalled(ctx, []string{id}, time.Hour)
	if err != nil || n != 1 {
		t.Fatalf("first touch: n=%d err=%v", n, err)
	}

	// second touch within the interval -> throttled to 0.
	if n, err := s.TouchRecalled(ctx, []string{id}, time.Hour); err != nil || n != 0 {
		t.Fatalf("throttled touch: n=%d err=%v", n, err)
	}

	// move last_recalled_at past the interval -> bumps again.
	setLastRecalled(t, db, id, time.Now().Add(-2*time.Hour))
	if n, err := s.TouchRecalled(ctx, []string{id}, time.Hour); err != nil || n != 1 {
		t.Fatalf("post-interval touch: n=%d err=%v", n, err)
	}

	// updated_at must be unchanged throughout.
	if after := readUpdatedAt(t, db, id); !after.Equal(before) {
		t.Errorf("updated_at changed: before=%v after=%v", before, after)
	}

	// archived rows are never touched.
	archived := mustUpsert(t, s, store.AgentContextUpsert{ProjectID: acProj, SourceAgent: "a", Kind: "fact", Scope: "project", Content: "arch"})
	if _, err := db.ExecContext(ctx, `UPDATE agent_context SET is_archived=true WHERE id=$1`, archived); err != nil {
		t.Fatalf("archive: %v", err)
	}
	if n, err := s.TouchRecalled(ctx, []string{archived}, time.Hour); err != nil || n != 0 {
		t.Fatalf("archived touch: n=%d err=%v", n, err)
	}
}

func readUpdatedAt(t *testing.T, db *sql.DB, id string) time.Time {
	t.Helper()
	var ts time.Time
	if err := db.QueryRowContext(context.Background(), `SELECT updated_at FROM agent_context WHERE id=$1`, id).Scan(&ts); err != nil {
		t.Fatalf("read updated_at %s: %v", id, err)
	}
	return ts
}
```

- [ ] **Step 2: Run the test to verify it FAILS**

Run: `cd ennam.kg.go && go test -tags=integration ./internal/store/ -run TestTouchRecalled -v`
Expected: FAIL to compile — `s.TouchRecalled` undefined.

- [ ] **Step 3: Add the const and the method**

In `internal/store/agent_context.go`, near `defaultRecallHalfLifeHours` (~147) add:

```go
// defaultRecalledTouchMinInterval throttles last_recalled_at writes: a row
// recalled again within this window is not re-bumped (avoids write amplification).
const defaultRecalledTouchMinInterval = time.Hour
```

After `RunRetentionSweep` (after its closing brace ~360) add:

```go
// TouchRecalled records that the given memories were surfaced by recall, by
// setting last_recalled_at = now() on rows whose last_recalled_at is NULL or
// older than minInterval. It writes last_recalled_at ONLY (never updated_at),
// skips archived rows, and is a no-op on empty ids. ids are sorted so concurrent
// touches acquire row locks in a consistent order (deadlock avoidance vs the
// retention sweep). Best-effort: callers log the error and move on.
func (s *AgentContextStore) TouchRecalled(ctx context.Context, ids []string, minInterval time.Duration) (int64, error) {
	if len(ids) == 0 {
		return 0, nil
	}
	sorted := append([]string(nil), ids...)
	sort.Strings(sorted)
	res, err := s.db.ExecContext(ctx, `
		UPDATE agent_context
		SET last_recalled_at = now()
		WHERE id = ANY($1)
		  AND is_archived = false
		  AND (last_recalled_at IS NULL OR last_recalled_at < now() - make_interval(secs => $2))`,
		pq.Array(sorted), minInterval.Seconds())
	if err != nil {
		return 0, fmt.Errorf("touch recalled: %w", err)
	}
	return res.RowsAffected()
}
```

Ensure `sort` is imported in `internal/store/agent_context.go` (add `"sort"` to the import block if absent).

- [ ] **Step 4: Run the test to verify it PASSES**

Run: `cd ennam.kg.go && go test -tags=integration ./internal/store/ -run TestTouchRecalled -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/store/agent_context.go internal/store/agent_context_retention_test.go
git commit -m "feat(daab): TouchRecalled store fn (last_recalled_at-only, throttled)"
```

---

## Task 5: Service — `RecalledTouchWriter` (batched worker)

**Files:**
- Create: `ennam.kg.go/internal/service/agent_context_touch.go`
- Test: `ennam.kg.go/internal/service/agent_context_touch_test.go`

**Interfaces:**
- Consumes: `store.AgentContextStore.TouchRecalled(ctx, ids, minInterval)` via a local `touchRecaller` interface; `internal/store` const `defaultRecalledTouchMinInterval` is store-package-private, so the writer defines its own `recalledTouchMinInterval = time.Hour`.
- Produces: `func NewRecalledTouchWriter(s touchRecaller, logger *slog.Logger) *RecalledTouchWriter`; methods `Enqueue(ids []string)`, `Start(ctx context.Context)`, `Stop()`. `Enqueue` is the interface the handler depends on.

- [ ] **Step 1: Write the failing unit test (no DB — fake store)**

Create `internal/service/agent_context_touch_test.go`:

```go
package service

import (
	"context"
	"sync"
	"testing"
	"time"
)

type fakeToucher struct {
	mu   sync.Mutex
	got  [][]string
	call chan struct{}
}

func (f *fakeToucher) TouchRecalled(ctx context.Context, ids []string, minInterval time.Duration) (int64, error) {
	f.mu.Lock()
	f.got = append(f.got, ids)
	f.mu.Unlock()
	f.call <- struct{}{}
	return int64(len(ids)), nil
}

func (f *fakeToucher) calls() [][]string {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := make([][]string, len(f.got))
	copy(out, f.got)
	return out
}

func TestRecalledTouchWriter_CoalescesAndFlushes(t *testing.T) {
	f := &fakeToucher{call: make(chan struct{}, 4)}
	w := newRecalledTouchWriter(f, nil, 10*time.Millisecond) // fast flush for the test
	w.Start(context.Background())
	defer w.Stop()

	w.Enqueue([]string{"a", "b"})
	w.Enqueue([]string{"b", "c"}) // "b" de-duped across enqueues

	select {
	case <-f.call:
	case <-time.After(2 * time.Second):
		t.Fatal("flush did not happen")
	}

	got := f.calls()
	if len(got) == 0 {
		t.Fatal("no TouchRecalled call recorded")
	}
	set := map[string]bool{}
	for _, id := range got[0] {
		set[id] = true
	}
	for _, want := range []string{"a", "b", "c"} {
		if !set[want] {
			t.Errorf("flush missing id %q; got %v", want, got[0])
		}
	}
}

func TestRecalledTouchWriter_EnqueueEmptyIsNoop(t *testing.T) {
	f := &fakeToucher{call: make(chan struct{}, 1)}
	w := newRecalledTouchWriter(f, nil, 10*time.Millisecond)
	w.Start(context.Background())
	defer w.Stop()

	w.Enqueue(nil)
	w.Enqueue([]string{})

	select {
	case <-f.call:
		t.Fatal("empty enqueue should not trigger a flush")
	case <-time.After(100 * time.Millisecond):
		// expected: nothing flushed
	}
}
```

- [ ] **Step 2: Run the test to verify it FAILS**

Run: `cd ennam.kg.go && go test ./internal/service/ -run TestRecalledTouchWriter -v`
Expected: FAIL to compile — `newRecalledTouchWriter` / `RecalledTouchWriter` undefined.

- [ ] **Step 3: Implement the writer**

Create `internal/service/agent_context_touch.go`:

```go
package service

import (
	"context"
	"log/slog"
	"sync"
	"time"
)

// touchRecaller is the store surface the writer drives.
type touchRecaller interface {
	TouchRecalled(ctx context.Context, ids []string, minInterval time.Duration) (int64, error)
}

const (
	recalledTouchMinInterval = time.Hour        // throttle window (matches store default)
	recalledFlushInterval    = 5 * time.Second  // how often pending ids are flushed
	recalledBufferSize       = 256              // enqueue backlog before drop-on-full
)

// RecalledTouchWriter batches recall-hit ids and flushes them to TouchRecalled on
// a single background goroutine. Best-effort: a full buffer drops (recall must
// never block), and flush errors are logged only. Mirrors AgentContextRetentionWorker.
type RecalledTouchWriter struct {
	store  touchRecaller
	ch     chan []string
	flush  time.Duration
	logger *slog.Logger
	stopCh chan struct{}
	once   sync.Once
}

// NewRecalledTouchWriter builds a writer with the default flush interval.
func NewRecalledTouchWriter(s touchRecaller, logger *slog.Logger) *RecalledTouchWriter {
	return newRecalledTouchWriter(s, logger, recalledFlushInterval)
}

func newRecalledTouchWriter(s touchRecaller, logger *slog.Logger, flush time.Duration) *RecalledTouchWriter {
	if logger == nil {
		logger = slog.Default()
	}
	return &RecalledTouchWriter{
		store:  s,
		ch:     make(chan []string, recalledBufferSize),
		flush:  flush,
		logger: logger,
		stopCh: make(chan struct{}),
	}
}

// Enqueue queues recall-hit ids. Non-blocking; drops on a full buffer.
func (w *RecalledTouchWriter) Enqueue(ids []string) {
	if len(ids) == 0 {
		return
	}
	select {
	case w.ch <- ids:
	default:
		// buffer full: drop (best-effort, next recall will re-supply hot ids).
	}
}

// Start runs the coalesce/flush loop until Stop() or ctx cancellation.
func (w *RecalledTouchWriter) Start(ctx context.Context) {
	go func() {
		ticker := time.NewTicker(w.flush)
		defer ticker.Stop()
		pending := make(map[string]struct{})
		doFlush := func() {
			if len(pending) == 0 {
				return
			}
			ids := make([]string, 0, len(pending))
			for id := range pending {
				ids = append(ids, id)
			}
			pending = make(map[string]struct{})
			if _, err := w.store.TouchRecalled(ctx, ids, recalledTouchMinInterval); err != nil {
				w.logger.WarnContext(ctx, "recalled touch flush failed", "error", err, "count", len(ids))
			}
		}
		for {
			select {
			case ids := <-w.ch:
				for _, id := range ids {
					pending[id] = struct{}{}
				}
			case <-ticker.C:
				doFlush()
			case <-w.stopCh:
				doFlush()
				return
			case <-ctx.Done():
				return
			}
		}
	}()
}

// Stop signals the loop to flush once and exit.
func (w *RecalledTouchWriter) Stop() { w.once.Do(func() { close(w.stopCh) }) }
```

- [ ] **Step 4: Run the test to verify it PASSES**

Run: `cd ennam.kg.go && go test ./internal/service/ -run TestRecalledTouchWriter -race -v`
Expected: PASS (both sub-tests), no race.

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/service/agent_context_touch.go internal/service/agent_context_touch_test.go
git commit -m "feat(daab): batched RecalledTouchWriter (best-effort, drop-on-full)"
```

---

## Task 6: Handler — enqueue returned top-K ids in `Recall`

**Files:**
- Modify: `ennam.kg.go/internal/handler/agent_context.go` (struct ~34, ctor ~43, `Recall` ~187-203)
- Modify: existing handler-test call sites of `NewAgentContextHandler` (pass `nil`)

**Interfaces:**
- Consumes: `RecalledTouchWriter.Enqueue([]string)` via a local `recalledEnqueuer` interface. `store.SearchResult.ID` (string) is the memory id.
- Produces: 6-arg `NewAgentContextHandler(s, embedder, pub, settings, recalled, logger)`.

- [ ] **Step 1: Add the interface + struct field + ctor param**

In `internal/handler/agent_context.go`, near the other small interfaces at the top of the file, add:

```go
// recalledEnqueuer receives the ids surfaced by a recall so their last_recalled_at
// can be updated out-of-band. Optional (nil in tests / when the writer is off).
type recalledEnqueuer interface {
	Enqueue(ids []string)
}
```

Change the struct (~34) to add the field:

```go
type AgentContextHandler struct {
	store     agentContextStore
	embedder  QueryEmbedder
	publisher agentContextEmbedPublisher
	settings  recallSettings
	recalled  recalledEnqueuer
	logger    *slog.Logger
}
```

Change the constructor (~43):

```go
func NewAgentContextHandler(s agentContextStore, embedder QueryEmbedder, pub agentContextEmbedPublisher, settings recallSettings, recalled recalledEnqueuer, logger *slog.Logger) *AgentContextHandler {
	return &AgentContextHandler{store: s, embedder: embedder, publisher: pub, settings: settings, recalled: recalled, logger: logger}
}
```

- [ ] **Step 2: Enqueue the returned top-K ids in `Recall`**

In `Recall`, replace the final success line (~203):

```go
	writeJSON(w, http.StatusOK, map[string]interface{}{"results": toRecallView(rows)})
```

with:

```go
	if h.recalled != nil && len(rows) > 0 {
		ids := make([]string, 0, len(rows))
		for _, row := range rows {
			ids = append(ids, row.ID)
		}
		h.recalled.Enqueue(ids) // fire-and-forget; must never affect the response
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"results": toRecallView(rows)})
```

- [ ] **Step 3: Fix existing `NewAgentContextHandler` call sites in tests**

Run: `cd ennam.kg.go && grep -rn "NewAgentContextHandler(" internal/handler/ | grep _test`
For each call site, insert `nil,` before the trailing `logger` argument (the new `recalled` param). Example transform:

```go
// before
h := NewAgentContextHandler(fakeStore, fakeEmbedder, fakePub, fakeSettings, logger)
// after
h := NewAgentContextHandler(fakeStore, fakeEmbedder, fakePub, fakeSettings, nil, logger)
```

- [ ] **Step 4: Write a handler test — recall still soft-fails and never blocks on the writer**

Add to the handler agent_context test file (same package `handler`) a test using a stub enqueuer whose `Enqueue` records the ids, plus a store stub that returns an error, asserting recall still returns 200 with empty results and the writer is NOT called on error:

```go
type stubEnqueuer struct{ got [][]string }

func (s *stubEnqueuer) Enqueue(ids []string) { s.got = append(s.got, ids) }

func TestRecall_EnqueuesReturnedIDs_AndSoftFailsWithoutEnqueue(t *testing.T) {
	// happy path: returned rows are enqueued.
	enq := &stubEnqueuer{}
	okStore := &fakeRecallStore{rows: []store.SearchResult{{ID: "m1"}, {ID: "m2"}}}
	h := NewAgentContextHandler(okStore, nil, nil, stubRecallSettings{}, enq, slog.Default())
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/agent-context/recall", strings.NewReader(`{"query":"x"}`))
	h.Recall(rec, req)
	if rec.Code != 200 {
		t.Fatalf("want 200, got %d", rec.Code)
	}
	if len(enq.got) != 1 || len(enq.got[0]) != 2 {
		t.Fatalf("want one enqueue of 2 ids, got %v", enq.got)
	}

	// error path: recall soft-fails to empty, writer NOT called.
	enq2 := &stubEnqueuer{}
	errStore := &fakeRecallStore{err: errors.New("boom")}
	h2 := NewAgentContextHandler(errStore, nil, nil, stubRecallSettings{}, enq2, slog.Default())
	rec2 := httptest.NewRecorder()
	req2 := httptest.NewRequest("POST", "/api/v1/agent-context/recall", strings.NewReader(`{"query":"x"}`))
	h2.Recall(rec2, req2)
	if rec2.Code != 200 {
		t.Fatalf("error path want 200, got %d", rec2.Code)
	}
	if len(enq2.got) != 0 {
		t.Fatalf("writer must not be called on recall error, got %v", enq2.got)
	}
}
```

> If a `fakeRecallStore` / `stubRecallSettings` already exists in the handler test file, reuse it and drop the redeclaration; otherwise add a minimal fake implementing `agentContextStore` (returning `rows`/`err` from `RecallAgentContext`, no-op for the other methods) and `recallSettings` (returning `0` for `RecallHalfLifeHours`). Add imports `errors`, `net/http/httptest`, `strings`, `log/slog`, and the `store` package as needed.

- [ ] **Step 5: Run the handler tests**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run 'TestRecall' -race -v`
Expected: PASS (new test + existing recall tests).

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.go
git add internal/handler/agent_context.go internal/handler/agent_context_test.go
git commit -m "feat(daab): recall enqueues returned top-K ids to the touch writer"
```

---

## Task 7: Wire the writer into the server composition root

**Files:**
- Modify: `ennam.kg.go/cmd/kg-server/main.go` (construct writer ~after 394; pass into handler ~543; Start/Stop ~near 919)

**Interfaces:**
- Consumes: `service.NewRecalledTouchWriter(acStore, logger)`; the 6-arg `handler.NewAgentContextHandler`.

- [ ] **Step 1: Construct the writer before the handler**

In `cmd/kg-server/main.go`, after `acStore := store.NewAgentContextStore(db)` (line 394), add:

```go
	recalledWriter := service.NewRecalledTouchWriter(acStore, logger)
```

- [ ] **Step 2: Pass the writer into the handler ctor**

Change the handler construction (line 543) from:

```go
	acHandler := handler.NewAgentContextHandler(acStore, embedClient, agentCtxPub, memSettings, logger)
```

to:

```go
	acHandler := handler.NewAgentContextHandler(acStore, embedClient, agentCtxPub, memSettings, recalledWriter, logger)
```

- [ ] **Step 3: Start/Stop the writer alongside the retention worker**

Immediately after the retention worker block (lines 919-921):

```go
	retentionWorker := service.NewAgentContextRetentionWorker(acStore, memSettings, logger)
	retentionWorker.Start(context.Background())
	defer retentionWorker.Stop()
```

add:

```go
	recalledWriter.Start(context.Background())
	defer recalledWriter.Stop()
```

- [ ] **Step 4: Build + full unit suite with race**

Run: `cd ennam.kg.go && go build ./... && go test ./... -race -count=1`
Expected: all packages `ok`.

- [ ] **Step 5: Full integration store suite (T3 store test included)**

Run: `cd ennam.kg.go && go test -tags=integration ./internal/store/ -run 'TestRetention|TestTouchRecalled' -v`
Expected: PASS.

- [ ] **Step 6: Commit + push + open PR2**

```bash
cd ennam.kg.go
git add cmd/kg-server/main.go
git commit -m "feat(daab): wire RecalledTouchWriter into kg-server (populate last_recalled_at)"
git push -u origin HEAD
```
PR title: `feat(daab): populate last_recalled_at on recall (batched, best-effort)`. Body: link spec + PR1; note the writer is idle under zero recall traffic and activates the T2 usage-decay signal once any agent calls `kg_recall`.

---

## Self-Review Notes (author)

- **Spec coverage:** T1 → Task 2 (⑤ doc + cap-exemption test); T2 → Task 1 (Pass B `GREATEST` + doc); T3 → Tasks 4 (TouchRecalled), 5 (writer), 6 (handler), 7 (wiring). §6 test table: keyed-cap (Task 2), usage-recency eviction (Task 1), throttle/archived/updated_at-untouched (Task 4), writer idle/flush (Task 5), recall soft-fail + enqueue (Task 6). Determinism tie-break by `id` is inherent in the `, id` suffix retained in the Pass B ORDER BY (Task 1 Step 4).
- **Deliberately NOT covered (per spec §7):** recall-ranking change, per-recall goroutine, `updated_at` bump, config knob, functional index, Pass A change. The concurrent sweep-vs-touch integration test (§6 last row) is intentionally deferred: row locks + best-effort touch make it tolerable-by-design (documented in the Task 1 Step 5 comment); add only if a real deadlock is observed.
- **Type consistency:** `TouchRecalled(ctx, ids []string, minInterval time.Duration) (int64, error)` is used identically in Task 4 (store), Task 5 (`touchRecaller` interface), and the fake. `Enqueue(ids []string)` matches across writer (Task 5), `recalledEnqueuer` (Task 6), stub, and main wiring (Task 7). `RecallAgentContext` returns `[]store.SearchResult` whose `.ID` is used in Task 6.
```
