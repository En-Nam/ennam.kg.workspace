# Superpowers Workflow Adoption & Serena Restructure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Ouroboros with Superpowers workflow, add AGENTS.md 12-rule template, restructure Serena memory directory.

**Architecture:** Two-file system (AGENTS.md = portable rules, CLAUDE.md = project-specific workflow). Serena restructured into 7 clear directories with INDEX.md entry point.

**Tech Stack:** Markdown files, bash (file operations), git.

**Spec:** `docs/superpowers/specs/2026-05-11-superpowers-workflow-adoption-design.md`

---

### Task 1: Create root AGENTS.md

**Files:**
- Create: `AGENTS.md`

- [ ] **Step 1: Create the file**

```markdown
# AGENTS.md — Agent Behavioral Rules

These rules apply to every agent and every task in this project
unless explicitly overridden by the user.
Bias: caution over speed on non-trivial work.
Use judgment on trivial tasks.

## Rule 1 — Think Before Coding
...(full content from approved Section 1)
```

- [ ] **Step 2: Verify file exists and is readable**

Run: `cat AGENTS.md | head -5`
Expected: First 5 lines of the file visible.

---

### Task 2: Rewrite root CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` — remove Ouroboros (lines 62-108), add Superpowers workflow + KG priority + Serena protocol

- [ ] **Step 1: Remove Ouroboros section**

Delete everything from `<!-- ooo:START -->` to `<!-- ooo:END -->` (lines 62-108).

- [ ] **Step 2: Add @AGENTS.md reference**

Add `@AGENTS.md` after `## Workflow Rules` heading.

- [ ] **Step 3: Add Superpowers Workflow section**

Add the 7-phase workflow with task complexity guide (from approved Section 2).

- [ ] **Step 4: Add Knowledge Source Priority section**

Add KG-first retrieval protocol (from approved addition to Section 2).

- [ ] **Step 5: Keep Mandatory Session Checkpoint**

Verify checkpoint section is preserved (lines 29-59 of current file).

- [ ] **Step 6: Add Serena Memory Protocol section**

Add read/write protocol with rules (from approved Section 4 addition).

- [ ] **Step 7: Verify final CLAUDE.md**

Run: `wc -l CLAUDE.md`
Expected: ~150-180 lines (was 108 with Ouroboros).

---

### Task 3: Edit per-service CLAUDE.md files

**Files:**
- Modify: `ennam.kg.go/CLAUDE.md` line 1
- Modify: `ennam.kg.python/CLAUDE.md` line 1
- Modify: `ennam.kg.requirements/CLAUDE.md` line 1
- Modify: `ennam.kg.next/CLAUDE.md` line 5

- [ ] **Step 1: Add @../AGENTS.md to Go CLAUDE.md**

Add `@../AGENTS.md` as the first line of `ennam.kg.go/CLAUDE.md`.

- [ ] **Step 2: Add @../AGENTS.md to Python CLAUDE.md**

Add `@../AGENTS.md` as the first line of `ennam.kg.python/CLAUDE.md`.

- [ ] **Step 3: Add @../AGENTS.md to Requirements CLAUDE.md**

Add `@../AGENTS.md` as the first line of `ennam.kg.requirements/CLAUDE.md`.

- [ ] **Step 4: Fix AGENTS.md reference in NextJS CLAUDE.md**

Change `@AGENTS.md` to `@../AGENTS.md` in `ennam.kg.next/CLAUDE.md` line 5.

- [ ] **Step 5: Verify all references**

Run: `grep -r "@.*AGENTS.md" --include="CLAUDE.md" .`
Expected: 4 files referencing `@../AGENTS.md` + root referencing `@AGENTS.md`.

---

### Task 4: Create Serena directory structure

**Files:**
- Create directories: `decisions/`, `services/`, `backlog/`, `comms/active/`, `comms/resolved/`, `archive/phases/`, `archive/qa-runs/`

- [ ] **Step 1: Create new directories**

```bash
cd .serena/memories
mkdir -p decisions services backlog comms/active comms/resolved archive/phases archive/qa-runs
```

- [ ] **Step 2: Verify structure**

```bash
find .serena/memories -type d | sort
```

---

### Task 5: Migrate comms — all 27 files to resolved

**Files:**
- Move: `memories/comms/*.md` → `memories/comms/resolved/`

- [ ] **Step 1: Move all existing comms files**

```bash
cd .serena/memories
mv comms/*.md comms/resolved/ 2>/dev/null
```

Note: The old `comms/` dir becomes the parent of `active/` and `resolved/`.

- [ ] **Step 2: Verify**

```bash
ls .serena/memories/comms/resolved/ | wc -l
```
Expected: 27 files.

---

### Task 6: Consolidate service state files

**Files:**
- Read + consolidate: `frontend/*` + `nextjs-dashboard/*` → `services/nextjs-dashboard.md`
- Read + consolidate: `python/*` + `python-worker/*` → `services/python-worker.md`
- Move: `go-api/*` → `services/go-api.md`

- [ ] **Step 1: Read all source files for NextJS**

Read `frontend/react-force-graph-3d-lessons.md` and `nextjs-dashboard/state-2026-05-08.md`.

- [ ] **Step 2: Create consolidated services/nextjs-dashboard.md**

Merge content from both files into one service state file.

- [ ] **Step 3: Read all source files for Python**

Read `python/phase2-architecture.md`, `python/phase2-blocking-points.md`, `python/phase2-implementation-status.md`, and `python-worker/state-2026-05-08.md`.

- [ ] **Step 4: Create consolidated services/python-worker.md**

Merge content from all 4 files into one service state file.

- [ ] **Step 5: Move Go API state**

```bash
cp .serena/memories/go-api/state-2026-05-08.md .serena/memories/services/go-api.md
```

- [ ] **Step 6: Remove old directories**

```bash
rm -rf .serena/memories/frontend .serena/memories/nextjs-dashboard
rm -rf .serena/memories/python .serena/memories/python-worker
rm -rf .serena/memories/go-api
```

---

### Task 7: Migrate project/ files

**Files:**
- Move to `decisions/`: technical-decisions.md, architecture-assessment-organization-layer.md, overview.md, knowledge-model.md, mcp-api-spec.md, go-backend-status.md, python-worker-architecture-final.md, phase3-design-spec.md, phase5-smart-context-design.md, phase6-multi-source-ingestion.md
- Move to `backlog/`: fe-action-required-* (9), development-plan.md, fix-kg-generation-progress-visibility.md, be-change-request-datasource-sync-status.md, phase5-ba021-work-plan.md, bug-kg-nodes-missing-ai-description.md, issues/sse-block-ordering-bug.md
- Move to `archive/phases/`: checkpoint-* (5), phase*-progress* (4), fe-done-* (3), phase2-fe-api-contract-resolution.md, phase2-go-api-change-request-frontend.md, phase2-ui-design-complete.md, phase2-wave1-go-implementation.md, api-documentation.md, lessons-learned-intent-parse-debugging.md, mssql-support-plan.md, python-worker-refactor-ai-engine.md, phase5-claude-oauth-integration-requirement.md, rename-knowledge-graph-to-schema-graph.md, bug-kg-generation-dual-entry-point.md (FIXED)

- [ ] **Step 1: Move decisions**

```bash
cd .serena/memories
for f in technical-decisions.md architecture-assessment-organization-layer.md \
  overview.md knowledge-model.md mcp-api-spec.md go-backend-status.md \
  python-worker-architecture-final.md phase3-design-spec.md \
  phase5-smart-context-design.md phase6-multi-source-ingestion.md; do
  mv "project/$f" decisions/ 2>/dev/null
done
```

- [ ] **Step 2: Move backlog items from project/**

```bash
cd .serena/memories
for f in development-plan.md fix-kg-generation-progress-visibility.md \
  be-change-request-datasource-sync-status.md phase5-ba021-work-plan.md \
  bug-kg-nodes-missing-ai-description.md; do
  mv "project/$f" backlog/ 2>/dev/null
done
```

- [ ] **Step 3: Move fe-action-required files to backlog**

```bash
cd .serena/memories
mv project/fe-action-required-*.md backlog/ 2>/dev/null
```

- [ ] **Step 4: Move issues to backlog**

```bash
mv .serena/memories/issues/sse-block-ordering-bug.md .serena/memories/backlog/
rmdir .serena/memories/issues 2>/dev/null
```

- [ ] **Step 5: Move archive items**

```bash
cd .serena/memories
mv project/checkpoint-*.md archive/phases/ 2>/dev/null
mv project/phase2-frontend-sprint1-progress.md archive/phases/ 2>/dev/null
mv project/phase2-gap-progress.md archive/phases/ 2>/dev/null
mv project/phase3-frontend-progress.md archive/phases/ 2>/dev/null
mv project/phase3-implementation-progress.md archive/phases/ 2>/dev/null
mv project/phase4-implementation-progress.md archive/phases/ 2>/dev/null
mv project/fe-done-*.md archive/phases/ 2>/dev/null
mv project/fe-integration-sse-realtime-progress.md archive/phases/ 2>/dev/null
mv project/phase2-fe-api-contract-resolution.md archive/phases/ 2>/dev/null
mv project/phase2-go-api-change-request-frontend.md archive/phases/ 2>/dev/null
mv project/phase2-ui-design-complete.md archive/phases/ 2>/dev/null
mv project/phase2-wave1-go-implementation.md archive/phases/ 2>/dev/null
mv project/api-documentation.md archive/phases/ 2>/dev/null
mv project/lessons-learned-intent-parse-debugging.md archive/phases/ 2>/dev/null
mv project/mssql-support-plan.md archive/phases/ 2>/dev/null
mv project/python-worker-refactor-ai-engine.md archive/phases/ 2>/dev/null
mv project/phase5-claude-oauth-integration-requirement.md archive/phases/ 2>/dev/null
mv project/rename-knowledge-graph-to-schema-graph.md archive/phases/ 2>/dev/null
mv project/bug-kg-generation-dual-entry-point.md archive/phases/ 2>/dev/null
```

- [ ] **Step 6: Move project/archive/ contents**

```bash
mv .serena/memories/project/archive/*.md .serena/memories/archive/phases/ 2>/dev/null
rmdir .serena/memories/project/archive 2>/dev/null
```

- [ ] **Step 7: Remove empty project/ directory**

```bash
# Check if anything remains
ls .serena/memories/project/
# If empty:
rmdir .serena/memories/project
```

---

### Task 8: Migrate QA files

**Files:**
- Keep in `qa/`: strategy-and-framework.md, automation-playbook.md, reporting-template.md, test-scope-by-phase.md, mcp-tools-rules.md, chat-deep-test-plan.md
- Move to `archive/qa-runs/`: all dated test result files (25+ files)

- [ ] **Step 1: Move dated QA runs to archive**

```bash
cd .serena/memories/qa
for f in *-2026-04-*.md *-2026-05-*.md; do
  mv "$f" ../archive/qa-runs/ 2>/dev/null
done
# Also move specific non-dated but result files
mv anthropic-oauth-limitation.md ../archive/qa-runs/ 2>/dev/null
```

- [ ] **Step 2: Verify QA directory has only strategy files**

```bash
ls .serena/memories/qa/
```
Expected: ~6 files (strategy, playbook, template, scope, mcp-tools, test-plan).

---

### Task 9: Clean up misc files

- [ ] **Step 1: Move suggested_commands.md to conventions**

```bash
mv .serena/memories/suggested_commands.md .serena/memories/conventions/
```

- [ ] **Step 2: Remove empty checkpoint dir in memories**

```bash
rmdir .serena/memories/checkpoint 2>/dev/null
```

---

### Task 10: Create INDEX.md

**Files:**
- Create: `.serena/memories/INDEX.md`

- [ ] **Step 1: Create INDEX.md with directory map**

Write INDEX.md with:
- Quick reference to each directory
- Service files table with descriptions
- Instructions for agents on read/write protocol

---

### Task 11: Update auto-memory

**Files:**
- Modify: `~/.claude/projects/.../memory/project_overview.md`

- [ ] **Step 1: Update project overview memory**

Reflect: workflow transitioned from Ouroboros to Superpowers. Serena restructured.

---

### Task 12: Final verification

- [ ] **Step 1: Verify directory structure**

```bash
find .serena/memories -type d | sort
```

- [ ] **Step 2: Verify no orphaned files**

```bash
find .serena/memories -maxdepth 1 -type f
```
Expected: Only `INDEX.md` at root level.

- [ ] **Step 3: Verify CLAUDE.md has no Ouroboros references**

```bash
grep -i "ouroboros\|ooo:" CLAUDE.md
```
Expected: No matches.

- [ ] **Step 4: Verify AGENTS.md is referenced by all services**

```bash
grep -r "@.*AGENTS.md" --include="CLAUDE.md" .
```
Expected: 5 matches.
