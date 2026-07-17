# Checkpoint: subagent-driven-development — DAAB↔AAAA Doc-Sync PlanA — FINAL (2026-07-16)

## Status: PLAN COMPLETE. Tasks 1-10 implemented+reviewed. Task 11 (E2E) — all 5 steps verified live.

## Summary
Full plan `docs/superpowers/plans/2026-07-15-daab-doc-sync-planA.md` is done. Real E2E run (human-in-loop with the user driving the UI, controller executing/inspecting via docker/DB) proved every guarantee the plan promised: sync, idempotency, per-doc isolation, no-persist — all confirmed with live data, not just unit tests.

## Task 11 E2E results (all verified with real data 2026-07-16)
1. Connect: ✅
2. Sync + content correctness (source_url backlink, real extracted text, canonical_document dedup rows): ✅
3. Idempotency: ✅ organically (9 real docs synced over multiple real Sync clicks, 0 duplicates) AND deliberately (content_hash mutated on one AAAA doc → only that doc re-ingested, same draft_node_id reused, 7 others untouched)
4. Isolation: ✅ deliberately (corrupted one doc's file_path → that doc failed with clear reason, sibling doc in same batch still ingested, batch completed, connection status returned to connected)
5. No-persist: ✅ `/tmp` in worker container has zero `aaaa_*` leftovers after the full session including several failure modes

## Real bugs found and fixed live (beyond the 2 found in the two whole-branch review passes)
1. `ennam.kg.go` `ca2c3d4` — `CreateWithCredential` never set Status=Connected (stuck at DB default `disconnected`).
2. `am-ai-agents` `src/proxy.ts` — `/api/integrations/daab/*` never added to `publicApiPaths`; Next 16 session-auth middleware 401'd every DAAB Bearer-token call before `daabTokenOk()` ever ran. Fixed live, user-confirmed before applying (security-boundary change).
3. `ennam.kg.python` `650f9ca` — temp download always named `aaaa_<id>.bin`; `extract_file_text` dispatches by extension → every real doc failed `UnsupportedFileTypeError`. Fixed: suffix now derived from `doc.file_name`.
4. `ennam.kg.go` `bae6375` — `canonical_document.go`'s hand-maintained `validCanonicalSourceTypes` map wasn't updated alongside migration 000077 (the CHECK-constraint fix) — ingestion pipeline dedup lookup 400'd "unknown source_type: aaaa" on every draft. Same bug CLASS as the whole-branch-review Critical, different layer (app-level map vs DB constraint) — three total instances of the same "'aaaa' not added everywhere it needed to be" bug across this plan.
5. DAAB Next: no UI wiring for the Go `/retry` endpoint (failed→pending) — worked around via direct API calls, not fixed, out of scope, not blocking.
6. Go `HandleArchiveProject` crashes for non-UUID caller identity (service-account email vs session UUID) — pre-existing, unrelated to this plan, found during ad-hoc cleanup. `mem:backlog/go-archive-project-invalid-actor-uuid-bug`.
7. Feature added per explicit user request (not a bug): `ConnectionStatusSyncing` existed but was never assigned — added Go Sync-sets-syncing (`ac6ae03`) + Python worker-resets-to-connected (`86615c5`) + Next.js conditional 3s polling while syncing (`105c04e`).

## Local-dev gotcha (environment, not code)
`aaaa_base_url` must be `http://host.docker.internal:3000` (not `localhost:3000`) since AAAA runs on host and DAAB worker runs in Docker. Recurring — connect-dialog has no env-aware default, had to fix in DB (`source_connections.config`) every time a new test connection was created.

## Final commit ranges (branch `task/implement_docs_sync`, all local, NOT pushed/PR'd)
- `other_projects/am-ai-agents`: e09e694..e869061 (Tasks 1-3 + proxy.ts session-auth exemption fix, confirmed committed)
- `ennam.kg.go`: 3714904..ac6ae03 (Tasks 4-7 + migration 000077 + status=connected fix + canonical_document map fix + syncing-status feature)
- `ennam.kg.python`: 52ef777..86615c5 (Tasks 8-9 + temp-extension fix + syncing-status feature)
- `ennam.kg.next`: 92774b9..105c04e (Task 10 + syncing-status polling)

## Follow-up notes for next session
- 25 DAAB test projects were archived (not deleted — API has no hard-delete) during cleanup, keeping only "C4K Staging", "Cảng Định An M&A", "Sala Food" active.
- Test data mutations (content_hash/file_path corruptions for step 3/4 verification) were fully restored to original values — confirmed via query, no lingering corruption in AAAA's `documents` table.

## Next steps
- Confirm the proxy.ts commit status (see above).
- If user wants to merge/PR: follow superpowers:finishing-a-development-branch (not yet invoked).
- Two backlog items open, both correctly out of scope for this plan: `mem:backlog/go-datasource-update-nil-bytea-bug`, `mem:backlog/go-archive-project-invalid-actor-uuid-bug`, plus `mem:backlog/aaaa-daab-sync-token-settings-ui` (UX enhancement, not a bug).

## Blockers / Risks
None blocking. Plan is functionally complete and proven end-to-end with real data.
