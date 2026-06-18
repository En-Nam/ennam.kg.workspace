# Checkpoint: cursor-agent (CLI re-index verify) — 2026-06-05

## What was done
- Rebuilt `indexer` + `worker` images (carry new ennam-kg-indexer package + CLI), brought stack up healthy.
- Verified `ennam-kg-index` CLI exists inside indexer image.
- Ran the Task 5 Step 4 verification of re-index REPLACE semantics + repo-relative file_path.
- Target repo SWITCHED from ennam-kg-go → ennam-kg-python: the indexer has NO Go parser
  (registered parsers = TypeScript, Python, Dart). Go discovers 0 files, so it cannot
  exercise the indexer at all. Python repo discovers 164 files.

## Results (project 50908a01-a9db-4b82-afbd-612c18e6de2d, fresh)
- 1st run: files=163 symbols=927 nodes_created=913 updated=0 archived=0 edges=352
- 2nd run (identical): nodes_created=0 updated=0 archived=0 edges_created=0
- Active indexer nodes: 913 before AND 913 after 2nd run (no accumulation)
- file_path stored REPO-RELATIVE (e.g. src/ennam_kg/agentic/engine.py) — not absolute
- properties.repo_path = /repos/ennam-kg-python
- Human nodes archived by indexer: 0
- Edges in project stable at 352 (no duplication)

## Current state — PASS (all stated criteria), with 1 quality concern
- file_path relative: PASS
- 2nd run ~0 new nodes, active count identical: PASS
- edges on 1st run, no crash on re-index: PASS (did not crash)
- no human nodes archived: PASS
- CONCERN (HIGH): 2nd run re-POSTs all 353 edges and gets HTTP 409 for each;
  these flood the summary errors[] array (~160KB output). Run survives and edges
  don't duplicate (server enforces uniqueness), but the indexer is NOT deduplicating
  edges client-side on re-index. Recent commits (ddf4f1c, 8bb8e96) intended edge
  re-index dedup — implementation still relies on server 409s. errors[] noise could
  mask real errors.

## Next steps
- Decide: treat edge-409-on-reindex as acceptable, or implement client-side edge
  existence check / skip-on-409 so re-index errors[] stays clean.
- Optionally re-run the same proof against ennam-kg-next (TS, 226 files) for breadth.
- Go indexing is a no-op until a Go parser is added (out of current scope).

## Blockers / Risks
- `docker compose` must be run from workspace root; running it from
  ennam.kg.python/ spins up a SEPARATE conflicting stack (port 8081 clash). Hit + cleaned.
