# BA-031 Phase 8c — Un-Merge Drill Runbook

## Purpose

This runbook documents how to run and interpret the un-merge reversibility drill
for the BA-031 entity resolution pipeline. The drill proves that every merge
operation can be fully reversed (byte-equivalent at node status+properties and
edge source/target+properties) at the HTTP layer.

---

## What Byte-Equivalence Means

After a merge followed by an un-merge, every field that was not written by the
merge operation must be identical to its pre-merge snapshot:

| Field | Compared? | Excluded? |
|-------|-----------|-----------|
| Node `status` | Yes | — |
| Node `properties` (JSONB, normalized) | Yes | — |
| Edge `source_id` / `target_id` | Yes | — |
| Edge `properties` (JSONB, normalized) | Yes | — |
| Node `version` | No | Bumped by trigger on every UPDATE |
| Node `updated_at` | No | Bumped by trigger |
| Edge `created_by` / timestamps | No | Not changed by merge |

"Normalized" means the JSONB is round-tripped through `json.Marshal` /
`json.Unmarshal` so numeric types and map key ordering are canonical before
`reflect.DeepEqual` is applied.

---

## Running the Drill

### Requirements

- Go 1.22+
- PostgreSQL at `localhost:5433` with migrations applied through `000064`
  (`000061` adds the `person` node type; `000064` adds the `merge_suggestions`
  sidecar used by Phase 8c)

### One-liner

```bash
export KG_TEST_DB_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable"
export KG_TEST_DATABASE_URL="$KG_TEST_DB_URL"

go test -tags=integration -v ./internal/integration/ -run TestBA031_UnmergeDrillByteEquivalent
```

### Expected output

```
=== RUN   TestBA031_UnmergeDrillByteEquivalent
    ba031_resolution_test.go:...: BA031 Phase 8c drill PASS: merge_op_id=..., repointed=1, collided=1, unmerge restored all 3 edges byte-equivalent
--- PASS: TestBA031_UnmergeDrillByteEquivalent (...)
PASS
```

### What the drill seeds

1. **member node** (person): `Alice Smith` — aliases: `["Alice"]`, provenance `doc-member`
2. **canonical node** (person): `Alice Smith (canonical)` — aliases: `["A. Smith"]`, provenance `doc-canon`
3. **org node** (person): `Org node` — no properties
4. **sharedTgt node** (person): `Shared target` — no properties
5. **Edge A**: member → org (non-colliding, re-pointed during merge)
6. **Edge B-member**: member → sharedTgt (colliding, superseded during merge)
7. **Edge B-canon**: canonical → sharedTgt (collision survivor, absorbs provenance from B-member)

The merge call includes a `merged_description` to exercise the scalar re-summary
reversal path in addition to the alias and provenance paths.

---

## Phase 8c Gate Decision

| Sub-gate | Status | Evidence |
|----------|--------|---------|
| Un-merge drill (HTTP level) | **PASS** | `TestBA031_UnmergeDrillByteEquivalent` against real DB |
| Shadow no-mutation | Covered by Task 8 | `ennam.kg.python/tests/resolution/test_pass2.py` |
| Merge precision gate (≥0.90) | **PENDING-DATA** | `vi_blocking_v1.json` is an empty skeleton |
| Merge recall gate (≥0.80) | **PENDING-DATA** | `vi_blocking_v1.json` is an empty skeleton |
| **Overall Phase 8c** | **PENDING-DATA** | Data gate not cleared |

> The 8c exit gate is **merge precision ≥ 0.90 AND recall ≥ 0.80** (plan §"Exit gate").
> The blocking-recall gate (recall@K=10 ≥ 0.90 in [0.72, 0.75]) is the **8b** gate
> and must pass first, since it feeds the `resolution_sim_threshold` / `resolution_top_k`
> that 8c uses.

---

## Clearing PENDING-DATA (precision / recall gate)

The gate requires the labelled Vietnamese benchmark
`ennam.kg.python/benchmarks/ba031/vi_blocking_v1.json`, populated per
`ennam.kg.python/benchmarks/ba031/schema.md` (≥ 30 gold groups / ≥ 50 labelled
pairs covering honorifics, diacritics↔romanised, abbreviations, org variants).

### Steps

1. **Populate `vi_blocking_v1.json`** following `benchmarks/ba031/schema.md`. The
   shape is an `entities` array (NOT `pairs`); two entities form a true-duplicate
   pair iff they share `gold_entity_id` AND `type`. Assign `_meta.owner`:

   ```json
   {
     "_meta": {"name": "vi_blocking_v1", "owner": "<NAME>", "language": "vi", "notes": "..."},
     "entities": [
       {"id": "e1", "gold_entity_id": "g_nguyen_van_a", "type": "person",
        "canonical_name": "Nguyễn Văn A", "aliases": ["ông A"], "description": "..."},
       {"id": "e2", "gold_entity_id": "g_nguyen_van_a", "type": "person",
        "canonical_name": "ông Nguyễn Văn A", "aliases": [], "description": "..."}
     ]
   }
   ```

2. **Run the 8b blocking-recall gate first** (it feeds 8c's thresholds). This CLI
   exists (`src/ennam_kg/benchmark/cli.py`) and requires the live stack + e5 model:

   ```bash
   cd ennam.kg.python
   uv run python -m ennam_kg.benchmark.cli \
     --dataset benchmarks/ba031/vi_blocking_v1.json \
     --project <bench-project-uuid> \
     --out /tmp/blocking-report.md
   ```

   8b gate: recall@K=10 ≥ 0.90 with `resolution_sim_threshold` in [0.72, 0.75].
   Record the chosen `resolution_sim_threshold` / `resolution_top_k` for 8c.

3. **Run the 8c merge precision/recall evaluation** with the real verifier model and
   the chosen `merge_confidence_threshold`, over the same labelled set.
   The scoring functions exist — `ennam_kg.benchmark.merge_eval.evaluate_merge`
   (single threshold) and `sweep_confidence` (tune) → `MergeScore{precision, recall,
   tp, fp, fn}` — but they consume **pre-computed** `blocked_pairs` + per-pair
   `verdicts`. ⚠️ **The end-to-end harness that produces those verdicts (load dataset
   → embed/insert → block via `/internal/resolution/candidates` → run `verify_pair`
   with the real model → `evaluate_merge`) is NOT yet built.** Today `merge_eval` is
   exercised only by `tests/benchmark/test_merge_eval.py` with synthetic verdicts.
   **This harness must be written when the dataset lands** (model it on
   `benchmark/cli.py` + `benchmark/sweep.py`, adding the `verify_pair` step). Until
   then the 8c precision/recall gate cannot be run.
   8c gate: **precision ≥ 0.90 AND recall ≥ 0.80**.

4. If the 8b gate passes, the 8c precision/recall gate passes, AND the un-merge
   drill above is PASS, update the gate decision in:
   - `.serena/memories/decisions/mcp-api-spec.md` (section: Phase 8c gate)
   - This runbook (table above)

5. Create commit: `docs(ba031-8c): precision/recall gate PASS — Phase 8c complete`

---

## Troubleshooting

### `person` node type fails with CHECK violation

The DB is not migrated to `000061`. Run:

```bash
cd ennam.kg.go
make db-migrate
```

The test requires `'person'` and will fail loudly if the DB predates migration `000061`.
There is no silent fallback — the error message will tell you to run `make db-migrate`.

### `KG_TEST_DB_URL not set` — test is skipped

Export both env vars before running (they point to the same DB):

```bash
export KG_TEST_DB_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable"
export KG_TEST_DATABASE_URL="$KG_TEST_DB_URL"
```

### Byte-equivalence assertion fails

The merge or unmerge service has a regression. Run the service-level drill first
to isolate HTTP vs service layer:

```bash
go test -tags=integration -v ./internal/service/ -run TestUnmerge_DrillByteEquivalent
```

If the service-level drill also fails, the bug is in `merge.go` / `unmerge.go`.
If only the HTTP-level drill fails, check `handler/merge.go` for decode/encode drift.
