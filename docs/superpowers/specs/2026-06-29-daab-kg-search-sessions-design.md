# DAAB `kg_search_sessions` — Design

**Date:** 2026-06-29
**Status:** APPROVED (design) — ready for implementation plan
**Scope:** DAAB (`ennam.kg.go`) — session/conversation search over `thread_messages`
**Owner role:** DAAB is the ecosystem keystone owner of shared memory; `kg_search_sessions` is the last P1 keystone deliverable. **LAAM** is the Phase-2 consumer.
**Related decisions:** `mem:decisions/ecosystem-hermes-allocation` (DAAB owns session search; "FTS + VN/CJK trigram", "raw windowed ts_headline, no LLM summary", "hybrid RRF > FTS-only"), `mem:decisions/daab-hermes-keystone-verification` (confirms `kg_search_sessions` = NET-NEW; RBAC body-trust IDOR class).

---

## 1. Problem

Conversation transcripts are stored (`thread_messages.content`) but **not searchable** — only B-tree `(thread_id, created_at)` and a GIN on `response_blocks` exist. There is no way to answer "what was said about X in past conversations?" The ecosystem needs this once, owned by DAAB, consumed by LAAM — not reinvented per platform.

A second, pre-existing problem this design must NOT inherit: recall/search handlers trust scope from the request body (`handler/search.go:124-176` reads `project_id`/`cross_project_ids` from JSON body — the verified IDOR class). Session search must resolve scope server-side from the key.

## 2. Goals / Non-goals

**Goals**
- Vietnamese-correct lexical search over conversation messages, returning raw windowed snippets (no LLM summary).
- A stable, opaque MCP contract that LAAM codes against and that survives a later semantic upgrade without a consumer rewrite.
- Strict user + project scoping resolved server-side (no body-trust).

**Non-goals (deferred — see §10)**
- Semantic embedding of `thread_messages` + hybrid RRF ranking (v2; the contract is shaped so this is a non-breaking re-index).
- `pg_trgm` trigram / CJK fuzzy matching.
- Cross-user `monitoring` scope for LAAM (needs its own decision record + threat model).
- Indexing `response_blocks` rich content (index `content` only).

## 3. Established design decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **FTS-only v1**, semantic deferred | No embed-on-write pipeline exists for `thread_messages` (net-new table + Python worker + backfill). BA-033 showed lexical winning on the VN corpus (caveat: that was doc retrieval, not conversation — supports lexical-first, not "semantic useless"). |
| D2 | **`simple` config + `unaccent`** (NOT `english`) | `english` runs the Snowball stemmer + English stopword list over Vietnamese syllables → silent token drops. `simple` = no stemming; `unaccent` gives diacritic-insensitive recall ("Việt"≈"Viet"). |
| D3 | **Message-level results, thread-grouped** | A monitoring consumer needs the salient slice (message + window), attributed to its thread — not whole-conversation blobs. |
| D4 | **Opaque, server-owned ranking contract** | `score` is opaque (never expose `ts_rank` or an FTS-vs-semantic split). Adding hybrid RRF in v2 changes only ordering, not the schema → LAAM does not rewrite. |
| D5 | **Single-user v1, server-resolved scope** | `user_id` + `project_id` resolved from the API key; body never widens scope. Cross-user monitoring deferred. |
| D6 | **Generated `tsvector` column + GIN; index `content` only** | Conforms to the existing FTS pattern (migration 000068), switching `english`→`simple`+`unaccent`. `response_blocks` rich text gap documented. |

## 4. Current-state facts (verified)

- **Schema** (`db/migrations/000036_create_conversation_threads.up.sql`): `conversation_threads(id, user_id NOT NULL, project_id NOT NULL, name, is_archived, deleted_at, …)`; `thread_messages(id, thread_id FK, role CHECK in (user,assistant), content TEXT NOT NULL, response_blocks JSONB [000037], created_at)`. `content` is NOT NULL for both roles; `response_blocks` is the rich render (NULL for user msgs).
- **Indexing today:** `thread_messages` has B-tree `(thread_id, created_at)`, `(thread_id)`, partial `(ai_query_id)`, and GIN on `response_blocks`. **No FTS / trigram / embeddings on `content`.**
- **RBAC:** `internal/store/thread.go` scopes EVERY query by `user_id` (+ `project_id` + `deleted_at IS NULL`). Sessions are single-user-owned; no shared-project sessions. `GetByID(id, userID)`, `List(userID, projectID, …)`.
- **Identity:** `middleware/auth.go` — `APIKey.UserID` is `*string`. It is populated for **user-bound keys**: web-login session keys AND **consumer keys bound to a user** via `api_keys.user_id` (migration `000070`, role `agent` keys included — the shipped consumer-key-user-scope mechanism that `kg_recall` already relies on). It is nil only for **pure service/project keys**. So `kg_search_sessions` is usable via MCP for a user-bound consumer key (same identity model as `kg_recall`); a pure service key gets empty results. This is the intended single-user model — cross-user `monitoring` is the deferred piece, not "no MCP access".
- **FTS today:** `'english'` everywhere (`store/search.go:344,352` hardcode it for `ts_rank`/`ts_headline`). No `simple`/`vietnamese`/`unaccent` config anywhere.
- **Extensions (verified on `daab-postgres`):** `pg_trgm` 1.6 installed; **`unaccent` available but NOT installed**. `to_tsvector(regconfig,text)` is **IMMUTABLE** (the `'simple'`-explicit form); the 1-arg `to_tsvector(text)` is STABLE. `unaccent()` is STABLE → needs an IMMUTABLE wrapper to be used in a generated column / index.
- **Reuse:** `store/rrf.go` `ReciprocalRankFusion(lists,k=60,limit)` (only needed once a 2nd signal exists — not in v1). `kg_recall` envelope `{"results":[recallView{…, score float64}]}` to mirror.
- **MCP bridge:** tool schemas in `internal/bridge/schema.go`, routes in `internal/bridge/client.go`; adding a tool = +1 each + tests (`mem:bridge-tool-count-drift`).
- **Migration head:** `000071` → new pair is `000072`.

## 5. Architecture

```
kg_search_sessions (MCP tool)
  → bridge: schema.go + client.go route
  → handler.SessionSearchHandler.Search
       resolve user_id + project_id from key identity (NEVER body)
       require user_id present (else empty result)
  → store.ThreadMessageStore.SearchMessages(ctx, userID, projectID, query, limit, cursor, opts)
       JOIN thread_messages m → conversation_threads t
       WHERE t.user_id=$ AND t.project_id=$ AND t.deleted_at IS NULL
         AND m.search_vector @@ plainto_tsquery('simple', f_unaccent($q))
       ORDER BY ts_rank(...) DESC, m.created_at DESC, m.id
       ts_headline('simple', f_unaccent(content), plainto_tsquery('simple', f_unaccent($q))) on the page only
  → opaque view {results:[{thread_id, thread_name, message_id, role, snippet, created_at, score}], total_count, next_cursor}
```

Two units: a schema migration (FTS infra) and a read path (store method + handler + MCP tool). No write-path change to message creation (the generated column maintains itself).

## 6. Schema migration (`000072_thread_messages_fts.{up,down}.sql`)

```sql
-- up
CREATE EXTENSION IF NOT EXISTS unaccent;

-- IMMUTABLE wrapper: unaccent() is STABLE; pin the dictionary so the result is
-- deterministic and usable in a generated column / index expression.
CREATE OR REPLACE FUNCTION f_unaccent(text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT unaccent('unaccent', $1) $$;

ALTER TABLE thread_messages
  ADD COLUMN search_vector tsvector
  GENERATED ALWAYS AS (to_tsvector('simple', f_unaccent(content))) STORED;

CREATE INDEX idx_thread_messages_search_vector
  ON thread_messages USING GIN (search_vector);
```
```sql
-- down
DROP INDEX IF EXISTS idx_thread_messages_search_vector;
ALTER TABLE thread_messages DROP COLUMN IF EXISTS search_vector;
DROP FUNCTION IF EXISTS f_unaccent(text);
-- leave the unaccent extension installed (other features may adopt it); dropping is optional.
```

Notes:
- `content` is NOT NULL, so no `COALESCE` needed, but the wrapper is `STRICT` (NULL-safe) regardless.
- The generated column backfills existing rows automatically on `ADD COLUMN … STORED` (one table rewrite — acceptable at current scale; flag if the table is very large at deploy time).
- **No partial index on `deleted_at`/`is_archived`**: those live on `conversation_threads`, not `thread_messages`, so they can't be an index predicate here. The `deleted_at IS NULL` filter is applied via the JOIN at query time.
- **No trigram GIN** on `content` in v1 (deferred — write/storage cost; `pg_trgm` stays installed for v2).

## 7. Store — `ThreadMessageStore.SearchMessages`

New method in `internal/store/thread_message.go`:

```
type SessionSearchHit struct {
    ThreadID   string
    ThreadName string
    MessageID  string
    Role       string
    Snippet    string    // ts_headline windowed, 'simple' config
    CreatedAt  time.Time
    Score      float64   // ts_rank (opaque to callers)
}

type SessionSearchParams struct {
    UserID    string  // required; empty => no results
    ProjectID string  // required
    Query     string
    Limit     int     // default 8, cap 50 (mirror recall)
    Offset    int     // OFFSET-based pagination (see note); next_cursor encodes offset+limit
    Role      string  // optional filter: 'user' | 'assistant'
    // (date_from/date_to optional — include only if cheap; else defer)
}

func (s *ThreadMessageStore) SearchMessages(ctx, p SessionSearchParams) ([]SessionSearchHit, int, error)
```

Query shape:
- `JOIN conversation_threads t ON t.id = m.thread_id`
- `WHERE t.user_id = $userID AND t.project_id = $projectID AND t.deleted_at IS NULL AND m.search_vector @@ plainto_tsquery('simple', f_unaccent($query))` (+ optional `m.role = $role`).
- `ORDER BY ts_rank(m.search_vector, plainto_tsquery('simple', f_unaccent($query))) DESC, m.created_at DESC, m.id` — deterministic tie-break.
- `ts_headline('simple', f_unaccent(m.content), plainto_tsquery('simple', f_unaccent($query)), 'StartSel=<mark>,StopSel=</mark>,MaxFragments=2,MaxWords=18,MinWords=6')` — Run only on the returned page (re-tokenizes at query time — expensive on the full candidate set). **Two correctness traps:** (1) `to_tsvector` (column), `ts_headline`, and `plainto_tsquery` must ALL use `'simple'` — config mismatch yields silently empty highlights. (2) The document passed to `ts_headline` must be `f_unaccent(m.content)`, NOT raw `m.content`: the query lexemes are unaccented, so highlighting against the accented original would never match (silent empty snippet). **Consequence (documented v1 limitation):** the returned `snippet` is **diacritic-stripped** (e.g. "Viet Nam" not "Việt Nam"). This is acceptable for a locate-the-moment snippet; the full original `content` (with diacritics) remains retrievable via the existing message-fetch endpoints by `message_id`. Restoring accented snippets is a v2 follow-up (§10).
- `total_count` via a `COUNT(*)` over the same WHERE (a second GIN scan — acceptable at current scale; revisit if the table grows large).
- **Pagination = OFFSET-based** for v1 (`LIMIT $limit OFFSET $offset`). Rationale: keyset pagination on `ts_rank` is fragile — the score is a recomputed float, not unique or stable across pages. The full ordering (`ts_rank desc, created_at desc, id`) is deterministic within a snapshot, so OFFSET paging is stable for a given query. `next_cursor` encodes the next `offset`. Fine for the small, capped result sets expected; revisit only if deep pagination becomes a real need.
- Empty `UserID` → return `(nil, 0, nil)` immediately (no query).
- `archived` threads: **included** by default (history search spans archived); only `deleted_at` excludes. (If consumer wants to exclude archived, add an opt-in flag later.)

## 8. Handler + MCP tool

New handler (e.g. `internal/handler/session_search.go`) — or extend an existing thread handler — exposing the read endpoint and registered route. RBAC:
- Resolve `projectID` and `userID` from `middleware.GetDeveloperIdentity` (same pattern as `kg_recall`'s `Recall`). **Never** read project/user from the body.
- If no project context → empty results (mirror recall's soft-fail to `{results:[]}`).
- Body carries only: `query` (required), `limit`, `cursor`, `role` (optional). A body `project_id` is ignored/forbidden (no widening). The opaque `cursor` (echoed from a prior `next_cursor`) is decoded server-side into the internal `Offset`; callers never see a raw offset.
- Soft-fail to empty result set on store error (never 5xx), mirroring `Recall`.

Response view (mirror `recallView`, add thread attribution + pagination):
```
{ "results": [ { "thread_id", "thread_name", "message_id", "role", "snippet", "created_at", "score" } ],
  "total_count": N, "next_cursor": "…" }
```
`score` is documented as **opaque and non-comparable across versions**; callers must not re-rank on it.

**MCP tool `kg_search_sessions`** (`internal/bridge/schema.go` + `client.go`): input `{query (required), limit?, cursor?, role?}`; output the envelope above. Description states: searches the caller's own conversation history (user+project scoped), returns raw windowed snippets, no summarization. +1 schema, +1 route, + the test bumps from `mem:bridge-tool-count-drift`.

## 9. RBAC / isolation gate

- Scope is **server-resolved**; body cannot widen it (avoids the `handler/search.go` body-trust IDOR class).
- **Gate test** (new, extends the `recall_isolation_test` pattern): seed 2 users in 1 project + 2 projects; assert (a) user A's search never returns user B's messages, (b) no key returns another project's messages, (c) a non-user-bound key gets empty results, (d) soft-deleted threads are excluded. Must pass before LAAM consumes.

## 10. Deferred — written follow-up tickets

1. **Semantic + hybrid RRF (v2)** — net-new `thread_message_embeddings` table + Python embed-on-write + backfill; fuse with FTS via `rrf.go`. Additive under the opaque contract — LAAM does not rewrite. Validate against a conversation-corpus eval (BA-033 was doc retrieval, not conversation).
2. **`pg_trgm` trigram / CJK fuzzy** — add only if CJK content or fuzzy/partial-term recall becomes a stated need; trigram GIN has real write/storage cost.
3. **Cross-user `monitoring` scope** — an audited, project-bounded key capability letting LAAM search across users (default deny). NOT in the current ecosystem contract; needs its own decision record + threat model before implementation.
4. **`response_blocks` rich text** — v1 indexes `content` only; assistant chart/table/code block text is not searchable. Document the gap; revisit if needed.
5. **`archived`-thread filter flag** — if a consumer needs to exclude archived threads.
6. **Accented snippets** — v1 snippets are diacritic-stripped (ts_headline runs on `f_unaccent(content)` so highlighting matches the unaccented query). v2 could restore accented snippets (e.g. position-map the headline back onto the original, or compute the window in Go) if human-facing display needs it.

## 11. Test plan (TDD)

**Store (integration, `KG_TEST_DSN`/`KG_TEST_DATABASE_URL` → :5433):**
- VN diacritic-insensitive: query "viet" matches content "Việt" and vice-versa (proves `simple`+`unaccent`).
- `english`-stemming regression guard: a VN token that English stemming would drop is still matched.
- Rank ordering: higher term frequency ranks first; deterministic tie-break (`created_at` desc, `id`).
- `ts_headline` returns a non-empty `<mark>`ed snippet even for an **unaccented query against accented content** (query "viet" on content "Việt Nam" → snippet contains `<mark>` — proves the `f_unaccent` on both the document and the query, and `simple` config consistency). Asserts the snippet is non-empty (diacritic-stripped is expected).
- User isolation: user A's search excludes user B's messages.
- Project isolation: search excludes other projects' messages.
- Soft-deleted threads excluded; archived threads included.
- Empty `UserID` → empty result, no query error.
- Pagination: `cursor`/offset returns the next page without overlap or gaps (deterministic order).

**Handler (integration + unit):**
- Body `project_id` does NOT widen scope (server-resolved wins).
- No project context / store error → soft-fail `{results:[]}`, not 5xx.
- Non-user-bound key → empty results.

**MCP bridge:** schema present + routed; tool-count drift tests updated (`mem:bridge-tool-count-drift`).

## 12. Files touched (anticipated)

- `db/migrations/000072_thread_messages_fts.{up,down}.sql` — unaccent ext + `f_unaccent` + generated `search_vector` + GIN.
- `internal/store/thread_message.go` — `SearchMessages` + `SessionSearchHit`/`SessionSearchParams` (+ test).
- `internal/handler/session_search.go` (new) — handler + route registration (+ tests, incl. isolation gate test).
- `internal/bridge/schema.go` + `internal/bridge/client.go` — `kg_search_sessions` tool + route (+ schema/client/handler/integration test bumps).
- `internal/handler/session_search_isolation_integration_test.go` (new) — isolation gate test mirroring the existing `recall_isolation_integration_test.go` / `agent_context_isolation_integration_test.go` pattern.
