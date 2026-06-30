# Checkpoint: backend-dev — 2026-06-28 (BA-033 IDF + 31-doc eval)

## What was done

### 1. IDF-weighted entity expansion (2a) — implemented & shipped
- `ennam.kg.go@fb69001`: `graph_retriever.go` scores expanded concepts via IDF (log(N/df+1) × base_score)
- All 4 graph modes (flat, parent_child, entity, hybrid) benefit from 2a
- Tests: `graph_retrieve_test.go` covers IDF scoring logic

### 2. 31-doc corpus ingested
- Uploaded 21 new PDFs (all Cảng Định An / Hàm Giang / Khu bến tổng hợp Định An)
- Worker processed via Tesseract vie + RapidOCR; some docs got 0 sections (content >50k chars validation limit, pre-existing)
- chunk_section_map.json regenerated: 52 entries → 214 entries
- Container: `daab-postgres` at :5433; edge type is `contains_section` (not `has_section`)

### 3. BA-033 Eval — 31-doc corpus results

**FINAL VERDICT: NO-GO for all graph modes**

Average marginal recall vs baseline: **-0.1917** across 10 queries.

| Query | baseline r@10 | graph r@10 | Δ |
|-------|--------------|------------|---|
| q01 Hàm Giang | 0.75 | 0.50 | -0.25 |
| q02 Định An decisions | 0.75 | 0.75 | 0.00 |
| q03 UBND Trà Vinh | 1.00 | 0.50 | -0.50 |
| q04 land lease | 0.75 | 0.50 | -0.25 |
| q05 FDI | 1.00 | 1.00 | 0.00 |
| q06 phê duyệt đầu tư | 0.67 | 1.00 | **+0.33** |
| q07 tiến độ thi công | 1.00 | 1.00 | 0.00 |
| q08 EIA | 1.00 | 0.25 | **-0.75** |
| q09 tổng mức đầu tư | 1.00 | 0.50 | -0.50 |
| q10 M&A ecosystem | 1.00 | 1.00 | 0.00 |

Root cause: **entity_blob problem** (single-project corpus). Every doc shares entities (cảng Định An, UBND Trà Vinh, Hàm Giang) → entity expansion is query-indiscriminate → brings in off-topic sections. q08 smoking gun: EIA query should return EIA sections, but entity traversal pulls in unrelated sections.

**Decision on 2b (IDF-sum normalization):** SKIP. No basis for improvement when entity modes are net-negative.

**Default mode: baseline** (unchanged)

## Files changed
- `ennam.kg.go/internal/service/graph_retriever.go` — IDF weighting (2a)
- `ennam.kg.go/internal/store/graph_retrieve.go` — IDF store support
- `ennam.kg.python/eval/chunk_section_map.json` — regenerated (214 entries)
- `scripts/ingest-batch-pdfs.py` — created for batch ingestion

## Current state
- 31 docs in project a0000000-0000-0000-0000-000000000001
- Graph retriever with IDF weighting deployed (2a done)
- 2b SKIPPED (no signal)
- BA-033 eval complete: graph modes NO-GO on single-project corpus

## Next steps
- BA-033 is concluded for single-project corpus
- Graph modes remain available but not default; revisit with multi-deal corpus
- GT quality note: existing 10 queries have ~2-4 GT sections each; adding new GT for 21 new docs would require independent annotation (not done — no reliable signal anyway given corpus homogeneity)
- Consider: implement docs sync pipeline (Plan A OCR already running) for a richer multi-project corpus

## Blockers / Risks
- BA-033 graph modes cannot be properly evaluated without a multi-project corpus (different deals)
- Corpus is 100% Cảng Định An → entity blob is structural, not fixable by tuning
