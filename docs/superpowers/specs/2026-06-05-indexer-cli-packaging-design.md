# `ennam-kg-indexer` CLI + Packaging — Design Spec

**Date**: 2026-06-05
**Status**: Approved (design)
**Goal**: Ship a thin CLI (`ennam-kg-index`) and a Docker image around the already-extracted `ennam-kg-indexer` package so any host — Python (pip) or non-Python (Docker sidecar) — can index local source and push knowledge nodes to a remote Ennam KG. Re-indexing a repo yields the **latest state, never accumulated** (100 → 101 active nodes, not 201).

**Depends on**: `2026-06-05-indexer-package-split-design.md` (DONE — `ennam-kg-indexer` package exists).
**Downstream (separate spec, B2)**: MCP `kg_index_source` tool that shells out to this CLI.

---

## Context

The indexer package (`parsers/`, `indexer/`, `kg_client/`) is now standalone and lightweight (`tree-sitter`, `pathspec`, `httpx`, `pydantic`). It has no entry point yet. To let external systems (e.g. LAAM) index their own source and send only the resulting nodes to a remote KG, we add:

1. A CLI entry point `ennam-kg-index` (pip console script).
2. A Docker image wrapping it for non-Python hosts.
3. **An engine semantics change** required by the "no accumulation" guarantee — covered below. This is the meaty part; the CLI itself is a thin shell.

### Why the engine must change (the real work)

Today code nodes store `properties.file_path` as an **absolute** path and `properties.repo_path` as the absolute scan root. The indexer's idempotency depends on the natural key `file_path:name:kind` being stable across runs. Two gaps break "re-index = latest state, no accumulation":

- **Gap 1 — unstable absolute paths.** On a fixed Docker mount (`/repos/ennam-kg-go`) keys are stable. But a CLI host may check the repo out at a different path each run (`/home/x/proj`, `/tmp/ci/proj`, a random clone dir). Keys drift → every run creates duplicates → accumulation.
- **Gap 2 — deleted-file nodes never archived.** The differ scopes archive to the *files scanned this run*. A file deleted between runs is not scanned, so its old nodes are never archived → accumulation, even on a stable mount.

Both are fixed here. Note this engine change is also the fix for the **Task 12a blocker** documented in the GitHub integration plan (`2026-06-05-github-integration-per-user.md`) — completing this spec removes the hardest part of that plan.

---

## Decisions (confirmed)

| # | Decision | Choice |
|---|----------|--------|
| Q1 | Scan modes | **Both** `full` and `incremental` |
| Q2 | Config/auth source | **Env vars + flags override** |
| Q3 | Incremental changed-files | **Explicit `--changed-files`** (caller-provided; no git in CLI) |
| Q4 | Disappeared nodes on re-index | **Archive (soft)** — keep version history |
| — | Repos per invocation | **One** (`--path` + `--repo-key`); host loops for multi-repo |
| — | Engine approach | **Approach 1** — repo-relative `file_path` + stable `repo_key` + repo-scoped archive (full) / per-file archive (incremental) |

---

## Part 1 — CLI Surface

Single console script `ennam-kg-index` exposed by the `ennam-kg-indexer` package.

```
ennam-kg-index \
  --path <dir>                # physical directory to READ source from (required)
  --project-id <uuid>         # KG project (required; or env KG_PROJECT_ID)
  --repo-key <str>            # stable repo identity stored in KG (default: value of --path)
  --mode full|incremental     # default: full
  --changed-files <a,b>       # required when --mode incremental; repo-relative paths, comma-separated
  --api-url <url>             # overrides env KG_API_URL
  --api-key <key>             # overrides env KG_API_KEY
```

**Config resolution:** flags override env. `KG_API_URL`, `KG_API_KEY`, `KG_PROJECT_ID` read from environment; `--api-url`, `--api-key`, `--project-id` override when present.

**Output / behavior:**
- **stdout**: a single JSON summary on completion — `{"mode", "repo_key", "files_scanned", "symbols_found", "nodes_created", "nodes_updated", "nodes_archived", "edges_created", "errors": [...]}`. Machine-parseable for hosts.
- **stderr**: human-readable progress logs (the engine's `logging` output is routed here, never to stdout).
- **Exit codes**:
  - `0` — scan completed (may include non-fatal per-file `errors[]`; a few unparseable files do not fail the run).
  - `2` — usage error (missing `--path`/`--project-id`, or `--mode incremental` without `--changed-files`).
  - `1` — fatal runtime error: `--path` does not exist, or the KG API is unreachable. A **pre-flight connectivity check** (cheap authenticated request, e.g. `GET /healthz` or a 1-node query) runs before scanning so an API-down situation exits `1` rather than "completing" with an all-errors result.

**`--changed-files` convention:** paths are **repo-relative** (relative to the repo root, matching the stored `file_path` scheme), not absolute — consistent so incremental keys line up with full-scan keys.

**Single-repo per call (intentional):** one `--path` + one `--repo-key` per invocation. A multi-repo project is indexed by the host calling the CLI once per repo. This keeps archive scope unambiguous (one repo = one unit) and the CLI composable. (The Python HTTP `/index/batch` endpoint remains the multi-repo entry for HTTP callers; the CLI stays single-repo.)

**Example (non-mount host, e.g. LAAM after checkout/clone):**
```bash
KG_API_URL=https://kg.server.com KG_API_KEY=xxx \
ennam-kg-index --path /tmp/clone-abc \
               --repo-key github.com/exnodes/ennam-kg-go \
               --project-id proj-123 --mode full
```

---

## Part 2 — Engine Semantics (Approach 1)

> **Critical KG-system safety guarantee:** code nodes share a project with human-authored knowledge nodes (decision/concept/requirement/…). A full re-index **must never archive human nodes** — only code nodes (`created_by == "python-indexer"`).

### 2.1 Repo-relative `file_path`

Parsers must read files by their **physical** path (`file_path.read_bytes()`), so relativization happens **after** parsing, in the extractor. `NodeExtractor.symbol_to_node` gains two distinct inputs:

```python
def symbol_to_node(self, symbol, project_id, *, physical_root: str, repo_key: str) -> dict:
    ...
    rel_path = os.path.relpath(symbol.file_path, physical_root)  # stable across checkouts
    ...
    "properties": {
        ...
        "file_path": rel_path,     # was: symbol.file_path (absolute)
        "repo_path": repo_key,     # was: the absolute scan root; now the stable logical key
        ...
    }
```

- `physical_root` = the `--path` actually read from (used ONLY to compute the relative path).
- `repo_key` = the stable logical identity (`--repo-key`, default = `--path`), stored in the existing `properties.repo_path` field — **no schema change** (verified: no consumer reads `properties.repo_path` as a real filesystem path; the only `repo_path` reference elsewhere is the `IndexMessage` transport field in Go).

### 2.2 Stable `repo_key` identity

The natural key remains `file_path:name:kind` but `file_path` is now repo-relative, so it is independent of where the repo is checked out. `repo_key` identifies which repo a node belongs to within a multi-repo project.

### 2.3 Archive scope by mode

`IndexDiffer.diff` gains `archive_scope` and `repo_key` parameters:

```python
async def diff(self, project_id, new_symbols, file_paths, *,
               archive_scope: str,    # "repo" (full) | "file" (incremental)
               repo_key: str) -> DiffResult:
```

- **full scan** → `archive_scope="repo"`: consider existing nodes where
  `created_by == "python-indexer"` **AND** `properties.repo_path == repo_key`.
  Archive any whose natural key is absent from the new scan. This catches deleted-file nodes (Gap 2) and is multi-repo safe (a scan of repo A never touches repo B's nodes, different `repo_key`) and human-node safe (`created_by` filter).
- **incremental scan** → `archive_scope="file"`: existing per-file behavior — only nodes whose `file_path` is in the scanned `--changed-files` set are considered for archive. Also filtered to code nodes.

> **Human-node safety implementation:** the primary filter is `created_by == "python-indexer"`. `get_nodes` (via `POST /api/v1/query`) returns full node dicts including `created_by`. Belt-and-suspenders: nodes without a `properties.file_path` (all human knowledge nodes) are excluded regardless. Both conditions must hold for a node to be archive-eligible.

### 2.4 Engine signatures (backward compatible)

```python
async def full_scan(self, project_id, repo_path, *, repo_key: str | None = None) -> IndexResult
async def incremental_scan(self, project_id, repo_path, changed_files, *, repo_key: str | None = None) -> IndexResult
```

`repo_path` is the physical root (read + relativize). `repo_key` defaults to `repo_path` when omitted. Existing callers (`worker.py` mount path, `api/indexing.py` `/index` + `/index/batch`) keep working unchanged — they get `repo_key == repo_path`, preserving today's behavior modulo the relative-path migration (§4).

---

## Part 3 — Packaging

### 3.1 pip CLI (Python hosts)

In `packages/ennam-kg-indexer/pyproject.toml`:
```toml
[project.scripts]
ennam-kg-index = "ennam_kg_indexer.cli:main"
```
New module `src/ennam_kg_indexer/cli.py`: argparse-based flag/env resolution → build `KGClient(api_url, api_key)` → pre-flight connectivity check → `IndexingEngine(kg_client).full_scan(...)` or `.incremental_scan(...)` → print JSON summary. `main()` wraps an `asyncio.run`. Logging configured to stderr.

### 3.2 Docker image (non-Python hosts)

`packages/ennam-kg-indexer/Dockerfile`: base `python:3.12-slim`, install the indexer package only (lightweight deps), `ENTRYPOINT ["ennam-kg-index"]`. **No `git`** needed — the CLI only reads `--path` (the host has already checked out / cloned and mounts it). Usage:

```bash
docker run --rm \
  -e KG_API_URL=https://kg.server.com -e KG_API_KEY=xxx \
  -v /host/repo:/src:ro \
  ennam-kg-indexer --path /src --repo-key github.com/exnodes/foo \
                   --project-id proj-123 --mode full
```

### 3.3 Single code path

CLI and Docker are thin shells over the same `IndexingEngine` + `KGClient` + REST API used by the internal worker. There is no second indexing implementation, so internal and external indexing cannot diverge in behavior.

---

## Part 4 — Backward Compatibility & Migration

- **Callers unchanged:** `repo_key` is optional (defaults to `repo_path`); `worker.py` and `api/indexing.py` need no call-site change. The `extractor`/`differ` changes are internal.
- **Self-healing migration, no migration script:** after deploy, each existing project/repo needs **one full re-index** (via the existing "Index Now" UI button or `POST /api/v1/projects/{id}/index`). On that run, old absolute-`file_path` nodes (same `repo_path` == mount path == default `repo_key`) fall within the repo-scoped archive set and are archived; fresh repo-relative nodes are created. Subsequent runs are stable.
- **Pre-migration state is safe:** until the one-time re-index, old nodes remain `active` exactly as before — nothing breaks, they simply have not yet gained stable keys.
- **Deploy note (must be in the plan):** trigger one full re-index per existing mount-indexed project after deploying this change.

---

## Part 5 — Testing

All tests live in `packages/ennam-kg-indexer/tests/`.

- **CLI (`cli.py`)**: full vs incremental parsing; `--mode incremental` without `--changed-files` → exit `2`; missing `--project-id` → exit `2`; env-vs-flag precedence; unreachable API → exit `1` (pre-flight); non-existent `--path` → exit `1`.
- **Extractor**: given `physical_root` + an absolute file path → `properties.file_path` is the correct repo-relative path; `properties.repo_path` equals the passed `repo_key`.
- **Differ — full (`archive_scope="repo"`)**: code node with matching `repo_key` absent from the new scan → archived (incl. a node whose whole file was deleted); a node with `created_by != "python-indexer"` (human knowledge) is **never** archived; a node with a different `repo_key` (another repo in the same project) is untouched.
- **Differ — incremental (`archive_scope="file"`)**: per-file scope unchanged; only `--changed-files` nodes considered.
- **Integration (the core "no accumulation" guarantee)**: `full_scan` twice with the same `repo_key`; second scan removes one symbol and adds two → the removed node is archived (not duplicated), the two new are created, and the active code-node count reflects the latest state (e.g. 100 → 101 active, never 201). Run from a *different* `physical_root` on the second pass to prove path-stability (relative keys still match).

---

## Out of Scope (this spec)

- MCP `kg_index_source` tool (separate spec B2 — shells out to this CLI).
- Incremental via `git diff` inside the CLI (Q3 chose explicit `--changed-files`; git-based detection deferred).
- PyPI publishing automation / image registry push (local build only for now).
- Hard delete of nodes (Q4 chose soft archive).
