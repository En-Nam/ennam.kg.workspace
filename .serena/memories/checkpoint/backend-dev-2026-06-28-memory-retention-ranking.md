# Checkpoint: backend-dev — 2026-06-28 (memory retention + recall ranking)

## What was done
- Designed + planned DAAB Phase-1 keystone deliverable "recall ranking + retention" for the `agent_context` shared-memory substrate. Spec + plan authored via brainstorming→writing-plans, hardened by an adversarial tech-consultant-vs-CTO review round.
- Plan executed (8 commits `58b76af`→`b7d2175`) + `a5a6946` (sync.Once guard on worker Stop()).
- Independently verified this session: `go build`/`go vet` OK; unit tests store+service+handler (`-race`) PASS; integration retention+recall (store, :5433) PASS; handler isolation (`KG_TEST_DSN`→:5433) PASS.

## What shipped
- Migration `000071` adds `agent_context.last_recalled_at` (forward-compat, unpopulated).
- Recall: recency decay in `fuseAgentRecall` (mem_key exempt, zero-now disables); over-fetch `max(TopK,50)` per branch; `mem_key` projected into `SearchResult`.
- **Scope-aware PII filter** (`agent_context.go:183/186`): `scope='user'` rows only for owner; project/agent shared. Closes gate #2f user-isolation hole AND fixes the prior NULL-exclusion bug (logged-in user now sees shared project rows). **Recall contract changed** — see spec §7.1.
- Retention sweep (`RunRetentionSweep`, single tx): Pass A exact dedup + Pass B growth-bound, both free-form+non-archived only, `SET is_archived=true` (no DELETE, no updated_at bump), then DELETE archived rows' embeddings. Worker mirrors OAuthRefreshWorker, started in main.go (:915-917).
- `MemorySettings` provider (system_settings + Go defaults): half_life 720h, bucket_cap 200, sweep_interval 3600s.

## Current state
- Branch `task/implement_docs_sync`; working tree clean; NOT merged to main.
- Phase-1 DAAB keystone: RBAC isolation (done) + recall ranking/retention (done). Remaining P1 keystone: `kg_search_sessions` (NOT started). See `mem:decisions/ecosystem-hermes-allocation` Phase 1.

## Next steps
- Optional PR for `task/implement_docs_sync` → main.
- Next keystone work: `kg_search_sessions` (unblocks LAAM Phase-2 consumer) OR the deferred follow-ups in `mem:backlog/agent-context-retention-followups`.

## Blockers / Risks
- None. Handler integration tests read `KG_TEST_DSN` (default :5432), NOT `KG_TEST_DATABASE_URL` (:5433) — set `KG_TEST_DSN` to the :5433 DSN when running them locally.
