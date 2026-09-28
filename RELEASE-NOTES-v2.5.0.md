# DAAB — Ennam Knowledge Graph Platform · Release v2.5.0

**Date:** TO BE COMPLETED (set when the images are built)
**Previous release:** v1.0.0 (2026-06-24, `ennam.kg.go` @ `4dfdda2`)
**Source commits (branch `task/implement_docs_sync`):**

| Repo | Commit |
|---|---|
| `ennam.kg.go` | `88c132d` |
| `ennam.kg.python` | `c758f82` |
| `ennam.kg.next` | `453af33` |
| `ennam.kg.workspace` (release scripts, compose bundle) | this commit |

> **Version number.** The release version jumps from v1.0.0 to v2.5.0. No 1.x or 2.0–2.4 releases were
> built in between; the changes below are everything since v1.0.0 (about 180 Go, 91 Python and
> 39 dashboard commits, 2026-06-25 → 2026-09-25).

## Images

Same three images as v1.0.0, tagged `:v2.5.0`, `:<go commit SHA>` and `:latest`:
`daab-server` (Go API), `daab-python` (indexer + worker), `daab-dashboard` (Next.js).

- Build and push: `VERSION=v2.5.0 scripts/release-local.sh push` (v2.5.0 is now the default).
- Run: `docker compose -f docker-compose.release.yml up -d` (defaults to `v2.5.0`; override with
  `KG_RELEASE_TAG`).
- `kg-server version` and `GET /api/v1/version` report `v2.5.0` (the version is passed as a build
  argument by both `release-local.sh` and `deploy-local.sh`).

| Image | Size |
|---|---|
| `daab-server` | TO BE COMPLETED |
| `daab-python` | TO BE COMPLETED |
| `daab-dashboard` | TO BE COMPLETED |

## Schema

Migrations up to `000087` (v1.0.0 shipped at schema version 66). The self-hosted profile auto-migrates on
start-up; staging and production use `kg-migrate`.

## What's new since v1.0.0

### Natural-language data query (MCP / API)
- New MCP tools `kg_query_datasource` / `kg_query_datasource_status`; server-side long-poll on query status
  (`wait_seconds`).
- **Plan cache**: a repeated question is served from its stored query plan without an AI call; the cache is
  invalidated when the schema changes.
- **Schema descriptions**: every table and column gets a description so the planner stops guessing
  (optional LLM-written table descriptions); value hints sampled from the source database.
- Hardened NL→SQL: operator whitelist, `HAVING`, JOIN fan-out guard, alias-aware plan validation,
  reserved-keyword guard, date expressions inlined, column-to-column comparisons, time windows,
  inverted-ranking repair, clarification options with one computation each.
- Numeric results returned as JSON numbers, with a `max_rows` result cap.

### Controlled writes to source databases
- Opt-in write path: `allow_writes` + `write_tables_whitelist` per data source, table description and a
  validated single-row insert (PostgreSQL), every attempt audited.
- **Write playbooks**: server-side, atomic multi-table operations; deterministic proposer from schema
  analysis; approval lifecycle (draft → approved → stale on schema drift, re-approve, disable).
- Dashboard: Write Access card and Write Playbooks panel on the data-source page.

### Data sources
- **MySQL / MariaDB** support (schema sync and queries), alongside PostgreSQL and SQL Server.
- Schema-sync stall root causes fixed; sync errors and warnings surfaced in the dashboard.

### Document-management sync (AAAA source connection)
- New source connection type with encrypted credentials, a sync queue and per-document isolation;
  dashboard connect/sync card, live sync progress and a stuck-sync warning.
- Master-record sync with hash skip, tombstone revoke and a per-connection reconcile sweep.

### Retrieval and graph
- Retrieval modes: parent-section expansion and entity-anchored cross-document retrieval; IDF-weighted
  entity expansion; optional inline chunk snippets; slim neighbour projection.
- Related documents and shared entities (`kg_related_documents`, `kg_document_shared_entities`).
- Background worker builds `similar_to` edges for fresh projects; higher HNSW `ef_search` for seeds.
- Cross-upload deduplication by content hash.
- Derived records (`kg_upsert_derived_record`, `kg_get_master_record`) with atomic provenance edges
  and a revoke route.

### Entity resolution
- Exact-name hub merges (`apply-exact-name`, optional auto-apply) with a name-classification store and
  genericness guards.
- Fuzzy alias merge with LLM adjudication, stratified precision sampling and review-cleared merges.

### Document ingestion and OCR
- Tiered PDF extraction: text layer first, then Tesseract (`vie`) plus RapidOCR per scanned page;
  OCR of pages whose text layer is Latin-mangled Vietnamese; per-page error isolation.
- Entity names kept in their original language; concept nodes reused per project.
- Extraction retries once on unparseable JSON instead of dropping entities; ingestion substrate failures
  now fail loudly; XLSX financial data no longer mangled.

### Agent memory
- Recall with recency decay, usage-aware eviction and a retention worker (deduplication, growth bound).
- Scope-aware PII filter on recall.

### MCP bridge
- Connection-aware server instructions (the server introduces the project and data sources a caller is
  bound to); a configured default project pins the scope.
- Misrouted tool calls return an error naming the right tool; null optional arguments treated as
  omitted.

### Dashboard
- Redesigned overview, activity, projects and data-source pages; unified dark palette; themed dialogs.
- 3D knowledge-graph explorer (GPU-batched, off-thread layout, direction-flow particles, type filter).
- AI providers: `supports_tools` / `supports_json` toggles; friendlier per-function model assignment.
- Sign-in with email through the identity provider (SSO).

### Security fixes
- Cross-project read leak in neighbour queries closed; IDOR fixes on exact-name apply endpoints.
- Edge-whitelist target-type validation enforced on inline links, with transactional rollback.
- Usage-metrics rollups and activity/audit recording wired correctly.

## Build & verification — TO BE COMPLETED before sharing this release

Run and record here, as for v1.0.0:
- [ ] Build the three images from the commits above (`scripts/release-local.sh push`); record sizes.
- [ ] Go: `go test -race ./...` including the integration-tagged isolation suite against a real Postgres.
- [ ] Python: `uv run pytest` (baseline at these commits: 922 passed, 1 failed, 20 skipped).
- [ ] Smoke test of `docker-compose.release.yml`: health checks green, `/readyz` 200, auto-migration to
      `000087`, `/api/v1/version` returns `v2.5.0`, `/api/v1/projects` 401 without / 200 with a key,
      dashboard sign-in.

## Known limitations

See the technical documentation pack (`ennam.kg.requirements/tech_docs`, DAAB doc 04 §5.3 and doc 03 §8)
for the full list of hardening items before production. Highlights: API-wide rate limiting, source-connection
webhook secrets not yet encrypted at rest, database-level read-only sessions only on PostgreSQL, two Python
paths that call a model provider directly (outside the usage log and circuit breaker), no CI for the Python
and dashboard repositories.
