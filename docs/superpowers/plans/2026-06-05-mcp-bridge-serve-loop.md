# MCP Bridge stdio Serve Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `kg-bridge serve` — a working MCP stdio server that hosts the 24 existing knowledge tools (forwarding to the Go REST API) plus the `.kg_session` side-effects, completing BA-002 so any MCP host/agent can use the bridge.

**Architecture:** Use the official `github.com/modelcontextprotocol/go-sdk` (v1.x, gate-passed) for the stdio JSON-RPC + handshake, isolated in a single new `internal/bridge/serve.go`. Register every tool from the existing `ListToolSchemas()`; a per-tool handler forwards to the existing `HandleToolCall` and maps the result. `kg_store_session`/`kg_end_session` get bridge-side session-id generation/injection and `.kg_session` file writes/removes. A new config loader reads `~/.kg/config.yaml` + env overrides.

**Tech Stack:** Go 1.25, `github.com/modelcontextprotocol/go-sdk` (mcp + mcp/jsonschema), stdlib `crypto/rand`, `gopkg.in/yaml.v3`, `go test`.

**Reference spec:** `docs/superpowers/specs/2026-06-05-mcp-bridge-serve-loop-design.md`

**Working dir for all commands:** `/Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace/ennam.kg.go` (referred to as `$GO`). Run tests with `go test ./internal/bridge/... -race -count=1`.

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `internal/bridge/config_load.go` | `LoadConfig()` — read `~/.kg/config.yaml` + env overrides → resolved `BridgeConfig` |
| Create | `internal/bridge/config_load_test.go` | loader tests |
| Create | `internal/bridge/uuid.go` | `newUUIDv4()` — RFC-4122 v4 string from `crypto/rand` |
| Create | `internal/bridge/uuid_test.go` | uuid format test |
| Create | `internal/bridge/serve.go` | the ONLY SDK-importing file: build server, register tools, dispatch→`HandleToolCall`, map results, session side-effects, run stdio |
| Create | `internal/bridge/serve_test.go` | dispatch mapping, schema conversion, session side-effects, stdout-discipline |
| Create | `internal/bridge/serve_e2e_test.go` | end-to-end: SDK client ↔ `RunServe` over an in-memory transport |
| Modify | `cmd/kg-bridge/main.go` | add `case "serve"` → `bridge.RunServe(...)` |
| Modify | `go.mod` / `go.sum` | add the SDK dependency |
| (reuse) | `internal/bridge/handler.go`, `schema.go`, `session.go`, `init.go` | unchanged; consumed by serve.go |

---

### Task 1: Config loader

Read `~/.kg/config.yaml` (`api_key`, `server_url`, `default_project_id`) and apply env overrides (`KG_API_KEY`, `KG_SERVER_URL`, `KG_PROJECT_ID` — env wins, BR-006.3). No SDK involved.

**Files:** Create `internal/bridge/config_load.go`, `internal/bridge/config_load_test.go`.

- [ ] **Step 1: Write the failing test**

Create `internal/bridge/config_load_test.go`:

```go
package bridge

import (
	"os"
	"path/filepath"
	"testing"
)

func writeConfig(t *testing.T, dir, body string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, "config.yaml"), []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
}

func TestLoadConfig_FileValues(t *testing.T) {
	dir := t.TempDir()
	writeConfig(t, dir, "api_key: filekey\nserver_url: http://file:8080\ndefault_project_id: proj-file\n")
	cfg, err := LoadConfigFrom(dir, map[string]string{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.APIKey != "filekey" || cfg.ServerURL != "http://file:8080" || cfg.DefaultProjectID != "proj-file" {
		t.Fatalf("got %+v", cfg)
	}
}

func TestLoadConfig_EnvOverrides(t *testing.T) {
	dir := t.TempDir()
	writeConfig(t, dir, "api_key: filekey\nserver_url: http://file:8080\n")
	env := map[string]string{"KG_API_KEY": "envkey", "KG_SERVER_URL": "http://env:9090", "KG_PROJECT_ID": "proj-env"}
	cfg, err := LoadConfigFrom(dir, env)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.APIKey != "envkey" || cfg.ServerURL != "http://env:9090" || cfg.DefaultProjectID != "proj-env" {
		t.Fatalf("env should override file, got %+v", cfg)
	}
}

func TestLoadConfig_MissingRequired(t *testing.T) {
	dir := t.TempDir()
	writeConfig(t, dir, "server_url: http://file:8080\n") // no api_key
	if _, err := LoadConfigFrom(dir, map[string]string{}); err == nil {
		t.Fatal("expected error when api_key is unresolved")
	}
}
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd $GO && go test ./internal/bridge/ -run TestLoadConfig -v`
Expected: FAIL — `LoadConfigFrom` undefined.

- [ ] **Step 3: Implement `config_load.go`**

Create `internal/bridge/config_load.go`:

```go
package bridge

import (
	"fmt"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

// BridgeConfig is the resolved configuration for the serve loop.
type BridgeConfig struct {
	APIKey           string `yaml:"api_key"`
	ServerURL        string `yaml:"server_url"`
	DefaultProjectID string `yaml:"default_project_id"`
}

// LoadConfig reads ~/.kg/config.yaml and applies environment overrides.
func LoadConfig() (BridgeConfig, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return BridgeConfig{}, fmt.Errorf("resolve home dir: %w", err)
	}
	env := map[string]string{
		"KG_API_KEY":    os.Getenv("KG_API_KEY"),
		"KG_SERVER_URL": os.Getenv("KG_SERVER_URL"),
		"KG_PROJECT_ID": os.Getenv("KG_PROJECT_ID"),
	}
	return LoadConfigFrom(filepath.Join(home, configDirName), env)
}

// LoadConfigFrom reads config.yaml from dir and applies env overrides (env wins).
// Missing file is tolerated (env may supply everything); missing api_key/server_url
// after merge is an error.
func LoadConfigFrom(dir string, env map[string]string) (BridgeConfig, error) {
	var cfg BridgeConfig
	data, err := os.ReadFile(filepath.Join(dir, configFileName))
	if err == nil {
		if err := yaml.Unmarshal(data, &cfg); err != nil {
			return BridgeConfig{}, fmt.Errorf("parse config: %w", err)
		}
	} else if !os.IsNotExist(err) {
		return BridgeConfig{}, fmt.Errorf("read config: %w", err)
	}

	if v := env["KG_API_KEY"]; v != "" {
		cfg.APIKey = v
	}
	if v := env["KG_SERVER_URL"]; v != "" {
		cfg.ServerURL = v
	}
	if v := env["KG_PROJECT_ID"]; v != "" {
		cfg.DefaultProjectID = v
	}

	if cfg.APIKey == "" {
		return BridgeConfig{}, fmt.Errorf("api_key not configured (set in %s or KG_API_KEY)", configFileName)
	}
	if cfg.ServerURL == "" {
		return BridgeConfig{}, fmt.Errorf("server_url not configured (set in %s or KG_SERVER_URL)", configFileName)
	}
	return cfg, nil
}
```

(`configDirName` = `.kg` and `configFileName` = `config.yaml` already exist as constants in `init.go`.)

- [ ] **Step 4: Run test — expect PASS**

Run: `cd $GO && go test ./internal/bridge/ -run TestLoadConfig -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd $GO
git add internal/bridge/config_load.go internal/bridge/config_load_test.go
git commit -m "feat(bridge): config loader with env overrides for serve"
```

---

### Task 2: UUIDv4 helper

The create-session API requires a client-supplied `session_id` in UUID format, and the repo has no uuid dependency.

**Files:** Create `internal/bridge/uuid.go`, `internal/bridge/uuid_test.go`.

- [ ] **Step 1: Write the failing test**

Create `internal/bridge/uuid_test.go`:

```go
package bridge

import (
	"regexp"
	"testing"
)

var uuidV4Re = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

func TestNewUUIDv4_Format(t *testing.T) {
	id, err := newUUIDv4()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !uuidV4Re.MatchString(id) {
		t.Fatalf("not a v4 uuid: %q", id)
	}
}

func TestNewUUIDv4_Unique(t *testing.T) {
	a, _ := newUUIDv4()
	b, _ := newUUIDv4()
	if a == b {
		t.Fatal("expected distinct uuids")
	}
}
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd $GO && go test ./internal/bridge/ -run TestNewUUIDv4 -v`
Expected: FAIL — `newUUIDv4` undefined.

- [ ] **Step 3: Implement `uuid.go`**

Create `internal/bridge/uuid.go`:

```go
package bridge

import (
	"crypto/rand"
	"fmt"
)

// newUUIDv4 returns a random RFC-4122 version-4 UUID string.
// The repo has no uuid dependency, so this is built on crypto/rand.
func newUUIDv4() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", fmt.Errorf("read random bytes: %w", err)
	}
	b[6] = (b[6] & 0x0f) | 0x40 // version 4
	b[8] = (b[8] & 0x3f) | 0x80 // variant 10
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16]), nil
}
```

- [ ] **Step 4: Run test — expect PASS**

Run: `cd $GO && go test ./internal/bridge/ -run TestNewUUIDv4 -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd $GO
git add internal/bridge/uuid.go internal/bridge/uuid_test.go
git commit -m "feat(bridge): crypto/rand UUIDv4 helper for session ids"
```

---

### Task 3: Add the SDK + `serve.go` core (tools registration, dispatch, result mapping, run)

Add the official MCP Go SDK, build the server, register all tools from `ListToolSchemas()` with converted input schemas, dispatch each `tools/call` to the existing `HandleToolCall`, and run over stdio. Session side-effects come in Task 4.

**Files:** Modify `go.mod`; create `internal/bridge/serve.go`, `internal/bridge/serve_test.go`; modify `cmd/kg-bridge/main.go`.

- [ ] **Step 1: Pin the SDK and confirm the exact API surface**

```bash
cd $GO
go get github.com/modelcontextprotocol/go-sdk@latest
go doc github.com/modelcontextprotocol/go-sdk/mcp.Server.AddTool
go doc github.com/modelcontextprotocol/go-sdk/mcp.ToolHandler
go doc github.com/modelcontextprotocol/go-sdk/mcp.CallToolRequest
go doc github.com/modelcontextprotocol/go-sdk/mcp.CallToolResult
go doc github.com/modelcontextprotocol/go-sdk/mcp/jsonschema.Schema
```
Expected: confirms `(*Server).AddTool(*Tool, ToolHandler)`; `ToolHandler` shape `func(context.Context, *CallToolRequest) (*CallToolResult, error)`; `CallToolRequest.Params` has `Name string` and `Arguments` (raw JSON / `map[string]any`); `CallToolResult{Content []Content; IsError bool}`; `TextContent{Text string}`. **If the non-generic `ToolHandler` exposes `Arguments` as `json.RawMessage`, unmarshal it into `map[string]interface{}` in the dispatcher; if it is already `map[string]any`, use it directly.** Adjust the code in Step 3 to the confirmed signature.

- [ ] **Step 2: Write the failing tests (schema conversion + result mapping)**

Create `internal/bridge/serve_test.go`:

```go
package bridge

import (
	"testing"
)

func TestToMCPInputSchema_ConvertsProperties(t *testing.T) {
	// kg_query is a real registered tool; its converted schema must be a valid
	// object schema carrying its properties.
	schema := GetToolSchema("kg_query")
	if schema == nil {
		t.Fatal("kg_query schema missing")
	}
	js, err := toMCPInputSchema(schema)
	if err != nil {
		t.Fatalf("convert failed: %v", err)
	}
	if js.Type != "object" {
		t.Fatalf("expected object schema, got %q", js.Type)
	}
	if _, ok := js.Properties["project_id"]; !ok {
		t.Fatal("expected project_id property in converted schema")
	}
}

func TestToCallToolResult_MapsContentAndError(t *testing.T) {
	in := &MCPToolResult{
		Content: []MCPContent{{Type: "text", Text: "hello"}},
		IsError: true,
	}
	out := toCallToolResult(in)
	if !out.IsError {
		t.Fatal("IsError not propagated")
	}
	if len(out.Content) != 1 {
		t.Fatalf("expected 1 content block, got %d", len(out.Content))
	}
	tc, ok := out.Content[0].(*mcpTextContent)
	if !ok || tc.Text != "hello" {
		t.Fatalf("text content not mapped: %#v", out.Content[0])
	}
}
```

> Note: `mcpTextContent` in the assertion is the SDK's `*mcp.TextContent` — in `serve_test.go` import the SDK and assert `*mcp.TextContent` directly. (Written as `mcpTextContent` here only to avoid implying an import in the plan prose; use `*mcp.TextContent` in real code.)

- [ ] **Step 3: Run tests — expect FAIL**

Run: `cd $GO && go test ./internal/bridge/ -run 'TestToMCPInputSchema|TestToCallToolResult' -v`
Expected: FAIL — `toMCPInputSchema` / `toCallToolResult` undefined.

- [ ] **Step 4: Implement `serve.go` core**

Create `internal/bridge/serve.go`:

```go
package bridge

import (
	"context"
	"encoding/json"
	"fmt"
	"os"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/modelcontextprotocol/go-sdk/mcp/jsonschema"
)

// toMCPInputSchema converts our registry ToolSchema into an SDK *jsonschema.Schema
// by round-tripping the existing buildInputSchema() JSON-Schema map through JSON.
func toMCPInputSchema(schema *ToolSchema) (*jsonschema.Schema, error) {
	raw, err := json.Marshal(buildInputSchema(schema)) // existing helper -> map[string]interface{}
	if err != nil {
		return nil, fmt.Errorf("marshal input schema for %s: %w", schema.ToolName, err)
	}
	var js jsonschema.Schema
	if err := json.Unmarshal(raw, &js); err != nil {
		return nil, fmt.Errorf("unmarshal input schema for %s: %w", schema.ToolName, err)
	}
	return &js, nil
}

// toCallToolResult maps our MCPToolResult to the SDK CallToolResult.
func toCallToolResult(r *MCPToolResult) *mcp.CallToolResult {
	content := make([]mcp.Content, 0, len(r.Content))
	for _, c := range r.Content {
		content = append(content, &mcp.TextContent{Text: c.Text})
	}
	return &mcp.CallToolResult{Content: content, IsError: r.IsError}
}

// RunServe loads config, builds the client + handler, registers all tools, and
// serves MCP over stdio until the client disconnects.
func RunServe(_ []string) error {
	cfg, err := LoadConfig()
	if err != nil {
		return err // stderr via main; never stdout
	}
	client, err := NewClient(cfg.ServerURL, cfg.APIKey)
	if err != nil {
		return fmt.Errorf("create client: %w", err)
	}
	handler := NewMCPToolHandler(client)

	server := mcp.NewServer(&mcp.Implementation{Name: "ennam-kg", Version: "v1"}, nil)
	if err := registerTools(server, handler, cfg); err != nil {
		return err
	}
	return server.Run(context.Background(), &mcp.StdioTransport{})
}

// registerTools binds every tool from the schema registry to the SDK server.
func registerTools(server *mcp.Server, handler *MCPToolHandler, cfg BridgeConfig) error {
	for name, schema := range ListToolSchemas() {
		toolName := name // capture
		in, err := toMCPInputSchema(schema)
		if err != nil {
			return err
		}
		server.AddTool(
			&mcp.Tool{Name: toolName, Description: schema.Description, InputSchema: in},
			makeToolHandler(handler, cfg, toolName),
		)
	}
	return nil
}

// makeToolHandler returns the SDK ToolHandler closure for one tool. Task 4 adds
// the session-specific branches; for now every tool forwards to HandleToolCall.
func makeToolHandler(handler *MCPToolHandler, cfg BridgeConfig, toolName string) mcp.ToolHandler {
	return func(ctx context.Context, req *mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		params, err := argsToMap(req)
		if err != nil {
			return &mcp.CallToolResult{
				Content: []mcp.Content{&mcp.TextContent{Text: "invalid arguments: " + err.Error()}},
				IsError: true,
			}, nil
		}
		result, errResp := handler.HandleToolCall(ctx, toolName, params)
		if errResp != nil {
			return nil, fmt.Errorf("%s", errResp.Message) // protocol-level error
		}
		return toCallToolResult(result), nil
	}
}

// argsToMap extracts the raw tool arguments as a map[string]interface{}.
// Adjust to the confirmed CallToolRequest.Params.Arguments type from Step 1:
// if it is already map[string]any, return it directly; if json.RawMessage, unmarshal.
func argsToMap(req *mcp.CallToolRequest) (map[string]interface{}, error) {
	raw := req.Params.Arguments
	switch a := any(raw).(type) {
	case map[string]interface{}:
		return a, nil
	case nil:
		return map[string]interface{}{}, nil
	default:
		b, err := json.Marshal(raw)
		if err != nil {
			return nil, err
		}
		var m map[string]interface{}
		if err := json.Unmarshal(b, &m); err != nil {
			return nil, err
		}
		return m, nil
	}
}

// ensure stderr-only diagnostics in this file
var _ = os.Stderr
```

> `MCPErrorResponse` is a flat struct `{Code int; Message string}` (verified, mcpresponse.go:56-58) — use `errResp.Message` (NOT `errResp.Error.Message`). The `_ = os.Stderr` line is a reminder marker; replace with real stderr logging if any is added (never `fmt.Print` to stdout in this file).

- [ ] **Step 5: Run tests — expect PASS**

Run: `cd $GO && go test ./internal/bridge/ -run 'TestToMCPInputSchema|TestToCallToolResult' -v`
Expected: PASS.

- [ ] **Step 6: Wire `serve` in main.go**

In `cmd/kg-bridge/main.go`, add a case to the `switch cmd` block (after `case "init":`):
```go
	case "serve":
		if err := bridge.RunServe(os.Args[2:]); err != nil {
			fmt.Fprintf(os.Stderr, "error: %v\n", err)
			os.Exit(1)
		}
```

- [ ] **Step 7: Build the whole module**

Run: `cd $GO && go build ./... && go test ./internal/bridge/ -count=1`
Expected: clean build; bridge tests pass.

- [ ] **Step 8: Commit**

```bash
cd $GO
git add go.mod go.sum internal/bridge/serve.go internal/bridge/serve_test.go cmd/kg-bridge/main.go
git commit -m "feat(bridge): MCP stdio serve loop hosting existing tools via official SDK"
```

---

### Task 4: Session side-effects (id generation/injection + `.kg_session` file)

`kg_store_session` must generate+inject a `session_id` (the API requires it) and, on success, write `.kg_session`; `kg_end_session` removes it.

**Files:** Modify `internal/bridge/serve.go`; modify `internal/bridge/serve_test.go`.

- [ ] **Step 1: Write the failing test**

Add to `internal/bridge/serve_test.go`:

```go
import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestStoreSession_InjectsSessionIDAndWritesFile(t *testing.T) {
	tmp := t.TempDir() // dir passed to dispatchStoreSession — no os.Chdir needed

	var seenParams map[string]interface{}
	result := &MCPToolResult{
		Content: []MCPContent{{Type: "text", Text: `{"session":{"id":"ignored","started_at":"2026-06-05T00:00:00Z"}}`}},
		IsError: false,
	}
	out, sessionID, err := dispatchStoreSession(
		context.Background(),
		map[string]interface{}{"project_id": "p1", "agent_name": "tester", "work_scope": "testing"},
		BridgeConfig{ServerURL: "http://kg:8080"},
		tmp,
		func(_ context.Context, params map[string]interface{}) (*MCPToolResult, *MCPErrorResponse) {
			seenParams = params
			return result, nil
		},
	)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if out.IsError {
		t.Fatal("did not expect error result")
	}
	// session_id was generated and injected into the forwarded params
	if seenParams["session_id"] == nil || seenParams["session_id"] != sessionID {
		t.Fatalf("session_id not injected; seen=%v generated=%v", seenParams["session_id"], sessionID)
	}
	// .kg_session written with the generated id + server-provided started_at
	data, err := os.ReadFile(filepath.Join(tmp, DefaultSessionFileName))
	if err != nil {
		t.Fatalf("session file not written: %v", err)
	}
	if !strings.Contains(string(data), sessionID) || !strings.Contains(string(data), "2026-06-05T00:00:00Z") {
		t.Fatalf("session file missing fields: %s", data)
	}
}
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd $GO && go test ./internal/bridge/ -run TestStoreSession -v`
Expected: FAIL — `dispatchStoreSession` undefined.

- [ ] **Step 3: Implement session dispatch in `serve.go`**

Add to `serve.go`:

```go
// forwardFunc abstracts HandleToolCall so the session logic is unit-testable.
type forwardFunc func(ctx context.Context, params map[string]interface{}) (*MCPToolResult, *MCPErrorResponse)

// dispatchStoreSession generates a session_id, injects it, forwards, and on
// success writes the .kg_session file into dir. Returns the result and the id.
// (dir is passed in — production uses "." = the bridge cwd; tests pass a temp dir,
// avoiding fragile process-global os.Chdir.)
func dispatchStoreSession(ctx context.Context, params map[string]interface{}, cfg BridgeConfig, dir string, forward forwardFunc) (*mcp.CallToolResult, string, error) {
	sessionID, err := newUUIDv4()
	if err != nil {
		return nil, "", err
	}
	params["session_id"] = sessionID

	result, errResp := forward(ctx, params)
	if errResp != nil {
		return nil, sessionID, fmt.Errorf("%s", errResp.Message)
	}
	if !result.IsError {
		sf := buildSessionFile(params, result, sessionID, cfg.ServerURL)
		if _, werr := WriteSessionFile(dir, sf); werr != nil {
			fmt.Fprintf(os.Stderr, "warning: failed to write %s: %v\n", DefaultSessionFileName, werr)
		}
	}
	return toCallToolResult(result), sessionID, nil
}

// buildSessionFile assembles the .kg_session contents from generated id (SessionID),
// request params, the create-session response (started_at, nested under "session"),
// and config (server_url). If started_at can't be parsed it is left empty —
// WriteSessionFile defaults an empty StartedAt to time.Now() (session.go:64-65).
func buildSessionFile(params map[string]interface{}, result *MCPToolResult, sessionID, serverURL string) SessionFile {
	startedAt := ""
	if len(result.Content) > 0 {
		var body map[string]any
		if err := json.Unmarshal([]byte(result.Content[0].Text), &body); err == nil {
			if sess, ok := body["session"].(map[string]any); ok {
				if s, ok := sess["started_at"].(string); ok {
					startedAt = s
				}
			}
		}
	}
	return SessionFile{
		SessionID:       sessionID,
		ProjectID:       strParam(params, "project_id"),
		Agent:           strParam(params, "agent_name"),
		StartedAt:       startedAt,
		Scope:           strParam(params, "work_scope"),
		TaskDescription: strParam(params, "task_description"),
		ServerURL:       serverURL,
	}
}

func strParam(m map[string]interface{}, k string) string {
	if v, ok := m[k].(string); ok {
		return v
	}
	return ""
}
```

Then wire these into `makeToolHandler` — replace its body with:

```go
func makeToolHandler(handler *MCPToolHandler, cfg BridgeConfig, toolName string) mcp.ToolHandler {
	forward := func(ctx context.Context, params map[string]interface{}) (*MCPToolResult, *MCPErrorResponse) {
		return handler.HandleToolCall(ctx, toolName, params)
	}
	return func(ctx context.Context, req *mcp.CallToolRequest) (*mcp.CallToolResult, error) {
		params, err := argsToMap(req)
		if err != nil {
			return &mcp.CallToolResult{
				Content: []mcp.Content{&mcp.TextContent{Text: "invalid arguments: " + err.Error()}},
				IsError: true,
			}, nil
		}
		switch toolName {
		case "kg_store_session":
			out, _, derr := dispatchStoreSession(ctx, params, cfg, ".", forward)
			return out, derr
		case "kg_end_session":
			result, errResp := forward(ctx, params)
			if errResp != nil {
				return nil, fmt.Errorf("%s", errResp.Message)
			}
			if !result.IsError {
				if rerr := RemoveSessionFile("."); rerr != nil {
					fmt.Fprintf(os.Stderr, "warning: failed to remove %s: %v\n", DefaultSessionFileName, rerr)
				}
			}
			return toCallToolResult(result), nil
		default:
			result, errResp := forward(ctx, params)
			if errResp != nil {
				return nil, fmt.Errorf("%s", errResp.Message)
			}
			return toCallToolResult(result), nil
		}
	}
}
```

> `WriteSessionFile(".", sf)` uses `"."` (the process cwd, inherited from the MCP host = project dir). `DefaultSessionFileName` and `SessionFile`/`WriteSessionFile`/`RemoveSessionFile` are existing exports in `session.go`.

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd $GO && go test ./internal/bridge/ -run TestStoreSession -v`
Expected: PASS.

- [ ] **Step 5: Full bridge suite + build**

Run: `cd $GO && go build ./... && go test ./internal/bridge/ -race -count=1`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cd $GO
git add internal/bridge/serve.go internal/bridge/serve_test.go
git commit -m "feat(bridge): session_id generation/injection + .kg_session side-effects in serve"
```

---

### Task 5: End-to-end protocol smoke + stdout discipline

Prove the real protocol path: an in-process SDK client connects to `RunServe`, lists tools, and the server emits nothing on stdout outside the protocol.

**Files:** Create `internal/bridge/serve_e2e_test.go`.

- [ ] **Step 1: Write the E2E test**

Create `internal/bridge/serve_e2e_test.go`:

```go
package bridge

import (
	"context"
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// TestServe_ListTools_E2E connects an in-memory SDK client to a server built the
// same way RunServe builds it, and asserts initialize + tools/list work and all
// registered tools are advertised.
func TestServe_ListTools_E2E(t *testing.T) {
	ctx := context.Background()

	// Build the server exactly like RunServe (minus real config/client): use a
	// nil-safe handler with a stub client pointed at an unused URL — tools/list
	// does not call the API.
	client, err := NewClient("http://unused:8080", "k")
	if err != nil {
		t.Fatal(err)
	}
	handler := NewMCPToolHandler(client)
	server := mcp.NewServer(&mcp.Implementation{Name: "ennam-kg", Version: "v1"}, nil)
	if err := registerTools(server, handler, BridgeConfig{ServerURL: "http://unused:8080"}); err != nil {
		t.Fatalf("registerTools: %v", err)
	}

	// In-memory transport pair.
	clientTransport, serverTransport := mcp.NewInMemoryTransports()
	go func() { _ = server.Run(ctx, serverTransport) }()

	c := mcp.NewClient(&mcp.Implementation{Name: "test-client", Version: "v1"}, nil)
	session, err := c.Connect(ctx, clientTransport, nil)
	if err != nil {
		t.Fatalf("connect (initialize handshake) failed: %v", err)
	}
	defer session.Close()

	res, err := session.ListTools(ctx, nil)
	if err != nil {
		t.Fatalf("tools/list failed: %v", err)
	}
	got := map[string]bool{}
	for _, tool := range res.Tools {
		got[tool.Name] = true
	}
	for _, want := range []string{"kg_query", "kg_store_decision", "kg_store_session", "kg_end_session"} {
		if !got[want] {
			t.Fatalf("tool %q missing from tools/list", want)
		}
	}
	if len(res.Tools) != len(ListToolSchemas()) {
		t.Fatalf("advertised %d tools, registry has %d", len(res.Tools), len(ListToolSchemas()))
	}
}
```

> Confirm the in-memory transport constructor name from Step-1 godoc (`mcp.NewInMemoryTransports` in v1.x). If the SDK names it differently, adjust; the intent is an in-process client↔server pair so no real subprocess/stdout is needed. stdout discipline is then guaranteed structurally: the only stdout writer is the SDK transport, and `serve.go` writes diagnostics only to `os.Stderr` (grep-asserted in Step 3).

- [ ] **Step 2: Run the E2E test — expect PASS**

Run: `cd $GO && go test ./internal/bridge/ -run TestServe_ListTools_E2E -v`
Expected: PASS — handshake + tools/list return all registered tools.

- [ ] **Step 3: Assert stdout discipline in serve.go**

Run: `cd $GO && grep -n "fmt.Print\|os.Stdout\|println(" internal/bridge/serve.go`
Expected: no matches (all diagnostics go to `os.Stderr`). If any match exists, change it to `fmt.Fprintf(os.Stderr, ...)`.

- [ ] **Step 4: Commit**

```bash
cd $GO
git add internal/bridge/serve_e2e_test.go
git commit -m "test(bridge): E2E initialize + tools/list over in-memory transport"
```

---

### Task 6: Manual verification against a live host

**Files:** none (verification only).

- [ ] **Step 1: Build the binary**

```bash
cd $GO && make build
ls bin/kg-bridge   # exists
```

- [ ] **Step 2: Generate config + run serve manually**

```bash
cd $GO
./bin/kg-bridge init --api-key ennam_kg_dev_000000000000000000000000 --server http://localhost:8080 --force
# Start the Go API (docker compose up -d kg-server postgres redis) in the workspace first.
# Then a raw initialize handshake over stdio (the server should respond with capabilities incl. tools):
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"manual","version":"1"}}}' | ./bin/kg-bridge serve
```
Expected: a single JSON-RPC response line on stdout advertising server capabilities (tools). No extra/log lines on stdout.

- [ ] **Step 3: Configure a real MCP host (manual, documented)**

Point Claude Code (and, if available, one non-Claude MCP host) at `kg-bridge serve` as an MCP server. Confirm the 24 tools appear and a `kg_query` call returns data from the live Go API; a `kg_store_session` call creates a session AND writes `.kg_session` in the cwd.

- [ ] **Step 4: Update BA-002 note**

Append to the bottom of `ennam.kg.requirements/documents/phase1/BA-002-mcp-bridge.md`:

```markdown
---

## Implementation note (2026-06-05): tool categories in the serve loop

The `kg-bridge serve` loop (added 2026-06) hosts tools in three categories:
- **HTTP-proxy tools** (most): forwarded verbatim to the REST API (pure translator).
- **Session tools** (`kg_store_session`, `kg_end_session`): proxy + bridge-side side effects — the bridge generates and injects the required `session_id` (the API does not generate it) and writes/removes the `.kg_session` file.
- **Local-execution tools** (`kg_index_source`, `kg_index_status`, separate spec): run a local subprocess instead of forwarding HTTP.

Do not assume every tool is a pure HTTP forward.
```

- [ ] **Step 5: Commit the doc note**

```bash
cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace
git add ennam.kg.requirements/documents/phase1/BA-002-mcp-bridge.md
git commit -m "docs(BA-002): note serve-loop tool categories"
```

---

## Self-Review

### Spec coverage

| Spec section | Task |
|--------------|------|
| Scope: `kg-bridge serve` hosting 24 tools | Task 3 |
| Config loader (file + env override) | Task 1 |
| SDK decision + maturity gate + isolation in serve.go | Task 3 (gate = Step 1; isolation = serve.go is the only SDK importer) |
| `initialize` + `tools/list` + `tools/call` | Task 3 (registration/dispatch) + Task 5 (E2E proves initialize+list) |
| Session side-effects + `session_id` generation/injection | Task 4 |
| `buildSessionFile` field sources (gen id, nested response, params, config) | Task 4 |
| UUIDv4 helper (no uuid dep) | Task 2 |
| Error model (tool-level vs protocol-level) | Task 3 (`toCallToolResult` for tool-level; returned `error` for protocol-level) |
| stdout discipline | Task 5 Step 3 (grep assert) + serve.go writes only to stderr |
| Testing (loader, mapping, session, E2E) | Tasks 1–5 |
| BA-002 note | Task 6 Step 4 |

### Placeholder scan

Concrete code throughout. Two explicit "confirm from godoc and adjust" points (Task 3 Step 1: exact `ToolHandler`/`Arguments` shape; `MCPErrorResponse.Error.Message` path; Task 5: in-memory transport constructor name) — these are unavoidable for an external SDK and are written as verification steps with exact commands, not vague TODOs.

### Type consistency

- `LoadConfigFrom(dir, env)` / `BridgeConfig{APIKey,ServerURL,DefaultProjectID}` — Task 1, used in Task 3 `RunServe` and Task 4 `cfg.ServerURL`.
- `newUUIDv4() (string, error)` — Task 2, used in Task 4 `dispatchStoreSession`.
- `toMCPInputSchema`/`toCallToolResult`/`registerTools`/`makeToolHandler`/`argsToMap` — Task 3, extended in Task 4.
- `dispatchStoreSession`/`buildSessionFile`/`strParam`/`forwardFunc` — Task 4.
- Reused existing exports: `ListToolSchemas`, `GetToolSchema`, `buildInputSchema`, `NewClient`, `NewMCPToolHandler`, `HandleToolCall`, `MCPToolResult`/`MCPContent`, `MCPErrorResponse`, `SessionFile`, `WriteSessionFile`, `RemoveSessionFile`, `DefaultSessionFileName`, `configDirName`/`configFileName`.

### Ordering note

Tasks 1–2 are standalone (no SDK), each green. Task 3 adds the SDK + serve core (green: tools host + forward). Task 4 layers session side-effects (green). Task 5 proves the protocol E2E. Task 6 is manual + the BA-002 doc note. Each task ends green and is committed independently.
