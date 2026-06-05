# MCP Bridge stdio Serve Loop — Design Spec

**Date**: 2026-06-05
**Status**: Approved (design)
**Goal**: Implement the missing MCP stdio server in `kg-bridge` so the 24 existing knowledge tools actually serve any MCP host (Claude Code and other models/hosts) — completing BA-002 Phase 1. The bridge package already has the building blocks (schemas, validation, HTTP-forward client, response formatting); this wires them into a live `kg-bridge serve` command over stdio.

**Why now**: Investigation (2026-06-05) found the MCP serve loop does not exist: `kg-bridge` has no `serve` command, `internal/bridge` has no stdio/JSON-RPC loop, `HandleToolCall`/`ListTools`/`WriteSessionFile` have no production caller, and there is no MCP library in `go.mod`. The platform's core promise ("accessible via MCP" — CLAUDE.md; agent boot protocol uses MCP as PRIMARY source) is therefore unfulfilled. This spec closes that Phase-1 gap.

**Unblocks**: `2026-06-05-mcp-index-source-tool-design.md` (`kg_index_source`) — layered on top once this serve loop exists.

---

## Scope

**In scope** — complete BA-002's bridge as a working MCP stdio server:
- `kg-bridge serve` command: load config → build client + handler → run stdio MCP server.
- MCP surface: `initialize` (capability = **tools only**), `tools/list`, `tools/call`.
- Serve the **24 existing tools** by wiring `ListTools()` + `HandleToolCall()`.
- Wire the **`.kg_session` file side-effects** (BR-004.3) for `kg_store_session` / `kg_end_session` — also currently unwired.
- Config loader (read `~/.kg/config.yaml` + env override) — also currently missing.

**Out of scope:**
- `kg_index_source` / `kg_index_status` local-execution tools (separate spec, layered after).
- MCP resources, prompts, sampling, server-initiated messages, HTTP/SSE transport.
- Auto-injecting `default_project_id` into tool params — BA-002 has no BR requiring it and its acceptance criteria show agents passing `project_id` explicitly; agents continue to pass it. (The config field still exists for the `kg_index_source` fallback in the other spec.)

---

## Decision: protocol via official SDK, isolated (with a maturity gate)

Use the official **`github.com/modelcontextprotocol/go-sdk`** for the stdio JSON-RPC + handshake, rather than hand-rolling the protocol.

**Rationale (long-term):** the core goal is "any agent/host can call it" — protocol-correctness across diverse, evolving MCP clients is exactly what a maintained SDK provides, with lower long-term maintenance than hand-rolled JSON-RPC/framing/handshake. The repo's lean-deps philosophy is respected via **isolation**: all SDK/protocol code lives in ONE new file `internal/bridge/serve.go`; `handler.go`/`schema.go`/`client.go`/`session.go` stay SDK-agnostic, so the SDK can be swapped or replaced by a hand-rolled loop later without touching tool logic.

**Maturity gate (run FIRST in the plan, before committing to the SDK):** verify the SDK
1. exists with a recent release and is compatible with `go 1.25`;
2. supports a **stdio server** and **registering tools from pre-built JSON input schemas with a generic call handler** (must NOT require per-tool Go structs / reflection — our tools come from `ListTools()` as `map[string]interface{}` schemas);
3. has been exercised against real MCP clients.
If the gate fails (immature / abandoned / heavy breaking changes / struct-only API), **fall back to a hand-rolled stdio loop** — a bounded surface: JSON-RPC framing over stdin/stdout + `initialize` + `tools/list` + `tools/call`. Either implementation lives behind the same `serve.go` boundary.

---

## Components

| File | Action | Responsibility |
|------|--------|----------------|
| `cmd/kg-bridge/main.go` | Modify | add `case "serve"` → `bridge.RunServe(args)` |
| `internal/bridge/serve.go` | Create | the ONLY SDK-importing file: config load, build client+handler, register tools, run stdio server, dispatch + map results |
| `internal/bridge/config_load.go` | Create | read `~/.kg/config.yaml` + env override (`KG_API_KEY`/`KG_SERVER_URL`/`KG_PROJECT_ID`) → resolved config |
| `internal/bridge/uuid.go` | Create | `newUUIDv4()` — RFC-4122 v4 string from `crypto/rand` (repo has no uuid dep); used to generate `session_id` for `kg_store_session` |
| `internal/bridge/handler.go` | (reuse) | `HandleToolCall`, `ListTools` — unchanged, SDK-agnostic |
| `internal/bridge/session.go` | (reuse) | `WriteSessionFile`/`RemoveSessionFile` — wired by serve.go |
| `internal/bridge/init.go` | (reuse) | `Config` struct + `RunInit` — config reader added in config_load.go |

---

## Serve flow

`RunServe`:
1. **Load config** (`config_load.go`): read `~/.kg/config.yaml` (`api_key`, `server_url`, `default_project_id`); apply env overrides `KG_API_KEY`/`KG_SERVER_URL`/`KG_PROJECT_ID` (env wins — BR-006.3). Fail fast if `api_key`/`server_url` unresolved.
2. `client, _ := NewClient(serverURL, apiKey)`
3. `handler := NewMCPToolHandler(client)`
4. Build the MCP server: register every tool from `handler.ListTools()` (name, description, inputSchema), set a single generic `tools/call` dispatcher, declare capability = tools.
5. Run over stdio until stdin EOF / SIGINT / SIGTERM, then clean shutdown.

---

## `tools/call` dispatch

A single generic handler in `serve.go`:

```
onToolCall(name, rawArgs):
    params := decode rawArgs -> map[string]interface{}      # SDK arg type -> map for HandleToolCall

    # kg_store_session needs a client-generated session_id (see below) — inject BEFORE forwarding:
    sessionID := ""
    if name == "kg_store_session":
        sessionID = newUUIDv4()                              # crypto/rand helper (no uuid dep in repo)
        params["session_id"] = sessionID

    result, errResp := handler.HandleToolCall(ctx, name, params)
    if errResp != nil:                                       # protocol-level (unknown tool / bad params)
        return SDK JSON-RPC error

    # session side-effects (BR-004.3) — only on success:
    if name == "kg_store_session" and not result.IsError:
        sf := buildSessionFile(params, result, sessionID, serverURL)   # see below
        WriteSessionFile(cwd(), sf)                          # cwd = bridge working dir (inherited from MCP host = project dir)
    if name == "kg_end_session" and not result.IsError:
        RemoveSessionFile(cwd())
    return mapToSDKResult(result)                            # content + isError
```

> **Why generate `session_id` (verified against the Go API):** `POST /api/v1/sessions` **requires a client-supplied `session_id`** — `service.StartSession` uses `req.SessionID` directly (`session.go:121 ID: req.SessionID`) and `validateStartRequest` rejects an empty one (`session.go:345-346`). The server does NOT generate it. Yet the `kg_store_session` tool schema does NOT expose `session_id` (BR-004.1: only `project_id`, `agent_name`, `work_scope?`, `metadata?`) and `HandleToolCall` only injects `node_type`, not `session_id`. So **the bridge must generate the id and inject it** — otherwise `kg_store_session` fails the API's required-field check. This matches BA-002's intent (the `.kg_session` file is "written by the bridge" and contains the id). The repo has **no uuid dependency**, so add a small UUIDv4 helper built on `crypto/rand` (pattern: the API expects UUID format — `kg_end_session` schema uses `Format:"uuid"`, `uuidPattern`).

### `buildSessionFile` field sources

`SessionFile` is assembled from three sources (verified against `session.go`):

| Field | Source |
|-------|--------|
| `SessionID` | the **bridge-generated** `sessionID` (the same value injected into the request) — NOT from the response |
| `StartedAt` | created-session response, `session.started_at` |
| `ProjectID` | request params (`project_id`) |
| `Agent` | request params (`agent_name`) |
| `Scope` | request params (`work_scope`, optional) |
| `TaskDescription` | request params (`task_description`, optional) |
| `ServerURL` | resolved bridge config `server_url` |

> **How to read `started_at` (verified against `mcpresponse.go` + `session.go`):** `HandleToolCall` does NOT expose the raw API body — it returns `*MCPToolResult` whose `Content[0].Text` is `json.MarshalIndent` of the response body (mcpresponse.go:124-136). The create-session response is **nested under a `session` key** (`session.go:166` encodes `sessionResponse{Session: session}`), and the session object has `started_at` (`models/session.go:60 json:"started_at"`). So `buildSessionFile` must `json.Unmarshal(result.Content[0].Text)` into a `map[string]any` and read `["session"]["started_at"]`. If parsing fails, fall back to the bridge's own clock (`time.Now().UTC()`) for `started_at`, still write the file, and log to stderr — do not fail the tool call. `SessionID` does NOT come from the response; it is the id the bridge generated and injected.

`cwd()` = `os.Getwd()` of the bridge process. The bridge runs as a subprocess of the MCP host, inheriting the host's working directory (the agent's project directory) — which is where git pre-commit hooks expect `.kg_session` (BR-004.3).

### Result mapping (Part: error model)

- `HandleToolCall` → `(*MCPToolResult, *MCPErrorResponse)`.
- `MCPToolResult` (tool-level; may carry `IsError: true` for 409, validation, server errors) → SDK tool result: copy `Content` → SDK content, `IsError` → SDK isError. Tool-level errors reach the agent as results, not transport failures.
- `MCPErrorResponse` (protocol-level: unknown tool, malformed params) → SDK JSON-RPC error response.

This preserves BA-002's two-tier error distinction.

---

## stdout discipline (CRITICAL for stdio MCP)

MCP stdio uses **stdout as the JSON-RPC channel**. A single stray write to stdout (a stray `fmt.Print`, a library log line) corrupts the protocol stream and breaks every client. Requirements:

- During `serve`, **stdout is owned exclusively by the MCP server** (the SDK, or the hand-rolled loop) for protocol frames.
- ALL diagnostics, logs, and errors from `RunServe`, config loading, the dispatch, and session-file handling go to **stderr** (`fmt.Fprintln(os.Stderr, ...)` / `slog` with a stderr handler).
- The existing `fmt.Printf`/`fmt.Println` calls in `init.go` are fine — they run only under the `init` command, never under `serve`. The serve code path must add **no** stdout writes.
- **SDK gate addition:** verify the chosen SDK writes protocol to stdout and its own diagnostics to stderr (or makes the log destination configurable). Reject an SDK that logs to stdout.
- A test asserts the `tools/list` E2E smoke produces **only** valid JSON-RPC on stdout (no extra lines).

## Error handling

| Situation | Behavior |
|-----------|----------|
| `api_key`/`server_url` unresolved (config + env both empty) | `RunServe` exits non-zero with a clear message before starting the server. |
| Go API unreachable at runtime | per-tool: `HandleToolCall`'s client returns an error → `MCPToolResult{IsError:true}` with the API error (BA-002 fail-fast behavior unchanged). |
| Unknown tool name | `MCPErrorResponse` → SDK JSON-RPC error. |
| Malformed params | bridge-side schema validation (existing `ValidateToolParams` inside `HandleToolCall`) → `MCPToolResult{IsError:true}`. |
| `WriteSessionFile` fails (e.g. read-only cwd) | log to stderr; the tool result still returns success (the KG session was created server-side; the file is a local convenience). Do not fail the tool call. |
| stdin EOF / signal | clean shutdown of the serve loop. |

---

## Testing

- **Config loader (unit):** env overrides file values; missing required values → error. Table-driven.
- **Dispatch mapping (unit):** with a fake/mocked `HandleToolCall`, assert `MCPToolResult` → SDK result mapping (content + isError) and `MCPErrorResponse` → JSON-RPC error. No real stdio needed.
- **Session id generation + injection (unit):** `kg_store_session` dispatch generates a UUIDv4 `session_id` and injects it into the params passed to `HandleToolCall` (assert the forwarded params contain a valid-UUID `session_id`); `newUUIDv4()` produces RFC-4122 v4 format.
- **Session side-effects (unit):** `kg_store_session` success → `WriteSessionFile` writes a `.kg_session` (temp cwd) whose `session_id` equals the generated/injected id, `started_at` parsed from `result.session.started_at`, other fields from params + config; on unparseable `started_at`, falls back to `time.Now()` and still writes; `kg_end_session` success → file removed; a `WriteSessionFile` failure does not fail the tool result.
- **`buildSessionFile` (unit):** field-source mapping correct (response vs params vs config).
- **E2E protocol smoke:** start `kg-bridge serve` as a subprocess, send a JSON-RPC `initialize` then `tools/list` over stdin, assert the response advertises capability=tools and lists all 24 tools with schemas; send one `tools/call` (e.g. `kg_query`) against a stubbed/live Go API and assert the forwarded result. Validates real protocol wiring.
- **Manual:** configure Claude Code (and ideally one non-Claude MCP host) to spawn `kg-bridge serve`; confirm tools appear and `kg_query` works against a live Go API.

---

## Self-Review notes

- Building blocks confirmed present and SDK-agnostic: `HandleToolCall` (handler.go:78), `ListTools` (handler.go:147, sourced from `ListToolSchemas()` not `toolRoutes`), `WriteSessionFile`/`RemoveSessionFile` (session.go), `Config` (init.go: `api_key`/`server_url`/`default_project_id`).
- No uuid dependency needed here (job ids belong to the `kg_index_source` spec).
- The SDK choice is gated and isolated, so the dependency decision is reversible.
