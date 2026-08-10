# Checkpoint: claude-code — 2026-08-10

Four changes for LAAM↔DAAB. Three committed and measured good; the fourth+fifth measured NO
effect and are UNCOMMITTED, awaiting a call from the user.

## Committed
| Commit | Repo | What | Measured |
|---|---|---|---|
| `41f42b9` | ennam.kg.go | connection instructions emit `project_id` / `data_source_id` verbatim | Q1 5→2 hops |
| `2db0bd9` | LAAM | `listTools` stops discarding MCP `instructions`; fed to system prompt as `serverNotes` (labelled `[slug]`, capped 2k, enabled-tools only, subordinate to operator rules) | ditto — DAAB fix was invisible without this |
| `02e7d13` | ennam.kg.go | `kg_query_datasource` description no longer routes DATA questions to `kg_search`/`kg_describe_table` | Q2-after-Q1 5→2 hops; schema tools 3/5 runs → 0/6 |
| `a1892d5` | ennam.kg.go | `measure_ambiguity.go` — names the measure a bare superlative was ranked by | fires on every verbatim run, silent when the measure is named; both verified live |

Hop counts from LAAM `chat_tool_call`; question text + notes from DAAB `ai_queries`.

## UNCOMMITTED — measured, did NOT work
See `mem:decisions/tool-result-notes-ignored-by-model` for the numbers.
- `ennam.kg.go/internal/bridge/schema.go` (+test): removed "Prefer questions with aggregates or
  limits", a clause that told the caller to restate the question WITH a metric while P1/P3 tell
  it to keep the user's wording. Rewrite rate 50% → 46%, i.e. unchanged.
- `LAAM/src/lib/agent/rewrite-notice.ts` (+2 test files) + orchestrator wiring: disclose-only
  note when the sent query ≠ the user's words. 0 of 4 rewritten runs disclosed anything.

Both are CORRECT changes (the contradiction was real; the note is proven to attach on real wire
shapes) that simply do not move behaviour. Keep-or-revert is the user's call. Nothing is staged.

## State
Go: `go test ./internal/bridge/ ./internal/service/ -race -count=1` + vet green.
LAAM: tsc clean; 2611 pass / 7 fail — those 7 (`search.test.ts`, `ConstellationClient.test.tsx`
WebGL) fail identically on a stashed clean tree = PRE-EXISTING.
Nothing pushed. `ennam.kg.go` on `task/implement_docs_sync`, LAAM on `task/improve-mcp-tool-call-voice`.

## Next
1. The disclosure problem needs a UI channel, not another note — see the decision memo.
2. LAAM rewrites the user's question ~50% of the time. Unsolved, and every note-based remedy is
   now measured as ineffective.
3. Multi-project keys: `composeConnectionInstructions` enumerates ≤3 projects; above
   `maxEnumeratedProjects` the discovery hop returns.
4. `cfg.DefaultProjectID` is EMPTY in the passthrough compose deployment → `serve.go`'s
   project_id auto-inject is dead there. Do NOT add `KG_PROJECT_ID` to compose (tenancy change).
5. Pre-existing, deliberately untouched: gofmt drift on `kg_get_master_record` in schema.go, and
   a UTF-8 BOM at the top of schema_test.go.
