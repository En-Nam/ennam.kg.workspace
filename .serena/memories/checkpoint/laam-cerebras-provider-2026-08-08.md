# Checkpoint: LAAM Cerebras provider integration — 2026-08-08

## What was done
Added Cerebras (api.cerebras.ai, OpenAI-compatible, gpt-oss-120b) as a second full-agent
cloud provider alongside BytePlus, sharing BytePlus's tool-loop code path in route.ts via a
small provider selector instead of duplicating ~250 lines.

- New `src/lib/llm/cerebras.ts`: adapter mirroring `byteplus.ts` (cerebrasChat/cerebrasStream,
  CerebrasUnavailableError, retry, reasoning_effort — same CHAT_REASONING_EFFORT* env vars as
  BytePlus since it's the same model id).
- **Key gotcha**: Cerebras's literal model name is `gpt-oss-120b` — IDENTICAL to BytePlus's.
  Routing (`isBytePlusModel`/`isCerebrasModel`) is exact-string whitelist membership, so the
  picker id CANNOT be the bare wire name or both providers would claim the same turn when
  both keys are set. Picker id = `gpt-oss-120b-cerebras`; `WIRE_MODEL`/`toWireModel()` in
  cerebras.ts translates it back to `gpt-oss-120b` before it hits the wire. Caught by a route
  test collision (BytePlus tests started resolving to Cerebras) — see
  `mem:mcp-results-arrive-stringified` sibling gotchas for other stringly-typed traps in this
  codebase.
- `internal.ts`: priority chain now INTERNAL_MODEL → BYTEPLUS_API_KEY → CEREBRAS_API_KEY →
  ANTHROPIC_API_KEY → DEFAULT_CHAT_MODEL (BytePlus keeps precedence for existing deployments).
- `route.ts`: generalized the BytePlus-only branch (`streamMainTurn`'s tool-loop+stream block,
  and `streamByteplusCompletion` → renamed `streamCloudCompletion`) to handle both providers
  via `cloudChat`/`cloudStream`/`cloudErrText`/`isCloudUnavailableError` selected by
  `isCerebrasModel(payload.model)`. Chose generalization over duplication (DRY, Rule 2) since
  the two providers are wire-identical.
- `chat/info/route.ts` + ChatClient/SettingsPanel/both ConstellationClients: `cerebrasModels`
  wired through the same env-gated pattern as `byteplusModels`.
- `.env.example`: documented CEREBRAS_API_KEY/CEREBRAS_BASE_URL + the picker-id-vs-wire-model
  gotcha, updated the INTERNAL_MODEL priority list.
- i18n: added `chat.grpCerebras` (vi/en/zh).

## Files changed
- New: `src/lib/llm/cerebras.ts`, `src/lib/llm/cerebras.test.ts`
- Modified: `.env.example`, `src/app/api/chat/route.ts` (+route.test.ts), `src/app/api/chat/info/route.ts` (+route.test.ts), `src/lib/llm/internal.ts` (+internal.test.ts), `src/lib/chat/replay-budget.ts`, `src/components/chat/ChatClient.tsx`, `src/components/chat/SettingsPanel.tsx`, `src/components/constellation/ConstellationClient.tsx`, `src/components/constellation-v2/ConstellationV2Client.tsx`, `src/i18n/dictionaries/chat.ts`

## Current state
- Full vitest suite: 2596/2603 pass. The 7 failures are PRE-EXISTING, unrelated to this work:
  `src/lib/search.test.ts` (drizzle query-shape mismatch) and `ConstellationClient.test.tsx`
  (WebGL unavailable in jsdom — `three.js` canvas). Verified neither file was touched.
- `npx tsc --noEmit` clean.
- NOT yet tested against the real Cerebras API — user will supply `CEREBRAS_API_KEY` and test
  live. No key was available during this session.

## Next steps
- User sets `CEREBRAS_API_KEY` in `.env` and smoke-tests a real chat turn on the
  `gpt-oss-120b-cerebras` picker option (Settings → model → "Cerebras API" optgroup).
- Watch for: whether Cerebras actually supports `reasoning_effort` the same way BytePlus does
  (docs didn't confirm this explicitly — only gpt-oss-120b tool-calling was confirmed), and
  whether the 429/503/529 retry-status assumptions hold on real traffic.

## Blockers / Risks
- None blocking. Real-traffic verification is the only remaining gap.
