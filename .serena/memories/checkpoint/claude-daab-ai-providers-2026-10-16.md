# Checkpoint: claude (DAAB AI providers) — 2026-10-16 — Claude 5.5 provider, function registry, pricing units

## What was done
- AI function registry (ennam.kg.go `models.AIFunctions`) 9 -> 16: + schema_description, resolution_verify, resolution_resummarise, cross_edges, insight_generation, format_detection, nl_summary (health_check and stream deliberately not routable). Python (ennam.kg.python) now tags previously untagged LLM calls: cross_edges, insight_generation, format_detection, nl_summary; implicit scorer reuses kg_implicit_scoring, table descriptions reuse kg_description. 694 untagged rows existed in ai_usage_logs (all on BytePlus). A function left on "auto" behaves as before.
- EXTRACTION_LLM_* direct-BytePlus bypass in daab-worker KEPT on purpose (BA-031: no circuit breaker, 600s timeout). While EXTRACTION_LLM_URL is set, `ai.model.extraction` has NO effect and those calls are not in ai_usage_logs.
- Claude providers (type anthropic_api, base https://api.anthropic.com): "Claude Haiku 5.5" prio 70 and "Claude Sonnet 5.5" prio 71, one provider per model because cost is per PROVIDER. Key = workspace .env ANTHROPIC_API_KEY, stored encrypted via PATCH /api/v1/ai-providers/{id} (the dashboard cannot edit a provider's key). Both health-check OK.
- Cost unit CHANGED: provider rates are now microdollars per 1,000 tokens (was per token) so Haiku $0.10/$0.50 per M fits an integer: Haiku 100/500, Sonnet 2000/10000. `models.TokenCostMicrodollars` (round to nearest) replaces inline math in selector.go and cost_ceiling.go. Column/JSON names still cost_per_*_token (documented in the struct). Fixtures x1000. Verified live: 42 in + 26 out on Haiku = 17 microdollars.
- Adapter anthropic.go (+ Python direct_client.py mirror): omit temperature for 5.x / Opus 4.7+ (400 otherwise); send thinking {type: disabled} for Haiku 5.x ONLY (Haiku thinks by default and thinking eats tight max_tokens; Sonnet 5.5 400s on "disabled"). Python agentic engine untouched (max_tokens 4096, handles thinking blocks itself).
- DB cleanup (hard delete + CSV backups of usage rows in the session scratchpad, /tmp so ephemeral): z.AI (578 usage rows), Alibaba Token Plan (43), Qwen 3.6 flash (2814). Providers now: BytePlus Ark (50), Claude Haiku 5.5 (70), Claude Sonnet 5.5 (71). ai.model.agentic was Alibaba qwen3.7-plus -> reset to auto. ai.model.nl_query_intent = Claude Haiku 5.5 (user's choice). nl_query_intent already passes EnableThinking=false for Qwen; the Anthropic adapter ignores that flag (Haiku always non-thinking, Sonnet does not think).

## Files changed
- ennam.kg.go: internal/ai/{anthropic,cost_ceiling,selector}.go (+tests), internal/models/{ai_function,ai_provider}.go + ai_provider_cost_test.go, internal/handler/{ai_functions,extraction}_test.go, internal/integration/ba031_ga_test.go
- ennam.kg.python: src/ennam_kg/ai_client/direct_client.py, ingestion/pipeline/cross_edges.py, kg_generator/{description_generator,implicit_detector}.py, streaming/{engine,format_detector,insight_generator}.py, tests/test_ai_request_types.py, tests/test_ai_client/test_direct_client.py

## Current state
- Pushed on task/demo_pharmacy: ennam.kg.go ad02a23, ennam.kg.python b370569. Containers rebuilt (kg-server via air, indexer, worker). Go tests (ai, models, handler, service, store) pass; Python 919 pass; `-tags integration` only COMPILES (needs DB).
- NOT in git: the provider rows, key and prices above live in the daab-postgres DB only.

## Next steps
- Assign `agentic` to a tools-capable model (Claude Haiku/Sonnet): BytePlus gpt-oss-120b has supports_tools=false, so auto leaves agentic chat on a model DAAB itself marks as non-tool.
- Haiku >100k-prompt tier ($0.50/$2.50) cannot be expressed (flat per provider).
- BytePlus gpt-oss truncates tight max_tokens (nl_summary 500 / probe at 120 -> finish_reason truncated); check if summaries are cut in practice.
- Optionally rename cost_per_*_token columns (needs migration + API contract change).

## Blockers / Risks
- Key lives only in .env + encrypted DB column; a fresh DB needs the PATCH again.
- Unformatted Go files pre-existed (ai_provider.go etc.); only my files were gofmt'd.
