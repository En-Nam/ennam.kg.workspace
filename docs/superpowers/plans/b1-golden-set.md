# B1 Golden Set — Hàm-Giang Entity-Variant Cluster

Source: `2026-07-14-daab-entity-variant-reduction.md`, Task 4. Hand-labeled
golden set + runbook for the entity-head-count and BA-031 precision
measurement harness (`ennam.kg.python/scripts/b1_entity_metrics.py`).

## Target entity

**Company:** "Công ty TNHH Xây dựng Hàm Giang" (the Hàm-Giang investor).

**Project:** Cảng — `project_id = 592c7ff7-9f6f-4cc5-9094-d9b3b685277e`.

## Known variant cluster (baseline, verified pre-fix)

Un-merged concept heads, `>= 4` (spec-verified head-id prefixes):
`23489eac`, `d5df2759`, `4b92a031`, `3e8f353a`, and possibly more — the exact
count is what the head-count SQL below measures.

Known surface forms among those heads (spec-verified):
- `CÔNG TY TNHH NAY DỰNG HÀM GIANG`
- `Cong ty THNN XD Ham Giang`
- `Công ty TNHH Xây dựng Hàm Giang` / `Cong ty TNHH Xay dung Ham Giang`
  (the fold-equal diacritic/case variants of the canonical name)

Head ids and surface forms per
`docs/superpowers/plans/2026-07-14-daab-entity-variant-reduction.md` line 26.
This is not an exhaustive enumeration — the head-id/surface-form pairing is
not disambiguated in the source spec beyond this list; the head-count SQL is
the authoritative measurement, not this table. Variant differences are
OCR/diacritic/abbreviation noise, not distinct entities:
- Tone-mark loss: `Xây` ↔ `Xay`, `Hàm` ↔ `Ham`.
- Company-type abbreviation: `TNHH` ↔ `THNN` (glyph-swapped).
- Word abbreviation: `Xây dựng` → `XD`.
- Glyph substitution: `Xây` → `Nay` (X→N misread; `XÂY DỰNG` → `NAY DỰNG`).

A separate `ấp/xã Hàm Giang` **location** node also matches `%ham giang%` but
has no company token (no `tnhh`/`thnn`/`xay d`/`nay d`/`xd `) — the SQL below
excludes it deliberately. It must **never** be merged into the company.

## Target (success criterion)

All company variants → **1** canonical concept-head node; every other
variant has `properties->>'merged_into'` pointing at that canonical node
(or, for residual glyph/abbreviation variants the LLM adjudicator declines
to merge, `decision='needs_review'` — fail-loud, not silently left split).

## Head-count SQL (verbatim — do not modify)

```sql
-- Un-merged concept heads whose folded name is the investor. Target: 1.
-- CRITICAL: unaccent() is required — lower('Hàm Giang')='hàm giang' does NOT match
-- '%ham giang%' (Vietnamese diacritics survive lower()). The unaccent extension is
-- installed (verified). Without it, all diacritic "Hàm"/"Xây" variants are missed.
SELECT count(*) AS heads
FROM knowledge_nodes
WHERE project_id='592c7ff7-9f6f-4cc5-9094-d9b3b685277e'
  AND node_type='concept'
  AND COALESCE(properties->>'merged_into','')=''
  AND unaccent(lower(title)) LIKE '%ham giang%'
  AND (unaccent(lower(title)) LIKE '%xay d%'
       OR unaccent(lower(title)) LIKE '%nay d%'
       OR unaccent(lower(title)) LIKE '%xd %'
       OR unaccent(lower(title)) LIKE '%tnhh%'
       OR unaccent(lower(title)) LIKE '%thnn%');
```

(Company variants only — the trailing company-token clause excludes the
`ấp/xã Hàm Giang` *location* node, which has no company token.)

This exact query is embedded in `scripts/b1_entity_metrics.py`
(`HEAD_COUNT_SQL`).

## BA-031 precision gate

The harness does not reimplement precision scoring — it delegates to the
existing `ennam_kg.resolution.fuzzy_sample_cli` sampler:

1. `uv run python -m ennam_kg.resolution.fuzzy_sample_cli --project 592c7ff7-9f6f-4cc5-9094-d9b3b685277e --draw <out.csv>`
   — draws a random + targeted (danger) stratum from the `suggested` merge
   band, writes `<out.csv>` with a blank `same_entity` column.
2. Hand-label the `same_entity` column (`1`=same entity, `0`=different) for
   each row.
3. `uv run python -m ennam_kg.resolution.fuzzy_sample_cli --project 592c7ff7-9f6f-4cc5-9094-d9b3b685277e --score <out.csv>`
   — or pass the labeled CSV to `b1_entity_metrics.py --adjudicated-csv
   <out.csv>`, which invokes the same `_score` gate. Thresholds: random
   stratum Wilson-LCB >= 0.95, targeted (danger) stratum Wilson-LCB >= 0.90.

## Runbook

```bash
cd ennam.kg.python

# 1. Head count only:
uv run python scripts/b1_entity_metrics.py --project 592c7ff7-9f6f-4cc5-9094-d9b3b685277e

# 2. Head count + BA-031 precision gate (after drawing/labeling a sample):
uv run python scripts/b1_entity_metrics.py \
  --project 592c7ff7-9f6f-4cc5-9094-d9b3b685277e \
  --adjudicated-csv <path-to-adjudicated.csv>
```

Requires `KG_DATABASE_URL` in the environment (same as
`classify_corpus_cli.py` / `emit_hub_candidates_cli.py` / `fuzzy_sample_cli.py`).

## BEFORE / AFTER baseline

**BEFORE (Task 4 Step 3 — NOT YET CAPTURED):**

- heads: _(pending — requires a live run against Cảng; not performed by this
  task; do not fabricate)_
- BA-031 precision (random / targeted): _(pending — same as above)_

> Live baseline capture against Cảng is **Task 5's responsibility** (this
> harness-writing task, Task 4, does not have — and per its brief must not
> use — live database access). Task 5 must run the runbook above, record the
> BEFORE numbers here (or in its own checkpoint referencing this file)
> *before* re-running the resolution pipeline, then the AFTER numbers once
> re-run, and confirm: heads trending toward 1 (or all residuals in
> `needs_review`), BA-031 precision not regressed vs. the BEFORE baseline.

**AFTER (Task 5 Step 2 — NOT YET CAPTURED):**

- heads: _(pending)_
- BA-031 precision (random / targeted): _(pending)_
- Over-merge audit (location node NOT absorbed; all merged members
  genuinely the same company): _(pending)_
