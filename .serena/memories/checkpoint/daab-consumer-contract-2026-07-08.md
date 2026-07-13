# Checkpoint: daab-consumer-contract — 2026-07-08

## What was done
- **Merged** the usage-based-decay work + project-resolution bugfix into `origin/main` (verified: 0 commits ahead; `ae6a43e`, `3c34abf`, `3dde306`, `b00bded` all ancestors of origin/main).
- **Source-verified AAAA + LAAM** (3 parallel agents over `other_projects/am-ai-agents`, `other_projects/LAAM`, and `BA-033`). Result: **two load-bearing claims in `decisions/ba033-slice2-deferred` are FALSE.**
  - *"AAAA is multi-tenant → global retrieval leaks"* — **false.** Zero tenant/org fields; per-`userId` isolation. Refuted in writing by AAAA's own Technical Principal (`am-ai-agents/docs/ecosystem/2026-06-23-aaaa-feedback-on-hermes-allocation.md:16,44,83`).
  - *"LAAM forbids LLM-summary-on-read"* — **no such principle exists.** LAAM's real rule is `AGENTS.md` Rule 13 (trust code over LLM fact-regurgitation).
- **Key insight — two DAAB products were conflated:**
  1. **memory-of-record** (`kg_remember`/`kg_recall`) → consumers = AAAA + LAAM. Alive, g2 passed, bug-fixed, dogfood-proven, merged.
  2. **document KG / GraphRAG (BA-033)** → consumers = DAAB's own dashboard + Claude Code agents. LAAM has **no document corpus** (no pgvector/RAG; data = agent sessions). AAAA has **no KG retrieval need** (feeds doc text straight to Claude `tool_use`) and its ecosystem doc says *"Client data from AAA never enters the internal KG."*
  BA-033's constraints never applied to memory. Dragging AAAA/LAAM into BA-033's consumer analysis was a category error (in the memos, and repeated by me).
- **Discovered both consumers are blocked on a gate DAAB already passed.** AAAA: refuses to wire until per-`userId` RBAC proof. LAAM: `kg_recall` "HOLD until DAAB gate g2". g2 passed (22/22 pkgs `-race`, userscope + cross-project isolation tests).
- **Wrote + committed** `docs/daab-memory-consumer-contract.md` (`b96845b`): MCP+REST contract, g2 evidence with test citations, single-project key requirement (§4), retention semantics, AAAA-contract mapping (`namespace` → `tags`; durable patterns → `mem_key`), and **3 honest gaps** (G1 no `degraded` flag — AAAA's only named ask; G2 multi-project/admin keys unusable; G3 one-way archive).
- **Corrected** `mem:decisions/ba033-slice2-deferred` (retracted both refuted claims; recorded that the 2026-07-03 "Gate A GREEN" measure was on the **concept-INCLUDED** graph and does NOT settle OQ-033-8).

## Current state
- `main` has memory-of-record + decay + bugfix. Working tree clean.
- **BA-033 correctly parked** — but for the RIGHT reasons: (a) OQ-033-8 graph density unresolved, (b) corpus is mixed-domain (recipe concept-hubs + M&A land parcels) so communities/summaries are meaningless and the falsifiability gate can't run, (c) no committed dashboard consumer. NOT because of AAAA/LAAM.
- FR-001 + FR-004 (`kg_graph_retrieve`, local retrieval) is the only BA-033 subset **not** blocked by OQ-033-8 — but its demand is also unproven, so it is not recommended yet.

## Next steps
- Send `docs/daab-memory-consumer-contract.md` to AAAA + LAAM; ask (1) is §3 the g2 proof you wanted, (2) do you need **G1** (`degraded` flag) — the only gap with a named requester.
- **Do NOT build** retention items ②/④/③ or any BA-033 slice. No demonstrated demand.
- Open product question, upstream of all GraphRAG work: **"DAAB Corpus & Consumer Charter"** — what corpus is DAAB's KG for, and who reads it? CLAUDE.md says "Ennam engineering projects"; live data is recipes + M&A. Nothing in GraphRAG can be decided before this.

## Blockers / Risks
- ⚠️ **Two API keys exposed in transcript** (`ennam_kg_e09c…`, `ennam_kg_c622…`) — **still need revoking**.
- ⚠️ **daab-postgres dev password leaked** into transcript (CRLF env-parse error) — **rotate**.
- 3 dogfood memory rows left in `agent_context` for project `592c7ff7` (source_agent = user's email). Harmless; keep or delete.
