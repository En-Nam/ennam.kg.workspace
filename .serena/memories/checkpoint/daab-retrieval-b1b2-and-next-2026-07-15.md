# Checkpoint: DAAB retrieval hardening (B1+B2) + next direction — 2026-07-15

## What was done (this session, all verified from source/DB)
- **Token-efficiency (gap #3)** shipped+live-verified on :8082: `kg_graph_retrieve` `include_snippet` (inline chunk content, null-discriminated, rune-safe cap, snippet=1181 chars live), `entity_neighbors.title`, `kg_get_neighbors` `view=slim` (763 vs 20855 B ~27x, 9 frozen fields, invalid→400). Bridge exposes them. Commits under `feat(retrieve)`/`feat(neighbors)`.
- **Sim-consumer harness run-3** (subagent as M&A analyst) → `other_projects/daab-sim-consumer/findings-rerun-2.md`. Source-verified corrections: consumer's "near-dup docs" REFUTED (77 docs=77 titles, dedup fine); "shared-entity empty" = IDF-ubiquity + entity fragmentation, substrate intact (1551 mentions edges). OCR confirmed = ROOT of entity fragmentation.
- **B1 entity-variant reduction** (plan `docs/superpowers/plans/2026-07-14-daab-entity-variant-reduction.md`): `fold_name()` (ASCII/tone-fold + abbrev-canon, stdlib difflib, no dep), fold grouping in `emit_hub_candidates_cli` + `classify_corpus_cli` (recall↑, still `decision=suggested`→LLM-gated), resolution re-run. Executed (subagent). **Result: investor 159 nodes → 105 merged, 54 heads.** NOT a bug — the 49 residual are LLM-confirmed 0.99 pairs routed to `needs_review` by **NFR-256 hub-safety degree gate** (`apply_suggestions.go`: hub degree≥threshold NEVER auto-merged, by design). Precision-safe floor MET.
- **B2 OCR figure fidelity** (plan `docs/superpowers/plans/2026-07-14-daab-ocr-figure-fidelity.md`): CPU preprocess (binarize/deskew/denoise, deskew searches on downscaled copy) before Tesseract; `_repair_confusables_near_units` (I→1,O→0,§ dropped) scoped to number+unit spans, wired into chunk-content + fields; residual-figure fallback (2nd detector + `unrecovered` fail-loud marker, NOT LLM-vision). Executed (subagent, another session). **Result: "33,6 ha" now retrievable (2 chunks, DB-verified); 0 unrecovered; 19 tests pass.** Model-vi swap was spike-gated (deferred if ONNX not readily available).

## Current state
- **All 5 top evidence-ranked retrieval gaps CLOSED**: dedup, stale-bridge, token-efficiency, entity(B1), OCR-figures(B2). Reading + relationship layers both solid.
- **Two adversarial 2-round debates** (CTO⇄consultant) drove the B spec; every plan self-reviewed + source-verified before/after (found real bugs each time: byte-vs-rune, concrete-handler-no-fake-seam, unaccent-in-SQL, dedup-blocks-reOCR, confusable impl/test mismatch).

## Operational items (NOT code — for admin/user)
1. **Investor entity still 54 heads** — collapse requires admin to approve the 49 `needs_review` pairs (verified same-entity, 0.99). Mechanism: `POST /api/v1/internal/resolution/apply-review-cleared` but pairs must be `review_cleared` first AND fuzzyHubMaxBlastCeiling may re-route the max-degree hub back — intentional NFR-256 gate; best done via dashboard admin. Do NOT force programmatically.
2. **Embedding service is 502** right now (graph_retrieve unavailable) — check embedding provider/container. Data already indexed is fine.
3. **SECURITY DEBT (recurring):** test/admin key `ennam_kg_15d6e8e7…` given this session for verification — revoke when done. (Prior test keys already revoked.)

## Next direction (decided: switch off retrieval-solo, evidence says diminishing returns)
- Decay/memory-of-record track = **DONE** (T1/T2/T3 all impl: migration 000071 last_recalled_at, `TouchRecalled`, `RecalledTouchWriter`, Pass-B effective-recency).
- **ROADMAP-AUTHORITATIVE NEXT = doc-sync Plan B (Supabase Storage Connector)** — CTO-greenlit (`mem:decisions/ecosystem-direction-cto-approved-2026-06-24`), the branch `task/implement_docs_sync`'s missing half. Plan A (OCR)=done; **Plan B=NOT STARTED** (no Supabase Storage fetch code). Plan: `docs/superpowers/plans/2026-06-26-doc-sync-planB-supabase-connector.md`, spec `docs/superpowers/specs/2026-06-26-daab-doc-sync-design.md`. Reuses `source_connections` (add source_type='supabase', credential_encrypted, supabase_synced_objects/etag, implement the existing 501 Sync route, StorageClient interface). Unblocks item #4 BA-033 Slice 2.
- **⚠️ Plan B is 3 weeks old — needs freshness-review before executing:** migration 000071 now TAKEN by decay → Plan B needs 000072; verify the 501 Sync route still exists, `extract_file_text` still returns 2-tuple (Plan B depends on it), source_connections state. THEN execute (Subagent-Driven).

## Next session should
1. Freshness-review doc-sync Plan B (fix stale migration number + verify Plan A dependencies intact).
2. Execute Plan B (Subagent-Driven).
3. (Optional) tell user to admin-approve the 49 needs_review + fix embedding 502.
