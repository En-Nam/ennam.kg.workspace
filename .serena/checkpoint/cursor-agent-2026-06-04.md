# Checkpoint: cursor-agent — 2026-06-04

## What was done
- Xóa 6 project (AM Agent, AM Project 1–3, AM Project Agent, Test KG 001) khỏi Postgres, giữ C4K (`a0000000-0000-0000-0000-000000000001`).
- Cascade thủ công: edges, embeddings, versions, nodes, benchmarks, data_sources (+ sync_jobs sau khi NULL `last_sync_job_id`), sessions, threads, v.v.
- `DEL ennam-kg:indexing` trên Redis.

## Files changed
- Không đổi code — chỉ thao tác DB/Redis.

## Current state
- `projects`: 1 row (C4K, active).
- `knowledge_nodes`: 649, `knowledge_edges`: 424 (C4K).

## Next steps
- Refresh dashboard — chỉ còn C4K.
- Nếu cần tạo project mới: UI Create Project.

## Blockers / Risks
- Không có API `DELETE /projects` — xóa DB trực tiếp; production cần endpoint hoặc script chuẩn hóa.
