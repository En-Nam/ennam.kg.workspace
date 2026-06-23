# Checkpoint: backend-dev — 2026-06-07

## What was done

- Implemented `GoParser` for `ennam-kg-indexer` theo plan `docs/superpowers/plans/2026-06-07-go-parser-implementation.md`
- 8 tasks, 8 commits trên branch `task/sines-enhancement` trong `ennam.kg.python` repo

### Chi tiết theo task
- Task 1: `GoParser` skeleton + registry wiring + `function_declaration` handler
- Task 2: `method_declaration` + receiver-type parent resolution (Repo, *Repo, *Box[T])
- Task 3: `type_declaration` → CLASS (struct) / INTERFACE / TYPE_ALIAS
- Task 4: `const_declaration` + `var_declaration` với multi-name spec support
- Task 5: Godoc doc-comment extraction với line-adjacency rule (`//` only, no blank gap)
- Task 6: Resilience tests (unreadable file → `[]`, malformed Go → log + extract subset)
- Task 7: Containment edge integration test (Repo struct → Save method edge qua full pipeline)
- Task 8: Full-suite verification + ruff format

## Files changed

- **Created**: `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/go_lang.py`
- **Modified**: `ennam.kg.python/packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/__init__.py`
- **Created**: `ennam.kg.python/packages/ennam-kg-indexer/tests/test_parsers/test_go.py`

## Current state

- **105/105 tests pass** (80 pre-existing + 25 Go tests), 0 failures, 0 regressions
- ruff lint clean
- Smoke test trên real `ennam.kg.go` files: 6+2+7 symbols — no tracebacks
- Branch: `task/sines-enhancement` (chưa merge vào main)
- `tree-sitter-go>=0.23` đã có sẵn trong `pyproject.toml` — không cần thay đổi deps

## Next steps

- Merge branch `task/sines-enhancement` vào main của `ennam.kg.python`
- Có thể chạy full index trên `ennam.kg.go` để kiểm tra symbols thực tế vào KG
- Markdown parser (spec: `docs/superpowers/specs/2026-06-07-markdown-indexer-parser-design.md`) chưa triển khai

## Blockers / Risks

- Không có blocker. Implementation hoàn chỉnh theo spec.

---

# Checkpoint: backend-dev — 2026-06-07 (Session 2 — Markdown Parser)

## What was done

Implemented the full `MarkdownParser` for `ennam-kg-indexer` — 9 tasks, all complete and passing.

- **Task 1**: Added `tree-sitter-language-pack>=0.9` dep, bumped `tree-sitter>=0.25.2`; added `SymbolKind.DOCUMENT`/`SECTION` and `Symbol.level`/`content` fields to `base.py`
- **Task 2**: Created `parsers/markdown.py` (`MarkdownParser`) with document hub extraction; registered in `__init__.py`; fixed 3 pre-existing tests that assumed `.md` was unsupported
- **Task 3**: Implemented `_walk_section` + helpers (`_heading_text`, `_heading_level`, `_own_range`) — own-range body hashes so subsection edits don't cascade-dirty parents
- **Task 4**: Locked hierarchy/parent threading, multi-H1, preamble skip, code-fence isolation with regression tests
- **Task 5**: Locked resilience contract (malformed → extract what we can; unreadable → `[]`)
- **Task 6**: Added `_document_to_node` branch in `extractor.py` — correct property shape, natural-key invariants preserved
- **Task 7**: `extract_edges` updated to include `DOCUMENT`/`SECTION` parents and emit `contains_section` (not `relates_to`)
- **Task 8**: Integration tests through mocked `engine.full_scan` — colon-heading natural-key round-trip verified
- **Task 9**: Full suite (122 tests pass), ruff clean, smoke-tested against 3 real markdown files (96/17/25 sections)

## Files changed

- `packages/ennam-kg-indexer/pyproject.toml` — new dep
- `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/base.py`
- `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/markdown.py` — new
- `packages/ennam-kg-indexer/src/ennam_kg_indexer/parsers/__init__.py`
- `packages/ennam-kg-indexer/src/ennam_kg_indexer/indexer/extractor.py`
- `packages/ennam-kg-indexer/tests/test_parsers/test_markdown.py` — new (17 tests)
- `packages/ennam-kg-indexer/tests/test_parsers/test_scanner.py`
- `packages/ennam-kg-indexer/tests/test_engine.py`

## Current state

- **122/122 indexer tests pass** (was 105 before this session)
- Branch: `task/sines-enhancement` (ennam.kg.python repo), last commit `3d52e07`
- `.md`/`.markdown` files now fully indexed via existing `kg_index_source`/CLI flow

## Next steps

- Merge `task/sines-enhancement` into main
- MCP tool integration for markdown indexing (plan: `docs/superpowers/plans/2026-06-06-mcp-kg-index-source-tool.md`)
- Setext heading support is out-of-scope for v1

## Blockers / Risks

- None

---

# Checkpoint: backend-dev — 2026-06-07 (Session 3 — LAAM Markdown Memory)

## What was done

Implemented the full LAAM Markdown Memory plan (`docs/superpowers/plans/2026-06-07-laam-markdown-memory-implementation.md`) in `ennam.kg.go`.

**Task 1 — auto_queue_processing setting**
- `internal/service/draft_node.go`: added `settingsReader`/`ingestionPublisher` interfaces; `UpsertFromIngestion` reads `ingestion.auto_queue_processing` from DB settings and auto-enqueues after approve
- Tests: `TestUpsertFromIngestion_AutoQueueWhenSettingOn`, `TestUpsertFromIngestion_NoQueueWhenSettingOff` (PASS)

**Task 2 — source_url plumbing**
- `internal/handler/ingest_public.go`: `source_url` field in request struct
- `internal/service/ingest_public.go`: `SourceURL` in `PublicIngestItem`, nil-guard to `*string`
- `internal/bridge/schema.go`: `source_url` in `kg_ingest_node`, `semantic` in `kg_search`
- `internal/bridge/schema_laam_test.go`: new file, 2 schema presence tests (PASS)

**Task 3 — embed client**
- `internal/embed/client.go`: `Client.EmbedQuery` → POST `/api/v1/embeddings`, 384-dim
- `internal/embed/client_test.go`: 2 tests including Authorization header assertion (PASS)

**Task 4 — semantic recall in HandleSearch**
- `internal/handler/search.go`: `QueryEmbedder` interface, `ensureQueryEmbedding`, wired into `HandleSearch`
- `internal/handler/routes.go`: embedder param forwarded
- `cmd/kg-server/main.go`: `embed.NewClient(KG_PYTHON_URL, ...)` wired into query handlers
- `internal/handler/search_test.go`: 3 `TestEnsureQueryEmbedding_*` tests (PASS)

**Task 5 — Hub node decision** — external hub per spec, no code changes

**Task 6 — Verification**
- `go build ./...`: PASS
- All 11 new tests: PASS
- Fixed pre-existing `TestSearchHandler_CrossProjectIDs_*` panic (recovery wrapper)
- Pre-existing datasource `extract-schema` panic confirmed pre-existing, not a regression

**Pre-existing compile error fixes** (prerequisites before new tests could run):
- `internal/service/node_test.go`: removed duplicate `testDecisionConfig` + 5 `TestNodeService_StoreDecision_*`
- `internal/service/update_test.go`: removed duplicate `mockNodeReaderForUpdate`, updated 4 call sites
- `internal/service/apikey_test.go`: added `Delete` method to `mockAPIKeyRepo`
- `internal/service/session_gate2_test.go`: `config.WorkScope` → `config.WorkScopeDefinition`
- `internal/service/datasource_test.go`: `validSSLModes` → `pgSSLModes`
- `internal/service/user_test.go`: added `GetKey` to `mockAPIKeySvcForUser`
- `internal/handler/session_gate2_test.go`: renamed `testConfig()` → `testGate2Config()`
- `internal/handler/sync_portal_test.go`: updated `NewSyncPortalHandler` calls (4→6 args)
- `internal/handler/user_test.go`, `auth_test.go`: added `GetKey` to `mockKeySvc`

## Files changed (ennam.kg.go)

- `internal/service/draft_node.go`, `draft_node_test.go`
- `internal/service/ingest_public.go`
- `internal/handler/ingest_public.go`
- `internal/bridge/schema.go`, `schema_laam_test.go` (new)
- `internal/embed/client.go` (new), `client_test.go` (new)
- `internal/handler/search.go`, `search_test.go`
- `internal/handler/routes.go`, `routes_test.go`
- `cmd/kg-server/main.go`
- Various test file compile-error fixes (see above)

## Current state

- Branch: `task/sines-enhancement` (ennam.kg.go repo)
- `go build ./...`: PASS
- 11 new tests: PASS
- Pre-existing datasource route test panic remains (outside scope)
- Task 7 (Docker E2E) deferred — requires running full stack

## Next steps

- Task 7 (E2E): `docker compose up -d --build`, ingest via `kg_ingest_node(auto_approve=true)`, verify embeddings, test `kg_search(semantic=true)`
- Fix remaining pre-existing datasource test panic (separate task)

## Blockers / Risks

- Docker stack not tested; Python embedding service required for semantic search in production
