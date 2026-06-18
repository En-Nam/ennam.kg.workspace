# IMP-008: LAAM Read-Only Qwen Tool Profile — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Qwen read-only tool profile: polish 6 read-tool descriptions (FR-1), add server-side `readonly` bearer scope enforcement (FR-2), and define the canonical profile constant (FR-3).

**Architecture:** Route classification tags are added to `ToolRoute` in `client.go` (single source of truth for read/write/local class); scope is extracted from the bearer token in `requireBearerV2` and injected as a context value; scope enforcement lives in `makeToolHandler` (the only place where `toolName` is known — MCP Streamable HTTP collapses all tool calls to a single `/` path, so HTTP middleware cannot classify by tool).

**Tech Stack:** Go stdlib, `internal/bridge` package, table-driven `go test -race`.

## Global Constraints

- Touch only `internal/bridge/` — no handler, service, or DB changes.
- The 35-tool catalog (33 routed + 2 local) is **unchanged** for Claude/internal callers.
- `const` cannot hold `[]string` in Go — use `var` for the profile.
- `go test ./internal/bridge/... -race` must stay green after each task.
- `make lint` (golangci-lint) must pass after each task.
- Final corrected route counts: **READ=12 / WRITE=21 / LOCAL=2** (see Task 1 for full list).

---

## File Map

| File | Changes |
|------|---------|
| `internal/bridge/client.go` | Add `RouteClass` type + `Class` field to `ToolRoute`; classify all 33 routes |
| `internal/bridge/schema.go` | Rewrite 5 tool descriptions; fix `kg_search_chunks` MaxValue; add `QwenReadOnlyToolProfile` var |
| `internal/bridge/middleware.go` | Add `ctxKeyScope` context key |
| `internal/bridge/startup.go` | Return `(token, readonlyToken string, err error)`; read `KG_MCP_TOKEN_READONLY` |
| `internal/bridge/middleware_auth.go` | Accept readonly token; inject scope into context |
| `internal/bridge/serve.go` | Update call sites for `validateHTTPStartup` and `requireBearerV2`; add scope gate in `makeToolHandler` |
| `internal/bridge/client_test.go` | AC-4: all routes tagged, no untagged route |
| `internal/bridge/schema_test.go` | Profile constant tests |
| `internal/bridge/serve_http_test.go` | Add imports; add 3 readonly scope tests |
| `internal/bridge/startup_test.go` | **Migrate** 3 existing tests to 3-value return; add 3 new readonly token tests |
| `internal/bridge/middleware_auth_test.go` | **Migrate** 10 existing calls from 2-arg to 3-arg; add 2 new scope tests |

---

## Task 1: Route Classification in `client.go`

**Files:**
- Modify: `internal/bridge/client.go`
- Test: `internal/bridge/client_test.go`

**Interfaces:**
- Produces: `RouteClass` type + constants (`RouteRead`, `RouteWrite`, `RouteLocal`); `ToolRoute.Class` field; used by Task 5 scope enforcement.

- [ ] **Step 1.1: Write the failing test**

Add to `internal/bridge/client_test.go`:

```go
func TestAllRoutesTagged(t *testing.T) {
    for name, route := range toolRoutes {
        if route.Class == "" {
            t.Errorf("tool %q has no route class; every route must be tagged read/write/local", name)
        }
    }
}

func TestLocalToolsNotInRoutes(t *testing.T) {
    for name := range localToolNames {
        if _, ok := toolRoutes[name]; ok {
            t.Errorf("local tool %q should not be in toolRoutes", name)
        }
    }
}
```

- [ ] **Step 1.2: Run test to verify it fails**

```bash
cd ennam.kg.go && go test ./internal/bridge/ -run TestAllRoutesTagged -v
```
Expected: FAIL — `RouteClass` undefined.

- [ ] **Step 1.3: Add `RouteClass` type and classify all routes**

In `client.go`, after the `const` block (after line 30), add:

```go
// RouteClass classifies an MCP tool route for scope enforcement.
// Enforcement lives in makeToolHandler, not HTTP middleware, because
// MCP Streamable HTTP routes all calls to a single path — the tool name
// is invisible at the HTTP layer.
type RouteClass string

const (
    // RouteRead marks routes that only read data (safe under readonly credentials).
    RouteRead RouteClass = "read"
    // RouteWrite marks routes that create, update, or delete data.
    RouteWrite RouteClass = "write"
    // RouteLocal marks tools executed locally (no HTTP route — no readonly bypass possible).
    RouteLocal RouteClass = "local"
)
```

Add `Class RouteClass` field to `ToolRoute`:

```go
type ToolRoute struct {
    Method       string
    PathTemplate string
    PathParams   []string
    QueryParams  []string
    // Class is the read/write/local classification used by the readonly scope gate.
    Class RouteClass
}
```

Classify all 33 entries in `toolRoutes`. Add `Class: RouteWrite` or `Class: RouteRead` to each entry.

**READ (12 routes):**
`kg_search`, `kg_search_chunks`, `kg_query`, `kg_get_node`, `kg_get_document`,
`kg_get_neighbors`, `kg_traverse`, `kg_get_context`, `kg_get_impact_analysis`,
`kg_get_history`, `kg_list_projects`, `kg_list_drafts`

**WRITE (21 routes):**
`kg_store_decision`, `kg_store_concept`, `kg_store_requirement`, `kg_store_task`,
`kg_store_architecture`, `kg_store_discovery`, `kg_store_session`, `kg_end_session`,
`kg_link`, `kg_update`, `kg_update_decision`, `kg_update_concept`, `kg_update_requirement`,
`kg_update_task`, `kg_update_architecture`, `kg_update_discovery`, `kg_deprecate`,
`kg_ingest_node`, `kg_ingest_batch`, `kg_approve_drafts`, `kg_process_drafts`

Example entries:

```go
"kg_search": {
    Method:       http.MethodPost,
    PathTemplate: apiPrefix + "/search",
    Class:        RouteRead,
},
"kg_store_decision": {
    Method:       http.MethodPost,
    PathTemplate: apiPrefix + "/nodes",
    Class:        RouteWrite,
},
"kg_end_session": {
    Method:       http.MethodPost,
    PathTemplate: apiPrefix + "/sessions/{session_id}/end",
    PathParams:   []string{"session_id"},
    Class:        RouteWrite, // POST that mutates sessions table + triggers RemoveSessionFile
},
"kg_list_drafts": {
    Method:       http.MethodGet,
    PathTemplate: apiPrefix + "/projects/{projectId}/draft-nodes",
    PathParams:   []string{"projectId"},
    QueryParams:  []string{"status", "source_type", "search", "limit", "offset"},
    Class:        RouteRead,
},
```

- [ ] **Step 1.4: Run test to verify it passes**

```bash
go test ./internal/bridge/ -run TestAllRoutesTagged -v
go test ./internal/bridge/ -run TestLocalToolsNotInRoutes -v
```
Expected: PASS.

- [ ] **Step 1.5: Run full bridge tests**

```bash
go test ./internal/bridge/... -race -count=1
```
Expected: all pass (only schema count tests may fail if they check exact counts — fix those by updating expected counts to 33 routes, 12 read, 21 write).

- [ ] **Step 1.6: Commit**

```bash
git add internal/bridge/client.go internal/bridge/client_test.go
git commit -m "feat(bridge): add RouteClass type and classify all 33 MCP routes (IMP-008 FR-2 prereq)"
```

---

## Task 2: FR-1 — Description Polish + `kg_search_chunks` MaxValue Fix

**Files:**
- Modify: `internal/bridge/schema.go` (descriptions only + one MaxValue field)
- Test: `internal/bridge/schema_test.go`

**Interfaces:**
- Produces: updated `Description` strings for 5 profile tools; `MaxValue: intPtr(10)` on `kg_search_chunks` limit.
- No schema breaking changes — param names, Required, and Enum are unchanged.

- [ ] **Step 2.1: Write the failing tests**

Add to `internal/bridge/schema_test.go`:

```go
func TestProfileToolDescriptions(t *testing.T) {
    cases := []struct {
        tool    string
        mustContain string
    }{
        {"kg_search", "Search KG nodes"},
        {"kg_search_chunks", "passage"},
        {"kg_get_node", "Fetch one node"},
        {"kg_get_neighbors", "one-hop"},
        {"kg_get_document", "citation"},
    }
    for _, tc := range cases {
        s := GetToolSchema(tc.tool)
        if s == nil {
            t.Fatalf("%s: schema not found", tc.tool)
        }
        if !strings.Contains(s.Description, tc.mustContain) {
            t.Errorf("%s: description %q missing %q", tc.tool, s.Description, tc.mustContain)
        }
    }
}

func TestKgSearchChunksLimitMaxValue(t *testing.T) {
    s := GetToolSchema("kg_search_chunks")
    if s == nil {
        t.Fatal("kg_search_chunks schema not found")
    }
    limit, ok := s.Properties["limit"]
    if !ok {
        t.Fatal("kg_search_chunks: limit param not found")
    }
    if limit.MaxValue == nil || *limit.MaxValue != 10 {
        t.Errorf("kg_search_chunks limit MaxValue: got %v, want 10", limit.MaxValue)
    }
}
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
go test ./internal/bridge/ -run TestProfileToolDescriptions -v
go test ./internal/bridge/ -run TestKgSearchChunksLimitMaxValue -v
```
Expected: TestProfileToolDescriptions fails (descriptions don't match); TestKgSearchChunksLimitMaxValue fails (MaxValue nil).

- [ ] **Step 2.3: Rewrite the 5 tool descriptions and fix MaxValue**

In `schema.go`, `buildToolSchemas()`:

**`kg_search`** (line ~1104):
```go
Description: "Search KG nodes by concept, decision, task, document, or keyword. Use `mode` to select fulltext (default), semantic (vector), or hybrid — pass `project_id` and `query` as the minimum.",
```

**`kg_get_node`** (line ~1174):
```go
Description: "Fetch one node by UUID and return its full properties, type, and status. Requires `id` and `project_id`.",
```

**`kg_get_document`** (line ~1184):
```go
Description: "Resolve a document_id to its citation metadata (filename, source URL, section count). Pass the document_id from a kg_search result's section properties to cite the source.",
```

**`kg_search_chunks`** (line ~1205):
```go
Description: "Search document passages for the exact text to cite in an answer; returns passage text with section and line location. Use instead of kg_search when you need a verbatim quote.",
```

Also on the `limit` param inside `kg_search_chunks` (around line ~1231), add `MaxValue`:
```go
"limit": {
    Type:        TypeInteger,
    Required:    false,
    Description: "Max results (default 5, max 10)",
    MaxValue:    intPtr(10),
},
```

**`kg_get_neighbors`** (line ~1246):
```go
Description: "Get the one-hop neighbors of a node with their edge labels and direction. Use to trace relationships from a node found via kg_search.",
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
go test ./internal/bridge/ -run TestProfileToolDescriptions -v
go test ./internal/bridge/ -run TestKgSearchChunksLimitMaxValue -v
```
Expected: PASS.

- [ ] **Step 2.5: Fix `kg_search_chunks` missing from existing `TestAllToolSchemasRegistered`**

`schema_test.go` already has `TestAllToolSchemasRegistered` which asserts `len(schemas) == 35` but does NOT list `kg_search_chunks` in its `expectedTools` slice. Add it:

```go
// In the expectedTools slice inside TestAllToolSchemasRegistered, add:
"kg_search_chunks",
```

The slice currently has 33 entries; after adding `kg_search_chunks` it will have 34 (the 35th check is the `len(schemas) != 35` assertion, which already covers the count). The comment at the top of that test says "32 MCP tools" — update it to "35 MCP tools (33 HTTP-proxy + 2 local-exec)".

- [ ] **Step 2.6: Run full bridge tests**

```bash
go test ./internal/bridge/... -race -count=1
```
Expected: all pass.

- [ ] **Step 2.7: Commit**

```bash
git add internal/bridge/schema.go internal/bridge/schema_test.go
git commit -m "feat(bridge): polish 5 read-tool descriptions and fix kg_search_chunks MaxValue (IMP-008 FR-1)"
```

---

## Task 3: FR-3 — Qwen Profile Constant

**Files:**
- Modify: `internal/bridge/schema.go`
- Test: `internal/bridge/schema_test.go`

**Interfaces:**
- Produces: `QwenReadOnlyToolProfile []string` — consumed by Phase-4 LAAM `QwenOllamaAdapter.renderTools()`.
- All 6 profile tools must be READ class (asserted in the test using Task 1's `RouteClass`).

- [ ] **Step 3.1: Write the failing tests**

Add to `internal/bridge/schema_test.go`:

```go
func TestQwenReadOnlyToolProfileContents(t *testing.T) {
    want := map[string]bool{
        "kg_search":        true,
        "kg_search_chunks": true,
        "kg_get_node":      true,
        "kg_get_neighbors": true,
        "kg_get_document":  true,
        "kg_list_drafts":   true,
    }
    if len(QwenReadOnlyToolProfile) != len(want) {
        t.Fatalf("profile length: got %d, want %d", len(QwenReadOnlyToolProfile), len(want))
    }
    for _, name := range QwenReadOnlyToolProfile {
        if !want[name] {
            t.Errorf("unexpected tool in profile: %q", name)
        }
    }
}

func TestQwenProfileToolsAreReadClass(t *testing.T) {
    for _, name := range QwenReadOnlyToolProfile {
        route, ok := toolRoutes[name]
        if !ok {
            // local tools (kg_index_source etc.) are not in toolRoutes — skip
            if localToolNames[name] {
                continue
            }
            t.Errorf("profile tool %q not found in toolRoutes", name)
            continue
        }
        if route.Class != RouteRead {
            t.Errorf("profile tool %q has class %q, want %q", name, route.Class, RouteRead)
        }
    }
}

func TestQwenProfileToolsHaveSchemas(t *testing.T) {
    for _, name := range QwenReadOnlyToolProfile {
        if GetToolSchema(name) == nil {
            t.Errorf("profile tool %q has no schema", name)
        }
    }
}
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
go test ./internal/bridge/ -run TestQwen -v
```
Expected: FAIL — `QwenReadOnlyToolProfile` undefined.

- [ ] **Step 3.3: Add the profile constant**

In `schema.go`, after the `localToolNames` var block (after line ~190), add:

```go
// QwenReadOnlyToolProfile is the canonical 6-tool set for the Qwen model profile.
// LAAM's QwenOllamaAdapter.renderTools() MUST render exactly these tools and no others.
// Rules:
//   - All 6 tools are READ class (safe under a readonly bearer credential).
//   - Unknown entries in a LAAM whitelist must be logged and dropped (fail-closed).
//   - ClaudeAdapter renders all 35 tools; only the Qwen path filters.
//
// Phase-4 acceptance criteria:
//   - QwenOllamaAdapter renders exactly these 6 tools (assert len==6 and names match).
//   - An unknown profile entry is logged at WARN level and silently dropped.
//   - DefaultProjectID MUST be configured before tool calls (project_id is required).
//   - Use kg_search as the primary entry point; kg_search_chunks for verbatim citation passages.
var QwenReadOnlyToolProfile = []string{
    "kg_search",
    "kg_search_chunks",
    "kg_get_node",
    "kg_get_neighbors",
    "kg_get_document",
    "kg_list_drafts",
}
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
go test ./internal/bridge/ -run TestQwen -v
```
Expected: all 3 PASS.

- [ ] **Step 3.5: Commit**

```bash
git add internal/bridge/schema.go internal/bridge/schema_test.go
git commit -m "feat(bridge): add QwenReadOnlyToolProfile constant and AC tests (IMP-008 FR-3)"
```

---

## Task 4: Scope Infrastructure (middleware context key + startup + auth middleware)

**Files:**
- Modify: `internal/bridge/middleware.go` (add `ctxKeyScope`)
- Modify: `internal/bridge/startup.go` (read `KG_MCP_TOKEN_READONLY`, return both tokens)
- Modify: `internal/bridge/middleware_auth.go` (accept readonly token, inject scope)
- Modify: `internal/bridge/serve.go` (update call sites)
- Test: `internal/bridge/middleware_auth_test.go` (scope injection tests)
- Test: `internal/bridge/startup_test.go` (readonly token optional)

**Interfaces:**
- Consumes: `RouteClass` from Task 1 (via Task 5).
- Produces: `ctxKeyScope` context key; `TokenScope` type; `scopeFromContext(ctx)` helper.
- `requireBearerV2(fullToken, readonlyToken string, onFailure func())` — new signature.
- `validateHTTPStartup(addr string) (token, readonlyToken string, err error)` — new signature.

- [ ] **Step 4.1: Write failing tests**

Add to `internal/bridge/middleware_auth_test.go`:

```go
func TestRequireBearerV2ScopeInjection(t *testing.T) {
    const fullToken = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"    // 43 chars
    const readonlyToken = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" // 43 chars

    mw := requireBearerV2(fullToken, readonlyToken, nil)

    tests := []struct {
        name      string
        authHeader string
        wantStatus int
        wantScope  string
    }{
        {"full token", "Bearer " + fullToken, http.StatusOK, "full"},
        {"readonly token", "Bearer " + readonlyToken, http.StatusOK, "readonly"},
        {"wrong token", "Bearer wrongtoken", http.StatusUnauthorized, ""},
        {"no header", "", http.StatusUnauthorized, ""},
        {"empty readonly skipped", "Bearer " + fullToken, http.StatusOK, "full"},
    }

    for _, tc := range tests {
        t.Run(tc.name, func(t *testing.T) {
            var gotScope string
            next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
                gotScope, _ = r.Context().Value(ctxKeyScope).(string)
                w.WriteHeader(http.StatusOK)
            })
            rec := httptest.NewRecorder()
            req := httptest.NewRequest(http.MethodGet, "/", nil)
            if tc.authHeader != "" {
                req.Header.Set("Authorization", tc.authHeader)
            }
            mw(next).ServeHTTP(rec, req)
            if rec.Code != tc.wantStatus {
                t.Errorf("status: got %d, want %d", rec.Code, tc.wantStatus)
            }
            if tc.wantScope != "" && gotScope != tc.wantScope {
                t.Errorf("scope: got %q, want %q", gotScope, tc.wantScope)
            }
        })
    }
}

func TestRequireBearerV2EmptyReadonlyToken(t *testing.T) {
    const fullToken = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    mw := requireBearerV2(fullToken, "", nil) // empty readonly = disabled

    var gotScope string
    next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        gotScope, _ = r.Context().Value(ctxKeyScope).(string)
        w.WriteHeader(http.StatusOK)
    })
    rec := httptest.NewRecorder()
    req := httptest.NewRequest(http.MethodGet, "/", nil)
    req.Header.Set("Authorization", "Bearer "+fullToken)
    mw(next).ServeHTTP(rec, req)
    if rec.Code != http.StatusOK {
        t.Fatalf("status: got %d, want 200", rec.Code)
    }
    if gotScope != "full" {
        t.Errorf("scope: got %q, want %q", gotScope, "full")
    }
}
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
go test ./internal/bridge/ -run TestRequireBearerV2Scope -v
go test ./internal/bridge/ -run TestRequireBearerV2Empty -v
```
Expected: FAIL — `ctxKeyScope` undefined; `requireBearerV2` signature mismatch.

- [ ] **Step 4.3: Add `ctxKeyScope` to `middleware.go`**

In `internal/bridge/middleware.go`, add after `ctxKeyTokenHash`:

```go
    // ctxKeyScope is the authorization scope of the presented Bearer token.
    // Values: "full" (default write+read credential) or "readonly" (read-only credential).
    // Set by requireBearerV2; read by makeToolHandler for scope enforcement.
    ctxKeyScope ctxKey = "scope"
```

- [ ] **Step 4.4: Migrate existing `startup_test.go` for new 3-value return**

`validateHTTPStartup` currently returns `(string, error)`. After the change below it returns `(string, string, error)`. Three existing tests will fail to compile — update them first:

```go
// TestValidateHTTPStartupRejectsEmptyToken:
if _, _, err := validateHTTPStartup(":8082"); err == nil { ... }

// TestValidateHTTPStartupRejectsLowEntropyToken:
if _, _, err := validateHTTPStartup(":8082"); err == nil { ... }

// TestValidateHTTPStartupPassesValidToken:
got, _, err := validateHTTPStartup("127.0.0.1:8082")
```

Also add a new test for the readonly token path:

```go
func TestValidateHTTPStartupReadonlyToken(t *testing.T) {
    full := base64.RawURLEncoding.EncodeToString(make([]byte, 32))
    ro := base64.RawURLEncoding.EncodeToString(make([]byte, 33)) // different value
    t.Setenv("KG_MCP_TOKEN", full)
    t.Setenv("KG_MCP_TOKEN_READONLY", ro)
    _, gotRO, err := validateHTTPStartup("127.0.0.1:8082")
    if err != nil {
        t.Fatalf("unexpected error: %v", err)
    }
    if gotRO != ro {
        t.Errorf("readonlyToken: got %q, want %q", gotRO, ro)
    }
}

func TestValidateHTTPStartupReadonlyAbsent(t *testing.T) {
    full := base64.RawURLEncoding.EncodeToString(make([]byte, 32))
    t.Setenv("KG_MCP_TOKEN", full)
    t.Setenv("KG_MCP_TOKEN_READONLY", "")
    _, gotRO, err := validateHTTPStartup("127.0.0.1:8082")
    if err != nil {
        t.Fatalf("unexpected error: %v", err)
    }
    if gotRO != "" {
        t.Errorf("readonlyToken should be empty when env unset, got %q", gotRO)
    }
}

func TestValidateHTTPStartupReadonlySameAsFullRejected(t *testing.T) {
    full := base64.RawURLEncoding.EncodeToString(make([]byte, 32))
    t.Setenv("KG_MCP_TOKEN", full)
    t.Setenv("KG_MCP_TOKEN_READONLY", full) // same value — must be rejected
    if _, _, err := validateHTTPStartup("127.0.0.1:8082"); err == nil {
        t.Error("expected error when KG_MCP_TOKEN_READONLY == KG_MCP_TOKEN")
    }
}
```

- [ ] **Step 4.5: Update `validateHTTPStartup` body in `startup.go`**

Change signature and body:

```go
// validateHTTPStartup checks all preconditions before the HTTP listener opens.
// Returns (fullToken, readonlyToken, nil) on success. readonlyToken is empty
// when KG_MCP_TOKEN_READONLY is not set (readonly scope disabled).
func validateHTTPStartup(addr string) (string, string, error) {
    token := os.Getenv("KG_MCP_TOKEN")
    if token == "" {
        return "", "", errors.New("KG_MCP_TOKEN is required for HTTP mode; set it or use stdio mode")
    }
    if err := validateTokenEntropy(token); err != nil {
        return "", "", fmt.Errorf("KG_MCP_TOKEN: %w", err)
    }
    if err := assertTLSDeployment(addr); err != nil {
        return "", "", fmt.Errorf("TLS deployment: %w", err)
    }
    readonlyToken := os.Getenv("KG_MCP_TOKEN_READONLY")
    if readonlyToken != "" {
        if err := validateTokenEntropy(readonlyToken); err != nil {
            return "", "", fmt.Errorf("KG_MCP_TOKEN_READONLY: %w", err)
        }
        if readonlyToken == token {
            return "", "", errors.New("KG_MCP_TOKEN_READONLY must differ from KG_MCP_TOKEN")
        }
    }
    return token, readonlyToken, nil
}
```

- [ ] **Step 4.6: Migrate existing `middleware_auth_test.go` for new 3-arg signature**

`requireBearerV2` currently takes 2 args: `(token string, onFailure func())`. The new signature is `(fullToken, readonlyToken string, onFailure func())`. Every existing call site in `middleware_auth_test.go` must add `""` as the second argument:

```go
// Replace ALL occurrences of:
requireBearerV2(validToken, nil)
requireBearerV2(validToken, func() { called++ })
// With:
requireBearerV2(validToken, "", nil)
requireBearerV2(validToken, "", func() { called++ })
```

There are 10 such call sites in `middleware_auth_test.go`. Update every one before implementing the new function — otherwise the file won't compile after the function signature changes.

- [ ] **Step 4.7: Update `requireBearerV2` in `middleware_auth.go`**

```go
// requireBearerV2 is a middleware factory. It accepts two tokens:
//   - fullToken: grants full read+write scope ("full")
//   - readonlyToken: optional; grants read-only scope ("readonly"); pass "" to disable
//
// On success it injects ctxKeyScope ("full" or "readonly") into the context.
// ctxKeyTokenHash (SHA-256 of presented token) is always injected for rate-limiting.
func requireBearerV2(fullToken, readonlyToken string, onFailure func()) func(http.Handler) http.Handler {
    wantFull := []byte("Bearer " + fullToken)
    hashFull := sha256sum([]byte(fullToken))
    var wantReadonly []byte
    var hashReadonly string
    if readonlyToken != "" {
        wantReadonly = []byte("Bearer " + readonlyToken)
        hashReadonly = sha256sum([]byte(readonlyToken))
    }
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            got := []byte(r.Header.Get("Authorization"))
            var tokenHash string
            var scope string
            switch {
            case subtle.ConstantTimeCompare(got, wantFull) == 1:
                tokenHash = hashFull
                scope = "full"
            case len(wantReadonly) > 0 && subtle.ConstantTimeCompare(got, wantReadonly) == 1:
                tokenHash = hashReadonly
                scope = "readonly"
            default:
                if onFailure != nil {
                    onFailure()
                }
                http.Error(w, "unauthorized", http.StatusUnauthorized)
                return
            }
            r = r.Clone(r.Context())
            r.Header.Del("Authorization")
            ctx := context.WithValue(r.Context(), ctxKeyTokenHash, tokenHash)
            ctx = context.WithValue(ctx, ctxKeyScope, scope)
            next.ServeHTTP(w, r.WithContext(ctx))
        })
    }
}
```

- [ ] **Step 4.8: Update call sites in `serve.go`**

In `serveHTTP`, change:
```go
// Old:
token, err := validateHTTPStartup(addr)
...
requireBearerV2(token, metrics.incAuthFailure),
```
To:
```go
// New:
token, readonlyToken, err := validateHTTPStartup(addr)
...
requireBearerV2(token, readonlyToken, metrics.incAuthFailure),
```

- [ ] **Step 4.9: Run tests to verify they pass**

```bash
go test ./internal/bridge/ -run TestRequireBearerV2 -v
go test ./internal/bridge/ -run TestValidateHTTPStartup -v
go test ./internal/bridge/... -race -count=1
```
Expected: all pass.

- [ ] **Step 4.10: Commit**

```bash
git add internal/bridge/middleware.go internal/bridge/startup.go \
        internal/bridge/middleware_auth.go internal/bridge/serve.go \
        internal/bridge/middleware_auth_test.go internal/bridge/startup_test.go
git commit -m "feat(bridge): add readonly bearer scope infrastructure — ctxKeyScope, KG_MCP_TOKEN_READONLY (IMP-008 FR-2 part A)"
```

---

## Task 5: FR-2 — Scope Enforcement in `makeToolHandler`

**Files:**
- Modify: `internal/bridge/serve.go` (`makeToolHandler` function)
- Test: `internal/bridge/serve_http_test.go`

**Interfaces:**
- Consumes: `ctxKeyScope` (Task 4), `RouteClass` from `toolRoutes` (Task 1).
- Produces: `IsError: true` response with message `"forbidden: readonly credential cannot invoke write tool"` when a readonly-scoped call targets a write/local route.

- [ ] **Step 5.1: Write the failing tests**

Add to `internal/bridge/serve_http_test.go`. The file currently only imports `"testing"` — add the required imports:

```go
import (
    "context"
    "encoding/json"
    "strings"
    "testing"

    "github.com/modelcontextprotocol/go-sdk/mcp"
)
```

Then add the tests:

```go
func TestReadonlyScopeBlocksWriteTools(t *testing.T) {
    // Verify that a request with scope="readonly" in context cannot call write tools.
    // We test makeToolHandler's scope gate in isolation by injecting scope via context.
    writeTools := []string{
        "kg_store_decision",
        "kg_link",
        "kg_deprecate",
        "kg_end_session",
        "kg_ingest_node",
    }
    client := &Client{baseURL: "http://unused", apiKey: "x"}
    lih := NewLocalIndexHandler(BridgeConfig{})
    cfg := BridgeConfig{}

    for _, toolName := range writeTools {
        t.Run(toolName, func(t *testing.T) {
            h := makeToolHandler(client, lih, cfg, toolName)
            // Inject readonly scope into context (as requireBearerV2 would do).
            ctx := context.WithValue(context.Background(), ctxKeyScope, "readonly")
            req := &mcp.CallToolRequest{}
            req.Params.Arguments = json.RawMessage(`{}`)
            result, err := h(ctx, req)
            if err != nil {
                t.Fatalf("unexpected error: %v", err)
            }
            if !result.IsError {
                t.Errorf("expected IsError=true for write tool %q with readonly scope", toolName)
            }
            if len(result.Content) == 0 {
                t.Fatalf("expected error content")
            }
            msg := result.Content[0].(*mcp.TextContent).Text
            if !strings.Contains(msg, "forbidden") {
                t.Errorf("expected 'forbidden' in error message, got: %q", msg)
            }
        })
    }
}

func TestReadonlyScopeAllowsReadTools(t *testing.T) {
    // Verify that scope="readonly" does NOT block read tools at the gate.
    // The tool call itself may fail (no real server) but IsError from scope gate = false.
    readTools := []string{"kg_get_node", "kg_list_projects", "kg_list_drafts"}
    client := &Client{baseURL: "http://127.0.0.1:19999", apiKey: "x"} // unreachable = expected error
    lih := NewLocalIndexHandler(BridgeConfig{})
    cfg := BridgeConfig{}

    for _, toolName := range readTools {
        t.Run(toolName, func(t *testing.T) {
            h := makeToolHandler(client, lih, cfg, toolName)
            ctx := context.WithValue(context.Background(), ctxKeyScope, "readonly")
            req := &mcp.CallToolRequest{}
            req.Params.Arguments = json.RawMessage(`{"id":"00000000-0000-0000-0000-000000000001","project_id":"00000000-0000-0000-0000-000000000001"}`)
            result, _ := h(ctx, req)
            if result != nil && result.IsError {
                // If it errored, make sure it's NOT the scope-gate message
                if len(result.Content) > 0 {
                    msg := result.Content[0].(*mcp.TextContent).Text
                    if strings.Contains(msg, "forbidden") {
                        t.Errorf("read tool %q should not be blocked by scope gate, got: %q", toolName, msg)
                    }
                }
            }
            // Result may be an HTTP-error (connection refused) — that's fine; scope gate must not fire.
        })
    }
}

func TestFullScopeAllowsWriteTools(t *testing.T) {
    // scope="full" must not block write tools (scope gate must not fire).
    client := &Client{baseURL: "http://127.0.0.1:19999", apiKey: "x"}
    lih := NewLocalIndexHandler(BridgeConfig{})
    cfg := BridgeConfig{}
    h := makeToolHandler(client, lih, cfg, "kg_store_decision")
    ctx := context.WithValue(context.Background(), ctxKeyScope, "full")
    req := &mcp.CallToolRequest{}
    req.Params.Arguments = json.RawMessage(`{}`)
    result, _ := h(ctx, req)
    if result != nil && result.IsError {
        if len(result.Content) > 0 {
            msg := result.Content[0].(*mcp.TextContent).Text
            if strings.Contains(msg, "forbidden") {
                t.Errorf("full-scope should not be blocked, got: %q", msg)
            }
        }
    }
}
```

- [ ] **Step 5.2: Run tests to verify they fail**

```bash
go test ./internal/bridge/ -run TestReadonlyScope -v
go test ./internal/bridge/ -run TestFullScope -v
```
Expected: FAIL — scope gate not yet implemented.

- [ ] **Step 5.3: Add scope gate to `makeToolHandler` in `serve.go`**

At the top of the `return func(ctx context.Context, req *mcp.CallToolRequest) (*mcp.CallToolResult, error)` closure, before `argsToMap`, add:

```go
// Scope enforcement lives here, not in requireBearerV2 HTTP middleware, because
// MCP Streamable HTTP routes all tool calls to a single "/" path — the tool name
// is invisible at the HTTP layer. Authentication (valid token?) happens in
// requireBearerV2; authorization (what can this token do?) is enforced here
// where toolName is known. Do NOT move this check upward.
if scope, _ := ctx.Value(ctxKeyScope).(string); scope == "readonly" {
    if route, ok := toolRoutes[toolName]; ok && route.Class != RouteRead {
        return &mcp.CallToolResult{
            Content: []mcp.Content{&mcp.TextContent{
                Text: fmt.Sprintf("forbidden: readonly credential cannot invoke write tool %q", toolName),
            }},
            IsError: true,
        }, nil
    }
    // Local tools (kg_index_source, kg_index_status) are not in toolRoutes.
    // They are blocked under readonly scope as they can mutate local state.
    if localToolNames[toolName] {
        return &mcp.CallToolResult{
            Content: []mcp.Content{&mcp.TextContent{
                Text: fmt.Sprintf("forbidden: readonly credential cannot invoke local-exec tool %q", toolName),
            }},
            IsError: true,
        }, nil
    }
}
```

- [ ] **Step 5.4: Run tests to verify they pass**

```bash
go test ./internal/bridge/ -run TestReadonlyScope -v
go test ./internal/bridge/ -run TestFullScope -v
```
Expected: all PASS.

- [ ] **Step 5.5: Run full bridge tests**

```bash
go test ./internal/bridge/... -race -count=1
```
Expected: all pass.

- [ ] **Step 5.6: Commit**

```bash
git add internal/bridge/serve.go internal/bridge/serve_http_test.go
git commit -m "feat(bridge): enforce readonly bearer scope in makeToolHandler — 403 before dispatch (IMP-008 FR-2 part B)"
```

---

## Task 6: AC Tests — All-Routes-Tagged + Profile Integrity

**Files:**
- Modify: `internal/bridge/client_test.go` (extend with route-count assertions)
- Modify: `internal/bridge/schema_test.go` (extend with profile + class cross-check)

These tests encode the acceptance criteria from IMP-008 so regressions are caught automatically.

- [ ] **Step 6.1: Add route-count AC test**

Add to `internal/bridge/client_test.go`:

```go
func TestRouteClassCounts(t *testing.T) {
    counts := map[RouteClass]int{}
    for _, route := range toolRoutes {
        counts[route.Class]++
    }
    // IMP-008 corrected counts: 12 read, 21 write, 0 local (local tools are not in toolRoutes)
    want := map[RouteClass]int{
        RouteRead:  12,
        RouteWrite: 21,
    }
    for class, wantCount := range want {
        if got := counts[class]; got != wantCount {
            t.Errorf("route class %q: got %d routes, want %d", class, got, wantCount)
        }
    }
    // Total routed = 33
    total := counts[RouteRead] + counts[RouteWrite]
    if total != 33 {
        t.Errorf("total routed routes: got %d, want 33", total)
    }
}
```

- [ ] **Step 6.2: AC-6 — verify `TestAllToolSchemasRegistered` already covers the invariant**

`schema_test.go` already has `TestAllToolSchemasRegistered` which asserts `len(schemas) == 35`. Do NOT add a duplicate `TestAllToolSchemasPresent` — it would be redundant and cause naming confusion. Instead, confirm the existing test passes after Task 2's changes (it should, since Task 2 only edits descriptions and adds MaxValue, not schemas).

No new code needed for this step — just confirm the existing test still passes:

```bash
go test ./internal/bridge/ -run TestAllToolSchemasRegistered -v
```
Expected: PASS.

- [ ] **Step 6.3: Run all new AC tests**

```bash
go test ./internal/bridge/ -run "TestRouteClassCounts|TestAllToolSchemasRegistered|TestQwen|TestProfileTool|TestKgSearchChunks" -v
```
Expected: all PASS.

- [ ] **Step 6.4: Run full test suite**

```bash
go test ./internal/bridge/... -race -count=1
make lint
```
Expected: all pass, no lint errors.

- [ ] **Step 6.5: Commit**

```bash
git add internal/bridge/client_test.go internal/bridge/schema_test.go
git commit -m "test(bridge): add IMP-008 AC tests — route counts, profile integrity, schema invariants"
```

---

## Self-Review

### Spec coverage

| Requirement | Task | Status |
|-------------|------|--------|
| FR-1: ≤2-sentence descriptions for 5 profile tools | Task 2 | ✓ |
| FR-1: default `limit` + pagination confirmed | Task 2 (verified in reading; schema tests check MaxValue) | ✓ |
| FR-1: `kg_search_chunks` MaxValue=10 enforced in schema | Task 2 | ✓ |
| FR-2: route class tag co-located with toolRoutes | Task 1 | ✓ |
| FR-2: readonly bearer scope extracted in requireBearerV2 | Task 4 | ✓ |
| FR-2: write/local routes return forbidden before dispatch | Task 5 | ✓ |
| FR-2: AC-4 all routes tagged, no untagged route | Task 1 + Task 6 | ✓ |
| FR-2: `KG_MCP_TOKEN_READONLY` env var provisioning | Task 4 startup.go | ✓ |
| FR-3: `QwenReadOnlyToolProfile` var with 6 tools | Task 3 | ✓ |
| FR-3: Phase-4 AC documented in var comment | Task 3 | ✓ |
| AC-6: 35-tool catalog unchanged for Claude callers | Task 6 | ✓ |
| `kg_end_session` classified WRITE | Task 1 | ✓ |
| `kg_list_drafts` classified READ and added to profile | Task 1 + Task 3 | ✓ |
| Enforcement in handler (not middleware) — comment | Task 5 | ✓ |
| Phase-8 migration note | Not a code task — noted in FR-3 var comment | ✓ |

### Breaking change migration (covered in plan)

| Breaking change | Existing tests affected | Fixed in |
|-----------------|------------------------|----------|
| `validateHTTPStartup` returns `(string, string, error)` instead of `(string, error)` | 3 tests in `startup_test.go` | Task 4, Step 4.4 |
| `requireBearerV2` gains second string arg (readonlyToken) | 10 call sites in `middleware_auth_test.go` | Task 4, Step 4.6 |
| `kg_search_chunks` missing from `TestAllToolSchemasRegistered.expectedTools` | Pre-existing gap in `schema_test.go` | Task 2, Step 2.5 |

### Open items NOT in scope (file as bugs/backlog)

- `kg_search_chunks` offset param has no `MinValue: intPtr(0)` (same gap as limit — separate bug).
- Session dangling under readonly scope: readonly tokens cannot call `kg_end_session` (WRITE). Sessions will TTL-expire server-side. Document in ops runbook, not in code.
- Phase-8 fine-grained per-key scopes will supersede FR-2's coarse gate. Migration path: deprecate `KG_MCP_TOKEN_READONLY` in Phase 8 and issue scoped API keys; FR-2's check in `makeToolHandler` generalises to `scope != "full" && route.Class != RouteRead`.
