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
- PostgreSQL at `localhost:5433` with migrations applied through `000061`
  (adds `person` node type)

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
| Precision gate (≥0.74) | **PENDING-DATA** | `vi_blocking_v1.json` is an empty skeleton |
| FP-rate gate (≤10 FP/100) | **PENDING-DATA** | `vi_blocking_v1.json` is an empty skeleton |
| F1 gate (≥0.75) | **PENDING-DATA** | `vi_blocking_v1.json` is an empty skeleton |
| **Overall Phase 8c** | **PENDING-DATA** | Data gate not cleared |

---

## Clearing PENDING-DATA (precision / recall gate)

The precision/recall gate (Task 9) requires real blocking candidate pairs in
`ennam.kg.python/data/benchmarks/vi_blocking_v1.json`.

### Steps

1. Populate `vi_blocking_v1.json` with real candidate pairs:

   ```json
   {
     "pairs": [
       {"id_a": "node-uuid-1", "id_b": "node-uuid-2", "label": 1},
       {"id_a": "node-uuid-3", "id_b": "node-uuid-4", "label": 0}
     ]
   }
   ```

   Label `1` = true match, `0` = non-match.

2. Re-run Task 9 precision/recall script:

   ```bash
   cd ennam.kg.python
   uv run python -m ennam_kg.benchmarks.blocking_eval \
     --candidates data/benchmarks/vi_blocking_v1.json \
     --thresholds precision=0.74 fp_per_100=10 f1=0.75
   ```

3. If all three thresholds pass, update the gate decision in:
   - `.serena/memories/decisions/mcp-api-spec.md` (section: Phase 8c gate)
   - This runbook (table above)

4. Create commit: `docs(ba031-8c): precision/recall gate PASS — Phase 8c complete`

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
