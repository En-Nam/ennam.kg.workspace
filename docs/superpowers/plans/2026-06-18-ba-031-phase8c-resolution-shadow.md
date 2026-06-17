# BA-031 Phase 8c (Resolution — Shadow Mode) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Pass 2 entity resolution that **proposes** merges without applying them: the verifier writes to a `merge_suggestions` sidecar, while the **merge transaction and un-merge are built and drilled** (in staging) so 8d can flip to auto-apply safely. Tune thresholds against the labelled benchmark. **Exit gate: merge precision ≥ 0.90 / recall ≥ 0.80 measured; un-merge drill restores a merged node + its edges (including a deduped colliding edge); cost telemetry live.**

**Architecture:** Python runs the verifier (embed new entity → 8a candidates endpoint → strong-model verify per pair → write suggestion). Go owns the merge transaction (single DB tx: alias/provenance union, canonical-name selection, member supersession with `merged_into`, **edge re-point with lossless collision handling**, audit, optimistic-lock write) and its inverse, un-merge. In 8c **nothing is applied to `knowledge_nodes`/`knowledge_edges` from the live verifier** — the merge/un-merge transactions are exercised only by the staging drill and the precision/recall benchmark.

**Tech Stack:** Go (`database/sql`, `store.Tx`, optimistic lock `store/version.go`), PostgreSQL, Python 3.12 (`AIClient.complete`, pytest), `multilingual-e5-small`.

> ## Sequential execution note (8b → 8c → 8d in one run)
> - **Build all engineering regardless of the benchmark gate.** Tasks 1–8 (sidecar, lossless edge re-point, merge tx, un-merge, handlers, verifier, re-summary, shadow orchestrator) are unit/integration-testable with synthetic fixtures + a test DB and run in the mạch. The shadow verifier writes suggestions and **applies nothing** — so building 8c never mutates the real graph.
> - **The precision/recall gate (Tasks 9–10) is PENDING-DATA without `vi_blocking_v1.json`.** If the owner dataset is a skeleton, record the gate `PENDING-DATA` (not PASS) and continue. **Do not fake a pass.** Thresholds fall back to defaults: `resolution_sim_threshold` = the value 8b's passing cell produced, else `0.74`; `resolution_top_k` = 8b's, else `10`; `merge_confidence_threshold` = `0.75`.
> - **Consequence for 8d:** because the 8c gate is PENDING-DATA in an automated run, **8d must keep `apply_mode="shadow"` and must NOT declare GA** — the apply path is built but stays disabled (see 8d note).
> - **Un-merge drill (Task 10) still runs** — it uses synthetic seed data + a test DB, not the VI dataset, so it is a real PASS/FAIL in the mạch.
> - Migration: 8c uses **000064**; environment-dependent integration steps that need the live stack/model → mark DEFERRED if unavailable (Rule 12), never skip silently.

## Global Constraints

- **Shadow only:** the production verifier writes `merge_suggestions`, never mutates the graph. Apply is 8d.
- **BR-005.11 LOSSLESS (rewrite from BA-031):** on an edge re-point UNIQUE(`source_id,target_id,edge_type`) collision, the surviving edge **absorbs** the duplicate's `provenance[]` (union, de-dup) **recording source-edge identity** (the superseded edge id per absorbed entry); the duplicate edge is **superseded (flagged `superseded_by_merge` in `properties`, row retained), never deleted**. Node merges retain the member (`status=superseded` + `merged_into`). Both directions reconstructable by un-merge.
- **Merge concurrency (BR-005.10):** the canonical write uses the existing optimistic lock (`UpdateNode` `WHERE version = expected`, `ErrVersionConflict` → re-read + retry). The `merged_into` chain is followed only to a node whose `status = active`; a cyclic step is rejected and logged (fail loud).
- **No cross-type / cross-project merge** (FR-004/BR-004.6, NFR-266): the verifier only ever sees same-type, same-project candidate pairs (guaranteed by the 8a candidates endpoint).
- **Qwen-portable prompts (NFR-265):** verify and re-summarise are **separate** single-turn JSON-in/JSON-out calls; no chat thread.
- **Thresholds:** start from the values 8b's passing grid cell produced (`resolution_sim_threshold`, `resolution_top_k`); `merge_confidence_threshold` default 0.75, tuned here.
- **Go:** `make -C ennam.kg.go test lint build`. **Next free migration is `000064`** (8a shipped 000061/000062/000063 — verified). Use **`uuid_generate_v4()`** for PKs (repo convention, e.g. 000006/000060 — `gen_random_uuid()` is NOT used here). Unique-violation detection uses **lib/pq**: `if pqErr, ok := err.(*pq.Error); ok && pqErr.Code == "23505"` (pattern at `store/apikey.go:327`). **Read before write:** `version.go` `UpdateNode` **replaces** `properties` wholesale — always read current `properties`, merge fields in, write the full object back (see memory: partial update replaces properties).
- **Python:** `cd ennam.kg.python && uv run pytest`. Verifier under `src/ennam_kg/resolution/`.

---

## File Structure

- `ennam.kg.go/db/migrations/000064_merge_suggestions.up.sql` / `.down.sql` — sidecar table.
- `ennam.kg.go/internal/store/merge_suggestion.go` (+ test) — sidecar CRUD.
- `ennam.kg.go/internal/store/edge_repoint.go` (+ test) — re-point + lossless collision supersede.
- `ennam.kg.go/internal/service/merge.go` (+ test) — merge transaction (orchestrates store ops).
- `ennam.kg.go/internal/service/unmerge.go` (+ test) — inverse of merge.
- `ennam.kg.go/internal/handler/merge.go` (+ test) — `POST /api/v1/internal/resolution/merge` (used by drill + 8d) and `POST /api/v1/internal/resolution/unmerge`.
- `ennam.kg.python/src/ennam_kg/resolution/{__init__,verify,resummarise,pass2}.py` (+ tests) — verifier + re-summarise + orchestrator (shadow).
- `ennam.kg.python/src/ennam_kg/benchmark/merge_eval.py` (+ test) — precision/recall of the merge decision (extends 8b).

---

## Task 1: `merge_suggestions` sidecar table + store

**Files:**
- Create: `db/migrations/000064_merge_suggestions.up.sql`, `.down.sql`
- Create: `internal/store/merge_suggestion.go`, `merge_suggestion_test.go`

**Interfaces:**
- Produces: `type MergeSuggestion struct { ID, ProjectID, NodeAID, NodeBID, ProposedCanonicalID, ResolutionModel, Reason, Decision string; EmbeddingSimilarity, MergeConfidence float64; DegreeMax int }`; `func (s *MergeSuggestionStore) Insert(ctx, MergeSuggestion) (string, error)`; `func (s *MergeSuggestionStore) ListByProject(ctx, projectID, decision string, limit, offset int) ([]MergeSuggestion, error)`; `func (s *MergeSuggestionStore) UpdateDecision(ctx, id, decision string) error`.

- [ ] **Step 1: Write the migration**

```sql
CREATE TABLE IF NOT EXISTS merge_suggestions (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id            UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    node_a_id             UUID NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    node_b_id             UUID NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    embedding_similarity  REAL NOT NULL,
    merge_confidence      REAL NOT NULL,
    proposed_canonical_id UUID NOT NULL,
    resolution_model      TEXT NOT NULL,
    reason                TEXT NOT NULL DEFAULT '',
    degree_max            INTEGER NOT NULL DEFAULT 0,
    decision              TEXT NOT NULL DEFAULT 'suggested'
                          CHECK (decision IN ('suggested','applied','rejected','needs_review')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_merge_suggestions_project_decision
    ON merge_suggestions (project_id, decision);
```

`.down.sql`: `DROP TABLE IF EXISTS merge_suggestions;`

- [ ] **Step 2: Failing store test** — insert a suggestion, list by `(project, 'suggested')`, assert round-trip; `UpdateDecision` to `applied` then list `'suggested'` returns 0. Run `go test ./internal/store/ -run MergeSuggestion` → FAIL (undefined).
- [ ] **Step 3: Implement `merge_suggestion.go`** (Insert/List/UpdateDecision using `database/sql`).
- [ ] **Step 4: Run test → PASS.**
- [ ] **Step 5: Commit** `feat(ba031-8c): merge_suggestions sidecar table + store`.

---

## Task 2: Edge re-point + lossless collision supersede (Go store)

The riskiest store primitive. Re-points a superseded member's edges to the canonical node; on a UNIQUE collision, unions provenance into the survivor (with source-edge identity) and supersedes the duplicate without deleting it.

**Files:**
- Create: `internal/store/edge_repoint.go`, `edge_repoint_test.go`

**Interfaces:**
- Consumes: `*sql.Tx`.
- Produces: `func (s *EdgeStore) RepointEdgesTx(ctx, tx *sql.Tx, memberID, canonicalID, mergeOpID string) (repointed int, collided int, err error)` — for each edge with `source_id=memberID` (and symmetrically `target_id=memberID`): attempt `UPDATE knowledge_edges SET source_id=canonicalID WHERE id=$edge`; on UNIQUE violation, instead (a) read the surviving edge `(canonicalID,target,edge_type)`, (b) union the member edge's `properties.provenance` into the survivor's, tagging each absorbed entry with `from_edge_id=<member edge id>`, (c) set the member edge's `properties.superseded_by_merge=mergeOpID` (retain row, leave its `source_id=memberID`). Returns counts.

- [ ] **Step 1: Write failing tests (real test DB)** covering: (a) a non-colliding edge is re-pointed (`source_id` becomes canonical); (b) a colliding edge — canonical already has the same `(target,edge_type)` — results in the survivor's provenance containing both entries tagged with `from_edge_id`, the duplicate row retained with `superseded_by_merge` set, and **no UNIQUE violation surfaced** to the caller; (c) edge count unchanged (nothing deleted).

```go
func TestRepoint_CollisionUnionsProvenanceAndSupersedes(t *testing.T) {
	// Arrange: member M and canonical C both have works_for -> Org, each with 1 provenance entry.
	// Act
	rep, col, err := edgeStore.RepointEdgesTx(ctx, tx, M, C, "op1")
	// Assert
	if err != nil { t.Fatal(err) }
	if col != 1 { t.Fatalf("want 1 collision, got %d", col) }
	surv := readEdge(C, Org, "works_for")
	assertProvenanceLen(t, surv, 2)                       // unioned
	assertEachAbsorbedTaggedFromEdge(t, surv)             // source-edge identity recorded
	dup := readEdge(M, Org, "works_for")
	assertSupersededByMerge(t, dup, "op1")               // retained, flagged
	assertTotalEdgeCountUnchanged(t)                      // nothing deleted
}
```

- [ ] **Step 2: Run → FAIL** (`go test ./internal/store/ -run TestRepoint_`).
- [ ] **Step 3: Implement `RepointEdgesTx`.** Use a savepoint per edge: `SAVEPOINT rp; UPDATE ... ;` — on a **lib/pq** unique violation (`if pqErr, ok := err.(*pq.Error); ok && pqErr.Code == "23505"`, pattern at `store/apikey.go:327`), `ROLLBACK TO SAVEPOINT rp` and run the union-and-supersede path; else `RELEASE SAVEPOINT rp`. Read/modify/write `properties` JSON in Go (don't try to do JSON surgery in SQL). Handle both `source_id=memberID` and `target_id=memberID` edges.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat(ba031-8c): lossless edge re-point (collision union + supersede, never delete)`.

---

## Task 3: Merge transaction (Go service)

**Files:**
- Create: `internal/service/merge.go`, `merge_test.go`

**Interfaces:**
- Consumes: `store.BeginTx`, `NodeStore`/`VersionStore` (optimistic `UpdateNode`), `EdgeStore.RepointEdgesTx` (Task 2), `NodeEmbeddingStore` (conditional re-embed).
- Produces: `func (s *MergeService) Merge(ctx, req MergeRequest) (*MergeResult, error)` where `MergeRequest{ProjectID, MemberID, CanonicalID, Confidence float64, ResolutionModel, Reason, MergedDescription *string}`. Steps in one tx:
  1. Resolve the **live** canonical by following `properties.merged_into` from `CanonicalID` to a `status=active` node; reject a cyclic/visited chain (fail loud, BR-005.10).
  2. Read both nodes + the canonical's `version`.
  3. Compute merged `aliases` (union member.canonical_name + both aliases, case-insensitive de-dup), select surviving `canonical_name` (the model's pick in `req`, else longer string), union `provenance`.
  4. If `MergedDescription != nil`, **first stamp the pre-merge `description` + embedding `content_hash` into a reversal record under `mergeOpID`** (e.g. `properties.merge_undo[mergeOpID] = {prev_description, prev_content_hash}`), then set the new description (FR-006); recompute `content_hash` and re-embed **only if** the embedded text changed (BR-006.4). Without this stamp, re-summarisation is irreversible and the Task 4 byte-equivalence assertion cannot hold.
  5. `RepointEdgesTx(member → canonical, mergeOpID)`.
  6. Supersede member: `UpdateNode(member, status="superseded", properties+={merged_into: canonical, superseded_by_merge: mergeOpID}, change_reason="pass2_merge")`.
  7. Append a `resolution_audit` entry on the canonical (`{decision:"confirmed", confidence, resolution_model, peer_node_id: member, reason}`) and `UpdateNode(canonical, expected_version, properties+={aliases, provenance, canonical_name, resolution_audit})`. On `ErrVersionConflict` → re-read canonical + retry the canonical write (bounded retries).
  Returns `MergeResult{CanonicalID, MergeOpID, RepointedEdges, CollidedEdges}`.

- [ ] **Step 1: Failing tests (test DB)** — (a) happy-path merge: member becomes `superseded` with `merged_into`, canonical gains aliases+provenance+audit, a member edge re-pointed; (b) transitive: member matches an already-merged node → resolves to the live canonical C; (c) cycle: a `merged_into` chain that revisits a node → error + nothing written; (d) optimistic conflict: simulate a stale version → retry succeeds.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement `merge.go`** per the steps. Keep chain-follow + cycle guard in one helper with a visited set; do all writes inside `tx`; roll back on any error (fail loud).
- [ ] **Step 4: Run → PASS** (`go test ./internal/service/ -run Merge`).
- [ ] **Step 5: Commit** `feat(ba031-8c): merge transaction (chain+cycle guard, optimistic lock, audit)`.

---

## Task 4: Un-merge (Go service) — FR-NEW-1

The inverse of Task 3. Required, built, and drilled before 8d.

**Files:**
- Create: `internal/service/unmerge.go`, `unmerge_test.go`

**Interfaces:**
- Produces: `func (s *UnmergeService) Unmerge(ctx, mergeOpID string) (*UnmergeResult, error)` — in one tx: (1) find the member node with `properties.superseded_by_merge == mergeOpID`; (2) restore it to `status=active`, remove `merged_into`/`superseded_by_merge`; (3) un-repoint: edges re-pointed by this op (tagged in the canonical's edge provenance with `from_edge_id` for absorbed entries; and member-side edges flagged `superseded_by_merge==mergeOpID`) are restored — re-point the moved edges back to the member, and for collision-superseded edges remove the `superseded_by_merge` flag and **subtract** the absorbed provenance entries (those tagged `from_edge_id` of the restored edge) from the survivor; (4) remove the matching `resolution_audit` entry + the aliases/provenance the merge added to the canonical (identifiable because provenance/aliases carry the member origin); (5) **restore the canonical's pre-merge `description` + embedding from the `merge_undo[mergeOpID]` stamp** (Task 3 step 4) and re-embed if `content_hash` changed back. Returns what was restored.

- [ ] **Step 1: Failing drill test (test DB)** — perform a merge (Task 3) that includes BOTH a re-pointed edge and a collision-superseded edge, then `Unmerge(mergeOpID)`; assert the graph is **byte-equivalent** to the pre-merge state: member `active`, no `merged_into`; edges back on the member; canonical's aliases/provenance/audit reverted; the previously-superseded duplicate edge active again.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement `unmerge.go`.** To make this tractable, the merge (Task 3) must stamp every mutation it makes with `mergeOpID` (already: member `superseded_by_merge`, absorbed provenance `from_edge_id`, audit entry, and an `added_by_merge_op` tag on aliases/provenance the merge appended to the canonical). Un-merge reverses exactly those stamped mutations. Add the `added_by_merge_op` stamping to Task 3 if not already present (update Task 3 + its tests accordingly).
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat(ba031-8c): un-merge (reverses a stamped merge op; lossless)`.

> Note: this couples Tasks 3 and 4 — the merge must **stamp** its mutations with `mergeOpID` for un-merge to reverse them precisely. If Task 3 was implemented without full stamping, extend it here and re-run its tests.

---

## Task 5: Merge/un-merge handlers

**Files:**
- Create: `internal/handler/merge.go`, `merge_test.go`; register routes.

**Interfaces:**
- Produces: `POST /api/v1/internal/resolution/merge` (body → `MergeRequest`) and `POST /api/v1/internal/resolution/unmerge` (`{merge_op_id}`). Admin/service-gated. Used by the drill and by 8d's apply path.

- [ ] **Step 1: Failing handler test** (merge then unmerge via HTTP, assert 200 + result shape). **Step 2:** FAIL. **Step 3:** implement + register. **Step 4:** PASS. **Step 5:** commit `feat(ba031-8c): merge/unmerge internal endpoints`.

---

## Task 6: Pass 2 verifier (Python, shadow) — FR-005

**Files:**
- Create: `src/ennam_kg/resolution/{__init__,verify}.py`
- Test: `tests/resolution/test_verify.py`

**Interfaces:**
- Consumes: `AIClient.complete(AIRequest) -> AIResponse` (single-turn JSON), the 8a candidates endpoint via the **shared `HttpxRetriever` from `ennam_kg.resolution.candidates_client`** (created in 8b — import, do not re-implement).
- Produces:
  - `VERIFY_PROMPT` + `build_verify_request(a:dict, b:dict) -> AIRequest` — JSON in `{a:{name,aliases,description,type}, b:{...}}`, expects JSON out `{same_entity:bool, confidence:float, canonical_name:str, reason:str}`.
  - `parse_verify_response(text:str) -> VerifyVerdict` — strict parse; on non-JSON after retry, raise (caller records a `rejected` suggestion with reason `verify_parse_failed`, fail loud).
  - `verify_pair(client, a, b) -> VerifyVerdict`.

- [ ] **Step 1: Failing tests** — `parse_verify_response` parses a valid verdict and rejects malformed; `build_verify_request` is single-turn (no chat history). Mock `AIClient`. **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** commit `feat(ba031-8c): Pass2 verifier prompt + parse (single-turn JSON)`.

---

## Task 7: Re-summarisation (Python) — FR-006

**Files:**
- Create: `src/ennam_kg/resolution/resummarise.py`; Test: `tests/resolution/test_resummarise.py`

**Interfaces:**
- Produces: `build_resummarise_request(descriptions:list[str], max_chars:int) -> AIRequest` (separate single-turn call) and `parse_resummarise_response(text:str, max_chars:int) -> str` — returns a single merged description; rejects/regenerates if it exceeds `max_chars` or equals the literal ordered concatenation of inputs (NFR-262).

- [ ] **Step 1: Failing tests** — output is not the literal concatenation; respects `max_chars`. Mock model. **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** commit `feat(ba031-8c): merged-description re-summarisation (not concatenation)`.

---

## Task 8: Pass 2 orchestrator (shadow) — writes suggestions only

**Files:**
- Create: `src/ennam_kg/resolution/pass2.py`; Test: `tests/resolution/test_pass2.py`

**Interfaces:**
- Consumes: `verify_pair`, `build_resummarise_request`, the shared `HttpxRetriever` from `ennam_kg.resolution.candidates_client` (8b), the `KGClient` (read node detail; **write `merge_suggestions` via a new `KGClient.create_merge_suggestion` hitting a Go endpoint** — add a thin POST `/api/v1/internal/resolution/suggestions` in Go store/handler, or reuse an existing suggestion-write path; decide and note), `embed_entity` (8a).
- Produces: `async def run_pass2_shadow(doc_id, run_id, project_id, deps) -> Pass2Summary{entities, candidates, suggestions, rejected}` — for each new entity: embed → candidates (same-type, ≥ threshold, top-K) → for each candidate `verify_pair` → if `confidence >= merge_confidence_threshold` compute proposed canonical + (optional) re-summary → **write a `merge_suggestions` row with `decision='suggested'`** (degree_max recorded for 8d). **Applies nothing to the graph.**

- [ ] **Step 1: Failing test (all deps mocked)** — new entity with one true-duplicate candidate (verdict confidence 0.9) produces exactly one `suggested` row with `proposed_canonical_id` set; a low-confidence candidate produces no suggestion; **no node/edge mutation** (assert the fake KG client recorded zero node/edge writes). **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. **Step 5:** commit `feat(ba031-8c): Pass2 shadow orchestrator (suggestions only, no apply)`.

> Sub-step in Task 8: add the Go suggestion-write endpoint + `MergeSuggestionStore.Insert` wiring (`POST /api/v1/internal/resolution/suggestions`) and the `KGClient.create_merge_suggestion` client method. Test the Go endpoint (handler test) and the client call.

---

## Task 9: Merge precision/recall benchmark (extends 8b) + threshold tuning

**Files:**
- Create: `src/ennam_kg/benchmark/merge_eval.py`; Test: `tests/benchmark/test_merge_eval.py`

**Interfaces:**
- Consumes: the 8b labelled dataset (`gold_entity_id`), `verify_pair` (real or mock model), the candidate blocking from 8b.
- Produces: `evaluate_merge(benchmark, blocked_pairs, verdicts, confidence_threshold) -> MergeScore{precision, recall, tp, fp, fn}` — a predicted merge = a verified pair with `confidence >= threshold`; precision = tp/(tp+fp), recall = tp/(tp+fn) against `gold_entity_id` equality; and a CLI/threshold sweep over `merge_confidence_threshold`.

- [ ] **Step 1: Failing tests** — synthetic verdicts over `sample.json` give known precision/recall; a wrong high-confidence merge counts as fp (precision drops). **Step 2:** FAIL. **Step 3:** implement metric + sweep. **Step 4:** PASS. **Step 5:** commit `feat(ba031-8c): merge precision/recall eval + confidence-threshold sweep`.

---

## Task 10: Staging drill + Phase 8c gate

**Files:**
- Create: `internal/integration/ba031_resolution_test.go`; a short `docs/superpowers/runbooks/ba031-unmerge-drill.md`.

- [ ] **Step 1: Un-merge drill (integration, real DB)** — seed two true-duplicate `person` nodes (one with a colliding edge), call `/internal/resolution/merge`, assert merged, then `/internal/resolution/unmerge`, assert byte-equivalent restore (reuse Task 4 assertions at the HTTP level).
- [ ] **Step 2: Shadow no-mutation test** — run `run_pass2_shadow` over a seeded doc, assert `merge_suggestions` rows created and **node/edge counts unchanged**.
- [ ] **Step 3: Run the merge precision/recall benchmark** on `vi_blocking_v1.json` with the real model; record `precision`/`recall` and the chosen `merge_confidence_threshold`.
- [ ] **Step 4: Gate decision (logged, Rule 12)** — PASS iff precision ≥ 0.90 AND recall ≥ 0.80 AND the un-merge drill restores byte-equivalent state. Record the chosen thresholds for 8d via `extraction-config`. A FAIL blocks 8d and is surfaced (re-tune threshold / revisit OQ-002/OQ-003).
- [ ] **Step 5: Commit** `test(ba031-8c): resolution gate — shadow no-mutation, un-merge drill, precision/recall`.

---

## Phase 8c Done — Definition of Done

- [ ] `merge_suggestions` sidecar live; verifier writes suggestions, **applies nothing** (Tasks 1, 6–8, 10).
- [ ] Merge transaction: chain+cycle guard, optimistic lock, audit, **lossless edge re-point** (Tasks 2, 3).
- [ ] **Un-merge built + drilled**: byte-equivalent restore including a deduped colliding edge (Tasks 4, 5, 10).
- [ ] Merge **precision ≥ 0.90 / recall ≥ 0.80** measured on `vi_blocking_v1.json`; `merge_confidence_threshold` chosen (Tasks 9, 10).
- [ ] `make -C ennam.kg.go test lint build` clean; `cd ennam.kg.python && uv run pytest` green.

## Verified at plan-review time (2026-06-18)
- Next migration is **000064** (8a shipped 000061/062/063). uuid PK uses **`uuid_generate_v4()`**. Driver is **lib/pq** → `pq.Error.Code == "23505"`. `knowledge_edges` has **no status column** (only `properties` JSONB) → edge supersession via `properties.superseded_by_merge` is the right mechanism. `version.go UpdateNode` replaces `properties` wholesale (read-merge-write). `AIClient.complete(AIRequest)->AIResponse` with `AIRequest{prompt, system_prompt, response_format="json", request_type}` and `AIResponse.content:str` — verify/re-summary use `response_format="json"`. `store.Tx`/`BeginTx`, `CreateEdgeTx`, optimistic `UpdateNode` + `ErrVersionConflict` all present. A supersede pattern exists at `handler/deprecate.go`.

## Soft spots (read before writing)
(a) whether read paths (traversal/neighbors) already filter to `active` nodes so superseded-member colliding edges are naturally excluded (Task 2/3 — confirm, else add a filter); (b) the `KGClient` method to read full node detail incl. `properties` for the verifier (Task 8); (c) where to register the new internal routes (Tasks 5, 8 — follow the `RegisterRoutes` pattern used by `resolution_candidates.go`/`extraction.go`).

## Self-Review
- **Spec coverage (8c):** FR-005 → Tasks 3, 6; FR-006 → Task 7; BR-005.11 lossless → Task 2; BR-005.10 chain/cycle/optimistic → Task 3; FR-NEW-1 un-merge → Tasks 4, 5, 10; FR-NEW-6 shadow/`merge_suggestions` → Tasks 1, 8; OQ-004 tuning + NFR-256/257 gate → Tasks 9, 10; NFR-262 re-summary-not-concat → Task 7; NFR-264 auditability → Task 3. Degree-gating apply + cost ceiling are **8d** (out of 8c scope; `degree_max` is *recorded* here for 8d).
- **Placeholder scan:** no TBD/TODO; the riskiest Go logic (Tasks 2–4) has concrete steps; Python verifier/re-summary have real parse contracts.
- **Type consistency:** `MergeSuggestion`/store methods, `RepointEdgesTx`, `MergeRequest`/`MergeResult`/`Merge`, `Unmerge`, `VerifyVerdict`/`verify_pair`, `run_pass2_shadow` referenced identically across tasks. Task 4 explicitly couples back to Task 3 (mergeOp stamping).
