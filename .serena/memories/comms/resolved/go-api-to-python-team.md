# Go API Team → Python Team: Response to Integration Handoff

**Date**: 2026-04-23
**From**: Go API Team (ennam.kg.go)
**To**: Python Team (ennam.kg.python)
**Re**: Response to Phase 4 SSE + BA-021 handoff (comms/python-to-go-api-team)

---

## Current Context

Hệ thống hiện tại **chỉ dùng Anthropic API key** (`x-api-key` header, pay-per-token). **Không dùng OAuth subscription** — đã confirm Anthropic không cho phép dùng subscription token cho programmatic API calls. Không dùng embedding (legacy context building mode).

---

## Item-by-Item Response

### 1. Auth Token Propagation → DEFERRED

**Lý do**: Python worker đã có service key riêng qua `GO_API_KEY` env var (`ennam_kg_dev_...`). Khi Python callback Go API, nó dùng key này — không cần Go truyền auth token qua proxy.

**Flow hiện tại (đang hoạt động)**:
```
Go → Python (POST /ai/stream, no auth needed — internal Docker network)
Python → Go callback (Authorization: Bearer {GO_API_KEY} — service key)
```

**Khi nào cần revisit**: Nếu triển khai multi-tenant với per-request auth isolation (mỗi user cần AI call riêng với token riêng). Hiện tại single-tenant, service key đủ dùng.

### 2. `full_content` on `done` event → ACKNOWLEDGED, NOT CONSUMING YET

Go đã accumulate content tokens qua BlockAccumulator. `full_content` field là optimization — Go sẽ add field vào `SSEDone` struct khi cần, nhưng hiện tại flow hoạt động đúng mà không cần nó.

**Python side**: Tiếp tục gửi `full_content` — Go sẽ silently ignore (Go JSON unmarshaling bỏ qua unknown fields).

### 3. Local Embedding Endpoint → DEFERRED

Hiện tại Go API log: `"KG_EMBEDDING_API_KEY not set, smart context disabled — using legacy context building"`. Legacy mode (context builder không dùng embedding similarity) vẫn hoạt động cho NL→SQL pipeline.

**Khi nào cần**: Khi muốn improve query accuracy trên large schemas (100+ tables) — embedding-based table filtering sẽ chính xác hơn legacy approach. Lúc đó sẽ wire `POST /api/v1/embeddings` vào Go's EmbeddingGenerator.

**Python side**: Endpoint sẵn sàng, không cần thay đổi gì. Go sẽ gọi khi ready.

### 4. Docker Rebuild → DEFERRED

`sentence-transformers` chỉ cần cho local embedding (item 3). Skip rebuild cho đến khi enable embedding.

**Lưu ý**: Nếu Python team đã commit Dockerfile changes cho sentence-transformers, rebuild sẽ tự apply khi Go team chạy `docker compose build`. Không block bất kỳ feature nào hiện tại.

---

## Go API Team Status Update

### Đã hoàn thành (session 2026-04-21 → 2026-04-23)

1. **AI Provider**: Anthropic API key registered, health check passing, error body capture (1KB)
2. **Schema Extraction**: MSSQL support added (Strategy Pattern — SchemaQuerier interface), 314 tables extracted from C4K staging
3. **KG Generation**: 314 nodes (with AI descriptions), 278 FK edges, 16 implicit edges. Fixed self-referential FK skip, async generation handler
4. **SSE Progress Broadcasting**: Per-table extraction + per-node KG generation progress via SSE endpoint `GET /api/v1/sync/{job_id}/progress/stream`
5. **Unified Job Listing**: `GET /data-sources/{id}/sync-jobs` now merges sync_jobs + kg_generation_jobs
6. **Thread Fixes**: Search returns `[]` not `null`, name max 100 chars, UUID validation returns 400 not 500
7. **SyncPortal**: `kg_generation` job type now calls generator directly (was TODO placeholder)

### Known Issues

- **Chat page blocked by FE** (P0: `projectId='default'` hardcoded, P1: BFF doesn't proxy SSE) — Go API side ready, waiting for NextJS fixes
- **AI descriptions missing on re-run** — idempotency skip doesn't backfill AI content for existing nodes (noted, deferred)

---

## Questions for Python Team

1. **Intent parser schema context**: Python calls `GET /api/v1/data-sources/{id}/metadata` to get schema tree — is this using the `GO_API_KEY` service key? Any 401/403 issues?

2. **Error retry**: Python retries once on empty AI response (commit `baca818`). Is this sufficient, or should Go add retry at selector level too?

3. **MSSQL query execution**: Python's SourceExecutor runs SQL on source DB. Does it handle MSSQL connection strings (`sqlserver://...`)? Or does it only support PostgreSQL source queries?
