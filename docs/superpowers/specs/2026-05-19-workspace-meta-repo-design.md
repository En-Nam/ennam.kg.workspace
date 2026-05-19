# Design: Workspace Meta-Repo + One-Shot Sub-Repo Bootstrap

- **Date:** 2026-05-19
- **Status:** Approved (design); pending spec review
- **Author:** claude-opus (technical-leader session)
- **Topic:** Make the project root a shareable git repo and let any teammate clone all sub-repos in one command.

## 1. Problem

The project root `ennam.kg/` holds team-critical, non-code assets — `CLAUDE.md`,
`AGENTS.md`, `docs/`, `scripts/`, `seeds/`, `docker-compose*.yml`, the Serena
knowledge store (`.serena/memories`, `.serena/checkpoint`) and Claude tooling
config — but it is **not** a git repository, so none of it is shared with the team.
Meanwhile the four code repos already exist as independent GitHub repos.

A teammate today has no single, reproducible way to get the root assets and then
pull every sub-repo at the right branch.

## 2. Goal

Two-step, reproducible onboarding:

1. Clone one workspace repo → get all shareable root assets.
2. Run one bootstrap command → all four sub-repos cloned into place on `main`.

Non-goals (explicitly out of scope, YAGNI):

- Updating / pulling sub-repos that already exist (branch model is "clone main,
  then dev creates own feature branches" — no forced main-tracking).
- Submodules or any third-party multi-repo tool.
- CI, automation, or hooks around the workspace repo.

## 3. Decisions (locked with user)

| # | Decision | Value |
|---|----------|-------|
| D1 | Workspace repo remote | `git@github.com:En-Nam/ennam.kg.workspace.git` |
| D2 | Clone mechanism | Manifest + cross-platform bootstrap scripts (not submodules, not 3rd-party tool) |
| D3 | Platforms | Windows **and** mac/linux — `.ps1` + `.sh`, one shared manifest |
| D4 | Branch model | Bootstrap clones at `main`; devs create feature branches themselves |
| D5 | Manifest location | `scripts/repos.txt` |
| D6 | Error handling | Best-effort: attempt all repos, collect failures, print summary, exit code ≠ 0 if any failed |
| D7 | Claude config | Promote `.claude/settings.local.json` → committed `.claude/settings.json`; gitignore the `.local.json` |

## 4. Architecture

Meta-repo (workspace) pattern: the workspace repo carries shared config &
knowledge; the four code repos stay fully independent with their own lifecycles.

```
ennam.kg/                         ← workspace repo (team clones this)
├── CLAUDE.md, AGENTS.md, docs/, scripts/, seeds/, docker-compose*.yml ...  ← tracked
├── README.md                     ← NEW: human onboarding entrypoint
├── scripts/repos.txt             ← NEW: manifest (single source of truth)
├── scripts/bootstrap.sh          ← NEW: reader for mac/linux
├── scripts/bootstrap.ps1         ← NEW: reader for windows
├── .gitignore                    ← NEW: excludes sub-repos + secrets + caches
├── .claude/settings.json         ← NEW: promoted from settings.local.json
├── ennam.kg.go/                  ← git-ignored, cloned by bootstrap
├── ennam.kg.python/              ← git-ignored, cloned by bootstrap
├── ennam.kg.next/                ← git-ignored, cloned by bootstrap
└── ennam.kg.requirements/        ← git-ignored, cloned by bootstrap
```

Data/logic separation: the manifest is data, the scripts are logic. Adding a
future sub-repo = one new line in `scripts/repos.txt`, no script change.

## 5. Components

### 5.1 Manifest — `scripts/repos.txt`

Plain whitespace-delimited text. Chosen over JSON/YAML so **both** PowerShell and
Bash parse it with zero dependencies (no `jq`, no YAML module) — this is what
keeps the two scripts from ever drifting apart.

Format: three columns `dir url branch`; lines starting with `#` and blank lines
are ignored.

```
# dir                  url                                              branch
ennam.kg.go            git@github.com:En-Nam/ennam.kg.go.git            main
ennam.kg.python        git@github.com:En-Nam/ennam.kg.python.git        main
ennam.kg.next          git@github.com:En-Nam/ennam.kg.next.git          main
ennam.kg.requirements  git@github.com:En-Nam/ennam.kg.requirements.git  main
```

### 5.2 Bootstrap scripts — `scripts/bootstrap.sh` + `scripts/bootstrap.ps1`

Identical behavior, ~30–40 lines each.

Algorithm (idempotent):

1. Resolve workspace root = parent directory of the `scripts/` dir holding the
   script → runnable from any working directory.
2. Read `scripts/repos.txt`; skip `#`/blank lines; parse `dir url branch`.
3. For each repo, inspect target dir `<root>/<dir>`:
   - **Missing** → `git clone -b <branch> <url> <dir>` → count *cloned*.
   - **Exists and is a git repo** → skip, print "already present" → count
     *skipped*. (Re-run safe.)
   - **Exists but NOT a git repo** (leftover/empty dir) → do **not** touch it,
     warn → count *failed*. The script never overwrites/deletes anything it did
     not create (AGENTS.md Rule 3).
4. Per D6 best-effort: a clone failure is recorded, the loop continues to the
   next repo.
5. Print a final summary line `cloned=<n> skipped=<n> failed=<n>` and exit with
   a non-zero code if `failed > 0`.

Preconditions: `git` must be on PATH. SSH access to the `En-Nam` org is required
(remotes are SSH). The script does not pre-probe SSH (noisy / can hang); on a
clone failure it surfaces git's own error so the cause is visible.

### 5.3 Root `.gitignore`

```gitignore
# --- Sub-repos (cloned by scripts/bootstrap.*) ---
/ennam.kg.go/
/ennam.kg.python/
/ennam.kg.next/
/ennam.kg.requirements/

# --- Secrets / local (NEVER commit) ---
/.env
/SECRET.md
/.claude/settings.local.json

# --- Cache / tool dirs ---
/.ruff_cache/
/.playwright-mcp/

# --- Scratch screenshots at root (real images go in docs/) ---
/*.png
```

`.serena/.gitignore` already excludes `/cache` and `/project.local.yml` within
`.serena/`; that file is left as-is and not duplicated at root (surgical, AGENTS
Rule 3). `.serena/memories`, `.serena/checkpoint`, `.serena/project.yml` remain
tracked and shared.

### 5.7 `.gitattributes` (root) — cross-platform line-ending guard

Added during implementation after code review found a real cross-platform
defect: a CRLF `scripts/repos.txt` (routine on Windows with
`core.autocrlf=true`) made `bootstrap.sh` fail while `bootstrap.ps1` succeeded —
the exact "shared manifest prevents drift" guarantee of §5.1, broken. A
CRLF-corrupted `bootstrap.sh` would also fail its own `#!/usr/bin/env bash`
shebang on macOS/Linux. Mitigation is two-layered:

- `.gitattributes` pins `*.sh` and `scripts/repos.txt` to `eol=lf` so they stay
  LF on any checkout regardless of `core.autocrlf`.
- `bootstrap.sh` reads with `IFS=$' \t\r'` so a stray `\r` is treated as a field
  separator even if the file is fetched outside git (zip download, Notepad).

`bootstrap.ps1` additionally sets `$ErrorActionPreference = 'Stop'` to mirror
`set -u`'s robustness posture (`Set-StrictMode` was deliberately not added —
nonzero regression risk against the existing conditional array-index code).

### 5.4 `.claude` config promotion (D7)

`.claude/settings.local.json` currently holds a permission allowlist + the
chrome-devtools MCP server config — team tooling, not personal secrets. Per
Claude Code convention, `settings.json` is the shared baseline and
`settings.local.json` is a personal override. Action: copy the current content
to `.claude/settings.json` (committed); gitignore `.claude/settings.local.json`
so a dev's personal overrides never get forced onto the team.

### 5.5 `README.md` (new, root)

Root has no README today. This becomes the human onboarding entrypoint
(distinct from the agent-facing CLAUDE.md):

- Prerequisites: `git`; SSH key added to the GitHub `En-Nam` org.
- Quickstart (the two-step flow, with both `.sh` and `.ps1` invocation).
- Note that sub-repos are cloned at runtime and are intentionally not part of
  the workspace repo.

### 5.6 Tracked assets (kept, not ignored)

CLAUDE.md, AGENTS.md, the `*.md` design/plan docs, `docs/`, `scripts/`,
`seeds/`, `docker-compose.yml`, `docker-compose.override.yml.dev`,
`.env.example`, `.vscode/`, `ennam.kg.code-workspace`,
`.serena/{memories,checkpoint,project.yml,.gitignore}`,
`.claude/settings.json`, `.gitattributes`.

## 6. Error Handling Strategy

Per D6 (best-effort + summary):

- A failed clone for one repo does not abort the others.
- Failures are collected and reported in the final summary.
- Exit code is non-zero when any repo failed, so the command is scriptable /
  detectable in onboarding checks.
- A pre-existing non-git directory at a target path is treated as a failure for
  that repo, never overwritten.

## 7. Verification Plan (executed in Phase 5, after implementation)

1. `git init` then `git add -A`; `git status` must show: the 4 sub-repo dirs,
   `.env`, `SECRET.md`, `*.png`, `.claude/settings.local.json` **not** staged;
   CLAUDE.md, `docs/`, `.serena/memories`, `.claude/settings.json` **staged**.
2. `git check-ignore .env SECRET.md ennam.kg.go .claude/settings.local.json`
   returns each path (deterministic gitignore proof).
3. Functional: from a clean temporary directory, run each bootstrap script →
   all four repos clone onto `main`; a second run reports every repo as
   *skipped* (idempotency proof); summary line and exit code correct.
4. Parity: `.sh` and `.ps1` produce the same cloned/skipped/failed outcome from
   the same `repos.txt`.

## 8. Risks & Open Items

- **Git init / commit deferral:** the workspace repo does not exist yet, so the
  design doc (and all new files) can only be committed once `git init` + the
  initial commit happen — that is step 1 of the implementation plan, not part of
  brainstorming. Noted explicitly so "commit the design doc" is not silently
  skipped (AGENTS.md Rule 12).
- **Remote must exist:** `En-Nam/ennam.kg.workspace` must be created on GitHub
  (empty) before the first `git push`. Implementation plan will call this out as
  a manual/owner step if the remote is absent.
- **Secret hygiene:** `.env` and `SECRET.md` already exist with real content;
  the very first `git add` must already exclude them — verification step 1/2
  gates this before any push.
- **CRLF cross-platform defect (found in review, resolved):** the original
  `bootstrap.sh` mis-parsed a CRLF `scripts/repos.txt`, diverging from
  `bootstrap.ps1` and breaking §5.1's anti-drift guarantee. Resolved by §5.7
  (`.gitattributes` `eol=lf` + `IFS`-based `\r` tolerance in `bootstrap.sh`).
