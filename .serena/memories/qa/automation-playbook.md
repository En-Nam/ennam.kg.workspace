# QA Automation Playbook — Step-by-Step Execution Guide

**Created**: 2026-04-15
**Usage**: QA agent follows this playbook to execute test suites

---

## Before You Start

```
1. read_memory("qa/strategy-and-framework")     → understand tools + test case format
2. read_memory("qa/test-scope-by-phase")         → know WHAT to test
3. read_memory("qa/reporting-template")          → know HOW to report
4. Verify Docker stack: browser_navigate("http://localhost:3500") → dashboard loads
5. Verify API: browser_evaluate("fetch('http://localhost:8080/health').then(r=>r.json())")
```

## Phase-by-Phase Execution

### Running Phase 1 Tests (Platform Foundation)

```
// 1. API endpoint tests (no browser needed)
browser_evaluate("fetch('http://localhost:8080/api/v1/projects', {headers:{'X-API-Key':'test-key'}}).then(r=>r.json())")
// Assert: returns array of projects

// 2. Dashboard navigation
browser_navigate("http://localhost:3500")
browser_snapshot()  // Assert: dashboard loads, sidebar visible

// 3. Search flow
browser_press_key("Meta+k")  // Cmd+K
browser_type("[role='searchbox']", "function")
browser_snapshot()  // Assert: search results appear

// 4. Graph visualization
browser_navigate("http://localhost:3500/graph")
browser_wait_for("canvas", {timeout: 5000})
browser_take_screenshot()  // Evidence: graph renders
```

### Running Phase 3 Tests (Auth — Most Critical)

```
// 1. Login flow
browser_navigate("http://localhost:3500/login")
browser_fill_form("[name='username']", "admin")
browser_fill_form("[name='password']", "admin123")
browser_click("button[type='submit']")
browser_wait_for("/dashboard", {timeout: 5000})
browser_snapshot()  // Assert: redirected to dashboard, user menu shows "admin"

// 2. Wrong password
browser_navigate("http://localhost:3500/login")
browser_fill_form("[name='username']", "admin")
browser_fill_form("[name='password']", "wrong")
browser_click("button[type='submit']")
browser_snapshot()  // Assert: error message "Invalid credentials"

// 3. Account lockout (5 attempts)
// Repeat wrong login 5 times...
browser_snapshot()  // Assert: "Account locked" message after 5th attempt

// 4. Role-based access
// Login as viewer1
browser_navigate("http://localhost:3500/projects/{id}/nodes")
browser_snapshot()  // Assert: "Create Node" button NOT visible for viewer

// 5. Session expiry check
browser_evaluate("document.cookie")  // Check maxAge = 15 days
```

### Running Phase 4 Tests (AI Query UX)

```
// 1. Create conversation thread
browser_navigate("http://localhost:3500/ai-query")
browser_click("[data-testid='new-thread']")
browser_fill_form("[data-testid='thread-name']", "Test Thread")
browser_click("[data-testid='create-thread']")
browser_snapshot()  // Assert: thread appears in sidebar

// 2. Send query with streaming
browser_fill_form("[data-testid='query-input']", "How many orders per month?")
browser_click("[data-testid='send-query']")
// Wait for streaming to complete
browser_wait_for("[data-testid='response-complete']", {timeout: 10000})
browser_take_screenshot()  // Evidence: response with chart/table

// 3. Verify first token latency
// Use Chrome DevTools to inspect SSE timing
// Or: browser_evaluate to measure time from send to first content

// 4. Chart interactions
browser_hover("[data-testid='chart'] .recharts-bar")  // Hover bar
browser_snapshot()  // Assert: tooltip shows data values

// 5. Tool menu
browser_click("[data-testid='tool-export-csv']")
// Assert: file download triggered
browser_click("[data-testid='tool-explain']")
browser_wait_for("[data-testid='explanation-content']")
browser_snapshot()  // Assert: markdown explanation rendered

// 6. Quick action buttons
browser_snapshot()  // Assert: 3 suggested action buttons visible
browser_click("[data-testid='quick-action-0']")  // Click first suggestion
browser_wait_for("[data-testid='response-complete']", {timeout: 10000})
// Assert: new query sent and response received

// 7. Insights
browser_snapshot()  // Assert: insight cards with confidence badges visible
// Count insights: at least 1 per response
```

## Common Assertion Patterns

### Assert element exists
```
browser_snapshot()
// Check snapshot output for expected text/element
```

### Assert API response
```
browser_evaluate("fetch('/api/v1/...', {headers:{...}}).then(r=>({status:r.status,body:r.json()}))")
```

### Assert no console errors
```
browser_console_messages()
// Check: no "Error" level messages
```

### Assert network request succeeded
```
browser_network_requests()
// Check: target API call returned 200/201
```

### Assert element NOT visible (negative test)
```
browser_snapshot()
// Verify expected element is NOT in accessibility tree
```

### Measure timing
```
browser_evaluate(`
  const start = Date.now();
  // ... trigger action ...
  // ... wait for result ...
  const elapsed = Date.now() - start;
  return elapsed;
`)
// Assert: elapsed < target_ms
```

## After Test Execution

1. Count pass/fail/skip
2. For each failure: capture screenshot + console + network evidence
3. Write report using template: `write_memory("qa/reports/phase{N}-{date}-e2e", report_content)`
4. If P0/P1 bugs found: immediately notify in report summary
5. Update test case status in testcase memory (if maintained)

## Tips for QA Agents

- **Always `browser_snapshot()` before assertions** — the snapshot is your source of truth
- **Use `browser_take_screenshot()` for ALL failures** — visual evidence is critical
- **Check `browser_console_messages()` after page loads** — catch silent JS errors
- **Use `browser_network_requests()` to verify API calls** — UI might hide API errors
- **Test negative cases** — wrong input, unauthorized access, empty states
- **Test edge cases** — empty lists, very long text, special characters, concurrent actions
- **Don't assume DOM selectors** — use `browser_snapshot()` first to discover available elements, then use the accessibility tree selectors
