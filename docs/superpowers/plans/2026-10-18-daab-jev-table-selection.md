# DAAB Jev Table Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When Jev is configured, switched on, and allowed for a project, DAAB asks Jev which tables a
question needs and sends only those to the NL→SQL planner. Otherwise nothing changes.

**Architecture:**
- A small Jev HTTP client and pure table-selection helpers live in a new Go package `internal/judge`.
- A `service.TableJudge` decides per request (mode, project opt-in, table count, selection cache),
  then prunes the schema tree on the legacy context path and logs to `ai_judge_logs`.
- The per-project opt-in lives in DAAB (`project_ai_settings`). It is flipped from DAAB web (internal
  and demo projects) and from Ennam Admin (customers, behind 2FA and audit).

**Tech Stack:**
- Go stdlib `net/http`, `database/sql`, golang-migrate (ennam.kg.go).
- Next 16 / React 19 / TanStack Query (ennam.kg.next).
- Next / drizzle / zod / vitest (ennam.kg.admin).

**Spec:** `docs/superpowers/specs/2026-10-18-daab-jev-table-selection-design.md`. Read it first; section
numbers below (§) refer to it.

## Global Constraints

- **Three nested git repos.** `ennam.kg.go`, `ennam.kg.next` and `ennam.kg.admin` each have their own
  `.git`; commit with `git -C <repo>`. The workspace root holds only docs and compose.
- **Branches:**
  - Create `feat/jev-table-selection` in `ennam.kg.go` and in `ennam.kg.next`, from their current
    `task/demo_pharmacy`.
  - In `ennam.kg.admin`, create it from `main`.
  - The workspace-root changes (compose, `.env*.example`) go on the current workspace branch.
- **Env names, defaults verbatim:**
  - `TYPESAFE_API_KEY` (empty = Jev unavailable)
  - `TYPESAFE_BASE_URL=https://api.typesafe.ai`
  - `TYPESAFE_DEFAULT_MODEL=jev-1.13.0`
  - `TYPESAFE_TIMEOUT_MS=800`
- **Setting keys and seeded defaults:**
  - `ai.judge.table_filter` = `"off"`, values `"off"|"shadow"|"on"`
  - `ai.judge.table_filter_threshold` = `0.2`, must be in (0,1)
  - `ai.judge.table_filter_max_tables` = `60`
- **Endpoint:** `POST {TYPESAFE_BASE_URL}/v1/systemone`, Bearer auth. **One attempt, no retries**
  (429/529 included), bounded by `TYPESAFE_TIMEOUT_MS`.
- **Jev runs only when all of these hold:** the key is set; the mode is not `off`; the question's
  project has `jev_allowed=true`; and 2 ≤ table count ≤ max_tables. This applies to shadow too.
- **What goes to Jev:** only the PII-masked question, table names, table descriptions (≤200 chars)
  and column **names**. Never row data, value hints, types or column descriptions.
- **Failure is never user-visible.** Any Jev failure → full schema (today's behaviour). Only `ok`
  selections are cached.
- **Never log** the API key or the raw question text (`query_hash` only).
- **Dev DB is on :5433. :5432 on this machine is `am-ai-postgres`, a DIFFERENT product. Never run
  a migration command without `KG_DB_PORT=5433`.**
  - `kg-migrate` reads `KG_DB_*` (not `DATABASE_URL`) and defaults to port 5432
    (`cmd/kg-migrate/main.go:29-34`). Always run `KG_DB_PORT=5433 make db-migrate`.
  - Integration tests: set `KG_TEST_DATABASE_URL` and `KG_TEST_DSN` to
    `postgres://ennam_kg:ennam_kg_dev@localhost:5433/ennam_kg?sslmode=disable`.
  - **A DB test that SKIPs reports PASS.** Always run with `-v` and confirm the tests ran.
- **Commit messages:** `<type>: <description>`, ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Plan decision (deviates from spec §4.8 wording):** do **not** add a judge entry to
`models.AIFunctions`. That registry is kept in step with Python tags (`tests/test_ai_request_types.py`),
and an entry would show up in the model-assignment UI and validation. Instead,
`GET /api/v1/ai-functions` gains a top-level `judge` object (Task 7).

## Review Focus

1. **Unreachable or slow TypeSafe in `on` mode** (DNS fail, TLS error, response at 801ms). The user
   still gets an answer built from the full schema, with no extra wait beyond the timeout. Test:
   Task 5 `TestTableJudge_OnTimeoutFallsBackToFullTree`.
2. **A project flipped off while a question is in flight, or a data source whose project row is
   missing** (no `project_ai_settings` row). Jev must not be called. Test: Task 5
   `TestTableJudge_ProjectNotAllowedOrMissing`.
3. **A question containing a Vietnamese phone number or email** (`0912 345 678`, `+84912345678`,
   `a.b@x.vn`). The masked text is what reaches the HTTP body. Test: Task 4 `TestMaskPII` and Task 5
   `TestTableJudge_SendsMaskedQuestion`, which asserts on the fake server's received body.
4. **Ennam Admin with DAAB down, or ops-role staff.** The card renders, the switch is disabled or
   hidden, and nothing is written. Tests: Task 10 card states and Task 9
   `setDaabJevAllowed refuses without project`.
5. **Settings set to garbage** (`ai.judge.table_filter="ON"`, threshold `1.5`, max_tables `-1`). PUT
   is rejected with 400; a bad value already in the DB is read as `off` / the default. Tests:
   Task 7 `TestValidateJudgeSetting` and Task 5 `TestTableJudge_BadStoredSettingsActAsDefaults`.

---

### Task 1: Fix the two ContextBuilder settings-key mismatches (spec §4.10)

**Files:**
- Modify: `ennam.kg.go/internal/service/context_builder.go` (`resolveDefaultTier` ~L330, `resolveTopK` ~L350, comment ~L77)
- Test: `ennam.kg.go/internal/service/context_builder_test.go`

**Interfaces:** none new.

- [ ] **Step 1: Create the branch.** `git -C ennam.kg.go switch -c feat/jev-table-selection`
- [ ] **Step 2: Write failing tests** `TestResolveDefaultTier_ReadsQueryTierKey` (store `ai.query_tier="precise"` → `QueryTierPrecise`) and `TestResolveTopK_ReadsContextTopKKey` (store `ai.context_top_k=15` → `15`). Existing tests use `&ContextBuilder{}` with a nil cache, so build `&ContextBuilder{settingsCache: NewSettingsService(fakeRepo, nil, nil)}` with a small in-file fake `SettingsRepository`.
- [ ] **Step 3: Run** `go test ./internal/service/ -run 'TestResolveDefaultTier|TestResolveTopK'`. Expected: FAIL (it returns balanced / 10).
- [ ] **Step 4: Implement:** read `ai.query_tier` and `ai.context_top_k`, and update the doc comment.
- [ ] **Step 5: Run** the same command. Expected: PASS. Then run `go test ./internal/service/`. Expected: PASS.
- [ ] **Step 6: Commit:** `fix: read the seeded ai.query_tier and ai.context_top_k keys in ContextBuilder`.

### Task 2: Migration, models and stores

**Files:**
- Create: `ennam.kg.go/db/migrations/000094_ai_judge.up.sql`, `000094_ai_judge.down.sql`
- Create: `ennam.kg.go/internal/models/ai_judge.go`
- Create: `ennam.kg.go/internal/store/project_ai_settings.go`, `ennam.kg.go/internal/store/ai_judge_log.go`
- Test: `ennam.kg.go/internal/store/project_ai_settings_test.go`, `ennam.kg.go/internal/store/ai_judge_log_test.go` (`//go:build integration`, `package store_test`, using `setupTestDB` from `favorite_test.go`)

**Interfaces — Produces:**
```go
// models
type JudgeMode string // JudgeModeOff="off", JudgeModeShadow="shadow", JudgeModeOn="on"
const (
    SettingJudgeTableFilter = "ai.judge.table_filter"
    SettingJudgeThreshold   = "ai.judge.table_filter_threshold"
    SettingJudgeMaxTables   = "ai.judge.table_filter_max_tables"
    JudgeChangedViaDAABWeb  = "daab_web"
    JudgeChangedViaAdmin    = "ennam_admin"
)
type ProjectAISettings struct {
    ProjectID       string     `json:"project_id"`
    JevAllowed      bool       `json:"jev_allowed"`
    ChangedByUserID *string    `json:"changed_by_user_id,omitempty"`
    ChangedByLabel  *string    `json:"changed_by_label"`
    ChangedVia      *string    `json:"changed_via"`
    ChangedAt       *time.Time `json:"changed_at"`
}
type AIJudgeLog struct {
    RequestType, Mode, Outcome, ErrorCode, Model, DataSourceID, QueryHash string // RequestType is always "jev_table_select" (not "table_filter": that is the smart-path LLM function)
    LatencyMs, InputTokens, TableCount, SelectedCount, SchemaCharsFull, SchemaCharsUsed int
    Scores     map[string]float64 // table -> p
    Selected   []string
    PlanTables []string // nil = unknown
}
// store
func NewProjectAISettingsStore(db *sql.DB) *ProjectAISettingsStore
func (s *ProjectAISettingsStore) Get(ctx context.Context, projectID string) (*models.ProjectAISettings, error) // no row → JevAllowed=false, other fields nil
func (s *ProjectAISettingsStore) Set(ctx context.Context, v *models.ProjectAISettings) error                  // upsert; changed_at = now()
func (s *ProjectAISettingsStore) List(ctx context.Context) ([]models.ProjectAISettings, error)
func (s *ProjectAISettingsStore) JevAllowedForDataSource(ctx context.Context, dataSourceID string) (bool, error) // joins data_sources; unknown ds → false, nil
func NewAIJudgeLogStore(db *sql.DB) *AIJudgeLogStore
func (s *AIJudgeLogStore) Insert(ctx context.Context, l *models.AIJudgeLog) error
```

- [ ] **Step 1: Write the migration.**
  - `project_ai_settings`: columns per spec §4.1. `changed_by_user_id` is nullable FK → `users(id)` ON DELETE SET NULL; `changed_via` has CHECK in (`daab_web`,`ennam_admin`).
  - `ai_judge_logs`: columns per spec §4.6, plus `latency_ms int`, `input_tokens int`, `created_at timestamptz default now()`, and an index on `created_at`. `mode` and `outcome` get CHECK constraints with the spec values. `data_source_id` is a plain uuid with **no FK**, so deleting a data source is never blocked by logs.
  - Seed the three settings with category `'ai'` using `ON CONFLICT (key) DO NOTHING`.
  - The down migration drops both tables and deletes the three keys.
- [ ] **Step 2: Write failing integration tests:**
  - `TestProjectAISettings_GetMissingIsNotAllowed`
  - `TestProjectAISettings_SetThenGetRoundTrip` (label, via, changed_at set)
  - `TestProjectAISettings_JevAllowedForDataSource` (allowed project's data source → true; other project's → false; unknown id → false, nil)
  - `TestAIJudgeLog_InsertWithNilPlanTables` (row exists, `plan_tables` IS NULL)
- [ ] **Step 3: Migrate and run.** Run `KG_DB_PORT=5433 make db-migrate`, then `KG_TEST_DATABASE_URL=<:5433 DSN> go test -tags=integration -v ./internal/store/ -run 'ProjectAISettings|AIJudgeLog'`. Expected: FAIL (types undefined).
- [ ] **Step 4: Implement models and stores.** Scores, Selected and PlanTables are stored as jsonb; nil PlanTables is written as SQL NULL.
- [ ] **Step 5: Run the tests with `-v`.** Expected: PASS, with no SKIP lines. Prove the down migration works with `KG_DB_PORT=5433 make db-migrate-down` then `KG_DB_PORT=5433 make db-migrate`. **Check `KG_DB_PORT=5433` is set before pressing enter.**
- [ ] **Step 6: Commit:** `feat: project_ai_settings and ai_judge_logs tables for the Jev judge`.

### Task 3: Jev HTTP client (`internal/judge`)

**Files:**
- Create: `ennam.kg.go/internal/judge/client.go`
- Test: `ennam.kg.go/internal/judge/client_test.go` (httptest server)

**Interfaces — Produces:**
```go
type Config struct { APIKey, BaseURL, Model string; Timeout time.Duration }
func ConfigFromEnv(getenv func(string) string) Config // defaults: https://api.typesafe.ai, jev-1.13.0, 800ms; bad TYPESAFE_TIMEOUT_MS → 800ms
func NewClient(cfg Config, hc *http.Client) *Client  // nil when cfg.APIKey == "" (after TrimSpace)
func (c *Client) Model() string
type NoulCriteria struct { True string `json:"true"`; False string `json:"false"` }
type NoulQuestion struct { Instructions any `json:"instructions"`; Criteria *NoulCriteria `json:"criteria,omitempty"` } // marshals with "type":"noul"
type Result struct { Model string; InputTokens int; Noul map[string]float64; Latency time.Duration }
type ErrorKind string // "timeout" | "http" | "transport" | "bad_response"
type Error struct { Kind ErrorKind; Status int; Msg string } // implements error; Msg never contains the key
func (c *Client) Noul(ctx context.Context, state any, qs map[string]NoulQuestion) (Result, error)
```

- [ ] **Step 1: Write failing tests:**
  - `TestNewClient_NilWithoutKey`
  - `TestConfigFromEnv_Defaults`
  - `TestNoul_SendsBearerModelStateQuestions`: the server asserts the path `/v1/systemone`, the header `Authorization: Bearer k`, `"model":"jev-1.13.0"`, and `questions.t0.type=="noul"`; it replies `{"model":"jev-1.13.0","answers":{"t0":{"type":"noul","noul":0.9}},"usage":{"input_tokens":12,"output_tokens":3}}`. The result has `Noul["t0"]==0.9` and `InputTokens==12`.
  - `TestNoul_429DoesNotRetry`: the server counts hits and returns 429. The test expects exactly 1 hit, `Kind=="http"` and `Status==429`.
  - `TestNoul_TimeoutKind`: the server sleeps 50ms with Timeout 10ms. Expect `Kind=="timeout"`.
  - `TestNoul_BadShape`: `{"answers":{"t0":{"type":"choice"}}}`. Expect `Kind=="bad_response"`.
  - `TestError_DoesNotLeakKey`: the 401 body echoes the key. The error string must not contain it.
- [ ] **Step 2: Run** `go test ./internal/judge/`. Expected: FAIL.
- [ ] **Step 3: Implement.** One request built with `http.NewRequestWithContext` under `context.WithTimeout(cfg.Timeout)`. Read the error body capped at 2 KiB and scrub the key from it. Latency is measured client-side.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: minimal TypeSafe Jev client (one attempt, typed errors)`.

### Task 4: Pure table-selection helpers (`internal/judge`)

**Files:**
- Create: `ennam.kg.go/internal/judge/tables.go`
- Test: `ennam.kg.go/internal/judge/tables_test.go`

**Interfaces — Produces:**
```go
type TableCard struct { Name, Description string; Columns []string } // Name = "schema.table"
type FK struct { From, To string }                                   // qualified table names
const TableQuestionText = "Is `table` needed to answer `state.question` with SQL — as a source of rows, a filter, or a join between other needed tables?"
func TableQuestions(cards []TableCard) map[string]NoulQuestion // keys "t0".."tN" in card order; criteria true/false per spec §4.3; Description truncated to 200 runes, omitted when empty
func SelectTables(cards []TableCard, fks []FK, noul map[string]float64, threshold float64) (selected []string, empty bool)
func MaskPII(q string) string // emails → "<email>", phone-like digit runs → "<phone>"
// Turns QueryPlan.Tables + Joins[].Table entries into qualified names from `known` ("schema.table").
// Entries may be "name", "schema.name", "name alias", or "(SELECT … FROM x JOIN y …) alias" — for
// subqueries take every FROM/JOIN target inside. Bare names resolve to the single known "schema.name"
// with that table part; unknown names (CTEs, typos) are dropped. Result is sorted and deduplicated.
func NormalizePlanTables(entries []string, known []string) []string
```

`SelectTables` keeps card order. It keeps every card with `noul[key] ≥ threshold`. Then the **bridge
rule** adds any non-selected table that has FKs (either direction) to ≥2 selected tables. When
nothing passes the threshold it returns `(allNames, true)`.

- [ ] **Step 1: Write failing tests:**
  - `TestTableQuestions_KeysAndShape`: 3 cards → keys t0..t2, `instructions.table.name` set, and no description key when empty.
  - `TestSelectTables_ThresholdKeepsOrder`
  - `TestSelectTables_BridgeTableAdded`: A–B–C chain, A and C selected, B below threshold → `[A B C]`.
  - `TestSelectTables_EmptyFallsBackToAll`
  - `TestMaskPII` with table cases:
    - `"khách 0912345678 mua gì"` → `"khách <phone> mua gì"`
    - `"+84 912 345 678"` → `"<phone>"`
    - `"a.b@x.vn"` → `"<email>"`
    - `"TXN-0004917"` unchanged
    - `"top 10 sản phẩm 2026"` unchanged
  - `TestNormalizePlanTables` (known = `public.sales`, `public.stores`, `public.refunds`):
    - `["sales s"]` → `[public.sales]`
    - `["public.stores"]` → `[public.stores]`
    - `["(SELECT store_id, SUM(x) FROM refunds GROUP BY store_id) r_agg"]` → `[public.refunds]`
    - `["cte_x", ""]` → `[]`
- [ ] **Step 2: Run** `go test ./internal/judge/ -run 'TableQuestions|SelectTables|MaskPII|NormalizePlanTables'`. Expected: FAIL.
- [ ] **Step 3: Implement.** Phone pattern: an optional `+84` or a leading `0`, then 9–10 more digits with optional spaces, dots or dashes. It must not match inside an identifier like `TXN-0004917` (require a non-alphanumeric boundary before it, and a total of ≥9 digits).
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat: Jev table-selection questions, selection with join bridges, PII masking, plan-table normalisation`.

### Task 5: `service.TableJudge` — gate, modes, caches, logging

**Files:**
- Create: `ennam.kg.go/internal/service/table_judge.go`
- Test: `ennam.kg.go/internal/service/table_judge_test.go` (fakes plus an httptest Jev server; no DB)

**Interfaces:**
- **Consumes:**
  - `judge.Client`, `judge.TableQuestions`, `judge.SelectTables`, `judge.MaskPII` (Tasks 3–4)
  - `models.Setting*` constants and `models.AIJudgeLog` (Task 2)
  - `*SettingsService.Get(ctx, key) (*models.SystemSetting, error)` (existing)
  - `store.SchemaTreeNode` (existing)
- **Produces:**
```go
type JudgeSettingsReader interface { Get(ctx context.Context, key string) (*models.SystemSetting, error) } // *SettingsService satisfies it
type ProjectJevGate interface { JevAllowedForDataSource(ctx context.Context, dataSourceID string) (bool, error) }
type JudgeLogWriter interface { Insert(ctx context.Context, l *models.AIJudgeLog) error }
func NewTableJudge(c *judge.Client, settings JudgeSettingsReader, gate ProjectJevGate, logs JudgeLogWriter, logger *slog.Logger) *TableJudge // c may be nil
type JudgeDecision struct {
    Tree   []*store.SchemaTreeNode // pruned (on + ok) or the input tree
    Finish func(planTables []string) // always non-nil; call exactly once after planning (nil = no plan)
}
func (j *TableJudge) Decide(ctx context.Context, dataSourceID, question string, tree []*store.SchemaTreeNode, renderLen func([]*store.SchemaTreeNode) int) JudgeDecision
func (j *TableJudge) Available() bool
func (j *TableJudge) Mode(ctx context.Context) models.JudgeMode
```

**Behaviour** (spec §4.4, §4.5, §4.6):
- The gate order is: client nil → mode → table count → project flag. Any "no" returns the input tree and a no-op `Finish`, with no HTTP call and no log row.
- The three settings are cached inside `TableJudge` for 5s. `SettingsService.Get` does not keep its cache fresh on its own (`settings.go:69,176`), so without this every question would cost 3 DB reads. An invalid stored mode counts as off, an invalid threshold as 0.2, and an invalid max_tables as 60.
- The project flag is cached per data source for 10s.
- **Selection cache:** an in-process LRU with **no TTL**, at most 1000 entries, evicting the least recently used. The key invalidates itself when anything sent to Jev changes:
  - `dsID`
  - `sha256(json.Marshal(TableQuestions(cards)))` — so column or description changes miss
  - `MaskPII(question)` after `normalizeNLQuery`
  - model
  - threshold

  Only `ok` results are stored. A repeated question therefore never pays Jev again until restart, which keeps the "repeated questions don't get slower" anti-goal.
- `Finish` is wrapped in `sync.Once`. Calling it twice is harmless, and its send to the shadow goroutine is non-blocking.
- **Log writes are off the request path** in both modes: a goroutine with `context.WithoutCancel(ctx)` and a 5s timeout.
- `plan_tables` and `selected` are both normalised with `judge.NormalizePlanTables` against the tree's qualified names before logging.
- Also produce `func TableCardsFromTree(tree []*store.SchemaTreeNode) ([]judge.TableCard, []judge.FK)` (exported).
- **`on` mode:**
  - On a cache hit, prune and log nothing.
  - On a miss, call Jev synchronously with the request ctx. On `ok`, prune the tree to the selected names. On error or `empty`, keep the full tree. `Finish` writes one log row with `mode=on`, the outcome, and the plan tables.
- **`shadow` mode:**
  - Return the input tree.
  - On a cache miss, and if the shadow semaphore (4) has a free slot, start a goroutine with `context.WithoutCancel(ctx)` plus the client timeout.
  - It calls Jev and **releases the semaphore slot as soon as the HTTP call returns**. Then it waits up to 2 minutes for `Finish` (a buffered channel of 1) and writes the row (`plan_tables` NULL if `Finish` never came). The planner's p90 is 6.8s, so holding the slot through the wait would starve the 4 slots.
  - When no slot is free, drop the shadow run.
- `SchemaCharsFull` and `SchemaCharsUsed` come from `renderLen(tree)` and `renderLen(pruned)`. In shadow, `SchemaCharsUsed` is the size the pruned tree would have had.
- `QueryHash` = hex sha256 of the normalized question. The raw question is never stored.
- Log-insert errors are logged at warn and never surface.

- [ ] **Step 1: Write failing tests** (fake settings map, fake gate, recording log writer, httptest Jev returning configurable scores and delay):
  - `TestTableJudge_NilClientIsOff`: no HTTP hit, same tree.
  - `TestTableJudge_ProjectNotAllowedOrMissing`: gate false or gate error → no HTTP hit.
  - `TestTableJudge_TableCountOutsideBounds`: 1 table, or `max_tables+1` tables → no HTTP hit.
  - `TestTableJudge_OnPrunesAndLogsWithPlanTables`: scores keep 2 of 4 → `Tree` has 2 tables; after `Finish([]string{"public.a"})` one row with `Outcome=="ok"`, `Mode=="on"`, `PlanTables==["public.a"]`.
  - `TestTableJudge_OnTimeoutFallsBackToFullTree`: the server sleeps past the timeout → the full tree; the row has `Outcome=="timeout"`; the call returns within timeout+100ms.
  - `TestTableJudge_OnCacheHitSkipsJev`: 2nd identical `Decide` → still 1 HTTP hit.
  - `TestTableJudge_FailureNotCached`: 1st call 500, 2nd call ok → 2 HTTP hits.
  - `TestTableJudge_ShadowReturnsFullTreeAndLogsAsync`: `Tree` = input; after `Finish(["public.b"])` the row appears (wait on the writer with a deadline) with `Mode=="shadow"`.
  - `TestTableJudge_SendsMaskedQuestion`: question `"khách 0912345678"` → the received body's `state.question` contains `<phone>` and not the digits.
  - `TestTableJudge_BadStoredSettingsActAsDefaults`: mode `"ON"` → off (no hit); threshold `"1.5"` with mode on → 0.2 is used.
  - `TestTableJudge_SettingsReadAtMostOncePer5s`: 10 `Decide` calls → the fake settings reader sees ≤ 3 reads (one per key).
  - `TestTableJudge_CacheMissesWhenColumnsChange`: same question, one column renamed → 2 HTTP hits.
  - `TestTableJudge_ShadowSlotReleasedBeforeFinish`: 5 shadow decisions without calling `Finish` → 5 HTTP hits (no starvation).
  - `TestTableJudge_FinishTwiceIsSafe`
- [ ] **Step 2: Run** `go test ./internal/service/ -run TableJudge -race`. Expected: FAIL.
- [ ] **Step 3: Implement** in `table_judge.go`. Build cards from the tree: name `schema.table`, description from `tableDescription(t.Table)`, column names in order. FKs come from `ForeignKeys` (`ReferencedSchema.ReferencedTable`).
- [ ] **Step 4: Run** the same command with `-race`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat: TableJudge decides, caches and logs Jev table selection`.

### Task 6: Wire TableJudge into the legacy context path, main.go, compose, env examples

**Files:**
- Modify: `ennam.kg.go/internal/service/query_intent.go` (`QueryIntentParser` struct, new option, `buildLegacyContext` ~L403, `ParseWithTier` ~L196–300 where the plan is returned)
- Modify: `ennam.kg.go/cmd/kg-server/main.go` (~L667–707, where the intent parser is built)
- Modify: `docker-compose.yml` (kg-server `environment:` next to `BYTEPLUS_API_KEY`), `.env.example`, `.env.release.example` (workspace root)
- Test: `ennam.kg.go/internal/service/query_intent_judge_integration_test.go`. Use `//go:build integration` and reuse `queryIntentCacheTestDB` and `seedQueryIntentFixture` from `query_intent_cache_integration_test.go`, along with that file's way of stubbing the AI planner. `metaStore` is a concrete store, so these tests need the DB.

**Interfaces:**
- **Consumes:** `NewTableJudge`, `JudgeDecision` (Task 5); `NewProjectAISettingsStore`, `NewAIJudgeLogStore` (Task 2); `judge.ConfigFromEnv`, `judge.NewClient` (Task 3).
- **Produces:**
  - `func WithTableJudge(j *TableJudge) QueryIntentOption`, which sets the new field `tableJudge *TableJudge`.
  - `buildLegacyContext(ctx, dataSourceID, nlQuery string, judge bool) (string, func([]string), error)` — the second return value is `Finish`, a no-op when the judge is off or not set.

- [ ] **Step 1: Write failing tests** with a stub Jev server and the seeded fixture tree:
  - `TestParseWithTier_JudgeOnShrinksSchemaContext`: the prompt sent to the planner contains only the selected tables, and `Finish` receives `plan.Tables` plus `plan.Joins[].Table` (raw; TableJudge normalises).
  - `TestParseWithTier_JudgeAbsentUnchanged`: the context is byte-identical to today's.
  - `TestParseWithTier_JudgeFinishOnClarification`: `Finish(nil)`.
  - `TestParseWithTier_JudgePlanCacheHitFinishes`
- [ ] **Step 2: Run** `KG_TEST_DATABASE_URL=<:5433 DSN> go test -tags=integration -v -race ./internal/service/ -run 'TestParseWithTier_Judge'`. Expected: FAIL, and all 4 tests listed (not SKIP).
- [ ] **Step 3: Implement.**
  - Add a `judge bool` parameter to `buildLegacyContext`. The no-smart-context branch passes `true`; the smart-context **fallback** at ~L206 passes `false`, so the smart path, including its fallback, never runs the judge.
  - When `judge` is true and a judge is set, call `p.tableJudge.Decide(ctx, dsID, nlQuery, tree, func(t) int { return len(p.buildSchemaContext(t, schemaContextMaxChars)) })` and render `decision.Tree`.
  - Call `Finish` on every return path of `ParseWithTier` after context building (plan → `plan.Tables` + `plan.Joins[].Table`; clarification or error → `nil`) through a single `defer` that reads a named result. `Finish` is `sync.Once`-safe.
- [ ] **Step 4: Wire it in `main.go`.**
  - `jc := judge.NewClient(judge.ConfigFromEnv(os.Getenv), nil)`.
  - Always build `NewTableJudge(jc, settingsSvc, projectAISettingsStore, aiJudgeLogStore, logger)` and append `WithTableJudge`.
  - Log `"jev judge available"` / `"jev judge unavailable (TYPESAFE_API_KEY not set)"` without the key.
  - Add the four `TYPESAFE_*` lines to compose (`${TYPESAFE_API_KEY:-}` etc.) and to both `.env*.example` files, with the §6/§7 comment.
- [ ] **Step 5: Verify:** `go build ./... && go test ./internal/service/ -race` passes; then `docker compose up -d --build kg-server` and confirm the log line. Expected: "jev judge available".
- [ ] **Step 6: Commit** in two places:
  - `git -C ennam.kg.go`: `feat: use TableJudge on the legacy schema-context path`.
  - Workspace root (compose and env examples only): `chore(env): pass TYPESAFE_* to kg-server`.

### Task 7: DAAB API — project AI settings, judge info, settings validation

**Files:**
- Create: `ennam.kg.go/internal/handler/project_ai_settings.go`
- Modify: `ennam.kg.go/internal/handler/settings.go` (`HandleUpdateSetting`, next to `validateAIModelAssignment`)
- Modify: `ennam.kg.go/internal/handler/ai_provider.go` (`ListFunctions`, `AIProviderHandler` gets an optional `judge *service.TableJudge` via setter `SetTableJudge`)
- Modify: `ennam.kg.go/cmd/kg-server/main.go` (register routes and the route-log list ~L1175)
- Test: `ennam.kg.go/internal/handler/project_ai_settings_test.go`, `ennam.kg.go/internal/handler/settings_judge_test.go`, extend `ai_functions_test.go`

**Interfaces:**
- **Consumes:** `ProjectAISettingsStore` (Task 2), `TableJudge.Available/Mode` (Task 5), `isGlobalAdmin(r)` (handler/project.go L52), `middleware.GetUserIdentity` / `GetDeveloperIdentity`, `ProjectStore.GetByID`.
- **Produces (HTTP):**
  - `GET /api/v1/projects/{id}/ai-settings` →
    `{"project_id","jev_allowed","changed_by_label","changed_via","changed_at","jev_available","judge_mode"}`
  - `PUT /api/v1/projects/{id}/ai-settings` with body `{"jev_allowed":bool,"changed_by_label"?:string}` → the same shape
  - `GET /api/v1/project-ai-settings` → `{"projects":[{project_id, jev_allowed, changed_by_label, changed_via, changed_at}]}`
  - `GET /api/v1/ai-functions` adds `"judge":{"available":bool,"mode":"off|shadow|on","threshold":number,"max_tables":int}`
  - `func validateJudgeSetting(key string, raw json.RawMessage) error`

Rules:
- All three project-AI routes return 403 unless `isGlobalAdmin(r)`.
- 404 for an unknown project. `ProjectStore.GetByID` returns a raw `sql.ErrNoRows` (`store/project.go:51-62`), so check `errors.Is`. Also check the id with `uuid.Parse` (or the repo's existing UUID check) first, so a malformed id gives 404 rather than a Postgres 500.
- **PUT with a user session:** label = the user's `DisplayName`, else `Username`; `changed_by_user_id` = `UserID`; via = `daab_web`; the body label is ignored.
- **PUT with an admin API key and no user:** `changed_by_label` is required (trimmed, 1–200 chars; else 400), via = `ennam_admin`.

- [ ] **Step 1: Write failing tests** (httptest; identity injected via `context.WithValue(ctx, middleware.UserIdentityKey|DeveloperIdentityKey, …)` as in `datasource_role_test.go`; the store faked behind a small interface defined in the handler file):
  - `TestProjectAISettings_ForbiddenForNonAdmin` (agent key, project-scoped admin key) → 403
  - `TestProjectAISettings_PutBySessionRecordsUser` → via `daab_web`
  - `TestProjectAISettings_PutByAdminKeyRequiresLabel` → 400 without a label, 200 with one and via `ennam_admin`
  - `TestProjectAISettings_UnknownProject404` (both an unknown valid UUID and `"not-a-uuid"`)
  - `TestValidateJudgeSetting` (table cases: mode `"shadow"` ok, `"ON"` 400; threshold `0.2` ok, `0`/`1`/`1.5`/`"x"` 400; max_tables `60` ok, `1`/`-1`/`2.5` 400 — the minimum allowed is 2; non-judge key → nil)
  - `TestListFunctions_IncludesJudgeInfo` (nil judge → `available:false, mode:"off"`)
- [ ] **Step 2: Run** `go test ./internal/handler/ -run 'ProjectAISettings|ValidateJudgeSetting|ListFunctions'`. Expected: FAIL.
- [ ] **Step 3: Implement** the handler, the validation call in `HandleUpdateSetting` (400 with the message), the `ListFunctions` addition, and the route registration and log list in `main.go`.
- [ ] **Step 4: Run** the same command, then `go test ./internal/handler/`. Expected: PASS. Run `make lint`. Expected: clean.
- [ ] **Step 5: Commit:** `feat: project AI settings API and judge info for the Jev switch`.

### Task 8: DAAB web — Jev section on the AI settings page

**Files:**
- Create: `ennam.kg.next/src/hooks/use-project-ai-settings.ts`, `ennam.kg.next/src/components/settings/JevSettings.tsx`
- Modify: `ennam.kg.next/src/types/ai-providers.ts` (add `JudgeInfo`, `ProjectAISettings`), `ennam.kg.next/src/hooks/use-ai-functions.ts` (return `{ functions, judge }` via a new `useJudgeInfo()`; keep `useAIFunctions()` returning functions), `ennam.kg.next/src/app/(dashboard)/admin/settings/ai-providers/page.tsx` (third section "Jev table selection")

**Interfaces:**
- **Consumes:** the Task 7 HTTP shapes through the existing `/api/kg/[...path]` proxy; `useSettings` / `useUpdateSetting` (`src/hooks/use-settings.ts`); `useProjects(true)` (`src/hooks/use-projects.ts`).
- **Produces:**
  - `useJudgeInfo(): UseQueryResult<JudgeInfo>`
  - `useProjectAISettings(): UseQueryResult<ProjectAISettings[]>`
  - `useSetProjectJev(): UseMutationResult<ProjectAISettings, Error, { projectId: string; allowed: boolean }>` (invalidates `['project-ai-settings']`)

UI copy (English, matching the page):
- Section caption: "Jev table selection".
- Intro: "Jev picks the tables a question needs so the planner reads less. Questions, table names and column names of allowed projects are sent to TypeSafe; no row data."
- Mode control: Off / Shadow / On, writing `ai.judge.table_filter` **with `category: 'ai'`**. Without it the upsert silently rewrites the category to `general`; `AIModelAssignments.tsx:150` does the same. The current mode is read from `useSettings()`, not from the `ai-functions` query, which has a 5-minute `staleTime`. After saving, invalidate both `['settings']` and `['ai-functions']`.
- Projects table: name, "Jev allowed" switch, and "changed by · via · when".
- When `judge.available=false`, every control is disabled and shows: "Jev key not configured on the server".
- Customer projects carry no special marking; the hint under the table reads: "Customer projects are normally switched in Ennam Admin."

- [ ] **Step 1: Create the branch.** `git -C ennam.kg.next switch -c feat/jev-table-selection`
- [ ] **Step 2: Implement** the types, hooks, `JevSettings` and the page section. Follow the existing settings components' classes and spacing (see `AIModelAssignments.tsx`).
- [ ] **Step 3: Verify:** `npm run lint` and `npm run build` in `ennam.kg.next`. Expected: no errors.
- [ ] **Step 4: Verify in the browser** (dev stack, admin login, http://localhost:3500/admin/settings/ai-providers):
  - With no key, the controls are disabled with the hint.
  - With the key, switch the mode to Shadow and turn on Pharmacy Chain. `GET /api/v1/project-ai-settings` shows it with `changed_via=daab_web`.
  - Screenshot at 1440 and 375 widths.
- [ ] **Step 5: Commit:** `feat: Jev mode and per-project switch on the AI settings page`.

### Task 9: Ennam Admin — DAAB client and service

**Files:**
- Modify: `ennam.kg.admin/src/lib/daab/client.ts` (the `DaabClient` interface, the real client, and the zod schema `AiSettingsJson`)
- Modify: `ennam.kg.admin/src/lib/daab/service.ts` (`setDaabJevAllowed`; `daabCardView` gains `jev`)
- Modify: `ennam.kg.admin/src/lib/audit.ts` (add `"org.daab_jev_allowed"`, `"org.daab_jev_disallowed"` beside `"org.daab_disconnected"`)
- Modify: `ennam.kg.admin/src/i18n/dictionaries/audit.ts`. Add labels `audit.action.org.daab_jev_allowed` (vi "Cho phép Jev (DAAB)" / en "Allowed Jev (DAAB)") and `audit.action.org.daab_jev_disallowed` (vi "Tắt Jev (DAAB)" / en "Turned Jev off (DAAB)"). `audit-actions.test.ts` requires a label for every action.
- Modify: `ennam.kg.admin/test/daab-fake.ts` (`FakeDaabClient` gets `getAiSettings` / `setAiSettings` with configurable answers and failures)
- Modify: `ennam.kg.admin/src/app/(staff)/orgs/[id]/page.tsx`. Start `daabCardView(...)` inside the existing `Promise.all`, not after it.
- Test: `ennam.kg.admin/src/lib/daab/client.test.ts` (extend), create `ennam.kg.admin/src/lib/daab/jev.int.test.ts`

**Interfaces — Produces:**
```ts
export type DaabAiSettings = { jevAllowed: boolean; changedByLabel: string | null; changedVia: "daab_web" | "ennam_admin" | null; changedAt: string | null; jevAvailable: boolean; judgeMode: "off" | "shadow" | "on" };
// DaabClient
getAiSettings(projectId: string): Promise<DaabAiSettings>;
setAiSettings(projectId: string, input: { jevAllowed: boolean; changedByLabel: string }): Promise<DaabAiSettings>;
// service
export async function setDaabJevAllowed(db: DbOrTx, actor: Actor, input: { orgId: string; allowed: boolean }): Promise<DaabOpResult>;
// DaabCardView gains:
jev: { ok: true; settings: DaabAiSettings } | { ok: false; kind: DaabErrorKind } | null; // null when the org has no project_id or DAAB is unconfigured
```

Rules:
- Add `"no_project"` to the `DaabOpError` union (`service.ts:32-40`).
- The project id is always `state.project_id` from `setup_state.daab`. It is kept through disconnect, so a disconnected org can still be switched.
- `setDaabJevAllowed` takes the org lock (`withOrgLock`), as the other DAAB operations do. It returns:
  - `org_not_found` when there is no org;
  - `internal_org` for an internal org;
  - `no_project` when there is no `state.project_id`.
- It sends `changedByLabel = actor.email`.
- It pre-reads the current value with `getAiSettings`. If that read fails, `previous` is `null` and the set still proceeds.
- On success it writes the audit row `org.daab_jev_allowed` / `org.daab_jev_disallowed` with `{ project_id, previous: boolean | null }`.
- `getAiSettings` uses a **2s timeout** (a per-call override of `DAAB_TIMEOUT_MS`), because it runs while the org page renders. `setAiSettings` keeps the 10s default.
- On a DAAB error it writes `org.daab_step_failed` with step `"jev"` and returns the error kind.
- Admin stores no copy of the flag.

- [ ] **Step 1: Create the branch.** `git -C ennam.kg.admin switch -c feat/jev-table-selection`
- [ ] **Step 2: Write failing tests:**
  - `client.test.ts` (use its existing fetch-mock style):
    - `getAiSettings parses DAAB's answer` (snake_case → DaabAiSettings)
    - `setAiSettings sends jev_allowed and changed_by_label`
    - `getAiSettings maps 403 to unauthorized`
  - `jev.int.test.ts` (fake client via `overrideDaabClient`, real DB):
    - `setDaabJevAllowed writes the audit row with the previous value`
    - `setDaabJevAllowed refuses without project` (`no_project`, no audit, no client call)
    - `setDaabJevAllowed records a DAAB failure` (`org.daab_step_failed`, step `jev`)
    - `daabCardView carries jev settings or the error kind`
    - `daabCardView gives up on a slow DAAB after 2s` (the fake delays 5s → `jev.ok === false`, kind `unreachable`)
- [ ] **Step 3: Run** `npm run test:unit -- src/lib/daab/client.test.ts` and `npm run test:int -- src/lib/daab/jev.int.test.ts`. Expected: FAIL.
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Run** the same commands, then `npm test`. Expected: PASS.
- [ ] **Step 6: Commit:** `feat: read and set a customer's Jev permission in DAAB`.

### Task 10: Ennam Admin — DAAB card switch and action

**Files:**
- Modify: `ennam.kg.admin/src/app/(staff)/orgs/[id]/daab-actions.ts` (`setDaabJevAction`)
- Modify: `ennam.kg.admin/src/app/(staff)/orgs/[id]/DaabCard.tsx` (new prop `isAdmin: boolean`; Jev block)
- Modify: `ennam.kg.admin/src/app/(staff)/orgs/[id]/page.tsx` (pass `isAdmin={ctx.staff.role === "admin"}`)
- Modify: `ennam.kg.admin/src/i18n/dictionaries/daab.ts` (keys below)
- Modify: `ennam.kg.admin/src/app/guard-inventory.test.ts`. Add `setDaabJevAction` to `ADMIN_ONLY` and to `REQUIRED_STAFF_ACTIONS` for `daab-actions.ts`.
- Test: `ennam.kg.admin/src/app/(staff)/orgs/[id]/DaabCard.test.tsx` (extend), `daab-actions.test.ts` (extend)

**The guard inventory checks the action's shape.** The body must start with exactly
`const ctx = await requireStaff({ role: "admin" });`, and `const su = await stepUp(ctx, fd.get("totp"));`
must come before any use of `db`.

**Interfaces:**
- **Consumes:** `setDaabJevAllowed`, `DaabCardView.jev` (Task 9); `requireStaff({ role: "admin" })` and `stepUp` (`src/lib/auth/guards.ts`); `staffActor`.
- **Produces:** `export async function setDaabJevAction(_prev: ActionState, fd: FormData): Promise<ActionState>`. Form fields: `orgId`, `allowed` (`"1"` | `"0"`), `totp`, `confirm` (must be `"1"` when `allowed=="1"`).

**i18n keys (vi / en):**

| Key | vi | en |
|---|---|---|
| `daab.jev.title` | Jev (chọn bảng cho câu hỏi) | Jev (table selection) |
| `daab.jev.on` | Đang cho phép | Allowed |
| `daab.jev.off` | Chưa cho phép | Not allowed |
| `daab.jev.allow` | Cho phép dùng Jev | Allow Jev |
| `daab.jev.disallow` | Tắt Jev | Turn Jev off |
| `daab.jev.confirm` | Chỉ bật sau khi khách hàng đã đồng ý gửi câu hỏi và tên bảng sang TypeSafe. | Only turn this on after the customer has agreed to send questions and table names to TypeSafe. |
| `daab.jev.changed` | Đổi bởi {who} qua {via} lúc {when} | Changed by {who} via {via} at {when} |
| `daab.jev.unavailable` | DAAB chưa cấu hình key Jev — bật ở đây chưa có tác dụng. | DAAB has no Jev key configured — allowing it here has no effect yet. |
| `daab.jev.unreachable` | Không đọc được trạng thái Jev từ DAAB. | Could not read the Jev status from DAAB. |
| `daab.error.no_project` | Tổ chức chưa có project DAAB. | This organization has no DAAB project yet. |

The block renders only when `view.jev !== null`.
- `ok:false` → the unreachable alert and no button.
- Non-admin → the status line only.
- Admin → the toggle form with a TOTP field. The allow form also has a required checkbox carrying the confirm text.

- [ ] **Step 1: Write failing tests:**
  - `DaabCard.test.tsx`:
    - `jev block hidden without project`
    - `jev unreachable shows alert and no form`
    - `ops sees status only`
    - `admin sees allow form with confirm checkbox`
    - `shows who/via/when`
  - `daab-actions.test.ts`:
    - `setDaabJevAction rejects allow without confirm`
    - `setDaabJevAction requires admin role`
- [ ] **Step 2: Run** `npm run test:unit -- 'src/app/(staff)/orgs/[id]'`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test` (includes `guard-inventory.test.ts` and `audit-actions.test.ts`) and `npm run typecheck`. Admin has no lint script. Expected: PASS / clean.
- [ ] **Step 5: Verify in the browser** (Admin at http://localhost:3200 against the dev DAAB):
  - Allow Jev on a connected customer org (with 2FA).
  - DAAB `GET /api/v1/projects/{id}/ai-settings` shows `changed_via=ennam_admin` and the staff email.
  - `/audit` shows `org.daab_jev_allowed`.
- [ ] **Step 6: Commit:** `feat: allow or stop Jev for a customer from the DAAB card`.

### Task 11: Replay script (spec §5.3, reduced per review)

The 200-question replay in spec §5.0 already gave the numbers, and a Go CLI would have to export private
renderers (`buildSchemaContext`, `tableDescription`). So commit the stdlib Python script that produced
§5.0 instead, for re-running after prompt, threshold or model changes.

**Files:**
- Create: `ennam.kg.go/scripts/jev-eval/jev_eval.py` (port of the smoke-test script: stdlib only, reads `TYPESAFE_*` from an env file, never prints the key)
- Create: `ennam.kg.go/scripts/jev-eval/README.md` (5 lines: what it measures, how to export `schema.json` / `gold.json` with the two `psql` queries, how to run)

- [ ] **Step 1: Port the script.**
  - Use the same question text and criteria as `judge.TableQuestionText` (Task 4). If they differ, the replay measures a different prompt from production.
  - Print the threshold table (0.1 / 0.2 / 0.3 / 0.5 × all / vi / en), latency p50/p90/max, and the misses at the chosen threshold.
- [ ] **Step 2: Run it.** `SSL_CERT_FILE=/etc/ssl/cert.pem python3 -I scripts/jev-eval/jev_eval.py <data_dir> ../.env 100`. Expected: recall 1.000 at 0.2, p90 < 800ms.
- [ ] **Step 3: Commit:** `chore: jev-eval replay script for the Jev table selection`.

### Task 12: End-to-end check in the dev stack (spec §5.4 kickoff)

**Files:** none (verification only); record results in the Serena checkpoint.

- [ ] **Step 1:** `docker compose up -d --build kg-server dashboard`, with `TYPESAFE_*` in the workspace `.env`.
- [ ] **Step 2:** In DAAB web, set the mode to **Shadow** and allow **Pharmacy Chain**. Ask 5 Vietnamese questions through LAAM chat or MCP `kg_query_datasource` (for example "Top 5 sản phẩm bán chạy nhất tháng này", "Nhân viên nào có số tiền hoàn trả cao nhất").
- [ ] **Step 3:** Check `select mode, outcome, latency_ms, selected_count, table_count, plan_tables, selected from ai_judge_logs where request_type='jev_table_select' order by created_at desc limit 5;`. Expected: 5 rows, `outcome=ok`, `plan_tables` filled and ⊆ `selected` (both qualified `schema.table`). Answers and latency in LAAM unchanged.
- [ ] **Step 4:** Switch the mode to **On** and ask 5 new questions. Expected:
  - answers are correct;
  - `ai_usage_logs` `nl_query_intent.input_tokens` for these questions is clearly below the ~11k baseline;
  - the rows have `mode=on`.
- [ ] **Step 5:** Turn Pharmacy Chain **off**, wait **15s** (the flag cache is 10s), and ask 1 new question. Expected: no new `ai_judge_logs` row for it.
- [ ] **Step 6:** Set the mode back to **Shadow** (the agreed default for dev) and write the Serena checkpoint with the numbers.
