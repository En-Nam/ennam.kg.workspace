# DAAB Fuzzy HUB Merge (review_cleared) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drain the 4044 parked fuzzy HUB merge suggestions (`needs_review`) safely — auto-clear the OCR/diacritic-typo majority via a deterministic de-diacritic gate, human-review only the bounded danger stratum, and apply cleared rows via a stricter sibling of `ApplyHubNameMerges`.

**Architecture:** A 3-value decision state machine (`needs_review → review_cleared → applied`). A Python partition step (de-diacritic base-form equality) auto-clears typos; a human clears the danger stratum per-canonical; a new Go applier `ApplyReviewClearedMerges` (clone of `ApplyHubNameMerges`, bypass + dry-run manifest + live-degree + max-blast ceiling) drains `review_cleared`. Reversible; re-embed orchestrated for embedding-based consumers (NOT Step-2, which self-updates from the re-pointed graph).

**Tech Stack:** Go (`ennam.kg.go`: `database/sql`, golang-migrate) + Python (`ennam.kg.python`: asyncpg, reuse `_normalize`). Tests: `go test` + `pytest`.

**Design spec:** `docs/superpowers/specs/2026-07-01-daab-fuzzy-hub-merge-design.md`

## Global Constraints

- Nested repos; run from each. DB :5433 (`KG_DATABASE_URL=postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg`). Integration: store `KG_TEST_DATABASE_URL`, handler `KG_TEST_DSN` → both :5433.
- Migration head `000074` → new `000075`. Constraint name verified: `merge_suggestions_decision_check`.
- **NFR-256 satisfied by a REVIEWED merge, not bypassed:** apply `review_cleared` via a dedicated bypass applier; NEVER re-route rows to `'suggested'` (re-enters the leaf gate → infinite loop).
- **Auto-clear gate = deterministic de-diacritic base-form EQUALITY** (independent of the spent LLM confidence, Rule 5). `is_danger_pair` (B) keeps diacritics → NOT the auto-clear gate.
- Degree gate stays ON everywhere except the reviewed bypass applier. Live degree recompute (stored `degree_max=0`).
- Reuse `merge.go`/`unmerge` (reversible), `ApplyHubNameMerges`/`processSuggestion` (clone), `fuzzy_sample_cli.py` (retarget). No `merge.go`/`pass2.py` change.
- Project `592c7ff7-9f6f-4cc5-9094-d9b3b685277e` (re-verify; counts point-in-time).

---

## Task 1: Migration — add `review_cleared` decision value

**Files:**
- Create: `ennam.kg.go/db/migrations/000075_merge_suggestions_review_cleared.up.sql`
- Create: `ennam.kg.go/db/migrations/000075_merge_suggestions_review_cleared.down.sql`

- [ ] **Step 1: up migration**
```sql
ALTER TABLE merge_suggestions DROP CONSTRAINT merge_suggestions_decision_check;
ALTER TABLE merge_suggestions ADD CONSTRAINT merge_suggestions_decision_check
  CHECK (decision IN ('suggested','applied','rejected','needs_review','review_cleared'));
```

- [ ] **Step 2: down migration**
```sql
-- any 'review_cleared' rows must be reset before reverting the constraint
UPDATE merge_suggestions SET decision='needs_review' WHERE decision='review_cleared';
ALTER TABLE merge_suggestions DROP CONSTRAINT merge_suggestions_decision_check;
ALTER TABLE merge_suggestions ADD CONSTRAINT merge_suggestions_decision_check
  CHECK (decision IN ('suggested','applied','rejected','needs_review'));
```

- [ ] **Step 3: apply + verify**

Run: `make db-migrate && make db-migrate-version` → `75`. `make db-shell`: `INSERT ... decision='review_cleared'` accepted; `\d merge_suggestions` shows the updated CHECK.

- [ ] **Step 4: reversibility** — `make db-migrate-down && make db-migrate && make db-migrate-version` → `75`.

- [ ] **Step 5: commit**
```bash
git add db/migrations/000075_merge_suggestions_review_cleared.up.sql db/migrations/000075_merge_suggestions_review_cleared.down.sql
git commit -m "feat(daab): add review_cleared decision value for fuzzy hub merge"
```

---

## Task 2: Python partition step — de-diacritic auto-clear

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/resolution/hub_partition_cli.py`
- Test: `ennam.kg.python/tests/resolution/test_hub_partition.py`

**Interfaces:**
- Pure: `de_diacritic_base(name: str) -> str` — `_normalize` + strip combining marks (NFD→drop Mn→recompose) + fold `đ→d`/`Đ→D`.
- CLI: `--project <uuid>` scans `needs_review` fuzzy rows; where `de_diacritic_base(a)==de_diacritic_base(b)` → flip `decision='review_cleared'`; else leave `needs_review`. `--dry-run` prints the split counts.

- [ ] **Step 1: failing unit tests**

Create `tests/resolution/test_hub_partition.py`:
```python
from ennam_kg.resolution.hub_partition_cli import de_diacritic_base, is_typo_pair

def test_de_diacritic_strips_combining_and_folds_d():
    assert de_diacritic_base("Định An") == "dinh an"   # đ→d AND ị diacritic stripped
    assert de_diacritic_base("Trà Vinh") == "tra vinh"

def test_typo_pairs_auto_clear():
    assert is_typo_pair("Công ty TNHH Xây dựng Hàm Giang", "Công ty TNHH Xây dựng Hâm Giang")  # à↔â
    assert is_typo_pair("Ban Quản lý KKT Trà Vinh", "Ban Quản lỷ KKT Trà Vinh")                 # ý↔ỷ
    assert is_typo_pair("Định An", "Dinh An")                                                   # đ↔d

def test_danger_pairs_stay():
    assert not is_typo_pair("UBND tỉnh Trà Vinh", "UBND tỉnh Sóc Trăng")  # different province
    assert not is_typo_pair("Quyết định 1283", "Quyết định 2443")          # different number
    assert not is_typo_pair("Xây dựng", "Xay d\\lllg")                     # OCR garble
```

- [ ] **Step 2: run → fail** — `cd ennam.kg.python && uv run pytest tests/resolution/test_hub_partition.py -v`.

- [ ] **Step 3: implement**

Create `src/ennam_kg/resolution/hub_partition_cli.py`:
```python
"""Partition the fuzzy-hub needs_review backlog: auto-clear OCR/diacritic-typo
pairs (needs_review -> review_cleared); leave the danger stratum for human review.
The auto-clear gate is a deterministic de-diacritic base-form equality — independent
of the (already-spent) LLM confidence (Rule 5).
"""
from __future__ import annotations
import argparse
import os
import unicodedata

from ennam_kg.resolution.rules import _normalize


def de_diacritic_base(name: str) -> str:
    """_normalize + strip Unicode combining marks + fold đ→d (NFD does NOT fold đ)."""
    base = _normalize(name)
    base = base.replace("đ", "d").replace("Đ", "d")  # đ/Đ are distinct letters, not d+mark
    decomposed = unicodedata.normalize("NFD", base)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", stripped)


def is_typo_pair(name_a: str, name_b: str) -> bool:
    """True = same entity under OCR/diacritic noise (auto-clear); False = danger (review)."""
    return de_diacritic_base(name_a) == de_diacritic_base(name_b)


async def _partition_async(project_id: str, dry_run: bool) -> tuple[int, int]:
    import asyncpg
    conn = await asyncpg.connect(os.environ["KG_DATABASE_URL"])
    try:
        rows = await conn.fetch(
            """
            SELECT ms.id::text, na.title, nb.title
            FROM merge_suggestions ms
            JOIN knowledge_nodes na ON na.id = ms.node_a_id
            JOIN knowledge_nodes nb ON nb.id = ms.node_b_id
            WHERE ms.project_id = $1::uuid AND ms.decision = 'needs_review'
              AND ms.reason <> 'exact normalized name match'
            """,
            project_id,
        )
        typo_ids = [r[0] for r in rows if is_typo_pair(r[1], r[2])]
        danger = len(rows) - len(typo_ids)
        if not dry_run and typo_ids:
            await conn.execute(
                "UPDATE merge_suggestions SET decision='review_cleared' WHERE id = ANY($1::uuid[])",
                typo_ids,
            )
        return len(typo_ids), danger
    finally:
        await conn.close()


def main() -> None:
    import asyncio
    p = argparse.ArgumentParser(description="Partition fuzzy-hub needs_review (typo auto-clear)")
    p.add_argument("--project", required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    cleared, danger = asyncio.run(_partition_async(args.project, args.dry_run))
    print(f"typo(auto-clear)={cleared}  danger(stay needs_review)={danger}  {'(dry-run, no writes)' if args.dry_run else '-> flipped to review_cleared'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: run → pass** — `uv run pytest tests/resolution/test_hub_partition.py -v`.

- [ ] **Step 5: commit**
```bash
cd ennam.kg.python
git add src/ennam_kg/resolution/hub_partition_cli.py tests/resolution/test_hub_partition.py
git commit -m "feat(daab): de-diacritic partition of fuzzy-hub needs_review (typo auto-clear)"
```

---

## Task 3: Go applier `ApplyReviewClearedMerges` + endpoint

**Files:**
- Modify: `ennam.kg.go/internal/service/apply_suggestions.go`
- Modify: `ennam.kg.go/internal/handler/apply_suggestions.go` (+ `Applier` interface + route)
- Modify: `ennam.kg.go/cmd/kg-server/main.go` (no change if the same handler/applier is reused — verify)
- Test: `ennam.kg.go/internal/service/apply_suggestions_test.go` (extend)

**Interfaces:**
- Produces: `(*ApplySuggestionsService).ApplyReviewClearedMerges(ctx, projectID string, dryRun bool) (ApplyResult, HubMergeManifest, error)` — clone of `ApplyHubNameMerges` sourcing `ListByProject(…, "review_cleared", …)`, with a live-degree **max-blast ceiling** that routes a too-high-degree canonical back to `needs_review`.
- `POST /api/v1/internal/resolution/apply-review-cleared`.

- [ ] **Step 1: failing test**

Extend `apply_suggestions_test.go` (mirror the `ApplyHubNameMerges` test): seed `review_cleared` fuzzy rows via the fake `suggestionStore`; assert `ApplyReviewClearedMerges(dryRun=true)` returns a per-canonical manifest, applies 0; `dryRun=false` applies via `processSuggestion` (bypass), suggestion→applied; a canonical whose live degree ≥ `fuzzyHubMaxBlastCeiling` is routed to `needs_review` (not applied). Use the file's existing fakes.

- [ ] **Step 2: run → fail** — `go test ./internal/service/ -run TestApplyReviewCleared -v`.

- [ ] **Step 3: implement** — in `apply_suggestions.go`, add the ceiling const + the method (clone of `ApplyHubNameMerges:140`):
```go
// fuzzyHubMaxBlastCeiling: even a typo-cleared fuzzy hub whose live degree is at/above
// this is routed to needs_review for an explicit human — de-diacritic equality is
// strong but not perfect for semantic VN diacritics, and blast radius scales with degree.
const fuzzyHubMaxBlastCeiling = 40

// ApplyReviewClearedMerges drains decision='review_cleared' fuzzy-hub rows. dryRun builds
// the per-canonical manifest and applies nothing. Cleared rows bypass the degree gate,
// EXCEPT a canonical at/above fuzzyHubMaxBlastCeiling, which is routed back to needs_review.
func (s *ApplySuggestionsService) ApplyReviewClearedMerges(ctx context.Context, projectID string, dryRun bool) (ApplyResult, HubMergeManifest, error) {
	sugg, err := s.suggestionStore.ListByProject(ctx, projectID, "review_cleared", maxSuggestions, 0)
	if err != nil {
		return ApplyResult{}, HubMergeManifest{}, fmt.Errorf("list review_cleared: %w", err)
	}
	byCanon := map[string]*HubMergeGroup{}
	for _, sg := range sugg {
		g := byCanon[sg.ProposedCanonicalID]
		if g == nil {
			g = &HubMergeGroup{CanonicalID: sg.ProposedCanonicalID}
			byCanon[sg.ProposedCanonicalID] = g
		}
		member := sg.NodeAID
		if sg.ProposedCanonicalID == sg.NodeAID {
			member = sg.NodeBID
		}
		g.MemberIDs = append(g.MemberIDs, member)
	}
	canonDegree := make(map[string]int, len(byCanon))
	for canonID := range byCanon {
		d, derr := s.edgeStore.Degree(ctx, canonID)
		if derr != nil {
			return ApplyResult{}, HubMergeManifest{}, fmt.Errorf("degree for %s: %w", canonID, derr)
		}
		canonDegree[canonID] = d
	}
	var manifest HubMergeManifest
	for canonID, g := range byCanon {
		g.DegreeMax = canonDegree[canonID]
		manifest.Groups = append(manifest.Groups, *g)
	}
	if dryRun {
		return ApplyResult{}, manifest, nil
	}
	var res ApplyResult
	for _, sg := range sugg {
		if canonDegree[sg.ProposedCanonicalID] >= fuzzyHubMaxBlastCeiling {
			// max-blast tail: require explicit human, route back to needs_review.
			if uerr := s.suggestionStore.UpdateDecision(ctx, sg.ID, "needs_review"); uerr != nil {
				res.Errors = append(res.Errors, fmt.Errorf("suggestion %s route-back: %w", sg.ID, uerr))
				continue
			}
			res.NeedsReview++
			continue
		}
		if applyErr := s.processSuggestion(ctx, sg, 0, true, &res); applyErr != nil {
			res.Errors = append(res.Errors, fmt.Errorf("suggestion %s: %w", sg.ID, applyErr))
		}
	}
	s.logger.Info("apply review-cleared merges", "project_id", projectID, "applied", res.Applied, "needs_review", res.NeedsReview, "groups", len(manifest.Groups))
	return res, manifest, nil
}
```

- [ ] **Step 4: handler + route** — in `handler/apply_suggestions.go`: add `ApplyReviewClearedMerges(...)` to the `Applier` interface (:21); add `HandleApplyReviewCleared` mirroring `HandleApplyHubName:124` (decode `{project_id, dry_run}`, `authorizeBodyProjectID`, call the service, return `{applied, needs_review, errors, manifest}` reusing `applyHubNameResponse` shape); register `mux.HandleFunc("POST /api/v1/internal/resolution/apply-review-cleared", h.HandleApplyReviewCleared)`. No `main.go` change if the same `ApplySuggestionsHandler`/service instance is reused (verify — the applier is the same `ApplySuggestionsService`).

- [ ] **Step 5: run + build**
```bash
go test -race ./internal/service/ -run TestApplyReviewCleared
go build ./... && go test ./internal/handler/ -run ApplyReviewCleared
```

- [ ] **Step 6: commit**
```bash
git add internal/service/apply_suggestions.go internal/handler/apply_suggestions.go cmd/kg-server/main.go internal/service/apply_suggestions_test.go
git commit -m "feat(daab): ApplyReviewClearedMerges (reviewed fuzzy-hub bypass applier, max-blast ceiling)"
```

---

## Task 4: Precision sampler — retarget to the hub population

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/resolution/fuzzy_sample_cli.py`
- Test: `ennam.kg.python/tests/resolution/test_fuzzy_sample.py` (extend if needed)

**Interfaces:** add `--decision` to target `review_cleared`/`needs_review` (default `suggested`); stricter default thresholds for the hub run.

- [ ] **Step 1: implement** — in `fuzzy_sample_cli.py`, thread a `decision` param into `_load_band_async` (`WHERE ms.decision = $2` instead of the hardcoded `'suggested'`) and add `--decision` (default `suggested`) + raise the hub defaults via args (`--random-threshold 0.97 --targeted-threshold 0.93` at call time; keep code defaults). No new pure logic → the existing `is_danger_pair`/`wilson_lcb` tests still cover it; add a one-line test that `_load_band` query builds with the passed decision if the loader is refactored to be testable, else rely on the runbook.

- [ ] **Step 2: run existing tests** — `uv run pytest tests/resolution/test_fuzzy_sample.py -v` (still PASS).

- [ ] **Step 3: commit**
```bash
cd ennam.kg.python
git add src/ennam_kg/resolution/fuzzy_sample_cli.py
git commit -m "feat(daab): fuzzy_sample_cli --decision param for the hub population"
```

---

## Task 5: Operational runbook — partition → review → gate → apply

**Files:** none (operational). Record outputs.

- [ ] **Step 1: Step-0 verify** — re-confirm the band: `SELECT count(*), count(DISTINCT proposed_canonical_id) FROM merge_suggestions WHERE decision='needs_review' AND reason<>'exact normalized name match';` (expect ~4044 / ~1915).

- [ ] **Step 2: Partition (dry-run then apply)** — `KG_DATABASE_URL=... uv run python -m ennam_kg.resolution.hub_partition_cli --project <PID> --dry-run` (see typo vs danger split), then without `--dry-run` (flips typo → `review_cleared`).

- [ ] **Step 3: Human review of the danger stratum (per-canonical)** — query the remaining `needs_review` grouped by `proposed_canonical_id`; for each canonical, confirm all members are the SAME entity. Approved rows → `UPDATE merge_suggestions SET decision='review_cleared' WHERE id IN (...)`. Reject genuinely-distinct pairs (`decision='rejected'`). Record patterns.

- [ ] **Step 4: Precision gate** — `uv run python -m ennam_kg.resolution.fuzzy_sample_cli --project <PID> --decision review_cleared --draw hub_sample.csv --random-threshold 0.97 --targeted-threshold 0.93`; human adjudicate `same_entity`; `--score hub_sample.csv --random-threshold 0.97 --targeted-threshold 0.93`. **PASS required before apply.** FAIL → tighten the de-diacritic gate / expand review; do NOT apply.

- [ ] **Step 5: Dry-run manifest** — `curl -XPOST .../apply-review-cleared -d '{"project_id":"<PID>","dry_run":true}'`; review the per-canonical manifest (esp. the highest-degree groups). Note which canonicals hit `fuzzyHubMaxBlastCeiling` (they route back to needs_review → give them explicit human sign-off first if you want them merged).

- [ ] **Step 6: Apply** — `curl -XPOST .../apply-review-cleared -d '{"project_id":"<PID>","dry_run":false}'`. Expect `applied` ≈ cleared count, `needs_review` = the ceiling-routed, `errors` empty.

- [ ] **Step 7: Re-embed (embedding consumers) + verify** — set `re_embed_pending=true` on applied canonicals (`UPDATE knowledge_nodes SET properties = jsonb_set(properties,'{re_embed_pending}','true') WHERE id IN (<applied canonicals>)`) so the Python embed worker recomputes; **Step-2 needs nothing** (graph/IDF self-updates). Verify: dup-name count drops; the "UBND tỉnh Trà Vinh" variants consolidate; `kg_document_shared_entities` returns one canonical for two docs mentioning an alias-pair. Re-sample ~50 applied merges for false merges (target 0); un-merge any via the manifest.

- [ ] **Step 8: Checkpoint** — Serena checkpoint; update `mem:backlog/daab-fuzzy-alias-merge-B` + `mem:backlog/daab-entity-resolution-corpus-rerun`; record the gate LCBs + any rejected pairs.

---

## Self-Review notes (author)

- **Spec coverage:** migration §7 → T1; discriminator §6 + partition §5 → T2; applier §8 (clone, ceiling, review_cleared source) → T3; precision gate §9 → T4 + T5 Step 4; state machine + review §5/§7 → T2/T5; re-embed §10 → T5 Step 7; reversibility §11 → T5 Step 7. All covered.
- **Verified anchors:** constraint name `merge_suggestions_decision_check`; `ApplyHubNameMerges` structure (byCanon + degree-once + processSuggestion bypass) cloned; `Applier` interface + `HandleApplyHubName` + `applyHubNameRequest/Response` mirrored; `ListByProject(projectID, decision, limit, offset)`; `UpdateDecision`; asyncpg + `KG_DATABASE_URL` + `_normalize`; `đ` not NFD-decomposed (explicit fold); `is_danger_pair` NOT the auto-clear gate.
- **Type consistency:** `ApplyReviewClearedMerges(ctx, projectID, dryRun) (ApplyResult, HubMergeManifest, error)` matches `ApplyHubNameMerges`; reuses `HubMergeManifest`/`HubMergeGroup`; handler reuses `applyHubNameResponse`.
- **Confirm at execution:** `fuzzyHubMaxBlastCeiling=40` is a first guess — tune from the dry-run manifest's degree distribution (the high-value "UBND Trà Vinh" hub may sit above it → then it needs one explicit human sign-off, which is acceptable). The precision thresholds (0.97/0.93) tune from the first scored run.
