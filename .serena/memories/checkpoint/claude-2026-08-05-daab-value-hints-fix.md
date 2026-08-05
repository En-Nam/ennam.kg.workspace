# Checkpoint: claude — 2026-08-05 (DAAB fix #8: categorical value hints — root cause of "Q10 nondeterminism")

Follow-up to `mem:checkpoint/claude-2026-08-05-daab-retry-and-joinfanout-fix`, where Q10 (insurance claim rejection rate) was written off as "genuine model nondeterminism, no code lever". User asked whether the remaining items could still be improved — investigated instead of assuming, and that conclusion was WRONG.

## Root cause (measured, not inferred)
`insurance_claims.claim_status` actually stores **'Rejected'** / **'Approved'** (capitalized). The planner had never seen a single VALUE from the source DB — `buildSchemaContext` emits table/column/type/PK/FK only — so it GUESSED the literal, often writing `claim_status = 'rejected'`. Postgres text `=` is case-sensitive → 0 matches → the query **succeeds** and reports "every store has a 0% rejection rate". Confidently wrong, not an error: the worst possible failure mode, and invisible without checking the DB.

Ground truth proving the coin-flip: with `'Rejected'` → PH-004 41/265 = 15.47%, PH-001 24/318 = 7.55%, PH-003 18/315 = 5.71%, PH-002 14/285 = 4.91%, PH-005 15/317 = 4.73%. With `'rejected'` → **all five stores 0**. Both answers had been observed across earlier runs — that WAS the "nondeterminism".

Scope is a whole class, not one question: ~30 enum-like text columns in this schema alone (refund_method, refund_reason, movement_type, event_type, adjustment_type, void_reason, payment_method, department, `status` on 6 different tables…). Any question filtering on any of them had the same silent-wrong-answer risk.

## Fix
- **New** `internal/service/value_hints.go` — `ValueHinter` samples the real distinct values of low-cardinality text columns via the existing read-only `SourceExecutor`, in ONE bounded UNION ALL query per data source, cached 10 min:
  - `LIMIT 5000` per column bounds rows SCANNED (a bare `SELECT DISTINCT col` can full-scan a customer table — unacceptable); enum-like columns repeat their full value set within the first few thousand rows.
  - fetches `maxValues+1` (26) per column so `groupValueHints` can DROP anything above 25 distinct values (identifier / free text, not a category).
  - skips PK and unique columns (always identifiers).
  - Strictly best-effort: any failure (unreachable source, non-Postgres dialect — the sampling SQL is Postgres-shaped) logs a warning and yields nil hints; the pipeline proceeds exactly as before. Failures are cached too, so a source that cannot be sampled isn't retried per query.
- `internal/service/query_intent.go` — new `ValueHintProvider` interface (accept-interfaces idiom) + `WithValueHints` functional option matching the existing `WithContextBuilder` pattern; hints appended to the schema context for BOTH the smart and legacy context paths (the guessed-literal failure is a property of the planner, not of how the schema text was assembled). Prompt also gained an explicit case-sensitivity rule: use the listed values verbatim; when a column's values are NOT listed and the spelling is uncertain, use `ILIKE` instead of `=` (ILIKE was already in the operator whitelist from fix #1).
- `cmd/kg-server/main.go` — wired on by default with a `KG_VALUE_HINTS=off` kill switch (sampling touches the customer DB, so it must be opt-out-able).
- 10 new tests in `value_hints_test.go` covering the pure logic (text-column detection, identifier quoting/escaping, query shape + both bounds present + SELECT-prefixed so `ensureReadStatement` accepts it, PK/numeric exclusion, high-cardinality drop, driver `[]byte` values, nil-degradation).
- `go build`, `gofmt -l`, `go vet ./...`, full repo `go test ./...` (21 packages) all clean.

## Live verification via LAAM
`docker restart daab-server` → log confirms "categorical value hints enabled for NL query planning".
- Q10 asked **4 times**: correct **4/4** (before: coin-flip). First run returned all five stores matching ground truth to the decimal (15.47 / 7.55 / 5.71 / 4.91 / 4.73).
- `ai_queries.generated_sql` confirms the planner now writes `claim_status = 'Rejected'` — correct capitalization, taken from the hint block.
- Regression sweep (Q1/Q3/Q4/Q5/Q8): all still correct; 9/10 datasource queries in the window completed, the 1 failure being the already-known random malformed-SQL class (the user-facing answer was still correct via the retry added in fix #5).

## Files changed
- `ennam.kg.go/internal/service/value_hints.go` (new), `value_hints_test.go` (new)
- `ennam.kg.go/internal/service/query_intent.go`
- `ennam.kg.go/cmd/kg-server/main.go`

## Lesson worth keeping
"The model is just nondeterministic" was a premature conclusion twice in this thread. Both times the actual cause was a deterministic gap in what the system TOLD the model (fix #1: no operator whitelist; fix #8: no value domain). Before writing off LLM behavior as unfixable noise, check what information the prompt is missing — and check the DB, since a *silently wrong* answer looks identical to a correct one from the outside.

## Genuinely remaining (no code lever identified)
- LAAM-side model sometimes gives up before issuing any query (Q9 did so in this last sweep, having answered correctly minutes earlier with identical inputs) — pure gpt-oss-120b reasoning variance, no DAAB query even reaches the DB.
- Occasional malformed AI JSON/SQL — already mitigated by the fix-#5 retry, not eliminated.
- Single-shot multi-metric asks (Q11/Q12) still better served by the decompose demo script.

## Blockers / Risks
- Sampling reads the customer's live source DB. Read-only (enforced by SourceExecutor), double-bounded, cached 10 min, kill-switchable. First query per data source per TTL pays the sampling cost.
- Everything across this entire thread (both repos) remains **uncommitted**.
