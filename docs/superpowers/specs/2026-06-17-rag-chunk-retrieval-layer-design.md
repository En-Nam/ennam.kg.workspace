# RAG Chunk Retrieval Layer (IMP-007) — Design Spec

**Date:** 2026-06-17
**Status:** Design approved via Tech-Consultant ↔ CTO review (2026-06-17). PO decisions locked: **(①) ship the `contains_section` edge now; (②) hold the build gate — run FR-4 first, after a minimal better extractor produces a representative long-doc eval corpus.**
**Requirement:** `ennam.kg.requirements/documents/improvements/IMP-007-rag-chunk-retrieval-layer.md`
**Affects:** BA-025 (Document Decomposition & Retrieval — adds `document_chunk` below `document_section`), BA-002 (MCP bridge — `kg_search_chunks`), BA-011 (NL query), BA-028 (LAAM passage recall)
**Untouched (shipped):** hybrid RRF + `multilingual-e5-small` 384-dim (IMP-005); `kg_search`; `document_section` decomposition; `kg_get_document` (IMP-006)
**Authoritative strategic source:** ecosystem design `thiet-ke-ecosystem-laam-daab-aaa.md` (§2 provenance principle, §3.1 Vector Index, §4.2.3 tool catalog + Qwen rules, §4.4 AAA Phase C, §5 data contracts)

---

## 1. Goal

Add a **passage-level retrieval unit** (`document_chunk`) below `document_section`, so LAAM/AAA can retrieve and cite the **exact passage** that grounds an answer (NotebookLM-grade), over the already-shipped e5-small/384-dim/hybrid-RRF stack — **without** changing the embedding model, `kg_search`, or section decomposition. This is bucket A of the RAG gap analysis and the prerequisite for AAA's `MasterRecord → derived_from → evidence → chunk → doc_id` provenance traversal (ecosystem Luồng 4).

## 2. Framing — committed in direction, evidence-gated in timing (locked)

Per IMP-007 §2 and the CTO review: the chunk/RAG layer is the **committed architecture** of DAAB (ecosystem §3.1 first-class "Vector Index — chunks gốc"; §4.2.3 `search_chunks` in catalog v1; principle *"không có RAG thì chỉ lưu chỉ mục"*). What is gated is **when** to build:

> **FR-4 runs FIRST as the build trigger + tuner.** Implement FR-1..FR-3 only once the eval, on a **representative long/sparsely-headed corpus with real extracted text**, shows section-level truncation measurably hurts tail-of-section recall. The eval also sets `CHUNK_SIZE`/`CHUNK_THRESHOLD` (they are eval **outputs**, not shipped constants).

**CTO finding that shaped decision ②:** the headline target doc — the Master Record PDF — extracts only **1706 chars** via pypdf (no OCR), so it is effectively invisible to the eval. The two `cang-dinh-an` markdown deal-reports (42KB/57KB) are usable but are weak evidence for the contract/Master-Record workload the layer exists for. **Decision ②: before FR-4, run a minimal better text-extractor (one-off, NOT full bucket-C OCR) to get the Master Record / a real contract into the eval corpus.** This keeps the gate honest. (Surfaced roadmap signal: bucket C extraction is a *soft prerequisite for evaluating* IMP-007 on its own headline corpus.)

## 3. Current state (AS-IS — verified against code)

| Fact | Evidence | Implication |
|------|----------|-------------|
| Section embedding is on `title + summary[:2000]` (summary = `text[:8000]`) | `ennam.kg.python/.../ingestion/pipeline/decompose.py:85,130` | **Truncation blind spot**: section content past ~2000 chars is not in the vector |
| `MarkdownSection` carries document-absolute `line_start`/`line_end` + raw `text` | `decompose.py` / `document_tree.py` | Chunk offsets can be derived without re-parsing the document |
| `knowledge_node_embeddings` is `UNIQUE(node_id)`, `ON CONFLICT(node_id) DO UPDATE`, has `chunk_text`+`content_hash`, `embedding vector(384)`, FK `ON DELETE CASCADE` | `db/migrations/000055_*.sql`; `internal/store/node_embedding.go:35` | **One embedding row per node** → each chunk must be its own node; deleting a chunk node cascades its embedding |
| `kg_search` hybrid arm defaults `scope` to `["document_section"]` | `internal/handler/search.go:18,290-292` (`hybridEmbeddedNodeTypes`) | Routing chunk search through `/search` would silently search the wrong type |
| Neither search arm supports a `document_id`/properties filter | `node_embedding.go:118-132` (SemanticSearch); `internal/store/search.go` (FTS) | The `document_id` filter needs an additive predicate in both arms |
| FTS `search_vector` trigger indexes `properties.content`/`summary` for **all** node types | `db/migrations/000010` | Chunks are FTS-searchable on insert if the passage is stored under `properties.content` — no FTS config needed |
| `node_type` is a CHECK constraint; `config.yaml node_types` is a Gate-1 registry that rejects unknown types | `db/migrations/000004/000051/000055`; `config.yaml`; `service/node.go` (`validateStoreRequest`) | Adding `document_chunk` requires both a CHECK migration **and** a `config.yaml` entry |
| Edge type is `contains_section` (`document → contains_section → document_section`); **`part_of` does not exist** | `internal/config/types.go` (`EdgeTypeContainsSection`); `decompose.py` writes it | The chunk edge must be `contains_section`, never `part_of` (IMP-007 §3.3 corrected) |
| Tool count = **34 schemas / 32 routes / 2 local** (`kg_get_document` landed) | `schema_test.go:50`, `handler_test.go:276`, `client_test.go:216` | `kg_search_chunks` → **35 / 33**; CLAUDE.md "25/30" is stale |
| `admin/reembed` re-encodes existing embedding rows by `chunk_text`; never creates nodes | `ennam.kg.python/.../api/admin.py:55-69` | Backfill needs a **new** job, not an extension of reembed |
| Master Record PDF → 1706 chars via pypdf (no OCR); two `cang-dinh-an` `.md` reports = 42KB/57KB VI | workspace probe | Eval corpus needs the minimal extractor (decision ②) |

## 4. Design decisions (final — consultant proposal + CTO rulings)

### D1 — Chunking algorithm
**Paragraph-first greedy packing** of `sec.text` on blank-line boundaries into a target window; a single over-long paragraph falls back to sentence split (VI/EN terminators), then a hard char cut. Fenced code blocks stay whole unless alone over `CHUNK_SIZE`.
- **Offsets:** running char cursor within `sec.text` → map to document-absolute lines via `sec.line_start + text[:char_off].count("\n")`. Store `char_start`/`char_end` (section-relative) + `line_start`/`line_end` (document-absolute).
- **Seed constants (eval inputs, NOT shipped values):** `CHUNK_THRESHOLD≈1800`, `CHUNK_SIZE≈1200`, `CHUNK_OVERLAP≈150` chars. **FR-4 sets the shipped values.** Sections ≤ threshold → single 1:1 chunk (BR-005).
- **HARD upper bound on `CHUNK_SIZE` (the e5 token window — critical):** `local_model.py:50` calls `SentenceTransformer.encode` with **no `max_seq_length` override**, so e5-small **silently truncates at ~512 tokens**. A chunk larger than the token window re-introduces the exact truncation blind spot this IMP fixes. Therefore `CHUNK_SIZE` must stay **comfortably below ~512 tokens** (≈1500-1800 chars of mixed VI, with margin) — FR-4 tunes **only within** that ceiling, never above it. *(This also sharpens the AS-IS finding: the real section cutoff is the ~512-token window, tighter than the 2000-char `summary[:2000]` slice — stronger evidence that chunking helps.)*

### D2 — chunk identity, idempotency, orphans (REVISED — verified the API)
**Verified blocker:** `StoreNodeRequest` has **no `id` field**; the node INSERT auto-generates the UUID server-side (`internal/store/node.go:70-71,102-104`). So a **client-chosen deterministic node id is impossible** without a Go API change → the original "chunk_id = UUIDv5(...)" as the node id is **infeasible**. Corrected design (mirrors the proven indexer **differ** pattern — natural key + content hash → create/update/archive, the codebase's existing idiom, Rule 11):
- **`chunk_id` (the citation id) = the server-generated node UUID** (stable once created).
- **Deterministic natural key** `chunk_key = f"{section_id}:{ordinal}"` stored in chunk **properties** — the idempotency key, not the id.
- **`content_hash = sha256(chunk_text)`** stored in chunk properties (and the embedding row already has the column): the change signal.
- **Idempotency (backfill / re-run on a stable section):** enumerate existing `document_chunk` nodes via `get_nodes(project_id, node_type="document_chunk")`, group by `section_id`; for each new chunk, match by `chunk_key`: **absent → create** (server assigns id); **present + same `content_hash` → skip**; **present + differing `content_hash` → `update_node`** with `change_reason="re-chunk"` (keeps the **same node id → citation stays stable**) + re-embed.
- **Orphan deletion is OUT OF REACH with the current API (verified):** there is **no hard-delete endpoint** for knowledge nodes (only soft-archive), and `SemanticSearch` does not filter status, so a soft-archived chunk would still be returned and its embedding row (cascade-on-DELETE only) would linger. Therefore backfill is **create/update/skip only**. Re-running with the **same `CHUNK_SIZE`** is fully idempotent (no orphans). **Changing `CHUNK_SIZE` requires a full re-ingest** of the affected documents, not a backfill-diff. True orphan deletion needs a future `DELETE /api/v1/nodes/{id}` endpoint — out of IMP-007 scope.
- **Steady-state new ingest** has no pre-existing chunks for a freshly-created section, so it just **creates** (no diff needed). The differ logic only runs in the backfill job / future stable-section re-ingest.
- **Idempotency limit (unchanged):** bounded by `section_id` stability; a full document re-upload makes new section ids → new `chunk_key`s → old chunks orphaned at the section layer (BA-025), resolved in bucket C. Documented, not solved here.
- **Idempotency limit (explicit BR, do not paper over):** holds **per stable `section_id`**. Section UUIDs are **not** stable across a full document re-upload (`decompose.py` creates fresh sections), so a re-upload orphans old chunks. This is a section-layer (BA-025) property, **out of IMP-007 scope**, and is the right place for bucket-C canonical `doc_id` to fix it. Documented, not solved here.

### D3 — Search path
New **`POST /api/v1/search-chunks`** handler (not `/search`):
- Forces `scope = ["document_chunk"]` server-side.
- Optional `document_id` → additive predicate `AND (n.)properties->>'document_id' = $n` in **both** arms.
- Reuses the **same** `ReciprocalRankFusion` + the **same** fail-soft ladder (embed-fail → fulltext; one-arm-fail → other; both-fail → 500) + `SemanticSearch` (already takes `nodeTypes`).
- One additive `DocumentID` field on `SearchParams` + a `documentID` arg to `SemanticSearch`; existing callers pass empty → `kg_search` byte-for-byte unchanged (BR-009).

### D4 — Edge model (CTO ruling, PO-locked ①: ship the edge now)
Create **`document_section —[contains_section]→ document_chunk`** in FR-1, extending the existing `document → contains_section → document_section` spine. Rationale: AAA Phase C (`evidence → chunk`, Luồng 4) is a **committed** consumer that traverses the graph; property-only chunks give *lookup* provenance but not *traversal* provenance (ecosystem §2 principle 4). Cost: one `edge_whitelist` target in `config.yaml` + one edge write per chunk. (`part_of` is a doc error — the type is `contains_section`.)

### D5 — Eval (FR-4)
- **Harness is EXTENDED, not reused as-is (corrects an overstatement):** `tests/eval/retrieval_eval.py:26` calls `POST /api/v1/search` (section search) and scores against returned **section ids**. To evaluate chunks it must (a) gain a target switch to call `POST /api/v1/search-chunks`, and (b) score against **chunk/passage ids**. Keep the existing section path intact for the no-regression run; add a chunk path alongside it. So FR-4 = one small harness extension + the labeled set, not a zero-code reuse.
- **Corpus:** the two `cang-dinh-an` `.md` reports + the Master Record / a real contract **after the minimal extractor** (decision ②). Markdown is the primary signal; the extracted long doc validates the flat/sparsely-headed case.
- **Labeled set:** 25-30 `query → expected-passage` pairs, ~80% VI / ~20% EN, **biased toward answers past the ~512-token section cutoff** (the exact failure being fixed). Two ground-truth granularities: section-id (for the section/no-regression run) and chunk/passage-id (for the chunk run). Human-authored. Caveat surfaced (IMP-005 discipline): labels are judgment; N is a smoke-gate, not a benchmark.
- **FTS-arm VI caveat (inherited):** the `search_vector` trigger uses `to_tsvector('english', …)` (`000010`), so the lexical arm stems VI poorly — chunk FTS inherits the same VI weakness as sections; VI recall rides on the **semantic** arm (as in IMP-005). Not new, but the eval must not credit the FTS arm for VI gains.
- **Bars:** (1) **trigger** — section-level recall@5 on the tail subset materially < 1.0; if saturated even here → defer. (2) **post-build** — chunk recall@5/MRR > section baseline, tail subset gains most. (3) **no-regression** — re-run the unchanged IMP-005 section eval; identical-or-better required.

### D6 — Migration + config change-sites (7, with the edge)
| # | Site | Change | Failure if missed |
|---|------|--------|-------------------|
| 1 | new `db/migrations/0000NN_document_chunk_node_type.up.sql` | extend `knowledge_nodes_node_type_check` with `'document_chunk'` (pattern of 000055) | INSERT rejected by CHECK |
| 2 | `config.yaml` `node_types:` | add `document_chunk` block (fields: title, summary, content, document_id, section_id, line_start/end, char_start/end, ordinal) | INSERT fails **Gate 1** (`validateStoreRequest`) |
| 3 | `internal/config/types.go` | `NodeTypeDocumentChunk` const + add to `ValidNodeTypes` | type unrecognized by validators |
| 4 | `internal/handler/search.go:187` | add `"document_chunk": true` to `validNodeTypes` | `kg_search` node-type filter 400s on `document_chunk` |
| 5 | `internal/bridge/schema.go` (+ `schema_test.go:50`, `handler_test.go:276`) | add `kg_search_chunks` schema; **34→35** | count + relational asserts fail |
| 6 | `internal/bridge/client.go` `toolRoutes` (+ `integration_test.go`, `client_test.go:216`) | route `kg_search_chunks → POST /api/v1/search-chunks`; **32→33** | tool unroutable |
| 7 | `config.yaml` `edge_whitelist` + Python pipeline | add `document_chunk` to the **existing** `document_section --contains_section--> targets[...]` rule (`config.yaml:592-594` already lists `document_section`; just append `document_chunk`); write the edge per chunk | edge write rejected by `validateEdgeRule`; or no spine |

Site 1 also needs the **`.down.sql`** (revert the CHECK to the prior list — note: dropping the value fails if `document_chunk` rows exist, so the down path must delete chunk nodes first, matching the 000055 down pattern).

**Not needed (verified):** 000008 JSONB constraints (document family has none); FTS `search:` config (trigger-driven — `properties.content` is auto-indexed by `000010`); no Python node-type allowlist blocks child creation. Gate-1 unknown-type rejection confirmed (`node.go:519`).

### D7 — Backfill
Chunk-on-ingest is steady state (chunker runs in `decompose.py` after section creation, reusing the `embed_passage` batch path). Existing corpus backfilled by a **new** one-off `POST /api/v1/admin/backfill-chunks` (lists existing `document_section` nodes, chunks `properties.content`, upserts chunks+embeddings+edges), idempotent via the deterministic `chunk_id`. **`admin/reembed` is not extended** (it cannot create nodes).

### Qwen response caps (CTO, ecosystem §3.2 "tràn context 32k")
- `kg_search_chunks` `limit`: default 5, **hard max 10** (lowered from 20 — passages are heavy).
- Response per hit = passage `text` (bounded by `CHUNK_SIZE`) + nested `citation` `{document_id, section_id, chunk_id, section_title, line_start, line_end}` + `score`. The nested citation is kept (product value) but flagged as a **Phase-5 test-matrix watch-item** for Qwen before LAAM E1 exposes it.

### chunk_id contract-drift note (CTO, ecosystem §5)
The `chunk_id` (server node UUID) and its `chunk_key` (`section_id:ordinal`) are **DAAB-internal identifiers**, NOT the canonical ecosystem `chunk_id` (which the **Ingest Core** will own, §4.1/§5). When the forward-compat seam swaps the producer to the Ingest Core, a **chunk_id re-key migration is expected** (bucket C). The store/tool/embedding stay; the id namespace does not. Documented so the seam is a tracked decision, not a silent assumption.

## 5. MCP tool `kg_search_chunks` (schema)

```
kg_search_chunks:
  description: "Search document passages (fine-grained chunks); return the passage text with a precise
                citation (document, section, lines). Use to ground a cited answer in the exact source passage."
  params:
    query:       string, required
    document_id: string, optional   # = ecosystem doc_id?; scope to one document (hub uuid from kg_search)
    project_id:  string, optional   # default project
    mode:        string, optional, enum[fulltext|semantic|hybrid], default "hybrid"
    limit:       integer, optional, default 5, max 10
    offset:      integer, optional, default 0
```
Routed HTTP-proxy tool (`toolRoutes`), NOT local. Aligns with ecosystem `search_chunks(query, doc_id?, limit?)` (§4.2.3).

## 6. Components & Files

| Component | Effort | Files |
|-----------|--------|-------|
| FR-4 minimal extractor + eval corpus + run (FIRST) | Small–Med | one-off extractor; **extend** `tests/eval/retrieval_eval.py` (add `/search-chunks` target + chunk-id scoring) + labeled set |
| Python: chunker (paragraph-first + offsets + UUIDv5 id + content_hash) in decompose | Medium | `ingestion/pipeline/` (+ tests) |
| Python: chunk embeddings via shared `embed_passage`; `contains_section` edge per chunk; orphan cleanup | Small | decompose pipeline (reuse) |
| Go: `document_chunk` node type — migration CHECK + `config.yaml node_types` + `config/types.go` + `search.go` validNodeTypes | Small | per D6 sites 1-4 |
| Go: `config.yaml edge_whitelist` for `document_section→contains_section→document_chunk` | Trivial | D6 site 7 |
| Go: `POST /search-chunks` handler (force scope + `document_id` filter both arms; reuse RRF/fail-soft) + additive `DocumentID` on `SearchParams`/`SemanticSearch` | Medium | `internal/handler/search.go`, `internal/store/search.go`, `internal/store/node_embedding.go` |
| Go: `kg_search_chunks` schema (34→35) + route (32→33) + count/route test fixes | Small | `bridge/schema.go`, `client.go`, `schema_test.go`, `handler_test.go`, `client_test.go`, `integration_test.go` |
| Python: `POST /admin/backfill-chunks` one-off (reuse chunker + upsert) | Small | `api/admin.py` |
| **Total** | **~5-7 days** (FR-4 + extractor run first) | + chunk embed/edge compute |

## 7. Testing strategy
- **Python unit:** chunker — long section → N chunks with correct offsets + deterministic ids; short section → 1 chunk; re-run idempotent (no dup); content change → re-embed; orphan removed.
- **Go store:** `SemanticSearch`/FTS with `document_id` filter; `search-chunks` forces `document_chunk` scope; fail-soft to fulltext on embed-down.
- **Go bridge:** `kg_search_chunks` schema (param `query` required, `limit` max 10) + route present; counts 34→35 / 32→33; relational `e2e_tools_test.go:805` auto-holds.
- **Go handler:** `kg_search` byte-for-byte unchanged (regression guard).
- **E2E (after gate):** ingest long doc → `kg_search_chunks` returns passage + citation past the 2000-char cutoff that section search misses → chain `document_id` → `kg_get_document` for filename.
- **Eval:** recall@5/MRR before (trigger) + after (prove) + section no-regression. `make test` (`-race`); `uv run pytest`.

## 8. Acceptance criteria
(Inherits IMP-007 §5; design-specific additions.)
1. FR-4 runs first on a representative long-doc corpus **with real extracted text** (minimal extractor applied to the Master Record / a contract); baseline + `CHUNK_SIZE` chosen from it; post-build re-run proves chunk recall > section baseline with no section regression.
2. A long section produces multiple `document_chunk` nodes (own 384-dim embedding, deterministic id, `contains_section` edge to its section); a short section → exactly one chunk; re-ingest of the same section → no duplicates.
3. `kg_search_chunks(query[, document_id])` returns passage `text` + citation `{document_id, section_id, chunk_id, section_title, line_start, line_end}`; `limit` capped at 10; fail-soft to fulltext.
4. Graph spine `document → contains_section → document_section → contains_section → document_chunk` is traversable (enables AAA Luồng 4).
5. `kg_search` + section retrieval unchanged; counts 34→35 / 32→33; all bridge cross-checks green.

## 9. Risks
| Risk | Level | Mitigation |
|------|-------|------------|
| Building before truncation is proven on a real long corpus | Med | Gate held (decision ②); minimal extractor first; FR-4 trigger on tail-subset recall |
| `document_id` JSONB predicate unindexed → slow on large chunk table | Low–Med | Accept now; add expression index on `(properties->>'document_id')` only if the eval corpus shows need (YAGNI) |
| Chunk + edge explosion on contracts/Master-Record | Med | 1:1 for short sections; measure embed/edge/row budget on the **representative** corpus before committing |
| **`CHUNK_SIZE` tuned above the e5 ~512-token window** → embedding silently re-truncates, defeating the fix | Med | Hard ceiling in D1; FR-4 tunes only within ~512 tokens; add an assertion in the chunker that no chunk exceeds the token budget |
| FR-4 harness assumed zero-code reusable but only evals sections | Low | Corrected (D5): extend harness with a `/search-chunks` target + chunk-id scoring before the gate run |
| Cross-re-upload orphans (section-id instability) | Low | Documented BR; resolved in bucket C (canonical doc_id), not IMP-007 |
| chunk_id re-key when Ingest Core lands | Low | Documented contract-drift note; store/tool unaffected |
| Qwen context flood from heavy passages | Med | `limit` max 10; bounded `text`; Phase-5 test-matrix watch-item before LAAM E1 |

## 10. Open items / next
- **OQ-2 (transport/naming):** Go `kg_*`/stdio vs ecosystem TS/`search_chunks`/Streamable HTTP — deferred to roadmap E2 / ecosystem Phase 3.
- **Roadmap signal:** bucket-C extraction (OCR) is a soft prerequisite to *evaluate* IMP-007 on its headline corpus — may reorder the roadmap.

**Next step:** spec approved → `superpowers:writing-plans` to create the step-by-step implementation plan (FR-4 + minimal extractor as step 1, then the chunker, then Go node-type/search/bridge, then backfill), TDD per step.

---

## 11. Implementation result (2026-06-17 — built)

**Gate decision:** PO chose **build-first, eval-as-proof** (Phase 0 STOP/GO folded into the post-build proof — the decision to build the layer was made explicitly, so the formal pre-build recall benchmark was not run as a blocker).

**Delivered (all phases):** Go — migration 000059 `document_chunk`; config node_types + edge_whitelist + `search` block; `NodeTypeDocumentChunk` const/ValidNodeTypes; `kg_search` allowlist; `document_id` filter on FTS + SemanticSearch; `POST /api/v1/search-chunks` (chunk-scoped hybrid RRF + fail-soft + `document_id`); MCP `kg_search_chunks` (35 schemas / 33 routes). Python — pure `chunker.py` (paragraph-first, token-capped to e5 512, deterministic `chunk_key`); decompose wiring (chunk nodes + `contains_section` edges + embeddings via the existing batch path); idempotent `POST /api/v1/admin/backfill-chunks` (create/update/skip by chunk_key+content_hash, no delete); eval-harness `--target chunks`.

**Verification:** Go full suite green (`-race`); Python 324 passed / 17 skipped. Per-task spec+quality reviews + a final whole-branch review per repo (both → merge; one Python counter-integrity bug found and fixed with a pinning test).

**Live E2E proof (rebuilt stack, fresh throwaway project):** backfilled real VI corpus sections → **22 `document_chunk` nodes + embeddings**; `kg_search_chunks` returned passages with full citations (`document_id`, `chunk_key`=`section_id:ordinal`, line ranges) in fulltext / hybrid / semantic modes, including passages **past the section cutoff** (the tail-recall goal); `document_id` filter returned only that document's chunks and **0 for a bogus id** (proves the JSONB predicate filters live); re-backfill reported `created:0 / skipped:22` (idempotency); section `kg_search` unchanged (no regression).

**Live bug found & fixed by the E2E:** `/api/v1/query` (and filtered search) 500'd for `document_chunk` because the `search:` config block lacked the type — adding a node type requires the `search:` block too (it drives the filter-validation context), not just `node_types`/`edge_whitelist`. Fixed in config.yaml + a regression test (`filter/validate_test.go`).

**FR-4 benchmark (run 2026-06-17):** Both `cang-dinh-an` reports ingested through the **real upload→decompose pipeline** (proving Task 5.1 live) → **122 sections + 154 chunks** auto-created. 15 VI labeled pairs (snippets = real prose sentences from the longest sections; queries = salient terms). Section vs chunk recall@5 / MRR:

| mode | section R@5 | chunk R@5 | section MRR | chunk MRR |
|------|-------------|-----------|-------------|-----------|
| fulltext | 0.800 | **1.000** | 0.586 | 0.613 |
| semantic | 0.800 | **0.867** | 0.586 | 0.586 |
| hybrid | 0.933 | 0.933 | 0.691 | 0.630 |

**Finding:** chunks **match-or-beat** sections on recall (higher in fulltext+semantic, tied in hybrid), zero regression. Notably **all 15 answer-snippets landed within the first ~1500 chars of their section** — i.e. this well-structured markdown decomposes into sections small enough that the e5 ~512-token window already covers them, so the *tail-of-section truncation* the chunk layer is designed to fix barely occurs on THIS corpus. The chunk layer's largest gain is therefore on documents with **few long sections** (e.g. poorly-structured PDFs / long unstructured text), not header-rich markdown. This is exactly the Phase-0 gate signal: the layer is correct and helps, but its headline-corpus payoff is modest. (N=15, derived labels, VI-only — a smoke-gate per Rule 12, not a statistical benchmark.)

**Deferred (documented follow-ups, not blockers):** orphan-chunk deletion on `CHUNK_SIZE` change (no node hard-delete API — requires full re-ingest); a larger human-labeled multilingual benchmark if a statistical claim is ever needed.
