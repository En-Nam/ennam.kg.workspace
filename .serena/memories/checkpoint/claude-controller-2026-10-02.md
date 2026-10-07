# Checkpoint: claude-controller — 2026-10-02

## What was done
- SDD execution of Proactive Intelligence plans (A demo data, B DAAB metrics layer, C tabular upload, D LAAM engine, E LAAM experience). Ledgers: workspace `.superpowers/sdd/2026-10-02-pi-*/progress.md` (every ruling is a `Ruling:` line).
- Plan A tasks 1-9; B tasks 1-18; C tasks 1-13 (safe steps); D tasks 1-23 (safe steps); E tasks 1-22 (safe steps); final DAAB<->LAAM contract review + fixes (bridge 2f8b46c, LAAM 52fcb1a).

## Repo HEADs
- ennam.kg.go 2f8b46c; LAAM 52fcb1a (branch task/proactive-intelligence); ennam.kg.python e10dcb9; ennam.kg.next f294b4d; workspace 2464dcf (branch task/demo_pharmacy).

## HELD for user (live DB / live stack / security-sensitive)
- A Task 10: reload pharmacy_demo (:5500 demo DB) via load_pharmacy_demo.sh.
- B Task 19: migrate + docker rebuild + kg-packs import/run on the registered project.
- C Task 13 Step 3 (live import + targets upload + psql) and C Task 12 Step 7 (browser).
- D Task 23 Steps 1/2 (seed --fake-run on LAAM :5500; curl tick) ; D Task 20 seed script written NOT run.
- E: migration 0021 intel_brief NOT applied; Playwright smoke + 6 screenshots + contrast check NOT run; seed-e2e-users.sh NOT run.
- Master M4-M7 (real mapping import, ground-truth check, E2E, 11-criteria report).

## Known pre-existing failures (identical at baseline)
- LAAM: scripts/eval/runner.test.ts x2, ConstellationClient.test.tsx x3, schedule.test.ts executeRunRow x1; eslint set-state-in-effect in ChatClient.tsx (+1 new), prefer-const route.ts:524.

## Next steps
- User decisions listed in the final message; then run held steps in order: A10 -> B19 -> C13 step 3 -> D23 steps 1/2 -> apply LAAM migration 0021 -> E22 step 7 -> M4-M7.

## Blockers / Risks
- Drizzle repo parity (repo.db.test.ts harness not implemented); concurrency/SKIP LOCKED unverified on real Postgres; TOCTOU on manual-run guard (needs partial unique index); scenarios without backtest interval always degraded (verify on real data).
