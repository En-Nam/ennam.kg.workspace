# Card #5 follow-up — columnar tool results become chat tables (BUG-02 on landed data)

Builds on `2026-11-19-chat-clickable-records-design.md`. Repo LAAM, same branch, no deploy.

## Why
E2E on the landed T-log org: a natural question ("Cho tôi xem các lần hoàn tiền từ 10/11 đến 18/11/2026") made the
model fetch the refunds with `kg_get_evidence`, whose result is `{columns:[...], rows:[[...],...], id_labels:{...}}`.
`view.ts` only recognises arrays of objects, so the result never became a code-built table; the model retyped it as
markdown and no id was clickable. The ids in that result are exactly what the record route needs (verified: the
namespaced refund id returns 200 with the full receipt).

## Goal
A columnar result (`columns: string[]` + `rows: unknown[][]`, each row the same length as `columns`) is a table like any
array-of-objects result: shown under the answer, ids clickable (existing BUG-02 rules), landed composite ids DISPLAYED by
their short label from the result's own `id_labels` map but SENT to the record route unchanged.

## Non-goals
Making the model's markdown tables clickable; any DAAB change; short-id lookup.

## Design
- `view.ts`: `asRows` (or `findRowsIn`) also accepts a container whose `columns` is a string array and `rows` an array of
  arrays of that length, converting each row to an object keyed by column. Declared column order is kept (already the
  rule in `orderedKeys`). Columns whose name starts with `_` (e.g. `_source_ref`, an internal reference) are not shown.
- `ViewDescriptor` gains optional `idLabels?: Record<string, string>`, read from the container's `id_labels` (string →
  string entries only). `ResultTables` renders `idLabels[value] ?? value` as the cell text; the button's record id stays
  the raw value. `viewKey` is unchanged in meaning.
- Consequence (intended, same rule as today): `digest.ts` shares `findRowsIn`, so a big columnar result (≥6000 chars,
  ≥10 rows) now reaches the MODEL as a digest (counts, totals, 5 sample rows) instead of every row — the same treatment
  array-of-objects results already get. Faster answers; the model points to the table instead of retyping it.
- Connector-agnostic: generic shape + generic `id_labels` key; no tool-name checks.

## Tests
`view.test.ts`: columnar → table (order kept, `_` columns hidden, idLabels carried, truncation/count siblings still
work, mismatched row length → not a table). `digest.test.ts`: a big columnar result is digested. `ResultTables.test.tsx`:
label shown, raw id fetched on click. E2E: the natural VI question shows a refund table; clicking `RTX-…` opens the drawer.
