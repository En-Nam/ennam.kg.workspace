# BA-031 Resolution Turn-On Runbook (shadow → apply → GA)

> **Type:** Operational runbook (human-in-the-loop), NOT a code-implementation plan.
> The apply pipeline is **already built** (Phase 8a/8b/8c/8d, 2026-06-18) and shipped **OFF** (`resolution.apply_mode = "shadow"`). This runbook is the procedure to validate the data gates and **flip the switch** so cross-document entity resolution (BA-031 FR-005) actually merges duplicates and produces the cross-document entity edges that BA-033 (community detection / GraphRAG retrieval) depends on.

**Created:** 2026-06-22
**Owner:** _(assign — needs a human with staging DB access + benchmark-labelling judgement)_
**Related:** BA-031 (`ennam.kg.requirements/documents/phase8/BA-031-...`), implementation plan `2026-06-18-ba-031-phase8d-auto-merge-ga.md`, BA-033 (downstream consumer), memory `ba031-resolution-thresholds-gates`.

---

## 🚧 PREREQUISITE — the suggestion-PRODUCER chain is NOT wired (verified 2026-06-22)

**This runbook flips a switch on machinery that currently has no input.** Verified against code:

- Pass 1 **closed-schema** extraction (`extraction/pass1.py`) does **NOT** run in the live pipeline — the worker calls the simple open-schema `extract_draft` (`ingestion/pipeline/engine.py:167,232`), so ingest produces old `concept` nodes, not BA-031 `Person`/`Organization` entities.
- The Pass 2 orchestrator `run_pass2_shadow()` (`extraction/pass2.py:113`) is real code but has **zero production callers**.
- The worker's `resolve_document` handler is an explicit **stub** (`worker.py:203-212`, "full implementation in Phase 8b"), and the Go API **never enqueues** `resolve_document` (`handler/extraction.go:267` enqueues only `extract_document`).

**Consequence:** nothing writes `merge_suggestions`. Flipping `apply_mode=apply` today yields `{"applied":0}` — apply has nothing to consume.

**→ A net-new implementation phase (Phase A) must precede this runbook:** see **`2026-06-22-ba-031-phaseA-producer-wiring.md`** — wires Pass 1 closed-schema extraction into live ingest, implements the `extract_document`/`resolve_document` handlers (call `run_pass1`/`run_pass2_shadow`), adds the Go entity-listing endpoint + doc-level resolve trigger. Its E2E test (a 2-doc shared-entity ingest producing ≥1 `merge_suggestions` row in shadow) is exactly the precondition Steps 4/7 below assume. Only after Phase A's DoD is green do these steps make sense. This runbook is the **turn-on procedure**, NOT the wiring work.

---

## Why this runbook exists

| | |
|---|---|
| **Built?** | ⚠️ **Partial.** The APPLY path is built + tested: `MergeService` (8c), `ApplySuggestionsService` (8d, degree-gated), `POST /api/v1/internal/resolution/apply`, un-merge, cost ceiling, telemetry. The PRODUCER path (Pass 1 live wiring + Pass 2 orchestration/trigger) is **NOT wired** — see the PREREQUISITE block above. |
| **On?** | ❌ No. `resolution.apply_mode: shadow` (`ennam.kg.go/config/config.yaml:1559`). The apply endpoint is a logged no-op until flipped to `"apply"`. |
| **What blocks the flip?** | The **data gates are PENDING-DATA**: `ennam.kg.python/benchmarks/ba031/vi_blocking_v1.json` is an **empty skeleton** (`entities: 0`, `owner: "TODO-ASSIGN"`). No labelled VI dataset → no real precision/recall PASS → GA not declarable. |
| **Tripwire** | `TestBA031GA_Step5_GADecisionGuard` (`ennam.kg.go/internal/integration/ba031_ga_test.go:541`) **fails the integration suite** if `apply_mode != "shadow"`. ⚠️ This file is behind `//go:build integration`, so it is **NOT run by `make test`** — it runs only via `go test -tags=integration ./internal/integration/...` (CI, needs `KG_TEST_DB_URL`). It must be updated in the SAME commit as the flip. |

> **Precondition for any apply (Step 4/7):** `POST /api/v1/internal/resolution/apply` only **consumes pre-existing `merge_suggestions`** rows (`decision='suggested'`); it does NOT generate them. Suggestions are produced upstream by Pass 1 extraction + Pass 2 candidate generation (`POST /api/v1/internal/resolution/candidates` → `POST /api/v1/internal/resolution/suggestions`). Ensure suggestions exist on the target project before Step 4 or Step 7, otherwise apply is a trivial no-op (0 applied) regardless of `apply_mode`.

**Consequence today:** because resolution never applies, every document's entities stay distinct — there are **no cross-document entity edges** to cluster. BA-033 cannot deliver value until this runbook completes. This is the real bottleneck, not missing spec.

---

## ⚠️ Threshold discrepancy to reconcile BEFORE Step 4 (Rule 7 — surface conflict)

Two sources disagree on the merge-precision bar. **Resolve which is authoritative before declaring GA — do not average them.**

| Source | Stated gate |
|---|---|
| BA-031 **NFR-256** | merge **precision ≥ 0.90** (at most 10% wrong merges); NFR-257 recall ≥ 0.80 |
| Tripwire test message (`ba031_ga_test.go:580,595`) | **precision ≥ 0.74, FP-rate ≤ 10%, F1 ≥ 0.75** |

The `0.74` in the test looks suspiciously like the `resolution_sim_threshold` (0.74), not a precision target. **Action:** the owner confirms the intended precision gate (NFR-256's 0.90 is the documented requirement) and, if the test message is wrong, corrects it as part of Step 6. Treat **precision ≥ 0.90 / recall ≥ 0.80 / FP-rate ≤ 10%** as the working target unless the owner decides otherwise and records why.

---

## Gate conditions (all must be GREEN before flipping)

```
G1  8b blocking-recall   ≥ 0.90 @ K=10, threshold ∈ [0.72, 0.75]
G2  8c merge precision   ≥ 0.90  AND  recall ≥ 0.80  (see discrepancy note)
G3  un-merge reversibility — byte-equivalent restore (already drilled; re-confirm)
G4  cost ceiling enforced before any LLM batch (per-run + per-doc)
G5  degree-gating verified — hubs (degree ≥ 10) NEVER auto-merge (NFR-256 leaf-only)
G6  shadow dry-run on staging reviewed — the would-merge set is sane (no obvious false merges)
```

G4/G5 are already PASS in `TestBA031GA_Step1/Step2`. G1/G2 are PENDING-DATA. G3 is drilled. G6 is new in this runbook.

---

## Procedure

### Step 1 — Populate the VI benchmark dataset (THE blocker)

**Owner task, requires judgement — cannot be automated.** Populate `ennam.kg.python/benchmarks/ba031/vi_blocking_v1.json` per `benchmarks/ba031/schema.md`:

- **≥ 30 gold entity groups** (clusters of names that refer to the same real entity) and **≥ 50 labelled VI candidate pairs** (same / different).
- Coverage required (these are the hard cases resolution must get right): **honorifics** ("ông A" / "Mr. A" / "Nguyễn Văn A"), **diacritics ↔ romanised** ("Nguyễn" / "Nguyen"), **abbreviations** ("AIO Link" / "AIOLink" / "AIO-Link"), **organisation variants**.
- Set `_meta.owner` to a real owner (not `TODO-ASSIGN`).

**Pass criteria:** `entities ≥ 30 groups`, `≥ 50 pairs`, schema-valid JSON.
**If skipped:** STOP. Every downstream gate is meaningless without this. (Rule 12 — do not fake a PASS on an empty skeleton.)

### Step 2 — Run the 8b blocking-recall gate (G1)

```bash
cd ennam.kg.python
uv run python -m ennam_kg.benchmark.cli \
  --dataset benchmarks/ba031/vi_blocking_v1.json \
  --project <staging-project-uuid> \
  --out reports/ba031-8b-blocking-$(date +%Y%m%d-%H%M%S).md
```

**Pass criteria:** CLI prints `GATE PASS: recall ≥ 0.90 @ K=10` with the best threshold in `[0.72, 0.75]`.
**If FAIL:** do NOT flip. Tune `resolution_sim_threshold` within the band / `resolution_top_k`, or improve embeddings; re-run. A failing blocking recall means Pass 2 never even sees the true duplicates.

### Step 3 — Run the 8c merge precision/recall gate (G2)

> **Verify the runner first.** The CLI module above is the **8b** blocking-recall runner. Confirm the 8c precision/recall benchmark entry point (Task 9/Task 10 from the 8c plan — see checkpoint `backend-dev-2026-06-18-ba031-phase8c-task10.md`) and its exact command before running. If it is a separate CLI subcommand or pytest target, record it here once confirmed.

**Pass criteria:** merge **precision ≥ 0.90 AND recall ≥ 0.80** (reconcile vs the tripwire message per the discrepancy note).
**If FAIL:** do NOT flip. Raise `merge_confidence_threshold` (default 0.75) to trade recall for precision, or improve the Pass-2 verifier prompt; re-run. Wrong merges propagate graph-wide — precision is the non-negotiable gate.

### Step 4 — Review the would-merge set on staging (G6)

> ⚠️ **Do NOT use the apply endpoint for this.** In `shadow` mode `POST .../resolution/apply` is a pure no-op — it returns `{"applied":0,"needs_review":0,"mode":"shadow"}` and computes **no** would-merge list (`apply_suggestions.go:89-100`). There is also **no GET endpoint** that lists suggestions. The would-merge set lives in the `merge_suggestions` table; inspect it directly with SQL.

First ensure candidate generation has populated suggestions on the staging project (see Precondition above). Then review the pending merges via the DB shell:

```bash
cd ennam.kg.go && make db-shell    # opens psql
```
```sql
-- pending merges that an "apply" run WOULD act on
SELECT node_a_id, node_b_id, proposed_canonical_id, confidence, reason, decision
FROM merge_suggestions
WHERE project_id = '<staging-project-uuid>' AND decision = 'suggested'
ORDER BY confidence DESC;
```

**Pass criteria:** a human reviews the `suggested` rows; no obviously-wrong merges (e.g. two distinct people collapsed); high-degree (hub) pairs are expected to land in `needs_review` at apply time (degree gate), not auto-merge.
**If suspicious merges appear:** tighten thresholds (`merge_confidence_threshold`) and return to Step 3. This is the last human checkpoint before real mutation.

### Step 5 — Re-confirm reversibility (G3)

> ⚠️ The reversibility test is in the **`integration`-tagged** package; `make test` skips it. Run it explicitly with the build tag and a test DB:

```bash
cd ennam.kg.go
KG_TEST_DB_URL='postgres://...test-db...' \
  go test -tags=integration ./internal/integration/ -run TestBA031GA_Step4_Reversibility -v
```

**Pass criteria:** `TestBA031GA_Step4_Reversibility` PASS — a merge can be un-merged to a byte-equivalent state. This is the safety net for any wrong merge that slips through.

### Step 6 — Flip the switch (ATOMIC commit)

Only when G1–G6 are all green. In **one commit**:

1. `ennam.kg.go/config/config.yaml:1559` — `apply_mode: shadow` → `apply_mode: apply`.
2. `ennam.kg.go/internal/integration/ba031_ga_test.go` — update `TestBA031GA_Step5_GADecisionGuard`: it currently **fails** if `apply_mode != "shadow"`. Change it to assert the GA-declared posture (expect `"apply"`) and update the decision-table log (`Step 5 — GA declaration: DECLARED`, record the passing gate numbers + date + owner). If the precision-threshold message was wrong (discrepancy note), correct it here too.
3. Record the GA decision: which gates passed, their measured values, `degree_threshold`, cost ceilings, dataset version, and owner — in the commit body and/or the BA-031 doc status (Draft → declare 8d GA).

```bash
cd ennam.kg.go && make lint build      # source-level checks
# The GA guard is integration-tagged — run it explicitly (it must now expect "apply"):
KG_TEST_DB_URL='postgres://...test-db...' \
  go test -tags=integration ./internal/integration/ -run TestBA031GA -v
```

> Note: `make test` alone will NOT catch a stale tripwire — the guard only runs under `-tags=integration`. Ensure CI runs the integration suite, or run it locally as above, before merging the flip.

**Commit:** `feat(ba031-8d): declare auto-merge GA — flip apply_mode to apply (gates G1-G6 green)`
**Note:** `apply_mode` is a DB-overridable runtime setting (system_settings overrides YAML, 60s cache); the YAML flip + tripwire update is the source-of-truth change, but confirm no stale `system_settings` row pins it back to `shadow`.

### Step 7 — Post-flip verification (the actual goal)

After deploy, run resolution on a real multi-document project and confirm the thing this whole effort is for:

```bash
# trigger apply on a real project, then verify cross-document entity edges now exist
curl -s -XPOST $PROD/api/v1/internal/resolution/apply -H "Authorization: Bearer $ADMIN_KEY" \
  -d '{"project_id":"<project-uuid>"}'
```

**Pass criteria:**
- The apply response shows `applied > 0` (merges happening).
- A previously-duplicated entity (e.g. "AIO Link" / "AIOLink" from two documents) is now **one canonical node** with both documents in its `provenance[]`, and its edges span both source documents.
- Spot-check `merge_suggestions` for `needs_review` rows (hubs) — these await human confirmation, not silent merge.

**Monitor:** wrong-merge rate over the first batches; if it exceeds the ~10% NFR-256 tolerance on leaves, roll back (Step 8) and re-tune.

### Step 8 — Rollback plan

If post-flip results are bad:

1. Set `apply_mode` back to `shadow` (config or `system_settings`) — stops further merges immediately (fail-closed gate).
2. Un-merge any wrong merges via `POST /api/v1/internal/resolution/unmerge` (8c, byte-equivalent restore — registered `cmd/kg-server/main.go:385`).
3. Revert the tripwire test change if reverting the GA declaration.
4. Re-tune thresholds, return to Step 3.

---

## Definition of Done

- [ ] `vi_blocking_v1.json` populated (≥30 groups / ≥50 VI pairs, owner assigned) — Step 1
- [ ] G1 8b blocking-recall PASS (≥0.90 @K=10, threshold in band) — Step 2
- [ ] G2 8c precision/recall PASS (≥0.90 / ≥0.80, discrepancy reconciled) — Step 3
- [ ] G6 staging shadow dry-run reviewed, would-merge set sane — Step 4
- [ ] G3 reversibility re-confirmed — Step 5
- [ ] `apply_mode: apply` + tripwire test updated, in one commit; `make lint build` + `go test -tags=integration ./internal/integration/ -run TestBA031GA` green — Step 6
- [ ] Post-flip: cross-document entity edges verified on a real project; needs_review hubs intact — Step 7
- [ ] Rollback procedure validated/understood — Step 8
- [ ] BA-031 8d GA recorded (gates, values, owner, date); memory `ba031-resolution-thresholds-gates` updated to GA-DECLARED

## Risks

- **Wrong merges propagate graph-wide** (NFR-256) — mitigated by G2 precision gate + degree-gating (hubs never auto-merge) + reversible un-merge. The precision gate is the load-bearing control; do not lower it to force a PASS.
- **Empty/weak benchmark → false confidence** — Step 1 quality determines whether every later gate is meaningful. Garbage dataset = garbage GA.
- **Threshold discrepancy** (0.74 vs 0.90) — unreconciled, this could declare GA at the wrong bar. Resolve in Step 6.
- **Cost** — cost ceiling (G4) caps spend before batches; Claude Max reports cost=0 and bypasses BA-009, so the per-run/per-doc ceiling is the only money guard.

## Downstream

Completing this runbook unblocks **BA-033** (OQ-033-2 hard-blocks community clustering while `apply_mode = shadow`). Once resolution is applied and producing a real resolved cross-document graph, BA-033's community detection + GraphRAG retrieval can be specced/implemented against real data.
