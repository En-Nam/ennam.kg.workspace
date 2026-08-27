# Checkpoint: claude (DAAB / ennam.kg.go sub-repo) — 2026-08-25

**Tooling note:** `activate_project` was not exposed in this session (same gap as
`mem:checkpoint/claude-laam-workflow-plan-content-fix-2026-08-25`) — ennam.kg.go's own
`.serena/memories/` store could not be reached, so this checkpoint is filed at the
workspace root instead. A future session with `activate_project` available should mirror
it into ennam.kg.go's own `checkpoint/` store.

## What was done

Fixed the `clarification_needed`-non-determinism gap this checkpoint continues from
`mem:checkpoint/claude-laam-workflow-plan-content-fix-2026-08-25` ("Next steps" item 2):
`ParseWithTier` (`internal/service/query_intent.go`) previously retried the AI call once
when its JSON was malformed (`sendAndParseWithRetry`), but had NO retry when the JSON
parsed fine and the resulting `QueryPlan` then failed `hardenPlan` (e.g. a hallucinated
column name) — same root cause (AI sampling variance), only one branch had the mitigation.

**Full TDD cycle followed** (superpowers:test-driven-development skill):
1. Read `mem:checkpoint/claude-laam-workflow-plan-content-fix-2026-08-25` in full, then
   `query_intent.go` + `plan_harden.go` to confirm the exact gap before writing anything.
2. Wrote 2 RED tests first in a new file
   `internal/service/query_intent_harden_retry_test.go` (DB-gated via
   `KG_TEST_DATABASE_URL`, same convention as `query_intent_cache_integration_test.go`):
   confirmed both failed for the expected reason (no retry happened) before touching
   production code.
3. Minimal fix in `ParseWithTier` (`internal/service/query_intent.go`, ~25 lines): when
   `hardenPlan` fails, call `p.sendAndParse(ctx, req)` ONE more time (same request, fresh
   AI sample) and `hardenPlan` the result; only on a SECOND failure does it fall through to
   `planValidationClarification` (unchanged clarification_needed shape/behavior). Same
   "max 1 retry, not infinite loop" idiom as `sendAndParseWithRetry`'s malformed-JSON
   retry — deliberately did NOT touch `sendAndParseWithRetry` itself (it has no access to
   `tree`/`hardenPlan`; folding this in there would have required threading a `validate`
   callback through a function with 4 existing tests asserting its exact 2-arg signature —
   more invasive than adding the retry at the one call site that already has `tree` in
   scope). Also handles two edge cases explicitly: retry's AI request itself erroring (falls
   back to the ORIGINAL harden clarification, not a hard error) and retry coming back
   `ambiguous` instead of a plan (trusts that clarification directly).
4. Verified GREEN: both new tests pass. Then ran the ENTIRE repo test suite (not just the
   touched package) — `go test ./... -race -count=1` with both `KG_TEST_DATABASE_URL` and
   `KG_TEST_DSN` set (so DB-gated integration tests actually ran, not silently skipped) —
   all 21 packages `ok`, no regressions.
5. `go vet ./...` clean. `gofmt -l` flagged ONE pre-existing misalignment in
   `query_intent.go` (line ~710, unrelated to this diff, confirmed via `git diff` showing
   it untouched) — left alone per Rule 3 (surgical changes, don't fix adjacent unrelated
   formatting). `golangci-lint` not installed locally — not run.

## Files changed (NOT committed — user said not to unless explicitly asked)

- `internal/service/query_intent.go` — the fix, ~25 lines added inside `ParseWithTier`'s
  existing `if plan != nil { ... hardenPlan ... }` block (see diff in this session's
  transcript for exact text; small enough to re-read directly rather than duplicate here).
- `internal/service/query_intent_harden_retry_test.go` — NEW file, 2 tests:
  - `TestParseWithTier_HardenPlanFailsThenRetrySucceeds_Recovers` — first AI response
    references a hallucinated column (`total_price`, not on the fixture's columnless
    `refunds` table), second (retry) response is a clean plan; asserts the clean plan wins
    and exactly 2 AI calls happened.
  - `TestParseWithTier_HardenPlanFailsTwice_StillClarificationNeeded` — both responses bad;
    asserts still `clarification_needed`, exactly 2 AI calls (not more — the "not infinite"
    guard).
  - Added `sequencedAIProvider` (multi-response fake, unlike the existing single-response
    `fakeAIProvider`) + `newSequencedAISelector` (same `*ai.Selector`-wrapping pattern as
    the existing `newFakeAISelector`, but taking the `ai.Provider` interface so it accepts
    either fake).

## Current state

- Local dev DB confirmed reachable this session at `localhost:5432` (NOT 5433 — that was
  the port in an older test-file comment; `docker compose ps` in ennam.kg.go showed
  `0.0.0.0:5432->5432` for `ennam-kg-postgres` this session, and
  `KG_TEST_DATABASE_URL=postgres://ennam_kg:ennam_kg_dev@localhost:5432/ennam_kg?sslmode=disable`
  worked directly). `mem:daab-dev-db-port-5433-trap` may need a note that the port can
  vary by machine/compose-file state — worth double-checking with `docker compose ps`
  each session rather than trusting either port number blindly.
- Working tree has these 2 files modified/added, UNCOMMITTED — user's explicit instruction
  this session was not to commit/deploy without being asked. `git status`/`git diff` will
  show them next session.
- The LAAM-side alternative (retry submit+poll at the graph-execution layer) was
  explicitly NOT chosen — user confirmed the DAAB-side fix was fine to pursue, just to be
  careful, and the DAAB-side fix benefits every DAAB consumer, not just LAAM.

## Next steps

- If the user wants this committed/pushed, do that in a fresh explicit request (not
  assumed).
- Consider whether `sendAndParseWithRetry`'s docstring (still says "retrying send() ONCE
  if parsing fails" only) should get a one-line pointer to this NEW, separate retry in
  `ParseWithTier` so a future reader does not think the malformed-JSON retry is the only
  retry layer in this file — not done this session (kept the diff minimal per Rule 3), but
  a good small follow-up if this file gets touched again.
- Mirror this checkpoint into ennam.kg.go's own `.serena/memories/checkpoint/` once
  `activate_project` is available in a session (same follow-up noted in the LAAM checkpoint
  this continues from).

## Blockers / Risks

- None new. The fix is small, tested (RED then GREEN), full-suite-verified, and does not
  change behavior for the already-covered malformed-JSON-retry or cache-hit/miss paths
  (their existing tests in `query_intent_test.go` / `query_intent_cache_integration_test.go`
  / `query_intent_cache_test.go` all still pass unmodified).
