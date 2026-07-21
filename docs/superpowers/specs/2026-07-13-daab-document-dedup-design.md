# DAAB Document Deduplication — Design Spec

**Date:** 2026-07-13
**Status:** Draft (pending user review)
**Branch:** task/implement_docs_sync
**Related:** FR-004 content-hash dedup (BA-030), FR-001 GraphRAG retrieval, `mem:backlog/daab-retrieval-quality-gaps-postfix`

---

## 1. Problem

The same PDF re-uploaded to a project is stored as a **new** document node instead of
being deduplicated against the existing one. Measured on **Cảng Định An**
(`592c7ff7-…`): **145 document nodes but only ~75 distinct titles → 48% duplicates**.

### Root cause (verified from DB, not inferred)

The existing FR-004 dedup keys every lookup on **`source_id`** (the per-upload id):

1. **Exact-hash** — `get_canonical_document_by_source(project, source_type, source_id, content_hash)` → `FindBySourceHash` (`WHERE project_id AND source_type AND source_id AND content_hash`).
2. **Source-only** — `find_canonical_document_by_source(project, source_type, source_id)` → `FindBySource` (`WHERE project_id AND source_type AND source_id`, any hash) → drives the CHANGED/regenerate path.

Re-uploading a file mints a **new `source_id`** (`upload:<uuid>`). Both lookups are
scoped to `source_id`, so **both miss**, and the pipeline falls through to
`create_node` — a brand-new hub, sections, chunks, embeddings.

**DB evidence** (`canonical_document`, project = Cảng, `deleted_at IS NULL`):

```
145 canonical rows | 74 distinct content_hash | 145 distinct source_id
```

Per duplicated title, the copies share **identical `content_hash`** and differ only by
`source_id`. Example — "01 Quyết định chủ trương đầu tư.pdf": both copies
`content_hash=80558b24…`, `source_id` = `upload:e8260401…` vs `upload:a67a56b5…`.

→ The duplicates are **exact re-uploads** (same bytes → same OCR → same hash). They are
**not** divergent-OCR variants. This is the single fact that determines the whole design:
**a per-project content-hash match (ignoring `source_id`) is both sufficient and correct.**

### Downstream harm

Duplicate copies embed near-identically and the chunk-link worker joins them at
`similar_to` `similarity≈1.0`. In `kg_graph_retrieve` this causes: false corroboration
(two "sources" that are one document), wasted result slots, and uneven extraction
(Haiku extracts each copy independently, so entities diverge across identical content).

---

## 2. Scope

**In scope**
- **Prevention** — stop new cross-upload duplicates at ingest (global per-project content-hash reuse).
- **Cleanup** — remove the existing ~70 duplicate document nodes and their sections / chunks / embeddings / `similar_to` edges for Cảng Định An.

**Out of scope (YAGNI — data does not justify it)**
- Near-duplicate / fuzzy / MinHash / SimHash dedup. The duplicates are byte-identical re-uploads; exact content-hash catches 100% of them.
- OCR-variant merging (same physical doc, different OCR text → different hash). Not the cause here; tracked separately under the OCR-quality gap.
- Cross-project dedup. Dedup is per-project by design (tenancy boundary).

---

## 3. Prevention design

### 3.1 Approach

Add a **third dedup tier** — *global content-hash reuse* — to the ingest pipeline,
inserted **after** the source-only (CHANGED/regenerate) check misses and **before**
`create_node`. On a hit it reuses the existing `knowledge_node_id` exactly like the
existing exact-hash reuse path (complete the draft pointing at the existing node,
`result.reused += 1`, no new substrate).

**Dedup precedence (final):**

| Tier | Match on | Outcome |
|------|----------|---------|
| 1. Exact-hash | project + source_type + source_id + content_hash | Reuse (unchanged re-process of same upload) |
| 2. Source-only | project + source_type + source_id (any hash) | Regenerate on existing hub (same upload, edited content) |
| **3. Global-hash (NEW)** | **project + content_hash (any source_id)** | **Reuse existing node (same content, different upload)** |
| 4. Miss | — | `create_node` (genuinely new document) |

**Why tier 3 sits after tier 2, not before:** if the *same* `source_id` already exists
with a *different* hash, that is a genuine content update of that upload and must
regenerate on its hub (tier 2). Only when the `source_id` is new (tier 2 miss) do we ask
"does this exact content already exist under another upload?" This ordering preserves the
existing update semantics and adds reuse only for the true cross-upload-duplicate case.

### 3.2 Go changes (`ennam.kg.go`)

**Store** — `internal/store/canonical_document.go`

New method `FindByContentHash`:

```go
// FindByContentHash returns the latest non-deleted canonical document matching
// (project_id, content_hash) regardless of source_id — the cross-upload dedup
// lookup (a re-uploaded identical file gets a new source_id but the same hash).
// Returns (nil, nil) on miss.
func (s *CanonicalDocumentStore) FindByContentHash(
    ctx context.Context, projectID, contentHash string,
) (*models.CanonicalDocument, error)
```

Query: `WHERE project_id = $1 AND content_hash = $2 AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 1`.
`deleted_at IS NULL` guarantees a soft-deleted (superseded / cleaned-up) row is never
matched — consistent with the existing `A→B→A` revert fix.

**Handler** — `internal/handler/canonical_document.go`

Extend the existing `GET …/canonical-documents/lookup` with a **content-hash-only mode**:
when `content_hash` is present **and `source_id` is empty**, call `FindByContentHash`
(`source_type` optional in this mode). The two existing modes are unchanged. Add
`ContentHashFinder` to the handler's store interface.

Route already registered — no `main.go` change.

### 3.3 Python changes (`ennam.kg.python`)

**Client** — `packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client/client.py`

New method mirroring the existing lookups:

```python
async def find_canonical_document_by_content_hash(
    self, project_id: str, content_hash: str
) -> dict[str, Any] | None:
    """GET …/canonical-documents/lookup with content_hash only (no source_id).
    Global per-project content-hash dedup. None on 404; raises on other errors."""
```

**Engine** — `src/ennam_kg/ingestion/pipeline/engine.py`

Insert tier 3 between the source-only miss (`prior is None`) and the `create_node` block
(after line 233, before line 235). Same failure discipline as the other lookups — a
non-404 `KGClientError` fails the draft loudly (`result.failed += 1`, `_safe_complete(…, False)`),
it does **not** silently fall through to `create_node` (NFR-243 ingest-once; AGENTS.md Rule 12):

```python
# --- Global content-hash dedup: identical file re-uploaded under a new source_id ---
try:
    dup = await self._kg.find_canonical_document_by_content_hash(
        project_id, canonical.content_hash
    )
except KGClientError as exc:
    result.failed += 1
    result.errors.append(f"{draft_id}: content-hash dedup lookup: {exc}")
    logger.warning("content-hash dedup lookup failed draft=%s: %s", draft_id, exc)
    await self._safe_complete(project_id, draft_id, False, "")
    continue

if dup is not None:
    dup_node_id = str(dup.get("knowledge_node_id") or "")
    await self._kg.complete_draft_node(
        project_id, draft_id, success=True, knowledge_node_id=dup_node_id
    )
    result.processed += 1
    result.reused += 1
    logger.info("content-hash dedup hit draft=%s existing_node=%s", draft_id, dup_node_id)
    continue
```

### 3.4 Data flow (prevention)

```
draft → build_canonical_document (content_hash)
  ├─ tier 1 exact-hash hit?      → reuse, done
  ├─ tier 2 source-only hit?     → regenerate on hub, done
  ├─ tier 3 global-hash hit?     → reuse existing node, done   ← NEW
  └─ miss                         → create_node (new document)
```

---

## 4. Cleanup design

### 4.1 Approach: soft-delete + re-ingest (not in-place merge)

Wipe Cảng Định An's document substrate and **re-ingest from the clean source folder**
`doc_pdf_test/project_1` (79 files = the full deduplicated set), rather than writing
merge logic that picks a survivor per hash and rewrites sections/chunks/edges.

**Why re-ingest, not in-place merge:**
1. The folder is the **clean, complete** set — re-ingest reproduces the correct corpus by construction.
2. Re-ingest **exercises the prevention fix end-to-end** — the strongest possible validation (if tier 3 works, 79 files yield ≤79 distinct-title documents with zero duplicate-doc `similar_to` edges).
3. In-place merge is fragile: choosing a survivor, re-pointing edges, reconciling divergent extractions across ~70 hashes — high risk for a one-shot cleanup with no reuse value.

**Trade-off accepted:** re-ingest re-runs OCR + Haiku extraction on 79 files (cost/time).
Acceptable for a one-time correctness reset, and it also refreshes extractions that were
uneven across the old duplicate copies.

### 4.2 Cleanup steps

1. **Snapshot** current counts (documents, sections, chunks, embeddings, `similar_to` edges) for the project — before/after evidence.
2. **Delete the document substrate**, reusing existing primitives:
   - Enumerate the project's `document` hub nodes.
   - For each hub, call the existing `DeleteDocumentSubtree(project, hub)` — it hard-deletes the `document_section` + `document_chunk` nodes, cascades embeddings, and deletes the edges touching those chunks (**including the cross-document `similar_to` edges, which live between chunks**). It does **not** delete the hub node itself.
   - Delete each `document` hub node and any hub-level edges (`has_section` etc.) — no existing store method targets the hub, so the one-shot script does this via direct SQL / the generic node-delete path.
   - Soft-delete the project's `canonical_document` rows (`SoftDeleteBySource` per source, or a project-scoped soft-delete added only if no existing method fits). Soft-delete is sufficient because tier-3 lookup filters `deleted_at IS NULL`.
   Because this runs once, the plan wraps it as a scripted cleanup (SQL + existing endpoints), not new production code.
3. **Re-ingest** `doc_pdf_test/project_1` through the normal upload → queue → worker path (same mechanism used for the Sala Food ingest), with the prevention fix deployed.
4. **Verify** (success criteria below).

### 4.3 Ordering (two hard constraints)

1. **Prevention before cleanup.** Prevention ships and is verified first (unit + a 2-file
   re-upload E2E), then cleanup re-ingests against the fixed pipeline. Cleanup on the old
   pipeline would just re-create duplicates.
2. **Deletion fully complete before re-ingest.** This is the subtle trap: tier-3 reuse
   matches any live `canonical_document` row with the same `content_hash`. If re-ingest
   starts while the old duplicate nodes still exist (or their canonical rows are not yet
   soft-deleted), tier 3 will happily **reuse the stale duplicated node** and the cleanup
   achieves nothing. Therefore deletion must be verified complete (zero live document hubs
   **and** zero live `canonical_document` rows for the project) before the first re-ingest
   upload. The plan gates re-ingest on this check.

---

## 5. Error handling

- **Prevention lookup failure** (non-404): fail the draft loudly, never fall through to `create_node` (NFR-243, Rule 12). 404 = miss = proceed to next tier.
- **`deleted_at` correctness:** tier 3 matches only live rows, so cleanup soft-deletes and content reverts cannot resurrect stale nodes.
- **Cleanup deletion failure:** abort and surface; do not re-ingest on top of a partially-deleted corpus (would reintroduce mixed state).
- **Concurrency:** ingest is single-worker per project (existing model); no new race introduced. Two identical files in one batch: the first creates the node, the second hits tier 3 on the just-committed canonical row (sequential draft loop).

---

## 6. Testing

**Go — store** (`canonical_document_test.go`)
- `FindByContentHash` hit across a *different* `source_id`, same hash.
- Miss returns `(nil, nil)`.
- Respects `deleted_at IS NULL` (soft-deleted row not matched).
- Nil-DB guard error (matches sibling methods).

**Go — handler** (`canonical_document_test.go`)
- Lookup with `content_hash` only (no `source_id`) → content-hash-only mode → 200 on hit, 404 on miss.
- Existing two modes unchanged (regression).

**Python — engine** (`tests/…/test_engine*.py`)
- Tier-3 hit: a draft with a **new `source_id`** but a `content_hash` already present in another canonical row → `reused += 1`, **no `create_node`**, draft completed pointing at the existing node. (Encodes the intent: identical re-upload must not create a second document — Rule 9.)
- Tier-3 lookup non-404 error → draft fails loudly, no `create_node`.
- Tier precedence: same `source_id` + changed hash still takes the tier-2 regenerate path (tier 3 not consulted).

**E2E — cleanup validation** (manual/scripted against live stack)
- After re-ingesting `doc_pdf_test/project_1`: `count(document) == count(distinct title)`; **zero** `similar_to` edges linking two chunks whose documents share a `content_hash`; graph-retrieve on a known query returns distinct documents (no duplicate corroboration).

---

## 7. Success criteria

1. Re-uploading an identical file creates **no** second document node (tier 3 reuse; unit + E2E proven).
2. Cảng Định An after cleanup: **live document-hub count == distinct `content_hash` count** among the re-ingested files (the exact dedup invariant; distinct-title ≈75 is the human-readable proxy). Zero `similar_to` edges linking two chunks whose parent documents share a `content_hash`.
3. `kg_graph_retrieve` on Cảng returns distinct documents — no duplicate corroboration in results.
4. All existing dedup tests (tiers 1–2, regenerate, A→B→A revert) still pass — no regression.
5. Sala Food (already clean) unaffected.
