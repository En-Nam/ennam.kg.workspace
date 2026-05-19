# QA/QC Strategy & Automation Framework

**Created**: 2026-04-15
**Target**: QA/QC Agent Team (test-worker, reviewer)
**Platform**: Ennam Knowledge Graph — 21 BA documents, 5 phases

---

## 1. QA Mission

Transform 743+ acceptance criteria across 21 BA documents into executable test cases. Run automated E2E tests against the live platform using Playwright MCP and Chrome DevTools MCP, then generate actionable bug reports for development teams.

## 2. Test Pyramid

| Level | Tool | Scope | Owner | Coverage Target |
|-------|------|-------|-------|----------------|
| **Unit** | Vitest (NextJS), Go test, pytest | Individual functions/components | Dev teams | 80%+ |
| **Integration** | Go test + httptest, pytest + httpx | API endpoints, service interactions | Dev teams + QA | 70%+ |
| **E2E (Browser)** | Playwright MCP + Chrome DevTools MCP | Full user flows via browser | **QA Team** | All critical paths |
| **E2E (API)** | Playwright MCP (API context) or curl | API-only flows (no UI) | **QA Team** | All endpoints |

**QA Team focuses on E2E level** — dev teams handle unit + integration.

## 3. Automation Tools

### 3.1 Playwright MCP
Primary tool for browser automation. Available tools:
- `browser_navigate(url)` — navigate to page
- `browser_click(selector)` — click element
- `browser_fill_form(selector, value)` — fill input
- `browser_type(selector, text)` — type text
- `browser_press_key(key)` — press keyboard key
- `browser_select_option(selector, value)` — select dropdown
- `browser_snapshot()` — get page accessibility tree (for assertions)
- `browser_take_screenshot()` — capture visual evidence
- `browser_wait_for(selector/url/timeout)` — wait for condition
- `browser_evaluate(script)` — run JS in page context
- `browser_console_messages()` — check console errors
- `browser_network_requests()` — inspect API calls
- `browser_tabs()` — manage browser tabs
- `browser_navigate_back()` — go back
- `browser_hover(selector)` — hover element
- `browser_drag(source, target)` — drag and drop
- `browser_file_upload(selector, paths)` — upload files
- `browser_handle_dialog(action)` — handle alert/confirm/prompt
- `browser_resize(width, height)` — resize viewport
- `browser_close()` — close browser

### 3.2 Chrome DevTools MCP
Supplementary tool for deeper inspection:
- Network waterfall analysis (latency, payload sizes)
- Performance profiling (FPS, memory, CPU)
- Console error capture
- WebSocket/SSE frame inspection
- DOM inspection for accessibility

### 3.3 Tool Selection Guide
| Scenario | Use |
|----------|-----|
| Navigate, click, fill forms, assert content | Playwright MCP |
| Check API response status/body | `browser_network_requests()` or `browser_evaluate(fetch(...))` |
| Verify SSE streaming events | Chrome DevTools (WebSocket/SSE inspector) |
| Capture visual evidence for report | `browser_take_screenshot()` |
| Check console errors after action | `browser_console_messages()` |
| Measure page load performance | Chrome DevTools Performance |
| Inspect chart rendering (Recharts) | `browser_evaluate()` to query DOM/SVG |

## 4. Test Case Structure

Each test case follows this format:

```markdown
### TC-{PHASE}-{BA}-{FR}-{SEQ}: {Title}

**BA Reference**: BA-{XXX}/FR-{YYY}/AC-{ZZZ}
**Priority**: P0 (blocker) | P1 (critical) | P2 (major) | P3 (minor)
**Type**: E2E-Browser | E2E-API | Visual | Performance
**Preconditions**: {setup required}

**Steps**:
1. {action} → expected: {result}
2. {action} → expected: {result}
3. ...

**Assertions**:
- [ ] {specific verifiable condition}
- [ ] {specific verifiable condition}

**Automation Hint**:
```
// Playwright MCP sequence
browser_navigate("http://localhost:3500/...")
browser_click("selector")
browser_snapshot() // assert content
```
```

### Test Case ID Convention
- `TC-P1-001-001-01` = Phase 1, BA-001, FR-001, test case 01
- `TC-P3-014-002-03` = Phase 3, BA-014, FR-002, test case 03

## 5. Test Execution Workflow

```
Step 1: Read test scope for target phase
        → read_memory("qa/test-scope-by-phase")

Step 2: Read relevant BA document(s)
        → read acceptance criteria (Section 3, Gherkin ACs)

Step 3: Generate test cases
        → write test cases to .serena/memories/qa/testcases/phase{N}/
        → follow TC format above

Step 4: Execute tests via Playwright MCP
        → browser_navigate to target page
        → execute test steps
        → capture screenshots for evidence
        → record pass/fail

Step 5: Generate report
        → read_memory("qa/reporting-template")
        → write report to .serena/memories/qa/reports/

Step 6: File bugs
        → for each failure, create bug entry in report
        → tag with BA ref, severity, team assignment
```

## 6. Environment

| Service | URL | Auth |
|---------|-----|------|
| Go API | http://localhost:8080 | API key or user login |
| NextJS Dashboard | http://localhost:3500 | User session (Phase 3+) |
| Python Worker | http://localhost:8081 | Internal (no direct test) |
| PostgreSQL | localhost:5433 | Direct DB queries for data setup |
| Redis | localhost:6380 | Queue inspection |

### Test User Accounts (Phase 3+)
| Username | Role | Purpose |
|----------|------|---------|
| `admin` | admin | Full access, settings, OAuth |
| `developer1` | developer | Standard project member |
| `viewer1` | viewer | Read-only access |

## 7. Test Data Setup

Before running tests, ensure:
1. Docker stack running: `docker compose up -d`
2. Migrations applied (automatic on startup)
3. Test data seeded: projects, nodes, edges
4. For Phase 2+: at least 1 data source registered with schema extracted
5. For Phase 3+: test users created (admin, developer1, viewer1)
6. For Phase 5: embeddings generated for test data source

## 8. Priority Matrix

| Priority | Definition | SLA |
|----------|-----------|-----|
| P0 — Blocker | App crashes, data loss, security breach | Fix immediately |
| P1 — Critical | Core feature broken, no workaround | Fix before release |
| P2 — Major | Feature partially broken, workaround exists | Fix in current sprint |
| P3 — Minor | UI glitch, typo, cosmetic issue | Fix when convenient |
