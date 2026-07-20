# MR Sync — Plan 3: DAAB sync worker, retraction, and UI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull each connected project's Master Record after its document sync, upsert it into DAAB with resolved provenance edges, revoke records for deleted projects, and surface per-track sync status in the dashboard.

**Architecture:** Extend the existing `handle_aaaa_sync` worker handler. After the document loop finishes, run an MR stage on the same connection credential: fetch → skip if `content_hash` unchanged → resolve `source_doc_ids`/`citations` to DAAB **`document`** nodes (via `draft_nodes.source_id`) → upsert with inline links. Tombstones revoke. One "Sync now" button drives both stages.

**Tech Stack:** Python 3.12 (asyncio, httpx), pytest, `uv`; Go (status fields); NextJS 16 + TanStack Query (dashboard).

**Spec:** `docs/superpowers/specs/2026-07-20-aaaa-master-record-to-daab-design.md` (D5, D6, D7, D9, D10, D11)

**Depends on:** **Plan 1** (endpoint accepting `links[]`/`content`, **and Task 2 Step 2b's `document` evidence-whitelist entry**) and **Plan 2** (AAAA read endpoint). Both must be merged first — this plan calls both.

> **Plan 1 is DONE (2026-07-20).** What it actually shipped, that this plan must
> match:
> - `POST /api/v1/projects/{id}/derived-records` accepts
>   `{title, subtype, source_system, record_ref, summary?, blank_summary?, content?, generated_at?, sections_present?, sections_stale?, provenance?, links?[]}`.
> - `POST .../derived-records/revoke` takes `{source_system, record_ref}`, sets
>   `revoked_at` **and** `Status = "deprecated"` so the record leaves normal
>   retrieval. Idempotent.
> - **A later upsert reactivates a revoked record** — it resets `Status` to
>   `"active"` and clears `revoked_at`. So the sweep in Task 4 must not revoke on
>   a failed request: the next successful sync would silently flip it back and
>   forth, churning version rows.
> - `links[]` accepts only `derived_from` / `evidence`, and **replaces** the
>   node's existing edges of those types. Send the complete set every time.
> - Edge targets are validated against the whitelist (tightened in Plan 1 commit
>   `2bd14c3` — previously only nil-gated). An invalid target now fails the upsert
>   rather than being silently skipped, so Task 2's drop-and-log must happen
>   **before** the call, not be relied on server-side.

> **Plan 2 is DONE (2026-07-20)** — `am-ai-agents` commits `5a5e476`..`f155a16`.
> Verified live against project `dc9f0cee-…` (Dasin), so this is the real payload
> shape, not a guess:
>
> ```
> GET /api/integrations/daab/master-records?projectId=<uuid>
> Authorization: Bearer <DaabSyncKey>
>
> record_ref:        "project:dc9f0cee-..."     ← use verbatim; never construct it
> title:             "Master Record — Dasin"    ← project name, not the id
> profile_status:    "COMPLETED"
> generated_at:      "2026-07-17T08:11:14.089Z"
> content_hash:      "052d3526..."              ← the D6 skip key
> sections_present:  [business, conflicts, financial, identity, legal,
>                     opportunity, ownership, risk, thesis]   (9)
> sections_stale:    []
> source_doc_ids:    9 entries
> citations:         []                          ← SEE WARNING BELOW
> summary:           7998 chars                  ← capped under 8000
> content:           34862 chars
> tombstone:         false
> ```
>
> Auth verified: no key → 401, wrong key → 401, and the request **reaches the
> route** (returns the route's own `{"error":"unauthorized"}`, not a proxy
> redirect) — the public-path entry works.

> ### ⚠ `citations` is empty in practice — plan around `source_doc_ids`
>
> Measured on the live dev DB: **0 of 9 sections have `citations`** (the column is
> `null`); only **6 of 9** have `sourceDocIds`. AAAA does not populate `citations`
> today.
>
> Consequences for this plan — none of these are bugs, but do not be surprised:
> - `resolve_links` (Task 2) reads both fields, but **`source_doc_ids` is the only
>   one that actually contributes**. Keep the `citations` branch (it is cheap and
>   AAAA may populate it later), just do not depend on it.
> - Sections with no `sourceDocIds` produce **no provenance edges at all**. Expect
>   roughly one edge per distinct source document — for Dasin that is ~9 edges for
>   9 sections, not one per section.
> - Do **not** treat "fewer edges than sections" as a failure in Task 3's logging;
>   log the dropped/unresolved ids, not the ratio.
> - The spec's D5 line "Source payload: `sourceDocIds` and `citations`" overstates
>   what exists. Corrected in the spec on 2026-07-20.

## Global Constraints

- Repos: `ennam.kg.python` (worker), `ennam.kg.go` (status fields), `ennam.kg.next` (UI). Each has its own `.git`.
- **Ordering is a correctness constraint, not a preference:** the MR stage runs **after** the document loop in the same run. MR `evidence` edges point at `document` nodes that only exist once their draft has been promoted; running MR first produces unresolvable refs (spec D6).
- **Never fail the whole sync because of MR.** Document sync succeeding must not be rolled back by an MR error — mirror the existing per-doc isolation style in `handle_aaaa_sync`.
- **No entity extraction over MR content** (spec D5). Link to existing nodes only; if a target does not resolve, drop-and-log.
- `subtype` is `aaaa_master_record`; `record_ref` comes verbatim from AAAA (`project:<id>`) — the worker must not construct it.
- Unresolvable evidence refs are **dropped and logged**, never fatal (spec D6).
- Run `uv run pytest` before each commit in `ennam.kg.python`.

---

### Task 1: AAAA client — fetch the master record

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/aaaa_sync_client.py`
- Test: `ennam.kg.python/tests/test_aaaa_master_record_client.py` (create)

**Interfaces:**
- Consumes: Plan 2's `GET /api/integrations/daab/master-records?projectId=`.
- Produces:
  - `@dataclass(frozen=True) MasterRecordPayload` with fields `record_ref, project_id, title, profile_status, generated_at, summary, content, sections_present, sections_stale, content_hash, source_doc_ids, citations`.
  - `fetch_master_record(aaaa_project_id, *, base_url, token) -> tuple[MasterRecordPayload | None, bool]` — returns `(payload, tombstone)`. `(None, False)` = nothing committed yet; `(None, True)` = project deleted.

- [ ] **Step 1: Write the failing test**

```python
import httpx, pytest
from ennam_kg.ingestion.aaaa_sync_client import fetch_master_record

def _client(handler):
    return httpx.MockTransport(handler)

@pytest.mark.asyncio
async def test_returns_payload_when_record_present(monkeypatch):
    body = {
        "master_record": {
            "record_ref": "project:p1", "project_id": "p1", "title": "MR — Dasin",
            "profile_status": "COMPLETED", "generated_at": "2026-07-20T09:00:00.000Z",
            "summary": "abstract", "content": "# full body",
            "sections_present": ["financial"], "sections_stale": ["risk"],
            "content_hash": "h1", "source_doc_ids": ["doc-1"],
            "citations": [{"section_key": "financial", "document_id": "doc-1"}],
        },
        "tombstone": False,
    }
    payload, tombstone = await fetch_master_record("p1", base_url="http://aaaa", token="t", _transport=_client(lambda r: httpx.Response(200, json=body)))
    assert tombstone is False
    assert payload.record_ref == "project:p1"
    assert payload.content_hash == "h1"
    assert payload.sections_stale == ["risk"]

@pytest.mark.asyncio
async def test_distinguishes_tombstone_from_not_built():
    # WHY (spec D7): both yield master_record=None, but only a tombstone may revoke
    # the record in DAAB. Conflating them would revoke every project that simply has
    # no master record yet.
    gone = {"master_record": None, "tombstone": True}
    p, t = await fetch_master_record("p1", base_url="http://aaaa", token="t", _transport=_client(lambda r: httpx.Response(200, json=gone)))
    assert (p, t) == (None, True)

    empty = {"master_record": None, "tombstone": False}
    p, t = await fetch_master_record("p1", base_url="http://aaaa", token="t", _transport=_client(lambda r: httpx.Response(200, json=empty)))
    assert (p, t) == (None, False)

@pytest.mark.asyncio
async def test_sends_bearer_token():
    seen = {}
    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"master_record": None, "tombstone": False})
    await fetch_master_record("p1", base_url="http://aaaa", token="s3cr3t", _transport=_client(handler))
    assert seen["auth"] == "Bearer s3cr3t"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_aaaa_master_record_client.py -v`
Expected: FAIL — `fetch_master_record` undefined.

- [ ] **Step 3: Implement**

Append to `aaaa_sync_client.py`, matching the module's existing standalone-async-function style:

```python
@dataclass(frozen=True)
class MasterRecordPayload:
    """One AAAA Master Record as served by the DAAB-facing read endpoint."""
    record_ref: str
    project_id: str
    title: str
    profile_status: str
    generated_at: str
    summary: str
    content: str
    sections_present: list[str]
    sections_stale: list[str]
    content_hash: str
    source_doc_ids: list[str]
    citations: list[dict[str, Any]]


async def fetch_master_record(
    aaaa_project_id: str,
    *,
    base_url: str,
    token: str,
    _transport: Any | None = None,
) -> tuple[MasterRecordPayload | None, bool]:
    """GET .../master-records — returns (payload, tombstone).

    (None, False) = no COMPLETED section yet. (None, True) = the project no longer
    exists at the source and its DAAB record must be revoked (spec D7). The two are
    NOT interchangeable.
    """
    base = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=_TIMEOUT, transport=_transport) as client:
        response = await client.get(
            f"{base}/api/integrations/daab/master-records",
            params={"projectId": aaaa_project_id},
            headers=_headers(token),
        )
    response.raise_for_status()
    body = response.json()

    if body.get("tombstone") is True:
        return None, True
    mr = body.get("master_record")
    if not mr:
        return None, False

    return (
        MasterRecordPayload(
            record_ref=mr["record_ref"],
            project_id=mr["project_id"],
            title=mr["title"],
            profile_status=mr.get("profile_status", ""),
            generated_at=mr.get("generated_at", ""),
            summary=mr.get("summary", ""),
            content=mr.get("content", ""),
            sections_present=list(mr.get("sections_present") or []),
            sections_stale=list(mr.get("sections_stale") or []),
            content_hash=mr["content_hash"],
            source_doc_ids=list(mr.get("source_doc_ids") or []),
            citations=list(mr.get("citations") or []),
        ),
        False,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_aaaa_master_record_client.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.python add src/ennam_kg/ingestion/aaaa_sync_client.py tests/test_aaaa_master_record_client.py
git -C ennam.kg.python commit -m "feat(ingestion): fetch AAAA master record with tombstone distinction"
```

---

### Task 2: Edge resolution — map AAAA document ids to DAAB `document` nodes

**Files:**
- Create: `ennam.kg.python/src/ennam_kg/ingestion/master_record_links.py`
- Test: `ennam.kg.python/tests/test_master_record_links.py`

**Interfaces:**
- Produces: `resolve_links(payload, *, lookup) -> tuple[list[dict], list[str]]` → `(links, dropped)`.
  `links` entries are `{"relationship": "evidence", "target_id": "<daab document node uuid>"}`.
  `lookup(aaaa_document_id) -> str | None` returns the DAAB **`document`** node id (injected, so this is testable without a DB).

**How the mapping actually works — verified against the live DB.** AAAA document
ids are **not** stored on graph nodes. The worker sets
`properties.aaaa_document_id` on the *draft* only, and that property does not
survive promotion (`select count(*) from knowledge_nodes where properties ?
'aaaa_document_id'` → **0**). The real chain is:

```
AAAA document_id
  → draft_nodes.source_id      (with source_type = 'aaaa')
  → draft_nodes.knowledge_node_id
  → knowledge_nodes            (node_type = 'document')
```

Confirmed live: `source_type='aaaa'` draft rows resolve to `node_type='document'`
nodes titled e.g. `BCTC KIEM TOAN 2024 DASIN-VND.pdf`.

**Target granularity is `document`, not `document_chunk`.** AAAA cites whole
documents; it knows nothing about DAAB's chunking. Linking to every chunk of a
cited document would assert chunk-level precision the source never provided.
This requires the whitelist change in **Plan 1 Task 2 Step 2b** — without it every
edge is rejected at Gate 1 and this task silently produces nothing.

- [ ] **Step 1: Write the failing test**

```python
from ennam_kg.ingestion.master_record_links import resolve_links

def _payload(**over):
    base = dict(source_doc_ids=["doc-1", "doc-2"],
                citations=[{"section_key": "financial", "document_id": "doc-1"}])
    base.update(over)
    return type("P", (), base)()

def test_builds_evidence_links_for_resolvable_documents():
    links, dropped = resolve_links(_payload(), lookup=lambda d: f"{d}-node" if d == "doc-1" else None)
    assert {"relationship": "evidence", "target_id": "doc-1-node"} in links
    assert dropped == ["doc-2"]

def test_works_with_citations_absent():
    # WHY: measured on the live dev DB — AAAA populates `citations` for 0 of 9
    # sections (the column is null); only source_doc_ids carries real data. This
    # must not degrade to zero links just because citations is missing.
    p = _payload(citations=None, source_doc_ids=["doc-1"])
    links, dropped = resolve_links(p, lookup=lambda d: "n1")
    assert links == [{"relationship": "evidence", "target_id": "n1"}]
    assert dropped == []

def test_section_with_no_source_docs_yields_no_links():
    # 3 of 9 live sections have no sourceDocIds at all. Producing no provenance
    # edge for them is correct behaviour, not a failure to report.
    p = _payload(citations=None, source_doc_ids=[])
    links, dropped = resolve_links(p, lookup=lambda d: "n1")
    assert links == []
    assert dropped == []

def test_unresolvable_refs_are_dropped_not_fatal():
    # WHY (spec D6): a document not yet ingested must not fail the whole upsert —
    # the MR is still worth storing, and the next run will resolve the missing ref.
    links, dropped = resolve_links(_payload(), lookup=lambda d: None)
    assert links == []
    assert sorted(dropped) == ["doc-1", "doc-2"]

def test_links_are_deduped():
    # The same document can back several sections; one edge per document, not one per citation.
    p = _payload(citations=[{"document_id": "doc-1"}, {"document_id": "doc-1"}], source_doc_ids=["doc-1"])
    links, _ = resolve_links(p, lookup=lambda d: "n1")
    assert len([l for l in links if l["target_id"] == "n1"]) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_master_record_links.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
"""Resolve an AAAA Master Record's document references to DAAB graph nodes.

Deliberately does NOT extract entities from the record text (spec D5): with BA-031
entity resolution in shadow mode, extracted entities would not merge with
document-extracted ones and would land as permanent duplicates. We link to nodes
that already exist instead.
"""
from typing import Any, Callable, Iterable


Targets are `document` nodes, resolved via
`draft_nodes.source_id -> draft_nodes.knowledge_node_id` (AAAA document ids are
NOT on graph nodes — see the Interfaces block above).

```python
def resolve_links(
    payload: Any,
    *,
    lookup: Callable[[str], str | None],
) -> tuple[list[dict[str, str]], list[str]]:
    doc_ids: list[str] = []
    for d in getattr(payload, "source_doc_ids", []) or []:
        if d and d not in doc_ids:
            doc_ids.append(d)
    for c in getattr(payload, "citations", []) or []:
        d = c.get("document_id") if isinstance(c, dict) else None
        if d and d not in doc_ids:
            doc_ids.append(d)

    links: list[dict[str, str]] = []
    dropped: list[str] = []
    seen: set[str] = set()

    for doc_id in doc_ids:
        node_id = lookup(doc_id)
        if not node_id:
            # Not ingested yet (or ingestion failed). Drop and let the caller log it —
            # a missing chunk must never sink the whole upsert (spec D6).
            dropped.append(doc_id)
            continue
        if node_id in seen:
            continue
        seen.add(node_id)
        links.append({"relationship": "evidence", "target_id": node_id})

    return links, dropped
```

The `lookup` implementation (built in Task 3) is a single query, not a traversal:

```sql
SELECT knowledge_node_id
FROM draft_nodes
WHERE source_type = 'aaaa' AND source_id = $1 AND knowledge_node_id IS NOT NULL
```
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd ennam.kg.python && uv run pytest tests/test_master_record_links.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.python add src/ennam_kg/ingestion/master_record_links.py tests/test_master_record_links.py
git -C ennam.kg.python commit -m "feat(ingestion): resolve master-record document refs to DAAB chunk nodes"
```

---

### Task 3: Worker stage — sync the master record after documents

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/worker.py` (`handle_aaaa_sync`, from :218)
- Modify: `ennam.kg.python/src/ennam_kg/ingestion/aaaa_sync_client.py` (upsert + revoke calls)
- Test: `ennam.kg.python/tests/test_aaaa_sync_master_record_stage.py`

**Interfaces:**
- Consumes: `fetch_master_record` (Task 1), `resolve_links` (Task 2), Plan 1's `POST /derived-records`.
- Produces: `upsert_derived_record(...)` and `revoke_derived_record(...)` client helpers; an MR stage that runs after the document loop.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_mr_stage_runs_after_documents():
    # WHY (spec D6): MR evidence edges target document_chunk nodes. If the MR stage
    # ran first, every evidence ref for a newly-synced document would be dropped.
    order = []
    ...  # stub list_documents -> order.append("docs"); fetch_master_record -> order.append("mr")
    assert order == ["docs", "mr"]

@pytest.mark.asyncio
async def test_skips_upsert_when_content_hash_unchanged():
    # WHY (spec D6/F2): every UPDATE writes a version row via trg_nodes_version, with
    # no change detection. ~10 rebuilds per 10 uploaded documents would archive ~10
    # near-identical versions and make node history unreadable.
    ...  # prior stored hash == payload.content_hash
    assert upsert_mock.call_count == 0

@pytest.mark.asyncio
async def test_upserts_when_hash_changed():
    ...
    assert upsert_mock.call_count == 1
    args = upsert_mock.call_args.kwargs
    assert args["subtype"] == "aaaa_master_record"
    assert args["record_ref"] == "project:p1"     # taken verbatim, never constructed
    assert args["source_system"] == "aaa"

@pytest.mark.asyncio
async def test_tombstone_revokes_and_skips_upsert():
    # spec D7
    ...
    assert revoke_mock.call_count == 1
    assert upsert_mock.call_count == 0

@pytest.mark.asyncio
async def test_mr_failure_does_not_fail_document_sync():
    # WHY: documents ingested successfully must not be lost because the MR stage
    # raised. Mirrors the per-doc isolation already used in this handler.
    fetch_mock.side_effect = RuntimeError("aaaa down")
    await handle_aaaa_sync(msg)          # must NOT raise
    assert documents_processed > 0

@pytest.mark.asyncio
async def test_dropped_evidence_refs_are_logged_not_fatal():
    # spec D6 — unresolved refs still allow the upsert to proceed.
    ...
    assert upsert_mock.call_count == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ennam.kg.python && uv run pytest tests/test_aaaa_sync_master_record_stage.py -v`
Expected: FAIL — no MR stage exists.

- [ ] **Step 3: Add the client helpers**

In `aaaa_sync_client.py`, mirroring `upsert_synced`:

```python
async def upsert_derived_record(
    *, base_url: str, api_key: str, project_id: str, body: dict[str, Any]
) -> str:
    """POST /api/v1/projects/{projectId}/derived-records — returns node_id.

    Idempotent by (source_system, record_ref). Provenance links in `body["links"]`
    REPLACE the node's existing derived_from/evidence edges, so the caller must send
    the complete current set every time (spec D9).
    """


async def revoke_derived_record(
    *, base_url: str, api_key: str, project_id: str, record_ref: str
) -> None:
    """Mark a derived_record revoked after its source project was deleted (spec D7)."""
```

> If Plan 1 did not add a revoke route, add it there rather than deleting the node here — a hard delete loses the audit trail of what LAAM previously answered from.

- [ ] **Step 4: Add the MR stage to `handle_aaaa_sync`**

After the document `while True:` loop completes, before the handler returns:

```python
        # ── Master Record stage (spec D6) ──────────────────────────────────────
        # Runs AFTER documents so evidence refs resolve against chunks ingested in
        # this same run. Wrapped whole: an MR failure must never discard a
        # successful document sync.
        try:
            payload, tombstone = await fetch_master_record(
                aaaa_project_id, base_url=conn.aaaa_base_url, token=conn.token
            )

            if tombstone:
                await aaaa_sync_client.revoke_derived_record(
                    base_url=settings.go_api_url,
                    api_key=settings.go_api_key,
                    project_id=daab_project_id,
                    record_ref=f"project:{aaaa_project_id}",
                )
                logger.info("aaaa_sync: master record revoked (source project deleted)")

            elif payload is None:
                logger.info("aaaa_sync: no committed master record yet")

            elif payload.content_hash == prior_mr_hash:
                # Skip entirely — an upsert here would write a no-op version row.
                logger.info("aaaa_sync: master record unchanged, skipped")

            else:
                links, dropped = resolve_links(payload, lookup=chunk_lookup)
                if dropped:
                    logger.warning(
                        "aaaa_sync: %d master-record refs unresolved, dropped: %s",
                        len(dropped), dropped,
                    )
                await aaaa_sync_client.upsert_derived_record(
                    base_url=settings.go_api_url,
                    api_key=settings.go_api_key,
                    project_id=daab_project_id,
                    body={
                        "title": payload.title,
                        "subtype": "aaaa_master_record",
                        "source_system": "aaa",
                        "record_ref": payload.record_ref,
                        "summary": payload.summary,
                        "content": payload.content,
                        "generated_at": payload.generated_at,
                        "sections_present": payload.sections_present,
                        "sections_stale": payload.sections_stale,
                        "links": links,
                    },
                )
                logger.info("aaaa_sync: master record upserted (%d links)", len(links))

        except Exception:
            logger.exception("aaaa_sync: master-record stage failed; documents kept")
```

Persist `payload.content_hash` after a successful upsert so the next run can compare — store it on the connection row (extend the existing `update_last_synced` call) rather than inventing a new table.

- [ ] **Step 5: Run tests**

Run: `cd ennam.kg.python && uv run pytest tests/test_aaaa_sync_master_record_stage.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.python add src/ennam_kg/ worker.py tests/
git -C ennam.kg.python commit -m "feat(worker): master-record sync stage with hash skip and tombstone revoke"
```

---

### Task 4: Reconcile sweep

**Files:**
- Modify: `ennam.kg.python/src/ennam_kg/worker.py`
- Test: `ennam.kg.python/tests/test_master_record_reconcile.py`

**Interfaces:**
- Produces: a periodic pass that revokes any `derived_record` whose `record_ref` no longer resolves at the source.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_reconcile_revokes_records_whose_source_is_gone():
    # WHY (spec D7): a per-project sync only runs for projects DAAB still knows about.
    # If a connection is removed, or a sync never runs again, a deleted company's
    # record would survive indefinitely and LAAM would keep answering from it.
    ...
    assert revoke_mock.call_args.kwargs["record_ref"] == "project:deleted-1"

@pytest.mark.asyncio
async def test_reconcile_leaves_live_records_alone():
    # A live project with no master record yet must NOT be revoked.
    ...
    assert revoke_mock.call_count == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.python && uv run pytest tests/test_master_record_reconcile.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

For each AAAA connection: list DAAB `derived_record` nodes with `source_system = "aaa"`, call the AAAA read endpoint per `record_ref`, and revoke on `tombstone: true`. Treat a network error as **unknown, not deleted** — never revoke on a failed request.

- [ ] **Step 4: Run tests + full suite**

Run: `cd ennam.kg.python && uv run pytest -q 2>&1 | tail -15`
Expected: new tests PASS; no new failures.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.python add src/ennam_kg/worker.py tests/test_master_record_reconcile.py
git -C ennam.kg.python commit -m "feat(worker): reconcile sweep revokes master records with deleted sources"
```

---

### Task 5: Per-track sync status (Go + dashboard)

**Files:**
- Modify: `ennam.kg.go/internal/handler/source_connection.go` (expose `last_mr_synced_at`, `mr_content_hash`)
- Modify: `ennam.kg.next/src/components/sources/aaaa-connect-dialog.tsx`
- Test: `ennam.kg.go/internal/handler/source_connection_test.go`

**Interfaces:**
- Produces: connection response carries `last_synced_at` (documents) **and** `last_mr_synced_at` (master record).

- [ ] **Step 1: Add the Go fields + migration**

Add `last_mr_synced_at` and `mr_content_hash` to the source-connection model/table and include them in the connection response. The worker (Task 3) writes both.

- [ ] **Step 2: Show two timestamps in the dialog**

In `aaaa-connect-dialog.tsx`, replace the single "Last synced" block with two:

```tsx
<div className="flex flex-col gap-1.5 rounded-md border border-[#2A2E45] bg-[#0D0F1A] px-3 py-2.5">
  <span className="text-[11px] font-semibold uppercase tracking-wider text-[#5C6080]">
    Documents
  </span>
  <span className="text-sm text-[#F0F0F8]">
    {connection.last_synced_at ? new Date(connection.last_synced_at).toLocaleString() : 'Never'}
  </span>
</div>
<div className="flex flex-col gap-1.5 rounded-md border border-[#2A2E45] bg-[#0D0F1A] px-3 py-2.5">
  <span className="text-[11px] font-semibold uppercase tracking-wider text-[#5C6080]">
    Master Record
  </span>
  <span className="text-sm text-[#F0F0F8]">
    {connection.last_mr_synced_at ? new Date(connection.last_mr_synced_at).toLocaleString() : 'Never'}
  </span>
</div>
```

**Keep the single "Sync now" button** (spec D11). Do not add a second trigger: two buttons would let a user run the MR stage before the document stage and violate the ordering constraint, and would invite half-synced state the user believes is complete.

- [ ] **Step 3: Verify**

Run: `cd ennam.kg.go && make test` and `cd ennam.kg.next && npm run build`
Expected: both clean.

- [ ] **Step 4: End-to-end smoke**

With the full stack up and an AAAA project connected:
1. Press **Sync now** → both timestamps update.
2. Press **Sync now** again with nothing changed → confirm the log says the master record was skipped, and confirm **no** new row in `knowledge_node_versions` for that node.
3. Rebuild the MR in AAAA, sync again → node updated, `node_id` unchanged, stale edges gone.

```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -tAc \
  "select count(*) from knowledge_node_versions v join knowledge_nodes n on n.id=v.node_id where n.node_type='derived_record';"
```

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/handler/source_connection.go internal/handler/source_connection_test.go migrations/
git -C ennam.kg.go commit -m "feat(connections): expose per-track master-record sync status"
git -C ennam.kg.next add src/components/sources/aaaa-connect-dialog.tsx
git -C ennam.kg.next commit -m "feat(sources): show per-track sync timestamps for AAAA connection"
```

---

## Self-Review

**Spec coverage:** D6 (ordering, hash skip, drop-and-log) → Tasks 1-3. D5 (link, never extract) → Task 2. D7 (tombstone + reconcile) → Tasks 1, 3, 4. D9 (send complete link set) → Task 3 Step 3 contract note. D10 (`sections_present`/`sections_stale` forwarded) → Task 3. D11 (one button, two timestamps) → Task 5. ✓

**Placeholder scan:** Task 3 Step 1 and Task 4 give test *names, intent, and assertions* with `...` for fixture wiring, because the existing `handle_aaaa_sync` test fixtures were not read while writing this plan. Task 4 Step 3 is an outline. These are the three steps requiring the implementer to read surrounding code first; every other step carries complete code. `chunk_lookup` (Task 3) is referenced but not implemented here — build it as the single `draft_nodes` query shown in Task 2, behind the `lookup` contract Task 2 already tests against.

**Type consistency:** `record_ref` flows verbatim AAAA → `MasterRecordPayload.record_ref` → upsert body → Plan 1's idempotency key. `content_hash` (AAAA response) → `payload.content_hash` → `mr_content_hash` (connection row). `links[]` entries `{relationship, target_id}` match Plan 1's `derivedRecordLink` exactly. `sections_present`/`sections_stale` match the Plan 1 config field names. ✓

**Resolved since first draft:** the revoke route is now **Plan 1 Task 4** — no longer an open item.

**Corrected after Plan 2 shipped:** `citations` is empty in practice (0/9 sections), so `source_doc_ids` is the sole provenance source; sections without it legitimately produce no edges. Tests added for both.

**Corrected after verifying against the live DB:** the first draft assumed `lookup` could find `document_chunk` nodes by AAAA document id. Both halves were wrong. (a) No graph node carries `aaaa_document_id` — the property is set on the draft and does not survive promotion (`properties ? 'aaaa_document_id'` matches 0 rows). The real path is `draft_nodes.source_id -> knowledge_node_id`. (b) The target is a **`document`** node, not chunks: AAAA cites whole documents, so chunk-level edges would fabricate precision the source never provided. This also forced a new prerequisite — **Plan 1 Task 2 Step 2b** must add `document` to the `evidence` whitelist, or every edge here is rejected at Gate 1 and this task silently produces nothing.
