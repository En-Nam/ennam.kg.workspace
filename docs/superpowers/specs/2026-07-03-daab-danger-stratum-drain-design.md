# DAAB Danger-Stratum Drain — Design Spec

**Date:** 2026-07-03
**Status:** Draft (for review)
**Depends on:** `2026-07-01-daab-fuzzy-hub-merge-design.md` (review_cleared state + `ApplyReviewClearedMerges` applier), Plan B fuzzy alias merge (`is_danger_pair`, `wilson_lcb`, `fuzzy_sample_cli`).

## 1. Problem

After the fuzzy-hub drain, project `592c7ff7-9f6f-4cc5-9094-d9b3b685277e` has **3148** `merge_suggestions` rows in `decision='needs_review'` (the "danger stratum"). These are pairs the Pass-2 LLM verdicted `same_entity`, but whose **de-diacritic base forms differ** (so the deterministic typo gate did NOT auto-clear them).

**Critical framing — selection bias.** This set is precisely the *residual the deterministic gate could not clear*. It is enriched for the LLM's blind spots. Therefore:
- Observed false-positives exist across the whole confidence range — at conf 0.75 (`Tổng giám đốc` ↔ `Giám đốc`, `thửa đất số I479` ↔ `số 479`) **and** at conf 0.99–1.0 (`Trà Vinh` ↔ `tỉnh Trà Vinh`, OCR-concatenated headers).
- `merge_confidence` is **not monotone in correctness** on this distribution. It is a **queue-prioritization** signal, **never a standalone apply gate**.

### 1.1 Observed composition (evidence)

| Signal | Value |
|--------|-------|
| confidence | [0.9,1.0) 2438 · =1.0 4 (⇒ ≥0.9 total 2442) · [0.8,0.9) 593 · [0.7,0.8) 113 (⇒ <0.9 total 706) |
| node_type (canonical) | organization 1593 · location 537 · concept 413 · artifact 313 · person 222 · event 70 |

Legit variants (should merge): abbreviation (`Bộ GTVT`↔`Bộ Giao thông vận tải`), parenthetical (`Bộ Xây dựng (XD)`↔`Bộ Xây dựng`), closed cross-language (`Việt Nam`↔`Vietnam`), OCR diacritic-only-in-base (`UBND thj xã Duyên Hâi`↔`UBND thị xã Duyên Hải`).
False positives (must NOT merge): different number (`I479`↔`479`), role (`Tổng giám đốc`↔`Giám đốc`), scope (`Kiểm soát viên của công ty mẹ`↔`Kiểm soát viên`), governing body (`Chủ tịch Hội đồng`↔`Chủ tịch Hội đồng thành viên`), generic drift (`doanh nghiệp`↔`công ty`), admin-unit ambiguity (`Trà Vinh` province/city/river).

## 2. Risk posture — Hybrid, safety-lead

**Every auto-drained row MUST belong to a named rule class, pass ALL guards (conjunctive), AND its class must clear an empirical per-class precision gate (Wilson LCB ≥ 0.99).** Confidence ≥ 0.9 is a *necessary-not-sufficient* filter within a class, never a class by itself. The auto-vs-human split is **data-decided** by the Wilson gate, not fixed by fiat.

Rationale for the ruling (over the aggressive "auto-apply conf≥0.9" alternative): the selection-bias argument above + documented high-confidence false-positives. Cost asymmetry favors under-merge: an un-merged duplicate is a **visible, recoverable omission**; a false merge is **silent latent corruption** — re-pointed edges contaminate retrieval, and undo-after-downstream-consumption is messy (Step-2 self-heals from the re-pointed graph, but embedding consumers — `kg_recall` semantic, BA-033 retriever — would need re-embed).

## 3. Architecture

```
Python partition CLI (danger_partition_cli.py)          Go applier (UNCHANGED)
  per row: de_diacritic_base + rule classifier   ─┐
           + guards G1–G6 (conjunctive)            │  flip class → decision='review_cleared'
  per class: emit sample → human label → wilson    ├──────────────────────────►  ApplyReviewClearedMerges
           GA gate: LCB≥0.99 → flip class          │     (degree ceiling + merge_undo, batch-tagged)
  fail guard / fail Wilson / concept / conf<0.9 ───┘  → stays needs_review → review CLI (human)
```

**Key invariant:** all rule + guard + Wilson logic lives in the **Python partition step**. The Go applier stays class-agnostic — it drains whatever is `review_cleared`. This reuses `ApplyReviewClearedMerges` **with no Go merge-code change** (mirrors the fuzzy-hub design). The applier's degree-ceiling still defers hubs.

### 3.1 Rule classes (L1) — each Wilson-gated independently

Applied on top of the existing `de_diacritic_base()`. A row is a class member only if both sides collapse to an identical normalized key under that class's transform.

- **R1 — Parenthetical strip, exact remainder.** Strip trailing `(...)`; member iff remainder is de-diacritic-EQUAL to the other side. (`Bộ Xây dựng (XD)` ↔ `Bộ Xây dựng`)
- **R2 — Curated abbreviation whitelist, governing tokens identical.** Closed, human-signed table (`GTVT→Giao thông vận tải`, `UBND→Ủy ban nhân dân`, `XD→Xây dựng`, ministry/agency set). Member iff every non-abbreviated token is identical and the differing token is a whitelist hit. **NOT** open acronym-initial matching. (`Bộ GTVT` ↔ `Bộ Giao thông vận tải`) — reuses/extends B's `is_danger_pair` GTVT handling.
- **R3 — Closed cross-language proper nouns, location/country only.** ~20-entry country map. (`Việt Nam` ↔ `Vietnam`) Nothing open-ended.
- **R4 — Admin-prefix strip, `location` type only.** Strip a leading admin/geo unit from the `{tỉnh, thành phố, TP, thị xã, huyện, quận, phường, xã}` set; member iff exactly ONE side carries such a unit and the bare remainder is de-diacritic-EQUAL. (`Trà Vinh` ↔ `tỉnh Trà Vinh`) **This is the highest-risk class** (bare token could be province/city/river); it is NOT decided by argument — the Wilson gate decides. If R4's sampled LCB < 0.99, the entire class routes to L3.

Concept nodes (413) are **excluded from all rule classes** — generics offer low merge value and high semantic-drift risk. All concept → L3.

### 3.2 Guards G1–G6 — conjunctive, block even at conf = 1.0

Applied AFTER rule normalization; a candidate auto-merges only if it passes ALL guards.

- **G1 — Number/identifier equality.** Multiset of numeric + alphanumeric-code tokens (`479`, `I479`, `K8`, `2016`) must match literally (do NOT fold I/1/l). Differ → block. (`I479` ≠ `479`; `K8` = `K8` ok)
- **G2 — Seniority/role modifier.** Whitelisted modifiers `{Tổng, Phó, Trưởng, …}`: one side carries a modifier the other lacks → block. (`Tổng giám đốc` ≠ `Giám đốc`)
- **G3 — Scope/governing-body suffix.** Residual trailing qualifier differs → block. (`Chủ tịch Hội đồng` ≠ `Chủ tịch Hội đồng thành viên`; `Kiểm soát viên` ≠ `… của công ty mẹ`)
- **G4 — Bare-generic.** Either side normalizes to a generic common noun with no proper specifier → block. (`doanh nghiệp` ≠ `công ty`)
- **G5 — Admin-unit-class mismatch.** BOTH sides carry an admin/geo unit word but **different** ones (`sông Trà Vinh` ≠ `tỉnh Trà Vinh`) → block. **Scope note:** G5 does NOT block the R4 case (one side bare, other has a unit); R4 is the controlled, Wilson-gated exception. G5 only fires on *conflicting* units.
- **G6 — OCR-concatenation / containment-plus-extra.** Longer side contains the other as a substring PLUS extra content tokens beyond whitelisted noise → block. (`BỘ GIAO THÔNG… CỘNG HÒA XÃ HỘI…` ≠ `Bộ Giao thông Vận tải`)

### 3.3 GA gate — two kinds, matched to how a class earns safety

**Do NOT apply a blanket Wilson LCB ≥ 0.99 to every class.** Wilson's lower bound at 100% observed precision is ≈ `n/(n+z²)`; certifying LCB ≥ 0.99 needs ≈ 380 labels (z=1.96) *even when every label is correct*. Small provable classes (R3 ≈ 15 countries → LCB ≈ 0.80) can therefore **never** pass a 0.99 statistical gate, and certifying a class by labeling ~380 rows is often more work than just reviewing it. So the gate is split by how the class earns its safety:

**Construction-safe classes — R1, R2, R3** (safety is by construction, not statistics):
1. One-time **human sign-off of the rule + its dictionary** (R2 abbreviation whitelist, R3 country map) — the closed table is the proof.
2. A **small spot-check** (~30 post-guard members per class): if any is wrong, the rule/dictionary is broken → fix it, don't ship the class.
3. On clean spot-check → flip the class to `review_cleared`. No large sample needed — the parenthetical/whitelist/closed-map transforms are meaning-preserving by definition.

**Empirically-gated class — R4** (admin-prefix strip is NOT provable; bare token may be province/city/river):
1. CLI emits a stratified human-label sample of R4's post-guard members (target n ≈ 150).
2. Human labels each same/different; compute `wilson_lcb(precision)` (reuse Plan B `wilson_lcb`).
3. **GA iff LCB ≥ 0.97** (drainer/CTO midpoint; n≈150 reaches it near 100% observed). If R4 is too small to reach the target, or precision < target → tighten R4's predicate or route the whole class to L3.

Confidence ≥ 0.9 is required as a within-class filter (necessary, not sufficient) for all classes. Human labels — not `is_danger_pair` — drive the R4 gate; `is_danger_pair`'s deterministic sub-checks (e.g. number cardinality) are reused *as guards* (§3.2), but its overall heuristic verdict is never the labeler.

### 3.4 Layer 3 — human review (union)

Routed to L3 = union of: all concept (413) ∪ all conf < 0.9 (706) ∪ any guard-fail ∪ any Wilson-fail class ∪ the 4 exactly-1.0 pairs (eyeballed individually; 1.0 is not a pass).

**Surface = CLI batch-approve grouped by `proposed_canonical_id` + rule-pattern** (not a UI). Shows: both surface forms, both node descriptions, degree of each, edge-type summary, token-level diff, `merge_confidence` + `embedding_similarity`, and which guard/class flagged it. Approve → `decision='review_cleared'` (feeds the applier); reject → `decision='rejected'`. Build a UI only if reviewers ask.

### 3.5 Reversibility / audit

Bulk-undo is available without schema change: a class flip is a bounded set of suggestion IDs applied in one run, so an audit can `merge_undo` exactly that set (query merges by the applied suggestion IDs / time window). A `batch_id` column is an optional convenience, not a requirement. The applier's degree ceiling caps single-merge blast radius. **Requirement:** the Pass-2 resolver must skip pairs already `decision='rejected'` on re-run, else human reject work is lost on the next corpus re-index (verify current behavior; add dedup if missing).

## 4. Components / interfaces

| Unit | Responsibility | Reuses |
|------|----------------|--------|
| `danger_partition_cli.py` | classify rows → R1–R4, run guards, emit per-class samples, compute Wilson, flip passing classes to `review_cleared` | `de_diacritic_base`, `is_danger_pair`, `wilson_lcb`, asyncpg |
| `danger_review_cli.py` | L3 batch-approve grouped by canonical; approve→review_cleared, reject→rejected | node/description/degree reads |
| abbreviation whitelist | closed human-signed table (data file, versioned) | — |
| `ApplyReviewClearedMerges` (Go) | drain `review_cleared`, degree ceiling, batch-tag | **unchanged** (or minimal: accept a `batch_id`) |

## 5. Testing

- Unit (pytest): each rule class R1–R4 (positive + near-miss negative); each guard G1–G6 on its documented FP pair AND a true-positive that must pass; the R4↔G5 boundary (bare↔unit passes R4; unit↔different-unit blocked by G5).
- `wilson_lcb` gate arithmetic (already covered in B; add class-partition test).
- Integration: dry-run partition prints per-class counts + guard-block counts; a flip of a synthetic passing class → `ApplyReviewClearedMerges` applies it; a rejected row is not re-suggested.

## 6. Success criteria

- Zero merges of the documented FP classes (numbers/roles/scope/admin-unit/generic) — enforced by guards + tests.
- Each auto-drained class earned safety per §3.3: R1–R3 via signed dictionary + clean ~30-row spot-check; R4 via Wilson LCB ≥ 0.97 on a human-labeled sample (else routed to L3).
- Residual (concept + conf<0.9 + guard/Wilson fails) routed to a working L3 CLI; rejects recorded and not re-suggested.
- No Go merge-code change; drain flows through `ApplyReviewClearedMerges`; reversible via `merge_undo` + `batch_id`.

## 7. Out of scope

- Re-running Pass-2 / re-embedding (orchestrated separately).
- A web review UI (CLI first; UI only on demand).
- The 1 fuzzy-hub hub deferred by the degree ceiling (separate item).
