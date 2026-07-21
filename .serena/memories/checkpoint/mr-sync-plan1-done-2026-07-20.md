# Checkpoint: AAAA Master Record → DAAB sync — 2026-07-20

## Status
- **Spec**: done — `docs/superpowers/specs/2026-07-20-aaaa-master-record-to-daab-design.md` (D1-D11, F1-F7)
- **Plan 1** (DAAB endpoint): ✅ **IMPLEMENTED & VERIFIED** in `ennam.kg.go`
- **Plan 2** (AAAA read endpoint): 🔄 in progress **in a separate chat session**
- **Plan 3** (worker + reconcile + UI): not started

## Design in one line
DAAB **pulls** the Master Record from AAAA (reusing `DaabSyncKey` + the existing
connection mapping), stores anchor + rich summary + full **non-indexed** content
+ provenance edges. No embedding in Phase 1. See `mem:decisions/...` n/a — the
spec file is authoritative.

## Plan 1 — what shipped (`ennam.kg.go`, commits `689dad5`..`e7c2709`)
- `WithTxSupport(txNodeStore, txNodeStore, txEdgeStore)` wired at `main.go:398-410`
- `DeleteEdgesBySourceTx` on both `EdgeStore` (edge.go:200) and `TxEdgeStore` (tx.go:95)
- config: `summary` 2000→8000, new non-indexed `content`, **`document` added to the `evidence` whitelist**
- handler: `links[]`, `provenance`, `blank_summary`, REPLACE edge semantics
- `POST .../derived-records/revoke`
- Verified: `go build ./...` clean, full `go test ./...` green. `make lint` NOT run (golangci-lint not installed locally).

## Bugs found by the work (worth knowing beyond this feature)
1. **Transactional node+edge writes were never wired in production.** `TxNodeStore`/`TxEdgeStore` adapters existed but were never constructed, so `hasTxSupport()` was false and every inline-`Links` write ran with **no rollback**. Affected all callers, not just `derived_record`. Fixed in `689dad5`.
2. **Inline-link edge whitelist was only nil-gated**, not actually validating target type. Fixed in `2bd14c3`.
3. AAAA document ids are **not** on graph nodes — `properties ? 'aaaa_document_id'` matches 0 rows. The real mapping is `draft_nodes.source_id -> knowledge_node_id`, resolving to a `document` node.
4. `MasterRecordSection` has **no `READY` status** — enum is `BUILDING/COMPLETED/FAILED/STALE`. Spec corrected to `COMPLETED`.

## Spec gaps closed by Plan 1's implementation (folded back in `187505d`)
- Revoke must also set `Status="deprecated"`, else the record keeps answering (`1e6d3af`).
- Upsert must **reactivate** a revoked record (`Status="active"`, clear `revoked_at`) — a project can legitimately return, and a tombstone served during an AAAA outage must not deprecate a company forever (`7599d70`).

## Governance — NOT yet done
IMP-010 and the ecosystem doc were annotated with **three reversals** (direction
push→pull; BR-003 content location; BR-004+BR-007 edge writing). All are marked
**pending PO sign-off**. IMP-010 was never ratified, so nothing approved was
overturned — but sign-off is still outstanding.

## Next steps
- Plan 2 finishing in the other session.
- Plan 3 afterwards. Its header now carries a summary of Plan 1's shipped contract — read that before starting; notably drop-and-log for unresolvable evidence refs must happen **client-side before** the upsert, since invalid targets now fail server-side.
- Optional: install `golangci-lint` and run `make lint` over Plan 1's changes.

## Risks
- Three unratified reversals awaiting PO sign-off.
- No RBAC on the DAAB write surface: `derived-records` is reachable by any API-key holder with project access **and** via the MCP bridge tool — it is not DAAB-internal.
