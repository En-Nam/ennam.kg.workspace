# Checkpoint: BA-033 Slice 1 + BA-031 graph cleanup — 2026-06-24

## What was done
- **BA-033 Slice 1 (chunk-sim retrieval)**: brainstorm→spec→plan→implemented (10 tasks, prior session). Fixed json-tag response defect + calibrated chunk-link threshold 0.83→0.90 (0.83 = multilingual-e5 noise floor → cross-topic false links). Ship-gate run: **NO-GO on the test corpus** (chunk-sim adds 0 marginal value over /search@20 at clean threshold; corpus is tiny+mixed-domain). Disposition: built-but-gated. Docs: `docs/superpowers/specs/2026-06-24-ba033-slice1-cross-document-retrieval-design.md` + plan same date.
- **BA-031 graph cleanup (3 fixes, committed+pushed task/implement_mcp):**
  1. #2 stale-suggestion drain — `MergeService.ResolveLiveCanonical` + apply-layer chain resolution; verified live (244 "member not active" errors → 0). `ennam.kg.go 541411a`.
  2. #1 status flip — `MarkDocResolved` + `POST /api/v1/internal/extraction/doc-resolved` + worker calls it after run_pass2_shadow. `ennam.kg.go 541411a` + `ennam.kg.python 3c541c1`.
  3. #3 batch verify default 1→6 — re-validated **G2 batch=6: precision 1.000 / recall 0.917**. `ennam.kg.python 896f335` + `docker-compose 7586d47`.
- **Re-extracted corpus** (project 6f5f1680 "LAAM Project Test") with new Track-B prompts to densify relations.

## Current state (project 6f5f1680, clean)
- Entity edges 117→342; **connected 75/109 (69%)** (was 8% pre-re-extract); **0 exact-name dup clusters**; 0 pending suggestions.
- The earlier "46 dup / 132" counts were POLLUTED by `created_by='ba031-benchmark'` nodes (G2 seed data) + cross-project rows — not real corpus dups. Cleaned.
- Possible semantic near-dups remain (e.g. "Cảng Định An" vs "Khu bến tổng hợp Định An") — resolution's judgment, do NOT force-merge.

## Plan-2 readiness: MET
Graph is dense (69% connected) + 0 dup + clear hubs/2 themes (port: Khải Thịnh/Hàm Giang/Cảng/ĐBSCL; recipe: Nguyên liệu/nước dùng/Phở Gà) → community detection viable.

## Next steps
- Brainstorm **BA-033 Slice 2** (community detection FR-002/003 + global retrieval FR-005) on the clean graph.
- BA-033 Slice 1 stays built-but-gated; re-run its ship-gate on a coherent real corpus before adopting chunk-sim as a default retrieval path.

## Known gaps / caveats
- 60 chunk_extraction_state rows stuck 'resolving' (pre-fix leftovers; fix #1 only flips on NEW resolve runs) — cosmetic.
- Embedding service cold-start ~25s > server timeout → first /search or /retrieve/graph after idle 502s (shared infra, affects /search too). Pre-warm or raise timeout — follow-up.
- merge_cli benchmark seeds `ba031-benchmark` nodes into the target project; MUST clean them (`DELETE WHERE created_by='ba031-benchmark'`) before measuring real graph stats — else dup/density counts are polluted.
- API URL for dev = http://localhost:8082 (8082→8080). Admin login: admin/Admin123!@# returns api_key. Linker/apply need a key with project access (worker GO_API_KEY lacks it → use admin login).
