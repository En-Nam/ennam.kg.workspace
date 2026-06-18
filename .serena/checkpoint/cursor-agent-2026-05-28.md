# Checkpoint: cursor-agent — 2026-05-28 (bổ sung)

## What was done
- Sửa `KGClient.get_neighbors`: chuẩn hóa response Go `{node_id, neighbors}` → `FlatResponse` (fix Pydantic validation trong Deep chat).
- Sửa `search_kg_semantic`: embedding qua HTTP `POST /api/v1/embeddings` thay vì load HF in-process (fix `Permission denied: /home/ennam` trong container).
- Thêm `embedding_service_url` trong config; `EMBEDDING_SERVICE_URL` + `HF_HOME` cho **indexer** và **worker** trong docker-compose.
- Cập nhật system prompt (deep tier): hướng dẫn lấy đủ mục 7.2 CRITICAL `#1–#10`, không dừng ở section "Rủi ro" mục 1.
- Test: `tests/kg_client/test_neighbors_normalize.py` (1 passed).

## Files changed
- `ennam.kg.python/src/ennam_kg/kg_client/client.py`
- `ennam.kg.python/src/ennam_kg/config.py`
- `ennam.kg.python/src/ennam_kg/agentic/tools.py`
- `ennam.kg.python/src/ennam_kg/agentic/prompts.py`
- `ennam.kg.python/tests/kg_client/test_neighbors_normalize.py`
- `docker-compose.yml`

## Current state
- Graph/document tree + 59 sections đã có trên hub `06a4715c-c18e-4384-8754-e62a569be890`.
- Chat Deep trước đó: 2 tool fail + agent tổng hợp sai (5 nhóm + #11–#19 thay vì 10 CRITICAL).
- Code fix xong; cần **recreate indexer** để container nhận env mới.

## Next steps
1. `docker compose up -d --force-recreate indexer` (và worker nếu cần).
2. Hỏi lại Deep chat: "Liệt kê 10 red flags CRITICAL mục 7.2" — kiểm tra không còn lỗi tool + đủ #1–#10.
3. Commit Phase 6.2 khi user yêu cầu.

## Blockers / Risks
- Indexer phải chạy và load model lần đầu (~vài giây) cho `/api/v1/embeddings`.
- Agent vẫn có thể bỏ sót nếu không gọi đủ `get_section_content` — prompt đã hướng dẫn nhưng không ép cứng bằng code.
