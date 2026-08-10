# Polling an async tool in code — TRIED AND REJECTED (2026-08-07)

Do not re-attempt without reading this. The mechanism worked perfectly and the system got
slower AND less correct.

## The idea
DAAB's query tool is async: it returns `{id, status: "pending"}` and someone must ask again.
Today the MODEL does the asking, costing a full round (~10k prompt tokens) to make a decision
that was never in doubt. Waiting is retry logic — Rule 5 puts retries in code.

## The measurement that justified building it
Traced all 79 model rounds over the 12-question set: **16 of them existed only to say "ask
about that ticket again"** — 15.2s of 147.8s, and ~190k prompt tokens per run. Unlike the
MCP-tool-cut (~10% inferred from noisy totals, p≈0.54), this was a direct sum of rounds that
would cease to exist. It looked like the one deterministic win available.

## What actually happened
Poll rounds went to **zero** — the code did exactly what it was built to do. But:

| | poll off | poll on #1 | poll on #2 |
|---|---|---|---|
| total | 147.8s | 250.7s | 199.7s |
| model rounds | 79 | 72 (predicted 63) | — |
| `kg_query_datasource` rounds | 19 | 24 | — |
| `kg_search` rounds | 0 | **6** | — |
| Q2 "show every refund" | correct | refused | "cannot determine who Sarah Miller is" |
| Q8 negative inventory | correct | **"471 products"** (a wrong answer already documented in context.ts P1 from 2026-08-05) | correct |
| Q5 most-refunded products | correct | correct | asks for clarification |

Q2 — the question this whole session was spent fixing — broke in BOTH runs. Neither run beat
the baseline on time.

## Why (the part worth remembering)
**A poll round was an accidental brake.** Each query used to cost 2 rounds (submit + poll), so
within the 25-round budget the model had to be economical. Halving the price of a query did not
buy speed; the model spent the savings on MORE queries — 19 → 24 — and wandered into
`kg_search`, a document-search tool that has no business answering a database question (the
exact mis-pick that rule R1 in `context.ts` exists to prevent).

Generalisation: **making a model action cheaper is not automatically good.** The round budget
and the loop's guards were tuned against the old prices. Change a price and you are changing
the shape of the search the model runs, not just its cost.

If this is revisited, the lever is probably not "make polling cheaper" but "cap how many
queries one question may run" — a different design.

## Also settled by this
Whether the env-configured pair (`TOOL_POLL_PAIRS`, naming DAAB's tools) should have been
auto-detected instead — generic detection via the `*_status` naming convention plus the tool's
own inputSchema — became moot. Worth noting the objection was right in principle: config that
names one connector's tools means the feature only exists for connectors someone hand-wired.

Code removed rather than left behind an unset flag (Rule 2/3 — no dead code).

Related: `mem:decisions/nl-query-pinning-rejected`,
`mem:decisions/tool-result-digest-blocked-on-view-frames`,
`mem:decisions/laam-latency-what-worked-and-what-didnt`.
