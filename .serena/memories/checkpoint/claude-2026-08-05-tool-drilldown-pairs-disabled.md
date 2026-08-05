# Checkpoint: claude — 2026-08-05 (LAAM .env: TOOL_DRILLDOWN_PAIRS — disabled, not just slug-fixed)

Follow-up to `mem:checkpoint/claude-2026-08-05-laam-g5-datafetch-guard`'s "config rot found" item. User asked to fix the stale `mcp__daab__*` slug → `daab-michael-pharmacy-chain`.

## Why a simple slug swap was wrong
Verified before editing (Rule 1 — don't guess): checked what `kg_get_master_record` actually returns for THIS project.
- `connector_credential` confirms the live connector slug is `daab-michael-pharmacy-chain` (not `daab`).
- `knowledge_nodes` for Michael Pharmacy Chain (`4ad7a5fa-…`) is 19 rows, ALL `node_type='architecture'` (DB schema nodes) — zero `derived_record`/`aaaa_master_record` rows.
- Master records only exist for two OTHER projects in this DAAB instance: "Cảng Định An v3" and "Dasin" — document-analysis projects, not DB-connected ones.

So a slug-only fix would have made the pair resolve correctly and then call `kg_get_master_record` every time a list-tool drilldown condition matched — always getting back `{"master_record": null, "hint": ...}`. Not broken, but a wasted tool round on every drilldown-eligible turn, for a feature this project's data doesn't support at all. This is a **project/pairing mismatch**, not a slug typo — a slug-only fix would have "fixed" it into a different-but-still-wrong state.

## Fix
`LAAM/.env` — `TOOL_DRILLDOWN_PAIRS` set to empty (disables D2 drilldown cleanly; `parseDrilldownPairs` treats empty/blank as `[]` with no warning, verified in `drilldown.ts:45`). Left a comment explaining why, plus the correct re-enable line (parameterized `<slug>`) for whenever the connector points at a document-analysis project that actually has master records.

## Verification
- `next dev` restarted to load the env change.
- Smoke-tested Q1 and Q9 via LAAM `/api/chat` (voice) — both answered correctly, zero `[drilldown]` warnings in server logs (confirms the empty value parses silently, not as a malformed-JSON warning).
- `npx vitest run src/lib/agent src/app/api/chat` (drilldown.test.ts included) → 290 passed. `npx tsc --noEmit` clean.

## Files changed
- `LAAM/.env` (not version-controlled — this change does NOT propagate to other environments; re-apply if `.env` is regenerated from `.env.example`, or fix that template too if this project stays DB-connected long-term)

## Blockers / Risks
- None. If DAAB is later pointed at a document-analysis project for this LAAM instance, re-enable via the commented template line with the correct slug.
