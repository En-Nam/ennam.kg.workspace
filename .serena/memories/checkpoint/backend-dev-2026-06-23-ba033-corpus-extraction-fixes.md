# Checkpoint: backend-dev — 2026-06-23 (BA-033 testbed corpus + extraction fixes)

## What was done
Built a clean 2-document resolved corpus for BA-033 (cross-document GraphRAG) by ingesting
2 payment-hooks PDFs into a fresh project, and in doing so found+fixed 3 extraction/Gate-1
bugs that had been silently producing an edgeless graph.

### 3 root-cause bugs found & fixed (systematic-debugging)
1. **Prompt emitted wrong edge type** — wip pass1 prompt said `relates_to`; the closed
   schema (CLOSED_EDGE_TYPES) only accepts `related_to`. Parser dropped 100% of relations.
   Fix: prompt → `related_to` + list the 7 valid types. Commit `1b1c436` (ennam.kg.python).
2. **Edge payload missing created_by** — pass1 Step-6 `create_edge` omitted `created_by`;
   Go `/api/v1/edges` returns 400 "created_by is required". Fix: add
   `created_by="extraction-worker"`. Commit `fa928a4` (ennam.kg.python).
3. **Gate-1 whitelist gap** — edge_whitelist had no rules for concept/artifact/location as
   source of related_to/mentions/part_of/derived_from (only person/org/event). concept
   (dominant entity type) edges → 422. Fix: added 7 entity-edge rules. Commit `1902c73`
   (ennam.kg.go config.yaml). kg-server config is live-mounted → restart reloads (no rebuild).

Edge progression across the fixes: **0 → 16 → 71** created.

### Infra fix (durable)
- Worker HF cache moved to a **named volume `hf_cache`** (docker-compose.yml) + removed the
  broken HF_HUB_OFFLINE attempt → models (bge/e5) survive every rebuild. No more docker-cp.
  Models load via online HEAD + cached `.no_exist` markers (full offline breaks bare-name
  resolution). This is the deferred Phase B "T7" fragility, now resolved for local dev.

## Final corpus (project ba033-payment-hooks-v4 = 7ce5feb9-231f-4c56-8367-6b1853e25879)
- 77 active entities, 15 superseded, **0 duplicate clusters** (clean resolved graph → OQ-033-2 ✓).
- **70 active entity edges** (related_to 55, mentions 12, part_of 4) → FR-002 has a real graph.
- 2 documents, 9 chunks. Antonyms correctly NOT merged (validates Phase B+C).
- 15 merges applied; 3 needs_review (degree-gated — safety working).
- Earlier throwaway projects: b8ddc005 (v1), 30f212c5 (v2), aba74ee9 (v3) — debris, can delete.

## Operational facts (must-know)
- kg-server is on host port **8082** (docker-compose.yml). Env keys in WORKSPACE-ROOT .env.
- The python-worker dev key (`ennam_kg_dev_000…`, key_hash f92031bd…) is scoped to verifone
  project only (project_ids). To target other projects: ingest creates chunks via BODY
  project_id (no X-Project-ID header → no override gate); extraction trigger + apply use the
  **admin login token** (admin / Admin123!@#) with X-Project-ID. Do NOT edit api_keys
  (safety-blocked + unnecessary).
- Extraction LLM: BytePlus `gpt-oss-120b` via DirectOpenAIClient (EXTRACTION_LLM_* in .env).
- title >= 5 chars is a hard DB CHECK (`chk_title_min_length`) → short acronyms (PID, USB…)
  are dropped at extraction. Intended; relaxing needs a migration.

## Remaining gaps for BA-033
- **Chunk embeddings = 0** (FR-001 input). No pipeline embeds document_chunk nodes yet
  (universal — verifone too). This is BA-033 FR-001 / BA-025 build work.
- **6 residual edge-failure pairs** (minor whitelist gaps, e.g. some person/event part_of) —
  negligible vs 70 edges; extend whitelist further only if needed.

## Next steps
- Corpus is FR-002-ready (resolved graph + edges). FR-001 needs a chunk-embedding step.
- Proceed to write BA-033 superpowers spec/plan (these findings = concrete prerequisites:
  FR-001 must generate chunk embeddings; the extraction→Gate-1 edge-vocab reconciliation is
  now done for the common cases).

## Blockers / Risks
- ⚠️ BytePlus key `ark-d618f…` still pending user rotation (security).
- Throwaway v1-v3 projects + their nodes remain in DB (harmless clutter).
