# Checkpoint: claude — 2026-08-05 (tool_call name sanitize fix)

## What was done
- User ran 12 QA questions against DAAB project "Michael Pharmacy Chain" via `/chat` and `/constellation` (Larvis), both real API calls (curl, session cookie, model=gpt-oss-120b via BytePlus — Ollama local not running).
- Root-caused: gpt-oss-120b (BytePlus) sometimes returns `tool_calls[].function.name` contaminated with its own harmony-format tokens (e.g. `kg_query_datasource_status<|channel|>commentary`, `kg_list_projects[]`). The contaminated name doesn't match `readAllow` (computed from clean MCP tool names) → `resolveKind` fail-closed treats a READ-ONLY tool as WRITE → spurious `pending_write` suspend, turn dies with no confirmer. Same contamination also leaked into the assistant's visible final text.
- Fix: `src/lib/agent/orchestrator.ts` — `sanitizeToolCallName()` strips trailing junk from `tc.function.name`, checked against the valid tool-name set built from the `tools` param passed into `runToolRounds` (same function backs both Ollama and BytePlus transports — confirmed BytePlus goes through `runToolRounds` too, not a separate loop). Sanitized name is stored back into `convo` so the model doesn't see its own corrupted name echoed in history. 3 new tests in `orchestrator.test.ts` (clean via `<|channel|>` suffix, clean via `[]` suffix, unknown name stays untouched — gate still fail-closed correctly for genuinely unrecognized tools).
- Also tightened `src/lib/agent/tools/laam/query-audit.ts` description to explicitly scope `laam_query_audit` to LAAM's OWN audit log (not any connected data source) — partial mitigation only, model still mis-picked it for a pharmacy business question in retest (see below).
- `npx tsc --noEmit` clean, `npx vitest run src/lib/agent src/app/api/chat` → 280 passed.

## Before/after (real API retest, same 12 questions, both modes)
Before fix: reliable ~4/12 (both modes correct or close). Blockers: Q5 (chat) and Q7 (chat) hard-stuck at spurious write-gate; Q7 also showed the leaked `<|channel|>commentary` text.
After fix: Q1, Q3, Q7, Q8 correct both modes; Q2, Q4, Q5 correct in voice (Q4 count of 9 duplicate-transaction groups verified exact match vs DB); Q6 verified end-to-end via the user's requested 2-step flow (ask list-5-transactions → use returned `TXN-0004917` → ask full receipt) — voice mode reconstructed the exact 6 line items, matching DB (`transaction_items` join `products`) exactly, incl. tax/discount breakdown not even in my ground-truth query.

## Still not clean (post-fix)
- Q9 (cash-drawer shortages), Q10-voice, Q11 (multi-metric compare), Q12 (after-hours/sensitive — still queries `laam_query_audit` instead of DAAB's `audit_events` despite tightened description) are inconsistent across runs — this is model-level SQL/tool-selection nondeterminism on gpt-oss-120b, not a single deterministic bug. Matches the team's own prior finding in `mem:checkpoint/voice-tool-grounding-2026-08-03` ("Chống nhiễm history: replay kèm tool-trace ngắn cho mỗi assistant message" listed as an open next-step, not done yet).
- Q4/Q5/Q6 chat-mode (non-voice) sometimes underperform voice-mode on the SAME question in this test run — worth another controlled A/B if the team wants to chase further (`voice-tool-grounding` checkpoint already tracks a similar asymmetry).

## Files changed
- `src/lib/agent/orchestrator.ts`, `src/lib/agent/orchestrator.test.ts`
- `src/lib/agent/tools/laam/query-audit.ts`

## Next steps (not done this session — scope/effort tradeoff, flagged to user)
- Q12 tool-selection: description tightening alone insufficient; likely needs the same class of fix as G1/G4 (a structural nudge in `orchestrator.ts`/`context.ts`), which the team's own convention requires eval-backed before landing (see context.ts comments on QW-1/QW-5 evals). Did not freelance this without a baseline eval run.
- Tool-trace-in-history-replay gap already tracked in `mem:checkpoint/voice-tool-grounding-2026-08-03` — still open, would likely reduce Q9-Q11 nondeterminism.
- Changes are uncommitted on `task/implement_docs_sync`; user has not asked for a commit yet.

## Blockers / Risks
- None blocking. Remaining Q9-Q12 flakiness is inherent model behavior, not a regression from this session's changes (verified via passing tests + tsc clean + real before/after API comparison).
