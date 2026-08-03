# BUG (HIGH, blocks mcp-query spec) — Go async NL query fails with openai-type providers

**Found:** 2026-08-03, live test on fresh pharmacy_demo dataset (project 4ad7a5fa, ds 3c7af733).

`POST /api/v1/ai-queries` (the exact path `docs/mcp-query-datasource-spec.md` §2 plans to expose as `kg_query_datasource`):

1. **Aggregation question** ("Which employee processed the most refunds by total refund amount?") → `failed`: `intent parsing failed: ... invalid JSON from AI: json: cannot unmarshal object into Go struct field QueryPlan.plan.aggregations of type string`. Active providers are BytePlus Ark `gpt-oss-120b` (prio 50) + z.AI `glm-5.2` (prio 60) — openai-type; model emits `aggregations` as objects, Go parser (`internal/service/nl_query.go` QueryPlan) expects strings. The Anthropic tool_use forced-schema trick (Python engine) doesn't apply on this Go path.
2. **Simple list question** ("List all stores with their name and city") → record `status=failed` with `error_message=clarification_needed` — clarification flow may be conflated with failure on this async path; verify before exposing via MCP.

**What DOES work:** KG-based schema filtering picked the right tables (refunds/refund_items/employees/cash_drawers) — failure is purely intent-parse response shape.

**Impact on spec:** §2 claims the pipeline "đã chạy production cho web app DAAB" — that was under the earlier provider setup. With current openai-type providers the async path breaks on aggregations (= most pharmacy demo questions). Fix options: (a) tolerant QueryPlan unmarshal (accept object or string aggregations), (b) structured-output/function-call forcing for openai-type providers, (c) route the MCP tools to the Python streaming/agentic path instead.

**Related:** `mem:decisions/agentic-engine-lessons`, archived `archive/phases/be-bug-python-intent-parse-resolved` (same bug class, Python side, fixed earlier).
