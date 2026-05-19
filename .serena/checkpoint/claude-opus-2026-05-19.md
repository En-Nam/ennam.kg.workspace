# Checkpoint: claude-opus — 2026-05-19

## What was done
- Compared the AM AI AGENT project's CLAUDE.md/AGENTS.md (working well elsewhere)
  against Ennam KG's, then did a **selective port** of presentation only.
- Root `CLAUDE.md`: replaced `Quick Start` one-liner with a sourced **Tech Stack**
  table + expanded **Build & Run** table (full-stack Docker + per-service local dev).
- Converted ASCII/text diagrams to Mermaid: Session Boot Protocol (kept 5 steps,
  KG-MCP first), Superpowers Workflow, Serena Read protocol, Serena Write protocol.
- `ennam.kg.next/CLAUDE.md`: added a managed `nextjs-agent-rules` block
  (verified Next 16.2.1 + React 19; verified `node_modules/next/dist/docs/` exists).

## Files changed
- `CLAUDE.md` (root) — Tech Stack + Build & Run tables; 4 Mermaid diagrams
- `ennam.kg.next/CLAUDE.md` — added BEGIN/END:nextjs-agent-rules block
- `.serena/checkpoint/claude-opus-2026-05-19.md` (this file)

## Current state
- Working. Knowledge Source Priority section (KG-MCP-first + KG query/write-back
  tables + fallback) deliberately left 100% untouched — no Serena-first regression.
- Root `AGENTS.md` unchanged (Next.js rule scoped to ennam.kg.next only, not root,
  to avoid noise during Go/Python sessions).
- All commands/stack values sourced from real docker-compose.yml + sub-project docs.

## Next steps
- Optional (not done, deferred): per-project Tech Stack detail; Vietnamese↔English
  glossary; Knowledge-Source Mermaid (intentionally skipped — conflict-sensitive).
- Mermaid uses `\n` label breaks + `<i>` HTML labels, matching the proven AM AI
  AGENT template (Rule 11 conformance) — confirm rendering in the team's viewer.

## Blockers / Risks
- None. Pure docs change; no code/tests affected.
