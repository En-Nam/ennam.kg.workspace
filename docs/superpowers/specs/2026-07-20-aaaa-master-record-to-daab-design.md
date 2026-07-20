# Design: AAAA Master Record → DAAB

**Date:** 2026-07-20
**Status:** Approved (design) — pending spec review
**Scope:** Cross-repo — `ennam.kg.go` (endpoint), `ennam.kg.python` (sync worker), `other_projects/am-ai-agents` (read endpoint).
**Supersedes two things in IMP-010** (`ennam.kg.requirements/documents/improvements/IMP-010-aaa-masterrecord-writeback-tools.md`):
1. **Transfer direction** — IMP-010 and `thiet-ke-ecosystem-laam-daab-aaa.md:104` specify AAA *pushing*; this design pulls. See [Direction reversal](#direction-reversal).
2. **Content location** — IMP-010 **BR-003** and FR-1 state the full record content stays in the source system ("KG is graph/index, not a duplicate document store"); this design stores it in DAAB. See [Content-location reversal](#content-location-reversal).

Both reversals require PO sign-off. IMP-010 is still "Proposed — pending PO sign-off", so neither overturns a ratified decision.

## Problem

AAAA synthesizes a **Master Record** (VN: "Hồ sơ tổng hợp") per project — a nine-section
analyst-grade report (Identity, Business, Financial, Ownership, Legal, Risk,
Opportunity, Conflicts, Sources) built by Claude from that project's analyzed
documents, costing ~60-90s per build. It is the single most decision-relevant
artifact AAAA produces.

It never reaches DAAB. AAAA has no sender; DAAB's `derived_record` receiving
surface is incomplete (below). Meanwhile **LAAM's only data path is LAAM → DAAB
via MCP** (`thiet-ke-ecosystem-laam-daab-aaa.md:101`, principle :33). AAAA
exposes no MCP server. So the synthesis is unreachable by the consumer that
needs it, and LAAM must re-derive conclusions from raw chunks — repeating work
AAAA already paid for, with different results.

## Findings that shape this design

Two independent architecture reviews (data-integrity lens, retrieval lens)
converged on these. All verified in code.

**F1 — The `derived_record` endpoint creates an orphan node. BLOCKING.**
`ennam.kg.go/internal/handler/derived_record.go:27-33` accepts only
`{title, subtype, source_system, record_ref, summary}`. It accepts **no
`provenance`** (though the schema field exists at `config/config.yaml:729-731`)
and calls `StoreNode` with **no `Links`** (:71-77). The whitelisted
`derived_record --derived_from-->` and `--evidence-->` edges
(`config/config.yaml:1091-1103`) have **no write path**. The MCP tool concedes
it: *"Returns node_id; attach provenance with kg_link"* (`bridge/schema.go:1662`).

Consequence: the ecosystem doc's central claim (:107) — *"traverse graph
MasterRecord → derived_from → entities → evidence → chunks → doc_id, không cần
tích hợp thêm"* — **does not work today**, because those edges are never
created. Any plan of the form "receiving side is done, just build the sender"
is wrong.

**F2 — Every update writes a version row unconditionally.**
`ennam.kg.go/internal/store/version.go:96-107`: the `trg_nodes_version` trigger
copies the OLD row into `knowledge_node_versions` on *every* UPDATE, with no
change detection. `derived_record.go:91-104` always calls `UpdateNode`.
Because AAAA auto-triggers a scoped MR rebuild after **every** document
analysis (`am-ai-agents/src/inngest/analyze-document.ts:1723`), 10 uploaded
documents produce ~10 rebuilds → 10 archived versions, most with an identical
summary. Node history stops being able to answer "when did this company's risk
profile actually change?" That is a provenance failure, not mere bloat.

**F3 — `record_ref = EntityProfile.id` is the wrong idempotency key.**
If a profile is rebuilt or recreated, `EntityProfile.id` changes while the
*company* did not — producing a second `derived_record` node while the old one
never dies.

**F4 — The 2000-char cap is a local schema choice, not a platform limit.**
`derived_record.summary` is capped at 2000 (`config/config.yaml`), but
`kg_remember` already accepts **8000** chars and hybrid-searches it
(`bridge/schema.go:1710`). Nine sections in 2000 chars ≈ 220 chars/section — a
table of contents, not a record.

**F5 — Vector-pool separation is already free.**
There is one embedding table, `knowledge_node_embeddings`, and `SemanticSearch`
already applies a `nodeTypes []string` filter as `AND n.node_type IN (...)`
(`internal/store/node_embedding.go:119-153`). Separation is a node-type choice,
not a new subsystem. (Relevant to Phase 2 only — Phase 1 does not embed.)

**F6 — `subtype: "master_record"` collides with an existing node type.**
DAAB already has a `master_record` **node type** from BA-031 meaning "a
resolved, de-duplicated entity record merging multiple extractions"
(`config/config.yaml:635-637`) — unrelated to AAAA's report. With
`filterable: [subtype]` (:1463) this is a live query-ambiguity bug.

**F7 — BA-031 entity resolution runs with auto-merge OFF** (`apply_mode=shadow`).
Entities extracted from MR content would **not** merge with document-extracted
ones; they would land as permanent duplicates.

## Decisions

### D1 — Direction: DAAB PULLS from AAAA

DAAB's sync worker fetches the Master Record from an AAAA read endpoint, on the
same connection it already uses for documents.

Rationale:
- **Credential already exists and points the right way.** AAAA issues
  `DaabSyncKey`; DAAB holds one (`2026-07-17-daab-sync-key-management-design.md`).
  Push would invert this — DAAB issuing a key to AAAA — creating a second
  credential lifecycle with its own rotation/revocation surface, weeks after the
  first was rebuilt properly.
- **Project mapping already exists.** Each DAAB connection stores
  `aaaa_base_url` + `aaaa_project_id` + `token`
  (`ennam.kg.go/internal/handler/source_connection.go:256`). Push would require
  AAAA to learn DAAB's project IDs — a second mapping, in the wrong place,
  guaranteed to drift.
- **Pull coalesces natively.** 10 incremental rebuilds → 1 fetch of the latest.
  Push fires 10 times unless AAAA builds debounce logic it does not have — and
  each push writes a version row (F2).
- **Push is the larger unbuilt surface.** AAAA has no sender, no MCP server, and
  no retry/backoff for a remote system. Pull extends a worker that already runs.

The counter-argument — "only AAAA knows which entities/documents each section
derived from, and that data builds the edges" — does not favour push. That data
lives in `MasterRecordSection.sourceDocIds` and `citations`
(`am-ai-agents/prisma/schema.prisma:956-957`); AAAA exposes it on the read
endpoint and pull carries the identical payload. Who initiates the transfer is
independent of who holds the knowledge.

The existing `POST /derived-records` endpoint is **not** wasted: DAAB's worker
calls it internally after fetching, exactly as the doc-sync worker does.

<a id="direction-reversal"></a>
**Direction reversal — recorded deliberately.** IMP-010 and
`thiet-ke-ecosystem-laam-daab-aaa.md:104` both specify AAA *pushing*
("ghi ngược"). This design reverses that. IMP-010 status is
**"Proposed — pending PO sign-off"** — never ratified — and when it was written
neither `DaabSyncKey` nor the connection-credential mechanism existed. Both
documents must be updated to reference this spec, or a future reader will find
code contradicting requirements.

### D2 — Fix the endpoint before building any sender

Extend `POST /api/v1/projects/{projectId}/derived-records` to accept
`provenance` and a `links[]` array, and create node + edges **atomically**
(`StoreNode` already supports inline `Links` in-transaction).

Requiring callers to make N follow-up `kg_link` calls is not a durable
contract: it is non-atomic (a crash between calls leaves a permanent orphan)
and it guarantees the edge whitelist stays decorative. Shipping a sender
against the endpoint as-is bakes in a provenance-free anchor.

This is a **prerequisite**, not a parallel workstream.

### D3 — Identity: `record_ref` keyed on the project, kind-prefixed

Format: `project:<aaaa_project_id>`.

- **Stable** across MR rebuild and `EntityProfile` recreation (fixes F3).
- **Already known to DAAB** — no new mapping.
- **Kind-prefixed** so `investor:<id>` can be added later without changing the
  idempotency key. `EntityProfile` is polymorphic over `projectId | investorId`
  (`schema.prisma:875-876`); Investor MRs are **out of scope for
  implementation** (DAAB has no investor mapping), but the key shape must not
  foreclose them. Changing an idempotency key after nodes exist is a migration;
  choosing its shape now is free.

`subtype` = **`aaaa_master_record`**, not `master_record` — resolves F6.

### D4 — Content: rich summary indexed, full content by reference. No embedding in Phase 1.

**Phase 1 (this spec):**
- Raise `derived_record.summary` cap **2000 → 8000** to match `kg_remember` (F4).
  Populate it with a genuine cross-section abstract, not a title.
- Store the **full Master Record content** in DAAB as a **non-indexed** field so
  LAAM gets 100% fidelity without depending on AAAA being reachable at query
  time.

<a id="content-location-reversal"></a>
**Content-location reversal — recorded deliberately.** IMP-010 **BR-003** states:
*"The full record content stays in the source system (AAA
`EntityProfile.masterRecord`); KG stores anchor + `summary` + `record_ref` +
provenance edges. KG is graph/index, not a duplicate document store."* The
shipped node-type description repeats it (`config/config.yaml:701`). **This
design overturns that rule.**

Why the rule's premise does not hold here:
- BR-003 guards against DAAB duplicating documents it already indexes. The
  Master Record is **not** such a document — it is a synthesis that exists in no
  chunk, produced by 60-90s of Claude reasoning over all of them.
- BR-003 implicitly assumes the consumer can reach the source system on demand.
  **LAAM cannot** — no MCP server on AAAA, and principle :33 forbids LAAM
  maintaining its own AAAA path. An unreachable source of truth is not a source
  of truth for the consumer.
- What remains valid in BR-003 is the *index* concern, and this design honours
  it: the content is stored **non-indexed**, and embedding is deferred and gated
  (Phase 2). DAAB does not become a competing retrieval corpus.

**Consequence to fix in the same change:** `config/config.yaml:701`'s description
("Content lives in the source system") becomes factually wrong once this ships.
Update it, or the schema will document the opposite of the behaviour.
- Expose it via a retrieval tool that returns the full record for a
  `derived_record` node. Discovery happens through the anchor (keyword `summary`
  + graph edges); the full body is fetched once the anchor is found.

**Phase 2 (deferred, gated on evidence):** chunk + embed MR sections as a
**distinct node type** sharing the existing vector table via the `nodeTypes`
filter (F5). Do **not** start here.

Rationale for deferring:
- "The summary is too lossy" argues for **access to full content**, which
  Phase 1 delivers — not necessarily for **putting it in the retrieval index**.
- Embedding is cheap to create and **permanently expensive to undo**: once
  derived restatements sit alongside primary chunks, a reranker sees two hits
  agreeing and scores confidence up, when in fact one was synthesized from the
  other. Same fact, counted twice, presented as independent corroboration.
- The MR is **Vietnamese**; source documents are mixed-language. Mixed-language
  embedding pools degrade retrieval independently of the duplication concern.
  Nobody has measured this here.

**Gate for Phase 2:** measured evidence that LAAM fails to locate Master Records
via anchor + summary + graph navigation. If Phase 2 proceeds, it MUST use a
distinct node type — **never** `document_chunk`, which is contractually the
verbatim-citation surface (`bridge/schema.go:1279`). MR prose is synthesized;
mixing it there would let a model quote AI-generated text as source material.

### D5 — Link, do not re-extract

**No entity extraction over MR content.** With BA-031 in shadow mode (F7),
MR-extracted entities become permanent duplicates: `kg_get_neighbors` on a
person returns half their edges, and degree/centrality metrics are silently
wrong. Worse, MR is *synthesized* — extraction would mint first-class entity
nodes for **inferred** entities present in no chunk: untraceable and
unfalsifiable.

Instead populate the already-whitelisted edges from AAAA's own data:
- `derived_record --derived_from--> [existing organization / person / project nodes]`
- `derived_record --evidence--> [document_chunk]`

Source payload: `MasterRecordSection.sourceDocIds` and `citations`
(`schema.prisma:956-957`).

### D6 — Sync: independent track, contentHash-coalesced

- **Independent of doc-sync.** MR changes when no document changed (manual
  rebuild; corrections — `am-ai-agents/src/app/api/projects/[id]/corrections/[cid]/route.ts:58`).
  Bundled into doc-sync, those changes stay invisible until someone happens to
  upload a document, and the anchor misrepresents the company for an unbounded
  period.
- **Cursor** on `EntityProfileRevision` / section `updatedAt`; fetch **latest
  only**, never replay per-rebuild.
- **Skip unchanged.** Compare `MasterRecordSection.contentHash`
  (`schema.prisma:958`, already exists) and **skip the upsert entirely** when
  unchanged. This is the direct fix for F2 — without it, every rebuild writes a
  no-op version row forever.
- **Ordering constraint.** `derived_record --evidence--> document_chunk` means
  MR sync must not outrun doc sync. Gate the upsert on referenced documents
  being ingested; drop-and-log unresolvable evidence refs rather than failing
  the whole upsert.
- **Committed sections only.** AAAA's read endpoint filters to
  `MasterRecordSection.status = READY` (`schema.prisma:954`,
  `EntityProfile.status` :878) so DAAB never ingests a half-built MR. See D10
  for what happens when only *some* sections are READY.

### D9 — Edges are REPLACE semantics, not additive

On every upsert, delete the `derived_from` / `evidence` edges owned by this
`derived_record` and recreate them from the incoming payload. The upsert
represents the complete current state of the record, mirroring the
"always sends the full record" principle already asserted in
`derived_record.go:60-62`.

**Failure mode this prevents.** The MR is rebuilt constantly, and a rebuild can
change *which documents feed which section* — a Legal section that cited
`contract-A.pdf` in build 1 may cite only `contract-B.pdf` in build 4. With
additive edges, after five rebuilds the graph asserts the MR is evidenced by
every document it has *ever* cited, including ones it has since dropped.
Provenance then answers "which documents back this conclusion?" with documents
that do not. That is a silent correctness failure — the graph looks richer while
being wrong, and nothing in the data reveals which edges are stale.

Implementation note: edge deletion must be scoped to edges whose source is this
node, and must run in the same transaction as the node update (D2), so a crash
cannot leave the record with new content and old provenance.

### D10 — Partially-READY Master Records: sync, but mark the gap

When some sections are `READY` and others are mid-rebuild, **sync the READY
sections and record which sections were absent or stale** in the node (e.g. a
`sections_present` / `sections_stale` property alongside `generated_at`).

Rejected alternative — all-or-nothing: a project whose MR rebuilds frequently
(which is the normal case, since every document analysis triggers a scoped
rebuild — `analyze-document.ts:1723`) could go indefinitely without ever
syncing.

Rejected alternative — sync silently: if the Risk section is missing and nothing
says so, LAAM answers "no risks identified" for a company whose risk analysis
was simply still building. A confident wrong answer is worse than an
acknowledged gap.

The rule: **incompleteness is acceptable; undisclosed incompleteness is not.**
Any consumer surface that renders the record must be able to tell that it is
partial.

### D11 — Trigger and UI: one button, two tracks

DAAB's existing AAAA connection dialog
(`ennam.kg.next/src/components/sources/aaaa-connect-dialog.tsx:118`) has a single
**"Sync now"** button hitting
`POST /api/v1/projects/{projectId}/connections/{connId}/sync`
(`source_connection.go:62`). **Extend that one action to cover both tracks. Do
not add a second button.**

- "Independent track" (D6) is a *backend cadence* property — MR needs its own
  cursor and change detection because it changes when documents do not. It is
  **not** a statement about user-facing actions.
- Two buttons would let a user run MR sync before doc sync, violating D6's
  ordering constraint and producing dangling evidence refs — a failure mode
  created purely by the UI.
- Two buttons also invite half-synced state: the user presses one, believes they
  synced, and does not notice the other is stale.

**UI change required:** replace the single "Last synced" line with **per-track
timestamps** (e.g. `Documents: 5 min ago` / `Master Record: 2 hours ago`). With
one combined timestamp, an MR-sync failure is invisible whenever doc sync
succeeded.

**Scheduled sync is the primary path**; the button is a manual override.

### D7 — Retraction

AAAA cascades MR sections on project delete (`onDelete: Cascade`,
`schema.prisma:969`). A pull cursor observes **absence, not deletion** — the
`derived_record` would survive in DAAB forever, and LAAM would keep answering
from a company profile that no longer exists in the system of record.

Neither push nor a naive pull cursor addresses this. Required: the AAAA read
endpoint reports **tombstones** (explicitly deleted/unavailable
`aaaa_project_id`s), and the worker runs a periodic **reconcile sweep** — any
`derived_record` whose `record_ref` no longer resolves at the source is marked
revoked/archived in DAAB.

This must ship with Phase 1, not after. An un-retractable stale company profile
is a correctness failure, not a cleanup task.

### D8 — Summary blanking must be explicit

`derived_record.go:60-62` blanks `summary` when omitted, justified by a comment
that "AAA always sends the full record on every upsert." **Under pull that
premise is false** — DAAB constructs the payload. If a fetch partially fails
and the worker upserts without a summary, it silently wipes the existing one.
Blanking must become an explicit caller intent, never an incidental side effect
of a partial fetch.

## Components

| Component | Change |
|---|---|
| `ennam.kg.go` — `internal/handler/derived_record.go` | Accept `provenance` + `links[]`; atomic node+edges; edge REPLACE semantics; explicit summary-blanking (D2, D8, D9) |
| `ennam.kg.next` — `components/sources/aaaa-connect-dialog.tsx` | Per-track last-synced timestamps; keep the single "Sync now" button (D11) |
| `ennam.kg.go` — `config/config.yaml` | `summary` max_length 2000 → 8000; full-content field (non-indexed); confirm edge whitelist (D4) |
| `ennam.kg.go` | Retrieval surface returning full MR content for a `derived_record` (D4) |
| `ennam.kg.python` — `ingestion/` | New independent MR sync track: cursor, contentHash skip, edge resolution, reconcile sweep (D6, D7) |
| `am-ai-agents` | `GET /api/integrations/daab/master-records` — `daabTokenOk` auth, `status=READY` only, returns sections + `sourceDocIds` + `citations` + `contentHash` + tombstones (D1, D6, D7) |
| `ennam.kg.go` — `config/config.yaml:701` | Rewrite the `derived_record` description — "Content lives in the source system" becomes false once D4 ships |
| `ennam.kg.requirements` / ecosystem doc | Update IMP-010 (direction **and** BR-003/FR-1 content-location) + ecosystem :104 to reference this spec's two reversals (D1, D4) |

## Out of scope

- **Investor Master Records** — key shape accommodates them (D3); implementation
  deferred until DAAB has an investor mapping.
- **Phase 2 embedding** — deferred and gated (D4).
- **AAAA-side MR generation logic** — AAAA-owned, unchanged by this design.

## Accepted risks

- **Staleness window.** Pull means MR lands on the next poll cycle, not
  instantly after rebuild. Accepted: MR takes 60-90s to build and is not
  real-time critical; doc-sync already has this property. Bounded by poll
  interval and made visible via a `generated_at` field.
- **Two unratified requirements are overturned** — transfer direction (D1) and
  content location (D4, IMP-010 BR-003). Mitigated by updating IMP-010, the
  ecosystem doc, and the `config.yaml:701` node description in the same change.
  Both need PO sign-off before implementation starts.
- **DAAB holds a second copy of the synthesis.** Accepted consequence of D4 and
  the direct cost of overturning BR-003: the copy can lag AAAA between syncs.
  Bounded by contentHash-driven sync (D6) and disclosed via `generated_at`;
  AAAA remains the system of record for edits.

## Testing

1. Endpoint creates node **and** edges atomically; a failure mid-write leaves no orphan.
2. Unchanged `contentHash` → **no** upsert, **no** new version row (F2 regression guard).
3. `record_ref` stable across an `EntityProfile` rebuild → updates the same node, never creates a second (F3 regression guard).
4. Partial fetch without summary does **not** blank an existing summary (D8).
5. Evidence refs to un-ingested documents are dropped-and-logged; the upsert still succeeds (D6).
6. AAAA endpoint returns only `status = READY` sections; a half-built MR is never served (D6).
7. Deleted project → tombstone → reconcile sweep marks the `derived_record` revoked; LAAM no longer retrieves it (D7).
8. `subtype = "aaaa_master_record"` does not collide with BA-031 `master_record` node-type queries (F6).
9. AAAA read endpoint rejects requests without a valid `DaabSyncKey` (fail closed).
10. **Edge replacement (D9):** upsert with a payload citing fewer documents than the previous build leaves *only* the new edges — dropped citations do not survive. Assert the stale edge is gone, not merely that the new one exists.
11. **Partial readiness (D10):** with some sections not READY, the node records which sections are absent/stale; a consumer can distinguish partial from complete.
12. **One trigger, ordered (D11):** a single sync run executes doc sync before MR sync; MR evidence refs resolve against documents ingested in the same run.
