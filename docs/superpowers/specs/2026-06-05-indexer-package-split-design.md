# `ennam-kg-indexer` Package Split — Design Spec

**Date**: 2026-06-05
**Status**: Approved (design)
**Goal**: Extract the code-indexing core (AST parsing → extract → diff → push) into a standalone, lightweight, publishable Python package `ennam-kg-indexer`, separated from the heavy `ennam-kg` service. This unlocks third-party integration (LAAM and others) where a host system indexes its own source locally and pushes only the resulting knowledge nodes to a remote Ennam KG API.

---

## Context

Today `ennam.kg.python` is a single monolithic package. Its `pyproject.toml` pulls `fastapi`, `redis`, `sentence-transformers` (~500MB), `pymssql`, `pypdf`, `anthropic`, etc. Any external system wanting only the code-indexing capability would have to install all of it.

Investigation of the current indexing flow found:

- The indexing pipeline (`parsers/` + `indexer/`) depends only on `tree-sitter`, `pathspec`, plus `kg_client` for pushing.
- The `summarizer/` module (Anthropic) is **dead code** in the index path — `worker.py` constructs a `ClaudeSummarizer` but never passes it to the engine and never calls it.
- `engine.py` stores `self.config = config` but never reads it, yet imports `from ennam_kg.config import Settings` purely for the type annotation. Both the param and the import must be removed, otherwise the indexer package still drags in `config.py` → `pydantic-settings`.
- All 9 AI-using features (NL query, streaming, ingestion, KG generation, benchmark, agentic) live in the service layer, never in the indexer.

**Two hidden couplings that the naive "just move 3 dirs" view misses (found during review):**

1. **`KGClient.embed_texts()` imports service config.** [`kg_client/client.py:184-185`](../../ennam.kg.python/src/ennam_kg/kg_client/client.py#L184) does `from ennam_kg.config import settings` to read `settings.embedding_service_url`. This method is an **embeddings (service) concern, never used by the indexer**. If `kg_client` moves as-is, it pulls `config.py` → `pydantic-settings` into the "lightweight" package. `embed_texts` must be removed from the core `KGClient`.
2. **`IndexingEngine` has two callers, not one.** Both [`worker.py:44`](../../ennam.kg.python/src/ennam_kg/worker.py#L44) and [`api/indexing.py:36`](../../ennam.kg.python/src/ennam_kg/api/indexing.py#L36) call `IndexingEngine(kg_client, settings)`. Dropping the `config` param breaks **both**.

Additionally, **`kg_client` is shared infrastructure** — it is the Go API HTTP client imported by ~15 service files (agentic, api, benchmark, ingestion, kg_generator, nl_query, streaming, worker), and `kg_client.models` (`FlatResponse`, `KnowledgeNode`, `Edge`) is used by `agentic/tools.py`. Moving it into the indexer package is functionally required (an external host needs it to push nodes) and the dependency stays one-way (service → indexer), but it means the indexer package becomes a dependency of nearly the whole service, and **every one of those ~15 imports must be rewritten**.

So the core indexer is genuinely standalone and AI-free **once `embed_texts` and the `Settings` coupling are removed**.

---

## Scope

- **In scope**: split into two packages within the existing `ennam.kg.python` repo (uv workspace / monorepo — "Mức 2"); core package contains parsing + extraction + diff + KG push client; drop the dead `summarizer` from the indexer entirely (option A).
- **Out of scope**: separate git repo (Mức 3); PyPI publishing automation; the MCP `kg_index_source` tool (depends on this, separate spec); CLI binary packaging for non-Python hosts (separate spec); any behavior change to indexing logic.

---

## Decisions (confirmed)

| Decision                        | Choice                                                |
| ------------------------------- | ----------------------------------------------------- |
| Split level                     | **Mức 2** — monorepo, 2 packages, uv workspace        |
| AI summarization in indexer     | **Drop entirely** (option A — it is dead code; YAGNI) |
| `Settings` dependency in engine | Remove unused `config` param from `IndexingEngine`    |
| Repo location                   | Stay in `ennam.kg.python` (no new repo)               |

---

## Target Structure

```
ennam.kg.python/
├── pyproject.toml                  # uv workspace root
├── packages/
│   ├── ennam-kg-indexer/           # NEW core package (lightweight, publishable)
│   │   ├── pyproject.toml
│   │   └── src/ennam_kg_indexer/
│   │       ├── __init__.py         # public API: IndexingEngine, IndexResult, KGClient
│   │       ├── parsers/            # MOVED from ennam_kg/parsers/
│   │       │   ├── base.py         (Symbol, SymbolKind, BaseParser)
│   │       │   ├── typescript.py
│   │       │   ├── python_lang.py
│   │       │   ├── dart.py
│   │       │   └── __init__.py     (get_parser registry)
│   │       ├── indexer/            # MOVED from ennam_kg/indexer/
│   │       │   ├── scanner.py      (discover_files, filter_changed)
│   │       │   ├── extractor.py    (NodeExtractor)
│   │       │   ├── differ.py       (IndexDiffer)
│   │       │   └── engine.py       (IndexingEngine, IndexResult)
│   │       └── kg_client/          # MOVED from ennam_kg/kg_client/
│   │           ├── client.py       (KGClient — httpx push)
│   │           └── models.py
│   └── ennam-kg/                   # service package (everything else)
│       ├── pyproject.toml          # depends on ennam-kg-indexer
│       └── src/ennam_kg/
│           ├── worker.py           # imports from ennam_kg_indexer
│           ├── main.py, api/
│           ├── queue/, ingestion/, nl_query/, streaming/,
│           ├── kg_generator/, benchmark/, agentic/, embeddings/,
│           ├── ai_client/, db_client/, summarizer/, config.py, crypto.py
```

### What moves to `ennam-kg-indexer`

| Module       | From                  | Notes                                          |
| ------------ | --------------------- | ---------------------------------------------- |
| `parsers/`   | `ennam_kg/parsers/`   | tree-sitter; no changes                        |
| `indexer/`   | `ennam_kg/indexer/`   | drop unused `config` param from engine         |
| `kg_client/` | `ennam_kg/kg_client/` | httpx push client; the only network dependency |

### What stays in `ennam-kg` service

Everything else: `worker.py`, `main.py`, `api/`, `queue/`, `ingestion/`, `nl_query/`, `streaming/`, `kg_generator/`, `benchmark/`, `agentic/`, `embeddings/`, `ai_client/`, `db_client/`, `summarizer/`, `config.py`, `crypto.py`.

> Note: `summarizer/` stays in the service (not deleted), but is no longer referenced by the index path. Cleaning up the dead `ClaudeSummarizer` instantiation in `worker.py` is part of this work.

---

## Package Dependencies

### `ennam-kg-indexer/pyproject.toml`

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
```

No `anthropic`, `fastapi`, `redis`, `sentence-transformers`, `pymssql`, `pypdf`, `uvicorn`, `pydantic-settings`.

### `ennam-kg/pyproject.toml` (service)

```toml
[project]
dependencies = [
    "ennam-kg-indexer",   # workspace dependency
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "pydantic-settings>=2.7",
    "redis>=5.2",
    "anthropic>=0.49",
    "sentence-transformers>=3.0",
    "numpy>=1.26",
    "asyncpg>=0.30",
    "pymssql>=2.3",
    "cryptography>=44",
    "pypdf>=5.0",
    "python-docx>=1.1",
    "openpyxl>=3.1",
    # httpx, pydantic come transitively via ennam-kg-indexer
]

[tool.uv.sources]
ennam-kg-indexer = { workspace = true }
```

### Workspace root `pyproject.toml`

```toml
[tool.uv.workspace]
members = ["packages/ennam-kg-indexer", "packages/ennam-kg"]
```

---

## Public API of `ennam-kg-indexer`

`src/ennam_kg_indexer/__init__.py` exports the minimal surface a host needs:

```python
from ennam_kg_indexer.indexer.engine import IndexingEngine, IndexResult
from ennam_kg_indexer.kg_client.client import KGClient

__all__ = ["IndexingEngine", "IndexResult", "KGClient"]
```

Host usage (e.g. LAAM, if Python):

```python
from ennam_kg_indexer import IndexingEngine, KGClient

client = KGClient(base_url="https://kg.server.com", api_key="...")
engine = IndexingEngine(client)             # NOTE: no Settings param anymore
result = await engine.full_scan(project_id, "/path/to/repo")
```

---

## Required Code Changes

1. **Decouple `KGClient.embed_texts` from service config (PREREQUISITE — do first).** `embed_texts` is an embeddings/service concern that the indexer never calls, and it is the only thing in `kg_client` importing `ennam_kg.config`. Remove `embed_texts` from the core `KGClient` and relocate the capability to the service layer:
   - Delete the `embed_texts` method (and its `from ennam_kg.config import settings` line) from `kg_client/client.py`.
   - There is exactly **one** real caller: [`agentic/tools.py:696`](../../ennam.kg.python/src/ennam_kg/agentic/tools.py#L696) `vectors = await self._kg.embed_texts([query])`. (Note: `ingestion/pipeline/decompose.py` has a local variable also named `embed_texts` but calls `LocalEmbeddingModel` directly — it is NOT a caller of this method.) Replace the `agentic/tools.py` call with a service-side helper that POSTs to `settings.embedding_service_url + /api/v1/embeddings` (the same endpoint `embed_texts` was hitting, served by `api/embeddings.py`). The KG core must not know about embeddings.
   - Verify: `grep -rn "ennam_kg.config\|embedding_service_url" packages/ennam-kg-indexer/src/` returns nothing after this step.

2. **Drop unused `config`/`Settings` from `IndexingEngine`.** In `indexer/engine.py`:
   - Remove the import `from ennam_kg.config import Settings` (line 9).
   - Change `def __init__(self, kg_client: KGClient, config: Settings)` → `def __init__(self, kg_client: KGClient)`, and delete `self.config = config`.
   - Update **BOTH** callers (not one): `worker.py:44` `IndexingEngine(kg_client, settings)` → `IndexingEngine(kg_client)`, and `api/indexing.py:36` `IndexingEngine(kg_client, settings)` → `IndexingEngine(kg_client)`.

3. **Move three directories** (`parsers/`, `indexer/`, `kg_client/`) into `packages/ennam-kg-indexer/src/ennam_kg_indexer/`.

4. **Rewrite imports inside the moved modules** (internal cross-refs): `from ennam_kg.parsers...` → `from ennam_kg_indexer.parsers...`, same for `indexer` and `kg_client`. Specifically includes `indexer/differ.py:8`, `indexer/engine.py:13-15`, `indexer/extractor.py:5`, `indexer/scanner.py:10`, and `kg_client/client.py:7`.

5. **Rewrite ALL service-side imports of the moved modules** (~15 files — this is the bulk of the mechanical work, NOT just "moved modules"). Every `from ennam_kg.kg_client...` / `from ennam_kg.indexer...` / `from ennam_kg.parsers...` in the service becomes `from ennam_kg_indexer...`. Known files importing `kg_client`:
   `agentic/engine.py`, `agentic/tools.py`, `api/agentic.py`, `api/indexing.py`, `api/streaming.py`, `benchmark/engine.py`, `benchmark/runner.py`, `ingestion/pipeline/cross_edges.py`, `ingestion/pipeline/decompose.py`, `ingestion/pipeline/engine.py`, `ingestion/pipeline/intra_edges.py`, `kg_generator/engine.py`, `nl_query/engine.py`, `streaming/engine.py`, `worker.py`.
   Plus `api/indexing.py` and `worker.py` for `indexer`.

6. **Update `worker.py` + `api/indexing.py` indexer imports**: `from ennam_kg.indexer.engine import IndexingEngine, IndexResult` → `from ennam_kg_indexer import IndexingEngine, IndexResult`.

7. **Remove dead summarizer wiring** in `worker.py` (the `ClaudeSummarizer` instantiation at lines 37-43 that is never used) — and the now-orphaned `cache.save()` at line ~218 if the cache serves nothing else. (The `summarizer/` module itself stays in the service package, just unreferenced.)

8. **Rewrite the workspace-root script consumer.** [`scripts/backfill-section-embeddings.py:18`](../../scripts/backfill-section-embeddings.py#L18) (at the **workspace root**, outside both packages) imports `from ennam_kg.kg_client.client import KGClient` — change to `from ennam_kg_indexer.kg_client.client import KGClient`. Note this script also imports `ennam_kg.config`, `ennam_kg.embeddings`, `ennam_kg.ingestion` (service modules, stay as-is), so it requires BOTH packages installed to run. (No other file outside `ennam.kg.python/` imports the moved modules — verified.)

9. **Set up uv workspace** — root `pyproject.toml` with `[tool.uv.workspace] members = [...]`; move service deps into `packages/ennam-kg/pyproject.toml`; create `packages/ennam-kg-indexer/pyproject.toml`.

10. **Regenerate `uv.lock`.** The existing `ennam.kg.python/uv.lock` (~378KB) is single-package and will break `uv sync --frozen` in the Dockerfile after restructuring. Run `uv lock` at the workspace root to produce a workspace-aware lock, and commit it. Without this, the Docker build fails on the frozen step.

11. **Rewrite the Dockerfile** for the new workspace layout (see Docker section below).

12. **Move tests**: `test_parsers/`, `test_engine.py`, `test_differ.py`, `test_extractor.py`, `test_kg_client/`, `test_kg_client.py`, `test_kg_client_phase2.py` → indexer package tests. Update any test that constructs `IndexingEngine(..., settings)` to drop the second arg. Any service test importing `kg_client` gets its import rewritten to `ennam_kg_indexer`. The rest stay with the service.

---

## Docker Rewrite

The current [`Dockerfile`](../../ennam.kg.python/Dockerfile) is single-package: multi-stage, `COPY src/ src/`, `uv sync --frozen --no-dev`, `PYTHONPATH=/app/src`, `CMD uvicorn ennam_kg.main:app`. `docker-compose.yml` runs **two** services from this image — `indexer` (`uvicorn ennam_kg.main:app`) and `worker` (`python -m ennam_kg.worker`).

After the split, the build context still installs the **service** package (which pulls the indexer via the workspace), so both runtime commands are unchanged. Concrete changes:

```dockerfile
# builder stage
COPY pyproject.toml uv.lock* ./
COPY packages/ packages/          # was: COPY src/ src/
RUN uv sync --frozen --no-dev     # resolves the whole workspace

# runtime stage
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/packages /app/packages
# Package is installed into the venv (editable/wheel) — drop PYTHONPATH=/app/src.
# If PYTHONPATH is kept, point it at both: /app/packages/ennam-kg/src:/app/packages/ennam-kg-indexer/src
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "ennam_kg.main:app", "--host", "0.0.0.0", "--port", "8081"]  # unchanged
```

The `worker` service's `command: ["python", "-m", "ennam_kg.worker"]` in `docker-compose.yml` is unchanged. Verify both `import ennam_kg.main` and `import ennam_kg_indexer` resolve inside the built image.

---

## Verification

- `cd packages/ennam-kg-indexer && uv sync && uv run pytest` — indexer tests pass with ONLY the lightweight deps installed (proves no hidden heavy dependency).
- In a clean venv: `pip install ./packages/ennam-kg-indexer` then `python -c "from ennam_kg_indexer import IndexingEngine, KGClient"` succeeds — and `python -c "import anthropic"` / `import fastapi` / `import pydantic_settings` all **fail** (proves the heavy deps did not leak in).
- `grep -rn "ennam_kg\." packages/ennam-kg-indexer/src/` returns nothing — the indexer package must NOT reference the `ennam_kg` service namespace at all (catches the `config`, `Settings`, and `embed_texts` couplings if any slipped through).
- `cd ennam.kg.python && uv sync && uv run pytest` — full service test suite still green (worker, api, ingestion, etc.).
- `grep -rn "from ennam_kg.kg_client\|from ennam_kg.indexer\|from ennam_kg.parsers\|ennam_kg\.kg_client\|ennam_kg\.indexer\|ennam_kg\.parsers" packages/ennam-kg/src scripts/` returns nothing — every consumer of the moved modules (the ~15 service files **and** the workspace-root `scripts/backfill-section-embeddings.py`) was rewritten to `ennam_kg_indexer`; the OLD path must be fully gone everywhere, not just inside the service package.
- `cd ennam.kg.python && uv sync --frozen` succeeds — proves the regenerated `uv.lock` matches the new workspace `pyproject.toml` (this is exactly what the Docker build runs).
- Docker `indexer` + `worker` images build and run healthy; a live `POST /index` against the dev stack still produces nodes (no behavior regression); the agentic `embed_texts` replacement still returns vectors (the one relocated caller works).

---

## Risks

| Risk | Mitigation |
| ---- | ---------- |
| **`kg_client.embed_texts` drags `config.py` into the core** (the central-claim killer) | Step 1 removes `embed_texts` from the core `KGClient` before the move; relocate the single caller (`agentic/tools.py:696`) to a service-side helper. Verified by `grep "ennam_kg\." packages/ennam-kg-indexer/src/` = empty. |
| **`engine.py` keeps `from ennam_kg.config import Settings`** | Step 2 removes the import AND the param together. Same grep catches a leftover. |
| **Second `IndexingEngine` caller (`api/indexing.py`) breaks** when param dropped | Step 2 explicitly updates BOTH callers (`worker.py:44`, `api/indexing.py:36`). |
| Import cycles between service and indexer | Indexer must NOT import anything from `ennam_kg` service. One-way only. The empty-grep verification enforces it. |
| **~15 service files import `kg_client`** — undercounting the rewrite | Step 5 lists all known files; verification greps the OLD path to zero across `packages/ennam-kg/src`. |
| Docker layout change (2 services use the image) | Dockerfile rewrite section gives concrete `COPY packages/` + venv-install steps; both `uvicorn ennam_kg.main:app` and `python -m ennam_kg.worker` commands stay unchanged. |
| Test fixtures referencing old import paths or `IndexingEngine(..., settings)` | Step 10 moves + rewrites test imports and drops the second constructor arg in the same change; run full suite. |

---

## Downstream (separate specs, depend on this)

- **MCP `kg_index_source` tool** — Go `kg-bridge` shells out to a local `ennam-kg-indexer` CLI so an agent can trigger a local index and push to remote KG.
- **CLI / Docker sidecar packaging** — wrap `ennam-kg-indexer` as a `ennam-kg index ...` CLI and a Docker image for non-Python hosts.
- **GitHub integration** (`2026-06-04-github-integration-design.md`) — independent; the server-side clone path is unaffected by this split.
