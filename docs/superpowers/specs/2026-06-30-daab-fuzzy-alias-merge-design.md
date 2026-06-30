# DAAB Fuzzy Alias Merge (B) — Design

**Date:** 2026-06-30
**Status:** APPROVED (design) — ready for implementation plan
**Scope:** DAAB (`ennam.kg.go` + a small Python adjudication script) — apply the parked fuzzy entity-merge backlog (the next entity-resolution tier after 1b exact-name merge), gated by a stratified precision check.
**Parent direction:** tighter cross-document entity linking. 1b merged **exact-name** aliases; B merges **fuzzy** aliases of the same entity (abbreviation↔full-form, diacritic/word-order variants) that 1b can't catch — improving Step-2 related-documents relatedness.
**Related:** `mem:ba031-resolution-thresholds-gates`, the 1b spec `2026-06-30-daab-exact-name-hub-merge-design.md`, Step-2 spec `2026-06-30-daab-related-documents-design.md`.

---

## 1. Problem

BA-031 Pass-2 (ANN blocking sim≥0.74 → cross-encoder bge-reranker → LLM `same_entity` verify) produced **4695 fuzzy merge suggestions** that sit **parked** (`decision='suggested'`). They are genuine aliases of the same entity — abbreviation↔full ("Bộ GTVT" ↔ "Bộ Giao thông vận tải", "UBND thị xã Duyên Hải" ↔ "Ủy ban nhân dân thị xã Duyên Hải"), missing conjunction ("Sở Tài nguyên và Môi trường" ↔ "Sở Tài nguyên Môi trường"), diacritic typos ("kinh tế" ↔ "kinh tê") — that 1b's exact-name rule (post-`_normalize`) cannot catch. Leaving them split keeps the same real entity fragmented across documents, weakening cross-document linking and Step-2 relatedness (the Step-2 quality gate flagged "semi-blob" cases partly from unmerged aliases).

The apply path already exists; B is **not** a new feature. But applying fuzzy merges is **riskier than exact-name**: fuzzy is *similarity*, not *identity*. A near-identical pair differing by one salient token (e.g. "UBND tỉnh Trà Vinh" vs "UBND tỉnh Sóc Trăng" — different provinces) could be a false merge that corrupts the shared graph for all consumers (AAA Master Record, LAAM recall, Step-2 IDF). So B must gate the apply on a precision check that specifically targets that failure mode.

## 2. Goals / Non-goals

**Goals**
- Apply the parked fuzzy LEAF merge backlog to consolidate aliases of the same entity.
- Gate the apply on a **stratified precision check on the real proposed population** that over-weights the one-salient-token-difference danger stratum.
- Fully reversible, with a manifest, and bounded consumer exposure.

**Non-goals (deferred — see §11)**
- **Fuzzy HUB merges** (degree≥10): not in the parked backlog (0 hubs), maximum blast radius — deferred. The existing degree gate routes any mid-batch hub accretion to `needs_review` automatically.
- **Re-running BA-031 Pass-2** / a new classifier / a 1b-style discriminator — the verdicts already exist and are LLM-judged (§4); re-validation = rebuilding Pass-2.
- A `bypassDegreeGate` apply variant (the exact-name/1b pattern) — fuzzy is NOT identity; the degree gate MUST stay live.
- New `audit_trail` enum / bespoke governance — `Merge` already records `merged_into`/reason/confidence/model and is reversible; that is the audit.
- Fixing OCR-garbled entity nodes (§4) — an extraction-quality concern, not B.

## 3. Established decisions (from 2-agent review, resolved by data)

| # | Decision | Basis |
|---|----------|-------|
| D1 | **Run the existing `ApplySuggestionsService.Apply(projectID, degreeThreshold)`** — degree gate ON, reason-agnostic sweep of `decision='suggested'`. No new apply code in the happy path. | Verified: `Apply` → `ListByProject(…, "suggested", …)` → `processSuggestion(…, false, …)` (`apply_suggestions.go:84-95`). The parked band IS the entire `suggested` population (4695 == 4695). |
| D2 | **Trust the parked verdicts; do NOT re-run Pass-2.** | Data-resolved the CTO⇄consultant disagreement: every parked row's `reason` is a natural-language **LLM verdict** ("Bộ GTVT is the abbreviation of…"), NOT the deleted high-sim rule's mechanical reason. So they came from the surviving CE+LLM path. |
| D3 | **Degree gate STAYS ON (no bypass).** | Fuzzy = similarity, not identity. Hub-safety (NFR-256) must remain live; a hub accreting degree mid-batch auto-routes to `needs_review`. |
| D4 | **Gate apply on a two-stratum precision sample on the REAL 4695 population** (random + targeted one-salient-token-difference), human-adjudicated, gate on the lower-confidence bound. | The LLM has a concentrated failure mode (cross-province near-names); a uniform sample hides it. Curated benchmarks (G2 1.000) are non-transferable — the antonym bug shipped past one. |
| D5 | **Leaf-only; defer fuzzy hubs.** | 0 hubs in the backlog; fuzzy hub false-merge is the max-blast event. |
| D6 | **Reversible + applied-ID manifest + bounded consumer window** (re-embed + recompute Step-2 IDF before consumers read). | `merge.go` sets `re_embed_pending`; `merge_undo`/`unmerge` exist. Undo bounds duration, not what consumers already read — so bound the exposure window. |

## 4. Current-state facts (verified on :5433 / in code, 2026-06-30)

- **Apply path (reuse target):** `internal/service/apply_suggestions.go:84` `Apply(ctx, projectID, degreeThreshold)` → `ListByProject(projectID, "suggested", maxSuggestions, 0)` (reason-agnostic) → `processSuggestion(ctx, ms, degreeThreshold, false, &result)` (**bypassDegreeGate=false** → live degree gate). `internal/handler/apply_suggestions.go` `HandleApply` is gated `if h.resolution.ApplyMode != "apply" → 503`.
- **The trapdoor is dormant, manual-only:** the worker (`ennam.kg.python/.../worker.py:285`) auto-calls **only** `/api/v1/internal/resolution/apply-exact-name`, NOT the generic `/apply`. So the 4695 fuzzy rows are NOT auto-flushed; they apply only on a manual `/apply` call. ⟹ **the gate is "do not call generic `/apply` until the precision sample passes."**
- **Parked band:** `merge_suggestions WHERE decision='suggested'` = **4695**, all with `reason <> 'exact normalized name match'` (i.e. the entire suggested population is the fuzzy band — `all_suggested == fuzzy == 4695`), **0 hubs (degree_max≥10) — all LEAF**, avg `merge_confidence` 0.95, avg `embedding_similarity` 0.94.
- **Verdict provenance:** all `reason` strings are LLM judgments (e.g. "The abbreviation UBND và the full name denote the same People's Committee of Duyên Hải town", "differ only by missing diacritic") — the surviving CE+LLM pipeline, not the deleted sim-rule. ⟹ trustworthy (D2).
- **Sample eyeball:** clean aliases ("…kinh tế tỉnh Trà Vinh" ↔ "…Trà Vinh"; "Sở TN&MT" ↔ "Sở TN MT"; "kinh tế" ↔ "kinh tê"). **New finding:** some pairs are **OCR-garbled document-header fragments** ("UBND TỈNH TRÀ VINH CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM" concatenations) — still arguably same-entity, but noise nodes (extraction-quality issue, not B's to fix; they merge harmlessly).
- **Reuse:** `internal/service/merge.go` (reversible merge: `merged_into`, `merge_undo`, alias union, `re_embed_pending`), `internal/service/apply_suggestions.go` (`HubMergeManifest` dry-run shape to mirror for the manifest), `internal/store/merge_suggestion.go` (`ListByProject`, `UpdateDecision`). `ennam.kg.python/.../resolution/pass2.py` (`route_pairs` — the verdict source; NO changes).

## 5. Architecture

```
Step 0 (verify): confirm all_suggested == fuzzy band; reason-distribution = LLM verdicts (re-run the §4 queries live).

Precision gate (Python adjudication script + human):
  draw two strata from the real 4695 population →
    (a) random ~100
    (b) targeted ~100: pairs whose _normalize'd names differ by exactly ONE token
        AND that token is a salient discriminator (province / town / number / date)
  human adjudicate same_entity (true/false) per pair →
  compute precision + a lower-confidence bound (Wilson) per stratum →
  PASS iff both strata clear the threshold (e.g. LCB ≥ 0.95 random, ≥ 0.90 targeted)

Apply (only after gate passes):
  POST /api/v1/internal/resolution/apply  {project_id}  (apply_mode=apply, degree gate ON)
  → ApplySuggestionsService.Apply → processSuggestion (gate live; hub accretion → needs_review)
  → emit an applied-ID manifest (suggestion_id, member, canonical) for audit/rollback

Consumer window:
  apply in a controlled window → trigger re-embed (merge sets re_embed_pending) +
  recompute Step-2 related-documents IDF before AAA/LAAM/dashboard read.

Rollback: spot-check post-apply; un-merge any false merge via the existing unmerge path.
```

Net new code is small: a **sampling/adjudication script** (Python, reads `merge_suggestions` + node titles, emits the two strata + computes precision/LCB) and a **manifest emit** on apply. The apply itself reuses the shipped, tested `Apply` path.

## 6. Precision gate (the safety core)

**Two strata, ~100 pairs each, human-adjudicated** (`same_entity` yes/no), NOT a review of all 4695:
1. **Random stratum** — uniform sample of the 4695 → estimates overall band precision.
2. **Targeted (danger) stratum** — pairs whose `_normalize`'d names differ by exactly **one token**, and that token is a salient discriminator (a province/town/district name, a number, or a date). This is the "UBND Trà Vinh vs UBND Sóc Trăng" / "thị xã X vs thị xã Y" false-merge class. Over-weighting it is mandatory — a uniform sample reports ~96% mean while a 70%-precision danger sub-population silently corrupts one entity class.

**Gate:** compute a Wilson lower-confidence bound per stratum; **PASS iff both clear their thresholds** (suggested: random LCB ≥ 0.95, targeted LCB ≥ 0.90 — tune from the spec author's first run). **FAIL on the targeted stratum** → add a **deterministic pre-filter** that excludes one-salient-token-difference pairs from this apply run (do NOT pre-build it; let the sample prove the need), and re-gate the remainder.

This is the precision gate "on the real population" both reviewers demanded, satisfied with ~200 adjudications instead of 4695.

## 7. Apply mechanism

- After the gate passes, apply via the existing `POST /api/v1/internal/resolution/apply` (`HandleApply` → `Apply(projectID, degreeThreshold)`), `apply_mode=apply`. **Degree gate stays ON** (no bypass). Hubs that accrete degree mid-batch auto-route to `needs_review` (free hub-deferral).
- If Step-0 finds `all_suggested > fuzzy` (un-applied exact/hub leftovers co-mingled — NOT the case today, but re-verify), add a reason-exclusion lister (`reason NOT IN ('exact normalized name match','exact-name hub merge candidate')`) so the run doesn't co-mingle bands. Today they are equal → the generic `Apply` IS exactly the fuzzy band.
- **Manifest:** capture the applied suggestion IDs + (member, canonical) — mirror the 1b `HubMergeManifest` shape — for audit + targeted rollback.

## 8. Trapdoor precaution

The generic `/apply` would flush all 4695 with no precision floor (degree gate is inert for an all-leaf set). It is dormant (worker doesn't call it — §4), so the operational rule suffices: **do not call generic `/apply` until the precision gate passes.** Optional belt-and-suspenders (only if the team wants a hard guard): temporarily move the fuzzy rows out of `decision='suggested'` (or reason-scope `Apply`) until gated — not required given the dormancy, but cheap insurance for a shared graph.

## 9. Consumer-impact window

A false merge rewrites `canonical_name`, unions aliases, and re-points edges; anything AAA/LAAM/Step-2 reads in the window between merge and any un-merge sees corrupted truth. So: **apply in a controlled window**, then trigger re-embed (merge already sets `re_embed_pending` for the worker) + recompute Step-2 related-documents IDF (the IDF is computed at query time, so it self-updates — but warm/verify before announcing). Bound the exposure; have the rollback runbook ready.

## 10. Reversibility / rollback

`Merge` stamps `merged_into` + reason + confidence + `resolution_model`; `unmerge`/`merge_undo` restore. Post-apply spot-check (re-sample ~50 applied pairs); any false merge → un-merge via the existing path, using the manifest to target it. No new rollback machinery.

## 11. Deferred — follow-ups

1. **Fuzzy HUB merges** (degree≥10) — high blast radius, not in the backlog; a separate, more-gated effort if cross-document linking still needs them after B.
2. **One-salient-token-difference pre-filter** — build only if the targeted stratum fails (§6).
3. **OCR-garbled entity nodes** — extraction-quality cleanup (the header-fragment concatenations); separate from resolution.
4. **Wire the fuzzy auto-apply** into the live pipeline (so future ingestion's fuzzy leaf suggestions apply automatically) — only after B's one-time gate establishes the precision is trustworthy; until then keep it manual + gated.

## 12. Test / verification plan

This is mostly an **operational runbook** (the apply path is already unit/integration-tested); net new code = the sampling script + manifest.

- **Step 0 (re-verify live):** `all_suggested == fuzzy == 4695`; reason-distribution = LLM verdicts (re-run §4 queries).
- **Sampling script (unit):** given a fixed set of `merge_suggestions` rows, it draws the random + targeted strata correctly (targeted = one-salient-token-diff), computes precision + Wilson LCB. Deterministic with a seeded RNG.
- **Gate (manual adjudication):** record the two strata's labels + LCBs; PASS/FAIL per §6 thresholds. Document the result.
- **Apply (integration):** on a test DB seeded with a fuzzy `suggested` pair, `Apply` merges it (gate ON), `merged_into` set, manifest captures the id; a hub pair routes to `needs_review`; un-merge restores.
- **Post-apply (operational):** duplicate-node count drops; re-sample ~50 applied pairs for false merges (target 0); spot-check Step-2 relatedness improved on a known alias (e.g. docs sharing "Bộ Giao thông vận tải" now link through one canonical).
- **Manifest:** applied-ID list persisted for rollback.

## 13. Files touched (anticipated)

- `ennam.kg.python/src/ennam_kg/resolution/` (new) — `fuzzy_sample_cli.py`: draws the two strata from `merge_suggestions` (+ node titles via DB), emits them for adjudication, computes precision + Wilson LCB. Reuses `_normalize` for the one-token-difference detector. (+ unit test.)
- `ennam.kg.go/internal/service/apply_suggestions.go` — emit an applied-ID manifest from `Apply` (or a thin wrapper) for audit/rollback; no change to the gating/merge logic.
- `ennam.kg.go/internal/store/merge_suggestion.go` — a reason-exclusion lister ONLY if Step-0 shows co-mingled bands (not needed today).
- **No migration** (uses existing tables + apply path). **No `merge.go`/`pass2.py` changes** (reuse as-is).
