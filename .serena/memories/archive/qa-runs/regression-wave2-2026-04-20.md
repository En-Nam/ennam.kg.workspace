# Full Regression Wave 2 — Phase 2 (KG AI Pipeline)

**Date**: 2026-04-20 | **5 parallel agents** | **246 TCs executed**

## Summary
| Metric | Count |
|--------|-------|
| Total TCs | 246 |
| PASS | 55 (22%) |
| FAIL | 43 (17%) |
| SKIP | 144 (59%) |
| PARTIAL | 4 (2%) |

## Results by BA
| BA | Pass | Fail | Skip | Partial |
|----|------|------|------|---------|
| BA-007 Data Source | 10 | 8 | 15 | 3 |
| BA-008+009 KG+AI | 15 | 2 | 38 | 0 |
| BA-010 KG Viz | 3 | 16 | 23 | 1 |
| BA-011+012 Query+Sync | 24 | 5 | 53 | 0 |
| BA-013 Benchmark | 3 | 12 | 15 | 0 |

## Critical Findings

### BLOCKER
1. **BFF Proxy broken** — blocks all BA-010 browser tests (23 BLOCKED)
2. **Benchmark DB enum mismatches** — difficulty `medium` vs `moderate`, status `created` vs `running`. Blocks all run operations.

### P1 Bugs
3. **SSE/WebSocket routing unreachable** — `/stream/sync/progress` and `/ws/sync/{job_id}/progress` registered on apiMux but mux only forwards `/api/` prefix. `sync_portal.go:65-66`.
4. **Column duplication bug** — Each column inserted 3x during extraction. `schema_extractor.go`.
5. **Extract-schema returns 500** — Handler does sync work while job tracking is async. Race condition.
6. **Heartbeat monitor kills long extractions** — Jobs marked stale before completion.

### P2 Bugs
7. BA-010: 16 features not implemented (tooltips, Escape key, confidence opacity, schema filter, search, radial/grouped layouts, SVG export)
8. BA-013: 5 endpoints missing (delete question, versions, cancel run, breakdown, regressions, trends)
9. BA-007: include_deleted not working, no DS status validation
10. BA-009: Duplicate provider name → 500 (should 409)

### High SKIP Rate (59%)
- 38 tests need live AI provider (not configured)
- 53 tests need browser (E2E-Browser type)
- 23 tests blocked by BFF proxy
- 30 tests need test data that doesn't exist
