# Ecosystem decision — Hermes-capability allocation across AAAA / DAAB / LAAM

**Status:** DECISION (CTO) · **Date:** 2026-06-23 · **Scope:** ecosystem-wide (all 3 platforms) · **Canonical copy:** identical file committed to the `decisions/` of all three repos.

> **TL;DR (vi):** Xây bộ nhớ MỘT LẦN, đặt trong **DAAB**, biến nó thành substrate mà **AAAA** và **LAAM** cùng tiêu thụ — KHÔNG để mỗi platform tự mọc kho memory riêng. Skill-creation + subagent-shell của Hermes = **skip toàn ecosystem** (bảo mật). Routing đa-provider = đã giải, skip.

## Context

Evaluated NousResearch/hermes-agent (prior adversarial round → verdict: *adopt-ideas-only, do-not-integrate* — Python vs our TS/Go, redundant, security model incompatible in-process). This decision takes the **verified** Hermes capabilities and allocates them across the ennam ecosystem's three platforms, which share one infra (pgvector Postgres + Redis on `ecosystem-net`, see `SharedContainers`).

Platforms: **AAAA** = `am-ai-agents` (AI investment banker / M&A; Next.js 16 / TS / Prisma 7 / Supabase / Claude tool_use / Inngest v4). **DAAB** = `ennam.kg` (knowledge graph; Go + pgvector; MCP `kg_*`). **LAAM** = agent monitoring + local-model chat + connectors (Next.js 16 / TS / Drizzle / Ollama+Claude+BytePlus; just shipped a run-until-done tool-loop + write-gate).

## Thesis

**Build memory once, in DAAB, and make it the substrate the other two consume.** Persistent cross-session memory + session search is the single highest-leverage Hermes capability, the one all three platforms independently lack and independently proposed to build native — the exact 3× reinvention to prevent. DAAB is the only platform with the right substrate (pgvector + versioned JSONB + graph + RBAC + project-scoping + MCP) and already names "Hermes-style memory unification" on its Phase 4 roadmap. So **DAAB owns memory-of-record + session search as MCP primitives**; **AAAA and LAAM are thin consumers**. Everything else is allocated down the risk gradient; the two dangerous capabilities (self-improving skill-creation, shell-backed subagents) are **ecosystem-wide skips** behind one shared security invariant.

## Allocation matrix (Hermes capability × platform)

`consume-shared` = call DAAB's MCP primitive.

| Hermes capability | AAAA | DAAB | LAAM |
|---|---|---|---|
| 1. Persistent cross-session memory | consume-shared (`kg_recall`, deal/entity-scoped) | **adopt-native (OWNER)** — `agent_memory`/`user_profile` nodes | consume-shared (chat/session recall) |
| 2. Session search (FTS + VN/CJK trigram) | consume-shared (sessions) + native (deal-doc bodies) | **adopt-native (OWNER)** — index threads/sessions, raw windowed | consume-shared (`kg_search_sessions`) |
| 3. Self-improvement / skill-creation | **skip** (deterministic offline correction-mining) | **skip** (infra, not an agent) | **skip** (already rejected — 8B safety) |
| 4. Isolated parallel subagents (shell) | **skip** (Inngest `step.run` fan-out) | **skip** (existing Redis worker queue) | **skip** (bounded tool-loop exists) |
| 5. Provider-agnostic routing | **skip** (already live) | **skip** (Haiku sufficient) | **skip** (already live) |
| 6. Multi-platform gateway | **defer** (narrow email→Inngest only) | **skip** (no end-user chat surface) | **defer** (connector surface exists) |
| 7. ACP / IDE adapter | **skip** | **defer** (MCP already serves IDE agents) | **skip** |
| 8. Security model (OS-only boundary) | **adopt** (guardrail) | **adopt** (guardrail — substrate owner) | **adopt** (guardrail — live connector creds) |

## Per-platform upgrade direction (+ anti-goals)

### AAAA (M&A) — thin consumer
- **P0 — Forward-propagating deal memory (consume-shared).** `applyCorrection` ALREADY reads corrections back — the real gap is *forward-propagation*: a confirmed correction/re-rank disagreement must be recallable on the *next* deal so the same valuation/red-flag error class isn't re-made. Start narrow: confirmed DataCorrections → one highest-value prompt (red-flag/valuation) via `kg_recall`, prompt-cached.
- **P1 — Bounded deal-scoped feedback loop (native, Inngest).** generate → verify ground truth (Rule 13) → re-run affected step with memory → stop on convergence or **hard cap**. Inngest = deterministic control flow; model only extracts/judges (Rule 5).
- **P1 — Deal-document-body FTS (native, tenant-gated)** for Teaser/IM/Analysis text that must NOT enter the shared graph.
- **Anti-goals:** no native memory store; **no cross-deal search before multi-tenancy** (HARD blocker, severity HIGH — cross-firm confidentiality breach); no skill-creation / shell-subagents.

### DAAB (knowledge graph) — KEYSTONE OWNER
- **P0 — Memory-of-record as graph primitive (OWNER).** New node types `agent_memory` (MEMORY.md role) + `user_profile` (USER.md role) on versioned-JSONB nodes; `kg_remember`/`kg_recall` MCP tools; recall = hybrid RRF over node embeddings scoped by `project_id` + `user_id`. **Reject Hermes's flat-file MEMORY.md/USER.md** — that markdown-breaks-under-parallel-agents pain is *why DAAB exists*.
- **P1 — Session/conversation search (OWNER).** Extend FTS to index threads/sessions; return raw windowed `ts_headline`, **no LLM summary** (Hermes's correct choice); hybrid RRF > FTS-only.
- **P1 — Own recall-ranking + retention** (decay / archive / dedup / growth-bound) at the recall boundary. (AAAA "stale poisoning" = DAAB "unbounded growth" = one problem.)
- **Anti-goals:** capture must NOT piggyback Gate-2 (skipped on error → silent amnesia) → needs its own **always-runs** checkpoint at the write-tool boundary; define the capture contract ONCE at `kg_remember`; **prove cross-platform RBAC isolation** of `user_profile` PII (see Open Questions).

### LAAM (monitor + chat + connectors) — thin consumer
- **P1 — Cross-session chat/agent memory (consume DAAB).** Chat is stateless across sessions; `kg_recall` gives "what did this user/agent decide before." Recall is read-only for Qwen 8B; curation is code-driven on DAAB.
- **P1 — Session search over monitored transcripts (consume).** `kg_search_sessions`; LAAM already parses transcripts — index the salient slice.
- **Anti-goals:** **hold the line — no skill-creation** (LAAM is the ecosystem's strongest precedent); no native memory store; write-curation stays OFF the local 8B (Rule 13).

## Shared-build decision

Build once on DAAB / shared infra: **memory-of-record** (`kg_remember`/`kg_recall`, RRF) · **session search** (`kg_search_sessions`, raw windowed) · **recall ranking + retention policy** · **security invariant** (ennam-level CLAUDE.md/AGENTS.md + audit-guard pattern). Owner: DAAB (+ ennam-level for the invariant); consumed by AAAA + LAAM as thin MCP clients.

Keep per-platform (do NOT centralize): provider-agnostic routing (refactor = risk, 0 gain); **AAAA deal-document-body FTS** (private corpus, never into the shared graph — session search is shared, deal-doc-body search is AAAA-local); orchestration (AAAA=Inngest, DAAB=Redis queue, LAAM=tool-loop — no shared subagent layer).

## Sequencing (with hard gates)

- **Phase 0 — Foundations (parallel):** DAAB confirm internals exist as asserted ← GATE · all: write the shared security invariant + audit-guard (cheap, now) · AAAA multi-tenancy (`tenant_id` isolation) ← HARD GATE for any AAAA search.
- **Phase 1 — Keystone (DAAB):** `agent_memory`+`user_profile`; `kg_remember`/`kg_recall`; always-runs capture checkpoint; recall ranking/retention · prove cross-platform RBAC isolation ← GATE before consumers.
- **Phase 2 — Thin consumers:** AAAA dealMemory (DataCorrections → one prompt via `kg_recall`) · LAAM chat/session recall (read-only Qwen) · DAAB `kg_search_sessions` ✅ **SHIPPED 2026-06-29** (branch `task/implement_docs_sync`, HEAD `0e0523a`): VN-correct FTS (`simple`+`f_unaccent`), user+project scoped, raw windowed `ts_headline` (no LLM summary), opaque MCP tool — security-reviewed (scope unwidenable by body/header). LAAM consume-shared (FTS recall) is now unblocked; **cross-user `monitoring` scope still gated** on the RBAC monitoring-scope decision + threat model (see `mem:backlog/daab-kg-search-sessions-followups`).
- **Phase 3 — Native, platform-private:** AAAA bounded feedback loop (hard cap + budget gate) · AAAA deal-doc FTS (ONLY after multi-tenancy) · LAAM session search over transcripts.
- **Phase 4 — Deferred:** AAAA narrow inbound-email→Inngest (treat email as untrusted).

**Hard dependencies:** DAAB internals-verification gates the memory budget; DAAB RBAC-isolation proof gates ALL consumers; AAAA multi-tenancy gates AAAA cross-deal/doc search (non-negotiable).

## Guardrails — security invariant (one, ecosystem-wide)

**No agent that executes model-authored or arbitrary code may run in the same process as live-credential connectors.** This is why Hermes cap. 3 (skill-creation) + cap. 4 (shell-subagents) are ecosystem skips — AAAA holds Supabase service-role + Google refresh tokens + Apollo/Hunter keys; LAAM holds live connector creds; DAAB is the credential-bearing substrate. Hermes's own SECURITY.md ("OS is the only boundary") confirms such agents must be OS-sandboxed and never co-located with live creds — adopting 3/4 would violate Hermes's own precondition. Encode once at ennam level + a copyable audit-guard pattern; it must also cover AAAA's bounded loop so "just add a shell tool" can't slip in later.

**Do NOT copy from Hermes:** flat-file MEMORY.md/USER.md (→ graph nodes); LLM-timed "self-nudge every ~10 turns" curation (→ deterministic code capture, Rule 5); self-improving skill-creation / background_review (arbitrary code-exec — hard no); shell/docker/ssh/modal subagent backends (second ungoverned orchestration layer — hard no); 7-channel gateway. **Copy the one principle Hermes got right:** raw windowed recall, no LLM summarization.

## Open questions / verification gates (CTO is explicit these are unverified)

1. **DAAB internals unverified from the CTO round** — the "thin extension of shipped infra" framing assumes `node_embedding`/`rrf`/`gate2`/thread-session stores / 384-dim embeddings / `content_hash` / `is_archived` exist. **DAAB team must confirm each**, else the memory build re-budgets from "extension" to "net-new" (changes Phase 1 scope).
2. **Cross-platform RBAC isolation** — when AAAA's/LAAM's agent key calls `kg_recall`, is `user_profile`/`agent_memory` PII provably scoped, or only within DAAB's own project model? Needs a written threat model + a test (foreign key must not reach another platform's nodes). Make-or-break for DAAB-as-shared-owner.
3. **MCP-hop latency** for AAAA's latency-sensitive doc-gen prompts — may need a read-through cache / local scoped replica.
4. **Capture contract** — what gets written, when, by whom — defined once at `kg_remember` or risk three incompatible write disciplines.
5. **AAAA multi-tenancy timeline** — cross-deal search is blocked on it; confirm the dependency is accepted, not bypassed.
6. **Convergence definition** for AAAA's bounded loop — explicit code-checkable stop condition + hard cap + budget gate.

## Provenance

Derived from a multi-agent CTO round (2026-06-23): 3 platform deep-dives (read from each repo) → 8-capability decomposition → per-platform allocation → 2 adversarial critiques (architect + product) → CTO synthesis. Adversarial corrections baked in: (a) AAAA `applyCorrection` already reads back — gap is forward-propagation; (b) AAAA cross-deal search hard-gated on multi-tenancy; (c) DAAB internals asserted, not verified — hence gate #1.
