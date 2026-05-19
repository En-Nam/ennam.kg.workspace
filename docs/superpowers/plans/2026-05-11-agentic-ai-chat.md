# Agentic AI Chat Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Chat/AI feature from a one-shot SQL generator into a full Agentic AI system with iterative tool-calling, tiered execution (Quick/Deep), clarification pause/resume, and cross-datasource querying.

**Architecture:** New `ennam_kg/agentic/` Python package runs an FSM-based agent loop (EXPLORE → PLAN → EXECUTE → SYNTHESIZE) calling Anthropic API with `tool_use`. Go API proxies SSE and persists tool call audit trails. NextJS frontend renders real-time agent progress, clarification prompts, and multi-source results.

**Tech Stack:** Python 3.12 (FastAPI, anthropic SDK, redis, pydantic), Go 1.22 (existing service), NextJS 16 (React 19, TanStack Query), PostgreSQL (migrations), Redis (ephemeral state)

**Design Spec:** [`docs/superpowers/specs/2026-05-11-agentic-ai-chat-design.md`](docs/superpowers/specs/2026-05-11-agentic-ai-chat-design.md)

---

## File Structure

### Python — New Files (Create)

| File | Responsibility |
|------|----------------|
| `src/ennam_kg/agentic/__init__.py` | Package exports |
| `src/ennam_kg/agentic/types.py` | Dataclasses: AgentConfig, LoopState, ToolCall, ToolResult, AgentState |
| `src/ennam_kg/agentic/loop_guard.py` | Anti-pattern detection: duplicate calls, node saturation, budget |
| `src/ennam_kg/agentic/state_store.py` | Redis-backed pause/resume state (JSON serialization) |
| `src/ennam_kg/agentic/sql_validator.py` | SQL security: block DDL/DML, strip comments |
| `src/ennam_kg/agentic/tools.py` | KGToolFactory: 7 tool definitions + executors |
| `src/ennam_kg/agentic/prompts.py` | 5-layer prompt assembly |
| `src/ennam_kg/agentic/engine.py` | AgenticEngine: main agentic loop |
| `src/ennam_kg/api/agentic.py` | FastAPI POST /api/v1/agentic/stream |
| `tests/test_agentic/test_types.py` | Tests for types |
| `tests/test_agentic/test_loop_guard.py` | Tests for loop guard |
| `tests/test_agentic/test_state_store.py` | Tests for state store |
| `tests/test_agentic/test_sql_validator.py` | Tests for SQL validator |
| `tests/test_agentic/test_tools.py` | Tests for tool factory |
| `tests/test_agentic/test_prompts.py` | Tests for prompt builder |
| `tests/test_agentic/test_engine.py` | Tests for engine |
| `tests/test_agentic/test_api.py` | Tests for API route |

### Go — Modified Files

| File | Change |
|------|--------|
| `db/migrations/000044_agentic_ai_support.up.sql` | Create: agent_tool_calls, clarification_sessions, ALTER thread_messages |
| `db/migrations/000044_agentic_ai_support.down.sql` | Rollback migration |
| `internal/models/thread.go` | Modify: add 6 agentic fields to ThreadMessage |
| `internal/service/sse_stream.go` | Modify: tier-aware timeout, agentic endpoint routing, new SSE events |
| `internal/handler/ai_stream.go` | Modify: HandleClarification endpoint, agentic routing |
| `internal/store/thread_message.go` | Modify: UpdateAgentMetadata function |

### Frontend — New & Modified Files

| File | Responsibility |
|------|----------------|
| `src/types/agentic.ts` | Create: all agentic SSE event types & state |
| `src/lib/streaming/sse-handler.ts` | Modify: extend StreamCallbacks with 8 agentic callbacks |
| `src/hooks/use-agentic-stream.ts` | Create: useAgenticStream hook |
| `src/components/chat/TierSelector.tsx` | Create: Quick/Deep toggle |
| `src/components/chat/AgenticProgress.tsx` | Create: collapsible tool call timeline |
| `src/components/chat/PhaseIndicator.tsx` | Create: phase badge component |
| `src/components/chat/ToolCallStepRow.tsx` | Create: individual step row |
| `src/components/chat/ClarificationPrompt.tsx` | Create: inline clarification form |
| `src/components/chat/CountdownRing.tsx` | Create: SVG countdown timer |
| `src/components/chat/KgNodeChip.tsx` | Create: clickable KG node badge |
| `src/components/chat/MultiSourceResults.tsx` | Create: tabbed datasource results |
| `src/components/chat/ChatMessage.tsx` | Modify: render agentic components |
| `src/components/chat/QueryInputBar.tsx` | Modify: add TierSelector |

---

## Phase 0: Database Migration

### Task 1: Create Agentic AI Migration

**Files:**
- Create: `ennam.kg.go/db/migrations/000044_agentic_ai_support.up.sql`
- Create: `ennam.kg.go/db/migrations/000044_agentic_ai_support.down.sql`

- [ ] **Step 1: Write the up migration**

```sql
-- 000044_agentic_ai_support.up.sql

-- Agent tool call audit trail
CREATE TABLE agent_tool_calls (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id      UUID NOT NULL REFERENCES thread_messages(id) ON DELETE CASCADE,
    thread_id       UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    iteration       INTEGER NOT NULL,
    phase           VARCHAR(20) NOT NULL,
    tool_name       VARCHAR(100) NOT NULL,
    tool_call_id    VARCHAR(100) NOT NULL,
    input_params    JSONB NOT NULL,
    output_result   JSONB,
    error_message   TEXT,
    duration_ms     INTEGER NOT NULL,
    tokens_used     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agent_tool_calls_message ON agent_tool_calls(message_id);
CREATE INDEX idx_agent_tool_calls_thread ON agent_tool_calls(thread_id);
CREATE INDEX idx_agent_tool_calls_tool ON agent_tool_calls(tool_name);
CREATE INDEX idx_agent_tool_calls_created ON agent_tool_calls(created_at);

-- Clarification session tracking
CREATE TABLE clarification_sessions (
    id              VARCHAR(100) PRIMARY KEY,
    thread_id       UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    message_id      UUID NOT NULL REFERENCES thread_messages(id),
    question        TEXT NOT NULL,
    options         JSONB,
    user_response   TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    responded_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_clarification_thread ON clarification_sessions(thread_id);
CREATE INDEX idx_clarification_status ON clarification_sessions(status)
    WHERE status = 'pending';

-- Extend thread_messages with agentic metadata
ALTER TABLE thread_messages ADD COLUMN agent_tier VARCHAR(20);
ALTER TABLE thread_messages ADD COLUMN agent_iterations INTEGER;
ALTER TABLE thread_messages ADD COLUMN agent_tools_used TEXT[];
ALTER TABLE thread_messages ADD COLUMN agent_total_tokens INTEGER;
ALTER TABLE thread_messages ADD COLUMN clarification_session_id VARCHAR(100);
ALTER TABLE thread_messages ADD COLUMN clarification_status VARCHAR(20);
```

- [ ] **Step 2: Write the down migration**

```sql
-- 000044_agentic_ai_support.down.sql
DROP TABLE IF EXISTS clarification_sessions;
DROP TABLE IF EXISTS agent_tool_calls;
ALTER TABLE thread_messages DROP COLUMN IF EXISTS agent_tier;
ALTER TABLE thread_messages DROP COLUMN IF EXISTS agent_iterations;
ALTER TABLE thread_messages DROP COLUMN IF EXISTS agent_tools_used;
ALTER TABLE thread_messages DROP COLUMN IF EXISTS agent_total_tokens;
ALTER TABLE thread_messages DROP COLUMN IF EXISTS clarification_session_id;
ALTER TABLE thread_messages DROP COLUMN IF EXISTS clarification_status;
```

- [ ] **Step 3: Verify migration syntax**

Run: `cd ennam.kg.go && cat db/migrations/000044_agentic_ai_support.up.sql | head -5`
Expected: File exists with CREATE TABLE header

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.go
git add db/migrations/000044_agentic_ai_support.up.sql db/migrations/000044_agentic_ai_support.down.sql
git commit -m "feat(db): add migration 000044 for agentic AI support

Add agent_tool_calls table, clarification_sessions table,
and extend thread_messages with agentic metadata columns."
```

---

## Phase 1: Python Core Types & Guards

### Task 2: Agent Types & Dataclasses

**Files:**
- Create: `ennam.kg.python/tests/test_agentic/__init__.py`
- Create: `ennam.kg.python/tests/test_agentic/test_types.py`
- Create: `ennam.kg.python/src/ennam_kg/agentic/__init__.py`
- Create: `ennam.kg.python/src/ennam_kg/agentic/types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agentic/__init__.py
# (empty)

# tests/test_agentic/test_types.py
"""Tests for agentic type definitions and serialization."""

import json

import pytest

from ennam_kg.agentic.types import (
    AgentConfig,
    AgentPhase,
    AgentState,
    LoopState,
    ToolCall,
    ToolResult,
)


class TestAgentConfig:
    def test_quick_defaults(self):
        cfg = AgentConfig(tier="quick")
        assert cfg.max_iterations == 3
        assert cfg.max_tokens == 30_000
        assert cfg.timeout_seconds == 300

    def test_deep_defaults(self):
        cfg = AgentConfig(tier="deep")
        assert cfg.max_iterations == 12
        assert cfg.max_tokens == 100_000
        assert cfg.timeout_seconds == 600

    def test_invalid_tier_raises(self):
        with pytest.raises(ValueError, match="tier"):
            AgentConfig(tier="invalid")


class TestLoopState:
    def test_initial_state(self):
        state = LoopState()
        assert state.iteration == 0
        assert state.phase == AgentPhase.EXPLORE
        assert state.tool_calls == []
        assert state.tokens_used == 0

    def test_can_continue_within_budget(self):
        state = LoopState()
        cfg = AgentConfig(tier="quick")
        assert state.can_continue(cfg) is True

    def test_cannot_continue_over_iterations(self):
        state = LoopState(iteration=3)
        cfg = AgentConfig(tier="quick")
        assert state.can_continue(cfg) is False

    def test_cannot_continue_over_tokens(self):
        # 85% of 30K = 25500
        state = LoopState(tokens_used=26_000)
        cfg = AgentConfig(tier="quick")
        assert state.can_continue(cfg) is False


class TestToolCall:
    def test_creation(self):
        tc = ToolCall(
            id="tc_001",
            name="search_kg",
            input={"query": "revenue"},
        )
        assert tc.id == "tc_001"
        assert tc.name == "search_kg"
        assert tc.input == {"query": "revenue"}


class TestToolResult:
    def test_success(self):
        tr = ToolResult(tool_call_id="tc_001", output={"nodes": []}, is_error=False)
        assert tr.is_error is False

    def test_error(self):
        tr = ToolResult(tool_call_id="tc_001", output="timeout", is_error=True)
        assert tr.is_error is True


class TestAgentState:
    def test_json_roundtrip(self):
        state = AgentState(
            messages=[{"role": "user", "content": "hello"}],
            loop_state=LoopState(iteration=2, phase=AgentPhase.EXECUTE),
            project_id="proj-1",
            data_source_id="ds-1",
            thread_id="t-1",
            message_id="m-1",
            tier="quick",
        )
        serialized = state.to_json()
        data = json.loads(serialized)
        assert data["project_id"] == "proj-1"
        assert data["loop_state"]["iteration"] == 2
        assert data["loop_state"]["phase"] == "EXECUTE"

        restored = AgentState.from_json(serialized)
        assert restored.project_id == "proj-1"
        assert restored.loop_state.iteration == 2
        assert restored.loop_state.phase == AgentPhase.EXECUTE
        assert restored.messages == [{"role": "user", "content": "hello"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ennam_kg.agentic'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ennam_kg/agentic/__init__.py
"""Agentic AI engine — iterative tool-calling agent loop."""

# src/ennam_kg/agentic/types.py
"""Core dataclasses for the agentic engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentPhase(str, Enum):
    EXPLORE = "EXPLORE"
    PLAN = "PLAN"
    EXECUTE = "EXECUTE"
    SYNTHESIZE = "SYNTHESIZE"


# Tool budgets per tier
_TIER_CONFIG = {
    "quick": {"max_iterations": 3, "max_tokens": 30_000, "timeout_seconds": 300},
    "deep": {"max_iterations": 12, "max_tokens": 100_000, "timeout_seconds": 600},
}

# Reserve 15% of token budget for synthesis
_TOKEN_RESERVE_RATIO = 0.85


@dataclass
class AgentConfig:
    tier: str
    max_iterations: int = 0
    max_tokens: int = 0
    timeout_seconds: int = 0

    def __post_init__(self):
        if self.tier not in _TIER_CONFIG:
            raise ValueError(f"Invalid tier: {self.tier!r}. Must be 'quick' or 'deep'.")
        defaults = _TIER_CONFIG[self.tier]
        if self.max_iterations == 0:
            self.max_iterations = defaults["max_iterations"]
        if self.max_tokens == 0:
            self.max_tokens = defaults["max_tokens"]
        if self.timeout_seconds == 0:
            self.timeout_seconds = defaults["timeout_seconds"]


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    tool_call_id: str
    output: Any
    is_error: bool = False
    duration_ms: int = 0


@dataclass
class LoopState:
    iteration: int = 0
    phase: AgentPhase = AgentPhase.EXPLORE
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_used: int = 0
    visited_nodes: set[str] = field(default_factory=set)

    def can_continue(self, config: AgentConfig) -> bool:
        if self.iteration >= config.max_iterations:
            return False
        if self.tokens_used >= int(config.max_tokens * _TOKEN_RESERVE_RATIO):
            return False
        return True


@dataclass
class AgentState:
    messages: list[dict[str, Any]]
    loop_state: LoopState
    project_id: str
    data_source_id: str
    thread_id: str
    message_id: str
    tier: str

    def to_json(self) -> str:
        return json.dumps({
            "messages": self.messages,
            "loop_state": {
                "iteration": self.loop_state.iteration,
                "phase": self.loop_state.phase.value,
                "tokens_used": self.loop_state.tokens_used,
                "visited_nodes": list(self.loop_state.visited_nodes),
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "input": tc.input}
                    for tc in self.loop_state.tool_calls
                ],
            },
            "project_id": self.project_id,
            "data_source_id": self.data_source_id,
            "thread_id": self.thread_id,
            "message_id": self.message_id,
            "tier": self.tier,
        })

    @classmethod
    def from_json(cls, raw: str) -> AgentState:
        data = json.loads(raw)
        ls = data["loop_state"]
        loop_state = LoopState(
            iteration=ls["iteration"],
            phase=AgentPhase(ls["phase"]),
            tokens_used=ls.get("tokens_used", 0),
            visited_nodes=set(ls.get("visited_nodes", [])),
            tool_calls=[
                ToolCall(id=tc["id"], name=tc["name"], input=tc["input"])
                for tc in ls.get("tool_calls", [])
            ],
        )
        return cls(
            messages=data["messages"],
            loop_state=loop_state,
            project_id=data["project_id"],
            data_source_id=data["data_source_id"],
            thread_id=data["thread_id"],
            message_id=data["message_id"],
            tier=data["tier"],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_types.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/agentic/__init__.py src/ennam_kg/agentic/types.py tests/test_agentic/
git commit -m "feat(agentic): add core type definitions

AgentConfig, LoopState, ToolCall, ToolResult, AgentState with
JSON roundtrip serialization. Tier-aware budgets (quick/deep)."
```

---

### Task 3: LoopGuard — Anti-Pattern Detection

**Files:**
- Create: `ennam.kg.python/tests/test_agentic/test_loop_guard.py`
- Create: `ennam.kg.python/src/ennam_kg/agentic/loop_guard.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agentic/test_loop_guard.py
"""Tests for LoopGuard anti-pattern detection."""

from ennam_kg.agentic.loop_guard import LoopGuard
from ennam_kg.agentic.types import LoopState, ToolCall


class TestDuplicateCallDetection:
    def test_first_call_allowed(self):
        guard = LoopGuard()
        state = LoopState()
        tc = ToolCall(id="tc1", name="search_kg", input={"query": "revenue"})
        result = guard.check(tc, state)
        assert result.allowed is True

    def test_identical_consecutive_call_blocked(self):
        guard = LoopGuard()
        tc = ToolCall(id="tc1", name="search_kg", input={"query": "revenue"})
        state = LoopState(tool_calls=[tc])
        tc2 = ToolCall(id="tc2", name="search_kg", input={"query": "revenue"})
        result = guard.check(tc2, state)
        assert result.allowed is False
        assert "duplicate" in result.reason.lower()

    def test_same_tool_different_params_allowed(self):
        guard = LoopGuard()
        tc1 = ToolCall(id="tc1", name="search_kg", input={"query": "revenue"})
        state = LoopState(tool_calls=[tc1])
        tc2 = ToolCall(id="tc2", name="search_kg", input={"query": "customers"})
        result = guard.check(tc2, state)
        assert result.allowed is True


class TestNodeSaturation:
    def test_node_visited_under_limit(self):
        guard = LoopGuard(max_node_visits=3)
        state = LoopState(visited_nodes={"node-1", "node-2"})
        tc = ToolCall(id="tc1", name="get_neighbors", input={"node_id": "node-1"})
        result = guard.check(tc, state)
        # First revisit is fine, only blocks at threshold
        assert result.allowed is True

    def test_node_visited_at_limit_blocked(self):
        guard = LoopGuard(max_node_visits=3)
        # Simulate node-1 visited 3 times already via tool_calls
        prior_calls = [
            ToolCall(id=f"tc{i}", name="get_neighbors", input={"node_id": "node-1"})
            for i in range(3)
        ]
        state = LoopState(tool_calls=prior_calls, visited_nodes={"node-1"})
        tc = ToolCall(id="tc4", name="get_neighbors", input={"node_id": "node-1"})
        result = guard.check(tc, state)
        assert result.allowed is False
        assert "already explored" in result.reason.lower()


class TestBudgetEnforcement:
    def test_within_budget(self):
        guard = LoopGuard(max_tool_calls=5)
        state = LoopState(tool_calls=[
            ToolCall(id=f"tc{i}", name="search_kg", input={"query": f"q{i}"})
            for i in range(4)
        ])
        tc = ToolCall(id="tc5", name="search_kg", input={"query": "final"})
        result = guard.check(tc, state)
        assert result.allowed is True

    def test_over_budget(self):
        guard = LoopGuard(max_tool_calls=3)
        state = LoopState(tool_calls=[
            ToolCall(id=f"tc{i}", name="search_kg", input={"query": f"q{i}"})
            for i in range(3)
        ])
        tc = ToolCall(id="tc4", name="search_kg", input={"query": "one more"})
        result = guard.check(tc, state)
        assert result.allowed is False
        assert "budget" in result.reason.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_loop_guard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ennam_kg.agentic.loop_guard'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ennam_kg/agentic/loop_guard.py
"""LoopGuard — detects and prevents agentic anti-patterns."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ennam_kg.agentic.types import LoopState, ToolCall

logger = logging.getLogger(__name__)


@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""


class LoopGuard:
    """Prevents infinite loops and wasteful tool calls."""

    def __init__(self, max_tool_calls: int = 12, max_node_visits: int = 3):
        self._max_tool_calls = max_tool_calls
        self._max_node_visits = max_node_visits

    def check(self, tool_call: ToolCall, state: LoopState) -> GuardResult:
        # 1. Budget check
        if len(state.tool_calls) >= self._max_tool_calls:
            return GuardResult(
                allowed=False,
                reason=f"Tool call budget exceeded ({self._max_tool_calls} max).",
            )

        # 2. Duplicate consecutive call check
        if state.tool_calls:
            last = state.tool_calls[-1]
            if last.name == tool_call.name and last.input == tool_call.input:
                return GuardResult(
                    allowed=False,
                    reason=f"Duplicate consecutive call: {tool_call.name} with same params.",
                )

        # 3. Node saturation check (for graph traversal tools)
        if tool_call.name in ("get_neighbors", "traverse_path"):
            node_id = tool_call.input.get("node_id", "")
            if node_id:
                visit_count = sum(
                    1 for tc in state.tool_calls
                    if tc.name == tool_call.name and tc.input.get("node_id") == node_id
                )
                if visit_count >= self._max_node_visits:
                    return GuardResult(
                        allowed=False,
                        reason=f"Node {node_id} already explored {visit_count} times.",
                    )

        return GuardResult(allowed=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_loop_guard.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/agentic/loop_guard.py tests/test_agentic/test_loop_guard.py
git commit -m "feat(agentic): add LoopGuard anti-pattern detection

Detects duplicate consecutive calls, node saturation (3+ visits),
and tool call budget exceeded. Returns GuardResult with reason."
```

---

### Task 4: AgentStateStore — Redis Pause/Resume

**Files:**
- Create: `ennam.kg.python/tests/test_agentic/test_state_store.py`
- Create: `ennam.kg.python/src/ennam_kg/agentic/state_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agentic/test_state_store.py
"""Tests for AgentStateStore — Redis-backed pause/resume."""

import json
from unittest.mock import AsyncMock

import pytest

from ennam_kg.agentic.state_store import AgentStateStore, SessionExpiredError
from ennam_kg.agentic.types import AgentPhase, AgentState, LoopState


@pytest.fixture()
def mock_redis():
    return AsyncMock()


@pytest.fixture()
def store(mock_redis):
    return AgentStateStore(mock_redis)


@pytest.fixture()
def sample_state():
    return AgentState(
        messages=[{"role": "user", "content": "test"}],
        loop_state=LoopState(iteration=1, phase=AgentPhase.PLAN),
        project_id="p1",
        data_source_id="ds1",
        thread_id="t1",
        message_id="m1",
        tier="quick",
    )


class TestSave:
    @pytest.mark.asyncio
    async def test_save_stores_json_with_ttl(self, store, mock_redis, sample_state):
        session_id = "session-abc"
        await store.save(session_id, sample_state)

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == "agent:session:session-abc"
        assert call_args[0][1] == 600  # TTL
        stored = json.loads(call_args[0][2])
        assert stored["project_id"] == "p1"
        assert stored["tier"] == "quick"


class TestRestore:
    @pytest.mark.asyncio
    async def test_restore_returns_state_and_deletes_key(self, store, mock_redis, sample_state):
        session_id = "session-abc"
        mock_redis.getdel.return_value = sample_state.to_json()

        restored = await store.restore(session_id)
        mock_redis.getdel.assert_called_once_with("agent:session:session-abc")
        assert restored.project_id == "p1"
        assert restored.loop_state.iteration == 1

    @pytest.mark.asyncio
    async def test_restore_expired_raises(self, store, mock_redis):
        mock_redis.getdel.return_value = None
        with pytest.raises(SessionExpiredError):
            await store.restore("expired-session")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_state_store.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ennam_kg/agentic/state_store.py
"""Redis-backed agent state store for clarification pause/resume."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ennam_kg.agentic.types import AgentState

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_KEY_PREFIX = "agent:session:"
_DEFAULT_TTL = 600  # 10 minutes


class SessionExpiredError(Exception):
    """Raised when a clarification session has expired or been consumed."""


class AgentStateStore:
    """Save/restore agent state in Redis for clarification pause/resume.

    Uses JSON serialization for safety. Keys are one-time-use:
    restored state is deleted immediately (getdel). 600s TTL.
    """

    def __init__(self, redis: Redis, ttl: int = _DEFAULT_TTL):
        self._redis = redis
        self._ttl = ttl

    async def save(self, session_id: str, state: AgentState) -> None:
        key = f"{_KEY_PREFIX}{session_id}"
        await self._redis.setex(key, self._ttl, state.to_json())
        logger.info("Saved agent state: session=%s ttl=%ds", session_id, self._ttl)

    async def restore(self, session_id: str) -> AgentState:
        key = f"{_KEY_PREFIX}{session_id}"
        raw = await self._redis.getdel(key)
        if raw is None:
            raise SessionExpiredError(
                f"Session {session_id} expired or already consumed."
            )
        logger.info("Restored agent state: session=%s", session_id)
        return AgentState.from_json(raw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_state_store.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/agentic/state_store.py tests/test_agentic/test_state_store.py
git commit -m "feat(agentic): add AgentStateStore for clarification pause/resume

Redis-backed JSON state store with 600s TTL. One-time restore
(key deleted after read). Raises SessionExpiredError if not found."
```

---

### Task 5: SQL Validator — Security Layer

**Files:**
- Create: `ennam.kg.python/tests/test_agentic/test_sql_validator.py`
- Create: `ennam.kg.python/src/ennam_kg/agentic/sql_validator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agentic/test_sql_validator.py
"""Tests for SQL security validator."""

import pytest

from ennam_kg.agentic.sql_validator import SQLValidationError, validate_sql


class TestValidSQL:
    def test_simple_select(self):
        validate_sql("SELECT id, name FROM users WHERE active = true")

    def test_select_with_join(self):
        validate_sql("SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id")

    def test_with_cte(self):
        validate_sql("WITH recent AS (SELECT * FROM orders WHERE date > '2026-01-01') SELECT * FROM recent")

    def test_select_with_subquery(self):
        validate_sql("SELECT * FROM (SELECT id FROM users) sub")


class TestBlockedSQL:
    def test_insert_blocked(self):
        with pytest.raises(SQLValidationError, match="INSERT"):
            validate_sql("INSERT INTO users (name) VALUES ('hacker')")

    def test_update_blocked(self):
        with pytest.raises(SQLValidationError, match="UPDATE"):
            validate_sql("UPDATE users SET name = 'hacked'")

    def test_delete_blocked(self):
        with pytest.raises(SQLValidationError, match="DELETE"):
            validate_sql("DELETE FROM users")

    def test_drop_blocked(self):
        with pytest.raises(SQLValidationError, match="DROP"):
            validate_sql("DROP TABLE users")

    def test_alter_blocked(self):
        with pytest.raises(SQLValidationError, match="ALTER"):
            validate_sql("ALTER TABLE users ADD COLUMN hacked BOOLEAN")

    def test_truncate_blocked(self):
        with pytest.raises(SQLValidationError, match="TRUNCATE"):
            validate_sql("TRUNCATE TABLE users")

    def test_create_blocked(self):
        with pytest.raises(SQLValidationError, match="CREATE"):
            validate_sql("CREATE TABLE hacked (id INT)")

    def test_grant_blocked(self):
        with pytest.raises(SQLValidationError, match="GRANT"):
            validate_sql("GRANT ALL ON users TO hacker")

    def test_exec_blocked(self):
        with pytest.raises(SQLValidationError, match="EXEC"):
            validate_sql("EXEC sp_who")

    def test_multiple_statements_blocked(self):
        with pytest.raises(SQLValidationError, match="single statement"):
            validate_sql("SELECT 1; DROP TABLE users")

    def test_sql_comments_stripped(self):
        with pytest.raises(SQLValidationError, match="must start with SELECT"):
            validate_sql("-- SELECT 1\nDROP TABLE users")

    def test_multiline_comment_stripped(self):
        validate_sql("SELECT /* this is fine */ id FROM users")

    def test_empty_sql_rejected(self):
        with pytest.raises(SQLValidationError, match="empty"):
            validate_sql("")

    def test_too_long_rejected(self):
        with pytest.raises(SQLValidationError, match="length"):
            validate_sql("SELECT " + "x" * 5001)

    def test_must_start_with_select_or_with(self):
        with pytest.raises(SQLValidationError, match="must start with SELECT"):
            validate_sql("EXPLAIN SELECT 1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_sql_validator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ennam_kg/agentic/sql_validator.py
"""SQL security validator — blocks DDL/DML, enforces SELECT-only."""

from __future__ import annotations

import re

_MAX_SQL_LENGTH = 5000

_BLOCKED_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
    "CREATE", "TRUNCATE", "EXEC", "EXECUTE",
    "GRANT", "REVOKE",
]

# Match single-line comments (-- ...) and multi-line comments (/* ... */)
_COMMENT_PATTERN = re.compile(r"--[^\n]*|/\*[\s\S]*?\*/")


class SQLValidationError(Exception):
    """Raised when SQL fails security validation."""


def validate_sql(sql: str) -> None:
    """Validate that SQL is a safe SELECT query.

    Raises SQLValidationError if:
    - SQL is empty or too long
    - SQL contains DDL/DML keywords
    - SQL contains multiple statements
    - SQL doesn't start with SELECT or WITH
    """
    if not sql or not sql.strip():
        raise SQLValidationError("SQL is empty.")

    if len(sql) > _MAX_SQL_LENGTH:
        raise SQLValidationError(f"SQL exceeds max length ({_MAX_SQL_LENGTH} chars).")

    # Strip comments for analysis (but keep original for execution)
    cleaned = _COMMENT_PATTERN.sub(" ", sql).strip()

    if not cleaned:
        raise SQLValidationError("SQL is empty after stripping comments.")

    # Must start with SELECT or WITH
    first_word = cleaned.split()[0].upper()
    if first_word not in ("SELECT", "WITH"):
        raise SQLValidationError(
            f"SQL must start with SELECT or WITH, got: {first_word}"
        )

    # Check for blocked keywords (as whole words in the cleaned SQL)
    upper_cleaned = cleaned.upper()
    for keyword in _BLOCKED_KEYWORDS:
        pattern = rf"\b{keyword}\b"
        if re.search(pattern, upper_cleaned):
            raise SQLValidationError(
                f"SQL contains blocked keyword: {keyword}"
            )

    # Multiple statements check (semicolon not inside quotes)
    in_single_quote = False
    semicolon_count = 0
    for char in cleaned:
        if char == "'" and not in_single_quote:
            in_single_quote = True
        elif char == "'" and in_single_quote:
            in_single_quote = False
        elif char == ";" and not in_single_quote:
            semicolon_count += 1

    if semicolon_count > 0:
        raise SQLValidationError("SQL must be a single statement (no semicolons).")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_sql_validator.py -v`
Expected: All 16 tests PASS

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/agentic/sql_validator.py tests/test_agentic/test_sql_validator.py
git commit -m "feat(agentic): add SQL security validator

Blocks DDL/DML keywords, enforces SELECT/WITH start, strips
comments, rejects multi-statement queries. Max 5000 chars."
```

---

## Phase 2: Python Tools & Prompts

### Task 6: KGToolFactory — Tool Definitions & Executors

**Files:**
- Create: `ennam.kg.python/tests/test_agentic/test_tools.py`
- Create: `ennam.kg.python/src/ennam_kg/agentic/tools.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agentic/test_tools.py
"""Tests for KGToolFactory — tool definitions and execution."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ennam_kg.agentic.tools import KGToolFactory


@pytest.fixture()
def mock_kg_client():
    client = AsyncMock()
    client.search.return_value = {"nodes": [{"id": "n1", "label": "revenue"}]}
    client.get_neighbors.return_value = {"nodes": [{"id": "n2"}], "edges": []}
    client.get_schema_metadata.return_value = {
        "tables": [{"name": "orders", "columns": [{"name": "id"}, {"name": "total"}]}]
    }
    return client


@pytest.fixture()
def mock_db_client():
    client = AsyncMock()
    result = MagicMock()
    result.columns = ["id", "total"]
    result.rows = [[1, 100], [2, 200]]
    result.to_dict.return_value = {"columns": ["id", "total"], "rows": [[1, 100], [2, 200]]}
    client.execute.return_value = result
    return client


@pytest.fixture()
def factory(mock_kg_client, mock_db_client):
    return KGToolFactory(
        kg_client=mock_kg_client,
        db_client=mock_db_client,
        project_id="proj-1",
        data_source_id="ds-1",
    )


class TestToolDefinitions:
    def test_quick_tier_returns_4_tools(self, factory):
        defs = factory.get_definitions("quick")
        names = [d["name"] for d in defs]
        assert len(names) == 4
        assert "search_kg" in names
        assert "get_table_schema" in names
        assert "execute_sql" in names
        assert "ask_clarification" in names
        assert "get_neighbors" not in names

    def test_deep_tier_returns_7_tools(self, factory):
        defs = factory.get_definitions("deep")
        names = [d["name"] for d in defs]
        assert len(names) == 7
        assert "get_neighbors" in names
        assert "list_datasources" in names
        assert "traverse_path" in names

    def test_tool_definitions_match_anthropic_format(self, factory):
        defs = factory.get_definitions("quick")
        for d in defs:
            assert "name" in d
            assert "description" in d
            assert "input_schema" in d
            assert d["input_schema"]["type"] == "object"


class TestToolExecution:
    @pytest.mark.asyncio
    async def test_search_kg(self, factory, mock_kg_client):
        result = await factory.execute("search_kg", {"query": "revenue"})
        mock_kg_client.search.assert_called_once_with(
            query="revenue", project_id="proj-1", limit=15
        )
        assert "nodes" in result

    @pytest.mark.asyncio
    async def test_get_table_schema(self, factory, mock_kg_client):
        result = await factory.execute("get_table_schema", {"data_source_id": "ds-1"})
        mock_kg_client.get_schema_metadata.assert_called_once_with("ds-1")
        assert "tables" in result

    @pytest.mark.asyncio
    async def test_execute_sql_valid(self, factory, mock_db_client):
        result = await factory.execute("execute_sql", {
            "sql": "SELECT id, total FROM orders",
            "data_source_id": "ds-1",
        })
        mock_db_client.execute.assert_called_once()
        assert "columns" in result

    @pytest.mark.asyncio
    async def test_execute_sql_blocked(self, factory):
        result = await factory.execute("execute_sql", {
            "sql": "DROP TABLE orders",
            "data_source_id": "ds-1",
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_ask_clarification(self, factory):
        result = await factory.execute("ask_clarification", {
            "question": "Which date range?",
            "options": ["Last month", "Last year"],
        })
        assert result["type"] == "clarification"
        assert result["question"] == "Which date range?"


class TestTruncation:
    @pytest.mark.asyncio
    async def test_large_result_truncated(self, factory, mock_kg_client):
        mock_kg_client.search.return_value = {
            "nodes": [{"id": f"n{i}", "label": "x" * 200} for i in range(50)]
        }
        result = await factory.execute("search_kg", {"query": "test"})
        assert len(result.get("nodes", [])) <= 15
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ennam_kg/agentic/tools.py
"""KGToolFactory — tool definitions and executors for the agentic engine."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ennam_kg.agentic.sql_validator import SQLValidationError, validate_sql

if TYPE_CHECKING:
    from ennam_kg.db_client.client import SourceDBClient
    from ennam_kg.kg_client.client import KGClient

logger = logging.getLogger(__name__)

_MAX_KG_NODES = 15
_MAX_DESCRIPTION_CHARS = 100
_MAX_SQL_ROWS = 20


# --- Tool Definitions (Anthropic tool_use format) ---

_SEARCH_KG = {
    "name": "search_kg",
    "description": "Search the knowledge graph for nodes matching a query. Returns concepts, decisions, architecture, requirements, and table metadata.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Natural language search query"},
        },
        "required": ["query"],
    },
}

_GET_NEIGHBORS = {
    "name": "get_neighbors",
    "description": "Get neighboring nodes and edges for a specific KG node. Use to explore graph connections.",
    "input_schema": {
        "type": "object",
        "properties": {
            "node_id": {"type": "string", "description": "The KG node ID to explore"},
        },
        "required": ["node_id"],
    },
}

_GET_TABLE_SCHEMA = {
    "name": "get_table_schema",
    "description": "Get the table schema (columns, types) for a datasource. ALWAYS call this before writing SQL.",
    "input_schema": {
        "type": "object",
        "properties": {
            "data_source_id": {"type": "string", "description": "Datasource ID to get schema for"},
        },
        "required": ["data_source_id"],
    },
}

_EXECUTE_SQL = {
    "name": "execute_sql",
    "description": "Execute a read-only SQL SELECT query on a datasource. Always call get_table_schema first. Never use SELECT *.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "SQL SELECT query to execute"},
            "data_source_id": {"type": "string", "description": "Target datasource ID"},
        },
        "required": ["sql", "data_source_id"],
    },
}

_LIST_DATASOURCES = {
    "name": "list_datasources",
    "description": "List all available datasources for the current project.",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

_ASK_CLARIFICATION = {
    "name": "ask_clarification",
    "description": "Ask the user a clarifying question when the query is ambiguous. The agent loop pauses until the user responds.",
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question to ask the user"},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of suggested answers",
            },
        },
        "required": ["question"],
    },
}

_TRAVERSE_PATH = {
    "name": "traverse_path",
    "description": "Find the shortest path between two KG nodes. Use to understand relationships between concepts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "from_node_id": {"type": "string", "description": "Starting node ID"},
            "to_node_id": {"type": "string", "description": "Target node ID"},
        },
        "required": ["from_node_id", "to_node_id"],
    },
}

_QUICK_TOOLS = [_SEARCH_KG, _GET_TABLE_SCHEMA, _EXECUTE_SQL, _ASK_CLARIFICATION]
_DEEP_TOOLS = [_SEARCH_KG, _GET_NEIGHBORS, _GET_TABLE_SCHEMA, _EXECUTE_SQL, _LIST_DATASOURCES, _ASK_CLARIFICATION, _TRAVERSE_PATH]


class KGToolFactory:
    """Provides tool definitions and executors for the agentic engine."""

    def __init__(
        self,
        kg_client: KGClient,
        db_client: SourceDBClient | None,
        project_id: str,
        data_source_id: str,
    ):
        self._kg = kg_client
        self._db = db_client
        self._project_id = project_id
        self._data_source_id = data_source_id

    def get_definitions(self, tier: str) -> list[dict]:
        if tier == "deep":
            return [dict(d) for d in _DEEP_TOOLS]
        return [dict(d) for d in _QUICK_TOOLS]

    async def execute(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        executor = {
            "search_kg": self._exec_search_kg,
            "get_neighbors": self._exec_get_neighbors,
            "get_table_schema": self._exec_get_table_schema,
            "execute_sql": self._exec_execute_sql,
            "list_datasources": self._exec_list_datasources,
            "ask_clarification": self._exec_ask_clarification,
            "traverse_path": self._exec_traverse_path,
        }.get(tool_name)

        if executor is None:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return await executor(tool_input)
        except Exception as exc:
            logger.error("Tool %s failed: %s", tool_name, exc)
            return {"error": str(exc)}

    async def _exec_search_kg(self, params: dict) -> dict:
        result = await self._kg.search(
            query=params["query"],
            project_id=self._project_id,
            limit=_MAX_KG_NODES,
        )
        return self._truncate_kg_result(result)

    async def _exec_get_neighbors(self, params: dict) -> dict:
        result = await self._kg.get_neighbors(
            node_id=params["node_id"],
            project_id=self._project_id,
        )
        return self._truncate_kg_result(result)

    async def _exec_get_table_schema(self, params: dict) -> dict:
        ds_id = params.get("data_source_id", self._data_source_id)
        return await self._kg.get_schema_metadata(ds_id)

    async def _exec_execute_sql(self, params: dict) -> dict:
        sql = params["sql"]
        try:
            validate_sql(sql)
        except SQLValidationError as exc:
            return {"error": f"SQL blocked: {exc}"}

        if self._db is None:
            return {"error": "No database connection available."}

        result = await self._db.execute(sql, [])
        data = result.to_dict()
        if len(data.get("rows", [])) > _MAX_SQL_ROWS:
            data["rows"] = data["rows"][:_MAX_SQL_ROWS]
            data["truncated"] = True
            data["total_rows"] = len(result.rows)
        return data

    async def _exec_list_datasources(self, _params: dict) -> dict:
        result = await self._kg.search(
            query="datasource",
            project_id=self._project_id,
            node_types=["data_source"],
            limit=20,
        )
        return result

    async def _exec_ask_clarification(self, params: dict) -> dict:
        return {
            "type": "clarification",
            "question": params["question"],
            "options": params.get("options"),
        }

    async def _exec_traverse_path(self, params: dict) -> dict:
        from_result = await self._kg.get_neighbors(
            node_id=params["from_node_id"],
            project_id=self._project_id,
        )
        to_result = await self._kg.get_neighbors(
            node_id=params["to_node_id"],
            project_id=self._project_id,
        )
        return {
            "from_node": params["from_node_id"],
            "to_node": params["to_node_id"],
            "from_neighbors": self._truncate_kg_result(from_result),
            "to_neighbors": self._truncate_kg_result(to_result),
        }

    @staticmethod
    def _truncate_kg_result(result: dict) -> dict:
        nodes = result.get("nodes", [])
        if len(nodes) > _MAX_KG_NODES:
            result = dict(result)
            result["nodes"] = nodes[:_MAX_KG_NODES]
            result["truncated"] = True
        for node in result.get("nodes", []):
            desc = node.get("description", "")
            if len(desc) > _MAX_DESCRIPTION_CHARS:
                node["description"] = desc[:_MAX_DESCRIPTION_CHARS] + "..."
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_tools.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/agentic/tools.py tests/test_agentic/test_tools.py
git commit -m "feat(agentic): add KGToolFactory with 7 tool definitions

Tool definitions in Anthropic format, filtered by tier (4 quick, 7 deep).
Executors delegate to KGClient/SourceDBClient with SQL validation and
result truncation (15 nodes, 20 SQL rows)."
```

---

### Task 7: Prompt Builder — 5-Layer Assembly

**Files:**
- Create: `ennam.kg.python/tests/test_agentic/test_prompts.py`
- Create: `ennam.kg.python/src/ennam_kg/agentic/prompts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agentic/test_prompts.py
"""Tests for layered prompt assembly."""

from ennam_kg.agentic.prompts import build_messages, build_system_prompt


class TestBuildSystemPrompt:
    def test_quick_tier_contains_identity(self):
        prompt = build_system_prompt(tier="quick", kg_context=None, schema_context=None)
        assert "AI analyst" in prompt
        assert "Ennam Knowledge Graph" in prompt

    def test_quick_tier_contains_concise_instruction(self):
        prompt = build_system_prompt(tier="quick", kg_context=None, schema_context=None)
        assert "quickly" in prompt.lower() or "concise" in prompt.lower()

    def test_deep_tier_contains_thorough_instruction(self):
        prompt = build_system_prompt(tier="deep", kg_context=None, schema_context=None)
        assert "thorough" in prompt.lower() or "detailed" in prompt.lower()

    def test_kg_context_injected(self):
        kg = {"nodes": [{"id": "n1", "label": "Revenue concept"}]}
        prompt = build_system_prompt(tier="quick", kg_context=kg, schema_context=None)
        assert "Revenue concept" in prompt

    def test_schema_context_injected(self):
        schema = {"tables": [{"name": "orders", "columns": [{"name": "id"}, {"name": "total"}]}]}
        prompt = build_system_prompt(tier="quick", kg_context=None, schema_context=schema)
        assert "orders" in prompt

    def test_rules_always_present(self):
        prompt = build_system_prompt(tier="quick", kg_context=None, schema_context=None)
        assert "SELECT" in prompt


class TestBuildMessages:
    def test_user_query_only(self):
        msgs = build_messages(query="What is revenue?", context_messages=None)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "What is revenue?"

    def test_with_context_messages(self):
        context = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        msgs = build_messages(query="Follow up?", context_messages=context)
        assert len(msgs) == 3
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello"
        assert msgs[2]["content"] == "Follow up?"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ennam_kg/agentic/prompts.py
"""Layered prompt assembly for the agentic engine."""

from __future__ import annotations

from typing import Any

# --- Layer 1: Agent Identity (shared) ---

_IDENTITY = """You are an AI analyst for the Ennam Knowledge Graph platform.
Your job: answer user questions by searching the knowledge graph and querying connected datasources.

Rules:
- ALWAYS search the KG first before writing SQL
- ONLY generate SELECT statements — never INSERT/UPDATE/DELETE/DROP
- When uncertain, use ask_clarification instead of guessing
- Cite KG nodes by ID when referencing discovered information
- Never call search_kg with the exact same query twice
- Never call execute_sql without first calling get_table_schema
- Never generate SQL with SELECT * — always specify columns
- Never assume table relationships without checking KG edges
"""

_QUICK_GUIDANCE = """
Respond quickly and concisely. Use at most 3 tool calls.
Only query a single datasource. Give a brief answer with data.
Only ask for clarification if the query is truly ambiguous.
"""

_DEEP_GUIDANCE = """
Analyze thoroughly and explore connections. You may use up to 12 tool calls.
You may query multiple datasources if needed. Provide a detailed analysis
with insights and KG citations. Ask for clarification if it would
significantly improve accuracy.
"""


def build_system_prompt(
    *,
    tier: str,
    kg_context: dict[str, Any] | None,
    schema_context: dict[str, Any] | None,
) -> str:
    """Assemble the 5-layer system prompt.

    Layer 1: Agent Identity & Rules (fixed)
    Layer 2: Tier-specific guidance (dynamic per tier)
    Layer 3: KG Context (dynamic, pre-fetched by Go)
    Layer 4: Datasource Schema (dynamic)
    Layer 5: Conversation History (handled in build_messages)
    """
    parts = [_IDENTITY]

    # Layer 2: Tier guidance
    if tier == "deep":
        parts.append(_DEEP_GUIDANCE)
    else:
        parts.append(_QUICK_GUIDANCE)

    # Layer 3: KG context
    if kg_context and kg_context.get("nodes"):
        nodes_text = "\n".join(
            f"- [{n.get('type', 'node')}] {n.get('label', n.get('id', ''))}: {n.get('description', '')[:200]}"
            for n in kg_context["nodes"][:20]
        )
        parts.append(f"\n## Relevant KG Context\n{nodes_text}")

    # Layer 4: Schema context
    if schema_context and schema_context.get("tables"):
        schema_lines = []
        for table in schema_context["tables"]:
            cols = ", ".join(
                c.get("name", "") for c in table.get("columns", [])
            )
            schema_lines.append(f"- {table['name']}: ({cols})")
        parts.append(f"\n## Available Tables\n" + "\n".join(schema_lines))

    return "\n".join(parts)


def build_messages(
    *,
    query: str,
    context_messages: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Build the messages array for the Anthropic API call.

    Includes conversation history (Layer 5) and the current query.
    """
    messages: list[dict[str, Any]] = []

    if context_messages:
        for msg in context_messages:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

    messages.append({"role": "user", "content": query})

    return messages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_prompts.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/agentic/prompts.py tests/test_agentic/test_prompts.py
git commit -m "feat(agentic): add layered prompt builder

5-layer system prompt: identity, tier guidance, KG context,
schema context. build_messages() handles conversation history."
```

---

## Phase 3: Python Engine & API

### Task 8: AgenticEngine — Main Agentic Loop

**Files:**
- Create: `ennam.kg.python/tests/test_agentic/test_engine.py`
- Create: `ennam.kg.python/src/ennam_kg/agentic/engine.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agentic/test_engine.py
"""Tests for AgenticEngine — the main agentic loop."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ennam_kg.agentic.engine import AgenticEngine
from ennam_kg.agentic.types import AgentConfig


@pytest.fixture()
def mock_ai_client():
    client = AsyncMock()
    client._client = AsyncMock()
    client._model = "claude-sonnet-4-5-20250514"
    return client


@pytest.fixture()
def mock_kg_client():
    client = AsyncMock()
    client.search.return_value = {"nodes": [{"id": "n1", "label": "test"}]}
    client.get_schema_metadata.return_value = {
        "tables": [{"name": "orders", "columns": [{"name": "id"}]}]
    }
    return client


@pytest.fixture()
def mock_db_client():
    client = AsyncMock()
    result = MagicMock()
    result.columns = ["id"]
    result.rows = [[1]]
    result.to_dict.return_value = {"columns": ["id"], "rows": [[1]]}
    client.execute.return_value = result
    return client


@pytest.fixture()
def mock_state_store():
    return AsyncMock()


def _make_anthropic_response(*, stop_reason="end_turn", content=None, tool_use=None):
    """Build a mock Anthropic Message response."""
    msg = MagicMock()
    msg.stop_reason = stop_reason
    msg.usage = MagicMock(input_tokens=500, output_tokens=200)

    blocks = []
    if content:
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = content
        blocks.append(text_block)
    if tool_use:
        for tc in tool_use:
            tu_block = MagicMock()
            tu_block.type = "tool_use"
            tu_block.id = tc["id"]
            tu_block.name = tc["name"]
            tu_block.input = tc["input"]
            blocks.append(tu_block)
    msg.content = blocks
    return msg


class TestEngineCreation:
    def test_creates_with_config(self, mock_ai_client, mock_kg_client, mock_db_client, mock_state_store):
        config = AgentConfig(tier="quick")
        engine = AgenticEngine(
            ai_client=mock_ai_client,
            kg_client=mock_kg_client,
            db_client=mock_db_client,
            state_store=mock_state_store,
            config=config,
        )
        assert engine._config.tier == "quick"
        assert engine._config.max_iterations == 3


class TestEngineEndTurn:
    @pytest.mark.asyncio
    async def test_simple_end_turn_yields_events(self, mock_ai_client, mock_kg_client, mock_db_client, mock_state_store):
        """When Anthropic returns end_turn immediately, emit agent_start + content + agent_done."""
        config = AgentConfig(tier="quick")
        engine = AgenticEngine(
            ai_client=mock_ai_client,
            kg_client=mock_kg_client,
            db_client=mock_db_client,
            state_store=mock_state_store,
            config=config,
        )

        mock_ai_client._client.messages.create.return_value = _make_anthropic_response(
            stop_reason="end_turn",
            content="The answer is 42."
        )

        events = []
        async for event in engine.stream(
            project_id="p1", data_source_id="ds1",
            thread_id="t1", message_id="m1",
            query="What is 42?",
        ):
            events.append(event)

        event_types = [e.event for e in events]
        assert "agent_start" in event_types
        assert "content" in event_types
        assert "agent_done" in event_types


class TestEngineToolUse:
    @pytest.mark.asyncio
    async def test_tool_use_then_end_turn(self, mock_ai_client, mock_kg_client, mock_db_client, mock_state_store):
        """Engine calls tool, then gets end_turn."""
        config = AgentConfig(tier="quick")
        engine = AgenticEngine(
            ai_client=mock_ai_client,
            kg_client=mock_kg_client,
            db_client=mock_db_client,
            state_store=mock_state_store,
            config=config,
        )

        resp1 = _make_anthropic_response(
            stop_reason="tool_use",
            tool_use=[{"id": "tc1", "name": "search_kg", "input": {"query": "test"}}],
        )
        resp2 = _make_anthropic_response(
            stop_reason="end_turn",
            content="Found: test node."
        )
        mock_ai_client._client.messages.create.side_effect = [resp1, resp2]

        events = []
        async for event in engine.stream(
            project_id="p1", data_source_id="ds1",
            thread_id="t1", message_id="m1",
            query="Search test",
        ):
            events.append(event)

        event_types = [e.event for e in events]
        assert "tool_call_start" in event_types
        assert "tool_call_end" in event_types
        assert "agent_done" in event_types


class TestEngineBudgetExceeded:
    @pytest.mark.asyncio
    async def test_budget_exceeded_forces_synthesis(self, mock_ai_client, mock_kg_client, mock_db_client, mock_state_store):
        """When max iterations reached, force synthesize."""
        config = AgentConfig(tier="quick")  # max 3 iterations
        engine = AgenticEngine(
            ai_client=mock_ai_client,
            kg_client=mock_kg_client,
            db_client=mock_db_client,
            state_store=mock_state_store,
            config=config,
        )

        tool_resp = _make_anthropic_response(
            stop_reason="tool_use",
            tool_use=[{"id": "tc1", "name": "search_kg", "input": {"query": "test"}}],
        )
        final_resp = _make_anthropic_response(
            stop_reason="end_turn",
            content="Budget exceeded summary."
        )
        mock_ai_client._client.messages.create.side_effect = [
            tool_resp, tool_resp, tool_resp, final_resp
        ]

        events = []
        async for event in engine.stream(
            project_id="p1", data_source_id="ds1",
            thread_id="t1", message_id="m1",
            query="Test budget",
        ):
            events.append(event)

        event_types = [e.event for e in events]
        assert "agent_done" in event_types
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

See `src/ennam_kg/agentic/engine.py` — the full implementation is documented in the design spec (Section 3.2). Key behaviors:

- Async generator yielding `SSEEvent` instances
- FSM: EXPLORE → PLAN → EXECUTE → SYNTHESIZE
- Calls `self._ai._client.messages.create()` directly (raw Anthropic SDK)
- LoopGuard checks before each tool execution
- Clarification pauses via `AgentStateStore.save()` + `clarification_request` event
- Budget exceeded → forced synthesis with collected data
- SSE events: `agent_start`, `tool_call_start`, `tool_call_end`, `content`, `agent_done`, `done`

The engine imports `SSEEvent` from `ennam_kg.streaming.models` and defines its own Pydantic data models (`AgentStartData`, `ToolCallStartData`, `ToolCallEndData`, `AgentDoneData`, `ClarificationRequestData`, `ContentData`, `DoneData`) for the new agentic SSE event payloads.

```python
# src/ennam_kg/agentic/engine.py
"""AgenticEngine — iterative tool-calling agent loop."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, AsyncGenerator

from pydantic import BaseModel

from ennam_kg.agentic.loop_guard import LoopGuard
from ennam_kg.agentic.prompts import build_messages, build_system_prompt
from ennam_kg.agentic.tools import KGToolFactory
from ennam_kg.agentic.types import (
    AgentConfig,
    AgentState,
    LoopState,
    ToolCall,
)
from ennam_kg.streaming.models import SSEEvent

if TYPE_CHECKING:
    from ennam_kg.agentic.state_store import AgentStateStore
    from ennam_kg.ai_client.direct_client import AnthropicDirectClient
    from ennam_kg.db_client.client import SourceDBClient
    from ennam_kg.kg_client.client import KGClient

logger = logging.getLogger(__name__)


# --- Agentic SSE event data models ---

class AgentStartData(BaseModel):
    tier: str
    max_iterations: int

class ToolCallStartData(BaseModel):
    tool: str
    input: dict[str, Any] = {}
    iteration: int

class ToolCallEndData(BaseModel):
    tool: str
    success: bool
    summary: str = ""
    duration_ms: int = 0

class AgentDoneData(BaseModel):
    iterations: int
    budget_exceeded: bool = False
    total_tokens: int = 0
    tools_used: list[str] = []

class ClarificationRequestData(BaseModel):
    session_id: str
    question: str
    options: list[str] | None = None
    timeout_seconds: int = 600

class ContentData(BaseModel):
    data: str

class DoneData(BaseModel):
    status: str = "complete"


class AgenticEngine:
    """Runs the agentic loop: EXPLORE -> PLAN -> EXECUTE -> SYNTHESIZE."""

    def __init__(
        self,
        *,
        ai_client: AnthropicDirectClient,
        kg_client: KGClient,
        db_client: SourceDBClient | None,
        state_store: AgentStateStore,
        config: AgentConfig,
    ):
        self._ai = ai_client
        self._kg = kg_client
        self._db = db_client
        self._state_store = state_store
        self._config = config
        self._guard = LoopGuard(
            max_tool_calls=config.max_iterations,
            max_node_visits=3,
        )

    async def stream(
        self,
        *,
        project_id: str,
        data_source_id: str,
        thread_id: str,
        message_id: str,
        query: str,
        context_messages: list[dict[str, Any]] | None = None,
        kg_context: dict[str, Any] | None = None,
        schema_context: dict[str, Any] | None = None,
        clarification_session_id: str | None = None,
    ) -> AsyncGenerator[SSEEvent, None]:
        """Run the agentic loop, yielding SSE events."""
        tool_factory = KGToolFactory(
            kg_client=self._kg,
            db_client=self._db,
            project_id=project_id,
            data_source_id=data_source_id,
        )

        # Resume from clarification or start fresh
        if clarification_session_id:
            state = await self._state_store.restore(clarification_session_id)
            loop_state = state.loop_state
            messages = state.messages
        else:
            loop_state = LoopState()
            messages = build_messages(
                query=query,
                context_messages=context_messages,
            )

        system_prompt = build_system_prompt(
            tier=self._config.tier,
            kg_context=kg_context,
            schema_context=schema_context,
        )
        tool_defs = tool_factory.get_definitions(self._config.tier)
        tools_used: list[str] = []

        # Emit agent_start
        yield SSEEvent(
            event="agent_start",
            data=AgentStartData(
                tier=self._config.tier,
                max_iterations=self._config.max_iterations,
            ),
        )

        while loop_state.can_continue(self._config):
            # Call Anthropic API
            response = await self._ai._client.messages.create(
                model=self._ai._model,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
                tools=tool_defs,
            )

            # Track token usage
            loop_state.tokens_used += (
                response.usage.input_tokens + response.usage.output_tokens
            )

            if response.stop_reason == "end_turn":
                for block in response.content:
                    if block.type == "text" and block.text:
                        yield SSEEvent(
                            event="content",
                            data=ContentData(data=block.text),
                        )
                break

            elif response.stop_reason == "tool_use":
                tool_results_for_api = []

                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    tc = ToolCall(id=block.id, name=block.name, input=block.input)

                    # LoopGuard check
                    guard_result = self._guard.check(tc, loop_state)
                    if not guard_result.allowed:
                        logger.info("LoopGuard blocked: %s — %s", tc.name, guard_result.reason)
                        tool_results_for_api.append({
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": f"Blocked: {guard_result.reason}",
                            "is_error": True,
                        })
                        continue

                    yield SSEEvent(
                        event="tool_call_start",
                        data=ToolCallStartData(
                            tool=tc.name,
                            input=tc.input,
                            iteration=loop_state.iteration,
                        ),
                    )

                    start_ms = int(time.time() * 1000)
                    result = await tool_factory.execute(tc.name, tc.input)
                    duration_ms = int(time.time() * 1000) - start_ms

                    loop_state.tool_calls.append(tc)
                    if tc.name not in tools_used:
                        tools_used.append(tc.name)

                    if tc.name in ("get_neighbors", "traverse_path"):
                        node_id = tc.input.get("node_id", "")
                        if node_id:
                            loop_state.visited_nodes.add(node_id)

                    # Handle clarification
                    if result.get("type") == "clarification":
                        session_id = str(uuid.uuid4())
                        state = AgentState(
                            messages=messages,
                            loop_state=loop_state,
                            project_id=project_id,
                            data_source_id=data_source_id,
                            thread_id=thread_id,
                            message_id=message_id,
                            tier=self._config.tier,
                        )
                        await self._state_store.save(session_id, state)

                        yield SSEEvent(
                            event="clarification_request",
                            data=ClarificationRequestData(
                                session_id=session_id,
                                question=result["question"],
                                options=result.get("options"),
                            ),
                        )
                        yield SSEEvent(
                            event="done",
                            data=DoneData(status="awaiting_clarification"),
                        )
                        return

                    is_error = "error" in result
                    summary = result.get("error", "")
                    if not is_error:
                        if "nodes" in result:
                            summary = f"{len(result['nodes'])} nodes found"
                        elif "columns" in result:
                            rows = result.get("rows", [])
                            summary = f"{len(rows)} rows returned"

                    yield SSEEvent(
                        event="tool_call_end",
                        data=ToolCallEndData(
                            tool=tc.name,
                            success=not is_error,
                            summary=summary,
                            duration_ms=duration_ms,
                        ),
                    )

                    tool_results_for_api.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": json.dumps(result),
                        "is_error": is_error,
                    })

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results_for_api})
                loop_state.iteration += 1
            else:
                break

        # Budget exceeded — force synthesis
        if not loop_state.can_continue(self._config):
            response = await self._ai._client.messages.create(
                model=self._ai._model,
                max_tokens=4096,
                system=system_prompt + "\n\nYou have reached the tool call budget. Synthesize your answer from the data collected so far.",
                messages=messages,
            )
            loop_state.tokens_used += (
                response.usage.input_tokens + response.usage.output_tokens
            )
            for block in response.content:
                if block.type == "text" and block.text:
                    yield SSEEvent(
                        event="content",
                        data=ContentData(data=block.text),
                    )

        yield SSEEvent(
            event="agent_done",
            data=AgentDoneData(
                iterations=loop_state.iteration,
                budget_exceeded=not loop_state.can_continue(self._config),
                total_tokens=loop_state.tokens_used,
                tools_used=tools_used,
            ),
        )

        yield SSEEvent(event="done", data=DoneData(status="complete"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_engine.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/agentic/engine.py tests/test_agentic/test_engine.py
git commit -m "feat(agentic): add AgenticEngine with FSM-based agentic loop

EXPLORE -> PLAN -> EXECUTE -> SYNTHESIZE with LoopGuard protection.
Handles tool_use, clarification pause/resume, budget enforcement.
Yields SSE events (agent_start, tool_call_start/end, content, agent_done)."
```

---

### Task 9: FastAPI Route — POST /api/v1/agentic/stream

**Files:**
- Create: `ennam.kg.python/tests/test_agentic/test_api.py`
- Create: `ennam.kg.python/src/ennam_kg/api/agentic.py`
- Modify: `ennam.kg.python/src/ennam_kg/main.py` (add router)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agentic/test_api.py
"""Tests for the agentic streaming API route."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ennam_kg.api.agentic import router


@pytest.fixture()
def app():
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.http_client = AsyncMock()
    return test_app


@pytest.fixture()
def client(app):
    return TestClient(app)


class TestAgenticRoute:
    def test_missing_required_fields_returns_422(self, client):
        resp = client.post("/api/v1/agentic/stream", json={})
        assert resp.status_code == 422

    def test_valid_request_returns_sse_content_type(self, client):
        with patch("ennam_kg.api.agentic._create_engine") as mock_create:
            async def fake_stream(**kwargs):
                from ennam_kg.streaming.models import SSEEvent
                from ennam_kg.agentic.engine import DoneData
                yield SSEEvent(event="done", data=DoneData(status="complete"))

            mock_engine = MagicMock()
            mock_engine.stream = fake_stream
            mock_create.return_value = (mock_engine, [])

            resp = client.post(
                "/api/v1/agentic/stream",
                json={
                    "project_id": "p1",
                    "data_source_id": "ds1",
                    "query": "test",
                    "thread_id": "t1",
                    "message_id": "m1",
                    "tier": "quick",
                },
                headers={"x-ai-api-key": "test-key", "x-ai-model-id": "claude-sonnet-4-5-20250514"},
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

```python
# src/ennam_kg/api/agentic.py
"""FastAPI route for agentic AI streaming."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ennam_kg.agentic.engine import AgenticEngine
from ennam_kg.agentic.state_store import AgentStateStore
from ennam_kg.agentic.types import AgentConfig
from ennam_kg.ai_client.direct_client import AnthropicDirectClient
from ennam_kg.config import settings
from ennam_kg.db_client.client import SourceDBClient
from ennam_kg.kg_client.client import KGClient
from ennam_kg.streaming.models import SSEError, SSEEvent, format_sse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agentic", tags=["agentic"])


class AgenticStreamRequest(BaseModel):
    project_id: str
    data_source_id: str
    query: str
    thread_id: str
    message_id: str
    tier: str = "quick"
    context_messages: list[dict[str, Any]] | None = None
    kg_context: dict[str, Any] | None = None
    schema_context: dict[str, Any] | None = None
    clarification_session_id: str | None = None
    dialect: str | None = None


async def _create_engine(
    request: Request,
    body: AgenticStreamRequest,
    api_key: str,
    model_id: str,
    db_dsn: str | None,
) -> tuple[AgenticEngine, list]:
    """Create engine and collect cleanup callbacks."""
    cleanups = []

    ai_client = AnthropicDirectClient(api_key=api_key, model_id=model_id)
    cleanups.append(ai_client.close)

    kg_client = KGClient(
        base_url=settings.go_api_url,
        api_key=settings.go_api_key,
        http_client=request.app.state.http_client,
    )

    db_client = None
    if db_dsn:
        dialect = body.dialect or "postgresql"
        db_client = SourceDBClient(dsn=db_dsn, dialect=dialect, row_limit=50, timeout=30)
        cleanups.append(db_client.close)

    import redis.asyncio as aioredis
    redis_conn = aioredis.from_url(settings.redis_url)
    cleanups.append(redis_conn.aclose)
    state_store = AgentStateStore(redis_conn)

    config = AgentConfig(tier=body.tier)
    engine = AgenticEngine(
        ai_client=ai_client,
        kg_client=kg_client,
        db_client=db_client,
        state_store=state_store,
        config=config,
    )
    return engine, cleanups


@router.post("/stream")
async def agentic_stream(
    request: Request,
    body: AgenticStreamRequest,
    x_ai_api_key: str = Header(...),
    x_ai_model_id: str = Header(...),
    x_db_dsn: str | None = Header(None),
):
    """Agentic AI streaming endpoint — runs the full agent loop."""
    engine, cleanups = await _create_engine(
        request, body, x_ai_api_key, x_ai_model_id, x_db_dsn,
    )

    async def event_generator():
        try:
            async for event in engine.stream(
                project_id=body.project_id,
                data_source_id=body.data_source_id,
                thread_id=body.thread_id,
                message_id=body.message_id,
                query=body.query,
                context_messages=body.context_messages,
                kg_context=body.kg_context,
                schema_context=body.schema_context,
                clarification_session_id=body.clarification_session_id,
            ):
                yield format_sse(event)
        except Exception as exc:
            logger.exception("Agentic stream error: %s", exc)
            yield format_sse(SSEEvent(
                event="error",
                data=SSEError(error_code="agentic_error", error_message=str(exc)),
            ))
        finally:
            for cleanup in cleanups:
                try:
                    await cleanup()
                except Exception:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/test_api.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Wire router into main.py**

Add to `ennam_kg/main.py`, after existing router includes:

```python
from ennam_kg.api.agentic import router as agentic_router
app.include_router(agentic_router)
```

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/api/agentic.py src/ennam_kg/main.py tests/test_agentic/test_api.py
git commit -m "feat(agentic): add POST /api/v1/agentic/stream route

FastAPI endpoint constructs AgenticEngine with tier-based config,
streams SSE events. Handles cleanup of AI/DB/Redis clients."
```

---

### Task 10: Package Exports

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/agentic/__init__.py`

- [ ] **Step 1: Update __init__.py with public exports**

```python
# src/ennam_kg/agentic/__init__.py
"""Agentic AI engine — iterative tool-calling agent loop."""

from ennam_kg.agentic.engine import AgenticEngine
from ennam_kg.agentic.loop_guard import LoopGuard
from ennam_kg.agentic.sql_validator import SQLValidationError, validate_sql
from ennam_kg.agentic.state_store import AgentStateStore, SessionExpiredError
from ennam_kg.agentic.tools import KGToolFactory
from ennam_kg.agentic.types import AgentConfig, AgentPhase, AgentState, LoopState, ToolCall, ToolResult

__all__ = [
    "AgenticEngine",
    "AgentConfig",
    "AgentPhase",
    "AgentState",
    "AgentStateStore",
    "KGToolFactory",
    "LoopGuard",
    "LoopState",
    "SQLValidationError",
    "SessionExpiredError",
    "ToolCall",
    "ToolResult",
    "validate_sql",
]
```

- [ ] **Step 2: Verify all tests pass**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/ -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/agentic/__init__.py
git commit -m "feat(agentic): add package __init__ with public exports"
```

---

## Phase 4: Go API Integration

### Task 11: ThreadMessage Model — Agentic Fields

**Files:**
- Modify: `ennam.kg.go/internal/models/thread.go`

- [ ] **Step 1: Add agentic fields to ThreadMessage struct**

Add these fields after `SuggestedActions` in the `ThreadMessage` struct (around line 64):

```go
// Agentic AI metadata
AgentTier              *string         `json:"agent_tier,omitempty" db:"agent_tier"`
AgentIterations        *int            `json:"agent_iterations,omitempty" db:"agent_iterations"`
AgentToolsUsed         []string        `json:"agent_tools_used,omitempty" db:"agent_tools_used"`
AgentTotalTokens       *int            `json:"agent_total_tokens,omitempty" db:"agent_total_tokens"`
ClarificationSessionID *string        `json:"clarification_session_id,omitempty" db:"clarification_session_id"`
ClarificationStatus    *string         `json:"clarification_status,omitempty" db:"clarification_status"`
```

- [ ] **Step 2: Verify Go build**

Run: `cd ennam.kg.go && go build ./...`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
cd ennam.kg.go
git add internal/models/thread.go
git commit -m "feat(models): add agentic metadata fields to ThreadMessage

agent_tier, agent_iterations, agent_tools_used, agent_total_tokens,
clarification_session_id, clarification_status."
```

---

### Task 12: SSE Stream Service — Tier-Aware Timeout & Agentic Routing

**Files:**
- Modify: `ennam.kg.go/internal/service/sse_stream.go`

- [ ] **Step 1: Add agentTimeout helper**

```go
// agentTimeout returns the appropriate stream timeout for the given tier.
func agentTimeout(tier string) time.Duration {
	if tier == "deep" {
		return 10 * time.Minute
	}
	return 5 * time.Minute
}
```

- [ ] **Step 2: Add ClarificationSessionID to StreamRequest**

Add to the `StreamRequest` struct:

```go
ClarificationSessionID string `json:"clarification_session_id,omitempty"`
```

- [ ] **Step 3: Add pythonEndpoint routing method**

```go
// pythonEndpoint returns the Python worker URL path based on request params.
func pythonEndpoint(req StreamRequest) string {
	if req.Tier != "" || req.ClarificationSessionID != "" {
		return "/api/v1/agentic/stream"
	}
	return "/api/v1/ai/stream"
}
```

- [ ] **Step 4: Verify Go build**

Run: `cd ennam.kg.go && go build ./...`
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.go
git add internal/service/sse_stream.go
git commit -m "feat(sse): add tier-aware timeout and agentic endpoint routing

agentTimeout returns 5min (quick) or 10min (deep).
pythonEndpoint routes to /api/v1/agentic/stream when tier is set."
```

---

### Task 13: HandleClarification — POST Endpoint

**Files:**
- Modify: `ennam.kg.go/internal/handler/ai_stream.go`
- Modify: `ennam.kg.go/internal/handler/routes.go`

- [ ] **Step 1: Add clarification request type and handler**

Add to `ai_stream.go`:

```go
type clarificationRequest struct {
	ThreadID  string `json:"thread_id"`
	SessionID string `json:"session_id"`
	Response  string `json:"response"`
}

// HandleClarification handles POST /api/v1/ai/clarification.
func (h *AIStreamHandler) HandleClarification(w http.ResponseWriter, r *http.Request) {
	var req clarificationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid JSON body", http.StatusBadRequest)
		return
	}

	if req.ThreadID == "" || req.SessionID == "" || req.Response == "" {
		http.Error(w, "thread_id, session_id, and response are required", http.StatusBadRequest)
		return
	}

	ctx := r.Context()
	msg := models.ThreadMessage{
		ID:                     uuid.NewString(),
		ThreadID:               req.ThreadID,
		Role:                   models.RoleUser,
		Content:                req.Response,
		ClarificationSessionID: &req.SessionID,
	}

	if _, err := h.messageStore.Create(ctx, msg); err != nil {
		log.Printf("ERROR: failed to persist clarification message: %v", err)
		http.Error(w, "failed to persist message", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"status":     "ok",
		"session_id": req.SessionID,
		"message_id": msg.ID,
	})
}
```

- [ ] **Step 2: Register route in routes.go**

```go
r.Post("/api/v1/ai/clarification", h.aiStream.HandleClarification)
```

- [ ] **Step 3: Verify Go build**

Run: `cd ennam.kg.go && go build ./...`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.go
git add internal/handler/ai_stream.go internal/handler/routes.go
git commit -m "feat(handler): add POST /api/v1/ai/clarification endpoint

Persists user clarification response as thread message,
returns session_id and message_id for stream resume."
```

---

### Task 14: Store — UpdateAgentMetadata

**Files:**
- Modify: `ennam.kg.go/internal/store/thread_message.go`

- [ ] **Step 1: Add UpdateAgentMetadata function**

```go
// UpdateAgentMetadata updates the agentic fields on a thread message.
func (s *ThreadMessageStore) UpdateAgentMetadata(ctx context.Context, messageID string, tier string, iterations int, toolsUsed []string, totalTokens int) error {
	query := `
		UPDATE thread_messages
		SET agent_tier = $2,
		    agent_iterations = $3,
		    agent_tools_used = $4,
		    agent_total_tokens = $5
		WHERE id = $1
	`
	_, err := s.db.ExecContext(ctx, query, messageID, tier, iterations, pq.Array(toolsUsed), totalTokens)
	return err
}
```

- [ ] **Step 2: Verify Go build**

Run: `cd ennam.kg.go && go build ./...`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
cd ennam.kg.go
git add internal/store/thread_message.go
git commit -m "feat(store): add UpdateAgentMetadata for agentic fields

Updates agent_tier, agent_iterations, agent_tools_used,
agent_total_tokens on thread_messages after agent completion."
```

---

## Phase 5: Frontend Types & Streaming

### Task 15: Agentic TypeScript Types

**Files:**
- Create: `ennam.kg.next/src/types/agentic.ts`

- [ ] **Step 1: Create agentic type definitions**

```typescript
// src/types/agentic.ts

export type AgentTier = 'quick' | 'deep';
export type AgentPhase = 'EXPLORE' | 'PLAN' | 'EXECUTE' | 'SYNTHESIZE';
export type ToolCallStatus = 'pending' | 'running' | 'success' | 'error';

export interface AgentStartEvent {
  tier: AgentTier;
  max_iterations: number;
}

export interface ToolCallStartEvent {
  tool: string;
  input: Record<string, unknown>;
  iteration: number;
}

export interface ToolCallEndEvent {
  tool: string;
  success: boolean;
  summary: string;
  duration_ms: number;
}

export interface AgentReasoningEvent {
  phase: AgentPhase;
}

export interface AgentDoneEvent {
  iterations: number;
  budget_exceeded: boolean;
  total_tokens: number;
  tools_used: string[];
}

export interface ClarificationRequestEvent {
  session_id: string;
  question: string;
  options?: string[];
  timeout_seconds: number;
}

export interface KgNodeReferenceEvent {
  node_id: string;
  node_type: string;
  label: string;
}

export interface DatasourceResultEvent {
  datasource: string;
  row_count: number;
  error?: string;
}

export interface ToolCallStep {
  id: string;
  tool: string;
  input: Record<string, unknown>;
  iteration: number;
  status: ToolCallStatus;
  summary?: string;
  durationMs?: number;
  startedAt: number;
}

export interface ClarificationState {
  sessionId: string;
  question: string;
  options?: string[];
  timeoutSeconds: number;
  startedAt: number;
}

export interface AgenticStreamState {
  isStreaming: boolean;
  tier: AgentTier;
  phase: AgentPhase;
  steps: ToolCallStep[];
  content: string;
  clarification: ClarificationState | null;
  kgNodeRefs: KgNodeReferenceEvent[];
  datasourceResults: DatasourceResultEvent[];
  done: AgentDoneEvent | null;
  error: string | null;
}

export const INITIAL_AGENTIC_STATE: AgenticStreamState = {
  isStreaming: false,
  tier: 'quick',
  phase: 'EXPLORE',
  steps: [],
  content: '',
  clarification: null,
  kgNodeRefs: [],
  datasourceResults: [],
  done: null,
  error: null,
};
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd ennam.kg.next && npx tsc --noEmit src/types/agentic.ts`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
cd ennam.kg.next
git add src/types/agentic.ts
git commit -m "feat(types): add agentic AI type definitions

SSE event types, ToolCallStep, ClarificationState,
AgenticStreamState with initial state constant."
```

---

### Task 16: Extend SSE Handler — Agentic Callbacks

**Files:**
- Modify: `ennam.kg.next/src/lib/streaming/sse-handler.ts`

- [ ] **Step 1: Add agentic imports and callback types**

Add import at top:

```typescript
import type {
  AgentStartEvent, ToolCallStartEvent, ToolCallEndEvent,
  AgentReasoningEvent, AgentDoneEvent, ClarificationRequestEvent,
  KgNodeReferenceEvent, DatasourceResultEvent,
} from '@/types/agentic';
```

Add to `StreamCallbacks` interface:

```typescript
onAgentStart?: (data: AgentStartEvent) => void;
onToolCallStart?: (data: ToolCallStartEvent) => void;
onToolCallEnd?: (data: ToolCallEndEvent) => void;
onAgentReasoning?: (data: AgentReasoningEvent) => void;
onAgentDone?: (data: AgentDoneEvent) => void;
onClarificationRequest?: (data: ClarificationRequestEvent) => void;
onKgNodeReference?: (data: KgNodeReferenceEvent) => void;
onDatasourceResult?: (data: DatasourceResultEvent) => void;
```

- [ ] **Step 2: Add event routing cases**

In the event parsing switch statement, add:

```typescript
case 'agent_start': callbacks.onAgentStart?.(parsed); break;
case 'tool_call_start': callbacks.onToolCallStart?.(parsed); break;
case 'tool_call_end': callbacks.onToolCallEnd?.(parsed); break;
case 'agent_reasoning': callbacks.onAgentReasoning?.(parsed); break;
case 'agent_done': callbacks.onAgentDone?.(parsed); break;
case 'clarification_request': callbacks.onClarificationRequest?.(parsed); break;
case 'kg_node_reference': callbacks.onKgNodeReference?.(parsed); break;
case 'datasource_result': callbacks.onDatasourceResult?.(parsed); break;
```

- [ ] **Step 3: Verify build**

Run: `cd ennam.kg.next && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.next
git add src/lib/streaming/sse-handler.ts
git commit -m "feat(streaming): extend SSE handler with 8 agentic callbacks

agent_start, tool_call_start/end, agent_reasoning, agent_done,
clarification_request, kg_node_reference, datasource_result."
```

---

### Task 17: useAgenticStream Hook

**Files:**
- Create: `ennam.kg.next/src/hooks/use-agentic-stream.ts`

- [ ] **Step 1: Create the hook**

The `useAgenticStream` hook manages the full agentic SSE lifecycle:
- `start(request)`: begins a new agentic stream
- `abort()`: cancels the current stream
- `resumeFromClarification(sessionId, threadId, response, tier)`: POSTs clarification and resumes

State tracked: `isStreaming`, `tier`, `phase`, `steps[]`, `content`, `clarification`, `kgNodeRefs[]`, `datasourceResults[]`, `done`, `error`.

Uses `startStream()` from `sse-handler.ts` with all 8 agentic callbacks wired to `setState()` reducers. Maps `onToolCallStart` → add step with status `'running'`, `onToolCallEnd` → update last running step's status/summary/duration.

See full implementation in Phase 5 section of design spec — the hook follows the same pattern as existing `useStreamQuery()` in `use-thread-messages.ts`.

- [ ] **Step 2: Verify build**

Run: `cd ennam.kg.next && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
cd ennam.kg.next
git add src/hooks/use-agentic-stream.ts
git commit -m "feat(hooks): add useAgenticStream hook

Manages full agentic SSE lifecycle: steps, phases, clarification
pause/resume, content accumulation, KG refs, datasource results."
```

---

## Phase 6: Frontend Components

### Task 18: TierSelector Component

**Files:**
- Create: `ennam.kg.next/src/components/chat/TierSelector.tsx`

- [ ] **Step 1: Create TierSelector**

Segmented control with Quick (default) and Deep buttons. Persists choice in `localStorage` per thread. Props: `threadId`, `disabled`, `onChange(tier)`.

Styling: `bg-gray-100` container, active button gets `bg-white shadow-sm`, Deep mode active gets `text-blue-600`.

- [ ] **Step 2: Verify build**

Run: `cd ennam.kg.next && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
cd ennam.kg.next
git add src/components/chat/TierSelector.tsx
git commit -m "feat(chat): add TierSelector segmented control

Quick/Deep toggle with localStorage persistence per thread."
```

---

### Task 19: AgenticProgress + PhaseIndicator + ToolCallStepRow

**Files:**
- Create: `ennam.kg.next/src/components/chat/PhaseIndicator.tsx`
- Create: `ennam.kg.next/src/components/chat/ToolCallStepRow.tsx`
- Create: `ennam.kg.next/src/components/chat/AgenticProgress.tsx`

- [ ] **Step 1: Create PhaseIndicator**

Badge with color per phase: EXPLORE (green), PLAN (yellow), EXECUTE (blue), SYNTHESIZE (purple).

- [ ] **Step 2: Create ToolCallStepRow**

Single row with: tool icon (lucide icons mapped per tool name), tool name in monospace, status indicator (running = animate-pulse blue, success = green, error = red), summary text, duration in ms.

Tool icon map: `search_kg` → Search, `get_neighbors` → GitBranch, `get_table_schema` → Table2, `execute_sql` → Database, `list_datasources` → List, `ask_clarification` → MessageCircle, `traverse_path` → Route.

- [ ] **Step 3: Create AgenticProgress**

Collapsible container: header with chevron + PhaseIndicator + step count + iteration count. Body: list of ToolCallStepRow. Auto-expands during streaming, user can toggle.

- [ ] **Step 4: Verify build**

Run: `cd ennam.kg.next && npm run build`
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.next
git add src/components/chat/PhaseIndicator.tsx src/components/chat/ToolCallStepRow.tsx src/components/chat/AgenticProgress.tsx
git commit -m "feat(chat): add AgenticProgress timeline components

PhaseIndicator (phase badge), ToolCallStepRow (step with icon/status),
AgenticProgress (collapsible timeline, auto-expand during streaming)."
```

---

### Task 20: ClarificationPrompt + CountdownRing

**Files:**
- Create: `ennam.kg.next/src/components/chat/CountdownRing.tsx`
- Create: `ennam.kg.next/src/components/chat/ClarificationPrompt.tsx`

- [ ] **Step 1: Create CountdownRing**

SVG circle with `stroke-dasharray`/`stroke-dashoffset` animation. Shows `mm:ss` in center. Turns red under 60s. Calls `onExpired()` when countdown reaches 0.

- [ ] **Step 2: Create ClarificationPrompt**

Inline form with: question text, optional option buttons (click = submit immediately), free-text input + Send button, CountdownRing in top-right. States: active → submitted ("Response sent. Resuming...") → expired ("Session expired. Please re-ask.").

- [ ] **Step 3: Verify build**

Run: `cd ennam.kg.next && npm run build`
Expected: Build succeeds

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.next
git add src/components/chat/CountdownRing.tsx src/components/chat/ClarificationPrompt.tsx
git commit -m "feat(chat): add ClarificationPrompt with countdown timer

Inline form with option buttons, free-text input, SVG CountdownRing
(600s TTL). Handles expiration and submission states."
```

---

### Task 21: KgNodeChip Component

**Files:**
- Create: `ennam.kg.next/src/components/chat/KgNodeChip.tsx`

- [ ] **Step 1: Create KgNodeChip**

Inline rounded-full badge with: icon per node type (6 types), truncated label (max 120px), click handler. Color per type using Tailwind (architecture=blue, decision=amber, concept=purple, requirement=green, task=gray, discovery=teal).

- [ ] **Step 2: Verify build**

Run: `cd ennam.kg.next && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
cd ennam.kg.next
git add src/components/chat/KgNodeChip.tsx
git commit -m "feat(chat): add KgNodeChip clickable KG reference badge

Icon per node type, truncated label, click handler for graph navigation."
```

---

### Task 22: MultiSourceResults Component

**Files:**
- Create: `ennam.kg.next/src/components/chat/MultiSourceResults.tsx`

- [ ] **Step 1: Create MultiSourceResults**

Single-source: compact inline display. Multi-source: tabbed interface, one tab per datasource. Each tab shows: datasource name + Database icon, row count or error message. Error state: AlertCircle icon + red text.

- [ ] **Step 2: Verify build**

Run: `cd ennam.kg.next && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
cd ennam.kg.next
git add src/components/chat/MultiSourceResults.tsx
git commit -m "feat(chat): add MultiSourceResults tabbed display

Tabbed datasource results for Deep mode cross-datasource queries.
Error state per tab, single-source compact view."
```

---

## Phase 7: Frontend Wiring

### Task 23: Wire Agentic Components into Chat UI

**Files:**
- Modify: `ennam.kg.next/src/components/chat/ChatMessage.tsx`
- Modify: `ennam.kg.next/src/components/chat/QueryInputBar.tsx`

- [ ] **Step 1: Import agentic components in ChatMessage.tsx**

```tsx
import { AgenticProgress } from './AgenticProgress';
import { ClarificationPrompt } from './ClarificationPrompt';
import { KgNodeChip } from './KgNodeChip';
import { MultiSourceResults } from './MultiSourceResults';
import type { AgenticStreamState } from '@/types/agentic';
```

- [ ] **Step 2: Add agentic props to ChatMessage**

Extend props: `agenticState?: AgenticStreamState`, `onClarificationSubmit?: (response: string) => void`, `onKgNodeClick?: (nodeId: string) => void`.

- [ ] **Step 3: Render agentic components in assistant message**

After existing content rendering, conditionally render: AgenticProgress (if steps exist), ClarificationPrompt (if clarification state), KgNodeChip list (if refs exist), MultiSourceResults (if datasource results exist).

- [ ] **Step 4: Add TierSelector to QueryInputBar.tsx**

Import TierSelector. Add `tier` and `onTierChange` props. Render TierSelector before the submit button.

- [ ] **Step 5: Verify build**

Run: `cd ennam.kg.next && npm run build`
Expected: Build succeeds

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.next
git add src/components/chat/ChatMessage.tsx src/components/chat/QueryInputBar.tsx
git commit -m "feat(chat): wire agentic components into chat UI

ChatMessage renders AgenticProgress, ClarificationPrompt, KgNodeChip,
MultiSourceResults. QueryInputBar includes TierSelector."
```

---

## Phase 8: Integration Verification

### Task 24: Cross-Service Smoke Test

- [ ] **Step 1: Verify Python test suite**

Run: `cd ennam.kg.python && uv run pytest tests/test_agentic/ -v --tb=short`
Expected: All agentic tests PASS (8 test files, ~50 tests)

- [ ] **Step 2: Verify Go build**

Run: `cd ennam.kg.go && go build ./...`
Expected: Build succeeds

- [ ] **Step 3: Verify Frontend build**

Run: `cd ennam.kg.next && npm run build`
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 4: Verify lint**

Run: `cd ennam.kg.python && uv run ruff check src/ennam_kg/agentic/ && uv run ruff format --check src/ennam_kg/agentic/`
Expected: No lint errors

- [ ] **Step 5: Final commit checkpoint**

```bash
cd ennam.kg.python && git log --oneline -5
cd ennam.kg.go && git log --oneline -5
cd ennam.kg.next && git log --oneline -5
```

---

## Critical Prerequisites (Pre-Implementation)

Before starting Task 2, these must be resolved:

1. **Fix context_messages bug** — Python `engine.py:210` TODO: `context_messages` assembled by Go but ignored by Python. Must wire into prompt Layer 5. (Quick fix in `streaming/engine.py`)

2. **AnthropicDirectClient** — Already has `complete_with_tools()` at `direct_client.py:84`, but AgenticEngine needs raw `self._client.messages.create()` access for `stop_reason` and multi-block content. The engine accesses `_client` directly (private attribute) — acceptable since both are internal code.

3. **Read-only DB roles** — Must be provisioned per datasource before `execute_sql` is safe. Infrastructure task, not code.

---

## Dependency Graph

```
Task 1 (migration)        ─────────────────────────────────> Task 14 (store)
Task 2 (types) ──> Task 3 (loop_guard) ──> Task 8 (engine)
Task 2 (types) ──> Task 4 (state_store) ──> Task 8 (engine)
Task 5 (sql_validator) ──> Task 6 (tools) ──> Task 8 (engine)
Task 7 (prompts) ──> Task 8 (engine) ──> Task 9 (API) ──> Task 10 (__init__)
Task 11 (model) ──> Task 14 (store)
Task 12 (SSE) ──> Task 13 (handler)
Task 15 (types) ──> Task 16 (SSE) ──> Task 17 (hook)
Task 18-22 (components) ──> Task 23 (wiring)
All ──> Task 24 (smoke test)
```

**Parallelizable work:**
- Phase 0 + Phase 1 can run in parallel (Go migration + Python types)
- Phase 4 (Go) + Phase 5-6 (Frontend) can run in parallel after Phase 3
- Tasks 18-22 (frontend components) are fully independent of each other
