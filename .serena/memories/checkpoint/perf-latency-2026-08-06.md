# Checkpoint: LAAM latency investigation — 2026-08-06

## What was done
- Measured where LAAM chat latency actually goes (BytePlus gpt-oss-120b, DAAB pharmacy demo).
  DAAB answers in ~2.3s regardless of question; LAAM is 93-97% of every slow turn.
- Instrumented per-round timing/usage (temporary, since removed). Finding: cost is
  **reasoning-token decode, not prefill**. Q2 (103s) = 3s cheap tool rounds + 22s heavy tool
  round (out=3,702 tok) + 76s final stream, of which **41s elapses before the first content
  token** while the model streams reasoning_content. Q1 (3.7k input) finishes its final round
  in 1.9s; Q2 (19k input) takes 76s. Bigger tool result → longer reasoning AND longer answer.
- Found `reasoning_effort` was never forwarded (applyOptions passed only temperature/top_p/
  presence_penalty) → provider default, measured to behave like "high".
- A/B'd three configs over the 12 demo questions + repeated the discriminating ones.

## Files changed
- `src/lib/llm/byteplus.ts` — +18 lines: `applyReasoningEffort(body, phase)`, called from
  byteplusChat("tools") and byteplusStream("final"). No-op unless env set. Committed 622287d.
- `.env.example` — documents all three vars + why not to set the tool-round one.
- `.env` (untracked) — `CHAT_REASONING_EFFORT_FINAL=low` enabled.

## Current state
- Shipped: 12-question sweep **357.6s → 275.2s (−23%)**; 5-store comparison 57.3s → 26.7s.
- `tsc --noEmit` clean, `npx vitest run src/lib/llm` 61/61 pass. `npm run lint` is broken
  **pre-existing** (`next lint` removed in Next 16) — untouched.
- Quality at n=8/config on Q4: baseline 3 correct / 2 false-negative / 3 partial; final-low
  4 / 3 / 1 → Fisher p=1.0, indistinguishable. Low on BOTH phases is the harmful one (3 of 4
  false negatives) — tool rounds are where the DAAB column choice is made.

## Next steps
1. **Q4 "duplicate refunds across stores" is wrong ~25% of the time AT BASELINE** — says "no
   duplicates" when ground truth is 9 `original_transaction_id` at >1 store. Model re-invents
   the definition each turn (`refund_transaction_id`, or requiring `refund_datetime` equality).
   Pin the definition in prompt or a playbook. Highest priority — it is a fraud question.
2. Digest the tool result before it enters model context (split the two consumers of `result`
   at `orchestrator.ts:279`; keep raw for `deriveFromToolResult` so the display panel is
   unaffected; replace TRUNCATE_NOTE's "re-query narrower" with "already displayed").
   Also expected to fix (3).
3. Q11 (compare sales/refunds/variance/claims) never returned a complete correct table — 0/9.
4. DAAB ticket: `SELECT *` on a JOIN collapses duplicate column names (`store_id` from
   refunds vs employees) — the exact column Q4 depends on.

## Blockers / Risks
- Grading trap: answers use U+2011 non-breaking hyphens (`TXN‑0000626`). A naive `"txn-"`
  match scores correct answers as failures — this produced a wrong intermediate conclusion
  mid-session. Normalize ‐‑‒–—− before grading.
- All quality numbers are n≤8 per config. Directional only.
