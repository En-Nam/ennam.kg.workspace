# Decision: DAAB ecosystem direction — CTO APPROVED (2026-06-24)

CTO (Danny Tran) reviewed `docs/daab-ecosystem-direction-2026-06-24.md` and approved. Supersedes the earlier "OCR not needed per mandate" stance.

## CTO answers
- **Overall direction: OK** — sequence accepted: Supabase shared identity → memory-of-record P0 (DAAB) → DAAB doc-sync → defer BA-033 retrieval/Slice 2 until a real coherent corpus.
- **Q2 (storage): confirmed** — Supabase stores **original files (binary PDFs)** in Storage buckets (S3-compatible). DAAB does NOT store documents; it syncs + back-links.
- **Q3 (OCR): DAAB NEEDS OCR** — CTO: "đằng nào bên con của em cũng cần OCR." This OVERRIDES my prior analysis (sample of 3 domain PDFs were born-digital text-layer → I had concluded OCR likely unneeded). The real bucket includes scanned docs (M&A contracts etc.); CTO has the full corpus picture. OCR is in DAAB's doc-sync scope.

## Implementation note — OCR is HYBRID, not OCR-everything
DAAB doc-sync text-extraction: pypdf first → if text-layer present, use it (cheap; the born-digital majority); if empty/scanned → OCR. Then **normalize Vietnamese text** (pypdf produced spacing/diacritic artifacts on VN — e.g. "D Ự ÁN C Ả NG"; this is a text-cleanup step, separate from OCR) → chunk → graph + back-link to Supabase Storage URL.

## OCR engine (from research)
- **PaddleOCR = front-runner**: Apache-2.0, CPU-capable (fits stack), markdown/layout, multilingual. **Must verify Vietnamese diacritic quality on real scans before committing.**
- OmniParse: poor fit (GPL-3.0 + mandatory 8-10GB GPU + self-admitted weak non-English).

## Greenlit roadmap (sequence)
1. Supabase shared identity (AAAA → Supabase login, then LAAM); DAAB consumes verified identity → user_id. Unblocks memory-of-record user-scope + cross-platform RBAC.
2. Memory-of-record P0 (DAAB): `kg_remember`/`kg_recall`. (See `mem:decisions/ecosystem-hermes-allocation`.)
3. DAAB doc-sync: pull binary PDF from Supabase Storage (S3) → hybrid pypdf/OCR → VN-normalize → chunk → graph + back-link. Reuses existing ingest + chunk_extraction_state idempotency + source_url provenance.
4. BA-033 retrieval / Slice 2: still deferred (`mem:decisions/ba033-slice2-deferred`) until doc-sync seeds a real coherent corpus → then re-measure density + falsifiability gate.

## Open (still to confirm with AAAA team)
- Whether Supabase document table/bucket has any metadata/text alongside binaries (it's binary in Storage; possible separate PG table for metadata + storage path).
- Supabase "Vectors" feature seen in nav — confirm AAAA isn't already doing RAG there (avoid DAAB↔AAAA RAG duplication).
- Multi-tenant scoping of the Supabase document folders (UUID folders) → maps to DAAB project/RBAC.
