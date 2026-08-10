# Checkpoint: LAAM latency + result-table work — 2026-08-07

## What was done (9 commits on `task/improve-mcp-tool-call-voice`)
- `622287d` wire `reasoning_effort`, split tools vs final phase.
- `e1ef92b` an empty tool result must not read as absence.
- `5ef41b6` → superseded by `cf0a513`/`0bad87a`: per-tool on/off for each MCP server, with a
  modal picker showing each tool's description + a filter over name AND description.
- `64e63ff` correct an n=1 speed figure recorded in `.env.example`.
- `55c9223` **result tables built from data, not retyped by the model**.
- `0203dbc` **digest large results before they reach the model** + row-limit raise.
- `921c71e` voice contract acknowledges the code-built table.

## Measured (Q2 "show every refund processed by Sarah Miller")
49.2s → **11.6-13.7s**; prompt 19,476 → ~4,700 tokens; output 2,739 → ~230; panel shows all
62 rows; reload rebuilds it. 12-question Larvis set: 144-235s over 5 sweeps, no round-cap hits,
all ground-truth questions correct.

## Two bugs the panel exists to prevent, both observed live
The model's own markdown table printed `PH-1` for a cell whose real value is `PH-001` (an id
absent from the database), and closed "All 62 records were returned" while showing 50.

## Current state
`tsc` clean, 310 agent tests, full suite green except 7 failures that pre-date this work
(`ConstellationClient.test.tsx`, `search.test.ts` — verified against a clean worktree at HEAD).

## Next steps
1. **Show the generated SQL under the table.** DAAB returns `sql` in every result and LAAM
   already receives it (confirmed in `chat_tool_call`) — it is simply never displayed. Q4 was
   wrong all session because the planner emitted `GROUP BY refund_id HAVING COUNT(DISTINCT
   store_id) > 1` — empty by construction, and obvious in one glance if the SQL were visible.
   This is the highest-value remaining item and needs no model cooperation.
2. Render DAAB's clarification as a choice card instead of letting the model paraphrase it.
3. Poll in code, not via the model (each poll is a full model round, 11-13k prompt tokens).
4. Prompt caching: BytePlus returns `prompt_tokens_details.cached_tokens` but it reads 0 —
   the platform has the feature, it is not enabled. Unverified.

## Blockers / Risks
- **Do not tune anything here at n=1.** The same config produced 127.5s and 297.6s on
  consecutive 12-question runs. I twice drew a wrong conclusion from a single sample this
  session — once optimistic, once pessimistic. Build a repeatable benchmark before the next
  round of tuning.
- **Prompt rules do not hold here.** Five separate rules in `context.ts` (P1/P2/P3 plus two I
  added) were violated in measurement. Prefer code.
- Known gap: a follow-up "show me the full table" can still be refused, because that turn
  re-reads the digested history and sees five rows. Left deliberately unpatched — see
  `mem:decisions/laam-latency-what-worked-and-what-didnt`.
- Three of the twelve questions (Q7/Q11/Q12) return a clarification instead of an answer, and
  the clarification comes from **DAAB**, not LAAM — `inventory_snapshots.variance_quantity`
  already carries a `user_description` and its intent parser still asks. Tune DAAB, not LAAM.
