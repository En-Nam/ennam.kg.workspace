# Checkpoint: business-analyst — 2026-06-22

## What was done
- Cross-document RAG/KG discussion → mapped 4 mechanisms (shared-entity, chunk-sim, entity resolution, community detection) onto Ennam KG.
- Authored **BA-033** (Cross-Document GraphRAG Retrieval) — chunk-sim links + community detection/summaries + graph-aware local/global retrieval. NFR-276→285. Added to phase8/README.
- Authored **BA-031 turn-on runbook** (shadow→apply→GA) and **Phase A plan** (wire the suggestion-producer chain).
- **Critical discovery (verified):** the suggestion-PRODUCER chain is NOT wired — flipping apply_mode alone yields applied:0. Pass1 closed-schema not in live pipeline (uses extract.py), Pass2 `run_pass2_shadow` has no caller, `resolve_document` worker is a stub, Go never enqueues resolve. → Phase A is net-new code that must precede the runbook.
- **Verified both plans against code; fixed real errors** (see below).

## Files changed
- `ennam.kg.requirements/documents/phase8/BA-033-cross-document-graphrag-retrieval.md` (new) + phase8/README.md
- `docs/superpowers/plans/2026-06-22-ba-031-resolution-turn-on-runbook.md` (new; verified+fixed)
- `docs/superpowers/plans/2026-06-22-ba-031-phaseA-producer-wiring.md` (new; verified+fixed)
- memory `ba031-resolution-thresholds-gates.md` (producer-chain gap + threshold discrepancy)

## Verified corrections (do not regress)
- Runbook: shadow apply is no-op (no would-merge list) → use SQL on merge_suggestions; integration tests behind `//go:build integration` (NOT in `make test`); auth = `Authorization: Bearer`; threshold discrepancy 0.74(test) vs 0.90(NFR-256) UNRESOLVED.
- Phase A E1: `get_entities` is SYNC (pass2.py:133 no await) → sync HttpxEntitiesClient, not async KGClient.
- Phase A E2: bare `GET /api/v1/nodes/{id}` does NOT exist → must add (Task 3 Step 0) for chunk hydration.
- Confirmed: closed-vocab migration 000061 LANDED; /candidates default min_similarity=0.82; complete_json absent (add).

## Current state
- 3 artifacts ready (all Draft/plan, NOT implemented). No Go/Python code changed. Run order locked: **Phase A → turn-on runbook → BA-033**.

## Next steps
- Start Phase A Task 1 (TDD). In parallel: owner can begin labelling vi_blocking_v1.json (runbook Step 1).
- When reaching BA-033: write its spec + plan (not yet done).

## Blockers / Risks
- Phase A D2 fan-in (per-chunk extract → per-doc resolve) idempotency is the load-bearing risk.
- Threshold discrepancy (0.74 vs 0.90) must be reconciled before GA.
- Plan line-number citations not all line-by-line verified — agents must re-read files at implement time (TDD will surface drift).
