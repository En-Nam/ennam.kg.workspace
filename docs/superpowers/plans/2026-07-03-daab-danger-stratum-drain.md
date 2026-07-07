# DAAB Danger-Stratum Drain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely drain the 3148 parked `needs_review` danger-stratum merge suggestions — auto-clear only rows that match a named deterministic rule class, pass all guards, and clear a per-class safety gate; route the rest to a human CLI.

**Architecture:** All rule/guard/gate logic lives in Python (pure functions + a partition CLI). Rows that qualify are flipped to `decision='review_cleared'` and drained by the existing Go `ApplyReviewClearedMerges` applier — **no Go merge-code change**. A second CLI handles the human (L3) residual. Reversible via `merge_undo`.

**Tech Stack:** Python 3.12 (`ennam.kg.python`: asyncpg, pytest, ruff), reusing `de_diacritic_base`, `wilson_lcb`, `_normalize`. Drain endpoint: existing `POST /api/v1/internal/resolution/apply-review-cleared`.

**Design spec:** `docs/superpowers/specs/2026-07-03-daab-danger-stratum-drain-design.md`

## Global Constraints

- Nested repos; run from `ennam.kg.python`. DB :5433 (`KG_DATABASE_URL=postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg`). Server host port **:8082** (compose maps 8082→8080).
- asyncpg driver: `$1`/`$2` placeholders, `$1::uuid` cast. `KG_DATABASE_URL` env.
- Project `592c7ff7-9f6f-4cc5-9094-d9b3b685277e` (re-verify; counts point-in-time). `review_cleared` currently = 0 (clean for reuse).
- **Confidence ≥ 0.9 is a within-class filter (necessary, not sufficient) — NEVER a standalone class.** Every auto-cleared row belongs to a rule class AND passes all guards.
- **Guards are conjunctive and block even at conf = 1.0.** Rows failing any guard / any class failing its gate / all concept nodes / all conf < 0.9 → stay `needs_review` (L3).
- Reuse: `de_diacritic_base` (`hub_partition_cli`), `_normalize` (`rules.py`), `wilson_lcb` (`fuzzy_sample_cli`), `ApplyReviewClearedMerges` (Go, unchanged). No `merge.go`/`pass2.py` change.
- ruff line-length=100, target py312. Use `logging`, not `print`, in importable modules (CLIs may print user output).

---

## Task 1: Guards G1–G6 (pure)

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/resolution/danger_guards.py`
- Test: `ennam.kg.python/tests/resolution/test_danger_guards.py`

**Interfaces:**
- Produces: `passes_guards(a: str, b: str, node_type: str) -> bool` — True iff the pair passes ALL of G1–G6. Also exposes each guard `block_g1_number(a,b) -> bool` … `block_g6_ocr_concat(a,b) -> bool` (each returns True = BLOCK) for unit testing.

- [ ] **Step 1: failing tests** — create `tests/resolution/test_danger_guards.py`:

```python
from ennam_kg.resolution.danger_guards import passes_guards, block_g1_number

def test_g1_blocks_alphanumeric_code_mismatch():
    # \d+ alone would MISS this (both yield ['479']); must use digit-containing tokens.
    assert block_g1_number("thửa đất số I479", "thửa đất số 479") is True
    assert block_g1_number("bãi chứa K8", "bãi đồ K8") is False  # same code token

def test_passes_guards_blocks_documented_false_positives():
    assert passes_guards("Tổng giám đốc", "Giám đốc", "person") is False          # G2 role
    assert passes_guards("Chủ tịch Hội đồng", "Chủ tịch Hội đồng thành viên", "organization") is False  # G3 scope
    assert passes_guards("Kiểm soát viên của công ty mẹ", "Kiểm soát viên", "person") is False          # G3 scope
    assert passes_guards("doanh nghiệp", "công ty", "concept") is False           # G4 generic
    assert passes_guards("sông Trà Vinh", "tỉnh Trà Vinh", "location") is False   # G5 conflicting unit
    assert passes_guards("BỘ GIAO THÔNG VẬN TẢI CỘNG HÒA XÃ HỘI CHỦ NGHĨA", "Bộ Giao thông Vận tải", "organization") is False  # G6 concat+extra

def test_passes_guards_allows_legit_variants():
    assert passes_guards("Bộ GTVT", "Bộ Giao thông vận tải", "organization") is True
    assert passes_guards("Trà Vinh", "tỉnh Trà Vinh", "location") is True         # bare↔unit: NOT blocked by G5
    assert passes_guards("Bộ Xây dựng (XD)", "Bộ Xây dựng", "organization") is True
```

- [ ] **Step 2: run to verify fail** — `uv run pytest tests/resolution/test_danger_guards.py -q` → FAIL (module missing).

- [ ] **Step 3: implement** — create `src/ennam_kg/resolution/danger_guards.py`:

```python
"""Conjunctive guards G1-G6 for danger-stratum auto-clear. Each block_* returns
True = BLOCK the merge. passes_guards = True iff none block. Guards are applied
AFTER rule normalization and block even at LLM confidence 1.0."""
from __future__ import annotations
import re
from ennam_kg.resolution.rules import _normalize

# Admin/geo unit words (Vietnamese). Presence differences drive R4 (bare↔unit)
# and G5 (unit↔different-unit).
ADMIN_UNITS = {"tỉnh", "thành phố", "tp", "thị xã", "huyện", "quận", "phường", "xã", "sông"}
# Seniority/role modifiers that change identity.
ROLE_MODIFIERS = {"tổng", "phó", "trưởng", "thành viên", "mẹ", "con"}
# Bare generic common nouns — merging these is semantic drift.
GENERICS = {"doanh nghiệp", "các doanh nghiệp", "công ty", "cơ quan", "địa phương",
            "khu vực", "đơn vị", "tổ chức"}

def _tokens(s: str) -> list[str]:
    return _normalize(s).split()

def block_g1_number(a: str, b: str) -> bool:
    """Digit-containing code tokens must match as a multiset. Uses \\w*\\d\\w*
    (NOT \\d+) so 'I479' != '479' is caught; 'K8' == 'K8' passes."""
    ca = sorted(re.findall(r"\w*\d\w*", _normalize(a)))
    cb = sorted(re.findall(r"\w*\d\w*", _normalize(b)))
    return ca != cb

def block_g2_role(a: str, b: str) -> bool:
    ta, tb = set(_tokens(a)), set(_tokens(b))
    diff = ta.symmetric_difference(tb)
    return bool(diff & {"tổng", "phó", "trưởng"})

def block_g3_scope(a: str, b: str) -> bool:
    ta, tb = set(_tokens(a)), set(_tokens(b))
    diff = ta.symmetric_difference(tb)
    return bool(diff & {"thành viên", "mẹ", "con"})

def block_g4_generic(a: str, b: str) -> bool:
    na, nb = _normalize(a), _normalize(b)
    return na in GENERICS or nb in GENERICS

def _units_in(s: str) -> set[str]:
    n = _normalize(s)
    return {u for u in ADMIN_UNITS if re.search(rf"\b{re.escape(u)}\b", n)}

def block_g5_admin_unit(a: str, b: str) -> bool:
    """Block only when BOTH sides carry an admin unit and they are DIFFERENT
    (sông vs tỉnh). Bare↔unit (Trà Vinh vs tỉnh Trà Vinh) is the R4 case — allowed."""
    ua, ub = _units_in(a), _units_in(b)
    return bool(ua) and bool(ub) and ua != ub

def block_g6_ocr_concat(a: str, b: str) -> bool:
    """Longer side contains the shorter as a substring PLUS >=3 extra tokens."""
    na, nb = _normalize(a), _normalize(b)
    lo, hi = sorted([na, nb], key=len)
    if lo and lo in hi:
        extra = len(hi.split()) - len(lo.split())
        return extra >= 3
    return False

def passes_guards(a: str, b: str, node_type: str) -> bool:
    return not (
        block_g1_number(a, b) or block_g2_role(a, b) or block_g3_scope(a, b)
        or block_g4_generic(a, b) or block_g5_admin_unit(a, b) or block_g6_ocr_concat(a, b)
    )
```

- [ ] **Step 4: run to verify pass** — `uv run pytest tests/resolution/test_danger_guards.py -q` → PASS. If a guard over-blocks a legit variant, tune only that guard's token set.

- [ ] **Step 5: commit**

```bash
git add src/ennam_kg/resolution/danger_guards.py tests/resolution/test_danger_guards.py
git commit -m "feat(daab): danger-stratum guards G1-G6 (conjunctive, block at conf=1.0)"
```

---

## Task 2: Rule classes R1–R4 + classifier (pure)

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/resolution/danger_rules.py`
- Test: `ennam.kg.python/tests/resolution/test_danger_rules.py`

**Interfaces:**
- Consumes: `de_diacritic_base` (`hub_partition_cli`), `passes_guards` (Task 1), `_normalize`.
- Produces: `rule_class(a: str, b: str, node_type: str) -> str | None` — returns `"R1"|"R2"|"R3"|"R4"` if a rule matches (BEFORE guards), else None. `auto_clear_class(a, b, node_type) -> str | None` — returns the class only if a rule matches AND `passes_guards` AND `node_type != "concept"`, else None.

- [ ] **Step 1: failing tests** — create `tests/resolution/test_danger_rules.py`:

```python
from ennam_kg.resolution.danger_rules import rule_class, auto_clear_class

def test_r1_parenthetical():
    assert rule_class("Bộ Xây dựng (XD)", "Bộ Xây dựng", "organization") == "R1"

def test_r2_abbreviation_whitelist():
    assert rule_class("Bộ GTVT", "Bộ Giao thông vận tải", "organization") == "R2"
    assert rule_class("UBND tỉnh Trà Vinh", "Ủy ban nhân dân tỉnh Trà Vinh", "organization") == "R2"

def test_r3_country_crosslang():
    assert rule_class("Việt Nam", "Vietnam", "location") == "R3"

def test_r4_admin_prefix_location_only():
    assert rule_class("Trà Vinh", "tỉnh Trà Vinh", "location") == "R4"
    assert rule_class("Trà Vinh", "tỉnh Trà Vinh", "organization") is None  # R4 fenced to location

def test_auto_clear_respects_guards_and_concept():
    assert auto_clear_class("Bộ GTVT", "Bộ Giao thông vận tải", "organization") == "R2"
    assert auto_clear_class("doanh nghiệp", "các doanh nghiệp", "concept") is None      # concept excluded
    assert auto_clear_class("sông Trà Vinh", "tỉnh Trà Vinh", "location") is None       # G5 blocks
```

- [ ] **Step 2: run to verify fail** — `uv run pytest tests/resolution/test_danger_rules.py -q` → FAIL.

- [ ] **Step 3: implement** — create `src/ennam_kg/resolution/danger_rules.py`:

```python
"""Deterministic rule classes R1-R4 for danger-stratum auto-clear. A row is a
class member iff both sides collapse to an identical key under the class transform.
auto_clear_class additionally requires passes_guards and node_type != concept."""
from __future__ import annotations
import re
from ennam_kg.resolution.hub_partition_cli import de_diacritic_base
from ennam_kg.resolution.danger_guards import passes_guards, ADMIN_UNITS

# R2: closed abbreviation whitelist (human-signed). Key = de_diacritic_base of abbrev.
ABBREV = {
    "gtvt": "giao thong van tai",
    "ubnd": "uy ban nhan dan",
    "hdnd": "hoi dong nhan dan",
    "xd": "xay dung",
    "tnmt": "tai nguyen va moi truong",
    "bql": "ban quan ly",
}
# R3: closed cross-language country/proper-noun map (de_diacritic_base keys).
COUNTRY = {"viet nam": "vietnam", "vietnam": "viet nam"}

def _r1(a: str, b: str) -> bool:
    def strip_paren(s: str) -> str:
        return de_diacritic_base(re.sub(r"\s*\([^)]*\)\s*", " ", s))
    return strip_paren(a) == de_diacritic_base(b) or strip_paren(b) == de_diacritic_base(a)

def _expand_abbrev(base: str) -> str:
    return " ".join(ABBREV.get(tok, tok) for tok in base.split())

def _r2(a: str, b: str) -> bool:
    ea, eb = _expand_abbrev(de_diacritic_base(a)), _expand_abbrev(de_diacritic_base(b))
    return ea == eb and de_diacritic_base(a) != de_diacritic_base(b)

def _r3(a: str, b: str) -> bool:
    ba, bb = de_diacritic_base(a), de_diacritic_base(b)
    return COUNTRY.get(ba) == bb or COUNTRY.get(bb) == ba

def _strip_leading_unit(base: str) -> tuple[str, bool]:
    toks = base.split()
    for u in sorted(ADMIN_UNITS, key=lambda x: -len(x)):
        ub = de_diacritic_base(u)
        parts = ub.split()
        if toks[: len(parts)] == parts:
            return " ".join(toks[len(parts):]), True
    return base, False

def _r4(a: str, b: str, node_type: str) -> bool:
    if node_type != "location":
        return False
    ba, bb = de_diacritic_base(a), de_diacritic_base(b)
    sa, ua = _strip_leading_unit(ba)
    sb, ub = _strip_leading_unit(bb)
    # exactly one side carried a unit, remainders equal
    return (ua != ub) and (sa == sb) and sa != ""

def rule_class(a: str, b: str, node_type: str) -> str | None:
    if _r1(a, b):
        return "R1"
    if _r2(a, b):
        return "R2"
    if _r3(a, b):
        return "R3"
    if _r4(a, b, node_type):
        return "R4"
    return None

def auto_clear_class(a: str, b: str, node_type: str) -> str | None:
    if node_type == "concept":
        return None
    cls = rule_class(a, b, node_type)
    if cls is None:
        return None
    return cls if passes_guards(a, b, node_type) else None
```

- [ ] **Step 4: run to verify pass** — `uv run pytest tests/resolution/test_danger_rules.py -q` → PASS.

- [ ] **Step 5: commit**

```bash
git add src/ennam_kg/resolution/danger_rules.py tests/resolution/test_danger_rules.py
git commit -m "feat(daab): danger-stratum rule classes R1-R4 + guarded classifier"
```

---

## Task 3: Partition CLI (classify, sample, score, apply-class)

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/resolution/danger_partition_cli.py`
- Test: `ennam.kg.python/tests/resolution/test_danger_partition.py`

**Interfaces:**
- Consumes: `auto_clear_class`, `rule_class` (Task 2), `wilson_lcb` (`fuzzy_sample_cli`), asyncpg.
- Produces: CLI `python -m ennam_kg.resolution.danger_partition_cli` with:
  - `--project <uuid> --dry-run` → prints per-class counts, guard-block count, concept/conf<0.9/L3 counts (no writes).
  - `--project <uuid> --sample <R1|R2|R3|R4> --out <csv>` → writes a human-label CSV for that class (column `same_entity` blank).
  - `--score <csv>` → prints `wilson_lcb`; a helper `class_report(rows) -> dict[str,int]` is unit-tested.
  - `--project <uuid> --apply-class <R1|R2|R3|R4>` → flips that class's rows (conf≥0.9, guarded) to `decision='review_cleared'`.

- [ ] **Step 1: failing test (pure aggregation)** — create `tests/resolution/test_danger_partition.py`:

```python
from ennam_kg.resolution.danger_partition_cli import class_report

def test_class_report_buckets_rows():
    rows = [
        {"a": "Bộ GTVT", "b": "Bộ Giao thông vận tải", "node_type": "organization", "conf": 0.99},
        {"a": "Trà Vinh", "b": "tỉnh Trà Vinh", "node_type": "location", "conf": 1.0},
        {"a": "doanh nghiệp", "b": "công ty", "node_type": "concept", "conf": 0.75},   # concept + low conf -> L3
        {"a": "Tổng giám đốc", "b": "Giám đốc", "node_type": "person", "conf": 0.95},  # guard-block -> L3
    ]
    rep = class_report(rows)
    assert rep["R2"] == 1
    assert rep["R4"] == 1
    assert rep["L3"] == 2
```

- [ ] **Step 2: run to verify fail** — `uv run pytest tests/resolution/test_danger_partition.py -q` → FAIL.

- [ ] **Step 3: implement** — create `src/ennam_kg/resolution/danger_partition_cli.py`:

```python
"""Danger-stratum partition CLI. Classifies needs_review rows into rule classes
R1-R4 (guarded, conf>=0.9, non-concept), emits per-class human-label samples,
scores precision via wilson_lcb, and flips a Wilson-passed / construction-safe
class to decision='review_cleared' for the existing ApplyReviewClearedMerges drain."""
from __future__ import annotations
import argparse
import asyncio
import csv
import os
from ennam_kg.resolution.danger_rules import auto_clear_class
from ennam_kg.resolution.fuzzy_sample_cli import wilson_lcb

CONF_FLOOR = 0.9

def class_report(rows: list[dict]) -> dict[str, int]:
    """Bucket rows by auto_clear_class (conf>=floor); everything else -> L3."""
    rep = {"R1": 0, "R2": 0, "R3": 0, "R4": 0, "L3": 0}
    for r in rows:
        cls = auto_clear_class(r["a"], r["b"], r["node_type"]) if r["conf"] >= CONF_FLOOR else None
        rep[cls if cls else "L3"] += 1
    return rep

async def _load(project_id: str) -> list[dict]:
    import asyncpg
    conn = await asyncpg.connect(os.environ["KG_DATABASE_URL"])
    try:
        rows = await conn.fetch(
            """
            SELECT ms.id::text, na.title AS a, nb.title AS b,
                   nc.node_type, ms.merge_confidence AS conf
            FROM merge_suggestions ms
            JOIN knowledge_nodes na ON na.id = ms.node_a_id
            JOIN knowledge_nodes nb ON nb.id = ms.node_b_id
            JOIN knowledge_nodes nc ON nc.id = ms.proposed_canonical_id
            WHERE ms.project_id = $1::uuid AND ms.decision = 'needs_review'
            """,
            project_id,
        )
        return [{"id": r[0], "a": r[1], "b": r[2], "node_type": r[3], "conf": float(r[4] or 0)} for r in rows]
    finally:
        await conn.close()

async def _apply_class(project_id: str, cls: str) -> int:
    import asyncpg
    rows = await _load(project_id)
    ids = [r["id"] for r in rows
           if r["conf"] >= CONF_FLOOR and auto_clear_class(r["a"], r["b"], r["node_type"]) == cls]
    if not ids:
        return 0
    conn = await asyncpg.connect(os.environ["KG_DATABASE_URL"])
    try:
        await conn.execute(
            "UPDATE merge_suggestions SET decision='review_cleared' WHERE id = ANY($1::uuid[])", ids
        )
    finally:
        await conn.close()
    return len(ids)

def _sample(project_id: str, cls: str, out: str) -> None:
    rows = asyncio.run(_load(project_id))
    members = [r for r in rows
               if r["conf"] >= CONF_FLOOR and auto_clear_class(r["a"], r["b"], r["node_type"]) == cls]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "a", "b", "conf", "same_entity"])
        w.writeheader()
        for r in members:
            w.writerow({"id": r["id"], "a": r["a"], "b": r["b"], "conf": r["conf"], "same_entity": ""})
    print(f"class {cls}: {len(members)} members -> {out}. Label same_entity (1/0), then --score.")

def _score(path: str) -> None:
    labels = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row["same_entity"].strip() in ("0", "1"):
                labels.append(int(row["same_entity"]))
    n, s = len(labels), sum(labels)
    print(f"n={n} same={s} precision={s/n if n else 0:.3f} wilson_lcb={wilson_lcb(s, n):.3f}")

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--sample", metavar="CLASS")
    p.add_argument("--out", metavar="CSV")
    p.add_argument("--score", metavar="CSV")
    p.add_argument("--apply-class", metavar="CLASS")
    a = p.parse_args()
    if a.score:
        _score(a.score); return
    if a.sample:
        _sample(a.project, a.sample, a.out); return
    if a.apply_class:
        n = asyncio.run(_apply_class(a.project, a.apply_class))
        print(f"flipped {n} rows of class {a.apply_class} -> review_cleared"); return
    if a.dry_run:
        rep = class_report(asyncio.run(_load(a.project)))
        print(rep); return
    p.error("choose one of --dry-run/--sample/--score/--apply-class")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: run to verify pass** — `uv run pytest tests/resolution/test_danger_partition.py -q` → PASS.

- [ ] **Step 5: live dry-run smoke (read-only)** — with the docker stack up:

```bash
KG_DATABASE_URL="postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg" \
  uv run python -m ennam_kg.resolution.danger_partition_cli \
  --project 592c7ff7-9f6f-4cc5-9094-d9b3b685277e --dry-run
```
Expected: a dict like `{'R1': .., 'R2': .., 'R3': .., 'R4': .., 'L3': ..}` summing to 3148. No writes.

- [ ] **Step 6: commit**

```bash
git add src/ennam_kg/resolution/danger_partition_cli.py tests/resolution/test_danger_partition.py
git commit -m "feat(daab): danger-stratum partition CLI (classify/sample/score/apply-class)"
```

---

## Task 4: L3 review CLI (human batch-approve)

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/resolution/danger_review_cli.py`
- Test: `ennam.kg.python/tests/resolution/test_danger_review.py`

**Interfaces:**
- Produces: CLI `python -m ennam_kg.resolution.danger_review_cli --project <uuid>` — lists `needs_review` groups by `proposed_canonical_id` with both titles, descriptions, degree, conf; per group accept → `review_cleared`, reject → `rejected`. A pure helper `group_by_canonical(rows) -> dict[str, list[dict]]` is unit-tested.

- [ ] **Step 1: failing test** — create `tests/resolution/test_danger_review.py`:

```python
from ennam_kg.resolution.danger_review_cli import group_by_canonical

def test_group_by_canonical():
    rows = [
        {"id": "1", "canon": "c1", "a": "x", "b": "y"},
        {"id": "2", "canon": "c1", "a": "x", "b": "z"},
        {"id": "3", "canon": "c2", "a": "p", "b": "q"},
    ]
    g = group_by_canonical(rows)
    assert set(g.keys()) == {"c1", "c2"}
    assert len(g["c1"]) == 2
```

- [ ] **Step 2: run to verify fail** — `uv run pytest tests/resolution/test_danger_review.py -q` → FAIL.

- [ ] **Step 3: implement** — create `src/ennam_kg/resolution/danger_review_cli.py`:

```python
"""L3 human review CLI for the danger-stratum residual. Lists needs_review rows
grouped by proposed_canonical_id; a reviewer accepts (-> review_cleared, feeds the
existing applier) or rejects (-> rejected, recorded so Pass-2 does not re-suggest)."""
from __future__ import annotations
import argparse
import asyncio
import os

def group_by_canonical(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["canon"], []).append(r)
    return out

async def _load(project_id: str) -> list[dict]:
    import asyncpg
    conn = await asyncpg.connect(os.environ["KG_DATABASE_URL"])
    try:
        rows = await conn.fetch(
            """
            SELECT ms.id::text, ms.proposed_canonical_id::text AS canon,
                   na.title AS a, nb.title AS b, ms.reason, ms.merge_confidence AS conf,
                   (SELECT count(*) FROM knowledge_edges e
                      WHERE (e.source_id = ms.proposed_canonical_id
                             OR e.target_id = ms.proposed_canonical_id)
                        AND COALESCE(e.properties->>'superseded_by_merge','') = '') AS degree
            FROM merge_suggestions ms
            JOIN knowledge_nodes na ON na.id = ms.node_a_id
            JOIN knowledge_nodes nb ON nb.id = ms.node_b_id
            WHERE ms.project_id = $1::uuid AND ms.decision = 'needs_review'
            ORDER BY ms.proposed_canonical_id
            """,
            project_id,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()

async def _set_decision(ids: list[str], decision: str) -> None:
    import asyncpg
    conn = await asyncpg.connect(os.environ["KG_DATABASE_URL"])
    try:
        await conn.execute(
            "UPDATE merge_suggestions SET decision=$2 WHERE id = ANY($1::uuid[])", ids, decision
        )
    finally:
        await conn.close()

def _review(project_id: str) -> None:
    rows = asyncio.run(_load(project_id))
    groups = group_by_canonical(rows)
    for canon, members in groups.items():
        deg = members[0].get("degree", 0)
        print(f"\n=== canonical {canon} (degree {deg}, {len(members)} pairs) ===")
        for m in members:
            print(f"  [{m['conf']:.2f}] {m['a']!r} <-> {m['b']!r}  | {m['reason'][:60]}")
        ans = input("accept(a) / reject(r) / skip(s)? ").strip().lower()
        ids = [m["id"] for m in members]
        if ans == "a":
            asyncio.run(_set_decision(ids, "review_cleared")); print(f"  -> review_cleared ({len(ids)})")
        elif ans == "r":
            asyncio.run(_set_decision(ids, "rejected")); print(f"  -> rejected ({len(ids)})")
        else:
            print("  skipped")

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--project", required=True)
    a = p.parse_args()
    _review(a.project)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: run to verify pass** — `uv run pytest tests/resolution/test_danger_review.py -q` → PASS.

- [ ] **Step 5: commit**

```bash
git add src/ennam_kg/resolution/danger_review_cli.py tests/resolution/test_danger_review.py
git commit -m "feat(daab): danger-stratum L3 review CLI (batch-approve by canonical)"
```

---

## Task 5: Operational runbook + reject-dedup verification

**Files:**
- Create: `ennam.kg.python/docs/danger-stratum-runbook.md`
- Verify (no change unless gap found): Pass-2 resolver skips `decision='rejected'` pairs.

- [ ] **Step 1: verify reject dedup** — confirm the resolver does not re-create suggestions for already-`rejected` pairs on re-run:

```bash
cd ../ennam.kg.python && grep -rnE "decision|rejected|needs_review" src/ennam_kg/resolution/pass2*.py src/ennam_kg/resolution/*.py | grep -iE "rejected|WHERE|INSERT"
```
If suggestions are inserted without excluding existing `rejected` pairs, note it in the runbook as a required follow-up (a `NOT EXISTS (... decision='rejected')` guard on the insert). Do NOT change pass2 in this plan unless the gap blocks the drain.

- [ ] **Step 2: write runbook** — create `docs/danger-stratum-runbook.md`:

```markdown
# Danger-Stratum Drain Runbook

Order (project 592c7ff7-9f6f-4cc5-9094-d9b3b685277e; server :8082):

1. Dry-run partition — see per-class + L3 split:
   `KG_DATABASE_URL=... python -m ennam_kg.resolution.danger_partition_cli --project <id> --dry-run`
2. Per class R1/R2/R3 (construction-safe): review the ABBREV/COUNTRY tables in
   danger_rules.py (human sign-off), then `--sample <class> --out c.csv`, label ~30,
   `--score c.csv`. If spot-check clean -> `--apply-class <class>`.
3. Class R4 (empirical): `--sample R4 --out r4.csv`, human-label n>=150, `--score r4.csv`.
   Apply ONLY if wilson_lcb >= 0.97; else tighten R4 or leave to L3.
4. Drain flipped rows via the applier (auth-gated; temp KG_AUTH_NOOP=true or use a key):
   `curl -X POST http://localhost:8082/api/v1/internal/resolution/apply-review-cleared \
      -H "Authorization: Bearer <key>" -H "Content-Type: application/json" \
      -d '{"project_id":"<id>","dry_run":false}'`
   (dry_run:true first to preview the manifest; degree-ceiling defers hubs.)
5. L3 residual: `python -m ennam_kg.resolution.danger_review_cli --project <id>`.
6. Rollback if needed: merge_undo on the applied suggestion set (time-windowed).
```

- [ ] **Step 3: commit**

```bash
git add docs/danger-stratum-runbook.md
git commit -m "docs(daab): danger-stratum drain runbook + reject-dedup check"
```

---

## Success Criteria

- `passes_guards` blocks every documented FP class (number/role/scope/generic/admin-unit/OCR-concat) — Task 1 tests green, including `I479≠479` via digit-containing tokens.
- `auto_clear_class` returns a class only for guarded, non-concept rule matches — Task 2 tests green; R4 fenced to `location`; R4↔G5 boundary correct (bare↔unit passes, unit↔different-unit blocks).
- Dry-run partition sums to the live `needs_review` count; per-class flips route through the unchanged `ApplyReviewClearedMerges`.
- R1–R3 gated by dictionary sign-off + ~30 spot-check; R4 gated by `wilson_lcb ≥ 0.97` on ≥150 human labels (else L3).
- L3 CLI records rejects as `decision='rejected'`; reject-dedup on re-run verified (or logged as follow-up).
- No Go merge-code change; reversible via `merge_undo`.
