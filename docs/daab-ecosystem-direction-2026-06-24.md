# DAAB — Hướng đi đề xuất & câu hỏi cần CTO chốt (2026-06-24)

> Một trang để CTO review + trả lời. Bối cảnh: BA-033 Slice 1 (chunk-sim retrieval) đã build nhưng **ship-gate NO-GO** (không thêm giá trị vs `/search` trên corpus test); Slice 2 (community detection) **đã defer** (graph quá thưa sau loại concept, 0 consumer hợp lệ, chưa có corpus thật, sai ưu tiên). Cần chốt hướng tiếp.

> **Tiền đề (mandate DAAB)** — theo quyết định CTO `decisions/ecosystem-hermes-allocation` (2026-06-23): DAAB = **keystone owner của shared knowledge substrate** (resolved graph + memory-of-record); **AAAA + LAAM = thin MCP consumer**. DAAB **KHÔNG** ôm document-storage / identity-provider / OCR. Toàn bộ đề xuất + câu hỏi dưới đây bám tiền đề này. **Nếu mandate đã đổi, xin CTO chỉnh dòng này trước** — các câu còn lại sẽ điều chỉnh theo.

## Đề xuất hướng (theo dependency)

| #   | Việc                                                                                                     | Chủ lực       | Ghi chú                                                                                                                       |
| --- | -------------------------------------------------------------------------------------------------------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 0   | **Supabase = shared identity** (AAAA → login Supabase, rồi LAAM)                                         | AAAA + LAAM   | DAAB consume identity đã verify → map sang `user_id`. **Đây là chốt nền.**                                                    |
| 1   | **Memory-of-record P0** (`kg_remember`/`kg_recall`)                                                      | DAAB          | Đúng P0 ecosystem, 3 consumer, không phụ thuộc corpus. Bước 0 gỡ đúng gate khó nhất (secure `user_id` + cross-platform RBAC). |
| 2   | **DAAB doc-sync** (nút sync: kéo doc chưa xử lý từ Supabase → chunk/extract → RAG/graph + **back-link**) | DAAB          | Nhỏ, tái dùng đồ có sẵn (idempotency + provenance). Bonus: **seed corpus thật** cho DAAB.                                     |
| 3   | **BA-033 retrieval / Slice 2**                                                                           | DAAB          | **Chờ corpus từ bước 2** → re-đo density + chạy falsifiability gate → mới quyết.                                              |
| —   | **OCR**                                                                                                  | demand-driven | Chỉ cần **nếu** doc Supabase là scan binary (xem Q3).                                                                         |

**Insight chính:** Supabase identity là **chốt chặn kép** — vừa gỡ gate identity/RBAC của memory-of-record, vừa (qua doc-sync) seed corpus thật → dần mở khóa retrieval/Slice 2. Một quyết định nền đẩy được cả 2 nhánh đang kẹt.

**Đúng mandate DAAB:** knowledge layer (memory + graph + sync-pull text). DAAB **không** ôm document-storage, **không** ôm identity-provider, **không** mặc định cần OCR.

## Câu hỏi cần CTO chốt

1. **Identity:** Xác nhận **Supabase là identity provider dùng chung** (AAAA + LAAM login Supabase) và DAAB consume identity đó làm `user_id`? → đây là tiền đề cho memory user-scope.
2. **Document storage:** Xác nhận **document để ở AAAA/Supabase**, DAAB chỉ **sync text + giữ back-link** (KHÔNG lưu bản sao document trong DAAB)?
3. **OCR — gần như KHÔNG cần (đã có evidence).** Supabase lưu **binary PDF trong Storage buckets** (S3-compatible), nên DAAB sync phải trích text. Test 3 PDF domain thật (release notes / investment thesis Cảng Định An / Nuvei spec) → **đều born-digital text-layer**, `pypdf` trích được hết → **không cần OCR cho loại này**.
   - **Cần CTO xác nhận:** trên bucket thật có lẫn **PDF scan** (vd hợp đồng ký) không? Nếu có → OCR chỉ cho phần scan (PaddleOCR ở DAAB sync **hoặc** AAAA pre-OCR — chốt thuộc ai). Nếu không → bỏ OCR khỏi scope.
   - **Lưu ý kỹ thuật (không phải OCR):** pypdf trích tiếng Việt bị **artifact khoảng trắng/dấu** → sync cần thêm bước **normalize text tiếng Việt** để chunk/extract sạch.
4. **Ưu tiên/sequencing:** OK build **memory-of-record P0 trước** (DAAB chủ lực), **doc-sync fast-follow**? Hay đảo thứ tự?
5. **RBAC isolation (make-or-break):** Chấp nhận dùng **Supabase-verified identity** làm cơ sở scope memory xuyên platform, kèm yêu cầu **threat-model + test** chứng minh PII (`user_profile`) không rò sang platform khác?
6. **Defer xác nhận:** OK **hoãn BA-033 Slice 2 (community) + OCR** tới khi có corpus thật / nhu cầu scan cụ thể (demand-driven)?

## Trạng thái hiện tại của DAAB

**Stack:** Go API (kg-server + kg-bridge MCP + kg-migrate) · Python workers (extraction/resolution/indexing) · PostgreSQL + pgvector · Redis · chạy qua docker-compose. Embedding: multilingual-e5-small 384-dim (CPU).

### ✅ Đã có / đang vận hành
- **Core KG (Phase 1-3):** node/edge CRUD + Gate-1 whitelist, hybrid search (lexical + semantic RRF), traversal/neighbors, users/auth (username-password + Claude OAuth), project management + RBAC, admin sync portal.
- **AI pipeline (Phase 2/4/5):** KG generation, AI provider abstraction (Claude/Haiku, circuit breaker, budget), NL→SQL query, conversational chat + rich rendering.
- **Ingestion (Phase 6):** unified ingestion + draft nodes, file extraction (**pdf text-layer / docx / xlsx / csv / json / md** — **KHÔNG OCR**), document decomposition → chunk + 384-dim embeddings, cross-source linking.
- **Satellite + MCP (Phase 7-8):** standalone code indexer + CLI, MCP bridge **~40 tool `kg_*`** (stdio + Streamable HTTP + Bearer auth), satellite memory recall.
- **BA-031 Entity Resolution: GA** (`apply_mode=apply`) — Pass1 closed-schema extraction + Pass2 resolution (cross-encoder + LLM verify, batch=6), degree-gated auto-merge, reversible un-merge. Vừa fix: chain-drain stale suggestions, status-flip, batch-verify default. Graph cleanup: connected 8%→69% (concept-included), 0 exact-name dup.
- **BA-032:** document navigation + cross-source backlinks (read tools).

### ❌ Chưa có (khớp đề xuất ở trên)
- **Memory-of-record** (`kg_remember`/`kg_recall`) — P0, **chưa bắt đầu**.
- **Consume Supabase identity** (map → `user_id`) — chưa có.
- **Doc-sync từ Supabase** (nút sync + back-link) — chưa có.
- **OCR** — chưa build; **theo mandate chưa cần** (input là born-digital text), chỉ thành nhu cầu nếu nguồn scan (Q3).
- **BA-033 retrieval:** Slice 1 built-but-gated (NO-GO trên corpus test); Slice 2 deferred (xem `decisions/ba033-slice2-deferred`).

### ⚠️ Known issues / nợ kỹ thuật
- **Embed service cold-start ~25s** > timeout server → query đầu sau idle bị 502 (ảnh hưởng cả `/search`). Cần pre-warm hoặc nới timeout.
- **Giá trị retrieval cross-doc chưa chứng minh** — cả Slice 1 (chunk-sim) lẫn Slice 2 (community) đều kẹt vì **chưa có corpus một-domain mạch lạc, đủ lớn** (corpus hiện tại là test lẫn 2 domain). → doc-sync (bước 2) là đường có corpus thật.
- Vài chunk `resolving` tồn (leftover pre-fix, cosmetic).
