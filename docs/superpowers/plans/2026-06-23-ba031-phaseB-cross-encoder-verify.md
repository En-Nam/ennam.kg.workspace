# BA-031 Phase B — Cross-Encoder Verify (LLM-Free Pipeline)

**Created:** 2026-06-23
**Depends on:** Phase A code stable + `vi_blocking_v1.json` human-validated
**Owner:** backend-dev
**Related:** BA-031, `2026-06-22-ba-031-resolution-turn-on-runbook.md`

---

## Problem

Phase A verify_pair calls LLM for every candidate pair:

- 200 entities/doc × K=10 = 2000 pairs → ~60 min/doc
- 35-doc corpus → ~35 hours, high token cost
- Critical path depends on external LLM API availability

**Goal:** Reduce verify time to <2 min/doc while maintaining precision ≥ 0.90.

---

## Proposed Architecture: 3-Stage Verify Pipeline

```
Stage 0: ANN Blocking (unchanged)
  multilingual-e5-small embeddings → K=10 candidates
         ↓ ~2000 pairs/doc
Stage 1: Rule-based Filter (new, ~0ms/pair)
  ├─ normalized exact match          → AUTO MERGE
  ├─ embedding score > 0.95 + same type → AUTO MERGE
  └─ embedding score < 0.72          → AUTO REJECT
         ↓ ~200–400 ambiguous pairs
Stage 2: BGE Reranker (new, ~10–30ms/pair)
  model: BAAI/bge-reranker-v2-m3 (568MB, local)
  ├─ score > 0.85  → MERGE SUGGESTION
  ├─ score < 0.40  → REJECT
  └─ score 0.40–0.85 → uncertain (~5% of pairs)
         ↓ ~10–40 uncertain pairs
Stage 3: LLM Verify (existing, scoped down)
  only for BGE-uncertain pairs
  ├─ confident → MERGE / REJECT
  └─ still uncertain → needs_review (hub gate, existing)
```

---

## Thresholds (to be benchmarked, initial estimates)

| Threshold | Value | Rationale |
|---|---|---|
| ANN sim (Stage 0) | 0.74 | Unchanged — G1 gate calibrated |
| Auto-merge sim (Stage 1) | > 0.95 | Very high confidence, same type required |
| Auto-reject sim (Stage 1) | < 0.72 | Below ANN blocking threshold |
| BGE merge (Stage 2) | > 0.85 | TBD — needs benchmark |
| BGE uncertain (Stage 2) | 0.40–0.85 | TBD — needs benchmark |
| BGE reject (Stage 2) | < 0.40 | TBD — needs benchmark |

**Threshold calibration task:** Run BGE on `vi_blocking_v1.json` (after human validation) and tune to hit precision ≥ 0.90, recall ≥ 0.80.

---

## Files Changed

> **Codebase-verified (2026-06-23).** Each row notes what the existing code looks like today so the diff is accurate, not assumed.

| File | Change | Codebase reality |
|---|---|---|
| `src/ennam_kg/resolution/rules.py` | New file — `rule_based_decision()` Stage 1 filter | ❌ Does not exist yet — clean new file |
| `src/ennam_kg/resolution/deps_factory.py` | Add `reranker_model` field to `Deps` dataclass + instantiate in `build_pass2_deps()` | ⚠️ `Deps.model` today is the **embedding** model (`encode_query` interface), NOT a cross-encoder. Must add a SEPARATE `reranker_model` field — do not overload `model`. |
| `src/ennam_kg/resolution/verify.py` | Add `crossencoder_score(reranker, a, b) -> float` returning a `VerifyVerdict`; keep existing `verify_pair()` unchanged as LLM Stage 3 | ✅ `verify_pair()` returns `VerifyVerdict{same_entity, confidence, canonical_name, reason}` — reuse this shape for cross-encoder output |
| `src/ennam_kg/resolution/pass2.py` | **Refactor** Phase 2 inner loop, not just "route". Split `_verify_one()` into: rule filter → cross-encoder → LLM (only uncertain pairs hit `verify_pair()`) | ⚠️ `_verify_one()` (≈ lines 173–198) currently hardcodes a direct `verify_pair()` call for EVERY pair inside the semaphore loop. Restructure so rule+cross-encoder run BEFORE the LLM semaphore, and only uncertain pairs enter it. |
| `src/ennam_kg/config.py` | Add `resolution_crossencoder_model`, `resolution_crossencoder_merge_threshold`, `resolution_crossencoder_uncertain_low`, `resolution_crossencoder_uncertain_high`, `resolution_rule_sim_high` | ✅ Existing pattern: `resolution_*` snake_case, field names mirror `Deps` fields. Stage 1's 0.95 auto-merge is currently a magic number — make it `resolution_rule_sim_high`. |
| `pyproject.toml` | — | ✅ **Already present**: `sentence-transformers>=3.0` (line 18). T1 is a no-op verify, not an add. |
| `Dockerfile` (worker) | Add RUN step to pre-download Jina model in runtime stage, before switching to non-root `ennam` user | ⚠️ Multi-stage build; `HF_HOME=/tmp/.cache/huggingface`. No model pre-bake today (downloads on first inference). Pre-bake needs network in CI + must land in the non-root user's cache path. Benchmark cold start, don't assume < 15s. |
| `tests/resolution/test_crossencoder_verify.py` + `test_rules.py` | New test files | ✅ `tests/resolution/` exists with `test_verify.py`, `test_pass2.py` — reuse AsyncMock + FakeKGClient patterns |
| `.env.example` | Add new `resolution_crossencoder_*` + `resolution_rule_sim_high` vars | ✅ Currently minimal (11 lines) |

**Memory requirement:** minimum 4GB RAM for worker container (model ~1.5GB + existing worker usage ~1GB).

---

## Model

> **DECISION (2026-06-23, implementation):** switched from jina-reranker-v2 to
> **`BAAI/bge-reranker-v2-m3`**. jina's HF remote code (`trust_remote_code=True`)
> imports `create_position_ids_from_input_ids` from transformers' xlm_roberta module,
> which the pinned transformers version (shared with the e5 embedding model) no longer
> exports → hard ImportError. Downgrading transformers would risk the core e5 pipeline.
> bge-reranker-v2-m3 uses stock XLM-RoBERTa (no remote code), loads cleanly, and via
> `sentence-transformers` `CrossEncoder.predict()` already returns scores in [0,1]
> (so `apply_sigmoid=False`). Smoke test on VI pairs discriminated correctly:
> near-miss "Khải Thịnh"/"Khai Thông" → 0.024, diacritics "Nguyễn Tấn Sự"/"Nguyen Tan Su" → 0.972.
> Honorific cases scored low via the cross-encoder (differing context), so honorific
> stripping was added to the Stage 1 rule normalizer instead — caught cheaply at Stage 1.

**`BAAI/bge-reranker-v2-m3`** (active choice)
- Size: 568MB on disk, ~2.3GB RAM inference
- Architecture: stock XLM-RoBERTa — no `trust_remote_code`, no `einops`
- Languages: 100+ including Vietnamese
- Output: [0,1] via CrossEncoder default sigmoid (`apply_sigmoid=False`)
- License: MIT
- **RAM requirement bumped to ≥ 6GB** for the worker container (model ~2.3GB +
  e5 embedding model + worker). Verified host has ~6.7GB free.

```python
from sentence_transformers import CrossEncoder

reranker = CrossEncoder(
    "jinaai/jina-reranker-v2-base-multilingual",
    automodel_args={"torch_dtype": "auto"},
    trust_remote_code=True,
)

# Input format: full entity context, not just name.
# ⚠️ FIELD NAMING: entities flowing through pass2 carry Go-API field names
# (`title`, `node_type`) OR legacy (`name`, `type`). verify.py already has an
# `_extract()` helper that normalizes both — REUSE it here, do NOT assume
# entity["name"]/entity["type"] (that KeyErrors on Go-API dicts).
def _entity_text(entity: dict) -> str:
    name = entity.get("title") or entity.get("name", "")
    etype = entity.get("node_type") or entity.get("type", "")
    desc = (entity.get("properties", {}).get("description")
            or entity.get("description", ""))
    return f"[{etype}] {name}: {desc[:200]}"

scores = reranker.predict([
    (_entity_text(entity_a), _entity_text(entity_b))
])
merge_confidence = float(scores[0])
```

> ⚠️ **Do NOT blindly apply sigmoid.** `jina-reranker-v2` via `CrossEncoder.predict()`
> returns scores in [0, 1] already (the model applies its own activation). Applying
> an extra `1/(1+exp(-x))` would double-squash and break threshold calibration.
> **T9 must first print the raw `predict()` output range on the benchmark set** and
> only add normalization if the values are unbounded logits. BGE reranker, by
> contrast, returns raw logits and DOES need sigmoid — so the normalization step is
> model-specific, not universal.

Alternative if quality insufficient after benchmarking: `BAAI/bge-reranker-v2-m3` (568MB, ~3GB RAM, returns logits → needs sigmoid).

---

## Stage 1 Rule-Based Filter

```python
import unicodedata, re

def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text.lower().strip())
    text = re.sub(r"[\s\-_\.]+", " ", text)
    return text

def _name_of(entity: dict) -> str:
    return entity.get("title") or entity.get("name", "")

def _type_of(entity: dict) -> str:
    return entity.get("node_type") or entity.get("type", "")

def rule_based_decision(
    entity_a, entity_b, sim_score: float, rule_sim_high: float,
) -> str | None:
    """Returns 'merge', 'reject', or None (pass to next stage).

    sim_score is the embedding cosine from Stage 0. rule_sim_high comes from
    config (resolution_rule_sim_high, default 0.95) — not a magic number.
    """
    # Safety check only — ANN blocking already filters below 0.72-0.74.
    # This guards against any future change to blocking threshold.
    if sim_score < 0.72:
        return "reject"
    # Auto-merge: very high embedding similarity + same entity type
    if sim_score > rule_sim_high and _type_of(entity_a) == _type_of(entity_b):
        return "merge"
    # Auto-merge: exact normalized name match (handles whitespace/dash/dot variants)
    # Note: does NOT handle abbreviations ("AIO Link" ≠ "AIOLink" after normalize).
    # Abbreviation cases fall through to Stage 2 (cross-encoder).
    if _normalize(_name_of(entity_a)) == _normalize(_name_of(entity_b)):
        return "merge"
    return None  # pass to cross-encoder
```

---

## Pass 2 Refactor (the HIGH-severity change)

Today `_verify_one()` (pass2.py ≈ L173–198) sends EVERY candidate pair into the
LLM semaphore. Phase B must restructure so the LLM only sees uncertain pairs:

```
Phase 1 (unchanged): embed entity, ANN-retrieve K candidates → list of pairs
                     each pair carries its Stage-0 sim_score

Phase 2a (NEW, sync, ~0ms): for each pair → rule_based_decision()
            'merge'/'reject' → final verdict, never touches LLM
            None             → goes to Phase 2b

Phase 2b (NEW, cross-encoder, batched ~10-30ms): score remaining pairs
            score > merge_threshold      → merge verdict
            score < uncertain_low        → reject verdict
            uncertain_low..uncertain_high → goes to Phase 2c

Phase 2c (existing LLM semaphore): only uncertain pairs call verify_pair()
            this is the ONLY stage that hits the LLM API

Phase 3 (unchanged): tally verdicts, write merge_suggestions
```

Key invariant to preserve: the parallel semaphore (`verify_concurrency`) must
still wrap ONLY Phase 2c (the async LLM calls). Phases 2a/2b are CPU-bound and
run synchronously/batched, so they must NOT be inside the asyncio.gather that
currently fans out the verify calls. Getting this wrong re-introduces the
sequential bottleneck or double-counts pairs.

---

## Expected Performance (per doc, 200 entities)

| Stage | Pairs in | Pairs out | Time |
|---|---|---|---|
| ANN Blocking (Phase 1) | 200 × K=10 = 2000 | ~400 (sim > 0.72) | ~2s |
| Rule Filter (Phase 2a) | 400 | ~200 ambiguous | ~0ms |
| Cross-Encoder (Phase 2b) | 200 | ~10–20 uncertain | ~3–6s |
| LLM Verify (Phase 2c) | 10–20 | 0 uncertain | ~14–28s |
| **Total** | | | **~20–40s/doc** |

35-doc corpus: **~12–23 minutes** (vs ~35 hours currently).

> These numbers are estimates pending T9 benchmark. The "~95% filtered before LLM"
> assumption is the load-bearing one — if the cross-encoder's uncertain band is wider
> than ~5% of pairs in practice, LLM volume (and time) rises proportionally. T9
> measures the ACTUAL uncertain-band fraction on real data before any GA claim.

---

## Task List

- [x] **T1** — ✅ DONE (verified): `sentence-transformers>=3.0` already in `pyproject.toml:18`. No-op.
- [ ] **T2** — Add `reranker_model` field to `Deps` dataclass + load Jina singleton in `build_pass2_deps()` with pre-warm. **Do not overload the existing `model` (embedding) field.**
- [ ] **T3** — Implement `rule_based_decision()` + `_name_of`/`_type_of`/`_normalize` helpers in new `resolution/rules.py` (handle both Go-API `title`/`node_type` and legacy `name`/`type`)
- [ ] **T4** — Implement `crossencoder_score()` in `verify.py` returning a `VerifyVerdict`; reuse the existing `_extract()` helper for field access; verify whether `predict()` output needs normalization (see Model note)
- [ ] **T5** — **Refactor** `pass2.py` Phase 2 into 2a (rule) / 2b (cross-encoder, batched) / 2c (LLM semaphore — uncertain only). Keep the semaphore wrapping ONLY 2c. (HIGH-severity — see refactor sketch above.)
- [ ] **T6** — Add `resolution_crossencoder_*` + `resolution_rule_sim_high` to `config.py` + `.env.example`
- [~] **T7** — DEFERRED (prod follow-up). The e5 embedding model already downloads at
  runtime to `HF_HOME=/tmp/.cache/huggingface` (not pre-baked), so bge downloads the
  same way on first resolve — consistent, one-time cold start per container. Pre-baking
  to the image is a prod optimization but `/tmp` may be tmpfs-mounted at runtime
  (wiping a baked cache), so it needs care; not required to validate Phase B.
- [ ] **T8** — Write `tests/resolution/test_crossencoder_verify.py` with known Vietnamese entity pairs (same name/different person; abbreviation variants; diacritics)
- [ ] **T9** — Benchmark on `vi_blocking_v1.json` (after human validation): tune thresholds to precision ≥ 0.90 / recall ≥ 0.80, confirm LLM called < 10% pairs
- [ ] **T10** — End-to-end load test: ingest 3 representative docs, measure wall-clock time vs Phase A baseline

---

## Definition of Done

- [ ] `crossencoder_score()` + `rule_based_decision()` pass unit tests with known Vietnamese entity pairs (same name/different person, abbreviation variants, diacritics)
- [ ] Cross-encoder + rule thresholds calibrated on (human-validated) `vi_blocking_v1.json`: precision ≥ 0.90, recall ≥ 0.80
- [ ] Measured uncertain-band fraction recorded; LLM called for < 10% of candidate pairs on benchmark dataset
- [ ] `pass2.py` refactor preserves the semaphore around LLM-only stage; `test_pass2.py` still green
- [ ] End-to-end load test (T10): representative docs complete far below Phase A baseline
- [ ] `uv run pytest` green; no regression in existing resolution tests
- [ ] Dockerfile builds cleanly with Jina model pre-downloaded; cold start measured

---

## Risks

| Risk | Mitigation |
|---|---|
| Jina reranker precision < 0.90 on Vietnamese | Benchmark first (T9); escalate to `BAAI/bge-reranker-v2-m3` (568MB) if needed |
| Worker container OOM when loading 278MB model | Require ≥ 4GB RAM; use `torch_dtype="auto"` (fp16 on GPU, bf16 on MPS, fp32 on CPU) |
| Model download fails in air-gapped prod | Pre-bake into Docker image at build time (T7) |
| Threshold tuning without reliable benchmark data | `vi_blocking_v1.json` must be human-validated first — AI-generated labels give unreliable G2 results |
| Cold start latency spike on first request | Pre-warm model at worker startup in `deps_factory.py` (T2) |

---

## Ordering vs Phase A GA

**Phase B implement TRƯỚC, Phase A GA SAU.**

Thứ tự đúng:
1. Implement Phase B (T2–T8)
2. Benchmark Phase B pipeline → G2 gate (T9) — đây là G2 gate chính thức cho GA
3. Load test (T10)
4. G6 human SQL review trên suggestions từ Phase B pipeline
5. Flip `apply_mode: apply` (Phase A runbook Step 6)

Nếu làm ngược (GA trước rồi mới Phase B), G2 gate phải chạy lại trên pipeline mới — tốn công gấp đôi và tạo ra 2 baseline khác nhau.

**Prerequisites thực sự:**
- Phase A code stable (worker, pass2, Go API đang hoạt động)
- `vi_blocking_v1.json` được human-validate (≥ 30 entity groups, ≥ 50 pairs, owner assigned)
