# `ennam-kg-indexer` Package Split — Design Spec

**Date**: 2026-06-05
**Status**: Approved (design)
**Goal**: Extract the code-indexing core (AST parsing → extract → diff → push) into a standalone, lightweight, publishable Python package `ennam-kg-indexer`, separated from the heavy `ennam-kg` service. This unlocks third-party integration (LAAM and others) where a host system indexes its own source locally and pushes only the resulting knowledge nodes to a remote Ennam KG API.

---

## Context

Today `ennam.kg.python` is a single monolithic package. Its `pyproject.toml` pulls `fastapi`, `redis`, `sentence-transformers` (~500MB), `pymssql`, `pypdf`, `anthropic`, etc. Any external system wanting only the code-indexing capability would have to install all of it.

Investigation of the current indexing flow found:

- `IndexingEngine` only depends on `tree-sitter`, `pathspec`, `httpx`, `pydantic`.
- The `summarizer/` module (Anthropic) is **dead code** in the index path — `worker.py` constructs a `ClaudeSummarizer` but never passes it to the engine and never calls it.
- `engine.py` stores `self.config = config` but never reads it — `Settings` is not actually needed by the indexer.
- All 9 AI-using features (NL query, streaming, ingestion, KG generation, benchmark, agentic) live in the service layer, never in the indexer.

So the core indexer is genuinely standalone and AI-free.

---

## Scope

- **In scope**: split into two packages within the existing `ennam.kg.python` repo (uv workspace / monorepo — "Mức 2"); core package contains parsing + extraction + diff + KG push client; drop the dead `summarizer` from the indexer entirely (option A).
- **Out of scope**: separate git repo (Mức 3); PyPI publishing automation; the MCP `kg_index_source` tool (depends on this, separate spec); CLI binary packaging for non-Python hosts (separate spec); any behavior change to indexing logic.

---

## Decisions (confirmed)

| Decision | Choice |
|----------|--------|
| Split level | **Mức 2** — monorepo, 2 packages, uv workspace |
| AI summarization in indexer | **Drop entirely** (option A — it is dead code; YAGNI) |
| `Settings` dependency in engine | Remove unused `config` param from `IndexingEngine` |
| Repo location | Stay in `ennam.kg.python` (no new repo) |

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

| Module | From | Notes |
|--------|------|-------|
| `parsers/` | `ennam_kg/parsers/` | tree-sitter; no changes |
| `indexer/` | `ennam_kg/indexer/` | drop unused `config` param from engine |
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

1. **Move three directories** (`parsers/`, `indexer/`, `kg_client/`) into `packages/ennam-kg-indexer/src/ennam_kg_indexer/`.
2. **Rewrite imports** inside moved modules: `from ennam_kg.parsers...` → `from ennam_kg_indexer.parsers...` (and `indexer`, `kg_client`).
3. **Drop unused `config` param** from `IndexingEngine.__init__` — change `def __init__(self, kg_client, config)` to `def __init__(self, kg_client)`. Update the one caller in `worker.py`.
4. **Update `worker.py` imports**: `from ennam_kg.indexer.engine import IndexingEngine` → `from ennam_kg_indexer import IndexingEngine`; same for `KGClient`.
5. **Remove dead summarizer wiring** in `worker.py` (the `ClaudeSummarizer` instantiation that is never used) — and the now-orphaned `cache.save()` if the cache serves nothing else.
6. **Set up uv workspace** — root `pyproject.toml` with workspace members; move service deps into `packages/ennam-kg/pyproject.toml`.
7. **Move tests**: parser/indexer/kg_client tests → indexer package; the rest stay with the service.

---

## Verification

- `cd packages/ennam-kg-indexer && uv sync && uv run pytest` — indexer tests pass with ONLY the lightweight deps installed (proves no hidden heavy dependency).
- `pip install ./packages/ennam-kg-indexer` in a clean venv → import `IndexingEngine` succeeds without `anthropic`/`fastapi`/`redis` present.
- `cd ennam.kg.python && uv sync && uv run pytest` — full service test suite still green (worker, api, ingestion, etc.).
- Docker `worker` and `indexer` images build and run; a live `POST /index` against the dev stack still produces nodes (no behavior regression).
- `grep -r "ennam_kg.parsers\|ennam_kg.indexer\|ennam_kg.kg_client" packages/ennam-kg/src` returns nothing (all rewritten to `ennam_kg_indexer`).

---

## Risks

| Risk | Mitigation |
|------|------------|
| Import cycles between service and indexer | Indexer must NOT import anything from `ennam_kg` service. One-way dependency only. Verify with grep. |
| Hidden use of `Settings` in moved code | Already verified `engine` doesn't use it; scanner/extractor/differ don't import config. Re-verify after move. |
| Docker build paths change | Update Dockerfiles to install workspace correctly (`uv sync` at root, or install the service package which pulls the indexer). |
| Test fixtures referencing old import paths | Move + rewrite test imports in the same change; run full suite. |

---

## Downstream (separate specs, depend on this)

- **MCP `kg_index_source` tool** — Go `kg-bridge` shells out to a local `ennam-kg-indexer` CLI so an agent can trigger a local index and push to remote KG.
- **CLI / Docker sidecar packaging** — wrap `ennam-kg-indexer` as a `ennam-kg index ...` CLI and a Docker image for non-Python hosts.
- **GitHub integration** (`2026-06-04-github-integration-design.md`) — independent; the server-side clone path is unaffected by this split.
