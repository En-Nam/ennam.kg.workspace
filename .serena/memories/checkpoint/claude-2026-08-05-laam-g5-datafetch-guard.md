# Checkpoint: claude — 2026-08-05 (LAAM fix: G5 data-fetch guard + verification of DAAB fix #9 + stale-stats loose end)

User asked "what else can be improved?" after fix #9. Investigated three things rather than speculating.

## 1. Verified DAAB fix #9 (metric-ambiguity clarification) — it DOES fire
`mem:checkpoint/claude-2026-08-05-daab-metric-ambiguity-clarification` shipped this UNVERIFIED and said so. Probed with Q7 ("Which stores have the highest inventory variance?" — the cleanest metric-ambiguity case, since variance_quantity and variance_value rank stores in OPPOSITE order). Confirmed working: the model now asks back, naming the actual columns, e.g. *"Bạn muốn xét độ chênh lệch dựa trên số lượng (variance_quantity) hay giá trị tiền tệ (variance_value)?"*. `query_clarifications` shows 4 distinct metric-level clarifications raised for this question shape — a category that produced ZERO clarifications before the fix (all prior ones were column-level).

## 2. NEW: G5 data-fetch guard (LAAM `orchestrator.ts`) — the dominant remaining failure
The Q7 probe exposed the real top failure: **2/3 runs the model called `kg_describe_table` FOUR times to read schema, then concluded "I don't have actual data" and stopped — never once calling `kg_query_datasource`.** Zero queries reached DAAB. The existing G4 grounding guard misses this because that turn DID call tools.

Fix, mirroring G4's proven code-level-nudge pattern (prompt fixes had already failed twice for the analogous voice-grounding issue, per `mem:checkpoint/voice-tool-grounding-2026-08-03`):
- `orchestrator.ts` — `DATA_FETCH_NUDGE` + `ToolRoundsOpts.dataFetchTools?: ReadonlySet<string>`. Fires when the turn is ending, tools WERE called, but none belonged to the data-fetch set. One-shot latch (same as G4/web_read), so a model that still refuses exits normally instead of looping to the backstop. Trigger is purely STRUCTURAL (Rule 5 — no intent classification, no reading the answer text).
- Tool names come from env `TOOL_DATA_FETCH` (comma-separated), NOT hardcoded — LAAM must not know any connector's tool names, exactly the reasoning behind the existing `TOOL_DRILLDOWN_PAIRS`. Unset ⇒ guard off, behavior identical to before.
- `route.ts` — parse env + pass at both `runToolRounds` call sites (Ollama + BytePlus).
- `.env` — set for the current DAAB connector.
- 4 new tests (nudge fires then model queries; no nudge when a data tool was already called; unset env = unchanged behavior incl. no extra round; nudge at most once).
- `npx vitest run src/lib/agent src/app/api/chat src/lib/chat` → 448 passed; `npx tsc --noEmit` clean.

**Measured effect** (same question, 3 runs before / 3 after): give-up rate **2/3 → 0/3**; every run now reaches DAAB. Post-fix outcomes: 2/3 ask back correctly, 1/3 answers.

## 3. Stale-stats loose end from the very first session — CLOSED (partially)
`stores` had `row_count_estimate = 0` in DAAB metadata (real: 5) and **all 19 tables had never been ANALYZEd**. Ran `ANALYZE` on `pharmacy_demo`; `pg_stat_user_tables` now correct (stores=5). NOTE: DAAB's stored `source_tables.row_count_estimate` is still 0 — it only refreshes on a schema re-extract/sync, which was NOT triggered (needs an authenticated DAAB API call; keys are hashed and unavailable). Impact is limited: `buildSchemaContext` omits the row count when it's 0 rather than telling the AI "0 rows", so the planner is not actively misled — but the dashboard UI and any human reading metadata still see 0. **Re-run schema sync for this data source before the demo to fully close it.**

## 4. Config rot found (not fixed — needs a decision)
`.env`'s `TOOL_DRILLDOWN_PAIRS` references `mcp__daab__kg_list_projects` / `mcp__daab__kg_get_master_record`, but the live connector slug is `daab-michael-pharmacy-chain`, so the real tool names are `mcp__daab-michael-pharmacy-chain__…`. **The D2 drilldown feature is silently dead for this connector** — the pairs never match. Either update the slug in the env or make the matching slug-agnostic.

## Process note — a mistake I made and corrected
Ran `npx prettier --write` on `route.ts` to fix indentation. The repo has NO prettier config, so it reformatted the entire file: a 631-insertion diff for a 9-line change (Rule 3 violation, would have destroyed git blame). Recovered safely: proved via `diff <(prettier HEAD-version) current` that the ONLY non-formatting delta was my own 12 lines (i.e. route.ts had no other uncommitted work at risk), backed the file up, `git checkout`-ed it, and re-applied the change by hand in the repo's own style. Final diff: 9 insertions, 0 modifications. **Never run a formatter on a file in this repo — there is no shared config, so it will reformat everything.**

## Files changed
- `LAAM/src/lib/agent/orchestrator.ts`, `orchestrator.test.ts`
- `LAAM/src/app/api/chat/route.ts` (+9 lines), `LAAM/.env`

## Blockers / Risks
- Everything across this whole thread (both repos) remains **uncommitted**.
- `.env` is not version-controlled — `TOOL_DATA_FETCH` must be set again on any other environment or the guard silently stays off.
