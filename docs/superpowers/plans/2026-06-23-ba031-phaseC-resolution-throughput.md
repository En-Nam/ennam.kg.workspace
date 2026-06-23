# BA-031 Phase C — Resolution Throughput (fewer LLM calls, same quality)

**Created:** 2026-06-23
**Depends on:** Phase B merged + GA decided (do NOT change verify logic mid-GA)
**Owner:** backend-dev
**Related:** Phase B plan `2026-06-23-ba031-phaseB-cross-encoder-verify.md`, runbook
`2026-06-22-ba-031-resolution-turn-on-runbook.md`, memory `ba031-resolution-thresholds-gates`

---

## Problem

Phase B already cut LLM calls ~86% (rule → cross-encoder → LLM). The residual
bottleneck on LARGE documents is the Stage 3 LLM band:

- OMNI Channel (716 entities → 6470 candidate pairs) → ~900-1300 LLM calls in the
  uncertain band → ~35-45 min, bounded by `verify_concurrency=10` × ~7s/call.
- Antonym-safe routing (Phase B removed the high-sim rule auto-merge) pushes MORE
  pairs to the LLM, so big technical docs feel this most.

**Goal:** cut the LLM-band call count further WITHOUT lowering G2 precision/recall
(precision ≥ 0.90, recall ≥ 0.80) and WITHOUT just cranking parallelism (which
trades load for speed — "ngốn hiệu năng"). Prefer doing LESS work over doing the
same work faster.

---

## Optimizations (ranked by leverage ÷ risk)

### C.1 — Dedup symmetric pairs before the LLM ⭐ (free, no quality change)

For an INTRA-document pair (both entities in the doc being resolved),
`run_pass2_shadow` Phase 1 emits it twice: entity A's ANN candidates yield (A, B),
and entity B's candidates independently yield (B, A). The same logical pair is then
fetched, cross-encoded, AND LLM-verified twice. (Cross-document pairs — A in this
doc, B only in another — appear once, since B is not in this doc's entity list; dedup
does not affect those.)

**Measured (3rd-party doc, 2026-06-23):** 99 merge rows collapsed to **55 unique
unordered ID-pairs** — i.e. **~44% of rows are pure A→B/B→A symmetry** (the rest are
genuine multi-instance pairs: one name with several distinct node IDs, e.g. node
`0688e5c4` paired with two different same-name nodes — those are NOT symmetry and
must each be kept). The symmetry fraction in the full `pending` list (612 pairs)
is similar, so deduping it roughly halves the intra-doc fetch + CE + LLM work.

**Change:** after Phase 1, dedup `pending` on `frozenset({entity["id"], node_b_id})`,
keeping the first occurrence (and its embedding similarity). The merge decision and
canonical-name pick for {A,B} are symmetric, so one evaluation suffices.

- **Expected:** ~30-44% fewer fetch + CE + LLM operations on intra-doc-heavy docs
  (less on cross-doc-heavy ones).
- **Quality impact:** none — identical decisions, just not computed twice.
- **Does NOT collapse:** distinct node IDs sharing a name — dedup is by ID-pair, not
  name. Multi-instance pairs each stay.
- **Already true in the benchmark:** `merge_cli` builds `blocked_pairs` as a
  `set[frozenset]` (already deduped), so G2 has always measured UNIQUE pairs while
  the worker double-counts. C.1 simply brings the worker in line — another reason
  this needs no G2 re-validation.
- **Re-validate G2?** No (no decision changes). Add a unit test asserting a
  doubled/symmetric pending list produces one outcome per unordered pair.

### C.2 — Batch LLM verify ⭐⭐ (biggest win, needs G2 re-validation)

Stage 3 currently sends one pair per `/ai/request` (`build_verify_request` → one
`VerifyVerdict`). Batch N pairs into a single prompt and parse a JSON array back.

- **Expected:** 5-10× fewer LLM calls (e.g. 900 → ~120 at batch 8).
- **Files:** `resolution/verify.py` — add `build_batch_verify_request(pairs)` and
  `parse_batch_verify_response(text) -> list[VerifyVerdict]` (greenfield — only the
  single-pair `build_verify_request`/`parse_verify_response` exist today, verify.py);
  `resolution/pass2.py` `route_pairs` Stage 3 (the `asyncio.gather` over `_verify_one`)
  — chunk the `uncertain` list by `verify_batch_size` and map results back to pairs.
- **Identity preservation (verified gap):** today the LLM stage maps verdicts back
  positionally and, on a `_verify_one` exception, emits a `PairOutcome("", "", ...)`
  with EMPTY node IDs (pass2.py). Batching breaks positional mapping — embed an
  explicit `pair_id` per pair in the prompt and key the response by it. The
  exception/partial-failure path must likewise carry each pair's identity so a dropped
  batch item maps to the right pair (and can be re-verified singly).
- **Two-tier cost telemetry:** `run_id` threads through every request for per-run cost
  attribution. A batch call + any single-pair fallbacks both carry the same `run_id`;
  telemetry already attributes per-request, so this is fine, but note the run's call
  count now mixes batch and single calls.
- **Config:** `resolution_verify_batch_size` (default 1 = current per-pair behavior,
  so the change is opt-in and reversible).
- **Risks + mitigations:**
  - *Attention dilution* — the model may judge a batch less carefully than a single
    pair. Mitigation: keep batches small (5-8); G2 is the gate.
  - *Partial/malformed array* — one bad item must not drop the whole batch.
    Mitigation: strict per-index parse; any missing/unparseable verdict falls back
    to a single-pair re-verify (or a conservative reject), logged.
  - *Order/identity drift* — the model must return verdicts in input order. Embed an
    explicit `pair_id` per pair in the prompt and key the response by it, not by
    position.
- **Re-validate G2?** YES — precision/recall must still PASS at the chosen batch
  size. This is the acceptance gate for C.2.

### C.3 — Tune the cross-encoder reject threshold (config + re-benchmark)

`resolution_crossencoder_reject_threshold = 0.20` today. Raising it auto-rejects
more pairs at the cheap CE stage, shrinking the LLM band.

- **Expected:** ~10-20% fewer LLM calls per 0.05 raise (data-dependent).
- **Risk:** recall — true pairs scoring in the newly-rejected band are lost. Recall
  has headroom now (0.915 vs 0.80 floor), but the margin is finite.
- **Method:** sweep reject ∈ {0.20, 0.25, 0.30} via `merge_cli`, pick the highest
  value that keeps recall ≥ 0.85 (buffer above the 0.80 floor). Config-only change.
- **Re-validate G2?** YES (it's literally a G2 sweep).

### C.5 — Write resilience: retry merge-suggestion writes ⭐ (reliability, not speed)

**Observed in production (2026-06-23):** OMNI Channel resolved 6470 pairs and found
~704 merges, but kg-server happened to restart (clean exit 0, recreated by compose)
DURING the Phase 3 write burst. Every `create_merge_suggestion` hit "All connection
attempts failed" → all 704 merges lost, `suggestions=0` despite ~1386 LLM calls of
work. The current Phase 3 loop logs the failure and moves on (counts it as skipped) —
no retry, no backoff, no batch transaction. A multi-minute, paid LLM pass is thrown
away by a few seconds of downstream unavailability.

**Change (`run_pass2_shadow` Phase 3 / `kg_client.create_merge_suggestion`):**
- Retry each write with bounded exponential backoff (e.g. 3 attempts, 0.5s → 2s).
- **Error taxonomy (verified against code — the plan's earlier "don't retry 422" was
  incomplete):** `create_merge_suggestion` → `_request` raises `KGClientError(status,
  detail)` ONLY for HTTP status ≥ 400. The OMNI failure ("All connection attempts
  failed") was NOT a `KGClientError` — it was an `httpx.RequestError`
  (`httpx.ConnectError`), which bypasses `KGClientError` entirely. So retry logic must:
  - retry on `httpx.RequestError` (connection/timeout/DNS — always transient), AND
  - retry on `KGClientError` with `status_code >= 500`, BUT
  - NOT retry `KGClientError` with `status_code` in 4xx (e.g. 422 Gate-2 reject — a
    real rejection, retrying won't help).
  The current Phase 3 (`pass2.py` ~L360-379) catches bare `Exception`, logs, and
  increments `pairs_skipped` — no retry. Add the retry around the single write, or
  (cleaner) inside `create_merge_suggestion` itself so all callers benefit.
- If a write still fails after retries, accumulate the failed pairs and report a
  COUNT in the summary (and a WARN) so a wholesale loss is loud, not silent
  (`suggestions=0 evaluated=6470` should never look like a normal result).
- Optional: a bulk/transactional suggestions endpoint so the write phase is one
  request, not N — both faster and atomic. (Larger change; sequence after C.1.)

- **Expected:** big-doc resolves survive a transient kg-server blip instead of
  discarding the entire LLM pass.
- **Re-validate G2?** No (write path only; decisions unchanged). Unit test: a write
  that fails twice then succeeds is retried and counted as written; a persistent
  failure is surfaced in the summary count.

> Why this is high priority: without it, every Phase C speedup still risks losing the
> whole run to one downstream hiccup. Reliability gates the value of throughput.

### C.4 — Low-effort knobs (use sparingly — these trade load for speed)

Flagged explicitly because they speed wall-clock by consuming MORE resources, which
is the opposite of the "không ngốn hiệu năng" goal. Reach for these only after C.1-C.3:

- **`resolution_verify_concurrency` 10 → 20**: ~2× faster band, but ~2× load on the
  Go `/ai/request` path and the upstream provider rate limit. Bench the provider's
  limit first.
- **Haiku for verify**: smaller/faster/cheaper per call for what is a binary
  classification. Requires routing the verify request to a Haiku-backed provider and
  re-validating G2 (model swap can shift precision).

---

## Recommended sequencing

1. **C.5 write retry** — land FIRST. Reliability gates everything else; without it a
   transient blip discards a whole paid LLM pass (already happened to OMNI).
2. **C.1 dedup** — free, no G2 re-run, immediately halves big-doc work.
3. **C.3 reject sweep** — cheap config tuning with a G2 sweep; lock the safe value.
4. **C.2 batch verify** — the structural win; implement behind `verify_batch_size`,
   re-validate G2, roll out by raising the batch size once green.
5. **C.4** — only if still needed, and only with provider-limit awareness.

---

## Task list

- [ ] **C1-T1** — Dedup `pending` by unordered ID-pair in `run_pass2_shadow` (keep
  first sim). Unit test: doubled/symmetric input → one outcome per pair.
- [ ] **C1-T2** — Measure call reduction on a real large doc (OMNI) vs Phase B baseline.
- [ ] **C3-T1** — Sweep `crossencoder_reject_threshold` via `merge_cli`; record
  precision/recall per value; set the highest value keeping recall ≥ 0.85.
- [ ] **C2-T1** — `build_batch_verify_request` + `parse_batch_verify_response`
  (per-`pair_id` keying, strict parse, per-item fallback) in `verify.py` + unit tests
  (well-formed batch, missing item, malformed item, reordered response).
- [ ] **C2-T2** — `route_pairs` Stage 3 chunks by `verify_batch_size`; map verdicts
  back by `pair_id`; unmapped pairs re-verified singly.
- [ ] **C2-T3** — Add `resolution_verify_batch_size` config (default 1) + `.env.example`.
- [ ] **C2-T4** — Re-validate G2 at batch sizes {4, 8}: precision ≥ 0.90, recall ≥ 0.80.
  Record the chosen size + measured LLM-call reduction. If quality dips, keep batch=1.
- [ ] **C-T-final** — End-to-end: re-resolve OMNI with C.1+C.3(+C.2); compare
  wall-clock + LLM-call count to the Phase B baseline (~900-1300 calls).

---

## Definition of Done

- [ ] C.1 merged; big-doc LLM-band calls down ~30-50%; existing resolution tests green.
- [ ] C.3 reject threshold locked at a G2-validated value (recall ≥ 0.85).
- [ ] C.2 (if adopted) behind `verify_batch_size`; G2 PASS at the chosen size with the
  measured call reduction recorded; per-item fallback covered by tests.
- [ ] No regression: `uv run pytest` green; G2 precision ≥ 0.90 AND recall ≥ 0.80
  reproducibly on clean benchmark data (delete `created_by='ba031-benchmark'` rows
  between runs — the COLUMN, not properties).
- [ ] OMNI re-resolve wall-clock and LLM-call count recorded vs Phase B baseline.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Batch verify lowers precision (attention dilution) | G2 is the gate; small batches; keep batch=1 if it dips |
| Malformed batch JSON drops good pairs | per-`pair_id` strict parse + single-pair fallback, logged |
| Reject-threshold raise quietly loses recall | sweep + keep recall ≥ 0.85 buffer, not just ≥ 0.80 |
| Dedup accidentally collapses same-name distinct nodes | dedup by ID-pair, never by name; unit test guards |
| Optimizing the wrong layer | C.1 first (free); only escalate to C.2/C.4 if big docs still hurt |

## Non-goals

- Re-enabling cross-encoder auto-merge or the high-sim rule (Phase B removed both for
  precision — near-miss orgs and antonyms; do not undo to save calls).
- Changing the embedding/blocking stage (G1 is calibrated).
