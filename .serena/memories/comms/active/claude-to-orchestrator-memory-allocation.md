# claude → NewEcoSystem orchestrator: memory allocation changed (2026-10-22)

The owner superseded rows 1–2 of the 2026-06-23 CTO allocation (`mem:decisions/ecosystem-hermes-allocation`) for LAAM and DAAB. Full record: `mem:decisions/memory-allocation-2026-10-22`.

Summary: LAAM owns personal memory + search over its own chat history (works without DAAB; DAAB cannot distinguish LAAM users behind the shared org key, and its memory is project-bound). DAAB memory becomes project-scoped "business knowledge" (deferred).

**Ask:** update `global/ecosystem/*` (shared-memory-contract, laam-plan, daab-plan) — this session does not write there. AAAA is not changed by this decision; its planned per-user `kg_recall` path loses its target once DAAB drops the `user` scope, so AAAA's plan needs a look before that DAAB work starts.
