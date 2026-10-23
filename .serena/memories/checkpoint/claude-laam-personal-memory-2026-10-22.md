# Checkpoint: claude (LAAM personal memory v1) — 2026-10-22

## What was done
- Decision `mem:decisions/memory-allocation-2026-10-22` (LAAM owns personal memory; DAAB memory → business knowledge, deferred `mem:backlog/daab-business-knowledge-memory`); comms to orchestrator for global/ecosystem.
- Spec LAAM/docs/superpowers/specs/2026-10-22-laam-personal-memory-design.md (2 review rounds: adversarial + Opus code-level).
- Implemented by a Sonnet agent, reviewed by Opus (0 critical/high; 3 medium + 6 low fixed). Branch `task/LAAM/improve` (31 commits ahead of main incl. harness hardening), NOT pushed.
- Key design: memory_propose/memory_forget are read-kind tools added per turn (not INTERNAL_TOOLS); proposals never suspend the turn; sealed token → memory_proposal frame after the answer → POST /api/memory/confirm re-checks all; snapshot per conversation (chat_conversation.memorySnapshot); user-role data block ≤1200 chars; fail-closed outside-data warning; audit {action,id} only; log.ts strips Drizzle params.

## Verified (throwaway worktree of HEAD)
unit 6828 pass; integration 578/578; tsc clean; db:generate clean.

## Not done / next
- Migration 0030 NOT applied to dev DB; docker image not rebuilt (needs owner OK).
- Live eval of the 5 memory scenarios not run.
- Someone else has uncommitted workflow edits in LAAM checkout (RunTimeline, ScheduleCard, …) — never touched.
- Push/merge decision pending.
