# Checkpoint: DAAB ranking fix + LAAM panel gate — 2026-08-07

Continues `mem:checkpoint/perf-latency-2026-08-07`. That phase was about SPEED; this one turned
out to be about CORRECTNESS.

## What was done

**DAAB (`ennam.kg.go`, branch `task/implement_docs_sync`, 4 commits)**
- `internal/service/rank_direction.go` (new): a "top N" over an all-negative measure comes back
  inverted (loss columns are negative, so `ORDER BY SUM(...) DESC` leads with the SMALLEST loss).
  Detected after execution, re-run with the direction corrected — no second LLM call. Gated on
  intent read from the question, and never silent: `QueryResult.ranking_note` says how it ranked.
- `feat(bridge)`: row-cap advice configurable per connection (`X-KG-Row-Cap` / `row_cap`).
- `fix(test)`: `query_intent_test.go` was committed with missing braces — the whole
  `internal/service` package had not compiled since 2026-08-06.
- `fix(docker)`: removed `2>/dev/null` from the dev-image CMD.

**LAAM (branch `task/improve-mcp-tool-call-voice`, 5 commits)**
- Tables now ride on the Turn (Larvis erased the previous answer's table on the next question);
  view frames accumulate by `viewKey` (splitFrames re-parses the whole buffer, so a mid-stream
  frame was appended once per chunk); `laam-scroll` on the table.
- BytePlus: one retry on 429/503/529, only before the body is read.
- Dropped `row-limit.ts` (connector owns its cap now).
- Panel gate: was `>=6000 chars AND >=10 rows`; now `>=3 rows AND >=2 columns`.
- `ViewDescriptor.note` carries a tool's interpretation note, rendered under the table.

## Current state

- Both repos green apart from pre-existing failures: LAAM 7 (WebGL/jsdom + `search.test.ts`),
  DAAB `TestGenerate_WithHaving` (expects LIMIT 1000, generator emits 100 — needs a decision).
- Nothing pushed. No PRs.
- Verified live: Larvis Q3 now renders a code-built table (10x4, matches ground truth); the
  ranking flip works in BOTH directions when called through MCP directly.

## The important finding (Q8 still wrong)

The DAAB guard reads ranking intent from the question TEXT. LAAM's model rewrites the user's
question into schema-speak before calling the tool — "losing us the **most** money" became
"Compute total shrinkage loss per product: sum adjustment_value where…", dropping the
superlative. `rankIntent` then returns unconfident and correctly declines to flip.

**Methodological lesson: testing through the MCP tool directly is NOT representative.** Phrasing
it myself kept the superlative and made the fix look complete; through LAAM it does not fire.

Likely fix: stop LAAM's model pre-translating — `natural_language_query` is meant to carry the
user's question, and DAAB (which has the schema) plans better from the original.

## Next steps

1. LAAM prompt: pass the user's question through verbatim instead of rewriting it.
2. Re-run the 12-question set in one thread — no clean full measurement exists after these changes.
3. Diagnose Q9 (misses the employee with 9 shortages) and Q11 (comparison never built; two
   "last month" queries fail) — both DAAB SQL generation.
4. Small: `sanitizeToolCallName` misses leading junk (`mkg_…`); 429 `ServerOverloaded` is
   mislabelled `rate_limit`.

## Blockers / Risks

- Same question, two runs, two different DAAB plans (adjustments+filter vs snapshots+no filter)
  → opposite answers. Non-determinism is a bigger demo risk than any single bug.
- `product_name` is NOT unique (two products named "Cereal50 Count") — ranking by name merges them.
- Air can rebuild, fail to start, and leave the container "Up" with nothing listening. Fixed in
  the Dockerfile but only after an image rebuild.
