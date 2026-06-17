# BA-031 Phase 8b (Blocking-Recall Benchmark) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the labelled Vietnamese **blocking-recall benchmark** and the deterministic sweep harness that gates Phase 8c. The harness loads labelled entities into a benchmark project, embeds them with the exact Pass-1 path, queries the 8a resolution-candidates endpoint, and reports blocking recall across a threshold × K grid. **Exit gate: blocking recall ≥ 0.90 at K=10 with `resolution_sim_threshold` in [0.72, 0.75].**

**Architecture:** Pure measurement, no merging and no LLM. The benchmark dataset is a JSON file of entities tagged with a `gold_entity_id` (entities sharing a gold id are true duplicates). The Python harness inserts each entity as a closed-vocab node + 384-dim embedding (via the existing `KGClient` + `embed_entity` from 8a), then for each query entity issues **one** call to `POST /api/v1/internal/resolution/candidates` at the loosest setting (top_k = max(K), min_similarity = min(threshold)) and computes the full T×K recall grid **offline** from the returned ranks. This isolates embedding/blocking quality from Pass-1 extraction noise and keeps the sweep cheap and exact.

**Tech Stack:** Python 3.12 (pytest, httpx), `multilingual-e5-small` (384-dim, `encode_query` both sides — symmetric, per 8a `embed.py`), Go resolution-candidates endpoint (8a), PostgreSQL + pgvector.

## Global Constraints

- **Measures blocking only** — no LLM verifier, no merges. Merge precision/recall is Phase 8c.
- **Symmetric embedding:** reuse 8a `ennam_kg.extraction.embed.embed_entity` (both sides `encode_query`) verbatim — do not re-implement embedding. The benchmark must measure the *real* path.
- **Same-type, project-scoped blocking:** queries pass the entity's `node_type`; the benchmark project is isolated (BR-004.6 / NFR-266) — never mix benchmark data with real projects.
- **Closed vocabulary (from 8a):** entity types ∈ `person, organization, concept, event, document_ref, location, artifact, project` (8 extractable; `master_record` excluded).
- **Dataset size floor (spec NFR-255/256/257 inputs):** ≥ 30 gold "chunks" worth of entities and ≥ 50 labelled same/different pairs, **in Vietnamese**, covering the hard cases: honorifics (`ông/bà/Mr.`), diacritics vs romanised, abbreviations, org name variants.
- **Sweep grid:** thresholds `{0.70, 0.72, 0.74, 0.75, 0.78, 0.80, 0.82, 0.85}`, K `{5, 10, 20}`.
- **Gate (hard):** recall@K=10 ≥ 0.90 at a threshold in [0.72, 0.75]. If unmet, 8c does not start; the OQ-002 normaliser is reconsidered.
- **Python conventions:** `cd ennam.kg.python && uv run pytest`; ruff lint. Harness under `src/ennam_kg/benchmark/`, tests under `tests/benchmark/`, data under `ennam.kg.python/benchmarks/ba031/`.
- **Determinism:** harness logic (loader, metrics, grid, report, gate) is unit-tested with a synthetic fixture and must be fully deterministic — no network, no model — by injecting a fake retriever. Only the end-to-end sweep (Task 6) touches the live model + endpoint.

---

## File Structure

- `ennam.kg.python/benchmarks/ba031/schema.md` — dataset format spec + labelling guide + named owner.
- `ennam.kg.python/benchmarks/ba031/sample.json` — small synthetic, English-safe fixture (harness tests; NOT the real benchmark).
- `ennam.kg.python/benchmarks/ba031/vi_blocking_v1.json` — the real labelled Vietnamese set (human deliverable; created in Task 1, filled by the owner).
- `src/ennam_kg/benchmark/__init__.py`
- `src/ennam_kg/benchmark/dataset.py` — dataclasses + `load_benchmark` + validation.
- `src/ennam_kg/benchmark/metrics.py` — `recall_at_k`, `evaluate_grid` (pure).
- `src/ennam_kg/benchmark/sweep.py` — `run_sweep` (inserts + embeds + queries via injected deps) and the `Retriever` protocol.
- `src/ennam_kg/benchmark/report.py` — `format_report`, `meets_gate`.
- `src/ennam_kg/benchmark/cli.py` — `python -m ennam_kg.benchmark.cli --dataset … --out …`.
- `tests/benchmark/` — mirrors the above.

---

## Task 1: Dataset schema, labelling guide, and synthetic fixture

Defines the contract and the human deliverable. Produces a tiny synthetic fixture the rest of the plan tests against, and the empty real-dataset file with instructions + owner.

**Files:**
- Create: `ennam.kg.python/benchmarks/ba031/schema.md`
- Create: `ennam.kg.python/benchmarks/ba031/sample.json`
- Create: `ennam.kg.python/benchmarks/ba031/vi_blocking_v1.json` (skeleton + `_meta.owner`)

**Interfaces:**
- Produces the on-disk JSON contract consumed by `load_benchmark` (Task 2):

```json
{
  "_meta": {"name": "vi_blocking_v1", "owner": "<NAME — REQUIRED before gate>", "language": "vi", "notes": "..."},
  "entities": [
    {"id": "e1", "gold_entity_id": "g_nguyen_van_a", "type": "person",
     "canonical_name": "Nguyễn Văn A", "aliases": ["Mr. A", "ông A"],
     "description": "Kỹ sư trưởng dự án Cảng Đình An"},
    {"id": "e2", "gold_entity_id": "g_nguyen_van_a", "type": "person",
     "canonical_name": "ông Nguyễn Văn A", "aliases": [], "description": "Chủ trì dự án"}
  ]
}
```

Rule: two entities are a **true duplicate pair** iff they share `gold_entity_id` AND `type`. Cross-type is never a pair (FR-004 same-type blocking).

- [ ] **Step 1: Write `schema.md`**

Document: the JSON shape above; the same-`gold_entity_id`-same-`type` pairing rule; the size floor (≥30 gold groups, ≥50 labelled pairs); the hard-case coverage checklist (honorifics, diacritics↔romanised, abbreviations, org variants); and a **named owner** line ("Owner: ____; benchmark must be filled and reviewed before the 8c gate"). State explicitly that this file is the funded/owned deliverable from the spec.

- [ ] **Step 2: Write `sample.json` (synthetic, deterministic fixture)**

Create ~8 entities across 3 gold groups and 2 types (e.g. 2 `person` gold groups, 1 `organization` group) with at least one obvious duplicate pair and one near-miss non-pair. ASCII-safe so harness tests don't depend on VI rendering. This is the fixture Tasks 2–5 assert against.

- [ ] **Step 3: Write `vi_blocking_v1.json` skeleton**

`{"_meta": {"name":"vi_blocking_v1","owner":"TODO-ASSIGN","language":"vi","notes":""}, "entities": []}` — the real data is filled by the owner; the harness + gate run against it once populated.

- [ ] **Step 4: Commit**

```bash
git add ennam.kg.python/benchmarks/ba031/schema.md \
        ennam.kg.python/benchmarks/ba031/sample.json \
        ennam.kg.python/benchmarks/ba031/vi_blocking_v1.json
git commit -m "docs(ba031-8b): blocking-benchmark dataset schema, labelling guide, synthetic fixture"
```

---

## Task 2: Dataset loader + validation

**Files:**
- Create: `src/ennam_kg/benchmark/__init__.py`, `src/ennam_kg/benchmark/dataset.py`
- Test: `tests/benchmark/test_dataset.py`

**Interfaces:**
- Produces:
  - `@dataclass BenchmarkEntity{id:str, gold_entity_id:str, type:str, canonical_name:str, aliases:list[str], description:str}`
  - `@dataclass Benchmark{name:str, owner:str, language:str, entities:list[BenchmarkEntity]}`
  - `load_benchmark(path:str) -> Benchmark` — parses JSON, validates: non-empty `id`/`gold_entity_id`/`canonical_name`; `type` ∈ the 8 extractable types; `id` unique; raises `BenchmarkError` on violation.
  - `true_pairs(b:Benchmark) -> set[frozenset[str]]` — all unordered `{id_a, id_b}` sharing `gold_entity_id` AND `type`.

- [ ] **Step 1: Write the failing tests**

```python
from ennam_kg.benchmark.dataset import load_benchmark, true_pairs, BenchmarkError

def test_loads_sample_and_computes_true_pairs():
    b = load_benchmark("benchmarks/ba031/sample.json")
    assert len(b.entities) >= 6
    tp = true_pairs(b)
    assert any(len(p) == 2 for p in tp)            # at least one duplicate pair
    # no cross-type pair exists
    by_id = {e.id: e for e in b.entities}
    for p in tp:
        a, c = tuple(p)
        assert by_id[a].type == by_id[c].type

def test_rejects_unknown_type(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"_meta":{"name":"x","owner":"o","language":"vi"},'
                   '"entities":[{"id":"e1","gold_entity_id":"g1","type":"vehicle",'
                   '"canonical_name":"X","aliases":[],"description":""}]}')
    try:
        load_benchmark(str(bad)); assert False, "expected BenchmarkError"
    except BenchmarkError:
        pass
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd ennam.kg.python && uv run pytest tests/benchmark/test_dataset.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `dataset.py`**

Implement the dataclasses, `EXTRACTABLE_TYPES` (import from `ennam_kg.extraction.schema` to stay DRY with 8a), `load_benchmark` (JSON parse → validate → construct), `BenchmarkError`, and `true_pairs` (group by `(gold_entity_id, type)`, emit all unordered intra-group pairs).

- [ ] **Step 4: Run to confirm pass**

Run: `cd ennam.kg.python && uv run pytest tests/benchmark/test_dataset.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/benchmark/__init__.py \
        ennam.kg.python/src/ennam_kg/benchmark/dataset.py \
        ennam.kg.python/tests/benchmark/test_dataset.py
git commit -m "feat(ba031-8b): benchmark dataset loader + validation + true_pairs"
```

---

## Task 3: Recall metric + offline T×K grid

The make-or-break math. Pure functions; no IO. Given, per query entity, the ranked candidate list (each `(node_id, rank)`) retrieved at the loosest setting, compute recall at any `(threshold, K)` by filtering offline.

**Files:**
- Create: `src/ennam_kg/benchmark/metrics.py`
- Test: `tests/benchmark/test_metrics.py`

**Interfaces:**
- Produces:
  - `recall_at_k(query_id:str, retrieved:list[tuple[str,float]], expected_dup_ids:set[str], threshold:float, k:int) -> tuple[int,int]` — returns `(found, total)` where `total = len(expected_dup_ids)` and `found` = how many expected ids appear among the candidates with `rank >= threshold` truncated to top-`k` by rank (query's own id excluded). `total == 0` → returns `(0, 0)` (query has no duplicate; excluded from aggregate).
  - `@dataclass GridCell{threshold:float, k:int, recall:float, found:int, total:int, avg_candidates:float}`
  - `evaluate_grid(per_query:dict[str,list[tuple[str,float]]], expected:dict[str,set[str]], thresholds:list[float], ks:list[int]) -> list[GridCell]` — aggregates `recall = sum(found)/sum(total)` over all queries with `total>0`; `avg_candidates` = mean candidate-set size after the `(threshold,k)` filter (cost proxy for 8c).

- [ ] **Step 1: Write the failing tests**

```python
from ennam_kg.benchmark.metrics import recall_at_k, evaluate_grid

def test_recall_filters_by_threshold_and_k():
    retrieved = [("dup1", 0.88), ("noise", 0.80), ("dup2", 0.73)]
    # threshold 0.75 keeps dup1+noise; k=10 -> dup1 found, dup2 filtered out (0.73<0.75)
    found, total = recall_at_k("q", retrieved, {"dup1", "dup2"}, threshold=0.75, k=10)
    assert (found, total) == (1, 2)
    # threshold 0.72 keeps all three; both dups found
    found, total = recall_at_k("q", retrieved, {"dup1", "dup2"}, threshold=0.72, k=10)
    assert (found, total) == (2, 2)
    # k=1 keeps only top-ranked dup1
    found, total = recall_at_k("q", retrieved, {"dup1", "dup2"}, threshold=0.72, k=1)
    assert (found, total) == (1, 2)

def test_recall_excludes_self_and_empty_total():
    found, total = recall_at_k("q", [("q", 0.99)], set(), threshold=0.5, k=10)
    assert (found, total) == (0, 0)

def test_evaluate_grid_aggregates():
    per_query = {"a": [("b", 0.90)], "b": [("a", 0.90)]}
    expected = {"a": {"b"}, "b": {"a"}}
    cells = evaluate_grid(per_query, expected, thresholds=[0.82], ks=[10])
    assert len(cells) == 1 and cells[0].recall == 1.0
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd ennam.kg.python && uv run pytest tests/benchmark/test_metrics.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `metrics.py`**

`recall_at_k`: filter `retrieved` to `rank >= threshold`, drop the query's own id, sort by rank desc, truncate to `k`, count how many are in `expected_dup_ids`; return `(found, total=len(expected))`. `evaluate_grid`: for each `(threshold,k)` sum `found`/`total` over queries with `total>0`, compute `avg_candidates`, emit a `GridCell`.

- [ ] **Step 4: Run to confirm pass**

Run: `cd ennam.kg.python && uv run pytest tests/benchmark/test_metrics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/benchmark/metrics.py \
        ennam.kg.python/tests/benchmark/test_metrics.py
git commit -m "feat(ba031-8b): recall@k metric + offline threshold×K grid"
```

---

## Task 4: Sweep harness (insert + embed + retrieve via injected deps)

Orchestrates the measurement. Inserts entities into the benchmark project, embeds via the 8a path, retrieves candidates once per entity at the loosest setting, returns the `per_query` map for `evaluate_grid`. All external deps injected so the logic is unit-testable with a fake retriever.

**Files:**
- Create: `src/ennam_kg/benchmark/sweep.py`
- Test: `tests/benchmark/test_sweep.py`

**Interfaces:**
- Consumes: `ennam_kg.extraction.embed.embed_entity(model, canonical_name, description)`; a `Retriever` protocol `retrieve(project_id, node_type, embedding, top_k, min_similarity) -> list[tuple[str,float]]` (real impl wraps the Go `/internal/resolution/candidates` via `httpx`; test impl is a fake); a `NodeWriter` protocol `insert_entity(project_id, entity, embedding) -> str` returning the created `node_id`.
- Produces:
  - `@dataclass SweepInputs{benchmark, project_id, thresholds, ks}`
  - `run_sweep(inputs, model, writer:NodeWriter, retriever:Retriever) -> tuple[dict[str,list[tuple[str,float]]], dict[str,set[str]]]` — returns `(per_query, expected)` ready for `evaluate_grid`. It (1) inserts + embeds every entity, mapping `benchmark.id → node_id`; (2) for each entity, retrieves at `top_k=max(ks)`, `min_similarity=min(thresholds)`; (3) translates returned `node_id`s back to benchmark ids; (4) builds `expected` from `true_pairs` (as benchmark ids).

- [ ] **Step 1: Write the failing test with fakes**

```python
from ennam_kg.benchmark.sweep import run_sweep, SweepInputs
from ennam_kg.benchmark.dataset import load_benchmark

class FakeModel:
    def encode_query(self, texts): return [[0.1, 0.2, 0.3]]   # constant vector
class FakeWriter:
    def __init__(self): self.ids = {}
    def insert_entity(self, project_id, entity, embedding):
        nid = "node_" + entity.id; self.ids[entity.id] = nid; return nid
class FakeRetriever:
    def __init__(self, by_query): self.by_query = by_query
    def retrieve(self, project_id, node_type, embedding, top_k, min_similarity):
        return self.by_query.get("called", [])  # simplified; real test keys per query

def test_run_sweep_maps_node_ids_back_to_benchmark_ids():
    b = load_benchmark("benchmarks/ba031/sample.json")
    # Build a retriever that, for any query, returns the other member of its gold group.
    inputs = SweepInputs(benchmark=b, project_id="bench-proj",
                         thresholds=[0.72, 0.82], ks=[5, 10])
    writer = FakeWriter()
    retriever = make_gold_aware_fake(b, writer)   # helper in the test
    per_query, expected = run_sweep(inputs, FakeModel(), writer, retriever)
    # expected pairs use benchmark ids, not node ids
    assert all(isinstance(qid, str) and not qid.startswith("node_") for qid in expected)
    # a query with a true duplicate surfaces it
    dup_q = next(q for q, exp in expected.items() if exp)
    assert any(cid in expected[dup_q] for cid, _ in per_query[dup_q])
```

> Provide `make_gold_aware_fake` in the test: it inserts entities via the writer, then returns, for each query, the node_ids of same-gold-same-type peers with a plausible rank (e.g. 0.88), so the sweep's id-translation and wiring are exercised deterministically.

- [ ] **Step 2: Run to confirm failure**

Run: `cd ennam.kg.python && uv run pytest tests/benchmark/test_sweep.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `sweep.py`**

Define the `Retriever`/`NodeWriter` `Protocol`s, `SweepInputs`, and `run_sweep` per the interface. Insert+embed each entity (capture `benchmark_id → node_id`); build reverse map `node_id → benchmark_id`; retrieve once per entity at the loosest `(min(thresholds), max(ks))`; map candidate `node_id`s back to benchmark ids (drop any not in the map — e.g. pre-existing nodes, though the isolated project should have none); build `expected` from `dataset.true_pairs` translated to benchmark ids. Return `(per_query, expected)`.

- [ ] **Step 4: Run to confirm pass**

Run: `cd ennam.kg.python && uv run pytest tests/benchmark/test_sweep.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/benchmark/sweep.py \
        ennam.kg.python/tests/benchmark/test_sweep.py
git commit -m "feat(ba031-8b): sweep harness (insert+embed+retrieve, injected deps)"
```

---

## Task 5: Report + gate check

Turns grid cells into a human-readable table and a machine gate decision.

**Files:**
- Create: `src/ennam_kg/benchmark/report.py`
- Test: `tests/benchmark/test_report.py`

**Interfaces:**
- Consumes: `list[GridCell]` from `evaluate_grid`.
- Produces:
  - `format_report(cells:list[GridCell]) -> str` — a markdown table (rows = thresholds, cols = K) of `recall` plus an `avg_candidates` companion table; highlights the K=10 column.
  - `meets_gate(cells:list[GridCell], min_recall:float=0.90, k:int=10, threshold_lo:float=0.72, threshold_hi:float=0.75) -> tuple[bool, GridCell|None]` — True iff some cell with `k==10` and `threshold_lo <= threshold <= threshold_hi` has `recall >= min_recall`; returns the best qualifying cell.

- [ ] **Step 1: Write the failing tests**

```python
from ennam_kg.benchmark.metrics import GridCell
from ennam_kg.benchmark.report import format_report, meets_gate

def test_meets_gate_true_when_k10_in_band_passes():
    cells = [
        GridCell(threshold=0.74, k=10, recall=0.92, found=46, total=50, avg_candidates=3.1),
        GridCell(threshold=0.82, k=10, recall=0.70, found=35, total=50, avg_candidates=1.2),
    ]
    ok, cell = meets_gate(cells)
    assert ok and cell.threshold == 0.74

def test_meets_gate_false_when_only_out_of_band_passes():
    cells = [GridCell(threshold=0.70, k=10, recall=0.95, found=47, total=50, avg_candidates=5.0)]
    ok, cell = meets_gate(cells)        # 0.70 is below the [0.72,0.75] band
    assert not ok

def test_format_report_contains_k10_and_recall():
    cells = [GridCell(threshold=0.74, k=10, recall=0.92, found=46, total=50, avg_candidates=3.1)]
    out = format_report(cells)
    assert "0.74" in out and "0.92" in out
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd ennam.kg.python && uv run pytest tests/benchmark/test_report.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `report.py`**

`format_report`: build markdown tables from the cells. `meets_gate`: filter cells to `k==k` and `threshold_lo <= threshold <= threshold_hi`, pick the max-recall cell, return `(recall>=min_recall, cell)`.

- [ ] **Step 4: Run to confirm pass**

Run: `cd ennam.kg.python && uv run pytest tests/benchmark/test_report.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/benchmark/report.py \
        ennam.kg.python/tests/benchmark/test_report.py
git commit -m "feat(ba031-8b): benchmark report + gate check (recall≥0.90 @K=10 in [0.72,0.75])"
```

---

## Task 6: CLI + live end-to-end run (real model + endpoint)

Wires the real `embed_entity` model, the real `httpx` retriever against the 8a endpoint, and a real `KGClient` writer into a runnable command. This is where the actual VI benchmark is measured.

**Files:**
- Create: `src/ennam_kg/benchmark/cli.py`
- Test: `tests/benchmark/test_cli.py` (smoke test on `sample.json` with the live model but a **local in-process** retriever/writer if the server isn't up; mark a live-server variant with the project's integration marker)

**Interfaces:**
- Consumes all of Tasks 2–5 + the real `model` (load the e5 model as `decompose.py` does), a `HttpxRetriever` (POSTs to `/api/v1/internal/resolution/candidates`), a `KGClientWriter` (wraps `ennam_kg_indexer.kg_client.client.KGClient` node-create + embedding upsert — reuse, don't hand-roll).
- Produces: `python -m ennam_kg.benchmark.cli --dataset benchmarks/ba031/vi_blocking_v1.json --project <uuid> --out report.md` → writes the report, prints the gate verdict, exits non-zero if the gate fails.

- [ ] **Step 1: Write the failing CLI smoke test**

```python
def test_cli_runs_on_sample_and_writes_report(tmp_path, monkeypatch):
    out = tmp_path / "r.md"
    # Inject fakes for model/writer/retriever via the cli's build_deps seam.
    rc = run_cli(["--dataset","benchmarks/ba031/sample.json","--project","p","--out",str(out)],
                 deps=fake_deps_that_pass_gate())
    assert out.exists()
    assert rc == 0
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd ennam.kg.python && uv run pytest tests/benchmark/test_cli.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `cli.py`**

`argparse` for `--dataset/--project/--out`; a `build_deps()` seam returning `(model, writer, retriever)` (real by default, overridable in tests); pipeline: `load_benchmark` → `run_sweep` → `evaluate_grid` → `format_report` (write `--out`) → `meets_gate` (print verdict; `sys.exit(0 if ok else 1)`).

- [ ] **Step 4: Run the smoke test to confirm pass**

Run: `cd ennam.kg.python && uv run pytest tests/benchmark/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Live dry-run on the synthetic fixture against a running server**

Bring up the stack (`docker compose up -d` or the documented integration harness), create an isolated benchmark project, and run:
`cd ennam.kg.python && uv run python -m ennam_kg.benchmark.cli --dataset benchmarks/ba031/sample.json --project <bench-uuid> --out /tmp/sample-report.md`
Expected: a report is written; the command exits with a verdict. (The synthetic fixture's pass/fail is not the real gate — this only proves the live wiring works end-to-end.)

- [ ] **Step 6: Commit**

```bash
git add ennam.kg.python/src/ennam_kg/benchmark/cli.py \
        ennam.kg.python/tests/benchmark/test_cli.py
git commit -m "feat(ba031-8b): benchmark CLI + live end-to-end wiring (e5 + candidates endpoint)"
```

---

## Phase 8b Done — Definition of Done

- [ ] Dataset schema + labelling guide published; `vi_blocking_v1.json` has a **named owner** and is **populated** with ≥30 gold groups / ≥50 labelled pairs in Vietnamese covering the hard cases (Task 1 + owner deliverable).
- [ ] Loader, metrics, grid, sweep, report, gate, CLI — all green (`cd ennam.kg.python && uv run pytest tests/benchmark/`).
- [ ] Live CLI run on `vi_blocking_v1.json` produces a report; **the gate verdict is recorded** (recall@K=10 in [0.72,0.75]).
- [ ] **Gate decision logged** in the report and a checkpoint: PASS (recall ≥0.90 → proceed to 8c; record the chosen `resolution_sim_threshold` + `resolution_top_k`) or FAIL (→ reconsider OQ-002 normaliser / re-embed strategy before 8c). Per Rule 12, a FAIL is surfaced, not hidden.

## Dependency & Hand-off Notes

- **Hard dependency on 8a:** the resolution-candidates endpoint (`POST /api/v1/internal/resolution/candidates`), `ChunkExtractionState`-independent (8b inserts entities directly, no Pass 1), and `extraction.embed.embed_entity`. Verified present at plan time (`internal/handler/resolution_candidates.go`, `src/ennam_kg/extraction/embed.py`).
- **Feeds 8c:** the chosen `resolution_sim_threshold` and `resolution_top_k` (from the passing grid cell) become 8c's defaults via `extraction-config`. If the gate fails, 8c is blocked.
- **Human deliverable owner:** the VI labelling is the funded/owned item from the spec — the engineering harness is useless without it. The plan ships the harness; the owner ships the data.

---

## Self-Review

- **Spec coverage (8b slice):** NFR-255/256/257 benchmark inputs → Tasks 1, 6 (dataset) + 3 (metrics); blocking-recall gate (spec §9 8b, "recall ≥90% @K=10") → Tasks 3, 5; threshold×K sweep (OQ-004) → Tasks 3, 4, 6; same-type/project isolation (FR-004/NFR-266) → Tasks 1, 4 (isolated project, type-scoped query); symmetric embedding (OQ-003) → reuse 8a `embed_entity` (Tasks 4, 6); OQ-002 revisit-if-fail → Task-6 DoD gate decision. Merge precision/recall (NFR-256/257 *merge*) is **8c**, correctly out of 8b scope — 8b measures blocking recall only.
- **Placeholder scan:** no TBD/TODO in harness code; the only intentional "TODO-ASSIGN" is the dataset owner field (a human deliverable, by design). All code steps carry real code + assertions.
- **Type consistency:** `BenchmarkEntity`/`Benchmark`/`true_pairs`, `recall_at_k`/`GridCell`/`evaluate_grid`, `run_sweep`/`SweepInputs`/`Retriever`/`NodeWriter`, `format_report`/`meets_gate` are referenced identically across tasks. `recall_at_k` returns `(found,total)` everywhere; `evaluate_grid` consumes `per_query`+`expected` exactly as `run_sweep` produces them.
- **Soft spots flagged (read before writing):** (a) exact `KGClient` node-create + embedding-upsert method names for the live writer (Task 6) — reuse, confirm signatures; (b) how the e5 model is loaded/shared in the worker process (mirror `decompose.py`) (Task 6); (c) the project's integration-test marker for the live-server CLI variant (Task 6 Step 5).
