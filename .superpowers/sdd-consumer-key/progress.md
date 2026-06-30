# DAAB Consumer-Key + User-Scope — SDD Progress Ledger

Plan: docs/superpowers/plans/2026-06-25-daab-consumer-key-user-scope.md
Spec: docs/superpowers/specs/2026-06-25-daab-consumer-key-user-scope-design.md
Branch: main (ennam.kg.go nested git repo)

> **CRITICAL REPO FACTS:**
> - Go changes: nested git repo `ennam.kg.go/` (own .git). Commit via `git -C ennam.kg.go`.
> - Go base HEAD = 17d0cbae24474f2b53e2bed61bca3fd99acf8752
> - Latest migration before this plan = 000069_add_supabase_user_id → new = 000070
> - Test DB: docker postgres on host port 5432 (or 5433), DSN: postgres://ennam_kg:ennam_kg_dev@localhost:5432/ennam_kg?sslmode=disable
>   KG_TEST_DATABASE_URL is the env var used by store tests; KG_TEST_DSN for handler tests.

## Tasks
- Task 1 (migration 000070 + model + store): complete (git -C ennam.kg.go 17d0cba..4f6b13d, review clean — Approved, 0 Critical/Important)
- Task 2 (DeveloperIdentity.UserID + helper): complete (git -C ennam.kg.go 4f6b13d..88f8b94, review clean — Approved, 0 Critical/Important)
- Task 3 (kg_remember/kg_recall user_id wiring, g2b live): complete (git -C ennam.kg.go 88f8b94..0d4f910, review clean — Approved, 0 Critical/Important; unit tests chosen over DB-backed — acceptable)
- Task 4 (login/JIT keys carry user_id): complete (git -C ennam.kg.go 0d4f910..0ff4f36, review clean — Approved, 0 Critical/Important; CreateUser uses post-insert SetKeyUserID backfill)
- Task 5 (dashboard for-user keys + consumer token-exchange): complete (git -C ennam.kg.go 0ff4f36..eb1ceb4, review clean — Approved, 0 Critical/Important; security: non-admin IDOR closed, consumer endpoint requires valid JWT)
- Task 6 (consumer-key policy test): complete (git -C ennam.kg.go eb1ceb4..8ae6890, review clean — Approved, 0 Critical/Important; validation pre-existed at apikey.go:341, task added formal test)
- Task 7 (T6/T7 user-isolation tests): complete (git -C ennam.kg.go 8ae6890..7600a56, review clean — Approved, 0 Critical/Important; non-vacuous isolation confirmed)
## ALL 7 TASKS COMPLETE — Go 17d0cba..7600a56

## Final Whole-Branch Review (security-reviewer, sonnet): MERGE WITH TRACKED FOLLOW-UPS

### Security Assessment: CLEAN
- D7 compliance: user_id resolved from key only, never from tool arg ✅
- Cross-user isolation (T6): `AND a.user_id = $N` in SQL filter ✅  
- IDOR in dashboard: non-admin user_id stripped ✅
- Consumer endpoint: no web-session revoke, no api_key_id update ✅
- P0 regression: empty UserID → no filter → project-scope works ✅
- SQL injection: positional $N params, no injection vector ✅

### IMP-2 FIXED: test(auth): cover internal consumer-key minting in policy test (7600a56..e4ff903)

### Tracked follow-ups (not blocking merge):
- IMP-1: Consumer-session key accumulation — each login mints a new key without deduplicating. Plan-mandated ("does NOT revoke existing key"). MUST resolve before AAAA/LAAM use consumer token-exchange in production.
- IMP-3: Admin 500 on non-existent UUID in user_id — FK rejects with 500 instead of 400. File as backlog.
- IMP-4: Q-3 non-admin self-binding not implemented — spec deviation. File as backlog.
- MIN-1: SetKeyUserID failure in CreateUser silently downgrades to project-scope memory. Logged only, not surfaced. Document.

## FINAL Go range: 17d0cba..e4ff903
