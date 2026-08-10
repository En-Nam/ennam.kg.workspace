# LAAM chat latency — the whole 2026-08-06 investigation, and the one thing to do next

## The finding that reframes everything: this pipeline is too noisy to A/B at n=1
Three runs of the SAME 12-question set on the SAME config: **127.5s, 239.7s, 297.6s**. A 2.3x
spread. Individual questions swing further (Q12 measured 13.5s and 80.9s; Q4 measured 15s and
65s). Every single-run comparison made earlier in the session — including figures that reached
code comments — is a draw from that distribution, not a measurement.

**Before optimising anything else, build a repeatable benchmark** (n>=3, report mean AND range,
score answers against DAAB ground truth, and normalise U+2011 hyphens before grading). Without
it, every future change is a coin flip — which is exactly how two plausible ideas below got as
far as being implemented before the numbers killed them.

## Where the time actually goes (traced per round, this part is solid)
DAAB answers in ~2.3s regardless of question. A 103s turn = ~3s cheap tool rounds + one 22s
round (out=3,702 tokens) + a 76s final round of which **41s elapsed before the first content
token**, streaming `reasoning_content`. Prefill is not the cost; **reasoning-token decode is**.
Bigger tool result in → longer thinking AND longer answer.

## Shipped
- `CHAT_REASONING_EFFORT_FINAL=low` (622287d). Mechanism measured directly on the API: 992 vs
  9,434 reasoning chars, 7.0s vs 32.9s. Never set the phase-less `CHAT_REASONING_EFFORT` — low
  on the TOOL rounds made the model pick the wrong column and answer "no duplicate refunds"
  on a fraud question (3 of 4 runs).
- Empty-result note (e1ef92b). An empty tool result can no longer read as absence; the answer
  now names the definition it tested. Partial: it did not reduce how often the answer still
  generalises to "there are none".
- `MCP_TOOL_ALLOWLIST` (5ef41b6). 55 tools / 45,678 chars of schema per round, four ever used.
  Set it for TOKEN COST (~10.3k tokens/round saved, certain), not speed: 265.6s vs 221.6s at
  n=3 each is t=0.67, p~0.54. No UI built — evidence does not justify it.

## Tried, measured, rejected (do not re-derive)
- `mem:decisions/nl-query-pinning-rejected` — sending the user's verbatim question instead of
  the model's rewrite. Faster, worse on every discriminating question.
- `mem:decisions/tool-result-digest-blocked-on-view-frames` — digesting large tool results.
  Blocked: `onView` is never passed from the chat route, so `deriveFromToolResult` never runs
  and no display surface carries the rows. Digesting = data loss; Q2 became a refusal.

## Still open, roughly by expected value
1. **Poll in code, not via the model.** DAAB is async (submit → `_status`); each poll costs a
   full model round (11-13k prompt tokens + decode). This is retry logic — Rule 5 says code
   owns it. Removes 1-2 rounds per query, more on multi-query questions.
2. **Prompt caching.** BytePlus returns `prompt_tokens_details.cached_tokens`, so the platform
   has the feature, but it reads 0 even on an identical repeated 3,679-token prefix — not
   enabled. The fixed prefix (system prompt + tool schemas) repeats on every round of every
   turn. Needs the Ark context-caching docs; unverified.
3. **Parallel tool calls.** `runToolRounds` dispatches sequentially (`for … await`). Count how
   often a round actually contains >1 call before building it — the traces suggest mostly one,
   in which case this wins nothing. Writes must stay sequential (`PendingWriteSignal`).

## Correctness debt that outranks all of the above for the demo
Q4 (duplicate refunds) is wrong ~25% of the time at BASELINE; Q11 rarely returns a complete
table; Q8 is right standalone but wrong inside the 12-question thread. See
`mem:checkpoint/perf-latency-2026-08-06`.
