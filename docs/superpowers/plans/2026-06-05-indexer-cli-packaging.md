# `ennam-kg-indexer` CLI + Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a thin CLI (`ennam-kg-index`) and Docker image around the `ennam-kg-indexer` package so any host can index local source and push to a remote KG, with re-index yielding the latest state (no accumulation), and without breaking existing features.

**Architecture:** First make the engine idempotent across checkouts — normalize `file_path` to repo-relative early in the pipeline and add a stable `repo_key` + mode-aware archive scope (repo for full, file for incremental). Then add the `cli.py` entry point, the Docker image, and verification. The CLI is a thin shell over the existing `IndexingEngine`.

**Tech Stack:** Python 3.12, uv workspace, tree-sitter, httpx, pydantic, pytest + pytest-asyncio + pytest-httpx, Docker.

**Reference spec:** `docs/superpowers/specs/2026-06-05-indexer-cli-packaging-design.md`

**Working dir for all commands:** `/Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace/ennam.kg.python` (referred to as `$PY`). Indexer package root: `$PY/packages/ennam-kg-indexer` (referred to as `$IDX`). Run pytest from `$PY` so the workspace dev deps (pytest-asyncio, pytest-httpx) are available.

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `$IDX/src/ennam_kg_indexer/indexer/extractor.py` | `symbol_to_node` stores `repo_key`; file_path is now relative (normalized upstream) |
| Modify | `$IDX/src/ennam_kg_indexer/indexer/engine.py` | early relative-path normalization, resolve root, `repo_key` + `archive_scope` threading, incremental changed-files join |
| Modify | `$IDX/src/ennam_kg_indexer/indexer/differ.py` | `diff(..., archive_scope, repo_key)` — repo-scope vs file-scope, code-only |
| Create | `$IDX/src/ennam_kg_indexer/cli.py` | argparse CLI, env/flag resolution, pre-flight check, JSON summary |
| Modify | `$IDX/pyproject.toml` | `[project.scripts] ennam-kg-index` |
| Create | `$IDX/Dockerfile` | lightweight image, ENTRYPOINT ennam-kg-index |
| Modify | `$IDX/README.md` | usage docs |
| Modify | `$IDX/tests/test_extractor.py` | update **all 4** `symbol_to_node` calls for the new signature |
| Create | `$IDX/tests/test_engine_relative_paths.py` | edge regression + path stability + full replace integration |
| Modify | `$IDX/tests/test_differ.py` | repo-scope + file-scope + human-node safety; **fix existing `_make_existing_node` fixture (add `created_by`)** |
| Modify | `$IDX/tests/test_engine.py` | **add `created_by` to the reconstructed existing nodes in `test_incremental_with_existing_nodes`** |
| Create | `$IDX/tests/test_cli.py` | arg parsing, exit codes, env precedence |

Existing service callers (`src/ennam_kg/worker.py`, `src/ennam_kg/api/indexing.py`) need **no change** — `repo_key` is optional and defaults to `repo_path`, preserving today's behavior.

---

### Task 1: Engine — repo-relative `file_path` + `repo_key` (idempotent across checkouts)

Normalize each symbol's `file_path` to repo-relative early in `_process_files` (so payload keys AND edge keys agree), thread a stable `repo_key`, resolve the physical root once, and join incremental changed-files to that root. Archive-scope wiring comes in Task 2; here `_process_files` accepts the param and passes it through.

**Files:**
- Modify: `$IDX/src/ennam_kg_indexer/indexer/extractor.py`
- Modify: `$IDX/src/ennam_kg_indexer/indexer/engine.py`
- Modify: `$IDX/tests/test_extractor.py`
- Create: `$IDX/tests/test_engine_relative_paths.py`

- [ ] **Step 1: Update the extractor signature + tests (write test first)**

Edit `$IDX/tests/test_extractor.py` — there are **4** positional calls `symbol_to_node(symbol, "proj-1", "/repo")` (currently at lines ~78, ~97, ~108, ~116). Change **every one** to the new keyword form `symbol_to_node(symbol, "proj-1", repo_key="...")`, and assert `repo_path` holds the key. The new expectation:

```python
# A symbol whose file_path is already repo-relative (engine normalizes before calling)
node = extractor.symbol_to_node(symbol, "proj-1", repo_key="github.com/exnodes/foo")
assert node["properties"]["file_path"] == symbol.file_path   # passthrough (relative)
assert node["properties"]["repo_path"] == "github.com/exnodes/foo"
```

- [ ] **Step 2: Run extractor tests — expect FAIL**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_extractor.py -v`
Expected: FAIL — `symbol_to_node()` got an unexpected keyword `repo_key` / missing positional `repo_path`.

- [ ] **Step 3: Change `symbol_to_node` signature**

In `extractor.py`, change the method signature and the two property lines:

```python
def symbol_to_node(self, symbol: Symbol, project_id: str, *, repo_key: str) -> dict[str, object]:
```
and in the returned `properties` dict:
```python
        "file_path": symbol.file_path,   # already repo-relative (engine normalizes upstream)
        ...
        "repo_path": repo_key,           # stable logical repo identity
```
(Leave everything else in the payload unchanged.)

- [ ] **Step 4: Run extractor tests — expect PASS**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_extractor.py -v`
Expected: PASS.

- [ ] **Step 5: Write the engine relative-path test (edge regression + stability)**

Create `$IDX/tests/test_engine_relative_paths.py`:

```python
"""Engine: repo-relative file_path normalization, edge integrity, path stability."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest

from ennam_kg_indexer.indexer.engine import IndexingEngine


def _mock_client() -> AsyncMock:
    c = AsyncMock()
    c.get_nodes.return_value = []          # nothing indexed yet
    c.create_node.return_value = {"id": "n-1"}
    c.update_node.return_value = {"id": "n-1"}
    c.create_edge.return_value = {"id": "e-1"}
    return c


@pytest.fixture()
def py_repo(tmp_path):
    """A tiny Python repo: one module with a class containing a method."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        "class Foo:\n    def bar(self):\n        return 1\n"
    )
    return tmp_path


@pytest.mark.asyncio
async def test_file_path_is_repo_relative(py_repo):
    client = _mock_client()
    engine = IndexingEngine(client)
    await engine.full_scan("proj-1", str(py_repo))
    # Every created node payload must carry a repo-relative file_path (no leading slash / tmp dir)
    created = [call.args[0] for call in client.create_node.call_args_list]
    assert created, "expected nodes to be created"
    for payload in created:
        fp = payload["properties"]["file_path"]
        assert not os.path.isabs(fp), f"file_path must be relative, got {fp}"
        assert fp.startswith("pkg/"), f"expected repo-relative path, got {fp}"


@pytest.mark.asyncio
async def test_containment_edge_created(py_repo):
    """Regression guard: relativizing must not break edge keys (node_id_map vs extract_edges)."""
    client = _mock_client()
    engine = IndexingEngine(client)
    result = await engine.full_scan("proj-1", str(py_repo))
    assert result.edges_created >= 1, "class->method containment edge must be created"


@pytest.mark.asyncio
async def test_keys_stable_across_physical_roots(tmp_path):
    """Same repo content under two different physical roots → identical natural keys."""
    keys_seen = []
    for sub in ("checkout-a", "checkout-b"):
        root = tmp_path / sub / "pkg"
        root.mkdir(parents=True)
        (root / "mod.py").write_text("def hello():\n    return 1\n")
        client = _mock_client()
        engine = IndexingEngine(client)
        await engine.full_scan("proj-1", str(tmp_path / sub), repo_key="logical-key")
        payloads = [c.args[0] for c in client.create_node.call_args_list]
        keys = sorted(p["properties"]["file_path"] for p in payloads)
        keys_seen.append(keys)
    assert keys_seen[0] == keys_seen[1] == ["pkg/mod.py"]
```

- [ ] **Step 6: Run engine test — expect FAIL**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_engine_relative_paths.py -v`
Expected: FAIL — engine still stores absolute paths / `full_scan` has no `repo_key` kwarg.

- [ ] **Step 7: Update the engine**

In `engine.py`, add `import os` at the top (alongside existing imports). Then:

Change `full_scan`:
```python
    async def full_scan(
        self, project_id: str, repo_path: str, *, repo_key: str | None = None
    ) -> IndexResult:
        """Full project scan: discover all files, parse, extract, diff, apply."""
        result = IndexResult()
        root = Path(repo_path).resolve()

        files = discover_files(root)
        logger.info("Discovered %d files in %s", len(files), root)

        await self._process_files(
            files, project_id, str(root), result,
            repo_key=repo_key or repo_path, archive_scope="repo",
        )
        ...
```

Change `incremental_scan`:
```python
    async def incremental_scan(
        self, project_id: str, repo_path: str, changed_files: list[str],
        *, repo_key: str | None = None,
    ) -> IndexResult:
        """Incremental scan: only process changed files."""
        result = IndexResult()
        root = Path(repo_path).resolve()

        # changed_files are repo-relative; join to root so the parser reads the right files.
        # (An already-absolute path makes `root / f` return that absolute path unchanged.)
        changed_paths = [root / f for f in changed_files]
        files = filter_changed(changed_paths)
        logger.info(
            "Incremental scan: %d supported files out of %d changed",
            len(files), len(changed_files),
        )

        await self._process_files(
            files, project_id, str(root), result,
            repo_key=repo_key or repo_path, archive_scope="file",
        )
        ...
```

Change `_process_files` — new keyword params, normalize in the parse loop, pass through to extractor + differ:
```python
    async def _process_files(
        self,
        files: list[Path],
        project_id: str,
        repo_root: str,            # resolved physical root (str)
        result: IndexResult,
        *,
        repo_key: str,
        archive_scope: str,
    ) -> None:
        """Shared pipeline: parse -> extract -> diff -> apply -> edges."""
        all_symbols: list[Symbol] = []
        all_payloads: list[dict[str, object]] = []
        file_paths: list[str] = []

        # 2. Parse each file; normalize file_path to repo-relative on every symbol
        for file_path in files:
            parser = get_parser(file_path)
            if parser is None:
                continue
            try:
                symbols = parser.parse(file_path)
                rel = os.path.relpath(str(file_path), repo_root)
                for s in symbols:
                    s.file_path = rel          # all symbols of a file share its relative path
                all_symbols.extend(symbols)
                result.files_scanned += 1
                result.symbols_found += len(symbols)
                file_paths.append(rel)         # relative; includes 0-symbol files
                logger.debug("Parsed %s: %d symbols", file_path, len(symbols))
            except Exception as exc:
                error_msg = f"Failed to parse {file_path}: {exc}"
                logger.warning(error_msg)
                result.errors.append(error_msg)

        # 3. Extract node payloads
        for symbol in all_symbols:
            payload = self.extractor.symbol_to_node(symbol, project_id, repo_key=repo_key)
            all_payloads.append(payload)

        # 4. Diff against existing KG state
        diff = await self.differ.diff(
            project_id, all_payloads, file_paths,
            archive_scope=archive_scope, repo_key=repo_key,
        )
        ...
```
(Everything after the diff call — the apply/create/update/archive/edges blocks — is unchanged.)

- [ ] **Step 8: Run engine + extractor tests — expect PASS**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_engine_relative_paths.py packages/ennam-kg-indexer/tests/test_extractor.py -v`
Expected: PASS. (The differ still uses its current default behavior; `diff` will be updated in Task 2 to accept the new kwargs — see next step's note.)

> **Note:** Step 7 passes `archive_scope` + `repo_key` to `differ.diff`, which does not yet accept them. To keep Task 1 self-contained and green, add a temporary tolerant signature to `differ.diff` now: `async def diff(self, project_id, new_symbols, file_paths, *, archive_scope: str = "file", repo_key: str = "")` and ignore the two new params for the moment (behavior unchanged). Task 2 implements the repo-scope logic. This one-line signature addition keeps every test green between tasks.

- [ ] **Step 9: Full indexer suite still green**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests -q`
Expected: all pass (existing differ/parser/kg_client tests unaffected).

- [ ] **Step 10: Commit**

```bash
cd $PY
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/extractor.py \
        packages/ennam-kg-indexer/src/ennam_kg_indexer/indexer/engine.py \
        packages/ennam-kg-indexer/src/ennam_kg_indexer/indexer/differ.py \
        packages/ennam-kg-indexer/tests/test_extractor.py \
        packages/ennam-kg-indexer/tests/test_engine_relative_paths.py
git commit -m "feat(indexer): repo-relative file_path + repo_key for checkout-stable keys"
```
> Path note: `extractor.py` lives at `.../ennam_kg_indexer/indexer/extractor.py` — adjust the `git add` path accordingly (`packages/ennam-kg-indexer/src/ennam_kg_indexer/indexer/extractor.py`).

---

### Task 2: Differ — mode-aware archive scope (repo vs file), code-only

Implement the repo-scoped archive (full scan replaces the whole repo) vs file-scoped (incremental), never touching human nodes.

**Files:**
- Modify: `$IDX/src/ennam_kg_indexer/indexer/differ.py`
- Modify: `$IDX/tests/test_differ.py`

- [ ] **Step 1: Write the differ tests (repo-scope, file-scope, human-node safety)**

> **REQUIRED first — fix the existing fixture, or Step 4 will leave old tests RED.** The new filter in Step 3 requires `created_by == "python-indexer"`. The existing helper `_make_existing_node` does NOT set it, so once Step 3 lands, every current differ test (`test_changed_hash_triggers_update`, `test_missing_symbol_triggers_archive`, `test_create_update_archive_together`) would archive/update nothing and fail. Edit `_make_existing_node` to add `created_by` at the top level (and a `repo_path` so it also satisfies repo-scope):
>
> ```python
> def _make_existing_node(
>     node_id: str = "existing-1",
>     name: str = "my_func",
>     kind: str = "function",
>     file_path: str = "src/app.py",
>     body_hash: str = "hash-aaa",
> ) -> dict[str, object]:
>     return {
>         "id": node_id,
>         "title": name,
>         "name": name,
>         "created_by": "python-indexer",   # NEW: required by the code-only filter
>         "properties": {
>             "file_path": file_path,
>             "kind": kind,
>             "body_hash": body_hash,
>             "repo_path": "/repo",          # NEW: default file-scope tests pass repo_key="/repo" (see Step 1 note below)
>         },
>     }
> ```
> The existing `differ.diff(...)` calls in those tests omit `repo_key`, so they run in default file-scope (`archive_scope="file"`), where `repo_path` is not consulted — adding it is harmless and future-proofs the fixture.

Add the new scope tests to `$IDX/tests/test_differ.py`:

```python
import pytest
from unittest.mock import AsyncMock
from ennam_kg_indexer.indexer.differ import IndexDiffer


def _payload(file_path, name, kind, body_hash="h1"):
    return {
        "title": f"{kind}: {name}",
        "properties": {"file_path": file_path, "kind": kind, "body_hash": body_hash,
                       "repo_path": "repoA"},
    }


def _existing(node_id, file_path, name, kind, *, created_by="python-indexer",
              repo_path="repoA", body_hash="h1"):
    return {"id": node_id, "title": f"{kind}: {name}", "created_by": created_by,
            "properties": {"file_path": file_path, "kind": kind, "body_hash": body_hash,
                           "repo_path": repo_path}}


@pytest.mark.asyncio
async def test_repo_scope_archives_deleted_file_node():
    client = AsyncMock()
    # existing: two code nodes in repoA; new scan only has one (other file deleted)
    client.get_nodes.return_value = [
        _existing("n1", "a.py", "f1", "function"),
        _existing("n2", "gone.py", "f2", "function"),
    ]
    differ = IndexDiffer(client)
    res = await differ.diff("proj", [_payload("a.py", "f1", "function")],
                            ["a.py"], archive_scope="repo", repo_key="repoA")
    assert "n2" in res.to_archive          # deleted-file node archived (repo scope)
    assert "n1" not in res.to_archive


@pytest.mark.asyncio
async def test_repo_scope_never_archives_human_nodes():
    client = AsyncMock()
    client.get_nodes.return_value = [
        _existing("h1", "", "Some Decision", "decision", created_by="alice", repo_path=""),
        _existing("n1", "gone.py", "f1", "function"),
    ]
    differ = IndexDiffer(client)
    res = await differ.diff("proj", [], [], archive_scope="repo", repo_key="repoA")
    assert "h1" not in res.to_archive      # human knowledge node untouched
    assert "n1" in res.to_archive


@pytest.mark.asyncio
async def test_repo_scope_ignores_other_repo():
    client = AsyncMock()
    client.get_nodes.return_value = [_existing("b1", "x.py", "f", "function", repo_path="repoB")]
    differ = IndexDiffer(client)
    res = await differ.diff("proj", [], [], archive_scope="repo", repo_key="repoA")
    assert "b1" not in res.to_archive      # different repo_key — not in scope


@pytest.mark.asyncio
async def test_file_scope_only_considers_scanned_files():
    client = AsyncMock()
    client.get_nodes.return_value = [
        _existing("n1", "a.py", "f1", "function"),
        _existing("n2", "b.py", "f2", "function"),
    ]
    differ = IndexDiffer(client)
    # incremental scan of only a.py, f1 removed; b.py must NOT be touched
    res = await differ.diff("proj", [], ["a.py"], archive_scope="file", repo_key="repoA")
    assert "n1" in res.to_archive
    assert "n2" not in res.to_archive
```

- [ ] **Step 2: Run differ tests — expect FAIL**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_differ.py -v`
Expected: the new repo-scope tests FAIL (current diff ignores `archive_scope`).

- [ ] **Step 3: Implement scope logic in `differ.py`**

Replace the existing-node lookup loop (the block that builds `existing_by_key`, currently filtering `if node_file not in file_paths_set: continue`) with scope-aware filtering. The method signature is already `async def diff(self, project_id, new_symbols, file_paths, *, archive_scope="file", repo_key="")` (added in Task 1 Step 8). Inside, replace the filter:

```python
        file_paths_set = set(file_paths)
        existing_by_key: dict[str, dict[str, object]] = {}
        for node in existing_nodes:
            props = node.get("properties", {}) or node.get("metadata", {})
            if not isinstance(props, dict):
                continue
            node_file = props.get("file_path", "")
            # Code-only guarantee: never consider human-authored knowledge nodes.
            if node.get("created_by") != "python-indexer" or not node_file:
                continue
            if archive_scope == "repo":
                # whole-repo replace: every code node of THIS repo
                if props.get("repo_path") != repo_key:
                    continue
            else:
                # incremental: only nodes in the scanned file set
                if node_file not in file_paths_set:
                    continue
            kind = props.get("kind", "")
            raw_title = node.get("title", "") or node.get("name", "")
            name = raw_title.split(": ", 1)[-1] if ": " in raw_title else raw_title
            key = f"{node_file}:{name}:{kind}"
            existing_by_key[key] = node
```
(The create/update determination and the archive loop — step 4/5 in the method — stay exactly as they are; they already operate on `existing_by_key`.)

- [ ] **Step 4: Run differ tests — expect PASS**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_differ.py -v`
Expected: PASS (all repo-scope + file-scope + human-safety tests green).

- [ ] **Step 5: Add the full-replace integration test**

Append to `$IDX/tests/test_engine_relative_paths.py`:

```python
@pytest.mark.asyncio
async def test_full_rescan_replaces_not_accumulates(tmp_path):
    """100 -> 101 semantics: re-scan archives removed symbol, no duplicate creates."""
    root = tmp_path / "pkg"
    root.mkdir()
    f = root / "mod.py"
    f.write_text("def a():\n    return 1\ndef b():\n    return 2\n")

    # First scan: KG empty -> a, b created
    c1 = _mock_client()
    await IndexingEngine(c1).full_scan("proj", str(tmp_path), repo_key="K")
    first = [p.args[0] for p in c1.create_node.call_args_list]
    assert len(first) == 2

    # Simulate KG now holding a, b (as the differ would see them next time)
    existing = []
    for i, p in enumerate(first):
        props = p["properties"]
        existing.append({"id": f"n{i}", "title": p["title"], "created_by": "python-indexer",
                         "properties": props})

    # Second scan from a DIFFERENT physical root, with b removed and c added
    root2 = tmp_path / "other" / "pkg"
    root2.mkdir(parents=True)
    (root2 / "mod.py").write_text("def a():\n    return 1\ndef c():\n    return 3\n")
    c2 = _mock_client()
    c2.get_nodes.return_value = existing
    res = await IndexingEngine(c2).full_scan("proj", str(tmp_path / "other"), repo_key="K")

    # 'a' unchanged -> not re-created; 'c' new -> created; 'b' gone -> archived
    created_titles = [p.args[0]["title"] for p in c2.create_node.call_args_list]
    assert any("c" in t for t in created_titles)
    assert all("b:" not in t and t != "function: b" for t in created_titles)  # no dup of a/b
    assert res.nodes_archived >= 1   # 'b' archived, not accumulated
```

- [ ] **Step 6: Run the integration test — expect PASS**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_engine_relative_paths.py -v`
Expected: PASS.

- [ ] **Step 7: Fix `test_engine.py::test_incremental_with_existing_nodes` (same `created_by` gap)**

This existing test rebuilds "existing" nodes from the captured `create_node` payloads but drops `created_by`, so after Step 3's code-only filter it would treat every symbol as new and fail `nodes_created == 0`. In `$IDX/tests/test_engine.py`, add `created_by` to the reconstruction loop:

```python
        for call in mock_kg_client.create_node.call_args_list:
            payload = call[0][0]
            existing_nodes.append(
                {
                    "id": f"existing-{len(existing_nodes)}",
                    "title": payload["title"],
                    "created_by": payload.get("created_by"),  # NEW: code-only filter needs this
                    "properties": payload.get("properties", {}),
                }
            )
```
(The payload already carries `created_by="python-indexer"` and a repo-relative `file_path`, so the rebuilt node matches the incremental scan's natural key.)

- [ ] **Step 8: Full indexer suite green**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests -q`
Expected: all pass — including the previously-existing differ and engine tests now that their fixtures carry `created_by`.

- [ ] **Step 9: Commit**

```bash
cd $PY
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/indexer/differ.py \
        packages/ennam-kg-indexer/tests/test_differ.py \
        packages/ennam-kg-indexer/tests/test_engine.py \
        packages/ennam-kg-indexer/tests/test_engine_relative_paths.py
git commit -m "feat(indexer): mode-aware archive scope (repo full-replace / file incremental), code-only"
```

---

### Task 3: CLI module + console script

**Files:**
- Create: `$IDX/src/ennam_kg_indexer/cli.py`
- Modify: `$IDX/pyproject.toml`
- Create: `$IDX/tests/test_cli.py`

- [ ] **Step 1: Write CLI tests (arg parsing, exit codes, env precedence)**

Create `$IDX/tests/test_cli.py`:

```python
"""CLI arg parsing + exit-code behavior."""

from __future__ import annotations

import pytest

from ennam_kg_indexer.cli import build_parser, resolve_config, UsageError


def test_incremental_requires_changed_files():
    args = build_parser().parse_args(
        ["--path", "/tmp/x", "--project-id", "p", "--mode", "incremental"]
    )
    with pytest.raises(UsageError):
        resolve_config(args, env={})


def test_flags_override_env():
    args = build_parser().parse_args(
        ["--path", "/tmp/x", "--project-id", "p", "--api-url", "http://flag", "--api-key", "fk"]
    )
    cfg = resolve_config(args, env={"KG_API_URL": "http://env", "KG_API_KEY": "ek"})
    assert cfg.api_url == "http://flag"
    assert cfg.api_key == "fk"


def test_env_used_when_flag_absent():
    args = build_parser().parse_args(["--path", "/tmp/x", "--project-id", "p"])
    cfg = resolve_config(args, env={"KG_API_URL": "http://env", "KG_API_KEY": "ek"})
    assert cfg.api_url == "http://env"
    assert cfg.api_key == "ek"


def test_missing_api_url_is_usage_error():
    args = build_parser().parse_args(["--path", "/tmp/x", "--project-id", "p"])
    with pytest.raises(UsageError):
        resolve_config(args, env={})


def test_repo_key_defaults_to_path():
    args = build_parser().parse_args(["--path", "/repos/foo", "--project-id", "p"])
    cfg = resolve_config(args, env={"KG_API_URL": "u", "KG_API_KEY": "k"})
    assert cfg.repo_key == "/repos/foo"
```

- [ ] **Step 2: Run CLI tests — expect FAIL**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_cli.py -v`
Expected: FAIL — `ennam_kg_indexer.cli` does not exist.

- [ ] **Step 3: Write `cli.py`**

Create `$IDX/src/ennam_kg_indexer/cli.py`:

```python
"""Command-line entry point for ennam-kg-indexer.

Reads source from a local --path and pushes knowledge nodes to a remote KG.
Config from env (KG_API_URL, KG_API_KEY, KG_PROJECT_ID); flags override env.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass

import httpx

from ennam_kg_indexer.indexer.engine import IndexingEngine
from ennam_kg_indexer.kg_client.client import KGClient, KGClientError


class UsageError(Exception):
    """Raised for invalid argument combinations (maps to exit code 2)."""


@dataclass
class Config:
    path: str
    project_id: str
    repo_key: str
    mode: str
    changed_files: list[str]
    api_url: str
    api_key: str


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ennam-kg-index", description="Index local source into Ennam KG.")
    p.add_argument("--path", required=True, help="physical directory to read source from")
    p.add_argument("--project-id", help="KG project id (or env KG_PROJECT_ID)")
    p.add_argument("--repo-key", help="stable repo identity stored in KG (default: --path)")
    p.add_argument("--mode", choices=["full", "incremental"], default="full")
    p.add_argument("--changed-files", help="comma-separated repo-relative paths (incremental only)")
    p.add_argument("--api-url", help="overrides env KG_API_URL")
    p.add_argument("--api-key", help="overrides env KG_API_KEY")
    return p


def resolve_config(args: argparse.Namespace, env: dict[str, str]) -> Config:
    api_url = args.api_url or env.get("KG_API_URL", "")
    api_key = args.api_key or env.get("KG_API_KEY", "")
    project_id = args.project_id or env.get("KG_PROJECT_ID", "")
    if not api_url or not api_key:
        raise UsageError("KG_API_URL and KG_API_KEY are required (via flags or env)")
    if not project_id:
        raise UsageError("--project-id (or KG_PROJECT_ID) is required")
    changed: list[str] = []
    if args.mode == "incremental":
        if not args.changed_files:
            raise UsageError("--changed-files is required when --mode incremental")
        changed = [c.strip() for c in args.changed_files.split(",") if c.strip()]
        if not changed:
            raise UsageError("--changed-files contained no valid paths")
    return Config(
        path=args.path, project_id=project_id, repo_key=args.repo_key or args.path,
        mode=args.mode, changed_files=changed, api_url=api_url, api_key=api_key,
    )


async def _run(cfg: Config) -> int:
    if not os.path.isdir(cfg.path):
        print(f"error: --path does not exist or is not a directory: {cfg.path}", file=sys.stderr)
        return 1
    # Own the httpx client via `async with` so it is always closed cleanly
    # (no ResourceWarning on exit). KGClient uses the passed client's base_url
    # for its relative request paths.
    async with httpx.AsyncClient(base_url=cfg.api_url, timeout=30.0) as http:
        client = KGClient(cfg.api_url, cfg.api_key, http_client=http)
        # Pre-flight: a cheap authenticated request. Connection/auth failure => exit 1.
        try:
            await client.get_nodes(cfg.project_id)
        except Exception as exc:  # connection refused, 401, etc.
            print(f"error: cannot reach KG API ({exc})", file=sys.stderr)
            return 1

        engine = IndexingEngine(client)
        try:
            if cfg.mode == "full":
                result = await engine.full_scan(cfg.project_id, cfg.path, repo_key=cfg.repo_key)
            else:
                result = await engine.incremental_scan(
                    cfg.project_id, cfg.path, cfg.changed_files, repo_key=cfg.repo_key
                )
        except KGClientError as exc:
            print(f"error: indexing failed ({exc})", file=sys.stderr)
            return 1

        summary = {
            "mode": cfg.mode, "repo_key": cfg.repo_key,
            "files_scanned": result.files_scanned, "symbols_found": result.symbols_found,
            "nodes_created": result.nodes_created, "nodes_updated": result.nodes_updated,
            "nodes_archived": result.nodes_archived, "edges_created": result.edges_created,
            "errors": result.errors,
        }
        print(json.dumps(summary))
        return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    parser = build_parser()
    args = parser.parse_args()
    try:
        cfg = resolve_config(args, dict(os.environ))
    except UsageError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(_run(cfg)))
```

- [ ] **Step 4: Run CLI tests — expect PASS**

Run: `cd $PY && uv run pytest packages/ennam-kg-indexer/tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Register the console script**

In `$IDX/pyproject.toml`, add after the `[project]` table (before `[build-system]`):
```toml
[project.scripts]
ennam-kg-index = "ennam_kg_indexer.cli:main"
```

- [ ] **Step 6: Re-sync and smoke-test the console script exists**

```bash
cd $PY
uv sync
uv run ennam-kg-index --help
```
Expected: argparse help text printed (exit 0); confirms the entry point is wired.

- [ ] **Step 7: Commit**

```bash
cd $PY
git add packages/ennam-kg-indexer/src/ennam_kg_indexer/cli.py \
        packages/ennam-kg-indexer/pyproject.toml \
        packages/ennam-kg-indexer/tests/test_cli.py \
        uv.lock
git commit -m "feat(indexer): add ennam-kg-index CLI entry point"
```

---

### Task 4: Docker image

**Files:**
- Create: `$IDX/Dockerfile`

- [ ] **Step 1: Write the Dockerfile**

Create `$IDX/Dockerfile`:

```dockerfile
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
COPY README.md ./
RUN uv pip install --system --no-cache .

FROM python:3.12-slim
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/ennam-kg-index /usr/local/bin/ennam-kg-index
ENTRYPOINT ["ennam-kg-index"]
```

> No `git` is installed — the CLI only reads `--path` (host has already checked out / mounted the source).

- [ ] **Step 2: Build the image**

```bash
cd $IDX
docker build -t ennam-kg-indexer:dev .
```
Expected: build succeeds; `ennam-kg-index` installed in the final image.

- [ ] **Step 3: Smoke-test the entry point in the image**

```bash
docker run --rm ennam-kg-indexer:dev --help
```
Expected: argparse help text (exit 0), proving the console script runs inside the image.

- [ ] **Step 4: Commit**

```bash
cd $PY
git add packages/ennam-kg-indexer/Dockerfile
git commit -m "build(indexer): Docker image for non-Python hosts"
```

---

### Task 5: README + final verification

**Files:**
- Modify: `$IDX/README.md`

- [ ] **Step 1: Document usage in the README**

Append a "CLI usage" section to `$IDX/README.md` covering: pip install + `ennam-kg-index` flags/env; the Docker sidecar example; and the migration note that existing mount-indexed projects need one full re-index after upgrade (paths switch from absolute to repo-relative). Use this content:

```markdown
## CLI usage

Install (Python host): `pip install ennam-kg-indexer` → provides `ennam-kg-index`.

```bash
KG_API_URL=https://kg.server.com KG_API_KEY=xxx \
ennam-kg-index --path /path/to/repo --repo-key github.com/org/repo \
               --project-id <uuid> --mode full
```

Flags: `--path` (physical dir, required), `--project-id` (or `KG_PROJECT_ID`),
`--repo-key` (stable identity, default `--path`), `--mode full|incremental`,
`--changed-files a,b` (repo-relative, required for incremental),
`--api-url`/`--api-key` (override env). Exit: 0 ok, 2 usage error, 1 runtime/connection error.
Prints a JSON summary to stdout; logs to stderr.

Docker (non-Python host):
```bash
docker run --rm -e KG_API_URL=... -e KG_API_KEY=... -v /host/repo:/src:ro \
  ennam-kg-indexer --path /src --repo-key github.com/org/repo --project-id <uuid>
```

### Migration note
This version stores `file_path` as **repo-relative** (was absolute). Existing
mount-indexed projects must be **fully re-indexed once** after upgrade (via the
dashboard "Index Now" or `POST /api/v1/projects/{id}/index`); the re-index
archives old absolute-path nodes and creates fresh relative-path ones.

> **Run the full re-index BEFORE any incremental scan.** An incremental scan that
> lands first cannot match the old absolute-path nodes (their natural keys differ),
> so it would **create duplicate** relative-path nodes instead of updating in place.
> Until the one-time full re-index has run, treat incremental scans as unsafe for
> an upgraded project.
```

- [ ] **Step 2: Clean-room install check (lightweight, no heavy deps)**

```bash
cd /tmp && rm -rf _cli_check && python3.12 -m venv _cli_check && . _cli_check/bin/activate
pip install "$IDX"
ennam-kg-index --help          # prints usage
python -c "import anthropic" 2>&1 | grep -q "No module named" && echo "anthropic absent: OK"
deactivate && rm -rf /tmp/_cli_check
```
Expected: help text prints; "anthropic absent: OK" prints (CLI carries only lightweight deps).

- [ ] **Step 3: Full service + indexer suites green (no regression)**

```bash
cd $PY
uv run pytest tests packages/ennam-kg-indexer/tests -q
```
Expected: both suites pass — existing callers (`worker.py`, `api/indexing.py`) still work with the optional `repo_key` default.

- [ ] **Step 4: Live end-to-end smoke (Docker stack)**

```bash
cd /Users/danhtrinh/Projects/Exnodes/EnnamKG/ennam.kg.workspace
docker compose up -d postgres redis kg-server indexer
# Run the CLI from inside the indexer container against a mounted repo:
docker compose exec indexer ennam-kg-index \
  --path /repos/ennam-kg-go --repo-key /repos/ennam-kg-go \
  --project-id <existing-project-uuid> --mode full \
  --api-url http://kg-server:8080 --api-key ennam_kg_dev_000000000000000000000000
# Re-run the SAME command — node counts must stay stable (replace, not accumulate).
```
Expected: first run prints a JSON summary with `nodes_created > 0`; second run shows `nodes_created` ~0 / `nodes_updated` for unchanged + correct active totals (no doubling).

- [ ] **Step 5: Commit**

```bash
cd $PY
git add packages/ennam-kg-indexer/README.md
git commit -m "docs(indexer): CLI usage, Docker, and migration note"
```

---

## Self-Review

### Spec coverage

| Spec section | Task |
|--------------|------|
| Part 1 — CLI surface (flags, env, exit codes, JSON, single-repo) | Task 3 |
| Part 2.1 — repo-relative `file_path`, normalize EARLY (edge-safe) | Task 1 |
| Part 2.2 — stable `repo_key` | Task 1 |
| Part 2.3 — archive scope repo/file, code-only, never human | Task 2 |
| Part 2.4 — edge re-index semantics (dedup; orphan deferred) | No code (verified-existing: UNIQUE constraint); documented, no task needed |
| Part 2.5 — engine signatures backward-compatible + changed-files join | Task 1 |
| Part 3.1 — pip console script | Task 3 |
| Part 3.2 — Docker image (no git) | Task 4 |
| Part 4 — backward compat + migration note | Task 1 (callers unchanged) + Task 5 (README note) |
| Part 5 — tests (CLI, extractor, edge regression, differ repo/file/human, integration) | Tasks 1–3 |

### Placeholder scan

No TBD/TODO. Every code/command step shows concrete content.

### Type consistency

- `symbol_to_node(symbol, project_id, *, repo_key)` — defined Task 1 Step 3, called in engine `_process_files` Task 1 Step 7, exercised in Task 1 Step 1 test. Consistent.
- `differ.diff(project_id, new_symbols, file_paths, *, archive_scope, repo_key)` — tolerant signature added Task 1 Step 8, logic Task 2 Step 3, called by engine Task 1 Step 7. Consistent.
- `full_scan(project_id, repo_path, *, repo_key=None)` / `incremental_scan(..., *, repo_key=None)` — Task 1 Step 7; CLI calls them Task 3 Step 3. Consistent.
- `Config` dataclass + `resolve_config`/`build_parser`/`UsageError` — defined Task 3 Step 3, used in Task 3 Step 1 tests. Consistent.

### Note on task ordering

Task 1 adds a tolerant `diff` signature (accepts but ignores `archive_scope`/`repo_key`) so the repo stays green before Task 2 implements the scope logic. Every task ends green and is committed independently.
