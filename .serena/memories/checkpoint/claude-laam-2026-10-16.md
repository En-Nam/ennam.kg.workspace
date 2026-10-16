# Checkpoint: claude (LAAM) — 2026-10-16

## What was done
- Home "Scenarios" redesign (ScenarioDigest, assumptions column, WhatIf names the measure); pack `scenario.text` via `presentScenario`.
- Causes analysis: `compare: target` rules use `decomposeTargetSpread`/`decomposeTargetRate` (new baseline kinds target_spread/target_rate); fallback to labelled previous period.
- Per-language rule names (`text.{en,vi}.name`, `ruleNameOf`); Vietnamese term unified to "mục cần chú ý".
- Quality gate: lint 0 errors (5 React-Compiler-only rules downgraded to warn in eslint.config.mjs), tsc clean, unit 6666 pass, integration 533/533. Playwright E2E NOT run; no LAAM CI workflow.
- Answered "is Home AI-written?": card face = deterministic templates (pack rule name + figures); AI (`intel_briefing`) writes only "Giải thích đầy đủ" on the finding page (numbers re-verified, 1 rewrite, else template). Prefilled task title reuses that brief title (no separate AI call).
- Audit of AI call sites: only chat default was missing from Settings → AI models. Added task `chat` ("Chat và Ask LAAM (model mặc định)"): model-only (no effort), no DeepSeek (chat route has no DeepSeek transport), Claude allowed. `/api/chat/info` uses `resolveChatDefault` (src/lib/llm/chat-default.ts); pinned model ignored if key gone or local model for a customer org.

## Files changed
- src/lib/llm/{tasks,task-config-view,chat-default}.ts (+tests), src/app/api/chat/info/route.ts, src/app/api/settings/llm-tasks/route.ts, src/components/settings/AiModelsManager.tsx (+test), src/i18n/dictionaries/ai-models.ts
- Earlier: intel scenario/present, pack schema, intel dictionary, eslint.config.mjs, CHANGELOG [Unreleased]

## Current state
- Pushed: branch task/proactive-intelligence at 4c6249a8. Container laam-v2-app rebuilt (laam-app:latest) and running on :3900 with the chat setting.
- CHANGELOG [Unreleased] does NOT yet mention the chat default model setting.
- Untracked `.spectex/` left uncommitted on purpose.

## Next steps
- Add CHANGELOG line for chat default model; update docs/DEPLOYMENT.md (stale migration numbers 0020–0025 → 0022–0028; new env vars ADMIN_API_URL/ADMIN_API_KEY/CONNECTOR_KEY/MCP_HOST_ALLOWLIST/LAAM_DOCKER_DATABASE_URL/LAAM_INTERNAL_ORG_ID/NAME, USAGE_ENFORCE, REGISTER_MODE).
- Run Playwright E2E; decide version (suggested v3.0.0, user said not yet); PR to main (293 commits ahead).

## Blockers / Risks
- Prod DB migration state unknown (renumbering pitfall); prod internal-org id must come from Admin.
- Packs 0.5.0 need this LAAM (strict schema); publish packs only after LAAM upgraded.
