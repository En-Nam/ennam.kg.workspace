# QA — fresh (unrehearsed) questions vs LAAM+DAAB, 2026-08-05

Questions LAAM had never seen, run after `499146a` + `16e861c`, text mode. Expected answers
computed from `pharmacy_demo` FIRST. Purpose: test generalisation beyond the rehearsed 12, and
re-attempt the row-fabrication bug on other many-row questions.
See `mem:backlog/daab-q8-column-semantics-and-row-fabrication`.

| # | Question | Verdict |
|---|---|---|
| N1 | Which store has the most employees? | PASS — PH-005, 22 |
| N2 | Which is our busiest store? | FAILED then FIXED (see P2) |
| N3 | Did any employee refund at a store they don't work at? | transient BytePlus API error |
| N4 | Which prescription drug is rejected by insurance most often? | PASS |
| N5 | List every void transaction with employee and reason | PASS — key result |

## N2 — the one real defect, now fixed (commit `396e19f`)
1 of 2 runs answered with **0 tool calls**, claiming no revenue/traffic data existed. Mechanism:
the P1 rule ("don't pick a column when several are plausible") was over-generalised by the model
into "can't commit to a metric ⇒ can't query ⇒ refuse". P2 states the intended path explicitly
(send the question down; the lower layer asks) and forbids claiming "no data" before calling any
tool. **Re-verified with 4 fresh threads: 0/4 refused**, all queried, all converged on PH-002
(1,062 transactions all-time / 209,047.13 revenue — both match the DB); one of the four asked
the user to choose the metric, which is also correct.

## Row fabrication — TWO attempts, NOT reproduced
- N5, 120 rows: 50 distinct rows, no repeats, three sampled rows matched the DB exactly, and it
  disclosed the cut honestly ("chỉ hiển thị 50 bản ghi đầu trong tổng 120").
- `discount_overrides`, 311 rows: it asked which amount column was meant
  (`discount_amount` / `adjusted_amount` / `original_amount`) — correct, but produced no big table.
Conclusion: likely a one-off degeneration on Q8, plausibly aggravated by a wrong-column result
full of near-identical rows. Do not chase further without a fresh reproduction.

## Minor, observed once each — NOT acted on
- One answer labelled a USD figure as "đồng" (VND). 1 of 4 runs.
- One of six sampled DAAB clarifying questions just echoed the user's question back as the stem.

## THREE GRADING ERRORS I MADE — the real lesson of this session
Every one was my verification being wrong, not the product:
1. **N4 "wrong answer"** — I graded with `GROUP BY product_name`, but **6 distinct product_ids
   share the name "Mock Rx Product DTravel"**, so my ground truth merged six drugs into a bogus
   13. The AI grouped by `product_id` and correctly returned PRD-00316, 6. **AI was right.**
2. **"DAAB returns an empty clarification question"** — my probe read `clarification.question`;
   the field is `clarifying_question`. No defect existed.
3. **"DAAB picks the wrong column for Q8"** — DAAB asks correctly 4/4 when given the user's
   actual words; LAAM was rewriting the question first.

Pattern: an apparent product bug was an artifact of my own tooling or ground-truth query three
times. Before reporting a defect, re-derive the expected value a second, independent way —
especially when the system's answer is internally consistent (correct SQL, figures taken
straight from `ai_queries.results`).
