# BA-031 Implementation Design — Two-Pass Graph Extraction & Entity Resolution (DAAB)

**Status**: Design — approved for planning
**Created**: 2026-06-18
**Author**: synthesised from a Tech-Consultant ↔ CTO design debate (2 rounds), grounded against the live Go/Python codebase
**Implements**: `ennam.kg.requirements/documents/phase8/BA-031-graph-extraction-entity-resolution.md`
**Relation to BA-031**: This is the **authoritative build contract** (a superset of BA-031). It keeps BA-031's 8 functional requirements and adds 7 new FRs, a numeric phased rollout (8a→8d), cost guardrails, and one corrective rewrite of **BR-005.11**. Where this spec extends or overrides BA-031 it says so explicitly. BA-031 in the requirements repo remains as-is; this document governs implementation.
**Depends On**: BA-030 (canonical `document_chunk` producer), BA-025 (`document_chunk` unit, migration 000059), `knowledge_node_embeddings` (000055), BA-009 (AI provider routing), BA-008 (confidence-scoring convention), `knowledge_nodes`/`knowledge_edges` (000004/000006).

---

## 1. Verdict & Scope

**Conditional GO** for the full implementation through **Phase 8c (resolution in shadow / suggest-only mode)**. **Phase 8d (auto-merge GA) is HARD-GATED** behind a funded labelled Vietnamese benchmark and a built-and-drilled un-merge capability (§9, §10).

**Build, not buy**, on entity resolution — a conscious decision. Off-the-shelf ER tooling (Splink, Zingg, Dedupe.io) targets structured, monolingual, tabular records with stable blocking keys. It cannot carry our three hard constraints simultaneously: (a) multilingual Vietnamese resolution (diacritics, honorifics "ông/bà/Mr."), (b) the closed-schema constraint that keeps the graph traversable, (c) mandatory provenance/auditability on every node and edge. We accept the maintenance + benchmark burden a vendor would otherwise own (§9 phase 8b funds it).

**Strategic coupling (why merge precision is critical):** AAA Phase C synthesises `MasterRecord` documents from this resolved graph via `derived_from`/`evidence` edges. Garbage in DAAB becomes garbage in every downstream MasterRecord. A wrong merge is not a local defect — it poisons the product surface. This justifies the strict gates below.

---

## 2. Architecture (grounded in the real codebase)

### 2.1 The load-bearing fact BA-031 under-states: job durability

`internal/jobengine/engine.go` is an **in-process goroutine pool with an in-memory `map[string]*JobStatus`** — retry/backoff but **no durability**; a server restart loses all job state. BA-031 repeatedly says "runs on the existing `jobengine`", which is insufficient for a multi-minute, multi-LLM-call pipeline.

The Python worker (`ennam.kg.python/src/ennam_kg/queue/consumer.py`) reads **only Redis `BRPOP`** (FIFO, mirrors Go `LPUSH` in `internal/queue/publisher.go`). The DB-backed `query_queue` (migration 000029, `store/queue.go`) is **AI-query-coupled** (`ai_query_id UUID NOT NULL REFERENCES ai_queries(id)`) and **not wired to the Python worker** — it cannot be reused as the extraction substrate.

**Decision (durability = transport + state, a coupled pair):**
- **Dispatch transport:** Redis `LPUSH→BRPOP` (the only path wired to Python). Do **not** add a DB-claim queue — gratuitous new Python surface for zero benefit.
- **Durability / recovery / idempotency:** a new **`chunk_extraction_state`** table. Redis `BRPOP` is a *destructive* pop; a consumer crash mid-pipeline silently drops the job (Redis AOF/RDB only protects against Redis restart, not consumer death). A **recovery sweep** re-enqueues chunks stuck in `staged`/`resolving` whose `run_id` is dead. BR-007.6 collapses any half-written `active` duplicates from a crash between Pass 1 and Pass 2.

> **This is one requirement, not two.** Redis dispatch *without* the state-table recovery sweep re-ships the exact `jobengine` durability bug under a new name. They must be built together.

### 2.2 Service division of labor

| Concern | Owner | Files to add / touch |
|---|---|---|
| Trigger endpoints (`/extract`, `/resolve`, `/runs/{id}`) | Go | new `internal/handler/extraction.go` + `routes.go` |
| Enqueue extract/resolve jobs | Go | new message types in `internal/queue/messages.go` (mirror Python `queue/messages.py`) |
| Gate 1 edge-whitelist + **symmetric node-type** enforcement | Go | `internal/validation/edge_whitelist.go` (existing), new `ValidNodeTypes` check in the node store/handler path, `internal/config/types.go` + `config.yaml` |
| Candidate blocking (same-type, project-scoped, `min_similarity`) | Go | reuse `internal/store/node_embedding.go` `SemanticSearch` (already supports `nodeTypes[]`+`projectID`); new internal endpoint adds the threshold floor |
| Embedding **upsert** | Go | `internal/store/node_embedding.go` `Upsert` (existing) |
| Optimistic-lock node update | Go | `internal/store/version.go` `UpdateNode(WHERE version=expected)` + `ErrVersionConflict` (existing) |
| Merge transaction (re-point, supersede, audit) | Go | new `internal/store/merge.go` (single DB tx) |
| Pass 1 extraction + gleaning (LLM) | Python | new `src/ennam_kg/extraction/` package (mirror `kg_generator/`) |
| Pass 2 verify + re-summarise (LLM) | Python | new `src/ennam_kg/resolution/` package |
| Embedding **vector generation** | Python | `embeddings/local_model.py` via `/api/v1/embeddings` (existing) |
| Provider routing (BA-009) | Python→Go | `ai_client/client.py` → Go AI abstraction (existing) |

### 2.3 The Go/Python tangle, made explicit

Pass-2 **blocking lives in Go** (`SemanticSearch`); the **verifier lives in Python**. The Python resolver therefore calls back into Go for candidates. The public `/api/v1/search` exposes `node_types` + `project_id` but returns top-K by rank with **no `min_similarity` floor**. A net-new internal endpoint is required (FR-NEW-4): `POST /api/v1/internal/resolution/candidates` taking `{node_id | embedding, node_type, project_id, top_k, min_similarity}`, applying the cosine cutoff server-side. This is **net-new surface**, not "reuse search."

### 2.4 Persist-then-resolve

The Pass-2 state machine shows `staged/embedded/resolving`, but `knowledge_nodes.status` (CHECK, migration 000015, 13 values) contains only `active` and `superseded` usable here, and we add no new status value. Therefore those intermediate states are **run-progress on `chunk_extraction_state`**, never `node.status`. Pass 1 **persists entities immediately as `active`**; Pass 2 merges later. A crash between passes leaves `active` duplicates that BR-007.6 collapses on the next resolve run. Holding entities in memory until resolved would lose extraction work on a crash and defeat the NFR-259 incremental guarantee — rejected.

### 2.5 End-to-end flow (durable)

```
POST /extract  → Go validates doc → record run → LPUSH {type:"extract_document", doc_id, run_id}
Python BRPOP   → Pass1: for each chunk:
                   skip-guard (content_hash in chunk_extraction_state) → if unchanged+done: SKIP (no LLM)
                   else: LLM extract → gleaning loop → drop out-of-vocab →
                   attach provenance (sentence_span) → POST nodes/edges to Go (Gate 1) as status=active →
                   mark chunk_extraction_state = extracted
                 → on done: LPUSH {type:"resolve_document", doc_id, run_id}
Python BRPOP   → Pass2: for each new entity:
                   POST /embeddings (symmetric prefix, same on both sides) → Go upserts embedding →
                   GET /resolution/candidates (same-type, ≥ threshold, top-K) →
                   for each pair: LLM verify →
                     8c shadow: write merge_suggestions sidecar (apply nothing)
                     8d GA:     if conf ≥ threshold AND degree-gate allows → Go merge tx
recovery sweep → periodically re-enqueue chunk_extraction_state rows with dead run_id
```

---

## 3. Open-Question Resolutions (final, joint)

| OQ | Resolution | Rationale |
|---|---|---|
| **OQ-001** | **(A)** — migration extends `knowledge_nodes_node_type_check` with the closed node types + `edge_whitelist` rules for the 7 relations. Single-owner BA-031 prerequisite. | (B) namespacing all entities under `concept` makes `SemanticSearch`'s `node_type IN (...)` same-type blocking degenerate to compare-every-concept → defeats BR-004.1 and explodes Pass-2 cost; a JSONB `subtype` cannot use the `idx_nodes_type` btree or a DB CHECK. The CHECK has been extended 4× (000051/055/059) with zero incident and has a clean down-migration — **schema is reversible; the *data* is the irreversible commitment**, which is why 8c/un-merge gate the data, not the schema. |
| **OQ-002** | **No deterministic VN normaliser in v1 — ONLY IF** paired with a lower `resolution_sim_threshold` + larger `resolution_top_k`. | A pair missed at cosine blocking never reaches the verifier, so "rely on the verifier" is valid only if blocking surfaces the pair. `multilingual-e5-small` may not clear 0.82 for "Mr. A" vs "Nguyễn Văn A". Recover recall at the blocker via threshold/K, not a hand-rolled normaliser (Rule 5). Revisit a light honorific-stripper only if NFR-257 is missed. |
| **OQ-003** | **`canonical_name + description`**, with a **symmetric prefix — the same e5 prefix on both the stored entity and the query entity**. Re-embed on merge only when the embedded `content_hash` changes (BR-006.4). | `e5` is prefix-instructed (`encode_query` prepends `query: `, `encode_passage` prepends `passage: ` — `local_model.py:59`). Entity-resolution blocking is a **symmetric** entity-vs-entity comparison, so a `query:`/`passage:` mismatch silently degrades cosine and masquerades as a threshold problem. The mandate is **symmetry** (same prefix both sides); per the `multilingual-e5` model card, default to `query:` on both for symmetric-similarity tasks, and confirm the exact prefix in the 8b benchmark sweep — do **not** hard-code `passage:` without that check. Note the existing ingestion path stores section embeddings via `encode_passage` (`decompose.py:249`); the resolution blocker must apply its chosen prefix consistently to **both** sides of the entity comparison rather than inheriting the asymmetric retrieval convention. |
| **OQ-004** | **HARD GATE.** 0.82/0.75 are placeholders. The benchmark must **sweep threshold × K** on real labelled VN data before GA; expose per-project via `extraction-config`. | OQ-002/003/004/NFR-257 are one system tension, not four independent items — threshold is the single point where recall is won or lost. |
| **OQ-005** | **Degree-gated auto-merge.** Low-degree/leaf nodes auto-merge once thresholds pass the benchmark; **high-degree `Organization`/`Project` hub nodes (degree ≥ threshold) require human confirm** (suggest-only). Overrules BA-031's blanket auto-merge. | NFR-256 tolerating 10% wrong merges is acceptable for leaves, **unacceptable for hubs** (a wrong hub merge silently corrupts every traversal through it and is expensive to even detect). |
| **OQ-006** | **No semantic relation dedup in v1** (YAGNI). On exact `(source,target,edge_type)` collision: **supersede-with-provenance, do not delete** (see §6 BR-005.11 rewrite). | Hard-delete compaction of confirmed-old superseded edges is a later, separately-gated BA. |
| **OQ-007** | **Resolved into BR-001.8.** Add `master_record` to the `node_type` CHECK (graph vocabulary = 9) but **exclude it from the extractable set (8)** — two distinct lists. Pass 1 never emits `MasterRecord`. | Schema-reserved for AAA Phase C write-back. No BA-031 behaviour depends on the AAA owner's answer. |

---

## 4. Functional Requirements

### 4.1 Original BA-031 FRs (implemented as specified, with the clarifications above)

- **FR-001** Closed-schema Pass 1 extraction (drop, don't coerce; closed 8 extractable types).
- **FR-002** Gleaning loop (bounded rounds, early-stop, fresh single-turn call per round).
- **FR-003** Mandatory provenance on every node and edge (`source_doc_id`, `chunk_id`, `sentence_span`).
- **FR-004** Candidate generation (same-type blocking, cosine ≥ threshold, top-K cap).
- **FR-005** Pass 2 LLM verification & merge (with the BR-005.11 rewrite in §6).
- **FR-006** Merged-description re-summarisation (never concatenate; conditional re-embed).
- **FR-007** Incremental resolution (new-doc scope; idempotency via §5 storage).
- **FR-008** Per-pass model routing (cheap Pass 1, strong Pass 2, via BA-009).

### 4.2 New FRs (this spec adds to BA-031)

- **FR-NEW-1 — Un-merge capability.** A built, tested, and *drilled* un-merge endpoint + service that reverses a merge: flips `merged_into` / `superseded_by_merge` flags and restores the pre-merge node **and edge** state. Hard prerequisite for 8d. *Precondition:* requires lossless edge dedup (§6) — i.e. the merge must record source-edge identity in the survivor's provenance so deduped edges are reconstructable.
- **FR-NEW-2 — Cost ceiling (independent of BA-009).** A per-run **and** per-document token + $ ceiling, **enforced before a batch starts**, plus a gleaning marginal-yield circuit breaker, plus per-run token/$ surfaced in the admin run view. *Why independent:* BA-009's budget is per-provider monthly ($50 default in `config.yaml`) and **the Claude Max path reports cost=0 and bypasses the budget check entirely** (`internal/ai/selector.go`: "claude_max always passes") — so on the primary path there is no ceiling at all. BA-009 cannot provide this guardrail.
- **FR-NEW-3 — `chunk_extraction_state` storage.** Durable per-chunk run-state + content-hash idempotency table (§5). Enables NFR-263 cost-idempotency and crash recovery. Absorbs BR-007.5/BR-007.6 mechanics.
- **FR-NEW-4 — Internal resolution-candidates endpoint.** `POST /api/v1/internal/resolution/candidates` over `SemanticSearch` with `nodeTypes`, `projectID`, `min_similarity`, `top_k` (the public `/search` has no similarity floor).
- **FR-NEW-5 — Symmetric app-side node-type validation.** Add a `ValidNodeTypes` app-level check on node creation. Today only edges are app-validated (`EdgeWhitelistValidator`); node creation falls through to the raw DB CHECK, producing a poor error and an asymmetric "fail loud."
- **FR-NEW-6 — Shadow / suggest-only resolution mode.** Pass 2 writes proposals to a new **`merge_suggestions`** sidecar table (candidate pair, scores, proposed canonical, model rationale) and applies *nothing* to `knowledge_nodes`/`knowledge_edges`. Config-gated; default before 8d. 8c→8d is a one-flag flip on the same code path; node status set stays untouched.
- **FR-NEW-7 — Degree-gating policy.** At merge time, split auto-apply (degree < threshold) from human-confirm (degree ≥ threshold). Implements OQ-005.

---

## 5. Data Model Additions

### 5.1 `chunk_extraction_state` (new table — FR-NEW-3)

| Column | Type | Notes |
|---|---|---|
| `chunk_id` | UUID (FK → `document_chunk` node) | PK component |
| `project_id` | UUID (FK → projects) | scope |
| `content_hash` | TEXT | hash of chunk content; skip-guard key (BR-007.5) |
| `status` | TEXT | run-progress: `pending / extracting / extracted / resolving / resolved / extract_failed` (NOT `node.status`) |
| `run_id` | UUID | owning run; recovery sweep targets dead `run_id`s |
| `gleaning_rounds_used` | INT | audit (FR-002) |
| `dropped_count` | INT | out-of-vocab drops (BR-001.3) |
| `updated_at` | TIMESTAMPTZ | recovery-sweep staleness |

Idempotency: a chunk whose `(chunk_id, content_hash)` is already `extracted`/`resolved` is **skipped** (zero LLM calls — NFR-263 cost-idempotency). Recovery: rows stuck in `extracting`/`resolving` past a staleness window with a dead `run_id` are re-enqueued.

### 5.2 `merge_suggestions` (new sidecar table — FR-NEW-6)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `project_id` | UUID | scope |
| `node_a_id`, `node_b_id` | UUID | candidate pair |
| `embedding_similarity` | REAL | from blocking |
| `merge_confidence` | REAL | from strong model |
| `proposed_canonical_id` | UUID | model's pick |
| `resolution_model` | TEXT | attribution |
| `reason` | TEXT | model rationale |
| `degree_max` | INT | max degree of the pair (drives degree-gating) |
| `decision` | TEXT | `suggested / applied / rejected / needs_review` |
| `created_at` | TIMESTAMPTZ | |

### 5.3 Reused tables (no column changes)

`knowledge_nodes`, `knowledge_edges`, `knowledge_node_embeddings` — BA-031 entity/edge/provenance contracts live in the JSONB `properties` column exactly as BA-031 §6 specifies. The **only** schema migration on these is the OQ-001 `node_type` CHECK + edge-whitelist extension.

---

## 6. Corrective Rewrite — BR-005.11 (delete → supersede, lossless)

**BA-031 as written:** on an edge re-point UNIQUE(`source_id`,`target_id`,`edge_type`) collision, "union provenance, **delete** duplicate." This is **lossy** — once the colliding edge row is deleted, un-merge cannot reconstruct the pre-merge graph (the duplicate's identity, timestamps, and independent provenance lineage are gone). It makes "reversible" false at the edge level.

**Rewrite (binding for this spec):**
> On a re-point collision, the **surviving** edge's `provenance[]` absorbs the superseded edge's `provenance[]` (union, de-duplicated), **recording source-edge identity** for each absorbed entry (which entries came from which source edge). The duplicate edge is **superseded, not deleted** — flagged `superseded_by_merge` with the merge-operation id in `properties`, the row retained. Un-merge restores it deterministically. Hard-delete compaction of confirmed-old superseded edges is deferred to a later, separately-gated BA.

This trades a small edge-table growth (retained superseded rows) for clean reversibility — the linchpin that makes FR-NEW-1 buildable. Node merges already retain the member (`superseded` + `merged_into` + provenance); this brings edges to parity.

---

## 7. Data Contracts & Prompt Design (Qwen-portable, NFR-265)

**Pass 1 — single JSON object, single-turn:**
```json
{
  "entities": [
    {"temp_id":"e1","type":"Person","canonical_name":"Nguyễn Văn A",
     "subtype":"engineer","aliases":["Mr. A"],"description":"…",
     "sentence_span":{"start":12,"end":64}}
  ],
  "relations": [
    {"type":"works_for","source":"e1","target":"e2",
     "sentence_span":{"start":12,"end":64},"confidence":0.9}
  ]
}
```
- `temp_id` resolves intra-chunk relations before persistence; **Go assigns real UUIDs** on persist.
- `sentence_span` offsets into the chunk satisfy BR-003.2 without duplicating chunk text (NFR-267); **validate spans server-side** and drop out-of-range entities (count as dropped, fail loud).
- Closed vocabulary injected as an explicit enum; **drop-don't-coerce enforced twice** — in the prompt ("if unsure, omit") and at Go Gate 1 (authoritative). Never trust the prompt alone.

**Gleaning (FR-002):** each round is a **fresh single-turn call** (chunk + already-found names → same JSON shape). No chat thread (Qwen has no multi-turn guarantee). Merge by case-insensitive `canonical_name` (BR-002.4); early-stop on empty (BR-002.2).

**Pass 2 verify — single JSON in/out:**
```json
// IN:  {"a":{name,aliases,description,type},"b":{…}}
// OUT: {"same_entity":true,"confidence":0.91,
//       "canonical_name":"Nguyễn Văn A","reason":"honorific vs full name, same role"}
```
**Re-summarisation (FR-006)** is a **separate** single-turn call (`{descriptions:[...],max_chars}` → `{description}`), kept single-purpose and skippable when only one member has a description.

> The "≤3 required params / enum / pagination" MCP-tool discipline (ecosystem §4.2.3) does **not** apply here — BA-031 is a backend batch pipeline exposing admin REST, not Qwen-facing MCP tools (BR-008.5 scope note).

---

## 8. Cost Model & Guardrails (FR-NEW-2)

**Shape:** Pass 1 per document ≈ `chunks × (1 + gleaning_rounds) × cheap_cost` (up to 3× calls/chunk at `gleaning_max_rounds = 2`). Pass 2 per document ≈ `new_entities × (≤ top_k strong verifications) × strong_cost`. Pass 1 is O(N·M·3) cheap; Pass 2 is O(new_entities·K) expensive.

**The gap:** BA-009's budget is per-provider monthly ($50 default) and the **Claude Max path bypasses it** — so the primary path is uncapped. Required guardrails:
1. **Per-run + per-document cost ceiling enforced before batch start**, independent of BA-009 (estimate from chunk count × model rate; refuse to start a run over the ceiling).
2. **Gleaning marginal-yield circuit breaker** — auto-disable round 2 when new-entity yield/100 chunks falls below a configured floor (don't pay 3× for ~1pp).
3. **Per-run token + $ surfaced in admin** (extend §9 run-status beyond model names; BR-008.4 already records the models).

**Model posture:** budget v1 on the **Haiku API** path. Local Qwen on RTX-5070-Ti is *upside* (NFR-260 admits order-of-magnitude throughput variance), benchmarked separately — never a premise the v1 cost model is load-bearing on. Portability (NFR-265) is kept as anti-lock-in insurance.

---

## 9. Phased Rollout with Numeric Gates

| Phase | Scope | Gate (measured, not asserted) |
|---|---|---|
| **8a Foundation** | OQ-001 migration (CHECK + edge-whitelist + `master_record`); `chunk_extraction_state`; internal candidates endpoint; symmetric `ValidNodeTypes` check; Pass 1 extraction + gleaning; Pass 2 single-turn contracts; embedding upsert w/ symmetric e5 prefix (same both sides); Redis dispatch **+ recovery sweep** | Pipeline runs end-to-end; **crash-recovery test passes** (kill worker mid-pipeline → chunk re-enqueued from state table → no dropped job, no duplicate `active` after BR-007.6); NFR-253 (100% closed-schema), NFR-254 (100% provenance), NFR-263 (idempotent re-ingest, zero LLM calls on unchanged path) |
| **8b Benchmark** | Funded, owned, costed VN labelled benchmark (≥30 gold chunks, ≥50 labelled same/different pairs, Vietnamese); threshold × K sweep | **Blocking recall ≥ 90% @ K=10** at start threshold **0.72–0.75** — the make-or-break gate; no resolution ships below the recall floor |
| **8c Resolution (SHADOW)** | Pass 2 writes `merge_suggestions` only (applies nothing); threshold tuning (OQ-004); un-merge **built + drilled in staging** | NFR-256 **precision ≥ 0.90**, NFR-257 **recall ≥ 0.80** measured on the benchmark; un-merge drill restores a merged node + its edges (incl. a deduped edge); cost telemetry (tokens + $ per run/doc) live |
| **8d Auto-merge GA** | Auto-merge unlocked, **degree-gated** (leaf auto, hubs suggest-only + human confirm) | Per-run **and** per-doc cost ceiling enforced; degree threshold set; un-merge runbook drilled; NFR-256's 10% tolerance applies to **leaf nodes only — never hubs** |

Build order is dependency-forced: 8a is pure prerequisite; 8b produces the gate-maker; 8c is reversible (writes nothing to the graph); 8d is the single irreversible step and goes last.

---

## 10. Risk Register (ranked)

| # | Risk | Likelihood | Impact | Acceptance condition |
|---|---|---|---|---|
| **R1** | **Blocking recall** — a pair missed at cosine blocking is invisible to the verifier *forever*; NFR-257 dies silently. Worse than a wrong-merge (which is at least downstream-detectable). | Med-High | Critical | Symmetric e5 prefix (same both sides, prefix confirmed in 8b); start threshold low (0.72–0.75); K=10; **recall ≥90% @K=10 gate at 8b** on real VN name variants |
| **R2** | **Wrong-merge propagation on high-degree hubs** (NFR-256 tolerates 10% wrong) compounded by FR-007 ingestion-order dependence (an early wrong merge becomes the canonical later docs resolve into). | Med-High | Critical (cross-system, poisons AAA) | Degree-gated review (hubs human-confirm); un-merge built+drilled; precision proven on benchmark |
| **R3** | **"Reversible" asserted, not built** — zero un-merge code exists; BR-005.11 (pre-rewrite) is lossy at the edge level. | High (true today) | High | FR-NEW-1 un-merge + §6 lossless-edge rewrite, both before 8d |
| **R4** | **Cost runaway** — no per-run/per-doc ceiling; Claude Max bypasses BA-009 budget. | High | High | FR-NEW-2 pre-batch ceiling + gleaning breaker |
| **R5** | **Benchmark debt** — the VN labelled benchmark gating every quantitative NFR is unbuilt/unfunded; Vietnamese labelling is non-trivial. | High | High | Named owner + cost line at 8b; auto-merge GA gated on it |
| **R6** | **No durable substrate** — `jobengine` is in-memory; naive "use Redis" re-ships the bug (destructive `BRPOP`). | Med | Med-High | Redis dispatch **+** `chunk_extraction_state` recovery sweep, as a coupled pair |
| **R7** | **Qwen portability doesn't materialise** → Pass 1 falls back to Haiku → cheap-Pass-1 premise reopens. | Med | Med | Budget v1 on Haiku; Qwen is benchmarked upside |
| **R8** | **Schema lock-in** (OQ-001). | Low | Low-Med | CHECK is reversible (clean down-migration); the *data* is the commitment, bounded by R2/R3 reversibility work |

---

## 11. Testing Strategy

- **Unit (Go):** edge-whitelist + symmetric node-type validation (drop-don't-coerce); merge transaction (re-point, UNIQUE-collision supersede-not-delete, provenance union with source-edge identity); optimistic-lock conflict + retry; `merged_into` chain-follow to `active` only + cycle guard (fail loud); provenance cap (NFR-267).
- **Unit (Python):** Pass 1 JSON contract parse + retry → `extract_failed`; span validation/drop; gleaning early-stop + intra-chunk dedup; Pass 2 verify/re-summary single-turn contracts; symmetric `passage:` embedding.
- **Integration:** end-to-end extract→resolve on a seeded corpus; **crash-recovery** (kill mid-pipeline, assert re-enqueue + no dup `active`); idempotent re-ingest (zero LLM calls on unchanged content_hash, zero new nodes/edges).
- **Benchmark (gates):** blocking recall ≥90% @K=10 (8b); merge precision ≥0.90 / recall ≥0.80 (8c); both on the labelled VN set.
- **Drill (gate):** un-merge restores a merged node + its edges including a deduped edge (8c), in staging, before 8d.
- **Tests encode intent (AGENTS.md Rule 9):** e.g. the merge-precision test fails if a wrong hub merge is auto-applied, not merely if counts change.

---

## 12. Non-Negotiables (joint, final)

1. **OQ-001 (A)** — DB CHECK + edge-whitelist enforcement; reject (B).
2. **Durable pipeline** — Redis dispatch **+** `chunk_extraction_state` recovery sweep (coupled).
3. **Per-run + per-doc cost ceiling**, enforced before batch start, independent of BA-009.
4. **Funded/owned/costed VN benchmark** gating OQ-004 thresholds and auto-merge GA, with a blocking-recall floor.
5. **Un-merge built + drilled** before 8d — and **edges superseded, not deleted** (§6) so un-merge is lossless.
6. **Degree-gated** human confirm for high-degree hubs.
7. **Shadow / suggest-only** resolution (8c) before any auto-apply (8d).
8. **Symmetric node-type validation** (parity with edge validation).

---

## Appendix — Provenance of this design

Synthesised from a two-round Tech-Consultant ↔ CTO debate, each grounded against the live codebase. Round 1 staked positions; Round 2 converged. The two corrections that survived adversarial review: (a) the durable substrate is **Redis transport + `chunk_extraction_state` recovery** (the DB `query_queue` is AI-query-coupled and not wired to Python — verified); (b) lossy edge dedup makes **lossless edge provenance a hard requirement** *and* degree-gating necessary (both, not either/or). The make-or-break gate is **blocking recall ≥90% @K=10 at 8b**.
