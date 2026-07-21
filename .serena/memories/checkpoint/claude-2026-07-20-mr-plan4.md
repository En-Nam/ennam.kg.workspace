# Checkpoint: claude (MR Plan 4) — 2026-07-20

## What was done
Executed `docs/superpowers/plans/2026-07-20-mr-plan4-fix-content-fts-leak.md` end-to-end via subagent-driven development (implementer + independent reviewer per task), plus TWO full verification passes as the user explicitly required.

**The defect:** `derived_record` (AAAA master record) stored its AI-synthesized body under property key `content`. The shared trigger `update_search_vector()` indexes `content` UNCONDITIONALLY for every node type and never reads config — so `search.derived_record.text_search: [title, summary]` had no effect at that layer. Spec D4 violation: the AI restatement surfaced in FTS alongside the very `document_chunk`s it was synthesized from.

**The fix:** rename that ONE node type's property `content` -> `record_body` (not in the trigger's key list). Trigger deliberately untouched — `content` is legitimately searchable for document_chunk/document_section/architecture (2200+ rows).

6 tasks: config -> Go handler + MCP bridge schema (rejects legacy `content` with 400) -> migration 000079 -> real-DB regression test -> Python worker -> rebuild + real re-sync + e2e verify.

## Files changed
- `ennam.kg.go` (7 commits: 966dd65, a5826d9, 5dc5137, 37dd0fa, b37dfaf, ded9d91, e445a92): `config/config.yaml`, `internal/handler/derived_record.go` + `_test.go`, `internal/bridge/schema.go` + `schema_test.go`, `internal/config/types_test.go`, `db/migrations/000079_derived_record_content_to_record_body.{up,down}.sql`, `internal/store/derived_record_search_test.go` (new).
- `ennam.kg.python` (1 commit 9fb5dd7): `src/ennam_kg/worker.py:628` now sends `record_body`; `tests/test_aaaa_sync_master_record_stage.py`.

## Current state — VERIFIED WORKING
- Live: `derived_record` rows carrying `content` = **0**. Real record `content=false, record_body=34862 chars, leaked=false`. 9 evidence edges intact.
- **The decisive evidence:** sentinel `7666509593` is STILL FTS-findable on document(4)/document_chunk(9)/document_section(6) — the genuine verbatim sources, which SHOULD be searchable — while `derived_record` is absent entirely. Exactly D4's intent.
- Go: full suite zero failures, build+vet clean. Python: only the known pre-existing `test_parser.py::test_drops_out_of_range_span_and_orphan_relation` fails (reproduced at parent commit); all errors confined to docker-dependent `tests/e2e/`.

## Key discoveries worth remembering
1. **Pass 2 (adversarial) found what pass 1 missed:** `update()` merges via `partial.MergeProperties`, which PRESERVES stored-only keys — so a stale `content` key SURVIVED a legitimate upsert and stayed searchable. Fixed (ded9d91) with `props["content"] = nil` (merge.go:38-46 genuinely deletes on nil). Lesson: a confirming review and a refuting review find different things.
2. **`make db-migrate` defaults to KG_DB_PORT=5432**, which is the UNRELATED container `ennam-kg-postgres`. The real dev DB is `daab-postgres` on **5433**. Cost a task real time. See `mem:global/preferences/...` and the workspace memory file.
3. The plan's Task-3 commit command said `migrations/`; the real path is `db/migrations/`.

## Next steps
- Rotate the dev-stack admin API key (a subagent wrote it into a scratch report; redacted, never git-tracked).
- Consider follow-up: service-layer guard rejecting a `content` property when node_type=='derived_record' — generic node endpoints still allow unknown JSONB fields (pre-existing, no producer reaches it, and ded9d91 now makes it self-heal).
- Run real `golangci-lint` in CI — unavailable in this sandbox throughout, `go vet` substituted.
- Cosmetic: `config.yaml:701` prose still says "full non-indexed content".

## Blockers / Risks
None blocking. Full audit trail in `.superpowers/sdd/progress.md`.
