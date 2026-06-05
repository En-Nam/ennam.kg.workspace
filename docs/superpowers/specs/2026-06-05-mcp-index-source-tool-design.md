# MCP `kg_index_source` Tool — Design Spec

**Date**: 2026-06-05
**Status**: Approved (design)
**Goal**: Add MCP tools that let ANY agent (any model / MCP host, including non-shell ones) trigger local code indexing through the `kg-bridge`, by shelling out to the locally-installed `ennam-kg-index` CLI. Indexing runs asynchronously so it never hits MCP host tool-call timeouts.

**Depends on**: `2026-06-05-indexer-cli-packaging-design.md` (DONE — `ennam-kg-index` CLI exists and is verified).

---

## Context

The `kg-bridge` (Go, BA-002) is the MCP entry point for agents. All 24 existing tools are **HTTP-proxy tools**: each maps to a REST route in `toolRoutes` and the bridge forwards the call to the remote KG API (zero business logic — "pure protocol translator").

Indexing the agent's **local** source cannot be a forward-HTTP tool: the remote KG API cannot see the agent's filesystem. The work (read files → tree-sitter parse → diff → push) lives in the Python indexer, exposed as the `ennam-kg-index` CLI. So the bridge must **spawn that CLI as a local subprocess** on the agent's machine.

**Why an MCP tool at all (not just "run the CLI via shell"):** Claude Code has a Bash tool and could run the CLI directly, but MCP is model/host-agnostic. Many MCP hosts/agents (other models, restricted/enterprise hosts) expose **only MCP tools and have no shell**. For them, an MCP tool is the *only* way to trigger local indexing. Serving any agent is the whole point of an MCP bridge (BA-002). The tool also injects credentials so the agent never handles the API key.

**Prerequisite (unchanged either way):** the agent's machine must have `ennam-kg-index` installed. The MCP tool adds a call path for non-shell agents; it does not remove the install requirement.

---

## Decisions (confirmed)

| # | Decision | Choice |
|---|----------|--------|
| — | Build the tool? | **Yes** — model/host-agnostic, for any agent incl. non-shell |
| Q1 | Scan modes exposed | **Full scan only** (agent re-calls to refresh; engine diffs create/update/archive) |
| Q2 | Execution model | **Async** — start tool returns immediately + a status tool to poll (no MCP timeout risk) |
| Q3 | CLI location | **Config override + PATH fallback** (`indexer_cli_path` in `~/.kg/config.yaml`, else `exec.LookPath`) |
| — | `project_id` | **Optional** — falls back to bridge config default project; error if neither |
| — | BA-002 deviation | Isolated in a new `local_index.go`; documented at the bottom of BA-002 |

---

## Part 1 — The two MCP tools

Registered in the existing schema registry (`buildToolSchemas()` in `schema.go`) so they appear in `tools/list` and get bridge-side param validation. They are **NOT** added to `toolRoutes` (no HTTP route).

### `kg_index_source` — start an index (returns immediately)

| Param | Required | Type | Notes |
|-------|----------|------|-------|
| `path` | yes | string | local source directory on the agent's machine |
| `project_id` | no | string | KG project; falls back to bridge config default project if omitted |
| `repo_key` | no | string | stable repo identity (default = `path`) |

Returns (MCP text content, JSON): `{ "job_id": "idx-<uuid>", "status": "running" }`

### `kg_index_status` — poll progress

| Param | Required | Type |
|-------|----------|------|
| `job_id` | yes | string |

Returns (MCP text content, JSON):
- running: `{ "job_id", "status": "running" }`
- done: `{ "job_id", "status": "done", "summary": { files_scanned, symbols_found, nodes_created, nodes_updated, nodes_archived, edges_created, errors } }`
- error: `{ "job_id", "status": "error", "error": "<message + stderr tail>" }`
- unknown job_id: MCP `isError: true`, text "unknown job_id".

**Agent flow:** call `kg_index_source` → get `job_id` → poll `kg_index_status(job_id)` every few seconds until `done`/`error`.

`mode`/`changed_files` are **not** exposed — "index this repo" = full scan; the engine's repo-scoped diff handles changed/added/deleted files automatically (verified: re-index replaces, does not accumulate).

---

## Part 2 — Bridge dispatch architecture (BA-002 deviation, isolated)

`HandleToolCall` gains a new branch **before** the existing `GetToolRoute` HTTP path:

```
HandleToolCall(tool, params):
    if tool in localTools {kg_index_source, kg_index_status}:   # NEW branch
        return localIndexHandler.Handle(tool, params)
    # existing path, UNCHANGED:
    GetToolRoute(tool) -> validate -> forward HTTP (CallToolMCP)
```

- All local logic (subprocess, job map, CLI lookup, env injection) lives in a **new file `internal/bridge/local_index.go`** (`LocalIndexHandler`). The HTTP-proxy path is **not touched** — the 24 existing tools remain pure protocol translators, preserving BA-002.
- The bridge now has **two clearly-bounded tool categories**: *HTTP-proxy tools* (24, unchanged) and *local-execution tools* (2, new, deliberate and isolated). A `localTools` set distinguishes the two dispatch branches.
- **Discovery + validation work automatically:** `ListTools()` builds from `ListToolSchemas()` (the schema registry), and `ValidateToolParams` uses `GetToolSchema` — both registry-based, not route-based (verified). Registering the two schemas is sufficient for them to appear in `tools/list` and be validated. `GetToolRoute` is never called for them because the local branch precedes it.
- **Doc:** append a note at the bottom of `BA-002-mcp-bridge.md` describing the two categories, so future maintainers don't assume "every tool proxies HTTP."

---

## Part 3 — Subprocess execution

### CLI location (Q3)
1. `indexer_cli_path` from `~/.kg/config.yaml`, if set.
2. else `exec.LookPath("ennam-kg-index")`.
3. neither → error (Part 4).

### Credential injection (the agent never handles secrets)
The bridge already holds `baseURL` + `apiKey` (the `Client` it uses to talk to the API — `client.go` fields). `LocalIndexHandler` is constructed with these. When spawning, it injects:
```
env: KG_API_URL=<bridge baseURL>, KG_API_KEY=<bridge apiKey>
args: --path <path> --project-id <project_id> --repo-key <repo_key|path> --mode full
```
The agent supplies only `path` (+ optional `project_id`, `repo_key`); it never sees the API key.

### Background run + in-memory job map
```go
type indexJob struct {
    status  string   // "running" | "done" | "error"
    summary map[string]any
    errMsg  string
}
// in LocalIndexHandler:
jobs map[string]*indexJob
mu   sync.Mutex
```
- `kg_index_source`: generate `job_id` (uuid), set `jobs[job_id] = {running}`, launch `exec.CommandContext(ctx, cli, args...)` in a **goroutine** with stdout+stderr captured, return `job_id` immediately.
- On subprocess exit: exit 0 → parse stdout JSON → `{done, summary}`; exit ≠ 0 → `{error, stderr tail}`; unparseable stdout → `{error, "could not parse indexer output"}`.
- **Timeout backstop:** `ctx` carries a configurable deadline (default 30 min). Async, so it never blocks the agent; the deadline only prevents a hung subprocess from living forever.
- `kg_index_status`: read `jobs[job_id]` under the mutex.

### Lifecycle
The `kg-bridge serve` process is long-lived for the MCP session, so the in-memory job map persists across tool calls within a session. A bridge restart loses jobs — acceptable (the index either already pushed to KG or the agent re-triggers). No durable store.

---

## Part 4 — Error handling

| Situation | Behavior |
|-----------|----------|
| CLI not found (config + PATH both fail) | `kg_index_source` → MCP `isError:true`: "ennam-kg-index not found. Install: `pip install ennam-kg-indexer`, or set `indexer_cli_path` in ~/.kg/config.yaml". No job created. |
| `path` does not exist | Bridge pre-checks before spawn → `isError` immediately, no job. |
| `project_id` omitted AND no bridge default | `isError`: "project_id required (or set a default project in ~/.kg/config.yaml)". |
| Bridge config missing `api_key`/`server_url` | `isError`: KG connection not configured. |
| Subprocess exit ≠ 0 (e.g. CLI pre-flight: API unreachable) | job `status=error`, `error` = stderr tail. |
| Unparseable CLI stdout | job `status=error`: "could not parse indexer output" + stdout tail. |
| Unknown `job_id` in `kg_index_status` | MCP `isError`: "unknown job_id". |

---

## Part 5 — Config & external-system setup

- **Out-of-box (most):** `pip install ennam-kg-indexer` + a configured `~/.kg/config.yaml` (`server_url`, `api_key`) → works; PATH finds the CLI; `project_id` may default from config.
- **Venv / Docker / non-standard install:** set `indexer_cli_path: /abs/path/to/ennam-kg-index` in `~/.kg/config.yaml`.
- **Config fields added to the bridge config schema:** `indexer_cli_path` (optional string), and reuse of the existing default `project_id` for the `project_id` fallback.
- **Docs:** the BA-002 bottom note (two tool categories) + a short section in the bridge README covering the two config fields and the three common errors (CLI not found, path missing, project_id missing).

---

## Part 6 — Testing (Go bridge)

Use a **fake CLI** (a stub executable written to a temp dir, with `indexer_cli_path` pointed at it) for deterministic tests — no real Python CLI required.

- **Happy path:** `kg_index_source` returns `job_id` + `running`; polling `kg_index_status` eventually returns `done` with the parsed summary (stub prints a known JSON summary to stdout).
- **Env/flags injection:** stub echoes its env + argv → assert `KG_API_URL`/`KG_API_KEY` come from bridge config and `--path/--project-id/--repo-key/--mode full` are passed correctly; the agent never passes the key.
- **Subprocess failure:** stub exits non-zero → job `status=error` with stderr captured.
- **CLI not found:** empty `indexer_cli_path` + not on PATH → `isError` with install guidance, no job.
- **Path missing:** non-existent `path` → `isError`, no job.
- **Unknown job_id:** `kg_index_status` with a bogus id → `isError`.
- **project_id fallback:** omitted → uses bridge config default; neither present → `isError`.
- **Dispatch/discovery:** both tools appear in `ListTools()` output with schemas; the local branch routes them to `LocalIndexHandler`; a representative HTTP-proxy tool (e.g. `kg_query`) still forwards HTTP unchanged (no regression).

---

## Out of Scope

- Incremental mode via MCP (full scan only; CLI still supports incremental for automated callers).
- Durable job store / cross-restart job recovery (in-memory per session).
- Concurrency caps on simultaneous index jobs (revisit if abused).
- Streaming progress (poll-based status only).
- Installing the CLI for the agent (prerequisite, not handled by the bridge).
