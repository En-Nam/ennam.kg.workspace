# DAAB Exact-Name Hub Merge (1b) — Design

**Date:** 2026-06-30
**Status:** APPROVED (design) — ready for implementation plan
**Scope:** DAAB (`ennam.kg.go` + `ennam.kg.python`) — entity resolution: corpus-global exact-name merge of duplicate concept (entity) nodes, with a genericness discriminator.
**Parent direction:** cross-document entity linking (the user's real need: "how are these 2 documents related"). BA-033 Slice 2 (community detection / global synthesis) is DROPPED — that is AAA's role, not DAAB's. Step 1a (re-run BA-031 resolution on the corpus) is DONE.
**Related:** `mem:backlog/daab-entity-resolution-corpus-rerun`, `mem:ba031-resolution-thresholds-gates`, `mem:decisions/ba033-slice2-deferred`.

---

## 1. Problem

DAAB's KG has **no cross-document entity links**: the same real-world entity is extracted as many separate concept nodes (e.g. "UBND tỉnh Trà Vinh" ×65, "công ty TNHH xây dựng Hàm Giang" ×103). Documents mentioning the same entity therefore do not connect — so "how are these 2 documents related?" is unanswerable, and downstream consumers (AAA Master Record synthesis, LAAM recall) cannot traverse cross-document relationships.

BA-031 resolution merges duplicates **per-document** (ANN blocking surfaces near pairs within a resolve batch). It never compares the same name **across** the 145-document corpus, so corpus-wide exact-name duplicates survive.

**Latent shared-graph correctness bug (the core of 1b):** the existing exact-name merge path treats `reason='exact normalized name match'` as a merge *safety* contract. It is not. That flag (set by `_normalize`: NFC + lowercase + separator-collapse + honorific-strip) guarantees **string-identity, never entity-identity**. It fires identically on "ubnd tỉnh trà vinh" (one real entity) and "dự án" (generic boilerplate, NOT an entity). There is **no genericness guard anywhere** (verified across Go `store/`+`service/` and Python `resolution/`). The comment at `apply_suggestions.go` even hard-codes the false premise *"exact normalized name = same real entity."* Merging "dự án" ×40 into one node would falsely link unrelated documents and **poison the shared graph for all consumers**.

**Live footgun:** `worker.py` POSTs `/api/v1/internal/resolution/apply-exact-name` after every `resolve_document`, which applies all `decision='suggested' AND reason='exact normalized name match'` rows **gate-bypassed** (`ApplyExactNameMerges` → `processSuggestion(bypassDegreeGate=true)`). Any such generic pair that ever co-blocks gets silently merged today.

## 2. Goals / Non-goals

**Goals**
- Merge corpus-wide exact-name duplicates that are **genuinely the same specific entity**, creating cross-document links through one canonical node.
- Install the **missing genericness discriminator** *in front of* exact-name merging — generic/uncertain names are never silently merged.
- Close the live footgun so new ingestion cannot merge generics.
- Fully reversible, auditable, with a precision gate measured on the **real** proposed-merge population.

**Non-goals (deferred — see §11)**
- BA-033 Slice 2 community detection / global summary (dropped — wrong layer, no consumer).
- A resident ML entity-type classifier / general entity-classification service.
- Re-running heavy LLM classification on every ingestion (the heavy classification is one-time per name; the resident guard is a cheap list lookup).
- The `same_as`-edge alternative (rejected: it doesn't give consumers the ONE canonical node the mandate requires, and abandons the reversible merge machinery).
- Fuzzy (non-exact) hub merging — out of scope; exact-name only.

## 3. Established decisions (from 2-agent review: tech-consultant ⇄ CTO)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **1b is "install the discriminator," not "relax the degree gate."** | The degree gate is ALREADY bypassed for the exact-name band; the real gap is the missing genericness guard. |
| D2 | **Build A — a corpus-global name-grouping scan** (not filter existing rows). | Step-0 measured **0 parked exact-name suggestions** (all `applied`); survivors never co-blocked → a fresh `GROUP BY _normalize(name)` scan is required. |
| D3 | **Hybrid discriminator, fail-safe (deny-and-default-to-review).** | Deterministic for clear buckets; LLM one-shot for the ambiguous residual (which holds the majority of value). Anything not positively cleared → `needs_review`, never silent merge. |
| D4 | **Distinct reason string + apply-path genericness guard** (fix the footgun). | 1b candidates MUST NOT use `reason='exact normalized name match'` (the worker would auto-apply them gate-bypassed before the discriminator runs). |
| D5 | **One-time backfill + resident lightweight guard.** | Backfill the current corpus; install a cheap denylist lookup in the apply path so future ingestion can't re-accumulate the trap. |
| D6 | **Top-degree hubs reviewed by a human even when classified `specific`.** | Blast radius + homonym risk ("Công ty TNHH ABC" could be two firms) scale with degree. Folded into the manifest-review danger strata. |
| D7 | **Reuse `_normalize`, `merge.go`/`unmerge.go`/`merge_undo`** — do not rewrite merge/normalization. | Match 1a's notion of "same name"; reuse the byte-reversible merge contract. |
| D8 | **Precision measured on the REAL proposed population; G2 1.000 is non-transferable.** | G2 was a curated person/org VI set — same blind-spot class that shipped the high-sim antonym bug. |

## 4. Current-state facts (verified on `:5433` / in code, 2026-06-30)

> Counts are point-in-time (corpus still growing; an earlier session saw 661/523). The job re-scans live; treat numbers as scale estimates, not invariants.

- **Code anchors:**
  - `ennam.kg.go/internal/service/apply_suggestions.go` — `ApplyExactNameMerges` (L110) → `processSuggestion(..., bypassDegreeGate=true)` (L129); degree-gate skip at L190-193; false-premise comment L117/104.
  - `ennam.kg.go/internal/store/merge_suggestion.go` — `ListExactNameSuggestions` (L119) filters `decision='suggested' AND reason='exact normalized name match'` (L128).
  - `ennam.kg.go/internal/service/merge.go` / `unmerge.go` — reversible merge + `merge_undo` byte-equivalence.
  - `ennam.kg.python/.../resolution/rules.py` — `_normalize` (L42); `EXACT_NAME_CONFIDENCE`; the antonym-bug postmortem (~L102-109).
  - `ennam.kg.python/.../worker.py:285` — unconditional `/apply-exact-name` POST (the footgun).
  - `ennam.kg.go/internal/config/types.go` — `ResolutionConfig` (`DegreeThreshold`, `AutoApplyExactName`).
- **Step-0:** `merge_suggestions WHERE reason='exact normalized name match'` → **5725 `applied`, 0 `suggested`/`needs_review`** ⟹ Build A.
- **Duplicate landscape:** 497 exact-name groups; **1616 collapsible nodes**. Bucketed by deterministic rules:

  | Bucket | Groups | Collapsible | Disposition |
  |--------|-------:|------------:|-------------|
  | `org_marker` (UBND/công ty/ban quản lý/sở/bộ/cục/…) | 89 | 605 | deterministic **clear** |
  | `bare_geo` (tỉnh/huyện/xã/phường/…, no marker) | 11 | 114 | **reject → needs_review** |
  | `short_generic` (≤12 chars, single token) | 4 | 7 | **reject** |
  | **`residual` (MIXED)** | 393 | **890** | **LLM classify** |

  The residual is genuinely mixed and not separable by simple rules: specific ("dự án khu bến tổng hợp định an" ×31, "thủ tướng chính phủ" ×15, "khu kinh tế định an" ×9) alongside generic ("dự án" ×40, "pháp luật" ×32, "điều 3" ×10, "khoản 2" ×8, "giám đốc" ×11). ⟹ the one-time LLM pass is warranted (890 collapsible nodes at stake).

## 5. Architecture

```
Python one-time job: classify_corpus_names (per project)
  scan concept nodes → GROUP BY _normalize(title), keep groups size>1
  deterministic bucket: org_marker→specific ; bare_geo/short_generic→generic
  residual → LLM classify {specific | generic | uncertain} (+ deterministic cross-check: doc-frequency, token count, markers)
  write artifact rows: entity_name_classification(normalized_name → class, source[rule|llm|human], rationale, reviewed_by)

Python: emit_hub_merge_candidates (per project)
  for each group whose name class='specific' (cleared): write merge_suggestions rows
    reason = 'exact-name hub merge candidate'   ← DISTINCT (worker's /apply-exact-name ignores it)
    decision = 'suggested' ; proposed_canonical_id = chosen canonical of the group
  generic/uncertain names → no candidate (stay split; logged)

Go: ApplyHubNameMerges(projectID, dryRun)   ← sibling of ApplyExactNameMerges
  list reason='exact-name hub merge candidate' AND name class='specific'
  dryRun → emit MANIFEST (group, canonical, members, degrees, projected connectivity-gain); apply nothing
  apply → reuse merge.go (reversible) ; bypassDegreeGate for cleared specifics ; record manifest

Go: apply-path genericness guard (footgun fix)
  ApplyExactNameMerges / ListExactNameSuggestions consult entity_name_classification:
    skip any name classified 'generic' ; route 'uncertain' to needs_review (never auto-merge)
```

Two reusable units: a **classification artifact** (per-name, auditable) and a **discriminator-gated apply** (reuses existing merge). The corpus scan and `_normalize` live in Python (where `_normalize` is); the merge apply lives in Go (where `merge.go` is) — mirroring the existing producer/apply split.

## 6. The discriminator

**Semantics:** binary, fail-safe. *Positively cleared as a specific entity → eligible for merge; everything else (generic OR uncertain) → not merged (logged / `needs_review`).*

**6.1 Deterministic pass (no LLM):**
- **`org_marker` → specific.** Normalized name contains an org/legal marker: `công ty`(+`tnhh`/`cổ phần`), `tổng công ty`, `tập đoàn`, `ngân hàng`, `hợp tác xã`, `doanh nghiệp`, `chi nhánh`, `ủy ban nhân dân`/`ubnd`, `hđnd`/`hội đồng nhân dân`, `ban quản lý`, `ban chỉ đạo`, `sở `, `bộ `, `cục `/`tổng cục`/`chi cục`, `phòng `, `trung tâm`, `viện `, `trường`/`đại học`, `bệnh viện`, `kho bạc`. **Marker precedence:** an org marker wins even if a geo token is present → "ubnd tỉnh trà vinh" = specific.
- **`bare_geo` → generic** (no marker, leads with `tỉnh`/`thành phố`/`tp`/`huyện`/`xã`/`phường`/`thị xã`/`thị trấn`/`ấp`/`khóm`/`quận`). Catches "tỉnh trà vinh" ×34 (a partial place reference, very high degree).
- **`short_generic` → generic** (≤12 chars, single token).

**6.2 LLM pass (one-shot, ~393 residual names):**
Classify each residual normalized name into `{specific | generic | uncertain}`. Prompt frames it as: *"Is this Vietnamese phrase a specific named entity (a particular organization, place, person, project, or document by its full proper name) safe to treat as ONE entity across documents — or a generic common noun / category / legal-reference (điều/khoản) / role that recurs identically across unrelated documents?"* Provide examples from the measured data. **Deterministic cross-check:** flag disagreement when the LLM says `specific` but the name is short + very high corpus document-frequency (the generic signature) → downgrade to `uncertain`. Rule 5 compliant (genuine classification/judgment, one-time batch, never in-loop).

**6.3 Artifact:** `entity_name_classification(normalized_name PK, class, source, rationale, reviewed_by, created_at)`. Every auto-merge traces to why a name was deemed a real entity. Human edits override (source=`human`).

## 7. The merge job

- **Corpus-global scan** (Python): `GROUP BY _normalize(title)` over `node_type='concept'` (active, non-archived), groups size>1. Reuse `_normalize` exactly (D7).
- **Candidate emission** (Python): for `specific` groups, write `merge_suggestions` rows with `reason='exact-name hub merge candidate'` (distinct — D4), `decision='suggested'`, a chosen `proposed_canonical_id` (e.g. highest-degree or earliest-created member; deterministic tiebreak).
- **Apply** (Go `ApplyHubNameMerges`): lists the distinct-reason candidates whose name class=`specific`; `dryRun` emits the manifest; apply reuses `merge.go` (reversible), `bypassDegreeGate=true` for cleared specifics, writes each merge to a retained **manifest** (group → canonical, members, degrees, projected connectivity-gain).
- **Idempotent + re-runnable** — re-running skips already-merged groups (members carry `merged_into`/`superseded_by_merge`).

## 8. Footgun fix (mandatory)

1. **Distinct reason string** for 1b candidates (§7) — the worker's `/apply-exact-name` (filters `reason='exact normalized name match'`) never touches them.
2. **Apply-path genericness guard:** `ListExactNameSuggestions` / `processSuggestion` consult `entity_name_classification` and **skip names classified `generic`**, route `uncertain` to `needs_review`. This closes the live footgun for the existing `exact normalized name match` path too, so future ingestion cannot silently merge "dự án". Resident cost = one indexed lookup per candidate.

## 9. Rollout & safety

1. **Step-0 SQL** (re-verify on the live stack before coding): exact-name `decision` breakdown (A vs B); bucket the groups; residual node-mass; reconcile corpus/count (`:5433` vs the daab-* stack the 1a checkpoint cites). Numbers size the review tiers; the design holds regardless.
2. **Shadow → manifest:** generate candidates + run `ApplyHubNameMerges(dryRun)` → manifest of every proposed merge.
3. **Review (gate to apply):**
   - **Exhaustive** on danger strata: ALL `generic` and `uncertain` classifications (assert zero would-merge) + ALL **top-degree** groups (e.g. degree ≥ a high threshold / top-K by size — the ×103/×65/×63 hubs) human-confirmed even if `specific`.
   - **Sample** N≈60–100 from the cleared bulk (honestly labelled a weak upper bound).
   - **Pass = zero false merges in danger review AND zero in bulk sample AND a passing un-merge drill.**
4. **Un-merge drill:** un-merge a handful of real merges, assert byte-equivalent restore (trust-but-verify the `merge.go` contract on the shared graph).
5. **Apply** cleared specifics; **retain the manifest** for false-merge detection + targeted rollback.
6. **Measure gain:** connected-component reduction / count of new cross-document paths through the canonical nodes (before/after).

## 10. Ongoing guard (resident, lightweight)

The `entity_name_classification` table is resident. The apply-path guard (§8.2) makes future ingestion fail-safe: known-`generic` names never merge; names not positively cleared route to `needs_review`. No heavy classification at ingest — a list lookup + a review queue. New unseen names accumulate in `needs_review`; a periodic (manual) re-run of the classification job clears them.

## 11. Deferred — follow-ups

1. **Periodic re-classification** of newly-seen `needs_review` names (manual trigger initially; automate only if drift rate justifies).
2. **The 4695 `suggested` (non-exact, fuzzy) backlog** — separate from 1b; triage later.
3. **Fuzzy hub merge** (non-exact near-duplicates) — out of scope; revisit after exact-name proves the connectivity value.
4. **Step 2 — "related documents / shared entities" retrieval** (the user-facing feature this unblocks): given 2 docs → shared canonical entities; given 1 doc → related docs. Mostly reuses `neighbors.go`/`graph_retrieve.go`; no LLM. Its own spec.
5. **Entity typing at extraction** (populate `subtype`) — would make future discriminators trivial; large pipeline change, deferred.

## 12. Test plan

**Discriminator (Python unit):**
- `org_marker` rule: "ubnd tỉnh trà vinh", "công ty tnhh xây dựng hàm giang", "ban quản lý khu kinh tế trà vinh" → `specific` (marker precedence over geo).
- `bare_geo`: "tỉnh trà vinh" → `generic`. `short_generic`: a ≤12-char single token → `generic`.
- LLM-pass harness on a labelled residual fixture (the measured names): "dự án", "pháp luật", "điều 3", "khoản 2" → `generic`; "dự án khu bến tổng hợp định an", "khu kinh tế định an", "thủ tướng chính phủ" → `specific`. Cross-check downgrade: high-doc-freq short name claimed `specific` → `uncertain`.
- Artifact upsert + `human` override precedence.

**Merge job (Go, integration on test DB):**
- Corpus-global scan groups exact-name duplicates (reuses `_normalize`); `specific` group merges into one canonical; `generic` group is NOT merged; members carry `merged_into`.
- Candidate rows use `reason='exact-name hub merge candidate'` (NOT the footgun reason).
- `ApplyHubNameMerges(dryRun)` emits a manifest and applies nothing; non-dryRun applies + records manifest.
- Idempotent: second run merges nothing further.
- **Footgun regression:** `ApplyExactNameMerges` skips a name classified `generic` (route `uncertain` to needs_review) — a generic exact-name pair is NOT auto-merged.
- Un-merge restores byte-equivalent.

**Connectivity (integration):** after merging a `specific` group spanning 2 documents, the two documents share a canonical node (a cross-document path exists that did not before).

## 13. Files touched (anticipated)

- `ennam.kg.python/.../resolution/` — new `classify_corpus_names` + `emit_hub_merge_candidates` (reuse `_normalize`, `rules.py`); CLI entrypoint; deterministic bucket rules + LLM classification.
- `ennam.kg.go/db/migrations/000074_entity_name_classification.{up,down}.sql` — the artifact table (current head is `000073`; re-verify at implementation).
- `ennam.kg.go/internal/store/` — `entity_name_classification` store + a `ListHubMergeCandidates` (clone of `ListExactNameSuggestions` with the distinct reason + class join).
- `ennam.kg.go/internal/service/apply_suggestions.go` — `ApplyHubNameMerges` (sibling; manifest + dryRun) + insert the genericness guard into `ApplyExactNameMerges`/`processSuggestion`.
- `ennam.kg.go/internal/service/merge.go`/`unmerge.go` — reused, not modified (unless the manifest needs a hook).
- Tests alongside each.
