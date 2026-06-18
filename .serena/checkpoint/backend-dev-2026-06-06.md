# Checkpoint: backend-dev — 2026-06-06

## What was done
Implemented the MCP Bridge stdio serve loop (plan `docs/superpowers/plans/2026-06-05-mcp-bridge-serve-loop.md`) via subagent-driven development — 6 tasks, each TDD + two-stage review (spec then code-quality) + a final holistic review.
- Task 1: `internal/bridge/config_load.go` — `LoadConfig`/`LoadConfigFrom` (~/.kg/config.yaml + env overrides, env wins).
- Task 2: `internal/bridge/uuid.go` — `newUUIDv4()` (crypto/rand, no new dep).
- Task 3: `internal/bridge/serve.go` — official `modelcontextprotocol/go-sdk` v1.6.1; `RunServe`, `registerTools`, `makeToolHandler`, schema/result adapters; `cmd/kg-bridge/main.go` `serve` case.
- Task 4: session side-effects in serve.go — `session_id` gen/inject for `kg_store_session`, `.kg_session` write; remove on `kg_end_session`.
- Task 5: `internal/bridge/serve_e2e_test.go` — in-memory SDK client↔server: initialize + tools/list + real tools/call.
- Task 6: built binary, raw stdio handshake verified, BA-002 implementation note appended.

## Files changed
- ennam.kg.go: `internal/bridge/{config_load,uuid,serve}.go` (+ tests), `internal/bridge/serve_e2e_test.go`, `cmd/kg-bridge/main.go`, `go.mod`/`go.sum`, one-line `fmt` import fix in `internal/bridge/integration_test.go`.
- ennam.kg.requirements: `documents/phase1/BA-002-mcp-bridge.md` (note, committed 5f63f5e in that repo).

## Current state (branch `task/sines-enhancement`, ennam.kg.go tip `3ce95c8`)
- WORKING: build clean, vet clean, gofmt clean. All 8 feature test groups pass under -race. Real binary answers `initialize` (serverInfo ennam-kg/v1) and `tools/list` (30 tools) over stdio with clean stdout discipline.
- SDK API deviations from plan (all adapted): jsonschema is `github.com/google/jsonschema-go/jsonschema`; `CallToolRequest.Params.Arguments` is `json.RawMessage`; `Tool.InputSchema` is `any`; non-generic `Server.AddTool(*Tool, ToolHandler)`.
- KNOWN PRE-EXISTING (out of scope): 9 top-level bridge test failures from schema drift — schema.go registers 30 tools while tests/BA-002 expect 19/25 and `node_type` is now required on kg_query. NOT touched by this feature; the integration_test.go `fmt` import was missing (package didn't compile before this work) and was fixed.

## Next steps
- Manual: point a live MCP host (Claude Code) at `kg-bridge serve` with the Go API up (docker compose up -d kg-server postgres redis) and confirm a real `kg_query` returns data + `kg_store_session` writes `.kg_session`.
- Separate task: reconcile the 30-vs-25 tool-count drift across schema.go / schema_test.go / client_test.go / BA-002.
- Not yet pushed; branch is ahead of origin.

## Tool-count drift reconciliation (follow-up, user-requested same session)
Decided source-of-truth: `schema.go`/`handler.go`/`client.go` (implementation) are correct; the failing tests + BA-002 were stale. Evidence: the 5 extra tools (kg_ingest_node/batch, kg_list_drafts, kg_approve_drafts, kg_process_drafts) come from `38bc6b6 feat(phase6)`; `node_type` required on kg_query is genuine (e2e_tools_test supplies it, injectNodeType covers only kg_store_*); client.go DOES url.PathEscape (the path test checked decoded r.URL.Path instead of EscapedPath).
- Fixed ONLY tests + docs (impl untouched): commit `04e1171` (ennam.kg.go test files), `5a63b54` + `8b7d445` (ennam.kg.requirements BA-002 + CLAUDE.md), all → 30 tools.
- Two tests got STRONGER: path-escaping now asserts `%20` present in EscapedPath; boolean-mismatch retargeted from kg_query's non-existent `include_edges` to kg_get_neighbors `include_cross_project` (a real bool field).
- RESULT: `go test ./internal/bridge/ -race -count=1` → ok, **0 failures** (was 9 pre-existing). go build ./... clean.

## Blockers / Risks
- A review subagent left this working dir checked out on `main` mid-run (ran `git checkout main` after a detached diff). Recovered: switched back to `task/sines-enhancement`; all commits intact. Watch for stray `.worktrees/` and `data/` untracked dirs in ennam.kg.go.
- Nothing pushed. Both repos on `task/sines-enhancement`.

---

## Session 2 (same day) — implemented `kg_index_source`/`kg_index_status` plan

### What was done
Fully implemented `docs/superpowers/plans/2026-06-06-mcp-kg-index-source-tool.md` via
subagent-driven development (implementer + spec review + code-quality review per task,
plus a final holistic go-reviewer pass). Added two MCP **local-execution** tools:
`kg_index_source` (start a local index, returns job_id immediately) and `kg_index_status`
(poll). They spawn the locally-installed `ennam-kg-index` CLI as a subprocess and inject
`KG_API_URL`/`KG_API_KEY` so the agent never handles the key. Indexing is async
(background goroutine + in-memory job map under a mutex). Bridge surface is now **32 tools
= 30 HTTP-proxy + 2 local-execution**.

### Files changed (ennam.kg.go, branch `task/sines-enhancement`)
- `internal/bridge/config_load.go` — `IndexerCLIPath` (`indexer_cli_path`) field
- `internal/bridge/schema.go` — 2 schema registrations + `localToolNames` set + comment fixes
- `internal/bridge/local_index.go` (NEW) — `LocalIndexHandler` (subprocess + async job map)
- `internal/bridge/serve.go` — dispatch the 2 local tools in `makeToolHandler` before forward
- tests: `local_index_test.go` (NEW), `serve_local_index_test.go` (NEW), plus count fixes in
  `schema_test.go`, `handler_test.go`, `e2e_tools_test.go`
- `README.md` — local-indexing subsection + tool-count 25→32 corrections
- (separate repo ennam.kg.requirements) `documents/phase1/BA-002-mcp-bridge.md` — 2-category note

### Commits
ennam.kg.go: `1de868e` config · `1604412` schemas · `2d15c14` LocalIndexHandler ·
`f8f89b5` dispatch · `2807080` README · `c0c0075` README count · `68557c2` stale-comment/expectedTools.
ennam.kg.requirements: `9681c4b` BA-002 note.

### Current state
WORKING: `go test ./internal/bridge/ -count=1 -race` PASS; `go build ./...` clean;
`go vet ./internal/bridge/` clean; all new files gofmt-clean. Final review: **ready to merge**,
no Critical/High issues.

### Next steps
- Manual acceptance smoke (plan Steps 4a Mac / 4b Windows "Cách B") NOT run — operator steps.
  On Windows set `indexer_cli_path` explicitly (PATH/PATHEXT caveat).
- Not pushed (project convention: local commits). Use finishing-a-development-branch when ready.

### Blockers / Risks
- Pre-existing gofmt alignment violations in `schema.go` (lines ~778/1066/1244/1259) predate
  this work (present at 04e1171); left untouched per surgical-changes rule. `make lint` flags
  them independently of this feature.
- `ennam.kg.go/CLAUDE.md` still says "25 MCP tool calls" — out of plan scope, not edited.
