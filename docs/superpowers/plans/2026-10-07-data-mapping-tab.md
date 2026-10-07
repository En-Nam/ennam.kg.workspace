# Data Mapping Tab (phase 1, no AI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a project admin set up the project's data mapping from the DAAB dashboard: download a template (or the current mapping), upload a mapping YAML, see problems in plain words and a diff against the current mapping, approve/apply it, and have metrics recomputed. Replaces the CLI-only `kg-packs import-mapping` + hand-edited `_projects/.../mapping.yaml` workflow for non-technical users.

**Architecture:** Extract the CLI's mapping logic into a Go library (`internal/intel/admin/mapping.go`, structured results, no `io.Writer`), keep the CLI as a thin wrapper, add project-admin HTTP endpoints, and a "Data mapping" tab in the dashboard. Packs get an optional `description:` per canonical field so the template and screens can explain each field. AI drafting is phase 2 and NOT in this plan.

**Tech Stack:** Go (net/http mux, existing intel/intelstore/livesource/engine packages), Next.js dashboard (Tailwind, react-query, existing `/api/kg` proxy), pack YAML.

**Spec/context:** `docs/superpowers/specs/2026-09-25-industry-pack-proactive-intelligence-design.md`; survey report summarised in the "Facts" section below.

## Global Constraints

- **No DB schema changes / no migrations** (mapping history/rollback is explicitly deferred). LAAM is not touched.
- **Non-technical users:** plain everyday words; never show raw error codes, expressions like `CAST(NULL AS ...)`, UUIDs as primary labels; every problem says what is wrong, where (entity and field), and what to do; confirm before applying; helpful empty/loading/error states; no horizontal scroll at 375px; keyboard accessible. The DAAB dashboard has no i18n: inline English like the rest of that app.
- **Authz:** all new endpoints require project role Admin (`requireProjectAccess` + `requireProjectRole(..., models.ProjectMemberRoleAdmin, resolver)`), `validProjectID` first, bodies capped (256 KiB for YAML bodies), errors `{"error":{"code","message"}}` via `writeIntelError`. Never log the YAML body or any connection details.
- **Safety:** validation writes nothing; apply is all-or-nothing at the validation level (any error => nothing written, as today); apply is idempotent (same file twice converges); the customer database is never contacted by validation (uses the synced schema tables only).
- **Validation catalog:** validate against the packs ENABLED for the project (`engine.ProjectCatalog`), not all packs on disk (the CLI's current behaviour for the CLI wrapper stays "all packs" only if a flag says so; default for the library is the project's packs; keep CLI tests green by passing an explicit catalog).
- **Packs repo:** changes to `ennam.kg.packs/` (a git clone inside the workspace, mounted by the running stack) are committed locally; **never push** (user approves pushes). Because the Go pack loader today rejects unknown field attributes, the Go loader change MUST be committed and running before any `description:` is added to a pack file.
- DB-backed Go tests only via `KG_TEST_DATABASE_URL`/`KG_TEST_DSN` built from `docker exec daab-postgres printenv` on **:5433**, never :5432; report skips. No docker compose; no container restarts; do not read `.env` or `envfiles/`.
- Code comments and commit messages in English; trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; explicit `git add <paths>` (never `git add -A`; `.spectex/` and other unrelated files exist). TDD in Go; `ennam.kg.next` has no test infra: verify with lint on touched files and `npm run build`.

## Facts from the survey (verify when you touch the code)

- CLI: `cmd/kg-packs/main.go` `cmdImportMapping` (~199-242) and `importMapping` (~269-340): `ParseMappingFile` (`internal/intel/mapping_file.go`, `KnownFields(true)`), `reg.Effective(all)` -> `intel.Compiler{Dialect: intel.Postgres{}, Catalog}`, `livesource.New(...).Bind(ctx, projectID, mapping)` (`internal/intel/livesource/live.go:89-128`: checks approved status, project ownership, Postgres, synced schema, table exists — columns come from `source_tables/source_columns`), `Compiler.EntityCTE` returns `*intel.MappingError{Entity, Code, Detail}` (`internal/intel/source.go:70-78`, codes `invalid_spec`, `missing_required_field`, `invalid_expression`, `invalid_timezone`; stops at first problem per entity), writes via `intelstore.UpsertMapping` (bumps version only if changed; unchanged keeps status; changed => proposed unless approved+approvedBy), then `ListMappings` read-back. Statuses: `proposed|approved|broken`. `mode: file` entities are not validated against a table (`file_dataset` name).
- Table `project_mapping` (migration `000089`): `entity, mode, data_source_id, file_dataset, spec JSONB {from, fields, enum_map}, status, version, approved_by, approved_at`; `ListMappings` returns specs but not approved_by/at. No serializer exists; `MappingSpec` has yaml tags (`types.go:136-140`).
- Canonical metadata: `intel.Field{Name, Type, Key, Required}`, `Entity{Name, Fields}`, `Catalog.Enums["<entity>.<field>"]`; the loader rejects any other field attribute (`pack.go:361-364`, `decodeFields`, `fieldYAML`). `MetricDef.Requires` lists entities a metric needs (`internal/intel/types.go`). Availability is entity-level (`engine/availability.go:43-73`); an unmapped optional field compiles to `CAST(NULL AS type)` and metrics still run.
- Recompute: `engine.Scheduler.Trigger(projectID)` is non-blocking (queue 64, drops when full); a run in progress is skipped; no run id/progress API; status is visible through `data_status`.
- Schema tree API: `GET /api/v1/data-sources/{id}/metadata` (`handler/datasource.go:584-606`; project-role check NOT verified), `POST .../extract-schema`, `POST .../sync-schema?dry_run=true` (project Developer).
- Dashboard: tabs in `ennam.kg.next/src/app/(dashboard)/projects/[id]/layout.tsx` (`projectTabs`), page pattern `projects/[id]/packs/page.tsx`, hooks `src/hooks/use-project-packs.ts`/`use-template-library.ts`, upload dropzone `src/components/sources/upload-dropzone.tsx`, result list `src/components/sources/tabular-upload-report.tsx`; the `/api/kg` proxy forwards text bodies (YAML goes inside a JSON body `{"yaml": "..."}`), no new proxy needed.

## HTTP contract (exact; all tasks code against it)

Base: `/api/v1/projects/{id}/mapping` (project Admin).

- `GET .../mapping` -> 200
```json
{
  "project_id": "uuid",
  "packs": ["retail", "pharmacy"],
  "data_sources": [{"id": "uuid", "name": "Pharmacy POS DB", "schema_synced": true}],
  "entities": [
    {"entity": "sale", "description": "…", "required_by_metrics": ["retail.net_sales"],
     "mapped": true, "mode": "live", "status": "approved", "version": 3,
     "data_source_id": "uuid", "file_dataset": "",
     "mapped_fields": ["sale_id"], "missing_required": [], "missing_optional": ["notes"]}
  ],
  "summary": {"entities_total": 17, "entities_mapped": 17, "entities_approved": 17, "entities_attention": 0}
}
```
  `entities` lists every entity of the project's enabled packs (mapped or not); `required_by_metrics` = metric keys whose `Requires` include the entity; `status` is `""` when not mapped; entities with status `broken` or `proposed` count under `entities_attention`.
- `GET .../mapping/template?data_source_id=<uuid>` -> 200 `application/x-yaml` (attachment `mapping-template.yaml`): complete template for the project's packs: `project_id`, `defaults{mode: live, data_source_id}`, every entity with every field as `field: ""` plus comments (field description, type, required/key, allowed enum values) and an `enum_map` placeholder for fields with enums. `data_source_id` optional (placeholder comment if absent); 400 `invalid_request` for a malformed id.
- `GET .../mapping/current` -> 200 `application/x-yaml` (attachment `mapping-current.yaml`): the stored mapping re-serialised in the same file format (round-trips through `ParseMappingFile`); 404 `no_mapping` when nothing is stored.
- `POST .../mapping/validate` body `{"yaml": "<text>"}` (<=256 KiB) -> 200 (never writes)
```json
{"ok": false,
 "issues": [{"entity": "sale", "field": "sold_at", "code": "missing_required_field", "message": "Required field 'sold_at' is not mapped.", "severity": "error"}],
 "diff": [{"entity": "sale", "change": "changed", "fields": [{"field": "sold_at", "before": "created_at", "after": "transaction_datetime"}]}],
 "summary": {"entities": 17, "errors": 1, "warnings": 2, "added": 0, "changed": 1, "unchanged": 16, "removed": 0}}
```
  `change` ∈ `added|changed|unchanged|removed` (removed = in current mapping but absent from the upload; apply does NOT delete entities, it only warns). Issue `code` ∈ `parse_error`, `project_mismatch`, `unknown_entity`, `unknown_field`, `missing_required_field`, `invalid_spec`, `invalid_expression`, `invalid_timezone`, `unknown_table`, `unknown_column`, `source_not_ready`, `unsupported_source`, `enum_value_unknown` (ERROR: the compiler rejects unknown enum values, so storing one would leave a broken mapping), `entity_not_in_enabled_packs` (warning), `removed_entity` (warning); `severity` ∈ `error|warning`. Parse errors carry the YAML line when known (`line` int, omitted otherwise). `ok` is true iff there are no errors.
- `POST .../mapping/apply` body `{"yaml": "<text>", "approve": true}` -> 200 `{"applied": [{"entity","status","version","changed"}], "recompute_triggered": true|false}`; 422 `mapping_rejected` with the same `issues` array when validation has errors (nothing written); 409 `schema_not_synced` when a live source has no synced schema ("Sync the data source schema first"); 409 `recompute_in_progress` is NOT an error (apply succeeds, `recompute_triggered:false`). `approve:false` stores as `proposed`. Audit slog line `intel mapping: applied` with project id, user/key id, entity count, never the YAML.

---

## File Structure

**ennam.kg.go:** `internal/intel/types.go`, `internal/intel/pack.go` (Field.Description), `internal/intel/admin/mapping.go` + `mapping_template.go` + `mapping_diff.go` + `mapping_marshal.go` (+ tests), `internal/handler/intel_mapping.go` (+ test), `cmd/kg-server/intel_wiring.go`/`main.go` (wiring), `cmd/kg-packs/main.go` (thin wrapper).
**ennam.kg.packs (local clone, commit only):** `retail/daab/canonical.yaml`, `pharmacy/daab/canonical.yaml`, `pack.yaml` versions, `CHANGELOG.md`, README note about `description`.
**ennam.kg.next:** `src/app/(dashboard)/projects/[id]/mapping/page.tsx`, `src/hooks/use-project-mapping.ts`, `src/types/project-mapping.ts`, `src/lib/project-mapping.ts` (plain wording for codes), `src/components/mapping/*`, `layout.tsx` (tab).

---

### Task 1: Field descriptions in packs (Go loader first, then pack files)

**Interfaces:** `intel.Field` gains `Description string` (yaml `description`, optional, max 200 chars, single line). `decodeFields`/`fieldYAML` accept it; every consumer that copies Fields keeps it (`cloneEntity`/`Effective`). No behavior change when absent.

- [ ] **Step 1 (Go, test first):** tests in `internal/intel` (loader test style): a pack with `description: "When the sale happened"` loads and `Catalog.Entities["sale"].Fields[i].Description` is set; description >200 chars or containing a newline is rejected with the file:line error; unknown attributes other than type/key/required/description still rejected; packs without descriptions unchanged. Run -> FAIL; implement; `go test -race -count=1 ./internal/intel/...` green; commit in `ennam.kg.go` (`feat(intel): optional field descriptions in canonical packs`).
- [ ] **Step 2 (packs, only AFTER step 1 is committed):** in `ennam.kg.packs/` add a `description:` to EVERY field of `retail/daab/canonical.yaml` and `pharmacy/daab/canonical.yaml` (plain English, <=100 chars, written for a store manager: e.g. `sold_at: When the sale was rung up`); bump both `pack.yaml` to `0.3.0` (MINOR: additive), add the CHANGELOG entry and a README line describing `description`. Run `bash _scripts/release_test.sh`, and `cd ennam.kg.go && PACKS_DIR=<workspace>/ennam.kg.packs go test -count=1 ./internal/intel/... ` (expect retail 27 / pharmacy 33 metrics). Commit locally in `ennam.kg.packs` (`feat: describe every canonical field`). Do NOT push. Note in the report that a DAAB binary older than step 1 cannot load these packs.

### Task 2: Mapping library (`internal/intel/admin/mapping*.go`) and thin CLI

**Interfaces (exact):**
```go
type Issue struct{ Entity, Field, Code, Message, Severity string; Line int }
type FieldChange struct{ Field, Before, After string }
type EntityDiff struct{ Entity, Change string; Fields []FieldChange }
type Summary struct{ Entities, Errors, Warnings, Added, Changed, Unchanged, Removed int }
type ValidationResult struct{ OK bool; Issues []Issue; Diff []EntityDiff; Summary Summary; Mappings []intel.Mapping }
type Binder interface { Bind(ctx context.Context, projectID string, m intel.Mapping) (livesource.Bound, error) } // satisfied by *livesource.Resolver
type MappingStore interface { ListMappings(ctx context.Context, projectID string) ([]intel.Mapping, error); UpsertMapping(ctx context.Context, m intel.Mapping, approvedBy string) (intel.Mapping, error) } // adapt to the real intelstore signatures

func ParseAndValidate(ctx context.Context, b Binder, cat *intel.Catalog, current []intel.Mapping, projectID string, raw []byte) (*ValidationResult, error)
func DiffMappings(current, proposed []intel.Mapping) []EntityDiff        // pure
func Template(cat *intel.Catalog, projectID, dataSourceID string) []byte  // pure, YAML with comments (description, type, required/key, enum values)
func MarshalMappingFile(projectID string, ms []intel.Mapping) ([]byte, error) // pure; ParseMappingFile(MarshalMappingFile(x)) == x
func Apply(ctx context.Context, st MappingStore, ms []intel.Mapping, approve bool, approvedBy string) ([]Applied, error)
type Applied struct{ Entity, Status string; Version int; Changed bool }
func Coverage(cat *intel.Catalog, ms []intel.Mapping) []EntityCoverage // per entity: mapped_fields, missing_required, missing_optional, required_by_metrics
```
Behavior: `ParseAndValidate` turns parse errors into `parse_error` issues (with line when the YAML library gives one), maps `intel.MappingError` codes and `Bind` errors (`project_mismatch`, `unsupported_source`, `ErrSourceNotReady` -> `source_not_ready`, `missing_table` -> `unknown_table`) to the issue codes in the contract with plain messages (never raw SQL), checks every mapped canonical field exists (`unknown_field`) and every source column exists (`unknown_column`, using the bound table's columns), unknown entities (`unknown_entity` error when not in ANY loaded pack; `entity_not_in_enabled_packs` warning when it exists but not in `cat`), enum_map values vs `Catalog.Enums` (`enum_value_unknown` warning), and `removed_entity` warnings for stored entities absent from the upload. Collect ALL issues per pass where practical (EntityCTE stops at the first problem per entity: call it per entity and also add the field-level checks above so users see more than one problem). `mode: file` entities are not bound; they only get structural checks. `Apply` refuses (returns the issues) when errors exist; the caller passes only validated mappings. Messages are English plain sentences ("Required field 'sold_at' is not mapped.", "Column 'created_at' does not exist in table 'transactions'.").
`cmd/kg-packs` `importMapping` becomes a wrapper over `ParseAndValidate` + `Apply` with the same stdout/exit behaviour and error strings used by its existing tests (they stay green; the CLI passes the catalog of ALL packs as today).

- [ ] **Step 1:** tests first (`internal/intel/admin/mapping_test.go`): pure tests for Template (contains every entity/field with descriptions, enum values, placeholder data source, parses back with `ParseMappingFile` after filling nothing? — template must be PARSEABLE as YAML even though fields are empty strings: assert it parses and every field value is `""`), MarshalMappingFile round-trip on the demo fixture `internal/intel/packtest/testdata/pharmacy-chain-mapping.yaml`, DiffMappings (added/changed/unchanged/removed, field-level before/after), Coverage; validation tests with a fake `Binder` (table/columns in memory): unknown entity/field/column/table, missing required field, bad expression, parse error with line, enum warning, multiple issues in one pass, mode file passes. DB-backed tests (same gating as `cmd/kg-packs/main_test.go`'s `cliDB`) for `Apply`: idempotent re-apply (no version bump), changed spec -> new version and `proposed` unless approved, error => nothing written. Run -> FAIL.
- [ ] **Step 2:** implement (files <~300 lines each), refactor `cmd/kg-packs/main.go`; `go build ./... && go vet ./... && go test -race -count=1 ./internal/intel/... ./cmd/kg-packs/...` (DB env on :5433; report skips) and gofmt on touched files.
- [ ] **Step 3:** commit in `ennam.kg.go`: `feat(intel): mapping library with validation, diff, template and apply (CLI is a thin wrapper)`.

### Task 3: Mapping HTTP endpoints

**Files:** `internal/handler/intel_mapping.go` (+ `_test.go`), `cmd/kg-server/intel_wiring.go`, `main.go`.

**Interfaces:** consumes Task 2. Handler struct takes: the library functions through small interfaces (store, binder, catalog provider `func(ctx, projectID) (*intel.Catalog, error)` using `engine.ProjectCatalog` with the holder's registry snapshot), the data source list for the project (`data_sources` with `schema_synced` computed from the synced schema tables via the existing store), `RunTrigger` (`sched.Trigger`), role resolver, logger. Implement exactly the HTTP contract above. `schema_synced` and the `data_sources` array come from existing stores (read how `handler/datasource.go` lists project sources; do not call the customer DB). When the registry is not loaded return 503 `packs_unavailable`; when the project has no enabled packs return 200 with empty `entities` and a `packs: []`.

- [ ] **Step 1:** tests first with fakes in the style of `intel_packs_test.go`/`intel_packs_admin_test.go`: 403 for Viewer/Developer and non-members, 400 malformed project/data source ids and non-JSON/oversize bodies, `GET mapping` coverage numbers, template and current YAML responses (headers, parse back), validate returns issues/diff without writing (fake store records zero writes), apply happy path writes and triggers recompute once (fake trigger), apply with errors -> 422 and zero writes, apply twice is idempotent, `schema_not_synced` 409, audit slog line contains no YAML. Run -> FAIL.
- [ ] **Step 2:** implement and wire; `go build ./... && go vet ./... && go test -race -count=1 ./internal/handler/... ./internal/intel/... ./cmd/...` (DB env on :5433; report skips), gofmt.
- [ ] **Step 3:** commit in `ennam.kg.go`: `feat(intel): project admin endpoints for data mapping`.

### Task 4: Dashboard "Data mapping" tab

**Files:** the dashboard files listed above. Consumes the HTTP contract through `/api/kg/projects/{id}/mapping/...` (YAML responses via `fetch` + blob download; request bodies `{"yaml": ...}`; the existing proxy forwards text, check that it preserves `application/x-yaml` content-type and attachment headers for GET, and if not, extend `src/app/api/kg/[...path]/route.ts` minimally with a test-free manual verification).

Page behavior (plain words; project Admin only; others see "Only project admins can change the data mapping." and the read-only summary):
1. **Summary header:** "Your data mapping" with the counts ("17 of 17 data groups are set up", "2 need attention") and a list of entities: friendly label (humanize `sale_line` -> "Sale lines"), status chip (Set up / Needs approval / Needs attention / Not set up) with icon+text, and for not-set-up or incomplete entities "Needed for: {metric names humanised}" and the missing required fields with their descriptions.
2. **Step panel:** (1) "Download a template" (choose the data source from a dropdown when there are several; button **Download template**; a secondary link **Download the current mapping**), (2) "Upload your file" (dropzone, .yaml/.yml, 256 KiB cap with a plain message), (3) "Check" runs validate automatically after upload, (4) results: a green/amber/red banner, issues grouped by entity, each with a plain sentence from `src/lib/project-mapping.ts` (code -> wording + "what to do": e.g. `unknown_column` -> "We couldn't find the column '{value}' in table '{table}'. Check the spelling in your file, or sync the data source schema if the table is new."), a diff view ("Changed: sale · sold_at: created_at -> transaction_datetime"), and (5) **Apply mapping** enabled only when `ok`; a confirm dialog: "Apply this mapping? Numbers for this project will be recalculated using it. Download the current mapping first if you may want to go back." with a checkbox-less single confirm; after success: "Mapping applied. Recalculating your numbers…" and a link to the Knowledge/Data status; errors `schema_not_synced` -> "The data source schema hasn't been synced yet. Open Data Sources, sync it, then try again." with a link to the project's Data Sources.
3. Empty/loading/error states; all buttons keyboard accessible; no horizontal scroll at 375px; uploaded file name shown; **Start over** link clears state.

- [ ] **Step 1:** types, hooks (`useProjectMapping`, `useValidateMapping`, `useApplyMapping`, error class with Go code/status like `use-project-packs.ts`), plain-wording module covering EVERY issue/error code in the contract (a default wording for unknown codes).
- [ ] **Step 2:** page + components + tab entry `{ href: .../mapping, label: 'Data mapping' }` after Industry Templates.
- [ ] **Step 3:** `npm run lint` on touched files and `npm run build`; visual check with mocked fetch on a temporary dev server (Playwright) at 1440 and 375 for: loading, not-admin, summary with attention items, template download area, upload with errors+warnings, diff, valid file + apply confirm, apply success, schema_not_synced; view the screenshots; state honestly what was and was not verified; remove temp files/servers.
- [ ] **Step 4:** commit in `ennam.kg.next`: `feat(projects): Data mapping tab to download a template, upload, check and apply a mapping`.

### Task 5: End-to-end verification (scratch), docs, final review

- [ ] **Step 1 (scratch DB, not the dev DB data):** with the Go handler tests plus a throwaway Postgres container? NOT allowed (no docker): use the dev DB :5433 ONLY through Go tests that create their own project rows and clean up. Exercise through the handler layer: template -> fill with the demo mapping fixture -> validate (expect OK) -> apply -> `GET mapping` shows all 17 entities approved -> re-apply idempotent -> deliberately broken file -> issues in plain words. Record the outputs.
- [ ] **Step 2:** manual UI verification is limited to the mocked-fetch screenshots from Task 4 (state so); list "not verified": real browser against the running stack after rebuild, real LLM (phase 2), `GetMetadata` project-role gap (see Task 3 report if the implementer checked it).
- [ ] **Step 3:** docs (Vietnamese): new section in `docs/superpowers/runbooks/2026-10-07-data-mapping.md`: how to set up a customer's mapping from the UI, the order (packs -> mapping -> recalculation), template/current/upload/apply, what the problems mean, what is NOT done (history/rollback, AI draft, field-level metric dependency), and the pack note that `description` needs DAAB built after commit X; update the usage guide pointer. Commit docs in the workspace repo with explicit paths.
- [ ] **Step 4:** final whole-branch review (separate agent), fixes, then summary to the user with the approval-gated steps: pushing `ennam.kg.packs` 0.3.0, rebuilding images and recreating containers.

---

## Review Focus

- A mapping file that is valid YAML but names another project (`project_mismatch`), a huge file, a file with duplicate entity keys, a template filled in wrongly, Windows line endings or a BOM.
- Apply twice concurrently; apply while a recompute runs; apply when the data source schema is stale; apply with `approve:false`.
- Authorization: Viewer/Developer/non-member/project-scoped API key; the schema tree endpoint's missing role check must not be reused by these endpoints.
- No YAML body, connection string or SQL in logs or error messages; validation never contacts the customer DB.
- The pack loader change must not break DAAB startup with existing packs (no descriptions) and a pack WITH descriptions must be loadable only by the new binary (documented).
- Non-technical wording for every code; entities with no description fall back to a humanised name.

## Self-Review

- **Coverage:** template download, current download, upload + plain-language validation, diff, apply with recompute, coverage summary (T2-T4), field descriptions (T1), docs/verification (T5). AI draft and rollback are explicitly out of scope.
- **Type consistency:** `Issue`/`EntityDiff`/`Summary`/`Applied` (T2) = JSON in the contract (T3) = dashboard types (T4); issue codes enumerated once in the contract.
- **Placeholders:** none; bounded choices (store/binder adapter signatures follow the real intelstore code).


## Decisions recorded after Task 2 (binding for Tasks 3-5)

- Library signatures differ slightly from the brief (see `.superpowers/sdd/2026-10-07-data-mapping-tab/task-2-report.md`): `ParseAndValidate`/`Validate` take an extra `all *intel.Catalog` (every loaded pack; nil = same as `cat`): the handler passes the project's catalog from `engine.ProjectCatalog` as `cat` and the all-packs catalog from the registry holder as `all`. `Binder.Bind` returns `*intel.BoundSource`; `MappingStore.UpsertMapping` returns `(int, error)`. `Apply` does NOT validate: the handler must check `res.OK` and pass `res.Mappings`.
- `enum_value_unknown` is an ERROR. Blank values in an uploaded file mean "not mapped" (so a partly filled template uploads cleanly); untouched template entities are skipped.
- Unknown data source in a file surfaces as `project_mismatch`; any other `Bind` failure is an internal error (HTTP 500 `internal`, never echo the raw error).
