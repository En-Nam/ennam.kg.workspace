# DAAB Fuzzy HUB Merge (review_cleared) — Design

**Date:** 2026-07-01
**Status:** APPROVED (design) — ready for implementation plan
**Scope:** DAAB (`ennam.kg.go` + a small Python partition step) — drain the parked fuzzy HUB merge backlog (`decision='needs_review'`) safely, via a reviewed state-machine + a stricter sibling applier.
**Parent direction:** the last tier of entity-alias consolidation after 1a/1b/B. B merged fuzzy LEAF pairs; the fuzzy HUBS (blocked by the degree gate) sit in `needs_review` — the biggest-value aliases ("UBND tỉnh Trà Vinh" variants), whose consolidation most improves Step-2 related-documents.
**Related:** `mem:backlog/daab-fuzzy-alias-merge-B`, `mem:ba031-resolution-thresholds-gates`, the B spec `2026-06-30-daab-fuzzy-alias-merge-design.md`, Step-2 spec `2026-06-30-daab-related-documents-design.md`.

---

## 1. Problem

B's gated `Apply` merged fuzzy LEAF pairs but routed **4044 fuzzy suggestions to `decision='needs_review'`** because their LIVE degree ≥ threshold (hub safety, NFR-256: hubs are NEVER auto-merged). These are the highest-value aliases (the 62-doc "UBND tỉnh Trà Vinh" hub still has ~10 unmerged variants), so consolidating them most improves cross-document linking / Step-2 relatedness.

But a false HUB merge is the **maximum-blast event** on the shared graph (it unions two high-degree entities → many documents falsely linked, corrupting AAA Master Record / LAAM recall / Step-2 IDF). The degree gate exists precisely to stop *auto*-merging fuzzy hubs. So draining the queue requires a mechanism that satisfies NFR-256 (a **reviewed** merge, not a bypass on spent confidence) — the crux both reviewers converged on.

**The confidence is already spent.** These rows were CE+LLM-verified `same_entity` (avg conf 0.95), then routed to `needs_review` on **degree, not doubt**. Re-applying on that same confidence adds zero new safety signal. So the applier needs an **independent** clearance signal.

## 2. Goals / Non-goals

**Goals**
- Drain the 4044 `needs_review` fuzzy-hub rows safely: auto-clear the obvious OCR/diacritic-typo majority via a deterministic check; route only the bounded danger stratum to per-canonical human review; apply cleared rows via a reviewed bypass applier.
- Reversible, with a manifest capturing `mergeOpID`s for one-command batch un-merge.
- Orchestrate the Step-2 / embedding recompute before consumers read.

**Non-goals (deferred — see §12)**
- Moving rows back to `'suggested'` (re-enters the leaf gate → infinite loop; NFR-256-forbidden).
- A bespoke review UI (the dry-run manifest IS the review artifact).
- Re-running BA-031 Pass-2 / a new ML stage (verdicts already exist; the gate is deterministic + human, not a re-classify).
- Porting the discriminator into Go (the partition is Python where `_normalize` lives; Go drains a decision value).
- Wiring fuzzy-hub auto-apply into the live ingestion pipeline (this is a one-time, reviewed, manual drain).

## 3. Established decisions (from 2-agent review — converged)

| # | Decision | Basis |
|---|----------|-------|
| D1 | **A reviewed bypass applier, NOT a re-route to `'suggested'`.** New `ApplyReviewClearedMerges` clones `ApplyHubNameMerges` (bypass + dry-run manifest + per-canonical grouping), sourcing `decision='review_cleared'`. | `Apply` recomputes LIVE degree and routes hubs straight back to `needs_review` (`apply_suggestions.go:259`) — moving to `'suggested'` is an infinite loop. The `bypassDegreeGate` path is reachable only via a dedicated applier. |
| D2 | **Add a `'review_cleared'` decision value** (3-value clearance: `needs_review` → `review_cleared` → drained to `applied`). | A clean state machine reusing `UpdateDecision`/`ListByProject`. Requires a migration (the `decision` CHECK is a closed vocab). |
| D3 | **Discriminator = deterministic de-diacritic base-form EQUALITY** (independent of the spent LLM confidence — Rule 5). de-diacritic-equal → typo (auto-clear); differ → danger (human). | NFR-256 needs an *independent* signal to replace exact-name determinism. `is_danger_pair` (B) KEEPS diacritics → it would over-flag "Hàm"↔"Hâm" as danger — WRONG for this typo-dominated population. De-diacritic equality is the correct auto-clear gate. |
| D4 | **Auto-clear = (de-diacritic-equal) AND (live degree < a max-blast ceiling).** typo-only above the ceiling → human review anyway. | Vietnamese diacritics are semantic (Trà/Trả/Trá are different words), so de-diacritic equality is strong-but-not-perfect; at maximum blast radius, require a human even for a "typo." |
| D5 | **Per-canonical human review (1915 groups), only the danger stratum.** The dry-run manifest (`byCanon` → `HubMergeManifest{CanonicalID, MemberIDs}`) IS the review artifact. | Humans answer "do all members belong to this entity?" once per canonical, only for the bounded danger subset — not 4044 pairs. |
| D6 | **Precision gate: reuse `fuzzy_sample_cli.py` retargeted to the hub population, with a STRICTER LCB.** | Blast radius scales with degree → hubs warrant a higher lower-confidence bound than B's leaf gate, measured on the real population. |
| D7 | **Reversibility as backstop + orchestrated re-embed.** Capture `mergeOpID`s in the manifest; verify un-merge on a sample. The apply path sets no `re_embed_pending` yet `canonical_name` can change → recompute embeddings + Step-2 before consumers read. | `merge.go` is byte-reversible per `merge_op_id`; but `apply_suggestions.go:270-277` calls `Merge` with no `MergedDescription`, and `merge.go` only flags `re_embed_pending` on a re-summary — so the recompute is a **separate orchestrated step**. |

## 4. Current-state facts (verified on :5433 / in code, 2026-07-01)

- **Backlog:** `merge_suggestions WHERE decision='needs_review' AND reason<>'exact normalized name match'` = **4044 rows / 1915 distinct `proposed_canonical_id` groups**, avg conf 0.95, avg sim 0.94, min sim 0.86. Same trusted BA-031 Pass-2 (CE bge + LLM) as B's leaf band.
- **Typo-dominated:** the population is mostly OCR/diacritic-typo variants of the SAME entity: "Công ty TNHH Xây dựng **Hàm** Giang" ↔ "…**Hâm** Giang" (à→â), "Ban Quản **lý** KKT Trà Vinh" ↔ "…**lỷ**…" / "…Trà Vinh" ↔ "…**Trả** Vinh", "…Xây dựng" ↔ OCR-garble "Xay d\lllg". Low false-merge risk; blocked purely for high degree. The danger (genuinely distinct high-degree entities) is a low-frequency, max-blast residual.
- **`degree_max` stored 0** (shadow default) — the applier recomputes LIVE degree per canonical (`ApplyHubNameMerges` does this at `apply_suggestions.go:164-170`).
- **Applier to clone:** `ApplyHubNameMerges(ctx, projectID, dryRun) (ApplyResult, HubMergeManifest, error)` (`apply_suggestions.go:140`) — reason-scoped list → `byCanon` grouping → live degree per canonical → dry-run manifest → `processSuggestion(..., bypassDegreeGate=true)` (`:199`, gate at `:259`). `HubMergeManifest{CanonicalID, MemberIDs, DegreeMax}` (`:133`). `ListByProject(projectID, decision, limit, offset)` (`merge_suggestion.go:68`).
- **No `needs_review` applier** exists; nothing drains that decision.
- **`decision` CHECK:** `000064_merge_suggestions.up.sql:13` `CHECK (decision IN ('suggested','applied','rejected','needs_review'))` — a closed vocab; adding `'review_cleared'` needs a migration (DROP + re-ADD the constraint). Migration head is `000074` → new pair `000075`. There is a `(project_id, decision)` index (drain query is indexed).
- **Discriminator base:** `ennam.kg.python/.../resolution/rules.py::_normalize` (NFC + lowercase + collapse-sep + strip-honorific, KEEPS diacritics) — extend with combining-mark stripping for the de-diacritic base form. `is_danger_pair` (B, `fuzzy_sample_cli.py`) is reused ONLY for the precision sampler's stratification, NOT the auto-clear gate.
- **Merge re-points edges** (`merge.go`) → a fuzzy-hub merge IMPROVES Step-2 (canonical accretes the aliases' document mentions); un-merge restores byte-equivalent.

## 5. Architecture

```
Python partition step (reuse _normalize + a new de_diacritic_base):
  for each needs_review fuzzy row (reason ≠ exact-name):
     de_diacritic_base(name_a) == de_diacritic_base(name_b)  → 'review_cleared'  (typo, auto)
     else                                                    → stays 'needs_review' (danger)
  (degree ceiling for typo rows is enforced in the Go applier — Python has no live degree)

Human review (per-canonical, danger stratum only):
  read the dry-run manifest (byCanon groups) → confirm "all members belong to this entity?"
  approved group's rows → 'review_cleared'

Precision gate (before the first non-dry-run drain):
  fuzzy_sample_cli.py retargeted to the hub population, STRICTER LCB → PASS/FAIL

Go: ApplyReviewClearedMerges(ctx, projectID, dryRun)  (stricter sibling of ApplyHubNameMerges)
  list ListByProject(projectID, 'review_cleared', …), group byCanon, recompute LIVE degree per canonical
  if degree ≥ max-blast ceiling → route back to needs_review (requires explicit human), NOT auto
  dryRun → manifest (CanonicalID, MemberIDs, DegreeMax, + mergeOpIDs on apply)
  apply → processSuggestion(..., bypassDegreeGate=true) → merged; suggestion → 'applied'

Post-apply orchestration:
  flag re_embed for every applied fuzzy-hub canonical → worker re-embeds →
  recompute Step-2 related-documents (query-time; warm/verify) BEFORE AAA/LAAM read.
```

Net new code: one migration, a Python partition step (reuse `_normalize` + a `de_diacritic_base`), one Go applier method (clone of `ApplyHubNameMerges`) + handler route, and a decision param on the sampler's loader. Everything else reuses shipped, tested paths.

## 6. The discriminator (auto-clear gate)

**`de_diacritic_base(name)`** = `_normalize(name)` (NFC + lowercase + collapse-sep + strip-honorific) then **strip Unicode combining marks** (NFD → drop `Mn` category → recompose) **AND explicitly map `đ→d`** (and `Đ→D`). The `đ`/`Đ` step is REQUIRED and separate: `đ` (U+0111) is a distinct base letter, NOT `d`+combining, so NFD alone does NOT fold it — verified. Without it, an `đ↔d` OCR typo ("Định An" ↔ "Dinh An") would over-route to human review instead of auto-clearing. Two names **auto-clear** iff `de_diacritic_base(a) == de_diacritic_base(b)`.

- "Hàm Giang"/"Hâm Giang" → "ham giang" == "ham giang" → **auto-clear** (typo).
- "Ban Quản lý…"/"Ban Quản lỷ…" → "…ly…" == "…ly…" → **auto-clear**.
- "Xây dựng"/"Xay d\lllg" (OCR garble) → "xay dung" ≠ "xay d\lllg" → **danger → review** (safe direction).
- "UBND Trà Vinh"/"UBND Sóc Trăng" → "ubnd tra vinh" ≠ "ubnd soc trang" → **danger → review**.
- Digit differs (e.g. "Quyết định 1283"/"…2443") → bases differ → **danger → review**.

**Honest residual risk:** Vietnamese diacritics are semantic, so two genuinely distinct entities could share a de-diacritic base. This is why (D4) the auto-clear cell also requires **live degree < a max-blast ceiling**, and why the precision gate (§9) + reversibility (§11) apply — the typo stratum does NOT ride entirely gate-free.

## 7. State machine + migration

`000075_merge_suggestions_review_cleared.{up,down}.sql`:
```sql
-- up: expand the decision vocabulary with 'review_cleared'
ALTER TABLE merge_suggestions DROP CONSTRAINT merge_suggestions_decision_check;
ALTER TABLE merge_suggestions ADD CONSTRAINT merge_suggestions_decision_check
  CHECK (decision IN ('suggested','applied','rejected','needs_review','review_cleared'));
-- down: revert (any 'review_cleared' rows must first be re-set to 'needs_review')
ALTER TABLE merge_suggestions DROP CONSTRAINT merge_suggestions_decision_check;
ALTER TABLE merge_suggestions ADD CONSTRAINT merge_suggestions_decision_check
  CHECK (decision IN ('suggested','applied','rejected','needs_review'));
```
(Confirm the constraint name via `\d merge_suggestions` — Postgres's default for an inline column CHECK is `merge_suggestions_decision_check`; adjust if different.)

Transitions: `needs_review` → `review_cleared` (Python auto for typo; human for danger) → `applied` (the applier) or back to `needs_review` (applier's max-blast ceiling). `UpdateDecision` handles the writes.

## 8. The applier — `ApplyReviewClearedMerges`

A near-copy of `ApplyHubNameMerges` (`apply_suggestions.go:140`):
- `ListByProject(projectID, "review_cleared", maxSuggestions, 0)` (NOT `listByReason` — fuzzy rows carry their own reason, so key on the decision value).
- `byCanon` grouping; recompute LIVE degree per canonical (mirror `:164-170`).
- **Max-blast ceiling:** if a canonical's live degree ≥ `fuzzyHubCeiling` (config; a hard ceiling well above the normal hub threshold), route it back to `needs_review` (requires explicit human) rather than auto-apply — even though it's `review_cleared`.
- `dryRun` → build the manifest (add per-merge `mergeOpID`s captured from `Merge` on apply).
- apply → `processSuggestion(..., bypassDegreeGate=true)` → `Merge` → suggestion `'applied'`.
- Handler route `POST /api/v1/internal/resolution/apply-review-cleared` mirroring `HandleApplyHubName` (dry-run opt-in, `authorizeBodyProjectID`).

## 9. Precision gate

Reuse `fuzzy_sample_cli.py`: add a `--decision` param to `_load_band_async` (target `needs_review` / `review_cleared` instead of `suggested`). Two strata (random + `is_danger_pair`-targeted) on the real hub population; **stricter LCB than B** (e.g. random ≥ 0.97, targeted ≥ 0.93 — tune from the first run) because blast radius scales with degree. Run once before the first non-dry-run drain. FAIL on the targeted stratum → tighten the de-diacritic gate or expand human review; do NOT drain.

## 10. Re-embed / consumer orchestration

The apply path sets no `re_embed_pending`, but a merge can change `canonical_name` (longer title wins) → the canonical's embedding is stale. So, as an explicit orchestrated step after the drain: flag `re_embed_pending` for every applied fuzzy-hub canonical (or invoke the re-embed worker path) and recompute/warm Step-2 related-documents (query-time IDF self-updates, but verify) **before AAA/LAAM read**. Bound the consumer exposure window.

## 11. Reversibility / rollback

`merge.go` is byte-reversible per `merge_op_id` (`merge_undo`/`aliases_merge_provenance` with presence flags). The manifest captures each applied merge's `mergeOpID` → batch un-merge is one pass over the manifest, not archaeology on `resolution_audit`. Verify un-merge restores byte-equivalence on a sample before scaling.

## 12. Deferred — follow-ups

1. **The danger stratum's un-reviewed remainder** — whatever the human doesn't clear stays `needs_review`; revisit later or leave split (safe).
2. **Wire fuzzy-hub auto-apply** into the live pipeline — only after this one-time reviewed drain proves the gate; keep manual + reviewed until then.
3. **A proper `re_embed_pending` on non-resummary merges** (fix the gap at the source) — currently orchestrated externally.
4. **OCR-garbled entity nodes** — extraction-quality cleanup (the "Xay d\lllg" fragments); separate from resolution.

## 13. Test plan

- **Discriminator (Python unit):** `de_diacritic_base` strips combining marks AND folds `đ→d` (assert "Định An"→"dinh an", i.e. `đ` folded — NFD alone leaves it "đinh an"); auto-clear pairs equal ("Hàm/Hâm Giang", "lý/lỷ", "Định/Dinh"), danger pairs differ ("Trà Vinh"/"Sóc Trăng", digit diff, OCR-garble "Xay d\lllg"). Confirm `is_danger_pair` is NOT used as the auto-clear gate (it keeps diacritics → would over-flag typos).
- **Partition step (integration):** seed needs_review fuzzy rows; typo pairs flip to `review_cleared`, danger pairs stay `needs_review`.
- **Migration:** `000075` applies (`review_cleared` accepted), down reverts (after resetting any review_cleared rows).
- **Applier (Go integration):** `ApplyReviewClearedMerges(dryRun=true)` emits a per-canonical manifest, applies nothing; `dryRun=false` merges via `processSuggestion` bypass, suggestion → `applied`, `mergeOpID` captured; a canonical above `fuzzyHubCeiling` routes back to `needs_review`; un-merge restores byte-equivalent.
- **Precision gate:** sampler retargeted to the hub population; stricter LCB thresholds; PASS/FAIL.
- **Post-apply (operational):** dup-name count drops; the "UBND tỉnh Trà Vinh" variants consolidate into one canonical; Step-2 `kg_document_shared_entities` returns the single canonical for two docs mentioning an alias-pair; re-embed flagged.

## 14. Files touched (anticipated)

- `ennam.kg.go/db/migrations/000075_merge_suggestions_review_cleared.{up,down}.sql` — expand the decision CHECK.
- `ennam.kg.go/internal/store/merge_suggestion.go` — reuse `ListByProject` with `'review_cleared'` (no new query needed unless a reason-filtered variant is wanted).
- `ennam.kg.go/internal/service/apply_suggestions.go` — `ApplyReviewClearedMerges` (clone of `ApplyHubNameMerges`, source `review_cleared`, max-blast ceiling, capture `mergeOpID`s).
- `ennam.kg.go/internal/handler/apply_suggestions.go` — `POST /api/v1/internal/resolution/apply-review-cleared` (mirror `HandleApplyHubName`) + `Applier` interface method; wire in `main.go`.
- `ennam.kg.python/src/ennam_kg/resolution/` — a partition step (new small CLI or a mode) reusing `_normalize` + a new `de_diacritic_base`; flips `needs_review → review_cleared` for the typo stratum.
- `ennam.kg.python/src/ennam_kg/resolution/fuzzy_sample_cli.py` — `--decision` param on `_load_band_async`; stricter default thresholds for the hub run.
- Tests alongside each. **No `merge.go`/`pass2.py` change.**
