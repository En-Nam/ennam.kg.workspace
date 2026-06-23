# Checkpoint: claude-opus — 2026-05-12

## What was done
- Implemented all 24 tasks of the Agentic AI Chat Engine across 3 services
- Python: Created `ennam_kg/agentic/` package (8 modules + 8 test files, 63 tests)
- Go: DB migration, model fields, SSE routing, clarification endpoint, metadata store
- Frontend: TypeScript types, SSE handler extension, useAgenticStream hook, 9 UI components, chat wiring
- Fixed lint issues: removed unused `json` import in prompts.py, auto-formatted all agentic files

## Files changed

### Python (ennam.kg.python) — Created
- `src/ennam_kg/agentic/__init__.py` — Package exports
- `src/ennam_kg/agentic/types.py` — AgentConfig, LoopState, ToolCall, ToolResult, AgentState
- `src/ennam_kg/agentic/loop_guard.py` — LoopGuard anti-pattern detection
- `src/ennam_kg/agentic/state_store.py` — Redis pause/resume (600s TTL, getdel)
- `src/ennam_kg/agentic/sql_validator.py` — SQL security validator
- `src/ennam_kg/agentic/tools.py` — KGToolFactory with 7 tool definitions
- `src/ennam_kg/agentic/prompts.py` — 5-layer prompt assembly
- `src/ennam_kg/agentic/engine.py` — AgenticEngine FSM loop
- `src/ennam_kg/api/agentic.py` — POST /api/v1/agentic/stream
- `src/ennam_kg/main.py` — Added agentic router
- `tests/test_agentic/` — 8 test files (63 tests total)

### Go (ennam.kg.go) — Created/Modified
- `db/migrations/000044_agentic_ai_support.up.sql` — agent_tool_calls + clarification_sessions tables
- `db/migrations/000044_agentic_ai_support.down.sql` — Rollback
- `internal/models/thread.go` — 6 agentic fields on ThreadMessage
- `internal/service/sse_stream.go` — agentTimeout, pythonEndpoint, ClarificationSessionID
- `internal/handler/ai_stream.go` — HandleClarification endpoint
- `internal/store/thread_message.go` — UpdateAgentMetadata method

### Frontend (ennam.kg.next) — Created/Modified
- `src/types/agentic.ts` — All agentic TypeScript types
- `src/lib/streaming/sse-handler.ts` — 8 new agentic callbacks
- `src/hooks/use-agentic-stream.ts` — useAgenticStream hook
- `src/components/chat/TierSelector.tsx`
- `src/components/chat/PhaseIndicator.tsx`
- `src/components/chat/ToolCallStepRow.tsx`
- `src/components/chat/AgenticProgress.tsx`
- `src/components/chat/CountdownRing.tsx`
- `src/components/chat/ClarificationPrompt.tsx`
- `src/components/chat/KgNodeChip.tsx`
- `src/components/chat/MultiSourceResults.tsx`
- `src/components/chat/ChatMessage.tsx` — Wired agentic components
- `src/components/chat/QueryInputBar.tsx` — Added TierSelector

## Current state
- All Python tests pass (63/63)
- Go build clean
- Frontend build clean (37 pages, 0 TS errors)
- Ruff lint + format clean
- **Nothing committed yet** — all changes are uncommitted in working directories

## Next steps
- Commit changes in each sub-repo (ennam.kg.python, ennam.kg.go, ennam.kg.next)
- Run database migration 000044 on dev/staging
- Provision read-only DB roles for execute_sql safety
- Integration test with live Anthropic API
- Wire useAgenticStream into the chat page's message flow (currently components are added but not connected to actual streaming)

## Blockers / Risks
- Read-only DB roles must be provisioned before execute_sql is safe in production
- The chat page needs to be updated to actually use useAgenticStream (components are wired into ChatMessage but the page-level hook connection is pending)
- No end-to-end test with live Anthropic API yet
