# Checkpoint: daab-billing-fastfail (Tasks C/D) — 2026-11-06

## What was done
- LAAM e4773e4c: workflow DAAB billing scope = whole RUN. Ledger on workflow_run.daabBilling (migration 0051, applied to live laam DB); lib/workflow/run-billing.ts applies node markers + outbox insert in ONE row-locked tx (recordUsageIn); closeRunDaabBillingSafe at every terminal path (run.ts finalize, resume finalize + 2 early exits, tickResume org_not_active, PATCH cancel, boot sweep preset_test). Authoring verify: in-memory ledger closed by route (closeOrgMcpBilling).
- Intel: providerForProject(…, {onOrgMcpResult, path}); brief prebuild = one intel_briefing meter; intel chat = turn meter (chatMeter hoisted in chat route); other paths unmetered + loud log on billable marker.
- LAAM 09048d45: int test intel-in-chat stored = outbox.
- 3ee7e73b earlier: retry meta fix.

## Current state
- tsc clean, db:generate no drift, test:int 102 files green, npm test green (UseTemplateDialog flaky under load 2/3 full runs; untouched).
- Live: uncached workflow query 14,195 tokens → 1 billed (outbox = Admin, 1000 charged); cached → 0 events.

## Next steps / risks
- Home brief not verified live (test org has no business_project).
- Early return in chat route between chatMeter creation and streamMainTurn skips finish() (harmless while intel emits no markers).
- applyRunDaabResults tx failure (e.g. payer lookup) drops that node's markers → under-bill, logged.
