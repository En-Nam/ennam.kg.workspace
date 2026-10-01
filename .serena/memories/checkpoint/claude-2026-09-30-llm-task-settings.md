# Checkpoint: claude — 2026-09-30 (LAAM per-task LLM settings)

## What was done
- Settings → AI models (`/settings/ai-models`, owner/admin only): per-function model + reasoning effort for summarize / workflow_generate / workflow_review / custom_agent_generate / workflow_agent_node. Empty = env behaviour (zero regression). Two effort boxes only for workflow_generate + workflow_agent_node.
- Design: pure rules `src/lib/llm/tasks.ts`; DB store `task-settings.ts` (5s cache, fail-soft, audited saves); `resolveTask` + `ctx: { task, model? }` in `internal.ts`; adapters accept `reasoningEffort` and export `envReasoningEffort(hasTools)`; `task-config-view.ts` feeds GET/PUT `/api/settings/llm-tasks` and the page.
- Also fixed Cerebras streaming: reads `delta.reasoning` (not `reasoning_content`).
- Earlier same day: CommandCode provider was built, benchmarked (slower than BytePlus in real chat) and fully REVERTED; Cerebras re-measured for workflow authoring (ab-branch 1/10, ab-daab 1/10 vs BytePlus ~10/10, ~7/10) — keep BytePlus for authoring. `.env` currently has INTERNAL_MODEL=gpt-oss-120b-cerebras (user's choice) — that now can be overridden per task in the UI.

## Files changed
New: src/lib/llm/{tasks,task-settings,task-config-view}.ts(+tests), src/app/api/settings/llm-tasks/route.ts(+test), src/components/settings/AiModels{Manager,Title}.tsx, src/app/(app)/settings/ai-models/page.tsx, src/i18n/dictionaries/ai-models.ts, drizzle/0019_llm_task_settings.sql, docs spec+plan. Modified: adapters (byteplus/cerebras/deepseek), internal.ts, workflow/ollama.ts, workflow/runtime.ts, chat + workflows + custom-agents routes, generate/chat route (reads model once), schema.ts, SettingsMenu, settings dictionary, CHANGELOG.

## Current state
- 13 commits on task/improve-workflow (NOT pushed). Migration 0019 applied to the dev DB; container laam-v2-app rebuilt with everything. Full suite: 3670 pass, 6 pre-existing fails (scripts/eval/runner.test.ts x2, ConstellationClient.test x3, schedule.test x1); tsc: 1 pre-existing error (executors.test.ts).
- Live-verified on :3900: GET/PUT/validation/audit; stored workflow_review=deepseek-v4-pro/high moved review 3.9s→22.5s, reset back to 4.6s. NOT verified live: the 403 for member/viewer (only one user exists; auth re-reads role from DB by sub) — unit tests only. UI not looked at in a browser.

## Next steps
- User to open /settings/ai-models and try it. Deferred minors: M1 stale effort draft after model switch; M2 cache race on save; M3 stored effort survives model fallback; M4 no-op PUT writes audit row; M5 select shows non-option value when provider unavailable; M6 agent-node model not pinned per node (comment in executors.ts:382 outdated); M7 PUT errors Vietnamese only.
- Consider DAAB rate limit (120 calls/60s) if a very fast model is chosen for workflow_agent_node.

## Blockers / Risks
- Bash "-n" anywhere in a command line trips the block-no-verify hook on git commits (keep sed -n out of commit commands); task-done needs a command that prints at least one line.
