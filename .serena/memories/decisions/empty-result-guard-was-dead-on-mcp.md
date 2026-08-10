# The empty-result guard never fired on an MCP result — 2026-08-07

## What was wrong

`LAAM/src/lib/agent/empty-result.ts` exists to stop a 0-row query being answered as "there are
no duplicate refunds". It inspects the result's SHAPE (`row_count`, `rows`, …).

An MCP tool result reaches the orchestrator as `{ text: "<stringified json>" }` —
`src/lib/connectors/mcp/client.ts` flattens text blocks into one string first. `foundNothing`
read `text` as a plain string, matched nothing, returned false. **The module had never once
annotated a DAAB result**, from the day it was written.

Its full test suite was green the whole time: every test built the payload by hand, in a shape
production never sends. `unwrapToolResult` (`src/lib/agent/drilldown.ts`) already existed for
exactly this wrapper and `view.ts` already used it — this module simply never did.

## How it was found

Not by tests. By measuring end to end and reading what the connector actually got: five fresh
runs of "Show duplicate refunds across stores", three of which answered "there are no duplicate
refunds" while DAAB's `ai_queries` showed `row_count = 0` at 09:31:31 / 09:31:42 / 09:31:53 —
and nothing in the conversation to stop them. Extends
`mem:mcp-direct-tests-not-representative`.

## Measured effect of the fix (`ce8b51f`), Q4 × 5 fresh conversations

| | before | after |
|---|---|---|
| false all-clear ("there are no duplicate refunds") | **3/5** | **0/5** |
| exactly right (9 groups / 18 records) | 0 | 1 |
| right entity, over-inclusive | 1 (8 rows, all one store) | 1 (12 groups — 3 of them same-store, labelled cross-store) |
| asked the user to choose a reading | 1 | 3 |

The three clarification runs all offered `original_transaction_id` as an option, which is the
correct reading.

**Do not read "0/5 silent" as Q4 being closed.** Run 4 listed 12 duplicate groups under prose
asserting all 12 span ≥2 stores; TXN-0004875 / TXN-0002019 / TXN-0002379 are same-store pairs.
Nothing on the page contradicts the claim — catching it took the SQL above. That is the SAME
class this session set out to kill, just smaller: a confident statement the reader cannot
check. Count it as a silent error, not a visible one. What changed is the magnitude — a wrong
qualifier on 3 of 12 real rows instead of a blanket "there are none".

## Rule this leaves behind

Anything in LAAM that reads a tool result must `unwrapToolResult` first, and must have at least
one test whose input is the `{ text: "<json>" }` wrapper rather than a hand-built object.
A guard that no-ops is indistinguishable from a guard that passed.
