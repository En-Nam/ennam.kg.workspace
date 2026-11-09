# Checkpoint: daab-billing-fastfail — 2026-11-06

## What was done
- Owner rule "charge a DAAB call only if it spent LLM API tokens" implemented across DAAB + LAAM.
- DAAB `a85156f`: ai.UsageTally on ProcessQuery ctx (Selector.Send + judge "on" mode count into it; stamps ai_usage_logs.run_id = ai_queries.id); migration 000095 ai_queries.ai_tokens_used/ai_calls written BEFORE terminal status; exposed on GET /ai-queries/{id}. Bridge emits MCP `_meta` "ennam/billing": pending{work_id} on kg_query_datasource, settled{work_id,billable_calls} on terminal status, settled{1} on kg_process_drafts. Source executor: 10s bounded connect, ErrSourceUnreachable (no retry, user-facing message), 30s per-source fail-fast memory.
- DAAB `b16eb07`: lib/pq v1.10.9 sql.Open ignores ctx on dial (75s despite 10s ping) → open via pq.NewConnector + sql.OpenDB (now 10.05s).
- LAAM `b3ccf7e2`: shared ledger src/lib/usage/org-mcp-billing.ts used by chat meter (+TurnUsage.daabOpen) and workflow MCP node; callTool hands `_meta` out of band; ExecuteHooks.onOrgMcpResult.

## Current state
- All green: Go make test, LAAM npm test (8125), tsc, test:int (1365). Live: cache-hit query billed 0; cache-miss run billed 4 of 5 (one cache hit); stored = outbox = Admin usage_event exactly.

## Next steps / risks
- Workflow: submit and status are separate nodes → submit node always charged as abandoned (no-token queries not free in workflows). Needs run-scoped (persisted) ledger.
- Now free: all DAAB tools except query pair + kg_process_drafts (incl. kg_insert_datasource_row writes). Successful plan-cache hits free.
- Deploy DAAB bridge before LAAM (old bridge ⇒ everything free).
- Unreachable-source path not measured live end-to-end through LAAM (RDS became reachable).
