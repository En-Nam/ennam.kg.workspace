# Checkpoint: backend-dev — 2026-06-23 (BA-031 Phase B)

## What was done
- Implemented BA-031 **Phase B** — 3-stage verify pipeline (rule → cross-encoder → LLM)
  to cut LLM calls ~86% and speed resolution from ~20min to ~3-4min per doc.
  - `resolution/rules.py` (new) — Stage 1 rule filter (exact normalized-name match,
    honorific strip). High-sim-same-type auto-merge REMOVED after G6 (see below).
  - `embeddings/local_reranker.py` (new) — `LocalReranker` wrapping bge-reranker-v2-m3.
  - `resolution/pass2.py` — extracted shared `route_pairs()` (used by worker AND G2
    benchmark); Phase 2 split into 2a rule / 2b cross-encoder / 2c LLM (uncertain only).
  - `resolution/verify.py` — `entity_text()` = name + aliases ONLY (description is
    noise for the reranker); lifted `extract_entity_fields()` to module level.
  - `benchmark/merge_cli.py` — now routes through `route_pairs()` so G2 measures the
    deployed pipeline (was LLM-only → would have validated the wrong path).
  - config: `resolution_crossencoder_*`, `resolution_rule_sim_high`.
- **Model choice**: jina-reranker-v2 rejected (remote code incompatible with pinned
  transformers). Switched to `BAAI/bge-reranker-v2-m3` (stock XLM-RoBERTa).
- **G2 gate**: PASS, reproducible on clean data — **precision 1.000, recall 0.915**
  (after removing high-sim rule; was 0.974 with it). Evolution: description-in CE
  (P0.824/R0.512) → name+aliases (R fixed) → CE auto-merge OFF (P up) → high-sim rule
  removed (P=1.000).
- **G6 human review**: caught the high-sim rule auto-merging ANTONYMS —
  `com.nuvei.PRE_PROCESSING` vs `POST_PROCESSING` (sim 0.981), `pre-/post-processing`.
  The VI benchmark (people/orgs) never exercised this, so G2 passed while production
  produced wrong merges. Removed the rule → those defer to LLM. Verified 0 pre/post
  pairs in final production suggestions.
- 3rd-party doc (204c82e1) re-resolved via tuned+fixed pipeline: **99 suggestions**
  (71 exact-name rule @0.990, 28 LLM @0.951), 86 LLM calls (14% of 612).

## Files changed (committed: cab6f86, 0232f22, f58aba7, e90361f on ennam.kg.python)
- src/ennam_kg/resolution/{rules.py(new), pass2.py, verify.py, deps_factory.py}
- src/ennam_kg/embeddings/local_reranker.py (new)
- src/ennam_kg/benchmark/merge_cli.py, config.py, .env.example
- tests/resolution/{test_rules.py, test_pass2_phaseb.py, test_verify_phaseb.py} (new)
- 77 resolution tests pass.

## Current state
- Gates: G1 PASS, G2 PASS (P=1.000/R=0.915), G3 drilled, G4/G5 PASS, G6 clean (tech).
- **GA DECLARED 2026-06-23**: `apply_mode` flipped shadow→apply (config.yaml + tripwire
  test `TestBA031GA_Step5` updated, commit `057e7ea` on ennam.kg.go). kg-server restarted.
  No system_settings override (YAML authoritative).
- **Apply RUN on 3rd-party suggestions** (Step 7 smoke test): applied=34, needs_review=0.
  Verified coherent + no corruption — 34 nodes superseded with valid `merged_into`
  pointers (e.g. 3× "Nuvei" → canonical "NUVEI TECHNOLOGIES" active). Degree-gate uses
  LIVE degree (apply_suggestions.go ignores shadow's degree_max=0). Reversible via un-merge.
  NOTE: apply was accidentally called twice — 2nd call's 65 "errors" are benign no-ops
  (service refuses to re-merge already-superseded / self-merge); not corruption.
- **PARTIAL dedup**: project still has ~363 active duplicate nodes (139 titles) — mostly
  OMNI/other-doc entities. The 99 suggestions only covered the 3rd-party doc. OMNI (716
  entities) was NEVER successfully resolved (its 704 merges lost to a kg-server restart
  during the write burst). 65 suggestions remain 'suggested' (redundant within collapsed
  clusters; would error on re-apply).
- Worker deployed with tuned+fixed config (commits cab6f86/0232f22/f58aba7/e90361f on
  ennam.kg.python). bge+e5 caches copied into the running container (ephemeral).

## Known issues / infra
- **bge + e5 models do NOT survive a worker image rebuild**: fresh container fails to
  load bge (st 5.x AutoProcessor 404 bug; host works via cached `.no_exist` markers).
  WORKAROUND used: `docker cp ~/.cache/huggingface/hub/models--* → container` + chown.
  PROPER FIX (TODO): bake HF cache into Docker image (T7) so rebuilds are self-contained.
- Transient DNS blips to huggingface.co observed; online model load retried OK.

## Next steps (NEXT SESSION — Phase C)
GA is done; session paused here intentionally (long session). Resume in a FRESH session
to run **Phase C** (`docs/superpowers/plans/2026-06-23-ba031-phaseC-resolution-throughput.md`)
to finish deduplicating the project and harden large-doc resolution. Order:
1. **C.5 write-retry FIRST** (plan L109-146) — retry `create_merge_suggestion` on
   `httpx.RequestError` + `KGClientError`≥500, NOT 4xx. Without it, re-running OMNI
   risks losing the whole pass again (it already happened once).
2. Re-run OMNI Channel doc (fbfff4ed, 716 entities) via the tuned worker → fresh
   suggestions. Enqueue: `LPUSH ennam:extraction '{"type":"resolve_document",
   "project_id":"1e69492a-...","doc_id":"fbfff4ed-...","run_id":"ba031-run-002"}'`.
   ⚠️ First ensure bge+e5 caches are present in the worker container (copy from host
   `~/.cache/huggingface/hub/` if the container was rebuilt) — see Known issues.
3. Apply again → collapse the remaining ~363 duplicates. (Re-run apply is idempotent-ish:
   already-merged pairs error as benign no-ops.)
4. C.1 dedup + C.3 reject-sweep + C.2 batch — only when ingesting the larger 35-doc corpus.

- **SECURITY (outstanding): user will self-rotate BytePlus API key `ark-d618f...`.**

## Blockers / Risks
- **Model-cache fragility on worker rebuild** (workaround: docker cp HF cache + chown;
  PROPER FIX is Dockerfile bake / volume mount — Phase B plan T7, still deferred).
- Benchmark entity cleanup MUST use `created_by` COLUMN (not properties) — 420 stale
  entities had polluted earlier G2 runs before this was found.
- Pairwise-suggestion apply on multi-instance clusters is order-dependent + incomplete
  in one pass (transitive cluster-merge would be cleaner; noted, not blocking).
