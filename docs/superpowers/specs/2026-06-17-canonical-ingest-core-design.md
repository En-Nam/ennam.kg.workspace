# Design Spec: Canonical Ingest Core (BA-030)

**Status**: Approved design — ready for implementation planning
**Created**: 2026-06-17
**Author**: brainstorming (orchestrated TC ⇄ CTO debate, 2 rounds)
**Source BA**: `ennam.kg.requirements/documents/phase8/BA-030-canonical-ingest-core.md`
**Decision record**: this spec encodes the converged Tech-Consultant / CTO ruling; where it narrows BA-030, the BA is the broader reference and this spec is authoritative for v1.

---

## 1. Problem & Goal

Text acquisition today is split across **three paths in two languages**, producing divergent canonical text, no shared document identity, silent loss of scanned PDFs, and duplicate chunks on re-ingest:

| # | Path | Where text is acquired today | Runtime |
|---|---|---|---|
| 1 | `local_upload` text (`.md/.txt/.json/.csv`) | Go `extractTextSync` (`file_upload.go:372`, `deferExtract=false`) | **Go** |
| 2 | `local_upload` binary (`.pdf/.docx/.xlsx`) | Python worker (`files.py` `_extract_pdf/_docx/_xlsx`) | **Python** |
| 3 | `satellite_api` | `content_raw` supplied in request; no extractor | none |

**Goal (v1):** one canonical document representation, produced by **one entry point in the Python worker**, consumed identically by **DAAB** (the KG) and **AAA** (field extraction). Go ceases synchronous text extraction.

**Hosting (PO-confirmed):** in-KG now, split-ready later. The canonical core is an internal consolidation inside Ennam KG, **not** a standalone microservice. The future §4.1 extraction stays localized *only if* AAA/DAAB bind to the **canonical contract** (`doc_id` / `canonical_document` / `chunk_key` / char-offsets) and never reach into KG-internal tables.

---

## 2. Scope (v1)

**In scope (the non-negotiable core):**

- **FR-001** Canonical Document Representation (`canonical_document` row, `doc_id` = `document` hub node id).
- **FR-002** Unified Extraction Entry Point — `build_canonical_document(draft, raw_text)` in the worker, **with single cross-path normalization** (see §4) and the **approval-gate invariant** (see §5).
- **FR-003** Fail-Loud on Empty Extraction (no silent near-empty docs; `extraction_empty`).
- **FR-004** Content-Hash Dedup — reuse path (no duplicate chunks) + content-change regenerate path.
- **FR-006** Single Chunk Producer — `decompose_document` consumes the canonical chunk list instead of re-parsing.

**Cut from v1 (deferred, by approved decision):**

- **FR-005 Per-Chunk Context Headers** — sole source of two-hash layering + title-drift (BR-005.6/OQ-008). Cutting it shrinks FR-006's blast radius. **Re-introduction trigger:** a real consumer (dashboard or BA-031) files a ticket needing the header. Not a benchmark — a concrete consumer ticket.
- **Two GET observability endpoints** (`/canonical`, `/chunks`) — YAGNI until operators need the inspector.

**Out of scope (unchanged from BA-030):** OCR for scanned PDFs (OQ-005 — a deliberate, *named* deviation from the §4.1 seed, documented not silent), cross-source dedup merge (OQ-001), table-structure recovery (OQ-006), embedding-model change (OQ-007), re-embed-on-rename (OQ-008).

---

## 3. Architecture

The pipeline is **three distinct stages**; `build_canonical_document` wraps all three behind one entry point:

```
bytes → text     files.py extract_file_text         (+ existing _extract_pdf/_docx/_xlsx)
text  → sections document_tree.parse_markdown_sections (the SECTIONING base, OQ-002 confirmed)
text  → chunks   chunker.chunk_section               (sole producer of {section_id}:{ordinal} keys)
```

**Key correction vs BA prose:** `parse_markdown_sections` is the *sectioning* base, **not** "the extractor." BR-002.2's "canonical base" wording is narrowed here to "sectioning base." `build_canonical_document` is the wrapper that owns all three stages plus normalization.

### Canonical contract (the only surface AAA/DAAB bind to)

```
doc_id          = canonical_document.knowledge_node_id  (= document hub knowledge_nodes.id)
canonical text  = normalized text (post-extraction, pre-chunk)
content_hash    = SHA-256(normalized canonical text)
chunk identity  = {section_id}:{ordinal} + char_start/char_end offsets
```

Direct reads of `draft_nodes.content_raw` from AAA/DAAB are **forbidden** once the contract is pinned (§5, gate 4).

### New entity — `canonical_document` (migration 000060)

Per BA-030 §6. One row per draft (`UNIQUE draft_node_id`). Indexes: `(project_id, source_type, source_id)` and `(project_id, content_hash) WHERE deleted_at IS NULL`. `extraction_method` CHECK reserves `ocr`/`mixed` (unused in v1) to avoid a future CHECK migration. **v1 writes only `text` / `native`.**

---

## 4. Cross-Path Normalization (CORE — closes the NFR-239 hole)

**The problem found in debate:** NFR-239 ("byte-identical across paths") is *unsatisfiable as written* — the worker pretty-prints JSON (`files.py:28-30`) and round-trips CSV to `\r\n` (`files.py:44-51`), Go returns raw bytes, and satellite supplies `content_raw` verbatim. The *same* document via upload vs satellite yields a different `content_hash` → different chunks.

**Resolution:** `build_canonical_document` applies **one** normalization step to all three paths' `raw_text` *before* hashing/sectioning. This is an explicit acceptance criterion of FR-002, not a separate FR.

Normalization policy (named decisions, not accidents):
- Line endings → LF.
- No JSON pretty-print as a hashing input (decode policy applied identically across paths).
- Truncation limits **named and accepted**: `parse_markdown_sections` caps at `text[:50000]`/section and `max_sections=200` (`document_tree.py:49,66`). v1 documents these as accepted policy; revisit only if a real doc exceeds them.

`content_hash` is computed over the **normalized** canonical text. NFR-239's cross-path equivalence test must cover **JSON and CSV**, not only markdown.

---

## 5. Approval-Gate Invariant (HARD requirement)

**The governance regression found in debate:** flipping text formats to `deferExtract=true` makes `PublishExtractUpload` fire (`file_upload.go:285`) on a `Status: Pending` draft, and the worker's extract handler runs `run_batch` immediately — **indexing text uploads before approval**, bypassing the gate `draft_node.go:172` enforces for the `kg_generation` path.

**Invariant:** extraction + canonicalization MAY run pre-approval; **decomposition, indexing, and any KG mutation MUST NOT run before approval.**

**Implementation rule:** `extract_upload` extracts text + writes canonical content **only**. It must **not** trigger `run_batch` / decomposition. Processing to KG nodes stays behind the approval-driven path exactly as `kg_generation` does today.

> Implementation to-do (non-blocking): confirm whether the worker's `ExtractUpload` handler currently extracts-only or also fans out to decompose; wire the gate accordingly.

---

## 6. Go Cutover (OQ-003 — delete-and-defer, no flag)

`extractTextSync` (`file_upload.go:372`) is `os.ReadFile` + `string(data)` — nothing to fall back to, so a feature flag is YAGNI. Three edits:

1. `classifyUploadFile` (`file_upload.go:355`): flip `.md/.txt/.json/.csv` → `deferExtract=true`.
2. Delete `extractTextSync` and its `if !deferExtract { … }` branch.
3. `ContentExtracted: false` for all formats at upload.

**Must land in the same phase as:** (a) normalization (§4 — JSON/CSV canonical text changes) and (b) the approval-gate wiring (§5). Deleting Go extraction without these trades a silent-extraction problem for a silent-divergence/governance problem. The deletion is git-reversible; the behavioral deltas are the real work.

---

## 7. AAA Non-Regression — OQ-009 as two artifacts (NFR-247)

Finding: `canonical_document` does **not exist yet**, so AAA cannot be reading it today — everything reads `draft_nodes.content_raw` (`engine.py:76`) or hub/section node content. OQ-009 is therefore two artifacts, not one blocker:

1. **Phase-0 characterization test (interim guard, write FIRST):** snapshot current `content_raw` + section/chunk content + char offsets for representative docs (**markdown + JSON + CSV**) through today's pipeline. Detects regressions during the refactor.
2. **Contract-pin (HARD gate before the FR-002 read cutover):** the **AAA phase owner** declares which field is authoritative for sign-off, the read path is pinned to the canonical contract, direct `content_raw` reads become forbidden, and the golden test is re-pointed at the pinned field. **CTO ratifies** the pinned path as a contract boundary.

This unblocks coding immediately (artifact 1) while guaranteeing the boundary before cutover (artifact 2).

---

## 8. FR-006 — Single Chunk Producer (the heavy, non-additive change)

**Not additive (BR-006.4 overstated).** `parse_markdown_sections` at `decompose.py:57` fans out to **three** consumers — `build_document_tree_json` (hub tree), the `document_section` loop (`:82`), and `chunk_section` (`:135`) — plus an inline embedding loop (`decompose.py:238-261`). `decompose_document` is a ~230-line function to **restructure**, not a one-line source swap. `build_canonical_document` must emit **sections + tree + chunks** together.

Verification (NFR-248): the producer never independently calls `parse_markdown_sections`/`chunk_section`; the canonical chunk list is its sole chunk source (code-path assertion at `decompose.py`).

---

## 9. FR-004 — Dedup (engine.py change)

`run_batch` (`engine.py:91-114`) today unconditionally calls `create_node` then `decompose_document` with zero idempotency — that *is* the duplicate-node defect. Reuse path (BR-004.2): look up the existing non-deleted `canonical_document` for `(project_id, source_type, source_id)`; on hash match, reuse `knowledge_node_id` + chunks + embeddings, **skip hub creation entirely**. Content-change path (BR-004.3) updates the canonical doc and **regenerates** chunks (stale-chunk replacement) — this is the **riskiest half** (orphan avoidance) and gets the most test coverage.

---

## 10. Approved Phase Order

| Phase | Scope | Verify | Migration |
|---|---|---|---|
| **P0** | Migration `000060` (empty `canonical_document`) + Phase-0 characterization test (md + json + csv) | up/down clean; golden snapshot committed | **000060** (new table, no backfill, reversible) |
| **P1** | `build_canonical_document` wrapper + **single normalization** (§4) + `content_hash` + FR-003 fail-loud; writes `canonical_document` **alongside** existing flow (no consumer cutover) | determinism (NFR-240); fail-loud (NFR-241); cross-path JSON/CSV equivalence (NFR-239) | — |
| **P2** | Go cutover (§6) behind **approval-gate invariant** (§5) | NFR-242 (no Go extraction); approval-gate test | — |
| **P3** | Contract-pin (§7 artifact 2) + re-pin NFR-247 golden test; forbid direct `content_raw` reads | golden test green against pinned field | — |
| **P4** | FR-004 dedup reuse + content-change regenerate | NFR-243 row-count; NFR-244 reprocess | — |
| **P5** | FR-006 `decompose_document` restructure (consumes canonical chunks) — **LAST** | NFR-248 (no independent re-parse) | — |

**FR-006 floor:** may not precede P0 — restructuring `decompose_document` without the characterization test + canonical chokepoint underneath is unguarded surgery.

**BA-031 unblock:** after P3 (trusted canonical surface + pinned contract). The CTO yielded its Round-1 "FR-006 first" position: pulling the riskiest change forward to unblock a downstream consumer is premature optimization (Rule 2). **BA-031 waits — accepted cost.**

---

## 11. Locked Approval Conditions (CTO ruling, verbatim)

1. Phase-0 characterization test over current `content_raw` read path, written FIRST.
2. Single cross-path normalization in `build_canonical_document`; `content_hash` over normalized text (CORE, non-negotiable).
3. Approval-gate invariant: extraction/canonicalization may run pre-approval; decomposition/indexing/KG mutation MUST NOT run before approval.
4. NFR-247 re-pinned to the canonical contract as a hard gate before the FR-002 read cutover; direct `content_raw` reads forbidden.
5. FR-005 + 2 GET endpoints CUT from v1; re-introduction trigger = a real consumer ticket.
6. Sequencing: P0 → P1 → P2 → P3 → P4 → FR-006 LAST. BA-031 unblocks after P3.
7. OCR gap stands as a deliberate, named §4.1 deviation — documented, not silent.

---

## 12. Open Items Before Spec Freeze

- **OQ-009 owner**: AAA phase owner must commit the authoritative read field before P2→P3 cutover (does not block P0/P1 coding).
- **Approval-gate handler check**: confirm worker `ExtractUpload` extract-only vs fan-out (P2 implementation to-do).
- Normalization specifics (LF + decode policy + accepted truncation limits) ratified as named decisions, not accidents.

---

## Appendix: Evidence (load-bearing file:line)

- `ennam.kg.go/internal/service/file_upload.go` — `classifyUploadFile:355`, `extractTextSync:372`, `PublishExtractUpload:285` (approval-gate seam), defer branch `240-248`.
- `ennam.kg.go/internal/service/draft_node.go:172` — auto-queue/`kg_generation` approval gate.
- `ennam.kg.python/.../adapters/files.py:28-30` (JSON pretty-print), `:44-51` (CSV `\r\n` round-trip) — cross-path hash divergence.
- `ennam.kg.python/.../pipeline/engine.py:76` (reads `content_raw`), `91-114` (unconditional create+decompose — dup-node defect).
- `ennam.kg.python/.../pipeline/decompose.py:57` (parse fan-out), `:82` (sections), `:135` (chunks), `238-261` (inline embeddings).
- `ennam.kg.python/.../pipeline/document_tree.py:22` (`parse_markdown_sections`), `:49,:66` (silent truncation 50K/section, 200 sections).
- `ennam.kg.python/.../pipeline/chunker.py:120` (`{section_id}:{ordinal}` chunk key).
- `build_canonical_document` / `canonical_document` confirmed **absent** from Go/Python source (exist only in docs) — the canonical surface does not yet exist.
