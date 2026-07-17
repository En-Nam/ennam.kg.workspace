# DAAB Doc-Sync (Supabase Storage → RAG) — Design Spec (2026-06-26, rev2 post-review)

> **⚠️ SUPERSEDED (connector half) — 2026-07-15.** The **Plan A OCR pipeline** in this spec is DONE and still valid. The **connector half** (Plan B: DAAB reads Supabase Storage directly via broker/scoped-key, single locked "corpus-project", enumerate-by-prefix) is **REPLACED** by `docs/superpowers/specs/2026-07-15-daab-doc-sync-planA-aaaa-endpoint-design.md`. Reason: verified that AAAA's document **metadata** lives in AAAA's own Postgres (not Supabase — only the Storage bucket is), so DAAB pulls metadata via an **AAAA integrations endpoint** + Storage **signed URLs**, mapped **per-project** (not one locked corpus). Future shared-Supabase path tracked in Serena `backlog/daab-doc-sync-planB-future`.
>
> **Status:** DRAFT rev3 — post 2-agent review + user decision. v1 = **combine Tesseract (text) + RapidOCR-latin (structured fields as metadata)**, sample-gated, signed-URL credential, locked corpus project. Awaiting approval before plan.
> **Goal:** Nút **Sync** ở Knowledge Sources kéo PDF scan từ Supabase Storage → OCR local (Tesseract) → VN-normalize → chunk → draft-node → graph + back-link. **Seed corpus** để đánh giá BA-033.
> **Implements:** `decisions/ecosystem-direction-cto-approved-2026-06-24` (DAAB = knowledge layer; sync text + back-link, không lưu document).

---

## 0. Prerequisites (chặn EXECUTION của full-run, không chặn build)

- **Credential đọc Supabase Storage** — REJECT `service_role` (key toàn quyền vào storage M&A bí mật, đứng trong platform riêng = blast-radius lớn). Theo thứ tự ưu tiên:
  1. **(Ưu tiên) Broker signed-URL của AAAA:** AAAA expose 1 endpoint trả **{list object `documents/` + signed-URL per object}**. DAAB **không giữ secret nào**; giải quyết luôn enumerate + download + credential. AAAA giữ quyền sở hữu storage.
  2. **(Fallback) Scoped read-only key** chỉ bucket `documents`, rotatable/revocable bởi AAAA, lưu **AES-256-GCM** (`KG_ENCRYPTION_KEY`).
  3. **Enumerate: REST/broker, KHÔNG cấp DB grant** vào `storage.objects`.
- Supabase URL: `https://nicrcubktflnwdkhotut.supabase.co`.
- **Quan trọng:** credential chỉ chặn **enumerate + download bộ đầy đủ**. Toàn bộ pipeline/UI/OCR/idempotency build + test được trên **10 file mẫu local** ngay (xem §6 sequencing).

## 1. Bối cảnh (verified thực nghiệm)
- Corpus: bucket `documents`, prefix **`documents/<aaaa-user-uuid>/<ts>-<uuid>.pdf`** = **216 PDF / 460MB**. Mẫu 10: **9/10 scan** (JPEG ~200dpi), văn bản pháp lý/tài chính VN (quyết định, giấy CN, mộc/dấu, form xoay). OCR bắt buộc.
- Loại trừ: `users/` (output AAAA), `matches/` (proposals), edge `445e…`. **Chỉ `documents/`.**
- OCR (test thật 3 engine): **Tesseract `vie` giữ dấu VN tốt nhất** (→ text chính); **RapidOCR-latin nhẹ nhất + tốt số/m³/ID** (→ structured fields); PaddleOCR loại (nặng, segfault arm64). → **v1 combine cả 2** (cả 2 đều nhẹ/Apache/arm64 → rẻ), reconcile dạng metadata (không token-merge).

## 2. Non-goals (v1)
- ❌ Lưu file gốc trên DAAB (tải tạm → xoá).
- ❌ **Token-level merge** 2 engine (chỉ Tesseract=text + RapidOCR=fields-as-metadata; tránh fragile reconcile).
- ❌ Extraction-LLM cho structured fields ở v1 (regex trước; LLM = v1.1 nếu regex noisy).
- ❌ service_role / DB grant.
- ❌ Sync output AAAA; auto-sync/webhook; map deal/project AAAA.
- ❌ **General multi-tenant rollout** — v1 chỉ là eval seed vào 1 project khoá admin (xem §3.0 tenancy).
- ❌ Full 216-run trước khi sample-gate qua (xem §6).

## 3. Kiến trúc & luồng (lean v1)

### 3.0 Tenancy (CTO ruling — bắt buộc)
Path span **nhiều user**; user_id metadata KHÔNG phải enforcement. → v1 sync hết vào **1 project chuyên dụng "M&A corpus" khoá quyền admin** (access nắm chặt). `aaaa_user_id` lưu metadata. **KHÔNG ship như feature chung** tới khi user-scope (D3) **enforce ở tầng RBAC**, không chỉ metadata. Plan ghi rõ đây là cổng "eval seed → product".

### 3.1 Flow
```
[Knowledge Sources /projects/{corpus-project}/sources]
 Card "Supabase" → (admin) Connect (broker URL hoặc scoped key, mã hoá, global) → [Connected] → [Sync]
   │ (async, WORKER — tách kg-server live path; nếu chung box: bounded conc 1-2 + off-hours)
   ▼
 1. List documents/ objects (qua broker/REST) chưa-sync (registry key = object_id + ETAG)
 2. PER OBJECT (try/except isolation — 1 file lỗi KHÔNG giết batch):
      a. temp-download /tmp  (try/finally đảm bảo xoá; orphan-sweep lúc worker start)
      b. tiered extract (OCREngine seam):
           - pypdf per-page text-layer + image-coverage check → trang born-digital: dùng text
           - trang scan → render ≥300dpi (pdfium) + deskew/binarize:
               • Tesseract `vie` (tessdata_best, psm, OSD-fallback) → TEXT chính
               • RapidOCR-latin (onnx) → structured fields (regex: số VB, ngày, m³, diện tích, mã số) → METADATA
             page-by-page (giải phóng bitmap), page-cap
      c. VN NFC-normalize (text Tesseract)
      d. XOÁ temp
      e. tạo draft-node: ghi content_raw + content_format NGAY (update_draft_content) → enqueue run_batch
         **bypass** đường handle_extract_upload (đường này đọc lại file từ KG_UPLOAD_DIR → vỡ no-persist)
      f. registry: ghi row {object_id, etag, state=drafted, node_id, project} NGAY (resume-safe)
 → Admin Approve → Process → embed 384-dim → graph node + back-link source_url=storage path (+aaaa_user_id meta)
 → registry state=synced
```

## 4. Components

### 4.1 UI (next, Knowledge Sources)
Card "Supabase" trong SOURCE CONNECTIONS. Connect dialog **admin-only** (broker URL hoặc scoped key) → lưu mã hoá global → [Connected] → nút **Sync** (vào corpus-project). Tiến độ qua stats sẵn có + **per-object log** (reason fail, page count, text-layer-vs-OCR, engine) cho debug batch 216.

### 4.2 Credential (Go, reuse `internal/crypto`)
AES-256-GCM, global, admin set. Broker URL hoặc scoped key. **Không** service_role, **không** DB grant.

### 4.3 Sync handler (Go → enqueue)
`POST /api/v1/projects/{id}/sources/supabase/sync` (admin) → enqueue job. Enumerate qua broker/REST (đệ quy per user-prefix + pagination nếu REST; broker trả sẵn list thì dùng luôn). Diff registry (etag) → list cần xử lý. **Batch + resume bắt buộc** (limit mỗi lần + tiếp tục).

### 4.4 OCR pipeline (Python worker, mở rộng `ingestion/adapters/files.py`)
- **OCREngine seam:** `extract(pdf) -> {text, structured_fields}`.
- Thay `_extract_pdf` thuần-pypdf hiện tại (silently rỗng trên scan) bằng tiered: text-layer probe (**char-count + image-coverage** — tránh false-negative do text-layer rác) → scan → **render ≥300dpi pdfium + deskew/binarize**, rồi **2 engine song song**:
  - **Tesseract `vie` tessdata_best** (psm, OSD fallback) → `text` (chunk/embedding).
  - **RapidOCR-latin** (onnx, lazy-load) → `structured_fields` qua **regex targeted** (số văn bản, ngày, m³, diện tích, mã số) → lưu metadata node. Regex noisy → nâng extraction-LLM (đã wired) ở v1.1.
- **page-by-page streaming + page-cap/timeout** (chống OOM doc 31+ trang). VN NFC-normalize cho `text`. Lazy-load; bounded concurrency.

### 4.5 Idempotency / registry (fix C4/C5)
Bảng `supabase_synced_object`: `object_id` (storage UUID), **`etag`** (change-key, KHÔNG size), `state` (processing|drafted|synced|failed), `node_id`, `project_id`, `failure_reason`, `synced_at`. Row tạo **lúc draft-creation** (resume bỏ qua non-absent). Etag đổi → re-sync.

### 4.6 No-persist (fix C1 + CTO)
Tải `/tmp` → OCR → ghi text vào draft → **xoá temp (`try/finally`)**. **Orphan-sweep** xoá temp sót lúc worker khởi động (crash safety — không để PDF M&A nằm lại). Graph node giữ `source_url` (storage path) — xem bản gốc → signed-URL on-demand. **Không** route vào `KG_UPLOAD_DIR`.

## 5. Decisions (chốt, có review)
- **OCR v1:** combine — Tesseract `vie` (tessdata_best) → text + preprocessing; RapidOCR-latin → structured fields (regex) làm metadata. Cả 2 nhẹ/Apache/arm64. Reconcile = metadata, KHÔNG token-merge.
- **Credential:** signed-URL broker (ưu tiên) / scoped read-only key; **reject service_role + DB grant**.
- **Tenancy:** 1 corpus-project khoá admin; metadata-only user-scope KHÔNG đủ cho general → gated.
- **No-persist:** temp→xoá + try/finally + orphan-sweep.
- **Idempotency:** object_id + etag, mark lúc draft-creation, resumable.
- **Integration:** OCR up-front → ghi content vào draft → bypass file-re-read path.
- **Gate:** sample-first (10 doc → BA-033 sanity) trước full 216.
- **OCR = năng lực chung của file-ingestion** (`files.py`), dùng bởi Local Upload / MCP / Supabase — KHÔNG phải tính năng riêng doc-sync. **KHÔNG microservice** v1 (worker + seam đã đủ cô lập; nếu lo crash onnx → subprocess, không phải service).
- **Tách 2 plan:** **Plan A** = OCR pipeline (build+test NGAY qua Local Upload/MCP trên 10 mẫu, không cần Supabase). **Plan B** = Supabase connector (build sẵn, mock storage để unit-test; E2E gated khi AAAA gắn Supabase + có credential).

## 6. Sequencing (CTO)
1. **Build song song NGAY (không cần credential):** OCR pipeline (Tesseract text + RapidOCR fields) + VN-normalize + idempotency schema + UI card — test trên **10 PDF mẫu local** đã có.
2. **OCR 10 mẫu → chunk → embed → BA-033 sanity check** (corpus có trả lời được query cross-doc không?).
3. **Nếu có giá trị →** xin credential (broker/scoped key) → **chạy full 216** (bounded conc 1-2, resumable, off-hours, isolated khỏi kg-server).
4. Nếu BA-033 yếu → dừng/điều chỉnh trước khi tốn OCR 216.

## 7. Open questions (còn)
- **OQ-1:** AAAA làm được **broker signed-URL** không, hay chỉ cấp scoped key? (quyết §0 + §4.3.)
- **OQ-2:** Worker có **chung box** với kg-server không? Nếu chung → bắt buộc throttle/off-hours cho 216-run.
- **OQ-3 (v2):** structured-field — dùng **extraction-LLM đã wired** (không regex) khi cần.

## 8. Success criteria (v1)
- Pipeline OCR 10 mẫu → text VN có dấu → chunk → embed → graph + back-link, chạy trên local (no credential).
- BA-033 sanity trên 10 mẫu cho tín hiệu (go/no-go full).
- Full-run: idempotent (etag), resumable, per-doc isolation, file gốc KHÔNG còn trên DAAB (orphan-sweep verified).
- Credential không phải service_role; chỉ admin connect; sync vào corpus-project khoá.
- Không ảnh hưởng kg-server live path.

## 9. Out of scope / follow-ups
- Extraction-LLM cho structured fields (v1.1 nếu regex noisy — đã wired sẵn); token-level merge 2 engine.
- General multi-tenant rollout (cần D3 RBAC enforced).
- Auto-sync/webhook; map deal/project AAAA.
- BA-033 retrieval eval đầy đủ (spec riêng, sau seed).

---

## Review incorporated (2026-06-26, 2-agent)
- **Tech consultant:** C1 no-persist↔pipeline (OCR up-front, ghi content vào draft, bypass re-read) · C3 REST non-recursive → broker/SQL + pagination · C4/C5 idempotency etag + mark-at-draft · C6 per-doc try/except + try/finally cleanup · I1 regex→LLM (defer) · I3 DPI/deskew/tessdata_best/psm · I4 image-coverage text-layer check · I5 page-cap streaming · M5 chunker prose-aware OK.
- **CTO:** cut RapidOCR/structured v1 (Tesseract-only, keep seam) · reject service_role → signed-URL broker · cross-tenant → locked corpus-project, not metadata-only · gate full-216 behind 10-doc BA-033 check · build pipeline on samples in parallel · orphan-sweep cleanup · bounded/resumable/off-hours run.

## Verified facts (2026-06-26)
- `documents/` 216 PDF/460MB; path `documents/<aaaa-user-uuid>/...`; owner null.
- 9/10 mẫu scan JPEG DCTDecode ~200dpi; prose pháp lý VN + form xoay.
- OCR: Tesseract dấu tốt nhất; RapidOCR nhẹ+số tốt (defer); PaddleOCR loại (segfault arm64).
- Worker đã có: extraction-LLM (`extraction_ai_client`), draft-node pipeline (`handle_extract_upload` re-reads KG_UPLOAD_DIR — phải bypass), prose-aware chunker, chunk_extraction_state, AES-256-GCM crypto, supabase_user_id (D3).
- public schema rỗng; AAAA metadata ở DB riêng.
