# Checkpoint: claude — 2026-09-30 (LAAM CommandCode provider) — REVERTED

## Outcome
CommandCode Provider API was integrated (adapter, picker, router, pricing, eval provider), tested, then **fully reverted by the user's decision** (not committed; `git checkout` + files deleted; app image rebuilt without it). Reason: slower than BytePlus gpt-oss-120b in real chat.

## Findings worth keeping
- Real chat "Get 5 first transaction in database": gpt-oss-120b 18s; gpt-6-luna 31s (sent the SAME DAAB query twice → extra round); deepseek-v4.1 31s (728 out tokens vs 376). DAAB side ≤2s, so time is LLM.
- Per-request (real 13-tool catalog): gpt-oss 3.3/2.6/1.0s (tool round / after result / first token); luna 3.1-4.0/3.6-3.9/1.3-1.5; deepseek 4-5.5/4.8-7/1.9-3.7; nemotron 2.3/2.6/1.2 (fastest). CommandCode = reseller hop, ~20-50% slower per request. reasoning_effort barely changes it.
- Eval (17 scenarios, k=5; parallel runs so ignore ms): sel/args/ground/term/write/block — gpt-oss 92/83/75/89/0/30%; nemotron 92/83/48/91/0/40% (web-research-loop up to 24 tool rounds); luna 100/100/75/89/100/100%. Luna was best quality. Scorecards: LAAM/.serena/qa/eval-2026-09-30-cc-compare-*.md (untracked).
- CommandCode API facts: base https://api.commandcode.ai/provider/v1, OpenAI-compat, json_object/reasoning_effort(low|medium|high|xhigh|max)/tools/tool_choice all accepted on the 5 probed models; meta/muse-spark-1.3-contributor = 403 on this account; glm-5.3-flash ~13s per tool round.
- Gotchas hit: zsh does not word-split unquoted vars (`set -- $cfg` broke a parallel eval launch — use a bash script); eval scorecard filename was date-only so concurrent runs overwrote each other (fix was reverted with the rest; reapply with an EVAL_LABEL suffix if needed).
- Faster alternative already in LAAM: Cerebras gpt-oss-120b (~0.5s).

## State
- LAAM tree back to baseline (pre-existing: 2 failing scripts/eval/runner.test.ts tests, 1 tsc error in executors.test.ts). `.env` still holds COMMANDCODE_API_KEY (unused).
