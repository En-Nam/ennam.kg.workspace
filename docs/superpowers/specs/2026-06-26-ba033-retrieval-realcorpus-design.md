# BA-033 Retrieval on Real Corpus — Parent-Child + Entity-Anchored — Design Spec (2026-06-26)

> **Status:** DRAFT — design cho phần SEARCH (sau khi doc-sync Plan A seed corpus thật). Mục tiêu: semantic search **chính xác + ổn định** + quan hệ cross-document (mục tiêu BA-033). Awaiting approval.
> **Depends on:** doc-sync Plan A (seed 216 VN legal M&A PDF → chunk + entity). BA-031 (entity extraction+resolution, GA). BA-033 Slice 1 (`kg_graph_retrieve` + chunk `similar_to`, built; NO-GO trên corpus TEST).

---

## 1. Bối cảnh (vì sao re-đo BA-033)
- **BA-033 Slice 1** (chunk-cosine `similar_to` edges) **NO-GO trên corpus test** (2 domain lẫn lộn, không mạch lạc) → không thêm giá trị vs `/search`. Slice 2 (community) deferred vì graph thưa + thiếu corpus.
- **Giờ có corpus thật**: 216 VN legal M&A docs (công ty/dự án/thửa đất **lặp lại nhiều doc** — vd "Cảng Định An", "Công ty Hàm Giang"). → cross-doc relationship **có cơ sở thật**.
- **Cơ chế cross-doc mạnh nhất = ENTITY (BA-031, đã build)**, không phải chunk-cosine. Doc cùng nhắc 1 entity → pass2 merge → entity canonical chung → docs link qua entity. Chính xác (neo cứng) + ổn định (không phụ ngưỡng cosine mờ).

## 2. Mục tiêu
1. **Re-đo BA-033** trên corpus thật (falsifiability gate) → quyết Slice 1 (chunk-sim) còn dùng không + Slice 2 (community) có cơ sở chưa.
2. **Parent-child (small-to-big) retrieval** — retrieve chunk nhỏ chính xác → trả về **section/parent context** → câu trả lời đầy đủ + ổn định (chunk boundary không xé ý).
3. **Entity-anchored cross-doc retrieval** — query → entity → traverse docs/chunks cùng entity → kết quả cross-doc (đạt mục tiêu BA-033).

## 3. Non-goals
- ❌ Đổi chunker core (đã đúng hybrid structure+recursive; markdownify ở Plan A).
- ❌ Re-build entity extraction (BA-031 GA — tái dùng).
- ❌ LLM-rerank / generation (ngoài scope retrieval; có thể follow-up).
- ❌ Slice 2 community detection (gated — chỉ làm nếu §6 eval cho thấy entity graph đủ dày + có consumer).

## 4. Thiết kế (3 retrieval mode, đo để chọn)

### 4.1 Baseline — flat chunk semantic (`/search` hiện tại)
Query → embed (e5-384) → top-k chunk (hybrid RRF lexical+semantic). Mốc so sánh.

### 4.2 Parent-child (small-to-big) — ĐỘ CHÍNH XÁC + ỔN ĐỊNH
- **Index nhỏ, return lớn:** retrieve top-k **chunk** (precise) → mở rộng mỗi chunk lên **parent `document_section`** (hoặc ±N chunk lân cận cùng section) → dedup theo section → trả **section-level context**.
- Tận dụng hierarchy SẴN CÓ: `document_section`→chunk (`contains_section`, `section_path`). Không cần re-index.
- Lợi: chunk nhỏ → embedding match chính xác; trả section → ngữ cảnh đủ, không phụ thuộc chunk-boundary may rủi → **ổn định**.
- Tunable (đo): chunk size nhỏ hơn (~800-1000 char vs 1800 hiện tại) + overlap ~10-15% → recall/precision (FR-4 Phase 0). Đo qua §6.

### 4.3 Entity-anchored cross-doc — MỤC TIÊU BA-033
- Query → trích/match **entity** (công ty/dự án/người/thửa) → traverse graph: entity → các chunk/doc `mentions` entity đó (xuyên doc) → gom + rank.
- Tái dùng `kg_graph_retrieve` (graph_retriever.go, Slice 1) nhưng **seed bằng entity** (không chỉ chunk-sim): từ chunk hit → entity của nó → chunk khác cùng entity (doc khác) = cross-doc expansion.
- Đây là cách "tạo mối relationship giữa tài liệu" chính xác nhất cho corpus M&A.

### 4.4 Hybrid (đề xuất cuối, đo xác nhận)
Flat semantic (4.1) **+** entity-anchored expansion (4.3) **+** parent-child context (4.2) → RRF fuse. Đo vs từng mode.

## 5. Dùng lại / cần build
| Phần | Trạng thái |
|---|---|
| Chunk + embed + hybrid RRF `/search` | ✅ có |
| `document_section`→chunk hierarchy | ✅ có (decompose) |
| Entity extraction + resolution (BA-031) | ✅ GA |
| `kg_graph_retrieve` (graph_retriever.go) | ✅ Slice 1 (re-purpose entity-seed) |
| chunk `similar_to` edges | ⚠️ Slice 1 NO-GO test — re-đo corpus thật |
| **Parent-child expansion** (retrieve chunk→section) | ❌ build mới (retrieval-side) |
| **Entity-seed expansion** trong graph_retrieve | ❌ build/điều chỉnh |
| **Chunk param tuning** (size/overlap) | ❌ tune qua eval |

## 6. Eval — falsifiability gate (quyết go/no-go từng mode)
- **Benchmark**: dùng BA-033 benchmark questions (có sẵn) trên **corpus thật**; bổ sung câu hỏi cross-doc M&A thật (vd "các dự án liên quan Cảng Định An", "công ty X xuất hiện ở những văn bản nào").
- **Metric**: cross-doc recall@k + precision@k; **marginal value** mỗi mode vs baseline flat (G\B set — như Slice 1 gate). Stability: variance giữa câu hỏi tương tự.
- **Gate**: mode chỉ ship nếu **marginal > 0** vs baseline. Entity-anchored kỳ vọng thắng (corpus entity-rich); parent-child kỳ vọng tăng độ đầy đủ/ổn định.
- Nếu chunk-sim (Slice 1) vẫn marginal=0 trên corpus thật → **bỏ hẳn**, dựa entity. Nếu entity graph đủ dày → mở khóa **Slice 2 community** (re-đánh giá).

## 7. Open questions
- **OQ-1:** Entity-match từ query — exact/alias match (dùng entity resolution alias) hay embed entity? (đề xuất: alias/lexical trước, rẻ.)
- **OQ-2:** Parent-child return granularity — section đầy đủ vs ±N chunk lân cận? (đo; section có thể dài → cap.)
- **OQ-3:** Re-rank sau fuse (cross-encoder đã có ở BA-031) — dùng cho retrieval không? (follow-up, đo trước.)
- **OQ-4:** Chunk size/overlap tối ưu — tune qua §6 eval, không hardcode.

## 8. Sequencing
1. **Gated on Plan A seed** (cần corpus + entity graph). Build song song được: parent-child expansion logic (unit-test với fixture nhỏ); entity-seed graph_retrieve.
2. Seed 10-mẫu (Plan A gate) → eval sơ bộ 3 mode → chọn hướng.
3. Seed full 216 → eval đầy đủ → ship mode thắng + chốt chunk params.
4. (Gated) Slice 2 community nếu entity graph đủ dày.

## 9. Success criteria
- ≥1 retrieval mode (kỳ vọng entity-anchored + parent-child) **marginal > baseline** trên corpus thật (eval §6).
- Cross-doc query (cùng entity) trả kết quả từ **≥2 doc khác nhau** đúng.
- Parent-child: câu trả lời đầy đủ hơn (section context) + ổn định (variance thấp) vs flat-chunk.
- Quyết định rõ: Slice 1 chunk-sim giữ/bỏ; Slice 2 mở/đóng — dựa data.

---

## Verified facts (2026-06-26)
- Pipeline: `parse_markdown_sections` (section theo heading) → `chunk_section` (đoạn, cap 1800, no-overlap) → embed e5-384 → hybrid RRF `/search`.
- `worker.py:220-250`: chunk → `run_pass1` (BA-031 entity) → `run_pass2` (resolution) — cross-doc entity link tự động.
- BA-033 Slice 1: `graph_retriever.go` + chunk `similar_to` (threshold 0.90) — NO-GO corpus test.
- Hierarchy `document_section`→chunk (`contains_section`, `section_path`) — sẵn cho parent-child.
- Corpus thật: 216 VN legal M&A (entity lặp xuyên doc) — chờ Plan A seed.
