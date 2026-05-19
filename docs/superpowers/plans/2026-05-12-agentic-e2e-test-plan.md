# Agentic AI Chat Engine — E2E Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a 3-layer E2E test suite (API smoke tests, browser E2E via Chrome DevTools MCP, accuracy evaluation) for the Agentic AI Chat Engine.

**Architecture:** Python pytest scripts hit the Go API directly on `:8080` for Layers 1 and 3. Layer 2 is a structured playbook for an AI agent to execute via Chrome DevTools MCP tools against the NextJS dashboard on `:3500`. All tests run against a Docker Compose stack rebuilt with latest code.

**Tech Stack:** Python 3.12, pytest, httpx (sync streaming), Chrome DevTools MCP, Docker Compose

---

## File Structure

```
tests/e2e/
├── requirements.txt          # httpx, pytest, pytest-timeout
├── pytest.ini                # pytest config (timeout defaults, markers)
├── conftest.py               # Session fixtures: auth, client, project_id, data_source_id
├── helpers/
│   ├── __init__.py
│   ├── auth.py               # login() → api_key + user dict
│   ├── sse.py                # SSEEvent dataclass + parse_sse_stream() generator
│   └── health.py             # wait_for_services() → blocks until all healthy
├── test_api_smoke.py         # Layer 1: 6 API smoke tests (API-01 to API-06)
├── test_accuracy.py          # Layer 3: 12 accuracy evaluation tests (ACC-01 to ACC-12)
├── browser_playbook.md       # Layer 2: Chrome DevTools MCP playbook (UI-01 to UI-08)
└── run_tests.sh              # Full test runner: Docker rebuild → health check → pytest
```

---

### Task 1: E2E Test Infrastructure

**Files:**
- Create: `tests/e2e/requirements.txt`
- Create: `tests/e2e/pytest.ini`
- Create: `tests/e2e/helpers/__init__.py`
- Create: `tests/e2e/helpers/auth.py`
- Create: `tests/e2e/helpers/sse.py`
- Create: `tests/e2e/helpers/health.py`
- Create: `tests/e2e/conftest.py`

- [ ] **Step 1: Create directory structure and requirements.txt**

```bash
mkdir -p tests/e2e/helpers
```

Write `tests/e2e/requirements.txt`:

```
httpx>=0.28
pytest>=8.3
pytest-timeout>=2.3
```

- [ ] **Step 2: Create pytest.ini**

Write `tests/e2e/pytest.ini`:

```ini
[pytest]
timeout = 600
markers =
    quick_tier: Tests using Quick tier (5 min timeout)
    deep_tier: Tests using Deep tier (10 min timeout)
    accuracy: Accuracy evaluation tests
    smoke: API smoke tests
```

- [ ] **Step 3: Create helpers/auth.py**

Write `tests/e2e/helpers/auth.py`:

```python
"""Authentication helper — login via Go API and return API key."""

from __future__ import annotations

import httpx

GO_API_URL = "http://localhost:8080"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Admin123!@#"


def login(
    base_url: str = GO_API_URL,
    username: str = ADMIN_USERNAME,
    password: str = ADMIN_PASSWORD,
) -> tuple[str, dict]:
    """Login to Go API and return (api_key, user_dict).

    Raises httpx.HTTPStatusError on auth failure.
    """
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["api_key"], data["user"]
```

- [ ] **Step 4: Create helpers/sse.py**

Write `tests/e2e/helpers/sse.py`:

```python
"""SSE stream parser for httpx streaming responses."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Generator

import httpx


@dataclass
class SSEEvent:
    """A single Server-Sent Event."""

    event: str
    data: dict = field(default_factory=dict)
    raw: str = ""


def parse_sse_stream(response: httpx.Response) -> Generator[SSEEvent, None, None]:
    """Parse SSE events from an httpx streaming response.

    Yields SSEEvent for each complete event (blank line delimiter).
    Handles the standard SSE format:
        event: <type>
        data: <json>
        <blank line>
    """
    event_type = ""
    data_lines: list[str] = []

    for line in response.iter_lines():
        if line.startswith("event:"):
            event_type = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
        elif line == "" and event_type:
            raw = "\n".join(data_lines)
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                data = {"raw": raw}
            yield SSEEvent(event=event_type, data=data, raw=raw)
            event_type = ""
            data_lines = []


def collect_sse_events(
    client: httpx.Client,
    body: dict,
    endpoint: str = "/api/v1/ai-query/stream",
) -> list[SSEEvent]:
    """Send a streaming POST request and collect all SSE events.

    Returns the full list of events after the stream completes.
    Raises httpx.HTTPStatusError on non-2xx response.
    """
    events: list[SSEEvent] = []
    with client.stream("POST", endpoint, json=body) as resp:
        if resp.status_code != 200:
            resp.read()
            resp.raise_for_status()
        for sse in parse_sse_stream(resp):
            events.append(sse)
    return events
```

- [ ] **Step 5: Create helpers/health.py**

Write `tests/e2e/helpers/health.py`:

```python
"""Docker health check — wait for all services to be ready."""

from __future__ import annotations

import sys
import time

import httpx

SERVICES = [
    ("kg-server", "http://localhost:8080/healthz"),
    ("indexer", "http://localhost:8081/healthz"),
    ("dashboard", "http://localhost:3500"),
]

MAX_WAIT_SECONDS = 120
POLL_INTERVAL = 5


def check_service(name: str, url: str) -> bool:
    """Check if a single service is healthy."""
    try:
        resp = httpx.get(url, timeout=5.0)
        return resp.status_code == 200
    except httpx.ConnectError:
        return False
    except httpx.ReadTimeout:
        return False


def wait_for_services() -> bool:
    """Block until all services are healthy or timeout is reached.

    Returns True if all services are healthy, False on timeout.
    """
    start = time.time()
    while time.time() - start < MAX_WAIT_SECONDS:
        results = {name: check_service(name, url) for name, url in SERVICES}
        if all(results.values()):
            print(f"All services healthy after {time.time() - start:.0f}s")
            return True
        unhealthy = [name for name, ok in results.items() if not ok]
        print(f"Waiting for: {', '.join(unhealthy)}")
        time.sleep(POLL_INTERVAL)
    print(f"Timeout after {MAX_WAIT_SECONDS}s — services not ready")
    return False


if __name__ == "__main__":
    ok = wait_for_services()
    sys.exit(0 if ok else 1)
```

- [ ] **Step 6: Create helpers/__init__.py**

Write `tests/e2e/helpers/__init__.py`:

```python
"""E2E test helpers."""

from helpers.auth import login
from helpers.health import wait_for_services
from helpers.sse import SSEEvent, collect_sse_events, parse_sse_stream

__all__ = [
    "SSEEvent",
    "collect_sse_events",
    "login",
    "parse_sse_stream",
    "wait_for_services",
]
```

- [ ] **Step 7: Create conftest.py with session fixtures**

Write `tests/e2e/conftest.py`:

```python
"""Shared fixtures for E2E tests.

Session-scoped fixtures authenticate once, discover the project and
data source, then provide a pre-configured httpx client for all tests.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from helpers.auth import login

GO_API_URL = "http://localhost:8080"


@pytest.fixture(scope="session")
def api_key() -> str:
    """Login as admin and return the API key."""
    key, _ = login()
    return key


@pytest.fixture(scope="session")
def admin_user() -> dict:
    """Login as admin and return the user dict."""
    _, user = login()
    return user


@pytest.fixture(scope="session")
def client(api_key: str) -> httpx.Client:
    """Pre-authenticated httpx client with 10-minute read timeout."""
    with httpx.Client(
        base_url=GO_API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0),
    ) as c:
        yield c


@pytest.fixture(scope="session")
def project_id(client: httpx.Client) -> str:
    """Discover the first available project ID."""
    resp = client.get("/api/v1/projects")
    resp.raise_for_status()
    projects = resp.json()
    assert len(projects) > 0, "No projects found — create one before running E2E tests"
    return projects[0]["id"]


@pytest.fixture(scope="session")
def data_source_id(client: httpx.Client, project_id: str) -> str:
    """Find the C4K Staging MSSQL data source ID."""
    resp = client.get("/api/v1/data-sources", params={"project_id": project_id})
    resp.raise_for_status()
    sources = resp.json()
    c4k = [
        s
        for s in sources
        if "c4k" in s["name"].lower() or "staging" in s["name"].lower()
    ]
    assert len(c4k) > 0, (
        f"C4K Staging data source not found. "
        f"Available: {[s['name'] for s in sources]}"
    )
    return c4k[0]["id"]


@pytest.fixture()
def thread_id(client: httpx.Client, project_id: str) -> str:
    """Create a fresh thread for each test, delete after."""
    resp = client.post(
        "/api/v1/threads",
        json={"project_id": project_id, "name": f"e2e-test-{uuid.uuid4().hex[:8]}"},
    )
    resp.raise_for_status()
    tid = resp.json()["id"]
    yield tid
    # Cleanup
    client.delete(f"/api/v1/threads/{tid}")
```

- [ ] **Step 8: Verify infrastructure by running pytest --collect-only**

```bash
cd tests/e2e
pip install -r requirements.txt
pytest --collect-only
```

Expected: `no tests ran` (no test files yet), but no import errors.

- [ ] **Step 9: Commit**

```bash
git add tests/e2e/
git commit -m "test(e2e): add test infrastructure — auth, SSE parser, health check, conftest"
```

---

### Task 2: Layer 1 — API Smoke Tests

**Files:**
- Create: `tests/e2e/test_api_smoke.py`

**Dependencies:** Task 1 (helpers and conftest)

- [ ] **Step 1: Write test_api_smoke.py with all 6 test cases**

Write `tests/e2e/test_api_smoke.py`:

```python
"""Layer 1 — API Smoke Tests (API-01 through API-06).

Direct HTTP requests to the Go API on :8080. Validates SSE event
contracts, tier routing, SQL security, clarification flow, and error handling.

All tests use the agentic streaming endpoint:
  POST /api/v1/ai-query/stream
Go routes to Python's /api/v1/agentic/stream when tier is set.
"""

from __future__ import annotations

import re
import uuid

import httpx
import pytest

from helpers.sse import SSEEvent, collect_sse_events, parse_sse_stream


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DDL_DML_PATTERN = re.compile(
    r"\b(DROP|ALTER|INSERT|UPDATE|DELETE|TRUNCATE|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


def get_events_by_type(events: list[SSEEvent], event_type: str) -> list[SSEEvent]:
    return [e for e in events if e.event == event_type]


def get_tool_calls(events: list[SSEEvent]) -> list[dict]:
    """Extract tool call start/end pairs from event list."""
    starts = get_events_by_type(events, "tool_call_start")
    return [s.data for s in starts]


# ---------------------------------------------------------------------------
# API-01: Quick Tier SSE Event Sequence
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.quick_tier
@pytest.mark.timeout(300)
def test_api_01_quick_tier_sse_event_sequence(
    client: httpx.Client,
    thread_id: str,
    data_source_id: str,
    project_id: str,
):
    """Quick tier produces correct SSE event sequence with budget limits."""
    body = {
        "thread_id": thread_id,
        "query": "What tables exist in C4K Staging?",
        "tier": "quick",
        "data_source_id": data_source_id,
        "project_id": project_id,
    }
    events = collect_sse_events(client, body)
    event_types = [e.event for e in events]

    # Must start with agent_start
    assert event_types[0] == "agent_start", f"First event should be agent_start, got {event_types[0]}"

    # Must contain tool calls
    assert "tool_call_start" in event_types, "No tool_call_start events"
    assert "tool_call_end" in event_types, "No tool_call_end events"

    # Must contain content
    assert "content" in event_types, "No content events"

    # Must end with done
    assert event_types[-1] == "done", f"Last event should be done, got {event_types[-1]}"

    # agent_done must appear before done
    assert "agent_done" in event_types, "No agent_done event"
    agent_done_idx = event_types.index("agent_done")
    done_idx = event_types.index("done")
    assert agent_done_idx < done_idx, "agent_done must come before done"

    # Check agent_start data
    start_data = events[0].data
    assert start_data["tier"] == "quick"
    assert start_data["max_iterations"] == 3

    # Check agent_done data — budget limits
    agent_done = get_events_by_type(events, "agent_done")[0].data
    assert agent_done["iterations"] <= 3, f"Quick tier exceeded 3 iterations: {agent_done['iterations']}"
    assert agent_done["total_tokens"] <= 30000, f"Quick tier exceeded 30K tokens: {agent_done['total_tokens']}"

    # Tool calls must be paired (each start has a matching end)
    starts = get_events_by_type(events, "tool_call_start")
    ends = get_events_by_type(events, "tool_call_end")
    assert len(starts) == len(ends), f"Mismatched tool call pairs: {len(starts)} starts, {len(ends)} ends"


# ---------------------------------------------------------------------------
# API-02: Deep Tier Extended Exploration
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.deep_tier
@pytest.mark.timeout(600)
def test_api_02_deep_tier_extended_exploration(
    client: httpx.Client,
    thread_id: str,
    data_source_id: str,
    project_id: str,
):
    """Deep tier allows more iterations and produces richer responses."""
    body = {
        "thread_id": thread_id,
        "query": (
            "Analyze the relationships between Customer, Order, and Product "
            "tables in C4K Staging. What are the foreign keys and how do they connect?"
        ),
        "tier": "deep",
        "data_source_id": data_source_id,
        "project_id": project_id,
    }
    events = collect_sse_events(client, body)
    event_types = [e.event for e in events]

    # Basic structure
    assert event_types[0] == "agent_start"
    assert event_types[-1] == "done"

    # agent_start shows deep tier config
    start_data = events[0].data
    assert start_data["tier"] == "deep"
    assert start_data["max_iterations"] == 12

    # Should have tool calls
    tool_starts = get_events_by_type(events, "tool_call_start")
    assert len(tool_starts) >= 2, f"Deep tier should use multiple tools, got {len(tool_starts)}"

    # Check tools used include schema inspection
    tools_used = [t.data.get("tool", "") for t in tool_starts]
    schema_tools = [t for t in tools_used if t in ("get_table_schema", "search_kg", "get_neighbors")]
    assert len(schema_tools) > 0, f"Expected schema inspection tools, got: {tools_used}"

    # agent_done present
    agent_done_events = get_events_by_type(events, "agent_done")
    assert len(agent_done_events) == 1
    agent_done = agent_done_events[0].data
    assert agent_done["iterations"] <= 12


# ---------------------------------------------------------------------------
# API-03: SQL Security — DDL Rejection
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.quick_tier
@pytest.mark.timeout(300)
def test_api_03_ddl_rejection(
    client: httpx.Client,
    thread_id: str,
    data_source_id: str,
    project_id: str,
):
    """DDL/DML statements are never executed — agent refuses gracefully."""
    body = {
        "thread_id": thread_id,
        "query": "Drop the Users table",
        "tier": "quick",
        "data_source_id": data_source_id,
        "project_id": project_id,
    }
    events = collect_sse_events(client, body)

    # Check no tool_call_end contains DDL/DML SQL
    tool_ends = get_events_by_type(events, "tool_call_end")
    for te in tool_ends:
        summary = te.data.get("summary", "")
        assert not DDL_DML_PATTERN.search(summary), (
            f"DDL/DML detected in tool_call_end summary: {summary[:200]}"
        )

    # Check tool_call_start inputs for execute_sql don't contain DDL
    tool_starts = get_events_by_type(events, "tool_call_start")
    for ts in tool_starts:
        if ts.data.get("tool") == "execute_sql":
            sql = ts.data.get("input", {}).get("sql", "")
            assert not DDL_DML_PATTERN.search(sql), (
                f"DDL/DML detected in execute_sql input: {sql[:200]}"
            )

    # Content should explain refusal or simply not execute destructive SQL
    content_events = get_events_by_type(events, "content")
    assert len(content_events) > 0, "Expected content response explaining refusal"

    # Stream should complete cleanly
    assert events[-1].event == "done"


# ---------------------------------------------------------------------------
# API-04: SQL Security — SELECT Enforcement
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.quick_tier
@pytest.mark.timeout(300)
def test_api_04_select_enforcement(
    client: httpx.Client,
    thread_id: str,
    data_source_id: str,
    project_id: str,
):
    """Only SELECT/WITH statements are executed — results are returned."""
    body = {
        "thread_id": thread_id,
        "query": "Show me the first 5 customers from C4K Staging",
        "tier": "quick",
        "data_source_id": data_source_id,
        "project_id": project_id,
    }
    events = collect_sse_events(client, body)
    event_types = [e.event for e in events]

    # Should have execute_sql tool call
    tool_starts = get_events_by_type(events, "tool_call_start")
    sql_calls = [t for t in tool_starts if t.data.get("tool") == "execute_sql"]
    assert len(sql_calls) > 0, f"Expected execute_sql tool call. Tools used: {[t.data.get('tool') for t in tool_starts]}"

    # Verify SQL is SELECT or WITH
    for call in sql_calls:
        sql = call.data.get("input", {}).get("sql", "").strip()
        assert sql != "", "execute_sql called with empty SQL"
        first_keyword = sql.split()[0].upper()
        assert first_keyword in ("SELECT", "WITH"), f"SQL must start with SELECT/WITH, got: {first_keyword}"
        assert len(sql) <= 5000, f"SQL exceeds 5000 char limit: {len(sql)} chars"

    # Tool should succeed
    tool_ends = get_events_by_type(events, "tool_call_end")
    sql_ends = [t for t in tool_ends if t.data.get("tool") == "execute_sql"]
    assert len(sql_ends) > 0
    for end in sql_ends:
        assert end.data.get("success") is True, f"execute_sql failed: {end.data.get('summary', '')}"

    # Stream completes
    assert events[-1].event == "done"


# ---------------------------------------------------------------------------
# API-05: Clarification Pause/Resume
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.deep_tier
@pytest.mark.timeout(600)
def test_api_05_clarification_pause_resume(
    client: httpx.Client,
    thread_id: str,
    data_source_id: str,
    project_id: str,
):
    """Ambiguous query triggers clarification; resume produces answer.

    NOTE: This test is LLM-dependent. If the agent does not request
    clarification, the test passes with a skip note (acceptable behavior).
    """
    body = {
        "thread_id": thread_id,
        "query": "Show me the data",
        "tier": "deep",
        "data_source_id": data_source_id,
        "project_id": project_id,
    }
    events = collect_sse_events(client, body)

    # Check if clarification was requested
    clarifications = get_events_by_type(events, "clarification_request")
    if len(clarifications) == 0:
        pytest.skip("LLM did not request clarification — acceptable behavior")

    # Clarification event should have session_id
    clar_data = clarifications[0].data
    session_id = clar_data.get("session_id", "")
    assert session_id != "", "clarification_request missing session_id"
    assert clar_data.get("question", "") != "", "clarification_request missing question"
    assert clar_data.get("timeout_seconds", 0) == 600

    # Done event should indicate awaiting_clarification
    done_events = get_events_by_type(events, "done")
    assert len(done_events) == 1
    assert done_events[0].data.get("status") == "awaiting_clarification"

    # Step 2: Resume via clarification endpoint
    clar_resp = client.post(
        "/api/v1/ai/clarification",
        json={
            "thread_id": thread_id,
            "session_id": session_id,
            "response": "Show me the top 10 customers by order count from C4K Staging",
        },
    )
    clar_resp.raise_for_status()
    clar_result = clar_resp.json()
    assert clar_result.get("status") == "ok"

    # Step 3: Resume stream with clarification_session_id
    resume_body = {
        "thread_id": thread_id,
        "query": "Show me the top 10 customers by order count from C4K Staging",
        "tier": "deep",
        "data_source_id": data_source_id,
        "project_id": project_id,
        "clarification_session_id": session_id,
    }
    resume_events = collect_sse_events(client, resume_body)
    resume_types = [e.event for e in resume_events]

    # Resumed stream should produce content and complete
    assert "content" in resume_types, "Resumed stream should produce content"
    assert resume_types[-1] == "done"
    resume_done = get_events_by_type(resume_events, "done")[0]
    assert resume_done.data.get("status") == "complete"


# ---------------------------------------------------------------------------
# API-06: Error Handling — Invalid Data Source
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.quick_tier
@pytest.mark.timeout(60)
def test_api_06_invalid_data_source(
    client: httpx.Client,
    thread_id: str,
    project_id: str,
):
    """Invalid data source ID produces clean error — no crash or hang."""
    fake_ds_id = str(uuid.uuid4())
    body = {
        "thread_id": thread_id,
        "query": "Show me all tables",
        "tier": "quick",
        "data_source_id": fake_ds_id,
        "project_id": project_id,
    }

    # May return HTTP error or SSE error event — either is acceptable
    try:
        with client.stream("POST", "/api/v1/ai-query/stream", json=body) as resp:
            if resp.status_code >= 400:
                # HTTP-level error — acceptable
                resp.read()
                assert resp.status_code in (400, 404, 422), (
                    f"Expected 4xx error, got {resp.status_code}"
                )
                return

            # If 200, check for error event in SSE stream
            events = list(parse_sse_stream(resp))
            event_types = [e.event for e in events]

            # Stream should contain an error or complete without crashing
            has_error = "error" in event_types
            has_done = "done" in event_types
            assert has_error or has_done, (
                f"Stream should contain error or done event. Got: {event_types}"
            )
    except httpx.ReadTimeout:
        pytest.fail("Request hung — connection not properly closed on invalid data source")
```

- [ ] **Step 2: Run a quick syntax check**

```bash
cd tests/e2e
python -c "import ast; ast.parse(open('test_api_smoke.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 3: Run pytest --collect-only to verify test discovery**

```bash
cd tests/e2e
pytest --collect-only test_api_smoke.py
```

Expected: 6 tests collected (test_api_01 through test_api_06).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_api_smoke.py
git commit -m "test(e2e): add Layer 1 API smoke tests — 6 tests for SSE events, SQL security, clarification"
```

---

### Task 3: Layer 2 — Browser E2E Playbook

**Files:**
- Create: `tests/e2e/browser_playbook.md`

**Dependencies:** None (this is documentation for agent-driven execution)

- [ ] **Step 1: Write the Chrome DevTools MCP playbook**

Write `tests/e2e/browser_playbook.md`:

````markdown
# Layer 2 — Browser E2E Playbook (Chrome DevTools MCP)

This playbook is executed by an AI agent using Chrome DevTools MCP tools
against the NextJS dashboard at `http://localhost:3500`.

**Prerequisites:** Docker services healthy, migration 000044 applied, admin account exists.

---

## Setup

Before starting, open a browser page:

```
Tool: new_page
URL: http://localhost:3500
```

Then start monitoring console messages:

```
Tool: list_console_messages
```

---

## UI-01: Login & Navigation to Chat

**Steps:**

1. Navigate to login page:
   ```
   Tool: navigate_page
   URL: http://localhost:3500/login
   ```

2. Take screenshot to see the login form:
   ```
   Tool: take_screenshot
   ```

3. Fill in the login form:
   ```
   Tool: fill_form
   Fields:
     - selector: input[name="username"], value: "admin"
     - selector: input[name="password"], value: "Admin123!@#"
   ```

4. Click the login button:
   ```
   Tool: click
   Selector: button[type="submit"]
   ```

5. Wait for navigation to complete:
   ```
   Tool: wait_for
   Selector: nav  (or any dashboard element)
   Timeout: 10000
   ```

6. Navigate to chat page:
   ```
   Tool: navigate_page
   URL: http://localhost:3500/chat
   ```

7. Take screenshot:
   ```
   Tool: take_screenshot
   ```

**Pass criteria:**
- [ ] Chat page renders (screenshot shows QueryInputBar)
- [ ] TierSelector visible (Quick/Deep toggle buttons)
- [ ] No error messages in console (`list_console_messages`)

---

## UI-02: TierSelector Toggle + Persistence

**Steps:**

1. Click the "Deep" button in TierSelector:
   ```
   Tool: click
   Selector: [data-tier="deep"]  (or button containing text "Deep")
   ```

2. Take screenshot — verify Deep is selected:
   ```
   Tool: take_screenshot
   ```

3. Check localStorage for persistence:
   ```
   Tool: evaluate_script
   Expression: localStorage.getItem('agentic-tier')
   ```
   Expected result: `"deep"`

4. Reload the page:
   ```
   Tool: navigate_page
   URL: http://localhost:3500/chat
   ```

5. Take screenshot — Deep should still be selected:
   ```
   Tool: take_screenshot
   ```

6. Verify localStorage survived reload:
   ```
   Tool: evaluate_script
   Expression: localStorage.getItem('agentic-tier')
   ```
   Expected: `"deep"`

7. Click "Quick" to switch back:
   ```
   Tool: click
   Selector: [data-tier="quick"]  (or button containing text "Quick")
   ```

8. Verify:
   ```
   Tool: evaluate_script
   Expression: localStorage.getItem('agentic-tier')
   ```
   Expected: `"quick"`

**Pass criteria:**
- [ ] Visual toggle works (screenshots show selection change)
- [ ] localStorage key `agentic-tier` persists correct value
- [ ] Selection survives page reload

---

## UI-03: Quick Tier — Streaming Response

**Steps:**

1. Ensure Quick tier is selected (from UI-02)

2. Type query into input:
   ```
   Tool: fill
   Selector: textarea  (or the QueryInputBar input element)
   Value: "What tables are in C4K Staging?"
   ```

3. Submit (press Enter or click send button):
   ```
   Tool: press_key
   Key: Enter
   ```

4. Wait 5 seconds for streaming to start, then take screenshot:
   ```
   Tool: wait_for
   Selector: [data-testid="agentic-progress"]  (or look for the AgenticProgress component)
   Timeout: 30000
   ```
   ```
   Tool: take_screenshot
   ```

5. Wait for response to complete (up to 5 minutes):
   ```
   Tool: wait_for
   Selector: [data-testid="agent-done"]  (or look for the completed state)
   Timeout: 300000
   ```

6. Take final screenshot:
   ```
   Tool: take_screenshot
   ```

7. Check console for errors:
   ```
   Tool: list_console_messages
   ```

**Pass criteria:**
- [ ] AgenticProgress component appeared during streaming
- [ ] PhaseIndicator showed a phase label
- [ ] ToolCallStepRow entries visible for tool calls
- [ ] Final answer rendered in ChatMessage
- [ ] No unhandled errors in console

---

## UI-04: Deep Tier — Extended Streaming

**Steps:**

1. Set TierSelector to Deep:
   ```
   Tool: click
   Selector: [data-tier="deep"]
   ```

2. Submit query:
   ```
   Tool: fill
   Selector: textarea
   Value: "Analyze the Customer table schema and show me the top 5 customers by order count"
   ```
   ```
   Tool: press_key
   Key: Enter
   ```

3. Wait 10 seconds, take screenshot (mid-stream):
   ```
   Tool: take_screenshot
   ```

4. Wait 30 seconds, take another screenshot:
   ```
   Tool: take_screenshot
   ```

5. Wait for completion (up to 10 minutes):
   ```
   Tool: wait_for
   Selector: [data-testid="agent-done"]
   Timeout: 600000
   ```

6. Take final screenshot:
   ```
   Tool: take_screenshot
   ```

**Pass criteria:**
- [ ] More tool call steps visible than UI-03 (Quick)
- [ ] AgenticProgress shows multiple iterations
- [ ] KgNodeChip badges appear if KG nodes referenced
- [ ] Response completes within 10 minutes
- [ ] No console errors

---

## UI-05: KgNodeChip Display

**Steps:**

1. Set tier to Quick

2. Submit query:
   ```
   Tool: fill
   Selector: textarea
   Value: "What architecture nodes exist in the knowledge graph?"
   ```
   ```
   Tool: press_key
   Key: Enter
   ```

3. Wait for completion:
   ```
   Tool: wait_for
   Selector: [data-testid="agent-done"]
   Timeout: 300000
   ```

4. Take screenshot of the response:
   ```
   Tool: take_screenshot
   ```

5. Check for KgNodeChip elements:
   ```
   Tool: evaluate_script
   Expression: document.querySelectorAll('[data-testid="kg-node-chip"]').length
   ```

**Pass criteria:**
- [ ] KgNodeChip components render as colored pill badges
- [ ] Chips show node labels
- [ ] Chips are visually distinct (different colors by node type)

**Note:** If KG has no architecture nodes, chips may not appear. Check if content references KG nodes. If no nodes in KG, mark as SKIP.

---

## UI-06: Error Resilience — Network Interruption

**Steps:**

1. Set tier to Deep

2. Submit a query:
   ```
   Tool: fill
   Selector: textarea
   Value: "List all tables in C4K Staging with their column counts"
   ```
   ```
   Tool: press_key
   Key: Enter
   ```

3. Wait for streaming to start (first tool call):
   ```
   Tool: wait_for
   Selector: [data-testid="tool-call-step"]
   Timeout: 60000
   ```

4. Simulate offline mode:
   ```
   Tool: emulate
   Options: { "offline": true }
   ```

5. Wait 3 seconds:
   ```
   Tool: take_screenshot
   ```

6. Restore network:
   ```
   Tool: emulate
   Options: { "offline": false }
   ```

7. Take screenshot after reconnect:
   ```
   Tool: take_screenshot
   ```

8. Check console for unhandled errors:
   ```
   Tool: list_console_messages
   ```

9. Verify can submit new query:
   ```
   Tool: fill
   Selector: textarea
   Value: "test"
   ```
   Verify input field accepts text (no frozen UI).

**Pass criteria:**
- [ ] UI shows error state, not blank screen or infinite spinner
- [ ] User can interact with the page after reconnect
- [ ] No unhandled exceptions in console (ERR_NETWORK is expected)

---

## UI-07: Chat History Persistence

**Steps:**

1. Note the current URL (should be `/chat/<threadId>` from previous tests):
   ```
   Tool: evaluate_script
   Expression: window.location.pathname
   ```
   Save this as `threadUrl`.

2. Navigate away:
   ```
   Tool: navigate_page
   URL: http://localhost:3500/graph
   ```

3. Navigate back to the thread:
   ```
   Tool: navigate_page
   URL: http://localhost:3500<threadUrl>
   ```

4. Wait for messages to load:
   ```
   Tool: wait_for
   Selector: [data-testid="chat-message"]
   Timeout: 10000
   ```

5. Take screenshot:
   ```
   Tool: take_screenshot
   ```

6. Check that previous messages are visible:
   ```
   Tool: evaluate_script
   Expression: document.querySelectorAll('[data-testid="chat-message"]').length
   ```
   Expected: > 0

**Pass criteria:**
- [ ] Previous messages render correctly
- [ ] Agentic metadata visible in historical messages
- [ ] QueryInputBar ready for new input

---

## UI-08: Network Request Inspection

**Steps:**

1. Set tier to Quick

2. Clear previous network data and start fresh monitoring:
   ```
   Tool: list_network_requests
   ```

3. Submit a query:
   ```
   Tool: fill
   Selector: textarea
   Value: "How many tables are in C4K Staging?"
   ```
   ```
   Tool: press_key
   Key: Enter
   ```

4. Wait for completion:
   ```
   Tool: wait_for
   Selector: [data-testid="agent-done"]
   Timeout: 300000
   ```

5. Inspect network requests:
   ```
   Tool: list_network_requests
   ```

6. Find the SSE request and inspect it:
   ```
   Tool: get_network_request
   URL pattern: "ai-query/stream" or "agentic/stream"
   ```

**Pass criteria:**
- [ ] SSE request visible in network log
- [ ] Request URL contains `/api/kg/` (BFF proxy path)
- [ ] Request body includes `"tier"` field
- [ ] Response content-type is `text/event-stream`
- [ ] No failed requests (no 4xx/5xx except intentional ones)

---

## Results Summary Template

| Test | Status | Notes |
|------|--------|-------|
| UI-01 | PASS / FAIL / SKIP | |
| UI-02 | PASS / FAIL / SKIP | |
| UI-03 | PASS / FAIL / SKIP | |
| UI-04 | PASS / FAIL / SKIP | |
| UI-05 | PASS / FAIL / SKIP | |
| UI-06 | PASS / FAIL / SKIP | |
| UI-07 | PASS / FAIL / SKIP | |
| UI-08 | PASS / FAIL / SKIP | |

**Screenshots saved to:** `docs/superpowers/test-results/browser-e2e/`
````

- [ ] **Step 2: Commit**

```bash
git add tests/e2e/browser_playbook.md
git commit -m "test(e2e): add Layer 2 browser E2E playbook — 8 Chrome DevTools MCP test cases"
```

---

### Task 4: Layer 3 — Accuracy Evaluation

**Files:**
- Create: `tests/e2e/test_accuracy.py`

**Dependencies:** Task 1 (helpers and conftest)

- [ ] **Step 1: Write test_accuracy.py with all 12 test cases**

Write `tests/e2e/test_accuracy.py`:

```python
"""Layer 3 — Accuracy Evaluation (ACC-01 through ACC-12).

Sends agentic queries via the API and captures responses for scoring.
Each test extracts content, tool calls, and metadata, then prints a
structured report for manual 0-3 rubric scoring.

Automated checks verify basic correctness (non-empty response, no errors).
The 0-3 score is assigned by reviewing the printed output.

Run with: pytest test_accuracy.py -v -s  (use -s to see printed reports)
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass

import httpx
import pytest

from helpers.sse import SSEEvent, collect_sse_events


# ---------------------------------------------------------------------------
# Scoring infrastructure
# ---------------------------------------------------------------------------

RESULTS: list[dict] = []


@dataclass
class AccuracyResult:
    """Structured result from an accuracy test case."""

    case_id: str
    category: str
    tier: str
    query: str
    content: str
    tools_used: list[str]
    iterations: int
    total_tokens: int
    has_error: bool
    error_detail: str = ""

    def print_report(self) -> None:
        """Print a formatted report for manual scoring."""
        border = "=" * 70
        print(f"\n{border}")
        print(f"  {self.case_id} | {self.category} | Tier: {self.tier}")
        print(f"{border}")
        print(f"  Query: {self.query}")
        print(f"  Tools: {', '.join(self.tools_used) or 'none'}")
        print(f"  Iterations: {self.iterations} | Tokens: {self.total_tokens}")
        if self.has_error:
            print(f"  ERROR: {self.error_detail}")
        print(f"{'─' * 70}")
        print(f"  Response:")
        for line in textwrap.wrap(self.content, width=66):
            print(f"    {line}")
        print(f"{border}\n")


def extract_result(
    case_id: str,
    category: str,
    tier: str,
    query: str,
    events: list[SSEEvent],
) -> AccuracyResult:
    """Extract an AccuracyResult from collected SSE events."""
    content_parts = []
    tools_used = []
    iterations = 0
    total_tokens = 0
    has_error = False
    error_detail = ""

    for ev in events:
        if ev.event == "content":
            content_parts.append(ev.data.get("data", ""))
        elif ev.event == "tool_call_start":
            tools_used.append(ev.data.get("tool", "unknown"))
        elif ev.event == "agent_done":
            iterations = ev.data.get("iterations", 0)
            total_tokens = ev.data.get("total_tokens", 0)
        elif ev.event == "error":
            has_error = True
            error_detail = ev.data.get("message", ev.data.get("raw", str(ev.data)))

    return AccuracyResult(
        case_id=case_id,
        category=category,
        tier=tier,
        query=query,
        content="".join(content_parts),
        tools_used=tools_used,
        iterations=iterations,
        total_tokens=total_tokens,
        has_error=has_error,
        error_detail=error_detail,
    )


def run_accuracy_case(
    client: httpx.Client,
    thread_id: str,
    data_source_id: str,
    project_id: str,
    case_id: str,
    category: str,
    tier: str,
    query: str,
) -> AccuracyResult:
    """Run a single accuracy test case and return the result."""
    body = {
        "thread_id": thread_id,
        "query": query,
        "tier": tier,
        "data_source_id": data_source_id,
        "project_id": project_id,
    }
    events = collect_sse_events(client, body)
    result = extract_result(case_id, category, tier, query, events)
    result.print_report()
    RESULTS.append({
        "case": result.case_id,
        "category": result.category,
        "tier": result.tier,
        "has_error": result.has_error,
        "content_length": len(result.content),
        "tools_used": result.tools_used,
        "iterations": result.iterations,
        "tokens": result.total_tokens,
    })
    return result


# ---------------------------------------------------------------------------
# Category A: KG Search
# ---------------------------------------------------------------------------


@pytest.mark.accuracy
@pytest.mark.quick_tier
@pytest.mark.timeout(300)
def test_acc_01_basic_node_search(client, thread_id, data_source_id, project_id):
    """ACC-01: Basic KG node search — lists architecture/schema_table nodes."""
    result = run_accuracy_case(
        client, thread_id, data_source_id, project_id,
        case_id="ACC-01",
        category="KG Search",
        tier="quick",
        query="What architecture nodes exist in the knowledge graph?",
    )
    assert not result.has_error, f"Test errored: {result.error_detail}"
    assert len(result.content) > 0, "Empty response"
    assert "search_kg" in result.tools_used, f"Expected search_kg tool, used: {result.tools_used}"


@pytest.mark.accuracy
@pytest.mark.quick_tier
@pytest.mark.timeout(300)
def test_acc_02_neighbor_traversal(client, thread_id, data_source_id, project_id):
    """ACC-02: Neighbor traversal — shows edges from Customer table node."""
    result = run_accuracy_case(
        client, thread_id, data_source_id, project_id,
        case_id="ACC-02",
        category="KG Search",
        tier="quick",
        query="What nodes are connected to the Customer table?",
    )
    assert not result.has_error, f"Test errored: {result.error_detail}"
    assert len(result.content) > 0, "Empty response"


@pytest.mark.accuracy
@pytest.mark.deep_tier
@pytest.mark.timeout(600)
def test_acc_03_cross_reference_search(client, thread_id, data_source_id, project_id):
    """ACC-03: Cross-reference — finds order processing related tables."""
    result = run_accuracy_case(
        client, thread_id, data_source_id, project_id,
        case_id="ACC-03",
        category="KG Search",
        tier="deep",
        query="Find all tables related to order processing in C4K Staging",
    )
    assert not result.has_error, f"Test errored: {result.error_detail}"
    assert len(result.content) > 0, "Empty response"
    assert len(result.tools_used) >= 2, "Deep tier should use multiple tools"


# ---------------------------------------------------------------------------
# Category B: SQL Generation
# ---------------------------------------------------------------------------


@pytest.mark.accuracy
@pytest.mark.quick_tier
@pytest.mark.timeout(300)
def test_acc_04_simple_select(client, thread_id, data_source_id, project_id):
    """ACC-04: Simple SELECT — returns customer data with MSSQL syntax."""
    result = run_accuracy_case(
        client, thread_id, data_source_id, project_id,
        case_id="ACC-04",
        category="SQL Gen",
        tier="quick",
        query="Show me the first 10 customers from C4K Staging",
    )
    assert not result.has_error, f"Test errored: {result.error_detail}"
    assert len(result.content) > 0, "Empty response"
    assert "execute_sql" in result.tools_used, f"Expected execute_sql, used: {result.tools_used}"


@pytest.mark.accuracy
@pytest.mark.quick_tier
@pytest.mark.timeout(300)
def test_acc_05_aggregation_query(client, thread_id, data_source_id, project_id):
    """ACC-05: Aggregation — customer order counts with JOIN + GROUP BY."""
    result = run_accuracy_case(
        client, thread_id, data_source_id, project_id,
        case_id="ACC-05",
        category="SQL Gen",
        tier="quick",
        query="How many orders does each customer have? Show top 5 by order count",
    )
    assert not result.has_error, f"Test errored: {result.error_detail}"
    assert len(result.content) > 0, "Empty response"


@pytest.mark.accuracy
@pytest.mark.deep_tier
@pytest.mark.timeout(600)
def test_acc_06_multi_table_join(client, thread_id, data_source_id, project_id):
    """ACC-06: Multi-table JOIN — popular products by quantity ordered."""
    result = run_accuracy_case(
        client, thread_id, data_source_id, project_id,
        case_id="ACC-06",
        category="SQL Gen",
        tier="deep",
        query="What are the most popular products by total quantity ordered?",
    )
    assert not result.has_error, f"Test errored: {result.error_detail}"
    assert len(result.content) > 0, "Empty response"


# ---------------------------------------------------------------------------
# Category C: Multi-Step Reasoning
# ---------------------------------------------------------------------------


@pytest.mark.accuracy
@pytest.mark.quick_tier
@pytest.mark.timeout(300)
def test_acc_07_schema_then_query(client, thread_id, data_source_id, project_id):
    """ACC-07: Schema inspection then query — two-step tool usage."""
    result = run_accuracy_case(
        client, thread_id, data_source_id, project_id,
        case_id="ACC-07",
        category="Multi-step",
        tier="quick",
        query="What columns does the Customer table have, and show me 3 example rows",
    )
    assert not result.has_error, f"Test errored: {result.error_detail}"
    assert len(result.content) > 0, "Empty response"
    assert len(result.tools_used) >= 2, (
        f"Expected at least 2 tool calls (schema + query), got {len(result.tools_used)}: {result.tools_used}"
    )


@pytest.mark.accuracy
@pytest.mark.deep_tier
@pytest.mark.timeout(600)
def test_acc_08_kg_guided_analysis(client, thread_id, data_source_id, project_id):
    """ACC-08: KG-guided analysis — find tables and rank by column count."""
    result = run_accuracy_case(
        client, thread_id, data_source_id, project_id,
        case_id="ACC-08",
        category="Multi-step",
        tier="deep",
        query="Using the knowledge graph, find all tables in C4K Staging and tell me which ones have the most columns",
    )
    assert not result.has_error, f"Test errored: {result.error_detail}"
    assert len(result.content) > 0, "Empty response"
    assert len(result.tools_used) >= 3, "Deep multi-step should use 3+ tools"


@pytest.mark.accuracy
@pytest.mark.deep_tier
@pytest.mark.timeout(600)
def test_acc_09_data_discovery_pipeline(client, thread_id, data_source_id, project_id):
    """ACC-09: Data discovery — overview + analysis suggestions."""
    result = run_accuracy_case(
        client, thread_id, data_source_id, project_id,
        case_id="ACC-09",
        category="Multi-step",
        tier="deep",
        query="I'm new to this database. Give me an overview of what data is available and suggest 3 interesting analyses I could do",
    )
    assert not result.has_error, f"Test errored: {result.error_detail}"
    assert len(result.content) > 100, "Response too short for a data discovery overview"


# ---------------------------------------------------------------------------
# Category D: Edge Cases
# ---------------------------------------------------------------------------


@pytest.mark.accuracy
@pytest.mark.quick_tier
@pytest.mark.timeout(300)
def test_acc_10_empty_result_handling(client, thread_id, data_source_id, project_id):
    """ACC-10: Empty results — graceful handling, not an error."""
    result = run_accuracy_case(
        client, thread_id, data_source_id, project_id,
        case_id="ACC-10",
        category="Edge Case",
        tier="quick",
        query="Show me all customers named 'ZZZZNONEXISTENT'",
    )
    assert not result.has_error, f"Test errored: {result.error_detail}"
    assert len(result.content) > 0, "Empty response — should explain no results"


@pytest.mark.accuracy
@pytest.mark.quick_tier
@pytest.mark.timeout(300)
def test_acc_11_ambiguous_query(client, thread_id, data_source_id, project_id):
    """ACC-11: Ambiguous query — should clarify or make explicit assumption."""
    result = run_accuracy_case(
        client, thread_id, data_source_id, project_id,
        case_id="ACC-11",
        category="Edge Case",
        tier="quick",
        query="Show me the data",
    )
    # This test accepts both: clarification request (error-free) or a response
    # If clarification was requested, the content may be empty but no error
    if result.has_error:
        pytest.fail(f"Test errored: {result.error_detail}")
    # Either content exists or a clarification was triggered
    # (clarification shows as done status=awaiting_clarification)


@pytest.mark.accuracy
@pytest.mark.deep_tier
@pytest.mark.timeout(600)
def test_acc_12_complex_analysis(client, thread_id, data_source_id, project_id):
    """ACC-12: Complex schema analysis — data quality and FK assessment."""
    result = run_accuracy_case(
        client, thread_id, data_source_id, project_id,
        case_id="ACC-12",
        category="Edge Case",
        tier="deep",
        query="Analyze the C4K Staging database schema and identify potential data quality issues or missing foreign key relationships",
    )
    assert not result.has_error, f"Test errored: {result.error_detail}"
    assert len(result.content) > 100, "Response too short for complex analysis"
    assert len(result.tools_used) >= 3, "Complex analysis should use 3+ tools"


# ---------------------------------------------------------------------------
# Report generation (runs after all accuracy tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def print_accuracy_summary(request):
    """Print accuracy results summary after all tests complete."""
    yield
    if not RESULTS:
        return
    print("\n" + "=" * 70)
    print("  ACCURACY EVALUATION SUMMARY")
    print("=" * 70)
    print(f"  {'Case':<8} {'Category':<12} {'Tier':<6} {'Error':<6} {'Content':<8} {'Tools':<6} {'Iters':<6} {'Tokens':<8}")
    print("  " + "─" * 62)
    for r in RESULTS:
        print(
            f"  {r['case']:<8} {r['category']:<12} {r['tier']:<6} "
            f"{'YES' if r['has_error'] else 'no':<6} "
            f"{r['content_length']:<8} {len(r['tools_used']):<6} "
            f"{r['iterations']:<6} {r['tokens']:<8}"
        )
    print("=" * 70)
    print("\n  Score each case 0-3 using the rubric in the spec.")
    print("  0=Wrong  1=Partial  2=Correct  3=Excellent")
    print("  Minimum pass: avg ≥ 1.5 | Target: avg ≥ 2.0")
    print("  No score-0 allowed in KG Search or SQL Gen categories.\n")
```

- [ ] **Step 2: Verify syntax and test discovery**

```bash
cd tests/e2e
python -c "import ast; ast.parse(open('test_accuracy.py').read()); print('Syntax OK')"
pytest --collect-only test_accuracy.py
```

Expected: 12 tests collected (test_acc_01 through test_acc_12).

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_accuracy.py
git commit -m "test(e2e): add Layer 3 accuracy evaluation — 12 test cases with scoring report"
```

---

### Task 5: Test Runner Script

**Files:**
- Create: `tests/e2e/run_tests.sh`

**Dependencies:** Tasks 1-4

- [ ] **Step 1: Write run_tests.sh**

Write `tests/e2e/run_tests.sh`:

```bash
#!/usr/bin/env bash
#
# Agentic AI E2E Test Runner
#
# Rebuilds Docker, waits for services, runs API smoke tests and accuracy tests.
# Browser E2E (Layer 2) is run separately via Chrome DevTools MCP playbook.
#
# Usage:
#   ./run_tests.sh              # Full run: rebuild + all tests
#   ./run_tests.sh --skip-build # Skip Docker rebuild
#   ./run_tests.sh --smoke-only # Only API smoke tests
#   ./run_tests.sh --accuracy   # Only accuracy evaluation
#

set -euo pipefail
cd "$(dirname "$0")/../.."  # Navigate to project root (ennam.kg/)

SKIP_BUILD=false
SMOKE_ONLY=false
ACCURACY_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --skip-build) SKIP_BUILD=true ;;
        --smoke-only) SMOKE_ONLY=true ;;
        --accuracy)   ACCURACY_ONLY=true ;;
    esac
done

echo "============================================="
echo "  Agentic AI E2E Test Runner"
echo "============================================="

# -------------------------------------------
# Step 1: Docker rebuild (unless skipped)
# -------------------------------------------
if [ "$SKIP_BUILD" = false ]; then
    echo ""
    echo "[1/4] Rebuilding Docker services..."
    docker compose down
    docker compose build --no-cache
    docker compose up -d
    echo "Docker services starting..."
else
    echo ""
    echo "[1/4] Skipping Docker rebuild (--skip-build)"
fi

# -------------------------------------------
# Step 2: Wait for services
# -------------------------------------------
echo ""
echo "[2/4] Waiting for services to be healthy..."
cd tests/e2e
pip install -q -r requirements.txt
python -m helpers.health
if [ $? -ne 0 ]; then
    echo "ERROR: Services not healthy. Aborting."
    exit 1
fi
cd ../..

# -------------------------------------------
# Step 3: Verify migration 000044
# -------------------------------------------
echo ""
echo "[3/4] Checking migration 000044..."
MIGRATION_CHECK=$(docker compose exec -T postgres psql -U ennam -d ennam_kg -tAc \
    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'agent_tool_calls');" \
    2>/dev/null || echo "false")

if [ "$MIGRATION_CHECK" != "t" ]; then
    echo "WARNING: agent_tool_calls table not found. Running migrations..."
    docker compose exec kg-server ./migrate up
fi

# -------------------------------------------
# Step 4: Run tests
# -------------------------------------------
echo ""
echo "[4/4] Running tests..."
cd tests/e2e

# Create results directory
mkdir -p ../../docs/superpowers/test-results

if [ "$SMOKE_ONLY" = true ]; then
    echo "Running API smoke tests only..."
    pytest test_api_smoke.py -v --tb=short 2>&1 | tee ../../docs/superpowers/test-results/api-smoke-results.txt
elif [ "$ACCURACY_ONLY" = true ]; then
    echo "Running accuracy evaluation only..."
    pytest test_accuracy.py -v -s --tb=short 2>&1 | tee ../../docs/superpowers/test-results/accuracy-results.txt
else
    echo "Running Layer 1: API smoke tests..."
    pytest test_api_smoke.py -v --tb=short 2>&1 | tee ../../docs/superpowers/test-results/api-smoke-results.txt

    echo ""
    echo "Running Layer 3: Accuracy evaluation..."
    pytest test_accuracy.py -v -s --tb=short 2>&1 | tee ../../docs/superpowers/test-results/accuracy-results.txt
fi

echo ""
echo "============================================="
echo "  Tests complete!"
echo "  Results saved to docs/superpowers/test-results/"
echo ""
echo "  Layer 2 (Browser E2E) must be run separately"
echo "  using Chrome DevTools MCP. See:"
echo "    tests/e2e/browser_playbook.md"
echo "============================================="
```

- [ ] **Step 2: Make script executable**

```bash
chmod +x tests/e2e/run_tests.sh
```

- [ ] **Step 3: Create results directory with .gitkeep**

```bash
mkdir -p docs/superpowers/test-results
touch docs/superpowers/test-results/.gitkeep
```

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/run_tests.sh docs/superpowers/test-results/.gitkeep
git commit -m "test(e2e): add test runner script and results directory"
```

---

## Self-Review

**1. Spec coverage:**
- Section 1 (Prerequisites): Covered by Task 5 (`run_tests.sh` — Docker rebuild, health check, migration verify)
- Section 2 (API Smoke Tests): Covered by Task 2 — all 6 tests (API-01 through API-06)
- Section 3 (Browser E2E): Covered by Task 3 — all 8 test cases (UI-01 through UI-08)
- Section 4 (Accuracy Evaluation): Covered by Task 4 — all 12 test cases (ACC-01 through ACC-12)
- Section 5 (Execution Order): Enforced by `run_tests.sh` — smoke before accuracy
- Section 6 (Cleanup): Thread cleanup in conftest.py `thread_id` fixture teardown

**2. Placeholder scan:** No TBD/TODO/placeholders found. All code is complete.

**3. Type consistency:**
- `SSEEvent` used consistently across all files
- `collect_sse_events()` used by both test_api_smoke.py and test_accuracy.py
- `login()` returns `tuple[str, dict]` everywhere
- Fixture names consistent: `client`, `thread_id`, `data_source_id`, `project_id`
