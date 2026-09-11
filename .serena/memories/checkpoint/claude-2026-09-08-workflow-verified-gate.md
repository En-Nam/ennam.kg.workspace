# Checkpoint: claude — 2026-09-08/09 (LAAM authoring gate + DAAB fixes)

## What was done
Three repos, everything committed, nothing merged, no PRs.

**LAAM** — `task/workflow-verified-gate`, 18 commits off `a3c7160`.
- Data gate: a turn with no resolved read paints nothing (`4efff7f`), extended for a submit ACK + clarification poll (`cce7775`) and for a query that ran and FAILED (`6b2a099`).
- Confirm card: a verified graph returns as `pendingGraph` behind `ask:{kind:"confirmBuild"}` with the real rows previewed (`dba1295`, `321285f`).
- `frozenLiterals` widened twice (`6fafa10`, `a809ae1`).
- AI-generate smoke-tests and routes `verify` to the editor's node badges (`c23b5d1`, `a2dedb3`).
- Task 2 withdrawn — premise was a misread; verify failures already surface as badges.

**ennam.kg.go** — `task/implement_docs_sync`.
- `2692842` `dateExpressionPattern`: a bare date expression is emitted as SQL, not bound. **This was the actual cause of every failing workflow** — DAAB bound `CURRENT_DATE - INTERVAL '30 days'` as a parameter, so every relative-date question died.
- `77e024c` bridge: `DefaultProjectID` now PINS `project_id` instead of only filling a blank. The model had composed a malformed id three times and the bridge deferred to it.

**ennam.kg.python** — `task/implement_docs_sync`, `53c4987`. Same date-expression fix in the parallel implementation. Not on the MCP path but live via `api/streaming.py`, the `process_nl_query` queue message, and the benchmark harness.

## Current state
**End-to-end verified twice.** Workflow `f44ed8cb`: 6/6 nodes green, real report table. Workflow `692ce28e` (after the bridge pin): turn 1 correctly refused to build and asked; turn 2 built and ran **8/8 green**, with no literal id anywhere in the saved graph (`useQuery` carries no `project_id` at all; `useStatus` uses a `{{steps…}}` reference) and no frozen-literal warning.

Tests: LAAM 3373 passing (5 pre-existing failures in `scripts/eval` + `constellation`, identical on `a3c7160`); Go `./...` all green, build + vet clean; Python 51/51 nl_query, ruff clean.

Docker `daab-server`, `daab-worker`, `daab-indexer`, `daab-bridge` rebuilt and restarted — all running the new code.

## Next steps
- Open PRs when wanted. The two DAAB fixes sit directly on `task/implement_docs_sync`, a branch whose name says docs sync — worth splitting before review.
- Demo data ends **2026-08-04**, so any "last month" question returns 0 rows from September onward. The workflow runs and reports that honestly, but for a live demo either reseed or ask with an absolute month.

## Blockers / Risks
- **Two divergent NL→SQL implementations.** Go has `value_is_expression` plus five expression fallbacks; Python has one and no `value_is_expression` at all, despite the planner prompt teaching the model to set it. Column comparisons, scalar subqueries and column±interval windows still fail on the Python path. Do NOT port the remaining four by hand — that is how they drifted. Decide whether Python calls Go, or whether both share a fixture-driven suite.
- **`closePlan` poll-as-producer** (workflow `6d8ab53a`): may have self-resolved — the `isFailedQuery` filter removes the dead chains closePlan was searching over, and it did not recur in either later run. Unproven. A matched test pair failed to reproduce it and no guard was added, deliberately: that file records two earlier guards reverted for being too broad. If it recurs, capture the real trace with `WF_AUTHORING_DEBUG=1` and read the `[wf-authoring][closure]` lines.
