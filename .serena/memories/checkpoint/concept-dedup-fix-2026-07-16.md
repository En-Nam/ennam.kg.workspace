# Checkpoint: concept dedup fix — cross-document entity bridges now exist (2026-07-16)

## What was done
Fixed `ingestion/pipeline/decompose.py` creating a **fresh `concept` node per mention**. Commit `06df209` "fix(ingestion): reuse project-scoped concept nodes instead of one per mention". Plan: `docs/superpowers/plans/2026-07-16-concept-dedup-fix.md`.

**Root cause (was at decompose.py:199-206):** `seen_concepts: set[str] = set()` was re-created **per document**, and `kg.create_node` was called **unconditionally** — no lookup, no upsert. So every document minted its own concepts → `document→concept` mentions == concept count (1:1) → **no concept shared by two documents → no entity bridges → the graph was disconnected islands** (matches the user's screenshot).

**Fix:** prefetch project concepts via `kg.get_nodes(project_id, node_type="concept")` → `_resolve_concept_key()` (reuses B1's `resolution/name_fold.py::fold_name` + a small `_LEGAL_FORMS` map for `trach nhiem huu han`→`tnhh`) → reuse-or-create → `result.concepts_reused` + an INFO log of created-vs-reused.

## Results (verified in DB, project `Dasin`)
| Metric | Before | After |
|---|---|---|
| concepts | 41 (≈15 real) | **26** |
| exact-duplicate titles | **10** | **0** |
| **concepts shared by >1 document** | **0 rows** | **11 concepts** |
| `Đại Tân` company | **8 nodes** | **1** (+ `CHI NHÁNH LONG AN` correctly kept separate) |

Top bridge: `CÔNG TY TRÁCH NHIỆM HỮU HẠN ĐẠI TÂN` now links **8 of 9 documents**. Tests: `tests/ingestion/` **119 passed**.

## Why this mattered (pairs with the OCR fix)
`mem:backlog/ingestion-ocr-content-loss-bugs` (OCR fix) raised text ~4× but concepts only went 28→41 — suspicious at the time, now explained: concepts were **multiplying, not accumulating**. Two distinct failures: OCR bug = text never reached the graph; concept bug = entities reached it but never connected documents. Both fixed → the corpus finally has content AND bridges.

## Known limitations (deliberate, documented in the plan)
- **Not race-safe** — concurrent workers can both miss the prefetch and create the same concept. Correct long-term fix is a DB-level upsert on `(project_id, node_type, folded_title)` in Go. Out of scope (AGENTS.md Rule 2/3). **Follow-up candidate.**
- `get_nodes` has `limit=5000` — a larger project would silently start duplicating.
- `properties.aliases` still `[]` — surface forms of reused variants are not captured.
- `concept` is still NOT enrolled in the resolution/`needs_review` pipeline (6 other types, hub-safety gates + LLM confirmation). Semantic near-duplicates `fold_name` can't catch remain — separate open decision in `mem:backlog/ba033-slice2-readiness-path`.
- Prefetch is per-document → N `get_nodes` calls per N-document batch. Simple; optimise only if measured slow.

## Next step (unblocked, evidence-led)
**Run the sim-consumer MCP harness on `Dasin`** — the corpus now has clean text (88% diacritics) AND cross-doc entity bridges, so findings are finally trustworthy. Harness: `other_projects/daab-sim-consumer` (persona + 0–3 rubric in its `CLAUDE.md`); HTTP-MCP verified working via scratchpad `mcp_call.py` (bridge `:8765`, `X-KG-Project-Id` header scopes the project; ~30 `kg_*` tools).
- Write `questions-dasin.md` for the real DD set: 3 audited financials (2023/24/25), GPĐT X1–X3, GCNĐKKD, 5.1M USD capital increase. Cross-doc financial trend is the FR-001 `kg_graph_retrieve` thesis and is chunk-similarity based (70 `similar_to` edges exist).
- **Caveat, do not overclaim:** Dasin is only 9 docs → validates the AAAA→sync→OCR→graph→MCP→consumer LOOP, but does NOT answer the corpus-level BA-033 Slice 2 go/no-go (needs Cảng Định An, 145 docs). See `mem:backlog/ba033-slice2-readiness-path`.

## Also still open
- Workspace-root docs/memories uncommitted; nothing merged to `main` on any of the 4 repos (`task/implement_docs_sync`).
- Pre-existing (not caused here): `tests/extraction/test_parser.py::test_drops_out_of_range_span_and_orphan_relation` fails; 16 ruff F401 in `benchmark/runner.py`.
- 1 doc failed sync: `94af7d35-...` "no signed URL returned" — untriaged.
- `.mcp.json` hardcodes an API key (repeatedly revoked) → `mem:backlog/aaaa-daab-sync-token-settings-ui`.
