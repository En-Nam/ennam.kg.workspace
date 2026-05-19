# Design: Superpowers Workflow Adoption & Serena Restructure

**Date**: 2026-05-11
**Status**: Approved
**Scope**: Ennam KG Platform only (expand to other projects after validation)

## Summary

Replace Ouroboros with Superpowers as the agent workflow engine. Introduce
tinbeta/skills AGENTS.md 12-rule template as behavioral foundation. Restructure
Serena memory directory for clarity and add memory protocol rules.

## Motivation

- Ouroboros is monolithic (Interview -> Seed -> Execute -> Evaluate). Superpowers
  is modular — each skill is invoked on-demand, better fit for varied task complexity.
- Serena directory has grown to 130+ files with duplicate directories, misplaced
  checkpoints, expired comms, and no index — agents waste tokens scanning.
- No memory protocol exists — agents create files arbitrarily, structure degrades.

## Design Decisions

### Decision 1: Two-File Architecture (Approach A)

**AGENTS.md** = 12 behavioral rules (project-agnostic, portable)
**CLAUDE.md** = Superpowers workflow phases + KG priority + Serena protocol (project-specific)

Rationale: When expanding to SalonBookly or other projects, copy AGENTS.md unchanged,
write new CLAUDE.md for that project's context.

### Decision 2: Structured Workflow with Skip

7 phases: Understand -> Plan -> Isolate -> Implement -> Verify -> Review -> Complete.
Phases may be skipped for trivial tasks except Phase 5 (Verify) which is mandatory.
Agents must state which phases they skip and why.

### Decision 3: KG-First Context Retrieval

Agents query Ennam KG MCP server FIRST for decisions, architecture, function context.
Fallback to Serena when KG MCP is unavailable. Fallback to source code as last resort.

### Decision 4: Serena Directory Restructure

Consolidate 130+ files into clean structure with INDEX.md entry point.

---

## Part 1: AGENTS.md (Root)

New file at `ennam.kg/AGENTS.md`. Contains 12 behavioral rules from tinbeta/skills.
Project-agnostic — no Ennam-specific content.

```
Rule 1  — Think Before Coding
Rule 2  — Simplicity First
Rule 3  — Surgical Changes
Rule 4  — Goal-Driven Execution
Rule 5  — Use the model only for judgment calls
Rule 6  — Context discipline
Rule 7  — Surface conflicts, don't average them
Rule 8  — Read before you write
Rule 9  — Tests verify intent, not just behavior
Rule 10 — Checkpoint after every significant step
Rule 11 — Match the codebase's conventions, even if you disagree
Rule 12 — Fail loud
```

Only change from original: Rule 6 renamed from "Token budgets are not advisory"
to "Context discipline" — Claude Code manages tokens internally, hard numbers
don't apply.

---

## Part 2: CLAUDE.md Workflow Section

Replaces the entire Ouroboros section (`<!-- ooo:START -->` to `<!-- ooo:END -->`).
Keeps existing sections: Project Overview, Sub-Projects, Documentation, Quick Start.

### Superpowers Workflow Phases

| Phase | Skill | Skippable | Output |
|-------|-------|-----------|--------|
| 1. Understand | `brainstorming` | Yes — if bug fix, typo, config | Approved design in `docs/superpowers/specs/` |
| 2. Plan | `writing-plans` | Yes — if single-file change | Implementation plan with success criteria |
| 3. Isolate | `using-git-worktrees` | Yes — if hotfix, docs-only | Isolated worktree or branch |
| 4. Implement | `test-driven-development`, `executing-plans`, `dispatching-parallel-agents`, `subagent-driven-development`, `systematic-debugging` | No | Working code with tests |
| 5. Verify | `verification-before-completion` | **NEVER** | Evidence of success criteria met |
| 6. Review | `requesting-code-review` | Yes — if docs/config only | Review feedback addressed |
| 7. Complete | `finishing-a-development-branch` | No | PR created or completion option presented |

On-demand skills (any phase):
- `systematic-debugging` — unexpected failures
- `receiving-code-review` — feedback from others
- `writing-skills` — creating/modifying workflow skills

### Task Complexity Guide

| Complexity | Example | Required Phases |
|-----------|---------|-----------------|
| Trivial | Fix typo, update config | Implement -> Verify |
| Simple | Single-file bug fix | Plan -> Implement -> Verify |
| Medium | New endpoint, component | Plan -> Implement -> Verify -> Review |
| Complex | Cross-service feature | ALL phases |

### Knowledge Source Priority

Query order (strict):
1. Ennam KG MCP — decisions, architecture, function context, discoveries
2. Serena memories — fallback when KG MCP is down or data not stored
3. Source code / git log — last resort for exact current implementation

When to query KG:
- Session start: `kg_get_context`
- Before coding: `kg_get_function_context`
- Before decisions: `kg_query` for prior decisions
- Unfamiliar code: `kg_query` for discoveries/architecture nodes

When to write back:
- Design decision made: `kg_store_decision`
- Non-obvious discovery: `kg_store_discovery`
- New concept defined: `kg_store_concept`
- Task completed: `kg_store_task`

Fallback: if KG MCP unreachable, log failure, use Serena, note in checkpoint.

### Mandatory Session Checkpoint

Unchanged from current protocol. Write to `.serena/checkpoint/<agent>-<YYYY-MM-DD>.md`
before ending session. Required content: what done, files changed, current state,
next steps, blockers.

### Serena Memory Protocol

Read protocol (session start):
1. `memories/INDEX.md` first
2. `services/<your-service>.md`
3. `comms/active/` for messages to you
4. `backlog/` for pending items in your domain

Write protocol:

| Action | Location | Naming |
|--------|----------|--------|
| Technical decision | `decisions/<topic>.md` | Descriptive topic |
| Service state update | `services/<service>.md` | Append/replace section |
| Flag work for other agent | `backlog/<service>-<topic>.md` | Prefix with target service |
| Ask another agent | `comms/active/<you>-to-<them>-<topic>.md` | |
| Respond to question | Append to existing file in `comms/active/` | |
| Close resolved thread | Move to `comms/resolved/` | |
| QA results | `qa/latest-results.md` (replace) | Archive old first |
| Historical data | `archive/<category>/` | |

Rules:
- Never create new top-level directories under `memories/`
- Never put files directly in `memories/` (always subdirectory)
- 1 file per service in `services/` — update, don't create siblings
- Delete backlog items when work is done
- Comms: respond in SAME file (append), move to resolved when done
- Update INDEX.md when adding files to `decisions/` or `services/`

---

## Part 3: Per-Service CLAUDE.md Changes

| File | Change |
|------|--------|
| `ennam.kg.go/CLAUDE.md` | Add `@../AGENTS.md` at top |
| `ennam.kg.python/CLAUDE.md` | Add `@../AGENTS.md` at top |
| `ennam.kg.requirements/CLAUDE.md` | Add `@../AGENTS.md` at top |
| `ennam.kg.next/CLAUDE.md` | Change `@AGENTS.md` to `@../AGENTS.md` |
| `ennam.kg.next/AGENTS.md` | Keep unchanged (Next.js framework warnings) |

---

## Part 4: Serena Directory Restructure

### New Structure

```
.serena/
├── checkpoint/                    # Session checkpoints (unchanged)
├── memories/
│   ├── INDEX.md                   # Entry point for agents
│   ├── conventions/               # Stable rules
│   │   ├── code-style.md
│   │   └── task-completion.md
│   ├── decisions/                 # Active technical decisions
│   ├── services/                  # 1 file per service (current state)
│   │   ├── go-api.md
│   │   ├── nextjs-dashboard.md
│   │   └── python-worker.md
│   ├── backlog/                   # Pending action items
│   ├── comms/
│   │   ├── active/                # Open inter-agent threads
│   │   └── resolved/              # Closed threads
│   ├── qa/                        # Strategy + latest results
│   └── archive/                   # Historical data
│       ├── phases/                # Completed phase checkpoints/progress
│       └── qa-runs/               # Dated QA test results
```

### Migration Plan

| Source | Action | Destination |
|--------|--------|-------------|
| `memories/comms/*` (27 files) | Move | `comms/resolved/` |
| `memories/frontend/*` + `memories/nextjs-dashboard/*` | Consolidate | `services/nextjs-dashboard.md` |
| `memories/python/*` + `memories/python-worker/*` | Consolidate | `services/python-worker.md` |
| `memories/go-api/*` | Move | `services/go-api.md` |
| `memories/project/checkpoint-*` (5 files) | Move | `archive/phases/` |
| `memories/project/phase*-progress*` | Move | `archive/phases/` |
| `memories/project/fe-done-*` (3 files) | Move | `archive/phases/` |
| `memories/project/fe-action-required-*` (9 files) | Move | `backlog/` |
| `memories/project/technical-decisions.md` | Move | `decisions/` |
| `memories/project/architecture-*` | Move | `decisions/` |
| `memories/project/bug-*`, `be-bug-*` | Check: resolved->archive, open->backlog | |
| `memories/project/rename-*` | Move | `decisions/` |
| `memories/project/overview.md` et al | Move | `decisions/` or `archive/` based on relevance |
| `memories/qa/` dated runs (30 files) | Move | `archive/qa-runs/` |
| `memories/qa/` strategy + playbook | Keep | `qa/` |
| `memories/issues/*` | Check: resolved->archive, open->backlog | |
| `memories/checkpoint/` (empty dir) | Delete | — |
| `memories/suggested_commands.md` | Move | `conventions/` or delete if stale |

### Ouroboros Removal

- Delete `<!-- ooo:START -->` to `<!-- ooo:END -->` from root CLAUDE.md
- User handles Ouroboros plugin uninstall separately (out of scope)

### Memory Update

Update `~/.claude/projects/.../memory/project_overview.md` to reflect
workflow transition from Ouroboros to Superpowers.

---

## Implementation Order

1. Create `AGENTS.md` (root)
2. Rewrite `CLAUDE.md` (root) — remove Ouroboros, add Superpowers workflow
3. Edit per-service CLAUDE.md files — add `@../AGENTS.md`
4. Create Serena directory structure (new dirs)
5. Migrate Serena files according to migration plan
6. Create `INDEX.md`
7. Consolidate service state files
8. Update auto-memory
