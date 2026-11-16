# Checkpoint: controller-pos-data-model — 2026-11-14

## What was done
- WS0 store-scoped authorization COMPLETE (11/11). E1 browser E2E PASS on isolated stack (laam_e2e :3110, bridge :18765, kg-server :18080 / ennam_kg_e2e):
  member.demo (PH-001) home/chat/manual+scheduled workflow PH-001 only; scope removed → schedule paused data_access_lost + notification; restored → resumed; owner.demo sees PH-001..005. Screenshots e1/shot-01..07.
- Final whole-branch reviews (opus x2): go With fixes (I1 CI skip), LAAM Yes (0/0/7). Fixed: go 0c224a8 CI WS0 gate, 261dca4 WARN + runbook; LAAM 490441db, 90043580 (project id lower-case in header + ticket pid).

## Files changed
- go: .github/workflows/ci.yml, cmd/kg-server/main.go, docs/ws0-delegation-runbook.md
- LAAM: src/lib/connectors/mcp/{delegation.ts,client.ts,org-store.ts,+tests}, docs/DEPLOYMENT.md

## Current state
- Heads: go 261dca4, LAAM 90043580, branch task/pos-data-model. Not pushed, no PR (user said stay on branch).
- E1 stack still running (e2e-down.sh + e1/e1-down.sh to stop; LAAM pid e1/laam.pid, tick e1/tick.pid).

## Next steps (product decisions for user)
- Member chat can't find "net sales": intel_list_metrics returns bare keys (no labels); member lacks mcp__ DAAB tools (L2 M-4).
- No-store users still see data-source quick tools (400); English-only refusal; brief prebuild acts as first member; success-path audit log in DAAB; admin-no-row executive persona.
- Trello reply to Huy (draft, not posted); KG backfill of WS0 decisions.

## Follow-ups done (same day, user asked: all 6 in order 2→1→5→4→3→6)
- 2 hide denied data-source tools/notes (LAAM 800fdc29, f03daa2b); 1 metric labels from pack glossary (d1b4fb6a);
  5 DAAB audit line "delegated data access" (go bdf2cb0); 4 prebuild as system w/ group stores, explicit allStores (6a5ee1dd, a7002b9a);
  3 refusal wording + run banner + paused line (b028e90b, 11b25c36); 6 People default role + Change role (242abced, 2cae9026); test fix 3a14dbfa.
- All reviewed (opus/sonnet), E2E verified on :3110 (shots 08-11). Heads: go bdf2cb0, LAAM 3a14dbfa. Not pushed.
- Parked: system meter (userId null) for prebuild; run-banner text not translated client-side; catalogue calls not audited.

## Blockers / Risks
- Turbopack dev HMR can leave a stale module after import-shape changes → restart dev (seen once, fail-closed).
