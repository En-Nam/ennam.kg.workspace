# Indexer Package Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the code-indexing core (`parsers/`, `indexer/`, `kg_client/`) out of the monolithic `ennam-kg` Python service into a standalone, lightweight, installable `ennam-kg-indexer` package — without breaking any existing feature.

**Architecture:** uv workspace, **Layout 1** — the service stays in place at `src/ennam_kg/` (root `pyproject.toml` is both the service package and the workspace root); only the indexer moves to `packages/ennam-kg-indexer/`. Two behavioral decouplings happen first (remove `embed_texts` config-coupling from the core `KGClient`; drop the unused `Settings` param from `IndexingEngine`), then the physical move + import rewrites, then Docker + verification.

**Tech Stack:** Python 3.12, uv (workspace), tree-sitter, httpx, pydantic, pytest, Docker.

**Reference spec:** `docs/superpowers/specs/2026-06-05-indexer-package-split-design.md`

**Working directory for all commands:** `/Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace/ennam.kg.python` (referred to below as `$PY`). The workspace-root script lives one level up at `../scripts/`.

**macOS `sed`/`xargs` note:** commands use BSD `sed -i ''` (empty backup suffix). Every `grep -rl ... | xargs sed` pass in this plan is guaranteed non-empty input (real old imports exist at that point); do not re-run a pass after it has already rewritten everything, since BSD `xargs` with empty input would invoke `sed` reading stdin and hang. If unsure, run the verifying `grep` first.

---

## Files

| Action | Path |
|--------|------|
| Create | `src/ennam_kg/embeddings/remote.py` (service-side embed helper) |
| Create | `tests/test_embeddings_remote.py` |
| Modify | `src/ennam_kg/kg_client/client.py` (remove `embed_texts`) — moves in Task 4 |
| Modify | `src/ennam_kg/agentic/tools.py` (rewrite embed caller) |
| Modify | `src/ennam_kg/indexer/engine.py` (drop `config`/`Settings`) — moves in Task 4 |
| Modify | `src/ennam_kg/worker.py` (drop engine arg; remove dead summarizer) |
| Modify | `src/ennam_kg/api/indexing.py` (drop engine arg) |
| Modify | `tests/test_engine.py` (drop arg + dead fixture) — moves in Task 4 |
| Create | `packages/ennam-kg-indexer/pyproject.toml` |
| Create | `packages/ennam-kg-indexer/src/ennam_kg_indexer/__init__.py` |
| Move | `src/ennam_kg/{parsers,indexer,kg_client}/` → `packages/ennam-kg-indexer/src/ennam_kg_indexer/` |
| Move | indexer-related tests → `packages/ennam-kg-indexer/tests/` |
| Modify | root `pyproject.toml` (workspace + deps) |
| Modify | `uv.lock` (regenerate) |
| Modify | `Dockerfile` |
| Modify | `../scripts/backfill-section-embeddings.py` (rewrite kg_client import) |

---

### Task 1: Decouple `embed_texts` from the core `KGClient`

The core `KGClient.embed_texts()` does `from ennam_kg.config import settings` — the single hidden coupling that would drag service config into the lightweight package. Move this capability to a service-side helper. The only real caller is `agentic/tools.py:696`.

**Files:**
- Create: `src/ennam_kg/embeddings/remote.py`
- Create: `tests/test_embeddings_remote.py`
- Modify: `src/ennam_kg/agentic/tools.py`
- Modify: `src/ennam_kg/kg_client/client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_embeddings_remote.py`:

```python
"""Tests for the service-side remote embedding helper."""

from __future__ import annotations

import pytest

from ennam_kg.embeddings.remote import embed_texts


@pytest.mark.asyncio
async def test_embed_texts_posts_and_returns_vectors(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://embed.test/api/v1/embeddings",
        json={"embeddings": [[0.1, 0.2, 0.3]]},
    )
    out = await embed_texts(["hello"], base_url="http://embed.test/", api_key="k")
    assert out == [[0.1, 0.2, 0.3]]
    req = httpx_mock.get_request()
    assert req.headers["Authorization"] == "Bearer k"


@pytest.mark.asyncio
async def test_embed_texts_empty_embeddings_returns_empty_list(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="http://embed.test/api/v1/embeddings",
        json={},
    )
    out = await embed_texts(["x"], base_url="http://embed.test", api_key="k")
    assert out == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $PY && uv run pytest tests/test_embeddings_remote.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ennam_kg.embeddings.remote'`

- [ ] **Step 3: Create the helper**

Create `src/ennam_kg/embeddings/remote.py`:

```python
"""Service-side helper to call the Python indexer's /api/v1/embeddings endpoint.

Lives in the service layer (not in the indexer core's KGClient) so the core
package stays free of service-config coupling.
"""

from __future__ import annotations

import httpx


async def embed_texts(texts: list[str], *, base_url: str, api_key: str) -> list[list[float]]:
    """POST texts to the embeddings endpoint and return their vectors."""
    base = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{base}/api/v1/embeddings",
            json={"texts": texts},
            headers={"Authorization": f"Bearer {api_key}"},
        )
    response.raise_for_status()
    body = response.json()
    return body.get("embeddings") or []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $PY && uv run pytest tests/test_embeddings_remote.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Rewrite the caller in `agentic/tools.py`**

At the top of `src/ennam_kg/agentic/tools.py`, add these imports (near the other `ennam_kg` imports):

```python
from ennam_kg.config import settings
from ennam_kg.embeddings.remote import embed_texts as embed_texts_remote
```

Then change the call at `_exec_search_kg_semantic` (currently `vectors = await self._kg.embed_texts([query])`):

```python
            vectors = await embed_texts_remote(
                [query],
                base_url=settings.embedding_service_url,
                api_key=settings.go_api_key,
            )
```

- [ ] **Step 6: Remove `embed_texts` from the core `KGClient`**

In `src/ennam_kg/kg_client/client.py`, delete the entire `embed_texts` method (the `async def embed_texts(...)` block including its `from ennam_kg.config import settings` line). Leave the rest of the class untouched.

- [ ] **Step 7: Verify no service coupling remains in kg_client + full suite green**

Run: `cd $PY && grep -n "ennam_kg.config\|embed_texts" src/ennam_kg/kg_client/client.py`
Expected: no output.

Run: `cd $PY && uv run pytest -q`
Expected: all tests pass (no regression; the agentic semantic-search path now uses the helper).

- [ ] **Step 8: Commit**

```bash
cd $PY
git add src/ennam_kg/embeddings/remote.py tests/test_embeddings_remote.py src/ennam_kg/agentic/tools.py src/ennam_kg/kg_client/client.py
git commit -m "refactor: move embed_texts out of core KGClient into service helper"
```

---

### Task 2: Drop the unused `config`/`Settings` from `IndexingEngine`

`IndexingEngine.__init__` takes a `config: Settings` it never reads, and imports `from ennam_kg.config import Settings` only for that annotation. Removing both severs the indexer's last tie to service config. Two callers (`worker.py`, `api/indexing.py`) and 7 test call sites must drop the second arg.

**Files:**
- Modify: `src/ennam_kg/indexer/engine.py`
- Modify: `src/ennam_kg/worker.py`
- Modify: `src/ennam_kg/api/indexing.py`
- Modify: `tests/test_engine.py`

- [ ] **Step 1: Edit `indexer/engine.py`**

Remove the import line:
```python
from ennam_kg.config import Settings
```

Change the constructor from:
```python
    def __init__(self, kg_client: KGClient, config: Settings):
        self.client = kg_client
        self.extractor = NodeExtractor()
        self.differ = IndexDiffer(kg_client)
        self.config = config
```
to:
```python
    def __init__(self, kg_client: KGClient):
        self.client = kg_client
        self.extractor = NodeExtractor()
        self.differ = IndexDiffer(kg_client)
```

- [ ] **Step 2: Update caller in `worker.py`**

In `src/ennam_kg/worker.py`, change:
```python
    engine = IndexingEngine(kg_client, settings)
```
to:
```python
    engine = IndexingEngine(kg_client)
```

- [ ] **Step 3: Update caller in `api/indexing.py`**

In `src/ennam_kg/api/indexing.py` `_make_engine()`, change:
```python
    return IndexingEngine(kg_client, settings)
```
to:
```python
    return IndexingEngine(kg_client)
```

- [ ] **Step 4: Update `tests/test_engine.py` — drop arg + dead fixture**

There are 7 call sites of `IndexingEngine(mock_kg_client, test_settings)`. Replace each with `IndexingEngine(mock_kg_client)`:

```bash
cd $PY
sed -i '' 's/IndexingEngine(mock_kg_client, test_settings)/IndexingEngine(mock_kg_client)/g' tests/test_engine.py
```

The `test_settings` fixture and its `from ennam_kg.config import Settings` import are now unused. Delete the `test_settings` fixture (the `@pytest.fixture()` + `def test_settings() -> Settings:` block) and the `from ennam_kg.config import Settings` line from `tests/test_engine.py`. Remove `test_settings` from any test function parameter lists that still name it.

- [ ] **Step 5: Run the indexer engine tests**

Run: `cd $PY && uv run pytest tests/test_engine.py -v`
Expected: all pass (the engine builds with one arg; no fixture errors).

- [ ] **Step 6: Verify engine has no config coupling + build check**

Run: `cd $PY && grep -n "ennam_kg.config\|Settings\|self.config" src/ennam_kg/indexer/engine.py`
Expected: no output.

Run: `cd $PY && uv run pytest -q`
Expected: full suite green.

- [ ] **Step 7: Commit**

```bash
cd $PY
git add src/ennam_kg/indexer/engine.py src/ennam_kg/worker.py src/ennam_kg/api/indexing.py tests/test_engine.py
git commit -m "refactor: drop unused config/Settings param from IndexingEngine"
```

---

### Task 3: Remove dead summarizer wiring from `worker.py`

`worker.py` constructs a `ClaudeSummarizer` that is never passed anywhere and never used (verified: the only references to the `summarizer` variable are its own assignment). Remove the dead wiring and now-unused imports. The `summarizer/` module itself stays (untouched) for potential future use.

**Files:**
- Modify: `src/ennam_kg/worker.py`

- [ ] **Step 1: Remove the dead summarizer block**

In `src/ennam_kg/worker.py`, delete these lines (the cache + summarizer setup, currently ~lines 36-43):

```python
    cache = SummaryCache(Path(".summary_cache.json"))
    summarizer: ClaudeSummarizer | None = None
    if settings.go_api_key:  # AI available if Go API is configured
        summarizer = ClaudeSummarizer(ai_client=ai_client, cache=cache)
        logger.info("AI summarization enabled (via Go API abstraction)")
    else:
        logger.info("AI summarization disabled (no Go API key)")
```

- [ ] **Step 2: Remove the orphaned `cache.save()`**

Near the end of `_run_worker` (currently ~line 218), delete:
```python
    # Save summary cache on shutdown
    cache.save()
```

- [ ] **Step 3: Remove now-unused imports**

Delete these import lines from `worker.py` (lines 16 and 18):
```python
from ennam_kg.summarizer.cache import SummaryCache
from ennam_kg.summarizer.claude import ClaudeSummarizer
```

Check whether `Path` is still used elsewhere in `worker.py`:
Run: `cd $PY && grep -n "Path(" src/ennam_kg/worker.py`
If there is NO remaining `Path(` usage, also remove `from pathlib import Path`. If there is, leave the import.

- [ ] **Step 4: Verify worker imports resolve + suite green**

Run: `cd $PY && uv run python -c "import ennam_kg.worker"`
Expected: no error (no NameError for `cache`/`summarizer`, no ImportError).

Run: `cd $PY && uv run pytest -q`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
cd $PY
git add src/ennam_kg/worker.py
git commit -m "refactor: remove dead summarizer wiring from worker"
```

---

### Task 4: Extract the `ennam-kg-indexer` package (structural move)

This is the structural move. After Tasks 1-3 the three target dirs (`parsers/`, `indexer/`, `kg_client/`) have no service coupling except self-references. Move them into the new package, rewrite every import (internal + ~15 service files + 1 root script), wire the uv workspace, regenerate the lock, and end on a fully green suite. Intermediate steps are not green; only the final commit is.

**Files:** (create) `packages/ennam-kg-indexer/pyproject.toml`, `packages/ennam-kg-indexer/src/ennam_kg_indexer/__init__.py`; (move) the three dirs + indexer tests; (modify) root `pyproject.toml`, `uv.lock`, ~15 service files, `../scripts/backfill-section-embeddings.py`.

- [ ] **Step 1: Create the package skeleton**

```bash
cd $PY
mkdir -p packages/ennam-kg-indexer/src/ennam_kg_indexer
mkdir -p packages/ennam-kg-indexer/tests
```

- [ ] **Step 2: Move the three source directories**

```bash
cd $PY
git mv src/ennam_kg/parsers   packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers
git mv src/ennam_kg/indexer   packages/ennam-kg-indexer/src/ennam_kg_indexer/indexer
git mv src/ennam_kg/kg_client packages/ennam-kg-indexer/src/ennam_kg_indexer/kg_client
```

- [ ] **Step 3: Rewrite imports INSIDE the moved package**

```bash
cd $PY
grep -rl "ennam_kg\.\(parsers\|indexer\|kg_client\)" packages/ennam-kg-indexer/src \
  | xargs sed -i '' \
    -e 's/ennam_kg\.parsers/ennam_kg_indexer.parsers/g' \
    -e 's/ennam_kg\.indexer/ennam_kg_indexer.indexer/g' \
    -e 's/ennam_kg\.kg_client/ennam_kg_indexer.kg_client/g'
```

Verify the moved package no longer references the service namespace at all:
Run: `cd $PY && grep -rn "ennam_kg\." packages/ennam-kg-indexer/src/`
Expected: no output (every reference is now `ennam_kg_indexer.`).

- [ ] **Step 4: Create the package public API `__init__.py`**

Create `packages/ennam-kg-indexer/src/ennam_kg_indexer/__init__.py`:

```python
"""ennam-kg-indexer: standalone code indexer (AST parse → extract → diff → push)."""

from ennam_kg_indexer.indexer.engine import IndexingEngine, IndexResult
from ennam_kg_indexer.kg_client.client import KGClient

__all__ = ["IndexingEngine", "IndexResult", "KGClient"]
```

- [ ] **Step 5: Create the indexer package `pyproject.toml`**

Create `packages/ennam-kg-indexer/pyproject.toml`:

```toml
[project]
name = "ennam-kg-indexer"
version = "0.1.0"
description = "Standalone code indexer for Ennam KG — AST parsing, diffing, and node push"
requires-python = ">=3.12"
dependencies = [
    "tree-sitter>=0.23",
    "tree-sitter-typescript>=0.23",
    "tree-sitter-python>=0.23",
    "tree-sitter-go>=0.23",
    "pathspec>=0.12",
    "httpx>=0.28",
    "pydantic>=2.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ennam_kg_indexer"]
```

- [ ] **Step 6: Move the indexer tests into the package**

Move BEFORE rewriting, so the next step can rewrite both the service and the package in clean disjoint passes. Note both `tests/test_kg_client/` (models test) AND `tests/kg_client/` (KGClient neighbors-normalize test) are KGClient tests with no service-fixture coupling — both move.

```bash
cd $PY
git mv tests/test_parsers             packages/ennam-kg-indexer/tests/test_parsers
git mv tests/test_engine.py           packages/ennam-kg-indexer/tests/test_engine.py
git mv tests/test_differ.py           packages/ennam-kg-indexer/tests/test_differ.py
git mv tests/test_extractor.py        packages/ennam-kg-indexer/tests/test_extractor.py
git mv tests/test_kg_client           packages/ennam-kg-indexer/tests/test_kg_client
git mv tests/test_kg_client.py        packages/ennam-kg-indexer/tests/test_kg_client.py
git mv tests/test_kg_client_phase2.py packages/ennam-kg-indexer/tests/test_kg_client_phase2.py
git mv tests/kg_client                packages/ennam-kg-indexer/tests/kg_client
```

- [ ] **Step 7: Rewrite imports in ALL remaining service code, the root script, AND the service tests that stay**

The moved indexer tests are now out of `tests/`. The service tests that REMAIN and still import the moved modules (`test_worker.py`, `test_token_propagation.py`, `test_streaming/test_engine.py`, `test_api_indexing.py`, `test_agentic/test_tools.py`) must also be rewritten — so the rewrite must cover `tests/` too, not just `src/`.

```bash
cd $PY
# Service package (src/), workspace-root script (../scripts/), AND remaining service tests (tests/)
grep -rl "ennam_kg\.\(parsers\|indexer\|kg_client\)" src/ ../scripts/ tests/ \
  | xargs sed -i '' \
    -e 's/ennam_kg\.parsers/ennam_kg_indexer.parsers/g' \
    -e 's/ennam_kg\.indexer/ennam_kg_indexer.indexer/g' \
    -e 's/ennam_kg\.kg_client/ennam_kg_indexer.kg_client/g'

# The moved package (src + tests)
grep -rl "ennam_kg\.\(parsers\|indexer\|kg_client\)" packages/ennam-kg-indexer \
  | xargs sed -i '' \
    -e 's/ennam_kg\.parsers/ennam_kg_indexer.parsers/g' \
    -e 's/ennam_kg\.indexer/ennam_kg_indexer.indexer/g' \
    -e 's/ennam_kg\.kg_client/ennam_kg_indexer.kg_client/g'
```

Verify the OLD paths are fully gone from service code, scripts, and service tests:
Run: `cd $PY && grep -rn "ennam_kg\.parsers\|ennam_kg\.indexer\|ennam_kg\.kg_client" src/ ../scripts/ tests/`
Expected: no output.

- [ ] **Step 8: Update the root `pyproject.toml` (workspace + deps)**

In `$PY/pyproject.toml`:

1. Add the indexer to `dependencies` and REMOVE the now-transitive `tree-sitter*`, `tree-sitter-typescript`, `tree-sitter-python`, `tree-sitter-go`, `pathspec`, and `httpx` lines (they come via `ennam-kg-indexer`). Add `"ennam-kg-indexer",` as the first dependency.
2. Append the workspace + source declarations:

```toml
[tool.uv.workspace]
members = ["packages/ennam-kg-indexer"]

[tool.uv.sources]
ennam-kg-indexer = { workspace = true }
```

(Keep everything else — `anthropic`, `fastapi`, `redis`, `sentence-transformers`, `pymssql`, `pypdf`, `pydantic-settings`, `cryptography`, `numpy`, `asyncpg`, `python-docx`, `openpyxl`, `pydantic`, `[project.scripts]`, ruff/pytest config — unchanged.)

- [ ] **Step 9: Regenerate the lockfile**

```bash
cd $PY
uv lock
```
Expected: `uv.lock` updates to a workspace-aware lock with both members. No resolution error.

- [ ] **Step 10: Sync and run the INDEXER package tests in isolation**

```bash
cd $PY
uv sync
uv run pytest packages/ennam-kg-indexer/tests -q
```
Expected: all moved indexer tests pass under the new `ennam_kg_indexer` namespace.

- [ ] **Step 11: Run the FULL suite (service + indexer)**

```bash
cd $PY
uv run pytest -q
```
Expected: full suite green — service imports resolve `ennam_kg_indexer.*`, no `ModuleNotFoundError`, no behavior regression.

- [ ] **Step 12: Verify the service no longer hosts the moved modules**

Run: `cd $PY && ls src/ennam_kg/parsers src/ennam_kg/indexer src/ennam_kg/kg_client 2>&1`
Expected: "No such file or directory" for all three.

- [ ] **Step 13: Commit**

```bash
cd $PY
git add -A
git add ../scripts/backfill-section-embeddings.py
git commit -m "refactor: extract ennam-kg-indexer package (parsers, indexer, kg_client) via uv workspace"
```

---

### Task 5: Update the Dockerfile for the workspace layout

The builder must copy `packages/` (the new indexer member) in addition to `src/` before `uv sync --frozen`, and the runtime stage must copy `packages/` too.

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1: Edit the builder stage**

In `$PY/Dockerfile`, the builder currently has:
```dockerfile
COPY pyproject.toml uv.lock* ./
COPY src/ src/
RUN uv sync --frozen --no-dev
```
Change to (add `COPY packages/` BEFORE the sync):
```dockerfile
COPY pyproject.toml uv.lock* ./
COPY packages/ packages/
COPY src/ src/
RUN uv sync --frozen --no-dev
```

- [ ] **Step 2: Edit the runtime stage**

The runtime stage currently copies:
```dockerfile
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
```
Add the packages copy:
```dockerfile
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/packages /app/packages
```
Leave `ENV PYTHONPATH="/app/src"`, `CMD ["uvicorn", "ennam_kg.main:app", ...]` unchanged.

- [ ] **Step 3: Build the image**

```bash
cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace
docker compose build indexer
```
Expected: build succeeds through `uv sync --frozen --no-dev` (proves the regenerated lock matches the workspace pyproject).

- [ ] **Step 4: Verify both namespaces import inside the image**

```bash
docker compose run --rm --no-deps indexer python -c "import ennam_kg.main; import ennam_kg_indexer; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 5: Commit**

```bash
cd $PY
git add Dockerfile
git commit -m "build: update Dockerfile for ennam-kg-indexer workspace member"
```

---

### Task 6: Final clean-room verification (no behavior regression, lightweight install proven)

**Files:** none (verification only).

- [ ] **Step 1: Prove the indexer installs WITHOUT the heavy deps**

```bash
cd /tmp && rm -rf _idx_check && python3.12 -m venv _idx_check && . _idx_check/bin/activate
pip install "$PY/packages/ennam-kg-indexer"
python -c "from ennam_kg_indexer import IndexingEngine, IndexResult, KGClient; print('import ok')"
python -c "import anthropic" 2>&1 | grep -q "No module named" && echo "anthropic absent: OK"
python -c "import fastapi" 2>&1 | grep -q "No module named" && echo "fastapi absent: OK"
python -c "import pydantic_settings" 2>&1 | grep -q "No module named" && echo "pydantic_settings absent: OK"
deactivate && rm -rf /tmp/_idx_check
```
Expected: `import ok`, and all three "absent: OK" lines print (the heavy deps did not leak into the core package).

- [ ] **Step 2: Confirm no old import paths remain anywhere**

```bash
cd $PY
grep -rn "from ennam_kg.kg_client\|from ennam_kg.indexer\|from ennam_kg.parsers\|ennam_kg\.kg_client\|ennam_kg\.indexer\|ennam_kg\.parsers" src/ ../scripts/ tests/ packages/ennam-kg-indexer
```
Expected: no output (covers service code, root script, remaining service tests, and the whole moved package).

- [ ] **Step 3: Bring up the dev stack and smoke-test indexing end-to-end**

```bash
cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace
docker compose up -d --build indexer worker
docker compose ps   # indexer + worker healthy
# trigger a real index against a mounted repo and confirm it still produces nodes
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:8081/index/batch \
  -H "Content-Type: application/json" \
  -d '{"project_id":"smoke","repo_paths":["/repos/ennam-kg-go"]}'
```
Expected: HTTP `200` (or `202`), `docker compose logs indexer` shows a scan running, no import errors.

- [ ] **Step 4: Smoke-test the relocated embed path (agentic semantic search)**

Confirm the `embed_texts` relocation works against the live embeddings endpoint:
```bash
curl -s -X POST http://localhost:8081/api/v1/embeddings \
  -H "Content-Type: application/json" -H "Authorization: Bearer ennam_kg_dev_000000000000000000000000" \
  -d '{"texts":["hello world"]}' | head -c 200
```
Expected: a JSON body containing an `embeddings` array (the same endpoint the agentic helper now calls).

- [ ] **Step 5: Final commit (if any verification tweaks were needed)**

If steps 1-4 required no changes, nothing to commit. Otherwise commit the fixes:
```bash
cd $PY
git add -A && git commit -m "fix: address indexer-split verification findings"
```

---

## Self-Review

### Spec coverage

| Spec requirement (Required Code Changes) | Task |
|------------------------------------------|------|
| 1. Decouple `embed_texts` from config | Task 1 |
| 2. Drop `config`/`Settings` + both callers | Task 2 |
| 3. Move three directories | Task 4 (Step 2) |
| 4. Rewrite imports inside moved modules | Task 4 (Step 3, plus Step 7 package pass for moved tests) |
| 5. Rewrite ALL ~15 service imports | Task 4 (Step 7, over `src/`) |
| 6. Update worker.py + api/indexing.py indexer imports | Task 4 (Step 7 sed covers them) |
| 7. Remove dead summarizer wiring | Task 3 |
| 8. Rewrite root script consumer | Task 4 (Step 7 includes `../scripts/`) |
| 8b. Rewrite remaining SERVICE tests that import moved modules (test_worker, test_token_propagation, test_streaming/test_engine, test_api_indexing, test_agentic/test_tools) | Task 4 (Step 7 includes `tests/`) |
| 9. Set up uv workspace | Task 4 (Steps 5, 8) |
| 10. Regenerate uv.lock | Task 4 (Step 9) |
| 11. Rewrite Dockerfile | Task 5 |
| 12. Move tests (incl. `tests/kg_client/` + `tests/test_kg_client/`) | Task 4 (Step 6) |
| Verification: clean-room install, no old paths (src+scripts+tests+package), no regression | Task 6 |

### Placeholder scan

No TBD/TODO. Every code/sed/command step shows concrete content.

### Type consistency

- `IndexingEngine(kg_client)` (one arg) used consistently in Task 2 across engine def, both callers, and tests.
- `embed_texts(texts, *, base_url, api_key)` signature defined in Task 1 Step 3 matches the call site in Step 5 and the test in Step 1.
- Public API `IndexingEngine, IndexResult, KGClient` exported in Task 4 Step 4 matches the clean-room import check in Task 6 Step 1.
- Namespace `ennam_kg_indexer.{parsers,indexer,kg_client}` consistent across Steps 3, 6, 7 and the package `__init__`.

### Ordering note

Tasks 1-3 are each independently green and in-place. Task 4 is the only task with red intermediate steps (a directory move cannot be partially valid); it ends green at Step 11 before its single commit. Tasks 5-6 are green throughout.
