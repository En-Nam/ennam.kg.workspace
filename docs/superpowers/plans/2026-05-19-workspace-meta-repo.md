# Workspace Meta-Repo + One-Shot Sub-Repo Bootstrap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the project root a shareable git repo (`En-Nam/ennam.kg.workspace`) and let any teammate clone all four sub-repos onto `main` with one command.

**Architecture:** Meta-repo pattern. The workspace repo carries shared config + knowledge; the four code repos stay independent and are cloned at runtime by a cross-platform bootstrap that reads a single text manifest (`scripts/repos.txt`). `.gitignore` excludes the sub-repo dirs, secrets, caches.

**Tech Stack:** git, Bash, Windows PowerShell. No build system, no test framework, no third-party multi-repo tool.

**Spec:** `docs/superpowers/specs/2026-05-19-workspace-meta-repo-design.md` (decisions D1–D7 referenced below).

> **Verification note (AGENTS.md Rule 2 + Rule 7):** A 30-line idempotent one-shot bootstrap does not warrant a committed test framework — that would be speculative weight in a repo whose `scripts/` are plain `.sh` files. Instead, Task 5 verifies behavior with **deterministic inline commands against a throwaway local git fixture** (real evidence, no network, nothing committed). This is a conscious, surfaced deviation from strict TDD-with-test-files; the evidence requirement of verification-before-completion is still met.

> **Ordering is safety-critical:** `.env` and `SECRET.md` hold real secrets. `.gitignore` (Task 1) MUST exist and be proven correct (Task 8 gate) *before* the first commit (Task 9) and any push (Task 10). Do not reorder.

---

### Task 1: Create root `.gitignore` + `.gitattributes` (safety-first — before any `git` command)

**Files:**
- Create: `d:\Projects\EnNam\ennam.kg\.gitignore`
- Create: `d:\Projects\EnNam\ennam.kg\.gitattributes`

- [ ] **Step 1: Create the file with this exact content**

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

- [ ] **Step 2: Verify it exists and content matches**

Run: `cat .gitignore`
Expected: the 6 grouped sections above, verbatim.

Note: `.serena/.gitignore` already excludes `/cache` and `/project.local.yml` within `.serena/` — leave that file untouched; do not duplicate those rules here (AGENTS.md Rule 3).

- [ ] **Step 3: Create `.gitattributes` (cross-platform line-ending guard — added per code review, spec §5.7)**

Create `d:\Projects\EnNam\ennam.kg\.gitattributes` with exactly:

```gitattributes
# Cross-platform bootstrap must stay LF even on Windows checkouts (core.autocrlf).
*.sh              text eol=lf
scripts/repos.txt text eol=lf
```

Rationale: a CRLF `scripts/repos.txt` (routine on Windows with
`core.autocrlf=true`) broke `bootstrap.sh` while `bootstrap.ps1` succeeded —
defeating the single-shared-manifest anti-drift guarantee. `bootstrap.sh` also
reads with `IFS=$' \t\r'` as defense-in-depth.

Verify: `cat .gitattributes`

No commit in this task — the repo does not exist yet.

---

### Task 2: Create the manifest `scripts/repos.txt` (D5)

**Files:**
- Create: `d:\Projects\EnNam\ennam.kg\scripts\repos.txt`

- [ ] **Step 1: Create the file with this exact content**

```
# dir                  url                                              branch
ennam.kg.go            git@github.com:En-Nam/ennam.kg.go.git            main
ennam.kg.python        git@github.com:En-Nam/ennam.kg.python.git        main
ennam.kg.next          git@github.com:En-Nam/ennam.kg.next.git          main
ennam.kg.requirements  git@github.com:En-Nam/ennam.kg.requirements.git  main
```

- [ ] **Step 2: Verify**

Run: `cat scripts/repos.txt`
Expected: header comment line + 4 repo lines, whitespace-separated.

---

### Task 3: Create `scripts/bootstrap.sh` (D2, D3, D4, D6)

**Files:**
- Create: `d:\Projects\EnNam\ennam.kg\scripts\bootstrap.sh`

- [ ] **Step 1: Create the file with this exact content**

```bash
#!/usr/bin/env bash
# Bootstrap: clone all Ennam KG sub-repos listed in scripts/repos.txt.
# Idempotent, best-effort. Re-running is safe.
# Spec: docs/superpowers/specs/2026-05-19-workspace-meta-repo-design.md
set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd "$script_dir/.." && pwd)"
manifest="$script_dir/repos.txt"

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: git not found on PATH." >&2
  exit 1
fi
if [ ! -f "$manifest" ]; then
  echo "ERROR: manifest not found: $manifest" >&2
  exit 1
fi

cloned=0; skipped=0; failed=0

while IFS=$' \t\r' read -r dir url branch _rest || [ -n "${dir:-}" ]; do
  case "${dir:-}" in ''|'#'*) dir=""; continue ;; esac
  if [ -z "${url:-}" ]; then
    echo "WARN: bad manifest line for '$dir' (missing url), skipping" >&2
    failed=$((failed+1)); dir=""; continue
  fi
  branch="${branch:-main}"
  target="$root_dir/$dir"

  if [ -d "$target/.git" ]; then
    echo "skip   $dir (already a git repo)"
    skipped=$((skipped+1)); dir=""; continue
  fi
  if [ -e "$target" ]; then
    echo "FAIL   $dir (path exists but is not a git repo; not touching it)" >&2
    failed=$((failed+1)); dir=""; continue
  fi

  echo "clone  $dir <- $url ($branch)"
  if git clone -b "$branch" "$url" "$target"; then
    cloned=$((cloned+1))
  else
    echo "FAIL   $dir (git clone failed; check SSH access to GitHub En-Nam org)" >&2
    failed=$((failed+1))
  fi
  dir=""
done < "$manifest"

echo "----"
echo "summary: cloned=$cloned skipped=$skipped failed=$failed"
[ "$failed" -eq 0 ] || exit 1
```

- [ ] **Step 2: Mark the file executable (preserved later via git)**

Run: `chmod +x scripts/bootstrap.sh`
Expected: no output, exit 0.

- [ ] **Step 3: Syntax-check the script (no execution)**

Run: `bash -n scripts/bootstrap.sh && echo SYNTAX_OK`
Expected: `SYNTAX_OK`

No commit yet (repo does not exist until Task 8).

---

### Task 4: Create `scripts/bootstrap.ps1` (D2, D3, D4, D6 — parity with `.sh`)

**Files:**
- Create: `d:\Projects\EnNam\ennam.kg\scripts\bootstrap.ps1`

- [ ] **Step 1: Create the file with this exact content**

```powershell
# Bootstrap: clone all Ennam KG sub-repos listed in scripts/repos.txt.
# Idempotent, best-effort. Re-running is safe.
# Spec: docs/superpowers/specs/2026-05-19-workspace-meta-repo-design.md

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir   = Split-Path -Parent $scriptDir
$manifest  = Join-Path $scriptDir 'repos.txt'

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host 'ERROR: git not found on PATH.'; exit 1
}
if (-not (Test-Path -LiteralPath $manifest)) {
    Write-Host "ERROR: manifest not found: $manifest"; exit 1
}

$cloned = 0; $skipped = 0; $failed = 0

foreach ($line in Get-Content -LiteralPath $manifest) {
    $trimmed = $line.Trim()
    if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
    $parts  = $trimmed -split '\s+'
    $dir    = $parts[0]
    $url    = if ($parts.Count -ge 2) { $parts[1] } else { '' }
    $branch = if ($parts.Count -ge 3 -and $parts[2]) { $parts[2] } else { 'main' }

    if ($url -eq '') {
        Write-Host "WARN: bad manifest line for '$dir' (missing url), skipping"
        $failed++; continue
    }
    $target = Join-Path $rootDir $dir

    if (Test-Path -LiteralPath (Join-Path $target '.git')) {
        Write-Host "skip   $dir (already a git repo)"; $skipped++; continue
    }
    if (Test-Path -LiteralPath $target) {
        Write-Host "FAIL   $dir (path exists but is not a git repo; not touching it)"
        $failed++; continue
    }

    Write-Host "clone  $dir <- $url ($branch)"
    & git clone -b $branch $url $target
    if ($LASTEXITCODE -eq 0) {
        $cloned++
    } else {
        Write-Host "FAIL   $dir (git clone failed; check SSH access to GitHub En-Nam org)"
        $failed++
    }
}

Write-Host '----'
Write-Host "summary: cloned=$cloned skipped=$skipped failed=$failed"
if ($failed -gt 0) { exit 1 } else { exit 0 }
```

- [ ] **Step 2: Parse-check the script (no execution)**

Run:
```
powershell -NoProfile -Command "$null=[System.Management.Automation.Language.Parser]::ParseFile('scripts/bootstrap.ps1',[ref]$null,[ref]$null); if($?){'PARSE_OK'}"
```
Expected: `PARSE_OK`

No commit yet.

---

### Task 5: Verify both bootstrap scripts against a throwaway local git fixture

This is the behavioral test: deterministic, no network, nothing committed. It proves the **clone**, **idempotent skip**, and **non-git-dir failure + non-zero exit** paths, and `.sh`/`.ps1` parity (D6).

**Files:** none created/modified (temp dirs only, cleaned up).

- [ ] **Step 1: Run the Bash fixture test for `bootstrap.sh`**

Run (single block):
```bash
set -e
tmp=$(mktemp -d); ws="$tmp/ws"
git init -q --bare "$tmp/remote.git"
src=$(mktemp -d)
git -C "$src" init -q
git -C "$src" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
git -C "$src" branch -M main
git -C "$src" remote add origin "$tmp/remote.git"
git -C "$src" push -q origin main
mkdir -p "$ws/scripts"
cp scripts/bootstrap.sh "$ws/scripts/"
printf '# test manifest\nsub  %s  main\n' "$tmp/remote.git" > "$ws/scripts/repos.txt"

echo "--- run 1 (expect clone) ---"
bash "$ws/scripts/bootstrap.sh"; echo "exit=$?"
[ -d "$ws/sub/.git" ] && echo "OK cloned"
[ "$(git -C "$ws/sub" branch --show-current)" = main ] && echo "OK on main"

echo "--- run 2 (expect skip, exit 0) ---"
bash "$ws/scripts/bootstrap.sh" | grep -q 'skipped=1' && echo "OK idempotent"

echo "--- run 3 (non-git dir => fail, exit 1) ---"
rm -rf "$ws/sub"; mkdir "$ws/sub"; : > "$ws/sub/foo"
set +e; bash "$ws/scripts/bootstrap.sh"; rc=$?; set -e
[ "$rc" -ne 0 ] && echo "OK fail-exit ($rc)"

rm -rf "$tmp" "$src"
echo "BOOTSTRAP_SH_VERIFIED"
```
Expected to print, in order: `OK cloned`, `OK on main`, `OK idempotent`, `OK fail-exit (1)`, `BOOTSTRAP_SH_VERIFIED`.

- [ ] **Step 2: Run the PowerShell fixture test for `bootstrap.ps1`**

Run (single block):
```bash
set -e
tmp=$(mktemp -d); ws="$tmp/ws"
git init -q --bare "$tmp/remote.git"
src=$(mktemp -d)
git -C "$src" init -q
git -C "$src" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
git -C "$src" branch -M main
git -C "$src" remote add origin "$tmp/remote.git"
git -C "$src" push -q origin main
mkdir -p "$ws/scripts"
cp scripts/bootstrap.ps1 "$ws/scripts/"
printf '# test manifest\nsub  %s  main\n' "$tmp/remote.git" > "$ws/scripts/repos.txt"

echo "--- run 1 (expect clone) ---"
powershell -NoProfile -File "$ws/scripts/bootstrap.ps1"; echo "exit=$?"
[ -d "$ws/sub/.git" ] && echo "OK cloned"

echo "--- run 2 (expect skip) ---"
powershell -NoProfile -File "$ws/scripts/bootstrap.ps1" | grep -q 'skipped=1' && echo "OK idempotent"

echo "--- run 3 (non-git dir => exit 1) ---"
rm -rf "$ws/sub"; mkdir "$ws/sub"; : > "$ws/sub/foo"
powershell -NoProfile -File "$ws/scripts/bootstrap.ps1"; rc=$?
[ "$rc" -ne 0 ] && echo "OK fail-exit ($rc)"

rm -rf "$tmp" "$src"
echo "BOOTSTRAP_PS1_VERIFIED"
```
Expected to print: `OK cloned`, `OK idempotent`, `OK fail-exit (1)`, `BOOTSTRAP_PS1_VERIFIED`.

- [ ] **Step 3: Confirm parity**

Both scripts produced the same `cloned/skipped/failed` outcomes from the same manifest shape. If either `*_VERIFIED` line is missing, stop and debug with `superpowers:systematic-debugging` before continuing — do not proceed to git init with an unverified bootstrap.

---

### Task 6: Promote `.claude/settings.local.json` → `.claude/settings.json` (D7)

**Files:**
- Create: `d:\Projects\EnNam\ennam.kg\.claude\settings.json`
- Keep (now git-ignored): `.claude/settings.local.json`

- [ ] **Step 1: Copy current local settings to the shared file, verbatim**

Run: `cp .claude/settings.local.json .claude/settings.json`
Expected: no output, exit 0.

- [ ] **Step 2: Verify the shared file content**

Run: `cat .claude/settings.json`
Expected: identical JSON to `.claude/settings.local.json` (permissions allowlist + chrome-devtools MCP server). `.claude/settings.local.json` remains on disk and is excluded by Task 1's `.gitignore`.

No commit yet.

---

### Task 7: Create `README.md` (human onboarding entrypoint, §5.5)

**Files:**
- Create: `d:\Projects\EnNam\ennam.kg\README.md`

- [ ] **Step 1: Create the file with this exact content**

````markdown
# Ennam KG — Workspace

This is the **workspace meta-repo**. It carries shared config and the Serena
knowledge store. The actual code lives in four independent repos that are
cloned at runtime — they are intentionally **not** part of this repo.

## Prerequisites

- `git`
- An SSH key added to your GitHub account, with access to the `En-Nam` org
  (test: `ssh -T git@github.com` should greet you by username).

## Setup (2 steps)

```bash
# 1. Clone this workspace repo
git clone git@github.com:En-Nam/ennam.kg.workspace.git ennam.kg
cd ennam.kg

# 2. Clone all sub-repos onto main
./scripts/bootstrap.sh        # macOS / Linux / Git Bash
.\scripts\bootstrap.ps1       # Windows PowerShell
```

After step 2 you have `ennam.kg.go/`, `ennam.kg.python/`, `ennam.kg.next/`,
`ennam.kg.requirements/` checked out on `main`. Create your own feature
branches from there.

`bootstrap` is idempotent — re-run it any time; existing repos are skipped.
To add a sub-repo later, add one line to `scripts/repos.txt`.

## Secrets

`.env` and `SECRET.md` are git-ignored and never shared. Copy `.env.example`
to `.env` and fill in values locally (ask the team lead for credentials).
````

- [ ] **Step 2: Verify**

Run: `cat README.md`
Expected: the content above, with both `.sh` and `.ps1` invocations shown.

---

### Task 8: `git init` + pre-commit safety gate (§5.6, §7, §8 secret hygiene)

**Files:** none created — initializes git, stages, verifies. **No commit in this task.**

- [ ] **Step 1: Initialize the repo and stage everything**

Run:
```bash
git init
git add -A
```
Expected: `Initialized empty Git repository ...`; no fatal errors. (Sub-repo dirs are git-ignored, so no "embedded repository" warning should appear. If one does, stop — `.gitignore` is wrong.)

- [ ] **Step 2: GATE — prove secrets and sub-repos are NOT staged**

Run:
```bash
git check-ignore .env SECRET.md ennam.kg.go ennam.kg.python ennam.kg.next ennam.kg.requirements .claude/settings.local.json .ruff_cache .playwright-mcp
```
Expected: every one of those paths is echoed back (each is ignored). If any path is **missing** from the output, STOP — fix `.gitignore` (Task 1) and redo Task 8. Do not proceed.

- [ ] **Step 3: GATE — prove no secret/sub-repo path is staged**

Run:
```bash
git diff --cached --name-only | grep -E '(^|/)(\.env$|SECRET\.md$|settings\.local\.json$)|^ennam\.kg\.(go|python|next|requirements)/' && echo "LEAK_DETECTED" || echo "GATE_PASS_NO_LEAK"
```
Expected: `GATE_PASS_NO_LEAK`. If `LEAK_DETECTED` prints, STOP immediately, fix `.gitignore`, run `git rm -r --cached <path>`, redo from Step 1. Never commit on `LEAK_DETECTED`.

- [ ] **Step 4: Confirm the intended shared assets ARE staged**

Run:
```bash
git diff --cached --name-only | grep -E '^(CLAUDE\.md|AGENTS\.md|README\.md|\.gitignore|\.gitattributes|scripts/repos\.txt|scripts/bootstrap\.sh|scripts/bootstrap\.ps1|\.claude/settings\.json|\.serena/memories/INDEX\.md|docs/superpowers/specs/2026-05-19-workspace-meta-repo-design\.md)$' | sort
```
Expected: all 11 paths listed. If any is missing, stop and investigate before committing.

- [ ] **Step 5: Preserve the executable bit on the Bash script**

Run:
```bash
git update-index --chmod=+x scripts/bootstrap.sh
git ls-files --stage scripts/bootstrap.sh
```
Expected: mode `100755` for `scripts/bootstrap.sh`.

---

### Task 9: Initial commit (resolves spec §8 commit-deferral)

**Files:** none — commits the staged tree from Task 8.

- [ ] **Step 1: Create the initial commit**

Run:
```bash
git commit -m "$(cat <<'EOF'
chore: initialize ennam.kg.workspace meta-repo

Shareable root: CLAUDE.md, AGENTS.md, docs/, scripts/, seeds/,
docker-compose*, Serena knowledge store, .claude/settings.json.

Adds scripts/repos.txt manifest + cross-platform bootstrap
(bootstrap.sh / bootstrap.ps1) so the four sub-repos clone onto
main in one command. .gitignore excludes sub-repos, secrets
(.env, SECRET.md), local config, and caches.

Spec: docs/superpowers/specs/2026-05-19-workspace-meta-repo-design.md
Plan: docs/superpowers/plans/2026-05-19-workspace-meta-repo.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
Expected: a commit is created. `git log --oneline -1` shows the message.

- [ ] **Step 2: Re-verify nothing secret landed in the commit**

Run:
```bash
git show --stat --name-only HEAD | grep -E '(\.env$|SECRET\.md$|settings\.local\.json$|^ennam\.kg\.(go|python|next|requirements)/)' && echo "POST_COMMIT_LEAK" || echo "COMMIT_CLEAN"
```
Expected: `COMMIT_CLEAN`. If `POST_COMMIT_LEAK`, STOP — the commit must be amended/reset and `.gitignore` fixed before any push. Do not push.

---

### Task 10: Create the GitHub remote and push (owner-gated, outward-facing)

> **Confirmation required before this task.** Pushing publishes the repo to GitHub. Proceed only after Task 9 Step 2 printed `COMMIT_CLEAN` and the user has explicitly approved the push.

**Files:** none.

- [ ] **Step 1: Check whether the remote already exists**

Run: `git ls-remote git@github.com:En-Nam/ennam.kg.workspace.git 2>&1 | head -1`
- If it lists refs or returns empty with exit 0 → repo exists, go to Step 3.
- If it errors with `Repository not found` → repo must be created, go to Step 2.

- [ ] **Step 2: Create the empty GitHub repo (only if Step 1 said "not found")**

Preferred (if `gh` is authenticated):
```bash
gh repo create En-Nam/ennam.kg.workspace --private
```
Expected: `✓ Created repository En-Nam/ennam.kg.workspace`.

If `gh` is unavailable: ask the user to create an **empty** private repo
`En-Nam/ennam.kg.workspace` on github.com (no README/license), then continue.

- [ ] **Step 3: Wire the remote and push `main`**

Run:
```bash
git remote add origin git@github.com:En-Nam/ennam.kg.workspace.git
git branch -M main
git push -u origin main
```
Expected: branch `main` pushed; upstream set to `origin/main`.

- [ ] **Step 4: Confirm the remote tree has no secrets**

Run:
```bash
git ls-tree -r --name-only origin/main | grep -E '(\.env$|SECRET\.md$|settings\.local\.json$|^ennam\.kg\.(go|python|next|requirements)/)' && echo "REMOTE_LEAK" || echo "REMOTE_CLEAN"
```
Expected: `REMOTE_CLEAN`.

---

### Task 11: Final verification evidence + mandatory checkpoint/knowledge writeback

**Files:**
- Modify (append): `d:\Projects\EnNam\ennam.kg\.serena\checkpoint\claude-opus-2026-05-19.md`
- Create: `d:\Projects\EnNam\ennam.kg\.serena\memories\decisions\workspace-meta-repo.md`
- Modify: `d:\Projects\EnNam\ennam.kg\.serena\memories\INDEX.md`

- [ ] **Step 1: Capture the consolidated verification evidence**

Run:
```bash
echo "== gitignore proof ==" && git check-ignore .env SECRET.md ennam.kg.go
echo "== tracked count ==" && git ls-files | wc -l
echo "== bootstrap syntax ==" && bash -n scripts/bootstrap.sh && echo sh_ok
```
Expected: the three ignored paths echoed; a non-zero tracked-file count; `sh_ok`. Record this output as the Phase 5 evidence.

- [ ] **Step 2: Append the session checkpoint (CLAUDE.md mandatory rule; file already exists today — append, do not overwrite)**

Append a section to `.serena/checkpoint/claude-opus-2026-05-19.md`:
```markdown

## Session: workspace meta-repo (append)
### What was done
- Initialized ennam.kg.workspace meta-repo; added .gitignore, scripts/repos.txt, bootstrap.sh/.ps1, README.md, .claude/settings.json
- Verified bootstrap (clone/idempotent/fail paths) against local fixture; pushed main
### Files changed
- NEW: .gitignore, scripts/repos.txt, scripts/bootstrap.sh, scripts/bootstrap.ps1, README.md, .claude/settings.json
- NEW: docs/superpowers/{specs,plans}/2026-05-19-workspace-meta-repo*
### Current state
- Workspace repo live at git@github.com:En-Nam/ennam.kg.workspace.git, main pushed, secrets verified excluded
### Next steps
- Team onboards via README 2-step flow
### Blockers / Risks
- None (or: note if KG MCP was unavailable for writeback)
```

- [ ] **Step 3: Record the decision in Serena (CLAUDE.md write protocol) and update INDEX**

Create `.serena/memories/decisions/workspace-meta-repo.md`:
```markdown
# Decision: Workspace meta-repo + bootstrap

Root is now git repo `En-Nam/ennam.kg.workspace`. Sub-repos are NOT
submodules — cloned at runtime by scripts/bootstrap.{sh,ps1} from the
scripts/repos.txt manifest, onto main. Rationale: submodules pin commits,
conflicting with the "main as standard, devs branch freely" model.
Secrets (.env, SECRET.md) and sub-repo dirs are git-ignored.
Spec: docs/superpowers/specs/2026-05-19-workspace-meta-repo-design.md
```
Then add this line under the decisions section of `.serena/memories/INDEX.md`:
`- decisions/workspace-meta-repo.md — root is a shared git repo; sub-repos cloned via bootstrap manifest, not submodules`

- [ ] **Step 4: Commit the checkpoint + knowledge writeback**

Run:
```bash
git add .serena/checkpoint/claude-opus-2026-05-19.md .serena/memories/decisions/workspace-meta-repo.md .serena/memories/INDEX.md docs/superpowers/plans/2026-05-19-workspace-meta-repo.md
git commit -m "docs: checkpoint + decision record for workspace meta-repo

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push
```
Expected: second commit pushed to `origin/main`.

> If the Ennam KG MCP server is reachable, also `kg_store_decision` for the meta-repo decision (CLAUDE.md knowledge-source priority). If unreachable, the Serena decision file above is the fallback — note the KG outage in the checkpoint.

---

## Self-Review

**1. Spec coverage:**

| Spec item | Task |
|-----------|------|
| D1 remote `ennam.kg.workspace` | Task 10 |
| D2 manifest + scripts (not submodules) | Tasks 2, 3, 4 |
| D3 cross-platform `.ps1` + `.sh` | Tasks 3, 4 |
| D4 clone at `main`, devs branch | Tasks 3, 4 (`git clone -b main`); README Task 7 |
| D5 manifest at `scripts/repos.txt` | Task 2 |
| D6 best-effort + summary + exit code | Tasks 3, 4 logic; Task 5 verifies |
| D7 promote `.claude/settings.json` | Task 6 |
| §5.3 `.gitignore` | Task 1 |
| §5.5 `README.md` | Task 7 |
| §5.6 tracked-asset set | Task 8 Step 4 |
| §7 verification (functional/idempotent/gitignore proof) | Tasks 5, 8, 11 |
| §8 commit deferral | Task 9 |
| §8 remote may not exist | Task 10 Steps 1–2 |
| §8 secret hygiene before push | Task 8 gate, Task 9 Step 2, Task 10 Step 4 |

No spec item is unmapped.

**2. Placeholder scan:** No `TBD`/`TODO`/"add error handling"/"similar to Task N". Every code and command step contains literal content. ✔

**3. Type/name consistency:** Manifest columns `dir url branch` are identical across `repos.txt` (Task 2), `bootstrap.sh` (Task 3), `bootstrap.ps1` (Task 4), and the fixture tests (Task 5). Summary token `summary: cloned=… skipped=… failed=…` and the grep `skipped=1` match between Tasks 3/4 and Task 5. Path `scripts/repos.txt` consistent throughout. ✔

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-19-workspace-meta-repo.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
