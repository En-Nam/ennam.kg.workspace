# Checkpoint: controller — 2026-11-15 (afternoon addendum)

## What was done
- Production DB facts: DAAB, LAAM and pharmacy DBs share one AWS RDS PostgreSQL 15.17 instance. Ran every migration and the Go suite on pg15.
- Reaper fix: go 7bacc4b removed `pg_input_is_valid`, which does not exist on PG15.
- Free questions on RDS (plan 2026-11-15-free-questions-rds-pg15):
  - portable view casts
  - keyword SQL guard, also blocking ts_stat/ts_rewrite
  - RDS-compatible readiness
  - deploy checklist fixes
- Pack semantic layer v1, retail + pharmacy (plan 2026-11-15-pack-semantic-layer, 7 tasks, all reviewed, final review done):
  - semantics.yaml loader with lazy, memoized merge
  - term:<key> derived tables in hardenPlan
  - column comments
  - per-project business-definitions block in the planner prompt, with store-local today
  - terms_used / definitions_used
  - 18 retail terms + 4 pharmacy terms, each equal to its standard metric
  - eval: 100% retail, 100% pharmacy (14/14)
- Browser E2E on simulated RDS:
  - weekday question → 60/59/53, matching the metric, with definitions_used
  - PH-003 refused
  - flags off → metrics only

## Heads (not pushed)
- go 3faeff2
- packs 9fc3830
- root 8258e52
- LAAM unchanged since 89ddad70

## Current state
- e2e stack running with flags OFF; grants restored.
- Deploy Monday per docs/deploy/2026-11-16-task-pos-data-model-checklist.md:
  - packs 0.7.0 has never been published
  - pre-tag semantic test step
  - landed DB created manually on RDS (no blind cross-DB REVOKE)

## Next steps
- Huy Trello reply: draft is in scratchpad huy-reply-draft.md. Owners are TBD; the user has not yet approved posting.
- Follow-ups:
  - free-question results should include the applied date range (the LAAM model doubted the numbers)
  - backlog/packs-ci-semantic-tests
  - backlog/daab-free-questions-sql-parser-guard
- Enabling free questions in prod: devops creates ennam_landed on RDS, then follow checklist §7.

## Blockers / Risks
- CI does not run the real-pack semantic tests; the manual pre-tag step covers it.
- Pre-existing flaky test: TestAIQueryUsage_RecordedBeforeTerminalAndZeroIsExplicit.
