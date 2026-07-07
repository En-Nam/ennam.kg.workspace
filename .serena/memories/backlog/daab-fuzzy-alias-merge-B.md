# Backlog — B: fuzzy alias merge (ready to execute)

**Filed:** 2026-06-30 · **Branch:** `task/implement_docs_sync` (already merged to main). · Next tier of entity-resolution after 1a/1b/Step-2 (all done + merged).
**Spec:** `docs/superpowers/specs/2026-06-30-daab-fuzzy-alias-merge-design.md` · **Plan:** `docs/superpowers/plans/2026-06-30-daab-fuzzy-alias-merge.md` (both committed).

## What B is (one line)
Apply the **4695 parked fuzzy merge suggestions** (alias→canonical: "Bộ GTVT"↔"Bộ Giao thông vận tải", "UBND thị xã Duyên Hải"↔"Ủy ban nhân dân...", missing "và", diacritic typos) via the EXISTING gated `Apply` path, after a **stratified precision gate** passes. Tightens cross-doc linking + Step-2 relatedness.

## Decided (2-agent debate, data-resolved — do NOT relitigate)
- **Run the existing `ApplySuggestionsService.Apply(projectID, threshold)`** (`POST /api/v1/internal/resolution/apply` body `{project_id}`, gated `apply_mode=apply`). **Degree gate STAYS ON, no bypass** (fuzzy=similarity≠identity). `maxSuggestions=10000` → one call covers 4695.
- **Trust the parked verdicts; do NOT re-run Pass-2.** Data-confirmed: all `reason` are LLM judgments (not the deleted high-sim rule). No new discriminator, no `merge.go`/`pass2.py` change, no migration.
- **Net new code = ONE Python script** (`fuzzy_sample_cli.py`, asyncpg — NOT psycopg) + an operational runbook. Manifest = pre-apply SQL snapshot (no Go change).
- **Leaf-only; defer fuzzy HUBS** (0 hubs in backlog; degree gate auto-routes mid-batch accretion to needs_review).
- Reversible (`merge.go`: `merged_into`/`merge_undo` + **re-points edges** → that's why B IMPROVES Step-2: canonical accretes the aliases' doc-mentions).

## ⚠️ TWO HUMAN GATES (agent cannot/should not do these alone)
1. **Adjudicate ~200 pairs (Step 4).** The gate's whole point is an INDEPENDENT human check of the LLM's verdicts (CTO: letting the same LLM re-judge reproduces the bias that shipped the antonym bug). An agent may pre-fill a DRAFT, but the HUMAN's labels are the gate. Over-weight the `targeted`/danger stratum (cross-place/number diffs like "UBND Trà Vinh" vs "UBND Sóc Trăng").
2. **Apply (Step 6)** mutates the shared graph (AAA/LAAM read it). Reversible but consequential → run ONLY after the gate PASSES, with explicit human go.

## Verified anchors (re-verify counts; DB state changes)
- Parked band = `merge_suggestions WHERE decision='suggested' AND reason<>'exact normalized name match'` = **4695, all leaf, 0 hub, conf 0.95, sim 0.94, 0 NULL canonical** (Apply won't error).
- `all_suggested == fuzzy == 4695` (band = entire suggested pop; no reason-exclusion lister needed). If ever `>`, add `reason NOT IN (...)` lister (spec §7).
- **Trapdoor:** generic `/apply` would flush all 4695 (degree gate inert for leaf) but worker only auto-calls `/apply-exact-name` → dormant. Rule: **don't call `/apply` until the gate passes.**
- Driver = **asyncpg** (`$1::uuid`, `KG_DATABASE_URL`); `_normalize` keeps diacritics + splits on space (`is_danger_pair` `_NOISE` must match diacritic tokens).

## How to start (next session)
1. `mcp__serena__read_memory("backlog/daab-fuzzy-alias-merge-B")` + read the spec & plan.
2. Execute the plan: Task 1 (script + pytest) → Task 2 runbook (step-0 verify → snapshot manifest → `--draw` → **human adjudicate** → `--score` gate → **on PASS + your go: `/apply`** → post-verify dup-drop + re-sample 50 + Step-2 spot-check → re-embed → checkpoint).
3. Stack: kg-server :8082, postgres :5433 (`KG_DATABASE_URL=postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg`). Project `592c7ff7-9f6f-4cc5-9094-d9b3b685277e` (re-verify).

## After B — remaining roadmap
- **D — `sse-block-ordering-bug`** (P1, Python+Go) still open. (C monitoring-scope = already done.)
- Deferred: fuzzy HUBS · one-token-diff pre-filter (if targeted stratum fails) · wire fuzzy auto-apply into live pipeline · OCR-garbled entity cleanup. See `mem:backlog/daab-entity-resolution-corpus-rerun`.
