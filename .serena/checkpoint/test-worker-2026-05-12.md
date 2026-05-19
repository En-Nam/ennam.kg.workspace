# Checkpoint: test-worker — 2026-05-12

## What was done

- Ran Wave 2 browser E2E tests (UI-01 through UI-08) using Chrome DevTools MCP
- Fixed 3 blocking bugs discovered during test execution:
  1. **SSE content format mismatch**: `SSEContent.Data` field added to Go model; `HandleContentToken` fallback to `Data` when `Token` is empty — fixes `(streamed response)` bug
  2. **Anthropic SDK objects not JSON-serializable**: `engine.py` now stores `[b.model_dump() for b in response.content]` in messages list — fixes multi-iteration tool call crash
  3. **conftest.py projects fixture**: Fixed `KeyError: 0` by extracting `data["projects"]` from dict response
- Applied fixes to running Docker environment via `docker cp` + `docker compose restart`
- Ran Layer 1 API smoke tests (`pytest tests/e2e/test_api_smoke.py`)
- Ran Layer 3 accuracy evaluation (`pytest tests/e2e/test_accuracy.py`)
- Wrote Wave 2 results report and backlog files for new bugs

## Files changed

- `ennam.kg.go/internal/models/sse.go` — Added `Data` field to `SSEContent`
- `ennam.kg.go/internal/service/sse_stream.go` — `HandleContentToken` Data fallback; `pythonEndpoint()` routing (from previous session)
- `ennam.kg.python/src/ennam_kg/agentic/engine.py` — `model_dump()` serialization fix
- `tests/e2e/conftest.py` — projects fixture shape fix
- `docs/superpowers/test-results/browser-e2e-wave2-results.md` — new report
- `.serena/memories/backlog/python-list-datasources-node-type.md` — new backlog
- `.serena/memories/backlog/next-agentic-stream-error-reset.md` — new backlog

**Committed:**
- Go repo: `5fee27a` — feat(agentic): add agentic stream routing and SSE content format support
- Python repo: `1e84f41` — feat(agentic): agentic engine with tool-calling loop and SSE streaming

## Current state

### Working ✅
- Quick tier end-to-end flow (agent_start → tools → content → agent_done → done)
- TierSelector UI (visible, localStorage persistence, request body tier field)
- Content text appearing in ChatMessageList after stream
- History refresh after stream completion
- Go API routing to agentic endpoint when tier is set
- DDL rejection SQL gate

### Broken / Degraded ❌
- `list_datasources` tool uses wrong node_type → all Deep tier flows hit 400 on first tool call
- `useAgenticStream` doesn't reset isStreaming on error events (no done event emitted on error)
- Layer 1: test_api_02 (Deep tier) and test_api_04 (SELECT enforcement) failing
- Layer 3 accuracy: 6/12 cases passing (below 2.0/3.0 gate)

## Next steps

1. **Git commit** all changed files (Go models, Go service, Python engine, conftest)
2. **Fix `list_datasources` node_type** — check correct node type in KG API config, fix in Python tools
3. **Fix `useAgenticStream` error reset** — add `setIsStreaming(false)` on error event and onerror callback
4. Re-run Layer 1 and Layer 3 after fixes
5. Investigate test_api_04 (execute_sql not invoked) separately — may need schema context in test query

## Blockers / Risks

- Python changes require `docker cp` + restart (not volume-mounted) — add to ops notes
- No KG seed data in test environment blocks UI-05 (KG traversal) and some accuracy cases
- Accuracy gate (2.0/3.0) not met until list_datasources is fixed

---

## Append — Bug fixes session (2026-05-12, post-Wave-2)

### What was done
- Fixed `list_datasources` P2 bug: replaced `kg.search(node_types=["data_source"])` with `kg.list_data_sources(project_id)` calling `GET /api/v1/data-sources`
- Added `KGClient.list_data_sources()` method
- Added try-except in `engine.py` around `tool_factory.execute()` so tool exceptions return error dicts instead of crashing the generator
- Fixed stream error termination: `agentic.py` now yields `done` after `error` so Go proxy closes client stream cleanly
- Fixed `useAgenticStream.onAgentDone` to set `isStreaming: false` for immediate UI response
- All 68 Python agentic tests passing

### Commits
- Python `ca42aab` — fix(agentic): list_datasources uses data-sources API + engine tool exception handling
- Python `20b7b63` — fix(agentic): yield done event after error so Go proxy closes stream cleanly
- Python `d9e81f0` — fix(test): remove dead data_lines var, move json import to top
- NextJS `ecbdfe8` — fix(stream): set isStreaming:false on agent_done for immediate UI response
- NextJS `8b1a61c` — chore(stream): document why resumeFromClarification passes empty project_id/data_source_id

### Current state
Both P2/P3 bugs from Wave 2 report are fixed and committed. System should now pass:
- UI-04 (Deep tier ≥2 tool calls)
- UI-06 (error clears isStreaming without page refresh)
- test_api_02 (Deep tier smoke test)
- Layer 3 accuracy should improve significantly (list_datasources unblocked)

### Next steps
- Apply fixes to Docker env: `docker cp` Python files + restart indexer for Python changes; `npm run build` or hot-reload for NextJS
- Re-run Wave 2 test suite to verify full pass
