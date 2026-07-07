# Checkpoint: daab-danger-review-drain — 2026-07-07

## What was done
- Verified (not just trusted memory) that cross-user `monitoring` scope for `kg_search_sessions` was already fully shipped 2026-06-29 (commit `e9a5877`): handler gate, SQL project-bound collapse, `kg_audit_log` (migration 000073), MCP bridge schema, full test coverage. Corrected the stale claim in `mem:backlog/daab-kg-search-sessions-followups` that said it still needed a decision record.
- Cleared the BA-031 danger-stratum `needs_review` residual (project `592c7ff7-9f6f-4cc5-9094-d9b3b685277e`), which stood at 2521 rows at session start:
  1. Extended `danger_guards.py` GENERICS set (TDD: RED→GREEN, 14/14 tests pass, no regressions) with bare role/title terms (`thành viên`, `giám đốc`, `tổng giám đốc`) — these were false-accepted by the existing G1-G6 guards. Reduced guard-pass pool 1706→1641.
  2. Dispatched 10 parallel `general-purpose` agents (background) to semantically review the 1641-row guard-pass pool (chunks of ~180 rows) against a strict rubric (bias reject/uncertain over accept). Result: 1238 accept / 297 reject / 106 uncertain.
  3. Personally spot-checked 40 accept + 15 reject + 15 uncertain samples — quality was solid (correctly caught "container" vs "tàu container", "huyện Duyên Hải" vs "thị xã Duyên Hải" post-2015-split, generic bare nouns like "kho xăng dầu").
  4. Web-researched 4 of the ambiguous groups within the 106 uncertain (user supplied one screenshot confirming `Cục Hàng hải Việt Nam` renamed to `Cục Hàng hải và Đường thủy Việt Nam` post-2022 merger — same org): resolved 9→accept (6 Cục Hàng hải renames, 2 "Ham Giang"/"xã Hàm Giang" bare↔unit location, 1 VSIC-1520 shoe-manufacturing phrasing), 3→reject (`UBND-CNXD` ≠ `Sở Xây dựng` — CNXD is Trà Vinh's civil/industrial construction *project management board*, a different org).
  5. Wrote all decisions to `merge_suggestions.decision` (`rejected`/`review_cleared`), leaving genuinely ambiguous rows as `needs_review`.
  6. Ran the drain (`POST /api/v1/internal/resolution/apply-review-cleared`, dry-run then real) — temporarily flipped `KG_AUTH_NOOP=true` on `daab-server` (docker compose), applied, then restored `KG_AUTH_NOOP=false` and restarted.

## Files changed
- `ennam.kg.python/src/ennam_kg/resolution/danger_guards.py` — GENERICS extended (3 new bare role/title terms).
- `ennam.kg.python/tests/resolution/test_danger_guards.py` — new test `test_passes_guards_blocks_bare_role_generic`.
- Serena memory `backlog/daab-kg-search-sessions-followups` — corrected stale "still gated" claim on monitoring scope to DONE with file citations.

## Current state (project 592c7ff7…)
- `merge_suggestions`: `needs_review=95` (genuinely ambiguous, needs human + source-document judgment — OCR-illegible fragments, in-document anaphora, land-parcel-vs-facility modeling questions), `review_cleared` fully drained, `rejected=1183`, **1245 new merges applied to the graph this session** (all reversible via `merge_undo`), 1 group held back by the existing hub degree-ceiling safety net.
- `daab-server` back to normal auth (`KG_AUTH_NOOP=false`).
- No code left uncommitted-vs-tested; `danger_guards.py` change has full green test suite.

## Next steps
- 95 remaining `needs_review` rows: human review via `danger_review_cli --project 592c7ff7-9f6f-4cc5-9094-d9b3b685277e` (interactive, one canonical group at a time) — no further automation shortcut identified for these.
- Consider whether the `danger_guards.py` GENERICS extension should get a short PR-style note/commit message of its own (currently uncommitted in working tree — check `git status` before next session).
- Backlog `daab-kg-search-sessions-followups` still has one open item: confirm LAAM actually calls `kg_search_sessions` with `scope=monitoring` in production (out of this repo, can't verify from DAAB side).

## Blockers / Risks
- None currently blocking. The 1245-merge drain is reversible (`merge_undo`) if a downstream consumer flags a bad merge.
