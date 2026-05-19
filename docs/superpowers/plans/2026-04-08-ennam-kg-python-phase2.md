# ennam.kg.python Phase 2 — AI Compute Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Python service from code indexing worker to full AI compute engine — implicit relationship detection, NL-to-SQL pipeline, and benchmark runner.

**Architecture:** Python remains a Redis queue consumer + FastAPI HTTP server calling Go API for persistence. New packages mirror the existing pattern (module → worker message → engine). AI calls route through Go API's provider abstraction layer (BA-009) instead of direct Anthropic SDK. Four waves matching BA dependency graph: AI client → KG generation → NL query → benchmark.

**Tech Stack:** Python 3.12+, FastAPI, httpx (async), pydantic, Redis (BRPOP), tree-sitter (existing), uv (package manager), ruff (lint), pytest + pytest-asyncio (test)

---

## Scope & Dependency Waves

```
Wave 1 (foundation):  AI Client adapter + Migrate summarizer
                          ↓
Wave 2 (BA-008):      KG Generation workers (implicit detection + AI descriptions)
                          ↓
Wave 3 (BA-011):      NL Query Pipeline (intent parsing + SQL generation + NL summary)
                          ↓
Wave 4 (BA-013):      Benchmark Runner (test execution + accuracy scoring)
```

**Go API Prerequisites** (must be implemented before Python can consume):
- Wave 1: Go API `/api/v1/ai/complete` endpoint (BA-009)
- Wave 2: Go API data source & schema metadata endpoints (BA-007), KG generation job endpoints (BA-008)
- Wave 3: Go API NL query endpoints (BA-011 FR-004 MCP connector, FR-008 query history)
- Wave 4: Go API benchmark CRUD endpoints (BA-013 FR-001/FR-002)

---

## File Structure

### New Files (by wave)

```
src/ennam_kg/
├── ai_client/                     # Wave 1: AI provider abstraction client
│   ├── __init__.py
│   ├── client.py                  # AIClient — calls Go API /api/v1/ai/complete
│   └── models.py                  # AIRequest, AIResponse, AIUsage pydantic models
│
├── kg_generator/                  # Wave 2: KG generation from schema metadata
│   ├── __init__.py
│   ├── implicit_detector.py       # Naming pattern + type analysis → AI scoring
│   ├── description_generator.py   # AI-generated table descriptions
│   ├── prompts.py                 # Prompt templates for detection + descriptions
│   └── engine.py                  # KGGenerationEngine orchestrator
│
├── nl_query/                      # Wave 3: NL → SQL pipeline
│   ├── __init__.py
│   ├── intent_parser.py           # NL → structured query plan via AI
│   ├── sql_generator.py           # Query plan → parameterized SQL
│   ├── response_formatter.py      # Result formatting + NL summary
│   ├── prompts.py                 # Prompt templates for NL query
│   └── engine.py                  # NLQueryEngine orchestrator
│
├── benchmark/                     # Wave 4: Benchmark execution
│   ├── __init__.py
│   ├── runner.py                  # Execute benchmark questions through NL pipeline
│   ├── scorer.py                  # Accuracy scoring (exact/semantic/partial/fail)
│   └── engine.py                  # BenchmarkEngine orchestrator
│
tests/
├── test_ai_client/
│   ├── test_client.py
│   └── test_models.py
├── test_kg_generator/
│   ├── test_implicit_detector.py
│   ├── test_description_generator.py
│   └── test_engine.py
├── test_nl_query/
│   ├── test_intent_parser.py
│   ├── test_sql_generator.py
│   ├── test_response_formatter.py
│   └── test_engine.py
└── test_benchmark/
    ├── test_runner.py
    ├── test_scorer.py
    └── test_engine.py
```

### Modified Files

```
src/ennam_kg/
├── config.py                      # Add AI client, NL query, benchmark settings
├── worker.py                      # Add new message handlers
├── queue/messages.py              # Add new message schemas
├── kg_client/client.py            # Add schema metadata + AI endpoints
├── summarizer/claude.py           # Migrate to use ai_client (deprecate direct anthropic)
├── api/__init__.py                # Register new routers
├── main.py                        # Add lifespan for new components
pyproject.toml                     # Add new dependencies (sqlglot)
```

---

## Wave 1: AI Client + Summarizer Migration

### Task 1: AI Client Models

**Files:**
- Create: `src/ennam_kg/ai_client/__init__.py`
- Create: `src/ennam_kg/ai_client/models.py`
- Test: `tests/test_ai_client/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ai_client/test_models.py
from ennam_kg.ai_client.models import AIRequest, AIResponse, AIUsage


def test_ai_request_minimal():
    req = AIRequest(prompt="Summarize this function", max_tokens=100)
    assert req.prompt == "Summarize this function"
    assert req.max_tokens == 100
    assert req.system_prompt is None
    assert req.temperature == 0.0


def test_ai_request_full():
    req = AIRequest(
        prompt="Analyze relationships",
        max_tokens=2000,
        system_prompt="You are a database analyst.",
        temperature=0.3,
        response_format="json",
    )
    assert req.system_prompt == "You are a database analyst."
    assert req.temperature == 0.3
    assert req.response_format == "json"


def test_ai_response():
    resp = AIResponse(
        content="The function calculates tax.",
        usage=AIUsage(input_tokens=50, output_tokens=20),
        model="claude-sonnet-4-20250514",
        provider="claude_max",
    )
    assert resp.content == "The function calculates tax."
    assert resp.usage.input_tokens == 50
    assert resp.usage.total_tokens == 70
    assert resp.provider == "claude_max"


def test_ai_usage_total():
    usage = AIUsage(input_tokens=100, output_tokens=50)
    assert usage.total_tokens == 150
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_ai_client/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ennam_kg.ai_client'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ennam_kg/ai_client/__init__.py
from ennam_kg.ai_client.client import AIClient
from ennam_kg.ai_client.models import AIRequest, AIResponse, AIUsage

__all__ = ["AIClient", "AIRequest", "AIResponse", "AIUsage"]
```

```python
# src/ennam_kg/ai_client/models.py
from __future__ import annotations

from pydantic import BaseModel


class AIRequest(BaseModel):
    """Request to the AI provider abstraction layer (BA-009)."""

    prompt: str
    max_tokens: int = 1000
    system_prompt: str | None = None
    temperature: float = 0.0
    response_format: str | None = None  # "json" or None for plain text


class AIUsage(BaseModel):
    """Token usage from an AI response."""

    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class AIResponse(BaseModel):
    """Response from the AI provider abstraction layer."""

    content: str
    usage: AIUsage
    model: str
    provider: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_ai_client/test_models.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/ai_client/__init__.py src/ennam_kg/ai_client/models.py tests/test_ai_client/test_models.py
git commit -m "feat: add AI client models for provider abstraction (BA-009)"
```

---

### Task 2: AI Client HTTP Adapter

**Files:**
- Create: `src/ennam_kg/ai_client/client.py`
- Test: `tests/test_ai_client/test_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ai_client/test_client.py
from __future__ import annotations

import pytest
import httpx

from ennam_kg.ai_client.client import AIClient
from ennam_kg.ai_client.models import AIRequest


@pytest.fixture
def ai_client(httpx_mock):
    """AIClient pointing at mock Go API."""
    client = AIClient(
        base_url="http://localhost:8080",
        api_key="test-key",
        http_client=httpx.AsyncClient(base_url="http://localhost:8080"),
    )
    return client


@pytest.mark.asyncio
async def test_complete_success(ai_client, httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:8080/api/v1/ai/complete",
        method="POST",
        json={
            "content": "This function calculates tax.",
            "usage": {"input_tokens": 50, "output_tokens": 20},
            "model": "claude-sonnet-4-20250514",
            "provider": "claude_max",
        },
    )
    req = AIRequest(prompt="Summarize this", max_tokens=100)
    resp = await ai_client.complete(req)
    assert resp.content == "This function calculates tax."
    assert resp.provider == "claude_max"
    assert resp.usage.total_tokens == 70


@pytest.mark.asyncio
async def test_complete_sends_auth_header(ai_client, httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:8080/api/v1/ai/complete",
        method="POST",
        json={
            "content": "ok",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "model": "claude-sonnet-4-20250514",
            "provider": "claude_max",
        },
    )
    await ai_client.complete(AIRequest(prompt="test"))
    request = httpx_mock.get_request()
    assert request.headers["authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_complete_sends_correct_payload(ai_client, httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:8080/api/v1/ai/complete",
        method="POST",
        json={
            "content": "ok",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "model": "claude-sonnet-4-20250514",
            "provider": "claude_max",
        },
    )
    await ai_client.complete(
        AIRequest(
            prompt="Analyze this",
            max_tokens=2000,
            system_prompt="You are an analyst.",
            temperature=0.3,
            response_format="json",
        )
    )
    request = httpx_mock.get_request()
    import json

    body = json.loads(request.content)
    assert body["prompt"] == "Analyze this"
    assert body["max_tokens"] == 2000
    assert body["system_prompt"] == "You are an analyst."
    assert body["temperature"] == 0.3
    assert body["response_format"] == "json"


@pytest.mark.asyncio
async def test_complete_api_error(ai_client, httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:8080/api/v1/ai/complete",
        method="POST",
        status_code=503,
        json={"error": "AI_PROVIDER_UNAVAILABLE", "message": "All providers exhausted"},
    )
    from ennam_kg.ai_client.client import AIClientError

    with pytest.raises(AIClientError) as exc_info:
        await ai_client.complete(AIRequest(prompt="test"))
    assert exc_info.value.status_code == 503
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_ai_client/test_client.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ennam_kg/ai_client/client.py
from __future__ import annotations

import logging
from typing import Any

import httpx

from ennam_kg.ai_client.models import AIRequest, AIResponse

logger = logging.getLogger(__name__)


class AIClientError(Exception):
    """Raised when the Go API AI endpoint returns an error."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"AI API error {status_code}: {detail}")


class AIClient:
    """Async client for Go API's AI provider abstraction layer (BA-009).

    Routes all AI requests through the Go API instead of calling
    providers (Anthropic, OpenAI) directly. The Go API handles provider
    selection, failover, rate limiting, and cost tracking.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = http_client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=120.0,  # AI calls can be slow
        )

    async def complete(self, request: AIRequest) -> AIResponse:
        """Send a completion request through the Go API AI abstraction."""
        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.system_prompt:
            payload["system_prompt"] = request.system_prompt
        if request.response_format:
            payload["response_format"] = request.response_format

        response = await self._http.post(
            "/api/v1/ai/complete",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )

        if response.status_code >= 400:
            raise AIClientError(
                status_code=response.status_code,
                detail=response.text,
            )

        return AIResponse.model_validate(response.json())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_ai_client/test_client.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/ai_client/client.py tests/test_ai_client/test_client.py
git commit -m "feat: add AIClient HTTP adapter for Go API AI abstraction (BA-009)"
```

---

### Task 3: Migrate Summarizer to AI Client

**Files:**
- Modify: `src/ennam_kg/summarizer/claude.py`
- Test: `tests/test_summarizer/test_claude.py` (update existing tests)

- [ ] **Step 1: Write the failing test for the new adapter path**

```python
# tests/test_summarizer/test_claude_v2.py
"""Tests for ClaudeSummarizer using AIClient (Phase 2 path)."""
from __future__ import annotations

import pytest

from ennam_kg.ai_client.models import AIResponse, AIUsage
from ennam_kg.summarizer.cache import SummaryCache
from ennam_kg.summarizer.claude import ClaudeSummarizer


class FakeAIClient:
    """Fake AIClient for testing."""

    def __init__(self, responses: dict[str, str]):
        self._responses = responses
        self.calls: list[dict] = []

    async def complete(self, request):
        self.calls.append({"prompt": request.prompt, "max_tokens": request.max_tokens})
        content = self._responses.get("default", "A test summary.")
        return AIResponse(
            content=content,
            usage=AIUsage(input_tokens=50, output_tokens=20),
            model="claude-sonnet-4-20250514",
            provider="claude_max",
        )


@pytest.mark.asyncio
async def test_summarize_symbols_via_ai_client():
    fake = FakeAIClient(responses={"default": "Calculates order total."})
    summarizer = ClaudeSummarizer(ai_client=fake, cache=SummaryCache())
    symbols = [
        {
            "name": "calculate_total",
            "kind": "function",
            "signature": "def calculate_total(items)",
            "body_snippet": "return sum(i.price for i in items)",
            "body_hash": "abc123",
        }
    ]
    results = await summarizer.summarize_symbols(symbols)
    assert results["abc123"] == "Calculates order total."
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_summarize_uses_cache():
    fake = FakeAIClient(responses={"default": "New summary."})
    cache = SummaryCache()
    cache.set("cached_hash", "Cached summary.")
    summarizer = ClaudeSummarizer(ai_client=fake, cache=cache)
    symbols = [
        {"name": "foo", "kind": "function", "signature": "", "body_snippet": "", "body_hash": "cached_hash"}
    ]
    results = await summarizer.summarize_symbols(symbols)
    assert results["cached_hash"] == "Cached summary."
    assert len(fake.calls) == 0  # No AI call for cached symbol
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_summarizer/test_claude_v2.py -v`
Expected: FAIL — `ClaudeSummarizer` constructor doesn't accept `ai_client`

- [ ] **Step 3: Rewrite ClaudeSummarizer to use AIClient**

Replace the content of `src/ennam_kg/summarizer/claude.py`:

```python
"""AI-powered summarization of code symbols.

Phase 2: Routes through Go API's AI provider abstraction (BA-009).
Legacy direct-Anthropic path removed.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ennam_kg.summarizer.cache import SummaryCache
from ennam_kg.summarizer.prompts import get_summary_prompt

if TYPE_CHECKING:
    from ennam_kg.ai_client.client import AIClient

logger = logging.getLogger(__name__)


class ClaudeSummarizer:
    """Summarizes code symbols via the AI provider abstraction layer."""

    def __init__(self, ai_client: AIClient, cache: SummaryCache | None = None) -> None:
        self._ai = ai_client
        self.cache = cache or SummaryCache()

    async def summarize_symbols(self, symbols: list[dict[str, str]]) -> dict[str, str]:
        """Summarize a batch of symbols.

        Args:
            symbols: list of dicts with keys: name, kind, signature, body_snippet, body_hash

        Returns:
            dict mapping body_hash -> summary text
        """
        results: dict[str, str] = {}

        for symbol in symbols:
            body_hash = symbol["body_hash"]

            cached = self.cache.get(body_hash)
            if cached is not None:
                results[body_hash] = cached
                continue

            try:
                summary = await self._summarize_single(symbol)
                self.cache.set(body_hash, summary)
                results[body_hash] = summary
            except Exception as exc:
                logger.warning("Failed to summarize %s: %s", symbol.get("name"), exc)
                results[body_hash] = ""

        self.cache.save()
        return results

    async def _summarize_single(self, symbol: dict[str, str]) -> str:
        """Summarize a single symbol via the AI provider."""
        from ennam_kg.ai_client.models import AIRequest

        prompt = get_summary_prompt(
            symbol_type=symbol.get("kind", "symbol"),
            name=symbol.get("name", ""),
            signature=symbol.get("signature", ""),
            body_snippet=symbol.get("body_snippet", ""),
        )

        response = await self._ai.complete(
            AIRequest(prompt=prompt, max_tokens=100)
        )
        return response.content.strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_summarizer/test_claude_v2.py -v`
Expected: 2 passed

- [ ] **Step 5: Update existing tests**

Update any existing `tests/test_summarizer/test_claude.py` tests to use the new constructor signature (replace `api_key=` with `ai_client=FakeAIClient(...)` and make tests async).

- [ ] **Step 6: Run all tests**

Run: `cd ennam.kg.python && uv run pytest -v`
Expected: All tests pass

- [ ] **Step 7: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/summarizer/claude.py tests/test_summarizer/
git commit -m "refactor: migrate ClaudeSummarizer to AI provider abstraction (BA-009)"
```

---

### Task 4: Update Config & Worker for AI Client

**Files:**
- Modify: `src/ennam_kg/config.py`
- Modify: `src/ennam_kg/worker.py`

- [ ] **Step 1: Update config.py — no new test needed (pydantic validates)**

Add to `Settings` class in `src/ennam_kg/config.py`:

```python
class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    go_api_url: str = "http://localhost:8080"
    go_api_key: str = ""
    redis_url: str = "redis://localhost:6379/0"
    redis_queue_name: str = "ennam-kg:indexing"
    redis_ai_queue_name: str = "ennam-kg:ai-tasks"  # Phase 2 AI task queue
    anthropic_api_key: str | None = None  # Deprecated: kept for backward compat
    log_level: str = "INFO"
    worker_concurrency: int = 2
    nl_query_timeout: int = 30  # seconds for NL query SQL execution
    benchmark_concurrency: int = 5  # parallel benchmark questions

    model_config = {
        "env_prefix": "",
        "env_file": ".env",
    }
```

- [ ] **Step 2: Update worker.py to initialize AIClient**

In `src/ennam_kg/worker.py`, modify `_run_worker`:

```python
from ennam_kg.ai_client.client import AIClient

async def _run_worker(settings: Settings) -> None:
    """Initialize components and consume messages forever."""
    kg_client = KGClient(settings.go_api_url, settings.go_api_key)

    # Phase 2: AI client through Go API abstraction
    ai_client = AIClient(settings.go_api_url, settings.go_api_key)

    cache = SummaryCache(Path(".summary_cache.json"))
    summarizer: ClaudeSummarizer | None = None
    if settings.go_api_key:  # AI available if Go API is configured
        summarizer = ClaudeSummarizer(ai_client=ai_client, cache=cache)
        logger.info("AI summarization enabled (via Go API abstraction)")
    else:
        logger.info("AI summarization disabled (no Go API key)")

    engine = IndexingEngine(kg_client, settings)
    consumer = RedisQueueConsumer(settings.redis_url, settings.redis_queue_name)
    # ... rest unchanged
```

- [ ] **Step 3: Run all tests**

Run: `cd ennam.kg.python && uv run pytest -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/config.py src/ennam_kg/worker.py
git commit -m "feat: wire AIClient into worker, add Phase 2 config settings"
```

---

## Wave 2: KG Generation (BA-008)

### Task 5: Implicit Relationship Detection — Naming Pattern Analyzer

**Files:**
- Create: `src/ennam_kg/kg_generator/__init__.py`
- Create: `src/ennam_kg/kg_generator/implicit_detector.py`
- Test: `tests/test_kg_generator/test_implicit_detector.py`

- [ ] **Step 1: Write failing tests for naming pattern detection**

```python
# tests/test_kg_generator/test_implicit_detector.py
from __future__ import annotations

import pytest

from ennam_kg.kg_generator.implicit_detector import (
    CandidateRelationship,
    find_naming_candidates,
)


def _make_tables() -> dict[str, dict]:
    """Sample schema metadata: 3 tables."""
    return {
        "users": {
            "columns": {"id": "integer", "name": "text", "email": "text"},
            "primary_key": "id",
            "foreign_keys": [],
        },
        "orders": {
            "columns": {
                "id": "integer",
                "user_id": "integer",
                "product_id": "integer",
                "status": "text",
            },
            "primary_key": "id",
            "foreign_keys": [
                {"column": "user_id", "references_table": "users", "references_column": "id"}
            ],
        },
        "products": {
            "columns": {"id": "integer", "name": "text", "price": "numeric"},
            "primary_key": "id",
            "foreign_keys": [],
        },
    }


def test_find_naming_candidates_detects_missing_fk():
    """orders.product_id has no FK but matches products table."""
    tables = _make_tables()
    candidates = find_naming_candidates(tables)
    assert len(candidates) == 1
    assert candidates[0].source_table == "orders"
    assert candidates[0].source_column == "product_id"
    assert candidates[0].target_table == "products"
    assert candidates[0].target_column == "id"


def test_find_naming_candidates_skips_existing_fk():
    """orders.user_id already has FK — should not appear as candidate."""
    tables = _make_tables()
    candidates = find_naming_candidates(tables)
    source_cols = [(c.source_table, c.source_column) for c in candidates]
    assert ("orders", "user_id") not in source_cols


def test_find_naming_candidates_type_compatibility():
    """Incompatible types should not produce candidates."""
    tables = {
        "orders": {
            "columns": {"id": "integer", "status_code": "text"},
            "primary_key": "id",
            "foreign_keys": [],
        },
        "statuses": {
            "columns": {"id": "integer", "name": "text"},
            "primary_key": "id",
            "foreign_keys": [],
        },
    }
    # status_code is TEXT, statuses.id is INTEGER — type mismatch
    candidates = find_naming_candidates(tables)
    assert len(candidates) == 0


def test_candidate_has_evidence():
    tables = _make_tables()
    candidates = find_naming_candidates(tables)
    assert candidates[0].evidence_count >= 2  # naming + type match
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_kg_generator/test_implicit_detector.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement naming pattern analyzer**

```python
# src/ennam_kg/kg_generator/__init__.py
```

```python
# src/ennam_kg/kg_generator/implicit_detector.py
"""Detect implicit relationships via naming conventions and type analysis (BA-008 FR-002)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# Type compatibility groups — types within the same group are compatible
_TYPE_GROUPS: list[set[str]] = [
    {"integer", "int", "int4", "int8", "bigint", "smallint", "serial", "bigserial"},
    {"uuid"},
    {"text", "varchar", "character varying", "char"},
]


def _types_compatible(type_a: str, type_b: str) -> bool:
    a = type_a.lower().split("(")[0].strip()
    b = type_b.lower().split("(")[0].strip()
    if a == b:
        return True
    for group in _TYPE_GROUPS:
        if a in group and b in group:
            return True
    return False


@dataclass
class CandidateRelationship:
    """A candidate implicit relationship between two tables."""

    source_table: str
    source_column: str
    target_table: str
    target_column: str
    evidence: list[str] = field(default_factory=list)

    @property
    def evidence_count(self) -> int:
        return len(self.evidence)


# Naming patterns: <table>_id, <singular>_id, <table>Id
_PATTERNS = [
    re.compile(r"^(.+)_id$"),       # snake_case: user_id -> user
    re.compile(r"^(.+)Id$"),        # camelCase: userId -> user
    re.compile(r"^fk_(.+)$"),       # fk_ prefix: fk_user -> user
]


def _singularize(name: str) -> str:
    """Naive singularization: strip trailing 's'."""
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith("ses") or name.endswith("xes"):
        return name[:-2]
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def find_naming_candidates(
    tables: dict[str, dict],
) -> list[CandidateRelationship]:
    """Find columns that look like FKs by naming convention but lack FK constraints.

    Args:
        tables: dict of table_name -> {columns: {col: type}, primary_key: str, foreign_keys: [{column, references_table, references_column}]}

    Returns:
        List of candidate relationships with at least 2 forms of evidence.
    """
    # Build lookup: table_name -> set of existing FK columns
    existing_fks: dict[str, set[str]] = {}
    for tname, tdata in tables.items():
        existing_fks[tname] = {fk["column"] for fk in tdata.get("foreign_keys", [])}

    # Build lookup: table_name (and singular form) -> table_name
    table_lookup: dict[str, str] = {}
    for tname in tables:
        table_lookup[tname] = tname
        table_lookup[_singularize(tname)] = tname

    candidates: list[CandidateRelationship] = []

    for src_table, src_data in tables.items():
        for col_name, col_type in src_data.get("columns", {}).items():
            # Skip if already has FK
            if col_name in existing_fks.get(src_table, set()):
                continue

            # Try naming patterns
            for pattern in _PATTERNS:
                match = pattern.match(col_name)
                if not match:
                    continue
                ref_hint = match.group(1).lower()
                target_table = table_lookup.get(ref_hint)
                if not target_table:
                    continue

                # Get target PK type
                target_pk = tables[target_table].get("primary_key", "id")
                target_pk_type = tables[target_table]["columns"].get(target_pk, "")

                evidence: list[str] = ["naming_convention"]

                # Check type compatibility
                if _types_compatible(col_type, target_pk_type):
                    evidence.append("type_compatible")
                else:
                    continue  # BA-008 BR-002.2: must have type compatibility

                # Only keep if >= 2 evidence (BA-008 BR-002.5)
                if len(evidence) >= 2:
                    candidates.append(
                        CandidateRelationship(
                            source_table=src_table,
                            source_column=col_name,
                            target_table=target_table,
                            target_column=target_pk,
                            evidence=evidence,
                        )
                    )
                break  # First matching pattern wins

    return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_kg_generator/test_implicit_detector.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/kg_generator/ tests/test_kg_generator/
git commit -m "feat: add implicit relationship naming pattern analyzer (BA-008 FR-002)"
```

---

### Task 6: AI Confidence Scoring for Candidates

**Files:**
- Modify: `src/ennam_kg/kg_generator/implicit_detector.py`
- Create: `src/ennam_kg/kg_generator/prompts.py`
- Test: `tests/test_kg_generator/test_implicit_detector.py` (add async tests)

- [ ] **Step 1: Write failing test for AI scoring**

```python
# Append to tests/test_kg_generator/test_implicit_detector.py

from ennam_kg.ai_client.models import AIResponse, AIUsage
from ennam_kg.kg_generator.implicit_detector import score_candidates


class FakeAIClient:
    async def complete(self, request):
        return AIResponse(
            content='{"confidence": 0.85, "reasoning": "Strong naming match and type compatibility."}',
            usage=AIUsage(input_tokens=200, output_tokens=50),
            model="claude-sonnet-4-20250514",
            provider="claude_max",
        )


@pytest.mark.asyncio
async def test_score_candidates():
    candidates = [
        CandidateRelationship(
            source_table="orders",
            source_column="product_id",
            target_table="products",
            target_column="id",
            evidence=["naming_convention", "type_compatible"],
        )
    ]
    scored = await score_candidates(candidates, FakeAIClient())
    assert len(scored) == 1
    assert scored[0].confidence == 0.85
    assert "naming" in scored[0].reasoning.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_kg_generator/test_implicit_detector.py::test_score_candidates -v`
Expected: FAIL — `score_candidates` not found

- [ ] **Step 3: Implement AI scoring**

Add to `src/ennam_kg/kg_generator/implicit_detector.py`:

```python
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ennam_kg.ai_client.client import AIClient

logger = logging.getLogger(__name__)


@dataclass
class ScoredRelationship:
    """A candidate with AI confidence score."""

    source_table: str
    source_column: str
    target_table: str
    target_column: str
    confidence: float
    reasoning: str
    evidence: list[str] = field(default_factory=list)


async def score_candidates(
    candidates: list[CandidateRelationship],
    ai_client: AIClient,
) -> list[ScoredRelationship]:
    """Score candidate relationships using AI provider (BA-008 FR-002 BR-002.4)."""
    from ennam_kg.ai_client.models import AIRequest
    from ennam_kg.kg_generator.prompts import get_implicit_scoring_prompt

    scored: list[ScoredRelationship] = []

    for candidate in candidates:
        prompt = get_implicit_scoring_prompt(candidate)
        try:
            response = await ai_client.complete(
                AIRequest(
                    prompt=prompt,
                    max_tokens=200,
                    system_prompt="You are a database relationship analyst. Respond with JSON only.",
                    temperature=0.0,
                    response_format="json",
                )
            )
            data = json.loads(response.content)
            scored.append(
                ScoredRelationship(
                    source_table=candidate.source_table,
                    source_column=candidate.source_column,
                    target_table=candidate.target_table,
                    target_column=candidate.target_column,
                    confidence=float(data.get("confidence", 0.0)),
                    reasoning=data.get("reasoning", ""),
                    evidence=candidate.evidence,
                )
            )
        except Exception as exc:
            logger.warning(
                "Failed to score %s.%s -> %s: %s",
                candidate.source_table,
                candidate.source_column,
                candidate.target_table,
                exc,
            )

    return scored
```

Create `src/ennam_kg/kg_generator/prompts.py`:

```python
"""Prompt templates for KG generation AI calls (BA-008)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ennam_kg.kg_generator.implicit_detector import CandidateRelationship


def get_implicit_scoring_prompt(candidate: CandidateRelationship) -> str:
    """Build prompt for AI confidence scoring of an implicit relationship."""
    return f"""Analyze this candidate implicit database relationship:

Source: table "{candidate.source_table}", column "{candidate.source_column}"
Target: table "{candidate.target_table}", column "{candidate.target_column}"
Evidence found: {", ".join(candidate.evidence)}

Score the likelihood that this is a real foreign key relationship.
Consider:
1. Naming convention strength (exact table_id match vs partial)
2. Data type compatibility
3. Semantic meaning of column and table names

Respond with JSON:
{{"confidence": <0.0-1.0>, "reasoning": "<brief explanation>"}}"""


def get_table_description_prompt(
    table_name: str,
    columns: list[dict[str, str]],
    foreign_keys: list[dict[str, str]],
) -> str:
    """Build prompt for AI-generated table description (BA-008 FR-003 BR-003.5)."""
    col_list = "\n".join(
        f"  - {c['name']} ({c['type']})" for c in columns
    )
    fk_list = "\n".join(
        f"  - {fk['column']} -> {fk['references_table']}.{fk['references_column']}"
        for fk in foreign_keys
    ) or "  (none)"

    return f"""Describe the purpose of this database table in one paragraph (2-3 sentences).

Table: {table_name}
Columns:
{col_list}
Foreign Keys:
{fk_list}

Base your description on the table name, column names, data types, and relationships.
Be specific about what data this table stores and its role in the system."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_kg_generator/test_implicit_detector.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/kg_generator/implicit_detector.py src/ennam_kg/kg_generator/prompts.py tests/test_kg_generator/
git commit -m "feat: add AI confidence scoring for implicit relationships (BA-008 FR-002)"
```

---

### Task 7: Description Generator

**Files:**
- Create: `src/ennam_kg/kg_generator/description_generator.py`
- Test: `tests/test_kg_generator/test_description_generator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_kg_generator/test_description_generator.py
from __future__ import annotations

import pytest

from ennam_kg.ai_client.models import AIResponse, AIUsage
from ennam_kg.kg_generator.description_generator import generate_table_descriptions


class FakeAIClient:
    def __init__(self):
        self.call_count = 0

    async def complete(self, request):
        self.call_count += 1
        return AIResponse(
            content="Stores customer orders with timestamps and status tracking.",
            usage=AIUsage(input_tokens=100, output_tokens=30),
            model="claude-sonnet-4-20250514",
            provider="claude_max",
        )


@pytest.mark.asyncio
async def test_generate_descriptions_for_tables_without_comments():
    tables = {
        "orders": {
            "columns": {"id": "integer", "user_id": "integer", "status": "text", "created_at": "timestamp"},
            "primary_key": "id",
            "foreign_keys": [{"column": "user_id", "references_table": "users", "references_column": "id"}],
            "comment": None,
        },
        "users": {
            "columns": {"id": "integer", "name": "text"},
            "primary_key": "id",
            "foreign_keys": [],
            "comment": "Registered user accounts",  # Has existing comment
        },
    }
    fake = FakeAIClient()
    descriptions = await generate_table_descriptions(tables, fake)
    # Only orders should get AI description (users has comment)
    assert "orders" in descriptions
    assert descriptions["orders"] == "Stores customer orders with timestamps and status tracking."
    assert "users" in descriptions
    assert descriptions["users"] == "Registered user accounts"  # Uses existing comment
    assert fake.call_count == 1  # Only 1 AI call (for orders)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_kg_generator/test_description_generator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement description generator**

```python
# src/ennam_kg/kg_generator/description_generator.py
"""AI-generated table descriptions (BA-008 FR-003 BR-003.5)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ennam_kg.ai_client.models import AIRequest
from ennam_kg.kg_generator.prompts import get_table_description_prompt

if TYPE_CHECKING:
    from ennam_kg.ai_client.client import AIClient

logger = logging.getLogger(__name__)


async def generate_table_descriptions(
    tables: dict[str, dict],
    ai_client: AIClient,
) -> dict[str, str]:
    """Generate descriptions for tables that lack database comments.

    Tables with existing comments use those as-is (no AI call).
    Tables without comments get AI-generated descriptions.

    Returns:
        dict mapping table_name -> description
    """
    descriptions: dict[str, str] = {}

    for table_name, table_data in tables.items():
        existing_comment = table_data.get("comment")
        if existing_comment:
            descriptions[table_name] = existing_comment
            continue

        columns = [
            {"name": col_name, "type": col_type}
            for col_name, col_type in table_data.get("columns", {}).items()
        ]
        foreign_keys = table_data.get("foreign_keys", [])

        prompt = get_table_description_prompt(table_name, columns, foreign_keys)

        try:
            response = await ai_client.complete(
                AIRequest(prompt=prompt, max_tokens=200)
            )
            descriptions[table_name] = response.content.strip()
        except Exception as exc:
            logger.warning("Failed to generate description for %s: %s", table_name, exc)
            descriptions[table_name] = ""

    return descriptions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_kg_generator/test_description_generator.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/kg_generator/description_generator.py tests/test_kg_generator/test_description_generator.py
git commit -m "feat: add AI table description generator (BA-008 FR-003)"
```

---

### Task 8: KG Generation Engine + Queue Messages

**Files:**
- Create: `src/ennam_kg/kg_generator/engine.py`
- Modify: `src/ennam_kg/queue/messages.py`
- Test: `tests/test_kg_generator/test_engine.py`

- [ ] **Step 1: Add new message schemas**

Add to `src/ennam_kg/queue/messages.py`:

```python
class GenerateKGMessage(BaseModel):
    """Message to trigger KG generation from schema metadata."""

    type: str  # "generate_kg"
    project_id: str
    data_source_id: str
    include_implicit: bool = True
    timestamp: str = ""


class DetectImplicitMessage(BaseModel):
    """Message to trigger implicit relationship detection only."""

    type: str  # "detect_implicit"
    project_id: str
    data_source_id: str
    timestamp: str = ""
```

- [ ] **Step 2: Write failing test for KG generation engine**

```python
# tests/test_kg_generator/test_engine.py
from __future__ import annotations

import pytest

from ennam_kg.ai_client.models import AIResponse, AIUsage
from ennam_kg.kg_generator.engine import KGGenerationEngine, KGGenerationResult


class FakeKGClient:
    def __init__(self):
        self.created_nodes: list[dict] = []
        self.created_edges: list[dict] = []
        self._node_counter = 0

    async def create_node(self, node_data):
        self._node_counter += 1
        node_id = f"node-{self._node_counter}"
        self.created_nodes.append({**node_data, "id": node_id})
        return {"id": node_id}

    async def create_edge(self, edge_data):
        self.created_edges.append(edge_data)
        return {"id": f"edge-{len(self.created_edges)}"}

    async def get_schema_metadata(self, data_source_id):
        return {
            "tables": {
                "users": {
                    "columns": {"id": "integer", "name": "text"},
                    "primary_key": "id",
                    "foreign_keys": [],
                    "comment": "User accounts",
                },
                "orders": {
                    "columns": {"id": "integer", "user_id": "integer", "product_id": "integer"},
                    "primary_key": "id",
                    "foreign_keys": [
                        {"column": "user_id", "references_table": "users", "references_column": "id"}
                    ],
                    "comment": None,
                },
                "products": {
                    "columns": {"id": "integer", "name": "text", "price": "numeric"},
                    "primary_key": "id",
                    "foreign_keys": [],
                    "comment": None,
                },
            }
        }


class FakeAIClient:
    async def complete(self, request):
        if "confidence" in request.prompt.lower() or "relationship" in request.prompt.lower():
            return AIResponse(
                content='{"confidence": 0.8, "reasoning": "Strong naming match."}',
                usage=AIUsage(input_tokens=100, output_tokens=30),
                model="test", provider="test",
            )
        return AIResponse(
            content="A table for storing data.",
            usage=AIUsage(input_tokens=50, output_tokens=20),
            model="test", provider="test",
        )


@pytest.mark.asyncio
async def test_full_generation():
    kg = FakeKGClient()
    ai = FakeAIClient()
    engine = KGGenerationEngine(kg_client=kg, ai_client=ai)
    result = await engine.generate(project_id="proj-1", data_source_id="ds-1")

    assert isinstance(result, KGGenerationResult)
    assert result.nodes_created == 3  # 3 tables
    assert result.implicit_candidates >= 1  # orders.product_id -> products
    assert len(result.errors) == 0
```

- [ ] **Step 3: Implement KG generation engine**

```python
# src/ennam_kg/kg_generator/engine.py
"""Orchestrates KG generation from schema metadata (BA-008)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ennam_kg.kg_generator.description_generator import generate_table_descriptions
from ennam_kg.kg_generator.implicit_detector import find_naming_candidates, score_candidates

if TYPE_CHECKING:
    from ennam_kg.ai_client.client import AIClient
    from ennam_kg.kg_client.client import KGClient

logger = logging.getLogger(__name__)


@dataclass
class KGGenerationResult:
    """Summary statistics for a KG generation run."""

    nodes_created: int = 0
    nodes_updated: int = 0
    edges_created: int = 0
    implicit_candidates: int = 0
    implicit_scored: int = 0
    errors: list[str] = field(default_factory=list)


class KGGenerationEngine:
    """Orchestrates the full KG generation pipeline (BA-008)."""

    def __init__(self, kg_client: KGClient, ai_client: AIClient):
        self._kg = kg_client
        self._ai = ai_client

    async def generate(
        self,
        project_id: str,
        data_source_id: str,
        include_implicit: bool = True,
    ) -> KGGenerationResult:
        """Run full KG generation pipeline.

        Pipeline order (BA-008 §4):
        1. Fetch schema metadata from Go API
        2. Generate/update nodes per table (FR-003)
        3. AI descriptions for tables without comments (FR-003)
        4. Implicit relationship detection + scoring (FR-002)
        5. Create edges (FR-004)
        """
        result = KGGenerationResult()

        # 1. Fetch schema metadata
        metadata = await self._kg.get_schema_metadata(data_source_id)
        tables = metadata.get("tables", {})
        logger.info("Fetched schema: %d tables for ds=%s", len(tables), data_source_id)

        # 2. Generate descriptions
        descriptions = await generate_table_descriptions(tables, self._ai)

        # 3. Create/update nodes
        node_id_map: dict[str, str] = {}
        for table_name, table_data in tables.items():
            try:
                node_data = {
                    "project_id": project_id,
                    "node_type": "architecture",
                    "title": table_name,
                    "status": "active",
                    "properties": {
                        "node_subtype": "schema_table",
                        "source_data_source_id": data_source_id,
                        "source_table_name": table_name,
                        "column_count": len(table_data.get("columns", {})),
                        "ai_description": descriptions.get(table_name, ""),
                        "schema_group": "public",
                    },
                }
                resp = await self._kg.create_node(node_data)
                node_id_map[table_name] = resp.get("id", "")
                result.nodes_created += 1
            except Exception as exc:
                result.errors.append(f"Failed to create node for {table_name}: {exc}")

        # 4. Implicit detection
        if include_implicit:
            candidates = find_naming_candidates(tables)
            result.implicit_candidates = len(candidates)
            if candidates:
                scored = await score_candidates(candidates, self._ai)
                result.implicit_scored = len(scored)
                for rel in scored:
                    src_node = node_id_map.get(rel.source_table)
                    tgt_node = node_id_map.get(rel.target_table)
                    if src_node and tgt_node:
                        try:
                            await self._kg.create_edge({
                                "project_id": project_id,
                                "source_id": src_node,
                                "target_id": tgt_node,
                                "edge_type": "schema_implicit",
                                "properties": {
                                    "confidence_score": rel.confidence,
                                    "detection_method": "ai_detected",
                                    "source_column": rel.source_column,
                                    "target_column": rel.target_column,
                                    "reasoning": rel.reasoning,
                                },
                            })
                            result.edges_created += 1
                        except Exception as exc:
                            result.errors.append(
                                f"Failed to create implicit edge {rel.source_table}->{rel.target_table}: {exc}"
                            )

        logger.info(
            "KG generation complete: %d nodes, %d edges, %d implicit candidates",
            result.nodes_created,
            result.edges_created,
            result.implicit_candidates,
        )
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_kg_generator/test_engine.py -v`
Expected: 1 passed

- [ ] **Step 5: Run all tests**

Run: `cd ennam.kg.python && uv run pytest -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/kg_generator/engine.py src/ennam_kg/queue/messages.py tests/test_kg_generator/test_engine.py
git commit -m "feat: add KG generation engine with implicit detection pipeline (BA-008)"
```

---

### Task 9: Add `get_schema_metadata` to KGClient

**Files:**
- Modify: `src/ennam_kg/kg_client/client.py`
- Test: `tests/test_kg_client/test_client_phase2.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_kg_client/test_client_phase2.py
from __future__ import annotations

import pytest
import httpx

from ennam_kg.kg_client.client import KGClient


@pytest.fixture
def kg_client(httpx_mock):
    return KGClient(
        base_url="http://localhost:8080",
        api_key="test-key",
        http_client=httpx.AsyncClient(base_url="http://localhost:8080"),
    )


@pytest.mark.asyncio
async def test_get_schema_metadata(kg_client, httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:8080/api/v1/data-sources/ds-1/schema",
        method="GET",
        json={
            "tables": {
                "users": {
                    "columns": {"id": "integer", "name": "text"},
                    "primary_key": "id",
                    "foreign_keys": [],
                    "comment": None,
                }
            }
        },
    )
    metadata = await kg_client.get_schema_metadata("ds-1")
    assert "users" in metadata["tables"]
    assert metadata["tables"]["users"]["columns"]["id"] == "integer"


@pytest.mark.asyncio
async def test_submit_nl_query(kg_client, httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:8080/api/v1/ai-queries",
        method="POST",
        json={
            "id": "q-1",
            "status": "completed",
            "sql": "SELECT * FROM orders",
            "results": {"columns": ["id"], "rows": [[1]]},
        },
    )
    result = await kg_client.submit_nl_query(
        project_id="proj-1",
        data_source_id="ds-1",
        query="show all orders",
    )
    assert result["sql"] == "SELECT * FROM orders"


@pytest.mark.asyncio
async def test_get_benchmark_questions(kg_client, httpx_mock):
    httpx_mock.add_response(
        url="http://localhost:8080/api/v1/benchmarks/ds-1/questions",
        method="GET",
        json={
            "questions": [
                {"id": "bq-1", "text": "How many orders?", "difficulty": "simple", "expected_sql": "SELECT COUNT(*) FROM orders"}
            ]
        },
    )
    result = await kg_client.get_benchmark_questions("ds-1")
    assert len(result["questions"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_kg_client/test_client_phase2.py -v`
Expected: FAIL — `AttributeError: 'KGClient' object has no attribute 'get_schema_metadata'`

- [ ] **Step 3: Add Phase 2 methods to KGClient**

Append to `src/ennam_kg/kg_client/client.py`:

```python
    # ---- Phase 2: Schema metadata + NL query + Benchmark ----

    async def get_schema_metadata(self, data_source_id: str) -> dict[str, Any]:
        """Get extracted schema metadata for a data source (BA-007)."""
        return await self._request("GET", f"/api/v1/data-sources/{data_source_id}/schema")

    async def submit_nl_query(
        self,
        project_id: str,
        data_source_id: str,
        query: str,
    ) -> dict[str, Any]:
        """Submit a natural language query (BA-011)."""
        return await self._request(
            "POST",
            "/api/v1/ai-queries",
            json={
                "project_id": project_id,
                "data_source_id": data_source_id,
                "natural_language_query": query,
            },
        )

    async def get_benchmark_questions(self, data_source_id: str) -> dict[str, Any]:
        """Get benchmark questions for a data source (BA-013)."""
        return await self._request("GET", f"/api/v1/benchmarks/{data_source_id}/questions")

    async def submit_benchmark_result(
        self,
        run_id: str,
        question_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit a single benchmark result (BA-013)."""
        return await self._request(
            "POST",
            f"/api/v1/benchmarks/runs/{run_id}/results",
            json={"question_id": question_id, **result},
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_kg_client/test_client_phase2.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/kg_client/client.py tests/test_kg_client/test_client_phase2.py
git commit -m "feat: add Phase 2 endpoints to KGClient (schema, NL query, benchmark)"
```

---

## Wave 3: NL Query Pipeline (BA-011)

### Task 10: Intent Parser

**Files:**
- Create: `src/ennam_kg/nl_query/__init__.py`
- Create: `src/ennam_kg/nl_query/intent_parser.py`
- Create: `src/ennam_kg/nl_query/prompts.py`
- Test: `tests/test_nl_query/test_intent_parser.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_nl_query/test_intent_parser.py
from __future__ import annotations

import json
import pytest

from ennam_kg.ai_client.models import AIResponse, AIUsage
from ennam_kg.nl_query.intent_parser import QueryPlan, parse_intent


SAMPLE_SCHEMA = {
    "tables": {
        "orders": {
            "columns": {"id": "integer", "customer_id": "integer", "total": "numeric", "created_at": "timestamp"},
            "primary_key": "id",
            "foreign_keys": [{"column": "customer_id", "references_table": "customers", "references_column": "id"}],
        },
        "customers": {
            "columns": {"id": "integer", "name": "text", "email": "text"},
            "primary_key": "id",
            "foreign_keys": [],
        },
    }
}


class FakeAIClient:
    def __init__(self, plan_json: dict):
        self._plan = plan_json

    async def complete(self, request):
        return AIResponse(
            content=json.dumps(self._plan),
            usage=AIUsage(input_tokens=500, output_tokens=200),
            model="test",
            provider="test",
        )


@pytest.mark.asyncio
async def test_parse_simple_query():
    plan_json = {
        "tables": ["orders"],
        "joins": [],
        "filters": [{"column": "orders.created_at", "operator": ">=", "value": "2026-03-01"}],
        "aggregations": [],
        "group_by": [],
        "order_by": [],
        "limit": None,
    }
    ai = FakeAIClient(plan_json)
    plan = await parse_intent("show me all orders from last month", SAMPLE_SCHEMA, ai)
    assert isinstance(plan, QueryPlan)
    assert plan.tables == ["orders"]
    assert len(plan.filters) == 1


@pytest.mark.asyncio
async def test_parse_validates_tables_exist():
    plan_json = {
        "tables": ["inventory"],  # Does not exist in schema
        "joins": [],
        "filters": [],
        "aggregations": [],
        "group_by": [],
        "order_by": [],
        "limit": None,
    }
    ai = FakeAIClient(plan_json)
    from ennam_kg.nl_query.intent_parser import IntentParseError

    with pytest.raises(IntentParseError, match="inventory"):
        await parse_intent("show inventory", SAMPLE_SCHEMA, ai)


@pytest.mark.asyncio
async def test_parse_join_query():
    plan_json = {
        "tables": ["orders", "customers"],
        "joins": [{"from_col": "orders.customer_id", "to_col": "customers.id", "type": "inner"}],
        "filters": [],
        "aggregations": [{"function": "COUNT", "column": "orders.id", "alias": "order_count"}],
        "group_by": ["customers.id", "customers.name"],
        "order_by": [{"column": "order_count", "direction": "DESC"}],
        "limit": 10,
    }
    ai = FakeAIClient(plan_json)
    plan = await parse_intent("which customers placed the most orders?", SAMPLE_SCHEMA, ai)
    assert len(plan.joins) == 1
    assert plan.limit == 10
    assert len(plan.aggregations) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_nl_query/test_intent_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement intent parser**

```python
# src/ennam_kg/nl_query/__init__.py
```

```python
# src/ennam_kg/nl_query/intent_parser.py
"""Parse natural language into structured query plans (BA-011 FR-002)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ennam_kg.ai_client.models import AIRequest

if TYPE_CHECKING:
    from ennam_kg.ai_client.client import AIClient

logger = logging.getLogger(__name__)


class IntentParseError(Exception):
    """Raised when intent parsing fails or produces invalid plan."""


@dataclass
class JoinSpec:
    from_col: str
    to_col: str
    type: str = "inner"


@dataclass
class FilterSpec:
    column: str
    operator: str
    value: str


@dataclass
class AggregationSpec:
    function: str
    column: str
    alias: str


@dataclass
class OrderBySpec:
    column: str
    direction: str = "ASC"


@dataclass
class QueryPlan:
    """Structured query plan from AI intent parsing."""

    tables: list[str] = field(default_factory=list)
    joins: list[JoinSpec] = field(default_factory=list)
    filters: list[FilterSpec] = field(default_factory=list)
    aggregations: list[AggregationSpec] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    order_by: list[OrderBySpec] = field(default_factory=list)
    limit: int | None = None


async def parse_intent(
    query: str,
    schema: dict,
    ai_client: AIClient,
) -> QueryPlan:
    """Parse a NL query into a validated QueryPlan.

    Raises IntentParseError if AI response is unparseable or references
    tables/columns not in the schema.
    """
    from ennam_kg.nl_query.prompts import get_intent_parsing_prompt

    prompt = get_intent_parsing_prompt(query, schema)

    response = await ai_client.complete(
        AIRequest(
            prompt=prompt,
            max_tokens=1000,
            system_prompt="You are a SQL query planner. Respond with JSON only.",
            temperature=0.0,
            response_format="json",
        )
    )

    try:
        data = json.loads(response.content)
    except json.JSONDecodeError as exc:
        raise IntentParseError(f"AI returned invalid JSON: {exc}") from exc

    plan = _build_plan(data)
    _validate_plan(plan, schema)
    return plan


def _build_plan(data: dict) -> QueryPlan:
    return QueryPlan(
        tables=data.get("tables", []),
        joins=[JoinSpec(**j) for j in data.get("joins", [])],
        filters=[FilterSpec(**f) for f in data.get("filters", [])],
        aggregations=[AggregationSpec(**a) for a in data.get("aggregations", [])],
        group_by=data.get("group_by", []),
        order_by=[OrderBySpec(**o) for o in data.get("order_by", [])],
        limit=data.get("limit"),
    )


def _validate_plan(plan: QueryPlan, schema: dict) -> None:
    """Validate all referenced tables exist in schema (BA-011 FR-002 BR-002.3)."""
    known_tables = set(schema.get("tables", {}).keys())
    for table in plan.tables:
        if table not in known_tables:
            raise IntentParseError(
                f"Query plan references unknown table '{table}'. "
                f"Available: {sorted(known_tables)}"
            )
```

```python
# src/ennam_kg/nl_query/prompts.py
"""Prompt templates for NL query pipeline (BA-011)."""
from __future__ import annotations


def get_intent_parsing_prompt(query: str, schema: dict) -> str:
    """Build prompt for intent parsing with full schema context."""
    tables_desc = []
    for tname, tdata in schema.get("tables", {}).items():
        cols = ", ".join(
            f"{c} ({t})" for c, t in tdata.get("columns", {}).items()
        )
        fks = ", ".join(
            f"{fk['column']} -> {fk['references_table']}.{fk['references_column']}"
            for fk in tdata.get("foreign_keys", [])
        )
        fk_str = f"\n    Foreign Keys: {fks}" if fks else ""
        tables_desc.append(f"  {tname}: [{cols}]{fk_str}")

    schema_text = "\n".join(tables_desc)

    return f"""Given this database schema:
{schema_text}

Parse this natural language query into a structured query plan:
"{query}"

Respond with JSON:
{{
  "tables": ["table1", "table2"],
  "joins": [{{"from_col": "table.col", "to_col": "table.col", "type": "inner"}}],
  "filters": [{{"column": "table.col", "operator": ">=", "value": "..."}}],
  "aggregations": [{{"function": "COUNT", "column": "table.col", "alias": "name"}}],
  "group_by": ["table.col"],
  "order_by": [{{"column": "col_or_alias", "direction": "ASC|DESC"}}],
  "limit": null
}}

Rules:
- Only reference tables and columns that exist in the schema above.
- Use foreign key relationships for JOINs.
- Resolve relative date expressions (e.g., "last month") to ISO date values.
- If no LIMIT is implied, set limit to null."""


def get_nl_summary_prompt(query: str, sql: str, results_preview: str) -> str:
    """Build prompt for generating NL summary of query results (BA-011 FR-005)."""
    return f"""Original question: "{query}"
Generated SQL: {sql}
Results (first 100 rows):
{results_preview}

Write a 2-4 sentence summary of these results that directly answers the original question.
Be specific with numbers and key findings."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_nl_query/test_intent_parser.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/nl_query/ tests/test_nl_query/
git commit -m "feat: add NL intent parser with schema validation (BA-011 FR-002)"
```

---

### Task 11: SQL Generator

**Files:**
- Create: `src/ennam_kg/nl_query/sql_generator.py`
- Test: `tests/test_nl_query/test_sql_generator.py`
- Modify: `pyproject.toml` (add `sqlglot` dependency)

- [ ] **Step 1: Add sqlglot dependency**

Edit `pyproject.toml` to add `"sqlglot>=26"` to dependencies list.

Run: `cd ennam.kg.python && uv sync`

- [ ] **Step 2: Write failing test**

```python
# tests/test_nl_query/test_sql_generator.py
from __future__ import annotations

import pytest

from ennam_kg.nl_query.intent_parser import (
    AggregationSpec,
    FilterSpec,
    JoinSpec,
    OrderBySpec,
    QueryPlan,
)
from ennam_kg.nl_query.sql_generator import generate_sql, SQLGenerationError


def test_simple_select():
    plan = QueryPlan(
        tables=["orders"],
        filters=[FilterSpec(column="orders.created_at", operator=">=", value="2026-03-01")],
    )
    sql, params = generate_sql(plan, dialect="postgres")
    assert "FROM orders" in sql
    assert "WHERE" in sql
    assert "orders.created_at >= $1" in sql
    assert params == ["2026-03-01"]


def test_join_query():
    plan = QueryPlan(
        tables=["orders", "customers"],
        joins=[JoinSpec(from_col="orders.customer_id", to_col="customers.id")],
    )
    sql, params = generate_sql(plan, dialect="postgres")
    assert "JOIN customers ON orders.customer_id = customers.id" in sql
    assert params == []


def test_aggregation_with_group_by():
    plan = QueryPlan(
        tables=["orders", "customers"],
        joins=[JoinSpec(from_col="orders.customer_id", to_col="customers.id")],
        aggregations=[AggregationSpec(function="COUNT", column="orders.id", alias="order_count")],
        group_by=["customers.id", "customers.name"],
        order_by=[OrderBySpec(column="order_count", direction="DESC")],
        limit=10,
    )
    sql, params = generate_sql(plan, dialect="postgres")
    assert "COUNT(orders.id) AS order_count" in sql
    assert "GROUP BY customers.id, customers.name" in sql
    assert "ORDER BY order_count DESC" in sql
    assert "LIMIT 10" in sql


def test_default_limit():
    plan = QueryPlan(tables=["orders"])
    sql, _ = generate_sql(plan, dialect="postgres")
    assert "LIMIT 1000" in sql


def test_rejects_empty_tables():
    plan = QueryPlan(tables=[])
    with pytest.raises(SQLGenerationError, match="No tables"):
        generate_sql(plan, dialect="postgres")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_nl_query/test_sql_generator.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement SQL generator**

```python
# src/ennam_kg/nl_query/sql_generator.py
"""Transform QueryPlan into parameterized SQL (BA-011 FR-003)."""
from __future__ import annotations

from ennam_kg.nl_query.intent_parser import QueryPlan


class SQLGenerationError(Exception):
    """Raised when SQL generation fails."""


def generate_sql(
    plan: QueryPlan,
    dialect: str = "postgres",
) -> tuple[str, list[str]]:
    """Generate parameterized SQL from a QueryPlan.

    Returns:
        (sql_string, parameters) — parameters use $N placeholders for postgres.

    BA-011 FR-003 rules:
    - Only SELECT statements (BR-003.5)
    - Parameterized values to prevent injection (BR-003.6)
    - Default LIMIT 1000 if not specified (BR-003.3)
    """
    if not plan.tables:
        raise SQLGenerationError("No tables specified in query plan")

    params: list[str] = []
    param_idx = 0

    # SELECT clause
    if plan.aggregations:
        select_parts: list[str] = []
        for agg in plan.aggregations:
            select_parts.append(f"{agg.function}({agg.column}) AS {agg.alias}")
        # Include group_by columns in select
        for col in plan.group_by:
            if col not in select_parts:
                select_parts.insert(0, col)
        select_clause = ", ".join(select_parts)
    else:
        # Select all columns from all tables
        select_clause = ", ".join(f"{t}.*" for t in plan.tables)

    # FROM clause
    from_table = plan.tables[0]

    # JOIN clause
    join_clauses: list[str] = []
    for join in plan.joins:
        join_clauses.append(
            f"{join.type.upper()} JOIN {join.to_col.split('.')[0]} "
            f"ON {join.from_col} = {join.to_col}"
        )

    # WHERE clause
    where_parts: list[str] = []
    for filt in plan.filters:
        param_idx += 1
        placeholder = f"${param_idx}" if dialect == "postgres" else "?"
        where_parts.append(f"{filt.column} {filt.operator} {placeholder}")
        params.append(filt.value)

    # GROUP BY
    group_by = ""
    if plan.group_by:
        group_by = f"GROUP BY {', '.join(plan.group_by)}"

    # ORDER BY
    order_by = ""
    if plan.order_by:
        parts = [f"{o.column} {o.direction}" for o in plan.order_by]
        order_by = f"ORDER BY {', '.join(parts)}"

    # LIMIT (default 1000 per BA-011 FR-003 BR-003.3)
    limit = plan.limit or 1000

    # Assemble
    sql_parts = [f"SELECT {select_clause}", f"FROM {from_table}"]
    sql_parts.extend(join_clauses)
    if where_parts:
        sql_parts.append(f"WHERE {' AND '.join(where_parts)}")
    if group_by:
        sql_parts.append(group_by)
    if order_by:
        sql_parts.append(order_by)
    sql_parts.append(f"LIMIT {limit}")

    return " ".join(sql_parts), params
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_nl_query/test_sql_generator.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/nl_query/sql_generator.py tests/test_nl_query/test_sql_generator.py pyproject.toml
git commit -m "feat: add SQL generator from query plans (BA-011 FR-003)"
```

---

### Task 12: NL Query Engine

**Files:**
- Create: `src/ennam_kg/nl_query/engine.py`
- Test: `tests/test_nl_query/test_engine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_nl_query/test_engine.py
from __future__ import annotations

import json
import pytest

from ennam_kg.ai_client.models import AIResponse, AIUsage
from ennam_kg.nl_query.engine import NLQueryEngine, NLQueryResult


class FakeKGClient:
    async def get_schema_metadata(self, data_source_id):
        return {
            "tables": {
                "orders": {
                    "columns": {"id": "integer", "total": "numeric", "created_at": "timestamp"},
                    "primary_key": "id",
                    "foreign_keys": [],
                },
            }
        }

    async def submit_nl_query(self, project_id, data_source_id, query):
        return {
            "id": "q-1",
            "status": "completed",
            "sql": "SELECT * FROM orders",
            "results": {"columns": ["id", "total"], "rows": [[1, 100.0], [2, 200.0]]},
        }


class FakeAIClient:
    def __init__(self):
        self.call_count = 0

    async def complete(self, request):
        self.call_count += 1
        if self.call_count == 1:
            # Intent parsing response
            return AIResponse(
                content=json.dumps({
                    "tables": ["orders"],
                    "joins": [],
                    "filters": [],
                    "aggregations": [],
                    "group_by": [],
                    "order_by": [],
                    "limit": None,
                }),
                usage=AIUsage(input_tokens=300, output_tokens=100),
                model="test", provider="test",
            )
        # Summary response
        return AIResponse(
            content="Found 2 orders with a total value of $300.",
            usage=AIUsage(input_tokens=200, output_tokens=30),
            model="test", provider="test",
        )


@pytest.mark.asyncio
async def test_nl_query_end_to_end():
    engine = NLQueryEngine(kg_client=FakeKGClient(), ai_client=FakeAIClient())
    result = await engine.query(
        project_id="proj-1",
        data_source_id="ds-1",
        natural_language="show me all orders",
    )
    assert isinstance(result, NLQueryResult)
    assert result.sql is not None
    assert "orders" in result.sql
    assert result.summary is not None
    assert len(result.errors) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_nl_query/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement NL query engine**

```python
# src/ennam_kg/nl_query/engine.py
"""Orchestrates the NL-to-SQL query pipeline (BA-011)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ennam_kg.ai_client.models import AIRequest
from ennam_kg.nl_query.intent_parser import IntentParseError, parse_intent
from ennam_kg.nl_query.prompts import get_nl_summary_prompt
from ennam_kg.nl_query.sql_generator import SQLGenerationError, generate_sql

if TYPE_CHECKING:
    from ennam_kg.ai_client.client import AIClient
    from ennam_kg.kg_client.client import KGClient

logger = logging.getLogger(__name__)

MAX_RETRIES = 2  # BA-011 FR-007 BR-007.3


@dataclass
class NLQueryResult:
    """Result of an NL query pipeline execution."""

    query_id: str | None = None
    sql: str | None = None
    parameters: list[str] = field(default_factory=list)
    results: dict[str, Any] | None = None
    summary: str | None = None
    tables_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    retries: int = 0


class NLQueryEngine:
    """Orchestrates NL → intent → SQL → execute → summarize (BA-011)."""

    def __init__(self, kg_client: KGClient, ai_client: AIClient):
        self._kg = kg_client
        self._ai = ai_client

    async def query(
        self,
        project_id: str,
        data_source_id: str,
        natural_language: str,
    ) -> NLQueryResult:
        """Execute a full NL query pipeline.

        Pipeline:
        1. Fetch schema metadata
        2. Parse intent (NL → QueryPlan)
        3. Generate SQL (QueryPlan → parameterized SQL)
        4. Execute via Go API (delegates to MCP connector)
        5. Generate NL summary
        """
        result = NLQueryResult()

        # 1. Fetch schema
        try:
            schema = await self._kg.get_schema_metadata(data_source_id)
        except Exception as exc:
            result.errors.append(f"Failed to fetch schema: {exc}")
            return result

        # 2. Parse intent
        try:
            plan = await parse_intent(natural_language, schema, self._ai)
            result.tables_used = plan.tables
        except IntentParseError as exc:
            result.errors.append(f"Intent parsing failed: {exc}")
            return result

        # 3. Generate SQL
        try:
            sql, params = generate_sql(plan, dialect="postgres")
            result.sql = sql
            result.parameters = params
        except SQLGenerationError as exc:
            result.errors.append(f"SQL generation failed: {exc}")
            return result

        # 4. Execute via Go API
        try:
            exec_result = await self._kg.submit_nl_query(
                project_id=project_id,
                data_source_id=data_source_id,
                query=natural_language,
            )
            result.query_id = exec_result.get("id")
            result.results = exec_result.get("results")
        except Exception as exc:
            result.errors.append(f"Query execution failed: {exc}")
            return result

        # 5. Generate NL summary
        try:
            results_preview = str(result.results)[:2000]
            summary_prompt = get_nl_summary_prompt(natural_language, sql, results_preview)
            summary_resp = await self._ai.complete(
                AIRequest(prompt=summary_prompt, max_tokens=300)
            )
            result.summary = summary_resp.content.strip()
        except Exception as exc:
            logger.warning("Failed to generate summary: %s", exc)
            # Summary failure is non-fatal

        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_nl_query/test_engine.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/nl_query/engine.py tests/test_nl_query/test_engine.py
git commit -m "feat: add NL query engine orchestrator (BA-011)"
```

---

## Wave 4: Benchmark Runner (BA-013)

### Task 13: Benchmark Scorer

**Files:**
- Create: `src/ennam_kg/benchmark/__init__.py`
- Create: `src/ennam_kg/benchmark/scorer.py`
- Test: `tests/test_benchmark/test_scorer.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_benchmark/test_scorer.py
from __future__ import annotations

from ennam_kg.benchmark.scorer import ScoreLevel, score_result


def test_exact_match():
    expected = {"columns": ["id", "name"], "rows": [[1, "Alice"], [2, "Bob"]]}
    actual = {"columns": ["id", "name"], "rows": [[1, "Alice"], [2, "Bob"]]}
    result = score_result(expected, actual)
    assert result.level == ScoreLevel.EXACT_MATCH
    assert result.score == 1.0


def test_semantic_match_different_order():
    expected = {"columns": ["id", "name"], "rows": [[1, "Alice"], [2, "Bob"]]}
    actual = {"columns": ["id", "name"], "rows": [[2, "Bob"], [1, "Alice"]]}
    result = score_result(expected, actual)
    assert result.level == ScoreLevel.SEMANTIC_MATCH
    assert result.score >= 0.9


def test_partial_match():
    expected = {"columns": ["id", "name"], "rows": [[1, "Alice"], [2, "Bob"], [3, "Carol"]]}
    actual = {"columns": ["id", "name"], "rows": [[1, "Alice"], [2, "Bob"]]}
    result = score_result(expected, actual)
    assert result.level == ScoreLevel.PARTIAL_MATCH
    assert 0.0 < result.score < 1.0


def test_failure_no_overlap():
    expected = {"columns": ["id"], "rows": [[1], [2], [3]]}
    actual = {"columns": ["id"], "rows": [[10], [20], [30]]}
    result = score_result(expected, actual)
    assert result.level == ScoreLevel.FAILURE
    assert result.score == 0.0


def test_failure_empty_actual():
    expected = {"columns": ["id"], "rows": [[1]]}
    actual = {"columns": [], "rows": []}
    result = score_result(expected, actual)
    assert result.level == ScoreLevel.FAILURE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_benchmark/test_scorer.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement scorer**

```python
# src/ennam_kg/benchmark/__init__.py
```

```python
# src/ennam_kg/benchmark/scorer.py
"""Accuracy scoring for benchmark results (BA-013 FR-004)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScoreLevel(str, Enum):
    EXACT_MATCH = "exact_match"       # 1.0 — identical results
    SEMANTIC_MATCH = "semantic_match"  # 0.9 — same data, different order
    PARTIAL_MATCH = "partial_match"    # 0.1-0.8 — overlapping subset
    FAILURE = "failure"               # 0.0 — no meaningful overlap


@dataclass
class ScoreResult:
    level: ScoreLevel
    score: float
    detail: str = ""


def score_result(
    expected: dict,
    actual: dict,
) -> ScoreResult:
    """Score actual results against expected results.

    Scoring levels (BA-013 FR-004):
    - Exact match: identical columns + rows in same order
    - Semantic match: same data, different row order
    - Partial match: overlapping rows (score = overlap / expected)
    - Failure: no meaningful overlap
    """
    expected_rows = [tuple(r) for r in expected.get("rows", [])]
    actual_rows = [tuple(r) for r in actual.get("rows", [])]

    if not expected_rows and not actual_rows:
        return ScoreResult(level=ScoreLevel.EXACT_MATCH, score=1.0, detail="Both empty")

    if not actual_rows:
        return ScoreResult(level=ScoreLevel.FAILURE, score=0.0, detail="No results returned")

    # Exact match: same order
    if expected_rows == actual_rows:
        return ScoreResult(level=ScoreLevel.EXACT_MATCH, score=1.0, detail="Identical results")

    # Semantic match: same set, different order
    if set(expected_rows) == set(actual_rows) and len(expected_rows) == len(actual_rows):
        return ScoreResult(
            level=ScoreLevel.SEMANTIC_MATCH,
            score=0.95,
            detail="Same data, different row order",
        )

    # Partial match: compute overlap
    expected_set = set(expected_rows)
    actual_set = set(actual_rows)
    overlap = expected_set & actual_set

    if not overlap:
        return ScoreResult(level=ScoreLevel.FAILURE, score=0.0, detail="No overlapping rows")

    overlap_ratio = len(overlap) / len(expected_set)
    return ScoreResult(
        level=ScoreLevel.PARTIAL_MATCH,
        score=round(overlap_ratio, 2),
        detail=f"{len(overlap)}/{len(expected_set)} rows match",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_benchmark/test_scorer.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/benchmark/ tests/test_benchmark/
git commit -m "feat: add benchmark accuracy scorer (BA-013 FR-004)"
```

---

### Task 14: Benchmark Runner + Engine

**Files:**
- Create: `src/ennam_kg/benchmark/runner.py`
- Create: `src/ennam_kg/benchmark/engine.py`
- Test: `tests/test_benchmark/test_engine.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_benchmark/test_engine.py
from __future__ import annotations

import json
import pytest

from ennam_kg.ai_client.models import AIResponse, AIUsage
from ennam_kg.benchmark.engine import BenchmarkEngine, BenchmarkRunResult


class FakeKGClient:
    async def get_schema_metadata(self, data_source_id):
        return {
            "tables": {
                "orders": {
                    "columns": {"id": "integer", "total": "numeric"},
                    "primary_key": "id",
                    "foreign_keys": [],
                },
            }
        }

    async def get_benchmark_questions(self, data_source_id):
        return {
            "questions": [
                {
                    "id": "bq-1",
                    "text": "How many orders?",
                    "difficulty": "simple",
                    "query_type": "aggregation",
                    "expected_results": {"columns": ["count"], "rows": [[42]]},
                },
                {
                    "id": "bq-2",
                    "text": "Show all orders",
                    "difficulty": "simple",
                    "query_type": "filter",
                    "expected_results": {"columns": ["id", "total"], "rows": [[1, 100]]},
                },
            ]
        }

    async def submit_nl_query(self, project_id, data_source_id, query):
        if "how many" in query.lower():
            return {"id": "q-1", "status": "completed", "sql": "SELECT COUNT(*) FROM orders",
                    "results": {"columns": ["count"], "rows": [[42]]}}
        return {"id": "q-2", "status": "completed", "sql": "SELECT * FROM orders",
                "results": {"columns": ["id", "total"], "rows": [[1, 100]]}}

    async def submit_benchmark_result(self, run_id, question_id, result):
        return {"id": f"br-{question_id}"}


class FakeAIClient:
    async def complete(self, request):
        return AIResponse(
            content=json.dumps({
                "tables": ["orders"], "joins": [], "filters": [],
                "aggregations": [], "group_by": [], "order_by": [], "limit": None,
            }),
            usage=AIUsage(input_tokens=100, output_tokens=50),
            model="test", provider="test",
        )


@pytest.mark.asyncio
async def test_benchmark_run():
    engine = BenchmarkEngine(
        kg_client=FakeKGClient(),
        ai_client=FakeAIClient(),
    )
    result = await engine.run(
        project_id="proj-1",
        data_source_id="ds-1",
        run_id="run-1",
    )
    assert isinstance(result, BenchmarkRunResult)
    assert result.total_questions == 2
    assert result.accuracy >= 0.9  # Both should be exact matches
    assert result.exact_matches >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_benchmark/test_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement benchmark engine**

```python
# src/ennam_kg/benchmark/runner.py
"""Execute a single benchmark question through the NL pipeline (BA-013 FR-003)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ennam_kg.benchmark.scorer import ScoreResult, score_result
from ennam_kg.nl_query.engine import NLQueryEngine

if TYPE_CHECKING:
    from ennam_kg.ai_client.client import AIClient
    from ennam_kg.kg_client.client import KGClient

logger = logging.getLogger(__name__)


@dataclass
class QuestionResult:
    question_id: str
    question_text: str
    generated_sql: str | None
    score: ScoreResult
    error: str | None = None


async def run_question(
    question: dict[str, Any],
    nl_engine: NLQueryEngine,
    project_id: str,
    data_source_id: str,
) -> QuestionResult:
    """Run a single benchmark question through the NL query pipeline."""
    question_id = question["id"]
    question_text = question["text"]
    expected = question.get("expected_results", {})

    try:
        query_result = await nl_engine.query(
            project_id=project_id,
            data_source_id=data_source_id,
            natural_language=question_text,
        )

        if query_result.errors:
            return QuestionResult(
                question_id=question_id,
                question_text=question_text,
                generated_sql=query_result.sql,
                score=ScoreResult(level="failure", score=0.0, detail="; ".join(query_result.errors)),
                error="; ".join(query_result.errors),
            )

        actual = query_result.results or {"columns": [], "rows": []}
        scored = score_result(expected, actual)

        return QuestionResult(
            question_id=question_id,
            question_text=question_text,
            generated_sql=query_result.sql,
            score=scored,
        )
    except Exception as exc:
        logger.warning("Benchmark question %s failed: %s", question_id, exc)
        return QuestionResult(
            question_id=question_id,
            question_text=question_text,
            generated_sql=None,
            score=ScoreResult(level="failure", score=0.0, detail=str(exc)),
            error=str(exc),
        )
```

```python
# src/ennam_kg/benchmark/engine.py
"""Orchestrates benchmark runs (BA-013 FR-003)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ennam_kg.benchmark.runner import QuestionResult, run_question
from ennam_kg.benchmark.scorer import ScoreLevel
from ennam_kg.nl_query.engine import NLQueryEngine

if TYPE_CHECKING:
    from ennam_kg.ai_client.client import AIClient
    from ennam_kg.kg_client.client import KGClient

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkRunResult:
    """Summary of a benchmark run."""

    run_id: str = ""
    total_questions: int = 0
    exact_matches: int = 0
    semantic_matches: int = 0
    partial_matches: int = 0
    failures: int = 0
    accuracy: float = 0.0
    question_results: list[QuestionResult] = field(default_factory=list)

    def _compute_accuracy(self) -> None:
        if self.total_questions == 0:
            self.accuracy = 0.0
            return
        total_score = sum(qr.score.score for qr in self.question_results)
        self.accuracy = round(total_score / self.total_questions, 4)


class BenchmarkEngine:
    """Orchestrates benchmark execution (BA-013)."""

    def __init__(self, kg_client: KGClient, ai_client: AIClient):
        self._kg = kg_client
        self._ai = ai_client
        self._nl_engine = NLQueryEngine(kg_client=kg_client, ai_client=ai_client)

    async def run(
        self,
        project_id: str,
        data_source_id: str,
        run_id: str,
    ) -> BenchmarkRunResult:
        """Execute all benchmark questions for a data source.

        Pipeline:
        1. Fetch benchmark questions from Go API
        2. Run each through NL query pipeline
        3. Score results
        4. Submit results back to Go API
        5. Compute aggregate accuracy
        """
        result = BenchmarkRunResult(run_id=run_id)

        # 1. Fetch questions
        questions_data = await self._kg.get_benchmark_questions(data_source_id)
        questions = questions_data.get("questions", [])
        result.total_questions = len(questions)

        # 2-3. Run and score each question
        for question in questions:
            qr = await run_question(
                question=question,
                nl_engine=self._nl_engine,
                project_id=project_id,
                data_source_id=data_source_id,
            )
            result.question_results.append(qr)

            # Classify
            if qr.score.level == ScoreLevel.EXACT_MATCH:
                result.exact_matches += 1
            elif qr.score.level == ScoreLevel.SEMANTIC_MATCH:
                result.semantic_matches += 1
            elif qr.score.level == ScoreLevel.PARTIAL_MATCH:
                result.partial_matches += 1
            else:
                result.failures += 1

            # 4. Submit to Go API
            try:
                await self._kg.submit_benchmark_result(
                    run_id=run_id,
                    question_id=qr.question_id,
                    result={
                        "score": qr.score.score,
                        "score_level": qr.score.level,
                        "generated_sql": qr.generated_sql,
                        "detail": qr.score.detail,
                        "error": qr.error,
                    },
                )
            except Exception as exc:
                logger.warning("Failed to submit result for %s: %s", qr.question_id, exc)

        # 5. Compute accuracy
        result._compute_accuracy()

        logger.info(
            "Benchmark run %s: %d questions, accuracy=%.1f%%, exact=%d, semantic=%d, partial=%d, fail=%d",
            run_id,
            result.total_questions,
            result.accuracy * 100,
            result.exact_matches,
            result.semantic_matches,
            result.partial_matches,
            result.failures,
        )

        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_benchmark/test_engine.py -v`
Expected: 1 passed

- [ ] **Step 5: Run all tests**

Run: `cd ennam.kg.python && uv run pytest -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/benchmark/ tests/test_benchmark/
git commit -m "feat: add benchmark runner and engine (BA-013)"
```

---

### Task 15: Wire Phase 2 Into Worker + New Queue Messages

**Files:**
- Modify: `src/ennam_kg/worker.py`
- Modify: `src/ennam_kg/queue/messages.py`
- Test: `tests/test_worker_phase2.py`

- [ ] **Step 1: Write failing test for new message handling**

```python
# tests/test_worker_phase2.py
from __future__ import annotations

import json
import pytest

from ennam_kg.queue.messages import GenerateKGMessage, ProcessNLQueryMessage, RunBenchmarkMessage


def test_generate_kg_message():
    msg = GenerateKGMessage(
        type="generate_kg",
        project_id="proj-1",
        data_source_id="ds-1",
        include_implicit=True,
    )
    assert msg.type == "generate_kg"
    assert msg.data_source_id == "ds-1"


def test_process_nl_query_message():
    msg = ProcessNLQueryMessage(
        type="process_nl_query",
        project_id="proj-1",
        data_source_id="ds-1",
        query="show all orders",
        query_id="q-1",
    )
    assert msg.query == "show all orders"


def test_run_benchmark_message():
    msg = RunBenchmarkMessage(
        type="run_benchmark",
        project_id="proj-1",
        data_source_id="ds-1",
        run_id="run-1",
    )
    assert msg.run_id == "run-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_worker_phase2.py -v`
Expected: FAIL — `ImportError` for new message types

- [ ] **Step 3: Add new message types**

Append to `src/ennam_kg/queue/messages.py`:

```python
class ProcessNLQueryMessage(BaseModel):
    """Message to process a natural language query."""

    type: str  # "process_nl_query"
    project_id: str
    data_source_id: str
    query: str
    query_id: str
    timestamp: str = ""


class RunBenchmarkMessage(BaseModel):
    """Message to run a benchmark suite."""

    type: str  # "run_benchmark"
    project_id: str
    data_source_id: str
    run_id: str
    timestamp: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_worker_phase2.py -v`
Expected: 3 passed

- [ ] **Step 5: Update worker.py with new message handlers**

In `src/ennam_kg/worker.py`, add to `handle_message`:

```python
from ennam_kg.kg_generator.engine import KGGenerationEngine
from ennam_kg.nl_query.engine import NLQueryEngine
from ennam_kg.benchmark.engine import BenchmarkEngine

# ... inside _run_worker, after existing engine initialization:
    kg_gen_engine = KGGenerationEngine(kg_client=kg_client, ai_client=ai_client)
    nl_engine = NLQueryEngine(kg_client=kg_client, ai_client=ai_client)
    benchmark_engine = BenchmarkEngine(kg_client=kg_client, ai_client=ai_client)

    # ... inside handle_message, add:
        elif msg_type == "generate_kg":
            ds_id = msg.get("data_source_id", "")
            include_implicit = msg.get("include_implicit", True)
            logger.info("Starting KG generation: project=%s ds=%s", project_id, ds_id)
            result = await kg_gen_engine.generate(project_id, ds_id, include_implicit)
            logger.info(
                "KG generation done: %d nodes, %d edges, %d implicit",
                result.nodes_created, result.edges_created, result.implicit_candidates,
            )

        elif msg_type == "process_nl_query":
            ds_id = msg.get("data_source_id", "")
            query = msg.get("query", "")
            logger.info("Processing NL query: project=%s query=%s", project_id, query[:50])
            result = await nl_engine.query(project_id, ds_id, query)
            logger.info("NL query done: sql=%s errors=%d", result.sql[:80] if result.sql else "none", len(result.errors))

        elif msg_type == "run_benchmark":
            ds_id = msg.get("data_source_id", "")
            run_id = msg.get("run_id", "")
            logger.info("Starting benchmark run: project=%s run=%s", project_id, run_id)
            result = await benchmark_engine.run(project_id, ds_id, run_id)
            logger.info("Benchmark done: accuracy=%.1f%% (%d questions)", result.accuracy * 100, result.total_questions)
```

- [ ] **Step 6: Run all tests**

Run: `cd ennam.kg.python && uv run pytest -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/worker.py src/ennam_kg/queue/messages.py tests/test_worker_phase2.py
git commit -m "feat: wire Phase 2 engines into worker with new queue messages"
```

---

### Task 16: Add Phase 2 HTTP Endpoints

**Files:**
- Create: `src/ennam_kg/api/phase2.py`
- Modify: `src/ennam_kg/api/__init__.py`
- Test: `tests/test_api/test_phase2.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_api/test_phase2.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_health_includes_phase2(client):
    """Smoke test — Phase 2 router registered."""
    response = client.get("/api/v1/phase2/health")
    assert response.status_code == 200
    assert response.json()["phase"] == "2"
```

Note: Exact test setup depends on existing test fixtures. Create a FastAPI TestClient fixture if not present.

- [ ] **Step 2: Implement Phase 2 API router**

```python
# src/ennam_kg/api/phase2.py
"""Phase 2 HTTP endpoints — manual triggers for KG generation, NL query, benchmark."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/phase2", tags=["phase2"])


@router.get("/health")
async def phase2_health():
    """Phase 2 subsystem health check."""
    return {
        "status": "ok",
        "phase": "2",
        "capabilities": ["kg_generation", "nl_query", "benchmark"],
    }
```

Register the router in `src/ennam_kg/api/__init__.py`.

- [ ] **Step 3: Run test, commit**

```bash
cd ennam.kg.python
git add src/ennam_kg/api/phase2.py src/ennam_kg/api/__init__.py tests/test_api/test_phase2.py
git commit -m "feat: add Phase 2 HTTP endpoints scaffold"
```

---

## Summary

| Wave | Tasks | BA Source | New Files | Key Deliverable |
|------|-------|----------|-----------|-----------------|
| 1 | 1-4 | BA-009 | `ai_client/` (3 files) | AI provider abstraction client + summarizer migration |
| 2 | 5-9 | BA-008 | `kg_generator/` (5 files) | Implicit detection + AI descriptions + KGClient extensions |
| 3 | 10-12 | BA-011 | `nl_query/` (5 files) | Intent parser + SQL generator + NL query engine |
| 4 | 13-16 | BA-013 | `benchmark/` (4 files) + `api/phase2.py` | Benchmark scorer + runner + worker wiring + HTTP endpoints |

**Total**: ~22 new source files, ~12 new test files, 16 tasks, ~64 steps

**Go API Prerequisites**: Each wave depends on corresponding Go API endpoints being available. Development can proceed with mocked Go API responses (test doubles), but integration testing requires the Go endpoints from BA-007, BA-009, BA-011, BA-013.

**Exit Criteria**: BA-013 requires >= 95% accuracy on the benchmark suite. The benchmark runner (Wave 4) provides the measurement framework, but achieving 95% will likely require iterative prompt tuning in Wave 3's NL query pipeline.
