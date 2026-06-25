# Checkpoint: backend-dev — 2026-06-23 (BA-031 Phase C — code phase)

## What was done
Executed BA-031 Phase C plan via subagent-driven development. All CODE tasks landed,
each task-reviewed (spec + quality) and a final whole-branch review (opus) = READY TO MERGE.

Prep (cleaned the dirty working tree into 2 labeled commits first):
- `4716071` fix(benchmark): merge_cli routes verify through AIClient(base_url,key) — the old
  `AIClient(settings=settings)` raised TypeError; prereq for the C.3 G2 sweep.
- `63a2b63` wip(extraction): DirectOpenAIClient extraction path + pass1 Gate-1 prop fixes +
  timeout/max_tokens bumps (this session's PDF-ingestion experiments; was uncommitted).

Phase C code (range 63a2b63..d7d5c5b, 6 commits, full resolution suite 107 passed):
- `2fa58b9` C.5 — retry merge-suggestion writes inside `create_merge_suggestion`
  (retry on httpx.RequestError + KGClientError>=500; NOT 4xx; 3 attempts, 0.5→1→2s backoff).
  New `Pass2Summary.suggestions_failed` counted distinctly + one loud WARN on wholesale loss.
- `16c0612` chore — removed dead test helper (review finding).
- `9051d86` C.1 — dedup symmetric intra-doc pairs by unordered node-id frozenset before verify
  (key by ID-pair never name; distinct same-name nodes kept). ~30-44% fewer fetch+CE+LLM ops.
- `ff1be2b` C2-T1 — `build_batch_verify_request`/`parse_batch_verify_response` in verify.py,
  keyed by pair_id (raise on top-level failure; per-item malformed → skipped).
- `4479639` C2-T2/T3 — `route_pairs` Stage-3 batches the uncertain band by `verify_batch_size`
  (default 1 = byte-for-byte today's behavior). Missing item → single re-verify; whole-batch
  failure → full single fallback. Fixed latent identity bug (failure PairOutcome now carries
  REAL node ids, not "",""). Wired Deps/config.py/deps_factory/.env.example.
- `d7d5c5b` test — pinned identity fix on the batch per-pair-fallback path (review I1).

## Files changed (all in ennam.kg.python)
- src/ennam_kg/resolution/{pass2.py, verify.py, deps_factory.py}
- src/ennam_kg/config.py (resolution_verify_batch_size=1), .env.example
- packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py (retry)
- src/ennam_kg/benchmark/merge_cli.py (prep), src/ennam_kg/{ai_client,extraction,worker} (prep wip)
- tests/resolution/{test_pass2_phasec_batch.py(new), test_verify_batch.py(new), +pass2/kg_client tests}

## Current state
- Code COMPLETE, reviewed (opus: Ready to merge, no Critical/Important; 4 deferrable Minors).
- batch_size still DEFAULT 1 → no behavior change in production yet; it's a confirmed G2 no-op.
  The actual throughput win requires raising verify_batch_size AFTER C.2-T4 G2 validation.
- Docker stack healthy; host HF cache has bge-reranker-v2-m3 + multilingual-e5-small.
- SDD ledger: .superpowers/sdd/progress.md (Phase C section). Per-task briefs/reports/diffs there.

## Operational gates — DONE (ran on ba031-benchmark-vi-v1 = c37146f1..., reject=0.20)
- Baseline batch=1: GATE PASS P=1.000 R=0.927, LLM band=110, blocked=462, GT=82.
- C.3 reject sweep {0.20,0.25,0.30}: band 110/102/98; recall 0.927/0.902/0.927 (FN 6/8/6 =
  LLM noise, NOT a threshold effect — CE separates VI so cleanly the [0.20,0.30] band is
  ~empty). DECISION: KEEP reject=0.20. Not worth a precision risk on unseen technical/antonym
  content for an ~11% within-noise saving.
- C.2-T4 batch=8 (clean re-run): GATE PASS P=1.000 R=0.939, band=107, 1 whole-batch fallback,
  0 single failures. ~5x fewer LLM calls (110 -> ~22). Batch verify is VALIDATED on VI.
- CONFIG: resolution_verify_batch_size kept DEFAULT=1. batch=8 proven on VI ONLY; do NOT flip
  the production default until an OMNI batch=8-vs-batch=1 suggestion-diff confirms no
  attention-dilution merges on hard content (Phase B antonym lesson).
- LESSON: a backgrounded `docker compose ... exec psql DELETE` loop silently no-op'd → 252
  bench nodes accumulated → GT collapsed → invalid batch4/batch8 numbers (discarded). ALWAYS
  verify count==0 after cleaning the bench project. Direct (non-loop) cleanup works.

## INFRA (must-know for next session)
- kg-server is on host port **8082** (docker-compose.yml modified, uncommitted), NOT 8080.
  Benchmark + OMNI must use KG_API_URL=http://localhost:8082. Env keys (KG_API_KEY/GO_API_KEY)
  live in the WORKSPACE-ROOT .env, not ennam.kg.python/.env.
- Benchmark project = ba031-benchmark-vi-v1 (c37146f1...). OMNI/doc project =
  ba031-pdf-test-verifone (1e69492a...) — 786 active nodes, the OMNI doc lives here.

## OMNI re-resolve — DEFERRED by user (2026-06-23). Worker-rebuild prerequisite:
The RUNNING worker container has OLD baked code (verified: MISSING C.5 retry + C.1 dedup).
Worker runs the BAKED image, not the /repos mount. So OMNI on the current worker would be
UNPROTECTED — repeats the run-001 total-loss risk. Before enqueuing OMNI:
1. `docker compose up -d --build worker` (bakes Phase C: C.5/C.1/C2 — they are committed).
2. Re-copy bge + e5 caches into the FRESH container's HF_HOME (/tmp/huggingface/hub) and
   chown — a rebuild loses them (ephemeral). Verify reranker + embed model load.
3. Worker has RESOLUTION_VERIFY_BATCH_SIZE unset → batch=1 (the safe path; run OMNI here first).
4. Enqueue: LPUSH ennam:extraction '{"type":"resolve_document","project_id":"1e69492a-...",
   "doc_id":"fbfff4ed-...","run_id":"ba031-run-002"}' (confirm full doc_id first).
5. Apply is separately gated; OMNI produces SUGGESTIONS only — review before apply.

## Blockers / Risks
- ⚠️ SECURITY: user will self-rotate BytePlus API key `ark-d618f...`. If rotated, the paid
  benchmark/OMNI runs need the new key in env before they'll authenticate.
- Model-cache fragility on worker rebuild (Phase B T7 still deferred — docker cp workaround).
