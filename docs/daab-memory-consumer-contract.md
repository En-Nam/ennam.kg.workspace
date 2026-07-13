# DAAB Memory-of-Record — Consumer Contract & Gate g2 Evidence

**Date:** 2026-07-08 · **Audience:** AAAA (AM AI Agent) and LAAM engineers · **Owner:** DAAB
**Status:** memory-of-record is **LIVE on `main`**. The gate both consumers are waiting on has **PASSED**.

---

## 0. TL;DR — you are blocked on a door that is already open

- **AAAA** refused to wire `kg_recall` until DAAB proves **per-`userId` RBAC isolation**.
- **LAAM**'s `kg_recall` wiring is *"Gated — HOLD until DAAB gate g2."*

**Gate g2 passed.** Evidence in §3. The memory API is live, isolation is test-proven, and it has been exercised end-to-end against a real database (§3.3). Nothing on DAAB's side blocks you.

Two things you must know before wiring: your API key **must be scoped to exactly one project** (§4), and recall **soft-fails silently** — there is no `degraded` flag yet (§7, gap G1).

---

## 1. What this document covers (and what it does not)

**Covers: DAAB's shared agent memory** — `kg_remember` / `kg_recall` over the `agent_context` store. This is the "build memory once, in DAAB; AAAA and LAAM are thin consumers" capability.

**Does NOT cover: DAAB's document knowledge graph** (search, graph retrieval, BA-033 GraphRAG / community detection). That is a *separate product* whose consumers are DAAB's own dashboard and Claude Code agents. LAAM has no document corpus; AAAA keeps client deal data out of DAAB's KG by its own policy. Earlier decision memos conflated the two — do not read BA-033's constraints as constraints on memory.

---

## 2. The contract

### 2.1 Surfaces

| Capability | MCP tool | REST | Class |
|---|---|---|---|
| Store a memory | `kg_remember` | `POST /api/v1/agent-context/remember` | write |
| Retrieve memories | `kg_recall` | `POST /api/v1/agent-context/recall` | read |

The MCP bridge proxies to REST — identical semantics. `project_id` and `user_id` are **resolved from the API key**, never passed by the caller.

### 2.2 `kg_remember`

| Param | Required | Type | Notes |
|---|---|---|---|
| `kind` | yes | enum | `preference` \| `decision` \| `fact` \| `correction` |
| `content` | yes | string | the memory text |
| `scope` | yes | enum | `project` \| `user` \| `agent` |
| `mem_key` | no | string | **idempotency key — same key replaces the prior memory** |
| `tags` | no | string[] | free-form labels |

Response: `{"id": "<uuid>", "status": "created" | "updated", "embedding": "queued"}`

### 2.3 `kg_recall`

| Param | Required | Type | Notes |
|---|---|---|---|
| `query` | yes | string | 1–500 chars |
| `kind` | no | enum | filter |
| `scope` | no | enum | filter |
| `tags` | no | string[] | filter, **any-match** |
| `top_k` | no | int | default 8, max 50 |

Response: `{"results": [{id, kind, scope, content, snippet?, tags, source_agent, created_at, updated_at, score}]}`

Ranking = RRF(semantic 384-dim `multilingual-e5-small` + lexical FTS, k=60) **× recency decay** (half-life 720h ≈ 30 days, configurable via `memory.recall_half_life_hours`). `mem_key` rows are **exempt from decay**.

### 2.4 Raw, never summarised — already guaranteed

`kg_recall`'s own tool description commits to *"Returns **raw snippets**, most relevant first"*, and `kg_search_sessions` to *"**no summarization**"*. **DAAB does not run an LLM on read.** AAAA's requirement that recall return raw windowed patterns rather than LLM summaries is already satisfied by construction — no change needed.

---

## 3. Gate g2 evidence (what you asked us to prove)

### 3.1 Per-`userId` isolation — the gate AAAA named

Recall applies this predicate (`internal/store/agent_context.go`, `agentRecallFilters`):

- **With** a user identity: `AND (a.scope <> 'user' OR a.user_id = $N)` → user-scoped rows return **only to their owner**; `project`/`agent` rows are shared.
- **Without** a user identity: `AND a.scope <> 'user'` → user-scoped rows are **never** returned.

Backed by migration `000069_add_supabase_user_id`. Tests (`internal/handler/agent_context_userscope_test.go`):
`TestRecall_WiresUserIDFromIdentity` · `TestRecall_EmptyUserIDForProjectKey` · `TestRecall_DifferentUsersGetDifferentParams` · `TestRecall_UserScopeIsolation` · `TestRecall_ProjectOnlyKeyUnchanged` · `TestRemember_WiresUserIDFromIdentity` · `TestRemember_EmptyUserIDForProjectKey`

### 3.2 Cross-project isolation

Tests (`internal/handler/recall_isolation_test.go`):
`TestSearch_ForeignProjectInBody_Forbidden` · `TestSearch_CrossProjectIDs_Forbidden` · `TestQuery_ForeignProjectInBody_Forbidden` · `TestNeighbors_ForeignProjectInBody_Forbidden` · `TestTraverse_ForeignProjectInBody_Forbidden` · `TestRequireNodeProjectAccess_ForeignNode_404`

Full Go suite green with `-race` (22/22 packages, verified 2026-07-08).

### 3.3 Live end-to-end proof (2026-07-08)

Against the real database with a real, dashboard-issued developer key scoped to one project:
`kg_remember` ×3 → `200 created` · `kg_recall` → returns them ranked with snippets · `last_recalled_at` populated on the recalled row · `updated_at` untouched.

> ⚠️ This dogfood also uncovered and fixed a **HIGH** bug (commit `ae6a43e`): before it, *no* dashboard-created key could use the memory API at all. See §4.

---

## 4. Getting an API key — READ THIS OR YOU WILL GET 400

Create a key at the dashboard: **`/settings/api-keys`** (admin-only page). Choose:

- **Role:** `developer` (least privilege).
- **Project IDs:** **exactly ONE project.**

**Why exactly one:** the memory handlers resolve the project from the key's `default_project_id`; failing that, from its **sole** `ProjectIDs[0]` (the fallback added in `ae6a43e`). The dashboard's create-key form exposes **no `default_project_id` field**, so:

| Key shape | `kg_remember` / `kg_recall` |
|---|---|
| developer, **1** project | ✅ works |
| developer, **2+** projects, no default | ❌ `400 no project context for this key` |
| admin, `project_ids = []` (all) | ❌ `400 no project context for this key` |

The `X-Project-ID` header does **not** help — the memory write path ignores it and the override gate rejects it (`403 project override not permitted`).

---

## 5. Mapping AAAA's proposed contract onto what exists

AAAA proposed: `kg_recall` with `scope:{userId, namespace:"aaaa.deal-error-patterns"}`, returning raw windowed patterns, with a `degraded` soft-fail flag.

| AAAA wanted | DAAB today | Action |
|---|---|---|
| `userId` scoping | ✅ built + test-proven (§3.1) | none |
| `namespace` | ❌ no such field | **Use `tags: ["aaaa.deal-error-patterns"]`** — recall filters by tags (any-match). No code change needed. |
| raw patterns, not LLM summaries | ✅ guaranteed (§2.4) | none |
| `degraded` soft-fail flag | ❌ **not built** | See gap **G1** (§7) |

**Operational advice for durable patterns:** free-form memories are capped (§6). If an error-pattern must never be evicted, write it with a **`mem_key`** — keyed rows are exempt from dedup, from the growth cap, **and** from recall recency decay. Use `mem_key` for the durable pattern set; leave free-form for transient observations.

---

## 6. Retention behaviour a consumer must know

An hourly sweep maintains the store (`RunRetentionSweep`):

- **Exact dedup** of free-form rows (`mem_key IS NULL`) on `md5(lower(btrim(content)))` within `(project_id, user_id, scope)` — newest by `updated_at` survives.
- **Growth cap:** max **200** live free-form rows per `(project_id, user_id, scope)` (`memory.bucket_cap`). Over-cap rows are archived, ranked by **effective recency** = `GREATEST(updated_at, COALESCE(last_recalled_at, updated_at))` — so a frequently-recalled old memory outranks a never-recalled newer one.
- **`mem_key` rows are exempt from BOTH passes** and from recall decay. They are the durable tier.
- Archiving **deletes the embedding** and is **one-way** (no un-archive API, no hard-delete TTL) — see gap **G3**.
- `last_recalled_at` is populated **best-effort, batched, ~5s after recall**, and **never bumps `updated_at`**.

---

## 7. Known gaps (honest — not built, not hidden)

| # | Gap | Impact on you |
|---|---|---|
| **G1** | **No `degraded` flag.** `kg_recall` soft-fails to `{"results": []}` with **HTTP 200** on embed/store error, logging only. | You **cannot distinguish** "no memories match" from "DAAB backend is degraded." AAAA explicitly requested this flag. **Not built.** If you need it, say so — it is a small, demand-driven change and we will build it. |
| **G2** | Keys must be single-project scoped (§4); multi-project and admin keys cannot use memory. Dashboard form has no default-project field. | Provision one key per project per consumer. |
| **G3** | Archival is a one-way trapdoor (embedding dropped, no recovery, no TTL). | Durable memories must use `mem_key`. |

None of these block wiring today. **G1 is the one we would build first if you ask.**

---

## 8. What we need from you

1. **Confirm the gate is closed on your side** — is §3 the evidence you asked for? If not, name precisely what is missing.
2. **Tell us if you need G1** (`degraded` flag). It is the only gap with a named requester.
3. **LAAM:** you have a generic "mount external MCP server" feature; DAAB currently appears only in your tests as slug `daab`. Mount it for real, or tell us what is missing.
4. **AAAA:** your `.mcp.json` declares only `supabase` + `inngest`. Add DAAB, or call REST directly from Inngest.

---

## Appendix — provenance

Written after source-verifying both consumers (2026-07-08). Two claims in the earlier decision memo `ba033-slice2-deferred` were **refuted by source** and must not be propagated:

- *"AAAA is multi-tenant, so cross-deal retrieval leaks"* — **false.** AAAA has zero tenant/org fields; isolation is per-`userId`. AAAA's own Technical Principal rebutted this (`am-ai-agents/docs/ecosystem/2026-06-23-aaaa-feedback-on-hermes-allocation.md:16,44,83`).
- *"LAAM forbids LLM-summary-on-read"* — **no such principle exists** in LAAM's docs. Its codified rule is `AGENTS.md` Rule 13 (trust code over LLM fact-regurgitation), which does not forbid consuming summaries.

Both claims were about **BA-033 GraphRAG**, a different product from memory. They never constrained `kg_remember`/`kg_recall`.
