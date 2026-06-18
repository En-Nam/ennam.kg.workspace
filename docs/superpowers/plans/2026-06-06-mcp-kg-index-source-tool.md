# MCP `kg_index_source` Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two MCP tools — `kg_index_source` (start a local index, returns a job_id immediately) and `kg_index_status` (poll progress) — so any MCP host (including non-shell agents) can trigger code indexing by having the bridge spawn the locally-installed `ennam-kg-index` CLI as a subprocess and inject KG credentials.

**Architecture:** These are the bridge's first **local-execution** tools — unlike the 30 existing HTTP-proxy tools (which forward to the Go API via `HandleToolCall` → `GetToolRoute`), they run a subprocess on the agent's machine. All local logic lives in a new isolated file `internal/bridge/local_index.go` (`LocalIndexHandler`: CLI lookup, env injection, in-memory job map, async goroutine). Dispatch is intercepted in the serve loop's `makeToolHandler` switch **before** the HTTP-forward path, so the existing 30 tools are untouched. Indexing runs async (start returns at once, agent polls) to avoid MCP host tool-call timeouts.

**Tech Stack:** Go (stdlib `os/exec`, `crypto/rand`, `sync`, `context`), official `modelcontextprotocol/go-sdk` (already wired by the serve loop), `gopkg.in/yaml.v3`. Tests use stdlib `testing` + a fake CLI shell stub (no real Python needed).

**Reference spec:** `docs/superpowers/specs/2026-06-05-mcp-index-source-tool-design.md`

**Working dir for all commands:** `/Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace/ennam.kg.go` (referred to as `$GO`). Run Go tests from `$GO`.

> **Spec deltas already reconciled in this plan (spec predates the serve loop):**
> - Spec assumes dispatch is a new branch in `HandleToolCall`. **Actual:** the serve loop (`serve.go`) dispatches per-tool in `makeToolHandler`'s `switch toolName`. `HandleToolCall` rejects any tool without an HTTP route (`GetToolRoute`), so local tools MUST be intercepted in `makeToolHandler` before `forward`. This plan targets `makeToolHandler`.
> - Spec says "24 existing tools" / config struct in `init.go`. **Actual:** there are **30** HTTP-proxy tools, and the serve-loop config is `BridgeConfig` in `config_load.go` (fields `APIKey`, `ServerURL`, `DefaultProjectID`). The new `indexer_cli_path` field is added to `BridgeConfig`.
> - `project_id` fallback uses `BridgeConfig.DefaultProjectID` (already parsed from `default_project_id` / `KG_PROJECT_ID`).

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `$GO/internal/bridge/config_load.go` | add `IndexerCLIPath` field (`indexer_cli_path`) to `BridgeConfig` |
| Modify | `$GO/internal/bridge/config_load_test.go` | assert `indexer_cli_path` parses from yaml |
| Modify | `$GO/internal/bridge/schema.go` | register `kg_index_source` + `kg_index_status` schemas in `buildToolSchemas()` |
| Modify | `$GO/internal/bridge/schema_test.go` | assert both tools registered + validation rules |
| Create | `$GO/internal/bridge/local_index.go` | `LocalIndexHandler`: CLI resolve, job map, async subprocess, env injection, `StartIndex`/`IndexStatus` |
| Create | `$GO/internal/bridge/local_index_test.go` | TDD with fake CLI stub: happy path, env/flags, failure, cli-not-found, path-missing, project_id fallback, unknown job |
| Modify | `$GO/internal/bridge/serve.go` | `registerTools` builds one shared `LocalIndexHandler`; `makeToolHandler` gains `lih` param + two dispatch cases |
| Create | `$GO/internal/bridge/serve_local_index_test.go` | dispatch test: `kg_index_source` routes to handler (fake CLI); a proxy tool still forwards (no regression) |
| Modify | `$WORKSPACE/ennam.kg.requirements/documents/phase1/BA-002-mcp-bridge.md` | note the two tool categories + the two local tools |
| Modify | `$GO/README.md` (or bridge section) | document `indexer_cli_path`, the two tools, and the three common errors |

`$WORKSPACE` = `/Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace`. The requirements repo is a **separate git repo** — commit BA-002 changes there, not in `$GO`.

The 30 HTTP-proxy tools, `HandleToolCall`, `GetToolRoute`, and `toolRoutes` are **not touched**.

---

### Task 1: Config — `indexer_cli_path` field

Add the optional CLI-path override to the serve-loop config so non-standard installs (venv, Docker) can point the bridge at the CLI.

**Files:**
- Modify: `$GO/internal/bridge/config_load.go`
- Modify: `$GO/internal/bridge/config_load_test.go`

- [ ] **Step 1: Write the failing test**

Add to `$GO/internal/bridge/config_load_test.go`:

```go
func TestLoadConfigFrom_ParsesIndexerCLIPath(t *testing.T) {
	dir := t.TempDir()
	yaml := "api_key: k\nserver_url: http://localhost:8080\nindexer_cli_path: /opt/venv/bin/ennam-kg-index\n"
	if err := os.WriteFile(filepath.Join(dir, configFileName), []byte(yaml), 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}
	cfg, err := LoadConfigFrom(dir, map[string]string{})
	if err != nil {
		t.Fatalf("LoadConfigFrom: %v", err)
	}
	if cfg.IndexerCLIPath != "/opt/venv/bin/ennam-kg-index" {
		t.Errorf("IndexerCLIPath = %q, want /opt/venv/bin/ennam-kg-index", cfg.IndexerCLIPath)
	}
}
```

> If `config_load_test.go` does not already import `os`, `path/filepath`, and `testing`, add them. They are almost certainly already imported by the existing tests in that file.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $GO && go test ./internal/bridge/ -run TestLoadConfigFrom_ParsesIndexerCLIPath -count=1`
Expected: FAIL — `cfg.IndexerCLIPath undefined (type BridgeConfig has no field IndexerCLIPath)`.

- [ ] **Step 3: Add the field**

In `$GO/internal/bridge/config_load.go`, add the field to `BridgeConfig`:

```go
// BridgeConfig is the resolved configuration for the serve loop.
type BridgeConfig struct {
	APIKey           string `yaml:"api_key"`
	ServerURL        string `yaml:"server_url"`
	DefaultProjectID string `yaml:"default_project_id"`
	IndexerCLIPath   string `yaml:"indexer_cli_path"`
}
```

(No env override is needed for this field — it is a machine-local install detail set in `config.yaml`. The existing `LoadConfigFrom` already unmarshals the whole file into `cfg`, so the new field is parsed automatically; no other change required.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $GO && go test ./internal/bridge/ -run TestLoadConfigFrom_ParsesIndexerCLIPath -count=1`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd $GO
git add internal/bridge/config_load.go internal/bridge/config_load_test.go
git commit -m "feat(bridge): add indexer_cli_path to serve-loop config"
```

---

### Task 2: Register the two tool schemas

Add `kg_index_source` and `kg_index_status` to the schema registry so they appear in `tools/list` and get bridge-side param validation. They are NOT added to `toolRoutes` (no HTTP route) — dispatch is handled in Task 4.

**Files:**
- Modify: `$GO/internal/bridge/schema.go`
- Modify: `$GO/internal/bridge/schema_test.go`

- [ ] **Step 1: Write the failing test**

Add to `$GO/internal/bridge/schema_test.go`:

```go
func TestBuildToolSchemas_RegistersLocalIndexTools(t *testing.T) {
	schemas := ListToolSchemas()

	src := schemas["kg_index_source"]
	if src == nil {
		t.Fatal("kg_index_source not registered")
	}
	if !src.Properties["path"].Required {
		t.Error("kg_index_source.path must be required")
	}
	if src.Properties["project_id"].Required {
		t.Error("kg_index_source.project_id must be optional (falls back to default)")
	}
	if src.Properties["repo_key"].Required {
		t.Error("kg_index_source.repo_key must be optional")
	}

	st := schemas["kg_index_status"]
	if st == nil {
		t.Fatal("kg_index_status not registered")
	}
	if !st.Properties["job_id"].Required {
		t.Error("kg_index_status.job_id must be required")
	}

	// Validation must reject a kg_index_source call missing the required path.
	vr := ValidateToolParams("kg_index_source", map[string]interface{}{})
	if vr.Valid {
		t.Error("expected validation failure when path is missing")
	}
	// And accept a well-formed minimal call.
	vr = ValidateToolParams("kg_index_source", map[string]interface{}{"path": "/some/dir"})
	if !vr.Valid {
		t.Errorf("expected valid call, got errors: %s", vr.Error())
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $GO && go test ./internal/bridge/ -run TestBuildToolSchemas_RegistersLocalIndexTools -count=1`
Expected: FAIL — `kg_index_source not registered` (nil map entry).

- [ ] **Step 3: Register the schemas**

In `$GO/internal/bridge/schema.go`, inside `buildToolSchemas()`, immediately **before** the final `return schemas` line, add:

```go
	// === Local-execution tools (NOT HTTP-proxy) ===
	// These do not map to a REST route; the serve loop dispatches them to
	// LocalIndexHandler, which spawns the ennam-kg-index CLI as a subprocess.
	// They are registered here so they appear in tools/list and get param validation.
	schemas["kg_index_source"] = &ToolSchema{
		ToolName: "kg_index_source",
		Description: "Index a local source directory into the knowledge graph by running the " +
			"ennam-kg-index CLI on this machine. Returns a job_id immediately; poll kg_index_status to get the result.",
		Properties: map[string]ParamSchema{
			"path": {
				Type:        TypeString,
				Required:    true,
				Description: "Local source directory on this machine to index",
				MinLength:   intPtr(1),
			},
			"project_id": {
				Type:        TypeString,
				Required:    false,
				Description: "KG project id (falls back to the bridge default project if omitted)",
				MinLength:   intPtr(1),
				// No uuid Pattern here on purpose: project_id is a passthrough CLI
				// arg validated by the server/CLI pre-flight, and the DefaultProjectID
				// fallback is not re-validated — enforcing a bridge-side uuid pattern
				// would be inconsistent and would reject the test/fixture ids.
			},
			"repo_key": {
				Type:        TypeString,
				Required:    false,
				Description: "Stable repo identity stored in KG (default: the path). Use a logical id like github.com/org/repo for re-index stability.",
				MinLength:   intPtr(1),
			},
		},
	}
	schemas["kg_index_status"] = &ToolSchema{
		ToolName:    "kg_index_status",
		Description: "Poll the status of an index job started by kg_index_source.",
		Properties: map[string]ParamSchema{
			"job_id": {
				Type:        TypeString,
				Required:    true,
				Description: "Job id returned by kg_index_source",
				MinLength:   intPtr(1),
			},
		},
	}

```

Also update the capacity hint and comment at the top of `buildToolSchemas()` (cosmetic, keeps the count honest):

Change:
```go
	schemas := make(map[string]*ToolSchema, 25)
```
to:
```go
	schemas := make(map[string]*ToolSchema, 32)
```

Then, still in `schema.go`, add a package-level set naming the local-execution tools. It is the canonical "these tools have NO HTTP route" list, reused by the cross-check test fixes in Step 5 (and available for dispatch). Place it right after the `toolSchemas` var declaration (near the existing `func init()`):

```go
// localToolNames are the tools dispatched to LocalIndexHandler instead of being
// forwarded to an HTTP route. They intentionally have NO entry in toolRoutes,
// so route/schema cross-checks must exclude them.
var localToolNames = map[string]bool{
	"kg_index_source": true,
	"kg_index_status": true,
}
```

- [ ] **Step 4: Run the registration test to verify it passes**

Run: `cd $GO && go test ./internal/bridge/ -run TestBuildToolSchemas_RegistersLocalIndexTools -count=1`
Expected: PASS.

- [ ] **Step 5: Update the four existing cross-check tests that the new no-route schemas break**

Adding two schemas without routes breaks four registry-vs-route assertions. Apply these **exact** edits (each was verified against the current source):

(a) `schema_test.go` — the schema-count assertion (currently `!= 30`). Change:
```go
	schemas := ListToolSchemas()
	if len(schemas) != 30 {
		t.Errorf("expected 30 tool schemas, got %d", len(schemas))
	}
```
to:
```go
	schemas := ListToolSchemas()
	if len(schemas) != 32 {
		t.Errorf("expected 32 tool schemas, got %d", len(schemas))
	}
```

(b) `schema_test.go` — `TestAllToolSchemasMatchRoutes`. The schema→route direction must skip local tools (they have no route by design). Change:
```go
	for name := range toolSchemas {
		if _, ok := toolRoutes[name]; !ok {
			t.Errorf("tool schema %q has no matching route", name)
		}
	}
```
to:
```go
	for name := range toolSchemas {
		if localToolNames[name] {
			continue // local-execution tools intentionally have no HTTP route
		}
		if _, ok := toolRoutes[name]; !ok {
			t.Errorf("tool schema %q has no matching route", name)
		}
	}
```

(c) `e2e_tools_test.go` — `TestE2E_SchemaValidationAllTools` count assertion. `toolNames` comes from `ListToolNames()` (routes, 30); `schemas` is the full registry (32). Change:
```go
	// Verify schema count matches route count.
	if len(schemas) != len(toolNames) {
		t.Errorf("schema count (%d) != route count (%d)", len(schemas), len(toolNames))
	}
```
to:
```go
	// Verify schema count matches route count plus the local-execution tools
	// (kg_index_source, kg_index_status), which have schemas but no routes.
	if len(schemas) != len(toolNames)+len(localToolNames) {
		t.Errorf("schema count (%d) != route count (%d) + local tools (%d)", len(schemas), len(toolNames), len(localToolNames))
	}
```

(d) `handler_test.go` — `TestMCPToolHandler_ListTools` count (`ListTools()` builds from schemas, so 32). Change:
```go
	if len(tools) != 30 {
		t.Errorf("expected 30 tools, got %d", len(tools))
	}
```
to:
```go
	if len(tools) != 32 {
		t.Errorf("expected 32 tools, got %d", len(tools))
	}
```

> Do **not** touch `integration_test.go` (`TestIntegration_AllToolsRegistered`): it counts `ListToolNames()` (routes, still 30) against a hardcoded 30-tool list — both unchanged, so it stays green. Likewise `serve_e2e_test.go` (`32 == 32`) and `TestValidateRequiredFields_AllToolsEmptyParams` (hardcoded map) need no change.

- [ ] **Step 6: Run the full bridge suite to verify zero regressions**

Run: `cd $GO && go test ./internal/bridge/ -count=1`
Expected: PASS — all tests, including the four edited cross-checks and the existing serve E2E tests.

- [ ] **Step 7: Commit**

```bash
cd $GO
git add internal/bridge/schema.go internal/bridge/schema_test.go internal/bridge/e2e_tools_test.go internal/bridge/handler_test.go
git commit -m "feat(bridge): register kg_index_source + kg_index_status schemas (no route)"
```

---

### Task 3: `LocalIndexHandler` — subprocess + job map (the core)

All local-execution logic in one new file. Async: `StartIndex` validates, spawns the CLI in a goroutine, and returns a `job_id` immediately; `IndexStatus` reads the in-memory job map. Credentials are injected into the subprocess env so the agent never handles the API key.

**Files:**
- Create: `$GO/internal/bridge/local_index.go`
- Create: `$GO/internal/bridge/local_index_test.go`

- [ ] **Step 1: Write the failing tests (fake CLI stub)**

Create `$GO/internal/bridge/local_index_test.go`:

```go
package bridge

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

// writeStub writes an executable shell stub to a temp dir and returns its path.
// Tests are Unix-only (the dev/CI environment is macOS/Linux); skip on Windows.
func writeStub(t *testing.T, body string) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("fake-CLI stub tests are Unix-only")
	}
	dir := t.TempDir()
	p := filepath.Join(dir, "ennam-kg-index")
	if err := os.WriteFile(p, []byte("#!/bin/sh\n"+body), 0o755); err != nil {
		t.Fatalf("write stub: %v", err)
	}
	return p
}

// waitStatus polls IndexStatus until the job reaches want (or fails the test).
func waitStatus(t *testing.T, h *LocalIndexHandler, jobID, want string) map[string]any {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		res := h.IndexStatus(map[string]interface{}{"job_id": jobID})
		var body map[string]any
		if err := json.Unmarshal([]byte(res.Content[0].Text), &body); err == nil {
			if body["status"] == want {
				return body
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("job %s did not reach status %q in time", jobID, want)
	return nil
}

func startJobID(t *testing.T, res *MCPToolResult) string {
	t.Helper()
	if res.IsError {
		t.Fatalf("StartIndex returned error: %s", res.Content[0].Text)
	}
	var body map[string]any
	if err := json.Unmarshal([]byte(res.Content[0].Text), &body); err != nil {
		t.Fatalf("parse start result: %v (%s)", err, res.Content[0].Text)
	}
	id, _ := body["job_id"].(string)
	if id == "" || body["status"] != "running" {
		t.Fatalf("unexpected start result: %s", res.Content[0].Text)
	}
	return id
}

func TestStartIndex_HappyPath(t *testing.T) {
	cli := writeStub(t, `echo '{"mode":"full","files_scanned":1,"symbols_found":2,"nodes_created":2,"nodes_updated":0,"nodes_archived":0,"edges_created":1,"errors":[]}'`)
	h := NewLocalIndexHandler(BridgeConfig{ServerURL: "http://u", APIKey: "k", IndexerCLIPath: cli})
	res := h.StartIndex(map[string]interface{}{"path": t.TempDir(), "project_id": "p", "repo_key": "rk"})
	jobID := startJobID(t, res)

	body := waitStatus(t, h, jobID, "done")
	summary, ok := body["summary"].(map[string]any)
	if !ok {
		t.Fatalf("expected summary object, got: %v", body["summary"])
	}
	if summary["nodes_created"].(float64) != 2 {
		t.Errorf("nodes_created = %v, want 2", summary["nodes_created"])
	}
}

func TestStartIndex_InjectsEnvAndFlags(t *testing.T) {
	cap := filepath.Join(t.TempDir(), "capture.txt")
	t.Setenv("CAPTURE_FILE", cap)
	// Stub appends its argv + KG_ env vars to CAPTURE_FILE, then prints a summary.
	cli := writeStub(t, `printf 'ARGS:%s\n' "$*" >> "$CAPTURE_FILE"
env | grep '^KG_' >> "$CAPTURE_FILE"
echo '{"nodes_created":0,"errors":[]}'`)
	h := NewLocalIndexHandler(BridgeConfig{ServerURL: "http://kg:8080", APIKey: "secret-key", IndexerCLIPath: cli})

	src := t.TempDir()
	res := h.StartIndex(map[string]interface{}{"path": src, "project_id": "proj-9", "repo_key": "github.com/org/r"})
	jobID := startJobID(t, res)
	waitStatus(t, h, jobID, "done")

	data, err := os.ReadFile(cap)
	if err != nil {
		t.Fatalf("read capture: %v", err)
	}
	out := string(data)
	for _, want := range []string{
		"--path", src,
		"--project-id", "proj-9",
		"--repo-key", "github.com/org/r",
		"--mode", "full",
		"KG_API_URL=http://kg:8080",
		"KG_API_KEY=secret-key",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("subprocess invocation missing %q\ngot:\n%s", want, out)
		}
	}
}

func TestStartIndex_SubprocessFailureBecomesErrorStatus(t *testing.T) {
	cli := writeStub(t, `echo 'boom: cannot reach KG API' >&2
exit 1`)
	h := NewLocalIndexHandler(BridgeConfig{ServerURL: "http://u", APIKey: "k", IndexerCLIPath: cli})
	res := h.StartIndex(map[string]interface{}{"path": t.TempDir(), "project_id": "p"})
	jobID := startJobID(t, res)

	body := waitStatus(t, h, jobID, "error")
	if msg, _ := body["error"].(string); !strings.Contains(msg, "boom") {
		t.Errorf("error status should carry stderr tail, got: %v", body["error"])
	}
}

func TestStartIndex_UnparseableOutputBecomesError(t *testing.T) {
	cli := writeStub(t, `echo 'not json at all'`)
	h := NewLocalIndexHandler(BridgeConfig{ServerURL: "http://u", APIKey: "k", IndexerCLIPath: cli})
	res := h.StartIndex(map[string]interface{}{"path": t.TempDir(), "project_id": "p"})
	jobID := startJobID(t, res)

	body := waitStatus(t, h, jobID, "error")
	if msg, _ := body["error"].(string); !strings.Contains(msg, "could not parse") {
		t.Errorf("expected parse error, got: %v", body["error"])
	}
}

func TestStartIndex_CLINotFound(t *testing.T) {
	// Empty IndexerCLIPath + a PATH that does not contain ennam-kg-index.
	t.Setenv("PATH", t.TempDir())
	h := NewLocalIndexHandler(BridgeConfig{ServerURL: "http://u", APIKey: "k"})
	res := h.StartIndex(map[string]interface{}{"path": t.TempDir(), "project_id": "p"})
	if !res.IsError {
		t.Fatal("expected isError when CLI not found")
	}
	if !strings.Contains(res.Content[0].Text, "ennam-kg-index not found") {
		t.Errorf("expected install guidance, got: %s", res.Content[0].Text)
	}
}

func TestStartIndex_PathMissing(t *testing.T) {
	cli := writeStub(t, `echo '{}'`)
	h := NewLocalIndexHandler(BridgeConfig{ServerURL: "http://u", APIKey: "k", IndexerCLIPath: cli})
	res := h.StartIndex(map[string]interface{}{"path": "/no/such/dir/xyz", "project_id": "p"})
	if !res.IsError {
		t.Fatal("expected isError when path does not exist")
	}
}

func TestStartIndex_ProjectIDFallback(t *testing.T) {
	cli := writeStub(t, `printf '%s' "$*" > "$CAPTURE_FILE"
echo '{"nodes_created":0,"errors":[]}'`)
	cap := filepath.Join(t.TempDir(), "cap.txt")
	t.Setenv("CAPTURE_FILE", cap)
	h := NewLocalIndexHandler(BridgeConfig{ServerURL: "http://u", APIKey: "k", DefaultProjectID: "default-proj", IndexerCLIPath: cli})
	res := h.StartIndex(map[string]interface{}{"path": t.TempDir()}) // no project_id
	jobID := startJobID(t, res)
	waitStatus(t, h, jobID, "done")

	data, _ := os.ReadFile(cap)
	if !strings.Contains(string(data), "default-proj") {
		t.Errorf("expected fallback to default project, argv: %s", string(data))
	}
}

func TestStartIndex_NoProjectIDAndNoDefault(t *testing.T) {
	cli := writeStub(t, `echo '{}'`)
	h := NewLocalIndexHandler(BridgeConfig{ServerURL: "http://u", APIKey: "k", IndexerCLIPath: cli})
	res := h.StartIndex(map[string]interface{}{"path": t.TempDir()})
	if !res.IsError {
		t.Fatal("expected isError when neither project_id nor default is set")
	}
	if !strings.Contains(res.Content[0].Text, "project_id") {
		t.Errorf("expected project_id guidance, got: %s", res.Content[0].Text)
	}
}

func TestIndexStatus_UnknownJobID(t *testing.T) {
	h := NewLocalIndexHandler(BridgeConfig{ServerURL: "http://u", APIKey: "k"})
	res := h.IndexStatus(map[string]interface{}{"job_id": "idx-deadbeef"})
	if !res.IsError {
		t.Fatal("expected isError for unknown job_id")
	}
	if !strings.Contains(res.Content[0].Text, "unknown job_id") {
		t.Errorf("got: %s", res.Content[0].Text)
	}
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $GO && go test ./internal/bridge/ -run 'TestStartIndex|TestIndexStatus' -count=1`
Expected: FAIL — `undefined: NewLocalIndexHandler` / `LocalIndexHandler`.

- [ ] **Step 3: Implement `local_index.go`**

Create `$GO/internal/bridge/local_index.go`:

```go
package bridge

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"
)

// defaultIndexTimeout bounds a single index subprocess so a hung CLI cannot
// live forever. It is generous; indexing is async so it never blocks the agent.
const defaultIndexTimeout = 30 * time.Minute

// indexJob is the in-memory state of one index run.
type indexJob struct {
	status  string         // "running" | "done" | "error"
	summary map[string]any // set when status == "done"
	errMsg  string         // set when status == "error"
}

// LocalIndexHandler runs the ennam-kg-index CLI as a subprocess on the agent's
// machine and tracks job state in memory. It is created once per serve session
// so the job map persists across tool calls within that session.
type LocalIndexHandler struct {
	cfg     BridgeConfig
	timeout time.Duration

	mu   sync.Mutex
	jobs map[string]*indexJob
}

// NewLocalIndexHandler constructs a handler bound to the bridge config (which
// carries the API URL + key injected into the subprocess, and the optional
// indexer_cli_path / default_project_id).
func NewLocalIndexHandler(cfg BridgeConfig) *LocalIndexHandler {
	return &LocalIndexHandler{
		cfg:     cfg,
		timeout: defaultIndexTimeout,
		jobs:    make(map[string]*indexJob),
	}
}

// newJobID returns "idx-" + 16 hex chars from 8 crypto/rand bytes.
// crypto/rand is the repo's established ID pattern (no uuid dependency).
func newJobID() (string, error) {
	var b [8]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", fmt.Errorf("read random bytes: %w", err)
	}
	return "idx-" + hex.EncodeToString(b[:]), nil
}

// resolveCLI returns the indexer CLI path: the configured override if set,
// else the first ennam-kg-index found on PATH.
func (h *LocalIndexHandler) resolveCLI() (string, bool) {
	if h.cfg.IndexerCLIPath != "" {
		return h.cfg.IndexerCLIPath, true
	}
	if p, err := exec.LookPath("ennam-kg-index"); err == nil {
		return p, true
	}
	return "", false
}

// StartIndex validates input, resolves the CLI + project_id, launches the
// subprocess in a goroutine, and returns {job_id, status:"running"} at once.
// All failures before launch return an isError result with no job created.
func (h *LocalIndexHandler) StartIndex(params map[string]interface{}) *MCPToolResult {
	if vr := ValidateToolParams("kg_index_source", params); !vr.Valid {
		return errResult(vr.Error())
	}
	path := strParam(params, "path")
	if info, err := os.Stat(path); err != nil || !info.IsDir() {
		return errResult(fmt.Sprintf("path does not exist or is not a directory: %s", path))
	}

	projectID := strParam(params, "project_id")
	if projectID == "" {
		projectID = h.cfg.DefaultProjectID
	}
	if projectID == "" {
		return errResult("project_id required (or set default_project_id in ~/.kg/config.yaml)")
	}

	repoKey := strParam(params, "repo_key")
	if repoKey == "" {
		repoKey = path
	}

	cli, ok := h.resolveCLI()
	if !ok {
		return errResult("ennam-kg-index not found. Install: pip install ennam-kg-indexer, " +
			"or set indexer_cli_path in ~/.kg/config.yaml")
	}

	jobID, err := newJobID()
	if err != nil {
		return errResult("failed to generate job id: " + err.Error())
	}

	h.mu.Lock()
	h.jobs[jobID] = &indexJob{status: "running"}
	h.mu.Unlock()

	go h.run(jobID, cli, path, projectID, repoKey)

	return okResult(fmt.Sprintf(`{"job_id":%q,"status":"running"}`, jobID))
}

// run executes the CLI to completion and records the outcome under the mutex.
// Runs in its own background context (NOT the tool-call context, which is
// cancelled as soon as StartIndex returns), bounded by h.timeout.
func (h *LocalIndexHandler) run(jobID, cli, path, projectID, repoKey string) {
	ctx, cancel := context.WithTimeout(context.Background(), h.timeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, cli,
		"--path", path,
		"--project-id", projectID,
		"--repo-key", repoKey,
		"--mode", "full",
	)
	// Inject KG credentials; the agent never supplies or sees the key.
	cmd.Env = append(os.Environ(),
		"KG_API_URL="+h.cfg.ServerURL,
		"KG_API_KEY="+h.cfg.APIKey,
	)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	runErr := cmd.Run()

	h.mu.Lock()
	defer h.mu.Unlock()
	job := h.jobs[jobID]
	if job == nil {
		return // defensive: job map only grows, but never panic
	}
	if runErr != nil {
		job.status = "error"
		job.errMsg = strings.TrimSpace(tailStr(stderr.String(), 800))
		if job.errMsg == "" {
			job.errMsg = runErr.Error()
		}
		return
	}
	var summary map[string]any
	if err := json.Unmarshal(stdout.Bytes(), &summary); err != nil {
		job.status = "error"
		job.errMsg = "could not parse indexer output: " + tailStr(strings.TrimSpace(stdout.String()), 400)
		return
	}
	job.status = "done"
	job.summary = summary
}

// IndexStatus reports the current state of a job as MCP text JSON.
func (h *LocalIndexHandler) IndexStatus(params map[string]interface{}) *MCPToolResult {
	if vr := ValidateToolParams("kg_index_status", params); !vr.Valid {
		return errResult(vr.Error())
	}
	jobID := strParam(params, "job_id")

	h.mu.Lock()
	job, ok := h.jobs[jobID]
	var snap indexJob
	if ok {
		snap = *job
	}
	h.mu.Unlock()

	if !ok {
		return errResult("unknown job_id")
	}

	var payload map[string]any
	switch snap.status {
	case "running":
		payload = map[string]any{"job_id": jobID, "status": "running"}
	case "done":
		payload = map[string]any{"job_id": jobID, "status": "done", "summary": snap.summary}
	default: // "error"
		payload = map[string]any{"job_id": jobID, "status": "error", "error": snap.errMsg}
	}
	b, err := json.Marshal(payload)
	if err != nil {
		return errResult("failed to encode status: " + err.Error())
	}
	return okResult(string(b))
}

func okResult(text string) *MCPToolResult {
	return &MCPToolResult{Content: []MCPContent{{Type: "text", Text: text}}}
}

func errResult(text string) *MCPToolResult {
	return &MCPToolResult{Content: []MCPContent{{Type: "text", Text: text}}, IsError: true}
}

// tailStr returns the last n bytes of s (whole string if shorter).
func tailStr(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[len(s)-n:]
}
```

> `strParam` is already defined in `serve.go` (package `bridge`) — reuse it, do not redefine.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $GO && go test ./internal/bridge/ -run 'TestStartIndex|TestIndexStatus' -count=1 -race`
Expected: PASS (all 9 cases). `-race` is important — the goroutine writes the job map under the mutex while `IndexStatus` reads it.

- [ ] **Step 5: Commit**

```bash
cd $GO
git add internal/bridge/local_index.go internal/bridge/local_index_test.go
git commit -m "feat(bridge): LocalIndexHandler runs ennam-kg-index CLI with async job tracking"
```

---

### Task 4: Wire dispatch into the serve loop

Build one shared `LocalIndexHandler` in `registerTools` and route the two local tools to it in `makeToolHandler`, before the HTTP-forward path. The 30 proxy tools keep going through `forward` → `HandleToolCall`.

**Files:**
- Modify: `$GO/internal/bridge/serve.go`
- Create: `$GO/internal/bridge/serve_local_index_test.go`

- [ ] **Step 1: Write the failing dispatch test**

Create `$GO/internal/bridge/serve_local_index_test.go`:

```go
package bridge

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// callViaHandler builds the SDK handler closure for one tool and invokes it
// with the given arguments, returning the SDK result.
func callViaHandler(t *testing.T, h *MCPToolHandler, lih *LocalIndexHandler, cfg BridgeConfig, tool string, args map[string]any) *mcp.CallToolResult {
	t.Helper()
	raw, err := json.Marshal(args)
	if err != nil {
		t.Fatalf("marshal args: %v", err)
	}
	handler := makeToolHandler(h, lih, cfg, tool)
	// CallToolRequest = ServerRequest[*CallToolParamsRaw]; the server-side Params
	// type is CallToolParamsRaw, whose Arguments is json.RawMessage (NOT the
	// client-side CallToolParams, whose Arguments is `any`).
	req := &mcp.CallToolRequest{Params: &mcp.CallToolParamsRaw{Arguments: raw}}
	res, err := handler(context.Background(), req)
	if err != nil {
		t.Fatalf("handler returned protocol error: %v", err)
	}
	return res
}

func TestMakeToolHandler_RoutesIndexSourceToLocalHandler(t *testing.T) {
	cli := writeStub(t, `echo '{"nodes_created":3,"errors":[]}'`)
	cfg := BridgeConfig{ServerURL: "http://u", APIKey: "k", IndexerCLIPath: cli}
	lih := NewLocalIndexHandler(cfg)
	h := NewMCPToolHandler(nil) // HTTP client never used for local tools

	res := callViaHandler(t, h, lih, cfg, "kg_index_source",
		map[string]any{"path": t.TempDir(), "project_id": "p"})
	if res.IsError {
		t.Fatalf("kg_index_source errored: %v", res.Content)
	}
	var body map[string]any
	if err := json.Unmarshal([]byte(res.Content[0].(*mcp.TextContent).Text), &body); err != nil {
		t.Fatalf("parse: %v", err)
	}
	jobID, _ := body["job_id"].(string)
	if jobID == "" || body["status"] != "running" {
		t.Fatalf("expected running job, got %v", body)
	}
	// Poll via the status tool through the same dispatch path. Time-bounded
	// (not a fixed iteration count) so it never races ahead of the subprocess.
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		sres := callViaHandler(t, h, lih, cfg, "kg_index_status", map[string]any{"job_id": jobID})
		var sb map[string]any
		_ = json.Unmarshal([]byte(sres.Content[0].(*mcp.TextContent).Text), &sb)
		if sb["status"] == "done" {
			return // success: dispatch routed both start AND status to LocalIndexHandler
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("index job never reached done via dispatch")
}

func TestMakeToolHandler_ProxyToolStillForwardsHTTP(t *testing.T) {
	// A representative HTTP-proxy tool (kg_search) must still hit the backend —
	// proving the local branch did not shadow the forward path.
	var hit bool
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hit = true
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"results":[]}`))
	}))
	defer backend.Close()

	cfg := BridgeConfig{ServerURL: backend.URL, APIKey: "k"}
	client, err := NewClient(cfg.ServerURL, cfg.APIKey)
	if err != nil {
		t.Fatalf("NewClient: %v", err)
	}
	h := NewMCPToolHandler(client)
	lih := NewLocalIndexHandler(cfg)

	res := callViaHandler(t, h, lih, cfg, "kg_search",
		map[string]any{"project_id": "11111111-1111-4111-8111-111111111111", "query": "x"})
	if res.IsError {
		t.Fatalf("kg_search errored: %v", res.Content)
	}
	if !hit {
		t.Error("kg_search did not forward to the HTTP backend")
	}
}
```

> If `kg_search`'s required params differ, mirror the exact arguments used by the existing `TestServe_CallTool_E2E` in `serve_e2e_test.go` (it already calls `kg_search` against an httptest backend) so this test passes the same schema validation.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $GO && go test ./internal/bridge/ -run TestMakeToolHandler -count=1`
Expected: FAIL — `too many arguments in call to makeToolHandler` (the `lih` param does not exist yet).

- [ ] **Step 3: Add the `lih` param and dispatch cases in `serve.go`**

In `$GO/internal/bridge/serve.go`:

(a) In `registerTools`, build one shared handler before the loop and pass it in:

```go
func registerTools(server *mcp.Server, handler *MCPToolHandler, cfg BridgeConfig) error {
	lih := NewLocalIndexHandler(cfg) // shared across all tool closures (job map persists per session)
	for name, schema := range ListToolSchemas() {
		toolName := name
		in, err := toMCPInputSchema(schema)
		if err != nil {
			return err
		}
		server.AddTool(
			&mcp.Tool{Name: toolName, Description: schema.Description, InputSchema: in},
			makeToolHandler(handler, lih, cfg, toolName),
		)
	}
	return nil
}
```

(b) Change the `makeToolHandler` signature and add the two local cases at the **top** of the switch:

```go
func makeToolHandler(handler *MCPToolHandler, lih *LocalIndexHandler, cfg BridgeConfig, toolName string) mcp.ToolHandler {
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
		case "kg_index_source":
			// Local-execution tool: run the CLI subprocess; never forwards HTTP.
			return toCallToolResult(lih.StartIndex(params)), nil
		case "kg_index_status":
			return toCallToolResult(lih.IndexStatus(params)), nil
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

- [ ] **Step 4: Run the dispatch + full bridge tests to verify they pass**

Run: `cd $GO && go test ./internal/bridge/ -count=1 -race`
Expected: PASS — the two new dispatch tests pass, and the existing serve tests (`TestServe_ListTools_E2E`, `TestServe_CallTool_E2E`, `TestStoreSession_*`) still pass (the `registerTools` signature is unchanged, so `serve_e2e_test.go` callers are unaffected).

- [ ] **Step 5: Build the binary**

Run: `cd $GO && go build ./... && go vet ./internal/bridge/`
Expected: clean build, no vet warnings.

- [ ] **Step 6: Commit**

```bash
cd $GO
git add internal/bridge/serve.go internal/bridge/serve_local_index_test.go
git commit -m "feat(bridge): dispatch kg_index_source/kg_index_status to LocalIndexHandler in serve loop"
```

---

### Task 5: Docs + final verification

**Files:**
- Modify: `$WORKSPACE/ennam.kg.requirements/documents/phase1/BA-002-mcp-bridge.md`
- Modify: `$GO/README.md`

- [ ] **Step 1: Document the two tool categories in BA-002**

In `$WORKSPACE/ennam.kg.requirements/documents/phase1/BA-002-mcp-bridge.md`, find the existing implementation note about tool categories (added during the serve-loop work) and extend it so it covers local-execution tools. Append this paragraph there:

```markdown
**Local-execution tools (2):** `kg_index_source` and `kg_index_status` are NOT HTTP-proxy
tools. Instead of forwarding to a REST route, the serve loop dispatches them to
`LocalIndexHandler` (`internal/bridge/local_index.go`), which spawns the locally
installed `ennam-kg-index` CLI as a subprocess on the agent's machine and tracks the
run in an in-memory job map. `kg_index_source` starts a full index of a local
directory and returns a `job_id` immediately; `kg_index_status` polls it. The bridge
injects `KG_API_URL` + `KG_API_KEY` into the subprocess, so the agent never handles
the API key. These two tools require the CLI to be installed on the agent's machine
(`pip install ennam-kg-indexer`, or `indexer_cli_path` in `~/.kg/config.yaml`). This
keeps the bridge's tool surface in two clear categories: 30 HTTP-proxy tools (pure
protocol translation) and 2 local-execution tools (deliberate, isolated subprocess).
```

> If the tool-count phrasing in BA-002 currently says "30 tools", update it to **32 tools (30 HTTP-proxy + 2 local-execution)** wherever the total appears.

- [ ] **Step 2: Document config + tools in the Go README**

In `$GO/README.md`, add a short subsection under the bridge/serve documentation:

```markdown
### Local indexing tools (`kg_index_source`, `kg_index_status`)

The bridge can trigger local code indexing for MCP hosts that have no shell. It runs
the `ennam-kg-index` CLI as a subprocess and pushes nodes to the configured KG server.

- **Prerequisite:** install the CLI on the same machine as the bridge —
  `pip install ennam-kg-indexer` (provides `ennam-kg-index`), or set
  `indexer_cli_path: /abs/path/to/ennam-kg-index` in `~/.kg/config.yaml` (venv/Docker).
- **`kg_index_source`** — params: `path` (required, local dir), `project_id`
  (optional, falls back to `default_project_id`), `repo_key` (optional, default = path;
  use a stable id like `github.com/org/repo`). Returns `{job_id, status:"running"}`.
- **`kg_index_status`** — param: `job_id`. Returns `running`, `done` (with the indexer's
  JSON summary), or `error`.
- The bridge injects `KG_API_URL`/`KG_API_KEY` into the subprocess; the agent never
  handles the key.

Common errors: `ennam-kg-index not found` (install it or set `indexer_cli_path`),
`path does not exist` (bad `path`), `project_id required` (pass it or set
`default_project_id`).
```

- [ ] **Step 3: Full bridge suite + build, one more time**

Run: `cd $GO && go test ./internal/bridge/ -count=1 -race && go build ./...`
Expected: PASS + clean build.

- [ ] **Step 4a: Mac dev smoke (fast local sanity, optional)**

```bash
# 1. Build the bridge
cd $GO && make build           # → bin/kg-bridge

# 2. Point it at the local server with a real config
mkdir -p ~/.kg && cat > ~/.kg/config.yaml <<'EOF'
server_url: http://localhost:8080
api_key: ennam_kg_dev_000000000000000000000000
default_project_id: a697ca97-112f-402c-8c0c-3c363e98b2ce
indexer_cli_path: /ABS/PATH/TO/ennam-kg-index   # `which ennam-kg-index` after pip install
EOF

# 3. Drive the bridge over stdio: initialize, then tools/call kg_index_source, then poll kg_index_status.
#    Verify: kg_index_source → {"job_id":"idx-...","status":"running"};
#            kg_index_status  → {"status":"done","summary":{...}} with nodes_created>0;
#            stdout carries ONLY JSON-RPC frames (no stray logging).
```

- [ ] **Step 4b: Windows acceptance smoke (the ACTUAL target — Cách B over LAN)**

This is the environment the user will run. The Go code is cross-platform and the tests are Unix-gated; this step validates the real deployment.

```powershell
# On the Windows machine (same LAN as the Mac running the KG server at 192.168.1.3:8080):

# 1. Install the indexer CLI (Python 3.12). pip drops ennam-kg-index.exe in ...\Scripts\
py -3.12 -m pip install C:\windows-test-kit\ennam_kg_indexer-0.1.0-py3-none-any.whl
$cli = (Get-Command ennam-kg-index).Source    # e.g. C:\Users\me\...\Scripts\ennam-kg-index.exe

# 2. Bridge config at %USERPROFILE%\.kg\config.yaml — set indexer_cli_path EXPLICITLY (see note below)
@"
server_url: http://192.168.1.3:8080
api_key: ennam_kg_dev_000000000000000000000000
default_project_id: a697ca97-112f-402c-8c0c-3c363e98b2ce
indexer_cli_path: $cli
"@ | Set-Content $env:USERPROFILE\.kg\config.yaml

# 3. Wire kg-bridge.exe (cross-compiled, in C:\windows-test-kit\) into the MCP host (Claude config):
#      "ennam-kg": { "command": "C:\\windows-test-kit\\kg-bridge.exe", "args": ["serve"] }
# 4. In Claude (Windows): call kg_index_source(path="C:\\src\\repoA") → expect {"status":"running"};
#    then kg_index_status(job_id) until {"status":"done","summary":{nodes_created:>0,...}}.
# 5. Re-run kg_index_source on the SAME repo → second summary shows nodes_created≈0 (replace, no accumulation).
```

> **Windows CLI-resolution note (call this out to the user):** `exec.LookPath("ennam-kg-index")` on
> Windows honors `PATHEXT` and finds `ennam-kg-index.exe` **only if the pip `Scripts\` dir is on the
> bridge process's PATH**. MCP hosts often launch the bridge with a minimal environment, so PATH may not
> include `Scripts\`. **Always set `indexer_cli_path` explicitly** (step 2 above) to avoid a
> "ennam-kg-index not found" error. The bridge's error message already points here, so the failure is
> graceful — but the explicit path skips it entirely.

Expected: on the first index a `job_id` returns immediately, polling reaches `done` with `nodes_created > 0`, the nodes are queryable from the Mac (`kg_query`/`kg_search` or dashboard), and the agent never handles the API key. Document the observed Windows output below this step when run.

- [ ] **Step 5: Commit the Go README + push nothing (per project convention, commits stay local)**

```bash
cd $GO
git add README.md
git commit -m "docs(bridge): document local indexing tools and indexer_cli_path"
```

- [ ] **Step 6: Commit the BA-002 doc in the requirements repo (separate repo)**

```bash
cd $WORKSPACE/ennam.kg.requirements
git add documents/phase1/BA-002-mcp-bridge.md
git commit -m "docs(BA-002): document local-execution tools (kg_index_source/status)"
```

---

## Self-Review

### Spec coverage

| Spec section | Task |
|--------------|------|
| Part 1 — `kg_index_source` (path/project_id/repo_key, returns job_id+running) | Task 2 (schema) + Task 3 (behavior) |
| Part 1 — `kg_index_status` (job_id → running/done/error/unknown) | Task 2 (schema) + Task 3 (behavior) |
| Part 1 — `mode`/`changed_files` not exposed (full scan only) | Task 3 (`--mode full` hard-coded) |
| Part 2 — dispatch branch before HTTP path; proxy tools untouched | Task 4 (`makeToolHandler` cases first; `kg_search` regression test) |
| Part 2 — local logic isolated in `local_index.go`; registry-based discovery+validation | Task 2 + Task 3 |
| Part 3 — CLI location (config override → PATH) | Task 3 `resolveCLI` |
| Part 3 — credential injection (`KG_API_URL`/`KG_API_KEY`), agent never sees key | Task 3 `run` env + `TestStartIndex_InjectsEnvAndFlags` |
| Part 3 — background goroutine + in-memory job map + timeout backstop | Task 3 `StartIndex`/`run`/`defaultIndexTimeout` |
| Part 3 — job_id = `idx-` + hex(crypto/rand 8) | Task 3 `newJobID` |
| Part 4 — all error rows (CLI not found, path missing, project_id missing, subprocess≠0, unparseable, unknown job_id) | Task 3 tests (one per row) |
| Part 5 — `indexer_cli_path` config field; default project fallback | Task 1 + Task 3 |
| Part 5 — docs (BA-002 note + README) | Task 5 |
| Part 6 — fake-CLI tests (happy, env/flags, failure, not-found, path, project fallback, unknown job, dispatch+no-regression) | Task 3 + Task 4 |

### Placeholder scan

No TBD/TODO. Every code and command step shows concrete content. The one runtime-specific value (`/ABS/PATH/TO/ennam-kg-index` in the manual smoke step) is an environment path the operator fills at run time, not a code placeholder.

### Type consistency

- `BridgeConfig.IndexerCLIPath` — added Task 1, read in Task 3 `resolveCLI`. Consistent.
- `LocalIndexHandler` + `NewLocalIndexHandler(BridgeConfig)` — defined Task 3, constructed in Task 4 `registerTools` and in tests. Consistent.
- `StartIndex(map[string]interface{}) *MCPToolResult` / `IndexStatus(...) *MCPToolResult` — defined Task 3, called in Task 4 `makeToolHandler`. Consistent.
- `makeToolHandler(handler *MCPToolHandler, lih *LocalIndexHandler, cfg BridgeConfig, toolName string)` — new signature Task 4 Step 3(b); only caller is `registerTools` (same step) + the Task 4 test helper. Consistent.
- `okResult`/`errResult`/`tailStr`/`newJobID` — defined in Task 3 `local_index.go`; `strParam` reused from `serve.go` (not redefined). Consistent.
- Schema names `kg_index_source`/`kg_index_status` — identical across Tasks 2, 3, 4. Consistent.
- `localToolNames` — defined Task 2 Step 3 in `schema.go`; consumed by the cross-check test fixes in Task 2 Step 5. Defined before use. Consistent.
- `project_id` schema is a plain optional string (no uuid `Pattern`) — deliberate so `ValidateToolParams` (called first in `StartIndex`, Task 3) accepts the non-uuid fixture ids used throughout the Task 3/4 tests; the server/CLI pre-flight is the real authority.

### No-route test reconciliation (verified against current source)

Registering two schemas without HTTP routes breaks exactly four existing assertions; Task 2 Step 5 fixes each with a precise edit: `schema_test.go` count (30→32) and `TestAllToolSchemasMatchRoutes` (skip `localToolNames`), `e2e_tools_test.go` count (`+len(localToolNames)`), `handler_test.go` `ListTools` count (30→32). Confirmed unaffected (no edit): `integration_test.go` (route-count, still 30), `serve_e2e_test.go` (`32 == 32`), `TestValidateRequiredFields_AllToolsEmptyParams` and `TestE2E_MCPHandlerToolValidation` (hardcoded subsets, not full-registry counts).

### Task ordering note

Task 2 registers the schemas before Task 4 wires dispatch. Between them, the tools appear in `tools/list` but `makeToolHandler`'s default case would forward them to `HandleToolCall` (which rejects no-route tools). No test exercises that intermediate state — Task 2's tests are schema-level (`ListToolSchemas`/`ValidateToolParams`) and `TestServe_ListTools_E2E` only lists, never calls — so every task ends green and independently committable.
