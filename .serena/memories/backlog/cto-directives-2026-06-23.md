# Backlog — CTO directives (2026-06-23 platform review)

> Tracking items from the CTO review `mem:global/ecosystem/cto-review-2026-06-23`. Contract: `mem:global/ecosystem/shared-memory-contract` · DAAB plan: `mem:global/ecosystem/daab-plan`. **DAAB owns the ecosystem critical path.** Delete items as completed.

## P0 — security hotfix (independent of Hermes; this is a LIVE prod defect)
- [ ] Ship cross-project RBAC fix (`requireProjectAccess` + `requireNodeProjectAccess`) as a **standalone security patch**.
- [ ] `recall_isolation_test` **T1–T7 GREEN in CI** (provision DB + golangci-lint + cgo for `-race`). = gate **g2a**.
- [ ] **Exposure audit** — did real cross-project reads occur pre-patch (body-override / `cross_project_ids` / by-UUID IDOR)? Report → CTO/human for any disclosure call.
- [ ] **Write-IDOR sweep** — `update*` / `deprecate` by-UUID + remaining by-id handlers (same `GetNode`-without-check pattern).

## P1 — keystone (after P0)
- [ ] **`user_id` scoping migration** (D1 — highest-leverage unblock): `knowledge_nodes`/`agent_context.user_id` + recall filters → T6/T7 green. = gate **g2b**.
- [ ] **`agent_context` sibling table** (D5) — NOT graph nodes (avoid edge-less islands).
- [ ] **`kg_remember` + `kg_recall`** over MCP+REST (one handler via bridge mirror). Honor D7: `readOnlyHint=true` + no-write-path test; **NO opaque-UUID args** (resolve project_id/user_id from the agent key); ≤2 unambiguous tools; raw windowed return, no LLM summary; soft-fail; deterministic ordering.
- [ ] **Always-runs capture** at the store INSERT boundary (NOT gate-2); **Python-local 384-dim embed-on-write** (forbid `generateDescription` LLM) — D8.
- [ ] **Retention background job** (decay / archive / dedup / growth-bound; compute in jobengine, enforce at recall).
- [ ] **Consumer-key class** (D3) — distinguish consumer vs internal; consumer keys `role=agent`, non-empty `project_ids`, `allow_project_override=false`. Required BEFORE issuing AAAA/LAAM keys.

## Confirmed scope
- Phase-1 re-budget thin→**net-new** ACCEPTED (D6). `kg_search_sessions` **DESCOPED** from the shared seam (D4) — internal-only if built at all.
- BA-031 8b/8c gates remain **PENDING-DATA** (VI labelled dataset) — separate track, not blocking the keystone.

## GATE
**g2 (g2a CI-green AND g2b live) must pass before ANY consumer (AAAA/LAAM) wires recall.**
