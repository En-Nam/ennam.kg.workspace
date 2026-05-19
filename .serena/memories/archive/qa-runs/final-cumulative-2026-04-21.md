# Final Cumulative QA Report — 2026-04-21

## Stats: 52 bugs found, 42 fixed (81%), 10 remaining
## Coverage: 19/21 BAs, 105/122 APIs, 23/23 pages, ~63% business logic

## 10 Remaining Bugs
- P1: OAuth header format (x-api-key vs Bearer) — blocks all AI calls
- P1: Python worker stale API key — infra config
- P2: Connection test ignores ssl_mode, history ASC not DESC, regex not enforced, max_per_source not enforced
- P2: Ctrl+K search crash (cmdk), 8 KG viz features deferred
- P3: Benchmark tooltip, chat-demo aria-labels

## Remaining Test Coverage Gaps
1. AI pipeline end-to-end (NL→SQL→results) — blocked by OAuth 401
2. MCP Bridge (BA-002) — needs MCP client
3. Code Indexing (BA-003) — needs repo source
4. Gate 2 completeness (BA-005) — not implemented
5. Smart context pipeline (BA-020) — not implemented
6. Full RBAC matrix (all role×endpoint combinations)
7. Performance tests (8 metrics)
8. E2E browser flows with real data

## Full Report: ennam.kg.requirements/QA/reports/final-cumulative-2026-04-21.md
