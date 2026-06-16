# IMP-006 P4b — OpenAI-Compatible Agentic Chat (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the agentic chat engine run on an **OpenAI-compatible** model (e.g. BytePlus `glm-4.7`/`kimi-k2.5`) when `ai.model.agentic` points at one — removing the P4a 501 — **without changing the engine or the working Anthropic path**.

**Architecture:** P4a already resolves `ai.model.agentic`, sends `X-AI-Provider-Type`/`X-AI-Base-URL`, and the agentic endpoint 501s on non-Anthropic. P4b adds an `OpenAIDirectClient` that **mimics the exact subset of the Anthropic SDK the engine consumes** — `client._client.messages.stream(model, max_tokens, system, messages, tools)` returning an async context manager that (a) `async for`-yields `content_block_delta`/`text_delta`-shaped events and (b) exposes `get_final_message()` returning an Anthropic-shaped `Message` (`.stop_reason`, `.content[]` text/tool_use blocks, `.usage`). All wire-format translation (Anthropic↔OpenAI for tools, messages, and the streamed tool-call accumulation) lives inside this client, built on `httpx` (no new dependency). The agentic endpoint picks `OpenAIDirectClient` vs `AnthropicDirectClient` by `provider_type`. `engine.py`, `AnthropicDirectClient`, and `agentic/tools.py` are **untouched** — zero regression risk to the Anthropic chat path.

**Tech Stack:** Python 3.12, `httpx` (streaming SSE), pytest + `pytest-httpx` (already deps). No `openai` SDK.

**Builds on P4a** (merged): `agentic` in `models.AIFunctions`; `Selector.ResolveEntry`; `CredentialInjection.ProviderType`; sse_stream sends `X-AI-Provider-Type`/`X-AI-Base-URL`/`X-AI-Model-ID`; `api/agentic.py._create_engine` 501s for non-Anthropic provider types; `_resolve_chat_model` honors the injected model.

**The exact engine contract this client must satisfy** (`agentic/engine.py`, unchanged):
- Calls `self._ai._client.messages.stream(model=…, max_tokens=…, system=[{"type":"text","text":…,"cache_control":…}], messages=[…], tools=[{"name","description","input_schema",…}])` as an `async with` context manager.
- `async for event in stream:` reads events where `event.type == "content_block_delta"` and `event.delta.type == "text_delta"` → `event.delta.text`.
- `response = await stream.get_final_message()` → `response.usage.input_tokens`/`.output_tokens` (cache fields read via `getattr(…, 0)`), `response.stop_reason` in `{"end_turn","tool_use"}`, `response.content` = blocks with `.type` (`"text"`→`.text`, `"tool_use"`→`.id`/`.name`/`.input` dict).
- `messages` it passes back contain Anthropic content blocks: assistant `{"type":"text"|"tool_use"}`, user `{"type":"tool_result","tool_use_id","content","is_error"?}`; the first user turn is a plain string.

---

## File Structure

**Create:**
- `ennam.kg.python/src/ennam_kg/ai_client/openai_direct_client.py` — translation fns + stream accumulator + the Anthropic-mimicking `OpenAIDirectClient`.
- `ennam.kg.python/tests/test_ai_client/test_openai_direct_client.py`

**Modify:**
- `ennam.kg.python/src/ennam_kg/api/agentic.py` — build `OpenAIDirectClient` for `provider_type == "openai"` (replace the 501).

---

## Task 1: Tool-definition translation (Anthropic → OpenAI)

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/ai_client/openai_direct_client.py`
- Test: `ennam.kg.python/tests/test_ai_client/test_openai_direct_client.py`

- [ ] **Step 1: Write the failing test**

Create `ennam.kg.python/tests/test_ai_client/test_openai_direct_client.py`:

```python
from ennam_kg.ai_client.openai_direct_client import anthropic_tools_to_openai


def test_tool_translation():
    tools = [
        {
            "name": "search_kg",
            "description": "Search the KG",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            "cache_control": {"type": "ephemeral"},
        }
    ]
    out = anthropic_tools_to_openai(tools)
    assert out == [
        {
            "type": "function",
            "function": {
                "name": "search_kg",
                "description": "Search the KG",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            },
        }
    ]


def test_tool_translation_empty():
    assert anthropic_tools_to_openai([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_ai_client/test_openai_direct_client.py::test_tool_translation -q`
Expected: FAIL — module/function not defined.

- [ ] **Step 3: Create the module with the translator**

Create `ennam.kg.python/src/ennam_kg/ai_client/openai_direct_client.py`:

```python
"""OpenAI-compatible chat client that mimics the Anthropic streaming interface
the agentic engine consumes (IMP-006 P4b). Built on httpx; no openai SDK.

The engine calls ``client._client.messages.stream(...)`` expecting an Anthropic
``messages.stream`` context manager. This module translates Anthropic tool defs,
message blocks, and the streamed response to/from OpenAI Chat Completions, exposing
Anthropic-shaped duck-typed objects so the engine needs no changes.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx

from ennam_kg.ai_client.client import AIClientError


def anthropic_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Translate Anthropic tool defs to OpenAI function-tool format.

    Anthropic: {"name", "description", "input_schema", "cache_control"?}
    OpenAI:    {"type":"function", "function":{"name","description","parameters"}}
    """
    out: list[dict] = []
    for t in tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
        )
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.python && uv run pytest tests/test_ai_client/test_openai_direct_client.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ennam_kg/ai_client/openai_direct_client.py tests/test_ai_client/test_openai_direct_client.py
git commit -m "feat(ai): Anthropic→OpenAI tool-def translation (IMP-006 P4b)"
```

---

## Task 2: Message translation (Anthropic blocks → OpenAI messages)

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ai_client/openai_direct_client.py`
- Test: `ennam.kg.python/tests/test_ai_client/test_openai_direct_client.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ai_client/test_openai_direct_client.py`:

```python
from ennam_kg.ai_client.openai_direct_client import anthropic_messages_to_openai


def test_message_translation_full_loop():
    system = [{"type": "text", "text": "You are an agent.", "cache_control": {"type": "ephemeral"}}]
    messages = [
        {"role": "user", "content": "What tables exist?"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me check."},
                {"type": "tool_use", "id": "call_1", "name": "search_kg", "input": {"query": "tables"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": "found orders, users"},
            ],
        },
    ]
    out = anthropic_messages_to_openai(system, messages)
    assert out[0] == {"role": "system", "content": "You are an agent."}
    assert out[1] == {"role": "user", "content": "What tables exist?"}
    assert out[2]["role"] == "assistant"
    assert out[2]["content"] == "Let me check."
    assert out[2]["tool_calls"] == [
        {"id": "call_1", "type": "function", "function": {"name": "search_kg", "arguments": json.dumps({"query": "tables"})}}
    ]
    assert out[3] == {"role": "tool", "tool_call_id": "call_1", "content": "found orders, users"}
```

(Add `import json` at the top of the test file if not already present.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_ai_client/test_openai_direct_client.py::test_message_translation_full_loop -q`
Expected: FAIL — `anthropic_messages_to_openai` not defined.

- [ ] **Step 3: Add the translator**

Append to `src/ennam_kg/ai_client/openai_direct_client.py`:

```python
def anthropic_messages_to_openai(system_blocks: list[dict], messages: list[dict]) -> list[dict]:
    """Translate the engine's Anthropic-format system + messages to OpenAI messages.

    - system blocks → a single {"role":"system"} message (concatenated text).
    - string content → passed through.
    - assistant content blocks: text → content; tool_use → tool_calls[].
    - user content blocks: tool_result → {"role":"tool", tool_call_id, content};
      text → {"role":"user", content}.
    """
    out: list[dict] = []
    sys_text = "\n".join(b.get("text", "") for b in system_blocks if b.get("type") == "text")
    if sys_text:
        out.append({"role": "system", "content": sys_text})

    for m in messages:
        role = m["role"]
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for b in content:
                if b.get("type") == "text":
                    text_parts.append(b.get("text", ""))
                elif b.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "id": b["id"],
                            "type": "function",
                            "function": {"name": b["name"], "arguments": json.dumps(b.get("input", {}))},
                        }
                    )
            msg: dict = {"role": "assistant", "content": "".join(text_parts) or None}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            out.append(msg)
        else:  # user turn that may carry tool_result blocks
            text_parts = []
            tool_msgs: list[dict] = []
            for b in content:
                if b.get("type") == "tool_result":
                    tc_content = b.get("content", "")
                    if not isinstance(tc_content, str):
                        tc_content = json.dumps(tc_content)
                    tool_msgs.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": tc_content})
                elif b.get("type") == "text":
                    text_parts.append(b.get("text", ""))
            if text_parts:
                out.append({"role": "user", "content": "".join(text_parts)})
            out.extend(tool_msgs)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.python && uv run pytest tests/test_ai_client/test_openai_direct_client.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ennam_kg/ai_client/openai_direct_client.py tests/test_ai_client/test_openai_direct_client.py
git commit -m "feat(ai): Anthropic→OpenAI message-array translation (IMP-006 P4b)"
```

---

## Task 3: Streamed-response accumulator (OpenAI chunks → Anthropic-shaped Message)

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ai_client/openai_direct_client.py`
- Test: `ennam.kg.python/tests/test_ai_client/test_openai_direct_client.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
from ennam_kg.ai_client.openai_direct_client import _OpenAIStreamState


def test_stream_accumulator_text_only():
    st = _OpenAIStreamState()
    assert st.feed({"choices": [{"delta": {"content": "Hel"}}]}) == "Hel"
    assert st.feed({"choices": [{"delta": {"content": "lo"}}]}) == "lo"
    st.feed({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    st.feed({"usage": {"prompt_tokens": 12, "completion_tokens": 3}, "choices": []})
    msg = st.final_message()
    assert msg.stop_reason == "end_turn"
    assert [b.type for b in msg.content] == ["text"]
    assert msg.content[0].text == "Hello"
    assert msg.usage.input_tokens == 12
    assert msg.usage.output_tokens == 3


def test_stream_accumulator_tool_calls_fragmented():
    st = _OpenAIStreamState()
    # OpenAI streams tool_calls in fragments by index.
    st.feed({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_9", "function": {"name": "search_kg"}}]}}]})
    st.feed({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"que'}}]}}]})
    st.feed({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'ry":"x"}'}}]}}]})
    st.feed({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
    msg = st.final_message()
    assert msg.stop_reason == "tool_use"
    blocks = [b for b in msg.content if b.type == "tool_use"]
    assert len(blocks) == 1
    assert blocks[0].id == "call_9"
    assert blocks[0].name == "search_kg"
    assert blocks[0].input == {"query": "x"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_ai_client/test_openai_direct_client.py -k accumulator -q`
Expected: FAIL — `_OpenAIStreamState` not defined.

- [ ] **Step 3: Add the accumulator**

Append:

```python
class _OpenAIStreamState:
    """Accumulates OpenAI Chat-Completions stream chunks into an Anthropic-shaped
    final Message. ``feed(chunk)`` returns the text delta (or None); ``final_message``
    returns a duck-typed object the engine reads like an Anthropic Message.
    """

    def __init__(self) -> None:
        self._text: list[str] = []
        self._tool_calls: dict[int, dict] = {}  # index -> {id, name, args}
        self._prompt_tokens = 0
        self._completion_tokens = 0

    def feed(self, chunk: dict) -> str | None:
        usage = chunk.get("usage")
        if usage:
            self._prompt_tokens = usage.get("prompt_tokens", 0) or 0
            self._completion_tokens = usage.get("completion_tokens", 0) or 0
        choices = chunk.get("choices") or []
        if not choices:
            return None
        delta = choices[0].get("delta") or {}
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            slot = self._tool_calls.setdefault(idx, {"id": "", "name": "", "args": ""})
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["name"] = fn["name"]
            if fn.get("arguments"):
                slot["args"] += fn["arguments"]
        text = delta.get("content")
        if text:
            self._text.append(text)
            return text
        return None

    def final_message(self) -> SimpleNamespace:
        content: list[SimpleNamespace] = []
        joined = "".join(self._text)
        if joined:
            content.append(SimpleNamespace(type="text", text=joined))
        for idx in sorted(self._tool_calls):
            slot = self._tool_calls[idx]
            raw = slot["args"].strip()
            try:
                args = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                args = {}
            content.append(SimpleNamespace(type="tool_use", id=slot["id"], name=slot["name"], input=args))
        stop_reason = "tool_use" if self._tool_calls else "end_turn"
        usage = SimpleNamespace(input_tokens=self._prompt_tokens, output_tokens=self._completion_tokens)
        return SimpleNamespace(stop_reason=stop_reason, content=content, usage=usage)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.python && uv run pytest tests/test_ai_client/test_openai_direct_client.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/ennam_kg/ai_client/openai_direct_client.py tests/test_ai_client/test_openai_direct_client.py
git commit -m "feat(ai): OpenAI stream accumulator → Anthropic-shaped Message (IMP-006 P4b)"
```

---

## Task 4: The streaming client + URL helper (httpx wiring)

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ai_client/openai_direct_client.py`
- Test: `ennam.kg.python/tests/test_ai_client/test_openai_direct_client.py`

- [ ] **Step 1: Write the failing test (URL helper + end-to-end stream via pytest-httpx)**

Append:

```python
import pytest
from ennam_kg.ai_client.openai_direct_client import openai_completions_url, OpenAIDirectClient


def test_completions_url():
    assert openai_completions_url("https://api.openai.com/v1") == "https://api.openai.com/v1/chat/completions"
    assert openai_completions_url("https://api.openai.com") == "https://api.openai.com/v1/chat/completions"
    assert openai_completions_url("https://ark.ap-southeast.bytepluses.com/api/coding/v3") == \
        "https://ark.ap-southeast.bytepluses.com/api/coding/v3/chat/completions"


@pytest.mark.asyncio
async def test_client_streams_text_and_final(httpx_mock):
    sse = (
        b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":" there"}}]}\n\n'
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\n'
        b'data: [DONE]\n\n'
    )
    httpx_mock.add_response(
        url="https://x.test/v1/chat/completions", method="POST",
        status_code=200, content=sse, headers={"content-type": "text/event-stream"},
    )
    client = OpenAIDirectClient(api_key="k", model_id="glm-4.7", base_url="https://x.test/v1")
    deltas = []
    async with client._client.messages.stream(
        model="glm-4.7", max_tokens=100,
        system=[{"type": "text", "text": "sys"}],
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
    ) as stream:
        async for ev in stream:
            if ev.type == "content_block_delta" and ev.delta.type == "text_delta":
                deltas.append(ev.delta.text)
        final = await stream.get_final_message()
    await client.close()
    assert "".join(deltas) == "Hi there"
    assert final.stop_reason == "end_turn"
    assert final.usage.input_tokens == 5
```

> If the installed `pytest-httpx` mocks streaming differently (e.g. requires `stream=...` instead of `content=...`), adjust the `add_response` call to that version's API — the assertions are the contract.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_ai_client/test_openai_direct_client.py -k "completions_url or client_streams" -q`
Expected: FAIL — `openai_completions_url` / `OpenAIDirectClient` not defined.

- [ ] **Step 3: Add the URL helper, the stream CM, and the client**

Append:

```python
def openai_completions_url(base_url: str) -> str:
    """Build the chat-completions URL. If base_url already ends in a version
    segment (".../v1", ".../v3", ".../coding/v3"), append only "/chat/completions";
    otherwise assume a host root and append "/v1/chat/completions"."""
    trimmed = (base_url or "").rstrip("/")
    last = trimmed.rsplit("/", 1)[-1] if "/" in trimmed else ""
    if len(last) >= 2 and last[0] == "v" and last[1].isdigit():
        return trimmed + "/chat/completions"
    return trimmed + "/v1/chat/completions"


class _OpenAIStreamCM:
    """Async context manager mimicking anthropic's messages.stream(...)."""

    def __init__(self, http: httpx.AsyncClient, url: str, headers: dict, payload: dict) -> None:
        self._http = http
        self._url = url
        self._headers = headers
        self._payload = payload
        self._state = _OpenAIStreamState()
        self._resp_cm: Any = None
        self._resp: httpx.Response | None = None

    async def __aenter__(self) -> "_OpenAIStreamCM":
        self._resp_cm = self._http.stream("POST", self._url, headers=self._headers, json=self._payload)
        self._resp = await self._resp_cm.__aenter__()
        if self._resp.status_code >= 400:
            body = await self._resp.aread()
            # AIClientError(status_code: int, detail: str) — see ai_client/client.py.
            raise AIClientError(
                status_code=self._resp.status_code,
                detail=f"openai-compatible stream error: {body[:300]!r}",
            )
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        if self._resp_cm is not None:
            await self._resp_cm.__aexit__(*exc)
        return False

    def __aiter__(self):
        # Return a fresh async generator (matches the codebase's stream-fake pattern
        # in tests/test_agentic/test_engine.py — a sync __aiter__ returning an async gen).
        return self._aiter()

    async def _aiter(self):
        assert self._resp is not None
        async for line in self._resp.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            text = self._state.feed(chunk)
            if text:
                yield SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(type="text_delta", text=text),
                )

    async def get_final_message(self) -> SimpleNamespace:
        return self._state.final_message()


class _OpenAIMessages:
    def __init__(self, http: httpx.AsyncClient, base_url: str, api_key: str) -> None:
        self._http = http
        self._url = openai_completions_url(base_url)
        self._api_key = api_key

    def stream(self, *, model: str, max_tokens: int, system: list[dict], messages: list[dict], tools: list[dict]) -> _OpenAIStreamCM:
        # `stream_options.include_usage` makes the gateway emit token usage in the
        # final chunk. Most OpenAI-compatible gateways (incl. BytePlus Ark) honor it;
        # if a provider 400s on this unknown field (watch for it in Task 6), drop the
        # key — usage then defaults to 0 (budget tracking approximate, streaming +
        # tool-calls still work).
        payload: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "messages": anthropic_messages_to_openai(system, messages),
        }
        oai_tools = anthropic_tools_to_openai(tools)
        if oai_tools:
            payload["tools"] = oai_tools
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        return _OpenAIStreamCM(self._http, self._url, headers, payload)


class _OpenAIChatNamespace:
    def __init__(self, http: httpx.AsyncClient, base_url: str, api_key: str) -> None:
        self.messages = _OpenAIMessages(http, base_url, api_key)


class OpenAIDirectClient:
    """OpenAI-compatible chat client that exposes ``._client.messages.stream`` the
    same way ``AnthropicDirectClient`` does, so the agentic engine is unchanged.
    """

    def __init__(
        self,
        api_key: str,
        model_id: str,
        provider_id: str = "",
        base_url: str | None = None,
        max_tokens_cap: int | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=600.0, write=30.0, pool=10.0)
        )
        self._client = _OpenAIChatNamespace(self._http, base_url or "https://api.openai.com/v1", api_key)
        self._model = model_id
        self._provider_id = provider_id
        self._max_tokens_cap = max_tokens_cap

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def model_id(self) -> str:
        return self._model

    async def close(self) -> None:
        await self._http.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ennam.kg.python && uv run pytest tests/test_ai_client/test_openai_direct_client.py -q`
Expected: PASS (all). If the streaming-mock test is environment-fragile, the URL + accumulator + translation tests (Tasks 1–3) still lock the core logic; the full httpx path is also covered by live acceptance (Task 6).

- [ ] **Step 5: Commit**

```bash
git add src/ennam_kg/ai_client/openai_direct_client.py tests/test_ai_client/test_openai_direct_client.py
git commit -m "feat(ai): OpenAIDirectClient — Anthropic-mimicking streaming over httpx (IMP-006 P4b)"
```

---

## Task 5: Wire the agentic endpoint to use the OpenAI client

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/api/agentic.py`

- [ ] **Step 1: Replace the 501 with the OpenAI client branch**

In `ennam.kg.python/src/ennam_kg/api/agentic.py`, add the import near the `AnthropicDirectClient` import:

```python
from ennam_kg.ai_client.openai_direct_client import OpenAIDirectClient
```

In `_create_engine`, replace the P4a guard block:

```python
    if provider_type not in ("anthropic_api", "claude_max", ""):
        raise HTTPException(
            status_code=501,
            detail=f"agentic chat is not yet supported on provider_type={provider_type!r} (IMP-006 P4b)",
        )

    ai_client = AnthropicDirectClient(api_key=api_key, model_id=model_id, base_url=base_url)
    cleanups.append(ai_client.close)
```

with a provider-type branch:

```python
    if provider_type == "openai":
        ai_client = OpenAIDirectClient(api_key=api_key, model_id=model_id, base_url=base_url)
    elif provider_type in ("anthropic_api", "claude_max", ""):
        ai_client = AnthropicDirectClient(api_key=api_key, model_id=model_id, base_url=base_url)
    else:
        raise HTTPException(
            status_code=501,
            detail=f"agentic chat is not supported on provider_type={provider_type!r}",
        )
    cleanups.append(ai_client.close)
```

> `OpenAIDirectClient` exposes the same `._client.messages.stream`, `_model`, and `close` that the engine + `_create_engine` cleanup use — it is a drop-in. `HTTPException` is already imported (P4a). Unknown/other provider types still 501.

- [ ] **Step 2: Verify lint + the existing agentic tests still pass**

Run: `cd ennam.kg.python && uv run ruff check src/ennam_kg/api/agentic.py && uv run pytest tests/test_agentic -q`
Expected: clean lint; agentic tests green (they mock the Anthropic client; the new branch is openai-only and untouched by them).

- [ ] **Step 3: Commit**

```bash
git add src/ennam_kg/api/agentic.py
git commit -m "feat(agentic): route OpenAI-compatible providers to OpenAIDirectClient (IMP-006 P4b)"
```

---

## Task 6: Live acceptance (against the running stack)

Requires a registered OpenAI-compatible provider whose model has **`supports_tools = true`** (BytePlus, e.g. `glm-4.7` or `kimi-k2.5` — confirm the model actually supports tool-calling; if a model ignores `tools`, the agent won't call tools and will just answer in text).

- [ ] **Step 1: Mark a BytePlus model tool-capable + assign it to agentic** — In **Admin → AI Providers**, set a BytePlus model's **tools** capability on (P3 toggle). In **Per-function model**, assign `Conversational agent (chat)` → that model. Save succeeds (P2 guard now passes: tools required + supported).
- [ ] **Step 2: Plain chat** — start an agentic chat asking a question that needs **no** tools ("Hello, who are you?"). The reply streams token-by-token from the BytePlus model (Go log shows `X-AI-Provider-Type: openai` + the model id; no 501).
- [ ] **Step 3: Tool-calling chat** — ask something that requires a KG tool (e.g. "search the knowledge graph for the orders table"). Confirm a `tool_call_start`/`tool_call_end` SSE pair occurs and the final answer uses the tool result — proving the OpenAI tool-call accumulation + Anthropic-shaped `tool_use` round-trips through the unchanged engine.
- [ ] **Step 4: Anthropic still works** — reassign `ai.model.agentic` to an Anthropic model (or `Auto`) and confirm chat still streams normally (no regression to the unchanged Anthropic path).
- [ ] **Step 5: Error surfacing** — temporarily set the BytePlus model id to a bogus value and chat → the stream surfaces the upstream error (`OpenAI-compatible stream error 4xx…`) rather than hanging.

---

## Done criteria (P4b)

- `anthropic_tools_to_openai`, `anthropic_messages_to_openai`, `_OpenAIStreamState`, `openai_completions_url`, and `OpenAIDirectClient` are implemented + unit-tested (`pytest tests/test_ai_client/test_openai_direct_client.py` green).
- The agentic endpoint builds `OpenAIDirectClient` for `provider_type == "openai"`; the engine, `AnthropicDirectClient`, and `agentic/tools.py` are unchanged (`pytest tests/test_agentic` green).
- Live: agentic chat runs on a tool-capable BytePlus model — plain replies stream, tool-calls round-trip, and the Anthropic path is unaffected. The P4a 501 is gone for `openai` providers (kept for any other unknown type).

This completes IMP-006: every AI function (Path A via the Go selector + agentic via Path B) can be routed to a provider/model from the dashboard, including OpenAI-compatible providers.
```
