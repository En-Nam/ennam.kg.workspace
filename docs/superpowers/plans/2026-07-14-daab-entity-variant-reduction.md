# DAAB Entity-Variant Reduction (Plan B1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse OCR-induced entity name variants (e.g. the "Công ty TNHH Xây dựng Hàm Giang" investor split across ≥4 concept heads) into one canonical entity — restoring the shared-entity / related-documents / centrality signals — with **no OCR change, no re-ingest, no dependency, no resolution-precision regression**.

**Architecture:** Add a *fold* variant of the resolution name-normalizer (ASCII/tone-fold + Vietnamese legal-abbreviation canonicalization) used **only in candidate generation** (`emit_hub_candidates_cli`), so fold-equivalent variants become merge *suggestions* that DEFER to the existing LLM adjudicator + danger guards — recall up, precision held by the unchanged verifier. Then re-run resolution over the existing corpus. This is Plan **B1** of the OCR/entity spec; Plan **B2** (OCR figure fidelity: preprocessing, RapidOCR-vi, fallback) is a separate follow-up.

**Tech Stack:** Python 3.12 (`unicodedata`, `difflib` — stdlib only), pytest, PostgreSQL 16, the existing BA-031 resolution CLIs.

## Global Constraints

- **Do NOT change `_normalize()`'s default behavior.** Stage-1 auto-merge (`rule_based_decision`, 0.99 confidence, `rules.py`) MUST keep using the strict NFC form. Add folding as a **separate** function used only where stated. This is the precision firewall.
- **Folded grouping only produces `decision="suggested"` candidates** — they pass through the existing LLM adjudication (`fuzzy_llm_adjudicate`) + `name_class` generic-reject + `danger_guards`. No new auto-merge path.
- **No `resolution_sim_threshold` change** (0.74 stays). No new dependency (stdlib `unicodedata`/`difflib` only; no rapidfuzz).
- **Precision is the hard gate:** the BA-031 benchmark precision (`fuzzy_sample_cli.py`, Wilson LCB) must not regress, and an over-merge audit on resulting org clusters must be clean.
- **Fail-loud:** if the re-run merges an obviously-wrong pair, that's a stop-and-fix, not a warning.
- Python: `ruff`, type hints, pytest; run `uv run pytest` / `uv run ruff check`.

**Key files & symbols (verified):**
- `ennam.kg.python/src/ennam_kg/resolution/rules.py` — `_normalize(text)` (line 50: `NFC + lower + strip separators + strip honorifics`), `_SEP_RE`, `_HONORIFICS`, `rule_based_decision` (Stage-1 auto-merge — do not disturb).
- `ennam.kg.python/src/ennam_kg/resolution/emit_hub_candidates_cli.py` — `_load_specific_groups_async` groups active concept nodes (`merged_into=''`) by `_normalize(title)`, filters to `entity_name_classification.class='specific'`, emits N-1 pairwise `create_merge_suggestion` (`reason="exact-name hub merge candidate"`, `decision="suggested"`). `build_candidates`, `_pick_canonical`.
- `ennam.kg.python/src/ennam_kg/resolution/classify_corpus_cli.py` — scans concept nodes, groups by `_normalize(name)`, writes `entity_name_classification(normalized_name, class)`.
- `ennam.kg.python/src/ennam_kg/resolution/fuzzy_llm_adjudicate.py` — `run_fuzzy_llm_adjudication(degree_threshold=0.84)` (worker post-resolve LLM adjudication; the precision gate).
- `ennam.kg.python/src/ennam_kg/resolution/danger_guards.py` — uses `_normalize`; antonym / pre-post / digit-mismatch guards (leave on strict form).
- Cảng project id: `592c7ff7-9f6f-4cc5-9094-d9b3b685277e`. Baseline (verified): investor split ≥4 un-merged concept heads (`23489eac`, `d5df2759`, `4b92a031`, `3e8f353a`, …); variants incl. `CÔNG TY TNHH NAY DỰNG HÀM GIANG`, `Cong ty THNN XD Ham Giang`.

---

### Task 1: Folding normalizer — `fold_name()`

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/resolution/name_fold.py`
- Test: `ennam.kg.python/tests/resolution/test_name_fold.py`

**Interfaces:**
- Produces: `fold_name(text: str) -> str` — applies the existing `_normalize` then (a) ASCII/tone-fold (NFD → strip combining marks) and (b) Vietnamese legal-abbreviation canonicalization. Deterministic, stdlib-only.
- Consumes: `resolution.rules._normalize`.

- [ ] **Step 1: Write the failing tests**

Create `tests/resolution/test_name_fold.py`. These encode the intent: OCR variants of one company fold to one string, while genuinely different names do NOT collide.

```python
from ennam_kg.resolution.name_fold import fold_name


def test_diacritic_variants_fold_equal():
    # Lost tone marks (OCR) must fold to the same key.
    assert fold_name("Công ty TNHH Xây dựng Hàm Giang") == fold_name("Cong ty TNHH Xay dung Ham Giang")


def test_legal_abbreviation_canonicalized():
    # THNN (OCR of TNHH) and Cty/Công ty canonicalize.
    assert fold_name("Cong ty THNN XD Ham Giang") == fold_name("công ty tnhh xd ham giang")
    assert fold_name("Cty TNHH Xay Dung") == fold_name("cong ty tnhh xay dung")


def test_fold_is_idempotent():
    once = fold_name("Công ty TNHH Xây dựng Hàm Giang")
    assert fold_name(once) == once


def test_distinct_names_do_not_collide():
    # Different companies must NOT fold together (precision guard).
    assert fold_name("Công ty TNHH Xây dựng Hàm Giang") != fold_name("Công ty TNHH Xây dựng Trà Vinh")
    # A location vs the company (both contain "Hàm Giang") must not collide.
    assert fold_name("ấp Chợ, xã Hàm Giang") != fold_name("Công ty TNHH Xây dựng Hàm Giang")


def test_glyph_error_nay_vs_xay_NOT_bridged_by_fold_alone():
    # Documents the boundary: fold does NOT merge a real glyph substitution.
    # These stay distinct after fold; the fuzzy/LLM stage (Task 3 grouping + adjudication) bridges them.
    assert fold_name("Cong ty TNHH NAY DUNG Ham Giang") != fold_name("Cong ty TNHH XAY DUNG Ham Giang")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ennam.kg.python && uv run pytest tests/resolution/test_name_fold.py -v`
Expected: `ModuleNotFoundError: ennam_kg.resolution.name_fold`.

- [ ] **Step 3: Implement `fold_name`**

Create `name_fold.py`:

```python
"""Aggressive fold of a name for OCR-variant candidate grouping (Plan B1).

Built ON TOP of resolution.rules._normalize. Used ONLY for candidate generation
(emit_hub_candidates), never for Stage-1 auto-merge — folded matches are emitted as
`decision="suggested"` and pass through the LLM adjudicator, so recall rises without
weakening precision.
"""
from __future__ import annotations

import unicodedata

from ennam_kg.resolution.rules import _normalize

# Vietnamese legal / company abbreviation canonicalization (applied to the
# already-lowercased, ASCII-folded token stream). OCR frequently renders TNHH as
# THNN and drops "cong ty" to "cty".
_ABBREV = {
    "thnn": "tnhh",
    "cty": "cong ty",
    "c.ty": "cong ty",
    # extend as the corpus reveals more; keep deterministic and reversible-safe.
}


def _ascii_fold(text: str) -> str:
    """Strip Vietnamese tone/diacritic marks: NFD → drop combining → ASCII."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    # đ/Đ have no combining form; map explicitly.
    return stripped.replace("đ", "d").replace("Đ", "d")


def fold_name(text: str) -> str:
    base = _normalize(text)          # NFC + lower + collapse separators + strip honorifics
    folded = _ascii_fold(base)       # tone/diacritic fold
    tokens = [_ABBREV.get(t, t) for t in folded.split(" ") if t]
    # Re-apply abbrev on the joined form for multi-token keys like "c.ty" already split.
    return " ".join(tokens)
```

> Note: `_normalize` lowercases before this runs, so `_ABBREV` keys are lowercase. `đ→d` must run because NFD does not decompose đ.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.python && uv run pytest tests/resolution/test_name_fold.py -v`
Expected: PASS (all 5). Confirms fold merges diacritic/abbrev variants, keeps distinct names apart, and does NOT over-reach on the NAY/XÂY glyph case (that's Task 3's grouping + LLM job).

- [ ] **Step 5: Lint + commit**

```bash
cd ennam.kg.python
uv run ruff check src/ennam_kg/resolution/name_fold.py tests/resolution/test_name_fold.py
git add src/ennam_kg/resolution/name_fold.py tests/resolution/test_name_fold.py
git commit -m "feat(resolution): fold_name for OCR-variant candidate grouping (stdlib-only)"
```

---

### Task 2: Fold-based candidate grouping in `emit_hub_candidates_cli`

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/resolution/emit_hub_candidates_cli.py`
- Test: `ennam.kg.python/tests/resolution/test_emit_hub_candidates.py` (create or extend)

**Interfaces:**
- Consumes: `fold_name` (Task 1); existing `build_candidates`, `create_merge_suggestion` POST path.
- Produces: candidate groups keyed on `fold_name(title)` instead of `_normalize(title)`; genericness membership checked on the folded key. Output shape unchanged (`decision="suggested"`, `reason="exact-name hub merge candidate"`).

- [ ] **Step 1: Write the failing test**

`build_candidates` is pure and already testable. Add a test that the *grouping* now unifies fold-equivalent variants. Extract the grouping keying so it's unit-testable, or test `build_candidates` with a folded-group dict. Minimal: test a small helper `_group_key(title)` = `fold_name(title)`.

```python
from ennam_kg.resolution.emit_hub_candidates_cli import build_candidates, _group_key


def test_group_key_unifies_ocr_variants():
    assert _group_key("Công ty TNHH Xây dựng Hàm Giang") == _group_key("Cong ty THNN Xay dung Ham Giang")


def test_build_candidates_emits_n_minus_1_for_folded_group():
    # Three OCR variants of one company → one group → 2 pairwise candidates to the canonical.
    groups = {
        "cong ty tnhh xay dung ham giang": [
            ("id-a", 5, "2026-01-01"),   # highest degree → canonical
            ("id-b", 1, "2026-01-02"),
            ("id-c", 0, "2026-01-03"),
        ]
    }
    cands = build_candidates(groups)
    assert len(cands) == 2
    assert all(c.proposed_canonical_id == "id-a" for c in cands)
    assert {c.member_id for c in cands} == {"id-b", "id-c"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/resolution/test_emit_hub_candidates.py -v`
Expected: FAIL — `_group_key` not defined (and grouping still uses `_normalize`).

- [ ] **Step 3: Switch grouping to `fold_name`**

In `emit_hub_candidates_cli.py`:
- Add import + helper:
```python
from ennam_kg.resolution.name_fold import fold_name

def _group_key(title: str) -> str:
    """Grouping key for hub-merge candidate generation (folded for OCR variants)."""
    return fold_name(title)
```
- In `_load_specific_groups_async`, replace `nm = _normalize(row["title"])` with `nm = _group_key(row["title"])`, and fold the classification set so membership matches:
```python
        specific_set = {fold_name(row["normalized_name"]) for row in class_rows}
        ...
        nm = _group_key(row["title"])
        if nm not in specific_set:
            continue
```
> The classification table stores `_normalize`d names; folding both sides keeps the membership check consistent without re-classifying. (Task 4 re-runs `classify_corpus` anyway; folding here is robust to either.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/resolution/test_emit_hub_candidates.py -v`
Expected: PASS. Grouping now unifies OCR variants; output still `decision="suggested"` (precision preserved by the downstream adjudicator).

- [ ] **Step 5: Lint + commit**

```bash
cd ennam.kg.python
uv run ruff check src/ennam_kg/resolution/emit_hub_candidates_cli.py tests/resolution/test_emit_hub_candidates.py
git add src/ennam_kg/resolution/emit_hub_candidates_cli.py tests/resolution/test_emit_hub_candidates.py
git commit -m "feat(resolution): group hub-merge candidates by fold_name (OCR-variant recall)"
```

---

### Task 3: Fold-aware classification re-run consistency

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/resolution/classify_corpus_cli.py`
- Test: `ennam.kg.python/tests/resolution/test_classify_corpus.py` (extend if present; else a focused unit test)

**Interfaces:**
- Produces: `classify_corpus_cli` groups by `fold_name` so `entity_name_classification.normalized_name` keys align with the folded candidate grouping (Task 2), and a single "specific/generic" class covers all OCR variants of a name together.

- [ ] **Step 1: Write the failing test**

`classify_corpus_cli.py:41` does `nm = _normalize(raw)`. Test that grouping for classification now folds:

```python
from ennam_kg.resolution.classify_corpus_cli import _classification_key  # to be added


def test_classification_key_folds_variants():
    assert _classification_key("Công ty TNHH Xây dựng Hàm Giang") == _classification_key("Cong ty THNN Xay dung Ham Giang")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/resolution/test_classify_corpus.py -k classification_key -v`
Expected: FAIL — `_classification_key` not defined.

- [ ] **Step 3: Route classification grouping through the fold**

In `classify_corpus_cli.py`, add and use:
```python
from ennam_kg.resolution.name_fold import fold_name

def _classification_key(raw: str) -> str:
    return fold_name(raw)
```
Replace the `nm = _normalize(raw)` grouping call (line ~41) with `nm = _classification_key(raw)`. Leave any other `_normalize` usage in the file unchanged unless it is the same grouping key.

> Rationale: classification decides specific-vs-generic per *name*; folding makes all OCR variants of one name share one classification, so a variant isn't dropped from candidate emission for being unclassified.

- [ ] **Step 4: Run to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/resolution/test_classify_corpus.py -v`
Expected: PASS; existing classify tests still green.

- [ ] **Step 5: Lint + commit**

```bash
cd ennam.kg.python
uv run ruff check src/ennam_kg/resolution/classify_corpus_cli.py tests/resolution/test_classify_corpus.py
git add src/ennam_kg/resolution/classify_corpus_cli.py tests/resolution/test_classify_corpus.py
git commit -m "feat(resolution): fold classification keys to align with candidate grouping"
```

---

### Task 4: Measurement harness — entity-head-count + precision gate

**Files:**
- Create: `ennam.kg.python/scripts/b1_entity_metrics.py` (standalone measurement script; not production code)
- Create: `docs/superpowers/plans/b1-golden-set.md` (the hand-labeled golden set + runbook)

**Interfaces:**
- Produces: a repeatable measurement of (a) un-merged concept-head count for a target entity name, (b) a pass/fail vs the BA-031 benchmark precision, run before and after the resolution re-run.

- [ ] **Step 1: Write the golden set + head-count query**

Create `docs/superpowers/plans/b1-golden-set.md` listing the Hàm-Giang variant cluster (the ≥4 head ids + surface forms from the spec) and the target: **all variants → 1 canonical, others `merged_into` it**. Include the exact head-count SQL:

```sql
-- Un-merged concept heads whose folded name is the investor. Target: 1.
SELECT count(*) AS heads
FROM knowledge_nodes
WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e'
  AND node_type='concept'
  AND COALESCE(properties->>'merged_into','')=''
  AND lower(title) LIKE '%ham giang%'
  AND (lower(title) LIKE '%xay d%' OR lower(title) LIKE '%nay d%' OR lower(title) LIKE '%xd %' OR lower(title) LIKE '%tnhh%' OR lower(title) LIKE '%thnn%');
```
(Company variants only — exclude the `ấp/xã Hàm Giang` location by requiring a company token.)

- [ ] **Step 2: Write `b1_entity_metrics.py`**

A script that: (1) prints the head-count via the query above; (2) invokes the existing BA-031 precision sampler (`fuzzy_sample_cli.py`) or asserts its last run passed. It reads `KG_DATABASE_URL`. Keep it a thin measurement wrapper — no new logic.

- [ ] **Step 3: Capture the BEFORE baseline**

Run `b1_entity_metrics.py` against Cảng and record: heads (expect ≥4) and current BA-031 precision (the baseline to not regress). Save into `b1-golden-set.md`.

- [ ] **Step 4: Commit the harness**

```bash
cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace
git add ennam.kg.python/scripts/b1_entity_metrics.py docs/superpowers/plans/b1-golden-set.md
git commit -m "test(resolution): B1 entity-head-count + precision measurement harness"
```

---

### Task 5: Re-run resolution over Cảng + verify the fix

**Files:** none (operational; runbook in `b1-golden-set.md`).

**Interfaces:**
- Consumes: Tasks 1–3 deployed; Task 4 harness.
- Produces: Cảng investor collapsed to 1 head, BA-031 precision flat.

- [ ] **Step 1: Re-run the resolution candidate + adjudication pipeline**

Against Cảng (`KG_DATABASE_URL` + `KG_API_URL=:8082` + a valid key), in order:
1. `uv run python -m ennam_kg.resolution.classify_corpus_cli --project 592c7ff7-...` (re-classify with fold).
2. `uv run python -m ennam_kg.resolution.emit_hub_candidates_cli --project 592c7ff7-...` (emit folded-group suggestions).
3. Trigger `fuzzy_llm_adjudicate` for the project (the LLM precision gate) — via its CLI (`fuzzy_llm_adjudicate_cli.py`) or the worker path; adjudicated merges apply, borderline → `needs_review`.

Record counts (candidates emitted, merged, needs_review).

- [ ] **Step 2: Verify success criteria**

Run `b1_entity_metrics.py`. Expected (understand what each channel fixes):
- **Fold-grouping (Tasks 1–3) merges the diacritic/abbrev-EXACT variants** — the three `…xay dung ham giang` surface forms (differing only by tone marks / `THNN↔TNHH`) collapse to one. This alone takes the investor from ~5 heads to ~3.
- **Residual glyph/abbreviation variants** — `NAY DỰNG` (a real X→N glyph substitution, full-name distance ≈1) and `XD` (abbreviation of "xây dựng") — are NOT fold-equal; they merge via the **existing embedding-sim → cross-encoder → LLM adjudication channel** that the re-run exercises (the cross-encoder "understands missing separators/abbreviations" per `rules.py`), OR, if the adjudicator is unsure, they go to **`needs_review`**.
- **Target: head count → 1.** **Acceptable floor: heads substantially reduced AND every residual head is in `needs_review` (fail-loud), never silently left split.** A head that is neither merged nor in needs_review is a bug.
- **BA-031 precision: not regressed** vs the Task-4 baseline (hard gate).
- **Over-merge audit:** spot-check the merged cluster members are all genuinely the same company (no unrelated party absorbed, and the `ấp/xã Hàm Giang` *location* is NOT merged into the company). If any wrong merge, STOP — the fold/abbrev map or the adjudication over-reached; fix before proceeding.

> If reaching exactly 1 requires the LLM channel to bridge NAY/XD and it declines, that is the correct precision-safe outcome (needs_review), not a failure — a human confirms the last hop. Do not lower thresholds or force-merge to hit "1".

- [ ] **Step 3: Re-verify the downstream signal (optional, evidence)**

Query a `shared-entities`/`related` path for a doc mentioning the investor and confirm it now resolves through the single canonical entity (the relationship-layer signal Gap B targets).

- [ ] **Step 4: Checkpoint + backlog update**

Via `mcp__serena__write_memory("checkpoint/<agent>-2026-07-14", …)`: record before/after head-count, merged/needs_review counts, BA-031 precision. Update `mem:backlog/daab-retrieval-quality-gaps-postfix` noting the entity-fragmentation half of gap resolved; B2 (OCR figures) remains.

---

## Self-Review

**Spec coverage (B1 portion):** §4 #1 (normalization + re-run) → Tasks 1–3 (fold + grouping + classification) + Task 5 (re-run). §4 #0 (entity metrics + BA-031 gate) → Task 4. §8 success criterion 1 (Hàm Giang 4→1, precision flat) → Task 5 Step 2. Resource claim (resolution-only, no re-OCR) → Task 5 uses only classify/emit/adjudicate CLIs. **B2 scope (OCR #2/#4/#3, figure metrics) is explicitly a separate plan — not covered here.**

**Placeholder scan:** No TBDs. The `_ABBREV` map is seeded with the observed cases and marked "extend as the corpus reveals more" — a deliberate data-driven extension point, not a deferral (the seeded entries fix the verified Hàm-Giang case).

**Precision firewall (consistency):** `_normalize` default is never changed (Global Constraints; Task 1 builds a separate `fold_name`); folding appears only in candidate/classification grouping (Tasks 2–3), which emit `decision="suggested"` → LLM-adjudicated. `test_glyph_error_nay_vs_xay_NOT_bridged_by_fold_alone` (Task 1) + `test_distinct_names_do_not_collide` encode that fold doesn't over-merge; Task 5 Step 2 over-merge audit + BA-031 gate are the runtime precision checks.

**What each channel actually merges (honest accounting):** fold-grouping (Tasks 1–3) merges only the *diacritic + abbrev-EXACT* variants (the `xay dung` forms differing by tone marks / `THNN↔TNHH`) — it does NOT bridge the `NAY DỰNG` glyph error or the `XD` abbreviation (fold_name keeps those distinct, by design and by test). Those residuals rely on the **pre-existing** embedding-sim → cross-encoder → LLM channel, exercised by the Task-5 re-run, with `needs_review` as the fail-loud floor (Task 5 Step 2). So `difflib`/rapidfuzz are correctly unnecessary — not because fold bridges the glyph case, but because the existing verifier channel already covers the near-identical residual and adding a new fuzzy metric would only duplicate it. The head-count target is 1; the *guaranteed* deliverable is "diacritic/abbrev variants merged + all residuals either merged or in needs_review, precision flat."

**Type consistency:** `fold_name(text:str)->str` identical across Task 1 def and Tasks 2–3 callers. `_group_key`/`_classification_key` are thin `fold_name` wrappers. `build_candidates` signature unchanged.
