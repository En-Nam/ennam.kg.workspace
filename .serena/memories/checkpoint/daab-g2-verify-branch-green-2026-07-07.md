# Checkpoint: daab-g2-verify (branch-green) — 2026-07-07

## What was done
- **Strategic re-orientation of DAAB direction.** Verified from SOURCE (not memory) that the memory-of-record keystone is **already built**, not unstarted: `internal/handler/agent_context.go` + `internal/store/agent_context.go` (kg_remember/kg_recall), migrations `000068_agent_context`, `000069_add_supabase_user_id`, `000070_add_api_key_user_id`, `000071_agent_context_last_recalled_at`; consumer/project-scope guards in `middleware/project.go`+`auth.go`; RBAC isolation keystone gate = PASS (`mem:decisions/daab-rbac-isolation-keystone-gate-verdict`). **Diagnosis: the critical-path work is done but stranded on `task/implement_docs_sync` — 55 go commits ahead of main, unmerged.** Recent sessions (fuzzy-hub/danger-stratum drains, kg_search_sessions) were data-quality polish off the critical path (kg_search_sessions was CTO-DESCOPED, D4). Right next direction = **close g2 + MERGE to main**, then D3 consumer-key class → issue AAAA/LAAM keys.
- **Ran gate g2 verify (user asked).** Go: `go test ./... -race -count=1` → **22/22 packages GREEN** (handler 36.8s, service 38.1s, bridge, store, middleware, supabaseauth). g2b user-scope recall contract explicitly green: `TestRecall_WiresUserIDFromIdentity`, `_EmptyUserIDForProjectKey`, `_DifferentUsersGetDifferentParams`, `_UserScopeIsolation`, `_ProjectOnlyKeyUnchanged`. `go vet` clean.
- **Ran full Python suite, chunked per-subdir (RAM-safe, torch isolated).** Total **633 passed / 1 failed / 20 deselected** (634 collected matches). The 1 failure `tests/extraction/test_parser.py::test_drops_out_of_range_span_and_orphan_relation` is **PRE-EXISTING, not a branch regression** — neither `parser.py` nor the test is in `main..HEAD` diff, so it fails on main too. 20 deselected = e2e/smoke/accuracy (need live Docker stack + `KG_TEST_DATABASE_URL`).
- **Secured secrets:** added `/kg-service/` to root `.gitignore` (was `?? kg-service/` untracked, 5 `.env` files with live DB password / API / encryption keys). `git check-ignore` confirms ignored. (`.gitignore` mod uncommitted — see below.)

## Files changed
- `.gitignore` (workspace root) — added `/kg-service/` under secrets section. **UNCOMMITTED in working tree.**
- No source code changed this session (verify-only + gitignore).

## Current state
- **Branch `task/implement_docs_sync` is merge-ready**: no regression from its 55 go commits; the 1 python failure is old debt already on main.
- Go: green with `-race`; NOT-run-locally = integration DB tests (`-tags=integration`, need daab-postgres :5433 DSN — classifier blocked printing the password, correct) + golangci-lint (not installed local). Both should run on CI to formally close g2a "CI-green".
- Python: 633/634 unit green.
- `.gitignore` change pending commit.

## Next steps
- Commit `.gitignore` (`chore: gitignore kg-service local env secrets`).
- **MERGE `task/implement_docs_sync` → main** across workspace + nested subrepos (ennam.kg.go / .python are nested git — `git -C`). Highest-leverage: unstrands the ecosystem critical path.
- Close g2a formally on CI: integration isolation test + golangci-lint.
- Then D3 consumer-key class → issue AAAA/LAAM keys → confirm LAAM actually calls kg_search_sessions scope=monitoring (out-of-repo).
- Deprioritized: 95 `needs_review` (manual polish), BA-033 slice 2 (Gate B product decision, `mem:decisions/ba033-slice2-deferred` / `mem:backlog/ba033-slice2-readiness-path` — Gate A now GREEN, Gate B still binding).

## Blockers / Risks
- Pre-existing python test-debt (`test_parser.py` span clamp-vs-drop) — clean up separately, not a merge blocker.
- Merge touches nested repos; workspace-root HEAD won't move sub-repo HEADs (`mem:ennam-go-is-nested-git-repo`).
