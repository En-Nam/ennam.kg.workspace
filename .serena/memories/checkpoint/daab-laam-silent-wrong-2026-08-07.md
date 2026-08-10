# Checkpoint: silent-wrong-answer pass + clean 3× sweep — 2026-08-07 (second session of the day)

Continues `mem:checkpoint/daab-ranking-and-panel-gate-2026-08-07`.

## What was done

**Refused the handoff's task 1.** It asked to make LAAM pass the user's question verbatim to
the connector. `mem:decisions/nl-query-pinning-rejected` had already measured both variants
(append: no effect; replace-first-call: faster and worse on Q4/Q8/Q11). Surfaced instead of
re-running it (Rule 7).

**DAAB `910eea7` — `rankingAdvisoryNote`.** The fragile part of yesterday's ranking flip was
`rankIntent(question)`: it recovers intent from text that has already passed through a lossy
rewriter. Split the two halves by what they need to know — flipping needs INTENT (may be
missing) and changes the answer; the note needs only the SIGN of the returned values (always
present) and changes nothing, it only states which end leads. Now emitted on every
non-flipped ranking over a negative measure. Fired for real during the sweep (run B Q9).

**LAAM `7d89e45` — P3 comparatives.** P3's preserved-wording list was all nouns, so dropping
"most" read as compliant. Added comparatives/superlatives explicitly. Second line of defence
only; prompt compliance is probabilistic.

**Clean 3× 12-question sweep**, graded against direct SQL — see `mem:qa/latest-results`.

## Files changed

- `ennam.kg.go/internal/service/rank_direction.go`, `rank_direction_test.go`, `nl_query.go`
- `LAAM/src/lib/agent/context.ts`

## Current state

- DAAB `task/implement_docs_sync`, 5 commits. LAAM `task/improve-mcp-tool-call-voice`,
  6 commits. **Neither pushed, no PRs** — still the open decision.
- Tests green apart from the known pre-existing ones (DAAB `TestGenerate_WithHaving`;
  LAAM 7 WebGL/jsdom + `search.test.ts`).
- **2 silent wrong answers in 36**, both Q4. Q8 fixed (0/3 → 3/3), Q9 2/3, Q3/Q10 3/3.

## Q4 follow-up, same session — root cause found and fixed

Two more LAAM commits after the sweep:

- `0e0d182` — the empty-result note now names the sentence shape that got past it (disclose the
  reading, then append "Vì vậy không có … trong hệ thống") and, when the text that came back
  empty is NOT the user's, requires re-asking once in the user's words. Terminates: not
  requested again once the user's own words are what came back empty.
- `ce8b51f` — **the real bug.** MCP results arrive as `{ text: "<json>" }`, so `foundNothing`
  read `text` as a string and the guard had NEVER fired on a DAAB result, with a fully green
  test suite. See `mem:decisions/empty-result-guard-was-dead-on-mcp`.

Q4 × 5 fresh conversations, before → after: **false all-clear 3/5 → 0/5**; one run exactly
right (9 groups / 18 records); one right-entity but over-inclusive (12 groups, 3 of them
same-store, described as cross-store); three asked the user, all offering
`original_transaction_id` as an option.

## Next steps

1. **Q4's remaining defect is over-claiming, not an all-clear** — run 4 labelled 3 same-store
   pairs as cross-store. Visible to a reader; much less dangerous than what it replaced. Its verbatim path already returns
   `clarification_needed` correctly; the model's self-authored definition of "duplicate" is
   what produces the false all-clear. Fixing it by pinning the text is closed off — look at
   DAAB planning `original_transaction_id` grouping, or at why the rewrite survives P3.
2. Q7 and Q12 never answer (3/3 clarification). Visible, so not urgent, but two of twelve
   demo questions produce no data.
3. Still open from the previous checkpoint: `sanitizeToolCallName` misses leading junk
   (`mkg_…`); BytePlus 429 + `ServerOverloaded` mislabelled `rate_limit`;
   `TestGenerate_WithHaving` LIMIT 1000 vs 100.

## Blockers / Risks

- Non-determinism unchanged and still the biggest demo risk: same question, same build,
  three runs, three different Q4 answers and three different Q11 answers.
- Agent logged into LAAM with the user's own credentials this session (user authorised it
  explicitly after Playwright's extension bridge was unavailable); the session cookie was
  minted through `/api/auth/callback/credentials` with curl.
