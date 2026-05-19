# Phase 2 Gap Analysis — Master Execution Plan

> **For agentic workers:** Execute plans in P1→P2→P3→P4 order. Each plan is self-contained with its own task list.

**Goal:** Close all gaps between current implementation and BA-007 through BA-013 specifications.

---

## Priority Ordering

```
P1: BA-008 KG Generation ──────────── CRITICAL PATH (unblocks P2 + P3)
    ↓
P2: BA-011 NL Query Expansion ─────── CORE VALUE (end-user feature)
    ↓
P3: BA-013 Benchmark Expansion ────── QUALITY GATE (95% accuracy exit condition)
    ↓
P4: BA-012 Admin Sync Portal ──────── OPERATIONAL (can defer without blocking)
```

### Why This Order

| Priority | Reason |
|----------|--------|
| **P1 first** | BA-011 queries need KG context (tables→nodes, FKs→edges) to generate correct SQL. Without KG data, the NL pipeline has nothing to work with. |
| **P2 second** | NL→SQL pipeline is the core user-facing feature. BA-013 benchmarks need this pipeline to execute test questions. |
| **P3 third** | Accuracy measurement is the Phase 2 exit gate (≥95%). Can't measure until NL pipeline works end-to-end. |
| **P4 last** | Admin tooling (sync portal, queue management, rate limiting) is operational infrastructure. Users can function without it. All sync operations already work via DataSource handler. |

---

## Current State vs Target

| BA | Current Endpoints | Target Endpoints | Gap | Plan |
|----|-------------------|------------------|-----|------|
| BA-007 Data Source | 10 | 10 | 0 | — (complete) |
| BA-008 KG Generation | 0 | 9 | **9** | [P1](2026-04-08-phase2-gap-P1-ba008-kg-generation.md) |
| BA-009 AI Provider | 9 | 9 | 0 | — (complete) |
| BA-010 Visualization | 0 | 1 | 1* | Included in P1 Task 6 |
| BA-011 AI Query | 2 | 6 | **4** | [P2](2026-04-08-phase2-gap-P2-ba011-nl-query-expansion.md) |
| BA-012 Admin Sync | 0 | 8 | **8** | [P4](2026-04-08-phase2-gap-P4-ba012-admin-sync-portal.md) |
| BA-013 Benchmark | 2 | 8 | **6** | [P3](2026-04-08-phase2-gap-P3-ba013-benchmark-expansion.md) |
| **Total** | **23** | **51** | **28** | |

*BA-010 is primarily frontend (Cytoscape.js). The Go API endpoint (`GET /kg/schema-graph`) is a simple query of KG nodes/edges created by BA-008.

---

## Migration Plan

| # | Plan | Tables/Changes |
|---|------|----------------|
| 025 | P1 | Extend knowledge_nodes/edges JSONB properties, relax self-ref CHECK |
| 026 | P1 | kg_generation_jobs |
| 027 | P2 | query_clarifications, query_favorites |
| 028 | P3 | Extend benchmark_questions + benchmark_runs with scoring fields |
| 029 | P4 | query_queue, dead_letter_queue, rate_limit_state, usage_metrics |

---

## Effort Estimate

| Plan | Tasks | New Files | Effort |
|------|-------|-----------|--------|
| P1: BA-008 | 7 | ~16 | **Large** — FK mapping, AI implicit detection |
| P2: BA-011 | 8 | ~14 | **Large** — full AI pipeline |
| P3: BA-013 | 5 | ~10 | **Medium** — scorer + runner |
| P4: BA-012 | 7 | ~18 | **Large** — job engine, WebSocket, queue |
| **Total** | **27 tasks** | **~58 files** | |

---

## Execution Strategy

### Recommended: Sequential P1→P2→P3, defer P4

For fastest path to a working end-to-end pipeline:
1. Execute P1 (BA-008) — ~1 session with subagent-driven
2. Execute P2 (BA-011) — ~1 session
3. Execute P3 (BA-013) — ~1 session
4. **Ship and validate** — run benchmarks, measure accuracy
5. Execute P4 (BA-012) if needed — operational polish

### Alternative: Parallel P1+P4, then P2+P3

If team bandwidth allows, P1 and P4 are independent (different files, different packages). They could run in parallel worktrees.

---

## Plan Files

| File | BA | Priority | Tasks |
|------|-----|----------|-------|
| [`P1-ba008-kg-generation.md`](2026-04-08-phase2-gap-P1-ba008-kg-generation.md) | BA-008 | P1 Critical | 7 |
| [`P2-ba011-nl-query-expansion.md`](2026-04-08-phase2-gap-P2-ba011-nl-query-expansion.md) | BA-011 | P2 High | 8 |
| [`P3-ba013-benchmark-expansion.md`](2026-04-08-phase2-gap-P3-ba013-benchmark-expansion.md) | BA-013 | P3 Medium | 5 |
| [`P4-ba012-admin-sync-portal.md`](2026-04-08-phase2-gap-P4-ba012-admin-sync-portal.md) | BA-012 | P4 Low | 7 |
