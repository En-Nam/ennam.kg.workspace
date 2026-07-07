# DAAB Fuzzy Alias Merge (B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the parked 4695-row fuzzy alias merge backlog (gated by a stratified precision check) to consolidate same-entity aliases and tighten cross-document linking / Step-2 relatedness.

**Architecture:** B is **not new code in the apply path** — it runs the existing, tested `ApplySuggestionsService.Apply` (degree gate ON, no bypass) against the parked fuzzy `suggested` band, **after** a stratified human-adjudicated precision gate passes. Net new code = one Python sampling/scoring script. The manifest is a pre-apply SQL snapshot (no Go change). Reversible via the existing un-merge.

**Tech Stack:** Python 3.12 (`ennam.kg.python`: psycopg, reuse `_normalize`), Go apply path (reuse), psql for the runbook. Tests: `pytest` for the script's pure logic.

**Design spec:** `docs/superpowers/specs/2026-06-30-daab-fuzzy-alias-merge-design.md`

## Global Constraints

- DB on **:5433** (`postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg`). Python direct-DB uses `KG_DATABASE_URL` (as `classify_corpus_cli.py` does). API via `KG_API_URL`/`KG_API_KEY`.
- **Degree gate STAYS ON** — apply via the generic `/apply` (`Apply(projectID, threshold)`, `bypassDegreeGate=false`). NEVER add a bypass variant (fuzzy ≠ identity).
- **Do NOT call `/apply` until the precision gate passes.** The generic `/apply` would flush all 4695 ungated-by-precision (degree gate is inert for an all-leaf set); it is dormant (the worker only auto-calls `/apply-exact-name`), so the operational rule is the safeguard.
- **Reversible:** `merge.go` sets `merged_into`/`merge_undo`/`re_embed_pending` + re-points edges; un-merge restores byte-equivalent.
- Verdicts are trusted (LLM-judged) — **do NOT re-run BA-031 Pass-2**. No new discriminator, no `merge.go`/`pass2.py` changes, no migration.
- Project: the corpus project (`592c7ff7-9f6f-4cc5-9094-d9b3b685277e` at time of writing — re-verify; counts are point-in-time).

---

## Task 1: Python precision-sampling script `fuzzy_sample_cli.py`

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/resolution/fuzzy_sample_cli.py`
- Test: `ennam.kg.python/tests/resolution/test_fuzzy_sample.py`

**Interfaces:**
- Pure, unit-tested helpers:
  - `is_danger_pair(name_a: str, name_b: str) -> bool` — true when, after `_normalize` + dropping admin/abbreviation boilerplate, a SUBSTANTIVE token differs (the cross-place / different-number false-merge class). Recall-oriented (over-flags safe diacritic diffs; the human adjudicates).
  - `wilson_lcb(successes: int, n: int, z: float = 1.96) -> float` — Wilson score lower bound.
- CLI: `--draw` (write the two strata to a CSV for adjudication) and `--score <file>` (read adjudicated labels → precision + LCB per stratum → PASS/FAIL).

- [ ] **Step 1: Write the failing unit tests**

Create `tests/resolution/test_fuzzy_sample.py`:
```python
from ennam_kg.resolution.fuzzy_sample_cli import is_danger_pair, wilson_lcb

def test_danger_cross_place_pair():
    # different province → DANGER (potential false merge)
    assert is_danger_pair("UBND tỉnh Trà Vinh", "UBND tỉnh Sóc Trăng") is True

def test_danger_different_number():
    assert is_danger_pair("Quyết định 1283", "Quyết định 2443") is True

def test_safe_abbreviation_alias_not_danger():
    # same entity, abbreviation vs full → NOT danger (boilerplate dropped, residual equal)
    assert is_danger_pair("UBND thị xã Duyên Hải", "Ủy ban nhân dân thị xã Duyên Hải") is False

def test_safe_missing_conjunction_not_danger():
    assert is_danger_pair("Sở Tài nguyên và Môi trường", "Sở Tài nguyên Môi trường") is False

def test_wilson_lcb_bounds():
    # 96/100 successes → LCB clearly below the point estimate (≈0.90), under 0.96
    lcb = wilson_lcb(96, 100)
    assert 0.88 < lcb < 0.96
    # all-fail small sample → low LCB
    assert wilson_lcb(0, 10) < 0.35
```

- [ ] **Step 2: Run → fail**

Run: `cd ennam.kg.python && uv run pytest tests/resolution/test_fuzzy_sample.py -v` → FAIL (no module).

- [ ] **Step 3: Implement the script**

Create `src/ennam_kg/resolution/fuzzy_sample_cli.py`:
```python
"""Stratified precision sampling for the fuzzy alias merge backlog (B).

--draw  : draw a random + a targeted (danger) stratum from the parked fuzzy
          'suggested' band, write a CSV for human adjudication (label column blank).
--score : read the adjudicated CSV, compute precision + Wilson LCB per stratum, PASS/FAIL.
"""
from __future__ import annotations
import argparse
import csv
import math
import os
import random
import re

from ennam_kg.resolution.rules import _normalize

# Admin/org boilerplate + abbreviation-expansion noise. Differences confined to
# these tokens are SAFE (abbreviation/conjunction/diacritic), not entity-distinguishing.
_NOISE = {
    "ubnd", "ủy", "uy", "ban", "nhân", "nhan", "dân", "dan", "và", "va",
    "tỉnh", "tinh", "thành", "thanh", "phố", "pho", "tp", "thị", "thi", "xã", "xa",
    "phường", "phuong", "huyện", "huyen", "quận", "quan", "sở", "so", "bộ", "bo",
    "cục", "cuc", "của", "cua", "hội", "hoi", "đồng", "dong",
}

def is_danger_pair(name_a: str, name_b: str) -> bool:
    """True if a substantive (non-boilerplate) token or a number differs — the
    cross-place / different-number false-merge class. Recall-oriented."""
    a, b = _normalize(name_a), _normalize(name_b)
    if set(re.findall(r"\d+", a)) != set(re.findall(r"\d+", b)):
        return True
    ta = {t for t in a.split() if t not in _NOISE and not t.isdigit()}
    tb = {t for t in b.split() if t not in _NOISE and not t.isdigit()}
    return bool(ta.symmetric_difference(tb))

def wilson_lcb(successes: int, n: int, z: float = 1.96) -> float:
    """Wilson score interval lower bound for a binomial proportion."""
    if n == 0:
        return 0.0
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return (centre - margin) / denom

# ---- DB + CLI ----

async def _load_band_async(project_id: str) -> list[dict]:
    import asyncpg  # the repo's driver (see classify_corpus_cli.py); asyncpg uses $1 placeholders
    conn = await asyncpg.connect(os.environ["KG_DATABASE_URL"])
    try:
        rows = await conn.fetch(
            """
            SELECT ms.id::text, na.title, nb.title, ms.embedding_similarity
            FROM merge_suggestions ms
            JOIN knowledge_nodes na ON na.id = ms.node_a_id
            JOIN knowledge_nodes nb ON nb.id = ms.node_b_id
            WHERE ms.project_id = $1::uuid AND ms.decision = 'suggested'
              AND ms.reason <> 'exact normalized name match'
            """,
            project_id,
        )
        return [{"id": r[0], "a": r[1], "b": r[2], "sim": float(r[3] or 0)} for r in rows]
    finally:
        await conn.close()

def _load_band(project_id: str) -> list[dict]:
    import asyncio
    return asyncio.run(_load_band_async(project_id))

def _draw(project_id: str, out_path: str, n_random: int, n_targeted: int, seed: int) -> None:
    rng = random.Random(seed)
    band = _load_band(project_id)
    danger = [r for r in band if is_danger_pair(r["a"], r["b"])]
    safe = [r for r in band if not is_danger_pair(r["a"], r["b"])]
    random_stratum = rng.sample(band, min(n_random, len(band)))
    targeted_stratum = rng.sample(danger, min(n_targeted, len(danger)))
    rows = [{**r, "stratum": "random"} for r in random_stratum] + \
           [{**r, "stratum": "targeted"} for r in targeted_stratum]
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "stratum", "a", "b", "sim", "same_entity"])
        w.writeheader()
        for r in rows:
            w.writerow({"id": r["id"], "stratum": r["stratum"], "a": r["a"], "b": r["b"], "sim": r["sim"], "same_entity": ""})
    print(f"band={len(band)} danger={len(danger)} safe={len(safe)} -> wrote {len(rows)} rows to {out_path}")
    print("Adjudicate the 'same_entity' column (1=same, 0=different), then run --score.")

def _score(in_path: str, random_thr: float, targeted_thr: float) -> None:
    strata: dict[str, list[int]] = {"random": [], "targeted": []}
    with open(in_path, newline="") as f:
        for row in csv.DictReader(f):
            lbl = row["same_entity"].strip()
            if lbl in ("0", "1"):
                strata[row["stratum"]].append(int(lbl))
    ok = True
    for name, thr in (("random", random_thr), ("targeted", targeted_thr)):
        labels = strata[name]
        n, s = len(labels), sum(labels)
        lcb = wilson_lcb(s, n)
        passed = n > 0 and lcb >= thr
        ok = ok and passed
        print(f"{name}: n={n} precision={s}/{n} lcb={lcb:.3f} threshold={thr} -> {'PASS' if passed else 'FAIL'}")
    print(f"\nGATE: {'PASS — safe to run /apply' if ok else 'FAIL — do NOT apply; see spec §6 (pre-filter danger pairs and re-gate)'}")

def main() -> None:
    p = argparse.ArgumentParser(description="Fuzzy alias merge precision sampling (B)")
    p.add_argument("--project", required=True)
    p.add_argument("--draw", metavar="OUT_CSV")
    p.add_argument("--score", metavar="ADJUDICATED_CSV")
    p.add_argument("--n-random", type=int, default=100)
    p.add_argument("--n-targeted", type=int, default=100)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--random-threshold", type=float, default=0.95)
    p.add_argument("--targeted-threshold", type=float, default=0.90)
    args = p.parse_args()
    if args.draw:
        _draw(args.project, args.draw, args.n_random, args.n_targeted, args.seed)
    elif args.score:
        _score(args.score, args.random_threshold, args.targeted_threshold)
    else:
        p.error("one of --draw / --score is required")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run → pass**

Run: `uv run pytest tests/resolution/test_fuzzy_sample.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/resolution/fuzzy_sample_cli.py tests/resolution/test_fuzzy_sample.py
git commit -m "feat(daab): stratified precision sampling for fuzzy alias merge (B)"
```

---

## Task 2: Operational runbook — gate → apply → verify (no new Go code)

**Files:** none (operational; reuses the shipped apply path). Record outputs.

- [ ] **Step 1: Step-0 verify (live)**

```sql
-- band == all suggested? (must be equal; else add a reason-exclusion lister — spec §7)
SELECT (SELECT count(*) FROM merge_suggestions WHERE project_id=:P AND decision='suggested') AS all_suggested,
       (SELECT count(*) FROM merge_suggestions WHERE project_id=:P AND decision='suggested'
              AND reason <> 'exact normalized name match') AS fuzzy;
-- reasons are LLM verdicts (not the deleted sim-rule)?
SELECT reason, count(*) FROM merge_suggestions
 WHERE project_id=:P AND decision='suggested' AND reason <> 'exact normalized name match'
 GROUP BY reason ORDER BY 2 DESC LIMIT 15;
```
Expected: `all_suggested == fuzzy`; reasons are natural-language LLM judgments. If `all_suggested > fuzzy` → STOP, add the reason-exclusion lister (spec §7) before applying.

- [ ] **Step 2: Snapshot the manifest (pre-apply, for rollback)**

```sql
\copy (SELECT ms.id, ms.node_a_id, ms.node_b_id, ms.proposed_canonical_id, na.title AS a, nb.title AS b, ms.embedding_similarity, ms.merge_confidence
       FROM merge_suggestions ms JOIN knowledge_nodes na ON na.id=ms.node_a_id JOIN knowledge_nodes nb ON nb.id=ms.node_b_id
       WHERE ms.project_id=:P AND ms.decision='suggested' AND ms.reason <> 'exact normalized name match')
  TO 'fuzzy_merge_manifest_<date>.csv' CSV HEADER;
```
This is the audit/rollback manifest (the set that will be applied).

- [ ] **Step 3: Draw the precision sample**

Run: `KG_DATABASE_URL=... uv run python -m ennam_kg.resolution.fuzzy_sample_cli --project <PID> --draw fuzzy_sample.csv`
Note the printed `band/danger/safe` counts (sizes the strata).

- [ ] **Step 4: Human adjudicate**

Fill the `same_entity` column in `fuzzy_sample.csv` (1=same entity, 0=different). For each pair decide: is this truly the SAME real-world entity? Pay special attention to the `targeted` stratum (cross-place/number differences). Record any false-merge patterns observed.

- [ ] **Step 5: Score the gate**

Run: `uv run python -m ennam_kg.resolution.fuzzy_sample_cli --project <PID> --score fuzzy_sample.csv`
Expected output: precision + Wilson LCB per stratum + GATE PASS/FAIL.
- **PASS** (random LCB ≥ 0.95 AND targeted LCB ≥ 0.90) → proceed to Step 6.
- **FAIL on targeted** → STOP. The danger class is real; build a deterministic pre-filter excluding `is_danger_pair` rows from this apply run (move them to `needs_review` or scope the apply), re-run Steps 3-5 on the remainder. Do NOT apply.

- [ ] **Step 6: Apply (only after PASS)**

```bash
curl -sS -XPOST "$KG_API_URL/api/v1/internal/resolution/apply" \
  -H "Authorization: Bearer $KG_API_KEY" -H 'Content-Type: application/json' \
  -d "{\"project_id\":\"<PID>\"}"
```
This runs the gated `Apply` (degree gate ON; `apply_mode=apply` required). Response: `{applied, needs_review, errors}`. Expect `applied ≈ band size`, `needs_review` for any hub-accretion, `errors` ideally empty. (Worker does NOT auto-call this — it is a deliberate, one-time manual run.)

- [ ] **Step 7: Post-apply verify + consumer window**

```sql
-- duplicate-node count dropped (canonical accreted aliases)
SELECT count(*) AS concepts, count(DISTINCT lower(btrim(title))) AS distinct_names
FROM knowledge_nodes WHERE node_type='concept' AND project_id=:P AND COALESCE(properties->>'merged_into','')='';
```
- Re-sample ~50 applied merges (from the manifest, now `decision='applied'`) and eyeball for false merges — target 0; un-merge any via the existing un-merge path, using the manifest id.
- **Consumer window:** the merge sets `re_embed_pending`; let the worker re-embed. Step-2 IDF is query-time (self-updates). Spot-check Step-2: pick 2 docs sharing an alias-pair now merged (e.g. both mention "Bộ Giao thông vận tải") and confirm `kg_document_shared_entities` returns the single canonical.

- [ ] **Step 8: Checkpoint + backlog**

Serena checkpoint; mark B done; update `mem:backlog/daab-entity-resolution-corpus-rerun`. Record the gate result (precision LCBs) and any false-merge patterns. Note deferred follow-ups (fuzzy HUBS; one-token-diff pre-filter if it was needed; wiring fuzzy auto-apply into the live pipeline; OCR-garbled entity cleanup).

---

## Self-Review notes (author)

- **Spec coverage:** precision gate §6 → T1 + T2 Steps 3-5; apply mechanism §7 → T2 Step 6 (existing `Apply`, degree gate ON); trapdoor §8 → the "do not call /apply until gate passes" constraint; manifest §7/§10 → T2 Step 2 (SQL snapshot, no Go change); consumer window §9 → T2 Step 7; reversibility §10 → un-merge in T2 Step 7; defer hubs §11 → free (degree gate). Step-0 §4 → T2 Step 1.
- **Verified anchors:** `Apply(projectID, threshold)` = reason-agnostic `ListByProject('suggested')` + `processSuggestion(...,false,...)` gate-on (`apply_suggestions.go:84-95`); `HandleApply` body `{project_id}`, gated `ApplyMode != "apply"` (config threshold); `maxSuggestions=10000` (one call covers 4695); `merge.go` re-points edges + sets `re_embed_pending`; worker auto-calls only `/apply-exact-name`; `_normalize` + `KG_DATABASE_URL` pattern from `classify_corpus_cli.py`. ApplyResult has only counts → manifest is the pre-apply SQL snapshot (no Go change).
- **No new Go code, no migration, no `merge.go`/`pass2.py` change.** Net new = one Python script + the runbook. This matches B's reality: "run the existing gated path, after a precision gate."
- **Verified (corrected here):** the repo's Python DB driver is **`asyncpg`** (dep `asyncpg>=0.30`; `classify_corpus_cli.py` uses `asyncpg.connect` + `$1` placeholders) — `_load_band` uses asyncpg async wrapped in `asyncio.run`, NOT psycopg. `_normalize` lowercases + NFC + collapses separators + strips leading honorifics and **keeps diacritics** + splits on space → the `is_danger_pair` tests hold and `_NOISE` matches the diacritic-bearing normalized tokens. The 4695 fuzzy rows all have a valid `proposed_canonical_id` (0 NULL, 0 not-in-pair) → `processSuggestion` validation passes, `Apply` won't error on them (so `errors` empty / `applied ≈ band` is realistic).
- **Confirm at execution:** the `is_danger_pair` `_NOISE` stoplist may need tuning after the first `--draw` (recall-oriented is intentional; the human is the final gate); the default thresholds (0.95/0.90) are a starting point — tune from the first scored run.
