# Checkpoint: cursor-agent (indexer CLI + packaging) — 2026-06-05

## What was done
Implemented the full plan `docs/superpowers/plans/2026-06-05-indexer-cli-packaging.md`
via subagent-driven development (implementer + spec review + code-quality review per task).
All 5 tasks complete, on branch `task/sines-enhancement` in `ennam.kg.python`.

- T1: `file_path` normalized repo-relative early in `engine._process_files`; stable `repo_key`
  threaded through extractor/engine; physical root resolved once; incremental changed-files joined to root.
- T2: mode-aware archive scope in differ — full=`repo` (whole-repo replace), incremental=`file`;
  code-only guard (`created_by=="python-indexer"` + non-empty file_path) never archives human nodes.
- T3: `ennam-kg-index` CLI (cli.py) — argparse, env/flag config, pre-flight, JSON summary, exit 0/2/1;
  console script in pyproject. Pre-flight `except` narrowed to `(httpx.HTTPError, KGClientError)`.
- T4: package-local `Dockerfile` (two-stage, no git). Image builds; `--help` runs in-container.
- T5: README CLI/Docker/migration section; clean-room install OK (no anthropic dep).

## Files changed (8 commits 9e5c33d..72f65dd)
- src/ennam_kg_indexer/indexer/extractor.py, indexer/engine.py, indexer/differ.py
- src/ennam_kg_indexer/cli.py (new), pyproject.toml ([project.scripts])
- Dockerfile (new), README.md
- tests/test_extractor.py, test_differ.py, test_engine.py, test_engine_relative_paths.py (new), test_cli.py (new)

## Current state — VERIFIED
- Indexer suite: 79 passed.
- No regression: failing-test set IDENTICAL between baseline 3744c45 (9 failed/271 passed/17 errors)
  and HEAD (9 failed/350 passed/17 errors; +79 indexer tests). Pre-existing failures are e2e (live stack)
  + agentic/benchmark/streaming — unrelated.
- Live Docker e2e: scan1 created 3 nodes; scan2 (same repo-key) created 0/updated 0/archived 0
  → replace-not-accumulate CONFIRMED against real backend.

## First-scan edge defect — FOUND in deep re-check, now FIXED (commit ed46ff9)
Symptom: first-scan edges failed with API 400 (empty source_id/target_id), self-healing on a later scan.
Root cause (proven against Go source `ennam.kg.go/internal/handler/node.go:99-103,208`): POST /api/v1/nodes
returns `{"node": {"id": ...}}` (storeNodeResponse), but `engine._process_files` read `resp.get("id","")`
-> always empty -> node_id_map filled with "" -> edges sent with empty endpoints. get_nodes returns
top-level `id`, which is why scan 2 worked. Pre-existing (the read line last changed in 09f2326, before
this work; plan's Part 2.4 added no edge code), and the original edge test used a flat `{"id":"n-1"}` mock
that masked it.
Fix: engine now unwraps `resp.get("node", resp).get("id","")`; `test_containment_edge_created` mirrors the
real `{"node":{"id":...}}` envelope and asserts non-empty edge endpoints (verified FAIL without the fix,
PASS with it). Zero regression (combined-suite failing set identical to pre-work baseline).

## Next steps
- User decision: branch finish (merge `task/sines-enhancement` / open PR / stay).
- Optional follow-ups (out of this plan's scope): fix create_node id extraction so first-scan edges
  succeed (and make the edge test assert against a realistic create response); add `.dockerignore` +
  non-root user + pin uv tag before CI; thread explicit `repo_key` through worker/api message schemas
  if mount path can change across redeploys.

## Blockers / Risks
- None blocking. The first-scan edge defect is pre-existing and self-heals on re-index; flag for a
  separate fix.
