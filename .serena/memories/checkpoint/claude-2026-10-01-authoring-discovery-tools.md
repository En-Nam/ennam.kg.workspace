# Checkpoint: claude — 2026-10-01 (authoring discovery-tools fix)

## What was done
- Root cause of the bad recipe workflow with Public APIs on: `searchCatalog` fail-open returned the WHOLE catalog on no match → probe lookup (`public_api_search`) got `resolved` → `buildFacts` gave it a ref → Plan/compileTrace made it a node → `reportPrompt` took the "DATA RESULTS" branch; the report agent (all internal tools) then called LAAM's stats tool. Reproduced on BOTH the pre-feature build and current: NOT caused by the per-task AI-model settings feature.
- Fix (5 commits + fix pass, on task/improve-workflow, not pushed): (1) catalog search: whole-word + 3-letter prefix, stop words, >=1/3 of words, `[]`+note when nothing matches, declared `fallback` entry (APILayer serpstack_search); (2) `Connector.discoveryTools` required + `isDiscoveryTool` + contract tests; (3) `resolveForTrace` (NOT resolveAuthoring — route still uses it for dispatch names) applied where `resolved` is attached to read records; (4) report node loses `laam_*` tools only (keeps web/util); (5) `scripts/ab-creative.mjs` live scorer.

## Files changed
src/lib/connectors/{catalogApi,types,index,apilayer,publicApis,+10 connectors}.ts(+tests), src/lib/workflow/{generateChat,runtime}.ts(+tests, facts.test), src/app/api/workflows/generate/{route,chat/route}.ts(+tests), scripts/ab-creative.mjs, CHANGELOG.md, spec+plan docs.

## Current state
- Full suite 3699 pass, 6 pre-existing fails (scripts/eval/runner.test x2, ConstellationClient.test x3, schedule.test x1); tsc 1 pre-existing (executors.test.ts:260). Container laam-v2-app rebuilt.
- Live `ab-creative` on :3900: 5/5 with APILayer ON and Public APIs OFF (0 lookup nodes). NOT yet run with Public APIs ON (the motivating scenario) — needs the user to enable that connector (account setting, not toggled by me).

## Next steps
- User enables Public APIs → `LAAM_BASE=http://localhost:3900 N=5 node scripts/ab-creative.mjs`; expect 5/5.
- Deferred minors: isReportNode ignores report-2/3; priorRecords across deploy; search-only data requests fall to agent-only path; NO_VIEW_TOOLS duplicates the lookup list (src/lib/agent/view.ts:191); note shown when enabledIds=[]; script default UUID/recipient.

## Blockers / Risks
- MCP third-party tools cannot be classified as discovery (no code guard). Vietnamese lexical matching is heuristic (ngẫu nhiên still matches trivia).
