# Q8 "negative inventory" — RESOLVED in LAAM. No DAAB defect found.

Supersedes TWO earlier framings in this same memory, both of which the probes disproved:
1. "DAAB's planner picks the wrong column" — wrong, the fault was in LAAM.
2. "DAAB returns an empty clarification question" — wrong, that was a probe-script bug.

Decision record: `mem:decisions/laam-forward-user-question-verbatim`.

## Ground truth (`pharmacy_demo`) — the demo doc is CORRECT
```
counted_quantity                     < 0  ->   0     <- the real reading
system_quantity                      < 0  ->   0
inventory_adjustments.quantity_after < 0  ->   0
variance_quantity                    < 0  -> 666 rows / 471 products  <- what LAAM used to report
SUM(inventory_movements.quantity_change) < 0 per product -> 727       <- meaningless (deltas
                                                                         with no opening balance)
```
All three legitimate stock readings agree on **none**. Do NOT update the demo doc.

## Root cause was LAAM, and it is fixed
Measured on DAAB's `ai_queries` log, same question, two phrasings:
- verbatim `"Which products have negative inventory?"` -> `clarification_needed` **4/4**
- column-committed `"...where variance_quantity is less than 0"` -> `completed`

A LAAM prompt rule was instructing the rewrite. Fixed in commit `16e861c`; see the decision
memory. Verified end-to-end: LAAM now forwards near-verbatim, both modes relay the
clarification, and a disambiguated question yields
`SELECT COUNT(*) FROM inventory_snapshots WHERE counted_quantity < $1` -> `{"count": 0}`.
No regression: Q11 still decomposes into 4 per-metric queries (and now returns the full
4-metric table in text mode); Q6 still forwards `TXN-0003476`.

## CORRECTION — the "empty clarification question" was MY bug, not DAAB's
`scratchpad/laam_test/ask.sh` read `clarification.question`. The real JSON field is
**`clarifying_question`** (`models.QueryClarification`, `internal/models/ai_query.go:28`), so
the probe printed `None` and I reported a defect that does not exist. DAAB populates it
properly — sampled 6 recent rows from `query_clarifications`, all well-formed, e.g.
"Do you want to consider the latest inventory snapshot overall, or the latest snapshot per
store?". The probe script has been fixed. **Lesson: a null in a probe means "check the field
name" before it means "the service is broken".**

Two minor, NON-structural quality observations (not worth a change on current evidence):
- 1 of 6 sampled clarifying questions just echoed the user's question back
  ("Which products have negative inventory?") — useless as a stem but harmless.
- One sampled option bundled `counted_quantity` and `variance_quantity` into a single choice
  (readings that differ 0 vs 471). Seen once; not reproduced in later samples.

## STILL OPEN — one item, not reproducible right now
**Fabricated table rows (LAAM/model).** Q8-text once emitted
`PRD-00134 | Elastic WrapTravel (trùng)` ~20x to fill a 100-row table. Verified fabrication at
the time: PRD-00134 appears exactly ONCE with negative variance, no product repeated in the
first 100 rows. Ruled out DAAB truncation (`maxRows`=10000, plan used LIMIT 100,
`truncated`=false) and LAAM's `CLOUD_RESULT_BOUND` (120k chars, ~20k used). Larvis did NOT
fabricate on the same data. With Q8 now returning zero rows there is nothing to fabricate
from, so **a different large-result question is needed to reproduce it**. Do not guess a fix
for something that cannot currently be reproduced. `.env` already carries
`CHAT_PRESENCE_PENALTY=0.2`, documented for this repetition class.

## Probe harness (reusable)
`scratchpad/laam_test/ask.sh` — posts to `POST /api/v1/ai-queries`, polls, prints
status / SQL / clarification / rows. Needs `daab.env` holding a project API key (user-supplied
2026-08-05, scratchpad only, never committed). It bypasses LAAM entirely so the planner is the
only variable. Driving DAAB through LAAM chat instead is a NOISY oracle — LAAM's own model
varies the forwarded wording run to run — and must not be used to tune planner prompts.
