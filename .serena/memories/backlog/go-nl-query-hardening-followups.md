# NL query hardening follow-ups (from 12-question pharmacy demo run, 2026-08-03)

Ran all `demo_mockdata/demo_questions.txt` through the fixed pipeline (`task/mcp-query-datasource`). 10/12 answerable; 3 hardening items, none blocking:

1. **Flaky intent JSON (Q3, 1-in-13):** "invalid character 'r' after object key" — likely MaxTokens=1024 truncating mid-JSON on complex plans (`query_intent.go` AIRequest). Cheap fix: raise to 2048. Retry of same question completed fine.
2. **SQL generator emits invalid GROUP BY (Q8):** plan mixed non-aggregated select columns with aggregations → `pq: column ... must appear in the GROUP BY clause`. `sql_generator.go` could auto-add non-aggregated select columns to GROUP BY (deterministic fix). `retryWithSimplification` doesn't help (only drops ORDER BY).
3. **Kitchen-sink questions hit 30s executor timeout (Q11 "compare sales, refunds, variance, claims"):** multi-fact join explosion → `canceling statement due to user request`. Options: teach tool description to tell the model to split (already partially there); or agentic tier decomposition. Not a bug per se.

Results matched expected_findings where comparable: Q1 Sarah Miller EMP-0006 $3689.32 (finding #1), Q10 PH-004 highest claim rejection (finding #5), Q6 receipt TXN-0000001 = manifest sample. Q12 (vague "sensitive activities") correctly returned clarification_needed with sensible options.

Related: `mem:backlog/go-nl-query-intent-parse-openai-providers` (RESOLVED by commit 92c62e0 — keep for history), `mem:checkpoint/claude-2026-08-03`.
