# MR Sync — Plan 1: DAAB `derived-records` endpoint

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `POST /api/v1/projects/{projectId}/derived-records` able to store a Master Record with its provenance edges atomically, replacing stale edges on every upsert.

**Architecture:** Extend the existing handler to accept `provenance` + `links[]` + full content. Edges become REPLACE semantics: delete edges owned by this node, recreate from payload, all in the node-update transaction. Properties continue to merge.

**Tech Stack:** Go (stdlib `net/http`, `database/sql`), PostgreSQL 16, `go test -race`.

**Spec:** `docs/superpowers/specs/2026-07-20-aaaa-master-record-to-daab-design.md` (D2, D4, D7, D8, D9)

**Prerequisite:** This plan is a **blocker for Plans 2 and 3**. Nothing else starts until it lands. **Task 0 must be done first** — transactional node+edge writes are not wired in production today, so D2's atomicity guarantee does not currently exist.

## Global Constraints

- Repo: `ennam.kg.go` — **a nested git repo**. Use `git -C ennam.kg.go` or `cd` into it; the workspace root HEAD will not move.
- Node type stays `derived_record`. `subtype` for AAAA is **`aaaa_master_record`** (not `master_record` — collides with BA-031's node type at `config/config.yaml:635`).
- **Properties merge, edges replace** (spec D9; narrows IMP-010 BR-007).
- Idempotency key remains `(source_system, record_ref)`; `record_ref` format is `project:<aaaa_project_id>`.
- Summary blanking must be an explicit caller intent, never incidental (spec D8).
- Adding/changing a node-type field requires updating **all** config gates — including the `search:` block — or `/query` 500s.
- Run `make lint` and `make test` before each commit.

---

### Task 0: Wire transactional node+edge support (PREREQUISITE — atomicity does not exist today)

**Files:**
- Modify: `ennam.kg.go/cmd/kg-server/main.go:397-399` (wiring only — **no store signature changes**)
- Test: `ennam.kg.go/internal/service/inline_links_test.go` (extend)

**Why this task exists.** Verified in code — **do not skip it assuming atomicity already works**:

- `NodeService.hasTxSupport()` (`internal/service/node.go:297-299`) requires
  `txBeginner`, `nodeRepoTx`, **and** `edgeRepoTx` to be non-nil.
- Production wires only `service.WithEdgeRepository(edgeStore)`
  (`cmd/kg-server/main.go:397-399`). **`WithTxSupport` is never called outside
  tests** (`grep -rn "WithTxSupport" --include="*.go" . | grep -v _test.go`
  returns only its own definition).
- Therefore `hasTxSupport()` is **false in production**, and inline `Links` take
  the non-transactional fallback: node first, edges after, **no rollback**.
- The bare stores cannot satisfy the interfaces directly: `EdgeStore.CreateEdgeTx`
  takes `tx *sql.Tx` (`internal/store/edge.go:128`) while
  `service.EdgeRepositoryTx` declares `tx store.Tx`
  (`internal/service/node.go:45`), and Go requires an exact signature match.
- **But the adapters for exactly this already exist and are correct**:
  `store.TxNodeStore` (`internal/store/tx.go:42`, implements `TxBeginner` +
  `NodeRepositoryTx`) and `store.TxEdgeStore` (:70, implements
  `EdgeRepositoryTx`). Both take `Tx`, assert `*sqlTx`, and delegate to the bare
  store with the unwrapped `*sql.Tx`.
- **They are simply never instantiated.** `grep -rn "NewTxNodeStore" --include="*.go" .`
  matches only its own definition.

So this is a **wiring gap, not a refactor**. Do not change store signatures — the
adapter layer is already the intended design and works.

Spec D2 requires node+edges to be atomic. Without this task, Plan 1 ships the
exact failure D2 exists to prevent: a crash between node write and edge write
leaves new content with old provenance.

**Interfaces:**
- Consumes: existing `store.NewTxNodeStore(db, nodeStore)` and `store.NewTxEdgeStore(edgeStore)` (`internal/store/tx.go:49, :77`).
- Produces: `WithTxSupport(...)` wired at the composition root so `hasTxSupport()` is true in production.

- [ ] **Step 1: Write the failing test**

A behavioural test — the interface assertions would already pass for the adapters,
so they would prove nothing. What is broken is the *wiring*.

```go
func TestStoreNode_EdgeFailureRollsBackNode(t *testing.T) {
	// WHY: this is Task 0's entire point. Build the NodeService exactly as
	// cmd/kg-server/main.go does, then request a node with one valid link and one
	// pointing at a nonexistent target.
	//
	// Today the node survives with a partial edge set — hasTxSupport() is false, so
	// StoreNode falls back to node-then-edges with no rollback. Spec D2 requires
	// both to vanish.
	//
	// Assert: the request errors AND no derived_record row exists afterwards.
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/service/ -run TestStoreNode_EdgeFailureRollsBackNode -v`
Expected: FAIL — the node is still present after the failed edge write.

- [ ] **Step 3: Wire the existing adapters at the composition root**

**Do not change any store method signature.** `TxNodeStore`/`TxEdgeStore` already
take `Tx`, assert `*sqlTx`, and delegate with the unwrapped `*sql.Tx`. They were
simply never constructed.

`cmd/kg-server/main.go:397-399`:

```go
	txNodeStore := store.NewTxNodeStore(db, nodeStore)
	txEdgeStore := store.NewTxEdgeStore(edgeStore)

	nodeSvc := service.NewNodeService(nodeStore, appCfg,
		service.WithEdgeRepository(edgeStore),
		// Without this, hasTxSupport() is false and inline Links are written after
		// the node with no rollback (spec D2).
		service.WithTxSupport(txNodeStore, txNodeStore, txEdgeStore),
	)
```

`txNodeStore` is passed twice deliberately: it implements **both** `TxBeginner`
and `NodeRepositoryTx` (`internal/store/tx.go:41`).

- [ ] **Step 4: Run to verify it passes**

Run: `cd ennam.kg.go && go build ./... && go test ./internal/service/ ./internal/store/ -race`
Expected: the rollback test passes; nothing else regresses.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add cmd/kg-server/main.go internal/service/
git -C ennam.kg.go commit -m "fix(kg): wire TxNodeStore/TxEdgeStore — inline links had no rollback in production"
```

> **Note for the reviewer:** this fixes a latent bug affecting **every** caller
> that passes inline `Links`, not just `derived_record`. Worth flagging separately
> — it means past inline-link writes were never atomic.

---

### Task 1: Store — delete edges by source node

**Files:**
- Modify: `ennam.kg.go/internal/store/edge.go` (bare method) and `internal/store/tx.go` (adapter method)
- Test: `ennam.kg.go/internal/store/edge_delete_test.go` (create)

**Interfaces:**
- Consumes: the existing two-layer pattern — bare store takes `*sql.Tx`, the `TxEdgeStore` adapter takes `Tx` and delegates (`internal/store/tx.go:83-90`).
- Produces: **two** methods mirroring `CreateEdgeTx`/`TxEdgeStore.CreateEdgeTx`:
  `func (s *EdgeStore) DeleteEdgesBySourceTx(ctx context.Context, tx *sql.Tx, sourceID string, edgeTypes []string) (int64, error)` and
  `func (t *TxEdgeStore) DeleteEdgesBySourceTx(ctx context.Context, tx Tx, sourceID string, edgeTypes []string) (int64, error)` — deletes edges originating at `sourceID` whose `edge_type` is in `edgeTypes`; returns rows deleted. Empty `edgeTypes` deletes nothing (guard against accidental wipe).

- [ ] **Step 1: Write the failing test**

Mirror the setup used by `internal/store/edge_getprojectid_test.go` (same DB fixture + cleanup). Test cases:

```go
func TestDeleteEdgesBySourceTx(t *testing.T) {
	// Arrange: one derived_record node with 2 evidence edges + 1 derived_from edge,
	// plus a control edge from a DIFFERENT source that must survive.
	// Act: DeleteEdgesBySourceTx(ctx, tx, recordID, []string{"evidence", "derived_from"})
	// Assert: returns 3; the control edge still exists.
}

func TestDeleteEdgesBySourceTx_EmptyTypesDeletesNothing(t *testing.T) {
	// Guard: an empty edgeTypes slice must be a no-op, not "delete all".
	// Act: DeleteEdgesBySourceTx(ctx, tx, recordID, nil)
	// Assert: returns 0; all edges still present.
}

func TestDeleteEdgesBySourceTx_ScopedToSource(t *testing.T) {
	// Edges TARGETING recordID must not be deleted — only edges whose source is recordID.
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestDeleteEdgesBySourceTx -v`
Expected: FAIL — `DeleteEdgesBySourceTx` undefined.

- [ ] **Step 3: Implement**

```go
// DeleteEdgesBySourceTx removes edges originating at sourceID whose edge_type is in
// edgeTypes, inside the caller's transaction. Used for REPLACE-semantics provenance:
// a derived_record upsert carries its complete current edge set, so edges it no longer
// claims must not survive (spec D9 — otherwise the graph asserts the record is evidenced
// by documents it has since dropped).
//
// An empty edgeTypes is a deliberate no-op, never "delete everything".
func (s *EdgeStore) DeleteEdgesBySourceTx(
	ctx context.Context,
	tx *sql.Tx,
	sourceID string,
	edgeTypes []string,
) (int64, error) {
	if sourceID == "" || len(edgeTypes) == 0 {
		return 0, nil
	}

	placeholders := make([]string, len(edgeTypes))
	args := make([]interface{}, 0, len(edgeTypes)+1)
	args = append(args, sourceID)
	for i, t := range edgeTypes {
		placeholders[i] = fmt.Sprintf("$%d", i+2)
		args = append(args, t)
	}

	query := fmt.Sprintf(
		`DELETE FROM knowledge_edges WHERE source_id = $1 AND edge_type IN (%s)`,
		strings.Join(placeholders, ", "),
	)

	res, err := tx.ExecContext(ctx, query, args...)
	if err != nil {
		return 0, fmt.Errorf("delete edges by source: %w", err)
	}
	return res.RowsAffected()
}
```

And the adapter, mirroring `TxEdgeStore.CreateEdgeTx` exactly:

```go
// DeleteEdgesBySourceTx delegates to the bare store with the unwrapped *sql.Tx.
// The Tx must have been created by TxNodeStore.BeginTx.
func (t *TxEdgeStore) DeleteEdgesBySourceTx(
	ctx context.Context,
	tx Tx,
	sourceID string,
	edgeTypes []string,
) (int64, error) {
	stx, ok := tx.(*sqlTx)
	if !ok {
		return 0, fmt.Errorf("invalid transaction type: expected *sqlTx")
	}
	return t.es.DeleteEdgesBySourceTx(ctx, stx.SQLTx(), sourceID, edgeTypes)
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd ennam.kg.go && go test ./internal/store/ -run TestDeleteEdgesBySourceTx -race -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/store/edge.go internal/store/tx.go internal/store/edge_delete_test.go
git -C ennam.kg.go commit -m "feat(store): delete edges by source node for REPLACE-semantics provenance"
```

---

### Task 2: Config — schema changes for the record body

**Files:**
- Modify: `ennam.kg.go/config/config.yaml` (node type at :699, search block at :1461)
- Test: `ennam.kg.go/internal/config/types_test.go` (extend)

**Interfaces:**
- Produces: `derived_record` accepts `summary` up to 8000 chars, plus new fields `content` (full record body, **not** in `text_search`), `generated_at`, `sections_present`, `sections_stale`.

- [ ] **Step 1: Update the node-type schema**

In `config/config.yaml` under `derived_record.fields`, change `summary` max_length `2000` → `8000`, and add:

```yaml
      content:
        type: text
        max_length: 200000
        description: "Full record body as rendered by the source system. NOT indexed for search — retrieved once the anchor is found (spec D4)."
      generated_at:
        type: string
        max_length: 64
        description: "RFC3339 timestamp of the source-system build this content came from"
      sections_present:
        type: json
        description: "Section keys included in this sync"
      sections_stale:
        type: json
        description: "Section keys known to the source but NOT included (not COMPLETED at fetch time) — spec D10"
```

- [ ] **Step 2: Rewrite the node-type description (doc drift)**

The current description at `config/config.yaml:701` says *"Content lives in the source system"*. That becomes false. Replace with:

```yaml
    description: "A satellite-computed record about a Project/entity (e.g. AAA Master Record). KG holds anchor + summary + full non-indexed content + provenance edges. The source system remains the system of record for edits (IMP-010, revised by the 2026-07-20 MR sync design)."
```

- [ ] **Step 2b: Allow `document` as an `evidence` target (BLOCKING for Plan 3)**

The current whitelist (`config/config.yaml:1098-1103`) is:

```yaml
  - source: derived_record
    relationship: evidence
    targets: [document_chunk, document_ref, artifact]
```

**`document` is missing, and every other target is wrong for this data.** Verified
against the live DB and the sync path:

- AAAA cites at **document level** only — `MasterRecordSection.sourceDocIds` and
  `citations[].document_id`. It has no knowledge of DAAB's chunking.
- An AAAA document resolves to a **`document`** node
  (`draft_nodes.source_id` → `draft_nodes.knowledge_node_id`; confirmed in the
  live DB: `source_type='aaaa'` rows map to `node_type='document'`).
- Targeting `document_chunk` would mean linking **every chunk** of a cited
  document — a 50-page statement produces hundreds of edges each asserting
  "this section is evidenced by chunk #187", which AAAA never said. That
  fabricates chunk-level precision the source data does not have, and is exactly
  the unfalsifiable-claim failure mode this design set out to avoid.
- `document_ref` is BA-031's *extracted mention* of a document, not the document.
- `derived_from` has the same gap (`targets:` line at :1093) and needs `document`
  too if a section is ever attributed to a whole document.

Change to:

```yaml
  - source: derived_record
    relationship: evidence
    targets: [document, document_chunk, document_ref, artifact]
    description: "A derived record is directly evidenced by these documents/chunks/references. Document-level targets match satellite systems that cite whole documents (e.g. AAA Master Record); chunk-level targets remain available for finer-grained producers."
```

Add a config test asserting `document` is an allowed `evidence` target for
`derived_record`, so a future whitelist edit cannot silently break Plan 3's edge
resolution.

- [ ] **Step 3: Leave the search block unchanged — and assert it**

`config/config.yaml:1461` must remain `text_search: [title, summary]`. **`content` must NOT be added** — it is deliberately unindexed (spec D4).

Add to `internal/config/types_test.go`:

```go
func TestDerivedRecordContentIsNotSearchable(t *testing.T) {
	// WHY (spec D4): the full MR body is stored for retrieval-after-anchor, NOT as a
	// competing retrieval corpus. Indexing it would put AI-synthesized prose alongside
	// verbatim source chunks, letting a reranker treat a restatement as independent
	// corroboration of its own source.
	cfg := loadTestConfig(t)
	sc := cfg.Search["derived_record"]
	for _, f := range sc.TextSearch {
		if f == "content" {
			t.Fatal("derived_record.content must not be in text_search — see spec D4")
		}
	}
}
```

- [ ] **Step 4: Run config gate tests**

Run: `cd ennam.kg.go && go test ./internal/config/ -race`
Expected: PASS, including the new assertion.

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add config/config.yaml internal/config/types_test.go
git -C ennam.kg.go commit -m "feat(config): derived_record carries full non-indexed content; summary 2000->8000"
```

---

### Task 3: Handler — accept provenance + links, replace edges atomically

**Files:**
- Modify: `ennam.kg.go/internal/handler/derived_record.go`
- Test: `ennam.kg.go/internal/handler/derived_record_test.go` (extend)

**Interfaces:**
- Consumes: `DeleteEdgesBySourceTx` (Task 1); config fields (Task 2); existing `service.InlineLink` (`internal/service/node.go:51`) and `StoreNodeRequest.Links`.
- Produces: request body extended to
  `{title, subtype, source_system, record_ref, summary?, content?, generated_at?, sections_present?, sections_stale?, provenance?, links?[], blank_summary?}`.
  `links[]` entries: `{relationship, target_id}` restricted to `derived_from` / `evidence`.

- [ ] **Step 1: Write the failing tests**

```go
func TestUpsertDerivedRecord_CreatesNodeAndEdgesAtomically(t *testing.T) {
	// WHY: IMP-010 BR-004 deferred edges to separate kg_link calls, which has no
	// transaction boundary — a crash between them leaves new content with old
	// provenance, indistinguishable from correct data (spec D2).
	// POST with links[] -> 201, and the edges exist in the same commit.
}

func TestUpsertDerivedRecord_ReplacesStaleEdges(t *testing.T) {
	// WHY (spec D9): a rebuild can DROP a citation. Additive edges would make the graph
	// assert the record is evidenced by every document it ever cited.
	// Arrange: upsert #1 with evidence -> [chunkA, chunkB].
	// Act:     upsert #2 with evidence -> [chunkB] only.
	// Assert:  the chunkA edge is GONE (not merely that chunkB exists).
}

func TestUpsertDerivedRecord_EdgeFailureRollsBackNode(t *testing.T) {
	// A link to a nonexistent target must not leave a half-written node.
	// Assert: 4xx, and no derived_record row was created.
}

func TestUpsertDerivedRecord_OmittedSummaryDoesNotBlank(t *testing.T) {
	// WHY (spec D8): under pull, DAAB constructs the payload. A partial fetch that
	// omits summary must NOT silently wipe the stored one.
	// Arrange: existing node with summary "S".
	// Act:     upsert without summary.
	// Assert:  summary is still "S".
}

func TestUpsertDerivedRecord_ExplicitBlankSummaryClears(t *testing.T) {
	// Blanking stays possible, but only as a declared intent.
	// Act: upsert with blank_summary=true. Assert: summary == "".
}

func TestUpsertDerivedRecord_RejectsNonWhitelistedRelationship(t *testing.T) {
	// links[] with relationship "mentions" -> 400. Only derived_from/evidence allowed
	// (config.yaml:1091-1103).
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestUpsertDerivedRecord -v`
Expected: FAIL — new fields/behaviour absent.

- [ ] **Step 3: Extend the request struct**

Replace `upsertDerivedRecordRequest` (`derived_record.go:27-33`):

```go
type derivedRecordLink struct {
	Relationship string `json:"relationship"`
	TargetID     string `json:"target_id"`
}

type upsertDerivedRecordRequest struct {
	Title           string                 `json:"title"`
	Subtype         string                 `json:"subtype"`
	SourceSystem    string                 `json:"source_system"`
	RecordRef       string                 `json:"record_ref"`
	Summary         *string                `json:"summary,omitempty"`
	BlankSummary    bool                   `json:"blank_summary,omitempty"`
	Content         *string                `json:"content,omitempty"`
	GeneratedAt     string                 `json:"generated_at,omitempty"`
	SectionsPresent []string               `json:"sections_present,omitempty"`
	SectionsStale   []string               `json:"sections_stale,omitempty"`
	Provenance      map[string]interface{} `json:"provenance,omitempty"`
	Links           []derivedRecordLink    `json:"links,omitempty"`
}

// provenanceEdgeTypes are the only relationships a derived_record may own, per the
// edge whitelist (config.yaml:1091-1103). Also the exact set cleared on replace (D9).
var provenanceEdgeTypes = []string{"derived_from", "evidence"}
```

Note `Summary` is now `*string`: absent (nil) and "explicitly empty" become distinguishable — this is what makes D8 enforceable.

- [ ] **Step 4: Validate links before any write**

```go
for _, l := range req.Links {
	if l.TargetID == "" {
		errorResponse(w, http.StatusBadRequest, "link target_id required")
		return
	}
	if !slices.Contains(provenanceEdgeTypes, l.Relationship) {
		errorResponse(w, http.StatusBadRequest,
			"link relationship must be derived_from or evidence")
		return
	}
}
```

- [ ] **Step 5: Build properties without incidental blanking**

Replace the current unconditional `"summary": req.Summary` (`derived_record.go:60-62`):

```go
props := map[string]interface{}{
	"subtype":       req.Subtype,
	"source_system": req.SourceSystem,
	"record_ref":    req.RecordRef,
}
// Summary is set only when the caller said something about it. Under pull, DAAB
// builds this payload — a partial fetch must not wipe a good stored summary (D8).
if req.BlankSummary {
	props["summary"] = ""
} else if req.Summary != nil {
	props["summary"] = *req.Summary
}
if req.Content != nil {
	props["content"] = *req.Content
}
if req.GeneratedAt != "" {
	props["generated_at"] = req.GeneratedAt
}
if req.SectionsPresent != nil {
	props["sections_present"] = req.SectionsPresent
}
if req.SectionsStale != nil {
	props["sections_stale"] = req.SectionsStale
}
if req.Provenance != nil {
	props["provenance"] = req.Provenance
}
```

- [ ] **Step 6: Create path — pass links inline**

`StoreNodeRequest` supports `Links []InlineLink` (`internal/service/node.go:51`). **These are only atomic once Task 0 is done** — without it `hasTxSupport()` is false and edges are written after the node with no rollback. Map and pass them:

```go
links := make([]service.InlineLink, 0, len(req.Links))
for _, l := range req.Links {
	links = append(links, service.InlineLink{Relationship: l.Relationship, TargetID: l.TargetID})
}
resp, serr := h.nodeSvc.StoreNode(r.Context(), service.StoreNodeRequest{
	ProjectID:  projectID,
	NodeType:   "derived_record",
	Title:      req.Title,
	Properties: props,
	CreatedBy:  req.SourceSystem,
	Links:      links,
})
```

- [ ] **Step 7: Update path — replace edges in the update transaction**

`UpdateNodeRequest` has **no** `Links` field, and no production edge-delete existed before Task 1. Add a service method that performs update + edge replace in one transaction, and call it from `h.update`:

```go
// UpdateNodeWithProvenance applies a property update and REPLACES the node's
// provenance edges in a single transaction. Properties merge (IMP-010 BR-007);
// edges replace (spec D9) — otherwise a rebuild that drops a citation leaves the
// stale edge asserting provenance that is no longer true.
func (s *UpdateService) UpdateNodeWithProvenance(
	ctx context.Context,
	req UpdateNodeRequest,
	projectID string,
	links []InlineLink,
	edgeTypes []string,
) (*models.KnowledgeNode, error)
```

Implementation outline (mirror the transaction pattern at `internal/service/node.go:305-370`):
1. `tx, err := s.txBeginner.BeginTx(ctx)`; `defer tx.Rollback()`
2. Apply the node update within `tx`
3. `s.edgeRepoTx.DeleteEdgesBySourceTx(ctx, tx, req.ID, edgeTypes)`
4. For each link: `s.edgeRepoTx.CreateEdgeTx(ctx, tx, store.CreateEdgeParams{ProjectID: projectID, SourceID: req.ID, TargetID: l.TargetID, EdgeType: l.Relationship, ...})`
5. `tx.Commit()`

- [ ] **Step 8: Run tests**

Run: `cd ennam.kg.go && go test ./internal/handler/ ./internal/service/ -run "DerivedRecord|Provenance" -race -v`
Expected: PASS (all six handler tests).

- [ ] **Step 9: Commit**

```bash
git -C ennam.kg.go add internal/handler/derived_record.go internal/handler/derived_record_test.go internal/service/update.go
git -C ennam.kg.go commit -m "feat(daab): derived_record upsert writes provenance edges atomically with REPLACE semantics"
```

---

### Task 4: Revoke route (retraction support)

**Files:**
- Modify: `ennam.kg.go/internal/handler/derived_record.go`
- Test: `ennam.kg.go/internal/handler/derived_record_test.go` (extend)

**Interfaces:**
- Produces: `POST /api/v1/projects/{projectId}/derived-records/revoke` with body `{source_system, record_ref}` → marks the record revoked. Idempotent: revoking an already-revoked or absent record returns 200, not an error.

Plan 3 Task 3 calls this when AAAA reports a tombstone. **Revoke, do not hard-delete** — deleting destroys the audit trail of what LAAM previously answered from, which is exactly what a retraction needs to remain explicable.

- [ ] **Step 1: Write the failing tests**

```go
func TestRevokeDerivedRecord_MarksRevoked(t *testing.T) {
	// WHY (spec D7): AAAA cascades master-record sections on project delete. A pull
	// cursor observes ABSENCE, not deletion — without this route the record survives
	// in DAAB forever and LAAM keeps answering from a company that no longer exists.
	// Assert: the node is flagged revoked and no longer returned by normal retrieval.
}

func TestRevokeDerivedRecord_IsIdempotent(t *testing.T) {
	// The reconcile sweep (Plan 3 Task 4) re-runs over the same records; a second
	// revoke must be a 200 no-op, not an error that spams the sweep's logs.
}

func TestRevokeDerivedRecord_UnknownRecordIs200(t *testing.T) {
	// Revoking something DAAB never stored is not a failure.
}

func TestRevokeDerivedRecord_ScopedToProject(t *testing.T) {
	// A caller without access to projectId gets 404 — same leak-avoidance as Upsert
	// (derived_record.go:41-44), not 403.
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestRevokeDerivedRecord -v`
Expected: FAIL — route undefined.

- [ ] **Step 3: Register the route**

In `RegisterRoutes` (`derived_record.go:23`):

```go
	mux.HandleFunc("POST /api/v1/projects/{projectId}/derived-records/revoke", h.Revoke)
```

- [ ] **Step 4: Implement `Revoke`**

Mirror `Upsert`'s project-access guard, then look up by `(source_system, record_ref)` via `FindDerivedRecordByKey`. If absent → `200 {"revoked": false, "reason": "not_found"}`. If present → set a `revoked_at` property (and clear provenance edges using `DeleteEdgesBySourceTx` from Task 1, so a revoked record stops asserting provenance) → `200 {"revoked": true}`.

Add `revoked_at` to the `derived_record` schema in Task 2's config block:

```yaml
      revoked_at:
        type: string
        max_length: 64
        description: "RFC3339 timestamp when the source system reported this record deleted (spec D7). Present = revoked."
```

- [ ] **Step 5: Run tests**

Run: `cd ennam.kg.go && go test ./internal/handler/ -run TestRevokeDerivedRecord -race -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git -C ennam.kg.go add internal/handler/derived_record.go internal/handler/derived_record_test.go config/config.yaml
git -C ennam.kg.go commit -m "feat(daab): revoke route for retracted derived records"
```

---

### Task 5: Bridge tool schema + full verification

**Files:**
- Modify: `ennam.kg.go/internal/bridge/schema.go` (the `kg_upsert_derived_record` schema at :1659-1670)
- Test: `ennam.kg.go/internal/bridge/schema_test.go`

- [ ] **Step 1: Update the tool schema and description**

Add `content`, `generated_at`, `links`, `blank_summary` params. Replace the description — it currently says *"Returns node_id; attach provenance with kg_link"*, which is now wrong:

```
"Upsert a satellite-computed record (e.g. AAA Master Record) as a derived_record node. Idempotent by (source_system, record_ref). Provenance edges are supplied inline via links[] and REPLACE the node's existing derived_from/evidence edges — send the complete current set on every call."
```

- [ ] **Step 2: Update the schema test**

The bridge has a tool-count/schema invariant. Update `schema_test.go` for the new params and assert the description no longer instructs callers to use `kg_link` for provenance.

- [ ] **Step 3: Full verification**

Run:
```bash
cd ennam.kg.go && make lint && go test ./... -race 2>&1 | tail -25
```
Expected: lint clean; no new failures. Record any pre-existing failures explicitly rather than treating them as caused by this work.

- [ ] **Step 4: Manual smoke against a live DB**

With the stack up, upsert twice for the same `record_ref` — second call with one fewer evidence link — and confirm via `psql` that the dropped edge is gone and `node_id` is unchanged.

```bash
docker exec daab-postgres psql -U ennam_kg -d ennam_kg -tAc \
  "select edge_type, target_id from knowledge_edges where source_id = '<node_id>';"
```

- [ ] **Step 5: Commit**

```bash
git -C ennam.kg.go add internal/bridge/schema.go internal/bridge/schema_test.go
git -C ennam.kg.go commit -m "feat(bridge): kg_upsert_derived_record carries inline provenance links"
```

---

## Self-Review

**Spec coverage:** D2 (atomic node+edges) → Tasks **0**,1,3 — Task 0 is what makes atomicity real; it was assumed present in the first draft and is not. D4 (8000 summary + non-indexed content) → Task 2. D7 (revoke route, consumed by Plan 3's tombstone + reconcile paths) → Task 4. D8 (explicit blanking) → Task 3 steps 3,5. D9 (edge replace) → Tasks 1,3,4. D10 fields (`sections_present`/`sections_stale`) → Task 2, populated by Plan 3. Config doc-drift fix → Task 2 step 2. ✓

**Not covered here (by design):** D1/D3/D6/D11 are Plans 2-3. Phase 2 embedding is out of scope entirely.

**Placeholder scan:** Task 3 step 7 gives an implementation outline rather than full method code, because `UpdateService`'s internals were not read end-to-end while writing this plan — the transaction pattern to mirror is cited (`internal/service/node.go:305-370`). Treat that step as the one place requiring the implementer to read surrounding code first. Every other step carries complete code.

**Type consistency:** `derivedRecordLink{Relationship, TargetID}` → `service.InlineLink{Relationship, TargetID}` → `store.CreateEdgeParams{SourceID, TargetID, EdgeType}`. `provenanceEdgeTypes` is the single source for both validation and the replace scope. `Summary *string` used consistently for the absent-vs-empty distinction. ✓
