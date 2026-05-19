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
