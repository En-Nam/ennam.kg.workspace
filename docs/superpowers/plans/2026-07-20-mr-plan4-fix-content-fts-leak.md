# MR Sync — Plan 4: stop the Master Record body leaking into full-text search

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `derived_record`'s full record body genuinely non-indexed, as spec D4 requires, by renaming the property out of the shared search trigger's hardcoded key list.

**Architecture:** Rename the `derived_record` property `content` → `record_body` across config, the Go handler, the bridge tool schema, and the Python worker, plus a data migration for existing rows. The shared trigger is left untouched.

**Tech Stack:** Go, PostgreSQL 16 (plpgsql trigger, golang-migrate), Python 3.12, Vitest/pytest/go test.

**Spec:** `docs/superpowers/specs/2026-07-20-aaaa-master-record-to-daab-design.md` (D4)

**Severity:** Medium, not urgent. Vector embeddings are unaffected (0 rows for `derived_record`), so only full-text search is polluted. Nothing is corrupted; the fix is a rename.

## The defect, verified in the live DB

The DB trigger `update_search_vector()` hardcodes the property keys it indexes:

```sql
setweight(to_tsvector('english', COALESCE(NEW.properties->>'summary', '')), 'B') ||
setweight(to_tsvector('english', COALESCE(NEW.properties->>'content', '')), 'B') ||   -- ← this line
```

It never reads `config.yaml`, so `search.derived_record.text_search: [title, summary]`
has **no effect at this layer**. Proof against the live Dasin record:

| Check | Result |
|---|---|
| `'7666509593'` present in `properties->>'content'` | **true** |
| same string present in `properties->>'summary'` | **false** |
| `search_vector @@ plainto_tsquery('7666509593')` | **true** ← indexed |

**Why it matters (D4's stated purpose):** a full-text query can now return the
`derived_record` alongside the very `document_chunk`s its content was synthesized
from. A ranker sees two hits agreeing and scores confidence up, when one is an
AI-written restatement of the other — one derived source masquerading as
independent corroboration.

## Why rename instead of fixing the trigger

`content` is a **legitimate, searchable** field for three other node types — counts
from the live DB:

| Node type | Rows with `content` | Should be searchable? |
|---|---|---|
| `document_chunk` | 1511 | **Yes** |
| `document_section` | 406 | **Yes** |
| `architecture` | 317 | **Yes** |
| `derived_record` | 1 | **No** — spec D4 |

Dropping `content` from the shared trigger would silently break full-text search
for 1511+406+317 nodes to fix 1. Making the trigger node-type-aware adds branching
plpgsql to a write-path trigger shared by every node type. Renaming touches only
`derived_record` and cannot regress anything else.

**Name choice: `record_body`.** The trigger extracts *exact* keys
(`properties->>'body'`), so `record_body` does not collide with the `body` entry.
Verify this assumption in Task 1 Step 1 rather than trusting it.

## Global Constraints

- Repos: `ennam.kg.go`, `ennam.kg.python` — each has its own `.git`; commit with `git -C <repo>`.
- **Do not modify `update_search_vector()`.** Three other node types depend on `content` being indexed.
- The rename is a **breaking change to the `derived-records` API contract**. Only DAAB's own worker calls it today (verified: no `record_ref` values other than `project:*` exist), so no external consumer breaks — but the bridge tool schema must be updated in the same change or MCP callers will send a field that is silently dropped.
- Adding/renaming a node-type field requires updating **all** config gates.
- Run `make test` (Go) and `uv run pytest` (Python) before each commit.

---

### Task 1: Rename the field in config, with a test that checks the real layer

**Files:**
- Modify: `ennam.kg.go/config/config.yaml` (the `derived_record.fields` block)
- Modify: `ennam.kg.go/internal/config/types_test.go` (replace the wrong-layer test)

**Interfaces:**
- Produces: `derived_record` declares `record_body` (type `text`, max_length 200000) instead of `content`.

- [ ] **Step 1: Confirm the collision assumption before relying on it**

Run:
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -tAc \
  "select pg_get_functiondef(p.oid) from pg_trigger t
     join pg_class c on c.oid=t.tgrelid join pg_proc p on p.oid=t.tgfoid
    where c.relname='knowledge_nodes' and t.tgname='trg_nodes_search_vector';"
```
Expected: the body lists exact keys `title, name, description, definition, summary,
content, rationale, impact, domain, body, context`. Confirm **`record_body` is not
among them** and that extraction is `properties->>'<key>'` (exact), not a pattern
match. If the trigger differs from this, stop and re-plan — the rename target may
need to change.

- [ ] **Step 2: Replace the wrong-layer test**

`TestDerivedRecordContentIsNotSearchable` (added by Plan 1) asserts against
`config.yaml` and **passed while the defect was live** — it checked the wrong layer.
Delete it and put the real assertion where it belongs.

Keep a config-level guard, but make it about the rename rather than about search:

```go
func TestDerivedRecordUsesRecordBodyNotContent(t *testing.T) {
	// WHY: `content` is a key the shared search trigger (update_search_vector)
	// indexes unconditionally. The full MR body must not live under that key, or it
	// lands in search_vector regardless of the `search:` block — which is exactly
	// what happened before this rename. The authoritative check is the DB-level test
	// in Task 4; this one stops the field name drifting back.
	cfg := loadTestConfig(t)
	fields := cfg.NodeTypes["derived_record"].Fields
	if _, bad := fields["content"]; bad {
		t.Fatal("derived_record must not declare a `content` field — the search trigger indexes that key")
	}
	if _, ok := fields["record_body"]; !ok {
		t.Fatal("derived_record must declare `record_body`")
	}
}
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/config/ -run DerivedRecord -v`
Expected: FAIL — `content` is still declared, `record_body` is not.

- [ ] **Step 4: Rename in config**

In `config/config.yaml` under `derived_record.fields`, replace the `content` block:

```yaml
      record_body:
        type: text
        max_length: 200000
        description: "Full record body as rendered by the source system. Deliberately NOT named `content`: the shared search trigger indexes that key unconditionally, which would put AI-synthesized prose into full-text results alongside the verbatim chunks it was derived from (spec D4)."
```

Leave the `search:` block for `derived_record` as `text_search: [title, summary]` —
correct, but not what enforces this.

- [ ] **Step 5: Run to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/config/ -race`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.go add config/config.yaml internal/config/types_test.go
git -C ennam.kg.go commit -m "fix(config): derived_record body moves to record_body, out of the search trigger's key list"
```

---

### Task 2: Update the Go handler and bridge tool schema

**Files:**
- Modify: `ennam.kg.go/internal/handler/derived_record.go` (`props["content"]`, line ~104)
- Modify: `ennam.kg.go/internal/bridge/schema.go` (`kg_upsert_derived_record`, line ~1670)
- Modify: `ennam.kg.go/internal/handler/derived_record_test.go`

**Interfaces:**
- Consumes: `record_body` from Task 1.
- Produces: request field renamed `content` → `record_body` on both the REST body and the MCP tool schema.

- [ ] **Step 1: Write the failing test**

```go
func TestUpsertDerivedRecord_StoresBodyUnderRecordBody(t *testing.T) {
	// WHY: the property KEY is the whole fix. Storing the same text under `content`
	// puts it in search_vector via the shared trigger (see Task 4's DB test).
	// POST with record_body set.
	// Assert: the stored node has properties["record_body"] and NO properties["content"].
}

func TestUpsertDerivedRecord_RejectsLegacyContentField(t *testing.T) {
	// Fail loud rather than silently dropping it — a caller still sending `content`
	// would otherwise think the body was stored when it was not.
	// POST with a `content` field.
	// Assert: 400, and no node is created.
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run "RecordBody|LegacyContent" -v`
Expected: FAIL.

- [ ] **Step 3: Rename in the request struct and props map**

In `derived_record.go`, change the request field:

```go
	RecordBody      *string                `json:"record_body,omitempty"`
	// Legacy `content` is accepted only to reject it explicitly (see below).
	LegacyContent   *string                `json:"content,omitempty"`
```

Add validation alongside the existing link checks:

```go
	if req.LegacyContent != nil {
		errorResponse(w, http.StatusBadRequest,
			"field `content` was renamed to `record_body` — see spec D4")
		return
	}
```

And in the props map, replace `props["content"] = *req.Content` with:

```go
	if req.RecordBody != nil {
		props["record_body"] = *req.RecordBody
	}
```

- [ ] **Step 4: Update the bridge tool schema**

In `internal/bridge/schema.go`, in `kg_upsert_derived_record`'s `Properties`, replace
the `content` entry:

```go
			"record_body":  {Type: TypeString, Required: false, Description: "Full record body. Stored in the KG but deliberately NOT full-text indexed — do not send this as `content`, which the search trigger would index."},
```

The bridge invariant is `schemas == routes + localToolNames`; renaming a *parameter*
does not change any count, so no count assertion should need touching. If one fails,
that is a signal the invariant is keyed on something unexpected — investigate rather
than adjusting the number.

- [ ] **Step 5: Run to verify they pass**

Run: `cd ennam.kg.go && go test ./internal/handler/ ./internal/bridge/ -race`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.go add internal/handler/derived_record.go internal/handler/derived_record_test.go internal/bridge/schema.go
git -C ennam.kg.go commit -m "fix(daab): rename derived_record content -> record_body; reject the legacy field loudly"
```

---

### Task 3: Migrate the existing row

**Files:**
- Create: `ennam.kg.go/migrations/<timestamp>_derived_record_content_to_record_body.up.sql` and `.down.sql`

**Interfaces:**
- Produces: existing `derived_record` rows carry `record_body`; `content` removed; `search_vector` rebuilt.

- [ ] **Step 1: Write the migration**

`.up.sql`:
```sql
-- Move the MR body out of the `content` key, which update_search_vector() indexes
-- unconditionally, into `record_body`, which it does not (spec D4).
-- Scoped to derived_record: `content` stays valid and searchable for
-- document_chunk / document_section / architecture.
UPDATE knowledge_nodes
SET properties = (properties - 'content') || jsonb_build_object('record_body', properties->'content')
WHERE node_type = 'derived_record'
  AND properties ? 'content';
```

`.down.sql`:
```sql
UPDATE knowledge_nodes
SET properties = (properties - 'record_body') || jsonb_build_object('content', properties->'record_body')
WHERE node_type = 'derived_record'
  AND properties ? 'record_body';
```

- [ ] **Step 2: Confirm the UPDATE re-fires the trigger**

`trg_nodes_version` and `trg_nodes_search_vector` both fire on UPDATE, so
`search_vector` is recomputed from the new properties and the stale body drops out.
Note this migration therefore **writes one version row per migrated node** — with 1
row today that is immaterial; on a larger dataset it would be worth batching.

- [ ] **Step 3: Apply and verify**

Run: `cd ennam.kg.go && migrate -path migrations -database "$DB_URL" up` (or the repo's
`make migrate` equivalent).

Then verify the leak is closed with the exact probe that exposed it:
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -tAc "
select (properties ? 'content')                                  as still_has_content,
       (properties ? 'record_body')                              as has_record_body,
       (search_vector @@ plainto_tsquery('english','7666509593')) as still_searchable
from knowledge_nodes where node_type='derived_record';"
```
Expected: `f | t | f`. The third column flipping to `f` is the fix.

- [ ] **Step 4: Commit**

```bash
git -C ennam.kg.go add migrations/
git -C ennam.kg.go commit -m "fix(db): migrate derived_record content -> record_body and rebuild search_vector"
```

---

### Task 4: DB-level regression test — the assertion that would have caught this

**Files:**
- Create/modify: `ennam.kg.go/internal/store/derived_record_search_test.go`

**Interfaces:**
- Produces: a test that writes a `derived_record` against a real DB and asserts its body is absent from `search_vector`.

- [ ] **Step 1: Write the failing test**

This is the test whose absence let the defect ship. It must run against a **real
database**, because the trigger is the thing under test — a config assertion or a
mocked store cannot observe it.

```go
func TestDerivedRecordBodyIsNotInSearchVector(t *testing.T) {
	// WHY this test exists (Rule 9): Plan 1 shipped
	// TestDerivedRecordContentIsNotSearchable, which asserted against config.yaml and
	// PASSED while the body was fully indexed. The config `search:` block does not
	// drive update_search_vector() — the trigger's hardcoded key list does. Only a
	// real-DB assertion can tell the truth here.
	//
	// Arrange: insert a derived_record whose record_body contains a distinctive token
	//          ("zqx-sentinel-7666509593") that appears in NO other field.
	// Act:     query search_vector @@ plainto_tsquery(<token>).
	// Assert:  NO match.
	//
	// Control (must be in the same test, or a false pass is easy):
	//   the same token placed in `summary` MUST match — otherwise the query itself
	//   is broken and the negative assertion proves nothing.
}
```

- [ ] **Step 2: Run to verify the control and the assertion behave**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestDerivedRecordBodyIsNotInSearchVector -race -v`
Expected: PASS after Tasks 1-3. Temporarily rename the field back to `content` to
confirm the test **fails** — a negative assertion that never fails is worthless.

- [ ] **Step 3: Commit**

```bash
git -C ennam.kg.go add internal/store/derived_record_search_test.go
git -C ennam.kg.go commit -m "test(store): assert derived_record body stays out of search_vector at the DB layer"
```

---

### Task 5: Update the Python worker

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/worker.py:625`
- Modify: `ennam.kg.python/tests/test_aaaa_sync_master_record_stage.py`

**Interfaces:**
- Consumes: the renamed API field from Task 2.
- Produces: the worker sends `record_body`.

> `MasterRecordPayload.content` (the field parsed from **AAAA's** response) does
> **not** change — AAAA's contract still calls it `content`, and Plan 2 is already
> deployed. Only the key sent onward to DAAB changes. Renaming the dataclass field
> too would force an unnecessary change on the AAAA side.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_upsert_sends_record_body_not_content():
    # WHY: DAAB now rejects `content` with a 400 (Task 2). Sending the old key would
    # break every MR sync, and sending neither would silently store no body at all.
    ...
    body = upsert_mock.call_args.kwargs["body"]
    assert body["record_body"] == payload.content
    assert "content" not in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_aaaa_sync_master_record_stage.py -k record_body -v`
Expected: FAIL — the worker still sends `content`.

- [ ] **Step 3: Rename the outgoing key**

`worker.py:625`, inside the upsert body:

```python
                        # AAAA calls this field `content`; DAAB stores it as
                        # `record_body` so the shared search trigger does not index
                        # it (spec D4).
                        "record_body": payload.content,
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_aaaa_sync_master_record_stage.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.python add src/ennam_kg/worker.py tests/test_aaaa_sync_master_record_stage.py
git -C ennam.kg.python commit -m "fix(worker): send master-record body as record_body"
```

---

### Task 6: Rebuild, re-sync, and verify end to end

**Files:** none.

- [ ] **Step 1: Rebuild the affected services**

Run: `docker compose up -d --build kg-server kg-bridge worker indexer`
Expected: all healthy. (`dashboard` is untouched by this plan.)

- [ ] **Step 2: Force a re-sync**

The worker skips when `content_hash` is unchanged (D6), so the migrated record will
not be rewritten on its own. Clear the stored hash to force one pass:

```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -tAc \
  "update source_connections set mr_content_hash = null where source_type='aaaa';"
```
Then press **Sync now** in the dashboard.

- [ ] **Step 3: Verify the fix holds after a real write**

The migration (Task 3) proves the *existing* row is clean; this proves the *write
path* is too.

```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -tAc "
select (properties ? 'content')                                  as has_content,
       (properties ? 'record_body')                              as has_record_body,
       length(properties->>'record_body')                        as body_len,
       (search_vector @@ plainto_tsquery('english','7666509593')) as leaked
from knowledge_nodes where node_type='derived_record';"
```
Expected: `f | t | 34862 | f`.

- [ ] **Step 4: Confirm nothing else regressed**

```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -tAc "
select node_type, count(*) from knowledge_nodes
where properties ? 'content' group by 1 order by 2 desc;"
```
Expected: `document_chunk`, `document_section`, `architecture` unchanged
(1511 / 406 / 317); **no `derived_record` row**.

Also confirm the 9 `evidence` edges survived the migration:
```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -tAc "
select count(*) from knowledge_edges e
join knowledge_nodes n on n.id=e.source_id
where n.node_type='derived_record' and e.edge_type='evidence';"
```
Expected: 9.

---

## Self-Review

**Spec coverage:** D4's non-indexed requirement is the whole plan — Task 1 (config),
Task 2 (write path), Task 3 (existing data), Task 4 (regression at the right layer),
Task 5 (producer), Task 6 (end-to-end). ✓

**Placeholder scan:** Task 2 Step 1, Task 4 Step 1, and Task 5 Step 1 give test
intent, arrange/act/assert and the exact sentinel token rather than full bodies,
because the surrounding fixture style in those files was not read while writing this
plan. Every production-code step carries complete code. Task 4 explicitly requires
verifying the negative assertion can fail — a test that cannot fail is what caused
this defect.

**Type consistency:** `record_body` is the property key in config (Task 1), the Go
request field `RecordBody` / props key (Task 2), the migration's jsonb key (Task 3),
and the worker's outgoing body key (Task 5). `MasterRecordPayload.content`
deliberately keeps its name — it mirrors **AAAA's** field, which is unchanged. ✓

**Known risk:** the rename is a breaking API change. Mitigated by rejecting the legacy
`content` field with a 400 rather than ignoring it (Task 2 Step 3), so any missed
caller fails loudly instead of silently storing nothing. Verified today that DAAB's
worker is the only caller.
